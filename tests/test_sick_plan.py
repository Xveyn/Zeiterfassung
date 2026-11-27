import datetime

import pytest

from src import sick_plan


def test_normalize_basis():
    assert sick_plan.normalize_basis("average_3m") == "average_3m"
    assert sick_plan.normalize_basis("standard") == "standard"
    for bad in ("kaputt", None, 3):
        assert sick_plan.normalize_basis(bad) == "standard"


_TAGE = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
SETTINGS = {
    "state": "BY",
    "default_pause": 30,
    **{f"default_start_{d}": "08:00" for d in _TAGE},
    **{f"default_end_{d}": "16:30" for d in _TAGE},
}


def _slot(start="08:00", end="16:00", pause=0):
    return {"start": start, "end": end, "pause": pause, "kategorie": ""}


def _entries(*days, slot=None):
    return {d: {"slots": [slot or _slot()]} for d in days}


def _prefill(date_from, date_to, **kw):
    args = dict(basis="standard", entries={}, reservations=None,
                vacation_days={}, sick_days={}, settings=SETTINGS)
    args.update(kw)
    return sick_plan.prefill(date_from, date_to, **args)


def _avg_entries():
    days = ["2026-03-02", "2026-03-04", "2026-03-06",
            "2026-03-09", "2026-03-11", "2026-03-13"]
    return _entries(*days)


def _avg(first="2026-03-16", **kw):
    args = dict(entries=_avg_entries(), vacation_days={}, sick_days={},
                state="")
    args.update(kw)
    return sick_plan.average_minutes(datetime.date.fromisoformat(first), **args)


RES_SAT = {"2026-06-06": {"slots": [_slot("09:00", "13:00", 30)]}}


def test_prefill_takes_reservation_net_minutes_even_on_weekend():
    p = _prefill("2026-06-06", "2026-06-06", reservations=RES_SAT)
    assert p.days == {"2026-06-06": 210}


def test_prefill_ignores_reservations_when_none_passed():
    p = _prefill("2026-06-06", "2026-06-06", reservations=None)
    assert p.days == {"2026-06-06": 0}


def test_prefill_weekend_and_holiday_are_zero():
    p = _prefill("2026-06-04", "2026-06-07")
    assert p.days["2026-06-04"] == 0
    assert p.days["2026-06-07"] == 0
    assert p.days["2026-06-05"] == 480


def test_prefill_without_state_counts_holiday_as_workday():
    p = _prefill("2026-06-04", "2026-06-04", settings={**SETTINGS, "state": ""})
    assert p.days == {"2026-06-04": 480}


def test_prefill_standard_uses_weekday_times_minus_pause():
    s = {**SETTINGS, "default_start_mon": "08:00", "default_end_mon": "16:30",
         "default_pause": 30}
    assert _prefill("2026-03-02", "2026-03-02", settings=s).days == {"2026-03-02": 480}


def test_standard_minutes_never_negative():
    s = {**SETTINGS, "default_start_mon": "16:00", "default_end_mon": "08:00"}
    assert sick_plan.standard_minutes(datetime.date(2026, 3, 2), s) == 0
    s = {**SETTINGS, "default_start_mon": "xx", "default_end_mon": ""}
    assert sick_plan.standard_minutes(datetime.date(2026, 3, 2), s) == 0
    s = {**SETTINGS, "default_start_mon": "08:00", "default_end_mon": "09:00",
         "default_pause": 90}
    assert sick_plan.standard_minutes(datetime.date(2026, 3, 2), s) == 0


def test_average_spreads_over_workdays():
    assert _avg() == 288
    p = _prefill("2026-03-16", "2026-03-20", basis="average_3m",
                 entries=_avg_entries(), settings={**SETTINGS, "state": ""})
    assert p.basis_used == "average_3m"
    assert sum(p.days.values()) == 1440


def test_average_excludes_vacation_and_sick_days():
    assert _avg(vacation_days={"2026-03-03": 480}) == 2880 // 9
    assert _avg(sick_days={"2026-03-05": 450}) == 2880 // 9


def test_average_counts_weekend_work():
    e = _avg_entries()
    e["2026-03-07"] = {"slots": [_slot("08:00", "12:00")]}
    assert _avg(entries=e) == 3120 // 10


def test_average_skips_holidays_in_denominator():
    e = _entries("2026-01-05", "2026-01-06", "2026-01-07", "2026-01-08",
                 "2026-01-09", slot=_slot("08:00", "16:00"))
    assert _avg("2026-01-19", entries=e, state="BY") == 2400 // 9 == 266


def test_reference_period_three_months_back_across_year():
    e = _entries("2025-01-01")
    r = sick_plan.reference_period(datetime.date(2026, 1, 10), e)
    assert r == (datetime.date(2025, 10, 10), datetime.date(2026, 1, 9))


def test_reference_period_clamps_to_month_length():
    e = _entries("2025-01-01")
    r = sick_plan.reference_period(datetime.date(2026, 5, 31), e)
    assert r == (datetime.date(2026, 2, 28), datetime.date(2026, 5, 30))


