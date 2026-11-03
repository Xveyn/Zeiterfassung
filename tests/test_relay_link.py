"""Tests der Verbindungsschicht zum Relay (`src/relay_link.py`, #358), ohne Netz.

Gefälschte Sockets aus `tests/fakes_relay.py`, Zeiten im Millisekundenbereich. Gewartet wird nur über
Ereignisse und Bedingungen mit Obergrenze; die wenigen festen Pausen sind negative Nachweise
(„es passiert nichts“) und deutlich länger als die beteiligten Wartezeiten.
"""
from __future__ import annotations

import logging
import struct
import threading
import time

import pytest

from src.mobile_box_cursor import MobileBoxCursor
from src.mobile_relay_codec import MAX_PAYLOAD, TYPE_OK, TYPE_SLOT, encode_put
from src.relay_link import LinkTiming, RelayLink, short_mark
from tests.fakes_relay import LIMIT_S, FakeConnect, FakeSocket, wait_until

SECRET = "S" * 20 + "ecret_" + "x" * 17          # 43 Zeichen, Form eines Box-Geheimnisses
OTHER = "O" * 43
TOL = 0.01          # Uhr und Event.wait: Untergrenzen mit ca. 10 ms Spielraum
assert len(SECRET) == 43

FAST = LinkTiming(heartbeat_s=5.0, pong_wait_s=5.0, backoff=(0.01,), throttled_wait_s=0.05,
                  idle_tick_s=5.0, join_s=1.0)


def slot(ver: int, data: bytes) -> bytes:
    return bytes([TYPE_SLOT]) + struct.pack(">I", ver) + data


def ok(ver: int) -> bytes:
    return bytes([TYPE_OK]) + struct.pack(">I", ver)


class Recorder:
    """Handler, der Aufrufe mitschreibt und auf Wunsch blockiert."""

    def __init__(self, cursor: MobileBoxCursor | None = None) -> None:
        self.cond = threading.Condition()
        self.calls: list[tuple[str, bytes]] = []
        self.threads: list[threading.Thread] = []
        self.have_seen: list[int] = []
        self.cursor = cursor
        self.block: threading.Event | None = None
        self.started = threading.Event()
        self.raise_on: set[bytes] = set()

    def __call__(self, secret: str, payload: bytes) -> None:
        with self.cond:
            self.calls.append((secret, payload))
            self.threads.append(threading.current_thread())
            if self.cursor is not None:
                self.have_seen.append(self.cursor.get(secret))
            self.cond.notify_all()
        self.started.set()
        if self.block is not None:
            self.block.wait(LIMIT_S)
        if payload in self.raise_on:
            raise ValueError(f"Handler kaputt {secret}")

    def wait_calls(self, count: int) -> bool:
        with self.cond:
            return self.cond.wait_for(lambda: len(self.calls) >= count, LIMIT_S)


@pytest.fixture
def cursor(tmp_path):
    return MobileBoxCursor(str(tmp_path / "mobile_box_cursor.json"))


@pytest.fixture
def make_link(cursor):
    links: list[RelayLink] = []

    def make(connect: FakeConnect, handler=None, *, timing: LinkTiming = FAST,
             on_idle=None) -> RelayLink:
        link = RelayLink(connect, handler or Recorder(), cursor, on_idle=on_idle, timing=timing)
        links.append(link)
        return link

    yield make
    for link in links:
        link.shutdown()


def connected(link: RelayLink, secret: str = SECRET) -> bool:
    return wait_until(lambda: link.states().get(secret) == "connected")


# --- Zustellung an den Arbeits-Thread --------------------------------------------------


def test_slot_reaches_handler_on_worker_thread(make_link):
    connect = FakeConnect()
    handler = Recorder()
    link = make_link(connect, handler)
    link.set_boxes([SECRET])
    sock = connect.socket(0)
    sock.feed(slot(1, b"req-1"))
    assert handler.wait_calls(1)
    assert handler.calls == [(SECRET, b"req-1")]
    assert handler.threads[0] not in sock.recv_threads
    assert handler.threads[0] is not threading.current_thread()


def test_have_advanced_before_handler_runs(make_link, cursor):
    connect = FakeConnect()
    handler = Recorder(cursor)
    link = make_link(connect, handler)
    link.set_boxes([SECRET])
    connect.socket(0).feed(slot(5, b"a"))
    assert handler.wait_calls(1)
    assert handler.have_seen == [5]
    assert cursor.get(SECRET) == 5


