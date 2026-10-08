# src/api_summary.py
"""Auswertungen der lokalen HTTP-API (#92), Tk-frei, rein und ohne Socket.

Summen, Kategorien, Wochenlimit, Pausenpflicht und Urlaub für einen Zeitraum
sowie Kategorienliste und Feiertage. Alles läuft über einen `get_all()`-Snapshot,
den der Aufrufer reicht; gerechnet wird in ganzen MINUTEN je Slot (Regel
„Summen NUR über Minuten“ in der Wurzel-`CLAUDE.md`), Dezimalstunden kommen
nirgends vor.

Gespeicherte Slots sind Fremddaten. `Storage` bereinigt sie an der Lese-Grenze
(`storage.sanitize_slot`); was `summarize` trotzdem von einem Aufrufer mit eigenem
Snapshot bekommt, zählt als ungewöhnlicher Slot 0 Minuten und wird geloggt. Das ist
die zweite Linie, kein Ersatz für die erste.
"""
from __future__ import annotations

import calendar
import datetime
import logging
import re
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from src.holidays_de import get_holidays
from src.pause_requirement import check_day_pause
from src.time_utils import calculate_hours, get_week_dates, hours_to_minutes
from src.vacations import cap_by_worktime
from src.weekly_limit import is_limit_active

if TYPE_CHECKING:  # nur für die Signaturen
    from src.settings import SettingsLike

_log = logging.getLogger(__name__)

_DAY_KEY_RE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
_MONTH_RE = re.compile(r"([0-9]{4})-([0-9]{2})")
_WEEK_RE = re.compile(r"([0-9]{4})-W([0-9]{2})")
_YEAR_RE = re.compile(r"[0-9]{4}")

# Darüber liefe `Sonntag = Montag + 6` aus dem darstellbaren Datumsbereich; die
# Routen lehnen ohnehin alles außerhalb 2000–2100 ab.
_MAX_PARSE_YEAR = 9998


def parse_month(raw: str) -> tuple[datetime.date, datetime.date] | None:
    """`YYYY-MM` → (erster, letzter Tag), sonst None. Nur ASCII-Ziffern."""
    match = _MONTH_RE.fullmatch(raw)
    if match is None:
        return None
    year, month = int(match[1]), int(match[2])
    if not 1 <= year <= _MAX_PARSE_YEAR or not 1 <= month <= 12:
        return None
    last_day = calendar.monthrange(year, month)[1]
    return datetime.date(year, month, 1), datetime.date(year, month, last_day)


def parse_week(raw: str) -> tuple[datetime.date, datetime.date] | None:
    """`YYYY-Www` (ISO-Woche) → (Montag, Sonntag), sonst None. Woche 53 gibt es
    nur in manchen Jahren; `fromisocalendar` lehnt die anderen ab."""
    match = _WEEK_RE.fullmatch(raw)
    if match is None:
        return None
    year, week = int(match[1]), int(match[2])
    if not 1 <= year <= _MAX_PARSE_YEAR:
        return None
    try:
        monday = datetime.date.fromisocalendar(year, week, 1)
    except ValueError:
        return None
    return monday, monday + datetime.timedelta(days=6)


def parse_year(raw: str) -> int | None:
    """`YYYY` (vier ASCII-Ziffern) → Jahr, sonst None."""
    return int(raw) if _YEAR_RE.fullmatch(raw) else None


def category_names(settings: SettingsLike) -> list[str]:
    """Die in den Einstellungen konfigurierten Kategorien, in ihrer Reihenfolge,
    ohne Leere und Doppelte. Kategorien, die nur in Ist-Zeiten vorkommen, stehen
    in der Summary unter `by_category`."""
    raw = settings.get("categories")
    if not isinstance(raw, list):
        return []
    names: list[str] = []
    for item in raw:
        if isinstance(item, str) and item.strip() and item not in names:
            names.append(item)
    return names


def holidays_for(settings: SettingsLike, year: int) -> dict[str, Any]:
    """Feiertage des eingestellten Bundeslands. Ohne gesetztes Bundesland ist die
    Liste leer und `state` ist `""` — so unterscheidet der Client „keine
    Feiertage“ von „Bundesland fehlt“ (dieselbe Lücke wie beim Urlaub)."""
    state = settings.get("state")
    if not isinstance(state, str):
        state = ""
    found = get_holidays(state, year)
    return {
        "year": year,
        "state": state,
        "holidays": [{"date": day.isoformat(), "name": name}
                     for day, name in sorted(found.items())],
    }


