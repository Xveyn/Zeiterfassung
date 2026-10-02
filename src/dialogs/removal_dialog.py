"""Rückfrage vor „Zeiterfassung entfernen" (#50).

Reiner Aufbau; was entfernt wird und in welcher Reihenfolge, steht in
`src/removal.py`.
"""
import tkinter as tk

from src.theme import (
    BG, CELL_BG, FONT, TEXT, center_dialog_on_parent, create_dialog, primary_button,
    px, run_modal, secondary_button,
)

MESSAGE = (
    "Entfernt werden:\n"
    "• Zugangsdaten und Schlüsselbund-Einträge\n"
    "• Autostart und Menüeintrag\n\n"
    "Die Programmdatei löschst du danach selbst — die App sagt dir, welche.\n"
    "Zeiten und Einstellungen bleiben erhalten, solange du nichts anderes "
    "ankreuzt."
)
DATA_LABEL = "Auch Zeiten, Einstellungen und Protokoll löschen"


def ask_removal(parent) -> bool | None:
    """Modal. `True`: auch die Nutzerdaten, `False`: nur Zugangsdaten und
    Integration, `None`: abgebrochen."""
    dialog = create_dialog(parent, "Zeiterfassung entfernen", modal=False,
                           escape_closes=False)
    result: dict[str, bool | None] = {"value": None}

    tk.Label(dialog, text=MESSAGE, font=FONT, bg=BG, fg=TEXT,
             wraplength=px(420), justify="left").pack(padx=24, pady=(20, 10))

    data_var = tk.BooleanVar(value=False)
    tk.Checkbutton(
        dialog, text=DATA_LABEL, variable=data_var, font=FONT, bg=BG, fg=TEXT,
        selectcolor=CELL_BG, activebackground=BG, activeforeground=TEXT,
        cursor="hand2",
    ).pack(padx=28, anchor="w")

    def confirm():
        result["value"] = bool(data_var.get())
        dialog.destroy()

    def cancel():
        dialog.destroy()

    btn_frame = tk.Frame(dialog, bg=BG)
    btn_frame.pack(pady=(14, 18))
    primary_button(btn_frame, "Entfernen", confirm).pack(side=tk.LEFT, padx=6)
    secondary_button(btn_frame, "Abbrechen", cancel).pack(side=tk.LEFT, padx=6)

    dialog.bind("<Escape>", lambda _e: cancel())
    dialog.protocol("WM_DELETE_WINDOW", cancel)

    center_dialog_on_parent(dialog, parent)
    run_modal(dialog)
    return result["value"]
