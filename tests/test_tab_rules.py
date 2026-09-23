"""Tests für tab_rules.py (#132, PR 2): Prüfung und Umrechnung je Tab —
der aufgeteilte Inhalt des früheren `save_settings`."""

from src.dialogs.settings_dialog import tab_rules as tr
from src.holidays_de import STATES
from src.settings import WEEKDAY_KEYS
from src.send_reminder import SHIFT_LABELS
from src.updater import FREQUENCY_OPTIONS


def work_raw(**overrides):
    raw = {
        "workweek_only": False,
        "default_pause": "30",
        "pause_warning_enabled": True,
        "hourly_rate": "15.5",
        "werkstudent_limit_enabled": False,
        "werkstudent_limit_start.year": "2026",
        "werkstudent_limit_start.month": "4",
        "werkstudent_limit_start.day": "1",
        "werkstudent_limit_end.year": "2026",
        "werkstudent_limit_end.month": "9",
        "werkstudent_limit_end.day": "30",
        "werkstudent_limit_max_hours": "20",
    }
    for key in WEEKDAY_KEYS:
        raw[f"default_start_{key}"] = "08:00"
        raw[f"default_end_{key}"] = "16:00"
    raw.update(overrides)
    return raw


OLD_WSL = {
    "werkstudent_limit_enabled": False,
    "werkstudent_limit_start": "2025-10-01",
    "werkstudent_limit_end": "2026-03-31",
    "werkstudent_limit_max_hours": 20.0,
}


def test_date_iso():
    assert tr.date_iso("1", "4", "2026") == "2026-04-01"
    assert tr.date_iso("31", "2", "2026") is None
    assert tr.date_iso("", "4", "2026") is None
    assert tr.date_iso("x", "4", "2026") is None


def test_validate_work_ok():
    assert tr.validate_work(work_raw()) is None


def test_validate_work_names_the_weekday():
    raw = work_raw(default_start_wed="17:00", default_end_wed="09:00")
    result = tr.validate_work(raw)
    assert result is not None
    title, msg = result
    assert title == "Standard-Arbeitszeit ungültig"
    assert msg.startswith("Mi: ")


def test_validate_work_checks_period_only_when_enabled():
    backwards = {"werkstudent_limit_end.year": "2025"}
    assert tr.validate_work(work_raw(**backwards)) is None
    result = tr.validate_work(work_raw(werkstudent_limit_enabled=True, **backwards))
    assert result is not None
    title, _ = result
    assert title == "Werkstudenten-Limit-Zeitraum ungültig"


def test_validate_work_rejects_unparseable_date_when_enabled():
    raw = work_raw(werkstudent_limit_enabled=True,
                   **{"werkstudent_limit_start.day": ""})
    result = tr.validate_work(raw)
    assert result is not None
    title, _ = result
    assert title == "Werkstudenten-Limit-Zeitraum ungültig"


def test_work_updates_converts_types():
    upd = tr.work_updates(work_raw(), OLD_WSL)
    assert upd["default_pause"] == 30
    assert upd["hourly_rate"] == 15.5
    assert upd["werkstudent_limit_start"] == "2026-04-01"
    assert upd["werkstudent_limit_end"] == "2026-09-30"
    assert upd["werkstudent_limit_max_hours"] == 20.0
    assert upd["default_start_sat"] == "08:00"
    assert upd["pause_warning_enabled"] is True
    assert upd["workweek_only"] is False


def test_work_updates_falls_back_on_bad_numbers():
    # Wie das frühere save_settings: Stundenlohn tolerant auf 0.0,
    # Wochenlimit auf den bisherigen Wert.
    upd = tr.work_updates(
        work_raw(hourly_rate="abc", werkstudent_limit_max_hours="20,5"), OLD_WSL)
    assert upd["hourly_rate"] == 0.0
    assert upd["werkstudent_limit_max_hours"] == 20.0


def test_work_updates_keeps_old_date_when_unparseable():
    upd = tr.work_updates(
        work_raw(**{"werkstudent_limit_end.day": "x"}), OLD_WSL)
    assert upd["werkstudent_limit_end"] == "2026-03-31"


def test_wsl_snapshot_from_settings_and_updates_agree():
    upd = tr.work_updates(work_raw(), OLD_WSL)
    assert tr.wsl_snapshot(upd) == {
        "enabled": False, "start": "2026-04-01", "end": "2026-09-30",
        "max_hours": 20.0}
    assert tr.wsl_snapshot(OLD_WSL)["start"] == "2025-10-01"


def app_raw(**overrides):
    raw = {
        "state": STATES[1][1], "show_weekend": True, "autostart": False,
        "always_on_top": False, "minimize_to_tray": True, "ui_scale": 125,
    }
    raw.update(overrides)
    return raw


def reminders_raw(**overrides):
    raw = {
        "reminders_enabled": True, "reminder_minutes_before": "15",
        "send_reminder_enabled": True, "send_reminder_day": "28",
        "send_reminder_time": "09:00",
        "send_reminder_weekend_shift": SHIFT_LABELS["backward"],
        "send_reminder_shift_holidays": False,
        "send_reminder_reservations_enabled": True,
        "send_reminder_default_minutes": "30",
    }
    raw.update(overrides)
    return raw


def test_slider_percent_snaps_to_five():
    assert tr.slider_percent(101.3) == 100
    assert tr.slider_percent(103.0) == 105
    assert tr.slider_percent(200.0) == 200


def test_validate_reminders():
    assert tr.validate_reminders(reminders_raw()) is None
    for bad in ("abc", "-5", "121", "7.5", ""):
        result = tr.validate_reminders(reminders_raw(reminder_minutes_before=bad))
        assert result is not None
        title, _ = result
        assert title == "Erinnerungszeit ungültig"


