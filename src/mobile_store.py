# src/mobile_store.py
"""Gerätelokale Persistenz der gekoppelten Handys (#221), Tk-frei und stdlib-only.

`mobile_devices.json` liegt neben `smtp.json` im Datenverzeichnis, reist aber weder
per Drive-Sync noch im Share-Doc: eine Kopplung gilt für genau diesen Desktop.

Die Datei enthält **kein Geheimnis im Klartext**: von jedem Gerätetoken steht nur
der SHA-256-Hash darin (das Token hat 256 Bit Zufall, aus dem Hash lässt es sich
nicht herleiten). Deshalb schreibt der Store über `json_store.atomic_write_json`
und nicht über den gehärteten Schreibpfad der Secret-Dateien (`secure_file`, ein
`icacls`-Aufruf je Schreibvorgang wäre bei jedem Abgleich unnötige Last). Die
Datei bekommt über `mkstemp` unter POSIX trotzdem 0600.

Der Store hat wie `smtp_store` einen **eigenen** Lock: er nimmt an keinem
Sync-Flow der Einträge teil. Die Datensätze und ihre Regeln (Ablauf, Karenz,
Widerruf) stehen in `mobile_pairing`; hier liegt nur die Dateimechanik.
"""
from __future__ import annotations

import copy
import datetime
import logging
import re
import threading
from typing import Any

from src.json_store import atomic_write_json, load_json_or_quarantine, quarantine_corrupt
from src.mobile_pairing import Record, shift

log = logging.getLogger(__name__)

SCHEMA_VERSION = 1
# Abgelaufene Datensätze bleiben so lange sichtbar (für `token_expired` und die Liste
# im Tab), danach räumt `prune` sie weg.
FORGET_AFTER = datetime.timedelta(days=30)

_HASH_RE = re.compile(r"[0-9a-f]{64}")
# Zeitstempel stehen als Text im festen Format `utc_now_iso` (nur dann ist der String-
# Vergleich korrekt). Eine Datei mit `"zzzz"` als Ablauf liefe sonst nie ab.
_TIME_RE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z")
_REQUIRED_TIMES = ("created_at", "expires_at", "last_seen")
_OPTIONAL_TIMES = ("last_pull_at", "previous_valid_until")      # leer = nie gesetzt
_TEXT_KEYS = ("id", "name")


class MobileStoreReadOnly(Exception):
    """Die Datei darf nicht überschrieben werden (neuere `schema_version` oder beim
    Start nicht lesbar). Der Aufrufer zeigt das an — ein still verworfener
    Speichervorgang wäre schlimmer als ein Fehler."""


def _has_surrogate(text: str) -> bool:
    return any("\ud800" <= ch <= "\udfff" for ch in text)


def _is_wellformed(record: Any) -> bool:
    """Strukturprüfung fürs Laden. Fremde oder handbearbeitete Datensätze, die
    `authenticate` oder den Tab zum Absturz brächten, werden übersprungen."""
    if not isinstance(record, dict):
        return False
    if not all(isinstance(record.get(key), str) for key in _TEXT_KEYS):
        return False
    if not record["id"]:
        return False
    # Ein Lone Surrogate (JSON-Escape "\ud800") lädt als str, lässt sich aber nicht
    # als UTF-8 schreiben: jedes spätere `save`, auch ein Widerruf, würfe.
    if any(_has_surrogate(record[key]) for key in _TEXT_KEYS):
        return False
    for key in _REQUIRED_TIMES:
        if not isinstance(record.get(key), str) or not _TIME_RE.fullmatch(record[key]):
            return False
    for key in _OPTIONAL_TIMES:
        value = record.get(key)
        if not isinstance(value, str) or (value and not _TIME_RE.fullmatch(value)):
            return False
    if not _HASH_RE.fullmatch(str(record.get("token_hash", ""))):
        return False
    previous = record.get("previous_token_hash")
    if not isinstance(previous, str) or (previous and not _HASH_RE.fullmatch(previous)):
        return False
    return isinstance(record.get("revoked"), bool)


