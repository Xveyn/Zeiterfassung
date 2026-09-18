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
import platform
import tkinter as tk
from collections.abc import Callable
from contextlib import contextmanager
from tkinter import ttk

from src.theme.palette import BG, CELL_BG, SEPARATOR, TEXT, TEXT_DISABLED, TEXT_MUTED
from src.theme.fonts import FONT, FONT_BOLD, FONT_SMALL
from src.theme.widgets import _LabelButton, _ToggleColors, secondary_button
from src.theme.form_logic import (
    body_height, enabled_states, is_descendant, wheel_route, wheel_units,
)

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


# Einrückung je Abhängigkeitsebene (Basis 100 %, mitskaliert).
INDENT = 22
# Rand links/rechts innerhalb des Formulars.
_EDGE = 12
# Abstand vor jeder Abschnitts-Überschrift außer der ersten.
_SECTION_GAP = 16
# Kleinste Umbruchbreite eines Hinweises, bevor das Formular gemessen ist.
_MIN_WRAP = 200
_WHEEL_EVENTS = ("<MouseWheel>", "<Button-4>", "<Button-5>")


class Form:
    """Ein Formular = ein Raster mit zwei Spalten, gegliedert in Abschnitte.

    Weil alle Abschnitte im selben Raster liegen, fluchten die Beschriftungen
    über das ganze Formular; die Spaltenbreite ergibt sich aus der längsten
    Beschriftung. Zeilen zählt `Form` selbst.

        form = Form(tab_frame, scroll=True, scale=ui_scale)
        form.frame.pack(fill="both", expand=True)
        form.section("Werkstudenten-Limit")
        form.check("Wochenlimit prüfen", wsl_var)
        with form.depends_on(wsl_var):
            form.row("Max. Stunden", dark_entry(form.body, hours_var, width=6))

    Widgets für `row`/`block` werden mit `form.body` als Parent gebaut.

    `scroll=True` legt den Körper in einen Canvas mit Scrollleiste: er wird
    höchstens `form_logic.body_height` hoch, die Leiste erscheint nur, wenn
    der Inhalt nicht hineinpasst. Das Mausrad scrollt das Formular, außer über
    Widgets, die selbst scrollen (Text, Listbox); über einer Combobox scrollt
    das Formular, und die Combobox ändert ihren Wert nicht.
    """

    def __init__(self, parent, *, scroll=False, scale=1.0):
        self._scale = scale
        self._row = 0
        self._sections = 0
        self._parents: dict[str, str | None] = {}
        self._vars: dict[str, tk.Variable] = {}
        self._members: dict[str, list] = {}
        self._stack: list[str] = []
        self._hints: list[tuple[tk.Label, int]] = []
        self._wrap = 0
        self._scrollable = False
        self._canvas = None
        if scroll:
            self.frame = tk.Frame(parent, bg=BG)
            self._canvas = tk.Canvas(self.frame, bg=BG, highlightthickness=0, bd=0)
            self._bar = ttk.Scrollbar(self.frame, orient="vertical",
                                      command=self._canvas.yview,
                                      style="Vertical.TScrollbar")
            self._canvas.configure(yscrollcommand=self._bar.set)
            self._canvas.grid(row=0, column=0, sticky="nsew")
            self.frame.grid_rowconfigure(0, weight=1)
            self.frame.grid_columnconfigure(0, weight=1)
            self.body = tk.Frame(self._canvas, bg=BG)
            self._canvas.create_window((0, 0), window=self.body, anchor="nw")
            self.body.bind("<Configure>", self._fit_canvas, add="+")
            # Am Toplevel statt per <Enter>/<Leave>: die feuern auch beim
            # Wechsel auf ein Kind-Widget. Jedes Form prüft selbst, ob das
            # Event in seinem Canvas liegt (mehrere Forms je Dialog).
            top = self.frame.winfo_toplevel()
            for seq in _WHEEL_EVENTS:
                top.bind(seq, self._on_wheel, add="+")
        else:
            self.frame = tk.Frame(parent, bg=BG)
            self.body = self.frame
        self.body.grid_columnconfigure(1, weight=1)
        self.body.bind("<Configure>", self._rewrap, add="+")

    # ---- Aufbau --------------------------------------------------------

    def section(self, title, hint=None):
        """Überschrift links, fett, mit feiner Linie bis zum rechten Rand."""
        top = 4 if self._sections == 0 else _SECTION_GAP
        self._sections += 1
        head = tk.Frame(self.body, bg=BG)
        tk.Label(head, text=title, font=FONT_BOLD, bg=BG, fg=TEXT).pack(side=tk.LEFT)
        tk.Frame(head, bg=SEPARATOR, height=1).pack(
            side=tk.LEFT, fill=tk.X, expand=True, padx=(8, 0), pady=(2, 0))
        head.grid(row=self._next_row(), column=0, columnspan=2, sticky="ew",
                  padx=_EDGE, pady=(top, 4))
        if hint:
            self.hint(hint)
        return head

    def row(self, label, widget):
        """Beschriftung in Spalte 0, `widget` (Parent `form.body`) in Spalte 1."""
        r = self._next_row()
        lbl = tk.Label(self.body, text=label, font=FONT, bg=BG, fg=TEXT)
        lbl.grid(row=r, column=0, sticky="w", padx=(self._indent(), 8), pady=4)
        widget.grid(row=r, column=1, sticky="w", padx=(0, _EDGE), pady=4)
        self._register(lbl, widget)
        return lbl

    def check(self, text, var):
        """Checkbox über beide Spalten."""
        cb = tk.Checkbutton(
            self.body, text=text, variable=var, font=FONT,
            bg=BG, fg=TEXT, selectcolor=CELL_BG,
            activebackground=BG, activeforeground=TEXT,
            disabledforeground=TEXT_DISABLED, cursor="hand2",
        )
        cb.grid(row=self._next_row(), column=0, columnspan=2, sticky="w",
                padx=(self._indent(), _EDGE), pady=2)
        self._register(cb)
        return cb

    def hint(self, text):
        """Kleiner, gedämpfter Hinweis über beide Spalten; bricht mit der
        Formularbreite um."""
        indent = self._indent()
        lbl = tk.Label(self.body, text=text, font=FONT_SMALL, bg=BG,
                       fg=TEXT_MUTED, justify="left", anchor="w",
                       wraplength=self._wrap_for(indent))
        lbl.grid(row=self._next_row(), column=0, columnspan=2, sticky="w",
                 padx=(indent, _EDGE), pady=(0, 4))
        self._hints.append((lbl, indent))
        self._register(lbl)
        return lbl

    def buttons(self, *specs: tuple[str, Callable[[], None]]):
        """Linksbündige Knopfreihe über beide Spalten."""
        bar = tk.Frame(self.body, bg=BG)
        made = []
        for text, command in specs:
            btn = secondary_button(bar, text, command)
            btn.pack(side=tk.LEFT, padx=(0, 6))
            made.append(btn)
        bar.grid(row=self._next_row(), column=0, columnspan=2, sticky="w",
                 padx=(self._indent(), _EDGE), pady=(6, 4))
        self._register(*made)
        return made

    def block(self, widget, *, pady=4):
        """Ein eigenes Widget (Parent `form.body`) über beide Spalten —
        Tabellen, Listen, Textfelder."""
        widget.grid(row=self._next_row(), column=0, columnspan=2, sticky="ew",
                    padx=(self._indent(), _EDGE), pady=pady)
        self._register(widget)
        return widget

    @contextmanager
    def depends_on(self, var):
        """Alles, was im `with`-Block entsteht, wird eingerückt und ist nur
        aktiv, solange `var` wahr ist (und alle Schalter darüber). Die
        Variable hält `Form` fest — sie braucht eine lebende Referenz, sonst
        löscht der GC die Tcl-Variable (s. src/CLAUDE.md, Dialoge)."""
        group = f"g{len(self._parents)}"
        self._parents[group] = self._stack[-1] if self._stack else None
        self._vars[group] = var
        self._members[group] = []
        self._stack.append(group)
        try:
            yield
        finally:
            self._stack.pop()
        var.trace_add("write", lambda *_: self.refresh_enabled())
        self.refresh_enabled()

    def refresh_enabled(self):
        """Wendet den aktuellen Zustand aller Schalter auf ihre Gruppen an."""
        values = {}
        for group, var in self._vars.items():
            try:
                values[group] = bool(var.get())
            except tk.TclError:
                # Leeres/ungültiges Feld hinter einer Int-/Double-Variable:
                # gilt als aus, statt den Aufbau abzubrechen.
                values[group] = False
        states = enabled_states(self._parents, values)
        for group, members in self._members.items():
            for widget in members:
                set_enabled(widget, states[group])

    # ---- intern --------------------------------------------------------

    def _next_row(self):
        r = self._row
        self._row += 1
        return r

    def _indent(self):
        return _EDGE + round(INDENT * self._scale) * len(self._stack)

    def _register(self, *widgets):
        if self._canvas is not None:
            for widget in widgets:
                self._guard_value_wheel(widget)
        if self._stack:
            self._members[self._stack[-1]].extend(widgets)

    def _guard_value_wheel(self, widget):
        """Widgets, die beim Rad ihren Wert ändern (Combobox), bekommen eine
        eigene Bindung, die das Formular scrollt und mit "break" das
        Klassen-Binding überspringt — die Toplevel-Bindung käme zu spät, die
        Klasse hätte den Wert dann schon verstellt."""
        if wheel_route(widget.winfo_class()) == "form_block":
            for seq in _WHEEL_EVENTS:
                widget.bind(seq, self._on_blocked_wheel)
        for child in widget.winfo_children():
            self._guard_value_wheel(child)

    def _wrap_for(self, indent):
        """Umbruchbreite eines Hinweises: Formularbreite abzüglich seiner
        Einrückung. Vor der ersten Messung ein fester, mitskalierter Wert."""
        floor = round(_MIN_WRAP * self._scale)
        if not self._wrap:
            return max(floor, round(420 * self._scale))
        return max(floor, self._wrap - indent - _EDGE)

    def _rewrap(self, _event=None):
        width = self.body.winfo_width()
        if width <= 1 or width == self._wrap:
            return
        self._wrap = width
        for lbl, indent in self._hints:
            lbl.config(wraplength=self._wrap_for(indent))

    def _fit_canvas(self, _event=None):
        canvas = self._canvas
        if canvas is None:
            return
        width = self.body.winfo_reqwidth()
        natural = self.body.winfo_reqheight()
        height = body_height(natural, self._scale, canvas.winfo_screenheight())
        canvas.configure(width=width, height=height,
                         scrollregion=(0, 0, width, natural))
        needed = natural > height
        if needed == self._scrollable:
            return
        self._scrollable = needed
        if needed:
            self._bar.grid(row=0, column=1, sticky="ns")
        else:
            self._bar.grid_remove()
            canvas.yview_moveto(0)

    def _scroll(self, event):
        if self._canvas is None or not self._scrollable:
            return
        num = event.num if event.num in (4, 5) else None
        units = wheel_units(platform.system(), int(getattr(event, "delta", 0) or 0), num)
        if units:
            self._canvas.yview_scroll(units, "units")

    def _on_wheel(self, event):
        canvas = self._canvas
        widget = event.widget
        if canvas is None or isinstance(widget, str):
            # Ein während des Events zerstörtes Widget kommt als Pfad-String
            # (s. widgets._click_keeps_focus) — nichts zu scrollen.
            return None
        try:
            if not canvas.winfo_exists():
                return None
            inside = is_descendant(str(widget), str(canvas))
            cls = widget.winfo_class()
        except tk.TclError:
            log.debug("Mausrad: Widget nicht mehr abfragbar", exc_info=True)
            return None
        if inside and wheel_route(cls) == "form":
            self._scroll(event)
        return None

    def _on_blocked_wheel(self, event):
        self._scroll(event)
        return "break"


def empty_state(parent, text, *, bg=BG):
    """Gedämpfter Leertext für eine leere Liste — statt einer leeren Fläche
    ("Noch kein SMTP-Konto angelegt.")."""
    return tk.Label(parent, text=text, font=FONT, bg=bg, fg=TEXT_MUTED,
                    justify="center")
