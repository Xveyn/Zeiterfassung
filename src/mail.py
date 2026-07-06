# src/mail.py
import base64
import os
import socket
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication
from email.header import Header

from src.oauth_utils import discard_token_for_scope_upgrade, write_token

GMAIL_SEND_SCOPE = "https://www.googleapis.com/auth/gmail.send"
DRIVE_APPDATA_SCOPE = "https://www.googleapis.com/auth/drive.appdata"
USERINFO_EMAIL_SCOPE = "https://www.googleapis.com/auth/userinfo.email"
CALENDAR_EVENTS_SCOPE = "https://www.googleapis.com/auth/calendar.events"
CALENDAR_LIST_SCOPE = "https://www.googleapis.com/auth/calendar.calendarlist.readonly"


def get_scopes(sync_enabled, gcal_enabled=False):
    """Liefert die OAuth-Scopes der App als Vereinigung aller aktiven Features.

    `userinfo.email` (Identity-Scope, non-sensitive) erlaubt die Anzeige
    des Absenders im Settings-Dialog. `openid` wurde absichtlich entfernt,
    weil Google den Scope mitunter normalisiert/strippt, was zu Scope-
    Mismatch-Warnings in google-auth führt.
    """
    scopes = [GMAIL_SEND_SCOPE, USERINFO_EMAIL_SCOPE]
    if sync_enabled:
        scopes.append(DRIVE_APPDATA_SCOPE)
    if gcal_enabled:
        scopes.append(CALENDAR_EVENTS_SCOPE)
        scopes.append(CALENDAR_LIST_SCOPE)
    return scopes


# Legacy: alte Callers benutzen weiter SCOPES (gmail-only). Neue Callers
# benutzen get_scopes(settings.get("sync_enabled")).
SCOPES = [GMAIL_SEND_SCOPE]


def fetch_user_email(token_path="token.json", sync_enabled=False, gcal_enabled=False):
    """Liest die E-Mail-Adresse des authentifizierten Users.

    Nutzt den `tokeninfo`-Endpoint, der die E-Mail aus dem Access-Token meldet,
    sofern der `userinfo.email`-Scope autorisiert ist. (Ein früher zuerst
    versuchter Gmail-`users().getProfile()`-Call ist mit dem `gmail.send`-Scope
    nicht erlaubt und warf jedes Mal nur ein 403 insufficientPermissions in den
    Log — die E-Mail kommt ohnehin aus tokeninfo, siehe #136.)

    Liefert die E-Mail oder leeren String bei fehlendem/ungültigem Token
    oder Fehler. Diese Funktion soll im Hintergrundthread laufen, weil sie
    HTTP-Calls macht.
    """
    import logging
    log = logging.getLogger(__name__)

    if not os.path.exists(token_path):
        return ""
    try:
        from google.oauth2.credentials import Credentials

        creds = Credentials.from_authorized_user_file(
            token_path, get_scopes(sync_enabled, gcal_enabled)
        )
        if creds.expired and creds.refresh_token:
            from google.auth.transport.requests import Request
            try:
                creds.refresh(Request())
                write_token(creds, token_path)
            except Exception:
                log.warning("fetch_user_email: token refresh failed")
                return ""
        if not creds.valid or not creds.token:
            log.warning("fetch_user_email: no valid token after refresh")
            return ""
        # Diagnose: welche Scopes hat der Token tatsächlich? google-auth's
        # creds.scopes spiegelt nur den im Konstruktor übergebenen Wert wider —
        # die GRANTED Scopes stehen im JSON-File.
        try:
            import json as _json
            with open(token_path, "r", encoding="utf-8") as f:
                _td = _json.load(f)
            log.info("fetch_user_email: granted scopes = %r", _td.get("scopes"))
        except Exception:
            pass
    except Exception:
        log.exception("fetch_user_email: setup failed")
        return ""

    # Tokeninfo — liest die E-Mail direkt aus dem Access-Token, sofern
    # userinfo.email-Scope autorisiert ist. Kein API-Auth nötig (Token kommt
    # als Query-Param), daher kein 401-Risiko.
    try:
        import json
        import urllib.parse
        import urllib.request

        url = (
            "https://oauth2.googleapis.com/tokeninfo?"
            + urllib.parse.urlencode({"access_token": creds.token})
        )
        with urllib.request.urlopen(url, timeout=10) as resp:
            data = json.load(resp)
        log.info("fetch_user_email: tokeninfo response keys = %r", list(data.keys()))
        return (data.get("email") or "")
    except Exception:
        log.exception("fetch_user_email: tokeninfo lookup failed")
        return ""