def test_reconnect_sends_have(make_link, cursor):
    connect = FakeConnect()
    handler = Recorder()
    link = make_link(connect, handler)
    link.set_boxes([SECRET])
    sock = connect.socket(0)
    sock.feed(slot(7, b"a"))
    assert handler.wait_calls(1)
    assert connect.calls[0].have == 0
    sock.close_from_server(1006, "")
    assert connect.wait_calls(2)
    assert connect.calls[1].secret == SECRET
    assert connect.calls[1].have == 7


def test_latest_wins_per_box(make_link):
    connect = FakeConnect()
    handler = Recorder()
    handler.block = threading.Event()
    link = make_link(connect, handler)
    link.set_boxes([SECRET])
    sock = connect.socket(0)
    sock.feed(slot(1, b"eins"))
    assert handler.wait_calls(1)
    sock.feed(slot(2, b"zwei"))
    sock.feed(slot(3, b"drei"))
    assert sock.wait_drained()
    handler.block.set()
    assert handler.wait_calls(2)
    assert [p for _, p in handler.calls] == [b"eins", b"drei"]


def test_ok_and_text_are_ignored(make_link):
    connect = FakeConnect()
    handler = Recorder()
    link = make_link(connect, handler)
    link.set_boxes([SECRET])
    sock = connect.socket(0)
    sock.feed(ok(1))
    sock.feed("pong")
    sock.feed(b"\x09kaputt")
    sock.feed(slot(2, b"echt"))
    assert handler.wait_calls(1)
    assert handler.calls == [(SECRET, b"echt")]


def test_two_boxes_each_reach_handler(make_link):
    connect = FakeConnect()
    handler = Recorder()
    link = make_link(connect, handler)
    link.set_boxes([SECRET, OTHER])
    assert connect.wait_calls(2)
    by_secret = {c.secret: i for i, c in enumerate(connect.calls)}
    connect.socket(by_secret[SECRET]).feed(slot(1, b"a"))
    connect.socket(by_secret[OTHER]).feed(slot(1, b"b"))
    assert handler.wait_calls(2)
    assert sorted(handler.calls) == sorted([(SECRET, b"a"), (OTHER, b"b")])
    assert len({t for t in handler.threads}) == 1


# --- put ------------------------------------------------------------------------------


def test_put_encodes_and_sends(make_link):
    connect = FakeConnect()
    link = make_link(connect)
    link.set_boxes([SECRET])
    assert connected(link)
    assert link.put(SECRET, b"antwort") is True
    assert connect.socket(0).sent[-1] == encode_put(b"antwort")


def test_put_without_connection_returns_false(make_link):
    connect = FakeConnect()
    connect.always_fail = OSError("weg")
    link = make_link(connect, timing=LinkTiming(backoff=(10.0,), join_s=1.0))
    assert link.put(SECRET, b"x") is False              # unbekannte Box
    link.set_boxes([SECRET])
    assert wait_until(lambda: link.states().get(SECRET) == "backoff")
    assert link.put(SECRET, b"x") is False              # Box ohne Verbindung


def test_put_after_server_close_returns_false(make_link):
    connect = FakeConnect()
    link = make_link(connect, timing=LinkTiming(backoff=(10.0,), join_s=1.0))
    link.set_boxes([SECRET])
    assert connected(link)
    connect.socket(0).close_from_server(1006)
    assert wait_until(lambda: link.states().get(SECRET) == "backoff")
    assert link.put(SECRET, b"x") is False


def test_put_oversize_returns_false_and_logs(make_link, caplog):
    caplog.set_level(logging.DEBUG, logger="src.relay_link")
    connect = FakeConnect()
    link = make_link(connect)
    link.set_boxes([SECRET])
    assert connected(link)
    sock = connect.socket(0)
    before = list(sock.sent)
    assert link.put(SECRET, b"x" * (MAX_PAYLOAD + 1)) is False
    assert sock.sent == before
    warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert warnings and short_mark(SECRET) in warnings[-1].getMessage()
    assert link.put(SECRET, "kein bytes") is False   # type: ignore[arg-type]


# --- Heartbeat --------------------------------------------------------------------------


