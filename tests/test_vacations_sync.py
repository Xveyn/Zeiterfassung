"""Urlaubs-Push: Plan-Logik, Ausführung und Aufräumen (Tk- und Google-frei)."""

import threading

import pytest

from src import gcal
from src.gcal import vacation_event_payload
from src.vacations import VacationStore
from src.vacations_sync import (
    plan_vacation_sync, purge_vacation_events, reconcile_vacations,
)
from tests.conftest import other_thread_can_acquire


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


# ------------------------------------------------------ purge_vacation_events

def _seeded_store(tmp_path, records):
    store = VacationStore(str(tmp_path / "vacations.json"))
    store.apply_reconciled(records)
    return store


def _fake_gcal(monkeypatch, remote_events, deleted):
    monkeypatch.setattr(gcal, "list_app_vacations",
                        lambda service, calendar_id: list(remote_events))
    monkeypatch.setattr(gcal, "delete_event",
                        lambda service, calendar_id, event_id:
                        deleted.append(event_id))


def test_purge_deletes_every_app_event(monkeypatch, tmp_path):
    store = _seeded_store(tmp_path, {"a": _period(event_id="evt-1")})
    deleted = []
    _fake_gcal(monkeypatch, [_remote("a")], deleted)

    purge_vacation_events(object(), "cal", store)

    assert deleted == ["evt-1"]


def test_purge_clears_the_local_event_ids(monkeypatch, tmp_path):
    """Ohne das Leeren legte ein spaeteres Wiedereinschalten kein Event mehr
    an: plan_vacation_sync haelt eine Periode mit gcal_event_id fuer bereits
    gepusht und findet remote nichts, was sie aktualisieren koennte."""
    store = _seeded_store(tmp_path, {"a": _period(event_id="evt-1")})
    _fake_gcal(monkeypatch, [_remote("a")], [])

    purge_vacation_events(object(), "cal", store)

    assert store.get_all_raw()["a"]["gcal_event_id"] is None


def test_purge_drops_tombstones_whose_event_is_gone(monkeypatch, tmp_path):
    store = _seeded_store(tmp_path, {
        "lebend": _period(event_id="evt-1"),
        "grabstein": _period(event_id="evt-2", deleted=True),
    })
    _fake_gcal(monkeypatch, [_remote("lebend"), _remote("grabstein", "evt-2")], [])

    purge_vacation_events(object(), "cal", store)

    assert list(store.get_all_raw()) == ["lebend"]


def test_purge_without_remote_events_leaves_the_store_alone(monkeypatch, tmp_path):
    store = _seeded_store(tmp_path, {"a": _period()})
    deleted = []
    _fake_gcal(monkeypatch, [], deleted)

    purge_vacation_events(object(), "cal", store)

    assert deleted == []
    assert store.get_all_raw()["a"]["gcal_event_id"] is None


# -------------------------------------------------------- reconcile_vacations
#
# Der Plan ist oben getestet; hier geht es um die Ausführung: welche Calls mit
# welchen Argumenten rausgehen und was davon im Store (auf Platte) ankommt.

def _reloaded(tmp_path):
    """Frisch von Platte gelesen — prüft, was persistiert wurde, nicht nur,
    was im Speicher des getesteten Store-Objekts steht."""
    return VacationStore(str(tmp_path / "vacations.json")).get_all_raw()


def test_reconcile_persists_the_id_of_a_created_event(fake_calendar, tmp_path):
    """Ohne das Zurückschreiben legte jeder weitere Abgleich ein neues Event
    zur selben Periode an."""
    store = _seeded_store(tmp_path, {"a": _period()})

    reconcile_vacations(fake_calendar.service, "cal-1", store)

    assert fake_calendar.created_vacations == [
        ("a", "2026-07-01", "2026-07-03", "2026-08-30T10:00:00Z")]
    assert _reloaded(tmp_path)["a"]["gcal_event_id"] == "evt-new-1"


