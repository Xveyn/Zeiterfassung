# Linux-Tray über StatusNotifierItem — Implementierungsplan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Tray-Icon inklusive Menü und Toasts auf KDE Plasma über die StatusNotifierItem-D-Bus-Schnittstelle — dormant hinter `ZEIT_LINUX_TRAY=1`, bis das manuelle Plasma-Gate grün ist.

**Architecture:** Neues Backend `src/tray_linux.py` hinter der bestehenden `TrayIcon`-Fassade (dritter Fall neben pystray/Windows und NSStatusItem/macOS). Die Menü-Logik liegt D-Bus-frei in `MenuState` und ist überall testbar; darüber liegt ein dünner Adapter, der zwei `dbus_fast.ServiceInterface`-Objekte exportiert (`org.kde.StatusNotifierItem` auf `/StatusNotifierItem`, `com.canonical.dbusmenu` auf `/MenuBar`) und sich beim `org.kde.StatusNotifierWatcher` registriert. `src/ui.py` bleibt unverändert.

**Tech Stack:** Python 3.10, `dbus-fast==5.0.22` (MIT, zero deps, pure Python + optionale Cython-Beschleunigung, nur Linux), stdlib `asyncio`/`threading`, Pillow (bereits vorhanden) für die Icon-Pixmaps, pytest.

**Spec:** [`docs/superpowers/specs/2026-07-29-linux-sni-tray-design.md`](../specs/2026-07-29-linux-sni-tray-design.md) · **Issue:** #42 · **Branch:** `feat/linux-sni-tray`

## Global Constraints

- **Deutsch in Kommentaren/Docstrings, Englisch in Commit-Typen** (`feat:`/`fix:`/`docs:`/`test:`), Body deutsch — wie im ganzen Repo.
- **Modulebene von `src/tray_linux.py` bleibt stdlib-only** (plus `src.tray`). `dbus_fast` und `PIL` werden **lazy in Funktionen** importiert, `ServiceInterface`-Subklassen werden **innerhalb** der Factory definiert. Grund: `src.ui → src.tray → src.tray_linux` wird von der CI auf Windows/macOS importiert. Vorbild: `src/tray_mac.py` (definiert seine `NSObject`-Subklasse in `start()`).
- **`src/ui.py` wird in diesem Plan nicht angefasst.** Kommt der Wunsch auf, ist das ein Zeichen, dass die Fassade verletzt wird.
- **Kein Default-an-Flip.** `is_supported()` liefert auf Linux nur mit `ZEIT_LINUX_TRAY=1` True.
- **Pin exakt:** `dbus-fast==5.0.22`, Marker `sys_platform == "linux"`, in `requirements.txt` **und** `requirements-test.txt`.
- **Ruff-Regeln des Projekts:** `select = ["E4","E7","E9","F","B"]`. Bugbear ist aktiv — `raise X(...) from exc` innerhalb von `except`-Blöcken ist Pflicht (B904).
- **Annotations-Regel für alle D-Bus-Member (bindend, empirisch geprüft):** `pyright` läuft im CI als Gate über `src` **und** `tests` (`pyproject.toml [tool.pyright] include`). Die in der dbus-fast-Doku gezeigten **String-Signaturen (`-> "s"`) sind damit unbrauchbar** — pyright meldet sie als undefinierte Namen (nachgestellt: zwei Methoden → vier Fehler). Verwendet werden deshalb:
  - **importierte Aliase** aus `dbus_fast.annotations` für einfache Typen: `DBusStr` (`s`), `DBusBool` (`b`), `DBusInt32` (`i`), `DBusUInt32` (`u`), `DBusObjectPath` (`o`), `DBusVariant` (`v`), `DBusDict` (`a{sv}`);
  - **inline `Annotated[list, DBusSignature("…")]`** für alles Zusammengesetzte (`as`, `ai`, `a(iiay)`, `(sa(iiay)ss)`, `u(ia{sv}av)`, `a(ia{sv})`, `a(isvu)`, `aiai`, `ui`).
  **Keine selbstgebauten Alias-Variablen** (`DBusStrList = Annotated[...]`): pyright wertet die als „Variable not allowed in type expression" und wird rot. Importierte Aliase und inline-Ausdrücke sind beide sauber — beides ist gegen pyright 1.1.411 und gegen die Laufzeit (dbus-fast liest `__metadata__`) durchgespielt.
  Der Python-Typ im `Annotated` ist bewusst das lose `list`: dbus-fast liest nur die Signatur, und Structs wie Multi-Out-Args sind auf dieser Ebene Listen (`service.py::_real_fn_result_to_body` akzeptiert Liste oder Tupel).
- **Zeilenlänge** 100 (`pyproject.toml`), Formatierung sonst wie im Umfeld.
- **Verifiziert wird lokal mit `pytest` aus dem Repo-Root.** Die D-Bus-Tasks brauchen Linux: lokal über Docker (Kommando in Task 7), sonst im CI-Linux-Job.

### Verifizierte API-Fakten zu dbus-fast 5.0.22 (Quelle: Wheel-Quelltext)

Diese vier Punkte sind beim Schreiben des Codes bindend — sie sind gegen den echten Paketinhalt geprüft, nicht geraten:

1. **Member-Name = Funktionsname 1:1** (`fn_name = name or fn.__name__`, `service.py:156/264/294`). Deshalb heißen die Python-Methoden exakt `Activate`, `GetLayout`, `Category` — keine snake_case-Umbenennung.
2. **String-Signaturen sind weiterhin gültig** (`_private/util.py::parse_annotation` erkennt sie per Regex). `def Activate(self, x: "i", y: "i")` ist korrekt; die neueren `Annotated[...]`-Aliase sind optional und für `a(iiay)`/`(ia{sv}av)` unnötig umständlich.
3. **`@dbus_method` liefert einen Wrapper, der `None` zurückgibt** (`service.py:150-160`). Ein Direktaufruf `menu.GetLayout(...)` im Test prüft **keine** Rückgabewerte — deshalb liegt die Menü-Logik in `MenuState` (pure, direkt testbar) und die Wire-Ebene wird über den echten Bus getestet (Task 7).
4. **`@dbus_property` erzeugt ein echtes Python-`property`** (`class _Property(property)`). `item.Category` ist im Test direkt lesbar.

---

### Task 1: Menü-Zustand (pure, ohne D-Bus)

**Files:**
- Create: `src/tray_linux.py`
- Test: `tests/test_tray_linux.py`

**Interfaces:**
- Consumes: `src.tray.build_menu_model(on_show, on_quit, actions)` → Liste von `MenuEntry(kind, label, callback, visible)` mit `kind ∈ {"item", "separator"}`.
- Produces: `MenuNode(id, props, callback, visible)`; `build_menu_nodes(model) -> list[MenuNode]`; `MenuState(model)` mit `.revision`, `.refresh() -> bool`, `.layout() -> tuple`, `.properties(node_id) -> dict`, `.ids() -> list[int]`, `.dispatch(node_id) -> bool`; Konstante `PROP_SIGNATURES: dict[str, str]`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_tray_linux.py
"""Pure Menü-/Icon-Logik des Linux-SNI-Backends (#42).

Läuft auf JEDER Plattform: das Modul importiert dbus_fast und PIL nur lazy in
Funktionen, hier wird ausschließlich die D-Bus-freie Schicht geprüft.
"""

from src.tray import build_menu_model
from src.tray_linux import MenuState, build_menu_nodes


def _model(sync_visible=True):
    """Menü-Modell wie es ui.py liefert: Anzeigen | — | Senden, Sync | — | Beenden."""
    return build_menu_model(
        lambda: None, lambda: None,
        [("Senden", lambda: None, None),
         ("Sync", lambda: None, lambda: sync_visible)],
    )


def test_nodes_have_sequential_ids_starting_at_one():
    nodes = build_menu_nodes(_model())
    assert [n.id for n in nodes] == [1, 2, 3, 4, 5, 6]


def test_separators_are_typed_and_carry_no_label():
    nodes = build_menu_nodes(_model())
    separators = [n for n in nodes if n.props.get("type") == "separator"]
    assert len(separators) == 2
    assert all("label" not in n.props for n in separators)


def test_items_carry_label_and_are_enabled():
    nodes = build_menu_nodes(_model())
    labels = [n.props["label"] for n in nodes if n.props["type"] == "standard"]
    assert labels == ["Anzeigen", "Senden", "Sync", "Beenden"]
    assert all(n.props["enabled"] is True
               for n in nodes if n.props["type"] == "standard")


def test_layout_root_is_a_submenu_with_all_children():
    state = MenuState(_model())
    root_id, root_props, children = state.layout()
    assert root_id == 0
    assert root_props["children-display"] == "submenu"
    assert [child_id for child_id, _props, _kids in children] == [1, 2, 3, 4, 5, 6]


def test_visible_callable_is_evaluated_into_the_layout():
    state = MenuState(_model(sync_visible=False))
    _root_id, _root_props, children = state.layout()
    by_label = {props.get("label"): props for _id, props, _kids in children}
    assert by_label["Sync"]["visible"] is False
    assert by_label["Senden"]["visible"] is True


