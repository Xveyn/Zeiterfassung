"""Box-Geheimnisse der Handy-Erfassung über den Relay (#358), gerätelokal und gehärtet.

Eine „Box" ist das Postfach am Relay, über das Handy und Desktop ihre verschlüsselten Umschläge
austauschen; ihr Geheimnis (`mobile_relay_codec.generate_box_secret`, 43 Zeichen Base64url) ist
Bearer und Adresse zugleich. Beim Koppeln liegt es zunächst als **offenes** Geheimnis (`pending`)
bereit; sobald sich ein Handy meldet, wandert es per `bind` zu dessen Geräte-ID.

Datei `mobile_box.json`:
`{"schema_version": 1, "pending": {"secret", "created_at"} | null, "devices": {device_id: {"secret"}}}`,
geschrieben über `secure_file.write_secret_json` (0600 / ACL) und **nur bei einer Änderung**.
Getrennt vom Push-Speicher `mobile_relay.json` (`mobile_relay_store`): anderes Geheimnis, anderer
Zweck. Reist nicht per Drive-Sync. Kein Schlüsselbund, wie dort.

Warum eine gehärtete Datei und kein Schlüsselbund (wie beim Push-Geheimnis, #331, `mobile_relay_store`):
ein geleaktes Box-Geheimnis erlaubt, den Slot der Gegenseite zu lesen (Gerätetoken im Klartext plus
versiegelter Umschlag), Slots zu überschreiben, den Desktop von der Box zu verdrängen und unversiegelte
Fehler zu fälschen — aber weder Inhalte zu lesen noch zu synchronisieren: das braucht den Geräteschlüssel
`k_dev` aus dem Schlüsselbund (`mobile_keys`). Ein Schlüsselbund-Zugriff blockiert bis zum 30-s-Watchdog,
darauf darf der Verbindungs-Thread nicht warten. Ein späterer Wechsel ist ein Backend-Tausch hinter
derselben API (`_load`/`_save_locked`/`_commit_locked`).

Lebenszyklus des offenen Geheimnisses (Regeln für die Verbindungsschicht, PR 3b):

- Der Kopplungscode lebt nur im Speicher (`PairingSession`). Nach einem Neustart ist ein `pending` in der
  Datei **verwaist**: kein Code kann es je einlösen. Beim Start und wenn der Koppel-Dialog schließt oder der
  Code abläuft: `clear_pending()` und die Box am Relay löschen (`box_relay.delete_box`). Nie mit einer
  offenen Box verbinden, ohne dass eine Kopplungssitzung offen ist.
- Die Geräte-ID für `bind(device_id, expected=…)` liefert `RelayAdapter.process` als
  `RelayResult.paired_device_id`.
- Scheitert `bind` nach einer gelungenen Kopplung (`OSError`), ist das Gerät gekoppelt, seine Box aber noch
  `pending`. Das nächste `open_pending` gäbe sie als „altes“ Geheimnis zurück; wer es löscht, löscht die Box,
  die das Handy benutzt (heilbar durch Neu-Koppeln). Deshalb: den Fehlschlag loggen, `bind` mit der
  `paired_device_id` einer erneuten Zustellung wiederholen (über `expected` idempotent) und das „alte“
  Geheimnis eines `open_pending` nie löschen, solange es gebunden oder in Benutzung ist.

Beim Laden verworfene Einträge (ungültiges Geheimnis, kaputtes `pending`) verschwinden beim nächsten
Schreiben von der Platte: ein Geheimnis, das je am Relay angelegt wurde, kann so zur Waise werden, von
der der Aufrufer nie erfährt.

Eigener Lock. Unbrauchbare Einträge werden übersprungen, eine kaputte Datei wird quarantäniert,
eine neuere `schema_version` oder ein Lesefehler macht den Store read-only: jede ändernde Methode
wirft dann `MobileBoxReadOnly`, bevor sie den Speicher anfasst. Schreibfehler rollen den Speicher
zurück. Nichts hier loggt ein Geheimnis, nur Zahlen und Ausnahmetypen.
"""
from __future__ import annotations

