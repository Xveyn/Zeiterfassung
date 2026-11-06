from src.reservations_sync import merge_reservations


def _lslot(start="09:00", end="17:00", kategorie="", event_id=None,
           send_reminder_minutes=None, pause=0):
    return {"start": start, "end": end, "kategorie": kategorie,
            "gcal_event_id": event_id,
            "send_reminder_minutes": send_reminder_minutes, "pause": pause}


def _local(slots=None, modified_at="2026-05-20T10:00:00Z", deleted=False):
    return {
        "slots": slots if slots is not None else [_lslot()],
        "modified_at": modified_at, "deleted": deleted,
    }


def _remote(date="2026-06-01", start="09:00", end="17:00", kategorie="",
            modified_at="2026-05-20T10:00:00Z", event_id="ev1", pause=0):
    return {"date": date, "start": start, "end": end, "kategorie": kategorie,
            "modified_at": modified_at, "event_id": event_id, "pause": pause}


def test_local_only_new_creates_event_per_slot():
    res = merge_reservations(
        {"2026-06-01": _local(slots=[_lslot(kategorie="Büro")],
                              modified_at="2026-05-20T10:00:00Z")},
        [], "2026-05-19T00:00:00Z")
    assert res["plan"]["create"] == [{
        "date": "2026-06-01", "slot_index": 0, "start": "09:00", "end": "17:00",
        "kategorie": "Büro", "modified_at": "2026-05-20T10:00:00Z"}]
    assert "2026-06-01" in res["merged"]
    assert res["imported_dates"] == []


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
    assert slots == [{"start": "09:00", "end": "17:00", "kategorie": "HO", "gcal_event_id": "ev1", "send_reminder_minutes": None, "pause": 0}]
    assert res["plan"] == {"create": [], "update": [], "delete": []}
    assert res["imported_dates"] == ["2026-06-01"]


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


import pytest


@pytest.mark.parametrize("bad", [None, "30", 30.0, True, -5])
def test_malformed_stored_pause_neither_raises_nor_updates_forever(bad):
    res = merge_reservations(
        {"2026-06-01": _local(slots=[_lslot(event_id="ev1", pause=bad)],
                              modified_at="2026-05-21T10:00:00Z")},
        [_remote(modified_at="2026-05-20T10:00:00Z", event_id="ev1")],
        "2026-05-19T00:00:00Z")
    assert res["plan"]["update"] == []


def test_malformed_event_pause_counts_as_zero():
    res = merge_reservations(
        {"2026-06-01": _local(slots=[_lslot(event_id="ev1")],
                              modified_at="2026-05-21T10:00:00Z")},
        [_remote(modified_at="2026-05-20T10:00:00Z", event_id="ev1", pause=None)],
        "2026-05-19T00:00:00Z")
    assert res["plan"]["update"] == []


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
    assert res["imported_dates"] == ["2026-06-01"]


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
    assert res["imported_dates"] == ["2026-06-01"]


def test_tombstone_without_remote_is_noop():
    res = merge_reservations(
        {"2026-06-01": _local(slots=[], deleted=True, modified_at="2026-05-21T10:00:00Z")},
        [], "2026-05-19T00:00:00Z")
    assert res["merged"] == {}
    assert res["plan"] == {"create": [], "update": [], "delete": []}


def test_local_wins_has_no_imported_dates():
    """Lokal gewinnt und pusht nur zu Google — kein Import, weil keine
    Remote-Daten lokal übernommen wurden."""
    res = merge_reservations(
        {"2026-06-01": _local(slots=[_lslot(start="08:00", event_id="ev1")],
                              modified_at="2026-05-21T10:00:00Z")},
        [_remote(start="09:00", modified_at="2026-05-20T10:00:00Z", event_id="ev1")],
        "2026-05-19T00:00:00Z")
    assert res["imported_dates"] == []


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
        lambda s, c, date, start, end, kategorie, modified_at, pause=0: "new-event-id")

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

    assert store.get("2026-07-01") == {"slots": [{"start": "10:00", "end": "18:00", "kategorie": "", "send_reminder_minutes": None, "pause": 0}]}


