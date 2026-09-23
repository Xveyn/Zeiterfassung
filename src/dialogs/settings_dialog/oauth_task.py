"""Generischer (fn, on_done)-Builder für OAuth-Aktivieren-Toggles (Audit H5).

Eigenes Modul (statt tab_google), weil der Builder keinen Tab-Bezug hat und
tests/test_settings_dialog.py sein messagebox im Funktions-Modul monkeypatcht.
"""

import traceback
from tkinter import messagebox

from src.mail import is_offline_error
from src.oauth_utils import (
    KEYRING_UNAVAILABLE_HINT, KEYRING_UNAVAILABLE_TITLE, is_keyring_unavailable,
)
from src.theme import themed_showerror


def _show_missing_credentials(parent, base_path, action):
    # Lazy: send_dialog zieht Report/Period-Picker nach — für den Aufbau des
    # Einstellungs-Dialogs unnötig. Eigene Funktion, damit Tests sie ersetzen.
    from src.dialogs.send_dialog import show_missing_credentials_dialog
    show_missing_credentials_dialog(parent, base_path, google_action=action)


def show_known_google_failure(dialog, error, base_path, action):
    """Zeigt einen BEKANNTEN Fehler einer Google-Verbinden-Aktion themed und
    ohne Traceback und liefert True — oder False, wenn `error` unerwartet ist
    und in den nativen Catch-all-Dialog gehört (CLAUDE.md „Bekannt-themed /
    unerwartet-nativ").

    Bekannt sind: Schlüsselbund nicht erreichbar (#101), fehlende
    credentials.json (derselbe „Keine Zugangsdaten"-Dialog wie beim Senden,
    mit „Datenordner öffnen", aber mit `action` statt des Gmail-Textes — kein
    SMTP-Hinweis, Drive und Kalender gibt es nur mit Google) und keine
    Internetverbindung. `action` nennt,
    was gerade scheiterte („Google Kalender aktivieren")."""
    if is_keyring_unavailable(error):
        themed_showerror(dialog, KEYRING_UNAVAILABLE_TITLE, KEYRING_UNAVAILABLE_HINT)
        return True
    if isinstance(error, FileNotFoundError) and base_path is not None:
        _show_missing_credentials(dialog, base_path, action)
        return True
    if is_offline_error(error):
        themed_showerror(
            dialog, "Keine Internetverbindung",
            f"„{action}“ braucht eine Verbindung zu Google.\n\n"
            "Bitte prüfe deine Internetverbindung und versuche es dann erneut.",
        )
        return True
    return False


def build_oauth_enable_task(*, service_fn, settings, setting_key, checkbox,
                            toggle_var, on_change, dialog, error_title,
                            on_success_dialog_ui=None, base_path=None):
    """Baut (fn, on_done) für einen OAuth-Aktivieren-Toggle (Drive-Sync / Kalender).

    fn (Worker-Thread): ruft service_fn() und persistiert setting_key=True bei
    Erfolg — läuft im Thread und überlebt daher einen Dialog-Close. Fängt seine
    Exceptions selbst, wirft nie.

    on_done (UI-Thread via App._marshal_to_ui): ruft on_change() (App-/root-scoped)
    VOR dem winfo_exists-Guard, danach die Dialog-Kosmetik (checkbox, toggle_var,
    Messagebox, optional on_success_dialog_ui) — übersprungen, wenn der Dialog weg
    ist. on_success_dialog_ui ist Dialog-Kosmetik (z.B. Kalenderliste laden) und
    läuft daher NACH dem Guard.

    base_path: Datenordner — nur für den „Keine Zugangsdaten"-Dialog bei
    fehlender credentials.json (s. `show_known_google_failure`).
    """
    def fn():
        try:
            service_fn()
        except Exception as e:
            return {"ok": False, "error": e, "tb": traceback.format_exc()}
        settings.set(setting_key, True)
        return {"ok": True}

    def on_done(res):
        if res["ok"]:
            on_change()
        if not checkbox.winfo_exists():
            return
        checkbox.config(state="normal")
        if res["ok"]:
            if on_success_dialog_ui is not None:
                on_success_dialog_ui()
        else:
            toggle_var.set(False)
            if show_known_google_failure(dialog, res["error"], base_path,
                                         error_title):
                return
            messagebox.showerror(
                error_title,
                f"OAuth-Flow fehlgeschlagen:\n\n{res['error']}\n\n{res['tb']}",
                parent=dialog,
            )

    return fn, on_done
