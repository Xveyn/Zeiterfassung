# tests/test_api_vacation_write.py
"""Body-Parser für POST /v1/vacations (#239, PR 7)."""
import json

import pytest

from src.api_entry_write import WriteError
from src.api_vacation_write import MAX_PERIOD_DAYS, parse_vacation_body


def body(**fields):
    base = {"name": "Sommer", "from": "2026-07-06", "to": "2026-07-17", "hours_per_day": 8}
    base.update(fields)
    return json.dumps({k: v for k, v in base.items() if v is not None}).encode()


def fails(raw, status, code):
    with pytest.raises(WriteError) as info:
        parse_vacation_body(raw)
    assert (info.value.status, info.value.code) == (status, code)


def test_hours_per_day_is_the_per_day_mode_with_a_value_in_hours():
    request = parse_vacation_body(body())

    assert request.name == "Sommer"
    assert (request.date_from, request.date_to) == ("2026-07-06", "2026-07-17")
    assert (request.mode, request.value, request.overrides) == ("per_day", 8.0, {})


def test_total_hours_is_the_total_mode():
    request = parse_vacation_body(body(hours_per_day=None, total_hours=80))
    assert (request.mode, request.value) == ("total", 80.0)


def test_day_hours_become_minute_overrides():
    request = parse_vacation_body(body(day_hours={"2026-07-10": 4, "2026-07-13": 7.5}))
    assert request.overrides == {"2026-07-10": 240, "2026-07-13": 450}


def test_the_name_is_trimmed():
    assert parse_vacation_body(body(name="  Sommer  ")).name == "Sommer"


def test_decimal_hours_are_taken_as_they_are():
    assert parse_vacation_body(body(hours_per_day=7.5)).value == 7.5


@pytest.mark.parametrize("raw", [b"{", b"[]", b'"x"'])
def test_a_wrong_body_is_400(raw):
    with pytest.raises(WriteError) as info:
        parse_vacation_body(raw)
    assert info.value.status == 400


@pytest.mark.parametrize("fields", [
    {"name": None}, {"from": None}, {"to": None},
    {"hours_per_day": None},                                   # weder noch
    {"total_hours": 40},                                       # beides
    {"unbekannt": 1},
])
def test_missing_conflicting_or_unknown_fields_are_400(fields):
    fails(body(**fields), 400, "invalid_body")


@pytest.mark.parametrize("name", ["", "   ", 5, "a\x00b", "x" * 101])
def test_a_bad_name_is_422(name):
    fails(body(name=name), 422, "invalid_name")


@pytest.mark.parametrize("field,value", [
    ("from", "2026-7-6"), ("from", "20260706"), ("from", "2026-02-30"), ("to", 5),
])
def test_bad_dates_are_422(field, value):
    fails(body(**{field: value}), 422, "invalid_date")


def test_years_outside_2000_to_2100_are_422():
    fails(body(**{"from": "1999-12-30", "to": "2000-01-02"}), 422, "date_out_of_range")


def test_a_period_longer_than_the_limit_is_422():
    fails(body(**{"from": "2026-01-01", "to": "2027-03-01"}), 422, "period_too_long")
    assert MAX_PERIOD_DAYS == 366
    parse_vacation_body(body(**{"from": "2026-01-01", "to": "2026-12-31"}))


def test_an_inverted_range_is_left_to_the_planner():
    # Die Meldung „Bis-Datum liegt vor Von-Datum“ kommt aus plan_vacation_save.
    request = parse_vacation_body(body(**{"from": "2026-07-17", "to": "2026-07-06"}))
    assert request.date_from > request.date_to


@pytest.mark.parametrize("field", ["hours_per_day", "total_hours"])
@pytest.mark.parametrize("value", ["8", True, None, [8], {"a": 1}])
def test_hours_must_be_numbers(field, value):
    fields = {"hours_per_day": None, "total_hours": None, field: value}
    raw = json.dumps({"name": "S", "from": "2026-07-06", "to": "2026-07-10", **fields}).encode()
    with pytest.raises(WriteError) as info:
        parse_vacation_body(raw)
    assert info.value.status in (400, 422)


def test_infinite_hours_are_refused():
    raw = (b'{"name": "S", "from": "2026-07-06", "to": "2026-07-10", "hours_per_day": 1e999}')
    fails(raw, 422, "invalid_hours")


def test_negative_hours_are_left_to_the_planner():
    assert parse_vacation_body(body(hours_per_day=-1)).value == -1.0


@pytest.mark.parametrize("day_hours", [
    {"2026-07-10": "4"}, {"2026-07-10": -1}, {"2026-07-10": True}, {"x": 4}, [4], {"2026-07-10": float("inf")},
])
def test_bad_day_hours_are_422(day_hours):
    raw = json.dumps({"name": "S", "from": "2026-07-06", "to": "2026-07-17",
                      "hours_per_day": 8, "day_hours": day_hours}, allow_nan=True).encode()
    with pytest.raises(WriteError) as info:
        parse_vacation_body(raw)
    assert info.value.status in (400, 422)


def test_day_hours_outside_the_period_are_refused_not_ignored():
    fails(body(day_hours={"2026-08-03": 4}), 422, "invalid_day_hours")
