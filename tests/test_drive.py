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
        service = get_drive_service("credentials.json", str(token_path))

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
