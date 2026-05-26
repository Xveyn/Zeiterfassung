# Arbeitszeiten teilen + importieren — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** User können ihre Arbeitszeiten als JSON-Anhang per Gmail an eine zweite Person schicken; Empfänger:in importiert sie mit Zeitraum-Filter und drei Konflikt-Modi atomar in die eigene Zeiterfassung.

**Architecture:** Pures `src/share.py` für Build/Parse/Diff/Apply, zwei neue Dialoge (`share_dialog`, `import_dialog`), neue `Storage.save_many()` für atomaren File-Write. Wire-Format ist eigenständig (`kind: "zeiterfassung-share"`), bewusst getrennt vom Multi-Device-Sync-Doc.

**Tech Stack:** Python 3, Tkinter, json (stdlib), Gmail API (bestehend), pytest.

**Spec:** [`docs/superpowers/specs/2026-05-18-share-entries-design.md`](../specs/2026-05-18-share-entries-design.md)

---

## File Structure

**Neu:**
- `src/share.py` — pure functions: `build_share_doc`, `serialize_share_doc`, `parse_share_doc`, `diff_share_against_local`, `apply_import`, `ShareValidationError`
- `src/dialogs/share_dialog.py` — Export-Dialog „Arbeitszeiten teilen"
- `src/dialogs/import_dialog.py` — Import-Dialog mit Zeitraum-Filter + Summary + Pro-Tag-Modal
- `tests/test_share.py` — pure-function-Tests

**Modifiziert:**
- `src/storage.py` — neue Methode `save_many()`
- `src/settings.py` — neuer Default-Key `share_recipient`
- `src/dialogs/settings_dialog.py` — neues Feld „Teilen mit:", Button „Arbeitszeiten importieren…"
- `src/mail.py` — `send_email` Signatur generalisiert (Attachment-Subtype konfigurierbar)
- `src/dialogs/send_dialog.py` — Aufruf an `send_email` an neue Signatur angepasst
- `src/ui.py` — Footer-Button „Teilen…"
- `tests/test_storage.py` — Tests für `save_many`
- `CHANGELOG.md` — Eintrag

---

## Task 1: `Storage.save_many()` — atomarer Multi-Entry-Write

**Files:**
- Modify: `src/storage.py`
- Test: `tests/test_storage.py`

- [ ] **Step 1: Write failing tests for save_many**

Append at the end of `tests/test_storage.py`:

```python
def test_save_many_empty_is_noop(tmp_path):
    """Leeres Dict darf keinen File-Write triggern."""
    path = str(tmp_path / "noop.json")
    s = Storage(path, device_id="d1")
    s.save_many({})
    assert not os.path.exists(path)


def test_save_many_writes_all_entries(tmp_storage):
    tmp_storage.save_many({
        "2026-05-14": {"start": "08:00", "end": "16:00", "pause": 30},
        "2026-05-15": {"start": "09:00", "end": "17:30", "pause": 45},
    })
    entries = tmp_storage.get_all()
    assert entries["2026-05-14"] == {"start": "08:00", "end": "16:00", "pause": 30}
    assert entries["2026-05-15"] == {"start": "09:00", "end": "17:30", "pause": 45}


def test_save_many_sets_metadata(tmp_storage):
    tmp_storage.save_many({"2026-05-14": {"start": "08:00", "end": "16:00", "pause": 30}})
    raw = tmp_storage.get_all_raw()["2026-05-14"]
    assert raw["device_id"] == "test-device"
    assert raw["deleted"] is False
    assert "modified_at" in raw and raw["modified_at"]


def test_save_many_overwrites_tombstone(tmp_storage):
    tmp_storage.save("2026-05-14", "08:00", "16:00", 30)
    tmp_storage.delete("2026-05-14")
    assert tmp_storage.get("2026-05-14") is None
    tmp_storage.save_many({"2026-05-14": {"start": "09:00", "end": "17:00", "pause": 0}})
    assert tmp_storage.get("2026-05-14") == {"start": "09:00", "end": "17:00", "pause": 0}


def test_save_many_calls_disk_write_once(tmp_storage):
    with mock.patch.object(tmp_storage, "_save_to_disk") as m:
        tmp_storage.save_many({
            "2026-05-14": {"start": "08:00", "end": "16:00", "pause": 30},
            "2026-05-15": {"start": "09:00", "end": "17:30", "pause": 45},
        })
    assert m.call_count == 1


def test_save_many_pause_default_zero(tmp_storage):
    """Pause-Feld fehlt → wird auf 0 default-gesetzt (analog zu save())."""
    tmp_storage.save_many({"2026-05-14": {"start": "08:00", "end": "16:00"}})
    assert tmp_storage.get_all()["2026-05-14"]["pause"] == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_storage.py -k save_many -v`
Expected: All six FAIL with `AttributeError: 'Storage' object has no attribute 'save_many'`.

- [ ] **Step 3: Implement save_many in src/storage.py**

Append after the `apply_merge` method (around line 130):

```python
    def save_many(self, updates):
        """Mehrere Einträge in einem einzigen Disk-Write speichern.

        updates: {date_str: {start, end, pause}}. Jeder Eintrag bekommt
        frische modified_at/device_id/deleted=False. Existierende Tombstones
        am selben Datum werden überschrieben.

        Leeres Dict ist No-op (kein Disk-Roundtrip).
        """
        if not updates:
            return
        now = _utc_now_iso()
        for date_str, payload in updates.items():
            self._data[date_str] = {
                "start": payload["start"],
                "end": payload["end"],
                "pause": payload.get("pause", 0),
                "modified_at": now,
                "device_id": self.device_id,
                "deleted": False,
            }
        self._save_to_disk()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_storage.py -v`
Expected: All tests PASS (including the existing ones).

- [ ] **Step 5: Commit**

```bash
git add src/storage.py tests/test_storage.py
git commit -m "feat(storage): save_many for atomic multi-entry writes

Single tmp+replace pass für N entries — Grundlage für atomaren Import
aus Share-Files.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 2: `ShareValidationError` + `parse_share_doc` (reject path)

**Files:**
- Create: `src/share.py`
- Test: `tests/test_share.py`

- [ ] **Step 1: Write failing reject-tests**

Create `tests/test_share.py`:

```python
import json

import pytest

from src.share import ShareValidationError, parse_share_doc


def _bytes(obj):
    return json.dumps(obj).encode("utf-8")


def test_parse_rejects_broken_json():
    with pytest.raises(ShareValidationError, match="JSON"):
        parse_share_doc(b"{not json")


def test_parse_rejects_non_object_toplevel():
    with pytest.raises(ShareValidationError, match="JSON-Objekt"):
        parse_share_doc(_bytes(["array", "instead"]))


def test_parse_rejects_wrong_kind():
    with pytest.raises(ShareValidationError, match="geteilte Zeiterfassung"):
        parse_share_doc(_bytes({"kind": "something-else", "schema_version": 1, "entries": {}}))


def test_parse_rejects_missing_kind():
    with pytest.raises(ShareValidationError, match="geteilte Zeiterfassung"):
        parse_share_doc(_bytes({"schema_version": 1, "entries": {}}))


def test_parse_rejects_missing_schema_version():
    with pytest.raises(ShareValidationError, match="schema_version"):
        parse_share_doc(_bytes({"kind": "zeiterfassung-share", "entries": {}}))


def test_parse_rejects_future_schema_version():
    with pytest.raises(ShareValidationError, match="neueren Version"):
        parse_share_doc(_bytes({
            "kind": "zeiterfassung-share",
            "schema_version": 2,
            "entries": {},
        }))


def test_parse_rejects_missing_entries():
    with pytest.raises(ShareValidationError, match="entries"):
        parse_share_doc(_bytes({"kind": "zeiterfassung-share", "schema_version": 1}))


def test_parse_rejects_bad_date_key():
    with pytest.raises(ShareValidationError, match="Datum"):
        parse_share_doc(_bytes({
            "kind": "zeiterfassung-share",
            "schema_version": 1,
            "entries": {"not-a-date": {"start": "08:00", "end": "16:00", "pause": 0}},
        }))


def test_parse_rejects_extra_entry_field():
    with pytest.raises(ShareValidationError, match="unbekannt"):
        parse_share_doc(_bytes({
            "kind": "zeiterfassung-share",
            "schema_version": 1,
            "entries": {"2026-05-14": {"start": "08:00", "end": "16:00", "pause": 0, "deleted": True}},
        }))


def test_parse_rejects_missing_entry_field():
    with pytest.raises(ShareValidationError, match="fehlend"):
        parse_share_doc(_bytes({
            "kind": "zeiterfassung-share",
            "schema_version": 1,
            "entries": {"2026-05-14": {"start": "08:00", "end": "16:00"}},
        }))


