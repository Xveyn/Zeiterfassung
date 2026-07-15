"""Periodischer Sende-Reminder-Check auf dem Tk-Thread.

Dünne Naht über die pure Logik in src/send_reminder.py: prüft minütlich, ob
der konfigurierte Tag/Uhrzeit für "Arbeitszeiten verschicken" erreicht ist,
und schickt ggf. einen Toast über das Tray-Icon. Der zuletzt benachrichtigte
Monat wird in settings persistiert (send_reminder_last_fired_month), damit
der Toast über App-Neustarts hinweg nur einmal pro Monat erscheint.
"""
import datetime
import logging

from src import send_reminder
from src.time_utils import MONTHS_DE

log = logging.getLogger(__name__)

_INITIAL_DELAY_MS = 2000   # erster Tick zeitnah — fängt 'App startet nach Fällig-Zeitpunkt'.
_INTERVAL_MS = 60_000      # danach minütlich.


class SendReminderScheduler:
    def __init__(self, root, settings, get_tray, now_provider=datetime.datetime.now):
        self._root = root
        self._settings = settings
        self._get_tray = get_tray
        self._now = now_provider
        self._after_id = None

    def start(self):
        """Plant den ersten Tick zeitnah + danach im Intervall. Idempotent."""
        if self._after_id is not None:
            return
        self._after_id = self._root.after(_INITIAL_DELAY_MS, self._tick)

    def stop(self):
        """Bricht den geplanten Tick ab. Idempotent."""
        if self._after_id is not None:
            try:
                self._root.after_cancel(self._after_id)
            except Exception:
                pass
            self._after_id = None

    def _tick(self):
        try:
            self.poll(self._now())
        except Exception:
            log.exception("Sende-Reminder-Tick fehlgeschlagen")
        finally:
            self._after_id = self._root.after(_INTERVAL_MS, self._tick)

    def poll(self, now_dt):
        """Ein Durchlauf: Fälligkeit prüfen, ggf. benachrichtigen und den
        Monat persistieren. Gibt True zurück, wenn benachrichtigt wurde (für
        Tests). Ohne Tray: no-op."""
        tray = self._get_tray()
        if tray is None:
            return False
        day = self._settings.get("send_reminder_day")
        time_str = self._settings.get("send_reminder_time")
        last_fired = self._settings.get("send_reminder_last_fired_month")
        if not send_reminder.is_due(now_dt, day, time_str, last_fired):
            return False
        tray.notify(_toast_text(now_dt))
        self._settings.set(
            "send_reminder_last_fired_month",
            f"{now_dt.year:04d}-{now_dt.month:02d}",
        )
        return True


def _toast_text(now_dt):
    """Deutscher Toast-Text mit dem aktuellen Monat."""
    return f"Zeit, deine Arbeitszeiten für {MONTHS_DE[now_dt.month]} zu verschicken."