def test_slow_handler_does_not_block_heartbeat(make_link):
    connect = FakeConnect()
    handler = Recorder()
    handler.block = threading.Event()
    timing = LinkTiming(heartbeat_s=0.02, pong_wait_s=1.0, backoff=(0.01,), join_s=1.0)
    link = make_link(connect, handler, timing=timing)
    link.set_boxes([SECRET])
    sock = connect.socket(0)
    sock.feed(slot(1, b"lang"))
    assert handler.started.wait(LIMIT_S)
    try:
        assert sock.wait_sent(lambda sent: sum(1 for s in sent if s == "ping") >= 3)
        assert handler.calls == [(SECRET, b"lang")]      # der Handler hängt noch
        assert len(connect.calls) == 1                   # kein Neuverbinden nötig
    finally:
        handler.block.set()


def test_missing_pong_reconnects(make_link):
    connect = FakeConnect()
    connect.auto_pong = False
    timing = LinkTiming(heartbeat_s=0.02, pong_wait_s=0.05, backoff=(0.01,), join_s=1.0)
    link = make_link(connect, timing=timing)
    link.set_boxes([SECRET])
    first = connect.socket(0)
    assert connect.wait_calls(2)
    assert first.closed_event.is_set()
    assert first.pings() >= 1


# --- Schließcodes -----------------------------------------------------------------------


def test_replaced_close_does_not_reconnect(make_link):
    connect = FakeConnect()
    link = make_link(connect)
    link.set_boxes([SECRET])
    assert connected(link)
    connect.socket(0).close_from_server(1000, "replaced")
    assert wait_until(lambda: link.states().get(SECRET) == "replaced")
    time.sleep(0.2)                                   # Backoff ist 10 ms: hier kämen viele Versuche
    assert len(connect.calls) == 1
    link.set_boxes([SECRET])                          # erneutes Nennen allein startet nicht
    time.sleep(0.05)
    assert len(connect.calls) == 1
    assert link.states()[SECRET] == "replaced"
    link.set_boxes([])
    link.set_boxes([SECRET])
    assert connect.wait_calls(2)
    assert connected(link)


def test_wiped_resets_have_and_reconnects(make_link, cursor):
    connect = FakeConnect()
    handler = Recorder()
    link = make_link(connect, handler)
    link.set_boxes([SECRET])
    sock = connect.socket(0)
    sock.feed(slot(5, b"a"))
    assert handler.wait_calls(1)
    assert cursor.get(SECRET) == 5
    sock.close_from_server(1000, "wiped")
    assert connect.wait_calls(2)
    assert connect.calls[1].have == 0
    assert cursor.get(SECRET) == 0


def test_throttle_close_waits_at_least_throttled_wait(make_link):
    connect = FakeConnect()
    timing = LinkTiming(heartbeat_s=5.0, backoff=(0.01,), throttled_wait_s=0.3, join_s=1.0)
    link = make_link(connect, timing=timing)
    link.set_boxes([SECRET])
    assert connected(link)
    closed_at = time.monotonic()
    connect.socket(0).close_from_server(1008, "")
    assert connect.wait_calls(2)
    assert connect.calls[1].at - closed_at >= 0.3 - TOL


def test_handshake_throttle_also_waits(make_link):
    from src.ws_client import SocketClosed
    connect = FakeConnect()
    connect.plan(SocketClosed(1008, ""))
    timing = LinkTiming(backoff=(0.01,), throttled_wait_s=0.3, join_s=1.0)
    link = make_link(connect, timing=timing)
    link.set_boxes([SECRET])
    assert connect.wait_calls(2)
    assert connect.calls[1].at - connect.calls[0].at >= 0.3 - TOL


def test_other_close_uses_backoff_and_resets_after_success(make_link):
    connect = FakeConnect()
    connect.plan(OSError("a"), OSError("b"))
    timing = LinkTiming(heartbeat_s=5.0, backoff=(0.01, 0.4, 5.0), join_s=1.0)
    link = make_link(connect, timing=timing)
    link.set_boxes([SECRET])
    assert connect.wait_calls(3)
    calls = connect.calls
    assert calls[1].at - calls[0].at >= 0.01 - TOL
    assert calls[2].at - calls[1].at >= 0.4 - TOL         # zweite Stufe
    assert connected(link)
    connect.socket(0).close_from_server(1006, "")
    assert connect.wait_calls(4)
    # nach der gelungenen Verbindung beginnt der Backoff wieder bei Stufe 1 (10 ms), nicht bei 5 s
    assert connect.calls[3].at - connect.calls[2].at < 2.0


# --- Geheimnis und Log ------------------------------------------------------------------


