# pyright: reportOptionalMemberAccess=true
"""Planung der Krankheitstage, ohne Tk.

Rein bis auf `commit_sick_block`: das schreibt über die übergebenen Stores
den Krankheitsblock und löscht danach Reservierungen.

Grundlage der vorbelegten Stunden (`sick_hours_basis`, synchronisiert):
die Standardzeit des Wochentags oder der Durchschnitt der letzten 3 Monate.
"""

from __future__ import annotations

import calendar
import datetime
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from src.absence import date_range, format_day_list, holiday_dates
from src.settings import WEEKDAY_KEYS
from src.sick_days import MAX_MINUTES, runs
from src.time_utils import calculate_hours, hours_to_minutes

if TYPE_CHECKING:
    from src.settings import SettingsLike
    from src.sick_days import SickStore

SIX_WEEKS_DAYS = 42
MAX_BLOCK_DAYS = 366
MAX_MINUTES_PER_DAY = MAX_MINUTES

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

RESERVATION_CHECK_TEXT = "Reservierungen in diesem Zeitraum löschen"
RESERVATION_CHECK_TEXT_NEW_DAYS = (
    "Reservierungen an den neu krank gemeldeten Tagen löschen")

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


def basis_changed(chosen: object, initial: object) -> bool:
    """Ob der Dialog eine andere Grundlage gewählt hat als die beim Öffnen.
    Nur dann rechnen gespeicherte Tage neu und wird `sick_hours_basis`
    geschrieben; ein inzwischen per Sync geänderter Wert bleibt sonst."""
    return normalize_basis(chosen) != normalize_basis(initial)


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


def reference_period(first_day: datetime.date, entries: Mapping[str, Any],
                     today: datetime.date | None = None
                     ) -> tuple[datetime.date, datetime.date] | None:
    """Drei Monate vor dem Anker bis zum Vortag, frühestens ab dem ersten Tag
    mit Ist-Zeit; `None`, wenn davon nichts übrig bleibt. Anker ist der
    frühere von `first_day` und `today` (`None` = heute): Tage, die noch
    nicht stattgefunden haben, zählten sonst als Arbeitstage mit 0 Minuten."""
    anchor = min(first_day, today or datetime.date.today())
    month = anchor.month - 3
    year = anchor.year
    if month < 1:
        month += 12
        year -= 1
    day = min(anchor.day, calendar.monthrange(year, month)[1])
    start = datetime.date(year, month, day)
    end = anchor - datetime.timedelta(days=1)
    first_worked = _first_worked_day(entries)
    if first_worked is None:
        return None
    start = max(start, first_worked)
    if start > end:
        return None
    return start, end


def average_minutes(first_day: datetime.date, *, entries: Mapping[str, Any],
                    vacation_days: Mapping[str, int],
                    sick_days: Mapping[str, int], state: str,
                    today: datetime.date | None = None) -> int | None:
    """Arbeitstäglicher Durchschnitt der Ist-Zeit im Referenzzeitraum.

    Zähler: alle Tage, Wochenende eingeschlossen; Nenner: Mo–Fr ohne
    Feiertage. Tage mit Urlaubs- oder Krankheitsminuten fallen aus beiden.
    """
    period = reference_period(first_day, entries, today)
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
            settings: SettingsLike,
            today: datetime.date | None = None) -> Prefill:
    """Vorbelegte Minuten je Kalendertag (Reihenfolge: Reservierung,
    Wochenende/Feiertag, Grundlage). `entries` ist die Sicht von
    `Storage.get_all()`, `reservations` die lebende von
    `ReservationStore.get_all()` (ohne Tombstones) oder `None`, wenn
    Reservierungen nicht aktiv sind. Wirft `ValueError` bei einem Datum
    ohne ISO-Form; Datum und 366-Tage-Limit prüft der Aufrufer vorher."""
    basis = normalize_basis(basis)
    days = date_range(date_from, date_to)
    state = settings.get("state") or ""
    hints: list[str] = []
    fell_back = False
    uses_basis = False
    average: int | None = None
    if basis == "average_3m" and days:
        average = average_minutes(
            days[0], entries=entries, vacation_days=vacation_days,
            sick_days=sick_days, state=state, today=today)
        if average is None:
            basis = DEFAULT_BASIS
            fell_back = True
    holidays = holiday_dates(days, state)
    out: dict[str, int] = {}
    for day in days:
        iso = day.isoformat()
        reserved = (reservations or {}).get(iso)
        if reserved and reserved.get("slots"):
            out[iso] = min(MAX_MINUTES_PER_DAY,
                           reservation_net_minutes(reserved))
        elif day.weekday() >= 5 or day in holidays:
            out[iso] = 0
        elif basis == "average_3m" and average is not None:
            out[iso] = average
        else:
            uses_basis = True
            out[iso] = standard_minutes(day, settings)
    if fell_back and uses_basis:
        hints.append(HINT_AVERAGE_FALLBACK)
    return Prefill(out, basis, hints)


