# src/theme/chrome.py
"""Fenster-Chrome: dunkle Titelleiste, Min/Max-Buttons, App-Icon, Dialog-Bau.

Der Win32-lastige Teil des Themes (DWM-Attribute ueber ctypes). Auf macOS
und Linux sind die Aufrufe No-ops. `create_dialog` ist der Einstieg für
jeden neuen Dialog — nicht handgebaute Toplevel-Boilerplate.

Zum bekannten kurzen Aufblitzen der hellen Titelleiste siehe
`docs/known-limitations.md` und den Kommentar in `apply_dark_titlebar`.
"""

import logging
import os
import platform
import tkinter as tk

from src.paths import get_resource_path

from src.theme.palette import BG, TEXT

log = logging.getLogger(__name__)


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

    **Nur noch für das Hauptfenster** (`ui.py`). Dialoge gehen seit Xveyn#34
    über `reveal_dialog`, das `_apply_dark_titlebar_now` synchron ruft.

    Der `after(100, …)`-Aufschub hier ist ein Rateversuch, und man sollte
    wissen worauf: Tk **erzeugt das Win32-Fenster während des Aufbaus neu**
    (messbar am wechselnden HWND — zuletzt bei `transient()`). Ein vorher
    gesetztes DWM-Attribut hängt danach an einem toten Handle; das ist das
    „Clobbern", von dem dieser Docstring früher sprach. Für ein Toplevel,
    das man verborgen aufbauen kann, ist Raten unnötig — deshalb der eigene
    Weg für Dialoge. Das Hauptfenster hat diese Klammer nicht: es ist von
    Anfang an sichtbar, und es verborgen zu starten wäre eine andere
    Baustelle (s. Xveyn#34, Tray-Restore).

    SET allein triggert auf Win11 24H2 keinen Frame-Redraw, also explizit per
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
        # Best-Effort: schlaegt die Win32-Chrome fehl, sieht das Fenster nur
        # nativ aus statt themed — kein Grund, den Dialog scheitern zu lassen.
        # Aber geloggt, nicht verschluckt: der Aufrufer prueft oben bereits
        # `platform.system() != "Windows"`, ein Fehler HIER ist also ein
        # echter Windows-Fehler und keine Plattform-Unvertraeglichkeit.
        log.debug("Dunkle Titelleiste konnte nicht gesetzt werden", exc_info=True)


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

    Daher Windows-only.

    **Synchron, nicht deferred** (Xveyn#34): gerufen wird das aus
    `reveal_dialog`, wenn der Dialog noch verborgen ist und sein HWND
    endgültig feststeht. Der frühere `after(100, …)`-Aufschub war ein
    Rateversuch auf den Zeitpunkt, zu dem Tk mit dem Neuerzeugen des
    Fensters fertig ist — und der Grund, warum der Dialog vorher sichtbar
    wurde, als er noch hell war.
    """
    if platform.system() != "Windows":
        return
    _disable_min_max_now(window)


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
        # Best-Effort: schlaegt die Win32-Chrome fehl, sieht das Fenster nur
        # nativ aus statt themed — kein Grund, den Dialog scheitern zu lassen.
        # Aber geloggt, nicht verschluckt: der Aufrufer prueft oben bereits
        # `platform.system() != "Windows"`, ein Fehler HIER ist also ein
        # echter Windows-Fehler und keine Plattform-Unvertraeglichkeit.
        log.debug("Min-/Max-Buttons konnten nicht deaktiviert werden", exc_info=True)


def create_dialog(parent, title, *, resizable=False, modal=True,
                  escape_closes=True):
    """Erzeugt einen konventionskonformen Dialog-Toplevel — DER Einstieg
    für neue Dialoge (ersetzt die frühere 8-Zeilen-Chrome-Boilerplate).

    Chrome in fester Reihenfolge: withdraw → title → resizable(False, False)
    → configure(bg=BG) → apply_app_icon → <Escape>-Bind auf destroy.

    **Der Dialog wird verborgen erzeugt** und erst von
    `center_dialog_on_parent` sichtbar gemacht (Xveyn#34). Grund ist der
    Handle-Wechsel: Tk erzeugt das Win32-Fenster während des Aufbaus neu —
    zuletzt bei `transient()`, das `center_dialog_on_parent` setzt. Ein
    DWM-Farbattribut, das vorher gesetzt wurde, hängt danach an einem toten
    HWND. Früher hat `apply_dark_titlebar` deshalb per `after(100, …)` eine
    Zeit *geraten*, zu der Tk fertig sein dürfte — und in genau diesem
    Ratefenster stand der Dialog schon sichtbar mit heller Titelleiste da.
    Verborgen aufgebaut gibt es nichts mehr zu raten: beim Sichtbarmachen
    ist der Handle endgültig, das Attribut wird synchron gesetzt.

    Daraus folgt die **Paarungs-Regel**: wer `create_dialog` ruft, MUSS
    `center_dialog_on_parent` rufen — sonst bleibt der Dialog unsichtbar.
    Alle Aufrufer tun das ohnehin (es war schon vorher Konvention);
    `tests/test_dialog_reveal.py` nagelt es fest.

    `grab_set`/`focus_set` wandern mit ins Sichtbarmachen: ein verborgenes
    Fenster kann keinen Grab nehmen (`TclError: grab failed: window not
    viewable`).

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
    # Vor dem allerersten Map — ein nie gezeigtes Fenster kann nicht hell
    # aufblitzen. Zurückgeholt wird es von center_dialog_on_parent.
    dialog.withdraw()
    dialog.title(title)
    if not resizable:
        dialog.resizable(False, False)
    dialog.configure(bg=BG)
    apply_app_icon(dialog)
    if escape_closes:
        dialog.bind("<Escape>", lambda _e: dialog.destroy())
    # Fremdattribut auf einer stdlib-Klasse: pyright kennt es nicht (`dialog`
    # ist hier als `tk.Toplevel` typisiert), `setattr` verbietet ruff als B010.
    # Also Punkt-Zuweisung plus gezieltes ignore — dasselbe Mittel wie bei den
    # plattform-optionalen Lazy-Imports. Auf der Leseseite (`geometry.py`)
    # fällt nichts an: der Parameter ist dort unannotiert (Tk-Schicht).
    dialog._zeit_reveal = (  # pyright: ignore[reportAttributeAccessIssue]
        lambda: reveal_dialog(dialog, modal=modal))
    return dialog


def reveal_dialog(dialog, *, modal=True):
    """Macht einen von `create_dialog` verborgen erzeugten Dialog sichtbar.

    Reihenfolge ist der ganze Punkt: erst die Fenster-Chrome **synchron**
    (das HWND ist jetzt endgültig, s. `create_dialog`), dann `deiconify`,
    dann `grab_set` (braucht ein sichtbares Fenster) und `focus_set`.
    focus_set MUSS nach grab_set laufen, sonst feuern Tastatur-Bindungen
    (z.B. Escape) am Dialog nie.

    Gerufen von `center_dialog_on_parent` über das Attribut `_zeit_reveal`,
    nicht per Import — `geometry` liegt in der Theme-Schichtung **vor**
    `chrome`, ein Import zurück wäre ein Zyklus.
    """
    if platform.system() == "Windows":
        _apply_dark_titlebar_now(dialog)
    disable_min_max(dialog)   # plattform-gegated, synchron
    dialog.deiconify()
    if modal:
        dialog.grab_set()
    dialog.focus_set()
