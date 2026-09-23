"""Prüfung und Umrechnung des Formularstands je Einstellungs-Tab (#132).

Der Inhalt des früheren `dialog.save_settings`, aufgeteilt auf die Tabs,
die ihn tragen. Jeder Tab liefert seinen **rohen** Formularstand
(`FieldSet.values()` — Text aus Entries/Comboboxen, Bools aus Häkchen);
hier wird er geprüft (`validate_*` → `(Titel, Meldung)` oder `None`) und in
Settings-Werte umgerechnet (`*_updates` → Dict für `Settings.apply_updates`).

Tk-frei und getestet. Die Umrechnung ist so tolerant wie vorher: was
das frühere `save_settings` still auf einen Fallback setzte, tut es hier auch.
"""

import datetime
from collections.abc import Mapping
from typing import Any

from src.devices import sanitize_device_name
from src.holidays_de import code_for_state_label
from src.send_reminder import shift_for_label
from src.settings import (
    WEEKDAY_KEYS, clamp_ui_scale, parse_hourly_rate, parse_reminder_minutes,
    resolve_calendar_id,
)
from src.time_utils import DAYS_DE, validate_entry, validate_period
from src.updater import frequency_for_label

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


# ---- Bericht & Mail ------------------------------------------------------

MAIL_KEYS = ("recipient", "name", "mail_subject", "mail_greeting",
             "mail_content", "mail_closing")


def mail_updates(raw: Mapping[str, Any]) -> dict[str, Any]:
    return {key: raw[key] for key in MAIL_KEYS}


# ---- Google --------------------------------------------------------------

def google_updates(raw: Mapping[str, Any]) -> dict[str, Any]:
    # Am Rand saniert (Länge, Steuerzeichen): der Name reist über die
    # Sync-Registry zu anderen Geräten und landet dort in einem Label.
    return {"device_name": sanitize_device_name(raw["device_name"])}


def calendar_update(cal_map: Mapping[str, str], selected: str,
                    stored_id: str | None, gcal_enabled: bool) -> str | None:
    """Neue Kalender-ID, falls sie sich ändert, sonst `None`.

    Nur mit geladener Liste (`cal_map` gefüllt): davor steht in der Combobox
    die gespeicherte ID statt eines Klarnamens, und ein vorschnelles
    Speichern schriebe über `resolve_calendar_id` "primary" fest."""
    if not gcal_enabled or not cal_map:
        return None
    new_id = resolve_calendar_id(dict(cal_map), selected, stored_id or "")
    return new_id if new_id != stored_id else None


# ---- App -----------------------------------------------------------------

def slider_percent(value: float) -> int:
    """Skalierungs-Regler auf 5er-Schritte (ttk.Scale kennt kein
    `resolution`)."""
    return round(value / 5) * 5


def validate_app(raw: Mapping[str, Any]) -> tuple[str, str] | None:
    if parse_reminder_minutes(raw["reminder_minutes_before"]) is None:
        return ("Erinnerungszeit ungültig",
                "Bitte eine ganze Zahl zwischen 0 und 120 Minuten angeben.")
    return None


def app_updates(raw: Mapping[str, Any]) -> dict[str, Any]:
    """Settings-Werte des App-Tabs. Setzt `validate_app` voraus."""
    minutes = parse_reminder_minutes(raw["reminder_minutes_before"])
    if minutes is None:
        raise ValueError("app_updates ohne vorheriges validate_app")
    return {
        "autostart": bool(raw["autostart"]),
        "state": code_for_state_label(raw["state"]),
        "show_weekend": bool(raw["show_weekend"]),
        "always_on_top": bool(raw["always_on_top"]),
        "minimize_to_tray": bool(raw["minimize_to_tray"]),
        "ui_scale": clamp_ui_scale(slider_percent(float(raw["ui_scale"])) / 100),
        "reminders_enabled": bool(raw["reminders_enabled"]),
        "reminder_minutes_before": minutes,
        "send_reminder_enabled": bool(raw["send_reminder_enabled"]),
        "send_reminder_day": int(raw["send_reminder_day"]),
        "send_reminder_time": raw["send_reminder_time"],
        "send_reminder_weekend_shift": shift_for_label(
            raw["send_reminder_weekend_shift"]),
        "send_reminder_shift_holidays": bool(raw["send_reminder_shift_holidays"]),
        "send_reminder_reservations_enabled": bool(
            raw["send_reminder_reservations_enabled"]),
        "send_reminder_default_minutes": int(raw["send_reminder_default_minutes"]),
        "send_period_from_last_reminder": bool(
            raw["send_period_from_last_reminder"]),
        "send_period_anchor_monthly": bool(raw["send_period_anchor_monthly"]),
    }


# ---- Updates -------------------------------------------------------------

def update_tab_updates(raw: Mapping[str, Any]) -> dict[str, Any]:
    updates: dict[str, Any] = {
        "update_check_frequency": frequency_for_label(raw["update_check_frequency"]),
        "prerelease_updates_enabled": bool(raw["prerelease_updates_enabled"]),
    }
    # Fehlt, wo die Plattform kein Selbst-Update kann (der Tab baut den
    # Schalter dann gar nicht) — der gespeicherte Wert bleibt unangetastet.
    if "auto_update_enabled" in raw:
        updates["auto_update_enabled"] = bool(raw["auto_update_enabled"])
    return updates
