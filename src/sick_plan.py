# pyright: reportOptionalMemberAccess=true
"""Planung der Krankheitstage — rein, ohne Tk und ohne I/O.

Grundlage der vorbelegten Stunden (`sick_hours_basis`, synchronisiert):
die Standardzeit des Wochentags oder der Durchschnitt der letzten 3 Monate.
"""

from __future__ import annotations

import calendar
import datetime
from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from src.absence import date_range, format_day_list, holiday_dates
from src.settings import WEEKDAY_KEYS
from src.time_utils import calculate_hours, hours_to_minutes

if TYPE_CHECKING:
    from src.settings import SettingsLike

SIX_WEEKS_DAYS = 42
MAX_BLOCK_DAYS = 366
MAX_MINUTES_PER_DAY = 1440

HINT_SIX_WEEKS = (
    "Die Entgeltfortzahlung endet in der Regel nach sechs Wochen; danach "
    "zahlt meist die Krankenkasse. Welche Tage zählen, klärt dein Arbeitgeber.")
HINT_SUGGESTION = (
    "Die Stunden sind ein Vorschlag. Abgerechnet wird beim Arbeitgeber; "
    "Wartezeit und Tarifvertrag kennt die App nicht.")
HINT_AU = (
    "Frag deinen Arbeitgeber, ab wann eine "
    "Arbeitsunfähigkeitsbescheinigung nötig ist.")
HINT_AVERAGE_FALLBACK = (
    "Im Zeitraum davor ist keine Arbeitszeit erfasst; vorbelegt ist die "
    "Standardzeit des Wochentags.")
HINT_SICK_ON_VACATION = (
    "Krankheit im Urlaub zählt hier als Krankheit. Damit die Urlaubstage "
    "gutgeschrieben werden, verlangt der Arbeitgeber in der Regel ein "
    "ärztliches Attest.")

BASES = ("standard", "average_3m")
DEFAULT_BASIS = "standard"

BASIS_LABELS = {
    "standard": "Standardzeit des Wochentags",
    "average_3m": "Durchschnitt der letzten 3 Monate",
}


def normalize_basis(value: object) -> str:
    """Unbrauchbare Werte (auch aus dem Sync) gelten als `standard`."""
    if isinstance(value, str) and value in BASES:
        return value
    return DEFAULT_BASIS


def _slot_minutes(slot: Mapping[str, Any]) -> int:
    """Minuten eines Slots (Spanne minus Pause); ein unlesbarer Slot zählt 0."""
    try:
        return hours_to_minutes(calculate_hours(
            slot.get("start"), slot.get("end"), slot.get("pause", 0)))
    except Exception:
        # Fremddaten aus dem Sync: ein unlesbarer Slot zählt 0
        return 0


def _day_minutes(record: Mapping[str, Any] | None) -> int:
    if not record:
        return 0
    return sum(_slot_minutes(s) for s in record.get("slots") or [])


def reservation_net_minutes(reservation: Mapping[str, Any] | None) -> int:
    """Netto-Minuten einer Reservierung, summiert über ihre Slots."""
    return _day_minutes(reservation)


def standard_minutes(day: datetime.date, settings: SettingsLike) -> int:
    """Standardzeit des Wochentags minus Standardpause, nie negativ."""
    key = WEEKDAY_KEYS[day.weekday()]
    pause = settings.get("default_pause") or 0
    return _slot_minutes({
        "start": settings.get(f"default_start_{key}"),
        "end": settings.get(f"default_end_{key}"),
        "pause": pause if isinstance(pause, int) else 0,
    })


def _first_worked_day(entries: Mapping[str, Any]) -> datetime.date | None:
    best: datetime.date | None = None
    for key, record in entries.items():
        if not isinstance(key, str) or not record or not record.get("slots"):
            continue
        try:
            day = datetime.date.fromisoformat(key)
        except ValueError:
            continue
        if best is None or day < best:
            best = day
    return best


def reference_period(first_day: datetime.date, entries: Mapping[str, Any]
                     ) -> tuple[datetime.date, datetime.date] | None:
    """Drei Monate vor `first_day` bis zum Vortag, frühestens ab dem ersten
    Tag mit Ist-Zeit; `None`, wenn davon nichts übrig bleibt."""
    month = first_day.month - 3
    year = first_day.year
    if month < 1:
        month += 12
        year -= 1
    day = min(first_day.day, calendar.monthrange(year, month)[1])
    start = datetime.date(year, month, day)
    end = first_day - datetime.timedelta(days=1)
    first_worked = _first_worked_day(entries)
    if first_worked is None:
        return None
    start = max(start, first_worked)
    if start > end:
        return None
    return start, end


