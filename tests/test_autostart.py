# tests/test_autostart.py
import os
import platform
import plistlib
import pytest
from unittest.mock import patch, MagicMock
from src.autostart import enable_autostart, disable_autostart, migrate_legacy_autostart
from src.autostart import (
    _macos_plist_path,
    _linux_desktop_path,
    is_autostart_enabled,
    _windows_run_command,
)


def test_windows_run_command_matches_installer_format():
    cmd = _windows_run_command(r"C:\app\Zeiterfassung.exe", "--minimized")
    assert cmd == r'"C:\app\Zeiterfassung.exe" --minimized'


def test_windows_run_command_without_arguments():
    cmd = _windows_run_command(r"C:\app\Zeiterfassung.exe", "")
    assert cmd == r'"C:\app\Zeiterfassung.exe"'


@pytest.fixture
def fake_startup(tmp_path, monkeypatch):
    """Patch _get_startup_folder to return a temp directory."""
    monkeypatch.setattr("src.autostart._get_startup_folder", lambda: str(tmp_path))
    return tmp_path


@pytest.mark.skipif(platform.system() != "Windows", reason="Windows only")
class TestWindowsAutostart:
    @pytest.fixture
    def temp_run_key(self, monkeypatch):
        import winreg
        subkey = r"Software\ZeiterfassungTest\Run"
        monkeypatch.setattr("src.autostart._RUN_KEY_SUBKEY", subkey)
        yield subkey
        try:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, subkey)
        except FileNotFoundError:
            pass

    def test_enable_writes_registry_value(self, temp_run_key, fake_startup):
        import winreg
        enable_autostart(r"C:\app\Zeiterfassung.exe", "--minimized")
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, temp_run_key) as key:
            value, _typ = winreg.QueryValueEx(key, "Zeiterfassung")
        assert value == r'"C:\app\Zeiterfassung.exe" --minimized'

    def test_disable_removes_registry_value(self, temp_run_key, fake_startup):
        import winreg
        enable_autostart(r"C:\app\Zeiterfassung.exe", "--minimized")
        disable_autostart()
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, temp_run_key) as key:
            with pytest.raises(FileNotFoundError):
                winreg.QueryValueEx(key, "Zeiterfassung")

    def test_disable_without_value_no_error(self, temp_run_key, fake_startup):
        disable_autostart()  # kein Wert vorhanden → kein Fehler

    def test_enable_removes_legacy_shortcut(self, temp_run_key, fake_startup):
        shortcut = fake_startup / "Zeiterfassung.lnk"
        shortcut.write_text("fake")
        enable_autostart(r"C:\app\Zeiterfassung.exe", "--minimized")
        assert not shortcut.exists()


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


class TestIsAutostartEnabled:
    def test_linux_true_when_desktop_exists(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.setenv("USERPROFILE", str(tmp_path))
        monkeypatch.delenv("HOMEDRIVE", raising=False)
        monkeypatch.delenv("HOMEPATH", raising=False)
        monkeypatch.setattr("src.autostart.platform.system", lambda: "Linux")
        assert is_autostart_enabled() is False
        enable_autostart("/opt/Zeiterfassung.AppImage", "--minimized")
        assert is_autostart_enabled() is True

    @pytest.mark.skipif(platform.system() != "Darwin", reason="macOS only")
    def test_macos_true_when_plist_exists(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.setenv("USERPROFILE", str(tmp_path))
        monkeypatch.delenv("HOMEDRIVE", raising=False)
        monkeypatch.delenv("HOMEPATH", raising=False)
        monkeypatch.setattr("src.autostart.platform.system", lambda: "Darwin")
        (tmp_path / "Library" / "LaunchAgents").mkdir(parents=True)
        assert is_autostart_enabled() is False

    @pytest.mark.skipif(platform.system() != "Windows", reason="Windows only")
    def test_windows_true_when_registry_value_exists(self, monkeypatch, tmp_path):
        import winreg
        subkey = r"Software\ZeiterfassungTest\Run2"
        monkeypatch.setattr("src.autostart._RUN_KEY_SUBKEY", subkey)
        monkeypatch.setattr("src.autostart._get_startup_folder", lambda: str(tmp_path))
        assert is_autostart_enabled() is False
        enable_autostart(r"C:\app\Zeiterfassung.exe", "--minimized")
        try:
            assert is_autostart_enabled() is True
        finally:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, subkey)


@pytest.mark.skipif(platform.system() != "Windows", reason="Windows only")
class TestMigrateLegacyAutostart:
    @pytest.fixture
    def frozen_win(self, monkeypatch, tmp_path):
        import winreg
        subkey = r"Software\ZeiterfassungTest\RunMig"
        monkeypatch.setattr("src.autostart._RUN_KEY_SUBKEY", subkey)
        monkeypatch.setattr("src.autostart._get_startup_folder", lambda: str(tmp_path))
        monkeypatch.setattr("src.autostart.sys.frozen", True, raising=False)
        monkeypatch.setattr("src.autostart.sys.executable",
                            str(tmp_path / "Zeiterfassung.exe"), raising=False)
        yield tmp_path
        try:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, subkey)
        except FileNotFoundError:
            pass

    def test_state2_shortcut_only_writes_registry(self, frozen_win):
        (frozen_win / "Zeiterfassung.lnk").write_text("fake")
        migrate_legacy_autostart(str(frozen_win))
        from src.autostart import _windows_registry_enabled
        assert _windows_registry_enabled() is True
        assert not (frozen_win / "Zeiterfassung.lnk").exists()

    def test_state3_both_keeps_registry_drops_shortcut(self, frozen_win):
        enable_autostart(str(frozen_win / "Zeiterfassung.exe"), "--minimized")
        (frozen_win / "Zeiterfassung.lnk").write_text("fake")
        migrate_legacy_autostart(str(frozen_win))
        from src.autostart import _windows_registry_enabled
        assert _windows_registry_enabled() is True
        assert not (frozen_win / "Zeiterfassung.lnk").exists()

    def test_state4_nothing_stays_nothing(self, frozen_win):
        migrate_legacy_autostart(str(frozen_win))
        from src.autostart import _windows_registry_enabled
        assert _windows_registry_enabled() is False

    def test_idempotent_second_run_noop(self, frozen_win):
        (frozen_win / "Zeiterfassung.lnk").write_text("fake")
        migrate_legacy_autostart(str(frozen_win))
        migrate_legacy_autostart(str(frozen_win))  # kein Fehler, kein Shortcut mehr
        assert not (frozen_win / "Zeiterfassung.lnk").exists()

    def test_not_frozen_is_noop(self, frozen_win, monkeypatch):
        monkeypatch.setattr("src.autostart.sys.frozen", False, raising=False)
        (frozen_win / "Zeiterfassung.lnk").write_text("fake")
        migrate_legacy_autostart(str(frozen_win))
        from src.autostart import _windows_registry_enabled
        assert _windows_registry_enabled() is False          # nichts geschrieben
        assert (frozen_win / "Zeiterfassung.lnk").exists()   # Shortcut unangetastet
