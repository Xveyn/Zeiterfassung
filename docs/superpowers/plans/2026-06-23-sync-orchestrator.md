# SyncOrchestrator-Extraktion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Den Drive-Sync-Cluster aus `src/ui.py` in eine eigene, testbare Klasse `SyncOrchestrator` (`src/sync_orchestrator.py`) auslagern — zweiter Schritt der ui.py-Entflechtung (#49).

**Architecture:** Neues Tk-nutzendes, aber Google-frei-auf-Modulebene Modul mit drei moved Fehler-Funktionen, zwei reinen Formatier-Helfern und der Klasse `SyncOrchestrator`. `App` konstruiert sie, hängt die Header-Widgets ein (`attach_widgets`) und delegiert. Verhalten unverändert.

**Tech Stack:** Python 3, Tkinter, pytest.

## Global Constraints

- Verhalten unverändert (reiner Refactor) — UI manuell verifiziert (Status-Label, manueller Sync, Tray-Toast, Quit-Push, Sync-deaktiviert-Hinweis).
- `src/sync_orchestrator.py`: `import tkinter`/`messagebox` auf Modulebene ist OK (stdlib, kein Display nötig zum Import). **Kein** `from src.main import ...` auf Modulebene — `_run_push_blocking` bleibt Lazy-Import **in** der Methode (Circular-Import: `src.main` → `src.ui` → `src.sync_orchestrator`). `NEWER_REMOTE_VERSION_MSG` bleibt Lazy-Import in `_friendly_sync_message` (wie Bestand).
- Strings (Dialog-/Toast-/Label-Texte) byte-identisch zum Bestand.
- Datum intern ISO, UI deutsch via `format_iso_date` (nicht roh).
- Lint: `python -m ruff check .` grün. Tests: `python -m pytest` grün.
- Commit-Messages enden mit `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`.
- PowerShell 5.1: kein `&&`; `;` oder `if ($?) { }`. Match Edits **by content**, nicht by Zeilennummer (`~` = ungefähr).

---

### Task 1: Modul mit Fehler-Funktionen (moved) + reine Helfer + Test-Migration

**Files:**
- Create: `src/sync_orchestrator.py`
- Modify: `src/ui.py` (Funktionen `_classify_sync_error`/`_friendly_sync_message`/`_show_sync_error` ~45-116 entfernen; Import ergänzen)
- Modify: `tests/test_ui_sync_errors.py` (Import-Quelle umstellen)
- Test: `tests/test_sync_orchestrator.py` (neu)

**Interfaces:**
- Produces: `src/sync_orchestrator.py` mit Modul-Funktionen `_classify_sync_error(error)`, `_friendly_sync_message(error, tb="")`, `_show_sync_error(parent, error, tb="", suffix="")` und reinen Helfern `_status_text(n_conflicts, last_pull_at) -> str`, `_tray_toast(ok, n_conflicts, error) -> str`.

- [ ] **Step 1: Neues Modul anlegen (Funktionen + Helfer)**

