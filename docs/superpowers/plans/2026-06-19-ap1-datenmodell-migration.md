# AP1 — Datenmodell + Migration (Multi-Slot) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `src/storage.py` und `src/reservations.py` auf das Multi-Slot-Datenmodell umstellen (eine Slot-Liste pro Tag statt eines einzelnen Eintrags) und bestehende Ein-Eintrag-Daten idempotent migrieren.

**Architecture:** Der Tag bleibt der Schlüssel und die Sync-Einheit; der Eintragswert wird `{slots: [...], <Metadaten>}`. Ist-Zeit-Slots tragen `{start, end, pause, kategorie}`, Reservierungs-Slots `{start, end, kategorie, gcal_event_id}`. Migration läuft rein in-memory beim Laden (idempotent über das Vorhandensein des `slots`-Keys), wie das bestehende `_migrate_legacy_entries`-Muster.

**Tech Stack:** Python stdlib (json, os, datetime), pytest. Keine neuen Dependencies.

## Global Constraints

- **Sync-Einheit = Tag.** Der Eintragswert ist eine Slot-Liste; Slots haben keine eigenen Sync-Metadaten. (Verbatim aus Spec, Leitentscheidung 1.)
- **Kategorie = String am Slot**, `""` = keine Kategorie = Verhalten wie vor Migration. (Leitentscheidung 2.)
- **Pause pro Ist-Zeit-Slot.** Reservierungs-Slots haben **kein** `pause`, dafür `gcal_event_id`. (Leitentscheidung 3 / Datenmodell.)
- **Migration idempotent:** Erkennung über vorhandenen `"slots"`-Key; bereits migrierte Einträge bleiben unangetastet.
- **Datumsformat:** intern ISO (`YYYY-MM-DD`, Timestamps `…THH:MM:SSZ`). Nicht ändern.
- **Harter Schnitt (abgestimmt):** AP1 stellt die Signaturen direkt auf Slots um. Nur die **AP1-eigenen** Testdateien werden in diesem Paket angepasst. Die übrige Test-Suite und die laufende App sind zwischen AP1 und den Consumer-Paketen **bewusst rot/kaputt** — volle Suite wird erst durch die späteren APs wieder grün. Verifikation in AP1 läuft daher **nur** gegen die vier AP1-Testdateien.
- **Validierung (Zeitformate, Non-Overlap) gehört NICHT in AP1** — Storage/Reservations bleiben (wie heute) permissiv und speichern, was übergeben wird. Non-Overlap kommt in AP3 (`time_utils` + Dialog).

## Forward-Dependencies (bewusst nach AP1 verschoben)

- **`gcal_event_id`-Erhalt über Reservierungs-Edits:** AP1's `ReservationStore.save(date, slots)` speichert die übergebenen Slots wie sie sind (mitgelieferte `gcal_event_id` bleibt, fehlende wird `None`). Das frühere „beim Speichern bestehende event_id bewahren" entfällt. **AP7** löst das Event-Mapping/-Aufräumen über den vollständigen Kalender-Event-Pull (`gcal.list_app_events`) statt über Tombstone-IDs. Tombstones tragen in AP1 daher `slots: []` (keine event_ids mehr).

---

## Dateistruktur

- `src/storage.py` — Ist-Zeit-Persistenz, Slot-Liste pro Tag + Migration. Verantwortung unverändert (nur Schema).
- `src/reservations.py` — Reservierungs-Persistenz, Slot-Liste pro Tag + neue Migration.
- `tests/test_storage.py` — Storage-API-Tests (umgeschrieben auf Slots).
- `tests/test_storage_migration.py` — Storage-Migrationstests (umgeschrieben + erweitert).
- `tests/test_reservations.py` — Reservations-API-Tests (umgeschrieben auf Slots).
- `tests/test_reservations_migration.py` — **neu**: Reservations-Migrationstests.

Task 1 (Storage) und Task 2 (Reservations) sind unabhängig (getrennte Dateien); ein Reviewer kann eines abnehmen und das andere ablehnen.

---

## Task 1: Storage — Slot-Datenmodell + Migration

**Files:**
- Modify: `src/storage.py` (komplette Neufassung der Methoden, siehe Step 3)
- Test: `tests/test_storage.py` (Neufassung)
- Test: `tests/test_storage_migration.py` (Neufassung)

**Interfaces:**
- Produces (von späteren APs genutzt):
  - `Storage.save(date_str: str, slots: list[dict]) -> None` — Ist-Zeit-Slot `{start, end, pause, kategorie}`; fehlende `pause`→0, `kategorie`→"".
  - `Storage.save_many(updates: dict[str, dict]) -> None` — `updates = {date: {"slots": [...]}}`.
  - `Storage.get(date_str) -> dict | None` — `{"slots": [{start, end, pause, kategorie}, ...]}` (frische Kopien) oder `None` bei Tombstone/fehlend.
  - `Storage.get_all() -> dict[str, dict]` — `{date: {"slots": [...]}}` ohne Tombstones.
  - `Storage.get_all_raw() -> dict` — komplette Roh-Einträge `{date: {"slots": [...], "modified_at", "device_id", "deleted"}}` inkl. Tombstones.
  - `Storage.delete(date_str) -> None` — Tombstone `{"slots": [], "deleted": True, ...}`.
  - `Storage.apply_merge(merged_entries) -> None` — validiert `_REQUIRED_ENTRY_KEYS = {"slots", "modified_at", "device_id", "deleted"}`.

