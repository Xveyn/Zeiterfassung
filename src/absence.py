# pyright: reportOptionalMemberAccess=true
"""Gemeinsamer Zeitraum-Kern für Urlaub und Krankheit: Tage eines Zeitraums,
Feiertage, Minuten-Verteilung und die Kappung gegen erfasste Ist-Zeit."""

from __future__ import annotations

import datetime
from dataclasses import dataclass
from typing import Any

from src.holidays_de import get_holidays
from src.time_utils import (
    calculate_hours, format_iso_date, hours_to_minutes,
)


def date_range(date_from: str, date_to: str) -> list[datetime.date]:
    """Alle Kalendertage von `date_from` bis `date_to` (inklusive). Leere
    Liste, wenn `date_to` vor `date_from` liegt."""
    start = datetime.date.fromisoformat(date_from)
    end = datetime.date.fromisoformat(date_to)
    if end < start:
        return []
    return [start + datetime.timedelta(days=i)
            for i in range((end - start).days + 1)]


def holiday_dates(days: list[datetime.date], state: str) -> set[datetime.date]:
    """Feiertage über den (ggf. jahresübergreifenden) Zeitraum. Ohne
    Bundesland liefert get_holidays ein leeres Dict — dann gilt kein Tag als
    Feiertag."""
    out: set[datetime.date] = set()
    for year in {d.year for d in days}:
        out |= set(get_holidays(state, year))
    return out


def apportion_minutes(total: int, n: int) -> list[int]:
    """Verteilt `total` Minuten auf `n` Tage so, dass die Summe EXAKT `total`
    ergibt.

    `total // n` für alle, die ersten `total % n` bekommen eine Minute mehr.
    Die Alternative — je Tag Dezimalstunden runden — ergäbe bei 40 h auf 6
    Tage 40,02 h und bei 40 h auf 7 Tage 39,97 h; genau der Fehler, den
    CLAUDE.md für den Footer beschreibt. So summiert sich stattdessen jeder
    Teilbericht exakt zum Ganzen.
    """
    if n <= 0:
        return []
    base, rest = divmod(total, n)
    return [base + 1 if i < rest else base for i in range(n)]


@dataclass(frozen=True)
class CappedDay:
    """Ein Tag, an dem Urlaub auf erfasste Ist-Zeit trifft.

    `minutes` sind die ursprünglichen Minuten der Abwesenheit (Urlaub oder
    Krankheit) am Tag, `work` die an ihm erfasste Arbeitszeit, `capped` der
    verbleibende Rest. `vacation` ist der Name für den Urlaubsfall.
    """

    date: str
    minutes: int
    work: int
    capped: int

    @property
    def vacation(self) -> int:
        return self.minutes


def cap_by_worktime(day_minutes: dict[str, int],
                    entries: dict[str, Any]
                    ) -> tuple[dict[str, int], list[CappedDay]]:
    """Kappt die Urlaubsminuten je Tag um die an ihm erfasste Ist-Zeit
    (Untergrenze 0) und meldet die betroffenen Tage.

    Gegenstück zu `conflicting_days`: die schließt den Zustand an den
    UI-Eingängen aus, diese Funktion räumt auf, wo er trotzdem entsteht.
    `Storage` kennt den Urlaub nicht, deshalb schreiben zwei Wege an der
    Sperre vorbei — der Import geteilter Arbeitszeiten (der Absender kennt
    den Urlaub des Empfängers nicht) und der Drive-Sync eines zweiten Geräts
    (Urlaub ist gerätelokal). Ohne Kappung landeten beide Werte additiv in
    „Zu vergüten gesamt“, ein Kalendertag käme also auf mehr Stunden, als er
    hat (Xveyn#97).

    Gekappt wird zugunsten des Urlaubs: der Tag bleibt bei seinem
    Urlaubswert, die erfasste Arbeitszeit wird darin aufgezehrt. Die App
    entscheidet damit nicht, welche der beiden Zahlen die richtige ist — der
    Tag ist schlicht falsch erfasst, und die Hinweiszeile im Zeitraum-Picker
    sowie die Fußnote im Bericht sagen das auch.

    Tage OHNE Urlaubsminuten bleiben unberührt: Wochenenden und Feiertage
    stehen mit 0 in der Periode und dürfen Arbeitszeit tragen — dieselbe
    Ausnahme, die `conflicting_days` macht.

    `entries` ist der bereits zeitraum- und kategoriegefilterte Ausschnitt,
    den der Bericht auch anzeigt: nur so gehen dort Ist-Zeit, Urlaub und
    „Zu vergüten gesamt“ zusammen auf. Gerechnet wird über MINUTEN je Slot
    (CLAUDE.md, Abschnitt „Stunden“), dieselbe Auflösung wie
    `report._week_block` und `webhook.total_minutes`.

    Returns (gekappte Tagesminuten, betroffene Tage chronologisch).
    """
    capped = dict(day_minutes)
    hits = []
    for date_str in sorted(day_minutes):
        minutes = day_minutes[date_str]
        if not minutes:
            continue
        work = sum(
            hours_to_minutes(calculate_hours(
                slot.get("start"), slot.get("end"), slot.get("pause", 0)))
            for slot in entries.get(date_str, {}).get("slots", []))
        if not work:
            continue
        capped[date_str] = max(0, minutes - work)
        hits.append(CappedDay(date_str, minutes, work, capped[date_str]))
    return capped, hits


