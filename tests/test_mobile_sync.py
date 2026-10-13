# tests/test_mobile_sync.py
import datetime
import json
import os
import threading
import types

import pytest

from src import mobile_sync, sync_history, sync_journal
from src.conflicts_store import ConflictsStore
from src.mobile_sync import SyncError
from src.reservations import ReservationStore
from src.settings import Settings
from src.storage import Storage

NOW = "2026-10-08T12:00:00Z"
TODAY = datetime.date(2026, 10, 8)
SLOT = {"start": "08:00", "end": "12:00", "pause": 0, "kategorie": "Projekt"}


def body(entries=None, **over):
    doc = {"protocol": 2, "client_time": NOW, "last_pull_at": "", "entries": {} if entries is None else entries}
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
    b'{"protocol":2,"client_time":"' + NOW.encode() + b'","entries":{"2026-10-07":{},"2026-10-07":{}}}',
])
def test_a_malformed_request_is_400_invalid_json(raw):
    error = rejected(raw)
    assert (error.status, error.code) == (400, "invalid_json") and error.message


@pytest.mark.parametrize("protocol", [None, 0, 1, 3, "2", 2.0, True, [2]])
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


# --- build_response ----------------------------------------------------------------------------

def _entry(date, *, slots=(SLOT,), modified_at="2026-10-01T10:00:00Z", device="DESK", deleted=False):
    return {"slots": [dict(s) if isinstance(s, dict) else s for s in slots], "modified_at": modified_at,
            "device_id": device, "deleted": deleted}


def _iso(offset):
    return (TODAY + datetime.timedelta(days=offset)).isoformat()


DEFAULTS = {"pause": 30, "weekdays": {}, "category_times": {}}
DESKTOP = {"name": "PC", "version": "1.0.0", "platform": "Linux"}


def respond(merged, *, sent=(), excluded=False, categories=("Projekt",), window_days=90,
            window_max_days=365):
    merged = {"entries": {}, "conflicts": [], "devices": {}, **merged}
    return mobile_sync.build_response(merged, sent_dates=sent, today=TODAY, now=NOW,
                                      excluded=excluded, categories=list(categories),
                                      defaults=DEFAULTS, desktop=DESKTOP,
                                      window_days=window_days, window_max_days=window_max_days)


def test_the_response_carries_the_protocol_fields_and_no_token():
    response = respond({})

    assert response == {
        "protocol": 2, "server_time": NOW, "last_pull_at": NOW, "excluded": False,
        "window_days": 90, "window_max_days": 365, "entries": {}, "conflicts": [],
        "categories": ["Projekt"],
        "defaults": DEFAULTS, "desktop": DESKTOP}


def test_the_window_is_today_minus_90_days_through_today():
    merged = {"entries": {
        _iso(-91): _entry(_iso(-91)), _iso(-90): _entry(_iso(-90)),
        _iso(0): _entry(_iso(0)), _iso(1): _entry(_iso(1)),
        _iso(-30): _entry(_iso(-30), slots=(), deleted=True)}}

    entries = respond(merged)["entries"]

    assert sorted(entries) == sorted([_iso(-90), _iso(-30), _iso(0)])
    assert entries[_iso(-30)]["deleted"] is True            # Tombstones im Fenster reisen mit


def test_days_the_phone_sent_are_included_outside_the_window():
    merged = {"entries": {"2025-01-15": _entry("2025-01-15"), _iso(-200): _entry(_iso(-200))}}

    entries = respond(merged, sent=["2025-01-15"])["entries"]

    assert sorted(entries) == ["2025-01-15"]


def test_entries_are_sorted_and_use_only_the_four_entry_fields():
    merged = {"entries": {_iso(0): _entry(_iso(0)), _iso(-1): _entry(_iso(-1))}}

    entries = respond(merged)["entries"]

    assert list(entries) == [_iso(-1), _iso(0)]
    assert set(entries[_iso(0)]) == {"slots", "modified_at", "device_id", "deleted"}


