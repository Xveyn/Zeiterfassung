import datetime
import json
import os


def _utc_now_iso():
    # Z-Suffix statt +00:00 — kompatibel zu JS/Drive-Konventionen
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


_REQUIRED_ENTRY_KEYS = frozenset({"start", "end", "pause", "modified_at", "device_id", "deleted"})


class Storage:
    def __init__(self, filepath="zeiterfassung.json", device_id=""):
        self.filepath = filepath
        self.device_id = device_id
        self._data = {}
        self._load()

    def _load(self):
        if not os.path.exists(self.filepath):
            return
        try:
            with open(self.filepath, "r", encoding="utf-8") as f:
                self._data = json.load(f)
        except (json.JSONDecodeError, ValueError):
            stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
            os.replace(self.filepath, f"{self.filepath}.corrupt-{stamp}")
            self._data = {}

    def _save_to_disk(self):
        tmp = self.filepath + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self._data, f, indent=2, ensure_ascii=False)
        try:
            os.replace(tmp, self.filepath)
        except OSError:
            if os.path.exists(tmp):
                os.remove(tmp)
            raise

    @staticmethod
    def _user_shape(entry):
        """Reduziert ein Roh-Entry auf {start, end, pause} für UI-Callers."""
        return {"start": entry["start"], "end": entry["end"], "pause": entry.get("pause", 0)}

    def get_all(self):
        """Liefert {date: {start, end, pause}} ohne Tombstones."""
        return {
            date: self._user_shape(entry)
            for date, entry in self._data.items()
            if not entry.get("deleted")
        }

    def get_all_raw(self):
        """Liefert die kompletten Eintragsobjekte inkl. Metadaten und Tombstones.
        Nur für den Sync-Pfad."""
        return dict(self._data)

    def get(self, date_str):
        entry = self._data.get(date_str)
        if entry is None or entry.get("deleted"):
            return None
        return self._user_shape(entry)

    def save(self, date_str, start, end, pause=0):
        self._data[date_str] = {
            "start": start,
            "end": end,
            "pause": pause,
            "modified_at": _utc_now_iso(),
            "device_id": self.device_id,
            "deleted": False,
        }
        self._save_to_disk()

    def delete(self, date_str):
        if date_str not in self._data:
            return
        # Tombstone: behält die Zeile mit deleted=true, damit der Sync ein
        # Delete gegen ein veraltetes Save eines anderen Geräts durchsetzen kann.
        self._data[date_str] = {
            "start": None,
            "end": None,
            "pause": None,
            "modified_at": _utc_now_iso(),
            "device_id": self.device_id,
            "deleted": True,
        }
        self._save_to_disk()

    def apply_merge(self, merged_entries):
        """Ersetzt den kompletten Storage-Stand durch das Merge-Ergebnis.
        merged_entries: {date: {start, end, pause, modified_at, device_id, deleted}}.
        Wirft ValueError, wenn ein Eintrag Pflichtfelder vermissen lässt."""
        for date, entry in merged_entries.items():
            missing = _REQUIRED_ENTRY_KEYS - entry.keys()
            if missing:
                raise ValueError(
                    f"apply_merge: entry {date!r} missing keys {sorted(missing)}"
                )
        self._data = dict(merged_entries)
        self._save_to_disk()
