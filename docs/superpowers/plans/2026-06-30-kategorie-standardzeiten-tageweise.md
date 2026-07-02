# Kategorie-Standardzeiten tageweise — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `category_times` pro Kategorie wahlweise „allgemein" (ein Satz) oder „tageweise" (Start/Ende pro Wochentag), mit Per-Feld-Fallback auf die globalen Wochentags-Defaults.

**Architecture:** Reine Logik in `category_defaults.py` (`resolve_slot_defaults`) und `dialogs/category_dialog.py` (`collect_categories`, neu: `row_defaults_from_entry`, `categories_losing_per_day`) — Tk-frei und voll getestet. Der Tk-Dialog ist nur Wiring (Modus-Toggle, ausklappbares Per-Tag-Grid, Downgrade-Confirm). Ein Sync-Schema-Bump v3→v4 schützt die neue Struktur vor Plättung durch Altclients.

**Tech Stack:** Python 3 (stdlib + `tkinter`), `pytest`. Keine neuen Dependencies.

**Spec:** `docs/superpowers/specs/2026-06-30-kategorie-standardzeiten-tageweise-design.md`

## Global Constraints

- **`mode` fehlt ⇒ „allgemein".** Nur der literale String `"per_day"` aktiviert den tageweise-Pfad; jeder andere/fehlende Wert ist allgemein.
- **Pause ist EIN Wert pro Kategorie** (top-level `pause`), nie pro Tag.
- **Per-Feld/-Tag-Fallback:** leeres/fehlendes Feld (Start/Ende/Pause/Tag) → globaler Wochentags-Standard für genau dieses Feld. `pause=0` ist gültig und bleibt erhalten.
- `category_times` ist **bereits** in `SYNCED_SETTING_KEYS` (`settings.py:11`) — **nicht anfassen**. Die Liste lebt nur in `settings.py`; `sync.py` importiert sie (kein Duplikat).
- **Nur `sync.SCHEMA_VERSION`** wird gebumpt (3→4). `share.SCHEMA_VERSION` ist ein separates Schema und bleibt 3.
- `days`-Keys = `WEEKDAY_KEYS` aus `settings.py` (`("mon","tue","wed","thu","fri","sat","sun")`, Index = `datetime.weekday()`).
- `STANDARD = "(Standard)"` (Sentinel in `category_dialog.py`) markiert „kein eigener Wert"; `_clean_field` macht daraus `None`.
- CI (`test.yml`) installiert nur `pytest`, `holidays==0.99`, google-libs — kein `requirements.txt`. Pure Tests laufen ohne Tk-Display; Tk-Importe sind in der Testumgebung verfügbar (Tests importieren `src.ui`).
- Commits: englischer Typ (`feat:`/`refactor:`/`test:`), Body deutsch ok; jeder Commit endet mit `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`.

---

## File Structure

- `src/category_defaults.py` — **modify**: `resolve_slot_defaults` bekommt `weekday_key` + per_day-Zweig.
- `src/dialogs/entry_dialog.py` — **modify**: beide `resolve_slot_defaults`-Aufrufe reichen `weekday_key` durch.
- `src/dialogs/category_dialog.py` — **modify**: `collect_categories` (mode/days) + **neu** `row_defaults_from_entry`, `categories_losing_per_day` + UI-Wiring.
- `src/sync.py` — **modify**: `SCHEMA_VERSION = 4`; `migrate_doc_to_v3` → `migrate_doc_to_current`.
- `src/main.py` — **modify**: 3 Aufrufstellen auf den neuen Funktionsnamen.
- Tests: `tests/test_category_defaults.py`, `tests/test_category_dialog.py`, `tests/test_sync.py`, `tests/test_storage_migration.py`.

Task-Abhängigkeiten: Task 1, 2, 5 sind unabhängig. Task 3 nutzt `collect_categories` (Task 2). Task 4 ist unabhängig. Task 6 (UI) nutzt Task 2–4.

---

## Task 1: `resolve_slot_defaults` um Wochentag + per_day-Zweig erweitern

**Files:**
- Modify: `src/category_defaults.py`
- Modify: `src/dialogs/entry_dialog.py` (zwei Aufrufstellen — sonst bricht der Aufruf)
- Test: `tests/test_category_defaults.py`

**Interfaces:**
- Produces: `resolve_slot_defaults(category_times, kategorie, weekday_key, g_start, g_end, g_pause) -> (start, end, pause)`. `weekday_key` ist ein `WEEKDAY_KEYS`-String; im per_day-Modus wählt er `days[weekday_key]`, sonst irrelevant.

- [ ] **Step 1: Bestehende Tests auf die neue Signatur ziehen + per_day-Fälle ergänzen**

In `tests/test_category_defaults.py` die 9 Bestandstests um den `weekday_key`-Parameter erweitern (Wert egal, da sie alle den general-Pfad treffen — `"mon"` einsetzen). Beispiel der Umstellung:

