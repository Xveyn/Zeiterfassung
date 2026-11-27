# pyright: reportOptionalMemberAccess=true
"""Krankheitstage: Tagesdatensätze, Blöcke und JSON-Persistenz.

Gespeichert wird je Kalendertag ein Datensatz
`{minutes, modified_at, device_id, deleted}` (LWW je Tag im Sync). Ein
„Block" ist nur eine Ableitung: die maximale Folge lückenloser lebender Tage.
Der Datensatz trägt genau diese vier Felder, unbekannte entfallen beim Merge;
weitere Tagesdaten gehören deshalb in einen eigenen Bereich des Sync-Docs
(wie `sick` selbst), nie in den Datensatz.
Gesundheitsdaten: in Logs stehen höchstens Anzahlen, nie Datum oder Minuten.
"""

from __future__ import annotations

import datetime
import logging
import re
import threading
from dataclasses import dataclass
from typing import Any, Iterable

from src.absence import date_range
from src.json_store import atomic_write_json, load_json_or_quarantine
from src.time_utils import utc_now_iso

_log = logging.getLogger(__name__)

SickDay = dict[str, Any]

MAX_MINUTES = 1440
_STAMP = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z")
REQUIRED_SICK_KEYS = frozenset({"minutes", "modified_at", "device_id", "deleted"})


def _is_iso_date(value: object) -> bool:
    if not isinstance(value, str):
        return False
    try:
        return datetime.date.fromisoformat(value).isoformat() == value
    except ValueError:
        return False


def _valid_minutes(value: object) -> bool:
    return (isinstance(value, int) and not isinstance(value, bool)
            and 0 <= value <= MAX_MINUTES)


def clean_record(raw: object) -> SickDay | None:
    """Prüft einen Tagesdatensatz (Fremddaten); `None`, wenn unbrauchbar.
    Ein Tombstone trägt immer 0 Minuten, unbekannte Felder entfallen."""
    if not isinstance(raw, dict):
        return None
    minutes = raw.get("minutes")
    modified_at = raw.get("modified_at")
    device_id = raw.get("device_id")
    deleted = raw.get("deleted")
    if (not _valid_minutes(minutes) or not isinstance(modified_at, str)
            or not _STAMP.fullmatch(modified_at)
            or not isinstance(device_id, str) or not isinstance(deleted, bool)):
        return None
    return {"minutes": 0 if deleted else minutes, "modified_at": modified_at,
            "device_id": device_id, "deleted": deleted}


def clean_section(raw: object) -> dict[str, SickDay]:
    """Bereinigt den ganzen Bestand; verworfen wird nur Unbrauchbares, geloggt
    nur die Anzahl."""
    if not isinstance(raw, dict):
        return {}
    out: dict[str, SickDay] = {}
    dropped = 0
    for key, value in raw.items():
        rec = clean_record(value) if _is_iso_date(key) else None
        if rec is None:
            dropped += 1
            continue
        out[key] = rec
    if dropped:
        _log.warning("%d unbrauchbare Krankheitstage verworfen", dropped)
    return out


def runs(dates: Iterable[str]) -> list[tuple[str, str]]:
    """Maximale Folgen lückenloser Kalendertage als (von, bis), chronologisch."""
    ordered = sorted({datetime.date.fromisoformat(d) for d in dates})
    result: list[tuple[str, str]] = []
    start: datetime.date | None = None
    prev: datetime.date | None = None
    for day in ordered:
        if prev is not None and (day - prev).days == 1:
            prev = day
            continue
        if start is not None and prev is not None:
            result.append((start.isoformat(), prev.isoformat()))
        start = prev = day
    if start is not None and prev is not None:
        result.append((start.isoformat(), prev.isoformat()))
    return result


@dataclass(frozen=True)
class SickBlock:
    date_from: str
    date_to: str
    days: dict[str, int]

    @property
    def total_minutes(self) -> int:
        return sum(self.days.values())


def _check_days(days: dict[str, int]) -> None:
    for date_str, minutes in days.items():
        if not _is_iso_date(date_str):
            raise ValueError("Kein gültiges Datum")
        if not _valid_minutes(minutes):
            raise ValueError(f"Minuten außerhalb 0–{MAX_MINUTES}")


