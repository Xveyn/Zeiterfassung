"""Koppel-Dialog der Handy-Erfassung (#221): zeigt einen Einmalcode als QR-Code und als
Text, zählt seine Gültigkeit herunter; ein Koppeln schließt ihn und meldet es in einer
themed Meldung.

Der Code lebt nur im Hauptspeicher (`PairingSession`). Verlässt der Nutzer den Dialog —
Schließen, X, Escape —, wird die Sitzung geschlossen: ein offener Code ohne Dialog wäre
ein Einmalpasswort, das niemand sieht. Der Dialog erkennt ein Koppeln am Gerätebestand
(vorher/nachher) und warnt, wenn dabei ein vorhandenes, nicht widerrufenes Gerät ersetzt
wurde (jemand hat sich mit dessen `device_id` gekoppelt).

Im Modus „relay“ (#358) kommt der Link vom `RelayService` (Worker: Datei und Netz) und steht
nur als QR-Code da: das Box-Geheimnis darin soll nie als Text auf dem Bildschirm stehen, und der
Code allein nützt ohne es nichts. Der Dialog schließt nur die Sitzung, die er selbst geöffnet hat
(über deren Code): die Sitzung synchron, der Relay räumt im Worker auf, und die Worker laufen
ungeordnet.

Der Poll läuft per `after` am Dialog und stirbt mit ihm.
"""
import logging
import tkinter as tk
from functools import partial

from src import qr
from src.dialogs.settings_dialog.tab_rules import (
    PAIR_INTRO_LAN, PAIR_INTRO_RELAY, RELAY_PAIR_HINT, format_countdown, pair_changes,
    pair_poll_keeps_running, pair_poll_view, paired_notice, relay_open_view,
)
from src.theme import (
    BG, FONT, FONT_BOLD, STATUS_OK, STATUS_WARN, TEXT, TEXT_MUTED, center_dialog_on_parent,
    create_dialog, primary_button, px, secondary_button, themed_showinfo, themed_showwarning,
)

log = logging.getLogger(__name__)

_POLL_MS = 1000
_WRAP_PX = 380
_MODULE_PX = 6           # Kantenlänge eines Moduls bei 100 %; skaliert über px()
_FAILED = object()       # `_open_relay_pairing` scheiterte mit einer Ausnahme (None heißt: abgelehnt)