def test_secret_never_logged(make_link, caplog):
    caplog.set_level(logging.DEBUG)
    from src.ws_client import SocketClosed
    connect = FakeConnect()
    connect.plan(OSError(f"kaputt {SECRET}"), SocketClosed(1006, SECRET),
                 OSError(f"wieder {SECRET}"))
    handler = Recorder()
    handler.raise_on = {b"boom"}
    link = make_link(connect, handler)
    link.set_boxes([SECRET])
    sock = connect.socket(0)
    sock.feed(slot(1, b"boom"))
    assert handler.wait_calls(1)
    assert link.put(SECRET, b"x" * (MAX_PAYLOAD + 1)) is False
    sock.close_from_server(1000, "replaced")
    assert wait_until(lambda: link.states().get(SECRET) == "replaced")
    link.shutdown()
    assert caplog.records
    for record in caplog.records:
        text = record.getMessage()
        assert SECRET not in text
        assert record.exc_info is None
        assert SECRET not in str(record.args)
    assert SECRET not in caplog.text
    assert short_mark(SECRET) in caplog.text
    assert all(SECRET not in t.name for t in threading.enumerate())


def test_a_failed_connect_logs_its_kind(make_link, caplog):
    from src.ws_client import ConnectFailed
    caplog.set_level(logging.DEBUG, logger="src.relay_link")
    connect = FakeConnect()
    connect.always_fail = ConnectFailed("gaierror")
    link = make_link(connect, timing=LinkTiming(backoff=(0.001,), join_s=1.0))
    link.set_boxes([SECRET])
    assert connect.wait_calls(2)
    warnings = [r.getMessage() for r in caplog.records
                if r.name == "src.relay_link" and r.levelno >= logging.WARNING]
    assert warnings and "gaierror" in warnings[0]


def test_offline_logs_once_per_state_change(make_link, caplog):
    caplog.set_level(logging.DEBUG, logger="src.relay_link")
    connect = FakeConnect()
    connect.always_fail = OSError("offline")
    timing = LinkTiming(backoff=(0.001,), join_s=1.0)
    link = make_link(connect, timing=timing)
    link.set_boxes([SECRET])
    assert connect.wait_calls(10)
    warnings = [r for r in caplog.records
                if r.name == "src.relay_link" and r.levelno >= logging.WARNING]
    assert len(warnings) == 1
    # wieder online, dann wieder offline: genau eine weitere Warnung
    connect.always_fail = None
    assert connected(link)
    connect.always_fail = OSError("offline")
    count = len(connect.calls)
    connect.sockets[-1].close_from_server(1006)
    assert connect.wait_calls(count + 10)
    warnings = [r for r in caplog.records
                if r.name == "src.relay_link" and r.levelno >= logging.WARNING]
    assert len(warnings) == 2


# --- Robustheit des Arbeits-Threads -----------------------------------------------------


def test_handler_exception_keeps_worker_alive(make_link, caplog):
    caplog.set_level(logging.DEBUG, logger="src.relay_link")
    connect = FakeConnect()
    handler = Recorder()
    handler.raise_on = {b"boom"}
    link = make_link(connect, handler)
    link.set_boxes([SECRET])
    sock = connect.socket(0)
    sock.feed(slot(1, b"boom"))
    assert handler.wait_calls(1)
    sock.feed(slot(2, b"gut"))
    assert handler.wait_calls(2)
    assert handler.calls[1] == (SECRET, b"gut")
    assert any("ValueError" in r.getMessage() for r in caplog.records)


def test_unexpected_connect_error_keeps_reader_alive(make_link):
    connect = FakeConnect()
    connect.plan(RuntimeError("unerwartet"))
    link = make_link(connect)
    link.set_boxes([SECRET])
    assert connect.wait_calls(2)
    assert connected(link)


def test_on_idle_called_periodically_from_worker(make_link):
    connect = FakeConnect()
    seen: list[threading.Thread] = []
    timing = LinkTiming(idle_tick_s=0.02, join_s=1.0)

    def on_idle() -> None:
        seen.append(threading.current_thread())
        if len(seen) == 2:
            raise RuntimeError("darf den Takt nicht beenden")

    make_link(connect, on_idle=on_idle, timing=timing)
    assert wait_until(lambda: len(seen) >= 4)
    assert len({t for t in seen}) == 1
    assert seen[0] is not threading.current_thread()


# --- set_boxes und shutdown -------------------------------------------------------------


def test_removed_box_is_closed_and_dropped(make_link):
    connect = FakeConnect()
    link = make_link(connect)
    link.set_boxes([SECRET])
    assert connected(link)
    link.set_boxes([])
    assert connect.socket(0).closed_event.wait(LIMIT_S)
    assert link.states() == {}
    time.sleep(0.05)
    assert len(connect.calls) == 1


