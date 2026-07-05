"""Worker-Kern des Sende-Dialogs (Audit M10): Tk-frei, wirft nie.

Erzeugt die PDF, holt den Gmail-Service (kann einen OAuth-Browser-Flow
auslösen), sendet die Mail und cached best-effort die Absender-Adresse.
Persistenz (settings.set) passiert hier im Worker -> überlebt einen
Dialog-Close. Fehler kommen als Result-Dict (classify_mail_error) zurück,
nie als Exception.
"""

import logging

from src.dialogs.mail_task import classify_mail_error
from src.mail import fetch_user_email, get_gmail_service, send_email
from src.report import generate_pdf

log = logging.getLogger(__name__)


def perform_send(*, date_from, date_to, entries, name, categories,
                 category_breakdown, credentials_path, token_path,
                 recipient, subject, html, pdf_filename,
                 sync_enabled, gcal_enabled, settings):
    try:
        pdf_bytes = generate_pdf(
            date_from, date_to, entries, name=name,
            categories=categories, category_breakdown=category_breakdown)
        service = get_gmail_service(
            credentials_path, token_path,
            sync_enabled=sync_enabled, gcal_enabled=gcal_enabled)
        send_email(service, recipient, subject, html,
                   attachment_bytes=pdf_bytes,
                   attachment_filename=pdf_filename,
                   attachment_subtype="pdf")
    except FileNotFoundError as e:
        return classify_mail_error(e)
    except Exception as e:
        log.exception("Senden fehlgeschlagen")
        return classify_mail_error(e)

    # Nach erfolgreichem Send ist der Token frisch — Absender-Adresse cachen.
    try:
        email = fetch_user_email(
            token_path, sync_enabled=sync_enabled, gcal_enabled=gcal_enabled)
        if email and email != settings.get("sender_email"):
            settings.set("sender_email", email)
    except Exception:
        log.exception("sender_email fetch after send failed")

    return {"ok": True}
