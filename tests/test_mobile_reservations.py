# tests/test_mobile_reservations.py
import datetime

import pytest

from src import mobile_reservations as mr

TODAY = datetime.date(2026, 10, 13)
NOW = datetime.datetime(2026, 10, 13, 12, 0, 0)
SLOT = {"start": "09:00", "end": "12:00", "kategorie": "Projekt"}
STAMP = "2026-10-13T11:00:00Z"


def parse_utc(text):
    try:
        return datetime.datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ")
    except (TypeError, ValueError):
        return None


def parse(raw):
    return mr.parse_reservations(raw, today=TODAY, now_dt=NOW, parse_utc=parse_utc,
                                 skew_limit=datetime.timedelta(minutes=15))


def day(*slots, modified_at=STAMP, deleted=False, **extra):
    return {"slots": list(slots), "modified_at": modified_at, "deleted": deleted, **extra}


def test_a_valid_day_is_parsed_to_the_three_phone_fields():
    out = parse({"2026-10-20": day({**SLOT, "pause": 30})})

    assert out == {"2026-10-20": {"slots": [SLOT], "modified_at": STAMP, "deleted": False}}


def test_unknown_day_fields_are_dropped():
    out = parse({"2026-10-20": day(SLOT, send_reminder_minutes=15, device_id="x")})

    assert out == {"2026-10-20": {"slots": [SLOT], "modified_at": STAMP, "deleted": False}}


def test_today_and_today_plus_365_are_allowed_and_the_day_after_is_not():
    last = (TODAY + datetime.timedelta(days=365)).isoformat()
    assert last in parse({TODAY.isoformat(): day(SLOT), last: day(SLOT)})
    with pytest.raises(mr.ReservationError):
        parse({(TODAY + datetime.timedelta(days=366)).isoformat(): day(SLOT)})


def test_a_day_before_today_is_rejected():
    with pytest.raises(mr.ReservationError) as excinfo:
        parse({(TODAY - datetime.timedelta(days=1)).isoformat(): day(SLOT)})
    assert "2026-10-12" in excinfo.value.message


@pytest.mark.parametrize("entry", [
    day({**SLOT, "send_reminder_minutes": 15}),        # Feld gehört dem Desktop
    day({**SLOT, "gcal_event_id": "x"}),               # ebenso
    day(),                                              # lebender Tag ohne Slots
    day(SLOT, deleted=True),                            # Tombstone mit Slots
    day(SLOT, modified_at="2026-10-13T12:20:00Z"),     # 20 Minuten in der Zukunft
    day(SLOT, modified_at="gestern"),
    day({**SLOT, "start": "25:00"}),
    "kein Objekt",
])
def test_a_bad_day_is_rejected(entry):
    with pytest.raises(mr.ReservationError):
        parse({"2026-10-20": entry})


def test_a_tombstone_carries_no_slots():
    out = parse({"2026-10-20": day(deleted=True)})
    assert out["2026-10-20"] == {"slots": [], "modified_at": STAMP, "deleted": True}


def test_more_than_the_cap_is_rejected():
    raw = {f"k{i}": day(SLOT) for i in range(mr.MAX_RESERVATIONS + 1)}
    with pytest.raises(mr.ReservationError):
        parse(raw)


def test_a_non_object_is_rejected():
    with pytest.raises(mr.ReservationError):
        parse(["2026-10-20"])


def test_build_returns_active_days_from_today_through_the_horizon_only():
    store = {
        "2026-10-12": {"slots": [dict(SLOT, gcal_event_id=None, send_reminder_minutes=None)],
                       "modified_at": STAMP, "deleted": False},          # gestern
        "2026-10-13": {"slots": [dict(SLOT, gcal_event_id="e", send_reminder_minutes=15)],
                       "modified_at": STAMP, "deleted": False},          # heute
        "2026-10-14": {"slots": [], "modified_at": STAMP, "deleted": True},   # Tombstone
        "2027-10-14": {"slots": [dict(SLOT)], "modified_at": STAMP, "deleted": False},  # > 365
    }

    out = mr.build_reservations(store, today=TODAY)

    assert out == {"2026-10-13": {"slots": [SLOT], "modified_at": STAMP, "deleted": False}}


def test_build_drops_unusable_slots_and_days_and_never_leaks_desktop_fields():
    store = {
        "2026-10-20": {"slots": [{"start": "09:00", "end": "kaputt", "kategorie": "x"},
                                 {"start": "10:00", "end": "11:00", "kategorie": 5,
                                  "gcal_event_id": "e"}],
                       "modified_at": STAMP, "deleted": False},
        "2026-10-21": {"slots": ["kein Objekt"], "modified_at": STAMP, "deleted": False},
        "kein-datum": {"slots": [dict(SLOT)], "modified_at": STAMP, "deleted": False},
    }

    out = mr.build_reservations(store, today=TODAY)

    assert out == {"2026-10-20": {"slots": [{"start": "10:00", "end": "11:00", "kategorie": ""}],
                                  "modified_at": STAMP, "deleted": False}}
