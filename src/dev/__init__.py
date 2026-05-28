# src/dev/ — Entwickler-Modus. Wird nur bei `python -m src.main --dev` importiert.
import logging


def activate(base_path):
    """Installiert die Fakes (Monkeypatch) und seedet Sample-Daten.

    Aufzurufen aus main(), nachdem base_path feststeht und bevor Storage/
    Settings konstruiert werden (sie lesen die geseedeten Dateien)."""
    from src import drive, gcal, mail
    from src.dev import fakes, seed

    mail.get_gmail_service = fakes.fake_get_gmail_service
    mail.send_email = fakes.fake_send_email

    drive.get_drive_service = fakes.fake_get_drive_service
    drive.find_sync_file = fakes.fake_find_sync_file
    drive.download = fakes.fake_download
    drive.upload = fakes.fake_upload

    gcal.get_calendar_service = fakes.fake_get_calendar_service
    gcal.list_calendars = fakes.fake_list_calendars
    gcal.list_app_events = fakes.fake_list_app_events
    gcal.create_event = fakes.fake_create_event
    gcal.update_event = fakes.fake_update_event
    gcal.delete_event = fakes.fake_delete_event

    seed.seed_if_empty(base_path)
    logging.getLogger("zeiterfassung.dev").info(
        "Dev-Mode aktiviert — Daten=%s", base_path)
