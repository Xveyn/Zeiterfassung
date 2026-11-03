"""WebSocket-Adapter zum Relay (#358), Tk-frei, ohne Logik des Abgleichs.

`relay_link` programmiert nur gegen `Socket` und `Connect`, nie gegen die Bibliothek
(`websockets`, sync-Client). Das Box-Geheimnis steht nie in einem Log, einer Ausnahme-Meldung
oder einer URL im Log: Bibliotheksausnahmen koennen URL und Header tragen, deshalb wird jede in
`SocketClosed`/`OSError` mit festem Text uebersetzt (`from None`, die Kette bleibt leer).
Blockiert (Netz): nur im Worker aufrufen.

Die Bibliothek loggt im DEBUG-Modus jede Kopfzeile des Handshakes, darunter
`Sec-WebSocket-Protocol: zeit.v1, <Geheimnis>`. Sie bekommt deshalb einen eigenen Logger
(`src.ws_client.lib`), fest auf WARNING: was die Bibliothek darüber noch meldet (Fehler mit
Traceback ihrer Sicherheitsnetze), trägt keine Kopfzeilen. `ZEITERFASSUNG_LOG_LEVEL=DEBUG` ändert
daran nichts, weil das Level des Loggers selbst gesetzt ist.

Ein hängendes `send` (voller Sendepuffer bei totem Netz) hält die Sperre der Bibliothek. Zwei
Wächter brechen die Verbindung dann hart ab (`_abort`, ein hängendes `send`/`recv` wacht mit
`SocketClosed` auf): der des `send` selbst nach `SEND_TIMEOUT_S`, der von `close()` nach
`ABORT_AFTER_S` (der Close-Handshake wartet höchstens `CLOSE_TIMEOUT_S`).
"""
from __future__ import annotations

import logging
import socket
import threading
from typing import Any, Callable, Protocol
from urllib.parse import urlsplit, urlunsplit

from src.mobile_relay_codec import BOX_SECRET_RE, MAX_FRAME, SUBPROTOCOL
from src.push_relay import RELAY_URL

log = logging.getLogger(__name__)

# Eigener Logger der Bibliothek, fest auf WARNING (kein Geheimnis aus den Handshake-Kopfzeilen im Log).
_LIB_LOG = logging.getLogger(__name__ + ".lib")
_LIB_LOG.setLevel(logging.WARNING)

CLOSE_TIMEOUT_S = 1.0      # Wartezeit des Close-Handshakes
ABORT_AFTER_S = 1.5        # danach bricht der Wächter von `close()` die Verbindung hart ab
SEND_TIMEOUT_S = 30.0      # danach bricht der Wächter eines hängenden `send` die Verbindung ab

WS_PATH = "/v1/box/ws"
FAILED_TEXT = "Verbindung zum Relay fehlgeschlagen"


class SocketClosed(Exception):
    """Die Verbindung ist zu (vom Server, vom Netz oder lokal geschlossen)."""

    def __init__(self, code: int | None = None, reason: str = "") -> None:
        super().__init__(f"Verbindung geschlossen (Code {code})")
        self.code = code
        self.reason = reason


class SocketTimeout(Exception):
    """`recv` hat in der gegebenen Zeit nichts erhalten."""


class Socket(Protocol):
    def recv(self, timeout: float) -> bytes | str:
        """Naechste Nachricht; wirft `SocketTimeout` oder `SocketClosed`."""
        ...

    def send(self, data: bytes | str) -> None:
        """Sendet eine Nachricht; wirft `SocketClosed`."""
        ...

    def close(self) -> None:
        """Schliesst; wirft nie, aus jedem Thread aufrufbar, weckt ein wartendes `recv` und ein
        hängendes `send` und kehrt zügig zurück (echter Socket: höchstens rund `ABORT_AFTER_S`)."""
        ...


Connect = Callable[[str, int], Socket]


def _ws_url(base_url: str, have: int) -> str:
    parts = urlsplit(base_url)
    scheme = {"https": "wss", "http": "ws"}.get(parts.scheme, parts.scheme)
    return urlunsplit((scheme, parts.netloc, WS_PATH, f"role=desktop&have={int(have)}", ""))


