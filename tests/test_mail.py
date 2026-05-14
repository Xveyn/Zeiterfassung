# tests/test_mail.py
import sys
import types

# Die CI installiert google-auth nicht (s. CLAUDE.md). Damit die Tests
# trotzdem laufen, stubben wir die Google-Module bei Bedarf.
try:
    import google.oauth2.credentials  # noqa: F401
    import google.auth.exceptions  # noqa: F401
    import google.auth.transport.requests  # noqa: F401
except ImportError:
    _google = types.ModuleType("google")
    _google.__path__ = []
    _oauth2 = types.ModuleType("google.oauth2")
    _oauth2.__path__ = []
    _creds = types.ModuleType("google.oauth2.credentials")

    class _StubCreds:
        @staticmethod
        def from_authorized_user_file(path, scopes):
            raise NotImplementedError

    _creds.Credentials = _StubCreds

    _auth = types.ModuleType("google.auth")
    _auth.__path__ = []
    _excs = types.ModuleType("google.auth.exceptions")

    class RefreshError(Exception):
        pass

    class TransportError(Exception):
        pass

    _excs.RefreshError = RefreshError
    _excs.TransportError = TransportError

    _transport = types.ModuleType("google.auth.transport")
    _transport.__path__ = []
    _trq = types.ModuleType("google.auth.transport.requests")

    class Request:  # noqa: D401
        pass

    _trq.Request = Request

    # Parent-Attribute setzen, damit unittest.mock.patch via getattr navigieren kann
    _google.oauth2 = _oauth2
    _google.auth = _auth
    _oauth2.credentials = _creds
    _auth.exceptions = _excs
    _auth.transport = _transport
    _transport.requests = _trq

    sys.modules["google"] = _google
    sys.modules["google.oauth2"] = _oauth2
    sys.modules["google.oauth2.credentials"] = _creds
    sys.modules["google.auth"] = _auth
    sys.modules["google.auth.exceptions"] = _excs
    sys.modules["google.auth.transport"] = _transport
    sys.modules["google.auth.transport.requests"] = _trq

import os  # noqa: E402
import pytest  # noqa: E402
from unittest.mock import patch, MagicMock  # noqa: E402

from src.mail import (  # noqa: E402
    refresh_token_if_needed,
    TokenAuthError,
    TokenNetworkError,
    get_scopes,
)


def test_get_scopes_without_sync_includes_gmail_and_userinfo():
    scopes = get_scopes(sync_enabled=False)
    assert "https://www.googleapis.com/auth/gmail.send" in scopes
    assert "https://www.googleapis.com/auth/userinfo.email" in scopes
    assert "https://www.googleapis.com/auth/drive.appdata" not in scopes


def test_get_scopes_with_sync_includes_drive_appdata():
    scopes = get_scopes(sync_enabled=True)
    assert "https://www.googleapis.com/auth/gmail.send" in scopes
    assert "https://www.googleapis.com/auth/drive.appdata" in scopes
    assert "https://www.googleapis.com/auth/userinfo.email" in scopes


def test_no_token_file(tmp_path):
    """Ohne token.json gibt die Funktion 'no_token' zurück."""
    path = str(tmp_path / "token.json")
    assert refresh_token_if_needed(path) == "no_token"


def test_valid_token_is_not_refreshed(tmp_path):
    """Gültige Credentials werden nicht erneuert."""
    path = str(tmp_path / "token.json")
    # Datei muss existieren, Inhalt wird aber nicht gelesen (mocked)
    open(path, "w").close()

    fake_creds = MagicMock()
    fake_creds.valid = True

    with patch("google.oauth2.credentials.Credentials.from_authorized_user_file",
               return_value=fake_creds):
        assert refresh_token_if_needed(path) == "valid"

    fake_creds.refresh.assert_not_called()


