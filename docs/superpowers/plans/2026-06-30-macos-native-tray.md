# Natives macOS-Tray (NSStatusItem) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** macOS-Tray ohne den pystray-Daemon-Thread-Crash (#88) — natives `NSStatusItem` auf dem Main-Thread, hinter der bestehenden `TrayIcon`-Fassade, in ausgelieferten Builds dormant (opt-in) bis zum manuellen Mac-Gate.

**Architecture:** `TrayIcon` wird zur Fassade, die per `platform.system()` ein Backend wählt: Windows → bestehender pystray-Pfad (verbatim in `_PystrayBackend`), macOS → neues `MacTrayBackend` in `src/tray_mac.py` (PyObjC, lazy importiert, kein Thread, keine zweite NSApplication). Ein pures `build_menu_model` speist den macOS-Renderer und die Tests; der Windows-Pfad bleibt inline unverändert.

**Tech Stack:** Python 3.10, Tkinter, pystray (Windows, unverändert), PyObjC (`pyobjc-framework-Cocoa`, macOS-only), pytest.

**Design-Spec:** `docs/superpowers/specs/2026-06-30-macos-native-tray-design.md` — bei Abweichungen gilt die Spec.

## Global Constraints

- **Dependency:** `pyobjc-framework-Cocoa>=10.0; sys_platform == "darwin"` — exakt diese Zeile, mit Marker (hält `pip install` auf Linux/Windows sauber).
- **Lazy PyObjC:** `src/tray_mac.py` importiert PyObjC (`objc`, `AppKit`, `Foundation`) **nur innerhalb von Methoden**, nie auf Modulebene. Modulebene = stdlib + `from src.tray import build_menu_model`. Grund: CI importiert `src.ui → src.tray → (dispatch) src.tray_mac` auf Linux.
- **Callback-Hülle (Klasse-(i)-Schutz):** *jeder* von AppKit aufgerufene Python-Callback (Action, `menuNeedsUpdate_`, Notify) umschließt seinen Body restlos mit `try/except` (swallow + log). Kein Python-Throw darf in einen ObjC-Frame zurück.
- **macOS dormant-Default:** `is_supported()` liefert auf macOS nur True, wenn `ZEIT_MACOS_TRAY=1` gesetzt ist (opt-in für den Mac-Tester). Der Default-an-Flip ist ein **separater PR nach bestandenem Mac-Gate** — NICHT Teil dieses Plans.
- **Windows unangetastet:** der pystray-Pfad wird **verbatim** in `_PystrayBackend` verschoben, kein Verhaltenswechsel. Kein natives Windows-/Linux-Tray.
- **Commit-Typen englisch** (`fix:`/`test:`/`build:`/`ci:`/`docs:`), Body Deutsch ok. Module als `python -m`, Imports absolut (`from src...`).

---

### Task 1: `is_supported()`-Staging + Opt-in

**Files:**
- Modify: `src/tray.py:11-24` (Imports + `is_supported`)
- Test: `tests/test_tray.py` (neu)

**Interfaces:**
- Produces: `is_supported() -> bool`; `_macos_tray_opt_in() -> bool` (liest Env `ZEIT_MACOS_TRAY`).

- [ ] **Step 1: Write the failing test**

`tests/test_tray.py` (neue Datei):

```python
# tests/test_tray.py
import pytest

from src import tray


@pytest.mark.parametrize("system,optin,expected", [
    ("Windows", None, True),
    ("Linux", None, False),
    ("Darwin", None, False),   # dormant-Default
    ("Darwin", "1", True),     # opt-in für den Mac-Tester
])
def test_is_supported_staging(system, optin, expected, monkeypatch):
    monkeypatch.setattr("src.tray.platform.system", lambda: system)
    if optin is None:
        monkeypatch.delenv("ZEIT_MACOS_TRAY", raising=False)
    else:
        monkeypatch.setenv("ZEIT_MACOS_TRAY", optin)
    assert tray.is_supported() is expected
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_tray.py -v`
Expected: FAIL — `Darwin/None` ergibt True (alter Code), erwartet False.

- [ ] **Step 3: Write minimal implementation**

