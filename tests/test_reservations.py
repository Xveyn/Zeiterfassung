import logging
from unittest import mock

import pytest
from src.reservations import ReservationStore


@pytest.fixture
def store(tmp_path):
    return ReservationStore(str(tmp_path / "res.json"))


def _slot(start, end, kategorie="", gcal_event_id=None, send_reminder_minutes=None):
    """Roh-Slot (inkl. gcal_event_id), wie er in get_all_raw erscheint."""
    return {"start": start, "end": end, "kategorie": kategorie,
            "gcal_event_id": gcal_event_id,
            "send_reminder_minutes": send_reminder_minutes}


def _ushape(*slots):
    """Erwartete User-Shape: slots ohne gcal_event_id."""
    return {"slots": [{"start": s["start"], "end": s["end"],
                       "kategorie": s["kategorie"],
                       "send_reminder_minutes": s.get("send_reminder_minutes")}
                      for s in slots]}


def test_load_empty(store):
    assert store.get_all() == {}


def test_save_and_get(store):
    store.save("2026-06-01", [_slot("09:00", "17:00")])
    assert store.get("2026-06-01") == _ushape(_slot("09:00", "17:00"))
    assert store.get_all() == {"2026-06-01": _ushape(_slot("09:00", "17:00"))}


def test_save_multiple_slots_with_categories(store):
    slots = [_slot("09:00", "12:00", "Kundentermin"), _slot("13:00", "17:00", "Büro")]
    store.save("2026-06-01", slots)
    assert store.get("2026-06-01") == _ushape(*slots)


def test_save_stamps_metadata(store):
    store.save("2026-06-01", [_slot("09:00", "17:00")])
    raw = store.get_all_raw()["2026-06-01"]
    assert raw["deleted"] is False
    assert raw["modified_at"].endswith("Z") and "T" in raw["modified_at"]


def test_save_stores_provided_event_id(store):
    """save speichert eine mitgelieferte gcal_event_id am Slot."""
    store.save("2026-06-01", [_slot("09:00", "17:00", "", "ev-1")])
    assert store.get_all_raw()["2026-06-01"]["slots"][0]["gcal_event_id"] == "ev-1"


def test_save_preserves_event_id_by_index_on_edit(store):
    """Ein Dialog-Edit liefert Slots OHNE gcal_event_id. save übernimmt die
    bestehenden ids positionsweise, damit der Reconcile die Events aktualisiert
    statt sie zu löschen und neu anzulegen."""
    store.save("2026-06-01", [_slot("08:00", "12:00", "A", "E1"),
                              _slot("13:00", "17:00", "B", "E2")])
    # Edit über den Dialog: geänderte Zeiten, KEINE event_ids mitgeliefert.
    store.save("2026-06-01", [{"start": "09:00", "end": "12:00", "kategorie": "A"},
                              {"start": "13:00", "end": "18:00", "kategorie": "B"}])
    slots = store.get_all_raw()["2026-06-01"]["slots"]
    assert [s["gcal_event_id"] for s in slots] == ["E1", "E2"]
    assert slots[0]["start"] == "09:00" and slots[1]["end"] == "18:00"


def test_save_new_slot_beyond_existing_has_no_event_id(store):
    """Eine über den Altbestand hinaus hinzugefügte Zeile bekommt keine id
    (→ der Reconcile legt dafür ein neues Event an)."""
    store.save("2026-06-01", [_slot("08:00", "12:00", "A", "E1")])
    store.save("2026-06-01", [{"start": "08:00", "end": "12:00", "kategorie": "A"},
                              {"start": "13:00", "end": "17:00", "kategorie": "B"}])
    slots = store.get_all_raw()["2026-06-01"]["slots"]
    assert slots[0]["gcal_event_id"] == "E1"
    assert slots[1]["gcal_event_id"] is None


def test_slot_defaults_kategorie_and_event_id(store):
    store.save("2026-06-01", [{"start": "09:00", "end": "17:00"}])
    slot = store.get_all_raw()["2026-06-01"]["slots"][0]
    assert slot["gcal_event_id"] is None
    assert slot["kategorie"] == ""


def test_user_shape_excludes_event_id(store):
    store.save("2026-06-01", [_slot("09:00", "17:00", "Büro", "ev-1")])
    assert store.get("2026-06-01") == {"slots": [{"start": "09:00", "end": "17:00", "kategorie": "Büro", "send_reminder_minutes": None}]}


def test_delete_writes_empty_slots_tombstone(store):
    store.save("2026-06-01", [_slot("09:00", "17:00", "", "ev-1")])
    store.delete("2026-06-01")
    assert store.get("2026-06-01") is None
    tomb = store.get_all_raw()["2026-06-01"]
    assert tomb["deleted"] is True
    assert tomb["slots"] == []