def test_shutdown_returns_within_join_while_connecting(make_link):
    connect = FakeConnect()
    connect.gate = threading.Event()
    link = make_link(connect, timing=LinkTiming(join_s=0.2))
    link.set_boxes([SECRET])
    try:
        assert connect.wait_calls(1)
        start = time.monotonic()
        link.shutdown()
        assert time.monotonic() - start < 0.2 + 0.5
        assert link.states() == {SECRET: "stopped"}
    finally:
        connect.gate.set()
    sock = connect.socket(0)
    assert sock.closed_event.wait(LIMIT_S)            # spät geöffnete Verbindung wird gleich zu


def test_shutdown_returns_within_join_in_backoff(make_link):
    connect = FakeConnect()
    connect.always_fail = OSError("weg")
    link = make_link(connect, timing=LinkTiming(backoff=(30.0,), join_s=0.5))
    link.set_boxes([SECRET])
    assert wait_until(lambda: link.states().get(SECRET) == "backoff")
    start = time.monotonic()
    link.shutdown()
    assert time.monotonic() - start < 0.5            # Wartezeit geweckt, nicht ausgesessen
    assert wait_until(lambda: not any(t.name.startswith("relay-") and t.is_alive()
                                      for t in threading.enumerate()))


def test_shutdown_returns_within_join_while_handler_runs(make_link):
    connect = FakeConnect()
    handler = Recorder()
    handler.block = threading.Event()
    link = make_link(connect, handler, timing=LinkTiming(join_s=0.2))
    link.set_boxes([SECRET])
    sock = connect.socket(0)
    sock.feed(slot(1, b"lang"))
    assert handler.started.wait(LIMIT_S)
    try:
        start = time.monotonic()
        link.shutdown()
        assert time.monotonic() - start < 0.2 + 0.5
        assert sock.closed_event.is_set()
    finally:
        handler.block.set()


def test_shutdown_is_idempotent_and_stops_everything(make_link):
    connect = FakeConnect()
    link = make_link(connect)
    link.set_boxes([SECRET])
    assert connected(link)
    link.shutdown()
    link.shutdown()
    assert link.states() == {SECRET: "stopped"}
    assert link.put(SECRET, b"x") is False
    link.set_boxes([OTHER])                            # nach dem Beenden ohne Wirkung
    time.sleep(0.05)
    assert len(connect.calls) == 1


def test_shutdown_from_handler_does_not_deadlock(make_link):
    connect = FakeConnect()
    done = threading.Event()
    holder: list[RelayLink] = []

    def handler(secret: str, payload: bytes) -> None:
        holder[0].shutdown()
        done.set()

    link = make_link(connect, handler)
    holder.append(link)
    link.set_boxes([SECRET])
    connect.socket(0).feed(slot(1, b"x"))
    assert done.wait(LIMIT_S)


def test_fake_socket_is_a_socket():
    from src.ws_client import Socket
    sock: Socket = FakeSocket()
    sock.close()


# --- Fix-Runde 1: hängendes close/send, Wiederaufnahme während eines Connects ---------------


def test_shutdown_returns_within_join_when_close_hangs(make_link):
    connect = FakeConnect()
    sock = FakeSocket()
    sock.hang_close = threading.Event()
    connect.plan(sock)
    link = make_link(connect, timing=LinkTiming(join_s=0.2))
    link.set_boxes([SECRET])
    assert connected(link)
    try:
        start = time.monotonic()
        link.shutdown()
        assert time.monotonic() - start < 0.2 + 0.5
        assert sock.close_entered.is_set()
    finally:
        sock.hang_close.set()


def test_set_boxes_does_not_block_when_close_hangs(make_link):
    connect = FakeConnect()
    sock = FakeSocket()
    sock.hang_close = threading.Event()
    connect.plan(sock)
    link = make_link(connect)
    link.set_boxes([SECRET])
    assert connected(link)
    try:
        start = time.monotonic()
        link.set_boxes([])
        assert time.monotonic() - start < 0.5
        assert sock.close_entered.wait(LIMIT_S)
        assert link.states() == {}
    finally:
        sock.hang_close.set()