def _slots_of(entry: Any) -> list[dict[str, Any]]:
    slots = entry.get("slots") if isinstance(entry, dict) else None
    if not isinstance(slots, list):
        return []
    return [slot for slot in slots if isinstance(slot, dict)]


def _slot_minutes(slot: Mapping[str, Any]) -> int:
    try:
        return hours_to_minutes(calculate_hours(
            slot.get("start"), slot.get("end"), slot.get("pause", 0)))
    except (TypeError, ValueError, AttributeError, ArithmeticError) as exc:
        # Kurz und ohne Slot-Inhalt: ein Dashboard fragt alle paar Sekunden, ein
        # ungewöhnlicher Slot dürfte die Log-Rotation sonst in Stunden leerspülen.
        _log.warning("Lokale API: Slot nicht berechenbar, zählt 0 Minuten (%s)",
                     type(exc).__name__)
        return 0


def _day_slots(cache: dict[str, list[tuple[dict[str, Any], int]]],
               entries: Mapping[str, Any], key: str) -> list[tuple[dict[str, Any], int]]:
    """Die Slots eines Tages samt Minuten, je Anfrage einmal berechnet: Tage,
    Kategorien, Wochen und Urlaubskappung teilen sich das Ergebnis (und ein
    ungewöhnlicher Slot loggt nur einmal)."""
    if key not in cache:
        cache[key] = [(slot, _slot_minutes(slot)) for slot in _slots_of(entries.get(key))]
    return cache[key]


def _week_row(iso_year: int, iso_week: int, entries: Mapping[str, Any],
              settings: SettingsLike, cache: dict[str, list[tuple[dict[str, Any], int]]],
              use_limit: bool) -> dict[str, Any]:
    dates = get_week_dates(iso_year, iso_week)
    total = sum(minutes for day in dates
                for _, minutes in _day_slots(cache, entries, day.isoformat()))
    limit = None
    if use_limit and any(is_limit_active(settings, day.isoformat()) for day in dates):
        limit = hours_to_minutes(settings.get("werkstudent_limit_max_hours"))
    return {
        "iso_year": iso_year, "iso_week": iso_week,
        "total_minutes": total, "limit_minutes": limit,
        "exceeded": limit is not None and total > limit,
    }


def _week_rows(weeks: list[tuple[int, int]], entries: Mapping[str, Any],
               settings: SettingsLike,
               cache: dict[str, list[tuple[dict[str, Any], int]]]) -> list[dict[str, Any]]:
    """Eine Zeile je Woche. Die Limit-Einstellungen sind Fremddaten (der Sync prüft
    nur, dass ein Wert da ist; der Einstellungsdialog nimmt auch `inf`): sind sie
    unlesbar, entfällt das Limit für die ganze Anfrage, einmal geloggt."""
    try:
        return [_week_row(year, week, entries, settings, cache, True) for year, week in weeks]
    except (TypeError, ValueError, ArithmeticError) as exc:
        _log.warning("Lokale API: Wochenlimit-Einstellungen nicht lesbar, Limit entfällt (%s)",
                     type(exc).__name__)
        return [_week_row(year, week, entries, settings, cache, False) for year, week in weeks]


def _weeks_in(date_from: datetime.date, date_to: datetime.date) -> list[tuple[int, int]]:
    weeks: list[tuple[int, int]] = []
    day = date_from
    while day <= date_to:
        iso = day.isocalendar()
        if (iso.year, iso.week) not in weeks:
            weeks.append((iso.year, iso.week))
        day += datetime.timedelta(days=1)
    return weeks


def _pause_warnings(settings: SettingsLike,
                    in_range: Mapping[str, Any]) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    for day_key in sorted(in_range):
        try:
            violation = check_day_pause(settings, _slots_of(in_range[day_key]))
        except Exception as exc:
            # Fremddaten (fehlende Felder, falsche Typen): kurz loggen, ohne
            # Traceback, damit ein pollendes Dashboard das Log nicht flutet.
            _log.warning("Lokale API: Pausenpflicht für %s nicht berechenbar (%s)",
                         day_key, type(exc).__name__)
            continue
        if violation is not None:
            found.append({"date": day_key, **violation})
    return found


