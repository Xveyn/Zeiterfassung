import datetime
import logging
import os
import tkinter as tk
import traceback
from tkinter import messagebox, ttk

from src.autostart import disable_autostart, enable_autostart, is_autostart_enabled, resolve_autostart_target
from src.platform_open import open_folder
from src.theme import (
    ACCENT, BG, CELL_BG, FONT, FONT_BOLD, FONT_SMALL,
    STATUS_OK, TEXT, TEXT_MUTED,
    apply_combobox_style, apply_notebook_style, attach_unfocus_on_click,
    center_dialog_on_parent, create_dialog,
    dark_combo, dark_entry, dark_text,
    primary_button, secondary_button,
    themed_askyesno, themed_showinfo, themed_showwarning, themed_showerror,
)
from src.holidays_de import STATES, code_for_state_label
from src.settings import (
    WEEKDAY_KEYS, clamp_ui_scale, parse_hourly_rate,
    parse_reminder_minutes, resolve_calendar_id,
)
from src.time_utils import format_iso_date, validate_period
from src.time_utils import DAYS_DE, validate_entry
from src.weekly_limit import format_limit_warnings, period_scan_needed, scan_period_for_warnings
from src.dialogs.settings_dialog._shared import label, subheader
from src.dialogs.settings_dialog.oauth_task import build_oauth_enable_task
from src.dialogs.settings_dialog.tab_work import WorkTab


