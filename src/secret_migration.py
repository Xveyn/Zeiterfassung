"""Umzug der Zugangsdaten in den Schlüsselbund beim Start (#101) — und das
Abräumen bei der Deinstallation (`forget_all`).

Idempotent und bei jedem Start geprüft — kein Versionsvergleich nötig: der
erste Start nach dem Update zieht um, ebenso ein Linux-System, das erst
später einen Secret Service bekommt. Pro Secret: in den Schlüsselbund
schreiben, zurücklesen, NUR bei Übereinstimmung die Datei neu schreiben.
Jeder Abbruch davor lässt die Datei gültig; der nächste Start holt nach.

Einzige Stelle, die umzieht — `token_store.save_credentials` behält den Ort
bei. Der Schlüsselbund wird nur gefragt, wenn es etwas umzuziehen gibt
(sonst löste jeder Start auf macOS einen Keychain-Dialog aus, Spec R4).
Tk-frei; läuft im BackgroundTaskRunner, nie vor dem Tk-Aufbau.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

from src import keyring_store, webhook_secrets
from src.oauth_utils import (
    REFRESH_TOKEN_KEY, REFRESH_TOKEN_LOCATION, new_token_keyring_key,
    read_token_meta, token_in_keyring, write_token_json,
)
from src.token_store import TOKEN_LOCK
from src.webhook_store import WebhookStoreReadOnly

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class MigrationReport:
    token_moved: bool = False
    webhooks_moved: tuple[str, ...] = ()
    failures: tuple[str, ...] = ()

    @property
    def moved_anything(self) -> bool:
        return self.token_moved or bool(self.webhooks_moved)


def _plaintext_refresh_token(token_path: str) -> str:
    meta = read_token_meta(token_path)
    if meta is None or token_in_keyring(meta):
        return ""
    token = meta.get("refresh_token")
    return token if isinstance(token, str) else ""


def _stored_and_verified(key: str, secret: str) -> bool:
    if not keyring_store.put(key, secret):
        return False
    if keyring_store.fetch(key) != secret:
        log.warning("Schlüsselbund liefert nach dem Schreiben einen anderen "
                    "Wert — Umzug unterbleibt")
        # Der Eintrag ist nicht verlässlich; stehen lassen hieße, ein
        # ungeprüftes Secret im Schlüsselbund zu hinterlassen.
        keyring_store.remove(key)
        return False
    return True


def _move_token(token_path: str, secret: str) -> bool:
    with TOKEN_LOCK:
        key = new_token_keyring_key()
        if not _stored_and_verified(key, secret):
            return False
        meta = read_token_meta(token_path)
        if meta is None or meta.get("refresh_token") != secret:
            # Zwischendurch neu geschrieben (Refresh, Rotation): der nächste
            # Start zieht den dann gültigen Token um.
            log.info("token.json hat sich während des Umzugs geändert")
            keyring_store.remove(key)
            return False
        meta.pop("refresh_token")
        meta[REFRESH_TOKEN_LOCATION] = "keyring"
        meta[REFRESH_TOKEN_KEY] = key
        try:
            write_token_json(json.dumps(meta), token_path)
        except OSError:
            log.warning("token.json ließ sich nach dem Umzug nicht schreiben",
                        exc_info=True)
            keyring_store.remove(key)
            return False
        return True


def _move_webhook(store: Any, record: dict[str, Any]) -> bool:
    secret = webhook_secrets.plaintext_secret(record)
    if not _stored_and_verified(webhook_secrets.keyring_key(record["id"]), secret):
        return False
    current = next((r for r in store.get_all() if r.get("id") == record["id"]), None)
    if current is None or webhook_secrets.plaintext_secret(current) != secret:
        log.info("Ein Webhook hat sich während des Umzugs geändert")
        return False
    try:
        store.save(webhook_secrets.stored_in_keyring(current))
    except (WebhookStoreReadOnly, OSError):
        log.warning("webhooks.json ließ sich nach dem Umzug nicht schreiben",
                    exc_info=True)
        return False
    return True


def migrate(token_path: str, webhook_store: Any | None) -> MigrationReport:
    """Zieht Klartext-Secrets um. Ohne Funde bleibt der Schlüsselbund
    unberührt und der Bericht leer."""
    token_secret = _plaintext_refresh_token(token_path)
    records = webhook_store.get_all() if webhook_store is not None else []
    pending = [r for r in records if webhook_secrets.plaintext_secret(r)]
    if not token_secret and not pending:
        return MigrationReport()

    failures: list[str] = []
    token_moved = False
    if token_secret:
        token_moved = _move_token(token_path, token_secret)
        if not token_moved:
            failures.append("Google-Anmeldung")
    moved: list[str] = []
    for record in pending:
        if _move_webhook(webhook_store, record):
            moved.append(str(record.get("name", "")))
        else:
            name = record.get("name", "")
            failures.append(f"Webhook „{name}“")
    return MigrationReport(token_moved, tuple(moved), tuple(failures))


def notice(report: MigrationReport, system: str) -> tuple[str, str]:
    """Titel und Text des einmaligen Hinweises nach einem Umzug."""
    parts = []
    if report.token_moved:
        parts.append("deine Google-Anmeldung")
    n = len(report.webhooks_moved)
    if n:
        parts.append(f"die Zugangsdaten von {n} Webhook" + ("s" if n > 1 else ""))
    what = " und ".join(parts)
    # „liegt" nur, wenn allein die Google-Anmeldung umgezogen ist —
    # „Zugangsdaten" ist Plural.
    verb = "liegt" if parts == ["deine Google-Anmeldung"] else "liegen"
    text = (f"{what[:1].upper()}{what[1:]} {verb} jetzt im Schlüsselbund des "
            "Betriebssystems statt im Klartext im Datenordner.")
    if system == "Darwin":
        text += ("\n\nmacOS kann nach App-Updates erneut fragen, ob Zeiterfassung "
                 "auf den Schlüsselbund zugreifen darf.")
    return "Zugangsdaten im Schlüsselbund", text


def toast_text(report: MigrationReport) -> str:
    """Kurzform für den Tray-Toast (Autostart mit --minimized)."""
    return "Zugangsdaten liegen jetzt im Schlüsselbund."
