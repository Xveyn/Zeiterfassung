# Tombstone-Kompaktierung Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eine vom Nutzer ausgelöste „Sync-Daten kompaktieren"-Aktion, die alte Tombstones (gelöschte Einträge + aufgelöste Konflikte) fleet-weit aus dem Google-Drive-Sync entfernt — sicher, ohne Auto-GC.

**Architecture:** Das Sync-Doc bekommt `meta.gc_watermark` (Schema v2). Die `merge`-Funktion (Signatur unverändert) propagiert das Watermark monoton und wendet zwei Regeln an: Regel 1 entfernt settled Tombstones (`< watermark`) → propagiert die Kompaktierung; Regel 2 unterdrückt Resurrection durch ein lange offline gewesenes Gerät. Das Watermark wird **nur** durch die manuelle Aktion gesetzt (Bestätigung + v1-Schema-Guard). Pure Logik in `sync.py`/`storage.py` (TDD), Orchestrierung/UI in `main.py`/`settings_dialog.py` (manueller Verify).

**Tech Stack:** Python 3, Tkinter, pytest, Google Drive API (bestehender Wrapper `src/drive.py`).

**Spec:** [`docs/superpowers/specs/2026-06-09-tombstone-gc-design.md`](../specs/2026-06-09-tombstone-gc-design.md)

---

## File Structure

| Datei | Verantwortung | Art |
|-------|---------------|-----|
| `src/settings.py` | lokaler Cache-Key `gc_watermark` | Config |
| `src/sync.py` | Schema-Bump, Watermark-Propagation, Regel 1 + 2 in `merge`, `compact_doc`, settled-Prädikate, `compact_local`, `_remote_is_pre_v2` | Pure Logik (TDD) |
| `src/storage.py` | (nur Wiederverwendung von `apply_merge` für den lokalen Strip — keine neue Methode nötig) | — |
| `src/main.py` | `_run_compaction_blocking` (Pull→Guard→Merge→Watermark/Strip→Push) | Orchestrierung (manueller Verify) |
| `src/dialogs/settings_dialog.py` | Button „Sync-Daten kompaktieren" + Bestätigungs-Dialog | UI (manueller Verify) |
| `docs/known-limitations.md` | Limitierungs-Eintrag umschreiben | Doku |
| `tests/test_sync.py` | Tests für alle pure Teile | Test |

**Konventionen (aus dem Repo):** Tests nutzen `_e(...)`/`_doc(...)`/`_s(...)`/`_conflict(...)`-Helfer (bereits in `tests/test_sync.py`). ISO-Zeit im Format `%Y-%m-%dT%H:%M:%SZ` (lexikografisch = chronologisch). `merge` ist pure. UI-Fehler immer per `messagebox.showerror` + `traceback` (CLAUDE.md). Tests laufen mit `pytest` aus dem Repo-Root.

---

## Chunk 1: Pure Sync-Logik (TDD)

### Task 1: Settings-Cache-Key `gc_watermark`

**Files:**
- Modify: `src/settings.py` (DEFAULTS-Dict)

- [ ] **Step 1: Key in DEFAULTS ergänzen**

In `src/settings.py`, im `DEFAULTS`-Dict, bei den lokalen Sync-Bookkeeping-Keys (`last_pull_at`, `drive_etag`) ergänzen:

```python
    "drive_etag": "",
    "gc_watermark": "",
```

(Nicht in `SYNCED_SETTING_KEYS` — bleibt gerätelokal.)

- [ ] **Step 2: Verify**

Run: `pytest tests/test_settings.py -q`
Expected: PASS (kein Verhalten geändert, nur ein neuer Default).

- [ ] **Step 3: Commit**

```bash
git add src/settings.py
git commit -m "feat(sync): lokalen gc_watermark-Cache-Key ergänzen"
```

---

### Task 2: Schema-Bump v2 + Watermark-Propagation (merge round-trip)

**Files:**
- Modify: `src/sync.py` (`SCHEMA_VERSION`, `merge`, `build_local_doc`, `apply_merged_doc`)
- Test: `tests/test_sync.py`

- [ ] **Step 1: Failing Tests schreiben**

Am Ende von `tests/test_sync.py` ergänzen. (Helfer `_meta_doc` erlaubt ein Doc mit `meta`.)