```python
G = ("08:00", "16:00", 30)  # globale (start, end, pause)


def test_unknown_category_falls_back_to_global():
    assert resolve_slot_defaults({}, "Office", "mon", *G) == ("08:00", "16:00", 30)


def test_full_category_overrides_all_fields():
    times = {"Office": {"start": "09:00", "end": "17:00", "pause": 45}}
    assert resolve_slot_defaults(times, "Office", "mon", *G) == ("09:00", "17:00", 45)
```

(Analog für die übrigen 7 Bestandstests: `"mon"` als drittes Argument einfügen.)

Neue per_day-Tests anhängen:

```python
PD = {
    "Homeoffice": {
        "mode": "per_day",
        "pause": 0,
        "days": {
            "mon": {"start": "09:00", "end": "18:00"},
            "fri": {"start": "09:00", "end": "14:00"},
        },
    }
}


def test_per_day_picks_weekday_set():
    assert resolve_slot_defaults(PD, "Homeoffice", "mon", *G) == ("09:00", "18:00", 0)
    assert resolve_slot_defaults(PD, "Homeoffice", "fri", *G) == ("09:00", "14:00", 0)


def test_per_day_missing_day_falls_back_to_global():
    # sat ist nicht in days → globaler Wochentags-Standard, Pause aus top-level
    assert resolve_slot_defaults(PD, "Homeoffice", "sat", *G) == ("08:00", "16:00", 0)


def test_per_day_missing_field_in_day_falls_back():
    times = {"X": {"mode": "per_day", "days": {"mon": {"start": "07:00"}}}}
    # end fehlt → global; pause fehlt top-level → global
    assert resolve_slot_defaults(times, "X", "mon", *G) == ("07:00", "16:00", 30)


def test_per_day_corrupt_days_falls_back():
    assert resolve_slot_defaults({"X": {"mode": "per_day", "days": "kaputt"}},
                                 "X", "mon", *G) == ("08:00", "16:00", 30)
    assert resolve_slot_defaults({"X": {"mode": "per_day"}},
                                 "X", "mon", *G) == ("08:00", "16:00", 30)


def test_mode_other_than_per_day_uses_general_path():
    times = {"X": {"mode": "general", "start": "10:00"}}
    assert resolve_slot_defaults(times, "X", "mon", *G) == ("10:00", "16:00", 30)
```

- [ ] **Step 2: Tests laufen lassen — müssen fehlschlagen**

Run: `pytest tests/test_category_defaults.py -v`
Expected: FAIL — die Bestandstests scheitern an der alten Signatur (zu viele Argumente), die neuen an fehlender per_day-Logik.

- [ ] **Step 3: `resolve_slot_defaults` implementieren**

In `src/category_defaults.py` die Funktion ersetzen:

```python
def resolve_slot_defaults(category_times, kategorie, weekday_key,
                          g_start, g_end, g_pause):
    """(start, end, pause) für einen Slot der Kategorie am gegebenen Wochentag.

    - mode == "per_day": Start/Ende aus days[weekday_key] (Per-Feld-Fallback auf
      g_start/g_end), Pause aus top-level "pause".
    - sonst (mode fehlt / != "per_day"): heutiger Ein-Satz-Pfad.
    Per-Feld-Fallback auf die globalen Werte überall, wo ein Feld leer/None/
    ungültig oder Kategorie/Tag unbekannt ist. pause=0 bleibt gültig.
    """
    entry = category_times.get(kategorie) if isinstance(category_times, dict) else None
    if not isinstance(entry, dict):
        return g_start, g_end, g_pause

    if entry.get("mode") == "per_day":
        days = entry.get("days")
        day = days.get(weekday_key) if isinstance(days, dict) else None
        if not isinstance(day, dict):
            day = {}
        start = day.get("start") or g_start
        end = day.get("end") or g_end
    else:
        start = entry.get("start") or g_start
        end = entry.get("end") or g_end

    pause = entry.get("pause")
    if pause is None or pause == "":
        pause = g_pause
    else:
        try:
            pause = int(pause)
        except (TypeError, ValueError):
            pause = g_pause

    return start, end, pause
```

- [ ] **Step 4: Tests laufen lassen — müssen bestehen**

Run: `pytest tests/test_category_defaults.py -v`
Expected: PASS (alle, inkl. der 9 angepassten + 5 neuen).

- [ ] **Step 5: Die zwei Aufrufstellen in `entry_dialog.py` anpassen**

`src/dialogs/entry_dialog.py` — im Ist-Slot (`on_cat_change`, derzeit ~`:123`):

```python
        def on_cat_change(*_a):
            t_start, t_end, t_pause = resolve_slot_defaults(
                category_times, kv.get().strip(), weekday_key,
                default_start, default_end, default_pause,
            )
```

Im Reservierungs-Slot (`on_cat_change`, derzeit ~`:233`):

```python
            def on_cat_change(*_a):
                # Reservierungen haben keine Pause → nur Start/Ende anwenden.
                t_start, t_end, _ = resolve_slot_defaults(
                    category_times, kv.get().strip(), weekday_key,
                    default_start, default_end, default_pause,
                )
```

(`weekday_key` ist im Funktions-Scope bereits definiert, `entry_dialog.py:48`.)

- [ ] **Step 6: Import-Smoke — entry_dialog lädt mit neuer Signatur**

