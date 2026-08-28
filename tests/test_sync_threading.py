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
    import src.sync_runtime as sync_runtime
    lock = threading.RLock()
    storage, settings, conflicts = _stores(tmp_path, lock)
    guard = threading.Lock()
    calls = []
    assert guard.acquire(blocking=False)
    try:
        sync_runtime.run_pull_in_background(
            storage, settings, conflicts, str(tmp_path),
            lambda **kw: calls.append(kw), data_lock=lock, sync_guard=guard)
    finally:
        guard.release()
    assert calls == []


def test_pull_holds_data_lock_during_apply_and_releases_guard(tmp_path, monkeypatch):
    """Während apply_merged_doc muss der Daten-Lock gehalten sein (kein
    UI-Save kann interleaven, H1); danach ist der Guard wieder frei."""
    import src.sync_runtime as sync_runtime
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
    sync_runtime.run_pull_in_background(
        storage, settings, conflicts, str(tmp_path),
        lambda **kw: calls.append(kw), data_lock=lock, sync_guard=guard)
    assert held == [True]                    # Apply lief unter dem Daten-Lock
    assert calls and calls[0]["ok"] is True
    assert guard.acquire(blocking=False)     # Guard wieder frei (finally)
    guard.release()


def test_pull_without_lock_and_guard_still_works(tmp_path, monkeypatch):
    """Alt-Aufrufer-Kompatibilität: ohne data_lock/sync_guard läuft der Pull
    wie bisher (bestehende Tests in test_sync.py decken die Semantik ab)."""
    import src.sync_runtime as sync_runtime
    lock = threading.RLock()
    storage, settings, conflicts = _stores(tmp_path, lock)
    _mock_drive_empty(monkeypatch)
    calls = []
    sync_runtime.run_pull_in_background(
        storage, settings, conflicts, str(tmp_path),
        lambda **kw: calls.append(kw))
    assert calls and calls[0]["ok"] is True


def test_push_skipped_when_guard_held(tmp_path):
    import src.sync_runtime as sync_runtime
    lock = threading.RLock()
    storage, settings, conflicts = _stores(tmp_path, lock)
    guard = threading.Lock()
    assert guard.acquire(blocking=False)
    try:
        res = sync_runtime.run_push_blocking(
            storage, settings, conflicts, str(tmp_path),
            data_lock=lock, sync_guard=guard)
    finally:
        guard.release()
    assert res == {"ok": False, "skipped": True}


def test_push_holds_data_lock_during_apply(tmp_path, monkeypatch):
    import src.sync_runtime as sync_runtime
    from src import sync
    lock = threading.RLock()
    storage, settings, conflicts = _stores(tmp_path, lock)
    _mock_drive_empty(monkeypatch)
    held = []
    orig = sync.apply_merged_doc

    def spy(merged, storage_, settings_, conflicts_):
        held.append(not _other_thread_can_acquire(lock))
        return orig(merged, storage_, settings_, conflicts_)

    monkeypatch.setattr(sync, "apply_merged_doc", spy)
    res = sync_runtime.run_push_blocking(
        storage, settings, conflicts, str(tmp_path),
        data_lock=lock, sync_guard=None)
    assert res.get("ok") is True
    assert held == [True]


def test_push_uploads_without_holding_data_lock(tmp_path, monkeypatch):
    """Spec-Invariante: der Daten-Lock wird NIE über den Netzwerk-Upload
    gehalten — während drive.upload muss er aus fremdem Thread nehmbar sein."""
    import src.sync_runtime as sync_runtime
    from src import drive
    lock = threading.RLock()
    storage, settings, conflicts = _stores(tmp_path, lock)
    monkeypatch.setattr(drive, "get_drive_service", lambda *a, **k: object())
    monkeypatch.setattr(drive, "find_sync_file", lambda service: None)
    lock_free = []

    def fake_upload(service, content, file_id=None, expected_etag=None):
        lock_free.append(_other_thread_can_acquire(lock))
        return ("file-1", "etag-1")

    monkeypatch.setattr(drive, "upload", fake_upload)
    res = sync_runtime.run_push_blocking(
        storage, settings, conflicts, str(tmp_path),
        data_lock=lock, sync_guard=None)
    assert res.get("ok") is True
    assert lock_free == [True]


def test_push_guard_released_after_run(tmp_path, monkeypatch):
    import src.sync_runtime as sync_runtime
    lock = threading.RLock()
    storage, settings, conflicts = _stores(tmp_path, lock)
    _mock_drive_empty(monkeypatch)
    guard = threading.Lock()
    res = sync_runtime.run_push_blocking(
        storage, settings, conflicts, str(tmp_path),
        data_lock=lock, sync_guard=guard)
    assert res.get("ok") is True
    assert guard.acquire(blocking=False)   # Guard nach dem Lauf wieder frei
    guard.release()


