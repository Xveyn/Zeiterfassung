# src/api_summary.py
"""Auswertungen der lokalen HTTP-API (#92), Tk-frei, rein und ohne Socket.

Summen, Kategorien, Wochenlimit, Pausenpflicht und Urlaub für einen Zeitraum
sowie Kategorienliste und Feiertage. Alles läuft über einen `get_all()`-Snapshot,
den der Aufrufer reicht; gerechnet wird in ganzen MINUTEN je Slot (Regel
„Summen NUR über Minuten“ in der Wurzel-`CLAUDE.md`), Dezimalstunden kommen
nirgends vor.

Gespeicherte Slots sind Fremddaten (der Sync validiert ihren Inhalt nicht): ein
Slot mit ungewöhnlichem Inhalt zählt 0 Minuten und wird geloggt, er macht aus
einer lesenden Route keine 500.
"""
from __future__ import annotations

import calendar
import datetime
import re
from typing import TYPE_CHECKING, Any

from src.holidays_de import get_holidays

if TYPE_CHECKING:  # nur für die Signaturen
    from src.settings import SettingsLike

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
