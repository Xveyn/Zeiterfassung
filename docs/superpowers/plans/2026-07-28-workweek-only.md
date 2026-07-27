# Nur Werktage (`workweek_only`) — Implementierungsplan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eine synchronisierte Einstellung `workweek_only`, die Sa/So in Kalender, Standardzeiten, Bericht/Mail/PDF und Stunden-Vorschau ausblendet — ohne Daten zu verändern.

**Architecture:** Ein neues pures Modul `src/workweek.py` (Prädikat, Filter, Zähler). Der Report-Pfad filtert **am Snapshot** (`storage.get_all()` in drei Dialogen), nicht in `report.py` — das bleibt settings-frei. Kalender und Standardzeiten lesen die Flag direkt.

**Tech Stack:** Python 3.10, Tkinter, pytest. Keine neuen Abhängigkeiten.

**Spec:** `docs/superpowers/specs/2026-07-28-workweek-only-design.md`

## Global Constraints

- Bezeichner englisch, UI-Texte und Docstrings deutsch (CONTRIBUTING.md).
- `workweek_only` ist ein **synchronisiertes** Setting: Default `False` in `DEFAULTS`, Eintrag in `SYNCED_SETTING_KEYS`.
- **Keine Daten verändern.** Wochenend-Einträge und die Standardzeiten für `sat`/`sun` bleiben in `settings.json`/`zeiterfassung.json` unangetastet; die Einstellung blendet nur aus.
- `report.py` wird **nicht** angefasst — kein neuer Parameter, keine Settings-Abhängigkeit.
- Werkstudenten-Limit (`weekly_limit.py`), Teilen (`share.py`) und der Kalender-Abgleich (`reservations_sync.py`) bleiben unberührt.
- Ein unlesbarer Datumsschlüssel gilt als **nicht** Wochenende (Filtern darf nichts verschlucken, das es nicht sicher zuordnen kann).
- Vor jedem Commit sauber: `python -m pytest -q -p no:warnings`, `python -m ruff check .`, `npx --no-install pyright`.
- Conventional-Commit-Betreff, Body deutsch. **Kein** `git push`, kein PR.

## File Structure

| Datei | Verantwortung |
|---|---|
| `src/workweek.py` (neu) | `is_weekend`, `filter_for_report`, `count_weekend_entries` — pur, Tk-frei |
| `src/settings.py` (ändern) | Default + `SYNCED_SETTING_KEYS` |
| `src/grid_renderer.py` (ändern) | `_visible_day_count`: `workweek_only` überstimmt `show_weekend` |
| `src/dialogs/settings_dialog/tab_work.py` (ändern) | Checkbox + Sa/So-Zeilen ausblenden (Vars bleiben) |
| `src/dialogs/settings_dialog/tab_app.py` (ändern) | vorhandene Wochenend-Checkbox deaktivieren + Hinweis |
| `src/dialogs/settings_dialog/dialog.py` (ändern) | Speicherpfad |
| `src/dialogs/send_dialog.py`, `export_dialog.py`, `period_picker.py` (ändern) | Snapshot filtern; Hinweiszeile |
| `tests/test_workweek.py` (neu), `test_settings.py`, `test_grid_geometry.py` (ändern) | Tests der puren Ebene |
| `README.md`, `src/CLAUDE.md`, Spec (ändern) | Doku |

---

### Task 1: Modul `src/workweek.py`

**Files:**
- Create: `src/workweek.py`
- Test: `tests/test_workweek.py` (neu)

**Interfaces:**
- Consumes: nichts.
- Produces:
  - `is_weekend(date_str) -> bool`
  - `filter_for_report(entries, settings) -> dict` — bei inaktiver Einstellung **dasselbe** Objekt (keine Kopie)
  - `count_weekend_entries(entries, date_from, date_to) -> int` — `date_from`/`date_to` sind `datetime.date`, Grenzen inklusive

- [ ] **Step 1: Write the failing tests**

Neue Datei `tests/test_workweek.py`:

