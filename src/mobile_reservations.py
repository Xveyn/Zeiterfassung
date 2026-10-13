# src/mobile_reservations.py
"""Reservierungen im Abgleich mit dem Handy (PR 2/3 von „Reservierungen ohne Google“),
Tk-frei und ohne I/O.

Zwei Dinge liegen hier, beide für `mobile_sync`:

- `parse_reservations`: der Teil `reservations` der Anfrage ist **Fremddaten**. Die
  Slot-Regeln sind die der Ist-Zeiten (`api_entry_write.parse_slots`); übernommen
  werden nur `start`, `end`, `kategorie` — `pause` gibt es bei Reservierungen nicht,
  `gcal_event_id` und `send_reminder_minutes` gehören dem Desktop und werden vom
  Slot-Parser als unbekannte Felder abgelehnt.
- `build_reservations`: die Antwort aus dem Store, nur aktive Tage von heute bis
  heute + `HORIZON_DAYS`, in derselben Form wie die Anfrage.

Den Merge macht `ReservationStore.merge_phone`; der Fehler hier ist ein
`ReservationError`, den `mobile_sync` in `SyncError(422, "invalid_entry", …)` übersetzt
(ein eigener Fehlercode brauchte einen Eintrag in `pwa/test/fixtures/errors.json`).
"""
from __future__ import annotations

import datetime
import re
from collections.abc import Callable, Mapping
from typing import Any

from src.api_entry_write import WriteError, parse_slots

MAX_RESERVATIONS = 400
HORIZON_DAYS = 365

_DATE_RE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
_CLOCK_RE = re.compile(r"([01]\d|2[0-3]):[0-5]\d")
_ECHO_MAX = 40


class ReservationError(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


def _label(date: object) -> str:
    # `ascii()` escaped auch Surrogate: die Meldung bleibt als UTF-8 schreibbar.
    return ascii(date)[1:-1][:_ECHO_MAX]


def _parse_day(date: str, raw: object, *, today: datetime.date, now_dt: datetime.datetime,
               parse_utc: Callable[[object], datetime.datetime | None],
               skew_limit: datetime.timedelta) -> dict[str, Any]:
    label = _label(date)

    def bad(reason: str) -> ReservationError:
        return ReservationError(f"Reservierung {label}: {reason}")

    if not _DATE_RE.fullmatch(date):
        raise bad("Datum muss YYYY-MM-DD sein.")
    try:
        day = datetime.date.fromisoformat(date)
    except ValueError:
        raise bad("kein gültiges Datum.") from None
    if not today <= day <= today + datetime.timedelta(days=HORIZON_DAYS):
        raise bad(f"nur von heute bis {HORIZON_DAYS} Tage voraus erlaubt.")
    if not isinstance(raw, dict):
        raise bad("Eintrag muss ein Objekt sein.")
    deleted = raw.get("deleted")
    if not isinstance(deleted, bool):
        raise bad("deleted muss true oder false sein.")
    modified = parse_utc(raw.get("modified_at"))
    if modified is None:
        raise bad("modified_at muss YYYY-MM-DDTHH:MM:SSZ sein.")
    if modified - now_dt > skew_limit:
        raise bad("modified_at liegt in der Zukunft.")
    slots_raw = raw.get("slots")
    if not isinstance(slots_raw, list):
        raise bad("slots muss eine Liste sein.")
    slots: list[dict[str, Any]] = []
    if deleted:
        if slots_raw:
            raise bad("Ein gelöschter Tag darf keine Slots tragen.")
    else:
        if not slots_raw:
            raise bad("Ein Tag ohne Slots ist gelöscht (deleted: true).")
        try:
            parsed = parse_slots(slots_raw)
        except WriteError as error:
            raise bad(error.message) from None
        slots = [{"start": s["start"], "end": s["end"], "kategorie": s["kategorie"]}
                 for s in parsed]
    return {"slots": slots, "modified_at": str(raw["modified_at"]), "deleted": deleted}


def parse_reservations(raw: object, *, today: datetime.date, now_dt: datetime.datetime,
                       parse_utc: Callable[[object], datetime.datetime | None],
                       skew_limit: datetime.timedelta) -> dict[str, dict[str, Any]]:
    """`reservations` der Anfrage → geprüfte Tage `{ISO: {slots, modified_at, deleted}}`.
    Wirft `ReservationError`; dann wurde nichts angewendet. `today` ist das lokale Datum
    des Desktops, `now_dt` seine UTC-Zeit."""
    if not isinstance(raw, dict):
        raise ReservationError("reservations muss ein Objekt sein.")
    if len(raw) > MAX_RESERVATIONS:
        raise ReservationError(f"Höchstens {MAX_RESERVATIONS} Reservierungstage je Anfrage.")
    # Unbekannte Felder am Tag (z. B. `device_id`) entfallen still, wie bei Ist-Zeiten.
    return {date: _parse_day(date, entry, today=today, now_dt=now_dt, parse_utc=parse_utc,
                             skew_limit=skew_limit)
            for date, entry in raw.items()}


def _clean_slots(raw: object) -> list[dict[str, str]]:
    """Gespeicherte Slots sind Fremddaten (Handbearbeitung, Kalender-Abgleich): nur die
    drei Felder des Protokolls, und nur mit gültiger Uhrzeit."""
    if not isinstance(raw, list):
        return []
    slots = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        start, end = item.get("start"), item.get("end")
        if not (isinstance(start, str) and _CLOCK_RE.fullmatch(start)
                and isinstance(end, str) and _CLOCK_RE.fullmatch(end)):
            continue
        category = item.get("kategorie")
        slots.append({"start": start, "end": end,
                      "kategorie": category if isinstance(category, str) else ""})
    return slots


def build_reservations(store_raw: Mapping[str, Any], *,
                       today: datetime.date) -> dict[str, dict[str, Any]]:
    """Alle aktiven Tage von heute bis heute + `HORIZON_DAYS`, sortiert. Tombstones und
    Tage ohne brauchbare Slots entfallen — ein Tag, der fehlt, löscht ihn in der PWA nur
    im Zukunftsfenster, ein Tombstone wäre dafür unnötig."""
    first = today.isoformat()
    last = (today + datetime.timedelta(days=HORIZON_DAYS)).isoformat()
    out: dict[str, dict[str, Any]] = {}
    for date in sorted(store_raw):
        entry = store_raw[date]
        if not (isinstance(date, str) and _DATE_RE.fullmatch(date) and first <= date <= last):
            continue
        if not isinstance(entry, dict) or entry.get("deleted") is True:
            continue
        slots = _clean_slots(entry.get("slots"))
        if not slots:
            continue
        out[date] = {"slots": slots, "modified_at": str(entry.get("modified_at") or ""),
                     "deleted": False}
    return out