def test_foreign_slot_values_are_sanitised_in_the_response():
    dirty = {"start": "08:00", "end": "12:00", "pause": "abc", "kategorie": 5, "send_reminder_minutes": 10}
    merged = {"entries": {_iso(0): _entry(_iso(0), slots=(dirty, "kein Objekt"))}}

    slots = respond(merged)["entries"][_iso(0)]["slots"]

    assert slots == [{"start": "08:00", "end": "12:00", "pause": 0, "kategorie": ""}]


def test_keys_that_are_not_a_date_are_left_out_of_the_response():
    merged = {"entries": {_iso(0): _entry(_iso(0)), _iso(0) + "x": _entry(_iso(0)),
                          "": _entry(_iso(0)), 5: _entry(_iso(0))}}

    assert list(respond(merged)["entries"]) == [_iso(0)]


def test_a_living_day_without_usable_slots_is_left_out_of_the_response():
    broken = {"slots": "nope", "modified_at": NOW, "device_id": "DESK", "deleted": False}
    merged = {"entries": {_iso(-1): broken, _iso(-2): _entry(_iso(-2), slots=("kein Objekt",)),
                          _iso(0): _entry(_iso(0))}}

    assert list(respond(merged)["entries"]) == [_iso(0)]


@pytest.mark.parametrize("flag", [0, "false", "yes", None, 1])
def test_deleted_is_true_only_for_the_boolean_true(flag):
    merged = {"entries": {_iso(0): _entry(_iso(0), deleted=flag)}}

    entry = respond(merged)["entries"][_iso(0)]

    assert entry["deleted"] is False and entry["slots"] == [SLOT]


def test_a_tombstone_never_carries_slots():
    merged = {"entries": {_iso(0): _entry(_iso(0), deleted=True)}}

    assert respond(merged)["entries"][_iso(0)] == {
        "slots": [], "modified_at": "2026-10-01T10:00:00Z", "device_id": "DESK", "deleted": True}


def test_a_sent_day_older_than_the_window_is_included_only_when_sent():
    old = "2025-01-15"
    merged = {"entries": {old: _entry(old)}}

    assert respond(merged)["entries"] == {}
    assert list(respond(merged, sent=[old])["entries"]) == [old]


def test_conflict_candidates_use_the_cleaned_slots():
    dirty = {"start": "08:00", "end": "12:00", "pause": "abc", "kategorie": 5, "send_reminder_minutes": 3}
    conflict = _conflict(_iso(-1))
    conflict["candidates"][0]["slots"] = [dirty, "kein Objekt"]

    versions = respond({"conflicts": [conflict]})["conflicts"][0]["versions"]

    assert versions[0]["slots"] == [{"start": "08:00", "end": "12:00", "pause": 0, "kategorie": ""}]


def test_conflicts_are_sorted_by_date():
    merged = {"conflicts": [_conflict(_iso(0)), _conflict(_iso(-2)), _conflict(_iso(-1))]}

    assert [c["date"] for c in respond(merged)["conflicts"]] == [_iso(-2), _iso(-1), _iso(0)]


def _conflict(key, *, resolved=False, kind="entry"):
    return {"id": f"c-{key}", "kind": kind, "key": key, "resolved": resolved,
            "candidates": [
                _entry(key, modified_at="2026-10-07T18:30:00Z", device="PHONE-0001"),
                _entry(key, slots=({"start": "09:00", "end": "13:00", "pause": 0, "kategorie": ""},),
                       modified_at="2026-10-07T20:00:00Z", device="DESK")]}


def test_a_conflict_whose_key_is_not_a_date_is_left_out():
    merged = {"conflicts": [_conflict(_iso(-1) + "x"), _conflict(_iso(-1))]}

    assert [c["date"] for c in respond(merged)["conflicts"]] == [_iso(-1)]


def test_open_entry_conflicts_in_the_window_are_listed_with_device_names():
    merged = {"conflicts": [_conflict(_iso(-1))],
              "devices": {"PHONE-0001": {"name": "Pixel", "updated_at": NOW}}}

    conflicts = respond(merged)["conflicts"]

    assert conflicts == [{"id": f"c-{_iso(-1)}", "date": _iso(-1), "versions": [
        {"device": "PHONE-0001", "name": "Pixel", "modified_at": "2026-10-07T18:30:00Z",
         "slots": [SLOT]},
        {"device": "DESK", "name": "", "modified_at": "2026-10-07T20:00:00Z",
         "slots": [{"start": "09:00", "end": "13:00", "pause": 0, "kategorie": ""}]}]}]


