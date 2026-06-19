# src/ui.py
import tkinter as tk
from tkinter import messagebox
import calendar
import ctypes
import datetime
import logging
import os
import platform
import threading
import traceback
import webbrowser
from src.time_utils import (
    DAYS_DE, MONTHS_DE,
    calculate_hours, format_iso_date, get_week_dates, get_week_label, week_spans_months,
)
from src.holidays_de import get_holidays
from src.tooltip import attach_tooltip
from src.mail import fetch_user_email, refresh_token_if_needed, TokenAuthError, TokenNetworkError
from src.drive import DriveAuthError, DriveNetworkError
from src.version import VERSION
from src.updater import (
    check_latest_release,
    is_newer,
    pick_asset_url,
    should_check_today,
    today_iso,
    Release,
)

from src.dialogs.entry_dialog import open_entry_dialog
from src.dialogs.send_dialog import open_send_dialog
from src.dialogs.settings_dialog import open_settings_dialog
from src.theme import (
    BG, CELL_BG, WEEKEND_BG, ACCENT, ACCENT_HOVER, TEXT, TEXT_MUTED,
    ENTRY_BG, WEEKEND_ENTRY_BG, WEEKEND_FG,
    HOLIDAY_BG, HOLIDAY_BG_HOVER, HOLIDAY_ACCENT,
    RESERVATION_ACCENT, TODAY_ACCENT,
    FONT, FONT_BOLD, FONT_HEADER, FONT_HEADER_SMALL, FONT_FOOTER, FONT_SMALL, FONT_TINY,
    CELL_BG_HOVER, WEEKEND_BG_HOVER, ENTRY_BG_HOVER, WEEKEND_ENTRY_BG_HOVER,
    apply_dark_titlebar, themed_askyesno, themed_ask_delete_choice, themed_showinfo,
    icon_button, label_button, secondary_button, set_toggle_active, toggle_button,
)


def _classify_sync_error(error):
    """Kategorisiert einen Google-Sync/Reconcile-Fehler als 'auth', 'network'
    oder 'unknown'. `error` kann eine Exception oder ein String sein (der
    Push-/Reconcile-Pfad liefert str(e), der Pull-Pfad das Exception-Objekt).
    Der abgelaufene/widerrufene Token kommt als invalid_grant durch — sowohl
    bei Drive als auch beim Kalender, da beide denselben OAuth-Token nutzen.
    Ein 403 'insufficient authentication scopes' / 'insufficientPermissions'
    ist ebenfalls ein Auth-Fall (Token deckt einen Scope nicht ab → Re-Consent):
    im String-Pfad fehlt die Typinfo, daher zusätzlich per Textmuster erkannt."""
    text = str(error)
    if (isinstance(error, DriveAuthError)
            or "invalid_grant" in text
            or "expired or revoked" in text
            or "insufficientPermissions" in text
            or "insufficient authentication scopes" in text):
        return "auth"
    if isinstance(error, DriveNetworkError):
        return "network"
    return "unknown"


def _friendly_sync_message(error, tb=""):
    """Mappt einen Drive-Sync-Fehler auf (Titel, Meldung) für die Messagebox.

    Bekannte, erwartbare Fälle (abgelaufener/​widerrufener Token, fehlendes Netz)
    bekommen eine verständliche Meldung OHNE Traceback. Nur bei wirklich
    unerwarteten Fehlern bleibt der Traceback erhalten (CLAUDE.md: Fehler im
    Sendepfad sichtbar machen)."""
    kind = _classify_sync_error(error)

    if kind == "auth":
        return (
            "Google-Verbindung erneuern",
            "Die App braucht erneut deine Erlaubnis für Google Drive. Das "
            "passiert, wenn die Verbindung abgelaufen oder widerrufen wurde "
            "oder eine neue Freigabe nötig ist.\n\nBitte öffne die "
            "Einstellungen und klicke auf „Google neu verbinden\" — danach "
            "im Browser die Freigabe bestätigen.",
            True,
        )
    if kind == "network":
        return (
            "Keine Internetverbindung",
            "Die Synchronisation mit Google Drive ist fehlgeschlagen, weil "
            "keine Verbindung zum Internet besteht.\n\nBitte prüfe deine "
            "Verbindung und versuche es erneut.",
            True,
        )
    detail = f"{error}\n\n{tb}" if tb else str(error)
    return (
        "Synchronisation fehlgeschlagen",
        "Bei der Synchronisation mit Google Drive ist ein unerwarteter "
        f"Fehler aufgetreten:\n\n{detail}",
        False,
    )


def _show_sync_error(parent, error, tb="", suffix=""):
    """Zeigt einen Sync-Fehler im passenden Stil: bekannte Fälle (Token/Netz)
    als themed Info-Dialog (wie die Gmail-Token-Meldung), unerwartete Fehler
    als `showerror` mit Traceback (CLAUDE.md). `suffix` wird optional angehängt."""
    title, message, known = _friendly_sync_message(error, tb)
    if suffix:
        message = f"{message}\n\n{suffix}"
    if known:
        themed_showinfo(parent, title, message)
    else:
        messagebox.showerror(title, message)


