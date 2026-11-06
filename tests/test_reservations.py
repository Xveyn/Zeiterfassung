import json
import logging
from unittest import mock

import pytest
from src.reservations import (
    fit_pause,
    ReservationStore, inherit_pause, migrate_reservations_enabled, normalize_pause,
    reservations_active,
)
from src.settings import SYNCED_SETTING_KEYS, Settings


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
                       "send_reminder_minutes": s.get("send_reminder_minutes"),
                       "pause": s.get("pause", 0)}
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
    assert store.get("2026-06-01") == {"slots": [{"start": "09:00", "end": "17:00", "kategorie": "Büro", "send_reminder_minutes": None, "pause": 0}]}


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


def test_reservations_enabled_is_off_by_default_and_device_local(tmp_path):
    settings = Settings(str(tmp_path / "settings.json"))
    assert settings.get("reservations_enabled") is False
    assert settings.get("reservations_migrated") is False
    assert "reservations_enabled" not in SYNCED_SETTING_KEYS
    assert "reservations_migrated" not in SYNCED_SETTING_KEYS


def test_reservations_active_needs_store_and_switch(tmp_path):
    settings = Settings(str(tmp_path / "settings.json"))
    store = object()
    assert reservations_active(store, settings) is False
    settings.set("reservations_enabled", True)
    assert reservations_active(store, settings) is True
    assert reservations_active(None, settings) is False


def test_reservations_active_ignores_gcal(tmp_path):
    settings = Settings(str(tmp_path / "settings.json"))
    settings.set("gcal_enabled", True)
    assert reservations_active(object(), settings) is False


def test_migration_turns_reservations_on_for_calendar_users(tmp_path):
    settings = Settings(str(tmp_path / "settings.json"))
    settings.set("gcal_enabled", True)
    migrate_reservations_enabled(settings)
    assert settings.get("reservations_enabled") is True
    assert settings.get("reservations_migrated") is True


def test_migration_leaves_users_without_calendar_off(tmp_path):
    settings = Settings(str(tmp_path / "settings.json"))
    migrate_reservations_enabled(settings)
    assert settings.get("reservations_enabled") is False
    assert settings.get("reservations_migrated") is True


def test_migration_runs_only_once(tmp_path):
    """Wer Reservierungen später bewusst ausschaltet, behält das."""
    settings = Settings(str(tmp_path / "settings.json"))
    settings.set("gcal_enabled", True)
    migrate_reservations_enabled(settings)
    settings.set("reservations_enabled", False)
    migrate_reservations_enabled(settings)
    assert settings.get("reservations_enabled") is False


def test_migration_persists(tmp_path):
    path = str(tmp_path / "settings.json")
    settings = Settings(path)
    settings.set("gcal_enabled", True)
    migrate_reservations_enabled(settings)
    again = Settings(path)
    assert again.get("reservations_enabled") is True
    assert again.get("reservations_migrated") is True


# --- merge_phone (Handy-Abgleich) ---------------------------------------------------------------

def _phone_store(tmp_path):
    return ReservationStore(str(tmp_path / "reservations.json"))


def _phone(*slots, modified_at="2026-10-13T10:00:00Z", deleted=False):
    return {"slots": [dict(s) for s in slots], "modified_at": modified_at, "deleted": deleted}


PHONE_SLOT = {"start": "09:00", "end": "12:00", "kategorie": "Projekt"}


def test_merge_phone_adds_a_new_day_with_the_phones_timestamp(tmp_path):
    store = _phone_store(tmp_path)

    changed = store.merge_phone({"2026-10-20": _phone(PHONE_SLOT)},
                                now="2026-10-13T10:00:00Z")

    assert changed is True
    raw = store.get_all_raw()["2026-10-20"]
    assert raw["modified_at"] == "2026-10-13T10:00:00Z"
    assert raw["deleted"] is False
    assert raw["slots"] == [{"start": "09:00", "end": "12:00", "kategorie": "Projekt",
                             "gcal_event_id": None, "send_reminder_minutes": None,
                             "pause": 0}]


def test_merge_phone_is_idempotent(tmp_path):
    store = _phone_store(tmp_path)
    store.merge_phone({"2026-10-20": _phone(PHONE_SLOT)}, now="2026-10-13T10:10:00Z")
    before = (tmp_path / "reservations.json").read_bytes()

    changed = store.merge_phone({"2026-10-20": _phone(PHONE_SLOT)})

    assert changed is False
    assert (tmp_path / "reservations.json").read_bytes() == before