def test_resolved_setting_and_out_of_window_conflicts_are_left_out():
    merged = {"conflicts": [
        _conflict(_iso(-1), resolved=True), _conflict("recipient", kind="setting"),
        _conflict(_iso(-200)), _conflict("2025-01-15"), "kein Objekt", {"kind": "entry", "key": 5}]}

    assert [c["date"] for c in respond(merged, sent=["2025-01-15"])["conflicts"]] == ["2025-01-15"]


def test_the_excluded_flag_and_categories_are_passed_through():
    response = respond({}, excluded=True, categories=["A", "B"])
    assert response["excluded"] is True and response["categories"] == ["A", "B"]


# --- Reservierungen -------------------------------------------------------------------------------

RES = {"start": "09:00", "end": "12:00", "kategorie": "Projekt"}


def res_day(*, slots=(RES,), modified_at="2026-10-08T11:00:00Z", deleted=False):
    return {"slots": list(slots), "modified_at": modified_at, "deleted": deleted}


def test_reservations_are_parsed_next_to_the_entries():
    request = mobile_sync.parse_request(
        body({}, reservations={"2026-10-20": res_day()}), now=NOW, today=TODAY)

    assert request.reservations == {"2026-10-20": res_day()}


def test_a_request_without_reservations_has_none():
    assert parse({}).reservations == {}


def test_a_bad_reservation_is_422_invalid_entry_and_names_the_day():
    error = rejected(body({}, reservations={"2027-12-01": res_day()}))   # mehr als 365 Tage voraus

    assert (error.status, error.code) == (422, "invalid_entry")
    assert "2027-12-01" in error.message


def test_the_clock_check_comes_before_the_reservations():
    error = rejected(body({}, client_time="2026-10-08T13:00:00Z",
                          reservations={"2027-12-01": res_day()}))

    assert error.code == "clock_skew"


def test_reservations_are_ignored_not_rejected_when_the_feature_is_off():
    request = mobile_sync.parse_request(
        body({}, reservations={"2026-10-01": res_day(), "x": 1}), now=NOW, today=TODAY,
        accept_reservations=False)

    assert request.reservations == {}


# --- perform_sync ---------------------------------------------------------------------------------

PHONE = "phone-0001"


@pytest.fixture
def env(tmp_path):
    settings = Settings(str(tmp_path / "settings.json"))
    settings.device_id_for_sync = "DESK"
    return types.SimpleNamespace(
        storage=Storage(str(tmp_path / "zeiterfassung.json"), device_id="DESK"),
        settings=settings,
        conflicts=ConflictsStore(str(tmp_path / "conflicts.json")),
        base=str(tmp_path))


def put_desktop(env, date, *, slots=(SLOT,), modified_at, device="DESK", deleted=False):
    raw = dict(env.storage.get_all_raw())
    raw[date] = {"slots": [dict(s) for s in slots], "modified_at": modified_at,
                 "device_id": device, "deleted": deleted}
    env.storage.apply_merge(raw)


def run(env, entries, *, last_pull_at="", now=NOW, wish=None, **over):
    extra = {} if wish is None else {"window_days": wish}
    request = mobile_sync.parse_request(body(entries, **extra), now=now)
    kwargs = dict(device_id=PHONE, device_name="Pixel", last_pull_at=last_pull_at,
                  categories=["Projekt"], storage=env.storage, settings=env.settings,
                  conflicts_store=env.conflicts, base=env.base, now=now, today=TODAY,
                  desktop=DESKTOP)
    kwargs.update(over)
    return mobile_sync.perform_sync(request, **kwargs)


def test_a_new_day_from_the_phone_is_stored_under_the_device_of_the_token(env):
    response = run(env, {"2026-10-07": day(device_id="evil")})

    stored = env.storage.get_all_raw()["2026-10-07"]
    assert stored["device_id"] == PHONE and stored["slots"] == [SLOT] and not stored["deleted"]
    assert response["entries"]["2026-10-07"]["device_id"] == PHONE


