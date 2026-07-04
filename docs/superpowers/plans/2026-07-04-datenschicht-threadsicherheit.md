# Datenschicht-Threadsicherheit (Audit H1/H2/M1) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Die vier JSON-Stores threadsicher machen und alle Drive-Sync-Läufe serialisieren, damit weder parallele Writes JSON korrumpieren (H2) noch UI-Saves im Sync-Fenster verloren gehen (H1) noch verwaiste Timeout-Worker parallel schreiben (M1).

**Architecture:** Ein geteilter `threading.RLock` (`data_lock`) wird in alle vier Stores injiziert und klammert in den Sync-Flows den Block Snapshot→Merge→Apply (nie über Netzwerk). Ein separater plain `threading.Lock` (`sync_guard`) serialisiert alle Sync-Einstiege; acquired UND released wird er im innersten Worker-Thread (`finally`, nach der letzten Store-Mutation) — nie in UI-Callbacks, nie beim Join-Timeout. Spec: `docs/superpowers/specs/2026-07-04-datenschicht-threadsicherheit-design.md`.

**Tech Stack:** Python 3.10+ stdlib (`threading`, `contextlib`), Tkinter, pytest. Keine neuen Dependencies.

## Global Constraints

- **Guard-Invariante:** `sync_guard` ist ein plain `threading.Lock` (NIE `RLock` — `Lock.release()` ist cross-thread erlaubt, `RLock` erzwingt Owner-Release). Release ausschließlich im `finally` des Threads, der die Store-Mutationen ausführt.
- **Daten-Lock-Invariante:** `data_lock` (`RLock`) wird NIE über einen Netzwerk-Call (`drive.get_drive_service`/`download`/`upload`, gcal-Calls) gehalten.
- Alle neuen Parameter sind Keyword-Parameter mit Default `None` — bestehende Aufrufer/Tests bleiben unverändert lauffähig.
- Tests: keine `sleep`s, keine Timing-Asserts — nur `threading.Event`/`start`/`join`/Probe-Threads. Alle bestehenden Tests (717 passed, 3 skipped) müssen grün bleiben.
- Kommentare/Docstrings auf Deutsch, Stil der umliegenden Dateien.
- Shell ist PowerShell 5.1: **kein `&&`** — Befehle einzeln oder mit `;` verketten.
- Test-Kommando aus dem Repo-Root: `python -m pytest -q` (Gesamtlauf) bzw. `python -m pytest <datei>::<test> -v`.
- Commit-Messages deutsch mit Conventional-Prefix; jede Commit-Message endet mit `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>` (als zweites `-m`).

---

### Task 0: Branch anlegen, Baseline prüfen, Docs committen

**Files:**
- Commit: `docs/superpowers/specs/2026-07-04-datenschicht-threadsicherheit-design.md`, `docs/superpowers/plans/2026-07-04-datenschicht-threadsicherheit.md`

**Interfaces:**
- Produces: Branch `fix/datenschicht-threadsicherheit` (ab `master`), grüne Baseline.

- [ ] **Step 1: Branch von master abzweigen**

```powershell
git checkout master
git pull
git checkout -b fix/datenschicht-threadsicherheit
```

Hinweis: Repo-Setup ist Fork→Upstream (origin = Fork, PRs gegen `margenheld/Zeiterfassung`). Falls `master` hinter upstream hängt: `git fetch upstream ; git merge upstream/master` vor dem Abzweigen. Die untracked Dateien (`AUDIT-2026-07-04.md`, docs) wandern automatisch mit.

- [ ] **Step 2: Baseline-Tests laufen lassen**

Run: `python -m pytest -q`
Expected: `717 passed, 3 skipped` (Anzahl kann leicht abweichen, aber 0 failed).

- [ ] **Step 3: Spec + Plan committen (NICHT das Audit — bleibt Arbeitsdokument)**

```powershell
git add docs/superpowers/specs/2026-07-04-datenschicht-threadsicherheit-design.md docs/superpowers/plans/2026-07-04-datenschicht-threadsicherheit.md
git commit -m "docs: Spec + Plan Datenschicht-Threadsicherheit (Audit H1/H2/M1)" -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 1: Geteilter RLock in allen vier Stores

**Files:**
- Modify: `src/storage.py`, `src/settings.py`, `src/conflicts_store.py`, `src/reservations.py`
- Test: `tests/test_store_locking.py` (neu)

**Interfaces:**
- Produces: `Storage(filepath, device_id="", lock=None)`, `Settings(filepath, lock=None)`, `ConflictsStore(filepath, lock=None)`, `ReservationStore(filepath, lock=None)`. Bei `lock=None` legt jeder Store einen eigenen `threading.RLock` an; injizierter Lock wird geteilt. Alle öffentlichen Lese-/Schreibmethoden laufen unter `with self._lock:`.
- Consumes: nichts (Basis-Task).

- [ ] **Step 1: Failing Tests schreiben**

Neue Datei `tests/test_store_locking.py`:

```python
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
```

- [ ] **Step 2: Tests laufen lassen — müssen fehlschlagen**

Run: `python -m pytest tests/test_store_locking.py -v`
Expected: FAIL, alle Tests mit `TypeError: __init__() got an unexpected keyword argument 'lock'`.

- [ ] **Step 3: `src/storage.py` umbauen**

Import ergänzen (nach `import json`):

```python
import threading
```

Konstruktor:

```python
    def __init__(self, filepath="zeiterfassung.json", device_id="", lock=None):
        self.filepath = filepath
        self.device_id = device_id
        # Geteilter Daten-Lock (Audit H1/H2): main() injiziert EINEN RLock in
        # alle vier Stores; ohne Injektion (Tests, Alt-Aufrufer) eigener Lock.
        # _load()/Migration laufen vor dem Teilen (single-threaded Boot) —
        # bewusst ungelockt.
        self._lock = lock if lock is not None else threading.RLock()
        self._data = {}
        self._load()
