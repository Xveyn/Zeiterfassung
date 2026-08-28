# src/tray/mac.py
"""Natives macOS-Tray (NSStatusItem) — Backend für TrayIcon (#88).

Der frühere pystray-Daemon-Thread treibt auf macOS eine zweite NSApplication an
und kollidiert mit der von Tk getriebenen → Crash beim Fenster-Mappen. Dieses
Backend hängt stattdessen ein NSStatusItem SYNCHRON auf dem Main-Thread an die
geteilte NSApplication, die Tk ohnehin treibt — kein Thread, keine zweite NSApp.

PyObjC wird LAZY in den Methoden importiert: Modulebene bleibt stdlib-only, damit
src.ui → src.tray → (dispatch) src.tray.mac auf Linux/Windows importierbar bleibt
(die CI importiert src.ui). Siehe Spec 2026-06-30-macos-native-tray-design.md.
"""

import logging
import os

from src.tray.model import build_menu_model

logger = logging.getLogger(__name__)


def _safe(fn):
    """0-arg-Callback aufrufen, ohne dass eine Python-Exception in einen
    ObjC-Frame zurückläuft (Klasse-(i)-Schutz, s. Spec). JEDER von AppKit
    aufgerufene Callback läuft hierdurch."""
    try:
        fn()
    except Exception:
        logger.exception("macOS-Tray-Callback-Fehler (geschluckt)")


class MacTrayBackend:
    """NSStatusItem-Backend mit derselben Lifecycle-API wie _PystrayBackend."""

    def __init__(self, resource_path, on_show, on_quit, actions=None):
        self.resource_path = resource_path
        self._on_show = on_show
        self._on_quit = on_quit
        self._actions = actions or []
        # STARKE Referenzen halten — sonst GC → Icon verschwindet/Crash.
        self._status_item = None
        self._menu = None
        self._delegate = None
        self._dynamic_items = []  # [(NSMenuItem, visible_callable)]

    def _load_image(self):
        from AppKit import NSImage  # pyright: ignore[reportMissingImports]  # pyobjc, nur macOS
        png = os.path.join(self.resource_path, "assets", "margenheld-icon.png")
        if not os.path.exists(png):
            return None
        image = NSImage.alloc().initByReferencingFile_(png)
        if image is not None:
            image.setSize_((18, 18))  # Menübar-Höhe
        return image

    def start(self):
        from AppKit import (  # pyright: ignore[reportMissingImports]  # pyobjc, nur macOS
            NSStatusBar, NSMenu, NSMenuItem, NSVariableStatusItemLength,
        )
        from Foundation import NSObject  # pyright: ignore[reportMissingImports]  # pyobjc, nur macOS

        model = build_menu_model(self._on_show, self._on_quit, self._actions)

        callbacks = {}            # representedObject-Key -> 0-arg-Callback
        dynamic_items = []        # [(NSMenuItem, visible_callable)]

        # Delegate LAZY definieren: NSObject-Subklasse braucht Foundation, und
        # die Methoden schließen über callbacks/dynamic_items (free vars).
        class _TrayDelegate(NSObject):
            def invoke_(self, sender):
                cb = callbacks.get(str(sender.representedObject()))
                if cb is not None:
                    _safe(cb)

            def menuNeedsUpdate_(self, menu):
                # live-Sichtbarkeit: visible-Callables vor jedem Öffnen auswerten
                for item, vis in dynamic_items:
                    try:
                        item.setHidden_(not bool(vis()))
                    except Exception:
                        logger.exception(
                            "macOS-Tray-Sichtbarkeit-Fehler (geschluckt)")

        delegate = _TrayDelegate.alloc().init()

        menu = NSMenu.alloc().init()
        menu.setAutoenablesItems_(False)
        menu.setDelegate_(delegate)

        for idx, entry in enumerate(model):
            if entry.kind == "separator":
                menu.addItem_(NSMenuItem.separatorItem())
                continue
            item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
                entry.label, "invoke:", "",
            )
            item.setTarget_(delegate)
            item.setRepresentedObject_(str(idx))
            callbacks[str(idx)] = entry.callback
            if entry.visible is not None:
                dynamic_items.append((item, entry.visible))
            menu.addItem_(item)

        status_item = NSStatusBar.systemStatusBar().statusItemWithLength_(
            NSVariableStatusItemLength)
        image = self._load_image()
        button = status_item.button()
        if image is not None and button is not None:
            button.setImage_(image)
        elif button is not None:
            button.setTitle_("Z")  # Last-Resort, falls PNG fehlt
        status_item.setMenu_(menu)

        # Refs festhalten (Reihenfolge egal; alle bis stop() leben lassen).
        self._delegate = delegate
        self._menu = menu
        self._dynamic_items = dynamic_items
        self._status_item = status_item

    def notify(self, message, title="Zeiterfassung"):
        """best-effort: NSUserNotification (deprecated, aber leichtgewichtig).
        ALLE Fehler geschluckt — Toast ist kosmetisch, Sync bleibt unberührt.

        Kein expliziter Main-Thread-Dispatch: der einzige Aufrufer
        (sync_orchestrator._on_tray_done) ist ein on_done-Callback und läuft
        bereits über _marshal_to_ui auf dem Tk-/Main-Thread (verifiziert)."""
        try:
            from Foundation import (  # pyright: ignore[reportMissingImports]  # pyobjc, nur macOS
                NSUserNotification, NSUserNotificationCenter,
            )
            note = NSUserNotification.alloc().init()
            note.setTitle_(title or "Zeiterfassung")
            note.setInformativeText_(message)
            NSUserNotificationCenter.defaultUserNotificationCenter() \
                .deliverNotification_(note)
        except Exception:
            logger.exception("macOS-Tray-Notify fehlgeschlagen (geschluckt)")

    def stop(self):
        """Entfernt das Status-Item und löst die Referenzen. Idempotent."""
        if self._status_item is not None:
            try:
                from AppKit import NSStatusBar  # pyright: ignore[reportMissingImports]  # pyobjc, nur macOS
                NSStatusBar.systemStatusBar().removeStatusItem_(
                    self._status_item)
            except Exception:
                logger.exception("macOS-Tray stop fehlgeschlagen")
        self._status_item = None
        self._menu = None
        self._delegate = None
        self._dynamic_items = []
