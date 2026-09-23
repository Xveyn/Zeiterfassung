"""Tab „SMTP": Liste der konfigurierten Mail-Konten.

Aufbau und Ablauf teilt er mit dem Webhooks-Tab (`_record_list_tab.py`, R12);
hier steht nur, was ihn davon unterscheidet. SMTP-Konten liegen in ihrem
eigenen, gerätelokalen Store und werden vom Unterdialog direkt gespeichert.
"""

from src import keyring_store, smtp_store
from src.dialogs.settings_dialog._record_list_tab import (
    RecordListKind, RecordListTab,
)
from src.dialogs.smtp_dialog import open_smtp_dialog


def _open_dialog(parent, store, runner, **kwargs):
    # Beim Aufruf aufgelöst, nicht beim Import gebunden — so bleibt
    # `tab_smtp.open_smtp_dialog` die eine Stelle, an der der Unterdialog hängt.
    open_smtp_dialog(parent, store, runner, **kwargs)


def _delete_secret(account_id):
    # Erst NACH dem erfolgreichen Schreiben (`remove_record` ruft den Hook nur
    # dann): sonst stünde ein Konto ohne Passwort in der Datei. Der Store
    # selbst fasst den Schlüsselbund nicht an, damit er reine
    # Dateipersistenz bleibt.
    keyring_store.delete_secret(account_id)


SMTP_KIND = RecordListKind(
    intro=("Berichte können statt über die Gmail-API auch über einen "
           "eigenen Mail-Server verschickt werden. Jedes Konto hat "
           "seinen eigenen Empfänger und lässt sich beim Senden "
           "einzeln auswählen. Konten gelten nur auf diesem Gerät und "
           "werden sofort gespeichert — unabhängig vom „Abbrechen“ "
           "dieses Einstellungen-Dialogs."),
    row_detail=lambda record: record.get("host", "?"),
    open_dialog=_open_dialog,
    remove_title="SMTP-Konto entfernen",
    remove_error="Das SMTP-Konto konnte nicht entfernt werden:",
    read_only_error=smtp_store.SmtpStoreReadOnly,
    after_delete=_delete_secret,
)


class SmtpTab(RecordListTab):
    KIND = SMTP_KIND
    title = "SMTP"
