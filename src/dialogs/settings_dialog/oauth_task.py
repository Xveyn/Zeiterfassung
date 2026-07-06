"""Generischer (fn, on_done)-Builder für OAuth-Aktivieren-Toggles (Audit H5).

Eigenes Modul (statt tab_google), weil der Builder keinen Tab-Bezug hat und
tests/test_settings_dialog.py sein messagebox im Funktions-Modul monkeypatcht.
"""

import traceback
from tkinter import messagebox


def build_oauth_enable_task(*, service_fn, settings, setting_key, checkbox,
                            toggle_var, on_change, dialog, error_title,
                            on_success_dialog_ui=None):
    """Baut (fn, on_done) für einen OAuth-Aktivieren-Toggle (Drive-Sync / Kalender).

    fn (Worker-Thread): ruft service_fn() und persistiert setting_key=True bei
    Erfolg — läuft im Thread und überlebt daher einen Dialog-Close. Fängt seine
    Exceptions selbst, wirft nie.

    on_done (UI-Thread via App._marshal_to_ui): ruft on_change() (App-/root-scoped)
    VOR dem winfo_exists-Guard, danach die Dialog-Kosmetik (checkbox, toggle_var,
    Messagebox, optional on_success_dialog_ui) — übersprungen, wenn der Dialog weg
    ist. on_success_dialog_ui ist Dialog-Kosmetik (z.B. Kalenderliste laden) und
    läuft daher NACH dem Guard.
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
            messagebox.showerror(
                error_title,
                f"OAuth-Flow fehlgeschlagen:\n\n{res['error']}\n\n{res['tb']}",
                parent=dialog,
            )

    return fn, on_done