class _PairDialog:
    def __init__(self, parent, service, relay=None, runner=None, mode="lan"):
        self._service = service
        self._parent = parent
        self._relay = relay
        self._runner = runner
        self._relay_mode = mode == "relay"
        self._relay_closed = False
        self._waiting = False               # Relay: `open_pairing` läuft im Worker
        self._session_code = None           # Relay: Code der eigenen Sitzung, nur die schließt der Dialog
        self._alive = True
        self._poll_id = None
        self._before = service.list_devices()
        self._failures_before = service.pair_failures
        self._dialog = dialog = create_dialog(
            parent, "Handy über Relay koppeln" if self._relay_mode else "Handy koppeln")

        tk.Label(
            dialog, text=PAIR_INTRO_RELAY if self._relay_mode else PAIR_INTRO_LAN,
            font=FONT, bg=BG, fg=TEXT, justify="left", anchor="w",
            wraplength=px(_WRAP_PX)).pack(padx=16, pady=(14, 8), anchor="w")

        # Weiße Fläche samt Ruhezone, unabhängig vom Dark-Theme (sonst scannt es nicht).
        self._canvas = tk.Canvas(dialog, bg="#ffffff", highlightthickness=0)
        self._canvas.pack(pady=4)

        self._address = tk.Label(dialog, text="", font=FONT, bg=BG, fg=TEXT_MUTED)
        self._code_title = tk.Label(dialog, text="", font=FONT, bg=BG, fg=TEXT_MUTED)
        self._code = tk.Label(dialog, text="", font=FONT_BOLD, bg=BG, fg=TEXT)
        if not self._relay_mode:            # Relay: nie Adresse oder Code als Text
            self._address.pack(pady=(6, 0))
            self._code_title.pack()
            self._code.pack()
        self._hint = tk.Label(
            dialog, text="", font=FONT, bg=BG, fg=TEXT_MUTED, justify="center",
            wraplength=px(_WRAP_PX))
        self._hint.pack(padx=16)
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

    def _blank_canvas(self):
        self._canvas.delete("all")
        self._canvas.config(width=1, height=1)      # `_draw` stellt die Größe wieder her

    def _clear_code(self):
        self._code_title.config(text="")
        self._code.config(text="")
        self._hint.config(text="")

    def _new_code(self):
        if self._relay_mode:
            self._new_relay_code()
            return
        status = self._service.status
        self._canvas.delete("all")
        self._result.config(text="")
        if status.state != "running":
            self._service.pairing.close()
            self._address.config(text="")
            self._clear_code()
            self._countdown.config(text="")
            self._result.config(
                text="Die Handy-Erfassung läuft gerade nicht. Im Reiter „Mobil“ "
                     "einschalten und speichern, dann hier erneut öffnen.",
                fg=STATUS_WARN)
            self._canvas.config(width=1, height=1)
            return
        self._before = self._service.list_devices()
        self._failures_before = self._service.pair_failures
        code = self._service.pairing.open()
        link = self._service.pair_link(code)
        self._address.config(text=f"Adresse: {status.address}:{status.port}")
        self._code_title.config(text="Kopplungscode (zum Abtippen):")
        self._code.config(text=code)
        self._hint.config(text=("Der Code gilt einmal, fünf Minuten lang, und verschlüsselt die "
                                "Verbindung — nur dem eigenen Handy zeigen."))
        # Sofort, nicht erst nach dem ersten Poll: sonst ist die Zeile eine Sekunde leer.
        self._countdown.config(
            text=f"Gültig noch {format_countdown(self._service.pairing.seconds_left())}")
        self._draw(link)
        self._schedule_poll()

    def _new_relay_code(self):
        if self._waiting:
            return
        self._blank_canvas()
        self._clear_code()
        self._result.config(text="")
        self._countdown.config(text="Öffnet …")
        self._waiting = True
        self._runner.run(self._open_relay_pairing, self._relay_opened)

    def _open_relay_pairing(self):
        """Worker: `RelayService.open_pairing`. Der Runner ruft `on_done` bei einer Ausnahme nie, der
        Dialog bliebe auf „Öffnet …“: sie wird zum Wert `_FAILED` (nur der Typ ins Log, nie der Link)."""
        try:
            return self._relay.open_pairing()
        except Exception as exc:
            log.warning("Relay-Kopplung: Öffnen scheiterte (%s)", type(exc).__name__)
            return _FAILED

    def _relay_opened(self, result):
        """Ergebnis von `_open_relay_pairing` (UI-Thread): `RelayPairing`, `None` (abgelehnt, ohne
        Grund) oder `_FAILED`. Was geschlossen wird, entscheidet `relay_open_view`."""
        self._waiting = False
        failed = result is _FAILED
        pairing = None if failed else result
        view = relay_open_view(alive=self._alive, code=pairing.code if pairing is not None else None,
                               failed=failed, own_code=self._session_code)
        for code in view.close_codes:
            self._close_relay_session(code)
        if not self._alive:
            return
        try:
            if not view.show:
                self._session_code = None
                self._cancel_poll()         # die alte Sitzung ist zu: kein Countdown dazu
                self._countdown.config(text="")
                self._result.config(text=view.message, fg=STATUS_WARN)
                return
            self._session_code = pairing.code
            self._before = self._service.list_devices()
            self._failures_before = self._service.pair_failures
            self._hint.config(text=RELAY_PAIR_HINT)
            self._countdown.config(
                text=f"Gültig noch {format_countdown(self._service.pairing.seconds_left())}")
            self._draw(pairing.link)
            self._schedule_poll()
        except tk.TclError:
            self._alive = False

    def _close_relay_session(self, code):
        """Schließt die Relay-Sitzung mit diesem Code im Worker (Datei, Netz)."""
        self._runner.run(partial(self._relay.close_pairing, code))

    def _release_relay(self):
        """Räumt die eigene Relay-Seite beim Verlassen ab: einmal, im Worker. Ein Öffnen, das noch
        läuft, räumt `_relay_opened` ab, sobald es ankommt."""
        if self._relay_mode and not self._relay_closed:
            self._relay_closed = True
            if self._session_code is not None:
                self._close_relay_session(self._session_code)

    def _close_own_session(self):
        """Schließt nur die Sitzung dieses Dialogs. Im Relay-Modus über den eigenen Code: ein
        spät laufendes Öffnen darf keine fremde treffen."""
        if self._relay_mode:
            self._service.pairing.close_if(self._session_code)
        else:
            self._service.pairing.close()

    def _draw(self, link):
        scale = px(_MODULE_PX)
        try:
            matrix = qr.qr_matrix(link) if link else None
        except qr.QrTooLong:
            log.warning("Koppel-Link zu lang für einen QR-Code", exc_info=True)
            matrix = None
        except ImportError:
            # segno fehlt (z. B. übersieht PyInstaller den lazy Import): ohne diesen Fang bliebe
            # der Dialog unsichtbar und der Code bis zum Ablauf offen. Adresse und Code stehen
            # als Text da.
            log.warning("segno nicht verfügbar, Koppel-Dialog ohne QR-Code", exc_info=True)
            matrix = None
        if matrix is None:
            self._canvas.config(width=1, height=1)
            text = ("Der QR-Code konnte nicht erzeugt werden. Das Koppeln über den Relay "
                    "braucht ihn." if self._relay_mode else
                    "Der QR-Code konnte nicht erzeugt werden — bitte Adresse und Code von "
                    "Hand eintippen.")
            self._result.config(text=text, fg=STATUS_WARN)
            return
        size = qr.canvas_size(len(matrix), scale)
        self._canvas.config(width=size, height=size)
        for x0, y0, x1, y1 in qr.dark_rects(matrix, scale):
            self._canvas.create_rectangle(x0, y0, x1, y1, fill="#000000", outline="")

    def _schedule_poll(self):
        if self._poll_id is None:
            self._poll_id = self._dialog.after(_POLL_MS, self._poll)

    def _cancel_poll(self):
        if self._poll_id is not None:
            try:
                self._dialog.after_cancel(self._poll_id)
            except tk.TclError:
                pass                        # Fenster schon weg: nichts mehr zu stornieren
            self._poll_id = None

    def _poll(self):
        self._poll_id = None
        if not self._alive:
            return
        if self._waiting:                   # Relay öffnet gerade: noch nichts zu prüfen
            self._schedule_poll()
            return
        try:
            changes = pair_changes(self._before, self._service.list_devices())
            state, text = pair_poll_view(
                active=self._service.pairing.is_active(),
                seconds_left=self._service.pairing.seconds_left(),
                paired=not changes.empty,
                failed=self._service.pair_failures > self._failures_before)
            if state == "paired":
                self._show_paired(changes)
            elif state == "failed":
                self._show_failed(text)
            elif state == "counting":
                self._countdown.config(text=text)
            else:
                self._show_expired(text)
            if self._alive and pair_poll_keeps_running(state):
                self._schedule_poll()
        except tk.TclError:
            self._alive = False             # Fenster zwischenzeitlich zu

    def _show_expired(self, text):
        """Ein abgelaufener Code zeigt weder QR-Code noch Code: er wäre nutzlos und
        sähe gültig aus. Die weiße Fläche schrumpft mit, sonst bliebe ein leeres Quadrat."""
        self._blank_canvas()
        self._clear_code()
        self._countdown.config(text=text)

    def _show_failed(self, text):
        """Der Code wurde eingelöst, das Gerät aber nicht gespeichert: Code und QR-Code sind
        verbraucht, der Dialog bleibt für „Neuer Code“ offen und sagt, was passiert ist."""
        self._blank_canvas()
        self._clear_code()
        self._countdown.config(text="")
        self._result.config(text=text, fg=STATUS_WARN)

    def _show_paired(self, changes):
        """Das Koppeln ist durch: der Dialog mit dem QR-Code geht zu, eine themed
        Meldung löst ihn ab (bei ersetztem Gerät als Warnung)."""
        notice = paired_notice(changes)
        parent = self._parent
        self._close()
        show = themed_showwarning if notice.warn else themed_showinfo
        show(parent, notice.title, notice.text)

    # --- Schließen -------------------------------------------------------------------

    def _close(self):
        self._close_own_session()
        self._release_relay()
        if self._dialog.winfo_exists():
            self._dialog.destroy()

    def _on_destroy(self, event):
        if event.widget is not self._dialog:
            return
        self._alive = False
        self._close_own_session()
        self._release_relay()
        self._cancel_poll()


def open_pair_dialog(parent, service, *, relay=None, runner=None, mode="lan"):
    """Öffnet den Koppel-Dialog (modal). Schließt die Kopplungssitzung beim Verlassen.
    `mode="relay"` verlangt `relay` (`RelayService`) und `runner` (`BackgroundTaskRunner`)."""
    if mode == "relay" and (relay is None or runner is None):
        raise ValueError("Der Relay-Modus braucht relay und runner")
    _PairDialog(parent, service, relay, runner, mode)