In `src/tray.py` den Kopf (Zeilen 11-13) um `import platform` ergänzen:

```python
import logging
import os
import platform
import threading
```

`is_supported()` (Zeilen 16-24) ersetzen durch:

```python
def _macos_tray_opt_in():
    """macOS-Tray ist bis zum bestandenen Mac-Gate dormant: nur aktiv, wenn der
    Tester ZEIT_MACOS_TRAY=1 setzt. Default-an-Flip = separater PR (s. Spec)."""
    return os.environ.get("ZEIT_MACOS_TRAY") == "1"


def is_supported():
    """Kann auf diesem System ein Tray-Icon gezeigt werden?

    Windows → True. Linux → False (uneinheitlich). macOS → nur mit Opt-in
    (dormant-Default, s. _macos_tray_opt_in). Aufrufer kann unabhängig davon
    `try/except` machen, falls das Backend zur Laufzeit doch fehlschlägt.
    """
    system = platform.system()
    if system == "Windows":
        return True
    if system == "Darwin":
        return _macos_tray_opt_in()
    return False
```

Den **lokalen** `import platform` innerhalb von `is_supported` (alte Zeile 23) damit entfernen.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_tray.py -v`
Expected: PASS (4 Parametrierungen grün).

- [ ] **Step 5: Commit**

```bash
git add src/tray.py tests/test_tray.py
git commit -m "fix(tray): macOS-Tray default off, opt-in via ZEIT_MACOS_TRAY (#88)"
```

---

### Task 2: Pures `build_menu_model`

**Files:**
- Modify: `src/tray.py` (neue Top-Level-Funktion + namedtuple, nach `is_supported`)
- Test: `tests/test_tray.py` (anhängen)

**Interfaces:**
- Consumes: nichts.
- Produces:
  - `MenuEntry = namedtuple("MenuEntry", ["kind", "label", "callback", "visible"])` — `kind` ∈ {`"item"`, `"separator"`}; bei Separator sind `label/callback/visible = None`.
  - `build_menu_model(on_show, on_quit, actions) -> list[MenuEntry]` — `actions` ist Liste von `(label, callback, visible)` (wie `TrayIcon.__init__`). Reihenfolge: Anzeigen, Separator, Aktionen, Separator (nur falls Aktionen), Beenden.

- [ ] **Step 1: Write the failing test**

`tests/test_tray.py` anhängen:

```python
def test_build_menu_model_structure():
    from src.tray import build_menu_model
    show = lambda: None
    quit_ = lambda: None
    vis = lambda: True
    actions = [("Senden", lambda: None, None), ("Sync", lambda: None, vis)]
    model = build_menu_model(show, quit_, actions)
    assert [(e.kind, e.label) for e in model] == [
        ("item", "Anzeigen"),
        ("separator", None),
        ("item", "Senden"),
        ("item", "Sync"),
        ("separator", None),
        ("item", "Beenden"),
    ]
    assert model[0].callback is show
    assert model[-1].callback is quit_
    sync = next(e for e in model if e.label == "Sync")
    assert sync.visible is vis


