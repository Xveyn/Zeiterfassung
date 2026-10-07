# src/api_service.py
"""Lebenszyklus der lokalen HTTP-API (#92), Tk-frei.

`ApiService.apply()` liest `api_enabled`/`api_port` aus den Settings und bringt
den Server in den passenden Zustand — im Worker, nie im UI-Thread: das
Token-Laden blockiert (Windows: `icacls` bis 15 s). Das Ergebnis ist ein
`ApiStatus` samt Grund, den der Settings-Tab (PR 3) anzeigt.

Beenden, Entfernen und Skalierungs-Neustart rufen `shutdown()`; das wartet nie
länger als `lock_timeout` auf einen laufenden Start (nichts darf das Beenden
aufhalten) und sperrt danach jeden weiteren Start — wichtig beim Entfernen, wo
ein spät fertiges Token-Laden die Datei neu anlegen würde.
"""
from __future__ import annotations

import errno
import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from src.api_auth import (
    load_or_create_token, rotate_token, single_token_verifier,
)
from src.api_auth import read_token as read_token_file
from src.api_routes import ApiContext
from src.api_server import ApiServer

if TYPE_CHECKING:  # nur für die Signaturen
    from src.settings import SettingsLike

_log = logging.getLogger(__name__)

DEFAULT_PORT = 17653
MIN_PORT = 1024
MAX_PORT = 65535

STATE_OFF = "off"
STATE_RUNNING = "running"
STATE_STARTING = "starting"
STATE_ERROR = "error"

REASON_INVALID_PORT = "invalid_port"
REASON_PORT_IN_USE = "port_in_use"
REASON_TOKEN_UNAVAILABLE = "token_unavailable"
REASON_START_FAILED = "start_failed"
REASON_CLOSED = "closed"
REASON_ROTATE_FAILED = "rotate_failed"

_MAX_PORT_DIGITS = 5
# Windows meldet einen belegten Port mit WSAEADDRINUSE (10048), einen mit
# SO_EXCLUSIVEADDRUSE fremd gebundenen mit WSAEACCES (10013).
_WINERRORS_IN_USE = (10048, 10013)


@dataclass(frozen=True)
class ApiStatus:
    state: str
    port: int | None = None
    reason: str = ""


@dataclass(frozen=True)
class RotateResult:
    ok: bool
    reason: str = ""