```

Alle öffentlichen Methoden bekommen `with self._lock:` um den kompletten Body (Einrückung +1). Vollständig:

```python
    def get_all(self):
        """Liefert {date: {slots: [...]}} ohne Tombstones."""
        with self._lock:
            return {
                date: self._user_shape(entry)
                for date, entry in self._data.items()
                if not entry.get("deleted")
            }

    def get_all_raw(self):
        """Liefert die kompletten Eintragsobjekte inkl. Metadaten und Tombstones.
        Nur für den Sync-Pfad."""
        with self._lock:
            return dict(self._data)

    def get(self, date_str):
        with self._lock:
            entry = self._data.get(date_str)
            if entry is None or entry.get("deleted"):
                return None
            return self._user_shape(entry)

    def save(self, date_str, slots):
        with self._lock:
            self._data[date_str] = {
                "slots": [_normalize_slot(s) for s in slots],
                "modified_at": _utc_now_iso(),
                "device_id": self.device_id,
                "deleted": False,
            }
            self._save_to_disk()

    def delete(self, date_str):
        with self._lock:
            if date_str not in self._data:
                return
            # Tombstone: behält die Zeile mit deleted=true, damit der Sync ein
            # Delete gegen ein veraltetes Save eines anderen Geräts durchsetzen kann.
            self._data[date_str] = {
                "slots": [],
                "modified_at": _utc_now_iso(),
                "device_id": self.device_id,
                "deleted": True,
            }
            self._save_to_disk()

    def apply_merge(self, merged_entries):
        """Ersetzt den kompletten Storage-Stand durch das Merge-Ergebnis.
        merged_entries: {date: {slots, modified_at, device_id, deleted}}.
        Wirft ValueError, wenn ein Eintrag Pflichtfelder vermissen lässt."""
        with self._lock:
            for date, entry in merged_entries.items():
                missing = _REQUIRED_ENTRY_KEYS - entry.keys()
                if missing:
                    raise ValueError(
                        f"apply_merge: entry {date!r} missing keys {sorted(missing)}"
                    )
            self._data = dict(merged_entries)
            self._save_to_disk()

    def save_many(self, updates):
        """Mehrere Einträge in einem einzigen Disk-Write speichern.

        updates: {date_str: {"slots": [...]}}. Jeder Eintrag bekommt
        frische modified_at/device_id/deleted=False. Existierende Tombstones
        am selben Datum werden überschrieben.

        Leeres Dict ist No-op (kein Disk-Roundtrip).
        """
        if not updates:
            return
        with self._lock:
            now = _utc_now_iso()
            for date_str, payload in updates.items():
                self._data[date_str] = {
                    "slots": [_normalize_slot(s) for s in payload.get("slots", [])],
                    "modified_at": now,
                    "device_id": self.device_id,
                    "deleted": False,
                }
            self._save_to_disk()
```

(`_load`, `_migrate_legacy_entries`, `_save_to_disk`, `_user_shape` bleiben unverändert — `_save_to_disk` wird nur innerhalb gelockter Methoden gerufen.)

- [ ] **Step 4: `src/settings.py` umbauen**

Import ergänzen (nach `import os`): `import threading`

Konstruktor:

```python
    def __init__(self, filepath="settings.json", lock=None):
        self.filepath = filepath
        # Geteilter Daten-Lock (Audit H1/H2) — siehe storage.py.
        self._lock = lock if lock is not None else threading.RLock()
        self._data = dict(DEFAULTS)
        self._synced_meta = {}   # {key: {"modified_at": ..., "device_id": ...}}
        self.device_id_for_sync = ""  # wird von main.py auf settings.device_id gesetzt
        self._load()
```

Methoden (RLock ist reentrant — `set` → `set_many` und `apply_updates` → `set_synced`/`set_many` bleiben korrekt):

```python
    def get(self, key):
        with self._lock:
            return self._data.get(key, DEFAULTS.get(key))

    def set_many(self, updates):
        """Mehrere Werte setzen, einmal auf Platte schreiben.

        Leeres Dict ist No-op (kein Disk-Roundtrip).
        """
        if not updates:
            return
        with self._lock:
            self._data.update(updates)
            self._save_to_disk()

    def set_synced(self, key, value):
        """Setzt einen whitelisted Sync-Key und stempelt Per-Field-Metadaten.
        Außerhalb der Whitelist verhält sich wie ein normales set()."""
        if key not in SYNCED_SETTING_KEYS:
            self.set(key, value)
            return
        with self._lock:
            self._data[key] = value
            self._synced_meta[key] = {
                "modified_at": _utc_now_iso(),
                "device_id": self.device_id_for_sync,
            }
            self._save_to_disk()

    def get_synced_doc(self):
        """{key: {value, modified_at, device_id}} — Eingabe für den Sync-Merge.
        Nur Keys mit vorhandener Metadaten-Spur werden zurückgegeben."""
        with self._lock:
            doc = {}
            for key in SYNCED_SETTING_KEYS:
                meta = self._synced_meta.get(key)
                if meta is None:
                    continue
                doc[key] = {
                    "value": self._data.get(key, DEFAULTS.get(key)),
                    "modified_at": meta["modified_at"],
                    "device_id": meta["device_id"],
                }
            return doc

    def apply_synced(self, synced_doc):
        """Übernimmt das Merge-Ergebnis: schreibt value in _data und Meta in
        _synced_meta. Schreibt einmal auf Platte."""
        if not synced_doc:
            return
        with self._lock:
            for key, payload in synced_doc.items():
                if key not in SYNCED_SETTING_KEYS:
                    continue
                if not isinstance(payload, dict) or "value" not in payload:
                    continue
                self._data[key] = payload["value"]
                self._synced_meta[key] = {
                    "modified_at": str(payload.get("modified_at", "")),
                    "device_id": str(payload.get("device_id", "")),
                }
            self._save_to_disk()
```

(`set` und `apply_updates` delegieren an gelockte Methoden — unverändert lassen.)

- [ ] **Step 5: `src/conflicts_store.py` umbauen**

Import ergänzen: `import threading`

```python
    def __init__(self, filepath="conflicts.json", lock=None):
        self.filepath = filepath
        # Geteilter Daten-Lock (Audit H1/H2) — siehe storage.py.
        self._lock = lock if lock is not None else threading.RLock()
        self._conflicts = []
        self._load()

    def get_all(self):
        with self._lock:
            return list(self._conflicts)

    def save_all(self, conflicts):
        with self._lock:
            self._conflicts = list(conflicts)
            self._save_to_disk()

    def count_unresolved(self):
        with self._lock:
            return sum(1 for c in self._conflicts if not c.get("resolved"))
```

- [ ] **Step 6: `src/reservations.py` umbauen**

Import ergänzen: `import threading`

```python
    def __init__(self, filepath="reservations.json", lock=None):
        self.filepath = filepath
        # Geteilter Daten-Lock (Audit H1/H2) — siehe storage.py.
        self._lock = lock if lock is not None else threading.RLock()
        self._data = {}
        self._load()
```

`get_all`, `get_all_raw`, `get`, `save`, `delete`, `apply_reconciled` analog zu Storage komplett in `with self._lock:` einrücken (Bodies unverändert, nur eingerückt; bei `save` gehört die komplette Positions-Übernahme-Logik inkl. `_save_to_disk()` in den Block, bei `delete` auch der Early-Return `if date_str not in self._data: return`).

- [ ] **Step 7: Tests laufen lassen — müssen bestehen**

Run: `python -m pytest tests/test_store_locking.py -v`
Expected: alle PASS.

- [ ] **Step 8: Gesamtsuite + Lint**

Run: `python -m pytest -q ; ruff check .`
Expected: 0 failed, ruff „All checks passed".

- [ ] **Step 9: Commit**

```powershell
git add src/storage.py src/settings.py src/conflicts_store.py src/reservations.py tests/test_store_locking.py
git commit -m "fix(stores): geteilten RLock in alle vier Stores injizieren (Audit H2)" -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Pull-Flow — Daten-Lock-Block + Sync-Guard

**Files:**
- Modify: `src/main.py` (`_run_pull_in_background`, neuer Helfer `_lock_ctx`)
- Test: `tests/test_sync_threading.py` (neu)

**Interfaces:**
- Consumes: Stores mit `lock=`-Param (Task 1).
- Produces: `_lock_ctx(lock)` (Context-Manager-Shim, `None` → `contextlib.nullcontext()`); `_run_pull_in_background(storage, settings, conflicts_store, base, ui_callback, data_lock=None, sync_guard=None)`. Skip-Semantik: bei gehaltenem Guard kehrt der Pull zurück, OHNE `ui_callback` zu rufen.