def average_minutes(first_day: datetime.date, *, entries: Mapping[str, Any],
                    vacation_days: Mapping[str, int],
                    sick_days: Mapping[str, int], state: str) -> int | None:
    """Arbeitstäglicher Durchschnitt der Ist-Zeit im Referenzzeitraum.

    Zähler: alle Tage, Wochenende eingeschlossen; Nenner: Mo–Fr ohne
    Feiertage. Tage mit Urlaubs- oder Krankheitsminuten fallen aus beiden.
    """
    period = reference_period(first_day, entries)
    if period is None:
        return None
    days = date_range(period[0].isoformat(), period[1].isoformat())
    holidays = holiday_dates(days, state)
    total = 0
    workdays = 0
    for day in days:
        iso = day.isoformat()
        if vacation_days.get(iso, 0) > 0 or sick_days.get(iso, 0) > 0:
            continue
        total += _day_minutes(entries.get(iso))
        if day.weekday() < 5 and day not in holidays:
            workdays += 1
    if not total or not workdays:
        return None
    return min(MAX_MINUTES_PER_DAY, total // workdays)


@dataclass(frozen=True)
class Prefill:
    days: dict[str, int]
    basis_used: str
    hints: list[str]


def prefill(date_from: str, date_to: str, *, basis: str,
            entries: Mapping[str, Any],
            reservations: Mapping[str, Any] | None,
            vacation_days: Mapping[str, int], sick_days: Mapping[str, int],
            settings: SettingsLike) -> Prefill:
    """Vorbelegte Minuten je Kalendertag (Reihenfolge: Reservierung,
    Wochenende/Feiertag, Grundlage). `reservations` ist `None`, wenn
    Reservierungen nicht aktiv sind."""
    basis = normalize_basis(basis)
    days = date_range(date_from, date_to)
    state = settings.get("state") or ""
    hints: list[str] = []
    average: int | None = None
    if basis == "average_3m" and days:
        average = average_minutes(
            days[0], entries=entries, vacation_days=vacation_days,
            sick_days=sick_days, state=state)
        if average is None:
            basis = DEFAULT_BASIS
            hints.append(HINT_AVERAGE_FALLBACK)
    holidays = holiday_dates(days, state)
    out: dict[str, int] = {}
    for day in days:
        iso = day.isoformat()
        reserved = (reservations or {}).get(iso)
        if reserved and reserved.get("slots"):
            out[iso] = reservation_net_minutes(reserved)
        elif day.weekday() >= 5 or day in holidays:
            out[iso] = 0
        elif basis == "average_3m" and average is not None:
            out[iso] = average
        else:
            out[iso] = standard_minutes(day, settings)
    return Prefill(out, basis, hints)


def plan_sick_save(date_from: str, date_to: str, prefilled: Mapping[str, int],
                   overrides: Mapping[str, int]) -> dict[str, Any]:
    """Tagesminuten eines Krankheitsblocks aus Vorbelegung und Überschreibungen.

    Liefert {"error": str | None, "days": {ISO: minutes}}; Fehler sind
    erwartete Eingabefehler, der Aufrufer zeigt sie themed.
    """
    if date_to < date_from:
        return {"error": "Das Bis-Datum liegt vor dem Von-Datum.", "days": {}}
    n = (datetime.date.fromisoformat(date_to)
         - datetime.date.fromisoformat(date_from)).days + 1
    if n > MAX_BLOCK_DAYS:
        return {"error": (f"Ein Krankheitszeitraum darf höchstens "
                          f"{MAX_BLOCK_DAYS} Tage umfassen."), "days": {}}
    days = {d: m for d, m in prefilled.items()}
    for day, minutes in overrides.items():
        if day in days:
            days[day] = max(0, int(minutes))
    over = sorted(d for d, m in days.items() if m > MAX_MINUTES_PER_DAY)
    if over:
        return {"error": ("Für diese Tage sind mehr als 24 Stunden "
                          "eingetragen:\n\n" + format_day_list(over)),
                "days": {}}
    return {"error": None, "days": days}


def work_blocking_days(days: Mapping[str, int],
                       entries: Mapping[str, Any]) -> list[str]:
    """Krankheitstage mit Minuten > 0, an denen schon Ist-Zeit liegt."""
    return sorted(d for d, m in days.items()
                  if m > 0 and (entries.get(d) or {}).get("slots"))


def sick_blocking_vacation(vacation_days: Mapping[str, int],
                           sick_days: Mapping[str, int]) -> list[str]:
    """Tage, an denen Urlaub und Krankheit beide Minuten > 0 tragen."""
    return sorted(d for d, m in sick_days.items()
                  if m > 0 and vacation_days.get(d, 0) > 0)


def block_hints(days: Mapping[str, int]) -> list[str]:
    hints = [HINT_SUGGESTION]
    if len(days) > SIX_WEEKS_DAYS:
        hints.insert(0, HINT_SIX_WEEKS)
    return hints
