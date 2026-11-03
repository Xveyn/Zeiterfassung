"""Verbindungsschicht zum Relay-Abgleich (#358, PR 3b), Tk-frei.

Hält je Box (= je Box-Geheimnis) eine WebSocket zum Relay, liest deren Slot und reicht jede
Anfrage des Handys an **einen** Handler weiter; die Antwort legt der Handler über `put` ab.
Programmiert nur gegen `ws_client.Socket`/`Connect`, nie gegen die Bibliothek; kennt weder App
noch Tk noch Settings.

Thread-Regeln (wer ruft was aus welchem Thread)
-----------------------------------------------
- **Leser-Thread je Box** (`relay-box-<marke>`, Daemon): verbindet (`connect(secret, have)`, `have`
  aus dem Cursor), liest mit `recv(timeout=heartbeat_s)`, sendet bei Stille den Text `ping` und
  wartet dann höchstens `pong_wait_s` auf irgendeine Nachricht (sonst: Verbindung tot, neu
  verbinden). Ein `slot` landet im Slot seiner Box (je Box höchstens ein wartendes `(ver, payload)`,
  „neuester gewinnt“: ein noch nicht begonnenes älteres fällt weg). `ok` und Text werden ignoriert.
  Der Leser ruft **nie** den Handler, `on_idle` oder den Cursor zum Vorrücken — ein Abgleich kann
  Sekunden dauern, der Heartbeat darf nicht warten.
- **Ein Arbeits-Thread** (`relay-worker`, Daemon, gestartet im Konstruktor) für alle Boxen: holt
  die wartenden Slots reihum ab, rückt **vorher** den Cursor vor (`cursor.advance`, unter der Sperre
  zusammen mit dem Abholen, damit ein gleichzeitiges `wiped` nie von einem alten `ver`
  überschrieben wird) und ruft dann `handler(secret, payload)` — immer nacheinander, nie
  gleichzeitig. Alle `idle_tick_s` ruft er außerdem `on_idle`. Ein werfender Handler oder
  `on_idle` beendet ihn nicht (nur der Ausnahme-Typ geht ins Log).
- **`put`** darf aus jedem Thread kommen (gedacht: der Handler im Arbeits-Thread). Gesendet wird
  unter dem **Sendesperr-Lock der Box**, den auch der Heartbeat des Lesers nimmt — ein Socket hat so
  nie zwei gleichzeitige Schreiber. `put` wirft nie; hängt das Senden an einem toten Netz, bricht
  der Sende-Wächter des Sockets (`ws_client.SEND_TIMEOUT_S`) die Verbindung ab, `put` liefert
  `False`, und der Leser verbindet über den Backoff neu.
- **`set_boxes`, `states`, `shutdown`** dürfen aus jedem Thread kommen (gedacht: der Dienst im
  Worker bzw. beim Beenden). `set_boxes` blockiert nicht: es startet fehlende Leser und schließt die
  Sockets entfernter Boxen auf kurzlebigen Daemon-Threads (`relay-close`), ohne auf sie oder die
  Leser zu warten. Wird ein Geheimnis entfernt und wieder genannt, solange alte Leser noch laufen
  (z. B. in einem hängenden `connect`), wartet der neue, bis **alle** beim Anlegen laufenden Leser
  dieses Geheimnisses beendet sind (`_live`, ein Leser verlässt die Menge erst an seinem Ende); die
  spät geöffnete Verbindung eines alten wird verworfen. So gibt es je Geheimnis nie zwei
  gleichzeitige `connect`, sonst verdrängte die alte die neue Verbindung (`replaced`).
- **`shutdown`** schließt alle Sockets auf `relay-close`-Threads (weckt ein wartendes `recv` und ein
  hängendes `send`; der Aufrufer wartet nie auf einen langsamen Close-Handshake), setzt die
  Stopp-Ereignisse (weckt jede Wartezeit des Backoffs) und den Arbeits-Thread, und wartet insgesamt
  höchstens `join_s` auf alle Threads samt Schließern. Ein hängendes `connect`, `close` oder ein
  langsamer Handler halten es also nicht auf; `on_idle` läuft danach nicht mehr. Die Threads sind
  Daemons und enden von selbst (ein spät geöffneter Socket wird sofort geschlossen). Aus dem Handler
  gerufen wartet es nicht auf den eigenen Thread.
- Die Threads liegen **außerhalb** von `BackgroundTaskRunner`; `wait_idle` wartet nicht auf sie.
- Gewartet wird nur über `threading.Event.wait` bzw. `Condition.wait` (mit Frist oder geweckt durch
  `notify_all` bei jedem Stopp und jedem Leser-Ende), nie über `sleep`.
- Eine Sperre (`_cond`) schützt Boxen, Zustände und Slots; sie wird nie über `connect`, `recv`,
  `send`, den Handler oder `on_idle` gehalten. Reihenfolge: `_cond` vor der Sperre des Cursors.

Schließcodes der Box: `1000` mit Grund `replaced` ⇒ kein automatisches Neuverbinden (Zustand
`replaced`; erst `set_boxes` ohne und danach wieder mit dem Geheimnis startet die Box neu), `1000`
mit `wiped` ⇒ Cursor auf 0 (`cursor.reset`) und neu verbinden, `1008` ⇒ mindestens
`throttled_wait_s` warten, alles andere ⇒ Backoff (`backoff`, nach einer gelungenen Verbindung
wieder ab der ersten Stufe).

Das Box-Geheimnis steht nie in einer Logzeile, einem Thread-Namen oder einem Statusfeld nach außen
(`states` ist nur intern, der Dienst übersetzt). Logs nennen die Kurzmarke `short_mark` (erste
sechs Zeichen von sha256(Geheimnis)) und von Ausnahmen nur den Typ, nie den Text. Offline loggt
eine Box höchstens eine Warnung je Zustandswechsel (verbunden → gestört), jeder weitere
Fehlversuch nur auf DEBUG.
"""
from __future__ import annotations

