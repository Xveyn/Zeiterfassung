"""Hintergrund-Tasks der App (Token-Refresh, Sender-Email, Update-Check,
Kalender-Reconcile) und die gemeinsame Thread-Mechanik.

Tk-frei und ohne Google-Imports auf Modulebene: `run_calendar_reconcile`
wird lazy in der Methode importiert (Circular-Import-Schutz — src.main zieht
App aus src.ui). UI-Arbeit (Dialoge, Banner, Refresh) macht die Klasse nicht
selbst, sondern liefert Ergebnisse ueber `marshal` an Callbacks der App.
"""

import logging
import os
import threading
import traceback

from src.mail import fetch_user_email, refresh_token_if_needed, TokenAuthError, TokenNetworkError
from src.updater import check_latest_release, is_newer, should_check_today
from src.version import VERSION

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
                # Lokale Bindung: Pyright traegt das None-Narrowing sonst nicht
                # in die Closure (reportOptionalCall-FP).
                done = on_done
                self._marshal(lambda: done(result))
        threading.Thread(target=worker, daemon=True).start()

    def refresh_token(self, on_auth_error, on_error):
        """Erneuert den Gmail-Token beim Start im Hintergrund. Auth-Fehler ->
        on_auth_error(msg); unerwartete Fehler -> on_error(traceback);
        Netzwerkfehler werden still uebergangen (Offline-Start)."""
        token_path = os.path.join(self._base_path, "token.json")

        def fn():
            try:
                refresh_token_if_needed(
                    token_path,
                    sync_enabled=self._settings.get("sync_enabled"),
                    gcal_enabled=self._settings.get("gcal_enabled"),
                )
                return None
            except TokenAuthError as e:
                return ("auth", str(e))
            except TokenNetworkError:
                return None
            except Exception:
                log.exception("Token-Refresh fehlgeschlagen")
                return ("error", traceback.format_exc())

        def on_done(outcome):
            if outcome is None:
                return
            kind, payload = outcome
            if kind == "auth":
                on_auth_error(payload)
            else:
                on_error(payload)

        self.run(fn, on_done)

    def fetch_sender_email(self):
        """Holt einmalig pro Start die authentifizierte E-Mail ueber OAuth2-
        Userinfo und cached sie in settings.sender_email. Still bei fehlendem
        Token/Netz/Scope (der naechste Send-Dialog triggert den Re-Consent)."""
        token_path = os.path.join(self._base_path, "token.json")
        if not os.path.exists(token_path):
            return

        def fn():
            try:
                email = fetch_user_email(
                    token_path,
                    sync_enabled=self._settings.get("sync_enabled"),
                    gcal_enabled=self._settings.get("gcal_enabled"),
                )
            except Exception:
                log.exception("sender_email-Fetch fehlgeschlagen")
                return None
            return email

        def on_done(email):
            if email and email != self._settings.get("sender_email"):
                self._settings.set("sender_email", email)

        self.run(fn, on_done)

    def check_update(self, on_result):
        """Fragt 1x pro Kalendertag GitHub nach einer neueren Version. `is_newer`
        wird bereits im Worker ausgewertet, damit on_result(release, newer) im
        UI-Thread keine ungeschuetzte Logik mehr ausfuehrt. Fehler still."""
        if not should_check_today(self._settings.get("last_update_check_at")):
            return

        def fn():
            try:
                release = check_latest_release("MargenHeld/Zeiterfassung")
                if release is None:
                    return None
                return (release, is_newer(VERSION, release.version))
            except Exception:
                log.exception("Update-Check fehlgeschlagen")
                return None

        def on_done(result):
            if result is None:
                return
            release, newer = result
            on_result(release, newer)

        self.run(fn, on_done)

    def reconcile_on_start(self, on_ok):
        """Gleicht beim Start die Reservierungen mit dem Google Kalender ab.
        Fehler werden STILL geloggt (Offline-Start nicht stoeren); bei Erfolg
        on_ok() im UI-Thread."""
        if not self._reservations_active():
            return

        def fn():
            from src.main import run_calendar_reconcile  # lazy: Circular-Import-Schutz
            return run_calendar_reconcile(
                self._reservation_store, self._settings, self._base_path)

        def on_done(result):
            if result.get("ok"):
                on_ok()

        self.run(fn, on_done)

    def trigger_reconcile(self, on_done):
        """Stoesst nach einer Reservierungsaenderung den Abgleich an. Das
        Ergebnis geht IMMER an on_done(result) (User hat aktiv gespeichert und
        erwartet Feedback)."""
        if not self._reservations_active():
            return

        def fn():
            from src.main import run_calendar_reconcile  # lazy: Circular-Import-Schutz
            return run_calendar_reconcile(
                self._reservation_store, self._settings, self._base_path)

        self.run(fn, on_done)
