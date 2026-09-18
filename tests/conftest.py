"""Gemeinsame Test-Helfer (Audit N22).

Vorher war die Ist-Zeit-Slot-Factory (`_slot`) 4× dupliziert (test_report/
test_storage/test_sync/test_weekly_limit) und der xhtml2pdf-Fake (`FakePisa`)
4× in test_report. Beide leben jetzt zentral hier.

Die Slot-Factory wird von den Aufrufern weiterhin auf ihren lokalen Namen
`_slot` aliast (`from tests.conftest import ist_slot as _slot`), damit die
vielen bestehenden Call-Sites unverändert bleiben. Reservierungs-Slots
(kategorie/gcal_event_id) und Sync-Einträge (modified_at/device_id) sind je
nur in einer Datei und bleiben dort lokal.

Dazu kommen der Kalender-Fake (`FakeCalendar`, Fixture `fake_calendar`) für
die Abgleich-Flows und `other_thread_can_acquire` für die Lock-Tests — beide
von mehreren Testdateien genutzt.
"""
import sys
import threading
import types
from unittest.mock import MagicMock

import pytest


def ist_slot(start, end, pause=0, kategorie=""):
    """Ein Ist-Zeit-Slot {start, end, pause, kategorie} für Storage-/Sync-/
    Report-/Weekly-Limit-Tests."""
    return {"start": start, "end": end, "pause": pause, "kategorie": kategorie}


def make_fake_xhtml2pdf(captured):
    """Fake für den lazy `xhtml2pdf`-Import in `report.generate_pdf` (die CI hat
    die Lib nicht). Liefert ein Mock-Modul, dessen `pisa.CreatePDF` das
    gerenderte HTML unter `captured['html']` ablegt und Erfolg (err=0) meldet.

    Nutzung:
        captured = {}
        with patch.dict("sys.modules", {"xhtml2pdf": make_fake_xhtml2pdf(captured)}):
            report.generate_pdf(...)
        assert "…" in captured["html"]
    """
    class _FakePisa:
        @staticmethod
        def CreatePDF(html_str, dest):
            captured["html"] = html_str
            return MagicMock(err=0)

    fake_mod = MagicMock()
    fake_mod.pisa = _FakePisa
    return fake_mod


def other_thread_can_acquire(lock):
    """True, wenn ein ANDERER Thread den Lock nehmen kann (= Lock frei).

    Ein RLock ist im eigenen Thread immer erneut nehmbar — ob ihn gerade
    jemand hält, sieht man nur von außen."""
    out = []

    def probe():
        got = lock.acquire(blocking=False)
        out.append(got)
        if got:
            lock.release()

    t = threading.Thread(target=probe)
    t.start()
    t.join()
    return out[0]


