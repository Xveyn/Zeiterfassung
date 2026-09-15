import json
from unittest.mock import MagicMock

import pytest

from src import gcal
from src.mail import get_scopes


def test_event_payload_has_summary_and_marker():
    body = gcal.event_payload("2026-06-01", "09:00", "17:00", "", "2026-05-20T10:00:00Z")
    assert body["summary"] == gcal.EVENT_SUMMARY
    private = body["extendedProperties"]["private"]
    assert private[gcal.APP_MARKER_KEY] == gcal.APP_MARKER_VALUE
    assert private["kategorie"] == ""
    assert private["modified_at"] == "2026-05-20T10:00:00Z"


def test_event_payload_summary_includes_kategorie():
    body = gcal.event_payload("2026-06-01", "09:00", "17:00", "Büro", "2026-05-20T10:00:00Z")
    assert body["summary"] == f"{gcal.EVENT_SUMMARY} — Büro"
    assert body["extendedProperties"]["private"]["kategorie"] == "Büro"


def test_event_payload_datetime_encodes_date_and_time():
    body = gcal.event_payload("2026-06-01", "09:30", "17:45", "", "2026-05-20T10:00:00Z")
    assert body["start"]["dateTime"].startswith("2026-06-01T09:30:00")
    assert body["end"]["dateTime"].startswith("2026-06-01T17:45:00")


def test_parse_event_roundtrips_payload_with_kategorie():
    body = gcal.event_payload("2026-06-01", "09:00", "17:00", "Büro", "2026-05-20T10:00:00Z")
    body["id"] = "ev-42"
    parsed = gcal.parse_event(body)
    assert parsed == {
        "date": "2026-06-01", "start": "09:00", "end": "17:00",
        "kategorie": "Büro", "modified_at": "2026-05-20T10:00:00Z", "event_id": "ev-42",
    }


def test_parse_event_missing_kategorie_defaults_empty():
    # Event ohne kategorie-Property (z.B. von einer älteren App-Version)
    body = {
        "id": "ev-1",
        "start": {"dateTime": "2026-06-01T09:00:00+02:00"},
        "end": {"dateTime": "2026-06-01T17:00:00+02:00"},
        "extendedProperties": {"private": {
            gcal.APP_MARKER_KEY: gcal.APP_MARKER_VALUE,
            "modified_at": "2026-05-20T10:00:00Z",
        }},
    }
    assert gcal.parse_event(body)["kategorie"] == ""


def test_parse_event_ignores_non_app_events():
    foreign = {"id": "x", "start": {"dateTime": "2026-06-01T09:00:00+02:00"},
               "end": {"dateTime": "2026-06-01T17:00:00+02:00"}}
    assert gcal.parse_event(foreign) is None


def test_parse_event_ignores_all_day_events():
    all_day = {
        "id": "x",
        "start": {"date": "2026-06-01"}, "end": {"date": "2026-06-02"},
        "extendedProperties": {"private": {gcal.APP_MARKER_KEY: gcal.APP_MARKER_VALUE}},
    }
    assert gcal.parse_event(all_day) is None


def test_parse_event_ignores_event_with_null_extended_properties():
    ev = {"id": "x", "extendedProperties": None,
          "start": {"dateTime": "2026-06-01T09:00:00+02:00"},
          "end": {"dateTime": "2026-06-01T17:00:00+02:00"}}
    assert gcal.parse_event(ev) is None


class _FakeExec:
    def __init__(self, result):
        self._result = result

    def execute(self):
        return self._result


class _FakeEvents:
    def __init__(self, recorder, list_result):
        self._recorder = recorder
        self._list_result = list_result

    def list(self, **kwargs):
        self._recorder.append(("list", kwargs))
        return _FakeExec(self._list_result)

    def insert(self, **kwargs):
        self._recorder.append(("insert", kwargs))
        return _FakeExec({"id": "created-id"})

    def update(self, **kwargs):
        self._recorder.append(("update", kwargs))
        return _FakeExec({"id": kwargs.get("eventId")})

    def delete(self, **kwargs):
        self._recorder.append(("delete", kwargs))
        return _FakeExec({})


