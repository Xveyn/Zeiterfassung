"""Tests des WebSocket-Adapters gegen einen lokalen Server (127.0.0.1, Port 0)."""
from __future__ import annotations

import socket
import threading
import time

import pytest

pytest.importorskip("websockets")

from websockets.sync.server import serve  # noqa: E402

from src import ws_client  # noqa: E402
from src.mobile_relay_codec import MAX_FRAME, SUBPROTOCOL  # noqa: E402

SECRET = "S" * 43
HTTP_403 = b"HTTP/1.1 403 Forbidden" + bytes([13, 10]) + b"Content-Length: 0" + bytes([13, 10, 13, 10])


class Harness:
    def __init__(self, behavior):
        self.seen = {}
        self.behavior = behavior
        self.server = serve(self._handler, "127.0.0.1", 0, subprotocols=[SUBPROTOCOL],
                            compression=None, max_size=MAX_FRAME + 64)
        self.port = self.server.socket.getsockname()[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def _handler(self, conn):
        self.seen["headers"] = conn.request.headers
        self.seen["path"] = conn.request.path
        self.seen["subprotocol"] = conn.subprotocol
        self.behavior(conn)

    @property
    def url(self):
        return f"http://127.0.0.1:{self.port}"

    def stop(self):
        self.server.shutdown()
        self.thread.join(5)


@pytest.fixture
def harness():
    made = []

    def make(behavior):
        h = Harness(behavior)
        made.append(h)
        return h

    yield make
    for h in made:
        h.stop()


def _hold(conn):
    try:
        for _ in conn:
            pass
    except Exception:
        pass


def test_handshake_has_no_origin_and_carries_subprotocol(harness):
    h = harness(_hold)
    sock = ws_client.connect(SECRET, 7, base_url=h.url)
    try:
        sock.send("ping")
        time.sleep(0.2)
    finally:
        sock.close()
    headers = h.seen["headers"]
    assert "Origin" not in headers
    offered = headers["Sec-WebSocket-Protocol"]
    assert SUBPROTOCOL in offered and SECRET in offered
    assert "permessage-deflate" not in (headers.get("Sec-WebSocket-Extensions") or "")
    assert h.seen["path"].endswith("role=desktop&have=7")
    assert h.seen["subprotocol"] == SUBPROTOCOL


def test_recv_times_out_with_SocketTimeout(harness):
    h = harness(_hold)
    sock = ws_client.connect(SECRET, 0, base_url=h.url)
    try:
        with pytest.raises(ws_client.SocketTimeout):
            sock.recv(0.1)
    finally:
        sock.close()


def test_recv_and_send_roundtrip(harness):
    h = harness(lambda conn: conn.send(conn.recv()))
    sock = ws_client.connect(SECRET, 0, base_url=h.url)
    try:
        sock.send(b"\x01abc")
        assert sock.recv(2.0) == b"\x01abc"
    finally:
        sock.close()


def test_server_close_surfaces_code_and_reason(harness):
    h = harness(lambda conn: conn.close(1000, "replaced"))
    sock = ws_client.connect(SECRET, 0, base_url=h.url)
    try:
        with pytest.raises(ws_client.SocketClosed) as info:
            sock.recv(2.0)
    finally:
        sock.close()
    assert info.value.code == 1000
    assert info.value.reason == "replaced"


def test_send_after_close_raises_SocketClosed(harness):
    h = harness(_hold)
    sock = ws_client.connect(SECRET, 0, base_url=h.url)
    sock.close()
    with pytest.raises(ws_client.SocketClosed):
        sock.send("ping")


def test_close_from_other_thread_wakes_recv(harness):
    h = harness(_hold)
    sock = ws_client.connect(SECRET, 0, base_url=h.url)
    threading.Timer(0.2, sock.close).start()
    started = time.monotonic()
    with pytest.raises(ws_client.SocketClosed):
        sock.recv(10.0)
    assert time.monotonic() - started < 5
    sock.close()  # doppelt schliessen wirft nie


def _dead_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_error_text_never_contains_secret():
    secret = "TOPSECRET" + "x" * 34
    with pytest.raises(OSError) as info:
        ws_client.connect(secret, 3, base_url=f"http://127.0.0.1:{_dead_port()}", open_timeout=2)
    assert secret not in str(info.value) and secret not in repr(info.value)
    assert info.value.__cause__ is None and info.value.__suppress_context__


def test_failed_handshake_hides_secret():
    secret = "REJECT" + "y" * 37
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)

    def accept_and_drop():
        conn, _ = listener.accept()
        conn.recv(4096)
        conn.sendall(HTTP_403)

    threading.Thread(target=accept_and_drop, daemon=True).start()
    port = listener.getsockname()[1]
    try:
        with pytest.raises((OSError, ws_client.SocketClosed)) as info:
            ws_client.connect(secret, 1, base_url=f"http://127.0.0.1:{port}", open_timeout=2)
    finally:
        listener.close()
    assert secret not in str(info.value) and secret not in repr(info.value)
    assert info.value.__cause__ is None and info.value.__suppress_context__


