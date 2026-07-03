# src/single_instance.py
"""Single-Instance-Guard (Tk-frei). Erstinstanz bindet einen pro-Nutzer
abgeleiteten Localhost-Port; Folgeinstanzen melden sich per Socket und beenden
sich. Blockiert den Start nie — jeder Fehlerpfad endet im (ggf. ungeschützten)
Weiterlauf."""
import logging
import os
import socket
import sys
import threading
import zlib

_MAGIC_SHOW = b"ZEIT-SHOW"
_MAGIC_PING = b"ZEIT-PING"
_MAGIC_OK = b"ZEIT-OK"
_ACK_TIMEOUT = 2.0          # großzügig gegen Boot-Last
_PORT_BASE = 20000
_PORT_SPAN = 12000          # Range 20000–31999, unter allen Ephemeral-Ranges

_log = logging.getLogger(__name__)


def _derive_port(base_path):
    norm = os.path.normcase(os.path.normpath(base_path))
    return _PORT_BASE + (zlib.crc32(norm.encode("utf-8")) % _PORT_SPAN)


class _Guard:
    def __init__(self, port):
        self.port = port
        self.bound = False
        self._sock = None
        self._lock = threading.Lock()
        self._show_fn = None
        self._pending_show = False
        self._stop = False

    def _try_bind(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        if sys.platform == "win32":
            # Windows: verhindert, dass ein zweiter Prozess denselben Port bindet.
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        else:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
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

    def _accept_loop(self):
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
            with conn:
                try:
                    data = conn.recv(32)
                    if data.startswith(_MAGIC_SHOW):
                        conn.sendall(_MAGIC_OK)
                        self._fire_show()
                    elif data.startswith(_MAGIC_PING):
                        conn.sendall(_MAGIC_OK)
                except OSError:
                    pass

    def _fire_show(self):
        with self._lock:
            fn = self._show_fn
            if fn is None:
                self._pending_show = True
                return
        fn()

    def serve(self, show_fn):
        """Registriert den Fenster-Holen-Callback. Ein vor serve() eingetroffenes
        SHOW feuert jetzt nach."""
        with self._lock:
            self._show_fn = show_fn
            pending = self._pending_show
            self._pending_show = False
        if pending:
            show_fn()

    def release(self):
        """Listener stoppen und Port freigeben (No-op wenn nie gebunden)."""
        self._stop = True
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None
        self.bound = False


def _notify_primary(port, show_requested):
    """Meldet sich bei der laufenden Instanz. True nur, wenn sie sich per
    ZEIT-OK als unsere App bestätigt."""
    msg = _MAGIC_SHOW if show_requested else _MAGIC_PING
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=_ACK_TIMEOUT) as sock:
            sock.sendall(msg)
            sock.settimeout(_ACK_TIMEOUT)
            return sock.recv(len(_MAGIC_OK)) == _MAGIC_OK
    except OSError:
        return False


def acquire(base_path, show_requested):
    """Erstinstanz → gebundener _Guard. Läuft schon eine (bestätigt per ZEIT-OK)
    → None (Aufrufer beendet sich). Port von Fremd-Software belegt → degradierter
    (ungebundener) _Guard, damit der Start nie blockiert."""
    port = _derive_port(base_path)
    guard = _Guard(port)
    if guard._try_bind():
        return guard
    if _notify_primary(port, show_requested):
        return None
    _log.warning("Single-Instance-Port %d belegt, kein ZEIT-OK — Start ohne Guard", port)
    return guard
