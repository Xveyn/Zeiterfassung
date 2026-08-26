# tests/test_main_linux_integration.py
"""Der Startup-Hook: beide Selbstheilungen laufen, und ein Fehler darin darf
den Start NIE verhindern (best-effort, wie das Logging-Setup)."""

import pytest

from src.main import _refresh_linux_integration


@pytest.fixture
def linux_frozen(tmp_path, monkeypatch):
    monkeypatch.setattr("src.main.platform.system", lambda: "Linux")
    monkeypatch.setattr("src.main.sys.frozen", True, raising=False)
    monkeypatch.setenv("APPIMAGE", "/home/sven/Zeiterfassung-2.0.0.AppImage")
    return tmp_path


def test_writes_menu_entry_and_refreshes_autostart(linux_frozen, monkeypatch):
    calls = []
    monkeypatch.setattr("src.main.refresh_linux_target",
                        lambda base: calls.append(("autostart", base)))
    monkeypatch.setattr("src.main.ensure_icon",
                        lambda res, data: "/data/icon.png")
    monkeypatch.setattr("src.main.write_menu_entry",
                        lambda target, icon: calls.append(("menu", target, icon)))

    _refresh_linux_integration(str(linux_frozen))

    assert ("autostart", str(linux_frozen)) in calls
    assert ("menu", "/home/sven/Zeiterfassung-2.0.0.AppImage",
            "/data/icon.png") in calls


def test_noop_on_windows(linux_frozen, monkeypatch):
    monkeypatch.setattr("src.main.platform.system", lambda: "Windows")
    calls = []
    monkeypatch.setattr("src.main.write_menu_entry",
                        lambda target, icon: calls.append("menu"))
    monkeypatch.setattr("src.main.refresh_linux_target", lambda base: None)
    _refresh_linux_integration(str(linux_frozen))
    assert calls == []


def test_noop_without_appimage_env(linux_frozen, monkeypatch):
    monkeypatch.delenv("APPIMAGE", raising=False)
    calls = []
    monkeypatch.setattr("src.main.write_menu_entry",
                        lambda target, icon: calls.append("menu"))
    monkeypatch.setattr("src.main.refresh_linux_target", lambda base: None)
    _refresh_linux_integration(str(linux_frozen))
    assert calls == []


def test_a_throwing_step_does_not_escape(linux_frozen, monkeypatch):
    """Ein nicht schreibbares ~/.local/share/applications darf den Start nicht
    verhindern — ungeschriebener Menüeintrag ist der Status quo, ein
    verhinderter Start wäre eine Regression."""
    def boom(*args, **kwargs):
        raise OSError("read-only filesystem")

    monkeypatch.setattr("src.main.refresh_linux_target", boom)
    monkeypatch.setattr("src.main.ensure_icon", boom)
    monkeypatch.setattr("src.main.write_menu_entry", boom)

    _refresh_linux_integration(str(linux_frozen))   # darf nicht werfen
