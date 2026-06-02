import datetime
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
    apply_app_icon, apply_combobox_style, apply_dark_titlebar,
    attach_unfocus_on_click,
    center_dialog_on_parent, disable_min_max,
    dark_combo, dark_entry, dark_text,
    primary_button, secondary_button,
)
from src.holidays_de import STATES
from src.settings import WEEKDAY_KEYS, SYNCED_SETTING_KEYS
from src.time_utils import DAYS_DE, validate_entry


def open_settings_dialog(parent, settings, base_path, on_change, *,
                         conflicts_store=None, storage=None,
                         reservation_store=None):
    """Modal dialog for editing app settings.

    on_change is called after a successful save so the calendar can refresh.
    conflicts_store and storage are optional; when provided, a Sync section
    with a conflicts button is shown.
    """
    dialog = tk.Toplevel(parent)
    dialog.title("Einstellungen")
    dialog.resizable(False, False)
    dialog.grab_set()
    dialog.focus_set()
    dialog.configure(bg=BG)
    apply_dark_titlebar(dialog)
    disable_min_max(dialog)
    apply_app_icon(dialog)

    apply_combobox_style(dialog)

    creds_path = os.path.join(base_path, "credentials.json")

    def label(text, row, col=0, **grid_kw):
        kw: dict[str, Any] = dict(padx=10, pady=8, sticky="w")
        kw.update(grid_kw)
        lbl = tk.Label(dialog, text=text, font=FONT, bg=BG, fg=TEXT)
        lbl.grid(row=row, column=col, **kw)
        return lbl

    def _section_header(title, row, top_pad=8):
        """Klickbarer Section-Header mit ▶/▼-Toggle. Caller hängt jedes zur
        Section gehörende Widget an `widgets` an. Beim Collapse merkt sich
        der Toggle pro Widget, ob es im Grid lag — damit eine eingeklappt-
        gestartete Sub-Section (z.B. Standardzeiten) beim Re-Expand nicht
        versehentlich aufgeht.

        Wir nutzen `winfo_manager()` statt `winfo_ismapped()`, weil letzteres
        vor dem ersten Window-Mapping False liefert — beim initialen Toggle
        (Default-Einklappen vor dem Anzeigen des Dialogs) würden sonst alle
        Widgets als 'nicht sichtbar' eingestuft, kein grid_remove() ausgeführt,
        und der User müsste zweimal klicken bis der Header-Text und der
        Inhalt sync sind. `winfo_manager()` ist mapping-unabhängig."""
        state = {"collapsed": False}
        header = tk.Label(
            dialog, text=f"— {title} — ▼", font=FONT_BOLD,
            bg=BG, fg=TEXT_MUTED, cursor="hand2",
        )
        header.grid(row=row, column=0, columnspan=2, padx=10, pady=(top_pad, 4))
        widgets: list[tk.Widget] = []

        def toggle(_event=None):
            if state["collapsed"]:
                for w in widgets:
                    if getattr(w, "_was_in_grid", True):
                        w.grid()
                header.config(text=f"— {title} — ▼")
                state["collapsed"] = False
            else:
                for w in widgets:
                    w._was_in_grid = (w.winfo_manager() == "grid")
                    if w._was_in_grid:
                        w.grid_remove()
                header.config(text=f"— {title} — ▶")
                state["collapsed"] = True

        header.bind("<Button-1>", toggle)
        return header, widgets, toggle

    gmail_header, gmail_widgets, gmail_toggle = _section_header(
        "Gmail-Zugangsdaten", row=0)

    gmail_widgets.append(label("Datenordner:", row=1, pady=4))

    creds_row = tk.Frame(dialog, bg=BG)
    creds_row.grid(row=1, column=1, padx=10, pady=4, sticky="w")
    gmail_widgets.append(creds_row)

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

    # Absender-Zeile: zeigt die authentifizierte E-Mail-Adresse, die ui.py
    # im Hintergrund über OAuth2-userinfo abruft und in settings cached.
    gmail_widgets.append(label("Absender:", row=2, pady=(0, 4)))
    sender_row = tk.Frame(dialog, bg=BG)
    sender_row.grid(row=2, column=1, padx=10, pady=(0, 4), sticky="w")
    gmail_widgets.append(sender_row)
    sender_label = tk.Label(
        sender_row,
        text=settings.get("sender_email") or "(noch nicht ermittelt)",
        font=FONT, bg=BG, fg=TEXT_MUTED,
    )
    sender_label.pack(side=tk.LEFT)

    def _set_sender_btn_text(text):
        # secondary_button ist ein Frame+Label-Konstrukt (kein tk.Button),
        # der Text liegt am inneren `_label`. Kein -state-Option — wir
        # markieren den laufenden Zustand nur über den Text.
        if hasattr(sender_btn, "_label"):
            sender_btn._label.config(text=text)

    def _refresh_sender():
        """OAuth-Flow + userinfo-Fetch im Thread, danach Label aktualisieren."""
        from src.mail import fetch_user_email, get_gmail_service

        _set_sender_btn_text("Verbinde…")

        def _do():
            try:
                # OAuth-Flow läuft, falls Token fehlt oder Scopes upgegradet werden müssen.
                get_gmail_service(
                    os.path.join(base_path, "credentials.json"),
                    os.path.join(base_path, "token.json"),
                    sync_enabled=settings.get("sync_enabled"),
                    gcal_enabled=settings.get("gcal_enabled"),
                )
                email = fetch_user_email(
                    os.path.join(base_path, "token.json"),
                    sync_enabled=settings.get("sync_enabled"),
                    gcal_enabled=settings.get("gcal_enabled"),
                )
            except Exception as e:
                err = e
                tb = traceback.format_exc()
                dialog.after(0, lambda: _finish_refresh_error(err, tb))
                return
            dialog.after(0, lambda: _finish_refresh_ok(email))

        threading.Thread(target=_do, daemon=True).start()

    def _finish_refresh_ok(email):
        if not sender_label.winfo_exists():
            return
        _set_sender_btn_text("Aktualisieren")
        if email:
            settings.set("sender_email", email)
            sender_label.config(text=email)
        else:
            sender_label.config(text="(nicht verfügbar — Scope fehlt evtl.)")

    def _finish_refresh_error(err, tb):
        if not sender_label.winfo_exists():
            return
        _set_sender_btn_text("Aktualisieren")
        messagebox.showerror(
            "Anmeldung fehlgeschlagen",
            f"OAuth-Flow oder Userinfo-Aufruf fehlgeschlagen:\n\n{err}\n\n{tb}",
            parent=dialog,
        )

    sender_btn = secondary_button(
        sender_row,
        "Aktualisieren" if settings.get("sender_email") else "Anmelden",
        _refresh_sender,
        padx=12, pady=2,
    )
    sender_btn.pack(side=tk.LEFT, padx=(10, 0))

    times_label = tk.Label(
        dialog, text="Standardzeiten: ▶", font=FONT, bg=BG, fg=TEXT,
        cursor="hand2",
    )
    times_label.grid(row=3, column=0, padx=10, pady=8, sticky="w")
    gmail_widgets.append(times_label)

    times_frame = tk.Frame(dialog, bg=BG)
    times_frame.grid(row=3, column=1, rowspan=2, padx=10, pady=4, sticky="w")
    times_frame.grid_remove()  # default eingeklappt — User klappt bei Bedarf auf
    gmail_widgets.append(times_frame)

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
    gmail_widgets.append(label("Standard-Pause (Min):", row=5))
    pause_var = tk.StringVar(value=str(settings.get("default_pause")))
    pause_combo = dark_combo(dialog, pause_var, PAUSE_VALUES)
    pause_combo.grid(row=5, column=1, padx=10, pady=8)
    gmail_widgets.append(pause_combo)

    gmail_widgets.append(label("Empfänger:", row=6))
    recipient_var = tk.StringVar(value=settings.get("recipient"))
    recipient_entry = dark_entry(dialog, recipient_var, width=25)
    recipient_entry.grid(row=6, column=1, padx=10, pady=8)
    gmail_widgets.append(recipient_entry)

    gmail_widgets.append(label("Name:", row=8))
    name_var = tk.StringVar(value=settings.get("name"))
    name_entry = dark_entry(dialog, name_var, width=25)
    name_entry.grid(row=8, column=1, padx=10, pady=8)
    gmail_widgets.append(name_entry)

    gmail_widgets.append(label("Stundenlohn (€):", row=9))
    rate_var = tk.StringVar(value=str(settings.get("hourly_rate") or ""))
    rate_entry = dark_entry(dialog, rate_var, width=10)
    rate_entry.grid(row=9, column=1, padx=10, pady=8, sticky="w")
    gmail_widgets.append(rate_entry)

    rate_hint = tk.Label(
        dialog, text="(optional – nur für dich sichtbar)", font=FONT_SMALL,
        bg=BG, fg=TEXT_MUTED,
    )
    rate_hint.grid(row=9, column=1, padx=(120, 10), pady=8, sticky="w")
    gmail_widgets.append(rate_hint)

    gmail_widgets.append(label("Bundesland:", row=10))
    state_labels = [lbl for _, lbl in STATES]
    current_code = settings.get("state")
    current_label = next(
        (lbl for code, lbl in STATES if code == current_code),
        STATES[0][1],
    )
    state_var = tk.StringVar(value=current_label)
    state_combo = dark_combo(dialog, state_var, state_labels, width=22)
    state_combo.grid(row=10, column=1, padx=10, pady=8)
    gmail_widgets.append(state_combo)

    mv_header, mv_widgets, mv_toggle = _section_header(
        "Mail-Vorlage", row=11, top_pad=16)

    mv_widgets.append(label("Betreff:", row=12, pady=4))
    subject_var = tk.StringVar(value=settings.get("mail_subject"))
    subject_entry = dark_entry(dialog, subject_var, width=35)
    subject_entry.grid(row=12, column=1, padx=10, pady=4)
    mv_widgets.append(subject_entry)

    mv_widgets.append(label("Anrede:", row=13, pady=4))
    greeting_var = tk.StringVar(value=settings.get("mail_greeting"))
    greeting_entry = dark_entry(dialog, greeting_var, width=35)
    greeting_entry.grid(row=13, column=1, padx=10, pady=4)
    mv_widgets.append(greeting_entry)

    mv_widgets.append(label("Inhalt:", row=14, pady=4, sticky="nw"))
    content_text = dark_text(dialog, 35, 3)
    content_text.grid(row=14, column=1, padx=10, pady=4)
    content_text.insert("1.0", settings.get("mail_content"))
    mv_widgets.append(content_text)

    mv_widgets.append(label("Gruß:", row=15, pady=4, sticky="nw"))
    closing_text = dark_text(dialog, 35, 2)
    closing_text.grid(row=15, column=1, padx=10, pady=4)
    closing_text.insert("1.0", settings.get("mail_closing"))
    mv_widgets.append(closing_text)

    placeholder_hint = tk.Label(
        dialog, text="Platzhalter: {zeitraum}, {gesamt}", font=("Segoe UI", 8),
        bg=BG, fg=TEXT_MUTED,
    )
    placeholder_hint.grid(row=16, column=0, columnspan=2, padx=10, pady=(0, 4))
    mv_widgets.append(placeholder_hint)

    show_weekend_var = tk.BooleanVar(value=settings.get("show_weekend"))
    tk.Checkbutton(
        dialog, text="Wochenende (Sa/So) im Kalender anzeigen",
        variable=show_weekend_var, font=FONT,
        bg=BG, fg=TEXT, selectcolor=CELL_BG,
        activebackground=BG, activeforeground=TEXT,
        cursor="hand2",
    ).grid(row=17, column=0, columnspan=2, padx=10, pady=(8, 0), sticky="w")

    autostart_var = tk.BooleanVar(value=settings.get("autostart"))
    tk.Checkbutton(
        dialog, text="Autostart (minimiert bei Anmeldung)",
        variable=autostart_var, font=FONT,
        bg=BG, fg=TEXT, selectcolor=CELL_BG,
        activebackground=BG, activeforeground=TEXT,
        cursor="hand2",
    ).grid(row=18, column=0, columnspan=2, padx=10, pady=(0, 0), sticky="w")

    always_on_top_var = tk.BooleanVar(value=settings.get("always_on_top"))
    tk.Checkbutton(
        dialog, text="Immer im Vordergrund",
        variable=always_on_top_var, font=FONT,
        bg=BG, fg=TEXT, selectcolor=CELL_BG,
        activebackground=BG, activeforeground=TEXT,
        cursor="hand2",
    ).grid(row=19, column=0, columnspan=2, padx=10, pady=(0, 0), sticky="w")

    minimize_to_tray_var = tk.BooleanVar(value=settings.get("minimize_to_tray"))
    tk.Checkbutton(
        dialog, text="Beim Schließen in den Infobereich minimieren",
        variable=minimize_to_tray_var, font=FONT,
        bg=BG, fg=TEXT, selectcolor=CELL_BG,
        activebackground=BG, activeforeground=TEXT,
        cursor="hand2",
    ).grid(row=20, column=0, columnspan=2, padx=10, pady=(0, 8), sticky="w")

    # --- Synchronisation (Multi-Device-Sync, Phase 4.6) ---
    tk.Label(
        dialog, text="— Synchronisation —", font=FONT_BOLD,
        bg=BG, fg=TEXT_MUTED,
    ).grid(row=21, column=0, columnspan=2, padx=10, pady=(16, 4))

    var_sync = tk.BooleanVar(value=settings.get("sync_enabled"))

    # Forward-Deklaration: die Closures unten referenzieren cb_sync, das erst
    # weiter unten als Checkbutton erzeugt wird. Beim ersten Aufruf der
    # Closures (User-Interaktion) ist cb_sync garantiert gesetzt — das assert
    # narrowt den Typ für Pylance.
    cb_sync: tk.Checkbutton | None = None

    def _finish_oauth(err, tb):
        assert cb_sync is not None
        cb_sync.config(state="normal")
        if err is None:
            settings.set("sync_enabled", True)
            on_change()
            return
        messagebox.showerror(
            "Synchronisation aktivieren",
            f"OAuth-Flow fehlgeschlagen:\n\n{err}\n\n{tb}",
            parent=dialog,
        )
        var_sync.set(False)

    def _on_sync_toggled():
        assert cb_sync is not None
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
                        gcal_enabled=settings.get("gcal_enabled"),
                    )
                except Exception as e:
                    err = e
                    tb = traceback.format_exc()
                dialog.after(0, lambda: _finish_oauth(err, tb))

            threading.Thread(target=_do_oauth, daemon=True).start()
            return
        if not new_state and settings.get("sync_enabled"):
            settings.set("sync_enabled", False)
            on_change()

    cb_sync = tk.Checkbutton(
        dialog, text="Mit Google Drive synchronisieren",
        variable=var_sync, font=FONT,
        bg=BG, fg=TEXT, selectcolor=CELL_BG,
        activebackground=BG, activeforeground=TEXT,
        cursor="hand2",
        command=_on_sync_toggled,
    )
    cb_sync.grid(row=22, column=0, columnspan=2, padx=10, pady=(4, 0), sticky="w")

    device_id = settings.get("device_id") or "(noch nicht gesetzt)"
    device_id_short = device_id[:8] + "…" if len(device_id) > 8 else device_id
    tk.Label(
        dialog, text=f"Geräte-ID: {device_id_short}", font=FONT_SMALL,
        bg=BG, fg=TEXT_MUTED,
    ).grid(row=23, column=0, columnspan=2, padx=10, pady=(2, 0), sticky="w")

    last_raw = settings.get("last_pull_at")
    if last_raw and len(last_raw) >= 10:
        try:
            last = datetime.date.fromisoformat(last_raw[:10]).strftime("%d.%m.%Y")
        except ValueError:
            last = last_raw[:10]
    else:
        last = "noch nie"
    tk.Label(
        dialog, text=f"Letzte Synchronisation: {last}", font=FONT_SMALL,
        bg=BG, fg=TEXT_MUTED,
    ).grid(row=24, column=0, columnspan=2, padx=10, pady=(2, 4), sticky="w")

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
        ).grid(row=25, column=0, columnspan=2, padx=10, pady=(0, 8), sticky="w")

    def _open_import_dialog():
        from src.dialogs.import_dialog import open_import_dialog

        def _after_import():
            on_change()
            dialog.destroy()

        open_import_dialog(
            dialog, storage, settings, _after_import,
            reservation_store=reservation_store,
        )

    if storage is not None:
        secondary_button(
            dialog,
            "Daten importieren…",
            _open_import_dialog,
            padx=12, pady=2,
        ).grid(row=26, column=0, columnspan=2, padx=10, pady=(4, 8), sticky="w")

    # --- Google Kalender (Reservierungen) ---
    tk.Label(
        dialog, text="— Google Kalender —", font=FONT_BOLD,
        bg=BG, fg=TEXT_MUTED,
    ).grid(row=27, column=0, columnspan=2, padx=10, pady=(16, 4))

    var_gcal = tk.BooleanVar(value=settings.get("gcal_enabled"))
    cb_gcal: tk.Checkbutton | None = None

    # Kalender-Auswahl: Combobox zeigt Klarnamen, gespeichert wird die ID.
    # cal_map summary->id wird im Hintergrund per API befüllt.
    cal_map: dict[str, str] = {}
    cal_var = tk.StringVar(value=settings.get("gcal_calendar_id") or "primary")

    cal_combo = dark_combo(dialog, cal_var, [cal_var.get()], width=30)
    cal_combo.grid(row=29, column=1, padx=10, pady=4, sticky="w")
    tk.Label(dialog, text="Kalender:", font=FONT, bg=BG, fg=TEXT).grid(
        row=29, column=0, padx=10, pady=4, sticky="w")

    cal_status = tk.Label(dialog, text="", font=FONT_SMALL, bg=BG, fg=TEXT_MUTED)
    cal_status.grid(row=30, column=0, columnspan=2, padx=10, pady=(0, 4), sticky="w")

    def _populate_calendars(items):
        if not cal_combo.winfo_exists():
            return
        cal_map.clear()
        for it in items:
            cal_map[it["summary"]] = it["id"]
        cal_combo["values"] = list(cal_map.keys()) or [cal_var.get()]
        # Gespeicherte ID auf den passenden Klarnamen zurückmappen.
        stored_id = settings.get("gcal_calendar_id") or "primary"
        for summary, cid in cal_map.items():
            if cid == stored_id:
                cal_var.set(summary)
                break
        cal_status.config(text="")

    def _load_calendars():
        cal_status.config(text="Kalenderliste wird geladen…")

        def _do():
            try:
                from src import gcal
                service = gcal.get_calendar_service(
                    os.path.join(base_path, "credentials.json"),
                    os.path.join(base_path, "token.json"),
                    sync_enabled=settings.get("sync_enabled"),
                )
                items = gcal.list_calendars(service)
            except Exception as e:
                tb = traceback.format_exc()
                # e/tb als Default-Argumente binden: das Lambda läuft via
                # dialog.after() VERZÖGERT — bis dahin hat Python die
                # except-Variable `e` am Blockende gelöscht (impliziter del),
                # ein freier Zugriff gäbe NameError.
                dialog.after(
                    0, lambda e=e, tb=tb: _load_calendars_error(e, tb))
                return
            dialog.after(0, lambda: _populate_calendars(items))

        threading.Thread(target=_do, daemon=True).start()

    def _load_calendars_error(err, tb):
        if cal_status.winfo_exists():
            cal_status.config(text="Kalenderliste nicht verfügbar")
        messagebox.showerror(
            "Google Kalender",
            f"Kalenderliste konnte nicht geladen werden:\n\n{err}\n\n{tb}",
            parent=dialog,
        )

    def _finish_gcal_oauth(err, tb):
        assert cb_gcal is not None
        if not cb_gcal.winfo_exists():
            return  # Dialog wurde während des OAuth-Flows geschlossen.
        cb_gcal.config(state="normal")
        if err is None:
            settings.set("gcal_enabled", True)
            on_change()
            _load_calendars()
            return
        messagebox.showerror(
            "Google Kalender aktivieren",
            f"OAuth-Flow fehlgeschlagen:\n\n{err}\n\n{tb}",
            parent=dialog,
        )
        var_gcal.set(False)

    def _on_gcal_toggled():
        assert cb_gcal is not None
        new_state = var_gcal.get()
        if new_state and not settings.get("gcal_enabled"):
            cb_gcal.config(state="disabled")

            def _do_oauth():
                err, tb = None, ""
                try:
                    from src import gcal
                    gcal.get_calendar_service(
                        os.path.join(base_path, "credentials.json"),
                        os.path.join(base_path, "token.json"),
                        sync_enabled=settings.get("sync_enabled"),
                    )
                except Exception as e:
                    err, tb = e, traceback.format_exc()
                dialog.after(0, lambda: _finish_gcal_oauth(err, tb))

            threading.Thread(target=_do_oauth, daemon=True).start()
            return
        if not new_state and settings.get("gcal_enabled"):
            settings.set("gcal_enabled", False)
            on_change()

    cb_gcal = tk.Checkbutton(
        dialog, text="Reservierungen mit Google Kalender abgleichen",
        variable=var_gcal, font=FONT,
        bg=BG, fg=TEXT, selectcolor=CELL_BG,
        activebackground=BG, activeforeground=TEXT,
        cursor="hand2", command=_on_gcal_toggled,
    )
    cb_gcal.grid(row=28, column=0, columnspan=2, padx=10, pady=(4, 0), sticky="w")

    if settings.get("gcal_enabled"):
        _load_calendars()

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
            "always_on_top": always_on_top_var.get(),
            "minimize_to_tray": minimize_to_tray_var.get(),
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
        # Kalender-Auswahl: Klarname zurück auf ID mappen, als Sync-Setting
        # speichern (reist über die Drive-Settings-Sync mit). Nur wenn die
        # Kalenderliste schon geladen ist (cal_map gefüllt) — sonst würde ein
        # vorschnelles "Speichern" fälschlich "primary" festschreiben.
        if settings.get("gcal_enabled") and cal_map:
            selected_cal_id = cal_map.get(
                cal_var.get(), settings.get("gcal_calendar_id") or "primary")
            if selected_cal_id != settings.get("gcal_calendar_id"):
                settings.set_synced("gcal_calendar_id", selected_cal_id)
        on_change()
        dialog.destroy()

    btn_frame = tk.Frame(dialog, bg=BG)
    btn_frame.grid(row=31, column=0, columnspan=2, pady=12)

    primary_button(btn_frame, "Speichern", save_settings).pack(side=tk.LEFT, padx=5)
    secondary_button(btn_frame, "Abbrechen", dialog.destroy).pack(side=tk.LEFT, padx=5)

    attach_unfocus_on_click(dialog)
    dialog.bind("<Escape>", lambda _e: dialog.destroy())
    # Mail-Vorlage default eingeklappt — spart Höhe, der Block wird selten
    # geändert. Funktioniert vor dem Mapping, weil der Toggle-Helper
    # winfo_manager() (mapping-unabhängig) statt winfo_ismapped() nutzt.
    mv_toggle()
    center_dialog_on_parent(dialog, parent)