def test_parse_rejects_bad_time_format():
    with pytest.raises(ShareValidationError, match="Startzeit"):
        parse_share_doc(_bytes({
            "kind": "zeiterfassung-share",
            "schema_version": 1,
            "entries": {"2026-05-14": {"start": "8:00", "end": "16:00", "pause": 0}},
        }))


def test_parse_rejects_negative_pause():
    with pytest.raises(ShareValidationError, match="Pause"):
        parse_share_doc(_bytes({
            "kind": "zeiterfassung-share",
            "schema_version": 1,
            "entries": {"2026-05-14": {"start": "08:00", "end": "16:00", "pause": -5}},
        }))


def test_parse_rejects_bool_as_pause():
    """bool ist Subklasse von int — verhindern, dass True als pause=1 durchgeht."""
    with pytest.raises(ShareValidationError, match="Pause"):
        parse_share_doc(_bytes({
            "kind": "zeiterfassung-share",
            "schema_version": 1,
            "entries": {"2026-05-14": {"start": "08:00", "end": "16:00", "pause": True}},
        }))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_share.py -v`
Expected: All FAIL with `ImportError` (module nicht existiert).

- [ ] **Step 3: Create src/share.py with validation**

Create `src/share.py`:

```python
"""Arbeitszeiten teilen + importieren — pure functions, kein UI-Import.

Wire-Format (eigenständig, kein Sync-Doc-Re-Use):
{
  "schema_version": 1,
  "kind": "zeiterfassung-share",
  "exported_at": "<UTC-ISO>",
  "exported_by": "<email or empty>",
  "entries": {"YYYY-MM-DD": {"start": "HH:MM", "end": "HH:MM", "pause": int>=0}}
}
"""

import datetime
import json
import re


SCHEMA_VERSION = 1
KIND = "zeiterfassung-share"

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_TIME_RE = re.compile(r"^\d{2}:\d{2}$")
_ENTRY_KEYS = frozenset({"start", "end", "pause"})


class ShareValidationError(Exception):
    """Datei kann nicht importiert werden. `.reason` enthält den deutschen Grund."""

    def __init__(self, reason):
        super().__init__(reason)
        self.reason = reason


def parse_share_doc(raw_bytes):
    """Parst und validiert Share-File-Inhalt. Wirft ShareValidationError bei
    jeder Schema-Verletzung — Aufrufer darf den lokalen Bestand nicht antasten,
    wenn diese Funktion wirft."""
    try:
        doc = json.loads(raw_bytes)
    except (ValueError, TypeError) as e:
        raise ShareValidationError(f"Datei ist kein gültiges JSON: {e}")

    if not isinstance(doc, dict):
        raise ShareValidationError("Datei-Inhalt ist kein JSON-Objekt.")

    if doc.get("kind") != KIND:
        raise ShareValidationError("Diese Datei ist keine geteilte Zeiterfassung.")

    schema_version = doc.get("schema_version")
    if not isinstance(schema_version, int) or isinstance(schema_version, bool):
        raise ShareValidationError("Fehlende oder ungültige schema_version.")
    if schema_version > SCHEMA_VERSION:
        raise ShareValidationError(
            "Diese Datei wurde mit einer neueren Version erstellt. "
            "Bitte App aktualisieren."
        )
    if schema_version < SCHEMA_VERSION:
        raise ShareValidationError(f"Unbekannte schema_version: {schema_version}")

    entries = doc.get("entries")
    if not isinstance(entries, dict):
        raise ShareValidationError("Feld 'entries' fehlt oder ist kein Objekt.")

    for date_str, entry in entries.items():
        if not isinstance(date_str, str) or not _DATE_RE.match(date_str):
            raise ShareValidationError(f"Ungültiger Datums-Key: {date_str!r}")
        try:
            datetime.date.fromisoformat(date_str)
        except ValueError:
            raise ShareValidationError(f"Ungültiges Datum: {date_str!r}")

        if not isinstance(entry, dict):
            raise ShareValidationError(f"Eintrag {date_str} ist kein Objekt.")

        keys = set(entry.keys())
        if keys != _ENTRY_KEYS:
            extras = sorted(keys - _ENTRY_KEYS)
            missing = sorted(_ENTRY_KEYS - keys)
            parts = []
            if extras:
                parts.append(f"unbekannte Felder: {extras}")
            if missing:
                parts.append(f"fehlende Felder: {missing}")
            raise ShareValidationError(f"Eintrag {date_str}: {'; '.join(parts)}")

        start = entry["start"]
        end = entry["end"]
        pause = entry["pause"]
        if not isinstance(start, str) or not _TIME_RE.match(start):
            raise ShareValidationError(
                f"Eintrag {date_str}: ungültige Startzeit {start!r}"
            )
        if not isinstance(end, str) or not _TIME_RE.match(end):
            raise ShareValidationError(
                f"Eintrag {date_str}: ungültige Endzeit {end!r}"
            )
        if not isinstance(pause, int) or isinstance(pause, bool) or pause < 0:
            raise ShareValidationError(
                f"Eintrag {date_str}: ungültige Pause {pause!r}"
            )

    return doc
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_share.py -v`
Expected: All 13 reject-tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/share.py tests/test_share.py
git commit -m "feat(share): parse + validate share-file wire format

Defensives Schema-Parsing für eingehende Share-Files. Jeder Verstoß
gegen das erwartete Format wirft eine ShareValidationError mit
deutscher Begründung — Aufrufer darf den lokalen Bestand nicht
antasten, wenn diese Funktion wirft.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 3: `build_share_doc` + `serialize_share_doc` (happy path, round-trip)

**Files:**
- Modify: `src/share.py`
- Test: `tests/test_share.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_share.py`:

```python
from src.share import build_share_doc, serialize_share_doc, KIND, SCHEMA_VERSION


class _FakeStorage:
    def __init__(self, entries):
        self._entries = entries

    def get_all(self):
        return dict(self._entries)


def test_build_share_doc_basic():
    storage = _FakeStorage({
        "2026-05-14": {"start": "08:00", "end": "16:00", "pause": 30},
    })
    doc = build_share_doc(storage, "alice@example.com")
    assert doc["kind"] == KIND
    assert doc["schema_version"] == SCHEMA_VERSION
    assert doc["exported_by"] == "alice@example.com"
    assert doc["entries"] == {"2026-05-14": {"start": "08:00", "end": "16:00", "pause": 30}}
    assert "exported_at" in doc and doc["exported_at"].endswith("Z")


def test_build_share_doc_empty_sender():
    storage = _FakeStorage({})
    doc = build_share_doc(storage, "")
    assert doc["exported_by"] == ""
    assert doc["entries"] == {}


def test_build_share_doc_none_sender_becomes_empty_string():
    storage = _FakeStorage({})
    doc = build_share_doc(storage, None)
    assert doc["exported_by"] == ""


def test_round_trip_build_serialize_parse():
    storage = _FakeStorage({
        "2026-05-14": {"start": "08:00", "end": "16:00", "pause": 30},
        "2026-05-15": {"start": "09:00", "end": "17:30", "pause": 45},
    })
    doc = build_share_doc(storage, "alice@example.com")
    payload = serialize_share_doc(doc)
    parsed = parse_share_doc(payload)
    assert parsed["entries"] == doc["entries"]
    assert parsed["kind"] == KIND
    assert parsed["schema_version"] == SCHEMA_VERSION


def test_serialize_utf8_umlauts():
    storage = _FakeStorage({})
    doc = build_share_doc(storage, "äöü@example.com")
    payload = serialize_share_doc(doc)
    assert b"\\u" not in payload  # ensure_ascii=False — Umlaute literal
    parsed = parse_share_doc(payload)
    assert parsed["exported_by"] == "äöü@example.com"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_share.py -k "build or round_trip or serialize_utf8" -v`
Expected: FAIL with `ImportError` für `build_share_doc`/`serialize_share_doc`.

- [ ] **Step 3: Implement build + serialize in src/share.py**

Append to `src/share.py` (after `class ShareValidationError`):

```python
def _utc_now_iso():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def build_share_doc(storage, sender_email):
    """Baut das Share-Doc aus dem lokalen Storage. Tombstones werden via
    storage.get_all() bereits ausgefiltert."""
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": KIND,
        "exported_at": _utc_now_iso(),
        "exported_by": sender_email or "",
        "entries": dict(storage.get_all()),
    }


def serialize_share_doc(doc):
    """Stabiles UTF-8-JSON, sortierte Keys (deterministisch für Tests)."""
    return json.dumps(doc, indent=2, ensure_ascii=False, sort_keys=True).encode("utf-8")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_share.py -v`
Expected: All 18 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/share.py tests/test_share.py
git commit -m "feat(share): build + serialize share-doc (round-trip)

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 4: `diff_share_against_local` (ohne Range-Filter)

**Files:**
- Modify: `src/share.py`
- Test: `tests/test_share.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_share.py`:

```python
from src.share import diff_share_against_local


