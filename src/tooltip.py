import tkinter as tk
from typing import Callable, Optional, Union

from src.theme import FONT_FAMILY

# Ein Tooltip-Text ist entweder fix oder wird beim Anzeigen berechnet.
# Dynamisch braucht es z.B. die Header-Pfeile: dieselben Buttons blättern
# im Monatsmodus Monate und im Wochenmodus Wochen.
TooltipText = Union[str, Callable[[], str]]

# Window-Manager-Zustände, in denen das Hauptfenster nicht sichtbar ist:
# 'iconic' = minimiert (auch via root.iconify() / Win+M), 'withdrawn' = per
# root.withdraw() weggeklappt (Minimize-to-Tray). In beiden Fällen muss ein
# offenes Tooltip mitverschwinden — sonst schwebt das overrideredirect-/topmost-
# Toplevel weiter über allem (der gemeldete Bug).
_HIDDEN_ROOT_STATES = ("iconic", "withdrawn")


def _should_hide_tip(root_state, widget_rects, pointer, grab_active=False):
    """Reine Entscheidungslogik: soll das Tooltip geschlossen werden?

    root_state: Rückgabe von Tk `root.state()`
        ('normal' / 'iconic' / 'withdrawn' / 'zoomed').
    widget_rects: Liste (x, y, w, h) der noch lebenden getrackten Widgets in
        Screen-Koordinaten. Zerstörte Widgets sind hier bereits ausgelassen.
    pointer: (px, py) Mauszeiger in Screen-Koordinaten.
    grab_active: True, wenn irgendein anderes Fenster der App gerade den
        Tk-Grab hält (z.B. ein modaler Dialog, siehe `grab_current()`).

    Schließen, wenn das Hauptfenster minimiert/weggeklappt ist, ein anderes
    Fenster den Grab hält, ODER der Zeiger über keinem der (noch
    existierenden) Widgets mehr steht. Der Grab-Fall greift, weil ein
    Rechtsklick auf die Zelle direkt einen modalen Dialog öffnen kann, ohne
    dass der Zeiger die Zelle verlässt (kein <Leave>) — grab_set() blockt nur
    künftige Events, blendet das bereits sichtbare, -topmost Tooltip aber
    nicht aus. Bewusst tk-frei gehalten, damit ohne Display testbar.
    """
    if root_state in _HIDDEN_ROOT_STATES:
        return True
    if grab_active:
        return True
    px, py = pointer
    for (x, y, w, h) in widget_rects:
        if x <= px < x + w and y <= py < y + h:
            return False
    return True


def _resolve_text(text: Optional[TooltipText]) -> str:
    """Löst einen Tooltip-Text zum Anzeige-Zeitpunkt auf.

    Ein String kommt unverändert zurück; ein Callable wird jetzt gerufen,
    damit der Text den aktuellen Zustand widerspiegelt statt den beim
    Anhängen. `None`/leer ergibt "" — und leerer Text unterdrückt in
    `_show` die Anzeige. Bewusst tk-frei gehalten, damit ohne Display
    testbar.
    """
    if callable(text):
        text = text()
    return "" if text is None else str(text)


# Genau ein Tooltip darf gleichzeitig sichtbar sein (#66). Die Instanzen kennen
# einander nicht, daher hält das Modul eine globale Referenz auf das aktuell
# offene Tooltip: beim Anzeigen eines neuen wird das vorherige sofort geschlossen
# (sonst hängt es bis zu seinem Close-Delay/Watchdog noch sichtbar herum, wenn
# der Zeiger schnell über mehrere Elemente fährt).
_active_tip = None


def _set_active_tip(tip):
    """Macht `tip` zum einzigen sichtbaren Tooltip: schließt ein evtl. anderes
    aktives und merkt sich `tip`."""
    global _active_tip
    prev = _active_tip
    if prev is not None and prev is not tip:
        prev._close()  # ruft seinerseits _clear_active_tip(prev)
    _active_tip = tip


def _clear_active_tip(tip):
    """Entfernt `tip` aus der Registry — aber nur, wenn es das aktive ist
    (ein bereits abgelöstes Tooltip darf das neue nicht überschreiben)."""
    global _active_tip
    if _active_tip is tip:
        _active_tip = None


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

    def __init__(self, widgets, text: TooltipText):
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
        if self.tip is not None:
            return
        text = _resolve_text(self.text)
        if not text:
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
            text=text,
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
        # Nur eines gleichzeitig (#66): ein evtl. noch offenes anderes schließen.
        _set_active_tip(self)

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
            primary = self._primary()
            root_state = primary.winfo_toplevel().state()
            pointer = primary.winfo_pointerxy()
            grab_active = primary.grab_current() is not None
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
        return _should_hide_tip(root_state, rects, pointer, grab_active)

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
        _clear_active_tip(self)


def attach_tooltip(widget_or_widgets, text: TooltipText) -> None:
    """Bindet ein Tooltip an ein Widget oder eine Gruppe von Widgets.

    Bei einer Gruppe (Tuple/Liste) gibt es genau einen geteilten Tooltip —
    nützlich für Container + Child-Labels, die als ein logisches Element
    fungieren. Mehrfachaufruf mit demselben Widget erzeugt allerdings mehrere
    unabhängige Tooltips; Aufrufer ist dafür verantwortlich, das zu vermeiden.

    `text` darf statt eines Strings ein Callable sein: es wird bei jedem
    Anzeigen neu gerufen (s. `_resolve_text`). Das ist der Weg für Texte,
    die vom aktuellen Zustand abhängen — etwa die Header-Pfeile, deren
    Beschriftung zwischen Monats- und Wochenansicht wechselt.
    """
    if isinstance(widget_or_widgets, tk.Misc):
        widgets = (widget_or_widgets,)
    else:
        widgets = tuple(widget_or_widgets)
    _Tooltip(widgets, text)
