# Multi-Device-Sync via Google Drive — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Multi-Device-Sync für Zeiteinträge und Mail-Settings via Google Drive `appDataFolder`, mit Last-Write-Wins pro Eintrag, expliziten Konflikt-Objekten und manueller User-Resolution.

**Architecture:** Sync-Engine (`src/sync.py`) ist pure Logik ohne Drive-Calls und lebt von Doc-Strukturen. Drive-API-Wrapper (`src/drive.py`) analog zu `src/mail.py`. Storage und Settings bekommen Per-Eintrag-/Per-Setting-Metadaten (`modified_at`, `device_id`, Tombstones). Konflikte sind First-Class-Objekte im Sync-File, Resolutions propagieren.

**Tech Stack:** Python stdlib, `google-api-python-client`, `google-auth`, `google-auth-oauthlib` (alle schon für Gmail vorhanden), Tkinter, pytest.

**Spec:** `docs/superpowers/specs/2026-05-14-multi-device-sync-design.md`

---

## File Structure

**Neue Dateien:**
- `src/sync.py` — Sync-Engine, pure Funktionen, keine I/O
- `src/drive.py` — Drive-API-Wrapper, OAuth + appDataFolder
- `src/conflicts_store.py` — JSON-Persistenz für `conflicts.json`
- `src/dialogs/conflicts_dialog.py` — Modal-Dialog für Konflikt-Resolution
- `tests/test_sync.py` — Unit-Tests für `sync.py`
- `tests/test_drive.py` — Mock-Tests für `drive.py`
- `tests/test_conflicts_store.py` — Unit-Tests für `conflicts_store.py`
- `tests/test_storage_migration.py` — Migrationstests für Storage

**Geänderte Dateien:**
- `src/storage.py` — Eintrags-Metadaten (`modified_at`, `device_id`, `deleted`), Tombstones, Migration, `apply_merge()`, `get_all_raw()`
- `src/settings.py` — Sync-Meta-Keys, `_synced_meta` Sub-Dict, `set_synced()`
- `src/mail.py` — Dynamisches `SCOPES` abhängig von Sync-State
- `src/main.py` — Storage/Settings mit `device_id` instanziieren, Pull beim Start, Push beim Close
- `src/ui.py` — Sync-Button + Status-Label im Header, Konflikt-Marker auf Kalender-Zellen
- `src/dialogs/settings_dialog.py` — Sync-Sektion mit Toggle, „Verbinden", „Konflikte ansehen"
- `tests/test_storage.py` — Anpassungen für Storage-Constructor mit `device_id`

---

## Phase 1: Foundation (Storage + Settings + ConflictsStore)

Diese Phase bringt nichts user-sichtbares — sie legt das Datenmodell-Fundament. Storage und Settings können neue Metadaten verwalten, ConflictsStore ist verfügbar. Sync-Engine kommt in Phase 2.

### Task 1.1: Storage — Constructor mit `device_id`, Metadaten beim Save

**Files:**
- Modify: `src/storage.py`
- Modify: `tests/test_storage.py`

- [ ] **Step 1: Failing test in `tests/test_storage.py` ergänzen**

Hänge an `tests/test_storage.py` an:

```python
def test_save_stamps_modified_at_and_device_id(tmp_path):
    storage = Storage(str(tmp_path / "t.json"), device_id="dev-1")
    storage.save("2026-05-14", "08:00", "16:00", pause=30)
    raw = storage.get_all_raw()
    assert raw["2026-05-14"]["start"] == "08:00"
    assert raw["2026-05-14"]["device_id"] == "dev-1"
    assert "modified_at" in raw["2026-05-14"]
    # ISO-Format
    assert "T" in raw["2026-05-14"]["modified_at"]
    assert raw["2026-05-14"]["modified_at"].endswith("Z")


def test_get_returns_user_shape_without_metadata(tmp_path):
    """Bestehende UI-Code-Pfade dürfen sich nicht ändern: get() liefert
    weiter {start, end, pause}, get_all() ebenso."""
    storage = Storage(str(tmp_path / "t.json"), device_id="dev-1")
    storage.save("2026-05-14", "08:00", "16:00", pause=30)
    assert storage.get("2026-05-14") == {"start": "08:00", "end": "16:00", "pause": 30}
    assert storage.get_all()["2026-05-14"] == {"start": "08:00", "end": "16:00", "pause": 30}
```

Außerdem den bestehenden Fixture-Konstruktor erweitern. Ersetze:

```python
@pytest.fixture
def tmp_storage(tmp_path):
    return Storage(str(tmp_path / "test.json"))
```

durch:

```python
@pytest.fixture
def tmp_storage(tmp_path):
    return Storage(str(tmp_path / "test.json"), device_id="test-device")
```

- [ ] **Step 2: Tests ausführen, Fail bestätigen**

```
pytest tests/test_storage.py::test_save_stamps_modified_at_and_device_id tests/test_storage.py::test_get_returns_user_shape_without_metadata -v
```

Erwartet: FAIL — `Storage.__init__` akzeptiert keinen `device_id`-Parameter, `get_all_raw()` existiert nicht.

- [ ] **Step 3: `src/storage.py` umbauen**

Ersetze den kompletten Inhalt von `src/storage.py`:

```python
import datetime
import json
import os


def _utc_now_iso():
    # Z-Suffix statt +00:00 — kompatibel zu JS/Drive-Konventionen
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class Storage:
    def __init__(self, filepath="zeiterfassung.json", device_id=""):
        self.filepath = filepath
        self.device_id = device_id
        self._data = {}
        self._load()

    def _load(self):
        if not os.path.exists(self.filepath):
            return
        try:
            with open(self.filepath, "r", encoding="utf-8") as f:
                self._data = json.load(f)
        except (json.JSONDecodeError, ValueError):
            stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
            os.replace(self.filepath, f"{self.filepath}.corrupt-{stamp}")
            self._data = {}

    def _save_to_disk(self):
        tmp = self.filepath + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self._data, f, indent=2, ensure_ascii=False)
        try:
            os.replace(tmp, self.filepath)
        except OSError:
            if os.path.exists(tmp):
                os.remove(tmp)
            raise

    @staticmethod
    def _user_shape(entry):
        """Reduziert ein Roh-Entry auf {start, end, pause} für UI-Callers."""
        return {"start": entry["start"], "end": entry["end"], "pause": entry.get("pause", 0)}

    def get_all(self):
        """Liefert {date: {start, end, pause}} ohne Tombstones."""
        return {
            date: self._user_shape(entry)
            for date, entry in self._data.items()
            if not entry.get("deleted")
        }

    def get_all_raw(self):
        """Liefert die kompletten Eintragsobjekte inkl. Metadaten und Tombstones.
        Nur für den Sync-Pfad."""
        return dict(self._data)

    def get(self, date_str):
        entry = self._data.get(date_str)
        if entry is None or entry.get("deleted"):
            return None
        return self._user_shape(entry)

    def save(self, date_str, start, end, pause=0):
        self._data[date_str] = {
            "start": start,
            "end": end,
            "pause": pause,
            "modified_at": _utc_now_iso(),
            "device_id": self.device_id,
            "deleted": False,
        }
        self._save_to_disk()

    def delete(self, date_str):
        # Tombstone: behält die Zeile mit deleted=true, damit der Sync ein
        # Delete gegen ein veraltetes Save eines anderen Geräts durchsetzen kann.
        self._data[date_str] = {
            "start": None,
            "end": None,
            "pause": None,
            "modified_at": _utc_now_iso(),
            "device_id": self.device_id,
            "deleted": True,
        }
        self._save_to_disk()

    def apply_merge(self, merged_entries):
        """Ersetzt den kompletten Storage-Stand durch das Merge-Ergebnis.
        merged_entries: {date: {start, end, pause, modified_at, device_id, deleted}}"""
        self._data = dict(merged_entries)
        self._save_to_disk()
```

- [ ] **Step 4: Tests ausführen, alle grün**

```
pytest tests/test_storage.py -v
```

Erwartet: Alle Tests PASS, inkl. der beiden neuen. Der bestehende `test_delete_entry` ist auch grün, weil `get_all()` Tombstones filtert.

- [ ] **Step 5: Commit**

```
git add src/storage.py tests/test_storage.py
git commit -m "feat(storage): add per-entry metadata and tombstone support"
```

---

### Task 1.2: Storage — Migration für Legacy-Einträge

**Files:**
- Modify: `src/storage.py`
- Create: `tests/test_storage_migration.py`

- [ ] **Step 1: Failing test schreiben**

Neue Datei `tests/test_storage_migration.py`:

```python
import json
import os

import pytest

from src.storage import Storage


def _write_legacy_json(tmp_path, payload):
    path = tmp_path / "legacy.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f)
    return str(path)


def test_legacy_entries_get_metadata_on_load(tmp_path):
    """Eintrag ohne modified_at/device_id/deleted wird beim Laden migriert."""
    path = _write_legacy_json(tmp_path, {
        "2026-03-23": {"start": "08:00", "end": "16:30", "pause": 30},
    })
    storage = Storage(path, device_id="dev-1")
    raw = storage.get_all_raw()
    entry = raw["2026-03-23"]
    assert entry["start"] == "08:00"
    assert entry["end"] == "16:30"
    assert entry["pause"] == 30
    assert entry["device_id"] == "dev-1"
    assert entry["deleted"] is False
    assert entry["modified_at"].endswith("Z")


def test_legacy_modified_at_uses_file_mtime(tmp_path):
    """Migrationszeitpunkt = mtime der Legacy-Datei (best lower bound)."""
    path = _write_legacy_json(tmp_path, {
        "2026-03-23": {"start": "08:00", "end": "16:30", "pause": 30},
    })
    # mtime künstlich setzen
    fixed_mtime = 1_700_000_000  # 2023-11-14T22:13:20Z
    os.utime(path, (fixed_mtime, fixed_mtime))
    storage = Storage(path, device_id="dev-1")
    entry = storage.get_all_raw()["2026-03-23"]
    assert entry["modified_at"] == "2023-11-14T22:13:20Z"


def test_user_facing_get_all_after_migration_unchanged(tmp_path):
    """UI-Code sieht nach Migration weiter die schmale Shape."""
    path = _write_legacy_json(tmp_path, {
        "2026-03-23": {"start": "08:00", "end": "16:30", "pause": 30},
    })
    storage = Storage(path, device_id="dev-1")
    assert storage.get_all() == {
        "2026-03-23": {"start": "08:00", "end": "16:30", "pause": 30}
    }


def test_partially_migrated_entries_not_touched(tmp_path):
    """Wenn modified_at schon da ist (z.B. Sync hat geschrieben), keine Re-Migration."""
    path = _write_legacy_json(tmp_path, {
        "2026-03-23": {
            "start": "08:00", "end": "16:30", "pause": 30,
            "modified_at": "2026-05-01T10:00:00Z",
            "device_id": "other-device",
            "deleted": False,
        },
    })
    storage = Storage(path, device_id="dev-1")
    entry = storage.get_all_raw()["2026-03-23"]
    assert entry["modified_at"] == "2026-05-01T10:00:00Z"
    assert entry["device_id"] == "other-device"
```

- [ ] **Step 2: Tests ausführen, Fail bestätigen**

```
pytest tests/test_storage_migration.py -v
```

Erwartet: Mehrere FAIL — Migration ist noch nicht implementiert.

- [ ] **Step 3: Migration in `_load` einbauen**

In `src/storage.py`: Ergänze nach dem `self._data = json.load(f)`-Block einen Migrationsschritt. Ersetze die `_load`-Methode komplett:

```python
    def _load(self):
        if not os.path.exists(self.filepath):
            return
        try:
            with open(self.filepath, "r", encoding="utf-8") as f:
                self._data = json.load(f)
        except (json.JSONDecodeError, ValueError):
            stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
            os.replace(self.filepath, f"{self.filepath}.corrupt-{stamp}")
            self._data = {}
            return
        self._migrate_legacy_entries()

    def _migrate_legacy_entries(self):
        """Spendet alten Einträgen ohne modified_at/device_id/deleted die
        Sync-Metadaten. Idempotent: Einträge mit modified_at bleiben unberührt.
        modified_at wird aus der File-mtime abgeleitet (best lower bound)."""
        try:
            mtime = os.path.getmtime(self.filepath)
        except OSError:
            mtime = None
        fallback_modified_at = (
            datetime.datetime.fromtimestamp(mtime, datetime.timezone.utc)
            .strftime("%Y-%m-%dT%H:%M:%SZ")
            if mtime is not None
            else _utc_now_iso()
        )
        for date, entry in list(self._data.items()):
            if not isinstance(entry, dict):
                continue
            if "modified_at" in entry:
                continue
            entry.setdefault("pause", 0)
            entry["modified_at"] = fallback_modified_at
            entry["device_id"] = self.device_id
            entry["deleted"] = False
```

- [ ] **Step 4: Tests ausführen, alle grün**

```
pytest tests/test_storage_migration.py tests/test_storage.py -v
```

Erwartet: Alle PASS.

- [ ] **Step 5: Commit**

```
git add src/storage.py tests/test_storage_migration.py
git commit -m "feat(storage): migrate legacy entries to add sync metadata"
```

---

### Task 1.3: Settings — Neue Sync-Meta-Keys

**Files:**
- Modify: `src/settings.py`
- Modify: `tests/test_settings.py`

- [ ] **Step 1: Failing test schreiben**

In `tests/test_settings.py` anhängen:

