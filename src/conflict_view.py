# pyright: reportOptionalMemberAccess=true
"""Anzeige-Modell des Konfliktdialogs — rein, ohne Tk und ohne I/O.

Der Dialog zeigt zwei Stände nebeneinander („Dieses Gerät" gegen ein anderes).
Hier wird entschieden, **was** auf den Karten steht und welche Felder sich
unterscheiden; `dialogs/conflicts_dialog.py` baut daraus nur noch Widgets.
Alle Eingaben stammen aus dem Sync-Doc und sind Fremddaten: ein unlesbares
Feld wird zu einem Platzhalter, nie zu einer Ausnahme.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass
from typing import Any

from src.devices import sanitize_device_name, short_device_id
from src.time_utils import (
    short_day_names, weekday_name, format_iso_date, format_iso_datetime,
)

OWN_TITLE = "Dieses Gerät"
OTHER_TITLE = "Anderes Gerät"
NO_CATEGORY = "ohne Kategorie"
DELETED_TEXT = "Gelöscht"
EMPTY_TEXT = "(leer)"

# Klartext statt Schlüssel. Jeder Eintrag aus `settings.SYNCED_SETTING_KEYS`
# braucht eine Beschriftung (ein Test hält das fest); unbekannte Schlüssel
# zeigt der Dialog roh.
SETTING_LABELS: dict[str, str] = {
    "recipient": "Empfänger",
    "name": "Name",
    "hourly_rate": "Stundenlohn",
    "mail_subject": "Mail-Betreff",
    "mail_greeting": "Mail-Anrede",
    "mail_content": "Mail-Text",
    "mail_closing": "Mail-Grußformel",
    "gcal_calendar_id": "Google Kalender",
    "categories": "Kategorien",
    "category_times": "Standardzeiten der Kategorien",
    "werkstudent_limit_enabled": "Werkstudenten-Limit aktiv",
    "werkstudent_limit_start": "Werkstudenten-Limit Beginn",
    "werkstudent_limit_end": "Werkstudenten-Limit Ende",
    "werkstudent_limit_max_hours": "Werkstudenten-Limit Stunden/Woche",
    "pause_warning_enabled": "Pausenwarnung",
    "workweek_only": "Nur Werktage",
}


@dataclass(frozen=True)
class Field:
    """Ein angezeigter Wert; `differs` färbt ihn als Unterschied."""

    text: str
    differs: bool = False


@dataclass(frozen=True)
class SlotView:
    start: Field
    end: Field
    category: Field
    pause: Field


@dataclass(frozen=True)
class CardView:
    """Eine Karte. `index` ist die Position in `conflict["candidates"]` —
    die Karten sind sortiert (eigenes Gerät zuerst), die Auswahl geht aber
    über den Index des Kandidaten."""

    index: int
    is_own: bool
    title: str
    device_line: str
    modified: str
    newer: bool
    slots: tuple[SlotView, ...] = ()
    deleted: Field | None = None
    value: Field | None = None


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _date_of(key: Any) -> datetime.date | None:
    try:
        return datetime.date.fromisoformat(str(key)[:10])
    except ValueError:
        return None


def setting_label(key: str) -> str:
    return SETTING_LABELS.get(key, key)


def conflict_title(conflict: dict[str, Any]) -> str:
    """„Montag, 01.06.2026" bzw. der Klartextname der Einstellung."""
    key = str(conflict.get("key", ""))
    if conflict.get("kind") == "setting":
        return setting_label(key)
    day = _date_of(key)
    if day is None:
        return key
    return f"{weekday_name(day)}, {format_iso_date(key)}"


def list_label(conflict: dict[str, Any]) -> str:
    """Zeile der Konfliktliste: „Mo, 01.06.2026" bzw. Einstellungsname."""
    key = str(conflict.get("key", ""))
    if conflict.get("kind") == "setting":
        return setting_label(key)
    day = _date_of(key)
    if day is None:
        return key
    return f"{short_day_names()[day.weekday()]}, {format_iso_date(key)}"


