# src/tray.py
"""System-Tray-Icon (Windows Notification Area / macOS Menu Bar).

Bewusst minimal: pystray läuft in eigenem Daemon-Thread, UI-Aktionen werden
via `root.after(0, ...)` auf den Tk-Thread marshallt. Auf Linux ist die
Verfügbarkeit WM-abhängig — wenn pystray-Backend fehlschlägt, gilt das
Feature als nicht verfügbar und der Caller fällt auf normales Schließverhalten
zurück.
"""

import logging
import os
import threading


def is_supported():
    """Kann auf diesem System ein Tray-Icon gezeigt werden?

    Conservative: True für Windows und macOS, False für Linux (uneinheitlich).
    Aufrufer kann unabhängig davon `try/except` machen, falls pystray zur
    Laufzeit doch fehlschlägt.
    """
    import platform
    return platform.system() in ("Windows", "Darwin")


class TrayIcon:
    """Wrapper um pystray.Icon mit Tk-freundlicher Lifecycle-API.

    Nutzung:
        tray = TrayIcon(base_path, on_show=show_fn, on_quit=quit_fn)
        tray.start()
        ...
        tray.stop()
    """

    def __init__(self, base_path, on_show, on_quit):
        self.base_path = base_path
        self._on_show = on_show
        self._on_quit = on_quit
        self._icon = None
        self._thread = None

    def _load_image(self):
        """Lädt das App-Icon als PIL-Bild. Fallback auf weiße Rechteck-Grafik,
        falls die PNG-Datei nicht da ist (sollte nicht passieren — assets sind
        in PyInstaller-Bundle mit drin)."""
        from PIL import Image
        png = os.path.join(self.base_path, "assets", "margenheld-icon.png")
        if os.path.exists(png):
            return Image.open(png)
        # Last-resort 16x16 weißes Bild — Icon ist sichtbar aber unbranded.
        return Image.new("RGB", (16, 16), color=(255, 255, 255))

    def start(self):
        """Startet das Tray-Icon im Hintergrundthread. Wirft die zugrunde
        liegende Exception, wenn pystray das Backend nicht laden kann —
        Aufrufer muss das fangen und auf Tray-Verzicht zurückfallen."""
        import pystray

        def _on_show_click(icon, item):
            self._on_show()

        def _on_quit_click(icon, item):
            # pystray-Stop muss zuerst, sonst hängt der Thread nach root.destroy()
            icon.stop()
            self._on_quit()

        image = self._load_image()
        menu = pystray.Menu(
            pystray.MenuItem("Anzeigen", _on_show_click, default=True),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Beenden", _on_quit_click),
        )
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

    def stop(self):
        """Beendet das Tray-Icon. Idempotent."""
        if self._icon is not None:
            try:
                self._icon.stop()
            except Exception:
                pass
            self._icon = None
