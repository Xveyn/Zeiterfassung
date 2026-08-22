import datetime

from src.send_reminder import (free_dates_for_month, is_due, label_for_shift,
scheduled_datetime, shift_for_label, shift_off_free_days)


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


def _weekend(year, month):
    """Alle Sa/So des Monats als free_dates-Menge."""
    import calendar
    last = calendar.monthrange(year, month)[1]
    return {datetime.date(year, month, d) for d in range(1, last + 1)
            if datetime.date(year, month, d).weekday() >= 5}


def test_shift_none_leaves_date_untouched():
    d = datetime.date(2026, 10, 31)  # Samstag
    assert shift_off_free_days(d, "none", _weekend(2026, 10)) == d
    assert shift_off_free_days(d, "kaputt", _weekend(2026, 10)) == d


def test_shift_backward_to_previous_workday():
    # Sa 15.08.2026 -> Fr 14.08.
    assert shift_off_free_days(
        datetime.date(2026, 8, 15), "backward", _weekend(2026, 8)
    ) == datetime.date(2026, 8, 14)


def test_shift_forward_to_next_workday():
    # Sa 15.08.2026 -> Mo 17.08.
    assert shift_off_free_days(
        datetime.date(2026, 8, 15), "forward", _weekend(2026, 8)
    ) == datetime.date(2026, 8, 17)


def test_shift_forward_stays_in_month():
    # Sa 31.10.2026 -> vorwaerts waere Mo 02.11. -> stattdessen Fr 30.10.
    assert shift_off_free_days(
        datetime.date(2026, 10, 31), "forward", _weekend(2026, 10)
    ) == datetime.date(2026, 10, 30)


def test_shift_backward_stays_in_month():
    # So 01.02.2026 -> rueckwaerts waere Fr 30.01. -> stattdessen Mo 02.02.
    assert shift_off_free_days(
        datetime.date(2026, 2, 1), "backward", _weekend(2026, 2)
    ) == datetime.date(2026, 2, 2)


def test_shift_all_days_free_returns_input():
    import calendar
    last = calendar.monthrange(2026, 2)[1]
    every_day = {datetime.date(2026, 2, d) for d in range(1, last + 1)}
    assert shift_off_free_days(
        datetime.date(2026, 2, 10), "backward", every_day
    ) == datetime.date(2026, 2, 10)


def test_shift_backward_from_first_workday_of_month_falls_forward():
    # Fr 01.05.2026 ist "Erster Mai": rueckwaerts landet man auf Do 30.04. und
    # damit im Vormonat -> stattdessen vorwaerts auf Mo 04.05.
    free = _weekend(2026, 5) | {datetime.date(2026, 5, 1)}
    assert shift_off_free_days(
        datetime.date(2026, 5, 1), "backward", free
    ) == datetime.date(2026, 5, 4)


def test_scheduled_datetime_applies_shift_after_clamp():
    # Tag 31 im Oktober -> Sa 31.10. -> backward -> Fr 30.10. um 18:00
    assert scheduled_datetime(
        2026, 10, 31, "18:00", "backward", _weekend(2026, 10)
    ) == datetime.datetime(2026, 10, 30, 18, 0)


def test_is_due_uses_shifted_date():
    free = _weekend(2026, 10)
    # Am Fr 30.10. 18:00 ist der auf diesen Tag vorgezogene Termin faellig.
    assert is_due(datetime.datetime(2026, 10, 30, 18, 0), 31, "18:00", "",
                  "backward", free) is True
    # Ohne Verschiebung noch nicht.
    assert is_due(datetime.datetime(2026, 10, 30, 18, 0), 31, "18:00", "") is False


def test_free_dates_for_month_weekend_only():
    free = free_dates_for_month(2026, 8)
    assert datetime.date(2026, 8, 15) in free   # Samstag
    assert datetime.date(2026, 8, 16) in free   # Sonntag
    assert datetime.date(2026, 8, 17) not in free


def test_free_dates_for_month_with_holidays():
    # Fr 01.05.2026 "Erster Mai" — ein Werktag, also nur ueber die Feiertage frei.
    assert datetime.date(2026, 5, 1) not in free_dates_for_month(2026, 5)
    assert datetime.date(2026, 5, 1) in free_dates_for_month(
        2026, 5, "BY", include_holidays=True)


def test_free_dates_for_month_without_state_is_weekend_only():
    free = free_dates_for_month(2026, 5, "", include_holidays=True)
    assert datetime.date(2026, 5, 1) not in free
    assert datetime.date(2026, 5, 2) in free    # Samstag


def test_shift_label_roundtrip():
    for mode in ("none", "backward", "forward"):
        assert shift_for_label(label_for_shift(mode)) == mode
    assert shift_for_label("Unsinn") == "none"
    assert label_for_shift("Unsinn") == label_for_shift("none")