def test_reconcile_returns_imported_dates(tmp_path, monkeypatch):
    """AP-Werkstudentenlimit: reconcile_reservations meldet zurück, welche
    Daten in diesem Lauf aus dem Kalender importiert wurden (#98)."""
    from src import gcal, reservations_sync
    from src.reservations import ReservationStore
    from src.settings import Settings

    store = ReservationStore(str(tmp_path / "res.json"))
    settings = Settings(str(tmp_path / "set.json"))

    monkeypatch.setattr(
        gcal, "list_app_events",
        lambda s, c: [{"date": "2026-06-01", "start": "09:00", "end": "17:00",
                       "kategorie": "", "modified_at": "2026-05-20T10:00:00Z",
                       "event_id": "ev1"}])
    monkeypatch.setattr(gcal, "update_event", lambda *a: None)
    monkeypatch.setattr(gcal, "delete_event", lambda *a: None)
    monkeypatch.setattr(gcal, "create_event", lambda *a: "unused")

    result = reservations_sync.reconcile_reservations(object(), "cal-1", store, settings)

    assert result["imported_dates"] == ["2026-06-01"]


def test_marker_survives_local_wins():
    res = merge_reservations(
        {"2026-06-01": _local(
            slots=[_lslot(event_id="ev1", send_reminder_minutes=15)],
            modified_at="2026-05-21T10:00:00Z")},
        [_remote(event_id="ev1", modified_at="2026-05-20T10:00:00Z")],
        "2026-05-19T00:00:00Z")
    assert res["merged"]["2026-06-01"]["slots"][0]["send_reminder_minutes"] == 15


def test_marker_follows_event_id_when_remote_wins():
    """Google liefert die Events in beliebiger Reihenfolge — der Marker muss
    dem richtigen Slot folgen, nicht der Position."""
    res = merge_reservations(
        {"2026-06-01": _local(
            slots=[_lslot(start="08:00", end="12:00", event_id="ev1"),
                   _lslot(start="13:00", end="17:00", event_id="ev2",
                          send_reminder_minutes=15)],
            modified_at="2026-05-20T10:00:00Z")},
        [_remote(start="13:00", end="17:00", event_id="ev2",
                 modified_at="2026-05-21T10:00:00Z"),
         _remote(start="08:00", end="12:00", event_id="ev1",
                 modified_at="2026-05-21T10:00:00Z")],
        "2026-05-19T00:00:00Z")
    slots = res["merged"]["2026-06-01"]["slots"]
    assert slots[0]["start"] == "13:00" and slots[0]["send_reminder_minutes"] == 15
    assert slots[1]["start"] == "08:00" and slots[1]["send_reminder_minutes"] is None


def test_marker_dropped_when_event_id_has_no_local_partner():
    res = merge_reservations(
        {"2026-06-01": _local(
            slots=[_lslot(event_id="ev1", send_reminder_minutes=15)],
            modified_at="2026-05-20T10:00:00Z")},
        [_remote(event_id="ev-neu", modified_at="2026-05-21T10:00:00Z")],
        "2026-05-19T00:00:00Z")
    slots = res["merged"]["2026-06-01"]["slots"]
    assert slots[0]["send_reminder_minutes"] is None


def test_remote_only_date_has_no_marker():
    res = merge_reservations({}, [_remote(event_id="ev1")], "2026-05-19T00:00:00Z")
    assert res["merged"]["2026-06-01"]["slots"][0]["send_reminder_minutes"] is None


# --- Pause (#455): Termin bleibt brutto, Pause reist als Property ---


def test_local_pause_with_event_without_property_updates_once():
    res = merge_reservations(
        {"2026-06-01": _local(slots=[_lslot(event_id="ev1", pause=30)])},
        [_remote(event_id="ev1", pause=0)], "2026-05-19T00:00:00Z")
    assert len(res["plan"]["update"]) == 1
    assert res["plan"]["update"][0]["pause"] == 30


def test_local_pause_zero_with_event_without_property_no_update():
    res = merge_reservations(
        {"2026-06-01": _local(slots=[_lslot(event_id="ev1", pause=0)])},
        [_remote(event_id="ev1", pause=0)], "2026-05-19T00:00:00Z")
    assert res["plan"]["update"] == []


def test_pause_change_alone_triggers_update():
    res = merge_reservations(
        {"2026-06-01": _local(slots=[_lslot(event_id="ev1", pause=45)])},
        [_remote(event_id="ev1", pause=30)], "2026-05-19T00:00:00Z")
    assert [u["pause"] for u in res["plan"]["update"]] == [45]


