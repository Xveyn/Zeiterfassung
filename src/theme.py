import platform
import tkinter as tk
from tkinter import ttk
from typing import TypedDict

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


class _ToggleColors(TypedDict):
    bg: str
    fg: str
    hover_bg: str
    hover_fg: str


class _LabelButton(tk.Frame):
    """tk.Frame mit zusätzlichen Attributen für das label_button-Konstrukt."""
    _label: tk.Label
    _colors: _ToggleColors


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
    width=0,
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
    frame = _LabelButton(parent, bg=bg, cursor="hand2")
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


def _toggle_colors(active) -> _ToggleColors:
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


def set_toggle_active(btn: _LabelButton, active):
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


def _hex_to_colorref(hex_color: str) -> int:
    """Wandelt '#RRGGBB' in Win32 COLORREF (0x00BBGGRR) — Win32 erwartet
    BGR-Byteorder, nicht RGB."""
    r = int(hex_color[1:3], 16)
    g = int(hex_color[3:5], 16)
    b = int(hex_color[5:7], 16)
    return (b << 16) | (g << 8) | r


def apply_dark_titlebar(window):
    """Färbt auf Windows 11 (22H2+) die Titelleiste in den App-Theme-Farben.

    Nutzt DWM-Attribute (alle Win11 22H2+):
      - DWMWA_CAPTION_COLOR (35): Titelleisten-Hintergrund → `BG`
      - DWMWA_TEXT_COLOR    (36): Titelleisten-Schrift     → `TEXT`
      - DWMWA_BORDER_COLOR  (34): Fensterrand              → `BG`

    Win10-Fallback: DWMWA_USE_IMMERSIVE_DARK_MODE (Index 20 ab Win10 20H1,
    19 davor) — gibt nur Default-Dark statt Custom-Color, aber besser als
    nichts.

    macOS/Linux: No-op (System-Theme bzw. WM zuständig).

    Wichtig: Tk setzt nach Toplevel-Erzeugung weitere Fenster-Properties
    (iconbitmap, resizable, geometry), die das DWM-Attribut clobbern. Daher
    via `window.after(100, ...)` deferren bis nach dem Tk-Init. SET allein
    triggert auf Win11 24H2 keinen Frame-Redraw, also explizit per
    `SetWindowPos(SWP_FRAMECHANGED)` nachschieben.
    """
    if platform.system() != "Windows":
        return
    window.after(100, lambda: _apply_dark_titlebar_now(window))


def _apply_dark_titlebar_now(window):
    try:
        import ctypes
        u32 = ctypes.windll.user32
        GWL_STYLE = -16
        WS_CAPTION = 0x00C00000
        GA_ROOT = 2
        try:
            get_long = u32.GetWindowLongPtrW
        except AttributeError:
            get_long = u32.GetWindowLongW

        wid = window.winfo_id()
        # winfo_id() ist auf Tk-Toplevels die innere Child-HWND (WS_CHILD).
        # Die echte WS_CAPTION-Top-Level ist der GA_ROOT-Ancestor.
        hwnd = u32.GetAncestor(wid, GA_ROOT) or wid
        if not (get_long(hwnd, GWL_STYLE) & WS_CAPTION):
            return

        set_attr = ctypes.windll.dwmapi.DwmSetWindowAttribute
        bg = ctypes.c_int(_hex_to_colorref(BG))
        text = ctypes.c_int(_hex_to_colorref(TEXT))

        DWMWA_BORDER_COLOR, DWMWA_CAPTION_COLOR, DWMWA_TEXT_COLOR = 34, 35, 36
        DWMWA_USE_IMMERSIVE_DARK_MODE = 20

        set_attr(hwnd, DWMWA_CAPTION_COLOR, ctypes.byref(bg), ctypes.sizeof(bg))
        set_attr(hwnd, DWMWA_TEXT_COLOR, ctypes.byref(text), ctypes.sizeof(text))
        set_attr(hwnd, DWMWA_BORDER_COLOR, ctypes.byref(bg), ctypes.sizeof(bg))

        # Win10-Fallback (Default-Dark statt Light)
        dark = ctypes.c_int(1)
        for attribute in (20, 19):
            if set_attr(hwnd, attribute, ctypes.byref(dark), ctypes.sizeof(dark)) == 0:
                break

        # SET allein reicht auf Win11 nicht, wenn das Fenster bereits gemappt
        # ist — Frame ist gecached. SWP_FRAMECHANGED zwingt Recalc der
        # Non-Client-Area, DWM zeichnet sie mit den neuen Attributen neu.
        SWP_NOSIZE, SWP_NOMOVE, SWP_NOZORDER, SWP_NOACTIVATE, SWP_FRAMECHANGED = 0x1, 0x2, 0x4, 0x10, 0x20
        u32.SetWindowPos(hwnd, 0, 0, 0, 0, 0,
            SWP_NOSIZE | SWP_NOMOVE | SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED)
    except Exception:
        pass


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
