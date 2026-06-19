import pytest
from unittest import mock

from src.drive import DriveAuthError, DriveConflictError, DriveNetworkError
from src.drive import SYNC_SCOPES, get_drive_service


def test_exceptions_are_distinct():
    assert not issubclass(DriveAuthError, DriveNetworkError)
    assert not issubclass(DriveNetworkError, DriveAuthError)
    assert not issubclass(DriveConflictError, DriveAuthError)


def test_sync_scopes_includes_gmail_send_and_drive_appdata():
    assert "https://www.googleapis.com/auth/gmail.send" in SYNC_SCOPES
    assert "https://www.googleapis.com/auth/drive.appdata" in SYNC_SCOPES


def test_get_drive_service_uses_existing_valid_token(tmp_path):
    token_path = tmp_path / "token.json"
    token_path.write_text('{"token": "fake"}')

    mock_creds = mock.MagicMock()
    mock_creds.valid = True
    mock_creds.expired = False

    with mock.patch("src.drive.Credentials") as mock_cred_cls, \
         mock.patch("src.drive.build") as mock_build:
        mock_cred_cls.from_authorized_user_file.return_value = mock_creds
        get_drive_service("credentials.json", str(token_path))

    mock_cred_cls.from_authorized_user_file.assert_called_once()
    assert mock_build.called
    assert mock_build.call_args[0][0] == "drive"


def test_get_drive_service_runs_oauth_flow_when_no_token(tmp_path):
    token_path = tmp_path / "token.json"  # doesn't exist
    creds_path = tmp_path / "credentials.json"
    creds_path.write_text('{"installed": {}}')

    new_creds = mock.MagicMock()
    new_creds.valid = True
    new_creds.to_json.return_value = '{"token": "new"}'

    with mock.patch("src.drive.InstalledAppFlow") as mock_flow_cls, \
         mock.patch("src.drive.build"):
        mock_flow = mock.MagicMock()
        mock_flow.run_local_server.return_value = new_creds
        mock_flow_cls.from_client_secrets_file.return_value = mock_flow

        get_drive_service(str(creds_path), str(token_path))

    assert mock_flow_cls.from_client_secrets_file.called
    call_args = mock_flow_cls.from_client_secrets_file.call_args
    used_scopes = call_args[0][1]
    assert "https://www.googleapis.com/auth/drive.appdata" in used_scopes
    assert "https://www.googleapis.com/auth/gmail.send" in used_scopes
    # Token wurde geschrieben
    assert token_path.exists()


from src.drive import find_sync_file


def test_find_sync_file_returns_id_when_present():
    service = mock.MagicMock()
    service.files().list().execute.return_value = {
        "files": [{"id": "file-abc", "name": "zeiterfassung-sync.json"}],
    }
    assert find_sync_file(service) == "file-abc"


def test_find_sync_file_returns_none_when_absent():
    service = mock.MagicMock()
    service.files().list().execute.return_value = {"files": []}
    assert find_sync_file(service) is None


def test_find_sync_file_queries_appdatafolder():
    service = mock.MagicMock()
    service.files().list().execute.return_value = {"files": []}
    find_sync_file(service)
    # spaces='appDataFolder' wurde verwendet
    call_kwargs = service.files().list.call_args[1]
    assert call_kwargs.get("spaces") == "appDataFolder"
    assert "zeiterfassung-sync.json" in call_kwargs.get("q", "")



from src.drive import download, upload


def test_download_returns_content_and_version():
    service = mock.MagicMock()
    service.files().get_media.return_value = "media-request"
    service.files().get().execute.return_value = {"version": 123}

    with mock.patch("src.drive.MediaIoBaseDownload") as mock_dl_cls:
        # Simuliere Downloader, der sofort done=True liefert
        mock_dl = mock.MagicMock()
        mock_dl.next_chunk.return_value = (None, True)
        mock_dl_cls.return_value = mock_dl

        # Buffer-Inhalt durch Side-Effect simulieren
        def fake_init(buf, req):
            buf.write(b'{"hello": "world"}')
            return mock_dl
        mock_dl_cls.side_effect = fake_init

        content, version = download(service, "file-123")

    assert content == b'{"hello": "world"}'
    assert version == "123"


def test_upload_new_file_when_file_id_none():
    service = mock.MagicMock()
    service.files().create().execute.return_value = {"id": "new-id", "version": 1}
    file_id, version = upload(service, b'{"x":1}', file_id=None, expected_etag="")
    assert file_id == "new-id"
    assert version == "1"


def test_upload_existing_file_uses_update():
    service = mock.MagicMock()
    service.files().update().execute.return_value = {"id": "file-123", "version": 2}
    file_id, version = upload(service, b'{"x":2}', file_id="file-123", expected_etag="")
    assert file_id == "file-123"
    assert version == "2"


def test_upload_412_response_raises_drive_conflict_error():
    """Drive API v3 schickt normalerweise kein 412, aber die 412→DriveConflictError-
    Mappung bleibt als defensiver Pfad bestehen."""
    from googleapiclient.errors import HttpError
    service = mock.MagicMock()
    resp = mock.MagicMock(status=412, reason="Precondition Failed")
    service.files().update().execute.side_effect = HttpError(resp, b"")
    with pytest.raises(DriveConflictError):
        upload(service, b'{"x":1}', file_id="file-1", expected_etag="")


