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


# --- v2 -> v3 über die Sync-Grenze: migrierte Altdaten müssen sich verlustfrei
#     als v3-Doc bauen und in ein frisches v3-Gerät mergen lassen ---

from src.sync import build_local_doc, merge, apply_merged_doc, SCHEMA_VERSION
from src.settings import Settings
from src.conflicts_store import ConflictsStore


def _stores(tmp_path, name, device_id):
    storage = Storage(str(tmp_path / f"{name}.json"), device_id=device_id)
    settings = Settings(str(tmp_path / f"{name}-s.json"))
    settings.device_id_for_sync = device_id
    conflicts = ConflictsStore(str(tmp_path / f"{name}-c.json"))
    return storage, settings, conflicts


def test_migrated_v2_entry_round_trips_through_v3_sync(tmp_path):
    """End-to-End: Gerät mit flachen v2-Daten wird auf v3 aktualisiert; die
    migrierten Daten erscheinen als valides v3-Doc (schema_version 3 + slots)
    und mergen verlustfrei in ein frisches v3-Gerät (kein ValueError in
    apply_merge, keine geplätteten Einträge)."""
    path = _write_legacy_json(tmp_path, {
        "2026-03-23": {
            "start": "08:00", "end": "16:30", "pause": 30,
            "modified_at": "2026-05-01T10:00:00Z",
            "device_id": "old-dev", "deleted": False,
        },
    })
    old = Storage(path, device_id="old-dev")
    old_settings = Settings(str(tmp_path / "old-s.json"))
    old_settings.device_id_for_sync = "old-dev"
    old_conflicts = ConflictsStore(str(tmp_path / "old-c.json"))

    # build_local_doc nach Migration -> v3-Doc mit slots
    doc = build_local_doc(old, old_settings, old_conflicts)
    assert SCHEMA_VERSION == 4
    assert doc["schema_version"] == 4
    assert doc["entries"]["2026-03-23"]["slots"] == [
        {"start": "08:00", "end": "16:30", "pause": 30, "kategorie": ""}
    ]

    # frisches v3-Gerät pullt das Doc -> verlustfreier Merge
    fresh, fresh_settings, fresh_conflicts = _stores(tmp_path, "fresh", "new-dev")
    merged = merge(build_local_doc(fresh, fresh_settings, fresh_conflicts), doc, "")
    apply_merged_doc(merged, fresh, fresh_settings, fresh_conflicts)

    assert fresh.get_all() == {
        "2026-03-23": {"slots": [
            {"start": "08:00", "end": "16:30", "pause": 30, "kategorie": ""}]}
    }


def test_migrated_v2_tombstone_round_trips_through_v3_sync(tmp_path):
    """Auch ein migrierter Alt-Tombstone (deleted=true -> slots=[]) muss die
    Sync-Grenze als Löschung überstehen, nicht als lebender Leereintrag."""
    path = _write_legacy_json(tmp_path, {
        "2026-03-23": {
            "start": None, "end": None, "pause": None,
            "modified_at": "2026-05-01T10:00:00Z",
            "device_id": "old-dev", "deleted": True,
        },
    })
    old = Storage(path, device_id="old-dev")
    old_settings = Settings(str(tmp_path / "old2-s.json"))
    old_settings.device_id_for_sync = "old-dev"
    old_conflicts = ConflictsStore(str(tmp_path / "old2-c.json"))

    doc = build_local_doc(old, old_settings, old_conflicts)
    assert doc["entries"]["2026-03-23"]["slots"] == []
    assert doc["entries"]["2026-03-23"]["deleted"] is True

    fresh, fresh_settings, fresh_conflicts = _stores(tmp_path, "fresh2", "new-dev")
    merged = merge(build_local_doc(fresh, fresh_settings, fresh_conflicts), doc, "")
    apply_merged_doc(merged, fresh, fresh_settings, fresh_conflicts)

    # Tombstone bleibt Löschung: nicht in der User-Sicht, aber als deleted im Raw.
    assert "2026-03-23" not in fresh.get_all()
    assert fresh.get_all_raw()["2026-03-23"]["deleted"] is True
