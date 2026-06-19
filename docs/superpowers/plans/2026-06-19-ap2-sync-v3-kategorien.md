# AP2 — Sync v3 + Kategorien-Setting Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Die Sync-Engine (`src/sync.py`) auf das Multi-Slot-Schema heben (Schema v2 → v3, Slot-Listen-Vergleich, Konflikt-Durchreichung auf Slot-Basis, Alt-Client-Guard) und eine syncbare Kategorien-Liste in den Settings einführen.

**Architecture:** Der Tag bleibt die Sync-/Konflikt-Einheit (LWW pro Datum, unverändert). Nur die Wert-Gleichheit (`_values_equal_entry`) und die Konflikt-Resolution wechseln von `{start,end,pause}` auf die Slot-Liste. Kategorien sind ein neuer String-Array-Setting-Key, der über die bestehende Settings-Sync-Whitelist mitläuft. Ein neuer `_remote_is_pre_v3`-Guard ersetzt `_remote_is_pre_v2` im Kompaktierungspfad.

**Tech Stack:** Python stdlib, pytest. Keine neuen Dependencies.

## Global Constraints

- **Tag bleibt Sync-/Konflikt-Einheit.** Day-level-LWW, Konflikt-Dedup, Watermark/Tombstone-Kompaktierung und Self-Heal-Regeln bleiben **strukturell unverändert** — sie operieren weiter pro Datum.
- **`SCHEMA_VERSION = 3`** in `src/sync.py`.
- **`_values_equal_entry`** vergleicht die **Slot-Liste reihenfolge-normalisiert** (nach Slot-Feldern sortiert) plus `deleted`. Slot-Felder: `start, end, pause (Default 0), kategorie (Default "")`.
- **Kategorie-Setting:** neuer Key `categories` = `list[str]`, Default `[]`. Muss in **beiden** `SYNCED_SETTING_KEYS` stehen (`src/settings.py` UND `src/sync.py`) — der Test `test_synced_whitelists_in_settings_and_sync_match` erzwingt Gleichheit.
- **Konflikt-Eingriff bewusst minimal:** Kandidaten tragen die Slot-Liste automatisch; nur `resolve_conflict` (entry-Zweig) und der Resolution-Apply-Block in `merge()` schreiben statt `{start,end,pause}` eine Slot-Liste. Der Konflikt-Flow wird voraussichtlich bald überarbeitet — **keine** neuen tiefen Annahmen verankern.
- **Alt-Client-Guard:** `_remote_is_pre_v3(remote_doc)` = `(schema_version or 1) < 3`. Ersetzt `_remote_is_pre_v2` im Kompaktierungspfad (`src/main.py`). Bei pre-v3-Remote wird die Kompaktierung ausgesetzt (bestehender `reason="old_version"`-Pfad).
- **Datumsformat:** intern ISO; nicht ändern.
- **Harter Schnitt (laufend):** Nur die AP2-Dateien werden angepasst. Consumer außerhalb (report, share, ui, gcal) bleiben rot bis zu ihren Paketen. Verifikation pro Task nur gegen die genannten Testdateien; ein voller `pytest`-Lauf ist weiterhin erwartbar rot.

## Forward-Dependencies / Design-Notes (für den Plan-Review)

