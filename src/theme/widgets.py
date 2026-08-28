# src/theme/widgets.py
"""Widget-Fabriken und ttk-Styles des Dark-Themes.

Alles, was ein Widget baut oder umfärbt: Entries, Combos, die
Label-basierten Buttons und die ttk-Styles für Combobox/Notebook.
"""

import tkinter as tk
from tkinter import ttk
from typing import TypedDict


from src.theme.palette import (
    ACCENT, ACCENT_DISABLED, ACCENT_HOVER, BG, CELL_BG, CELL_BG_HOVER,
    ENTRY_BG, TEXT, TEXT_MUTED,
)
from src.theme.fonts import FONT, FONT_BOLD, FONT_SMALL


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


def apply_notebook_style(dialog):
    """Dark-Styling für ttk.Notebook (Tab-Leiste + Inhaltsfläche).

    MUSS nach apply_combobox_style laufen — das setzt global theme_use("clam");
    diese Funktion setzt selbst KEIN Theme. Aktiver Tab bekommt BG (verschmilzt
    mit der Inhaltsfläche), inaktive CELL_BG/TEXT_MUTED, Hover CELL_BG_HOVER.
    bordercolor/lightcolor/darkcolor der Notebook-Fläche auf BG, sonst zeichnet
    clam einen hellen 3D-Rand um den Inhalt, der aus dem Dark-Theme fällt.
    focuscolor=BG unterdrückt den Punktrahmen um den Tab-Text bei Fokus.
    ACCENT wird bewusst NICHT verwendet — das ist der rote Fehler-/Lösch-Akzent."""
    style = ttk.Style(dialog)
    style.configure(
        "Dark.TNotebook",
        background=BG, borderwidth=0, tabmargins=(6, 6, 6, 0),
        bordercolor=BG, lightcolor=BG, darkcolor=BG,
    )
    style.configure(
        "Dark.TNotebook.Tab",
        background=CELL_BG, foreground=TEXT_MUTED,
        bordercolor=BG, lightcolor=CELL_BG, darkcolor=CELL_BG,
        padding=(14, 6), font=FONT, focuscolor=BG,
    )
    style.map(
        "Dark.TNotebook.Tab",
        background=[("selected", BG), ("active", CELL_BG_HOVER)],
        foreground=[("selected", TEXT), ("active", TEXT)],
        lightcolor=[("selected", BG)],
        darkcolor=[("selected", BG)],
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


def set_primary_button_enabled(btn, enabled):
    """Schaltet einen `primary_button` optisch aktiv/inaktiv: deaktiviert =
    gedämpfter Rotton (ACCENT_DISABLED) + Pfeil-Cursor, kein Hover-Wechsel.

    Mutiert `_colors` (die Enter/Leave-Handler lesen frisch daraus) analog
    set_toggle_active. Wichtig: nur die OPTIK — die `command`/on_click-Bindung
    bleibt aktiv, daher muss der Callback selbst bei disabled ein No-op machen
    (Klick auf einen optisch deaktivierten Button soll nichts tun)."""
    cursor = "hand2" if enabled else "arrow"
    c = (
        {"bg": ACCENT, "fg": "#ffffff",
         "hover_bg": ACCENT_HOVER, "hover_fg": "#ffffff"}
        if enabled else
        {"bg": ACCENT_DISABLED, "fg": TEXT_MUTED,
         "hover_bg": ACCENT_DISABLED, "hover_fg": TEXT_MUTED}
    )
    btn._colors = c
    btn.config(bg=c["bg"], cursor=cursor)
    btn._label.config(bg=c["bg"], fg=c["fg"], cursor=cursor)


def set_button_text(btn, text):
    """Setzt den sichtbaren Text eines label_button-Konstrukts (primary_/
    secondary_button). Kapselt den `_label`-Zugriff, damit Aufrufer nicht auf
    das private Innen-Widget greifen (Audit N17)."""
    btn._label.config(text=text)


def set_secondary_button_enabled(btn, enabled):
    """Pendant zu set_primary_button_enabled für `secondary_button`:
    deaktiviert = gedämpfte Schrift (TEXT_MUTED) + Pfeil-Cursor, kein
    Hover-Wechsel. Mutiert `_colors` (Enter/Leave lesen frisch daraus).
    Wichtig: nur die OPTIK — die `command`/on_click-Bindung bleibt aktiv,
    daher muss der Callback selbst bei disabled ein No-op machen."""
    cursor = "hand2" if enabled else "arrow"
    c = (
        {"bg": CELL_BG, "fg": TEXT,
         "hover_bg": ENTRY_BG, "hover_fg": TEXT}
        if enabled else
        {"bg": CELL_BG, "fg": TEXT_MUTED,
         "hover_bg": CELL_BG, "hover_fg": TEXT_MUTED}
    )
    btn._colors = c
    btn.config(bg=c["bg"], cursor=cursor)
    btn._label.config(bg=c["bg"], fg=c["fg"], cursor=cursor)


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
        if _click_keeps_focus(event.widget):
            return
        dialog.focus_set()

    dialog.bind("<Button-1>", _unfocus, add="+")


def _click_keeps_focus(widget):
    """True, wenn der geklickte Widget den Fokus behalten soll (Eingabefeld).

    Defensiv: Wird ein Widget WÄHREND seines Klick-Events zerstört (z.B. die
    "×"-Schaltfläche einer Slot-Zeile im Tages-Dialog), liefert Tk für das
    nachgelagerte Toplevel-`<Button-1>` `event.widget` als Pfad-String statt
    als Widget-Objekt — `winfo_class()` würde dann mit AttributeError crashen.
    Ein String- oder bereits zerstörtes Widget → Fokus auf den Dialog ziehen
    (kein Eingabefeld)."""
    if isinstance(widget, str):
        return False
    try:
        return widget.winfo_class() in _FOCUSABLE_INPUT_CLASSES
    except tk.TclError:
        return False


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


def set_icon_button_enabled(btn, enabled, *, fg=ACCENT):
    """Pendant zu set_primary_button_enabled für `icon_button` (Header-⟳):
    deaktiviert = gedämpfte Schrift (TEXT_MUTED) + Pfeil-Cursor, kein
    Hover-Wechsel; aktiviert zurück auf `fg` (Default ACCENT wie icon_button).

    Ein `icon_button` ist ein `_LabelButton` (Frame) und kennt KEIN `-state` —
    `btn.config(state=...)` wirft `TclError`. Darum diese Optik-only-Variante.
    Wie bei set_primary_button_enabled bleibt die `command`/on_click-Bindung
    aktiv, der Callback muss bei disabled also selbst ein No-op machen."""
    cursor = "hand2" if enabled else "arrow"
    c = (
        {"bg": CELL_BG, "fg": fg,
         "hover_bg": ENTRY_BG, "hover_fg": fg}
        if enabled else
        {"bg": CELL_BG, "fg": TEXT_MUTED,
         "hover_bg": CELL_BG, "hover_fg": TEXT_MUTED}
    )
    btn._colors = c
    btn.config(bg=c["bg"], cursor=cursor)
    btn._label.config(bg=c["bg"], fg=c["fg"], cursor=cursor)