class _FakeService:
    def __init__(self, recorder, list_result=None):
        self._recorder = recorder
        self._events = _FakeEvents(recorder, list_result or {"items": []})

    def events(self):
        return self._events


def test_list_app_events_filters_and_parses():
    body = gcal.event_payload("2026-06-01", "09:00", "17:00", "", "2026-05-20T10:00:00Z")
    body["id"] = "ev-1"
    foreign = {"id": "ev-2", "start": {"dateTime": "2026-06-02T09:00:00+02:00"},
               "end": {"dateTime": "2026-06-02T17:00:00+02:00"}}
    recorder = []
    service = _FakeService(recorder, {"items": [body, foreign]})

    events = gcal.list_app_events(service, "cal-1")

    assert len(events) == 1
    assert events[0]["event_id"] == "ev-1"
    _, kwargs = recorder[0]
    assert kwargs["privateExtendedProperty"] == "zeiterfassung=reservation"
    assert kwargs["calendarId"] == "cal-1"


def test_create_event_returns_event_id():
    recorder = []
    service = _FakeService(recorder)
    event_id = gcal.create_event(
        service, "cal-1", "2026-06-01", "09:00", "17:00", "Büro", "2026-05-20T10:00:00Z")
    assert event_id == "created-id"
    assert recorder[0][0] == "insert"
    assert recorder[0][1]["body"]["extendedProperties"]["private"]["kategorie"] == "Büro"


def test_update_event_sends_kategorie():
    recorder = []
    service = _FakeService(recorder)
    gcal.update_event(
        service, "cal-1", "ev-1", "2026-06-01", "09:00", "17:00", "HO", "2026-05-20T10:00:00Z")
    assert recorder[0][0] == "update"
    assert recorder[0][1]["eventId"] == "ev-1"
    assert recorder[0][1]["body"]["extendedProperties"]["private"]["kategorie"] == "HO"


def test_delete_event_swallows_already_gone():
    class _GoneResp:
        status = 410

    class _GoneService:
        def events(self):
            class _E:
                def delete(self, **kwargs):
                    class _Boom:
                        def execute(self_):  # pyright: ignore[reportSelfClsParameterName]  # self_ bewusst gegen Shadowing
                            err = Exception("gone")
                            err.resp = _GoneResp()
                            raise err
                    return _Boom()
            return _E()

    gcal.delete_event(_GoneService(), "cal-1", "ev-x")


def test_list_app_vacations_filters_on_the_vacation_marker():
    """Der serverseitige Filter ist die Trennung: bekäme der Reservierungs-
    Pull Urlaubs-Events zurück, könnte sein Reconcile sie als verwaiste
    App-Events löschen."""
    service = MagicMock()
    service.events.return_value.list.return_value.execute.return_value = {
        "items": [], "nextPageToken": None}
    gcal.list_app_vacations(service, "cal-1")
    kwargs = service.events.return_value.list.call_args.kwargs
    assert kwargs["privateExtendedProperty"] == "zeiterfassung=vacation"


def test_reservation_parser_rejects_a_vacation_event():
    ev = {**gcal.vacation_event_payload("a", "2026-07-01", "2026-07-03",
                                        "2026-08-30T10:00:00Z"), "id": "x"}
    assert gcal.parse_event(ev) is None


def test_vacation_parser_rejects_a_reservation_event():
    ev = {**gcal.event_payload("2026-07-01", "08:00", "16:00", "",
                               "2026-08-30T10:00:00Z"), "id": "x"}
    assert gcal.parse_vacation_event(ev) is None


# --- get_calendar_service: interactive=False startet keinen Browser -------