```python
# --- Tombstone-Kompaktierung: Watermark-Propagation ---

def _meta_doc(entries=None, conflicts=None, watermark=""):
    d = _doc(entries=entries, conflicts=conflicts)
    d["schema_version"] = 2
    d["meta"] = {"gc_watermark": watermark}
    return d


def test_merge_watermark_propagates_max():
    local = _meta_doc(watermark="2026-05-01T00:00:00Z")
    remote = _meta_doc(watermark="2026-05-10T00:00:00Z")
    merged = merge(local, remote, "2026-04-01T00:00:00Z")
    assert merged["meta"]["gc_watermark"] == "2026-05-10T00:00:00Z"


def test_merge_watermark_monotonic_local_wins_when_remote_missing_meta():
    """v1-Remote ohne meta darf das lokale Watermark nicht zurücksetzen."""
    local = _meta_doc(watermark="2026-05-10T00:00:00Z")
    remote = _doc()  # schema_version 1, kein meta
    merged = merge(local, remote, "2026-04-01T00:00:00Z")
    assert merged["meta"]["gc_watermark"] == "2026-05-10T00:00:00Z"


def test_merge_no_meta_either_side_yields_empty_watermark():
    merged = merge(_doc(), _doc(), "2026-04-01T00:00:00Z")
    assert merged["meta"]["gc_watermark"] == ""
```

Außerdem die **bestehende** Assertion in `test_build_local_doc_includes_storage_settings_conflicts` anpassen:

```python
    assert doc["schema_version"] == 2
```

und einen Round-Trip-Test für das Watermark ergänzen:

```python
def test_build_local_doc_includes_watermark_from_settings(tmp_path):
    storage = Storage(str(tmp_path / "z.json"), device_id="A")
    settings = Settings(str(tmp_path / "s.json"))
    settings.set("gc_watermark", "2026-05-10T00:00:00Z")
    conflicts = ConflictsStore(str(tmp_path / "c.json"))
    doc = build_local_doc(storage, settings, conflicts)
    assert doc["meta"]["gc_watermark"] == "2026-05-10T00:00:00Z"


def test_apply_merged_doc_persists_watermark(tmp_path):
    storage = Storage(str(tmp_path / "z.json"), device_id="A")
    settings = Settings(str(tmp_path / "s.json"))
    conflicts = ConflictsStore(str(tmp_path / "c.json"))
    merged = _meta_doc(watermark="2026-05-11T00:00:00Z")
    apply_merged_doc(merged, storage, settings, conflicts)
    assert settings.get("gc_watermark") == "2026-05-11T00:00:00Z"
```

- [ ] **Step 2: Run, erwartet FAIL**

Run: `pytest tests/test_sync.py -k "watermark or build_local_doc_includes_storage or apply_merged_doc_persists" -v`
Expected: FAIL (`merged["meta"]` KeyError; `schema_version` ist 1).

- [ ] **Step 3: Implementieren**

In `src/sync.py`:

```python
SCHEMA_VERSION = 2
```

Helfer am Modulanfang (nach `SCHEMA_VERSION`):

```python
def _watermark_of(doc):
    return ((doc.get("meta") or {}).get("gc_watermark") or "")
```

In `merge(local, remote, last_pull_at)`, das `merged`-Skeleton um `meta` erweitern und das Watermark direkt nach dem Skeleton berechnen:

```python
    merged = {
        "schema_version": SCHEMA_VERSION,
        "entries": {},
        "settings": {},
        "conflicts": [],
        "meta": {"gc_watermark": ""},
    }
    watermark = max(_watermark_of(local), _watermark_of(remote))
    merged["meta"]["gc_watermark"] = watermark
```

(Die `max`-Bildung über die ISO-Strings ist monoton; leere Strings sind kleinster Wert.)

In `build_local_doc`, das zurückgegebene Doc um `meta` erweitern:

```python
def build_local_doc(storage, settings, conflicts_store):
    return {
        "schema_version": SCHEMA_VERSION,
        "entries": storage.get_all_raw(),
        "settings": settings.get_synced_doc(),
        "conflicts": conflicts_store.get_all(),
        "meta": {"gc_watermark": settings.get("gc_watermark") or ""},
    }
```

In `apply_merged_doc`, das Watermark persistieren:

```python
def apply_merged_doc(merged_doc, storage, settings, conflicts_store):
    storage.apply_merge(merged_doc.get("entries", {}))
    settings.apply_synced(merged_doc.get("settings", {}))
    conflicts_store.save_all(merged_doc.get("conflicts", []))
    settings.set("gc_watermark", (merged_doc.get("meta") or {}).get("gc_watermark") or "")
```

- [ ] **Step 4: Run, erwartet PASS**

Run: `pytest tests/test_sync.py -v`
Expected: PASS (auch alle bestehenden Tests — `merged` hat jetzt zusätzlich `meta`, was keine bestehende Assertion verletzt).

- [ ] **Step 5: Commit**

```bash
git add src/sync.py tests/test_sync.py
git commit -m "feat(sync): Schema v2 mit meta.gc_watermark + monotoner Propagation"
```

---

### Task 3: Regel 1 — settled Tombstones entfernen (Kompaktierung propagieren)

**Files:**
- Modify: `src/sync.py` (settled-Prädikate, Drop-Schritt am Ende von `merge`)
- Test: `tests/test_sync.py`

- [ ] **Step 1: Failing Tests schreiben**

