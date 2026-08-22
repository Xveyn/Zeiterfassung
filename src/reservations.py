"""JSON-Persistenz der Reservierungen (geplante Arbeitszeiten).

Reservierungen sind ein eigenständiges Konzept neben den erfassten Ist-Zeiten
(`storage.py`). Sie werden über `gcal.py` / `reservations_sync.py` mit einem
Google Kalender abgeglichen — NICHT über die Drive-Multi-Device-Sync. Daher
fehlt hier (anders als bei `Storage`) das `device_id`-Feld.

Schema pro Tag (ISO-Datum als Schlüssel):
    {slots: [{start, end, kategorie, gcal_event_id, send_reminder_minutes}], modified_at, deleted}
`gcal_event_id` ist None, bis der Slot erstmals in den Kalender gepusht wurde.
`send_reminder_minutes` ist None oder die Minuten vor Slot-Ende, zu denen an
das Verschicken der Arbeitszeiten erinnert wird — höchstens ein Slot pro Tag
trägt einen Wert.
Eine gelöschte Reservierung bleibt als Tombstone (deleted=True, slots=[])
erhalten, bis der Reconcile die zugehörigen Events entfernt hat.
"""

from __future__ import annotations

import datetime
import json
import logging
import os
import threading
from typing import Any

from src.time_utils import utc_now_iso

# JSON-getragene Records (Audit N8): ein Slot {start, end, kategorie,
# gcal_event_id}; ein Reservierungs-Record {slots, modified_at, deleted};
# der Store hält {ISO-Datum: Reservation}. Werte sind heterogen → Any.
Slot = dict[str, Any]
Reservation = dict[str, Any]

_REQUIRED_RESERVATION_KEYS = frozenset({"slots", "modified_at", "deleted"})


def _normalize_reminder_minutes(value: Any) -> int | None:
    """Erinnerungs-Minuten am Reservierungs-Slot: int in [0, 120] oder None.

    Alles andere (bool, String, Ausreißer) wird zu None — dieselbe Toleranz,
    mit der der Store auch sonst korrupte Werte wegnormalisiert, statt beim
    Laden zu werfen.
    """
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value if 0 <= value <= 120 else None


def _normalize_slot(slot: Slot) -> Slot:
    """Vervollständigt einen Reservierungs-Slot auf
    {start, end, kategorie, gcal_event_id, send_reminder_minutes}. Fehlende
    `kategorie` → "", fehlende `gcal_event_id` → None, fehlende/ungültige
    `send_reminder_minutes` → None."""
    return {
        "start": slot.get("start"),
        "end": slot.get("end"),
        "kategorie": slot.get("kategorie", ""),
        "gcal_event_id": slot.get("gcal_event_id"),
        "send_reminder_minutes": _normalize_reminder_minutes(
            slot.get("send_reminder_minutes")),
    }


