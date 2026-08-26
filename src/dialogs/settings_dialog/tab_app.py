"""Tab „App": Bundesland, UI-Optionen, Skalierung, Benachrichtigungen."""

import tkinter as tk
from tkinter import ttk

from src.autostart import is_autostart_enabled
from src.dialogs.settings_dialog._shared import label
from src.holidays_de import STATES
from src.send_reminder import SHIFT_LABELS, label_for_shift
from src.theme import (
    ACCENT, BG, CELL_BG, FONT, FONT_BOLD, FONT_SMALL, TEXT, TEXT_MUTED,
    TIME_VALUES, dark_combo,
)


class AppTab:
    """Baut den App-Tab; exponiert die Variablen für save_settings."""

    def __init__(self, frame, settings):
        label(frame, "Bundesland:", row=0, pady=(10, 8))
        state_labels = [lbl for _, lbl in STATES]
        current_code = settings.get("state")
        current_label = next(
            (lbl for code, lbl in STATES if code == current_code),
            STATES[0][1],
        )
        state_var = tk.StringVar(value=current_label)
        dark_combo(frame, state_var, state_labels, width=22).grid(
            row=0, column=1, padx=10, pady=(10, 8), sticky="w")

        # Gerätelokale UI-Optionen. Alle in app_frame (ein Grid-Member), damit die
        # pack-Interna dieses Frames unberührt bleiben.
        app_frame = tk.Frame(frame, bg=BG)
        app_frame.grid(row=1, column=0, columnspan=2, padx=10, pady=(4, 4), sticky="we")

        show_weekend_var = tk.BooleanVar(value=settings.get("show_weekend"))
        weekend_cb = tk.Checkbutton(
            app_frame, text="Wochenende (Sa/So) im Kalender anzeigen",
            variable=show_weekend_var, font=FONT,
            bg=BG, fg=TEXT, selectcolor=CELL_BG,
            activebackground=BG, activeforeground=TEXT,
            cursor="hand2",
        )
        weekend_cb.pack(anchor="w")
        if settings.get("workweek_only"):
            # Sonst stünde hier ein Haken, der sichtbar nichts tut: der
            # Nur-Werktage-Modus blendet Sa/So ohnehin aus.
            weekend_cb.config(state="disabled")
            tk.Label(
                app_frame,
                text="Durch „Nur Werktage\" (Arbeitszeit) überstimmt.",
                font=FONT_SMALL, bg=BG, fg=TEXT_MUTED,
            ).pack(anchor="w", padx=(24, 0))

        autostart_var = tk.BooleanVar(value=is_autostart_enabled())
        tk.Checkbutton(
            app_frame, text="Autostart (minimiert bei Anmeldung)",
            variable=autostart_var, font=FONT,
            bg=BG, fg=TEXT, selectcolor=CELL_BG,
            activebackground=BG, activeforeground=TEXT,
            cursor="hand2",
        ).pack(anchor="w")

        always_on_top_var = tk.BooleanVar(value=settings.get("always_on_top"))
        tk.Checkbutton(
            app_frame, text="Immer im Vordergrund",
            variable=always_on_top_var, font=FONT,
            bg=BG, fg=TEXT, selectcolor=CELL_BG,
            activebackground=BG, activeforeground=TEXT,
            cursor="hand2",
        ).pack(anchor="w")

        minimize_to_tray_var = tk.BooleanVar(value=settings.get("minimize_to_tray"))
        tk.Checkbutton(
            app_frame, text="Beim Schließen in den Infobereich minimieren",
            variable=minimize_to_tray_var, font=FONT,
            bg=BG, fg=TEXT, selectcolor=CELL_BG,
            activebackground=BG, activeforeground=TEXT,
            cursor="hand2",
        ).pack(anchor="w")

        # --- Darstellung (UI-Skalierung, gerätelokal) ---
        tk.Label(
            app_frame, text="— Darstellung —", font=FONT_BOLD,
            bg=BG, fg=TEXT_MUTED,
        ).pack(pady=(12, 4))
        scale_row = tk.Frame(app_frame, bg=BG)
        scale_row.pack(fill="x")
        tk.Label(
            scale_row, text="Skalierung:", font=FONT, bg=BG, fg=TEXT,
        ).pack(side=tk.LEFT, padx=(0, 8))

        # ttk.Scale statt klassischer tk.Scale: das clam-Theme ist via
        # apply_combobox_style aktiv, klassische tk.Scale rendert unter Windows
        # einen hellen System-Trough/-Regler. Wert in eigenem Label (kein
        # showvalue-Kasten); auf 5er-Schritte gerastert (ttk.Scale kennt kein
        # resolution). Akzent analog dark_entry: Ruhe TEXT_MUTED, Press ACCENT.
        scale_style = ttk.Style(frame)
        scale_style.configure(
            "Display.Horizontal.TScale",
            background=TEXT_MUTED, troughcolor=CELL_BG,
            bordercolor=CELL_BG, darkcolor=TEXT_MUTED, lightcolor=TEXT_MUTED,
        )
        scale_style.map(
            "Display.Horizontal.TScale",
            background=[("pressed", ACCENT)],
            darkcolor=[("pressed", ACCENT)],
            lightcolor=[("pressed", ACCENT)],
        )
        scale_var = tk.DoubleVar(value=round(settings.get("ui_scale") * 100))
        scale_value_label = tk.Label(
            scale_row, text=f"{round(scale_var.get() / 5) * 5} %", font=FONT,
            bg=BG, fg=TEXT_MUTED, width=5, anchor="w",
        )

        def _on_scale(_raw):
            scale_value_label.config(text=f"{round(scale_var.get() / 5) * 5} %")

        scale_widget = ttk.Scale(
            scale_row, from_=75, to=200, orient="horizontal",
            variable=scale_var, command=_on_scale, length=200,
            style="Display.Horizontal.TScale",
        )
        scale_widget.bind(
            "<ButtonPress-1>", lambda _e: scale_value_label.config(fg=ACCENT), add="+",
        )
        scale_widget.bind(
            "<ButtonRelease-1>", lambda _e: scale_value_label.config(fg=TEXT_MUTED), add="+",
        )
        scale_widget.pack(side=tk.LEFT)
        scale_value_label.pack(side=tk.LEFT, padx=(8, 0))
        tk.Label(
            app_frame, text="Änderung startet die App neu.", font=FONT_SMALL,
            bg=BG, fg=TEXT_MUTED,
        ).pack(anchor="w", pady=(2, 0))

        # --- Benachrichtigungen (Reservierungs-Erinnerungen, gerätelokal) ---
        tk.Label(
            app_frame, text="— Benachrichtigungen —", font=FONT_BOLD,
            bg=BG, fg=TEXT_MUTED,
        ).pack(pady=(12, 4))

        reminders_enabled_var = tk.BooleanVar(value=settings.get("reminders_enabled"))
        tk.Checkbutton(
            app_frame, text="Erinnerungen als Toast anzeigen",
            variable=reminders_enabled_var, font=FONT,
            bg=BG, fg=TEXT, selectcolor=CELL_BG,
            activebackground=BG, activeforeground=TEXT, cursor="hand2",
        ).pack(anchor="w")

        reminder_row = tk.Frame(app_frame, bg=BG)
        reminder_row.pack(anchor="w", pady=(4, 0))
        tk.Label(
            reminder_row, text="Erinnerung Minuten vor Ende der Reservierung:",
            font=FONT, bg=BG, fg=TEXT,
        ).pack(side=tk.LEFT, padx=(0, 8))
        reminder_minutes_var = tk.StringVar(
            value=str(settings.get("reminder_minutes_before")))
        dark_combo(
            reminder_row, reminder_minutes_var,
            [str(m) for m in range(0, 121, 5)], width=4,
        ).pack(side=tk.LEFT)
        tk.Label(
            app_frame, text="Nur für Reservierungen mit Kategorie.", font=FONT_SMALL,
            bg=BG, fg=TEXT_MUTED,
        ).pack(anchor="w", pady=(2, 0))

        send_reminder_enabled_var = tk.BooleanVar(value=settings.get("send_reminder_enabled"))
        tk.Checkbutton(
            app_frame, text="Erinnerung zum Verschicken der Arbeitszeiten",
            variable=send_reminder_enabled_var, font=FONT,
            bg=BG, fg=TEXT, selectcolor=CELL_BG,
            activebackground=BG, activeforeground=TEXT, cursor="hand2",
        ).pack(anchor="w", pady=(8, 0))

        send_reminder_row = tk.Frame(app_frame, bg=BG)
        send_reminder_row.pack(anchor="w", pady=(4, 0))
        tk.Label(
            send_reminder_row, text="Tag im Monat:",
            font=FONT, bg=BG, fg=TEXT,
        ).pack(side=tk.LEFT, padx=(0, 8))
        send_reminder_day_var = tk.StringVar(
            value=str(settings.get("send_reminder_day")))
        dark_combo(
            send_reminder_row, send_reminder_day_var,
            [str(d) for d in range(1, 32)], width=4,
        ).pack(side=tk.LEFT, padx=(0, 8))
        tk.Label(
            send_reminder_row, text="um", font=FONT, bg=BG, fg=TEXT,
        ).pack(side=tk.LEFT, padx=(0, 8))
        send_reminder_time_var = tk.StringVar(value=settings.get("send_reminder_time"))
        dark_combo(
            send_reminder_row, send_reminder_time_var, TIME_VALUES, width=6,
        ).pack(side=tk.LEFT)
        tk.Label(
            app_frame, text="Bei kürzeren Monaten wird auf den letzten Tag verschoben.",
            font=FONT_SMALL, bg=BG, fg=TEXT_MUTED,
        ).pack(anchor="w", pady=(2, 0))

        # Der Settings-Dialog ist nicht scrollbar (create_dialog setzt
        # resizable(False, False)) und der Notebook nimmt die Höhe des
        # höchsten Tabs an — jede Zeile hier wächst also 1:1 in die
        # Dialoghöhe. Die folgenden Optionen sind deshalb bewusst auf
        # wenige, breite Zeilen gelegt statt auf je eine eigene.
        shift_row = tk.Frame(app_frame, bg=BG)
        shift_row.pack(anchor="w", pady=(2, 0))
        tk.Label(
            shift_row, text="Fällt er aufs Wochenende:",
            font=FONT, bg=BG, fg=TEXT,
        ).pack(side=tk.LEFT, padx=(0, 8))
        send_reminder_shift_var = tk.StringVar(
            value=label_for_shift(settings.get("send_reminder_weekend_shift")))
        dark_combo(
            shift_row, send_reminder_shift_var,
            [SHIFT_LABELS[m] for m in ("none", "backward", "forward")],
            width=18,
        ).pack(side=tk.LEFT, padx=(0, 8))
        send_reminder_shift_holidays_var = tk.BooleanVar(
            value=settings.get("send_reminder_shift_holidays"))
        tk.Checkbutton(
            shift_row, text="auch Feiertage",
            variable=send_reminder_shift_holidays_var, font=FONT,
            bg=BG, fg=TEXT, selectcolor=CELL_BG,
            activebackground=BG, activeforeground=TEXT, cursor="hand2",
        ).pack(side=tk.LEFT)

        # --- Tagesbezogene Erinnerung an Reservierungen ---
        res_row = tk.Frame(app_frame, bg=BG)
        res_row.pack(anchor="w", pady=(4, 0))
        send_reminder_reservations_var = tk.BooleanVar(
            value=settings.get("send_reminder_reservations_enabled"))
        tk.Checkbutton(
            res_row, text="Reservierungen",
            variable=send_reminder_reservations_var, font=FONT,
            bg=BG, fg=TEXT, selectcolor=CELL_BG,
            activebackground=BG, activeforeground=TEXT, cursor="hand2",
        ).pack(side=tk.LEFT, padx=(0, 12))
        tk.Label(
            res_row, text="Standard:", font=FONT, bg=BG, fg=TEXT,
        ).pack(side=tk.LEFT, padx=(0, 8))
        send_reminder_default_minutes_var = tk.StringVar(
            value=str(settings.get("send_reminder_default_minutes")))
        dark_combo(
            res_row, send_reminder_default_minutes_var,
            [str(m) for m in range(0, 121, 5)], width=4,
        ).pack(side=tk.LEFT, padx=(0, 8))
        tk.Label(
            res_row, text="Minuten vor Ende", font=FONT, bg=BG, fg=TEXT,
        ).pack(side=tk.LEFT)
        # Ein Hinweis statt zweier Zeilen. Ohne Kalender-Abgleich zeigt die
        # App gar keine Reservierungen (App._reservations_active) — der
        # Schalter bliebe sonst wirkungslos, ohne dass man sieht warum.
        res_hint = "Erinnerungs-Tage werden im Tages-Dialog gesetzt."
        if not settings.get("gcal_enabled"):
            res_hint = ("Erinnerungs-Tage im Tages-Dialog; nur mit Abgleich "
                        "(Tab Google).")
        tk.Label(
            app_frame, text=res_hint, font=FONT_SMALL, bg=BG, fg=TEXT_MUTED,
        ).pack(anchor="w", padx=(24, 0), pady=(2, 0))

        period_row = tk.Frame(app_frame, bg=BG)
        period_row.pack(anchor="w", pady=(4, 0))
        send_period_from_last_var = tk.BooleanVar(
            value=settings.get("send_period_from_last_reminder"))
        tk.Checkbutton(
            period_row, text="Zeitraum ab der letzten Erinnerung vorbelegen",
            variable=send_period_from_last_var, font=FONT,
            bg=BG, fg=TEXT, selectcolor=CELL_BG,
            activebackground=BG, activeforeground=TEXT, cursor="hand2",
        ).pack(side=tk.LEFT, padx=(0, 12))
        send_period_anchor_monthly_var = tk.BooleanVar(
            value=settings.get("send_period_anchor_monthly"))
        tk.Checkbutton(
            period_row, text="inkl. Monatstermine",
            variable=send_period_anchor_monthly_var, font=FONT,
            bg=BG, fg=TEXT, selectcolor=CELL_BG,
            activebackground=BG, activeforeground=TEXT, cursor="hand2",
        ).pack(side=tk.LEFT)

        self.frame = frame
        self.state_var = state_var
        self.show_weekend_var = show_weekend_var
        self.autostart_var = autostart_var
        self.always_on_top_var = always_on_top_var
        self.minimize_to_tray_var = minimize_to_tray_var
        self.scale_var = scale_var
        self.reminders_enabled_var = reminders_enabled_var
        self.reminder_minutes_var = reminder_minutes_var
        self.send_reminder_enabled_var = send_reminder_enabled_var
        self.send_reminder_day_var = send_reminder_day_var
        self.send_reminder_time_var = send_reminder_time_var
        self.send_reminder_shift_var = send_reminder_shift_var
        self.send_reminder_shift_holidays_var = send_reminder_shift_holidays_var
        self.send_reminder_reservations_var = send_reminder_reservations_var
        self.send_reminder_default_minutes_var = send_reminder_default_minutes_var
        self.send_period_from_last_var = send_period_from_last_var
        self.send_period_anchor_monthly_var = send_period_anchor_monthly_var
