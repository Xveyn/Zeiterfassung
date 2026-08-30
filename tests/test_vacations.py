"""VacationStore: Persistenz, Tombstones, abgeleitete Tagessichten."""

import json

import pytest

from src.vacations import VacationStore


@pytest.fixture
def store(tmp_path):
    return VacationStore(str(tmp_path / "vacations.json"))


def _days(*pairs):
    return dict(pairs)


def test_load_empty(store):
    assert store.get_all() == {}
    assert store.day_minutes() == {}


def test_save_returns_period_id(store):
    pid = store.save(None, "Sommer", "2026-07-01", "2026-07-03",
                     _days(("2026-07-01", 480), ("2026-07-02", 480),
                           ("2026-07-03", 0)))
    assert isinstance(pid, str) and pid
    assert set(store.get_all()) == {pid}


def test_save_stores_all_fields(store):
    pid = store.save(None, "Sommer", "2026-07-01", "2026-07-02",
                     _days(("2026-07-01", 480), ("2026-07-02", 240)))
    period = store.get(pid)
    assert period["name"] == "Sommer"
    assert period["from"] == "2026-07-01"
    assert period["to"] == "2026-07-02"
    assert period["days"] == {"2026-07-01": 480, "2026-07-02": 240}
    assert period["gcal_event_id"] is None
    assert period["deleted"] is False
    assert period["modified_at"].endswith("Z") and "T" in period["modified_at"]


def test_save_with_existing_id_overwrites_and_keeps_event_id(store):
    pid = store.save(None, "Sommer", "2026-07-01", "2026-07-02",
                     _days(("2026-07-01", 480), ("2026-07-02", 480)))
    raw = store.get_all_raw()
    raw[pid]["gcal_event_id"] = "evt-1"
    store.apply_reconciled(raw)

    store.save(pid, "Sommerurlaub", "2026-07-01", "2026-07-03",
               _days(("2026-07-01", 480), ("2026-07-02", 480),
                     ("2026-07-03", 480)))
    period = store.get(pid)
    assert period["name"] == "Sommerurlaub"
    assert period["to"] == "2026-07-03"
    # Die Event-Bindung überlebt das Bearbeiten — sonst legte der nächste
    # Reconcile ein zweites Event an, statt das vorhandene zu verschieben.
    assert period["gcal_event_id"] == "evt-1"


def test_delete_without_calendar_event_removes_the_record(store):
    """Ohne gcal_event_id gibt es draußen nichts aufzuräumen — ein Tombstone
    wäre auf einem Rechner ohne Google unsterblich."""
    pid = store.save(None, "Sommer", "2026-07-01", "2026-07-02",
                     _days(("2026-07-01", 480), ("2026-07-02", 480)))
    store.delete(pid)
    assert store.get(pid) is None
    assert store.get_all() == {}
    assert store.get_all_raw() == {}


def test_delete_with_calendar_event_writes_tombstone(store):
    """Mit Event bleibt der Tombstone, bis reconcile_vacations ihn einlöst."""
    pid = store.save(None, "Sommer", "2026-07-01", "2026-07-02",
                     _days(("2026-07-01", 480), ("2026-07-02", 480)))
    raw = store.get_all_raw()
    raw[pid]["gcal_event_id"] = "evt-1"
    store.apply_reconciled(raw)

    store.delete(pid)
    assert store.get(pid) is None
    assert store.get_all() == {}
    tomb = store.get_all_raw()[pid]
    assert tomb["deleted"] is True
    assert tomb["days"] == {}
    assert tomb["gcal_event_id"] == "evt-1"


def test_delete_unknown_id_is_noop(store):
    store.delete("gibtsnicht")
    assert store.get_all_raw() == {}


def test_day_minutes_flattens_across_periods(store):
    store.save(None, "A", "2026-07-01", "2026-07-02",
               _days(("2026-07-01", 480), ("2026-07-02", 0)))
    store.save(None, "B", "2026-08-03", "2026-08-03", _days(("2026-08-03", 240)))
    assert store.day_minutes() == {
        "2026-07-01": 480, "2026-07-02": 0, "2026-08-03": 240,
    }


def test_day_minutes_excludes_tombstones(store):
    pid = store.save(None, "A", "2026-07-01", "2026-07-01",
                     _days(("2026-07-01", 480)))
    store.delete(pid)
    assert store.day_minutes() == {}


def test_period_for_date_finds_the_period(store):
    pid = store.save(None, "Sommer", "2026-07-01", "2026-07-03",
                     _days(("2026-07-01", 480), ("2026-07-02", 480),
                           ("2026-07-03", 480)))
    assert store.period_for_date("2026-07-02")["name"] == "Sommer"
    assert store.period_for_date("2026-07-02")["id"] == pid
    assert store.period_for_date("2026-07-04") is None


