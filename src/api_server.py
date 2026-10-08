# src/api_server.py
"""HTTP-Server der lokalen API (#92), Tk-frei. Kein Fachwissen: er nimmt eine
Anfrage entgegen, lässt `api_auth.authorize` entscheiden, übergibt an
`api_routes.handle` und schreibt die Antwort.

Eigener Daemon-Thread (Muster: der Accept-Loop in `single_instance`), pro
Verbindung ein weiterer Daemon-Thread (`ThreadingMixIn`). Der Server berührt nie
ein Widget und hält keinen Store-Lock; die Routen holen ihre Daten über die
Store-Methoden.

Absichtlich NICHT `serve_forever()`/`shutdown()`: `shutdown()` wartet, bis
`serve_forever()` die Schleife verlassen hat, und blockiert für immer, wenn der
Thread nie dorthin kommt (er startet nicht, oder `start()` scheitert nach dem
Bind). Stattdessen pollt eine eigene Schleife mit `handle_request()` und einem
0,1-s-Timeout gegen ein `Event`; der Preis sind rund zehn Aufwachvorgänge pro
Sekunde.

Unter Windows bindet der Server mit `SO_EXCLUSIVEADDRUSE` und ohne
`SO_REUSEADDR`: sonst dürfte ein anderer lokaler Prozess denselben Port
zusätzlich binden und Bearer-Token mitlesen. Wie in `single_instance`.
"""
from __future__ import annotations

import http
import http.server
import json
import logging
import socket
import socketserver
import sys
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, cast
from urllib.parse import parse_qs

from src.api_auth import (
    AuthResult, Policy, Principal, TokenVerifier, authorize, authorize_public,
)
from src.api_routes import (
    ApiContext, ApiRequest, ApiResponse, error_response, handle, methods_for_path,
    routed_methods,
)

_log = logging.getLogger(__name__)

MAX_BODY_BYTES = 1024 * 1024
_SOCKET_TIMEOUT_S = 10.0
# Das Socket-Timeout gilt je recv(): ein Byte alle 9 s hielte eine Verbindung
# ewig offen. Die Gesamtfrist kappt sie; die Obergrenze verhindert, dass ein
# lokaler Prozess (auch ohne Token — angenommen wird vor der Auth) Threads und
# Dateihandles der ganzen App verbraucht.
_REQUEST_DEADLINE_S = 15.0
_MAX_CONNECTIONS = 32
# Lingering close: erst die Sendeseite schließen, dann kurz leer lesen. Schließt
# der Server mit ungelesenen Bytes im Puffer, schickt das OS ein RST und der
# Client verliert unter Umständen die Antwort (401 wird zu "connection reset").
# Dazu hält der zuerst schließende Teil TIME_WAIT auf seinem Port — beim Server
# wäre das der API-Port.
_LINGER_TIMEOUT_S = 0.5
_LINGER_WINDOW_S = 1.0
_LINGER_MAX_BYTES = 64 * 1024
_POLL_INTERVAL_S = 0.1
_MAX_QUERY_FIELDS = 20
_MAX_CONTENT_LENGTH_DIGITS = 12
# Diese Header dürfen genau einmal vorkommen. Ein `dict` kann Duplikate nicht
# darstellen — `authorize` sähe nur den letzten und könnte getäuscht werden.
_SINGLE_VALUE_HEADERS = ("host", "authorization", "origin", "content-type",
                         "content-length")

_AUTH_MESSAGES = {
    "method_not_allowed": "Methode nicht erlaubt.",
    "bad_host": "Ungültiger Host-Header.",
    "bad_origin": "Anfragen mit Origin-Header sind nicht erlaubt.",
    "browser_request": "Browser-Anfragen sind nicht erlaubt.",
    "unauthorized": "Token fehlt oder ist ungültig.",
    "token_expired": "Das Token ist abgelaufen. Das Gerät muss neu gekoppelt werden.",
    "token_revoked": "Das Token wurde widerrufen. Das Gerät muss neu gekoppelt werden.",
    "unsupported_media_type": "Content-Type muss application/json sein.",
}


