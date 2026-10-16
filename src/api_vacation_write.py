# src/api_vacation_write.py
"""Schreibpfad der lokalen API für Urlaub (#239, PR 7), Tk-frei und ohne Socket.

Der Body von `POST /v1/vacations` ist **Fremddaten**. Dieses Modul prüft nur Form
und Wertebereich und baut daraus dieselbe Eingabe, die der Urlaubs-Dialog dem
Planer gibt; **gerechnet wird nicht hier**, sondern in
`vacation_plan.plan_vacation_save` (Arbeitstage, Feiertage, Verteilung der
Gesamtstunden, Obergrenze je Tag) — die API soll nicht neu rechnen.

Body: `name`, `from`, `to` (ISO) und genau eines von `hours_per_day`
(Stunden je Arbeitstag) oder `total_hours` (auf die Arbeitstage verteilt); dazu
optional `day_hours` — Stunden einzelner Tage, die den berechneten Wert
überschreiben (die „Einzelne Tage anpassen“-Liste des Dialogs). Stunden sind
Zahlen, Dezimalstellen erlaubt; die Minuten ergeben sich wie im Dialog.
"""
from __future__ import annotations

import datetime
import math
import re
import unicodedata
from dataclasses import dataclass
from typing import Any

from src.api_entry_write import WriteError, check_date_range, load_json_body
from src.vacation_plan import hours_to_minutes_exact

MAX_NAME_LEN = 100
# Ein Skript-Fehler mit 2000–2100 würde sonst 36 500 Tage in `vacations.json`
# und jeden Bericht schreiben; ein Jahr ist die großzügige Grenze (der Dialog
# kennt keine, aber auch niemanden mit einem längeren Urlaub am Stück).
MAX_PERIOD_DAYS = 366

_DATE_RE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
_KEYS = frozenset({"name", "from", "to", "hours_per_day", "total_hours", "day_hours"})
_REQUIRED = frozenset({"name", "from", "to"})


@dataclass(frozen=True)
class VacationRequest:
    name: str
    date_from: str
    date_to: str
    mode: str                       # "per_day" | "total", wie im Dialog
    value: float                    # Stunden je Arbeitstag bzw. Gesamtstunden
    overrides: dict[str, int]       # {ISO: Minuten}


def _parse_name(value: Any) -> str:
    if not isinstance(value, str):
        raise WriteError(422, "invalid_name", "name muss Text sein.")
    value = value.strip()
    if not value:
        raise WriteError(422, "invalid_name", "Bitte einen Namen für den Urlaub angeben.")
    if len(value) > MAX_NAME_LEN:
        raise WriteError(422, "invalid_name",
                         f"name darf höchstens {MAX_NAME_LEN} Zeichen haben.")
    if any(unicodedata.category(ch) in ("Cc", "Cs") for ch in value):
        raise WriteError(422, "invalid_name",
                         "name darf keine Steuerzeichen oder ungültigen Unicode-Zeichen enthalten.")
    return value


def _parse_day(value: Any, label: str, code: str = "invalid_date") -> datetime.date:
    if not isinstance(value, str) or not _DATE_RE.fullmatch(value):
        raise WriteError(422, code, f"{label}: erwartet YYYY-MM-DD.")
    try:
        day = datetime.date.fromisoformat(value)
    except ValueError:
        raise WriteError(422, code, f"{label}: kein gültiges Datum.") from None
    check_date_range(day)
    return day


def _hours(value: Any, label: str, code: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise WriteError(422, code, f"{label} muss eine endliche Zahl (Stunden) sein.")
    return float(value)


def parse_vacation_body(body: bytes) -> VacationRequest:
    """Body → geprüfte Eingabe für den Planer. Wirft `WriteError`: 400 bei
    kaputtem JSON oder falscher Form, 422 bei ungültigen Werten. Negative Stunden
    und ein vertauschter Zeitraum bleiben dem Planer überlassen, damit die Meldung
    dieselbe ist wie in der App."""
    data = load_json_body(body)
    if not isinstance(data, dict):
        raise WriteError(400, "invalid_body", "Erwartet wird ein Objekt.")
    unknown = set(data) - _KEYS
    if unknown or not _REQUIRED <= set(data):
        raise WriteError(
            400, "invalid_body",
            "Erlaubt sind name, from, to (Pflicht), hours_per_day oder total_hours "
            f"(genau eines) und day_hours; gefunden: {sorted(str(k)[:40] for k in data)[:10]}.")
    has_per_day, has_total = "hours_per_day" in data, "total_hours" in data
    if has_per_day == has_total:
        raise WriteError(400, "invalid_body",
                         "Genau eines von hours_per_day oder total_hours angeben.")

    name = _parse_name(data["name"])
    first = _parse_day(data["from"], "from")
    last = _parse_day(data["to"], "to")
    if last >= first and (last - first).days + 1 > MAX_PERIOD_DAYS:
        raise WriteError(422, "period_too_long",
                         f"Ein Urlaub darf höchstens {MAX_PERIOD_DAYS} Tage umfassen.")

    mode = "per_day" if has_per_day else "total"
    value = _hours(data["hours_per_day" if has_per_day else "total_hours"],
                   "hours_per_day" if has_per_day else "total_hours", "invalid_hours")

    overrides: dict[str, int] = {}
    raw_days = data.get("day_hours", {})
    if not isinstance(raw_days, dict):
        raise WriteError(422, "invalid_day_hours", 'day_hours muss {"YYYY-MM-DD": Stunden} sein.')
    for key, hours in raw_days.items():
        day = _parse_day(key, "day_hours", "invalid_day_hours")
        amount = _hours(hours, f"day_hours[{key}]", "invalid_day_hours")
        if amount < 0:
            raise WriteError(422, "invalid_day_hours", f"day_hours[{key}]: nicht negativ.")
        if last >= first and not first <= day <= last:
            # Der Dialog ignoriert Tage außerhalb still; ein Skript soll seinen
            # Tippfehler erfahren, statt dass eine Zahl verschwindet.
            raise WriteError(422, "invalid_day_hours", f"day_hours[{key}] liegt außerhalb des Zeitraums.")
        overrides[key] = hours_to_minutes_exact(amount)

    return VacationRequest(name, first.isoformat(), last.isoformat(), mode, value, overrides)
