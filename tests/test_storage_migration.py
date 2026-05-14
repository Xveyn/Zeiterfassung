import json
import os

import pytest

from src.storage import Storage


def _write_legacy_json(tmp_path, payload):
    path = tmp_path / "legacy.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f)
    return str(path)


def test_legacy_entries_get_metadata_on_load(tmp_path):
    """Eintrag ohne modified_at/device_id/deleted wird beim Laden migriert."""
    path = _write_legacy_json(tmp_path, {
        "2026-03-23": {"start": "08:00", "end": "16:30", "pause": 30},
    })
    storage = Storage(path, device_id="dev-1")
    raw = storage.get_all_raw()
    entry = raw["2026-03-23"]
    assert entry["start"] == "08:00"
    assert entry["end"] == "16:30"
    assert entry["pause"] == 30
    assert entry["device_id"] == "dev-1"
    assert entry["deleted"] is False
    assert entry["modified_at"].endswith("Z")


def test_legacy_modified_at_uses_file_mtime(tmp_path):
    """Migrationszeitpunkt = mtime der Legacy-Datei (best lower bound)."""
    path = _write_legacy_json(tmp_path, {
        "2026-03-23": {"start": "08:00", "end": "16:30", "pause": 30},
    })
    # mtime künstlich setzen
    fixed_mtime = 1_700_000_000  # 2023-11-14T22:13:20Z
    os.utime(path, (fixed_mtime, fixed_mtime))
    storage = Storage(path, device_id="dev-1")
    entry = storage.get_all_raw()["2026-03-23"]
    assert entry["modified_at"] == "2023-11-14T22:13:20Z"


def test_user_facing_get_all_after_migration_unchanged(tmp_path):
    """UI-Code sieht nach Migration weiter die schmale Shape."""
    path = _write_legacy_json(tmp_path, {
        "2026-03-23": {"start": "08:00", "end": "16:30", "pause": 30},
    })
    storage = Storage(path, device_id="dev-1")
    assert storage.get_all() == {
        "2026-03-23": {"start": "08:00", "end": "16:30", "pause": 30}
    }


def test_partially_migrated_entries_not_touched(tmp_path):
    """Wenn modified_at schon da ist (z.B. Sync hat geschrieben), keine Re-Migration."""
    path = _write_legacy_json(tmp_path, {
        "2026-03-23": {
            "start": "08:00", "end": "16:30", "pause": 30,
            "modified_at": "2026-05-01T10:00:00Z",
            "device_id": "other-device",
            "deleted": False,
        },
    })
    storage = Storage(path, device_id="dev-1")
    entry = storage.get_all_raw()["2026-03-23"]
    assert entry["modified_at"] == "2026-05-01T10:00:00Z"
    assert entry["device_id"] == "other-device"
