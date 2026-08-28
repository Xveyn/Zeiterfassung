"""Drive-Sync-Orchestrierung für die UI: manueller Sync, Tray-Sync,
Pull-Callbacks, Status-Label, Quit-Push und die Fehler-Aufbereitung.

`import tkinter`/`messagebox` auf Modulebene ist unkritisch (stdlib, kein
Display zum Import nötig). `run_push_blocking` kommt aus `src.sync_runtime`
— früher aus `src.main`, was nur lazy ging (Circular-Import: src.main →
src.ui → src.sync_orchestrator).
"""

import logging
import tkinter as tk
import traceback
from tkinter import messagebox

from src.drive import DriveAuthError, DriveNetworkError
from src.sync_runtime import run_push_blocking
from src.theme import set_icon_button_enabled, themed_showinfo
from src.time_utils import format_iso_date


def classify_sync_error(error):
    """Kategorisiert einen Google-Sync/Reconcile-Fehler als 'auth', 'network'
    oder 'unknown'. `error` kann eine Exception oder ein String sein (der
    Push-/Reconcile-Pfad liefert str(e), der Pull-Pfad das Exception-Objekt).
    Der abgelaufene/widerrufene Token kommt als invalid_grant durch — sowohl
    bei Drive als auch beim Kalender, da beide denselben OAuth-Token nutzen.
    Ein 403 'insufficient authentication scopes' / 'insufficientPermissions'
    ist ebenfalls ein Auth-Fall (Token deckt einen Scope nicht ab → Re-Consent):
    im String-Pfad fehlt die Typinfo, daher zusätzlich per Textmuster erkannt."""
    text = str(error)
    if (isinstance(error, DriveAuthError)
            or "invalid_grant" in text
            or "expired or revoked" in text
            or "insufficientPermissions" in text
            or "insufficient authentication scopes" in text):
        return "auth"
    if isinstance(error, DriveNetworkError):
        return "network"
    return "unknown"


def _friendly_sync_message(error, tb=""):
    """Mappt einen Drive-Sync-Fehler auf (Titel, Meldung, known) für die Messagebox."""
    from src.sync import NEWER_REMOTE_VERSION_MSG
    if str(error) == NEWER_REMOTE_VERSION_MSG:
        return ("Update erforderlich", NEWER_REMOTE_VERSION_MSG, True)

    kind = classify_sync_error(error)

    if kind == "auth":
        return (
            "Google-Verbindung erneuern",
            "Die App braucht erneut deine Erlaubnis für Google Drive. Das "
            "passiert, wenn die Verbindung abgelaufen oder widerrufen wurde "
            "oder eine neue Freigabe nötig ist.\n\nBitte öffne die "
            "Einstellungen und klicke auf „Google neu verbinden\" — danach "
            "im Browser die Freigabe bestätigen.",
            True,
        )
    if kind == "network":
        return (
            "Keine Internetverbindung",
            "Die Synchronisation mit Google Drive ist fehlgeschlagen, weil "
            "keine Verbindung zum Internet besteht.\n\nBitte prüfe deine "
            "Verbindung und versuche es erneut.",
            True,
        )
    detail = f"{error}\n\n{tb}" if tb else str(error)
    return (
        "Synchronisation fehlgeschlagen",
        "Bei der Synchronisation mit Google Drive ist ein unerwarteter "
        f"Fehler aufgetreten:\n\n{detail}",
        False,
    )


def _show_sync_error(parent, error, tb="", suffix=""):
    """Zeigt einen Sync-Fehler im passenden Stil: bekannte Fälle (Token/Netz)
    als themed Info-Dialog, unerwartete Fehler als showerror mit Traceback.
    `suffix` wird optional angehängt."""
    title, message, known = _friendly_sync_message(error, tb)
    if suffix:
        message = f"{message}\n\n{suffix}"
    if known:
        themed_showinfo(parent, title, message)
    else:
        messagebox.showerror(title, message)


def _status_text(n_conflicts, last_pull_at):
    """Text fürs Status-Label: offener Konflikt hat Vorrang, sonst letzter Pull."""
    if n_conflicts > 0:
        return f"⚠ {n_conflicts} Konflikt{'e' if n_conflicts != 1 else ''}"
    return f"✓ {format_iso_date(last_pull_at, fallback='noch nie')}"


def _tray_toast(ok, n_conflicts, error):
    """Toast-Meldung nach Tray-Sync."""
    if not ok:
        return f"Sync fehlgeschlagen:\n{error}"
    if n_conflicts == 0:
        return "Synchronisiert."
    return f"Synchronisiert — {n_conflicts} Konflikt{'e' if n_conflicts != 1 else ''} offen."