def test_calendar_service_non_interactive_without_token_raises_auth_error(tmp_path):
    """Ohne brauchbaren Token gibt es im nicht-interaktiven Modus nur den
    Fehler — kein `flow.run_local_server`, das ungefragt den Browser aufreißt."""
    with pytest.raises(gcal.CalendarAuthError):
        gcal.get_calendar_service(
            str(tmp_path / "credentials.json"),
            str(tmp_path / "token.json"),
            interactive=False,
        )


def test_calendar_service_non_interactive_never_starts_the_oauth_flow(monkeypatch, tmp_path):
    """Scharfe Variante: credentials.json IST da (der FileNotFoundError greift
    also nicht) und der Flow würde sofort auffliegen, wenn er liefe."""
    creds = tmp_path / "credentials.json"
    creds.write_text("{}", encoding="utf-8")

    import google_auth_oauthlib.flow as flow_mod

    class _Tripwire:
        @staticmethod
        def from_client_secrets_file(*a, **k):
            raise AssertionError("OAuth-Flow gestartet — genau das soll nicht passieren")

    monkeypatch.setattr(flow_mod, "InstalledAppFlow", _Tripwire)

    with pytest.raises(gcal.CalendarAuthError):
        gcal.get_calendar_service(str(creds), str(tmp_path / "token.json"),
                                  interactive=False)


def test_calendar_service_interactive_still_runs_the_flow(monkeypatch, tmp_path):
    """Der Default bleibt interaktiv — der Kalender-Schalter lebt davon."""
    creds = tmp_path / "credentials.json"
    creds.write_text("{}", encoding="utf-8")

    import google_auth_oauthlib.flow as flow_mod
    import googleapiclient.discovery as disc
    from src import oauth_utils

    started = []

    class _Flow:
        @staticmethod
        def from_client_secrets_file(*a, **k):
            started.append(True)
            return _Flow()

        def run_local_server(self, port=0):
            return "CREDS"

    monkeypatch.setattr(flow_mod, "InstalledAppFlow", _Flow)
    monkeypatch.setattr(oauth_utils, "write_token", lambda *a, **k: None)
    monkeypatch.setattr(gcal, "write_token", lambda *a, **k: None)
    monkeypatch.setattr(disc, "build", lambda *a, **k: "SERVICE")

    assert gcal.get_calendar_service(str(creds), str(tmp_path / "token.json")) == "SERVICE"
    assert started == [True]


# --- get_calendar_service: vorhandener, aber nicht (mehr) tragender Token ---
#
# Die Tests oben decken "kein token.json". Der Fall aus Xveyn#124 war aber
# ein token.json, das DA ist und nicht mehr trägt — widerrufen, abgelaufen
# oder mit zu wenigen Scopes. Genau diese Zweige laufen vor der
# interactive-Weiche und entscheiden, ob sie überhaupt erreicht wird.

class _FakeCreds:
    """Die Attribute, die get_calendar_service an echten Credentials liest."""

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


def _existing_token(monkeypatch, tmp_path, creds, scopes):
    """Legt credentials.json und ein token.json mit `scopes` an; das Laden
    des Tokens liefert `creds`. Liefert (credentials_path, token_path)."""
    from google.oauth2 import credentials as credentials_mod

    creds_path = tmp_path / "credentials.json"
    creds_path.write_text("{}", encoding="utf-8")
    token_path = tmp_path / "token.json"
    token_path.write_text(json.dumps({"token": "t", "scopes": list(scopes)}),
                          encoding="utf-8")
    monkeypatch.setattr(credentials_mod.Credentials, "from_authorized_user_file",
                        staticmethod(lambda path, scopes: creds))
    return str(creds_path), str(token_path)


def _forbid_consent_flow(monkeypatch):
    import google_auth_oauthlib.flow as flow_mod

    class _Tripwire:
        @staticmethod
        def from_client_secrets_file(*a, **k):
            raise AssertionError("OAuth-Flow gestartet — genau das soll nicht passieren")

    monkeypatch.setattr(flow_mod, "InstalledAppFlow", _Tripwire)


