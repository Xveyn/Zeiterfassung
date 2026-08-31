from unittest.mock import MagicMock

from src import gcal


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
