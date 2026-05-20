# src/gcal.py
"""Google-Calendar-API-Wrapper für die Reservierungs-Anbindung.

Google-Imports liegen LAZY in den I/O-Funktionen — die CI installiert kein
requirements.txt, `import src.gcal` muss aber funktionieren (analog mail.py).
Die pure Helper `event_payload` / `parse_event` haben keine Google-Abhängigkeit.
"""

import datetime

CALENDAR_EVENTS_SCOPE = "https://www.googleapis.com/auth/calendar.events"
CALENDAR_LIST_SCOPE = "https://www.googleapis.com/auth/calendar.calendarlist.readonly"

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
