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
    calculate_hours, get_week_dates, get_week_label, week_spans_months,
)
from src.holidays_de import get_holidays
from src.tooltip import attach_tooltip
from src.mail import refresh_token_if_needed, TokenAuthError, TokenNetworkError
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
    FONT, FONT_BOLD, FONT_HEADER, FONT_HEADER_SMALL, FONT_FOOTER, FONT_SMALL, FONT_TINY,
    CELL_BG_HOVER, WEEKEND_BG_HOVER, ENTRY_BG_HOVER, WEEKEND_ENTRY_BG_HOVER,
    apply_dark_titlebar,
    icon_button, label_button, secondary_button, set_toggle_active, toggle_button,
)

class App:
    def __init__(self, root, storage, settings, base_path=".", conflicts_store=None):
        self.root = root
        self.storage = storage
        self.settings = settings
        self.base_path = base_path
        self.conflicts_store = conflicts_store
        self.root.title(f"Zeiterfassung v{VERSION}")
        self.root.configure(bg=BG)
        apply_dark_titlebar(self.root)

        # Set unique AppUserModelID so Windows shows our icon in taskbar
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("margenheld.zeiterfassung")
        except Exception:
            pass

        # Set window/taskbar icon
        ico_path = os.path.join(base_path, "assets", "margenheld-icon.ico")
        png_path = os.path.join(base_path, "assets", "margenheld-icon.png")
        if platform.system() == "Windows" and os.path.exists(ico_path):
            self.root.iconbitmap(ico_path)
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
        self.root.bind("<Left>", lambda e: self._prev())
        self.root.bind("<Right>", lambda e: self._next())
        self._refresh()
        self._proactive_token_refresh()
        self._update_banner = None
        self._proactive_update_check()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _proactive_token_refresh(self):
        """Erneuert den Gmail-Token beim App-Start im Hintergrund.

        Auth-Fehler werden als Messagebox gezeigt, Netzwerkfehler still
        übergangen, damit ein Offline-Start nicht stört.
        """
        token_path = os.path.join(self.base_path, "token.json")

        def worker():
            try:
                refresh_token_if_needed(token_path)
            except TokenAuthError as e:
                msg = str(e)
                self.root.after(0, lambda: messagebox.showwarning(
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
                self.root.after(0, lambda: messagebox.showerror(
                    "Token-Refresh fehlgeschlagen", err
                ))

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

        icon_button(frame, "\u203a", self._next).pack(side=tk.RIGHT, padx=(0, 5))

        # --- Sync-Button und Status (Multi-Device-Sync, Phase 4.5) ---
        self.sync_button = icon_button(frame, "\u27f3", self._on_sync_clicked)
        self.sync_button.pack(side=tk.RIGHT, padx=(4, 0))
        self.sync_status_label = tk.Label(frame, text="", bg=BG, fg=TEXT_MUTED, font=FONT_SMALL)
        self.sync_status_label.pack(side=tk.RIGHT, padx=(8, 4))
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
        open_settings_dialog(
            self.root, self.settings, self.base_path,
            on_change=self._refresh,
            conflicts_store=self.conflicts_store,
            storage=self.storage,
        )

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
            self.root.geometry(
                f"{self.root.winfo_reqwidth()}x{self.root.winfo_reqheight()}"
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

    def _build_entry_cell(self, parent, date_str, day_text, entry, is_weekend, pad, cell_size=None):
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
        # FONT_TINY (7pt) statt FONT_SMALL (8pt), damit "HH:MM-HH:MM" in die
        # pixel-fixierte Standardzelle (width=8 in FONT) reinpasst.
        time_lbl = tk.Label(
            cell, text=f"{entry['start']}-{entry['end']}",
            font=FONT_TINY, bg=bg, fg=TEXT_MUTED, cursor="hand2",
        )
        time_lbl.pack(pady=(0, pad))
        for w in (cell, day_lbl, time_lbl):
            w.bind("<Button-1>", lambda e, d=date_str: self._open_dialog(d))
            w.bind("<Button-3>", lambda e, d=date_str: self._delete_entry(d))
            w.bind("<Enter>", lambda e, c=cell, dl=day_lbl, tl=time_lbl, hb=hover_bg: self._cell_hover(c, dl, tl, hb))
            w.bind("<Leave>", lambda e, c=cell, dl=day_lbl, tl=time_lbl, ob=bg: self._cell_hover(c, dl, tl, ob))
        return cell

    def _build_empty_cell(self, parent, date_str, day_text, is_weekend, height):
        bg = WEEKEND_BG if is_weekend else CELL_BG
        hover_bg = WEEKEND_BG_HOVER if is_weekend else CELL_BG_HOVER
        fg = WEEKEND_FG if is_weekend else TEXT
        cell = tk.Label(
            parent, text=day_text, font=FONT,
            bg=bg, fg=fg, relief=tk.FLAT,
            width=8, height=height, cursor="hand2",
        )
        cell.bind("<Button-1>", lambda e, d=date_str: self._open_dialog(d))
        cell.bind("<Enter>", lambda e, c=cell, hb=hover_bg: c.config(bg=hb))
        cell.bind("<Leave>", lambda e, c=cell, ob=bg: c.config(bg=ob))
        return cell

    def _build_day_cell(self, parent, date_str, day_text, day_date, is_weekend,
                        entry, holidays_map, pad, empty_height,
                        holiday_max_len, holiday_cell_size=None,
                        entry_cell_size=None):
        """Dispatcht auf Entry-, Holiday- oder Empty-Zelle und liefert die fertig
        konfigurierte Widget-Instanz. Caller grided das Ergebnis selbst."""
        if entry:
            cell = self._build_entry_cell(
                parent, date_str, day_text, entry, is_weekend, pad,
                cell_size=entry_cell_size,
            )
            if day_date in holidays_map:
                attach_tooltip(cell, f"Feiertag: {holidays_map[day_date]}")
            return cell
        if day_date in holidays_map:
            return self._build_holiday_cell(
                parent, day_text=day_text,
                name=holidays_map[day_date], max_name_len=holiday_max_len,
                on_click=lambda d=date_str: self._open_dialog(d),
                cell_size=holiday_cell_size,
            )
        return self._build_empty_cell(
            parent, date_str, day_text, is_weekend, empty_height,
        )

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

    def _refresh_month(self):
        # In den versteckten Backbuffer bauen, dann via lift() in den Vordergrund
        # holen — verhindert sichtbare leere Fläche zwischen Refreshes.
        new_frame = self._get_inactive_grid()
        self._build_grid_header(new_frame)

        cal = calendar.Calendar(firstweekday=0)
        entries = self.storage.get_all()
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
        probe = tk.Label(new_frame, text="", font=FONT, width=8, height=3)
        probe.update_idletasks()
        cell_size = (probe.winfo_reqwidth(), probe.winfo_reqheight())
        probe.destroy()

        # Auf 6 Wochen padden, damit die Fensterhöhe zwischen Monaten konstant
        # bleibt und `geometry("")` in `_refresh` keinen sichtbaren Resize auslöst.
        n = self._visible_day_count()
        weeks = cal.monthdayscalendar(self.year, self.month)
        while len(weeks) < 6:
            weeks.append([0] * 7)

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
                    pad=4, empty_height=3, holiday_max_len=12,
                    holiday_cell_size=cell_size,
                    entry_cell_size=cell_size,
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
        probe = tk.Label(new_frame, text="", font=FONT, width=8, height=5)
        probe.update_idletasks()
        cell_size = (probe.winfo_reqwidth(), probe.winfo_reqheight())
        probe.destroy()

        n = self._visible_day_count()
        for col, day_date in enumerate(dates[:n]):
            date_str = day_date.isoformat()
            entry = entries.get(date_str)
            if entry:
                total_hours += self._entry_hours(entry)
            day_text = f"{day_date.day}.{day_date.month}." if spans else str(day_date.day)

            cell = self._build_day_cell(
                new_frame, date_str, day_text, day_date,
                is_weekend=col >= 5, entry=entry, holidays_map=holidays_map,
                pad=8, empty_height=5, holiday_max_len=18,
                holiday_cell_size=cell_size,
                entry_cell_size=cell_size,
            )
            cell.grid(row=1, column=col, sticky="nsew", padx=2, pady=2)

        self._activate_grid(new_frame)
        self._update_footer(total_hours)

    @staticmethod
    def _truncate(text: str, max_len: int) -> str:
        if len(text) <= max_len:
            return text
        return text[: max_len - 1] + "…"

    def _build_holiday_cell(self, parent, day_text, name, max_name_len, on_click, cell_size=None):
        """Grüne Feiertagszelle. Layout analog zur Eintragszelle.

        cell_size: optional (width_px, height_px). Wenn gesetzt, wird der Frame
        auf diese Pixel-Größe fixiert (verhindert Aufweitung der Spalte durch
        längere Namen — relevant für die Wochenansicht).
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
            font=FONT_SMALL, bg=HOLIDAY_BG, fg=TEXT_MUTED, cursor="hand2",
        )
        name_lbl.pack(pady=(0, 4))

        for w in (cell, day_lbl, name_lbl):
            w.bind("<Button-1>", lambda e: on_click())
            w.bind("<Enter>", lambda e, c=cell, dl=day_lbl, nl=name_lbl:
                self._cell_hover(c, dl, nl, HOLIDAY_BG_HOVER))
            w.bind("<Leave>", lambda e, c=cell, dl=day_lbl, nl=name_lbl:
                self._cell_hover(c, dl, nl, HOLIDAY_BG))
        if truncated != name:
            # Nur am äußersten Frame binden, sonst gleichzeitige Tooltips, weil
            # Tk Enter-Events an Frame und Child unabhängig schickt.
            attach_tooltip(cell, name)
        return cell

    @staticmethod
    def _cell_hover(frame, day_lbl, time_lbl, bg):
        frame.config(bg=bg)
        day_lbl.config(bg=bg)
        time_lbl.config(bg=bg)

    def _delete_entry(self, date_str):
        if messagebox.askyesno("Eintrag löschen", f"Eintrag für {date_str} löschen?"):
            self.storage.delete(date_str)
            self._refresh()

    def _open_dialog(self, date_str):
        open_entry_dialog(
            self.root, date_str, self.storage, self.settings,
            on_change=self._refresh,
        )

    def _send(self):
        open_send_dialog(self.root, self.storage, self.settings, self.base_path)

    def on_sync_pull_success(self):
        """Wird aus dem UI-Thread nach erfolgreichem Pull aufgerufen."""
        # _refresh() re-renders the full calendar grid (month or week view).
        self._refresh()
        self._update_sync_status_label()

    def on_sync_pull_error(self, error):
        import tkinter.messagebox as mb
        mb.showerror("Synchronisation fehlgeschlagen",
                      f"Beim Abrufen der Drive-Daten ist ein Fehler aufgetreten:\n\n{error}")
        self._update_sync_status_label()

    def _update_sync_status_label(self):
        if not hasattr(self, "sync_status_label"):
            return
        if not self.settings.get("sync_enabled"):
            self.sync_status_label.config(text="")
            return
        n = 0
        if self.conflicts_store is not None:
            n = self.conflicts_store.count_unresolved()
        if n > 0:
            self.sync_status_label.config(text=f"⚠ {n} Konflikt{'e' if n != 1 else ''}")
        else:
            last = self.settings.get("last_pull_at") or "noch nie"
            self.sync_status_label.config(text=f"✓ {last[:10] if len(last) >= 10 else last}")

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
            ok = _run_push_blocking(
                self.storage, self.settings, self.conflicts_store,
                self.base_path, timeout_seconds=15,
            )
            self.root.after(0, lambda: self._on_manual_sync_done(ok))
        threading.Thread(target=_do, daemon=True).start()

    def _on_manual_sync_done(self, ok):
        if not ok:
            import tkinter.messagebox as mb
            mb.showerror("Synchronisation", "Synchronisation fehlgeschlagen. Logs prüfen.")
        self._update_sync_status_label()

    def _on_close(self):
        if self.settings.get("sync_enabled"):
            from src.main import _run_push_blocking
            try:
                _run_push_blocking(self.storage, self.settings, self.conflicts_store,
                                    self.base_path, timeout_seconds=5)
            except Exception:
                pass
        self.root.destroy()
