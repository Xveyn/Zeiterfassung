# src/device_id.py
"""Stabile Geräte-ID für den Multi-Device-Sync.

Installierte Builds (frozen): abgeleitet von einer stabilen, pro OS-Installation
eindeutigen System-ID (Windows `MachineGuid`, macOS `IOPlatformUUID`, Linux
`/etc/machine-id`) — überlebt eine Neuinstallation der App, anders als eine in
`settings.json` zufällig generierte UUID (die beim Reinstall verloren geht,
weil `settings.json` im Install-Verzeichnis liegt, s. `paths.py::get_base_path`).
Gehasht mit App-Salt, damit die rohe, OS-weite System-ID nie im Klartext in der
(Google-Drive-)Sync-Datei oder der Konflikt-UI landet.

Repo-/Skript-Modus (`python -m src.main`) nutzt dieses Modul bewusst NICHT
(s. `main.py::_ensure_device_id`) — sonst hätte eine parallel zu einer echten
Installation laufende Dev-Instanz auf demselben Rechner dieselbe device_id,
obwohl es zwei unabhängige Prozesse mit eigenen Storage-Dateien sind.

Alle Resolver liefern `None` statt zu werfen (fehlende Berechtigung, Registry-
Key/Datei fehlt, `ioreg` nicht gefunden, unbekannte Plattform) — Caller fällt
dann auf die bisherige, in settings.json persistierte Zufalls-UUID zurück,
statt die App scheitern zu lassen.
"""

import hashlib
import platform
import re
import subprocess

_SALT = "zeiterfassung"


def _windows_machine_guid():
    import winreg
    try:
        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography",
            0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY,
        ) as key:
            value, _ = winreg.QueryValueEx(key, "MachineGuid")
        return value or None
    except OSError:
        return None


def _macos_platform_uuid():
    try:
        result = subprocess.run(
            ["ioreg", "-rd1", "-c", "IOPlatformExpertDevice"],
            capture_output=True, text=True, timeout=5, check=True,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    match = re.search(r'"IOPlatformUUID"\s*=\s*"([^"]+)"', result.stdout)
    return match.group(1) if match else None


def _linux_machine_id(paths=("/etc/machine-id", "/var/lib/dbus/machine-id")):
    # systemd schreibt /etc/machine-id; ältere/dbus-only-Systeme haben nur den
    # zweiten Pfad. Beide sind stabil pro OS-Installation. `paths` als
    # Parameter (statt hartkodiert) macht die Funktion ohne Filesystem-Mocking
    # testbar (s. tests/test_device_id.py).
    for path in paths:
        try:
            with open(path, encoding="utf-8") as f:
                value = f.read().strip()
        except OSError:
            continue
        if value:
            return value
    return None


def stable_hardware_id():
    """Rohe, plattformspezifische System-ID, oder `None` (nicht lesbar oder
    unbekannte Plattform). Ruft die Resolver über ihren Modulnamen auf (statt
    über ein bei Modul-Import gebautes Dict) — Tests monkeypatchen einzelne
    Resolver auf beliebigen Plattformen, ein vorab gebautes Dict würde dabei
    noch die alte Funktionsreferenz halten."""
    system = platform.system()
    if system == "Windows":
        return _windows_machine_guid()
    if system == "Darwin":
        return _macos_platform_uuid()
    if system == "Linux":
        return _linux_machine_id()
    return None


def derive_device_id():
    """Gehashte, stabile device_id aus der System-ID, oder `None`, wenn diese
    nicht ermittelbar ist."""
    raw = stable_hardware_id()
    if not raw:
        return None
    return hashlib.sha256(f"{_SALT}:{raw}".encode("utf-8")).hexdigest()