def test_merge_phone_keeps_calendar_ids_and_reminders_by_index(tmp_path):
    store = _phone_store(tmp_path)
    store.apply_reconciled({"2026-10-20": {
        "slots": [{"start": "09:00", "end": "12:00", "kategorie": "Projekt",
                   "gcal_event_id": "ev1", "send_reminder_minutes": 15}],
        "modified_at": "2026-10-12T08:00:00Z", "deleted": False}})

    changed = store.merge_phone({"2026-10-20": _phone(
        {"start": "09:30", "end": "12:00", "kategorie": "Projekt"})})

    assert changed is True
    slot = store.get_all_raw()["2026-10-20"]["slots"][0]
    assert slot["start"] == "09:30"
    assert slot["gcal_event_id"] == "ev1"
    assert slot["send_reminder_minutes"] == 15


def test_merge_phone_loses_against_a_newer_desktop_day(tmp_path):
    store = _phone_store(tmp_path)
    store.apply_reconciled({"2026-10-20": {
        "slots": [{"start": "08:00", "end": "09:00", "kategorie": "",
                   "gcal_event_id": None, "send_reminder_minutes": None}],
        "modified_at": "2026-10-13T11:00:00Z", "deleted": False}})

    changed = store.merge_phone({"2026-10-20": _phone(PHONE_SLOT, modified_at="2026-10-13T10:00:00Z")})

    assert changed is False
    assert store.get_all_raw()["2026-10-20"]["slots"][0]["start"] == "08:00"


def test_merge_phone_tombstone_deletes_a_known_day(tmp_path):
    store = _phone_store(tmp_path)
    # `now` festnageln: ohne Angabe stempelt `merge_phone` mit der echten Uhr, und der Test
    # hinge davon ab, ob sie vor oder nach den festen Stempeln unten liegt.
    store.merge_phone({"2026-10-20": _phone(PHONE_SLOT)}, now="2026-10-13T10:10:00Z")

    changed = store.merge_phone({"2026-10-20": _phone(modified_at="2026-10-13T12:00:00Z", deleted=True)},
                                now="2026-10-13T12:00:00Z")

    assert changed is True
    assert store.get_all_raw()["2026-10-20"] == {
        "slots": [], "modified_at": "2026-10-13T12:00:00Z", "deleted": True}
    assert store.get("2026-10-20") is None


def test_merge_phone_ignores_a_tombstone_for_an_unknown_day(tmp_path):
    store = _phone_store(tmp_path)

    changed = store.merge_phone({"2026-10-20": _phone(modified_at="2026-10-13T12:00:00Z", deleted=True)})

    assert changed is False
    assert store.get_all_raw() == {}


def test_merge_phone_keeps_memory_unchanged_when_the_write_fails(tmp_path, monkeypatch):
    store = _phone_store(tmp_path)

    def boom(*_args, **_kwargs):
        raise OSError("Platte voll")

    monkeypatch.setattr("src.reservations.atomic_write_json", boom)

    with pytest.raises(OSError):
        store.merge_phone({"2026-10-20": _phone(PHONE_SLOT)})

    assert store.get_all_raw() == {}


def test_merge_phone_raises_an_old_stamp_to_the_floor_so_a_slow_phone_clock_still_wins(tmp_path):
    store = _phone_store(tmp_path)
    store.apply_reconciled({"2026-10-20": {
        "slots": [{"start": "08:00", "end": "09:00", "kategorie": "",
                   "gcal_event_id": None, "send_reminder_minutes": None}],
        "modified_at": "2026-10-13T11:00:00Z", "deleted": False}})

    # Das Handy hat den Tag nach dem letzten Abgleich (11:30) geändert, seine Uhr geht nach.
    changed = store.merge_phone({"2026-10-20": _phone(PHONE_SLOT, modified_at="2026-10-13T10:58:00Z")},
                                floor="2026-10-13T11:30:01Z", now="2026-10-13T11:40:00Z")

    assert changed is True
    assert store.get_all_raw()["2026-10-20"]["slots"][0]["start"] == "09:00"


def test_merge_phone_stamps_a_won_day_with_the_receipt_time_so_the_calendar_keeps_it(tmp_path):
    store = _phone_store(tmp_path)

    store.merge_phone({"2026-10-20": _phone(PHONE_SLOT, modified_at="2026-10-13T10:00:00Z")},
                      now="2026-10-13T10:10:00Z")

    assert store.get_all_raw()["2026-10-20"]["modified_at"] == "2026-10-13T10:10:00Z"


