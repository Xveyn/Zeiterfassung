"""Gefälschte WebSocket für die Tests von `relay_link` (#358), ohne Netz.

`FakeSocket` erfüllt das `Socket`-Protocol aus `src/ws_client.py`: der Test legt Nachrichten
der Box über `feed` ab oder schließt serverseitig über `close_from_server`; `recv` wartet höchstens
`timeout` und wirft dann `SocketTimeout`, `close` weckt ein wartendes `recv` (wie die Bibliothek).
`FakeConnect` ist ein `Connect`: protokolliert jeden Aufruf (Geheimnis, `have`, Zeitpunkt) und
liefert, was der Test vorgibt (Socket oder Ausnahme), sonst einen frischen `FakeSocket`.
Alle Wartehilfen sind durch eine Obergrenze (Standard 5 s) beschränkt, nie feste Sleeps.
"""
from __future__ import annotations

import threading
import time
from collections import deque
from typing import Callable

from src.ws_client import SocketClosed, SocketTimeout

LIMIT_S = 5.0


def wait_until(predicate: Callable[[], bool], timeout: float = LIMIT_S) -> bool:
    """Prüft `predicate` bis zur Obergrenze; kurze Abfrage statt fester Wartezeit."""
    deadline = time.monotonic() + timeout
    while True:
        if predicate():
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.002)


class _LocalClose:
    """Marke in der Eingangsschlange: lokal geschlossen."""


class FakeSocket:
    def __init__(self, *, auto_pong: bool = True) -> None:
        self.auto_pong = auto_pong
        self._cond = threading.Condition()
        self._inbox: deque[object] = deque()
        self._closed = False
        self._idle_in_recv = False
        self.sent: list[bytes | str] = []
        self.recv_threads: set[threading.Thread] = set()
        self.closed_event = threading.Event()
        # Hängende Aufrufe (wie bei totem Netz): `send` hängt, bis `wake_send` gesetzt ist; `close`
        # setzt es nur mit `close_wakes_send` (sonst weckt es erst ein separater harter Abbruch,
        # den `relay_link` gar nicht kennt). `close` hängt, bis der Test `hang_close` setzt.
        self.hang_send = False
        self.wake_send = threading.Event()
        self.close_wakes_send = True
        self.hang_close: threading.Event | None = None
        self.send_entered = threading.Event()
        self.close_entered = threading.Event()

    # --- Steuerung durch den Test -------------------------------------------------------
    def feed(self, data: bytes | str) -> None:
        with self._cond:
            self._inbox.append(data)
            self._cond.notify_all()

    def close_from_server(self, code: int | None, reason: str = "") -> None:
        with self._cond:
            self._inbox.append(SocketClosed(code, reason))
            self._cond.notify_all()

    def wait_drained(self, timeout: float = LIMIT_S) -> bool:
        """Wahr, sobald alles Gelieferte verarbeitet ist und der Leser wieder in `recv` wartet."""
        with self._cond:
            return self._cond.wait_for(lambda: not self._inbox and self._idle_in_recv, timeout)

    def wait_sent(self, predicate: Callable[[list[bytes | str]], bool],
                  timeout: float = LIMIT_S) -> bool:
        with self._cond:
            return self._cond.wait_for(lambda: predicate(list(self.sent)), timeout)

    def pings(self) -> int:
        with self._cond:
            return sum(1 for item in self.sent if item == "ping")

    # --- Socket-Protocol ---------------------------------------------------------------
    def recv(self, timeout: float) -> bytes | str:
        self.recv_threads.add(threading.current_thread())
        deadline = time.monotonic() + timeout
        with self._cond:
            while True:
                if self._inbox:
                    item = self._inbox.popleft()
                    self._idle_in_recv = False
                    self._cond.notify_all()
                    if isinstance(item, SocketClosed):
                        self._closed = True
                        self.closed_event.set()
                        raise item
                    if isinstance(item, _LocalClose):
                        raise SocketClosed(None, "")
                    assert isinstance(item, (bytes, str))
                    return item
                if self._closed:
                    raise SocketClosed(None, "")
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    self._idle_in_recv = False
                    raise SocketTimeout()
                self._idle_in_recv = True
                self._cond.notify_all()
                self._cond.wait(remaining)

    def send(self, data: bytes | str) -> None:
        if self.hang_send and data != "ping":
            self.send_entered.set()
            self.wake_send.wait(LIMIT_S)
            raise SocketClosed(None, "")
        with self._cond:
            if self._closed:
                raise SocketClosed(None, "")
            self.sent.append(data)
            if data == "ping" and self.auto_pong:
                self._inbox.append("pong")
            self._cond.notify_all()

    def close(self) -> None:
        self.close_entered.set()
        if self.close_wakes_send:
            self.wake_send.set()
        if self.hang_close is not None:
            self.hang_close.wait(LIMIT_S)
        with self._cond:
            if not self._closed:
                self._closed = True
                self._inbox.append(_LocalClose())
            self.closed_event.set()
            self._cond.notify_all()


class ConnectCall:
    def __init__(self, secret: str, have: int, at: float) -> None:
        self.secret = secret
        self.have = have
        self.at = at


class FakeConnect:
    """`Connect` mit Drehbuch: `plan` nimmt Sockets oder Ausnahmen in Reihenfolge entgegen."""

    def __init__(self) -> None:
        self._cond = threading.Condition()
        self._plan: deque[object] = deque()
        self.calls: list[ConnectCall] = []
        self.sockets: list[FakeSocket] = []
        self.always_fail: BaseException | None = None
        self.gate: threading.Event | None = None   # gesetzt: `connect` wartet darauf (≤ 5 s)
        self.auto_pong = True
        self.in_flight = 0            # gerade laufende `connect`-Aufrufe
        self.max_in_flight = 0

    def plan(self, *items: object) -> None:
        with self._cond:
            self._plan.extend(items)

    def __call__(self, secret: str, have: int) -> FakeSocket:
        with self._cond:
            self.calls.append(ConnectCall(secret, have, time.monotonic()))
            self.in_flight += 1
            self.max_in_flight = max(self.max_in_flight, self.in_flight)
            self._cond.notify_all()
            gate = self.gate
        if gate is not None:
            gate.wait(LIMIT_S)
        with self._cond:
            self.in_flight -= 1
            item: object
            if self._plan:
                item = self._plan.popleft()
            elif self.always_fail is not None:
                item = self.always_fail
            else:
                item = FakeSocket(auto_pong=self.auto_pong)
            if isinstance(item, BaseException):
                raise item
            assert isinstance(item, FakeSocket)
            self.sockets.append(item)
            self._cond.notify_all()
            return item

    def wait_calls(self, count: int, timeout: float = LIMIT_S) -> bool:
        with self._cond:
            return self._cond.wait_for(lambda: len(self.calls) >= count, timeout)

    def open_sockets(self) -> list[FakeSocket]:
        with self._cond:
            return [s for s in self.sockets if not s.closed_event.is_set()]

    def socket(self, index: int, timeout: float = LIMIT_S) -> FakeSocket:
        with self._cond:
            ok = self._cond.wait_for(lambda: len(self.sockets) > index, timeout)
            assert ok, f"Socket {index} wurde nie geöffnet"
            return self.sockets[index]
