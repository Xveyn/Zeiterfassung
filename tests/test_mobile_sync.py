# tests/test_mobile_sync.py
import datetime
import json

import pytest

from src import mobile_sync
from src.mobile_sync import SyncError

NOW = "2026-10-08T12:00:00Z"
TODAY = datetime.date(2026, 10, 8)
SLOT = {"start": "08:00", "end": "12:00", "pause": 0, "kategorie": "Projekt"}


def body(entries=None, **over):
    doc = {"protocol": 1, "client_time": NOW, "last_pull_at": "", "entries": {} if entries is None else entries}
    doc.update(over)
    return json.dumps(doc).encode()


def day(*, slots=(SLOT,), modified_at="2026-10-07T18:30:00Z", deleted=False, **extra):
    return {"slots": list(slots), "modified_at": modified_at, "deleted": deleted, **extra}


def tomb(modified_at="2026-10-07T18:30:00Z"):
    return day(slots=(), modified_at=modified_at, deleted=True)


def parse(entries=None, **over):
    return mobile_sync.parse_request(body(entries, **over), now=NOW)


def rejected(raw_body):
    with pytest.raises(SyncError) as excinfo:
        mobile_sync.parse_request(raw_body, now=NOW)
    return excinfo.value


# --- Form des Requests ------------------------------------------------------------------------

def test_a_valid_request_is_parsed_without_a_device_id():
    request = parse({"2026-10-07": day(device_id="evil"), "2026-10-06": tomb()})

    assert request.client_time == NOW
    assert request.entries["2026-10-07"] == {
        "slots": [SLOT], "modified_at": "2026-10-07T18:30:00Z", "deleted": False}
    assert request.entries["2026-10-06"] == {
        "slots": [], "modified_at": "2026-10-07T18:30:00Z", "deleted": True}


def test_a_request_without_entries_is_fine():
    doc = json.loads(body())
    del doc["entries"]
    assert mobile_sync.parse_request(json.dumps(doc).encode(), now=NOW).entries == {}


@pytest.mark.parametrize("raw", [
    b"{kaputt", b"[]", b'"text"', b"\xff", b'{"protocol": NaN}', pytest.param(b"[" * 100000, id="deep-nesting"),
    body(client_time="gestern"), body(client_time=None), body(client_time="2026-10-08 12:00:00"),
    body(entries=[]), body(entries="x"),
    b'{"protocol":1,"client_time":"' + NOW.encode() + b'","entries":{"2026-10-07":{},"2026-10-07":{}}}',
])
def test_a_malformed_request_is_400_invalid_json(raw):
    error = rejected(raw)
    assert (error.status, error.code) == (400, "invalid_json") and error.message


@pytest.mark.parametrize("protocol", [None, 0, 2, "1", 1.0, True, [1]])
def test_a_wrong_protocol_is_400_invalid_protocol(protocol):
    error = rejected(body(protocol=protocol))
    assert (error.status, error.code) == (400, "invalid_protocol")


def test_a_missing_protocol_is_400_invalid_protocol():
    doc = json.loads(body())
    del doc["protocol"]
    assert rejected(json.dumps(doc).encode()).code == "invalid_protocol"


# --- Uhr ---------------------------------------------------------------------------------------------

@pytest.mark.parametrize("client_time,ok", [
    ("2026-10-08T12:15:00Z", True), ("2026-10-08T11:45:00Z", True),
    ("2026-10-08T12:15:01Z", False), ("2026-10-08T11:44:59Z", False),
])
def test_the_clock_skew_limit_is_fifteen_minutes(client_time, ok):
    if ok:
        assert parse(client_time=client_time).client_time == client_time
    else:
        error = rejected(body(client_time=client_time))
        assert (error.status, error.code) == (409, "clock_skew")


def test_a_skewed_clock_is_reported_as_skew_not_as_an_invalid_entry():
    late = "2026-10-08T13:00:00Z"
    error = rejected(body({"2026-10-08": day(modified_at=late)}, client_time=late))
    assert (error.status, error.code) == (409, "clock_skew")


@pytest.mark.parametrize("modified_at,ok", [
    ("2026-10-08T12:15:00Z", True), ("2026-10-08T12:15:01Z", False),
])
def test_a_modified_at_in_the_future_is_rejected(modified_at, ok):
    entries = {"2026-10-08": day(modified_at=modified_at)}
    if ok:
        assert parse(entries).entries["2026-10-08"]["modified_at"] == modified_at
    else:
        assert rejected(body(entries)).code == "invalid_entry"


# --- Einträge ----------------------------------------------------------------------------------------

@pytest.mark.parametrize("key", [
    "2026-02-30", "20261007", "2026-10-7", "٢٠٢٦-١٠-٠٧", "1999-12-31", "2101-01-01",
    "2026-10-07 ", "", "\ud800", "x" * 5000,
])
def test_a_bad_date_key_is_422_with_the_date_in_the_message(key):
    error = rejected(body({key: day()}))
    assert (error.status, error.code) == (422, "invalid_entry")
    error.message.encode("utf-8")                       # nie ein Surrogat in der Antwort
    assert len(error.message) < 200


@pytest.mark.parametrize("entry", [
    5, None, [], "x",
    {"slots": [SLOT], "modified_at": "2026-10-07T18:30:00Z"},                              # deleted fehlt
    day(deleted="nein"), day(deleted=1),
    day(modified_at="2026-10-07 18:30:00"), day(modified_at="2026-10-07T18:30:00+00:00"),
    day(modified_at="٢026-10-07T18:30:00Z"), day(modified_at=None), day(modified_at="2026-13-07T18:30:00Z"),
    {"slots": "x", "modified_at": "2026-10-07T18:30:00Z", "deleted": False},
    day(slots=()),                                                  # lebender Tag ohne Slots
    day(slots=(SLOT,), deleted=True),                               # Tombstone mit Slots
    day(slots=({"start": "09:00", "end": "08:00"},)),
    day(slots=({"start": "08:00", "end": "12:00", "pause": "x"},)),
    day(slots=({"start": "08:00", "end": "12:00", "kategorie": "a\x00b"},)),
    day(slots=({"start": "08:00", "end": "12:00", "extra": 1},)),
    day(slots=({"start": "08:00", "end": "10:00"}, {"start": "09:00", "end": "11:00"})),
    day(slots=({"start": "00:00", "end": "00:01"},) * 51),
])
def test_a_bad_entry_is_422_invalid_entry(entry):
    error = rejected(body({"2026-10-07": entry}))
    assert (error.status, error.code) == (422, "invalid_entry")
    assert error.message.startswith("2026-10-07:")


def test_one_bad_day_rejects_the_whole_request():
    error = rejected(body({"2026-10-07": day(), "2026-10-06": day(slots=())}))
    assert error.code == "invalid_entry"


def test_at_most_400_days_per_request():
    dates = [(TODAY - datetime.timedelta(days=i)).isoformat() for i in range(401)]
    assert len(parse({d: day() for d in dates[:400]}).entries) == 400
    error = rejected(body({d: day() for d in dates}))
    assert (error.status, error.code) == (422, "invalid_entry")
