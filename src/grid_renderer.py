"""Kalender-/Grid-Rendering der App (Monats-/Wochenansicht, Zelltypen,
Double-Buffer). Eigenständig herausgelöst aus dem App-God-Object (#49).

Tk-nutzend, aber kein src.ui-Import. Datum/View ist NICHT Renderer-Eigentum:
es kommt per refresh(...)/measure_max_width(...)-Parametern; App bleibt die
Quelle (von _navigate/_set_view mutiert)."""

import calendar
import datetime
import platform
import tkinter as tk

from src.time_utils import (
    DAYS_DE, MONTHS_DE,
    calculate_hours, format_hours_colon, format_iso_date, format_minutes_hm,
    get_week_dates, get_week_label, hours_to_minutes, week_spans_months,
)
from src.holidays_de import get_holidays
from src.tooltip import attach_tooltip
from src.vacations import period_for_day
from src.theme import (
    BG, CELL_BG, WEEKEND_BG, ACCENT, TEXT, TEXT_MUTED,
    ENTRY_BG, WEEKEND_ENTRY_BG, WEEKEND_FG,
    HOLIDAY_BG, HOLIDAY_BG_HOVER, HOLIDAY_ACCENT,
    RESERVATION_ACCENT, TODAY_ACCENT,
    VACATION_BG, VACATION_BG_HOVER, VACATION_ACCENT,
    CELL_BG_HOVER, WEEKEND_BG_HOVER, ENTRY_BG_HOVER, WEEKEND_ENTRY_BG_HOVER,
    FONT, FONT_BOLD, FONT_TINY, FONT_SMALL, FONT_HEADER, FONT_HEADER_SMALL,
    _should_show_delete_button,
)

# Probe-Label-Geometrie zur Zellgrößen-Messung (aus ui.py übernommen).
# HEIGHT=4: die Eintragszelle trägt drei Textzeilen (Tagnummer, brutto
# start-end, Netto-Stunden) — bei 3 schnitt pack_propagate(False) die
# Stunden-Zeile ab.
PROBE_WIDTH_WIDE = 12
PROBE_WIDTH_NARROW = 8
PROBE_HEIGHT = 4