import hashlib
import logging
import threading
import time
from collections import deque
from collections.abc import Callable, Collection
from dataclasses import dataclass
from functools import partial
from typing import TypeVar

from src.mobile_box_cursor import MobileBoxCursor
from src.mobile_relay_codec import FrameError, FrameTooLarge, decode_message, encode_put
from src.ws_client import Connect, Socket, SocketClosed, SocketTimeout

log = logging.getLogger(__name__)

HEARTBEAT_TEXT = "ping"
CLOSE_NORMAL = 1000
CLOSE_POLICY = 1008
REASON_REPLACED = "replaced"
REASON_WIPED = "wiped"

STATE_CONNECTING = "connecting"
STATE_CONNECTED = "connected"
STATE_BACKOFF = "backoff"
STATE_REPLACED = "replaced"
STATE_STOPPED = "stopped"

_OUT_STOPPED = "stopped"
_OUT_REPLACED = "replaced"
_OUT_WIPED = "wiped"
_OUT_THROTTLED = "throttled"
_OUT_ERROR = "error"

_T = TypeVar("_T")


@dataclass(frozen=True)
class LinkTiming:
    heartbeat_s: float = 90.0
    pong_wait_s: float = 30.0
    backoff: tuple[float, ...] = (1, 2, 4, 8, 16, 30, 60)
    throttled_wait_s: float = 60.0
    idle_tick_s: float = 5.0
    join_s: float = 2.0


DEFAULT_TIMING = LinkTiming()     # unveränderlich, als Vorgabe von `RelayLink(timing=…)` teilbar

def short_mark(secret: str) -> str:
    """Kurzmarke einer Box für Logs: die ersten 6 Zeichen von sha256(Geheimnis)."""
    return hashlib.sha256(str(secret).encode("utf-8", "replace")).hexdigest()[:6]


def _close_async(sock: Socket) -> threading.Thread:
    """Schließt `sock` auf einem kurzlebigen Daemon-Thread: der Aufrufer wartet nie auf ein
    langsames `close()` (Close-Handshake, ein hängendes `send` hinter der Sperre der Bibliothek)."""
    thread = threading.Thread(target=sock.close, name="relay-close", daemon=True)
    thread.start()
    return thread