def test_diff_only_additions():
    storage = _FakeStorage({})
    share = {"2026-05-14": {"start": "08:00", "end": "16:00", "pause": 30}}
    diff = diff_share_against_local(share, storage)
    assert diff["additions"] == [("2026-05-14", {"start": "08:00", "end": "16:00", "pause": 30})]
    assert diff["conflicts"] == []
    assert diff["untouched"] == []
    assert diff["out_of_range"] == 0


def test_diff_only_untouched():
    storage = _FakeStorage({"2026-05-14": {"start": "08:00", "end": "16:00", "pause": 30}})
    share = {"2026-05-14": {"start": "08:00", "end": "16:00", "pause": 30}}
    diff = diff_share_against_local(share, storage)
    assert diff["additions"] == []
    assert diff["conflicts"] == []
    assert diff["untouched"] == ["2026-05-14"]


def test_diff_only_conflicts():
    storage = _FakeStorage({"2026-05-14": {"start": "08:00", "end": "16:00", "pause": 30}})
    share = {"2026-05-14": {"start": "09:00", "end": "17:30", "pause": 30}}
    diff = diff_share_against_local(share, storage)
    assert len(diff["conflicts"]) == 1
    date, local, shared = diff["conflicts"][0]
    assert date == "2026-05-14"
    assert local["start"] == "08:00"
    assert shared["start"] == "09:00"


def test_diff_pause_difference_is_conflict():
    storage = _FakeStorage({"2026-05-14": {"start": "08:00", "end": "16:00", "pause": 30}})
    share = {"2026-05-14": {"start": "08:00", "end": "16:00", "pause": 45}}
    diff = diff_share_against_local(share, storage)
    assert len(diff["conflicts"]) == 1
    assert diff["untouched"] == []


def test_diff_mixed():
    storage = _FakeStorage({
        "2026-05-14": {"start": "08:00", "end": "16:00", "pause": 30},  # untouched
        "2026-05-15": {"start": "08:00", "end": "16:00", "pause": 30},  # conflict
    })
    share = {
        "2026-05-14": {"start": "08:00", "end": "16:00", "pause": 30},
        "2026-05-15": {"start": "09:00", "end": "17:00", "pause": 30},
        "2026-05-16": {"start": "10:00", "end": "18:00", "pause": 0},   # addition
    }
    diff = diff_share_against_local(share, storage)
    assert diff["untouched"] == ["2026-05-14"]
    assert [d for d, _, _ in diff["conflicts"]] == ["2026-05-15"]
    assert [d for d, _ in diff["additions"]] == ["2026-05-16"]


def test_diff_tombstone_treated_as_addition():
    """Tombstones im Storage tauchen in get_all() nicht auf → share entry zählt als addition."""
    class _StorageWithTombstone:
        def get_all(self):
            return {}  # tombstone gefiltert
    share = {"2026-05-14": {"start": "08:00", "end": "16:00", "pause": 0}}
    diff = diff_share_against_local(share, _StorageWithTombstone())
    assert len(diff["additions"]) == 1
    assert diff["conflicts"] == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_share.py -k diff -v`
Expected: FAIL with `ImportError`.

- [ ] **Step 3: Implement diff_share_against_local**

Append to `src/share.py`:

```python
def _entries_equal(a, b):
    return (a.get("start") == b.get("start")
            and a.get("end") == b.get("end")
            and a.get("pause", 0) == b.get("pause", 0))