class _LibSocket:
    """`Socket` ueber eine `websockets.sync`-Verbindung."""

    def __init__(self, conn: Any, abort_after: float = ABORT_AFTER_S) -> None:
        self._conn = conn
        self._abort_after = abort_after

    @staticmethod
    def _closed(exc: Any) -> SocketClosed:
        rcvd = getattr(exc, "rcvd", None)
        return SocketClosed(rcvd.code if rcvd else None, rcvd.reason if rcvd else "")

    def recv(self, timeout: float) -> bytes | str:
        from websockets.exceptions import ConnectionClosed
        try:
            return self._conn.recv(timeout=timeout)
        except TimeoutError:
            raise SocketTimeout() from None
        except ConnectionClosed as exc:
            raise self._closed(exc) from None

    def send(self, data: bytes | str) -> None:
        from websockets.exceptions import ConnectionClosed
        done = self._arm_watchdog(SEND_TIMEOUT_S, "relay-ws-send")
        try:
            self._conn.send(data)
        except ConnectionClosed as exc:
            raise self._closed(exc) from None
        finally:
            done.set()

    def _arm_watchdog(self, after: float, name: str) -> threading.Event:
        """Bricht die Verbindung nach `after` hart ab, wenn das gelieferte Ereignis bis dahin nicht
        gesetzt ist. Ein hängendes `send` (voller Sendepuffer bei totem Netz) hält sonst die Sperre
        der Bibliothek und damit Heartbeat und Arbeits-Thread bis zum TCP-Timeout des Systems."""
        done = threading.Event()

        def watchdog() -> None:
            if done.wait(after):
                return
            try:
                self._abort()
            except Exception as exc:
                # Daemon-Wächter: ein Fehler im Abbruch (auch ein `AssertionError` der Bibliothek,
                # `close_socket` prüft den Zustand per `assert`) darf nur geloggt werden, nie den
                # Prozess stören; nur der Typ, der Text könnte Verbindungsdaten tragen.
                log.warning("Harter Abbruch der Relay-Verbindung scheiterte (%s)",
                            type(exc).__name__)

        threading.Thread(target=watchdog, name=name, daemon=True).start()
        return done

    def _abort(self) -> None:
        """Harter Abbruch, ohne Sperre der Bibliothek.

        websockets 17.4 hält `protocol_mutex` über das ganze `sendall` eines `send`
        (`send_context` → `send_data`), und der Socket ist nach dem Handshake blockierend
        (`settimeout(None)`). Ein hängendes `send` wacht unter POSIX nur durch
        `shutdown(SHUT_RDWR)` auf (ein `close(fd)` aus einem anderen Thread weckt einen blockierten
        Syscall dort nicht); unter Windows tun es beide. Deshalb zuerst `shutdown`: der Sender
        bekommt einen Fehler, verlässt `send_context` und gibt die Sperre frei; `recv_events` sieht
        EOF. Erst danach `close_socket()` — das schließt den Socket und nimmt am Ende die Sperre,
        die dann frei ist (sonst warteten Wächter und Sender aufeinander)."""
        sock = getattr(self._conn, "socket", None)
        if sock is not None:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                # Schon geschlossen oder nie verbunden (ENOTCONN/EBADF): dann hängt dort nichts.
                log.debug("shutdown der Relay-Verbindung nicht möglich", exc_info=False)
        self._conn.close_socket()

    def close(self) -> None:
        done = self._arm_watchdog(self._abort_after, "relay-ws-close")
        try:
            # Wartet auf die Sperre der Bibliothek; hält sie ein hängendes `send`, löst der Wächter sie.
            self._conn.close()
        except (OSError, RuntimeError):
            # Schliessen darf nie werfen; eine halb tote Verbindung ist ohnehin zu.
            log.debug("Schliessen der Relay-Verbindung scheiterte", exc_info=False)
        finally:
            done.set()


def connect(secret: str, have: int, *, base_url: str = RELAY_URL,
            open_timeout: float = 10.0) -> Socket:
    """Oeffnet die Verbindung zur Box. Wirft `SocketClosed` (Handshake abgelehnt) oder `OSError`
    (Netz, TLS, Zeit), beide ohne das Geheimnis im Text."""
    from websockets.exceptions import ConnectionClosed, WebSocketException
    from websockets.sync.client import connect as lib_connect
    if not isinstance(secret, str) or BOX_SECRET_RE.fullmatch(secret) is None:
        # Kein gueltiges Subprotocol-Token: die Bibliothek wuerfe ValueError mit dem Geheimnis im Text.
        raise OSError(FAILED_TEXT) from None
    try:
        conn = lib_connect(
            _ws_url(base_url, have),
            subprotocols=[SUBPROTOCOL, secret],  # type: ignore[list-item]
            origin=None,
            compression=None,        # Nutzlast ist verschluesselt, Kompression bringt nichts
            ping_interval=None,      # der Heartbeat ist der Text `ping`
            max_size=MAX_FRAME + 16,
            open_timeout=open_timeout,
            close_timeout=CLOSE_TIMEOUT_S,
            logger=_LIB_LOG,
            legacy=True,             # sonst DeprecationWarning in 17.x ohne `with`
        )
    except ConnectionClosed as exc:
        raise _LibSocket._closed(exc) from None
    except WebSocketException:
        # Handshake abgelehnt (z. B. 403/1008); der Text der Ausnahme kann das Geheimnis tragen.
        raise SocketClosed(None, "handshake") from None
    except OSError:
        raise OSError(FAILED_TEXT) from None
    except ValueError:
        # Die Bibliothek nennt bei ungueltigen Argumenten das Geheimnis im Text; verwerfen.
        raise OSError(FAILED_TEXT) from None
    return _LibSocket(conn)