def _guarded(what: str, mark: str, fn: Callable[[], _T]) -> _T | None:
    """Ruft `fn`; jede `Exception` wird mit Typ geloggt und ergibt `None`."""
    try:
        return fn()
    except Exception as exc:
        # Thread-Rand: ein Programmfehler im Handler, in `on_idle` oder in einer Verbindung darf den
        # Leser bzw. den einen Arbeits-Thread nicht beenden. Nur der Typ ins Log — der Text einer
        # Ausnahme kann das Geheimnis oder Inhalte tragen, deshalb auch kein `exc_info`.
        log.error("Relay-Box %s: %s scheiterte (%s)", mark, what, type(exc).__name__)
        return None


class _PongMissing(Exception):
    """Nach einem `ping` kam in `pong_wait_s` nichts zurück."""


class _Box:
    """Zustand einer Box. Felder außer `reported` nur unter `RelayLink._cond` ändern;
    `reported` gehört allein dem Leser-Thread der Box."""

    def __init__(self, secret: str, predecessors: frozenset[_Box] = frozenset()) -> None:
        self.secret = secret
        # Alle beim Anlegen noch laufenden Leser desselben Geheimnisses; dieser startet erst, wenn
        # keiner davon mehr läuft (`RelayLink._live`).
        self.predecessors = predecessors
        self.mark = short_mark(secret)
        self.stop = threading.Event()
        self.send_lock = threading.Lock()
        self.sock: Socket | None = None
        self.state = STATE_CONNECTING
        self.pending: tuple[int, bytes] | None = None
        self.reported: str | None = None


