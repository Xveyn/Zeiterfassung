# src/drive.py
"""Google Drive API Wrapper für den Multi-Device-Sync.

Hält die appDataFolder-spezifische Datei `zeiterfassung-sync.json`.
Scope: drive.appdata (non-sensitive, per-app-isolated).
"""

SYNC_FILENAME = "zeiterfassung-sync.json"
SYNC_MIMETYPE = "application/json"
DRIVE_APPDATA_SCOPE = "https://www.googleapis.com/auth/drive.appdata"


class DriveAuthError(Exception):
    """Token revoked oder Auth fehlgeschlagen — User muss neu verbinden."""


class DriveNetworkError(Exception):
    """Netzwerkproblem oder Drive-API nicht erreichbar."""


class DriveConflictError(Exception):
    """ETag-Mismatch beim Upload — Remote wurde inzwischen verändert."""


import io
import os
import stat

try:
    from google.auth.exceptions import RefreshError, TransportError
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError
    from googleapiclient.http import MediaIoBaseDownload, MediaIoBaseUpload
except ImportError:
    Credentials = None  # type: ignore
    InstalledAppFlow = None  # type: ignore
    build = None  # type: ignore
    Request = None  # type: ignore
    RefreshError = Exception  # type: ignore
    TransportError = Exception  # type: ignore
    HttpError = Exception  # type: ignore
    MediaIoBaseDownload = None  # type: ignore
    MediaIoBaseUpload = None  # type: ignore


SYNC_SCOPES = [
    "https://www.googleapis.com/auth/gmail.send",
    DRIVE_APPDATA_SCOPE,
]


def _write_token(creds, token_path):
    with open(token_path, "w") as f:
        f.write(creds.to_json())
    try:
        os.chmod(token_path, stat.S_IRUSR | stat.S_IWUSR)  # 0o600
    except OSError:
        pass


def get_drive_service(credentials_path, token_path):
    """OAuth mit kombinierten Scopes (Gmail + Drive appdata). Token wird mit
    beiden Scopes geschrieben — Gmail send funktioniert weiter mit demselben
    token.json. Wirft DriveAuthError oder DriveNetworkError bei Problemen."""
    creds = None
    if os.path.exists(token_path):
        creds = Credentials.from_authorized_user_file(token_path, SYNC_SCOPES)

    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
        except RefreshError as e:
            raise DriveAuthError(str(e)) from e
        except TransportError as e:
            raise DriveNetworkError(str(e)) from e
        _write_token(creds, token_path)

    if not creds or not creds.valid:
        if not os.path.exists(credentials_path):
            raise FileNotFoundError(
                f"credentials.json nicht gefunden unter:\n{credentials_path}"
            )
        flow = InstalledAppFlow.from_client_secrets_file(credentials_path, SYNC_SCOPES)
        creds = flow.run_local_server(port=0)
        _write_token(creds, token_path)

    return build("drive", "v3", credentials=creds)
