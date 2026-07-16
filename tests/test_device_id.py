"""device_id: stabile, hardware-abgeleitete Geräte-ID für installierte Builds.

Plattform-Resolver werden, wo sinnvoll, gegen die ECHTE Umgebung getestet
(skipif aufs jeweilige OS gegated, wie tests/test_autostart.py) — CI läuft auf
allen drei Plattformen (test.yml: ubuntu/macos/windows), sodass jeder Resolver
irgendwo real verifiziert wird. Dispatch/Hashing/Fallback-Logik ist zusätzlich
plattformunabhängig über Monkeypatching abgedeckt.
"""

import hashlib
import platform

import pytest

from src import device_id


class TestLinuxMachineId:
    """Datei-basiert, daher überall (nicht nur auf Linux) direkt testbar —
    kein Monkeypatching von builtins nötig, s. `paths`-Parameter."""

    def test_reads_first_existing_path(self, tmp_path):
        p = tmp_path / "machine-id"
        p.write_text("abc123\n", encoding="utf-8")
        assert device_id._linux_machine_id(paths=(str(p),)) == "abc123"

    def test_falls_back_to_second_path(self, tmp_path):
        missing = tmp_path / "does-not-exist"
        p = tmp_path / "dbus-machine-id"
        p.write_text("fallback-id", encoding="utf-8")
        assert device_id._linux_machine_id(paths=(str(missing), str(p))) == "fallback-id"

    def test_none_when_all_paths_missing(self, tmp_path):
        missing = tmp_path / "nope"
        assert device_id._linux_machine_id(paths=(str(missing),)) is None

    def test_none_when_file_empty(self, tmp_path):
        p = tmp_path / "empty"
        p.write_text("", encoding="utf-8")
        assert device_id._linux_machine_id(paths=(str(p),)) is None


class TestMacosPlatformUuid:
    """subprocess-Mocking ist plattformunabhängig durchführbar — die Funktion
    selbst prüft keine Plattform, das übernimmt stable_hardware_id()."""

    def test_parses_ioreg_output(self, monkeypatch):
        output = (
            '+-o J316sAP  <class IOPlatformExpertDevice>\n'
            '    "IOPlatformUUID" = "1F2E3D4C-5B6A-7988-9A0B-1C2D3E4F5061"\n'
        )
        monkeypatch.setattr(
            device_id.subprocess, "run",
            lambda *a, **k: type("R", (), {"stdout": output})())
        assert device_id._macos_platform_uuid() == "1F2E3D4C-5B6A-7988-9A0B-1C2D3E4F5061"

    def test_none_when_ioreg_missing(self, monkeypatch):
        def _raise(*a, **k):
            raise FileNotFoundError("ioreg not found")
        monkeypatch.setattr(device_id.subprocess, "run", _raise)
        assert device_id._macos_platform_uuid() is None

    def test_none_when_output_unparseable(self, monkeypatch):
        monkeypatch.setattr(
            device_id.subprocess, "run",
            lambda *a, **k: type("R", (), {"stdout": "no uuid here"})())
        assert device_id._macos_platform_uuid() is None


@pytest.mark.skipif(platform.system() != "Windows", reason="Windows only")
class TestWindowsMachineGuidReal:
    def test_reads_real_machine_guid(self):
        value = device_id._windows_machine_guid()
        assert value is not None
        # MachineGuid ist ein GUID: 8-4-4-4-12 Hex-Zeichen.
        import re
        assert re.fullmatch(
            r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
            r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}", value)

    def test_none_when_registry_key_missing(self, monkeypatch):
        import winreg

        def _raise(*a, **k):
            raise FileNotFoundError("key not found")
        monkeypatch.setattr(winreg, "OpenKey", _raise)
        assert device_id._windows_machine_guid() is None


@pytest.mark.skipif(platform.system() != "Darwin", reason="macOS only")
class TestMacosPlatformUuidReal:
    def test_reads_real_platform_uuid(self):
        value = device_id._macos_platform_uuid()
        assert value is not None
        assert len(value) > 0


@pytest.mark.skipif(platform.system() != "Linux", reason="Linux only")
class TestLinuxMachineIdReal:
    def test_reads_real_machine_id(self):
        value = device_id._linux_machine_id()
        assert value is not None
        assert len(value) > 0


class TestStableHardwareIdDispatch:
    def test_dispatches_to_windows_resolver(self, monkeypatch):
        monkeypatch.setattr(device_id.platform, "system", lambda: "Windows")
        monkeypatch.setattr(device_id, "_windows_machine_guid", lambda: "win-id")
        assert device_id.stable_hardware_id() == "win-id"

    def test_dispatches_to_macos_resolver(self, monkeypatch):
        monkeypatch.setattr(device_id.platform, "system", lambda: "Darwin")
        monkeypatch.setattr(device_id, "_macos_platform_uuid", lambda: "mac-id")
        assert device_id.stable_hardware_id() == "mac-id"

    def test_dispatches_to_linux_resolver(self, monkeypatch):
        monkeypatch.setattr(device_id.platform, "system", lambda: "Linux")
        monkeypatch.setattr(device_id, "_linux_machine_id", lambda: "linux-id")
        assert device_id.stable_hardware_id() == "linux-id"

    def test_unknown_platform_returns_none(self, monkeypatch):
        monkeypatch.setattr(device_id.platform, "system", lambda: "FreeBSD")
        assert device_id.stable_hardware_id() is None

    def test_resolver_returning_none_propagates(self, monkeypatch):
        monkeypatch.setattr(device_id.platform, "system", lambda: "Linux")
        monkeypatch.setattr(device_id, "_linux_machine_id", lambda: None)
        assert device_id.stable_hardware_id() is None


class TestDeriveDeviceId:
    def test_hashes_raw_id_with_salt(self, monkeypatch):
        monkeypatch.setattr(device_id, "stable_hardware_id", lambda: "raw-123")
        expected = hashlib.sha256(b"zeiterfassung:raw-123").hexdigest()
        assert device_id.derive_device_id() == expected

    def test_deterministic_for_same_raw_id(self, monkeypatch):
        monkeypatch.setattr(device_id, "stable_hardware_id", lambda: "same-id")
        assert device_id.derive_device_id() == device_id.derive_device_id()

    def test_different_raw_ids_yield_different_hashes(self, monkeypatch):
        monkeypatch.setattr(device_id, "stable_hardware_id", lambda: "id-a")
        hash_a = device_id.derive_device_id()
        monkeypatch.setattr(device_id, "stable_hardware_id", lambda: "id-b")
        hash_b = device_id.derive_device_id()
        assert hash_a != hash_b

    def test_none_when_hardware_id_unavailable(self, monkeypatch):
        monkeypatch.setattr(device_id, "stable_hardware_id", lambda: None)
        assert device_id.derive_device_id() is None
