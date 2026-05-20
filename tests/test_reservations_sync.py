from src.reservations_sync import merge_reservations


def _local(start="09:00", end="17:00", modified_at="2026-05-20T10:00:00Z",
           deleted=False, event_id=None):
    return {"start": start, "end": end, "modified_at": modified_at,
            "deleted": deleted, "gcal_event_id": event_id}


def _remote(date="2026-06-01", start="09:00", end="17:00",
            modified_at="2026-05-20T10:00:00Z", event_id="ev1"):
    return {"date": date, "start": start, "end": end,
            "modified_at": modified_at, "event_id": event_id}


def test_local_only_new_creates_event():
    res = merge_reservations(
        {"2026-06-01": _local(modified_at="2026-05-20T10:00:00Z")},
        [], "2026-05-19T00:00:00Z")
    assert res["plan"]["create"] == [{
        "date": "2026-06-01", "start": "09:00", "end": "17:00",
        "modified_at": "2026-05-20T10:00:00Z"}]
    assert "2026-06-01" in res["merged"]


def test_local_only_stale_is_dropped():
    res = merge_reservations(
        {"2026-06-01": _local(modified_at="2026-05-10T10:00:00Z")},
        [], "2026-05-19T00:00:00Z")
    assert res["merged"] == {}
    assert res["plan"]["create"] == []


def test_remote_only_is_imported():
    res = merge_reservations({}, [_remote()], "2026-05-19T00:00:00Z")
    assert res["merged"]["2026-06-01"]["start"] == "09:00"
    assert res["merged"]["2026-06-01"]["gcal_event_id"] == "ev1"
    assert res["plan"] == {"create": [], "update": [], "delete": []}


def test_both_newer_local_wins_and_updates():
    res = merge_reservations(
        {"2026-06-01": _local(start="08:00", modified_at="2026-05-21T10:00:00Z")},
        [_remote(start="09:00", modified_at="2026-05-20T10:00:00Z")],
        "2026-05-19T00:00:00Z")
    assert res["merged"]["2026-06-01"]["start"] == "08:00"
    assert res["merged"]["2026-06-01"]["gcal_event_id"] == "ev1"
    assert res["plan"]["update"] == [{
        "date": "2026-06-01", "event_id": "ev1", "start": "08:00",
        "end": "17:00", "modified_at": "2026-05-21T10:00:00Z"}]


def test_both_newer_remote_wins():
    res = merge_reservations(
        {"2026-06-01": _local(start="08:00", modified_at="2026-05-20T10:00:00Z")},
        [_remote(start="09:00", modified_at="2026-05-21T10:00:00Z")],
        "2026-05-19T00:00:00Z")
    assert res["merged"]["2026-06-01"]["start"] == "09:00"
    assert res["plan"]["update"] == []


def test_both_equal_values_no_update():
    res = merge_reservations(
        {"2026-06-01": _local(modified_at="2026-05-21T10:00:00Z")},
        [_remote(modified_at="2026-05-20T10:00:00Z")],
        "2026-05-19T00:00:00Z")
    assert res["plan"]["update"] == []
    assert res["merged"]["2026-06-01"]["gcal_event_id"] == "ev1"


def test_tombstone_newer_deletes_event():
    res = merge_reservations(
        {"2026-06-01": _local(deleted=True, modified_at="2026-05-21T10:00:00Z",
                              event_id="ev1")},
        [_remote(modified_at="2026-05-20T10:00:00Z")],
        "2026-05-19T00:00:00Z")
    assert res["plan"]["delete"] == [{"event_id": "ev1"}]
    assert "2026-06-01" not in res["merged"]


def test_tombstone_older_than_remote_update_is_dropped():
    res = merge_reservations(
        {"2026-06-01": _local(deleted=True, modified_at="2026-05-20T10:00:00Z")},
        [_remote(modified_at="2026-05-21T10:00:00Z")],
        "2026-05-19T00:00:00Z")
    assert res["plan"]["delete"] == []
    assert res["merged"]["2026-06-01"]["start"] == "09:00"


def test_tombstone_without_remote_is_noop():
    res = merge_reservations(
        {"2026-06-01": _local(deleted=True, modified_at="2026-05-21T10:00:00Z")},
        [], "2026-05-19T00:00:00Z")
    assert res["merged"] == {}
    assert res["plan"] == {"create": [], "update": [], "delete": []}


def test_duplicate_remote_events_keeps_newest_deletes_rest():
    res = merge_reservations(
        {},
        [_remote(modified_at="2026-05-20T10:00:00Z", event_id="old"),
         _remote(modified_at="2026-05-21T10:00:00Z", event_id="new")],
        "2026-05-19T00:00:00Z")
    assert res["merged"]["2026-06-01"]["gcal_event_id"] == "new"
    assert res["plan"]["delete"] == [{"event_id": "old"}]


def test_local_only_exactly_at_watermark_is_dropped():
    res = merge_reservations(
        {"2026-06-01": _local(modified_at="2026-05-19T00:00:00Z")},
        [], "2026-05-19T00:00:00Z")
    assert res["merged"] == {}
    assert res["plan"]["create"] == []
