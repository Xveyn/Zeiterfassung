"""Verwaltung der Urlaubsperioden: Übersicht + Anlege-/Bearbeiten-Dialog.

Die Entscheidungslogik (`plan_vacation_save`) ist Tk-frei und getestet; der
Tkinter-Teil ist nur Wiring — dieselbe Aufteilung wie in `category_dialog.py`
und `entry_dialog.py` (M16).
"""

import datetime
import logging
import tkinter as tk
from tkinter import ttk

from src.holidays_de import get_holidays
from src.theme import (
    ACCENT, BG, CELL_BG, FONT, FONT_BOLD, FONT_SMALL, TEXT, TEXT_MUTED,
    apply_combobox_style,
    center_dialog_on_parent, create_dialog, dark_entry, primary_button,
    secondary_button, set_button_text, themed_askyesno, themed_showerror,
)
from src.time_utils import (
    format_iso_date, format_iso_weekday_date, format_minutes_hm,
)
from src.dialogs.date_row import build_date_row
from src.vacations import apportion_minutes, conflicting_days, expand_days

log = logging.getLogger(__name__)

# Obergrenze je Urlaubstag. 24 h ist die einzige Grenze, die sich nicht
# diskutieren lässt — ein Kalendertag hat nicht mehr. Alles darunter wäre
# erfundene Policy: 10-Stunden-Tage gibt es, und ein Urlaubstag darf so lang
# sein wie der Arbeitstag, den er ersetzt.
MAX_HOURS_PER_DAY = 24
MAX_MINUTES_PER_DAY = MAX_HOURS_PER_DAY * 60


def _hours_to_minutes_exact(hours: float) -> int:
    """Eingegebene Stunden → Minuten. Anders als `time_utils.hours_to_minutes`
    (das gerundete Dezimalstunden aus `calculate_hours` entgegennimmt) ist der
    Wert hier eine direkte Nutzereingabe — gerundet wird auf die nächste ganze
    Minute."""
    return int(round(hours * 60))


def _format_hours(minutes: int) -> str:
    """Minuten → Anzeigewert der Stundenfelder, deutsches Dezimalkomma.

    Eine Schreibweise im ganzen Dialog: Sammelfeld und Tageszeilen sprechen
    dasselbe Format, statt `str(8.0)` = „8.0" neben „8,00" zu stellen.
    """
    return f"{minutes / 60:.2f}".replace(".", ",")


def _dominant_minutes(days: dict) -> int:
    """Der häufigste Nicht-Null-Tageswert einer Periode — die Rückrechnung
    des Sammelfelds beim Bearbeiten.

    Bei Gleichstand gewinnt der größere Wert (deterministisch, und der
    Regelfall ist ohnehin ein einziger Wert über alle Arbeitstage). Nur
    Nullen (reines Wochenende, oder Urlaub ohne Stunden) → 0.
    """
    counts: dict[int, int] = {}
    for minutes in days.values():
        if minutes:
            counts[minutes] = counts.get(minutes, 0) + 1
    if not counts:
        return 0
    return max(counts, key=lambda m: (counts[m], m))