```python
# --- Sync metadata (1.12.0) ---


def test_sync_enabled_default_is_false(tmp_settings):
    assert tmp_settings.get("sync_enabled") is False


def test_device_id_default_is_empty(tmp_settings):
    """device_id wird beim ersten App-Start in main.py befüllt, nicht hier."""
    assert tmp_settings.get("device_id") == ""


def test_last_pull_at_default_is_empty(tmp_settings):
    assert tmp_settings.get("last_pull_at") == ""


def test_drive_etag_default_is_empty(tmp_settings):
    assert tmp_settings.get("drive_etag") == ""


def test_sync_meta_persists(tmp_path):
    path = str(tmp_path / "settings.json")
    s1 = Settings(path)
    s1.set("sync_enabled", True)
    s1.set("device_id", "dev-uuid")
    s1.set("last_pull_at", "2026-05-14T10:00:00Z")
    s1.set("drive_etag", "etag-123")
    s2 = Settings(path)
    assert s2.get("sync_enabled") is True
    assert s2.get("device_id") == "dev-uuid"
    assert s2.get("last_pull_at") == "2026-05-14T10:00:00Z"
    assert s2.get("drive_etag") == "etag-123"
```

- [ ] **Step 2: Tests ausführen, Fail bestätigen**

```
pytest tests/test_settings.py -k "sync_enabled_default or device_id_default or last_pull_at_default or drive_etag_default or sync_meta_persists" -v
```

Erwartet: FAIL — Defaults fehlen.

- [ ] **Step 3: Defaults in `src/settings.py` ergänzen**

In `src/settings.py` im `DEFAULTS`-Dict (nach `"show_weekend": True,`) einfügen:

```python
    "sync_enabled": False,
    "device_id": "",
    "last_pull_at": "",
    "drive_etag": "",
```

- [ ] **Step 4: Tests ausführen, alle grün**

```
pytest tests/test_settings.py -v
```

Erwartet: Alle PASS.

- [ ] **Step 5: Commit**

```
git add src/settings.py tests/test_settings.py
git commit -m "feat(settings): add sync metadata keys"
```

---

### Task 1.4: Settings — `set_synced()` mit Per-Field-Metadaten

**Files:**
- Modify: `src/settings.py`
- Modify: `tests/test_settings.py`

- [ ] **Step 1: Failing test schreiben**

In `tests/test_settings.py` anhängen:

```python
def test_set_synced_records_metadata(tmp_path):
    """set_synced(key, value) speichert value im flachen Dict und führt
    Per-Field-Metadaten in _synced_meta."""
    path = str(tmp_path / "settings.json")
    s = Settings(path)
    s.device_id_for_sync = "dev-1"  # Wird von main.py gesetzt
    s.set_synced("recipient", "a@b.de")
    assert s.get("recipient") == "a@b.de"
    meta = s.get_synced_doc()
    assert meta["recipient"]["value"] == "a@b.de"
    assert meta["recipient"]["device_id"] == "dev-1"
    assert meta["recipient"]["modified_at"].endswith("Z")


def test_set_synced_persists_metadata_across_reload(tmp_path):
    path = str(tmp_path / "settings.json")
    s1 = Settings(path)
    s1.device_id_for_sync = "dev-1"
    s1.set_synced("name", "Max Mustermann")
    s2 = Settings(path)
    meta = s2.get_synced_doc()
    assert meta["name"]["value"] == "Max Mustermann"
    assert meta["name"]["device_id"] == "dev-1"


def test_apply_synced_overwrites_value_and_meta(tmp_path):
    """apply_synced(merged_settings) wird vom Sync-Pfad genutzt: setzt sowohl
    flat value als auch _synced_meta-Eintrag."""
    path = str(tmp_path / "settings.json")
    s = Settings(path)
    s.apply_synced({
        "recipient": {"value": "remote@x.de", "modified_at": "2026-05-14T10:00:00Z",
                       "device_id": "other-dev"},
    })
    assert s.get("recipient") == "remote@x.de"
    assert s.get_synced_doc()["recipient"]["device_id"] == "other-dev"


def test_get_synced_doc_empty_when_nothing_set(tmp_settings):
    assert tmp_settings.get_synced_doc() == {}
```

- [ ] **Step 2: Tests ausführen, Fail bestätigen**

```
pytest tests/test_settings.py -k "set_synced or apply_synced or get_synced_doc" -v
```

Erwartet: FAIL — Methoden fehlen.

- [ ] **Step 3: `src/settings.py` erweitern**

In `src/settings.py`:

(a) Top-Level neue Konstante nach `WEEKDAY_KEYS`:

```python
SYNCED_SETTING_KEYS = (
    "recipient", "name", "hourly_rate",
    "mail_subject", "mail_greeting", "mail_content", "mail_closing",
)
```

(b) Import oben ergänzen:

```python
import datetime
```

(c) Helper-Funktion nach `_migrate_legacy_default_times`:

```python
def _utc_now_iso():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
```

(d) Im `Settings.__init__` nach `self._data = dict(DEFAULTS)`:

```python
        self._synced_meta = {}   # {key: {"modified_at": ..., "device_id": ...}}
        self.device_id_for_sync = ""  # wird von main.py auf settings.device_id gesetzt
```

(e) In `_load`, vor `_migrate_legacy_default_times(loaded)`:

```python
        # _synced_meta aus der Datei extrahieren, sonst landet es als unbekannter Key
        synced_meta_raw = loaded.pop("_synced_meta", None)
        if isinstance(synced_meta_raw, dict):
            for k, v in synced_meta_raw.items():
                if not isinstance(v, dict):
                    continue
                if "modified_at" in v and "device_id" in v:
                    self._synced_meta[k] = {
                        "modified_at": str(v["modified_at"]),
                        "device_id": str(v["device_id"]),
                    }
```

(f) In `_save_to_disk` vor `json.dump`:

```python
        payload = dict(self._data)
        if self._synced_meta:
            payload["_synced_meta"] = self._synced_meta
        tmp = self.filepath + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
```

(Ersetzt die bestehende `json.dump(self._data, ...)`-Zeile — siehe ganzer ersetzter Block unten.)

Ersetze den **kompletten** `_save_to_disk`:

```python
    def _save_to_disk(self):
        # Atomic write: temp file + replace, damit ein Crash mid-write
        # kein halb geschriebenes settings.json hinterlässt.
        payload = dict(self._data)
        if self._synced_meta:
            payload["_synced_meta"] = self._synced_meta
        tmp = self.filepath + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
        try:
            os.replace(tmp, self.filepath)
        except OSError:
            if os.path.exists(tmp):
                os.remove(tmp)
            raise
```

(g) Neue Methoden am Ende der `Settings`-Klasse:

```python
    def set_synced(self, key, value):
        """Setzt einen whitelisted Sync-Key und stempelt Per-Field-Metadaten.
        Außerhalb der Whitelist verhält sich wie ein normales set()."""
        if key not in SYNCED_SETTING_KEYS:
            self.set(key, value)
            return
        self._data[key] = value
        self._synced_meta[key] = {
            "modified_at": _utc_now_iso(),
            "device_id": self.device_id_for_sync,
        }
        self._save_to_disk()

    def get_synced_doc(self):
        """{key: {value, modified_at, device_id}} — Eingabe für den Sync-Merge.
        Nur Keys mit vorhandener Metadaten-Spur werden zurückgegeben."""
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

- [ ] **Step 4: Tests ausführen, alle grün**

```
pytest tests/test_settings.py -v
```

Erwartet: Alle PASS.

- [ ] **Step 5: Commit**

```
git add src/settings.py tests/test_settings.py
git commit -m "feat(settings): add set_synced/apply_synced for sync-tracked fields"
```

---

### Task 1.5: ConflictsStore — neues Modul

**Files:**
- Create: `src/conflicts_store.py`
- Create: `tests/test_conflicts_store.py`

- [ ] **Step 1: Failing test schreiben**

Neue Datei `tests/test_conflicts_store.py`:

```python
import json

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


def test_corrupt_file_is_quarantined(tmp_path):
    path = tmp_path / "conflicts.json"
    path.write_text("not json{{{", encoding="utf-8")
    store = ConflictsStore(str(path))
    assert store.get_all() == []
    quarantined = list(tmp_path.glob("conflicts.json.corrupt-*"))
    assert len(quarantined) == 1


def test_count_unresolved(tmp_conflicts):
    tmp_conflicts.save_all([
        {"id": "c-1", "resolved": False},
        {"id": "c-2", "resolved": True},
        {"id": "c-3", "resolved": False},
    ])
    assert tmp_conflicts.count_unresolved() == 2
```

- [ ] **Step 2: Tests ausführen, Fail bestätigen**

```
pytest tests/test_conflicts_store.py -v
```

Erwartet: FAIL — Modul existiert nicht.

- [ ] **Step 3: `src/conflicts_store.py` schreiben**

Neue Datei `src/conflicts_store.py`:

```python
import datetime
import json
import os


class ConflictsStore:
    """JSON-Persistenz für die lokale Konflikt-Liste. Spiegelt die conflicts-Liste
    aus dem Sync-File, damit der ConflictsDialog ohne Netz funktioniert."""

    def __init__(self, filepath="conflicts.json"):
        self.filepath = filepath
        self._conflicts = []
        self._load()

    def _load(self):
        if not os.path.exists(self.filepath):
            return
        try:
            with open(self.filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, ValueError):
            stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
            os.replace(self.filepath, f"{self.filepath}.corrupt-{stamp}")
            return
        if isinstance(data, list):
            self._conflicts = data

    def _save_to_disk(self):
        tmp = self.filepath + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self._conflicts, f, indent=2, ensure_ascii=False)
        try:
            os.replace(tmp, self.filepath)
        except OSError:
            if os.path.exists(tmp):
                os.remove(tmp)
            raise

    def get_all(self):
        return list(self._conflicts)

    def save_all(self, conflicts):
        self._conflicts = list(conflicts)
        self._save_to_disk()

    def count_unresolved(self):
        return sum(1 for c in self._conflicts if not c.get("resolved"))
```

- [ ] **Step 4: Tests ausführen, alle grün**

```
pytest tests/test_conflicts_store.py -v
```

Erwartet: Alle PASS.

- [ ] **Step 5: Commit**

```
git add src/conflicts_store.py tests/test_conflicts_store.py
git commit -m "feat: add ConflictsStore for local conflict persistence"
```

---

## Phase 2: Sync Engine (`src/sync.py`)

Pure Python, keine I/O, keine Drive-Calls — vollständig unit-testbar. Diese Phase liefert die komplette Merge-Logik.

### Task 2.1: `sync.py` Grundgerüst + `_merge_one` Helper

**Files:**
- Create: `src/sync.py`
- Create: `tests/test_sync.py`

- [ ] **Step 1: Failing test schreiben**

Neue Datei `tests/test_sync.py`:

```python
from src.sync import _merge_one


def _e(start, end, pause, modified_at, device_id="d", deleted=False):
    return {
        "start": start, "end": end, "pause": pause,
        "modified_at": modified_at, "device_id": device_id, "deleted": deleted,
    }


def test_merge_one_local_only_keeps_local():
    local = _e("08:00", "16:00", 30, "2026-05-14T10:00:00Z")
    merged, conflict = _merge_one(local, None, "2026-05-13T00:00:00Z")
    assert merged is local
    assert conflict is None


def test_merge_one_remote_only_keeps_remote():
    remote = _e("09:00", "17:00", 30, "2026-05-14T10:00:00Z")
    merged, conflict = _merge_one(None, remote, "2026-05-13T00:00:00Z")
    assert merged is remote
    assert conflict is None


def test_merge_one_equal_values_no_conflict():
    e1 = _e("08:00", "16:00", 30, "2026-05-14T10:00:00Z")
    e2 = _e("08:00", "16:00", 30, "2026-05-14T11:00:00Z")
    merged, conflict = _merge_one(e1, e2, "2026-05-13T00:00:00Z")
    assert conflict is None
    # bei gleichen Values darf irgendeine Seite gewinnen, aber kein Conflict
    assert merged["start"] == "08:00"


def test_merge_one_only_local_changed_no_conflict():
    """remote.modified_at < last_pull_at: nur local hat sich geändert, kein Conflict."""
    local = _e("09:00", "17:00", 30, "2026-05-14T10:00:00Z")  # changed after last_pull
    remote = _e("08:00", "16:00", 30, "2026-05-10T00:00:00Z")  # before last_pull
    merged, conflict = _merge_one(local, remote, "2026-05-13T00:00:00Z")
    assert conflict is None
    assert merged is local


def test_merge_one_only_remote_changed_no_conflict():
    local = _e("08:00", "16:00", 30, "2026-05-10T00:00:00Z")
    remote = _e("09:00", "17:00", 30, "2026-05-14T10:00:00Z")
    merged, conflict = _merge_one(local, remote, "2026-05-13T00:00:00Z")
    assert conflict is None
    assert merged is remote


def test_merge_one_both_changed_creates_conflict():
    local = _e("08:00", "16:00", 30, "2026-05-14T10:00:00Z", device_id="A")
    remote = _e("09:00", "17:00", 30, "2026-05-14T11:00:00Z", device_id="B")
    merged, conflict = _merge_one(local, remote, "2026-05-13T00:00:00Z")
    assert conflict is not None
    assert conflict["kind"] == "entry"
    # provisorischer Wert = jüngerer (LWW)
    assert merged is remote
    # Beide Kandidaten im Conflict
    candidate_devices = sorted(c["device_id"] for c in conflict["candidates"])
    assert candidate_devices == ["A", "B"]