`src/sync_orchestrator.py`:
```python
"""Drive-Sync-Orchestrierung für die UI: manueller Sync, Tray-Sync,
Pull-Callbacks, Status-Label, Quit-Push und die Fehler-Aufbereitung.

`import tkinter`/`messagebox` auf Modulebene ist unkritisch (stdlib, kein
Display zum Import nötig). `_run_push_blocking` wird LAZY in den Methoden aus
`src.main` importiert — sonst Circular-Import (src.main → src.ui →
src.sync_orchestrator).
"""

import traceback
import tkinter as tk
from tkinter import messagebox

from src.drive import DriveAuthError, DriveNetworkError
from src.theme import themed_showinfo
from src.time_utils import format_iso_date


def _classify_sync_error(error):
    """Kategorisiert einen Google-Sync/Reconcile-Fehler als 'auth', 'network'
    oder 'unknown'. `error` kann eine Exception oder ein String sein (der
    Push-/Reconcile-Pfad liefert str(e), der Pull-Pfad das Exception-Objekt).
    Der abgelaufene/widerrufene Token kommt als invalid_grant durch — sowohl
    bei Drive als auch beim Kalender, da beide denselben OAuth-Token nutzen.
    Ein 403 'insufficient authentication scopes' / 'insufficientPermissions'
    ist ebenfalls ein Auth-Fall (Token deckt einen Scope nicht ab → Re-Consent):
    im String-Pfad fehlt die Typinfo, daher zusätzlich per Textmuster erkannt."""
    text = str(error)
    if (isinstance(error, DriveAuthError)
            or "invalid_grant" in text
            or "expired or revoked" in text
            or "insufficientPermissions" in text
            or "insufficient authentication scopes" in text):
        return "auth"
    if isinstance(error, DriveNetworkError):
        return "network"
    return "unknown"


def _friendly_sync_message(error, tb=""):
    """Mappt einen Drive-Sync-Fehler auf (Titel, Meldung, known) für die Messagebox."""
    from src.sync import NEWER_REMOTE_VERSION_MSG
    if str(error) == NEWER_REMOTE_VERSION_MSG:
        return ("Update erforderlich", NEWER_REMOTE_VERSION_MSG, True)

    kind = _classify_sync_error(error)

    if kind == "auth":
        return (
            "Google-Verbindung erneuern",
            "Die App braucht erneut deine Erlaubnis für Google Drive. Das "
            "passiert, wenn die Verbindung abgelaufen oder widerrufen wurde "
            "oder eine neue Freigabe nötig ist.\n\nBitte öffne die "
            "Einstellungen und klicke auf „Google neu verbinden\" — danach "
            "im Browser die Freigabe bestätigen.",
            True,
        )
    if kind == "network":
        return (
            "Keine Internetverbindung",
            "Die Synchronisation mit Google Drive ist fehlgeschlagen, weil "
            "keine Verbindung zum Internet besteht.\n\nBitte prüfe deine "
            "Verbindung und versuche es erneut.",
            True,
        )
    detail = f"{error}\n\n{tb}" if tb else str(error)
    return (
        "Synchronisation fehlgeschlagen",
        "Bei der Synchronisation mit Google Drive ist ein unerwarteter "
        f"Fehler aufgetreten:\n\n{detail}",
        False,
    )


def _show_sync_error(parent, error, tb="", suffix=""):
    """Zeigt einen Sync-Fehler im passenden Stil: bekannte Fälle (Token/Netz)
    als themed Info-Dialog, unerwartete Fehler als showerror mit Traceback.
    `suffix` wird optional angehängt."""
    title, message, known = _friendly_sync_message(error, tb)
    if suffix:
        message = f"{message}\n\n{suffix}"
    if known:
        themed_showinfo(parent, title, message)
    else:
        messagebox.showerror(title, message)


def _status_text(n_conflicts, last_pull_at):
    """Text fürs Status-Label: offener Konflikt hat Vorrang, sonst letzter Pull."""
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

- [ ] **Step 2: Funktionen aus `ui.py` entfernen + Import ergänzen**

In `src/ui.py` die drei Funktionsdefinitionen `_classify_sync_error` (~45-63), `_friendly_sync_message` (~66-103) und `_show_sync_error` (~106-116) **komplett löschen** (das `_delete_action` darunter bleibt).

Bei den `from src...`-Imports oben ergänzen:
```python
from src.sync_orchestrator import _classify_sync_error, _show_sync_error
```
(`ui.py` nutzt aktuell noch `_show_sync_error` in den Sync-Methoden und `_classify_sync_error` in `_on_reconcile_done`; `_friendly_sync_message` nutzt `ui.py` nicht direkt.)

- [ ] **Step 3: Test-Import migrieren**

In `tests/test_ui_sync_errors.py` die Zeile
```python
from src.ui import _classify_sync_error, _friendly_sync_message
```
ändern zu
```python
from src.sync_orchestrator import _classify_sync_error, _friendly_sync_message
```
(Die `DriveAuthError`/`DriveNetworkError`-Imports im Test aus `src.drive` bleiben.)

- [ ] **Step 4: Tests für die reinen Helfer schreiben**

`tests/test_sync_orchestrator.py`:
```python
"""SyncOrchestrator: reine Formatier-Helfer (ohne Tk)."""

