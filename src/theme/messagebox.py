# src/theme/messagebox.py
"""Themed Drop-ins für die `tkinter.messagebox`-Familie.

ACHTUNG, bewusste Zweiteilung (Audit N14): diese Dialoge sind fuer
BEKANNTE, erwartete Fehler. Unerwartete Fehler (die generischen
`except`-Zweige mit Traceback) nutzen weiterhin das ROHE
`tkinter.messagebox.showerror` — ein themed Dialog baut selbst Tk-Widgets
auf und könnte im bereits gestoerten Zustand genau die Meldung
verschlucken, die er zeigen soll.
"""

import tkinter as tk


from src.theme.palette import BG, CELL_BG, TEXT
from src.theme.fonts import FONT
from src.theme.widgets import primary_button, secondary_button, set_primary_button_enabled
from src.theme.geometry import center_dialog_on_parent
from src.theme.chrome import create_dialog


def themed_askyesno(parent, title: str, message: str, lock_ms: int = 0) -> bool:
    """Modaler Ja/Nein-Dialog im App-Theme. Drop-in für `messagebox.askyesno`.

    Eigener Toplevel statt der Tk-Messagebox, damit die DWM-Titelleiste
    (apply_dark_titlebar) und die Theme-Farben angewendet werden können —
    `tkinter.messagebox.*` ist eine Black-Box ohne Customization-Hooks.

    lock_ms: optionaler kurzer Lock nach dem Öffnen, analog zu
    `themed_ask_delete_choice` — verhindert versehentliches Sofort-Bestätigen
    bei Lösch-Rückfragen (z.B. genau eine löschbare Einheit am Tag).
    """
    dialog = create_dialog(parent, title, modal=False, escape_closes=False)

    result = {"value": False}
    unlock = {"ready": lock_ms <= 0}

    tk.Label(
        dialog, text=message, font=FONT, bg=BG, fg=TEXT,
        wraplength=380, justify="left",
    ).pack(padx=24, pady=(20, 14))

    def click_yes():
        if not unlock["ready"]:
            return
        result["value"] = True
        dialog.destroy()

    def click_no():
        dialog.destroy()

    btn_frame = tk.Frame(dialog, bg=BG)
    btn_frame.pack(pady=(0, 18))
    yes_btn = primary_button(btn_frame, "Ja", click_yes)
    yes_btn.pack(side=tk.LEFT, padx=6)
    secondary_button(btn_frame, "Nein", click_no).pack(side=tk.LEFT, padx=6)

    if lock_ms > 0:
        set_primary_button_enabled(yes_btn, False)

        def _unlock():
            unlock["ready"] = True
            set_primary_button_enabled(yes_btn, True)
        dialog.after(lock_ms, _unlock)

    dialog.bind("<Return>", lambda e: click_yes())
    dialog.bind("<Escape>", lambda e: click_no())
    dialog.protocol("WM_DELETE_WINDOW", click_no)

    center_dialog_on_parent(dialog, parent)
    dialog.grab_set()
    dialog.wait_window()
    return result["value"]