```

- [ ] **Step 2: Tests ausführen, Fail bestätigen**

```
pytest tests/test_sync.py -v
```

Erwartet: ImportError oder FAIL — Modul fehlt.

- [ ] **Step 3: `src/sync.py` mit `_merge_one` schreiben**

Neue Datei `src/sync.py`:

```python
"""Sync-Engine: pure Funktionen ohne I/O. Drive-Calls leben in src/drive.py.

Doc-Struktur (Sync-File und Zwischenformate):
{
  "schema_version": 1,
  "entries":   {date: {start, end, pause, modified_at, device_id, deleted}},
  "settings":  {key:  {value, modified_at, device_id}},
  "conflicts": [{id, kind, key, candidates, detected_at,
                 resolved, resolution, resolved_at, resolved_by}]
}
"""

import datetime
import uuid


SCHEMA_VERSION = 1

SYNCED_SETTING_KEYS = (
    "recipient", "name", "hourly_rate",
    "mail_subject", "mail_greeting", "mail_content", "mail_closing",
)


def _utc_now_iso():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _values_equal_entry(a, b):
    return (a.get("start") == b.get("start")
            and a.get("end") == b.get("end")
            and a.get("pause") == b.get("pause")
            and bool(a.get("deleted")) == bool(b.get("deleted")))


def _values_equal_setting(a, b):
    return a.get("value") == b.get("value")


def _merge_one(local, remote, last_pull_at, equal_fn=_values_equal_entry, kind="entry", key=None):
    """LWW-Merge eines einzelnen Werts.

    Returns: (winner_dict, conflict_or_none)

    - Wenn nur eine Seite vorhanden ist → diese Seite gewinnt, kein Conflict.
    - Werte gleich → eine Seite gewinnt, kein Conflict.
    - Werte unterschiedlich, beide modified_at > last_pull_at → Conflict
      mit beiden Kandidaten, provisorischer Wert ist der jüngere (LWW).
    - Werte unterschiedlich, nur eine Seite seit last_pull_at geändert →
      diese Seite gewinnt (kein Conflict).
    """
    if local is None and remote is None:
        return (None, None)
    if local is None:
        return (remote, None)
    if remote is None:
        return (local, None)
    if equal_fn(local, remote):
        # jüngerer modified_at gewinnt — bei tie egal
        winner = remote if remote["modified_at"] >= local["modified_at"] else local
        return (winner, None)

    local_changed = local["modified_at"] > last_pull_at
    remote_changed = remote["modified_at"] > last_pull_at

    winner = remote if remote["modified_at"] >= local["modified_at"] else local

    if local_changed and remote_changed:
        conflict = {
            "id": str(uuid.uuid4()),
            "kind": kind,
            "key": key,
            "candidates": [_strip_for_candidate(local), _strip_for_candidate(remote)],
            "detected_at": _utc_now_iso(),
            "resolved": False,
            "resolution": None,
            "resolved_at": None,
            "resolved_by": None,
        }
        return (winner, conflict)
    return (winner, None)


def _strip_for_candidate(item):
    """Reduziert ein Entry/Setting auf das, was im conflict.candidates landen soll."""
    return {k: v for k, v in item.items()}
```

- [ ] **Step 4: Tests ausführen, alle grün**

```
pytest tests/test_sync.py -v
```

Erwartet: Alle PASS.

- [ ] **Step 5: Commit**

```
git add src/sync.py tests/test_sync.py
git commit -m "feat(sync): add _merge_one core LWW helper"
```

---

### Task 2.2: `sync.py` — Tombstone-Handling im Merge

**Files:**
- Modify: `src/sync.py`
- Modify: `tests/test_sync.py`

- [ ] **Step 1: Failing test schreiben**

In `tests/test_sync.py` anhängen:

```python
def test_merge_one_tombstone_wins_when_only_remote_changed():
    local = _e("08:00", "16:00", 30, "2026-05-01T10:00:00Z")  # before last_pull
    remote = _e(None, None, None, "2026-05-14T10:00:00Z", deleted=True)
    merged, conflict = _merge_one(local, remote, "2026-05-10T00:00:00Z")
    assert merged is remote
    assert merged["deleted"] is True
    assert conflict is None


def test_merge_one_tombstone_vs_edit_creates_conflict_when_both_changed():
    local = _e("08:00", "16:00", 30, "2026-05-14T09:00:00Z")
    remote = _e(None, None, None, "2026-05-14T10:00:00Z", deleted=True)
    merged, conflict = _merge_one(local, remote, "2026-05-13T00:00:00Z")
    assert conflict is not None
    # LWW: jüngerer gewinnt provisorisch
    assert merged is remote
```

- [ ] **Step 2: Tests ausführen, Fail bestätigen**

```
pytest tests/test_sync.py::test_merge_one_tombstone_wins_when_only_remote_changed tests/test_sync.py::test_merge_one_tombstone_vs_edit_creates_conflict_when_both_changed -v
```

Erwartet: PASS — `_merge_one` und `_values_equal_entry` behandeln den `deleted`-Flag schon korrekt (verschieden = nicht equal).

- [ ] **Step 3: (Kein Code-Change nötig — Tests dokumentieren erwartetes Verhalten)**

Falls Tests fehlschlagen: Debug. Sonst weiter.

- [ ] **Step 4: Commit**

```
git add tests/test_sync.py
git commit -m "test(sync): document tombstone merge behavior"
```

---

### Task 2.3: `sync.py` — `merge()` für Entries

**Files:**
- Modify: `src/sync.py`
- Modify: `tests/test_sync.py`

- [ ] **Step 1: Failing test schreiben**

In `tests/test_sync.py` anhängen:

```python
from src.sync import merge


def _doc(entries=None, settings=None, conflicts=None):
    return {
        "schema_version": 1,
        "entries": entries or {},
        "settings": settings or {},
        "conflicts": conflicts or [],
    }


def test_merge_empty_docs_returns_empty():
    merged = merge(_doc(), _doc(), "2026-05-13T00:00:00Z")
    assert merged["entries"] == {}
    assert merged["settings"] == {}
    assert merged["conflicts"] == []


def test_merge_local_only_entry_preserved():
    local = _doc(entries={"2026-05-14": _e("08:00", "16:00", 30, "2026-05-14T10:00:00Z")})
    merged = merge(local, _doc(), "2026-05-13T00:00:00Z")
    assert "2026-05-14" in merged["entries"]


def test_merge_remote_only_entry_added():
    remote = _doc(entries={"2026-05-14": _e("09:00", "17:00", 30, "2026-05-14T10:00:00Z")})
    merged = merge(_doc(), remote, "2026-05-13T00:00:00Z")
    assert merged["entries"]["2026-05-14"]["start"] == "09:00"


def test_merge_conflict_creates_conflict_object():
    local = _doc(entries={"D": _e("08:00", "16:00", 30, "2026-05-14T09:00:00Z", "A")})
    remote = _doc(entries={"D": _e("09:00", "17:00", 30, "2026-05-14T10:00:00Z", "B")})
    merged = merge(local, remote, "2026-05-13T00:00:00Z")
    assert len(merged["conflicts"]) == 1
    c = merged["conflicts"][0]
    assert c["kind"] == "entry"
    assert c["key"] == "D"
    assert c["resolved"] is False


def test_merge_no_conflict_when_only_one_side_changed():
    local = _doc(entries={"D": _e("08:00", "16:00", 30, "2026-05-01T09:00:00Z")})
    remote = _doc(entries={"D": _e("09:00", "17:00", 30, "2026-05-14T10:00:00Z")})
    merged = merge(local, remote, "2026-05-10T00:00:00Z")
    assert merged["conflicts"] == []
    assert merged["entries"]["D"]["start"] == "09:00"
```

- [ ] **Step 2: Tests ausführen, Fail bestätigen**

```
pytest tests/test_sync.py -v
```

Erwartet: FAIL — `merge()` fehlt.

- [ ] **Step 3: `merge()` in `src/sync.py` ergänzen**

In `src/sync.py` am Ende anhängen:

```python
def merge(local, remote, last_pull_at):
    """Hauptfunktion: erwartet zwei Sync-Docs, liefert das gemergte Doc."""
    merged = {
        "schema_version": SCHEMA_VERSION,
        "entries": {},
        "settings": {},
        "conflicts": [],
    }
    new_conflicts = []

    # Entries
    all_keys = set(local.get("entries", {}).keys()) | set(remote.get("entries", {}).keys())
    for key in all_keys:
        l = local.get("entries", {}).get(key)
        r = remote.get("entries", {}).get(key)
        winner, conflict = _merge_one(l, r, last_pull_at,
                                       equal_fn=_values_equal_entry, kind="entry", key=key)
        if winner is not None:
            merged["entries"][key] = winner
        if conflict is not None:
            new_conflicts.append(conflict)

    merged["conflicts"] = new_conflicts
    return merged
```

- [ ] **Step 4: Tests ausführen, grün**

```
pytest tests/test_sync.py -v
```

Erwartet: Alle PASS.

- [ ] **Step 5: Commit**

```
git add src/sync.py tests/test_sync.py
git commit -m "feat(sync): merge entries with LWW and conflict detection"
```

---

### Task 2.4: `sync.py` — `merge()` für Settings (Whitelist)

**Files:**
- Modify: `src/sync.py`
- Modify: `tests/test_sync.py`

- [ ] **Step 1: Failing test schreiben**

In `tests/test_sync.py` anhängen:

```python
def _s(value, modified_at, device_id="d"):
    return {"value": value, "modified_at": modified_at, "device_id": device_id}


def test_merge_setting_local_only():
    local = _doc(settings={"recipient": _s("a@b.de", "2026-05-14T10:00:00Z")})
    merged = merge(local, _doc(), "2026-05-13T00:00:00Z")
    assert merged["settings"]["recipient"]["value"] == "a@b.de"


def test_merge_setting_conflict_creates_setting_conflict():
    local = _doc(settings={
        "recipient": _s("a@b.de", "2026-05-14T09:00:00Z", "A"),
    })
    remote = _doc(settings={
        "recipient": _s("x@y.de", "2026-05-14T10:00:00Z", "B"),
    })
    merged = merge(local, remote, "2026-05-13T00:00:00Z")
    assert len(merged["conflicts"]) == 1
    assert merged["conflicts"][0]["kind"] == "setting"
    assert merged["conflicts"][0]["key"] == "recipient"


def test_merge_setting_ignores_non_whitelisted():
    """Settings außerhalb der SYNCED_SETTING_KEYS werden im Merge ignoriert."""
    local = _doc(settings={"autostart": _s(True, "2026-05-14T10:00:00Z")})
    remote = _doc(settings={"autostart": _s(False, "2026-05-14T11:00:00Z")})
    merged = merge(local, remote, "2026-05-13T00:00:00Z")
    assert "autostart" not in merged["settings"]
```

- [ ] **Step 2: Tests ausführen, Fail bestätigen**

```
pytest tests/test_sync.py -k "merge_setting" -v
```

Erwartet: FAIL — `merge()` ignoriert Settings.

- [ ] **Step 3: `merge()` um Settings-Logik erweitern**

In `src/sync.py` in `merge()` vor `merged["conflicts"] = new_conflicts` einfügen:

```python
    # Settings (Whitelist)
    for key in SYNCED_SETTING_KEYS:
        l = local.get("settings", {}).get(key)
        r = remote.get("settings", {}).get(key)
        winner, conflict = _merge_one(l, r, last_pull_at,
                                       equal_fn=_values_equal_setting, kind="setting", key=key)
        if winner is not None:
            merged["settings"][key] = winner
        if conflict is not None:
            new_conflicts.append(conflict)
```

- [ ] **Step 4: Tests ausführen, grün**

```
pytest tests/test_sync.py -v
```

Erwartet: Alle PASS.

- [ ] **Step 5: Commit**

```
git add src/sync.py tests/test_sync.py
git commit -m "feat(sync): merge whitelisted settings with conflict detection"
```

---

### Task 2.5: `sync.py` — Konflikt-Listen-Merge + Idempotenz

**Files:**
- Modify: `src/sync.py`
- Modify: `tests/test_sync.py`

- [ ] **Step 1: Failing test schreiben**

In `tests/test_sync.py` anhängen:

```python
def _conflict(id_, key="D", kind="entry", resolved=False,
              resolution=None, resolved_at=None, resolved_by=None,
              candidates=None):
    return {
        "id": id_, "kind": kind, "key": key,
        "candidates": candidates or [],
        "detected_at": "2026-05-14T10:00:00Z",
        "resolved": resolved, "resolution": resolution,
        "resolved_at": resolved_at, "resolved_by": resolved_by,
    }


def test_merge_conflicts_union_by_id():
    local = _doc(conflicts=[_conflict("c-1"), _conflict("c-2")])
    remote = _doc(conflicts=[_conflict("c-2"), _conflict("c-3")])
    merged = merge(local, remote, "2026-05-13T00:00:00Z")
    ids = sorted(c["id"] for c in merged["conflicts"])
    assert ids == ["c-1", "c-2", "c-3"]


def test_merge_conflicts_resolved_wins_over_unresolved():
    """Wenn dasselbe Konflikt-ID auf einer Seite resolved ist, gilt resolved."""
    resolved = _conflict("c-1", resolved=True,
                         resolution={"start": "08:00", "end": "16:00", "pause": 30},
                         resolved_at="2026-05-14T11:00:00Z",
                         resolved_by="A")
    unresolved = _conflict("c-1", resolved=False)
    merged = merge(_doc(conflicts=[resolved]), _doc(conflicts=[unresolved]),
                    "2026-05-13T00:00:00Z")
    assert len(merged["conflicts"]) == 1
    assert merged["conflicts"][0]["resolved"] is True


