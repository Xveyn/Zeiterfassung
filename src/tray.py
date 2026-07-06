# src/tray.py
"""System-Tray-Icon — Plattform-Fassade über zwei Backends.

`TrayIcon` wählt per platform.system(): Windows → `_PystrayBackend` (pystray im
Daemon-Thread, UI-Aktionen via `root.after(0, …)` auf den Tk-Thread). macOS →
`MacTrayBackend` (src/tray_mac.py): natives NSStatusItem SYNCHRON auf dem
Main-Thread, KEIN Thread, keine zweite NSApplication (Fix #88). macOS ist bis zum
manuellen Mac-Gate dormant (Opt-in `ZEIT_MACOS_TRAY=1`, s. is_supported). Linux
hat kein Tray. `build_menu_model` ist die backend-agnostische, testbare Naht.
"""

import logging
import os
import platform
import threading
from collections import namedtuple


def _macos_tray_opt_in():
    """macOS-Tray ist bis zum bestandenen Mac-Gate dormant: nur aktiv, wenn der
    Tester ZEIT_MACOS_TRAY=1 setzt. Default-an-Flip = separater PR (s. Spec)."""
    return os.environ.get("ZEIT_MACOS_TRAY") == "1"


def is_supported():
    """Kann auf diesem System ein Tray-Icon gezeigt werden?

    Windows → True. Linux → False (uneinheitlich). macOS → nur mit Opt-in
    (dormant-Default, s. _macos_tray_opt_in). Aufrufer kann unabhängig davon
    `try/except` machen, falls das Backend zur Laufzeit doch fehlschlägt.
    """
    system = platform.system()
    if system == "Windows":
        return True
    if system == "Darwin":
        return _macos_tray_opt_in()
    return False


MenuEntry = namedtuple("MenuEntry", ["kind", "label", "callback", "visible"])


def build_menu_model(on_show, on_quit, actions):
    """Backend-agnostisches Menü-Modell (pure, ohne AppKit/pystray) aus den
    Tray-Aktionen. Speist den macOS-Renderer (src/tray_mac.py) und die Tests;
    der Windows-Pfad baut sein pystray-Menü weiter inline.

    `actions`: Liste (label, callback, visible). `callback` ist 0-arg und
    marshallt selbst auf den Tk-Thread. `visible` ist None (immer sichtbar) oder
    eine 0-arg-Callable → Bool (dynamische Sichtbarkeit).
    """
    entries = [
        MenuEntry("item", "Anzeigen", on_show, None),
        MenuEntry("separator", None, None, None),
    ]
    for label, callback, visible in actions:
        entries.append(MenuEntry("item", label, callback, visible))
    if actions:
        entries.append(MenuEntry("separator", None, None, None))
    entries.append(MenuEntry("item", "Beenden", on_quit, None))
    return entries


def _select_backend(system):
    """Backend-Klasse nach Plattform. macOS lazy, damit PyObjC nicht in den
    Linux/Windows-Importpfad gerät."""
    if system == "Windows":
        return _PystrayBackend
    if system == "Darwin":
        from src.tray_mac import MacTrayBackend
        return MacTrayBackend
    return None