class SickStore:
    """Krankheitstage je Kalendertag. Teilt sich mit `Storage` das Lock, wenn
    eines übergeben wird (Sync-Apply läuft über beide Stores)."""

    def __init__(self, filepath: str = "sick.json", device_id: str = "",
                 lock: threading.RLock | None = None) -> None:
        self.filepath = filepath
        self.device_id = device_id
        self._lock = lock if lock is not None else threading.RLock()
        self._data: dict[str, SickDay] = {}
        self._load()

    def _load(self) -> None:
        self._data = clean_section(load_json_or_quarantine(self.filepath))

    def _save_to_disk(self) -> None:
        atomic_write_json(self.filepath, self._data)

    def _commit(self, new_data: dict[str, SickDay]) -> None:
        """Ersetzt den Speicher und schreibt einmal; scheitert das Schreiben,
        bleibt der alte Stand erhalten (Aufräumen und Weiterwerfen)."""
        previous = self._data
        self._data = new_data
        try:
            self._save_to_disk()
        except BaseException:
            self._data = previous
            raise

    def _live(self, minutes: int, stamp: str) -> SickDay:
        return {"minutes": minutes, "modified_at": stamp,
                "device_id": self.device_id, "deleted": False}

    def _tombstone(self, stamp: str) -> SickDay:
        return {"minutes": 0, "modified_at": stamp,
                "device_id": self.device_id, "deleted": True}

    def day_minutes(self) -> dict[str, int]:
        with self._lock:
            return {d: r["minutes"] for d, r in self._data.items()
                    if not r["deleted"]}

    def is_sick(self, date_str: str) -> bool:
        with self._lock:
            rec = self._data.get(date_str)
            return rec is not None and not rec["deleted"]

    def blocks(self) -> list[SickBlock]:
        minutes = self.day_minutes()
        return [self._block(minutes, a, b) for a, b in runs(minutes)]

    def block_for(self, date_str: str) -> SickBlock | None:
        minutes = self.day_minutes()
        if date_str not in minutes:
            return None
        for a, b in runs(minutes):
            if a <= date_str <= b:
                return self._block(minutes, a, b)
        return None

    @staticmethod
    def _block(minutes: dict[str, int], date_from: str, date_to: str) -> SickBlock:
        return SickBlock(date_from, date_to, {
            d.isoformat(): minutes[d.isoformat()]
            for d in date_range(date_from, date_to)})

    def save_range(self, days: dict[str, int]) -> None:
        _check_days(days)
        if not days:
            return
        with self._lock:
            stamp = utc_now_iso()
            new = dict(self._data)
            for date_str, minutes in days.items():
                new[date_str] = self._live(minutes, stamp)
            self._commit(new)

    def replace_block(self, old_dates: Iterable[str], days: dict[str, int]) -> None:
        """Schreibt `days` und macht die alten Tage außerhalb davon zu
        Tombstones, in einem Schreibvorgang."""
        _check_days(days)
        with self._lock:
            stamp = utc_now_iso()
            new = dict(self._data)
            for date_str in old_dates:
                if date_str not in days and date_str in new and not new[date_str]["deleted"]:
                    new[date_str] = self._tombstone(stamp)
            for date_str, minutes in days.items():
                new[date_str] = self._live(minutes, stamp)
            self._commit(new)

    def delete_days(self, dates: Iterable[str]) -> None:
        with self._lock:
            stamp = utc_now_iso()
            new = dict(self._data)
            changed = False
            for date_str in dates:
                if date_str in new and not new[date_str]["deleted"]:
                    new[date_str] = self._tombstone(stamp)
                    changed = True
            if changed:
                self._commit(new)

    def get_all_raw(self) -> dict[str, SickDay]:
        with self._lock:
            return {d: dict(r) for d, r in self._data.items()}

    def apply_merge(self, merged: dict[str, SickDay]) -> None:
        """Ersetzt den Stand durch das Merge-Ergebnis; geschrieben wird nur
        bei einer Änderung. Wirft `ValueError`, wenn ein Datensatz
        Pflichtfelder vermissen lässt (die Meldung nennt kein Datum)."""
        with self._lock:
            for rec in merged.values():
                missing = REQUIRED_SICK_KEYS - rec.keys()
                if missing:
                    raise ValueError(
                        f"apply_merge: Krankheitstag ohne {sorted(missing)}")
            new = {d: dict(r) for d, r in merged.items()}
            if new != self._data:
                self._commit(new)
