# src/mobile_keys.py
"""Geräteschlüssel `k_dev` der Handy-Erfassung (#249): Ablage im OS-Schlüsselbund, Datei als Fallback.

`mobile_keys.json` hält je Gerät nur den **Ort**: `{"location": "keyring"}` (der Schlüssel liegt
im Schlüsselbund unter `mobile:<device_id>`) oder `{"location": "file", "key": <base64url>}`
(Fallback: kein Schlüsselbund verfügbar, oder der Umzug steht noch aus). Gehärtet geschrieben
(`secure_file.write_secret_json`: 0600 unter Linux/macOS, ACL unter Windows) und nur beim
Koppeln, Umziehen, Widerrufen und Aufräumen — nie je Abgleich (die Token-Hashes und der
Zähler liegen in `mobile_devices.json`, die bei jedem Abgleich geschrieben wird).

**Der heiße Pfad (`get`) liest nur den Speicher-Cache.** Ein Schlüsselbund-Zugriff kann bis zum
30-s-Watchdog blockieren (gesperrter Schlüsselbund, Prompt); unter der Gerätesperre oder in einem
Server-Thread darf das nie passieren. `load`, `migrate`, `remove` und `retain` blockieren deshalb
und laufen nur im Worker. Fehlt ein Schlüssel im Cache, liefert `get` `None`; der Server antwortet
dann `503 key_unavailable` und stößt `request_load` an (gedrosselt).

Koppeln schreibt zuerst in die Datei (`put`: schnell, kein Schlüsselbund); `migrate` zieht den
Schlüssel danach in den Schlüsselbund um — erst nach erfolgreichem Zurücklesen wird die Datei
auf `keyring` umgeschrieben, jeder Abbruch davor lässt sie gültig (Muster `secret_migration`).

Eigener Lock wie `mobile_store`, nie über einen Schlüsselbund-Aufruf gehalten. Fremde oder
kaputte Einträge werden übersprungen, eine kaputte Datei wird quarantäniert, eine neuere
`schema_version` macht den Store read-only. Nichts hier loggt einen Schlüssel.
"""
from __future__ import annotations

import logging
import re
import threading
import time
from collections.abc import Iterable
from typing import Any

from src import keyring_store
from src.json_store import load_json_or_quarantine, quarantine_corrupt
from src.mobile_crypto import KEY_BYTES, CryptoError, b64d, b64e
from src.mobile_pairing import normalize_device_id
from src.secure_file import write_secret_json

log = logging.getLogger(__name__)

SCHEMA_VERSION = 1
LOAD_RETRY_SECONDS = 60.0
LOCATION_KEYRING = "keyring"
LOCATION_FILE = "file"
_KEY_TEXT_RE = re.compile(r"[A-Za-z0-9_-]{43}")        # 32 Bytes, base64url ohne Padding


class MobileKeysReadOnly(Exception):
    """Die Datei darf nicht überschrieben werden (neuere `schema_version` oder beim Start
    nicht lesbar). Der Aufrufer zeigt das an — ein still verworfener Schlüssel wäre
    schlimmer als ein Fehler."""


def keyring_key(device_id: str) -> str:
    """Name des Eintrags im Schlüsselbund (Service über `keyring_store.service_for`)."""
    return f"mobile:{device_id}"


def _decode(text: object) -> bytes | None:
    if not isinstance(text, str) or not _KEY_TEXT_RE.fullmatch(text):
        return None
    try:
        raw = b64d(text)
    except CryptoError:
        return None
    return raw if len(raw) == KEY_BYTES else None


Entry = dict[str, Any]


