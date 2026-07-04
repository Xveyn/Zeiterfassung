"""Threadsicherheit der vier Stores: geteilter injizierter RLock (Audit H1/H2).

Kein Sleep/Timing — Lock-Besitz wird über einen Probe-Thread geprüft
(non-blocking acquire aus fremdem Thread), Robustheit über einen Stresstest,
dessen Erfolgskriterium "keine Exception + valides JSON" ist.
"""

import json
import threading

from src.conflicts_store import ConflictsStore
from src.reservations import ReservationStore
from src.settings import Settings
from src.storage import Storage


def _other_thread_can_acquire(lock):
    """True, wenn ein ANDERER Thread den Lock nehmen kann (= Lock frei).
    Deterministisch: nur start/join, kein Sleep. RLock ist reentrant pro
    Thread — deshalb MUSS die Probe aus einem fremden Thread kommen."""
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


def _slot(start="08:00", end="16:00", pause=0):
    return {"start": start, "end": end, "pause": pause, "kategorie": ""}


def _assert_disk_write_locked(store, lock, mutate):
    """Spy auf _save_to_disk: während des Disk-Writes muss der Lock gehalten
    sein (Probe aus fremdem Thread darf ihn NICHT bekommen)."""
    held = []
    orig = store._save_to_disk

    def spy():
        held.append(not _other_thread_can_acquire(lock))
        orig()

    store._save_to_disk = spy
    mutate()
    assert held == [True]


def test_all_stores_accept_shared_lock(tmp_path):
    lock = threading.RLock()
    Storage(str(tmp_path / "z.json"), device_id="A", lock=lock)
    Settings(str(tmp_path / "s.json"), lock=lock)
    ConflictsStore(str(tmp_path / "c.json"), lock=lock)
    ReservationStore(str(tmp_path / "r.json"), lock=lock)


def test_storage_save_holds_lock_during_disk_write(tmp_path):
    lock = threading.RLock()
    storage = Storage(str(tmp_path / "z.json"), device_id="A", lock=lock)
    _assert_disk_write_locked(
        storage, lock, lambda: storage.save("2026-01-01", [_slot()]))


def test_storage_apply_merge_holds_lock_during_disk_write(tmp_path):
    lock = threading.RLock()
    storage = Storage(str(tmp_path / "z.json"), device_id="A", lock=lock)
    entry = {"slots": [_slot()], "modified_at": "2026-01-01T10:00:00Z",
             "device_id": "A", "deleted": False}
    _assert_disk_write_locked(
        storage, lock, lambda: storage.apply_merge({"2026-01-01": entry}))


def test_settings_set_holds_lock_during_disk_write(tmp_path):
    lock = threading.RLock()
    settings = Settings(str(tmp_path / "s.json"), lock=lock)
    _assert_disk_write_locked(
        settings, lock, lambda: settings.set("recipient", "x@example.com"))


def test_conflicts_save_all_holds_lock_during_disk_write(tmp_path):
    lock = threading.RLock()
    conflicts = ConflictsStore(str(tmp_path / "c.json"), lock=lock)
    _assert_disk_write_locked(
        conflicts, lock, lambda: conflicts.save_all([{"id": "1", "resolved": False}]))


def test_reservations_save_holds_lock_during_disk_write(tmp_path):
    lock = threading.RLock()
    store = ReservationStore(str(tmp_path / "r.json"), lock=lock)
    _assert_disk_write_locked(
        store, lock,
        lambda: store.save("2026-01-01", [{"start": "08:00", "end": "12:00"}]))


def test_default_lock_created_when_not_injected(tmp_path):
    """Ohne Injektion legt der Store einen eigenen RLock an — Alt-Aufrufer
    (bestehende Tests) bleiben unverändert und trotzdem intern threadsicher."""
    storage = Storage(str(tmp_path / "z.json"), device_id="A")
    _assert_disk_write_locked(
        storage, storage._lock, lambda: storage.save("2026-01-01", [_slot()]))


def test_parallel_writes_keep_file_valid_json(tmp_path):
    """Stresstest (Robustheitsnetz, kein Timing-Assert): parallele
    save/delete/apply_merge/get_all dürfen weder werfen noch die Datei
    korrumpieren."""
    lock = threading.RLock()
    path = tmp_path / "z.json"
    storage = Storage(str(path), device_id="A", lock=lock)
    errors = []

    def writer(i):
        try:
            for n in range(30):
                date = f"2026-01-{(n % 28) + 1:02d}"
                storage.save(date, [_slot()])
                if n % 7 == 0:
                    storage.delete(date)
                if n % 11 == 0:
                    storage.apply_merge(storage.get_all_raw())
                storage.get_all()
        except Exception as e:  # noqa: BLE001 — Fehler ins Hauptthread-Assert tragen
            errors.append(e)

    threads = [threading.Thread(target=writer, args=(i,)) for i in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    json.loads(path.read_text(encoding="utf-8"))  # Datei ist valides JSON
