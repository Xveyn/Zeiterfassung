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
