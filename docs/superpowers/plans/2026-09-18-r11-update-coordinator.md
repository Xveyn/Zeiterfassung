# R11 UpdateCoordinator Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Den Update-Lebenszyklus (Start-Check, Toast/Banner-Routing, Tray-Check, Anwenden beim Beenden) aus `src/ui.py::App` in eine fünfte, Tk-freie App-Komponente `UpdateCoordinator` ziehen — strikt verhaltensneutral.

**Architecture:** Neues Modul `src/update_coordinator.py` mit der Modulfunktion `route_update_notification` und der Klasse `UpdateCoordinator(settings, runner, banner, get_tray)`, gebaut wie `SyncOrchestrator` (Konstruktor-Injektion, `get_tray` lazy, kein Import von `src.ui`). Der Coordinator baut den `AutoUpdater` (R9) selbst. `App` baut weiter den `UpdateBanner`, hält den Coordinator als `self._updates` und behält den Try/Except-Gurt vor `root.destroy()`.

**Tech Stack:** Python 3.10, Tkinter (nur in `ui.py`), pytest, ruff, pyright 1.1.411.

**Spec:** `docs/superpowers/specs/2026-09-18-r11-update-coordinator-design.md`

## Global Constraints

- Strikt verhaltensneutral: keine Änderung an Texten, Reihenfolgen, Settings-Keys (`last_update_check_at`, `update_toast_shown_version`, `pending_update_path`, `pending_update_sha256`, `prerelease_updates_enabled`) oder Fehlerpfaden.
- Bestehende Test-Assertions bleiben wortgleich; geändert werden nur Aufbau und Aufruf.
- `src/update_coordinator.py` ist Tk-frei (kein `import tkinter`) und vollständig annotiert (Eintrag in `tests/test_type_annotations.py::ANNOTATED_MODULES`).
- `src/update_coordinator.py` importiert `src.ui` nicht.
- Der Gurt `try: … except Exception: logging.getLogger(__name__).exception("Vorbereitetes Update konnte nicht angewendet werden")` bleibt in `App._quit_with_sync_push`, unmittelbar vor `self.root.destroy()`.
- Befehle in PowerShell nie mit `&&` verketten (Windows-Dev-Maschine, PowerShell 5.1); in Git-Bash ist `;` ebenso sicher.
- Mehrzeilige Commit-Messages über eine Temp-Datei (`git commit -F <datei>`), nicht über Heredoc/Here-String im Aufruf.
- Jeder Commit endet mit der Zeile `Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>`.
- Alle Prüfbefehle aus dem Repo-Root: `python -m pytest -q -p no:warnings`, `python -m ruff check .`, `npx --yes pyright@1.1.411`.
- pyright-Erwartung überall: `0 errors, 1 warning` — die eine Warnung ist die bestehende zu `src/build_info.py` (in `version.py`). **Jede weitere Warnung ist ein Befund**: `reportAttributeAccessIssue` steht in `pyproject.toml` global auf `"warning"`, ein Tippfehler in einem Attributnamen (z.B. `self._updates.auto_updaterr`) erscheint dort NUR als Warnung, nicht als Fehler.
- Bewusste, dokumentierte Abweichungen von „verhaltensneutral" (sonst keine): (1) Log-Einträge der umgezogenen Methoden erscheinen im Logfile unter dem Logger `src.update_coordinator` statt `src.ui`; (2) der Gurt in `_quit_with_sync_push` umschließt jetzt auch das Lesen von `pending_update_path` (vorher lag es davor) — fängt also etwas mehr, nie weniger.

---

## File Structure

| Datei | Aktion | Verantwortung |
|---|---|---|
| `src/update_coordinator.py` | Create | `route_update_notification`, `UpdateCoordinator` (Start-Check, Ergebnis-Routing, Tray-Check, Anwenden beim Beenden, Besitz des `AutoUpdater`) |
| `src/ui.py` | Modify | nur noch Wiring: Banner bauen, `self._updates` anlegen/starten, Tray-Eintrag, `auto_updater` an den Dialog, Gurt beim Beenden |
| `tests/test_ui_update_routing.py` → `tests/test_update_coordinator.py` | `git mv` + Modify | Routing-, Check-Ergebnis-, Tray-Check-, Auto-Trigger-Tests gegen den Coordinator; neue Tests für `start` und `on_ready` |
| `tests/test_ui_apply_pending_update.py` → `tests/test_update_coordinator_apply_pending.py` | `git mv` + Modify | `_apply_pending_update`-Tests gegen den Coordinator; neue Tests für `apply_pending_on_quit` |
| `tests/test_ui_update_wiring.py` | Create | die zwei App-seitigen Tests (Tray-Eintrag, Gurt beim Beenden) |
| `tests/test_auto_update.py` | Modify | Integrationstest nutzt `UpdateCoordinator.on_check_result` statt `App._on_update_check_result` |
| `tests/test_type_annotations.py` | Modify | Whitelist-Eintrag |
| `CLAUDE.md`, `src/CLAUDE.md`, Docstrings in `src/self_update.py`, `src/auto_update.py`, `src/dialogs/settings_dialog/tab_updates.py`, `tests/test_self_update.py`, `tests/test_tab_updates_apply.py` | Modify | Verweise auf die neue Komponente |

---

### Task 1: `UpdateCoordinator` anlegen (Tests zuerst umziehen)

In diesem Task entsteht die neue Komponente neben dem unveränderten `App`-Code. Die Tests wechseln ihr Ziel auf den Coordinator; `App` behält vorübergehend seine alten Methoden (Task 2 entfernt sie). Nach dem Task ist die Suite grün.

**Files:**
- Create: `src/update_coordinator.py`
- Create: `tests/test_ui_update_wiring.py`
- Move+Modify: `tests/test_ui_update_routing.py` → `tests/test_update_coordinator.py`
- Move+Modify: `tests/test_ui_apply_pending_update.py` → `tests/test_update_coordinator_apply_pending.py`
- Modify: `tests/test_auto_update.py:56-112`
- Modify: `tests/test_type_annotations.py` (Liste `ANNOTATED_MODULES`)

**Interfaces:**
- Consumes: `src.auto_update.AutoUpdater(settings, runner, on_ready)`; `src.self_update.{apply_linux, apply_windows, discard_download, verify_file}`; `src.updater.{REPO, check_for_update, is_newer, manual_check_toast_text, today_iso, update_toast_text}`; `src.version.installed_release_id`.
- Produces (für Task 2):
  - `route_update_notification(release: Any, tray_active: bool, toast_shown_version: str) -> tuple[str, str | None]`
  - `class UpdateCoordinator(settings, runner, banner, get_tray: Callable[[], _Tray | None])`
  - Attribut `auto_updater: AutoUpdater`
  - `start() -> None`, `on_check_result(release: Any, newer: bool) -> None`, `tray_check() -> None`, `apply_pending_on_quit() -> None`
  - privat: `_on_tray_check_result(release: Any) -> None`, `_apply_pending_update(path: str) -> None`

- [ ] **Step 1: Testdateien verschieben**

```bash
git mv tests/test_ui_update_routing.py tests/test_update_coordinator.py
git mv tests/test_ui_apply_pending_update.py tests/test_update_coordinator_apply_pending.py
```

- [ ] **Step 2: Die zwei App-seitigen Tests nach `tests/test_ui_update_wiring.py` verschieben (Assertions unverändert, Aufbau auf `MagicMock`)**

`test_tray_menu_offers_update_check` aus `tests/test_update_coordinator.py` und `test_quit_with_sync_push_destroys_the_window_even_if_applying_raises` aus `tests/test_update_coordinator_apply_pending.py` **löschen** und in der neuen Datei ablegen. Inhalt von `tests/test_ui_update_wiring.py`:

```python
"""Wie `App` den UpdateCoordinator verdrahtet (R11, Xveyn#123).

Der Update-Lebenszyklus selbst liegt in `src/update_coordinator.py` und wird
in `test_update_coordinator*.py` geprüft. Hier bleibt, was `App` behält: den
Tray-Eintrag und den Gurt vor `root.destroy()`.
"""

from unittest.mock import MagicMock

from src.ui import App


class _FakeSettings:
    def __init__(self, data):
        self._data = data

    def get(self, key):
        return self._data.get(key, "")


def test_tray_menu_offers_update_check():
    """Der Eintrag hängt in derselben actions-Liste wie die anderen
    Tray-Aktionen — damit rendern ihn beide Backends (pystray/NSStatusItem)."""
    fake = MagicMock()
    labels = [label for label, _cb, _vis in App._tray_actions(fake)]
    assert "Nach Updates suchen" in labels
    entry = next(a for a in App._tray_actions(fake) if a[0] == "Nach Updates suchen")
    assert entry[2] is None          # immer sichtbar, kein Settings-Gate
    assert callable(entry[1])


def test_quit_with_sync_push_destroys_the_window_even_if_applying_raises(monkeypatch):
    """F3-Zusage: NICHTS zwischen dem Anwenden und `root.destroy()` darf das
    Beenden aufhalten. Bleibt wider Erwarten doch eine Exception uebrig,
    wird sie geloggt — das Fenster geht trotzdem zu."""
    fake = MagicMock()
    fake.settings = _FakeSettings({"pending_update_path": r"C:\Temp\setup.exe"})
    fake._single_instance = None
    fake._apply_pending_update = MagicMock(
        side_effect=OSError("kein Platz mehr in %TEMP%"))

    App._quit_with_sync_push(fake)

    fake.root.destroy.assert_called_once_with()
```

- [ ] **Step 3: `tests/test_update_coordinator.py` auf den Coordinator umstellen**

(a) Modul-Docstring und Imports ersetzen — der Dateianfang bis einschließlich `class _FakeTray` wird zu:

```python
"""UpdateCoordinator (R11, Xveyn#123): Routing der Update-Benachrichtigung
(Toast vs. Banner vs. schon gesehen), Ergebnis des Start-Checks, Tray-Check
und Auslösen des stillen Downloads.

Bis R11 lagen diese Tests gegen `App`; die Assertions sind beim Umzug
wortgleich geblieben — nur Aufbau und Aufruf haben sich geändert.
"""

from unittest.mock import MagicMock

from src.update_coordinator import UpdateCoordinator, route_update_notification


class _Rel:
    def __init__(self, release_id, is_prerelease=False):
        self.release_id = release_id
        self.version = release_id.split("-pre.")[0]
        self.is_prerelease = is_prerelease


class _FakeSettings:
    def __init__(self, data):
        self._data = data

    def get(self, key):
        return self._data.get(key, "")

    def set(self, key, value):
        self._data[key] = value

    def set_many(self, updates):
        self._data.update(updates)


class _FakeRunner:
    """Stand-in für BackgroundTaskRunner: sammelt Jobs, `flush()` führt sie aus
    wie der echte Runner (fn im Worker, on_done danach im UI-Thread)."""

    def __init__(self):
        self.jobs = []
        self.check_update_calls = []

    def run(self, fn, on_done=None):
        self.jobs.append((fn, on_done))

    def check_update(self, on_result):
        self.check_update_calls.append(on_result)

    def flush(self):
        jobs, self.jobs = self.jobs, []
        for fn, on_done in jobs:
            result = fn()
            if on_done is not None:
                on_done(result)


class _Harness:
    """Die Abhängigkeiten eines UpdateCoordinators unter denselben Namen, unter
    denen die Tests sie bis R11 an `App` fanden — so bleiben die Assertions
    wortgleich. `coordinator` ist das Objekt unter Test."""

    def __init__(self, tray, settings_data):
        self.settings = _FakeSettings(settings_data)
        self._tray = tray
        self._update_banner = MagicMock()
        self._bg = _FakeRunner()
        self.coordinator = UpdateCoordinator(
            self.settings, self._bg, self._update_banner, lambda: self._tray)
        # Stub statt echter Automatik-Logik: die Tests in dieser Datei prüfen
        # Toast/Banner, nicht die Auto-Update-Policy — die hat eigene Tests
        # in test_auto_update.py.
        self._auto_updater = MagicMock()
        self.coordinator.auto_updater = self._auto_updater


class _FakeTray:
    def __init__(self):
        self.messages = []

    def notify(self, message, title="Zeiterfassung"):
        self.messages.append(message)
```

(b) Im Rest der Datei diese Ersetzungen (alle Vorkommen), **in genau dieser Reihenfolge** — wer `ui_module` → `coordinator_module` vor der Import-Zeile ersetzt, erhält `import src.ui as coordinator_module`, und die Tests patchen dann das falsche Modul:

| alt | neu |
|---|---|
| `_route_update_notification(` | `route_update_notification(` |
| `import src.ui as ui_module` | `import src.update_coordinator as coordinator_module` |
| `ui_module` | `coordinator_module` |
| `_FakeApp(` | `_Harness(` |
| `App._on_update_check_result(fake, ` | `fake.coordinator.on_check_result(` |
| `App._tray_check_update(fake)` | `fake.coordinator.tray_check()` |

(c) In `_tray_app` die letzten Zeilen vor `return fake` löschen — die Bindung ist beim Coordinator unnötig:

```python
    # Der Worker-Callback ist eine echte App-Methode: gebunden ans Fake-Objekt
    # läuft im Test derselbe Code wie in der App.
    fake._on_tray_check_update_result = MethodType(
        App._on_tray_check_update_result, fake)
```

Den Docstring von `_tray_app` von „App-Stand-in mit gestubbtem Update-Check." auf „Coordinator-Harness mit gestubbtem Update-Check." ändern.

(d) Den Abschnitt „Auslöser des stillen Downloads" behalten; er prüft danach `fake._auto_updater.maybe_start` (der Stub aus `_Harness`).

(e) Am Dateiende zwei neue Tests anhängen:

```python
# --- Neu mit R11: Verträge, die es bisher nicht als Test gab --------------


def test_start_hands_the_check_result_to_on_check_result():
    """`start()` ersetzt den Aufruf `_bg.check_update(...)` aus
    `App.__init__`: genau ein Check, dessen Ergebnis im Coordinator landet."""
    fake = _Harness(tray=None, settings_data={})

    fake.coordinator.start()

    assert fake._bg.check_update_calls == [fake.coordinator.on_check_result]


def test_the_auto_updater_reports_ready_to_the_banner(monkeypatch):
    """Der Coordinator baut den AutoUpdater (R9) selbst — dessen `on_ready`
    muss beim Banner ankommen, sonst sieht niemand, dass ein vorbereitetes
    Update beim Beenden installiert wird."""
    import src.auto_update as auto_update

    monkeypatch.setattr(auto_update, "supports_self_update", lambda *a, **k: True)
    banner = MagicMock()
    settings = _FakeSettings({
        "auto_update_enabled": True,
        "pending_update_path": r"C:\Temp\Zeiterfassung_Setup-1-ab.exe",
    })
    coordinator = UpdateCoordinator(settings, _FakeRunner(), banner, lambda: None)
    rel = _Rel("1.9.0")

    assert coordinator.auto_updater.maybe_start(rel) == "pending"
    banner.show_ready_to_install.assert_called_once_with(rel)
```

- [ ] **Step 4: `tests/test_update_coordinator_apply_pending.py` auf den Coordinator umstellen**

(a) Dateianfang bis einschließlich `class _FakeApp` ersetzen durch:

```python
"""UpdateCoordinator._apply_pending_update / apply_pending_on_quit: Anwenden
eines vorbereiteten Auto-Updates beim Beenden (Task 9, seit R11 im
Coordinator). Die Assertions sind beim Umzug aus `App` wortgleich geblieben.
"""

import os
import platform
from unittest.mock import MagicMock

from src.update_coordinator import UpdateCoordinator


class _FakeSettings:
    def __init__(self, data):
        self._data = data
        self.set_many_calls = []

    def get(self, key):
        return self._data.get(key, "")

    def set_many(self, updates):
        self.set_many_calls.append(dict(updates))
        self._data.update(updates)


class _FakeApp:
    """Hält die Settings unter dem Namen, unter dem die Tests sie bis R11 an
    `App` fanden; `coordinator` ist das Objekt unter Test."""

    def __init__(self, settings_data):
        self.settings = _FakeSettings(settings_data)
        self.coordinator = UpdateCoordinator(
            self.settings, MagicMock(), MagicMock(), lambda: None)
```

(b) Im Rest der Datei diese Ersetzungen (alle Vorkommen):

| alt | neu |
|---|---|
| `App._apply_pending_update(fake, ` | `fake.coordinator._apply_pending_update(` |
| `"src.ui.apply_windows"` | `"src.update_coordinator.apply_windows"` |
| `"src.ui.apply_linux"` | `"src.update_coordinator.apply_linux"` |
| `logger="src.ui"` | `logger="src.update_coordinator"` |

(c) Am Dateiende zwei neue Tests anhängen:

```python
# --- Neu mit R11: der Einstieg beim Beenden -------------------------------


def test_apply_pending_on_quit_touches_nothing_without_a_pending_update(monkeypatch):
    """Der Normalfall beim Beenden: nichts vorbereitet — dann wird weder
    geleert noch angewendet."""
    fake = _FakeApp({})
    monkeypatch.setattr(
        "src.update_coordinator.apply_windows",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("nicht anwenden")))

    fake.coordinator.apply_pending_on_quit()

    assert fake.settings.set_many_calls == []


def test_apply_pending_on_quit_applies_exactly_the_pending_file(monkeypatch, tmp_path):
    import hashlib
    import sys

    path = tmp_path / "setup.exe"
    content = b"echtes Update"
    path.write_bytes(content)
    fake = _FakeApp({"pending_update_path": str(path),
                     "pending_update_sha256": hashlib.sha256(content).hexdigest()})
    monkeypatch.setattr(platform, "system", lambda: "Windows")
    calls = []
    monkeypatch.setattr(
        "src.update_coordinator.apply_windows",
        lambda exe, setup, pid, restart: calls.append((exe, setup, pid, restart)) or True)

    fake.coordinator.apply_pending_on_quit()

    assert calls == [(sys.executable, str(path), os.getpid(), False)]
```

- [ ] **Step 5: Integrationstest in `tests/test_auto_update.py` umstellen**

Im Test `test_startup_check_and_updates_tab_never_download_twice` (Zeilen 56-112):

- `import src.ui as ui_module` → `import src.update_coordinator as coordinator_module`
- `monkeypatch.setattr(ui_module, "today_iso", lambda: "2026-09-18")` → `monkeypatch.setattr(coordinator_module, "today_iso", lambda: "2026-09-18")`
- Den Block ab `banner = MagicMock()` bis einschließlich `app._auto_updater = updater` ersetzen durch:

```python
    banner = MagicMock()
    coordinator = coordinator_module.UpdateCoordinator(
        settings, runner, banner, lambda: None)
    updater = coordinator.auto_updater
```

- `App._on_update_check_result(app, rel, True)   # Start-Check der App` → `coordinator.on_check_result(rel, True)     # Start-Check der App`
- Den Import `from src.ui import App` am Dateikopf entfernen (danach unbenutzt).
- Den Docstring-Schluss „Beide echten Einstiege, ein gemeinsamer AutoUpdater." bleibt.

- [ ] **Step 6: Whitelist-Eintrag**

In `tests/test_type_annotations.py`, Liste `ANNOTATED_MODULES`, direkt nach `"src/auto_update.py",` einfügen:

```python
    "src/update_coordinator.py",
```

- [ ] **Step 7: Tests laufen lassen — müssen scheitern**

Run: `python -m pytest tests/test_update_coordinator.py tests/test_update_coordinator_apply_pending.py tests/test_auto_update.py tests/test_type_annotations.py -q -p no:warnings`
Expected: `Interrupted: 2 errors during collection` — beide mit `ModuleNotFoundError: No module named 'src.update_coordinator'`. (`test_auto_update.py`/`test_type_annotations.py` kommen dabei nicht zur Ausführung; rot ist es aus dem richtigen Grund.)

- [ ] **Step 8: `src/update_coordinator.py` anlegen**

