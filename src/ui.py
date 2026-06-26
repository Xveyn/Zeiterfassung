# src/ui.py
import tkinter as tk
from tkinter import messagebox
import ctypes
import datetime
import logging
import os
import platform
import time
from src.time_utils import (
    format_iso_date, get_week_dates,
)

from src.version import VERSION, version_label

from src.background_tasks import BackgroundTaskRunner
from src.grid_renderer import GridRenderer
from src.sync_orchestrator import _classify_sync_error, SyncOrchestrator
from src.update_banner import UpdateBanner
from src.dialogs.entry_dialog import open_entry_dialog
from src.dialogs.send_dialog import open_send_dialog
from src.dialogs.settings_dialog import open_settings_dialog
from src.theme import (
    BG, ACCENT, TEXT, TEXT_MUTED,
    FONT_HEADER, FONT_FOOTER, FONT_SMALL, apply_dark_titlebar, themed_askyesno, themed_ask_delete_choice, themed_showerror, themed_showinfo,
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


class App:
    def __init__(self, root, storage, settings, base_path=".", conflicts_store=None,
                 reservation_store=None):
        self.root = root
        self.storage = storage
        self.settings = settings
        self.base_path = base_path
        self.conflicts_store = conflicts_store
        self.reservation_store = reservation_store
        self.root.title(f"Zeiterfassung v{version_label()}")
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

        self._tray = None
        self._bg = BackgroundTaskRunner(
            self._marshal_to_ui, self.settings, self.base_path,
            self.reservation_store, self._reservations_active,
        )
        self._sync = SyncOrchestrator(
            self.root, self.storage, self.settings, self.conflicts_store,
            self.base_path, self._bg, self._refresh, lambda: self._tray,
        )
        self._renderer = GridRenderer(
            self.root, self.storage, self.settings, self.reservation_store,
            self.conflicts_store, self._open_dialog, self._delete_day,
            self._reservations_active,
        )
        self._build_header()
        self._renderer.build_grid(self.root)
        self._build_footer()
        self._renderer.attach_labels(self.header_label, self.footer_label)
        self._sync.attach_widgets(
            self.sync_button, self.sync_status_label, self._next_button)
        self._sync.update_status_label()
        self._apply_always_on_top()
        self._apply_tray_setting()
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
            self.root, self.settings, lambda: self._renderer.grid_container)
        self._bg.check_update(on_result=self._update_banner.handle_check_result)
        self._bg.reconcile_on_start(on_ok=self._refresh)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

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

        # width fixiert reqwidth → kein Pack-Reflow, wenn sich die Stunden-/
        # Brutto-Summe beim Monatswechsel ändert. 40 deckt die längste
        # Variante ab ("Gesamt: 999.99h  —  99999.99 € brutto" ≈ 38 Zeichen).
        self.footer_label = tk.Label(
            footer_frame, text="Gesamt: 0.0h", font=FONT_FOOTER,
            bg=BG, fg=ACCENT, width=40,
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
            # Nach jeder Settings-Speicherung den sender_email-Fetch nochmal
            # anstoßen. Damit erscheint die Absender-Adresse automatisch nach
            # Sync-Aktivierung (frischer Token mit userinfo.email-Scope), ohne
            # dass der User den "Aktualisieren"-Button drücken muss.
            self._bg.fetch_sender_email()
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
                themed_showinfo(
                    self.root,
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
          vorausgewählt; der „Löschen"-Button ist nach dem Öffnen kurz gesperrt
          (gegen versehentliches Sofort-Löschen).

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
                                   f"{kind} für {date_de} löschen?"):
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
        open_send_dialog(self.root, self.storage, self.settings, self.base_path)

    def _share(self):
        from src.dialogs.share_dialog import open_share_dialog
        open_share_dialog(
            self.root, self.storage, self.settings, self.base_path,
            reservation_store=self.reservation_store,
        )

    def _export(self):
        from src.dialogs.export_dialog import open_export_dialog
        open_export_dialog(self.root, self.storage, self.settings)

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
        self.root.destroy()