```python
# --- Regel 1: settled Tombstones droppen ---

def test_merge_drops_settled_entry_tombstone():
    wm = "2026-05-10T00:00:00Z"
    local = _meta_doc(
        entries={"D": _e(None, None, None, "2026-05-05T00:00:00Z", deleted=True)},
        watermark=wm,
    )
    merged = merge(local, _meta_doc(watermark=wm), "2026-04-01T00:00:00Z")
    assert "D" not in merged["entries"]


def test_merge_keeps_tombstone_at_or_after_watermark():
    wm = "2026-05-10T00:00:00Z"
    # genau auf der Grenze: strikt < → bleibt
    local = _meta_doc(
        entries={"D": _e(None, None, None, wm, deleted=True)},
        watermark=wm,
    )
    merged = merge(local, _meta_doc(watermark=wm), "2026-04-01T00:00:00Z")
    assert "D" in merged["entries"]


def test_merge_keeps_live_entry_older_than_watermark():
    """Regel 1 entfernt nur deleted-Einträge, keine lebenden."""
    wm = "2026-05-10T00:00:00Z"
    local = _meta_doc(
        entries={"D": _e("08:00", "16:00", 30, "2026-05-05T00:00:00Z")},
        watermark=wm,
    )
    merged = merge(local, _meta_doc(watermark=wm), "2026-04-01T00:00:00Z")
    assert "D" in merged["entries"]


def test_merge_compaction_propagates_and_sticks():
    """Gerät B hält lokalen Tombstone, pullt kompaktierten Remote (ohne D,
    Watermark gesetzt) → B verwirft den Tombstone, lädt ihn nicht erneut hoch."""
    wm = "2026-05-10T00:00:00Z"
    local = _meta_doc(  # B hat den alten Tombstone noch
        entries={"D": _e(None, None, None, "2026-05-05T00:00:00Z", deleted=True)},
        watermark="",
    )
    remote = _meta_doc(entries={}, watermark=wm)  # bereits kompaktiert
    merged = merge(local, remote, "2026-05-06T00:00:00Z")
    assert "D" not in merged["entries"]
    assert merged["meta"]["gc_watermark"] == wm


def test_merge_recovers_after_failed_compaction_push():
    """Partial-Failure: lokal wurde kompaktiert (Watermark=now gesetzt), aber der
    Push schlug fehl → Remote trägt den Tombstone noch. Beim nächsten Sync gewinnt
    das höhere lokale Watermark monoton und Regel 1 entfernt den Remote-Tombstone."""
    now = "2026-06-09T12:00:00Z"
    local = _meta_doc(entries={}, watermark=now)  # lokal schon kompaktiert
    remote = _meta_doc(  # Remote hat den alten Tombstone noch, altes/leeres Watermark
        entries={"D": _e(None, None, None, "2026-05-05T00:00:00Z", deleted=True)},
        watermark="",
    )
    merged = merge(local, remote, "2026-05-06T00:00:00Z")
    assert "D" not in merged["entries"]
    assert merged["meta"]["gc_watermark"] == now


def test_merge_drops_settled_resolved_conflict():
    wm = "2026-05-10T00:00:00Z"
    c = _conflict("c-1", resolved=True, resolution={"start": "08:00"},
                  resolved_at="2026-05-05T00:00:00Z", resolved_by="A")
    local = _meta_doc(conflicts=[c], watermark=wm)
    merged = merge(local, _meta_doc(watermark=wm), "2026-04-01T00:00:00Z")
    assert merged["conflicts"] == []


def test_merge_keeps_resolved_conflict_without_resolved_at():
    """Defensiv: resolved=True aber resolved_at None/'' → nicht droppen (kein Crash)."""
    wm = "2026-05-10T00:00:00Z"
    c = _conflict("c-1", resolved=True, resolution={"start": "08:00"},
                  resolved_at=None, resolved_by="A")
    local = _meta_doc(conflicts=[c], watermark=wm)
    merged = merge(local, _meta_doc(watermark=wm), "2026-04-01T00:00:00Z")
    assert len(merged["conflicts"]) == 1


def test_merge_keeps_unresolved_conflict_regardless_of_watermark():
    wm = "2026-05-10T00:00:00Z"
    c = _conflict("c-1", resolved=False)
    local = _meta_doc(conflicts=[c], watermark=wm)
    merged = merge(local, _meta_doc(watermark=wm), "2026-04-01T00:00:00Z")
    assert len(merged["conflicts"]) == 1


def test_merge_no_drop_when_watermark_empty():
    """Backwards-compat: ohne Watermark verhält sich merge wie bisher."""
    local = _doc(entries={"D": _e(None, None, None, "2026-05-05T00:00:00Z", deleted=True)})
    merged = merge(local, _doc(), "2026-04-01T00:00:00Z")
    assert "D" in merged["entries"]
```

- [ ] **Step 2: Run, erwartet FAIL**