from src.sync_orchestrator import _status_text, _tray_toast


def test_status_text_no_conflicts_shows_last_pull():
    assert _status_text(0, "2026-06-14") == "✓ 14.06.2026"


def test_status_text_never_pulled_fallback():
    assert _status_text(0, None) == "✓ noch nie"


def test_status_text_single_conflict_singular():
    assert _status_text(1, "2026-06-14") == "⚠ 1 Konflikt"


def test_status_text_multiple_conflicts_plural():
    assert _status_text(3, "2026-06-14") == "⚠ 3 Konflikte"


def test_tray_toast_ok_no_conflicts():
    assert _tray_toast(True, 0, None) == "Synchronisiert."


def test_tray_toast_ok_single_conflict():
    assert _tray_toast(True, 1, None) == "Synchronisiert — 1 Konflikt offen."


def test_tray_toast_ok_multiple_conflicts():
    assert _tray_toast(True, 2, None) == "Synchronisiert — 2 Konflikte offen."


def test_tray_toast_failure():
    assert _tray_toast(False, 0, "boom") == "Sync fehlgeschlagen:\nboom"
```

- [ ] **Step 5: Tests + Lint + Import-Smoke**

Run:
```
python -m pytest tests/test_sync_orchestrator.py tests/test_ui_sync_errors.py -q
python -m ruff check src/ui.py src/sync_orchestrator.py tests/test_sync_orchestrator.py tests/test_ui_sync_errors.py
python -c "import src.ui"
python -m pytest -q
```
Expected: Helfer-Tests + migrierte Fehler-Tests grün; Lint sauber; `import src.ui` ohne Fehler; volle Suite grün (unveränderte Zahl + 8 neue Helfer-Tests).

- [ ] **Step 6: Commit**

```
git add src/sync_orchestrator.py src/ui.py tests/test_sync_orchestrator.py tests/test_ui_sync_errors.py
git commit -m "refactor(ui): Sync-Fehler-Funktionen + Formatier-Helfer nach sync_orchestrator (#49)"
```

---

### Task 2: `SyncOrchestrator`-Klasse + Verhaltens-Tests

**Files:**
- Modify: `src/sync_orchestrator.py` (Klasse ergänzen)
- Test: `tests/test_sync_orchestrator.py` (Klassen-Tests ergänzen)

**Interfaces:**
- Consumes: `_status_text`, `_tray_toast`, `_show_sync_error` (Task 1).
- Produces: `SyncOrchestrator(root, storage, settings, conflicts_store, base_path, runner, on_refresh, get_tray)` mit `attach_widgets(sync_button, status_label, next_button)`, `on_pull_success()`, `on_pull_error(error, tb="")`, `update_status_label()`, `on_sync_clicked()`, `tray_sync()`, `push_on_quit()`. `runner` muss `.run(fn, on_done)` haben; `on_refresh` ist eine no-arg Callable; `get_tray` liefert das Tray-Objekt oder None.

- [ ] **Step 1: Klassen-Tests schreiben (RED)**

In `tests/test_sync_orchestrator.py` ergänzen:
```python
from unittest.mock import MagicMock

from src.sync_orchestrator import SyncOrchestrator


class _FakeRunner:
    def __init__(self, execute=True):
        self.calls = []
        self._execute = execute

    def run(self, fn, on_done=None):
        self.calls.append((fn, on_done))
        if self._execute:
            result = fn()
            if on_done is not None:
                on_done(result)