Run: `python -c "import src.dialogs.entry_dialog"`
Expected: kein Fehler (keine Ausgabe).

- [ ] **Step 7: Commit**

```bash
git add src/category_defaults.py src/dialogs/entry_dialog.py tests/test_category_defaults.py
git commit -m "$(cat <<'EOF'
feat(category-times): resolve_slot_defaults mit Wochentag + per_day-Zweig

weekday_key wählt im per_day-Modus den Tagessatz; general-Pfad unverändert.
entry_dialog reicht weekday_key durch.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: `collect_categories` um Modus + Per-Tag-Grid erweitern

**Files:**
- Modify: `src/dialogs/category_dialog.py`
- Test: `tests/test_category_dialog.py`

**Interfaces:**
- Consumes: `_clean_field`, `WEEKDAY_KEYS`, `STANDARD` (bereits im Modul).
- Produces: `collect_categories(rows) -> (categories, category_times)`. Jede `row` ist `{"name", "mode", "start", "end", "pause", "days"}` mit `days = {tag: {"start","end"}}` (Roh-Strings/STANDARD). `mode` ist `"general"` oder `"per_day"`.

- [ ] **Step 1: Neue Tests für den per_day-Build schreiben**

In `tests/test_category_dialog.py` den `_row`-Helfer um `mode`/`days` erweitern und Tests anhängen. **Bestehende** `_row`-Aufrufe liefern `mode="general"` als Default — die Bestandstests bleiben dadurch gültig:

```python
def _row(name, start=STANDARD, end=STANDARD, pause=STANDARD,
         mode="general", days=None):
    return {"name": name, "start": start, "end": end, "pause": pause,
            "mode": mode, "days": days or {}}


def _pd_days(**kw):
    """kw wie mon=("09:00","18:00") → {"mon": {"start":..,"end":..}}."""
    return {k: {"start": v[0], "end": v[1]} for k, v in kw.items()}


def test_per_day_row_builds_nested_entry():
    rows = [_row("Homeoffice", mode="per_day", pause="0",
                 days=_pd_days(mon=("09:00", "18:00"), fri=("09:00", "14:00")))]
    cats, times = collect_categories(rows)
    assert cats == ["Homeoffice"]
    assert times == {"Homeoffice": {
        "mode": "per_day", "pause": 0,
        "days": {"mon": {"start": "09:00", "end": "18:00"},
                 "fri": {"start": "09:00", "end": "14:00"}},
    }}


def test_per_day_empty_fields_drop_out():
    rows = [_row("X", mode="per_day",
                 days=_pd_days(mon=("09:00", STANDARD), tue=(STANDARD, STANDARD)))]
    _, times = collect_categories(rows)
    # tue komplett leer entfällt; mon behält nur start
    assert times == {"X": {"mode": "per_day", "days": {"mon": {"start": "09:00"}}}}


def test_per_day_without_any_data_is_dropped():
    rows = [_row("X", mode="per_day", pause=STANDARD,
                 days=_pd_days(mon=(STANDARD, STANDARD)))]
    cats, times = collect_categories(rows)
    assert cats == ["X"]
    assert times == {}


def test_per_day_with_only_pause_keeps_entry():
    rows = [_row("X", mode="per_day", pause="45", days={})]
    _, times = collect_categories(rows)
    assert times == {"X": {"mode": "per_day", "days": {}, "pause": 45}}
```

- [ ] **Step 2: Tests laufen lassen — müssen fehlschlagen**

Run: `pytest tests/test_category_dialog.py -v`
Expected: FAIL — `collect_categories` kennt `mode`/`days` noch nicht (per_day-Tests scheitern; general-Bestandstests bleiben grün).

- [ ] **Step 3: `collect_categories` implementieren**

In `src/dialogs/category_dialog.py` die Funktion ersetzen:

```python
def collect_categories(rows):
    """Baut (categories, category_times) aus den Roh-Zeilen.

    rows: [{name, mode, start, end, pause, days}]. mode "per_day" → verschachtelter
    Eintrag {mode, pause?, days:{tag:{start?,end?}}}; sonst flacher {start?,end?,pause?}.
    STANDARD/leere Felder entfallen → Per-Feld-Fallback. Leerer Eintrag entfällt ganz.
    Namen getrimmt, ohne Leere, dedupliziert (erstes Vorkommen gewinnt).
    """
    categories = []
    category_times = {}
    for row in rows:
        name = (row.get("name") or "").strip()
        if not name or name in categories:
            continue
        categories.append(name)
        pause = _clean_field(row.get("pause"))

        if row.get("mode") == "per_day":
            raw_days = row.get("days") or {}
            days = {}
            for key in WEEKDAY_KEYS:
                d = raw_days.get(key) or {}
                start = _clean_field(d.get("start"))
                end = _clean_field(d.get("end"))
                day_entry = {}
                if start is not None:
                    day_entry["start"] = start
                if end is not None:
                    day_entry["end"] = end
                if day_entry:
                    days[key] = day_entry
            if not days and pause is None:
                continue  # leerer per_day-Eintrag → komplett global
            entry = {"mode": "per_day", "days": days}
            if pause is not None:
                entry["pause"] = int(pause)
            category_times[name] = entry
        else:
            entry = {}
            start = _clean_field(row.get("start"))
            end = _clean_field(row.get("end"))
            if start is not None:
                entry["start"] = start
            if end is not None:
                entry["end"] = end
            if pause is not None:
                entry["pause"] = int(pause)
            if entry:
                category_times[name] = entry
    return categories, category_times
