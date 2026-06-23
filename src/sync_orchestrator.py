"""Drive-Sync-Orchestrierung für die UI: manueller Sync, Tray-Sync,
Pull-Callbacks, Status-Label, Quit-Push und die Fehler-Aufbereitung.

`import tkinter`/`messagebox` auf Modulebene ist unkritisch (stdlib, kein
Display zum Import nötig). `_run_push_blocking` wird LAZY in den Methoden aus
`src.main` importiert — sonst Circular-Import (src.main → src.ui →
src.sync_orchestrator).
"""

from tkinter import messagebox

from src.drive import DriveAuthError, DriveNetworkError
from src.theme import themed_showinfo
from src.time_utils import format_iso_date


def _classify_sync_error(error):
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

    kind = _classify_sync_error(error)

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