def test_refresh_bumps_revision_only_when_visibility_changed():
    visible = {"sync": True}
    model = build_menu_model(
        lambda: None, lambda: None,
        [("Sync", lambda: None, lambda: visible["sync"])],
    )
    state = MenuState(model)
    before = state.revision

    assert state.refresh() is False
    assert state.revision == before

    visible["sync"] = False
    assert state.refresh() is True
    assert state.revision == before + 1


def test_dispatch_calls_the_callback_of_that_node():
    clicked = []
    model = build_menu_model(
        lambda: clicked.append("show"), lambda: clicked.append("quit"),
        [("Senden", lambda: clicked.append("send"), None)],
    )
    state = MenuState(model)
    send_id = next(n.id for n in build_menu_nodes(model)
                   if n.props.get("label") == "Senden")

    assert state.dispatch(send_id) is True
    assert clicked == ["send"]


def test_dispatch_on_separator_or_unknown_id_is_a_noop():
    state = MenuState(_model())
    assert state.dispatch(2) is False      # Separator
    assert state.dispatch(99) is False     # gibt es nicht


def test_throwing_visible_callable_keeps_the_entry_visible():
    def boom():
        raise RuntimeError("Settings nicht lesbar")

    model = build_menu_model(lambda: None, lambda: None,
                             [("Sync", lambda: None, boom)])
    state = MenuState(model)
    _root_id, _root_props, children = state.layout()
    by_label = {props.get("label"): props for _id, props, _kids in children}
    assert by_label["Sync"]["visible"] is True


def test_throwing_callback_does_not_escape_dispatch():
    def boom():
        raise RuntimeError("Dialog kaputt")

    model = build_menu_model(lambda: None, lambda: None,
                             [("Senden", boom, None)])
    state = MenuState(model)
    send_id = next(n.id for n in build_menu_nodes(model)
                   if n.props.get("label") == "Senden")
    assert state.dispatch(send_id) is True   # geschluckt, nicht geworfen
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_tray_linux.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.tray_linux'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/tray_linux.py
"""Linux-Tray über StatusNotifierItem (SNI) — Backend für TrayIcon (#42).

KDE Plasma implementiert SNI nativ; die Schnittstelle ist reines D-Bus. Dieses
Backend braucht deshalb WEDER GTK NOCH GObject-Introspection — anders als
pystrays appindicator-Backend, das beides in die AppImage zwingen würde.

Modulebene ist stdlib-only (plus src.tray): `dbus_fast` und `PIL` werden lazy in
den Funktionen importiert, die ServiceInterface-Subklassen in `_make_interfaces`
definiert. Grund: die CI importiert `src.ui → src.tray → src.tray_linux` auch auf
Windows/macOS. Dasselbe Muster wie das NSObject-Delegate in `tray_mac.py`.

Die Menü-Logik liegt in `MenuState` — D-Bus-frei und damit auf jeder Plattform
testbar; die D-Bus-Objekte sind nur die Hülle darum.

Spec: docs/superpowers/specs/2026-07-29-linux-sni-tray-design.md
"""

import logging
import os
from collections import namedtuple

from src.tray import build_menu_model  # noqa: F401  (ab Task 5 genutzt)

logger = logging.getLogger(__name__)

# dbusmenu-Property → D-Bus-Typ. Die pure Schicht liefert nackte Python-Werte,
# der D-Bus-Adapter verpackt sie damit in Variants (eine Quelle für beide).
PROP_SIGNATURES = {
    "type": "s",
    "label": "s",
    "enabled": "b",
    "visible": "b",
    "children-display": "s",
}

MenuNode = namedtuple("MenuNode", ["id", "props", "callback", "visible"])


def build_menu_nodes(model):
    """Menü-Modell (`tray.build_menu_model`) → dbusmenu-Knoten.

    IDs laufen ab 1, weil 0 in dbusmenu die Wurzel ist. `visible` bleibt die
    Callable — ausgewertet wird sie erst in `MenuState`, bei jedem Öffnen.
    """
    nodes = []
    for index, entry in enumerate(model, start=1):
        if entry.kind == "separator":
            nodes.append(MenuNode(index, {"type": "separator"}, None, None))
        else:
            nodes.append(MenuNode(
                index,
                {"type": "standard", "label": entry.label, "enabled": True},
                entry.callback,
                entry.visible,
            ))
    return nodes


class MenuState:
    """dbusmenu-Zustand ohne D-Bus: Knoten, Sichtbarkeit, Revision, Dispatch.

    Der Host (Plasma) ruft vor jedem Öffnen `AboutToShow`; darauf werten wir die
    `visible`-Callables neu aus. Ändert sich etwas, steigt die Revision und der
    Host holt das Layout neu — Linux verhält sich damit LIVE wie Windows, nicht
    als Snapshot wie macOS.
    """

    def __init__(self, model):
        self._nodes = build_menu_nodes(model)
        self._visibility = self._evaluate()
        self.revision = 1

    def _evaluate(self):
        visibility = {}
        for node in self._nodes:
            if node.visible is None:
                visibility[node.id] = True
                continue
            try:
                visibility[node.id] = bool(node.visible())
            except Exception:
                # Lieber ein Eintrag zu viel als ein totes Menü.
                logger.exception("Tray-Sichtbarkeit warf — Eintrag bleibt sichtbar")
                visibility[node.id] = True
        return visibility

    def refresh(self):
        """`visible`-Callables neu auswerten. True, wenn sich etwas geändert hat
        (dann ist die Revision gestiegen und der Host muss neu laden)."""
        current = self._evaluate()
        if current == self._visibility:
            return False
        self._visibility = current
        self.revision += 1
        return True

    def layout(self):
        """`(root_id, root_props, children)` mit nackten Property-Dicts.
        Kinder sind flach — wir haben keine Submenüs."""
        children = [
            (node.id, {**node.props, "visible": self._visibility[node.id]}, [])
            for node in self._nodes
        ]
        return (0, {"children-display": "submenu"}, children)

    def properties(self, node_id):
        """Property-Dict eines Knotens (für GetGroupProperties/GetProperty)."""
        for node in self._nodes:
            if node.id == node_id:
                return {**node.props, "visible": self._visibility[node.id]}
        return {}

    def ids(self):
        return [node.id for node in self._nodes]

    def dispatch(self, node_id):
        """Callback des Knotens aufrufen. True, wenn es einen gab.

        Exceptions werden geschluckt: der Callback läuft im D-Bus-Loop-Thread,
        ein Wurf würde die Loop killen und das Icon stumm schalten.
        """
        for node in self._nodes:
            if node.id == node_id and node.callback is not None:
                try:
                    node.callback()
                except Exception:
                    logger.exception("Tray-Menü-Callback warf (geschluckt)")
                return True
        return False
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_tray_linux.py -v`
Expected: PASS (10 Tests)

- [ ] **Step 5: Commit**

```bash
git add src/tray_linux.py tests/test_tray_linux.py
git commit -m "feat(tray): dbusmenu-Menüzustand für das Linux-SNI-Backend (#42)"
```

---

### Task 2: Icon-Pixmaps (ARGB32)

**Files:**
- Modify: `src/tray_linux.py` (Funktionen ans Ende anfügen)
- Test: `tests/test_tray_linux.py` (Tests anfügen)

**Interfaces:**
- Produces: `argb32_from_rgba(rgba: bytes) -> bytes`; `icon_pixmaps(base_path, sizes=(32, 64, 128)) -> list[tuple[int, int, bytes]]`.

- [ ] **Step 1: Write the failing test**

Ans Ende von `tests/test_tray_linux.py`:

```python
import os

import pytest

from src.tray_linux import argb32_from_rgba, icon_pixmaps


def test_argb32_reorders_one_pixel():
    # RGBA (1,2,3,4) → ARGB (4,1,2,3): SNI erwartet ARGB32 in Network-Byte-Order.
    assert argb32_from_rgba(bytes([1, 2, 3, 4])) == bytes([4, 1, 2, 3])


def test_argb32_reorders_every_pixel_and_keeps_length():
    rgba = bytes([1, 2, 3, 4, 10, 20, 30, 40])
    assert argb32_from_rgba(rgba) == bytes([4, 1, 2, 3, 40, 10, 20, 30])
    assert len(argb32_from_rgba(rgba)) == len(rgba)


def test_icon_pixmaps_without_png_returns_empty_list(tmp_path):
    # Kein Wurf: ein Item ohne Pixmap ist besser als gar kein Tray.
    assert icon_pixmaps(str(tmp_path)) == []


def test_icon_pixmaps_reads_the_app_icon_in_requested_sizes():
    pytest.importorskip("PIL")  # nicht in requirements-test.txt
    # Repo-Root aus __file__ ableiten statt "." — der Test darf nicht davon
    # abhängen, aus welchem Verzeichnis pytest gestartet wurde.
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    pixmaps = icon_pixmaps(repo_root, sizes=(16, 32))
    assert [(w, h) for w, h, _data in pixmaps] == [(16, 16), (32, 32)]
    assert len(pixmaps[0][2]) == 16 * 16 * 4
    assert len(pixmaps[1][2]) == 32 * 32 * 4
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_tray_linux.py -v -k "argb32 or pixmaps"`
Expected: FAIL — `ImportError: cannot import name 'argb32_from_rgba'`

- [ ] **Step 3: Write minimal implementation**

Ans Ende von `src/tray_linux.py`:

```python
def argb32_from_rgba(rgba):
    """RGBA-Bytes → ARGB32 in Network-Byte-Order, wie SNI es für `IconPixmap`
    verlangt (`a(iiay)`). Pillow-frei und damit überall testbar."""
    argb = bytearray(len(rgba))
    argb[0::4] = rgba[3::4]   # A
    argb[1::4] = rgba[0::4]   # R
    argb[2::4] = rgba[1::4]   # G
    argb[3::4] = rgba[2::4]   # B
    return bytes(argb)


