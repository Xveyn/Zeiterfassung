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
from typing import Annotated

from src.tray import build_menu_model  # noqa: F401  (ab Task 5 genutzt)

logger = logging.getLogger(__name__)

ITEM_PATH = "/StatusNotifierItem"
MENU_PATH = "/MenuBar"
WATCHER_NAME = "org.kde.StatusNotifierWatcher"
WATCHER_PATH = "/StatusNotifierWatcher"
NOTIFY_NAME = "org.freedesktop.Notifications"
NOTIFY_PATH = "/org/freedesktop/Notifications"

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