- [ ] **Step 1: Failing Tests schreiben**

Neue Datei `tests/test_sync_threading.py`:

```python
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
```

- [ ] **Step 2: Tests laufen lassen — müssen fehlschlagen**

Run: `python -m pytest tests/test_sync_threading.py -v`
Expected: FAIL mit `TypeError: _run_pull_in_background() got an unexpected keyword argument 'data_lock'` (die ersten zwei Tests); der dritte PASS (unveränderte Signatur-Nutzung).

- [ ] **Step 3: `_lock_ctx`-Helfer + Pull-Umbau in `src/main.py`**

Import ergänzen (nach `import logging`): `import contextlib`

Helfer direkt vor `_run_pull_in_background` einfügen:

```python
def _lock_ctx(lock):
    """Context-Manager-Shim für den optionalen Daten-Lock: `with _lock_ctx(l)`
    lockt, wenn ein Lock übergeben wurde, und ist sonst ein No-op (Tests,
    Alt-Aufrufer). Hält den Sync-Apply-Block atomar gegen UI-Saves (Audit H1)."""
    return lock if lock is not None else contextlib.nullcontext()
```

`_run_pull_in_background` komplett ersetzen:

```python
def _run_pull_in_background(storage, settings, conflicts_store, base, ui_callback,
                            data_lock=None, sync_guard=None):
    """Pull läuft in einem Thread; UI-Update über ui_callback (root.after).

    sync_guard (plain Lock, Re-Entrancy-Guard, Audit H2): läuft bereits ein
    anderer Sync, wird der Pull still übersprungen — ohne ui_callback; der
    laufende Sync meldet sein Ergebnis selbst. Release im finally DIESES
    Threads (nach der letzten Store-Mutation), nie in UI-Callbacks.
    data_lock (geteilter Store-RLock, Audit H1): klammert
    Snapshot→Merge→Apply atomar gegen parallele UI-Saves. Wird NICHT über
    den Download gehalten."""
    from src import drive, sync
    if sync_guard is not None and not sync_guard.acquire(blocking=False):
        return
    try:
        try:
            service = drive.get_drive_service(
                os.path.join(base, "credentials.json"),
                os.path.join(base, "token.json"),
                gcal_enabled=settings.get("gcal_enabled"),
            )
            file_id = drive.find_sync_file(service)
            if file_id is None:
                remote_doc = {"schema_version": 1, "entries": {}, "settings": {}, "conflicts": []}
                etag = ""
            else:
                content, etag = drive.download(service, file_id)
                def _quarantine(fid):
                    import datetime
                    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
                    try:
                        service.files().update(
                            fileId=fid,
                            body={"name": f"zeiterfassung-sync.corrupt-{stamp}.json"},
                        ).execute()
                    except Exception:
                        logging.getLogger(__name__).warning(
                            "Quarantine rename failed for %s", fid, exc_info=True)
                remote_doc = _parse_remote_or_quarantine(content, file_id, _quarantine)
            if sync._remote_is_newer(remote_doc):
                # Neueres (zukünftiges) Schema: NICHT mergen/pushen — Pull sauber
                # abbrechen, last_pull_at/etag unverändert lassen.
                ui_callback(ok=False, error=sync.NEWER_REMOTE_VERSION_MSG, tb="")
                return
            # Älteres Remote (v1/v2) wird aufs aktuelle Schema migriert und normal
            # gemergt (absorb-and-upgrade). Dass ältere Geräte ein hochgezogenes
            # v4-Doc nicht überschreiben, sichert deren Push-Guard (ab v1.15.2).
            remote_doc = sync.migrate_doc_to_current(remote_doc)
            # Snapshot→Merge→Apply atomar: kein UI-Save kann zwischen
            # build_local_doc und apply_merged_doc interleaven (Audit H1).
            with _lock_ctx(data_lock):
                local_doc = sync.build_local_doc(storage, settings, conflicts_store)
                merged = sync.merge(local_doc, remote_doc, settings.get("last_pull_at") or "")
                sync.apply_merged_doc(merged, storage, settings, conflicts_store)
                settings.set_many({
                    "last_pull_at": sync._utc_now_iso(),
                    "drive_etag": etag,
                })
            ui_callback(ok=True, error=None, tb="")
        except Exception as e:
            tb = traceback.format_exc()
            logging.getLogger(__name__).exception("Sync pull failed")
            ui_callback(ok=False, error=e, tb=tb)
    finally:
        if sync_guard is not None:
            sync_guard.release()
```

- [ ] **Step 4: Tests laufen lassen — müssen bestehen**

Run: `python -m pytest tests/test_sync_threading.py tests/test_sync.py -v`
Expected: alle PASS (auch die bestehenden Pull-Tests, da neue Params Defaults haben).

- [ ] **Step 5: Commit**

```powershell
git add src/main.py tests/test_sync_threading.py
git commit -m "fix(sync): Pull — Daten-Lock um Snapshot/Merge/Apply + Re-Entrancy-Guard (Audit H1/H2)" -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Push + Kompaktierung — Guard im inneren Worker, Lock-Block ohne Netz

**Files:**
- Modify: `src/main.py` (`_run_push_blocking`, `_run_compaction_blocking`)
- Test: `tests/test_sync_threading.py` (erweitern)

**Interfaces:**
- Consumes: `_lock_ctx` (Task 2), Stores mit Lock (Task 1).
- Produces: `_run_push_blocking(storage, settings, conflicts_store, base, timeout_seconds=5, data_lock=None, sync_guard=None, guard_timeout=0)` und `_run_compaction_blocking(storage, settings, conflicts_store, base, timeout_seconds=20, data_lock=None, sync_guard=None)`. Skip-Result: `{"ok": False, "skipped": True}`. `guard_timeout>0` → blockierend warten (Quit-Semantik), sonst non-blocking-skip. Guard-Release im `finally` des **inneren** `_do`-Threads.

- [ ] **Step 1: Failing Tests an `tests/test_sync_threading.py` anhängen**

```python
def test_push_skipped_when_guard_held(tmp_path):
    import src.main as main
    lock = threading.RLock()
    storage, settings, conflicts = _stores(tmp_path, lock)
    guard = threading.Lock()
    assert guard.acquire(blocking=False)
    try:
        res = main._run_push_blocking(
            storage, settings, conflicts, str(tmp_path),
            data_lock=lock, sync_guard=guard)
    finally:
        guard.release()
    assert res == {"ok": False, "skipped": True}


def test_push_holds_data_lock_during_apply(tmp_path, monkeypatch):
    import src.main as main
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
    res = main._run_push_blocking(
        storage, settings, conflicts, str(tmp_path),
        data_lock=lock, sync_guard=None)
    assert res.get("ok") is True
    assert held == [True]


def test_push_uploads_without_holding_data_lock(tmp_path, monkeypatch):
    """Spec-Invariante: der Daten-Lock wird NIE über den Netzwerk-Upload
    gehalten — während drive.upload muss er aus fremdem Thread nehmbar sein."""
    import src.main as main
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
    res = main._run_push_blocking(
        storage, settings, conflicts, str(tmp_path),
        data_lock=lock, sync_guard=None)
    assert res.get("ok") is True
    assert lock_free == [True]