Run: `pytest tests/test_sync.py -k "drops_settled or keeps_tombstone or compaction_propagates or recovers_after or keeps_resolved or keeps_unresolved or keeps_live or no_drop_when" -v`
Expected: FAIL (Tombstones bleiben erhalten).

- [ ] **Step 3: Implementieren**

Settled-Prädikate in `src/sync.py` (Modulebene, nach `_watermark_of`):

```python
def _is_settled_entry(entry, watermark):
    return bool(entry.get("deleted")) and (entry.get("modified_at") or "") < watermark


def _is_settled_conflict(conflict, watermark):
    resolved_at = conflict.get("resolved_at") or ""
    return bool(conflict.get("resolved")) and resolved_at != "" and resolved_at < watermark
```

Drop-Schritt **als letzter Schritt** in `merge`, NACH der bestehenden Resolution-Application-Schleife (die `merged["conflicts"]` iteriert und resolved-Werte in `merged["entries"]` schreibt), direkt vor `return merged`:

```python
    # Regel 1: settled Tombstones entfernen (Kompaktierung propagieren).
    # Läuft NACH der Resolution-Application, damit kein resolved-Wert verloren geht.
    if watermark:
        merged["entries"] = {
            k: v for k, v in merged["entries"].items()
            if not _is_settled_entry(v, watermark)
        }
        merged["conflicts"] = [
            c for c in merged["conflicts"]
            if not _is_settled_conflict(c, watermark)
        ]

    return merged
```

- [ ] **Step 4: Run, erwartet PASS**

Run: `pytest tests/test_sync.py -v`
Expected: PASS (alle, inkl. bestehende).

- [ ] **Step 5: Commit**

```bash
git add src/sync.py tests/test_sync.py
git commit -m "feat(sync): Regel 1 — settled Tombstones bei Merge entfernen"
```

---

### Task 4: Regel 2 — Self-Heal-Suppression (excluded-gated)

**Files:**
- Modify: `src/sync.py` (`merge`, Entries-Schleife)
- Test: `tests/test_sync.py`

- [ ] **Step 1: Failing Tests schreiben**

```python
# --- Regel 2: Self-Heal-Suppression ---

def test_merge_suppresses_stale_live_entry_for_excluded_device():
    """Zurückkehrendes Gerät (last_pull_at < remote.watermark) verwirft einen
    alten, anderswo gelöschten-und-kompaktierten Tag statt ihn aufstehen zu lassen."""
    wm = "2026-05-10T00:00:00Z"
    local = _meta_doc(
        entries={"D": _e("08:00", "16:00", 30, "2026-05-05T00:00:00Z")},  # alt, lebend
        watermark="",
    )
    remote = _meta_doc(entries={}, watermark=wm)  # D wurde anderswo kompaktiert
    # last_pull_at < remote.watermark → excluded
    merged = merge(local, remote, "2026-05-06T00:00:00Z")
    assert "D" not in merged["entries"]


def test_merge_first_sync_device_keeps_history():
    """Erstsync (last_pull_at == '') ist NICHT excluded → Historie bleibt/lädt hoch."""
    wm = "2026-05-10T00:00:00Z"
    local = _meta_doc(
        entries={"D": _e("08:00", "16:00", 30, "2026-05-05T00:00:00Z")},
        watermark="",
    )
    remote = _meta_doc(entries={}, watermark=wm)
    merged = merge(local, remote, "")  # Erstsync
    assert merged["entries"]["D"]["start"] == "08:00"


def test_merge_keeps_fresh_offline_edit_for_excluded_device():
    """Excluded, aber Eintrag NEUER als Watermark → echter Offline-Edit, bleibt."""
    wm = "2026-05-10T00:00:00Z"
    local = _meta_doc(
        entries={"D": _e("08:00", "16:00", 30, "2026-05-15T00:00:00Z")},  # > watermark
        watermark="",
    )
    remote = _meta_doc(entries={}, watermark=wm)
    merged = merge(local, remote, "2026-05-06T00:00:00Z")  # excluded
    assert merged["entries"]["D"]["start"] == "08:00"


def test_merge_no_suppression_when_remote_present():
    """Suppression greift nur bei remote-fehlendem Key."""
    wm = "2026-05-10T00:00:00Z"
    local = _meta_doc(
        entries={"D": _e("08:00", "16:00", 30, "2026-05-05T00:00:00Z")},
        watermark="",
    )
    remote = _meta_doc(
        entries={"D": _e("09:00", "17:00", 30, "2026-05-04T00:00:00Z")},
        watermark=wm,
    )
    merged = merge(local, remote, "2026-05-06T00:00:00Z")
    assert "D" in merged["entries"]
```

- [ ] **Step 2: Run, erwartet FAIL**

Run: `pytest tests/test_sync.py -k "suppresses_stale or first_sync_device_keeps or fresh_offline_edit or no_suppression_when" -v`
Expected: FAIL (`test_merge_suppresses_stale_live_entry_for_excluded_device` schlägt fehl — D bleibt).

