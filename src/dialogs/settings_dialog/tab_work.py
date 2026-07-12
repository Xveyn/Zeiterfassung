"""Tab „Arbeitszeit": Standardzeiten, Pause, Werkstudenten-Limit, Kategorien."""

import calendar
import datetime
import tkinter as tk

from src.dialogs.category_dialog import open_category_dialog
from src.dialogs.settings_dialog._shared import label, subheader
from src.settings import WEEKDAY_KEYS
from src.theme import (
    BG, CELL_BG, FONT, FONT_SMALL, PAUSE_VALUES, TEXT, TEXT_MUTED,
    TIME_VALUES, dark_combo, dark_entry, secondary_button,
)
from src.time_utils import DAYS_DE


class WorkTab:
    """Baut den Arbeitszeit-Tab; exponiert die Tk-Variablen, die
    save_settings in dialog.py liest (Vertrag siehe Spec H4)."""

    def __init__(self, frame, dialog, settings):
        label(frame, "Standardzeiten:", row=0, pady=(10, 4), sticky="nw")
        times_frame = tk.Frame(frame, bg=BG)
        times_frame.grid(row=0, column=1, padx=10, pady=(10, 4), sticky="w")

        tk.Label(times_frame, text="Start", font=FONT_SMALL, bg=BG, fg=TEXT_MUTED).grid(
            row=0, column=1, padx=2)
        tk.Label(times_frame, text="Ende", font=FONT_SMALL, bg=BG, fg=TEXT_MUTED).grid(
            row=0, column=2, padx=2)

        start_vars = {}
        end_vars = {}
        for i, (key, lbl) in enumerate(zip(WEEKDAY_KEYS, DAYS_DE, strict=False), start=1):
            tk.Label(times_frame, text=lbl, font=FONT, bg=BG, fg=TEXT, width=3, anchor="w").grid(
                row=i, column=0, padx=(0, 8), pady=2)
            start_vars[key] = tk.StringVar(value=settings.get(f"default_start_{key}"))
            dark_combo(times_frame, start_vars[key], TIME_VALUES).grid(
                row=i, column=1, padx=2, pady=2)
            end_vars[key] = tk.StringVar(value=settings.get(f"default_end_{key}"))
            dark_combo(times_frame, end_vars[key], TIME_VALUES).grid(
                row=i, column=2, padx=2, pady=2)

        label(frame, "Standard-Pause (Min):", row=1)
        pause_var = tk.StringVar(value=str(settings.get("default_pause")))
        dark_combo(frame, pause_var, PAUSE_VALUES).grid(
            row=1, column=1, padx=10, pady=8, sticky="w")

        subheader(frame, "Werkstudenten-Limit", row=2)
        wsl_frame = tk.Frame(frame, bg=BG)
        wsl_frame.grid(row=3, column=0, columnspan=2, padx=10, pady=(0, 4), sticky="we")

        wsl_enabled_var = tk.BooleanVar(value=settings.get("werkstudent_limit_enabled"))
        tk.Checkbutton(
            wsl_frame, text="Wochenstunden-Limit aktivieren", variable=wsl_enabled_var,
            font=FONT, bg=BG, fg=TEXT, selectcolor=CELL_BG,
            activebackground=BG, activeforeground=TEXT, cursor="hand2",
        ).pack(anchor="w")

        def _wsl_date_row(parent_frame, label_text, default_date):
            row = tk.Frame(parent_frame, bg=BG)
            row.pack(anchor="w", pady=(4, 0))
            tk.Label(row, text=label_text, font=FONT, bg=BG, fg=TEXT).pack(
                side=tk.LEFT, padx=(0, 5))
            month_values = [str(m) for m in range(1, 13)]
            year_values = [str(y) for y in range(2020, datetime.date.today().year + 3)]
            day_var = tk.StringVar(value=str(default_date.day))
            max_day = calendar.monthrange(default_date.year, default_date.month)[1]
            day_cb = dark_combo(row, day_var, [str(d) for d in range(1, max_day + 1)], width=3)
            day_cb.pack(side=tk.LEFT, padx=2)
            tk.Label(row, text=".", font=FONT, bg=BG, fg=TEXT).pack(side=tk.LEFT)
            month_var = tk.StringVar(value=str(default_date.month))
            dark_combo(row, month_var, month_values, width=3).pack(side=tk.LEFT, padx=2)
            tk.Label(row, text=".", font=FONT, bg=BG, fg=TEXT).pack(side=tk.LEFT)
            year_var = tk.StringVar(value=str(default_date.year))
            dark_combo(row, year_var, year_values, width=5).pack(side=tk.LEFT, padx=2)

            def _update_days(*_a):
                try:
                    m = int(month_var.get())
                    y = int(year_var.get())
                    md = calendar.monthrange(y, m)[1]
                except (ValueError, KeyError):
                    md = 31
                day_cb["values"] = [str(d) for d in range(1, md + 1)]
                if int(day_var.get()) > md:
                    day_var.set(str(md))

            month_var.trace_add("write", _update_days)
            year_var.trace_add("write", _update_days)
            return day_var, month_var, year_var

        wsl_start_default = (
            datetime.date.fromisoformat(settings.get("werkstudent_limit_start"))
            if settings.get("werkstudent_limit_start") else datetime.date.today())
        wsl_end_default = (
            datetime.date.fromisoformat(settings.get("werkstudent_limit_end"))
            if settings.get("werkstudent_limit_end") else datetime.date.today())
        wsl_start_vars = _wsl_date_row(wsl_frame, "Zeitraum von:", wsl_start_default)
        wsl_end_vars = _wsl_date_row(wsl_frame, "bis:", wsl_end_default)

        wsl_hours_row = tk.Frame(wsl_frame, bg=BG)
        wsl_hours_row.pack(anchor="w", pady=(4, 0))
        tk.Label(wsl_hours_row, text="Limit (Stunden/Woche):", font=FONT, bg=BG, fg=TEXT).pack(
            side=tk.LEFT, padx=(0, 5))
        wsl_hours_var = tk.StringVar(value=str(settings.get("werkstudent_limit_max_hours")))
        dark_entry(wsl_hours_row, wsl_hours_var, width=6).pack(side=tk.LEFT)

        secondary_button(
            frame, "Kategorien verwalten",
            lambda: open_category_dialog(dialog, settings),
        ).grid(row=4, column=0, columnspan=2, padx=10, pady=(12, 8), sticky="w")

        self.frame = frame
        self.start_vars = start_vars
        self.end_vars = end_vars
        self.pause_var = pause_var
        self.wsl_enabled_var = wsl_enabled_var
        self.wsl_start_vars = wsl_start_vars
        self.wsl_end_vars = wsl_end_vars
        self.wsl_hours_var = wsl_hours_var
