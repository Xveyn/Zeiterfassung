"""Tab „Google": Konto/Status, Absender, Drive-Sync (Konflikte/Import/
Reconnect/Kompaktierung) und Google-Kalender — inkl. der H5-Worker
(runner.run, Persistenz im fn, winfo_exists-Guards)."""

import logging
import os
from collections.abc import Callable
import tkinter as tk
from tkinter import messagebox

from src import gcal
from src.devices import MAX_NAME_LENGTH
from src.dialogs.settings_dialog.fields import FieldSet
from src.dialogs.settings_dialog.form_model import SaveOutcome
from src.dialogs.settings_dialog.google_tab_task import (
    check_token_status, fetch_sender_email, load_calendars,
    open_calendar_service, open_drive_service, reconnect_drive,
)
from src.dialogs.settings_dialog.oauth_task import (
    build_oauth_enable_task, show_known_google_failure,
)
from src.dialogs.settings_dialog.tab_rules import calendar_update, google_updates
from src.oauth_utils import (
    KEYRING_UNAVAILABLE_HINT, KEYRING_UNAVAILABLE_TITLE, is_keyring_unavailable,
)
from src.sync_runtime import run_compaction_blocking
from src.theme import (
    ACCENT, BG, FONT, FONT_SMALL, STATUS_OK, STATUS_WARN, TEXT_MUTED, Form,
    dark_combo, dark_entry, secondary_button, themed_askyesno, themed_showerror,
    themed_showinfo, themed_showwarning,
)
from src.time_utils import format_date, local_date_of_iso

# Zeichen + Farbe je Zustand aus mail.scope_summary — dieselbe Sprache
# wie die credentials.json-Zeile darüber (✓ grün / ✗ rot).
_SCOPE_MARKS = {
    "ok": ("✓", STATUS_OK),
    "partial": ("○", TEXT_MUTED),
    "core_missing": ("✗", ACCENT),
}

# Text + Farbe je Token-Zustand aus google_tab_task.check_token_status.
# „unknown" (offline) bleibt bewusst gedämpft statt warnend: nicht prüfbar
# ist nicht dasselbe wie abgelaufen, und ein falscher Alarm schickte den
# Nutzer grundlos durch einen Re-Consent.
_TOKEN_MARKS = {
    "valid": ("✓ gültig", STATUS_OK),
    "no_token": ("nicht angemeldet", TEXT_MUTED),
    "reauth": ("⚠ abgelaufen — „Google neu verbinden“ nötig", STATUS_WARN),
    "unknown": ("nicht prüfbar (offline)", TEXT_MUTED),
    "keyring": ("⚠ Schlüsselbund nicht erreichbar", STATUS_WARN),
}


