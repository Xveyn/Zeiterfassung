import json
import os

from src.storage import Storage


def _write_legacy_json(tmp_path, payload):
    path = tmp_path / "legacy.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f)
    return str(path)


def test_legacy_entry_wrapped_into_single_slot(tmp_path):
    """Alter Ein-Eintrag-Tag ohne Metadaten → 1-Slot-Liste + Sync-Metadaten."""
    path = _write_legacy_json(tmp_path, {
        "2026-03-23": {"start": "08:00", "end": "16:30", "pause": 30},
    })
    storage = Storage(path, device_id="dev-1")
    raw = storage.get_all_raw()["2026-03-23"]
    assert raw["slots"] == [{"start": "08:00", "end": "16:30", "pause": 30, "kategorie": ""}]
    assert raw["device_id"] == "dev-1"
    assert raw["deleted"] is False
    assert raw["modified_at"].endswith("Z")
    # alte Top-Level-Zeitfelder entfernt
    assert "start" not in raw and "end" not in raw and "pause" not in raw


def test_legacy_modified_at_uses_file_mtime(tmp_path):
    """Migrationszeitpunkt = mtime der Legacy-Datei (best lower bound)."""
    path = _write_legacy_json(tmp_path, {
        "2026-03-23": {"start": "08:00", "end": "16:30", "pause": 30},
    })
    fixed_mtime = 1_700_000_000  # 2023-11-14T22:13:20Z
    os.utime(path, (fixed_mtime, fixed_mtime))
    storage = Storage(path, device_id="dev-1")
    assert storage.get_all_raw()["2026-03-23"]["modified_at"] == "2023-11-14T22:13:20Z"


def test_user_facing_get_all_after_migration(tmp_path):
    """UI-Code sieht nach Migration die Slot-Shape."""
    path = _write_legacy_json(tmp_path, {
        "2026-03-23": {"start": "08:00", "end": "16:30", "pause": 30},
    })
    storage = Storage(path, device_id="dev-1")
    assert storage.get_all() == {
        "2026-03-23": {"slots": [{"start": "08:00", "end": "16:30", "pause": 30, "kategorie": ""}]}
    }


def test_v2_entry_with_metadata_gets_slot_wrapped_keeping_metadata(tmp_path):
    """v2-Eintrag (Metadaten da, aber kein slots-Key) wird in Slots gewrappt;
    modified_at/device_id bleiben erhalten (keine Re-Stampelung)."""
    path = _write_legacy_json(tmp_path, {
        "2026-03-23": {
            "start": "08:00", "end": "16:30", "pause": 30,
            "modified_at": "2026-05-01T10:00:00Z",
            "device_id": "other-device",
            "deleted": False,
        },
    })
    storage = Storage(path, device_id="dev-1")
    raw = storage.get_all_raw()["2026-03-23"]
    assert raw["slots"] == [{"start": "08:00", "end": "16:30", "pause": 30, "kategorie": ""}]
    assert raw["modified_at"] == "2026-05-01T10:00:00Z"
    assert raw["device_id"] == "other-device"
    assert raw["deleted"] is False


def test_legacy_tombstone_becomes_empty_slots(tmp_path):
    """Alt-Tombstone (deleted=true, start=null) → slots=[]."""
    path = _write_legacy_json(tmp_path, {
        "2026-03-23": {
            "start": None, "end": None, "pause": None,
            "modified_at": "2026-05-01T10:00:00Z",
            "device_id": "other-device",
            "deleted": True,
        },
    })
    storage = Storage(path, device_id="dev-1")
    raw = storage.get_all_raw()["2026-03-23"]
    assert raw["slots"] == []
    assert raw["deleted"] is True


def test_migration_idempotent_after_persist(tmp_path):
    """Zweites Laden einer bereits migrierten Datei wrappt nicht erneut."""
    path = _write_legacy_json(tmp_path, {
        "2026-03-23": {"start": "08:00", "end": "16:30", "pause": 30},
    })
    s1 = Storage(path, device_id="dev-1")
    s1._save_to_disk()  # migrierte Form persistieren
    s2 = Storage(path, device_id="dev-1")
    raw = s2.get_all_raw()["2026-03-23"]
    assert raw["slots"] == [{"start": "08:00", "end": "16:30", "pause": 30, "kategorie": ""}]
    # Slot ist nicht doppelt verschachtelt
    assert "slots" not in raw["slots"][0]
