# tests/test_mobile_store.py
import json
import logging
import os
import stat
import sys
import threading

import pytest

from src import mobile_pairing as mp
from src import mobile_store
from src.mobile_store import MobileStore, MobileStoreReadOnly

NOW = "2026-10-08T12:00:00Z"


def make_record(device_id="device-0001", name="Pixel", now=NOW):
    record, token = mp.issue_device(device_id, name, now)
    return record, token


@pytest.fixture
def path(tmp_path):
    return str(tmp_path / "mobile_devices.json")


def backups(path):
    directory = os.path.dirname(path)
    return sorted(n for n in os.listdir(directory) if ".corrupt-" in n)


# --- Grundfunktionen --------------------------------------------------------------------------

def test_a_missing_file_gives_an_empty_store(path):
    store = MobileStore(path)
    assert store.get_all() == [] and store.get("device-0001") is None
    assert not os.path.exists(path)                      # Lesen legt nichts an


def test_save_and_get_round_trip_through_the_file(path):
    record, token = make_record()
    MobileStore(path).save(record)

    again = MobileStore(path)

    assert again.get("device-0001") == record
    assert mp.authenticate(again.get_all(), token, NOW).ok


def test_saving_the_same_id_replaces_instead_of_duplicating(path):
    store = MobileStore(path)
    first, _ = make_record()
    store.save(first)
    second = dict(first, name="Pixel 2")

    store.save(second)

    assert [r["name"] for r in store.get_all()] == ["Pixel 2"]


def test_two_devices_are_kept_apart(path):
    store = MobileStore(path)
    a, _ = make_record("device-aaaa", "A")
    b, _ = make_record("device-bbbb", "B")
    store.save(a)
    store.save(b)
    assert [r["id"] for r in MobileStore(path).get_all()] == ["device-aaaa", "device-bbbb"]


def test_results_are_copies(path):
    store = MobileStore(path)
    record, _ = make_record()
    store.save(record)

    store.get("device-0001")["name"] = "geändert"
    store.get_all()[0]["revoked"] = True
    record["name"] = "auch geändert"

    assert store.get("device-0001")["name"] == "Pixel" and not store.get("device-0001")["revoked"]


def test_the_file_never_contains_a_plaintext_token(path):
    record, token = make_record()
    renewed, new_token = mp.renew(record, NOW)
    MobileStore(path).save(renewed)

    text = open(path, encoding="utf-8").read()

    assert token not in text and new_token not in text
    assert renewed["token_hash"] in text


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX-Rechte")
def test_the_file_is_private_on_posix(path):
    record, _ = make_record()
    MobileStore(path).save(record)
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600


def test_replace_all_writes_once_and_replaces_everything(path):
    store = MobileStore(path)
    a, _ = make_record("device-aaaa")
    b, _ = make_record("device-bbbb")
    store.save(a)
    store.save(b)

    store.replace_all([mp.revoke(a), mp.revoke(b)])

    assert all(r["revoked"] for r in MobileStore(path).get_all())


# --- prune ------------------------------------------------------------------------------------------

def test_prune_forgets_only_devices_expired_for_more_than_thirty_days(path):
    store = MobileStore(path)
    old, _ = make_record("device-old1", now="2026-07-01T00:00:00Z")      # läuft 2026-07-31 ab
    recent, _ = make_record("device-new1", now="2026-09-20T00:00:00Z")   # läuft 2026-10-20 ab
    fresh, _ = make_record("device-live", now=NOW)
    for record in (old, recent, fresh):
        store.save(record)

    removed = store.prune(NOW)                                            # Grenze: 2026-09-08

    assert removed == 1
    assert [r["id"] for r in MobileStore(path).get_all()] == ["device-new1", "device-live"]


def test_prune_without_a_hit_does_not_write(path, monkeypatch):
    store = MobileStore(path)
    record, _ = make_record()
    store.save(record)
    calls = []
    monkeypatch.setattr(mobile_store, "atomic_write_json", lambda *a, **k: calls.append(a))

    assert store.prune(NOW) == 0 and calls == []