def icon_pixmaps(base_path, sizes=(32, 64, 128)):
    """`[(breite, höhe, argb32)]` aus `assets/margenheld-icon.png`.

    Mehrere Größen, damit der Host für seine Panel-Höhe die passende wählt.
    Pillow wird lazy importiert (wie im pystray-Backend). Fehlt die PNG oder
    Pillow, bleibt die Liste leer und das Item startet ohne eigenes Icon —
    besser als ein Tray, das gar nicht erst hochkommt.
    """
    png = os.path.join(base_path, "assets", "margenheld-icon.png")
    if not os.path.exists(png):
        logger.warning("Tray-Icon %s fehlt — Item startet ohne Pixmap", png)
        return []
    try:
        from PIL import Image  # pyright: ignore[reportMissingImports]  # Pillow: nicht in CI-Test-Deps
    except ImportError:
        logger.warning("Pillow nicht verfügbar — Item startet ohne Pixmap")
        return []
    pixmaps = []
    with Image.open(png) as image:
        rgba = image.convert("RGBA")
        for size in sizes:
            scaled = rgba.resize((size, size))
            pixmaps.append((size, size, argb32_from_rgba(scaled.tobytes())))
    return pixmaps
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_tray_linux.py -v`
Expected: PASS (14 Tests; der Pillow-Test skippt, falls Pillow fehlt)

- [ ] **Step 5: Commit**

```bash
git add src/tray_linux.py tests/test_tray_linux.py
git commit -m "feat(tray): ARGB32-Icon-Pixmaps für das Linux-SNI-Backend (#42)"
```

---

### Task 3: Abhängigkeit und Build-Bündelung

**Files:**
- Modify: `requirements.txt`
- Modify: `requirements-test.txt`
- Modify: `build.py:185-191` (`build_linux`)
- Test: `tests/test_build.py:48-58`

**Interfaces:**
- Produces: `dbus_fast` ist im Linux-Build gebündelt und im Linux-Testlauf installiert.

- [ ] **Step 1: Write the failing test**

In `tests/test_build.py` ans Ende anfügen:

```python
def test_linux_bundles_dbus_fast(monkeypatch):
    """Das SNI-Tray importiert dbus_fast lazy — ohne --collect-all fehlt es in
    der AppImage und das Tray stirbt beim Start statt beim Build (#42)."""
    cmd = _capture_pyinstaller_cmd(monkeypatch, build.build_linux)
    assert "dbus_fast" in cmd


def test_windows_does_not_bundle_dbus_fast(monkeypatch):
    """dbus_fast ist Linux-only (Marker in requirements.txt) — auf Windows wäre
    das --collect-all ein Build-Fehler."""
    cmd = _capture_pyinstaller_cmd(monkeypatch, build.build_windows)
    assert "dbus_fast" not in cmd
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_build.py -v`
Expected: FAIL — `assert 'dbus_fast' in cmd` (der Windows-Test ist bereits grün)

- [ ] **Step 3: Write minimal implementation**

`build.py`, in `build_linux()` den PyInstaller-Aufruf ersetzen:

```python
    cmd = _pyinstaller_common([
        "--onefile",
        # tray_linux.py importiert dbus_fast lazy → explizit bündeln, sonst
        # fehlt es in der AppImage und das SNI-Tray startet nicht (#42).
        "--collect-all", "dbus_fast",
    ])
```

`requirements.txt` — nach der `Pillow`-Zeile:

```
dbus-fast==5.0.22; sys_platform == "linux"
```

`requirements-test.txt` — ans Ende:

```
# Nur für den Linux-Job: Integrationstest des SNI-Trays gegen einen echten
# dbus-daemon (tests/test_tray_linux_dbus.py). Pure Python, keine C-Deps.
dbus-fast==5.0.22; sys_platform == "linux"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_build.py -v`
Expected: PASS (6 Tests)

- [ ] **Step 5: Commit**

```bash
git add requirements.txt requirements-test.txt build.py tests/test_build.py
git commit -m "build: dbus-fast pinnen und in den Linux-Build bündeln (#42)"
```

---

### Task 4: D-Bus-Adapter (SNI-Item + dbusmenu)

**Files:**
- Modify: `src/tray_linux.py` (Konstanten oben ergänzen, `_safe` und `_make_interfaces` anfügen)
- Test: `tests/test_tray_linux_iface.py`

**Interfaces:**
- Consumes: `MenuState`, `PROP_SIGNATURES`, `icon_pixmaps` (Task 1/2).
- Produces: `_make_interfaces(state, on_activate, pixmaps) -> (item_iface, menu_iface)`; Modulkonstanten `ITEM_PATH`, `MENU_PATH`, `WATCHER_NAME`, `WATCHER_PATH`, `NOTIFY_NAME`, `NOTIFY_PATH`.

**Hinweis zum Testschnitt:** `@dbus_method` liefert einen Wrapper, der `None` zurückgibt (verifiziert, s. Global Constraints) — Rückgabewerte sind also nur über den Bus prüfbar (Task 7). Was dieser Task testet, ist das, was hier auch wirklich schiefgehen kann: dass **jede Signatur-Annotation parst** (das passiert beim Klassenaufbau in `_make_interfaces`) und dass die **Properties** die richtigen Werte liefern (`dbus_property` ist ein echtes `property`).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_tray_linux_iface.py
"""D-Bus-Adapter des Linux-SNI-Backends (#42).

Braucht dbus_fast, aber KEINEN laufenden Bus: geprüft werden der Aufbau der
ServiceInterface-Klassen (dabei parst dbus_fast jede Signatur-Annotation — ein
Tippfehler in "a(iiay)" fliegt genau hier auf) und die Item-Properties.
Rückgabewerte der @dbus_method-Methoden sind so NICHT prüfbar (der Decorator
liefert einen None-Wrapper) — das macht der Bus-Test in test_tray_linux_dbus.py.
"""

import pytest

pytest.importorskip("dbus_fast")

from src.tray import build_menu_model
from src.tray_linux import MENU_PATH, MenuState, _make_interfaces


def _interfaces(pixmaps=(), on_activate=lambda: None):
    state = MenuState(build_menu_model(
        lambda: None, lambda: None, [("Senden", lambda: None, None)]))
    return _make_interfaces(state, on_activate, list(pixmaps))


def test_interfaces_are_built_with_the_expected_names():
    item, menu = _interfaces()
    assert item.name == "org.kde.StatusNotifierItem"
    assert menu.name == "com.canonical.dbusmenu"


def test_item_properties_describe_the_app():
    item, _menu = _interfaces()
    assert item.Category == "ApplicationStatus"
    assert item.Id == "zeiterfassung"
    assert item.Title == "Zeiterfassung"
    assert item.Status == "Active"


def test_item_is_not_a_menu_so_left_click_activates():
    """ItemIsMenu=False ist die Bedingung dafür, dass Plasma den Linksklick als
    Activate schickt statt nur das Menü zu öffnen."""
    item, _menu = _interfaces()
    assert item.ItemIsMenu is False
    assert item.Menu == MENU_PATH


def test_item_exposes_the_pixmaps_it_was_given():
    item, _menu = _interfaces(pixmaps=[(2, 2, b"\x00" * 16)])
    assert item.IconPixmap == [[2, 2, b"\x00" * 16]]
    assert item.IconName == ""


def test_menu_reports_dbusmenu_version_three():
    _item, menu = _interfaces()
    assert menu.Version == 3
    assert menu.Status == "normal"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_tray_linux_iface.py -v`
Expected: FAIL — `ImportError: cannot import name 'MENU_PATH'` (bzw. Skip, wenn `dbus_fast` lokal nicht installiert ist — dann in Docker laufen lassen, s. Task 7)

- [ ] **Step 3: Write minimal implementation**

In `src/tray_linux.py` den Import-Block um `Annotated` ergänzen (stdlib, darf auf
Modulebene stehen — im Gegensatz zu `DBusSignature`):

```python
from typing import Annotated
```

Direkt unter `logger = ...` die Konstanten ergänzen:

```python
ITEM_PATH = "/StatusNotifierItem"
MENU_PATH = "/MenuBar"
WATCHER_NAME = "org.kde.StatusNotifierWatcher"
WATCHER_PATH = "/StatusNotifierWatcher"
NOTIFY_NAME = "org.freedesktop.Notifications"
NOTIFY_PATH = "/org/freedesktop/Notifications"
```

Ans Ende von `src/tray_linux.py`:

```python
def _safe(fn):
    """0-arg-Callback aufrufen, ohne dass eine Exception in den D-Bus-Loop
    zurückläuft (ein Wurf dort würde die Loop beenden — Icon stumm)."""
    try:
        fn()
    except Exception:
        logger.exception("Linux-Tray-Callback-Fehler (geschluckt)")


def _make_interfaces(state, on_activate, pixmaps):
    """Baut die beiden D-Bus-Objekte: SNI-Item und dbusmenu.

    `dbus_fast` wird hier LAZY importiert und die Klassen werden IN der Funktion
    definiert (sie erben von ServiceInterface) — dasselbe Muster wie das
    NSObject-Delegate in `tray_mac.py`. So bleibt die Modulebene stdlib-only.

    Die Methodennamen sind exakt die D-Bus-Member-Namen: dbus_fast leitet den
    Namen 1:1 vom Funktionsnamen ab.
    """
    from dbus_fast import PropertyAccess, Variant  # pyright: ignore[reportMissingImports]  # dbus-fast: nur auf Linux installiert
    from dbus_fast.annotations import (  # pyright: ignore[reportMissingImports]  # dbus-fast: nur auf Linux installiert
        DBusBool, DBusInt32, DBusObjectPath, DBusSignature, DBusStr, DBusUInt32, DBusVariant,
    )
    from dbus_fast.service import (  # pyright: ignore[reportMissingImports]  # dbus-fast: nur auf Linux installiert
        ServiceInterface, dbus_method, dbus_property, dbus_signal,
    )

    # Zusammengesetzte Signaturen stehen INLINE (siehe Annotations-Regel in den
    # Global Constraints — ein selbstgebauter Alias wäre für pyright eine
    # Variable im Typausdruck und damit ein Fehler). Der Python-Typ ist bewusst
    # das lose `list`: dbus_fast liest ohnehin nur die DBusSignature, und
    # Structs wie Multi-Out-Args sind auf dieser Ebene Listen.
    def _variants(props):
        return {key: Variant(PROP_SIGNATURES[key], value) for key, value in props.items()}

    class _Item(ServiceInterface):
        """org.kde.StatusNotifierItem — Icon und Klick-Verhalten."""

        def __init__(self):
            super().__init__("org.kde.StatusNotifierItem")

        @dbus_property(PropertyAccess.READ)
        def Category(self) -> DBusStr:
            return "ApplicationStatus"

        @dbus_property(PropertyAccess.READ)
        def Id(self) -> DBusStr:
            return "zeiterfassung"

        @dbus_property(PropertyAccess.READ)
        def Title(self) -> DBusStr:
            return "Zeiterfassung"

        @dbus_property(PropertyAccess.READ)
        def Status(self) -> DBusStr:
            return "Active"

        @dbus_property(PropertyAccess.READ)
        def WindowId(self) -> DBusInt32:
            return 0

        @dbus_property(PropertyAccess.READ)
        def ItemIsMenu(self) -> DBusBool:
            # False → Plasma schickt beim Linksklick Activate, statt nur das
            # Menü zu öffnen. Das ist der Default-Klick, den pystrays
            # appindicator-Backend prinzipbedingt nicht kann.
            return False

        @dbus_property(PropertyAccess.READ)
        def Menu(self) -> DBusObjectPath:
            return MENU_PATH

        @dbus_property(PropertyAccess.READ)
        def IconName(self) -> DBusStr:
            # Leer: wir liefern Pixmaps statt eines Theme-Icons (die App ist
            # nicht im Icon-Theme des Systems installiert).
            return ""

        @dbus_property(PropertyAccess.READ)
        def IconPixmap(self) -> Annotated[list, DBusSignature("a(iiay)")]:
            return [[width, height, data] for width, height, data in pixmaps]

        @dbus_property(PropertyAccess.READ)
        def ToolTip(self) -> Annotated[list, DBusSignature("(sa(iiay)ss)")]:
            return ["", [], "Zeiterfassung", ""]

        @dbus_method()
        def Activate(self, x: DBusInt32, y: DBusInt32):
            _safe(on_activate)

        @dbus_method()
        def SecondaryActivate(self, x: DBusInt32, y: DBusInt32):
            pass

        @dbus_method()
        def ContextMenu(self, x: DBusInt32, y: DBusInt32):
            # Der Host zeigt das dbusmenu selbst (Menu-Property ist gesetzt);
            # die Methode existiert nur, damit niemand UnknownMethod sieht.
            pass

        @dbus_method()
        def Scroll(self, delta: DBusInt32, orientation: DBusStr):
            pass

        @dbus_method()
        def ProvideXdgActivationToken(self, token: DBusStr):
            # Tk kann den Token nicht verwerten — unter Wayland darf der
            # Compositor das Anheben deshalb verweigern (s. Spec).
            pass

    class _Menu(ServiceInterface):
        """com.canonical.dbusmenu — dünne Hülle um MenuState."""

        def __init__(self):
            super().__init__("com.canonical.dbusmenu")

        @dbus_property(PropertyAccess.READ)
        def Version(self) -> DBusUInt32:
            return 3

        @dbus_property(PropertyAccess.READ)
        def Status(self) -> DBusStr:
            return "normal"

        @dbus_property(PropertyAccess.READ)
        def TextDirection(self) -> DBusStr:
            return "ltr"

        @dbus_property(PropertyAccess.READ)
        def IconThemePath(self) -> Annotated[list, DBusSignature("as")]:
            return []

        @dbus_method()
        def GetLayout(self, parentId: DBusInt32, recursionDepth: DBusInt32,
                      propertyNames: Annotated[list, DBusSignature("as")],
                      ) -> Annotated[list, DBusSignature("u(ia{sv}av)")]:
            root_id, root_props, children = state.layout()
            nodes = [
                Variant("(ia{sv}av)", [child_id, _variants(props), []])
                for child_id, props, _kids in children
            ]
            return [state.revision, [root_id, _variants(root_props), nodes]]

        @dbus_method()
        def GetGroupProperties(self,
                               ids: Annotated[list, DBusSignature("ai")],
                               propertyNames: Annotated[list, DBusSignature("as")],
                               ) -> Annotated[list, DBusSignature("a(ia{sv})")]:
            wanted = list(ids) if ids else state.ids()
            return [[node_id, _variants(state.properties(node_id))] for node_id in wanted]

        @dbus_method()
        def GetProperty(self, id: DBusInt32, name: DBusStr) -> DBusVariant:
            props = state.properties(id)
            if name not in props:
                return Variant("s", "")
            return Variant(PROP_SIGNATURES[name], props[name])

        @dbus_method()
        def Event(self, id: DBusInt32, eventId: DBusStr, data: DBusVariant,
                  timestamp: DBusUInt32):
            if eventId == "clicked":
                state.dispatch(id)

        @dbus_method()
        def EventGroup(self, events: Annotated[list, DBusSignature("a(isvu)")],
                       ) -> Annotated[list, DBusSignature("ai")]:
            for event in events:
                if event[1] == "clicked":
                    state.dispatch(event[0])
            return []

        @dbus_method()
        def AboutToShow(self, id: DBusInt32) -> DBusBool:
            # Plasma ruft das vor jedem Öffnen → hier wird `visible` live neu
            # ausgewertet (Windows-Parität, kein Snapshot wie auf macOS).
            if not state.refresh():
                return False
            self.LayoutUpdated(state.revision, 0)
            return True

        @dbus_method()
        def AboutToShowGroup(self, ids: Annotated[list, DBusSignature("ai")],
                             ) -> Annotated[list, DBusSignature("aiai")]:
            if not state.refresh():
                return [[], []]
            self.LayoutUpdated(state.revision, 0)
            return [list(ids), []]

        @dbus_signal()
        def LayoutUpdated(self, revision: DBusUInt32,
                          parent: DBusInt32) -> Annotated[list, DBusSignature("ui")]:
            return [revision, parent]

    return _Item(), _Menu()
```


- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_tray_linux_iface.py -v`
Expected: PASS (5 Tests) — bzw. sauberer Skip ohne `dbus_fast`; dann in Docker verifizieren (Task 7, gleiches Kommando mit anderem Testpfad).

- [ ] **Step 5: Commit**

```bash
git add src/tray_linux.py tests/test_tray_linux_iface.py
git commit -m "feat(tray): SNI-Item und dbusmenu als D-Bus-Objekte (#42)"
```

---

### Task 5: Backend-Lebenszyklus (start/stop/notify)

**Files:**
- Modify: `src/tray_linux.py` (`asyncio`/`threading`-Imports oben, `LinuxTrayBackend` anfügen)
- Test: `tests/test_tray_linux.py` (Tests anfügen)

**Interfaces:**
- Consumes: `MenuState`, `_make_interfaces`, `icon_pixmaps`, Konstanten aus Task 1/2/4.
- Produces: `LinuxTrayBackend(base_path, on_show, on_quit, actions=None)` mit `start()`, `stop()`, `notify(message, title="Zeiterfassung")` — dieselbe Lifecycle-API wie `_PystrayBackend` und `MacTrayBackend`.

- [ ] **Step 1: Write the failing test**

Ans Ende von `tests/test_tray_linux.py`:

```python
from src.tray_linux import LinuxTrayBackend


def test_backend_keeps_the_facade_constructor_signature():
    """Die Fassade instanziiert alle Backends gleich (tray.TrayIcon.start)."""
    backend = LinuxTrayBackend("base", on_show=lambda: None,
                               on_quit=lambda: None, actions=[])
    assert backend.base_path == "base"