```

- [ ] **Step 4: Tests laufen lassen — müssen bestehen**

Run: `pytest tests/test_category_dialog.py -v`
Expected: PASS (alle Bestands- + neue per_day-Tests).

- [ ] **Step 5: Commit**

```bash
git add src/dialogs/category_dialog.py tests/test_category_dialog.py
git commit -m "$(cat <<'EOF'
feat(category-times): collect_categories baut per_day-Einträge

mode-Zeilen erzeugen verschachtelte {mode, pause?, days}-Struktur; leere
per_day-Zeilen entfallen. general-Pfad unverändert.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: `row_defaults_from_entry` (Hydration) + Round-Trip-Beweis

**Files:**
- Modify: `src/dialogs/category_dialog.py`
- Test: `tests/test_category_dialog.py`

**Interfaces:**
- Consumes: `collect_categories` (Task 2), `WEEKDAY_KEYS`, `STANDARD`.
- Produces: `row_defaults_from_entry(entry) -> {"mode","start","end","pause","days"}` (Roh-Strings/STANDARD, alle 7 Tage in `days`). Umkehrung von `collect_categories` pro Zeile.

- [ ] **Step 1: Hydration- und Round-Trip-Tests schreiben**

In `tests/test_category_dialog.py` anhängen (Import um `row_defaults_from_entry` ergänzen):

```python
from src.dialogs.category_dialog import (
    STANDARD, collect_categories, row_defaults_from_entry,
)


def test_hydrate_general_entry():
    r = row_defaults_from_entry({"start": "09:30", "end": "17:00", "pause": 30})
    assert r["mode"] == "general"
    assert (r["start"], r["end"], r["pause"]) == ("09:30", "17:00", "30")


def test_hydrate_per_day_entry_fills_all_days():
    e = {"mode": "per_day", "pause": 0,
         "days": {"mon": {"start": "09:00", "end": "18:00"}}}
    r = row_defaults_from_entry(e)
    assert r["mode"] == "per_day"
    assert r["pause"] == "0"
    assert r["days"]["mon"] == {"start": "09:00", "end": "18:00"}
    # nicht gesetzte Tage → STANDARD in beiden Feldern
    assert r["days"]["sun"] == {"start": STANDARD, "end": STANDARD}


def test_hydrate_corrupt_entry_is_general_standard():
    r = row_defaults_from_entry("kaputt")
    assert r["mode"] == "general"
    assert (r["start"], r["end"], r["pause"]) == (STANDARD, STANDARD, STANDARD)


def test_roundtrip_preserves_per_day_entry():
    e = {"mode": "per_day", "pause": 0,
         "days": {"mon": {"start": "09:00", "end": "18:00"},
                  "fri": {"start": "09:00", "end": "14:00"}}}
    cats, times = collect_categories([{"name": "Homeoffice", **row_defaults_from_entry(e)}])
    assert cats == ["Homeoffice"]
    assert times == {"Homeoffice": e}


def test_roundtrip_preserves_general_entry():
    e = {"start": "09:30", "end": "17:00", "pause": 30}
    _, times = collect_categories([{"name": "Office", **row_defaults_from_entry(e)}])
    assert times == {"Office": e}
```

- [ ] **Step 2: Tests laufen lassen — müssen fehlschlagen**

Run: `pytest tests/test_category_dialog.py -k "hydrate or roundtrip" -v`
Expected: FAIL — `row_defaults_from_entry` existiert nicht (ImportError).

- [ ] **Step 3: `row_defaults_from_entry` implementieren**

In `src/dialogs/category_dialog.py` (nach `collect_categories`) einfügen:

```python
def row_defaults_from_entry(entry):
    """category_times[name]-Eintrag → Vorbelegungs-Strings einer Dialog-Zeile.

    {mode, start, end, pause, days} mit Roh-Strings/STANDARD; days enthält ALLE 7
    Tage (ungesetzt → STANDARD). Umkehrung von collect_categories pro Zeile.
    Defensiv: Nicht-Dict/korrupt → allgemein, alles STANDARD.
    """
    if not isinstance(entry, dict):
        return {"mode": "general", "start": STANDARD, "end": STANDARD,
                "pause": STANDARD, "days": {}}

    pause = entry.get("pause")
    pause_str = str(pause) if pause not in (None, "") else STANDARD

    if entry.get("mode") == "per_day":
        raw_days = entry.get("days") if isinstance(entry.get("days"), dict) else {}
        days = {}
        for key in WEEKDAY_KEYS:
            d = raw_days.get(key) if isinstance(raw_days.get(key), dict) else {}
            days[key] = {"start": d.get("start") or STANDARD,
                         "end": d.get("end") or STANDARD}
        return {"mode": "per_day", "start": STANDARD, "end": STANDARD,
                "pause": pause_str, "days": days}

    return {"mode": "general",
            "start": entry.get("start") or STANDARD,
            "end": entry.get("end") or STANDARD,
            "pause": pause_str, "days": {}}
```

