"""Tab „Webhooks": Liste der konfigurierten HTTP-Ziele.

Aufbau und Ablauf teilt er mit dem SMTP-Tab (`_record_list_tab.py`, R12);
hier steht nur, was ihn davon unterscheidet. Webhooks liegen in ihrem
eigenen, gerätelokalen Store und werden vom Unterdialog direkt gespeichert.
"""

from urllib.parse import urlsplit

from src import webhook_secrets, webhook_store
from src.dialogs.settings_dialog._record_list_tab import (
    RecordListKind, RecordListTab,
)
from src.dialogs.webhook_dialog import open_webhook_dialog


def _open_dialog(parent, store, runner, **kwargs):
    # Beim Aufruf aufgelöst, nicht beim Import gebunden — so bleibt
    # `tab_webhooks.open_webhook_dialog` die eine Stelle, an der der
    # Unterdialog hängt.
    open_webhook_dialog(parent, store, runner, **kwargs)


def _forget_secret(webhook_id):
    # Wie tab_smtp._delete_secret: erst NACH dem erfolgreichen Schreiben
    # (remove_record ruft den Hook nur dann), und ein fehlender Eintrag ist
    # kein Fehler. Für Webhooks ohne Schlüsselbund-Secret ein No-op.
    webhook_secrets.forget_by_id(webhook_id)


WEBHOOKS_KIND = RecordListKind(
    intro=("Der Bericht kann zusätzlich zur E-Mail an HTTP-Endpunkte "
           "gesendet werden. Webhooks gelten nur auf diesem Gerät und "
           "werden sofort gespeichert — unabhängig vom „Speichern“ "
           "dieses Einstellungen-Dialogs."),
    row_detail=lambda record: urlsplit(record.get("url", "")).hostname or "?",
    open_dialog=_open_dialog,
    remove_title="Webhook entfernen",
    remove_error="Der Webhook konnte nicht entfernt werden:",
    read_only_error=webhook_store.WebhookStoreReadOnly,
    after_delete=_forget_secret,
)


class WebhooksTab(RecordListTab):
    KIND = WEBHOOKS_KIND
    title = "Webhooks"
