"""Periodischer Reservierungs-Erinnerungs-Check auf dem Tk-Thread.

Dünne Naht über die pure Logik in src/reminders.py: liest heutige
Reservierungen + Ist-Zeiten, ermittelt fällige Toasts (upcoming/missed) und
schickt sie über das Tray-Icon. Das Scheduling nutzt root.after; die eigentliche
Entscheidung liegt in reminders.due_reminders (Tk-frei, testbar). poll() enthält
die gesamte testbare Logik und braucht keinen Event-Loop.
"""
import contextlib
import datetime
import logging

from src import reminders
from src.settings import WEEKDAY_KEYS

log = logging.getLogger(__name__)

_INITIAL_DELAY_MS = 2000   # erster Tick zeitnah — fängt 'App startet nach Ende'.
_INTERVAL_MS = 60_000      # danach minütlich.


class ReminderScheduler:
    def __init__(self, root, settings, storage, reservation_store, get_tray,
                 now_provider=datetime.datetime.now, data_lock=None,
                 on_logged=None, marshal=None):
        self._root = root
        self._settings = settings
        self._storage = storage
        self._reservation_store = reservation_store
        self._get_tray = get_tray
        self._now = now_provider
        self._after_id = None
        self._fired = set()
        self._fired_date = None
        self._data_lock = data_lock if data_lock is not None else contextlib.nullcontext()
        self._on_logged = on_logged
        # marshal schiebt den WinRT-Callback TclError-sicher auf den Tk-Thread
        # (= App._marshal_to_ui). Default (Tests): inline ausführen.
        self._marshal = marshal if marshal is not None else (lambda fn: fn())

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
            res_slot = {"start": rem.key[1], "end": rem.key[2], "kategorie": rem.kategorie}
            tray.notify_action(
                _toast_text(rem), "Zeiterfassung",
                "Arbeitszeit eintragen", self._make_log_action(today, res_slot))
            self._fired.add(rem.key)
        return due

    def _make_log_action(self, today, res_slot):
        """0-arg-Callback für den Toast-Button. Läuft auf dem WinRT-Hintergrund-
        thread und marshallt via self._marshal (= App._marshal_to_ui) TclError-
        sicher auf den Tk-Thread — NICHT roh via root.after (das umginge den
        doppelten TclError-Schutz, wenn das Fenster beim Klick schon zu ist)."""
        return lambda: self._marshal(
            lambda: self._log_reservation(today, res_slot))

    def _log_reservation(self, today, res_slot):
        """Trägt den Reservierungs-Slot als Ist-Zeit ein (an heutige Slots
        angehängt) und stößt den UI-Refresh an. Read-modify-write unter data_lock."""
        category_times = self._settings.get("category_times") or {}
        default_pause = self._settings.get("default_pause")
        weekday_key = WEEKDAY_KEYS[datetime.date.fromisoformat(today).weekday()]
        ist_slot = reminders.ist_slot_from_reservation(
            res_slot, category_times, weekday_key, default_pause)
        try:
            with self._data_lock:
                entry = self._storage.get(today)
                slots = list(entry.get("slots", [])) if entry else []
                slots.append(ist_slot)
                self._storage.save(today, slots)
        except Exception:
            log.exception("Arbeitszeit aus Toast-Button eintragen fehlgeschlagen")
            return
        if self._on_logged is not None:
            self._on_logged()


def _toast_text(rem):
    """Deutscher Toast-Text je Typ."""
    if rem.kind == "missed":
        return f"'{rem.kategorie}' (bis {rem.end}) heute ohne erfasste Arbeitszeit."
    return (f"Reservierung '{rem.kategorie}' endet um {rem.end} — "
            "Arbeitszeit noch nicht eingetragen.")