def test_push_guard_released_after_run(tmp_path, monkeypatch):
    import src.main as main
    lock = threading.RLock()
    storage, settings, conflicts = _stores(tmp_path, lock)
    _mock_drive_empty(monkeypatch)
    guard = threading.Lock()
    res = main._run_push_blocking(
        storage, settings, conflicts, str(tmp_path),
        data_lock=lock, sync_guard=guard)
    assert res.get("ok") is True
    assert guard.acquire(blocking=False)   # Guard nach dem Lauf wieder frei
    guard.release()


def test_push_guard_timeout_waits_for_running_sync(tmp_path, monkeypatch):
    """Quit-Semantik: guard_timeout>0 wartet auf den laufenden Sync statt zu
    skippen. Deterministischer Ausgang (großzügige Timeouts begrenzen nur die
    Dauer im Fehlerfall, sie werden nicht asserted)."""
    import src.main as main
    lock = threading.RLock()
    storage, settings, conflicts = _stores(tmp_path, lock)
    _mock_drive_empty(monkeypatch)
    guard = threading.Lock()
    guard.acquire()   # "laufender Sync"
    out = {}

    def run_push():
        out["res"] = main._run_push_blocking(
            storage, settings, conflicts, str(tmp_path),
            timeout_seconds=30, data_lock=lock, sync_guard=guard,
            guard_timeout=30)

    t = threading.Thread(target=run_push)
    t.start()
    guard.release()   # der "laufende Sync" endet — der wartende Push übernimmt
    t.join()
    assert out["res"].get("ok") is True


def test_compaction_skipped_when_guard_held(tmp_path):
    import src.main as main
    lock = threading.RLock()
    storage, settings, conflicts = _stores(tmp_path, lock)
    guard = threading.Lock()
    assert guard.acquire(blocking=False)
    try:
        res = main._run_compaction_blocking(
            storage, settings, conflicts, str(tmp_path),
            data_lock=lock, sync_guard=guard)
    finally:
        guard.release()
    assert res == {"ok": False, "skipped": True}


def test_compaction_holds_data_lock_during_compact(tmp_path, monkeypatch):
    import src.main as main
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
    res = main._run_compaction_blocking(
        storage, settings, conflicts, str(tmp_path),
        data_lock=lock, sync_guard=None)
    assert res.get("ok") is True
    assert held == [True]
```

- [ ] **Step 2: Tests laufen lassen — müssen fehlschlagen**

Run: `python -m pytest tests/test_sync_threading.py -v`
Expected: die neuen Tests FAIL mit `TypeError: ... unexpected keyword argument 'data_lock'`; Task-2-Tests PASS.

- [ ] **Step 3: `_run_push_blocking` komplett ersetzen**

```python
def _run_push_blocking(storage, settings, conflicts_store, base, timeout_seconds=5,
                       data_lock=None, sync_guard=None, guard_timeout=0):
    """Synchroner Push mit Timeout. Fehler werden geloggt, nicht angezeigt
    (App schließt gerade).

    sync_guard/guard_timeout (Audit H2/M1): Re-Entrancy-Guard. guard_timeout=0
    → non-blocking (zweiter Klick/Tray-Sync liefert {"skipped": True});
    guard_timeout>0 → blockierend warten (Quit-Push wartet auf einen laufenden
    Sync). Der Guard wird im INNEREN _do-Thread acquired UND im finally
    released — erst nach der letzten Store-Mutation. Ein per Join-Timeout
    „verwaister" Worker hält ihn dadurch bis zum echten Ende: er IST dann der
    laufende Sync, statt parallel zu einem neuen zu schreiben.
    data_lock (Audit H1): klammert Snapshot→Merge→Apply→Upload-Snapshot
    atomar; der Upload selbst läuft OHNE Daten-Lock (nie Lock über Netz)."""
    import json
    from src import drive, sync

    result = {}

    def _do():
        if sync_guard is not None:
            got = (sync_guard.acquire(timeout=guard_timeout) if guard_timeout > 0
                   else sync_guard.acquire(blocking=False))
            if not got:
                result["ok"] = False
                result["skipped"] = True
                return
        try:
            try:
                service = drive.get_drive_service(
                    os.path.join(base, "credentials.json"),
                    os.path.join(base, "token.json"),
                    gcal_enabled=settings.get("gcal_enabled"),
                )
                file_id = drive.find_sync_file(service)
                # Push = download -> Guard -> Merge -> upload. drive.upload kennt
                # kein File-level If-Match (ignoriert expected_etag), daher MUSS hier
                # das frische Remote-Doc gelesen und gemergt werden — sonst
                # überschreibt der Push fremde oder neuere Stände blind (Datenverlust
                # bzw. Clobber eines neueren Schemas während eines Rollouts).
                if file_id is not None:
                    remote_bytes, _etag = drive.download(service, file_id)
                    try:
                        remote_doc = json.loads(remote_bytes)
                    except (json.JSONDecodeError, ValueError):
                        remote_doc = {"schema_version": 1, "entries": {}, "settings": {}, "conflicts": []}
                    if sync._remote_is_newer(remote_doc):
                        # Neueres Gerät hat das Remote-Doc fortgeschrieben: nicht
                        # mergen/überschreiben — Push abbrechen, neuere Daten bleiben.
                        result["ok"] = False
                        result["error"] = sync.NEWER_REMOTE_VERSION_MSG
                        result["tb"] = ""
                        return
                else:
                    remote_doc = {"schema_version": 1, "entries": {}, "settings": {}, "conflicts": []}
                # Älteres Remote (v1/v2) absorbieren: aufs aktuelle Schema migrieren,
                # dann mergen — sonst gingen v2-only-Stände beim Upload verloren.
                remote_doc = sync.migrate_doc_to_current(remote_doc)
                # Snapshot→Merge→Apply→Upload-Snapshot atomar (Audit H1);
                # der Upload danach läuft bewusst ungelockt.
                with _lock_ctx(data_lock):
                    local_doc = sync.build_local_doc(storage, settings, conflicts_store)
                    merged = sync.merge(local_doc, remote_doc, settings.get("last_pull_at") or "")
                    sync.apply_merged_doc(merged, storage, settings, conflicts_store)
                    doc = sync.build_local_doc(storage, settings, conflicts_store)
                    content = json.dumps(doc, ensure_ascii=False).encode("utf-8")
                new_id, new_etag = drive.upload(service, content, file_id, expected_etag="")
                settings.set_many({
                    "last_pull_at": sync._utc_now_iso(),
                    "drive_etag": new_etag,
                })
                result["ok"] = True
            except Exception as e:
                logging.getLogger(__name__).exception("Sync push failed: %s", e)
                result["ok"] = False
                result["error"] = str(e)
                result["tb"] = traceback.format_exc()
        finally:
            if sync_guard is not None:
                sync_guard.release()

    t = threading.Thread(target=_do, daemon=True)
    t.start()
    t.join(timeout=timeout_seconds)
    if not result:
        result = {"ok": False, "error": "Timeout", "tb": ""}
    return result
