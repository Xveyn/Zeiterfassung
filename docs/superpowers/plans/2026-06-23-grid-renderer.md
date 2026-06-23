# GridRenderer-Extraktion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Das Kalender-/Grid-Rendering aus `src/ui.py` in eine eigene Komponente `GridRenderer` (`src/grid_renderer.py`) auslagern — letzter Schritt der ui.py-Entflechtung (#49).

**Architecture:** Neues Tk-Rendering-Modul (kein `src.ui`-Import). `GridRenderer` besitzt den kompletten Rendering-State (Double-Buffer, Geometrie); bekommt Stores per Konstruktor, Datum/View per `refresh(...)`, Interaktion (`_open_dialog`/`_delete_day`) als Callbacks. `App._refresh` wird ein dünner Shim. Verhalten unverändert.

**Tech Stack:** Python 3, Tkinter, pytest.

## Global Constraints

- Verhalten unverändert (reiner Move-Refactor) — alle Strings/Farben/Fonts/Geometrie byte-identisch.
- `src/grid_renderer.py`: **kein** `src.ui`-Import. Datum/View ist **nicht** Renderer-Eigentum — kommt per `refresh(...)`/`measure_max_width(...)`-Parametern (App bleibt die Quelle).
- `measure_max_width` behält die bewusste `settings._data["show_weekend"]`-Direktmutation (Pre-Mainloop-Probing, kein Disk-Save).
- Lint: `python -m ruff check .` (ganzes Repo) grün. Tests: `python -m pytest` grün.
- Commit-Messages enden mit `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`.
- PowerShell 5.1: kein `&&`; `;` oder `if ($?) { }`. Match Edits **by content**, nicht by Zeilennummer (`~` = ungefähr).

### Substitutions-Tabelle (für ALLE verbatim verschobenen Methoden)

Beim Verschieben jeder Methode aus `App` in `GridRenderer` exakt diese Ersetzungen anwenden — sonst nichts ändern:

| In `App` (alt) | In `GridRenderer` (neu) |
|---|---|
| `self.storage` | `self._storage` |
| `self.settings` | `self._settings` |
| `self.reservation_store` | `self._reservation_store` |
| `self.conflicts_store` | `self._conflicts_store` |
| `self.root` | `self._root` |
| `self.view_mode` | `self._view_mode` |
| `self.year` / `self.month` | `self._year` / `self._month` |
| `self.iso_year` / `self.current_week` | `self._iso_year` / `self._current_week` |
| `self.grid_frames` | `self._grid_frames` |
| `self.grid_frame` | `self._grid_frame` |
| `self.grid_container` | `self.grid_container` *(unverändert — public)* |
| `self.header_label` | `self._header_label` |
| `self.footer_label` | `self._footer_label` |
| `self._open_dialog` | `self._on_cell_click` |
| `self._delete_day` | `self._on_cell_right_click` |

Unverändert bleiben (bereits `_`-prefixed, werden Renderer-Attribute/-Methoden): `self._active_grid_idx`, `self._fixed_width`, `self._suppress_geometry`, `self._last_refresh_view`, `self._last_refresh_columns`, `self._reservations_active` *(jetzt das injizierte Callable, gleiche Aufruf-Syntax)*, und alle `self._build_*` / `self._hover` / `self._truncate` / `self._fmt_slot_line` / `self._entry_hours` / `self._visible_day_count` / `self._dates_with_unresolved_conflicts` / `self._cell_layout_metrics` / `self._get_inactive_grid` / `self._activate_grid` / `self._update_footer` / `self._refresh_month` / `self._refresh_week` / `self._build_grid_header` (alle ziehen mit).

---

### Task 1: `src/grid_renderer.py` + Tests

**Files:**
- Create: `src/grid_renderer.py`
- Test: `tests/test_grid_renderer.py` (neu)
- Modify: `tests/test_ui_hover.py` (Import-Migration)

**Interfaces:**
- Produces: `GridRenderer(root, storage, settings, reservation_store, conflicts_store, on_cell_click, on_cell_right_click, reservations_active)` mit `build_grid(parent)`, `attach_labels(header_label, footer_label)`, `refresh(view_mode, year, month, iso_year, current_week)`, `measure_max_width(view_mode, year, month, iso_year, current_week)`, der public-Attribut `grid_container`, und allen verschobenen Rendering-Methoden. `on_cell_click(date_str)` / `on_cell_right_click(date_str)` / `reservations_active()` sind Callables.