class FakeCalendar:
    """In-Memory-Ersatz für die Netz-Funktionen in `src.gcal`.

    Ersetzt wird nur die Grenze zu Google — `reservations_sync`,
    `vacations_sync` und die Stores laufen echt. Jede Methode trägt die
    Signatur ihres Vorbilds und prüft, dass Service und Kalender-ID aus dem
    Flow stammen; ein Aufruf mit vertauschten Argumenten fällt dadurch auf,
    statt still durchgewinkt zu werden.

    `raise_on(name, exc)` lässt einen Aufruf scheitern, `hooks[name]` führt
    vorher beliebigen Code aus (z.B. eine gleichzeitige UI-Änderung).
    """

    _FUNCTIONS = (
        "get_calendar_service", "list_app_events", "create_event",
        "update_event", "delete_event", "list_app_vacations",
        "create_vacation_event", "update_vacation_event",
    )

    def __init__(self, calendar_id="cal-1"):
        self.calendar_id = calendar_id
        self.service = object()
        self.reservation_events = []   # Form wie gcal.parse_event
        self.vacation_events = []      # Form wie gcal.parse_vacation_event
        self.calls = []
        self.created_vacations = []    # (period_id, from, to, modified_at)
        self.updated_vacations = []    # (event_id, period_id, from, to, modified_at)
        self.deleted = []              # event_ids beider Event-Typen
        self.hooks = {}
        self._next_id = 0

    def install(self, monkeypatch):
        from src import gcal
        for name in self._FUNCTIONS:
            monkeypatch.setattr(gcal, name, getattr(self, name))
        return self

    def raise_on(self, name, exc):
        def _raise():
            raise exc
        self.hooks[name] = _raise

    def _enter(self, name, service=None, calendar_id=None):
        self.calls.append(name)
        hook = self.hooks.get(name)
        if hook is not None:
            hook()
        if name != "get_calendar_service":
            assert service is self.service, f"{name}: fremdes Service-Objekt"
            assert calendar_id == self.calendar_id, f"{name}: Kalender {calendar_id!r}"

    def _new_event_id(self):
        self._next_id += 1
        return f"evt-new-{self._next_id}"

    def get_calendar_service(self, credentials_path="credentials.json",
                             token_path="token.json", sync_enabled=False,
                             interactive=True):
        self._enter("get_calendar_service")
        return self.service

    def list_app_events(self, service, calendar_id):
        self._enter("list_app_events", service, calendar_id)
        return list(self.reservation_events)

    def create_event(self, service, calendar_id, date_str, start, end,
                     kategorie, modified_at):
        self._enter("create_event", service, calendar_id)
        return self._new_event_id()

    def update_event(self, service, calendar_id, event_id, date_str, start,
                     end, kategorie, modified_at):
        self._enter("update_event", service, calendar_id)

    def delete_event(self, service, calendar_id, event_id):
        self._enter("delete_event", service, calendar_id)
        self.deleted.append(event_id)

    def list_app_vacations(self, service, calendar_id):
        self._enter("list_app_vacations", service, calendar_id)
        return list(self.vacation_events)

    def create_vacation_event(self, service, calendar_id, period_id,
                              date_from, date_to, modified_at):
        self._enter("create_vacation_event", service, calendar_id)
        self.created_vacations.append((period_id, date_from, date_to, modified_at))
        return self._new_event_id()

    def update_vacation_event(self, service, calendar_id, event_id, period_id,
                              date_from, date_to, modified_at):
        self._enter("update_vacation_event", service, calendar_id)
        self.updated_vacations.append(
            (event_id, period_id, date_from, date_to, modified_at))


@pytest.fixture
def fake_calendar(monkeypatch):
    """Ein installierter `FakeCalendar` ohne Events (Kalender-ID `cal-1`)."""
    return FakeCalendar().install(monkeypatch)


# --- Schlüsselbund (Keyring) -------------------------------------------------------

class FakeKeyring:
    """Stand-in für das `keyring`-Paket. `keyring_store` importiert `keyring`
    lazy in den Funktionen — ein Modul in sys.modules ersetzt also das echte
    Backend vollständig. Kein Test darf Einträge im Anmeldeinformations-
    manager / in der Keychain des Entwicklerrechners hinterlassen."""

    def __init__(self, working=True, block=None, lie=False):
        self.working = working
        self.block = block          # threading.Event: blockiert bis gesetzt
        self.lie = lie              # get_password liefert einen falschen Wert
        self.store = {}

    def _guard(self):
        if self.block is not None:
            self.block.wait()
        if not self.working:
            raise RuntimeError("No recommended backend was available")

    def set_password(self, service, account, password):
        self._guard()
        self.store[(service, account)] = password

    def get_password(self, service, account):
        self._guard()
        value = self.store.get((service, account))
        if self.lie and value is not None:
            return value + "-verfälscht"
        return value

    def delete_password(self, service, account):
        self._guard()
        del self.store[(service, account)]


def _install_fake_keyring(monkeypatch, fake):
    module = types.ModuleType("keyring")
    module.set_password = fake.set_password
    module.get_password = fake.get_password
    module.delete_password = fake.delete_password
    monkeypatch.setitem(sys.modules, "keyring", module)
    return fake


def _clear_keyring_cache():
    from src import keyring_store
    if hasattr(keyring_store, "_known"):
        keyring_store._known.clear()


