"""Modal zum Verwalten der Kategorien samt ihrer Standardzeiten.

Jede Kategorie ist eine Zeile (wie die Slot-Zeilen im Tages-Dialog): Name +
Start/Ende/Pause. „(Standard)" in einem Zeit-Feld bedeutet „kein eigener Wert,
globale Standardzeit gilt" und landet beim Speichern als fehlendes Feld. Die
Listen-Logik (`collect_categories`) ist pure und getestet; der Tkinter-Teil ist
nur Wiring. Speichert `categories` (Liste) und `category_times` (Dict) via
settings.set_synced.
"""

import tkinter as tk

from src.settings import WEEKDAY_KEYS
from src.theme import (
    BG, FONT, FONT_BOLD, PAUSE_VALUES, TEXT, TEXT_MUTED, TIME_VALUES,
    attach_unfocus_on_click, center_dialog_on_parent, create_dialog,
    dark_combo, dark_entry, primary_button, secondary_button, themed_askyesno,
)
from src.time_utils import DAYS_DE

# Sentinel-Eintrag in den Zeit-Combos: „kein eigener Wert, globaler Standard
# gilt". Wird beim Speichern als fehlendes/leeres Feld abgelegt.
STANDARD = "(Standard)"


def _clean_field(value):
    """STANDARD/leer → None, sonst der getrimmte Wert."""
    value = (value or "").strip()
    return None if value in ("", STANDARD) else value


def collect_categories(rows):
    """Baut (categories, category_times) aus den Roh-Zeilen.

    rows: [{name, mode, start, end, pause, days}]. mode "per_day" → verschachtelter
    Eintrag {mode, pause?, days:{tag:{start?,end?}}}; sonst flacher {start?,end?,pause?}.
    STANDARD/leere Felder entfallen → Per-Feld-Fallback. Leerer Eintrag entfällt ganz.
    Namen getrimmt, ohne Leere, dedupliziert (erstes Vorkommen gewinnt).
    """
    categories = []
    category_times = {}
    for row in rows:
        name = (row.get("name") or "").strip()
        if not name or name in categories:
            continue
        categories.append(name)
        pause = _clean_field(row.get("pause"))

        if row.get("mode") == "per_day":
            raw_days = row.get("days") or {}
            days = {}
            for key in WEEKDAY_KEYS:
                d = raw_days.get(key) or {}
                start = _clean_field(d.get("start"))
                end = _clean_field(d.get("end"))
                day_entry = {}
                if start is not None:
                    day_entry["start"] = start
                if end is not None:
                    day_entry["end"] = end
                if day_entry:
                    days[key] = day_entry
            if not days and pause is None:
                continue  # leerer per_day-Eintrag → komplett global
            entry = {"mode": "per_day", "days": days}
            if pause is not None:
                entry["pause"] = int(pause)
            category_times[name] = entry
        else:
            entry = {}
            start = _clean_field(row.get("start"))
            end = _clean_field(row.get("end"))
            if start is not None:
                entry["start"] = start
            if end is not None:
                entry["end"] = end
            if pause is not None:
                entry["pause"] = int(pause)
            if entry:
                category_times[name] = entry
    return categories, category_times


def categories_losing_per_day(rows):
    """Namen der Zeilen im Modus 'general', die noch >=1 gesetztes (Nicht-
    STANDARD-)Tagesfeld in 'days' tragen — d.h. versteckte per_day-Daten, die ein
    Save als allgemein verwerfen würde. Basis für den Downgrade-Confirm."""
    losing = []
    for row in rows:
        name = (row.get("name") or "").strip()
        if not name or row.get("mode") == "per_day":
            continue
        raw_days = row.get("days") or {}
        for key in WEEKDAY_KEYS:
            d = raw_days.get(key) or {}
            if _clean_field(d.get("start")) is not None or _clean_field(d.get("end")) is not None:
                losing.append(name)
                break
    return losing


def row_defaults_from_entry(entry):
    """category_times[name]-Eintrag → Vorbelegungs-Strings einer Dialog-Zeile.

    {mode, start, end, pause, days} mit Roh-Strings/STANDARD; days enthält ALLE 7
    Tage (ungesetzt → STANDARD). Umkehrung von collect_categories pro Zeile.
    Defensiv: Nicht-Dict/korrupt → allgemein, alles STANDARD.
    """
    if not isinstance(entry, dict):
        return {"mode": "general", "start": STANDARD, "end": STANDARD,
                "pause": STANDARD, "days": {}}

    pause = entry.get("pause")
    pause_str = str(pause) if pause not in (None, "") else STANDARD

    if entry.get("mode") == "per_day":
        raw_days = entry.get("days") if isinstance(entry.get("days"), dict) else {}
        days = {}
        for key in WEEKDAY_KEYS:
            d = raw_days.get(key) if isinstance(raw_days.get(key), dict) else {}
            days[key] = {"start": d.get("start") or STANDARD,
                         "end": d.get("end") or STANDARD}
        return {"mode": "per_day", "start": STANDARD, "end": STANDARD,
                "pause": pause_str, "days": days}

    return {"mode": "general",
            "start": entry.get("start") or STANDARD,
            "end": entry.get("end") or STANDARD,
            "pause": pause_str, "days": {}}


