import datetime

from src.send_reminder import (due_day_reminder, free_dates_for_month, is_due,
label_for_shift, scheduled_datetime, shift_for_label, shift_off_free_days)


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


def _res(end, minutes, start="08:00"):
    return {"start": start, "end": end, "kategorie": "",
            "send_reminder_minutes": minutes}


def test_due_day_reminder_fires_n_minutes_before_end():
    slots = [_res("17:00", 15)]
    assert due_day_reminder(slots, datetime.datetime(2026, 8, 31, 16, 44)) is None
    rem = due_day_reminder(slots, datetime.datetime(2026, 8, 31, 16, 45))
    assert rem is not None and rem.end == "17:00" and rem.minutes == 15


def test_due_day_reminder_is_caught_up_after_end():
    """App startet erst um 18:00 — der Toast von 16:45 wird nachgeholt."""
    rem = due_day_reminder([_res("17:00", 15)],
                           datetime.datetime(2026, 8, 31, 18, 0))
    assert rem is not None


def test_due_day_reminder_zero_minutes_fires_at_end():
    slots = [_res("17:00", 0)]
    assert due_day_reminder(slots, datetime.datetime(2026, 8, 31, 16, 59)) is None
    assert due_day_reminder(slots, datetime.datetime(2026, 8, 31, 17, 0)) is not None


def test_due_day_reminder_without_marker_returns_none():
    assert due_day_reminder([_res("17:00", None)],
                            datetime.datetime(2026, 8, 31, 18, 0)) is None
    assert due_day_reminder([], datetime.datetime(2026, 8, 31, 18, 0)) is None


def test_due_day_reminder_picks_the_marked_slot():
    slots = [_res("12:00", None, start="08:00"), _res("17:00", 30, start="13:00")]
    rem = due_day_reminder(slots, datetime.datetime(2026, 8, 31, 16, 30))
    assert rem is not None and rem.end == "17:00" and rem.minutes == 30


def test_due_day_reminder_ignores_broken_values():
    assert due_day_reminder([{"start": "08:00", "end": "kaputt",
                              "send_reminder_minutes": 15}],
                            datetime.datetime(2026, 8, 31, 23, 0)) is None
    assert due_day_reminder([{"start": "08:00", "end": "17:00",
                              "send_reminder_minutes": 999}],
                            datetime.datetime(2026, 8, 31, 23, 0)) is None
    assert due_day_reminder([{"start": "08:00", "end": "17:00",
                              "send_reminder_minutes": True}],
                            datetime.datetime(2026, 8, 31, 23, 0)) is None


def test_marked_reminder_dates_collects_days_with_marker():
    from src.send_reminder import marked_reminder_dates
    raw = {
        "2026-08-02": {"slots": [{"send_reminder_minutes": 15}],
                       "modified_at": "x", "deleted": False},
        "2026-08-10": {"slots": [{"send_reminder_minutes": None}],
                       "modified_at": "x", "deleted": False},
        "2026-09-05": {"slots": [{"send_reminder_minutes": None},
                                 {"send_reminder_minutes": 30}],
                       "modified_at": "x", "deleted": False},
        "2026-09-20": {"slots": [{"send_reminder_minutes": 15}],
                       "modified_at": "x", "deleted": True},
    }
    assert sorted(marked_reminder_dates(raw)) == [
        datetime.date(2026, 8, 2), datetime.date(2026, 9, 5)]


def test_marked_reminder_dates_ignores_broken_date_keys():
    from src.send_reminder import marked_reminder_dates
    raw = {"kein-datum": {"slots": [{"send_reminder_minutes": 15}],
                          "modified_at": "x", "deleted": False}}
    assert marked_reminder_dates(raw) == []


def test_monthly_anchor_dates_covers_three_months():
    from src.send_reminder import monthly_anchor_dates
    dates = monthly_anchor_dates(datetime.date(2026, 9, 5), 23, "16:30")
    assert dates == [datetime.date(2026, 9, 23), datetime.date(2026, 8, 23),
                     datetime.date(2026, 7, 23)]


def test_monthly_anchor_dates_crosses_year_boundary():
    from src.send_reminder import monthly_anchor_dates
    dates = monthly_anchor_dates(datetime.date(2026, 1, 10), 15, "16:30")
    assert dates == [datetime.date(2026, 1, 15), datetime.date(2025, 12, 15),
                     datetime.date(2025, 11, 15)]


def test_previous_anchor_date_marked_only():
    from src.send_reminder import previous_anchor_date
    assert previous_anchor_date(
        datetime.date(2026, 9, 5),
        [datetime.date(2026, 8, 2), datetime.date(2026, 9, 5)],
        [],
    ) == datetime.date(2026, 8, 2)


def test_previous_anchor_date_prefers_the_nearest():
    from src.send_reminder import previous_anchor_date
    assert previous_anchor_date(
        datetime.date(2026, 9, 5),
        [datetime.date(2026, 8, 2)],
        [datetime.date(2026, 8, 23), datetime.date(2026, 9, 23)],
    ) == datetime.date(2026, 8, 23)


def test_previous_anchor_date_none_when_no_past_anchor():
    from src.send_reminder import previous_anchor_date
    assert previous_anchor_date(datetime.date(2026, 9, 5),
                                [datetime.date(2026, 9, 5)], []) is None
    assert previous_anchor_date(datetime.date(2026, 9, 5), [], []) is None


def test_default_send_period_starts_day_after_anchor():
    from src.send_reminder import default_send_period
    assert default_send_period(
        datetime.date(2026, 9, 5), [datetime.date(2026, 8, 2)], []
    ) == (datetime.date(2026, 8, 3), datetime.date(2026, 9, 5))


def test_default_send_period_none_without_anchor():
    from src.send_reminder import default_send_period
    assert default_send_period(datetime.date(2026, 9, 5), [], []) is None
