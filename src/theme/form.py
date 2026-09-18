# src/theme/form.py
"""Formular-Bausteine des Dark-Themes (#132).

Ein Formular ist ein Raster mit zwei Spalten — links die Beschriftung, rechts
das Bedienelement —, gegliedert in linksbündige Abschnitte. Abhängige Optionen
werden eingerückt und ausgegraut, solange ihr Schalter aus ist. Auf Wunsch
scrollt der Formular-Körper, statt den Dialog aus dem Bildschirm wachsen zu
lassen.

Die Entscheidungen dahinter liegen Tk-frei in `form_logic.py` und sind dort
getestet; hier steht nur ihre Umsetzung in Tk.
"""

import logging
import tkinter as tk
from tkinter import ttk

from src.theme.palette import CELL_BG, TEXT, TEXT_DISABLED
from src.theme.widgets import _LabelButton, _ToggleColors

log = logging.getLogger(__name__)


def set_enabled(widget, on):
    """Schaltet ein Widget bedienbar oder ausgegraut — Zustand UND Farbe.

    Kennt jede Widget-Art der Dialoge: die Label-Buttons aus `widgets`, alle
    ttk-Widgets (Combobox), `tk.Entry`, Check-/Radiobuttons, `tk.Text`,
    `tk.Label` und Container (`tk.Frame`), deren Kinder rekursiv folgen. Ein
    ausgegrautes Feld behält seinen Wert."""
    if isinstance(widget, _LabelButton):
        _set_label_button_enabled(widget, on)
        return
    if isinstance(widget, ttk.Widget):
        widget.state(["!disabled"] if on else ["disabled"])
        return
    state = tk.NORMAL if on else tk.DISABLED
    if isinstance(widget, tk.Entry):
        widget.config(state=state, disabledbackground=CELL_BG,
                      disabledforeground=TEXT_DISABLED)
    elif isinstance(widget, (tk.Checkbutton, tk.Radiobutton)):
        widget.config(state=state, disabledforeground=TEXT_DISABLED)
    elif isinstance(widget, tk.Text):
        widget.config(state=state, fg=TEXT if on else TEXT_DISABLED)
    elif isinstance(widget, tk.Label):
        _set_label_enabled(widget, on)
    elif isinstance(widget, tk.Frame):
        for child in widget.winfo_children():
            set_enabled(child, on)
    else:
        try:
            widget.config(state=state)
        except tk.TclError:
            # Widget ohne -state (etwa ein Canvas): bleibt, wie es ist.
            log.debug("set_enabled: %s kennt keinen state",
                      widget.winfo_class(), exc_info=True)


def _set_label_enabled(label, on):
    """Labels kennen keinen gesperrten Zustand mit eigener Farbe — also die
    Schriftfarbe tauschen und die ursprüngliche merken (ein Hinweis ist
    gedämpft, eine Beschriftung nicht; beide sollen zurück)."""
    if not on:
        if not hasattr(label, "_zeit_fg") or label._zeit_fg is None:
            label._zeit_fg = label.cget("fg")
        label.config(fg=TEXT_DISABLED)
    else:
        if hasattr(label, "_zeit_fg") and label._zeit_fg is not None:
            label.config(fg=label._zeit_fg)


def _set_label_button_enabled(btn: _LabelButton, on):
    """Gesperrt: Schrift in TEXT_DISABLED, kein Hover-Wechsel, Pfeil-Cursor,
    und der Klick tut nichts (`label_button` prüft `_zeit_disabled`). Die
    Farben davor werden gemerkt und beim Entsperren zurückgesetzt."""
    if on == (not btn._zeit_disabled):
        return
    if not on:
        btn._zeit_colors = btn._colors
        bg = btn._colors["bg"]
        btn._colors = _ToggleColors(
            bg=bg, fg=TEXT_DISABLED, hover_bg=bg, hover_fg=TEXT_DISABLED)
    else:
        btn._colors = btn._zeit_colors
    btn._zeit_disabled = not on
    cursor = "hand2" if on else "arrow"
    c = btn._colors
    btn.config(bg=c["bg"], cursor=cursor)
    btn._label.config(bg=c["bg"], fg=c["fg"], cursor=cursor)
