# src/drive.py
"""Google Drive API Wrapper für den Multi-Device-Sync.

Hält die appDataFolder-spezifische Datei `zeiterfassung-sync.json`.
Scope: drive.appdata (non-sensitive, per-app-isolated).
"""

import io
import logging
import os

from src.oauth_utils import write_token

SYNC_FILENAME = "zeiterfassung-sync.json"
SYNC_MIMETYPE = "application/json"
DRIVE_APPDATA_SCOPE = "https://www.googleapis.com/auth/drive.appdata"


class DriveAuthError(Exception):
    """Token revoked oder Auth fehlgeschlagen — User muss neu verbinden."""


class DriveNetworkError(Exception):
    """Netzwerkproblem oder Drive-API nicht erreichbar."""


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


def _dedupe_sort_key(f):
    """Sortierschlüssel für mehrfach vorhandene Sync-Dateien: ältestes
    createdTime gewinnt, bei Gleichstand die kleinere id.

    Fehlt `createdTime` (Drive liefert das Feld nicht), rutscht die Datei ans
    Ende — sonst gälte sie als "ältestmöglich" und schlüge jeden echten
    Zeitstempel."""
    created = f.get("createdTime")
    return (created is None, created or "", f.get("id") or "")


def find_sync_file(service):
    """Listet appDataFolder und sucht nach SYNC_FILENAME. Liefert file_id oder None.

    Bei mehreren Treffern gewinnt deterministisch die ÄLTESTE Datei (Audit M3).
    Zwei Geräte können beim Erst-Setup gleichzeitig anlegen — der
    appDataFolder kennt kein atomares create-if-not-exists, die Race ist also
    nicht verhinderbar, nur ihre Folge. Ohne feste Regel nähme jedes Gerät
    irgendeinen Treffer: die Stände liefen auseinander (Split-Brain), und da
    die Drive-API ohne `orderBy` KEINE Sortierung garantiert, könnte sogar
    dasselbe Gerät zwischen zwei Syncs auf die jeweils andere Datei greifen —
    Einträge verschwänden und tauchten wieder auf. Mit der Regel konvergieren
    alle Geräte auf dieselbe Datei; die auseinandergelaufenen Stände führt der
    LWW-Merge beim nächsten Push wieder zusammen (jedes Gerät hält seinen
    Stand ja lokal).

    Sortiert wird bewusst lokal statt per `orderBy` — das Ergebnis hängt dann
    nicht vom Server-Verhalten ab und ist testbar.

    Wirft DriveNetworkError bei API-Fehlern."""
    try:
        result = service.files().list(
            spaces="appDataFolder",
            q=f"name = '{SYNC_FILENAME}'",
            fields="files(id, name, createdTime)",
            pageSize=10,
        ).execute()
    except HttpError as e:
        raise _http_error_to_drive_error(e) from e
    except (TransportError, TimeoutError) as e:
        # Verbindungsabbruch/Timeout beim Request selbst — es gibt keine
        # HTTP-Response, daher kein HttpError. Ohne diesen Fang landet der
        # Fehler unklassifiziert im 'unknown'-Fall der UI (roher, unstyled
        # Dialog statt der schon vorhandenen themed Netzwerk-Meldung).
        raise DriveNetworkError(str(e)) from e

    files = result.get("files", [])
    if not files:
        return None
    if len(files) > 1:
        # Der Nutzer sieht davon nichts (appDataFolder ist im Drive-UI
        # unsichtbar) — ohne Log wäre der Split-Brain nicht diagnostizierbar.
        logging.getLogger(__name__).warning(
            "Mehrere Sync-Dateien im appDataFolder (%d) — älteste gewinnt. "
            "Kandidaten: %s",
            len(files),
            [(f.get("id"), f.get("createdTime")) for f in files],
        )
    return min(files, key=_dedupe_sort_key)["id"]