- [ ] **Step 4: Tests laufen lassen — müssen bestehen**

Run: `pytest tests/test_category_dialog.py -v`
Expected: PASS (alle, inkl. Round-Trip).

- [ ] **Step 5: Commit**

```bash
git add src/dialogs/category_dialog.py tests/test_category_dialog.py
git commit -m "$(cat <<'EOF'
feat(category-times): row_defaults_from_entry + Round-Trip-Test

Pure Hydration als Umkehrung von collect_categories; Round-Trip beweist, dass
Öffnen+Speichern ohne Änderung einen per_day-Eintrag nicht plättet.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: `categories_losing_per_day` (Basis für den Downgrade-Confirm)

**Files:**
- Modify: `src/dialogs/category_dialog.py`
- Test: `tests/test_category_dialog.py`

**Interfaces:**
- Consumes: `_clean_field`, `WEEKDAY_KEYS`.
- Produces: `categories_losing_per_day(rows) -> [name, ...]` — Namen der `general`-Zeilen, die noch gesetzte (versteckte) `days`-Felder tragen.

- [ ] **Step 1: Tests schreiben**

In `tests/test_category_dialog.py` anhängen (Import ergänzen):

```python
from src.dialogs.category_dialog import categories_losing_per_day


def test_losing_general_row_with_hidden_days():
    rows = [_row("X", mode="general",
                 days=_pd_days(mon=("09:00", "18:00")))]
    assert categories_losing_per_day(rows) == ["X"]


def test_not_losing_general_row_without_days():
    rows = [_row("X", mode="general")]
    assert categories_losing_per_day(rows) == []


def test_not_losing_active_per_day_row():
    rows = [_row("X", mode="per_day",
                 days=_pd_days(mon=("09:00", "18:00")))]
    assert categories_losing_per_day(rows) == []
```

- [ ] **Step 2: Tests laufen lassen — müssen fehlschlagen**

Run: `pytest tests/test_category_dialog.py -k losing -v`
Expected: FAIL — Funktion existiert nicht.

- [ ] **Step 3: Implementieren**

In `src/dialogs/category_dialog.py` einfügen:

```python
def categories_losing_per_day(rows):
    """Namen der Zeilen im Modus 'general', die noch >=1 gesetztes (Nicht-
    STANDARD-)Tagesfeld in 'days' tragen — d.h. versteckte per_day-Daten, die ein
    Save als allgemein verwerfen würde. Basis für den Downgrade-Confirm."""
    losing = []
    for row in rows:
        name = (row.get("name") or "").strip()
        if not name or row.get("mode") == "per_day":
            continue
        raw_days = row.get("days") or {}
        for key in WEEKDAY_KEYS:
            d = raw_days.get(key) or {}
            if _clean_field(d.get("start")) is not None or _clean_field(d.get("end")) is not None:
                losing.append(name)
                break
    return losing
```

- [ ] **Step 4: Tests laufen lassen — müssen bestehen**

Run: `pytest tests/test_category_dialog.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/dialogs/category_dialog.py tests/test_category_dialog.py
git commit -m "$(cat <<'EOF'
feat(category-times): categories_losing_per_day für Downgrade-Confirm

Pure Logik: welche general-Zeilen tragen noch versteckte Tagesdaten.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: Sync-Schema-Bump v3 → v4

**Files:**
- Modify: `src/sync.py` (`SCHEMA_VERSION`, `migrate_doc_to_v3` → `migrate_doc_to_current`)
- Modify: `src/main.py` (3 Aufrufstellen)
- Test: `tests/test_sync.py`, `tests/test_storage_migration.py`

**Interfaces:**
- Produces: `migrate_doc_to_current(remote_doc)` (vormals `migrate_doc_to_v3`), Verhalten unverändert; `SCHEMA_VERSION == 4`.

- [ ] **Step 1: Alle Verwender von `migrate_doc_to_v3` und `== 3` auflisten**

Run: `git grep -n "migrate_doc_to_v3\|schema_version\"\] == 3\|SCHEMA_VERSION == 3"`
Expected: Treffer in `src/sync.py` (def), `src/main.py` (3×), `tests/test_sync.py`, `tests/test_storage_migration.py`. Diese Liste ist die Arbeitsgrundlage für Step 3–4.

- [ ] **Step 2: Tests anpassen (rot)**

`tests/test_sync.py`:
- Import (`~:658`): `migrate_doc_to_v3` → `migrate_doc_to_current`.
- `test_migrate_doc_to_v3_wraps_flat_entries` → umbenennen `test_migrate_doc_to_current_wraps_flat_entries`; Aufruf `migrate_doc_to_current(doc)`; `assert out["schema_version"] == 4`.
- `test_migrate_doc_to_v3_is_idempotent_on_v3` → `test_migrate_doc_to_current_is_idempotent`; Aufruf umbenennen; `assert out["schema_version"] == 4`.
- `~:293` und `~:808`: `assert ...["schema_version"] == 3` → `== 4`.
- `test_remote_is_newer` (`~:662`): unverändert lassen — nutzt `SCHEMA_VERSION ± 1`/absolute `2`, bleibt korrekt bei 4.