def test_stop_without_start_is_a_noop():
    backend = LinuxTrayBackend("base", on_show=lambda: None, on_quit=lambda: None)
    backend.stop()
    backend.stop()   # idempotent, auch mehrfach


def test_notify_without_start_is_a_noop():
    backend = LinuxTrayBackend("base", on_show=lambda: None, on_quit=lambda: None)
    backend.notify("hallo")   # darf nicht werfen


def test_start_raises_when_no_session_bus_is_reachable(monkeypatch):
    """Ohne Session-Bus muss start() SYNCHRON werfen — ui.py::_apply_tray_setting
    fängt das, zeigt eine Meldung und schaltet die Optionen ab."""
    pytest.importorskip("dbus_fast")
    monkeypatch.setenv("DBUS_SESSION_BUS_ADDRESS", "unix:path=/nonexistent/zeit-test")
    backend = LinuxTrayBackend(".", on_show=lambda: None, on_quit=lambda: None)
    with pytest.raises(Exception):
        backend.start()
    backend.stop()   # muss auch nach fehlgeschlagenem Start aufräumbar sein
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_tray_linux.py -v`
Expected: FAIL beim Sammeln — `ImportError: cannot import name 'LinuxTrayBackend' from 'src.tray_linux'`

- [ ] **Step 3: Write minimal implementation**

Oben in `src/tray_linux.py` die Imports ergänzen (stdlib bleibt stdlib):

```python
import asyncio
import concurrent.futures
import logging
import os
import threading
from collections import namedtuple
```

Ans Ende von `src/tray_linux.py`:

```python
def _log_notify_failure(future):
    """Done-Callback für den fire-and-forget-Toast: Fehler landen im Log statt
    im Nichts — ohne dass der aufrufende Tk-Thread auf den Bus wartet."""
    try:
        future.result()
    except Exception:
        logger.exception("Linux-Tray-Notify fehlgeschlagen (geschluckt)")


class LinuxTrayBackend:
    """SNI-Backend: exportiert Item und Menü auf dem Session-Bus und meldet sich
    beim StatusNotifierWatcher an.

    Ein Daemon-Thread mit eigener Asyncio-Loop — dasselbe Muster, das pystray auf
    Windows fährt. `start()` blockiert, bis Verbindung UND Registrierung stehen,
    und wirft deren Fehler im Aufrufer-Thread durch: genau der Vertrag, den
    `ui.py::_apply_tray_setting` erwartet.

    Die Menü-Callbacks laufen im Loop-Thread und marshallen selbst per
    `root.after(0, …)` auf den Tk-Thread (unverändertes Muster aus ui.py).
    """

    START_TIMEOUT_S = 10
    SHUTDOWN_TIMEOUT_S = 5

    def __init__(self, base_path, on_show, on_quit, actions=None):
        self.base_path = base_path
        self._on_show = on_show
        self._on_quit = on_quit
        self._actions = actions or []
        self._thread = None
        self._loop = None
        self._bus = None
        self._name = None
        self._stopping = None   # asyncio.Event, im Loop-Thread erzeugt

    def start(self):
        """Startet Loop-Thread, exportiert die Objekte, registriert sich.
        Wirft synchron, wenn kein Bus oder kein Watcher erreichbar ist."""
        ready = concurrent.futures.Future()
        self._thread = threading.Thread(target=self._run, args=(ready,), daemon=True)
        self._thread.start()
        try:
            ready.result(timeout=self.START_TIMEOUT_S)
        except concurrent.futures.TimeoutError as exc:
            raise RuntimeError(
                f"Kein StatusNotifierWatcher hat innerhalb von {self.START_TIMEOUT_S}s "
                "geantwortet — läuft ein SNI-fähiger Desktop (KDE Plasma)?") from exc

    def _run(self, ready):
        loop = asyncio.new_event_loop()
        self._loop = loop
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._serve(ready))
        except Exception as exc:
            if not ready.done():
                ready.set_exception(exc)
            else:
                logger.exception("Linux-Tray-Loop beendet sich mit Fehler")
        finally:
            loop.close()

    async def _serve(self, ready):
        from dbus_fast import BusType  # pyright: ignore[reportMissingImports]  # dbus-fast: nur auf Linux installiert
        from dbus_fast.aio import MessageBus  # pyright: ignore[reportMissingImports]  # dbus-fast: nur auf Linux installiert

        bus = await MessageBus(bus_type=BusType.SESSION).connect()
        self._bus = bus
        self._stopping = asyncio.Event()

        state = MenuState(build_menu_model(self._on_show, self._on_quit, self._actions))
        item, menu = _make_interfaces(state, self._on_show, icon_pixmaps(self.base_path))
        bus.export(ITEM_PATH, item)
        bus.export(MENU_PATH, menu)

        self._name = f"org.kde.StatusNotifierItem-{os.getpid()}-1"
        await self._own_name(bus)
        await self._register(bus)
        await self._watch_watcher(bus)

        ready.set_result(None)
        await self._stopping.wait()

        # Abbau IM Loop-Thread, nicht in stop(): sonst müsste stop() auf eine
        # Coroutine warten, deren Loop unmittelbar danach zumacht — das hing
        # bis zum Timeout, ausgerechnet im Quit-Pfad.
        if self._name:
            await bus.release_name(self._name)
        bus.disconnect()

    async def _own_name(self, bus):
        """Busnamen belegen — und prüfen, dass er uns wirklich gehört.

        Ohne die Prüfung würden wir bei belegtem Namen (zweite Instanz, deren
        Single-Instance-Guard degradiert ist) einen fremden Namen beim Watcher
        anmelden: Plasma fragte dann die falsche Anwendung nach Icon und Menü,
        und niemand sähe einen Fehler.
        """
        from dbus_fast import RequestNameReply  # pyright: ignore[reportMissingImports]  # dbus-fast: nur auf Linux installiert

        reply = await bus.request_name(self._name)
        if reply is not RequestNameReply.PRIMARY_OWNER:
            raise RuntimeError(
                f"Busname {self._name} ist bereits belegt (Antwort: {reply}) — "
                "läuft die Zeiterfassung doppelt?")

    async def _register(self, bus):
        from dbus_fast import Message, MessageType  # pyright: ignore[reportMissingImports]  # dbus-fast: nur auf Linux installiert

        reply = await bus.call(Message(
            destination=WATCHER_NAME, path=WATCHER_PATH, interface=WATCHER_NAME,
            member="RegisterStatusNotifierItem", signature="s", body=[self._name],
        ))
        if reply is None or reply.message_type is MessageType.ERROR:
            detail = reply.body[0] if reply is not None and reply.body else "keine Antwort"
            raise RuntimeError(f"StatusNotifierWatcher lehnte die Registrierung ab: {detail}")

    async def _watch_watcher(self, bus):
        """Nach einem plasmashell-Neustart neu anmelden — sonst ist das Icon weg
        und niemand kann sich erklären, warum."""
        introspection = await bus.introspect("org.freedesktop.DBus", "/org/freedesktop/DBus")
        proxy = bus.get_proxy_object(
            "org.freedesktop.DBus", "/org/freedesktop/DBus", introspection)
        dbus_iface = proxy.get_interface("org.freedesktop.DBus")

        # Loop LOKAL festhalten statt über self._loop: stop() setzt das Attribut
        # auf None, und ein Signal, das genau währenddessen eintrudelt, liefe
        # sonst in einen AttributeError im Loop-Callback.
        loop = asyncio.get_running_loop()

        def on_name_owner_changed(name, old_owner, new_owner):
            if name == WATCHER_NAME and new_owner:
                loop.create_task(self._reregister(bus))

        dbus_iface.on_name_owner_changed(on_name_owner_changed)

    async def _reregister(self, bus):
        try:
            await self._register(bus)
        except Exception:
            logger.exception("Erneute Tray-Anmeldung nach Watcher-Neustart fehlgeschlagen")

    def notify(self, message, title="Zeiterfassung"):
        """Toast über org.freedesktop.Notifications. Fehlertolerant wie auf den
        anderen Plattformen — ein fehlender Toast darf nie den Sync stören.

        Bewusst OHNE `.result()`: notify() läuft auf dem Tk-Thread (Aufrufer ist
        `sync_orchestrator._on_tray_done` bzw. die Reminder-Scheduler). Ein
        hängender Benachrichtigungsdienst würde die UI sonst einfrieren.
        """
        loop, bus = self._loop, self._bus
        if loop is None or bus is None:
            return
        try:
            future = asyncio.run_coroutine_threadsafe(self._notify(message, title), loop)
        except Exception:
            logger.exception("Linux-Tray-Notify konnte nicht eingereiht werden")
            return
        future.add_done_callback(_log_notify_failure)

    async def _notify(self, message, title):
        from dbus_fast import Message  # pyright: ignore[reportMissingImports]  # dbus-fast: nur auf Linux installiert

        icon = os.path.join(self.base_path, "assets", "margenheld-icon.png")
        await self._bus.call(Message(
            destination=NOTIFY_NAME, path=NOTIFY_PATH, interface=NOTIFY_NAME,
            member="Notify", signature="susssasa{sv}i",
            body=[
                "Zeiterfassung",
                0,                      # replaces_id 0: Toasts überschreiben sich nicht
                icon if os.path.exists(icon) else "",
                title or "Zeiterfassung",
                message,
                [], {}, -1,
            ],
        ))

    def stop(self):
        """Signalisiert dem Loop-Thread das Ende und joint ihn. Idempotent.

        Der eigentliche Abbau (release_name/disconnect) passiert im Loop-Thread
        am Ende von `_serve` — hier wird nur das Event gesetzt (threadsafe über
        `call_soon_threadsafe`, weil `asyncio.Event.set` es nicht ist).
        """
        loop, self._loop = self._loop, None
        stopping = self._stopping
        if loop is not None and stopping is not None and not loop.is_closed():
            try:
                loop.call_soon_threadsafe(stopping.set)
            except RuntimeError:
                # Loop war schon zu (z.B. nach fehlgeschlagenem start()).
                logger.debug("Linux-Tray-Loop war beim Stoppen bereits beendet")
        if self._thread is not None:
            self._thread.join(timeout=self.SHUTDOWN_TIMEOUT_S)
            self._thread = None
        self._bus = None
        self._name = None
        self._stopping = None