def test_push_guard_timeout_waits_for_running_sync(tmp_path, monkeypatch):
    """Quit-Semantik: guard_timeout>0 wartet auf den laufenden Sync statt zu
    skippen. Deterministischer Ausgang (großzügige Timeouts begrenzen nur die
    Dauer im Fehlerfall, sie werden nicht asserted)."""
    import src.sync_runtime as sync_runtime
    lock = threading.RLock()
    storage, settings, conflicts = _stores(tmp_path, lock)
    _mock_drive_empty(monkeypatch)
    guard = threading.Lock()
    guard.acquire()   # "laufender Sync"
    out = {}

    def run_push():
        out["res"] = sync_runtime.run_push_blocking(
            storage, settings, conflicts, str(tmp_path),
            timeout_seconds=30, data_lock=lock, sync_guard=guard,
            guard_timeout=30)

    t = threading.Thread(target=run_push)
    t.start()
    guard.release()   # der "laufende Sync" endet — der wartende Push übernimmt
    t.join()
    assert out["res"].get("ok") is True


def test_compaction_skipped_when_guard_held(tmp_path):
    import src.sync_runtime as sync_runtime
    lock = threading.RLock()
    storage, settings, conflicts = _stores(tmp_path, lock)
    guard = threading.Lock()
    assert guard.acquire(blocking=False)
    try:
        res = sync_runtime.run_compaction_blocking(
            storage, settings, conflicts, str(tmp_path),
            data_lock=lock, sync_guard=guard)
    finally:
        guard.release()
    assert res == {"ok": False, "skipped": True}


def test_compaction_holds_data_lock_during_compact(tmp_path, monkeypatch):
    import src.sync_runtime as sync_runtime
    from src import sync
    lock = threading.RLock()
    storage, settings, conflicts = _stores(tmp_path, lock)
    _mock_drive_empty(monkeypatch)
    held = []
    orig = sync.compact_local

    def spy(storage_, settings_, conflicts_, now):
        held.append(not _other_thread_can_acquire(lock))
        return orig(storage_, settings_, conflicts_, now)

    monkeypatch.setattr(sync, "compact_local", spy)
    res = sync_runtime.run_compaction_blocking(
        storage, settings, conflicts, str(tmp_path),
        data_lock=lock, sync_guard=None)
    assert res.get("ok") is True
    assert held == [True]


def test_resolve_conflict_holds_data_lock_during_save_all(tmp_path):
    """Whole-Branch-Review-Finding: resolve_conflict liest conflicts_store,
    mutiert die Liste und schreibt sie zurück (save_all) — diese RMW-Spanne
    muss unter dem geteilten Daten-Lock laufen, sonst kann ein Hintergrund-
    Sync (apply_merged_doc) dazwischen schreiben und die frisch gemergte
    Änderung verlieren."""
    from src import sync
    lock = threading.RLock()
    storage, settings, conflicts = _stores(tmp_path, lock)
    conflicts.save_all([{
        "id": "c1", "kind": "entry", "key": "2026-01-01",
        "candidates": [], "detected_at": "", "resolved": False,
        "resolution": None, "resolved_at": None, "resolved_by": None,
    }])
    held = []
    orig = conflicts.save_all

    def spy(all_conflicts):
        held.append(not _other_thread_can_acquire(lock))
        return orig(all_conflicts)

    conflicts.save_all = spy
    chosen = {"slots": [{"start": "08:00", "end": "16:00", "pause": 0, "kategorie": ""}]}
    sync.resolve_conflict("c1", chosen, conflicts, storage, settings,
                           device_id="A", data_lock=lock)
    assert held == [True]
    assert storage.get("2026-01-01") == {"slots": chosen["slots"]}
    assert conflicts.get_all()[0]["resolved"] is True


def test_reconcile_holds_data_lock_during_rebase_and_apply(tmp_path, monkeypatch):
    """Der Reconcile-Rebase+Replace (reservations_sync) läuft unter dem
    geteilten Daten-Lock — kein UI-Save kann zwischen Rebase-Read und
    apply_reconciled interleaven."""
    from src.reservations import ReservationStore
    from src import gcal
    from src.reservations_sync import reconcile_reservations
    lock = threading.RLock()
    store = ReservationStore(str(tmp_path / "r.json"), lock=lock)
    settings = Settings(str(tmp_path / "s.json"), lock=lock)
    monkeypatch.setattr(gcal, "list_app_events", lambda service, cal: [])
    held = []
    orig = store.apply_reconciled

    def spy(reconciled):
        held.append(not _other_thread_can_acquire(lock))
        return orig(reconciled)

    store.apply_reconciled = spy
    reconcile_reservations(object(), "cal-1", store, settings, data_lock=lock)
    assert held == [True]