```python
"""Der Update-Lebenszyklus der App — fünfte App-Komponente (R11, Xveyn#123).

Start-Check, Toast-vs.-Banner-Routing seines Ergebnisses, der manuelle Check
aus dem Tray-Menü und das Anwenden eines still vorbereiteten Updates beim
Beenden. Bis R11 lag das alles in `ui.App`; gebaut ist die Komponente wie
`SyncOrchestrator`: Konstruktor-Injektion, `get_tray` lazy (die einzige Quelle
bleibt `App._tray`), kein Import von `src.ui`.

Einen Schritt weiter als `SyncOrchestrator`: Tk-frei. Den Banner baut `App`
(er braucht `root`, den Renderer und `_open_settings`) und reicht ihn fertig
herein; die Tray-Callbacks marshallt `App` selbst per `root.after`.

Die Auto-Update-Policy (R9) gehört dem `AutoUpdater`, den der Coordinator
baut und als `auto_updater` für den Einstellungsdialog bereithält.

Der Gurt vor `root.destroy()` bleibt bewusst in `App._quit_with_sync_push`:
die Zusage „nichts darf das Beenden aufhalten" gilt dem `destroy()`, und der
gehört der App.
"""

import logging
import os
import platform
import sys
from typing import Any, Callable, Protocol

from src.auto_update import AutoUpdater
from src.self_update import apply_linux, apply_windows, discard_download, verify_file
from src.updater import (
    REPO, check_for_update, is_newer, manual_check_toast_text, today_iso,
    update_toast_text,
)
from src.version import installed_release_id


class _Settings(Protocol):
    def get(self, key: str) -> Any: ...

    def set(self, key: str, value: Any) -> None: ...

    def set_many(self, updates: dict[str, Any]) -> None: ...


class _Runner(Protocol):
    def run(self, fn: Callable[[], Any],
            on_done: Callable[[Any], None] | None = None) -> None: ...

    def check_update(self, on_result: Callable[[Any, bool], None]) -> None: ...


class _Banner(Protocol):
    def show_if_newer(self, release: Any) -> None: ...

    def show_ready_to_install(self, release: Any) -> None: ...


class _Tray(Protocol):
    def notify(self, message: str) -> None: ...


def route_update_notification(release: Any, tray_active: bool,
                              toast_shown_version: str) -> tuple[str, str | None]:
    """Entscheidet zwischen Toast, Banner oder No-op für eine neue Version.

    Verglichen wird die volle Kennung (`release_id`), nicht die Basisversion —
    sonst würde ein zweiter Pre-Release derselben Version (pre.1 -> pre.2)
    als "schon gemeldet" durchfallen."""
    if tray_active:
        if release.release_id == toast_shown_version:
            return "none", None
        return "toast", update_toast_text(release)
    return "banner", None


class UpdateCoordinator:
    """Update-Lebenszyklus der App; alle Methoden laufen im UI-Thread."""

    def __init__(self, settings: _Settings, runner: _Runner, banner: _Banner,
                 get_tray: Callable[[], _Tray | None]) -> None:
        self._settings = settings
        self._runner = runner            # App._bg
        self._banner = banner            # das UpdateBanner-Exemplar der App
        self._get_tray = get_tray        # lambda: App._tray
        # Läuft gerade ein manueller Update-Check aus dem Tray? Blockt den
        # zweiten Klick, damit ein Doppelklick nicht zwei Requests und zwei
        # Toasts auslöst (siehe tray_check).
        self._update_check_running = False
        # Die eine Auto-Update-Policy samt Guard (R9) — der Updates-Tab
        # bekommt dasselbe Exemplar, sonst luden der Start-Check und der
        # Check des Tabs dasselbe Update zweimal.
        self.auto_updater = AutoUpdater(
            settings, runner, on_ready=banner.show_ready_to_install)

    def start(self) -> None:
        """Stößt den Start-Check an (Frequenz-Throttle im Runner)."""
        self._runner.check_update(on_result=self.on_check_result)

    def on_check_result(self, release: Any, newer: bool) -> None:
        """Verarbeitet das Ergebnis des Hintergrund-Update-Checks im UI-Thread."""
        self._settings.set("last_update_check_at", today_iso())
        if not newer:
            return
        tray = self._get_tray()
        action, text = route_update_notification(
            release,
            tray is not None,
            self._settings.get("update_toast_shown_version"),
        )
        # `tray`/`text` sind bei "toast" per Konstruktion gesetzt
        # (route_update_notification liefert "toast" nur mit Tray und Text);
        # die Prüfung macht das für den Typchecker sichtbar.
        if action == "toast" and tray is not None and text is not None:
            tray.notify(text)
            self._settings.set("update_toast_shown_version", release.release_id)
        elif action == "banner":
            self._banner.show_if_newer(release)
        # Derselbe Check, der den Nutzer ueber Toast/Banner informiert, loest
        # bei aktivem Automatik-Schalter zusaetzlich den stillen Hintergrund-
        # Download aus — kein eigener Timer (Design-Regel 1: "vorhandener
        # Update-Check"). Laeuft unabhaengig von der toast/banner-Routing-
        # Entscheidung oben, deshalb hier und nicht in einem der beiden Zweige.
        # Die Policy selbst liegt in `auto_update.AutoUpdater` (R9).
        self.auto_updater.maybe_start(release)

    def tray_check(self) -> None:
        """Manueller Update-Check aus dem Tray-Menü; Ergebnis kommt als Toast.

        Übergeht bewusst den Frequenz-Throttle (`updater.should_check`) des
        Hintergrund-Checks — manuell heißt manuell —, respektiert aber dessen
        Kanal-Einstellung (`prerelease_updates_enabled`).
        """
        if self._get_tray() is None or self._update_check_running:
            return
        self._update_check_running = True
        include_prereleases = bool(self._settings.get("prerelease_updates_enabled"))

        def fn() -> Any:
            try:
                return check_for_update(REPO, include_prereleases)
            except Exception:
                logging.getLogger(__name__).exception(
                    "Manueller Update-Check fehlgeschlagen")
                return None

        self._runner.run(fn, self._on_tray_check_result)

    def _on_tray_check_result(self, release: Any) -> None:
        """Ergebnis des manuellen Checks im UI-Thread: immer ein Toast.

        Das Lauf-Flag wird als Erstes freigegeben — auch im Fehlerfall, sonst
        wäre der Menüpunkt nach einem Netzausfall dauerhaft tot.
        """
        self._update_check_running = False
        installed = installed_release_id()
        if release is not None:
            # Nur eine erfolgreiche Abfrage zählt als „heute geprüft"; sonst
            # schwiege nach einem Fehlversuch auch der Hintergrund-Check.
            self._settings.set("last_update_check_at", today_iso())
            if is_newer(installed, release.release_id):
                # Der Hintergrund-Check soll dieselbe Version nicht gleich
                # nochmal melden (route_update_notification liest den Wert).
                self._settings.set("update_toast_shown_version", release.release_id)
        tray = self._get_tray()
        if tray is not None:
            tray.notify(manual_check_toast_text(installed, release))

    def apply_pending_on_quit(self) -> None:
        """Wendet ein vorbereitetes Update beim Beenden an, falls eines liegt.

        Ein vorbereitetes Update erst hier anwenden — die App macht ohnehin
        zu, der Nutzer verliert keinen angefangenen Eintrag, und der
        Neustart nach dem Update entfaellt. Der Gurt gegen doch noch
        entkommende Exceptions sitzt beim Aufrufer (`App._quit_with_sync_push`,
        direkt vor `root.destroy()`).
        """
        pending = self._settings.get("pending_update_path")
        if pending:
            self._apply_pending_update(pending)

    def _apply_pending_update(self, path: str) -> None:
        """Ein vorbereitetes Update beim Beenden anwenden (best-effort).

        Erneut geprueft wird hier bewusst: zwischen Download und Beenden
        koennen Stunden liegen, und Aufraeum-Tools leeren %TEMP%. Fehlt die
        Datei oder stimmt ihr Hash nicht mehr, faellt der Vorgang still aus —
        der naechste Update-Check beginnt von vorn. Ein Fehlschlag hier darf
        das Beenden NIE aufhalten (der Aufrufer sichert das zusaetzlich ab).

        Gemeldet wird hier NICHTS: die App macht gerade zu, ein Dialog haette
        kein Gegenueber mehr. Jeder Fehlerpfad geht ins Log — und raeumt
        seine Datei weg. Seit `download_dest` jedem Download-Lauf einen
        eigenen Namen gibt, ueberschreibt sie kein spaeterer Lauf mehr; wer
        sie hier liegen laesst, laesst dauerhaft ~65 MB liegen
        (`sweep_appimage_backup` raeumt nur `.old`).
        """
        expected = self._settings.get("pending_update_sha256")
        self._settings.set_many({"pending_update_path": "",
                                 "pending_update_sha256": ""})
        if not os.path.exists(path) or not verify_file(path, expected):
            logging.getLogger(__name__).info(
                "Vorbereitetes Update verworfen (Datei fehlt oder Hash "
                "stimmt nicht)")
            discard_download(path)
            return

        if platform.system() == "Windows":
            # restart=False: wer beendet, will beendet haben — der Helfer
            # installiert, startet die App aber NICHT wieder (Gegenstueck:
            # der Sofort-Weg im Updates-Tab). Linux verhaelt sich unten
            # schon so: `apply_linux` ersetzt nur, ohne `os.execv`.
            if not apply_windows(sys.executable, path, os.getpid(), False):
                # apply_windows hat den Grund bereits geloggt; die Datei
                # bleibt sonst als Leiche im %TEMP%.
                discard_download(path)
            return
        appimage = os.environ.get("APPIMAGE", "")
        if not appimage:
            logging.getLogger(__name__).info(
                "Vorbereitetes Update nicht angewendet: $APPIMAGE ist nicht "
                "gesetzt")
            discard_download(path)
            return
        error = apply_linux(appimage, path)
        if error is not None:
            logging.getLogger(__name__).warning(
                "Vorbereitetes Update nicht angewendet: %s", error)
            discard_download(path)
```

Hinweis zum `toast`-Zweig: `App` rief `self._tray.notify(text)` ohne Prüfung; `route_update_notification` liefert `"toast"` aber nur bei `tray_active=True` und immer mit Text. Die zusätzliche Bedingung ändert kein Verhalten, sie macht die Zusage für pyright sichtbar.

- [ ] **Step 9: Tests laufen lassen — müssen bestehen**

Run: `python -m pytest tests/test_update_coordinator.py tests/test_update_coordinator_apply_pending.py tests/test_ui_update_wiring.py tests/test_auto_update.py tests/test_type_annotations.py tests/test_catch_all_handlers.py -q -p no:warnings`
Expected: PASS (alle).

