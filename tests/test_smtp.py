"""Tests für den SMTP-Versand und seine Fehlerklassifikation.

Getestet wird gegen einen smtplib-Stub — kein Netz, kein echter Server.
"""

import smtplib
import socket
import ssl

import pytest

from src import smtp


def _record(**overrides):
    base = {
        "id": "rec-1", "name": "Firma", "enabled": True,
        "host": "mail.example.com", "port": 587, "security": "starttls",
        "username": "user@example.com", "from_addr": "user@example.com",
        "recipient": "buchhaltung@example.com",
        "password_location": "keyring",
    }
    base.update(overrides)
    return base


class _FakeServer:
    def __init__(self, host=None, port=None, timeout=None, context=None):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.context = context
        self.started_tls = False
        self.tls_context = None
        self.logged_in = None
        self.sent = []
        self.noops = 0
        self.quit_called = False
        self.closed = False
        self.fail_starttls = None
        self.fail_login = None
        self.fail_send = None

    def starttls(self, context=None):
        self.started_tls = True
        self.tls_context = context
        if self.fail_starttls:
            raise self.fail_starttls

    def login(self, user, password):
        if self.fail_login:
            raise self.fail_login
        self.logged_in = (user, password)

    def send_message(self, message):
        if self.fail_send:
            raise self.fail_send
        self.sent.append(message)

    def noop(self):
        self.noops += 1

    def quit(self):
        self.quit_called = True

    def close(self):
        self.closed = True


@pytest.fixture
def fake_smtp(monkeypatch):
    """Fängt SMTP und SMTP_SSL ab und merkt sich die erzeugte Instanz."""
    created = {}

    def make(kind):
        def factory(*args, **kwargs):
            server = _FakeServer(*args, **kwargs)
            created[kind] = server
            return server
        return factory

    monkeypatch.setattr(smtp.smtplib, "SMTP", make("plain"))
    monkeypatch.setattr(smtp.smtplib, "SMTP_SSL", make("ssl"))
    return created


# --- Verbindungsaufbau -----------------------------------------------------

def test_starttls_connection_upgrades_and_logs_in(fake_smtp):
    smtp.send(_record(), "geheim", subject="S", html="<p>x</p>")
    server = fake_smtp["plain"]
    assert server.started_tls is True
    assert server.logged_in == ("user@example.com", "geheim")
    assert server.quit_called is True


def test_starttls_gets_a_verifying_context(fake_smtp):
    """Ohne expliziten Kontext faellt smtplib auf _create_stdlib_context()
    zurueck — OHNE Hostname- und Zertifikatspruefung. Eine Regression dort
    kaeme sonst durch alle Tests."""
    smtp.send(_record(), "geheim", subject="S", html="<p>x</p>")
    context = fake_smtp["plain"].tls_context
    assert context is not None
    assert context.check_hostname is True
    assert context.verify_mode == ssl.CERT_REQUIRED


def test_ssl_connection_uses_smtp_ssl_without_starttls(fake_smtp):
    smtp.send(_record(security="ssl", port=465), "geheim",
              subject="S", html="<p>x</p>")
    server = fake_smtp["ssl"]
    assert server.port == 465
    assert server.context is not None
    assert "plain" not in fake_smtp


def test_plain_connection_does_not_start_tls(fake_smtp):
    smtp.send(_record(security="none", port=25), "", subject="S", html="<p>x</p>")
    assert fake_smtp["plain"].started_tls is False


def test_unknown_security_mode_is_rejected(fake_smtp):
    """Fail-CLOSED. Ein durchgerutschter Wert (Handedit in smtp.json,
    Gross-/Kleinschreibung, spaetere Migration) darf NICHT still
    unverschluesselt verbinden und AUTH PLAIN im Klartext schicken."""
    with pytest.raises(ValueError):
        smtp.send(_record(security="TLS"), "geheim", subject="S", html="<p>x</p>")
    assert fake_smtp == {}


def test_no_login_without_username(fake_smtp):
    """Interner Relay ohne Auth."""
    smtp.send(_record(username=""), "", subject="S", html="<p>x</p>")
    assert fake_smtp["plain"].logged_in is None


def test_timeout_is_set(fake_smtp):
    """Ohne Timeout hängt der Worker unbegrenzt an einem stummen Server."""
    smtp.send(_record(), "geheim", subject="S", html="<p>x</p>")
    assert fake_smtp["plain"].timeout == smtp.DEFAULT_TIMEOUT


# --- Nachricht -------------------------------------------------------------

def test_message_carries_from_to_and_attachment(fake_smtp):
    smtp.send(_record(), "geheim", subject="Bericht", html="<p>Grüße</p>",
              attachment_bytes=b"%PDF-1.4", attachment_filename="b.pdf",
              attachment_subtype="pdf")
    message = fake_smtp["plain"].sent[0]
    assert message["from"] == "user@example.com"
    assert message["to"] == "buchhaltung@example.com"
    assert "b.pdf" in message.as_string()


def test_to_overrides_the_account_recipient(fake_smtp):
    """Der Teilen-Pfad fragt den Empfaenger im Dialog ab; das
    recipient-Feld des Kontos ist semantisch etwas anderes."""
    smtp.send(_record(), "geheim", subject="S", html="<p>x</p>",
              to="kollege@example.com")
    assert fake_smtp["plain"].sent[0]["to"] == "kollege@example.com"


# --- Verbindung schließen --------------------------------------------------