- [ ] **Step 3: Implementieren**

In `merge`, `excluded` einmalig berechnen (direkt nach der Watermark-Zeile):

```python
    remote_wm = _watermark_of(remote)
    excluded = bool(last_pull_at) and last_pull_at < remote_wm
```

In der **Entries-Schleife**, nach dem `_merge_one`-Call, vor dem `if winner is not None`:

```python
        # Regel 2: Self-Heal — ein zurückgekehrtes (excluded) Gerät darf einen
        # alten, remote-fehlenden lebenden Eintrag nicht auferstehen lassen.
        if (excluded and r is None and l is not None
                and (l.get("modified_at") or "") < remote_wm):
            winner = None
```

(`l`, `r`, `winner` sind die bestehenden Variablen der Schleife. `_merge_one` bleibt unverändert.)

- [ ] **Step 4: Run, erwartet PASS**

Run: `pytest tests/test_sync.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/sync.py tests/test_sync.py
git commit -m "feat(sync): Regel 2 — Self-Heal-Suppression für excluded Geräte"
```

---

### Task 5: `compact_doc`, `compact_local`, `_remote_is_pre_v2`

**Files:**
- Modify: `src/sync.py` (drei neue Funktionen)
- Test: `tests/test_sync.py`

- [ ] **Step 1: Failing Tests schreiben**

```python
# --- Kompaktierungs-Helfer ---

from src.sync import compact_doc, compact_local, _remote_is_pre_v2


def test_compact_doc_sets_watermark_and_strips(tmp_path=None):
    now = "2026-06-09T12:00:00Z"
    doc = _meta_doc(
        entries={
            "DEL": _e(None, None, None, "2026-05-05T00:00:00Z", deleted=True),
            "LIVE": _e("08:00", "16:00", 30, "2026-05-05T00:00:00Z"),
        },
        conflicts=[_conflict("c-1", resolved=True, resolution={"start": "08:00"},
                             resolved_at="2026-05-05T00:00:00Z", resolved_by="A")],
        watermark="",
    )
    out = compact_doc(doc, now)
    assert out["meta"]["gc_watermark"] == now
    assert "DEL" not in out["entries"]
    assert "LIVE" in out["entries"]
    assert out["conflicts"] == []
    # pure: Original unverändert
    assert "DEL" in doc["entries"]


def test_compact_doc_idempotent_second_run_is_clean_noop_but_advances_watermark():
    out1 = compact_doc(_meta_doc(
        entries={"DEL": _e(None, None, None, "2026-05-05T00:00:00Z", deleted=True)},
        watermark=""), "2026-06-09T12:00:00Z")
    out2 = compact_doc(out1, "2026-06-10T12:00:00Z")
    assert out2["entries"] == {}
    assert out2["meta"]["gc_watermark"] == "2026-06-10T12:00:00Z"


def test_compact_local_strips_stores_and_sets_watermark(tmp_path):
    storage = Storage(str(tmp_path / "z.json"), device_id="A")
    storage.save("LIVE", "08:00", "16:00", 30)
    storage.save("DEL", "08:00", "16:00", 30)
    storage.delete("DEL")  # Tombstone
    settings = Settings(str(tmp_path / "s.json"))
    conflicts = ConflictsStore(str(tmp_path / "c.json"))
    conflicts.save_all([
        {"id": "c-1", "kind": "entry", "key": "X", "candidates": [],
         "detected_at": "...", "resolved": True, "resolution": {"start": "08:00"},
         "resolved_at": "2026-05-05T00:00:00Z", "resolved_by": "A"},
        {"id": "c-2", "kind": "entry", "key": "Y", "candidates": [],
         "detected_at": "...", "resolved": False, "resolution": None,
         "resolved_at": None, "resolved_by": None},
    ])
    now = "2026-06-09T12:00:00Z"
    compact_local(storage, settings, conflicts, now)

    assert settings.get("gc_watermark") == now
    raw = storage.get_all_raw()
    assert "DEL" not in raw            # Tombstone gestrippt
    assert "LIVE" in raw               # lebend bleibt
    remaining = [c["id"] for c in conflicts.get_all()]
    assert remaining == ["c-2"]        # nur unresolved bleibt


def test_remote_is_pre_v2():
    assert _remote_is_pre_v2({"schema_version": 1, "entries": {}}) is True
    assert _remote_is_pre_v2({"schema_version": 2, "entries": {}}) is True  # kein meta
    assert _remote_is_pre_v2({"schema_version": 2, "meta": {"gc_watermark": ""}}) is False
    assert _remote_is_pre_v2({"schema_version": 2, "meta": {}}) is True     # meta ohne key
```

- [ ] **Step 2: Run, erwartet FAIL**

Run: `pytest tests/test_sync.py -k "compact_doc or compact_local or remote_is_pre_v2" -v`
Expected: FAIL (ImportError — Funktionen existieren nicht).

