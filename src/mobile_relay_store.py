"""Relay-Geheimnisse der gekoppelten Handys (#331), gerätelokal und gehärtet.

Das Geheimnis ist Identität und Bearer des Handys beim Push-Relay (`relay/`): wer es kennt, kann dessen
Relay-Objekt löschen oder ersetzen — mehr nicht, der Relay gibt nichts heraus. Der Desktop braucht es
nur, um das Objekt beim Widerruf eines Geräts abzuräumen. Deshalb eine eigene Datei
`mobile_relay.json` (`{"schema_version": 1, "secrets": {device_id: secret}}`), geschrieben über
`secure_file.write_secret_json` (0600 / ACL) und **nur bei einer Änderung**: die Datei
`mobile_devices.json` wird bei jedem Abgleich geschrieben und dürfte keinen `icacls`-Aufruf je
Abgleich tragen, diese hier schon, weil sie sich fast nie ändert. Kein Schlüsselbund: es schützt nur
das Objekt eines Handys (Entscheidung im Plan zu #331).

Eigener Lock wie `mobile_keys`. Fremde oder kaputte Einträge werden übersprungen, eine kaputte Datei
wird quarantäniert, eine neuere `schema_version` macht den Store read-only. Nichts hier loggt ein
Geheimnis.
"""
from __future__ import annotations

import logging
import threading
from collections.abc import Iterable

from src.json_store import load_json_or_quarantine, quarantine_corrupt
from src.mobile_pairing import normalize_device_id
from src.mobile_reminders import RELAY_SECRET_RE
from src.secure_file import write_secret_json

log = logging.getLogger(__name__)

SCHEMA_VERSION = 1


class MobileRelayReadOnly(Exception):
    """Die Datei darf nicht überschrieben werden (neuere `schema_version` oder beim Start nicht
    lesbar). Der Aufrufer zeigt das an — ein still verworfenes Geheimnis wäre schlimmer als ein Fehler."""


def _valid(secret: object) -> bool:
    return isinstance(secret, str) and RELAY_SECRET_RE.fullmatch(secret) is not None


class MobileRelayStore:
    def __init__(self, filepath: str = "mobile_relay.json") -> None:
        self.filepath = filepath
        self._lock = threading.RLock()
        self._secrets: dict[str, str] = {}
        self._readonly = False
        self._load()

    def _load(self) -> None:
        try:
            data = load_json_or_quarantine(self.filepath)
        except OSError:
            # Kein Quarantäne-Rename: ein kurzzeitig gesperrtes File (Virenscanner) ist kein
            # defektes File. Lieber ohne Geheimnisse laufen, ohne die Datei zu überschreiben.
            self._readonly = True
            log.warning("mobile_relay.json nicht lesbar — die Datei wird nicht überschrieben",
                        exc_info=True)
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
            log.warning("mobile_relay.json hat schema_version %s (bekannt: %s) — die Datei wird "
                        "nicht gelesen und nicht überschrieben", version, SCHEMA_VERSION)
            return
        raw = data.get("secrets")
        if not isinstance(raw, dict):
            return
        for device_id, secret in raw.items():
            if normalize_device_id(device_id) is None or not _valid(secret):
                log.warning("mobile_relay.json: Eintrag übersprungen (id=%r)", str(device_id)[:70])
                continue
            self._secrets[device_id] = secret

    def _save_locked(self) -> None:
        if self._readonly:
            raise MobileRelayReadOnly(self.filepath)
        write_secret_json(self.filepath,
                          {"schema_version": SCHEMA_VERSION, "secrets": self._secrets},
                          prefix=".mobile-relay-")

    def get(self, device_id: str) -> str | None:
        with self._lock:
            return self._secrets.get(device_id)

    def known_ids(self) -> set[str]:
        with self._lock:
            return set(self._secrets)

    def set(self, device_id: str, secret: str) -> bool:
        """Legt das Geheimnis ab; `True`, wenn sich etwas geändert hat (nur dann wird geschrieben).
        Wirft `ValueError` bei unbrauchbarer ID oder Form, `OSError` beim Schreiben (der Speicher
        bleibt dann auf dem alten Stand)."""
        if normalize_device_id(device_id) is None or not _valid(secret):
            raise ValueError("Ungültige Geräte-ID oder ungültiges Relay-Geheimnis.")
        with self._lock:
            previous = self._secrets.get(device_id)
            if previous == secret:
                return False
            self._secrets[device_id] = secret
            try:
                self._save_locked()
            except BaseException:
                # Zurückrollen und weiterreichen (Muster `storage`): sonst läuft der Speicher
                # dem Stand der Platte voraus.
                if previous is None:
                    self._secrets.pop(device_id, None)
                else:
                    self._secrets[device_id] = previous
                raise
            return True

    def remove(self, device_id: str) -> str | None:
        """Entfernt das Geheimnis und liefert es zurück (der Aufrufer räumt damit das Objekt am
        Relay ab); `None`, wenn es keins gab."""
        with self._lock:
            previous = self._secrets.pop(device_id, None)
            if previous is None:
                return None
            try:
                self._save_locked()
            except BaseException:
                self._secrets[device_id] = previous
                raise
            return previous

    def retain(self, device_ids: Iterable[str]) -> dict[str, str]:
        """Behält nur die genannten Geräte; liefert die entfernten `{id: Geheimnis}`."""
        keep = set(device_ids)
        with self._lock:
            dropped = {i: s for i, s in self._secrets.items() if i not in keep}
            if not dropped:
                return {}
            for device_id in dropped:
                del self._secrets[device_id]
            try:
                self._save_locked()
            except BaseException:
                self._secrets.update(dropped)
                raise
            return dropped