class App:
    def __init__(self, root, storage, settings, base_path=".", conflicts_store=None,
                 reservation_store=None):
        self.root = root
        self.storage = storage
        self.settings = settings
        self.base_path = base_path
        self.conflicts_store = conflicts_store
        self.reservation_store = reservation_store
        self.root.title(f"Zeiterfassung v{VERSION}")
        self.root.configure(bg=BG)
        apply_dark_titlebar(self.root)

        # Set unique AppUserModelID so Windows shows our icon in taskbar.
        # Die AUMID bleibt bewusst die stabile, namespaced ID — Windows knüpft
        # Taskbar-Pins und Fenster-Gruppierung daran; ein Wechsel würde
        # bestehende Pins beim Update lösen. Den lesbaren Absender-Namen für
        # Toast-Benachrichtigungen (inkl. dynamischer Version) registrieren wir
        # separat als DisplayName unter dem AUMID-Registry-Key — den greift
        # Windows für die Toast-Attribution, ohne die AUMID selbst zu ändern.
        app_aumid = "margenheld.zeiterfassung"
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(app_aumid)
        except Exception:
            pass
        try:
            import winreg
            with winreg.CreateKeyEx(
                winreg.HKEY_CURRENT_USER,
                rf"Software\Classes\AppUserModelId\{app_aumid}",
            ) as _aumid_key:
                winreg.SetValueEx(
                    _aumid_key, "DisplayName", 0, winreg.REG_SZ,
                    f"Zeiterfassung v{VERSION}",
                )
        except Exception:
            pass

        # Set window/taskbar icon
        ico_path = os.path.join(base_path, "assets", "margenheld-icon.ico")
        png_path = os.path.join(base_path, "assets", "margenheld-icon.png")
        if platform.system() == "Windows" and os.path.exists(ico_path):
            # default=ico_path → `wm iconbitmap -default` setzt das
            # App-weite Default-Icon im Tk-Interpreter. Muss auf root
            # gesetzt werden, damit künftige Toplevels (Settings, Entry,
            # …) das Icon erben statt das Tk-Default-Feder-Icon zu zeigen.
            self.root.iconbitmap(default=ico_path)
        if os.path.exists(png_path):
            icon = tk.PhotoImage(file=png_path)
            self.root.iconphoto(True, icon)
            self._icon_ref = icon

        self.root.resizable(False, False)

        today = datetime.date.today()
        self.year = today.year
        self.month = today.month
        self.view_mode = "month"  # "month" or "week"
        iso = today.isocalendar()
        self.iso_year = iso[0]
        self.current_week = iso[1]

        self._build_header()
        self._build_grid()
        self._build_footer()
        self._apply_always_on_top()
        self._tray = None
        self._apply_tray_setting()
        self.root.bind("<Left>", lambda e: self._prev())
        self.root.bind("<Right>", lambda e: self._next())
        # Tab schaltet zwischen Monat- und Wochenansicht. "break" verhindert
        # die Default-Focus-Traversal, die sonst zwischen den Toggle-Buttons
        # springen würde und das Toggle visuell zerschießt.
        self.root.bind("<Tab>", self._on_tab_toggle_view)
        # Vor dem ersten echten Refresh: alle 4 Kombinationen
        # (view × show_weekend) einmal in den Backbuffer rendern, max reqwidth
        # observen. Das Fenster ist noch nicht gemappt (mainloop nicht
        # gestartet) — keine sichtbaren Zwischenzustände.
        self._fixed_width = self._measure_max_width()
        self._refresh()
        self._proactive_token_refresh()
        self._proactive_sender_email_fetch()
        self._update_banner = None
        self._proactive_update_check()
        self._proactive_calendar_reconcile()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _proactive_token_refresh(self):
        """Erneuert den Gmail-Token beim App-Start im Hintergrund.

        Auth-Fehler werden als Messagebox gezeigt, Netzwerkfehler still
        übergangen, damit ein Offline-Start nicht stört.
        """
        token_path = os.path.join(self.base_path, "token.json")

        def worker():
            try:
                refresh_token_if_needed(
                    token_path,
                    sync_enabled=self.settings.get("sync_enabled"),
                    gcal_enabled=self.settings.get("gcal_enabled"),
                )
            except TokenAuthError as e:
                msg = str(e)
                self.root.after(0, lambda: themed_showinfo(
                    self.root,
                    "Gmail-Anmeldung abgelaufen",
                    "Der Gmail-Token konnte nicht automatisch erneuert werden:\n\n"
                    f"{msg}\n\n"
                    "Beim nächsten Senden wirst du zur erneuten Anmeldung aufgefordert."
                ))
            except TokenNetworkError:
                pass
            except Exception as e:
                logging.getLogger(__name__).exception("Token-Refresh fehlgeschlagen")
                err = f"{type(e).__name__}: {e}\n\n{traceback.format_exc()}"
                self.root.after(0, lambda: themed_showinfo(
                    self.root, "Token-Refresh fehlgeschlagen", err
                ))

        threading.Thread(target=worker, daemon=True).start()

    def _proactive_sender_email_fetch(self):
        """Holt einmalig pro App-Start die authentifizierte E-Mail-Adresse über
        das OAuth2-Userinfo-Endpoint und cached sie in `settings.sender_email`.

        Schlägt still fehl, wenn kein Token, kein Netz oder der userinfo.email-
        Scope dem Token noch nicht gewährt wurde — der nächste Send-Dialog
        triggert dann den OAuth-Re-Consent, und beim nächsten App-Start klappt
        es. So bekommt der User nichts mit, wenn alles funktioniert.
        """
        token_path = os.path.join(self.base_path, "token.json")
        if not os.path.exists(token_path):
            return

        def worker():
            try:
                email = fetch_user_email(
                    token_path,
                    sync_enabled=self.settings.get("sync_enabled"),
                    gcal_enabled=self.settings.get("gcal_enabled"),
                )
            except Exception:
                logging.getLogger(__name__).exception("sender_email-Fetch fehlgeschlagen")
                return
            if email and email != self.settings.get("sender_email"):
                self.root.after(0, lambda: self.settings.set("sender_email", email))

        threading.Thread(target=worker, daemon=True).start()

    def _proactive_update_check(self):
        """Fragt einmal pro Kalendertag GitHub nach einer neueren Version.

        Der HTTP-Call läuft in einem Daemon-Thread; alle State-Mutationen
        (Settings-Write, Banner-Aufbau) werden via `root.after(0, ...)` auf
        den UI-Thread marshallt, damit `Settings.set` nicht parallel zu
        Schreibvorgängen aus dem Settings-Dialog läuft.

        Fehler werden still verschluckt — Update-Hinweis ist nice-to-have.
        """
        if not should_check_today(self.settings.get("last_update_check_at")):
            return

        def worker():
            try:
                release = check_latest_release("MargenHeld/Zeiterfassung")
                if release is None:
                    return
                newer = is_newer(VERSION, release.version)
            except Exception:
                # Pure Logik, robust gegen exotische Tags. Bei jedem Fehler:
                # nichts persistieren, nichts anzeigen — morgen nochmal probieren.
                # Trace landet im Logfile, falls jemand den Fehler diagnostizieren will.
                logging.getLogger(__name__).exception("Update-Check fehlgeschlagen")
                return
            self.root.after(
                0, lambda: self._handle_update_check_result(release, newer)
            )

        threading.Thread(target=worker, daemon=True).start()

    def _reservations_active(self):
        """True, wenn Reservierungen angezeigt/bearbeitet werden dürfen: ein
        Store existiert UND der Google-Kalender-Sync ist in den Settings aktiv.
        Bei deaktiviertem Sync werden Reservierungen weder im Kalender
        gerendert noch im Tages-Dialog angeboten."""
        return (self.reservation_store is not None
                and bool(self.settings.get("gcal_enabled")))

    def _proactive_calendar_reconcile(self):
        """Gleicht beim App-Start die Reservierungen mit dem Google Kalender ab.

        Läuft im Hintergrund. Fehler werden STILL geloggt (ein Offline-Start
        darf nicht nerven — analog Token-Refresh/Update-Check).
        """
        if not self._reservations_active():
            return

        def worker():
            from src.main import run_calendar_reconcile
            result = run_calendar_reconcile(
                self.reservation_store, self.settings, self.base_path)
            if result.get("ok"):
                self.root.after(0, self._refresh)

        threading.Thread(target=worker, daemon=True).start()

    def _trigger_calendar_reconcile(self):
        """Stößt nach einer Reservierungsänderung den Kalender-Abgleich an.

        Fehler werden hier ALS MESSAGEBOX gezeigt — der User hat aktiv
        gespeichert und erwartet Feedback (CLAUDE.md: Sendepfad-Fehler sichtbar).
        """
        if not self._reservations_active():
            return

        def worker():
            from src.main import run_calendar_reconcile
            result = run_calendar_reconcile(
                self.reservation_store, self.settings, self.base_path)
            self.root.after(0, lambda: self._on_reconcile_done(result))

        threading.Thread(target=worker, daemon=True).start()

    def _on_reconcile_done(self, result):
        if not result.get("ok"):
            error = result.get("error", "?")
            if _classify_sync_error(error) == "auth":
                themed_showinfo(
                    self.root,
                    "Google-Verbindung abgelaufen",
                    "Die Reservierung wurde lokal gespeichert. Der "
                    "Kalender-Abgleich ist fehlgeschlagen, weil die Verbindung "
                    "zu Google abgelaufen oder widerrufen wurde.\n\nBitte "
                    "verbinde die App in den Einstellungen neu (Google-Kalender "
                    "aus- und wieder einschalten). Der Abgleich wird danach "
                    "automatisch nachgeholt.",
                )
            else:
                messagebox.showerror(
                    "Google-Kalender-Abgleich fehlgeschlagen",
                    f"Die Reservierung wurde lokal gespeichert, der Kalender-Abgleich "
                    f"ist aber fehlgeschlagen:\n\n{error}\n\n"
                    f"{result.get('tb', '')}\n\n"
                    "Der Abgleich wird beim nächsten Start erneut versucht.",
                )
        self._refresh()

    def _handle_update_check_result(self, release: "Release", newer: bool):
        """Läuft im UI-Thread. Persistiert den Check-Stand und zeigt ggf. den Banner.

        `is_newer` ist bereits im Worker ausgewertet, damit hier keine ungeschützte
        Logik im Tk-Event-Loop läuft.
        """
        self.settings.set("last_update_check_at", today_iso())
        if not newer:
            return
        if release.version == self.settings.get("dismissed_version"):
            return
        self._show_update_banner(release)

    def _show_update_banner(self, release: "Release"):
        if self._update_banner is not None:
            return
        self._update_banner = tk.Frame(self.root, bg=ACCENT)
        self._update_banner.pack(
            before=self.grid_container, fill=tk.X, padx=10, pady=(5, 0),
        )

        tk.Label(
            self._update_banner,
            text=f"Version {release.version} verfügbar",
            bg=ACCENT, fg="#ffffff", font=FONT_BOLD,
        ).pack(side=tk.LEFT, padx=10, pady=6)

        dismiss_btn = label_button(
            self._update_banner, "✕",
            lambda: self._dismiss_update_banner(release.version),
            bg=ACCENT, fg="#ffffff",
            hover_bg=ACCENT_HOVER, hover_fg="#ffffff",
            font=FONT_BOLD,
            label_padx=8,
        )
        dismiss_btn.pack(side=tk.RIGHT, padx=(0, 4), pady=6)
        attach_tooltip(dismiss_btn, "Diese Version ausblenden")

        label_button(
            self._update_banner, "Download",
            lambda: self._open_update_download(release),
            bg="#ffffff", fg=ACCENT,
            hover_bg="#f0f0f0", hover_fg=ACCENT_HOVER,
            font=FONT_BOLD,
            label_padx=14, label_pady=2,
        ).pack(side=tk.RIGHT, padx=8, pady=4)

    def _open_update_download(self, release: "Release"):
        url = pick_asset_url(
            release.assets, platform.system(), release.version,
        ) or release.html_url
        webbrowser.open(url)

    def _dismiss_update_banner(self, version: str):
        self.settings.set("dismissed_version", version)
        if self._update_banner is not None:
            self._update_banner.destroy()
            self._update_banner = None

    def _build_header(self):
        frame = tk.Frame(self.root, bg=BG)
        frame.pack(fill=tk.X, padx=10, pady=(10, 0))
        self.header_frame = frame

        # H\u00f6hen-Anker: leeres Label mit FONT_HEADER. H\u00e4lt die Header-Reihe auf
        # konstanter H\u00f6he (= Lineh\u00f6he von FONT_HEADER), damit Toggle- und
        # Icon-Buttons beim View-Wechsel nicht vertikal springen \u2014 das
        # header_label wechselt zwischen 16pt (Monat) und 12pt (Woche), und
        # die Reihenh\u00f6he folgt sonst dem gr\u00f6\u00dften Kind.
        tk.Label(frame, text="", font=FONT_HEADER, bg=BG, width=0).pack(side=tk.LEFT)

        icon_button(frame, "\u2039", self._prev).pack(side=tk.LEFT)

        toggle_frame = tk.Frame(frame, bg=BG)
        toggle_frame.pack(side=tk.LEFT, padx=10)

        self.btn_month = toggle_button(
            toggle_frame, "Monat", lambda: self._set_view("month"), active=True,
        )
        self.btn_month.pack(side=tk.LEFT, padx=(0, 1))

        self.btn_week = toggle_button(
            toggle_frame, "Woche", lambda: self._set_view("week"), active=False,
        )
        self.btn_week.pack(side=tk.LEFT)

        # font und width werden in _refresh() je nach View gesetzt — fixe
        # width verhindert Pack-Reflow beim Text-Wechsel innerhalb derselben
        # View, und die Wochen-Variante braucht eine kleinere Schrift, weil
        # das KW-Label sonst breiter als das Fenster ist.
        self.header_label = tk.Label(
            frame, text="", bg=BG, fg="#ffffff",
        )
        self.header_label.pack(side=tk.LEFT, expand=True)

        icon_button(
            frame, "\u2699", self._open_settings,
            fg=TEXT_MUTED, hover_fg=TEXT,
        ).pack(side=tk.RIGHT)

        self._next_button = icon_button(frame, "\u203a", self._next)
        self._next_button.pack(side=tk.RIGHT, padx=(0, 5))

        # --- Sync-Button und Status (Multi-Device-Sync) ---
        # Widgets werden erzeugt, aber nur gepackt wenn sync_enabled. Sync
        # ist opt-in; bei deaktiviertem Sync soll der Header unver\u00e4ndert wirken.
        self.sync_button = icon_button(frame, "\u27f3", self._on_sync_clicked)
        self.sync_status_label = tk.Label(frame, text="", bg=BG, fg=TEXT_MUTED, font=FONT_SMALL)
        self._update_sync_status_label()

    def _build_grid(self):
        # Double-Buffer: zwei dauerhafte Frames im selben Grid-Slot. Refresh
        # baut in den inaktiven (versteckt unter dem aktiven), dann lift()
        # tauscht atomar. So nie sichtbar leerer Hintergrund zwischen Destroy
        # und Pack.
        self.grid_container = tk.Frame(self.root, bg=BG)
        self.grid_container.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        self.grid_container.rowconfigure(0, weight=1)
        self.grid_container.columnconfigure(0, weight=1)
        self.grid_frames = []
        for _ in range(2):
            f = tk.Frame(self.grid_container, bg=BG)
            f.grid(row=0, column=0, sticky="nsew")
            for col in range(7):
                f.columnconfigure(col, weight=1)
            self.grid_frames.append(f)
        self.grid_frames[0].lift()
        self._active_grid_idx = 0
        self.grid_frame = self.grid_frames[0]  # Alias auf aktiven Frame

    def _build_footer(self):
        footer_frame = tk.Frame(self.root, bg=BG)
        footer_frame.pack(fill=tk.X, padx=10, pady=(0, 10))

        # width fixiert reqwidth → kein Pack-Reflow, wenn sich die Stunden-/
        # Brutto-Summe beim Monatswechsel ändert. 40 deckt die längste
        # Variante ab ("Gesamt: 999.99h  —  99999.99 € brutto" ≈ 38 Zeichen).
        self.footer_label = tk.Label(
            footer_frame, text="Gesamt: 0.0h", font=FONT_FOOTER,
            bg=BG, fg=ACCENT, width=40,
        )
        self.footer_label.pack(side=tk.LEFT, expand=True)

        secondary_button(
            footer_frame, "Teilen…", self._share, padx=12,
        ).pack(side=tk.RIGHT, padx=(0, 4))
        secondary_button(
            footer_frame, "Monat senden", self._send, padx=12,
        ).pack(side=tk.RIGHT)

    def _prev(self):
        if self.view_mode == "month":
            if self.month == 1:
                self.month = 12
                self.year -= 1
            else:
                self.month -= 1
        else:
            dates = get_week_dates(self.iso_year, self.current_week)
            prev_monday = dates[0] - datetime.timedelta(days=7)
            iso = prev_monday.isocalendar()
            self.iso_year = iso[0]
            self.current_week = iso[1]
        self._refresh()

    def _next(self):
        if self.view_mode == "month":
            if self.month == 12:
                self.month = 1
                self.year += 1
            else:
                self.month += 1
        else:
            dates = get_week_dates(self.iso_year, self.current_week)
            next_monday = dates[0] + datetime.timedelta(days=7)
            iso = next_monday.isocalendar()
            self.iso_year = iso[0]
            self.current_week = iso[1]
        self._refresh()

    def _on_tab_toggle_view(self, _event=None):
        self._set_view("week" if self.view_mode == "month" else "month")
        return "break"

    def _measure_max_width(self):
        """Pre-warm: rendert alle 4 (view × show_weekend)-Kombinationen einmal
        in den versteckten Backbuffer und gibt die maximale reqwidth zurück.
        Läuft vor `mainloop()` — Zwischenzustände sind nie sichtbar.

        Settings werden direkt über `_data` mutiert (kein Disk-Save) und am
        Ende wiederhergestellt. `_suppress_geometry` verhindert den
        Resize-Call im _refresh-Pfad während der Messung.
        """
        saved_view = self.view_mode
        saved_weekend = self.settings.get("show_weekend")
        max_w = 0
        self._suppress_geometry = True
        try:
            for view in ("month", "week"):
                for weekend in (True, False):
                    self.view_mode = view
                    self.settings._data["show_weekend"] = weekend
                    # Force-rebuild über Tracking-Reset — sonst greift der
                    # view_changed/cols_changed-Shortcut in _refresh.
                    self._last_refresh_view = None
                    self._last_refresh_columns = None
                    self._refresh()
                    self.root.update_idletasks()
                    w = self.root.winfo_reqwidth()
                    if w > max_w:
                        max_w = w
        finally:
            self._suppress_geometry = False
            self.view_mode = saved_view
            self.settings._data["show_weekend"] = saved_weekend
            self._last_refresh_view = None
            self._last_refresh_columns = None
        return max_w

    def _set_view(self, mode):
        if mode == self.view_mode:
            return
        today = datetime.date.today()
        if mode == "week":
            iso = today.isocalendar()
            self.iso_year = iso[0]
            self.current_week = iso[1]
        else:
            self.year = today.year
            self.month = today.month
        self.view_mode = mode
        self._update_toggle_style()
        self._refresh()

    def _update_toggle_style(self):
        set_toggle_active(self.btn_month, self.view_mode == "month")
        set_toggle_active(self.btn_week, self.view_mode == "week")

    def _open_settings(self):
        def _on_change():
            self._refresh()
            self._update_sync_status_label()
            self._apply_always_on_top()
            self._apply_tray_setting()
            # Nach jeder Settings-Speicherung den sender_email-Fetch nochmal
            # anstoßen. Damit erscheint die Absender-Adresse automatisch nach
            # Sync-Aktivierung (frischer Token mit userinfo.email-Scope), ohne
            # dass der User den "Aktualisieren"-Button drücken muss.
            self._proactive_sender_email_fetch()
        open_settings_dialog(
            self.root, self.settings, self.base_path,
            on_change=_on_change,
            conflicts_store=self.conflicts_store,
            storage=self.storage,
            reservation_store=self.reservation_store,
        )

    def _apply_always_on_top(self):
        """Tk-übergreifender Topmost-Toggle. Funktioniert auf Windows, macOS
        und Linux (X11/Wayland mit gängigen WMs) identisch — kein OS-Sniffing
        nötig. Bei deaktivierter Option wird das Attribut explizit auf False
        gesetzt, damit ein Toggle wirklich zurücksetzt."""
        try:
            self.root.attributes("-topmost", bool(self.settings.get("always_on_top")))
        except tk.TclError:
            # Sehr exotische WMs ohne topmost-Unterstützung — silently ignore.
            pass

    def _apply_tray_setting(self):
        """Startet oder stoppt das Tray-Icon abhängig vom Settings-Toggle.

        Auf Linux unterstützen wir Tray bewusst nicht — pystray-Backend ist
        je nach Desktop-Umgebung unzuverlässig. Wenn das Setup auf Win/macOS
        fehlschlägt (z.B. fehlende Lib im Frozen-Build), wird ein Toast
        gezeigt und das Feature deaktiviert.
        """
        from src.tray import TrayIcon, is_supported

        want_tray = bool(self.settings.get("minimize_to_tray"))

        if want_tray and self._tray is None:
            if not is_supported():
                messagebox.showinfo(
                    "Infobereich-Icon",
                    "Das Minimieren in den Infobereich ist auf dieser Plattform "
                    "nicht zuverlässig nutzbar (typisch Linux). Option wurde "
                    "wieder deaktiviert.",
                )
                self.settings.set("minimize_to_tray", False)
                return
            tray = TrayIcon(
                self.base_path,
                on_show=lambda: self.root.after(0, self._restore_from_tray),
                on_quit=lambda: self.root.after(0, self._quit_with_sync_push),
                actions=[
                    ("Monat senden",
                     lambda: self.root.after(0, self._send), None),
                    ("Teilen…",
                     lambda: self.root.after(0, self._share), None),
                    ("Mit Google Drive synchronisieren",
                     lambda: self.root.after(0, self._tray_sync),
                     lambda: bool(self.settings.get("sync_enabled"))),
                ],
            )
            try:
                tray.start()
            except Exception as e:
                logging.getLogger(__name__).exception("Tray-Start fehlgeschlagen")
                messagebox.showerror(
                    "Infobereich-Icon",
                    f"Tray-Icon konnte nicht gestartet werden:\n\n{e}",
                )
                self.settings.set("minimize_to_tray", False)
                return
            self._tray = tray

        elif not want_tray and self._tray is not None:
            self._tray.stop()
            self._tray = None

    def _restore_from_tray(self):
        """Bringt das Fenster aus dem `withdraw()`-Zustand zurück."""
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()

    def _refresh(self):
        if self.view_mode == "month":
            # FONT_HEADER (16pt) + width=16 — längste Variante "September 2026"
            # (14 Zeichen) passt rein.
            self.header_label.config(
                text=f"{MONTHS_DE[self.month]} {self.year}",
                font=FONT_HEADER, width=16,
            )
            self._refresh_month()
        else:
            # FONT_HEADER_SMALL (12pt) + width=32 — die längste Variante
            # mit Jahreswechsel "KW 53 · 30.12.2025 – 05.01.2026" (31 Zeichen)
            # passt in 16pt nicht ins Fenster (7 × Standardzelle), daher
            # in der Wochenansicht kleinerer Header-Font.
            self.header_label.config(
                text=get_week_label(self.iso_year, self.current_week),
                font=FONT_HEADER_SMALL, width=32,
            )
            self._refresh_week()
        # Geometry nur beim First-Render, bei View-Wechsel und bei Wechsel der
        # sichtbaren Spaltenzahl (show_weekend-Toggle) neu setzen. Innerhalb
        # derselben Kombination ist die natürliche Größe konstant; ein erneuter
        # `geometry("")`-Aufruf triggert trotzdem einen WM-Repaint und erzeugt
        # sichtbares Flackern.
        current_cols = self._visible_day_count()
        view_changed = getattr(self, "_last_refresh_view", None) != self.view_mode
        cols_changed = getattr(self, "_last_refresh_columns", None) != current_cols
        if view_changed or cols_changed:
            self._last_refresh_view = self.view_mode
            self._last_refresh_columns = current_cols
            # Beim View- oder Spalten-Wechsel hält der jetzt-inaktive Buffer
            # noch den alten Layout-Stand. Children destroyen + rowconfigure
            # zurücksetzen reicht NICHT: Tk's reqheight-Cache des Frames bleibt
            # auf der alten Höhe, `grid_container.reqheight = max(active,
            # inactive)` zieht das Window-Resize hoch. Den Inactive-Frame
            # komplett ersetzen umgeht den Cache — frischer Frame hat
            # reqheight = 0.
            inactive_idx = 1 - self._active_grid_idx
            self.grid_frames[inactive_idx].destroy()
            new_inactive = tk.Frame(self.grid_container, bg=BG)
            new_inactive.grid(row=0, column=0, sticky="nsew")
            for col in range(7):
                new_inactive.columnconfigure(col, weight=1 if col < current_cols else 0)
            self.grid_frames[inactive_idx] = new_inactive
            # Frisch erstellter Frame liegt in der Stacking-Order obenauf und
            # würde den aktiven Frame verdecken — active wieder nach vorn.
            self.grid_frames[self._active_grid_idx].lift()
            self.root.update_idletasks()
            # Tk schrumpft Toplevels auf Windows nicht zuverlässig via
            # `geometry("")` — explizit auf reqsize setzen erzwingt Resize.
            # Breite wird auf den beim Start gemessenen Max-Wert gepinnt,
            # damit View-/Weekend-Toggle die Fensterbreite nicht ändern.
            # Während der Initial-Messung (_measure_max_width) suppress geometry,
            # sonst flackert das Fenster beim Probing.
            if not getattr(self, "_suppress_geometry", False):
                width = max(
                    getattr(self, "_fixed_width", 0),
                    self.root.winfo_reqwidth(),
                )
                self.root.geometry(
                    f"{width}x{self.root.winfo_reqheight()}"
                )

    def _visible_day_count(self):
        """Sichtbare Wochentag-Spalten (5 bei show_weekend=False, sonst 7).

        Wird von _build_grid_header und den Refresh-Pfaden als einzige
        Quelle der Wahrheit konsultiert.
        """
        return 7 if self.settings.get("show_weekend") else 5

    def _build_grid_header(self, parent):
        n = self._visible_day_count()
        for col, day_name in enumerate(DAYS_DE[:n]):
            fg = TEXT_MUTED if col < 5 else WEEKEND_FG
            tk.Label(
                parent, text=day_name, font=FONT_BOLD, bg=BG, fg=fg,
            ).grid(row=0, column=col, sticky="nsew", padx=2, pady=2)

    def _build_entry_cell(self, parent, date_str, day_text, entry, is_weekend, pad,
                          cell_size=None, time_font=FONT_TINY):
        bg = WEEKEND_ENTRY_BG if is_weekend else ENTRY_BG
        hover_bg = WEEKEND_ENTRY_BG_HOVER if is_weekend else ENTRY_BG_HOVER
        cell = tk.Frame(
            parent, bg=bg, relief=tk.SOLID,
            highlightbackground=ACCENT, highlightthickness=1, cursor="hand2",
        )
        if cell_size is not None:
            # Pixel-fixiert wie die Feiertagszelle — sonst weitet die Zeit-Zeile
            # ("HH:MM-HH:MM" in FONT_SMALL) die Spalte auf und der Header-Reflow
            # lässt den Monatsnamen flackern, sobald Einträge dazukommen.
            cell.config(width=cell_size[0], height=cell_size[1])
            cell.pack_propagate(False)
        day_lbl = tk.Label(
            cell, text=day_text, font=FONT,
            bg=bg, fg=TEXT, cursor="hand2",
        )
        day_lbl.pack(pady=(pad, 0))
        # time_font default FONT_TINY (7pt) damit "HH:MM-HH:MM" in die
        # pixel-fixierte Standardzelle (width=8 in FONT) reinpasst. Wenn der
        # Caller eine breitere Zelle nutzt (z.B. bei ausgeblendeten Wochenenden
        # mit width=11), kann eine größere Schrift übergeben werden.
        time_lbl = tk.Label(
            cell, text=f"{entry['start']}-{entry['end']}",
            font=time_font, bg=bg, fg=TEXT_MUTED, cursor="hand2",
        )
        time_lbl.pack(pady=(0, pad))
        for w in (cell, day_lbl, time_lbl):
            w.bind("<Button-1>", lambda e, d=date_str: self._open_dialog(d))
            w.bind("<Button-3>", lambda e, d=date_str: self._delete_day(d))
            w.bind("<Enter>", lambda e, c=cell, dl=day_lbl, tl=time_lbl, hb=hover_bg: self._cell_hover(c, dl, tl, hb))
            w.bind("<Leave>", lambda e, c=cell, dl=day_lbl, tl=time_lbl, ob=bg: self._cell_hover(c, dl, tl, ob))
        return cell

    def _add_reservation_marker(self, cell):
        """Runder violetter Eck-Punkt auf einer Ist-Zeitzelle, die zusätzlich
        eine Reservierung hat. Ein Canvas-Oval statt eines Text-Bullets — „•"
        rendert je nach Font als kaum sichtbarer Fleck; das Oval gibt einen
        sauber gerundeten, größenkontrollierten Punkt. place() überlagert die
        gepackten Kind-Widgets. Der Marker wird als cell._reservation_marker
        getaggt, damit _cell_hover seinen Hintergrund beim Hover mitfärbt."""
        box, dot = 12, 7
        marker = tk.Canvas(
            cell, width=box, height=box, bg=cell.cget("bg"),
            highlightthickness=0, cursor="hand2",
        )
        inset = (box - dot) // 2
        marker.create_oval(
            inset, inset, inset + dot, inset + dot,
            fill=RESERVATION_ACCENT, outline="",
        )
        marker.place(relx=1.0, x=-3, y=3, anchor="ne")
        cell._reservation_marker = marker

    def _build_empty_cell(self, parent, date_str, day_text, is_weekend, cell_size):
        bg = WEEKEND_BG if is_weekend else CELL_BG
        hover_bg = WEEKEND_BG_HOVER if is_weekend else CELL_BG_HOVER
        fg = WEEKEND_FG if is_weekend else TEXT
        # Pixel-fixiert auf dieselbe Außengröße wie Entry-/Holiday-Zellen, damit
        # die per sticky="nsew"+weight gestreckten Spalten unabhängig vom Inhalt
        # gleich breit bleiben.
        # Breite OHNE Aufschlag: die reqwidth muss exakt der der gefüllten Zellen
        # entsprechen (die mit width=cell_size[0]+highlightthickness=1 gebaut
        # werden). Tk zählt den 1-px-Highlight-Rand hier NICHT zur reqwidth, also
        # ist deren reqwidth ebenfalls cell_size[0]. Ein früher gesetztes +2
        # machte leere Spalten 2 px breiter als Eintragsspalten — in der
        # Wochenansicht (1 Zelle pro Spalte) verschob das die Spaltenbreiten
        # gegenüber der Monatsansicht (dort mittelt sich der Unterschied über die
        # 6 Zeilen weg). Höhe +2 kompensiert den Rand der gefüllten Zellen
        # vertikal und betrifft die Spaltenbreite nicht.
        cell = tk.Frame(parent, bg=bg, cursor="hand2")
        cell.config(width=cell_size[0], height=cell_size[1] + 2)
        cell.pack_propagate(False)
        day_lbl = tk.Label(
            cell, text=day_text, font=FONT, bg=bg, fg=fg, cursor="hand2",
        )
        day_lbl.pack(expand=True)
        for w in (cell, day_lbl):
            w.bind("<Button-1>", lambda e, d=date_str: self._open_dialog(d))
            w.bind("<Button-3>", lambda e, d=date_str: self._delete_day(d))
            w.bind("<Enter>", lambda e, c=cell, dl=day_lbl, hb=hover_bg: self._empty_hover(c, dl, hb))
            w.bind("<Leave>", lambda e, c=cell, dl=day_lbl, ob=bg: self._empty_hover(c, dl, ob))
        return cell

    def _build_day_cell(self, parent, date_str, day_text, day_date, is_weekend,
                        entry, holidays_map, pad,
                        holiday_max_len, cell_size, conflict_dates=None,
                        entry_time_font=FONT_TINY, holiday_name_font=FONT_SMALL,
                        reservation=None):
        """Dispatcht auf Entry-, Holiday- oder Empty-Zelle.

        reservation: optionales {start, end} für den Tag. Eine Reservierung
        ändert den Zelltyp NICHT — sie wird ausschließlich als kleiner
        violetter Eck-Punkt (plus Tooltip) auf die ohnehin gebaute Zelle
        gelegt. Ein Tag mit nur einer Reservierung sieht also aus wie ein
        leerer Tag (bzw. Feiertag) mit Punkt.
        """
        is_holiday = day_date in holidays_map
        if entry:
            cell = self._build_entry_cell(
                parent, date_str, day_text, entry, is_weekend, pad,
                cell_size=cell_size, time_font=entry_time_font,
            )
        elif is_holiday:
            cell = self._build_holiday_cell(
                parent, day_text=day_text,
                name=holidays_map[day_date], max_name_len=holiday_max_len,
                on_click=lambda d=date_str: self._open_dialog(d),
                on_right_click=lambda d=date_str: self._delete_day(d),
                cell_size=cell_size,
                name_font=holiday_name_font,
                # Bei zusätzlicher Reservierung übernimmt der Reservierungs-
                # Tooltip unten den Feiertagsnamen — sonst klebten zwei
                # unabhängige Tooltips am selben Widget (s. attach_tooltip).
                name_tooltip=reservation is None,
            )
        else:
            cell = self._build_empty_cell(
                parent, date_str, day_text, is_weekend, cell_size,
            )

        # Reservierung ist ein reiner Overlay-Marker (Eck-Punkt) — sie ändert
        # den Zelltyp nicht. Genau ein attach_tooltip pro Zelle: Mehrfachaufruf
        # erzeugt überlappende Tooltips (s. attach_tooltip-Docstring).
        if reservation is not None:
            self._add_reservation_marker(cell)
            tip = f"Reservierung: {reservation['start']}-{reservation['end']}"
            if is_holiday:
                tip += f"\nFeiertag: {holidays_map[day_date]}"
            attach_tooltip(cell, tip)
        elif entry and is_holiday:
            attach_tooltip(cell, f"Feiertag: {holidays_map[day_date]}")

        # Heutigen Tag mit blauem Rahmen hervorheben. Vor dem Konflikt-Block,
        # damit ein Konflikt (orange) auf demselben Tag den Rand gewinnt.
        if day_date == datetime.date.today():
            cell.configure(highlightbackground=TODAY_ACCENT, highlightthickness=2)

        if conflict_dates and date_str in conflict_dates:
            cell.configure(highlightbackground="orange", highlightthickness=2)
            attach_tooltip(cell, "Konflikt — bitte auflösen")

        return cell

    def _get_inactive_grid(self):
        """Liefert das versteckte Grid-Frame (Double-Buffer-Backbuffer).
        Children, Row- und Column-Config werden zurückgesetzt. Nur sichtbare
        Spalten erhalten weight=1 — ausgeblendete (Sa/So bei show_weekend=False)
        würden sonst den vom Header/Footer geforderten Extra-Platz absorbieren
        und einen Leerraum-Streifen rechts neben Fr produzieren."""
        inactive = self.grid_frames[1 - self._active_grid_idx]
        for child in list(inactive.winfo_children()):
            child.destroy()
        for row in range(8):
            inactive.rowconfigure(row, minsize=0, weight=0)
        n = self._visible_day_count()
        for col in range(7):
            inactive.columnconfigure(col, weight=1 if col < n else 0)
        return inactive

    def _activate_grid(self, frame):
        """Hebt das eben gefüllte Backbuffer-Frame nach vorne. Der bisherige
        Front-Buffer bleibt als Backbuffer hinten — keine Destroy-Lücke."""
        frame.lift()
        self._active_grid_idx = 1 - self._active_grid_idx
        self.grid_frame = frame

    def _update_footer(self, total_hours):
        rate = self.settings.get("hourly_rate") or 0
        total_rounded = round(total_hours, 2)
        if rate > 0:
            brutto = round(total_hours * rate, 2)
            self.footer_label.config(
                text=f"Gesamt: {total_rounded}h  —  {brutto:.2f} € brutto"
            )
        else:
            self.footer_label.config(text=f"Gesamt: {total_rounded}h")

    def _entry_hours(self, entry):
        return calculate_hours(
            entry["start"], entry["end"], pause_minutes=entry.get("pause", 0),
        )

    def _dates_with_unresolved_conflicts(self):
        """Gibt die Menge der ISO-Datums-Strings zurück, für die ungelöste
        Konflikte vom Typ 'entry' vorliegen."""
        if not self.conflicts_store:
            return set()
        return {
            c["key"] for c in self.conflicts_store.get_all()
            if c.get("kind") == "entry" and not c.get("resolved")
        }

    def _refresh_month(self):
        # In den versteckten Backbuffer bauen, dann via lift() in den Vordergrund
        # holen — verhindert sichtbare leere Fläche zwischen Refreshes.
        new_frame = self._get_inactive_grid()
        self._build_grid_header(new_frame)

        cal = calendar.Calendar(firstweekday=0)
        entries = self.storage.get_all()
        reservations = (
            self.reservation_store.get_all() if self._reservations_active() else {})
        total_hours = 0.0

        state = self.settings.get("state")
        holidays_map = get_holidays(state, self.year) if state else {}

        # Probe-Label, um die natürliche Pixel-Größe einer Standard-Tageszelle
        # zu ermitteln. Wird genutzt für:
        #  (a) Feiertagszellen pixel-fixieren — sonst weiten lange Feiertags-
        #      namen die Spalte auf, das Grid wächst und der Header-Reflow
        #      lässt den Monatsnamen flackern.
        #  (b) konstante Reihenhöhe (minsize unten), damit gepaddete Wochen
        #      ohne Content nicht zusammenklappen.
        # Bei ausgeblendeten Wochenenden (5 Spalten statt 7) bleibt mehr
        # Horizontalplatz pro Spalte — Zellen werden breiter, damit die
        # Zeit-Zeile in FONT_SMALL statt FONT_TINY lesbar dargestellt wird.
        wide_cells = not self.settings.get("show_weekend")
        probe_width = 12 if wide_cells else 8
        # FONT_SMALL (8pt) statt FONT_TINY (7pt) im 7-Spalten-Modus — Spalten
        # werden durch sticky="nsew" + columnconfigure(weight=1) über die
        # Probe-Breite hinaus gestreckt, sodass "09:30-17:00" auch in 8pt
        # bequem reinpasst und besser lesbar bleibt.
        entry_time_font = FONT if wide_cells else FONT_SMALL
        holiday_name_font = FONT if wide_cells else FONT_SMALL
        probe = tk.Label(new_frame, text="", font=FONT, width=probe_width, height=3)
        probe.update_idletasks()
        cell_size = (probe.winfo_reqwidth(), probe.winfo_reqheight())
        probe.destroy()

        # Auf 6 Wochen padden, damit die Fensterhöhe zwischen Monaten konstant
        # bleibt und `geometry("")` in `_refresh` keinen sichtbaren Resize auslöst.
        n = self._visible_day_count()
        weeks = cal.monthdayscalendar(self.year, self.month)
        # Bei ausgeblendetem Wochenende: führende Wochen verwerfen, deren
        # sichtbarer Anteil (Mo–Fr) komplett aus 0 besteht — sonst entsteht
        # eine sichtbar leere erste Zeile, wenn der Monat am Sa/So beginnt.
        if n < 7:
            while weeks and not any(weeks[0][:n]):
                weeks.pop(0)
        while len(weeks) < 6:
            weeks.append([0] * 7)

        # Einmal pro Render berechnen, nicht pro Zelle.
        conflict_dates = self._dates_with_unresolved_conflicts()

        for row, week in enumerate(weeks, start=1):
            for col, day in enumerate(week[:n]):
                if day == 0:
                    tk.Label(new_frame, text="", bg=BG, relief=tk.FLAT).grid(
                        row=row, column=col, sticky="nsew", padx=2, pady=2)
                    continue

                date_str = f"{self.year}-{self.month:02d}-{day:02d}"
                day_date = datetime.date(self.year, self.month, day)
                entry = entries.get(date_str)
                if entry:
                    total_hours += self._entry_hours(entry)

                cell = self._build_day_cell(
                    new_frame, date_str, str(day), day_date,
                    is_weekend=col >= 5, entry=entry, holidays_map=holidays_map,
                    pad=4,
                    # Bei schmalen Zellen (7-Spalten-Modus) kürzer trunkieren,
                    # damit der padx=4-Innenraum der Holiday-Zelle erhalten bleibt.
                    holiday_max_len=12 if wide_cells else 9,
                    cell_size=cell_size,
                    conflict_dates=conflict_dates,
                    entry_time_font=entry_time_font,
                    holiday_name_font=holiday_name_font,
                    reservation=reservations.get(date_str),
                )
                cell.grid(row=row, column=col, sticky="nsew", padx=2, pady=2)

        row_min_h = cell_size[1] + 4  # +4 für pady=2 oben/unten
        for row in range(1, 7):
            new_frame.rowconfigure(row, minsize=row_min_h)

        self._activate_grid(new_frame)
        self._update_footer(total_hours)

    def _refresh_week(self):
        new_frame = self._get_inactive_grid()
        self._build_grid_header(new_frame)

        dates = get_week_dates(self.iso_year, self.current_week)
        entries = self.storage.get_all()
        reservations = (
            self.reservation_store.get_all() if self._reservations_active() else {})
        total_hours = 0.0
        spans = week_spans_months(self.iso_year, self.current_week)
        state = self.settings.get("state")
        holidays_map: dict[datetime.date, str] = {}
        if state:
            for y in {dates[0].year, dates[-1].year}:
                holidays_map.update(get_holidays(state, y))

        # Probe-Label, um die natürliche Pixel-Größe einer Standard-Wochenzelle
        # zu ermitteln. Holiday-Zellen werden auf diese Größe fixiert, damit
        # längere Feiertagsnamen die Spalte nicht aufweiten.
        # Bei ausgeblendeten Wochenenden: breitere Zellen + größere Time-Schrift.
        wide_cells = not self.settings.get("show_weekend")
        probe_width = 12 if wide_cells else 8
        entry_time_font = FONT if wide_cells else FONT_SMALL
        holiday_name_font = FONT if wide_cells else FONT_SMALL
        probe = tk.Label(new_frame, text="", font=FONT, width=probe_width, height=3)
        probe.update_idletasks()
        cell_size = (probe.winfo_reqwidth(), probe.winfo_reqheight())
        probe.destroy()

        n = self._visible_day_count()
        # Einmal pro Render berechnen, nicht pro Zelle.
        conflict_dates = self._dates_with_unresolved_conflicts()

        for col, day_date in enumerate(dates[:n]):
            date_str = day_date.isoformat()
            entry = entries.get(date_str)
            if entry:
                total_hours += self._entry_hours(entry)
            day_text = f"{day_date.day}.{day_date.month}." if spans else str(day_date.day)

            cell = self._build_day_cell(
                new_frame, date_str, day_text, day_date,
                is_weekend=col >= 5, entry=entry, holidays_map=holidays_map,
                # pad=4 wie in der Monatsansicht, damit die vertikale Anordnung
                # von Tagesziffer und Zeitzeile beim View-Wechsel nicht springt.
                pad=4,
                # 18 war zu lang für die gerenderte Spaltenbreite — "Christi
                # Himmelfa…" lief über den Zellenrand hinaus. Werte unten
                # passen zu den effektiv gestreckten Spalten in beiden Modi.
                holiday_max_len=14 if wide_cells else 12,
                cell_size=cell_size,
                conflict_dates=conflict_dates,
                entry_time_font=entry_time_font,
                holiday_name_font=holiday_name_font,
                reservation=reservations.get(date_str),
            )
            cell.grid(row=1, column=col, sticky="nsew", padx=2, pady=2)

        self._activate_grid(new_frame)
        self._update_footer(total_hours)

    @staticmethod
    def _truncate(text: str, max_len: int) -> str:
        if len(text) <= max_len:
            return text
        return text[: max_len - 1] + "…"

    def _build_holiday_cell(self, parent, day_text, name, max_name_len, on_click,
                             cell_size=None, name_font=FONT_SMALL,
                             name_tooltip=True, on_right_click=None):
        """Grüne Feiertagszelle. Layout analog zur Eintragszelle.

        cell_size: optional (width_px, height_px). Wenn gesetzt, wird der Frame
        auf diese Pixel-Größe fixiert (verhindert Aufweitung der Spalte durch
        längere Namen — relevant für die Wochenansicht).
        name_font: Schriftart für den Feiertagsnamen. Default FONT_SMALL (8pt);
        bei breiteren Zellen (Wochenenden ausgeblendet) kann FONT übergeben werden.
        name_tooltip: ob bei abgeschnittenem Namen ein Voll-Namen-Tooltip
        angehängt wird. False, wenn der Aufrufer selbst einen Tooltip setzt
        (Doppel-Tooltip am selben Widget vermeiden).
        """
        cell = tk.Frame(
            parent, bg=HOLIDAY_BG, relief=tk.SOLID,
            highlightbackground=HOLIDAY_ACCENT, highlightthickness=1,
            cursor="hand2",
        )
        if cell_size is not None:
            cell.config(width=cell_size[0], height=cell_size[1])
            cell.pack_propagate(False)
        day_lbl = tk.Label(
            cell, text=day_text, font=FONT,
            bg=HOLIDAY_BG, fg=TEXT, cursor="hand2",
        )
        day_lbl.pack(pady=(4, 0))
        truncated = self._truncate(name, max_name_len)
        name_lbl = tk.Label(
            cell, text=truncated,
            font=name_font, bg=HOLIDAY_BG, fg=TEXT_MUTED, cursor="hand2",
        )
        # padx=4 für sichtbare Innenränder, sonst klebt der Feiertagsname an
        # den Zellrändern. Caller sorgt mit passendem max_name_len dafür,
        # dass der Text in die verbleibende Breite passt.
        name_lbl.pack(pady=(0, 4), padx=4)

        for w in (cell, day_lbl, name_lbl):
            w.bind("<Button-1>", lambda e: on_click())
            if on_right_click is not None:
                w.bind("<Button-3>", lambda e: on_right_click())
            w.bind("<Enter>", lambda e, c=cell, dl=day_lbl, nl=name_lbl:
                self._cell_hover(c, dl, nl, HOLIDAY_BG_HOVER))
            w.bind("<Leave>", lambda e, c=cell, dl=day_lbl, nl=name_lbl:
                self._cell_hover(c, dl, nl, HOLIDAY_BG))
        if name_tooltip and truncated != name:
            # Geteilter Tooltip über alle drei Widgets — _Tooltip trackt sie
            # gemeinsam, sodass Pointer-Wechsel zwischen Frame und Child-
            # Labels den Tooltip nicht schließt/neu öffnet.
            attach_tooltip((cell, day_lbl, name_lbl), f"Feiertag: {name}")
        return cell

    @staticmethod
    def _cell_hover(frame, day_lbl, time_lbl, bg):
        frame.config(bg=bg)
        day_lbl.config(bg=bg)
        time_lbl.config(bg=bg)
        # Eck-Marker (nur auf Entry-Zellen mit zusätzlicher Reservierung)
        # mitfärben, sonst bleibt beim Hover ein andersfarbiges Rechteck stehen.
        marker = getattr(frame, "_reservation_marker", None)
        if marker is not None:
            marker.config(bg=bg)

    @staticmethod
    def _empty_hover(frame, day_lbl, bg):
        frame.config(bg=bg)
        day_lbl.config(bg=bg)
        # Reservierungs-Eck-Punkt mitfärben — Nur-Reservierungs-Tage sind
        # Empty-Zellen mit Marker; sonst bliebe beim Hover ein andersfarbiges
        # Rechteck hinter dem Punkt stehen.
        marker = getattr(frame, "_reservation_marker", None)
        if marker is not None:
            marker.config(bg=bg)

    def _delete_day(self, date_str):
        """Rechtsklick-Löschen für einen Tag. Löscht NIE ohne Bestätigung.

        Je nachdem, was am Tag liegt:
        - nur Arbeitszeit   → Ja/Nein-Abfrage
        - nur Reservierung  → Ja/Nein-Abfrage
        - beides            → Checkbox-Auswahl, was gelöscht werden soll

        Reservierungen werden nur berücksichtigt, wenn sie aktiv sind
        (_reservations_active); das Löschen einer Reservierung stößt den
        Kalender-Abgleich an.
        """
        entry = self.storage.get(date_str)
        reservation = (
            self.reservation_store.get(date_str)
            if self._reservations_active() else None
        )
        if entry is None and reservation is None:
            return

        date_de = format_iso_date(date_str)
        delete_entry = False
        delete_reservation = False

        if entry is not None and reservation is not None:
            choice = themed_ask_delete_choice(
                self.root, "Löschen", f"Was für den {date_de} löschen?",
                [("entry", "Arbeitszeit"), ("reservation", "Reservierung")],
            )
            if not choice:
                return
            delete_entry = "entry" in choice
            delete_reservation = "reservation" in choice
        elif entry is not None:
            if not themed_askyesno(self.root, "Arbeitszeit löschen",
                                   f"Arbeitszeit für {date_de} löschen?"):
                return
            delete_entry = True
        else:
            if not themed_askyesno(self.root, "Reservierung löschen",
                                   f"Reservierung für {date_de} löschen?"):
                return
            delete_reservation = True

        if delete_entry:
            self.storage.delete(date_str)
        if delete_reservation:
            self.reservation_store.delete(date_str)

        self._refresh()
        if delete_reservation:
            self._trigger_calendar_reconcile()

    def _open_dialog(self, date_str):
        # Bei deaktiviertem Kalender-Sync KEIN reservation_store an den Dialog
        # geben — dann wird der Reservierungs-Block nicht angezeigt und ist per
        # Linksklick nicht setzbar (open_entry_dialog wertet None entsprechend).
        open_entry_dialog(
            self.root, date_str, self.storage, self.settings,
            on_change=self._refresh,
            reservation_store=(
                self.reservation_store if self._reservations_active() else None),
            trigger_reconcile=self._trigger_calendar_reconcile,
        )

    def _send(self):
        open_send_dialog(self.root, self.storage, self.settings, self.base_path)

    def _share(self):
        from src.dialogs.share_dialog import open_share_dialog
        open_share_dialog(
            self.root, self.storage, self.settings, self.base_path,
            reservation_store=self.reservation_store,
        )

    def on_sync_pull_success(self):
        """Wird aus dem UI-Thread nach erfolgreichem Pull aufgerufen."""
        # _refresh() re-renders the full calendar grid (month or week view).
        self._refresh()
        self._update_sync_status_label()

    def on_sync_pull_error(self, error, tb=""):
        _show_sync_error(self.root, error, tb)
        self._update_sync_status_label()

    def _update_sync_status_label(self):
        if not hasattr(self, "sync_status_label"):
            return
        enabled = self.settings.get("sync_enabled")
        if not enabled:
            # Widgets verstecken, falls vorher sichtbar.
            self.sync_button.pack_forget()
            self.sync_status_label.pack_forget()
            self.sync_status_label.config(text="")
            return
        # Sichtbar machen, falls vorher versteckt. Vor dem ›-Button einsortieren,
        # damit Layout-Reihenfolge identisch zum Build-Time-Pack ist.
        if not self.sync_button.winfo_ismapped():
            self.sync_button.pack(side=tk.RIGHT, padx=(4, 0), before=self._next_button)
            self.sync_status_label.pack(
                side=tk.RIGHT, padx=(8, 4), before=self.sync_button
            )
        n = 0
        if self.conflicts_store is not None:
            n = self.conflicts_store.count_unresolved()
        if n > 0:
            self.sync_status_label.config(text=f"⚠ {n} Konflikt{'e' if n != 1 else ''}")
        else:
            shown = format_iso_date(
                self.settings.get("last_pull_at"), fallback="noch nie")
            self.sync_status_label.config(text=f"✓ {shown}")

    def _on_sync_clicked(self):
        if not self.settings.get("sync_enabled"):
            import tkinter.messagebox as mb
            mb.showinfo("Synchronisation",
                          "Synchronisation ist deaktiviert. In den Einstellungen aktivierbar.")
            return
        self.sync_status_label.config(text="Synchronisiere…")
        import threading
        from src.main import _run_push_blocking
        def _do():
            result = _run_push_blocking(
                self.storage, self.settings, self.conflicts_store,
                self.base_path, timeout_seconds=15,
            )
            self.root.after(0, lambda: self._on_manual_sync_done(result))
        threading.Thread(target=_do, daemon=True).start()

    def _on_manual_sync_done(self, result):
        if not result.get("ok"):
            _show_sync_error(
                self.root, result.get("error", "?"), result.get("tb", ""))
        # _refresh() re-renders the full calendar grid so newly detected conflict
        # markers appear immediately without requiring a manual view-change.
        self._refresh()
        self._update_sync_status_label()

    def _tray_sync(self):
        """Drive-Sync aus dem Tray-Menü. Wie _on_sync_clicked, aber das Ergebnis
        geht als Tray-Toast zurück statt ins (im Tray-Modus versteckte) Status-
        Label. Der Menüpunkt ist ohnehin nur bei aktivem Sync sichtbar; der
        Guard fängt den Grenzfall ab, dass Sync zwischen Menü-Öffnen und Klick
        deaktiviert wurde."""
        if not self.settings.get("sync_enabled"):
            return
        import threading
        from src.main import _run_push_blocking

        def _do():
            result = _run_push_blocking(
                self.storage, self.settings, self.conflicts_store,
                self.base_path, timeout_seconds=15,
            )
            self.root.after(0, lambda: self._on_tray_sync_done(result))
        threading.Thread(target=_do, daemon=True).start()

    def _on_tray_sync_done(self, result):
        # Still aktualisieren, damit der nächste Fenster-Aufruf den Stand zeigt.
        self._refresh()
        self._update_sync_status_label()
        if self._tray is None:
            return
        # title="" — kein fetter Titel: der Absender oben („Zeiterfassung
        # vX.Y.Z") nennt die App bereits, eine zusätzliche „Zeiterfassung"-
        # Titelzeile wäre redundant. Es bleibt nur die Statusmeldung.
        if result.get("ok"):
            n = (self.conflicts_store.count_unresolved()
                 if self.conflicts_store is not None else 0)
            msg = ("Synchronisiert." if n == 0
                   else f"Synchronisiert — {n} Konflikt{'e' if n != 1 else ''} offen.")
            self._tray.notify(msg, title="")
        else:
            self._tray.notify(f"Sync fehlgeschlagen:\n{result.get('error', '?')}",
                              title="")

    def _on_close(self):
        # Bei aktivem Minimize-to-Tray klappt der X-Button das Fenster nur weg;
        # der Prozess lebt weiter und ist über das Tray-Icon erreichbar. Sync-
        # Push und Quit passieren erst beim Tray-Menü-„Beenden" bzw. wenn das
        # Feature deaktiviert oder das Tray-Setup fehlgeschlagen ist.
        if self.settings.get("minimize_to_tray") and self._tray is not None:
            self.root.withdraw()
            return
        self._quit_with_sync_push()

    def _quit_with_sync_push(self):
        """Push zum Drive (falls aktiv) und App komplett beenden. Wird vom
        normalen X-Klick (ohne Tray) und vom Tray-Menü-„Beenden" aufgerufen."""
        if self.settings.get("sync_enabled"):
            from src.main import _run_push_blocking
            try:
                result = _run_push_blocking(
                    self.storage, self.settings, self.conflicts_store,
                    self.base_path, timeout_seconds=5,
                )
            except Exception as e:
                result = {"ok": False, "error": e, "tb": traceback.format_exc()}
            if not result.get("ok"):
                # CLAUDE.md: Fehler dürfen nicht silently verschluckt werden.
                # Wir zeigen die Messagebox blockierend; User entscheidet, ob er
                # die Daten nochmal woanders sichern will oder die App so schließt.
                _show_sync_error(
                    self.root, result.get("error", "?"), result.get("tb", ""),
                    suffix="Lokale Daten bleiben erhalten und werden beim "
                           "nächsten Start synchronisiert.",
                )
        if self._tray is not None:
            self._tray.stop()
        self.root.destroy()
