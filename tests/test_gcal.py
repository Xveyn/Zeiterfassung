from src import gcal


def test_event_payload_has_summary_and_marker():
    body = gcal.event_payload("2026-06-01", "09:00", "17:00", "2026-05-20T10:00:00Z")
    assert body["summary"] == gcal.EVENT_SUMMARY
    private = body["extendedProperties"]["private"]
    assert private[gcal.APP_MARKER_KEY] == gcal.APP_MARKER_VALUE
    assert private["modified_at"] == "2026-05-20T10:00:00Z"


def test_event_payload_datetime_encodes_date_and_time():
    body = gcal.event_payload("2026-06-01", "09:30", "17:45", "2026-05-20T10:00:00Z")
    # dateTime trägt das Datum und die HH:MM-Zeit (plus lokalem Offset).
    assert body["start"]["dateTime"].startswith("2026-06-01T09:30:00")
    assert body["end"]["dateTime"].startswith("2026-06-01T17:45:00")


def test_parse_event_roundtrips_payload():
    body = gcal.event_payload("2026-06-01", "09:00", "17:00", "2026-05-20T10:00:00Z")
    body["id"] = "ev-42"
    parsed = gcal.parse_event(body)
    assert parsed == {
        "date": "2026-06-01", "start": "09:00", "end": "17:00",
        "modified_at": "2026-05-20T10:00:00Z", "event_id": "ev-42",
    }


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