class _FakeLabel:
    def __init__(self):
        self.text = None

    def config(self, text):
        self.text = text


def _orch(sync_enabled=True, execute_runner=False, get_tray=lambda: None,
          conflicts=0, on_refresh=None):
    settings = {"sync_enabled": sync_enabled, "last_pull_at": None}
    settings = MagicMock(get=lambda k, d=None: {"sync_enabled": sync_enabled,
                                                 "last_pull_at": None}.get(k, d))
    conflicts_store = MagicMock(count_unresolved=lambda: conflicts)
    runner = _FakeRunner(execute=execute_runner)
    orch = SyncOrchestrator(
        root=object(), storage=object(), settings=settings,
        conflicts_store=conflicts_store, base_path=".", runner=runner,
        on_refresh=on_refresh or (lambda: None), get_tray=get_tray,
    )
    return orch, runner


def test_on_sync_clicked_disabled_does_not_run(monkeypatch):
    import src.sync_orchestrator as so
    shown = []
    monkeypatch.setattr(so.messagebox, "showinfo",
                        lambda *a, **k: shown.append(a))
    orch, runner = _orch(sync_enabled=False)
    orch.on_sync_clicked()
    assert runner.calls == []
    assert shown  # Hinweis-Dialog gezeigt


def test_on_sync_clicked_enabled_sets_label_and_runs():
    orch, runner = _orch(sync_enabled=True, execute_runner=False)
    label = _FakeLabel()
    orch.attach_widgets(sync_button=object(), status_label=label,
                        next_button=object())
    orch.on_sync_clicked()
    assert label.text == "Synchronisiere…"
    assert len(runner.calls) == 1
    assert runner.calls[0][1] == orch._on_manual_done


def test_on_tray_done_notifies_with_toast():
    tray = MagicMock()
    orch, _ = _orch(get_tray=lambda: tray, conflicts=2)
    # ohne attach_widgets -> update_status_label() no-op (status_label None)
    orch._on_tray_done({"ok": True})
    tray.notify.assert_called_once_with("Synchronisiert — 2 Konflikte offen.",
                                        title="")


def test_on_tray_done_without_tray_does_not_crash():
    orch, _ = _orch(get_tray=lambda: None)
    orch._on_tray_done({"ok": True})  # darf nicht werfen


def test_push_on_quit_disabled_is_noop():
    orch, _ = _orch(sync_enabled=False)
    # darf nicht werfen und nichts pushen (Guard greift vor dem Lazy-Import)
    orch.push_on_quit()