class GoogleTab:
    """Baut den Google-Tab; Tab-Schnittstelle für den `SaveCoordinator`
    (#132).

    Aufgebaut in Sektionsmethoden (R4, #51): `_build_account_section`,
    `_build_sync_section`, `_build_calendar_section`,
    `_build_advanced_section`. Vorher lag alles in
    einem 525-Zeilen-`__init__` mit 13 Closures über ~30 geteilten lokalen
    Variablen; geteilter Zustand liegt jetzt auf `self`.

    Die Sektionen bauen in ein gemeinsames `Form` (#132) — Zeilen zählt das
    Formular, keine Row-Nummern mehr von Hand. Dazu kommt `_build_advanced_
    section` für die Kompaktierung.
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

        self.title = "Google"
        # Setzt der Dialog: nach dem Nachladen der Kalenderliste steht in
        # `cal_var` der Klarname statt der ID — das ist keine Änderung des
        # Nutzers, der Coordinator übernimmt es als gespeichert.
        self.on_calendars_loaded: Callable[[], None] | None = None

        self._form = Form(frame, scroll=True)
        self._form.frame.pack(fill="both", expand=True)
        self._build_account_section()
        self._build_sync_section()
        self._build_calendar_section()
        self._build_advanced_section()

        fields = FieldSet()
        fields.add("device_name", self.device_name_var)
        fields.add("gcal_calendar", self.cal_var)
        self.fields = fields

    def values(self):
        return self.fields.values()

    def load(self, values):
        self.fields.load(values)

    def validate(self):
        return None

    def save(self):
        settings = self._settings
        raw = self.values()
        settings.apply_updates(google_updates(raw))
        new_id = calendar_update(
            self.cal_map, raw["gcal_calendar"],
            settings.get("gcal_calendar_id"), bool(settings.get("gcal_enabled")))
        if new_id is not None:
            settings.set_synced("gcal_calendar_id", new_id)
        return SaveOutcome(saved=True)

    # --- Google-Konto -----------------------------------------------------

    def _build_account_section(self):
        form, settings = self._form, self._settings
        body = form.body
        form.section("Konto")

        self._status_label = tk.Label(body, text="", font=FONT_SMALL, bg=BG)
        form.row("credentials.json:", self._status_label)
        self._refresh_status()

        # Absender-Zeile: zeigt die authentifizierte E-Mail-Adresse, die ui.py
        # im Hintergrund über OAuth2-userinfo abruft und in settings cached.
        sender_row = tk.Frame(body, bg=BG)
        self._sender_label = tk.Label(
            sender_row,
            text=settings.get("sender_email") or "(noch nicht ermittelt)",
            font=FONT, bg=BG, fg=TEXT_MUTED,
        )
        self._sender_label.pack(side=tk.LEFT)
        self._sender_btn = secondary_button(
            sender_row,
            "Aktualisieren" if settings.get("sender_email") else "Anmelden",
            self._refresh_sender, padx=12, pady=2,
        )
        self._sender_btn.pack(side=tk.LEFT, padx=(10, 0))
        form.row("Absender:", sender_row)

        scopes_row = tk.Frame(body, bg=BG)
        secondary_button(
            scopes_row, "Anzeigen", self._open_scopes, padx=12, pady=2,
        ).pack(side=tk.LEFT)
        self._scopes_status = tk.Label(scopes_row, text="", font=FONT_SMALL, bg=BG)
        self._scopes_status.pack(side=tk.LEFT, padx=(10, 0))
        form.row("Berechtigungen:", scopes_row)
        self._refresh_scopes_status()

        # Anmeldung: trägt der Token noch? Ergänzt die Zeile darüber, ersetzt
        # sie nicht — die sagt, WELCHE Scopes gewährt sind, diese, OB der
        # Token überhaupt noch trägt (Xveyn#124). „Google neu verbinden"
        # steht direkt daneben: genau diese Zeile sagt, wann er nötig ist.
        token_row = tk.Frame(body, bg=BG)
        self._token_status = tk.Label(
            token_row, text="wird geprüft…", font=FONT_SMALL, bg=BG, fg=TEXT_MUTED)
        self._token_status.pack(side=tk.LEFT)
        secondary_button(
            token_row, "Google neu verbinden", self._reconnect_google,
            padx=12, pady=2,
        ).pack(side=tk.LEFT, padx=(10, 0))
        form.row("Anmeldung:", token_row)
        self._check_token()

    def _show_keyring_error(self, error):
        """Zeigt den Schlüsselbund-Ausfall (#101) als themed Meldung und
        liefert True — oder False, wenn `error` etwas anderes ist. Ein
        bekannter Fehler: kurz und ohne Traceback, anders als die nativen
        Catch-all-Dialoge daneben."""
        if not is_keyring_unavailable(error):
            return False
        themed_showerror(self._dialog, KEYRING_UNAVAILABLE_TITLE,
                         KEYRING_UNAVAILABLE_HINT)
        return True

    def _refresh_status(self):
        if not self._status_label.winfo_exists():
            return
        if os.path.exists(self._creds_path):
            self._status_label.config(text="✓ vorhanden", fg=STATUS_OK)
        else:
            self._status_label.config(
                text="✗ fehlt (Datenordner: Tab App)", fg=ACCENT)
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
                if show_known_google_failure(dialog, res.get("error"),
                                             base_path, "Anmelden"):
                    return
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

    def _check_token(self):
        """Prüft den Token beim Aufbau im Worker — ohne Browser.

        `check_token_status` erneuert dabei still, wenn der Refresh-Token noch
        trägt; nur wenn auch der tot ist, steht hier der Hinweis. Ein einzelner
        Netzaufruf pro Dialog-Öffnung, und nur dann, wenn der Token abgelaufen
        ist — ein gültiger Token wird lokal beantwortet.
        """
        settings, base_path = self._settings, self._base_path

        def _on_done(res):
            if not self._token_status.winfo_exists():
                return
            if not res["ok"]:
                # Unerwarteter Fehler: die Zeile ist ein Statusanzeiger, kein
                # Fehlerkanal — sie sagt „unbekannt", die Spur geht ins Log.
                logging.getLogger(__name__).warning(
                    "Token-Status nicht ermittelbar: %s", res["tb"])
                self._token_status.config(text="nicht prüfbar", fg=TEXT_MUTED)
                return
            text, fg = _TOKEN_MARKS[res["state"]]
            self._token_status.config(text=text, fg=fg)

        self._runner.run(lambda: check_token_status(settings, base_path), _on_done)

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
        form, settings = self._form, self._settings
        body = form.body
        form.section("Synchronisation",
                     hint="Der Schalter wirkt sofort (Anmeldung im Browser).")

        # Nicht in einer depends_on-Gruppe (Besitz-Vertrag): der Schalter
        # wird während des Consent-Flows selbst gesperrt (oauth_task).
        self._var_sync = tk.BooleanVar(value=settings.get("sync_enabled"))
        self._cb_sync = form.check("Mit Google Drive synchronisieren", self._var_sync)
        self._cb_sync.config(command=self._on_sync_toggled)

        # Gerätename: reist über die Sync-Registry mit und macht die
        # Geräte-ID im Konfliktdialog lesbar (s. devices.py). Leer lassen ist
        # erlaubt — dann zeigt der Dialog weiter nur die gekürzte ID.
        self.device_name_var = tk.StringVar(value=settings.get("device_name") or "")
        entry = dark_entry(body, self.device_name_var, width=24)
        # Die Länge deckelt beim Speichern ohnehin `sanitize_device_name`; hier
        # sichtbar machen, statt den Namen still zu kürzen (das Feld zeigte
        # nach dem Speichern weiter den ungekürzten Namen, gespeichert wäre ein
        # anderer).
        entry.config(
            validate="key",
            validatecommand=(body.register(
                lambda proposed: len(proposed) <= MAX_NAME_LENGTH), "%P"),
        )
        form.row("Gerät:", entry)
        # Bewusst KEIN Tooltip (Konvention „Tooltips" in CLAUDE.md): Dialoge
        # bekommen keine flächendeckenden, und ein Hover-Text an einem
        # Eingabefeld bliebe die ganze Tippdauer offen — er verdeckte dabei
        # genau die Zeilen darunter, weil `_Tooltip` starr unter dem Widget
        # aufpoppt und keinen Auto-Hide-Timeout kennt. Was nicht
        # selbsterklärend ist, steht deshalb als Hinweiszeile da.
        form.hint("Wird anderen Geräten bei Sync-Konflikten angezeigt.")

        device_id = settings.get("device_id") or "(noch nicht gesetzt)"
        device_id_short = device_id[:8] + "…" if len(device_id) > 8 else device_id
        form.row("Geräte-ID:", tk.Label(body, text=device_id_short, font=FONT,
                                        bg=BG, fg=TEXT_MUTED))

        # Lokales Datum wie im Header-Status-Label (s. sync_orchestrator.
        # _status_view) — zwei verschiedene Daten für denselben Wert wären
        # schlimmer als ein um Mitternacht schiefes.
        _pulled_on = local_date_of_iso(settings.get("last_pull_at"))
        last = format_date(_pulled_on) if _pulled_on else "noch nie"
        form.row("Letzte Synchronisation:", tk.Label(
            body, text=last, font=FONT, bg=BG, fg=TEXT_MUTED))

        unresolved = 0
        if self._conflicts_store is not None:
            unresolved = self._conflicts_store.count_unresolved()
        if unresolved > 0:
            form.buttons((f"Konflikte ansehen ({unresolved})",
                          self._open_conflicts_dialog))

    def _build_advanced_section(self):
        # Nicht an sync_enabled hängen, sondern an "hat je gesynct" (Audit N6):
        # wer den Sync abschaltet, behält seine Tombstones (das Remote kennt
        # die gelöschten Tage weiter) — und braucht damit weiterhin einen Weg,
        # sie loszuwerden. Die Kompaktierung ist ein voller Drive-Roundtrip
        # (Pull → Merge → Watermark → Push) und bleibt auch dann die sichere
        # Variante, weil sie alle Geräte über das gc_watermark einbezieht. Nie
        # gesyncte Rechner brauchen den Knopf nicht: dort verwirft der
        # Startup-Sweep (sync.drop_orphan_tombstones) die Tombstones ohnehin.
        settings = self._settings
        ever_synced = settings.get("sync_enabled") or settings.get("last_pull_at")
        if not (ever_synced and self._storage is not None
                and self._conflicts_store is not None):
            return
        # Abgesetzt ganz unten (#132): die Aktion entfernt Einträge endgültig
        # und stand vorher zwischen alltäglichen Knöpfen.
        self._form.section(
            "Erweitert",
            hint="Entfernt alte gelöschte Einträge endgültig aus dem Sync — "
                 "nur, wenn alle Geräte aktuell sind und kürzlich "
                 "synchronisiert haben.")
        self._form.buttons(("Sync-Daten kompaktieren", self._on_compact_clicked))

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
                base_path=base_path,
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
            if show_known_google_failure(dialog, res.get("error"), base_path,
                                         "Google neu verbinden"):
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
                if self._show_keyring_error(res.get("error")):
                    return
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

    def _build_calendar_section(self):
        form, settings = self._form, self._settings
        body = form.body
        form.section("Kalender",
                     hint="Der Schalter wirkt sofort (Anmeldung im Browser).")

        self._var_gcal = tk.BooleanVar(value=settings.get("gcal_enabled"))
        # Kalender-Auswahl: Combobox zeigt Klarnamen, gespeichert wird die ID.
        # cal_map summary->id wird im Hintergrund per API befüllt.
        self.cal_map: dict[str, str] = {}
        self.cal_var = tk.StringVar(value=settings.get("gcal_calendar_id") or "primary")

        # Wie beim Sync: nicht in eine Gruppe, der Consent sperrt ihn selbst.
        self._cb_gcal = form.check(
            "Reservierungen mit Google Kalender abgleichen", self._var_gcal)
        self._cb_gcal.config(command=self._on_gcal_toggled)
        with form.depends_on(self._var_gcal):
            self._cal_combo = dark_combo(body, self.cal_var,
                                         [self.cal_var.get()], width=30)
            form.row("Kalender:", self._cal_combo)
        # Außerhalb der Gruppe: „nicht verfügbar" soll lesbar bleiben.
        self._cal_status = form.hint("")

        if settings.get("gcal_enabled"):
            # Beim Aufbau: nicht-interaktiv. Hier hat niemand geklickt, und
            # ein Consent-Flow riss bisher ungefragt den Browser auf, sobald
            # der Token nicht mehr trug (Xveyn#124).
            self._load_calendars(interactive=False)

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
        if self.on_calendars_loaded is not None:
            self.on_calendars_loaded()

    def _load_calendars(self, interactive=True):
        """Lädt die Kalenderliste im Worker.

        `interactive=False` beim Tab-Aufbau: kein Consent-Flow, und der
        Fehlschlag bleibt in der Statuszeile. Eine Messagebox beim bloßen
        Öffnen des Dialogs wäre dieselbe Zumutung wie das Browserfenster —
        der Nutzer wollte nur in die Einstellungen.
        """
        settings, base_path, dialog = self._settings, self._base_path, self._dialog

        self._cal_status.config(text="Kalenderliste wird geladen…")

        def _on_done(res):
            if not self._cal_status.winfo_exists():
                return
            if not res["ok"]:
                if isinstance(res["error"], gcal.CalendarAuthError):
                    self._cal_status.config(
                        text="Kalenderliste nicht geladen — Anmeldung erforderlich")
                    return
                if is_keyring_unavailable(res["error"]):
                    self._cal_status.config(
                        text="Kalenderliste nicht geladen — Schlüsselbund nicht erreichbar")
                    if interactive:
                        self._show_keyring_error(res["error"])
                    return
                self._cal_status.config(text="Kalenderliste nicht verfügbar")
                if not interactive:
                    logging.getLogger(__name__).warning(
                        "Kalenderliste beim Öffnen nicht geladen: %s", res["tb"])
                    return
                if show_known_google_failure(dialog, res["error"], base_path,
                                             "Kalenderliste laden"):
                    return
                messagebox.showerror(
                    "Google Kalender",
                    "Kalenderliste konnte nicht geladen werden:\n\n"
                    f"{res['error']}\n\n{res['tb']}",
                    parent=dialog,
                )
                return
            self._populate_calendars(res["items"])

        self._runner.run(
            lambda: load_calendars(settings, base_path, interactive=interactive),
            _on_done)

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
                base_path=base_path,
                on_success_dialog_ui=self._load_calendars,
            )
            self._runner.run(fn, on_done)
            return
        if not new_state and settings.get("gcal_enabled"):
            settings.set("gcal_enabled", False)
            self._on_change()