```

Außerdem oben im Modul den `noqa`-Kommentar am `build_menu_model`-Import entfernen — er wird jetzt benutzt:

```python
from src.tray import build_menu_model
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_tray_linux.py -v`
Expected: PASS (18 Tests; der Bus-Test skippt ohne `dbus_fast`)

- [ ] **Step 5: Commit**

```bash
git add src/tray_linux.py tests/test_tray_linux.py
git commit -m "feat(tray): Lebenszyklus des Linux-SNI-Backends (start/stop/notify) (#42)"
```

---

### Task 6: Gate und Backend-Auswahl in der Fassade

**Files:**
- Modify: `src/tray.py:1-10` (Modul-Docstring), `:19-37` (Opt-in + `is_supported`), `:64-72` (`_select_backend`), `:96-101` (Plattform-Vergleich im Klassen-Docstring)
- Test: `tests/test_tray.py:7-19`, `:56-61`

**Interfaces:**
- Consumes: `src.tray_linux.LinuxTrayBackend` (Task 5).
- Produces: `is_supported()` → auf Linux `True` **nur** mit `ZEIT_LINUX_TRAY=1`; `_select_backend("Linux")` → `LinuxTrayBackend`.

- [ ] **Step 1: Write the failing test**

In `tests/test_tray.py` die Parametrisierung ersetzen und den Dispatch-Test anpassen:

```python
@pytest.mark.parametrize("system,mac_optin,linux_optin,expected", [
    ("Windows", None, None, True),
    ("Linux", None, None, False),    # dormant-Default
    ("Linux", None, "1", True),      # opt-in für den Plasma-Tester
    ("Darwin", None, None, False),   # dormant-Default
    ("Darwin", "1", None, True),     # opt-in für den Mac-Tester
])
def test_is_supported_staging(system, mac_optin, linux_optin, expected, monkeypatch):
    monkeypatch.setattr("src.tray.platform.system", lambda: system)
    for var, value in (("ZEIT_MACOS_TRAY", mac_optin), ("ZEIT_LINUX_TRAY", linux_optin)):
        if value is None:
            monkeypatch.delenv(var, raising=False)
        else:
            monkeypatch.setenv(var, value)
    assert tray.is_supported() is expected


def test_select_backend_dispatch():
    from src.tray import _select_backend, _PystrayBackend
    from src.tray_linux import LinuxTrayBackend
    from src.tray_mac import MacTrayBackend
    assert _select_backend("Windows") is _PystrayBackend
    assert _select_backend("Darwin") is MacTrayBackend
    assert _select_backend("Linux") is LinuxTrayBackend
    assert _select_backend("Haiku") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_tray.py -v`
Expected: FAIL — `assert False is True` beim Linux-Opt-in und `assert None is LinuxTrayBackend`

- [ ] **Step 3: Write minimal implementation**

`src/tray.py` — den Modul-Docstring-Schluss ersetzen:

```python
"""System-Tray-Icon — Plattform-Fassade über drei Backends.

`TrayIcon` wählt per platform.system(): Windows → `_PystrayBackend` (pystray im
Daemon-Thread, UI-Aktionen via `root.after(0, …)` auf den Tk-Thread). macOS →
`MacTrayBackend` (src/tray_mac.py): natives NSStatusItem SYNCHRON auf dem
Main-Thread, KEIN Thread, keine zweite NSApplication (Fix #88). Linux →
`LinuxTrayBackend` (src/tray_linux.py): StatusNotifierItem über D-Bus, ohne GTK
oder GObject-Introspection (#42). macOS und Linux sind bis zu ihrem manuellen
Plattform-Gate dormant (Opt-in `ZEIT_MACOS_TRAY=1` bzw. `ZEIT_LINUX_TRAY=1`,
s. is_supported). `build_menu_model` ist die backend-agnostische, testbare Naht.
"""
```

Opt-in-Helfer neben `_macos_tray_opt_in` ergänzen:

```python
def _linux_tray_opt_in():
    """Linux-Tray ist bis zum bestandenen Plasma-Gate dormant: nur aktiv, wenn
    der Tester ZEIT_LINUX_TRAY=1 setzt (#42, analog macOS). Der Default-an-Flip
    ersetzt diese Prüfung später durch „läuft ein StatusNotifierWatcher?"."""
    return os.environ.get("ZEIT_LINUX_TRAY") == "1"
```

`is_supported()` ersetzen:

```python
def is_supported():
    """Kann auf diesem System ein Tray-Icon gezeigt werden?

    Windows → True. macOS und Linux → nur mit Opt-in (dormant-Default, s.
    _macos_tray_opt_in / _linux_tray_opt_in). Aufrufer kann unabhängig davon
    `try/except` machen, falls das Backend zur Laufzeit doch fehlschlägt.
    """
    system = platform.system()
    if system == "Windows":
        return True
    if system == "Darwin":
        return _macos_tray_opt_in()
    if system == "Linux":
        return _linux_tray_opt_in()
    return False
```

`_select_backend` ersetzen:

```python
def _select_backend(system):
    """Backend-Klasse nach Plattform. macOS und Linux lazy, damit PyObjC bzw.
    dbus_fast nicht in den jeweils fremden Importpfad geraten."""
    if system == "Windows":
        return _PystrayBackend
    if system == "Darwin":
        from src.tray_mac import MacTrayBackend
        return MacTrayBackend
    if system == "Linux":
        from src.tray_linux import LinuxTrayBackend
        return LinuxTrayBackend
    return None
```

Im `_PystrayBackend`-Klassendocstring den Plattform-Absatz zu `visible` abschließen — der letzte Satz („Linux hat kein Tray") wird ersetzt:

```
    Plattform-Unterschied bei `visible`: Das win32-Backend baut das Popup-Menü
    bei jedem Rechtsklick neu, wertet die Callable also LIVE aus (ein Sync-
    Eintrag erscheint/verschwindet sofort, wenn sich die Settings ändern). Das
    macOS-Backend (NSStatusItem, kein `menuNeedsUpdate:`-Delegate) baut das Menü
    dagegen nur EINMAL beim Tray-Start — dort ist `visible` ein Snapshot vom
    Start-Zeitpunkt. Für uns unkritisch: Bei verstecktem Fenster sind die
    Einstellungen nicht erreichbar, und das Icon wird ohnehin neu gebaut, wenn
    der Minimieren-Schalter umgelegt wird. Das Linux-Backend wertet `visible`
    wie Windows LIVE aus (dbusmenu `AboutToShow` vor jedem Öffnen, s.
    tray_linux.MenuState.refresh).
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_tray.py tests/test_tray_linux.py -v`
Expected: PASS

- [ ] **Step 5: Volle Suite plus Lint und Typen**

Run: `pytest && ruff check . && pyright`
Expected: alles grün (keine Regression in `test_ui_*`, die `src.ui → src.tray` importieren)

- [ ] **Step 6: Commit**

```bash
git add src/tray.py tests/test_tray.py
git commit -m "feat(tray): Linux-Backend hinter dem Opt-in-Gate freischalten (#42)"
```

---

### Task 7: Integrationstest gegen einen echten dbus-daemon

**Files:**
- Create: `tests/test_tray_linux_dbus.py`

**Interfaces:**
- Consumes: `LinuxTrayBackend` (Task 5), `MENU_PATH`/`ITEM_PATH` (Task 4).
- Produces: nichts für andere Tasks — dieser Test ist die Evidenz, dass die Signaturen über den Draht stimmen.

**Ausführung:** Der Test braucht Linux mit `dbus-daemon` und `dbus_fast`. Auf der Windows-Dev-Maschine läuft er über Docker (Docker Desktop ist vorhanden); im CI läuft er im `test-matrix`-Job mit.

```powershell
docker run --rm -v "${PWD}:/w" -w /w python:3.10-slim sh -c "apt-get update -qq && apt-get install -y -qq dbus >/dev/null && pip install -q -r requirements-test.txt && pytest tests/test_tray_linux_dbus.py tests/test_tray_linux_iface.py -v"
```

- [ ] **Step 1: Write the failing test**

```python
# tests/test_tray_linux_dbus.py
"""SNI-Backend gegen einen ECHTEN dbus-daemon (#42).

Das ist die einzige Ebene, auf der die D-Bus-Signaturen und die Rückgabewerte
der @dbus_method-Methoden wirklich geprüft werden können (der Decorator liefert
beim Direktaufruf einen None-Wrapper). Gegenstelle sind ein Fake-Watcher und ein
Fake-Notification-Dienst auf einem eigenen Session-Bus.

Läuft nur auf Linux mit dbus_fast und dbus-daemon — sonst sauberer Skip.
Lokal (Windows-Dev-Maschine) über Docker, s. Plan Task 7.
"""