def test_app_updates_converts():
    upd = tr.app_updates(app_raw())
    assert upd["state"] == STATES[1][0]
    assert upd["ui_scale"] == 1.25
    assert upd["autostart"] is False


def test_reminders_updates_converts():
    upd = tr.reminders_updates(reminders_raw())
    assert set(upd) == set(tr.REMINDER_KEYS)
    assert upd["reminder_minutes_before"] == 15
    assert upd["send_reminder_day"] == 28
    assert upd["send_reminder_weekend_shift"] == "backward"
    assert upd["send_reminder_default_minutes"] == 30


def test_reminders_updates_keeps_values_of_disabled_options():
    # Ausgegraut heißt nicht gelöscht: schaltet man die Erinnerung ab, bleiben
    # Minuten und Tag gespeichert und sind beim Wiedereinschalten da.
    upd = tr.reminders_updates(reminders_raw(
        reminders_enabled=False, send_reminder_enabled=False))
    assert upd["reminders_enabled"] is False
    assert upd["reminder_minutes_before"] == 15
    assert upd["send_reminder_day"] == 28


def test_shift_moves():
    assert tr.shift_moves(SHIFT_LABELS["none"]) is False
    assert tr.shift_moves(SHIFT_LABELS["backward"]) is True
    assert tr.shift_moves(SHIFT_LABELS["forward"]) is True


def test_app_updates_clamps_scale():
    assert tr.app_updates(app_raw(ui_scale=500))["ui_scale"] == 2.0


def sending_raw(**overrides):
    raw = {k: f"<{k}>" for k in tr.MAIL_KEYS}
    raw.update({"send_period_from_last_reminder": True,
                "send_period_anchor_monthly": False})
    raw.update(overrides)
    return raw


def test_sending_updates():
    upd = tr.sending_updates(sending_raw())
    assert set(upd) == set(tr.SENDING_KEYS)
    assert upd["mail_subject"] == "<mail_subject>"
    assert upd["send_period_from_last_reminder"] is True
    assert upd["send_period_anchor_monthly"] is False


def test_google_updates_sanitizes_device_name():
    upd = tr.google_updates({"device_name": "  Laptop\x07 ", "gcal_calendar": "x"})
    assert upd == {"device_name": "Laptop"}


def test_calendar_update():
    cal_map = {"Arbeit": "abc@group", "Privat": "primary"}
    assert tr.calendar_update(cal_map, "Arbeit", "primary", True) == "abc@group"
    assert tr.calendar_update(cal_map, "Privat", "primary", True) is None
    # Liste noch nicht geladen: nie vorschnell "primary" festschreiben.
    assert tr.calendar_update({}, "primary", "abc@group", True) is None
    assert tr.calendar_update(cal_map, "Arbeit", "primary", False) is None


def test_update_tab_updates():
    raw = {"update_check_frequency": FREQUENCY_OPTIONS[1][1],
           "prerelease_updates_enabled": True}
    assert tr.update_tab_updates(raw) == {
        "update_check_frequency": FREQUENCY_OPTIONS[1][0],
        "prerelease_updates_enabled": True}
    raw["auto_update_enabled"] = False
    assert tr.update_tab_updates(raw)["auto_update_enabled"] is False


# Die Schlüssel, die das frühere dialog.save_settings geschrieben hat —
# wörtlich aus dessen `updates`-Dict (plus die Wochentage und die beiden
# Sonderfälle auto_update_enabled und gcal_calendar_id). Speichern je Tab
# darf keinen davon verlieren und keinen dazuerfinden.
_legacy_keys_base = {
    "autostart", "default_pause", "recipient", "name", "mail_subject",
    "mail_greeting", "mail_content", "mail_closing", "hourly_rate", "state",
    "show_weekend", "always_on_top", "minimize_to_tray", "reminders_enabled",
    "reminder_minutes_before", "send_reminder_enabled", "send_reminder_day",
    "send_reminder_time", "send_reminder_weekend_shift",
    "send_reminder_shift_holidays", "send_reminder_reservations_enabled",
    "send_reminder_default_minutes", "send_period_from_last_reminder",
    "send_period_anchor_monthly", "update_check_frequency",
    "prerelease_updates_enabled", "ui_scale", "werkstudent_limit_enabled",
    "werkstudent_limit_start", "werkstudent_limit_end",
    "werkstudent_limit_max_hours", "pause_warning_enabled", "workweek_only",
    "device_name", "auto_update_enabled",
}
LEGACY_KEYS = (
    _legacy_keys_base |
    {f"default_start_{k}" for k in WEEKDAY_KEYS} |  # type: ignore[reportGeneralTypeIssues]
    {f"default_end_{k}" for k in WEEKDAY_KEYS}
)


def test_tabs_together_write_exactly_the_legacy_keys():
    written = [
        tr.work_updates(work_raw(), OLD_WSL),
        tr.reminders_updates(reminders_raw()),
        tr.sending_updates(sending_raw()),
        tr.google_updates({"device_name": "", "gcal_calendar": ""}),
        tr.app_updates(app_raw()),
        tr.update_tab_updates({"update_check_frequency": FREQUENCY_OPTIONS[0][1],
                               "prerelease_updates_enabled": False,
                               "auto_update_enabled": True}),
    ]
    keys = [k for upd in written for k in upd]
    assert len(keys) == len(set(keys)), "ein Schlüssel in zwei Tabs"
    assert set(keys) == LEGACY_KEYS