def test_plan_entries_carry_pause_only_when_positive():
    res = merge_reservations(
        {"2026-06-01": _local(slots=[_lslot(pause=30)])}, [], "2026-05-19T00:00:00Z")
    assert res["plan"]["create"][0]["pause"] == 30
    res = merge_reservations(
        {"2026-06-01": _local(slots=[_lslot()])}, [], "2026-05-19T00:00:00Z")
    assert "pause" not in res["plan"]["create"][0]


def test_remote_wins_takes_pause_from_event_property():
    res = merge_reservations(
        {"2026-06-01": _local(slots=[_lslot(event_id="ev1", pause=10)])},
        [_remote(event_id="ev1", pause=30, modified_at="2026-05-21T10:00:00Z")],
        "2026-05-19T00:00:00Z")
    assert res["merged"]["2026-06-01"]["slots"][0]["pause"] == 30


@pytest.mark.parametrize("pause,expected", [(19, 19), (20, 0), (30, 0)])
def test_remote_wins_pause_must_stay_below_shortened_span(pause, expected):
    res = merge_reservations(
        {"2026-06-01": _local(slots=[
            _lslot(start="08:00", end="08:40", event_id="ev1", pause=30)])},
        [_remote(start="08:00", end="08:20", event_id="ev1", pause=pause,
                 modified_at="2026-05-21T10:00:00Z")],
        "2026-05-19T00:00:00Z")
    assert res["merged"]["2026-06-01"]["slots"][0]["pause"] == expected


def test_shortened_event_settles_after_one_update():
    first = merge_reservations(
        {"2026-06-01": _local(slots=[
            _lslot(start="08:00", end="08:40", event_id="ev1", pause=30)])},
        [_remote(start="08:00", end="08:20", event_id="ev1", pause=30,
                 modified_at="2026-05-21T10:00:00Z")],
        "2026-05-19T00:00:00Z")
    merged = first["merged"]["2026-06-01"]
    again = merge_reservations(
        {"2026-06-01": merged},
        [_remote(start="08:00", end="08:20", event_id="ev1", pause=30,
                 modified_at=merged["modified_at"])],
        "2026-05-19T00:00:00Z")
    assert len(again["plan"]["update"]) <= 1
    assert "pause" not in (again["plan"]["update"] or [{}])[0]


def test_remote_wins_without_property_yields_pause_zero():
    res = merge_reservations(
        {"2026-06-01": _local(slots=[
            _lslot(start="08:00", end="12:00", event_id="ev1", pause=15)])},
        [_remote(start="08:00", end="12:00", event_id="ev1",
                 modified_at="2026-05-21T10:00:00Z")],
        "2026-05-19T00:00:00Z")
    assert res["merged"]["2026-06-01"]["slots"][0]["pause"] == 0


def test_new_remote_event_without_local_slot_has_pause_zero():
    res = merge_reservations({}, [_remote(event_id="ev9")], "2026-05-19T00:00:00Z")
    assert res["merged"]["2026-06-01"]["slots"][0]["pause"] == 0


def test_reconcile_passes_pause_to_create_and_update(tmp_path, monkeypatch):
    from src import gcal, reservations_sync
    from src.reservations import ReservationStore
    from src.settings import Settings

    store = ReservationStore(str(tmp_path / "res.json"))
    store.save("2026-06-01", [{"start": "09:00", "end": "17:00", "kategorie": "",
                               "pause": 30}])
    store.save("2026-06-02", [{"start": "09:00", "end": "17:00", "kategorie": "",
                               "pause": 20, "gcal_event_id": "evt-2"}])
    settings = Settings(str(tmp_path / "set.json"))
    calls = []
    monkeypatch.setattr(gcal, "list_app_events", lambda s, c: [
        {"date": "2026-06-02", "start": "09:00", "end": "17:00", "kategorie": "",
         "modified_at": "2020-01-01T00:00:00Z", "event_id": "evt-2", "pause": 0}])
    monkeypatch.setattr(gcal, "delete_event", lambda *a: None)
    monkeypatch.setattr(
        gcal, "create_event",
        lambda s, c, d, st, en, k, m, pause=0: calls.append(("create", pause)) or "n")
    monkeypatch.setattr(
        gcal, "update_event",
        lambda s, c, e, d, st, en, k, m, pause=0: calls.append(("update", pause)))

    reservations_sync.reconcile_reservations(object(), "cal", store, settings)

    assert sorted(calls) == [("create", 30), ("update", 20)]


