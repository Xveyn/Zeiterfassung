import tkinter as tk

from src.theme import FONT_FAMILY

# Window-Manager-Zustände, in denen das Hauptfenster nicht sichtbar ist:
# 'iconic' = minimiert (auch via root.iconify() / Win+M), 'withdrawn' = per
# root.withdraw() weggeklappt (Minimize-to-Tray). In beiden Fällen muss ein
# offenes Tooltip mitverschwinden — sonst schwebt das overrideredirect-/topmost-
# Toplevel weiter über allem (der gemeldete Bug).
_HIDDEN_ROOT_STATES = ("iconic", "withdrawn")


def _should_hide_tip(root_state, widget_rects, pointer):
    """Reine Entscheidungslogik: soll das Tooltip geschlossen werden?

    root_state: Rückgabe von Tk `root.state()`
        ('normal' / 'iconic' / 'withdrawn' / 'zoomed').
    widget_rects: Liste (x, y, w, h) der noch lebenden getrackten Widgets in
        Screen-Koordinaten. Zerstörte Widgets sind hier bereits ausgelassen.
    pointer: (px, py) Mauszeiger in Screen-Koordinaten.

    Schließen, wenn das Hauptfenster minimiert/weggeklappt ist ODER der Zeiger
    über keinem der (noch existierenden) Widgets mehr steht. Letzteres deckt
    sowohl das normale Verlassen als auch den Re-Render ab (leere Liste ->
    schließen). Bewusst tk-frei gehalten, damit ohne Display testbar.
    """
    if root_state in _HIDDEN_ROOT_STATES:
        return True
    px, py = pointer
    for (x, y, w, h) in widget_rects:
        if x <= px < x + w and y <= py < y + h:
            return False
    return True


class _Tooltip:
    """Hover-Tooltip an ein oder mehrere Tk-Widgets binden.

    Mehrere Widgets teilen eine einzige Tooltip-Instanz — Hovering über
    irgendeines von ihnen zeigt genau ein Popup. Wechsel zwischen den
    Widgets (z.B. Frame → Child-Label) blendet den Tooltip nicht weg, weil
    `_should_hide_tip` prüft, ob der Pointer noch in einem der Widgets ist.

    Das Tooltip-Toplevel ist `overrideredirect` + `-topmost` und wird daher
    NICHT vom Window-Manager mit dem Hauptfenster minimiert. Es genügt deshalb
    nicht, nur auf `<Leave>` zu schließen: Minimieren ohne Mausbewegung (Win+M,
    Autostart `--minimized`, Tray-Withdraw) oder das Zerstören der Zelle beim
    Kalender-Re-Render erzeugen kein `<Leave>`. Zusätzlich greifen daher ein
    `<Destroy>`-Binding (sofortiges Aufräumen bei Re-Render) und ein Watchdog-
    Poll, der Fensterzustand und Pointer erneut prüft, solange das Tooltip offen
    ist.
    """

    _CLOSE_DELAY_MS = 80
    _WATCHDOG_MS = 200

    def __init__(self, widgets, text: str):
        self.widgets = tuple(widgets)
        self.text = text
        self.tip: tk.Toplevel | None = None
        self._close_after_id: str | None = None
        self._watchdog_id: str | None = None
        for w in self.widgets:
            w.bind("<Enter>", self._show, add="+")
            w.bind("<Leave>", self._on_leave, add="+")
            w.bind("<Destroy>", self._on_destroy, add="+")

    def _primary(self):
        return self.widgets[0]

    def _show(self, _event):
        if self._close_after_id is not None:
            self._cancel(self._close_after_id)
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
        # Auffangnetz für alle Fälle, in denen kein <Leave> kommt (minimiert,
        # Re-Render, Fokuswechsel): solange das Tooltip offen ist, periodisch
        # selbst prüfen, ob es noch sichtbar sein darf.
        self._schedule_watchdog()

    def _on_leave(self, _event):
        if self._close_after_id is not None:
            self._cancel(self._close_after_id)
        self._close_after_id = self._primary().after(
            self._CLOSE_DELAY_MS, self._maybe_close
        )

    def _on_destroy(self, event):
        # Wird eines der getrackten Widgets selbst zerstört (Kalender-Re-Render),
        # das offene Tooltip sofort schließen, statt es verwaisen zu lassen.
        if event.widget in self.widgets:
            self._close()

    def _maybe_close(self):
        self._close_after_id = None
        if self.tip is None:
            return
        if self._evaluate_should_hide():
            self._close()

    def _watchdog(self):
        self._watchdog_id = None
        if self.tip is None:
            return
        if self._evaluate_should_hide():
            self._close()
        else:
            self._schedule_watchdog()

    def _evaluate_should_hide(self):
        """Sammelt Fensterzustand, Widget-Rechtecke und Pointer defensiv aus Tk
        und delegiert an die reine `_should_hide_tip`-Logik. Ist Tk-State nicht
        mehr lesbar (Widget weg), wird geschlossen."""
        try:
            root_state = self._primary().winfo_toplevel().state()
            pointer = self._primary().winfo_pointerxy()
        except tk.TclError:
            return True
        rects = []
        for w in self.widgets:
            try:
                rects.append(
                    (w.winfo_rootx(), w.winfo_rooty(),
                     w.winfo_width(), w.winfo_height())
                )
            except tk.TclError:
                continue
        return _should_hide_tip(root_state, rects, pointer)

    def _schedule_watchdog(self):
        try:
            self._watchdog_id = self._primary().after(
                self._WATCHDOG_MS, self._watchdog
            )
        except tk.TclError:
            self._watchdog_id = None

    def _cancel(self, after_id):
        try:
            self._primary().after_cancel(after_id)
        except tk.TclError:
            pass

    def _close(self):
        if self._close_after_id is not None:
            self._cancel(self._close_after_id)
            self._close_after_id = None
        if self._watchdog_id is not None:
            self._cancel(self._watchdog_id)
            self._watchdog_id = None
        if self.tip is not None:
            try:
                self.tip.destroy()
            except tk.TclError:
                pass
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
