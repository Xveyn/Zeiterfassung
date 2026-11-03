"""WebSocket-Adapter zum Relay (#358), Tk-frei, ohne Logik des Abgleichs.

`relay_link` programmiert nur gegen `Socket` und `Connect`, nie gegen die Bibliothek
(`websockets`, sync-Client). Das Box-Geheimnis steht nie in einem Log, einer Ausnahme-Meldung
oder einer URL im Log: Bibliotheksausnahmen koennen URL und Header tragen, deshalb wird jede in
`SocketClosed`/`OSError` mit festem Text uebersetzt (`from None`, die Kette bleibt leer).
Blockiert (Netz): nur im Worker aufrufen.
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Protocol
from urllib.parse import urlsplit, urlunsplit

from src.mobile_relay_codec import BOX_SECRET_RE, MAX_FRAME, SUBPROTOCOL
from src.push_relay import RELAY_URL

log = logging.getLogger(__name__)

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
        """Schliesst; wirft nie, aus jedem Thread aufrufbar, weckt ein wartendes `recv`."""
        ...


Connect = Callable[[str, int], Socket]


def _ws_url(base_url: str, have: int) -> str:
    parts = urlsplit(base_url)
    scheme = {"https": "wss", "http": "ws"}.get(parts.scheme, parts.scheme)
    return urlunsplit((scheme, parts.netloc, WS_PATH, f"role=desktop&have={int(have)}", ""))


class _LibSocket:
    """`Socket` ueber eine `websockets.sync`-Verbindung."""

    def __init__(self, conn: Any) -> None:
        self._conn = conn

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
        try:
            self._conn.send(data)
        except ConnectionClosed as exc:
            raise self._closed(exc) from None

    def close(self) -> None:
        try:
            self._conn.close()
        except (OSError, RuntimeError):
            # Schliessen darf nie werfen; eine halb tote Verbindung ist ohnehin zu.
            log.debug("Schliessen der Relay-Verbindung scheiterte", exc_info=False)


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
