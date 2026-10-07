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
from src.api_service import (
    DEFAULT_PORT, MAX_PORT, MIN_PORT, REASON_INVALID_PORT, REASON_PORT_IN_USE,
    REASON_TOKEN_UNAVAILABLE, STATE_ERROR, STATE_RUNNING, STATE_STARTING,
    ApiStatus, parse_port,
)
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
        "state": code_for_state_label(raw["state"]),
        "show_weekend": bool(raw["show_weekend"]),
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


# ---- Versand -------------------------------------------------------------

MAIL_KEYS = ("recipient", "name", "mail_subject", "mail_greeting",
             "mail_content", "mail_closing")
SENDING_KEYS = MAIL_KEYS + ("send_period_from_last_reminder",
                            "send_period_anchor_monthly")


def sending_updates(raw: Mapping[str, Any]) -> dict[str, Any]:
    updates: dict[str, Any] = {key: raw[key] for key in MAIL_KEYS}
    updates["send_period_from_last_reminder"] = bool(
        raw["send_period_from_last_reminder"])
    updates["send_period_anchor_monthly"] = bool(raw["send_period_anchor_monthly"])
    return updates


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


# ---- Erinnerungen --------------------------------------------------------

REMINDER_KEYS = (
    "reminders_enabled", "reminder_minutes_before",
    "send_reminder_enabled", "send_reminder_day", "send_reminder_time",
    "send_reminder_weekend_shift", "send_reminder_shift_holidays",
    "send_reminder_reservations_enabled", "send_reminder_default_minutes",
)


def shift_moves(label: str) -> bool:
    """Verschiebt die gewählte Wochenend-Regel den Termin überhaupt? Nur
    dann hat „auch Feiertage" eine Wirkung (und ist bedienbar)."""
    return shift_for_label(label) != "none"


def validate_reminders(raw: Mapping[str, Any]) -> tuple[str, str] | None:
    if parse_reminder_minutes(raw["reminder_minutes_before"]) is None:
        return ("Erinnerungszeit ungültig",
                "Bitte eine ganze Zahl zwischen 0 und 120 Minuten angeben.")
    return None


def reminders_updates(raw: Mapping[str, Any]) -> dict[str, Any]:
    """Settings-Werte des Erinnerungen-Tabs. Setzt `validate_reminders`
    voraus. Ausgegraute Optionen werden mitgeschrieben — ihr Wert bleibt
    erhalten, bis der Schalter wieder an ist."""
    minutes = parse_reminder_minutes(raw["reminder_minutes_before"])
    if minutes is None:
        raise ValueError("reminders_updates ohne vorheriges validate_reminders")
    return {
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
    }


# ---- App -----------------------------------------------------------------

def slider_percent(value: float) -> int:
    """Skalierungs-Regler auf 5er-Schritte (ttk.Scale kennt kein
    `resolution`)."""
    return round(value / 5) * 5


