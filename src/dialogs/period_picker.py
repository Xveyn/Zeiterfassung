import calendar
import datetime
import tkinter as tk

from src import workweek
from src.dialogs.date_row import build_date_row
from src.report import filter_period, total_hours
from src.theme import BG, CELL_BG, FONT, FONT_SMALL, TEXT, TEXT_MUTED


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

    def __init__(self, from_vars, to_vars, category_vars, breakdown_var,
                vacation_var=None):
        self._from = from_vars        # (day_var, month_var, year_var)
        self._to = to_vars            # (day_var, month_var, year_var)
        self._cats = category_vars    # {kategorie: BooleanVar}
        self._breakdown = breakdown_var  # BooleanVar
        self._vacation = vacation_var    # BooleanVar oder None

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

    def get_category_breakdown(self):
        """True = "Summe je Kategorie"-Tabelle in den Bericht aufnehmen."""
        return bool(self._breakdown.get())

    def get_show_vacation(self):
        """True = Urlaubs-Block in den Bericht aufnehmen. False, wenn der
        Schalter gar nicht gebaut wurde (kein Urlaub vorhanden)."""
        return bool(self._vacation.get()) if self._vacation is not None else False


def build_period_picker(parent, storage, settings, on_change=None,
                        from_default=None, to_default=None,
                        vacation_store=None):
    """Baut Von/Bis-Datumszeilen + Kategorie-Checkboxen + Live-Stundenvorschau
    in einen eigenen Frame. Liefert (frame, handle). Der Frame wird vom
    Aufrufer ins Dialog-Layout gegridded; die Aktions-Buttons bleiben Sache
    des Aufrufers (Senden bzw. Export).

    on_change: optionaler Callback, der bei jeder Benutzer-Änderung an Datum
    oder Kategorie-Auswahl gefeuert wird (z.B. damit der Export-Dialog seinen
    Button (de)aktivieren kann). Wird beim initialen Aufbau NICHT gefeuert —
    der Aufrufer setzt den Anfangszustand selbst.

    from_default / to_default: optionale Vorbelegung der Datumszeilen. Ohne
    sie gilt wie bisher „Vormonats-Pendant bis heute" (_default_from_date).

    vacation_store: optionaler Urlaubs-Store. Ohne ihn (oder ohne Urlaub im
    Bestand) wird der „Urlaub ausweisen"-Schalter gar nicht gebaut."""
    frame = tk.Frame(parent, bg=BG)

    today = datetime.date.today()
    from_value = from_default if from_default is not None else _default_from_date(today)
    to_value = to_default if to_default is not None else today

    # Von/Bis über das gemeinsame Datums-Zeilen-Widget (Audit M14). Der
    # on_change-Callback (Tag-Clamp + Vorschau) ist late-bound auf das weiter
    # unten definierte _changed; er feuert erst bei Benutzer-Interaktion, also
    # ist _changed dann längst gebunden. label_width=4 hält "Von:"/"Bis:"
    # untereinander bündig.
    from_row = build_date_row(frame, "Von:", from_value,
                              on_change=lambda: _changed(), label_width=4)
    to_row = build_date_row(frame, "Bis:", to_value,
                            on_change=lambda: _changed(), label_width=4)
    from_row.frame.grid(row=0, column=0, columnspan=6, sticky="w", padx=(10, 0), pady=8)
    to_row.frame.grid(row=1, column=0, columnspan=6, sticky="w", padx=(10, 0), pady=8)
    from_vars = from_row.vars
    to_vars = to_row.vars

    # Kategorien aus Bestand UND Settings-Pickliste ("" = ohne Kategorie). Alle
    # default ausgewählt. Bewusst NICHT auf den Zeitraum eingeschränkt (vgl.
    # bisheriger send_dialog-Kommentar). Seit dem Snapshot-Filter folgt sie
    # aber dem gefilterten Bestand (all_entries, s.u.): im Nur-Werktage-Modus
    # taucht eine Kategorie, die ausschließlich an Wochenenden benutzt wurde,
    # in der Pickliste nicht mehr auf — gewollt, denn im Modus liefert sie
    # ohnehin keine Einträge.
    # Zwei Sichten auf denselben Snapshot: die Vorschau rechnet mit den
    # gefilterten Daten, der Hinweis zählt auf den ungefilterten — sonst wäre
    # die Zahl, die er nennt, per Konstruktion immer 0.
    all_entries_raw = storage.get_all()
    all_entries = workweek.filter_for_report(all_entries_raw, settings)
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

    # Schalter: Gesamtstunden nach Kategorie aufschlüsseln. Default aus —
    # standardmäßig zeigt der Bericht nur das Gesamt, die "Summe je Kategorie"-
    # Tabelle ist opt-in. Greift in PDF-Export und Mail-Versand gleichermaßen.
    breakdown_var = tk.BooleanVar(value=False)
    tk.Checkbutton(
        frame, text="Nach Kategorie aufschlüsseln", variable=breakdown_var,
        font=FONT, bg=BG, fg=TEXT, selectcolor=CELL_BG,
        activebackground=BG, activeforeground=TEXT,
        highlightthickness=0, bd=0, anchor="w",
    ).grid(row=3, column=0, columnspan=6, padx=10, pady=(0, 4), sticky="w")

    # Schalter: Urlaub im Bericht ausweisen. Wird NUR gebaut, wenn überhaupt
    # Urlaub existiert — ein Schalter für ein ungenutztes Feature ist Rauschen.
    # Default aus, wie die Kategorie-Aufschlüsselung.
    vacation_days = vacation_store.day_minutes() if vacation_store else {}
    vacation_var = None
    if any(vacation_days.values()):
        vacation_var = tk.BooleanVar(value=False)
        tk.Checkbutton(
            frame, text="Urlaub ausweisen", variable=vacation_var,
            command=lambda: _changed(),
            font=FONT, bg=BG, fg=TEXT, selectcolor=CELL_BG,
            activebackground=BG, activeforeground=TEXT,
            highlightthickness=0, bd=0, anchor="w",
        ).grid(row=4, column=0, columnspan=6, padx=10, pady=(0, 4), sticky="w")

    handle = _PeriodPickerHandle(
        from_vars, to_vars, category_vars, breakdown_var, vacation_var)

    # Live-Vorschau (Gesamtstunden über den Build-Zeit-Snapshot all_entries).
    total_label = tk.Label(frame, text="", font=FONT, bg=BG, fg=TEXT)
    total_label.grid(row=5, column=0, columnspan=6, padx=10, pady=(0, 8), sticky="w")

    # Gedämpfte Hinweiszeile: nur im Nur-Werktage-Modus und nur, wenn im
    # gewählten Zeitraum tatsächlich Wochenend-Einträge liegen. Ohne sie
    # verlöre jemand mit Alt-Daten stillschweigend Stunden aus dem Bericht.
    weekend_hint = tk.Label(frame, text="", font=FONT_SMALL, bg=BG, fg=TEXT_MUTED)
    weekend_hint.grid(row=6, column=0, columnspan=6, padx=10, pady=(0, 8), sticky="w")
    weekend_hint.grid_remove()  # startet unsichtbar; ein leeres Label würde trotzdem eine Zeile beanspruchen

    def _update_total(*_):
        df, dt = handle.get_range()
        if df is None or dt is None or df > dt:
            total_label.config(text="Gesamtstunden: —")
            weekend_hint.grid_remove()
            return
        hours = total_hours(df, dt, all_entries, handle.get_categories())
        text = f"Gesamtstunden: {hours}h"
        if handle.get_show_vacation():
            in_range = filter_period(df, dt, vacation_days) or {}
            urlaub = round(sum(in_range.values()) / 60, 2)
            if urlaub:
                text += f"  (+ {urlaub}h Urlaub)"
        total_label.config(text=text)
        n = (workweek.count_weekend_entries(all_entries_raw, df, dt)
             if settings.get("workweek_only") else 0)
        if n == 1:
            weekend_hint.config(text="1 Wochenend-Eintrag im Zeitraum wird nicht berücksichtigt.")
            weekend_hint.grid()
        elif n > 1:
            weekend_hint.config(
                text=f"{n} Wochenend-Einträge im Zeitraum werden nicht berücksichtigt.")
            weekend_hint.grid()
        else:
            weekend_hint.grid_remove()

    def _changed(*_):
        # Benutzer-Änderung an Datum oder Kategorie: Vorschau aktualisieren und
        # den Aufrufer benachrichtigen (Export-Button (de)aktivieren). Die
        # Datumszeilen rufen dies über ihren on_change (siehe build_date_row);
        # die Kategorie-Checkboxen über command=_changed.
        _update_total()
        if on_change is not None:
            on_change()

    _update_total()

    return frame, handle