@pytest.fixture(autouse=True)
def _no_os_keyring(monkeypatch):
    """Standard für JEDEN Test: kein Schlüsselbund verfügbar — alle Pfade
    verhalten sich wie heute ohne Schlüsselbund (Datei), und ein Entwickler
    mit installiertem `keyring` schreibt beim Testlauf nichts in seinen
    echten Schlüsselbund. Der Prozess-Cache von `keyring_store` wird
    geleert, damit kein Test Werte eines anderen sieht."""
    _clear_keyring_cache()
    _install_fake_keyring(monkeypatch, FakeKeyring(working=False))


@pytest.fixture
def fake_keyring(monkeypatch):
    def _install(working=True, block=None, lie=False):
        _clear_keyring_cache()
        return _install_fake_keyring(
            monkeypatch, FakeKeyring(working=working, block=block, lie=lie))
    return _install


# --- Google-Anmeldung: Token-Zustände und Consent-Stolperdraht ---------------
#
# Anders als `FakeCalendar` ersetzen diese Helfer NICHT die Service-Builder
# (`gcal.get_calendar_service`, `drive.get_drive_service`), sondern nur, was
# darunter liegt: das Laden des Tokens, den Consent-Flow und `build`. Die
# Entscheidung „Flow starten oder Auth-Fehler" läuft damit echt.

class FakeGoogleCreds:
    """Die Attribute, die die Service-Builder an echten Credentials lesen."""

    def __init__(self, *, valid, expired, refresh_error=None):
        self.valid = valid
        self.expired = expired
        self.refresh_token = "refresh-1"
        self.refreshed = False
        self._refresh_error = refresh_error

    def refresh(self, request):
        if self._refresh_error is not None:
            raise self._refresh_error
        self.valid, self.expired, self.refreshed = True, False, True

    def to_json(self):
        return '{"token": "refreshed"}'


def install_existing_token(monkeypatch, tmp_path, creds, scopes):
    """Legt credentials.json und ein token.json mit `scopes` an; das Laden
    des Tokens liefert `creds`. Liefert (credentials_path, token_path)."""
    import json

    from google.oauth2 import credentials as credentials_mod

    creds_path = tmp_path / "credentials.json"
    creds_path.write_text("{}", encoding="utf-8")
    token_path = tmp_path / "token.json"
    token_path.write_text(json.dumps({"token": "t", "scopes": list(scopes)}),
                          encoding="utf-8")
    # drive.py bindet `Credentials` beim Import — es ist dieselbe Klasse, das
    # Attribut an ihr zu ersetzen trifft also beide Builder.
    monkeypatch.setattr(credentials_mod.Credentials, "from_authorized_user_file",
                        staticmethod(lambda path, scopes: creds))
    return str(creds_path), str(token_path)


def revoked_google_creds():
    """Credentials, deren Refresh-Token Google widerrufen hat — der Zustand
    aus Xveyn#129 (`invalid_grant` bei jedem Start)."""
    from google.auth.exceptions import RefreshError

    return FakeGoogleCreds(
        valid=False, expired=True,
        refresh_error=RefreshError("invalid_grant: Token has been expired or revoked."))


def forbid_consent_flow(monkeypatch):
    """Lässt jeden Start des Browser-Consents sofort scheitern — in gcal
    (lazy importiert) wie in drive (beim Import gebunden)."""
    import google_auth_oauthlib.flow as flow_mod

    from src import drive

    class _Tripwire:
        @staticmethod
        def from_client_secrets_file(*a, **k):
            raise AssertionError("OAuth-Flow gestartet — genau das soll nicht passieren")

    monkeypatch.setattr(flow_mod, "InstalledAppFlow", _Tripwire)
    monkeypatch.setattr(drive, "InstalledAppFlow", _Tripwire)


def fake_google_build(monkeypatch):
    """Ersetzt discovery.build; liefert das Dict, in dem der Aufruf landet."""
    import googleapiclient.discovery as disc

    from src import drive

    built = {}

    def build(name, version, credentials=None):
        built.update(name=name, version=version, credentials=credentials)
        return "SERVICE"

    monkeypatch.setattr(disc, "build", build)
    monkeypatch.setattr(drive, "build", build)
    return built
