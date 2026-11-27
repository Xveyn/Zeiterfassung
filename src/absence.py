# pyright: reportOptionalMemberAccess=true
"""Gemeinsamer Zeitraum-Kern für Urlaub und Krankheit: Tage eines Zeitraums,
Feiertage, Minuten-Verteilung und die Kappung gegen erfasste Ist-Zeit."""

from __future__ import annotations

import datetime
from dataclasses import dataclass
from typing import Any, Literal

from src.holidays_de import get_holidays
from src.time_utils import calculate_hours, format_iso_date, hours_to_minutes


def date_range(date_from: str, date_to: str) -> list[datetime.date]:
    """Alle Kalendertage von `date_from` bis `date_to` (inklusive). Leere
    Liste, wenn `date_to` vor `date_from` liegt.

    Wirft `ValueError` bei einem Wert, der kein ISO-Datum ist. Eine
    Längengrenze gibt es hier nicht: Aufrufer prüfen das 366-Tage-Limit vorher.
    """
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
    """Ein Tag, an dem eine Abwesenheit (Urlaub oder Krankheit) auf erfasste
    Ist-Zeit trifft.

    `minutes` sind die ursprünglichen Abwesenheitsminuten des Tages, `work`
    die an ihm erfasste Arbeitszeit, `capped` der verbleibende Rest.
    """

    date: str
    minutes: int
    work: int
    capped: int

    @property
    def vacation(self) -> int:
        """Für die Urlaubs-Aufrufer (`api_summary`); neuer Code liest
        `minutes`. Keine Aussage über die Art der Abwesenheit."""
        return self.minutes


