# pyright: reportOptionalMemberAccess=true
"""Reihenfolge der Slots eines Tages (#520).

Pure Logik, Tk-frei. Drei Modi (`slot_order_mode`): `chrono` (Default), `category`
(nach Kategoriename) und `custom` (Listenreihenfolge). Ist-Zeiten werden bei Anzeige,
Ausgabe und — außer in `custom` — beim Speichern so sortiert; Reservierungen nur bei Anzeige und Ausgabe, im Speicher
und im Editor bleiben sie in Listenreihenfolge (`gcal_event_id` und
`send_reminder_minutes` hängen positionsweise am Slot). `ordered` liefert deshalb
den Index der gespeicherten Liste mit: Löschen-Schlüssel (`entry:<index>`)
beziehen sich auf sie, nicht auf die angezeigte Reihenfolge.
"""

from __future__ import annotations

from typing import Any

MODES = ("chrono", "category", "custom")
DEFAULT_MODE = "chrono"

MODE_LABELS = {
    "chrono": "Nach Uhrzeit",
    "category": "Nach Kategorie",
    "custom": "Eigene Reihenfolge",
}

_FOLD = str.maketrans({"ä": "a", "ö": "o", "ü": "u"})


def normalize_mode(value: Any) -> str:
    """Ein Modus aus Einstellungen oder Sync-Antwort; Unbrauchbares gilt als `chrono`."""
    return value if isinstance(value, str) and value in MODES else DEFAULT_MODE


def mode_for_label(label: Any) -> str:
    """Der Modus zur Beschriftung in der Auswahl; Unbekanntes gilt als `chrono`."""
    for mode, text in MODE_LABELS.items():
        if text == label:
            return mode
    return DEFAULT_MODE


def _text(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def fold_name(name: str) -> str:
    """Kategoriename ohne Groß-/Kleinschreibung, ä/ö/ü wie a/o/u, ß wie ss.
    Gleiche Regel in `pwa/slot-order.js`."""
    return name.casefold().translate(_FOLD)


def _key(mode: str, index: int, slot: Any) -> tuple[Any, ...]:
    """Sortierschlüssel. `chrono`: Start, Ende, Kategorie, Position. `category`:
    benannte vor unbenannten Kategorien, Name gefaltet, dann Start, Ende, Position.

    `HH:MM` ist validiert, der Textvergleich entspricht dem Zeitvergleich. Ein
    Slot ohne lesbare Startzeit kommt ans Ende, in Listenreihenfolge — Sortieren
    darf nie Daten verschlucken oder werfen, die es nicht sicher zuordnen kann.
    """
    start = _text(slot.get("start")) if isinstance(slot, dict) else None
    if start is None:
        return (True, "", "", "", "", index)
    end = _text(slot.get("end")) or ""
    kategorie = _text(slot.get("kategorie")) or ""
    if mode == "category":
        return (False, kategorie == "", fold_name(kategorie), start, end, index)
    return (False, start, end, kategorie, "", index)


def ordered(slots: list[Any], mode: str = DEFAULT_MODE) -> list[tuple[int, Any]]:
    """Slots in der Reihenfolge des Modus, jeweils mit ihrem Index in der
    gespeicherten Liste. `custom` ist die gespeicherte Reihenfolge selbst."""
    mode = normalize_mode(mode)
    if mode == "custom":
        return list(enumerate(slots))
    return sorted(enumerate(slots), key=lambda pair: _key(mode, *pair))


def sorted_slots(slots: list[Any], mode: str = DEFAULT_MODE) -> list[Any]:
    """Wie `ordered`, nur die Slots (dieselben Objekte, nichts wird kopiert)."""
    return [slot for _, slot in ordered(slots, mode)]