def test_build_menu_model_no_actions_single_separator():
    from src.tray import build_menu_model
    model = build_menu_model(lambda: None, lambda: None, [])
    assert [e.kind for e in model] == ["item", "separator", "item"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_tray.py -k build_menu_model -v`
Expected: FAIL — `ImportError: cannot import name 'build_menu_model'`.

- [ ] **Step 3: Write minimal implementation**

In `src/tray.py` oben den Import ergänzen und die Funktion direkt nach `is_supported()` einfügen:

```python
from collections import namedtuple
```

```python
MenuEntry = namedtuple("MenuEntry", ["kind", "label", "callback", "visible"])


def build_menu_model(on_show, on_quit, actions):
    """Backend-agnostisches Menü-Modell (pure, ohne AppKit/pystray) aus den
    Tray-Aktionen. Speist den macOS-Renderer (src/tray_mac.py) und die Tests;
    der Windows-Pfad baut sein pystray-Menü weiter inline.

    `actions`: Liste (label, callback, visible). `callback` ist 0-arg und
    marshallt selbst auf den Tk-Thread. `visible` ist None (immer sichtbar) oder
    eine 0-arg-Callable → Bool (dynamische Sichtbarkeit).
    """
    entries = [
        MenuEntry("item", "Anzeigen", on_show, None),
        MenuEntry("separator", None, None, None),
    ]
    for label, callback, visible in actions:
        entries.append(MenuEntry("item", label, callback, visible))
    if actions:
        entries.append(MenuEntry("separator", None, None, None))
    entries.append(MenuEntry("item", "Beenden", on_quit, None))
    return entries
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_tray.py -k build_menu_model -v`
Expected: PASS (2 Tests).

- [ ] **Step 5: Commit**

```bash
git add src/tray.py tests/test_tray.py
git commit -m "feat(tray): pure build_menu_model als Backend-Naht"
```

---

### Task 3: Natives `MacTrayBackend` (`src/tray_mac.py`) + Dependency

**Files:**
- Create: `src/tray_mac.py`
- Modify: `requirements.txt` (eine Zeile)
- Test: `tests/test_tray_mac.py` (neu)

**Interfaces:**
- Consumes: `src.tray.build_menu_model`, `src.tray.MenuEntry`.
- Produces:
  - `_safe(fn) -> None` — ruft 0-arg `fn` auf, schluckt + loggt jede Exception (Klasse-(i)-Schutz).
  - `MacTrayBackend(base_path, on_show, on_quit, actions=None)` mit `.start()`, `.stop()`, `.notify(message, title="Zeiterfassung")`. Gleiche Konstruktor-Signatur wie `_PystrayBackend` (Task 4) — die Fassade instanziiert beide identisch.

- [ ] **Step 1: Add the dependency**

`requirements.txt` am Ende ergänzen:

```
pyobjc-framework-Cocoa>=10.0; sys_platform == "darwin"
```

- [ ] **Step 2: Write the failing test**

`tests/test_tray_mac.py` (neu):

```python
# tests/test_tray_mac.py
import platform
import threading

import pytest


def test_safe_swallows_callback_exceptions():
    """Klasse-(i)-Schutz: _safe lässt keine Python-Exception durch (läuft auf
    jeder Plattform — reines Python)."""
    from src.tray_mac import _safe
    calls = []
    _safe(lambda: calls.append("ok"))
    _safe(lambda: (_ for _ in ()).throw(ValueError("boom")))  # raises
    assert calls == ["ok"]  # zweiter Aufruf wirft NICHT durch


@pytest.mark.skipif(
    platform.system() != "Darwin",
    reason="natives NSStatusItem nur auf macOS (im test-macos-Job)",
)
def test_native_backend_constructs_no_thread_and_tears_down():
    """In-Process-Smoke (nur macOS): Backend unter Tk-Root konstruieren, KEIN
    Thread, Menü gerendert, sauber abbauen. Skippt, wenn der Runner keinen
    Status-Bar-/Display-Zugriff hat (statt falsch rot)."""
    import tkinter
    from src.tray_mac import MacTrayBackend

    try:
        root = tkinter.Tk()
    except Exception:
        pytest.skip("kein Tk/Display auf dem Runner")
    root.withdraw()

    before = threading.active_count()
    backend = MacTrayBackend(
        base_path=".",
        on_show=lambda: None,
        on_quit=lambda: None,
        actions=[("Sync", lambda: None, lambda: True)],
    )
    try:
        try:
            backend.start()
        except Exception:
            pytest.skip("Status-Bar auf dem Runner nicht verfügbar")
        # Bug-Guard (#88): natives Backend startet KEINEN Daemon-Thread
        assert threading.active_count() == before
        # Menü gerendert: Anzeigen | sep | Sync | sep | Beenden = 5 Items
        assert backend._menu.numberOfItems() == 5
    finally:
        backend.stop()
        assert backend._status_item is None  # idempotenter Teardown
        root.destroy()
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/test_tray_mac.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.tray_mac'`. (Auf Windows/Linux skippt der zweite Test ohnehin.)

- [ ] **Step 4: Write the implementation**

`src/tray_mac.py` (neu):

```python
# src/tray_mac.py
"""Natives macOS-Tray (NSStatusItem) — Backend für TrayIcon (#88).

Der frühere pystray-Daemon-Thread treibt auf macOS eine zweite NSApplication an
und kollidiert mit der von Tk getriebenen → Crash beim Fenster-Mappen. Dieses
Backend hängt stattdessen ein NSStatusItem SYNCHRON auf dem Main-Thread an die
geteilte NSApplication, die Tk ohnehin treibt — kein Thread, keine zweite NSApp.

PyObjC wird LAZY in den Methoden importiert: Modulebene bleibt stdlib-only, damit
src.ui → src.tray → (dispatch) src.tray_mac auf Linux/Windows importierbar bleibt
(die CI importiert src.ui). Siehe Spec 2026-06-30-macos-native-tray-design.md.
"""

import logging
import os

from src.tray import build_menu_model

logger = logging.getLogger(__name__)


def _safe(fn):
    """0-arg-Callback aufrufen, ohne dass eine Python-Exception in einen
    ObjC-Frame zurückläuft (Klasse-(i)-Schutz, s. Spec). JEDER von AppKit
    aufgerufene Callback läuft hierdurch."""
    try:
        fn()
    except Exception:
        logger.exception("macOS-Tray-Callback-Fehler (geschluckt)")


class MacTrayBackend:
    """NSStatusItem-Backend mit derselben Lifecycle-API wie _PystrayBackend."""

    def __init__(self, base_path, on_show, on_quit, actions=None):
        self.base_path = base_path
        self._on_show = on_show
        self._on_quit = on_quit
        self._actions = actions or []
        # STARKE Referenzen halten — sonst GC → Icon verschwindet/Crash.
        self._status_item = None
        self._menu = None
        self._delegate = None
        self._dynamic_items = []  # [(NSMenuItem, visible_callable)]

    def _load_image(self):
        from AppKit import NSImage
        png = os.path.join(self.base_path, "assets", "margenheld-icon.png")
        if not os.path.exists(png):
            return None
        image = NSImage.alloc().initByReferencingFile_(png)
        if image is not None:
            image.setSize_((18, 18))  # Menübar-Höhe
        return image

    def start(self):
        from AppKit import (
            NSStatusBar, NSMenu, NSMenuItem, NSVariableStatusItemLength,
        )
        from Foundation import NSObject

        model = build_menu_model(self._on_show, self._on_quit, self._actions)

        callbacks = {}            # representedObject-Key -> 0-arg-Callback
        dynamic_items = []        # [(NSMenuItem, visible_callable)]

        # Delegate LAZY definieren: NSObject-Subklasse braucht Foundation, und
        # die Methoden schließen über callbacks/dynamic_items (free vars).
        class _TrayDelegate(NSObject):
            def invoke_(self, sender):
                cb = callbacks.get(str(sender.representedObject()))
                if cb is not None:
                    _safe(cb)

            def menuNeedsUpdate_(self, menu):
                # live-Sichtbarkeit: visible-Callables vor jedem Öffnen auswerten
                for item, vis in dynamic_items:
                    try:
                        item.setHidden_(not bool(vis()))
                    except Exception:
                        logger.exception(
                            "macOS-Tray-Sichtbarkeit-Fehler (geschluckt)")

        delegate = _TrayDelegate.alloc().init()

        menu = NSMenu.alloc().init()
        menu.setAutoenablesItems_(False)
        menu.setDelegate_(delegate)

        for idx, entry in enumerate(model):
            if entry.kind == "separator":
                menu.addItem_(NSMenuItem.separatorItem())
                continue
            item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
                entry.label, "invoke:", "",
            )
            item.setTarget_(delegate)
            item.setRepresentedObject_(str(idx))
            callbacks[str(idx)] = entry.callback
            if entry.visible is not None:
                dynamic_items.append((item, entry.visible))
            menu.addItem_(item)

        status_item = NSStatusBar.systemStatusBar().statusItemWithLength_(
            NSVariableStatusItemLength)
        image = self._load_image()
        button = status_item.button()
        if image is not None and button is not None:
            button.setImage_(image)
        elif button is not None:
            button.setTitle_("Z")  # Last-Resort, falls PNG fehlt
        status_item.setMenu_(menu)

        # Refs festhalten (Reihenfolge egal; alle bis stop() leben lassen).
        self._delegate = delegate
        self._menu = menu
        self._dynamic_items = dynamic_items
        self._status_item = status_item

    def notify(self, message, title="Zeiterfassung"):
        """best-effort: NSUserNotification (deprecated, aber leichtgewichtig).
        ALLE Fehler geschluckt — Toast ist kosmetisch, Sync bleibt unberührt.

        Kein expliziter Main-Thread-Dispatch: der einzige Aufrufer
        (sync_orchestrator._on_tray_done) ist ein on_done-Callback und läuft
        bereits über _marshal_to_ui auf dem Tk-/Main-Thread (verifiziert)."""
        try:
            from Foundation import (
                NSUserNotification, NSUserNotificationCenter,
            )
            note = NSUserNotification.alloc().init()
            note.setTitle_(title or "Zeiterfassung")
            note.setInformativeText_(message)
            NSUserNotificationCenter.defaultUserNotificationCenter() \
                .deliverNotification_(note)
        except Exception:
            logger.exception("macOS-Tray-Notify fehlgeschlagen (geschluckt)")

    def stop(self):
        """Entfernt das Status-Item und löst die Referenzen. Idempotent."""
        if self._status_item is not None:
            try:
                from AppKit import NSStatusBar
                NSStatusBar.systemStatusBar().removeStatusItem_(
                    self._status_item)
            except Exception:
                logger.exception("macOS-Tray stop fehlgeschlagen")
        self._status_item = None
        self._menu = None
        self._delegate = None
        self._dynamic_items = []
```

> **Hinweis (unverifiziert bis Mac-Gate):** Exakte PyObjC-Selektor-Signaturen
> (`invoke:` als `b"v@:@"`, `menuNeedsUpdate:`), Closure-Verhalten der
> Delegate-Methoden und ob Tks Runloop das Menü serviced, werden erst auf einem
> Mac final bestätigt (Klasse-(ii), s. Spec). Der Code ist die vorgeschlagene
> Implementierung; bei Abweichung auf dem Mac nachziehen.

- [ ] **Step 5: Run test to verify it passes (lokal)**

Run: `pytest tests/test_tray_mac.py -v`
Expected: `test_safe_swallows_callback_exceptions` PASS; der native Smoke `SKIPPED` (non-Darwin). Zusätzlich Import prüfen:
Run: `python -c "import src.tray_mac; print('import ok')"`
Expected: `import ok` (Modul lädt ohne PyObjC, weil lazy).

- [ ] **Step 6: Commit**

```bash
git add src/tray_mac.py tests/test_tray_mac.py requirements.txt
git commit -m "feat(tray): natives macOS NSStatusItem-Backend (dormant, #88)"
```

---

### Task 4: `TrayIcon`-Fassade + Backend-Dispatch

**Files:**
- Modify: `src/tray.py` (TrayIcon → Fassade; bestehende pystray-Logik → `_PystrayBackend`; neu `_select_backend`)
- Test: `tests/test_tray.py` (anhängen)

**Interfaces:**
- Consumes: `MacTrayBackend` (Task 3, lazy importiert), `_PystrayBackend` (hier).
- Produces:
  - `_select_backend(system) -> type | None` — `"Windows"` → `_PystrayBackend`, `"Darwin"` → `MacTrayBackend`, sonst `None`.
  - `_PystrayBackend(base_path, on_show, on_quit, actions=None)` — die heutige `TrayIcon`-Implementierung, verbatim.
  - `TrayIcon(base_path, on_show, on_quit, actions=None)` — Fassade: `start()` wählt+instanziiert+startet das Backend, `stop()`/`notify()` delegieren. Öffentliche API unverändert (ui.py/sync_orchestrator nutzen sie weiter).

- [ ] **Step 1: Write the failing test**

`tests/test_tray.py` anhängen:

```python
def test_select_backend_dispatch():
    from src.tray import _select_backend, _PystrayBackend
    from src.tray_mac import MacTrayBackend
    assert _select_backend("Windows") is _PystrayBackend
    assert _select_backend("Darwin") is MacTrayBackend
    assert _select_backend("Linux") is None


def test_facade_instantiates_and_delegates(monkeypatch):
    """Fassade wählt das Backend, instanziiert mit denselben Args und delegiert
    start/stop/notify — plattformunabhängig über ein Fake-Backend."""
    from src import tray

    seen = {}

    class FakeBackend:
        def __init__(self, base_path, on_show, on_quit, actions=None):
            seen["init"] = (base_path, on_show, on_quit, actions)

        def start(self):
            seen["start"] = True

        def stop(self):
            seen["stop"] = True

        def notify(self, message, title="Zeiterfassung"):
            seen["notify"] = (message, title)

    monkeypatch.setattr("src.tray._select_backend", lambda system: FakeBackend)

    show, quit_ = (lambda: None), (lambda: None)
    acts = [("Sync", lambda: None, None)]
    icon = tray.TrayIcon("base", on_show=show, on_quit=quit_, actions=acts)
    icon.start()
    assert seen["init"] == ("base", show, quit_, acts)
    assert seen["start"] is True
    icon.notify("hallo")
    assert seen["notify"] == ("hallo", "Zeiterfassung")
    icon.stop()
    assert seen["stop"] is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_tray.py -k "select_backend or facade" -v`
Expected: FAIL — `cannot import name '_select_backend' / '_PystrayBackend'`.

- [ ] **Step 3: Refactor `src/tray.py`**

a) Die **bestehende** `class TrayIcon` in `class _PystrayBackend` umbenennen — Body **unverändert** (start/stop/notify/_load_image/_wrap_action/_wrap_visible/_notify_with_icon bleiben wortgleich). Nur die Zeile `class TrayIcon:` → `class _PystrayBackend:` und im Docstring „pystray-Backend (Windows)" vermerken.

