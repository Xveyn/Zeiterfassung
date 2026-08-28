# src/tray/model.py
"""Backend-agnostisches Menue-Modell des Trays.

Die testbare Naht zwischen Fassade und Backends: pure Datenstruktur, keine
Plattform-API. Eigenes Modul (R7, #51), damit die Backends nicht aus ihrem
eigenen Paket-`__init__` zurueckimportieren muessen — hier zeigt alles nach
unten.
"""

from collections import namedtuple


MenuEntry = namedtuple("MenuEntry", ["kind", "label", "callback", "visible"])


def build_menu_model(on_show, on_quit, actions):
    """Backend-agnostisches Menü-Modell (pure, ohne AppKit/pystray) aus den
    Tray-Aktionen. Speist den macOS-Renderer (src/tray/mac.py) und die Tests;
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
