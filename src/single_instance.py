# src/single_instance.py
"""Single-Instance-Guard (Tk-frei). Erstinstanz bindet einen pro-Nutzer
abgeleiteten Localhost-Port; Folgeinstanzen melden sich per Socket und beenden
sich. Blockiert den Start nie — jeder Fehlerpfad endet im (ggf. ungeschützten)
Weiterlauf."""
from __future__ import annotations

import hmac
from typing import Callable
import logging
import os
import socket
import stat
import sys
import tempfile
import threading
import time
import zlib

from src.secure_file import harden_windows_acl

_MAGIC_SHOW = b"ZEIT-SHOW"
_MAGIC_PING = b"ZEIT-PING"
_MAGIC_OK = b"ZEIT-OK"
_MAGIC_LEN = len(_MAGIC_SHOW)   # 9; SHOW und PING sind gleich lang
_SECRET_LEN = 32
_SECRET_FILENAME = "instance-secret"
_ACK_TIMEOUT = 2.0          # großzügig gegen Boot-Last
_PORT_BASE = 20000
_PORT_SPAN = 12000          # Range 20000–31999, unter allen Ephemeral-Ranges

_log = logging.getLogger(__name__)


def _derive_port(base_path: str) -> int:
    norm = os.path.normcase(os.path.normpath(base_path))
    return _PORT_BASE + (zlib.crc32(norm.encode("utf-8")) % _PORT_SPAN)