def test_https_maps_to_wss():
    assert ws_client._ws_url("https://example.org", 5) == "wss://example.org/v1/box/ws?role=desktop&have=5"
    assert ws_client._ws_url("http://127.0.0.1:1", 0) == "ws://127.0.0.1:1/v1/box/ws?role=desktop&have=0"


@pytest.mark.parametrize("bad", ["a b" + "x" * 40, "a,b" + "x" * 40, "\u00e4" * 43, "ab\ncd" + "x" * 38, ""])
def test_invalid_secret_raises_oserror_without_secret(bad):
    with pytest.raises(OSError) as info:
        ws_client.connect(bad, 1, base_url=f"http://127.0.0.1:{_dead_port()}", open_timeout=2)
    exc = info.value
    if bad:
        assert bad not in str(exc) and bad not in repr(exc)
    assert exc.__cause__ is None and exc.__context__ is None


# --- Fix-Runde 1: DEBUG-Leck, zeitbegrenztes Schliessen ------------------------------------


def test_debug_log_never_contains_secret(harness, caplog):
    import logging
    caplog.set_level(logging.DEBUG)
    secret = "DEBUGLEAK" + "z" * 34
    h = harness(lambda conn: conn.send(conn.recv()))
    sock = ws_client.connect(secret, 4, base_url=h.url)
    try:
        sock.send(b"\x01abc")
        assert sock.recv(2.0) == b"\x01abc"
    finally:
        sock.close()
    # Der lokale Testserver (Logger `websockets.server`) spielt den Relay und loggt selbst; geprüft
    # wird alles, was die Client-Seite schreibt.
    client = [r for r in caplog.records if not r.name.startswith("websockets.server")]
    assert client is not None
    for record in client:
        assert secret not in record.getMessage()
        assert secret not in str(record.args)
        if record.exc_info:
            assert secret not in logging.Formatter().formatException(record.exc_info)
    assert not [r for r in client if r.name.startswith("websockets")]


class SilentServer:
    """Nimmt den WebSocket-Handshake an und liest danach nie wieder (Server hängt)."""

    def __init__(self):
        import base64
        import hashlib
        self._b64 = base64
        self._sha1 = hashlib.sha1
        self.listener = socket.socket()
        self.listener.bind(("127.0.0.1", 0))
        self.listener.listen(1)
        self.port = self.listener.getsockname()[1]
        self.release = threading.Event()
        self.conns = []
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        conn, _ = self.listener.accept()
        self.conns.append(conn)
        conn.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4096)
        data = b""
        while b"\r\n\r\n" not in data:
            chunk = conn.recv(4096)
            if not chunk:
                return
            data += chunk
        key = ""
        for line in data.decode("latin-1").split("\r\n"):
            if line.lower().startswith("sec-websocket-key:"):
                key = line.split(":", 1)[1].strip()
        accept = self._b64.b64encode(self._sha1(
            (key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()).digest()).decode()
        conn.sendall(("HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\n"
                      "Connection: Upgrade\r\nSec-WebSocket-Accept: " + accept + "\r\n"
                      "Sec-WebSocket-Protocol: " + SUBPROTOCOL + "\r\n\r\n").encode())
        self.release.wait(30)

    @property
    def url(self):
        return f"http://127.0.0.1:{self.port}"

    def stop(self):
        self.release.set()
        for conn in self.conns:
            conn.close()
        self.listener.close()


@pytest.fixture
def silent():
    server = SilentServer()
    yield server
    server.stop()


def test_close_returns_quickly_when_server_ignores_close(silent):
    sock = ws_client.connect(SECRET, 0, base_url=silent.url)
    started = time.monotonic()
    sock.close()
    elapsed = time.monotonic() - started
    assert elapsed < ws_client.ABORT_AFTER_S + 1.0, elapsed


def test_close_wakes_a_hung_send(silent):
    sock = ws_client.connect(SECRET, 0, base_url=silent.url)
    progress = {"sent": 0, "error": None}
    frame = b"\x01" + b"x" * (MAX_FRAME - 1)

    def flood():
        try:
            while True:
                sock.send(frame)
                progress["sent"] += 1
        except Exception as exc:  # Ergebnis des Tests, nicht verschluckt
            progress["error"] = exc

    sender = threading.Thread(target=flood, daemon=True)
    sender.start()
    # warten, bis der Sendepuffer voll ist und `send` hängt (kein Fortschritt mehr)
    deadline = time.monotonic() + 20
    last, stalled_since = -1, time.monotonic()
    while time.monotonic() < deadline:
        if progress["sent"] != last:
            last, stalled_since = progress["sent"], time.monotonic()
        elif time.monotonic() - stalled_since > 0.5:
            break
        time.sleep(0.02)
    assert sender.is_alive(), "send hing nie"
    started = time.monotonic()
    sock.close()
    assert time.monotonic() - started < ws_client.ABORT_AFTER_S + 1.5
    sender.join(5)
    assert not sender.is_alive()
    assert isinstance(progress["error"], ws_client.SocketClosed)
