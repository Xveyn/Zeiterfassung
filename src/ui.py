# src/ui.py
import tkinter as tk
from tkinter import messagebox
import ctypes
import datetime
import logging
import os
import platform
import subprocess
import sys
import time
from src.time_utils import (
    format_iso_date, get_week_dates,
)

from src.version import VERSION, version_label

from src.background_tasks import BackgroundTaskRunner
from src.weekly_limit import format_limit_warnings
from src.grid_renderer import GridRenderer
from src.sync_orchestrator import classify_sync_error, SyncOrchestrator
from src.update_banner import UpdateBanner
from src.updater import today_iso, update_toast_text
from src.reminder_scheduler import ReminderScheduler
from src.send_reminder_scheduler import SendReminderScheduler
from src.dialogs.entry_dialog import open_entry_dialog
from src.dialogs.send_dialog import open_send_dialog
from src.dialogs.settings_dialog import open_settings_dialog
from src.theme import (
    BG, ACCENT, TEXT, TEXT_MUTED,
    FONT_HEADER, FONT_FOOTER, FONT_SMALL, apply_dark_titlebar, themed_askyesno, themed_ask_delete_choice, themed_showerror, themed_showinfo,
    themed_showwarning,
    icon_button, secondary_button, set_toggle_active, toggle_button,
    _stray_click_suppressed,
)


def _delete_action(slots, selected, prefix):
    """Entscheidet beim Rechtsklick-Löschen, was mit einem Typ (Arbeitszeit
    bzw. Reservierung) passiert.

    `selected` ist die Menge angehakter Keys; pro Typ entweder '<prefix>:all'
    (ganzer Typ) oder '<prefix>:<index>' (einzelne Slots). Liefert (action,
    keep): 'none' (Typ nicht betroffen) / 'delete' (Tag-Typ ganz löschen) /
    'save' (mit den verbleibenden Slots überschreiben)."""
    keys = {k for k in selected if k.startswith(prefix + ":")}
    if not keys:
        return "none", None
    if f"{prefix}:all" in keys:
        return "delete", None
    keep = [s for i, s in enumerate(slots) if f"{prefix}:{i}" not in keys]
    if not keep:
        return "delete", None
    return "save", keep


def _route_update_notification(release, tray_active, toast_shown_version):
    """Entscheidet zwischen Toast, Banner oder No-op für eine neue Version.

    Verglichen wird die volle Kennung (`release_id`), nicht die Basisversion —
    sonst würde ein zweiter Pre-Release derselben Version (pre.1 -> pre.2)
    als "schon gemeldet" durchfallen."""
    if tray_active:
        if release.release_id == toast_shown_version:
            return "none", None
        return "toast", update_toast_text(release)
    return "banner", None