def test_the_phone_appears_with_its_name_in_the_device_registry(env):
    run(env, {"2026-10-07": day()})
    assert env.settings.get("known_devices")[PHONE]["name"] == "Pixel"


def test_a_newer_phone_change_wins_without_a_conflict(env):
    put_desktop(env, "2026-10-07", modified_at="2026-10-01T10:00:00Z")

    run(env, {"2026-10-07": day(slots=({"start": "07:00", "end": "11:00"},),
                                modified_at="2026-10-07T18:30:00Z")},
        last_pull_at="2026-10-05T00:00:00Z")

    assert env.storage.get("2026-10-07")["slots"][0]["start"] == "07:00"
    assert env.conflicts.get_all() == []


def test_a_phone_tombstone_deletes_an_older_desktop_day(env):
    put_desktop(env, "2026-10-05", modified_at="2026-10-05T10:00:00Z")

    response = run(env, {"2026-10-05": tomb("2026-10-07T18:30:00Z")},
                   last_pull_at="2026-10-06T00:00:00Z")

    assert env.storage.get("2026-10-05") is None
    assert env.storage.get_all_raw()["2026-10-05"]["deleted"] is True
    assert response["entries"]["2026-10-05"]["deleted"] is True


def test_a_change_on_both_sides_becomes_a_conflict(env):
    put_desktop(env, "2026-10-07", modified_at="2026-10-07T20:00:00Z",
                slots=({"start": "09:00", "end": "13:00", "pause": 0, "kategorie": ""},))

    response = run(env, {"2026-10-07": day(modified_at="2026-10-07T18:30:00Z")},
                   last_pull_at="2026-10-06T00:00:00Z")

    stored = env.conflicts.get_all()
    assert len(stored) == 1 and stored[0]["key"] == "2026-10-07" and not stored[0]["resolved"]
    assert [c["date"] for c in response["conflicts"]] == ["2026-10-07"]
    assert {v["device"] for v in response["conflicts"][0]["versions"]} == {PHONE, "DESK"}
    assert response["entries"]["2026-10-07"]["slots"][0]["start"] == "09:00"    # LWW: der jüngere


def test_the_first_sync_turns_every_differing_day_into_a_conflict(env):
    put_desktop(env, "2026-10-07", modified_at="2026-10-01T10:00:00Z",
                slots=({"start": "09:00", "end": "13:00", "pause": 0, "kategorie": ""},))

    run(env, {"2026-10-07": day(modified_at="2026-10-07T18:30:00Z")}, last_pull_at="")

    assert len(env.conflicts.get_all()) == 1


def test_the_same_request_twice_changes_nothing_and_adds_no_conflict(env):
    put_desktop(env, "2026-10-07", modified_at="2026-10-07T20:00:00Z",
                slots=({"start": "09:00", "end": "13:00", "pause": 0, "kategorie": ""},))
    entries = {"2026-10-07": day(modified_at="2026-10-07T18:30:00Z"), "2026-10-06": day()}

    first = run(env, entries, last_pull_at="")
    stored = dict(env.storage.get_all_raw())
    second = run(env, entries, last_pull_at="")

    assert len(env.conflicts.get_all()) == 1
    assert env.storage.get_all_raw() == stored
    assert second["entries"] == first["entries"]


def test_a_phone_offline_longer_than_the_last_compaction_cannot_resurrect_a_day(env):
    env.settings.set("gc_watermark", "2026-10-01T00:00:00Z")

    response = run(env, {"2026-08-15": day(modified_at="2026-08-15T10:00:00Z")},
                   last_pull_at="2026-09-01T00:00:00Z")

    assert response["excluded"] is True
    assert "2026-08-15" not in env.storage.get_all_raw()
    assert "2026-08-15" not in response["entries"]


