"""Modal zum Verwalten der Kategorie-Pickliste. Die Listen-Logik
(add/remove/rename) ist pure und getestet; der Tkinter-Teil ist nur Wiring.
Speichert via settings.set_synced('categories', ...)."""

import tkinter as tk

from src.category_defaults import remove_category_times, rename_category_times
from src.theme import (
    ACCENT, BG, CELL_BG, FONT, FONT_BOLD, PAUSE_VALUES, TEXT, TEXT_MUTED,
    TIME_VALUES, apply_app_icon, apply_dark_titlebar, attach_unfocus_on_click,
    center_dialog_on_parent, dark_combo, dark_entry, disable_min_max,
    primary_button, secondary_button,
)

# Sentinel-Eintrag in den Zeit-Combos: bedeutet "kein eigener Wert, globaler
# Standard gilt". Wird beim Speichern als fehlendes/leeres Feld abgelegt.
STANDARD = "(Standard)"


def add_category(categories, name):
    """Fügt `name` (getrimmt) hinzu, falls nicht leer und nicht vorhanden.
    Liefert IMMER eine neue Liste (Original bleibt unangetastet)."""
    name = name.strip()
    if not name or name in categories:
        return list(categories)
    return list(categories) + [name]


def remove_category(categories, name):
    """Entfernt `name`. Liefert eine neue Liste."""
    return [c for c in categories if c != name]


def rename_category(categories, old, new):
    """Benennt `old` in `new` (getrimmt) um. No-op, wenn `new` leer ist, `old`
    nicht existiert, oder `new` bereits eine ANDERE Kategorie ist."""
    new = new.strip()
    if not new or old not in categories:
        return list(categories)
    if new in categories and new != old:
        return list(categories)
    return [new if c == old else c for c in categories]


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

    listbox = tk.Listbox(
        outer, height=8, width=30, font=FONT, bg=CELL_BG, fg=TEXT,
        selectbackground=ACCENT, selectforeground="#ffffff",
        highlightthickness=0, bd=0, activestyle="none",
    )
    listbox.pack(fill="x", pady=(4, 8))

    def refresh():
        listbox.delete(0, tk.END)
        for c in categories:
            listbox.insert(tk.END, c)

    refresh()

    def _selected():
        sel = listbox.curselection()
        return categories[sel[0]] if sel else None

    name_var = tk.StringVar()

    # --- Zeit-Felder für die aktuell selektierte Kategorie ---
    start_var = tk.StringVar(value=STANDARD)
    end_var = tk.StringVar(value=STANDARD)
    pause_var = tk.StringVar(value=STANDARD)
    prev_sel = [None]  # zuletzt selektierte Kategorie (Tk liefert nur die neue)

    def _load_fields(cat):
        entry = category_times.get(cat) or {}
        start_var.set(entry.get("start") or STANDARD)
        end_var.set(entry.get("end") or STANDARD)
        p = entry.get("pause")
        pause_var.set(str(p) if p not in (None, "") else STANDARD)

    def _store_fields(cat):
        """Schreibt die angezeigten Felder in den Eintrag von `cat` zurück.
        STANDARD/leer → Feld entfällt; bleibt nichts übrig, verschwindet der
        Kategorie-Eintrag ganz (komplett globaler Fallback)."""
        if cat is None:
            return
        entry = {}
        if start_var.get() not in ("", STANDARD):
            entry["start"] = start_var.get()
        if end_var.get() not in ("", STANDARD):
            entry["end"] = end_var.get()
        if pause_var.get() not in ("", STANDARD):
            entry["pause"] = int(pause_var.get())
        if entry:
            category_times[cat] = entry
        else:
            category_times.pop(cat, None)

    def on_select(_e=None):
        _store_fields(prev_sel[0])
        cat = _selected()
        if cat is None:
            return
        _load_fields(cat)
        prev_sel[0] = cat

    listbox.bind("<<ListboxSelect>>", on_select)

    def on_add():
        nonlocal categories
        categories = add_category(categories, name_var.get())
        name_var.set("")
        refresh()

    def on_rename():
        nonlocal categories, category_times
        current = _selected()
        if current is None:
            return
        _store_fields(current)
        new = name_var.get()
        categories = rename_category(categories, current, new)
        category_times = rename_category_times(category_times, current, new)
        name_var.set("")
        prev_sel[0] = None
        refresh()

    def on_remove():
        nonlocal categories, category_times
        current = _selected()
        if current is None:
            return
        categories = remove_category(categories, current)
        category_times = remove_category_times(category_times, current)
        prev_sel[0] = None
        refresh()

    edit_row = tk.Frame(outer, bg=BG)
    edit_row.pack(fill="x", pady=(0, 8))
    dark_entry(edit_row, name_var, width=18).pack(side=tk.LEFT, padx=(0, 4))
    secondary_button(edit_row, "Hinzufügen", on_add).pack(side=tk.LEFT, padx=2)
    secondary_button(edit_row, "Umbenennen", on_rename).pack(side=tk.LEFT, padx=2)
    secondary_button(edit_row, "Entfernen", on_remove).pack(side=tk.LEFT, padx=2)

    tk.Label(
        outer, text="Standardzeiten der gewählten Kategorie",
        font=FONT_BOLD, bg=BG, fg=TEXT,
    ).pack(anchor="w", pady=(4, 0))
    tk.Label(
        outer, text='„(Standard)" = globale Standardzeit verwenden',
        font=FONT, bg=BG, fg=TEXT_MUTED,
    ).pack(anchor="w")
    time_row = tk.Frame(outer, bg=BG)
    time_row.pack(fill="x", pady=(4, 8))
    tk.Label(time_row, text="Start", font=FONT, bg=BG, fg=TEXT_MUTED).pack(side=tk.LEFT)
    dark_combo(time_row, start_var, [STANDARD, *TIME_VALUES],
               width=8).pack(side=tk.LEFT, padx=(2, 8))
    tk.Label(time_row, text="Ende", font=FONT, bg=BG, fg=TEXT_MUTED).pack(side=tk.LEFT)
    dark_combo(time_row, end_var, [STANDARD, *TIME_VALUES],
               width=8).pack(side=tk.LEFT, padx=(2, 8))
    tk.Label(time_row, text="Pause", font=FONT, bg=BG, fg=TEXT_MUTED).pack(side=tk.LEFT)
    dark_combo(time_row, pause_var, [STANDARD, *PAUSE_VALUES],
               width=10).pack(side=tk.LEFT, padx=2)

    def on_save():
        _store_fields(prev_sel[0])
        settings.set_synced("categories", categories)
        settings.set_synced("category_times", category_times)
        if on_change is not None:
            on_change()
        dialog.destroy()

    save_row = tk.Frame(outer, bg=BG)
    save_row.pack(fill="x")
    primary_button(save_row, "Speichern", on_save).pack(side=tk.LEFT, padx=2)
    secondary_button(save_row, "Schließen", dialog.destroy).pack(side=tk.LEFT, padx=2)

    center_dialog_on_parent(dialog, parent)
