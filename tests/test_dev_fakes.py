import logging

import pytest

from src.dev import fakes


@pytest.fixture(autouse=True)
def _reset():
    fakes.reset_state()
    yield
    fakes.reset_state()


def test_fake_send_email_logs_and_returns_id(caplog):
    with caplog.at_level(logging.INFO, logger="zeiterfassung.dev"):
        msg_id = fakes.fake_send_email(
            object(), "a@b.de", "Betreff", "<html></html>",
            attachment_filename="report.pdf",
        )
    assert msg_id.startswith("dev-msg-")
    assert "würde Mail senden" in caplog.text
    assert "a@b.de" in caplog.text


def test_fake_drive_roundtrip():
    service = fakes.fake_get_drive_service("c.json", "t.json")
    assert fakes.fake_find_sync_file(service) is None

    content = b'{"entries": {"x": 1}}'
    file_id, ver1 = fakes.fake_upload(service, content)
    assert file_id == "dev-file"
    assert fakes.fake_find_sync_file(service) == "dev-file"

    data, ver2 = fakes.fake_download(service, file_id)
    assert data == content
    assert ver2 == ver1

    _, ver3 = fakes.fake_upload(service, b'{"entries": {}}', file_id)
    assert int(ver3) > int(ver1)


def test_fake_list_calendars_returns_id_summary_dicts():
    service = fakes.fake_get_calendar_service()
    calendars = fakes.fake_list_calendars(service)
    assert len(calendars) >= 1
    for cal in calendars:
        assert set(cal) == {"id", "summary"}
    assert any(c["id"] == "primary" for c in calendars)


def test_fake_calendar_create_list_delete():
    service = fakes.fake_get_calendar_service()
    assert fakes.fake_list_app_events(service, "cal") == []

    eid = fakes.fake_create_event(service, "cal", "2026-05-28", "08:00", "16:00", "m1")
    events = fakes.fake_list_app_events(service, "cal")
    assert len(events) == 1
    assert events[0]["event_id"] == eid
    assert events[0]["date"] == "2026-05-28"

    fakes.fake_update_event(service, "cal", eid, "2026-05-28", "09:00", "17:00", "m2")
    assert fakes.fake_list_app_events(service, "cal")[0]["start"] == "09:00"

    fakes.fake_delete_event(service, "cal", eid)
    assert fakes.fake_list_app_events(service, "cal") == []


def test_simulate_auth_error_once_raises_then_clears():
    from src.mail import TokenAuthError
    fakes.simulate_auth_error_once()
    with pytest.raises(TokenAuthError):
        fakes.fake_get_gmail_service()
    # Nur einmal — danach wieder normal
    assert fakes.fake_get_gmail_service() is not None


def test_reset_state_clears_drive_and_calendar():
    service = fakes.fake_get_drive_service("c", "t")
    fakes.fake_upload(service, b"{}")
    fakes.fake_create_event(service, "cal", "2026-05-28", "08:00", "16:00", "m")
    fakes.reset_state()
    assert fakes.fake_find_sync_file(service) is None
    assert fakes.fake_list_app_events(service, "cal") == []
