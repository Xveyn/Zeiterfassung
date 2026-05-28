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
            return
        self._migrate_legacy_entries()

    def _migrate_legacy_entries(self):
        """Spendet alten Einträgen ohne modified_at/device_id/deleted die
        Sync-Metadaten. Idempotent: Einträge mit modified_at bleiben unberührt.
        modified_at wird aus der File-mtime abgeleitet (best lower bound)."""
        try:
            mtime = os.path.getmtime(self.filepath)
        except OSError:
            mtime = None
        fallback_modified_at = (
            datetime.datetime.fromtimestamp(mtime, datetime.timezone.utc)
            .strftime("%Y-%m-%dT%H:%M:%SZ")
            if mtime is not None
            else _utc_now_iso()
        )
        for date, entry in list(self._data.items()):
            if not isinstance(entry, dict):
                continue
            if "modified_at" in entry:
                continue
            entry.setdefault("pause", 0)
            entry["modified_at"] = fallback_modified_at
            entry["device_id"] = self.device_id
            entry["deleted"] = False

    def reload(self):
        """Verwirft den In-Memory-Stand und liest die Datei neu ein.

        Für Dev-Tools, die die JSON-Datei unter der laufenden App ersetzen
        (z.B. Reseed). Setzt `_data` erst leer, damit ein Reload nach dem
        Löschen der Datei nicht den alten Stand behält."""
        self._data = {}
        self._load()

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

    def save_many(self, updates):
        """Mehrere Einträge in einem einzigen Disk-Write speichern.

        updates: {date_str: {start, end, pause}}. Jeder Eintrag bekommt
        frische modified_at/device_id/deleted=False. Existierende Tombstones
        am selben Datum werden überschrieben.

        Leeres Dict ist No-op (kein Disk-Roundtrip).
        """
        if not updates:
            return
        now = _utc_now_iso()
        for date_str, payload in updates.items():
            self._data[date_str] = {
                "start": payload["start"],
                "end": payload["end"],
                "pause": payload.get("pause", 0),
                "modified_at": now,
                "device_id": self.device_id,
                "deleted": False,
            }
        self._save_to_disk()
