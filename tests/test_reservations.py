from unittest import mock

import pytest
from src.reservations import ReservationStore


@pytest.fixture
def store(tmp_path):
    return ReservationStore(str(tmp_path / "res.json"))


def test_load_empty(store):
    assert store.get_all() == {}


def test_save_and_get(store):
    store.save("2026-06-01", "09:00", "17:00")
    assert store.get("2026-06-01") == {"start": "09:00", "end": "17:00"}
    assert store.get_all() == {"2026-06-01": {"start": "09:00", "end": "17:00"}}


def test_save_stamps_metadata(store):
    store.save("2026-06-01", "09:00", "17:00")
    raw = store.get_all_raw()["2026-06-01"]
    assert raw["deleted"] is False
    assert raw["gcal_event_id"] is None
    assert raw["modified_at"].endswith("Z") and "T" in raw["modified_at"]


def test_save_preserves_existing_event_id(store):
    store.save("2026-06-01", "09:00", "17:00")
    store.apply_reconciled({"2026-06-01": {
        "start": "09:00", "end": "17:00", "modified_at": "2026-05-20T10:00:00Z",
        "deleted": False, "gcal_event_id": "ev-1",
    }})
    store.save("2026-06-01", "08:00", "16:00")
    assert store.get_all_raw()["2026-06-01"]["gcal_event_id"] == "ev-1"


def test_delete_writes_tombstone_and_keeps_event_id(store):
    store.apply_reconciled({"2026-06-01": {
        "start": "09:00", "end": "17:00", "modified_at": "2026-05-20T10:00:00Z",
        "deleted": False, "gcal_event_id": "ev-1",
    }})
    store.delete("2026-06-01")
    assert store.get("2026-06-01") is None
    tomb = store.get_all_raw()["2026-06-01"]
    assert tomb["deleted"] is True
    assert tomb["gcal_event_id"] == "ev-1"


def test_delete_nonexistent_is_noop(store):
    store.delete("2026-01-01")
    assert store.get_all_raw() == {}


def test_get_excludes_tombstones(store):
    store.save("2026-06-01", "09:00", "17:00")
    store.delete("2026-06-01")
    assert "2026-06-01" not in store.get_all()
    assert "2026-06-01" in store.get_all_raw()


def test_persistence(tmp_path):
    path = str(tmp_path / "res.json")
    ReservationStore(path).save("2026-06-01", "09:00", "17:00")
    assert ReservationStore(path).get("2026-06-01") == {"start": "09:00", "end": "17:00"}


def test_apply_reconciled_replaces_data(store):
    store.save("2026-06-01", "09:00", "17:00")
    store.apply_reconciled({"2026-07-01": {
        "start": "10:00", "end": "18:00", "modified_at": "2026-05-20T10:00:00Z",
        "deleted": False, "gcal_event_id": "ev-9",
    }})
    assert "2026-06-01" not in store.get_all_raw()
    assert store.get("2026-07-01") == {"start": "10:00", "end": "18:00"}


def test_corrupt_json_is_quarantined_and_starts_empty(tmp_path):
    path = tmp_path / "res.json"
    path.write_text("{not valid", encoding="utf-8")
    store = ReservationStore(str(path))
    assert store.get_all() == {}
    assert len(list(tmp_path.glob("res.json.corrupt-*"))) == 1


def test_save_failure_keeps_original_intact(tmp_path):
    path = tmp_path / "res.json"
    store = ReservationStore(str(path))
    store.save("2026-06-01", "09:00", "17:00")
    original = path.read_bytes()
    with mock.patch("os.replace", side_effect=OSError("disk full")):
        with pytest.raises(OSError):
            store.save("2026-06-02", "09:00", "17:00")
    assert path.read_bytes() == original
    assert [p for p in tmp_path.iterdir() if p.suffix == ".tmp"] == []


def test_apply_reconciled_rejects_missing_keys(store):
    with pytest.raises(ValueError, match="missing keys"):
        store.apply_reconciled({"2026-06-01": {"start": "09:00", "end": "17:00"}})
    # _data unverändert (kein Halb-Schreiben)
    assert store.get_all_raw() == {}
