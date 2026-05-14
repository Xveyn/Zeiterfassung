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


def find_sync_file(service):
    """Listet appDataFolder und sucht nach SYNC_FILENAME. Liefert file_id oder None.
    Wirft DriveNetworkError bei API-Fehlern."""
    try:
        result = service.files().list(
            spaces="appDataFolder",
            q=f"name = '{SYNC_FILENAME}'",
            fields="files(id, name)",
            pageSize=10,
        ).execute()
    except HttpError as e:
        raise DriveNetworkError(str(e)) from e

    files = result.get("files", [])
    if not files:
        return None
    return files[0]["id"]


def download(service, file_id):
    """Lädt die Sync-Datei herunter. Liefert (bytes, version_token).

    version_token ist in Drive API v3 keine echte ETag mehr (das Feld wurde
    in v3 entfernt), sondern die `version`-Nummer der Datei als String —
    monoton steigend, eindeutig pro Modifikation. Wird nur informativ
    zurückgegeben; aktuell ohne Optimistic-Lock-Verwendung beim Push.

    Wirft DriveNetworkError bei API-Fehlern."""
    try:
        meta = service.files().get(fileId=file_id, fields="version").execute()
        request = service.files().get_media(fileId=file_id)
        buf = io.BytesIO()
        downloader = MediaIoBaseDownload(buf, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()
    except HttpError as e:
        raise DriveNetworkError(str(e)) from e
    return buf.getvalue(), str(meta.get("version", ""))


def upload(service, content_bytes, file_id=None, expected_etag=None):
    """Uploadet `content_bytes` als Sync-Datei.

    - file_id=None  → neues File in appDataFolder anlegen
    - file_id gesetzt → update der bestehenden Datei

    Drive API v3 kennt kein `etag`-Feld mehr und unterstützt kein
    granulares If-Match auf Datei-Updates ohne HTTP-Header-Tricks, die
    googleapiclient nicht sauber freilegt. Die `expected_etag`-Signatur
    bleibt aus Kompatibilitätsgründen erhalten, wird aber ignoriert.
    Konflikt-Erkennung passiert pro-Eintrag über `modified_at` im
    Sync-Doc-Merge, nicht auf File-Ebene.

    Liefert (file_id, new_version_token).
    """
    media = MediaIoBaseUpload(io.BytesIO(content_bytes),
                                mimetype=SYNC_MIMETYPE,
                                resumable=False)
    try:
        if file_id is None:
            metadata = {"name": SYNC_FILENAME, "parents": ["appDataFolder"]}
            resp = service.files().create(
                body=metadata, media_body=media, fields="id, version",
            ).execute()
            return resp["id"], str(resp.get("version", ""))
        resp = service.files().update(
            fileId=file_id, media_body=media, fields="id, version",
        ).execute()
        return resp["id"], str(resp.get("version", ""))
    except HttpError as e:
        status = getattr(e.resp, "status", None) if hasattr(e, "resp") else None
        if status == 412:
            raise DriveConflictError(str(e)) from e
        raise DriveNetworkError(str(e)) from e