def parse_port(value: Any) -> int | None:
    """Gültiger Port (1024–65535) oder `None`. Bools, Floats, Text mit Nicht-
    ASCII-Ziffern und absurd lange Zahlen sind ungültig."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        port = value
    elif isinstance(value, str):
        text = value.strip()
        if not (text.isascii() and text.isdigit()) or len(text) > _MAX_PORT_DIGITS:
            return None
        port = int(text)
    else:
        return None
    return port if MIN_PORT <= port <= MAX_PORT else None


def _port_in_use(exc: OSError) -> bool:
    return (exc.errno in (errno.EADDRINUSE, errno.EACCES)
            or getattr(exc, "winerror", None) in _WINERRORS_IN_USE)


class ApiService:
    def __init__(self, settings: SettingsLike, base_path: str, context: ApiContext, *,
                 run: Callable[..., None],
                 on_status: Callable[[ApiStatus], None] | None = None) -> None:
        self._settings = settings
        self._base_path = base_path
        self._context = context
        self._run = run
        self._on_status = on_status
        self._lock = threading.Lock()
        self._server: ApiServer | None = None
        self._status = ApiStatus(STATE_OFF)
        self._closed = False

    @property
    def status(self) -> ApiStatus:
        return self._status

    def apply(self) -> None:
        """Bringt den Server in den Zustand der Settings. Im UI-Thread
        aufrufen; die Arbeit läuft im Worker, `on_status` kommt zurück.

        Sofort sichtbar wird „startet": das Token-Laden blockiert unter
        Windows bis 15 s, bis dahin stünde sonst „aus" da."""
        if self._closed:
            return
        port = parse_port(self._settings.get("api_port"))
        if (self._settings.get("api_enabled") and port is not None
                and self._running_port() != port):
            self._status = ApiStatus(STATE_STARTING, port)
        self._run(self._reconcile, self._publish)

    def _running_port(self) -> int | None:
        server = self._server
        if server is None:
            return None
        try:
            return server.port
        except RuntimeError:                     # gerade gestoppt
            return None

    def _publish(self, _result: ApiStatus) -> None:
        # Der aktuelle Stand, nicht das Ergebnis dieses Workers: kommen zwei
        # Worker vertauscht zurück, würde die UI sonst einen veralteten
        # Status zeigen.
        if self._on_status is not None:
            self._on_status(self._status)

    def _reconcile(self) -> ApiStatus:
        with self._lock:
            try:
                return self._reconcile_locked()
            except Exception:
                # Der Runner würde den Fehler nur loggen und `on_done` nie
                # rufen — der Status bliebe stehen. Hier wird er zum Zustand.
                _log.exception("Lokale API: Start/Stopp fehlgeschlagen")
                self._stop_server()
                self._status = ApiStatus(STATE_ERROR, None, REASON_START_FAILED)
                return self._status

    def _reconcile_locked(self) -> ApiStatus:
        if self._closed:
            return self._status
        if not self._settings.get("api_enabled"):
            self._stop_server()
            self._status = ApiStatus(STATE_OFF)
            return self._status
        port = parse_port(self._settings.get("api_port"))
        if port is None:
            self._stop_server()
            self._status = ApiStatus(STATE_ERROR, None, REASON_INVALID_PORT)
            return self._status
        if self._server is not None and self._server.port == port:
            # Läuft schon. RUNNING setzen statt `_status` durchzureichen: `apply`
            # kann dazwischen „startet" geschrieben haben.
            self._status = ApiStatus(STATE_RUNNING, port)
            return self._status
        self._stop_server()
        token = load_or_create_token(self._base_path)    # blockiert: nur im Worker
        if token is None:
            self._status = ApiStatus(STATE_ERROR, None, REASON_TOKEN_UNAVAILABLE)
            return self._status
        if self._closed:                         # Beenden/Entfernen kam dazwischen
            return self._status
        server = ApiServer(self._context, single_token_verifier(token), port=port)
        try:
            server.start()
        except OSError as exc:
            reason = REASON_PORT_IN_USE if _port_in_use(exc) else REASON_START_FAILED
            _log.warning("Lokale API: Start auf Port %s scheitert (%s)", port, reason,
                         exc_info=True)
            self._status = ApiStatus(STATE_ERROR, port, reason)
            return self._status
        self._server = server
        self._status = ApiStatus(STATE_RUNNING, server.port)
        return self._status

    def _stop_server(self) -> None:
        server, self._server = self._server, None
        if server is not None:
            server.stop()

    def shutdown(self, lock_timeout: float = 1.0) -> None:
        """Stoppt den Server und sperrt weitere Starts. Blockiert höchstens
        `lock_timeout`: läuft gerade ein Start (der Worker hält den Lock),
        wird nicht gewartet — der Start prüft `_closed` und bricht selbst ab,
        und ein Daemon-Thread stirbt mit dem Prozess."""
        self._closed = True
        if not self._lock.acquire(timeout=lock_timeout):
            _log.warning("Lokale API: Beenden wartet nicht auf einen laufenden Start")
            return
        try:
            self._stop_server()
            self._status = ApiStatus(STATE_OFF)
        finally:
            self._lock.release()

    def rotate(self) -> RotateResult:
        """Erneuert das Token und tauscht den Prüfer des laufenden Servers aus.

        **Blockiert** (Dateizugriff, unter Windows `icacls`): nur im Worker.
        Läuft unter demselben Lock wie der Start — nach jeder Verschränkung
        akzeptiert der Server genau das Token, das in der Datei steht.
        Scheitert das Schreiben, bleibt das alte Token gültig."""
        with self._lock:
            if self._closed:
                return RotateResult(False, REASON_CLOSED)
            try:
                token = rotate_token(self._base_path)
            except OSError:
                _log.warning("Lokale API: Token konnte nicht erneuert werden",
                             exc_info=True)
                return RotateResult(False, REASON_ROTATE_FAILED)
            if self._server is not None:
                self._server.set_verifier(single_token_verifier(token))
            return RotateResult(True)

    def read_token(self) -> str | None:
        """Token zum Kopieren (Settings-Tab). Rein lesend: legt nichts an.
        Dateizugriff — über den Worker aufrufen."""
        return read_token_file(self._base_path)

    def reopen(self) -> None:
        """Macht `shutdown` rückgängig (Skalierungs-Neustart ist gescheitert,
        die App läuft weiter). Der nächste `apply()` startet wieder."""
        self._closed = False