def group_conflicts(conflicts: list[dict[str, Any]]
                    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """(Zeiten, Einstellungen), je sortiert: Tage nach Datum, Einstellungen
    nach Beschriftung."""
    entries = [c for c in conflicts if c.get("kind") != "setting"]
    settings = [c for c in conflicts if c.get("kind") == "setting"]
    entries.sort(key=lambda c: str(c.get("key", "")))
    settings.sort(key=list_label)
    return entries, settings


def format_setting_value(key: str, value: Any) -> str:
    if isinstance(value, bool):
        return "an" if value else "aus"
    if value is None or value == "" or value == [] or value == {}:
        return EMPTY_TEXT
    if key in ("werkstudent_limit_start", "werkstudent_limit_end"):
        return format_iso_date(str(value), fallback=str(value))
    if key == "hourly_rate" and isinstance(value, (int, float)):
        return f"{value:.2f}".replace(".", ",") + " €"
    if key == "werkstudent_limit_max_hours" and isinstance(value, (int, float)):
        return f"{value:g} h".replace(".", ",")
    if isinstance(value, list):
        return ", ".join(str(v) for v in value)
    if isinstance(value, dict):
        return ", ".join(str(k) for k in value)
    return str(value)


def _slot_fields(slot: Any) -> tuple[str, str, str, str]:
    s = _as_dict(slot)
    start = str(s.get("start") or "–")
    end = str(s.get("end") or "–")
    category = str(s.get("kategorie") or "").strip() or NO_CATEGORY
    try:
        pause = int(s.get("pause") or 0)
    except (TypeError, ValueError):
        pause = 0
    pause_text = f"Pause {pause} min" if pause else "keine Pause"
    return start, end, category, pause_text


def _slots_of(cand: dict[str, Any]) -> list[Any]:
    slots = cand.get("slots")
    return list(slots) if isinstance(slots, list) else []


def _slot_views(mine: dict[str, Any], other: dict[str, Any]) -> tuple[SlotView, ...]:
    other_slots = [] if other.get("deleted") else _slots_of(other)
    views = []
    for pos, slot in enumerate(_slots_of(mine)):
        own = _slot_fields(slot)
        theirs = _slot_fields(other_slots[pos]) if pos < len(other_slots) else None
        flags = [theirs is None or own[i] != theirs[i] for i in range(4)]
        views.append(SlotView(
            Field(own[0], flags[0]), Field(own[1], flags[1]),
            Field(own[2], flags[2]), Field(own[3], flags[3])))
    return tuple(views)


def _known_name(device_id: Any, registry: Any) -> str:
    if not isinstance(device_id, str) or not isinstance(registry, dict):
        return ""
    return sanitize_device_name(_as_dict(registry.get(device_id)).get("name"))


def _modified(cand: dict[str, Any]) -> str:
    text = format_iso_datetime(cand.get("modified_at"), fallback="")
    return f"geändert {text}" if text else ""


def _stamp(cand: dict[str, Any]) -> str:
    stamp = cand.get("modified_at")
    return stamp if isinstance(stamp, str) else ""


def _titles(device_id: Any, own_device_id: Any, own_name: str,
            registry: Any) -> tuple[bool, str, str]:
    """(is_own, Titel, Zeile darunter)."""
    has_id = isinstance(device_id, str) and bool(device_id)
    short = short_device_id(device_id) if has_id else ""
    if has_id and device_id == own_device_id:
        name = sanitize_device_name(own_name) or _known_name(device_id, registry)
        return True, OWN_TITLE, name or short
    name = _known_name(device_id, registry)
    if name:
        return False, name, ""
    return False, OTHER_TITLE, short


def build_cards(conflict: dict[str, Any], registry: Any,
                own_device_id: Any, own_name: str = "") -> list[CardView]:
    """Die zwei Karten eines Konflikts, das eigene Gerät zuerst."""
    raw = conflict.get("candidates")
    cands = [_as_dict(c) for c in raw] if isinstance(raw, list) else []
    if len(cands) != 2:
        return []
    is_setting = conflict.get("kind") == "setting"
    stamps = [_stamp(c) for c in cands]
    cards = []
    for i, cand in enumerate(cands):
        other = cands[1 - i]
        is_own, title, line = _titles(cand.get("device_id"), own_device_id,
                                      own_name, registry)
        newer = bool(stamps[i]) and stamps[i] > stamps[1 - i]
        key = str(conflict.get("key", ""))
        if is_setting:
            cards.append(CardView(
                i, is_own, title, line, _modified(cand), newer,
                value=Field(format_setting_value(key, cand.get("value")), True)))
        elif cand.get("deleted"):
            cards.append(CardView(
                i, is_own, title, line, _modified(cand), newer,
                deleted=Field(DELETED_TEXT, not other.get("deleted"))))
        else:
            cards.append(CardView(
                i, is_own, title, line, _modified(cand), newer,
                slots=_slot_views(cand, other)))
    cards.sort(key=lambda c: (not c.is_own, c.index))
    return cards