def test_merge_phone_stays_idempotent_with_the_receipt_stamp(tmp_path):
    store = _phone_store(tmp_path)
    day = {"2026-10-20": _phone(PHONE_SLOT, modified_at="2026-10-13T10:00:00Z")}
    store.merge_phone(day, floor="2026-10-13T09:00:01Z", now="2026-10-13T10:10:00Z")

    again = store.merge_phone(day, floor="2026-10-13T09:00:01Z", now="2026-10-13T10:20:00Z")

    assert again is False


# --- Pause an Reservierungen (#455) -------------------------------------------------------------

def test_slot_defaults_pause_to_zero(tmp_path):
    path = tmp_path / "res.json"
    path.write_text(json.dumps({"2026-12-01": {
        "slots": [{"start": "08:00", "end": "12:00", "kategorie": "A",
                   "gcal_event_id": None, "send_reminder_minutes": None}],
        "modified_at": "2026-11-01T10:00:00Z", "deleted": False}}), encoding="utf-8")
    store = ReservationStore(str(path))
    assert store.get("2026-12-01")["slots"][0]["pause"] == 0


def test_save_keeps_pause_and_get_all_returns_it(store):
    store.save("2026-12-01", [{"start": "08:00", "end": "15:30", "kategorie": "A", "pause": 30}])
    assert store.get_all()["2026-12-01"]["slots"][0]["pause"] == 30
    assert store.get_all_raw()["2026-12-01"]["slots"][0]["pause"] == 30


def test_normalize_pause_rejects_bad_values():
    for bad in (True, 30.0, "30", -1, 1441, None):
        assert normalize_pause(bad) == 0
    assert normalize_pause(30) == 30
    assert normalize_pause(0) == 0
    assert normalize_pause(1440) == 1440


def _old(start, end, pause=None):
    s = {"start": start, "end": end, "kategorie": "A"}
    if pause is not None:
        s["pause"] = pause
    return s


def test_inherit_pause_same_index_same_times():
    out = inherit_pause([_old("08:00", "12:00", 30)], [{"start": "08:00", "end": "12:00"}])
    assert out[0]["pause"] == 30


def test_inherit_pause_not_for_inserted_slot():
    out = inherit_pause([_old("08:00", "12:00", 30)],
                        [{"start": "06:00", "end": "07:00", "kategorie": "B"},
                         {"start": "08:00", "end": "12:00", "kategorie": "A"}])
    assert [s["pause"] for s in out] == [0, 0]


@pytest.mark.parametrize("pause,start,end,expected", [
    (19, "08:00", "08:20", 19), (20, "08:00", "08:20", 0), (0, "08:00", "08:20", 0),
    (30, "22:00", "02:00", 0), (30, "08:00", "08:00", 0),
    (True, "08:00", "12:00", 0), (30.0, "08:00", "12:00", 0),
    (30, None, "12:00", 30), (30, "aa:bb", "12:00", 30),
])
def test_fit_pause(pause, start, end, expected):
    assert fit_pause(pause, start, end) == expected


def test_inherit_drops_pause_not_below_span():
    out = inherit_pause([_old("08:00", "08:20", 30)], [{"start": "08:00", "end": "08:20"}])
    assert out[0]["pause"] == 0


def test_inherit_keeps_explicit_zero():
    out = inherit_pause([_old("08:00", "12:00", 30)],
                        [{"start": "08:00", "end": "12:00", "pause": 0}])
    assert out[0]["pause"] == 0


@pytest.mark.parametrize("old,new,expected", [
    ([_old("08:00", "12:00", 30)], [{"start": "08:00", "end": "12:00"}], [30]),
    ([_old("08:00", "12:00", 30)],
     [{"start": "08:00", "end": "12:00", "kategorie": "Neu"}], [30]),
    ([_old("08:00", "12:00", 30)], [{"start": "08:00", "end": "13:00"}], [0]),
    ([_old("08:00", "12:00", 30), _old("13:00", "17:00", 45)],
     [{"start": "13:00", "end": "17:00"}, {"start": "08:00", "end": "12:00"}], [0, 0]),
    ([_old("08:00", "12:00", 30), _old("13:00", "17:00", 45)],
     [{"start": "13:00", "end": "17:00"}], [0]),
    ([_old("08:00", "12:00", 30)],
     [{"start": "08:00", "end": "12:00"}, {"start": "13:00", "end": "17:00"}], [30, 0]),
    ([_old("08:00", "12:00")], [{"start": "08:00", "end": "12:00"}], [0]),
    ([_old("08:00", "12:00", 30)], [{"start": "08:00", "end": "12:00", "pause": 0}], [0]),
])
def test_inherit_pause_cases(old, new, expected):
    assert [s["pause"] for s in inherit_pause(old, new)] == expected


