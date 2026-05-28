import os
import platform
import tkinter as tk
from tkinter import ttk
from typing import TypedDict

from src.paths import get_base_path

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

# Reservation cell colors ("geplant"-Look — violetter Akzent, abgesetzt von
# der roten Ist-Zeit-Zelle und der grünen Feiertagszelle)
RESERVATION_BG = "#2a2150"
RESERVATION_BG_HOVER = "#352a66"
RESERVATION_ACCENT = "#a78bfa"

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
    # background MUSS für readonly explizit gemappt werden — sonst rendert
    # clam den Pfeil-Button (Combobox.downarrow) im System-Default-Hell statt
    # in CELL_BG. fieldbackground reicht nicht, weil das nur das Textfeld
    # links färbt, nicht den Button rechts.
    style.map("Dark.TCombobox",
        fieldbackground=[("readonly", CELL_BG)],
        background=[("readonly", CELL_BG), ("active", CELL_BG)],
        selectbackground=[("readonly", CELL_BG)],
        selectforeground=[("readonly", TEXT)],
        bordercolor=[("focus", ACCENT)],
        arrowcolor=[("readonly", ACCENT), ("active", ACCENT)],
    )
    # ComboboxPopdownFrame ist die ttk-Klasse des Frames innen im Popdown.
    # background=CELL_BG sorgt dafür, dass keine helle System-Default-Fläche
    # zwischen Listbox und Scrollbar durchblitzt.
    style.configure(
        "ComboboxPopdownFrame",
        borderwidth=0, relief="flat",
        background=CELL_BG,
    )

    # Der Popdown selbst ist ein Toplevel der Klasse ComboboxPopdown, der in
    # combobox.tcl mit -borderwidth 1 -relief solid hardcoded ist. Die Farbe
    # dieses Borders folgt der Toplevel-background. Per option_add auf die
    # Klasse setzen wir background=ENTRY_BG → dezenter 1px-Rand statt heller
    # Systemfarbe.
    dialog.option_add("*ComboboxPopdown.background", ENTRY_BG)

    # Listbox-Optionen können laut Tk-Doku NICHT per ttk.Style gesetzt werden,
    # nur per option_add. selectBackground=ENTRY_BG (dezenter Hover) statt
    # ACCENT — ttk::combobox bindet <Motion> so, dass die Selection mit der
    # Maus wandert, „selected" und „hover" sind dadurch dasselbe. ACCENT war
    # beim Scrollen zu aggressiv; ENTRY_BG passt zum Theme.
    dialog.option_add("*TCombobox*Listbox.background", CELL_BG)
    dialog.option_add("*TCombobox*Listbox.foreground", TEXT)
    dialog.option_add("*TCombobox*Listbox.selectBackground", ENTRY_BG)
    dialog.option_add("*TCombobox*Listbox.selectForeground", TEXT)
    dialog.option_add("*TCombobox*Listbox.borderWidth", 0)
    dialog.option_add("*TCombobox*Listbox.activeStyle", "none")
    dialog.option_add("*TCombobox*Listbox.font", FONT)

    # Die Scrollbar im Combobox-Popdown ist eine ttk::scrollbar (kein legacy
    # tk.Scrollbar) — daher greifen option_add-Properties nicht, nur ttk.Style.
    # clam-Theme stylt die Vertical.TScrollbar über background/troughcolor/
    # bordercolor/arrowcolor; lightcolor/darkcolor müssen mitgesetzt werden,
    # sonst zeichnet clam einen 3D-Effekt mit hellen Highlights.
    style.configure(
        "Vertical.TScrollbar",
        background=ENTRY_BG, troughcolor=CELL_BG,
        bordercolor=CELL_BG, arrowcolor=TEXT_MUTED,
        lightcolor=ENTRY_BG, darkcolor=ENTRY_BG,
        gripcount=0,
    )
    style.map(
        "Vertical.TScrollbar",
        background=[("active", ACCENT), ("pressed", ACCENT)],
        arrowcolor=[("active", TEXT), ("pressed", TEXT)],
    )


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


_FOCUSABLE_INPUT_CLASSES = frozenset({
    "Entry", "Text", "Checkbutton", "Spinbox", "Listbox", "Radiobutton",
    "TCombobox", "TEntry", "TSpinbox", "TCheckbutton",
})