def diff_share_against_local(share_entries, storage, date_from=None, date_to=None):
    """Vergleicht share_entries mit storage.get_all().

    date_from/date_to: optional datetime.date, inclusive auf beiden Seiten.
    None = unbeschränkt. Einträge außerhalb fallen in 'out_of_range'-Count
    und tauchen sonst nirgends auf.

    Returns dict mit 'additions' (list of (date, entry)), 'conflicts'
    (list of (date, local_entry, share_entry)), 'untouched' (list of date)
    und 'out_of_range' (int).
    """
    additions = []
    conflicts = []
    untouched = []
    out_of_range = 0
    local = storage.get_all()

    for date_str in sorted(share_entries.keys()):
        try:
            d = datetime.date.fromisoformat(date_str)
        except ValueError:
            # parse_share_doc hat das schon abgefangen — defensive Skip.
            continue
        if date_from is not None and d < date_from:
            out_of_range += 1
            continue
        if date_to is not None and d > date_to:
            out_of_range += 1
            continue

        share_entry = share_entries[date_str]
        local_entry = local.get(date_str)
        if local_entry is None:
            additions.append((date_str, share_entry))
        elif _entries_equal(local_entry, share_entry):
            untouched.append(date_str)
        else:
            conflicts.append((date_str, local_entry, share_entry))

    return {
        "additions": additions,
        "conflicts": conflicts,
        "untouched": untouched,
        "out_of_range": out_of_range,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_share.py -v`
Expected: All tests PASS (24 total now).

- [ ] **Step 5: Commit**

```bash
git add src/share.py tests/test_share.py
git commit -m "feat(share): diff share-entries against local storage

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 5: Range-Filter in `diff_share_against_local`

**Files:**
- Test: `tests/test_share.py`

(Implementation ist in Task 4 bereits enthalten — diese Task verifiziert per Test, dass die Range-Logik tut, was sie soll.)

- [ ] **Step 1: Write tests for range filter**

Append to `tests/test_share.py`:

```python
import datetime as _dt


def test_diff_range_filter_excludes_left():
    storage = _FakeStorage({})
    share = {
        "2026-05-10": {"start": "08:00", "end": "16:00", "pause": 0},
        "2026-05-15": {"start": "08:00", "end": "16:00", "pause": 0},
    }
    diff = diff_share_against_local(share, storage, date_from=_dt.date(2026, 5, 12))
    assert [d for d, _ in diff["additions"]] == ["2026-05-15"]
    assert diff["out_of_range"] == 1


def test_diff_range_filter_excludes_right():
    storage = _FakeStorage({})
    share = {
        "2026-05-10": {"start": "08:00", "end": "16:00", "pause": 0},
        "2026-05-15": {"start": "08:00", "end": "16:00", "pause": 0},
    }
    diff = diff_share_against_local(share, storage, date_to=_dt.date(2026, 5, 12))
    assert [d for d, _ in diff["additions"]] == ["2026-05-10"]
    assert diff["out_of_range"] == 1


def test_diff_range_filter_inclusive_bounds():
    storage = _FakeStorage({})
    share = {
        "2026-05-10": {"start": "08:00", "end": "16:00", "pause": 0},
        "2026-05-15": {"start": "08:00", "end": "16:00", "pause": 0},
    }
    diff = diff_share_against_local(
        share, storage,
        date_from=_dt.date(2026, 5, 10),
        date_to=_dt.date(2026, 5, 15),
    )
    assert len(diff["additions"]) == 2
    assert diff["out_of_range"] == 0


def test_diff_range_filter_completely_outside():
    storage = _FakeStorage({})
    share = {"2026-05-14": {"start": "08:00", "end": "16:00", "pause": 0}}
    diff = diff_share_against_local(
        share, storage,
        date_from=_dt.date(2030, 1, 1),
    )
    assert diff["additions"] == []
    assert diff["conflicts"] == []
    assert diff["untouched"] == []
    assert diff["out_of_range"] == 1


def test_diff_range_none_bounds_unconstrained():
    storage = _FakeStorage({})
    share = {"2026-05-14": {"start": "08:00", "end": "16:00", "pause": 0}}
    diff = diff_share_against_local(share, storage, date_from=None, date_to=None)
    assert len(diff["additions"]) == 1
    assert diff["out_of_range"] == 0
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `pytest tests/test_share.py -k range -v`
Expected: All 5 range-tests PASS (Logik existiert bereits aus Task 4).

- [ ] **Step 3: Commit**

```bash
git add tests/test_share.py
git commit -m "test(share): cover date_from/date_to range filter in diff

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 6: `apply_import` (atomarer Apply)

**Files:**
- Modify: `src/share.py`
- Test: `tests/test_share.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_share.py`:

```python
from unittest import mock

from src.share import apply_import


class _RecordingStorage:
    def __init__(self):
        self.save_many_calls = []

    def save_many(self, updates):
        self.save_many_calls.append(dict(updates))


def test_apply_import_empty_is_noop():
    s = _RecordingStorage()
    apply_import(s, [])
    # save_many wird mit leerem Dict aufgerufen; Storage selbst dedupliziert das
    # zu einem No-op. Hier reicht uns: keine Exception.
    assert s.save_many_calls in ([], [{}])


def test_apply_import_single_call_for_all_decisions():
    s = _RecordingStorage()
    decisions = [
        {"date": "2026-05-14", "entry": {"start": "08:00", "end": "16:00", "pause": 30}},
        {"date": "2026-05-15", "entry": {"start": "09:00", "end": "17:00", "pause": 0}},
    ]
    apply_import(s, decisions)
    assert len(s.save_many_calls) == 1
    assert s.save_many_calls[0] == {
        "2026-05-14": {"start": "08:00", "end": "16:00", "pause": 30},
        "2026-05-15": {"start": "09:00", "end": "17:00", "pause": 0},
    }


def test_apply_import_integration_with_real_storage(tmp_path):
    from src.storage import Storage
    s = Storage(str(tmp_path / "z.json"), device_id="dev1")
    s.save("2026-05-14", "08:00", "16:00", 30)
    apply_import(s, [
        {"date": "2026-05-15", "entry": {"start": "09:00", "end": "17:00", "pause": 0}},
        {"date": "2026-05-14", "entry": {"start": "10:00", "end": "18:00", "pause": 45}},
    ])
    entries = s.get_all()
    assert entries["2026-05-14"] == {"start": "10:00", "end": "18:00", "pause": 45}
    assert entries["2026-05-15"] == {"start": "09:00", "end": "17:00", "pause": 0}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_share.py -k apply_import -v`
Expected: FAIL with `ImportError`.

- [ ] **Step 3: Implement apply_import in src/share.py**

Append to `src/share.py`:

```python
def apply_import(storage, decisions):
    """Wendet Import-Decisions atomar an (eine save_many-Aufruf).

    decisions: list of {"date": "YYYY-MM-DD", "entry": {start, end, pause}}.
    """
    updates = {d["date"]: d["entry"] for d in decisions}
    storage.save_many(updates)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_share.py -v`
Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/share.py tests/test_share.py
git commit -m "feat(share): apply_import via Storage.save_many (atomic)

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 7: Settings — `share_recipient` Default

**Files:**
- Modify: `src/settings.py`
- Test: `tests/test_settings.py`

- [ ] **Step 1: Write failing test**

Read `tests/test_settings.py` to find a similar default test and follow the pattern. Then add:

```python
def test_share_recipient_default_empty(tmp_path):
    from src.settings import Settings
    s = Settings(str(tmp_path / "s.json"))
    assert s.get("share_recipient") == ""


def test_share_recipient_persists(tmp_path):
    from src.settings import Settings
    path = str(tmp_path / "s.json")
    s1 = Settings(path)
    s1.set("share_recipient", "bob@example.com")
    s2 = Settings(path)
    assert s2.get("share_recipient") == "bob@example.com"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_settings.py -k share_recipient -v`
Expected: First test FAILS (returns `None` because key fehlt im DEFAULTS-Dict).

- [ ] **Step 3: Add default to src/settings.py**

In `src/settings.py`, inside the `DEFAULTS` dict, after the `"recipient": "",` line (line 15):

```python
    "share_recipient": "",
```

Do NOT add it to `SYNCED_SETTING_KEYS` — explizit per-device, kein Sync.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_settings.py -v`
Expected: All settings tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/settings.py tests/test_settings.py
git commit -m "feat(settings): add share_recipient default (per-device)

Empfänger-Adresse für das Teilen, getrennt vom PDF-Reporting-Empfänger.
Bewusst nicht in SYNCED_SETTING_KEYS — bleibt pro Gerät.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 8: Mail — `send_email` generalisieren für JSON-Anhang

**Files:**
- Modify: `src/mail.py`
- Modify: `src/dialogs/send_dialog.py`
- Test: `tests/test_mail.py`

- [ ] **Step 1: Look at existing send_email tests**

Read `tests/test_mail.py` to understand the test pattern. The existing `send_email` signature uses `pdf_bytes`/`pdf_filename`. We generalize to `attachment_bytes`/`attachment_filename`/`attachment_subtype`.

- [ ] **Step 2: Write failing tests**

Append to `tests/test_mail.py`:

```python
def test_send_email_json_attachment_uses_subtype():
    """JSON-Anhang setzt MIME-Subtype 'json' statt 'pdf'."""
    from unittest.mock import MagicMock
    from src.mail import send_email

    service = MagicMock()
    service.users().messages().send().execute.return_value = {"id": "mid-1"}

    msg_id = send_email(
        service, "to@example.com", "Subj", "<p>body</p>",
        attachment_bytes=b'{"x":1}',
        attachment_filename="share.json",
        attachment_subtype="json",
    )
    assert msg_id == "mid-1"
    # Wir können den Raw-Body über send.call_args inspizieren:
    call_kwargs = service.users().messages().send.call_args
    body = call_kwargs.kwargs.get("body") or call_kwargs.args[-1]
    import base64
    raw = base64.urlsafe_b64decode(body["raw"]).decode()
    assert "application/json" in raw
    assert "share.json" in raw
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/test_mail.py::test_send_email_json_attachment_uses_subtype -v`
Expected: FAIL because `send_email` doesn't accept `attachment_bytes` yet.

- [ ] **Step 4: Update send_email signature in src/mail.py**

Replace the `send_email` function (lines 236-262) with:

```python
def send_email(service, to, subject, html_body,
               attachment_bytes=None, attachment_filename=None,
               attachment_subtype="pdf",
               # legacy aliases — bleibe rückwärtskompatibel falls ein Caller
               # noch nicht migriert ist:
               pdf_bytes=None, pdf_filename=None):
    """Send an HTML email via Gmail API, optionally with a binary attachment.

    attachment_subtype steuert den MIMEApplication-_subtype (z.B. 'pdf', 'json').
    pdf_bytes/pdf_filename sind Legacy-Aliase und werden auf
    attachment_bytes/attachment_filename gemappt.
    """
    if pdf_bytes is not None and attachment_bytes is None:
        attachment_bytes = pdf_bytes
        attachment_filename = attachment_filename or pdf_filename
        attachment_subtype = "pdf"

    if attachment_bytes:
        message = MIMEMultipart()
        message["to"] = to
        message["subject"] = Header(subject, "utf-8")  # pyright: ignore[reportArgumentType]
        message.attach(MIMEText(html_body, "html", _charset="utf-8"))

        attachment = MIMEApplication(attachment_bytes, _subtype=attachment_subtype)
        attachment.add_header(
            "Content-Disposition", "attachment",
            filename=attachment_filename or f"attachment.{attachment_subtype}",
        )
        message.attach(attachment)
    else:
        message = MIMEText(html_body, "html", _charset="utf-8")
        message["to"] = to
        message["subject"] = Header(subject, "utf-8")  # pyright: ignore[reportArgumentType]

    raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
    body = {"raw": raw}

    sent = service.users().messages().send(userId="me", body=body).execute()
    return sent["id"]
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_mail.py -v`
Expected: All PASS (alte PDF-Tests via Legacy-Aliase, neuer JSON-Test direkt).

- [ ] **Step 6: Migrate send_dialog.py to new signature**

In `src/dialogs/send_dialog.py`, find the `send_email` call (around line 185):

Replace:
```python
            send_email(service, recipient, subject, html,
                       pdf_bytes=pdf_bytes, pdf_filename=pdf_filename)
```

With:
```python
            send_email(service, recipient, subject, html,
                       attachment_bytes=pdf_bytes,
                       attachment_filename=pdf_filename,
                       attachment_subtype="pdf")
```

- [ ] **Step 7: Run all tests**

Run: `pytest -v`
Expected: All PASS — legacy aliases sind weiter da, aber send_dialog nutzt den neuen Pfad.

- [ ] **Step 8: Commit**

```bash
git add src/mail.py src/dialogs/send_dialog.py tests/test_mail.py
git commit -m "feat(mail): generalize send_email for arbitrary attachments

Neue Parameter attachment_bytes/_filename/_subtype. pdf_bytes/pdf_filename
bleiben als Legacy-Aliase, send_dialog migriert auf den neuen Namen.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 9: Settings-Dialog — Feld „Teilen mit:"

**Files:**
- Modify: `src/dialogs/settings_dialog.py`

(Reine UI-Änderung — keine Tests, folgt bestehender Konvention.)

- [ ] **Step 1: Add the "Teilen mit:" entry below "Empfänger:"**

In `src/dialogs/settings_dialog.py`, find the block (lines 201-207):

```python
    label("Empfänger:", row=6)
    recipient_var = tk.StringVar(value=settings.get("recipient"))
    dark_entry(dialog, recipient_var, width=25).grid(row=6, column=1, padx=10, pady=8)

    label("Name:", row=7)
    name_var = tk.StringVar(value=settings.get("name"))
    dark_entry(dialog, name_var, width=25).grid(row=7, column=1, padx=10, pady=8)
```

We need to insert a „Teilen mit:" row between „Empfänger:" and „Name:". Renumbering would touch ~20 grid-calls below, so instead we use **a tighter same-row layout**: split the Empfänger column into two stacked entries with a sub-label.

Actually, cleaner: explicitly renumber. Replace ALL `row=N` für N>=7 mit N+1. To keep the edit auditable, we go top-to-bottom.

Replace the block (lines 201-289 — alles von „Empfänger:" bis vor dem „Synchronisation"-Header):

```python
    label("Empfänger:", row=6)
    recipient_var = tk.StringVar(value=settings.get("recipient"))
    dark_entry(dialog, recipient_var, width=25).grid(row=6, column=1, padx=10, pady=8)

    label("Teilen mit:", row=7)
    share_recipient_var = tk.StringVar(value=settings.get("share_recipient"))
    dark_entry(dialog, share_recipient_var, width=25).grid(row=7, column=1, padx=10, pady=8)

    label("Name:", row=8)
    name_var = tk.StringVar(value=settings.get("name"))
    dark_entry(dialog, name_var, width=25).grid(row=8, column=1, padx=10, pady=8)

    label("Stundenlohn (€):", row=9)
    rate_var = tk.StringVar(value=str(settings.get("hourly_rate") or ""))
    dark_entry(dialog, rate_var, width=10).grid(row=9, column=1, padx=10, pady=8, sticky="w")

    tk.Label(
        dialog, text="(optional – nur für dich sichtbar)", font=FONT_SMALL,
        bg=BG, fg=TEXT_MUTED,
    ).grid(row=9, column=1, padx=(120, 10), pady=8, sticky="w")

    label("Bundesland:", row=10)
    state_labels = [lbl for _, lbl in STATES]
    current_code = settings.get("state")
    current_label = next(
        (lbl for code, lbl in STATES if code == current_code),
        STATES[0][1],
    )
    state_var = tk.StringVar(value=current_label)
    dark_combo(dialog, state_var, state_labels, width=22).grid(row=10, column=1, padx=10, pady=8)

    tk.Label(
        dialog, text="— Mail-Vorlage —", font=FONT_BOLD, bg=BG, fg=TEXT_MUTED,
    ).grid(row=11, column=0, columnspan=2, padx=10, pady=(16, 4))

    label("Betreff:", row=12, pady=4)
    subject_var = tk.StringVar(value=settings.get("mail_subject"))
    dark_entry(dialog, subject_var, width=35).grid(row=12, column=1, padx=10, pady=4)

    label("Anrede:", row=13, pady=4)
    greeting_var = tk.StringVar(value=settings.get("mail_greeting"))
    dark_entry(dialog, greeting_var, width=35).grid(row=13, column=1, padx=10, pady=4)

    label("Inhalt:", row=14, pady=4, sticky="nw")
    content_text = dark_text(dialog, 35, 3)
    content_text.grid(row=14, column=1, padx=10, pady=4)
    content_text.insert("1.0", settings.get("mail_content"))

    label("Gruß:", row=15, pady=4, sticky="nw")
    closing_text = dark_text(dialog, 35, 2)
    closing_text.grid(row=15, column=1, padx=10, pady=4)
    closing_text.insert("1.0", settings.get("mail_closing"))

    tk.Label(
        dialog, text="Platzhalter: {zeitraum}, {gesamt}", font=("Segoe UI", 8),
        bg=BG, fg=TEXT_MUTED,
    ).grid(row=16, column=0, columnspan=2, padx=10, pady=(0, 4))

    show_weekend_var = tk.BooleanVar(value=settings.get("show_weekend"))
    tk.Checkbutton(
        dialog, text="Wochenende (Sa/So) im Kalender anzeigen",
        variable=show_weekend_var, font=FONT,
        bg=BG, fg=TEXT, selectcolor=CELL_BG,
        activebackground=BG, activeforeground=TEXT,
        cursor="hand2",
    ).grid(row=17, column=0, columnspan=2, padx=10, pady=(8, 0), sticky="w")

    autostart_var = tk.BooleanVar(value=settings.get("autostart"))
    tk.Checkbutton(
        dialog, text="Autostart (minimiert bei Anmeldung)",
        variable=autostart_var, font=FONT,
        bg=BG, fg=TEXT, selectcolor=CELL_BG,
        activebackground=BG, activeforeground=TEXT,
        cursor="hand2",
    ).grid(row=18, column=0, columnspan=2, padx=10, pady=(0, 0), sticky="w")

    always_on_top_var = tk.BooleanVar(value=settings.get("always_on_top"))
    tk.Checkbutton(
        dialog, text="Immer im Vordergrund",
        variable=always_on_top_var, font=FONT,
        bg=BG, fg=TEXT, selectcolor=CELL_BG,
        activebackground=BG, activeforeground=TEXT,
        cursor="hand2",
    ).grid(row=19, column=0, columnspan=2, padx=10, pady=(0, 0), sticky="w")

    minimize_to_tray_var = tk.BooleanVar(value=settings.get("minimize_to_tray"))
    tk.Checkbutton(
        dialog, text="Beim Schließen in den Infobereich minimieren",
        variable=minimize_to_tray_var, font=FONT,
        bg=BG, fg=TEXT, selectcolor=CELL_BG,
        activebackground=BG, activeforeground=TEXT,
        cursor="hand2",
    ).grid(row=20, column=0, columnspan=2, padx=10, pady=(0, 8), sticky="w")
```

- [ ] **Step 2: Renumber the Sync-Sektion**

Replace the block from `# --- Synchronisation (Multi-Device-Sync, Phase 4.6) ---` down to the buttons (lines 291-457). Increment every `row=N` for N>=20 by 1. The buttons-grid row stays the visually-last entry (now row=26).

Concretely: replace `row=20` → `row=21`, `row=21` → `row=22`, …, `row=25` → `row=26`. Use a single search-and-replace per row number, top-down, to avoid double-increments. Easiest: do them in decreasing order (25→26, 24→25, …, 20→21).

After the renumber the bottom of the file should end with:

```python
    btn_frame = tk.Frame(dialog, bg=BG)
    btn_frame.grid(row=26, column=0, columnspan=2, pady=12)
```

- [ ] **Step 3: Update save_settings to persist share_recipient**

In the same file, find the `updates = {...}` dict in `save_settings` and add the new key alongside `"recipient": recipient_var.get(),`:

```python
            "share_recipient": share_recipient_var.get(),
```

`share_recipient` ist nicht in `SYNCED_SETTING_KEYS`, daher landet es automatisch in `plain_updates` und wird via `set_many` geschrieben.

- [ ] **Step 4: Manual smoke test**

Run: `python -m src.main`

Open Settings, vergewissere Dich:
- Die neue Zeile „Teilen mit:" steht direkt unter „Empfänger:".
- Werte werden gespeichert und beim erneuten Öffnen des Dialogs geladen.
- Layout ist nicht zerschossen — Sync-Sektion, Pause-Sektion, Buttons sind alle an Ort.

- [ ] **Step 5: Commit**

```bash
git add src/dialogs/settings_dialog.py
git commit -m "feat(settings-ui): add „Teilen mit:" recipient field

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 10: Share-Dialog — Export per Mail

**Files:**
- Create: `src/dialogs/share_dialog.py`

- [ ] **Step 1: Create share_dialog.py**

Create `src/dialogs/share_dialog.py`:

```python
"""Modal-Dialog „Arbeitszeiten teilen": baut Share-Doc, sendet per Gmail."""

import logging
import os
import tkinter as tk
import traceback
from tkinter import messagebox

from src.dialogs.send_dialog import show_missing_credentials_dialog
from src.mail import get_gmail_service, send_email
from src.share import build_share_doc, serialize_share_doc
from src.theme import (
    BG, FONT, TEXT,
    apply_dark_titlebar, center_dialog_on_parent,
    primary_button, secondary_button, themed_showinfo,
)


def open_share_dialog(parent, storage, settings, base_path):
    share_recipient = settings.get("share_recipient")
    if not share_recipient:
        messagebox.showwarning(
            "Kein Empfänger zum Teilen",
            "Bitte zuerst eine Empfänger-Adresse unter „Teilen mit:" in den "
            "Einstellungen angeben.",
            parent=parent,
        )
        return

    credentials_path = os.path.join(base_path, "credentials.json")
    token_path = os.path.join(base_path, "token.json")

    if not os.path.exists(credentials_path):
        show_missing_credentials_dialog(parent, base_path)
        return

    entries = storage.get_all()
    if not entries:
        messagebox.showinfo(
            "Keine Einträge",
            "Es sind keine Einträge zum Teilen vorhanden.",
            parent=parent,
        )
        return

    dialog = tk.Toplevel(parent)
    dialog.title("Arbeitszeiten teilen")
    dialog.resizable(False, False)
    dialog.grab_set()
    dialog.configure(bg=BG)
    apply_dark_titlebar(dialog)

    tk.Label(
        dialog,
        text=(
            f"Alle {len(entries)} Einträge werden als JSON-Anhang an\n"
            f"{share_recipient}\n"
            "gesendet."
        ),
        font=FONT, bg=BG, fg=TEXT,
        wraplength=380, justify="left",
    ).grid(row=0, column=0, columnspan=2, padx=20, pady=(20, 12))

    def do_send():
        sender_email = settings.get("sender_email") or ""
        display_name = settings.get("name") or sender_email or "anonym"
        try:
            doc = build_share_doc(storage, sender_email)
            payload = serialize_share_doc(doc)
            service = get_gmail_service(
                credentials_path, token_path,
                sync_enabled=settings.get("sync_enabled"),
            )
            subject = f"Arbeitszeiten geteilt von {display_name}"
            html = (
                "<html><head><meta charset=\"utf-8\"></head><body>"
                f"<p>Hallo,</p>"
                f"<p>im Anhang findest Du meine Arbeitszeiten "
                f"({len(entries)} Tage) als JSON-Datei.</p>"
                "<p>Du kannst sie in der Zeiterfassung-App über "
                "<em>Einstellungen → Arbeitszeiten importieren…</em> einlesen. "
                "Vor dem Import kannst Du einen Zeitraum auswählen und "
                "festlegen, was bei Konflikten passieren soll.</p>"
                f"<p>Viele Grüße<br/>{display_name}</p>"
                "</body></html>"
            )
            filename = f"zeiterfassung-share-{doc['exported_at'][:10].replace('-', '')}.json"
            send_email(
                service, share_recipient, subject, html,
                attachment_bytes=payload,
                attachment_filename=filename,
                attachment_subtype="json",
            )
            dialog.destroy()
            themed_showinfo(
                parent,
                "Geteilt",
                f"Arbeitszeiten wurden an {share_recipient} gesendet.",
            )
        except FileNotFoundError as e:
            messagebox.showerror("Fehler", str(e), parent=dialog)
        except Exception as e:
            logging.getLogger(__name__).exception("Teilen fehlgeschlagen")
            messagebox.showerror(
                "Teilen fehlgeschlagen",
                f"{type(e).__name__}: {e}\n\n{traceback.format_exc()}",
                parent=dialog,
            )

    btn_frame = tk.Frame(dialog, bg=BG)
    btn_frame.grid(row=1, column=0, columnspan=2, pady=(0, 16))

    primary_button(btn_frame, "Senden", do_send).pack(side=tk.LEFT, padx=5)
    secondary_button(btn_frame, "Abbrechen", dialog.destroy).pack(side=tk.LEFT, padx=5)

    center_dialog_on_parent(dialog, parent)
```

- [ ] **Step 2: Run pytest to catch syntax errors**

Run: `pytest -v`
Expected: All tests still PASS — neue Datei wird nirgendwo importiert, also keine Wirkung. Aber Syntax-Errors würden Pytest brechen, wenn ein Test sie via Glob mitlädt.

- [ ] **Step 3: Commit**

```bash
git add src/dialogs/share_dialog.py
git commit -m "feat(share-ui): add share_dialog for exporting entries via Gmail

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 11: Import-Dialog — Datei-Pick + Summary + Range-Filter

**Files:**
- Create: `src/dialogs/import_dialog.py`

- [ ] **Step 1: Create import_dialog.py**

Create `src/dialogs/import_dialog.py`:

```python
"""Modal-Dialog „Arbeitszeiten importieren": Datei-Pick, Summary mit
Zeitraum-Filter + Konflikt-Modi, optional Pro-Tag-Modal, atomarer Apply."""

import calendar
import datetime
import logging
import tkinter as tk
import traceback
from tkinter import filedialog, messagebox

from src.share import (
    ShareValidationError,
    apply_import,
    diff_share_against_local,
    parse_share_doc,
)
from src.theme import (
    BG, CELL_BG, FONT, FONT_SMALL, TEXT, TEXT_MUTED,
    apply_combobox_style, apply_dark_titlebar, center_dialog_on_parent,
    dark_combo, primary_button, secondary_button, themed_showinfo,
)


def open_import_dialog(parent, storage, settings, on_change):
    """Startet den Import-Flow. on_change wird bei erfolgreichem Apply aufgerufen
    (damit der Kalender re-rendert)."""
    path = filedialog.askopenfilename(
        parent=parent,
        title="Share-Datei auswählen",
        filetypes=[("Zeiterfassung Share", "*.json"), ("Alle Dateien", "*.*")],
    )
    if not path:
        return

    try:
        with open(path, "rb") as f:
            raw = f.read()
    except OSError as e:
        messagebox.showerror(
            "Datei nicht lesbar",
            f"{type(e).__name__}: {e}",
            parent=parent,
        )
        return

    try:
        doc = parse_share_doc(raw)
    except ShareValidationError as e:
        messagebox.showerror(
            "Datei ungültig",
            f"Die Datei kann nicht importiert werden:\n\n{e.reason}",
            parent=parent,
        )
        return

    share_entries = doc["entries"]
    if not share_entries:
        messagebox.showinfo(
            "Leere Datei",
            "Die Datei enthält keine Einträge.",
            parent=parent,
        )
        return

    dates = sorted(datetime.date.fromisoformat(d) for d in share_entries.keys())
    file_min, file_max = dates[0], dates[-1]

    _ImportSummaryDialog(parent, storage, doc, file_min, file_max, on_change).show()


class _ImportSummaryDialog:
    def __init__(self, parent, storage, doc, file_min, file_max, on_change):
        self.parent = parent
        self.storage = storage
        self.doc = doc
        self.share_entries = doc["entries"]
        self.file_min = file_min
        self.file_max = file_max
        self.on_change = on_change

        self.top = tk.Toplevel(parent)
        self.top.title("Arbeitszeiten importieren")
        self.top.resizable(False, False)
        self.top.grab_set()
        self.top.configure(bg=BG)
        apply_dark_titlebar(self.top)
        apply_combobox_style(self.top)

        self._build()
        center_dialog_on_parent(self.top, parent)

    def show(self):
        self.top.wait_window()

    def _build(self):
        row = 0
        tk.Label(
            self.top,
            text=f"Datei: zeiterfassung-share (geteilt von "
                 f"{self.doc.get('exported_by') or 'unbekannt'})",
            font=FONT, bg=BG, fg=TEXT, justify="left",
        ).grid(row=row, column=0, columnspan=6, padx=10, pady=(10, 4), sticky="w")
        row += 1

        tk.Label(
            self.top,
            text=f"Exportiert: {self.doc.get('exported_at', '')}",
            font=FONT_SMALL, bg=BG, fg=TEXT_MUTED, justify="left",
        ).grid(row=row, column=0, columnspan=6, padx=10, pady=(0, 10), sticky="w")
        row += 1

        tk.Label(
            self.top, text="Zeitraum filtern:", font=FONT, bg=BG, fg=TEXT,
        ).grid(row=row, column=0, columnspan=6, padx=10, pady=(4, 0), sticky="w")
        row += 1

        self.from_day, self.from_month, self.from_year = self._build_date_row(
            row, "Von:", self.file_min)
        row += 1
        self.to_day, self.to_month, self.to_year = self._build_date_row(
            row, "Bis:", self.file_max)
        row += 1

        tk.Label(
            self.top,
            text=f"Voller Bereich der Datei: "
                 f"{self.file_min.isoformat()} bis {self.file_max.isoformat()}",
            font=FONT_SMALL, bg=BG, fg=TEXT_MUTED,
        ).grid(row=row, column=0, columnspan=6, padx=10, pady=(0, 8), sticky="w")
        row += 1

        self.counts_label = tk.Label(
            self.top, text="", font=FONT, bg=BG, fg=TEXT, justify="left",
        )
        self.counts_label.grid(row=row, column=0, columnspan=6, padx=10, pady=(4, 4), sticky="w")
        row += 1

        tk.Label(
            self.top, text="Konflikt-Behandlung:", font=FONT, bg=BG, fg=TEXT,
        ).grid(row=row, column=0, columnspan=6, padx=10, pady=(8, 0), sticky="w")
        row += 1

        self.mode_var = tk.StringVar(value="import")
        for mode_value, mode_label in [
            ("import", "Alles vom Import übernehmen"),
            ("local", "Alles lokal behalten"),
            ("per_day", "Pro Tag entscheiden"),
        ]:
            tk.Radiobutton(
                self.top, text=mode_label, variable=self.mode_var, value=mode_value,
                font=FONT, bg=BG, fg=TEXT, selectcolor=CELL_BG,
                activebackground=BG, activeforeground=TEXT,
            ).grid(row=row, column=0, columnspan=6, padx=20, pady=0, sticky="w")
            row += 1

        btn_frame = tk.Frame(self.top, bg=BG)
        btn_frame.grid(row=row, column=0, columnspan=6, pady=12)
        primary_button(btn_frame, "Weiter", self._on_next).pack(side=tk.LEFT, padx=5)
        secondary_button(btn_frame, "Abbrechen", self.top.destroy).pack(side=tk.LEFT, padx=5)

        self._recompute_counts()

    def _build_date_row(self, row, label_text, default_date):
        tk.Label(self.top, text=label_text, font=FONT, bg=BG, fg=TEXT).grid(
            row=row, column=0, padx=(10, 5), pady=4, sticky="w")

        day_var = tk.StringVar(value=str(default_date.day))
        max_day = calendar.monthrange(default_date.year, default_date.month)[1]
        day_cb = dark_combo(self.top, day_var,
                             [str(d) for d in range(1, max_day + 1)], width=3)
        day_cb.grid(row=row, column=1, padx=2, pady=4)

        tk.Label(self.top, text=".", font=FONT, bg=BG, fg=TEXT).grid(row=row, column=2)

        month_var = tk.StringVar(value=str(default_date.month))
        dark_combo(self.top, month_var,
                    [str(m) for m in range(1, 13)], width=3).grid(
            row=row, column=3, padx=2, pady=4)

        tk.Label(self.top, text=".", font=FONT, bg=BG, fg=TEXT).grid(row=row, column=4)

        year_var = tk.StringVar(value=str(default_date.year))
        years = [str(y) for y in range(2020, datetime.date.today().year + 2)]
        dark_combo(self.top, year_var, years, width=5).grid(
            row=row, column=5, padx=(2, 10), pady=4)

        def _on_change(*_):
            try:
                m = int(month_var.get())
                y = int(year_var.get())
                max_day = calendar.monthrange(y, m)[1]
            except (ValueError, KeyError):
                max_day = 31
            day_cb["values"] = [str(d) for d in range(1, max_day + 1)]
            try:
                if int(day_var.get()) > max_day:
                    day_var.set(str(max_day))
            except ValueError:
                pass
            self._recompute_counts()

        day_var.trace_add("write", _on_change)
        month_var.trace_add("write", _on_change)
        year_var.trace_add("write", _on_change)

        return day_var, month_var, year_var

    def _get_range(self):
        try:
            d_from = datetime.date(
                int(self.from_year.get()), int(self.from_month.get()),
                int(self.from_day.get()))
            d_to = datetime.date(
                int(self.to_year.get()), int(self.to_month.get()),
                int(self.to_day.get()))
        except ValueError:
            return None, None
        if d_from > d_to:
            return None, None
        return d_from, d_to

    def _compute_diff(self):
        d_from, d_to = self._get_range()
        if d_from is None:
            return None
        return diff_share_against_local(
            self.share_entries, self.storage,
            date_from=d_from, date_to=d_to,
        )

    def _recompute_counts(self):
        diff = self._compute_diff()
        if diff is None:
            self.counts_label.config(
                text="(Von-Datum muss vor Bis-Datum liegen)",
                fg=TEXT_MUTED,
            )
            return
        text = (
            f"• {len(diff['additions'])} neue Tage werden importiert\n"
            f"• {len(diff['conflicts'])} Tage haben Konflikte\n"
            f"• {len(diff['untouched'])} Tage sind identisch (übersprungen)\n"
            f"• {diff['out_of_range']} Tage außerhalb des Zeitraums (ignoriert)"
        )
        self.counts_label.config(text=text, fg=TEXT)

    def _on_next(self):
        diff = self._compute_diff()
        if diff is None:
            messagebox.showerror(
                "Ungültiger Zeitraum",
                "Das Von-Datum muss vor dem Bis-Datum liegen.",
                parent=self.top,
            )
            return
        if not diff["additions"] and not diff["conflicts"]:
            messagebox.showinfo(
                "Nichts zu importieren",
                "Im gewählten Zeitraum sind alle Einträge bereits identisch.",
                parent=self.top,
            )
            return

        mode = self.mode_var.get()
        if mode == "import":
            decisions = self._decisions_from(diff, take_import_for_conflicts=True)
        elif mode == "local":
            decisions = self._decisions_from(diff, take_import_for_conflicts=False)
        else:  # per_day
            if not diff["conflicts"]:
                decisions = self._decisions_from(diff, take_import_for_conflicts=True)
            else:
                decisions = _PerDayDialog(self.top, diff).show()
                if decisions is None:
                    return  # User abgebrochen → atomar nichts tun
        self._apply(decisions)

    @staticmethod
    def _decisions_from(diff, *, take_import_for_conflicts):
        decisions = [{"date": d, "entry": e} for d, e in diff["additions"]]
        if take_import_for_conflicts:
            decisions += [
                {"date": d, "entry": s} for d, _local, s in diff["conflicts"]
            ]
        return decisions

    def _apply(self, decisions):
        try:
            apply_import(self.storage, decisions)
        except Exception as e:
            logging.getLogger(__name__).exception("Import fehlgeschlagen")
            messagebox.showerror(
                "Import fehlgeschlagen",
                f"{type(e).__name__}: {e}\n\n{traceback.format_exc()}",
                parent=self.top,
            )
            return
        self.on_change()
        self.top.destroy()
        # Wir können den 'übersprungen'-Count nicht trivial neu berechnen,
        # weil der lokale Bestand inzwischen mutiert ist. Stattdessen geben
        # wir die Decisions-Zahl aus.
        themed_showinfo(
            self.parent,
            "Importiert",
            f"{len(decisions)} Einträge wurden importiert.",
        )


class _PerDayDialog:
    """Modal mit Pro-Tag-Wahl (lokal vs. import). Liefert decisions oder None
    bei Abbruch."""

    def __init__(self, parent, diff):
        self.diff = diff
        self._result = None

        self.top = tk.Toplevel(parent)
        self.top.title("Pro Tag entscheiden")
        self.top.transient(parent)
        self.top.grab_set()
        self.top.configure(bg=BG)
        apply_dark_titlebar(self.top)

        self._build()
        center_dialog_on_parent(self.top, parent)

    def show(self):
        self.top.wait_window()
        return self._result

    def _build(self):
        tk.Label(
            self.top, text="Wähle pro Tag, was übernommen werden soll:",
            font=FONT, bg=BG, fg=TEXT,
        ).pack(padx=10, pady=(10, 4), anchor="w")

        # Scrollbarer Bereich für die Liste
        canvas = tk.Canvas(self.top, bg=BG, highlightthickness=0, height=320)
        scrollbar = tk.Scrollbar(self.top, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True, padx=(10, 0))
        scrollbar.pack(side="right", fill="y")

        list_frame = tk.Frame(canvas, bg=BG)
        canvas.create_window((0, 0), window=list_frame, anchor="nw")

        self.choices = {}  # date -> StringVar("L" or "I")
        for i, (date, local, shared) in enumerate(self.diff["conflicts"]):
            var = tk.StringVar(value="L")
            self.choices[date] = var

            tk.Label(
                list_frame, text=date, font=FONT, bg=BG, fg=TEXT, width=12, anchor="w",
            ).grid(row=i, column=0, padx=4, pady=2, sticky="w")

            tk.Label(
                list_frame,
                text=f"Lokal: {local['start']}—{local['end']} (P{local.get('pause', 0)})",
                font=FONT_SMALL, bg=BG, fg=TEXT_MUTED, anchor="w",
            ).grid(row=i, column=1, padx=4, pady=2, sticky="w")

            tk.Label(
                list_frame,
                text=f"Import: {shared['start']}—{shared['end']} (P{shared.get('pause', 0)})",
                font=FONT_SMALL, bg=BG, fg=TEXT_MUTED, anchor="w",
            ).grid(row=i, column=2, padx=4, pady=2, sticky="w")

            tk.Radiobutton(
                list_frame, text="lokal", variable=var, value="L",
                font=FONT_SMALL, bg=BG, fg=TEXT, selectcolor=CELL_BG,
                activebackground=BG, activeforeground=TEXT,
            ).grid(row=i, column=3, padx=2, pady=0)
            tk.Radiobutton(
                list_frame, text="import", variable=var, value="I",
                font=FONT_SMALL, bg=BG, fg=TEXT, selectcolor=CELL_BG,
                activebackground=BG, activeforeground=TEXT,
            ).grid(row=i, column=4, padx=2, pady=0)

        list_frame.update_idletasks()
        canvas.configure(scrollregion=canvas.bbox("all"))

        btn_frame = tk.Frame(self.top, bg=BG)
        btn_frame.pack(pady=10)

        secondary_button(
            btn_frame, "Alle auf Import",
            lambda: [v.set("I") for v in self.choices.values()],
        ).pack(side=tk.LEFT, padx=4)
        secondary_button(
            btn_frame, "Alle auf Lokal",
            lambda: [v.set("L") for v in self.choices.values()],
        ).pack(side=tk.LEFT, padx=4)
        primary_button(btn_frame, "Anwenden", self._on_apply).pack(side=tk.LEFT, padx=4)
        secondary_button(btn_frame, "Abbrechen", self.top.destroy).pack(side=tk.LEFT, padx=4)

    def _on_apply(self):
        # Decisions = additions + jene conflicts mit Wahl "I"
        decisions = [{"date": d, "entry": e} for d, e in self.diff["additions"]]
        for date, _local, shared in self.diff["conflicts"]:
            if self.choices[date].get() == "I":
                decisions.append({"date": date, "entry": shared})
        self._result = decisions
        self.top.destroy()
```

- [ ] **Step 2: Run pytest to catch syntax errors**

Run: `pytest -v`
Expected: All PASS — neue Datei wird noch nirgendwo importiert.

- [ ] **Step 3: Commit**

```bash
git add src/dialogs/import_dialog.py
git commit -m "feat(import-ui): import_dialog with range filter + conflict modes

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 12: UI-Verdrahtung — Footer-Button „Teilen…" + Settings-Eintrag „Importieren…"

**Files:**
- Modify: `src/ui.py`
- Modify: `src/dialogs/settings_dialog.py`

- [ ] **Step 1: Add Footer-Button in src/ui.py**

In `src/ui.py`, find the footer block (lines 335-337):

```python
        secondary_button(
            footer_frame, "Monat senden", self._send, padx=12,
        ).pack(side=tk.RIGHT)
```

Insert directly above a second `secondary_button` for sharing:

```python
        secondary_button(
            footer_frame, "Teilen…", self._share, padx=12,
        ).pack(side=tk.RIGHT, padx=(0, 4))
        secondary_button(
            footer_frame, "Monat senden", self._send, padx=12,
        ).pack(side=tk.RIGHT)
```

Then add the `_share` method next to `_send` (around line 946):

```python
    def _send(self):
        open_send_dialog(self.root, self.storage, self.settings, self.base_path)

    def _share(self):
        from src.dialogs.share_dialog import open_share_dialog
        open_share_dialog(self.root, self.storage, self.settings, self.base_path)
```

- [ ] **Step 2: Add Import-Button in Settings-Dialog**

In `src/dialogs/settings_dialog.py`, after the Conflict-Button section (around the bottom, before `def save_settings():`), insert an Import-Button. The natural position is right after the conflict-button-block (look for `secondary_button(dialog, f"Konflikte ansehen…")` — we add a row below it).

Add this block after the existing `if unresolved > 0:` block (which currently uses `row=24` or whatever the renumbered value is — after Task 9 it's `row=25`):

```python
    def _open_import_dialog():
        from src.dialogs.import_dialog import open_import_dialog

        def _after_import():
            on_change()
            dialog.destroy()  # Re-Open mit aktuellen Daten; einfacher als partial refresh

        open_import_dialog(dialog, storage, settings, _after_import)

    if storage is not None:
        secondary_button(
            dialog,
            "Arbeitszeiten importieren…",
            _open_import_dialog,
            padx=12, pady=2,
        ).grid(row=25, column=0, columnspan=2, padx=10, pady=(4, 8), sticky="w")
```

(Falls die Conflicts-Row schon `row=25` belegt, dieses Import-Row auf `row=26` und Buttons auf `row=27` schieben. Counterpart-Fix unten.)

If you needed to bump the Import-Row, also bump:
```python
    btn_frame = tk.Frame(dialog, bg=BG)
    btn_frame.grid(row=26, column=0, columnspan=2, pady=12)
```
to `row=27`.

- [ ] **Step 3: Manual smoke test (export path)**

Run: `python -m src.main`

Test:
1. Open Settings, set „Teilen mit:" to a known address (Gmail-Empfänger Deiner Wahl). Save.
2. Footer-Button „Teilen…" klicken → Bestätigungs-Dialog erscheint, „Senden" → Mail geht raus.
3. Mail im Postfach des Empfängers prüfen: korrektes Subject, HTML-Body, JSON-Anhang, korrekter Inhalt.

- [ ] **Step 4: Manual smoke test (import path)**

Mit der eben gesendeten JSON-Datei (oder einer Test-Datei):

1. Settings öffnen → „Arbeitszeiten importieren…" klicken.
2. Datei-Picker → JSON wählen.
3. Summary-Modal: Counts plausibel? Range ändern → Counts updaten live?
4. „Alles vom Import" → Weiter → Kalender refresht, Einträge da.
5. Wiederholung mit „Alles lokal behalten" → konfliktbehaftete Tage unverändert.
6. Wiederholung mit „Pro Tag entscheiden" → Pro-Tag-Modal öffnet, Wahl möglich, Anwenden funktioniert.
7. Abbrechen im Pro-Tag-Modal → kein Effekt (atomar).
8. Defekte Datei (z.B. random JSON) → klare Fehlermeldung, kein lokaler Datenverlust.

- [ ] **Step 5: Commit**

```bash
git add src/ui.py src/dialogs/settings_dialog.py
git commit -m "feat(ui): wire up Teilen-Button + Import-Eintrag im Settings-Dialog

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 13: CHANGELOG-Eintrag

**Files:**
- Modify: `CHANGELOG.md`

- [ ] **Step 1: Read existing CHANGELOG to follow conventions**

Read `CHANGELOG.md` to see the current top-most unreleased section (oder die jüngste Release-Sektion).

- [ ] **Step 2: Add an entry under „Unreleased" or the current dev version**

Add bullet points like:

```markdown
- Arbeitszeiten an eine zweite Person teilen: neuer Footer-Button „Teilen…" und Empfänger-Adresse „Teilen mit:" in den Einstellungen.
- Arbeitszeiten aus einer Share-Datei importieren: Einstellungen → „Arbeitszeiten importieren…", mit Zeitraum-Filter und drei Konflikt-Modi (alles importieren / alles lokal / pro Tag entscheiden).
```

- [ ] **Step 3: Commit**

```bash
git add CHANGELOG.md
git commit -m "docs(changelog): note share + import feature

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Self-Review Notes

**Spec coverage check:**
- Eigenes Wire-Format mit `kind`-Marker → Task 2 (parse) + Task 3 (build/serialize) ✓
- Defensive Validation, lokaler Bestand intakt bei kaputtem File → Task 2 ✓
- `share_recipient` Setting (per-device, nicht synced) → Task 7 ✓
- `Storage.save_many` (atomar) → Task 1 ✓
- Diff mit Range-Filter → Task 4 + Task 5 ✓
- `apply_import` (eine save_many-Call) → Task 6 ✓
- Mail-Pipeline mit JSON-Anhang → Task 8 ✓
- Settings-Dialog Feld + Import-Button → Task 9 + Task 12 ✓
- Share-Dialog (Export) → Task 10 ✓
- Import-Dialog mit Live-Range, Konflikt-Modi, Pro-Tag-Modal, atomarer Abbruch → Task 11 ✓
- UI-Verdrahtung Footer-Button + Settings-Eintrag → Task 12 ✓
- CHANGELOG → Task 13 ✓

**Placeholder scan:** Keine TBDs/TODOs in den Steps. Alle Code-Blöcke sind vollständig.

**Type/Name consistency:**
- `ShareValidationError` (Task 2) wird in Task 11 importiert ✓
- `build_share_doc` / `serialize_share_doc` / `parse_share_doc` / `diff_share_against_local` / `apply_import` — alle in Tasks 2-6 definiert, in Tasks 10-11 verwendet ✓
- `Storage.save_many` (Task 1) wird in Task 6 von `apply_import` aufgerufen ✓
- `send_email`-Signatur (Task 8) — Task 10 nutzt neue Parameter-Namen, Task 8 migriert send_dialog parallel ✓
- `share_recipient` (Task 7) wird in Tasks 9 (settings_dialog) und 10 (share_dialog) gelesen ✓
- `_FakeStorage` (Task 3) wird in Task 4 + Task 5 wiederverwendet — Definition in Task 3 enthält bereits `get_all()`, was ausreicht ✓
