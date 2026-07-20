import datetime
import tkinter as tk
from tkinter import ttk

from src.autostart import disable_autostart, enable_autostart, is_autostart_enabled, resolve_autostart_target
from src.updater import frequency_for_label
from src.theme import (
    BG,
    apply_combobox_style, apply_notebook_style, attach_unfocus_on_click,
    center_dialog_on_parent, create_dialog,
    primary_button, secondary_button,
    themed_showwarning, themed_showerror,
)
from src.holidays_de import code_for_state_label
from src.settings import (
    WEEKDAY_KEYS, clamp_ui_scale, parse_hourly_rate,
    parse_reminder_minutes, resolve_calendar_id,
)
from src.time_utils import validate_period
from src.time_utils import DAYS_DE, validate_entry
from src.weekly_limit import format_limit_warnings, period_scan_needed, scan_period_for_warnings
from src.dialogs.settings_dialog.tab_app import AppTab
from src.dialogs.settings_dialog.tab_google import GoogleTab
from src.dialogs.settings_dialog.tab_mail import MailTab
from src.dialogs.settings_dialog.tab_updates import UpdatesTab
from src.dialogs.settings_dialog.tab_work import WorkTab


def open_settings_dialog(parent, settings, base_path, on_change, *,
                         runner, conflicts_store=None, storage=None,
                         reservation_store=None, on_request_restart=None,
                         data_lock=None, sync_guard=None):
    """Modaler Dialog zum Bearbeiten der App-Einstellungen, aufgeteilt auf fünf
    Tabs (Arbeitszeit / Bericht & Mail / Google / App / Updates).

    on_change wird nach erfolgreichem Speichern aufgerufen, damit der Kalender
    sich aktualisiert. conflicts_store und storage sind optional; sind sie
    gesetzt, erscheint im Google-Tab der Sync-Block mit Konflikte-Button.
    data_lock/sync_guard: geteilter Store-Lock + Sync-Guard für die Kompaktierung
    (Audit H1/H2) — von App durchgereicht.
    runner: der App-BackgroundTaskRunner (App._bg); alle Hintergrund-Worker des
    Dialogs laufen über runner.run(fn, on_done) (Audit H5).
    """
    dialog = create_dialog(parent, "Einstellungen", escape_closes=False)

    apply_combobox_style(dialog)
    apply_notebook_style(dialog)

    notebook = ttk.Notebook(dialog, style="Dark.TNotebook")
    notebook.pack(fill="both", expand=True, padx=8, pady=(8, 0))

    tab_work = tk.Frame(notebook, bg=BG)
    tab_mail = tk.Frame(notebook, bg=BG)
    tab_google = tk.Frame(notebook, bg=BG)
    tab_app = tk.Frame(notebook, bg=BG)
    tab_updates = tk.Frame(notebook, bg=BG)
    notebook.add(tab_work, text="Arbeitszeit")
    notebook.add(tab_mail, text="Bericht & Mail")
    notebook.add(tab_google, text="Google")
    notebook.add(tab_app, text="App")
    notebook.add(tab_updates, text="Updates")

    # ===================== Tab: Arbeitszeit =====================
    work = WorkTab(tab_work, dialog, settings)

    # ===================== Tab: Bericht & Mail =====================
    mail = MailTab(tab_mail, settings)

    # ===================== Tab: Google =====================
    google = GoogleTab(
        tab_google, dialog, settings, base_path, on_change, runner,
        storage, conflicts_store, reservation_store, data_lock, sync_guard)

    # ===================== Tab: App =====================
    app = AppTab(tab_app, settings)

    # ===================== Tab: Updates =====================
    updates_tab = UpdatesTab(tab_updates, settings, runner)

    def _on_tab_changed(_event):
        if notebook.select() == str(tab_updates):
            updates_tab.on_tab_selected()

    notebook.bind("<<NotebookTabChanged>>", _on_tab_changed)

    # ===================== Speichern / Buttons =====================
    tabs = {
        "work": work.frame,
        "mail": mail.frame,
        "google": google.frame,
        "app": app.frame,
        "updates": updates_tab.frame,
    }

    def save_settings():
        for key, lbl in zip(WEEKDAY_KEYS, DAYS_DE, strict=False):
            ok, msg = validate_entry(work.start_vars[key].get(), work.end_vars[key].get())
            if not ok:
                notebook.select(tabs["work"])
                themed_showerror(
                    dialog,
                    "Standard-Arbeitszeit ungültig",
                    f"{lbl}: {msg}",
                )
                return

        wsl_start_date = datetime.date(
            int(work.wsl_start_vars[2].get()), int(work.wsl_start_vars[1].get()),
            int(work.wsl_start_vars[0].get()))
        wsl_end_date = datetime.date(
            int(work.wsl_end_vars[2].get()), int(work.wsl_end_vars[1].get()),
            int(work.wsl_end_vars[0].get()))
        wsl_start_iso = wsl_start_date.isoformat()
        wsl_end_iso = wsl_end_date.isoformat()
        if work.wsl_enabled_var.get():
            ok, msg = validate_period(wsl_start_iso, wsl_end_iso)
            if not ok:
                notebook.select(tabs["work"])
                themed_showerror(dialog, "Werkstudenten-Limit-Zeitraum ungültig", msg)
                return
        old_wsl_max_hours = settings.get("werkstudent_limit_max_hours")
        try:
            wsl_max_hours = float(work.wsl_hours_var.get())
        except ValueError:
            wsl_max_hours = old_wsl_max_hours

        old_wsl_enabled = settings.get("werkstudent_limit_enabled")
        old_wsl_start = settings.get("werkstudent_limit_start")
        old_wsl_end = settings.get("werkstudent_limit_end")

        new_autostart = app.autostart_var.get()
        old_autostart = is_autostart_enabled()

        # Autostart-Toggle muss vor dem Settings-Write passieren, weil
        # er failen kann und dann nichts persistiert werden soll.
        if new_autostart != old_autostart:
            try:
                if new_autostart:
                    target, arguments = resolve_autostart_target(base_path)
                    enable_autostart(target, arguments)
                else:
                    disable_autostart()
            except Exception as e:
                notebook.select(tabs["app"])
                themed_showerror(
                    dialog,
                    "Autostart-Fehler",
                    f"Autostart konnte nicht geändert werden:\n{e}",
                )
                return

        reminder_minutes = parse_reminder_minutes(app.reminder_minutes_var.get())
        if reminder_minutes is None:
            notebook.select(tabs["app"])
            themed_showerror(
                dialog, "Erinnerungszeit ungültig",
                "Bitte eine ganze Zahl zwischen 0 und 120 Minuten angeben.",
            )
            return

        hourly_rate = parse_hourly_rate(mail.rate_var.get())
        selected_code = code_for_state_label(app.state_var.get())
        old_scale = settings.get("ui_scale")
        new_scale = clamp_ui_scale((round(app.scale_var.get() / 5) * 5) / 100)

        updates = {
            "autostart": new_autostart,
            "default_pause": int(work.pause_var.get()),
            "recipient": mail.recipient_var.get(),
            "name": mail.name_var.get(),
            "mail_subject": mail.subject_var.get(),
            "mail_greeting": mail.greeting_var.get(),
            "mail_content": mail.content_text.get("1.0", "end-1c"),
            "mail_closing": mail.closing_text.get("1.0", "end-1c"),
            "hourly_rate": hourly_rate,
            "state": selected_code,
            "show_weekend": app.show_weekend_var.get(),
            "always_on_top": app.always_on_top_var.get(),
            "minimize_to_tray": app.minimize_to_tray_var.get(),
            "reminders_enabled": app.reminders_enabled_var.get(),
            "reminder_minutes_before": reminder_minutes,
            "send_reminder_enabled": app.send_reminder_enabled_var.get(),
            "send_reminder_day": int(app.send_reminder_day_var.get()),
            "send_reminder_time": app.send_reminder_time_var.get(),
            "update_check_frequency": frequency_for_label(updates_tab.frequency_var.get()),
            "ui_scale": new_scale,
            "werkstudent_limit_enabled": work.wsl_enabled_var.get(),
            "werkstudent_limit_start": wsl_start_iso,
            "werkstudent_limit_end": wsl_end_iso,
            "werkstudent_limit_max_hours": wsl_max_hours,
            "pause_warning_enabled": work.pause_warning_var.get(),
        }
        for key in WEEKDAY_KEYS:
            updates[f"default_start_{key}"] = work.start_vars[key].get()
            updates[f"default_end_{key}"] = work.end_vars[key].get()
        settings.apply_updates(updates)
        # Kalender-Auswahl: Klarname zurück auf ID mappen, als Sync-Setting
        # speichern. Nur wenn die Kalenderliste schon geladen ist (cal_map
        # gefüllt) — sonst würde ein vorschnelles Speichern "primary" festschreiben.
        if settings.get("gcal_enabled") and google.cal_map:
            selected_cal_id = resolve_calendar_id(
                google.cal_map, google.cal_var.get(), settings.get("gcal_calendar_id"))
            if selected_cal_id != settings.get("gcal_calendar_id"):
                settings.set_synced("gcal_calendar_id", selected_cal_id)

        old_wsl = {
            "enabled": old_wsl_enabled, "start": old_wsl_start, "end": old_wsl_end,
            "max_hours": old_wsl_max_hours,
        }
        new_wsl = {
            "enabled": work.wsl_enabled_var.get(), "start": wsl_start_iso, "end": wsl_end_iso,
            "max_hours": wsl_max_hours,
        }
        if storage is not None and period_scan_needed(old_wsl, new_wsl):
            period_warnings = scan_period_for_warnings(settings, storage.get_all())
            if period_warnings:
                notebook.select(tabs["work"])
                themed_showwarning(
                    dialog, "Wochenlimit überschritten",
                    "Im konfigurierten Zeitraum liegen bereits erfasste Wochen über "
                    f"dem Limit:\n\n{format_limit_warnings(period_warnings)}\n\n"
                    "Grobe Näherung, keine rechtliche Bewertung.",
                )

        on_change()
        dialog.destroy()
        if on_request_restart is not None and new_scale != old_scale:
            on_request_restart()

    btn_frame = tk.Frame(dialog, bg=BG)
    btn_frame.pack(pady=12)
    primary_button(btn_frame, "Speichern", save_settings).pack(side=tk.LEFT, padx=5)
    secondary_button(btn_frame, "Abbrechen", dialog.destroy).pack(side=tk.LEFT, padx=5)

    attach_unfocus_on_click(dialog)
    dialog.bind("<Escape>", lambda _e: dialog.destroy())
    center_dialog_on_parent(dialog, parent)
