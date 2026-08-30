"""Urlaubsperioden: reine Regeln und JSON-Persistenz.

Urlaub ist ein eigenständiges Konzept neben Ist-Zeiten (`storage.py`) und
Reservierungen (`reservations.py`). Gespeichert wird die **Periode** als
Record mit Identität — sie trägt einen (nur lokal sichtbaren) Namen, ein
Kalender-Event und wird als Einheit gelöscht. Die Tagesminuten liegen in ihr:

    {period_id: {name, from, to, days: {ISO: minutes},
                 gcal_event_id, modified_at, deleted}}

`days` deckt JEDEN Kalendertag von `from` bis `to` ab, lückenlos — daraus
folgt „Urlaub gewinnt" im Kalender ohne weitere Rangfolge-Regel. Wochenenden
und Feiertage stehen mit 0 Minuten darin: sichtbar als Urlaub, aber ohne
Stunden.

Werte sind **Minuten** (CLAUDE.md: Summen nie über Dezimalstunden). Der Store
reist NICHT per Drive-Sync und trägt daher — wie `reservations.py` — kein
`device_id`-Feld.
"""

from __future__ import annotations

import datetime
from typing import Any

from src.holidays_de import get_holidays

# JSON-getragener Record (Audit N8): Werte sind heterogen → Any.
Vacation = dict[str, Any]


def _date_range(date_from: str, date_to: str) -> list[datetime.date]:
    """Alle Kalendertage von `date_from` bis `date_to` (inklusive). Leere
    Liste, wenn `date_to` vor `date_from` liegt."""
    start = datetime.date.fromisoformat(date_from)
    end = datetime.date.fromisoformat(date_to)
    if end < start:
        return []
    return [start + datetime.timedelta(days=i)
            for i in range((end - start).days + 1)]


def _holiday_dates(days: list[datetime.date], state: str) -> set[datetime.date]:
    """Feiertage über den (ggf. jahresübergreifenden) Zeitraum. Ohne
    Bundesland liefert get_holidays ein leeres Dict — dann gilt kein Tag als
    Feiertag."""
    out: set[datetime.date] = set()
    for year in {d.year for d in days}:
        out |= set(get_holidays(state, year))
    return out


def expand_days(date_from: str, date_to: str, minutes_per_day: int,
                state: str) -> dict[str, int]:
    """Baut {ISO: minutes} über ALLE Kalendertage von `date_from` bis
    `date_to`.

    Wochenenden (Sa/So) und Feiertage des Bundeslands `state` bekommen 0 —
    sie sind ohnehin frei und sollen keine Urlaubsstunden tragen. Sie bleiben
    aber im Dict, damit der Kalender den Zeitraum durchgehend einfärben kann.
    """
    days = _date_range(date_from, date_to)
    holidays = _holiday_dates(days, state)
    return {
        d.isoformat(): (
            0 if (d.weekday() >= 5 or d in holidays) else minutes_per_day
        )
        for d in days
    }


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


def periods_overlap(periods: dict[str, Vacation], period_id: str | None,
                    date_from: str, date_to: str) -> str | None:
    """Prüft, ob [date_from, date_to] eine bestehende Periode schneidet.

    Datums-Pendant zu `time_utils.slots_overlap`. Liefert den Namen der
    kollidierenden Periode oder None. `period_id` ist die gerade bearbeitete
    Periode — sie darf sich nicht mit sich selbst überschneiden. Tombstones
    zählen nicht mit.
    """
    for pid, period in periods.items():
        if pid == period_id or period.get("deleted"):
            continue
        if period.get("from", "") <= date_to and date_from <= period.get("to", ""):
            return period.get("name", "")
    return None


def total_minutes(day_minutes: dict[str, int]) -> int:
    """Summe über Minuten — die einzige erlaubte Summenbildung (CLAUDE.md)."""
    return sum(day_minutes.values())