```

- [ ] **Step 4: `_run_compaction_blocking` komplett ersetzen**

```python
def _run_compaction_blocking(storage, settings, conflicts_store, base, timeout_seconds=20,
                             data_lock=None, sync_guard=None):
    """User-ausgelöste Kompaktierung: frischer Pull → Alt-Client-Guard → Merge →
    Watermark setzen + lokal strippen → Push. Liefert
    {"ok": bool, "reason": str, "error": ..., "tb": ...}.

    reason == "newer_version": ein neueres Gerät hat ein Schema geschrieben, das
    diese Version nicht versteht — Kompaktierung abgebrochen, kein Merge/Upload
    (sonst würde das neuere Doc überschrieben). Ältere Remote-Docs (v1/v2) werden
    wie bei Pull/Push aufs aktuelle Schema migriert.

    sync_guard: non-blocking — läuft ein Sync, kommt {"skipped": True} zurück
    (der Settings-Dialog zeigt dann einen Hinweis). Release im finally des
    inneren _do-Threads. data_lock: klammert Merge/Apply/Kompaktierung atomar;
    der Upload läuft ungelockt (Invarianten wie _run_push_blocking)."""
    import json
    from src import drive, sync

    result = {}

    def _do():
        if sync_guard is not None and not sync_guard.acquire(blocking=False):
            result["ok"] = False
            result["skipped"] = True
            return
        try:
            try:
                service = drive.get_drive_service(
                    os.path.join(base, "credentials.json"),
                    os.path.join(base, "token.json"),
                    gcal_enabled=settings.get("gcal_enabled"),
                )
                file_id = drive.find_sync_file(service)
                if file_id is not None:
                    content, _etag = drive.download(service, file_id)
                    try:
                        remote_doc = json.loads(content)
                    except (json.JSONDecodeError, ValueError):
                        remote_doc = {"schema_version": 1}
                    # Neueres Schema (>v3) auf dem FRISCH gepullten Doc: nicht
                    # mergen/überschreiben — Kompaktierung abbrechen.
                    if sync._remote_is_newer(remote_doc):
                        result.update({"ok": False, "reason": "newer_version"})
                        return
                else:
                    remote_doc = {"schema_version": 2, "entries": {}, "settings": {},
                                  "conflicts": [], "meta": {"gc_watermark": ""}}

                # Älteres Remote (v1/v2) absorbieren: aufs aktuelle Schema migrieren.
                remote_doc = sync.migrate_doc_to_current(remote_doc)
                now = sync._utc_now_iso()
                # Merge + Apply + Watermark/Strippung + Upload-Snapshot atomar
                # (Audit H1); der Upload danach läuft bewusst ungelockt.
                with _lock_ctx(data_lock):
                    # 1) normaler Merge des frischen Remote-Stands
                    local_doc = sync.build_local_doc(storage, settings, conflicts_store)
                    merged = sync.merge(local_doc, remote_doc, settings.get("last_pull_at") or "")
                    sync.apply_merged_doc(merged, storage, settings, conflicts_store)
                    settings.set("last_pull_at", now)
                    # 2) Watermark setzen + lokal strippen
                    sync.compact_local(storage, settings, conflicts_store, now)
                    # 3) kompaktiertes Doc für den Upload snapshotten
                    doc = sync.build_local_doc(storage, settings, conflicts_store)
                    payload = json.dumps(doc, ensure_ascii=False).encode("utf-8")
                new_id, new_etag = drive.upload(service, payload, file_id, expected_etag="")
                settings.set("drive_etag", new_etag)
                result.update({"ok": True})
            except Exception as e:
                logging.getLogger(__name__).exception("Kompaktierung fehlgeschlagen")
                result.update({"ok": False, "error": str(e), "tb": traceback.format_exc()})
        finally:
            if sync_guard is not None:
                sync_guard.release()

    t = threading.Thread(target=_do, daemon=True)
    t.start()
    t.join(timeout=timeout_seconds)
    if not result:
        result = {"ok": False, "error": "Timeout", "tb": ""}
    return result
```

- [ ] **Step 5: Tests laufen lassen — müssen bestehen**

Run: `python -m pytest tests/test_sync_threading.py tests/test_sync.py -v`
Expected: alle PASS.

- [ ] **Step 6: Commit**

```powershell
git add src/main.py tests/test_sync_threading.py
git commit -m "fix(sync): Push/Kompaktierung — Guard im inneren Worker, Lock nie über Netz (Audit H1/H2/M1)" -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: SyncOrchestrator — Verdrahtung, Button-Disable, skipped-Handling, Quit

**Files:**
- Modify: `src/sync_orchestrator.py`
- Test: `tests/test_sync_orchestrator.py` (erweitern + eine bestehende Fixture anpassen)

**Interfaces:**
- Consumes: `_run_push_blocking(..., data_lock=, sync_guard=, guard_timeout=)` (Task 3).
- Produces: `SyncOrchestrator(root, storage, settings, conflicts_store, base_path, runner, on_refresh, get_tray, data_lock=None, sync_guard=None)`; `_push(guard_timeout=0, timeout_seconds=15)`; `on_sync_clicked` deaktiviert den Button, `_on_manual_done` reaktiviert ihn und behandelt `skipped`; `_on_tray_done` skippt Toast bei `skipped`; `push_on_quit` nutzt `guard_timeout=5, timeout_seconds=10` und loggt bei `skipped` statt Dialog.

- [ ] **Step 1: Failing Tests schreiben (und Fixture erweitern)**

In `tests/test_sync_orchestrator.py` die Klasse `_FakeLabel` um eine `_FakeButton`-Klasse ergänzen und `_orch` um `data_lock`/`sync_guard` erweitern:

```python
class _FakeButton:
    """Fake für den Sync-Button: config(state=...) + winfo_ismapped für
    update_status_label (meldet sich als bereits gepackt)."""
    def __init__(self):
        self.state = None

    def config(self, state=None):
        if state is not None:
            self.state = state

    def winfo_ismapped(self):
        return True
```

`_orch` ersetzen durch:

```python
def _orch(sync_enabled=True, execute_runner=False, get_tray=lambda: None,
          conflicts=0, on_refresh=None, data_lock=None, sync_guard=None):
    _vals = {"sync_enabled": sync_enabled, "last_pull_at": None}
    settings = MagicMock(get=lambda k, d=None: _vals.get(k, d))
    conflicts_store = MagicMock(count_unresolved=lambda: conflicts)
    runner = _FakeRunner(execute=execute_runner)
    orch = SyncOrchestrator(
        root=object(), storage=object(), settings=settings,
        conflicts_store=conflicts_store, base_path=".", runner=runner,
        on_refresh=on_refresh or (lambda: None), get_tray=get_tray,
        data_lock=data_lock, sync_guard=sync_guard,
    )
    return orch, runner
```

Im bestehenden Test `test_on_sync_clicked_enabled_sets_label_and_runs` das `sync_button=object()` durch `sync_button=_FakeButton()` ersetzen (der Klick konfiguriert den Button-State jetzt).

Neue Tests anhängen:

```python
def test_on_sync_clicked_disables_button():
    orch, runner = _orch(sync_enabled=True, execute_runner=False)
    label, button = _FakeLabel(), _FakeButton()
    orch.attach_widgets(sync_button=button, status_label=label,
                        next_button=object())
    orch.on_sync_clicked()
    assert button.state == "disabled"


def test_on_manual_done_reenables_button():
    orch, _ = _orch(sync_enabled=True)
    label, button = _FakeLabel(), _FakeButton()
    orch.attach_widgets(sync_button=button, status_label=label,
                        next_button=object())
    orch._on_manual_done({"ok": True})
    assert button.state == "normal"


def test_on_manual_done_skipped_shows_no_error(monkeypatch):
    import src.sync_orchestrator as so
    errors = []
    monkeypatch.setattr(so, "_show_sync_error", lambda *a, **k: errors.append(a))
    refreshed = []
    orch, _ = _orch(sync_enabled=True, on_refresh=lambda: refreshed.append(1))
    label, button = _FakeLabel(), _FakeButton()
    orch.attach_widgets(sync_button=button, status_label=label,
                        next_button=object())
    orch._on_manual_done({"ok": False, "skipped": True})
    assert errors == []          # kein Fehlerdialog — anderer Sync läuft nur
    assert refreshed == []       # kein Refresh nötig, nichts hat sich geändert
    assert button.state == "normal"


def test_on_tray_done_skipped_no_toast():
    tray = MagicMock()
    orch, _ = _orch(get_tray=lambda: tray)
    orch._on_tray_done({"ok": False, "skipped": True})
    tray.notify.assert_not_called()


def test_push_passes_lock_guard_and_timeouts(monkeypatch):
    captured = {}

    def fake(storage, settings, conflicts_store, base, timeout_seconds=5, **kw):
        captured.update(kw)
        captured["timeout_seconds"] = timeout_seconds
        return {"ok": True}

    monkeypatch.setattr("src.main._run_push_blocking", fake)
    lock, guard = object(), object()
    orch, _ = _orch(sync_enabled=True, data_lock=lock, sync_guard=guard)
    orch._push()
    assert captured["data_lock"] is lock
    assert captured["sync_guard"] is guard
    assert captured["guard_timeout"] == 0
    assert captured["timeout_seconds"] == 15


def test_push_on_quit_uses_guard_timeout(monkeypatch):
    captured = {}

    def fake(storage, settings, conflicts_store, base, timeout_seconds=5, **kw):
        captured.update(kw)
        captured["timeout_seconds"] = timeout_seconds
        return {"ok": True}

    monkeypatch.setattr("src.main._run_push_blocking", fake)
    orch, _ = _orch(sync_enabled=True)
    orch.push_on_quit()
    assert captured["guard_timeout"] == 5
    assert captured["timeout_seconds"] == 10


def test_push_on_quit_skipped_logs_no_dialog(monkeypatch):
    import src.sync_orchestrator as so
    errors = []
    monkeypatch.setattr(so, "_show_sync_error", lambda *a, **k: errors.append(a))
    monkeypatch.setattr("src.main._run_push_blocking",
                        lambda *a, **k: {"ok": False, "skipped": True})
    orch, _ = _orch(sync_enabled=True)
    orch.push_on_quit()
    assert errors == []
```

- [ ] **Step 2: Tests laufen lassen — müssen fehlschlagen**

Run: `python -m pytest tests/test_sync_orchestrator.py -v`
Expected: FAIL — `_orch` scheitert mit `TypeError: __init__() got an unexpected keyword argument 'data_lock'`.

- [ ] **Step 3: `src/sync_orchestrator.py` umbauen**

Import ergänzen (nach `import tkinter as tk`): `import logging`

`__init__` ersetzen:

```python
    def __init__(self, root, storage, settings, conflicts_store, base_path,
                 runner, on_refresh, get_tray, data_lock=None, sync_guard=None):
        self._root = root
        self._storage = storage
        self._settings = settings
        self._conflicts_store = conflicts_store
        self._base_path = base_path
        self._runner = runner          # App._bg, hat .run(fn, on_done)
        self._on_refresh = on_refresh    # App._refresh
        self._get_tray = get_tray        # lambda: App._tray
        self._data_lock = data_lock      # geteilter Store-RLock (Audit H1)
        self._sync_guard = sync_guard    # Sync-Re-Entrancy-Guard (Audit H2)
        self._sync_button = None
        self._status_label = None
        self._next_button = None
```

`_push` ersetzen:

```python
    def _push(self, guard_timeout=0, timeout_seconds=15):
        from src.main import _run_push_blocking
        return _run_push_blocking(
            self._storage, self._settings, self._conflicts_store,
            self._base_path, timeout_seconds=timeout_seconds,
            data_lock=self._data_lock, sync_guard=self._sync_guard,
            guard_timeout=guard_timeout,
        )
```

`on_sync_clicked` — nach der `_status_label`-Zeile den Button deaktivieren:

```python
    def on_sync_clicked(self):
        if not self._settings.get("sync_enabled"):
            themed_showinfo(
                self._root,
                "Synchronisation",
                "Synchronisation ist deaktiviert. In den Einstellungen aktivierbar.")
            return
        self._status_label.config(text="Synchronisiere…")
        if self._sync_button is not None:
            self._sync_button.config(state=tk.DISABLED)
        self._runner.run(self._push, self._on_manual_done)
```

`_on_manual_done` ersetzen:

```python
    def _on_manual_done(self, result):
        if self._sync_button is not None:
            self._sync_button.config(state=tk.NORMAL)
        if result.get("skipped"):
            # Anderer Sync läuft bereits — dessen Callback aktualisiert die UI.
            self.update_status_label()
            return
        if not result.get("ok"):
            _show_sync_error(self._root, result.get("error", "?"),
                             result.get("tb", ""))
        self._on_refresh()
        self.update_status_label()
```

`_on_tray_done` — skipped-Early-Return an den Anfang:

```python
    def _on_tray_done(self, result):
        if result.get("skipped"):
            return  # anderer Sync läuft — kein Toast, nichts hat sich geändert
        self._on_refresh()
        self.update_status_label()
        tray = self._get_tray()
        if tray is None:
            return
        tray.notify(
            _tray_toast(result.get("ok"), self._conflict_count(),
                       result.get("error", "?")),
            title="",
        )
```

`push_on_quit` ersetzen (nutzt jetzt `self._push` statt Duplikat — DRY):

```python
    def push_on_quit(self):
        """Blockierender Push beim Beenden. Wartet per guard_timeout bis 5 s
        auf einen laufenden Sync (Worst Case gesamt ~10 s mit Push-Timeout).
        Kein tray.stop() (bleibt App-Lifecycle)."""
        if not self._settings.get("sync_enabled"):
            return
        try:
            result = self._push(guard_timeout=5, timeout_seconds=10)
        except Exception as e:
            result = {"ok": False, "error": e, "tb": traceback.format_exc()}
        if result.get("skipped"):
            logging.getLogger(__name__).warning(
                "Quit-Push übersprungen — ein anderer Sync läuft noch; "
                "lokale Daten syncen beim nächsten Start.")
            return
        if not result.get("ok"):
            _show_sync_error(
                self._root, result.get("error", "?"), result.get("tb", ""),
                suffix="Lokale Daten bleiben erhalten und werden beim "
                       "nächsten Start synchronisiert.",
            )
```

- [ ] **Step 4: Tests laufen lassen — müssen bestehen**

Run: `python -m pytest tests/test_sync_orchestrator.py -v`
Expected: alle PASS (inkl. der angepassten Bestands-Tests).

- [ ] **Step 5: Commit**