class MobileKeyStore:
    def __init__(self, filepath: str = "mobile_keys.json") -> None:
        self.filepath = filepath
        self._lock = threading.RLock()
        self._entries: dict[str, Entry] = {}
        self._cache: dict[str, bytes] = {}
        self._last_try: dict[str, float] = {}
        self._readonly = False
        self._load_file()

    # --- Datei ----------------------------------------------------------------------------------

    def _load_file(self) -> None:
        try:
            data = load_json_or_quarantine(self.filepath)
        except OSError:
            # Kein Quarantäne-Rename: ein kurzzeitig gesperrtes File (Virenscanner) ist kein
            # defektes File. Lieber ohne Schlüssel laufen, ohne die Datei zu überschreiben.
            self._readonly = True
            log.warning("mobile_keys.json nicht lesbar — starte ohne Geräteschlüssel, die "
                        "Datei wird nicht überschrieben", exc_info=True)
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
            log.warning("mobile_keys.json hat schema_version %s (bekannt: %s) — die Datei wird "
                        "nicht gelesen und nicht überschrieben", version, SCHEMA_VERSION)
            return
        raw = data.get("keys")
        if not isinstance(raw, dict):
            return
        for device_id, entry in raw.items():
            parsed = self._parse_entry(device_id, entry)
            if parsed is None:
                log.warning("mobile_keys.json: Eintrag übersprungen (id=%r)", str(device_id)[:70])
                continue
            location, key = parsed
            if location == LOCATION_FILE and key is not None:
                self._entries[device_id] = {"location": LOCATION_FILE, "key": b64e(key)}
                self._cache[device_id] = key
            else:
                self._entries[device_id] = {"location": LOCATION_KEYRING}

    @staticmethod
    def _parse_entry(device_id: object, entry: object) -> tuple[str, bytes | None] | None:
        if normalize_device_id(device_id) is None or not isinstance(entry, dict):
            return None
        location = entry.get("location")
        if location == LOCATION_KEYRING:
            return LOCATION_KEYRING, None
        if location == LOCATION_FILE:
            key = _decode(entry.get("key"))
            return (LOCATION_FILE, key) if key is not None else None
        return None

    def _save_locked(self) -> None:
        if self._readonly:
            raise MobileKeysReadOnly(self.filepath)
        write_secret_json(self.filepath, {"schema_version": SCHEMA_VERSION, "keys": self._entries},
                          prefix=".mobile-keys-")

    # --- Heißer Pfad ----------------------------------------------------------------------------

    def get(self, device_id: str) -> bytes | None:
        """Der Schlüssel aus dem Speicher-Cache — blockiert nie und fasst den Schlüsselbund nie an."""
        with self._lock:
            return self._cache.get(device_id)

    def where(self) -> dict[str, str]:
        """`{device_id: "keyring" | "file"}` — auch für Geräte, deren Schlüsselbund-Schlüssel
        noch nicht geladen ist. Nur lesen, kein Schlüsselbund-Aufruf."""
        with self._lock:
            return {device_id: entry["location"] for device_id, entry in self._entries.items()}

    # --- Schreiben (schnell, kein Schlüsselbund) -------------------------------------------------

    def put(self, device_id: str, key: bytes) -> None:
        """Legt den Schlüssel in Cache und gehärtete Datei ab (Ort `file`). Der Umzug in den
        Schlüsselbund folgt über `migrate` im Worker. Ein Schreibfehler rollt den Speicher zurück."""
        if normalize_device_id(device_id) is None or len(key) != KEY_BYTES:
            raise ValueError("Ungültige Geräte-ID oder Schlüssellänge")
        with self._lock:
            if self._readonly:
                raise MobileKeysReadOnly(self.filepath)
            old_entry = self._entries.get(device_id)
            old_key = self._cache.get(device_id)
            self._entries[device_id] = {"location": LOCATION_FILE, "key": b64e(key)}
            self._cache[device_id] = key
            try:
                self._save_locked()
            except BaseException:
                self._restore(device_id, old_entry, old_key)
                raise

    def _restore(self, device_id: str, entry: Entry | None, key: bytes | None) -> None:
        if entry is None:
            self._entries.pop(device_id, None)
        else:
            self._entries[device_id] = entry
        if key is None:
            self._cache.pop(device_id, None)
        else:
            self._cache[device_id] = key

    # --- Schlüsselbund (blockiert: nur im Worker) ------------------------------------------------

    def _apply_fetched(self, device_id: str, value: str) -> None:
        """`value` kam aus dem Schlüsselbund (`""` = es gibt keinen Eintrag)."""
        key = _decode(value) if value else None
        with self._lock:
            entry = self._entries.get(device_id)
            if entry is None or entry["location"] != LOCATION_KEYRING:
                return                                    # inzwischen neu gekoppelt oder entfernt
            if key is not None:
                self._cache[device_id] = key
                return
            # Der Schlüsselbund hat geantwortet, aber der Eintrag fehlt oder ist unbrauchbar
            # (gelöscht, anderer Rechner): das Gerät kann nicht mehr entschlüsseln.
            del self._entries[device_id]
            try:
                self._save_locked()
            except (OSError, MobileKeysReadOnly):
                log.warning("mobile_keys.json: Eintrag nicht entfernbar", exc_info=True)
        log.warning("Der Schlüssel eines gekoppelten Handys fehlt im Schlüsselbund — das Handy "
                    "muss neu koppeln (id=%r)", device_id)

    def load(self) -> bool:
        """Lädt die Schlüssel der Geräte mit Ort `keyring` in den Cache. Bricht beim ersten
        nicht lesbaren Eintrag ab (ein hängender Schlüsselbund kostete sonst je Gerät den
        Watchdog) und liefert dann `False`."""
        with self._lock:
            pending = [device_id for device_id, entry in self._entries.items()
                       if entry["location"] == LOCATION_KEYRING and device_id not in self._cache]
        for device_id in pending:
            value = keyring_store.fetch(keyring_key(device_id))
            if value is None:
                log.warning("Schlüsselbund nicht lesbar — Geräteschlüssel bleiben vorerst unverfügbar")
                return False
            self._apply_fetched(device_id, value)
        return True

    def request_load(self, device_id: str) -> None:
        """Stößt das Nachladen **eines** Schlüssels im Hintergrund an (nicht blockierend,
        höchstens alle `LOAD_RETRY_SECONDS` je Gerät)."""
        with self._lock:
            entry = self._entries.get(device_id)
            if entry is None or entry["location"] != LOCATION_KEYRING or device_id in self._cache:
                return
            now = time.monotonic()
            last = self._last_try.get(device_id)
            if last is not None and now - last < LOAD_RETRY_SECONDS:
                return
            self._last_try[device_id] = now
        threading.Thread(target=self._load_one, args=(device_id,), daemon=True,
                         name="mobile-keys-load").start()

    def _load_one(self, device_id: str) -> None:
        value = keyring_store.fetch(keyring_key(device_id))
        if value is None:
            return                                        # nicht lesbar: der nächste Versuch kommt später
        self._apply_fetched(device_id, value)

    def migrate(self) -> int:
        """Zieht Schlüssel mit Ort `file` in den Schlüsselbund. Pro Schlüssel: ablegen →
        zurücklesen und vergleichen → erst dann die Datei auf `keyring` umschreiben (der
        Schlüssel verlässt sie). Liefert die Zahl der umgezogenen; bei fehlendem Schlüsselbund
        0 (der nächste Start versucht es wieder)."""
        with self._lock:
            pending = [(device_id, self._cache[device_id]) for device_id, entry in self._entries.items()
                       if entry["location"] == LOCATION_FILE and device_id in self._cache]
        moved = 0
        for device_id, key in pending:
            text = b64e(key)
            if not keyring_store.put(keyring_key(device_id), text):
                return moved                              # kein Schlüsselbund: nicht je Gerät erneut warten
            if keyring_store.fetch(keyring_key(device_id)) != text:
                log.warning("Schlüsselbund hat den Schlüssel nicht wie abgelegt zurückgegeben — "
                            "er bleibt in der Datei (id=%r)", device_id)
                continue
            with self._lock:
                entry = self._entries.get(device_id)
                if entry is None or entry["location"] != LOCATION_FILE or self._cache.get(device_id) != key:
                    continue                              # inzwischen neu gekoppelt: später erneut
                self._entries[device_id] = {"location": LOCATION_KEYRING}
                try:
                    self._save_locked()
                except (OSError, MobileKeysReadOnly):
                    self._entries[device_id] = entry
                    log.warning("mobile_keys.json nicht schreibbar — der Schlüssel bleibt in der "
                                "Datei (id=%r)", device_id, exc_info=True)
                    continue
                moved += 1
        return moved

    def remove(self, device_id: str) -> None:
        """Entfernt den Schlüssel aus Cache, Datei und Schlüsselbund (blockiert). Ein
        unbekanntes Gerät ist kein Fehler; ein Schreibfehler hält den Widerruf nicht auf."""
        with self._lock:
            entry = self._entries.pop(device_id, None)
            self._cache.pop(device_id, None)
            self._last_try.pop(device_id, None)
            if entry is not None:
                try:
                    self._save_locked()
                except (OSError, MobileKeysReadOnly):
                    log.warning("mobile_keys.json nicht schreibbar — ein Eintrag blieb stehen",
                                exc_info=True)
        if entry is not None:
            keyring_store.remove(keyring_key(device_id))

    def retain(self, device_ids: Iterable[str]) -> None:
        """Räumt die Schlüssel aller Geräte ab, die nicht in `device_ids` stehen (blockiert)."""
        keep = set(device_ids)
        with self._lock:
            stale = [device_id for device_id in self._entries if device_id not in keep]
        for device_id in stale:
            self.remove(device_id)