def test_excluded_is_false_without_or_after_the_watermark(env):
    env.settings.set("gc_watermark", "2026-10-01T00:00:00Z")
    assert run(env, {}, last_pull_at="")["excluded"] is False
    assert run(env, {}, last_pull_at="2026-10-02T00:00:00Z")["excluded"] is False


def test_a_successful_sync_leaves_no_journal_and_marks_the_machine_as_synced(env):
    assert not sync_history.ever_synced(env.base)

    run(env, {"2026-10-07": day()})

    assert sync_journal.JOURNAL_FILENAME not in os.listdir(env.base)
    assert sync_history.ever_synced(env.base)


def test_a_busy_guard_is_503_and_nothing_is_applied(env):
    guard = threading.Lock()
    guard.acquire()

    with pytest.raises(SyncError) as excinfo:
        run(env, {"2026-10-07": day()}, sync_guard=guard)

    assert (excinfo.value.status, excinfo.value.code) == (503, "busy")
    assert env.storage.get_all_raw() == {} and not sync_history.ever_synced(env.base)
    assert guard.locked()                                      # der fremde Halter bleibt Halter


def test_the_guard_is_released_after_success_and_after_an_error(env, monkeypatch):
    guard = threading.Lock()
    run(env, {"2026-10-07": day()}, sync_guard=guard)
    assert guard.acquire(blocking=False)
    guard.release()

    def boom(*args, **kwargs):
        raise RuntimeError("Platte voll")
    monkeypatch.setattr(sync_journal, "apply_merged_doc_journaled", boom)
    with pytest.raises(RuntimeError):
        run(env, {"2026-10-06": day()}, sync_guard=guard)
    assert guard.acquire(blocking=False)


def test_snapshot_merge_and_apply_run_under_the_data_lock(env, monkeypatch):
    lock = threading.RLock()
    seen = {}
    real = sync_journal.apply_merged_doc_journaled

    def spy(*args, **kwargs):
        seen["owned"] = lock._is_owned()
        return real(*args, **kwargs)
    monkeypatch.setattr(sync_journal, "apply_merged_doc_journaled", spy)

    run(env, {"2026-10-07": day()}, data_lock=lock)

    assert seen == {"owned": True}
    assert lock.acquire(blocking=False)                        # und danach wieder frei


def test_the_response_has_the_window_and_the_categories(env):
    put_desktop(env, "2026-10-01", modified_at="2026-10-01T10:00:00Z")
    put_desktop(env, "2025-01-15", modified_at="2025-01-15T10:00:00Z")

    response = run(env, {}, last_pull_at="2026-10-02T00:00:00Z")

    assert sorted(response["entries"]) == ["2026-10-01"]
    assert response["categories"] == ["Projekt"] and response["last_pull_at"] == NOW


def test_perform_sync_overrides_a_device_id_that_slipped_into_the_request(env):
    # Zweite Linie hinter parse_request: selbst ein von Hand gebauter Request kann
    # nicht als anderes Gerät schreiben.
    request = mobile_sync.SyncRequest(NOW, {"2026-10-07": {
        "slots": [SLOT], "modified_at": "2026-10-07T18:30:00Z", "deleted": False,
        "device_id": "evil"}})

    mobile_sync.perform_sync(
        request, device_id=PHONE, device_name="Pixel", last_pull_at="", categories=[],
        storage=env.storage, settings=env.settings, conflicts_store=env.conflicts,
        base=env.base, now=NOW, today=TODAY, desktop=DESKTOP)

    assert env.storage.get_all_raw()["2026-10-07"]["device_id"] == PHONE