def test_reconcile_updates_the_event_of_an_edited_period(fake_calendar, tmp_path):
    store = _seeded_store(tmp_path, {"a": _period(
        event_id="evt-1", date_to="2026-07-10", modified_at="2026-08-30T12:00:00Z")})
    fake_calendar.vacation_events = [_remote("a")]

    reconcile_vacations(fake_calendar.service, "cal-1", store)

    assert fake_calendar.updated_vacations == [
        ("evt-1", "a", "2026-07-01", "2026-07-10", "2026-08-30T12:00:00Z")]
    assert fake_calendar.created_vacations == []


def test_reconcile_drops_a_tombstone_once_its_event_is_deleted(fake_calendar, tmp_path):
    """Der Tombstone hat genau einen Zweck — das Event abräumen. Danach muss
    er weg, sonst wüchse vacations.json mit jedem gelöschten Urlaub."""
    store = _seeded_store(tmp_path, {
        "lebend": _period(event_id="evt-1"),
        "grabstein": _period(event_id="evt-2", deleted=True),
    })
    fake_calendar.vacation_events = [_remote("lebend"),
                                     _remote("grabstein", event_id="evt-2")]

    reconcile_vacations(fake_calendar.service, "cal-1", store)

    assert fake_calendar.deleted == ["evt-2"]
    assert list(_reloaded(tmp_path)) == ["lebend"]


def test_reconcile_without_changes_does_not_rewrite_the_store(fake_calendar, tmp_path):
    """Der Abgleich läuft bei jedem Start und jeder Reservierungsänderung.
    Ist nichts zurückzuschreiben, darf er die Datei nicht anfassen — sichtbar
    daran, dass eine gelöschte Datei nicht wieder entsteht."""
    store = _seeded_store(tmp_path, {"a": _period(event_id="evt-1")})
    fake_calendar.vacation_events = [_remote("a")]
    (tmp_path / "vacations.json").unlink()

    reconcile_vacations(fake_calendar.service, "cal-1", store)

    assert not (tmp_path / "vacations.json").exists()


def test_reconcile_does_not_resurrect_a_period_deleted_during_the_push(
        fake_calendar, tmp_path):
    """Die Netz-Calls laufen ohne Lock, der Nutzer kann derweil löschen. Das
    Zurückschreiben muss den Store neu lesen — schriebe es den Snapshot vom
    Anfang zurück, käme der gelöschte Urlaub wieder."""
    store = _seeded_store(tmp_path, {"a": _period()})
    fake_calendar.hooks["create_vacation_event"] = lambda: store.delete("a")

    reconcile_vacations(fake_calendar.service, "cal-1", store)

    assert "a" not in store.get_all_raw()
    assert "a" not in _reloaded(tmp_path)


def test_reconcile_api_failure_propagates_and_leaves_the_store_untouched(
        fake_calendar, tmp_path):
    """Der lokale Store ist die Quelle, Google die Kopie: scheitert ein Call,
    bleibt der Store wie er war, und der Aufrufer erfährt davon."""
    store = _seeded_store(tmp_path, {"a": _period()})
    before = _reloaded(tmp_path)
    fake_calendar.raise_on("create_vacation_event", RuntimeError("quota exceeded"))

    with pytest.raises(RuntimeError, match="quota exceeded"):
        reconcile_vacations(fake_calendar.service, "cal-1", store)

    assert _reloaded(tmp_path) == before


def test_reconcile_holds_the_data_lock_only_while_writing_back(fake_calendar, tmp_path):
    """Audit H1: das Zurückschreiben klammert gegen parallele UI-Saves — die
    Netz-Calls davor dürfen den Lock nicht halten, sonst friert jeder Save
    für die Dauer eines Google-Roundtrips ein."""
    lock = threading.RLock()
    store = VacationStore(str(tmp_path / "vacations.json"), lock=lock)
    store.apply_reconciled({"a": _period()})
    free_during_network = []
    held_during_write = []
    fake_calendar.hooks["create_vacation_event"] = (
        lambda: free_during_network.append(other_thread_can_acquire(lock)))
    original_apply = store.apply_reconciled

    def spy_apply(reconciled):
        held_during_write.append(not other_thread_can_acquire(lock))
        original_apply(reconciled)

    store.apply_reconciled = spy_apply

    reconcile_vacations(fake_calendar.service, "cal-1", store, data_lock=lock)

    assert free_during_network == [True]
    assert held_during_write == [True]