# --- kaputte oder fremde Dateien ---------------------------------------------------------------------

def test_unparsable_json_is_quarantined(path):
    open(path, "w", encoding="utf-8").write("{ kaputt")
    store = MobileStore(path)
    assert store.get_all() == [] and not os.path.exists(path) and len(backups(path)) == 1
    record, _ = make_record()
    store.save(record)                                                    # und benutzbar
    assert MobileStore(path).get("device-0001") == record


@pytest.mark.parametrize("content", ["[]", '"text"', "42", "true"])
def test_a_non_object_top_level_is_quarantined(path, content, caplog):
    open(path, "w", encoding="utf-8").write(content)
    with caplog.at_level(logging.WARNING):
        store = MobileStore(path)
    assert store.get_all() == [] and len(backups(path)) == 1
    assert "Top-Level" in caplog.text


def test_malformed_records_are_skipped_and_never_logged_in_full(path, caplog):
    good, _ = make_record("device-good")
    bad_hash = dict(good, id="device-bad1", token_hash="xyz")
    secret_marker = "GEHEIMER-HASH-INHALT"
    junk = [None, "x", 5, {"id": "device-nope"}, bad_hash, dict(good, id="", ),
            dict(good, id="device-bad2", revoked="ja"), dict(good, id="device-bad3", name=5),
            dict(good, id="device-bad4", previous_token_hash=secret_marker)]
    open(path, "w", encoding="utf-8").write(
        json.dumps({"schema_version": 1, "devices": [*junk, good]}))

    with caplog.at_level(logging.WARNING):
        store = MobileStore(path)

    assert [r["id"] for r in store.get_all()] == ["device-good"]
    assert secret_marker not in caplog.text and good["token_hash"] not in caplog.text
    assert "übersprungen" in caplog.text


@pytest.mark.parametrize("devices", [None, "x", 5, {"a": 1}])
def test_a_devices_field_of_the_wrong_type_gives_an_empty_store(path, devices):
    open(path, "w", encoding="utf-8").write(json.dumps({"schema_version": 1, "devices": devices}))
    assert MobileStore(path).get_all() == []


def test_a_newer_schema_is_read_only_and_never_overwritten(path):
    original = json.dumps({"schema_version": 99, "devices": [], "neu": True})
    open(path, "w", encoding="utf-8").write(original)
    store = MobileStore(path)
    record, _ = make_record()

    with pytest.raises(MobileStoreReadOnly):
        store.save(record)

    assert open(path, encoding="utf-8").read() == original and store.get_all() == []


def test_an_unreadable_file_is_read_only_and_not_quarantined(path, monkeypatch):
    open(path, "w", encoding="utf-8").write(json.dumps({"schema_version": 1, "devices": []}))

    def boom(_path):
        raise PermissionError("gesperrt")
    monkeypatch.setattr(mobile_store, "load_json_or_quarantine", boom)

    store = MobileStore(path)
    record, _ = make_record()

    with pytest.raises(MobileStoreReadOnly):
        store.save(record)
    assert os.path.exists(path) and backups(path) == []


# --- Schreibfehler und Nebenläufigkeit -------------------------------------------------------------------

def test_a_failed_write_rolls_the_memory_back(path, monkeypatch):
    store = MobileStore(path)
    first, _ = make_record("device-0001")
    store.save(first)

    def boom(*_args, **_kwargs):
        raise OSError(28, "Platte voll")
    monkeypatch.setattr(mobile_store, "atomic_write_json", boom)
    second, _ = make_record("device-0002")

    with pytest.raises(OSError):
        store.save(second)
    with pytest.raises(OSError):
        store.replace_all([])

    assert [r["id"] for r in store.get_all()] == ["device-0001"]
    assert [r["id"] for r in MobileStore(path).get_all()] == ["device-0001"]


