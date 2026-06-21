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
from src.tooltip import attach_tooltip

# Deutsche Wochentags-Kürzel, indexgleich zu WEEKDAY_KEYS (Mo=mon … So=sun).
_WEEKDAY_LABELS_DE = ("Mo", "Di", "Mi", "Do", "Fr", "Sa", "So")

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
    std_labels = [std_row]
    for text, w, fg in (
        ("Standard", 15, TEXT_MUTED),
        (std_start, 11, TEXT),
        (std_end, 13, TEXT),
        (std_pause, 11, TEXT),
    ):
        lbl = tk.Label(std_row, text=text, font=FONT, bg=BG, fg=fg,
                       width=w, anchor="w")
        lbl.pack(side=tk.LEFT, padx=2)
        std_labels.append(lbl)

    # Bei abweichenden Wochentagen sind die echten Zeiten im "variabel" nicht
    # ablesbar — per Hover die Zeiten je Tag zeigen.
    if is_variable:
        lines = [
            f"{lbl}: {s}–{e}"
            for lbl, s, e in zip(_WEEKDAY_LABELS_DE, day_starts, day_ends)
        ]
        attach_tooltip(std_labels, "Standardzeiten je Wochentag:\n" + "\n".join(lines))

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
