import logging
import os
from unittest import mock

import pytest
from src.storage import Storage


@pytest.fixture
def tmp_storage(tmp_path):
    return Storage(str(tmp_path / "test.json"), device_id="test-device")


from tests.conftest import ist_slot as _slot  # geteilte Ist-Zeit-Factory (Audit N22)


def test_load_empty(tmp_storage):
    assert tmp_storage.get_all() == {}


def test_save_and_load(tmp_storage):
    tmp_storage.save("2026-03-23", [_slot("08:00", "16:30")])
    entries = tmp_storage.get_all()
    assert entries["2026-03-23"] == {"slots": [_slot("08:00", "16:30")]}


def test_save_multiple_slots(tmp_storage):
    slots = [_slot("08:00", "12:00", 0, "Büro"), _slot("13:00", "17:00", 30, "Homeoffice")]
    tmp_storage.save("2026-03-23", slots)
    assert tmp_storage.get("2026-03-23") == {"slots": slots}


def test_slot_defaults_pause_and_kategorie(tmp_storage):
    tmp_storage.save("2026-03-23", [{"start": "08:00", "end": "16:30"}])
    assert tmp_storage.get("2026-03-23") == {"slots": [_slot("08:00", "16:30", 0, "")]}


def test_delete_entry(tmp_storage):
    tmp_storage.save("2026-03-23", [_slot("08:00", "16:30")])
    tmp_storage.delete("2026-03-23")
    assert "2026-03-23" not in tmp_storage.get_all()


def test_delete_writes_tombstone(tmp_storage):
    tmp_storage.save("2026-03-23", [_slot("08:00", "16:30")])
    tmp_storage.delete("2026-03-23")
    raw = tmp_storage.get_all_raw()["2026-03-23"]
    assert raw["deleted"] is True
    assert raw["slots"] == []


def test_delete_nonexistent(tmp_storage):
    tmp_storage.delete("2026-01-01")  # should not raise
    assert tmp_storage.get_all_raw() == {}


def test_persistence(tmp_path):
    path = str(tmp_path / "test.json")
    s1 = Storage(path)
    s1.save("2026-03-23", [_slot("08:00", "16:30")])
    s2 = Storage(path)
    assert s2.get_all()["2026-03-23"] == {"slots": [_slot("08:00", "16:30")]}


def test_save_with_pause(tmp_storage):
    tmp_storage.save("2026-03-23", [_slot("08:00", "16:30", 30)])
    assert tmp_storage.get("2026-03-23") == {"slots": [_slot("08:00", "16:30", 30)]}


def test_save_fsyncs_before_replace(tmp_path, monkeypatch):
    # N1: _save_to_disk muss den Temp-File fsyncen, bevor os.replace ihn sichtbar
    # macht (Durability). Wir prüfen, dass fsync tatsächlich aufgerufen wird.
    import src.storage as storage_mod
    fsync_calls = []
    monkeypatch.setattr(storage_mod.os, "fsync", lambda fd: fsync_calls.append(fd))
    s = Storage(str(tmp_path / "z.json"))

    s.save("2026-05-14", [_slot("08:00", "16:00")])

    assert fsync_calls, "os.fsync wurde beim Speichern nicht aufgerufen"


def test_corrupt_json_is_quarantined_and_starts_empty(tmp_path, caplog):
    path = tmp_path / "test.json"
    path.write_text("{not valid json", encoding="utf-8")

    with caplog.at_level(logging.WARNING):
        storage = Storage(str(path))

    assert storage.get_all() == {}
    quarantined = list(tmp_path.glob("test.json.corrupt-*"))
    assert len(quarantined) == 1
    assert quarantined[0].read_text(encoding="utf-8") == "{not valid json"
    # N4: Quarantäne wird jetzt geloggt, nicht mehr stumm.
    assert any("Quarantäne" in r.message for r in caplog.records)


def test_save_failure_keeps_original_file_intact(tmp_path):
    path = tmp_path / "test.json"
    storage = Storage(str(path))
    storage.save("2026-03-23", [_slot("08:00", "16:30")])
    original_bytes = path.read_bytes()

    with mock.patch("os.replace", side_effect=OSError("disk full")):
        with pytest.raises(OSError):
            storage.save("2026-03-24", [_slot("09:00", "17:00")])

    assert path.read_bytes() == original_bytes
    leftovers = [p for p in tmp_path.iterdir() if p.suffix == ".tmp"]
    assert leftovers == []


def test_save_does_not_leave_tmp_files(tmp_path):
    path = tmp_path / "test.json"
    storage = Storage(str(path))
    storage.save("2026-03-23", [_slot("08:00", "16:30")])
    storage.save("2026-03-24", [_slot("09:00", "17:00")])

    leftovers = [p.name for p in tmp_path.iterdir() if p.name.endswith(".tmp")]
    assert leftovers == []


