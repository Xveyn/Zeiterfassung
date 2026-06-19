from src.reservations_sync import merge_reservations


def _lslot(start="09:00", end="17:00", kategorie="", event_id=None):
    return {"start": start, "end": end, "kategorie": kategorie, "gcal_event_id": event_id}


def _local(slots=None, modified_at="2026-05-20T10:00:00Z", deleted=False):
    return {
        "slots": slots if slots is not None else [_lslot()],
        "modified_at": modified_at, "deleted": deleted,
    }


def _remote(date="2026-06-01", start="09:00", end="17:00", kategorie="",
            modified_at="2026-05-20T10:00:00Z", event_id="ev1"):
    return {"date": date, "start": start, "end": end, "kategorie": kategorie,
            "modified_at": modified_at, "event_id": event_id}


def test_local_only_new_creates_event_per_slot():
    res = merge_reservations(
        {"2026-06-01": _local(slots=[_lslot(kategorie="Büro")],
                              modified_at="2026-05-20T10:00:00Z")},
        [], "2026-05-19T00:00:00Z")
    assert res["plan"]["create"] == [{
        "date": "2026-06-01", "slot_index": 0, "start": "09:00", "end": "17:00",
        "kategorie": "Büro", "modified_at": "2026-05-20T10:00:00Z"}]
    assert "2026-06-01" in res["merged"]


def test_local_only_stale_is_dropped():
    res = merge_reservations(
        {"2026-06-01": _local(modified_at="2026-05-10T10:00:00Z")},
        [], "2026-05-19T00:00:00Z")
    assert res["merged"] == {}
    assert res["plan"]["create"] == []


def test_local_only_exactly_at_watermark_is_dropped():
    res = merge_reservations(
        {"2026-06-01": _local(modified_at="2026-05-19T00:00:00Z")},
        [], "2026-05-19T00:00:00Z")
    assert res["merged"] == {}
    assert res["plan"]["create"] == []


def test_remote_only_is_imported_as_slots():
    res = merge_reservations({}, [_remote(kategorie="HO")], "2026-05-19T00:00:00Z")
    slots = res["merged"]["2026-06-01"]["slots"]
    assert slots == [{"start": "09:00", "end": "17:00", "kategorie": "HO", "gcal_event_id": "ev1"}]
    assert res["plan"] == {"create": [], "update": [], "delete": []}


def test_remote_only_multiple_events_become_multiple_slots():
    res = merge_reservations(
        {},
        [_remote(start="08:00", end="12:00", event_id="a"),
         _remote(start="13:00", end="17:00", event_id="b")],
        "2026-05-19T00:00:00Z")
    ids = sorted(s["gcal_event_id"] for s in res["merged"]["2026-06-01"]["slots"])
    assert ids == ["a", "b"]
    assert res["plan"] == {"create": [], "update": [], "delete": []}


def test_local_wins_updates_matched_slot():
    res = merge_reservations(
        {"2026-06-01": _local(slots=[_lslot(start="08:00", event_id="ev1")],
                              modified_at="2026-05-21T10:00:00Z")},
        [_remote(start="09:00", modified_at="2026-05-20T10:00:00Z", event_id="ev1")],
        "2026-05-19T00:00:00Z")
    assert res["plan"]["update"] == [{
        "event_id": "ev1", "date": "2026-06-01", "start": "08:00", "end": "17:00",
        "kategorie": "", "modified_at": "2026-05-21T10:00:00Z"}]
    assert res["merged"]["2026-06-01"]["slots"][0]["gcal_event_id"] == "ev1"


def test_local_wins_category_change_updates():
    res = merge_reservations(
        {"2026-06-01": _local(slots=[_lslot(kategorie="HO", event_id="ev1")],
                              modified_at="2026-05-21T10:00:00Z")},
        [_remote(kategorie="Büro", modified_at="2026-05-20T10:00:00Z", event_id="ev1")],
        "2026-05-19T00:00:00Z")
    assert len(res["plan"]["update"]) == 1
    assert res["plan"]["update"][0]["kategorie"] == "HO"