b) Direkt nach `is_supported()`/`build_menu_model` die Dispatch-Funktion einfügen:

```python
def _select_backend(system):
    """Backend-Klasse nach Plattform. macOS lazy, damit PyObjC nicht in den
    Linux/Windows-Importpfad gerät."""
    if system == "Windows":
        return _PystrayBackend
    if system == "Darwin":
        from src.tray_mac import MacTrayBackend
        return MacTrayBackend
    return None
```

c) Eine **neue** schlanke `TrayIcon`-Fassade ans Dateiende anfügen:

```python
class TrayIcon:
    """Plattform-Fassade: wählt per platform.system() das Backend
    (_PystrayBackend auf Windows, MacTrayBackend auf macOS) und delegiert.
    Öffentliche API (start/stop/notify) unverändert."""

    def __init__(self, base_path, on_show, on_quit, actions=None):
        self.base_path = base_path
        self._on_show = on_show
        self._on_quit = on_quit
        self._actions = actions or []
        self._backend = None

    def start(self):
        """Startet das plattformspezifische Backend. Wirft dessen Exception
        durch (synchron) — Aufrufer (_apply_tray_setting) fängt und fällt auf
        Tray-Verzicht zurück."""
        backend_cls = _select_backend(platform.system())
        if backend_cls is None:
            raise RuntimeError("Tray auf dieser Plattform nicht unterstützt")
        backend = backend_cls(
            self.base_path, self._on_show, self._on_quit, self._actions)
        backend.start()
        self._backend = backend  # erst nach erfolgreichem start halten

    def notify(self, message, title="Zeiterfassung"):
        if self._backend is not None:
            self._backend.notify(message, title)

    def stop(self):
        if self._backend is not None:
            self._backend.stop()
            self._backend = None
```