def plan_vacation_save(name, date_from, date_to, mode, value, overrides, state):
    """Baut die Tagesminuten einer Urlaubsperiode aus der Dialog-Eingabe.

    mode: "per_day" (value = Stunden je Arbeitstag) oder "total" (value =
    Gesamtstunden, die auf die Arbeitstage verteilt werden). `value` ist None,
    wenn im Stundenfeld keine Zahl steht.

    Kein Tag darf über MAX_HOURS_PER_DAY liegen. Geprüft wird das an allen
    drei Eingabewegen — Sammelwert, verteilte Gesamtstunden und den Overrides
    der Tagesliste; jeder für sich kann die Grenze reißen, und ohne die
    Prüfung landeten 48 h/Tag unbeanstandet im Store und im Bericht.
    overrides: {ISO: minutes} aus der aufgeklappten Tagesliste; sie gewinnen
    über den berechneten Wert. Tage außerhalb des Zeitraums werden ignoriert.
    state: Bundesland-Code für die Feiertagsliste.

    Liefert {"error": str|None, "days": {ISO: minutes}}. Alle Fehler sind
    bekannte, erwartete Fehler → der Aufrufer zeigt sie themed (Audit N14).
    """
    if not (name or "").strip():
        return {"error": "Bitte einen Namen für den Urlaub eingeben.", "days": {}}
    if date_to < date_from:
        return {"error": "Das Bis-Datum liegt vor dem Von-Datum.", "days": {}}
    if value is None:
        return {"error": "Bitte eine Zahl in das Stundenfeld eingeben.",
                "days": {}}
    if value < 0:
        return {"error": "Die Stundenzahl darf nicht negativ sein.", "days": {}}

    if mode == "total":
        # Erst die Arbeitstage ermitteln (Expansion mit 1 Minute als Marker),
        # dann die Gesamtminuten exakt auf sie verteilen.
        skeleton = expand_days(date_from, date_to, 1, state)
        workdays = [d for d, m in skeleton.items() if m]
        if not workdays:
            return {
                "error": ("Im Zeitraum liegt kein Arbeitstag, auf den die "
                          "Stunden verteilt werden könnten."),
                "days": {},
            }
        parts = apportion_minutes(_hours_to_minutes_exact(value), len(workdays))
        if parts and max(parts) > MAX_MINUTES_PER_DAY:
            return {
                "error": (f"Die Gesamtstunden ergeben mehr als "
                          f"{MAX_HOURS_PER_DAY} Stunden pro Arbeitstag "
                          f"({len(workdays)} Arbeitstage im Zeitraum)."),
                "days": {},
            }
        days = {d: 0 for d in skeleton}
        # strict=True: die Längen sind per Konstruktion gleich, und `ruff` hat
        # B905 scharf (select enthält "B") — ein zip() ohne strict= macht den
        # Linter rot.
        for day, minutes in zip(sorted(workdays), parts, strict=True):
            days[day] = minutes
    else:
        minutes_per_day = _hours_to_minutes_exact(value)
        if minutes_per_day > MAX_MINUTES_PER_DAY:
            return {
                "error": (f"Mehr als {MAX_HOURS_PER_DAY} Stunden pro Tag gibt "
                          f"es nicht."),
                "days": {},
            }
        days = expand_days(date_from, date_to, minutes_per_day, state)

    for day, minutes in overrides.items():
        if day in days:
            days[day] = max(0, int(minutes))

    # Nach den Overrides erneut: die Grenze oben deckt nur den Sammelwert ab,
    # ein einzelner Tag aus der Tagesliste kann sie danach immer noch reißen.
    over = sorted(d for d, m in days.items() if m > MAX_MINUTES_PER_DAY)
    if over:
        return {
            "error": (f"Für diese Tage sind mehr als {MAX_HOURS_PER_DAY} "
                      f"Stunden eingetragen:\n\n"
                      + _format_day_list(over)),
            "days": {},
        }

    return {"error": None, "days": days}


def _format_day_list(days, limit=8):
    """Die kollidierenden Tage als deutsche Datumsliste, ab `limit` gekürzt.

    Ein dreiwöchiger Urlaub über einem vollen Monat Arbeitszeit ergäbe sonst
    eine Fehlermeldung, die aus dem Bildschirm läuft.
    """
    shown = [format_iso_date(d) for d in days[:limit]]
    rest = len(days) - len(shown)
    if rest > 0:
        shown.append(f"… und {rest} weitere")
    return "\n".join(shown)


def _period_line(period):
    """Eine Zeile der Übersicht: Name, Zeitraum, Gesamtstunden."""
    total = sum(period.get("days", {}).values())
    return (f"{period.get('name', '')}   "
            f"{format_iso_date(period.get('from'))} – "
            f"{format_iso_date(period.get('to'))}   "
            f"{format_minutes_hm(total)}")