```

Run (RED): `python -m pytest tests/test_sync_orchestrator.py -q` → FAIL (`SyncOrchestrator` fehlt / Methoden fehlen).

- [ ] **Step 2: Klasse implementieren (GREEN)**

In `src/sync_orchestrator.py` ans Ende ergänzen:
```python
class SyncOrchestrator:
    """Kapselt den Drive-Sync der UI. Hält stabile Deps; die Header-Widgets
    werden nach dem Build über attach_widgets nachgereicht, das Tray-Objekt
    lazy über get_tray gelesen (einzige Quelle bleibt App._tray)."""

    def __init__(self, root, storage, settings, conflicts_store, base_path,
                 runner, on_refresh, get_tray):
        self._root = root
        self._storage = storage
        self._settings = settings
        self._conflicts_store = conflicts_store
        self._base_path = base_path
        self._runner = runner          # App._bg, hat .run(fn, on_done)
        self._on_refresh = on_refresh    # App._refresh
        self._get_tray = get_tray        # lambda: App._tray
        self._sync_button = None
        self._status_label = None
        self._next_button = None

    def attach_widgets(self, sync_button, status_label, next_button):
        self._sync_button = sync_button
        self._status_label = status_label
        self._next_button = next_button

    def _conflict_count(self):
        if self._conflicts_store is not None:
            return self._conflicts_store.count_unresolved()
        return 0

    def _push(self):
        from src.main import _run_push_blocking
        return _run_push_blocking(
            self._storage, self._settings, self._conflicts_store,
            self._base_path, timeout_seconds=15,
        )

    def on_pull_success(self):
        """Aus dem UI-Thread nach erfolgreichem Pull."""
        self._on_refresh()
        self.update_status_label()

    def on_pull_error(self, error, tb=""):
        _show_sync_error(self._root, error, tb)
        self.update_status_label()

    def update_status_label(self):
        if self._status_label is None:
            return
        if not self._settings.get("sync_enabled"):
            self._sync_button.pack_forget()
            self._status_label.pack_forget()
            self._status_label.config(text="")
            return
        # Sichtbar machen, falls vorher versteckt. Reihenfolge wie Build-Time.
        if not self._sync_button.winfo_ismapped():
            self._sync_button.pack(side=tk.RIGHT, padx=(4, 0),
                                   before=self._next_button)
            self._status_label.pack(side=tk.RIGHT, padx=(8, 4),
                                    before=self._sync_button)
        self._status_label.config(
            text=_status_text(self._conflict_count(),
                              self._settings.get("last_pull_at")))

    def on_sync_clicked(self):
        if not self._settings.get("sync_enabled"):
            messagebox.showinfo(
                "Synchronisation",
                "Synchronisation ist deaktiviert. In den Einstellungen aktivierbar.")
            return
        self._status_label.config(text="Synchronisiere…")
        self._runner.run(self._push, self._on_manual_done)

    def _on_manual_done(self, result):
        if not result.get("ok"):
            _show_sync_error(self._root, result.get("error", "?"),
                             result.get("tb", ""))
        self._on_refresh()
        self.update_status_label()

    def tray_sync(self):
        if not self._settings.get("sync_enabled"):
            return
        self._runner.run(self._push, self._on_tray_done)

    def _on_tray_done(self, result):
        self._on_refresh()
        self.update_status_label()
        tray = self._get_tray()
        if tray is None:
            return
        tray.notify(
            _tray_toast(result.get("ok"), self._conflict_count(),
                       result.get("error", "?")),
            title="",
        )

    def push_on_quit(self):
        """Blockierender Push beim Beenden (kurzes Timeout). Kein tray.stop()
        (bleibt App-Lifecycle)."""
        if not self._settings.get("sync_enabled"):
            return
        from src.main import _run_push_blocking
        try:
            result = _run_push_blocking(
                self._storage, self._settings, self._conflicts_store,
                self._base_path, timeout_seconds=5,
            )
        except Exception as e:
            result = {"ok": False, "error": e, "tb": traceback.format_exc()}
        if not result.get("ok"):
            _show_sync_error(
                self._root, result.get("error", "?"), result.get("tb", ""),
                suffix="Lokale Daten bleiben erhalten und werden beim "
                       "nächsten Start synchronisiert.",
            )
```

- [ ] **Step 3: Tests grün + Lint**

Run:
```
python -m pytest tests/test_sync_orchestrator.py -q
python -m ruff check src/sync_orchestrator.py tests/test_sync_orchestrator.py
```
Expected: alle Klassen- + Helfer-Tests PASS; Lint sauber.

- [ ] **Step 4: Commit**

```
git add src/sync_orchestrator.py tests/test_sync_orchestrator.py
git commit -m "feat(ui): SyncOrchestrator-Klasse mit Sync-/Tray-/Quit-Logik (#49)"
```

---

### Task 3: `App` verdrahten, alte Methoden entfernen

**Files:**
- Modify: `src/ui.py` (`__init__`, `_build_header`, `_set_view`/`_open_settings`, `_apply_tray_setting`, Sync-Methoden, Delegatoren)

**Interfaces:**
- Consumes: `SyncOrchestrator` (Task 2), `_classify_sync_error` (Task 1).

- [ ] **Step 1: Import ergänzen**

In `src/ui.py` bei den `from src...`-Imports ergänzen:
```python
from src.sync_orchestrator import SyncOrchestrator
```
(Der in Task 1 ergänzte `from src.sync_orchestrator import _classify_sync_error, _show_sync_error` wird in Step 6 getrimmt.)

- [ ] **Step 2: `__init__` — Runner+Orchestrator vor `_build_header`, Widgets nachreichen**

In `src/ui.py` den Block (~206-211)
```python
        self._build_header()
        self._build_grid()
        self._build_footer()
        self._apply_always_on_top()
        self._tray = None
        self._apply_tray_setting()