def themed_ask_delete_choice(parent, title: str, message: str, options, lock_ms: int = 0):
    """Modaler Lösch-Dialog mit Checkboxen — das Gegenstück zu `themed_askyesno`
    für Tage, an denen mehrere löschbare Objekte liegen (Ist-Zeit UND
    Reservierung).

    `options` ist eine Liste von (key, label)-Tupeln; alle Checkboxen sind
    vorausgewählt. Rückgabe: die Menge der angehakten keys, die der User mit
    „Löschen" bestätigt — oder None bei Abbruch (Escape / Schließen /
    „Abbrechen"). Sind alle Checkboxen abgewählt, ist „Löschen" deaktiviert
    (gedämpfter Rotton, nicht klickbar) — so kann der Klick nicht versehentlich
    den Dialog schließen und auf einem Kalendertag dahinter landen.
    """
    dialog = create_dialog(parent, title, modal=False, escape_closes=False)

    result: dict[str, set[str] | None] = {"value": None}
    # Optionaler kurzer Lock nach dem Öffnen: verhindert versehentliches
    # Sofort-Löschen, wenn (wie üblich) alle Optionen vorausgewählt sind.
    unlock = {"ready": lock_ms <= 0}

    tk.Label(
        dialog, text=message, font=FONT, bg=BG, fg=TEXT,
        wraplength=380, justify="left",
    ).pack(padx=24, pady=(20, 10))

    checkbuttons = []
    vars_by_key = {}
    for key, label in options:
        var = tk.BooleanVar(value=True)
        vars_by_key[key] = var
        cb = tk.Checkbutton(
            dialog, text=label, variable=var, font=FONT,
            bg=BG, fg=TEXT, selectcolor=CELL_BG,
            activebackground=BG, activeforeground=TEXT, cursor="hand2",
        )
        cb.pack(padx=28, anchor="w")
        checkbuttons.append(cb)

    def click_delete():
        if not unlock["ready"]:
            return
        selected = {key for key, var in vars_by_key.items() if var.get()}
        # Leere Auswahl ist ein No-Op: Dialog NICHT schließen, sonst landet der
        # Klick auf einem Kalendertag dahinter und öffnet den Speichern-Dialog.
        if not selected:
            return
        result["value"] = selected
        dialog.destroy()

    def click_cancel():
        dialog.destroy()

    btn_frame = tk.Frame(dialog, bg=BG)
    btn_frame.pack(pady=(14, 18))
    delete_btn = primary_button(btn_frame, "Löschen", click_delete)
    delete_btn.pack(side=tk.LEFT, padx=6)
    secondary_button(btn_frame, "Abbrechen", click_cancel).pack(side=tk.LEFT, padx=6)

    def _refresh_delete_btn(*_):
        # Löschen nur klickbar, wenn der Lock abgelaufen ist UND mind. eine
        # Option gewählt ist.
        set_primary_button_enabled(
            delete_btn,
            unlock["ready"] and any(var.get() for var in vars_by_key.values()))

    for cb in checkbuttons:
        cb.config(command=_refresh_delete_btn)

    if lock_ms > 0:
        def _unlock():
            unlock["ready"] = True
            _refresh_delete_btn()
        dialog.after(lock_ms, _unlock)
    _refresh_delete_btn()

    dialog.bind("<Return>", lambda e: click_delete())
    dialog.bind("<Escape>", lambda e: click_cancel())
    dialog.protocol("WM_DELETE_WINDOW", click_cancel)

    center_dialog_on_parent(dialog, parent)
    dialog.grab_set()
    dialog.wait_window()
    return result["value"]


def _themed_ok_dialog(parent, title: str, message: str) -> None:
    """Modaler OK-Dialog im App-Theme — Basis für info/warning/error.

    Eigener Toplevel mit Dark-Theme-Farben und gebrandeter Titelleiste
    (`tkinter.messagebox.*` ist eine Black-Box ohne Customization-Hooks).
    """
    dialog = create_dialog(parent, title, modal=False, escape_closes=False)

    tk.Label(
        dialog, text=message, font=FONT, bg=BG, fg=TEXT,
        wraplength=380, justify="left",
    ).pack(padx=24, pady=(20, 14))

    btn_frame = tk.Frame(dialog, bg=BG)
    btn_frame.pack(pady=(0, 18))
    primary_button(btn_frame, "OK", dialog.destroy).pack()

    dialog.bind("<Return>", lambda e: dialog.destroy())
    dialog.bind("<Escape>", lambda e: dialog.destroy())
    dialog.protocol("WM_DELETE_WINDOW", dialog.destroy)

    center_dialog_on_parent(dialog, parent)
    dialog.grab_set()
    dialog.wait_window()


def themed_showinfo(parent, title: str, message: str) -> None:
    """Modaler Info-Dialog im App-Theme. Drop-in für `messagebox.showinfo`."""
    _themed_ok_dialog(parent, title, message)


def themed_showwarning(parent, title: str, message: str) -> None:
    """Modaler Warn-Dialog im App-Theme. Drop-in für `messagebox.showwarning`."""
    _themed_ok_dialog(parent, title, message)


def themed_showerror(parent, title: str, message: str) -> None:
    """Modaler Fehler-Dialog im App-Theme. Drop-in für `messagebox.showerror`.

    Für **bekannte, erwartete** Fehler (Validierung, „Keine Einträge" …). Für
    **unerwartete** Fehler mit Traceback bleibt bewusst das rohe
    `messagebox.showerror` — ein themed Toplevel könnte im gestörten Zustand
    selbst scheitern und die Meldung verschlucken. Konvention siehe
    CLAUDE.md, „UI-Fehler sichtbar machen" (Audit N14)."""
    _themed_ok_dialog(parent, title, message)