def test_concurrent_saves_lose_nothing(path):
    store = MobileStore(path)
    records = [make_record(f"device-{i:04d}")[0] for i in range(20)]
    threads = [threading.Thread(target=store.save, args=(r,)) for r in records]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert sorted(r["id"] for r in MobileStore(path).get_all()) == sorted(r["id"] for r in records)


@pytest.mark.parametrize("field,value", [
    ("expires_at", "zzzz"), ("expires_at", ""), ("expires_at", "2026-11-07 12:00:00"),
    ("expires_at", "2026-11-07T12:00:00+00:00"), ("expires_at", "٢026-11-07T12:00:00Z"),
    ("created_at", "gestern"), ("last_seen", "9999"), ("last_pull_at", "irgendwann"),
    ("previous_valid_until", "bald"),
])
def test_a_record_with_a_malformed_timestamp_is_skipped(path, field, value):
    # Zeitstempel werden als Text verglichen; "zzzz" liefe sonst nie ab.
    good, _ = make_record("device-good")
    bad = dict(good, id="device-bad1", **{field: value})
    open(path, "w", encoding="utf-8").write(json.dumps({"schema_version": 1, "devices": [bad, good]}))

    assert [r["id"] for r in MobileStore(path).get_all()] == ["device-good"]


def test_empty_optional_timestamps_are_fine(path):
    record, _ = make_record()
    assert record["last_pull_at"] == "" and record["previous_valid_until"] == ""
    MobileStore(path).save(record)
    assert MobileStore(path).get("device-0001") == record


def test_a_record_with_a_lone_surrogate_is_skipped_so_saving_keeps_working(path):
    # Ein JSON-Escape "\ud800" lädt als str, scheiterte aber beim Schreiben mit
    # UnicodeEncodeError und sperrte damit auch jeden Widerruf.
    good, token = make_record("device-good")
    bad = dict(good, id="device-bad1", name="X\ud800")
    open(path, "w", encoding="utf-8").write(
        json.dumps({"schema_version": 1, "devices": [bad, good]}, ensure_ascii=True))
    store = MobileStore(path)

    store.save(mp.revoke(store.get("device-good")))

    assert [r["id"] for r in MobileStore(path).get_all()] == ["device-good"]
    assert MobileStore(path).get("device-good")["revoked"] is True


def test_duplicate_ids_in_the_file_keep_only_the_first_record(path):
    first, t1 = make_record("device-0001", "Erstes")
    second, t2 = make_record("device-0001", "Zweites")
    open(path, "w", encoding="utf-8").write(
        json.dumps({"schema_version": 1, "devices": [first, second]}))
    store = MobileStore(path)

    store.save(mp.revoke(store.get("device-0001")))

    again = MobileStore(path)
    assert [r["name"] for r in again.get_all()] == ["Erstes"]
    assert mp.authenticate(again.get_all(), t2, NOW).status == "unauthorized"
    assert mp.authenticate(again.get_all(), t1, NOW).status == "revoked"


# --- Replay-Zähler (#249) ---------------------------------------------------------------------

def test_last_seq_round_trips_through_the_file(path):
    record, _ = make_record()
    store = MobileStore(path)
    store.save(mp.with_seq(record, 41))
    assert MobileStore(path).get("device-0001")["last_seq"] == 41


def test_a_record_without_last_seq_loads_as_zero(path):
    record, _ = make_record()
    legacy = {k: v for k, v in record.items() if k != "last_seq"}
    with open(path, "w", encoding="utf-8") as handle:
        json.dump({"schema_version": 1, "devices": [legacy]}, handle)
    assert MobileStore(path).get("device-0001")["last_seq"] == 0


@pytest.mark.parametrize("value", [-1, 2 ** 53, 1.5, "7", True, None, [1]])
def test_a_record_with_an_invalid_last_seq_is_skipped(path, value):
    record, _ = make_record()
    broken = {**record, "last_seq": value}
    with open(path, "w", encoding="utf-8") as handle:
        json.dump({"schema_version": 1, "devices": [broken]}, handle)
    assert MobileStore(path).get_all() == []