def download(service, file_id):
    """Lädt die Sync-Datei herunter. Liefert (bytes, version_token).

    version_token ist in Drive API v3 keine ETag (die File-Ressource hat kein
    solches Feld), sondern die `version`-Nummer der Datei als String — monoton
    steigend, aber laut Doku auch bei serverseitigen Änderungen ohne fremden
    Push. Wird nur informativ zurückgegeben und **bewusst nicht** als
    Optimistic-Lock-Anker benutzt; die Begründung steht bei `upload`.

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
    except (TransportError, TimeoutError) as e:
        raise DriveNetworkError(str(e)) from e
    return buf.getvalue(), str(meta.get("version", ""))


def upload(service, content_bytes, file_id=None):
    """Uploadet `content_bytes` als Sync-Datei.

    - file_id=None  → neues File in appDataFolder anlegen
    - file_id gesetzt → update der bestehenden Datei

    Es gibt hier bewusst KEIN File-level Optimistic Locking — Konflikt-
    Erkennung passiert stattdessen im Push-Flow (`main.py::run_push_blocking`)
    doc-level über `sync.remote_is_newer` und pro-Eintrag über `modified_at`
    im Sync-Doc-Merge (Audit M2, entschieden in Xveyn/Zeiterfassung#46).

    Warum kein Locking (die Optionen sind geprüft, nicht übersehen):

    - Die File-Ressource der Drive API v3 hat **kein `etag`-Feld** mehr, und
      die v3-Referenz dokumentiert **keinen** Precondition-Mechanismus für
      Datei-Updates. Auf undokumentiertes If-Match-Verhalten baut der Sync
      nicht.
    - `version` (der von `download`/`upload` gelieferte Token) taugt nicht als
      Ersatz-Anker: laut Doku spiegelt er *„every change made to the file on
      the server, even those not visible to the user"* — er steigt also auch
      ohne fremden Push. Ein Retry-on-conflict darauf hätte False Positives.
      Vor allem aber wäre ein Check-dann-Upload selbst nicht atomar: das
      Fenster würde kleiner, nicht geschlossen. Eine verifizierte Heilung
      (s.u.) gegen eine kleinere Restwahrscheinlichkeit zu tauschen, lohnt
      nicht.
    - Drive **Content Restrictions** (`contentRestrictions.readOnly`) sind
      als Mutex ungeeignet und wären schlechter als der Status quo: Setzen
      *„overwrites the existing one"* (kein atomares Test-and-Set, dasselbe
      TOCTOU eine Ebene höher), und es gibt kein TTL/Lease — ein Absturz
      zwischen Lock und Unlock ließe die Sync-Datei dauerhaft gesperrt
      zurück (*„a new revision of the file may not be added"*). Aus einem
      selbstheilenden Clobber würde ein nicht selbstheilender Ausfall.

    Der akzeptierte Trade-off: Zwischen `download` und `upload` im Push liegt
    ein TOCTOU-Fenster (der `data_lock` klammert bewusst keine Netzwerk-Calls),
    in dem ein zweites Gerät hochladen kann — dessen Stand überschreibt unser
    Upload dann. Das ist toleriert, weil der Merge LWW pro Eintrag über
    `modified_at` ist: das geclobberte Gerät hat seine Einträge lokal weiter
    mit dem neueren Stempel und gewinnt sie beim nächsten Push zurück. Das
    `gc_watermark` wird als `max(local, remote)` gemergt, kann also nicht
    zurückfallen; die Konfliktliste ist Union-by-ID.

    **Grenze der Heilung:** Sie greift nur, solange beide Geräte weiter
    syncen. Wird ein Gerät direkt nach einem Clobber nie wieder gesynct
    (deinstalliert, Platte neu), ist sein letzter Push permanent verloren.
    Bei einem sekundenbreiten Fenster und Solo-Nutzung ist das akzeptiert —
    aber es ist der Grund, warum hier nicht pauschal „kein Datenverlust"
    steht.

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
        raise _http_error_to_drive_error(e) from e
    except (TransportError, TimeoutError) as e:
        raise DriveNetworkError(str(e)) from e
