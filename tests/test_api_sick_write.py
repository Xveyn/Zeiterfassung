# tests/test_api_sick_write.py
"""Body-Parser für POST /v1/sick."""
import json

import pytest

from src.api_entry_write import WriteError
from src.api_sick_write import parse_sick_body


def body(**fields):
    base = {"from": "2026-07-06", "to": "2026-07-10"}
    base.update(fields)
    return json.dumps({k: v for k, v in base.items() if v is not None}).encode()


def fails(raw, status, code):
    with pytest.raises(WriteError) as info:
        parse_sick_body(raw)
    assert (info.value.status, info.value.code) == (status, code)


def test_valid_body_with_defaults():
    request = parse_sick_body(body())
    assert (request.date_from, request.date_to) == ("2026-07-06", "2026-07-10")
    assert request.basis is None and request.overrides == {}


def test_basis_and_day_hours_are_read():
    request = parse_sick_body(body(basis="average_3m", day_hours={"2026-07-07": 4.5}))
    assert request.basis == "average_3m"
    assert request.overrides == {"2026-07-07": 270}


def test_unknown_or_missing_keys_are_invalid_body():
    fails(body(extra=1), 400, "invalid_body")
    fails(json.dumps({"from": "2026-07-06"}).encode(), 400, "invalid_body")


def test_unknown_basis_is_422():
    fails(body(basis="median"), 422, "invalid_basis")


def test_more_than_366_days_is_422():
    fails(body(to="2027-07-07"), 422, "period_too_long")
    parse_sick_body(body(to="2027-07-06"))


def test_day_hours_outside_period_or_range():
    fails(body(day_hours={"2026-08-01": 4}), 422, "invalid_day_hours")
    fails(body(day_hours={"2026-07-07": 25}), 422, "invalid_day_hours")
    fails(body(day_hours={"2026-07-07": -1}), 422, "invalid_day_hours")
    fails(body(day_hours=[1]), 422, "invalid_day_hours")
