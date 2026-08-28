from __future__ import annotations

import threading
from typing import Any

from src.json_store import atomic_write_json, load_json_or_quarantine

# Ein Konflikt-Record, wie er in conflicts.json / im Sync-Doc liegt
# (id, kind, key, candidates, detected_at, resolved, resolution, …). Die
# Felder sind heterogen (str/bool/list), daher Any als Wert (Audit N8).
Conflict = dict[str, Any]


class ConflictsStore:
    """JSON-Persistenz für die lokale Konflikt-Liste. Spiegelt die conflicts-Liste
    aus dem Sync-File, damit der ConflictsDialog ohne Netz funktioniert."""

    def __init__(self, filepath: str = "conflicts.json",
                 lock: threading.RLock | None = None) -> None:
        self.filepath = filepath
        # Geteilter Daten-Lock (Audit H1/H2) — siehe storage.py.
        self._lock = lock if lock is not None else threading.RLock()
        self._conflicts: list[Conflict] = []
        self._load()

    def _load(self) -> None:
        data = load_json_or_quarantine(self.filepath)
        # Kein isinstance-Treffer (fehlend, korrupt, kein Array) → leere Liste
        # aus __init__ bleibt stehen.
        if isinstance(data, list):
            self._conflicts = data

    def _save_to_disk(self) -> None:
        atomic_write_json(self.filepath, self._conflicts)

    def get_all(self) -> list[Conflict]:
        with self._lock:
            return list(self._conflicts)

    def save_all(self, conflicts: list[Conflict]) -> None:
        with self._lock:
            self._conflicts = list(conflicts)
            self._save_to_disk()

    def count_unresolved(self) -> int:
        with self._lock:
            return sum(1 for c in self._conflicts if not c.get("resolved"))

    def unresolved_entry_keys(self) -> set[str]:
        """ISO-Datums-Keys aller ungelösten Konflikte vom Typ 'entry' — für
        den Konflikt-Hinweis in der Kalenderzelle und das Linksklick-Routing
        (App._open_dialog: Konflikttag → ConflictsDialog statt Tages-Dialog)."""
        with self._lock:
            return {
                c["key"] for c in self._conflicts
                if c.get("kind") == "entry" and not c.get("resolved")
            }