# Ab wie vielen betroffenen Tagen der Hinweis nur noch die Zahl nennt: eine
# Datumsliste über einen ganzen Urlaubsmonat wäre in der einzeiligen
# Hinweiszeile des Zeitraum-Pickers nicht mehr lesbar.
_MAX_LISTED_DAYS = 3


def cap_notice(hits: list[CappedDay], kind: str = "vacation") -> str:
    """Ein Satz über die von `cap_by_worktime` gekappten Tage, oder "".

    `kind` ist `"vacation"` oder `"sick"`. Gemeinsame Formulierung für die
    Hinweiszeile im Zeitraum-Picker und die Fußnote im Bericht — beide sagen
    dasselbe, und zwar wortgleich. Datumsangaben deutsch (CLAUDE.md), Stunden
    im selben Dezimalformat wie der Rest des Berichts.
    """
    if not hits:
        return ""

    gekuerzt = round(sum(h.minutes - h.capped for h in hits) / 60, 2)
    if kind == "sick":
        if len(hits) == 1:
            wo = f"An 1 Tag ({format_iso_date(hits[0].date)})"
            satz = f"die Krankheitsstunden sind dort um {gekuerzt}h gekürzt."
        else:
            liste = (f" ({', '.join(format_iso_date(h.date) for h in hits)})"
                     if len(hits) <= _MAX_LISTED_DAYS else "")
            wo = f"An {len(hits)} Tagen{liste}"
            satz = (f"die Krankheitsstunden sind dort um insgesamt "
                    f"{gekuerzt}h gekürzt.")
        return f"{wo} ist Arbeitszeit erfasst; {satz}"

    if len(hits) == 1:
        wo = f"An 1 Tag ({format_iso_date(hits[0].date)})"
        satz = ("Der Urlaub ist dort um "
                f"{gekuerzt}h gekürzt, damit der Tag nicht doppelt zählt.")
    else:
        liste = (f" ({', '.join(format_iso_date(h.date) for h in hits)})"
                 if len(hits) <= _MAX_LISTED_DAYS else "")
        wo = f"An {len(hits)} Tagen{liste}"
        satz = (f"Der Urlaub ist dort um insgesamt {gekuerzt}h gekürzt, "
                f"damit die Tage nicht doppelt zählen.")
    return f"{wo} liegt Urlaub auf erfasster Arbeitszeit. {satz}"


def format_day_list(days: list[str], limit: int = 8) -> str:
    """Die kollidierenden Tage als deutsche Datumsliste, ab `limit` gekürzt.

    Ein dreiwöchiger Urlaub über einem vollen Monat Arbeitszeit ergäbe sonst
    eine Fehlermeldung, die aus dem Bildschirm läuft.
    """
    shown = [format_iso_date(d) for d in days[:limit]]
    rest = len(days) - len(shown)
    if rest > 0:
        shown.append(f"… und {rest} weitere")
    return "\n".join(shown)