def _grid_all_standard(day_vars):
    """True wenn alle 7 Tages-Start/Ende-Vars noch den STANDARD-Sentinel halten."""
    return all(
        v["start"].get() == STANDARD and v["end"].get() == STANDARD
        for v in day_vars.values()
    )


def open_category_dialog(parent, settings, on_change=None):
    categories = list(settings.get("categories") or [])
    category_times = dict(settings.get("category_times") or {})

    dialog = create_dialog(parent, "Kategorien verwalten")
    attach_unfocus_on_click(dialog)

    outer = tk.Frame(dialog, bg=BG)
    outer.pack(padx=12, pady=12)

    tk.Label(outer, text="Kategorien", font=FONT_BOLD, bg=BG, fg=TEXT).pack(anchor="w")
    tk.Label(
        outer, text='Pro Kategorie: Name + Standardzeiten. '
                    '„(Standard)" = globale Standardzeit verwenden.',
        font=FONT, bg=BG, fg=TEXT_MUTED,
    ).pack(anchor="w", pady=(0, 6))

    # Spaltenüberschriften
    head = tk.Frame(outer, bg=BG)
    head.pack(fill="x")
    tk.Label(head, text="Name", font=FONT, bg=BG, fg=TEXT_MUTED,
             width=15, anchor="w").pack(side=tk.LEFT, padx=2)
    tk.Label(head, text="Modus", font=FONT, bg=BG, fg=TEXT_MUTED,
             width=10, anchor="w").pack(side=tk.LEFT, padx=2)
    tk.Label(head, text="Start", font=FONT, bg=BG, fg=TEXT_MUTED,
             width=11, anchor="w").pack(side=tk.LEFT, padx=2)
    tk.Label(head, text="Ende", font=FONT, bg=BG, fg=TEXT_MUTED,
             width=13, anchor="w").pack(side=tk.LEFT, padx=2)
    tk.Label(head, text="Pause", font=FONT, bg=BG, fg=TEXT_MUTED,
             width=11, anchor="w").pack(side=tk.LEFT, padx=2)

    rows_frame = tk.Frame(outer, bg=BG)
    rows_frame.pack(fill="x")
    rows = []  # Liste von {frame, name, start, end, pause}

    # Read-only Referenzzeile: die globalen Standardzeiten, damit der Nutzer
    # direkt sieht, worauf „(Standard)" hinausläuft. Als schlichte Labels (kein
    # Eingabefeld) — eindeutig nicht editierbar. Start/Ende sind pro Wochentag
    # konfigurierbar: sind alle Tage gleich, zeigen wir den Wert, sonst
    # „variabel"; Pause ist global. Spaltenbreiten = die der Überschriften.
    day_starts = [settings.get(f"default_start_{d}") for d in WEEKDAY_KEYS]
    day_ends = [settings.get(f"default_end_{d}") for d in WEEKDAY_KEYS]
    is_variable = len(set(day_starts)) > 1 or len(set(day_ends)) > 1
    std_start = "variabel" if len(set(day_starts)) > 1 else day_starts[0]
    std_end = "variabel" if len(set(day_ends)) > 1 else day_ends[0]
    std_pause = str(settings.get("default_pause"))

    std_row = tk.Frame(rows_frame, bg=BG)
    std_row.pack(fill="x", pady=2)
    for text, w, fg in (
        ("Standard", 15, TEXT_MUTED),
        ("", 10, TEXT_MUTED),  # Spacer für Modus-Spalte
        (std_start, 11, TEXT),
        (std_end, 13, TEXT),
        (std_pause, 11, TEXT),
    ):
        tk.Label(std_row, text=text, font=FONT, bg=BG, fg=fg,
                 width=w, anchor="w").pack(side=tk.LEFT, padx=2)

    # Bei abweichenden Wochentagen zeigen Start/Ende „variabel". Ein Toggle
    # klappt — wie in den Einstellungen — die echten Zeiten je Tag inline aus
    # (read-only); das Fenster passt seine Höhe automatisch an.
    if is_variable:
        daygrid = tk.Frame(rows_frame, bg=BG)
        tk.Label(daygrid, text="Start", font=FONT, bg=BG, fg=TEXT_MUTED).grid(
            row=0, column=1, padx=6)
        tk.Label(daygrid, text="Ende", font=FONT, bg=BG, fg=TEXT_MUTED).grid(
            row=0, column=2, padx=6)
        for i, (key, lbl) in enumerate(zip(WEEKDAY_KEYS, DAYS_DE, strict=False), start=1):
            tk.Label(daygrid, text=lbl, font=FONT, bg=BG, fg=TEXT,
                     width=4, anchor="w").grid(row=i, column=0, padx=(2, 8),
                                               pady=1, sticky="w")
            tk.Label(daygrid, text=settings.get(f"default_start_{key}"),
                     font=FONT, bg=BG, fg=TEXT).grid(row=i, column=1, padx=6, pady=1)
            tk.Label(daygrid, text=settings.get(f"default_end_{key}"),
                     font=FONT, bg=BG, fg=TEXT).grid(row=i, column=2, padx=6, pady=1)

        toggle_holder = {}

        def _toggle_daygrid():
            if daygrid.winfo_ismapped():
                daygrid.pack_forget()
                toggle_holder["btn"]._label.config(text="Pro Tag ▶")
            else:
                daygrid.pack(after=std_row, anchor="center", pady=(0, 4))
                toggle_holder["btn"]._label.config(text="Pro Tag ▼")

        toggle_holder["btn"] = secondary_button(
            std_row, "Pro Tag ▶", _toggle_daygrid, padx=8, pady=0)
        toggle_holder["btn"].pack(side=tk.LEFT, padx=2)

    def add_row(name="", defaults=None):
        if defaults is None:
            defaults = row_defaults_from_entry({})

        # Container hält row + day_frame als Geschwister (pack-Reihenfolge).
        container = tk.Frame(rows_frame, bg=BG)
        container.pack(fill="x", pady=2)
        row = tk.Frame(container, bg=BG)
        row.pack(fill="x")

        # StringVars
        nv = tk.StringVar(value=name)
        mode_var = tk.StringVar()
        start_var = tk.StringVar(value=defaults["start"])
        end_var = tk.StringVar(value=defaults["end"])
        pause_var = tk.StringVar(value=defaults["pause"])

        # Name-Entry
        dark_entry(row, nv, width=15).pack(side=tk.LEFT, padx=2)
        # Modus-Combo
        mode_combo = dark_combo(row, mode_var, ["Allgemein", "Tageweise"], width=10)
        mode_combo.pack(side=tk.LEFT, padx=2)

        # general_frame mit Start–Ende — Sichtbarkeit via _apply_mode
        general_frame = tk.Frame(row, bg=BG)
        dark_combo(general_frame, start_var,
                   [STANDARD, *TIME_VALUES], width=11).pack(side=tk.LEFT, padx=2)
        tk.Label(general_frame, text="–",
                 font=FONT, bg=BG, fg=TEXT_MUTED).pack(side=tk.LEFT)
        dark_combo(general_frame, end_var,
                   [STANDARD, *TIME_VALUES], width=11).pack(side=tk.LEFT, padx=2)

        # Pause-Combo (immer sichtbar, bleibt in row)
        pause_combo = dark_combo(row, pause_var, [STANDARD, *PAUSE_VALUES], width=11)
        pause_combo.pack(side=tk.LEFT, padx=2)

        # 7-Tage-Grid — Sichtbarkeit via _apply_mode
        day_vars = {}
        day_frame = tk.Frame(container, bg=BG)
        for i, (key, lbl) in enumerate(zip(WEEKDAY_KEYS, DAYS_DE, strict=False)):
            d = (defaults["days"] or {}).get(key) or {}
            sv = tk.StringVar(value=d.get("start") or STANDARD)
            ev = tk.StringVar(value=d.get("end") or STANDARD)
            day_vars[key] = {"start": sv, "end": ev}
            tk.Label(day_frame, text=lbl, font=FONT, bg=BG, fg=TEXT,
                     width=4, anchor="w").grid(row=i, column=0,
                                               padx=(16, 4), pady=1, sticky="w")
            dark_combo(day_frame, sv, [STANDARD, *TIME_VALUES], width=11).grid(
                row=i, column=1, padx=2, pady=1)
            tk.Label(day_frame, text="–", font=FONT, bg=BG, fg=TEXT_MUTED).grid(
                row=i, column=2, pady=1)
            dark_combo(day_frame, ev, [STANDARD, *TIME_VALUES], width=11).grid(
                row=i, column=3, padx=2, pady=1)

        # Toggle-Button für das Tages-Grid (analog zur Referenzzeile _toggle_daygrid).
        # Anfangs nicht gepackt; _apply_mode steuert Sichtbarkeit.
        row_toggle_holder = {}

        def _toggle_day_row():
            if day_frame.winfo_ismapped():
                day_frame.pack_forget()
                row_toggle_holder["btn"]._label.config(text="Pro Tag ▶")
            else:
                day_frame.pack(after=row, anchor="w", pady=(0, 4))
                row_toggle_holder["btn"]._label.config(text="Pro Tag ▼")

        row_toggle_holder["btn"] = secondary_button(
            row, "Pro Tag ▶", _toggle_day_row, padx=8, pady=0)

        def _apply_mode(*_a, expand=True):
            if mode_var.get() == "Tageweise":
                # Allgemeine Werte ins Grid spiegeln, falls Grid noch leer (STANDARD).
                if _grid_all_standard(day_vars):
                    for tag in WEEKDAY_KEYS:
                        day_vars[tag]["start"].set(start_var.get())
                        day_vars[tag]["end"].set(end_var.get())
                general_frame.pack_forget()
                row_toggle_holder["btn"].pack(side=tk.LEFT, padx=2, before=pause_combo)
                if expand:
                    day_frame.pack(after=row, anchor="w", pady=(0, 4))
                    row_toggle_holder["btn"]._label.config(text="Pro Tag ▼")
                else:
                    day_frame.pack_forget()
                    row_toggle_holder["btn"]._label.config(text="Pro Tag ▶")
            else:
                # Montags-Werte in general zurückschreiben, falls general noch STANDARD.
                if start_var.get() == STANDARD:
                    mon = day_vars["mon"]
                    if mon["start"].get() != STANDARD:
                        start_var.set(mon["start"].get())
                    if mon["end"].get() != STANDARD:
                        end_var.set(mon["end"].get())
                day_frame.pack_forget()
                row_toggle_holder["btn"].pack_forget()
                general_frame.pack(in_=row, side=tk.LEFT,
                                   padx=2, before=pause_combo)

        record = {
            "frame": row, "name": nv, "mode": mode_var,
            "start": start_var, "end": end_var, "pause": pause_var,
            "days": day_vars,
        }

        def remove():
            container.destroy()
            rows.remove(record)

        secondary_button(row, "×", remove, padx=8, pady=0).pack(side=tk.LEFT, padx=2)
        rows.append(record)

        # Initialen Modus setzen + Sichtbarkeit herstellen.
        # <<ComboboxSelected>> feuert bei programmatischem .set() NICHT.
        # expand=False: Tageweise-Grid beim Laden eingeklappt (Fenster kompakt).
        mode_var.set("Tageweise" if defaults["mode"] == "per_day" else "Allgemein")
        _apply_mode(expand=False)

        mode_combo.bind("<<ComboboxSelected>>", _apply_mode)

    if categories:
        for c in categories:
            add_row(c, row_defaults_from_entry(category_times.get(c) or {}))
    else:
        add_row("", row_defaults_from_entry({}))

    btns = tk.Frame(outer, bg=BG)
    btns.pack(fill="x", pady=(2, 8))
    secondary_button(
        btns, "+ Kategorie",
        lambda: add_row("", row_defaults_from_entry({})),
    ).pack(side=tk.LEFT, padx=2)

    def on_save():
        raw = []
        for r in rows:
            raw.append({
                "name": r["name"].get(),
                "mode": "per_day" if r["mode"].get() == "Tageweise" else "general",
                "start": r["start"].get(),
                "end": r["end"].get(),
                "pause": r["pause"].get(),
                "days": {
                    tag: {"start": v["start"].get(), "end": v["end"].get()}
                    for tag, v in r["days"].items()
                },
            })

        losing = categories_losing_per_day(raw)
        if losing:
            names = ", ".join(losing)
            if not themed_askyesno(
                dialog, "Tageszeiten verwerfen?",
                f"Für {names} gehen die tageweise gesetzten Zeiten verloren, "
                "wenn als „Allgemein“ gespeichert wird.\n\nTrotzdem speichern?",
            ):
                return

        cats, times = collect_categories(raw)
        settings.set_synced("categories", cats)
        settings.set_synced("category_times", times)
        if on_change is not None:
            on_change()
        dialog.destroy()

    save_row = tk.Frame(outer, bg=BG)
    save_row.pack(fill="x")
    primary_button(save_row, "Speichern", on_save).pack(side=tk.LEFT, padx=2)
    secondary_button(save_row, "Schließen", dialog.destroy).pack(side=tk.LEFT, padx=2)

    center_dialog_on_parent(dialog, parent)