- [ ] **Step 4: Run the new tests to verify they pass**

Run: `pytest tests/test_tray.py -v`
Expected: PASS (is_supported, build_menu_model, select_backend, facade).

- [ ] **Step 5: Run the full suite for regressions**

Run: `pytest tests/ -q`
Expected: PASS — insbesondere `tests/test_sync_orchestrator.py` (nutzt `_tray`/`notify`/`stop`) und `tests/test_ui_*` bleiben grün. Bricht etwas, ist die Fassaden-API von der alten abgewichen → angleichen.

- [ ] **Step 6: Commit**

```bash
git add src/tray.py tests/test_tray.py
git commit -m "refactor(tray): TrayIcon als Plattform-Fassade, pystray in _PystrayBackend (#88)"
```

---

### Task 5: macOS-Build — PyObjC collecten

**Files:**
- Modify: `build.py:131-139` (`build_macos`, PyInstaller-Args)

**Interfaces:**
- Consumes/Produces: keine Code-Schnittstelle (Build-Config).

- [ ] **Step 1: Modify `build_macos`**

In `build.py::build_macos` die `_pyinstaller_common(...)`-Argliste um die pyobjc-Collect-Flags ergänzen (lazy importierte AppKit/Foundation übersieht PyInstallers statische Analyse sonst). Aus:

```python
    cmd = _pyinstaller_common([
        "--windowed",
        "-D",
        "--icon", "assets/margenheld-icon.icns",
        "--osx-bundle-identifier", "com.margenheld.zeiterfassung",
    ])
```

wird:

```python
    cmd = _pyinstaller_common([
        "--windowed",
        "-D",
        "--icon", "assets/margenheld-icon.icns",
        "--osx-bundle-identifier", "com.margenheld.zeiterfassung",
        # tray_mac.py importiert AppKit/Foundation lazy → explizit bündeln,
        # sonst fehlt PyObjC im DMG und das native Tray fällt still aus (#88).
        "--collect-all", "objc",
        "--collect-all", "AppKit",
        "--collect-all", "Foundation",
    ])
```

(Nur `build_macos` — Windows/Linux-Build unverändert.)

- [ ] **Step 2: Verify the file parses and contains the flags**

Run: `python -c "import ast; ast.parse(open('build.py').read()); print('parse ok')"`
Expected: `parse ok`.
Run: `grep -c "collect-all\", \"AppKit" build.py`
Expected: `1`.

> Echte Verifikation (PyObjC vollständig im DMG) ist erst der macOS-DMG-Build + Mac-Gate, nicht hier automatisierbar.

- [ ] **Step 3: Commit**

