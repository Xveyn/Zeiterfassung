import logging
import os
import threading
import tkinter as tk
import traceback
from tkinter import messagebox
from typing import Any

from src.autostart import disable_autostart, enable_autostart, resolve_autostart_target
from src.platform_open import open_folder
from src.theme import (
    ACCENT, BG, CELL_BG, FONT, FONT_BOLD, FONT_SMALL,
    PAUSE_VALUES, STATUS_OK, TEXT, TEXT_MUTED, TIME_VALUES,
    apply_combobox_style, apply_dark_titlebar, center_dialog_on_parent,
    dark_combo, dark_entry, dark_text,
    primary_button, secondary_button,
)
from src.holidays_de import STATES
from src.settings import WEEKDAY_KEYS, SYNCED_SETTING_KEYS
from src.time_utils import DAYS_DE, validate_entry


def open_settings_dialog(parent, settings, base_path, on_change, *,
                         conflicts_store=None, storage=None):
    """Modal dialog for editing app settings.

    on_change is called after a successful save so the calendar can refresh.
    conflicts_store and storage are optional; when provided, a Sync section
    with a conflicts button is shown.
    """
    dialog = tk.Toplevel(parent)
    dialog.title("Einstellungen")
    dialog.resizable(False, False)
    dialog.grab_set()
    dialog.configure(bg=BG)
    apply_dark_titlebar(dialog)

    apply_combobox_style(dialog)

    creds_path = os.path.join(base_path, "credentials.json")

    def label(text, row, col=0, **grid_kw):
        kw: dict[str, Any] = dict(padx=10, pady=8, sticky="w")
        kw.update(grid_kw)
        tk.Label(dialog, text=text, font=FONT, bg=BG, fg=TEXT).grid(row=row, column=col, **kw)

    tk.Label(
        dialog, text="— Gmail-Zugangsdaten —", font=FONT_BOLD,
        bg=BG, fg=TEXT_MUTED,
    ).grid(row=0, column=0, columnspan=2, padx=10, pady=(8, 4))

    label("Datenordner:", row=1, pady=4)

    creds_row = tk.Frame(dialog, bg=BG)
    creds_row.grid(row=1, column=1, padx=10, pady=4, sticky="w")

    def open_data_folder():
        try:
            open_folder(base_path)
        except Exception as e:
            logging.getLogger(__name__).exception("Datenordner konnte nicht geöffnet werden")
            messagebox.showerror(
                "Ordner konnte nicht geöffnet werden",
                f"{type(e).__name__}: {e}\n\n{traceback.format_exc()}",
                parent=dialog,
            )

    secondary_button(creds_row, "Ordner öffnen", open_data_folder, padx=12, pady=2).pack(side=tk.LEFT)

    status_label = tk.Label(creds_row, text="", font=FONT_SMALL, bg=BG)
    status_label.pack(side=tk.LEFT, padx=(10, 0))

    def refresh_status():
        if not status_label.winfo_exists():
            return
        if os.path.exists(creds_path):
            status_label.config(text="✓ credentials.json vorhanden", fg=STATUS_OK)
        else:
            status_label.config(text="✗ credentials.json fehlt", fg=ACCENT)
        dialog.after(500, refresh_status)

    refresh_status()

    times_label = tk.Label(
        dialog, text="Standardzeiten: ▶", font=FONT, bg=BG, fg=TEXT,
        cursor="hand2",
    )
    times_label.grid(row=3, column=0, padx=10, pady=8, sticky="w")

    times_frame = tk.Frame(dialog, bg=BG)
    times_frame.grid(row=3, column=1, rowspan=2, padx=10, pady=4, sticky="w")
    times_frame.grid_remove()  # default eingeklappt — User klappt bei Bedarf auf

    def toggle_times(_event=None):
        if times_frame.winfo_ismapped():
            times_frame.grid_remove()
            times_label.config(text="Standardzeiten: ▶")
        else:
            times_frame.grid()
            times_label.config(text="Standardzeiten: ▼")

    times_label.bind("<Button-1>", toggle_times)

    tk.Label(times_frame, text="Start", font=FONT_SMALL, bg=BG, fg=TEXT_MUTED).grid(
        row=0, column=1, padx=2)
    tk.Label(times_frame, text="Ende", font=FONT_SMALL, bg=BG, fg=TEXT_MUTED).grid(
        row=0, column=2, padx=2)

    start_vars = {}
    end_vars = {}
    for i, (key, lbl) in enumerate(zip(WEEKDAY_KEYS, DAYS_DE), start=1):
        tk.Label(times_frame, text=lbl, font=FONT, bg=BG, fg=TEXT, width=3, anchor="w").grid(
            row=i, column=0, padx=(0, 8), pady=2)
        start_vars[key] = tk.StringVar(value=settings.get(f"default_start_{key}"))
        dark_combo(times_frame, start_vars[key], TIME_VALUES).grid(
            row=i, column=1, padx=2, pady=2)
        end_vars[key] = tk.StringVar(value=settings.get(f"default_end_{key}"))
        dark_combo(times_frame, end_vars[key], TIME_VALUES).grid(
            row=i, column=2, padx=2, pady=2)

    # Pause bleibt absichtlich global — Spec 2026-05-08, Out-of-Scope: Pause pro Wochentag.
    label("Standard-Pause (Min):", row=5)
    pause_var = tk.StringVar(value=str(settings.get("default_pause")))
    dark_combo(dialog, pause_var, PAUSE_VALUES).grid(row=5, column=1, padx=10, pady=8)

    label("Empfänger:", row=6)
    recipient_var = tk.StringVar(value=settings.get("recipient"))
    dark_entry(dialog, recipient_var, width=25).grid(row=6, column=1, padx=10, pady=8)

    label("Name:", row=7)
    name_var = tk.StringVar(value=settings.get("name"))
    dark_entry(dialog, name_var, width=25).grid(row=7, column=1, padx=10, pady=8)

    label("Stundenlohn (€):", row=8)
    rate_var = tk.StringVar(value=str(settings.get("hourly_rate") or ""))
    dark_entry(dialog, rate_var, width=10).grid(row=8, column=1, padx=10, pady=8, sticky="w")

    tk.Label(
        dialog, text="(optional – nur für dich sichtbar)", font=FONT_SMALL,
        bg=BG, fg=TEXT_MUTED,
    ).grid(row=8, column=1, padx=(120, 10), pady=8, sticky="w")

    label("Bundesland:", row=9)
    state_labels = [lbl for _, lbl in STATES]
    current_code = settings.get("state")
    current_label = next(
        (lbl for code, lbl in STATES if code == current_code),
        STATES[0][1],
    )
    state_var = tk.StringVar(value=current_label)
    dark_combo(dialog, state_var, state_labels, width=22).grid(row=9, column=1, padx=10, pady=8)

    tk.Label(
        dialog, text="— Mail-Vorlage —", font=FONT_BOLD, bg=BG, fg=TEXT_MUTED,
    ).grid(row=10, column=0, columnspan=2, padx=10, pady=(16, 4))

    label("Betreff:", row=11, pady=4)
    subject_var = tk.StringVar(value=settings.get("mail_subject"))
    dark_entry(dialog, subject_var, width=35).grid(row=11, column=1, padx=10, pady=4)

    label("Anrede:", row=12, pady=4)
    greeting_var = tk.StringVar(value=settings.get("mail_greeting"))
    dark_entry(dialog, greeting_var, width=35).grid(row=12, column=1, padx=10, pady=4)

    label("Inhalt:", row=13, pady=4, sticky="nw")
    content_text = dark_text(dialog, 35, 3)
    content_text.grid(row=13, column=1, padx=10, pady=4)
    content_text.insert("1.0", settings.get("mail_content"))

    label("Gruß:", row=14, pady=4, sticky="nw")
    closing_text = dark_text(dialog, 35, 2)
    closing_text.grid(row=14, column=1, padx=10, pady=4)
    closing_text.insert("1.0", settings.get("mail_closing"))

    tk.Label(
        dialog, text="Platzhalter: {zeitraum}, {gesamt}", font=("Segoe UI", 8),
        bg=BG, fg=TEXT_MUTED,
    ).grid(row=15, column=0, columnspan=2, padx=10, pady=(0, 4))

    show_weekend_var = tk.BooleanVar(value=settings.get("show_weekend"))
    tk.Checkbutton(
        dialog, text="Wochenende (Sa/So) im Kalender anzeigen",
        variable=show_weekend_var, font=FONT,
        bg=BG, fg=TEXT, selectcolor=CELL_BG,
        activebackground=BG, activeforeground=TEXT,
        cursor="hand2",
    ).grid(row=16, column=0, columnspan=2, padx=10, pady=(8, 0), sticky="w")

    autostart_var = tk.BooleanVar(value=settings.get("autostart"))
    tk.Checkbutton(
        dialog, text="Autostart (minimiert bei Anmeldung)",
        variable=autostart_var, font=FONT,
        bg=BG, fg=TEXT, selectcolor=CELL_BG,
        activebackground=BG, activeforeground=TEXT,
        cursor="hand2",
    ).grid(row=17, column=0, columnspan=2, padx=10, pady=(0, 8), sticky="w")

    # --- Synchronisation (Multi-Device-Sync, Phase 4.6) ---
    tk.Label(
        dialog, text="— Synchronisation —", font=FONT_BOLD,
        bg=BG, fg=TEXT_MUTED,
    ).grid(row=18, column=0, columnspan=2, padx=10, pady=(16, 4))

    var_sync = tk.BooleanVar(value=settings.get("sync_enabled"))

    # cb is assigned after creation so _on_sync_toggled and _finish_oauth can reference it
    cb_sync = None

    def _finish_oauth(err, tb):
        cb_sync.config(state="normal")
        if err is None:
            settings.set("sync_enabled", True)
            return
        messagebox.showerror(
            "Synchronisation aktivieren",
            f"OAuth-Flow fehlgeschlagen:\n\n{err}\n\n{tb}",
            parent=dialog,
        )
        var_sync.set(False)

    def _on_sync_toggled():
        new_state = var_sync.get()
        if new_state and not settings.get("sync_enabled"):
            cb_sync.config(state="disabled")

            def _do_oauth():
                err = None
                tb = ""
                try:
                    from src import drive
                    drive.get_drive_service(
                        os.path.join(base_path, "credentials.json"),
                        os.path.join(base_path, "token.json"),
                    )
                except Exception as e:
                    err = e
                    tb = traceback.format_exc()
                dialog.after(0, lambda: _finish_oauth(err, tb))

            threading.Thread(target=_do_oauth, daemon=True).start()
            return
        if not new_state and settings.get("sync_enabled"):
            settings.set("sync_enabled", False)

    cb_sync = tk.Checkbutton(
        dialog, text="Mit Google Drive synchronisieren",
        variable=var_sync, font=FONT,
        bg=BG, fg=TEXT, selectcolor=CELL_BG,
        activebackground=BG, activeforeground=TEXT,
        cursor="hand2",
        command=_on_sync_toggled,
    )
    cb_sync.grid(row=19, column=0, columnspan=2, padx=10, pady=(4, 0), sticky="w")

    device_id = settings.get("device_id") or "(noch nicht gesetzt)"
    device_id_short = device_id[:8] + "…" if len(device_id) > 8 else device_id
    tk.Label(
        dialog, text=f"Geräte-ID: {device_id_short}", font=FONT_SMALL,
        bg=BG, fg=TEXT_MUTED,
    ).grid(row=20, column=0, columnspan=2, padx=10, pady=(2, 0), sticky="w")

    last = settings.get("last_pull_at") or "noch nie"
    tk.Label(
        dialog, text=f"Letzte Synchronisation: {last}", font=FONT_SMALL,
        bg=BG, fg=TEXT_MUTED,
    ).grid(row=21, column=0, columnspan=2, padx=10, pady=(2, 4), sticky="w")

    unresolved = 0
    if conflicts_store is not None:
        unresolved = conflicts_store.count_unresolved()
    if unresolved > 0:
        def _open_conflicts_dialog():
            from src.dialogs.conflicts_dialog import ConflictsDialog
            ConflictsDialog(dialog, storage, settings, conflicts_store)

        secondary_button(
            dialog,
            f"Konflikte ansehen ({unresolved})",
            _open_conflicts_dialog,
            padx=12, pady=2,
        ).grid(row=22, column=0, columnspan=2, padx=10, pady=(0, 8), sticky="w")

    def save_settings():
        for key, lbl in zip(WEEKDAY_KEYS, DAYS_DE):
            ok, msg = validate_entry(start_vars[key].get(), end_vars[key].get())
            if not ok:
                messagebox.showerror(
                    "Standard-Arbeitszeit ungültig",
                    f"{lbl}: {msg}",
                    parent=dialog,
                )
                return

        new_autostart = autostart_var.get()
        old_autostart = settings.get("autostart")

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
                messagebox.showerror(
                    "Autostart-Fehler",
                    f"Autostart konnte nicht geändert werden:\n{e}",
                    parent=dialog,
                )
                return

        rate_str = rate_var.get().strip()
        try:
            hourly_rate = float(rate_str) if rate_str else 0.0
        except ValueError:
            hourly_rate = 0.0

        selected_label = state_var.get()
        selected_code = next(
            (code for code, lbl in STATES if lbl == selected_label),
            "",
        )

        updates = {
            "autostart": new_autostart,
            "default_pause": int(pause_var.get()),
            "recipient": recipient_var.get(),
            "name": name_var.get(),
            "mail_subject": subject_var.get(),
            "mail_greeting": greeting_var.get(),
            "mail_content": content_text.get("1.0", "end-1c"),
            "mail_closing": closing_text.get("1.0", "end-1c"),
            "hourly_rate": hourly_rate,
            "state": selected_code,
            "show_weekend": show_weekend_var.get(),
        }
        for key in WEEKDAY_KEYS:
            updates[f"default_start_{key}"] = start_vars[key].get()
            updates[f"default_end_{key}"] = end_vars[key].get()
        synced_updates = {k: v for k, v in updates.items() if k in SYNCED_SETTING_KEYS}
        plain_updates = {k: v for k, v in updates.items() if k not in SYNCED_SETTING_KEYS}
        for key, value in synced_updates.items():
            settings.set_synced(key, value)
        if plain_updates:
            settings.set_many(plain_updates)
        on_change()
        dialog.destroy()

    btn_frame = tk.Frame(dialog, bg=BG)
    btn_frame.grid(row=23, column=0, columnspan=2, pady=12)

    primary_button(btn_frame, "Speichern", save_settings).pack(side=tk.LEFT, padx=5)
    secondary_button(btn_frame, "Abbrechen", dialog.destroy).pack(side=tk.LEFT, padx=5)

    center_dialog_on_parent(dialog, parent)