- [ ] **Step 1: `tests/test_storage.py` neu schreiben**

Ersetze den **kompletten** Inhalt von `tests/test_storage.py` durch:

```python
import os
from unittest import mock

import pytest
from src.storage import Storage


@pytest.fixture
def tmp_storage(tmp_path):
    return Storage(str(tmp_path / "test.json"), device_id="test-device")


def _slot(start, end, pause=0, kategorie=""):
    return {"start": start, "end": end, "pause": pause, "kategorie": kategorie}


def test_load_empty(tmp_storage):
    assert tmp_storage.get_all() == {}


def test_save_and_load(tmp_storage):
    tmp_storage.save("2026-03-23", [_slot("08:00", "16:30")])
    entries = tmp_storage.get_all()
    assert entries["2026-03-23"] == {"slots": [_slot("08:00", "16:30")]}


def test_save_multiple_slots(tmp_storage):
    slots = [_slot("08:00", "12:00", 0, "Büro"), _slot("13:00", "17:00", 30, "Homeoffice")]
    tmp_storage.save("2026-03-23", slots)
    assert tmp_storage.get("2026-03-23") == {"slots": slots}


def test_slot_defaults_pause_and_kategorie(tmp_storage):
    tmp_storage.save("2026-03-23", [{"start": "08:00", "end": "16:30"}])
    assert tmp_storage.get("2026-03-23") == {"slots": [_slot("08:00", "16:30", 0, "")]}


def test_delete_entry(tmp_storage):
    tmp_storage.save("2026-03-23", [_slot("08:00", "16:30")])
    tmp_storage.delete("2026-03-23")
    assert "2026-03-23" not in tmp_storage.get_all()


def test_delete_writes_tombstone(tmp_storage):
    tmp_storage.save("2026-03-23", [_slot("08:00", "16:30")])
    tmp_storage.delete("2026-03-23")
    raw = tmp_storage.get_all_raw()["2026-03-23"]
    assert raw["deleted"] is True
    assert raw["slots"] == []


def test_delete_nonexistent(tmp_storage):
    tmp_storage.delete("2026-01-01")  # should not raise
    assert tmp_storage.get_all_raw() == {}


def test_persistence(tmp_path):
    path = str(tmp_path / "test.json")
    s1 = Storage(path)
    s1.save("2026-03-23", [_slot("08:00", "16:30")])
    s2 = Storage(path)
    assert s2.get_all()["2026-03-23"] == {"slots": [_slot("08:00", "16:30")]}


def test_save_with_pause(tmp_storage):
    tmp_storage.save("2026-03-23", [_slot("08:00", "16:30", 30)])
    assert tmp_storage.get("2026-03-23") == {"slots": [_slot("08:00", "16:30", 30)]}


def test_corrupt_json_is_quarantined_and_starts_empty(tmp_path):
    path = tmp_path / "test.json"
    path.write_text("{not valid json", encoding="utf-8")

    storage = Storage(str(path))

    assert storage.get_all() == {}
    quarantined = list(tmp_path.glob("test.json.corrupt-*"))
    assert len(quarantined) == 1
    assert quarantined[0].read_text(encoding="utf-8") == "{not valid json"


def test_save_failure_keeps_original_file_intact(tmp_path):
    path = tmp_path / "test.json"
    storage = Storage(str(path))
    storage.save("2026-03-23", [_slot("08:00", "16:30")])
    original_bytes = path.read_bytes()

    with mock.patch("os.replace", side_effect=OSError("disk full")):
        with pytest.raises(OSError):
            storage.save("2026-03-24", [_slot("09:00", "17:00")])

    assert path.read_bytes() == original_bytes
    leftovers = [p for p in tmp_path.iterdir() if p.suffix == ".tmp"]
    assert leftovers == []


def test_save_does_not_leave_tmp_files(tmp_path):
    path = tmp_path / "test.json"
    storage = Storage(str(path))
    storage.save("2026-03-23", [_slot("08:00", "16:30")])
    storage.save("2026-03-24", [_slot("09:00", "17:00")])

    leftovers = [p.name for p in tmp_path.iterdir() if p.name.endswith(".tmp")]
    assert leftovers == []


def test_save_stamps_modified_at_and_device_id(tmp_path):
    storage = Storage(str(tmp_path / "t.json"), device_id="dev-1")
    storage.save("2026-05-14", [_slot("08:00", "16:00", 30)])
    raw = storage.get_all_raw()
    assert raw["2026-05-14"]["slots"] == [_slot("08:00", "16:00", 30)]
    assert raw["2026-05-14"]["device_id"] == "dev-1"
    assert "T" in raw["2026-05-14"]["modified_at"]
    assert raw["2026-05-14"]["modified_at"].endswith("Z")


def test_get_returns_user_shape_without_metadata(tmp_path):
    storage = Storage(str(tmp_path / "t.json"), device_id="dev-1")
    storage.save("2026-05-14", [_slot("08:00", "16:00", 30)])
    assert storage.get("2026-05-14") == {"slots": [_slot("08:00", "16:00", 30)]}
    assert storage.get_all()["2026-05-14"] == {"slots": [_slot("08:00", "16:00", 30)]}


def test_user_shape_returns_independent_copies(tmp_path):
    """get() darf keine Referenz auf interne Slot-Dicts herausgeben."""
    storage = Storage(str(tmp_path / "t.json"))
    storage.save("2026-05-14", [_slot("08:00", "16:00")])
    got = storage.get("2026-05-14")
    got["slots"][0]["start"] = "00:00"
    assert storage.get("2026-05-14")["slots"][0]["start"] == "08:00"


def test_apply_merge_rejects_entry_missing_required_keys(tmp_path):
    storage = Storage(str(tmp_path / "t.json"), device_id="dev-1")
    with pytest.raises(ValueError, match="missing keys"):
        storage.apply_merge({"2026-05-14": {"slots": [_slot("08:00", "16:00")]}})
    # _data unverändert geblieben (kein Halb-Schreiben)
    assert storage.get_all_raw() == {}


def test_apply_merge_accepts_complete_entries(tmp_path):
    storage = Storage(str(tmp_path / "t.json"), device_id="dev-1")
    storage.apply_merge({"2026-05-14": {
        "slots": [_slot("08:00", "16:00", 30)],
        "modified_at": "2026-05-14T10:00:00Z",
        "device_id": "other-dev",
        "deleted": False,
    }})
    assert storage.get("2026-05-14") == {"slots": [_slot("08:00", "16:00", 30)]}


def test_save_many_empty_is_noop(tmp_path):
    path = str(tmp_path / "noop.json")
    s = Storage(path, device_id="d1")
    s.save_many({})
    assert not os.path.exists(path)


def test_save_many_writes_all_entries(tmp_storage):
    tmp_storage.save_many({
        "2026-05-14": {"slots": [_slot("08:00", "16:00", 30)]},
        "2026-05-15": {"slots": [_slot("09:00", "17:30", 45)]},
    })
    entries = tmp_storage.get_all()
    assert entries["2026-05-14"] == {"slots": [_slot("08:00", "16:00", 30)]}
    assert entries["2026-05-15"] == {"slots": [_slot("09:00", "17:30", 45)]}


def test_save_many_sets_metadata(tmp_storage):
    tmp_storage.save_many({"2026-05-14": {"slots": [_slot("08:00", "16:00", 30)]}})
    raw = tmp_storage.get_all_raw()["2026-05-14"]
    assert raw["device_id"] == "test-device"
    assert raw["deleted"] is False
    assert "modified_at" in raw and raw["modified_at"]


def test_save_many_overwrites_tombstone(tmp_storage):
    tmp_storage.save("2026-05-14", [_slot("08:00", "16:00", 30)])
    tmp_storage.delete("2026-05-14")
    assert tmp_storage.get("2026-05-14") is None
    tmp_storage.save_many({"2026-05-14": {"slots": [_slot("09:00", "17:00")]}})
    assert tmp_storage.get("2026-05-14") == {"slots": [_slot("09:00", "17:00")]}


def test_save_many_calls_disk_write_once(tmp_storage):
    with mock.patch.object(tmp_storage, "_save_to_disk") as m:
        tmp_storage.save_many({
            "2026-05-14": {"slots": [_slot("08:00", "16:00", 30)]},
            "2026-05-15": {"slots": [_slot("09:00", "17:30", 45)]},
        })
    assert m.call_count == 1


def test_save_many_slot_defaults(tmp_storage):
    tmp_storage.save_many({"2026-05-14": {"slots": [{"start": "08:00", "end": "16:00"}]}})
    slot = tmp_storage.get_all()["2026-05-14"]["slots"][0]
    assert slot["pause"] == 0
    assert slot["kategorie"] == ""
```