- [ ] **Step 3: Implementieren**

In `src/sync.py`:

```python
def compact_doc(doc, now):
    """Pure: liefert eine Kopie von `doc` mit gesetztem gc_watermark=now und
    entfernten settled Tombstones (deleted-Einträge + resolved Konflikte mit
    Zeit < now). Mutiert `doc` nicht."""
    return {
        "schema_version": SCHEMA_VERSION,
        "entries": {
            k: v for k, v in doc.get("entries", {}).items()
            if not _is_settled_entry(v, now)
        },
        "settings": dict(doc.get("settings", {})),
        "conflicts": [
            c for c in doc.get("conflicts", [])
            if not _is_settled_conflict(c, now)
        ],
        "meta": {"gc_watermark": now},
    }


def compact_local(storage, settings, conflicts_store, now):
    """Schreibt das gc_watermark lokal und strippt settled Tombstones aus
    Storage und ConflictsStore. Ein lokaler Schreibvorgang pro Store
    (Wiederverwendung von storage.apply_merge — Required-Key-Validator +
    Atomic-Write bleiben auf einem Pfad)."""
    settings.set("gc_watermark", now)
    storage.apply_merge({
        k: v for k, v in storage.get_all_raw().items()
        if not _is_settled_entry(v, now)
    })
    conflicts_store.save_all([
        c for c in conflicts_store.get_all()
        if not _is_settled_conflict(c, now)
    ])


def _remote_is_pre_v2(remote_doc):
    """True, wenn das Remote-Doc von einem v1-Gerät stammt (Schema < 2 oder
    fehlendes/leeres meta ohne gc_watermark-Key) — dann ist gerade ein älteres
    Gerät aktiv und die Kompaktierung muss abbrechen."""
    if (remote_doc.get("schema_version") or 1) < 2:
        return True
    meta = remote_doc.get("meta")
    return not (isinstance(meta, dict) and "gc_watermark" in meta)
```

- [ ] **Step 4: Run, erwartet PASS**

Run: `pytest tests/test_sync.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/sync.py tests/test_sync.py
git commit -m "feat(sync): compact_doc/compact_local + v1-Remote-Guard"
```

---

## Chunk 2: Orchestrierung + UI (manueller Verify)

> Diese Tasks sind Wiring/UI ohne sinnvolle Unit-Tests (Drive-I/O, Tkinter). Verifikation manuell, siehe Verify-Pfade. `_remote_is_pre_v2` (Task 5) ist unit-getestet und kapselt die einzige nicht-triviale Entscheidung.

### Task 6: `_run_compaction_blocking` in `main.py`

**Files:**
- Modify: `src/main.py` (neue Funktion neben `_run_push_blocking`)

- [ ] **Step 1: Funktion implementieren**

Orientierung an `_run_push_blocking` (Thread + Timeout, `result`-Dict). Ablauf: Pull → v1-Guard → normaler Merge (wie Pull) → `last_pull_at = now` → `compact_local(now)` → Push. Ein einziges `now` für Merge-Stempel und Kompaktierung wiederverwenden ist nicht nötig (sie sind unabhängig), aber `last_pull_at` und das Watermark sollen aus demselben `now` stammen.

```python
def _run_compaction_blocking(storage, settings, conflicts_store, base, timeout_seconds=20):
    """User-ausgelöste Kompaktierung: frischer Pull → v1-Guard → Merge →
    Watermark setzen + lokal strippen → Push. Liefert
    {"ok": bool, "reason": str, "error": ..., "tb": ...}.

    reason == "old_version": ein älteres Gerät ist aktiv (Remote ist pre-v2),
    Kompaktierung abgebrochen, KEINE Änderung vorgenommen."""
    import json
    from src import drive, sync

    result = {}

    def _do():
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
                # v1-Guard auf dem FRISCH gepullten Doc (nie gecacht):
                if sync._remote_is_pre_v2(remote_doc):
                    result.update({"ok": False, "reason": "old_version"})
                    return
            else:
                remote_doc = {"schema_version": 2, "entries": {}, "settings": {},
                              "conflicts": [], "meta": {"gc_watermark": ""}}

            # 1) normaler Merge des frischen Remote-Stands
            now = sync._utc_now_iso()
            local_doc = sync.build_local_doc(storage, settings, conflicts_store)
            merged = sync.merge(local_doc, remote_doc, settings.get("last_pull_at") or "")
            sync.apply_merged_doc(merged, storage, settings, conflicts_store)
            settings.set("last_pull_at", now)
            # 2) Watermark setzen + lokal strippen
            sync.compact_local(storage, settings, conflicts_store, now)
            # 3) kompaktiertes Doc hochladen
            doc = sync.build_local_doc(storage, settings, conflicts_store)
            payload = json.dumps(doc, ensure_ascii=False).encode("utf-8")
            new_id, new_etag = drive.upload(service, payload, file_id, expected_etag="")
            settings.set("drive_etag", new_etag)
            result.update({"ok": True})
        except Exception as e:
            logging.getLogger(__name__).exception("Kompaktierung fehlgeschlagen")
            result.update({"ok": False, "error": str(e), "tb": traceback.format_exc()})

    t = threading.Thread(target=_do, daemon=True)
    t.start()
    t.join(timeout=timeout_seconds)
    if not result:
        result = {"ok": False, "error": "Timeout", "tb": ""}
    return result
```

