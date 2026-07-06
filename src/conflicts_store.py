import datetime
import json
import os
import threading


class ConflictsStore:
    """JSON-Persistenz für die lokale Konflikt-Liste. Spiegelt die conflicts-Liste
    aus dem Sync-File, damit der ConflictsDialog ohne Netz funktioniert."""

    def __init__(self, filepath="conflicts.json", lock=None):
        self.filepath = filepath
        # Geteilter Daten-Lock (Audit H1/H2) — siehe storage.py.
        self._lock = lock if lock is not None else threading.RLock()
        self._conflicts = []
        self._load()

    def _load(self):
        if not os.path.exists(self.filepath):
            return
        try:
            with open(self.filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, ValueError):
            stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
            os.replace(self.filepath, f"{self.filepath}.corrupt-{stamp}")
            return
        if isinstance(data, list):
            self._conflicts = data

    def _save_to_disk(self):
        tmp = self.filepath + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self._conflicts, f, indent=2, ensure_ascii=False)
        try:
            os.replace(tmp, self.filepath)
        except OSError:
            if os.path.exists(tmp):
                os.remove(tmp)
            raise

    def get_all(self):
        with self._lock:
            return list(self._conflicts)

    def save_all(self, conflicts):
        with self._lock:
            self._conflicts = list(conflicts)
            self._save_to_disk()

    def count_unresolved(self):
        with self._lock:
            return sum(1 for c in self._conflicts if not c.get("resolved"))