def open_settings_dialog(parent, settings, base_path, on_change, *,
                         runner, conflicts_store=None, storage=None,
                         reservation_store=None, on_request_restart=None,
                         data_lock=None, sync_guard=None):
    """Modaler Dialog zum Bearbeiten der App-Einstellungen, aufgeteilt auf vier
    Tabs (Arbeitszeit / Bericht & Mail / Google / App).

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

    creds_path = os.path.join(base_path, "credentials.json")

    notebook = ttk.Notebook(dialog, style="Dark.TNotebook")
    notebook.pack(fill="both", expand=True, padx=8, pady=(8, 0))

    tab_work = tk.Frame(notebook, bg=BG)
    tab_mail = tk.Frame(notebook, bg=BG)
    tab_google = tk.Frame(notebook, bg=BG)
    tab_app = tk.Frame(notebook, bg=BG)
    notebook.add(tab_work, text="Arbeitszeit")
    notebook.add(tab_mail, text="Bericht & Mail")
    notebook.add(tab_google, text="Google")
    notebook.add(tab_app, text="App")

    # ===================== Tab: Arbeitszeit =====================
    work = WorkTab(tab_work, dialog, settings)

    # ===================== Tab: Bericht & Mail =====================
    label(tab_mail, "Empfänger:", row=0, pady=(10, 8))
    recipient_var = tk.StringVar(value=settings.get("recipient"))
    dark_entry(tab_mail, recipient_var, width=25).grid(row=0, column=1, padx=10, pady=(10, 8))

    label(tab_mail, "Name:", row=1)
    name_var = tk.StringVar(value=settings.get("name"))
    dark_entry(tab_mail, name_var, width=25).grid(row=1, column=1, padx=10, pady=8)

    label(tab_mail, "Stundenlohn (€):", row=2)
    rate_var = tk.StringVar(value=str(settings.get("hourly_rate") or ""))
    dark_entry(tab_mail, rate_var, width=10).grid(row=2, column=1, padx=10, pady=8, sticky="w")
    tk.Label(
        tab_mail, text="(optional – nur für dich sichtbar)", font=FONT_SMALL,
        bg=BG, fg=TEXT_MUTED,
    ).grid(row=2, column=1, padx=(120, 10), pady=8, sticky="w")

    subheader(tab_mail, "Mail-Vorlage", row=3)

    label(tab_mail, "Betreff:", row=4, pady=4)
    subject_var = tk.StringVar(value=settings.get("mail_subject"))
    dark_entry(tab_mail, subject_var, width=35).grid(row=4, column=1, padx=10, pady=4)

    label(tab_mail, "Anrede:", row=5, pady=4)
    greeting_var = tk.StringVar(value=settings.get("mail_greeting"))
    dark_entry(tab_mail, greeting_var, width=35).grid(row=5, column=1, padx=10, pady=4)

    label(tab_mail, "Inhalt:", row=6, pady=4, sticky="nw")
    content_text = dark_text(tab_mail, 35, 3)
    content_text.grid(row=6, column=1, padx=10, pady=4)
    content_text.insert("1.0", settings.get("mail_content"))

    label(tab_mail, "Gruß:", row=7, pady=4, sticky="nw")
    closing_text = dark_text(tab_mail, 35, 2)
    closing_text.grid(row=7, column=1, padx=10, pady=4)
    closing_text.insert("1.0", settings.get("mail_closing"))

    tk.Label(
        tab_mail, text="Platzhalter: {zeitraum}, {gesamt}", font=("Segoe UI", 8),
        bg=BG, fg=TEXT_MUTED,
    ).grid(row=8, column=0, columnspan=2, padx=10, pady=(0, 8))

    # ===================== Tab: Google =====================
    subheader(tab_google, "Google-Konto", row=0, top_pad=10)

    label(tab_google, "Datenordner:", row=1, pady=4)
    creds_row = tk.Frame(tab_google, bg=BG)
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

    # Absender-Zeile: zeigt die authentifizierte E-Mail-Adresse, die ui.py
    # im Hintergrund über OAuth2-userinfo abruft und in settings cached.
    label(tab_google, "Absender:", row=2, pady=(0, 4))
    sender_row = tk.Frame(tab_google, bg=BG)
    sender_row.grid(row=2, column=1, padx=10, pady=(0, 4), sticky="w")
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
        from src.dialogs.send_dialog import show_missing_credentials_dialog

        if not os.path.exists(creds_path):
            # Konsistent mit Senden/Teilen: freundlicher Hinweis + „Datenordner
            # öffnen" statt OAuth-Traceback bei fehlender credentials.json.
            show_missing_credentials_dialog(dialog, base_path)
            return

        _set_sender_btn_text("Verbinde…")

        def _fn():
            from src.mail import fetch_user_email, get_gmail_service
            try:
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
                return {"ok": False, "error": e, "tb": traceback.format_exc()}
            if email:
                settings.set("sender_email", email)   # Cache überlebt Close
            return {"ok": True, "email": email}

        def _on_done(res):
            if not sender_label.winfo_exists():
                return
            _set_sender_btn_text("Aktualisieren")
            if not res["ok"]:
                messagebox.showerror(
                    "Anmeldung fehlgeschlagen",
                    "OAuth-Flow oder Userinfo-Aufruf fehlgeschlagen:\n\n"
                    f"{res['error']}\n\n{res['tb']}",
                    parent=dialog,
                )
                return
            email = res["email"]
            sender_label.config(
                text=email if email
                else "(nicht verfügbar — Scope fehlt evtl.)")

        runner.run(_fn, _on_done)

    sender_btn = secondary_button(
        sender_row,
        "Aktualisieren" if settings.get("sender_email") else "Anmelden",
        _refresh_sender,
        padx=12, pady=2,
    )
    sender_btn.pack(side=tk.LEFT, padx=(10, 0))

    subheader(tab_google, "Synchronisation", row=3)
    tk.Label(
        tab_google, text="Diese Schalter wirken sofort (Anmeldung im Browser).",
        font=FONT_SMALL, bg=BG, fg=TEXT_MUTED,
    ).grid(row=4, column=0, columnspan=2, padx=10, pady=(0, 4), sticky="w")

    var_sync = tk.BooleanVar(value=settings.get("sync_enabled"))

    # Forward-Deklaration: die Closures unten referenzieren cb_sync, das erst
    # weiter unten als Checkbutton erzeugt wird. Beim ersten Aufruf der
    # Closures (User-Interaktion) ist cb_sync garantiert gesetzt — das assert
    # narrowt den Typ für Pylance.
    cb_sync: tk.Checkbutton | None = None

    def _on_sync_toggled():
        assert cb_sync is not None
        new_state = var_sync.get()
        if new_state and not settings.get("sync_enabled"):
            cb_sync.config(state="disabled")

            def _service():
                from src import drive
                drive.get_drive_service(
                    os.path.join(base_path, "credentials.json"),
                    os.path.join(base_path, "token.json"),
                    gcal_enabled=settings.get("gcal_enabled"),
                )

            fn, on_done = build_oauth_enable_task(
                service_fn=_service, settings=settings,
                setting_key="sync_enabled", checkbox=cb_sync,
                toggle_var=var_sync, on_change=on_change, dialog=dialog,
                error_title="Synchronisation aktivieren",
            )
            runner.run(fn, on_done)
            return
        if not new_state and settings.get("sync_enabled"):
            settings.set("sync_enabled", False)
            on_change()

    cb_sync = tk.Checkbutton(
        tab_google, text="Mit Google Drive synchronisieren",
        variable=var_sync, font=FONT,
        bg=BG, fg=TEXT, selectcolor=CELL_BG,
        activebackground=BG, activeforeground=TEXT,
        cursor="hand2",
        command=_on_sync_toggled,
    )
    cb_sync.grid(row=5, column=0, columnspan=2, padx=10, pady=(4, 0), sticky="w")

    device_id = settings.get("device_id") or "(noch nicht gesetzt)"
    device_id_short = device_id[:8] + "…" if len(device_id) > 8 else device_id
    tk.Label(
        tab_google, text=f"Geräte-ID: {device_id_short}", font=FONT_SMALL,
        bg=BG, fg=TEXT_MUTED,
    ).grid(row=6, column=0, columnspan=2, padx=10, pady=(2, 0), sticky="w")

    last = format_iso_date(settings.get("last_pull_at"), fallback="noch nie")
    tk.Label(
        tab_google, text=f"Letzte Synchronisation: {last}", font=FONT_SMALL,
        bg=BG, fg=TEXT_MUTED,
    ).grid(row=7, column=0, columnspan=2, padx=10, pady=(2, 4), sticky="w")

    # Ab hier wachsen im Google-Tab optionale Zeilen (Konflikte, Kompaktieren)
    # dynamisch — deshalb eine laufende Row-Nummer statt fixer Konstanten.
    next_google_row = 8
    unresolved = 0
    if conflicts_store is not None:
        unresolved = conflicts_store.count_unresolved()
    if unresolved > 0:
        def _open_conflicts_dialog():
            from src.dialogs.conflicts_dialog import ConflictsDialog
            # data_lock durchgereicht bis zu sync.resolve_conflict
            # (Review-Finding: RMW-Spanne muss atomar gegen Hintergrund-Sync sein).
            ConflictsDialog(dialog, storage, settings, conflicts_store, data_lock=data_lock)

        secondary_button(
            tab_google,
            f"Konflikte ansehen ({unresolved})",
            _open_conflicts_dialog,
            padx=12, pady=2,
        ).grid(row=next_google_row, column=0, columnspan=2, padx=10, pady=(0, 8), sticky="w")
        next_google_row += 1

    def _open_import_dialog():
        from src.dialogs.import_dialog import open_import_dialog

        def _after_import():
            on_change()
            dialog.destroy()

        open_import_dialog(
            dialog, storage, settings, _after_import,
            reservation_store=reservation_store,
        )

    btn_row = tk.Frame(tab_google, bg=BG)
    btn_row.grid(row=next_google_row, column=0, columnspan=2, padx=10, pady=(4, 8), sticky="w")
    next_google_row += 1

    # label_button liefert einen tk.Frame (keine -state-Option) — Doppelklick-
    # Schutz daher über ein Flag statt cb.config(state=...).
    reconnect_busy = {"value": False}

    def _reconnect_google():
        if reconnect_busy["value"]:
            return
        if not themed_askyesno(
            dialog, "Google neu verbinden",
            "Die App fragt die Google-Berechtigungen neu ab. Dazu öffnet sich "
            "ein Browser-Fenster zur Anmeldung — bitte dort die Freigabe "
            "bestätigen.\n\nFortfahren?",
        ):
            return
        reconnect_busy["value"] = True

        def _fn():
            from src import drive
            try:
                drive.reconnect(
                    os.path.join(base_path, "credentials.json"),
                    os.path.join(base_path, "token.json"),
                    gcal_enabled=settings.get("gcal_enabled"),
                )
            except Exception as e:
                return {"ok": False, "error": e, "tb": traceback.format_exc()}
            return {"ok": True}

        def _on_done(res):
            reconnect_busy["value"] = False
            if not dialog.winfo_exists():
                return
            if res["ok"]:
                themed_showinfo(
                    dialog, "Google neu verbunden",
                    "Die Google-Berechtigungen wurden erneuert. Die "
                    "Synchronisation sollte jetzt wieder funktionieren.",
                )
                return
            messagebox.showerror(
                "Google neu verbinden",
                "Die Neuverbindung ist fehlgeschlagen:\n\n"
                f"{res['error']}\n\n{res['tb']}",
                parent=dialog,
            )

        runner.run(_fn, _on_done)

    reconnect_btn = secondary_button(
        btn_row, "Google neu verbinden", _reconnect_google, padx=12, pady=2)
    reconnect_btn.pack(side=tk.LEFT)

    if storage is not None:
        secondary_button(
            btn_row, "Daten importieren", _open_import_dialog, padx=12, pady=2,
        ).pack(side=tk.LEFT, padx=(8, 0))

    if settings.get("sync_enabled") and storage is not None and conflicts_store is not None:
        def _on_compact_clicked():
            confirmed = themed_askyesno(
                dialog,
                "Sync-Daten kompaktieren",
                "Entfernt alte gelöschte Einträge endgültig aus dem Sync.\n\n"
                "Nur ausführen, wenn ALLE deine Geräte auf der aktuellen Version "
                "sind und kürzlich synchronisiert haben.\n\nFortfahren?",
            )
            if not confirmed:
                return

            def _show(res):
                if not dialog.winfo_exists():
                    return
                if res.get("skipped"):
                    themed_showinfo(
                        dialog,
                        "Kompaktierung",
                        "Eine Synchronisation läuft gerade — bitte kurz "
                        "warten und erneut versuchen.",
                    )
                    return
                if res.get("reason") == "old_version":
                    themed_showwarning(
                        dialog,
                        "Kompaktierung abgebrochen",
                        "Ein Gerät nutzt noch eine ältere Version — bitte erst "
                        "alle Geräte aktualisieren und synchronisieren.",
                    )
                elif res.get("reason") == "newer_version":
                    from src.sync import NEWER_REMOTE_VERSION_MSG
                    themed_showwarning(
                        dialog, "Update erforderlich", NEWER_REMOTE_VERSION_MSG,
                    )
                elif not res.get("ok"):
                    detail = f"{res.get('error', '?')}\n\n{res.get('tb', '')}"
                    themed_showerror(
                        dialog,
                        "Kompaktierung fehlgeschlagen",
                        f"Die Kompaktierung ist fehlgeschlagen:\n\n{detail}",
                    )
                else:
                    themed_showinfo(
                        dialog,
                        "Kompaktierung", "Sync-Daten wurden kompaktiert.",
                    )

            def _fn():
                from src.main import _run_compaction_blocking
                return _run_compaction_blocking(
                    storage, settings, conflicts_store, base_path,
                    data_lock=data_lock, sync_guard=sync_guard)

            runner.run(_fn, _show)

        secondary_button(
            tab_google, "Sync-Daten kompaktieren", _on_compact_clicked,
            padx=12, pady=2,
        ).grid(row=next_google_row, column=0, columnspan=2, padx=10, pady=(0, 8), sticky="w")
        next_google_row += 1

    subheader(tab_google, "Google Kalender", row=next_google_row)
    next_google_row += 1

    var_gcal = tk.BooleanVar(value=settings.get("gcal_enabled"))
    cb_gcal: tk.Checkbutton | None = None

    # Kalender-Auswahl: Combobox zeigt Klarnamen, gespeichert wird die ID.
    # cal_map summary->id wird im Hintergrund per API befüllt.
    cal_map: dict[str, str] = {}
    cal_var = tk.StringVar(value=settings.get("gcal_calendar_id") or "primary")

    gcal_check_row = next_google_row
    cal_label_row = next_google_row + 1
    cal_status_row = next_google_row + 2

    cb_gcal = tk.Checkbutton(
        tab_google, text="Reservierungen mit Google Kalender abgleichen",
        variable=var_gcal, font=FONT,
        bg=BG, fg=TEXT, selectcolor=CELL_BG,
        activebackground=BG, activeforeground=TEXT,
        cursor="hand2",
    )
    cb_gcal.grid(row=gcal_check_row, column=0, columnspan=2, padx=10, pady=(4, 0), sticky="w")

    tk.Label(tab_google, text="Kalender:", font=FONT, bg=BG, fg=TEXT).grid(
        row=cal_label_row, column=0, padx=10, pady=4, sticky="w")
    cal_combo = dark_combo(tab_google, cal_var, [cal_var.get()], width=30)
    cal_combo.grid(row=cal_label_row, column=1, padx=10, pady=4, sticky="w")

    cal_status = tk.Label(tab_google, text="", font=FONT_SMALL, bg=BG, fg=TEXT_MUTED)
    cal_status.grid(row=cal_status_row, column=0, columnspan=2, padx=10, pady=(0, 4), sticky="w")

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

        def _fn():
            from src import gcal
            try:
                service = gcal.get_calendar_service(
                    os.path.join(base_path, "credentials.json"),
                    os.path.join(base_path, "token.json"),
                    sync_enabled=settings.get("sync_enabled"),
                )
                items = gcal.list_calendars(service)
            except Exception as e:
                return {"ok": False, "error": e, "tb": traceback.format_exc()}
            return {"ok": True, "items": items}

        def _on_done(res):
            if not cal_status.winfo_exists():
                return
            if not res["ok"]:
                cal_status.config(text="Kalenderliste nicht verfügbar")
                messagebox.showerror(
                    "Google Kalender",
                    "Kalenderliste konnte nicht geladen werden:\n\n"
                    f"{res['error']}\n\n{res['tb']}",
                    parent=dialog,
                )
                return
            _populate_calendars(res["items"])

        runner.run(_fn, _on_done)

    def _on_gcal_toggled():
        assert cb_gcal is not None
        new_state = var_gcal.get()
        if new_state and not settings.get("gcal_enabled"):
            cb_gcal.config(state="disabled")

            def _service():
                from src import gcal
                gcal.get_calendar_service(
                    os.path.join(base_path, "credentials.json"),
                    os.path.join(base_path, "token.json"),
                    sync_enabled=settings.get("sync_enabled"),
                )

            fn, on_done = build_oauth_enable_task(
                service_fn=_service, settings=settings,
                setting_key="gcal_enabled", checkbox=cb_gcal,
                toggle_var=var_gcal, on_change=on_change, dialog=dialog,
                error_title="Google Kalender aktivieren",
                on_success_dialog_ui=_load_calendars,
            )
            runner.run(fn, on_done)
            return
        if not new_state and settings.get("gcal_enabled"):
            settings.set("gcal_enabled", False)
            on_change()

    cb_gcal.config(command=_on_gcal_toggled)

    if settings.get("gcal_enabled"):
        _load_calendars()

    # ===================== Tab: App =====================
    label(tab_app, "Bundesland:", row=0, pady=(10, 8))
    state_labels = [lbl for _, lbl in STATES]
    current_code = settings.get("state")
    current_label = next(
        (lbl for code, lbl in STATES if code == current_code),
        STATES[0][1],
    )
    state_var = tk.StringVar(value=current_label)
    dark_combo(tab_app, state_var, state_labels, width=22).grid(
        row=0, column=1, padx=10, pady=(10, 8), sticky="w")

    # Gerätelokale UI-Optionen. Alle in app_frame (ein Grid-Member), damit die
    # pack-Interna dieses Frames unberührt bleiben.
    app_frame = tk.Frame(tab_app, bg=BG)
    app_frame.grid(row=1, column=0, columnspan=2, padx=10, pady=(4, 4), sticky="we")

    show_weekend_var = tk.BooleanVar(value=settings.get("show_weekend"))
    tk.Checkbutton(
        app_frame, text="Wochenende (Sa/So) im Kalender anzeigen",
        variable=show_weekend_var, font=FONT,
        bg=BG, fg=TEXT, selectcolor=CELL_BG,
        activebackground=BG, activeforeground=TEXT,
        cursor="hand2",
    ).pack(anchor="w")

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
    scale_style = ttk.Style(dialog)
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

    # ===================== Speichern / Buttons =====================
    tabs = {"work": work.frame, "mail": tab_mail, "google": tab_google, "app": tab_app}

    def save_settings():
        for key, lbl in zip(WEEKDAY_KEYS, DAYS_DE):
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

        new_autostart = autostart_var.get()
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

        reminder_minutes = parse_reminder_minutes(reminder_minutes_var.get())
        if reminder_minutes is None:
            notebook.select(tabs["app"])
            themed_showerror(
                dialog, "Erinnerungszeit ungültig",
                "Bitte eine ganze Zahl zwischen 0 und 120 Minuten angeben.",
            )
            return

        hourly_rate = parse_hourly_rate(rate_var.get())
        selected_code = code_for_state_label(state_var.get())
        old_scale = settings.get("ui_scale")
        new_scale = clamp_ui_scale((round(scale_var.get() / 5) * 5) / 100)

        updates = {
            "autostart": new_autostart,
            "default_pause": int(work.pause_var.get()),
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
            "reminders_enabled": reminders_enabled_var.get(),
            "reminder_minutes_before": reminder_minutes,
            "ui_scale": new_scale,
            "werkstudent_limit_enabled": work.wsl_enabled_var.get(),
            "werkstudent_limit_start": wsl_start_iso,
            "werkstudent_limit_end": wsl_end_iso,
            "werkstudent_limit_max_hours": wsl_max_hours,
        }
        for key in WEEKDAY_KEYS:
            updates[f"default_start_{key}"] = work.start_vars[key].get()
            updates[f"default_end_{key}"] = work.end_vars[key].get()
        settings.apply_updates(updates)
        # Kalender-Auswahl: Klarname zurück auf ID mappen, als Sync-Setting
        # speichern. Nur wenn die Kalenderliste schon geladen ist (cal_map
        # gefüllt) — sonst würde ein vorschnelles Speichern "primary" festschreiben.
        if settings.get("gcal_enabled") and cal_map:
            selected_cal_id = resolve_calendar_id(
                cal_map, cal_var.get(), settings.get("gcal_calendar_id"))
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
