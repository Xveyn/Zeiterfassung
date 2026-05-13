import platform
import tkinter as tk
from tkinter import ttk

_system = platform.system()
if _system == "Darwin":
    FONT_FAMILY = "Helvetica Neue"
elif _system == "Linux":
    FONT_FAMILY = "DejaVu Sans"
else:
    FONT_FAMILY = "Segoe UI"

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

FONT = (FONT_FAMILY, 10)
FONT_SMALL = (FONT_FAMILY, 8)
FONT_TINY = (FONT_FAMILY, 7)
FONT_BOLD = (FONT_FAMILY, 10, "bold")
FONT_HEADER = (FONT_FAMILY, 16, "bold")
FONT_HEADER_SMALL = (FONT_FAMILY, 12, "bold")
FONT_FOOTER = (FONT_FAMILY, 12, "bold")

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


def label_button(
    parent, text, command, *,
    bg, fg, hover_bg, hover_fg,
    font,
    label_padx=0, label_pady=0,
    width=None,
):
    """Frame+Label-Konstrukt als Button-Ersatz.

    `tk.Button` ignoriert auf macOS bg/fg (Aqua-Backend zeichnet nativ).
    `tk.Label` respektiert bg/fg auf allen Plattformen — daher Label
    mit Klick-Bindings statt echtem Button.

    Rückgabe: tk.Frame mit Attributen `_label` (inneres Label) und
    `_colors` (dict mit bg/fg/hover_bg/hover_fg). set_toggle_active
    mutiert `_colors`; die in dieser Funktion gesetzten Bindings lesen
    daraus — kein Unbind nötig, attach_tooltip (add="+") bleibt
    funktional.
    """
    frame = tk.Frame(parent, bg=bg, cursor="hand2")
    label = tk.Label(
        frame, text=text, font=font,
        bg=bg, fg=fg, cursor="hand2",
        width=width,
    )
    label.pack(padx=label_padx, pady=label_pady)
    frame._label = label
    frame._colors = {
        "bg": bg, "fg": fg,
        "hover_bg": hover_bg, "hover_fg": hover_fg,
    }

    def on_click(_e):
        command()

    def on_enter(_e):
        c = frame._colors
        frame.config(bg=c["hover_bg"])
        label.config(bg=c["hover_bg"], fg=c["hover_fg"])

    def on_leave(_e):
        c = frame._colors
        frame.config(bg=c["bg"])
        label.config(bg=c["bg"], fg=c["fg"])

    for w in (frame, label):
        w.bind("<Button-1>", on_click)
        w.bind("<Enter>", on_enter)
        w.bind("<Leave>", on_leave)

    return frame


def primary_button(parent, text, command, font=FONT_BOLD, padx=16, pady=4):
    return label_button(
        parent, text, command,
        bg=ACCENT, fg="#ffffff",
        hover_bg=ACCENT_HOVER, hover_fg="#ffffff",
        font=font,
        label_padx=padx, label_pady=pady,
    )


def secondary_button(parent, text, command, font=FONT, padx=16, pady=4):
    return label_button(
        parent, text, command,
        bg=CELL_BG, fg=TEXT,
        hover_bg=ENTRY_BG, hover_fg=TEXT,
        font=font,
        label_padx=padx, label_pady=pady,
    )


def _toggle_colors(active):
    if active:
        # Aktive Toggle-Variante: kein Hover-Farbwechsel (würde wie "klickbar" aussehen)
        return {
            "bg": ACCENT, "fg": "#ffffff",
            "hover_bg": ACCENT, "hover_fg": "#ffffff",
        }
    return {
        "bg": CELL_BG, "fg": TEXT_MUTED,
        "hover_bg": ENTRY_BG, "hover_fg": TEXT,
    }


def toggle_button(parent, text, command, active=False):
    """Two-state segmented button used for the Monat/Woche switcher.

    Re-style with set_toggle_active(btn, bool) when state changes.
    """
    return label_button(
        parent, text, command,
        font=FONT_SMALL, width=6,
        **_toggle_colors(active),
    )


def set_toggle_active(btn, active):
    """Mutiert die in `label_button` gesetzten `_colors`. Die Enter/Leave-
    Handler lesen bei jedem Hover frisch daraus — kein Unbind nötig,
    keine Closures mit alten Farben."""
    btn._colors = _toggle_colors(active)
    c = btn._colors
    btn.config(bg=c["bg"])
    btn._label.config(bg=c["bg"], fg=c["fg"])


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


def icon_button(parent, text, command, fg=ACCENT, hover_fg=None):
    """Compact icon-style button used in the header (‹ › ⚙)."""
    if hover_fg is None:
        hover_fg = fg
    return label_button(
        parent, text, command,
        bg=CELL_BG, fg=fg,
        hover_bg=ENTRY_BG, hover_fg=hover_fg,
        font=FONT_BOLD,
        width=3,
    )