def _vacation_part(vacation_days: Mapping[str, int], first: str, last: str,
                   work: dict[str, Any]) -> tuple[int, list[dict[str, Any]]]:
    """(Urlaubsminuten nach Kappung, gekappte Tage). Gekappt wird wie in Mail,
    PDF und Webhook gegen die erfasste Ist-Zeit desselben Ausschnitts, damit ein
    Kalendertag nie mehr Stunden hat, als er hat (`vacations.cap_by_worktime`)."""
    days = {key: minutes for key, minutes in vacation_days.items()
            if _DAY_KEY_RE.fullmatch(key) and first <= key <= last
            and isinstance(minutes, int) and not isinstance(minutes, bool)}
    try:
        capped, hits = cap_by_worktime(days, work)
    except Exception:
        _log.exception("Lokale API: Urlaubskappung nicht berechenbar, Urlaub ungekappt")
        capped, hits = dict(days), []
    return sum(capped.values()), [
        {"date": hit.date, "vacation_minutes": hit.vacation,
         "work_minutes": hit.work, "counted_minutes": hit.capped}
        for hit in hits]


def summarize(date_from: datetime.date, date_to: datetime.date,
              entries: Mapping[str, Any], settings: SettingsLike,
              vacation_days: Mapping[str, int]) -> dict[str, Any]:
    """Auswertung für [date_from, date_to] (beide einschließlich) über einen
    `Storage.get_all()`-Snapshot (ohne Tombstones) und den Urlaubs-Snapshot
    `{ISO: Minuten}`. `by_category` ist nach Minuten absteigend sortiert, bei
    Gleichstand nach Name, die leere Kategorie zuletzt (wie im Bericht). `weeks` führt jede ISO-Woche auf, die der Zeitraum
    berührt, mit der Summe der GANZEN Woche — das Wochenlimit gilt für die Woche,
    auch wenn der Monat sie nur teilweise enthält."""
    first, last = date_from.isoformat(), date_to.isoformat()
    in_range = {key: entry for key, entry in entries.items()
                if _DAY_KEY_RE.fullmatch(key) and first <= key <= last
                and _slots_of(entry)}
    cache: dict[str, list[tuple[dict[str, Any], int]]] = {}
    days = []
    by_category: dict[str, int] = {}
    for key in sorted(in_range):
        pairs = _day_slots(cache, entries, key)
        for slot, slot_minutes in pairs:
            name = slot.get("kategorie")
            name = name if isinstance(name, str) else ""
            by_category[name] = by_category.get(name, 0) + slot_minutes
        days.append({"date": key, "minutes": sum(m for _, m in pairs), "slots": len(pairs)})
    total = sum(day["minutes"] for day in days)
    # Die Kappung rechnet gegen die bereits berechneten Minuten (ein Slot je
    # "00:00"–"hh:mm"), nicht gegen die Rohdaten: ein ungewöhnlicher Slot an einem
    # Urlaubstag darf die Kappung der anderen Tage nicht abschalten.
    work = {key: {"slots": [{"start": "00:00", "end": f"{minutes // 60:02d}:{minutes % 60:02d}",
                             "pause": 0} for _, minutes in _day_slots(cache, entries, key)]}
            for key in in_range}
    vacation_minutes, capped_days = _vacation_part(vacation_days, first, last, work)
    return {
        "from": first,
        "to": last,
        "total_minutes": total,
        "vacation_minutes": vacation_minutes,
        "payable_minutes": total + vacation_minutes,
        "vacation_capped_days": capped_days,
        "days": days,
        "by_category": [{"kategorie": name, "minutes": minutes} for name, minutes
                        in sorted(by_category.items(),
                                  key=lambda kv: (-kv[1], kv[0] == "", kv[0]))],
        "weeks": _week_rows(_weeks_in(date_from, date_to), entries, settings, cache),
        "pause_warnings": _pause_warnings(settings, in_range),
    }