import asyncio
import os
import shutil
import subprocess
import sys
import threading
import time

import pytest

pytest.importorskip("dbus_fast")
if sys.platform != "linux":
    pytest.skip("Session-Bus gibt es nur auf Linux", allow_module_level=True)
if shutil.which("dbus-daemon") is None:
    pytest.skip("dbus-daemon nicht installiert", allow_module_level=True)

from typing import Annotated

from dbus_fast import BusType, PropertyAccess, Variant  # pyright: ignore[reportMissingImports]  # dbus-fast: nur auf Linux installiert
from dbus_fast.aio import MessageBus  # pyright: ignore[reportMissingImports]  # dbus-fast: nur auf Linux installiert
from dbus_fast.annotations import (  # pyright: ignore[reportMissingImports]  # dbus-fast: nur auf Linux installiert
    DBusBool, DBusDict, DBusInt32, DBusSignature, DBusStr, DBusUInt32,
)
from dbus_fast.service import ServiceInterface, dbus_method, dbus_property  # pyright: ignore[reportMissingImports]  # dbus-fast: nur auf Linux installiert

from src.tray_linux import ITEM_PATH, MENU_PATH, LinuxTrayBackend


class _FakeWatcher(ServiceInterface):
    """Minimaler org.kde.StatusNotifierWatcher — merkt sich die Anmeldungen.

    Annotationen wie im Produktivcode über die dbus_fast-Aliase: pyright prüft
    `tests` mit (pyproject.toml), String-Signaturen wären dort rot.
    """

    def __init__(self):
        super().__init__("org.kde.StatusNotifierWatcher")
        self.registered = []

    @dbus_method()
    def RegisterStatusNotifierItem(self, service: DBusStr):
        self.registered.append(service)

    @dbus_property(PropertyAccess.READ)
    def IsStatusNotifierHostRegistered(self) -> DBusBool:
        return True

    @dbus_property(PropertyAccess.READ)
    def RegisteredStatusNotifierItems(self) -> Annotated[list, DBusSignature("as")]:
        return list(self.registered)

    @dbus_property(PropertyAccess.READ)
    def ProtocolVersion(self) -> DBusInt32:
        return 0


class _FakeNotifications(ServiceInterface):
    """Minimaler org.freedesktop.Notifications — merkt sich die Toasts."""

    def __init__(self):
        super().__init__("org.freedesktop.Notifications")
        self.messages = []

    @dbus_method()
    def Notify(self, app_name: DBusStr, replaces_id: DBusUInt32, app_icon: DBusStr,
               summary: DBusStr, body: DBusStr,
               actions: Annotated[list, DBusSignature("as")],
               hints: DBusDict, timeout: DBusInt32) -> DBusUInt32:
        self.messages.append((app_name, summary, body))
        return 1


class _LoopThread:
    """Asyncio-Loop in einem eigenen Thread — für die Fakes und den Testclient.
    Das Backend bringt seinen eigenen Thread mit; beide müssen gleichzeitig
    laufen, sonst blockiert start() auf einer Registrierung, die niemand
    beantwortet."""

    def __init__(self):
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self.loop.run_forever, daemon=True)
        self.thread.start()

    def run(self, coro, timeout=15):
        return asyncio.run_coroutine_threadsafe(coro, self.loop).result(timeout=timeout)

    def close(self):
        self.loop.call_soon_threadsafe(self.loop.stop)
        self.thread.join(timeout=5)
        self.loop.close()


@pytest.fixture()
def bus_env(monkeypatch):
    """Eigener Session-Bus pro Test — kein Kontakt zum Bus des Entwicklers."""
    proc = subprocess.Popen(
        ["dbus-daemon", "--session", "--print-address", "--nofork"],
        stdout=subprocess.PIPE, text=True,
    )
    address = proc.stdout.readline().strip()
    monkeypatch.setenv("DBUS_SESSION_BUS_ADDRESS", address)
    yield address
    proc.terminate()
    proc.wait(timeout=5)


class _Desktop:
    """Fake-Desktop auf dem Testbus: Watcher + Notification-Dienst + die Loop,
    auf der beide bedient werden."""

    def __init__(self, helper, bus, watcher, notifications):
        self.helper = helper
        self.bus = bus
        self.watcher = watcher
        self.notifications = notifications

    def run(self, coro, timeout=15):
        return self.helper.run(coro, timeout)

    def restart_watcher(self):
        """Simuliert einen plasmashell-Neustart: Name freigeben, neu belegen."""
        async def restart():
            await self.bus.release_name("org.kde.StatusNotifierWatcher")
            new_bus = await MessageBus(bus_type=BusType.SESSION).connect()
            new_bus.export("/StatusNotifierWatcher", self.watcher)
            await new_bus.request_name("org.kde.StatusNotifierWatcher")
            return new_bus

        self.bus = self.run(restart())


@pytest.fixture()
def desktop(bus_env):
    """Fake-Desktop: Watcher und Notification-Dienst laufen auf dem Testbus."""
    helper = _LoopThread()
    watcher, notifications = _FakeWatcher(), _FakeNotifications()

    async def serve():
        bus = await MessageBus(bus_type=BusType.SESSION).connect()
        bus.export("/StatusNotifierWatcher", watcher)
        bus.export("/org/freedesktop/Notifications", notifications)
        await bus.request_name("org.kde.StatusNotifierWatcher")
        await bus.request_name("org.freedesktop.Notifications")
        return bus

    bus = helper.run(serve())
    fake = _Desktop(helper, bus, watcher, notifications)
    yield fake
    fake.bus.disconnect()
    helper.close()


def _wait_for(predicate, timeout=5):
    """Auf eine Zustellung über den Bus warten (die läuft asynchron in fremden
    Threads) — statt sofort zu prüfen und sporadisch rot zu sein."""
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        time.sleep(0.05)
    return predicate()


def _backend(clicked):
    return LinuxTrayBackend(
        ".",
        on_show=lambda: clicked.append("show"),
        on_quit=lambda: clicked.append("quit"),
        actions=[("Senden", lambda: clicked.append("send"), None),
                 ("Sync", lambda: clicked.append("sync"), lambda: True)],
    )


async def _menu_proxy(bus, name):
    introspection = await bus.introspect(name, MENU_PATH)
    return bus.get_proxy_object(name, MENU_PATH, introspection) \
              .get_interface("com.canonical.dbusmenu")


async def _item_proxy(bus, name):
    introspection = await bus.introspect(name, ITEM_PATH)
    return bus.get_proxy_object(name, ITEM_PATH, introspection) \
              .get_interface("org.kde.StatusNotifierItem")


def test_backend_registers_itself_with_the_watcher(desktop):
    backend = _backend([])
    backend.start()
    try:
        assert desktop.watcher.registered == [
            f"org.kde.StatusNotifierItem-{os.getpid()}-1"]
    finally:
        backend.stop()


def test_menu_layout_carries_all_entries_in_order(desktop):
    backend = _backend([])
    backend.start()
    try:
        async def read_labels():
            bus = await MessageBus(bus_type=BusType.SESSION).connect()
            menu = await _menu_proxy(bus, desktop.watcher.registered[0])
            _revision, layout = await menu.call_get_layout(0, -1, [])
            _root_id, _root_props, children = layout
            labels = []
            for child in children:
                props = child.value[1]
                labels.append(props["label"].value if "label" in props else "—")
            bus.disconnect()
            return labels

        assert desktop.run(read_labels()) == [
            "Anzeigen", "—", "Senden", "Sync", "—", "Beenden",
        ]
    finally:
        backend.stop()


def test_clicking_a_menu_entry_runs_its_callback(desktop):
    clicked = []
    backend = _backend(clicked)
    backend.start()
    try:
        async def click_send():
            bus = await MessageBus(bus_type=BusType.SESSION).connect()
            menu = await _menu_proxy(bus, desktop.watcher.registered[0])
            _revision, layout = await menu.call_get_layout(0, -1, [])
            send_id = next(
                child.value[0] for child in layout[2]
                if child.value[1].get("label") is not None
                and child.value[1]["label"].value == "Senden"
            )
            await menu.call_event(send_id, "clicked", Variant("s", ""), 0)
            bus.disconnect()

        desktop.run(click_send())
        assert clicked == ["send"]
    finally:
        backend.stop()


def test_left_click_activates_and_shows_the_window(desktop):
    clicked = []
    backend = _backend(clicked)
    backend.start()
    try:
        async def activate():
            bus = await MessageBus(bus_type=BusType.SESSION).connect()
            item = await _item_proxy(bus, desktop.watcher.registered[0])
            assert await item.get_item_is_menu() is False
            await item.call_activate(0, 0)
            bus.disconnect()

        desktop.run(activate())
        assert clicked == ["show"]
    finally:
        backend.stop()


