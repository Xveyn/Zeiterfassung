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
from src.tray.linux import MENU_PATH, MenuState, _make_interfaces


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