@dataclass(frozen=True)
class Surface:
    """Was eine Server-Instanz ausliefert: die lokale API (Loopback, ein Token) und
    die Handy-Instanz (LAN, Gerätetoken, CORS) teilen sich diesen Server und
    unterscheiden sich nur hierin.

    `dispatch` bekommt eine bereits authentifizierte Anfrage. `methods` ist, was
    irgendeine Route kann (`Allow` bei einem 405 aus `authorize`, nicht
    `ALLOWED_METHODS`), `route_methods(path)` was genau dieser Pfad kann (leer =
    unbekannt; der Preflight fragt es). `public` sind (Methode, Pfad)-Paare, die
    ohne Token erreichbar sind — exakt, kein Muster. `cors` schaltet Preflight und
    CORS-Header für die erlaubten Origins der Policy ein."""
    dispatch: Callable[[ApiRequest, Principal], ApiResponse]
    methods: frozenset[str]
    route_methods: Callable[[str], frozenset[str]]
    public: frozenset[tuple[str, str]] = frozenset()
    cors: bool = False


def local_surface(context: ApiContext) -> Surface:
    return Surface(dispatch=lambda request, principal: handle(request, context, principal),
                   methods=routed_methods(), route_methods=methods_for_path)


def _auth_error(auth: AuthResult, allowed_methods: frozenset[str]) -> ApiResponse:
    headers: dict[str, str] = {}
    if auth.status == 405:
        headers["Allow"] = ", ".join(sorted(allowed_methods))
    if auth.status == 401:
        headers["WWW-Authenticate"] = "Bearer"
    return error_response(auth.status, auth.code,
                          _AUTH_MESSAGES.get(auth.code, "Abgelehnt."), headers)


