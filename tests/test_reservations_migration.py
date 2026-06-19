import json

from src.reservations import ReservationStore


def _write_legacy(tmp_path, payload):
    path = tmp_path / "legacy_res.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f)
    return str(path)


def test_legacy_reservation_wrapped_into_single_slot(tmp_path):
    path = _write_legacy(tmp_path, {
        "2026-06-01": {
            "start": "09:00", "end": "17:00",
            "modified_at": "2026-05-20T10:00:00Z",
            "deleted": False, "gcal_event_id": "ev-1",
        },
    })
    store = ReservationStore(path)
    raw = store.get_all_raw()["2026-06-01"]
    assert raw["slots"] == [
        {"start": "09:00", "end": "17:00", "kategorie": "", "gcal_event_id": "ev-1"}
    ]
    assert raw["modified_at"] == "2026-05-20T10:00:00Z"
    assert raw["deleted"] is False
    # alte Top-Level-Felder entfernt
    assert "start" not in raw and "end" not in raw and "gcal_event_id" not in raw


def test_legacy_reservation_tombstone_becomes_empty_slots(tmp_path):
    path = _write_legacy(tmp_path, {
        "2026-06-01": {
            "start": None, "end": None,
            "modified_at": "2026-05-20T10:00:00Z",
            "deleted": True, "gcal_event_id": "ev-1",
        },
    })
    store = ReservationStore(path)
    raw = store.get_all_raw()["2026-06-01"]
    assert raw["slots"] == []
    assert raw["deleted"] is True


def test_user_facing_get_all_after_migration(tmp_path):
    path = _write_legacy(tmp_path, {
        "2026-06-01": {
            "start": "09:00", "end": "17:00",
            "modified_at": "2026-05-20T10:00:00Z",
            "deleted": False, "gcal_event_id": None,
        },
    })
    store = ReservationStore(path)
    assert store.get_all() == {
        "2026-06-01": {"slots": [{"start": "09:00", "end": "17:00", "kategorie": ""}]}
    }


def test_reservation_migration_idempotent_after_persist(tmp_path):
    path = _write_legacy(tmp_path, {
        "2026-06-01": {
            "start": "09:00", "end": "17:00",
            "modified_at": "2026-05-20T10:00:00Z",
            "deleted": False, "gcal_event_id": "ev-1",
        },
    })
    s1 = ReservationStore(path)
    s1._save_to_disk()  # migrierte Form persistieren
    s2 = ReservationStore(path)
    raw = s2.get_all_raw()["2026-06-01"]
    assert raw["slots"] == [
        {"start": "09:00", "end": "17:00", "kategorie": "", "gcal_event_id": "ev-1"}
    ]
    assert "slots" not in raw["slots"][0]
