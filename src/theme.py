import tkinter as tk
from tkinter import ttk

# Dark Modern color palette
BG = "#1a1a2e"
CELL_BG = "#16213e"
WEEKEND_BG = "#0f3460"
ACCENT = "#e94560"
ACCENT_HOVER = "#c73550"
STATUS_OK = "#4ade80"
TEXT = "#e0e0e0"
TEXT_MUTED = "#888888"
ENTRY_BG = "#1a3a5c"
WEEKEND_ENTRY_BG = "#1a3050"
WEEKEND_FG = "#6c6c80"

FONT = ("Segoe UI", 10)
FONT_SMALL = ("Segoe UI", 8)
FONT_TINY = ("Segoe UI", 7)
FONT_BOLD = ("Segoe UI", 10, "bold")
FONT_HEADER = ("Segoe UI", 16, "bold")
FONT_HEADER_SMALL = ("Segoe UI", 12, "bold")
FONT_FOOTER = ("Segoe UI", 12, "bold")

# Hover colors (slightly lighter variants)
CELL_BG_HOVER = "#1e2d52"
WEEKEND_BG_HOVER = "#153a6e"
ENTRY_BG_HOVER = "#224a70"
WEEKEND_ENTRY_BG_HOVER = "#223e60"

# Holiday cell colors (green analog to red ACCENT for entries)
HOLIDAY_BG = "#0f3a2a"
HOLIDAY_BG_HOVER = "#15523a"
HOLIDAY_ACCENT = "#4ade80"  # gleicher Grünton wie STATUS_OK

# Time dropdown values (5-min steps, 00:00 - 23:55)
TIME_VALUES = [f"{h:02d}:{m:02d}" for h in range(24) for m in range(0, 60, 5)]
PAUSE_VALUES = [str(m) for m in range(0, 125, 5)]


def apply_combobox_style(dialog):
    style = ttk.Style(dialog)
    style.theme_use("clam")
    style.configure(
        "Dark.TCombobox",
        fieldbackground=CELL_BG, background=CELL_BG,
        foreground=TEXT, arrowcolor=ACCENT,
        bordercolor=TEXT_MUTED, lightcolor=CELL_BG, darkcolor=CELL_BG,
        selectbackground=ENTRY_BG, selectforeground=TEXT,
    )
    style.map("Dark.TCombobox",
        fieldbackground=[("readonly", CELL_BG)],
        selectbackground=[("readonly", CELL_BG)],
        selectforeground=[("readonly", TEXT)],
        bordercolor=[("focus", ACCENT)],
    )
    dialog.option_add("*TCombobox*Listbox.background", CELL_BG)
    dialog.option_add("*TCombobox*Listbox.foreground", TEXT)
    dialog.option_add("*TCombobox*Listbox.selectBackground", ACCENT)
    dialog.option_add("*TCombobox*Listbox.selectForeground", "#ffffff")
    dialog.option_add("*TCombobox*Listbox.font", FONT)


def dark_entry(parent, textvariable, width=25, **kw):
    return tk.Entry(
        parent, textvariable=textvariable, width=width, font=FONT,
        bg=CELL_BG, fg=TEXT, insertbackground=ACCENT,
        relief=tk.FLAT, highlightbackground=TEXT_MUTED,
        highlightcolor=ACCENT, highlightthickness=1, **kw,
    )


def dark_combo(parent, textvariable, values, width=8, **kw):
    return ttk.Combobox(
        parent, textvariable=textvariable, values=values,
        width=width, font=FONT, style="Dark.TCombobox", state="readonly", **kw,
    )


def dark_text(parent, width, height, **kw):
    return tk.Text(
        parent, width=width, height=height, font=FONT,
        bg=CELL_BG, fg=TEXT, insertbackground=ACCENT,
        relief=tk.FLAT, highlightbackground=TEXT_MUTED,
        highlightcolor=ACCENT, highlightthickness=1, wrap=tk.WORD, **kw,
    )


def primary_button(parent, text, command, **kw):
    kw.setdefault("font", FONT_BOLD)
    kw.setdefault("padx", 16)
    kw.setdefault("pady", 4)
    return tk.Button(
        parent, text=text, command=command,
        bg=ACCENT, fg="#ffffff",
        activebackground=ACCENT_HOVER, activeforeground="#ffffff",
        relief=tk.FLAT, cursor="hand2", **kw,
    )


def secondary_button(parent, text, command, **kw):
    kw.setdefault("font", FONT)
    kw.setdefault("padx", 16)
    kw.setdefault("pady", 4)
    return tk.Button(
        parent, text=text, command=command,
        bg=CELL_BG, fg=TEXT,
        activebackground=ENTRY_BG, activeforeground=TEXT,
        relief=tk.FLAT, cursor="hand2", **kw,
    )


def toggle_button(parent, text, command, active=False, **kw):
    """Two-state segmented button used for the Monat/Woche switcher.

    Re-style with set_toggle_active(btn, bool) when state changes.
    """
    btn = tk.Button(
        parent, text=text, command=command,
        font=FONT_SMALL, width=6, relief=tk.FLAT, cursor="hand2", **kw,
    )
    set_toggle_active(btn, active)
    return btn


def set_toggle_active(btn, active):
    if active:
        btn.config(
            bg=ACCENT, fg="#ffffff",
            activebackground=ACCENT, activeforeground="#ffffff",
        )
    else:
        btn.config(
            bg=CELL_BG, fg=TEXT_MUTED,
            activebackground=ENTRY_BG, activeforeground=TEXT,
        )


def center_dialog_on_parent(dialog, parent):
    """Position a Toplevel dialog over its parent's screen rect.

    Tk-Default platziert Toplevels auf dem Primärmonitor — bei Multi-Monitor-
    Setups öffnet sich der Dialog daher nicht beim Parent. transient() bindet
    den Dialog zusätzlich an den Parent (Icon, Z-Order, gemeinsam minimieren).

    Wenn der Dialog größer als der Parent ist (z.B. Settings-Modal über
    kleinem App-Fenster), wird statt zentriert auf Parent-Top-Left
    ausgerichtet — sonst rutscht die Titlebar oberhalb des Monitorrands.

    Muss gerufen werden, nachdem alle Widgets erstellt sind, damit
    winfo_reqwidth/reqheight die finale Größe liefern.
    """
    dialog.transient(parent)
    dialog.update_idletasks()
    w = dialog.winfo_reqwidth()
    h = dialog.winfo_reqheight()
    px = parent.winfo_rootx()
    py = parent.winfo_rooty()
    pw = parent.winfo_width()
    ph = parent.winfo_height()
    x = px + max(0, (pw - w) // 2)
    y = py + max(0, (ph - h) // 2)
    dialog.geometry(f"+{x}+{y}")


def icon_button(parent, text, command, fg=ACCENT, hover_fg=None, **kw):
    """Compact icon-style button used in the header (‹ › ⚙)."""
    if hover_fg is None:
        hover_fg = fg
    return tk.Button(
        parent, text=text, command=command, width=3,
        font=FONT_BOLD, bg=CELL_BG, fg=fg,
        activebackground=ENTRY_BG, activeforeground=hover_fg,
        relief=tk.FLAT, cursor="hand2", **kw,
    )