- **Regulärer Sync-Pull/Push hat KEINEN Pre-Version-Guard** (`src/main.py` `_run_pull_blocking` Z. 76–79 und der Push-Retry Z. 119–121 rufen `sync.merge` direkt). Mergt man einen **v2-Remote** in einen v3-Client, hat dessen Eintrag kein `slots` → er würde als Leer-Slot-Tag interpretiert und, falls er Merge-Gewinner wird, `apply_merge` verletzen (fehlender `slots`-Key → `ValueError`). **Entscheidung:** AP2 liefert nur den Guard im **Kompaktierungs**-Pfad (bestehende „old_version"-UI) + die `_remote_is_pre_v3`-Primitive. Das Verdrahten des Guards in den **regulären Pull** inkl. UI-Hinweis gehört zu **AP6** (dort lebt der Pull-Result-UI-Handler und der Hinweistext). Bis dahin ist „v3-Client gegen v2-Remote synchronisieren" nicht unterstützt — auf dem unausgelieferten Feature-Branch unkritisch, und die Spec-Empfehlung lautet ohnehin „alle Geräte updaten". *(Dieser Punkt ist bewusst zur Abnahme im Plan-Review markiert.)*
- **`_coerce` braucht KEINE Änderung** für `list`-Defaults: der bestehende generische Zweig `if isinstance(value, target_type) and not isinstance(value, bool): return value` akzeptiert eine Liste, und ein Nicht-Listen-Wert fällt durch alle Cast-Zweige auf `_COERCE_FAILED` (→ Default `[]`). Wird per Test fixiert, nicht per Code geändert.

---

## Dateistruktur

- `src/settings.py` — `categories`-Default + Whitelist-Eintrag. Verantwortung unverändert.
- `src/sync.py` — Schema-Bump, Slot-Gleichheit, Konflikt-Resolution auf Slots, `_remote_is_pre_v3`, Whitelist-Eintrag.
- `src/main.py` — Kompaktierungs-Guard `_remote_is_pre_v2` → `_remote_is_pre_v3` (eine Zeile + Kommentar).
- `tests/test_settings.py` — Kategorien-Tests.
- `tests/test_sync.py` — `_e`-Helfer auf Slots, interne Zugriffe + Resolutions/Kandidaten auf Slots, Schema-Assertion, `_remote_is_pre_v3`-Test, neue Slot-Tests.

Task 1 (Kategorien-Setting) berührt `settings.py` + die `sync.py`-Whitelist-Zeile (gekoppelt durch den Whitelist-Match-Test). Task 2 (Sync-Slot-Logik) berührt die Sync-Merge-/Konflikt-Logik + `main.py` + `test_sync.py`.

---

## Task 1: Kategorien-Setting (settings.py + sync.py-Whitelist)

**Files:**
- Modify: `src/settings.py` (`DEFAULTS`, `SYNCED_SETTING_KEYS`)
- Modify: `src/sync.py` (`SYNCED_SETTING_KEYS` — nur diese Tupel-Zeile)
- Test: `tests/test_settings.py` (neue Tests anhängen)

**Interfaces:**
- Produces: Setting-Key `categories` (`list[str]`, Default `[]`), in beiden `SYNCED_SETTING_KEYS`. Wird von AP6 (`settings_dialog`) via `set_synced("categories", [...])` gepflegt und von AP3/AP4 (Dialog-Pickliste / Report) via `settings.get("categories")` gelesen.

- [ ] **Step 1: Failing-Tests in `tests/test_settings.py` anhängen**

Hänge ans Ende von `tests/test_settings.py` an:

```python
# --- categories (Multi-Slot-Feature, AP2) ---


def test_categories_default_is_empty_list(tmp_settings):
    assert tmp_settings.get("categories") == []


def test_categories_is_synced_setting():
    assert "categories" in SYNCED_SETTING_KEYS


def test_categories_persists_list(tmp_path):
    path = str(tmp_path / "settings.json")
    s1 = Settings(path)
    s1.set("categories", ["Büro", "Homeoffice"])
    s2 = Settings(path)
    assert s2.get("categories") == ["Büro", "Homeoffice"]


def test_categories_non_list_falls_back_to_default(tmp_path, caplog):
    """Ein Nicht-Listen-Wert wird von _coerce abgelehnt → Default []."""
    path = _write_json(tmp_path, json.dumps({"categories": "Büro"}))
    with caplog.at_level("WARNING"):
        s = Settings(path)
    assert s.get("categories") == []
    assert any("categories" in rec.message for rec in caplog.records)


def test_categories_synced_doc_roundtrip(tmp_path):
    path = str(tmp_path / "settings.json")
    s = Settings(path)
    s.device_id_for_sync = "dev-1"
    s.set_synced("categories", ["Büro", "Kundentermin"])
    doc = s.get_synced_doc()
    assert doc["categories"]["value"] == ["Büro", "Kundentermin"]
    assert doc["categories"]["device_id"] == "dev-1"
```

- [ ] **Step 2: Tests laufen lassen — müssen FEHLSCHLAGEN**

Run: `python -m pytest tests/test_settings.py -q`
Expected: FAIL — `categories` ist noch kein Default/kein Synced-Key; `test_synced_whitelists_in_settings_and_sync_match` ist hier noch grün (beide Whitelists ohne `categories`), bricht aber, sobald nur eine Seite ergänzt würde — daher Step 3 ergänzt beide.

- [ ] **Step 3: `src/settings.py` — `categories` ergänzen**

In `src/settings.py`, in `SYNCED_SETTING_KEYS` (aktuell):

```python
SYNCED_SETTING_KEYS = (
    "recipient", "name", "hourly_rate",
    "mail_subject", "mail_greeting", "mail_content", "mail_closing",
    "gcal_calendar_id",
)
```

ändere zu (Komma + neuer Eintrag in letzter Zeile):

```python
SYNCED_SETTING_KEYS = (
    "recipient", "name", "hourly_rate",
    "mail_subject", "mail_greeting", "mail_content", "mail_closing",
    "gcal_calendar_id", "categories",
)
```

Und in `DEFAULTS` einen Eintrag ergänzen (z.B. direkt nach `"last_calendar_sync_at": "",`):

```python
    "categories": [],
```

- [ ] **Step 4: `src/sync.py` — Whitelist-Duplikat angleichen**

In `src/sync.py`, in `SYNCED_SETTING_KEYS` (aktuell):

```python
SYNCED_SETTING_KEYS = (
    "recipient", "name", "hourly_rate",
    "mail_subject", "mail_greeting", "mail_content", "mail_closing",
    "gcal_calendar_id",
)
```

ändere zu:

```python
SYNCED_SETTING_KEYS = (
    "recipient", "name", "hourly_rate",
    "mail_subject", "mail_greeting", "mail_content", "mail_closing",
    "gcal_calendar_id", "categories",
)
```

- [ ] **Step 5: Tests laufen lassen — müssen BESTEHEN**

Run: `python -m pytest tests/test_settings.py -q`
Expected: PASS (inkl. `test_synced_whitelists_in_settings_and_sync_match`).

- [ ] **Step 6: Commit**

```bash
git add src/settings.py src/sync.py tests/test_settings.py
git commit -m "feat(settings): syncbare categories-Liste (#53)

Neuer Setting-Key categories (list[str], Default []), aufgenommen in
beide SYNCED_SETTING_KEYS (settings.py + sync.py). _coerce akzeptiert
Listen-Defaults bereits generisch; per Test fixiert. Teil von AP2.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 2: Sync v3 — Slot-Gleichheit, Konflikt-Resolution, Alt-Client-Guard

**Files:**
- Modify: `src/sync.py` (`SCHEMA_VERSION`, `_values_equal_entry` + Helfer, Resolution-Apply-Block in `merge`, `resolve_conflict`, `_remote_is_pre_v2` → `_remote_is_pre_v3`)
- Modify: `src/main.py` (Kompaktierungs-Guard-Aufruf Z. 168 + Kommentar)
- Test: `tests/test_sync.py` (umfangreiche Anpassung, siehe Steps)

**Interfaces:**
- Consumes: Storage-Slot-API aus AP1 (`storage.save(date, slots)`, `storage.get(date) -> {"slots": [...]}`, `storage.delete(date)`); Slot-Schema `{start, end, pause, kategorie}`.
- Produces:
  - `sync.SCHEMA_VERSION == 3`.
  - `_values_equal_entry(a, b)` vergleicht Slot-Listen reihenfolge-normalisiert + `deleted`.
  - `resolve_conflict(...)` (entry-Zweig): `chosen_value = {"slots": [...], "deleted"?: bool}` → schreibt via `storage.save(key, chosen_value["slots"])` bzw. `storage.delete(key)`.
  - Resolution-Apply in `merge()` schreibt `{"slots": resolution.get("slots", []), modified_at, device_id, deleted}`.
  - `_remote_is_pre_v3(remote_doc) -> bool`.

### Teil A — `src/sync.py` anpassen

- [ ] **Step 1: `SCHEMA_VERSION` bumpen**

In `src/sync.py`: `SCHEMA_VERSION = 2` → `SCHEMA_VERSION = 3`.

- [ ] **Step 2: Slot-Gleichheit einführen**

Ersetze in `src/sync.py` die Funktion `_values_equal_entry` (aktuell):

```python
def _values_equal_entry(a, b):
    return (a.get("start") == b.get("start")
            and a.get("end") == b.get("end")
            and a.get("pause") == b.get("pause")
            and bool(a.get("deleted")) == bool(b.get("deleted")))
```

durch:

```python
def _slots_signature(entry):
    """Reihenfolge-normalisierte Signatur der Slot-Liste eines Eintrags,
    für den Gleichheitsvergleich im Merge. Sortiert nach den Slot-Feldern,
    damit eine reine Umordnung der Slots NICHT als Änderung zählt."""
    return sorted(
        (s.get("start"), s.get("end"), s.get("pause", 0), s.get("kategorie", ""))
        for s in (entry.get("slots") or [])
    )


def _values_equal_entry(a, b):
    return (_slots_signature(a) == _slots_signature(b)
            and bool(a.get("deleted")) == bool(b.get("deleted")))
```

- [ ] **Step 3: Resolution-Apply-Block auf Slots umstellen**

In `src/sync.py`, in `merge()`, im Block „Resolutions anwenden", ersetze den `if c["kind"] == "entry":`-Zweig (aktuell):

```python
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
```

durch:

```python
        if c["kind"] == "entry":
            current = merged["entries"].get(c["key"])
            if current is None or current["modified_at"] < resolved_at:
                merged["entries"][c["key"]] = {
                    "slots": resolution.get("slots", []),
                    "modified_at": resolved_at,
                    "device_id": resolved_by,
                    "deleted": bool(resolution.get("deleted", False)),
                }
```

- [ ] **Step 4: `resolve_conflict` entry-Zweig auf Slots umstellen**

In `src/sync.py`, in `resolve_conflict`, ersetze den `if target["kind"] == "entry":`-Zweig (aktuell):

```python
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
```

durch:

```python
    if target["kind"] == "entry":
        if chosen_value.get("deleted"):
            storage.delete(target["key"])
        else:
            storage.save(target["key"], chosen_value.get("slots", []))
```

Aktualisiere außerdem den Docstring-Satz von `resolve_conflict` (aktuell „Für entries: {start, end, pause} (und optional deleted).") auf:
„Für entries: {slots: [...]} (und optional deleted)."

- [ ] **Step 5: `_remote_is_pre_v2` → `_remote_is_pre_v3` ersetzen**

In `src/sync.py`, ersetze die Funktion `_remote_is_pre_v2` (aktuell):

```python
def _remote_is_pre_v2(remote_doc):
    """True, wenn das Remote-Doc von einem v1-Gerät stammt (Schema < 2 oder
    fehlendes/leeres meta ohne gc_watermark-Key) — dann ist gerade ein älteres
    Gerät aktiv und die Kompaktierung muss abbrechen."""
    if (remote_doc.get("schema_version") or 1) < 2:
        return True
    meta = remote_doc.get("meta")
    return not (isinstance(meta, dict) and "gc_watermark" in meta)
```

durch:

```python
def _remote_is_pre_v3(remote_doc):
    """True, wenn das Remote-Doc von einem Gerät stammt, das das Multi-Slot-
    Schema (v3) noch nicht versteht (schema_version < 3). Dann ist ein
    älteres Gerät aktiv: Kompaktierung muss abbrechen, und ein v2-Remote darf
    nicht in einen v3-Client gemergt werden (er hätte keine `slots`)."""
    return (remote_doc.get("schema_version") or 1) < 3
```

### Teil B — `src/main.py` Kompaktierungs-Guard

- [ ] **Step 6: Guard-Aufruf in `src/main.py` umstellen**

In `src/main.py`, in `_run_compaction_blocking`, ersetze (Z. ~167–168):

```python
                # v1-Guard auf dem FRISCH gepullten Doc (nie gecacht):
                if sync._remote_is_pre_v2(remote_doc):
```

durch:

```python
                # Alt-Client-Guard auf dem FRISCH gepullten Doc (nie gecacht):
                if sync._remote_is_pre_v3(remote_doc):
```

Passe außerdem den Docstring-Satz von `_run_compaction_blocking` an: ersetze
„ein älteres Gerät ist aktiv (Remote ist pre-v2)" durch
„ein älteres Gerät ist aktiv (Remote ist pre-v3)".

> Diese `main.py`-Änderung ist Wiring ohne sinnvollen Unit-Test (Drive-I/O + Thread). Die nicht-triviale Entscheidung steckt in `_remote_is_pre_v3` und ist unit-getestet (Teil C). Manuelle Verifikation: `python -c "from src import main, sync"` muss fehlerfrei importieren (Step 12).

### Teil C — `tests/test_sync.py` anpassen

- [ ] **Step 7: `_e`-Helfer auf Slot-Shape umstellen**

In `tests/test_sync.py`, ersetze den Helfer `_e` (Z. 11–15):

```python
def _e(start, end, pause, modified_at, device_id="d", deleted=False):
    return {
        "start": start, "end": end, "pause": pause,
        "modified_at": modified_at, "device_id": device_id, "deleted": deleted,
    }
```

durch:

```python
def _e(start, end, pause, modified_at, device_id="d", deleted=False):
    slots = [] if deleted else [{"start": start, "end": end, "pause": pause, "kategorie": ""}]
    return {
        "slots": slots,
        "modified_at": modified_at, "device_id": device_id, "deleted": deleted,
    }


def _slot(start, end, pause=0, kategorie=""):
    return {"start": start, "end": end, "pause": pause, "kategorie": kategorie}
```

- [ ] **Step 8: Interne Eintrags-Zugriffe in `tests/test_sync.py` auf Slots umstellen**

Führe diese exakten Ersetzungen durch (jede Zeile genau einmal vorhanden):

- Z. 38: `    assert merged["start"] == "08:00"`
  → `    assert merged["slots"][0]["start"] == "08:00"`
- Z. 118: `    assert merged["entries"]["2026-05-14"]["start"] == "09:00"`
  → `    assert merged["entries"]["2026-05-14"]["slots"][0]["start"] == "09:00"`
- Z. 137: `    assert merged["entries"]["D"]["start"] == "09:00"`
  → `    assert merged["entries"]["D"]["slots"][0]["start"] == "09:00"`
- Z. 559: `    assert merged["entries"]["D"]["start"] == "08:00"`
  → `    assert merged["entries"]["D"]["slots"][0]["start"] == "08:00"`
- Z. 571: `    assert merged["entries"]["D"]["start"] == "08:00"`
  → `    assert merged["entries"]["D"]["slots"][0]["start"] == "08:00"`

- [ ] **Step 9: `storage.save`/`storage.get`-Aufrufe in `tests/test_sync.py` auf Slot-API umstellen**

- `test_build_local_doc_includes_storage_settings_conflicts` (Z. ~277):
  `    storage.save("2026-05-14", "08:00", "16:00", 30)`
  → `    storage.save("2026-05-14", [_slot("08:00", "16:00", 30)])`
- gleicher Test, Z. ~288: `    assert doc["schema_version"] == 2` → `    assert doc["schema_version"] == 3`
- `test_round_trip_no_loss` (Z. ~293):
  `    storage.save("2026-05-14", "08:00", "16:00", 30)`
  → `    storage.save("2026-05-14", [_slot("08:00", "16:00", 30)])`
- gleicher Test, Z. ~303:
  `    assert storage.get("2026-05-14") == {"start": "08:00", "end": "16:00", "pause": 30}`
  → `    assert storage.get("2026-05-14") == {"slots": [_slot("08:00", "16:00", 30)]}`
- `test_compact_local_strips_stores_and_sets_watermark` (Z. ~596–597):
  ```python
      storage.save("LIVE", "08:00", "16:00", 30)
      storage.save("DEL", "08:00", "16:00", 30)
  ```
  →
  ```python
      storage.save("LIVE", [_slot("08:00", "16:00", 30)])
      storage.save("DEL", [_slot("08:00", "16:00", 30)])
  ```

- [ ] **Step 10: Resolution-/Kandidaten-Dicts in `tests/test_sync.py` auf Slot-Shape umstellen**

- `test_merge_applies_resolved_conflict_to_entry`:
  - Z. ~243: `resolution={"start": "10:00", "end": "18:00", "pause": 30}`
    → `resolution={"slots": [_slot("10:00", "18:00", 30)]}`
  - Z. ~253–254:
    ```python
        assert e["start"] == "10:00"
        assert e["end"] == "18:00"
    ```
    →
    ```python
        assert e["slots"][0]["start"] == "10:00"
        assert e["slots"][0]["end"] == "18:00"
    ```
- `test_resolve_entry_conflict_updates_storage_and_marks_resolved`:
  - Kandidaten (Z. ~315–320) ersetzen:
    ```python
        "candidates": [
            {"start": "08:00", "end": "16:00", "pause": 30,
             "modified_at": "2026-05-14T09:00:00Z", "device_id": "A", "deleted": False},
            {"start": "09:00", "end": "17:00", "pause": 30,
             "modified_at": "2026-05-14T10:00:00Z", "device_id": "B", "deleted": False},
        ],
    ```
    →
    ```python
        "candidates": [
            {"slots": [_slot("08:00", "16:00", 30)],
             "modified_at": "2026-05-14T09:00:00Z", "device_id": "A", "deleted": False},
            {"slots": [_slot("09:00", "17:00", 30)],
             "modified_at": "2026-05-14T10:00:00Z", "device_id": "B", "deleted": False},
        ],
    ```
  - chosen (Z. ~326): `    chosen = {"start": "09:00", "end": "17:00", "pause": 30}`
    → `    chosen = {"slots": [_slot("09:00", "17:00", 30)]}`
  - Z. ~330: `    assert storage.get("2026-05-14") == {"start": "09:00", "end": "17:00", "pause": 30}`
    → `    assert storage.get("2026-05-14") == {"slots": [_slot("09:00", "17:00", 30)]}`
- Übrige entry-Konflikt-Resolutions, die noch `{"start": ...}` nutzen, auf Slot-Shape angleichen (nicht asserted, aber konsistent halten):
  - `test_merge_conflicts_resolved_wins_over_unresolved` (Z. ~198):
    `resolution={"start": "08:00", "end": "16:00", "pause": 30}`
    → `resolution={"slots": [_slot("08:00", "16:00", 30)]}`
  - `test_merge_conflicts_lww_on_resolved_at_when_both_resolved` (Z. ~210 und ~213):
    `resolution={"start": "08:00"}` → `resolution={"slots": [_slot("08:00", "16:00", 30)]}`
    und `resolution={"start": "09:00"}` → `resolution={"slots": [_slot("09:00", "17:00", 30)]}`
  - `test_compact_local_strips_stores_and_sets_watermark`, Konflikt `c-1` (Z. ~603):
    `"resolution": {"start": "08:00"}` → `"resolution": {"slots": [_slot("08:00", "16:00", 30)]}`

- [ ] **Step 11: `_remote_is_pre_v2`-Import + -Test auf v3 umstellen, Slot-Tests ergänzen**

- Import (Z. ~591): `from src.sync import compact_local, _remote_is_pre_v2`
  → `from src.sync import compact_local, _remote_is_pre_v3`
- Ersetze den Test `test_remote_is_pre_v2` (Z. ~623–627) durch:

```python
def test_remote_is_pre_v3():
    assert _remote_is_pre_v3({"schema_version": 1, "entries": {}}) is True
    assert _remote_is_pre_v3({"schema_version": 2, "entries": {}}) is True
    assert _remote_is_pre_v3({"schema_version": 3, "entries": {}}) is False
    assert _remote_is_pre_v3({}) is True  # fehlende schema_version → pre-v3
```

- Hänge ans Ende von `tests/test_sync.py` zwei neue Tests an:

```python
def test_merge_slot_reorder_is_not_a_conflict():
    """Gleiche Slots in unterschiedlicher Reihenfolge zählen als gleich →
    kein Konflikt, auch wenn beide Seiten seit last_pull geändert haben."""
    a = {"slots": [_slot("08:00", "12:00", 0, "Büro"), _slot("13:00", "17:00", 0, "HO")],
         "modified_at": "2026-05-14T10:00:00Z", "device_id": "A", "deleted": False}
    b = {"slots": [_slot("13:00", "17:00", 0, "HO"), _slot("08:00", "12:00", 0, "Büro")],
         "modified_at": "2026-05-14T11:00:00Z", "device_id": "B", "deleted": False}
    local = _doc(entries={"D": a})
    remote = _doc(entries={"D": b})
    merged = merge(local, remote, "2026-05-13T00:00:00Z")
    assert merged["conflicts"] == []


def test_merge_different_slots_conflict_candidates_carry_slots():
    """Unterschiedliche Slot-Listen, beide geändert → Konflikt; die Kandidaten
    tragen die jeweilige Slot-Liste."""
    a = {"slots": [_slot("08:00", "16:00", 30, "Büro")],
         "modified_at": "2026-05-14T09:00:00Z", "device_id": "A", "deleted": False}
    b = {"slots": [_slot("09:00", "17:00", 30, "HO")],
         "modified_at": "2026-05-14T10:00:00Z", "device_id": "B", "deleted": False}
    merged = merge(_doc(entries={"D": a}), _doc(entries={"D": b}), "2026-05-13T00:00:00Z")
    assert len(merged["conflicts"]) == 1
    cand_by_dev = {c["device_id"]: c for c in merged["conflicts"][0]["candidates"]}
    assert cand_by_dev["A"]["slots"] == [_slot("08:00", "16:00", 30, "Büro")]
    assert cand_by_dev["B"]["slots"] == [_slot("09:00", "17:00", 30, "HO")]
```

### Teil D — Verifikation

- [ ] **Step 12: Import-Smoke-Test für die `main.py`-Wiring-Änderung**

Run: `python -c "from src import main, sync; print(sync._remote_is_pre_v3({'schema_version': 2}))"`
Expected: gibt `True` aus, kein ImportError/AttributeError.

- [ ] **Step 13: Sync-Tests laufen lassen — müssen BESTEHEN**

Run: `python -m pytest tests/test_sync.py -q`
Expected: PASS (alle Tests grün).

- [ ] **Step 14: AP1+AP2-Regressionscheck (kein Rückschritt)**

Run: `python -m pytest tests/test_storage.py tests/test_storage_migration.py tests/test_reservations.py tests/test_reservations_migration.py tests/test_settings.py tests/test_sync.py -q`
Expected: PASS.

> **Hinweis:** Ein voller `pytest`-Lauf bleibt erwartbar rot (report/share/ui/gcal nutzen noch die alte API). Das ist der harte Schnitt; AP2 verifiziert nur die obigen Dateien.

- [ ] **Step 15: Commit**

```bash
git add src/sync.py src/main.py tests/test_sync.py
git commit -m "feat(sync): Schema v3 — Slot-Listen-Merge + Alt-Client-Guard (#53)

_values_equal_entry vergleicht reihenfolge-normalisierte Slot-Listen;
Konflikt-Resolution (resolve_conflict + merge-Apply) schreibt Slot-Listen.
SCHEMA_VERSION 2->3. _remote_is_pre_v2 -> _remote_is_pre_v3 (schema<3),
im Kompaktierungs-Guard verdrahtet. Day-level-LWW unverändert. Teil von AP2.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Self-Review

**1. Spec-Coverage (AP2-Scope laut Spec-Abschnitt „Sync (sync.py) — SCHEMA_VERSION 2 → 3"):**
- `SCHEMA_VERSION = 3` → Task 2, Step 1 ✓
- `_values_equal_entry` vergleicht Slot-Liste reihenfolge-normalisiert + deleted → Task 2, Step 2 (+ Test Step 11 reorder) ✓
- Konflikt-Kandidaten tragen Slot-Liste; resolve_conflict + Resolution-Apply schreiben Slot-Liste → Task 2, Steps 3–4 (+ Test Step 11 candidates) ✓
- `_remote_is_pre_v3` + Kompaktierungs-Guard → Task 2, Steps 5–6 (+ Test Step 11) ✓
- Day-level-LWW/Watermark/Tombstone unverändert → keine Änderung an `_merge_one`/Watermark-Logik ✓
- Kategorien-Setting in beide `SYNCED_SETTING_KEYS` + Default → Task 1 ✓
- `_coerce` für Listen → bewusst KEINE Code-Änderung (bereits abgedeckt), per Test fixiert → Task 1, Step 1 (`test_categories_non_list_falls_back_to_default`) ✓
- Bewusst NICHT in AP2 (dokumentiert): regulärer-Pull-Pre-v3-Guard + UI-Hinweis → AP6; Consumer-Anpassungen (report/share/ui/gcal) → ihre Pakete.

**2. Placeholder-Scan:** Keine TBD/TODO; alle Code- und Test-Edits zeigen exakten Inhalt (old→new). Zeilennummern sind als Orientierung mit „~" markiert, der Match-Text ist eindeutig. ✓

**3. Typ-Konsistenz:**
- `chosen_value`/`resolution` für entry = `{"slots": [...], "deleted"?: bool}` — konsistent zwischen `resolve_conflict`, Resolution-Apply und den test_sync-Edits. ✓
- `storage.save(date, slots)` / `storage.get -> {"slots": [...]}` — konsistent zu AP1-Interfaces und den test_sync-Edits. ✓
- `_remote_is_pre_v3` Name identisch in sync.py, main.py-Aufruf, test-Import und Test. ✓
- `categories` Key-Name identisch in DEFAULTS, beiden Whitelists und allen Tests. ✓
- `_slot(...)`-Helfer in test_sync.py liefert `{start,end,pause,kategorie}` wie das AP1-Slot-Schema. ✓