- [ ] **Step 10: Volle Suite, Lint, Typecheck**

Run: `python -m pytest -q -p no:warnings`, dann `python -m ruff check .`, dann `npx --yes pyright@1.1.411`
Expected: alle Tests grün; `All checks passed!`; pyright `0 errors, 1 warning` (nur die bestehende `build_info`-Warnung). (ui.py ist in diesem Task unverändert; seine alten Update-Methoden sind vorübergehend ungetestet — Task 2 entfernt sie.)

- [ ] **Step 11: Commit**

Commit-Message in eine Temp-Datei schreiben (Inhalt):

```
refactor(update): UpdateCoordinator als Tk-freie Komponente anlegen (R11)

Start-Check, Toast/Banner-Routing, Tray-Check und Anwenden beim Beenden
als `src/update_coordinator.py`, gebaut wie SyncOrchestrator. Die Tests
wechseln ihr Ziel von App auf den Coordinator; ihre Assertions bleiben
wortgleich. App ist in diesem Schritt noch unverändert.

Refs Xveyn/Zeiterfassung#123

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
```

```bash
git add src/update_coordinator.py tests/
git commit -F <temp-datei>
```

---

### Task 2: `App` auf den Coordinator umstellen

**Files:**
- Modify: `src/ui.py` (Imports Z. 16-33, `_route_update_notification` Z. 67-77, `__init__` Z. 115-119 und 189-199, `_open_settings` Z. ~535, `_tray_actions` Z. 638-639, `_tray_check_update`/`_on_tray_check_update_result` Z. 642-681, `_on_update_check_result` Z. 711-732, `_quit_with_sync_push` Z. 980-997, `_apply_pending_update` Z. 1000-1047)
- Modify: `tests/test_ui_update_wiring.py`

**Interfaces:**
- Consumes (aus Task 1): `UpdateCoordinator(settings, runner, banner, get_tray)`, `.start()`, `.tray_check`, `.apply_pending_on_quit()`, `.auto_updater`.
- Produces: `App._updates: UpdateCoordinator`; `App._update_banner` bleibt.

- [ ] **Step 1: Wiring-Tests auf das Zielbild ändern (rot)**

In `tests/test_ui_update_wiring.py`:

(a) Im Gurt-Test die Zeilen

```python
    fake = MagicMock()
    fake.settings = _FakeSettings({"pending_update_path": r"C:\Temp\setup.exe"})
    fake._single_instance = None
    fake._apply_pending_update = MagicMock(
        side_effect=OSError("kein Platz mehr in %TEMP%"))

    App._quit_with_sync_push(fake)

    fake.root.destroy.assert_called_once_with()
```

ersetzen durch (das `settings`-Setup entfällt: App liest den Pfad nicht mehr selbst)

```python
    fake = MagicMock()
    fake._single_instance = None
    fake._updates.apply_pending_on_quit.side_effect = OSError(
        "kein Platz mehr in %TEMP%")

    App._quit_with_sync_push(fake)

    fake._updates.apply_pending_on_quit.assert_called_once_with()
    fake.root.destroy.assert_called_once_with()
```

Danach die nun unbenutzte Klasse `_FakeSettings` samt Leerzeilen aus `tests/test_ui_update_wiring.py` löschen.

(b) Drei neue Tests anhängen:

```python
def test_quit_applies_the_pending_update_before_destroying_the_window():
    """Die Reihenfolge ist die Zusage: erst anwenden, dann `destroy()` —
    umgekehrt hätte `apply_pending_on_quit` kein Gegenüber mehr, und unter
    Windows startet der Helfer erst, wenn die App weg ist."""
    fake = MagicMock()
    fake._single_instance = None
    order = []
    fake._updates.apply_pending_on_quit.side_effect = lambda: order.append("apply")
    fake.root.destroy.side_effect = lambda: order.append("destroy")

    App._quit_with_sync_push(fake)

    assert order == ["apply", "destroy"]


def test_settings_dialog_gets_the_coordinators_auto_updater(monkeypatch):
    """Updates-Tab und Start-Check müssen DENSELBEN AutoUpdater teilen (R9),
    sonst gäbe es wieder zwei Guards. pyright meldet einen Tippfehler an
    dieser Stelle nur als Warnung — deshalb dieser Test."""
    captured = {}
    monkeypatch.setattr("src.ui.open_settings_dialog",
                        lambda *a, **k: captured.update(k))
    fake = MagicMock()

    App._open_settings(fake)

    assert captured["auto_updater"] is fake._updates.auto_updater


def test_tray_update_entry_runs_the_coordinator_check():
    """Der Tray-Eintrag marshallt auf den Tk-Thread (wie alle Einträge) und
    landet beim Coordinator — nicht mehr in einer App-Methode."""
    fake = MagicMock()
    entry = next(a for a in App._tray_actions(fake) if a[0] == "Nach Updates suchen")

    entry[1]()

    fake.root.after.assert_called_once_with(0, fake._updates.tray_check)
```

- [ ] **Step 2: Wiring-Tests laufen lassen — müssen scheitern**

Run: `python -m pytest tests/test_ui_update_wiring.py -q -p no:warnings`
Expected: 4 FAIL, 1 PASS — `apply_pending_on_quit` nicht gerufen (Gurt-Test; Reihenfolge-Test mit `order == ["destroy"]`), `auto_updater` ist `fake._auto_updater` statt `fake._updates.auto_updater`, `after` mit `fake._tray_check_update` statt `fake._updates.tray_check`. `test_tray_menu_offers_update_check` bleibt grün.

- [ ] **Step 3: `src/ui.py` umbauen**

(a) Imports: die Zeilen

```python
from src.version import VERSION, installed_release_id, version_label
```
```python
from src.auto_update import AutoUpdater
from src.self_update import (
    apply_linux, apply_windows, discard_download, verify_file,
)
```
```python
from src.updater import (
    REPO, check_for_update, is_newer, manual_check_toast_text, today_iso,
    update_toast_text,
)
```

ersetzen durch

```python
from src.version import VERSION, version_label
```
```python
from src.update_coordinator import UpdateCoordinator
```

(die `updater`-Zeile entfällt ganz; `from src.update_coordinator import UpdateCoordinator` direkt nach `from src.update_banner import UpdateBanner` einfügen).

(b) Die Modulfunktion `_route_update_notification` (von `def _route_update_notification(` bis einschließlich `return "banner", None`) **samt der zwei folgenden Leerzeilen** löschen — zwischen `_delete_action` und `class App` bleiben danach genau zwei Leerzeilen.

(c) In `App.__init__` diese Zeilen löschen:

```python
        # Läuft gerade ein manueller Update-Check aus dem Tray? Blockt den
        # zweiten Klick, damit ein Doppelklick nicht zwei Requests und zwei
        # Toasts auslöst (siehe _tray_check_update).
        self._update_check_running = False
```

(d) In `App.__init__` den Block

```python
        # Die eine Auto-Update-Policy samt Guard (R9) — der Updates-Tab
        # bekommt dasselbe Exemplar, sonst luden der Start-Check und der
        # Check des Tabs dasselbe Update zweimal.
        self._auto_updater = AutoUpdater(
            self.settings, self._bg,
            on_ready=self._update_banner.show_ready_to_install)
        self._bg.check_update(on_result=self._on_update_check_result)
```

ersetzen durch

```python
        # Update-Lebenszyklus (R11): Start-Check, Toast/Banner, Tray-Check,
        # Anwenden beim Beenden — und der AutoUpdater (R9) für den
        # Einstellungsdialog. Den Banner baut die App, weil er an root und
        # am Renderer hängt; der Coordinator bekommt ihn fertig.
        self._updates = UpdateCoordinator(
            self.settings, self._bg, self._update_banner, lambda: self._tray)
        self._updates.start()
```

