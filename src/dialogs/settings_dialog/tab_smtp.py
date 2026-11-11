"""Liste „SMTP-Konten" im Versand-Tab: die konfigurierten Mail-Konten.

Aufbau und Ablauf teilt sie mit der Webhook-Liste (`_record_list_tab.py`, R12);
hier steht nur, was ihn davon unterscheidet. SMTP-Konten liegen in ihrem
eigenen, gerätelokalen Store und werden vom Unterdialog direkt gespeichert.
"""

from src import keyring_store, smtp_store
from src.dialogs.settings_dialog._record_list_tab import (
    RecordListKind, RecordListTab,
)
from src.dialogs.smtp_dialog import open_smtp_dialog
from src.i18n import t


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
    intro=lambda: t("liste_smtp.intro"),
    section=lambda: t("liste_smtp.abschnitt"),
    empty=lambda: t("liste_smtp.leer"),
    row_detail=lambda record: record.get("host", "?"),
    open_dialog=_open_dialog,
    remove_title=lambda: t("liste_smtp.entfernen_titel"),
    remove_error=lambda: t("liste_smtp.entfernen_fehler"),
    read_only_error=smtp_store.SmtpStoreReadOnly,
    after_delete=_delete_secret,
)


class SmtpTab(RecordListTab):
    KIND = SMTP_KIND