def open_vacation_dialog(parent, vacation_store, settings, on_change=None,
                         storage=None, reservation_store=None, runner=None):
    """Übersicht aller Urlaubsperioden mit Neu / Bearbeiten / Löschen.

    storage/reservation_store dienen allein der Kollisionsprüfung beim
    Speichern (s. `_open_edit_dialog`); ohne sie wird nicht geprüft.

    runner: der BackgroundTaskRunner der App. Nur für den Kalender-Schalter —
    das Aufräumen beim Abschalten listet und löscht über das Netz und läuft
    deshalb über `runner.purge_vacations` (Audit H5), nicht im UI-Thread.
    """
    dialog = create_dialog(parent, "Urlaub verwalten")

    tk.Label(dialog, text="Urlaubszeiträume", font=FONT_BOLD, bg=BG,
             fg=TEXT).pack(anchor="w", padx=12, pady=(12, 4))

    # Kalender-Schalter. Gebaut NUR bei nutzbarem Kalender (aktiviert und
    # einer gewählt) — ohne den gibt es nichts zu schalten, und ein Schalter
    # für ein unerreichbares Feature ist Rauschen (dieselbe Regel wie beim
    # „Urlaub ausweisen"-Häkchen im period_picker).
    gcal_ready = bool(settings.get("gcal_enabled")
                      and settings.get("gcal_calendar_id"))
    if gcal_ready:
        push_var = tk.BooleanVar(value=bool(settings.get("vacation_gcal_enabled")))
        tk.Checkbutton(
            dialog, text="In den Google-Kalender eintragen",
            variable=push_var, command=lambda: _toggle_push(),
            font=FONT, bg=BG, fg=TEXT, selectcolor=CELL_BG,
            activebackground=BG, activeforeground=TEXT,
            highlightthickness=0, bd=0, anchor="w",
        ).pack(anchor="w", padx=12, pady=(0, 6))

    # selectbackground=ACCENT wie in conflicts_dialog.py und tab_webhooks.py.
    # Stand hier auf CELL_BG, also auf der Hintergrundfarbe der Liste: die
    # Auswahl war damit unsichtbar, und weil „Bearbeiten"/„Löschen" ohne
    # Auswahl mit einer Fehlermeldung abbrechen, sah die Liste aus, als ließe
    # sich gar nichts auswählen.
    listbox = tk.Listbox(
        dialog, font=FONT, bg=CELL_BG, fg=TEXT, selectbackground=ACCENT,
        selectforeground="#ffffff", highlightthickness=0, relief=tk.FLAT,
        width=52, height=10, activestyle="none",
    )
    # Doppelklick öffnet den Bearbeiten-Dialog, wie in der Webhook-Liste
    # (tab_webhooks.py) — dieselbe Bauform aus Liste plus Neu/Bearbeiten/
    # Löschen, also derselbe kurze Weg.
    listbox.bind("<Double-Button-1>", lambda e: _edit())
    listbox.pack(fill=tk.BOTH, expand=True, padx=12)

    hint = tk.Label(
        dialog,
        text="Löschen geht auch per Rechtsklick auf einen Urlaubstag im Kalender.",
        font=FONT_SMALL, bg=BG, fg=TEXT_MUTED)
    hint.pack(anchor="w", padx=12, pady=(4, 0))

    order = []

    def _reload():
        listbox.delete(0, tk.END)
        order.clear()
        periods = vacation_store.get_all()
        for pid in sorted(periods, key=lambda p: periods[p].get("from", "")):
            order.append(pid)
            listbox.insert(tk.END, _period_line(periods[pid]))

    def _selected_id():
        sel = listbox.curselection()
        return order[sel[0]] if sel else None

    def _changed():
        _reload()
        if on_change is not None:
            on_change()

    def _toggle_push():
        """Schaltet den Kalender-Push um.

        Einschalten stößt über `on_change` den normalen Abgleich an, der die
        fehlenden Events anlegt. Ausschalten fragt, ob die bereits
        eingetragenen Termine weg sollen — und zwar NUR, wenn überhaupt
        welche draußen liegen; das steht lokal in den `gcal_event_id` der
        Perioden, kostet also keinen Netzaufruf. „Nein" lässt sie stehen,
        die App fasst sie danach nicht mehr an.
        """
        enabled = bool(push_var.get())
        try:
            settings.set("vacation_gcal_enabled", enabled)
        except OSError as e:
            push_var.set(not enabled)   # Anzeige und Zustand nicht auseinanderlaufen lassen
            themed_showerror(
                dialog, "Einstellung nicht gespeichert",
                f"Die Einstellungen konnten nicht geschrieben werden:\n\n{e}")
            return

        if enabled:
            if on_change is not None:
                on_change()
            return

        pushed = any(p.get("gcal_event_id")
                     for p in vacation_store.get_all_raw().values())
        if not pushed or runner is None:
            return
        if not themed_askyesno(
                dialog, "Urlaubstermine entfernen?",
                "Die bereits im Kalender eingetragenen Urlaubstermine "
                "entfernen?\n\n„Nein“ lässt sie stehen — "
                "die App fasst sie danach nicht mehr an.", lock_ms=600):
            return

        def _on_purged(result):
            if not result.get("ok"):
                themed_showerror(
                    dialog, "Urlaubstermine nicht entfernt",
                    "Die Termine konnten nicht aus dem Kalender entfernt "
                    "werden:\n\n" + result.get("error", "")
                    + "\n\nDer Push ist trotzdem abgeschaltet; "
                    "die Termine stehen noch im Kalender.")

        runner.purge_vacations(_on_purged)

    def _new():
        _open_edit_dialog(dialog, vacation_store, settings, None, _changed,
                          storage, reservation_store)

    def _edit():
        pid = _selected_id()
        if pid is None:
            themed_showerror(dialog, "Kein Urlaub gewählt",
                             "Bitte zuerst einen Urlaubszeitraum auswählen.")
            return
        _open_edit_dialog(dialog, vacation_store, settings, pid, _changed,
                          storage, reservation_store)

    def _delete():
        pid = _selected_id()
        if pid is None:
            themed_showerror(dialog, "Kein Urlaub gewählt",
                             "Bitte zuerst einen Urlaubszeitraum auswählen.")
            return
        period = vacation_store.get(pid)
        if period is None:
            # Die Liste ist nur ein Abbild des Stores; ist die Periode
            # zwischenzeitlich weg (Rechtsklick im Kalender, während der
            # Dialog offen steht), neu einlesen statt auf None zuzugreifen.
            _changed()
            return
        if not themed_askyesno(
                dialog, "Urlaub löschen",
                f"Urlaub „{period['name']}“ komplett löschen?", lock_ms=600):
            return
        vacation_store.delete(pid)
        _changed()

    buttons = tk.Frame(dialog, bg=BG)
    buttons.pack(fill=tk.X, padx=12, pady=12)
    secondary_button(buttons, "Neu", _new).pack(side=tk.LEFT)
    secondary_button(buttons, "Bearbeiten", _edit).pack(side=tk.LEFT, padx=(8, 0))
    secondary_button(buttons, "Löschen", _delete).pack(side=tk.LEFT, padx=(8, 0))
    primary_button(buttons, "Schließen", dialog.destroy).pack(side=tk.RIGHT)

    _reload()
    center_dialog_on_parent(dialog, parent)