class GridRenderer:
    def __init__(self, root, storage, settings, reservation_store, conflicts_store,
                 on_cell_click, on_cell_right_click, reservations_active,
                 vacation_store=None):
        self._root = root
        self._storage = storage
        self._settings = settings
        self._reservation_store = reservation_store
        self._conflicts_store = conflicts_store
        self._on_cell_click = on_cell_click            # (date_str) -> None
        self._on_cell_right_click = on_cell_right_click  # (date_str) -> None
        self._reservations_active = reservations_active  # () -> bool
        self._vacation_store = vacation_store
        # Rendering-State:
        self.grid_container = None
        self._grid_frames = []
        self._active_grid_idx = 0
        self._grid_frame = None
        self._header_label = None
        self._footer_label = None
        self._header_width_spacer = None
        self._fixed_width = None
        self._suppress_geometry = False
        self._last_refresh_view = None
        self._last_refresh_columns = None
        self._last_footer_wide = None
        # Transienter Datum/View-Stand (von refresh gesetzt; Defaults nur
        # Platzhalter, refresh() ueberschreibt sie vor jedem Render).
        self._view_mode = "month"
        self._year = 0
        self._month = 0
        self._iso_year = 0
        self._current_week = 0

    def build_grid(self, parent):
        # Double-Buffer: zwei dauerhafte Frames im selben Grid-Slot. Refresh
        # baut in den inaktiven (versteckt unter dem aktiven), dann lift()
        # tauscht atomar.
        self.grid_container = tk.Frame(parent, bg=BG)
        self.grid_container.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        self.grid_container.rowconfigure(0, weight=1)
        self.grid_container.columnconfigure(0, weight=1)
        self._grid_frames = []
        for _ in range(2):
            f = tk.Frame(self.grid_container, bg=BG)
            f.grid(row=0, column=0, sticky="nsew")
            for col in range(7):
                f.columnconfigure(col, weight=1)
            self._grid_frames.append(f)
        self._grid_frames[0].lift()
        self._active_grid_idx = 0
        self._grid_frame = self._grid_frames[0]

    def attach_labels(self, header_label, footer_label, header_width_spacer):
        self._header_label = header_label
        self._footer_label = footer_label
        self._header_width_spacer = header_width_spacer

    def refresh(self, view_mode: str, year: int, month: int,
                iso_year: int, current_week: int):
        self._view_mode = view_mode
        self._year = year
        self._month = month
        self._iso_year = iso_year
        self._current_week = current_week
        if self._view_mode == "month":
            # FONT_HEADER (16pt) + width=16 — längste Variante "September 2026".
            font, width = FONT_HEADER, 16
            self._header_label.config(
                text=f"{MONTHS_DE[self._month]} {self._year}", font=font, width=width,
            )
            self._refresh_month()
        else:
            # FONT_HEADER_SMALL (12pt) + width=32 — KW-Variante mit Jahreswechsel.
            font, width = FONT_HEADER_SMALL, 32
            self._header_label.config(
                text=get_week_label(self._iso_year, self._current_week),
                font=font, width=width,
            )
            self._refresh_week()
        # header_width_spacer steht (unsichtbar) an header_labels alter pack-
        # Position, damit dessen Breitenbedarf weiter in die reqwidth des
        # Frames eingeht — header_label selbst ist per `place` zentriert und
        # zählt dafür nicht mehr mit (s. ui.py::_build_header).
        self._header_width_spacer.config(font=font, width=width)
        current_cols = self._visible_day_count()
        view_changed = self._last_refresh_view != self._view_mode
        cols_changed = self._last_refresh_columns != current_cols
        if view_changed or cols_changed:
            self._last_refresh_view = self._view_mode
            self._last_refresh_columns = current_cols
            # Inactive-Frame komplett ersetzen umgeht Tks reqheight-Cache.
            inactive_idx = 1 - self._active_grid_idx
            self._grid_frames[inactive_idx].destroy()
            new_inactive = tk.Frame(self.grid_container, bg=BG)
            new_inactive.grid(row=0, column=0, sticky="nsew")
            for col in range(7):
                new_inactive.columnconfigure(col, weight=1 if col < current_cols else 0)
            self._grid_frames[inactive_idx] = new_inactive
            self._grid_frames[self._active_grid_idx].lift()

        # Footer-Reservierung (s. _update_footer) wechselt die Breite, wenn der
        # Stundenlohn zur Laufzeit gesetzt/entfernt wird — dann muss die fixe
        # Fensterbreite nachziehen, auch ohne Spalten-/View-Wechsel, sonst würde
        # die breitere Lohn-Variante unter dem fixen Fenster abgeschnitten.
        footer_wide = (self._settings.get("hourly_rate") or 0) > 0
        if view_changed or cols_changed or self._last_footer_wide != footer_wide:
            self._last_footer_wide = footer_wide
            self.repin_geometry()

    def repin_geometry(self):
        """Pinnt Fensterbreite (>= gemessenes Maximum) und -höhe (aktuelle
        reqheight) neu auf die fixe Geometrie.

        Aufrufer: der View-/Spalten-Wechsel in refresh() **und** das Ein-/
        Ausblenden des Update-Banners (UpdateBanner._show/_dismiss über einen
        injizierten Callback) — der ändert die nötige Höhe, ohne dass sich View
        oder Spaltenzahl ändern, würde also sonst nicht nachgeführt und liefe
        unter dem fixen Fenster über (#92). Das Fenster bleibt
        resizable(False, False); gewachsen/geschrumpft wird nur kontrolliert
        hier. Während der Vorab-Messung (measure_max_width) unterdrückt
        _suppress_geometry den Resize.

        Die Breite **ratcht**: _fixed_width wächst mit der breitesten je
        angeforderten reqwidth mit, schrumpft aber nie wieder. Grund: der Footer
        ist ohne Stundenlohn schmal (width=20) und mit Lohn breit (width=42,
        s. _update_footer). Startet die App ohne Lohn, pinnt measure_max_width
        die schmale Breite; trägt der Nutzer später einen Lohn ein, wächst das
        Fenster hier einmalig auf die breite Variante. Ohne Ratchet würde es beim
        Entfernen des Lohns wieder zurückschrumpfen und bei jedem Lohn-Ein/Aus
        zwischen schmal und breit springen. Die Höhe ratcht bewusst NICHT (das
        Update-Banner braucht sie in beide Richtungen)."""
        self._root.update_idletasks()
        if not self._suppress_geometry:
            width = max(self._fixed_width or 0, self._root.winfo_reqwidth())
            self._fixed_width = width
            self._root.geometry(f"{width}x{self._root.winfo_reqheight()}")

    def measure_max_width(self, view_mode: str, year: int, month: int,
                          iso_year: int, current_week: int):
        """Pre-warm: rendert alle 4 (view × show_weekend)-Kombinationen einmal
        in den versteckten Backbuffer und merkt die maximale reqwidth intern
        (self._fixed_width). show_weekend wird über settings.override_in_memory
        temporär verstellt (kein Disk-Save, danach wiederhergestellt);
        _suppress_geometry verhindert den Resize während der Messung. Läuft vor
        mainloop()."""
        max_w = 0
        self._suppress_geometry = True
        try:
            for view in ("month", "week"):
                for weekend in (True, False):
                    with self._settings.override_in_memory("show_weekend", weekend):
                        self._last_refresh_view = None
                        self._last_refresh_columns = None
                        self.refresh(view, year, month, iso_year, current_week)
                        self._root.update_idletasks()
                        w = self._root.winfo_reqwidth()
                        if w > max_w:
                            max_w = w
        finally:
            self._suppress_geometry = False
            self._last_refresh_view = None
            self._last_refresh_columns = None
        self._fixed_width = max_w
        return max_w

    def _visible_day_count(self):
        """Sichtbare Wochentag-Spalten (5 bei show_weekend=False, sonst 7).

        `workweek_only` überstimmt `show_weekend`: im Nur-Werktage-Modus sind
        Sa/So immer aus (die Checkbox im App-Tab ist dann deaktiviert).

        Wird von _build_grid_header und den Refresh-Pfaden als einzige
        Quelle der Wahrheit konsultiert.
        """
        if self._settings.get("workweek_only"):
            return 5
        return 7 if self._settings.get("show_weekend") else 5

    def _wide_cells(self):
        """Breite Zellen, sobald nur 5 Spalten sichtbar sind (5 Spalten = mehr
        Horizontalplatz je Spalte). Aus _visible_day_count abgeleitet, damit
        workweek_only mitzieht — nicht show_weekend erneut lesen.
        """
        return self._visible_day_count() == 5

    def _build_grid_header(self, parent):
        n = self._visible_day_count()
        for col, day_name in enumerate(DAYS_DE[:n]):
            fg = TEXT_MUTED if col < 5 else WEEKEND_FG
            tk.Label(
                parent, text=day_name, font=FONT_BOLD, bg=BG, fg=fg,
            ).grid(row=0, column=col, sticky="nsew", padx=2, pady=2)

    def _build_entry_cell(self, parent, date_str, day_text, entry, is_weekend, pad,
                          cell_size=None, time_font=FONT_TINY, bg=None, hover_bg=None):
        # bg/hover_bg übersteuern die Wochenend-Ableitung: ein Urlaubstag MIT
        # erfasster Ist-Zeit („halber Urlaubstag") behält Zeit- und
        # Stundenzeile, wechselt aber den Untergrund. Ohne Übersteuerung
        # verhält sich die Zelle exakt wie bisher.
        if bg is None:
            bg = WEEKEND_ENTRY_BG if is_weekend else ENTRY_BG
        if hover_bg is None:
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
        time_lbl.pack()
        # Netto-Stunden unter der Brutto-Zeit: macht den Footer nachrechenbar.
        # Gleiche Schrift wie die Zeit-Zeile, aber kräftigeres fg — die Stunden
        # sind die Zahl, um die es geht, start-end ist der Beleg dazu.
        hours_lbl = tk.Label(
            cell, text=self._fmt_cell_hours(entry),
            font=time_font, bg=bg, fg=TEXT, cursor="hand2",
        )
        hours_lbl.pack(pady=(0, pad))
        labels = (day_lbl, time_lbl, hours_lbl)
        for w in (cell, *labels):
            w.bind("<Button-1>", lambda e, d=date_str: self._on_cell_click(d))
            w.bind("<Button-3>", lambda e, d=date_str: self._on_cell_right_click(d))
            w.bind("<Enter>", lambda e, c=cell, ls=labels, hb=hover_bg: self._hover(c, hb, *ls))
            w.bind("<Leave>", lambda e, c=cell, ls=labels, ob=bg: self._hover(c, ob, *ls))
        return cell

    def _build_vacation_cell(self, parent, date_str, day_text, minutes, pad,
                             cell_size, time_font=FONT_TINY):
        """Urlaubstag ohne erfasste Ist-Zeit: Tagnummer, „Urlaub" und die
        Stundenzeile nur, wenn der Tag Minuten trägt. Wochenend- und
        Feiertags-Tage einer Periode stehen mit 0 Minuten im Store — sie
        werden eingefärbt (der Zeitraum bleibt als Block sichtbar), zeigen
        aber keine Dauer.

        Stundenformat H:MM wie in _fmt_cell_hours — dort ist begründet, warum
        die Zelle NICHT `format_minutes_hm` spricht: zwei Notationen fürs
        selbe im selben Fenster lasen sich widersprüchlich, und „7 h 30 min"
        sind 10 Zeichen in einer auf 8 fixierten Zelle. Der Tooltip darf
        `format_minutes_hm` behalten — dort ist Platz.
        """
        bg, hover_bg = VACATION_BG, VACATION_BG_HOVER
        cell = tk.Frame(
            parent, bg=bg, relief=tk.SOLID,
            highlightbackground=VACATION_ACCENT, highlightthickness=1,
            cursor="hand2",
        )
        if cell_size is not None:
            cell.config(width=cell_size[0], height=cell_size[1])
            cell.pack_propagate(False)
        day_lbl = tk.Label(cell, text=day_text, font=FONT, bg=bg, fg=TEXT,
                           cursor="hand2")
        day_lbl.pack(pady=(pad, 0))
        name_lbl = tk.Label(cell, text="Urlaub", font=time_font, bg=bg,
                            fg=VACATION_ACCENT, cursor="hand2")
        name_lbl.pack()
        hours_lbl = tk.Label(
            cell,
            text=f"{format_hours_colon(minutes / 60)} h" if minutes else "",
            font=time_font, bg=bg, fg=TEXT, cursor="hand2")
        hours_lbl.pack(pady=(0, pad))
        labels = (day_lbl, name_lbl, hours_lbl)
        for w in (cell, *labels):
            w.bind("<Button-1>", lambda e, d=date_str: self._on_cell_click(d))
            w.bind("<Button-3>", lambda e, d=date_str: self._on_cell_right_click(d))
            w.bind("<Enter>", lambda e, c=cell, ls=labels, hb=hover_bg: self._hover(c, hb, *ls))
            w.bind("<Leave>", lambda e, c=cell, ls=labels, ob=bg: self._hover(c, ob, *ls))
        return cell

    @staticmethod
    def _fmt_slot_line(slot):
        """Eine Tooltip-Zeile für einen Slot: 'HH:MM-HH:MM  Kategorie'
        (Kategorie weggelassen, wenn leer)."""
        kat = f"  {slot['kategorie']}" if slot.get("kategorie") else ""
        return f"{slot['start']}-{slot['end']}{kat}"

    @staticmethod
    def _build_tooltip_text(entry, reservation, holiday_name, has_conflict=False,
                            vacation=None, vacation_minutes=0):
        """Baut den kombinierten Hover-Tooltip aus den vorhandenen Einheiten.

        Reine Funktion (Tk-frei, testbar): entscheidet, WELCHE Blöcke der
        Tooltip enthält und in welcher Reihenfolge. Gibt "" zurück, wenn nichts
        anzuzeigen ist.

        vacation: die Urlaubsperiode dieses Tages (mit `name`/`from`/`to`) oder
        None; vacation_minutes die Minuten DIESES Tages — Wochenend- und
        Feiertags-Tage einer Periode tragen 0 und zeigen dann keine Dauer.
        Der Periodenname steht bewusst nur hier und im Verwaltungs-Dialog:
        im Bericht heißt es schlicht „Urlaub".

        holiday_name: Feiertagsname, falls der Tag ein Feiertag ist, sonst None.
        Er kommt in den kombinierten Tooltip, sobald ohnehin ein Eintrag, eine
        Reservierung ODER ein Urlaub vorliegt — in all diesen Fällen zeigt die
        Zelle den Namen nicht mehr selbst als Zelltext.

        has_conflict: der Konflikt-Hinweis wird in DENSELBEN Tooltip gefaltet
        (Audit M11) — ein zweiter attach_tooltip am selben Widget verletzte den
        'genau EIN Tooltip pro Zelle'-Invariant.
        """
        parts = []
        if entry and entry.get("slots"):
            parts.append(
                "Arbeitszeit:\n"
                + "\n".join(
                    GridRenderer._fmt_slot_line(s) for s in entry["slots"]))
        if reservation is not None:
            parts.append(
                "Reservierung:\n"
                + "\n".join(
                    GridRenderer._fmt_slot_line(s)
                    for s in reservation.get("slots", [])))
        if vacation is not None:
            span = (f"{format_iso_date(vacation.get('from'))} – "
                    f"{format_iso_date(vacation.get('to'))}")
            if vacation_minutes:
                span += f"  ·  {format_minutes_hm(vacation_minutes)}"
            parts.append(f"Urlaub: {vacation.get('name', '')}\n{span}")
        if holiday_name and (reservation is not None or entry
                             or vacation is not None):
            parts.append(f"Feiertag: {holiday_name}")
        if has_conflict:
            parts.append("Konflikt — bitte auflösen")
        return "\n".join(parts)

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
        Klick ruft denselben _on_cell_right_click-Pfad wie der Win/Linux-Rechtsklick
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
                 lambda e, d=date_str: (self._on_cell_right_click(d), "break")[1])
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
            w.bind("<Button-1>", lambda e, d=date_str: self._on_cell_click(d))
            w.bind("<Button-3>", lambda e, d=date_str: self._on_cell_right_click(d))
            w.bind("<Enter>", lambda e, c=cell, dl=day_lbl, hb=hover_bg: self._hover(c, hb, dl))
            w.bind("<Leave>", lambda e, c=cell, dl=day_lbl, ob=bg: self._hover(c, ob, dl))
        return cell

    def _build_day_cell(self, parent, date_str, day_text, day_date, is_weekend,
                        entry, holidays_map, pad,
                        holiday_max_len, cell_size, conflict_dates=None,
                        entry_time_font=FONT_TINY, holiday_name_font=FONT_SMALL,
                        reservation=None, vacation=None):
        """Dispatcht auf Vacation-, Entry-, Holiday- oder Empty-Zelle.

        vacation: die Urlaubsperiode dieses Tages oder None. Urlaub GEWINNT —
        er färbt die Zelle auch über Feiertag und Wochenende hinweg, damit der
        Zeitraum im Kalender ein durchgehender Block bleibt. Der Feiertagsname
        geht dabei nicht verloren: er wandert in den kombinierten Tooltip.
        Liegt am selben Tag Ist-Zeit vor („halber Urlaubstag"), wird weiterhin
        die Eintragszelle gebaut — nur mit dem Urlaubs-Untergrund. Der Inhalt
        (Zeiten, Stunden) bleibt sichtbar.

        reservation: optionales {slots} für den Tag. Eine Reservierung ändert
        den Zelltyp NICHT — sie wird ausschließlich als kleiner violetter
        Eck-Punkt (plus Tooltip) auf die ohnehin gebaute Zelle gelegt.
        """
        is_holiday = day_date in holidays_map
        # Minuten aus der Periode selbst — sie bringt ihre `days` mit, eine
        # zweite Store-Sicht wäre eine zweite Quelle für dieselbe Zahl.
        vacation_minutes = (
            vacation.get("days", {}).get(date_str, 0) if vacation else 0)
        if entry:
            cell = self._build_entry_cell(
                parent, date_str, day_text, entry, is_weekend, pad,
                cell_size=cell_size, time_font=entry_time_font,
                bg=VACATION_BG if vacation is not None else None,
                hover_bg=VACATION_BG_HOVER if vacation is not None else None,
            )
        elif vacation is not None:
            cell = self._build_vacation_cell(
                parent, date_str, day_text, vacation_minutes, pad,
                cell_size=cell_size, time_font=entry_time_font,
            )
        elif is_holiday:
            cell = self._build_holiday_cell(
                parent, day_text=day_text,
                name=holidays_map[day_date], max_name_len=holiday_max_len,
                on_click=lambda d=date_str: self._on_cell_click(d),
                on_right_click=lambda d=date_str: self._on_cell_right_click(d),
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
        # (Arbeitszeit-Slots, Reservierung, Urlaub, Feiertag, Konflikt-Hinweis)
        # in einen kombinierten Tooltip (Textaufbau in _build_tooltip_text). Ein
        # Feiertag OHNE Eintrag/Reservierung/Urlaub zeigt seinen Namen weiterhin
        # als Zelltext (Holiday-Zelle) bzw. eigenen Tooltip (name_tooltip) und
        # kommt hier NICHT rein.
        has_conflict = bool(conflict_dates and date_str in conflict_dates)
        if reservation is not None:
            self._add_reservation_marker(cell)
        tip_text = self._build_tooltip_text(
            entry, reservation,
            holidays_map[day_date] if is_holiday else None,
            has_conflict=has_conflict,
            vacation=vacation, vacation_minutes=vacation_minutes)
        if tip_text:
            attach_tooltip(cell, tip_text)

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

        # Der Konflikt-Hinweis steckt bereits im kombinierten Tooltip oben
        # (has_conflict → _build_tooltip_text, Audit M11); hier nur noch der
        # orange Rand als visuelle Markierung, KEIN zweiter attach_tooltip.
        if has_conflict:
            cell.configure(highlightbackground="orange", highlightthickness=2)

        return cell

    def _get_inactive_grid(self):
        """Liefert das versteckte Grid-Frame (Double-Buffer-Backbuffer).
        Children, Row- und Column-Config werden zurückgesetzt. Nur sichtbare
        Spalten erhalten weight=1 — ausgeblendete (Sa/So bei show_weekend=False)
        würden sonst den vom Header/Footer geforderten Extra-Platz absorbieren
        und einen Leerraum-Streifen rechts neben Fr produzieren."""
        inactive = self._grid_frames[1 - self._active_grid_idx]
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
        self._grid_frame = frame

    def _update_footer(self, total_minutes):
        """Footer aus den ANGEZEIGTEN Minuten der Zellen, nicht aus der Summe
        der Dezimalstunden — sonst weicht die Gesamtsumme von der Summe ab,
        die der Nutzer in den Zellen sieht (s. hours_to_minutes)."""
        rate = self._settings.get("hourly_rate") or 0
        total_text = format_minutes_hm(total_minutes)
        # width fixiert die reqwidth des Labels → kein Pack-Reflow, wenn sich die
        # Summe beim Monatswechsel ändert. Die Reservierung hängt am Stundenlohn:
        # mit Lohn deckt width=42 die längste Variante ab
        # ("Gesamt: 999 h 50 min  —  99999.99 € brutto" ≈ 42 Zeichen); ohne Lohn
        # zeigt der Footer nur "Gesamt: X h Y min" (≤ 20 Zeichen), dann genügt
        # width=20 — sonst
        # zöge die leere 40-Zeichen-Reservierung das Fenster unnötig breiter als
        # das Kalender-Grid (der Footer packt fill=X unter der Root und geht so in
        # deren reqwidth ein). refresh() pinnt die Breite neu, wenn der Lohn zur
        # Laufzeit gesetzt/entfernt wird (Wechsel der Reservierungsbreite).
        if rate > 0:
            # Geld aus DEMSELBEN Minutenwert wie die angezeigte Summe —
            # sonst widersprächen sich Stunden- und Euro-Anzeige im selben
            # Footer (Differenz sub-Cent, aber sichtbar inkonsistent).
            brutto = round(total_minutes / 60 * rate, 2)
            self._footer_label.config(
                text=f"Gesamt: {total_text}  —  {brutto:.2f} € brutto",
                width=42,
            )
        else:
            self._footer_label.config(text=f"Gesamt: {total_text}", width=20)

    @staticmethod
    def _display_minutes(entry):
        """Die Minuten, die die Zelle für diesen Tag ANZEIGT.

        Der Footer summiert genau diese Werte auf — dadurch stimmt seine
        Summe per Konstruktion mit dem überein, was in den Zellen steht.
        """
        return hours_to_minutes(GridRenderer._entry_hours(entry))

    @staticmethod
    def _entry_hours(entry):
        return round(sum(
            calculate_hours(s["start"], s["end"], pause_minutes=s.get("pause", 0))
            for s in entry.get("slots", [])
        ), 2)

    @staticmethod
    def _fmt_cell_hours(entry):
        """Zellzeile 'H:MM h · PM': gezählte Netto-Stunden des Tages + die
        abgezogene Pause (Summe über alle Slots), "" ohne Slots.

        Die Zeit-Zeile darüber zeigt brutto start-end; ohne diese Zeile ist der
        Footer nicht nachrechenbar (die Pause ist unsichtbar abgezogen). Die
        Pause steht bewusst mit dran, damit ein Tag mit abweichender Pause
        (z.B. P0 unter 6 h, keine Pflichtpause) als Absicht erkennbar ist statt
        wie ein Vertipper auszusehen.

        H:MM statt Dezimalstunden, damit Zelle und Footer (format_hours_hm)
        dieselbe Schreibweise sprechen — zwei Notationen fürs selbe im selben
        Fenster lasen sich widersprüchlich. Kompaktform, weil die Zeile hier
        mit 'HH:MM-HH:MM' um die Spaltenbreite konkurriert.
        """
        slots = entry.get("slots", [])
        if not slots:
            return ""
        pause = sum(int(s.get("pause", 0)) for s in slots)
        return f"{format_hours_colon(GridRenderer._entry_hours(entry))} h · P{pause}"

    def _dates_with_unresolved_conflicts(self):
        """Gibt die Menge der ISO-Datums-Strings zurück, für die ungelöste
        Konflikte vom Typ 'entry' vorliegen."""
        if not self._conflicts_store:
            return set()
        return self._conflicts_store.unresolved_entry_keys()

    def _cell_layout_metrics(self, frame):
        """Misst die natuerliche Pixelgroesse einer Standard-Tageszelle (Probe-
        Label) und liefert die layout-abhaengigen Groessen.

        Bei ausgeblendetem Wochenende (5 statt 7 Spalten) bleibt mehr Horizontal-
        platz pro Spalte: breitere Zellen und groessere Zeit-/Feiertagsschrift
        (FONT statt FONT_SMALL), damit z.B. '09:30-17:00' bequem lesbar bleibt.
        Holiday-Zellen werden spaeter auf `cell_size` fixiert, damit lange
        Feiertagsnamen die Spalte nicht aufweiten (Header-Reflow/Flackern)."""
        wide_cells = self._wide_cells()
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
        entries = self._storage.get_all()
        reservations = (
            self._reservation_store.get_all() if self._reservations_active() else {})
        vacation_periods = (
            self._vacation_store.get_all() if self._vacation_store else {})
        total_minutes = 0

        state = self._settings.get("state")
        holidays_map = get_holidays(state, self._year) if state else {}

        cell_size, entry_time_font, holiday_name_font, wide_cells = \
            self._cell_layout_metrics(new_frame)

        # Auf 6 Wochen padden, damit die Fensterhöhe zwischen Monaten konstant
        # bleibt und `geometry("")` in `refresh` keinen sichtbaren Resize auslöst.
        n = self._visible_day_count()
        weeks = cal.monthdayscalendar(self._year, self._month)
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

                date_str = f"{self._year}-{self._month:02d}-{day:02d}"
                day_date = datetime.date(self._year, self._month, day)
                entry = entries.get(date_str)
                if entry:
                    total_minutes += self._display_minutes(entry)

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
                    vacation=period_for_day(vacation_periods, date_str),
                )
                cell.grid(row=row, column=col, sticky="nsew", padx=2, pady=2)

        row_min_h = cell_size[1] + 4  # +4 für pady=2 oben/unten
        for row in range(1, 7):
            new_frame.rowconfigure(row, minsize=row_min_h)

        self._activate_grid(new_frame)
        self._update_footer(total_minutes)

    def _refresh_week(self):
        new_frame = self._get_inactive_grid()
        self._build_grid_header(new_frame)

        dates = get_week_dates(self._iso_year, self._current_week)
        entries = self._storage.get_all()
        reservations = (
            self._reservation_store.get_all() if self._reservations_active() else {})
        vacation_periods = (
            self._vacation_store.get_all() if self._vacation_store else {})
        total_minutes = 0
        spans = week_spans_months(self._iso_year, self._current_week)
        state = self._settings.get("state")
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
                total_minutes += self._display_minutes(entry)
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
                vacation=period_for_day(vacation_periods, date_str),
            )
            cell.grid(row=1, column=col, sticky="nsew", padx=2, pady=2)

        self._activate_grid(new_frame)
        self._update_footer(total_minutes)

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
