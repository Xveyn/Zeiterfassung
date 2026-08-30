"""Reine Urlaubs-Regeln (Tk-frei, ohne Store)."""

import pytest

from src.vacations import (
    apportion_minutes, expand_days, periods_overlap, total_minutes,
)


# ---------------------------------------------------------------- expand_days

def test_expand_days_covers_every_calendar_day():
    days = expand_days("2026-04-13", "2026-04-20", 480, "")
    assert sorted(days) == [
        "2026-04-13", "2026-04-14", "2026-04-15", "2026-04-16",
        "2026-04-17", "2026-04-18", "2026-04-19", "2026-04-20",
    ]


def test_expand_days_zeroes_weekend():
    days = expand_days("2026-04-13", "2026-04-20", 480, "")
    assert days["2026-04-18"] == 0  # Samstag
    assert days["2026-04-19"] == 0  # Sonntag
    assert days["2026-04-13"] == 480  # Montag


def test_expand_days_zeroes_holiday_for_state():
    # 2026-01-01 ist bundesweit Feiertag; 2026-01-06 nur in BY/BW/ST.
    bayern = expand_days("2026-01-01", "2026-01-07", 480, "BY")
    assert bayern["2026-01-01"] == 0
    assert bayern["2026-01-06"] == 0
    assert bayern["2026-01-07"] == 480


def test_expand_days_without_state_keeps_holidays_paid():
    # Ohne Bundesland liefert get_holidays ein leeres Dict — nur Wochenenden
    # fallen dann auf 0.
    ohne = expand_days("2026-01-01", "2026-01-02", 480, "")
    assert ohne["2026-01-01"] == 480


def test_expand_days_spans_year_boundary():
    days = expand_days("2026-12-28", "2027-01-04", 480, "BY")
    assert len(days) == 8
    assert days["2026-12-28"] == 480
    assert days["2027-01-01"] == 0  # Neujahr
    assert days["2027-01-04"] == 480


def test_expand_days_single_day():
    assert expand_days("2026-04-13", "2026-04-13", 480, "") == {"2026-04-13": 480}


def test_expand_days_reversed_range_is_empty():
    assert expand_days("2026-04-20", "2026-04-13", 480, "") == {}


# ---------------------------------------------------------- apportion_minutes

def test_apportion_minutes_even_split():
    assert apportion_minutes(2400, 6) == [400, 400, 400, 400, 400, 400]


def test_apportion_minutes_remainder_goes_to_front():
    assert apportion_minutes(2400, 7) == [343, 343, 343, 343, 343, 343, 342]


@pytest.mark.parametrize("total", [0, 1, 59, 2400, 2401, 9999])
@pytest.mark.parametrize("n", [1, 2, 3, 5, 6, 7, 30, 31])
def test_apportion_minutes_always_sums_exactly(total, n):
    parts = apportion_minutes(total, n)
    assert len(parts) == n
    assert sum(parts) == total
    assert all(p >= 0 for p in parts)


def test_apportion_minutes_zero_days():
    assert apportion_minutes(2400, 0) == []


# ------------------------------------------------------------ periods_overlap

def _period(name, date_from, date_to, deleted=False):
    return {"name": name, "from": date_from, "to": date_to,
            "days": {}, "gcal_event_id": None,
            "modified_at": "2026-08-30T10:00:00Z", "deleted": deleted}


def test_periods_overlap_detects_true_overlap():
    periods = {"a": _period("Sommer", "2026-07-01", "2026-07-14")}
    assert periods_overlap(periods, None, "2026-07-10", "2026-07-20") == "Sommer"


def test_periods_overlap_detects_touching_edge():
    periods = {"a": _period("Sommer", "2026-07-01", "2026-07-14")}
    assert periods_overlap(periods, None, "2026-07-14", "2026-07-20") == "Sommer"


def test_periods_overlap_detects_enclosure():
    periods = {"a": _period("Sommer", "2026-07-05", "2026-07-10")}
    assert periods_overlap(periods, None, "2026-07-01", "2026-07-31") == "Sommer"


def test_periods_overlap_allows_adjacent_ranges():
    periods = {"a": _period("Sommer", "2026-07-01", "2026-07-14")}
    assert periods_overlap(periods, None, "2026-07-15", "2026-07-20") is None


def test_periods_overlap_excludes_self_when_editing():
    periods = {"a": _period("Sommer", "2026-07-01", "2026-07-14")}
    assert periods_overlap(periods, "a", "2026-07-05", "2026-07-20") is None


def test_periods_overlap_ignores_tombstones():
    periods = {"a": _period("Sommer", "2026-07-01", "2026-07-14", deleted=True)}
    assert periods_overlap(periods, None, "2026-07-10", "2026-07-20") is None


# -------------------------------------------------------------- total_minutes

def test_total_minutes_sums_over_minutes():
    assert total_minutes({"2026-04-13": 480, "2026-04-14": 240}) == 720


def test_total_minutes_empty():
    assert total_minutes({}) == 0


def test_period_for_day_finds_the_covering_period():
    from src.vacations import period_for_day
    periods = {"a1": {**_period("Sommer", "2026-07-01", "2026-07-02"),
                      "days": {"2026-07-01": 480, "2026-07-02": 0}}}
    hit = period_for_day(periods, "2026-07-02")
    assert hit["name"] == "Sommer"
    assert hit["id"] == "a1"
    assert period_for_day(periods, "2026-07-03") is None


def test_period_for_day_returns_a_detached_days_copy():
    from src.vacations import period_for_day
    periods = {"a1": {**_period("Sommer", "2026-07-01", "2026-07-01"),
                      "days": {"2026-07-01": 480}}}
    hit = period_for_day(periods, "2026-07-01")
    hit["days"]["2026-07-01"] = 0
    assert periods["a1"]["days"]["2026-07-01"] == 480
