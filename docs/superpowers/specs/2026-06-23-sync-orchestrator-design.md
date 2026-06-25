# Design: ui.py entflechten — SyncOrchestrator

**Issue:** #49 (Refactor: ui.py God-Object entflechten), **zweiter Extraktions-Schritt**
nach `BackgroundTaskRunner` (PR #70).
**Branch:** `refactor/ui-sync-orchestrator`, gestackt auf `refactor/ui-bg-tasks` (PR #70,
noch nicht gemerged).

**Leitprinzip:** Verhalten unverändert. Eine kohäsive Verantwortlichkeit (Drive-Sync:
manueller Sync, Tray-Sync, Pull-Callbacks, Status-Label, Quit-Push, Fehler-Aufbereitung)
aus `App` in eine eigene, testbare Klasse `SyncOrchestrator` ziehen.

## Ausgangslage

`src/ui.py` ist nach PR #70 bei ~1387 Zeilen. Der Sync-Cluster (~150 Zeilen) ist gut
abgegrenzt, aber in `App` vermengt. Beteiligt:

- Modul-Funktionen: `_classify_sync_error`, `_friendly_sync_message`, `_show_sync_error`
- App-Methoden: `on_sync_pull_success`, `on_sync_pull_error`, `_update_sync_status_label`,
  `_on_sync_clicked`, `_on_manual_sync_done`, `_tray_sync`, `_on_tray_sync_done`,
  `_quit_with_sync_push`

Kopplung: `storage`, `settings`, `conflicts_store`, `base_path`, `root`, der Thread-Helfer
`App._bg.run`, der Render-Callback `App._refresh`, die Widgets `sync_button` /
`sync_status_label` (im **Header** erzeugt) + `_next_button` (Header, für die Pack-Reihenfolge),
und `App._tray` (dynamisch, von `_apply_tray_setting` als einziger Stelle gepflegt).

Cross-Modul-Aufrufer:
- `src/main.py:295/297` ruft `app.on_sync_pull_success()` / `app.on_sync_pull_error(error, tb)`
  — Public-API von `App`, bleibt unverändert.
- `tests/test_ui_sync_errors.py` importiert `_classify_sync_error` / `_friendly_sync_message`
  aus `src.ui`.

## Teil A — Neues Modul `src/sync_orchestrator.py`

Tk-frei auf Modulebene (nutzt `tkinter` nur für `messagebox` / Widget-Configs zur Laufzeit);
keine Google-Imports auf Modulebene (`_run_push_blocking` bleibt Lazy-Import in den Methoden,
`NEWER_REMOTE_VERSION_MSG` Lazy in `_friendly_sync_message`).

### Modul-Funktionen (verbatim aus ui.py verschoben)

`_classify_sync_error(error)`, `_friendly_sync_message(error, tb="")`,
`_show_sync_error(parent, error, tb="", suffix="")` — Logik unverändert. Nötige Imports
ins neue Modul: `from tkinter import messagebox`, `from src.drive import DriveAuthError,
DriveNetworkError`, `from src.theme import themed_showinfo`.

### Zwei reine Helfer (neu, für Testbarkeit)

Heben die einzige Formatierungs-„Logik" aus den sonst reinen Widget-Glue-Methoden heraus —
unit-testbar ohne Tk, Strings byte-identisch zum Bestand:

```python
def _status_text(n_conflicts, last_pull_at):
    """Text fürs Status-Label: Konflikt-Hinweis hat Vorrang, sonst letzter Pull."""
    if n_conflicts > 0:
        return f"⚠ {n_conflicts} Konflikt{'e' if n_conflicts != 1 else ''}"
    return f"✓ {format_iso_date(last_pull_at, fallback='noch nie')}"

def _tray_toast(ok, n_conflicts, error):
    """Toast-Meldung nach Tray-Sync."""
    if not ok:
        return f"Sync fehlgeschlagen:\n{error}"
    if n_conflicts == 0:
        return "Synchronisiert."
    return f"Synchronisiert — {n_conflicts} Konflikt{'e' if n_conflicts != 1 else ''} offen."
```

(`format_iso_date` aus `src.time_utils`.)

### Klasse `SyncOrchestrator`

```python
class SyncOrchestrator:
    def __init__(self, root, storage, settings, conflicts_store, base_path,
                 runner, on_refresh, get_tray):
        self._root = root
        self._storage = storage
        self._settings = settings
        self._conflicts_store = conflicts_store
        self._base_path = base_path
        self._runner = runner            # App._bg, hat .run(fn, on_done)
        self._on_refresh = on_refresh     # App._refresh
        self._get_tray = get_tray         # lambda: app._tray (einzige Quelle bleibt App._tray)
        self._sync_button = None
        self._status_label = None
        self._next_button = None

    def attach_widgets(self, sync_button, status_label, next_button):
        self._sync_button = sync_button
        self._status_label = status_label
        self._next_button = next_button

    # --- public ---
    def on_pull_success(self): ...        # _on_refresh() + update_status_label()
    def on_pull_error(self, error, tb=""):  # _show_sync_error(root, ...) + update_status_label()
    def update_status_label(self): ...    # Sichtbarkeit (enabled) + _status_text(...)
    def on_sync_clicked(self): ...        # Guard + Label "Synchronisiere…" + runner.run(push, _on_manual_done)
    def tray_sync(self): ...              # Guard + runner.run(push, _on_tray_done)
    def push_on_quit(self): ...           # blockierender Push (timeout 5) + _show_sync_error bei Fehler

    # --- intern ---
    def _push(self): ...                  # lazy _run_push_blocking(storage, settings, conflicts_store, base_path, timeout_seconds=15)
    def _on_manual_done(self, result): ... # Fehlerdialog + _on_refresh + update_status_label
    def _on_tray_done(self, result): ...  # _on_refresh + update_status_label + tray.notify(_tray_toast(...))
```

**Verhaltens-Details (1:1 zum Bestand):**
- `update_status_label`: bei `sync_enabled=False` Button+Label `pack_forget` und Text leeren;
  sonst sichtbar machen (Button `before=next_button`, Label `before=sync_button`) und Text via
  `_status_text(conflicts_store.count_unresolved() if conflicts_store else 0, last_pull_at)`.
  Früh-Return wenn `status_label` noch nicht attached (entspricht dem bisherigen
  `hasattr(self, "sync_status_label")`-Guard).
- `on_sync_clicked`: bei `sync_enabled=False` `messagebox.showinfo("Synchronisation",
  "… In den Einstellungen aktivierbar.")` (verbatim) und Return; sonst Label „Synchronisiere…"
  + `runner.run(self._push, self._on_manual_done)`.
- `tray_sync`: bei `sync_enabled=False` Return; sonst `runner.run(self._push, self._on_tray_done)`.
- `_on_tray_done`: `tray = self._get_tray(); if tray is None: return` nach refresh+label;
  sonst `tray.notify(_tray_toast(result.get("ok"), n, result.get("error","?")), title="")`.
- `push_on_quit`: nur wenn `sync_enabled`; `_run_push_blocking(..., timeout_seconds=5)` in
  `try/except`; bei `not ok` `_show_sync_error(root, error, tb, suffix="Lokale Daten bleiben
  erhalten und werden beim nächsten Start synchronisiert.")`. Kein `tray.stop()` (bleibt in App).

## Teil B — Verdrahtung in `App`

`__init__`-Reihenfolge (Orchestrator vor `_build_header`, da dessen Widgets
`command=self._sync.on_sync_clicked` binden; `self._bg` wandert dafür entsprechend nach oben):
```python
self._bg = BackgroundTaskRunner(...)
self._sync = SyncOrchestrator(
    self.root, self.storage, self.settings, self.conflicts_store,
    self.base_path, self._bg, self._refresh, lambda: self._tray,
)
self._build_header()    # sync_button command -> self._sync.on_sync_clicked; KEIN update-Call drin
self._build_grid(); self._build_footer()
self._sync.attach_widgets(self.sync_button, self.sync_status_label, self._next_button)
self._sync.update_status_label()
```

Call-Site-Umbiegungen:
- `_build_header`: `command` des Sync-Buttons → `self._sync.on_sync_clicked`; der bisherige
  `self._update_sync_status_label()`-Aufruf in `_build_header` entfällt (wird nach `attach_widgets`
  in `__init__` gemacht).
- `_set_view`: `self._update_sync_status_label()` → `self._sync.update_status_label()`.
- `on_sync_pull_success` / `on_sync_pull_error` bleiben in `App` als **dünne Delegatoren**
  (`self._sync.on_pull_success()` / `self._sync.on_pull_error(error, tb)`) — `main.py` unverändert.
- `_on_reconcile_done` nutzt `_classify_sync_error` → `from src.sync_orchestrator import
  _classify_sync_error` in `ui.py`.
- `_apply_tray_setting`: Tray-Action „synchronisieren" → `self._sync.tray_sync`; `on_quit`-Lambda
  bleibt `self._quit_with_sync_push`.
- `_quit_with_sync_push` bleibt in `App`, schrumpft zu:
  `self._sync.push_on_quit()` + `if self._tray is not None: self._tray.stop()`.

Entfallen aus `App`: `_update_sync_status_label`, `_on_sync_clicked`, `_on_manual_sync_done`,
`_tray_sync`, `_on_tray_sync_done` und die drei Modul-Funktionen (ins neue Modul). Bleiben:
`on_sync_pull_success`, `on_sync_pull_error`, `_quit_with_sync_push`.

## Tests

- `tests/test_ui_sync_errors.py`: Import auf `from src.sync_orchestrator import _classify_sync_error,
  _friendly_sync_message` umstellen (Logik unverändert → bleibt grün).
- Neu `tests/test_sync_orchestrator.py` (ohne Tk, mit Fakes):
  - `_status_text`: Konflikt-Plural/Singular, „noch nie"-Fallback, ✓-Datum.
  - `_tray_toast`: ok+0, ok+N (Plural/Singular), Fehlerfall.
  - `on_sync_clicked`: `sync_enabled=False` → kein `runner.run` (Fake-Runner zählt); `True` → genau
    ein `run` + Fake-Label-Text „Synchronisiere…".
  - `_on_tray_done`: Fake-Tray bekommt `notify` mit `_tray_toast`-Text; `get_tray()→None` → kein Crash.
  - `push_on_quit`: `sync_enabled=False` → kein `_run_push_blocking` (monkeypatch).

Fakes: `_FakeRunner.run(fn, on_done)` führt `fn` synchron aus und ruft `on_done(result)` direkt
(deterministisch, kein Thread). `_FakeLabel.config(text=...)` merkt sich den Text. `_FakeTray.notify`
merkt sich `(msg, title)`.

## Verifikation (AC 4 — Verhalten unverändert)

- Volle Suite grün, `ruff check .` sauber, Import-Smoke (`import src.ui`, `import src.sync_orchestrator`,
  `import src.main` — kein Circular-Import).
- Manueller App-Smoke: Start + Status-Label, manueller Sync-Klick, Tray-Sync-Toast, Quit-mit-Push,
  Sync-deaktiviert-Hinweis.

## Nicht-Ziele (Folge-PRs)

- `GridRenderer` (Rendering-Extraktion) — der verbleibende große Block.
- Update-Banner-Komponente.
