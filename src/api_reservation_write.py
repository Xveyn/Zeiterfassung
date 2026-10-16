# src/api_reservation_write.py
"""Schreibpfad der lokalen API für Reservierungen (#239, PR 6), Tk-frei und ohne Socket.

Wie `api_entry_write` nimmt dieses Modul **Fremddaten** (der Body kommt von einem
Skript). Die Slot-Regeln sind die der Ist-Zeiten (`api_entry_write.parse_slots`);
dazu kommt, was nur Reservierungen kennen:

- kein `pause` (Reservierungen haben keine Pause-Spalte) und nie `gcal_event_id`
  (die Kalender-IDs gehören dem Abgleich);
- `send_reminder_minutes`: ganze Zahl 0–120 oder `null`, höchstens an **einem**
  Slot je Tag (die Sende-Erinnerung hängt an genau einem Slot);
- Reservierungen sind zukünftige Soll-Zeiten: heute bis heute + `HORIZON_DAYS`,
  dieselbe Grenze wie im Handy-Abgleich (`mobile_reservations`).

Der Parser meldet zusätzlich, ob **irgendein** Slot `send_reminder_minutes`
überhaupt nennt: ein Skript, das nur Zeiten kennt, soll die Erinnerung des Nutzers
nicht überschreiben (die Route übernimmt dann den bisherigen Wert positionsweise,
wie der Store es mit den Kalender-IDs tut).
"""
from __future__ import annotations

import datetime
from typing import Any

from src.api_entry_write import (
    MAX_SLOTS, WriteError, load_json_body, parse_slots,
)
from src.mobile_reservations import HORIZON_DAYS

__all__ = ["HORIZON_DAYS", "check_reservation_day", "parse_reservation_body"]

_REMINDER_KEY = "send_reminder_minutes"
_MAX_REMINDER = 120


def _parse_reminder(value: Any, index: int) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= _MAX_REMINDER:
        raise WriteError(422, "invalid_reminder",
                         f"Slot {index}: send_reminder_minutes muss eine ganze Zahl "
                         f"von 0 bis {_MAX_REMINDER} oder null sein.")
    return value


def parse_reservation_body(body: bytes) -> tuple[list[dict[str, Any]], bool]:
    """Body → (geprüfte Slots `{start, end, kategorie, send_reminder_minutes}`,
    `reminder_given`). Wirft `WriteError`: 400 bei kaputtem JSON oder falscher Form,
    422 bei ungültigem Slot."""
    data = load_json_body(body)
    if not isinstance(data, dict) or set(data) != {"slots"} or not isinstance(data["slots"], list):
        raise WriteError(400, "invalid_body", 'Erwartet wird {"slots": [...]}.')
    raw = data["slots"]
    if not raw:
        raise WriteError(422, "empty_slots",
                         "Eine leere Slot-Liste speichert nichts — zum Löschen DELETE benutzen.")
    if len(raw) > MAX_SLOTS:
        raise WriteError(422, "too_many_slots", f"Höchstens {MAX_SLOTS} Slots je Tag.")

    reminders: list[int | None] = []
    reminder_given = False
    plain: list[Any] = []
    for index, item in enumerate(raw, start=1):
        if not isinstance(item, dict):
            raise WriteError(422, "invalid_slot", f"Slot {index} muss ein Objekt sein.")
        if "pause" in item:
            raise WriteError(422, "invalid_slot",
                             f"Slot {index}: Reservierungen haben keine Pause.")
        reminder_given = reminder_given or _REMINDER_KEY in item
        reminders.append(_parse_reminder(item.get(_REMINDER_KEY), index))
        plain.append({key: value for key, value in item.items() if key != _REMINDER_KEY})
    if sum(1 for value in reminders if value is not None) > 1:
        raise WriteError(422, "invalid_reminder",
                         "send_reminder_minutes darf an höchstens einem Slot je Tag stehen.")

    parsed = parse_slots(plain)
    slots = [{"start": slot["start"], "end": slot["end"], "kategorie": slot["kategorie"],
              _REMINDER_KEY: reminder}
             for slot, reminder in zip(parsed, reminders, strict=True)]
    return slots, reminder_given


def check_reservation_day(day: datetime.date, today: datetime.date) -> None:
    """Reservierungen sind per Definition zukünftige Soll-Zeiten. Das Jahr prüft
    `api_entry_write.check_date_range` vorher; `today` ist das lokale Datum."""
    if day < today:
        raise WriteError(422, "date_in_past",
                         "Reservierungen gibt es nur für heute und die Zukunft. "
                         "Vergangene Zeiten gehören als Ist-Zeit nach /v1/entries.")
    if day > today + datetime.timedelta(days=HORIZON_DAYS):
        raise WriteError(422, "date_too_far",
                         f"Reservierungen sind nur bis {HORIZON_DAYS} Tage im Voraus möglich.")