def _open_edit_dialog(parent, vacation_store, settings, period_id, on_saved,
                      storage=None, reservation_store=None):
    """Anlegen bzw. Bearbeiten einer Periode: Name, Von/Bis, Stunden-Modus und
    die aufklappbare Tagesliste."""
    existing = vacation_store.get(period_id) if period_id else None
    title = "Urlaub bearbeiten" if existing else "Urlaub eintragen"
    dialog = create_dialog(parent, title)
    # Registriert die ttk-Styles des Dark-Themes — Dark.TCombobox fuer die
    # Von/Bis-Zeilen UND Vertical.TScrollbar fuer die Tagesliste unten.
    apply_combobox_style(dialog)
    state = settings.get("state") or ""

    today = datetime.date.today()
    from_default = (datetime.date.fromisoformat(existing["from"])
                    if existing else today)
    to_default = (datetime.date.fromisoformat(existing["to"])
                  if existing else today)

    name_row = tk.Frame(dialog, bg=BG)
    name_row.pack(anchor="w", padx=12, pady=(12, 4))
    tk.Label(name_row, text="Name:", font=FONT, bg=BG, fg=TEXT, width=6,
             anchor="w").pack(side=tk.LEFT, padx=(0, 5))
    name_var = tk.StringVar(value=existing["name"] if existing else "")
    dark_entry(name_row, name_var, width=30).pack(side=tk.LEFT)

    # year_to_offset=3 statt des Defaults 2: ein Urlaub über den Jahreswechsel
    # muss sich auch im laufenden Jahr noch für das übernächste eintragen
    # lassen (Default deckt 2026 nur bis 2027 ab).
    from_row = build_date_row(dialog, "Von:", from_default,
                              on_change=lambda: _recalc(), label_width=6,
                              year_to_offset=3)
    to_row = build_date_row(dialog, "Bis:", to_default,
                            on_change=lambda: _recalc(), label_width=6,
                            year_to_offset=3)
    from_row.frame.pack(anchor="w", padx=12, pady=4)
    to_row.frame.pack(anchor="w", padx=12, pady=4)

    # Ohne gesetztes Bundesland kennt holidays_de keine Feiertage — dann
    # tragen der 25./26.12. volle Stunden und landen in „Zu vergüten gesamt".
    # Das ist der DEFAULT-Zustand eines frischen Nutzers (settings["state"]
    # ist ""), also gehört ein Hinweis in den Dialog statt einer stillen
    # Falschrechnung.
    if not state:
        tk.Label(
            dialog,
            text=("Kein Bundesland gewählt — Feiertage werden als "
                  "Urlaubstage mit Stunden gezählt."),
            font=FONT_SMALL, bg=BG, fg=TEXT_MUTED, wraplength=380,
            justify="left",
        ).pack(anchor="w", padx=12, pady=(4, 0))

    # Sammelwert beim BEARBEITEN aus der Periode ableiten, nicht aus den
    # Settings: sonst zeigte der Dialog einem Urlaub mit 6 h/Tag ein „8,0",
    # und die erste Änderung schriebe stillschweigend 8 h in alle Tage.
    mode_var = tk.StringVar(value="per_day")
    value_var = tk.StringVar(value=_format_hours(
        _dominant_minutes(existing["days"]) if existing
        else _hours_to_minutes_exact(settings.get("vacation_hours_per_day") or 8.0)
    ))

    mode_frame = tk.Frame(dialog, bg=BG)
    mode_frame.pack(anchor="w", padx=12, pady=(8, 4))
    for mode, label in (("per_day", "Stunden pro Tag"),
                        ("total", "Gesamtstunden")):
        tk.Radiobutton(
            mode_frame, text=label, variable=mode_var, value=mode,
            command=lambda: _recalc(drop_overrides=True), font=FONT, bg=BG,
            fg=TEXT, selectcolor=CELL_BG, activebackground=BG,
            activeforeground=TEXT, highlightthickness=0, bd=0, anchor="w",
        ).pack(anchor="w")
    dark_entry(mode_frame, value_var, width=8).pack(anchor="w", pady=(4, 0))
    # drop_overrides=True: wer den Sammelwert ändert, MEINT „alle Tage neu".
    # Der Zeitraum-Callback oben (build_date_row) ruft dagegen ohne das Flag.
    value_var.trace_add("write", lambda *_: _recalc(drop_overrides=True))

    overrides = dict(existing["days"]) if existing else {}
    day_vars = {}
    expanded = {"on": False}

    toggle = secondary_button(
        dialog, "▸ Einzelne Tage anpassen", lambda: _toggle_days())
    toggle.pack(anchor="w", padx=12, pady=(8, 0))

    # Scrollbarer Container für die Tagesliste — Muster aus import_dialog.py:391.
    # Ohne ihn wüchse der Dialog bei einem dreiwöchigen Urlaub um 21 Zeilen aus
    # dem Bildschirm, und `create_dialog` setzt resizable(False, False).
    day_scroll = tk.Frame(dialog, bg=BG)
    day_canvas = tk.Canvas(day_scroll, bg=BG, highlightthickness=0, height=220)
    # ttk.Scrollbar, NICHT tk.Scrollbar: die Legacy-Scrollbar kennt keine
    # ttk-Styles und bleibt im hellen Systemlook stehen, mitten im dunklen
    # Dialog. Vertical.TScrollbar ist in theme/widgets.py bereits dunkel
    # konfiguriert (dort fuer das Combobox-Popdown).
    day_bar = ttk.Scrollbar(day_scroll, orient="vertical",
                            command=day_canvas.yview,
                            style="Vertical.TScrollbar")
    day_canvas.configure(yscrollcommand=day_bar.set)
    day_canvas.pack(side="left", fill="both", expand=True)
    day_bar.pack(side="right", fill="y")
    day_rows_frame = tk.Frame(day_canvas, bg=BG)
    day_canvas.create_window((0, 0), window=day_rows_frame, anchor="nw")

    total_label = tk.Label(dialog, text="", font=FONT_BOLD, bg=BG, fg=TEXT)
    total_label.pack(anchor="w", padx=12, pady=(8, 4))

    def _range():
        try:
            df = datetime.date(int(from_row.vars[2].get()),
                               int(from_row.vars[1].get()),
                               int(from_row.vars[0].get()))
            dt = datetime.date(int(to_row.vars[2].get()),
                               int(to_row.vars[1].get()),
                               int(to_row.vars[0].get()))
        except ValueError:
            return None, None
        return df, dt

    def _value():
        """Der Sammelwert als Zahl, oder None bei Buchstabensalat im Feld.

        None statt eines Sentinel-Werts wie -1: der ergäbe die Meldung „darf
        nicht negativ sein“ für eine Eingabe, die gar keine Zahl ist.
        """
        try:
            return float((value_var.get() or "0").replace(",", "."))
        except ValueError:
            return None

    def _current_plan():
        df, dt = _range()
        if df is None or dt is None:
            return {"error": "Ungültiges Datum.", "days": {}}
        return plan_vacation_save(
            name_var.get().strip(), df.isoformat(), dt.isoformat(),
            mode_var.get(), _value(), overrides, state)

    def _rebuild_day_rows(days):
        for child in day_rows_frame.winfo_children():
            child.destroy()
        day_vars.clear()
        holidays = {}
        for year in {d[:4] for d in days}:
            holidays.update(get_holidays(state, int(year)))
        for day in sorted(days):
            row = tk.Frame(day_rows_frame, bg=BG)
            row.pack(anchor="w", pady=1)
            tk.Label(row, text=format_iso_weekday_date(day), font=FONT_SMALL,
                     bg=BG, fg=TEXT, width=24, anchor="w").pack(side=tk.LEFT)
            var = tk.StringVar(value=_format_hours(days[day]))
            day_vars[day] = var
            dark_entry(row, var, width=6).pack(side=tk.LEFT)
            holiday_name = holidays.get(datetime.date.fromisoformat(day))
            if holiday_name:
                tk.Label(row, text=holiday_name, font=FONT_SMALL, bg=BG,
                         fg=TEXT_MUTED).pack(side=tk.LEFT, padx=(6, 0))
            var.trace_add("write", lambda *_, d=day: _override(d))
        # Scrollbereich nach dem Aufbau neu vermessen (import_dialog.py:430).
        day_rows_frame.update_idletasks()
        day_canvas.configure(scrollregion=day_canvas.bbox("all"))

    def _override(day):
        try:
            hours = float((day_vars[day].get() or "0").replace(",", "."))
        except ValueError:
            return
        overrides[day] = max(0, _hours_to_minutes_exact(hours))
        _update_total()

    def _update_total():
        plan = _current_plan()
        if plan["error"] and not plan["days"]:
            total_label.config(text="Urlaub gesamt: —")
            return
        total_label.config(
            text=f"Urlaub gesamt: {format_minutes_hm(sum(plan['days'].values()))}")

    def _recalc(drop_overrides=False):
        """Neu berechnen. `drop_overrides` NUR, wenn der Nutzer den
        Sammelwert oder den Modus ändert — dann ist „setze alle Tage neu"
        genau die Absicht.

        Bei einer reinen ZEITRAUM-Änderung bleiben die Überschreibungen
        stehen; es fallen lediglich die weg, die nicht mehr im Bereich
        liegen. Sonst würde das Verlängern eines Urlaubs um einen Tag
        stillschweigend alle bereits gesetzten Tageswerte auf den
        Sammelwert zurücksetzen — bei einem gespeicherten Urlaub also
        Datenverlust bei einer völlig normalen Bearbeitung.
        """
        if drop_overrides:
            overrides.clear()
        plan = _current_plan()
        # Aussortiert wird nur bei GÜLTIGEM Plan. Ein Fehler liefert ein leeres
        # `days` — daran gemessen läge jede Überschreibung außerhalb des
        # Zeitraums und flöge raus. Wer „48" ins Stundenfeld tippt und danach
        # das Bis-Datum korrigiert, verlöre so alle von Hand gesetzten Tage,
        # obwohl er nur einen Tippfehler behoben hat.
        if plan["error"] is None:
            for day in [d for d in overrides if d not in plan["days"]]:
                del overrides[day]
        if expanded["on"]:
            _rebuild_day_rows(plan["days"])
        _update_total()

    def _toggle_days():
        expanded["on"] = not expanded["on"]
        if expanded["on"]:
            _rebuild_day_rows(_current_plan()["days"])
            # before=: pack_forget entfernt das Widget aus der Pack-Liste, ein
            # späteres pack() hängt es HINTEN an — die Tagesliste landete sonst
            # unter „Urlaub gesamt" und unter den Buttons.
            day_scroll.pack(anchor="w", padx=24, fill=tk.X, before=total_label)
            set_button_text(toggle, "▾ Einzelne Tage anpassen")
        else:
            day_scroll.pack_forget()
            set_button_text(toggle, "▸ Einzelne Tage anpassen")

    def _blocking_days(days):
        """Tage der geplanten Periode, an denen schon Ist-Zeit oder eine
        Reservierung liegt (Regel in `vacations.conflicting_days`).

        Reservierungen zählen NUR bei aktivem Kalender-Sync — ohne ihn zeigt
        der Kalender sie gar nicht an und der Rechtsklick löscht sie nicht
        (vgl. `ui.App._reservations_active`). Eine Sperre wegen einer
        unsichtbaren, nicht löschbaren Reservierung wäre eine Sackgasse.
        """
        entry_dates = (
            [d for d, e in storage.get_all().items() if e.get("slots")]
            if storage is not None else [])
        reservation_dates = (
            [d for d, r in reservation_store.get_all().items() if r.get("slots")]
            if reservation_store is not None and settings.get("gcal_enabled")
            else [])
        return conflicting_days(days, entry_dates, reservation_dates)

    def _save():
        plan = _current_plan()
        if plan["error"]:
            themed_showerror(dialog, "Urlaub nicht gespeichert", plan["error"])
            return
        blocked = _blocking_days(plan["days"])
        if blocked:
            themed_showerror(
                dialog, "Urlaub nicht gespeichert",
                "An diesen Tagen ist bereits Arbeitszeit oder eine "
                "Reservierung erfasst:\n\n"
                + _format_day_list(blocked)
                + "\n\nUrlaub und Arbeitszeit schließen sich am selben Tag "
                  "aus. Lösche zuerst die Einträge (Rechtsklick im Kalender) "
                  "oder wähle einen anderen Zeitraum.")
            return
        df, dt = _range()
        try:
            vacation_store.save(period_id, name_var.get().strip(),
                                df.isoformat(), dt.isoformat(), plan["days"])
        except ValueError as e:
            # Überschneidung mit einer anderen Periode — bekannter Fehler.
            themed_showerror(dialog, "Urlaub nicht gespeichert", str(e))
            return
        except OSError as e:
            themed_showerror(
                dialog, "Urlaub nicht gespeichert",
                f"Die Urlaubsdatei konnte nicht geschrieben werden:\n\n{e}")
            return
        # Sammelwert als Vorbelegung für den nächsten Urlaub merken — sonst
        # wäre die Einstellung nur per Hand-Edit der settings.json änderbar
        # und damit tot. Nur im per_day-Modus: im total-Modus ist der
        # eingegebene Wert eine Gesamtsumme, keine Tageslänge.
        #
        # BEWUSST hinter dem try des Stores: der Urlaub ist hier bereits
        # gespeichert. Läge das settings.set im selben try, meldete ein
        # OSError daraus „Die Urlaubsdatei konnte nicht geschrieben werden“,
        # obwohl sie es wurde — und ein zweiter Speichern-Klick liefe beim
        # Neuanlegen in die Überschneidungsprüfung mit der eben erzeugten
        # Periode. Scheitert nur die Vorbelegung, ist das folgenlos.
        value = _value()
        if mode_var.get() == "per_day" and value is not None and value > 0:
            try:
                settings.set("vacation_hours_per_day", value)
            except OSError:
                log.exception(
                    "Vorbelegung vacation_hours_per_day nicht gespeichert")
        dialog.destroy()
        on_saved()

    buttons = tk.Frame(dialog, bg=BG)
    buttons.pack(fill=tk.X, padx=12, pady=12)
    secondary_button(buttons, "Abbrechen", dialog.destroy).pack(side=tk.RIGHT)
    primary_button(buttons, "Speichern", _save).pack(side=tk.RIGHT, padx=(0, 8))

    _update_total()
    center_dialog_on_parent(dialog, parent)
