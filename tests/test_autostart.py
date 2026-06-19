# tests/test_autostart.py
import os
import platform
import plistlib
import pytest
from unittest.mock import patch, MagicMock
from src.autostart import enable_autostart, disable_autostart, _get_startup_folder, _get_shortcut_path
from src.autostart import (
    _macos_plist_path,
    _linux_desktop_path,
)


@pytest.fixture
def fake_startup(tmp_path, monkeypatch):
    """Patch _get_startup_folder to return a temp directory."""
    monkeypatch.setattr("src.autostart._get_startup_folder", lambda: str(tmp_path))
    return tmp_path


@pytest.mark.skipif(platform.system() != "Windows", reason="Windows only")
class TestWindowsAutostart:

    def test_get_startup_folder_returns_existing_dir(self):
        folder = _get_startup_folder()
        assert os.path.isdir(folder)

    def test_get_shortcut_path(self, fake_startup):
        path = _get_shortcut_path()
        assert path == str(fake_startup / "Zeiterfassung.lnk")

    def test_enable_creates_shortcut(self, fake_startup):
        with patch("src.autostart.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            enable_autostart(r"C:\app\Zeiterfassung.exe", "--minimized")
            mock_run.assert_called_once()
            args = mock_run.call_args[0][0]
            assert args[0] == "cscript"
            assert args[1] == "//nologo"
            assert args[2].endswith(".vbs")

    def test_enable_cleans_up_vbs(self, fake_startup):
        with patch("src.autostart.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            enable_autostart(r"C:\app\Zeiterfassung.exe", "--minimized")
            vbs_path = mock_run.call_args[0][0][2]
            assert not os.path.exists(vbs_path)

    def test_disable_removes_shortcut(self, fake_startup):
        shortcut = fake_startup / "Zeiterfassung.lnk"
        shortcut.write_text("fake")
        assert shortcut.exists()
        disable_autostart()
        assert not shortcut.exists()

    def test_disable_no_shortcut_no_error(self, fake_startup):
        disable_autostart()


class TestMacOSAutostart:
    @pytest.fixture
    def fake_home(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.setenv("USERPROFILE", str(tmp_path))
        monkeypatch.delenv("HOMEDRIVE", raising=False)
        monkeypatch.delenv("HOMEPATH", raising=False)
        monkeypatch.setattr("src.autostart.platform.system", lambda: "Darwin")
        agents = tmp_path / "Library" / "LaunchAgents"
        agents.mkdir(parents=True)
        return tmp_path

    def test_plist_path(self, fake_home):
        expected = os.path.join(
            str(fake_home), "Library", "LaunchAgents", "com.margenheld.zeiterfassung.plist"
        )
        assert _macos_plist_path() == expected

    def test_enable_writes_plist_with_correct_content(self, fake_home):
        with patch("src.autostart.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            enable_autostart(
                "/Applications/Zeiterfassung.app/Contents/MacOS/Zeiterfassung",
                "--minimized",
            )
        plist_path = _macos_plist_path()
        assert os.path.exists(plist_path)
        with open(plist_path, "rb") as f:
            data = plistlib.load(f)
        assert data["Label"] == "com.margenheld.zeiterfassung"
        assert data["ProgramArguments"] == [
            "/Applications/Zeiterfassung.app/Contents/MacOS/Zeiterfassung",
            "--minimized",
        ]
        assert data["RunAtLoad"] is True
        assert data["ProcessType"] == "Interactive"

    def test_enable_invokes_launchctl_load(self, fake_home):
        with patch("src.autostart.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            enable_autostart(
                "/Applications/Zeiterfassung.app/Contents/MacOS/Zeiterfassung",
                "--minimized",
            )
        call = mock_run.call_args_list[-1]
        args = call[0][0]
        assert args[:3] == ["launchctl", "load", "-w"]
        assert args[3] == _macos_plist_path()

    def test_disable_unloads_and_removes_plist(self, fake_home):
        plist_path = _macos_plist_path()
        with open(plist_path, "w") as f:
            f.write("<plist/>")
        with patch("src.autostart.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            disable_autostart()
        assert mock_run.call_args[0][0][:2] == ["launchctl", "unload"]
        assert not os.path.exists(plist_path)

    def test_disable_tolerates_missing_plist(self, fake_home):
        with patch("src.autostart.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            disable_autostart()

    def test_enable_is_idempotent_runs_unload_before_load(self, fake_home):
        with patch("src.autostart.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            enable_autostart(
                "/Applications/Zeiterfassung.app/Contents/MacOS/Zeiterfassung",
                "--minimized",
            )
        calls = mock_run.call_args_list
        assert len(calls) == 2
        assert calls[0][0][0][:2] == ["launchctl", "unload"]
        assert calls[1][0][0][:3] == ["launchctl", "load", "-w"]


class TestLinuxAutostart:
    @pytest.fixture
    def fake_home(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.setenv("USERPROFILE", str(tmp_path))
        monkeypatch.delenv("HOMEDRIVE", raising=False)
        monkeypatch.delenv("HOMEPATH", raising=False)
        monkeypatch.setattr("src.autostart.platform.system", lambda: "Linux")
        return tmp_path

    def test_desktop_path(self, fake_home):
        expected = os.path.join(
            str(fake_home), ".config", "autostart", "Zeiterfassung.desktop"
        )
        assert _linux_desktop_path() == expected

    def test_enable_writes_desktop_file(self, fake_home):
        enable_autostart("/opt/Zeiterfassung.AppImage", "--minimized")
        path = _linux_desktop_path()
        assert os.path.exists(path)
        content = open(path, encoding="utf-8").read()
        assert "Exec=/opt/Zeiterfassung.AppImage --minimized" in content
        assert "Type=Application" in content
        assert "Name=Zeiterfassung" in content

    def test_enable_without_arguments_has_no_trailing_space(self, fake_home):
        enable_autostart("/opt/Zeiterfassung.AppImage", "")
        content = open(_linux_desktop_path(), encoding="utf-8").read()
        assert "Exec=/opt/Zeiterfassung.AppImage\n" in content

    def test_disable_removes_desktop_file(self, fake_home):
        path = _linux_desktop_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write("fake")
        disable_autostart()
        assert not os.path.exists(path)

    def test_disable_tolerates_missing_file(self, fake_home):
        disable_autostart()