```python
"""Nur-Werktage-Modus: Prädikat, Report-Filter und Zähler für die Hinweiszeile.

Pure Logik ohne Tk und ohne Storage — die Einstellung kommt als Stub herein."""

import datetime

from src.workweek import count_weekend_entries, filter_for_report, is_weekend


class _Settings:
    def __init__(self, workweek_only):
        self._value = workweek_only

    def get(self, key):
        assert key == "workweek_only"
        return self._value


def _entries(*dates):
    return {d: {"slots": [{"start": "08:00", "end": "16:00", "pause": 30}]} for d in dates}


# 2026-07-27 ist ein Montag, 2026-08-01 ein Samstag, 2026-08-02 ein Sonntag.

def test_saturday_and_sunday_are_weekend():
    assert is_weekend("2026-08-01") is True
    assert is_weekend("2026-08-02") is True


def test_weekdays_are_not_weekend():
    assert is_weekend("2026-07-27") is False
    assert is_weekend("2026-07-31") is False


def test_unparsable_key_is_not_weekend():
    """Filtern darf nichts verschlucken, das es nicht sicher zuordnen kann."""
    assert is_weekend("kaputt") is False
    assert is_weekend("") is False
    assert is_weekend(None) is False


def test_filter_is_a_noop_when_setting_is_off():
    entries = _entries("2026-07-27", "2026-08-01")
    result = filter_for_report(entries, _Settings(False))
    assert result is entries          # nicht einmal kopiert


def test_filter_drops_weekend_days_when_setting_is_on():
    entries = _entries("2026-07-27", "2026-07-31", "2026-08-01", "2026-08-02")
    result = filter_for_report(entries, _Settings(True))
    assert sorted(result) == ["2026-07-27", "2026-07-31"]


def test_filter_leaves_the_input_untouched():
    """Die Daten bleiben — gefiltert wird eine Kopie."""
    entries = _entries("2026-07-27", "2026-08-01")
    filter_for_report(entries, _Settings(True))
    assert sorted(entries) == ["2026-07-27", "2026-08-01"]


def test_filter_handles_empty_and_weekend_free_input():
    assert filter_for_report({}, _Settings(True)) == {}
    entries = _entries("2026-07-27")
    assert filter_for_report(entries, _Settings(True)) == entries


def test_count_weekend_entries_in_range():
    entries = _entries("2026-07-27", "2026-08-01", "2026-08-02")
    n = count_weekend_entries(
        entries, datetime.date(2026, 7, 27), datetime.date(2026, 8, 2))
    assert n == 2


def test_count_respects_the_range_bounds_inclusively():
    entries = _entries("2026-08-01", "2026-08-02")
    same_day = count_weekend_entries(
        entries, datetime.date(2026, 8, 1), datetime.date(2026, 8, 1))
    assert same_day == 1
    outside = count_weekend_entries(
        entries, datetime.date(2026, 7, 1), datetime.date(2026, 7, 31))
    assert outside == 0


def test_count_is_zero_without_weekend_entries():
    entries = _entries("2026-07-27", "2026-07-31")
    n = count_weekend_entries(
        entries, datetime.date(2026, 7, 1), datetime.date(2026, 8, 31))
    assert n == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_workweek.py -q -p no:warnings`
Expected: FAIL beim Import — `ModuleNotFoundError: No module named 'src.workweek'`

- [ ] **Step 3: Implement the module**

Neue Datei `src/workweek.py`:

```python
# src/workweek.py
"""Nur-Werktage-Modus: Wochenende (Sa/So) überall deaktivieren.

Pure Logik, Tk-frei — wie `weekly_limit.py`/`pause_requirement.py`. Die
Einstellung `workweek_only` blendet Sa/So aus Kalender, Standardzeiten und
Bericht aus, **ohne Daten zu löschen**: Die Einträge bleiben im Storage und
tauchen wieder auf, sobald die Einstellung zurückgenommen wird.

Bewusst nicht hier: das Werkstudenten-Limit (zählt real geleistete Stunden,
auch am Wochenende), das Teilen von Rohdaten und der Kalender-Abgleich.
"""

import datetime


def is_weekend(date_str):
    """Ist der ISO-Datumsschlüssel ein Samstag oder Sonntag?

    Ein unlesbarer Schlüssel gilt als **nicht** Wochenende: Filtern darf nie
    Daten verschlucken, die es nicht sicher zuordnen kann.
    """
    try:
        return datetime.date.fromisoformat(date_str).weekday() >= 5
    except (TypeError, ValueError):
        return False


def filter_for_report(entries, settings):
    """`entries` ohne Wochenendtage — wenn `workweek_only` aktiv ist.

    Bei inaktiver Einstellung wird das Eingabe-Dict unverändert
    zurückgegeben (nicht kopiert); sonst entsteht ein neues Dict, das Original
    bleibt unangetastet.

    Angewendet wird das am Snapshot (`storage.get_all()`) der Dialoge, nicht in
    `report.py` — so bleibt der Report settings-frei, und Mail-HTML, PDF und
    Stunden-Vorschau sehen automatisch dieselben Daten.
    """
    if not settings.get("workweek_only"):
        return entries
    return {k: v for k, v in entries.items() if not is_weekend(k)}


def count_weekend_entries(entries, date_from, date_to):
    """Anzahl der Wochenend-Tage mit Eintrag im Zeitraum (Grenzen inklusive).

    Für die Hinweiszeile im Sende-/Export-Dialog — gezählt wird deshalb auf dem
    **ungefilterten** Snapshot. `date_from`/`date_to` sind `datetime.date`.
    """
    from_str = date_from.isoformat()
    to_str = date_to.isoformat()
    return sum(1 for k in entries if from_str <= k <= to_str and is_weekend(k))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_workweek.py -q -p no:warnings`
Expected: PASS (10 Tests)

- [ ] **Step 5: Suite, Lint, Typecheck**

Run: `python -m pytest -q -p no:warnings && python -m ruff check . && npx --no-install pyright src/workweek.py tests/test_workweek.py`
Expected: alles grün, „0 errors"

- [ ] **Step 6: Commit**

```bash
git add src/workweek.py tests/test_workweek.py
git commit -m "feat(workweek): pures Modul fuer den Nur-Werktage-Modus"
```

---

### Task 2: Einstellung und Kalender-Spalten

**Files:**
- Modify: `src/settings.py` (`DEFAULTS` bei `"show_weekend": True`, `SYNCED_SETTING_KEYS`)
- Modify: `src/grid_renderer.py` (`_visible_day_count`, aktuell Zeile 203-209)
- Test: `tests/test_settings.py`, `tests/test_grid_geometry.py`

**Interfaces:**
- Consumes: nichts aus Task 1 (unabhängig).
- Produces: Setting-Key `workweek_only` (Default `False`, synchronisiert); `_visible_day_count()` liefert 5, sobald `workweek_only` aktiv ist.

- [ ] **Step 1: Write the failing tests**

In `tests/test_settings.py` ans Ende anfügen (die vorhandenen `werkstudent_limit_enabled`-Tests um Zeile 583/590 sind das Vorbild — `tmp_settings` ist deren Fixture, benutze dieselbe):

```python
def test_workweek_only_defaults_to_off(tmp_settings):
    assert tmp_settings.get("workweek_only") is False


def test_workweek_only_is_synced():
    """Die Flag bestimmt den Berichtsinhalt — auf zwei Geräten unterschiedlich
    eingestellt hieße: zwei verschiedene Berichte aus denselben Daten."""
    assert "workweek_only" in SYNCED_SETTING_KEYS
```

In `tests/test_grid_geometry.py` ans Ende anfügen:

```python
def _renderer_with_settings(**values):
    """GridRenderer mit gestubbten Settings; nicht gesetzte Keys → Default."""
    root = MagicMock()
    root.winfo_reqwidth.return_value = 700
    root.winfo_reqheight.return_value = 400
    settings = MagicMock(get=lambda k, d=None: values.get(k, d))
    return GridRenderer(
        root=root, storage=object(), settings=settings,
        reservation_store=None, conflicts_store=None,
        on_cell_click=lambda d: None, on_cell_right_click=lambda d: None,
        reservations_active=lambda: False,
    )


def test_workweek_only_hides_weekend_even_when_show_weekend_is_on():
    """Der Nur-Werktage-Modus überstimmt den Kalender-Schalter — sonst stünde
    im App-Tab ein Haken, der sichtbar nichts tut."""
    r = _renderer_with_settings(show_weekend=True, workweek_only=True)
    assert r._visible_day_count() == 5


def test_show_weekend_still_governs_when_workweek_only_is_off():
    assert _renderer_with_settings(
        show_weekend=True, workweek_only=False)._visible_day_count() == 7
    assert _renderer_with_settings(
        show_weekend=False, workweek_only=False)._visible_day_count() == 5
```

Prüfe beim Anfügen, ob `SYNCED_SETTING_KEYS` in `tests/test_settings.py` schon importiert ist; falls nicht, ergänze den Import aus `src.settings`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_settings.py tests/test_grid_geometry.py -q -p no:warnings`
Expected: FAIL — `workweek_only` fehlt in den Defaults (`get` liefert `None` statt `False`), nicht in `SYNCED_SETTING_KEYS`, und `_visible_day_count()` liefert 7 statt 5.

- [ ] **Step 3: Add the setting**

In `src/settings.py` in `DEFAULTS` direkt **nach** `"show_weekend": True,` einfügen:

```python
    "workweek_only": False,
```

und in `SYNCED_SETTING_KEYS` direkt **nach** `"pause_warning_enabled",` :

```python
    "workweek_only",
```

- [ ] **Step 4: Let workweek_only outrank show_weekend**

In `src/grid_renderer.py` die Methode `_visible_day_count` ersetzen:

```python
    def _visible_day_count(self):
        """Sichtbare Wochentag-Spalten (5 bei show_weekend=False, sonst 7).

        `workweek_only` überstimmt `show_weekend`: im Nur-Werktage-Modus sind
        Sa/So immer aus (die Checkbox im App-Tab ist dann deaktiviert).

        Wird von _build_grid_header und den Refresh-Pfaden als einzige
        Quelle der Wahrheit konsultiert.
        """
        if self._settings.get("workweek_only"):
            return 5
        return 7 if self._settings.get("show_weekend") else 5
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_settings.py tests/test_grid_geometry.py -q -p no:warnings`
Expected: PASS

- [ ] **Step 6: Suite, Lint, Typecheck**

Run: `python -m pytest -q -p no:warnings && python -m ruff check . && npx --no-install pyright`
Expected: alles grün. Die Footer-Summe braucht **keine** Änderung: sie zählt nur gerenderte Zellen.

- [ ] **Step 7: Commit**

```bash
git add src/settings.py src/grid_renderer.py tests/test_settings.py tests/test_grid_geometry.py
git commit -m "feat(workweek): Einstellung workweek_only, Kalender ohne Sa/So"
```

---

### Task 3: Einstellungs-Oberfläche

**Files:**
- Modify: `src/dialogs/settings_dialog/tab_work.py` (Checkbox + Standardzeiten-Zeilen)
- Modify: `src/dialogs/settings_dialog/dialog.py` (Speicherpfad, `updates`-Dict um Zeile 192)
- Modify: `src/dialogs/settings_dialog/tab_app.py` (Zeile 35-42: Checkbox deaktivieren + Hinweis)

**Interfaces:**
- Consumes: Setting-Key `workweek_only` aus Task 2.
- Produces: `WorkTab.workweek_only_var` (`tk.BooleanVar`), von `dialog.py::save_settings` gelesen.

**Keine automatisierten Tests** für diesen Task: reines Tk-Wiring, konsistent mit der übrigen UI-Schicht. Die bestehende Suite muss grün bleiben — insbesondere `tests/test_settings_dialog.py`.

- [ ] **Step 1: Checkbox in den Arbeitszeit-Tab**

In `src/dialogs/settings_dialog/tab_work.py` **vor** der Zeile `label(frame, "Standardzeiten:", row=0, pady=(10, 4), sticky="nw")` einfügen:

```python
        workweek_only_var = tk.BooleanVar(value=settings.get("workweek_only"))
        tk.Checkbutton(
            frame, text="Nur Werktage — Wochenende (Sa/So) komplett deaktivieren",
            variable=workweek_only_var, font=FONT, bg=BG, fg=TEXT, selectcolor=CELL_BG,
            activebackground=BG, activeforeground=TEXT, cursor="hand2",
        ).grid(row=0, column=0, columnspan=2, padx=10, pady=(10, 0), sticky="w")
