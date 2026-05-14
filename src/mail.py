# src/mail.py
import base64
import os
import stat
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication
from email.header import Header

GMAIL_SEND_SCOPE = "https://www.googleapis.com/auth/gmail.send"
DRIVE_APPDATA_SCOPE = "https://www.googleapis.com/auth/drive.appdata"


def get_scopes(sync_enabled):
    if sync_enabled:
        return [GMAIL_SEND_SCOPE, DRIVE_APPDATA_SCOPE]
    return [GMAIL_SEND_SCOPE]


# Legacy: alte Callers benutzen weiter SCOPES (gmail-only). Neue Callers
# benutzen get_scopes(settings.get("sync_enabled")).
SCOPES = [GMAIL_SEND_SCOPE]


class TokenAuthError(Exception):
    """Refresh-Token ist ungültig — User muss sich neu anmelden."""


class TokenNetworkError(Exception):
    """Refresh fehlgeschlagen wegen Netzwerkproblem."""


def _write_token(creds, token_path):
    """Persistiere Credentials und setze restriktive Permissions (Unix only).

    Auf Windows bleibt das chmod ein No-op — POSIX-Permissions gibt es
    dort nicht. `try/except OSError` deckt zusätzlich exotische Filesystems
    (sshfs, FAT32 auf USB-Stick) ab, wo chmod fehlschlagen kann.
    """
    with open(token_path, "w") as f:
        f.write(creds.to_json())
    try:
        os.chmod(token_path, stat.S_IRUSR | stat.S_IWUSR)  # 0o600
    except OSError:
        pass


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

    _write_token(creds, token_path)


def refresh_token_if_needed(token_path="token.json", sync_enabled=False):
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

    scopes = get_scopes(sync_enabled)

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


def get_gmail_service(credentials_path="credentials.json", token_path="token.json", sync_enabled=False):
    """Authenticate with Gmail API and return a service object.

    Returns the service object, or raises an exception on failure.
    """
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build

    scopes = get_scopes(sync_enabled)
    creds = None

    if os.path.exists(token_path):
        creds = Credentials.from_authorized_user_file(token_path, scopes)

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
        _write_token(creds, token_path)

    return build("gmail", "v1", credentials=creds)


def send_email(service, to, subject, html_body, pdf_bytes=None, pdf_filename=None):
    """Send an HTML email via Gmail API, optionally with a PDF attachment.

    Returns the sent message id, or raises an exception on failure.
    """
    if pdf_bytes:
        message = MIMEMultipart()
        message["to"] = to
        message["subject"] = Header(subject, "utf-8")  # pyright: ignore[reportArgumentType]
        message.attach(MIMEText(html_body, "html", _charset="utf-8"))

        attachment = MIMEApplication(pdf_bytes, _subtype="pdf")
        attachment.add_header(
            "Content-Disposition", "attachment",
            filename=pdf_filename or "Zeiterfassung.pdf"
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
