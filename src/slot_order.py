# pyright: reportOptionalMemberAccess=true
"""Reihenfolge der Slots eines Tages (#520).

Pure Logik, Tk-frei. Ist-Zeiten werden bei Anzeige, Ausgabe und beim Speichern
chronologisch sortiert; Reservierungen nur bei Anzeige und Ausgabe, im Speicher
und im Editor bleiben sie in Listenreihenfolge (`gcal_event_id` und
`send_reminder_minutes` hängen positionsweise am Slot). `ordered` liefert deshalb
den Index der gespeicherten Liste mit: Löschen-Schlüssel (`entry:<index>`)
beziehen sich auf sie, nicht auf die angezeigte Reihenfolge.
"""

from __future__ import annotations

from typing import Any


def _text(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _key(index: int, slot: Any) -> tuple[bool, str, str, str, int]:
    """Sortierschlüssel `chrono`: Start, Ende, Kategorie, Listenposition.

    `HH:MM` ist validiert, der Textvergleich entspricht dem Zeitvergleich. Ein
    Slot ohne lesbare Startzeit kommt ans Ende, in Listenreihenfolge — Sortieren darf nie Daten
    verschlucken oder werfen, die es nicht sicher zuordnen kann.
    """
    start = _text(slot.get("start")) if isinstance(slot, dict) else None
    if start is None:
        return (True, "", "", "", index)
    return (False, start, _text(slot.get("end")) or "", _text(slot.get("kategorie")) or "", index)


def ordered(slots: list[Any]) -> list[tuple[int, Any]]:
    """Slots chronologisch, jeweils mit ihrem Index in der gespeicherten Liste."""
    return sorted(enumerate(slots), key=lambda pair: _key(*pair))


def sorted_slots(slots: list[Any]) -> list[Any]:
    """Wie `ordered`, nur die Slots (dieselben Objekte, nichts wird kopiert)."""
    return [slot for _, slot in ordered(slots)]