class MobileStore:
    def __init__(self, filepath: str = "mobile_devices.json",
                 lock: threading.RLock | None = None) -> None:
        self.filepath = filepath
        self._lock = lock if lock is not None else threading.RLock()
        self._devices: list[Record] = []
        self._readonly = False
        self._load()

    def _load(self) -> None:
        try:
            data = load_json_or_quarantine(self.filepath)
        except OSError:
            # KEINE Quarantäne: ein kurzzeitig gesperrtes File (Virenscanner, Backup)
            # ist kein defektes File. Lieber ohne Geräte laufen, ohne die Datei zu
            # überschreiben (wie smtp_store).
            self._readonly = True
            log.warning("mobile_devices.json nicht lesbar — starte ohne gekoppelte "
                        "Geräte, die Datei wird nicht überschrieben", exc_info=True)
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
            log.warning("mobile_devices.json hat schema_version %s (bekannt: %s) — die "
                        "Datei wird nicht gelesen und nicht überschrieben",
                        version, SCHEMA_VERSION)
            return
        raw = data.get("devices")
        if not isinstance(raw, list):
            return
        seen: set[str] = set()
        for record in raw:
            if _is_wellformed(record) and record["id"] not in seen:
                # Doppelte IDs behielten sonst zwei Token, von denen ein Widerruf nur
                # eines träfe (`get`/`save` nehmen den ersten, `authenticate` jeden).
                seen.add(record["id"])
                self._devices.append(record)
            else:
                # Nie den Datensatz loggen (er trägt Token-Hashes), nur id und Name.
                log.warning("mobile_devices.json: Datensatz übersprungen (id=%r, name=%r)",
                            record.get("id") if isinstance(record, dict) else None,
                            record.get("name") if isinstance(record, dict) else None)

    def _save_to_disk(self) -> None:
        if self._readonly:
            raise MobileStoreReadOnly(self.filepath)
        atomic_write_json(self.filepath, {"schema_version": SCHEMA_VERSION,
                                          "devices": self._devices})

    def get_all(self) -> list[Record]:
        with self._lock:
            return copy.deepcopy(self._devices)

    def get(self, device_id: str) -> Record | None:
        with self._lock:
            for record in self._devices:
                if record["id"] == device_id:
                    return copy.deepcopy(record)
            return None

    def save(self, record: Record) -> None:
        """Legt an oder ersetzt nach `id`. Wirft `MobileStoreReadOnly` oder `OSError`;
        dann bleibt der Speicherstand unverändert (Rollback)."""
        with self._lock:
            previous = copy.deepcopy(self._devices)
            for i, existing in enumerate(self._devices):
                if existing["id"] == record["id"]:
                    self._devices[i] = copy.deepcopy(record)
                    break
            else:
                self._devices.append(copy.deepcopy(record))
            try:
                self._save_to_disk()
            except BaseException:
                self._devices = previous
                raise

    def replace_all(self, records: list[Record]) -> None:
        """Ersetzt den ganzen Bestand in einem Schreibvorgang (Widerruf aller,
        Aufräumen). Rollback wie bei `save`."""
        with self._lock:
            previous = self._devices
            self._devices = copy.deepcopy(records)
            try:
                self._save_to_disk()
            except BaseException:
                self._devices = previous
                raise

    def prune(self, now: str) -> int:
        """Entfernt Geräte, die seit mehr als `FORGET_AFTER` abgelaufen sind. Liefert
        die Zahl der entfernten Datensätze; ohne Treffer wird nicht geschrieben."""
        limit = shift(now, -FORGET_AFTER)
        with self._lock:
            kept = [r for r in self._devices if r["expires_at"] >= limit]
            removed = len(self._devices) - len(kept)
            if removed:
                self.replace_all(kept)
            return removed