def test_inherit_pause_does_not_mutate_input():
    new = [{"start": "08:00", "end": "12:00"}]
    inherit_pause([_old("08:00", "12:00", 30)], new)
    assert "pause" not in new[0]


def _store_with_pause(tmp_path, pause):
    store = _phone_store(tmp_path)
    store.apply_reconciled({"2026-10-20": {
        "slots": [{"start": "09:00", "end": "12:00", "kategorie": "Projekt",
                   "gcal_event_id": None, "send_reminder_minutes": None, "pause": pause}],
        "modified_at": "2026-10-13T09:00:00Z", "deleted": False}})
    return store


def test_merge_phone_inherits_pause_when_absent(tmp_path):
    store = _store_with_pause(tmp_path, 30)
    changed = store.merge_phone({"2026-10-20": _phone(
        PHONE_SLOT, modified_at="2026-10-13T10:00:00Z")}, now="2026-10-13T10:05:00Z")
    assert changed is True
    assert store.get_all_raw()["2026-10-20"]["slots"][0]["pause"] == 30


def test_merge_phone_takes_explicit_pause(tmp_path):
    store = _store_with_pause(tmp_path, 30)
    store.merge_phone({"2026-10-20": _phone(
        {**PHONE_SLOT, "pause": 45}, modified_at="2026-10-13T10:00:00Z")},
        now="2026-10-13T10:05:00Z")
    assert store.get_all_raw()["2026-10-20"]["slots"][0]["pause"] == 45


def test_phone_key_old_slot_without_key_equals_zero(tmp_path):
    path = tmp_path / "reservations.json"
    path.write_text(json.dumps({"2026-10-20": {
        "slots": [{"start": "09:00", "end": "12:00", "kategorie": "Projekt",
                   "gcal_event_id": None, "send_reminder_minutes": None}],
        "modified_at": "2026-10-13T10:00:00Z", "deleted": False}}), encoding="utf-8")
    store = ReservationStore(str(path))
    before_bytes = path.read_bytes()
    before_mtime = path.stat().st_mtime_ns
    changed = store.merge_phone({"2026-10-20": _phone(
        {**PHONE_SLOT, "pause": 0}, modified_at="2026-10-13T10:00:00Z")})
    assert changed is False
    assert path.read_bytes() == before_bytes
    assert path.stat().st_mtime_ns == before_mtime


def test_phone_key_bigger_phone_pause_wins_at_equal_stamp(tmp_path):
    store = _store_with_pause(tmp_path, 30)
    changed = store.merge_phone({"2026-10-20": _phone(
        {**PHONE_SLOT, "pause": 45}, modified_at="2026-10-13T09:00:00Z")},
        now="2026-10-13T09:00:00Z")
    assert changed is True
    assert store.get_all_raw()["2026-10-20"]["slots"][0]["pause"] == 45


def test_phone_key_smaller_phone_pause_loses_at_equal_stamp(tmp_path):
    # Bekannte Eigenheit: bei Gleichstand der Stempel gewinnt nach JSON-Ordnung die
    # groessere Pause, hier also der Store (30 gegen 0).
    store = _store_with_pause(tmp_path, 30)
    changed = store.merge_phone({"2026-10-20": _phone(
        {**PHONE_SLOT, "pause": 0}, modified_at="2026-10-13T09:00:00Z")},
        now="2026-10-13T09:00:00Z")
    assert changed is False
    assert store.get_all_raw()["2026-10-20"]["slots"][0]["pause"] == 30


def test_partial_delete_keeps_other_slots_pause(store):
    from src.ui import _delete_action
    store.save("2026-12-01", [
        {"start": "08:00", "end": "12:00", "kategorie": "A", "pause": 30},
        {"start": "13:00", "end": "17:00", "kategorie": "B", "pause": 45}])
    res_slots = store.get("2026-12-01")["slots"]
    action, keep = _delete_action(res_slots, {"reservation:0"}, "reservation")
    assert action == "save"
    store.save("2026-12-01", keep)
    after = store.get("2026-12-01")["slots"]
    assert [(s["start"], s["pause"]) for s in after] == [("13:00", 45)]
