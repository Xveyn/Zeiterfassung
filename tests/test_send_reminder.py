import datetime

from src.send_reminder import is_due, scheduled_datetime


def test_scheduled_datetime_clamps_day_31_in_february():
    assert scheduled_datetime(2026, 2, 31, "18:00") == datetime.datetime(2026, 2, 28, 18, 0)


def test_scheduled_datetime_clamps_day_31_in_april():
    assert scheduled_datetime(2026, 4, 31, "18:00") == datetime.datetime(2026, 4, 30, 18, 0)


def test_scheduled_datetime_no_clamp_needed():
    assert scheduled_datetime(2026, 7, 15, "09:30") == datetime.datetime(2026, 7, 15, 9, 30)


def test_scheduled_datetime_invalid_time_returns_none():
    assert scheduled_datetime(2026, 7, 15, "kaputt") is None
    assert scheduled_datetime(2026, 7, 15, None) is None


def test_scheduled_datetime_out_of_range_time_returns_none():
    assert scheduled_datetime(2026, 7, 15, "25:00") is None
    assert scheduled_datetime(2026, 7, 15, "18:60") is None
    assert scheduled_datetime(2026, 7, 15, "18:-5") is None


def test_is_due_before_scheduled_time():
    now = datetime.datetime(2026, 7, 15, 17, 59)
    assert is_due(now, 15, "18:00", "") is False


def test_is_due_at_scheduled_time():
    now = datetime.datetime(2026, 7, 15, 18, 0)
    assert is_due(now, 15, "18:00", "") is True


def test_is_due_already_fired_this_month():
    now = datetime.datetime(2026, 7, 15, 18, 5)
    assert is_due(now, 15, "18:00", "2026-07") is False


def test_is_due_catch_up_after_missed_moment():
    # App war den ganzen Monat zu, wird erst nach dem Fällig-Zeitpunkt gestartet.
    now = datetime.datetime(2026, 7, 20, 9, 0)
    assert is_due(now, 15, "18:00", "2026-06") is True


def test_is_due_fired_in_previous_month_new_month_not_yet_due():
    now = datetime.datetime(2026, 7, 10, 8, 0)
    assert is_due(now, 15, "18:00", "2026-06") is False


def test_is_due_invalid_time_never_due():
    now = datetime.datetime(2026, 7, 20, 9, 0)
    assert is_due(now, 15, "kaputt", "") is False
