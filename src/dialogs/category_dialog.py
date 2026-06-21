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
    apply_app_icon, apply_dark_titlebar, attach_unfocus_on_click,
    center_dialog_on_parent, dark_combo, dark_entry, disable_min_max,
    primary_button, secondary_button,
)

# Sentinel-Eintrag in den Zeit-Combos: „kein eigener Wert, globaler Standard
# gilt". Wird beim Speichern als fehlendes/leeres Feld abgelegt.
STANDARD = "(Standard)"


def _clean_field(value):
    """STANDARD/leer → None, sonst der getrimmte Wert."""
    value = (value or "").strip()
    return None if value in ("", STANDARD) else value


def collect_categories(rows):
    """Baut (categories, category_times) aus den Roh-Zeilen.

    `rows` ist eine Liste von Dicts mit den Roh-Strings der Combos/Entries:
    `{"name", "start", "end", "pause"}`.

    - `categories`: Namen in Eingabereihenfolge, getrimmt, ohne Leere,
      dedupliziert (erstes Vorkommen gewinnt).
    - `category_times`: `{name: {start?, end?, pause?}}` nur für Namen mit
      mindestens einem gesetzten (Nicht-Standard-)Feld. Leere/STANDARD-Felder
      entfallen → Per-Feld-Fallback auf die globalen Standardzeiten.
    """
    categories = []
    category_times = {}
    for row in rows:
        name = (row.get("name") or "").strip()
        if not name or name in categories:
            continue
        categories.append(name)
        entry = {}
        start = _clean_field(row.get("start"))
        end = _clean_field(row.get("end"))
        pause = _clean_field(row.get("pause"))
        if start is not None:
            entry["start"] = start
        if end is not None:
            entry["end"] = end
        if pause is not None:
            entry["pause"] = int(pause)
        if entry:
            category_times[name] = entry
    return categories, category_times


def open_category_dialog(parent, settings, on_change=None):
    categories = list(settings.get("categories") or [])
    category_times = dict(settings.get("category_times") or {})

    dialog = tk.Toplevel(parent)
    dialog.title("Kategorien verwalten")
    dialog.resizable(False, False)
    dialog.grab_set()
    dialog.focus_set()
    dialog.configure(bg=BG)
    apply_dark_titlebar(dialog)
    disable_min_max(dialog)
    apply_app_icon(dialog)
    attach_unfocus_on_click(dialog)
    dialog.bind("<Escape>", lambda _e: dialog.destroy())

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
    tk.Label(head, text="Start", font=FONT, bg=BG, fg=TEXT_MUTED,
             width=11, anchor="w").pack(side=tk.LEFT, padx=2)
    tk.Label(head, text="Ende", font=FONT, bg=BG, fg=TEXT_MUTED,
             width=13, anchor="w").pack(side=tk.LEFT, padx=2)
    tk.Label(head, text="Pause", font=FONT, bg=BG, fg=TEXT_MUTED,
             width=11, anchor="w").pack(side=tk.LEFT, padx=2)

    rows_frame = tk.Frame(outer, bg=BG)
    rows_frame.pack(fill="x")
    rows = []  # Liste von {frame, name, start, end, pause}
    _keep = []  # haltet StringVars der read-only Zeile am Leben

    # Read-only Referenzzeile: die globalen Standardzeiten, damit der Nutzer
    # direkt sieht, worauf „(Standard)" hinausläuft. Start/Ende sind pro
    # Wochentag konfigurierbar — sind alle Tage gleich, zeigen wir den Wert,
    # sonst „variabel". Pause ist global. Nicht editierbar, nicht in `rows`.
    starts = {settings.get(f"default_start_{d}") for d in WEEKDAY_KEYS}
    ends = {settings.get(f"default_end_{d}") for d in WEEKDAY_KEYS}
    std_start = next(iter(starts)) if len(starts) == 1 else "variabel"
    std_end = next(iter(ends)) if len(ends) == 1 else "variabel"
    std_pause = str(settings.get("default_pause"))

    std_row = tk.Frame(rows_frame, bg=BG)
    std_row.pack(fill="x", pady=2)
    std_name = tk.StringVar(value="Standard")
    _keep.append(std_name)
    std_name_e = dark_entry(std_row, std_name, width=15)
    std_name_e.configure(state="disabled")
    std_name_e.pack(side=tk.LEFT, padx=2)

    def _ro_combo(val, width):
        c = dark_combo(std_row, None, [val], width=width)
        c.set(val)
        c.configure(state="disabled")
        return c

    _ro_combo(std_start, 11).pack(side=tk.LEFT, padx=2)
    tk.Label(std_row, text="–", font=FONT, bg=BG, fg=TEXT_MUTED).pack(side=tk.LEFT)
    _ro_combo(std_end, 11).pack(side=tk.LEFT, padx=2)
    _ro_combo(std_pause, 11).pack(side=tk.LEFT, padx=2)

    def add_row(name="", start=STANDARD, end=STANDARD, pause=STANDARD):
        row = tk.Frame(rows_frame, bg=BG)
        row.pack(fill="x", pady=2)
        nv = tk.StringVar(value=name)
        sv = tk.StringVar(value=start)
        ev = tk.StringVar(value=end)
        pv = tk.StringVar(value=pause)
        dark_entry(row, nv, width=15).pack(side=tk.LEFT, padx=2)
        dark_combo(row, sv, [STANDARD, *TIME_VALUES], width=11).pack(side=tk.LEFT, padx=2)
        tk.Label(row, text="–", font=FONT, bg=BG, fg=TEXT_MUTED).pack(side=tk.LEFT)
        dark_combo(row, ev, [STANDARD, *TIME_VALUES], width=11).pack(side=tk.LEFT, padx=2)
        dark_combo(row, pv, [STANDARD, *PAUSE_VALUES], width=11).pack(side=tk.LEFT, padx=2)
        record = {"frame": row, "name": nv, "start": sv, "end": ev, "pause": pv}

        def remove():
            row.destroy()
            rows.remove(record)

        secondary_button(row, "×", remove, padx=8, pady=0).pack(side=tk.LEFT, padx=2)
        rows.append(record)

    if categories:
        for c in categories:
            t = category_times.get(c) or {}
            p = t.get("pause")
            add_row(
                c,
                t.get("start") or STANDARD,
                t.get("end") or STANDARD,
                str(p) if p not in (None, "") else STANDARD,
            )
    else:
        add_row()  # eine leere Startzeile

    btns = tk.Frame(outer, bg=BG)
    btns.pack(fill="x", pady=(2, 8))
    secondary_button(btns, "+ Kategorie", lambda: add_row()).pack(side=tk.LEFT, padx=2)

    def on_save():
        raw = [{
            "name": r["name"].get(),
            "start": r["start"].get(),
            "end": r["end"].get(),
            "pause": r["pause"].get(),
        } for r in rows]
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