```powershell
git add src/sync_orchestrator.py tests/test_sync_orchestrator.py
git commit -m "fix(sync): Orchestrator — Guard/Lock-Verdrahtung, Button-Disable, skipped-Handling, Quit-Wartefenster" -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: Reconcile-Pfad — Rebase+Apply unter dem Daten-Lock (angrenzend)

**Files:**
- Modify: `src/reservations_sync.py` (`reconcile_reservations`), `src/main.py` (`run_calendar_reconcile`), `src/background_tasks.py` (`BackgroundTaskRunner`)
- Test: `tests/test_sync_threading.py` (erweitern)

**Interfaces:**
- Consumes: `ReservationStore(..., lock=)` (Task 1).
- Produces: `reconcile_reservations(service, calendar_id, store, settings, data_lock=None)`; `run_calendar_reconcile(reservation_store, settings, base, storage, data_lock=None)`; `BackgroundTaskRunner(marshal, settings, base_path, reservation_store, reservations_active, storage=None, data_lock=None)`.

- [ ] **Step 1: Failing Test an `tests/test_sync_threading.py` anhängen**

```python
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
```

- [ ] **Step 2: Test laufen lassen — muss fehlschlagen**

Run: `python -m pytest tests/test_sync_threading.py::test_reconcile_holds_data_lock_during_rebase_and_apply -v`
Expected: FAIL mit `TypeError: reconcile_reservations() got an unexpected keyword argument 'data_lock'`.

- [ ] **Step 3: `src/reservations_sync.py` umbauen**

Import ergänzen (bei den Modul-Imports): `import contextlib`

Signatur + Schlussteil von `reconcile_reservations` ändern (Docstring-Ergänzung + Lock-Klammer um Rebase/Apply/Watermark; der gcal-Netzwerkteil davor bleibt ungelockt):

```python
def reconcile_reservations(service, calendar_id, store, settings, data_lock=None):
```

Docstring um diesen Absatz ergänzen:

```python
    data_lock: optionaler geteilter Store-Lock (Audit H1/H2, angrenzend) —
    klammert Rebase → apply_reconciled → Watermark atomar gegen parallele
    UI-Saves. Die gcal-Netzwerk-Calls davor laufen bewusst ungelockt.
```

Den Schlussblock (ab dem Rebase-Kommentar) ersetzen:

```python
    # Rebase: Reservierungen, die seit dem Snapshot lokal gespeichert/geändert
    # wurden (paralleler Reconcile / User-Save während des Netzwerkteils),
    # dürfen nicht durch den apply_reconciled-Replace verloren gehen.
    # Rebase + Replace + Watermark laufen atomar unter dem Daten-Lock —
    # zwischen Rebase-Read und Replace kann so kein weiterer Save landen.
    with (data_lock if data_lock is not None else contextlib.nullcontext()):
        for date, entry in store.get_all_raw().items():
            snap = local_snapshot.get(date)
            if snap is None or entry.get("modified_at", "") > snap.get("modified_at", ""):
                merged[date] = entry

        store.apply_reconciled(merged)
        settings.set("last_calendar_sync_at", _utc_now_iso())
    return {"imported_dates": imported_dates}
```

(Bewusst KEIN Import von `src.main._lock_ctx` — der wäre ein Zyklus `reservations_sync → main → ui → …`; der Inline-`contextlib`-Ausdruck ist der Preis dafür.)

- [ ] **Step 4: `run_calendar_reconcile` in `src/main.py` durchreichen**

Signatur: `def run_calendar_reconcile(reservation_store, settings, base, storage, data_lock=None):`

Docstring-Ergänzung (ein Satz): `data_lock wird an reconcile_reservations durchgereicht (Rebase+Apply atomar, Audit H1).`

Aufruf ersetzen:

```python
        result = reconcile_reservations(service, calendar_id, reservation_store,
                                        settings, data_lock=data_lock)
```

- [ ] **Step 5: `src/background_tasks.py` durchreichen**

`__init__` ersetzen:

```python
    def __init__(self, marshal, settings, base_path, reservation_store,
                 reservations_active, storage=None, data_lock=None):
        self._marshal = marshal                          # App._marshal_to_ui
        self._settings = settings
        self._base_path = base_path
        self._reservation_store = reservation_store
        self._reservations_active = reservations_active  # callable -> bool
        self._storage = storage
        self._data_lock = data_lock                      # geteilter Store-RLock
```

In `reconcile_on_start` UND `trigger_reconcile` den `run_calendar_reconcile`-Aufruf ersetzen:

```python
            return run_calendar_reconcile(
                self._reservation_store, self._settings, self._base_path,
                self._storage, data_lock=self._data_lock)
```

- [ ] **Step 6: Tests laufen lassen — müssen bestehen**

Run: `python -m pytest tests/test_sync_threading.py -v ; python -m pytest -q`
Expected: neuer Test PASS, Gesamtsuite 0 failed.

- [ ] **Step 7: Commit**

```powershell
git add src/reservations_sync.py src/main.py src/background_tasks.py tests/test_sync_threading.py
git commit -m "fix(reservations): Reconcile-Rebase+Apply unter dem geteilten Daten-Lock" -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: Settings-Dialog — Kompaktierung mit Guard + Hinweis bei laufendem Sync

**Files:**
- Modify: `src/dialogs/settings_dialog.py` (Signatur + Kompaktierungs-Closure, Z. ~505-551)

**Interfaces:**
- Consumes: `_run_compaction_blocking(..., data_lock=, sync_guard=)` (Task 3).
- Produces: `open_settings_dialog(parent, settings, base_path, on_change, *, conflicts_store=None, storage=None, reservation_store=None, on_request_restart=None, data_lock=None, sync_guard=None)`.

Hinweis: `settings_dialog` ist Tk-gebunden und in dieser Suite bewusst nicht headless getestet (Audit M16) — die Kompaktierungs-Semantik selbst ist über die Task-3-Tests abgedeckt; hier nur Durchreichung + Hinweis-Zweig. Verifikation über Gesamtsuite + manuellen Smoke in Task 7.

- [ ] **Step 1: Signatur erweitern**

```python
def open_settings_dialog(parent, settings, base_path, on_change, *,
                         conflicts_store=None, storage=None,
                         reservation_store=None, on_request_restart=None,
                         data_lock=None, sync_guard=None):
```

Docstring um einen Satz ergänzen: `data_lock/sync_guard: geteilter Store-Lock + Sync-Guard für die Kompaktierung (Audit H1/H2) — von App durchgereicht.`

- [ ] **Step 2: `_show`-Closure — skipped-Zweig VOR den reason-Checks einfügen**

In der Funktion `_show(res)` (aktuell Z. ~517) direkt nach dem `winfo_exists`-Guard:

```python
            def _show(res):
                if not dialog.winfo_exists():
                    return
                if res.get("skipped"):
                    themed_showinfo(
                        dialog,
                        "Kompaktierung",
                        "Eine Synchronisation läuft gerade — bitte kurz "
                        "warten und erneut versuchen.",
                    )
                    return
                if res.get("reason") == "old_version":
                    ...
```

(Restliche Zweige unverändert.)

- [ ] **Step 3: `_do`-Closure — Lock + Guard durchreichen**

```python
            def _do():
                from src.main import _run_compaction_blocking
                res = _run_compaction_blocking(
                    storage, settings, conflicts_store, base_path,
                    data_lock=data_lock, sync_guard=sync_guard)
                dialog.after(0, lambda: _show(res))
```

