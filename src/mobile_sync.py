# src/mobile_sync.py
"""Fachlicher Kern von `POST /v1/sync` der Handy-Erfassung (#221), Tk-frei, ohne Socket.

Drei Dinge liegen hier:

- `parse_request`: der Body vom Handy ist **Fremddaten**. Er wird mit denselben
  Regeln wie `PUT /v1/entries` geprüft (`api_entry_write`), dazu Datum, Zeitstempel,
  Tag-Obergrenze und die Uhr. Eine Ablehnung ist ein `SyncError`; dann wurde
  nichts angewendet.
- `build_response`: die Antwort aus dem Merge-Ergebnis (Lesefenster, offene
  Konflikte). Rein.
- `perform_sync`: Guard und Lock, `sync.merge` mit dem Handy als `local`, die
  journalisierte Anwendung. Token, Gerätedatensatz und `last_pull_at` des Handys
  gehören der Route: sie kommen als Parameter herein, die Antwort enthält
  `token`/`expires_at` **nicht**.

Es gibt keinen Merge in JavaScript und keinen zweiten hier: Konfliktlogik bleibt
`sync.merge`.
"""
from __future__ import annotations

import datetime
import re
from dataclasses import dataclass
from typing import Any

from src.api_entry_write import WriteError, check_date_range, load_json_body, parse_slots

PROTOCOL = 1
WINDOW_DAYS = 90
MAX_ENTRIES = 400
# LWW vertraut `modified_at`: eine falsche Uhr würde echte Einträge überschreiben.
CLOCK_SKEW_LIMIT = datetime.timedelta(minutes=15)

_TIME_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
# Nur ASCII-Ziffern: `\d` matcht auch andere Schriften.
_TIME_RE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z")
_DATE_RE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
_ECHO_MAX = 40


class SyncError(Exception):
    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


@dataclass(frozen=True)
class SyncRequest:
    client_time: str
    # {date: {slots, modified_at, deleted}} — bewusst ohne `device_id`: die setzt
    # `perform_sync` aus dem Token, nie aus dem Body.
    entries: dict[str, dict[str, Any]]


def _parse_utc(text: object) -> datetime.datetime | None:
    if not isinstance(text, str) or not _TIME_RE.fullmatch(text):
        return None
    try:
        return datetime.datetime.strptime(text, _TIME_FORMAT)
    except ValueError:
        return None


def _parse_entry(date: str, raw: object, now_dt: datetime.datetime) -> dict[str, Any]:
    # `ascii()` escaped auch Surrogate: die Meldung bleibt als UTF-8 schreibbar.
    label = ascii(date)[1:-1][:_ECHO_MAX]

    def bad(reason: str) -> SyncError:
        return SyncError(422, "invalid_entry", f"{label}: {reason}")

    if not _DATE_RE.fullmatch(date):
        raise bad("Datum muss YYYY-MM-DD sein.")
    try:
        day = datetime.date.fromisoformat(date)
    except ValueError:
        raise bad("kein gültiges Datum.") from None
    try:
        check_date_range(day)
    except WriteError as error:
        raise bad(error.message) from None
    if not isinstance(raw, dict):
        raise bad("Eintrag muss ein Objekt sein.")
    deleted = raw.get("deleted")
    if not isinstance(deleted, bool):
        raise bad("deleted muss true oder false sein.")
    modified = _parse_utc(raw.get("modified_at"))
    if modified is None:
        raise bad("modified_at muss YYYY-MM-DDTHH:MM:SSZ sein.")
    if modified - now_dt > CLOCK_SKEW_LIMIT:
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
            slots = parse_slots(slots_raw)
        except WriteError as error:
            raise bad(error.message) from None
    return {"slots": slots, "modified_at": str(raw["modified_at"]), "deleted": deleted}


def parse_request(body: bytes, *, now: str) -> SyncRequest:
    """Body → geprüfte Einträge. `now` ist die Desktop-Zeit (UTC-Text). Wirft `SyncError`."""
    try:
        data = load_json_body(body)
    except WriteError as error:
        raise SyncError(400, "invalid_json", error.message) from None
    if not isinstance(data, dict):
        raise SyncError(400, "invalid_json", "Erwartet wird ein JSON-Objekt.")
    protocol = data.get("protocol")
    if not isinstance(protocol, int) or isinstance(protocol, bool) or protocol != PROTOCOL:
        raise SyncError(400, "invalid_protocol", f"Unterstützt wird protocol {PROTOCOL}.")
    client = _parse_utc(data.get("client_time"))
    if client is None:
        raise SyncError(400, "invalid_json",
                        "client_time fehlt oder ist kein UTC-Zeitstempel (YYYY-MM-DDTHH:MM:SSZ).")
    raw_entries = data.get("entries", {})
    if not isinstance(raw_entries, dict):
        raise SyncError(400, "invalid_json", "entries muss ein Objekt sein.")
    now_dt = datetime.datetime.strptime(now, _TIME_FORMAT)
    # Die Uhr zuerst: ein vorgehendes Handy trägt Zukunftsstempel, und „modified_at
    # liegt in der Zukunft" wäre dann die irreführende der beiden Meldungen.
    if abs(client - now_dt) > CLOCK_SKEW_LIMIT:
        raise SyncError(409, "clock_skew",
                        "Die Uhr des Handys weicht mehr als 15 Minuten von der des Desktops ab. "
                        "Bitte Datum und Uhrzeit am Handy prüfen.")
    if len(raw_entries) > MAX_ENTRIES:
        raise SyncError(422, "invalid_entry", f"Höchstens {MAX_ENTRIES} Tage je Anfrage.")
    entries = {date: _parse_entry(date, raw, now_dt) for date, raw in raw_entries.items()}
    return SyncRequest(str(data["client_time"]), entries)
