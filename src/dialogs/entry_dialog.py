import datetime
import tkinter as tk
from tkinter import messagebox

from src.holidays_de import get_holidays
from src.settings import WEEKDAY_KEYS
from src.theme import (
    BG, FONT, FONT_BOLD, PAUSE_VALUES, TEXT, TEXT_MUTED, TIME_VALUES,
    apply_combobox_style, apply_dark_titlebar, center_dialog_on_parent,
    dark_combo, primary_button, secondary_button, themed_askyesno,
)
from src.time_utils import validate_entry


def open_entry_dialog(parent, date_str, storage, settings, on_change,
                      reservation_store=None, trigger_reconcile=None):
    """Modaler Dialog zum Bearbeiten von Ist-Zeit und Reservierung eines Tages.

    on_change wird nach erfolgreichem Speichern/Löschen aufgerufen, damit der
    Aufrufer den Kalender neu rendert.
    reservation_store / trigger_reconcile sind optional; sind sie gesetzt und
    ist der Tag heute/zukünftig (oder existiert bereits eine Reservierung),
    wird der Reservierungs-Block angezeigt. trigger_reconcile() stößt nach
    einer Reservierungsänderung den Kalender-Abgleich an.
    """
    entry = storage.get(date_str)
    day = datetime.date.fromisoformat(date_str)

    # Feiertags-Warnung beim Anlegen einer Ist-Zeit (nicht beim Edit).
    if entry is None:
        state = settings.get("state")
        if state:
            feiertage = get_holidays(state, day.year)
            if day in feiertage:
                date_de = day.strftime("%d.%m.%Y")
                confirm = themed_askyesno(
                    parent, "Feiertag",
                    f"Der {date_de} ist {feiertage[day]} (Feiertag).\n\n"
                    "Trotzdem Eintrag anlegen?",
                )
                if not confirm:
                    return

    existing_reservation = (
        reservation_store.get(date_str) if reservation_store is not None else None
    )
    show_reservation = reservation_store is not None and (
        day >= datetime.date.today() or existing_reservation is not None
    )

    dialog = tk.Toplevel(parent)
    dialog.title(date_str)
    dialog.resizable(False, False)
    dialog.grab_set()
    dialog.configure(bg=BG)
    apply_dark_titlebar(dialog)
    apply_combobox_style(dialog)

    # --- Ist-Zeit ---
    tk.Label(dialog, text="Start:", font=FONT, bg=BG, fg=TEXT).grid(
        row=0, column=0, padx=10, pady=8, sticky="w")
    weekday_key = WEEKDAY_KEYS[day.weekday()]
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
        ok, msg = validate_entry(start_var.get(), end_var.get(),
                                 pause_minutes=int(pause_var.get()))
        if not ok:
            messagebox.showerror("Fehler", msg, parent=dialog)
            return
        storage.save(date_str, start_var.get(), end_var.get(),
                     pause=int(pause_var.get()))
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

    # --- Reservierung ---
    # Ist-Zeit und Reservierung sind bewusst getrennte Konzepte mit je eigenem
    # Speichern-Button. Jeder Block speichert unabhängig und schließt danach den
    # Dialog — es gibt absichtlich keinen kombinierten Speichern-Pfad.
    if show_reservation:
        tk.Label(
            dialog, text="— Reservierung —", font=FONT_BOLD, bg=BG, fg=TEXT_MUTED,
        ).grid(row=4, column=0, columnspan=2, padx=10, pady=(8, 4))

        tk.Label(dialog, text="Start:", font=FONT, bg=BG, fg=TEXT).grid(
            row=5, column=0, padx=10, pady=8, sticky="w")
        res_start_var = tk.StringVar(
            value=existing_reservation["start"] if existing_reservation
            else settings.get(f"default_start_{weekday_key}")
        )
        dark_combo(dialog, res_start_var, TIME_VALUES).grid(
            row=5, column=1, padx=10, pady=8)

        tk.Label(dialog, text="Ende:", font=FONT, bg=BG, fg=TEXT).grid(
            row=6, column=0, padx=10, pady=8, sticky="w")
        res_end_var = tk.StringVar(
            value=existing_reservation["end"] if existing_reservation
            else settings.get(f"default_end_{weekday_key}")
        )
        dark_combo(dialog, res_end_var, TIME_VALUES).grid(
            row=6, column=1, padx=10, pady=8)

        def save_reservation():
            ok, msg = validate_entry(res_start_var.get(), res_end_var.get(),
                                     pause_minutes=0)
            if not ok:
                messagebox.showerror("Fehler", msg, parent=dialog)
                return
            reservation_store.save(date_str, res_start_var.get(), res_end_var.get())
            dialog.destroy()
            on_change()
            if trigger_reconcile is not None:
                trigger_reconcile()

        def delete_reservation():
            reservation_store.delete(date_str)
            dialog.destroy()
            on_change()
            if trigger_reconcile is not None:
                trigger_reconcile()

        res_btn_frame = tk.Frame(dialog, bg=BG)
        res_btn_frame.grid(row=7, column=0, columnspan=2, pady=12)
        primary_button(res_btn_frame, "Reservierung speichern",
                       save_reservation).pack(side=tk.LEFT, padx=5)
        if existing_reservation is not None:
            secondary_button(res_btn_frame, "Reservierung löschen",
                             delete_reservation).pack(side=tk.LEFT, padx=5)

    center_dialog_on_parent(dialog, parent)