@pytest.mark.parametrize("phone_stamp", [
    pytest.param("2026-10-07T11:54:00Z", id="slow-phone-clock"),
    pytest.param("2026-10-07T12:00:00Z", id="same-second-as-last-pull"),
])
def test_a_phone_edit_after_the_last_pull_wins_even_with_a_stamp_before_it(env, phone_stamp):
    # Das Handy schickt nur Tage, die es seit dem letzten Abgleich geändert hat. Sein
    # Stempel stammt von der Handy-Uhr, last_pull_at von der des Desktops: bei einer
    # nachgehenden Uhr läge er sonst vor last_pull_at und verlöre still gegen die
    # Desktop-Version, ohne Konflikt.
    put_desktop(env, "2026-10-07", modified_at="2026-10-07T11:57:00Z",
                slots=({"start": "09:00", "end": "13:00", "pause": 0, "kategorie": ""},))
    corrected = {"start": "07:00", "end": "11:00", "pause": 0, "kategorie": ""}

    response = run(env, {"2026-10-07": day(slots=(corrected,), modified_at=phone_stamp)},
                   last_pull_at="2026-10-07T12:00:00Z")

    assert env.storage.get("2026-10-07")["slots"][0]["start"] == "07:00"
    assert env.conflicts.get_all() == []
    assert response["entries"]["2026-10-07"]["slots"] == [corrected]
    assert response["entries"]["2026-10-07"]["device_id"] == PHONE


def test_a_sent_day_older_than_the_window_comes_back_from_perform_sync(env):
    old = "2026-01-15"                      # TODAY - 90 Tage liegt davor
    response = run(env, {old: day(modified_at="2026-10-07T18:30:00Z")})

    assert list(response["entries"]) == [old]


def test_perform_sync_sends_defaults_from_the_settings_and_the_desktop_info(env):
    env.settings.set("default_pause", 20)

    response = run(env, {})

    assert response["defaults"]["pause"] == 20 and response["desktop"] == DESKTOP


def test_the_window_follows_the_granted_days_not_the_constant():
    merged = {"entries": {_iso(-100): _entry(_iso(-100)), _iso(-10): _entry(_iso(-10))}}

    assert sorted(respond(merged, window_days=90)["entries"]) == [_iso(-10)]
    wide = respond(merged, window_days=180)
    assert sorted(wide["entries"]) == [_iso(-100), _iso(-10)] and wide["window_days"] == 180


def test_perform_sync_grants_the_wish_up_to_the_setting(env):
    env.settings.set("mobile_window_max_days", 180)

    assert run(env, {}, wish=365)["window_days"] == 180         # Wunsch über der Obergrenze
    assert run(env, {}, wish=120)["window_days"] == 120
    assert run(env, {})["window_days"] == 90                    # kein Wunsch
    assert run(env, {})["window_max_days"] == 180


def test_perform_sync_reads_the_setting_on_every_call(env):
    assert run(env, {}, wish=365)["window_days"] == 365
    env.settings.set("mobile_window_max_days", 30)
    assert run(env, {}, wish=365)["window_days"] == 30


# --- perform_sync mit Reservierungen --------------------------------------------------------------

def run_res(env, store, reservations, *, report=None, data_lock=None, accept=True):
    request = mobile_sync.parse_request(
        body({}, reservations=reservations), now=NOW, today=TODAY, accept_reservations=accept)
    return mobile_sync.perform_sync(
        request, device_id=PHONE, device_name="Pixel", last_pull_at="", categories=["Projekt"],
        storage=env.storage, settings=env.settings, conflicts_store=env.conflicts,
        base=env.base, now=NOW, today=TODAY, desktop=DESKTOP, data_lock=data_lock,
        reservation_store=store, report=report)


@pytest.fixture
def res_store(env):
    return ReservationStore(os.path.join(env.base, "reservations.json"))


def test_perform_sync_merges_reservations_and_returns_the_active_days(env, res_store):
    env.settings.set_many({"reservations_enabled": True})
    report = mobile_sync.SyncReport()

    response = run_res(env, res_store, {"2026-10-20": res_day()}, report=report)

    assert report.reservations_changed is True
    # Der Tag trägt den Empfangszeitpunkt als Stempel (NOW), nicht den älteren des Handys.
    assert response["reservations"] == {"2026-10-20": res_day(modified_at=NOW)}
    assert res_store.get("2026-10-20") is not None


def test_perform_sync_repeating_the_same_request_reports_no_change(env, res_store):
    env.settings.set_many({"reservations_enabled": True})
    run_res(env, res_store, {"2026-10-20": res_day()})
    report = mobile_sync.SyncReport()

    run_res(env, res_store, {"2026-10-20": res_day()}, report=report)

    assert report.reservations_changed is False


