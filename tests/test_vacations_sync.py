"""Plan-Logik des Urlaubs-Push (Tk- und Google-frei)."""

from src.gcal import vacation_event_payload
from src.vacations_sync import plan_vacation_sync


def _period(name="Sommer", date_from="2026-07-01", date_to="2026-07-03",
            event_id=None, deleted=False, modified_at="2026-08-30T10:00:00Z"):
    return {"name": name, "from": date_from, "to": date_to,
            "days": {} if deleted else {date_from: 480},
            "gcal_event_id": event_id, "modified_at": modified_at,
            "deleted": deleted}


def _remote(period_id, event_id="evt-1", modified_at="2026-08-30T10:00:00Z",
            date_from="2026-07-01", date_to="2026-07-03"):
    return {"period_id": period_id, "event_id": event_id,
            "modified_at": modified_at, "from": date_from, "to": date_to}


def test_plan_creates_event_for_new_period():
    plan = plan_vacation_sync({"a": _period()}, [])
    assert plan["create"] == [("a", "2026-07-01", "2026-07-03",
                              "2026-08-30T10:00:00Z")]
    assert plan["update"] == []
    assert plan["delete"] == []


def test_plan_is_idempotent_when_nothing_changed():
    local = {"a": _period(event_id="evt-1")}
    plan = plan_vacation_sync(local, [_remote("a")])
    assert plan["create"] == []
    assert plan["update"] == []
    assert plan["delete"] == []


def test_plan_updates_when_local_is_newer():
    local = {"a": _period(event_id="evt-1", date_to="2026-07-10",
                          modified_at="2026-08-30T12:00:00Z")}
    plan = plan_vacation_sync(local, [_remote("a")])
    assert plan["update"] == [("evt-1", "a", "2026-07-01", "2026-07-10",
                               "2026-08-30T12:00:00Z")]


def test_plan_deletes_event_of_tombstoned_period():
    local = {"a": _period(event_id="evt-1", deleted=True)}
    plan = plan_vacation_sync(local, [_remote("a")])
    assert plan["delete"] == ["evt-1"]


def test_plan_deletes_orphan_remote_event():
    plan = plan_vacation_sync({}, [_remote("verwaist", event_id="evt-9")])
    assert plan["delete"] == ["evt-9"]


def test_plan_deletes_duplicate_events_of_one_period():
    """Ein Abbruch zwischen zwei create-Calls hinterlässt zwei Events zur
    selben Periode. Beide zu behalten hieße, das überzählige nie wieder zu
    sehen — es muss weg."""
    local = {"a": _period(event_id="evt-1")}
    plan = plan_vacation_sync(local, [_remote("a", event_id="evt-1"),
                                      _remote("a", event_id="evt-2")])
    assert plan["delete"] == ["evt-2"]
    assert plan["create"] == []


def test_plan_deletes_all_but_one_event_without_period_id():
    """parse_vacation_event liefert für ein Event ohne period_id "" — mehrere
    davon dürfen nicht aufeinander abgebildet werden."""
    plan = plan_vacation_sync({}, [_remote("", event_id="evt-8"),
                                   _remote("", event_id="evt-9")])
    assert sorted(plan["delete"]) == ["evt-8", "evt-9"]


def test_plan_updates_when_event_was_moved_in_google():
    """Google fasst die private modified_at beim Verschieben nicht an — ein
    reiner Zeitstempel-Vergleich sähe den Unterschied nie."""
    local = {"a": _period(event_id="evt-1", date_from="2026-07-01",
                          date_to="2026-07-03")}
    verschoben = _remote("a", date_from="2026-08-01", date_to="2026-08-03")
    plan = plan_vacation_sync(local, [verschoben])
    assert plan["update"] == [("evt-1", "a", "2026-07-01", "2026-07-03",
                               "2026-08-30T10:00:00Z")]


def test_plan_updates_on_second_edit_within_the_same_second():
    """utc_now_iso hat Sekundenauflösung: zwei Bearbeitungen in derselben
    Sekunde ergäben `T > T` = False und fielen ohne Zeitraum-Vergleich
    stillschweigend unter den Tisch."""
    local = {"a": _period(event_id="evt-1", date_to="2026-07-10",
                          modified_at="2026-08-30T10:00:00Z")}
    plan = plan_vacation_sync(local, [_remote("a")])
    assert len(plan["update"]) == 1


def test_payload_end_date_is_exclusive():
    body = vacation_event_payload("a", "2026-07-01", "2026-07-03",
                                  "2026-08-30T10:00:00Z")
    assert body["start"] == {"date": "2026-07-01"}
    # Die Calendar-API behandelt end.date exklusiv — ein Urlaub bis zum 03.
    # endet im Event am 04., sonst fehlte der letzte Tag.
    assert body["end"] == {"date": "2026-07-04"}


def test_payload_uses_the_vacation_marker():
    body = vacation_event_payload("a", "2026-07-01", "2026-07-03",
                                  "2026-08-30T10:00:00Z")
    private = body["extendedProperties"]["private"]
    assert private["zeiterfassung"] == "vacation"
    assert private["period_id"] == "a"


def test_payload_does_not_carry_the_local_name():
    body = vacation_event_payload("a", "2026-07-01", "2026-07-03",
                                  "2026-08-30T10:00:00Z")
    assert body["summary"] == "Urlaub"