def test_merge_conflicts_lww_on_resolved_at_when_both_resolved():
    c_a = _conflict("c-1", resolved=True,
                    resolution={"start": "08:00"}, resolved_at="2026-05-14T11:00:00Z",
                    resolved_by="A")
    c_b = _conflict("c-1", resolved=True,
                    resolution={"start": "09:00"}, resolved_at="2026-05-14T12:00:00Z",
                    resolved_by="B")
    merged = merge(_doc(conflicts=[c_a]), _doc(conflicts=[c_b]), "2026-05-13T00:00:00Z")
    assert len(merged["conflicts"]) == 1
    assert merged["conflicts"][0]["resolved_by"] == "B"


def test_merge_idempotent_does_not_duplicate_unresolved_conflict():
    """Bei wiederholtem merge mit denselben Inputs entsteht kein zweiter Eintrag."""
    local = _doc(
        entries={"D": _e("08:00", "16:00", 30, "2026-05-14T09:00:00Z", "A")},
        conflicts=[_conflict("c-1", key="D",
                              candidates=[_e("08:00", "16:00", 30, "2026-05-14T09:00:00Z", "A"),
                                          _e("09:00", "17:00", 30, "2026-05-14T10:00:00Z", "B")])],
    )
    remote = _doc(entries={"D": _e("09:00", "17:00", 30, "2026-05-14T10:00:00Z", "B")})
    merged = merge(local, remote, "2026-05-13T00:00:00Z")
    # Conflict für D existiert schon → kein neuer
    entry_conflicts_for_d = [c for c in merged["conflicts"]
                              if c["kind"] == "entry" and c["key"] == "D"]
    assert len(entry_conflicts_for_d) == 1
    assert entry_conflicts_for_d[0]["id"] == "c-1"
```

- [ ] **Step 2: Tests ausführen, Fail bestätigen**

```
pytest tests/test_sync.py -k "merge_conflicts or merge_idempotent" -v
```

Erwartet: FAIL — Konflikt-Listen-Merge fehlt.

- [ ] **Step 3: Konflikt-Listen-Merge implementieren**

In `src/sync.py`:

(a) Helper-Funktion vor `merge()`:

```python
def _merge_conflict_pair(a, b):
    """LWW auf resolved_at, resolved beats unresolved."""
    if a.get("resolved") and not b.get("resolved"):
        return a
    if b.get("resolved") and not a.get("resolved"):
        return b
    if a.get("resolved") and b.get("resolved"):
        return a if (a.get("resolved_at") or "") >= (b.get("resolved_at") or "") else b
    return a  # beide unresolved — ID-Match heißt dasselbe Detection-Event


def _equivalent_unresolved_exists(existing, new_conflict):
    """Dedupe: existiert bereits ein unresolved Konflikt mit gleichem
    (kind, key, Kandidaten-Set)?"""
    if new_conflict.get("resolved"):
        return False
    new_keys = _candidate_signatures(new_conflict["candidates"])
    for c in existing:
        if c.get("resolved"):
            continue
        if c["kind"] != new_conflict["kind"] or c["key"] != new_conflict["key"]:
            continue
        if _candidate_signatures(c["candidates"]) == new_keys:
            return True
    return False


def _candidate_signatures(candidates):
    """Sortiertes Tuple aus (modified_at, device_id) — als Set-Vergleichsbasis."""
    return tuple(sorted((c.get("modified_at"), c.get("device_id")) for c in candidates))
```

(b) `merge()` umschreiben — ersetze die komplette Funktion:

```python
def merge(local, remote, last_pull_at):
    merged = {
        "schema_version": SCHEMA_VERSION,
        "entries": {},
        "settings": {},
        "conflicts": [],
    }
    new_conflicts = []

    # Entries
    all_entry_keys = set(local.get("entries", {}).keys()) | set(remote.get("entries", {}).keys())
    for key in all_entry_keys:
        l = local.get("entries", {}).get(key)
        r = remote.get("entries", {}).get(key)
        winner, conflict = _merge_one(l, r, last_pull_at,
                                       equal_fn=_values_equal_entry, kind="entry", key=key)
        if winner is not None:
            merged["entries"][key] = winner
        if conflict is not None:
            new_conflicts.append(conflict)

    # Settings (Whitelist)
    for key in SYNCED_SETTING_KEYS:
        l = local.get("settings", {}).get(key)
        r = remote.get("settings", {}).get(key)
        winner, conflict = _merge_one(l, r, last_pull_at,
                                       equal_fn=_values_equal_setting, kind="setting", key=key)
        if winner is not None:
            merged["settings"][key] = winner
        if conflict is not None:
            new_conflicts.append(conflict)

    # Conflicts-Liste: Union by ID
    by_id = {}
    for c in local.get("conflicts", []) + remote.get("conflicts", []):
        cid = c["id"]
        if cid in by_id:
            by_id[cid] = _merge_conflict_pair(by_id[cid], c)
        else:
            by_id[cid] = c

    # Neu erkannte Konflikte dazu, mit Dedup
    existing = list(by_id.values())
    for c in new_conflicts:
        if not _equivalent_unresolved_exists(existing, c):
            by_id[c["id"]] = c
            existing.append(c)

    merged["conflicts"] = list(by_id.values())
    return merged
```

- [ ] **Step 4: Tests ausführen, grün**

```
pytest tests/test_sync.py -v
```

Erwartet: Alle PASS.

- [ ] **Step 5: Commit**

```
git add src/sync.py tests/test_sync.py
git commit -m "feat(sync): merge conflict list with union-by-id and dedup"
```

---

### Task 2.6: `sync.py` — Resolution-Propagation

**Files:**
- Modify: `src/sync.py`
- Modify: `tests/test_sync.py`

- [ ] **Step 1: Failing test schreiben**

In `tests/test_sync.py` anhängen:

```python
def test_merge_applies_resolved_conflict_to_entry():
    """Resolved Konflikt aktualisiert merged.entries auf die Resolution."""
    resolved = _conflict("c-1", key="D",
                         resolved=True,
                         resolution={"start": "10:00", "end": "18:00", "pause": 30},
                         resolved_at="2026-05-14T12:00:00Z",
                         resolved_by="A")
    local = _doc(
        entries={"D": _e("08:00", "16:00", 30, "2026-05-14T11:00:00Z")},
        conflicts=[resolved],
    )
    remote = _doc(entries={"D": _e("09:00", "17:00", 30, "2026-05-14T10:00:00Z")})
    merged = merge(local, remote, "2026-05-13T00:00:00Z")
    e = merged["entries"]["D"]
    assert e["start"] == "10:00"
    assert e["end"] == "18:00"
    assert e["modified_at"] == "2026-05-14T12:00:00Z"
    assert e["device_id"] == "A"
    assert e["deleted"] is False


def test_merge_applies_resolved_setting_conflict():
    resolved = _conflict("c-1", kind="setting", key="recipient",
                         resolved=True, resolution={"value": "final@x.de"},
                         resolved_at="2026-05-14T12:00:00Z", resolved_by="A")
    local = _doc(
        settings={"recipient": _s("a@b.de", "2026-05-14T09:00:00Z")},
        conflicts=[resolved],
    )
    merged = merge(local, _doc(), "2026-05-13T00:00:00Z")
    assert merged["settings"]["recipient"]["value"] == "final@x.de"
    assert merged["settings"]["recipient"]["device_id"] == "A"
```

- [ ] **Step 2: Tests ausführen, Fail bestätigen**

```
pytest tests/test_sync.py -k "merge_applies_resolved" -v
```

Erwartet: FAIL.

- [ ] **Step 3: Resolution-Apply-Schritt in `merge()`**

In `src/sync.py`, am Ende der `merge()`-Funktion vor `return merged` einfügen:

```python
    # Resolutions anwenden: jeder resolved Konflikt überschreibt entries/settings,
    # falls die Resolution jünger ist als der aktuelle merged-Wert.
    for c in merged["conflicts"]:
        if not c.get("resolved"):
            continue
        resolution = c.get("resolution") or {}
        resolved_at = c.get("resolved_at") or ""
        resolved_by = c.get("resolved_by") or ""
        if c["kind"] == "entry":
            current = merged["entries"].get(c["key"])
            if current is None or current["modified_at"] < resolved_at:
                merged["entries"][c["key"]] = {
                    "start": resolution.get("start"),
                    "end": resolution.get("end"),
                    "pause": resolution.get("pause", 0),
                    "modified_at": resolved_at,
                    "device_id": resolved_by,
                    "deleted": bool(resolution.get("deleted", False)),
                }
        elif c["kind"] == "setting":
            current = merged["settings"].get(c["key"])
            if current is None or current["modified_at"] < resolved_at:
                merged["settings"][c["key"]] = {
                    "value": resolution.get("value"),
                    "modified_at": resolved_at,
                    "device_id": resolved_by,
                }
```

- [ ] **Step 4: Tests ausführen, grün**

```
pytest tests/test_sync.py -v
```

Erwartet: Alle PASS.

- [ ] **Step 5: Commit**

```
git add src/sync.py tests/test_sync.py
git commit -m "feat(sync): propagate resolved conflicts into entries/settings"
```

---

### Task 2.7: `sync.py` — `build_local_doc` und `apply_merged_doc`

**Files:**
- Modify: `src/sync.py`
- Modify: `tests/test_sync.py`

- [ ] **Step 1: Failing test schreiben**

In `tests/test_sync.py` anhängen:

```python
import pytest

from src.conflicts_store import ConflictsStore
from src.settings import Settings
from src.storage import Storage
from src.sync import apply_merged_doc, build_local_doc


def test_build_local_doc_includes_storage_settings_conflicts(tmp_path):
    storage = Storage(str(tmp_path / "z.json"), device_id="A")
    storage.save("2026-05-14", "08:00", "16:00", 30)
    settings = Settings(str(tmp_path / "s.json"))
    settings.device_id_for_sync = "A"
    settings.set_synced("recipient", "a@b.de")
    conflicts = ConflictsStore(str(tmp_path / "c.json"))
    conflicts.save_all([{"id": "c-1", "kind": "entry", "key": "D", "resolved": False}])

    doc = build_local_doc(storage, settings, conflicts)
    assert "2026-05-14" in doc["entries"]
    assert doc["settings"]["recipient"]["value"] == "a@b.de"
    assert doc["conflicts"][0]["id"] == "c-1"
    assert doc["schema_version"] == 1


def test_round_trip_no_loss(tmp_path):
    storage = Storage(str(tmp_path / "z.json"), device_id="A")
    storage.save("2026-05-14", "08:00", "16:00", 30)
    settings = Settings(str(tmp_path / "s.json"))
    settings.device_id_for_sync = "A"
    settings.set_synced("name", "Max")
    conflicts = ConflictsStore(str(tmp_path / "c.json"))

    local = build_local_doc(storage, settings, conflicts)
    merged = merge(local, _doc(), "2025-01-01T00:00:00Z")
    apply_merged_doc(merged, storage, settings, conflicts)

    assert storage.get("2026-05-14") == {"start": "08:00", "end": "16:00", "pause": 30}
    assert settings.get("name") == "Max"
```

- [ ] **Step 2: Tests ausführen, Fail bestätigen**

```
pytest tests/test_sync.py -k "build_local_doc or round_trip" -v
```

Erwartet: FAIL.

- [ ] **Step 3: Adapter-Funktionen implementieren**

In `src/sync.py` ans Ende anhängen:

```python
def build_local_doc(storage, settings, conflicts_store):
    """Erzeugt das Sync-Doc-Format aus den lokalen Stores."""
    return {
        "schema_version": SCHEMA_VERSION,
        "entries": storage.get_all_raw(),
        "settings": settings.get_synced_doc(),
        "conflicts": conflicts_store.get_all(),
    }


def apply_merged_doc(merged_doc, storage, settings, conflicts_store):
    """Schreibt das Merge-Ergebnis zurück in die lokalen Stores."""
    storage.apply_merge(merged_doc.get("entries", {}))
    settings.apply_synced(merged_doc.get("settings", {}))
    conflicts_store.save_all(merged_doc.get("conflicts", []))
```

- [ ] **Step 4: Tests ausführen, grün**

```
pytest tests/test_sync.py -v
```

Erwartet: Alle PASS.

- [ ] **Step 5: Commit**

```
git add src/sync.py tests/test_sync.py
git commit -m "feat(sync): add build_local_doc and apply_merged_doc adapters"
```

---

### Task 2.8: `sync.py` — `resolve_conflict`

**Files:**
- Modify: `src/sync.py`
- Modify: `tests/test_sync.py`

- [ ] **Step 1: Failing test schreiben**

In `tests/test_sync.py` anhängen:

```python
from src.sync import resolve_conflict


def test_resolve_entry_conflict_updates_storage_and_marks_resolved(tmp_path):
    storage = Storage(str(tmp_path / "z.json"), device_id="A")
    settings = Settings(str(tmp_path / "s.json"))
    conflicts = ConflictsStore(str(tmp_path / "c.json"))
    conflicts.save_all([{
        "id": "c-1", "kind": "entry", "key": "2026-05-14",
        "candidates": [
            {"start": "08:00", "end": "16:00", "pause": 30,
             "modified_at": "2026-05-14T09:00:00Z", "device_id": "A", "deleted": False},
            {"start": "09:00", "end": "17:00", "pause": 30,
             "modified_at": "2026-05-14T10:00:00Z", "device_id": "B", "deleted": False},
        ],
        "detected_at": "2026-05-14T11:00:00Z",
        "resolved": False, "resolution": None,
        "resolved_at": None, "resolved_by": None,
    }])

    chosen = {"start": "09:00", "end": "17:00", "pause": 30}
    resolve_conflict("c-1", chosen, conflicts, storage, settings, device_id="A")

    # storage hat den Wert
    assert storage.get("2026-05-14") == {"start": "09:00", "end": "17:00", "pause": 30}
    # conflict ist resolved
    c = conflicts.get_all()[0]
    assert c["resolved"] is True
    assert c["resolution"] == chosen
    assert c["resolved_by"] == "A"
    assert c["resolved_at"].endswith("Z")


