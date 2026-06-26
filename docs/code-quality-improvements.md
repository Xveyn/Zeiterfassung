# Code-Quality-Improvements

Hygiene-Befunde aus dem Review vom 2026-05-17. Priorisiert nach Hebelwirkung
(großer Effekt / kleiner Aufwand zuerst). Reine Hygiene-Punkte — Kernfunktionalität
ist stabil, das hier sind keine Bug-Reports.

## Duplikate (klein, hoher Effekt)

- [x] **`SYNCED_SETTING_KEYS` doppelt definiert** — erledigt (Issue #48)
  In `settings.py` belassen, aus `sync.py` raus und importiert. Schutz-Test
  `test_sync_reexports_settings_whitelist` erzwingt jetzt Identität (`is`)
  statt nur Wertgleichheit.

- [ ] **`_utc_now_iso()` dreifach kopiert**
  `src/storage.py:6`, `src/settings.py:102`, `src/sync.py:25`. Gehört in
  `src/time_utils.py`, das alle drei eh schon importieren.

- [ ] **Probe-Label-Block in `_refresh_month`/`_refresh_week` ist gespiegelt**
  `src/ui.py:753-764` vs. `:834-841` Zeile für Zeile identisch (außer
  `height=3`/`height=5` und Font-Wahl). Helper
  `_measure_cell_size(parent, height) → (cell_size, entry_time_font, holiday_name_font)`
  würde ~20 Zeilen sparen und beide Refresh-Pfade synchron halten.

- [ ] **Lokale `import tkinter.messagebox as mb`** in `src/ui.py:956, 990, 1007`
  obwohl `from tkinter import messagebox` schon top-level steht. Dead Weight.

## Verdächtige Stellen (Klärung nötig)

- [ ] **`_strip_for_candidate` ist ein No-op**
  `src/sync.py:84-86` ist `{k: v for k, v in item.items()}`, also nur ein
  shallow copy. Der Name impliziert Filter-Logik, die fehlt. Entweder
  Funktion löschen und Callsites auf `dict(...)` ändern, oder fehlende
  Strip-Logik nachziehen. Vorher klären, ob Strip versehentlich entfernt wurde.

- [ ] **`_measure_max_width` greift auf `settings._data` direkt**
  `src/ui.py:403` mutiert die private `_data` der `Settings`-Klasse, um den
  Disk-Save zu umgehen. Sauberer: `settings.set_in_memory(key, value)` in
  der `Settings`-Klasse, damit der Bypass kein Cross-Boundary-Hack ist.

- [ ] **Zirkuläre Imports zwischen `ui` und `main`**
  `src/ui.py:996, 1029` machen `from src.main import _run_push_blocking`
  lazy. `main.py` importiert `from src.ui import App`. Funktioniert nur,
  weil verzögert. `_run_push_blocking` gehört nach `src/sync.py` oder
  einen neuen `src/drive_ops.py` — Cycle strukturell brechen statt durch
  Import-Timing umgehen.

- [ ] **Instance-State über `getattr`-Defaults**
  `src/ui.py:530, 531, 559` lesen `_last_refresh_view`, `_last_refresh_columns`,
  `_suppress_geometry` via `getattr(self, "_x", default)`. In `__init__` als
  echte Attribute initialisieren, damit klar ist welche State die Klasse hält.

## Kleinkram

- [ ] **Magic numbers ohne Kommentar**
  `height=3` (Monat-Probe) vs. `height=5` (Woche-Probe) in `src/ui.py`.
  Konstanten oder mindestens ein Kommentar zur Begründung.

- [ ] **Hardcoded Font in Settings-Dialog**
  `src/dialogs/settings_dialog.py:251` nutzt `("Segoe UI", 8)` direkt
  statt des bereits importierten `FONT_SMALL`. Plattforminkonsistent
  (auf macOS/Linux wäre die Font-Wahl anders).

## Bewusst nicht angefasst

- **`src/ui.py` mit ~1050 Zeilen** ist groß, aber keine echte God-Class. Falls
  die Datei weiterwächst, könnten die Sync-Methoden (`_on_sync_clicked`,
  `on_sync_pull_*`, `_update_sync_status_label`) in ein Mixin — heute nicht
  akut.
- **Fehlender „Abbrechen"-Button im Entry-Dialog** ist Design (Fenster zu =
  Abbrechen), nicht Hygiene.