- [ ] **Step 2: `tests/test_storage_migration.py` neu schreiben**

Ersetze den **kompletten** Inhalt von `tests/test_storage_migration.py` durch:

```python
import json
import os

from src.storage import Storage


def _write_legacy_json(tmp_path, payload):
    path = tmp_path / "legacy.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f)
    return str(path)


def test_legacy_entry_wrapped_into_single_slot(tmp_path):
    """Alter Ein-Eintrag-Tag ohne Metadaten → 1-Slot-Liste + Sync-Metadaten."""
    path = _write_legacy_json(tmp_path, {
        "2026-03-23": {"start": "08:00", "end": "16:30", "pause": 30},
    })
    storage = Storage(path, device_id="dev-1")
    raw = storage.get_all_raw()["2026-03-23"]
    assert raw["slots"] == [{"start": "08:00", "end": "16:30", "pause": 30, "kategorie": ""}]
    assert raw["device_id"] == "dev-1"
    assert raw["deleted"] is False
    assert raw["modified_at"].endswith("Z")
    # alte Top-Level-Zeitfelder entfernt
    assert "start" not in raw and "end" not in raw and "pause" not in raw


def test_legacy_modified_at_uses_file_mtime(tmp_path):
    """Migrationszeitpunkt = mtime der Legacy-Datei (best lower bound)."""
    path = _write_legacy_json(tmp_path, {
        "2026-03-23": {"start": "08:00", "end": "16:30", "pause": 30},
    })
    fixed_mtime = 1_700_000_000  # 2023-11-14T22:13:20Z
    os.utime(path, (fixed_mtime, fixed_mtime))
    storage = Storage(path, device_id="dev-1")
    assert storage.get_all_raw()["2026-03-23"]["modified_at"] == "2023-11-14T22:13:20Z"


def test_user_facing_get_all_after_migration(tmp_path):
    """UI-Code sieht nach Migration die Slot-Shape."""
    path = _write_legacy_json(tmp_path, {
        "2026-03-23": {"start": "08:00", "end": "16:30", "pause": 30},
    })
    storage = Storage(path, device_id="dev-1")
    assert storage.get_all() == {
        "2026-03-23": {"slots": [{"start": "08:00", "end": "16:30", "pause": 30, "kategorie": ""}]}
    }


def test_v2_entry_with_metadata_gets_slot_wrapped_keeping_metadata(tmp_path):
    """v2-Eintrag (Metadaten da, aber kein slots-Key) wird in Slots gewrappt;
    modified_at/device_id bleiben erhalten (keine Re-Stampelung)."""
    path = _write_legacy_json(tmp_path, {
        "2026-03-23": {
            "start": "08:00", "end": "16:30", "pause": 30,
            "modified_at": "2026-05-01T10:00:00Z",
            "device_id": "other-device",
            "deleted": False,
        },
    })
    storage = Storage(path, device_id="dev-1")
    raw = storage.get_all_raw()["2026-03-23"]
    assert raw["slots"] == [{"start": "08:00", "end": "16:30", "pause": 30, "kategorie": ""}]
    assert raw["modified_at"] == "2026-05-01T10:00:00Z"
    assert raw["device_id"] == "other-device"


def test_legacy_tombstone_becomes_empty_slots(tmp_path):
    """Alt-Tombstone (deleted=true, start=null) → slots=[]."""
    path = _write_legacy_json(tmp_path, {
        "2026-03-23": {
            "start": None, "end": None, "pause": None,
            "modified_at": "2026-05-01T10:00:00Z",
            "device_id": "other-device",
            "deleted": True,
        },
    })
    storage = Storage(path, device_id="dev-1")
    raw = storage.get_all_raw()["2026-03-23"]
    assert raw["slots"] == []
    assert raw["deleted"] is True


def test_migration_idempotent_after_persist(tmp_path):
    """Zweites Laden einer bereits migrierten Datei wrappt nicht erneut."""
    path = _write_legacy_json(tmp_path, {
        "2026-03-23": {"start": "08:00", "end": "16:30", "pause": 30},
    })
    s1 = Storage(path, device_id="dev-1")
    s1._save_to_disk()  # migrierte Form persistieren
    s2 = Storage(path, device_id="dev-1")
    raw = s2.get_all_raw()["2026-03-23"]
    assert raw["slots"] == [{"start": "08:00", "end": "16:30", "pause": 30, "kategorie": ""}]
    # Slot ist nicht doppelt verschachtelt
    assert "slots" not in raw["slots"][0]
```