def test_resolve_setting_conflict_updates_settings(tmp_path):
    storage = Storage(str(tmp_path / "z.json"), device_id="A")
    settings = Settings(str(tmp_path / "s.json"))
    settings.device_id_for_sync = "A"
    conflicts = ConflictsStore(str(tmp_path / "c.json"))
    conflicts.save_all([{
        "id": "c-2", "kind": "setting", "key": "recipient",
        "candidates": [
            {"value": "a@b.de", "modified_at": "...", "device_id": "A"},
            {"value": "x@y.de", "modified_at": "...", "device_id": "B"},
        ],
        "detected_at": "...", "resolved": False, "resolution": None,
        "resolved_at": None, "resolved_by": None,
    }])
    resolve_conflict("c-2", {"value": "x@y.de"}, conflicts, storage, settings, device_id="A")
    assert settings.get("recipient") == "x@y.de"
    assert conflicts.get_all()[0]["resolved"] is True


def test_resolve_nonexistent_conflict_raises(tmp_path):
    storage = Storage(str(tmp_path / "z.json"), device_id="A")
    settings = Settings(str(tmp_path / "s.json"))
    conflicts = ConflictsStore(str(tmp_path / "c.json"))
    with pytest.raises(KeyError):
        resolve_conflict("missing", {}, conflicts, storage, settings, device_id="A")
```

- [ ] **Step 2: Tests ausführen, Fail bestätigen**

```
pytest tests/test_sync.py -k "resolve" -v
```

Erwartet: FAIL — `resolve_conflict` fehlt.

- [ ] **Step 3: `resolve_conflict` implementieren**

In `src/sync.py` ans Ende anhängen:

```python
def resolve_conflict(conflict_id, chosen_value, conflicts_store, storage, settings, device_id):
    """User hat einen Konflikt aufgelöst. chosen_value enthält den gewählten
    (oder manuell editierten) Wert. Für entries: {start, end, pause} (und
    optional deleted). Für settings: {value}.
    Schreibt den Wert in den entsprechenden Store und markiert den Konflikt
    als resolved im ConflictsStore."""
    all_conflicts = conflicts_store.get_all()
    target = next((c for c in all_conflicts if c["id"] == conflict_id), None)
    if target is None:
        raise KeyError(f"Konflikt {conflict_id!r} nicht gefunden")

    now = _utc_now_iso()
    target["resolved"] = True
    target["resolution"] = dict(chosen_value)
    target["resolved_at"] = now
    target["resolved_by"] = device_id

    if target["kind"] == "entry":
        if chosen_value.get("deleted"):
            storage.delete(target["key"])
        else:
            storage.save(
                target["key"],
                chosen_value.get("start"),
                chosen_value.get("end"),
                chosen_value.get("pause", 0),
            )
    elif target["kind"] == "setting":
        settings.set_synced(target["key"], chosen_value.get("value"))

    conflicts_store.save_all(all_conflicts)
```

- [ ] **Step 4: Tests ausführen, grün**

```
pytest tests/test_sync.py -v
```

Erwartet: Alle PASS.

- [ ] **Step 5: Commit**

```
git add src/sync.py tests/test_sync.py
git commit -m "feat(sync): add resolve_conflict to mark and apply user choice"
```

---

## Phase 3: Drive Client (`src/drive.py`)

### Task 3.1: `drive.py` — Modul-Skelett + Exceptions

**Files:**
- Create: `src/drive.py`
- Create: `tests/test_drive.py`

- [ ] **Step 1: Failing test schreiben**

Neue Datei `tests/test_drive.py`:

```python
import pytest

from src.drive import DriveAuthError, DriveConflictError, DriveNetworkError


def test_exceptions_are_distinct():
    assert not issubclass(DriveAuthError, DriveNetworkError)
    assert not issubclass(DriveNetworkError, DriveAuthError)
    assert not issubclass(DriveConflictError, DriveAuthError)
```

- [ ] **Step 2: Test laufen, Fail**

```
pytest tests/test_drive.py -v
```

Erwartet: ImportError.

- [ ] **Step 3: `src/drive.py` Skelett**

Neue Datei `src/drive.py`:

```python
# src/drive.py
"""Google Drive API Wrapper für den Multi-Device-Sync.

Hält die appDataFolder-spezifische Datei `zeiterfassung-sync.json`.
Scope: drive.appdata (non-sensitive, per-app-isolated).
"""

SYNC_FILENAME = "zeiterfassung-sync.json"
SYNC_MIMETYPE = "application/json"
DRIVE_APPDATA_SCOPE = "https://www.googleapis.com/auth/drive.appdata"


class DriveAuthError(Exception):
    """Token revoked oder Auth fehlgeschlagen — User muss neu verbinden."""


class DriveNetworkError(Exception):
    """Netzwerkproblem oder Drive-API nicht erreichbar."""


class DriveConflictError(Exception):
    """ETag-Mismatch beim Upload — Remote wurde inzwischen verändert."""
```

- [ ] **Step 4: Test grün**

```
pytest tests/test_drive.py -v
```

- [ ] **Step 5: Commit**

```
git add src/drive.py tests/test_drive.py
git commit -m "feat(drive): scaffold module and exception hierarchy"
```

---

### Task 3.2: `drive.py` — `get_drive_service` mit kombinierten Scopes

**Files:**
- Modify: `src/drive.py`
- Modify: `tests/test_drive.py`

- [ ] **Step 1: Failing test schreiben**

In `tests/test_drive.py` anhängen:

```python
from unittest import mock

from src.drive import SYNC_SCOPES, get_drive_service


def test_sync_scopes_includes_gmail_send_and_drive_appdata():
    assert "https://www.googleapis.com/auth/gmail.send" in SYNC_SCOPES
    assert "https://www.googleapis.com/auth/drive.appdata" in SYNC_SCOPES


def test_get_drive_service_uses_existing_valid_token(tmp_path):
    token_path = tmp_path / "token.json"
    token_path.write_text('{"token": "fake"}')

    mock_creds = mock.MagicMock()
    mock_creds.valid = True
    mock_creds.expired = False

    with mock.patch("src.drive.Credentials") as mock_cred_cls, \
         mock.patch("src.drive.build") as mock_build:
        mock_cred_cls.from_authorized_user_file.return_value = mock_creds
        service = get_drive_service("credentials.json", str(token_path))

    mock_cred_cls.from_authorized_user_file.assert_called_once()
    assert mock_build.called
    assert mock_build.call_args[0][0] == "drive"


def test_get_drive_service_runs_oauth_flow_when_no_token(tmp_path):
    token_path = tmp_path / "token.json"  # doesn't exist
    creds_path = tmp_path / "credentials.json"
    creds_path.write_text('{"installed": {}}')

    new_creds = mock.MagicMock()
    new_creds.valid = True
    new_creds.to_json.return_value = '{"token": "new"}'

    with mock.patch("src.drive.InstalledAppFlow") as mock_flow_cls, \
         mock.patch("src.drive.build"):
        mock_flow = mock.MagicMock()
        mock_flow.run_local_server.return_value = new_creds
        mock_flow_cls.from_client_secrets_file.return_value = mock_flow

        get_drive_service(str(creds_path), str(token_path))

    assert mock_flow_cls.from_client_secrets_file.called
    call_args = mock_flow_cls.from_client_secrets_file.call_args
    used_scopes = call_args[0][1]
    assert "https://www.googleapis.com/auth/drive.appdata" in used_scopes
    assert "https://www.googleapis.com/auth/gmail.send" in used_scopes
    # Token wurde geschrieben
    assert token_path.exists()
```

- [ ] **Step 2: Test laufen, Fail**

```
pytest tests/test_drive.py -v
```

- [ ] **Step 3: `get_drive_service` implementieren**

In `src/drive.py` ergänzen (am Modul-Top nach den Exception-Klassen):

```python
import io
import os
import stat

try:
    from google.auth.exceptions import RefreshError, TransportError
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError
    from googleapiclient.http import MediaIoBaseDownload, MediaIoBaseUpload
except ImportError:
    # Wir akzeptieren ImportError beim Modul-Laden, damit Tests mit
    # mock.patch("src.drive.Credentials") greifen können. Bei echten Aufrufen
    # ohne installierte Libs würde es zur Laufzeit fehlschlagen — akzeptabel,
    # weil mail.py dieselben Libs braucht.
    Credentials = None  # type: ignore
    InstalledAppFlow = None  # type: ignore
    build = None  # type: ignore
    Request = None  # type: ignore
    RefreshError = Exception  # type: ignore
    TransportError = Exception  # type: ignore
    HttpError = Exception  # type: ignore
    MediaIoBaseDownload = None  # type: ignore
    MediaIoBaseUpload = None  # type: ignore


SYNC_SCOPES = [
    "https://www.googleapis.com/auth/gmail.send",
    DRIVE_APPDATA_SCOPE,
]


def _write_token(creds, token_path):
    with open(token_path, "w") as f:
        f.write(creds.to_json())
    try:
        os.chmod(token_path, stat.S_IRUSR | stat.S_IWUSR)  # 0o600
    except OSError:
        pass


def get_drive_service(credentials_path, token_path):
    """OAuth mit kombinierten Scopes (Gmail + Drive appdata). Token wird mit
    beiden Scopes geschrieben — Gmail send funktioniert weiter mit demselben
    token.json. Wirft DriveAuthError oder DriveNetworkError bei Problemen."""
    creds = None
    if os.path.exists(token_path):
        creds = Credentials.from_authorized_user_file(token_path, SYNC_SCOPES)

    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
        except RefreshError as e:
            raise DriveAuthError(str(e)) from e
        except TransportError as e:
            raise DriveNetworkError(str(e)) from e
        _write_token(creds, token_path)

    if not creds or not creds.valid:
        if not os.path.exists(credentials_path):
            raise FileNotFoundError(
                f"credentials.json nicht gefunden unter:\n{credentials_path}"
            )
        flow = InstalledAppFlow.from_client_secrets_file(credentials_path, SYNC_SCOPES)
        creds = flow.run_local_server(port=0)
        _write_token(creds, token_path)

    return build("drive", "v3", credentials=creds)
```

- [ ] **Step 4: Test grün**

```
pytest tests/test_drive.py -v
```

Erwartet: Alle PASS. CI installiert die google-libs nicht, aber `mock.patch("src.drive.Credentials")` ersetzt das `None` mit einem Mock, das funktioniert.

Bei `ImportError`-Pfad: Locally mit installierter Lib läuft alles. CI: Wir müssen prüfen, ob die test_drive.py Tests in CI laufen können. Workflow-Anpassung kommt in Task 5.x.

- [ ] **Step 5: Commit**

```
git add src/drive.py tests/test_drive.py
git commit -m "feat(drive): add get_drive_service with combined OAuth scopes"
```

---

### Task 3.3: `drive.py` — `find_sync_file`

**Files:**
- Modify: `src/drive.py`
- Modify: `tests/test_drive.py`

- [ ] **Step 1: Failing test schreiben**

In `tests/test_drive.py` anhängen:

```python
from src.drive import find_sync_file


def test_find_sync_file_returns_id_when_present():
    service = mock.MagicMock()
    service.files().list().execute.return_value = {
        "files": [{"id": "file-abc", "name": "zeiterfassung-sync.json"}],
    }
    assert find_sync_file(service) == "file-abc"


def test_find_sync_file_returns_none_when_absent():
    service = mock.MagicMock()
    service.files().list().execute.return_value = {"files": []}
    assert find_sync_file(service) is None


def test_find_sync_file_queries_appdatafolder():
    service = mock.MagicMock()
    service.files().list().execute.return_value = {"files": []}
    find_sync_file(service)
    # spaces='appDataFolder' wurde verwendet
    call_kwargs = service.files().list.call_args[1]
    assert call_kwargs.get("spaces") == "appDataFolder"
    assert "zeiterfassung-sync.json" in call_kwargs.get("q", "")
```

- [ ] **Step 2: Test laufen, Fail**

```
pytest tests/test_drive.py -v
```

- [ ] **Step 3: `find_sync_file` implementieren**

In `src/drive.py` ergänzen:

```python
def find_sync_file(service):
    """Listet appDataFolder und sucht nach SYNC_FILENAME. Liefert file_id oder None.
    Wirft DriveNetworkError bei API-Fehlern."""
    try:
        result = service.files().list(
            spaces="appDataFolder",
            q=f"name = '{SYNC_FILENAME}'",
            fields="files(id, name)",
            pageSize=10,
        ).execute()
    except HttpError as e:
        raise DriveNetworkError(str(e)) from e

    files = result.get("files", [])
    if not files:
        return None
    return files[0]["id"]
```

- [ ] **Step 4: Test grün**

```
pytest tests/test_drive.py -v
```

- [ ] **Step 5: Commit**

```
git add src/drive.py tests/test_drive.py
git commit -m "feat(drive): add find_sync_file for appDataFolder lookup"
```

---

### Task 3.4: `drive.py` — `download` und `upload` mit ETag

**Files:**
- Modify: `src/drive.py`
- Modify: `tests/test_drive.py`

- [ ] **Step 1: Failing test schreiben**

In `tests/test_drive.py` anhängen:

```python
import io

from src.drive import download, upload