def test_connection_is_closed_when_sending_fails(fake_smtp, monkeypatch):
    """Sonst bleibt die Verbindung offen, wenn der Server die Mail ablehnt."""
    record = _record()

    def factory(*args, **kwargs):
        server = _FakeServer(*args, **kwargs)
        server.fail_send = smtplib.SMTPRecipientsRefused({"a@b": (550, b"nope")})
        fake_smtp["plain"] = server
        return server

    monkeypatch.setattr(smtp.smtplib, "SMTP", factory)
    with pytest.raises(smtplib.SMTPRecipientsRefused):
        smtp.send(record, "geheim", subject="S", html="<p>x</p>")
    assert fake_smtp["plain"].closed is True


def test_close_still_closes_when_quit_raises(fake_smtp):
    """smtplib.quit() ruft close() erst NACH dem QUIT-Kommando; wirft das auf
    einer toten Verbindung, bliebe der Filedescriptor offen."""
    smtp.send(_record(), "geheim", subject="S", html="<p>x</p>")
    server = fake_smtp["plain"]

    def boom():
        raise smtplib.SMTPServerDisconnected("weg")

    server.quit = boom
    smtp._close(server)
    assert server.closed is True


def test_test_connection_sends_noop_but_no_mail(fake_smtp):
    smtp.test_connection(_record(), "geheim")
    server = fake_smtp["plain"]
    assert server.noops == 1
    assert server.sent == []


# --- Fehlerklassifikation --------------------------------------------------

@pytest.mark.parametrize("exc,expected", [
    (smtplib.SMTPAuthenticationError(535, b"Authentication unsuccessful"), "auth"),
    (smtp.AuthNotSupported("SMTP AUTH extension not supported by server."), "auth"),
    (smtplib.SMTPRecipientsRefused({"a@b": (550, b"no such user")}), "recipient"),
    (smtplib.SMTPSenderRefused(553, b"bad sender", "a@b"), "recipient"),
    (smtp.TlsNotSupported("STARTTLS extension not supported by server."), "tls"),
    (ssl.SSLError("certificate verify failed"), "tls"),
    (smtplib.SMTPServerDisconnected("connection closed"), "server"),
    (smtplib.SMTPConnectError(421, b"service unavailable"), "server"),
    (smtplib.SMTPNotSupportedError("SMTPUTF8 not supported"), "server"),
    (socket.gaierror("Name or service not known"), "offline"),
    (ConnectionRefusedError("refused"), "offline"),
    (TimeoutError("timed out"), "offline"),
    (OSError(101, "Network is unreachable"), "offline"),
    (ValueError("irgendwas ganz anderes"), "error"),
])
def test_error_classification(exc, expected):
    """Ohne eigenen Klassifikator kaeme jede SMTP-Fehlerantwort als
    „unerwarteter Fehler mit Traceback" beim Nutzer an."""
    result = smtp.classify_smtp_error(exc)
    assert result["ok"] is False
    assert result["kind"] == expected


def test_disconnect_after_timeout_is_not_reported_as_offline():
    """smtplib wirft SMTPServerDisconnected aus einem except-OSError-Block;
    is_offline_error folgt __context__ bis zum TimeoutError des Sockets. Ein
    Server, der annimmt und dann schweigt — der Fall, fuer den der Timeout
    existiert —, darf nicht „keine Internetverbindung" melden."""
    try:
        try:
            raise TimeoutError("timed out")
        except TimeoutError:
            # `from None` unterdrückt nur die Anzeige der Kette, nicht
            # __context__ selbst — is_offline_error() liest __context__
            # weiter aus. Ohne das flaggt ruff (B904) hier zu Recht eine
            # verschluckte Exception-Kette.
            raise smtplib.SMTPServerDisconnected(
                "Connection unexpectedly closed") from None
    except smtplib.SMTPServerDisconnected as e:
        assert smtp.classify_smtp_error(e)["kind"] == "server"


def test_only_the_unexpected_kind_carries_a_traceback():
    """Erwartete Fehler bekommen eine kurze Meldung, keinen Traceback."""
    try:
        raise smtplib.SMTPAuthenticationError(535, b"nope")
    except smtplib.SMTPAuthenticationError as e:
        assert smtp.classify_smtp_error(e)["tb"] is None
    try:
        raise ValueError("unerwartet")
    except ValueError as e:
        assert smtp.classify_smtp_error(e)["tb"] is not None


def test_detail_contains_the_server_response():
    exc = smtplib.SMTPAuthenticationError(535, b"5.7.3 Authentication unsuccessful")
    detail = smtp.classify_smtp_error(exc)["detail"]
    assert "535" in detail
    assert "Authentication unsuccessful" in detail


def test_recipient_detail_is_readable():
    """SMTPRecipientsRefused hat KEIN smtp_code/smtp_error, sondern ein Dict.
    Ohne eigenen Zweig staende in der Meldung woertlich
    {'a@b': (550, b'...')} — geschweifte Klammern und Bytes-Literal, und das
    beim haeufigsten Empfaengerfehler ueberhaupt."""
    exc = smtplib.SMTPRecipientsRefused(
        {"tippfehler@example.com": (550, b"5.1.1 User unknown")})
    detail = smtp.classify_smtp_error(exc)["detail"]
    assert "tippfehler@example.com" in detail
    assert "550" in detail
    assert "User unknown" in detail
    assert "{" not in detail
    assert "b'" not in detail