- [ ] **Step 3: Beide Storage-Testdateien laufen lassen — müssen FEHLSCHLAGEN**

Run: `python -m pytest tests/test_storage.py tests/test_storage_migration.py -q`
Expected: FAIL (altes `storage.py` kennt die Slot-API/Migration noch nicht — u.a. `TypeError`/`AssertionError`/`KeyError`).

- [ ] **Step 4: `src/storage.py` neu schreiben**

Ersetze den **kompletten** Inhalt von `src/storage.py` durch:

```python
import datetime
import json
import os


def _utc_now_iso():
    # Z-Suffix statt +00:00 — kompatibel zu JS/Drive-Konventionen
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


_REQUIRED_ENTRY_KEYS = frozenset({"slots", "modified_at", "device_id", "deleted"})


def _normalize_slot(slot):
    """Vervollständigt einen Ist-Zeit-Slot auf {start, end, pause, kategorie}.

    Fehlende `pause` → 0, fehlende `kategorie` → "" (= keine Kategorie,
    Verhalten wie vor der Migration). Storage validiert die Zeitwerte
    bewusst nicht (wie bisher) — das ist Sache der UI/Validierung (AP3)."""
    return {
        "start": slot.get("start"),
        "end": slot.get("end"),
        "pause": slot.get("pause", 0),
        "kategorie": slot.get("kategorie", ""),
    }


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
            return
        self._migrate_legacy_entries()

    def _migrate_legacy_entries(self):
        """Rüstet Sync-Metadaten nach UND wrappt alte Ein-Eintrag-Tage in eine
        Slot-Liste. Idempotent: Einträge mit `slots` bleiben unangetastet,
        Einträge mit `modified_at` behalten ihre Metadaten.
        modified_at wird (für ganz alte Einträge ohne Metadaten) aus der
        File-mtime abgeleitet (best lower bound)."""
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
            # 1. Sync-Metadaten für ganz alte Einträge nachrüsten.
            if "modified_at" not in entry:
                entry["modified_at"] = fallback_modified_at
                entry["device_id"] = self.device_id
                entry.setdefault("deleted", False)
            # 2. Slot-Wrapping für Einträge im alten Ein-Eintrag-Schema.
            if "slots" not in entry:
                if entry.get("deleted"):
                    entry["slots"] = []
                else:
                    entry["slots"] = [{
                        "start": entry.get("start"),
                        "end": entry.get("end"),
                        "pause": entry.get("pause", 0),
                        "kategorie": "",
                    }]
                entry.pop("start", None)
                entry.pop("end", None)
                entry.pop("pause", None)

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
        """Reduziert ein Roh-Entry auf {slots: [...]} für UI-Caller.
        Liefert frische Kopien, damit Caller den internen Stand nicht mutieren."""
        return {"slots": [dict(s) for s in entry.get("slots", [])]}

    def get_all(self):
        """Liefert {date: {slots: [...]}} ohne Tombstones."""
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

    def save(self, date_str, slots):
        self._data[date_str] = {
            "slots": [_normalize_slot(s) for s in slots],
            "modified_at": _utc_now_iso(),
            "device_id": self.device_id,
            "deleted": False,
        }
        self._save_to_disk()

    def delete(self, date_str):
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

- [ ] **Step 5: Storage-Tests laufen lassen — müssen BESTEHEN**

Run: `python -m pytest tests/test_storage.py tests/test_storage_migration.py -q`
Expected: PASS (alle Tests grün).

- [ ] **Step 6: Commit**

```bash
git add src/storage.py tests/test_storage.py tests/test_storage_migration.py
git commit -m "feat(storage): Multi-Slot-Datenmodell pro Tag + Migration (#53)