class App:
    def __init__(self, root, storage, settings, base_path=".", conflicts_store=None,
                 reservation_store=None, single_instance=None,
                 data_lock=None, sync_guard=None):
        self.root = root
        self.storage = storage
        self.settings = settings
        self._single_instance = single_instance
        self.base_path = base_path
        self.conflicts_store = conflicts_store
        self.reservation_store = reservation_store
        self._data_lock = data_lock      # geteilter Store-RLock (Audit H1)
        self._sync_guard = sync_guard    # Sync-Re-Entrancy-Guard (Audit H2)
        self.root.title(f"Zeiterfassung v{version_label()}")
        self.root.configure(bg=BG)
        apply_dark_titlebar(self.root)

        # Win32-Fenster-/Taskbar-Identität nur unter Windows (Audit N21) — die
        # AUMID-/DisplayName-Registry-Schritte sind auf macOS/Linux ohnehin
        # No-ops (ctypes.windll/winreg fehlen), das Gate macht das explizit.
        if platform.system() == "Windows":
            self._setup_windows_app_identity()
        self._setup_window_icon(base_path)

        self.root.resizable(False, False)
        self._init_view_state()

        self._tray = None
        self._bg = BackgroundTaskRunner(
            self._marshal_to_ui, self.settings, self.base_path,
            self.reservation_store, self._reservations_active, self.storage,
            data_lock=data_lock,
        )
        self._sync = SyncOrchestrator(
            self.root, self.storage, self.settings, self.conflicts_store,
            self.base_path, self._bg, self._refresh, lambda: self._tray,
            data_lock=data_lock, sync_guard=sync_guard,
        )
        self._renderer = GridRenderer(
            self.root, self.storage, self.settings, self.reservation_store,
            self.conflicts_store, self._open_dialog, self._delete_day,
            self._reservations_active,
        )
        self._reminders = ReminderScheduler(
            self.root, self.settings, self.storage,
            self.reservation_store, lambda: self._tray,
            data_lock=data_lock, on_logged=self._refresh,
            marshal=self._marshal_to_ui,
        )
        self._send_reminders = SendReminderScheduler(
            self.root, self.settings, lambda: self._tray,
        )
        self._build_header()
        self._renderer.build_grid(self.root)
        self._build_footer()
        self._renderer.attach_labels(
            self.header_label, self.footer_label, self.header_width_spacer)
        self._sync.attach_widgets(
            self.sync_button, self.sync_status_label, self._next_button)
        self._sync.update_status_label()
        self._apply_always_on_top()
        self._apply_tray_setting()
        self._apply_reminder_setting()
        self._apply_send_reminder_setting()
        self.root.bind("<Left>", lambda e: self._navigate(-1))
        self.root.bind("<Right>", lambda e: self._navigate(+1))
        # Tab schaltet zwischen Monat- und Wochenansicht. "break" verhindert
        # die Default-Focus-Traversal, die sonst zwischen den Toggle-Buttons
        # springen würde und das Toggle visuell zerschießt.
        self.root.bind("<Tab>", self._on_tab_toggle_view)
        # Vor dem ersten echten Refresh: alle 4 Kombinationen
        # (view × show_weekend) einmal in den Backbuffer rendern, max reqwidth
        # observen. Das Fenster ist noch nicht gemappt (mainloop nicht
        # gestartet) — keine sichtbaren Zwischenzustände.
        self._renderer.measure_max_width(
            self.view_mode, self.year, self.month, self.iso_year, self.current_week)
        self._refresh()
        self._bg.refresh_token(
            on_auth_error=lambda msg: themed_showinfo(
                self.root,
                "Gmail-Anmeldung abgelaufen",
                "Der Gmail-Token konnte nicht automatisch erneuert werden:\n\n"
                f"{msg}\n\n"
                "Beim nächsten Senden wirst du zur erneuten Anmeldung aufgefordert.",
            ),
            on_error=lambda tb: themed_showinfo(
                self.root, "Token-Refresh fehlgeschlagen", tb,
            ),
        )
        self._bg.fetch_sender_email()
        self._update_banner = UpdateBanner(
            self.root, self.settings, lambda: self._renderer.grid_container,
            on_resize=self._renderer.repin_geometry)
        self._bg.check_update(on_result=self._on_update_check_result)
        self._bg.reconcile_on_start(on_ok=self._on_reconcile_start_done)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _setup_windows_app_identity(self):
        """Setzt die AppUserModelID und registriert den Toast-DisplayName
        (Windows-only, aus __init__ extrahiert — Audit N21).

        Die AUMID bleibt bewusst die stabile, namespaced ID — Windows knüpft
        Taskbar-Pins und Fenster-Gruppierung daran; ein Wechsel würde
        bestehende Pins beim Update lösen. Den lesbaren Absender-Namen für
        Toast-Benachrichtigungen (inkl. dynamischer Version) registrieren wir
        separat als DisplayName unter dem AUMID-Registry-Key — den greift
        Windows für die Toast-Attribution, ohne die AUMID selbst zu ändern.
        Jeder Schritt ist einzeln gegen Fehler abgesichert."""
        from src.tray import AUMID as app_aumid
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

    def _setup_window_icon(self, base_path):
        """Setzt App-/Taskbar-Icon (aus __init__ extrahiert — Audit N21).

        Unter Windows das .ico als Tk-Default (`wm iconbitmap -default`), damit
        künftige Toplevels (Settings, Entry, …) es erben statt des Tk-Default-
        Feder-Icons; zusätzlich das .png als iconphoto auf allen Plattformen."""
        ico_path = os.path.join(base_path, "assets", "margenheld-icon.ico")
        png_path = os.path.join(base_path, "assets", "margenheld-icon.png")
        if platform.system() == "Windows" and os.path.exists(ico_path):
            self.root.iconbitmap(default=ico_path)
        if os.path.exists(png_path):
            icon = tk.PhotoImage(file=png_path)
            self.root.iconphoto(True, icon)
            self._icon_ref = icon

    def _init_view_state(self):
        """Initialer Kalender-View-Zustand aus dem heutigen Datum (aus __init__
        extrahiert — Audit N21): Jahr/Monat + Monatsansicht, ISO-Jahr/-Woche."""
        today = datetime.date.today()
        self.year = today.year
        self.month = today.month
        self.view_mode = "month"  # "month" or "week"
        iso = today.isocalendar()
        self.iso_year = iso[0]
        self.current_week = iso[1]

    def _reservations_active(self):
        """True, wenn Reservierungen angezeigt/bearbeitet werden dürfen: ein
        Store existiert UND der Google-Kalender-Sync ist in den Settings aktiv.
        Bei deaktiviertem Sync werden Reservierungen weder im Kalender
        gerendert noch im Tages-Dialog angeboten."""
        return (self.reservation_store is not None
                and bool(self.settings.get("gcal_enabled")))

    def _on_reconcile_done(self, result):
        if not result.get("ok"):
            error = result.get("error", "?")
            if classify_sync_error(error) == "auth":
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
        self._show_limit_warnings(result.get("limit_warnings"))

    def _on_reconcile_start_done(self, result):
        self._refresh()
        self._show_limit_warnings(result.get("limit_warnings"))

    def _show_limit_warnings(self, warnings):
        if not warnings:
            return
        themed_showwarning(
            self.root, "Wochenlimit überschritten",
            "Der Kalender-Import betrifft Wochen über dem konfigurierten "
            f"Werkstudenten-Limit:\n\n{format_limit_warnings(warnings)}\n\n"
            "Grobe Näherung, keine rechtliche Bewertung.",
        )

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

        icon_button(frame, "\u2039", lambda: self._navigate(-1)).pack(side=tk.LEFT)

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

        # header_width_spacer: unsichtbarer Platzhalter (kein Text, gleiche
        # bg), der ANSTELLE von header_label im pack-Fluss steht — GridRenderer
        # hält font/width synchron zum echten header_label (s. attach_labels/
        # refresh dort). Grund: header_label selbst wird unten per `place`
        # (nicht `pack`) absolut auf die Fensterbreite zentriert, damit es nie
        # verrutscht, egal wie breit die rechte Sync-Button-Gruppe gerade ist
        # (die darf während des Synchronisierens ruhig wandern). `place`-
        # Kinder zählen aber nicht zur reqwidth des Frames — ohne diesen
        # Platzhalter würde GridRenderer.measure_max_width() die von
        # header_label benötigte Breite nicht mehr einrechnen und das fixe
        # Fenster könnte zu schmal gepinnt werden (u.a. Sync-Button ohne Platz).
        self.header_width_spacer = tk.Label(frame, text="", bg=BG, width=0)
        self.header_width_spacer.pack(side=tk.LEFT, expand=True)

        # font und width werden in _refresh() je nach View gesetzt — fixe
        # width verhindert Pack-Reflow beim Text-Wechsel innerhalb derselben
        # View, und die Wochen-Variante braucht eine kleinere Schrift, weil
        # das KW-Label sonst breiter als das Fenster ist.
        self.header_label = tk.Label(
            frame, text="", bg=BG, fg="#ffffff",
        )
        self.header_label.place(relx=0.5, rely=0.5, anchor="center")

        icon_button(
            frame, "\u2699", self._open_settings,
            fg=TEXT_MUTED, hover_fg=TEXT,
        ).pack(side=tk.RIGHT)

        self._next_button = icon_button(frame, "\u203a", lambda: self._navigate(+1))
        self._next_button.pack(side=tk.RIGHT, padx=(0, 5))

        # --- Sync-Button und Status (Multi-Device-Sync) ---
        # Widgets werden erzeugt, aber nur gepackt wenn sync_enabled. Sync
        # ist opt-in; bei deaktiviertem Sync soll der Header unver\u00e4ndert wirken.
        self.sync_button = icon_button(frame, "\u27f3", self._sync.on_sync_clicked)
        self.sync_status_label = tk.Label(frame, text="", bg=BG, fg=TEXT_MUTED, font=FONT_SMALL)

    def _build_footer(self):
        footer_frame = tk.Frame(self.root, bg=BG)
        footer_frame.pack(fill=tk.X, padx=10, pady=(0, 10))

        # Die reqwidth-fixierende Label-Breite setzt GridRenderer._update_footer
        # abhängig vom Stundenlohn (16 ohne, 40 mit — Details dort). Der
        # Startwert 16 gilt bis zum ersten refresh (Vorab-Messung vor mainloop).
        self.footer_label = tk.Label(
            footer_frame, text="Gesamt: 0.0h", font=FONT_FOOTER,
            bg=BG, fg=ACCENT, width=16,
        )
        self.footer_label.pack(side=tk.LEFT, expand=True)

        secondary_button(
            footer_frame, "Teilen", self._share, padx=12,
        ).pack(side=tk.RIGHT, padx=(0, 4))
        secondary_button(
            footer_frame, "Export", self._export, padx=12,
        ).pack(side=tk.RIGHT, padx=(0, 4))
        secondary_button(
            footer_frame, "Arbeitszeiten senden", self._send, padx=12,
        ).pack(side=tk.RIGHT, padx=(0, 4))

    def _navigate(self, direction):
        """Blättert die Ansicht um `direction` Einheiten (-1 zurück, +1 vor):
        im Monatsmodus ±1 Monat (mit Jahreswechsel), im Wochenmodus ±7 Tage."""
        if self.view_mode == "month":
            m = self.month + direction
            if m < 1:
                self.month, self.year = 12, self.year - 1
            elif m > 12:
                self.month, self.year = 1, self.year + 1
            else:
                self.month = m
        else:
            monday = get_week_dates(self.iso_year, self.current_week)[0] \
                + datetime.timedelta(days=7 * direction)
            self.iso_year, self.current_week = monday.isocalendar()[:2]
        self._refresh()

    def _on_tab_toggle_view(self, _event=None):
        self._set_view("week" if self.view_mode == "month" else "month")
        return "break"

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
            self._sync.update_status_label()
            self._apply_always_on_top()
            self._apply_tray_setting()
            self._apply_reminder_setting()
            self._apply_send_reminder_setting()
            # Nach jeder Settings-Speicherung den sender_email-Fetch nochmal
            # anstoßen. Damit erscheint die Absender-Adresse automatisch nach
            # Sync-Aktivierung (frischer Token mit userinfo.email-Scope), ohne
            # dass der User den "Aktualisieren"-Button drücken muss.
            self._bg.fetch_sender_email()
        open_settings_dialog(
            self.root, self.settings, self.base_path,
            on_change=_on_change,
            runner=self._bg,
            conflicts_store=self.conflicts_store,
            storage=self.storage,
            reservation_store=self.reservation_store,
            on_request_restart=self.restart_for_scaling,
            data_lock=self._data_lock,
            sync_guard=self._sync_guard,
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

        # Tray dient mehrerem: Minimize-to-Tray UND als Toast-Kanal für
        # Reservierungs- und Sende-Erinnerungen. Es läuft, sobald EINES aktiv ist.
        want_tray = (bool(self.settings.get("minimize_to_tray"))
                     or bool(self.settings.get("reminders_enabled"))
                     or bool(self.settings.get("send_reminder_enabled")))

        if want_tray and self._tray is None:
            if not is_supported():
                themed_showinfo(
                    self.root,
                    "Infobereich-Icon / Benachrichtigungen",
                    "Infobereich-Icon und Toast-Benachrichtigungen sind auf "
                    "dieser Plattform nicht zuverlässig nutzbar (typisch Linux). "
                    "Die Optionen wurden wieder deaktiviert.",
                )
                self.settings.set("minimize_to_tray", False)
                self.settings.set("reminders_enabled", False)
                self.settings.set("send_reminder_enabled", False)
                return
            tray = TrayIcon(
                self.base_path,
                on_show=lambda: self.root.after(0, self._restore_from_tray),
                on_quit=lambda: self.root.after(0, self._quit_with_sync_push),
                actions=[
                    ("Arbeitszeiten senden",
                     lambda: self.root.after(0, self._send), None),
                    ("Teilen",
                     lambda: self.root.after(0, self._share), None),
                    ("Export",
                     lambda: self.root.after(0, self._export), None),
                    ("Mit Google Drive synchronisieren",
                     lambda: self.root.after(0, self._sync.tray_sync),
                     lambda: bool(self.settings.get("sync_enabled"))),
                ],
            )
            try:
                tray.start()
            except Exception as e:
                logging.getLogger(__name__).exception("Tray-Start fehlgeschlagen")
                themed_showerror(
                    self.root,
                    "Infobereich-Icon",
                    f"Tray-Icon konnte nicht gestartet werden:\n\n{e}",
                )
                self.settings.set("minimize_to_tray", False)
                self.settings.set("reminders_enabled", False)
                self.settings.set("send_reminder_enabled", False)
                return
            self._tray = tray

        elif not want_tray and self._tray is not None:
            self._tray.stop()
            self._tray = None

    def _apply_reminder_setting(self):
        """Startet/stoppt den Reminder-Poll abhängig vom Setting. Braucht ein
        laufendes Tray-Icon als Toast-Kanal — ohne Tray wird gestoppt.

        MUSS nach `_apply_tray_setting()` laufen (liest `self._tray`): erst wird
        der Tray-Kanal (de)aktiviert, dann der Poll daran gekoppelt. Beide
        Call-Sites (__init__, Settings-`_on_change`) halten diese Reihenfolge."""
        want = bool(self.settings.get("reminders_enabled")) and self._tray is not None
        if want:
            self._reminders.start()
        else:
            self._reminders.stop()

    def _apply_send_reminder_setting(self):
        """Startet/stoppt den monatlichen Sende-Reminder-Poll abhängig vom
        Setting. Braucht ein laufendes Tray-Icon als Toast-Kanal — ohne Tray
        wird gestoppt.

        MUSS nach `_apply_tray_setting()` laufen (liest `self._tray`), wie
        `_apply_reminder_setting()`."""
        want = bool(self.settings.get("send_reminder_enabled")) and self._tray is not None
        if want:
            self._send_reminders.start()
        else:
            self._send_reminders.stop()

    def _on_update_check_result(self, release, newer):
        """Verarbeitet das Ergebnis des Hintergrund-Update-Checks im UI-Thread."""
        self.settings.set("last_update_check_at", today_iso())
        if not newer:
            return
        action, text = _route_update_notification(
            release,
            self._tray is not None,
            self.settings.get("update_toast_shown_version"),
        )
        if action == "toast":
            self._tray.notify(text)
            self.settings.set("update_toast_shown_version", release.release_id)
        elif action == "banner":
            self._update_banner.show_if_newer(release)

    def _restore_from_tray(self):
        """Bringt das Fenster aus dem `withdraw()`-Zustand zurück."""
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()

    def _marshal_to_ui(self, fn):
        """Marshallt `fn` aus einem Daemon-Worker auf den Tk-Thread via
        after(0) und verwirft den Aufruf still, falls das Fenster
        zwischenzeitlich geschlossen wurde.

        Hintergrund-Threads (Sync-Pull, Reconcile, Update-Check, Token-
        Refresh) planen ihr Ergebnis per after(0). Schließt der Nutzer das
        Fenster, bevor der Callback feuert, läuft er gegen den zerstörten
        Tk-Interpreter -> "application has been destroyed" (TclError). Sowohl
        das Einplanen als auch das spätere Ausführen werden daher gegen
        TclError abgesichert (vgl. tooltip.py)."""
        def guarded():
            try:
                fn()
            except tk.TclError:
                pass
        try:
            self.root.after(0, guarded)
        except tk.TclError:
            pass

    def _refresh(self):
        self._renderer.refresh(
            self.view_mode, self.year, self.month, self.iso_year, self.current_week)

    def _delete_day(self, date_str):
        """Rechtsklick-Löschen für einen Tag. Löscht NIE ohne Bestätigung.

        - Genau eine löschbare Einheit (1 Arbeitszeit-Slot ODER 1 Reservierung)
          → Ja/Nein-Abfrage.
        - Mehrere Einheiten (mehrere Slots und/oder Arbeitszeit + Reservierung)
          → Auswahl-Dialog: pro Slot bzw. pro Typ eine Checkbox, alle
          vorausgewählt.

        Beide Dialogvarianten sperren ihren Bestätigen-Button nach dem Öffnen
        kurz (lock_ms=600, siehe theme.py) — gegen versehentliches Sofort-
        Löschen, z.B. durch einen schnellen Doppel-Rechtsklick.

        Reservierungen werden nur berücksichtigt, wenn sie aktiv sind
        (_reservations_active); eine Reservierungs-Änderung stößt den Kalender-
        Abgleich an.
        """
        if _stray_click_suppressed(getattr(self.root, "_dialog_closed_at", 0),
                                   time.monotonic()):
            return  # Rechtsklick schlägt von einem eben geschlossenen Dialog durch (#44).
        entry = self.storage.get(date_str)
        reservation = (
            self.reservation_store.get(date_str)
            if self._reservations_active() else None
        )
        entry_slots = entry["slots"] if entry else []
        res_slots = reservation["slots"] if reservation else []
        if not entry_slots and not res_slots:
            return

        date_de = format_iso_date(date_str)

        # Löschbare Einheiten: bei genau einem Slot der Typ als Ganzes, bei
        # mehreren je Slot eine Checkbox.
        options = []
        if entry_slots:
            if len(entry_slots) == 1:
                options.append(("entry:all", "Arbeitszeit"))
            else:
                for i, s in enumerate(entry_slots):
                    options.append((f"entry:{i}", f"Arbeitszeit  {GridRenderer._fmt_slot_line(s)}"))
        if res_slots:
            if len(res_slots) == 1:
                options.append(("reservation:all", "Reservierung"))
            else:
                for i, s in enumerate(res_slots):
                    options.append((f"reservation:{i}", f"Reservierung  {GridRenderer._fmt_slot_line(s)}"))

        if len(options) == 1:
            kind = "Arbeitszeit" if options[0][0].startswith("entry") else "Reservierung"
            if not themed_askyesno(self.root, f"{kind} löschen",
                                   f"{kind} für {date_de} löschen?", lock_ms=600):
                return
            selected = {options[0][0]}
        else:
            selected = themed_ask_delete_choice(
                self.root, "Löschen", f"Was für den {date_de} löschen?",
                options, lock_ms=600,
            )
            if not selected:
                return

        entry_action, entry_keep = _delete_action(entry_slots, selected, "entry")
        if entry_action == "delete":
            self.storage.delete(date_str)
        elif entry_action == "save":
            self.storage.save(date_str, entry_keep)

        res_action, res_keep = _delete_action(res_slots, selected, "reservation")
        res_touched = res_action != "none"
        if res_action == "delete":
            self.reservation_store.delete(date_str)
        elif res_action == "save":
            self.reservation_store.save(date_str, res_keep)

        self._refresh()
        if res_touched:
            self._bg.trigger_reconcile(self._on_reconcile_done)

    def _open_dialog(self, date_str):
        if _stray_click_suppressed(getattr(self.root, "_dialog_closed_at", 0),
                                   time.monotonic()):
            return  # Linksklick schlägt von einem eben geschlossenen Dialog durch (#44).
        # Ein Tag mit ungelöstem Sync-Konflikt (Ist-Zeit zwischen zwei Geräten
        # widersprüchlich) öffnet den ConflictsDialog statt des normalen
        # Tages-Dialogs — die Ist-Zeit steht buchstäblich zur Debatte, sie vor
        # der Auflösung normal zu editieren würde einen der beiden Kandidaten
        # überschreiben. Gefiltert auf genau diesen Tag (filter_key), statt die
        # volle Liste aller offenen Konflikte zu zeigen.
        if self.conflicts_store is not None and date_str in self.conflicts_store.unresolved_entry_keys():
            from src.dialogs.conflicts_dialog import ConflictsDialog
            ConflictsDialog(
                self.root, self.storage, self.settings, self.conflicts_store,
                data_lock=self._data_lock, filter_key=date_str,
                on_resolved=self._refresh,
            )
            return
        # Bei deaktiviertem Kalender-Sync KEIN reservation_store an den Dialog
        # geben — dann wird der Reservierungs-Block nicht angezeigt und ist per
        # Linksklick nicht setzbar (open_entry_dialog wertet None entsprechend).
        open_entry_dialog(
            self.root, date_str, self.storage, self.settings,
            on_change=self._refresh,
            reservation_store=(
                self.reservation_store if self._reservations_active() else None),
            trigger_reconcile=lambda: self._bg.trigger_reconcile(self._on_reconcile_done),
        )

    def _send(self):
        open_send_dialog(self.root, self.storage, self.settings, self.base_path, self._bg)

    def _share(self):
        from src.dialogs.share_dialog import open_share_dialog
        open_share_dialog(
            self.root, self.storage, self.settings, self.base_path, self._bg,
            reservation_store=self.reservation_store,
        )

    def _export(self):
        from src.dialogs.export_dialog import open_export_dialog
        open_export_dialog(self.root, self.storage, self.settings, self._bg)

    def on_sync_pull_success(self):
        """Public-API für main.py: nach erfolgreichem Pull (UI-Thread)."""
        self._sync.on_pull_success()

    def on_sync_pull_error(self, error, tb=""):
        self._sync.on_pull_error(error, tb)

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
        self._sync.push_on_quit()
        if self._tray is not None:
            self._tray.stop()
        self._reminders.stop()
        self._send_reminders.stop()
        if self._single_instance is not None:
            self._single_instance.release()
        self.root.destroy()

    def restart_for_scaling(self):
        """Startet die App neu, damit eine geänderte UI-Skalierung greift
        (tk-scaling wird nur beim Start gesetzt). Erst den neuen Prozess
        spawnen, dann erst das alte Fenster abbauen — schlägt Popen fehl,
        bleibt die laufende App vollständig intakt (Tray läuft, Fenster offen)
        und der Nutzer bekommt einen Hinweis. Kein Sync-Push: der Faktor ist
        lokal, ein 5-s-Push würde den Neustart nur verzögern."""
        from src.main import relaunch_command
        cmd = relaunch_command(
            sys.argv, sys.executable, getattr(sys, "frozen", False))
        if self._single_instance is not None:
            self._single_instance.release()
        # Port VOR dem Spawn freigeben, sonst fände die neue Instanz ihn noch
        # belegt, schickte SHOW und beendete sich — die App verschwände beim
        # bloßen Skalierungswechsel.
        try:
            env = os.environ.copy()
            # PyInstaller-Onefile (≥6.10) behandelt einen per sys.executable
            # gespawnten Kindprozess standardmäßig als Worker-Subprozess DER-
            # SELBEN Instanz und lässt ihn das bereits entpackte _MEIPASS-
            # Verzeichnis DES ALTEN Prozesses mitnutzen. Das räumt der alte
            # Prozess aber auf, sobald er unten beendet wird — der neue
            # Prozess bricht dann mit fehlenden Bundle-Dateien ab (z.B. "Tcl
            # data directory ... not found", googleapiclient-Discovery-Docs
            # nicht auffindbar → UnknownApiNameOrVersion). Ohne dieses Signal
            # ist der Neustart also ein Wettlauf gegen die Temp-Aufräumung des
            # alten Prozesses. PYINSTALLER_RESET_ENVIRONMENT=1 zwingt den
            # neuen Prozess, sich frisch (in ein eigenes Verzeichnis) zu
            # entpacken, statt zu erben — No-op im Repo-Modus (kein Bootloader
            # liest die Variable dort).
            env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
            subprocess.Popen(cmd, env=env)
        except Exception:
            logging.getLogger(__name__).exception(
                "Neustart für UI-Skalierung fehlgeschlagen")
            # N18: Popen ist fehlgeschlagen, der oben freigegebene Single-
            # Instance-Guard würde sonst für den Rest der Session fehlen
            # (ein manueller Zweitstart bliebe unbemerkt). Guard neu binden.
            if self._single_instance is not None:
                from src import single_instance
                self._single_instance = single_instance.acquire(
                    self.base_path, show_requested=False)
                if self._single_instance is not None:
                    self._single_instance.serve(
                        lambda: self._marshal_to_ui(self._restore_from_tray))
            themed_showinfo(
                self.root,
                "Neustart nötig",
                "Die Skalierung wird beim nächsten Start der App wirksam.",
            )
            return
        if self._tray is not None:
            self._tray.stop()
        self._reminders.stop()
        self._send_reminders.stop()
        self.root.destroy()
