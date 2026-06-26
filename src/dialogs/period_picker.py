import calendar
import datetime
import tkinter as tk

from src.report import total_hours
from src.theme import BG, CELL_BG, FONT, TEXT, dark_combo


def selected_category_filter(selected_map):
    """selected_map: {kategorie: bool}. Liefert None, wenn keine Kategorien
    existieren ODER alle ausgewählt sind (= kein Filter), sonst die Menge der
    ausgewählten Kategorien. Identisch zur bisherigen send_dialog-Semantik
    (`_selected_categories`)."""
    if not selected_map:
        return None
    selected = {kat for kat, on in selected_map.items() if on}
    if len(selected) == len(selected_map):
        return None
    return selected


def _default_from_date(today):
    """Vormonats-Pendant zu heute (Tag auf Monatslänge gekappt). Default für
    das Von-Datum."""
    if today.month == 1:
        return today.replace(year=today.year - 1, month=12)
    from_month = today.month - 1
    max_day = calendar.monthrange(today.year, from_month)[1]
    return today.replace(month=from_month, day=min(today.day, max_day))


class _PeriodPickerHandle:
    """Lese-Schnittstelle auf die Picker-Widgets, ohne dass der Aufrufer die
    Tk-Vars kennt."""

    def __init__(self, from_vars, to_vars, category_vars):
        self._from = from_vars        # (day_var, month_var, year_var)
        self._to = to_vars            # (day_var, month_var, year_var)
        self._cats = category_vars    # {kategorie: BooleanVar}

    def get_range(self):
        try:
            df = datetime.date(
                int(self._from[2].get()), int(self._from[1].get()), int(self._from[0].get()))
            dt = datetime.date(
                int(self._to[2].get()), int(self._to[1].get()), int(self._to[0].get()))
        except ValueError:
            return None, None
        return df, dt

    def get_categories(self):
        return selected_category_filter({k: v.get() for k, v in self._cats.items()})


def build_period_picker(parent, storage, settings, on_change=None):
    """Baut Von/Bis-Datumszeilen + Kategorie-Checkboxen + Live-Stundenvorschau
    in einen eigenen Frame. Liefert (frame, handle). Der Frame wird vom
    Aufrufer ins Dialog-Layout gegridded; die Aktions-Buttons bleiben Sache
    des Aufrufers (Senden bzw. Export).

    on_change: optionaler Callback, der bei jeder Benutzer-Änderung an Datum
    oder Kategorie-Auswahl gefeuert wird (z.B. damit der Export-Dialog seinen
    Button (de)aktivieren kann). Wird beim initialen Aufbau NICHT gefeuert —
    der Aufrufer setzt den Anfangszustand selbst."""
    frame = tk.Frame(parent, bg=BG)

    today = datetime.date.today()
    from_default = _default_from_date(today)
    month_values = [str(m) for m in range(1, 13)]
    year_values = [str(y) for y in range(2020, today.year + 2)]

    def update_day_values(day_cb, day_var, month_var, year_var):
        try:
            m = int(month_var.get())
            y = int(year_var.get())
            max_day = calendar.monthrange(y, m)[1]
        except (ValueError, KeyError):
            max_day = 31
        day_cb["values"] = [str(d) for d in range(1, max_day + 1)]
        if int(day_var.get()) > max_day:
            day_var.set(str(max_day))

    def build_date_row(row, label_text, default_date):
        tk.Label(frame, text=label_text, font=FONT, bg=BG, fg=TEXT).grid(
            row=row, column=0, padx=(10, 5), pady=8, sticky="w")
        day_var = tk.StringVar(value=str(default_date.day))
        max_day = calendar.monthrange(default_date.year, default_date.month)[1]
        day_cb = dark_combo(frame, day_var, [str(d) for d in range(1, max_day + 1)], width=3)
        day_cb.grid(row=row, column=1, padx=2, pady=8)
        tk.Label(frame, text=".", font=FONT, bg=BG, fg=TEXT).grid(row=row, column=2)
        month_var = tk.StringVar(value=str(default_date.month))
        dark_combo(frame, month_var, month_values, width=3).grid(row=row, column=3, padx=2, pady=8)
        tk.Label(frame, text=".", font=FONT, bg=BG, fg=TEXT).grid(row=row, column=4)
        year_var = tk.StringVar(value=str(default_date.year))
        dark_combo(frame, year_var, year_values, width=5).grid(row=row, column=5, padx=(2, 10), pady=8)
        month_var.trace_add("write", lambda *_: update_day_values(day_cb, day_var, month_var, year_var))
        year_var.trace_add("write", lambda *_: update_day_values(day_cb, day_var, month_var, year_var))
        return day_var, month_var, year_var

    from_vars = build_date_row(0, "Von:", from_default)
    to_vars = build_date_row(1, "Bis:", today)

    # Kategorien aus Bestand UND Settings-Pickliste ("" = ohne Kategorie). Alle
    # default ausgewählt. Bewusst NICHT auf den Zeitraum eingeschränkt (vgl.
    # bisheriger send_dialog-Kommentar).
    all_entries = storage.get_all()
    present_categories = sorted(
        {(s.get("kategorie") or "") for e in all_entries.values() for s in e["slots"]}
        | {c for c in (settings.get("categories") or [])},
        key=lambda k: (k == "", k.lower()),
    )
    category_vars = {}
    if present_categories:
        tk.Label(frame, text="Kategorien:", font=FONT, bg=BG, fg=TEXT).grid(
            row=2, column=0, padx=(10, 5), pady=(4, 8), sticky="nw")
        cat_frame = tk.Frame(frame, bg=BG)
        cat_frame.grid(row=2, column=1, columnspan=5, padx=(0, 10), pady=(4, 8), sticky="w")
        for kat in present_categories:
            var = tk.BooleanVar(value=True)
            category_vars[kat] = var
            label = kat if kat else "(ohne Kategorie)"
            tk.Checkbutton(
                cat_frame, text=label, variable=var,
                command=lambda: _changed(),
                font=FONT, bg=BG, fg=TEXT, selectcolor=CELL_BG,
                activebackground=BG, activeforeground=TEXT,
                highlightthickness=0, bd=0, anchor="w",
            ).pack(anchor="w")

    handle = _PeriodPickerHandle(from_vars, to_vars, category_vars)

    # Live-Vorschau (Gesamtstunden über den Build-Zeit-Snapshot all_entries).
    total_label = tk.Label(frame, text="", font=FONT, bg=BG, fg=TEXT)
    total_label.grid(row=3, column=0, columnspan=6, padx=10, pady=(0, 8), sticky="w")

    def _update_total(*_):
        df, dt = handle.get_range()
        if df is None or dt is None or df > dt:
            total_label.config(text="Gesamtstunden: —")
            return
        hours = total_hours(df, dt, all_entries, handle.get_categories())
        total_label.config(text=f"Gesamtstunden: {hours}h")

    def _changed(*_):
        # Benutzer-Änderung an Datum oder Kategorie: Vorschau aktualisieren und
        # den Aufrufer benachrichtigen (Export-Button (de)aktivieren).
        _update_total()
        if on_change is not None:
            on_change()

    for _v in (*from_vars, *to_vars):
        _v.trace_add("write", _changed)
    _update_total()

    return frame, handle