def test_shutdown_in_time_while_put_and_close_hang(make_link):
    """Wie ein echter Socket hinter der Sperre der Bibliothek: `send` hängt, `close` hängt ebenfalls
    und weckt `send` nicht — nur ein harter Abbruch täte das (`ws_client`, getestet dort mit echtem
    Server). `shutdown` hält trotzdem seine Frist; nach dem Abbruch liefert `put` `False`."""
    connect = FakeConnect()
    sock = FakeSocket()
    sock.hang_send = True
    sock.close_wakes_send = False
    sock.hang_close = threading.Event()
    connect.plan(sock)
    link = make_link(connect, timing=LinkTiming(join_s=0.3))
    link.set_boxes([SECRET])
    assert connected(link)
    result: list[bool] = []
    putter = threading.Thread(target=lambda: result.append(link.put(SECRET, b"antwort")),
                              daemon=True)
    putter.start()
    try:
        assert sock.send_entered.wait(LIMIT_S)
        start = time.monotonic()
        link.shutdown()
        assert time.monotonic() - start < 0.3 + 0.5
        assert sock.close_entered.wait(LIMIT_S)
        assert putter.is_alive() and result == []       # `put` hängt noch: nur der Abbruch weckt
        sock.wake_send.set()                             # harter Abbruch des echten Sockets
        putter.join(LIMIT_S)
        assert result == [False]
    finally:
        sock.wake_send.set()
        sock.hang_close.set()


def test_readd_while_old_connect_hangs_keeps_new_connection(make_link):
    connect = FakeConnect()
    connect.gate = threading.Event()
    link = make_link(connect)
    link.set_boxes([SECRET])
    assert connect.wait_calls(1)                     # alter Leser hängt in `connect`
    link.set_boxes([])
    link.set_boxes([SECRET])
    time.sleep(0.05)
    assert len(connect.calls) == 1                   # der neue wartet auf das Ende des alten
    connect.gate.set()
    assert connect.wait_calls(2)
    old, new = connect.socket(0), connect.socket(1)
    assert old.closed_event.wait(LIMIT_S)            # späte Verbindung des alten verworfen
    assert connected(link)
    time.sleep(0.05)
    assert link.states() == {SECRET: "connected"}
    assert not new.closed_event.is_set()
    assert len(connect.calls) == 2


def test_on_idle_not_called_after_shutdown(make_link):
    connect = FakeConnect()
    calls: list[float] = []
    link = make_link(connect, on_idle=lambda: calls.append(time.monotonic()),
                     timing=LinkTiming(idle_tick_s=0.01, join_s=1.0))
    assert wait_until(lambda: len(calls) >= 2)
    link.shutdown()
    count = len(calls)
    time.sleep(0.05)
    assert len(calls) == count


def _churn(link: RelayLink) -> None:
    """set_boxes([S]) mit hängendem connect A, dann [] ; [S] ; [] ; [S] (Fund des Re-Reviews)."""
    link.set_boxes([])
    link.set_boxes([SECRET])
    time.sleep(0.05)
    link.set_boxes([])
    time.sleep(0.05)
    link.set_boxes([SECRET])
    time.sleep(0.1)


def test_churn_never_runs_two_connects_for_one_secret(make_link):
    connect = FakeConnect()
    connect.gate = threading.Event()
    link = make_link(connect)
    link.set_boxes([SECRET])
    assert connect.wait_calls(1)
    try:
        _churn(link)
        assert len(connect.calls) == 1                  # alle Nachfolger warten auf A
        assert connect.max_in_flight == 1
    finally:
        connect.gate.set()
    assert connect.wait_calls(2)
    assert connected(link)
    time.sleep(0.1)
    assert connect.max_in_flight == 1
    assert len(connect.calls) == 2
    assert link.states() == {SECRET: "connected"}
    assert wait_until(lambda: len(connect.open_sockets()) == 1)
    assert connect.socket(0).closed_event.is_set()       # spät geöffnete Verbindung von A verworfen
    assert connect.open_sockets() == [connect.socket(1)]


def test_churn_ending_removed_leaves_nothing_after_release(make_link):
    connect = FakeConnect()
    connect.gate = threading.Event()
    link = make_link(connect)
    link.set_boxes([SECRET])
    assert connect.wait_calls(1)
    try:
        _churn(link)
        link.set_boxes([])
    finally:
        connect.gate.set()
    assert connect.socket(0).closed_event.wait(LIMIT_S)
    time.sleep(0.1)
    assert len(connect.calls) == 1
    assert link.states() == {}
    assert connect.open_sockets() == []
    assert wait_until(lambda: link._live == {})          # kein Leser des Geheimnisses läuft mehr