def app_updates(raw: Mapping[str, Any]) -> dict[str, Any]:
    """Settings-Werte des App-Tabs."""
    return {
        "autostart": bool(raw["autostart"]),
        "always_on_top": bool(raw["always_on_top"]),
        "minimize_to_tray": bool(raw["minimize_to_tray"]),
        "ui_scale": clamp_ui_scale(slider_percent(float(raw["ui_scale"])) / 100),
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


# ---- API (#92) --------------------------------------------------------------

# Bereich, aus dem `single_instance` den Port je Installationsordner ableitet
# (20000–31999); `tests/test_tab_rules.py` hält ihn gegen Drift fest.
_SINGLE_INSTANCE_FROM = 20000
_SINGLE_INSTANCE_TO = 31999
# Ab hier vergeben Betriebssysteme kurzlebig Ports an andere Programme (Linux
# 32768+, Windows 49152+).
_EPHEMERAL_FROM = 32768

_API_ERRORS = {
    REASON_INVALID_PORT: "Ungültiger Port — die API ist aus.",
    REASON_PORT_IN_USE: ("Port {port} ist belegt. Einen anderen Port wählen oder das "
                         "andere Programm beenden."),
    REASON_TOKEN_UNAVAILABLE: ("Das Token ist nicht les- oder schreibbar "
                               "(Zugriffsrechte des Datenordners?)."),
}


def validate_api(raw: Mapping[str, Any]) -> tuple[str, str] | None:
    """Der Port muss gültig sein — auch bei ausgeschalteter API, damit ein
    kaputter Wert nicht erst beim späteren Einschalten auffällt."""
    if parse_port(raw["api_port"]) is None:
        return ("Ungültiger Port",
                f"Der Port muss eine Zahl zwischen {MIN_PORT} und {MAX_PORT} sein.")
    return None


def api_updates(raw: Mapping[str, Any]) -> dict[str, Any]:
    """Settings-Werte des API-Tabs. Tolerant wie die anderen Tabs: ein
    ungültiger Port fällt auf den Standard (`validate_api` fängt ihn vorher)."""
    return {
        "api_enabled": bool(raw["api_enabled"]),
        "api_port": parse_port(raw["api_port"]) or DEFAULT_PORT,
    }


def port_hint(raw_port: Any) -> str:
    """Hinweis zum eingegebenen Port, leer wenn es nichts zu sagen gibt."""
    port = parse_port(raw_port)
    if port is None:
        return ""
    if _SINGLE_INSTANCE_FROM <= port <= _SINGLE_INSTANCE_TO:
        return ("Dieser Bereich wird auch vom Mehrfachstart-Schutz der App genutzt "
                "(je Installationsordner ein Port). Bei einem Konflikt einen anderen "
                "Port wählen.")
    if port >= _EPHEMERAL_FROM:
        return (f"Ab {_EPHEMERAL_FROM} vergibt das Betriebssystem kurzlebig Ports an "
                "andere Programme; ist der Port beim Start belegt, bleibt die API aus.")
    return ""


def status_view(status: ApiStatus) -> tuple[str, str]:
    """(Text, Art) für die Statuszeile; Art ist `ok`, `muted` oder `error`."""
    if status.state == STATE_RUNNING:
        return f"Läuft auf 127.0.0.1:{status.port}", "ok"
    if status.state == STATE_STARTING:
        return "Startet …", "muted"
    if status.state == STATE_ERROR:
        text = _API_ERRORS.get(status.reason,
                               "Start fehlgeschlagen. Details im Protokoll.")
        return text.format(port=status.port), "error"
    return "Aus.", "muted"


def curl_example(raw_port: Any) -> str:
    """Beispielaufruf für die Hinweiszeile; mit Platzhalter statt echtem Token."""
    port = parse_port(raw_port) or DEFAULT_PORT
    return f'curl -H "Authorization: Bearer <Token>" http://127.0.0.1:{port}/v1/status'


TOKEN_MASK = "•" * 24
TOKEN_MISSING = "Wird beim ersten Einschalten erzeugt."


def token_buttons_enabled(*, api_on: bool, token_known: bool, busy: bool) -> bool:
    """Ob „Token kopieren“ und „Neu erzeugen“ bedienbar sind: nur bei
    eingeschalteter API (Häkchen im Formular), vorhandenem Token und ohne
    laufende Rotation. Eine Stelle für beide Knöpfe — `set_secondary_button_
    enabled` dämpft nur die Optik, der Callback bleibt gebunden."""
    return api_on and token_known and not busy


def token_label_view(*, token_known: bool, notice: str | None) -> tuple[str, str]:
    """(Text, Art) der Token-Zeile; Art ist `ok` oder `muted`. Eine Rückmeldung
    (`notice`) geht vor der Maske: das Nachlesen des Tokens nach „Neu erzeugen“
    kommt Millisekunden nach der Erfolgsmeldung zurück und würde sie sonst
    überschreiben."""
    if notice:
        return notice, "ok"
    return (TOKEN_MASK if token_known else TOKEN_MISSING), "muted"