class TokenAuthError(Exception):
    """Refresh-Token ist ungültig — User muss sich neu anmelden."""


class TokenNetworkError(Exception):
    """Refresh fehlgeschlagen wegen Netzwerkproblem."""


# Klassennamen netzwerkbezogener Exceptions, die auf eine fehlende
# Internetverbindung hindeuten. Geprüft wird über den Namen, damit mail.py
# httplib2/requests/google.auth nicht eager importieren muss (CI ohne
# requirements.txt, s. CLAUDE.md).
_OFFLINE_EXC_NAMES = frozenset({
    "TransportError",        # google.auth.exceptions
    "ServerNotFoundError",   # httplib2.error — typisch beim Offline-Send
    "NewConnectionError",    # urllib3
    "MaxRetryError",         # urllib3
    "ConnectTimeout",        # requests
    "URLError",              # urllib.error
})


def is_offline_error(exc):
    """True, wenn `exc` (oder eine Ursache in seiner Kette) auf eine fehlende
    Internetverbindung hindeutet — anders als ein echter Bug oder ein
    API-Fehler (z.B. ein 4xx von Google).

    Der Sendepfad nutzt das, um statt eines kryptischen Tracebacks eine
    verständliche „kein Internet"-Meldung zu zeigen.
    """
    seen = set()
    current = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, TokenNetworkError):
            return True
        # socket.gaierror (DNS schlägt fehl), ConnectionError und
        # TimeoutError sind OSError-Subklassen und die klassischen
        # Offline-Symptome. googleapiclient.errors.HttpError (echte
        # API-Fehler) ist KEIN OSError und wird so nicht fälschlich erfasst.
        if isinstance(current, (socket.gaierror, ConnectionError, TimeoutError)):
            return True
        if type(current).__name__ in _OFFLINE_EXC_NAMES:
            return True
        current = current.__cause__ or current.__context__
    return False


def _refresh_and_persist(creds, token_path):
    """Refresh credentials and write them back. Translates Google exceptions."""
    from google.auth.exceptions import RefreshError, TransportError
    from google.auth.transport.requests import Request

    try:
        creds.refresh(Request())
    except RefreshError as e:
        raise TokenAuthError(str(e)) from e
    except TransportError as e:
        raise TokenNetworkError(str(e)) from e

    write_token(creds, token_path)


def refresh_token_if_needed(token_path="token.json", sync_enabled=False,
                            gcal_enabled=False):
    """Proactively refresh the Gmail token when it is expired.

    Returns one of:
        "no_token"  — no token file present (first use)
        "valid"     — token is still valid, no refresh needed
        "refreshed" — refresh succeeded and file was updated

    Raises:
        TokenAuthError    — refresh_token is invalid, user must re-authenticate
        TokenNetworkError — network issue prevented the refresh attempt
    """
    from google.oauth2.credentials import Credentials

    scopes = get_scopes(sync_enabled, gcal_enabled)

    if not os.path.exists(token_path):
        return "no_token"

    creds = Credentials.from_authorized_user_file(token_path, scopes)

    if creds.valid:
        return "valid"

    if not creds.expired or not creds.refresh_token:
        raise TokenAuthError(
            "Token ist ungültig und enthält kein Refresh-Token."
        )

    _refresh_and_persist(creds, token_path)
    return "refreshed"