```

- [ ] **Step 2: Die nachfolgenden Grid-Zeilen um 1 verschieben**

Im selben File, alle Stellen mit fester Row-Nummer:

| Element | vorher | nachher |
|---|---|---|
| `label(frame, "Standardzeiten:", row=…)` | `row=0` | `row=1` |
| `times_frame.grid(row=…)` | `row=0` | `row=1` |
| `label(frame, "Standard-Pause (Min):", row=…)` | `row=1` | `row=2` |
| `dark_combo(frame, pause_var, PAUSE_VALUES).grid(row=…)` | `row=1` | `row=2` |
| Pausenpflicht-Checkbutton `.grid(row=…)` | `row=2` | `row=3` |
| `subheader(frame, "Werkstudenten-Limit", row=…)` | `row=3` | `row=4` |
| `wsl_frame.grid(row=…)` | `row=4` | `row=5` |
| Button „Kategorien verwalten" `.grid(row=…)` | `row=5` | `row=6` |

Die Zeile `label(frame, "Standardzeiten:", ...)` behält ihr `pady=(10, 4)` — die Checkbox darüber schließt mit `pady=(10, 0)` an.

- [ ] **Step 3: Sa/So-Zeilen ausblenden, Werte behalten**

Die Wochentags-Schleife in `tab_work.py` ersetzen. Vorher:

```python
        for i, (key, lbl) in enumerate(zip(WEEKDAY_KEYS, DAYS_DE, strict=False), start=1):
            tk.Label(times_frame, text=lbl, font=FONT, bg=BG, fg=TEXT, width=3, anchor="w").grid(
                row=i, column=0, padx=(0, 8), pady=2)
            start_vars[key] = tk.StringVar(value=settings.get(f"default_start_{key}"))
            dark_combo(times_frame, start_vars[key], TIME_VALUES).grid(
                row=i, column=1, padx=2, pady=2)
            end_vars[key] = tk.StringVar(value=settings.get(f"default_end_{key}"))
            dark_combo(times_frame, end_vars[key], TIME_VALUES).grid(
                row=i, column=2, padx=2, pady=2)
```

Nachher:

```python
        # Die StringVars entstehen für ALLE sieben Tage, auch für die
        # ausgeblendeten: save_settings schreibt unverändert alle Wochentage
        # zurück, damit die Werte für Sa/So erhalten bleiben und sofort wieder
        # da sind, wenn "Nur Werktage" zurückgenommen wird.
        workweek_only = bool(settings.get("workweek_only"))
        row = 0
        for key, lbl in zip(WEEKDAY_KEYS, DAYS_DE, strict=False):
            start_vars[key] = tk.StringVar(value=settings.get(f"default_start_{key}"))
            end_vars[key] = tk.StringVar(value=settings.get(f"default_end_{key}"))
            if workweek_only and key in ("sat", "sun"):
                continue
            row += 1
            tk.Label(times_frame, text=lbl, font=FONT, bg=BG, fg=TEXT, width=3, anchor="w").grid(
                row=row, column=0, padx=(0, 8), pady=2)
            dark_combo(times_frame, start_vars[key], TIME_VALUES).grid(
                row=row, column=1, padx=2, pady=2)
            dark_combo(times_frame, end_vars[key], TIME_VALUES).grid(
                row=row, column=2, padx=2, pady=2)