def test_perform_sync_leaves_reservations_alone_when_the_feature_is_off(env, res_store):
    report = mobile_sync.SyncReport()

    response = run_res(env, res_store, {"2026-10-20": res_day()}, report=report)

    assert "reservations" not in response
    assert report.reservations_changed is False
    assert res_store.get_all_raw() == {}


def test_perform_sync_with_the_feature_off_does_not_reject_garbage(env, res_store):
    response = run_res(env, res_store, {"2026-10-01": "kaputt"}, accept=False)

    assert "reservations" not in response


def test_perform_sync_without_a_store_has_no_reservations_field(env):
    env.settings.set_many({"reservations_enabled": True})

    assert "reservations" not in run(env, {})


def test_perform_sync_writes_reservations_inside_the_data_lock(env, res_store):
    env.settings.set_many({"reservations_enabled": True})
    inside = []
    real = res_store.merge_phone

    class Spy:
        def __init__(self):
            self.depth = 0

        def __enter__(self):
            self.depth += 1

        def __exit__(self, *exc):
            self.depth -= 1

    spy = Spy()

    def merge(days, **kwargs):
        inside.append(spy.depth)
        return real(days, **kwargs)

    res_store.merge_phone = merge
    run_res(env, res_store, {"2026-10-20": res_day()}, data_lock=spy)

    assert inside == [1]


# --- Einstellungen --------------------------------------------------------------------------------

SET_STAMP = "2026-10-08T11:00:00Z"


def setting(value, modified_at=SET_STAMP):
    return {"value": value, "modified_at": modified_at}


def desktop_setting(env, key, value, modified_at):
    env.settings.apply_synced({key: {"value": value, "modified_at": modified_at, "device_id": "DESK"}})


def run_settings(env, settings, *, last_pull_at="", **over):
    request = mobile_sync.parse_request(body({}, settings=settings), now=NOW, today=TODAY)
    kwargs = dict(device_id=PHONE, device_name="Pixel", last_pull_at=last_pull_at,
                  storage=env.storage, settings=env.settings, conflicts_store=env.conflicts,
                  base=env.base, now=NOW, today=TODAY, desktop=DESKTOP)
    kwargs.update(over)
    return mobile_sync.perform_sync(request, **kwargs)


def test_settings_are_parsed_next_to_the_entries():
    request = mobile_sync.parse_request(body({}, settings={"categories": setting(["A"])}), now=NOW, today=TODAY)
    assert request.settings == {"categories": {"value": ["A"], "modified_at": SET_STAMP}}


def test_a_request_without_settings_has_none():
    assert parse({}).settings == {}


def test_a_forbidden_setting_key_is_422_invalid_entry_and_names_the_key():
    error = rejected(body({}, settings={"hourly_rate": setting(100)}))
    assert (error.status, error.code) == (422, "invalid_entry")
    assert "hourly_rate" in error.message


def test_the_clock_check_comes_before_the_settings():
    error = rejected(body({}, client_time="2026-10-08T13:00:00Z", settings={"hourly_rate": setting(1)}))
    assert error.code == "clock_skew"


def test_a_phone_change_wins_and_the_response_has_the_state_after_applying(env):
    desktop_setting(env, "categories", ["Alt"], "2026-10-01T10:00:00Z")

    response = run_settings(env, {"categories": setting(["Neu", "Intern"]),
                                  "category_times": setting({"Neu": {"start": "09:00", "pause": 30}})},
                            last_pull_at="2026-10-05T00:00:00Z")

    assert env.settings.get("categories") == ["Neu", "Intern"]
    assert response["categories"] == ["Neu", "Intern"]
    assert response["defaults"]["category_times"] == {"Neu": {"start": "09:00", "pause": 30}}


def test_a_slow_phone_clock_still_wins_against_an_older_desktop_value(env):
    desktop_setting(env, "categories", ["Alt"], "2026-10-04T10:00:00Z")

    # Das Handy hat nach dem letzten Abgleich (10-05) geändert, seine Uhr geht nach.
    run_settings(env, {"categories": setting(["Neu"], modified_at="2026-10-03T00:00:00Z")},
                 last_pull_at="2026-10-05T00:00:00Z")

    assert env.settings.get("categories") == ["Neu"]


