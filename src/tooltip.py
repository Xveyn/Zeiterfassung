import tkinter as tk

from src.theme import FONT_FAMILY


class _Tooltip:
    """Hover-Tooltip an ein oder mehrere Tk-Widgets binden.

    Mehrere Widgets teilen eine einzige Tooltip-Instanz — Hovering über
    irgendeines von ihnen zeigt genau ein Popup. Wechsel zwischen den
    Widgets (z.B. Frame → Child-Label) blendet den Tooltip nicht weg, weil
    `_maybe_close` prüft, ob der Pointer noch in einem der Widgets ist.
    """

    _CLOSE_DELAY_MS = 80

    def __init__(self, widgets, text: str):
        self.widgets = tuple(widgets)
        self.text = text
        self.tip: tk.Toplevel | None = None
        self._close_after_id: str | None = None
        for w in self.widgets:
            w.bind("<Enter>", self._show, add="+")
            w.bind("<Leave>", self._on_leave, add="+")

    def _primary(self):
        return self.widgets[0]

    def _show(self, _event):
        if self._close_after_id is not None:
            self._primary().after_cancel(self._close_after_id)
            self._close_after_id = None
        if self.tip is not None or not self.text:
            return
        # Positioniere relativ zum ersten (typisch äußersten) Widget — stabile
        # Tooltip-Position auch wenn der Mauszeiger zwischen Children wandert.
        anchor = self._primary()
        x = anchor.winfo_rootx() + 20
        y = anchor.winfo_rooty() + anchor.winfo_height() + 4
        self.tip = tk.Toplevel(anchor)
        self.tip.wm_overrideredirect(True)
        self.tip.wm_geometry(f"+{x}+{y}")
        # Falls das Hauptfenster topmost ist (Setting 'Immer im Vordergrund'),
        # muss das Tooltip-Toplevel ebenfalls topmost sein — sonst landet es
        # hinter dem Mainwindow und der User sieht nichts.
        try:
            self.tip.attributes("-topmost", True)
        except tk.TclError:
            pass
        tk.Label(
            self.tip,
            text=self.text,
            background="#1e293b",
            foreground="#e0e0e0",
            relief="solid",
            borderwidth=1,
            padx=8,
            pady=4,
            font=(FONT_FAMILY, 9),
        ).pack()

    def _on_leave(self, _event):
        if self._close_after_id is not None:
            self._primary().after_cancel(self._close_after_id)
        self._close_after_id = self._primary().after(
            self._CLOSE_DELAY_MS, self._maybe_close
        )

    def _maybe_close(self):
        self._close_after_id = None
        if self.tip is None:
            return
        # Pointer immer noch über IRGENDEINEM der getrackten Widgets? Dann offen
        # lassen. Wichtig für (Frame, Child)-Binding: Enter auf Child schickt
        # Leave auf Frame und umgekehrt — würden wir einzeln tracken, ploppte
        # der Tooltip bei jedem Wechsel zu.
        for w in self.widgets:
            try:
                x, y = w.winfo_pointerxy()
                wx = w.winfo_rootx()
                wy = w.winfo_rooty()
                ww = w.winfo_width()
                wh = w.winfo_height()
            except tk.TclError:
                continue
            if wx <= x < wx + ww and wy <= y < wy + wh:
                return
        self.tip.destroy()
        self.tip = None


def attach_tooltip(widget_or_widgets, text: str) -> None:
    """Bindet ein Tooltip an ein Widget oder eine Gruppe von Widgets.

    Bei einer Gruppe (Tuple/Liste) gibt es genau einen geteilten Tooltip —
    nützlich für Container + Child-Labels, die als ein logisches Element
    fungieren. Mehrfachaufruf mit demselben Widget erzeugt allerdings mehrere
    unabhängige Tooltips; Aufrufer ist dafür verantwortlich, das zu vermeiden.
    """
    if isinstance(widget_or_widgets, tk.Misc):
        widgets = (widget_or_widgets,)
    else:
        widgets = tuple(widget_or_widgets)
    _Tooltip(widgets, text)