```bash
git add build.py
git commit -m "build(macos): PyObjC (objc/AppKit/Foundation) ins DMG collecten (#88)"
```

---

### Task 6: CI — `test-macos`-Job

**Files:**
- Modify: `.github/workflows/test.yml` (neuer Job neben `test`/`lint`)

**Interfaces:**
- Consumes: `tests/test_tray_mac.py` (Smoke läuft nur auf Darwin), `pyobjc-framework-Cocoa`.

- [ ] **Step 1: Add the job**

In `.github/workflows/test.yml` nach dem `test`-Job (vor `lint`) einfügen:

```yaml
  test-macos:
    runs-on: macos-latest
    steps:
      - uses: actions/checkout@v6
      - uses: actions/setup-python@v6
        with:
          python-version: '3.10'
      - run: pip install pytest "holidays==0.99" google-api-python-client google-auth google-auth-oauthlib pyobjc-framework-Cocoa
      - run: pytest tests/
```

(Gleiche Deps wie der Linux-`test`-Job + `pyobjc-framework-Cocoa`; kein `pystray`/`Pillow` nötig, da macOS das native Backend nutzt. Der native Smoke in `test_tray_mac.py` läuft hier, skippt bei fehlendem Status-Bar-Zugriff.)

- [ ] **Step 2: Verify the YAML parses**

