# src/theme/geometry.py
"""Fenster-Geometrie und zwei reine Prädikate.

`center_dialog_on_parent` ist der Geometrie-Teil; `_stray_click_suppressed`
(Streuklick-Guard) und `_should_show_delete_button` (macOS-✕-Regel) sind
Tk-freie Policy-Funktionen und werden direkt getestet
(`tests/test_click_guard.py`, `tests/test_delete_button.py`).
"""

import platform
import time
import tkinter as tk


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


STRAY_CLICK_GUARD_S = 0.2


def _stray_click_suppressed(closed_at, now, window=STRAY_CLICK_GUARD_S):
    """True, wenn ein Klick unterdrückt werden soll, weil gerade (< `window`
    Sekunden) ein Dialog geschlossen wurde — sonst schlägt der Schließ-Klick auf
    eine Kalenderzelle durch (#44).

    `closed_at` ist ein `time.monotonic()`-Wert oder 0/None (nie ein Dialog
    geschlossen). Grenze offen: genau bei `window` wird nicht mehr unterdrückt.
    now < closed_at (Uhr-Anomalie, mit monotonic praktisch unmöglich) → nicht
    unterdrücken.
    """
    if not closed_at:
        return False
    return 0 <= (now - closed_at) < window


def _should_show_delete_button(is_macos, has_entry, has_reservation):
    """macOS-only Lösch-Button (✕) in der Tageszelle: nur auf macOS und nur,
    wenn der Tag löschbare Einheiten hat — Ist-Zeit ODER aktive Reservierung.
    Reine Logik, damit aus den Tests ohne Tk/UI-Deps prüfbar (vgl.
    _stray_click_suppressed)."""
    return is_macos and (has_entry or has_reservation)


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

    transient() bindet den Dialog an den Parent (Z-Order über Parent, Icon,
    gemeinsames Minimieren). ABER: Ist der Parent gerade `withdraw()`n (Tray-
    Modus — Dialog kommt aus einer Tray-Quick-Action), zeigt der Window-Manager
    ein transientes Fenster zu einem versteckten Master NICHT sauber an: es
    erscheint unfokussiert hinter anderen Fenstern und die Dark-Titelleiste
    wird nicht gerendert. Daher transient nur bei sichtbarem Parent setzen; ist
    er versteckt, bleibt der Dialog ein eigenständiges Top-Level und wird unten
    selbst in den Vordergrund geholt und fokussiert.
    """
    parent_viewable = bool(parent.winfo_viewable())
    if parent_viewable:
        dialog.transient(parent)
    dialog.update_idletasks()
    w = dialog.winfo_reqwidth()
    h = dialog.winfo_reqheight()
    px = parent.winfo_rootx()
    py = parent.winfo_rooty()
    pw = parent.winfo_width()
    ph = parent.winfo_height()
    wa_left, wa_top, wa_right, wa_bottom = _parent_workarea(parent)
    if parent_viewable:
        x = px + max(0, (pw - w) // 2)
        y = py + max(0, (ph - h) // 2)
        # max(wa_*, wa_*_far - *) sorgt dafür, dass bei einem Dialog größer als
        # der Bildschirm der obere/linke Rand sichtbar bleibt.
        x = max(wa_left, min(x, max(wa_left, wa_right - w)))
        y = max(wa_top, min(y, max(wa_top, wa_bottom - h)))
    else:
        # Hauptfenster versteckt (Tray-Quick-Action): an der letzten Parent-
        # Position zu zentrieren wirkt zufällig. Stattdessen auf der Arbeits-
        # fläche des (zuletzt genutzten) Monitors mittig setzen.
        x = wa_left + max(0, (wa_right - wa_left - w) // 2)
        y = wa_top + max(0, (wa_bottom - wa_top - h) // 2)
    dialog.geometry(f"+{x}+{y}")

    if not parent_viewable:
        # Ohne transient-Bindung muss der Dialog selbst nach vorn — sonst
        # öffnet er bei verstecktem Hauptfenster unfokussiert im Hintergrund.
        dialog.lift()
        dialog.focus_force()

    # Stray-Klick-Guard (#44): Schließt dieser Dialog, während das Hauptfenster
    # sichtbar dahinter liegt, kann der Schließ-Klick auf eine Kalenderzelle
    # durchschlagen. Beim Zerstören den Schließzeitpunkt aufs Toplevel stempeln;
    # die Klick-Handler in ui.py ignorieren Klicks im Guard-Fenster. Nur bei
    # sichtbarem Parent (im Tray-/withdrawn-Zustand gibt es keinen Durchschlag).
    def _stamp_close(event, _dialog=dialog, _parent=parent):
        if str(event.widget) != str(_dialog):
            return  # Destroy eines Kind-Widgets, nicht des Dialogs selbst.
        try:
            if _parent.winfo_viewable():
                _parent.winfo_toplevel()._dialog_closed_at = time.monotonic()
        except tk.TclError:
            pass  # Parent bereits zerstört (App-Teardown) — irrelevant.

    dialog.bind("<Destroy>", _stamp_close, add="+")
