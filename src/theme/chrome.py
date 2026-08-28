# src/theme/chrome.py
"""Fenster-Chrome: dunkle Titelleiste, Min/Max-Buttons, App-Icon, Dialog-Bau.

Der Win32-lastige Teil des Themes (DWM-Attribute ueber ctypes). Auf macOS
und Linux sind die Aufrufe No-ops. `create_dialog` ist der Einstieg für
jeden neuen Dialog — nicht handgebaute Toplevel-Boilerplate.

Zum bekannten kurzen Aufblitzen der hellen Titelleiste siehe
`docs/known-limitations.md` und den Kommentar in `apply_dark_titlebar`.
"""

import os
import platform
import tkinter as tk

from src.paths import get_resource_path

from src.theme.palette import BG, TEXT


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
    base = get_resource_path()
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


def create_dialog(parent, title, *, resizable=False, modal=True,
                  escape_closes=True):
    """Erzeugt einen konventionskonformen Dialog-Toplevel — DER Einstieg
    für neue Dialoge (ersetzt die frühere 8-Zeilen-Chrome-Boilerplate).

    Chrome in fester Reihenfolge: title → resizable(False, False) →
    grab_set → focus_set → configure(bg=BG) → apply_dark_titlebar →
    disable_min_max → apply_app_icon → <Escape>-Bind auf destroy.
    focus_set() MUSS nach grab_set() laufen, sonst feuern Tastatur-
    Bindungen (z.B. Escape) am Dialog nie.

    resizable=True ruft resizable() bewusst NICHT auf (Tk-Default bleibt).
    modal=False lässt grab_set() weg — für Dialoge, die wie die themed_*-
    Familie am Ende selbst center→grab_set→wait_window fahren.
    escape_closes=False lässt den Escape-Bind weg — für Dialoge ohne
    Escape (Settings) oder mit eigener Escape-Semantik (themed_*).

    KEIN transient-Param: transient setzt center_dialog_on_parent —
    bewusst gated auf sichtbaren Parent (Tray-Fall, siehe dort).
    Content-Styles (apply_combobox_style/apply_notebook_style/
    attach_unfocus_on_click) und center_dialog_on_parent (braucht die
    fertige Größe) bleiben beim Aufrufer."""
    dialog = tk.Toplevel(parent)
    dialog.title(title)
    if not resizable:
        dialog.resizable(False, False)
    if modal:
        dialog.grab_set()
    dialog.focus_set()
    dialog.configure(bg=BG)
    apply_dark_titlebar(dialog)
    disable_min_max(dialog)
    apply_app_icon(dialog)
    if escape_closes:
        dialog.bind("<Escape>", lambda _e: dialog.destroy())
    return dialog