```

- [ ] **Step 4: Var exponieren und speichern**

Am Ende von `tab_work.py` bei den übrigen `self.…`-Zuweisungen ergänzen:

```python
        self.workweek_only_var = workweek_only_var
```

In `src/dialogs/settings_dialog/dialog.py` im `updates`-Dict direkt nach `"pause_warning_enabled": work.pause_warning_var.get(),` ergänzen:

```python
            "workweek_only": work.workweek_only_var.get(),
```

- [ ] **Step 5: Überstimmten Schalter im App-Tab kenntlich machen**

In `src/dialogs/settings_dialog/tab_app.py` den Block ab Zeile 35 ersetzen. Vorher:

```python
        show_weekend_var = tk.BooleanVar(value=settings.get("show_weekend"))
        tk.Checkbutton(
            app_frame, text="Wochenende (Sa/So) im Kalender anzeigen",
            variable=show_weekend_var, font=FONT,
            bg=BG, fg=TEXT, selectcolor=CELL_BG,
            activebackground=BG, activeforeground=TEXT,
            cursor="hand2",
        ).pack(anchor="w")
```

Nachher:

```python
        show_weekend_var = tk.BooleanVar(value=settings.get("show_weekend"))
        weekend_cb = tk.Checkbutton(
            app_frame, text="Wochenende (Sa/So) im Kalender anzeigen",
            variable=show_weekend_var, font=FONT,
            bg=BG, fg=TEXT, selectcolor=CELL_BG,
            activebackground=BG, activeforeground=TEXT,
            cursor="hand2",
        )
        weekend_cb.pack(anchor="w")
        if settings.get("workweek_only"):
            # Sonst stünde hier ein Haken, der sichtbar nichts tut: der
            # Nur-Werktage-Modus blendet Sa/So ohnehin aus.
            weekend_cb.config(state="disabled")
            tk.Label(
                app_frame,
                text="Durch „Nur Werktage" (Arbeitszeit) überstimmt.",
                font=FONT_SMALL, bg=BG, fg=TEXT_MUTED,
            ).pack(anchor="w", padx=(24, 0))
```

Prüfe den Import-Block der Datei: `FONT_SMALL` und `TEXT_MUTED` müssen aus `src.theme` importiert sein; fehlt eines, ergänze es dort.

- [ ] **Step 6: Suite, Lint, Typecheck**

Run: `python -m pytest -q -p no:warnings && python -m ruff check . && npx --no-install pyright`
Expected: dieselbe Testzahl wie am Ende von Task 2 (dieser Task fügt keine Tests hinzu), Lint und Typecheck sauber. Schlägt `tests/test_settings_dialog.py` fehl, stimmt eine der verschobenen Row-Nummern nicht.

- [ ] **Step 7: Commit**

```bash
git add src/dialogs/settings_dialog/tab_work.py src/dialogs/settings_dialog/tab_app.py src/dialogs/settings_dialog/dialog.py
git commit -m "feat(settings): Checkbox 'Nur Werktage', Standardzeiten ohne Sa/So"
```

---

### Task 4: Bericht, Vorschau, Hinweiszeile und Doku

**Files:**
- Modify: `src/dialogs/send_dialog.py` (Zeile 100), `src/dialogs/export_dialog.py` (Zeile 47), `src/dialogs/period_picker.py` (Zeile 93 + Vorschau-Block ab Zeile 131)
- Modify: `README.md`, `src/CLAUDE.md`, `docs/superpowers/specs/2026-07-28-workweek-only-design.md`

**Interfaces:**
- Consumes: `workweek.filter_for_report(entries, settings)` und `workweek.count_weekend_entries(entries, date_from, date_to)` aus Task 1; Setting-Key aus Task 2.
- Produces: nichts für spätere Tasks (letzter Task).

**Keine automatisierten Tests** für diesen Task: die gefilterte Datenmenge ist in Task 1 abgedeckt, hier ist nur Verdrahtung. Die bestehende Suite muss grün bleiben.

- [ ] **Step 1: Snapshot im Sende-Dialog filtern**

In `src/dialogs/send_dialog.py` Zeile 100. Vorher:

```python
        entries = storage.get_all()
