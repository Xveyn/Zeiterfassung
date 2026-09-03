"""Periodischer Sende-Reminder-Check auf dem Tk-Thread.

Dünne Naht über die pure Logik in src/send_reminder.py: prüft minütlich, ob
einer von zwei Kanälen fällig ist, und schickt ggf. einen Toast über das
Tray-Icon.

- **Monatlicher Kanal**: der konfigurierte Tag/Uhrzeit für "Arbeitszeiten
  verschicken" ist erreicht. Der zuletzt benachrichtigte Monat wird in
  settings persistiert (send_reminder_last_fired_month), damit der Toast über
  App-Neustarts hinweg nur einmal pro Monat erscheint.
- **Tagesbezogener Kanal**: eine heutige Reservierung mit gesetztem
  `send_reminder_minutes` läuft in Kürze aus. Nur aktiv, wenn sowohl
  `send_reminder_reservations_enabled` als auch `gcal_enabled` gesetzt sind
  (ohne Kalender-Abgleich zeigt die App gar keine Reservierungen an, ein
  Toast dafür wäre nicht nachvollziehbar). Der Fired-Zustand lebt nur im
  Speicher und wird tageweise zurückgesetzt (analog `ReminderScheduler`) —
  ein persistierter Marker müsste in reservations.json landen und würde dort
  `modified_at` anfassen, was einen gcal-Push auslöst.
"""
import datetime
import logging

from src import send_reminder
from src.time_utils import MONTHS_DE

log = logging.getLogger(__name__)

_INITIAL_DELAY_MS = 2000   # erster Tick zeitnah — fängt 'App startet nach Fällig-Zeitpunkt'.
_INTERVAL_MS = 60_000      # danach minütlich.


class SendReminderScheduler:
    def __init__(self, root, settings, get_tray, reservation_store=None,
                 now_provider=datetime.datetime.now):
        self._root = root
        self._settings = settings
        self._get_tray = get_tray
        self._reservation_store = reservation_store
        self._now = now_provider
        self._after_id = None
        # Tagesbezogener Kanal: Dedup nur im Speicher, tageweise
        # zurückgesetzt (Muster von ReminderScheduler). Ein persistierter
        # Marker müsste in reservations.json landen und würde dort
        # modified_at anfassen — das löst einen gcal-Push aus.
        self._day_fired = False
        self._day_fired_date = None

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
                # Die ID kann laengst abgelaufen sein (Tick gefeuert,
                # Root zerstoert) — after_cancel wirft dann. `stop()` ist
                # idempotent, das Ziel (kein geplanter Tick mehr) ist so
                # oder so erreicht.
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
        """Ein Durchlauf über beide Kanäle: monatlicher Termin und
        tagesbezogene Erinnerung. Gibt True zurück, wenn mindestens einer
        benachrichtigt hat (für Tests). Ohne Tray: no-op."""
        tray = self._get_tray()
        if tray is None:
            return False
        fired_monthly = self._poll_monthly(now_dt, tray)
        fired_day = self._poll_day(now_dt, tray)
        return fired_monthly or fired_day

    def _poll_monthly(self, now_dt, tray):
        day = self._settings.get("send_reminder_day")
        time_str = self._settings.get("send_reminder_time")
        last_fired = self._settings.get("send_reminder_last_fired_month")
        shift_mode = self._settings.get("send_reminder_weekend_shift")
        free_dates = (
            send_reminder.free_dates_for_month(
                now_dt.year, now_dt.month, self._settings.get("state"),
                bool(self._settings.get("send_reminder_shift_holidays")))
            if shift_mode in ("backward", "forward") else frozenset()
        )
        if not send_reminder.is_due(now_dt, day, time_str, last_fired,
                                    shift_mode, free_dates):
            return False
        tray.notify(_toast_text(now_dt))
        self._settings.set(
            "send_reminder_last_fired_month",
            f"{now_dt.year:04d}-{now_dt.month:02d}",
        )
        return True

    def _poll_day(self, now_dt, tray):
        """Tagesbezogener Kanal. Verlangt zusätzlich zum Haupt-Schalter die
        Option „Reservierungen" UND einen aktiven Kalender-Abgleich: ohne
        gcal_enabled zeigt die App gar keine Reservierungen an
        (App._reservations_active), ein Toast dafür wäre nicht nachvollziehbar."""
        if self._reservation_store is None:
            return False
        if not (self._settings.get("send_reminder_reservations_enabled")
                and self._settings.get("gcal_enabled")):
            return False
        today = now_dt.date().isoformat()
        if self._day_fired_date != today:
            self._day_fired = False
            self._day_fired_date = today
        if self._day_fired:
            return False
        reservation = self._reservation_store.get(today)
        slots = reservation.get("slots", []) if reservation else []
        rem = send_reminder.due_day_reminder(slots, now_dt)
        if rem is None:
            return False
        tray.notify(_day_toast_text(rem))
        self._day_fired = True
        return True


def _toast_text(now_dt):
    """Deutscher Toast-Text mit dem aktuellen Monat."""
    return f"Zeit, deine Arbeitszeiten für {MONTHS_DE[now_dt.month]} zu verschicken."


def _day_toast_text(rem):
    """Deutscher Toast-Text für die tagesbezogene Erinnerung."""
    return (f"Reservierung endet um {rem.end} — Zeit, deine Arbeitszeiten "
            "zu verschicken.")