def attach_unfocus_on_click(dialog):
    """Klick auf nicht-interaktive Bereiche zieht den Fokus weg von
    Eingabefeldern. Sonst bleibt der rote Fokusrand (`highlightcolor=ACCENT`)
    auf einem Entry sichtbar, auch wenn der User längst nicht mehr darin
    schreibt.

    Tk's Standard-bindtags enthalten den Toplevel bei jedem Descendant —
    eine einzige `<Button-1>`-Bindung auf dem Dialog fängt daher alle Klicks
    im Dialog. Im Handler filtern wir nach Widget-Klasse: fokussierbare
    Eingabe-Widgets (Entry, Text, Checkbutton, Combobox, …) ziehen den
    Fokus selbst und sollen ihn behalten; bei allen anderen Klicks (Label,
    Frame-Bg, Frame+Label-Button) ziehen wir den Fokus auf den Dialog.
    """
    def _unfocus(event):
        if event.widget.winfo_class() in _FOCUSABLE_INPUT_CLASSES:
            return
        dialog.focus_set()

    dialog.bind("<Button-1>", _unfocus, add="+")


def _parent_workarea(parent):
    """Liefert (left, top, right, bottom) der taskbar-freien Arbeitsfläche
    des Monitors, auf dem `parent` liegt.

    `wm_maxsize()` liefert auf Windows nur die Arbeitsfläche des Primär-
    monitors — bei einem Parent auf Monitor 2 würde das Clamping den Dialog
    fälschlich zurück auf Monitor 1 ziehen. Daher auf Windows direkt via
    ctypes den richtigen Monitor des Parent ermitteln.

    macOS/Linux: Multi-Monitor-Workarea ist ohne externe Lib nicht sauber
    aus Tk abrufbar — Fallback auf den Primärmonitor (`wm_maxsize`).
    """
    if platform.system() == "Windows":
        try:
            import ctypes
            from ctypes import wintypes

            class RECT(ctypes.Structure):
                _fields_ = [
                    ("left", wintypes.LONG), ("top", wintypes.LONG),
                    ("right", wintypes.LONG), ("bottom", wintypes.LONG),
                ]

            class MONITORINFO(ctypes.Structure):
                _fields_ = [
                    ("cbSize", wintypes.DWORD), ("rcMonitor", RECT),
                    ("rcWork", RECT), ("dwFlags", wintypes.DWORD),
                ]

            user32 = ctypes.windll.user32
            # argtypes/restype explizit setzen — ohne das ist restype c_int
            # (32 Bit), und ein HMONITOR auf 64-Bit-Windows kann darüber
            # liegen → truncated → GetMonitorInfo bekommt einen ungültigen
            # Handle → Fallback auf Primärmonitor (genau der bisherige Bug).
            user32.MonitorFromPoint.argtypes = [wintypes.POINT, wintypes.DWORD]
            user32.MonitorFromPoint.restype = wintypes.HANDLE
            user32.GetMonitorInfoW.argtypes = [
                wintypes.HANDLE, ctypes.POINTER(MONITORINFO)]
            user32.GetMonitorInfoW.restype = wintypes.BOOL

            MONITOR_DEFAULTTONEAREST = 2
            # Lookup über den Mittelpunkt des Parent statt über dessen HWND:
            # Tk's winfo_id() liefert auf Windows den Client-HWND (nicht den
            # WM-Frame). MonitorFromPoint umgeht die HWND-Abstraktion und
            # arbeitet direkt auf den Bildschirmkoordinaten, die Tk per
            # winfo_rootx/y konsistent liefert.
            cx = parent.winfo_rootx() + parent.winfo_width() // 2
            cy = parent.winfo_rooty() + parent.winfo_height() // 2
            pt = wintypes.POINT(cx, cy)
            hmon = user32.MonitorFromPoint(pt, MONITOR_DEFAULTTONEAREST)
            if hmon:
                mi = MONITORINFO()
                mi.cbSize = ctypes.sizeof(MONITORINFO)
                if user32.GetMonitorInfoW(hmon, ctypes.byref(mi)):
                    r = mi.rcWork
                    return (r.left, r.top, r.right, r.bottom)
        except Exception:
            pass  # Fallback unten

    try:
        max_w, max_h = parent.wm_maxsize()
    except tk.TclError:
        max_w = parent.winfo_screenwidth()
        max_h = parent.winfo_screenheight()
    return (0, 0, max_w, max_h)