def test_reference_period_starts_at_first_recorded_day():
    e = _entries("2026-02-10", "2026-02-20")
    e["2026-01-15"] = {"slots": []}
    e["kaputt"] = {"slots": [_slot()]}
    r = sick_plan.reference_period(datetime.date(2026, 3, 2), e)
    assert r == (datetime.date(2026, 2, 10), datetime.date(2026, 3, 1))
    assert sick_plan.reference_period(datetime.date(2026, 2, 10), e) is None
    assert sick_plan.reference_period(datetime.date(2026, 3, 2), {}) is None


def test_average_none_without_worktime_falls_back_with_hint():
    p = _prefill("2026-03-02", "2026-03-02", basis="average_3m")
    assert p.basis_used == "standard"
    assert sick_plan.HINT_AVERAGE_FALLBACK in p.hints
    assert p.days == {"2026-03-02": 480}


def test_average_floors_and_caps():
    e = {"2026-03-02": {"slots": [_slot("00:00", "08:21")]},
         "2026-03-03": {"slots": [_slot("00:00", "08:20")]}}
    assert _avg("2026-03-04", entries=e) == 500
    big = {"2026-03-02": {"slots": [_slot("00:00", "23:59"),
                                    _slot("00:00", "23:59")]}}
    assert _avg("2026-03-03", entries=big) == 1440


def test_average_ignores_malformed_slots():
    e = _avg_entries()
    e["2026-03-10"] = {"slots": [
        {"start": "08:00"},
        {"start": "08:00", "end": "16:00", "pause": None}]}
    assert _avg(entries=e) == 288


def test_prefill_unknown_basis_counts_as_standard():
    p = _prefill("2026-03-02", "2026-03-02", basis="kaputt",
                 entries=_avg_entries())
    assert p.basis_used == "standard"
    assert p.days == {"2026-03-02": 480}
    assert sick_plan.HINT_AVERAGE_FALLBACK not in p.hints


def test_plan_rejects_reversed_range_and_too_long_block():
    r = sick_plan.plan_sick_save("2026-03-05", "2026-03-04", {}, {})
    assert r["error"] == "Das Bis-Datum liegt vor dem Von-Datum."
    start = datetime.date(2026, 1, 1)

    def block(n):
        end = (start + datetime.timedelta(days=n - 1)).isoformat()
        return sick_plan.plan_sick_save("2026-01-01", end, {}, {})
    assert block(367)["error"] == (
        "Ein Krankheitszeitraum darf höchstens 366 Tage umfassen.")
    assert block(366)["error"] is None


def test_plan_overrides_win_inside_range_only():
    pre = {"2026-03-02": 480, "2026-03-03": 480}
    r = sick_plan.plan_sick_save(
        "2026-03-02", "2026-03-03", pre,
        {"2026-03-02": 120, "2026-03-09": 60, "2026-03-03": -5})
    assert r == {"error": None, "days": {"2026-03-02": 120, "2026-03-03": 0}}


def test_plan_rejects_override_above_24h():
    pre = {"2026-03-02": 480}
    r = sick_plan.plan_sick_save("2026-03-02", "2026-03-02", pre,
                                 {"2026-03-02": 1441})
    assert r["error"].startswith(
        "Für diese Tage sind mehr als 24 Stunden eingetragen:")
    assert r["days"] == {}


def test_work_blocking_days_only_counts_days_with_minutes():
    e = _entries("2026-03-06", "2026-03-07", "2026-03-04")
    days = {"2026-03-06": 480, "2026-03-07": 0, "2026-03-08": 480}
    assert sick_plan.work_blocking_days(days, e) == ["2026-03-06"]


def test_sick_blocking_vacation():
    vac = {"2026-03-02": 480, "2026-03-03": 0, "2026-03-04": 480}
    sick = {"2026-03-04": 450, "2026-03-03": 450, "2026-03-02": 0}
    assert sick_plan.sick_blocking_vacation(vac, sick) == ["2026-03-04"]


def test_block_hints_six_weeks_from_43_days():
    d42 = {f"d{i}": 0 for i in range(42)}
    assert sick_plan.block_hints(d42) == [sick_plan.HINT_SUGGESTION]
    d43 = {f"d{i}": 0 for i in range(43)}
    assert sick_plan.block_hints(d43) == [sick_plan.HINT_SIX_WEEKS,
                                          sick_plan.HINT_SUGGESTION]


def test_reservation_net_minutes_ignores_broken():
    assert sick_plan.reservation_net_minutes(None) == 0
    r = {"slots": [_slot("09:00", "13:00", 30), {"start": "x"},
                   {"start": "08:00", "end": "09:00", "pause": None}]}
    assert sick_plan.reservation_net_minutes(r) == 210
    assert sick_plan.reservation_net_minutes(
        {"slots": [{"start": "09:00", "end": "13:00"}]}) == 240


@pytest.mark.parametrize("bad", ["x", None])
def test_reference_period_ignores_non_date_keys(bad):
    e = {bad: {"slots": [_slot()]}}
    assert sick_plan.reference_period(datetime.date(2026, 3, 2), e) is None