def get_gmail_service(credentials_path="credentials.json", token_path="token.json",
                      sync_enabled=False, gcal_enabled=False):
    """Authenticate with Gmail API and return a service object.

    Returns the service object, or raises an exception on failure.
    """
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build

    scopes = get_scopes(sync_enabled, gcal_enabled)
    creds = None

    if os.path.exists(token_path):
        creds = Credentials.from_authorized_user_file(token_path, scopes)
        # Scope-Upgrade-Erkennung: deckt der gespeicherte Token nicht alle
        # angeforderten Scopes ab (typisch nach Feature-Update), erzwingen wir
        # einen frischen OAuth-Flow. Sonst bleibt der Token "valid" und der
        # User wundert sich, warum eine Scope-abhängige Funktion 401/403 wirft.
        if discard_token_for_scope_upgrade(token_path, scopes):
            creds = None

    if creds and creds.expired and creds.refresh_token:
        try:
            _refresh_and_persist(creds, token_path)
        except TokenAuthError:
            creds = None

    if not creds or not creds.valid:
        if not os.path.exists(credentials_path):
            raise FileNotFoundError(
                f"credentials.json nicht gefunden unter:\n{credentials_path}\n\n"
                "Bitte erstelle ein Google Cloud Projekt mit Gmail API "
                "und lade die OAuth2 Client-ID dort ab."
            )
        flow = InstalledAppFlow.from_client_secrets_file(credentials_path, scopes)
        creds = flow.run_local_server(port=0)
        write_token(creds, token_path)

    return build("gmail", "v1", credentials=creds)


def send_email(service, to, subject, html_body,
               attachment_bytes=None, attachment_filename=None,
               attachment_subtype="pdf",
               # legacy aliases — bleibe rückwärtskompatibel falls ein Caller
               # noch nicht migriert ist:
               pdf_bytes=None, pdf_filename=None):
    """Send an HTML email via Gmail API, optionally with a binary attachment.

    attachment_subtype steuert den MIMEApplication-_subtype (z.B. 'pdf', 'json').
    pdf_bytes/pdf_filename sind Legacy-Aliase und werden auf
    attachment_bytes/attachment_filename gemappt.
    """
    if pdf_bytes is not None and attachment_bytes is None:
        attachment_bytes = pdf_bytes
        attachment_filename = attachment_filename or pdf_filename
        attachment_subtype = "pdf"

    # Header-Injection UND stille Falschzustellung verhindern (Audit N11 / #133):
    # Steuerzeichen im Empfänger abweisen, statt sie still zu strippen — ein
    # gestripptes "a@b\nBcc: c" würde sonst an die vermurkste Adresse "a@bBcc: c"
    # gesendet, ohne dass der Nutzer es merkt. Der Wert kommt aus den Settings,
    # der Fehler wird im Sende-Dialog sichtbar gemacht (classify_mail_error).
    if "\r" in to or "\n" in to or "\x00" in to:
        raise ValueError(
            "Die Empfängeradresse enthält unzulässige Steuerzeichen "
            "(Zeilenumbruch oder Nullbyte). Bitte korrigiere die Adresse "
            "in den Einstellungen."
        )

    if attachment_bytes:
        message = MIMEMultipart()
        message["to"] = to
        message["subject"] = Header(subject, "utf-8")  # pyright: ignore[reportArgumentType]
        message.attach(MIMEText(html_body, "html", _charset="utf-8"))

        attachment = MIMEApplication(attachment_bytes, _subtype=attachment_subtype)
        attachment.add_header(
            "Content-Disposition", "attachment",
            filename=attachment_filename or f"attachment.{attachment_subtype}",
        )
        message.attach(attachment)
    else:
        message = MIMEText(html_body, "html", _charset="utf-8")
        message["to"] = to
        message["subject"] = Header(subject, "utf-8")  # pyright: ignore[reportArgumentType]

    raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
    body = {"raw": raw}

    sent = service.users().messages().send(userId="me", body=body).execute()
    return sent["id"]
