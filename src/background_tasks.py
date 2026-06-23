"""Hintergrund-Tasks der App (Token-Refresh, Sender-Email, Update-Check,
Kalender-Reconcile) und die gemeinsame Thread-Mechanik.

Tk-frei und ohne Google-Imports auf Modulebene: `run_calendar_reconcile`
wird lazy in der Methode importiert (Circular-Import-Schutz — src.main zieht
App aus src.ui). UI-Arbeit (Dialoge, Banner, Refresh) macht die Klasse nicht
selbst, sondern liefert Ergebnisse ueber `marshal` an Callbacks der App.
"""

import logging
import threading

log = logging.getLogger(__name__)


class BackgroundTaskRunner:
    def __init__(self, marshal, settings, base_path, reservation_store,
                 reservations_active):
        self._marshal = marshal                          # App._marshal_to_ui
        self._settings = settings
        self._base_path = base_path
        self._reservation_store = reservation_store
        self._reservations_active = reservations_active  # callable -> bool

    def run(self, fn, on_done=None):
        """Fuehrt fn() in einem Daemon-Thread aus und liefert dessen Rueckgabe
        via marshal an on_done auf dem UI-Thread."""
        def worker():
            result = fn()
            if on_done is not None:
                self._marshal(lambda: on_done(result))
        threading.Thread(target=worker, daemon=True).start()