Storage speichert pro Tag eine Slot-Liste ({start,end,pause,kategorie})
statt eines einzelnen Eintrags. Legacy-Einträge (mit/ohne Sync-Metadaten)
werden idempotent in eine 1-Slot-Liste migriert, Tombstones in slots=[].
Teil von AP1; harter Schnitt, Consumer-Pakete folgen.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 2: Reservations — Slot-Datenmodell + Migration

**Files:**
- Modify: `src/reservations.py` (komplette Neufassung, siehe Step 4)
- Test: `tests/test_reservations.py` (Neufassung)
- Create: `tests/test_reservations_migration.py`

**Interfaces:**
- Consumes: nichts aus Task 1 (eigenständige Datei).
- Produces (von späteren APs, v.a. AP3/AP7, genutzt):
  - `ReservationStore.save(date_str: str, slots: list[dict]) -> None` — Reservierungs-Slot `{start, end, kategorie, gcal_event_id}`; fehlende `kategorie`→"", `gcal_event_id`→None.
  - `ReservationStore.get(date_str) -> dict | None` — **User-Shape** `{"slots": [{start, end, kategorie}, ...]}` (ohne `gcal_event_id`) oder `None`.
  - `ReservationStore.get_all() -> dict` — `{date: {"slots": [{start, end, kategorie}]}}` ohne Tombstones.
  - `ReservationStore.get_all_raw() -> dict` — komplette Roh-Einträge inkl. `gcal_event_id` pro Slot und Metadaten/Tombstones (für Reconcile, AP7).
  - `ReservationStore.delete(date_str) -> None` — Tombstone `{"slots": [], "deleted": True, ...}`.
  - `ReservationStore.apply_reconciled(reconciled) -> None` — validiert `_REQUIRED_RESERVATION_KEYS = {"slots", "modified_at", "deleted"}`.

- [ ] **Step 1: `tests/test_reservations.py` neu schreiben**

Ersetze den **kompletten** Inhalt von `tests/test_reservations.py` durch:

```python
from unittest import mock

import pytest
from src.reservations import ReservationStore


@pytest.fixture
def store(tmp_path):
    return ReservationStore(str(tmp_path / "res.json"))


def _slot(start, end, kategorie="", gcal_event_id=None):
    """Roh-Slot (inkl. gcal_event_id), wie er in get_all_raw erscheint."""
    return {"start": start, "end": end, "kategorie": kategorie, "gcal_event_id": gcal_event_id}


def _ushape(*slots):
    """Erwartete User-Shape: slots ohne gcal_event_id."""
    return {"slots": [{"start": s["start"], "end": s["end"], "kategorie": s["kategorie"]}
                      for s in slots]}


def test_load_empty(store):
    assert store.get_all() == {}


def test_save_and_get(store):
    store.save("2026-06-01", [_slot("09:00", "17:00")])
    assert store.get("2026-06-01") == _ushape(_slot("09:00", "17:00"))
    assert store.get_all() == {"2026-06-01": _ushape(_slot("09:00", "17:00"))}


def test_save_multiple_slots_with_categories(store):
    slots = [_slot("09:00", "12:00", "Kundentermin"), _slot("13:00", "17:00", "Büro")]
    store.save("2026-06-01", slots)
    assert store.get("2026-06-01") == _ushape(*slots)


def test_save_stamps_metadata(store):
    store.save("2026-06-01", [_slot("09:00", "17:00")])
    raw = store.get_all_raw()["2026-06-01"]
    assert raw["deleted"] is False
    assert raw["modified_at"].endswith("Z") and "T" in raw["modified_at"]


def test_save_stores_provided_event_id(store):
    """save speichert eine mitgelieferte gcal_event_id am Slot. Der Erhalt
    bestehender event_ids über Edits ist Sache des Reconcile (AP7)."""
    store.save("2026-06-01", [_slot("09:00", "17:00", "", "ev-1")])
    assert store.get_all_raw()["2026-06-01"]["slots"][0]["gcal_event_id"] == "ev-1"


def test_slot_defaults_kategorie_and_event_id(store):
    store.save("2026-06-01", [{"start": "09:00", "end": "17:00"}])
    slot = store.get_all_raw()["2026-06-01"]["slots"][0]
    assert slot["gcal_event_id"] is None
    assert slot["kategorie"] == ""


def test_user_shape_excludes_event_id(store):
    store.save("2026-06-01", [_slot("09:00", "17:00", "Büro", "ev-1")])
    assert store.get("2026-06-01") == {"slots": [{"start": "09:00", "end": "17:00", "kategorie": "Büro"}]}


def test_delete_writes_empty_slots_tombstone(store):
    store.save("2026-06-01", [_slot("09:00", "17:00", "", "ev-1")])
    store.delete("2026-06-01")
    assert store.get("2026-06-01") is None
    tomb = store.get_all_raw()["2026-06-01"]
    assert tomb["deleted"] is True
    assert tomb["slots"] == []


def test_delete_nonexistent_is_noop(store):
    store.delete("2026-01-01")
    assert store.get_all_raw() == {}


def test_get_excludes_tombstones(store):
    store.save("2026-06-01", [_slot("09:00", "17:00")])
    store.delete("2026-06-01")
    assert "2026-06-01" not in store.get_all()
    assert "2026-06-01" in store.get_all_raw()


def test_persistence(tmp_path):
    path = str(tmp_path / "res.json")
    ReservationStore(path).save("2026-06-01", [_slot("09:00", "17:00")])
    assert ReservationStore(path).get("2026-06-01") == _ushape(_slot("09:00", "17:00"))


def test_apply_reconciled_replaces_data(store):
    store.save("2026-06-01", [_slot("09:00", "17:00")])
    store.apply_reconciled({"2026-07-01": {
        "slots": [_slot("10:00", "18:00", "", "ev-9")],
        "modified_at": "2026-05-20T10:00:00Z", "deleted": False,
    }})
    assert "2026-06-01" not in store.get_all_raw()
    assert store.get("2026-07-01") == _ushape(_slot("10:00", "18:00"))


def test_apply_reconciled_rejects_missing_keys(store):
    with pytest.raises(ValueError, match="missing keys"):
        store.apply_reconciled({"2026-06-01": {"slots": [_slot("09:00", "17:00")]}})
    # _data unverändert (kein Halb-Schreiben)
    assert store.get_all_raw() == {}


def test_corrupt_json_is_quarantined_and_starts_empty(tmp_path):
    path = tmp_path / "res.json"
    path.write_text("{not valid", encoding="utf-8")
    store = ReservationStore(str(path))
    assert store.get_all() == {}
    assert len(list(tmp_path.glob("res.json.corrupt-*"))) == 1


def test_save_failure_keeps_original_intact(tmp_path):
    path = tmp_path / "res.json"
    store = ReservationStore(str(path))
    store.save("2026-06-01", [_slot("09:00", "17:00")])
    original = path.read_bytes()
    with mock.patch("os.replace", side_effect=OSError("disk full")):
        with pytest.raises(OSError):
            store.save("2026-06-02", [_slot("09:00", "17:00")])
    assert path.read_bytes() == original
    assert [p for p in tmp_path.iterdir() if p.suffix == ".tmp"] == []
```

- [ ] **Step 2: `tests/test_reservations_migration.py` neu anlegen**

Lege `tests/test_reservations_migration.py` mit folgendem Inhalt an:

```python
import json

from src.reservations import ReservationStore


def _write_legacy(tmp_path, payload):
    path = tmp_path / "legacy_res.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f)
    return str(path)


def test_legacy_reservation_wrapped_into_single_slot(tmp_path):
    path = _write_legacy(tmp_path, {
        "2026-06-01": {
            "start": "09:00", "end": "17:00",
            "modified_at": "2026-05-20T10:00:00Z",
            "deleted": False, "gcal_event_id": "ev-1",
        },
    })
    store = ReservationStore(path)
    raw = store.get_all_raw()["2026-06-01"]
    assert raw["slots"] == [
        {"start": "09:00", "end": "17:00", "kategorie": "", "gcal_event_id": "ev-1"}
    ]
    assert raw["modified_at"] == "2026-05-20T10:00:00Z"
    assert raw["deleted"] is False
    # alte Top-Level-Felder entfernt
    assert "start" not in raw and "end" not in raw and "gcal_event_id" not in raw


def test_legacy_reservation_tombstone_becomes_empty_slots(tmp_path):
    path = _write_legacy(tmp_path, {
        "2026-06-01": {
            "start": None, "end": None,
            "modified_at": "2026-05-20T10:00:00Z",
            "deleted": True, "gcal_event_id": "ev-1",
        },
    })
    store = ReservationStore(path)
    raw = store.get_all_raw()["2026-06-01"]
    assert raw["slots"] == []
    assert raw["deleted"] is True


def test_user_facing_get_all_after_migration(tmp_path):
    path = _write_legacy(tmp_path, {
        "2026-06-01": {
            "start": "09:00", "end": "17:00",
            "modified_at": "2026-05-20T10:00:00Z",
            "deleted": False, "gcal_event_id": None,
        },
    })
    store = ReservationStore(path)
    assert store.get_all() == {
        "2026-06-01": {"slots": [{"start": "09:00", "end": "17:00", "kategorie": ""}]}
    }


def test_reservation_migration_idempotent_after_persist(tmp_path):
    path = _write_legacy(tmp_path, {
        "2026-06-01": {
            "start": "09:00", "end": "17:00",
            "modified_at": "2026-05-20T10:00:00Z",
            "deleted": False, "gcal_event_id": "ev-1",
        },
    })
    s1 = ReservationStore(path)
    s1._save_to_disk()  # migrierte Form persistieren
    s2 = ReservationStore(path)
    raw = s2.get_all_raw()["2026-06-01"]
    assert raw["slots"] == [
        {"start": "09:00", "end": "17:00", "kategorie": "", "gcal_event_id": "ev-1"}
    ]
    assert "slots" not in raw["slots"][0]
```

- [ ] **Step 3: Beide Reservations-Testdateien laufen lassen — müssen FEHLSCHLAGEN**

Run: `python -m pytest tests/test_reservations.py tests/test_reservations_migration.py -q`
Expected: FAIL (altes `reservations.py` kennt Slot-API/Migration noch nicht).

- [ ] **Step 4: `src/reservations.py` neu schreiben**

Ersetze den **kompletten** Inhalt von `src/reservations.py` durch:

```python
"""JSON-Persistenz der Reservierungen (geplante Arbeitszeiten).

Reservierungen sind ein eigenständiges Konzept neben den erfassten Ist-Zeiten
(`storage.py`). Sie werden über `gcal.py` / `reservations_sync.py` mit einem
Google Kalender abgeglichen — NICHT über die Drive-Multi-Device-Sync. Daher
fehlt hier (anders als bei `Storage`) das `device_id`-Feld.

Schema pro Tag (ISO-Datum als Schlüssel):
    {slots: [{start, end, kategorie, gcal_event_id}], modified_at, deleted}
`gcal_event_id` ist None, bis der Slot erstmals in den Kalender gepusht wurde.
Eine gelöschte Reservierung bleibt als Tombstone (deleted=True, slots=[])
erhalten, bis der Reconcile die zugehörigen Events entfernt hat.
"""

import datetime
import json
import os


def _utc_now_iso():
    # Z-Suffix statt +00:00 — konsistent zu storage.py / sync.py.
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


_REQUIRED_RESERVATION_KEYS = frozenset({"slots", "modified_at", "deleted"})


def _normalize_slot(slot):
    """Vervollständigt einen Reservierungs-Slot auf
    {start, end, kategorie, gcal_event_id}. Fehlende `kategorie` → "",
    fehlende `gcal_event_id` → None."""
    return {
        "start": slot.get("start"),
        "end": slot.get("end"),
        "kategorie": slot.get("kategorie", ""),
        "gcal_event_id": slot.get("gcal_event_id"),
    }


class ReservationStore:
    def __init__(self, filepath="reservations.json"):
        self.filepath = filepath
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
            return
        self._migrate_legacy_reservations()

    def _migrate_legacy_reservations(self):
        """Wrappt alte Ein-Reservierung-Tage in eine Slot-Liste. Idempotent:
        Einträge mit `slots` bleiben unangetastet. modified_at/deleted werden
        nur gesetzt, falls sie fehlen (alte Dateien tragen sie i.d.R. bereits);
        Fallback ist die File-mtime (best lower bound)."""
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
            if "slots" in entry:
                continue
            if entry.get("deleted"):
                entry["slots"] = []
            else:
                entry["slots"] = [{
                    "start": entry.get("start"),
                    "end": entry.get("end"),
                    "kategorie": "",
                    "gcal_event_id": entry.get("gcal_event_id"),
                }]
            entry.pop("start", None)
            entry.pop("end", None)
            entry.pop("gcal_event_id", None)
            entry.setdefault("modified_at", fallback_modified_at)
            entry.setdefault("deleted", False)

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
        """User-Shape: Slots ohne das interne Feld gcal_event_id."""
        return {"slots": [
            {"start": s.get("start"), "end": s.get("end"), "kategorie": s.get("kategorie", "")}
            for s in entry.get("slots", [])
        ]}

    def get_all(self):
        """{date: {slots: [...]}} ohne Tombstones — für die UI."""
        return {
            date: self._user_shape(entry)
            for date, entry in self._data.items()
            if not entry.get("deleted")
        }

    def get_all_raw(self):
        """Komplette Objekte inkl. Metadaten, gcal_event_id und Tombstones —
        für den Reconcile."""
        return dict(self._data)

    def get(self, date_str):
        entry = self._data.get(date_str)
        if entry is None or entry.get("deleted"):
            return None
        return self._user_shape(entry)

    def save(self, date_str, slots):
        """Legt die Reservierungs-Slots eines Tages an oder überschreibt sie.
        Die übergebenen Slots werden so gespeichert, wie sie sind (inkl.
        mitgelieferter gcal_event_id). Das Bewahren bestehender event_ids über
        Edits hinweg übernimmt der Reconcile (AP7), nicht dieser save-Pfad."""
        self._data[date_str] = {
            "slots": [_normalize_slot(s) for s in slots],
            "modified_at": _utc_now_iso(),
            "deleted": False,
        }
        self._save_to_disk()

    def delete(self, date_str):
        """Tombstone schreiben (slots=[]). Der Reconcile entfernt die
        zugehörigen Kalender-Events über den vollständigen Event-Pull (AP7)."""
        if date_str not in self._data:
            return
        self._data[date_str] = {
            "slots": [],
            "modified_at": _utc_now_iso(),
            "deleted": True,
        }
        self._save_to_disk()

    def apply_reconciled(self, reconciled):
        """Ersetzt den kompletten Stand durch das Reconcile-Ergebnis.
        Wirft ValueError, wenn ein Eintrag Pflichtfelder vermissen lässt —
        analog zu Storage.apply_merge."""
        for date, entry in reconciled.items():
            missing = _REQUIRED_RESERVATION_KEYS - entry.keys()
            if missing:
                raise ValueError(
                    f"apply_reconciled: entry {date!r} missing keys {sorted(missing)}"
                )
        self._data = dict(reconciled)
        self._save_to_disk()
```