- [ ] **Step 4: Gesamtsuite + Lint**

Run: `python -m pytest -q ; ruff check .`
Expected: 0 failed, ruff sauber.

- [ ] **Step 5: Commit**

```powershell
git add src/dialogs/settings_dialog.py
git commit -m "fix(settings): Kompaktierung — Sync-Guard durchreichen, Hinweis bei laufendem Sync" -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 7: End-Verdrahtung main()/App + Architektur-Doku + Gesamtverifikation

**Files:**
- Modify: `src/main.py` (`main()`), `src/ui.py` (`App.__init__`, `_open_settings`-Aufruf), `src/CLAUDE.md` (Threading-Modell)

**Interfaces:**
- Consumes: alles aus Tasks 1–6.
- Produces: laufende App mit einem geteilten `data_lock` (RLock) über alle vier Stores und einem `sync_guard` (plain Lock) über alle fünf Sync-Einstiege.

- [ ] **Step 1: `main()` verdrahten**

In `src/main.py::main()` direkt vor der `Settings`-Instanzierung:

```python
    # Geteilter Daten-Lock über alle vier Stores (Audit H1/H2) + Sync-Guard.
    # data_lock: RLock (reentrant — der Sync-Apply-Block ruft gelockte
    # Store-Methoden). sync_guard: bewusst plain Lock, NIE RLock — er wird
    # thread-übergreifend acquired/released (Lock erlaubt das, RLock nicht).
    data_lock = threading.RLock()
    sync_guard = threading.Lock()

    settings = Settings(os.path.join(base, "settings.json"), lock=data_lock)
    device_id = _ensure_device_id(settings)
    settings.device_id_for_sync = device_id

    storage = Storage(os.path.join(base, "zeiterfassung.json"),
                      device_id=device_id, lock=data_lock)

    conflicts_store = ConflictsStore(os.path.join(base, "conflicts.json"),
                                     lock=data_lock)

    reservation_store = ReservationStore(os.path.join(base, "reservations.json"),
                                         lock=data_lock)
```

App-Konstruktion ersetzen:

```python
    app = App(root, storage, settings, base_path=base, conflicts_store=conflicts_store,
              reservation_store=reservation_store, single_instance=guard,
              data_lock=data_lock, sync_guard=sync_guard)
```

Startup-Pull-Thread ersetzen:

```python
        threading.Thread(
            target=_run_pull_in_background,
            args=(storage, settings, conflicts_store, base, _on_sync_done),
            kwargs={"data_lock": data_lock, "sync_guard": sync_guard},
            daemon=True,
        ).start()
```

- [ ] **Step 2: `App.__init__` in `src/ui.py` verdrahten**

Signatur (Z. 56-57) ersetzen:

```python
    def __init__(self, root, storage, settings, base_path=".", conflicts_store=None,
                 reservation_store=None, single_instance=None,
                 data_lock=None, sync_guard=None):
```

Nach `self.reservation_store = reservation_store` (Z. 64) einfügen:

```python
        self._data_lock = data_lock      # geteilter Store-RLock (Audit H1)
        self._sync_guard = sync_guard    # Sync-Re-Entrancy-Guard (Audit H2)
```

`BackgroundTaskRunner`-Konstruktion (Z. 119-122) ersetzen:

```python
        self._bg = BackgroundTaskRunner(
            self._marshal_to_ui, self.settings, self.base_path,
            self.reservation_store, self._reservations_active, self.storage,
            data_lock=data_lock,
        )
```

`SyncOrchestrator`-Konstruktion (Z. 123-126) ersetzen:

```python
        self._sync = SyncOrchestrator(
            self.root, self.storage, self.settings, self.conflicts_store,
            self.base_path, self._bg, self._refresh, lambda: self._tray,
            data_lock=data_lock, sync_guard=sync_guard,
        )
```

Im `open_settings_dialog`-Aufruf (Z. ~351-358) die zwei Kwargs anhängen:

```python
        open_settings_dialog(
            self.root, self.settings, self.base_path,
            on_change=_on_change,
            conflicts_store=self.conflicts_store,
            storage=self.storage,
            reservation_store=self.reservation_store,
            on_request_restart=self.restart_for_scaling,
            data_lock=self._data_lock,
            sync_guard=self._sync_guard,
        )
```

- [ ] **Step 3: `src/CLAUDE.md` — Threading-Modell ergänzen**

Im Abschnitt „## Threading-Modell" nach dem bestehenden Absatz anfügen:

```markdown
**Datenschicht-Locking (Audit H1/H2/M1):** Alle vier Stores
(`storage`/`settings`/`conflicts_store`/`reservations`) teilen sich einen in
`main()` erzeugten `RLock` (Konstruktor-Param `lock=`; ohne Injektion legt
jeder Store einen eigenen an — Tests bleiben unverändert). Die Sync-Flows
(`_run_pull_in_background`/`_run_push_blocking`/`_run_compaction_blocking`/
`reconcile_reservations`) klammern Snapshot→Merge→Apply mit diesem `data_lock`
— **nie über Netzwerk-Calls**. Ein separater plain `threading.Lock`
(`sync_guard`) serialisiert alle Drive-Sync-Einstiege (Startup-Pull, Manual-,
Tray-, Quit-Push, Kompaktierung): non-blocking-skip mit
`{"skipped": True}`-Result, nur der Quit-Push wartet (`guard_timeout=5`).
Acquired UND released wird der Guard im innersten Worker-Thread (`finally`,
nach der letzten Store-Mutation) — nie in UI-Callbacks, nie beim Join-Timeout;
er MUSS plain `Lock` bleiben (cross-thread release). Neue Sync-Einstiege
müssen beide Locks respektieren. Design:
`docs/superpowers/specs/2026-07-04-datenschicht-threadsicherheit-design.md`.
```

- [ ] **Step 4: Gesamtsuite + Lint**

Run: `python -m pytest -q ; ruff check .`
Expected: 0 failed (Baseline + ~20 neue Tests), ruff „All checks passed".

- [ ] **Step 5: Manueller Smoke-Test (Windows-Dev-Maschine)**

Run: `python -m src.main`
Prüfen: App startet; ein Eintrag lässt sich anlegen/löschen; App über X beenden (kein Hänger > ein paar Sekunden). Bei aktiviertem Sync zusätzlich: Sync-Button klicken → Button kurz deaktiviert, danach wieder aktiv. (Lokale Python-Umgebung braucht ggf. Deps — `holidays` ist installiert, Rest siehe Memory `run-app-needs-deps`.)

- [ ] **Step 6: Commit**

```powershell
git add src/main.py src/ui.py src/CLAUDE.md
git commit -m "feat(main): Daten-Lock + Sync-Guard app-weit verdrahten (Audit H1/H2/M1)" -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Abschluss

Nach Task 7: `superpowers:finishing-a-development-branch` — Branch nach `origin` (Fork) pushen, PR gegen `margenheld/Zeiterfassung` öffnen (siehe Memory `pr-workflow-upstream`). PR-Beschreibung: Audit-Findings H1/H2/M1 referenzieren, Spec verlinken, explizit erwähnen, dass M6 (Cross-Store-Transaktionalität) bewusst out of scope bleibt. Kein `release:*`-Label (kein Release-PR).
