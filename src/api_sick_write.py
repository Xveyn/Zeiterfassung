# src/api_sick_write.py
# pyright: reportOptionalMemberAccess=true
"""Schreibpfad der lokalen API für Krankheit, Tk-frei und ohne Socket.

Der Body von `POST /v1/sick` ist **Fremddaten**. Dieses Modul prüft nur Form und
Wertebereich; gerechnet wird in `sick_plan` (Vorbelegung, Obergrenze je Tag),
derselben Planung wie im Dialog.

Body: `from`, `to` (ISO, Pflicht); optional `basis` (`standard`/`average_3m`,
sonst gilt die Einstellung) und `day_hours` — Stunden einzelner Tage, die den
vorbelegten Wert überschreiben. Stunden sind Zahlen, Dezimalstellen erlaubt.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.api_entry_write import WriteError, load_json_body
from src.api_vacation_write import _hours, _parse_day
from src.sick_plan import BASES, MAX_BLOCK_DAYS
from src.vacation_plan import hours_to_minutes_exact

_KEYS = frozenset({"from", "to", "basis", "day_hours"})
_REQUIRED = frozenset({"from", "to"})


@dataclass(frozen=True)
class SickRequest:
    date_from: str
    date_to: str
    basis: str | None
    overrides: dict[str, int]       # {ISO: Minuten}


def parse_sick_body(body: bytes) -> SickRequest:
    """Body → geprüfte Eingabe. Wirft `WriteError`: 400 bei kaputtem JSON oder
    falscher Form, 422 bei ungültigen Werten. Ein vertauschter Zeitraum bleibt
    dem Planer überlassen (dieselbe Meldung wie in der App)."""
    data = load_json_body(body)
    if not isinstance(data, dict):
        raise WriteError(400, "invalid_body", "Erwartet wird ein Objekt.")
    unknown = set(data) - _KEYS
    if unknown or not _REQUIRED <= set(data):
        raise WriteError(
            400, "invalid_body",
            "Erlaubt sind from, to (Pflicht), basis und day_hours; "
            f"gefunden: {sorted(str(k)[:40] for k in data)[:10]}.")
    first = _parse_day(data["from"], "from")
    last = _parse_day(data["to"], "to")
    if last >= first and (last - first).days + 1 > MAX_BLOCK_DAYS:
        raise WriteError(422, "period_too_long",
                         f"Ein Krankheitszeitraum darf höchstens {MAX_BLOCK_DAYS} Tage umfassen.")

    basis: Any = data.get("basis")
    if "basis" in data and (not isinstance(basis, str) or basis not in BASES):
        raise WriteError(422, "invalid_basis",
                         f"basis muss einer von {', '.join(BASES)} sein.")

    overrides: dict[str, int] = {}
    raw_days = data.get("day_hours", {})
    if not isinstance(raw_days, dict):
        raise WriteError(422, "invalid_day_hours", 'day_hours muss {"YYYY-MM-DD": Stunden} sein.')
    for key, hours in raw_days.items():
        day = _parse_day(key, "day_hours", "invalid_day_hours")
        amount = _hours(hours, f"day_hours[{key}]", "invalid_day_hours")
        if amount < 0 or amount > 24:
            raise WriteError(422, "invalid_day_hours",
                             f"day_hours[{key}]: 0 bis 24 Stunden.")
        if last >= first and not first <= day <= last:
            raise WriteError(422, "invalid_day_hours",
                             f"day_hours[{key}] liegt außerhalb des Zeitraums.")
        overrides[key] = hours_to_minutes_exact(amount)
    return SickRequest(first.isoformat(), last.isoformat(), basis, overrides)