(e) In `_open_settings`: `auto_updater=self._auto_updater,` → `auto_updater=self._updates.auto_updater,`

(f) In `_tray_actions`: `lambda: self.root.after(0, self._tray_check_update), None),` → `lambda: self.root.after(0, self._updates.tray_check), None),`

(g) Die Methoden `_tray_check_update`, `_on_tray_check_update_result`, `_on_update_check_result` und `_apply_pending_update` vollständig löschen (jeweils von `def` bis zum Ende des Körpers).

(h) In `_quit_with_sync_push` den Block

```python
        # Ein vorbereitetes Update erst hier anwenden — die App macht ohnehin
        # zu, der Nutzer verliert keinen angefangenen Eintrag, und der
        # Neustart nach dem Update entfaellt.
        pending = self.settings.get("pending_update_path")
        if pending:
            try:
                self._apply_pending_update(pending)
            except Exception:
                # Zweiter Gurt zur Zusage im Docstring von
                # `_apply_pending_update`: NICHTS darf zwischen hier und
                # `root.destroy()` das Beenden aufhalten. Die gerufenen
                # Funktionen sind selbst auf "wirft nie" gebaut — bleibt
                # trotzdem etwas durch (ein Settings-Schreibfehler, ein
                # Plattform-Aufruf, den niemand vorhergesehen hat), landet
                # der Nutzer sonst vor einem Fehler-Popup mit einem Fenster,
                # das nicht mehr zugeht. Geloggt statt geschluckt.
                logging.getLogger(__name__).exception(
                    "Vorbereitetes Update konnte nicht angewendet werden")
        self.root.destroy()
```

ersetzen durch

```python
        # Ein vorbereitetes Update erst hier anwenden (UpdateCoordinator,
        # R11) — die App macht ohnehin zu, der Nutzer verliert keinen
        # angefangenen Eintrag, und der Neustart nach dem Update entfaellt.
        try:
            self._updates.apply_pending_on_quit()
        except Exception:
            # Zweiter Gurt zur Zusage im Docstring von
            # `UpdateCoordinator._apply_pending_update`: NICHTS darf zwischen
            # hier und `root.destroy()` das Beenden aufhalten. Die gerufenen
            # Funktionen sind selbst auf "wirft nie" gebaut — bleibt
            # trotzdem etwas durch (ein Settings-Schreibfehler, ein
            # Plattform-Aufruf, den niemand vorhergesehen hat), landet der
            # Nutzer sonst vor einem Fehler-Popup mit einem Fenster, das nicht
            # mehr zugeht. Der Gurt bleibt hier, weil die Zusage dem
            # `destroy()` gilt, und das gehört der App. Geloggt statt
            # geschluckt.
            logging.getLogger(__name__).exception(
                "Vorbereitetes Update konnte nicht angewendet werden")
        self.root.destroy()
```

Hinweis: vorher lief der `try` nur, wenn `pending_update_path` gesetzt war, und das Lesen des Pfads lag außerhalb. Jetzt läuft immer `apply_pending_on_quit()`, das ohne Pfad sofort zurückkehrt (Test aus Task 1); das Lesen liegt damit innerhalb des Gurts — er fängt etwas mehr, nie weniger (s. Global Constraints).

- [ ] **Step 4: Wiring-Tests laufen lassen — müssen bestehen**

Run: `python -m pytest tests/test_ui_update_wiring.py -q -p no:warnings`
Expected: 5 passed.

- [ ] **Step 5: Reste prüfen**

Run (Git-Bash): `grep -n "_update_check_running\|self\._auto_updater\|self\._apply_pending_update\|def _apply_pending_update\|_on_update_check_result\|_tray_check_update\|_route_update_notification\|today_iso\|installed_release_id" src/ui.py`
Expected: keine Treffer. (Der neue Gurt-Kommentar nennt `` `UpdateCoordinator._apply_pending_update` `` — das Muster ist bewusst so eng, dass er nicht trifft. Den Kommentar NICHT ändern.)

- [ ] **Step 6: Volle Suite, Lint, Typecheck**

Run: `python -m pytest -q -p no:warnings`, `python -m ruff check .`, `npx --yes pyright@1.1.411`
Expected: alle grün; `All checks passed!` (keine unbenutzten Importe mehr); pyright `0 errors, 1 warning` (nur `build_info`).

- [ ] **Step 7: Commit**

Commit-Message (Temp-Datei):

```
refactor(ui): App delegiert den Update-Lebenszyklus an den Coordinator (R11)

App baut weiter den UpdateBanner und hält den Coordinator als `_updates`:
Start-Check über `start()`, Tray-Eintrag über `tray_check`, `auto_updater`
für den Einstellungsdialog, Anwenden beim Beenden über
`apply_pending_on_quit()`. Der Gurt vor `root.destroy()` bleibt in App —
die Zusage gilt dem destroy(). Rund 130 LOC weniger in ui.py.

Refs Xveyn/Zeiterfassung#123

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
```

```bash
git add src/ui.py tests/test_ui_update_wiring.py
git commit -F <temp-datei>
```

---

### Task 3: Dokumentation nachziehen

