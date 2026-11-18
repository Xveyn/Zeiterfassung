# pyright: reportOptionalMemberAccess=true
"""Reihenfolge der Slots eines Tages (#520).

Pure Logik, Tk-frei. Gespeichert wird die Liste in der Reihenfolge, in der sie
kommt; sortiert wird erst bei Anzeige und Ausgabe. Die Position im Speicher ist
an anderer Stelle bedeutsam (bei Reservierungen hängen `gcal_event_id` und
`send_reminder_minutes` positionsweise am Slot), deshalb liefert `ordered` den
ursprünglichen Index mit: Löschen-Schlüssel (`entry:<index>`) beziehen sich auf
die gespeicherte Liste, nicht auf die angezeigte.
"""

from __future__ import annotations

from typing import Any


def _text(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _key(index: int, slot: Any) -> tuple[bool, str, str, str, int]:
    """Sortierschlüssel `chrono`: Start, Ende, Kategorie, Listenposition.

    `HH:MM` ist validiert, der Textvergleich entspricht dem Zeitvergleich. Ein
    Slot ohne lesbare Startzeit kommt ans Ende — Sortieren darf nie Daten
    verschlucken oder werfen, die es nicht sicher zuordnen kann.
    """
    if not isinstance(slot, dict):
        return (True, "", "", "", index)
    start = _text(slot.get("start"))
    end = _text(slot.get("end")) or ""
    kategorie = _text(slot.get("kategorie")) or ""
    return (start is None, start or "", end, kategorie, index)


def ordered(slots: list[Any]) -> list[tuple[int, Any]]:
    """Slots chronologisch, jeweils mit ihrem Index in der gespeicherten Liste."""
    return sorted(enumerate(slots), key=lambda pair: _key(*pair))


def sorted_slots(slots: list[Any]) -> list[Any]:
    """Wie `ordered`, nur die Slots (dieselben Objekte, nichts wird kopiert)."""
    return [slot for _, slot in ordered(slots)]