def test_notify_reaches_the_notification_service(desktop):
    backend = _backend([])
    backend.start()
    try:
        backend.notify("Synchronisiert.", "Zeiterfassung")
        # notify() ist bewusst fire-and-forget (es läuft auf dem Tk-Thread) —
        # also auf die Zustellung warten statt sofort zu prüfen.
        assert _wait_for(lambda: bool(desktop.notifications.messages))
        assert desktop.notifications.messages == [
            ("Zeiterfassung", "Zeiterfassung", "Synchronisiert."),
        ]
    finally:
        backend.stop()


def test_item_reregisters_after_the_watcher_restarts(desktop):
    """plasmashell-Neustart: der Watcher verschwindet und kommt wieder — das
    Item muss sich von selbst neu anmelden, sonst ist das Icon dauerhaft weg."""
    backend = _backend([])
    backend.start()
    try:
        assert len(desktop.watcher.registered) == 1
        desktop.restart_watcher()
        assert _wait_for(lambda: len(desktop.watcher.registered) == 2)
        assert desktop.watcher.registered[1] == desktop.watcher.registered[0]
    finally:
        backend.stop()


def test_stop_releases_the_bus_name(desktop):
    backend = _backend([])
    backend.start()
    name = desktop.watcher.registered[0]
    backend.stop()

    async def owner_gone():
        bus = await MessageBus(bus_type=BusType.SESSION).connect()
        introspection = await bus.introspect("org.freedesktop.DBus", "/org/freedesktop/DBus")
        dbus_iface = bus.get_proxy_object(
            "org.freedesktop.DBus", "/org/freedesktop/DBus", introspection
        ).get_interface("org.freedesktop.DBus")
        has_owner = await dbus_iface.call_name_has_owner(name)
        bus.disconnect()
        return has_owner

    assert desktop.run(owner_gone()) is False
```

- [ ] **Step 2: Run test to verify it fails**

Run (PowerShell, Repo-Root):

```powershell
docker run --rm -v "${PWD}:/w" -w /w python:3.10-slim sh -c "apt-get update -qq && apt-get install -y -qq dbus >/dev/null && pip install -q -r requirements-test.txt && pytest tests/test_tray_linux_dbus.py -v"
```

Expected: Zuerst rot, solange eine Signatur oder ein Rückgabewert nicht stimmt — genau dafür ist dieser Test da. Läuft er beim ersten Versuch grün, bestätigt er Task 4/5; läuft er rot, wird **hier** korrigiert (Signaturen in `_make_interfaces`), nicht auf dem Plasma-Rechner.

- [ ] **Step 3: Korrekturen aus dem Rotlauf einarbeiten**

Typische Fundstellen in dieser Reihenfolge prüfen:
1. `GetLayout`-Rückgabe: äußere Liste `[revision, [root_id, props, children]]`, Kinder als `Variant("(ia{sv}av)", …)`.
2. Property-Variants: jeder Schlüssel muss in `PROP_SIGNATURES` stehen — ein fehlender Eintrag wirft `KeyError` im Adapter.
3. `AboutToShowGroup`-Signatur `"aiai"` (zwei Out-Args), `EventGroup`-Eingang `"a(isvu)"`.
4. `Notify`-Signatur `"susssasa{sv}i"` und die acht Body-Elemente in genau dieser Reihenfolge.

- [ ] **Step 4: Run test to verify it passes**

Run (Docker-Kommando aus Schritt 2, zusätzlich `tests/test_tray_linux_iface.py`)
Expected: PASS (7 Bus-Tests + 5 Adapter-Tests)

- [ ] **Step 5: Commit**

```bash
git add tests/test_tray_linux_dbus.py src/tray_linux.py
git commit -m "test(tray): SNI-Backend gegen echten dbus-daemon verifizieren (#42)"
```

---

### Task 8: Dokumentation

**Files:**
- Modify: `README.md:375-383` (Plattform-Tabelle)
- Modify: `CLAUDE.md` (Modul-Liste beim `tray.py`-Eintrag)
- Modify: `src/CLAUDE.md` (Tray-Abschnitt)
- Modify: `docs/known-limitations.md:111`

**Interfaces:**
- Consumes: das fertige Verhalten aus Task 1–7. Kein Code.

- [ ] **Step 1: README — Tray-Zeile in die Plattform-Tabelle**

Nach der Zeile `| Autostart bei Anmeldung | … |` einfügen:

```markdown
| Infobereich-Icon (Tray) | ✓ (pystray) | ○ (NSStatusItem, Opt-in `ZEIT_MACOS_TRAY=1`) | ○ (StatusNotifierItem, Opt-in `ZEIT_LINUX_TRAY=1`) |
```

Direkt unter die Tabelle:

```markdown
○ = implementiert, aber bis zum manuellen Plattform-Test dormant. Das Linux-Tray
spricht StatusNotifierItem über D-Bus (KDE Plasma, XFCE, GNOME mit
AppIndicator-Extension); Desktops ohne StatusNotifierWatcher bekommen wie bisher
kein Icon. Unter Wayland holt ein Klick das Fenster zurück, das Anheben in den
Vordergrund darf der Compositor aber verweigern.
```

- [ ] **Step 2: CLAUDE.md — Modul-Liste**

Den `tray.py`-Eintrag ersetzen:

```markdown
- `src/tray.py` — Infobereich-Icon (Minimize-to-Tray); Plattform-Fassade über pystray (Windows), `tray_mac.py` (macOS) und `tray_linux.py` (Linux)
- `src/tray_linux.py` — Linux-Tray über StatusNotifierItem + `com.canonical.dbusmenu` (D-Bus via `dbus-fast`, kein GTK/GI); dormant bis zum Plasma-Gate (Opt-in `ZEIT_LINUX_TRAY=1`, #42). Menü-Logik D-Bus-frei in `MenuState`
```

- [ ] **Step 3: src/CLAUDE.md — Tray-Abschnitt**

Die Zeile `- `tray.py` (Fassade) + `tray_mac.py` (…)` ersetzen:

```markdown
- `tray.py` (Fassade) + `tray_mac.py` (natives macOS-NSStatusItem-Backend, #88)
  + `tray_linux.py` (StatusNotifierItem über D-Bus, #42). Beide Nicht-Windows-
  Backends sind dormant hinter einer Opt-in-Env-Var, bis ihr manuelles
  Plattform-Gate grün ist.
```

Und den Absatz zu `_tray_actions()` um einen Satz ergänzen:

```markdown
Die `visible`-Callable wird auf Windows und Linux LIVE ausgewertet (pystray baut
das Popup neu, dbusmenu fragt vor jedem Öffnen `AboutToShow`), auf macOS ist sie
ein Snapshot vom Tray-Start.
```

- [ ] **Step 4: known-limitations.md**

Die Aufzählung in Zeile 111 anpassen — der Linux/KDE-Tray ist kein reines Gegenbeispiel mehr, sondern der Beleg für den Zuschnitt:

```markdown
(`<Button-2>`/Control-Klick, ✕-Delete-Gate), Fenster-Chrome und die Darstellung
des Linux-Trays in Plasma (#42) — deckt ein Linux-Framebuffer strukturell ohnehin
nicht ab. Beim Linux-Tray zeigt sich dabei genau der Zuschnitt-Gedanke: die
dbusmenu-Logik liegt D-Bus-frei in `tray_linux.MenuState` und wird überall
getestet, die Wire-Ebene gegen einen echten `dbus-daemon` — offen bleibt nur,
was Plasma daraus zeichnet.
```

- [ ] **Step 5: Verify**

Run: `pytest && ruff check .`
Expected: PASS (Doku-Änderungen brechen nichts; der Lauf bestätigt den Gesamtstand)

- [ ] **Step 6: Commit**

```bash
git add README.md CLAUDE.md src/CLAUDE.md docs/known-limitations.md
git commit -m "docs: Linux-SNI-Tray dokumentieren (#42)"
```

---

## Abschluss: Verifikation und Übergabe

- [ ] **Volle Suite lokal:** `pytest && ruff check . && pyright`
- [ ] **Linux-Pfad in Docker:** das Kommando aus Task 7 (deckt `test_tray_linux_iface.py` und `test_tray_linux_dbus.py` ab)
- [ ] **PR öffnen** (erst auf ausdrückliche Ansage — Push ist eine schreibende Remote-Op)
- [ ] **Pre-Release vorschlagen:** Der PR ist plattformspezifisch (`CLAUDE.md`, „Plattformspezifische PRs"). Nach dem Merge Actions → Release → „Run workflow" mit Häkchen *prerelease*, damit eine AppImage mit `dbus_fast` entsteht.
- [ ] **Manuelles Plasma-Gate** auf Debian 13 / Plasma 6, AppImage mit `ZEIT_LINUX_TRAY=1` starten:
  - Icon erscheint im Systemabschnitt
  - Linksklick holt das Fenster zurück
  - Rechtsklick zeigt Anzeigen / Senden / Teilen / Export / Sync / Beenden
  - Sync-Eintrag erscheint und verschwindet mit `sync_enabled`
  - Fenster schließen minimiert in den Systemabschnitt, „Beenden" beendet sauber
  - Reservierungs-Erinnerung erscheint als Toast
  - nach `plasmashell --replace` ist das Icon wieder da
- [ ] **Erst danach** der separate Flip-PR: Env-Var raus, Watcher-Probe rein, Default an.
