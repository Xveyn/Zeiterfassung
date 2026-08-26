"""Gerätelokale Persistenz der Webhook-Konfiguration (Tk-frei, stdlib-only).

`webhooks.json` liegt neben `token.json` im Datenverzeichnis und enthält
Konfiguration UND Secrets. Sie wird deshalb wie `token.json` gehärtet
geschrieben (chmod 0600 + icacls auf der Temp-Datei, dann os.replace) — der
dritte Secret-Schreibpfad der App, siehe src/CLAUDE.md.

Nichts hiervon reist per Drive-Sync: Webhooks sind bewusst gerätelokal, damit
kein Secret im Sync-Doc landet.
"""

from __future__ import annotations

import copy
import datetime
import json
import logging
import os
import stat
import tempfile
import threading
import time
import uuid
from typing import Any

from src.secure_file import harden_windows_acl
from src.webhook import validate_url

log = logging.getLogger(__name__)

SCHEMA_VERSION = 1

Webhook = dict[str, Any]

_REQUIRED_KEYS = ("id", "name", "url", "enabled", "payload", "auth")
_AUTH_MODES = ("none", "header", "hmac")


class WebhookStoreReadOnly(Exception):
    """Die Datei darf nicht überschrieben werden (neuere schema_version oder
    beim Start nicht lesbar). Der Aufrufer zeigt das als themed Fehlerdialog —
    ein still verworfener Speichervorgang wäre schlimmer als ein Fehler."""


def new_id() -> str:
    """Stabile Kennung eines Webhooks. Trägt die Zuordnung, wenn der Nutzer
    den Namen ändert."""
    return uuid.uuid4().hex


def _is_wellformed(record: Any) -> bool:
    """Strukturprüfung fürs Laden — absichtlich schwächer als validate_record.
    Hier geht es nur darum, ob mit dem Datensatz überhaupt zu arbeiten ist."""
    if not isinstance(record, dict):
        return False
    if any(k not in record for k in _REQUIRED_KEYS):
        return False
    if not isinstance(record.get("payload"), dict):
        return False
    auth = record.get("auth")
    if not isinstance(auth, dict) or auth.get("mode") not in _AUTH_MODES:
        return False
    # URL mitprüfen: sonst erschiene ein Eintrag mit kaputter oder unsicherer
    # Adresse in der Ziel-Auswahl und scheiterte erst beim Senden.
    ok, _msg = validate_url(record.get("url", ""))
    return ok


def validate_record(record: Webhook, existing: list[Webhook]) -> tuple[bool, str]:
    """Prüft einen im Dialog bearbeiteten Datensatz. (ok, deutsche Begründung).

    `existing` ist die aktuelle Liste; der Datensatz selbst (gleiche `id`) wird
    beim Namens-Vergleich ausgenommen, sonst könnte man einen Webhook nicht
    speichern, ohne ihn umzubenennen.
    """
    name = (record.get("name") or "").strip()
    if not name:
        return False, "Bitte einen Namen angeben."
    for other in existing:
        if other.get("id") != record.get("id") and \
                (other.get("name") or "").strip().lower() == name.lower():
            return False, f"Es gibt bereits einen Webhook namens „{name}“."

    ok, msg = validate_url(record.get("url", ""))
    if not ok:
        return False, msg

    payload = record.get("payload") or {}
    if not payload.get("json") and not payload.get("pdf"):
        return False, "Bitte mindestens JSON oder PDF auswählen."

    auth = record.get("auth") or {}
    mode = auth.get("mode")
    if mode == "header":
        if not (auth.get("header") or "").strip():
            return False, "Bitte einen Header-Namen angeben."
        if not (auth.get("value") or "").strip():
            return False, "Bitte einen Header-Wert (Token) angeben."
    elif mode == "hmac":
        if not (auth.get("header") or "").strip():
            return False, "Bitte einen Header-Namen angeben."
        if not (auth.get("secret") or "").strip():
            return False, "Bitte ein Secret für die Signatur angeben."
    elif mode != "none":
        return False, "Unbekanntes Auth-Verfahren."
    return True, ""


