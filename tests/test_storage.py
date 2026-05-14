import os
from unittest import mock

import pytest
from src.storage import Storage

@pytest.fixture
def tmp_storage(tmp_path):
    return Storage(str(tmp_path / "test.json"), device_id="test-device")

def test_load_empty(tmp_storage):
    assert tmp_storage.get_all() == {}

def test_save_and_load(tmp_storage):
    tmp_storage.save("2026-03-23", "08:00", "16:30")
    entries = tmp_storage.get_all()
    assert entries["2026-03-23"] == {"start": "08:00", "end": "16:30", "pause": 0}

def test_delete_entry(tmp_storage):
    tmp_storage.save("2026-03-23", "08:00", "16:30")
    tmp_storage.delete("2026-03-23")
    assert "2026-03-23" not in tmp_storage.get_all()

def test_delete_nonexistent(tmp_storage):
    tmp_storage.delete("2026-01-01")  # should not raise

def test_persistence(tmp_path):
    path = str(tmp_path / "test.json")
    s1 = Storage(path)
    s1.save("2026-03-23", "08:00", "16:30")
    s2 = Storage(path)
    assert s2.get_all()["2026-03-23"] == {"start": "08:00", "end": "16:30", "pause": 0}

def test_save_with_pause(tmp_storage):
    tmp_storage.save("2026-03-23", "08:00", "16:30", pause=30)
    entry = tmp_storage.get("2026-03-23")
    assert entry == {"start": "08:00", "end": "16:30", "pause": 30}

def test_save_default_pause_zero(tmp_storage):
    tmp_storage.save("2026-03-23", "08:00", "16:30")
    entry = tmp_storage.get("2026-03-23")
    assert entry == {"start": "08:00", "end": "16:30", "pause": 0}


def test_corrupt_json_is_quarantined_and_starts_empty(tmp_path):
    path = tmp_path / "test.json"
    path.write_text("{not valid json", encoding="utf-8")

    storage = Storage(str(path))

    assert storage.get_all() == {}
    quarantined = list(tmp_path.glob("test.json.corrupt-*"))
    assert len(quarantined) == 1
    assert quarantined[0].read_text(encoding="utf-8") == "{not valid json"


def test_save_failure_keeps_original_file_intact(tmp_path):
    path = tmp_path / "test.json"
    storage = Storage(str(path))
    storage.save("2026-03-23", "08:00", "16:30")
    original_bytes = path.read_bytes()

    with mock.patch("os.replace", side_effect=OSError("disk full")):
        with pytest.raises(OSError):
            storage.save("2026-03-24", "09:00", "17:00")

    assert path.read_bytes() == original_bytes
    leftovers = [p for p in tmp_path.iterdir() if p.suffix == ".tmp"]
    assert leftovers == []


def test_save_does_not_leave_tmp_files(tmp_path):
    path = tmp_path / "test.json"
    storage = Storage(str(path))
    storage.save("2026-03-23", "08:00", "16:30")
    storage.save("2026-03-24", "09:00", "17:00")

    leftovers = [p.name for p in tmp_path.iterdir() if p.name.endswith(".tmp")]
    assert leftovers == []


def test_save_stamps_modified_at_and_device_id(tmp_path):
    storage = Storage(str(tmp_path / "t.json"), device_id="dev-1")
    storage.save("2026-05-14", "08:00", "16:00", pause=30)
    raw = storage.get_all_raw()
    assert raw["2026-05-14"]["start"] == "08:00"
    assert raw["2026-05-14"]["device_id"] == "dev-1"
    assert "modified_at" in raw["2026-05-14"]
    # ISO-Format
    assert "T" in raw["2026-05-14"]["modified_at"]
    assert raw["2026-05-14"]["modified_at"].endswith("Z")


def test_get_returns_user_shape_without_metadata(tmp_path):
    """Bestehende UI-Code-Pfade dürfen sich nicht ändern: get() liefert
    weiter {start, end, pause}, get_all() ebenso."""
    storage = Storage(str(tmp_path / "t.json"), device_id="dev-1")
    storage.save("2026-05-14", "08:00", "16:00", pause=30)
    assert storage.get("2026-05-14") == {"start": "08:00", "end": "16:00", "pause": 30}
    assert storage.get_all()["2026-05-14"] == {"start": "08:00", "end": "16:00", "pause": 30}