Run: `python -c "import yaml; yaml.safe_load(open('.github/workflows/test.yml')); print('yaml ok')"`
Expected: `yaml ok`. (Falls PyYAML fehlt: `pip install pyyaml`.)

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/test.yml
git commit -m "ci: test-macos-Job (pyobjc-Import, Dispatch, In-Process-Smoke) (#88)"
```

---

### Task 7: Doku nachziehen

**Files:**
- Modify: `src/tray.py` (Modul-Docstring)
- Modify: `src/CLAUDE.md` (Infra-Liste)
- Modify: `CLAUDE.md` (Struktur-Modul-Liste)

**Interfaces:** keine.

- [ ] **Step 1: `src/tray.py`-Modul-Docstring aktualisieren**

Den Modul-Docstring (Zeilen 2-9) so fassen, dass er Fassade + zwei Backends beschreibt. Ersetzen durch:

```python
"""System-Tray-Icon — Plattform-Fassade über zwei Backends.

`TrayIcon` wählt per platform.system(): Windows → `_PystrayBackend` (pystray im
Daemon-Thread, UI-Aktionen via `root.after(0, …)` auf den Tk-Thread). macOS →
`MacTrayBackend` (src/tray_mac.py): natives NSStatusItem SYNCHRON auf dem
Main-Thread, KEIN Thread, keine zweite NSApplication (Fix #88). macOS ist bis zum
manuellen Mac-Gate dormant (Opt-in `ZEIT_MACOS_TRAY=1`, s. is_supported). Linux
hat kein Tray. `build_menu_model` ist die backend-agnostische, testbare Naht.
"""
```

- [ ] **Step 2: `src/CLAUDE.md` ergänzen**

Im Abschnitt „Berichte & Plattform/Infra" die `tray.py`-Erwähnung um `tray_mac.py` erweitern. Die Zeile mit `tray.py` (in der Aufzählung `holidays_de.py`, `paths.py`, … `tray.py`, `version.py`) so ändern, dass nach `tray.py` ergänzt wird: `tray.py`/`tray_mac.py` (macOS-NSStatusItem-Backend, Fassade in `tray.py`).

Konkret die bestehende Zeile

```
  (GitHub-Releases, stdlib-only, 1×/Tag), `platform_open.py`, `logging_setup.py`, `tray.py`,
```

ersetzen durch

```
  (GitHub-Releases, stdlib-only, 1×/Tag), `platform_open.py`, `logging_setup.py`,
  `tray.py` (Fassade) + `tray_mac.py` (natives macOS-NSStatusItem-Backend, #88),
```

- [ ] **Step 3: Root-`CLAUDE.md`-Modulliste ergänzen**

In der „## Struktur"-Aufzählung direkt nach der `src/tray.py`-Zeile eine Zeile einfügen:

```
- `src/tray_mac.py` — natives macOS-Tray (NSStatusItem, Main-Thread) als Backend von `tray.py`; macOS-Tray ist bis zum Mac-Gate dormant (Opt-in `ZEIT_MACOS_TRAY=1`, #88)
```

- [ ] **Step 4: Verify docs render (kein Code-Test)**

Run: `git diff --stat`
Expected: `src/tray.py`, `src/CLAUDE.md`, `CLAUDE.md` geändert.

- [ ] **Step 5: Commit**

```bash
git add src/tray.py src/CLAUDE.md CLAUDE.md
git commit -m "docs(tray): Fassade + macOS-Backend + dormant-Staging dokumentieren (#88)"
```

---

## Nach dem Plan: CHANGELOG / Version / Release

- **CHANGELOG.md / `src/version.py`:** Dieser Branch behebt #88 (macOS-Tray default aus, natives Backend dormant). Beim PR die Version + CHANGELOG nach dem Release-Prozess (Root-`CLAUDE.md`) setzen — nicht Teil der Code-Tasks, da rein Release-Mechanik.
- **Default-an-Flip (separater PR):** Nach bestandenem manuellem Mac-Gate `is_supported()` auf macOS unconditional True. Required Release-Gate — nicht in diesem Plan.

## Manuelles Mac-Gate (required vor dem Flip-PR)

Mit `ZEIT_MACOS_TRAY=1` auf einem Mac, `minimize_to_tray` aktiv:
1. App starten → Tray-Icon erscheint in der Menübar.
2. Klick aufs Icon → Menü öffnet (Anzeigen | Senden/Teilen/Export/Sync | Beenden).
3. „Anzeigen", jede Quick-Action, „Beenden" lösen die richtige Aktion aus.
4. Sync an/aus schalten → Sync-Eintrag erscheint/verschwindet live.
5. **Kein Crash** beim „Google neu verbinden" und beim Sync-/Kalender-Aktivieren bei aktivem Tray (= Klasse-(ii)-Prüfung, der eigentliche #88-Beweis).
6. Fenster schließen → minimiert ins Tray; „Beenden" beendet sauber (Sync-Push).