def test_delete_nonexistent_is_noop(store):
    store.delete("2026-01-01")
    assert store.get_all_raw() == {}


def test_get_excludes_tombstones(store):
    store.save("2026-06-01", [_slot("09:00", "17:00")])
    store.delete("2026-06-01")
    assert "2026-06-01" not in store.get_all()
    assert "2026-06-01" in store.get_all_raw()


def test_persistence(tmp_path):
    path = str(tmp_path / "res.json")
    ReservationStore(path).save("2026-06-01", [_slot("09:00", "17:00")])
    assert ReservationStore(path).get("2026-06-01") == _ushape(_slot("09:00", "17:00"))


def test_apply_reconciled_replaces_data(store):
    store.save("2026-06-01", [_slot("09:00", "17:00")])
    store.apply_reconciled({"2026-07-01": {
        "slots": [_slot("10:00", "18:00", "", "ev-9")],
        "modified_at": "2026-05-20T10:00:00Z", "deleted": False,
    }})
    assert "2026-06-01" not in store.get_all_raw()
    assert store.get("2026-07-01") == _ushape(_slot("10:00", "18:00"))


def test_apply_reconciled_rejects_missing_keys(store):
    with pytest.raises(ValueError, match="missing keys"):
        store.apply_reconciled({"2026-06-01": {"slots": [_slot("09:00", "17:00")]}})
    # _data unverändert (kein Halb-Schreiben)
    assert store.get_all_raw() == {}


def test_corrupt_json_is_quarantined_and_starts_empty(tmp_path, caplog):
    path = tmp_path / "res.json"
    path.write_text("{not valid", encoding="utf-8")
    with caplog.at_level(logging.WARNING):
        store = ReservationStore(str(path))
    assert store.get_all() == {}
    assert len(list(tmp_path.glob("res.json.corrupt-*"))) == 1
    # N4: Quarantäne wird jetzt geloggt, nicht mehr stumm.
    assert any("Quarantäne" in r.message for r in caplog.records)


def test_save_failure_keeps_original_intact(tmp_path):
    path = tmp_path / "res.json"
    store = ReservationStore(str(path))
    store.save("2026-06-01", [_slot("09:00", "17:00")])
    original = path.read_bytes()
    with mock.patch("os.replace", side_effect=OSError("disk full")):
        with pytest.raises(OSError):
            store.save("2026-06-02", [_slot("09:00", "17:00")])
    assert path.read_bytes() == original
    assert [p for p in tmp_path.iterdir() if p.suffix == ".tmp"] == []


def test_send_reminder_minutes_survives_save_and_get(store):
    store.save("2026-08-31", [
        {"start": "08:00", "end": "12:00", "kategorie": "Office"},
        {"start": "13:00", "end": "17:00", "kategorie": "Kunde",
         "send_reminder_minutes": 15},
    ])
    slots = store.get("2026-08-31")["slots"]
    assert slots[0]["send_reminder_minutes"] is None
    assert slots[1]["send_reminder_minutes"] == 15
    raw = store.get_all_raw()["2026-08-31"]["slots"]
    assert raw[1]["send_reminder_minutes"] == 15


def test_send_reminder_minutes_missing_key_becomes_none(store):
    store.save("2026-08-31", [{"start": "08:00", "end": "12:00"}])
    assert store.get("2026-08-31")["slots"][0]["send_reminder_minutes"] is None


def test_send_reminder_minutes_out_of_range_or_wrong_type_becomes_none(store):
    store.save("2026-08-31", [
        {"start": "08:00", "end": "09:00", "send_reminder_minutes": 121},
        {"start": "09:00", "end": "10:00", "send_reminder_minutes": -1},
        {"start": "10:00", "end": "11:00", "send_reminder_minutes": "15"},
        {"start": "11:00", "end": "12:00", "send_reminder_minutes": True},
    ])
    assert [s["send_reminder_minutes"] for s in store.get("2026-08-31")["slots"]] \
        == [None, None, None, None]


def test_send_reminder_minutes_not_carried_over_positionally(store):
    """Anders als gcal_event_id wird der Marker NICHT vom Vorstand geerbt —
    sonst könnte der Dialog ihn nie löschen."""
    store.save("2026-08-31", [{"start": "08:00", "end": "12:00",
                               "send_reminder_minutes": 15}])
    store.save("2026-08-31", [{"start": "08:00", "end": "12:00"}])
    assert store.get("2026-08-31")["slots"][0]["send_reminder_minutes"] is None
