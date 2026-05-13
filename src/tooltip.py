import tkinter as tk

from src.theme import FONT_FAMILY


class _Tooltip:
    """Hover-Tooltip an ein beliebiges Tk-Widget binden.

    Tk feuert ``<Leave>`` auch dann, wenn der Pointer in ein Child-Widget
    wandert. Damit der Tooltip in dem Fall nicht aufflackert, wird das
    Schließen kurz verzögert und nur ausgeführt, wenn der Pointer
    tatsächlich außerhalb des Bind-Widgets steht.
    """

    _CLOSE_DELAY_MS = 80

    def __init__(self, widget: tk.Widget, text: str):
        self.widget = widget
        self.text = text
        self.tip: tk.Toplevel | None = None
        self._close_after_id: str | None = None
        widget.bind("<Enter>", self._show, add="+")
        widget.bind("<Leave>", self._on_leave, add="+")

    def _show(self, _event):
        if self._close_after_id is not None:
            self.widget.after_cancel(self._close_after_id)
            self._close_after_id = None
        if self.tip is not None or not self.text:
            return
        x = self.widget.winfo_rootx() + 20
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 4
        self.tip = tk.Toplevel(self.widget)
        self.tip.wm_overrideredirect(True)
        self.tip.wm_geometry(f"+{x}+{y}")
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
            self.widget.after_cancel(self._close_after_id)
        self._close_after_id = self.widget.after(
            self._CLOSE_DELAY_MS, self._maybe_close
        )

    def _maybe_close(self):
        self._close_after_id = None
        if self.tip is None:
            return
        # Pointer immer noch über dem Widget (z.B. in einem Child)? Dann offen lassen.
        x, y = self.widget.winfo_pointerxy()
        wx = self.widget.winfo_rootx()
        wy = self.widget.winfo_rooty()
        ww = self.widget.winfo_width()
        wh = self.widget.winfo_height()
        if wx <= x < wx + ww and wy <= y < wy + wh:
            return
        self.tip.destroy()
        self.tip = None


def attach_tooltip(widget: tk.Widget, text: str) -> None:
    """Bindet ein Tooltip an widget. Mehrfachaufruf erzeugt mehrere Tooltips — Aufrufer ist verantwortlich, das nur einmal pro Widget zu tun."""
    _Tooltip(widget, text)