class _Handler(http.server.BaseHTTPRequestHandler):
    server_version = "Zeiterfassung-API"
    sys_version = ""
    protocol_version = "HTTP/1.0"            # eine Anfrage je Verbindung
    timeout = _SOCKET_TIMEOUT_S

    def version_string(self) -> str:
        return self.server_version

    def setup(self) -> None:
        super().setup()
        self._deadline = threading.Timer(_REQUEST_DEADLINE_S, self._abort)
        self._deadline.daemon = True
        self._deadline.start()

    def finish(self) -> None:
        self._deadline.cancel()
        super().finish()

    def _abort(self) -> None:
        # Gesamtfrist überschritten: ein blockierter recv() kehrt zurück.
        try:
            self.connection.shutdown(socket.SHUT_RDWR)
        except OSError:
            _log.debug("Abbruch nach Gesamtfrist: Verbindung schon zu", exc_info=True)

    def __getattr__(self, name: str) -> Any:
        # Jede Methode läuft durch denselben Weg — auch unbekannte, damit sie
        # von `authorize` mit 405 abgelehnt werden statt als HTML-501 von
        # `http.server`.
        if name.startswith("do_"):
            return self._serve
        raise AttributeError(name)

    def log_message(self, format: str, *args: Any) -> None:
        _log.debug("API %s", format % args)

    def send_error(self, code: int, message: str | None = None,
                   explain: str | None = None) -> None:
        try:
            phrase = http.HTTPStatus(code).phrase
        except ValueError:
            phrase = "Fehler"
        self._send(error_response(code, "http_error", phrase))

    def _send(self, response: ApiResponse) -> None:
        # ensure_ascii (Standard): ein Lone Surrogate in gespeicherten Daten
        # (korrupte Datei, Sync) würde sonst beim UTF-8-Encode werfen — außerhalb
        # jedes try, der Client bekäme eine leere Antwort.
        payload = json.dumps(response.body).encode("utf-8")
        self.close_connection = True
        try:
            self.send_response(response.status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Connection", "close")
            for name, value in response.headers.items():
                self.send_header(name, value)
            self.end_headers()
            self.wfile.write(payload)
        except OSError:
            _log.debug("Client hat die Verbindung vor der Antwort geschlossen",
                       exc_info=True)

    def _serve(self) -> None:
        try:
            response = self._respond()
        except Exception:
            # Programmfehler: Details nur ins Log, nie in die Antwort.
            _log.exception("API-Anfrage fehlgeschlagen")
            response = error_response(500, "internal_error", "Interner Fehler.")
        self._send(response)

    def _read_body(self) -> bytes | ApiResponse:
        raw = self.headers.get("Content-Length")
        if raw is None:
            return b""
        if not (raw.isascii() and raw.isdigit()):
            return error_response(400, "invalid_content_length",
                                  "Content-Length ist keine Zahl.")
        if len(raw) > _MAX_CONTENT_LENGTH_DIGITS or int(raw) > MAX_BODY_BYTES:
            return error_response(413, "payload_too_large", "Body ist zu groß.")
        length = int(raw)
        if length == 0:
            return b""
        try:
            data = self.rfile.read(length)
        except TimeoutError:
            return error_response(408, "request_timeout", "Body kam nicht rechtzeitig an.")
        except ConnectionError:
            return error_response(400, "incomplete_body",
                                  "Verbindung während des Bodys beendet.")
        if len(data) != length:
            return error_response(400, "incomplete_body", "Body ist unvollständig.")
        return data

    def _respond(self) -> ApiResponse:
        server = cast("_ApiHTTPServer", self.server)
        for name in _SINGLE_VALUE_HEADERS:
            if len(self.headers.get_all(name) or []) > 1:
                return error_response(400, "duplicate_header",
                                      f"Header {name} darf nur einmal vorkommen.")
        headers = dict(self.headers.items())
        path = self.path.partition("?")[0]
        surface = server.surface
        if (self.command, path) in surface.public:
            auth = authorize_public(self.command, headers, server.policy)
        else:
            auth = authorize(self.command, headers, server.policy, server.verifier)
        if not auth.ok or auth.principal is None:
            return _auth_error(auth, surface.methods)
        if any(name.lower() == "transfer-encoding" for name in headers):
            return error_response(400, "unsupported_encoding",
                                  "Transfer-Encoding wird nicht unterstützt.")
        body = self._read_body()
        if isinstance(body, ApiResponse):
            return body
        raw_query = self.path.partition("?")[2]
        try:
            query = parse_qs(raw_query, keep_blank_values=True,
                             max_num_fields=_MAX_QUERY_FIELDS)
        except ValueError:
            return error_response(400, "invalid_query", "Ungültige Query.")
        request = ApiRequest(self.command, path, query, body)
        return surface.dispatch(request, auth.principal)


class _ApiHTTPServer(http.server.ThreadingHTTPServer):
    daemon_threads = True
    timeout = _POLL_INTERVAL_S
    # Unter Windows würde SO_REUSEADDR das gleichzeitige Binden desselben
    # Ports erlauben; dort schützt SO_EXCLUSIVEADDRUSE (server_bind).
    allow_reuse_address = sys.platform != "win32"
    max_connections = _MAX_CONNECTIONS
    # Der Standard (5) lässt bei einem Schwung gleichzeitiger Verbindungen die
    # Warteschlange überlaufen: Latenz bis über eine Sekunde, unter Windows
    # abgewiesene Verbindungen. Angenommen wird ohnehin sofort (Obergrenze oben).
    request_queue_size = 128

    def __init__(self, address: tuple[str, int],
                 policy_for_port: Callable[[int], Policy],
                 verifier: TokenVerifier, surface: Surface) -> None:
        self.verifier = verifier
        self.surface = surface
        self.policy: Policy
        self._slots = threading.BoundedSemaphore(self.max_connections)
        super().__init__(address, _Handler)
        self.policy = policy_for_port(self.server_address[1])

    def server_bind(self) -> None:
        if sys.platform == "win32":
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        # Nicht `HTTPServer.server_bind`: das ruft `socket.getfqdn` auf, und das
        # kann bei kaputtem DNS lange hängen.
        socketserver.TCPServer.server_bind(self)
        host, port = self.server_address[:2]
        self.server_name = str(host)
        self.server_port = port

    def process_request(self, request: Any, client_address: Any) -> None:
        if not self._slots.acquire(blocking=False):
            # Voll: sofort schließen, kein Thread, kein Warten im Accept-Thread.
            self.close_request(request)
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self._slots.release()                # Thread-Start gescheitert
            raise

    def process_request_thread(self, request: Any, client_address: Any) -> None:
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._slots.release()

    def shutdown_request(self, request: Any) -> None:
        """Lingering close, siehe `_LINGER_*`. Läuft im Verbindungs-Thread."""
        try:
            request.shutdown(socket.SHUT_WR)
            request.settimeout(_LINGER_TIMEOUT_S)
            end = time.monotonic() + _LINGER_WINDOW_S
            drained = 0
            while drained < _LINGER_MAX_BYTES and time.monotonic() < end:
                chunk = request.recv(4096)
                if not chunk:
                    break
                drained += len(chunk)
        except OSError:
            _log.debug("Lingering close: Verbindung schon zu", exc_info=True)
        finally:
            self.close_request(request)

    def handle_error(self, request: Any, client_address: Any) -> None:
        # Standard wäre ein Traceback auf stderr — unter --noconsole spurlos.
        exc = sys.exc_info()[1]
        if isinstance(exc, (ConnectionError, TimeoutError)):
            # Port-Scanner, RST, Abbruch: kein Fehler der App. Auf ERROR geloggt
            # spülte ein lokaler Prozess damit die Log-Rotation leer.
            _log.debug("API-Verbindung abgebrochen", exc_info=True)
            return
        _log.exception("API-Verbindung fehlgeschlagen")


class ApiServer:
    def __init__(self, context: ApiContext | None, verifier: TokenVerifier, *, port: int = 0,
                 policy_for_port: Callable[[int], Policy] = Policy.loopback,
                 surface: Surface | None = None) -> None:
        if surface is None:
            if context is None:
                raise ValueError("ApiServer braucht einen Kontext oder eine Surface")
            surface = local_surface(context)
        self._surface = surface
        self._verifier = verifier
        self._requested_port = port
        self._policy_for_port = policy_for_port
        self._httpd: _ApiHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()

    @property
    def port(self) -> int:
        if self._httpd is None:
            raise RuntimeError("Server läuft nicht")
        return int(self._httpd.server_address[1])

    def start(self) -> None:
        """Bindet und startet den Server-Thread. Wirft `OSError`, wenn der
        Bind scheitert (Port belegt)."""
        if self._httpd is not None:
            raise RuntimeError("Server läuft bereits")
        bind_host = self._policy_for_port(self._requested_port).bind_host
        httpd = _ApiHTTPServer((bind_host, self._requested_port), self._policy_for_port,
                               self._verifier, self._surface)
        self._httpd = httpd
        self._stop_event.clear()
        thread = threading.Thread(target=self._serve_loop, args=(httpd,),
                                  name="api-server", daemon=True)
        self._thread = thread
        thread.start()

    def _serve_loop(self, httpd: _ApiHTTPServer) -> None:
        while not self._stop_event.is_set():
            httpd.handle_request()

    def set_verifier(self, verifier: TokenVerifier) -> None:
        """Tauscht den Prüfer (Token-Rotation) ohne Neustart."""
        self._verifier = verifier
        if self._httpd is not None:
            self._httpd.verifier = verifier

    def stop(self, timeout: float = 2.0) -> None:
        """Beendet den Server und gibt den Port frei. Idempotent."""
        self._stop_event.set()
        thread, httpd = self._thread, self._httpd
        self._thread = None
        self._httpd = None
        if thread is not None:
            thread.join(timeout)
        if httpd is not None:
            httpd.server_close()