def test_expired_token_is_refreshed_and_persisted(tmp_path):
    """Abgelaufene Credentials werden refreshed und die Datei neu geschrieben."""
    path = str(tmp_path / "token.json")
    open(path, "w").close()

    fake_creds = MagicMock()
    fake_creds.valid = False
    fake_creds.expired = True
    fake_creds.refresh_token = "rt"
    fake_creds.to_json.return_value = '{"fresh": true}'

    with patch("google.oauth2.credentials.Credentials.from_authorized_user_file",
               return_value=fake_creds):
        assert refresh_token_if_needed(path) == "refreshed"

    fake_creds.refresh.assert_called_once()
    with open(path) as f:
        assert f.read() == '{"fresh": true}'


def test_no_refresh_token_raises_auth_error(tmp_path):
    """Wenn Credentials kein refresh_token haben, TokenAuthError."""
    path = str(tmp_path / "token.json")
    open(path, "w").close()

    fake_creds = MagicMock()
    fake_creds.valid = False
    fake_creds.expired = True
    fake_creds.refresh_token = None

    with patch("google.oauth2.credentials.Credentials.from_authorized_user_file",
               return_value=fake_creds):
        with pytest.raises(TokenAuthError):
            refresh_token_if_needed(path)


def test_refresh_error_translates_to_auth_error(tmp_path):
    """Google RefreshError wird in TokenAuthError übersetzt."""
    from google.auth.exceptions import RefreshError

    path = str(tmp_path / "token.json")
    open(path, "w").close()

    fake_creds = MagicMock()
    fake_creds.valid = False
    fake_creds.expired = True
    fake_creds.refresh_token = "rt"
    fake_creds.refresh.side_effect = RefreshError("invalid_grant")

    with patch("google.oauth2.credentials.Credentials.from_authorized_user_file",
               return_value=fake_creds):
        with pytest.raises(TokenAuthError, match="invalid_grant"):
            refresh_token_if_needed(path)


def test_transport_error_translates_to_network_error(tmp_path):
    """Google TransportError wird in TokenNetworkError übersetzt."""
    from google.auth.exceptions import TransportError

    path = str(tmp_path / "token.json")
    open(path, "w").close()

    fake_creds = MagicMock()
    fake_creds.valid = False
    fake_creds.expired = True
    fake_creds.refresh_token = "rt"
    fake_creds.refresh.side_effect = TransportError("connection refused")

    with patch("google.oauth2.credentials.Credentials.from_authorized_user_file",
               return_value=fake_creds):
        with pytest.raises(TokenNetworkError, match="connection refused"):
            refresh_token_if_needed(path)


def test_failed_refresh_does_not_overwrite_token(tmp_path):
    """Bei Refresh-Fehler bleibt die Token-Datei unberührt."""
    from google.auth.exceptions import RefreshError

    path = str(tmp_path / "token.json")
    with open(path, "w") as f:
        f.write("original-content")

    fake_creds = MagicMock()
    fake_creds.valid = False
    fake_creds.expired = True
    fake_creds.refresh_token = "rt"
    fake_creds.refresh.side_effect = RefreshError("boom")

    with patch("google.oauth2.credentials.Credentials.from_authorized_user_file",
               return_value=fake_creds):
        with pytest.raises(TokenAuthError):
            refresh_token_if_needed(path)

    with open(path) as f:
        assert f.read() == "original-content"


import platform  # noqa: E402
import stat  # noqa: E402


@pytest.mark.skipif(
    platform.system() == "Windows",
    reason="Windows hat kein POSIX-Permission-Modell",
)
def test_refresh_writes_token_with_0600_permissions(tmp_path):
    """Nach erfolgreichem Refresh hat token.json Mode 0o600."""
    path = str(tmp_path / "token.json")
    open(path, "w").close()

    fake_creds = MagicMock()
    fake_creds.valid = False
    fake_creds.expired = True
    fake_creds.refresh_token = "rt"
    fake_creds.to_json.return_value = '{"fresh": true}'

    with patch("google.oauth2.credentials.Credentials.from_authorized_user_file",
               return_value=fake_creds):
        refresh_token_if_needed(path)

    mode = os.stat(path).st_mode & 0o777
    assert mode == 0o600, f"Erwartete 0o600, ist {oct(mode)}"