# --- Folgelauf und Erhalt (Fake-Kalender, speichert den Body) ---


class _FakeCalendar:
    """Minimaler Calendar-Service: speichert Event-Bodies, zählt update()."""

    def __init__(self, events=None):
        self.events_by_id = dict(events or {})
        self.updates = 0
        self._n = 0

    def events(self):
        return self

    def list(self, **kw):
        items = [dict(b, id=i) for i, b in self.events_by_id.items()]

        class _R:
            def execute(self_inner):
                return {"items": items}
        return _R()

    def insert(self, calendarId, body):
        self._n += 1
        eid = f"gen{self._n}"
        self.events_by_id[eid] = body
        return _Exec({"id": eid})

    def update(self, calendarId, eventId, body):
        self.updates += 1
        self.events_by_id[eventId] = body
        return _Exec({})

    def delete(self, calendarId, eventId):
        self.events_by_id.pop(eventId, None)
        return _Exec({})


class _Exec:
    def __init__(self, value):
        self._v = value

    def execute(self):
        return self._v


def _setup(tmp_path, pause, event_pause=None, local_mod="2026-06-02T10:00:00Z",
           event_mod="2026-05-20T10:00:00Z"):
    from src import gcal
    from src.reservations import ReservationStore
    from src.settings import Settings

    store = ReservationStore(str(tmp_path / "res.json"))
    store.save("2026-06-01", [{"start": "09:00", "end": "17:00", "kategorie": "",
                               "pause": pause, "gcal_event_id": "ev1"}])
    raw = store.get_all_raw()
    raw["2026-06-01"]["modified_at"] = local_mod
    store.apply_reconciled(raw)
    body = gcal.event_payload("2026-06-01", "09:00", "17:00", "", event_mod,
                              event_pause or 0)
    return store, Settings(str(tmp_path / "set.json")), _FakeCalendar({"ev1": body})


def test_second_run_after_update_is_quiet(tmp_path):
    from src import reservations_sync
    store, settings, cal = _setup(tmp_path, pause=30)
    reservations_sync.reconcile_reservations(cal, "c", store, settings)
    assert cal.updates == 1
    assert cal.events_by_id["ev1"]["extendedProperties"]["private"]["pause"] == "30"
    reservations_sync.reconcile_reservations(cal, "c", store, settings)
    assert cal.updates == 1


def test_pause_30_to_0_no_permanent_diff(tmp_path):
    from src import reservations_sync
    store, settings, cal = _setup(tmp_path, pause=0, event_pause=30)
    reservations_sync.reconcile_reservations(cal, "c", store, settings)
    assert cal.updates == 1
    assert "pause" not in cal.events_by_id["ev1"]["extendedProperties"]["private"]
    reservations_sync.reconcile_reservations(cal, "c", store, settings)
    assert cal.updates == 1


def test_local_wins_run_keeps_pause_in_store(tmp_path):
    from src import reservations_sync
    store, settings, cal = _setup(tmp_path, pause=30)
    reservations_sync.reconcile_reservations(cal, "c", store, settings)
    assert store.get_all_raw()["2026-06-01"]["slots"][0]["pause"] == 30


def test_remote_wins_run_without_property_adopts_pause_zero_no_pingpong(tmp_path):
    """Gerät B setzt Pause 30 -> 0 (Event neuer, ohne Property); Gerät A mit
    älterer lokaler Pause 30 übernimmt 0 und schreibt 30 nie zurück."""
    from src import reservations_sync
    store, settings, cal = _setup(tmp_path, pause=30, local_mod="2026-05-01T10:00:00Z",
                                  event_mod="2026-05-20T10:00:00Z")
    reservations_sync.reconcile_reservations(cal, "c", store, settings)
    assert store.get_all_raw()["2026-06-01"]["slots"][0]["pause"] == 0
    reservations_sync.reconcile_reservations(cal, "c", store, settings)
    assert cal.updates == 0
    assert "pause" not in cal.events_by_id["ev1"]["extendedProperties"]["private"]