def test_download_returns_content_and_etag():
    service = mock.MagicMock()
    service.files().get_media.return_value = "media-request"
    service.files().get().execute.return_value = {"etag": "etag-123"}

    with mock.patch("src.drive.MediaIoBaseDownload") as mock_dl_cls:
        # Simuliere Downloader, der sofort done=True liefert
        mock_dl = mock.MagicMock()
        mock_dl.next_chunk.return_value = (None, True)
        mock_dl_cls.return_value = mock_dl

        # Buffer-Inhalt durch Side-Effect simulieren
        def fake_init(buf, req):
            buf.write(b'{"hello": "world"}')
            return mock_dl
        mock_dl_cls.side_effect = fake_init

        content, etag = download(service, "file-123")

    assert content == b'{"hello": "world"}'
    assert etag == "etag-123"


def test_upload_new_file_when_file_id_none():
    service = mock.MagicMock()
    service.files().create().execute.return_value = {"id": "new-id", "etag": "etag-new"}
    file_id, etag = upload(service, b'{"x":1}', file_id=None, expected_etag="")
    assert file_id == "new-id"
    assert etag == "etag-new"


def test_upload_existing_file_uses_update():
    service = mock.MagicMock()
    service.files().update().execute.return_value = {"id": "file-123", "etag": "etag-2"}
    file_id, etag = upload(service, b'{"x":2}', file_id="file-123", expected_etag="etag-1")
    assert file_id == "file-123"
    assert etag == "etag-2"


def test_upload_etag_mismatch_raises_drive_conflict_error():
    from googleapiclient.errors import HttpError
    service = mock.MagicMock()
    # HttpError mit status 412 (Precondition Failed) simulieren
    resp = mock.MagicMock(status=412, reason="Precondition Failed")
    service.files().update().execute.side_effect = HttpError(resp, b"")
    with pytest.raises(DriveConflictError):
        upload(service, b'{"x":1}', file_id="file-1", expected_etag="old")