```
ersetzen durch:
```python
        self._tray = None
        self._bg = BackgroundTaskRunner(
            self._marshal_to_ui, self.settings, self.base_path,
            self.reservation_store, self._reservations_active,
        )
        self._sync = SyncOrchestrator(
            self.root, self.storage, self.settings, self.conflicts_store,
            self.base_path, self._bg, self._refresh, lambda: self._tray,
        )
        self._build_header()
        self._build_grid()
        self._build_footer()
        self._sync.attach_widgets(
            self.sync_button, self.sync_status_label, self._next_button)
        self._sync.update_status_label()
        self._apply_always_on_top()
        self._apply_tray_setting()
```

Und den **alten** `self._bg = BackgroundTaskRunner(...)`-Konstruktor-Block weiter unten (~224-227, direkt vor `self._bg.refresh_token(`) **löschen** — `self._bg` ist jetzt oben konstruiert. Die Task-Start-Aufrufe (`self._bg.refresh_token(...)`, `fetch_sender_email()`, `check_update(...)`, `reconcile_on_start(...)`) bleiben unverändert an ihrer Stelle.

- [ ] **Step 3: `_build_header` — Button-Command + update-Call**

In `src/ui.py` `_build_header`:
- Zeile (~384) `self.sync_button = icon_button(frame, "⟳", self._on_sync_clicked)` → `self.sync_button = icon_button(frame, "⟳", self._sync.on_sync_clicked)`.
- Die Zeile (~386) `self._update_sync_status_label()` **löschen** (initialer Stand kommt jetzt aus `__init__` nach `attach_widgets`).

- [ ] **Step 4: `_set_view`/`_open_settings` — Status-Label-Aufruf umbiegen**

Grep `src/ui.py` nach `self._update_sync_status_label()`. Die verbleibende Stelle (in `_open_settings`, ~506 — nach Schließen des Settings-Dialogs) ersetzen durch `self._sync.update_status_label()`. (Nach diesem Step darf es **keinen** `self._update_sync_status_label(`-Aufruf mehr geben.)

- [ ] **Step 5: Sync-Methoden ersetzen — Delegatoren behalten, Rest löschen**

In `src/ui.py`:

(a) `on_sync_pull_success`/`on_sync_pull_error` zu Delegatoren machen:
```python
    def on_sync_pull_success(self):
        """Public-API für main.py: nach erfolgreichem Pull (UI-Thread)."""
        self._sync.on_pull_success()

    def on_sync_pull_error(self, error, tb=""):
        self._sync.on_pull_error(error, tb)
```

(b) Die Methoden `_update_sync_status_label`, `_on_sync_clicked`, `_on_manual_sync_done`, `_tray_sync`, `_on_tray_sync_done` **komplett löschen**.

(c) `_quit_with_sync_push` schrumpfen zu:
```python
    def _quit_with_sync_push(self):
        """Push zum Drive (falls aktiv) und App komplett beenden. Wird vom
        normalen X-Klick (ohne Tray) und vom Tray-Menü-„Beenden" aufgerufen."""
        self._sync.push_on_quit()
        if self._tray is not None:
            self._tray.stop()
```

- [ ] **Step 6: `_apply_tray_setting` + Import-Trim**

(a) In `_apply_tray_setting` die Tray-Action (~565) `lambda: self.root.after(0, self._tray_sync)` → `lambda: self.root.after(0, self._sync.tray_sync)`. (Der `on_quit`-Lambda `self._quit_with_sync_push` bleibt.)

(b) Import-Trim: `ui.py` nutzt jetzt nur noch `_classify_sync_error` (in `_on_reconcile_done`), nicht mehr `_show_sync_error`. Die Zeile
```python
from src.sync_orchestrator import _classify_sync_error, _show_sync_error
```
zu
```python
from src.sync_orchestrator import _classify_sync_error
```
ändern. (Per Lint/F401 verifizieren — falls doch noch `_show_sync_error` referenziert wird, behalten.)

- [ ] **Step 7: Grep-Kontrolle, Lint, volle Suite, Import-Smoke**

Run:
```
python -m ruff check .
python -m pytest -q
python -c "import src.ui"
python -c "import src.sync_orchestrator"
python -c "import src.main"
```
Grep-Kontrolle in `src/ui.py`: **kein** `_on_sync_clicked`, `_on_manual_sync_done`, `_tray_sync`, `_on_tray_sync_done`, `_update_sync_status_label` mehr; `_quit_with_sync_push`, `on_sync_pull_success`, `on_sync_pull_error` noch da (als Delegatoren/Lifecycle).
Expected: Lint sauber; volle Suite grün (unveränderte Zahl + Task-1/2-Tests); alle Import-Smokes ohne Fehler (kein Circular-Import).

- [ ] **Step 8: Manuelle AC-4-Verifikation** *(führt der Controller aus, nicht der Implementer)*

`python -m src.main` starten und prüfen: Start ohne Fehler, Status-Label sichtbar/Text korrekt (bei aktivem Sync), manueller Sync-Klick (Label „Synchronisiere…" → Ergebnis), Tray-Sync-Toast, Quit-mit-Push, Sync-deaktiviert-Hinweis-Dialog.

- [ ] **Step 9: Commit**

```
git add src/ui.py
git commit -m "refactor(ui): App an SyncOrchestrator verdrahten, alte Sync-Methoden entfernen (#49)"
```

---

## Self-Review

**Spec coverage:**
- Modul + 3 Fehler-Funktionen moved + 2 reine Helfer: Task 1. ✓
- `SyncOrchestrator`-Klasse mit allen Methoden: Task 2. ✓
- App-Wiring (Reihenfolge, attach_widgets, Delegatoren, Tray, Quit-Split, Entfernungen): Task 3. ✓
- Test-Migration + neue Tests: Task 1 (Helfer + Migration), Task 2 (Klasse). ✓
- AC 4 manuell: Task 3 Step 8. ✓

**Type-Konsistenz:** `SyncOrchestrator(root, storage, settings, conflicts_store, base_path, runner, on_refresh, get_tray)`, `attach_widgets(sync_button, status_label, next_button)`, `on_pull_success()`, `on_pull_error(error, tb="")`, `update_status_label()`, `on_sync_clicked()`, `tray_sync()`, `push_on_quit()`, `_on_manual_done`, `_on_tray_done`, `_status_text(n_conflicts, last_pull_at)`, `_tray_toast(ok, n_conflicts, error)` — über alle Tasks konsistent.

**Platzhalter:** keine.

**Offene Risiken:**
- `__init__`-Umstellung: `self._bg` muss exakt einmal konstruiert werden (oben), der alte Konstruktor-Block unten gelöscht — sonst doppelte Konstruktion. Task 3 Step 2 explizit.
- `_on_tray_done` berechnet `_conflict_count()` auch im Fehlerfall (Original nur im ok-Zweig). `count_unresolved()` ist nebenwirkungsfrei → verhaltensäquivalent; bewusst vereinfacht.
- Import-Trim (`_show_sync_error`) per F401 abgesichert (Task 3 Step 6).