`tests/test_storage_migration.py`:
- `~:135`: `assert SCHEMA_VERSION == 3` → `== 4`.
- `~:136`: `assert doc["schema_version"] == 3` → `== 4`.

Run: `pytest tests/test_sync.py tests/test_storage_migration.py -v`
Expected: FAIL (Name `migrate_doc_to_current` fehlt, `SCHEMA_VERSION` ist noch 3).

- [ ] **Step 3: `sync.py` ändern**

`SCHEMA_VERSION` (`~:24`):

```python
SCHEMA_VERSION = 4
```

Funktion umbenennen + Docstring anpassen (Body bleibt — `schema_version` wird über `SCHEMA_VERSION` automatisch 4):

```python
def migrate_doc_to_current(remote_doc):
    """Migriert ein älteres Sync-Doc auf das aktuelle Schema (v4): flache Einträge
    (start/end/pause) werden in eine Slot-Liste gewrappt. Idempotent — Einträge mit
    `slots` bleiben unangetastet; Tombstones bekommen eine leere Slot-Liste.
    settings/conflicts/meta bleiben unberührt (per_day-category_times ist additiv in
    den Settings und braucht keine Doc-Migration).

    Damit absorbiert ein aktueller Client ein älteres (v1–v3) Remote-Doc und zieht es
    hoch, statt es abzuweisen oder beim Push zu plätten."""
    entries = remote_doc.get("entries") or {}
    migrated = {}
    for date, entry in entries.items():
        if not isinstance(entry, dict):
            continue
        if "slots" in entry:
            migrated[date] = entry
            continue
        if entry.get("deleted"):
            slots = []
        else:
            slots = [{
                "start": entry.get("start"),
                "end": entry.get("end"),
                "pause": entry.get("pause", 0),
                "kategorie": "",
            }]
        migrated[date] = {
            "slots": slots,
            "modified_at": entry.get("modified_at"),
            "device_id": entry.get("device_id"),
            "deleted": bool(entry.get("deleted", False)),
        }
    return {**remote_doc, "schema_version": SCHEMA_VERSION, "entries": migrated}
```

(`_remote_is_newer` und `NEWER_REMOTE_VERSION_MSG` bleiben **unverändert** — sie greifen über `SCHEMA_VERSION` automatisch für v4.)

- [ ] **Step 4: `main.py` — 3 Aufrufstellen umbenennen**

In `src/main.py` an den drei Stellen (`~:97`, `~:150`, `~:214`):

```python
            remote_doc = sync.migrate_doc_to_current(remote_doc)
```

(jeweils `migrate_doc_to_v3` → `migrate_doc_to_current`.)

- [ ] **Step 5: Tests laufen lassen — müssen bestehen**

Run: `pytest tests/test_sync.py tests/test_storage_migration.py -v`
Expected: PASS.

- [ ] **Step 6: Sicherstellen, dass kein `migrate_doc_to_v3` mehr existiert**

Run: `git grep -n "migrate_doc_to_v3"`
Expected: keine Treffer.

- [ ] **Step 7: Import-Smoke main.py**

Run: `python -c "import src.main"`
Expected: kein Fehler.

- [ ] **Step 8: Settings-Roundtrip-Smoke (per_day-Dict lädt/speichert unverändert)**

In `tests/test_settings.py` ergänzen (Import von `Settings` aus `src.settings` ist dort vorhanden):

```python
def test_per_day_category_times_roundtrips(tmp_path):
    path = str(tmp_path / "settings.json")
    s = Settings(path)
    pd = {"Homeoffice": {"mode": "per_day", "pause": 0,
                         "days": {"mon": {"start": "09:00", "end": "18:00"}}}}
    s.set_synced("category_times", pd)
    # frisch laden → verschachtelte Struktur kommt unverändert zurück (Dict-Passthrough)
    assert Settings(path).get("category_times") == pd
```

Run: `pytest tests/test_settings.py::test_per_day_category_times_roundtrips -v`
Expected: PASS (zeigt: `_coerce`/`_load` lassen den per_day-Dict als Ganzes durch).

- [ ] **Step 9: Commit**

