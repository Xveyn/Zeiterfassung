"""Tab „Google": Konto/Status, Absender, Drive-Sync (Konflikte/Import/
Reconnect/Kompaktierung) und Google-Kalender — inkl. der H5-Worker
(runner.run, Persistenz im fn, winfo_exists-Guards)."""

import logging
import os
import tkinter as tk
import traceback
from tkinter import messagebox

from src.dialogs.settings_dialog._shared import label, subheader
from src.dialogs.settings_dialog.google_tab_task import (
    fetch_sender_email, load_calendars, open_calendar_service,
    open_drive_service, reconnect_drive,
)
from src.dialogs.settings_dialog.oauth_task import build_oauth_enable_task
from src.platform_open import open_folder
from src.sync_runtime import run_compaction_blocking
from src.theme import (
    ACCENT, BG, CELL_BG, FONT, FONT_SMALL, STATUS_OK, TEXT, TEXT_MUTED,
    dark_combo, dark_entry, secondary_button, themed_askyesno, themed_showerror,
    themed_showinfo, themed_showwarning,
)
from src.tooltip import attach_tooltip
from src.time_utils import format_iso_date

# Zeichen + Farbe je Zustand aus mail.scope_summary — dieselbe Sprache
# wie die credentials.json-Zeile darüber (✓ grün / ✗ rot).
_SCOPE_MARKS = {
    "ok": ("✓", STATUS_OK),
    "partial": ("○", TEXT_MUTED),
    "core_missing": ("✗", ACCENT),
}


