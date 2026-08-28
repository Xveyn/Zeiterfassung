from __future__ import annotations

import datetime
import os
import threading
from typing import Any

from src.json_store import atomic_write_json, load_json_or_quarantine
from src.time_utils import utc_now_iso

# JSON-getragene Records (Audit N8): ein Slot {start, end, pause, kategorie};
# ein Entry {slots, modified_at, device_id, deleted}; der Store hält
# {ISO-Datum: Entry}. Werte sind heterogen (str/int/bool/list) → Any.
Slot = dict[str, Any]
Entry = dict[str, Any]

REQUIRED_ENTRY_KEYS = frozenset({"slots", "modified_at", "device_id", "deleted"})


def _normalize_slot(slot: Slot) -> Slot:
    """Vervollständigt einen Ist-Zeit-Slot auf {start, end, pause, kategorie}.

    Fehlende `pause` → 0, fehlende `kategorie` → "" (= keine Kategorie,
    Verhalten wie vor der Migration). Storage validiert die Zeitwerte
    bewusst nicht (wie bisher) — das ist Sache der UI/Validierung (AP3)."""
    return {
        "start": slot.get("start"),
        "end": slot.get("end"),
        "pause": slot.get("pause", 0),
        "kategorie": slot.get("kategorie", ""),
    }


class Storage:
    def __init__(self, filepath: str = "zeiterfassung.json", device_id: str = "",
                 lock: threading.RLock | None = None) -> None:
        self.filepath = filepath
        self.device_id = device_id
        # Geteilter Daten-Lock (Audit H1/H2): main() injiziert EINEN RLock in
        # alle vier Stores; ohne Injektion (Tests, Alt-Aufrufer) eigener Lock.
        # _load()/Migration laufen vor dem Teilen (single-threaded Boot) —
        # bewusst ungelockt.
        self._lock = lock if lock is not None else threading.RLock()
        self._data: dict[str, Entry] = {}
        self._load()

    def _load(self) -> None:
        data = load_json_or_quarantine(self.filepath)
        if data is None:  # nicht vorhanden oder korrupt (dann quarantäniert)
            self._data = {}
            return
        self._data = data
        self._migrate_legacy_entries()

    def _migrate_legacy_entries(self) -> None:
        """Rüstet Sync-Metadaten nach UND wrappt alte Ein-Eintrag-Tage in eine
        Slot-Liste. Idempotent: Einträge mit `slots` bleiben unangetastet,
        Einträge mit `modified_at` behalten ihre Metadaten.
        modified_at wird (für ganz alte Einträge ohne Metadaten) aus der
        File-mtime abgeleitet (best lower bound)."""
        try:
            mtime = os.path.getmtime(self.filepath)
        except OSError:
            mtime = None
        fallback_modified_at = (
            datetime.datetime.fromtimestamp(mtime, datetime.timezone.utc)
            .strftime("%Y-%m-%dT%H:%M:%SZ")
            if mtime is not None
            else utc_now_iso()
        )
        for _date, entry in list(self._data.items()):
            if not isinstance(entry, dict):
                continue
            # 1. Sync-Metadaten für ganz alte Einträge nachrüsten.
            if "modified_at" not in entry:
                entry["modified_at"] = fallback_modified_at
                entry["device_id"] = self.device_id
                entry.setdefault("deleted", False)
            # 2. Slot-Wrapping für Einträge im alten Ein-Eintrag-Schema.
            if "slots" not in entry:
                if entry.get("deleted"):
                    entry["slots"] = []
                else:
                    entry["slots"] = [{
                        "start": entry.get("start"),
                        "end": entry.get("end"),
                        "pause": entry.get("pause", 0),
                        "kategorie": "",
                    }]
                entry.pop("start", None)
                entry.pop("end", None)
                entry.pop("pause", None)
                entry.setdefault("device_id", self.device_id)
                entry.setdefault("deleted", False)

    def _save_to_disk(self) -> None:
        atomic_write_json(self.filepath, self._data)

    @staticmethod
    def _user_shape(entry: Entry) -> dict[str, Any]:
        """Reduziert ein Roh-Entry auf {slots: [...]} für UI-Caller.
        Liefert frische Kopien, damit Caller den internen Stand nicht mutieren."""
        return {"slots": [dict(s) for s in entry.get("slots", [])]}

    def get_all(self) -> dict[str, dict[str, Any]]:
        """Liefert {date: {slots: [...]}} ohne Tombstones."""
        with self._lock:
            return {
                date: self._user_shape(entry)
                for date, entry in self._data.items()
                if not entry.get("deleted")
            }

    def get_all_raw(self) -> dict[str, Entry]:
        """Liefert die kompletten Eintragsobjekte inkl. Metadaten und Tombstones.
        Nur für den Sync-Pfad."""
        with self._lock:
            return dict(self._data)

    def get(self, date_str: str) -> dict[str, Any] | None:
        with self._lock:
            entry = self._data.get(date_str)
            if entry is None or entry.get("deleted"):
                return None
            return self._user_shape(entry)

    def save(self, date_str: str, slots: list[Slot]) -> None:
        with self._lock:
            self._data[date_str] = {
                "slots": [_normalize_slot(s) for s in slots],
                "modified_at": utc_now_iso(),
                "device_id": self.device_id,
                "deleted": False,
            }
            self._save_to_disk()

    def delete(self, date_str: str) -> None:
        with self._lock:
            if date_str not in self._data:
                return
            # Tombstone: behält die Zeile mit deleted=true, damit der Sync ein
            # Delete gegen ein veraltetes Save eines anderen Geräts durchsetzen kann.
            self._data[date_str] = {
                "slots": [],
                "modified_at": utc_now_iso(),
                "device_id": self.device_id,
                "deleted": True,
            }
            self._save_to_disk()

    def apply_merge(self, merged_entries: dict[str, Entry]) -> None:
        """Ersetzt den kompletten Storage-Stand durch das Merge-Ergebnis.
        merged_entries: {date: {slots, modified_at, device_id, deleted}}.
        Wirft ValueError, wenn ein Eintrag Pflichtfelder vermissen lässt."""
        with self._lock:
            for date, entry in merged_entries.items():
                missing = REQUIRED_ENTRY_KEYS - entry.keys()
                if missing:
                    raise ValueError(
                        f"apply_merge: entry {date!r} missing keys {sorted(missing)}"
                    )
            self._data = dict(merged_entries)
            self._save_to_disk()

    def save_many(self, updates: dict[str, dict[str, Any]]) -> None:
        """Mehrere Einträge in einem einzigen Disk-Write speichern.

        updates: {date_str: {"slots": [...]}}. Jeder Eintrag bekommt
        frische modified_at/device_id/deleted=False. Existierende Tombstones
        am selben Datum werden überschrieben.

        Leeres Dict ist No-op (kein Disk-Roundtrip).
        """
        if not updates:
            return
        with self._lock:
            now = utc_now_iso()
            for date_str, payload in updates.items():
                self._data[date_str] = {
                    "slots": [_normalize_slot(s) for s in payload.get("slots", [])],
                    "modified_at": now,
                    "device_id": self.device_id,
                    "deleted": False,
                }
            self._save_to_disk()