def test_find_sync_file_403_raises_drive_auth_error():
    """403 'insufficient authentication scopes / insufficientPermissions' ist ein
    Berechtigungs-/Scope-Problem (Re-Consent nötig), KEIN Netzfehler — muss als
    DriveAuthError kommen, damit das UI die richtige Reconnect-Meldung zeigt."""
    from googleapiclient.errors import HttpError
    service = mock.MagicMock()
    resp = mock.MagicMock(status=403, reason="Forbidden")
    service.files().list().execute.side_effect = HttpError(
        resp, b'{"error": {"message": "Insufficient Permission"}}')
    with pytest.raises(DriveAuthError):
        find_sync_file(service)


def test_find_sync_file_non_403_http_error_stays_network():
    """Andere HTTP-Fehler (z.B. 500) bleiben DriveNetworkError."""
    from googleapiclient.errors import HttpError
    service = mock.MagicMock()
    resp = mock.MagicMock(status=500, reason="Server Error")
    service.files().list().execute.side_effect = HttpError(resp, b"")
    with pytest.raises(DriveNetworkError):
        find_sync_file(service)


def test_download_403_raises_drive_auth_error():
    from googleapiclient.errors import HttpError
    service = mock.MagicMock()
    resp = mock.MagicMock(status=403, reason="Forbidden")
    service.files().get().execute.side_effect = HttpError(resp, b"")
    with pytest.raises(DriveAuthError):
        download(service, "file-1")


def test_upload_403_raises_drive_auth_error():
    from googleapiclient.errors import HttpError
    service = mock.MagicMock()
    resp = mock.MagicMock(status=403, reason="Forbidden")
    service.files().update().execute.side_effect = HttpError(resp, b"")
    with pytest.raises(DriveAuthError):
        upload(service, b'{"x":1}', file_id="file-1", expected_etag="")


from src.drive import reconnect


def test_reconnect_deletes_existing_token_and_forces_flow(tmp_path):
    """Kern des Re-Consent-Fixes: trotz vorhandenem, gültigem Alt-Token muss
    reconnect den vollen OAuth-Flow erzwingen (Token löschen → Consent-Screen),
    sonst wird ein scope-armer Token nie ersetzt."""
    token = tmp_path / "token.json"
    token.write_text('{"token": "old-underscoped"}')
    creds_path = tmp_path / "credentials.json"
    creds_path.write_text('{"installed": {}}')

    new_creds = mock.MagicMock()
    new_creds.valid = True
    new_creds.to_json.return_value = '{"token": "fresh"}'

    with mock.patch("src.drive.InstalledAppFlow") as mock_flow_cls, \
         mock.patch("src.drive.build"):
        mock_flow = mock.MagicMock()
        mock_flow.run_local_server.return_value = new_creds
        mock_flow_cls.from_client_secrets_file.return_value = mock_flow
        reconnect(str(creds_path), str(token))

    assert mock_flow_cls.from_client_secrets_file.called  # voller Flow erzwungen
    assert token.read_text() == '{"token": "fresh"}'      # Alt-Token ersetzt


def test_reconnect_without_existing_token_runs_flow(tmp_path):
    """Fehlt token.json bereits, darf reconnect nicht scheitern, sondern den
    Flow normal starten."""
    token = tmp_path / "token.json"  # existiert nicht
    creds_path = tmp_path / "credentials.json"
    creds_path.write_text('{"installed": {}}')

    new_creds = mock.MagicMock()
    new_creds.valid = True
    new_creds.to_json.return_value = '{"token": "fresh"}'

    with mock.patch("src.drive.InstalledAppFlow") as mock_flow_cls, \
         mock.patch("src.drive.build"):
        mock_flow = mock.MagicMock()
        mock_flow.run_local_server.return_value = new_creds
        mock_flow_cls.from_client_secrets_file.return_value = mock_flow
        reconnect(str(creds_path), str(token))

    assert mock_flow_cls.from_client_secrets_file.called


def test_get_drive_service_with_gcal_requests_calendar_scopes(tmp_path, monkeypatch):
    """Bei gcal_enabled fordert get_drive_service auch die Calendar-Scopes an,
    damit ein Drive-Re-Consent die Calendar-Scopes nicht aus token.json wirft."""
    import json
    from src import drive

    token_path = tmp_path / "token.json"
    token_path.write_text(json.dumps({
        "token": "t", "refresh_token": "r", "client_id": "c",
        "client_secret": "s", "scopes": ["x"],
    }), encoding="utf-8")

    captured = {}

    class _FakeCreds:
        valid = True
        expired = False
        refresh_token = None

        @classmethod
        def from_authorized_user_file(cls, path, scopes):
            captured["scopes"] = scopes
            return cls()

    monkeypatch.setattr(drive, "Credentials", _FakeCreds)
    monkeypatch.setattr(drive, "build", lambda *a, **k: object())

    drive.get_drive_service("credentials.json", str(token_path), gcal_enabled=True)
    assert "https://www.googleapis.com/auth/calendar.events" in captured["scopes"]
    assert "https://www.googleapis.com/auth/calendar.calendarlist.readonly" in captured["scopes"]