def center_dialog_on_parent(dialog, parent):
    """Position a Toplevel dialog over its parent's screen rect.

    Tk-Default platziert Toplevels auf dem Primärmonitor — bei Multi-Monitor-
    Setups öffnet sich der Dialog daher nicht beim Parent. transient() bindet
    den Dialog zusätzlich an den Parent (Icon, Z-Order, gemeinsam minimieren).

    Wenn der Dialog größer als der Parent ist (z.B. Settings-Modal über
    kleinem App-Fenster), wird statt zentriert auf Parent-Top-Left
    ausgerichtet — sonst rutscht die Titlebar oberhalb des Monitorrands.

    Danach wird die Position an die Arbeitsfläche **des Parent-Monitors**
    geklammert, damit ein Parent am unteren/oberen Rand den Dialog nicht aus
    dem sichtbaren Bereich schiebt und gleichzeitig auf demselben Bildschirm
    bleibt wie der Parent (siehe `_parent_workarea`).

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
    wa_left, wa_top, wa_right, wa_bottom = _parent_workarea(parent)
    x = px + max(0, (pw - w) // 2)
    y = py + max(0, (ph - h) // 2)
    # max(wa_*, wa_*_far - *) sorgt dafür, dass bei einem Dialog größer als
    # der Bildschirm der obere/linke Rand sichtbar bleibt.
    x = max(wa_left, min(x, max(wa_left, wa_right - w)))
    y = max(wa_top, min(y, max(wa_top, wa_bottom - h)))
    dialog.geometry(f"+{x}+{y}")


def _hex_to_colorref(hex_color: str) -> int:
    """Wandelt '#RRGGBB' in Win32 COLORREF (0x00BBGGRR) — Win32 erwartet
    BGR-Byteorder, nicht RGB."""
    r = int(hex_color[1:3], 16)
    g = int(hex_color[3:5], 16)
    b = int(hex_color[5:7], 16)
    return (b << 16) | (g << 8) | r


_app_icon_ref: tk.PhotoImage | None = None


def apply_app_icon(window):
    """Setzt das App-Icon (margenheld-icon) auf einen Toplevel.

    iconphoto(default=True) auf dem Root-Window vererbt das Icon auf Windows
    nicht zuverlässig auf neue Toplevels — die zeigen dann das Tk-Default-
    Feder-Icon in der Taskbar/Titelleiste. Daher pro Toplevel explizit:
    auf Windows iconbitmap (.ico, multi-resolution → Taskbar scharf), auf
    allen Plattformen zusätzlich iconphoto (PNG, Title-Bar in Tk).

    Referenz auf das PhotoImage wird modul-global gehalten — Tk löscht das
    Bild sonst per GC, sobald die lokale Variable aus dem Scope fällt, und
    der Icon-Slot wird leer.
    """
    # Windows: nichts tun. Das App-weite Default-Icon wird einmal in ui.py
    # via root.iconbitmap(default=ico_path) gesetzt; alle Toplevels erben
    # es und Windows rendert die ICO multi-resolution sauber. Ein
    # zusätzliches iconphoto(.png) würde das ICO überschreiben mit einem
    # PNG-Render, das anders aussieht (Rand, Anti-Aliasing).
    if platform.system() == "Windows":
        return
    global _app_icon_ref
    base = get_base_path()
    png_path = os.path.join(base, "assets", "margenheld-icon.png")
    if os.path.exists(png_path):
        try:
            if _app_icon_ref is None:
                _app_icon_ref = tk.PhotoImage(file=png_path)
            window.iconphoto(False, _app_icon_ref)
        except tk.TclError:
            pass


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


def disable_min_max(window):
    """Entfernt Minimize- und Maximize-Buttons aus der Titelleiste eines
    Modal-Dialogs auf Windows.

    Wichtig: Windows rendert Min und Max als Paar — wenn einer fehlt, wird
    der andere ausgegraut angezeigt statt versteckt. Nur wenn BEIDE
    (WS_MAXIMIZEBOX + WS_MINIMIZEBOX) aus dem Window-Style entfernt sind,
    zeigt die Titelleiste nur den Close-Button (Modal-typisch).

    Plattform-Verhalten:
      - macOS: `resizable(False, False)` deaktiviert die Traffic-Light-
        Buttons (grün/gelb) bereits — kein Win32-Pendant nötig.
      - Linux: `transient(parent)` führt bei den meisten WMs (GNOME/KDE/
        Mutter) dazu, dass kein Min/Max gerendert wird.

    Daher Windows-only. Deferred via after(100, …) wie apply_dark_titlebar.
    """
    if platform.system() != "Windows":
        return
    window.after(100, lambda: _disable_min_max_now(window))


def _disable_min_max_now(window):
    try:
        import ctypes
        from ctypes import wintypes
        u32 = ctypes.windll.user32
        GWL_STYLE = -16
        WS_MAXIMIZEBOX = 0x00010000
        WS_MINIMIZEBOX = 0x00020000
        GA_ROOT = 2

        # argtypes/restype explizit — sonst returnt ctypes Pointer als c_int
        # (32 Bit), HWNDs auf 64-Bit-Windows werden truncated → GetAncestor
        # liefert ungültigen Handle → Style-Modifikation läuft ins Leere.
        u32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
        u32.GetAncestor.restype = wintypes.HWND
        # GWL_STYLE-Wert ist ein LONG (32-bit), aber der HWND-Parameter
        # muss als HWND deklariert sein, nicht als c_int.
        try:
            get_long = u32.GetWindowLongPtrW
            set_long = u32.SetWindowLongPtrW
            get_long.argtypes = [wintypes.HWND, ctypes.c_int]
            get_long.restype = ctypes.c_ssize_t
            set_long.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
            set_long.restype = ctypes.c_ssize_t
        except AttributeError:
            get_long = u32.GetWindowLongW
            set_long = u32.SetWindowLongW
            get_long.argtypes = [wintypes.HWND, ctypes.c_int]
            get_long.restype = wintypes.LONG
            set_long.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.LONG]
            set_long.restype = wintypes.LONG

        u32.SetWindowPos.argtypes = [
            wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
            ctypes.c_int, ctypes.c_int, wintypes.UINT,
        ]
        u32.SetWindowPos.restype = wintypes.BOOL

        wid = window.winfo_id()
        hwnd = u32.GetAncestor(wid, GA_ROOT) or wid
        style = get_long(hwnd, GWL_STYLE)
        set_long(hwnd, GWL_STYLE, style & ~(WS_MAXIMIZEBOX | WS_MINIMIZEBOX))

        SWP_NOSIZE, SWP_NOMOVE, SWP_NOZORDER, SWP_NOACTIVATE, SWP_FRAMECHANGED = 0x1, 0x2, 0x4, 0x10, 0x20
        u32.SetWindowPos(hwnd, 0, 0, 0, 0, 0,
            SWP_NOSIZE | SWP_NOMOVE | SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED)
    except Exception:
        pass


def themed_askyesno(parent, title: str, message: str) -> bool:
    """Modaler Ja/Nein-Dialog im App-Theme. Drop-in für `messagebox.askyesno`.

    Eigener Toplevel statt der Tk-Messagebox, damit die DWM-Titelleiste
    (apply_dark_titlebar) und die Theme-Farben angewendet werden können —
    `tkinter.messagebox.*` ist eine Black-Box ohne Customization-Hooks.
    """
    dialog = tk.Toplevel(parent)
    dialog.title(title)
    dialog.resizable(False, False)
    dialog.configure(bg=BG)
    apply_dark_titlebar(dialog)
    disable_min_max(dialog)
    apply_app_icon(dialog)
    dialog.focus_set()

    result = {"value": False}

    tk.Label(
        dialog, text=message, font=FONT, bg=BG, fg=TEXT,
        wraplength=380, justify="left",
    ).pack(padx=24, pady=(20, 14))

    def click_yes():
        result["value"] = True
        dialog.destroy()

    def click_no():
        dialog.destroy()

    btn_frame = tk.Frame(dialog, bg=BG)
    btn_frame.pack(pady=(0, 18))
    primary_button(btn_frame, "Ja", click_yes).pack(side=tk.LEFT, padx=6)
    secondary_button(btn_frame, "Nein", click_no).pack(side=tk.LEFT, padx=6)

    dialog.bind("<Return>", lambda e: click_yes())
    dialog.bind("<Escape>", lambda e: click_no())
    dialog.protocol("WM_DELETE_WINDOW", click_no)

    center_dialog_on_parent(dialog, parent)
    dialog.grab_set()
    dialog.wait_window()
    return result["value"]


def themed_showinfo(parent, title: str, message: str) -> None:
    """Modaler Info-Dialog im App-Theme. Drop-in für `messagebox.showinfo`.

    Eigener Toplevel mit Dark-Theme-Farben und gebrandeter Titelleiste —
    `tkinter.messagebox.*` ist eine Black-Box ohne Customization-Hooks.
    """
    dialog = tk.Toplevel(parent)
    dialog.title(title)
    dialog.resizable(False, False)
    dialog.configure(bg=BG)
    apply_dark_titlebar(dialog)
    disable_min_max(dialog)
    apply_app_icon(dialog)
    dialog.focus_set()

    tk.Label(
        dialog, text=message, font=FONT, bg=BG, fg=TEXT,
        wraplength=380, justify="left",
    ).pack(padx=24, pady=(20, 14))

    btn_frame = tk.Frame(dialog, bg=BG)
    btn_frame.pack(pady=(0, 18))
    primary_button(btn_frame, "OK", dialog.destroy).pack()

    dialog.bind("<Return>", lambda e: dialog.destroy())
    dialog.bind("<Escape>", lambda e: dialog.destroy())
    dialog.protocol("WM_DELETE_WINDOW", dialog.destroy)

    center_dialog_on_parent(dialog, parent)
    dialog.grab_set()
    dialog.wait_window()


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
