import logging

import pytest

from src.conflicts_store import ConflictsStore


@pytest.fixture
def tmp_conflicts(tmp_path):
    return ConflictsStore(str(tmp_path / "conflicts.json"))


def test_empty_on_first_load(tmp_conflicts):
    assert tmp_conflicts.get_all() == []


def test_save_and_persist(tmp_path):
    path = str(tmp_path / "conflicts.json")
    s1 = ConflictsStore(path)
    s1.save_all([{"id": "c-1", "kind": "entry", "key": "2026-05-14",
                  "resolved": False}])
    s2 = ConflictsStore(path)
    assert s2.get_all() == [{"id": "c-1", "kind": "entry", "key": "2026-05-14",
                              "resolved": False}]


def test_corrupt_file_is_quarantined(tmp_path, caplog):
    path = tmp_path / "conflicts.json"
    path.write_text("not json{{{", encoding="utf-8")
    with caplog.at_level(logging.WARNING):
        store = ConflictsStore(str(path))
    assert store.get_all() == []
    quarantined = list(tmp_path.glob("conflicts.json.corrupt-*"))
    assert len(quarantined) == 1
    # N4: Quarantäne wird jetzt geloggt, nicht mehr stumm.
    assert any("Quarantäne" in r.message for r in caplog.records)


def test_count_unresolved(tmp_conflicts):
    tmp_conflicts.save_all([
        {"id": "c-1", "resolved": False},
        {"id": "c-2", "resolved": True},
        {"id": "c-3", "resolved": False},
    ])
    assert tmp_conflicts.count_unresolved() == 2
