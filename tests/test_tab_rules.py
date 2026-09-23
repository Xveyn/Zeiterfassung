"""Tests für tab_rules.py (#132, PR 2): Prüfung und Umrechnung je Tab —
der aufgeteilte Inhalt des früheren `save_settings`."""

from src.dialogs.settings_dialog import tab_rules as tr
from src.settings import WEEKDAY_KEYS


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