```bash
git add src/sync.py src/main.py tests/test_sync.py tests/test_storage_migration.py tests/test_settings.py
git commit -m "$(cat <<'EOF'
feat(sync): SCHEMA_VERSION 3->4 als Forward-Compat-Guard (#84)

Schützt die neue per_day-category_times-Struktur: Altclients (v3) brechen
Pull/Push/Compaction via _remote_is_newer sauber ab, statt sie zu plätten.
migrate_doc_to_v3 -> migrate_doc_to_current (Verhalten unverändert).
Settings-Roundtrip-Smoke: per_day-Dict lädt/speichert unverändert.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: UI-Wiring im Kategorien-Dialog (Modus-Toggle, Per-Tag-Grid, Confirm)

**Files:**
- Modify: `src/dialogs/category_dialog.py` (`open_category_dialog` + `add_row` + `on_save`)

**Interfaces:**
- Consumes: `row_defaults_from_entry` (Task 3), `collect_categories` (Task 2), `categories_losing_per_day` (Task 4), `themed_askyesno` (aus `src.theme`).

Reines Tk-Wiring — die verlustkritische Logik ist in Task 2–4 pure getestet. Kein Unit-Test (Wiring); Verify ist manuell (Step 7). Der bestehende read-only „Pro Tag ▶"-Toggle der Referenzzeile (`category_dialog.py:135–162`) ist die Vorlage für das ausklappbare Grid.

- [ ] **Step 1: `themed_askyesno` importieren**

In `src/dialogs/category_dialog.py` den `from src.theme import (...)`-Block um `themed_askyesno` ergänzen (alphabetisch einsortiert).

- [ ] **Step 2: `add_row` auf Modus-Toggle + Per-Tag-Grid umbauen**

`add_row` nimmt künftig einen vorbereiteten `defaults`-Dict (aus `row_defaults_from_entry`) statt einzelner Argumente. Aufbau pro Zeile:

- Name-Entry (wie bisher).
- **Modus-Combo** `dark_combo` mit Werten `["Allgemein", "Tageweise"]`, gemappt auf `general`/`per_day`. StringVar `mode_var`.
- **General-Felder** (Start–Ende-Combos) in einem eigenen Frame `general_frame`.
- **Pause-Combo** (immer sichtbar, eine pro Zeile).
- **Per-Tag-Grid** in einem eigenen Frame `day_frame` (7 Zeilen Mo–So, je zwei `dark_combo` Start/Ende), vorbefüllt aus `defaults["days"]`. Die 14 StringVars in `day_vars[tag] = {"start": sv, "end": ev}` halten.
- `×`-Button (wie bisher).

**Layout:** Die Hauptzeile (`row`) trägt fix `[Name] [Modus] [general_frame] [Pause] [×]`
nebeneinander (`side=tk.LEFT`). `general_frame` enthält die Start–Ende-Combos; im
per_day-Modus wird es per `pack_forget()` ausgeblendet und stattdessen `day_frame` (das
7-Tage-Grid) **unter** der Zeile gezeigt. `day_frame` wird in einem die Zeile umgebenden
Container nach `row` eingehängt (analog zum bestehenden `daygrid`-Toggle, das per
`pack(after=std_row, ...)` einklappt, `category_dialog.py:152–162`).

Sichtbarkeit nach `mode_var` (verstecken, **nie** zerstören):

```python
        def _apply_mode(*_a):
            if mode_var.get() == "Tageweise":
                general_frame.pack_forget()
                day_frame.pack(after=row, anchor="w", pady=(0, 4))
            else:
                day_frame.pack_forget()
                # general_frame wieder an seine Stelle in der Zeile, vor der
                # Pause-Combo — dieselben pack-Optionen wie beim Erstaufbau:
                general_frame.pack(in_=row, side=tk.LEFT, padx=2, before=pause_combo)

        mode_combo.bind("<<ComboboxSelected>>", _apply_mode)
```

`record` trägt alle vom Save gelesenen Vars (Schlüssel **identisch** zu den `on_save`-
Zugriffen `r["..."]`):

```python
        record = {"frame": row, "name": nv, "mode": mode_var,
                  "start": start_var, "end": end_var, "pause": pause_var,
                  "days": day_vars}
```

**Spiegelung beim Wechsel auf Tageweise** (nur wenn das Grid noch komplett STANDARD ist, damit ein erneuter Toggle bestehende Tageswerte nicht überschreibt):

```python
            if mode_var.get() == "Tageweise" and _grid_all_standard(day_vars):
                for tag in WEEKDAY_KEYS:
                    day_vars[tag]["start"].set(start_var.get())
                    day_vars[tag]["end"].set(end_var.get())
```

**Rückschaltung auf Allgemein:** general-Combo mit dem Montags-Satz vorbefüllen, falls sie noch STANDARD ist:

```python
            if mode_var.get() == "Allgemein" and start_var.get() == STANDARD:
                mon = day_vars["mon"]
                if mon["start"].get() != STANDARD:
                    start_var.set(mon["start"].get())
                if mon["end"].get() != STANDARD:
                    end_var.set(mon["end"].get())
```

`record` hält jetzt zusätzlich `mode_var` und `day_vars`, damit `on_save` die Zeile vollständig auslesen kann. Initialen Modus aus `defaults["mode"]` setzen, **danach** `_apply_mode()` einmal direkt rufen (Sichtbarkeit herstellen) — `<<ComboboxSelected>>` feuert bei programmatischem `.set()` nicht.

- [ ] **Step 3: Hydration beim Laden auf `row_defaults_from_entry` umstellen**

Die Lade-Schleife (`category_dialog.py:185–194`) ersetzen:

```python
    if categories:
        for c in categories:
            add_row(c, row_defaults_from_entry(category_times.get(c) or {}))
    else:
        add_row("", row_defaults_from_entry({}))