```

- [ ] **Step 2: Test laufen, Fail**

```
pytest tests/test_drive.py -v
```

- [ ] **Step 3: `download` und `upload` implementieren**

In `src/drive.py` ergänzen:

```python
def download(service, file_id):
    """Lädt die Sync-Datei herunter. Liefert (bytes, etag).
    Wirft DriveNetworkError bei API-Fehlern."""
    try:
        meta = service.files().get(fileId=file_id, fields="etag").execute()
        request = service.files().get_media(fileId=file_id)
        buf = io.BytesIO()
        downloader = MediaIoBaseDownload(buf, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()
    except HttpError as e:
        raise DriveNetworkError(str(e)) from e
    return buf.getvalue(), meta.get("etag", "")


def upload(service, content_bytes, file_id=None, expected_etag=None):
    """Uploadet `content_bytes` als Sync-Datei.

    - file_id=None  → neues File in appDataFolder anlegen
    - file_id gesetzt + expected_etag gesetzt → If-Match-Header für optimistic locking
    - Bei ETag-Mismatch → DriveConflictError

    Liefert (file_id, new_etag).
    """
    media = MediaIoBaseUpload(io.BytesIO(content_bytes),
                                mimetype=SYNC_MIMETYPE,
                                resumable=False)
    try:
        if file_id is None:
            metadata = {"name": SYNC_FILENAME, "parents": ["appDataFolder"]}
            resp = service.files().create(
                body=metadata, media_body=media, fields="id, etag",
            ).execute()
            return resp["id"], resp.get("etag", "")
        else:
            kwargs = {"fileId": file_id, "media_body": media, "fields": "id, etag"}
            if expected_etag:
                # If-Match-Header via Request-Builder
                update_request = service.files().update(**kwargs)
                update_request.headers["If-Match"] = expected_etag
                resp = update_request.execute()
            else:
                resp = service.files().update(**kwargs).execute()
            return resp["id"], resp.get("etag", "")
    except HttpError as e:
        status = getattr(e.resp, "status", None) if hasattr(e, "resp") else None
        if status == 412:
            raise DriveConflictError(str(e)) from e
        raise DriveNetworkError(str(e)) from e
```

- [ ] **Step 4: Test grün**

```
pytest tests/test_drive.py -v
```

- [ ] **Step 5: Commit**

```
git add src/drive.py tests/test_drive.py
git commit -m "feat(drive): add download and upload with etag-based optimistic locking"
```

---

### Task 3.5: CI-Workflow für `google-*` Test-Deps

**Files:**
- Modify: `.github/workflows/test.yml`

- [ ] **Step 1: Workflow lesen**

```
cat .github/workflows/test.yml
```

Aktuell installiert er nur `pytest holidays`. Für `test_drive.py` brauchen wir `google-api-python-client google-auth google-auth-oauthlib` — die werden bereits via `mail.py`-Imports gebraucht, aber in Tests wird `from googleapiclient.errors import HttpError` direkt gemacht.

- [ ] **Step 2: Workflow erweitern**

Im `Install dependencies`-Step die Lib-Liste erweitern:

```yaml
      - name: Install dependencies
        run: pip install pytest holidays google-api-python-client google-auth google-auth-oauthlib
```

- [ ] **Step 3: Tests lokal laufen**

```
pytest tests/test_drive.py tests/test_mail.py -v
```

Erwartet: Alle PASS.

- [ ] **Step 4: Commit**

```
git add .github/workflows/test.yml
git commit -m "ci: add google-api-python-client to test deps for drive tests"
```

---

## Phase 4: Wiring + UI

### Task 4.1: `mail.py` — Dynamic SCOPES via Setting

**Files:**
- Modify: `src/mail.py`
- Modify: `tests/test_mail.py`

- [ ] **Step 1: Failing test schreiben**

In `tests/test_mail.py` anhängen:

```python
from src.mail import get_scopes


def test_get_scopes_without_sync_only_gmail():
    scopes = get_scopes(sync_enabled=False)
    assert scopes == ["https://www.googleapis.com/auth/gmail.send"]


def test_get_scopes_with_sync_includes_drive_appdata():
    scopes = get_scopes(sync_enabled=True)
    assert "https://www.googleapis.com/auth/gmail.send" in scopes
    assert "https://www.googleapis.com/auth/drive.appdata" in scopes
```

- [ ] **Step 2: Test laufen, Fail**

```
pytest tests/test_mail.py -v
```

- [ ] **Step 3: `get_scopes` und Aufruf in `get_gmail_service`**

In `src/mail.py`:

(a) Ersetze die `SCOPES = [...]`-Zeile durch:

```python
GMAIL_SEND_SCOPE = "https://www.googleapis.com/auth/gmail.send"
DRIVE_APPDATA_SCOPE = "https://www.googleapis.com/auth/drive.appdata"


def get_scopes(sync_enabled):
    if sync_enabled:
        return [GMAIL_SEND_SCOPE, DRIVE_APPDATA_SCOPE]
    return [GMAIL_SEND_SCOPE]


# Legacy: alte Callers benutzen weiter SCOPES (gmail-only). Neue Callers
# benutzen get_scopes(settings.get("sync_enabled")).
SCOPES = [GMAIL_SEND_SCOPE]
```

(b) `refresh_token_if_needed` und `get_gmail_service` werden um `sync_enabled` erweitert. Ändere beide Signaturen:

```python
def refresh_token_if_needed(token_path="token.json", sync_enabled=False):
    ...
    creds = Credentials.from_authorized_user_file(token_path, get_scopes(sync_enabled))
    ...


def get_gmail_service(credentials_path="credentials.json", token_path="token.json",
                      sync_enabled=False):
    ...
    scopes = get_scopes(sync_enabled)
    creds = None
    if os.path.exists(token_path):
        creds = Credentials.from_authorized_user_file(token_path, scopes)
    ...
    flow = InstalledAppFlow.from_client_secrets_file(credentials_path, scopes)
    ...
```

Konkret die Stellen in `get_gmail_service` ersetzen: alle Vorkommen von `SCOPES` durch `scopes` (lokale Variable, abgeleitet von Parameter).

- [ ] **Step 4: Test grün**

```
pytest tests/test_mail.py -v
```

- [ ] **Step 5: Commit**

```
git add src/mail.py tests/test_mail.py
git commit -m "feat(mail): make scopes dynamic via sync_enabled flag"
```

---

### Task 4.2: `main.py` — `device_id` initialisieren

**Files:**
- Modify: `src/main.py`

- [ ] **Step 1: `device_id`-Generierung in `main.py`**

Ersetze den Inhalt von `src/main.py`:

```python
# src/main.py
import logging
import os
import sys
import tkinter as tk
import uuid

from src.logging_setup import setup_logging
from src.paths import get_base_path
from src.settings import Settings
from src.storage import Storage
from src.ui import App
from src.version import VERSION


def _ensure_device_id(settings):
    """Bei Erststart oder fehlendem device_id: UUID generieren und persistieren."""
    if not settings.get("device_id"):
        settings.set("device_id", str(uuid.uuid4()))


def main():
    base = get_base_path()
    try:
        setup_logging(base)
        logging.getLogger(__name__).info("Zeiterfassung v%s gestartet", VERSION)
    except Exception:
        pass

    settings = Settings(os.path.join(base, "settings.json"))
    _ensure_device_id(settings)
    device_id = settings.get("device_id")
    settings.device_id_for_sync = device_id

    storage = Storage(os.path.join(base, "zeiterfassung.json"), device_id=device_id)

    root = tk.Tk()
    app = App(root, storage, settings, base_path=base)

    if "--minimized" in sys.argv:
        root.iconify()

    root.mainloop()


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Test manuell — App starten**

```
python -m src.main
```

Erwartet: Fenster öffnet sich. `settings.json` enthält jetzt `"device_id": "<uuid>"` und (bei vorhandenen Einträgen nach erstem Save) Einträge bekommen den `device_id`-Stamp.

- [ ] **Step 3: Bestehende Tests laufen lassen**

```
pytest -v
```

Erwartet: Alle PASS (Storage hat sinnvollen Default `device_id=""`, Tests übergeben explizit `device_id="test-device"`).

- [ ] **Step 4: Commit**

```
git add src/main.py
git commit -m "feat(main): generate stable device_id and wire to storage/settings"
```

---

### Task 4.3: `main.py` — Pull beim App-Start (Background-Thread)

**Files:**
- Modify: `src/main.py`
- Create: `src/conflicts_store.py` (falls noch nicht eingebunden — schon in 1.5)

- [ ] **Step 1: Sync-Bootstrap in `main.py`**

Ersetze den `main()`-Inhalt durch (Diff zur letzten Version):

```python
import threading

from src.conflicts_store import ConflictsStore


def _run_pull_in_background(storage, settings, conflicts_store, base, ui_callback):
    """Pull läuft in einem Thread; UI-Update über ui_callback (root.after)."""
    from src import drive, sync
    try:
        service = drive.get_drive_service(
            os.path.join(base, "credentials.json"),
            os.path.join(base, "token.json"),
        )
        file_id = drive.find_sync_file(service)
        if file_id is None:
            remote_doc = {"schema_version": 1, "entries": {}, "settings": {}, "conflicts": []}
            etag = ""
        else:
            content, etag = drive.download(service, file_id)
            import json
            remote_doc = json.loads(content) if content else {"entries": {}, "settings": {}, "conflicts": []}
        local_doc = sync.build_local_doc(storage, settings, conflicts_store)
        merged = sync.merge(local_doc, remote_doc, settings.get("last_pull_at") or "")
        sync.apply_merged_doc(merged, storage, settings, conflicts_store)
        settings.set_many({
            "last_pull_at": sync._utc_now_iso(),
            "drive_etag": etag,
        })
        ui_callback(ok=True, error=None)
    except Exception as e:
        logging.getLogger(__name__).exception("Sync pull failed")
        ui_callback(ok=False, error=e)


def main():
    base = get_base_path()
    try:
        setup_logging(base)
        logging.getLogger(__name__).info("Zeiterfassung v%s gestartet", VERSION)
    except Exception:
        pass

    settings = Settings(os.path.join(base, "settings.json"))
    _ensure_device_id(settings)
    device_id = settings.get("device_id")
    settings.device_id_for_sync = device_id

    storage = Storage(os.path.join(base, "zeiterfassung.json"), device_id=device_id)
    conflicts_store = ConflictsStore(os.path.join(base, "conflicts.json"))

    root = tk.Tk()
    app = App(root, storage, settings,
              base_path=base, conflicts_store=conflicts_store)

    if "--minimized" in sys.argv:
        root.iconify()

    if settings.get("sync_enabled"):
        def _on_sync_done(ok, error):
            def apply():
                if ok:
                    app.on_sync_pull_success()
                else:
                    app.on_sync_pull_error(error)
            root.after(0, apply)
        threading.Thread(
            target=_run_pull_in_background,
            args=(storage, settings, conflicts_store, base, _on_sync_done),
            daemon=True,
        ).start()

    root.mainloop()


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: `App.__init__` Signatur erweitern**

In `src/ui.py`: Suche `class App` und füge `conflicts_store=None` zum Init hinzu, plus die beiden Callback-Stubs:

```python
class App:
    def __init__(self, root, storage, settings, base_path, conflicts_store=None):
        ...  # bisheriger Code
        self.conflicts_store = conflicts_store
        ...

    def on_sync_pull_success(self):
        """Wird aus dem UI-Thread nach erfolgreichem Pull aufgerufen."""
        self.refresh_calendar()  # falls vorhanden, sonst entsprechende UI-Aktualisierung
        # Konflikt-Anzahl ggf. im Header updaten — Task 4.5

    def on_sync_pull_error(self, error):
        import tkinter.messagebox as mb
        mb.showerror("Synchronisation fehlgeschlagen",
                       f"Beim Abrufen der Drive-Daten ist ein Fehler aufgetreten:\n\n{error}")
```

Falls `App` keine `refresh_calendar`-Methode hat: passe an die existierende Re-Render-Methode an (Grep `def refresh` oder `def update_calendar` in `ui.py`).

- [ ] **Step 3: App testen**

```
pytest -v
```

Erwartet: Alle PASS.

```
python -m src.main
```

Mit `sync_enabled=False` (default): keine Pull-Aktion. Falls Sync aktiviert: Pull läuft (oder schlägt fehl mit MessageBox — das ist erwartet ohne credentials.json).

- [ ] **Step 4: Commit**

```
git add src/main.py src/ui.py
git commit -m "feat(main): pull from Drive on startup in background thread"
```

---

### Task 4.4: `main.py` — Push beim App-Close

**Files:**
- Modify: `src/main.py`
- Modify: `src/ui.py`

- [ ] **Step 1: Push-Funktion in `main.py`**

In `src/main.py` ergänzen (vor `main()`):

```python
def _run_push_blocking(storage, settings, conflicts_store, base, timeout_seconds=5):
    """Synchroner Push mit Timeout. Fehler werden geloggt, nicht angezeigt
    (App schließt gerade)."""
    import json
    from src import drive, sync

    result = {}

    def _do():
        try:
            service = drive.get_drive_service(
                os.path.join(base, "credentials.json"),
                os.path.join(base, "token.json"),
            )
            file_id = drive.find_sync_file(service)
            doc = sync.build_local_doc(storage, settings, conflicts_store)
            content = json.dumps(doc, ensure_ascii=False).encode("utf-8")
            expected_etag = settings.get("drive_etag")
            try:
                new_id, new_etag = drive.upload(service, content, file_id, expected_etag)
            except drive.DriveConflictError:
                # Etag-Mismatch: 1× pull-merge-push retry
                if file_id is not None:
                    remote_bytes, _ = drive.download(service, file_id)
                    remote_doc = json.loads(remote_bytes)
                else:
                    remote_doc = {"schema_version": 1, "entries": {}, "settings": {}, "conflicts": []}
                local_doc = sync.build_local_doc(storage, settings, conflicts_store)
                merged = sync.merge(local_doc, remote_doc, settings.get("last_pull_at") or "")
                sync.apply_merged_doc(merged, storage, settings, conflicts_store)
                doc = sync.build_local_doc(storage, settings, conflicts_store)
                content = json.dumps(doc, ensure_ascii=False).encode("utf-8")
                new_id, new_etag = drive.upload(service, content, file_id, expected_etag="")
            settings.set("drive_etag", new_etag)
            result["ok"] = True
        except Exception as e:
            logging.getLogger(__name__).exception("Sync push failed: %s", e)
            result["ok"] = False
            result["error"] = e

    t = threading.Thread(target=_do, daemon=True)
    t.start()
    t.join(timeout=timeout_seconds)
    return result.get("ok", False)
```

- [ ] **Step 2: `App` ruft Push beim Schließen auf**

In `src/ui.py` — in `class App`, wo `WM_DELETE_WINDOW` oder eine `on_close`-Methode existiert (Grep nach `WM_DELETE_WINDOW`):

Falls keine existiert, ergänze:

```python
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _on_close(self):
        if self.settings.get("sync_enabled"):
            from src.main import _run_push_blocking  # vermeidet Zirkel-Import beim Modul-Load
            _run_push_blocking(self.storage, self.settings, self.conflicts_store,
                                self.base_path, timeout_seconds=5)
        self.root.destroy()
```

(Bestehende `protocol`-Bindings ggf. konsolidieren — Grep `WM_DELETE_WINDOW` in `ui.py` und passe an.)

- [ ] **Step 3: App-Close mit aktivem Sync manuell testen**

Wenn `sync_enabled=True` und Netz erreichbar: App schließen → Push läuft, Daten landen in Drive.

Wenn Netz unerreichbar oder Auth fehlt: Logfile zeigt Fehler, App schließt trotzdem.

- [ ] **Step 4: Commit**

```
git add src/main.py src/ui.py
git commit -m "feat(main): push to Drive on app close with 5s timeout"
```

---

### Task 4.5: `ui.py` — Sync-Button + Status-Label im Header

**Files:**
- Modify: `src/ui.py`

- [ ] **Step 1: Header-Layout um Sync-Widgets erweitern**

In `src/ui.py`, im Bereich wo der Header gebaut wird (Grep nach `Settings`-Button oder `header_frame`):

Nach dem Settings-Button einfügen:

```python
        # Sync-Button und Status
        self.sync_button = tk.Button(header_frame, text="⟳",
                                       command=self._on_sync_clicked,
                                       width=3)
        self.sync_button.pack(side="right", padx=(4, 0))
        self.sync_status_label = tk.Label(header_frame, text="")
        self.sync_status_label.pack(side="right", padx=(8, 4))
        self._update_sync_status_label()
```

Neue Methoden in `App`:

```python
    def _update_sync_status_label(self):
        if not self.settings.get("sync_enabled"):
            self.sync_status_label.config(text="")
            return
        n = 0
        if self.conflicts_store is not None:
            n = self.conflicts_store.count_unresolved()
        if n > 0:
            self.sync_status_label.config(text=f"⚠ {n} Konflikt{'e' if n != 1 else ''}")
        else:
            last = self.settings.get("last_pull_at") or "noch nie"
            self.sync_status_label.config(text=f"✓ {last[:10] if len(last) >= 10 else last}")

    def _on_sync_clicked(self):
        if not self.settings.get("sync_enabled"):
            import tkinter.messagebox as mb
            mb.showinfo("Synchronisation",
                          "Synchronisation ist deaktiviert. In den Einstellungen aktivierbar.")
            return
        # Trigger Push (und implizit Pull bei Etag-Mismatch)
        self.sync_status_label.config(text="Synchronisiere…")
        import threading
        from src.main import _run_push_blocking
        def _do():
            ok = _run_push_blocking(self.storage, self.settings, self.conflicts_store,
                                       self.base_path, timeout_seconds=15)
            self.root.after(0, lambda: self._on_manual_sync_done(ok))
        threading.Thread(target=_do, daemon=True).start()

    def _on_manual_sync_done(self, ok):
        if not ok:
            import tkinter.messagebox as mb
            mb.showerror("Synchronisation", "Synchronisation fehlgeschlagen. Logs prüfen.")
        self._update_sync_status_label()
```

- [ ] **Step 2: `on_sync_pull_success`/`on_sync_pull_error` aktualisieren**

Ersetze die in 4.3 angelegten Stubs:

```python
    def on_sync_pull_success(self):
        self.refresh_calendar()  # oder existierende Re-Render-Methode
        self._update_sync_status_label()

    def on_sync_pull_error(self, error):
        import tkinter.messagebox as mb
        mb.showerror("Synchronisation fehlgeschlagen",
                       f"Beim Abrufen der Drive-Daten ist ein Fehler aufgetreten:\n\n{error}")
        self._update_sync_status_label()
```

- [ ] **Step 3: Manueller UI-Test**

```
python -m src.main
```

Mit `sync_enabled=False`: kein Sync-Status sichtbar oder Button bringt Hinweis-Dialog.

Mit `sync_enabled=True`: Button im Header sichtbar, Status zeigt Datum des letzten Pulls.

- [ ] **Step 4: Commit**

```
git add src/ui.py
git commit -m "feat(ui): add sync button and status label in header"
```

---

### Task 4.6: `dialogs/settings_dialog.py` — Sync-Sektion

**Files:**
- Modify: `src/dialogs/settings_dialog.py`

- [ ] **Step 1: Bestehenden Dialog lesen**

```
cat src/dialogs/settings_dialog.py
```

(Datei vermutlich groß — Sync-Sektion wird angefügt; bestehendes Layout-Pattern beibehalten.)

- [ ] **Step 2: Sync-Sektion hinzufügen**

Im SettingsDialog am Ende des Layouts (vor den OK/Abbrechen-Buttons) folgenden Block einfügen (Grep nach „autostart" oder „checkbox" für Layout-Pattern, dann analog):

```python
        # --- Synchronisation ---
        sync_frame = tk.LabelFrame(parent, text="Synchronisation")
        sync_frame.pack(fill="x", padx=8, pady=8)

        self.var_sync = tk.BooleanVar(value=self.settings.get("sync_enabled"))
        cb = tk.Checkbutton(sync_frame, text="Mit Google Drive synchronisieren",
                              variable=self.var_sync,
                              command=self._on_sync_toggled)
        cb.pack(anchor="w", padx=8, pady=4)

        device_id = self.settings.get("device_id") or "(noch nicht gesetzt)"
        tk.Label(sync_frame, text=f"Geräte-ID: {device_id[:8]}…").pack(anchor="w", padx=8)

        last = self.settings.get("last_pull_at") or "noch nie"
        tk.Label(sync_frame, text=f"Letzte Synchronisation: {last}").pack(anchor="w", padx=8)

        unresolved = 0
        if self.conflicts_store is not None:
            unresolved = self.conflicts_store.count_unresolved()
        if unresolved > 0:
            tk.Button(sync_frame,
                       text=f"Konflikte ansehen ({unresolved})",
                       command=self._open_conflicts_dialog).pack(anchor="w", padx=8, pady=4)
```

Constructor-Signatur erweitern: füge `conflicts_store=None` in `__init__` hinzu, speichere als `self.conflicts_store`.

Neue Methoden:

```python
    def _on_sync_toggled(self):
        new_state = self.var_sync.get()
        if new_state and not self.settings.get("sync_enabled"):
            # Aktivierung: OAuth-Flow mit erweitertem Scope
            try:
                from src import drive
                drive.get_drive_service(
                    os.path.join(self.base_path, "credentials.json"),
                    os.path.join(self.base_path, "token.json"),
                )
            except Exception as e:
                import tkinter.messagebox as mb
                mb.showerror("Synchronisation aktivieren",
                               f"OAuth-Flow fehlgeschlagen:\n\n{e}")
                self.var_sync.set(False)
                return
            self.settings.set("sync_enabled", True)
        elif not new_state and self.settings.get("sync_enabled"):
            self.settings.set("sync_enabled", False)

    def _open_conflicts_dialog(self):
        from src.dialogs.conflicts_dialog import ConflictsDialog
        ConflictsDialog(self.root, self.storage, self.settings, self.conflicts_store)
```

Ergänze `os` und `base_path` import / Attribut, falls noch nicht vorhanden.

- [ ] **Step 3: Aufrufer im UI anpassen**

In `src/ui.py`, wo der SettingsDialog aufgerufen wird (Grep `SettingsDialog(`):

```python
        SettingsDialog(self.root, self.settings, ...,
                        conflicts_store=self.conflicts_store,
                        base_path=self.base_path,
                        storage=self.storage)
```

Aktuelle Aufrufer-Parameter beibehalten und die neuen ergänzen.

- [ ] **Step 4: Manueller UI-Test**

```
python -m src.main
```

Settings öffnen → Sync-Sektion sichtbar. Checkbox aktivieren → OAuth-Browser-Tab öffnet sich (sofern credentials.json vorhanden).

- [ ] **Step 5: Commit**

```
git add src/dialogs/settings_dialog.py src/ui.py
git commit -m "feat(settings-dialog): add sync section with toggle and conflicts link"
```

---

### Task 4.7: `dialogs/conflicts_dialog.py` — Neuer Dialog

**Files:**
- Create: `src/dialogs/conflicts_dialog.py`

- [ ] **Step 1: Datei anlegen**

Neue Datei `src/dialogs/conflicts_dialog.py`:

```python
# src/dialogs/conflicts_dialog.py
import tkinter as tk
from tkinter import ttk, messagebox

from src import sync


def _fmt_entry_candidate(cand):
    if cand.get("deleted"):
        return f"GELÖSCHT (von {cand.get('device_id', '?')[:8]}…, {cand.get('modified_at', '')})"
    return (f"{cand.get('start', '')}—{cand.get('end', '')} "
            f"(Pause {cand.get('pause', 0)} min, von "
            f"{cand.get('device_id', '?')[:8]}…, {cand.get('modified_at', '')})")


def _fmt_setting_candidate(cand):
    return f"{cand.get('value', '')!r} (von {cand.get('device_id', '?')[:8]}…, {cand.get('modified_at', '')})"


class ConflictsDialog:
    def __init__(self, parent, storage, settings, conflicts_store):
        self.parent = parent
        self.storage = storage
        self.settings = settings
        self.conflicts_store = conflicts_store

        self.top = tk.Toplevel(parent)
        self.top.title("Konflikte auflösen")
        self.top.transient(parent)
        self.top.grab_set()

        self._build()
        self._refresh_list()

    def _build(self):
        left = tk.Frame(self.top)
        left.pack(side="left", fill="y", padx=8, pady=8)

        tk.Label(left, text="Offene Konflikte").pack(anchor="w")
        self.listbox = tk.Listbox(left, width=40, height=15)
        self.listbox.pack(fill="y", expand=True)
        self.listbox.bind("<<ListboxSelect>>", lambda _e: self._on_select())

        self.right = tk.Frame(self.top)
        self.right.pack(side="right", fill="both", expand=True, padx=8, pady=8)

        self.detail_label = tk.Label(self.right, text="Wähle einen Konflikt links.",
                                       wraplength=400, justify="left")
        self.detail_label.pack(anchor="nw")

        button_row = tk.Frame(self.right)
        button_row.pack(side="bottom", fill="x", pady=(8, 0))
        self.btn_a = tk.Button(button_row, text="Version A übernehmen",
                                  command=lambda: self._resolve_with_candidate(0),
                                  state="disabled")
        self.btn_b = tk.Button(button_row, text="Version B übernehmen",
                                  command=lambda: self._resolve_with_candidate(1),
                                  state="disabled")
        self.btn_a.pack(side="left", padx=4)
        self.btn_b.pack(side="left", padx=4)
        tk.Button(button_row, text="Schließen", command=self.top.destroy).pack(side="right")

    def _refresh_list(self):
        self.listbox.delete(0, "end")
        self._unresolved = [c for c in self.conflicts_store.get_all() if not c.get("resolved")]
        for c in self._unresolved:
            self.listbox.insert("end", f"{c['kind']}: {c['key']}")

    def _on_select(self):
        sel = self.listbox.curselection()
        if not sel:
            return
        c = self._unresolved[sel[0]]
        if c["kind"] == "entry":
            cand_a = _fmt_entry_candidate(c["candidates"][0])
            cand_b = _fmt_entry_candidate(c["candidates"][1])
        else:
            cand_a = _fmt_setting_candidate(c["candidates"][0])
            cand_b = _fmt_setting_candidate(c["candidates"][1])
        self.detail_label.config(text=f"Konflikt für {c['key']}\n\nA: {cand_a}\n\nB: {cand_b}")
        self.btn_a.config(state="normal")
        self.btn_b.config(state="normal")
        self._selected = c

    def _resolve_with_candidate(self, idx):
        c = self._selected
        cand = c["candidates"][idx]
        if c["kind"] == "entry":
            chosen = {
                "start": cand.get("start"),
                "end": cand.get("end"),
                "pause": cand.get("pause", 0),
                "deleted": cand.get("deleted", False),
            }
        else:
            chosen = {"value": cand.get("value")}
        device_id = self.settings.get("device_id") or ""
        try:
            sync.resolve_conflict(c["id"], chosen, self.conflicts_store,
                                     self.storage, self.settings, device_id)
        except Exception as e:
            messagebox.showerror("Konflikt-Resolution fehlgeschlagen", str(e))
            return
        self._refresh_list()
        self.btn_a.config(state="disabled")
        self.btn_b.config(state="disabled")
        self.detail_label.config(text="Konflikt aufgelöst. Wähle den nächsten.")
```

- [ ] **Step 2: Manueller Test**

Setze testweise einen fake Konflikt in `conflicts.json` und öffne Settings → Konflikte ansehen.

```python
# In Python-Shell oder Setup-Skript:
from src.conflicts_store import ConflictsStore
cs = ConflictsStore("conflicts.json")
cs.save_all([{
    "id": "test-1", "kind": "entry", "key": "2026-05-14",
    "candidates": [
        {"start": "08:00", "end": "16:00", "pause": 30, "modified_at": "2026-05-14T09:00:00Z", "device_id": "abc", "deleted": False},
        {"start": "09:00", "end": "17:00", "pause": 30, "modified_at": "2026-05-14T10:00:00Z", "device_id": "def", "deleted": False},
    ],
    "detected_at": "2026-05-14T11:00:00Z",
    "resolved": False, "resolution": None,
    "resolved_at": None, "resolved_by": None,
}])
```

App starten, Settings → Konflikte ansehen → Dialog öffnet sich, Konflikt sichtbar, Auflösung funktioniert.

- [ ] **Step 3: Commit**

```
git add src/dialogs/conflicts_dialog.py
git commit -m "feat(conflicts-dialog): add modal for user-driven conflict resolution"
```

---

### Task 4.8: `ui.py` — Kalender-Markierung für Tage mit Konflikt

**Files:**
- Modify: `src/ui.py`

- [ ] **Step 1: Konflikt-Set in App halten**

In `App` neue Methode:

```python
    def _dates_with_unresolved_conflicts(self):
        if not self.conflicts_store:
            return set()
        return {c["key"] for c in self.conflicts_store.get_all()
                 if c.get("kind") == "entry" and not c.get("resolved")}
```

- [ ] **Step 2: Kalender-Render erweitern**

Suche in `ui.py` die Stelle, wo Kalender-Tage gerendert werden (Grep `entry` oder `cal_grid`). Beim Rendern jedes Tags:

```python
        conflict_dates = self._dates_with_unresolved_conflicts()
        ...
        for date_str in render_dates:
            ...
            if date_str in conflict_dates:
                cell.config(highlightbackground="orange", highlightthickness=2)
                cell.bind("<Enter>", lambda _e: self._show_tooltip("Konflikt — bitte auflösen"))
```

(Anpassen an existierendes Kalender-Render-Pattern; existierender Code könnte z.B. `Label`s in einem Grid sein. Wichtig: nur Style-Änderung, keine andere Logik.)

- [ ] **Step 3: Re-Render nach Sync**

In `on_sync_pull_success` und `_on_manual_sync_done` sicherstellen, dass `refresh_calendar()` (oder die existierende Re-Render-Methode) aufgerufen wird.

- [ ] **Step 4: Manueller UI-Test**

Konflikt einfügen wie in 4.7, App starten — Tag mit Konflikt hat oranges Highlighting.

- [ ] **Step 5: Commit**

```
git add src/ui.py
git commit -m "feat(ui): highlight calendar cells with unresolved conflicts"
```

---

## Phase 5: Robustness Polish

### Task 5.1: Robuste Behandlung korrupter Remote-Datei

**Files:**
- Modify: `src/main.py`
- Modify: `tests/test_sync.py`

- [ ] **Step 1: Failing test schreiben**

In `tests/test_sync.py` anhängen:

```python
import json as _json


def test_main_pull_quarantines_corrupt_remote(tmp_path, monkeypatch):
    """Wenn die Drive-Datei kein gültiges JSON ist, wird sie via Drive umbenannt
    und der Pull behandelt sie als 'leer'.
    Wir testen das auf der Sync-Engine-Ebene: parse_remote_or_quarantine sollte
    bei kaputtem Inhalt ein leeres Doc zurückgeben und einen Callback aufrufen."""
    from src.main import _parse_remote_or_quarantine

    quarantined = []
    def fake_quarantine(file_id):
        quarantined.append(file_id)

    doc = _parse_remote_or_quarantine(b"not json{{{", "file-1", fake_quarantine)
    assert doc == {"schema_version": 1, "entries": {}, "settings": {}, "conflicts": []}
    assert quarantined == ["file-1"]


def test_main_pull_returns_doc_when_valid_json():
    from src.main import _parse_remote_or_quarantine
    raw = _json.dumps({"schema_version": 1, "entries": {"D": {}}, "settings": {}, "conflicts": []})
    doc = _parse_remote_or_quarantine(raw.encode(), "file-1", lambda fid: None)
    assert "D" in doc["entries"]
```

- [ ] **Step 2: Tests laufen, Fail**

```
pytest tests/test_sync.py -k "parse_remote" -v
```

- [ ] **Step 3: Helper in `src/main.py` extrahieren**

In `src/main.py`:

```python
def _parse_remote_or_quarantine(content_bytes, file_id, on_corrupt):
    """Parsed Remote-Bytes als JSON. Bei Fehler ruft on_corrupt(file_id) auf
    und liefert ein leeres Doc."""
    import json
    try:
        return json.loads(content_bytes)
    except (json.JSONDecodeError, ValueError):
        on_corrupt(file_id)
        return {"schema_version": 1, "entries": {}, "settings": {}, "conflicts": []}
```

Und im `_run_pull_in_background` den Parser nutzen:

```python
        if file_id is None:
            remote_doc = {"schema_version": 1, "entries": {}, "settings": {}, "conflicts": []}
            etag = ""
        else:
            content, etag = drive.download(service, file_id)
            def _quarantine(fid):
                # Drive-API: rename to .corrupt-<ts>
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
```

- [ ] **Step 4: Test grün**

```
pytest tests/test_sync.py -v
```

- [ ] **Step 5: Commit**

```
git add src/main.py tests/test_sync.py
git commit -m "feat(sync): quarantine corrupt remote sync file on pull"
```

---

### Task 5.2: CHANGELOG + Version-Bump

**Files:**
- Modify: `CHANGELOG.md`
- Modify: `src/version.py`

- [ ] **Step 1: Version bumpen**

In `src/version.py`:

```python
VERSION = "1.12.0"
```

(Major-Feature → Minor-Bump.)

- [ ] **Step 2: CHANGELOG-Eintrag**

In `CHANGELOG.md` oben:

```markdown
## 1.12.0 — 2026-05-14

### Hinzugefügt
- Multi-Device-Sync via Google Drive (opt-in). Zeiteinträge und Mail-Settings
  synchronisieren über einen versteckten Ordner in deinem Drive (`appDataFolder`).
  Pull beim App-Start, Push manuell oder beim Schließen.
- Konflikt-Behandlung: Wenn derselbe Tag auf zwei Geräten offline bearbeitet wird,
  erscheinen beide Versionen in einem Konflikt-Dialog zur manuellen Auswahl.
- Sync-Button und Status-Anzeige im Header (nur sichtbar bei aktivem Sync).
- Geräte-ID wird einmal pro Installation generiert (siehe Einstellungen).

### Hinweise
- Aktivierung erfordert einen erneuten Google-OAuth-Consent mit erweitertem Scope
  (`drive.appdata`, non-sensitive).
- Beim Aufräumen alter Einträge wachsen Tombstone-Marker derzeit unbeschränkt —
  siehe `docs/known-limitations.md`.
```

- [ ] **Step 3: Commit**

```
git add src/version.py CHANGELOG.md
git commit -m "chore: bump v1.12.0 + Changelog for multi-device sync"
```

---

### Task 5.3: Manueller Test-Pass + Smoke

**Files:**
- (Keine Code-Änderungen; Verifikation)

- [ ] **Step 1: Alle Tests laufen lassen**

```
pytest -v
```

Erwartet: Alle PASS, keine Warnings über fehlende Module.

- [ ] **Step 2: App-Start ohne aktiven Sync**

```
python -m src.main
```

Erwartet: App startet unverändert. Keine Drive-Calls. Eintrags-Anlage funktioniert. Beim Speichern: Eintrag bekommt jetzt `modified_at`/`device_id` (in `zeiterfassung.json` sichtbar). UI verhält sich wie vorher.

- [ ] **Step 3: App-Start mit aktivem Sync (echte Drive-Anbindung)**

Voraussetzung: `credentials.json` vorhanden.

1. Settings öffnen → Sync aktivieren → OAuth-Browser → Consent für Drive-Scope.
2. Eintrag anlegen, App schließen.
3. `zeiterfassung-sync.json` in Drive sollte angelegt sein (in Drive Web-UI nicht sichtbar — appDataFolder).
4. Auf anderem Gerät (oder Test-Setup: zweite `~/Library/Application Support/Zeiterfassung-2/` o.ä.) selben Account verbinden, App starten → Pull bringt Daten.
5. Konflikt erzwingen: Auf beiden Geräten denselben Tag editieren während eines offline ist. Wiederverbinden → Konflikt erscheint, Resolution propagiert.

- [ ] **Step 4: Quarantäne-Pfad smoke-testen**

`zeiterfassung-sync.json` lokal mit kaputtem Inhalt via Python-Shell hochladen:

```python
from src import drive
service = drive.get_drive_service("credentials.json", "token.json")
file_id = drive.find_sync_file(service)
drive.upload(service, b"not json", file_id=file_id)
```

App starten → Banner „Remote-Daten beschädigt", Sync-File hat Suffix `.corrupt-<ts>`.

- [ ] **Step 5: Commit (leer falls keine Änderungen, sonst Fixes aus dem manuellen Test)**

```
git status
# Wenn Fixes nötig waren:
git add -p
git commit -m "fix: <details aus manuellem Testlauf>"
```

---

## Self-Review

Nach Fertigstellung dieses Plans Review:

**Spec-Coverage:**
- Sync-File-Struktur (entries/settings/conflicts) → Tasks 1.1, 1.4, 1.5, 2.7 ✓
- Drive `appDataFolder` mit `drive.appdata` Scope → Task 3.1, 3.2 ✓
- LWW pro Eintrag mit Konflikt-Erkennung → Task 2.1, 2.3 ✓
- Tombstones für Deletes → Task 1.1, 1.2, 2.2 ✓
- Settings-Whitelist + `_synced_meta` → Task 1.4, 2.4 ✓
- Konflikt-Listen-Merge mit Idempotenz → Task 2.5 ✓
- Resolution-Propagation in entries/settings → Task 2.6 ✓
- `resolve_conflict` mit Storage/Settings-Update → Task 2.8 ✓
- ETag-Optimistic-Lock + Retry → Task 3.4, 4.4 ✓
- Migration alter Einträge → Task 1.2 ✓
- Opt-in via Settings-Toggle → Task 4.6 ✓
- Pull on start, push on close, manual button → Task 4.3, 4.4, 4.5 ✓
- Konflikt-Dialog → Task 4.7 ✓
- Kalender-Markierung für Konflikte → Task 4.8 ✓
- Korrupte Remote-File-Quarantäne → Task 5.1 ✓
- CI-Workflow-Anpassung → Task 3.5 ✓
- CHANGELOG + Version-Bump → Task 5.2 ✓
- Manueller Test-Plan → Task 5.3 ✓

**Placeholders:** Keine TBDs, alle Code-Blöcke konkret.

**Typkonsistenz:** `_merge_one` Signatur in 2.1 und 2.3 konsistent (`equal_fn`, `kind`, `key`). `build_local_doc`/`apply_merged_doc` Parameter-Reihenfolge konsistent in 2.7 und 2.8.
