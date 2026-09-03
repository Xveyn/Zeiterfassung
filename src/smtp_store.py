"""Gerätelokale Persistenz der SMTP-Konten (Tk-frei, stdlib-only).

`smtp.json` liegt neben `token.json` im Datenverzeichnis. Sie enthält
Konfiguration und — wenn kein Schlüsselbund verfügbar ist — auch Passwörter,
und wird deshalb wie `token.json` und `webhooks.json` gehärtet geschrieben
(chmod 0600 + icacls auf der Temp-Datei, dann os.replace). Der vierte
Secret-Schreibpfad der App, siehe src/CLAUDE.md.

Nichts hiervon reist per Drive-Sync und nichts steht im Share-Doc: SMTP-Konten
sind bewusst gerätelokal, damit kein Secret im Sync-Doc landet — dieselbe
Begründung wie bei den Webhooks.

Der Store fasst den Schlüsselbund NICHT an. Das Secret zu einem gelöschten
Konto räumt der Aufrufer ab (`tab_smtp._remove`), damit dieses Modul reine
Dateipersistenz bleibt und ohne Zugriff auf den echten Credential Manager
testbar ist.
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
from src.smtp import SECURITY_MODES

log = logging.getLogger(__name__)

SCHEMA_VERSION = 1

Account = dict[str, Any]

_REQUIRED_KEYS = ("id", "name", "enabled", "host", "port", "security",
                  "username", "from_addr", "recipient", "password_location")
_FORBIDDEN_CHARS = ("\r", "\n", "\x00")


class SmtpStoreReadOnly(Exception):
    """Die Datei darf nicht überschrieben werden (neuere schema_version oder
    beim Start nicht lesbar). Der Aufrufer zeigt das als themed Fehlerdialog —
    ein still verworfener Speichervorgang wäre schlimmer als ein Fehler."""


def new_id() -> str:
    """Stabile Kennung eines Kontos. Trägt die Zuordnung — im Store UND als
    Keyring-Account —, wenn der Nutzer den Namen ändert."""
    return uuid.uuid4().hex


def _is_wellformed(record: Any) -> bool:
    """Strukturprüfung fürs Laden — schwächer als validate_record, aber NICHT
    wertfrei.

    `security` wird mitgeprüft, und das ist keine Kosmetik: `validate_record`
    läuft beim Laden nie, und `smtp._open` weist einen unbekannten Wert zwar
    ab, aber erst beim Senden. Ein solcher Datensatz soll gar nicht erst in
    der Ziel-Auswahl erscheinen — dasselbe Muster, das `webhook_store` für die
    URL fährt („sonst erschiene ein Eintrag mit kaputter oder unsicherer
    Adresse in der Ziel-Auswahl und scheiterte erst beim Senden").
    """
    if not isinstance(record, dict):
        return False
    if any(k not in record for k in _REQUIRED_KEYS):
        return False
    return record.get("security") in SECURITY_MODES


def validate_record(record: Account, existing: list[Account]) -> tuple[bool, str]:
    """Prüft einen Datensatz vor dem Speichern. Liefert `(ok, meldung)`.

    Das Passwort wird hier NICHT geprüft: bei aktivem Schlüsselbund steht es
    gar nicht im Datensatz. Die Regel „bei gesetztem Benutzer ist ein Passwort
    Pflicht" gehört in den Dialog, der das Eingabefeld besitzt, und gilt dort
    nur beim Neuanlegen.
    """
    name = (record.get("name") or "").strip()
    if not name:
        return False, "Bitte einen Namen angeben."
    for other in existing:
        if other.get("id") == record.get("id"):
            continue
        if (other.get("name") or "").strip().lower() == name.lower():
            return False, "Es gibt bereits ein Konto mit diesem Namen."

    if not (record.get("host") or "").strip():
        return False, "Bitte einen Server angeben."

    port = record.get("port")
    if not isinstance(port, int) or isinstance(port, bool) or not 1 <= port <= 65535:
        return False, "Der Port muss eine Zahl zwischen 1 und 65535 sein."

    if record.get("security") not in SECURITY_MODES:
        return False, "Unbekannte Verschlüsselung."

    for field, label in (("from_addr", "Absenderadresse"),
                         ("recipient", "Empfängeradresse")):
        value = (record.get(field) or "").strip()
        if not value:
            return False, f"Bitte eine {label} angeben."
        if any(ch in value for ch in _FORBIDDEN_CHARS):
            return False, (f"Die {label} enthält unzulässige Steuerzeichen "
                           "(Zeilenumbruch oder Nullbyte).")

    return True, ""


class SmtpStore:
    """Analog `WebhookStore`; Details dort nachlesen.

    Wie dieser bekommt der Store **keinen** geteilten Daten-Lock injiziert
    (`main.py`): SMTP-Konten nehmen an keinem Sync-Flow teil, es gibt also
    keine übergreifende Invariante zu wahren — und `save`/`delete` halten den
    Lock über den icacls-Subprozess (timeout 15 s) plus bis zu vier Retries.
    """

    def __init__(self, filepath: str = "smtp.json",
                 lock: threading.RLock | None = None) -> None:
        self.filepath = filepath
        # Die Signatur ist einheitlich mit den übrigen Stores (`lock=`-
        # Parameter wie storage.py, Audit H1/H2) — ein injizierter Lock wird
        # also übernommen. `main.py` injiziert hier aber bewusst KEINEN: dieser
        # Store bekommt nicht den geteilten Daten-Lock, sondern legt sich ohne
        # Injektion seinen eigenen an. SMTP-Konten nehmen an keinem Sync-Flow
        # teil (kein Snapshot→Merge→Apply, kein Sync-Doc, kein Journal) — es
        # gibt also keine übergreifende Invariante mit den anderen Stores zu
        # wahren, siehe src/CLAUDE.md.
        self._lock = lock if lock is not None else threading.RLock()
        self._accounts: list[Account] = []
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
            log.warning("smtp.json nicht lesbar — starte ohne SMTP-Konten, "
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
            # überschreiben. Lieber ohne SMTP-Konten laufen.
            self._readonly = True
            log.warning(
                "smtp.json hat schema_version %s (bekannt: %s) — die Datei "
                "wird nicht gelesen und nicht überschrieben.",
                version, SCHEMA_VERSION)
            return

        raw = data.get("accounts")
        if not isinstance(raw, list):
            return
        for record in raw:
            if _is_wellformed(record):
                self._accounts.append(record)
            else:
                # NIEMALS den Datensatz selbst loggen — im Datei-Fallback
                # enthält er das Passwort, und logs/zeiterfassung.log ist
                # ungehärtet und genau die Datei, die Nutzer bei Problemen
                # anhängen.
                log.warning(
                    "smtp.json: Datensatz übersprungen (id=%r, name=%r)",
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
            log.warning("smtp.json korrupt (%s); Quarantäne-Rename "
                        "fehlgeschlagen — starte ohne SMTP-Konten", reason,
                        exc_info=True)
            return
        log.warning("smtp.json korrupt (%s) — nach %s in Quarantäne "
                    "verschoben, starte ohne SMTP-Konten",
                    reason, os.path.basename(target))

    def _save_to_disk(self) -> None:
        """Atomar und gehärtet — derselbe Ablauf wie oauth_utils.write_token.

        chmod und icacls laufen auf der TEMP-Datei: sonst gäbe es ein Fenster,
        in dem smtp.json schon am Zielpfad steht, aber noch die geerbten
        Rechte trägt.
        """
        if self._readonly:
            # Lautlos zurückkehren wäre die schlechteste Variante: der Dialog
            # schlösse sich, die Liste zeigte den Eintrag (er steht in
            # self._accounts), auf Platte stünde nichts — auffallen würde es
            # erst nach dem Neustart.
            raise SmtpStoreReadOnly(
                "Die SMTP-Datei stammt von einer neueren Version oder ist "
                "nicht lesbar und wird deshalb nicht überschrieben.")
        payload = {"schema_version": SCHEMA_VERSION, "accounts": self._accounts}
        directory = os.path.dirname(os.path.abspath(self.filepath))
        fd, tmp_path = tempfile.mkstemp(
            dir=directory, prefix=".smtp-", suffix=".tmp")
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

    def get_all(self) -> list[Account]:
        # deepcopy, nicht dict(): auch wenn die Konten hier flacher sind als
        # die Webhooks, bleibt die Regel dieselbe — eine flache Kopie ließe
        # den Aufrufer den Store-Inhalt mutieren.
        with self._lock:
            return copy.deepcopy(self._accounts)

    def enabled(self) -> list[Account]:
        with self._lock:
            return copy.deepcopy(
                [a for a in self._accounts if a.get("enabled")])

    def save(self, record: Account) -> None:
        """Legt an oder ersetzt nach `id`.

        Wirft `SmtpStoreReadOnly` oder `OSError`, wenn nicht geschrieben
        werden konnte — der Aufrufer MUSS das anzeigen. Bei einem Fehler bleibt
        der Speicherstand unverändert (Rollback), damit Liste und Platte nicht
        auseinanderlaufen.

        Blockierend (icacls-Subprozess, bis zu 15 s) — gehört in einen
        Worker-Thread, nicht in einen Tk-Callback.
        """
        with self._lock:
            previous = copy.deepcopy(self._accounts)
            for i, existing in enumerate(self._accounts):
                if existing.get("id") == record.get("id"):
                    self._accounts[i] = copy.deepcopy(record)
                    break
            else:
                self._accounts.append(copy.deepcopy(record))
            try:
                self._save_to_disk()
            except BaseException:
                self._accounts = previous
                raise

    def delete(self, account_id: str) -> None:
        """Wie `save`: wirft bei Schreibfehlern und rollt dann zurück.

        Fasst den Schlüsselbund NICHT an — s. Modul-Docstring. Das Secret des
        gelöschten Kontos räumt der Aufrufer ab.
        """
        with self._lock:
            previous = copy.deepcopy(self._accounts)
            self._accounts = [
                a for a in self._accounts if a.get("id") != account_id]
            try:
                self._save_to_disk()
            except BaseException:
                self._accounts = previous
                raise