def _write_secret_atomic(path: str, secret: bytes) -> None:
    """Schreibt das Instanz-Secret atomar (Temp + os.replace) mit 0600 und
    PermissionError-Retry — Muster aus oauth_utils.write_token (Issue #135).

    Unter Windows ist das chmod ein No-op, deshalb zusätzlich die ACL-Härtung
    (Audit M8): wer das Secret lesen kann, kann den SHOW/PING-Handshake fälschen
    und einer laufenden Instanz das Fenster nach vorn holen. Gehärtet wird die
    Temp-Datei, bevor os.replace sie unter dem Zielnamen sichtbar macht."""
    directory = os.path.dirname(os.path.abspath(path))
    fd, tmp_path = tempfile.mkstemp(
        dir=directory, prefix=".instance-secret-", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(secret)
        try:
            os.chmod(tmp_path, stat.S_IRUSR | stat.S_IWUSR)  # 0o600; Win: No-op
        except OSError:
            pass
        harden_windows_acl(tmp_path)
        attempts = 5
        for attempt in range(attempts):
            try:
                os.replace(tmp_path, path)
                break
            except PermissionError:
                if attempt == attempts - 1:
                    raise
                time.sleep(0.2)
    except BaseException:
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        raise


def _load_or_create_secret(base_path: str) -> bytes | None:
    """Lädt das 32-Byte-Instanz-Secret aus <base_path>/instance-secret oder
    erzeugt es beim ersten Start. Liefert 32 Bytes — oder None, wenn Lesen ODER
    Schreiben an einem OSError scheitert. None heißt: Handshake läuft
    unauthentifiziert weiter (der Start darf NIE an dieser Datei scheitern,
    Modul-Invariante). Eine vorhandene, aber unlesbare Datei wird NICHT
    überschrieben (könnte das Secret einer laufenden Instanz sein)."""
    path = os.path.join(base_path, _SECRET_FILENAME)
    try:
        with open(path, "rb") as f:
            data = f.read()
    except FileNotFoundError:
        data = None
    except OSError:
        _log.warning("Instanz-Secret nicht lesbar — Handshake unauthentifiziert",
                     exc_info=True)
        return None
    if data is not None and len(data) == _SECRET_LEN:
        return data
    # fehlt oder falsche Größe → neu erzeugen
    secret = os.urandom(_SECRET_LEN)
    try:
        _write_secret_atomic(path, secret)
        return secret
    except OSError:
        _log.warning("Instanz-Secret nicht schreibbar — Handshake unauthentifiziert",
                     exc_info=True)
        return None


def _recv_exactly(conn: socket.socket, n: int) -> bytes:
    """Liest genau n Bytes. Bei Timeout, geschlossener Verbindung oder
    Short-Read → b'' (Aufrufer verwirft die Verbindung). TCP ist ein Stream:
    ein einzelnes recv darf legal weniger als n Bytes liefern."""
    buf = bytearray()
    while len(buf) < n:
        try:
            chunk = conn.recv(n - len(buf))
        except OSError:
            return b""
        if not chunk:
            return b""
        buf.extend(chunk)
    return bytes(buf)


class _Guard:
    def __init__(self, port: int, secret: bytes | None) -> None:
        self.port = port
        self.secret = secret        # bytes(32) oder None (unauth. Fallback)
        self.bound = False
        self._sock = None
        self._lock = threading.Lock()
        self._show_fn = None
        self._pending_show = False
        self._stop = False

    def _try_bind(self) -> bool:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            if sys.platform == "win32":
                # Windows: verhindert, dass ein zweiter Prozess denselben Port bindet.
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            else:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind(("127.0.0.1", self.port))
            sock.listen(5)
        except OSError:
            sock.close()
            return False
        sock.settimeout(0.5)
        self._sock = sock
        self.bound = True
        threading.Thread(target=self._accept_loop, daemon=True).start()
        return True

    def _accept_loop(self) -> None:
        while not self._stop:
            sock = self._sock
            if sock is None:            # release() lief parallel → sauber raus
                break
            try:
                conn, _addr = sock.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            self._handle_conn(conn)

    def _handle_conn(self, conn: socket.socket) -> None:
        conn.settimeout(_ACK_TIMEOUT)
        with conn:
            try:
                if self.secret is None:
                    # Fallback (Secret nicht verfügbar): altes,
                    # unauthentifiziertes Protokoll — nur Magic prüfen.
                    magic = conn.recv(64)[:_MAGIC_LEN]
                else:
                    data = _recv_exactly(conn, _MAGIC_LEN + _SECRET_LEN)
                    if len(data) != _MAGIC_LEN + _SECRET_LEN:
                        return
                    magic, secret = data[:_MAGIC_LEN], data[_MAGIC_LEN:]
                    if not hmac.compare_digest(secret, self.secret):
                        return
                if magic == _MAGIC_SHOW:
                    conn.sendall(_MAGIC_OK)
                    self._fire_show()
                elif magic == _MAGIC_PING:
                    conn.sendall(_MAGIC_OK)
            except OSError:
                pass

    def _fire_show(self) -> None:
        with self._lock:
            fn = self._show_fn
            if fn is None:
                self._pending_show = True
                return
        fn()

    def serve(self, show_fn: Callable[[], None]) -> None:
        """Registriert den Fenster-Holen-Callback. Ein vor serve() eingetroffenes
        SHOW feuert jetzt nach."""
        with self._lock:
            self._show_fn = show_fn
            pending = self._pending_show
            self._pending_show = False
        if pending:
            show_fn()

    def release(self) -> None:
        """Listener stoppen und Port freigeben (No-op wenn nie gebunden)."""
        self._stop = True
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None
        self.bound = False


def _notify_primary(port: int, show_requested: bool,
                    secret: bytes | None) -> bool:
    """Meldet sich bei der laufenden Instanz. True nur, wenn sie sich per
    ZEIT-OK als unsere App bestätigt. Das Secret authentifiziert uns gegenüber
    dem Primary; None → altes Protokoll (nur Magic)."""
    magic = _MAGIC_SHOW if show_requested else _MAGIC_PING
    payload = magic if secret is None else magic + secret
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=_ACK_TIMEOUT) as sock:
            sock.sendall(payload)
            sock.settimeout(_ACK_TIMEOUT)
            return sock.recv(len(_MAGIC_OK)) == _MAGIC_OK
    except OSError:
        return False


def acquire(base_path: str, show_requested: bool) -> _Guard | None:
    """Erstinstanz → gebundener _Guard. Läuft schon eine (bestätigt per ZEIT-OK)
    → None (Aufrufer beendet sich). Port von Fremd-Software belegt → degradierter
    (ungebundener) _Guard, damit der Start nie blockiert."""
    port = _derive_port(base_path)
    secret = _load_or_create_secret(base_path)
    guard = _Guard(port, secret)
    if guard._try_bind():
        return guard
    if _notify_primary(port, show_requested, secret):
        return None
    _log.warning("Single-Instance-Port %d belegt, kein ZEIT-OK — Start ohne Guard", port)
    return guard