class GoogleTab:
    """Baut den Google-Tab; exponiert cal_map/cal_var für save_settings.

    Aufgebaut in drei Sektionsmethoden (R4, #51): `_build_account_section`,
    `_build_sync_section`, `_build_calendar_section`. Vorher lag alles in
    einem 525-Zeilen-`__init__` mit 13 Closures über ~30 geteilten lokalen
    Variablen; geteilter Zustand liegt jetzt auf `self`.

    Die Row-Nummern der Sync- und Kalender-Sektion sind nicht fix: optionale
    Zeilen (Konflikte, Kompaktieren) erscheinen nur unter Bedingungen. Deshalb
    reicht `_build_sync_section` die nächste freie Zeile an
    `_build_calendar_section` weiter.
    """

    def __init__(self, frame, dialog, settings, base_path, on_change, runner,
                 storage, conflicts_store, reservation_store,
                 data_lock, sync_guard):
        self.frame = frame
        self._dialog = dialog
        self._settings = settings
        self._base_path = base_path
        self._on_change = on_change
        self._runner = runner
        self._storage = storage
        self._conflicts_store = conflicts_store
        self._reservation_store = reservation_store
        self._data_lock = data_lock
        self._sync_guard = sync_guard
        self._creds_path = os.path.join(base_path, "credentials.json")

        # label_button liefert einen tk.Frame (keine -state-Option) — Doppelklick-
        # Schutz daher über ein Flag statt cb.config(state=...).
        self._reconnect_busy = False

        # Cache, damit der 500ms-Poll token.json nur bei echter Änderung liest.
        self._scope_stamp = None
        self._scope_granted = None

        self._build_account_section()
        next_row = self._build_sync_section()
        self._build_calendar_section(next_row)

    # --- Google-Konto -----------------------------------------------------

    def _build_account_section(self):
        frame, settings = self.frame, self._settings

        subheader(frame, "Google-Konto", row=0, top_pad=10)

        label(frame, "Datenordner:", row=1, pady=4)
        creds_row = tk.Frame(frame, bg=BG)
        creds_row.grid(row=1, column=1, padx=10, pady=4, sticky="w")

        secondary_button(
            creds_row, "Ordner öffnen", self._open_data_folder, padx=12, pady=2,
        ).pack(side=tk.LEFT)

        self._status_label = tk.Label(creds_row, text="", font=FONT_SMALL, bg=BG)
        self._status_label.pack(side=tk.LEFT, padx=(10, 0))
        self._refresh_status()

        # Absender-Zeile: zeigt die authentifizierte E-Mail-Adresse, die ui.py
        # im Hintergrund über OAuth2-userinfo abruft und in settings cached.
        label(frame, "Absender:", row=2, pady=(0, 4))
        sender_row = tk.Frame(frame, bg=BG)
        sender_row.grid(row=2, column=1, padx=10, pady=(0, 4), sticky="w")
        self._sender_label = tk.Label(
            sender_row,
            text=settings.get("sender_email") or "(noch nicht ermittelt)",
            font=FONT, bg=BG, fg=TEXT_MUTED,
        )
        self._sender_label.pack(side=tk.LEFT)

        self._sender_btn = secondary_button(
            sender_row,
            "Aktualisieren" if settings.get("sender_email") else "Anmelden",
            self._refresh_sender,
            padx=12, pady=2,
        )
        self._sender_btn.pack(side=tk.LEFT, padx=(10, 0))

        label(frame, "Berechtigungen:", row=3, pady=(0, 4))
        scopes_row = tk.Frame(frame, bg=BG)
        scopes_row.grid(row=3, column=1, padx=10, pady=(0, 4), sticky="w")

        secondary_button(
            scopes_row, "Anzeigen", self._open_scopes, padx=12, pady=2,
        ).pack(side=tk.LEFT)

        self._scopes_status = tk.Label(scopes_row, text="", font=FONT_SMALL, bg=BG)
        self._scopes_status.pack(side=tk.LEFT, padx=(10, 0))
        self._refresh_scopes_status()

    def _open_data_folder(self):
        try:
            open_folder(self._base_path)
        except Exception as e:
            logging.getLogger(__name__).exception("Datenordner konnte nicht geöffnet werden")
            messagebox.showerror(
                "Ordner konnte nicht geöffnet werden",
                f"{type(e).__name__}: {e}\n\n{traceback.format_exc()}",
                parent=self._dialog,
            )

    def _refresh_status(self):
        if not self._status_label.winfo_exists():
            return
        if os.path.exists(self._creds_path):
            self._status_label.config(text="✓ credentials.json vorhanden", fg=STATUS_OK)
        else:
            self._status_label.config(text="✗ credentials.json fehlt", fg=ACCENT)
        self._dialog.after(500, self._refresh_status)

    def _set_sender_btn_text(self, text):
        # secondary_button ist ein Frame+Label-Konstrukt (kein tk.Button),
        # der Text liegt am inneren `_label`. Kein -state-Option — wir
        # markieren den laufenden Zustand nur über den Text.
        if hasattr(self._sender_btn, "_label"):
            self._sender_btn._label.config(text=text)

    def _refresh_sender(self):
        """OAuth-Flow + userinfo-Fetch im Thread, danach Label aktualisieren."""
        from src.dialogs.send_dialog import show_missing_credentials_dialog

        settings, base_path, dialog = self._settings, self._base_path, self._dialog

        if not os.path.exists(self._creds_path):
            # Konsistent mit Senden/Teilen: freundlicher Hinweis + „Datenordner
            # öffnen" statt OAuth-Traceback bei fehlender credentials.json.
            show_missing_credentials_dialog(dialog, base_path)
            return

        self._set_sender_btn_text("Verbinde…")

        def _on_done(res):
            if not self._sender_label.winfo_exists():
                return
            self._set_sender_btn_text("Aktualisieren")
            if not res["ok"]:
                messagebox.showerror(
                    "Anmeldung fehlgeschlagen",
                    "OAuth-Flow oder Userinfo-Aufruf fehlgeschlagen:\n\n"
                    f"{res['error']}\n\n{res['tb']}",
                    parent=dialog,
                )
                return
            email = res["email"]
            self._sender_label.config(
                text=email if email
                else "(nicht verfügbar — Scope fehlt evtl.)")

        self._runner.run(lambda: fetch_sender_email(settings, base_path), _on_done)

    def _open_scopes(self):
        from src.dialogs.scopes_dialog import open_scopes_dialog
        open_scopes_dialog(self._dialog, self._settings, self._base_path)

    def _refresh_scopes_status(self):
        """Hält den Einzeiler neben „Anzeigen" aktuell.

        Hängt am selben Poll wie die credentials.json-Zeile, statt einen
        zweiten Timer aufzumachen: so zieht der Text sowohl nach einem
        Re-Consent (token.json ändert sich) als auch nach dem Umlegen der
        Sync-/Kalender-Schalter (Nenner ändert sich) nach.
        """
        from src.mail import scope_summary
        from src.oauth_utils import read_granted_scopes

        if not self._scopes_status.winfo_exists():
            return
        token_path = os.path.join(self._base_path, "token.json")
        try:
            st = os.stat(token_path)
            stamp = (st.st_mtime, st.st_size)
        except OSError:
            stamp = None
        if stamp != self._scope_stamp:
            self._scope_stamp = stamp
            self._scope_granted = (
                read_granted_scopes(token_path) if stamp is not None else None)

        granted = self._scope_granted
        if granted is None:
            text = ("✗ nicht angemeldet" if stamp is None
                    else "✗ Berechtigungen nicht lesbar")
            self._scopes_status.config(text=text, fg=ACCENT)
        else:
            summary = scope_summary(
                granted,
                self._settings.get("sync_enabled"),
                self._settings.get("gcal_enabled"),
            )
            mark, color = _SCOPE_MARKS[summary.status]
            self._scopes_status.config(text=f"{mark} {summary.text}", fg=color)
        self._dialog.after(500, self._refresh_scopes_status)

    # --- Synchronisation --------------------------------------------------

    def _build_sync_section(self):
        """Baut die Sync-Sektion und liefert die nächste freie Grid-Zeile."""
        frame, settings = self.frame, self._settings

        subheader(frame, "Synchronisation", row=4)
        tk.Label(
            frame, text="Diese Schalter wirken sofort (Anmeldung im Browser).",
            font=FONT_SMALL, bg=BG, fg=TEXT_MUTED,
        ).grid(row=5, column=0, columnspan=2, padx=10, pady=(0, 4), sticky="w")

        self._var_sync = tk.BooleanVar(value=settings.get("sync_enabled"))
        self._cb_sync = tk.Checkbutton(
            frame, text="Mit Google Drive synchronisieren",
            variable=self._var_sync, font=FONT,
            bg=BG, fg=TEXT, selectcolor=CELL_BG,
            activebackground=BG, activeforeground=TEXT,
            cursor="hand2",
            command=self._on_sync_toggled,
        )
        self._cb_sync.grid(row=6, column=0, columnspan=2, padx=10, pady=(4, 0), sticky="w")

        # Gerätename: reist über die Sync-Registry mit und macht die
        # Geräte-ID im Konfliktdialog lesbar (s. devices.py). Leer lassen ist
        # erlaubt — dann zeigt der Dialog weiter nur die gekürzte ID.
        device_row = tk.Frame(frame, bg=BG)
        device_row.grid(row=7, column=0, columnspan=2, padx=10, pady=(6, 0), sticky="w")
        tk.Label(
            device_row, text="Gerät:", font=FONT_SMALL, bg=BG, fg=TEXT_MUTED,
        ).pack(side=tk.LEFT)
        self.device_name_var = tk.StringVar(value=settings.get("device_name") or "")
        entry = dark_entry(device_row, self.device_name_var, width=24)
        entry.pack(side=tk.LEFT, padx=(6, 0))
        attach_tooltip(
            entry,
            "Name dieses Geräts. Andere Geräte zeigen ihn beim Auflösen\n"
            "von Sync-Konflikten statt der Geräte-ID an.",
        )

        device_id = settings.get("device_id") or "(noch nicht gesetzt)"
        device_id_short = device_id[:8] + "…" if len(device_id) > 8 else device_id
        tk.Label(
            frame, text=f"Geräte-ID: {device_id_short}", font=FONT_SMALL,
            bg=BG, fg=TEXT_MUTED,
        ).grid(row=8, column=0, columnspan=2, padx=10, pady=(2, 0), sticky="w")

        last = format_iso_date(settings.get("last_pull_at"), fallback="noch nie")
        tk.Label(
            frame, text=f"Letzte Synchronisation: {last}", font=FONT_SMALL,
            bg=BG, fg=TEXT_MUTED,
        ).grid(row=9, column=0, columnspan=2, padx=10, pady=(2, 4), sticky="w")

        # Ab hier wachsen im Google-Tab optionale Zeilen (Konflikte, Kompaktieren)
        # dynamisch — deshalb eine laufende Row-Nummer statt fixer Konstanten.
        next_google_row = 10
        unresolved = 0
        if self._conflicts_store is not None:
            unresolved = self._conflicts_store.count_unresolved()
        if unresolved > 0:
            secondary_button(
                frame,
                f"Konflikte ansehen ({unresolved})",
                self._open_conflicts_dialog,
                padx=12, pady=2,
            ).grid(row=next_google_row, column=0, columnspan=2, padx=10, pady=(0, 8), sticky="w")
            next_google_row += 1

        btn_row = tk.Frame(frame, bg=BG)
        btn_row.grid(row=next_google_row, column=0, columnspan=2, padx=10, pady=(4, 8), sticky="w")
        next_google_row += 1

        secondary_button(
            btn_row, "Google neu verbinden", self._reconnect_google, padx=12, pady=2,
        ).pack(side=tk.LEFT)

        if self._storage is not None:
            secondary_button(
                btn_row, "Daten importieren", self._open_import_dialog, padx=12, pady=2,
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
        if ever_synced and self._storage is not None and self._conflicts_store is not None:
            secondary_button(
                frame, "Sync-Daten kompaktieren", self._on_compact_clicked,
                padx=12, pady=2,
            ).grid(row=next_google_row, column=0, columnspan=2, padx=10, pady=(0, 8), sticky="w")
            next_google_row += 1

        return next_google_row

    def _on_sync_toggled(self):
        settings, base_path = self._settings, self._base_path
        new_state = self._var_sync.get()
        if new_state and not settings.get("sync_enabled"):
            self._cb_sync.config(state="disabled")

            fn, on_done = build_oauth_enable_task(
                service_fn=lambda: open_drive_service(settings, base_path),
                settings=settings,
                setting_key="sync_enabled", checkbox=self._cb_sync,
                toggle_var=self._var_sync, on_change=self._on_change,
                dialog=self._dialog,
                error_title="Synchronisation aktivieren",
            )
            self._runner.run(fn, on_done)
            return
        if not new_state and settings.get("sync_enabled"):
            settings.set("sync_enabled", False)
            self._on_change()

    def _open_conflicts_dialog(self):
        from src.dialogs.conflicts_dialog import ConflictsDialog
        # data_lock durchgereicht bis zu sync.resolve_conflict
        # (Review-Finding: RMW-Spanne muss atomar gegen Hintergrund-Sync sein).
        ConflictsDialog(self._dialog, self._storage, self._settings,
                        self._conflicts_store, data_lock=self._data_lock,
                        on_resolved=self._on_change)

    def _open_import_dialog(self):
        from src.dialogs.import_dialog import open_import_dialog

        def _after_import():
            self._on_change()
            self._dialog.destroy()

        open_import_dialog(
            self._dialog, self._storage, self._settings, _after_import,
            reservation_store=self._reservation_store,
        )

    def _reconnect_google(self):
        dialog, settings, base_path = self._dialog, self._settings, self._base_path

        if self._reconnect_busy:
            return
        if not themed_askyesno(
            dialog, "Google neu verbinden",
            "Die App fragt die Google-Berechtigungen neu ab. Dazu öffnet sich "
            "ein Browser-Fenster zur Anmeldung — bitte dort die Freigabe "
            "bestätigen.\n\nFortfahren?",
        ):
            return
        self._reconnect_busy = True

        def _on_done(res):
            self._reconnect_busy = False
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

        self._runner.run(lambda: reconnect_drive(settings, base_path), _on_done)

    def _on_compact_clicked(self):
        dialog = self._dialog

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
            return run_compaction_blocking(
                self._storage, self._settings, self._conflicts_store,
                self._base_path,
                data_lock=self._data_lock, sync_guard=self._sync_guard)

        self._runner.run(_fn, _show)

    # --- Google Kalender --------------------------------------------------

    def _build_calendar_section(self, start_row):
        frame, settings = self.frame, self._settings

        subheader(frame, "Google Kalender", row=start_row)
        start_row += 1

        self._var_gcal = tk.BooleanVar(value=settings.get("gcal_enabled"))

        # Kalender-Auswahl: Combobox zeigt Klarnamen, gespeichert wird die ID.
        # cal_map summary->id wird im Hintergrund per API befüllt.
        self.cal_map: dict[str, str] = {}
        self.cal_var = tk.StringVar(value=settings.get("gcal_calendar_id") or "primary")

        gcal_check_row = start_row
        cal_label_row = start_row + 1
        cal_status_row = start_row + 2

        self._cb_gcal = tk.Checkbutton(
            frame, text="Reservierungen mit Google Kalender abgleichen",
            variable=self._var_gcal, font=FONT,
            bg=BG, fg=TEXT, selectcolor=CELL_BG,
            activebackground=BG, activeforeground=TEXT,
            cursor="hand2",
            command=self._on_gcal_toggled,
        )
        self._cb_gcal.grid(row=gcal_check_row, column=0, columnspan=2,
                           padx=10, pady=(4, 0), sticky="w")

        tk.Label(frame, text="Kalender:", font=FONT, bg=BG, fg=TEXT).grid(
            row=cal_label_row, column=0, padx=10, pady=4, sticky="w")
        self._cal_combo = dark_combo(frame, self.cal_var, [self.cal_var.get()], width=30)
        self._cal_combo.grid(row=cal_label_row, column=1, padx=10, pady=4, sticky="w")

        self._cal_status = tk.Label(frame, text="", font=FONT_SMALL, bg=BG, fg=TEXT_MUTED)
        self._cal_status.grid(row=cal_status_row, column=0, columnspan=2,
                              padx=10, pady=(0, 4), sticky="w")

        if settings.get("gcal_enabled"):
            self._load_calendars()

    def _populate_calendars(self, items):
        if not self._cal_combo.winfo_exists():
            return
        self.cal_map.clear()
        for it in items:
            self.cal_map[it["summary"]] = it["id"]
        self._cal_combo["values"] = list(self.cal_map.keys()) or [self.cal_var.get()]
        # Gespeicherte ID auf den passenden Klarnamen zurückmappen.
        stored_id = self._settings.get("gcal_calendar_id") or "primary"
        for summary, cid in self.cal_map.items():
            if cid == stored_id:
                self.cal_var.set(summary)
                break
        self._cal_status.config(text="")

    def _load_calendars(self):
        settings, base_path, dialog = self._settings, self._base_path, self._dialog

        self._cal_status.config(text="Kalenderliste wird geladen…")

        def _on_done(res):
            if not self._cal_status.winfo_exists():
                return
            if not res["ok"]:
                self._cal_status.config(text="Kalenderliste nicht verfügbar")
                messagebox.showerror(
                    "Google Kalender",
                    "Kalenderliste konnte nicht geladen werden:\n\n"
                    f"{res['error']}\n\n{res['tb']}",
                    parent=dialog,
                )
                return
            self._populate_calendars(res["items"])

        self._runner.run(lambda: load_calendars(settings, base_path), _on_done)

    def _on_gcal_toggled(self):
        settings, base_path = self._settings, self._base_path
        new_state = self._var_gcal.get()
        if new_state and not settings.get("gcal_enabled"):
            self._cb_gcal.config(state="disabled")

            fn, on_done = build_oauth_enable_task(
                service_fn=lambda: open_calendar_service(settings, base_path),
                settings=settings,
                setting_key="gcal_enabled", checkbox=self._cb_gcal,
                toggle_var=self._var_gcal, on_change=self._on_change,
                dialog=self._dialog,
                error_title="Google Kalender aktivieren",
                on_success_dialog_ui=self._load_calendars,
            )
            self._runner.run(fn, on_done)
            return
        if not new_state and settings.get("gcal_enabled"):
            settings.set("gcal_enabled", False)
            self._on_change()
