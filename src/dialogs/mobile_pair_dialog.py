"""Koppel-Dialog der Handy-Erfassung (#221): zeigt einen Einmalcode als QR-Code und als
Text, zählt seine Gültigkeit herunter und meldet das Koppeln.

Der Code lebt nur im Hauptspeicher (`PairingSession`). Verlässt der Nutzer den Dialog —
Schließen, X, Escape —, wird die Sitzung geschlossen: ein offener Code ohne Dialog wäre
ein Einmalpasswort, das niemand sieht. Der Dialog erkennt ein Koppeln am Gerätebestand
(vorher/nachher) und warnt, wenn dabei ein vorhandenes, nicht widerrufenes Gerät ersetzt
wurde (jemand hat sich mit dessen `device_id` gekoppelt).

Der Poll läuft per `after` am Dialog und stirbt mit ihm.
"""
import logging
import tkinter as tk

from src import qr
from src.dialogs.settings_dialog.tab_rules import format_countdown, pair_changes
from src.theme import (
    BG, FONT, FONT_BOLD, STATUS_OK, STATUS_WARN, TEXT, TEXT_MUTED, center_dialog_on_parent,
    create_dialog, primary_button, px, secondary_button,
)

log = logging.getLogger(__name__)

_POLL_MS = 1000
_WRAP_PX = 380
_MODULE_PX = 6           # Kantenlänge eines Moduls bei 100 %; skaliert über px()


class _PairDialog:
    def __init__(self, parent, service):
        self._service = service
        self._alive = True
        self._poll_id = None
        self._before = service.list_devices()
        self._dialog = dialog = create_dialog(parent, "Handy koppeln")

        tk.Label(
            dialog, text=("Kamera-App des Handys öffnen und den QR-Code scannen — oder "
                          "die Adresse im Browser öffnen und den Code eintippen."),
            font=FONT, bg=BG, fg=TEXT, justify="left", anchor="w",
            wraplength=px(_WRAP_PX)).pack(padx=16, pady=(14, 8), anchor="w")

        # Weiße Fläche samt Ruhezone, unabhängig vom Dark-Theme (sonst scannt es nicht).
        self._canvas = tk.Canvas(dialog, bg="#ffffff", highlightthickness=0)
        self._canvas.pack(pady=4)

        self._address = tk.Label(dialog, text="", font=FONT, bg=BG, fg=TEXT_MUTED)
        self._address.pack(pady=(6, 0))
        self._code = tk.Label(dialog, text="", font=FONT_BOLD, bg=BG, fg=TEXT)
        self._code.pack()
        self._countdown = tk.Label(dialog, text="", font=FONT, bg=BG, fg=TEXT_MUTED)
        self._countdown.pack()
        self._result = tk.Label(
            dialog, text="", font=FONT, bg=BG, fg=STATUS_OK, justify="left",
            wraplength=px(_WRAP_PX))
        self._result.pack(padx=16, pady=(6, 0), anchor="w")

        buttons = tk.Frame(dialog, bg=BG)
        buttons.pack(pady=12)
        primary_button(buttons, "Neuer Code", self._new_code).pack(side=tk.LEFT, padx=5)
        secondary_button(buttons, "Schließen", self._close).pack(side=tk.LEFT, padx=5)

        dialog.protocol("WM_DELETE_WINDOW", self._close)
        dialog.bind("<Escape>", lambda _e: self._close())
        dialog.bind("<Destroy>", self._on_destroy, add="+")
        self._new_code()
        center_dialog_on_parent(dialog, parent)

    # --- Code und Anzeige ---------------------------------------------------------

    def _new_code(self):
        status = self._service.status
        self._canvas.delete("all")
        self._result.config(text="")
        if status.state != "running":
            self._service.pairing.close()
            self._address.config(text="")
            self._code.config(text="")
            self._countdown.config(text="")
            self._result.config(
                text="Die Handy-Erfassung läuft gerade nicht. Im Reiter „Mobil“ "
                     "einschalten und speichern, dann hier erneut öffnen.",
                fg=STATUS_WARN)
            self._canvas.config(width=1, height=1)
            return
        self._before = self._service.list_devices()
        code = self._service.pairing.open()
        link = self._service.pair_link(code)
        self._address.config(text=f"Adresse: {status.address}:{status.port}")
        self._code.config(text=f"Code: {code}")
        self._draw(link)
        self._schedule_poll()

    def _draw(self, link):
        scale = px(_MODULE_PX)
        try:
            matrix = qr.qr_matrix(link) if link else None
        except qr.QrTooLong:
            log.warning("Koppel-Link zu lang für einen QR-Code", exc_info=True)
            matrix = None
        if matrix is None:
            self._canvas.config(width=1, height=1)
            self._result.config(text="Der QR-Code konnte nicht erzeugt werden — bitte "
                                     "Adresse und Code von Hand eintippen.", fg=STATUS_WARN)
            return
        size = qr.canvas_size(len(matrix), scale)
        self._canvas.config(width=size, height=size)
        for x0, y0, x1, y1 in qr.dark_rects(matrix, scale):
            self._canvas.create_rectangle(x0, y0, x1, y1, fill="#000000", outline="")

    def _schedule_poll(self):
        if self._poll_id is None:
            self._poll_id = self._dialog.after(_POLL_MS, self._poll)

    def _poll(self):
        self._poll_id = None
        if not self._alive:
            return
        try:
            left = self._service.pairing.seconds_left()
            changes = pair_changes(self._before, self._service.list_devices())
            if not changes.empty:
                self._show_paired(changes)
            elif left > 0:
                self._countdown.config(text=f"Gültig noch {format_countdown(left)}")
            elif not self._service.pairing.is_active():
                self._countdown.config(text="Der Code ist abgelaufen — „Neuer Code“.")
            if self._alive and (left > 0 or not changes.empty):
                self._schedule_poll()
        except tk.TclError:
            self._alive = False             # Fenster zwischenzeitlich zu

    def _show_paired(self, changes):
        names = ", ".join(d["name"] for d in changes.added + changes.replaced)
        text = f"Gekoppelt: {names}. Für ein weiteres Handy „Neuer Code“."
        color = STATUS_OK
        if changes.replaced:
            old = ", ".join(d["name"] for d in changes.replaced)
            text += (f"\nAchtung: dabei wurde das vorhandene Gerät „{old}“ ersetzt "
                     "(jemand hat sich mit dessen Kennung gekoppelt). Gehörte der Code "
                     "nicht zu Ihrem eigenen Handy, widerrufen Sie das Gerät im Reiter.")
            color = STATUS_WARN
        self._result.config(text=text, fg=color)
        self._canvas.delete("all")
        self._code.config(text="")
        self._countdown.config(text="")
        self._before = self._service.list_devices()

    # --- Schließen -------------------------------------------------------------------

    def _close(self):
        self._service.pairing.close()
        if self._dialog.winfo_exists():
            self._dialog.destroy()

    def _on_destroy(self, event):
        if event.widget is not self._dialog:
            return
        self._alive = False
        self._service.pairing.close()
        if self._poll_id is not None:
            try:
                self._dialog.after_cancel(self._poll_id)
            except tk.TclError:
                pass                        # Fenster schon weg: nichts mehr zu stornieren


def open_pair_dialog(parent, service):
    """Öffnet den Koppel-Dialog (modal). Schließt die Kopplungssitzung beim Verlassen."""
    _PairDialog(parent, service)