**Files:**
- Modify: `src/CLAUDE.md` (Z. 23-28 Schichten-Überblick, Z. 37 Überschrift, Z. 106-110 UpdateBanner, Z. ~449 `auto_update.py`-Eintrag, Z. ~540 Tray-Absatz)
- Modify: `CLAUDE.md` (Z. 471 „Update-Weg", Z. 1026 Strukturliste `ui.py`, neuer Eintrag nach `src/auto_update.py`)
- Modify: Docstrings/Kommentare in `src/auto_update.py` (Z. 4, 97), `src/dialogs/settings_dialog/tab_updates.py` (Z. 285, 420, 444), `src/self_update.py` (Z. 317, 347, 433, 501), `tests/test_self_update.py` (Z. 473, 502), `tests/test_tab_updates_apply.py` (Z. 3, 40)
- Modify: `CONTRIBUTING.md` (Z. 67 Komponentenliste, Z. 80 Verzeichnisbaum), `docs/code-quality-improvements.md` (Z. 75-77)

**Interfaces:**
- Consumes: Namen aus Task 1/2 (`UpdateCoordinator`, `update_coordinator.py`, `App._updates`, `on_check_result`, `tray_check`, `apply_pending_on_quit`, `_apply_pending_update`).
- Produces: nichts Code-Wirksames.

- [ ] **Step 1: Verweise in Docstrings/Kommentaren ersetzen**

| Datei | alt | neu |
|---|---|---|
| `src/auto_update.py` Z. 4 | `` App beim Start (`ui.App._on_update_check_result`) `` | `` App beim Start (`UpdateCoordinator.on_check_result`) `` |
| `src/auto_update.py` Z. 97 | `` (`ui.App._apply_pending_update`) `` | `` (`UpdateCoordinator._apply_pending_update`) `` |
| `src/dialogs/settings_dialog/tab_updates.py` Z. 285, 420 | `` `ui.App._apply_pending_update` `` | `` `UpdateCoordinator._apply_pending_update` `` |
| `src/dialogs/settings_dialog/tab_updates.py` Z. 444 | `ui.App._apply_pending_update beim` | `UpdateCoordinator._apply_pending_update beim` |
| `src/self_update.py` Z. 317, 347 | `` `App._apply_pending_update` `` | `` `UpdateCoordinator._apply_pending_update` `` |
| `src/self_update.py` Z. 433, 501 | `` `ui.App._apply_pending_update` `` | `` `UpdateCoordinator._apply_pending_update` `` |
| `tests/test_self_update.py` Z. 473 | `` (`ui.App._apply_pending_update`) `` | `` (`UpdateCoordinator._apply_pending_update`) `` |
| `tests/test_self_update.py` Z. 502 | `` `App._apply_pending_update` laeuft `` | `` `UpdateCoordinator._apply_pending_update` laeuft `` |
| `tests/test_tab_updates_apply.py` Z. 3 | `test_ui_apply_pending_update.py/test_ui_update_routing.py` | `test_update_coordinator_apply_pending.py/test_update_coordinator.py` |
| `tests/test_tab_updates_apply.py` Z. 40 | `test_ui_update_routing.py).` | `test_update_coordinator.py).` |

Danach Kontrolle (Git-Bash): `grep -rn "App._apply_pending_update\|App._on_update_check_result\|_tray_check_update\|test_ui_update_routing\|test_ui_apply_pending_update" src tests --include=*.py`
Expected: keine Treffer.

- [ ] **Step 2: `src/CLAUDE.md` anpassen**

(a) Schichten-Überblick: `   ├─ delegiert an vier Komponenten ▼` → `   ├─ delegiert an fünf Komponenten ▼`; nach der Zeile `   └─ UpdateBanner        (update_banner.py)    — GitHub-Release-Hinweis` die `└─` dieser Zeile zu `├─` machen und anfügen:

```
   └─ UpdateCoordinator   (update_coordinator.py) — Update-Lebenszyklus (Check, Toast/Banner, Tray, Beenden)
```

(b) `## Die vier App-Komponenten und ihre Verträge` → `## Die fünf App-Komponenten und ihre Verträge`

(c) Im Abschnitt „UpdateBanner": `` Persistenz von `last_update_check_at` und Toast-vs.-
Banner-Routing liegen in `ui.py::_on_update_check_result` bzw.
`_route_update_notification(...)`. `` → `` Persistenz von `last_update_check_at` und Toast-vs.-
Banner-Routing liegen im `UpdateCoordinator` (`on_check_result` bzw.
`route_update_notification(...)`). ``

(d) Nach dem Abschnitt „UpdateBanner" (vor `## Threading-Modell`) einen neuen Abschnitt einfügen:

```markdown
### UpdateCoordinator (`update_coordinator.py`)
Der Update-Lebenszyklus der App, seit R11 (Xveyn#123) eigene Komponente statt
rund 130 LOC in `App`. Gebaut wie `SyncOrchestrator` — Konstruktor-Injektion
`(settings, runner, banner, get_tray)`, `get_tray` **lazy** über
`lambda: App._tray`, kein Import von `src.ui` —, aber einen Schritt weiter:
**Tk-frei** und vollständig annotiert (Whitelist in
`test_type_annotations.py`). Den Banner baut `App` (er hängt an `root` und am
Renderer) und reicht ihn fertig herein; die Tray-Callbacks marshallt `App`
selbst per `root.after`.
- `start()` stößt den Start-Check an (`BackgroundTaskRunner.check_update`,
  Frequenz-Throttle dort); `on_check_result(release, newer)` schreibt
  `last_update_check_at`, routet über `route_update_notification` zu Toast oder
  Banner und löst `auto_updater.maybe_start` aus.
- `tray_check()` ist „Nach Updates suchen" aus dem Tray: übergeht den Throttle,
  meldet **immer** einen Toast, blockt den Doppelklick über
  `_update_check_running`.
- `auto_updater` ist der `AutoUpdater` (R9), den der Coordinator selbst baut
  (`on_ready` = `banner.show_ready_to_install`); `App` reicht ihn an
  `open_settings_dialog`.
- `apply_pending_on_quit()` wendet ein vorbereitetes Update beim Beenden an.
  **Der Gurt davor bleibt in `App._quit_with_sync_push`**, direkt vor
  `root.destroy()`: die Zusage „nichts darf das Beenden aufhalten" gilt dem
  `destroy()`, und der gehört der App.
```

(e) Im Eintrag `auto_update.py`: `` Beide
  Auslöser — `App._on_update_check_result` und der Check des Tabs — rufen `` → `` Beide
  Auslöser — `UpdateCoordinator.on_check_result` und der Check des Tabs — rufen ``; außerdem `` `App` baut das einzige `AutoUpdater`-Exemplar `` → `` Der `UpdateCoordinator` baut das einzige `AutoUpdater`-Exemplar `` und den Schlusssatz `Kandidat für
  R11: ein `UpdateCoordinator` als fünfte App-Komponente baut hierauf auf.` löschen.

(f) Tray-Absatz: `` „Nach Updates suchen" (`_tray_check_update`) ist der `` → `` „Nach Updates suchen" (`UpdateCoordinator.tray_check`) ist der ``; `` blockt über `_update_check_running` den Doppelklick `` bleibt.

(g) UpdateBanner-Abschnitt, zweiter Banner-Zustand: `` der `AutoUpdater` (`auto_update.py`, s.u.): `App` reicht ihm `` → `` der `AutoUpdater` (`auto_update.py`, s.u.): der `UpdateCoordinator` reicht ihm `` (die Folgezeile `` `show_ready_to_install` als `on_ready` hinein — der Banner importiert weder `` bleibt).

(h) BackgroundTaskRunner-Abschnitt: `` `trigger_reconcile`. UI-Arbeit (Dialoge/Banner/Refresh) bleibt in App und kommt als Callback. `` → `` `trigger_reconcile`. UI-Arbeit (Dialoge/Banner/Refresh) bleibt beim Aufrufer — `App`, für den Update-Check der `UpdateCoordinator` — und kommt als Callback. ``

(i) „Wo gehört neuer Code hin?": `` `sync_runtime.py`. Reine Persistenz/Logik → der passende Store bzw. `sync.py`/`share.py` `` → `` `sync_runtime.py`. Update-**Ablauf** (Check, Toast/Banner, Anwenden beim Beenden) → `update_coordinator.py`, die Auto-Update-**Policy** → `auto_update.py`. Reine Persistenz/Logik → der passende Store bzw. `sync.py`/`share.py` ``

- [ ] **Step 3: `CLAUDE.md` anpassen**

(a) „Update-Weg": `` angewendet (`ui.App._apply_pending_update`), bleibt die App zu: `` → `` angewendet (`UpdateCoordinator._apply_pending_update`), bleibt die App zu: ``

(b) Strukturliste: `` `App` ist schlanker Koordinator über `GridRenderer`/`BackgroundTaskRunner`/`SyncOrchestrator`/`UpdateBanner` `` → `` `App` ist schlanker Koordinator über `GridRenderer`/`BackgroundTaskRunner`/`SyncOrchestrator`/`UpdateBanner`/`UpdateCoordinator` ``

(c) Strukturliste: nach dem Eintrag `` - `src/auto_update.py` — … `` (endet mit `Updates-Tab weiter (s. „Update-Weg")`) einfügen:

```markdown
- `src/update_coordinator.py` — der Update-**Lebenszyklus** als fünfte
  App-Komponente (R11): Start-Check, Toast-vs.-Banner-Routing, Tray-Check
  „Nach Updates suchen", Anwenden eines vorbereiteten Updates beim Beenden.
  Tk-frei, baut den `AutoUpdater`; der Gurt vor `root.destroy()` bleibt in
  `App` (s. `src/CLAUDE.md`)
```

(e) „Update-Weg", Absatz „Und es lädt immer nur einer": `` `auto_update.AutoUpdater`, das die App besitzt und an den Tab durchreicht, mit `` → `` `auto_update.AutoUpdater`, das der `UpdateCoordinator` besitzt und die App an den Tab durchreicht, mit ``

(d) Im `auto_update.py`-Eintrag der Strukturliste: `Tk-frei, die App besitzt das eine Exemplar und reicht es an den
  Updates-Tab weiter` → `Tk-frei, der `UpdateCoordinator` besitzt das eine Exemplar, die App
  reicht es an den Updates-Tab weiter`

- [ ] **Step 3b: `CONTRIBUTING.md` und `docs/code-quality-improvements.md`**

(a) `CONTRIBUTING.md` Z. 67: `` (`GridRenderer`, `BackgroundTaskRunner`, `SyncOrchestrator`, `UpdateBanner`) `` → `` (`GridRenderer`, `BackgroundTaskRunner`, `SyncOrchestrator`, `UpdateBanner`, `UpdateCoordinator`) ``

(b) `CONTRIBUTING.md` Verzeichnisbaum: nach der Zeile `│   ├── update_banner.py   # GitHub-Release-Hinweis-Banner` einfügen:

```
│   ├── update_coordinator.py # Update-Lebenszyklus: Start-Check, Toast/Banner, Tray-Check, Anwenden beim Beenden
```

(c) `docs/code-quality-improvements.md`: `` `background_tasks.py`, `update_banner.py`). `` → `` `background_tasks.py`, `update_banner.py`, seit R11 `update_coordinator.py`). ``