**Hinweis:** `ui.py` wird in DIESER Task NICHT verändert (außer dem Test-Import). Die Rendering-Methoden existieren danach transient in beiden Dateien — `ui.py` nutzt weiter seine eigenen (Task 2 entfernt sie). Der Baum bleibt grün.

- [ ] **Step 1: Failing tests schreiben**

`tests/test_grid_renderer.py`:
```python
"""GridRenderer: reine Helfer ohne Tk (statics + Methoden, die nur settings/
conflicts_store lesen)."""

from unittest.mock import MagicMock

from src.time_utils import calculate_hours
from src.grid_renderer import GridRenderer


def _renderer(show_weekend=True, conflicts=None):
    settings = MagicMock(get=lambda k, d=None: {"show_weekend": show_weekend}.get(k, d))
    cstore = MagicMock(get_all=lambda: conflicts) if conflicts is not None else None
    return GridRenderer(
        root=object(), storage=object(), settings=settings,
        reservation_store=None, conflicts_store=cstore,
        on_cell_click=lambda d: None, on_cell_right_click=lambda d: None,
        reservations_active=lambda: False,
    )


def test_fmt_slot_line_with_category():
    assert GridRenderer._fmt_slot_line(
        {"start": "08:00", "end": "12:00", "kategorie": "Büro"}) == "08:00-12:00  Büro"


def test_fmt_slot_line_without_category():
    assert GridRenderer._fmt_slot_line(
        {"start": "08:00", "end": "12:00"}) == "08:00-12:00"


def test_truncate_clips_long_text():
    assert GridRenderer._truncate("Donnerstag", 5) == "Donn…"


def test_truncate_keeps_short_text():
    assert GridRenderer._truncate("Mo", 5) == "Mo"


def test_entry_hours_sums_slots():
    entry = {"slots": [
        {"start": "08:00", "end": "12:00", "pause": 0},
        {"start": "13:00", "end": "17:00", "pause": 0},
    ]}
    expected = round(
        calculate_hours("08:00", "12:00", pause_minutes=0)
        + calculate_hours("13:00", "17:00", pause_minutes=0), 2)
    assert _renderer()._entry_hours(entry) == expected == 8.0


def test_entry_hours_subtracts_pause():
    entry = {"slots": [{"start": "08:00", "end": "12:00", "pause": 30}]}
    assert _renderer()._entry_hours(entry) == 3.5


def test_visible_day_count_with_weekend():
    assert _renderer(show_weekend=True)._visible_day_count() == 7


def test_visible_day_count_without_weekend():
    assert _renderer(show_weekend=False)._visible_day_count() == 5


def test_dates_with_unresolved_conflicts_filters_entry_kind():
    conflicts = [
        {"key": "2026-06-01", "kind": "entry", "resolved": False},
        {"key": "2026-06-02", "kind": "entry", "resolved": True},
        {"key": "2026-06-03", "kind": "reservation", "resolved": False},
    ]
    assert _renderer(conflicts=conflicts)._dates_with_unresolved_conflicts() == {"2026-06-01"}


def test_dates_with_unresolved_conflicts_none_store():
    assert _renderer()._dates_with_unresolved_conflicts() == set()
```

- [ ] **Step 2: Test failen sehen**

Run: `python -m pytest tests/test_grid_renderer.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.grid_renderer'`.

- [ ] **Step 3: Modul-Gerüst (Header, Imports, Konstanten, Konstruktor, öffentliche Methoden)**

