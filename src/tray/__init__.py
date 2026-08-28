# src/tray/__init__.py
"""System-Tray-Icon — Plattform-Fassade über vier Backends.

`TrayIcon` wählt per platform.system(): Windows → `_PystrayBackend`
(`tray/windows.py`: pystray im Daemon-Thread, UI-Aktionen via `root.after(0, …)`
auf den Tk-Thread). macOS → `MacTrayBackend` (`tray/mac.py`): natives
NSStatusItem SYNCHRON auf dem Main-Thread, KEIN Thread, keine zweite
NSApplication (Fix #88). Linux → `LinuxTrayBackend` (`tray/linux.py`):
StatusNotifierItem über D-Bus, ohne GTK oder GObject-Introspection (#42).
macOS und Linux sind bis zu ihrem manuellen Plattform-Gate dormant (Opt-in
`ZEIT_MACOS_TRAY=1` bzw. `ZEIT_LINUX_TRAY=1`, s. is_supported).
`build_menu_model` (`tray/model.py`) ist die backend-agnostische, testbare Naht.

Der Import-Pfad bleibt `src.tray` — Aufrufer und Tests merken vom Paket-Schnitt
(R7, #51) nichts. **Die Backends dürfen hier nur LAZY landen** (mac/linux in
`_select_backend`): `src.ui → src.tray` muss auf jeder Plattform importierbar
sein, ohne PyObjC oder dbus_fast zu ziehen.
"""

import os
import platform

from src.tray.model import MenuEntry, build_menu_model  # noqa: F401  (Re-Export)
from src.tray.windows import _PystrayBackend  # noqa: F401  (Re-Export für Tests)

__all__ = [
    "MenuEntry", "TrayIcon", "build_menu_model", "is_supported",
]


def _macos_tray_opt_in():
    """macOS-Tray ist bis zum bestandenen Mac-Gate dormant: nur aktiv, wenn der
    Tester ZEIT_MACOS_TRAY=1 setzt. Default-an-Flip = separater PR (s. Spec)."""
    return os.environ.get("ZEIT_MACOS_TRAY") == "1"


def _linux_tray_opt_in():
    """Linux-Tray ist bis zum bestandenen Plasma-Gate dormant: nur aktiv, wenn
    der Tester ZEIT_LINUX_TRAY=1 setzt (#42, analog macOS). Der Default-an-Flip
    ersetzt diese Prüfung später durch „läuft ein StatusNotifierWatcher?"."""
    return os.environ.get("ZEIT_LINUX_TRAY") == "1"


def is_supported():
    """Kann auf diesem System ein Tray-Icon gezeigt werden?

    Windows → True. macOS und Linux → nur mit Opt-in (dormant-Default, s.
    _macos_tray_opt_in / _linux_tray_opt_in). Aufrufer kann unabhängig davon
    `try/except` machen, falls das Backend zur Laufzeit doch fehlschlägt.
    """
    system = platform.system()
    if system == "Windows":
        return True
    if system == "Darwin":
        return _macos_tray_opt_in()
    if system == "Linux":
        return _linux_tray_opt_in()
    return False


def _select_backend(system):
    """Backend-Klasse nach Plattform. macOS und Linux lazy, damit PyObjC bzw.
    dbus_fast nicht in den jeweils fremden Importpfad geraten."""
    if system == "Windows":
        return _PystrayBackend
    if system == "Darwin":
        from src.tray.mac import MacTrayBackend
        return MacTrayBackend
    if system == "Linux":
        from src.tray.linux import LinuxTrayBackend
        return LinuxTrayBackend
    return None


class TrayIcon:
    """Plattform-Fassade: wählt per platform.system() das Backend
    (_PystrayBackend auf Windows, MacTrayBackend auf macOS, LinuxTrayBackend
    auf Linux — s. _select_backend) und delegiert. Öffentliche API
    (start/stop/notify) unverändert."""

    def __init__(self, resource_path, on_show, on_quit, actions=None):
        self.resource_path = resource_path
        self._on_show = on_show
        self._on_quit = on_quit
        self._actions = actions or []
        self._backend = None

    def start(self):
        """Startet das plattformspezifische Backend. Wirft dessen Exception
        durch (synchron) — Aufrufer (_apply_tray_setting) fängt und fällt auf
        Tray-Verzicht zurück."""
        backend_cls = _select_backend(platform.system())
        if backend_cls is None:
            raise RuntimeError("Tray auf dieser Plattform nicht unterstützt")
        backend = backend_cls(
            self.resource_path, self._on_show, self._on_quit, self._actions)
        backend.start()
        self._backend = backend  # erst nach erfolgreichem start halten

    def notify(self, message, title="Zeiterfassung"):
        if self._backend is not None:
            self._backend.notify(message, title)

    def stop(self):
        if self._backend is not None:
            self._backend.stop()
            self._backend = None