```

(Die `+ Kategorie`-Schaltfläche ruft `add_row("", row_defaults_from_entry({}))`.)

- [ ] **Step 4: `on_save` — Roh-Dicts inkl. mode/days + Downgrade-Confirm**

```python
    def on_save():
        raw = []
        for r in rows:
            raw.append({
                "name": r["name"].get(),
                "mode": "per_day" if r["mode"].get() == "Tageweise" else "general",
                "start": r["start"].get(),
                "end": r["end"].get(),
                "pause": r["pause"].get(),
                "days": {tag: {"start": v["start"].get(), "end": v["end"].get()}
                         for tag, v in r["days"].items()},
            })

        losing = categories_losing_per_day(raw)
        if losing:
            names = ", ".join(losing)
            if not themed_askyesno(
                dialog, "Tageszeiten verwerfen?",
                f"Für {names} gehen die tageweise gesetzten Zeiten verloren, "
                "wenn als „Allgemein" gespeichert wird.\n\nTrotzdem speichern?",
            ):
                return

        cats, times = collect_categories(raw)
        settings.set_synced("categories", cats)
        settings.set_synced("category_times", times)
        if on_change is not None:
            on_change()
        dialog.destroy()
```

- [ ] **Step 5: `_grid_all_standard`-Helfer ergänzen** (lokal in `open_category_dialog` oder Modulebene)

```python
def _grid_all_standard(day_vars):
    return all(v["start"].get() == STANDARD and v["end"].get() == STANDARD
               for v in day_vars.values())
```

- [ ] **Step 6: Voller Testlauf + Lint + Import-Smoke**

Run: `pytest -q`
Expected: PASS (alle Tests grün).

Run: `ruff check .`
Expected: keine neuen Findings (`category_dialog.py`, `category_defaults.py`, `sync.py`, `main.py`, `entry_dialog.py`).

Run: `python -c "import src.dialogs.category_dialog"`
Expected: kein Fehler.

- [ ] **Step 7: Manueller Verify — der echte Verhaltenstest**

Run: `python -m src.main`

1. Kategorien verwalten öffnen → `Homeoffice` auf **Tageweise** stellen → Grid klappt auf, mit gespiegelten Werten vorbefüllt.
2. Mo–Do `09:00–18:00`, Fr `09:00–14:00`, Sa/So leer lassen → **Speichern**.
3. `settings.json` prüfen: `category_times["Homeoffice"]` hat `mode:"per_day"`, `days` mit mon–fri, `pause`. `Office_1` unverändert flach.
4. Tages-Dialog an einem **Montag** öffnen → „+ Slot" → `Homeoffice` wählen → Felder `09:00–18:00`. An einem **Freitag** → `09:00–14:00`. An einem **Samstag** → globaler Standard `08:00–16:00`.
5. Kategorien-Dialog → `Homeoffice` zurück auf **Allgemein** → **Speichern** → **Confirm** erscheint mit „Homeoffice".

Erwartetes Ergebnis: alle Schritte wie beschrieben.

- [ ] **Step 8: Commit**

```bash
git add src/dialogs/category_dialog.py
git commit -m "$(cat <<'EOF'
feat(category-times): Kategorien-Dialog mit Modus-Toggle + Per-Tag-Grid (#84)

Modus-Umschalter pro Zeile, ausklappbares 7-Tage-Grid (verstecken statt
zerstören), Hydration via row_defaults_from_entry, Downgrade-Confirm beim
Speichern. Verlustkritische Logik ist pure getestet.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: CHANGELOG-Eintrag

**Files:**
- Modify: `CHANGELOG.md`

- [ ] **Step 1: Eintrag ergänzen** (Stil/Sektion an die bestehende `CHANGELOG.md` anpassen)

```markdown
- Standardzeiten pro Kategorie wahlweise tageweise (pro Wochentag) statt nur
  allgemein konfigurierbar (#84).
```

- [ ] **Step 2: Commit**

```bash
git add CHANGELOG.md
git commit -m "$(cat <<'EOF'
docs(changelog): tageweise Kategorie-Standardzeiten (#84)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

> **Release-Mechanik (nicht Teil dieses Plans):** `src/version.py`-Bump + `release:*`-Label am PR steuern den Release-Workflow (siehe Projekt-`CLAUDE.md`). Gehört in den Release-PR, nicht in die Feature-Tasks.

---

## Notizen für die Ausführung

- **Reihenfolge:** Task 1 → 2 → 3 → 4 → 5 → 6 → 7. Task 5 (Sync) ist unabhängig und könnte vorgezogen werden; Task 6 braucht Task 2–4.
- **Datenmodell-Invariante:** `mode` wird bei „allgemein" **nicht** geschrieben (Bestandseinträge bleiben byte-stabil). Nie `"mode":"general"` persistieren.
- **Kein Anfassen** von `SYNCED_SETTING_KEYS` (schon korrekt) und `share.SCHEMA_VERSION` (bleibt 3).
- Bei Tk-Eigenheiten (pack-Reihenfolge, `<<ComboboxSelected>>` feuert nicht bei `.set()`) den bestehenden `category_dialog.py`/`entry_dialog.py`-Stil spiegeln.
