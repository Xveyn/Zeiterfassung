"""Periodischer Reservierungs-Erinnerungs-Check auf dem Tk-Thread.

Dünne Naht über die pure Logik in src/reminders.py: liest heutige
Reservierungen + Ist-Zeiten, ermittelt fällige Toasts (upcoming/missed) und
schickt sie über das Tray-Icon. Das Scheduling nutzt root.after; die eigentliche
Entscheidung liegt in reminders.due_reminders (Tk-frei, testbar). poll() enthält
die gesamte testbare Logik und braucht keinen Event-Loop.
"""
import datetime
import logging

from src import reminders

log = logging.getLogger(__name__)

_INITIAL_DELAY_MS = 2000   # erster Tick zeitnah — fängt 'App startet nach Ende'.
_INTERVAL_MS = 60_000      # danach minütlich.


class ReminderScheduler:
    def __init__(self, root, settings, storage, reservation_store, get_tray,
                 now_provider=datetime.datetime.now):
        self._root = root
        self._settings = settings
        self._storage = storage
        self._reservation_store = reservation_store
        self._get_tray = get_tray
        self._now = now_provider
        self._after_id = None
        self._fired = set()
        self._fired_date = None

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
            log.exception("Reminder-Tick fehlgeschlagen")
        finally:
            self._after_id = self._root.after(_INTERVAL_MS, self._tick)

    def poll(self, now_dt):
        """Ein Durchlauf: fällige Reminder ermitteln, benachrichtigen, markieren.
        Gibt die gefeuerten Reminder zurück (für Tests). Ohne Tray: no-op."""
        tray = self._get_tray()
        if tray is None:
            return []
        today = now_dt.date().isoformat()
        if self._fired_date != today:
            self._fired.clear()
            self._fired_date = today
        reservation = self._reservation_store.get(today)
        reserved_slots = reservation.get("slots", []) if reservation else []
        entry = self._storage.get(today)
        logged = {
            (s.get("kategorie") or "").strip()
            for s in (entry.get("slots", []) if entry else [])
            if (s.get("kategorie") or "").strip()
        }
        minutes = self._settings.get("reminder_minutes_before")
        due = reminders.due_reminders(
            reserved_slots, logged, now_dt, minutes, self._fired)
        for rem in due:
            tray.notify(_toast_text(rem))
            self._fired.add(rem.key)
        return due


def _toast_text(rem):
    """Deutscher Toast-Text je Typ."""
    if rem.kind == "missed":
        return f"'{rem.kategorie}' (bis {rem.end}) heute ohne erfasste Arbeitszeit."
    return (f"Reservierung '{rem.kategorie}' endet um {rem.end} — "
            "Arbeitszeit noch nicht eingetragen.")
