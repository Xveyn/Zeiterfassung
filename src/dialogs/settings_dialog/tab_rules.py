"""Prüfung und Umrechnung des Formularstands je Einstellungs-Tab (#132).

Der Inhalt des früheren `dialog.save_settings`, aufgeteilt auf die Tabs,
die ihn tragen. Jeder Tab liefert seinen **rohen** Formularstand
(`FieldSet.values()` — Text aus Entries/Comboboxen, Bools aus Häkchen);
hier wird er geprüft (`validate_*` → `(Titel, Meldung)` oder `None`) und in
Settings-Werte umgerechnet (`*_updates` → Dict für `Settings.apply_updates`).

Tk-frei und getestet. Die Umrechnung ist so tolerant wie vorher: was
`save_settings` still auf einen Fallback setzte, tut es hier auch.
"""

import datetime
from collections.abc import Mapping
from typing import Any

from src.settings import WEEKDAY_KEYS, parse_hourly_rate
from src.time_utils import DAYS_DE, validate_entry, validate_period

WSL_KEYS = (
    "werkstudent_limit_enabled", "werkstudent_limit_start",
    "werkstudent_limit_end", "werkstudent_limit_max_hours",
)


def date_iso(day: str, month: str, year: str) -> str | None:
    """ISO-Datum aus den drei Combobox-Werten, `None` bei Unsinn/31.02."""
    try:
        return datetime.date(int(year), int(month), int(day)).isoformat()
    except (TypeError, ValueError):
        return None


def _wsl_date(raw: Mapping[str, Any], which: str) -> str | None:
    prefix = f"werkstudent_limit_{which}"
    return date_iso(raw[f"{prefix}.day"], raw[f"{prefix}.month"],
                    raw[f"{prefix}.year"])


def validate_work(raw: Mapping[str, Any]) -> tuple[str, str] | None:
    for key, label in zip(WEEKDAY_KEYS, DAYS_DE, strict=True):
        ok, msg = validate_entry(raw[f"default_start_{key}"],
                                 raw[f"default_end_{key}"])
        if not ok:
            return "Standard-Arbeitszeit ungültig", f"{label}: {msg}"
    # Der Zeitraum zählt nur, wenn das Limit an ist — wie bisher.
    if raw["werkstudent_limit_enabled"]:
        start, end = _wsl_date(raw, "start"), _wsl_date(raw, "end")
        if start is None or end is None:
            return ("Werkstudenten-Limit-Zeitraum ungültig",
                    "Bitte ein gültiges Datum wählen.")
        ok, msg = validate_period(start, end)
        if not ok:
            return "Werkstudenten-Limit-Zeitraum ungültig", msg
    return None


def work_updates(raw: Mapping[str, Any],
                 old: Mapping[str, Any]) -> dict[str, Any]:
    """Settings-Werte des Arbeitszeit-Tabs. `old` trägt die bisherigen
    `WSL_KEYS`-Werte: ein nicht lesbares Wochenlimit oder Datum behält den
    gespeicherten Wert, statt zu werfen."""
    try:
        max_hours = float(raw["werkstudent_limit_max_hours"])
    except (TypeError, ValueError):
        max_hours = old["werkstudent_limit_max_hours"]
    updates: dict[str, Any] = {
        "default_pause": int(raw["default_pause"]),
        "pause_warning_enabled": bool(raw["pause_warning_enabled"]),
        "hourly_rate": parse_hourly_rate(raw["hourly_rate"]),
        "werkstudent_limit_enabled": bool(raw["werkstudent_limit_enabled"]),
        "werkstudent_limit_start": (_wsl_date(raw, "start")
                                    or old["werkstudent_limit_start"]),
        "werkstudent_limit_end": (_wsl_date(raw, "end")
                                  or old["werkstudent_limit_end"]),
        "werkstudent_limit_max_hours": max_hours,
        "workweek_only": bool(raw["workweek_only"]),
    }
    # Alle sieben Tage, auch Sa/So bei „Nur Werktage": die Werte bleiben so
    # erhalten und sind sofort wieder da, wenn der Modus zurückgenommen wird.
    for key in WEEKDAY_KEYS:
        updates[f"default_start_{key}"] = raw[f"default_start_{key}"]
        updates[f"default_end_{key}"] = raw[f"default_end_{key}"]
    return updates


def wsl_snapshot(values: Mapping[str, Any]) -> dict[str, Any]:
    """Die Form, die `weekly_limit.period_scan_needed` vergleicht — aus
    Settings-Werten oder aus `work_updates`."""
    return {
        "enabled": values["werkstudent_limit_enabled"],
        "start": values["werkstudent_limit_start"],
        "end": values["werkstudent_limit_end"],
        "max_hours": values["werkstudent_limit_max_hours"],
    }