> **Bewusst NICHT anfassen:** die bestehenden `{"schema_version": 1, …}`-Literale in `main.py` (`_parse_remote_or_quarantine` Korrupt-Fallback, Missing-File-Fallback im Pull, Push-Retry-Fallback) bleiben **unverändert**. Sie sind sicher — `merge` liest sie über `_watermark_of` als leeres Watermark (kein Drop, keine Suppression) — und die Tests `tests/test_sync.py::test_main_pull_*` asserten bewusst v1 auf `_parse_remote_or_quarantine`. Nicht „aufräumen", sonst brechen diese Tests. Der Korrupt-Fallback in `_run_compaction_blocking` (`{"schema_version": 1}`) ist Absicht: ein nicht-parsebarer Remote löst über `_remote_is_pre_v2` einen sicheren Abbruch aus (keine Kompaktierung gegen korrupten Stand).

- [ ] **Step 2: Build-Verify (Import/Syntax)**

Run: `python -c "import src.main"`
Expected: kein Fehler.

- [ ] **Step 3: Commit**

```bash
git add src/main.py
git commit -m "feat(sync): _run_compaction_blocking (Pull/Guard/Merge/Strip/Push)"
```

---

### Task 7: UI-Button „Sync-Daten kompaktieren"

**Files:**
- Modify: `src/dialogs/settings_dialog.py` (neuer Button am Ende der Sync-Sektion + Renumbering der gcal-Sektion)

> **IST-Stand (geprüft):** Der Dialog nutzt EIN gemeinsames Grid. Belegte Rows:
> 21 Sync-Header · 22 Sync-Checkbox · 23 Geräte-ID · 24 Letzte Synchronisation · 25 „Konflikte ansehen" (nur wenn `unresolved > 0`) · 26 „Arbeitszeiten importieren…" (nur wenn `storage is not None`) · 27 gcal-Header · 28 `cb_gcal` · 29 `cal_combo` + „Kalender:"-Label · 30 `cal_status` · 31 `btn_frame` (Speichern/Abbrechen).
> Es gibt **keine** freie Row. Der neue Button kommt auf eine **neue row 27**, die gcal-Sektion + Button-Frame wandern um **+1** nach unten.

- [ ] **Step 1: Compaction-Button einfügen (neue row 27)**

Direkt **vor** dem Kommentar `# --- Google Kalender (Reservierungen) ---` (aktuell vor `dialog`-Label row 27) einfügen. Stil über den vorhandenen `secondary_button`-Helfer (Frame+Label-Konstrukt, kein `tk.Button` — bereits importiert via `from src.theme import ... secondary_button`). `messagebox`, `threading`, `storage`, `settings`, `conflicts_store`, `base_path` sind in der Funktion in Scope (siehe bestehende Sync-/gcal-Sektion):

```python
    if settings.get("sync_enabled"):
        def _on_compact_clicked():
            confirmed = messagebox.askyesno(
                "Sync-Daten kompaktieren",
                "Entfernt alte gelöschte Einträge endgültig aus dem Sync.\n\n"
                "Nur ausführen, wenn ALLE deine Geräte auf der aktuellen Version "
                "sind und kürzlich synchronisiert haben.\n\nFortfahren?",
                parent=dialog,
            )
            if not confirmed:
                return

            def _show(res):
                if not dialog.winfo_exists():
                    return
                if res.get("reason") == "old_version":
                    messagebox.showwarning(
                        "Kompaktierung abgebrochen",
                        "Ein Gerät nutzt noch eine ältere Version — bitte erst "
                        "alle Geräte aktualisieren und synchronisieren.",
                        parent=dialog,
                    )
                elif not res.get("ok"):
                    detail = f"{res.get('error', '?')}\n\n{res.get('tb', '')}"
                    messagebox.showerror(
                        "Kompaktierung fehlgeschlagen",
                        f"Die Kompaktierung ist fehlgeschlagen:\n\n{detail}",
                        parent=dialog,
                    )
                else:
                    messagebox.showinfo(
                        "Kompaktierung", "Sync-Daten wurden kompaktiert.",
                        parent=dialog,
                    )

            def _do():
                from src.main import _run_compaction_blocking
                res = _run_compaction_blocking(
                    storage, settings, conflicts_store, base_path)
                dialog.after(0, lambda: _show(res))

            threading.Thread(target=_do, daemon=True).start()

        secondary_button(
            dialog, "Sync-Daten kompaktieren", _on_compact_clicked,
            padx=12, pady=2,
        ).grid(row=27, column=0, columnspan=2, padx=10, pady=(0, 8), sticky="w")
```