```

Nachher:

```python
        # Nur-Werktage-Modus: Sa/So fliegen einmal am Snapshot raus — damit
        # sehen Mail-HTML (generate_report) und PDF (generate_pdf im Worker)
        # automatisch dieselben Daten, ohne dass report.py die Einstellung
        # kennen muss.
        entries = workweek.filter_for_report(storage.get_all(), settings)
```

Am Dateikopf `from src import workweek` ergänzen (zu den übrigen `src`-Importen).

- [ ] **Step 2: Snapshot im Export-Dialog filtern**

In `src/dialogs/export_dialog.py` Zeile 47 analog:

```python
        entries = workweek.filter_for_report(storage.get_all(), settings)
```

Auch hier `from src import workweek` am Dateikopf ergänzen. Prüfe, dass `settings` in dieser Funktion verfügbar ist (der Dialog bekommt es als Parameter) — falls nicht, melde das als BLOCKED, statt es durchzureichen.

- [ ] **Step 3: Vorschau filtern und Hinweiszeile bauen**

In `src/dialogs/period_picker.py` Zeile 93. Vorher:

```python
    all_entries = storage.get_all()
```

Nachher:

```python
    # Zwei Sichten auf denselben Snapshot: die Vorschau rechnet mit den
    # gefilterten Daten, der Hinweis zählt auf den ungefilterten — sonst wäre
    # die Zahl, die er nennt, per Konstruktion immer 0.
    all_entries_raw = storage.get_all()
    all_entries = workweek.filter_for_report(all_entries_raw, settings)
```

`from src import workweek` am Dateikopf ergänzen.

Direkt **nach** dem `total_label`-Block (aktuell Zeile 131-133) das Hinweis-Label anlegen:

```python
    # Gedämpfte Hinweiszeile: nur im Nur-Werktage-Modus und nur, wenn im
    # gewählten Zeitraum tatsächlich Wochenend-Einträge liegen. Ohne sie
    # verlöre jemand mit Alt-Daten stillschweigend Stunden aus dem Bericht.
    weekend_hint = tk.Label(frame, text="", font=FONT_SMALL, bg=BG, fg=TEXT_MUTED)
    weekend_hint.grid(row=5, column=0, columnspan=6, padx=10, pady=(0, 8), sticky="w")
```

Und in `_update_total` die Aktualisierung ergänzen — die Funktion sieht danach so aus:

```python
    def _update_total(*_):
        df, dt = handle.get_range()
        if df is None or dt is None or df > dt:
            total_label.config(text="Gesamtstunden: —")
            weekend_hint.config(text="")
            return
        hours = total_hours(df, dt, all_entries, handle.get_categories())
        total_label.config(text=f"Gesamtstunden: {hours}h")
        n = (workweek.count_weekend_entries(all_entries_raw, df, dt)
             if settings.get("workweek_only") else 0)
        if n == 1:
            weekend_hint.config(text="1 Wochenend-Eintrag im Zeitraum wird nicht berücksichtigt.")
        elif n > 1:
            weekend_hint.config(
                text=f"{n} Wochenend-Einträge im Zeitraum werden nicht berücksichtigt.")
        else:
            weekend_hint.config(text="")