- [ ] **Step 4: Prüfen**

Kontroll-grep über die Doku (Git-Bash): `grep -rn "App._apply_pending_update\|App._on_update_check_result\|_tray_check_update\|das die App besitzt\|App. reicht ihm" CLAUDE.md src/CLAUDE.md CONTRIBUTING.md docs/code-quality-improvements.md`
Expected: keine Treffer.

Run: `python -m pytest tests/test_claude_md_claims.py -q -p no:warnings`, dann `python -m pytest -q -p no:warnings`, `python -m ruff check .`
Expected: alle grün. Scheitert `test_claude_md_claims.py`, ist eine zitierte Behauptung umformuliert worden — das Muster im Test nachziehen, nicht die Behauptung zurückdrehen.

- [ ] **Step 5: Commit**

Commit-Message (Temp-Datei):

```
docs: UpdateCoordinator in CLAUDE.md, src/CLAUDE.md und Docstrings (R11)

Refs Xveyn/Zeiterfassung#123

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
```

```bash
git add CLAUDE.md CONTRIBUTING.md docs/code-quality-improvements.md src/ tests/
git commit -F <temp-datei>
```

---

### Task 4: Verifikation in der echten App

Kein Code im Repo. Harness ins Scratchpad (nicht ins Repo), Muster wie bei R9.

**Files:**
- Create (Scratchpad): `r11_harness.py`

- [ ] **Step 1: Harness schreiben**

Netz **und** Plattform sind gefälscht: ein fester Release statt der GitHub-API, sonst fehlte ohne Netz oder bei Rate-Limit der Start-Toast still. Toasts und Banner werden auf stdout gespiegelt, damit ein Agent sie prüfen kann. Der Tray-Check geht über den **echten** Menüeintrag aus `_tray_actions`. Das zweite Argument `tray|banner` wählt den Weg; `banner` ist der Default-Nutzerfall (ohne Tray), und nur dort wirkt der an den Coordinator gereichte Banner.

```python
"""R11-Harness. Weg "tray": Start-Check -> Toast, Tray-Menüeintrag -> Toast,
Beenden mit vorbereitetem Update -> apply_windows(restart=False).
Weg "banner" (Default-Nutzer ohne Tray): Start-Check -> Banner.
Netz und Plattform gefälscht; Toast/Banner auf stdout gespiegelt."""
import hashlib, os, sys, tempfile
data, mode = sys.argv[1], sys.argv[2]
os.environ["ZEITERFASSUNG_DATA_DIR"] = data
sys.path.insert(0, os.getcwd())

import src.background_tasks as bt
import src.tray as tray_pkg
import src.update_banner as ub
import src.update_coordinator as uc
import src.ui as ui
from src.settings import Settings
from src.updater import Release

s = Settings(os.path.join(data, "settings.json"))
s.set("minimize_to_tray", mode == "tray")
s.set("last_update_check_at", "")          # Throttle aus, auch bei Wiederholung

REL = Release(version="9.9.9", html_url="https://example.invalid/r", assets=())
bt.check_for_update = lambda *a, **k: REL
uc.check_for_update = lambda *a, **k: REL
bt.installed_release_id = lambda: "0.0.1"
uc.installed_release_id = lambda: "0.0.1"

orig_notify = tray_pkg.TrayIcon.notify
def notify(self, message, title="Zeiterfassung"):
    print("TOAST:", message, flush=True)
    return orig_notify(self, message, title)
tray_pkg.TrayIcon.notify = notify

orig_show = ub.UpdateBanner.show_if_newer
def show_if_newer(self, release):
    print("BANNER:", release.release_id, flush=True)
    return orig_show(self, release)
ub.UpdateBanner.show_if_newer = show_if_newer

FAKE = os.path.join(tempfile.gettempdir(), "r11-fake-setup.exe")
def fake_apply(exe, setup, pid, restart):
    print("APPLY_WINDOWS", setup, "restart=", restart, flush=True)
    os.remove(setup)                       # aufräumen, statt liegen lassen
    return True
uc.apply_windows = fake_apply

orig_init = ui.App.__init__
def init(self, *a, **k):
    orig_init(self, *a, **k)
    def tray_check():
        entry = next(a for a in self._tray_actions() if a[0] == "Nach Updates suchen")
        print("TRAY_CHECK", flush=True)
        entry[1]()                          # echter Menü-Callback (root.after)
    def quit_with_pending():
        with open(FAKE, "wb") as f:
            f.write(b"fake")
        self.settings.set_many({
            "pending_update_path": FAKE,
            "pending_update_sha256": hashlib.sha256(b"fake").hexdigest()})
        print("QUIT", flush=True)
        self._quit_with_sync_push()
    if mode == "tray":
        self.root.after(6000, tray_check)
        self.root.after(12000, quit_with_pending)
    else:
        self.root.after(6000, self._quit_with_sync_push)
ui.App.__init__ = init

from src.main import main
main()
print("MAIN_RETURNED", flush=True)
```

- [ ] **Step 2: Weg „tray" laufen lassen**

Run (Git-Bash, aus dem Repo-Root; `$SP` = Scratchpad):
`rm -rf "$SP/r11data"; mkdir -p "$SP/r11data"; PYTHONIOENCODING=utf-8 timeout 60 python -u "$SP/r11_harness.py" "$SP/r11data" tray`

Expected, in dieser Reihenfolge:
- `TOAST: …9.9.9…` (Start-Check, Tray aktiv)
- `TRAY_CHECK`, danach `TOAST: …` mit dem Ergebnis des manuellen Checks
- `QUIT`, dann `APPLY_WINDOWS …r11-fake-setup.exe restart= False`
- `MAIN_RETURNED`

- [ ] **Step 3: Weg „banner" laufen lassen**

Run: `rm -rf "$SP/r11data"; mkdir -p "$SP/r11data"; PYTHONIOENCODING=utf-8 timeout 60 python -u "$SP/r11_harness.py" "$SP/r11data" banner`

Expected: `BANNER: 9.9.9`, kein `TOAST:`, dann `MAIN_RETURNED`.

- [ ] **Step 4: Log prüfen**

Nach jedem Lauf: stderr ohne Traceback; `grep -n "ERROR\|WARNING" "$SP/r11data/logs/zeiterfassung.log"` → keine Treffer aus `src.update_coordinator` oder `src.ui`.

---

## Abschluss

Nach Task 4: `superpowers:finishing-a-development-branch` (Suite erneut, dann Merge/PR-Menü). PR-Beschreibung: Refs #123 (R11), Hinweis „strikt verhaltensneutral, Assertions wortgleich", kein zusätzlicher Pre-Release über den offenen R9-Gate hinaus.
