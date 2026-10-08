from __future__ import annotations

import datetime
import logging
import os
import threading
from typing import Any

from src.json_store import (
    atomic_write_json, backup_corrupt, load_json_or_quarantine, quarantine_corrupt,
)
from src.time_utils import utc_now_iso

# JSON-getragene Records (Audit N8): ein Slot {start, end, pause, kategorie};
# ein Entry {slots, modified_at, device_id, deleted}; der Store hält
# {ISO-Datum: Entry}. Werte sind heterogen (str/int/bool/list) → Any.
Slot = dict[str, Any]
Entry = dict[str, Any]

REQUIRED_ENTRY_KEYS = frozenset({"slots", "modified_at", "device_id", "deleted"})

log = logging.getLogger(__name__)

# Eine Pause über einen ganzen Tag hinaus ist kein Wert, sondern Müll.
MAX_PAUSE_MINUTES = 24 * 60


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


def sanitize_slot(slot: Any) -> Slot | None:
    """Ein wohlgeformter Ist-Zeit-Slot aus einem gespeicherten, oder `None`.

    Gespeicherte Slots sind Fremddaten: der Sync prüft nur, dass `slots` eine
    Liste ist, und eine Datei lässt sich von Hand ändern. Alles, was die Datei
    hergibt, läuft hier durch, bevor UI, Berichte und API es sehen:
    - Kein Objekt → `None` (der Slot entfällt).
    - `start`/`end` nur als Text, sonst `None` (`calculate_hours` zählt das 0).
    - `kategorie` nur als Text, sonst `""`.
    - `pause` eine ganze Zahl von 0 bis `MAX_PAUSE_MINUTES` (`30.0` zählt als 30),
      sonst `0`: `None`, Bool, Text, negativ, `inf`/`nan` und Riesen-Ints
      brächten sonst jede Rechnung damit zum Absturz.
    Weitere Schlüssel bleiben erhalten; das Original wird nie verändert."""
    if not isinstance(slot, dict):
        return None
    pause = slot.get("pause", 0)
    if isinstance(pause, float) and pause.is_integer():
        pause = int(pause)
    if isinstance(pause, bool) or not isinstance(pause, int) or not 0 <= pause <= MAX_PAUSE_MINUTES:
        pause = 0
    start, end, kategorie = slot.get("start"), slot.get("end"), slot.get("kategorie", "")
    clean = dict(slot)
    clean.update({
        "start": start if isinstance(start, str) else None,
        "end": end if isinstance(end, str) else None,
        "pause": pause,
        "kategorie": kategorie if isinstance(kategorie, str) else "",
    })
    return clean


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
        if not isinstance(data, dict):
            # Gültiges JSON, aber kein Store (Liste, Text, Zahl): sonst stürbe schon
            # der Start in der Migration. Wie unparsebar behandeln.
            quarantine_corrupt(
                self.filepath, f"Top-Level ist {type(data).__name__}, erwartet ein Objekt")
            self._data = {}
            return
        self._data = data
        dropped = self._drop_non_object_entries()
        self._migrate_legacy_entries()
        repaired = self._repair_slot_structure()
        if dropped or repaired:
            self._heal(f"{dropped} Eintrag/Einträge ohne Objektform, "
                       f"{repaired} Eintrag/Einträge mit kaputter Slot-Liste")

    def _drop_non_object_entries(self) -> int:
        """Entfernt Tage, deren Wert kein Objekt ist (`null`, Text, Liste)."""
        bad = [day for day, entry in self._data.items() if not isinstance(entry, dict)]
        for day in bad:
            del self._data[day]
        return len(bad)

    def _repair_slot_structure(self) -> int:
        """Macht aus einer Nicht-Liste als `slots` eine leere Liste und wirft
        Nicht-Objekte aus der Liste. Nur die STRUKTUR: ungewöhnliche Werte in einem
        Slot (`pause: null`) bleiben roh liegen und werden an der Lese-Grenze
        (`sanitize_slot`) bereinigt, damit der Sync keine spontanen Änderungen sieht."""
        fixed = 0
        for entry in self._data.values():
            slots = entry.get("slots")
            if not isinstance(slots, list):
                entry["slots"] = []
                fixed += 1
                continue
            objects = [slot for slot in slots if isinstance(slot, dict)]
            if len(objects) != len(slots):
                entry["slots"] = objects
                fixed += 1
        return fixed

    def _heal(self, problems: str) -> None:
        """Sichert die Datei, dann schreibt sie den reparierten Stand zurück —
        sonst fände jeder Start dasselbe vor und legte jedes Mal eine Sicherung an.
        Ohne Sicherung wird nicht geschrieben (nichts geht still verloren); der
        reparierte Stand gilt dann nur im Speicher."""
        try:
            backup_corrupt(self.filepath, problems)
            self._save_to_disk()
        except (OSError, ValueError):
            # ValueError: ein einzelnes Surrogat in einer Kategorie lässt sich nicht
            # als UTF-8 schreiben (UnicodeEncodeError) — das darf den Start nicht kosten.
            log.warning("%s: Reparatur nicht auf die Platte geschrieben, der Stand "
                        "gilt nur im Speicher", os.path.basename(self.filepath),
                        exc_info=True)

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
    def _user_shape(entry: Any) -> dict[str, Any]:
        """Reduziert ein Roh-Entry auf {slots: [...]} für UI-Caller.
        Liefert frische, bereinigte Kopien (`sanitize_slot`), damit Caller den
        internen Stand nicht mutieren und nie auf Fremddaten treffen, die ihre
        Rechnung zum Absturz bringen."""
        slots = entry.get("slots") if isinstance(entry, dict) else None
        if not isinstance(slots, list):
            return {"slots": []}
        return {"slots": [clean for clean in map(sanitize_slot, slots) if clean is not None]}

    def get_all(self) -> dict[str, dict[str, Any]]:
        """Liefert {date: {slots: [...]}} ohne Tombstones."""
        with self._lock:
            return {
                date: self._user_shape(entry)
                for date, entry in self._data.items()
                if isinstance(entry, dict) and not entry.get("deleted")
            }

    def get_all_raw(self) -> dict[str, Entry]:
        """Liefert die kompletten Eintragsobjekte inkl. Metadaten und Tombstones.
        Nur für den Sync-Pfad."""
        with self._lock:
            return dict(self._data)

    def get(self, date_str: str) -> dict[str, Any] | None:
        with self._lock:
            entry = self._data.get(date_str)
            if not isinstance(entry, dict) or entry.get("deleted"):
                return None
            return self._user_shape(entry)

    def _restore_day(self, date_str: str, previous: Entry | None) -> None:
        if previous is None:
            self._data.pop(date_str, None)
        else:
            self._data[date_str] = previous

    def save(self, date_str: str, slots: list[Slot]) -> None:
        with self._lock:
            previous = self._data.get(date_str)
            self._data[date_str] = {
                "slots": [_normalize_slot(s) for s in slots],
                "modified_at": utc_now_iso(),
                "device_id": self.device_id,
                "deleted": False,
            }
            try:
                self._save_to_disk()
            except BaseException:
                # Scheitert das Schreiben (Platte voll, Rechte, nicht kodierbares
                # Zeichen), darf der Speicher dem Stand der Platte nicht vorauslaufen:
                # sonst hält ein Retry den Tag für gespeichert, und jeder spätere
                # Save schriebe ihn unbemerkt mit.
                self._restore_day(date_str, previous)
                raise

    def delete(self, date_str: str) -> None:
        with self._lock:
            if date_str not in self._data:
                return
            # Tombstone: behält die Zeile mit deleted=true, damit der Sync ein
            # Delete gegen ein veraltetes Save eines anderen Geräts durchsetzen kann.
            previous = self._data[date_str]
            self._data[date_str] = {
                "slots": [],
                "modified_at": utc_now_iso(),
                "device_id": self.device_id,
                "deleted": True,
            }
            try:
                self._save_to_disk()
            except BaseException:
                self._restore_day(date_str, previous)   # Begründung: siehe save()
                raise

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
            previous_data = self._data
            self._data = dict(merged_entries)
            try:
                self._save_to_disk()
            except BaseException:
                self._data = previous_data              # Begründung: siehe save()
                raise

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
            previous_data = dict(self._data)
            now = utc_now_iso()
            for date_str, payload in updates.items():
                self._data[date_str] = {
                    "slots": [_normalize_slot(s) for s in payload.get("slots", [])],
                    "modified_at": now,
                    "device_id": self.device_id,
                    "deleted": False,
                }
            try:
                self._save_to_disk()
            except BaseException:
                self._data = previous_data              # Begründung: siehe save()
                raise