def test_period_for_date_ignores_tombstones(store):
    pid = store.save(None, "Sommer", "2026-07-01", "2026-07-01",
                     _days(("2026-07-01", 480)))
    store.delete(pid)
    assert store.period_for_date("2026-07-01") is None


def test_save_rejects_overlapping_period(store):
    store.save(None, "Sommer", "2026-07-01", "2026-07-14",
               _days(("2026-07-01", 480)))
    with pytest.raises(ValueError, match="Sommer"):
        store.save(None, "Zweiter", "2026-07-10", "2026-07-20",
                   _days(("2026-07-10", 480)))


def test_save_allows_editing_the_same_period(store):
    pid = store.save(None, "Sommer", "2026-07-01", "2026-07-14",
                     _days(("2026-07-01", 480)))
    store.save(pid, "Sommer", "2026-07-05", "2026-07-20",
               _days(("2026-07-05", 480)))
    assert store.get(pid)["from"] == "2026-07-05"


def test_save_editing_keeps_the_same_id(store):
    """Beim Bearbeiten darf keine neue ID gewürfelt werden — sonst risse der
    Bezug zum Kalender-Event ab."""
    pid = store.save(None, "Sommer", "2026-07-01", "2026-07-02",
                     _days(("2026-07-01", 480)))
    same = store.save(pid, "Sommer neu", "2026-07-01", "2026-07-02",
                      _days(("2026-07-01", 240)))
    assert same == pid
    assert list(store.get_all()) == [pid]


def test_save_rejects_reversed_range(store):
    with pytest.raises(ValueError, match="Bis-Datum"):
        store.save(None, "Verdreht", "2026-07-10", "2026-07-01",
                   _days(("2026-07-10", 480)))


def test_overlap_error_names_the_way_out(store):
    """Die Meldung soll den Ausweg nennen — Anhängen an eine bestehende
    Periode ist durch das Überschneidungsverbot sonst eine Sackgasse."""
    store.save(None, "Sommer", "2026-07-01", "2026-07-14",
               _days(("2026-07-01", 480)))
    with pytest.raises(ValueError, match="Bearbeite stattdessen"):
        store.save(None, "Anschluss", "2026-07-14", "2026-07-20",
                   _days(("2026-07-14", 480)))


def _period_via(store, reader, pid, date_str):
    """Holt denselben Record über einen der vier Leser — für die
    parametrisierte Isolations-Prüfung unten."""
    if reader == "get":
        return store.get(pid)
    if reader == "get_all":
        return store.get_all()[pid]
    if reader == "get_all_raw":
        return store.get_all_raw()[pid]
    if reader == "period_for_date":
        return store.period_for_date(date_str)
    raise ValueError(reader)


@pytest.mark.parametrize(
    "reader", ["get", "get_all", "get_all_raw", "period_for_date"])
def test_returned_records_do_not_share_the_days_dict(store, reader):
    """Der Dialog bearbeitet `days` des zurückgegebenen Records — das darf
    bei KEINEM der vier Leser am Store vorbei in den Speicher schreiben.
    Ein künftig vergessenes `_copy` in einem der vier fliegt hier auf."""
    pid = store.save(None, "Sommer", "2026-07-01", "2026-07-01",
                     _days(("2026-07-01", 480)))
    period = _period_via(store, reader, pid, "2026-07-01")
    period["days"]["2026-07-01"] = 0
    assert store.get(pid)["days"]["2026-07-01"] == 480
    assert store.day_minutes()["2026-07-01"] == 480


def test_persists_across_instances(tmp_path):
    path = str(tmp_path / "vacations.json")
    first = VacationStore(path)
    pid = first.save(None, "Sommer", "2026-07-01", "2026-07-01",
                     _days(("2026-07-01", 480)))
    second = VacationStore(path)
    assert second.get(pid)["name"] == "Sommer"


def test_corrupt_file_is_quarantined(tmp_path):
    path = tmp_path / "vacations.json"
    path.write_text("{kaputt", encoding="utf-8")
    store = VacationStore(str(path))
    assert store.get_all() == {}
    assert list(tmp_path.glob("vacations.json.corrupt-*"))


def test_written_file_is_valid_json(tmp_path):
    path = tmp_path / "vacations.json"
    store = VacationStore(str(path))
    store.save(None, "Sommer", "2026-07-01", "2026-07-01",
               _days(("2026-07-01", 480)))
    data = json.loads(path.read_text(encoding="utf-8"))
    assert len(data) == 1


def test_apply_reconciled_rejects_incomplete_entry(store):
    with pytest.raises(ValueError, match="missing keys"):
        store.apply_reconciled({"a": {"name": "Sommer"}})