def cap_by_worktime(day_minutes: dict[str, int],
                    entries: dict[str, Any]
                    ) -> tuple[dict[str, int], list[CappedDay]]:
    """Kappt die Abwesenheitsminuten je Tag um die dort erfasste Ist-Zeit
    (Untergrenze 0).

    Tage mit 0 Abwesenheitsminuten bleiben unberührt, sie dürfen Arbeitszeit
    tragen. `entries` ist der bereits zeitraum- und kategoriegefilterte
    Ausschnitt, den die Ausgabe zeigt; gerechnet wird in Minuten je Slot.
    Begründung für Urlaub: Wurzel-`CLAUDE.md`, „Urlaub: Periode als Einheit,
    Stunden pro Tag“ (`cap_by_worktime`).

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
# Datumsliste über einen ganzen Monat Abwesenheit wäre in der einzeiligen
# Hinweiszeile des Zeitraum-Pickers nicht mehr lesbar.
_MAX_LISTED_DAYS = 3


def _where(dates: list[str]) -> str:
    """„An 1 Tag (01.09.2026)“ bzw. „An 2 Tagen (…)“; ab dem vierten Tag ohne
    Datumsliste."""
    if len(dates) == 1:
        return f"An 1 Tag ({format_iso_date(dates[0])})"
    liste = (f" ({', '.join(format_iso_date(d) for d in dates)})"
             if len(dates) <= _MAX_LISTED_DAYS else "")
    return f"An {len(dates)} Tagen{liste}"


def cap_notice(hits: list[CappedDay],
               kind: Literal["vacation", "sick"] = "vacation") -> str:
    """Ein Satz über die von `cap_by_worktime` gekappten Tage, oder "".

    `kind` ist `"vacation"` oder `"sick"`, alles andere wirft `ValueError`.
    Gemeinsame Formulierung für die Hinweiszeile im Zeitraum-Picker und die
    Fußnote im Bericht — beide sagen dasselbe, und zwar wortgleich. Stunden im
    selben Dezimalformat wie der Rest des Berichts.
    """
    if kind not in ("vacation", "sick"):
        raise ValueError(f"unbekannte Art der Abwesenheit: {kind!r}")
    if not hits:
        return ""

    gekuerzt = round(sum(h.minutes - h.capped for h in hits) / 60, 2)
    wo = _where([h.date for h in hits])
    einzeln = len(hits) == 1
    if kind == "sick":
        wie = "" if einzeln else "insgesamt "
        return (f"{wo} ist Arbeitszeit erfasst; "
                f"die Krankheitsstunden sind dort um {wie}{gekuerzt}h gekürzt.")
    if einzeln:
        satz = (f"Der Urlaub ist dort um {gekuerzt}h gekürzt, "
                f"damit der Tag nicht doppelt zählt.")
    else:
        satz = (f"Der Urlaub ist dort um insgesamt {gekuerzt}h gekürzt, "
                f"damit die Tage nicht doppelt zählen.")
    return f"{wo} liegt Urlaub auf erfasster Arbeitszeit. {satz}"


@dataclass(frozen=True)
class AbsenceCut:
    """Urlaub und Krankheit nach „Krankheit gewinnt“ und Kappung durch Ist-Zeit.

    `vacation`/`sick` enthalten alle Eingabetage (gekappt), `*_capped` die von
    der Kappung betroffenen Tage, `sick_on_vacation` die Tage (ISO, sortiert),
    an denen Urlaubsminuten unter einem Krankheitstag auf 0 gesetzt wurden.
    """

    vacation: dict[str, int]
    sick: dict[str, int]
    vacation_capped: list[CappedDay]
    sick_capped: list[CappedDay]
    sick_on_vacation: list[str]


def cut_absences(entries: dict[str, Any], vacation_days: dict[str, int],
                 sick_days: dict[str, int]) -> AbsenceCut:
    """Rechnet Urlaub und Krankheit auf einen Ausschnitt gegeneinander und
    gegen die Ist-Zeit ab; die Eingaben bleiben unverändert.

    `sick_days` sind nur lebende Krankheitstage. Jeder davon, auch mit 0
    Minuten, setzt Urlaubsminuten > 0 desselben Tages auf 0: ein Kalendertag
    zählt nie als beides. Danach kappt `cap_by_worktime` erst die Krankheit,
    dann den bereits genullten Urlaub.
    """
    vacation = dict(vacation_days)
    sick_on_vacation = sorted(
        d for d in sick_days if vacation.get(d, 0) > 0)
    for date_str in sick_on_vacation:
        vacation[date_str] = 0
    sick, sick_capped = cap_by_worktime(sick_days, entries)
    vacation, vacation_capped = cap_by_worktime(vacation, entries)
    return AbsenceCut(vacation, sick, vacation_capped, sick_capped,
                      sick_on_vacation)


def cut_for_output(entries: dict[str, Any], vacation_days: dict[str, int],
                   sick_days: dict[str, int] | None) -> AbsenceCut:
    """Urlaub und Krankheit für eine Ausgabe (Bericht, Webhook, Vorschau,
    Leer-Prüfung); die Eingaben sind schon auf Zeitraum und Kategorien
    gefiltert.

    `sick_days=None` heißt Häkchen „Krankheit ausweisen“ aus: dann nur die
    Kappung des Urlaubs (`cap_by_worktime`), ohne jeden Krankheitstag, damit
    die Ausgabe bitgleich bleibt und Krankheit nirgends durchscheint. Mit
    Dict (auch leer) `cut_absences`.
    """
    if sick_days is None:
        vacation, vacation_capped = cap_by_worktime(vacation_days, entries)
        return AbsenceCut(vacation, {}, vacation_capped, [], [])
    return cut_absences(entries, vacation_days, sick_days)


def sick_on_vacation_notice(dates: list[str]) -> str:
    """Ein Satz über Krankheitstage, die im Urlaub lagen, oder ""."""
    if not dates:
        return ""
    if len(dates) == 1:
        return (f"{_where(dates)} lag Krankheit im Urlaub; "
                f"dieser Tag zählt als Krankheit.")
    return (f"{_where(dates)} lag Krankheit im Urlaub; "
            f"diese Tage zählen als Krankheit.")


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
