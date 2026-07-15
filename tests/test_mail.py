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

import socket  # noqa: E402

from src.mail import (  # noqa: E402
    refresh_token_if_needed,
    is_offline_error,
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


def test_send_email_json_attachment_uses_subtype():
    """JSON-Anhang setzt MIME-Subtype 'json' statt 'pdf'."""
    from unittest.mock import MagicMock
    from src.mail import send_email

    service = MagicMock()
    service.users().messages().send().execute.return_value = {"id": "mid-1"}

    msg_id = send_email(
        service, "to@example.com", "Subj", "<p>body</p>",
        attachment_bytes=b'{"x":1}',
        attachment_filename="share.json",
        attachment_subtype="json",
    )
    assert msg_id == "mid-1"
    # Inspect the raw body sent to Gmail
    call_kwargs = service.users().messages().send.call_args
    body = call_kwargs.kwargs.get("body") or call_kwargs.args[-1]
    import base64
    raw = base64.urlsafe_b64decode(body["raw"]).decode()
    assert "application/json" in raw
    assert "share.json" in raw


def test_send_email_rejects_recipient_with_control_chars():
    """Audit N11 / #133: CR/LF/NUL im Empfänger werden abgewiesen (ValueError),
    statt still gestrippt und an eine vermurkste Adresse gesendet zu werden.

    Verhindert Header-Injection UND stille Falschzustellung: ein gestripptes
    "a@b\\nBcc: c" würde sonst an "a@bBcc: c" gehen, ohne dass der Nutzer es merkt.
    """
    from unittest.mock import MagicMock
    from src.mail import send_email

    service = MagicMock()

    with pytest.raises(ValueError):
        send_email(
            service,
            "victim@example.com\r\nBcc: attacker@evil.com",
            "Subj",
            "<p>body</p>",
        )

    # Es darf nichts gesendet worden sein.
    service.users().messages().send.assert_not_called()


import platform  # noqa: E402


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


def test_get_scopes_with_gcal_includes_calendar_scopes():
    scopes = get_scopes(sync_enabled=False, gcal_enabled=True)
    assert "https://www.googleapis.com/auth/calendar.events" in scopes
    assert "https://www.googleapis.com/auth/calendar.calendarlist.readonly" in scopes


def test_get_scopes_without_gcal_has_no_calendar_scopes():
    scopes = get_scopes(sync_enabled=True, gcal_enabled=False)
    assert not any("calendar" in s for s in scopes)


def test_fetch_user_email_uses_tokeninfo_not_gmail_getprofile(tmp_path):
    """Regression #136: fetch_user_email darf keinen Gmail-getProfile-Call machen.

    Mit dem einzigen gewährten Gmail-Scope `gmail.send` wirft
    `users().getProfile()` ein 403 insufficientPermissions (reiner Log-Noise) —
    die E-Mail kommt stattdessen aus dem tokeninfo-Endpoint (userinfo.email).
    Erwartet: es wird kein Gmail-Service gebaut, das Ergebnis stammt aus tokeninfo.
    """
    from src.mail import fetch_user_email

    path = str(tmp_path / "token.json")
    open(path, "w").close()

    fake_creds = MagicMock()
    fake_creds.valid = True
    fake_creds.expired = False
    fake_creds.token = "access-token"

    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self):
            return b'{"email": "me@example.com"}'

    with patch("google.oauth2.credentials.Credentials.from_authorized_user_file",
               return_value=fake_creds), \
         patch("googleapiclient.discovery.build") as mock_build, \
         patch("urllib.request.urlopen", return_value=_Resp()):
        result = fetch_user_email(path)

    assert result == "me@example.com"
    mock_build.assert_not_called()


def _named_exc(name):
    """Erzeugt eine Exception-Klasse mit exakt diesem __name__ — simuliert
    bibliotheksspezifische Netzwerkfehler (httplib2, requests, google.auth)
    ohne deren Import."""
    return type(name, (Exception,), {})


def test_is_offline_error_true_for_token_network_error():
    assert is_offline_error(TokenNetworkError("connection refused"))


def test_is_offline_error_true_for_socket_and_connection_errors():
    assert is_offline_error(socket.gaierror("getaddrinfo failed"))
    assert is_offline_error(ConnectionError("connection reset"))
    assert is_offline_error(TimeoutError("timed out"))


def test_is_offline_error_true_for_library_errors_by_name():
    # httplib2 / google.auth / requests werden in den Tests nicht importiert —
    # die Erkennung läuft über den Klassennamen.
    assert is_offline_error(_named_exc("ServerNotFoundError")("kein Server"))
    assert is_offline_error(_named_exc("TransportError")("transport"))


def test_is_offline_error_walks_cause_chain():
    """Ein in einen generischen Fehler verpackter Netzwerkfehler wird erkannt."""
    outer = RuntimeError("Senden fehlgeschlagen")
    outer.__cause__ = ConnectionError("offline")
    assert is_offline_error(outer)


def test_is_offline_error_false_for_genuine_errors():
    assert not is_offline_error(ValueError("ungültiges Datum"))
    assert not is_offline_error(RuntimeError("Gmail API: 403 insufficient scope"))
    assert not is_offline_error(None)


def test_fetch_user_email_sends_token_in_post_body_not_url(tmp_path):
    """N10: Der Access-Token darf nicht als URL-Query-Parameter gehen
    (Leak-Risiko über URL-Logs), sondern im POST-Body."""
    from src.mail import fetch_user_email

    path = str(tmp_path / "token.json")
    open(path, "w").close()

    fake_creds = MagicMock()
    fake_creds.valid = True
    fake_creds.expired = False
    fake_creds.token = "access-token-xyz"

    captured = {}

    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self):
            return b'{"email": "me@example.com"}'

    def _fake_urlopen(req, timeout=None):
        captured["req"] = req
        return _Resp()

    with patch("google.oauth2.credentials.Credentials.from_authorized_user_file",
               return_value=fake_creds), \
         patch("urllib.request.urlopen", _fake_urlopen):
        result = fetch_user_email(path)

    assert result == "me@example.com"
    req = captured["req"]
    assert req.get_method() == "POST"
    assert "access-token-xyz" not in req.full_url     # nicht in der URL
    assert b"access-token-xyz" in req.data            # sondern im Body
