"""Threading-Verhalten der Sync-Flows: Sync-Guard (Re-Entrancy, Audit H2) und
Daten-Lock-Klammer um Snapshot→Merge→Apply (Audit H1). Deterministisch über
Probe-Threads — kein Sleep, keine Timing-Asserts."""

import threading

from src.conflicts_store import ConflictsStore
from src.settings import Settings
from src.storage import Storage


def _other_thread_can_acquire(lock):
    """True, wenn ein ANDERER Thread den Lock nehmen kann (= Lock frei)."""
    out = []

    def probe():
        got = lock.acquire(blocking=False)
        out.append(got)
        if got:
            lock.release()

    t = threading.Thread(target=probe)
    t.start()
    t.join()
    return out[0]


def _stores(tmp_path, lock):
    storage = Storage(str(tmp_path / "z.json"), device_id="A", lock=lock)
    settings = Settings(str(tmp_path / "s.json"), lock=lock)
    settings.device_id_for_sync = "A"
    conflicts = ConflictsStore(str(tmp_path / "c.json"), lock=lock)
    return storage, settings, conflicts


def _mock_drive_empty(monkeypatch):
    """Drive-Fassade: kein Remote-File (Pfad ohne Download), Upload gemockt."""
    from src import drive
    monkeypatch.setattr(drive, "get_drive_service", lambda *a, **k: object())
    monkeypatch.setattr(drive, "find_sync_file", lambda service: None)
    monkeypatch.setattr(
        drive, "upload",
        lambda service, content, file_id=None, expected_etag=None: ("file-1", "etag-1"))
    return drive


def test_pull_skipped_when_guard_held(tmp_path):
    """Läuft bereits ein Sync (Guard gehalten), wird der Pull still
    übersprungen: kein ui_callback, kein Drive-Zugriff."""
    import src.main as main
    lock = threading.RLock()
    storage, settings, conflicts = _stores(tmp_path, lock)
    guard = threading.Lock()
    calls = []
    assert guard.acquire(blocking=False)
    try:
        main._run_pull_in_background(
            storage, settings, conflicts, str(tmp_path),
            lambda **kw: calls.append(kw), data_lock=lock, sync_guard=guard)
    finally:
        guard.release()
    assert calls == []


def test_pull_holds_data_lock_during_apply_and_releases_guard(tmp_path, monkeypatch):
    """Während apply_merged_doc muss der Daten-Lock gehalten sein (kein
    UI-Save kann interleaven, H1); danach ist der Guard wieder frei."""
    import src.main as main
    from src import sync
    lock = threading.RLock()
    storage, settings, conflicts = _stores(tmp_path, lock)
    guard = threading.Lock()
    _mock_drive_empty(monkeypatch)
    held = []
    orig = sync.apply_merged_doc

    def spy(merged, storage_, settings_, conflicts_):
        held.append(not _other_thread_can_acquire(lock))
        return orig(merged, storage_, settings_, conflicts_)

    monkeypatch.setattr(sync, "apply_merged_doc", spy)
    calls = []
    main._run_pull_in_background(
        storage, settings, conflicts, str(tmp_path),
        lambda **kw: calls.append(kw), data_lock=lock, sync_guard=guard)
    assert held == [True]                    # Apply lief unter dem Daten-Lock
    assert calls and calls[0]["ok"] is True
    assert guard.acquire(blocking=False)     # Guard wieder frei (finally)
    guard.release()


def test_pull_without_lock_and_guard_still_works(tmp_path, monkeypatch):
    """Alt-Aufrufer-Kompatibilität: ohne data_lock/sync_guard läuft der Pull
    wie bisher (bestehende Tests in test_sync.py decken die Semantik ab)."""
    import src.main as main
    lock = threading.RLock()
    storage, settings, conflicts = _stores(tmp_path, lock)
    _mock_drive_empty(monkeypatch)
    calls = []
    main._run_pull_in_background(
        storage, settings, conflicts, str(tmp_path),
        lambda **kw: calls.append(kw))
    assert calls and calls[0]["ok"] is True