import logging
import threading
from collections.abc import Iterable
from typing import Any

from src.json_store import load_json_or_quarantine, quarantine_corrupt
from src.mobile_pairing import normalize_device_id
from src.mobile_relay_codec import BOX_SECRET_RE, generate_box_secret
from src.secure_file import write_secret_json

log = logging.getLogger(__name__)

SCHEMA_VERSION = 1


class MobileBoxReadOnly(Exception):
    """Die Datei darf nicht überschrieben werden (neuere `schema_version` oder beim Start nicht
    lesbar). Der Aufrufer zeigt das an — ein still verworfenes Geheimnis wäre schlimmer als ein Fehler."""


def _valid(secret: object) -> bool:
    return isinstance(secret, str) and BOX_SECRET_RE.fullmatch(secret) is not None


class MobileBoxStore:
    def __init__(self, filepath: str = "mobile_box.json") -> None:
        self.filepath = filepath
        self._lock = threading.RLock()
        self._pending: dict[str, str] | None = None
        self._devices: dict[str, str] = {}
        self._readonly = False
        self._load()

    @property
    def read_only(self) -> bool:
        return self._readonly

    def _load(self) -> None:
        try:
            data = load_json_or_quarantine(self.filepath)
        except OSError as exc:
            # Kein Quarantäne-Rename: ein kurzzeitig gesperrtes File (Virenscanner) ist kein
            # defektes File. Lieber ohne Geheimnisse laufen, ohne die Datei zu überschreiben.
            self._readonly = True
            log.warning("mobile_box.json nicht lesbar (%s) — die Datei wird nicht überschrieben",
                        type(exc).__name__)
            return
        if data is None:
            return
        if not isinstance(data, dict):
            quarantine_corrupt(self.filepath,
                               f"Top-Level ist {type(data).__name__}, erwartet ein Objekt")
            return
        version = data.get("schema_version")
        if isinstance(version, int) and not isinstance(version, bool) and version > SCHEMA_VERSION:
            self._readonly = True
            log.warning("mobile_box.json hat schema_version %s (bekannt: %s) — die Datei wird "
                        "nicht gelesen und nicht überschrieben", version, SCHEMA_VERSION)
            return
        skipped = 0
        pending = data.get("pending")
        if pending is not None:
            if (isinstance(pending, dict) and _valid(pending.get("secret"))
                    and isinstance(pending.get("created_at"), str)):
                self._pending = {"secret": pending["secret"], "created_at": pending["created_at"]}
            else:
                skipped += 1
        raw = data.get("devices")
        if isinstance(raw, dict):
            for device_id, entry in raw.items():
                secret = entry.get("secret") if isinstance(entry, dict) else None
                if normalize_device_id(device_id) is None or not isinstance(secret, str) or not _valid(secret):
                    skipped += 1
                    continue
                self._devices[device_id] = secret
        if skipped:
            # Nur die Zahl: die Einträge stehen neben Geheimnissen, und ein Log ist kein Ort dafür.
            log.warning("mobile_box.json: %d unbrauchbare Einträge übersprungen", skipped)

    def _snapshot(self) -> tuple[dict[str, str] | None, dict[str, str]]:
        return (dict(self._pending) if self._pending is not None else None, dict(self._devices))

    def _restore(self, snapshot: tuple[dict[str, str] | None, dict[str, str]]) -> None:
        self._pending, self._devices = snapshot

    def _check_writable(self) -> None:
        if self._readonly:
            raise MobileBoxReadOnly(self.filepath)

    def _save_locked(self) -> None:
        document: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "pending": self._pending,
            "devices": {i: {"secret": s} for i, s in self._devices.items()},
        }
        write_secret_json(self.filepath, document, prefix=".mobile_box-")

    def _commit_locked(self, snapshot: tuple[dict[str, str] | None, dict[str, str]]) -> None:
        """Schreibt den geänderten Stand; bei jedem Fehler zurückrollen (Muster `storage`) und
        weiterreichen, sonst läuft der Speicher dem Stand der Platte voraus."""
        try:
            self._save_locked()
        except BaseException:
            self._restore(snapshot)
            raise

    def pending(self) -> str | None:
        with self._lock:
            return self._pending["secret"] if self._pending is not None else None

    def get(self, device_id: str) -> str | None:
        with self._lock:
            return self._devices.get(device_id)

    def known_ids(self) -> list[str]:
        with self._lock:
            return sorted(self._devices)

    def all_secrets(self) -> list[str]:
        """Offenes und gebundene Geheimnisse ohne Duplikate (offenes zuerst, Geräte nach ID)."""
        with self._lock:
            result: list[str] = []
            if self._pending is not None:
                result.append(self._pending["secret"])
            for device_id in sorted(self._devices):
                if self._devices[device_id] not in result:
                    result.append(self._devices[device_id])
            return result

    def open_pending(self, now: str) -> tuple[str, str | None]:
        """Legt ein neues offenes Geheimnis an; liefert `(neues, altes_oder_None)` — das alte
        räumt der Aufrufer am Relay ab. Wirft `MobileBoxReadOnly` bzw. `OSError`."""
        with self._lock:
            self._check_writable()
            snapshot = self._snapshot()
            previous = self._pending["secret"] if self._pending is not None else None
            secret = generate_box_secret()
            self._pending = {"secret": secret, "created_at": now}
            self._commit_locked(snapshot)
            return secret, previous

    def clear_pending(self) -> str | None:
        """Verwirft das offene Geheimnis und liefert es zurück (`None`, wenn es keins gab)."""
        with self._lock:
            self._check_writable()
            if self._pending is None:
                return None
            snapshot = self._snapshot()
            secret = self._pending["secret"]
            self._pending = None
            self._commit_locked(snapshot)
            return secret

    def bind(self, device_id: str, expected: str | None = None) -> tuple[str | None, str | None]:
        """Verschiebt das offene Geheimnis zum Gerät. Liefert `(gebundenes, ersetztes_altes_des_Geräts)`;
        ohne offenes Geheimnis `(None, None)` ohne Schreiben. Wirft `ValueError` bei unbrauchbarer ID
        (es ändert sich nichts). Mit `expected` wird nur gebunden, wenn es dem offenen Geheimnis
        entspricht — die Verbindungsschicht übergibt das Geheimnis der Box, auf der die Koppel-Anfrage
        ankam; ein zwischenzeitlich neu geöffnetes Pairing bleibt so unangetastet (`(None, None)`)."""
        with self._lock:
            self._check_writable()
            if normalize_device_id(device_id) is None:
                raise ValueError("Ungültige Geräte-ID.")
            if self._pending is None:
                return None, None
            if expected is not None and expected != self._pending["secret"]:
                return None, None
            snapshot = self._snapshot()
            secret = self._pending["secret"]
            replaced = self._devices.get(device_id)
            self._devices[device_id] = secret
            self._pending = None
            self._commit_locked(snapshot)
            return secret, replaced

    def remove(self, device_id: str) -> str | None:
        """Entfernt den Eintrag des Geräts und liefert dessen Geheimnis (`None`, wenn es keins gab)."""
        with self._lock:
            self._check_writable()
            if device_id not in self._devices:
                return None
            snapshot = self._snapshot()
            secret = self._devices.pop(device_id)
            self._commit_locked(snapshot)
            return secret

    def retain(self, ids: Iterable[str]) -> dict[str, str]:
        """Behält nur die genannten Geräte; liefert die entfernten `{id: Geheimnis}`."""
        with self._lock:
            self._check_writable()
            keep = set(ids)
            dropped = {i: s for i, s in self._devices.items() if i not in keep}
            if not dropped:
                return {}
            snapshot = self._snapshot()
            for device_id in dropped:
                del self._devices[device_id]
            self._commit_locked(snapshot)
            return dropped