def plan_sick_save(date_from: str, date_to: str, prefilled: Mapping[str, int],
                   overrides: Mapping[str, int]) -> dict[str, Any]:
    """Tagesminuten eines Krankheitsblocks aus Vorbelegung und Überschreibungen.

    Liefert {"error": str | None, "days": {ISO: minutes}}; Fehler sind
    erwartete Eingabefehler, der Aufrufer zeigt sie themed. Der Aufrufer
    übergibt geprüfte ISO-Daten und ganzzahlige Minuten.
    """
    if date_to < date_from:
        return {"error": "Das Bis-Datum liegt vor dem Von-Datum.", "days": {}}
    n = (datetime.date.fromisoformat(date_to)
         - datetime.date.fromisoformat(date_from)).days + 1
    if n > MAX_BLOCK_DAYS:
        return {"error": (f"Ein Krankheitszeitraum darf höchstens "
                          f"{MAX_BLOCK_DAYS} Tage umfassen."), "days": {}}
    days = {d.isoformat(): prefilled.get(d.isoformat(), 0)
            for d in date_range(date_from, date_to)}
    for day, minutes in overrides.items():
        if day in days:
            days[day] = max(0, int(minutes))
    over = sorted(d for d, m in days.items() if m > MAX_MINUTES_PER_DAY)
    if over:
        return {"error": (f"Für diese Tage sind mehr als "
                          f"{MAX_MINUTES_PER_DAY // 60} Stunden "
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


def touches_vacation(days: Mapping[str, int],
                     vacation_days: Mapping[str, int]) -> bool:
    """Ob der geplante Block einen Urlaubstag mit Minuten > 0 überdeckt, mit
    wie vielen Krankheitsminuten auch immer: jeder lebende Krankheitstag setzt
    den Urlaub dort auf 0 (`absence.cut_absences`)."""
    return any(vacation_days.get(d, 0) > 0 for d in days)


def vacation_sick_conflicts(plan_days: Mapping[str, int],
                            sick_days: Mapping[str, int],
                            existing_days: Mapping[str, int] | None = None,
                            ) -> list[str]:
    """Tage, die ein Urlaub neu über einen Krankheitstag (Minuten > 0) legt.
    Beim Bearbeiten (`existing_days`) sperrt ein Tag nicht, den der Urlaub
    schon mit Minuten > 0 abdeckte: Krankheit im Urlaub ist erlaubt, nur
    das Neu-Überdecken nicht."""
    covered = existing_days or {}
    return [d for d in sick_blocking_vacation(plan_days, sick_days)
            if covered.get(d, 0) <= 0]


def block_hints(days: Mapping[str, int]) -> list[str]:
    """Hinweise zum Block; `days` ist der Block nach dem Speichern
    (`resulting_block_days`), nicht nur die gerade geplanten Tage."""
    hints = [HINT_SUGGESTION]
    if len(days) > SIX_WEEKS_DAYS:
        hints.insert(0, HINT_SIX_WEEKS)
    return hints


def resulting_block_days(days: Mapping[str, int],
                         sick_days: Mapping[str, int]) -> dict[str, int]:
    """Der Block nach dem Speichern: die geplanten Tage plus die lebenden
    Krankheitstage, die lückenlos an sie anschließen; geplante Werte gewinnen.
    `sick_days` ist der Bestand ohne die Tage des bearbeiteten Blocks (die
    schreibt das Speichern neu oder macht sie zu Tombstones). Eine Meldung,
    die einen bestehenden Block verlängert, zählt so mit dessen Tagen."""
    if not days:
        return {}
    merged = {**sick_days, **days}
    out: dict[str, int] = {}
    for first, last in runs(merged):
        if any(first <= d <= last for d in days):
            for day in date_range(first, last):
                out[day.isoformat()] = merged[day.isoformat()]
    return out


def reservation_dates_in(days: Mapping[str, int],
                         reservations: Mapping[str, Any] | None) -> list[str]:
    """Tage des Blocks, an denen Reservierungs-Slots liegen."""
    if not reservations:
        return []
    return sorted(d for d in days if (reservations.get(d) or {}).get("slots"))


def reservation_dates_to_offer(days: Mapping[str, int],
                               reservations: Mapping[str, Any] | None,
                               sick_dates: Iterable[str]) -> list[str]:
    """Reservierungstage, deren Löschen das Speichern anbietet: nur Tage, die
    vor diesem Speichern kein Krankheitstag waren. `sick_dates` sind die
    lebenden Krankheitstage davor (ein Mapping zählt mit seinen Schlüsseln).
    Die Reservierungen eines schon kranken Tages hat der Nutzer beim
    Krankmelden bewusst stehen lassen, wie dessen Minuten
    (`stored_overrides`)."""
    covered = set(sick_dates)
    return [d for d in reservation_dates_in(days, reservations)
            if d not in covered]


def reservation_check_text(days: Mapping[str, int],
                           sick_dates: Iterable[str]) -> str:
    """Beschriftung des Häkchens: „in diesem Zeitraum“ stimmt nur, solange
    kein geplanter Tag schon krank war (`reservation_dates_to_offer`)."""
    covered = set(sick_dates)
    if any(d in covered for d in days):
        return RESERVATION_CHECK_TEXT_NEW_DAYS
    return RESERVATION_CHECK_TEXT


class ReservationDeleteError(Exception):
    """Der Krankheitsblock ist geschrieben, aber nicht alle Reservierungen
    ließen sich löschen; `deleted` nennt die bereits gelöschten Tage, der
    Grund steht in `__cause__` (`OSError` ist erwartet, alles andere nicht)."""

    def __init__(self, deleted: list[str]) -> None:
        super().__init__("Reservierungen nicht vollständig gelöscht")
        self.deleted = deleted


def commit_sick_block(sick_store: SickStore, reservation_store: Any, *,
                      old_dates: Iterable[str], days: dict[str, int],
                      delete_reservations: bool) -> list[str]:
    """Schreibt den Block und löscht danach, nur auf Wunsch, die Reservierungen
    der Tage, die vorher kein Krankheitstag waren (`reservation_dates_to_offer`,
    gelesen vor dem Schreiben; die alten Tage des Blocks zählen immer als
    krank). Die Minuten wurden vorher geplant, die Reservierungen dürfen erst
    jetzt wegfallen. Liefert die gelöschten Reservierungstage.

    Ein Fehler beim Schreiben des Blocks wirft unverändert (der Block steht
    dann nicht); jeder Fehler danach wird zu `ReservationDeleteError` (der
    Block steht dann schon)."""
    old = list(old_dates)
    sick_before = set(sick_store.day_minutes()).union(old)
    if old:
        sick_store.replace_block(old, days)
    else:
        sick_store.save_range(days)
    if not delete_reservations or reservation_store is None:
        return []
    deleted: list[str] = []
    try:
        for date in reservation_dates_to_offer(
                days, reservation_store.get_all(), sick_before):
            reservation_store.delete(date)
            deleted.append(date)
    except Exception as e:
        # Weitergeworfen, nicht geschluckt: der Aufrufer muss wissen, dass
        # der Block schon steht, um trotzdem zu schließen und neu zu zeichnen.
        raise ReservationDeleteError(deleted) from e
    return deleted


def stored_overrides(date_from: str, date_to: str,
                     sick_days: Mapping[str, int],
                     edit_block_days: Mapping[str, int] | None = None,
                     ) -> dict[str, int]:
    """Gespeicherte Überschreibungen im Zeitraum (ISO-Daten, Vergleich als
    Text): die Tage des bearbeiteten Blocks und jeder lebende Krankheitstag
    darin, der Store zuletzt (er ist frischer als der Block beim Öffnen). Ein
    bestehender Krankheitstag behält so seine Minuten, auch wenn ein neuer
    Zeitraum ihn überdeckt; neu rechnet ihn nur ein Wechsel der Grundlage
    (`edit_overrides`)."""
    out = {d: m for d, m in (edit_block_days or {}).items()
           if date_from <= d <= date_to}
    out.update({d: m for d, m in sick_days.items()
                if date_from <= d <= date_to})
    return out


def edit_overrides(stored: Mapping[str, int], edited: Mapping[str, int], *,
                   basis_changed: bool) -> dict[str, int]:
    """Überschreibungen des Dialogs: die gespeicherten Werte
    (`stored_overrides`), solange die Grundlage unverändert ist, darüber die
    in diesem Dialog von Hand geänderten Tage. Mit gewechselter Grundlage
    rechnen die gespeicherten Tage neu, nur die von Hand geänderten bleiben."""
    out = {} if basis_changed else dict(stored)
    out.update(edited)
    return out
