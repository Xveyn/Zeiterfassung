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