def test_local_wins_equal_values_no_update():
    res = merge_reservations(
        {"2026-06-01": _local(slots=[_lslot(event_id="ev1")],
                              modified_at="2026-05-21T10:00:00Z")},
        [_remote(modified_at="2026-05-20T10:00:00Z", event_id="ev1")],
        "2026-05-19T00:00:00Z")
    assert res["plan"]["update"] == []
    assert res["merged"]["2026-06-01"]["slots"][0]["gcal_event_id"] == "ev1"


def test_local_wins_new_slot_creates_extra_event():
    res = merge_reservations(
        {"2026-06-01": _local(
            slots=[_lslot(start="08:00", end="12:00", event_id="ev1"),
                   _lslot(start="13:00", end="17:00", event_id=None)],
            modified_at="2026-05-21T10:00:00Z")},
        [_remote(start="08:00", end="12:00", modified_at="2026-05-20T10:00:00Z", event_id="ev1")],
        "2026-05-19T00:00:00Z")
    assert res["plan"]["update"] == []
    assert res["plan"]["create"] == [{
        "date": "2026-06-01", "slot_index": 1, "start": "13:00", "end": "17:00",
        "kategorie": "", "modified_at": "2026-05-21T10:00:00Z"}]
    assert res["plan"]["delete"] == []


def test_local_wins_removed_slot_deletes_orphan_event():
    res = merge_reservations(
        {"2026-06-01": _local(slots=[_lslot(start="08:00", end="12:00", event_id="ev1")],
                              modified_at="2026-05-21T10:00:00Z")},
        [_remote(start="08:00", end="12:00", modified_at="2026-05-20T10:00:00Z", event_id="ev1"),
         _remote(start="13:00", end="17:00", modified_at="2026-05-20T10:00:00Z", event_id="ev2")],
        "2026-05-19T00:00:00Z")
    assert res["plan"]["delete"] == [{"event_id": "ev2"}]
    assert [s["gcal_event_id"] for s in res["merged"]["2026-06-01"]["slots"]] == ["ev1"]


def test_remote_wins_adopts_remote_slots():
    res = merge_reservations(
        {"2026-06-01": _local(slots=[_lslot(start="08:00", event_id="ev1")],
                              modified_at="2026-05-20T10:00:00Z")},
        [_remote(start="09:00", modified_at="2026-05-21T10:00:00Z", event_id="ev1")],
        "2026-05-19T00:00:00Z")
    assert res["merged"]["2026-06-01"]["slots"][0]["start"] == "09:00"
    assert res["plan"]["update"] == []


def test_tombstone_newer_deletes_all_events():
    res = merge_reservations(
        {"2026-06-01": _local(slots=[], deleted=True, modified_at="2026-05-21T10:00:00Z")},
        [_remote(modified_at="2026-05-20T10:00:00Z", event_id="ev1"),
         _remote(start="13:00", modified_at="2026-05-20T10:00:00Z", event_id="ev2")],
        "2026-05-19T00:00:00Z")
    deleted = sorted(d["event_id"] for d in res["plan"]["delete"])
    assert deleted == ["ev1", "ev2"]
    assert "2026-06-01" not in res["merged"]


def test_tombstone_older_than_remote_is_dropped():
    res = merge_reservations(
        {"2026-06-01": _local(slots=[], deleted=True, modified_at="2026-05-20T10:00:00Z")},
        [_remote(modified_at="2026-05-21T10:00:00Z", event_id="ev1")],
        "2026-05-19T00:00:00Z")
    assert res["plan"]["delete"] == []
    assert res["merged"]["2026-06-01"]["slots"][0]["start"] == "09:00"


