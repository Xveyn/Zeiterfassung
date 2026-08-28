"""Worker-Kerne des Google-Tabs (R4, Stufe 2): Tk-frei, werfen nie.

Muster wie `send_task`/`share_task`/`mail_task` (Audit M10) und `oauth_task`
(H5): der blockierende Teil liegt hier und ist ohne Tk testbar, der Tab
behält nur `runner.run(fn, on_done)` und die Widget-Kosmetik im `on_done`.

Drei Kerne mit Result-Dict — `{"ok": True, …}` bzw.
`{"ok": False, "error": <Exception>, "tb": <traceback>}`. `error` ist bewusst
das **Exception-Objekt**, nicht `str(e)`: die Aufrufer formatieren es selbst in
ihre Meldung, und ein Objekt lässt sich im Test auf seinen Typ prüfen.

Dazu zwei `service_fn`-Einstiege für `oauth_task.build_oauth_enable_task` —
die **werfen** (der Builder fängt selbst) und liefern deshalb kein Dict.

`settings` wird hereingereicht statt ausgelesen: `fetch_sender_email`
persistiert die ermittelte Adresse hier im Worker, damit der Cache einen
Dialog-Close überlebt (dieselbe Regel wie in `oauth_task`).

Die Google-Wrapper (`mail`, `drive`, `gcal`) sind auf Modulebene importierbar —
ihre eigenen Google-Imports sind lazy, damit die CI ohne `requirements.txt`
durchläuft (wie in `send_task.py`/`sync_orchestrator.py`).
"""

import os
import traceback

from src import drive, gcal
from src.mail import fetch_user_email, get_gmail_service


def _paths(base_path):
    """(credentials.json, token.json) im Datenverzeichnis."""
    return (os.path.join(base_path, "credentials.json"),
            os.path.join(base_path, "token.json"))


def fetch_sender_email(settings, base_path):
    """OAuth-Flow + userinfo-Abruf. Persistiert die Adresse als `sender_email`.

    Liefert `{"ok": True, "email": <str|None>}` — `email` kann `None` sein,
    wenn der userinfo-Scope fehlt; das ist kein Fehler, sondern eine Anzeige
    ohne Wert. Nur bei einer echten Adresse wird geschrieben.
    """
    creds_path, token_path = _paths(base_path)
    try:
        get_gmail_service(
            creds_path, token_path,
            sync_enabled=settings.get("sync_enabled"),
            gcal_enabled=settings.get("gcal_enabled"),
        )
        email = fetch_user_email(
            token_path,
            sync_enabled=settings.get("sync_enabled"),
            gcal_enabled=settings.get("gcal_enabled"),
        )
    except Exception as e:
        return {"ok": False, "error": e, "tb": traceback.format_exc()}
    if email:
        settings.set("sender_email", email)   # Cache überlebt Close
    return {"ok": True, "email": email}


def load_calendars(settings, base_path):
    """Kalenderliste des angemeldeten Kontos. `{"ok": True, "items": [...]}`."""
    creds_path, token_path = _paths(base_path)
    try:
        service = gcal.get_calendar_service(
            creds_path, token_path,
            sync_enabled=settings.get("sync_enabled"),
        )
        items = gcal.list_calendars(service)
    except Exception as e:
        return {"ok": False, "error": e, "tb": traceback.format_exc()}
    return {"ok": True, "items": items}


def reconnect_drive(settings, base_path):
    """Erneuert die Google-Berechtigungen (frischer Consent). `{"ok": True}`."""
    creds_path, token_path = _paths(base_path)
    try:
        drive.reconnect(
            creds_path, token_path,
            gcal_enabled=settings.get("gcal_enabled"),
        )
    except Exception as e:
        return {"ok": False, "error": e, "tb": traceback.format_exc()}
    return {"ok": True}


def open_drive_service(settings, base_path):
    """`service_fn` für den Drive-Sync-Toggle — wirft bei Fehlschlag."""
    creds_path, token_path = _paths(base_path)
    drive.get_drive_service(
        creds_path, token_path,
        gcal_enabled=settings.get("gcal_enabled"),
    )


def open_calendar_service(settings, base_path):
    """`service_fn` für den Kalender-Toggle — wirft bei Fehlschlag."""
    creds_path, token_path = _paths(base_path)
    gcal.get_calendar_service(
        creds_path, token_path,
        sync_enabled=settings.get("sync_enabled"),
    )
