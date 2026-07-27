"""Tab „Google": Konto/Status, Absender, Drive-Sync (Konflikte/Import/
Reconnect/Kompaktierung) und Google-Kalender — inkl. der H5-Worker
(runner.run, Persistenz im fn, winfo_exists-Guards)."""

import logging
import os
import tkinter as tk
import traceback
from tkinter import messagebox

from src.dialogs.settings_dialog._shared import label, subheader
from src.dialogs.settings_dialog.oauth_task import build_oauth_enable_task
from src.platform_open import open_folder
from src.theme import (
    ACCENT, BG, CELL_BG, FONT, FONT_SMALL, STATUS_OK, TEXT, TEXT_MUTED,
    dark_combo, secondary_button, themed_askyesno, themed_showerror,
    themed_showinfo, themed_showwarning,
)
from src.time_utils import format_iso_date


class GoogleTab:
    """Baut den Google-Tab; exponiert cal_map/cal_var für save_settings."""

    def __init__(self, frame, dialog, settings, base_path, on_change, runner,
                 storage, conflicts_store, reservation_store,
                 data_lock, sync_guard):
        creds_path = os.path.join(base_path, "credentials.json")

        subheader(frame, "Google-Konto", row=0, top_pad=10)

        label(frame, "Datenordner:", row=1, pady=4)
        creds_row = tk.Frame(frame, bg=BG)
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
        label(frame, "Absender:", row=2, pady=(0, 4))
        sender_row = tk.Frame(frame, bg=BG)
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

        label(frame, "Berechtigungen:", row=3, pady=(0, 4))
        scopes_row = tk.Frame(frame, bg=BG)
        scopes_row.grid(row=3, column=1, padx=10, pady=(0, 4), sticky="w")

        def _open_scopes():
            from src.dialogs.scopes_dialog import open_scopes_dialog
            open_scopes_dialog(dialog, settings, base_path)

        secondary_button(
            scopes_row, "Anzeigen", _open_scopes, padx=12, pady=2,
        ).pack(side=tk.LEFT)

        subheader(frame, "Synchronisation", row=4)
        tk.Label(
            frame, text="Diese Schalter wirken sofort (Anmeldung im Browser).",
            font=FONT_SMALL, bg=BG, fg=TEXT_MUTED,
        ).grid(row=5, column=0, columnspan=2, padx=10, pady=(0, 4), sticky="w")

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
            frame, text="Mit Google Drive synchronisieren",
            variable=var_sync, font=FONT,
            bg=BG, fg=TEXT, selectcolor=CELL_BG,
            activebackground=BG, activeforeground=TEXT,
            cursor="hand2",
            command=_on_sync_toggled,
        )
        cb_sync.grid(row=6, column=0, columnspan=2, padx=10, pady=(4, 0), sticky="w")

        device_id = settings.get("device_id") or "(noch nicht gesetzt)"
        device_id_short = device_id[:8] + "…" if len(device_id) > 8 else device_id
        tk.Label(
            frame, text=f"Geräte-ID: {device_id_short}", font=FONT_SMALL,
            bg=BG, fg=TEXT_MUTED,
        ).grid(row=7, column=0, columnspan=2, padx=10, pady=(2, 0), sticky="w")

        last = format_iso_date(settings.get("last_pull_at"), fallback="noch nie")
        tk.Label(
            frame, text=f"Letzte Synchronisation: {last}", font=FONT_SMALL,
            bg=BG, fg=TEXT_MUTED,
        ).grid(row=8, column=0, columnspan=2, padx=10, pady=(2, 4), sticky="w")

        # Ab hier wachsen im Google-Tab optionale Zeilen (Konflikte, Kompaktieren)
        # dynamisch — deshalb eine laufende Row-Nummer statt fixer Konstanten.
        next_google_row = 9
        unresolved = 0
        if conflicts_store is not None:
            unresolved = conflicts_store.count_unresolved()
        if unresolved > 0:
            def _open_conflicts_dialog():
                from src.dialogs.conflicts_dialog import ConflictsDialog
                # data_lock durchgereicht bis zu sync.resolve_conflict
                # (Review-Finding: RMW-Spanne muss atomar gegen Hintergrund-Sync sein).
                ConflictsDialog(dialog, storage, settings, conflicts_store,
                               data_lock=data_lock, on_resolved=on_change)

            secondary_button(
                frame,
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

        btn_row = tk.Frame(frame, bg=BG)
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

        # Nicht an sync_enabled hängen, sondern an "hat je gesynct" (Audit N6):
        # wer den Sync abschaltet, behält seine Tombstones (das Remote kennt
        # die gelöschten Tage weiter) — und braucht damit weiterhin einen Weg,
        # sie loszuwerden. Die Kompaktierung ist ein voller Drive-Roundtrip
        # (Pull → Merge → Watermark → Push) und bleibt auch dann die sichere
        # Variante, weil sie alle Geräte über das gc_watermark einbezieht. Nie
        # gesyncte Rechner brauchen den Knopf nicht: dort verwirft der
        # Startup-Sweep (sync.drop_orphan_tombstones) die Tombstones ohnehin.
        ever_synced = settings.get("sync_enabled") or settings.get("last_pull_at")
        if ever_synced and storage is not None and conflicts_store is not None:
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
                frame, "Sync-Daten kompaktieren", _on_compact_clicked,
                padx=12, pady=2,
            ).grid(row=next_google_row, column=0, columnspan=2, padx=10, pady=(0, 8), sticky="w")
            next_google_row += 1

        subheader(frame, "Google Kalender", row=next_google_row)
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
            frame, text="Reservierungen mit Google Kalender abgleichen",
            variable=var_gcal, font=FONT,
            bg=BG, fg=TEXT, selectcolor=CELL_BG,
            activebackground=BG, activeforeground=TEXT,
            cursor="hand2",
        )
        cb_gcal.grid(row=gcal_check_row, column=0, columnspan=2, padx=10, pady=(4, 0), sticky="w")

        tk.Label(frame, text="Kalender:", font=FONT, bg=BG, fg=TEXT).grid(
            row=cal_label_row, column=0, padx=10, pady=4, sticky="w")
        cal_combo = dark_combo(frame, cal_var, [cal_var.get()], width=30)
        cal_combo.grid(row=cal_label_row, column=1, padx=10, pady=4, sticky="w")

        cal_status = tk.Label(frame, text="", font=FONT_SMALL, bg=BG, fg=TEXT_MUTED)
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

        self.frame = frame
        self.cal_map = cal_map
        self.cal_var = cal_var
