"""Modal zum Verwalten der Kategorie-Pickliste. Die Listen-Logik
(add/remove/rename) ist pure und getestet; der Tkinter-Teil ist nur Wiring.
Speichert via settings.set_synced('categories', ...)."""

import tkinter as tk

from src.theme import (
    ACCENT, BG, CELL_BG, FONT, FONT_BOLD, TEXT,
    apply_app_icon, apply_dark_titlebar, attach_unfocus_on_click,
    center_dialog_on_parent, dark_entry, disable_min_max,
    primary_button, secondary_button,
)


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

    def on_add():
        nonlocal categories
        categories = add_category(categories, name_var.get())
        name_var.set("")
        refresh()

    def on_rename():
        nonlocal categories
        current = _selected()
        if current is None:
            return
        categories = rename_category(categories, current, name_var.get())
        name_var.set("")
        refresh()

    def on_remove():
        nonlocal categories
        current = _selected()
        if current is None:
            return
        categories = remove_category(categories, current)
        refresh()

    edit_row = tk.Frame(outer, bg=BG)
    edit_row.pack(fill="x", pady=(0, 8))
    dark_entry(edit_row, name_var, width=18).pack(side=tk.LEFT, padx=(0, 4))
    secondary_button(edit_row, "Hinzufügen", on_add).pack(side=tk.LEFT, padx=2)
    secondary_button(edit_row, "Umbenennen", on_rename).pack(side=tk.LEFT, padx=2)
    secondary_button(edit_row, "Entfernen", on_remove).pack(side=tk.LEFT, padx=2)

    def on_save():
        settings.set_synced("categories", categories)
        if on_change is not None:
            on_change()
        dialog.destroy()

    save_row = tk.Frame(outer, bg=BG)
    save_row.pack(fill="x")
    primary_button(save_row, "Speichern", on_save).pack(side=tk.LEFT, padx=2)
    secondary_button(save_row, "Schließen", dialog.destroy).pack(side=tk.LEFT, padx=2)

    center_dialog_on_parent(dialog, parent)
