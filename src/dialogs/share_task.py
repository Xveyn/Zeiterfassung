"""Worker-Kern des Teilen-Dialogs (Audit M10): Tk-frei, wirft nie.

Der Share-Doc-Bau + die Serialisierung laufen auf dem UI-Thread (schnell,
Klick-Zeit-Snapshot); dieser Worker bekommt den fertigen `payload` und
erledigt nur den blockierenden Teil: Transport aufbauen (evtl. OAuth oder
Schlüsselbund-Zugriff) + senden + optional Standard-Empfänger persistieren.

`transport=None` ist der Gmail-Weg; ein SMTP-Record schickt stattdessen über
dieses Konto. Der Empfänger kommt in **beiden** Fällen aus `recipient`, also
aus dem Eingabefeld des Dialogs — das `recipient`-Feld eines SMTP-Kontos
bezeichnet etwas anderes (wohin dieses Konto den Bericht schickt).
"""

import logging

from src import keyring_store, smtp
from src.dialogs.mail_task import classify_mail_error
from src.mail import get_gmail_service, send_email

log = logging.getLogger(__name__)


def perform_share(*, payload, filename, credentials_path, token_path,
                  recipient, subject, html, sync_enabled, gcal_enabled,
                  save_default, settings, transport=None):
    if transport is None:
        result = _share_via_gmail(
            payload=payload, filename=filename,
            credentials_path=credentials_path, token_path=token_path,
            recipient=recipient, subject=subject, html=html,
            sync_enabled=sync_enabled, gcal_enabled=gcal_enabled)
    else:
        result = _share_via_smtp(
            record=transport, payload=payload, filename=filename,
            recipient=recipient, subject=subject, html=html)

    if not result["ok"]:
        return result
    if save_default:
        settings.set("share_recipient", recipient)
    return result


def _share_via_gmail(*, payload, filename, credentials_path, token_path,
                     recipient, subject, html, sync_enabled, gcal_enabled):
    try:
        service = get_gmail_service(
            credentials_path, token_path,
            sync_enabled=sync_enabled, gcal_enabled=gcal_enabled)
        send_email(service, recipient, subject, html,
                   attachment_bytes=payload,
                   attachment_filename=filename,
                   attachment_subtype="json")
    except FileNotFoundError as e:
        return classify_mail_error(e)
    except Exception as e:
        log.exception("Teilen fehlgeschlagen")
        return classify_mail_error(e)
    return {"ok": True}


def _share_via_smtp(*, record, payload, filename, recipient, subject, html):
    try:
        password = keyring_store.get_secret(record)
        smtp.send(record, password, subject=subject, html=html, to=recipient,
                  attachment_bytes=payload,
                  attachment_filename=filename,
                  attachment_subtype="json")
    except Exception as e:
        log.exception("Teilen über SMTP-Konto %r fehlgeschlagen",
                      record.get("name"))
        return smtp.classify_smtp_error(e)
    return {"ok": True}