class WebhookStore:
    def __init__(self, filepath: str = "webhooks.json",
                 lock: threading.RLock | None = None) -> None:
        self.filepath = filepath
        # Geteilter Daten-Lock (Audit H1/H2) — siehe storage.py.
        self._lock = lock if lock is not None else threading.RLock()
        self._webhooks: list[Webhook] = []
        self._readonly = False
        self._load()

    def _load(self) -> None:
        if not os.path.exists(self.filepath):
            return
        try:
            with open(self.filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
        except OSError:
            # KEINE Quarantäne: ein kurzzeitig gesperrtes File (Virenscanner,
            # Backup, Netzlaufwerk) ist kein defektes File. Umbenennen hieße
            # hier, eine intakte Konfiguration samt Secrets wegzuwerfen — der
            # nächste save() legte eine frische leere Datei an. settings.py
            # macht diese Unterscheidung schon richtig; conflicts_store.py
            # nicht, das ist kein Vorbild.
            self._readonly = True
            log.warning("webhooks.json nicht lesbar — starte ohne Webhooks, "
                        "die Datei wird nicht überschrieben", exc_info=True)
            return
        except (json.JSONDecodeError, ValueError):
            self._quarantine("JSON nicht parsebar")
            return
        if not isinstance(data, dict):
            self._quarantine(f"unerwartetes Toplevel-Format ({type(data).__name__})")
            return

        version = data.get("schema_version")
        if isinstance(version, int) and not isinstance(version, bool) \
                and version > SCHEMA_VERSION:
            # Nicht anfassen: ein älterer Build darf eine neuere Datei nicht
            # überschreiben. Lieber ohne Webhooks laufen.
            self._readonly = True
            log.warning(
                "webhooks.json hat schema_version %s (bekannt: %s) — die Datei "
                "wird nicht gelesen und nicht überschrieben.",
                version, SCHEMA_VERSION)
            return

        raw = data.get("webhooks")
        if not isinstance(raw, list):
            return
        for record in raw:
            if _is_wellformed(record):
                self._webhooks.append(record)
            else:
                # NIEMALS den Datensatz selbst loggen — er enthält das Token
                # bzw. HMAC-Secret, und logs/zeiterfassung.log ist ungehärtet
                # und genau die Datei, die Nutzer bei Problemen anhängen.
                log.warning(
                    "webhooks.json: Datensatz übersprungen (id=%r, name=%r)",
                    (record or {}).get("id") if isinstance(record, dict) else None,
                    (record or {}).get("name") if isinstance(record, dict) else None,
                )

    def _quarantine(self, reason: str) -> None:
        """Verschiebt die kaputte Datei nach `.corrupt-<stamp>` statt sie
        kommentarlos zu verwerfen (Muster wie settings/conflicts_store)."""
        stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        target = f"{self.filepath}.corrupt-{stamp}"
        try:
            os.replace(self.filepath, target)
        except OSError:
            log.warning("webhooks.json korrupt (%s); Quarantäne-Rename "
                        "fehlgeschlagen — starte ohne Webhooks", reason,
                        exc_info=True)
            return
        log.warning("webhooks.json korrupt (%s) — nach %s in Quarantäne "
                    "verschoben, starte ohne Webhooks",
                    reason, os.path.basename(target))

    def _save_to_disk(self) -> None:
        """Atomar und gehärtet — derselbe Ablauf wie oauth_utils.write_token.

        chmod und icacls laufen auf der TEMP-Datei: sonst gäbe es ein Fenster,
        in dem webhooks.json schon am Zielpfad steht, aber noch die geerbten
        Rechte trägt.
        """
        if self._readonly:
            # Lautlos zurückkehren wäre die schlechteste Variante: der Dialog
            # schlösse sich, die Liste zeigte den Eintrag (er steht in
            # self._webhooks), auf Platte stünde nichts — auffallen würde es
            # erst nach dem Neustart.
            raise WebhookStoreReadOnly(
                "Die Webhook-Datei stammt von einer neueren Version oder ist "
                "nicht lesbar und wird deshalb nicht überschrieben.")
        payload = {"schema_version": SCHEMA_VERSION, "webhooks": self._webhooks}
        directory = os.path.dirname(os.path.abspath(self.filepath))
        fd, tmp_path = tempfile.mkstemp(
            dir=directory, prefix=".webhooks-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())
            try:
                os.chmod(tmp_path, stat.S_IRUSR | stat.S_IWUSR)  # 0o600
            except OSError:
                pass
            harden_windows_acl(tmp_path)
            # Retry wie in oauth_utils.write_token (#135/#117): ein
            # Virenscanner, der die frische Temp-Datei greift — die gerade per
            # icacls neu ge-ACLt wurde —, blockiert den Rename kurzzeitig.
            # Gezielt PermissionError, damit echte Fehler nicht maskiert werden.
            attempts = 5
            for attempt in range(attempts):
                try:
                    os.replace(tmp_path, self.filepath)
                    break
                except PermissionError:
                    if attempt == attempts - 1:
                        raise
                    time.sleep(0.2)
        except BaseException:
            try:
                os.remove(tmp_path)
            except OSError:
                pass
            raise

    def get_all(self) -> list[Webhook]:
        # deepcopy, nicht dict(): `auth` und `payload` sind verschachtelt, eine
        # flache Kopie ließe den Aufrufer den Store-Inhalt mutieren.
        with self._lock:
            return copy.deepcopy(self._webhooks)

    def enabled(self) -> list[Webhook]:
        with self._lock:
            return copy.deepcopy(
                [w for w in self._webhooks if w.get("enabled")])

    def get(self, webhook_id: str) -> Webhook | None:
        with self._lock:
            for w in self._webhooks:
                if w.get("id") == webhook_id:
                    return copy.deepcopy(w)
            return None

    def save(self, record: Webhook) -> None:
        """Legt an oder ersetzt nach `id`.

        Wirft `WebhookStoreReadOnly` oder `OSError`, wenn nicht geschrieben
        werden konnte — der Aufrufer MUSS das anzeigen. Bei einem Fehler bleibt
        der Speicherstand unverändert (Rollback), damit Liste und Platte nicht
        auseinanderlaufen.

        Blockierend (icacls-Subprozess, bis zu 15 s) — gehört in einen
        Worker-Thread, nicht in einen Tk-Callback.
        """
        with self._lock:
            previous = copy.deepcopy(self._webhooks)
            for i, existing in enumerate(self._webhooks):
                if existing.get("id") == record.get("id"):
                    self._webhooks[i] = copy.deepcopy(record)
                    break
            else:
                self._webhooks.append(copy.deepcopy(record))
            try:
                self._save_to_disk()
            except BaseException:
                self._webhooks = previous
                raise

    def delete(self, webhook_id: str) -> None:
        """Wie `save`: wirft bei Schreibfehlern und rollt dann zurück."""
        with self._lock:
            previous = copy.deepcopy(self._webhooks)
            self._webhooks = [
                w for w in self._webhooks if w.get("id") != webhook_id]
            try:
                self._save_to_disk()
            except BaseException:
                self._webhooks = previous
                raise