```

In allen drei Dateien gilt derselbe Import-Stil: `from src import workweek` am Dateikopf, Aufrufe als `workweek.filter_for_report(...)` / `workweek.count_weekend_entries(...)`. Prüfe außerdem, ob `FONT_SMALL` und `TEXT_MUTED` im `src.theme`-Import dieser Datei stehen, und ergänze sie sonst.

Achtung Grid: Prüfe vor dem Einfügen, ob `row=5` im Frame frei ist (die Vorschau liegt auf `row=4`). Ist die Zeile belegt, nimm die nächste freie und lass die bestehenden Zeilen unverändert.

- [ ] **Step 4: Suite, Lint, Typecheck**

Run: `python -m pytest -q -p no:warnings && python -m ruff check . && npx --no-install pyright`
Expected: dieselbe Testzahl wie am Ende von Task 2, Lint und Typecheck sauber.

- [ ] **Step 5: Doku nachziehen**

`README.md` — in der Feature-Liste nach dem Punkt „**Pausenpflicht-Warnung** …" einfügen:

```
- **Nur Werktage** — Optional lässt sich das Wochenende komplett deaktivieren: Sa/So verschwinden aus Kalender, Standardzeiten, Bericht, Mailversand und PDF-Export. Vorhandene Wochenend-Einträge bleiben gespeichert und sind sofort wieder da, wenn die Einstellung zurückgenommen wird
```

`README.md` — in der Einstellungs-Tabelle nach der Zeile `| **Pausenpflicht-Warnung** | … |`:

```
| **Nur Werktage** | Wochenende (Sa/So) überall ausblenden — Kalender, Standardzeiten und Bericht. Überstimmt „Wochenende im Kalender anzeigen"; Daten bleiben erhalten |
```

`README.md` — in der Projektstruktur nach der `pause_requirement.py`-Zeile:

```
│   ├── workweek.py        # Nur-Werktage-Modus (Sa/So ausblenden), pure Logik
```

`src/CLAUDE.md` — im Abschnitt „Daten- & Persistenz-Schicht" nach dem `pause_requirement.py`-Absatz anfügen:

```
  `workweek.py` — Nur-Werktage-Modus (`workweek_only`, synchronisiert). `is_weekend`
  (unlesbarer Schlüssel → False, Filtern darf nichts verschlucken),
  `filter_for_report` (inaktiv → dasselbe Dict, kein Kopieren) und
  `count_weekend_entries` für die Hinweiszeile. Gefiltert wird am **Snapshot**
  (`storage.get_all()` in send_dialog/export_dialog/period_picker), NICHT in
  `report.py` — das bleibt settings-frei, und Mail-HTML, PDF und Vorschau sehen
  dadurch automatisch dieselben Daten. Im Kalender überstimmt die Flag
  `show_weekend` (`grid_renderer._visible_day_count`); in den Standardzeiten
  entfallen die Sa/So-Zeilen, ihre `StringVar`s aber nicht — der Speicherpfad
  schreibt weiter alle sieben Tage, damit die Werte erhalten bleiben. Bewusst
  unberührt: Werkstudenten-Limit (zählt real geleistete Stunden), Teilen und
  Kalender-Abgleich.
```

`docs/superpowers/specs/2026-07-28-workweek-only-design.md` — im Abschnitt „4. Hinweiszeile" den Beispieltext an den umgesetzten Wortlaut angleichen: `3 Wochenend-Einträge im Zeitraum werden nicht berücksichtigt.` (neutral, weil derselbe Baustein im Sende- **und** im Export-Dialog steckt).

- [ ] **Step 6: Commit**

```bash
git add src/dialogs/send_dialog.py src/dialogs/export_dialog.py src/dialogs/period_picker.py README.md src/CLAUDE.md docs/superpowers/specs/2026-07-28-workweek-only-design.md
git commit -m "feat(report): Wochenenden im Nur-Werktage-Modus aus Bericht und Vorschau nehmen"
```

---

## Abschluss

- [ ] `python -m pytest -q`, `python -m ruff check .`, `npx --no-install pyright` ein letztes Mal.
- [ ] Manuelle Prüfung durch den Controller (nicht durch Implementer): Einstellung an/aus, Kalender-Spalten, Standardzeiten-Zeilen, Hinweiszeile im Sende- und Export-Dialog, Werte für Sa/So nach dem Zurücknehmen noch da.
- [ ] PR gegen `margenheld/Zeiterfassung:master`, Hinweis auf den Stapel (#172 → #173 → #174 → #175 → dieser).
