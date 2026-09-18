# tests/test_tray.py
import pytest

from src import tray


@pytest.mark.parametrize("system,mac_optin,watcher,expected", [
    ("Windows", None, False, True),
    ("Linux", None, True, True),     # Sitzung mit StatusNotifierWatcher (Plasma, XFCE, …)
    ("Linux", None, False, False),   # z. B. GNOME ohne AppIndicator-Extension
    ("Darwin", None, True, False),   # dormant-Default, Watcher ist dort egal
    ("Darwin", "1", False, True),    # opt-in für den Mac-Tester
])
def test_is_supported(system, mac_optin, watcher, expected, monkeypatch):
    monkeypatch.setattr("src.tray.platform.system", lambda: system)
    monkeypatch.setattr("src.tray.linux.watcher_available", lambda: watcher)
    if mac_optin is None:
        monkeypatch.delenv("ZEIT_MACOS_TRAY", raising=False)
    else:
        monkeypatch.setenv("ZEIT_MACOS_TRAY", mac_optin)
    assert tray.is_supported() is expected


def test_linux_no_longer_needs_the_opt_in_variable(monkeypatch):
    """Plasma-Gate bestanden (#42): die frühere Env-Var entscheidet nichts mehr."""
    monkeypatch.setattr("src.tray.platform.system", lambda: "Linux")
    monkeypatch.setattr("src.tray.linux.watcher_available", lambda: False)
    monkeypatch.setenv("ZEIT_LINUX_TRAY", "1")
    assert tray.is_supported() is False


def test_watcher_probe_says_no_without_dbus_fast(monkeypatch):
    """Ohne dbus_fast (Windows/macOS-CI, kaputter Build) ist die Antwort
    „kein Watcher", nie eine Exception."""
    import sys
    from src.tray import linux
    monkeypatch.setitem(sys.modules, "dbus_fast", None)
    monkeypatch.setitem(sys.modules, "dbus_fast.aio", None)
    assert linux.watcher_available(timeout=0.5) is False


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
    from src.tray.linux import LinuxTrayBackend
    from src.tray.mac import MacTrayBackend
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
        def __init__(self, resource_path, on_show, on_quit, actions=None):
            seen["init"] = (resource_path, on_show, on_quit, actions)

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
