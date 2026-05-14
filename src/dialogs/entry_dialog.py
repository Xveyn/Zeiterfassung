import datetime
import tkinter as tk
from tkinter import messagebox

from src.holidays_de import get_holidays
from src.settings import WEEKDAY_KEYS
from src.theme import (
    BG, FONT, PAUSE_VALUES, TEXT, TIME_VALUES,
    apply_combobox_style, apply_dark_titlebar, center_dialog_on_parent,
    dark_combo, primary_button, secondary_button,
)
from src.time_utils import validate_entry


def open_entry_dialog(parent, date_str, storage, settings, on_change):
    """Modal dialog to edit/delete one day's time entry.

    on_change is invoked after successful save or delete so the caller
    can refresh the calendar view.
    """
    dialog = tk.Toplevel(parent)
    dialog.title(date_str)
    dialog.resizable(False, False)
    dialog.grab_set()
    dialog.configure(bg=BG)
    apply_dark_titlebar(dialog)

    entry = storage.get(date_str)

    apply_combobox_style(dialog)

    tk.Label(dialog, text="Start:", font=FONT, bg=BG, fg=TEXT).grid(
        row=0, column=0, padx=10, pady=8, sticky="w")
    weekday_key = WEEKDAY_KEYS[datetime.date.fromisoformat(date_str).weekday()]
    start_var = tk.StringVar(
        value=entry["start"] if entry else settings.get(f"default_start_{weekday_key}")
    )
    dark_combo(dialog, start_var, TIME_VALUES).grid(row=0, column=1, padx=10, pady=8)

    tk.Label(dialog, text="Ende:", font=FONT, bg=BG, fg=TEXT).grid(
        row=1, column=0, padx=10, pady=8, sticky="w")
    end_var = tk.StringVar(
        value=entry["end"] if entry else settings.get(f"default_end_{weekday_key}")
    )
    dark_combo(dialog, end_var, TIME_VALUES).grid(row=1, column=1, padx=10, pady=8)

    tk.Label(dialog, text="Pause (Min):", font=FONT, bg=BG, fg=TEXT).grid(
        row=2, column=0, padx=10, pady=8, sticky="w")

    default_pause = settings.get("default_pause")
    if entry and "pause" in entry:
        current_pause = str(entry["pause"])
    else:
        current_pause = str(default_pause) if not entry else "0"
    pause_var = tk.StringVar(value=current_pause)
    dark_combo(dialog, pause_var, PAUSE_VALUES).grid(row=2, column=1, padx=10, pady=8)

    def save():
        ok, msg = validate_entry(start_var.get(), end_var.get(), pause_minutes=int(pause_var.get()))
        if not ok:
            messagebox.showerror("Fehler", msg, parent=dialog)
            return

        # Feiertags-Warnung nur beim Anlegen, nicht beim Edit (entry is None)
        if entry is None:
            state = settings.get("state")
            if state:
                day = datetime.date.fromisoformat(date_str)
                feiertage = get_holidays(state, day.year)
                if day in feiertage:
                    date_de = day.strftime("%d.%m.%Y")
                    confirm = messagebox.askyesno(
                        "Feiertag",
                        f"Der {date_de} ist {feiertage[day]} (Feiertag).\n\n"
                        "Trotzdem Eintrag anlegen?",
                        parent=dialog,
                    )
                    if not confirm:
                        return

        storage.save(date_str, start_var.get(), end_var.get(), pause=int(pause_var.get()))
        dialog.destroy()
        on_change()

    def delete():
        storage.delete(date_str)
        dialog.destroy()
        on_change()

    btn_frame = tk.Frame(dialog, bg=BG)
    btn_frame.grid(row=3, column=0, columnspan=2, pady=12)

    primary_button(btn_frame, "Speichern", save).pack(side=tk.LEFT, padx=5)
    if entry is not None:
        secondary_button(btn_frame, "Löschen", delete).pack(side=tk.LEFT, padx=5)

    center_dialog_on_parent(dialog, parent)
