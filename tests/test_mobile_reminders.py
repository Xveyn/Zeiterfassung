"""Der Block `reminders` der Handy-Antwort und das Relay-Geheimnis der Anfrage (#331)."""
import datetime
import itertools

import pytest

from src.mobile_reminders import RELAY_SECRET_RE, build_block, parse_push, phone_covers
from src.settings import Settings

NOW = datetime.datetime(2026, 10, 22, 8, 0)
PLUS2 = datetime.timezone(datetime.timedelta(hours=2))
SECRET = "Q" * 43


class FakeReservations:
    def __init__(self, raw=None):
        self._raw = raw or {}

    def get_all_raw(self):
        return self._raw


_files = itertools.count()


def make_settings(tmp_path, **values):
    # Jeder Aufruf eine eigene Datei: sonst erbte er die Werte des vorigen im selben Test.
    settings = Settings(str(tmp_path / f"settings{next(_files)}.json"))
    for key, value in values.items():
        settings.set(key, value)
    return settings


def block(tmp_path, reservations=None, **values):
    return build_block(make_settings(tmp_path, **values), reservations, NOW, tz=PLUS2)


OFF = {"reservation": {"enabled": False, "minutes_before": 15}, "send": {"enabled": False, "at": []}}


def test_everything_off_is_a_complete_block_not_a_missing_one(tmp_path):
    assert block(tmp_path) == OFF


def test_reservation_reminder_needs_the_switch_the_tick_and_reservations(tmp_path):
    on = {"mobile_push_enabled": True, "reservations_enabled": True, "reminder_minutes_before": 20}
    assert block(tmp_path, **on)["reservation"] == {"enabled": True, "minutes_before": 20}
    for off in ({"mobile_push_enabled": False}, {"mobile_push_reservation": False},
                {"reservations_enabled": False}):
        assert block(tmp_path, **{**on, **off})["reservation"]["enabled"] is False, off


def test_the_toast_switch_does_not_gate_the_phone(tmp_path):
    out = block(tmp_path, mobile_push_enabled=True, reservations_enabled=True, reminders_enabled=False)
    assert out["reservation"]["enabled"] is True


def test_send_reminder_covers_monthly_and_day_bound(tmp_path):
    base = {"mobile_push_enabled": True, "send_reminder_day": 28, "send_reminder_time": "18:00"}
    assert block(tmp_path, **base)["send"] == {"enabled": False, "at": []}
    monthly = block(tmp_path, send_reminder_enabled=True, **base)["send"]
    assert monthly["enabled"] is True and monthly["at"][0] == "2026-10-28T16:00:00Z"
    reservations = FakeReservations({"2026-10-23": {"deleted": False, "slots": [
        {"start": "09:00", "end": "12:00", "kategorie": "P", "send_reminder_minutes": 30}]}})
    day = block(tmp_path, reservations, send_reminder_reservations_enabled=True,
                reservations_enabled=True, **base)["send"]
    assert day["enabled"] is True and day["at"] == ["2026-10-23T09:30:00Z"]


def test_day_bound_times_need_reservations_and_ignore_tombstones(tmp_path):
    raw = {"2026-10-23": {"deleted": True, "slots": [
        {"start": "09:00", "end": "12:00", "kategorie": "P", "send_reminder_minutes": 30}]},
           "2026-10-24": {"deleted": False, "slots": [
               {"start": "09:00", "end": "12:00", "kategorie": "P", "send_reminder_minutes": 30}]}}
    on = {"mobile_push_enabled": True, "send_reminder_reservations_enabled": True}
    assert block(tmp_path, FakeReservations(raw), reservations_enabled=True, **on)["send"]["at"] == ["2026-10-24T09:30:00Z"]
    assert block(tmp_path, FakeReservations(raw), reservations_enabled=False, **on)["send"] == {"enabled": False, "at": []}
    assert block(tmp_path, None, reservations_enabled=True, **on)["send"]["at"] == []


def test_the_send_switch_off_empties_the_list(tmp_path):
    out = block(tmp_path, mobile_push_enabled=True, mobile_push_send=False, send_reminder_enabled=True)
    assert out["send"] == {"enabled": False, "at": []}


def test_unusable_minutes_fall_back(tmp_path):
    out = block(tmp_path, mobile_push_enabled=True, reservations_enabled=True, reminder_minutes_before=-3)
    assert out["reservation"]["minutes_before"] == 15


# --- Relay-Geheimnis --------------------------------------------------------------------------

def test_a_valid_secret_is_read():
    assert parse_push({"relay_secret": SECRET}) == SECRET
    assert RELAY_SECRET_RE.fullmatch("A-_" + "b" * 40)


@pytest.mark.parametrize("raw", [None, 5, "x", [], {}, {"relay_secret": None}, {"relay_secret": 5},
                                 {"relay_secret": "Q" * 42}, {"relay_secret": "Q" * 44},
                                 {"relay_secret": "Q" * 42 + "="}, {"relay_secret": "Q" * 42 + " "},
                                 {"relay_secret": "Q" * 42 + "\n"}, {"relay_secret": "ä" * 43}])
def test_everything_else_is_discarded(raw):
    assert parse_push(raw) is None


# --- Toast unterdrücken ---------------------------------------------------------------------------

def covers(tmp_path, kind="reservation", ids=("d1",), **values):
    base = {"mobile_push_enabled": True, "mobile_push_suppress_toast": True, "reservations_enabled": True}
    return phone_covers(make_settings(tmp_path, **{**base, **values}), ids, kind)


def test_phone_covers_when_every_condition_holds(tmp_path):
    assert covers(tmp_path) is True
    assert covers(tmp_path, kind="send") is True


@pytest.mark.parametrize("override", [
    {"mobile_push_enabled": False}, {"mobile_push_suppress_toast": False},
    {"mobile_push_reservation": False}, {"reservations_enabled": False}])
def test_phone_does_not_cover_a_reservation_toast_when_a_condition_fails(tmp_path, override):
    assert covers(tmp_path, **override) is False


def test_phone_does_not_cover_without_a_known_device(tmp_path):
    assert covers(tmp_path, ids=()) is False


def test_the_send_kind_has_its_own_tick(tmp_path):
    assert covers(tmp_path, kind="send", mobile_push_send=False) is False
    assert covers(tmp_path, kind="send", reservations_enabled=False) is True
