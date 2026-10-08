"""Thread-sichere Übergabe von Callbacks an den UI-Thread (Tk-frei).

Worker dürfen `root.after` nicht aufrufen, solange die Mainloop nicht läuft
(`RuntimeError: main thread is not in main loop`, Xveyn#244). Sie legen ihre
Callbacks deshalb hier ab; der UI-Thread leert die Queue per Poll."""
import logging
import queue
from typing import Callable

log = logging.getLogger(__name__)

POLL_MS = 50


class UiQueue:
    def __init__(self) -> None:
        self._q: "queue.SimpleQueue[Callable[[], None]]" = queue.SimpleQueue()
        self._running = False

    def put(self, fn: Callable[[], None]) -> None:
        self._q.put(fn)

    def drain(self) -> None:
        while True:
            try:
                fn = self._q.get_nowait()
            except queue.Empty:
                return
            try:
                fn()
            except Exception:
                log.exception("UI-Callback fehlgeschlagen")

    def start(self, schedule: Callable[[int, Callable[[], None]], object]) -> None:
        """Startet den Poll auf dem UI-Thread. `schedule(ms, fn)` ist `root.after`."""
        self._running = True

        def poll() -> None:
            if not self._running:
                return
            self.drain()
            try:
                schedule(POLL_MS, poll)
            except Exception:
                # Tk bereits zerstört: der Poll endet, es gibt nichts mehr zu tun.
                self._running = False
                log.debug("UI-Poll beendet (Scheduler nicht mehr verfügbar)",
                          exc_info=True)

        poll()

    def stop(self) -> None:
        self._running = False