- [ ] **Step 2: gcal-Sektion + Button-Frame um +1 renumbern**

Exakt diese `grid(row=…)`-Werte ändern (Reihenfolge wie im File):

| Widget | alt | neu |
|--------|-----|-----|
| gcal-Header-Label (`— Google Kalender —`) | 27 | 28 |
| `cb_gcal.grid(...)` | 28 | 29 |
| „Kalender:"-Label + `cal_combo.grid(...)` (beide) | 29 | 30 |
| `cal_status.grid(...)` | 30 | 31 |
| `btn_frame.grid(...)` | 31 | 32 |

Nichts anderes anfassen (nur die `row=`-Zahlen).

- [ ] **Step 3: Build-Verify**

Run: `python -c "import src.dialogs.settings_dialog"`
Expected: kein Fehler.

- [ ] **Step 4: Manueller Verify (Übergabe-relevant)**

App starten (`python -m src.main`), Einstellungen öffnen → bei aktivem Sync erscheint „Sync-Daten kompaktieren" unterhalb der Sync-Controls, oberhalb des Google-Kalender-Abschnitts; Layout der gcal-Sektion unverschoben/intakt. Klick → Bestätigung → Verhalten je nach Remote-Zustand (Verify-Matrix).

- [ ] **Step 5: Commit**

```bash
git add src/dialogs/settings_dialog.py
git commit -m "feat(ui): Button 'Sync-Daten kompaktieren' in den Einstellungen"
```

---

### Task 8: `known-limitations.md` umschreiben

**Files:**
- Modify: `docs/known-limitations.md`

- [ ] **Step 1: Abschnitt ersetzen**

Den Abschnitt „## Sync: Keine Tombstone-Garbage-Collection" ersetzen durch eine Beschreibung der manuellen Kompaktierung: bewusste Entscheidung gegen Auto-GC (Mixed-Version-Fleet-Hazard), wie die Aktion funktioniert (Bestätigung + v1-Schema-Guard), und die **akzeptierten Restrisiken**: (a) v1-Gerät offline während Kompaktierung, das mit Altdaten zurückkehrt → Resurrection möglich (Mitigation: Schema-Guard + Bestätigung; harte Empfehlung „alle Geräte aktuell"); (b) v2-Offline-Edit mit `modified_at` vor dem Watermark → Verlust-Edge; (c) Clock-Skew. Verweis auf die Spec.

- [ ] **Step 2: Commit**

```bash
git add docs/known-limitations.md
git commit -m "docs: known-limitations auf manuelle Tombstone-Kompaktierung aktualisieren"
```

---

## Verify-Matrix (manueller Verify, Übergabe)

| Szenario | Schritt | Erwartung |
|----------|---------|-----------|
| Happy path | 2 Geräte (beide aktuell), auf A einen Tag löschen, beide syncen, dann auf A „Kompaktieren" | Erfolg-Dialog; Sync-File enthält den Tombstone nicht mehr; B räumt den Tombstone beim nächsten Sync ebenfalls ab und lädt ihn nicht erneut hoch |
| v1 aktiv | Ein Gerät auf alter Version pusht zuletzt (Remote pre-v2), dann „Kompaktieren" | Warn-Dialog „ältere Version", **keine** Änderung an lokalen/Remote-Daten |
| Push-Fehler | Netzwerk trennen, „Kompaktieren" | Fehler-Dialog mit Traceback; beim nächsten normalen Sync vollendet sich die Kompaktierung selbst (lokales Watermark gewinnt monoton) |
| Erstsync | Frisches Gerät mit lokaler Historie, Sync aktivieren, pullen | Historie geht NICHT verloren (Erstsync ist nicht excluded) |
| v2-Straggler / falsche Zusicherung | v2-Gerät B war beim Kompaktieren offline (Tag D auf A gelöscht+kompaktiert, B hält D noch lebend), B kommt zurück und pullt beim Start | B verwirft D (Regel 2, excluded) → **keine** Resurrection, auch wenn die „alle synchronisiert"-Zusicherung falsch war (pinned durch Task-4-Unit-Test) |

## Reihenfolge & Abhängigkeiten

Tasks 1→5 strikt sequenziell (jeder baut auf dem vorigen `merge`-Stand auf). Task 6 hängt an 2–5 (nutzt `compact_local`, `_remote_is_pre_v2`, `merge`). Task 7 hängt an 6. Task 8 unabhängig (kann jederzeit nach Task 5).

**Gate vor PR:** `pytest` komplett grün; `python -c "import src.main; import src.dialogs.settings_dialog"`; manuelle Verify-Matrix (mind. Happy path + v1-aktiv).
