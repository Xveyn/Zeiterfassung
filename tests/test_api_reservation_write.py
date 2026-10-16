# tests/test_api_reservation_write.py
"""Body-Parser und Datumsregeln für Reservierungen in der lokalen API (#239)."""
import datetime
import json

import pytest

from src.api_entry_write import WriteError
from src.api_reservation_write import (
    HORIZON_DAYS, check_reservation_day, parse_reservation_body,
)

TODAY = datetime.date(2026, 10, 14)


def body(slots):
    return json.dumps({"slots": slots}).encode()


def parse(slots):
    return parse_reservation_body(body(slots))


def fails(slots_or_bytes, status, code):
    raw = slots_or_bytes if isinstance(slots_or_bytes, bytes) else body(slots_or_bytes)
    with pytest.raises(WriteError) as info:
        parse_reservation_body(raw)
    assert (info.value.status, info.value.code) == (status, code)


def test_a_slot_gets_the_three_reservation_fields_and_no_pause():
    slots, given = parse([{"start": "08:00", "end": "12:00", "kategorie": "Projekt"}])

    assert slots == [{"start": "08:00", "end": "12:00", "kategorie": "Projekt",
                      "send_reminder_minutes": None}]
    assert given is False


def test_kategorie_defaults_to_empty():
    slots, _ = parse([{"start": "08:00", "end": "09:00"}])
    assert slots[0]["kategorie"] == ""


def test_reminder_minutes_are_taken_and_reported_as_given():
    slots, given = parse([{"start": "08:00", "end": "12:00", "send_reminder_minutes": 15},
                          {"start": "13:00", "end": "17:00"}])

    assert [s["send_reminder_minutes"] for s in slots] == [15, None]
    assert given is True


def test_an_explicit_null_counts_as_given_so_a_script_can_clear_the_marker():
    slots, given = parse([{"start": "08:00", "end": "12:00", "send_reminder_minutes": None}])

    assert slots[0]["send_reminder_minutes"] is None
    assert given is True


@pytest.mark.parametrize("value", [-1, 121, 1.5, "15", True, [15]])
def test_reminder_minutes_must_be_an_int_between_0_and_120(value):
    fails([{"start": "08:00", "end": "12:00", "send_reminder_minutes": value}],
          422, "invalid_reminder")


def test_at_most_one_slot_per_day_may_carry_a_reminder():
    fails([{"start": "08:00", "end": "12:00", "send_reminder_minutes": 10},
           {"start": "13:00", "end": "17:00", "send_reminder_minutes": 10}],
          422, "invalid_reminder")


def test_pause_does_not_exist_for_reservations():
    fails([{"start": "08:00", "end": "12:00", "pause": 30}], 422, "invalid_slot")


def test_gcal_event_id_is_never_accepted():
    fails([{"start": "08:00", "end": "12:00", "gcal_event_id": "x"}], 422, "invalid_slot")


@pytest.mark.parametrize("slots,code", [
    ([{"start": "8:00", "end": "12:00"}], "invalid_time"),
    ([{"start": "12:00", "end": "08:00"}], "invalid_slots"),
    ([{"start": "08:00", "end": "12:00"}, {"start": "11:00", "end": "13:00"}], "invalid_slots"),
    (["x"], "invalid_slot"),
    ([{"start": "08:00", "end": "12:00", "kategorie": "Office*"}], "invalid_category"),
])
def test_slots_follow_the_rules_of_the_actual_hours(slots, code):
    fails(slots, 422, code)


def test_an_empty_list_is_refused_with_a_hint_to_delete():
    fails([], 422, "empty_slots")


@pytest.mark.parametrize("raw", [b"{", b'{"slots": 1}', b'{"slots": [], "x": 1}', b"[]"])
def test_a_wrong_body_shape_is_400(raw):
    with pytest.raises(WriteError) as info:
        parse_reservation_body(raw)
    assert info.value.status == 400


def test_today_and_the_horizon_are_allowed():
    check_reservation_day(TODAY, TODAY)
    check_reservation_day(TODAY + datetime.timedelta(days=HORIZON_DAYS), TODAY)


def test_a_past_day_is_422():
    with pytest.raises(WriteError) as info:
        check_reservation_day(TODAY - datetime.timedelta(days=1), TODAY)
    assert (info.value.status, info.value.code) == (422, "date_in_past")


def test_beyond_the_horizon_is_422():
    with pytest.raises(WriteError) as info:
        check_reservation_day(TODAY + datetime.timedelta(days=HORIZON_DAYS + 1), TODAY)
    assert (info.value.status, info.value.code) == (422, "date_too_far")
