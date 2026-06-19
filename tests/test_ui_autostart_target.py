# tests/test_ui_autostart_target.py
import sys
from src.autostart import resolve_autostart_target


def test_repo_mode_returns_python_interpreter(monkeypatch):
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    target, args = resolve_autostart_target("/repo")
    assert target == sys.executable
    assert args.endswith("main.py --minimized")
    assert "/repo" in args or "\\repo" in args


def test_frozen_windows_uses_sys_executable(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "Zeiterfassung.exe"))
    monkeypatch.setattr("src.autostart.platform.system", lambda: "Windows")
    target, args = resolve_autostart_target("/ignored")
    assert target == str(tmp_path / "Zeiterfassung.exe")
    assert args == "--minimized"


def test_frozen_macos_uses_sys_executable(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "Zeiterfassung"))
    monkeypatch.setattr("src.autostart.platform.system", lambda: "Darwin")
    target, args = resolve_autostart_target("/ignored")
    assert target == str(tmp_path / "Zeiterfassung")
    assert args == "--minimized"


def test_frozen_linux_prefers_appimage_env(monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", "/tmp/_MEIxxx/Zeiterfassung")
    monkeypatch.setattr("src.autostart.platform.system", lambda: "Linux")
    monkeypatch.setenv("APPIMAGE", "/home/u/Apps/Zeiterfassung.AppImage")
    target, args = resolve_autostart_target("/ignored")
    assert target == "/home/u/Apps/Zeiterfassung.AppImage"
    assert args == "--minimized"


def test_frozen_linux_falls_back_to_sys_executable(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "Zeiterfassung"))
    monkeypatch.setattr("src.autostart.platform.system", lambda: "Linux")
    monkeypatch.delenv("APPIMAGE", raising=False)
    target, args = resolve_autostart_target("/ignored")
    assert target == str(tmp_path / "Zeiterfassung")
    assert args == "--minimized"