def test_tombstone_without_remote_is_noop():
    res = merge_reservations(
        {"2026-06-01": _local(slots=[], deleted=True, modified_at="2026-05-21T10:00:00Z")},
        [], "2026-05-19T00:00:00Z")
    assert res["merged"] == {}
    assert res["plan"] == {"create": [], "update": [], "delete": []}


# --- reconcile (mit gemockten gcal-I/O) ---


def test_reconcile_creates_event_and_persists_event_id_per_slot(tmp_path, monkeypatch):
    from src import gcal, reservations_sync
    from src.reservations import ReservationStore
    from src.settings import Settings

    store = ReservationStore(str(tmp_path / "res.json"))
    store.save("2026-06-01", [{"start": "09:00", "end": "17:00", "kategorie": "Büro"}])
    settings = Settings(str(tmp_path / "set.json"))

    monkeypatch.setattr(gcal, "list_app_events", lambda s, c: [])
    monkeypatch.setattr(gcal, "update_event", lambda *a: None)
    monkeypatch.setattr(gcal, "delete_event", lambda *a: None)
    monkeypatch.setattr(
        gcal, "create_event",
        lambda s, c, date, start, end, kategorie, modified_at: "new-event-id")

    reservations_sync.reconcile_reservations(object(), "cal-1", store, settings)

    raw = store.get_all_raw()["2026-06-01"]
    assert raw["slots"][0]["gcal_event_id"] == "new-event-id"
    assert settings.get("last_calendar_sync_at") != ""


def test_reconcile_imported_update_plans_update(tmp_path, monkeypatch):
    """AP5-Forward-Test: ein lokal geändertes (jüngeres) Slot mit bestehender
    event_id wird beim Reconcile als update geplant (kein Duplikat)."""
    from src import gcal, reservations_sync
    from src.reservations import ReservationStore
    from src.settings import Settings

    store = ReservationStore(str(tmp_path / "res.json"))
    # Slot mit bereits bekannter event_id (wie nach einem früheren Reconcile).
    store.save("2026-06-01", [{"start": "10:00", "end": "14:00",
                               "kategorie": "", "gcal_event_id": "evt-1"}])
    settings = Settings(str(tmp_path / "set.json"))

    updated = []
    remote = {"date": "2026-06-01", "start": "08:00", "end": "12:00",
              "kategorie": "", "modified_at": "2020-01-01T00:00:00Z", "event_id": "evt-1"}
    monkeypatch.setattr(gcal, "list_app_events", lambda s, c: [remote])
    monkeypatch.setattr(gcal, "create_event", lambda *a: "x")
    monkeypatch.setattr(gcal, "delete_event", lambda *a: None)
    monkeypatch.setattr(
        gcal, "update_event",
        lambda s, c, event_id, *a: updated.append(event_id))

    reservations_sync.reconcile_reservations(object(), "cal-1", store, settings)

    assert updated == ["evt-1"]
    assert store.get_all_raw()["2026-06-01"]["slots"][0]["start"] == "10:00"


def test_reconcile_preserves_concurrent_local_save(tmp_path, monkeypatch):
    from src import gcal, reservations_sync
    from src.reservations import ReservationStore
    from src.settings import Settings

    store = ReservationStore(str(tmp_path / "res.json"))
    settings = Settings(str(tmp_path / "set.json"))

    def fake_list(s, c):
        store.save("2026-07-01", [{"start": "10:00", "end": "18:00", "kategorie": ""}])
        return []

    monkeypatch.setattr(gcal, "list_app_events", fake_list)
    monkeypatch.setattr(gcal, "create_event", lambda *a: "ev")
    monkeypatch.setattr(gcal, "update_event", lambda *a: None)
    monkeypatch.setattr(gcal, "delete_event", lambda *a: None)

    reservations_sync.reconcile_reservations(object(), "cal-1", store, settings)

    assert store.get("2026-07-01") == {"slots": [{"start": "10:00", "end": "18:00", "kategorie": ""}]}