def _fake_build(monkeypatch):
    """Ersetzt discovery.build; liefert das Dict, in dem der Aufruf landet."""
    import googleapiclient.discovery as disc

    built = {}

    def build(name, version, credentials=None):
        built.update(name=name, version=version, credentials=credentials)
        return "SERVICE"

    monkeypatch.setattr(disc, "build", build)
    return built


_CALENDAR_SCOPES = get_scopes(False, gcal_enabled=True)


def test_calendar_service_non_interactive_with_revoked_refresh_token_raises_auth_error(
        monkeypatch, tmp_path):
    """Widerrufener Refresh-Token: `RefreshError` wird zum Auth-Fall — und der
    darf beim bloßen Öffnen der Einstellungen keinen Browser starten."""
    from google.auth.exceptions import RefreshError

    creds = _FakeCreds(valid=False, expired=True,
                       refresh_error=RefreshError("invalid_grant"))
    creds_path, token_path = _existing_token(monkeypatch, tmp_path, creds,
                                             _CALENDAR_SCOPES)
    _forbid_consent_flow(monkeypatch)
    _fake_build(monkeypatch)

    with pytest.raises(gcal.CalendarAuthError):
        gcal.get_calendar_service(creds_path, token_path, interactive=False)


def test_calendar_service_refreshes_expired_token_without_consent(monkeypatch, tmp_path):
    """Trägt der Refresh-Token noch, erneuert der Service still, schreibt
    den erneuerten Token zurück und baut mit genau diesen Credentials."""
    creds = _FakeCreds(valid=False, expired=True)
    creds_path, token_path = _existing_token(monkeypatch, tmp_path, creds,
                                             _CALENDAR_SCOPES)
    _forbid_consent_flow(monkeypatch)
    built = _fake_build(monkeypatch)
    written = []
    monkeypatch.setattr(gcal, "write_token",
                        lambda c, path: written.append((c, path)))

    service = gcal.get_calendar_service(creds_path, token_path, interactive=False)

    assert service == "SERVICE"
    assert creds.refreshed is True
    assert built == {"name": "calendar", "version": "v3", "credentials": creds}
    assert written == [(creds, token_path)]


def test_calendar_service_network_error_during_refresh_propagates_without_flow(
        monkeypatch, tmp_path):
    """Offline ist kein Auth-Problem: ein `TransportError` beim Refresh fliegt
    durch, statt selbst im interaktiven Modus einen Consent-Flow zu starten,
    der ohne Netz ohnehin scheitert."""
    from google.auth.exceptions import TransportError

    creds = _FakeCreds(valid=False, expired=True,
                       refresh_error=TransportError("no route to host"))
    creds_path, token_path = _existing_token(monkeypatch, tmp_path, creds,
                                             _CALENDAR_SCOPES)
    _forbid_consent_flow(monkeypatch)
    _fake_build(monkeypatch)

    with pytest.raises(TransportError):
        gcal.get_calendar_service(creds_path, token_path, interactive=True)


def test_calendar_service_non_interactive_token_without_calendar_scope_raises_auth_error(
        monkeypatch, tmp_path):
    """Ein gültiger Token ohne Kalender-Scope trägt für den Kalender nicht:
    ohne die Scope-Prüfung käme ein Service zurück, dessen erster Aufruf mit
    403 scheitert — statt des Auth-Falls, den die Statuszeile anzeigen kann."""
    creds = _FakeCreds(valid=True, expired=False)
    gmail_only = get_scopes(False, gcal_enabled=False)
    creds_path, token_path = _existing_token(monkeypatch, tmp_path, creds, gmail_only)
    _forbid_consent_flow(monkeypatch)
    _fake_build(monkeypatch)

    with pytest.raises(gcal.CalendarAuthError):
        gcal.get_calendar_service(creds_path, token_path, interactive=False)