class ReservationStore:
    def __init__(self, filepath: str = "reservations.json",
                 lock: threading.RLock | None = None) -> None:
        self.filepath = filepath
        # Geteilter Daten-Lock (Audit H1/H2) — siehe storage.py.
        self._lock = lock if lock is not None else threading.RLock()
        self._data: dict[str, Reservation] = {}
        self._load()

    def _load(self) -> None:
        if not os.path.exists(self.filepath):
            return
        try:
            with open(self.filepath, "r", encoding="utf-8") as f:
                self._data = json.load(f)
        except (json.JSONDecodeError, ValueError):
            stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
            target = f"{self.filepath}.corrupt-{stamp}"
            os.replace(self.filepath, target)
            logging.getLogger(__name__).warning(
                "%s korrupt (JSON nicht parsebar) — nach %s in Quarantäne "
                "verschoben, starte leer",
                os.path.basename(self.filepath), os.path.basename(target),
            )
            self._data = {}
            return
        self._migrate_legacy_reservations()

    def _migrate_legacy_reservations(self) -> None:
        """Wrappt alte Ein-Reservierung-Tage in eine Slot-Liste. Idempotent:
        Einträge mit `slots` bleiben unangetastet. modified_at/deleted werden
        nur gesetzt, falls sie fehlen (alte Dateien tragen sie i.d.R. bereits);
        Fallback ist die File-mtime (best lower bound)."""
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
            if "slots" in entry:
                continue
            if entry.get("deleted"):
                entry["slots"] = []
            else:
                entry["slots"] = [{
                    "start": entry.get("start"),
                    "end": entry.get("end"),
                    "kategorie": "",
                    "gcal_event_id": entry.get("gcal_event_id"),
                    "send_reminder_minutes": None,
                }]
            entry.pop("start", None)
            entry.pop("end", None)
            entry.pop("gcal_event_id", None)
            entry.setdefault("modified_at", fallback_modified_at)
            entry.setdefault("deleted", False)

    def _save_to_disk(self) -> None:
        tmp = self.filepath + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self._data, f, indent=2, ensure_ascii=False)
            # N1: fsync vor os.replace (Durability bei Crash/Stromausfall).
            f.flush()
            os.fsync(f.fileno())
        try:
            os.replace(tmp, self.filepath)
        except OSError:
            if os.path.exists(tmp):
                os.remove(tmp)
            raise

    @staticmethod
    def _user_shape(entry: Reservation) -> dict[str, Any]:
        """User-Shape: Slots ohne das interne Feld gcal_event_id.

        `send_reminder_minutes` ist dagegen Teil der User-Shape: der
        Tages-Dialog zeigt es an, und der Teil-Lösch-Pfad in ui.py speichert
        die verbleibenden Slots aus genau dieser Shape zurück — fehlte das
        Feld hier, ginge die Markierung beim Löschen eines anderen Slots
        verloren.
        """
        return {"slots": [
            {"start": s.get("start"), "end": s.get("end"),
             "kategorie": s.get("kategorie", ""),
             "send_reminder_minutes": s.get("send_reminder_minutes")}
            for s in entry.get("slots", [])
        ]}

    def get_all(self) -> dict[str, dict[str, Any]]:
        """{date: {slots: [...]}} ohne Tombstones — für die UI."""
        with self._lock:
            return {
                date: self._user_shape(entry)
                for date, entry in self._data.items()
                if not entry.get("deleted")
            }

    def get_all_raw(self) -> dict[str, Reservation]:
        """Komplette Objekte inkl. Metadaten, gcal_event_id und Tombstones —
        für den Reconcile."""
        with self._lock:
            return dict(self._data)

    def get(self, date_str: str) -> dict[str, Any] | None:
        with self._lock:
            entry = self._data.get(date_str)
            if entry is None or entry.get("deleted"):
                return None
            return self._user_shape(entry)

    def save(self, date_str: str, slots: list[Slot]) -> None:
        """Legt die Reservierungs-Slots eines Tages an oder überschreibt sie.

        Dialog-Edits liefern Slots OHNE gcal_event_id. Damit der Reconcile die
        zugehörigen Kalender-Events aktualisiert statt sie zu löschen und neu
        anzulegen, übernehmen wir bestehende event_ids positionsweise vom
        vorherigen Stand. Eine explizit mitgelieferte gcal_event_id hat Vorrang;
        Zeilen über den Altbestand hinaus bleiben ohne id (→ neues Event)."""
        with self._lock:
            existing_slots = (self._data.get(date_str) or {}).get("slots", [])
            new_slots = []
            for i, s in enumerate(slots):
                ns = _normalize_slot(s)
                if ns["gcal_event_id"] is None and i < len(existing_slots):
                    ns["gcal_event_id"] = existing_slots[i].get("gcal_event_id")
                new_slots.append(ns)
            self._data[date_str] = {
                "slots": new_slots,
                "modified_at": utc_now_iso(),
                "deleted": False,
            }
            self._save_to_disk()

    def delete(self, date_str: str) -> None:
        """Tombstone schreiben (slots=[]). Der Reconcile entfernt die
        zugehörigen Kalender-Events über den vollständigen Event-Pull (AP7)."""
        with self._lock:
            if date_str not in self._data:
                return
            self._data[date_str] = {
                "slots": [],
                "modified_at": utc_now_iso(),
                "deleted": True,
            }
            self._save_to_disk()

    def apply_reconciled(self, reconciled: dict[str, Reservation]) -> None:
        """Ersetzt den kompletten Stand durch das Reconcile-Ergebnis.
        Wirft ValueError, wenn ein Eintrag Pflichtfelder vermissen lässt —
        analog zu Storage.apply_merge."""
        with self._lock:
            for date, entry in reconciled.items():
                missing = _REQUIRED_RESERVATION_KEYS - entry.keys()
                if missing:
                    raise ValueError(
                        f"apply_reconciled: entry {date!r} missing keys {sorted(missing)}"
                    )
            self._data = dict(reconciled)
            self._save_to_disk()
