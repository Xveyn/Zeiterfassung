"""JSON-Persistenz der Reservierungen (geplante Arbeitszeiten).

Reservierungen sind ein eigenständiges Konzept neben den erfassten Ist-Zeiten
(`storage.py`). Sie werden über `gcal.py` / `reservations_sync.py` mit einem
Google Kalender abgeglichen — NICHT über die Drive-Multi-Device-Sync. Daher
fehlt hier (anders als bei `Storage`) das `device_id`-Feld.

Schema pro Tag (ISO-Datum als Schlüssel):
    {start, end, modified_at, deleted, gcal_event_id}
`gcal_event_id` ist None, bis die Reservierung erstmals in den Kalender
gepusht wurde. Eine gelöschte Reservierung bleibt als Tombstone (deleted=True)
erhalten, bis der Reconcile das Event entfernt hat.
"""

import datetime
import json
import os


def _utc_now_iso():
    # Z-Suffix statt +00:00 — konsistent zu storage.py / sync.py.
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


_REQUIRED_RESERVATION_KEYS = frozenset(
    {"start", "end", "modified_at", "deleted", "gcal_event_id"}
)


class ReservationStore:
    def __init__(self, filepath="reservations.json"):
        self.filepath = filepath
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
        return {"start": entry["start"], "end": entry["end"]}

    def get_all(self):
        """{date: {start, end}} ohne Tombstones — für die UI."""
        return {
            date: self._user_shape(entry)
            for date, entry in self._data.items()
            if not entry.get("deleted")
        }

    def get_all_raw(self):
        """Komplette Objekte inkl. Metadaten und Tombstones — für den Reconcile."""
        return dict(self._data)

    def get(self, date_str):
        entry = self._data.get(date_str)
        if entry is None or entry.get("deleted"):
            return None
        return self._user_shape(entry)

    def save(self, date_str, start, end):
        """Legt eine Reservierung an oder überschreibt sie. Eine schon
        vorhandene gcal_event_id bleibt erhalten, damit der Reconcile das
        bestehende Event aktualisiert statt ein zweites anzulegen."""
        existing = self._data.get(date_str) or {}
        self._data[date_str] = {
            "start": start,
            "end": end,
            "modified_at": _utc_now_iso(),
            "deleted": False,
            "gcal_event_id": existing.get("gcal_event_id"),
        }
        self._save_to_disk()

    def delete(self, date_str):
        """Tombstone schreiben. gcal_event_id bleibt erhalten, damit der
        Reconcile weiß, welches Event zu löschen ist."""
        existing = self._data.get(date_str)
        if existing is None:
            return
        self._data[date_str] = {
            "start": None,
            "end": None,
            "modified_at": _utc_now_iso(),
            "deleted": True,
            "gcal_event_id": existing.get("gcal_event_id"),
        }
        self._save_to_disk()

    def apply_reconciled(self, reconciled):
        """Ersetzt den kompletten Stand durch das Reconcile-Ergebnis.
        Wirft ValueError, wenn ein Eintrag Pflichtfelder vermissen lässt —
        analog zu Storage.apply_merge."""
        for date, entry in reconciled.items():
            missing = _REQUIRED_RESERVATION_KEYS - entry.keys()
            if missing:
                raise ValueError(
                    f"apply_reconciled: entry {date!r} missing keys {sorted(missing)}"
                )
        self._data = dict(reconciled)
        self._save_to_disk()
