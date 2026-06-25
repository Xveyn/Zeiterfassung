# src/ui.py
import tkinter as tk
from tkinter import messagebox
import calendar
import ctypes
import datetime
import logging
import os
import platform
import time
from src.time_utils import (
    DAYS_DE, MONTHS_DE,
    calculate_hours, format_iso_date, get_week_dates, get_week_label, week_spans_months,
)
from src.holidays_de import get_holidays
from src.tooltip import attach_tooltip

from src.version import VERSION, version_label

from src.background_tasks import BackgroundTaskRunner
from src.sync_orchestrator import _classify_sync_error, SyncOrchestrator
from src.update_banner import UpdateBanner
from src.dialogs.entry_dialog import open_entry_dialog
from src.dialogs.send_dialog import open_send_dialog
from src.dialogs.settings_dialog import open_settings_dialog
from src.theme import (
    BG, CELL_BG, WEEKEND_BG, ACCENT, TEXT, TEXT_MUTED,
    _should_show_delete_button,
    ENTRY_BG, WEEKEND_ENTRY_BG, WEEKEND_FG,
    HOLIDAY_BG, HOLIDAY_BG_HOVER, HOLIDAY_ACCENT,
    RESERVATION_ACCENT, TODAY_ACCENT,
    FONT, FONT_BOLD, FONT_HEADER, FONT_HEADER_SMALL, FONT_FOOTER, FONT_SMALL, FONT_TINY,
    CELL_BG_HOVER, WEEKEND_BG_HOVER, ENTRY_BG_HOVER, WEEKEND_ENTRY_BG_HOVER,
    apply_dark_titlebar, themed_askyesno, themed_ask_delete_choice, themed_showinfo,
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


# Probe-Label-Geometrie zur Zellgroessen-Messung (Month- und Week-Render teilen sie).
PROBE_WIDTH_WIDE = 12    # ausgeblendetes Wochenende -> breitere Zellen
PROBE_WIDTH_NARROW = 8   # 7-Spalten-Modus
PROBE_HEIGHT = 3


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
        self._build_header()
        self._build_grid()
        self._build_footer()
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
        self._fixed_width = self._measure_max_width()
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
            self.root, self.settings, lambda: self.grid_container)
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
            footer_frame, "Teilen", self._share, padx=12,
        ).pack(side=tk.RIGHT, padx=(0, 4))
        secondary_button(
            footer_frame, "Arbeitszeiten senden", self._send, padx=12,
        ).pack(side=tk.RIGHT)

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
                    ("Arbeitszeiten senden",
                     lambda: self.root.after(0, self._send), None),
                    ("Teilen",
                     lambda: self.root.after(0, self._share), None),
                    ("Mit Google Drive synchronisieren",
                     lambda: self.root.after(0, self._sync.tray_sync),
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
        slots = entry.get("slots", [])
        if slots:
            first = slots[0]
            time_text = f"{first['start']}-{first['end']}"
            if len(slots) > 1:
                time_text += f"  +{len(slots) - 1}"
        else:
            time_text = ""
        time_lbl = tk.Label(
            cell, text=time_text,
            font=time_font, bg=bg, fg=TEXT_MUTED, cursor="hand2",
        )
        time_lbl.pack(pady=(0, pad))
        for w in (cell, day_lbl, time_lbl):
            w.bind("<Button-1>", lambda e, d=date_str: self._open_dialog(d))
            w.bind("<Button-3>", lambda e, d=date_str: self._delete_day(d))
            w.bind("<Enter>", lambda e, c=cell, dl=day_lbl, tl=time_lbl, hb=hover_bg: self._hover(c, hb, dl, tl))
            w.bind("<Leave>", lambda e, c=cell, dl=day_lbl, tl=time_lbl, ob=bg: self._hover(c, ob, dl, tl))
        return cell

    @staticmethod
    def _fmt_slot_line(slot):
        """Eine Tooltip-Zeile für einen Slot: 'HH:MM-HH:MM  Kategorie'
        (Kategorie weggelassen, wenn leer)."""
        kat = f"  {slot['kategorie']}" if slot.get("kategorie") else ""
        return f"{slot['start']}-{slot['end']}{kat}"

    def _add_reservation_marker(self, cell):
        """Runder violetter Eck-Punkt auf einer Ist-Zeitzelle, die zusätzlich
        eine Reservierung hat. Ein Canvas-Oval statt eines Text-Bullets — „•"
        rendert je nach Font als kaum sichtbarer Fleck; das Oval gibt einen
        sauber gerundeten, größenkontrollierten Punkt. place() überlagert die
        gepackten Kind-Widgets. Der Marker wird als cell._reservation_marker
        getaggt, damit _hover seinen Hintergrund beim Hover mitfärbt."""
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

    def _add_delete_button(self, cell, date_str):
        """macOS-only: kleines ✕ oben links, das den Lösch-Pfad auslöst.

        <Button-3> ist auf macOS unzuverlässig (Sekundärklick je nach Tk-Version
        <Button-2>/Control-Klick); dieser Button gibt dort einen verlässlichen
        Lösch-Auslöser, ohne den Linksklick-Dialog mit Lösch-Buttons zu belasten.
        Klick ruft denselben _delete_day-Pfad wie der Win/Linux-Rechtsklick
        (Ja/Nein bzw. Slot-Auswahl). Getaggt als cell._delete_button, damit
        _hover seinen Hintergrund beim Hover mitfärbt."""
        bg = cell.cget("bg")
        btn = tk.Label(
            cell, text="✕", font=FONT_TINY, bg=bg, fg=TEXT_MUTED, cursor="hand2",
        )
        btn.place(relx=0.0, x=3, y=2, anchor="nw")
        # "break" stoppt jede Propagation, damit der Klick nicht zusätzlich als
        # Zell-Linksklick (Bearbeiten-Dialog) durchschlägt.
        btn.bind("<Button-1>",
                 lambda e, d=date_str: (self._delete_day(d), "break")[1])
        # fg-Hover (rot als Lösch-Affordance) steuert der Button selbst; den bg
        # färbt _hover mit der Zelle.
        btn.bind("<Enter>", lambda e: btn.config(fg=ACCENT))
        btn.bind("<Leave>", lambda e: btn.config(fg=TEXT_MUTED))
        cell._delete_button = btn

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
            w.bind("<Enter>", lambda e, c=cell, dl=day_lbl, hb=hover_bg: self._hover(c, hb, dl))
            w.bind("<Leave>", lambda e, c=cell, dl=day_lbl, ob=bg: self._hover(c, ob, dl))
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
        # den Zelltyp nicht. Genau EIN attach_tooltip pro Zelle (Mehrfachaufruf
        # erzeugt überlappende Tooltips); deshalb alle relevanten Infos
        # (mehrere Arbeitszeit-Slots, Reservierung, Feiertag) in einen
        # kombinierten Tooltip. Ein Feiertag-OHNE-Eintrag/-Reservierung zeigt
        # seinen Namen weiterhin als Zelltext (Holiday-Zelle) bzw. eigenen
        # Tooltip (name_tooltip) und kommt hier NICHT rein.
        tip_parts = []
        if entry and len(entry.get("slots", [])) > 1:
            tip_parts.append(
                "Arbeitszeit:\n"
                + "\n".join(self._fmt_slot_line(s) for s in entry["slots"]))
        if reservation is not None:
            self._add_reservation_marker(cell)
            tip_parts.append(
                "Reservierung:\n"
                + "\n".join(self._fmt_slot_line(s) for s in reservation.get("slots", [])))
        if is_holiday and (reservation is not None or entry):
            tip_parts.append(f"Feiertag: {holidays_map[day_date]}")
        if tip_parts:
            attach_tooltip(cell, "\n".join(tip_parts))

        # macOS-only Lösch-Button (✕) oben links, sobald der Tag löschbare
        # Einheiten hat (Ist-Zeit ODER aktive Reservierung). reservation wird
        # nur bei aktivem Kalender-Sync übergeben (vgl. _add_reservation_marker),
        # daher deckt `reservation is not None` die aktive Reservierung ab.
        if _should_show_delete_button(
            platform.system() == "Darwin", bool(entry), reservation is not None
        ):
            self._add_delete_button(cell, date_str)

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
        return round(sum(
            calculate_hours(s["start"], s["end"], pause_minutes=s.get("pause", 0))
            for s in entry.get("slots", [])
        ), 2)

    def _dates_with_unresolved_conflicts(self):
        """Gibt die Menge der ISO-Datums-Strings zurück, für die ungelöste
        Konflikte vom Typ 'entry' vorliegen."""
        if not self.conflicts_store:
            return set()
        return {
            c["key"] for c in self.conflicts_store.get_all()
            if c.get("kind") == "entry" and not c.get("resolved")
        }

    def _cell_layout_metrics(self, frame):
        """Misst die natuerliche Pixelgroesse einer Standard-Tageszelle (Probe-
        Label) und liefert die layout-abhaengigen Groessen.

        Bei ausgeblendetem Wochenende (5 statt 7 Spalten) bleibt mehr Horizontal-
        platz pro Spalte: breitere Zellen und groessere Zeit-/Feiertagsschrift
        (FONT statt FONT_SMALL), damit z.B. '09:30-17:00' bequem lesbar bleibt.
        Holiday-Zellen werden spaeter auf `cell_size` fixiert, damit lange
        Feiertagsnamen die Spalte nicht aufweiten (Header-Reflow/Flackern)."""
        wide_cells = not self.settings.get("show_weekend")
        probe_width = PROBE_WIDTH_WIDE if wide_cells else PROBE_WIDTH_NARROW
        entry_time_font = FONT if wide_cells else FONT_SMALL
        holiday_name_font = FONT if wide_cells else FONT_SMALL
        probe = tk.Label(frame, text="", font=FONT, width=probe_width, height=PROBE_HEIGHT)
        probe.update_idletasks()
        cell_size = (probe.winfo_reqwidth(), probe.winfo_reqheight())
        probe.destroy()
        return cell_size, entry_time_font, holiday_name_font, wide_cells

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

        cell_size, entry_time_font, holiday_name_font, wide_cells = \
            self._cell_layout_metrics(new_frame)

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

        cell_size, entry_time_font, holiday_name_font, wide_cells = \
            self._cell_layout_metrics(new_frame)

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
                self._hover(c, HOLIDAY_BG_HOVER, dl, nl))
            w.bind("<Leave>", lambda e, c=cell, dl=day_lbl, nl=name_lbl:
                self._hover(c, HOLIDAY_BG, dl, nl))
        if name_tooltip and truncated != name:
            # Geteilter Tooltip über alle drei Widgets — _Tooltip trackt sie
            # gemeinsam, sodass Pointer-Wechsel zwischen Frame und Child-
            # Labels den Tooltip nicht schließt/neu öffnet.
            attach_tooltip((cell, day_lbl, name_lbl), f"Feiertag: {name}")
        return cell

    @staticmethod
    def _hover(frame, bg, *labels):
        """Faerbt Zelle + uebergebene Labels beim Hover. Die Eck-Overlays
        (_reservation_marker, macOS-_delete_button) werden mitgefaerbt, sonst
        bleibt ein andersfarbiges Rechteck stehen. Nur bg — die fg des
        Loesch-Buttons steuert dessen eigener Enter/Leave-Handler."""
        frame.config(bg=bg)
        for lbl in labels:
            lbl.config(bg=bg)
        for attr in ("_reservation_marker", "_delete_button"):
            w = getattr(frame, attr, None)
            if w is not None:
                w.config(bg=bg)

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
                    options.append((f"entry:{i}", f"Arbeitszeit  {self._fmt_slot_line(s)}"))
        if res_slots:
            if len(res_slots) == 1:
                options.append(("reservation:all", "Reservierung"))
            else:
                for i, s in enumerate(res_slots):
                    options.append((f"reservation:{i}", f"Reservierung  {self._fmt_slot_line(s)}"))

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