class _PystrayBackend:
    """pystray-Backend (Windows). Tk-freundliche Lifecycle-API.

    Wird von der TrayIcon-Fassade auf Windows gewählt (auf macOS läuft das
    native MacTrayBackend, s. tray_mac.py). Body unverändert ggü. dem früheren
    monolithischen TrayIcon.

    Nutzung (intern, über die Fassade):
        backend = _PystrayBackend(base_path, on_show=show_fn, on_quit=quit_fn)
        tray.start()
        ...
        tray.stop()

    actions: optionale Liste von (label, callback, visible)-Tupeln, die als
    Quick-Actions zwischen „Anzeigen" und „Beenden" ins Menü kommen. `callback`
    ist eine 0-arg-Funktion (sollte selbst auf den Tk-Thread marshallen, wie
    on_show/on_quit). `visible` ist None (immer sichtbar) oder eine 0-arg-
    Funktion → Bool.

    Plattform-Unterschied bei `visible`: Das win32-Backend baut das Popup-Menü
    bei jedem Rechtsklick neu, wertet die Callable also LIVE aus (ein Sync-
    Eintrag erscheint/verschwindet sofort, wenn sich die Settings ändern). Das
    macOS-Backend (NSStatusItem, kein `menuNeedsUpdate:`-Delegate) baut das Menü
    dagegen nur EINMAL beim Tray-Start — dort ist `visible` ein Snapshot vom
    Start-Zeitpunkt. Für uns unkritisch: Bei verstecktem Fenster sind die
    Einstellungen nicht erreichbar, und das Icon wird ohnehin neu gebaut, wenn
    der Minimieren-Schalter umgelegt wird. Linux hat kein Tray (is_supported()).
    """

    def __init__(self, base_path, on_show, on_quit, actions=None):
        self.base_path = base_path
        self._on_show = on_show
        self._on_quit = on_quit
        self._actions = actions or []
        self._icon = None
        self._thread = None

    def _load_image(self):
        """Lädt das App-Icon als PIL-Bild. Fallback auf weiße Rechteck-Grafik,
        falls die PNG-Datei nicht da ist (sollte nicht passieren — assets sind
        in PyInstaller-Bundle mit drin)."""
        from PIL import Image  # pyright: ignore[reportMissingImports]  # Pillow: nicht in CI-Test-Deps
        png = os.path.join(self.base_path, "assets", "margenheld-icon.png")
        if os.path.exists(png):
            return Image.open(png)
        # Last-resort 16x16 weißes Bild — Icon ist sichtbar aber unbranded.
        return Image.new("RGB", (16, 16), color=(255, 255, 255))

    def start(self):
        """Startet das Tray-Icon im Hintergrundthread. Wirft die zugrunde
        liegende Exception, wenn pystray das Backend nicht laden kann —
        Aufrufer muss das fangen und auf Tray-Verzicht zurückfallen."""
        import pystray  # pyright: ignore[reportMissingImports]  # nicht in CI-Test-Deps

        def _on_show_click(icon, item):
            self._on_show()

        def _on_quit_click(icon, item):
            # pystray-Stop muss zuerst, sonst hängt der Thread nach root.destroy()
            icon.stop()
            self._on_quit()

        image = self._load_image()
        items = [
            pystray.MenuItem("Anzeigen", _on_show_click, default=True),
            pystray.Menu.SEPARATOR,
        ]
        for label, callback, visible in self._actions:
            items.append(pystray.MenuItem(
                label, self._wrap_action(callback),
                # pystray akzeptiert für `visible` auch ein Callable (dynamische
                # Sichtbarkeit), sein Typ-Stub deklariert aber nur bool.
                visible=self._wrap_visible(visible),  # pyright: ignore[reportArgumentType]
            ))
        if self._actions:
            items.append(pystray.Menu.SEPARATOR)
        items.append(pystray.MenuItem("Beenden", _on_quit_click))
        menu = pystray.Menu(*items)
        icon = pystray.Icon(
            "zeiterfassung",
            image,
            "Zeiterfassung",
            menu,
        )
        self._icon = icon

        def _run():
            try:
                icon.run()
            except Exception:
                logging.getLogger(__name__).exception("Tray-Icon-Thread crashed")

        self._thread = threading.Thread(target=_run, daemon=True)
        self._thread.start()

    @staticmethod
    def _wrap_action(callback):
        """pystray-Handler-Signatur ist (icon, item); der Caller-Callback ist
        0-arg. Der läuft im pystray-Thread und marshallt selbst auf den Tk-
        Thread (siehe Klassen-Docstring)."""
        def handler(icon, item):
            callback()
        return handler

    @staticmethod
    def _wrap_visible(visible):
        """`visible` ist None (immer sichtbar) oder eine 0-arg-Funktion → Bool.
        pystray erwartet entweder einen Bool oder ein Callable mit (item)-
        Signatur und wertet Callables bei jedem Menü-Öffnen neu aus."""
        if visible is None:
            return True
        return lambda item: bool(visible())

    def notify(self, message, title="Zeiterfassung"):
        """Zeigt eine System-Benachrichtigung (Toast) über das Tray-Icon.
        Fehlertolerant — nicht jedes Backend unterstützt notify()."""
        if self._icon is None:
            return
        # Bevorzugt der Toast MIT App-Icon (Windows); bei anderem Backend oder
        # Fehler Fallback auf pystrays Standard-notify().
        if self._notify_with_icon(message, title):
            return
        try:
            self._icon.notify(message, title)
        except Exception:
            logging.getLogger(__name__).exception("Tray-Notify fehlgeschlagen")

    def _notify_with_icon(self, message, title):
        """Windows-only: Toast mit dem App-Icon als großem Balloon-Icon.

        pystrays eigenes notify() setzt KEIN Balloon-Icon (dwInfoFlags bleibt 0
        = NIIF_NONE) — dann zeigt Windows je nach Version ein generisches oder
        gar kein Logo. Wir setzen NIIF_USER|NIIF_LARGE_ICON plus das HICON des
        bereits gesetzten Tray-Icons, damit das Logo im Toast erscheint.

        Greift bewusst in pystray-Interna (`_icon._message`, `_icon_handle`,
        `_util.win32`). Jeder Fehler oder ein Nicht-win32-Backend → False, der
        Aufrufer fällt dann auf das Standard-notify() zurück."""
        import platform
        if platform.system() != "Windows":
            return False
        try:
            from pystray._util import win32  # pyright: ignore[reportMissingImports]  # nicht in CI-Test-Deps
            handle = getattr(self._icon, "_icon_handle", None)
            # _message ist eine pystray-Interne (nicht im Type-Stub) — wie
            # _icon_handle per getattr holen: entfernt die Pylance-Warnung und
            # faellt sauber auf Standard-notify() zurueck, falls sie fehlt.
            send_message = getattr(self._icon, "_message", None)
            if not handle or send_message is None:
                return False
            # Konstanten sind in pystrays win32-Util nicht definiert.
            NIIF_USER = 0x00000004
            NIIF_LARGE_ICON = 0x00000020
            send_message(
                win32.NIM_MODIFY,
                win32.NIF_INFO,
                szInfo=message,
                szInfoTitle=title or "",
                dwInfoFlags=NIIF_USER | NIIF_LARGE_ICON,
                hBalloonIcon=handle,
            )
            return True
        except Exception:
            logging.getLogger(__name__).exception(
                "Tray-Notify mit Icon fehlgeschlagen — Fallback auf Standard")
            return False

    def stop(self):
        """Beendet das Tray-Icon. Idempotent."""
        if self._icon is not None:
            try:
                self._icon.stop()
            except Exception:
                # N13: Stop ist best-effort (Icon evtl. schon weg), aber nicht spurlos.
                logging.getLogger(__name__).debug(
                    "Tray-Icon stop() fehlgeschlagen", exc_info=True)
            self._icon = None


class TrayIcon:
    """Plattform-Fassade: wählt per platform.system() das Backend
    (_PystrayBackend auf Windows, MacTrayBackend auf macOS) und delegiert.
    Öffentliche API (start/stop/notify) unverändert."""

    def __init__(self, base_path, on_show, on_quit, actions=None):
        self.base_path = base_path
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
            self.base_path, self._on_show, self._on_quit, self._actions)
        backend.start()
        self._backend = backend  # erst nach erfolgreichem start halten

    def notify(self, message, title="Zeiterfassung"):
        if self._backend is not None:
            self._backend.notify(message, title)

    def stop(self):
        if self._backend is not None:
            self._backend.stop()
            self._backend = None