`src/grid_renderer.py` — Anfang:
```python
"""Kalender-/Grid-Rendering der App (Monats-/Wochenansicht, Zelltypen,
Double-Buffer). Eigenständig herausgelöst aus dem App-God-Object (#49).

Tk-nutzend, aber kein src.ui-Import. Datum/View ist NICHT Renderer-Eigentum:
es kommt per refresh(...)/measure_max_width(...)-Parametern; App bleibt die
Quelle (von _navigate/_set_view mutiert)."""

import calendar
import datetime
import platform
import tkinter as tk

from src.time_utils import (
    DAYS_DE, MONTHS_DE,
    calculate_hours, get_week_dates, get_week_label, week_spans_months,
)
from src.holidays_de import get_holidays
from src.tooltip import attach_tooltip
from src.theme import (
    BG, CELL_BG, WEEKEND_BG, ACCENT, TEXT, TEXT_MUTED,
    ENTRY_BG, WEEKEND_ENTRY_BG, WEEKEND_FG,
    HOLIDAY_BG, HOLIDAY_BG_HOVER, HOLIDAY_ACCENT,
    RESERVATION_ACCENT, TODAY_ACCENT,
    CELL_BG_HOVER, WEEKEND_BG_HOVER, ENTRY_BG_HOVER, WEEKEND_ENTRY_BG_HOVER,
    FONT, FONT_BOLD, FONT_TINY, FONT_SMALL, FONT_HEADER, FONT_HEADER_SMALL,
    _should_show_delete_button,
)

# Probe-Label-Geometrie zur Zellgrößen-Messung (aus ui.py übernommen).
PROBE_WIDTH_WIDE = 12
PROBE_WIDTH_NARROW = 8
PROBE_HEIGHT = 3


class GridRenderer:
    def __init__(self, root, storage, settings, reservation_store, conflicts_store,
                 on_cell_click, on_cell_right_click, reservations_active):
        self._root = root
        self._storage = storage
        self._settings = settings
        self._reservation_store = reservation_store
        self._conflicts_store = conflicts_store
        self._on_cell_click = on_cell_click            # (date_str) -> None
        self._on_cell_right_click = on_cell_right_click  # (date_str) -> None
        self._reservations_active = reservations_active  # () -> bool
        # Rendering-State:
        self.grid_container = None
        self._grid_frames = None
        self._active_grid_idx = 0
        self._grid_frame = None
        self._header_label = None
        self._footer_label = None
        self._fixed_width = None
        self._suppress_geometry = False
        self._last_refresh_view = None
        self._last_refresh_columns = None
        # Transienter Datum/View-Stand (von refresh gesetzt):
        self._view_mode = None
        self._year = None
        self._month = None
        self._iso_year = None
        self._current_week = None

    def build_grid(self, parent):
        # Double-Buffer: zwei dauerhafte Frames im selben Grid-Slot. Refresh
        # baut in den inaktiven (versteckt unter dem aktiven), dann lift()
        # tauscht atomar.
        self.grid_container = tk.Frame(parent, bg=BG)
        self.grid_container.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        self.grid_container.rowconfigure(0, weight=1)
        self.grid_container.columnconfigure(0, weight=1)
        self._grid_frames = []
        for _ in range(2):
            f = tk.Frame(self.grid_container, bg=BG)
            f.grid(row=0, column=0, sticky="nsew")
            for col in range(7):
                f.columnconfigure(col, weight=1)
            self._grid_frames.append(f)
        self._grid_frames[0].lift()
        self._active_grid_idx = 0
        self._grid_frame = self._grid_frames[0]

    def attach_labels(self, header_label, footer_label):
        self._header_label = header_label
        self._footer_label = footer_label

    def refresh(self, view_mode, year, month, iso_year, current_week):
        self._view_mode = view_mode
        self._year = year
        self._month = month
        self._iso_year = iso_year
        self._current_week = current_week
        if self._view_mode == "month":
            # FONT_HEADER (16pt) + width=16 — längste Variante "September 2026".
            self._header_label.config(
                text=f"{MONTHS_DE[self._month]} {self._year}",
                font=FONT_HEADER, width=16,
            )
            self._refresh_month()
        else:
            # FONT_HEADER_SMALL (12pt) + width=32 — KW-Variante mit Jahreswechsel.
            self._header_label.config(
                text=get_week_label(self._iso_year, self._current_week),
                font=FONT_HEADER_SMALL, width=32,
            )
            self._refresh_week()
        current_cols = self._visible_day_count()
        view_changed = self._last_refresh_view != self._view_mode
        cols_changed = self._last_refresh_columns != current_cols
        if view_changed or cols_changed:
            self._last_refresh_view = self._view_mode
            self._last_refresh_columns = current_cols
            # Inactive-Frame komplett ersetzen umgeht Tks reqheight-Cache.
            inactive_idx = 1 - self._active_grid_idx
            self._grid_frames[inactive_idx].destroy()
            new_inactive = tk.Frame(self.grid_container, bg=BG)
            new_inactive.grid(row=0, column=0, sticky="nsew")
            for col in range(7):
                new_inactive.columnconfigure(col, weight=1 if col < current_cols else 0)
            self._grid_frames[inactive_idx] = new_inactive
            self._grid_frames[self._active_grid_idx].lift()
            self._root.update_idletasks()
            if not self._suppress_geometry:
                width = max(self._fixed_width or 0, self._root.winfo_reqwidth())
                self._root.geometry(f"{width}x{self._root.winfo_reqheight()}")

    def measure_max_width(self, view_mode, year, month, iso_year, current_week):
        """Pre-warm: rendert alle 4 (view × show_weekend)-Kombinationen einmal
        in den versteckten Backbuffer und merkt die maximale reqwidth intern
        (self._fixed_width). show_weekend wird über _data temporär mutiert
        (kein Disk-Save) und wiederhergestellt; _suppress_geometry verhindert
        den Resize während der Messung. Läuft vor mainloop()."""
        saved_weekend = self._settings.get("show_weekend")
        max_w = 0
        self._suppress_geometry = True
        try:
            for view in ("month", "week"):
                for weekend in (True, False):
                    self._settings._data["show_weekend"] = weekend
                    self._last_refresh_view = None
                    self._last_refresh_columns = None
                    self.refresh(view, year, month, iso_year, current_week)
                    self._root.update_idletasks()
                    w = self._root.winfo_reqwidth()
                    if w > max_w:
                        max_w = w
        finally:
            self._suppress_geometry = False
            self._settings._data["show_weekend"] = saved_weekend
            self._last_refresh_view = None
            self._last_refresh_columns = None
        self._fixed_width = max_w
        return max_w
```

