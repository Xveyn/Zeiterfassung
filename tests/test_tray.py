# tests/test_tray.py
import pytest

from src import tray


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


def test_build_menu_model_structure():
    from src.tray import build_menu_model

    def show():
        return None

    def quit_():
        return None

    def vis():
        return True

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


def test_select_backend_dispatch():
    from src.tray import _select_backend, _PystrayBackend
    from src.tray_linux import LinuxTrayBackend
    from src.tray_mac import MacTrayBackend
    assert _select_backend("Windows") is _PystrayBackend
    assert _select_backend("Darwin") is MacTrayBackend
    assert _select_backend("Linux") is LinuxTrayBackend
    assert _select_backend("Haiku") is None


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
