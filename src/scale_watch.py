# pyright: reportOptionalMemberAccess=true
"""Periodischer Check, ob die Desktop-Skalierung noch zum Start passt
(Xveyn#201). Tk-frei: `root.after` kommt als Objekt herein.

Der Faktor gilt bis zum Neustart (s. `src/dpi.py`); wechselt der Nutzer den
Monitor, passt die UI nicht mehr. Gemeldet werden nur Zustandswechsel, damit
der Aufrufer einen Hinweis zeigen und wieder entfernen kann."""

import logging
from typing import Any, Callable, Optional

log = logging.getLogger(__name__)

_INTERVAL_MS = 5000

# Frühestens so lange nach dem Start darf die App sich selbst neu starten:
# flattert `Xft.dpi`, wäre es sonst eine Neustart-Schleife.
MIN_UPTIME_S = 60


def may_auto_restart(enabled: bool, mismatch: bool, dialog_open: bool,
                     bg_busy: bool, uptime_s: float) -> bool:
    """Ob der automatische Neustart jetzt laufen darf: Schalter an, die
    Skalierung passt nicht, nichts offen oder in Arbeit, App lange genug
    oben. Nie mitten in der Arbeit — sonst bleibt es beim Banner."""
    return (enabled and mismatch and not dialog_open and not bg_busy
            and uptime_s >= MIN_UPTIME_S)


class ScaleWatcher:
    def __init__(self, root: Any, changed: Callable[[], bool],
                 on_change: Callable[[bool], None],
                 interval_ms: int = _INTERVAL_MS) -> None:
        self._root = root
        self._changed = changed
        self._on_change = on_change
        self._interval_ms = interval_ms
        self._after_id: Optional[str] = None
        self._mismatch = False

    def start(self) -> None:
        """Plant den ersten Tick. Idempotent."""
        if self._after_id is None:
            self._after_id = self._root.after(self._interval_ms, self._tick)

    def stop(self) -> None:
        """Bricht den geplanten Tick ab. Idempotent."""
        if self._after_id is not None:
            try:
                self._root.after_cancel(self._after_id)
            except Exception:
                # Die ID kann längst abgelaufen sein (Root zerstört); das
                # Ziel, kein Tick mehr, ist so oder so erreicht.
                log.debug("after_cancel fehlgeschlagen", exc_info=True)
            self._after_id = None

    def poll(self) -> None:
        """Prüft einmal und meldet, wenn sich der Zustand geändert hat."""
        mismatch = bool(self._changed())
        if mismatch != self._mismatch:
            self._mismatch = mismatch
            self._on_change(mismatch)

    def _tick(self) -> None:
        self._after_id = None
        try:
            self.poll()
        except Exception:
            log.exception("Skalierungs-Check fehlgeschlagen")
        finally:
            self.start()
