# tests/test_paths.py
import os
import sys
import pytest
from src.paths import get_base_path


def test_returns_directory():
    result = get_base_path()
    assert os.path.isdir(result)


@pytest.mark.parametrize("system", ["Windows", "Darwin", "Linux"])
def test_repo_mode_returns_project_root(system, monkeypatch):
    monkeypatch.setattr("src.paths.platform.system", lambda: system)
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    result = get_base_path()
    assert os.path.isdir(os.path.join(result, "src"))
    assert os.path.isdir(os.path.join(result, "tests"))


def test_frozen_windows_returns_exe_dir(tmp_path, monkeypatch):
    monkeypatch.setattr("src.paths.platform.system", lambda: "Windows")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "Zeiterfassung.exe"))
    assert get_base_path() == str(tmp_path)


def test_frozen_macos_returns_library_support_and_creates_dir(tmp_path, monkeypatch):
    monkeypatch.setattr("src.paths.platform.system", lambda: "Darwin")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.delenv("HOMEDRIVE", raising=False)
    monkeypatch.delenv("HOMEPATH", raising=False)
    result = get_base_path()
    expected = os.path.join(
        os.path.expanduser("~"), "Library", "Application Support", "Zeiterfassung"
    )
    assert result == expected
    assert os.path.isdir(result)


def test_frozen_linux_respects_xdg_data_home(tmp_path, monkeypatch):
    monkeypatch.setattr("src.paths.platform.system", lambda: "Linux")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    xdg = tmp_path / "xdg"
    monkeypatch.setenv("XDG_DATA_HOME", str(xdg))
    result = get_base_path()
    assert result == os.path.join(str(xdg), "Zeiterfassung")
    assert os.path.isdir(result)


def test_frozen_linux_falls_back_to_local_share(tmp_path, monkeypatch):
    monkeypatch.setattr("src.paths.platform.system", lambda: "Linux")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.delenv("HOMEDRIVE", raising=False)
    monkeypatch.delenv("HOMEPATH", raising=False)
    result = get_base_path()
    expected = os.path.join(
        os.path.expanduser("~"), ".local", "share", "Zeiterfassung"
    )
    assert result == expected
    assert os.path.isdir(result)


from src.paths import get_resource_path


class TestGetResourcePath:
    """get_resource_path liefert das BUNDLE-Verzeichnis (assets/), nicht das
    Nutzerdaten-Verzeichnis. Auf Windows fielen beide bisher zufällig zusammen,
    auf Linux/macOS nie — daher der eigene Helfer."""

    def test_frozen_uses_meipass(self, monkeypatch, tmp_path):
        monkeypatch.setattr("src.paths.sys.frozen", True, raising=False)
        monkeypatch.setattr("src.paths.sys._MEIPASS", str(tmp_path), raising=False)
        assert get_resource_path() == str(tmp_path)

    def test_frozen_without_meipass_falls_back_to_executable_dir(
            self, monkeypatch, tmp_path):
        # sys.frozen ohne _MEIPASS: kein PyInstaller-Bundle. Statt zu werfen
        # das Exe-Verzeichnis nehmen — dort lag assets/ auf Windows schon immer.
        monkeypatch.setattr("src.paths.sys.frozen", True, raising=False)
        monkeypatch.delattr("src.paths.sys._MEIPASS", raising=False)
        exe = tmp_path / "Zeiterfassung.exe"
        monkeypatch.setattr("src.paths.sys.executable", str(exe), raising=False)
        assert get_resource_path() == str(tmp_path)

    def test_script_mode_returns_repo_root(self, monkeypatch):
        monkeypatch.setattr("src.paths.sys.frozen", False, raising=False)
        root = get_resource_path()
        assert os.path.isdir(os.path.join(root, "assets"))

    def test_is_not_the_data_dir_when_they_differ(self, monkeypatch, tmp_path):
        """Der eigentliche Punkt: auf Linux zeigen die beiden Helfer
        auseinander. Fiele get_resource_path auf get_base_path zurück, wäre
        der Befund nicht behoben."""
        monkeypatch.setattr("src.paths.sys.frozen", True, raising=False)
        monkeypatch.setattr("src.paths.sys._MEIPASS", str(tmp_path / "bundle"),
                            raising=False)
        monkeypatch.setattr("src.paths.platform.system", lambda: "Linux")
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
        monkeypatch.delenv("ZEITERFASSUNG_DATA_DIR", raising=False)
        assert get_resource_path() != get_base_path()