class RelayLink:
    def __init__(self, connect: Connect, handler: Callable[[str, bytes], None],
                 cursor: MobileBoxCursor, *, on_idle: Callable[[], None] | None = None,
                 timing: LinkTiming = DEFAULT_TIMING) -> None:
        self._connect = connect
        self._handler = handler
        self._cursor = cursor
        self._on_idle = on_idle
        self._timing = timing
        self._cond = threading.Condition()
        self._boxes: dict[str, _Box] = {}
        self._ready: deque[str] = deque()
        self._readers: list[threading.Thread] = []
        # Je Geheimnis die Boxen, deren Leser-Thread noch läuft (auch entfernte). Ein Leser verlässt
        # die Menge erst an seinem tatsächlichen Ende, also nach `connect` und Schließen.
        self._live: dict[str, set[_Box]] = {}
        self._closed = False
        self._worker = threading.Thread(target=self._work, name="relay-worker", daemon=True)
        self._worker.start()

    # --- öffentliche Schnittstelle ------------------------------------------------------

    def set_boxes(self, secrets: Collection[str]) -> None:
        """Gleicht die Boxen ab: startet fehlende Leser, schließt entfernte. Blockiert nicht."""
        wanted = set(secrets)
        closing: list[Socket] = []
        with self._cond:
            if self._closed:
                return
            for secret in [s for s in self._boxes if s not in wanted]:
                box = self._boxes.pop(secret)
                box.stop.set()
                box.pending = None
                if box.sock is not None:
                    closing.append(box.sock)
            self._readers = [t for t in self._readers if t.is_alive()]
            for secret in wanted:
                if secret in self._boxes:
                    continue
                running = self._live.setdefault(secret, set())
                box = _Box(secret, frozenset(running))
                running.add(box)
                self._boxes[secret] = box
                thread = threading.Thread(target=self._read, args=(box,),
                                          name=f"relay-box-{box.mark}", daemon=True)
                self._readers.append(thread)
                # unter der Sperre gestartet: `shutdown` sieht nie einen ungestarteten Thread
                thread.start()
            self._cond.notify_all()           # ein wartender Nachfolger sieht sein `stop`
        for sock in closing:
            _close_async(sock)

    def put(self, secret: str, frame: bytes) -> bool:
        """Legt `frame` als `put` in die Box. `False`, wenn nicht verbunden oder zu groß; wirft nie."""
        mark = short_mark(secret)
        try:
            data = encode_put(frame)
        except FrameTooLarge:
            log.warning("Relay-Box %s: Antwort zu groß (%d Byte), verworfen", mark, len(frame))
            return False
        except FrameError:
            log.warning("Relay-Box %s: ungültige Antwort verworfen", mark)
            return False
        with self._cond:
            box = self._boxes.get(secret)
            sock = box.sock if box is not None and box.state == STATE_CONNECTED else None
        if box is None or sock is None:
            return False
        with box.send_lock:
            try:
                sock.send(data)
            except (SocketClosed, OSError) as exc:
                log.info("Relay-Box %s: Senden scheiterte (%s)", mark, type(exc).__name__)
                return False
        return True

    def states(self) -> dict[str, str]:
        """Zustand je Box (Schlüssel = Geheimnis). Nur intern — nie so ins Log oder in die UI."""
        with self._cond:
            return {secret: box.state for secret, box in self._boxes.items()}

    def shutdown(self) -> None:
        """Beendet alles; idempotent, wartet höchstens `join_s`."""
        with self._cond:
            if self._closed:
                return
            self._closed = True
            sockets: list[Socket] = []
            for box in self._boxes.values():
                box.stop.set()
                box.pending = None
                box.state = STATE_STOPPED
                if box.sock is not None:
                    sockets.append(box.sock)
            self._ready.clear()
            threads = [*self._readers, self._worker]
            self._cond.notify_all()
        threads += [_close_async(sock) for sock in sockets]
        deadline = time.monotonic() + self._timing.join_s
        current = threading.current_thread()
        for thread in threads:
            if thread is current:
                continue
            thread.join(max(0.0, deadline - time.monotonic()))

    # --- Leser-Thread je Box ------------------------------------------------------------

    def _set_state(self, box: _Box, state: str) -> None:
        with self._cond:
            if not self._closed and not box.stop.is_set():
                box.state = state

    def _report_failure(self, box: _Box, kind: str) -> None:
        if box.reported != "failing":
            box.reported = "failing"
            log.warning("Relay-Box %s nicht verbunden (%s), neuer Versuch nach Wartezeit",
                        box.mark, kind)
        else:
            log.debug("Relay-Box %s: Versuch gescheitert (%s)", box.mark, kind)

    def _report_ok(self, box: _Box) -> None:
        if box.reported != "ok":
            box.reported = "ok"
            log.info("Relay-Box %s verbunden", box.mark)

    def _read(self, box: _Box) -> None:
        try:
            if self._await_predecessor(box):
                self._run_box(box)
        finally:
            with self._cond:
                running = self._live.get(box.secret)
                if running is not None:
                    running.discard(box)
                    if not running:
                        del self._live[box.secret]
                self._cond.notify_all()

    def _await_predecessor(self, box: _Box) -> bool:
        """Wartet, bis keiner der beim Anlegen laufenden Leser desselben Geheimnisses mehr läuft
        (sonst verdrängte dessen noch laufendes `connect` die neue Verbindung, `1000 replaced`).
        `False` bei `stop`: dann endet dieser Leser sofort, ohne je verbunden zu haben."""
        with self._cond:
            self._cond.wait_for(lambda: box.stop.is_set() or not (
                box.predecessors & self._live.get(box.secret, set())))
            box.predecessors = frozenset()
            return not box.stop.is_set()

    def _run_box(self, box: _Box) -> None:
        timing = self._timing
        steps = timing.backoff or (1.0,)
        attempt = 0
        while not box.stop.is_set():
            self._set_state(box, STATE_CONNECTING)
            result = _guarded("Verbindung", box.mark, partial(self._session, box))
            outcome, was_connected = result if result is not None else (_OUT_ERROR, False)
            if box.stop.is_set():
                break
            if was_connected:
                attempt = 0
            if outcome == _OUT_REPLACED:
                self._set_state(box, STATE_REPLACED)
                log.warning("Relay-Box %s: von einer anderen Verbindung verdrängt, "
                            "kein automatisches Neuverbinden", box.mark)
                return
            step = steps[min(attempt, len(steps) - 1)]
            if outcome == _OUT_THROTTLED:
                delay = max(timing.throttled_wait_s, step)
            elif outcome == _OUT_WIPED:
                delay = step
            else:
                delay = step
                attempt += 1
            self._set_state(box, STATE_BACKOFF)
            box.stop.wait(delay)

    def _session(self, box: _Box) -> tuple[str, bool]:
        """Eine Verbindung von `connect` bis zum Ende. Liefert (Ausgang, war verbunden)."""
        try:
            sock = self._connect(box.secret, self._cursor.get(box.secret))
        except SocketClosed as exc:
            return self._closed_outcome(box, exc), False
        except OSError as exc:
            self._report_failure(box, type(exc).__name__)
            return _OUT_ERROR, False
        with self._cond:
            stale = box.stop.is_set() or self._closed
            if not stale:
                box.sock = sock
                box.state = STATE_CONNECTED
        if stale:
            sock.close()
            return _OUT_STOPPED, False
        self._report_ok(box)
        try:
            self._read_loop(box, sock)
            outcome = _OUT_STOPPED
        except SocketClosed as exc:
            outcome = _OUT_STOPPED if box.stop.is_set() else self._closed_outcome(box, exc)
        except _PongMissing:
            self._report_failure(box, "keine Antwort auf ping")
            outcome = _OUT_ERROR
        except OSError as exc:
            self._report_failure(box, type(exc).__name__)
            outcome = _OUT_ERROR
        finally:
            with self._cond:
                if box.sock is sock:
                    box.sock = None
            sock.close()
        return outcome, True

    def _closed_outcome(self, box: _Box, exc: SocketClosed) -> str:
        # Der Grund kommt vom Server; geloggt wird nur der Code.
        if exc.code == CLOSE_NORMAL and exc.reason == REASON_REPLACED:
            return _OUT_REPLACED
        if exc.code == CLOSE_NORMAL and exc.reason == REASON_WIPED:
            with self._cond:
                box.pending = None            # ein altes `ver` darf den Cursor nicht wieder anheben
                self._cursor.reset(box.secret)
            log.info("Relay-Box %s wurde geleert, Cursor zurückgesetzt", box.mark)
            return _OUT_WIPED
        if exc.code == CLOSE_POLICY:
            self._report_failure(box, "gedrosselt, Code 1008")
            return _OUT_THROTTLED
        self._report_failure(box, f"geschlossen, Code {exc.code}")
        return _OUT_ERROR

    def _read_loop(self, box: _Box, sock: Socket) -> None:
        timing = self._timing
        awaiting_pong = False
        while not box.stop.is_set():
            try:
                data = sock.recv(timing.pong_wait_s if awaiting_pong else timing.heartbeat_s)
            except SocketTimeout:
                if awaiting_pong:
                    raise _PongMissing() from None
                with box.send_lock:
                    sock.send(HEARTBEAT_TEXT)
                awaiting_pong = True
                continue
            awaiting_pong = False
            message = decode_message(data)
            if message is not None and message.kind == "slot":
                self._offer(box, message.ver, message.data)

    def _offer(self, box: _Box, ver: int, payload: bytes) -> None:
        with self._cond:
            if box.stop.is_set() or self._boxes.get(box.secret) is not box:
                return
            if box.pending is None:
                self._ready.append(box.secret)
            box.pending = (ver, payload)
            self._cond.notify_all()

    # --- Arbeits-Thread -----------------------------------------------------------------

    def _take_job(self) -> tuple[str, bytes, str] | None:
        """Unter `_cond`: nächster wartender Slot (Cursor schon vorgerückt) oder `None`."""
        while self._ready:
            secret = self._ready.popleft()
            box = self._boxes.get(secret)
            if box is None or box.pending is None:
                continue
            ver, payload = box.pending
            box.pending = None
            self._cursor.advance(secret, ver)
            return secret, payload, box.mark
        return None

    def _work(self) -> None:
        tick = self._timing.idle_tick_s
        next_idle = time.monotonic() + tick
        while True:
            with self._cond:
                while not self._closed and not self._ready:
                    remaining = next_idle - time.monotonic()
                    if remaining <= 0:
                        break
                    self._cond.wait(remaining)
                if self._closed:
                    return
                job = self._take_job()
            if job is not None:
                secret, payload, mark = job
                _guarded("Handler", mark, partial(self._handler, secret, payload))
            now = time.monotonic()
            if now >= next_idle:
                next_idle = now + tick
                if self._on_idle is not None and not self._closed:
                    _guarded("on_idle", "-", self._on_idle)