class SyncOrchestrator:
    """Kapselt den Drive-Sync der UI. Hält stabile Deps; die Header-Widgets
    werden nach dem Build über attach_widgets nachgereicht, das Tray-Objekt
    lazy über get_tray gelesen (einzige Quelle bleibt App._tray)."""

    def __init__(self, root, storage, settings, conflicts_store, base_path,
                 runner, on_refresh, get_tray, data_lock=None, sync_guard=None):
        self._root = root
        self._storage = storage
        self._settings = settings
        self._conflicts_store = conflicts_store
        self._base_path = base_path
        self._runner = runner          # App._bg, hat .run(fn, on_done)
        self._on_refresh = on_refresh    # App._refresh
        self._get_tray = get_tray        # lambda: App._tray
        self._data_lock = data_lock      # geteilter Store-RLock (Audit H1)
        self._sync_guard = sync_guard    # Sync-Re-Entrancy-Guard (Audit H2)
        self._sync_button = None
        self._status_label = None
        self._next_button = None
        # Re-Entrancy-Flag für den manuellen Sync-Button: der icon_button ist
        # nur OPTISCH deaktivierbar (set_icon_button_enabled, kein echtes
        # -state), die Klick-Bindung bleibt aktiv. Dieses Flag trägt daher den
        # No-op bei bereits laufendem Manual-Sync (der sync_guard schützt die
        # Daten zusätzlich engineseitig; hier geht es um Doppelklick-UX).
        self._sync_in_progress = False

    def attach_widgets(self, sync_button, status_label, next_button):
        self._sync_button = sync_button
        self._status_label = status_label
        self._next_button = next_button

    def _conflict_count(self):
        if self._conflicts_store is not None:
            return self._conflicts_store.count_unresolved()
        return 0

    def _push(self, guard_timeout=0, timeout_seconds=15):
        return run_push_blocking(
            self._storage, self._settings, self._conflicts_store,
            self._base_path, timeout_seconds=timeout_seconds,
            data_lock=self._data_lock, sync_guard=self._sync_guard,
            guard_timeout=guard_timeout,
        )

    def on_pull_success(self):
        """Aus dem UI-Thread nach erfolgreichem Pull."""
        self._on_refresh()
        self.update_status_label()

    def on_pull_error(self, error, tb=""):
        _show_sync_error(self._root, error, tb)
        self.update_status_label()

    def update_status_label(self):
        if self._status_label is None:
            return
        if not self._settings.get("sync_enabled"):
            self._sync_button.pack_forget()
            self._status_label.pack_forget()
            self._status_label.config(text="")
            return
        # Sichtbar machen, falls vorher versteckt. Reihenfolge wie Build-Time.
        if not self._sync_button.winfo_ismapped():
            self._sync_button.pack(side=tk.RIGHT, padx=(4, 0),
                                   before=self._next_button)
            self._status_label.pack(side=tk.RIGHT, padx=(8, 4),
                                    before=self._sync_button)
        self._status_label.config(
            text=_status_text(self._conflict_count(),
                              self._settings.get("last_pull_at")))

    def on_sync_clicked(self):
        if not self._settings.get("sync_enabled"):
            themed_showinfo(
                self._root,
                "Synchronisation",
                "Synchronisation ist deaktiviert. In den Einstellungen aktivierbar.")
            return
        if self._sync_in_progress:
            return  # läuft bereits — Button ist nur optisch gedimmt
        self._sync_in_progress = True
        self._status_label.config(text="Synchronisiere…")
        if self._sync_button is not None:
            set_icon_button_enabled(self._sync_button, False)
        self._runner.run(self._push, self._on_manual_done)

    def _on_manual_done(self, result):
        self._sync_in_progress = False
        if self._sync_button is not None:
            set_icon_button_enabled(self._sync_button, True)
        if result.get("skipped"):
            # Anderer Sync läuft bereits — dessen Callback aktualisiert die UI.
            self.update_status_label()
            return
        if not result.get("ok"):
            _show_sync_error(self._root, result.get("error", "?"),
                             result.get("tb", ""))
        self._on_refresh()
        self.update_status_label()

    def tray_sync(self):
        if not self._settings.get("sync_enabled"):
            return
        self._runner.run(self._push, self._on_tray_done)

    def _on_tray_done(self, result):
        if result.get("skipped"):
            return  # anderer Sync läuft — kein Toast, nichts hat sich geändert
        self._on_refresh()
        self.update_status_label()
        tray = self._get_tray()
        if tray is None:
            return
        tray.notify(
            _tray_toast(result.get("ok"), self._conflict_count(),
                       result.get("error", "?")),
            title="",
        )

    def push_on_quit(self):
        """Blockierender Push beim Beenden. Wartet per guard_timeout bis 5 s
        auf einen laufenden Sync (Worst Case gesamt ~10 s mit Push-Timeout).
        Kein tray.stop() (bleibt App-Lifecycle)."""
        if not self._settings.get("sync_enabled"):
            return
        try:
            result = self._push(guard_timeout=5, timeout_seconds=10)
        except Exception as e:
            result = {"ok": False, "error": e, "tb": traceback.format_exc()}
        if result.get("skipped"):
            logging.getLogger(__name__).warning(
                "Quit-Push übersprungen — ein anderer Sync läuft noch; "
                "lokale Daten syncen beim nächsten Start.")
            return
        if not result.get("ok"):
            _show_sync_error(
                self._root, result.get("error", "?"), result.get("tb", ""),
                suffix="Lokale Daten bleiben erhalten und werden beim "
                       "nächsten Start synchronisiert.",
            )