def test_a_change_on_both_sides_becomes_a_setting_conflict_and_the_newer_wins(env):
    desktop_setting(env, "categories", ["Desktop"], "2026-10-06T10:00:00Z")

    response = run_settings(env, {"categories": setting(["Handy"], modified_at="2026-10-08T10:00:00Z")},
                            last_pull_at="2026-10-05T00:00:00Z")

    conflicts = env.conflicts.get_all()
    assert [(c["kind"], c["key"]) for c in conflicts] == [("setting", "categories")]
    assert env.settings.get("categories") == ["Handy"]
    assert response["conflicts"] == []                     # das Handy zeigt nur Einträge


def test_the_same_request_twice_changes_nothing_and_makes_no_second_conflict(env):
    desktop_setting(env, "categories", ["Alt"], "2026-10-01T10:00:00Z")
    first = run_settings(env, {"categories": setting(["Neu"])}, last_pull_at="2026-10-05T00:00:00Z")
    before = (env.settings.get("categories"), len(env.conflicts.get_all()))

    again = run_settings(env, {"categories": setting(["Neu"])}, last_pull_at="2026-10-05T00:00:00Z")

    assert (env.settings.get("categories"), len(env.conflicts.get_all())) == before
    assert again["categories"] == first["categories"]


def test_a_retry_after_a_lost_response_adds_no_conflict_and_keeps_the_value(env):
    desktop_setting(env, "categories", ["Alt"], "2026-10-01T10:00:00Z")
    run_settings(env, {"categories": setting(["Neu"])}, last_pull_at="2026-10-05T00:00:00Z")
    stored = (env.settings.get("categories"), len(env.conflicts.get_all()))

    # Die erste Antwort ging verloren, die Route hat aber `last_pull_at` schon vorgerückt: das Handy
    # schickt denselben Block noch einmal, jetzt mit dem neuen Abgleichstand.
    again = run_settings(env, {"categories": setting(["Neu"])}, last_pull_at="2026-10-08T11:59:00Z")

    assert (env.settings.get("categories"), len(env.conflicts.get_all())) == stored
    assert again["categories"] == ["Neu"]


def test_a_per_day_category_the_phone_sends_back_stays_bit_identical(env):
    times = {"Support": {"mode": "per_day", "pause": 15,
                         "days": {"fri": {"start": "07:00", "end": "11:00"}}},
             "Projekt": {"start": "09:00", "end": "17:00", "pause": 45}}
    desktop_setting(env, "categories", ["Support", "Projekt"], "2026-10-01T10:00:00Z")
    desktop_setting(env, "category_times", times, "2026-10-01T10:00:00Z")

    run_settings(env, {"categories": setting(["Support", "Projekt", "Neu"]), "category_times": setting(times)},
                 last_pull_at="2026-10-05T00:00:00Z")

    assert env.settings.get("category_times") == times


def test_category_times_alone_with_an_unknown_name_is_422_and_applies_nothing(env):
    desktop_setting(env, "categories", ["A"], "2026-10-01T10:00:00Z")
    request = mobile_sync.parse_request(
        body({"2026-10-07": day()}, settings={"category_times": setting({"Fremd": {"pause": 5}})}),
        now=NOW, today=TODAY)

    with pytest.raises(SyncError) as excinfo:
        mobile_sync.perform_sync(request, device_id=PHONE, device_name="Pixel", last_pull_at="",
                                 storage=env.storage, settings=env.settings, conflicts_store=env.conflicts,
                                 base=env.base, now=NOW, today=TODAY, desktop=DESKTOP)

    assert (excinfo.value.status, excinfo.value.code) == (422, "invalid_entry")
    assert env.storage.get("2026-10-07") is None
    assert env.settings.get("category_times") == {}


def test_without_a_categories_argument_the_response_reads_the_settings(env):
    desktop_setting(env, "categories", ["Aus den Einstellungen"], "2026-10-01T10:00:00Z")
    assert run_settings(env, {})["categories"] == ["Aus den Einstellungen"]
