# Design: ui.py entflechten — GridRenderer (Abschluss)

**Issue:** #49 (ui.py God-Object entflechten), **vierter und letzter** Extraktions-Schritt
nach `BackgroundTaskRunner` (#70), `SyncOrchestrator` (#71), `UpdateBanner` (#72).
**Branch:** `refactor/ui-grid-renderer`, gestackt auf `refactor/ui-update-banner` (#72).

**Leitprinzip:** Verhalten unverändert. Das Kalender-/Grid-Rendering — der eigentliche
God-Object-Kern (~600 Zeilen) — aus `App` in eine eigene Komponente `GridRenderer`
(`src/grid_renderer.py`) ziehen. Damit ist die ui.py-Entflechtungs-Reihe von #49 durch.

Dies ist die riskanteste Extraktion: visuell sensibel, Double-Buffer + Fenster-Geometrie,
nicht headless-testbar. Daher kleine, gestaffelte Tasks + Screenshot-Abnahme.

## Ausgangslage

`src/ui.py` ist nach #72 bei ~1136 Zeilen. Das Rendering-Cluster ist intern kohäsiv, hängt
aber über drei Kanäle an `App`:
1. **App-State (Stores):** `storage`, `settings`, `reservation_store`, `conflicts_store`.
2. **Datum/View-State:** `view_mode`, `year`, `month`, `iso_year`, `current_week` — von
   `_navigate`/`_set_view` mutiert; **bleibt App-Eigentum**, wird per `refresh(...)` übergeben.
3. **Interaktion:** die Zell-Builder binden `_open_dialog` (Linksklick) und `_delete_day`
   (Rechtsklick) sowie `_reservations_active` — werden als Callbacks injiziert.

Reiner Rendering-State (Double-Buffer-Frames, Geometrie-Tracking, `_fixed_width`) wandert
**vollständig** in den Renderer. `header_label`/`footer_label` werden weiter in `App`
erzeugt (Header/Footer-Chrome), aber vom Renderer beschrieben (per `attach_labels`).

### Methoden-Klassifikation (aus der Coupling-Karte)

- **Pure Rendering → Renderer:** `_refresh`, `_refresh_month`, `_refresh_week`, `_build_grid`,
  `_build_grid_header`, `_build_entry_cell`, `_build_empty_cell`, `_build_day_cell`,
  `_build_holiday_cell`, `_get_inactive_grid`, `_activate_grid`, `_update_footer`,
  `_cell_layout_metrics`, `_add_reservation_marker`, `_add_delete_button`, `_measure_max_width`,
  `_visible_day_count`, `_dates_with_unresolved_conflicts`, `_entry_hours`, `_hover`,
  `_truncate`, `_fmt_slot_line`.
- **Interaktion/Persistenz → bleibt App:** `_open_dialog`, `_delete_day` (Klick-Handler, die
  die Zellen binden — injiziert).
- **Navigation/Chrome → bleibt App:** `_navigate`, `_set_view`, `_update_toggle_style`,
  `_on_tab_toggle_view`, `_build_header`, `_build_footer`.

## Teil A — Neues Modul `src/grid_renderer.py`

Tk-Rendering-Komponente, **kein** `src.ui`-Import. Modul-Konstanten `PROBE_WIDTH_WIDE = 12`,
`PROBE_WIDTH_NARROW = 8`, `PROBE_HEIGHT = 3` ziehen aus `ui.py` mit.

### Konstruktor & öffentliche Schnittstelle

```python
class GridRenderer:
    def __init__(self, root, storage, settings, reservation_store, conflicts_store,
                 on_cell_click, on_cell_right_click, reservations_active):
        self._root = root
        self._storage = storage
        self._settings = settings
        self._reservation_store = reservation_store
        self._conflicts_store = conflicts_store
        self._on_cell_click = on_cell_click            # App._open_dialog (date_str) -> None
        self._on_cell_right_click = on_cell_right_click  # App._delete_day (date_str) -> None
        self._reservations_active = reservations_active  # () -> bool
        # Rendering-State (von build_grid/attach_labels/measure gesetzt):
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

    def build_grid(self, parent):
        """Erzeugt grid_container + die zwei gestapelten Double-Buffer-Frames in parent."""

    def attach_labels(self, header_label, footer_label):
        """Die in App erzeugten Header-/Footer-Labels, die refresh/_update_footer beschreiben."""

    def refresh(self, view_mode, year, month, iso_year, current_week):
        """Der eine Render-Eintritt: setzt header_label (Text/Font/Width je View), rendert in
        den Backbuffer, aktiviert ihn, aktualisiert den Footer, regelt die Fenster-Geometrie."""

    def measure_max_width(self, view_mode, year, month, iso_year, current_week):
        """Probt die 4 Kombinationen (View × show_weekend) im versteckten Backbuffer und merkt
        die maximale reqwidth intern (self._fixed_width). show_weekend wird nach dem Proben
        wiederhergestellt. Vor dem ersten echten refresh aufgerufen."""
```

### Verhaltens-Details (1:1 zum Bestand)

- **Double-Buffer:** `build_grid` legt `grid_container` (mit `rowconfigure(0, weight=1)`,
  `columnconfigure(0, weight=1)`) und zwei `tk.Frame`s an (beide `grid(row=0,col=0,
  sticky="nsew")`), liftet Frame 0, `_active_grid_idx=0`. `_get_inactive_grid` zerstört die
  Kinder des Backbuffers + reset row/col-config; `_activate_grid` liftet + flippt den Index.
  Der View-/Spalten-Wechsel-Sonderfall (Backbuffer komplett neu erzeugen, um Tks
  reqheight-Cache zu leeren) bleibt erhalten.
- **header_label:** `refresh` setzt Text (Monatsname bzw. KW-Label), Font (`FONT_HEADER` 16
  / `FONT_HEADER_SMALL` 12) und Width (16/32) je View — verbatim.
- **Zell-Builder:** binden `self._on_cell_click`/`self._on_cell_right_click` statt der alten
  direkten `App`-Methoden; `_build_day_cell` reicht sie analog als Lambdas an
  `_build_holiday_cell` weiter. `_add_delete_button` bindet `self._on_cell_right_click`.
- **Reservierungen:** `_refresh_month`/`_refresh_week` holen `reservation_store.get_all()` nur
  wenn `self._reservations_active()` True liefert (sonst `{}`).
- **measure_max_width:** mutiert `settings._data["show_weekend"]` temporär (wie der Bestand,
  bewusst nicht via `.set()`), rendert die 4 Kombinationen mit dem übergebenen Datum, merkt
  `_fixed_width`, stellt `show_weekend` wieder her. Strings/Geometrie unverändert.
- Statische Helfer `_hover(frame, bg, *labels)`, `_truncate(text, max_len)`,
  `_fmt_slot_line(slot)` bleiben `@staticmethod`. `_entry_hours(entry)`,
  `_visible_day_count()`, `_dates_with_unresolved_conflicts()` werden Renderer-Methoden
  (lesen `settings`/`conflicts_store`).

## Teil B — Verdrahtung in `App`

### `__init__` (Renderer vor `_build_header`; Labels nach Build; measure/refresh delegiert)

```python
self._renderer = GridRenderer(
    self.root, self.storage, self.settings, self.reservation_store,
    self.conflicts_store, self._open_dialog, self._delete_day,
    self._reservations_active,
)
self._build_header()                       # erzeugt header_label (+ sync/nav chrome)
self._renderer.build_grid(self.root)       # ersetzt das bisherige self._build_grid()
self._build_footer()                       # erzeugt footer_label
self._renderer.attach_labels(self.header_label, self.footer_label)
self._sync.attach_widgets(self.sync_button, self.sync_status_label, self._next_button)
self._sync.update_status_label()
self._apply_always_on_top()
self._apply_tray_setting()
... bindings ...
self._renderer.measure_max_width(
    self.view_mode, self.year, self.month, self.iso_year, self.current_week)
self._refresh()
self._update_banner = UpdateBanner(
    self.root, self.settings, lambda: self._renderer.grid_container)
self._bg.check_update(on_result=self._update_banner.handle_check_result)
self._bg.reconcile_on_start(on_ok=self._refresh)
```

### `_refresh` bleibt als dünner Shim in `App`

Er ist der eine Render-Eintritt für **alle** bestehenden Aufrufer (Navigation, `_set_view`,
`_delete_day`, `_open_dialog`-`on_change`, sowie die Callbacks `on_refresh=self._refresh` in
SyncOrchestrator und `on_ok=self._refresh` in BackgroundTaskRunner):
```python
def _refresh(self):
    self._renderer.refresh(
        self.view_mode, self.year, self.month, self.iso_year, self.current_week)
```

### Weitere Call-Site-Änderungen
- `self._build_grid()` → `self._renderer.build_grid(self.root)`; `App._build_grid` entfällt.
- `self._fixed_width = self._measure_max_width()` → `self._renderer.measure_max_width(...)`
  (App speichert `_fixed_width` nicht mehr — Renderer-intern).
- UpdateBanner-Anker `lambda: self.grid_container` → `lambda: self._renderer.grid_container`.

### Entfernt aus `App`
Alle „Pure Rendering"-Methoden (siehe Klassifikation) + `self._fixed_width` + die
Probe-Konstanten. **Bleibt:** `_refresh` (Shim), `_open_dialog`, `_delete_day`, `_navigate`,
`_set_view`, `_update_toggle_style`, `_on_tab_toggle_view`, `_build_header`, `_build_footer`.

Theme-/`time_utils`-/`holidays_de`-/`tooltip`-Imports in `ui.py`, die nur noch das Rendering
nutzte, per Lint (F401) trimmen; in `grid_renderer.py` neu importieren.

## Tests

- **Migration:** `tests/test_ui_hover.py` → `from src.grid_renderer import GridRenderer`
  (testet `GridRenderer._hover`). Per Grep prüfen, ob weitere Tests auf verschobene Methoden
  zeigen, und migrieren.
- **Neu `tests/test_grid_renderer.py`** (ohne Tk, reine Helfer):
  - `_entry_hours`: Summe über mehrere Slots (`calculate_hours`).
  - `_visible_day_count`: 7 bei `show_weekend=True`, 5 bei `False` (Fake-settings).
  - `_dates_with_unresolved_conflicts`: `conflicts_store.get_all()` liefert eine Liste von
    Dicts `{"key": <iso>, "kind": <str>, "resolved": <bool>}`; die Methode gibt die Menge der
    `key`s zurück, für die `kind == "entry"` **und** `not resolved`. Test: Mix aus
    entry/reservation-kind, resolved/unresolved → nur unresolved entry-keys; `conflicts_store
    = None` → leere Menge.
  - `_truncate`: Clipping + `…`-Suffix; kurzer Text unverändert.
  - `_fmt_slot_line`: `"HH:MM-HH:MM  Kategorie"`-Format.

  Fakes: `_FakeSettings.get(key, default)`; `_FakeConflicts.get_all()` liefert die obige
  Dict-Liste.

## Verifikation (AC — Verhalten unverändert, höchstes Risiko)

- Volle Suite grün, `ruff check .` sauber, Import-Smoke (`import src.ui`,
  `import src.grid_renderer`, `import src.main` — kein Circular-Import).
- **Manueller Smoke mit Screenshot** (Rendering ist nicht headless-testbar):
  App starten, Screenshot in **Monats-** und **Wochenansicht**; visuell prüfen:
  Grid + Wochentags-Header rendern; Entry-/Holiday-/Empty-Zellen; Reservierungs-Marker;
  Heute-Rahmen (blau) / Konflikt-Rahmen (orange); Footer-Summe; Update-Banner-Position;
  Weekend-Toggle (5↔7 Spalten); Vor/Zurück-Navigation; Tab-Umschaltung.

## Abschluss

Mit diesem PR ist die ui.py-Entflechtung von #49 durch: `App` ist ein schlanker Koordinator
über `BackgroundTaskRunner`, `SyncOrchestrator`, `UpdateBanner` und `GridRenderer`, plus die
Interaktions-/Navigations-/Chrome-Schicht.
