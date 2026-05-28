"""Fake-Implementierungen der Google-Eintrittspunkte für den Dev-Mode.

Alle Funktionen spiegeln die Signaturen der echten Wrapper in src/mail.py,
src/drive.py und src/gcal.py. Sie führen keine Netzwerk-Calls aus, liefern
kanonische Erfolge und loggen, was passiert wäre. Der Drive- und Kalender-
State lebt prozessweit als Modul-Globals.
"""

import json
import logging

log = logging.getLogger("zeiterfassung.dev")


class _FakeService:
    """Platzhalter-Objekt, das die gemockten Builder zurückgeben. Wird nur
    durchgereicht, nie aufgerufen."""


_drive_doc = None        # dict | None
_drive_version = 0
_events = {}             # event_id -> {date, start, end, modified_at, event_id}
_event_counter = 0
_msg_counter = 0
_simulate_auth_error = False


def reset_state():
    """Setzt Drive-Doc, Kalender und Zähler zurück (für 'Sample-Daten neu laden')."""
    global _drive_doc, _drive_version, _events, _event_counter, _msg_counter
    global _simulate_auth_error
    _drive_doc = None
    _drive_version = 0
    _events = {}
    _event_counter = 0
    _msg_counter = 0
    _simulate_auth_error = False


def simulate_auth_error_once():
    """Lässt den nächsten Service-Builder-Aufruf einmalig TokenAuthError werfen."""
    global _simulate_auth_error
    _simulate_auth_error = True


def _maybe_raise_auth():
    global _simulate_auth_error
    if _simulate_auth_error:
        _simulate_auth_error = False
        from src.mail import TokenAuthError
        log.warning("DEV: simulierter TokenAuthError")
        raise TokenAuthError("DEV: simulierter Token-Fehler")


# --- Gmail ---------------------------------------------------------------

def fake_get_gmail_service(credentials_path="credentials.json",
                           token_path="token.json",
                           sync_enabled=False, gcal_enabled=False):
    _maybe_raise_auth()
    log.info("DEV fake_get_gmail_service()")
    return _FakeService()


def fake_send_email(service, to, subject, html_body,
                    attachment_bytes=None, attachment_filename=None,
                    attachment_subtype="pdf",
                    pdf_bytes=None, pdf_filename=None):
    global _msg_counter
    _msg_counter += 1
    filename = attachment_filename or pdf_filename
    log.info("DEV: würde Mail senden an=%s betreff=%s anhang=%s",
             to, subject, filename)
    return f"dev-msg-{_msg_counter}"


# --- Drive ---------------------------------------------------------------

def fake_get_drive_service(credentials_path, token_path, gcal_enabled=False):
    _maybe_raise_auth()
    log.info("DEV fake_get_drive_service()")
    return _FakeService()


def fake_find_sync_file(service):
    return "dev-file" if _drive_doc is not None else None


def fake_download(service, file_id):
    payload = _drive_doc if _drive_doc is not None else {}
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    log.info("DEV fake_download() version=%s", _drive_version)
    return data, str(_drive_version)


def fake_upload(service, content_bytes, file_id=None, expected_etag=None):
    global _drive_doc, _drive_version
    _drive_doc = json.loads(content_bytes)
    _drive_version += 1
    log.info("DEV fake_upload() -> version=%s", _drive_version)
    return "dev-file", str(_drive_version)


# --- Calendar ------------------------------------------------------------

def fake_get_calendar_service(credentials_path="credentials.json",
                              token_path="token.json", sync_enabled=False):
    _maybe_raise_auth()
    log.info("DEV fake_get_calendar_service()")
    return _FakeService()


def fake_list_app_events(service, calendar_id):
    return [dict(ev) for ev in _events.values()]


def fake_create_event(service, calendar_id, date_str, start, end, modified_at):
    global _event_counter
    _event_counter += 1
    event_id = f"dev-evt-{_event_counter}"
    _events[event_id] = {
        "date": date_str, "start": start, "end": end,
        "modified_at": modified_at, "event_id": event_id,
    }
    log.info("DEV fake_create_event() id=%s date=%s", event_id, date_str)
    return event_id


def fake_update_event(service, calendar_id, event_id, date_str, start, end, modified_at):
    _events[event_id] = {
        "date": date_str, "start": start, "end": end,
        "modified_at": modified_at, "event_id": event_id,
    }
    log.info("DEV fake_update_event() id=%s", event_id)


def fake_delete_event(service, calendar_id, event_id):
    _events.pop(event_id, None)
    log.info("DEV fake_delete_event() id=%s", event_id)
