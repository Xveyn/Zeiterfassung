"""Cursor der Boxen am Relay (`have`, dauerhaft), #358.

Je Box die Version (`ver`) des zuletzt verarbeiteten Slots; beim Verbinden als `have` gemeldet. Die
Datei trägt nur sha256 der Geheimnisse und wird bei jedem Abgleich geschrieben, deshalb ohne
ACL-Härtung (wie `mobile_store`). Ein Schreibfehler wirft nie: schlimmstenfalls kommt eine Antwort
nach einem Neustart noch einmal (der Adapter ist über `last_seq` gesichert). Format und Vertrag:
`src/CLAUDE.md`, Eintrag `mobile_box_cursor.py`.
"""
from __future__ import annotations

import hashlib
import logging
import threading
from collections.abc import Iterable
from typing import Any

from src.json_store import atomic_write_json, load_json_or_quarantine, quarantine_corrupt

log = logging.getLogger(__name__)

SCHEMA_VERSION = 1
_MAX_VER = 2 ** 31


def _digest(secret: str) -> str:
    return hashlib.sha256(secret.encode()).hexdigest()


def _valid_ver(ver: object) -> bool:
    return isinstance(ver, int) and not isinstance(ver, bool) and 0 <= ver < _MAX_VER


class MobileBoxCursor:
    def __init__(self, filepath: str = "mobile_box_cursor.json") -> None:
        self.filepath = filepath
        self._lock = threading.Lock()
        self._have: dict[str, int] = {}
        self._load()

    def _load(self) -> None:
        try:
            data = load_json_or_quarantine(self.filepath)
        except OSError as exc:
            log.warning("mobile_box_cursor.json nicht lesbar (%s) — Start ohne Cursor",
                        type(exc).__name__)
            return
        if data is None:
            return
        if not isinstance(data, dict):
            quarantine_corrupt(self.filepath,
                               f"Top-Level ist {type(data).__name__}, erwartet ein Objekt")
            return
        raw = data.get("have")
        if not isinstance(raw, dict):
            return
        skipped = 0
        for key, ver in raw.items():
            if isinstance(key, str) and len(key) == 64 and _valid_ver(ver):
                self._have[key] = ver
            else:
                skipped += 1
        if skipped:
            log.warning("mobile_box_cursor.json: %d unbrauchbare Einträge übersprungen", skipped)

    def _save_locked(self) -> None:
        document: dict[str, Any] = {"schema_version": SCHEMA_VERSION, "have": dict(self._have)}
        try:
            atomic_write_json(self.filepath, document)
        except OSError as exc:
            # Der Wert bleibt im Speicher; ein verlorener Cursor kostet nur eine erneute Zustellung.
            log.warning("mobile_box_cursor.json nicht geschrieben (%s)", type(exc).__name__)

    def get(self, secret: str) -> int:
        with self._lock:
            return self._have.get(_digest(secret), 0)

    def advance(self, secret: str, ver: int) -> bool:
        """Speichert `ver` nur, wenn es größer ist; `True` bei Änderung. Wirft nie."""
        if not _valid_ver(ver):
            return False
        key = _digest(secret)
        with self._lock:
            if ver <= self._have.get(key, 0):
                return False
            self._have[key] = ver
            self._save_locked()
            return True

    def reset(self, secret: str) -> None:
        """Vergisst den Cursor einer Box (Box wurde am Relay geleert, `wiped`)."""
        key = _digest(secret)
        with self._lock:
            if key in self._have:
                del self._have[key]
                self._save_locked()

    def retain(self, secrets: Iterable[str]) -> None:
        """Behält nur die Cursor der genannten Boxen."""
        keep = {_digest(s) for s in secrets}
        with self._lock:
            dropped = [k for k in self._have if k not in keep]
            if not dropped:
                return
            for key in dropped:
                del self._have[key]
            self._save_locked()