- [ ] **Step 4: Übrige Rendering-Methoden verbatim verschieben**

Aus `src/ui.py` die folgenden Methoden **kopieren** (nicht löschen — das macht Task 2) und in `GridRenderer` einfügen, dabei die **Substitutions-Tabelle** (oben) anwenden:

`_refresh_month`, `_refresh_week`, `_visible_day_count`, `_get_inactive_grid`, `_activate_grid`, `_update_footer`, `_entry_hours`, `_dates_with_unresolved_conflicts`, `_cell_layout_metrics`, `_build_grid_header`, `_build_entry_cell`, `_fmt_slot_line` (static), `_add_reservation_marker`, `_add_delete_button`, `_build_empty_cell`, `_build_day_cell`, `_build_holiday_cell`, `_hover` (static), `_truncate` (static).

Wichtig:
- `_refresh_month` liest jetzt `self._year`/`self._month`; `_refresh_week` liest `self._iso_year`/`self._current_week` (transient von `refresh` gesetzt) — die Tabelle deckt das ab.
- Keine `_build_grid`/`_refresh`/`_measure_max_width`-Kopie (sind oben schon als `build_grid`/`refresh`/`measure_max_width` umgesetzt).
- Importiere in `grid_renderer.py` nur die Theme-/time_utils-Namen, die die verschobenen Methoden tatsächlich nutzen — der Import-Block oben ist die Erwartung; falls eine Methode einen weiteren Namen braucht, ergänzen; ungenutzte entfernen (ruff F401 muss grün sein).

- [ ] **Step 5: `tests/test_ui_hover.py` migrieren**

In `tests/test_ui_hover.py` den Import
```python
from src.ui import App
```
ändern zu
```python
from src.grid_renderer import GridRenderer
```
und im Testkörper `App._hover` durch `GridRenderer._hover` ersetzen (gleiche Aufrufe — `_hover` ist eine staticmethod mit identischer Signatur). Sonst nichts ändern.

- [ ] **Step 6: Tests grün + Lint + Import-Smoke**

Run:
```
python -m pytest tests/test_grid_renderer.py tests/test_ui_hover.py -q
python -m ruff check src/grid_renderer.py tests/test_grid_renderer.py tests/test_ui_hover.py
python -c "import src.grid_renderer"
python -m pytest -q
```
Expected: Helfer- + Hover-Tests grün; Lint sauber (kein F401 in grid_renderer.py); `import src.grid_renderer` ohne Fehler; volle Suite grün (unveränderte Zahl + neue Tests; `ui.py` unverändert lauffähig).

