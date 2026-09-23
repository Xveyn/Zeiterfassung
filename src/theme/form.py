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
from src.theme.fonts import FONT, FONT_BOLD, FONT_SMALL, current_scale, px
from src.theme.widgets import _LabelButton, _ToggleColors, secondary_button
from src.theme.form_logic import (
    WHEEL_STEP, body_height, enabled_states, is_descendant, scroll_target,
    scroll_units, wheel_route,
)

log = logging.getLogger(__name__)


def set_enabled(widget, on):
    """Schaltet ein Widget bedienbar oder ausgegraut — Zustand UND Farbe.

    Kennt jede Widget-Art der Dialoge: die Label-Buttons aus `widgets`, alle
    ttk-Widgets (Combobox), `tk.Entry`, Check-/Radiobuttons, `tk.Text`,
    `tk.Label` und Container (`tk.Frame`/`tk.LabelFrame`/`ttk.Frame`), deren
    Kinder rekursiv folgen. Ein ausgegrautes Feld behält seinen Wert.

    Label-Buttons NIE zugleich über `set_enabled` UND einen der
    `set_*_button_enabled`-Helfer (`set_primary_button_enabled`/
    `set_secondary_button_enabled`/`set_icon_button_enabled`) steuern — beide
    Wege mutieren dieselben `_colors`/`_zeit_*`-Attribute des Buttons und
    laufen sich sonst gegenseitig den Rang ab (welcher zuletzt lief,
    gewinnt, aber undokumentiert)."""
    if isinstance(widget, _LabelButton):
        _set_label_button_enabled(widget, on)
        return
    if isinstance(widget, ttk.Frame):
        # Vor dem generischen ttk.Widget-Zweig: ein ttk.Frame hat kein
        # sinnvolles eigenes -state (state(["disabled"]) ändert an einem
        # Frame optisch nichts) — gemeint ist immer, seine Kinder zu sperren.
        for child in widget.winfo_children():
            set_enabled(child, on)
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
        # Cursor nur mitziehen, wenn er gerade den Gegenwert der Zielrichtung
        # trägt — sonst bekäme ein Check-/Radiobutton ohne je gesetztes
        # cursor="hand2" (form.check() setzt es, ein künftiger Aufrufer
        # vielleicht nicht) beim Aktivieren einen Hand-Cursor aufgezwungen,
        # den er vorher nie hatte.
        if not on and widget.cget("cursor") == "hand2":
            widget.config(cursor="arrow")
        elif on and widget.cget("cursor") == "arrow":
            widget.config(cursor="hand2")
    elif isinstance(widget, tk.Text):
        widget.config(state=state, fg=TEXT if on else TEXT_DISABLED)
    elif isinstance(widget, tk.Label):
        _set_label_enabled(widget, on)
    elif isinstance(widget, (tk.Frame, tk.LabelFrame)):
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
    gedämpft, eine Beschriftung nicht; beide sollen zurück).

    `_zeit_fg` wird beim Wiederherstellen wieder geleert: sonst hielte ein
    Label über mehrere disable/enable-Zyklen hinweg die Farbe der ERSTEN
    Aufnahme fest, auch wenn sich die Farbe zwischenzeitlich (z.B. durch
    eine neue Kategorie) geändert hat."""
    if not on:
        if getattr(label, "_zeit_fg", None) is None:
            label._zeit_fg = label.cget("fg")
        label.config(fg=TEXT_DISABLED)
    elif getattr(label, "_zeit_fg", None) is not None:
        label.config(fg=label._zeit_fg)
        label._zeit_fg = None


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
# Umbruchbreite eines Hinweises vor der ersten Messung (mitskaliert) — vorher
# ein Literal, jetzt benannt, damit sie neben `_MIN_WRAP` sichtbar bleibt.
_INITIAL_WRAP = 420
# <MouseWheel> feuert auf Windows und macOS; <Button-4>/<Button-5> sind die
# X11-Tastencodes für das Rad (Linux) und dort NUR gemeint — auf Windows/macOS
# lauern sie ungenutzt, aber harmlos... außer dass ein völlig anderes Gerät
# (z.B. Maustaste 4/5 einer Gaming-Maus) rein zufällig dieselben Button-Codes
# senden kann. `_wheel_sequences` bindet sie deshalb nur dort, wo sie
# tatsächlich das Mausrad bedeuten.
_WHEEL_EVENTS = ("<MouseWheel>",)
_X11_WHEEL_EVENTS = ("<Button-4>", "<Button-5>")


def _wheel_sequences(widget):
    """Event-Sequenzen, die an `widget` als Mausrad gebunden werden sollen:
    `<MouseWheel>` immer, `<Button-4>`/`<Button-5>` nur unter X11 (s.
    `_X11_WHEEL_EVENTS`)."""
    if widget.tk.call("tk", "windowingsystem") == "x11":
        return _WHEEL_EVENTS + _X11_WHEEL_EVENTS
    return _WHEEL_EVENTS


class FormRow:
    """Handle einer `Form.row`: Beschriftung und Bedienelement, gemeinsam
    ein- und ausblendbar — für Zeilen, die ein Schalter im selben Tab
    sichtbar macht (Sa/So bei „Nur Werktage")."""

    def __init__(self, label, widget):
        self.label = label
        self.widget = widget

    def show(self, visible):
        # grid_remove statt grid_forget: die Grid-Optionen (Zeile, Einzug)
        # bleiben gemerkt, ein nacktes grid() stellt die Zeile wieder her.
        for w in (self.label, self.widget):
            if visible:
                w.grid()
            else:
                w.grid_remove()


class Form:
    """Ein Formular = ein Raster mit zwei Spalten, gegliedert in Abschnitte.

    Weil alle Abschnitte im selben Raster liegen, fluchten die Beschriftungen
    über das ganze Formular; die Spaltenbreite ergibt sich aus der längsten
    Beschriftung. Zeilen zählt `Form` selbst.

        form = Form(tab_frame, scroll=True)
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

    **Lebensdauer-Vertrag:** Ein `Form` lebt so lange wie sein Dialog. Die
    Mausrad-Bindung am Toplevel (`scroll=True`) und die Variablen-Traces aus
    `depends_on` werden nie wieder abgebaut — ein `Form`, das bei jedem
    Refresh neu gebaut wird, häuft beides pro Aufruf erneut an (mehrfach
    feuernde Bindings, tote Traces auf verwaisten Widgets). Formulare gehören
    einmal in den Dialog-Aufbau, nicht in eine Refresh-Methode.

    **`scroll=True`-Formulare nicht verschachteln:** zwei geschachtelte
    Scroll-Canvases binden beide dieselben Mausrad-Events an ihren jeweiligen
    Toplevel — ein Rad-Ereignis über dem inneren Formular scrollte dann
    zugleich das äußere mit.
    """

    def __init__(self, parent, *, scroll=False):
        self._row = 0
        self._sections = 0
        self._parents: dict[str, str | None] = {}
        self._vars: dict[str, tk.Variable] = {}
        self._invert: dict[str, bool] = {}
        self._indents: dict[str, bool] = {}
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
            self._canvas.configure(yscrollcommand=self._bar.set,
                                   yscrollincrement=px(WHEEL_STEP))
            self._canvas.grid(row=0, column=0, sticky="nsew")
            self.frame.grid_rowconfigure(0, weight=1)
            self.frame.grid_columnconfigure(0, weight=1)
            self.body = tk.Frame(self._canvas, bg=BG)
            self._body_window = self._canvas.create_window(
                (0, 0), window=self.body, anchor="nw")
            self.body.bind("<Configure>", self._fit_canvas, add="+")
            # Ohne das hier bliebe der Körper auf seiner reqwidth stehen,
            # sobald der Canvas breiter zugewiesen bekommt als er selbst
            # angefordert hat (z.B. im Notebook-Tab neben einer breiteren
            # Seite): die Trennlinie der Abschnitte reichte dann nicht bis
            # zum rechten Rand, und `_rewrap` läse weiterhin die alte,
            # schmale `body.winfo_width()`.
            self._canvas.bind("<Configure>", self._fit_body_width, add="+")
            # Am Toplevel statt per <Enter>/<Leave>: die feuern auch beim
            # Wechsel auf ein Kind-Widget. Jedes Form prüft selbst, ob das
            # Event in seinem Canvas liegt (mehrere Forms je Dialog).
            top = self.frame.winfo_toplevel()
            for seq in _wheel_sequences(top):
                top.bind(seq, self._on_wheel, add="+")
            # Tab-Taste auf ein Feld außerhalb des Sichtbereichs: dorthin
            # scrollen, sonst tippt man blind (<FocusIn> des Toplevels sieht
            # die Fokuswechsel aller Kinder).
            top.bind("<FocusIn>", self._on_focus, add="+")
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

    def row(self, label, widget, *, align_top=False):
        """Beschriftung in Spalte 0, `widget` (Parent `form.body`) in Spalte 1.
        `align_top` hält die Beschriftung oben (mehrzeilige Textfelder).
        Liefert ein `FormRow`, über das sich die Zeile ausblenden lässt."""
        r = self._next_row()
        lbl = tk.Label(self.body, text=label, font=FONT, bg=BG, fg=TEXT)
        lbl.grid(row=r, column=0, sticky="nw" if align_top else "w",
                 padx=(self._indent(), 8), pady=4)
        widget.grid(row=r, column=1, sticky="w", padx=(0, _EDGE), pady=4)
        self._register(lbl, widget)
        return FormRow(lbl, widget)

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
        Tabellen, Listen, Textfelder.

        `widget` muss VOLLSTÄNDIG gebaut sein, bevor es hierher übergeben
        wird: `_register`/`_guard_value_wheel` durchsucht die Kinder von
        `widget` einmalig beim Aufruf, um Comboboxen gegen das Mausrad zu
        schützen (s. `_guard_value_wheel`). Erst danach hinzugefügte
        Comboboxen sind NICHT geschützt — ein Rad-Ereignis über ihnen würde
        dann versehentlich ihren Wert ändern statt das Formular zu scrollen."""
        widget.grid(row=self._next_row(), column=0, columnspan=2, sticky="ew",
                    padx=(self._indent(), _EDGE), pady=pady)
        self._register(widget)
        return widget

    @contextmanager
    def depends_on(self, var, *, invert=False, indent=True):
        """Alles, was im `with`-Block entsteht, wird eingerückt und ist nur
        aktiv, solange `var` wahr ist (und alle Schalter darüber).
        `invert=True` dreht das um: aktiv, solange `var` AUS ist
        („Wochenende anzeigen" gegen „Nur Werktage"). `indent=False` rückt
        nicht ein — für eine Option, die neben ihrem Gegenspieler steht statt
        unter einem Hauptschalter. Die Variable hält `Form` fest — sie braucht eine lebende Referenz, sonst
        löscht der GC die Tcl-Variable (s. src/CLAUDE.md, Dialoge).

        **Besitz-Vertrag:** die Mitglieder einer `depends_on`-Gruppe gehören
        dem `Form` — `refresh_enabled` setzt ihren Zustand bei JEDER
        Schalteränderung neu (`set_enabled(widget, states[group])`). Ein
        Widget, das aus einem anderen Grund gesperrt ist (z.B. „läuft
        gerade", während eines Hintergrund-Tasks), gehört deshalb nicht in
        eine Gruppe: die nächste Schalteränderung überschreibt seinen
        Zustand kommentarlos. Ein readonly `tk.Entry` wird durch Aktivieren
        der Gruppe zu `normal` — `set_enabled` kennt keinen dritten,
        readonly-erhaltenden Zustand."""
        group = f"g{len(self._parents)}"
        self._parents[group] = self._stack[-1] if self._stack else None
        self._vars[group] = var
        self._invert[group] = invert
        self._indents[group] = indent
        self._members[group] = []
        self._stack.append(group)
        try:
            yield
        finally:
            self._stack.pop()
        var.trace_add("write", lambda *_: self.refresh_enabled())
        self.refresh_enabled()

    def refresh_enabled(self):
        """Wendet den aktuellen Zustand aller Schalter auf ihre Gruppen an
        (s. Besitz-Vertrag in `depends_on`: überschreibt jedes Mitglied
        bedingungslos, unabhängig von einer anderweitigen Sperre)."""
        values = {}
        for group, var in self._vars.items():
            try:
                values[group] = bool(var.get()) != self._invert[group]
            except tk.TclError:
                # Leeres/ungültiges Feld hinter einer Int-/Double-Variable:
                # die Gruppe gilt als aus (auch bei `invert` — im Zweifel
                # grau), statt den Aufbau abzubrechen.
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
        levels = sum(1 for group in self._stack if self._indents[group])
        return _EDGE + px(INDENT) * levels

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
            for seq in _wheel_sequences(widget):
                # add="+" statt Ersetzen: wie jede andere Bindung in diesem
                # Modul additiv, damit ein Widget, das aus irgendeinem Grund
                # bereits eine eigene Instanz-Bindung auf dieselbe Sequenz
                # trägt, diese nicht verliert.
                widget.bind(seq, self._on_blocked_wheel, add="+")
        for child in widget.winfo_children():
            self._guard_value_wheel(child)

    def _wrap_for(self, indent):
        """Umbruchbreite eines Hinweises: Formularbreite abzüglich seiner
        Einrückung. Vor der ersten Messung ein fester, mitskalierter Wert."""
        floor = px(_MIN_WRAP)
        if not self._wrap:
            return max(floor, px(_INITIAL_WRAP))
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
        height = body_height(natural, current_scale(),
                             canvas.winfo_screenheight())
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

    def _fit_body_width(self, event):
        """Streckt das `body`-Fenster-Item auf die tatsächliche Canvas-
        Breite, nie schmaler als `body` von sich aus bräuchte. Ohne das
        bliebe `body` auf seiner reqwidth stehen, sobald der Canvas mehr
        Platz zugewiesen bekommt (Notebook-Tab neben einer breiteren Seite) —
        die Abschnitts-Trennlinie erreichte den rechten Rand nicht, und
        `_rewrap` läse eine zu schmale Breite. `_fit_canvas` bleibt bei der
        reqwidth für die eigene Größenanforderung des Canvas, sonst gäbe es
        eine Rückkopplung."""
        canvas = self._canvas
        if canvas is None:
            return
        width = max(event.width, self.body.winfo_reqwidth())
        canvas.itemconfigure(self._body_window, width=width)

    def _scroll(self, event):
        if self._canvas is None or not self._scrollable:
            return
        num = event.num if event.num in (4, 5) else None
        units = scroll_units(platform.system(),
                             int(getattr(event, "delta", 0) or 0), num)
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
            # Ein Text/eine Listbox ohne Überlauf gibt das Rad ans Formular
            # ab (form_logic.wheel_route) — sonst stünde die Seite über den
            # Vorlagen-Feldern still.
            can_scroll = True
            if wheel_route(cls) == "widget":
                can_scroll = tuple(widget.yview()) != (0.0, 1.0)
        except tk.TclError:
            log.debug("Mausrad: Widget nicht mehr abfragbar", exc_info=True)
            return None
        if inside and wheel_route(cls, can_scroll) == "form":
            self._scroll(event)
        return None

    def _on_focus(self, event):
        canvas = self._canvas
        widget = event.widget
        if canvas is None or not self._scrollable or isinstance(widget, str):
            return
        try:
            if not is_descendant(str(widget), str(self.body)):
                return
            top = widget.winfo_rooty() - self.body.winfo_rooty()
            height = widget.winfo_height()
            total = self.body.winfo_reqheight()
            first, last = canvas.yview()
        except tk.TclError:
            log.debug("Fokus: Widget nicht mehr abfragbar", exc_info=True)
            return
        target = scroll_target(top, height, first, last, total)
        if target is not None:
            canvas.yview_moveto(target)

    def _on_blocked_wheel(self, event):
        self._scroll(event)
        return "break"


def empty_state(parent, text, *, bg=BG):
    """Gedämpfter Leertext für eine leere Liste — statt einer leeren Fläche
    ("Noch kein SMTP-Konto angelegt.")."""
    return tk.Label(parent, text=text, font=FONT, bg=bg, fg=TEXT_MUTED,
                    justify="center")