def test_save_stamps_modified_at_and_device_id(tmp_path):
    storage = Storage(str(tmp_path / "t.json"), device_id="dev-1")
    storage.save("2026-05-14", [_slot("08:00", "16:00", 30)])
    raw = storage.get_all_raw()
    assert raw["2026-05-14"]["slots"] == [_slot("08:00", "16:00", 30)]
    assert raw["2026-05-14"]["device_id"] == "dev-1"
    assert "T" in raw["2026-05-14"]["modified_at"]
    assert raw["2026-05-14"]["modified_at"].endswith("Z")


def test_get_returns_user_shape_without_metadata(tmp_path):
    storage = Storage(str(tmp_path / "t.json"), device_id="dev-1")
    storage.save("2026-05-14", [_slot("08:00", "16:00", 30)])
    assert storage.get("2026-05-14") == {"slots": [_slot("08:00", "16:00", 30)]}
    assert storage.get_all()["2026-05-14"] == {"slots": [_slot("08:00", "16:00", 30)]}


def test_user_shape_returns_independent_copies(tmp_path):
    """get() darf keine Referenz auf interne Slot-Dicts herausgeben."""
    storage = Storage(str(tmp_path / "t.json"))
    storage.save("2026-05-14", [_slot("08:00", "16:00")])
    got = storage.get("2026-05-14")
    got["slots"][0]["start"] = "00:00"
    assert storage.get("2026-05-14")["slots"][0]["start"] == "08:00"


def test_apply_merge_rejects_entry_missing_required_keys(tmp_path):
    storage = Storage(str(tmp_path / "t.json"), device_id="dev-1")
    with pytest.raises(ValueError, match="missing keys"):
        storage.apply_merge({"2026-05-14": {"slots": [_slot("08:00", "16:00")]}})
    # _data unverändert geblieben (kein Halb-Schreiben)
    assert storage.get_all_raw() == {}


def test_apply_merge_accepts_complete_entries(tmp_path):
    storage = Storage(str(tmp_path / "t.json"), device_id="dev-1")
    storage.apply_merge({"2026-05-14": {
        "slots": [_slot("08:00", "16:00", 30)],
        "modified_at": "2026-05-14T10:00:00Z",
        "device_id": "other-dev",
        "deleted": False,
    }})
    assert storage.get("2026-05-14") == {"slots": [_slot("08:00", "16:00", 30)]}


def test_save_many_empty_is_noop(tmp_path):
    path = str(tmp_path / "noop.json")
    s = Storage(path, device_id="d1")
    s.save_many({})
    assert not os.path.exists(path)


def test_save_many_writes_all_entries(tmp_storage):
    tmp_storage.save_many({
        "2026-05-14": {"slots": [_slot("08:00", "16:00", 30)]},
        "2026-05-15": {"slots": [_slot("09:00", "17:30", 45)]},
    })
    entries = tmp_storage.get_all()
    assert entries["2026-05-14"] == {"slots": [_slot("08:00", "16:00", 30)]}
    assert entries["2026-05-15"] == {"slots": [_slot("09:00", "17:30", 45)]}


def test_save_many_sets_metadata(tmp_storage):
    tmp_storage.save_many({"2026-05-14": {"slots": [_slot("08:00", "16:00", 30)]}})
    raw = tmp_storage.get_all_raw()["2026-05-14"]
    assert raw["device_id"] == "test-device"
    assert raw["deleted"] is False
    assert "modified_at" in raw and raw["modified_at"]


def test_save_many_overwrites_tombstone(tmp_storage):
    tmp_storage.save("2026-05-14", [_slot("08:00", "16:00", 30)])
    tmp_storage.delete("2026-05-14")
    assert tmp_storage.get("2026-05-14") is None
    tmp_storage.save_many({"2026-05-14": {"slots": [_slot("09:00", "17:00")]}})
    assert tmp_storage.get("2026-05-14") == {"slots": [_slot("09:00", "17:00")]}


def test_save_many_calls_disk_write_once(tmp_storage):
    with mock.patch.object(tmp_storage, "_save_to_disk") as m:
        tmp_storage.save_many({
            "2026-05-14": {"slots": [_slot("08:00", "16:00", 30)]},
            "2026-05-15": {"slots": [_slot("09:00", "17:30", 45)]},
        })
    assert m.call_count == 1


def test_save_many_slot_defaults(tmp_storage):
    tmp_storage.save_many({"2026-05-14": {"slots": [{"start": "08:00", "end": "16:00"}]}})
    slot = tmp_storage.get_all()["2026-05-14"]["slots"][0]
    assert slot["pause"] == 0
    assert slot["kategorie"] == ""