- [ ] **Step 5: Reservations-Tests laufen lassen — müssen BESTEHEN**

Run: `python -m pytest tests/test_reservations.py tests/test_reservations_migration.py -q`
Expected: PASS (alle Tests grün).

- [ ] **Step 6: AP1-Gesamtverifikation (nur AP1-Dateien)**

Run: `python -m pytest tests/test_storage.py tests/test_storage_migration.py tests/test_reservations.py tests/test_reservations_migration.py -q`
Expected: PASS.

> **Hinweis:** Ein voller `pytest`-Lauf ist an dieser Stelle **erwartbar rot** (Consumer wie `report.py`, `share.py`, `sync.py`, `ui.py` und deren Tests nutzen noch die alte Signatur). Das ist der bewusste harte Schnitt — die Suite wird durch AP2–AP7 wieder grün. AP1 verifiziert nur die vier obigen Dateien.

- [ ] **Step 7: Commit**

```bash
git add src/reservations.py tests/test_reservations.py tests/test_reservations_migration.py
git commit -m "feat(reservations): Multi-Slot-Datenmodell pro Tag + Migration (#53)

ReservationStore speichert pro Tag eine Slot-Liste
({start,end,kategorie,gcal_event_id}). Legacy-Reservierungen werden
idempotent in eine 1-Slot-Liste migriert, Tombstones in slots=[].
User-Shape blendet gcal_event_id aus. event_id-Erhalt über Edits wandert
in den Reconcile (AP7). Teil von AP1.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Self-Review

**1. Spec-Coverage (AP1-Scope):**
- Storage Slot-Liste pro Tag → Task 1 ✓
- Storage-Migration (lebend + Tombstone + v2-mit-Metadaten) idempotent → Task 1, Step 2/4 ✓
- Reservations Slot-Liste + `gcal_event_id` pro Slot → Task 2 ✓
- Reservations-Migration → Task 2 ✓
- `_REQUIRED_*`-Keys auf neues Schema → beide Tasks ✓
- Kategorie als String, `""` = keine → `_normalize_slot` + Migration ✓
- Pause pro Ist-Zeit-Slot, kein Pause bei Reservierung → Slot-Schemata ✓
- Nicht in AP1 (korrekt ausgelassen): Non-Overlap-Validierung (AP3), Sync-Schema-Bump/`_values_equal_entry` (AP2), gcal-Reconcile (AP7), Consumer-Anpassungen (AP3–7).

**2. Placeholder-Scan:** Keine TBD/TODO/„später"; jeder Code- und Test-Step zeigt vollständigen Inhalt. ✓

**3. Typ-Konsistenz:**
- `Storage.save(date, slots)` / `save_many({date:{"slots":[...]}})` — konsistent zwischen Interface-Block, Code und Tests. ✓
- Ist-Zeit-Slot `{start,end,pause,kategorie}` vs. Reservierungs-Slot `{start,end,kategorie,gcal_event_id}` — durchgängig getrennt. ✓
- Reservations-User-Shape ohne `gcal_event_id`, Raw mit — in Code (`_user_shape`/`get_all_raw`) und Tests (`_ushape` vs. `_slot`) konsistent. ✓
- `_REQUIRED_ENTRY_KEYS = {slots,modified_at,device_id,deleted}`, `_REQUIRED_RESERVATION_KEYS = {slots,modified_at,deleted}` — wie in den `apply_*`-Tests erwartet. ✓
