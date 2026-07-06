import json
import os

import pytest

from src import sync_journal
from src.conflicts_store import ConflictsStore
from src.settings import Settings
from src.storage import Storage


def _stores(tmp_path):
    storage = Storage(str(tmp_path / "zeiterfassung.json"), device_id="A")
    settings = Settings(str(tmp_path / "settings.json"))
    conflicts = ConflictsStore(str(tmp_path / "conflicts.json"))
    return storage, settings, conflicts


def _merged_doc():
    return {
        "schema_version": 4,
        "entries": {
            "2026-05-14": {
                "slots": [{"start": "08:00", "end": "16:00", "pause": 30, "kategorie": ""}],
                "modified_at": "2026-05-14T10:00:00Z", "device_id": "A", "deleted": False,
            }
        },
        "settings": {
            "recipient": {"value": "a@b.de", "modified_at": "2026-05-14T10:00:00Z",
                          "device_id": "A"},
        },
        "conflicts": [{"id": "c1", "kind": "entry", "key": "2026-05-14",
                       "candidates": [], "resolved": True, "resolution": None,
                       "resolved_at": "2026-05-14T10:00:00Z", "resolved_by": "A"}],
        "meta": {"gc_watermark": "2026-05-10T00:00:00Z"},
    }


def test_journaled_apply_writes_all_stores_and_removes_journal(tmp_path):
    storage, settings, conflicts = _stores(tmp_path)
    journal = str(tmp_path / sync_journal.JOURNAL_FILENAME)

    sync_journal.apply_merged_doc_journaled(_merged_doc(), storage, settings, conflicts, journal)

    assert not os.path.exists(journal)          # Journal nach Erfolg gelöscht
    assert "2026-05-14" in storage.get_all_raw()
    assert settings.get("recipient") == "a@b.de"
    assert settings.get("gc_watermark") == "2026-05-10T00:00:00Z"
    assert conflicts.get_all() == _merged_doc()["conflicts"]


def test_recover_is_noop_without_journal(tmp_path):
    storage, settings, conflicts = _stores(tmp_path)
    journal = str(tmp_path / sync_journal.JOURNAL_FILENAME)
    assert sync_journal.recover_pending_apply(journal, storage, settings, conflicts) is False


def test_recover_applies_leftover_journal(tmp_path):
    storage, settings, conflicts = _stores(tmp_path)
    journal = tmp_path / sync_journal.JOURNAL_FILENAME
    journal.write_text(json.dumps(_merged_doc()), encoding="utf-8")

    recovered = sync_journal.recover_pending_apply(str(journal), storage, settings, conflicts)

    assert recovered is True
    assert "2026-05-14" in storage.get_all_raw()
    assert settings.get("gc_watermark") == "2026-05-10T00:00:00Z"
    assert not journal.exists()               # Journal nach Recovery gelöscht


def test_crash_during_apply_leaves_journal_then_recovers(tmp_path, monkeypatch):
    # Crash mitten in apply_merged_doc: der dritte Write (conflicts) wirft.
    storage, settings, conflicts = _stores(tmp_path)
    journal = str(tmp_path / sync_journal.JOURNAL_FILENAME)

    def boom(*_a, **_k):
        raise RuntimeError("simulierter Crash vor dem letzten Write")
    monkeypatch.setattr(conflicts, "save_all", boom)

    with pytest.raises(RuntimeError):
        sync_journal.apply_merged_doc_journaled(_merged_doc(), storage, settings, conflicts, journal)

    assert os.path.exists(journal)                 # Journal überlebt den Crash
    assert settings.get("gc_watermark") == ""      # Write 4 kam nicht mehr dran (inkonsistent)

    # „Neustart": frische Stores lesen den partiellen Disk-Stand, Recovery holt nach.
    storage2, settings2, conflicts2 = _stores(tmp_path)
    assert settings2.get("gc_watermark") == ""     # partieller Stand auf Platte
    recovered = sync_journal.recover_pending_apply(journal, storage2, settings2, conflicts2)

    assert recovered is True
    assert settings2.get("gc_watermark") == "2026-05-10T00:00:00Z"  # jetzt konsistent
    assert conflicts2.get_all() == _merged_doc()["conflicts"]
    assert not os.path.exists(journal)


def test_recover_discards_unreadable_journal(tmp_path):
    storage, settings, conflicts = _stores(tmp_path)
    journal = tmp_path / sync_journal.JOURNAL_FILENAME
    journal.write_text("not json{{{", encoding="utf-8")

    recovered = sync_journal.recover_pending_apply(str(journal), storage, settings, conflicts)

    assert recovered is False
    assert not journal.exists()               # kaputtes Journal verworfen