- [ ] **Step 7: Commit**

```
git add src/grid_renderer.py tests/test_grid_renderer.py tests/test_ui_hover.py
git commit -m "feat(ui): GridRenderer-Komponente (Rendering aus App herausgeloest) (#49)"
```

---

### Task 2: `App` verdrahten, Rendering-Methoden + Imports entfernen

**Files:**
- Modify: `src/ui.py` (`__init__`-Wiring; `_refresh`-Shim; ~19 Rendering-Methoden + `self._fixed_width` + Probe-Konstanten entfernen; Imports trimmen)

**Interfaces:**
- Consumes: `GridRenderer` (Task 1).

- [ ] **Step 1: Import ergänzen**

In `src/ui.py` bei den `from src...`-Imports ergänzen:
```python
from src.grid_renderer import GridRenderer
```

- [ ] **Step 2: `__init__`-Wiring**

In `src/ui.py` `__init__`:

(a) Direkt nach der `SyncOrchestrator`-Konstruktion (und vor `self._build_header()`) den Renderer konstruieren:
```python
        self._renderer = GridRenderer(
            self.root, self.storage, self.settings, self.reservation_store,
            self.conflicts_store, self._open_dialog, self._delete_day,
            self._reservations_active,
        )
```

(b) `self._build_grid()` ersetzen durch `self._renderer.build_grid(self.root)`.

(c) Nach `self._build_footer()` (und vor `self._sync.attach_widgets(...)`) ergänzen:
```python
        self._renderer.attach_labels(self.header_label, self.footer_label)
```

(d) `self._fixed_width = self._measure_max_width()` ersetzen durch:
```python
        self._renderer.measure_max_width(
            self.view_mode, self.year, self.month, self.iso_year, self.current_week)
```

(e) Der UpdateBanner-Anker (`lambda: self.grid_container`) → `lambda: self._renderer.grid_container`.

- [ ] **Step 3: `_refresh`-Shim**

In `src/ui.py` die alte `_refresh`-Methode (der ganze Body, ~481-543) ersetzen durch:
```python
    def _refresh(self):
        self._renderer.refresh(
            self.view_mode, self.year, self.month, self.iso_year, self.current_week)
```

- [ ] **Step 4: Rendering-Methoden + `_build_grid` + `_measure_max_width` entfernen**

In `src/ui.py` folgende Methoden **komplett löschen** (sie leben jetzt im Renderer): `_build_grid`, `_measure_max_width`, `_refresh_month`, `_refresh_week`, `_visible_day_count`, `_build_grid_header`, `_build_entry_cell`, `_fmt_slot_line`, `_add_reservation_marker`, `_add_delete_button`, `_build_empty_cell`, `_build_day_cell`, `_build_holiday_cell`, `_get_inactive_grid`, `_activate_grid`, `_update_footer`, `_entry_hours`, `_dates_with_unresolved_conflicts`, `_cell_layout_metrics`, `_hover`, `_truncate`. Außerdem die Modul-Konstanten `PROBE_WIDTH_WIDE`/`PROBE_WIDTH_NARROW`/`PROBE_HEIGHT` (am Dateianfang) entfernen.

**Behalten:** `_refresh` (Shim), `_open_dialog`, `_delete_day`, `_navigate`, `_set_view`, `_update_toggle_style`, `_on_tab_toggle_view`, `_build_header`, `_build_footer`.

- [ ] **Step 5: Ungenutzte Imports trimmen**

