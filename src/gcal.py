# src/gcal.py
"""Google-Calendar-API-Wrapper für die Reservierungs-Anbindung.

Google-Imports liegen LAZY in den I/O-Funktionen — die CI installiert kein
requirements.txt, `import src.gcal` muss aber funktionieren (analog mail.py).
Die pure Helper `event_payload` / `parse_event` haben keine Google-Abhängigkeit.
"""

import datetime

from src.mail import get_scopes

# Marker in extendedProperties.private — über diesen findet der Pull "seine"
# Events; manuell angelegte Termine bleiben dadurch unangetastet.
APP_MARKER_KEY = "zeiterfassung"
APP_MARKER_VALUE = "reservation"

EVENT_SUMMARY = "Arbeitszeit (reserviert)"
EVENT_DESCRIPTION = "Von der Zeiterfassung verwaltete Reservierung."


def event_payload(date_str, start, end, modified_at):
    """Baut den Calendar-API-Event-Body aus einer Reservierung.

    date_str ISO ('YYYY-MM-DD'), start/end 'HH:MM'. Die dateTime-Werte tragen
    den lokalen UTC-Offset (`astimezone()`) — kein IANA-Zeitzonenname nötig.
    """
    day = datetime.date.fromisoformat(date_str)
    sh, sm = (int(p) for p in start.split(":"))
    eh, em = (int(p) for p in end.split(":"))
    start_dt = datetime.datetime(day.year, day.month, day.day, sh, sm).astimezone()
    end_dt = datetime.datetime(day.year, day.month, day.day, eh, em).astimezone()
    return {
        "summary": EVENT_SUMMARY,
        "description": EVENT_DESCRIPTION,
        "start": {"dateTime": start_dt.isoformat()},
        "end": {"dateTime": end_dt.isoformat()},
        "extendedProperties": {
            "private": {
                APP_MARKER_KEY: APP_MARKER_VALUE,
                "modified_at": modified_at,
            },
        },
    }


def parse_event(event):
    """Wandelt ein Calendar-API-Event in die Reservierungs-Form um.

    Liefert {date, start, end, modified_at, event_id} oder None, wenn das Event
    nicht den App-Marker trägt oder kein dateTime-Event ist (Ganztags-Events
    haben nur `date`).
    """
    private = (event.get("extendedProperties") or {}).get("private") or {}
    if private.get(APP_MARKER_KEY) != APP_MARKER_VALUE:
        return None
    start_raw = (event.get("start") or {}).get("dateTime")
    end_raw = (event.get("end") or {}).get("dateTime")
    if not start_raw or not end_raw:
        return None
    # Die Calendar-API liefert dateTime evtl. in einem anderen Offset (z.B. UTC)
    # zurück als gesendet — vor dem strftime auf lokale Zeit normalisieren.
    start_dt = datetime.datetime.fromisoformat(start_raw).astimezone()
    end_dt = datetime.datetime.fromisoformat(end_raw).astimezone()
    return {
        "date": start_dt.date().isoformat(),
        "start": start_dt.strftime("%H:%M"),
        "end": end_dt.strftime("%H:%M"),
        "modified_at": private.get("modified_at", ""),
        "event_id": event.get("id", ""),
    }


def get_calendar_service(credentials_path="credentials.json",
                         token_path="token.json", sync_enabled=False):
    """Authentifiziert gegen die Calendar API und liefert ein Service-Objekt.

    Fordert die VEREINIGUNG aller App-Scopes an (Gmail, Drive falls Sync,
    Calendar) — sonst verdrängte ein Calendar-Re-Consent die Gmail-/Drive-
    Scopes aus dem gemeinsamen token.json. Spiegelt get_gmail_service inkl.
    Scope-Upgrade-Erkennung. Google-Imports lazy (CI ohne requirements.txt).
    """
    import json as _json
    import os
    import stat

    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build

    scopes = get_scopes(sync_enabled, gcal_enabled=True)

    def _write(c):
        with open(token_path, "w") as f:
            f.write(c.to_json())
        try:
            os.chmod(token_path, stat.S_IRUSR | stat.S_IWUSR)  # 0o600
        except OSError:
            pass

    creds = None
    if os.path.exists(token_path):
        creds = Credentials.from_authorized_user_file(token_path, scopes)
        # Scope-Upgrade-Erkennung: hat der Token nicht alle Scopes, frischer Flow.
        try:
            with open(token_path, "r", encoding="utf-8") as f:
                granted = set(_json.load(f).get("scopes") or [])
            if not set(scopes).issubset(granted):
                creds = None
                try:
                    os.remove(token_path)
                except OSError:
                    pass
        except Exception:
            pass

    if creds and creds.expired and creds.refresh_token:
        # Spiegelt get_gmail_service: ein ungültiger Refresh-Token (RefreshError)
        # führt zum frischen OAuth-Flow; ein Netzwerkfehler (TransportError)
        # propagiert, statt einen aussichtslosen Browser-Flow zu starten.
        from google.auth.exceptions import RefreshError
        try:
            creds.refresh(Request())
            _write(creds)
        except RefreshError:
            creds = None

    if not creds or not creds.valid:
        if not os.path.exists(credentials_path):
            raise FileNotFoundError(
                f"credentials.json nicht gefunden unter:\n{credentials_path}"
            )
        flow = InstalledAppFlow.from_client_secrets_file(credentials_path, scopes)
        creds = flow.run_local_server(port=0)
        _write(creds)

    return build("calendar", "v3", credentials=creds)


def list_calendars(service):
    """Liefert [{"id", "summary"}] aller Kalender des Users — für das Dropdown.
    Paginiert, damit auch Accounts mit sehr vielen Kalendern vollständig
    erfasst werden (analog list_app_events)."""
    calendars = []
    page_token = None
    while True:
        resp = service.calendarList().list(pageToken=page_token).execute()
        for c in resp.get("items", []):
            calendars.append({"id": c["id"], "summary": c.get("summary", c["id"])})
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    return calendars


def list_app_events(service, calendar_id):
    """Listet alle von der App angelegten Events des Kalenders.

    Serverseitiger Filter über das App-Marker-Property. Liefert eine Liste
    geparster Reservierungs-Dicts ({date, start, end, modified_at, event_id}).
    """
    events = []
    page_token = None
    while True:
        resp = service.events().list(
            calendarId=calendar_id,
            privateExtendedProperty=f"{APP_MARKER_KEY}={APP_MARKER_VALUE}",
            singleEvents=True,
            maxResults=2500,
            pageToken=page_token,
        ).execute()
        for ev in resp.get("items", []):
            parsed = parse_event(ev)
            if parsed is not None:
                events.append(parsed)
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    return events


def create_event(service, calendar_id, date_str, start, end, modified_at):
    """Legt ein Event an und liefert dessen event_id."""
    body = event_payload(date_str, start, end, modified_at)
    created = service.events().insert(calendarId=calendar_id, body=body).execute()
    return created["id"]


def update_event(service, calendar_id, event_id, date_str, start, end, modified_at):
    """Überschreibt ein bestehendes Event mit den Reservierungs-Werten."""
    body = event_payload(date_str, start, end, modified_at)
    service.events().update(
        calendarId=calendar_id, eventId=event_id, body=body,
    ).execute()


def delete_event(service, calendar_id, event_id):
    """Löscht ein Event. Ein bereits gelöschtes Event (404/410) ist kein Fehler."""
    try:
        service.events().delete(
            calendarId=calendar_id, eventId=event_id,
        ).execute()
    except Exception as e:
        status = getattr(getattr(e, "resp", None), "status", None)
        if status in (404, 410):
            return
        raise
