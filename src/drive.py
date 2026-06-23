# src/drive.py
"""Google Drive API Wrapper für den Multi-Device-Sync.

Hält die appDataFolder-spezifische Datei `zeiterfassung-sync.json`.
Scope: drive.appdata (non-sensitive, per-app-isolated).
"""

import io
import os

from src.oauth_utils import write_token

SYNC_FILENAME = "zeiterfassung-sync.json"
SYNC_MIMETYPE = "application/json"
DRIVE_APPDATA_SCOPE = "https://www.googleapis.com/auth/drive.appdata"


class DriveAuthError(Exception):
    """Token revoked oder Auth fehlgeschlagen — User muss neu verbinden."""


class DriveNetworkError(Exception):
    """Netzwerkproblem oder Drive-API nicht erreichbar."""


class DriveConflictError(Exception):
    """ETag-Mismatch beim Upload — Remote wurde inzwischen verändert."""


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


def _http_error_to_drive_error(e):
    """Mappt einen googleapiclient HttpError auf die passende Drive-Fehlerklasse.

    403 ('insufficient authentication scopes' / 'insufficientPermissions') ist
    ein Berechtigungs-/Scope-Problem: die API hat geantwortet, es ist KEIN
    Netzfehler. Der gespeicherte Token deckt einen benötigten Scope nicht ab →
    DriveAuthError, damit das UI zur Neuverbindung (Re-Consent) auffordert.
    Alles andere bleibt DriveNetworkError."""
    resp_obj = getattr(e, "resp", None)
    status = getattr(resp_obj, "status", None) if resp_obj is not None else None
    if status == 403:
        return DriveAuthError(str(e))
    return DriveNetworkError(str(e))


SYNC_SCOPES = [
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/userinfo.email",
    DRIVE_APPDATA_SCOPE,
]


def get_drive_service(credentials_path, token_path, gcal_enabled=False):
    """OAuth mit kombinierten Scopes (Gmail + Drive appdata, optional Calendar).
    Token wird mit allen Scopes geschrieben — Gmail send und Calendar
    funktionieren weiter mit demselben token.json. Wirft DriveAuthError oder
    DriveNetworkError bei Problemen."""
    if (Credentials is None or InstalledAppFlow is None
            or Request is None or build is None):
        raise ImportError(
            "Google-API-Libs fehlen — google-api-python-client und "
            "google-auth-oauthlib müssen installiert sein."
        )
    scopes = list(SYNC_SCOPES)
    if gcal_enabled:
        scopes.append("https://www.googleapis.com/auth/calendar.events")
        scopes.append("https://www.googleapis.com/auth/calendar.calendarlist.readonly")

    creds = None
    if os.path.exists(token_path):
        creds = Credentials.from_authorized_user_file(token_path, scopes)

    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
        except RefreshError as e:
            raise DriveAuthError(str(e)) from e
        except TransportError as e:
            raise DriveNetworkError(str(e)) from e
        write_token(creds, token_path)

    if not creds or not creds.valid:
        if not os.path.exists(credentials_path):
            raise FileNotFoundError(
                f"credentials.json nicht gefunden unter:\n{credentials_path}"
            )
        flow = InstalledAppFlow.from_client_secrets_file(credentials_path, scopes)
        creds = flow.run_local_server(port=0)
        write_token(creds, token_path)

    return build("drive", "v3", credentials=creds)


def reconnect(credentials_path, token_path, gcal_enabled=False):
    """Erzwingt einen frischen OAuth-Consent: löscht ein vorhandenes token.json
    und startet den vollen Flow neu (über get_drive_service ohne Token).

    Nötig, weil ein gespeicherter Token, der einen inzwischen benötigten Scope
    NICHT abdeckt, weder über `creds.valid` (ignoriert Scopes) noch über einen
    Refresh (fordert fehlende Scopes nicht nach) ersetzt wird — der Consent-
    Screen erscheint nur, wenn kein Token existiert. Holt mit den aktuellen
    Scopes (inkl. Calendar bei gcal_enabled) neu ein."""
    try:
        os.remove(token_path)
    except FileNotFoundError:
        pass
    return get_drive_service(credentials_path, token_path, gcal_enabled=gcal_enabled)


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
        raise _http_error_to_drive_error(e) from e

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
    if MediaIoBaseDownload is None:
        raise ImportError("googleapiclient fehlt — Drive-Sync nicht verfügbar.")
    try:
        meta = service.files().get(fileId=file_id, fields="version").execute()
        request = service.files().get_media(fileId=file_id)
        buf = io.BytesIO()
        downloader = MediaIoBaseDownload(buf, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()
    except HttpError as e:
        raise _http_error_to_drive_error(e) from e
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
    if MediaIoBaseUpload is None:
        raise ImportError("googleapiclient fehlt — Drive-Sync nicht verfügbar.")
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
        # googleapiclient's HttpError trägt e.resp (httplib2.Response) — der
        # Fallback oben aliased HttpError auf Exception, daher kennt Pylance
        # das Attribut nicht statisch. getattr() umgeht das sauber.
        resp_obj = getattr(e, "resp", None)
        status = getattr(resp_obj, "status", None) if resp_obj is not None else None
        if status == 412:
            raise DriveConflictError(str(e)) from e
        raise _http_error_to_drive_error(e) from e