Per `python -m ruff check src/ui.py` die jetzt ungenutzten Imports finden und entfernen — erwartbar betroffen: aus `src.theme` viele Zell-Farben/-Fonts (z.B. `CELL_BG`, `WEEKEND_BG`, `ENTRY_BG`, `WEEKEND_ENTRY_BG`, `WEEKEND_FG`, `HOLIDAY_*`, `RESERVATION_ACCENT`, `TODAY_ACCENT`, `*_HOVER`, `FONT_TINY`, `_should_show_delete_button`), aus `src.time_utils` ggf. `DAYS_DE`/`get_week_dates`?/`week_spans_months`/`calculate_hours`, `get_holidays`, ggf. `attach_tooltip`, `calendar`. **Nur tatsächlich ungenutzte entfernen** — Namen, die `_navigate`/`_set_view`/`_open_dialog`/`_delete_day`/`_build_header`/`_build_footer` noch nutzen, bleiben (z.B. `get_week_dates` in `_navigate`, `FONT_HEADER`? nein bleibt im Renderer, `ACCENT`/`BG`/`FONT_FOOTER` in `_build_footer`/`_build_header`, `format_iso_date`/`themed_*` in `_delete_day`). Lint entscheidet.

- [ ] **Step 6: Grep-Kontrolle, Lint, volle Suite, Import-Smoke**

Run:
```
python -m ruff check .
python -m pytest -q
python -c "import src.ui"
python -c "import src.grid_renderer"
python -c "import src.main"
```
Grep-Kontrolle in `src/ui.py`: **keine** der in Step 4 gelöschten Methodennamen mehr als `def` vorhanden; `self.grid_container`/`self.grid_frames`/`self._fixed_width`/`self.header_label`-Schreibzugriffe nur noch dort, wo sie hingehören (header_label/footer_label-Erzeugung in `_build_header`/`_build_footer` bleibt). Es darf **kein** `self._build_grid`/`self._measure_max_width`/`self._refresh_month`/`self._refresh_week`-Aufruf mehr geben.
Expected: Lint sauber; volle Suite grün (unveränderte Zahl); alle Import-Smokes ohne Fehler (kein Circular-Import).

- [ ] **Step 7: Manuelle AC-Verifikation mit Screenshot** *(führt der Controller aus, nicht der Implementer)*

`python -m src.main` starten; Screenshot in **Monats-** und **Wochenansicht**; visuell prüfen: Grid + Wochentags-Header, Entry-/Holiday-/Empty-Zellen, Reservierungs-Marker, Heute-/Konflikt-Rahmen, Footer-Summe, Update-Banner-Position, Weekend-Toggle (5↔7 Spalten), Navigation, Tab-Umschaltung.

- [ ] **Step 8: Commit**

```
git add src/ui.py
git commit -m "refactor(ui): App an GridRenderer verdrahten, Rendering-Methoden entfernen (#49)"
```

---

## Self-Review

**Spec coverage:**
- Modul `GridRenderer` (Konstruktor, build_grid, attach_labels, refresh, measure_max_width, alle Rendering-Methoden, Konstanten): Task 1. ✓
- App-Wiring (Renderer-Konstruktion, _refresh-Shim, build_grid/measure/anchor, Methoden + Imports raus): Task 2. ✓
- Tests (reine Helfer) + Hover-Migration: Task 1. ✓
- AC manuell + Screenshot: Task 2 Step 7. ✓

**Type-Konsistenz:** `GridRenderer(root, storage, settings, reservation_store, conflicts_store, on_cell_click, on_cell_right_click, reservations_active)`; `build_grid(parent)`; `attach_labels(header_label, footer_label)`; `refresh(view_mode, year, month, iso_year, current_week)`; `measure_max_width(view_mode, year, month, iso_year, current_week)`; `App._refresh()` ruft `refresh` mit genau diesen 5 Werten — konsistent. `on_cell_click`/`on_cell_right_click` = `App._open_dialog`/`_delete_day` (beide `(date_str) -> None`); `reservations_active` = `App._reservations_active` (`() -> bool`).

**Platzhalter:** keine.

**Offene Risiken:**
- Transiente Duplikation nach Task 1 (Rendering-Logik in ui.py UND grid_renderer.py) — gewollt, in Task 2 aufgelöst; jeder Commit für sich grün.
- Import-Trim (ui.py + grid_renderer.py) strikt per ruff F401 — keine Namen raten.
- `_refresh`-Shim erhält ALLE bestehenden `self._refresh`-Aufrufer + die als Callback übergebenen `on_refresh=self._refresh`/`on_ok=self._refresh` (SyncOrchestrator/BackgroundTaskRunner) — Signatur `_refresh(self)` bleibt unverändert.
- Höchstes Risiko visuell: Screenshot-Abnahme in Task 2 Step 7 ist Pflicht.
