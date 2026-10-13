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
import os
import threading
from typing import Any

from src.json_store import atomic_write_json, load_json_or_quarantine
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
        data = load_json_or_quarantine(self.filepath)
        if data is None:  # nicht vorhanden oder korrupt (dann quarantäniert)
            self._data = {}
            return
        self._data = data
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
        atomic_write_json(self.filepath, self._data)

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

    @staticmethod
    def _phone_key(entry: Reservation) -> tuple[str, str]:
        """Ordnung für den LWW-Vergleich mit dem Handy: Zeitstempel, dann der Inhalt.
        Ohne den zweiten Teil entschiede bei gleicher Sekunde die Reihenfolge der
        Aufrufe (vgl. `sync._lww_key`). Nur Felder, die das Handy kennt: `gcal_event_id`
        und `send_reminder_minutes` gehören dem Desktop und zählen nicht."""
        slots = [{"start": s.get("start"), "end": s.get("end"),
                  "kategorie": s.get("kategorie", "")} for s in entry.get("slots", [])]
        content = json.dumps({"slots": slots, "deleted": entry.get("deleted") is True},
                             sort_keys=True, ensure_ascii=False)
        return (str(entry.get("modified_at") or ""), content)

    def merge_phone(self, days: dict[str, Reservation], *, floor: str = "",
                    now: str | None = None) -> bool:
        """Übernimmt vom Handy gesendete Tage per LWW. `days` ist bereits geprüft
        (`mobile_reservations.parse_reservations`). Ein Tag gewinnt nur mit einem
        **größeren** Schlüssel als der Desktop-Stand: dieselbe Anfrage zweimal ist
        damit ein No-op, ohne Schreiben und ohne Kalender-Abgleich.

        Zwei Uhren, zwei Korrekturen (Review, wie `mobile_sync._phone_doc` bei den
        Ist-Zeiten): `floor` (das `last_pull_at` des Handys + 1 s) hebt einen älteren
        Stempel an — das Handy schickt nur Tage, die es seit dem Abgleich geändert hat,
        eine nachgehende Handy-Uhr darf die Änderung nicht gegen eine frühere
        Desktop-Version verlieren. Und ein gewonnener Tag bekommt mindestens den
        Empfangszeitpunkt (`now`) als Stempel: der Kalender-Abgleich verwirft lokale Tage
        ohne Event, deren Stempel nicht über seinem Watermark liegt
        (`reservations_sync._merge_one_date`, Fall 4), und ein offline erfasster Tag
        käme sonst mit altem Stempel und ginge dort verloren.

        Slots erben `gcal_event_id` und `send_reminder_minutes` per Index (wie
        `save`). Ein Tombstone für einen unbekannten Tag wird verworfen: es gibt
        draußen nichts aufzuräumen. Geschrieben wird erst auf die Platte, dann in den
        Speicher — scheitert das Schreiben, bleibt der Stand unverändert.
        Liefert, ob sich etwas geändert hat."""
        with self._lock:
            merged = dict(self._data)
            changed = False
            received = now or utc_now_iso()
            for date, incoming in days.items():
                incoming = {**incoming, "modified_at": max(incoming["modified_at"], floor)}
                current = merged.get(date)
                if incoming.get("deleted") is True and current is None:
                    continue
                if current is not None and self._phone_key(incoming) <= self._phone_key(current):
                    continue
                if incoming.get("deleted") is True:
                    merged[date] = {"slots": [], "modified_at": max(incoming["modified_at"], received),
                                    "deleted": True}
                else:
                    old_slots = (current or {}).get("slots", [])
                    new_slots = []
                    for i, slot in enumerate(incoming["slots"]):
                        normalized = _normalize_slot(slot)
                        if i < len(old_slots):
                            normalized["gcal_event_id"] = old_slots[i].get("gcal_event_id")
                            normalized["send_reminder_minutes"] = _normalize_reminder_minutes(
                                old_slots[i].get("send_reminder_minutes"))
                        new_slots.append(normalized)
                    merged[date] = {"slots": new_slots, "modified_at": max(incoming["modified_at"], received),
                                    "deleted": False}
                changed = True
            if changed:
                atomic_write_json(self.filepath, merged)
                self._data = merged
            return changed

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


def reservations_active(store: Any, settings: Any) -> bool:
    """True, wenn Reservierungen angezeigt und bearbeitet werden dürfen: ein
    Store existiert UND der Nutzer hat sie eingeschaltet. Unabhängig vom
    Google-Kalender — der ist nur ein optionaler Abgleich."""
    return store is not None and bool(settings.get("reservations_enabled"))


def migrate_reservations_enabled(settings: Any) -> None:
    """Einmalige Umstellung beim Start: wer den Kalender-Abgleich an hatte, sah
    bisher Reservierungen und behält sie. Der Marker wird auch ohne
    Umstellung gesetzt — ein später bewusst ausgeschalteter Schalter wird nie
    wieder überschrieben."""
    if settings.get("reservations_migrated"):
        return
    updates: dict[str, Any] = {"reservations_migrated": True}
    if settings.get("gcal_enabled"):
        updates["reservations_enabled"] = True
    settings.set_many(updates)
