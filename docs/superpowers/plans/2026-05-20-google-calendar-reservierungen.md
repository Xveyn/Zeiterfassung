# Google-Kalender-Reservierungen Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Zukünftige Arbeitszeiten als eigenständige „Reservierungen" verwalten und sie einseitig in einen vom User wählbaren Google Kalender pushen, der zugleich der geräteübergreifende Speicher ist.

**Architecture:** Drei neue Module spiegeln bestehende Vorlagen — `reservations.py` (lokaler JSON-Store, wie `storage.py`), `gcal.py` (Calendar-API-Wrapper, wie `mail.py`), `reservations_sync.py` (pure `merge_reservations()` + Orchestrator `reconcile_reservations()`, wie `sync.py`). Der Abgleich ist ein Reconcile (pull → LWW-merge → push); der Kalender ist die Quelle der Wahrheit, ein Wasserstand unterscheidet lokale Löschungen von remote-Neuanlagen. Die Drive-Multi-Device-Sync bleibt unangetastet.

**Tech Stack:** Python 3, Tkinter, `google-api-python-client` / `google-auth-oauthlib` (bereits durch Gmail/Drive vorhanden), pytest.

**Spec:** `docs/superpowers/specs/2026-05-20-google-calendar-reservierungen-design.md`

**Konventionen:** Lazy Google-Imports in `gcal.py` (CI installiert kein `requirements.txt`), atomic JSON-Writes (`.tmp` + `os.replace`), `_utc_now_iso()` mit `Z`-Suffix, Fehler im Sendepfad als `messagebox` mit Traceback, Worker-Threads marshallen über `root.after(0, …)`, deutschsprachige Kommentare.

---

## Task 1: Settings — neue Keys + Whitelist-Synchronität

**Files:**
- Modify: `src/settings.py`
- Modify: `src/sync.py`
- Test: `tests/test_settings.py`

- [ ] **Step 1: Failing-Tests schreiben**

An `tests/test_settings.py` anhängen:

```python
def test_gcal_defaults_present():
    from src.settings import DEFAULTS
    assert DEFAULTS["gcal_enabled"] is False
    assert DEFAULTS["gcal_calendar_id"] == ""
    assert DEFAULTS["last_calendar_sync_at"] == ""


def test_gcal_calendar_id_is_synced_setting():
    from src.settings import SYNCED_SETTING_KEYS
    assert "gcal_calendar_id" in SYNCED_SETTING_KEYS


def test_synced_whitelists_in_settings_and_sync_match():
    """Die Whitelist existiert dupliziert in settings.py und sync.py und
    muss identisch bleiben — sonst mergt sync.py einen Key nicht."""
    from src.settings import SYNCED_SETTING_KEYS as a
    from src.sync import SYNCED_SETTING_KEYS as b
    assert set(a) == set(b)
```

- [ ] **Step 2: Tests laufen lassen — müssen fehlschlagen**

Run: `pytest tests/test_settings.py -k gcal_defaults_present -v`
Expected: FAIL mit `KeyError: 'gcal_enabled'`

- [ ] **Step 3: `src/settings.py` anpassen**

In `DEFAULTS` direkt nach `"drive_etag": "",` einfügen:

```python
    "drive_etag": "",
    "gcal_enabled": False,
    "gcal_calendar_id": "",
    "last_calendar_sync_at": "",
```

`SYNCED_SETTING_KEYS` (oben in der Datei) erweitern:

```python
SYNCED_SETTING_KEYS = (
    "recipient", "name", "hourly_rate",
    "mail_subject", "mail_greeting", "mail_content", "mail_closing",
    "gcal_calendar_id",
)
```

- [ ] **Step 4: `src/sync.py` anpassen**

`SYNCED_SETTING_KEYS` (oben in der Datei) identisch erweitern:

```python
SYNCED_SETTING_KEYS = (
    "recipient", "name", "hourly_rate",
    "mail_subject", "mail_greeting", "mail_content", "mail_closing",
    "gcal_calendar_id",
)
```

- [ ] **Step 5: Tests laufen lassen — müssen bestehen**

Run: `pytest tests/test_settings.py tests/test_sync.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/settings.py src/sync.py tests/test_settings.py
git commit -m "feat(settings): add gcal_enabled/gcal_calendar_id/last_calendar_sync_at keys"
```

---

## Task 2: `ReservationStore` — lokaler JSON-Store

**Files:**
- Create: `src/reservations.py`
- Test: `tests/test_reservations.py`

- [ ] **Step 1: Failing-Tests schreiben**

Neue Datei `tests/test_reservations.py`:

```python
import os
from unittest import mock

import pytest
from src.reservations import ReservationStore


@pytest.fixture
def store(tmp_path):
    return ReservationStore(str(tmp_path / "res.json"))


def test_load_empty(store):
    assert store.get_all() == {}


def test_save_and_get(store):
    store.save("2026-06-01", "09:00", "17:00")
    assert store.get("2026-06-01") == {"start": "09:00", "end": "17:00"}
    assert store.get_all() == {"2026-06-01": {"start": "09:00", "end": "17:00"}}


def test_save_stamps_metadata(store):
    store.save("2026-06-01", "09:00", "17:00")
    raw = store.get_all_raw()["2026-06-01"]
    assert raw["deleted"] is False
    assert raw["gcal_event_id"] is None
    assert raw["modified_at"].endswith("Z") and "T" in raw["modified_at"]


def test_save_preserves_existing_event_id(store):
    store.save("2026-06-01", "09:00", "17:00")
    store.apply_reconciled({"2026-06-01": {
        "start": "09:00", "end": "17:00", "modified_at": "2026-05-20T10:00:00Z",
        "deleted": False, "gcal_event_id": "ev-1",
    }})
    store.save("2026-06-01", "08:00", "16:00")
    assert store.get_all_raw()["2026-06-01"]["gcal_event_id"] == "ev-1"


def test_delete_writes_tombstone_and_keeps_event_id(store):
    store.apply_reconciled({"2026-06-01": {
        "start": "09:00", "end": "17:00", "modified_at": "2026-05-20T10:00:00Z",
        "deleted": False, "gcal_event_id": "ev-1",
    }})
    store.delete("2026-06-01")
    assert store.get("2026-06-01") is None
    tomb = store.get_all_raw()["2026-06-01"]
    assert tomb["deleted"] is True
    assert tomb["gcal_event_id"] == "ev-1"


def test_delete_nonexistent_is_noop(store):
    store.delete("2026-01-01")
    assert store.get_all_raw() == {}


def test_get_excludes_tombstones(store):
    store.save("2026-06-01", "09:00", "17:00")
    store.delete("2026-06-01")
    assert "2026-06-01" not in store.get_all()
    assert "2026-06-01" in store.get_all_raw()


def test_persistence(tmp_path):
    path = str(tmp_path / "res.json")
    ReservationStore(path).save("2026-06-01", "09:00", "17:00")
    assert ReservationStore(path).get("2026-06-01") == {"start": "09:00", "end": "17:00"}


def test_apply_reconciled_replaces_data(store):
    store.save("2026-06-01", "09:00", "17:00")
    store.apply_reconciled({"2026-07-01": {
        "start": "10:00", "end": "18:00", "modified_at": "2026-05-20T10:00:00Z",
        "deleted": False, "gcal_event_id": "ev-9",
    }})
    assert "2026-06-01" not in store.get_all_raw()
    assert store.get("2026-07-01") == {"start": "10:00", "end": "18:00"}


def test_corrupt_json_is_quarantined_and_starts_empty(tmp_path):
    path = tmp_path / "res.json"
    path.write_text("{not valid", encoding="utf-8")
    store = ReservationStore(str(path))
    assert store.get_all() == {}
    assert len(list(tmp_path.glob("res.json.corrupt-*"))) == 1


def test_save_failure_keeps_original_intact(tmp_path):
    path = tmp_path / "res.json"
    store = ReservationStore(str(path))
    store.save("2026-06-01", "09:00", "17:00")
    original = path.read_bytes()
    with mock.patch("os.replace", side_effect=OSError("disk full")):
        with pytest.raises(OSError):
            store.save("2026-06-02", "09:00", "17:00")
    assert path.read_bytes() == original
    assert [p for p in tmp_path.iterdir() if p.suffix == ".tmp"] == []
```

- [ ] **Step 2: Tests laufen lassen — müssen fehlschlagen**

Run: `pytest tests/test_reservations.py -v`
Expected: FAIL mit `ModuleNotFoundError: No module named 'src.reservations'`

- [ ] **Step 3: `src/reservations.py` implementieren**

```python
# src/reservations.py
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
        """Ersetzt den kompletten Stand durch das Reconcile-Ergebnis."""
        self._data = dict(reconciled)
        self._save_to_disk()
```

- [ ] **Step 4: Tests laufen lassen — müssen bestehen**

Run: `pytest tests/test_reservations.py -v`
Expected: PASS (12 Tests)

- [ ] **Step 5: Commit**

```bash
git add src/reservations.py tests/test_reservations.py
git commit -m "feat(reservations): add ReservationStore for local reservation persistence"
```

---

## Task 3: `merge_reservations()` — pure LWW-Merge

**Files:**
- Create: `src/reservations_sync.py`
- Test: `tests/test_reservations_sync.py`

- [ ] **Step 1: Failing-Tests schreiben**

Neue Datei `tests/test_reservations_sync.py`:

```python
from src.reservations_sync import merge_reservations


def _local(start="09:00", end="17:00", modified_at="2026-05-20T10:00:00Z",
           deleted=False, event_id=None):
    return {"start": start, "end": end, "modified_at": modified_at,
            "deleted": deleted, "gcal_event_id": event_id}


def _remote(date="2026-06-01", start="09:00", end="17:00",
            modified_at="2026-05-20T10:00:00Z", event_id="ev1"):
    return {"date": date, "start": start, "end": end,
            "modified_at": modified_at, "event_id": event_id}


def test_local_only_new_creates_event():
    res = merge_reservations(
        {"2026-06-01": _local(modified_at="2026-05-20T10:00:00Z")},
        [], "2026-05-19T00:00:00Z")
    assert res["plan"]["create"] == [{
        "date": "2026-06-01", "start": "09:00", "end": "17:00",
        "modified_at": "2026-05-20T10:00:00Z"}]
    assert "2026-06-01" in res["merged"]


def test_local_only_stale_is_dropped():
    res = merge_reservations(
        {"2026-06-01": _local(modified_at="2026-05-10T10:00:00Z")},
        [], "2026-05-19T00:00:00Z")
    assert res["merged"] == {}
    assert res["plan"]["create"] == []


def test_remote_only_is_imported():
    res = merge_reservations({}, [_remote()], "2026-05-19T00:00:00Z")
    assert res["merged"]["2026-06-01"]["start"] == "09:00"
    assert res["merged"]["2026-06-01"]["gcal_event_id"] == "ev1"
    assert res["plan"] == {"create": [], "update": [], "delete": []}


def test_both_newer_local_wins_and_updates():
    res = merge_reservations(
        {"2026-06-01": _local(start="08:00", modified_at="2026-05-21T10:00:00Z")},
        [_remote(start="09:00", modified_at="2026-05-20T10:00:00Z")],
        "2026-05-19T00:00:00Z")
    assert res["merged"]["2026-06-01"]["start"] == "08:00"
    assert res["merged"]["2026-06-01"]["gcal_event_id"] == "ev1"
    assert res["plan"]["update"] == [{
        "date": "2026-06-01", "event_id": "ev1", "start": "08:00",
        "end": "17:00", "modified_at": "2026-05-21T10:00:00Z"}]


def test_both_newer_remote_wins():
    res = merge_reservations(
        {"2026-06-01": _local(start="08:00", modified_at="2026-05-20T10:00:00Z")},
        [_remote(start="09:00", modified_at="2026-05-21T10:00:00Z")],
        "2026-05-19T00:00:00Z")
    assert res["merged"]["2026-06-01"]["start"] == "09:00"
    assert res["plan"]["update"] == []


def test_both_equal_values_no_update():
    res = merge_reservations(
        {"2026-06-01": _local(modified_at="2026-05-21T10:00:00Z")},
        [_remote(modified_at="2026-05-20T10:00:00Z")],
        "2026-05-19T00:00:00Z")
    assert res["plan"]["update"] == []
    assert res["merged"]["2026-06-01"]["gcal_event_id"] == "ev1"


def test_tombstone_newer_deletes_event():
    res = merge_reservations(
        {"2026-06-01": _local(deleted=True, modified_at="2026-05-21T10:00:00Z",
                              event_id="ev1")},
        [_remote(modified_at="2026-05-20T10:00:00Z")],
        "2026-05-19T00:00:00Z")
    assert res["plan"]["delete"] == [{"event_id": "ev1"}]
    assert "2026-06-01" not in res["merged"]


def test_tombstone_older_than_remote_update_is_dropped():
    res = merge_reservations(
        {"2026-06-01": _local(deleted=True, modified_at="2026-05-20T10:00:00Z")},
        [_remote(modified_at="2026-05-21T10:00:00Z")],
        "2026-05-19T00:00:00Z")
    assert res["plan"]["delete"] == []
    assert res["merged"]["2026-06-01"]["start"] == "09:00"


def test_tombstone_without_remote_is_noop():
    res = merge_reservations(
        {"2026-06-01": _local(deleted=True, modified_at="2026-05-21T10:00:00Z")},
        [], "2026-05-19T00:00:00Z")
    assert res["merged"] == {}
    assert res["plan"] == {"create": [], "update": [], "delete": []}


def test_duplicate_remote_events_keeps_newest_deletes_rest():
    res = merge_reservations(
        {},
        [_remote(modified_at="2026-05-20T10:00:00Z", event_id="old"),
         _remote(modified_at="2026-05-21T10:00:00Z", event_id="new")],
        "2026-05-19T00:00:00Z")
    assert res["merged"]["2026-06-01"]["gcal_event_id"] == "new"
    assert res["plan"]["delete"] == [{"event_id": "old"}]
```

- [ ] **Step 2: Tests laufen lassen — müssen fehlschlagen**

Run: `pytest tests/test_reservations_sync.py -v`
Expected: FAIL mit `ModuleNotFoundError: No module named 'src.reservations_sync'`

- [ ] **Step 3: `src/reservations_sync.py` implementieren (nur `merge_reservations`)**

```python
# src/reservations_sync.py
"""Reservierungs-Abgleich mit dem Google Kalender.

`merge_reservations()` ist eine pure LWW-Merge-Funktion (kein I/O), die
`reconcile_reservations()` (weiter unten, Task 9) orchestriert pull → merge →
push. Der Merge spiegelt `sync.py::_merge_one` OHNE den Konflikt-Zweig: bei
beidseitiger Änderung gewinnt still der jüngere `modified_at`-Stand.
"""

import datetime


def _utc_now_iso():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _from_remote(remote):
    """Reservierungs-Record aus einem geparsten Kalender-Event."""
    return {
        "start": remote["start"],
        "end": remote["end"],
        "modified_at": remote["modified_at"],
        "deleted": False,
        "gcal_event_id": remote["event_id"],
    }


def _merge_one_date(date, local, remote, watermark, merged, plan):
    """Mergt einen einzelnen Tag. Mutiert `merged` und `plan` in-place.

    `local`  — Reservierungs-Record (echt oder Tombstone) oder None
    `remote` — geparstes Kalender-Event oder None
    `watermark` — last_calendar_sync_at
    """
    is_tombstone = local is not None and local.get("deleted")

    # Fall 1: nichts vorhanden.
    if local is None and remote is None:
        return

    # Fälle 2 & 3: lokaler Tombstone.
    if is_tombstone:
        if remote is None:
            return  # Tombstone fällt weg, nichts zu tun.
        if local["modified_at"] >= remote["modified_at"]:
            plan["delete"].append({"event_id": remote["event_id"]})
            return  # Löschung gewinnt, Tombstone fällt weg.
        merged[date] = _from_remote(remote)  # Remote-Update ist jünger.
        return

    # Fall 6: nur remote → übernehmen.
    if local is None:
        merged[date] = _from_remote(remote)
        return

    # Fall 5: nur lokal (echt).
    if remote is None:
        if local["modified_at"] > watermark:
            merged[date] = dict(local)  # lokale Neuanlage.
            plan["create"].append({
                "date": date, "start": local["start"], "end": local["end"],
                "modified_at": local["modified_at"],
            })
        # sonst: war beim letzten Sync da, remote jetzt weg → verwerfen.
        return

    # Fall 4: beide vorhanden (echt) → LWW.
    if remote["modified_at"] > local["modified_at"]:
        merged[date] = _from_remote(remote)
        return
    # Lokal gewinnt (inkl. Gleichstand — App ist autoritativ).
    record = dict(local)
    record["gcal_event_id"] = remote["event_id"]
    merged[date] = record
    if local["start"] != remote["start"] or local["end"] != remote["end"]:
        plan["update"].append({
            "date": date, "event_id": remote["event_id"],
            "start": local["start"], "end": local["end"],
            "modified_at": local["modified_at"],
        })


def merge_reservations(local_raw, remote_events, watermark):
    """Pure Merge zwischen lokalen Reservierungen und Kalender-Events.

    local_raw:     {date: {start, end, modified_at, deleted, gcal_event_id}}
    remote_events: Liste von {date, start, end, modified_at, event_id}
    watermark:     last_calendar_sync_at (ISO-String, "" beim Erststart)

    Liefert {"merged": {...}, "plan": {"create": [...], "update": [...],
    "delete": [...]}}.
    """
    plan = {"create": [], "update": [], "delete": []}

    # Remote-Events nach Datum gruppieren. Bei mehreren Events pro Tag (seltenes
    # Race) gewinnt das jüngste, die übrigen landen im delete-Plan — Selbstheilung.
    remote_by_date = {}
    for ev in remote_events:
        d = ev["date"]
        if d not in remote_by_date:
            remote_by_date[d] = ev
            continue
        keep, drop = remote_by_date[d], ev
        if ev["modified_at"] > keep["modified_at"]:
            keep, drop = ev, keep
        remote_by_date[d] = keep
        plan["delete"].append({"event_id": drop["event_id"]})

    merged = {}
    for date in set(local_raw.keys()) | set(remote_by_date.keys()):
        _merge_one_date(
            date, local_raw.get(date), remote_by_date.get(date),
            watermark, merged, plan,
        )
    return {"merged": merged, "plan": plan}
```

- [ ] **Step 4: Tests laufen lassen — müssen bestehen**

Run: `pytest tests/test_reservations_sync.py -v`
Expected: PASS (10 Tests)

- [ ] **Step 5: Commit**

```bash
git add src/reservations_sync.py tests/test_reservations_sync.py
git commit -m "feat(reservations): add pure merge_reservations LWW merge"
```

---

## Task 4: `gcal.py` — Scope-Konstanten + pure Event-Helper

**Files:**
- Create: `src/gcal.py`
- Test: `tests/test_gcal.py`

- [ ] **Step 1: Failing-Tests schreiben**

Neue Datei `tests/test_gcal.py`:

```python
from src import gcal


def test_event_payload_has_summary_and_marker():
    body = gcal.event_payload("2026-06-01", "09:00", "17:00", "2026-05-20T10:00:00Z")
    assert body["summary"] == gcal.EVENT_SUMMARY
    private = body["extendedProperties"]["private"]
    assert private[gcal.APP_MARKER_KEY] == gcal.APP_MARKER_VALUE
    assert private["modified_at"] == "2026-05-20T10:00:00Z"


def test_event_payload_datetime_encodes_date_and_time():
    body = gcal.event_payload("2026-06-01", "09:30", "17:45", "2026-05-20T10:00:00Z")
    # dateTime trägt das Datum und die HH:MM-Zeit (plus lokalem Offset).
    assert body["start"]["dateTime"].startswith("2026-06-01T09:30:00")
    assert body["end"]["dateTime"].startswith("2026-06-01T17:45:00")


def test_parse_event_roundtrips_payload():
    body = gcal.event_payload("2026-06-01", "09:00", "17:00", "2026-05-20T10:00:00Z")
    body["id"] = "ev-42"
    parsed = gcal.parse_event(body)
    assert parsed == {
        "date": "2026-06-01", "start": "09:00", "end": "17:00",
        "modified_at": "2026-05-20T10:00:00Z", "event_id": "ev-42",
    }


def test_parse_event_ignores_non_app_events():
    foreign = {"id": "x", "start": {"dateTime": "2026-06-01T09:00:00+02:00"},
               "end": {"dateTime": "2026-06-01T17:00:00+02:00"}}
    assert gcal.parse_event(foreign) is None


def test_parse_event_ignores_all_day_events():
    all_day = {
        "id": "x",
        "start": {"date": "2026-06-01"}, "end": {"date": "2026-06-02"},
        "extendedProperties": {"private": {gcal.APP_MARKER_KEY: gcal.APP_MARKER_VALUE}},
    }
    assert gcal.parse_event(all_day) is None
```

- [ ] **Step 2: Tests laufen lassen — müssen fehlschlagen**

Run: `pytest tests/test_gcal.py -v`
Expected: FAIL mit `ModuleNotFoundError: No module named 'src.gcal'`

- [ ] **Step 3: `src/gcal.py` mit Konstanten + pure Helpern anlegen**

```python
# src/gcal.py
"""Google-Calendar-API-Wrapper für die Reservierungs-Anbindung.

Google-Imports liegen LAZY in den I/O-Funktionen — die CI installiert kein
requirements.txt, `import src.gcal` muss aber funktionieren (analog mail.py).
Die pure Helper `event_payload` / `parse_event` haben keine Google-Abhängigkeit.
"""

import datetime

from src.mail import get_scopes

CALENDAR_EVENTS_SCOPE = "https://www.googleapis.com/auth/calendar.events"
CALENDAR_LIST_SCOPE = "https://www.googleapis.com/auth/calendar.calendarlist.readonly"

# Marker in extendedProperties.private — über diesen findet der Pull "seine"
# Events; manuell angelegte Termine bleiben dadurch unangetastet.
APP_MARKER_KEY = "zeiterfassung"
APP_MARKER_VALUE = "reservation"

EVENT_SUMMARY = "Arbeitszeit (reserviert)"
EVENT_DESCRIPTION = "Von der Zeiterfassung verwaltete Reservierung."


def event_payload(date_str, start, end, modified_at):
    """Baut den Calendar-API-Event-Body aus einer Reservierung.

    date_str ISO ('YYYY-MM-DD'), start/end 'HH:MM'. Die dateTime-Werte tragen
    den lokalen UTC-Offset (`astimezone()`) — kein IANA-Zeitzonenname nötig.
    """
    day = datetime.date.fromisoformat(date_str)
    sh, sm = (int(p) for p in start.split(":"))
    eh, em = (int(p) for p in end.split(":"))
    start_dt = datetime.datetime(day.year, day.month, day.day, sh, sm).astimezone()
    end_dt = datetime.datetime(day.year, day.month, day.day, eh, em).astimezone()
    return {
        "summary": EVENT_SUMMARY,
        "description": EVENT_DESCRIPTION,
        "start": {"dateTime": start_dt.isoformat()},
        "end": {"dateTime": end_dt.isoformat()},
        "extendedProperties": {
            "private": {
                APP_MARKER_KEY: APP_MARKER_VALUE,
                "modified_at": modified_at,
            },
        },
    }


def parse_event(event):
    """Wandelt ein Calendar-API-Event in die Reservierungs-Form um.

    Liefert {date, start, end, modified_at, event_id} oder None, wenn das Event
    nicht den App-Marker trägt oder kein dateTime-Event ist (Ganztags-Events
    haben nur `date`).
    """
    private = (event.get("extendedProperties") or {}).get("private") or {}
    if private.get(APP_MARKER_KEY) != APP_MARKER_VALUE:
        return None
    start_raw = (event.get("start") or {}).get("dateTime")
    end_raw = (event.get("end") or {}).get("dateTime")
    if not start_raw or not end_raw:
        return None
    start_dt = datetime.datetime.fromisoformat(start_raw)
    end_dt = datetime.datetime.fromisoformat(end_raw)
    return {
        "date": start_dt.date().isoformat(),
        "start": start_dt.strftime("%H:%M"),
        "end": end_dt.strftime("%H:%M"),
        "modified_at": private.get("modified_at", ""),
        "event_id": event.get("id", ""),
    }
```

- [ ] **Step 4: Tests laufen lassen — müssen bestehen**

Run: `pytest tests/test_gcal.py -v`
Expected: PASS (5 Tests)

- [ ] **Step 5: Commit**

```bash
git add src/gcal.py tests/test_gcal.py
git commit -m "feat(gcal): add Calendar event payload/parse helpers"
```

---

## Task 5: `mail.py` — `get_scopes(gcal_enabled)` + Gmail-Getter durchreichen

**Hintergrund:** `token.json` ist das gemeinsame Token für Gmail, Drive und (neu) Calendar. Würde ein Getter beim Refresh-Write nur eine Teilmenge der Scopes schreiben, schrumpfte der in `token.json` notierte Scope-Satz — der nächste `get_calendar_service`-Aufruf erkennt dann fälschlich „Scope fehlt" und erzwingt einen OAuth-Re-Consent (Browser öffnet sich). Deshalb fordert jeder Getter die *Vereinigung* aller aktiven Scopes an.

**Files:**
- Modify: `src/mail.py`
- Test: `tests/test_mail.py`

- [ ] **Step 1: Failing-Tests schreiben**

An `tests/test_mail.py` anhängen:

```python
def test_get_scopes_with_gcal_includes_calendar_scopes():
    from src.mail import get_scopes
    scopes = get_scopes(sync_enabled=False, gcal_enabled=True)
    assert "https://www.googleapis.com/auth/calendar.events" in scopes
    assert "https://www.googleapis.com/auth/calendar.calendarlist.readonly" in scopes


def test_get_scopes_without_gcal_has_no_calendar_scopes():
    from src.mail import get_scopes
    scopes = get_scopes(sync_enabled=True, gcal_enabled=False)
    assert not any("calendar" in s for s in scopes)
```

- [ ] **Step 2: Tests laufen lassen — müssen fehlschlagen**

Run: `pytest tests/test_mail.py -k get_scopes_with_gcal -v`
Expected: FAIL mit `TypeError: get_scopes() got an unexpected keyword argument 'gcal_enabled'`

- [ ] **Step 3: `src/mail.py` anpassen**

Konstanten oben bei `DRIVE_APPDATA_SCOPE` ergänzen:

```python
GMAIL_SEND_SCOPE = "https://www.googleapis.com/auth/gmail.send"
DRIVE_APPDATA_SCOPE = "https://www.googleapis.com/auth/drive.appdata"
USERINFO_EMAIL_SCOPE = "https://www.googleapis.com/auth/userinfo.email"
CALENDAR_EVENTS_SCOPE = "https://www.googleapis.com/auth/calendar.events"
CALENDAR_LIST_SCOPE = "https://www.googleapis.com/auth/calendar.calendarlist.readonly"
```

`get_scopes` ersetzen:

```python
def get_scopes(sync_enabled, gcal_enabled=False):
    """Liefert die OAuth-Scopes der App als Vereinigung aller aktiven Features.

    `userinfo.email` (Identity-Scope, non-sensitive) erlaubt die Anzeige
    des Absenders im Settings-Dialog. `openid` wurde absichtlich entfernt,
    weil Google den Scope mitunter normalisiert/strippt, was zu Scope-
    Mismatch-Warnings in google-auth führt.
    """
    scopes = [GMAIL_SEND_SCOPE, USERINFO_EMAIL_SCOPE]
    if sync_enabled:
        scopes.append(DRIVE_APPDATA_SCOPE)
    if gcal_enabled:
        scopes.append(CALENDAR_EVENTS_SCOPE)
        scopes.append(CALENDAR_LIST_SCOPE)
    return scopes
```

`fetch_user_email` — Signatur und den `get_scopes`-Aufruf erweitern:

```python
def fetch_user_email(token_path="token.json", sync_enabled=False, gcal_enabled=False):
```

Im Funktionskörper den Aufruf `get_scopes(sync_enabled)` (in der `Credentials.from_authorized_user_file`-Zeile) ersetzen durch:

```python
        creds = Credentials.from_authorized_user_file(
            token_path, get_scopes(sync_enabled, gcal_enabled)
        )
```

`refresh_token_if_needed` — Signatur und Aufruf:

```python
def refresh_token_if_needed(token_path="token.json", sync_enabled=False,
                            gcal_enabled=False):
```

und im Körper `scopes = get_scopes(sync_enabled)` ersetzen durch:

```python
    scopes = get_scopes(sync_enabled, gcal_enabled)
```

`get_gmail_service` — Signatur und Aufruf:

```python
def get_gmail_service(credentials_path="credentials.json", token_path="token.json",
                      sync_enabled=False, gcal_enabled=False):
```

und im Körper `scopes = get_scopes(sync_enabled)` ersetzen durch:

```python
    scopes = get_scopes(sync_enabled, gcal_enabled)
```

- [ ] **Step 4: Tests laufen lassen — müssen bestehen**

Run: `pytest tests/test_mail.py -v`
Expected: PASS (alle bestehenden + 2 neue)

- [ ] **Step 5: Commit**

```bash
git add src/mail.py tests/test_mail.py
git commit -m "feat(mail): thread gcal_enabled through get_scopes and OAuth getters"
```

---

## Task 6: `drive.py` — `get_drive_service(gcal_enabled)`

**Files:**
- Modify: `src/drive.py`
- Test: `tests/test_drive.py`

- [ ] **Step 1: Failing-Test schreiben**

An `tests/test_drive.py` anhängen:

```python
def test_get_drive_service_with_gcal_requests_calendar_scopes(tmp_path, monkeypatch):
    """Bei gcal_enabled fordert get_drive_service auch die Calendar-Scopes an,
    damit ein Drive-Re-Consent die Calendar-Scopes nicht aus token.json wirft."""
    import json
    from src import drive

    token_path = tmp_path / "token.json"
    token_path.write_text(json.dumps({
        "token": "t", "refresh_token": "r", "client_id": "c",
        "client_secret": "s", "scopes": ["x"],
    }), encoding="utf-8")

    captured = {}

    class _FakeCreds:
        valid = True
        expired = False
        refresh_token = None

        @classmethod
        def from_authorized_user_file(cls, path, scopes):
            captured["scopes"] = scopes
            return cls()

    monkeypatch.setattr(drive, "Credentials", _FakeCreds)
    monkeypatch.setattr(drive, "build", lambda *a, **k: object())

    drive.get_drive_service("credentials.json", str(token_path), gcal_enabled=True)
    assert "https://www.googleapis.com/auth/calendar.events" in captured["scopes"]
```

- [ ] **Step 2: Test laufen lassen — muss fehlschlagen**

Run: `pytest tests/test_drive.py -k with_gcal -v`
Expected: FAIL mit `TypeError: get_drive_service() got an unexpected keyword argument 'gcal_enabled'`

- [ ] **Step 3: `src/drive.py` anpassen**

`get_drive_service` Signatur ändern und die Scope-Liste dynamisch bilden. Die Funktion verwendet aktuell zweimal `SYNC_SCOPES` — beide Vorkommen durch die lokale Variable `scopes` ersetzen:

```python
def get_drive_service(credentials_path, token_path, gcal_enabled=False):
    """OAuth mit kombinierten Scopes (Gmail + Drive appdata, optional Calendar).
    Token wird mit allen Scopes geschrieben — Gmail send und Calendar
    funktionieren weiter mit demselben token.json. Wirft DriveAuthError oder
    DriveNetworkError bei Problemen."""
    if (Credentials is None or InstalledAppFlow is None
            or Request is None or build is None):
        raise ImportError(
            "Google-API-Libs fehlen — google-api-python-client und "
            "google-auth-oauthlib müssen installiert sein."
        )
    scopes = list(SYNC_SCOPES)
    if gcal_enabled:
        scopes.append("https://www.googleapis.com/auth/calendar.events")
        scopes.append("https://www.googleapis.com/auth/calendar.calendarlist.readonly")

    creds = None
    if os.path.exists(token_path):
        creds = Credentials.from_authorized_user_file(token_path, scopes)

    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
        except RefreshError as e:
            raise DriveAuthError(str(e)) from e
        except TransportError as e:
            raise DriveNetworkError(str(e)) from e
        _write_token(creds, token_path)

    if not creds or not creds.valid:
        if not os.path.exists(credentials_path):
            raise FileNotFoundError(
                f"credentials.json nicht gefunden unter:\n{credentials_path}"
            )
        flow = InstalledAppFlow.from_client_secrets_file(credentials_path, scopes)
        creds = flow.run_local_server(port=0)
        _write_token(creds, token_path)

    return build("drive", "v3", credentials=creds)
```

`SYNC_SCOPES` bleibt als Modul-Konstante unverändert (Basis-Satz; `test_drive.py` importiert sie).

- [ ] **Step 4: Tests laufen lassen — müssen bestehen**

Run: `pytest tests/test_drive.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/drive.py tests/test_drive.py
git commit -m "feat(drive): add gcal_enabled flag to get_drive_service scope set"
```

---

## Task 7: OAuth-Getter-Aufrufe auf `gcal_enabled` umstellen

Alle bestehenden Aufrufe der OAuth-Getter müssen `gcal_enabled=settings.get("gcal_enabled")` mitgeben, damit `token.json` stets den vollen Scope-Satz behält.

**Files:**
- Modify: `src/ui.py`
- Modify: `src/main.py`
- Modify: `src/dialogs/settings_dialog.py`
- Modify: `src/dialogs/send_dialog.py`
- Modify: `src/dialogs/share_dialog.py`

- [ ] **Step 1: `src/ui.py`**

In `_proactive_token_refresh` den `refresh_token_if_needed`-Aufruf ersetzen:

```python
                refresh_token_if_needed(
                    token_path,
                    sync_enabled=self.settings.get("sync_enabled"),
                    gcal_enabled=self.settings.get("gcal_enabled"),
                )
```

In `_proactive_sender_email_fetch` den `fetch_user_email`-Aufruf ersetzen:

```python
                email = fetch_user_email(
                    token_path,
                    sync_enabled=self.settings.get("sync_enabled"),
                    gcal_enabled=self.settings.get("gcal_enabled"),
                )
```

- [ ] **Step 2: `src/main.py`**

In `_run_pull_in_background` den `drive.get_drive_service`-Aufruf ersetzen:

```python
        service = drive.get_drive_service(
            os.path.join(base, "credentials.json"),
            os.path.join(base, "token.json"),
            gcal_enabled=settings.get("gcal_enabled"),
        )
```

In `_run_push_blocking` den `drive.get_drive_service`-Aufruf identisch ersetzen (gleiche drei Argumente).

- [ ] **Step 3: `src/dialogs/settings_dialog.py`**

In `_refresh_sender._do` die Aufrufe ersetzen:

```python
                get_gmail_service(
                    os.path.join(base_path, "credentials.json"),
                    os.path.join(base_path, "token.json"),
                    sync_enabled=settings.get("sync_enabled"),
                    gcal_enabled=settings.get("gcal_enabled"),
                )
                email = fetch_user_email(
                    os.path.join(base_path, "token.json"),
                    sync_enabled=settings.get("sync_enabled"),
                    gcal_enabled=settings.get("gcal_enabled"),
                )
```

In `_on_sync_toggled._do_oauth` den `drive.get_drive_service`-Aufruf ersetzen:

```python
                    drive.get_drive_service(
                        os.path.join(base_path, "credentials.json"),
                        os.path.join(base_path, "token.json"),
                        gcal_enabled=settings.get("gcal_enabled"),
                    )
```

- [ ] **Step 4: `src/dialogs/send_dialog.py`**

Den `get_gmail_service`-Aufruf in `do_send` ersetzen:

```python
            service = get_gmail_service(
                credentials_path, token_path,
                sync_enabled=settings.get("sync_enabled"),
                gcal_enabled=settings.get("gcal_enabled"),
            )
```

Den `fetch_user_email`-Aufruf (nach erfolgreichem Send) ersetzen:

```python
                email = fetch_user_email(
                    token_path,
                    sync_enabled=settings.get("sync_enabled"),
                    gcal_enabled=settings.get("gcal_enabled"),
                )
```

- [ ] **Step 5: `src/dialogs/share_dialog.py`**

Den `get_gmail_service`-Aufruf in `do_send` ersetzen:

```python
            service = get_gmail_service(
                credentials_path, token_path,
                sync_enabled=settings.get("sync_enabled"),
                gcal_enabled=settings.get("gcal_enabled"),
            )
```

- [ ] **Step 6: Volle Test-Suite laufen lassen**

Run: `pytest -q`
Expected: PASS (keine Regression — alle Aufrufe nutzen benannte Argumente)

- [ ] **Step 7: Commit**

```bash
git add src/ui.py src/main.py src/dialogs/settings_dialog.py src/dialogs/send_dialog.py src/dialogs/share_dialog.py
git commit -m "feat(oauth): pass gcal_enabled to all OAuth service getters"
```

---

## Task 8: `gcal.py` — Calendar-Service + Event-CRUD

**Files:**
- Modify: `src/gcal.py`
- Test: `tests/test_gcal.py`

- [ ] **Step 1: Failing-Tests schreiben (mit Fake-Service)**

An `tests/test_gcal.py` anhängen:

```python
class _FakeExec:
    def __init__(self, result):
        self._result = result

    def execute(self):
        return self._result


class _FakeEvents:
    def __init__(self, recorder, list_result):
        self._recorder = recorder
        self._list_result = list_result

    def list(self, **kwargs):
        self._recorder.append(("list", kwargs))
        return _FakeExec(self._list_result)

    def insert(self, **kwargs):
        self._recorder.append(("insert", kwargs))
        return _FakeExec({"id": "created-id"})

    def update(self, **kwargs):
        self._recorder.append(("update", kwargs))
        return _FakeExec({"id": kwargs.get("eventId")})

    def delete(self, **kwargs):
        self._recorder.append(("delete", kwargs))
        return _FakeExec({})


class _FakeService:
    def __init__(self, recorder, list_result=None):
        self._recorder = recorder
        self._events = _FakeEvents(recorder, list_result or {"items": []})

    def events(self):
        return self._events


def test_list_app_events_filters_and_parses():
    body = gcal.event_payload("2026-06-01", "09:00", "17:00", "2026-05-20T10:00:00Z")
    body["id"] = "ev-1"
    foreign = {"id": "ev-2", "start": {"dateTime": "2026-06-02T09:00:00+02:00"},
               "end": {"dateTime": "2026-06-02T17:00:00+02:00"}}
    recorder = []
    service = _FakeService(recorder, {"items": [body, foreign]})

    events = gcal.list_app_events(service, "cal-1")

    assert len(events) == 1
    assert events[0]["event_id"] == "ev-1"
    _, kwargs = recorder[0]
    assert kwargs["privateExtendedProperty"] == "zeiterfassung=reservation"
    assert kwargs["calendarId"] == "cal-1"


def test_create_event_returns_event_id():
    recorder = []
    service = _FakeService(recorder)
    event_id = gcal.create_event(
        service, "cal-1", "2026-06-01", "09:00", "17:00", "2026-05-20T10:00:00Z")
    assert event_id == "created-id"
    assert recorder[0][0] == "insert"


def test_delete_event_swallows_already_gone():
    class _GoneResp:
        status = 410

    class _GoneService:
        def events(self):
            class _E:
                def delete(self, **kwargs):
                    class _Boom:
                        def execute(self_):
                            err = Exception("gone")
                            err.resp = _GoneResp()
                            raise err
                    return _Boom()
            return _E()

    # Darf NICHT werfen.
    gcal.delete_event(_GoneService(), "cal-1", "ev-x")
```

- [ ] **Step 2: Tests laufen lassen — müssen fehlschlagen**

Run: `pytest tests/test_gcal.py -k "list_app_events or create_event or delete_event" -v`
Expected: FAIL mit `AttributeError: module 'src.gcal' has no attribute 'list_app_events'`

- [ ] **Step 3: `src/gcal.py` um Service + CRUD erweitern**

Folgende Funktionen am Ende von `src/gcal.py` anhängen:

```python
def get_calendar_service(credentials_path="credentials.json",
                         token_path="token.json", sync_enabled=False):
    """Authentifiziert gegen die Calendar API und liefert ein Service-Objekt.

    Fordert die VEREINIGUNG aller App-Scopes an (Gmail, Drive falls Sync,
    Calendar) — sonst verdrängte ein Calendar-Re-Consent die Gmail-/Drive-
    Scopes aus dem gemeinsamen token.json. Spiegelt get_gmail_service inkl.
    Scope-Upgrade-Erkennung. Google-Imports lazy (CI ohne requirements.txt).
    """
    import json as _json
    import os
    import stat

    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build

    scopes = get_scopes(sync_enabled, gcal_enabled=True)

    def _write(c):
        with open(token_path, "w") as f:
            f.write(c.to_json())
        try:
            os.chmod(token_path, stat.S_IRUSR | stat.S_IWUSR)  # 0o600
        except OSError:
            pass

    creds = None
    if os.path.exists(token_path):
        creds = Credentials.from_authorized_user_file(token_path, scopes)
        # Scope-Upgrade-Erkennung: hat der Token nicht alle Scopes, frischer Flow.
        try:
            with open(token_path, "r", encoding="utf-8") as f:
                granted = set(_json.load(f).get("scopes") or [])
            if not set(scopes).issubset(granted):
                creds = None
                try:
                    os.remove(token_path)
                except OSError:
                    pass
        except Exception:
            pass

    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            _write(creds)
        except Exception:
            creds = None

    if not creds or not creds.valid:
        if not os.path.exists(credentials_path):
            raise FileNotFoundError(
                f"credentials.json nicht gefunden unter:\n{credentials_path}"
            )
        flow = InstalledAppFlow.from_client_secrets_file(credentials_path, scopes)
        creds = flow.run_local_server(port=0)
        _write(creds)

    return build("calendar", "v3", credentials=creds)


def list_calendars(service):
    """Liefert [{"id", "summary"}] aller Kalender des Users — für das Dropdown."""
    result = service.calendarList().list().execute()
    return [
        {"id": c["id"], "summary": c.get("summary", c["id"])}
        for c in result.get("items", [])
    ]


def list_app_events(service, calendar_id):
    """Listet alle von der App angelegten Events des Kalenders.

    Serverseitiger Filter über das App-Marker-Property. Liefert eine Liste
    geparster Reservierungs-Dicts ({date, start, end, modified_at, event_id}).
    """
    events = []
    page_token = None
    while True:
        resp = service.events().list(
            calendarId=calendar_id,
            privateExtendedProperty=f"{APP_MARKER_KEY}={APP_MARKER_VALUE}",
            singleEvents=True,
            maxResults=2500,
            pageToken=page_token,
        ).execute()
        for ev in resp.get("items", []):
            parsed = parse_event(ev)
            if parsed is not None:
                events.append(parsed)
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    return events


def create_event(service, calendar_id, date_str, start, end, modified_at):
    """Legt ein Event an und liefert dessen event_id."""
    body = event_payload(date_str, start, end, modified_at)
    created = service.events().insert(calendarId=calendar_id, body=body).execute()
    return created["id"]


def update_event(service, calendar_id, event_id, date_str, start, end, modified_at):
    """Überschreibt ein bestehendes Event mit den Reservierungs-Werten."""
    body = event_payload(date_str, start, end, modified_at)
    service.events().update(
        calendarId=calendar_id, eventId=event_id, body=body,
    ).execute()


def delete_event(service, calendar_id, event_id):
    """Löscht ein Event. Ein bereits gelöschtes Event (404/410) ist kein Fehler."""
    try:
        service.events().delete(
            calendarId=calendar_id, eventId=event_id,
        ).execute()
    except Exception as e:
        status = getattr(getattr(e, "resp", None), "status", None)
        if status in (404, 410):
            return
        raise
```

- [ ] **Step 4: Tests laufen lassen — müssen bestehen**

Run: `pytest tests/test_gcal.py -v`
Expected: PASS (8 Tests)

- [ ] **Step 5: Commit**

```bash
git add src/gcal.py tests/test_gcal.py
git commit -m "feat(gcal): add calendar service and event CRUD wrappers"
```

---

## Task 9: `reconcile_reservations()` — Orchestrator

**Files:**
- Modify: `src/reservations_sync.py`
- Test: `tests/test_reservations_sync.py`

- [ ] **Step 1: Failing-Tests schreiben**

An `tests/test_reservations_sync.py` anhängen:

```python
def test_reconcile_creates_event_and_persists_event_id(tmp_path, monkeypatch):
    from src import gcal, reservations_sync
    from src.reservations import ReservationStore
    from src.settings import Settings

    store = ReservationStore(str(tmp_path / "res.json"))
    store.save("2026-06-01", "09:00", "17:00")
    settings = Settings(str(tmp_path / "set.json"))

    monkeypatch.setattr(gcal, "list_app_events", lambda s, c: [])
    monkeypatch.setattr(gcal, "update_event", lambda *a: None)
    monkeypatch.setattr(gcal, "delete_event", lambda *a: None)
    monkeypatch.setattr(
        gcal, "create_event",
        lambda s, c, date, start, end, modified_at: "new-event-id")

    reservations_sync.reconcile_reservations(object(), "cal-1", store, settings)

    assert store.get_all_raw()["2026-06-01"]["gcal_event_id"] == "new-event-id"
    assert settings.get("last_calendar_sync_at") != ""


def test_reconcile_deletes_orphaned_event(tmp_path, monkeypatch):
    from src import gcal, reservations_sync
    from src.reservations import ReservationStore
    from src.settings import Settings

    store = ReservationStore(str(tmp_path / "res.json"))
    settings = Settings(str(tmp_path / "set.json"))

    remote = {"date": "2026-06-01", "start": "09:00", "end": "17:00",
              "modified_at": "2026-05-20T10:00:00Z", "event_id": "ev-old"}
    deleted = []
    monkeypatch.setattr(gcal, "list_app_events", lambda s, c: [remote, dict(remote)])
    monkeypatch.setattr(gcal, "create_event", lambda *a: "x")
    monkeypatch.setattr(gcal, "update_event", lambda *a: None)
    monkeypatch.setattr(
        gcal, "delete_event",
        lambda s, c, event_id: deleted.append(event_id))

    reservations_sync.reconcile_reservations(object(), "cal-1", store, settings)

    assert deleted == ["ev-old"]  # eines der Duplikate wird gelöscht
    assert store.get("2026-06-01") == {"start": "09:00", "end": "17:00"}
```

- [ ] **Step 2: Tests laufen lassen — müssen fehlschlagen**

Run: `pytest tests/test_reservations_sync.py -k reconcile -v`
Expected: FAIL mit `AttributeError: module 'src.reservations_sync' has no attribute 'reconcile_reservations'`

- [ ] **Step 3: `reconcile_reservations` an `src/reservations_sync.py` anhängen**

```python
def reconcile_reservations(service, calendar_id, store, settings):
    """Voller Kalender-Abgleich: pull → merge → push.

    service:     gebauter Google-Calendar-Service (aus gcal.get_calendar_service)
    calendar_id: ID des Ziel-Kalenders
    store:       ReservationStore
    settings:    Settings (liest/schreibt last_calendar_sync_at)

    Mutiert store und settings. Wirft bei Netz-/API-Fehlern weiter — der Caller
    entscheidet, ob still geloggt oder als Messagebox gezeigt wird.
    """
    from src import gcal

    watermark = settings.get("last_calendar_sync_at") or ""
    remote_events = gcal.list_app_events(service, calendar_id)
    result = merge_reservations(store.get_all_raw(), remote_events, watermark)
    merged, plan = result["merged"], result["plan"]

    for item in plan["delete"]:
        gcal.delete_event(service, calendar_id, item["event_id"])

    for item in plan["update"]:
        gcal.update_event(
            service, calendar_id, item["event_id"],
            item["date"], item["start"], item["end"], item["modified_at"],
        )

    for item in plan["create"]:
        event_id = gcal.create_event(
            service, calendar_id,
            item["date"], item["start"], item["end"], item["modified_at"],
        )
        merged[item["date"]]["gcal_event_id"] = event_id

    store.apply_reconciled(merged)
    settings.set("last_calendar_sync_at", _utc_now_iso())
```

- [ ] **Step 4: Tests laufen lassen — müssen bestehen**

Run: `pytest tests/test_reservations_sync.py -v`
Expected: PASS (12 Tests)

- [ ] **Step 5: Commit**

```bash
git add src/reservations_sync.py tests/test_reservations_sync.py
git commit -m "feat(reservations): add reconcile_reservations orchestrator"
```

---

## Task 10: `main.py` — `run_calendar_reconcile()`-Helper

Ein blockierender Helper, der den Service baut und den Reconcile fährt — analog `_run_push_blocking`. Wird von `ui.py` in einem Thread aufgerufen.

**Files:**
- Modify: `src/main.py`

- [ ] **Step 1: Helper an `src/main.py` anhängen** (nach `_run_push_blocking`, vor `def main()`)

```python
def run_calendar_reconcile(reservation_store, settings, base):
    """Baut den Calendar-Service und fährt einen Reservierungs-Reconcile.

    Liefert {"ok": bool, "error": str, "tb": str}. Wirft NICHT — der Caller
    (UI-Thread) wertet das Dict aus. No-op, wenn gcal deaktiviert oder kein
    Kalender gewählt ist.
    """
    from src import gcal
    from src.reservations_sync import reconcile_reservations

    if not settings.get("gcal_enabled"):
        return {"ok": True, "error": "", "tb": ""}
    calendar_id = settings.get("gcal_calendar_id")
    if not calendar_id:
        return {"ok": True, "error": "", "tb": ""}

    try:
        service = gcal.get_calendar_service(
            os.path.join(base, "credentials.json"),
            os.path.join(base, "token.json"),
            sync_enabled=settings.get("sync_enabled"),
        )
        reconcile_reservations(service, calendar_id, reservation_store, settings)
        return {"ok": True, "error": "", "tb": ""}
    except Exception as e:
        logging.getLogger(__name__).exception("Kalender-Reconcile fehlgeschlagen")
        return {"ok": False, "error": f"{type(e).__name__}: {e}",
                "tb": traceback.format_exc()}
```

- [ ] **Step 2: Sanity-Check — Modul importierbar**

Run: `python -c "import src.main"`
Expected: kein Fehler

- [ ] **Step 3: Volle Test-Suite**

Run: `pytest -q`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add src/main.py
git commit -m "feat(main): add run_calendar_reconcile helper"
```

---

## Task 11: `theme.py` — Reservierungs-Farbkonstanten

**Files:**
- Modify: `src/theme.py`

- [ ] **Step 1: Konstanten ergänzen**

In `src/theme.py` direkt nach dem Holiday-Block (`HOLIDAY_ACCENT = ...`) einfügen:

```python
# Reservation cell colors ("geplant"-Look — violetter Akzent, abgesetzt von
# der roten Ist-Zeit-Zelle und der grünen Feiertagszelle)
RESERVATION_BG = "#2a2150"
RESERVATION_BG_HOVER = "#352a66"
RESERVATION_ACCENT = "#a78bfa"
```

- [ ] **Step 2: Sanity-Check**

Run: `python -c "from src.theme import RESERVATION_BG, RESERVATION_BG_HOVER, RESERVATION_ACCENT"`
Expected: kein Fehler

- [ ] **Step 3: Commit**

```bash
git add src/theme.py
git commit -m "feat(theme): add reservation cell color constants"
```

---

## Task 12: `entry_dialog.py` — Reservierungs-Block

Der Tages-Dialog bekommt unter dem Ist-Zeit-Block einen zweiten Block „Reservierung". Er wird nur gebaut, wenn `date >= heute` ODER für den Tag bereits eine Reservierung existiert.

**Files:**
- Modify: `src/dialogs/entry_dialog.py` (vollständiger Ersatz)

- [ ] **Step 1: `src/dialogs/entry_dialog.py` vollständig ersetzen**

```python
import datetime
import tkinter as tk
from tkinter import messagebox

from src.holidays_de import get_holidays
from src.settings import WEEKDAY_KEYS
from src.theme import (
    BG, FONT, FONT_BOLD, PAUSE_VALUES, TEXT, TEXT_MUTED, TIME_VALUES,
    apply_combobox_style, apply_dark_titlebar, center_dialog_on_parent,
    dark_combo, primary_button, secondary_button, themed_askyesno,
)
from src.time_utils import validate_entry


def open_entry_dialog(parent, date_str, storage, settings, on_change,
                      reservation_store=None, trigger_reconcile=None):
    """Modaler Dialog zum Bearbeiten von Ist-Zeit und Reservierung eines Tages.

    on_change wird nach erfolgreichem Speichern/Löschen aufgerufen, damit der
    Aufrufer den Kalender neu rendert.
    reservation_store / trigger_reconcile sind optional; sind sie gesetzt und
    ist der Tag heute/zukünftig (oder existiert bereits eine Reservierung),
    wird der Reservierungs-Block angezeigt. trigger_reconcile() stößt nach
    einer Reservierungsänderung den Kalender-Abgleich an.
    """
    entry = storage.get(date_str)
    day = datetime.date.fromisoformat(date_str)

    # Feiertags-Warnung beim Anlegen einer Ist-Zeit (nicht beim Edit).
    if entry is None:
        state = settings.get("state")
        if state:
            feiertage = get_holidays(state, day.year)
            if day in feiertage:
                date_de = day.strftime("%d.%m.%Y")
                confirm = themed_askyesno(
                    parent, "Feiertag",
                    f"Der {date_de} ist {feiertage[day]} (Feiertag).\n\n"
                    "Trotzdem Eintrag anlegen?",
                )
                if not confirm:
                    return

    existing_reservation = (
        reservation_store.get(date_str) if reservation_store is not None else None
    )
    show_reservation = reservation_store is not None and (
        day >= datetime.date.today() or existing_reservation is not None
    )

    dialog = tk.Toplevel(parent)
    dialog.title(date_str)
    dialog.resizable(False, False)
    dialog.grab_set()
    dialog.configure(bg=BG)
    apply_dark_titlebar(dialog)
    apply_combobox_style(dialog)

    # --- Ist-Zeit ---
    tk.Label(dialog, text="Start:", font=FONT, bg=BG, fg=TEXT).grid(
        row=0, column=0, padx=10, pady=8, sticky="w")
    weekday_key = WEEKDAY_KEYS[day.weekday()]
    start_var = tk.StringVar(
        value=entry["start"] if entry else settings.get(f"default_start_{weekday_key}")
    )
    dark_combo(dialog, start_var, TIME_VALUES).grid(row=0, column=1, padx=10, pady=8)

    tk.Label(dialog, text="Ende:", font=FONT, bg=BG, fg=TEXT).grid(
        row=1, column=0, padx=10, pady=8, sticky="w")
    end_var = tk.StringVar(
        value=entry["end"] if entry else settings.get(f"default_end_{weekday_key}")
    )
    dark_combo(dialog, end_var, TIME_VALUES).grid(row=1, column=1, padx=10, pady=8)

    tk.Label(dialog, text="Pause (Min):", font=FONT, bg=BG, fg=TEXT).grid(
        row=2, column=0, padx=10, pady=8, sticky="w")
    default_pause = settings.get("default_pause")
    if entry and "pause" in entry:
        current_pause = str(entry["pause"])
    else:
        current_pause = str(default_pause) if not entry else "0"
    pause_var = tk.StringVar(value=current_pause)
    dark_combo(dialog, pause_var, PAUSE_VALUES).grid(row=2, column=1, padx=10, pady=8)

    def save():
        ok, msg = validate_entry(start_var.get(), end_var.get(),
                                 pause_minutes=int(pause_var.get()))
        if not ok:
            messagebox.showerror("Fehler", msg, parent=dialog)
            return
        storage.save(date_str, start_var.get(), end_var.get(),
                     pause=int(pause_var.get()))
        dialog.destroy()
        on_change()

    def delete():
        storage.delete(date_str)
        dialog.destroy()
        on_change()

    btn_frame = tk.Frame(dialog, bg=BG)
    btn_frame.grid(row=3, column=0, columnspan=2, pady=12)
    primary_button(btn_frame, "Speichern", save).pack(side=tk.LEFT, padx=5)
    if entry is not None:
        secondary_button(btn_frame, "Löschen", delete).pack(side=tk.LEFT, padx=5)

    # --- Reservierung ---
    if show_reservation:
        tk.Label(
            dialog, text="— Reservierung —", font=FONT_BOLD, bg=BG, fg=TEXT_MUTED,
        ).grid(row=4, column=0, columnspan=2, padx=10, pady=(8, 4))

        tk.Label(dialog, text="Start:", font=FONT, bg=BG, fg=TEXT).grid(
            row=5, column=0, padx=10, pady=8, sticky="w")
        res_start_var = tk.StringVar(
            value=existing_reservation["start"] if existing_reservation
            else settings.get(f"default_start_{weekday_key}")
        )
        dark_combo(dialog, res_start_var, TIME_VALUES).grid(
            row=5, column=1, padx=10, pady=8)

        tk.Label(dialog, text="Ende:", font=FONT, bg=BG, fg=TEXT).grid(
            row=6, column=0, padx=10, pady=8, sticky="w")
        res_end_var = tk.StringVar(
            value=existing_reservation["end"] if existing_reservation
            else settings.get(f"default_end_{weekday_key}")
        )
        dark_combo(dialog, res_end_var, TIME_VALUES).grid(
            row=6, column=1, padx=10, pady=8)

        def save_reservation():
            ok, msg = validate_entry(res_start_var.get(), res_end_var.get(),
                                     pause_minutes=0)
            if not ok:
                messagebox.showerror("Fehler", msg, parent=dialog)
                return
            reservation_store.save(date_str, res_start_var.get(), res_end_var.get())
            dialog.destroy()
            on_change()
            if trigger_reconcile is not None:
                trigger_reconcile()

        def delete_reservation():
            reservation_store.delete(date_str)
            dialog.destroy()
            on_change()
            if trigger_reconcile is not None:
                trigger_reconcile()

        res_btn_frame = tk.Frame(dialog, bg=BG)
        res_btn_frame.grid(row=7, column=0, columnspan=2, pady=12)
        primary_button(res_btn_frame, "Reservierung speichern",
                       save_reservation).pack(side=tk.LEFT, padx=5)
        if existing_reservation is not None:
            secondary_button(res_btn_frame, "Reservierung löschen",
                             delete_reservation).pack(side=tk.LEFT, padx=5)

    center_dialog_on_parent(dialog, parent)
```

- [ ] **Step 2: Sanity-Check — Dialog importierbar, App startet**

Run: `python -c "import src.dialogs.entry_dialog"`
Expected: kein Fehler

Run: `python -m src.main` — App startet, einen Tag anklicken, der Dialog öffnet (Reservierungs-Block bei heutigen/zukünftigen Tagen sichtbar, da `reservation_store` von `ui.py` erst in Task 14 durchgereicht wird, ist der Block zunächst noch ausgeblendet — das ist erwartet). Fenster schließen.

- [ ] **Step 3: Commit**

```bash
git add src/dialogs/entry_dialog.py
git commit -m "feat(entry-dialog): add reservation section to the day dialog"
```

---

## Task 13: `settings_dialog.py` — Bereich „Google Kalender"

**Files:**
- Modify: `src/dialogs/settings_dialog.py`

- [ ] **Step 1: Import ergänzen**

In `src/dialogs/settings_dialog.py` den `theme`-Import um nichts erweitern, aber den `src.settings`-Import prüfen — `SYNCED_SETTING_KEYS` ist bereits importiert. Keine Änderung am Importblock nötig.

- [ ] **Step 2: Google-Kalender-Bereich vor dem `btn_frame` einfügen**

Die Settings-Dialog-Zeilennummern sind hartkodiert. Der neue Bereich belegt Zeilen 27–30, der bestehende `btn_frame` rückt von Zeile 27 auf 31.

Den Block ab `def save_settings():` ist betroffen — füge VOR `def save_settings():` den folgenden Abschnitt ein:

```python
    # --- Google Kalender (Reservierungen) ---
    tk.Label(
        dialog, text="— Google Kalender —", font=FONT_BOLD,
        bg=BG, fg=TEXT_MUTED,
    ).grid(row=27, column=0, columnspan=2, padx=10, pady=(16, 4))

    var_gcal = tk.BooleanVar(value=settings.get("gcal_enabled"))
    cb_gcal: tk.Checkbutton | None = None

    # Kalender-Auswahl: Combobox zeigt Klarnamen, gespeichert wird die ID.
    # cal_map summary->id wird im Hintergrund per API befüllt.
    cal_map: dict[str, str] = {}
    cal_var = tk.StringVar(value=settings.get("gcal_calendar_id") or "primary")

    cal_combo = dark_combo(dialog, cal_var, [cal_var.get()], width=30)
    cal_combo.grid(row=29, column=1, padx=10, pady=4, sticky="w")
    tk.Label(dialog, text="Kalender:", font=FONT, bg=BG, fg=TEXT).grid(
        row=29, column=0, padx=10, pady=4, sticky="w")

    cal_status = tk.Label(dialog, text="", font=FONT_SMALL, bg=BG, fg=TEXT_MUTED)
    cal_status.grid(row=30, column=0, columnspan=2, padx=10, pady=(0, 4), sticky="w")

    def _populate_calendars(items):
        if not cal_combo.winfo_exists():
            return
        cal_map.clear()
        for it in items:
            cal_map[it["summary"]] = it["id"]
        cal_combo["values"] = list(cal_map.keys()) or [cal_var.get()]
        # Gespeicherte ID auf den passenden Klarnamen zurückmappen.
        stored_id = settings.get("gcal_calendar_id") or "primary"
        for summary, cid in cal_map.items():
            if cid == stored_id:
                cal_var.set(summary)
                break
        cal_status.config(text="")

    def _load_calendars():
        cal_status.config(text="Kalenderliste wird geladen…")

        def _do():
            try:
                from src import gcal
                service = gcal.get_calendar_service(
                    os.path.join(base_path, "credentials.json"),
                    os.path.join(base_path, "token.json"),
                    sync_enabled=settings.get("sync_enabled"),
                )
                items = gcal.list_calendars(service)
            except Exception as e:
                tb = traceback.format_exc()
                dialog.after(0, lambda: _load_calendars_error(e, tb))
                return
            dialog.after(0, lambda: _populate_calendars(items))

        threading.Thread(target=_do, daemon=True).start()

    def _load_calendars_error(err, tb):
        if cal_status.winfo_exists():
            cal_status.config(text="Kalenderliste nicht verfügbar")
        messagebox.showerror(
            "Google Kalender",
            f"Kalenderliste konnte nicht geladen werden:\n\n{err}\n\n{tb}",
            parent=dialog,
        )

    def _finish_gcal_oauth(err, tb):
        assert cb_gcal is not None
        cb_gcal.config(state="normal")
        if err is None:
            settings.set("gcal_enabled", True)
            _load_calendars()
            return
        messagebox.showerror(
            "Google Kalender aktivieren",
            f"OAuth-Flow fehlgeschlagen:\n\n{err}\n\n{tb}",
            parent=dialog,
        )
        var_gcal.set(False)

    def _on_gcal_toggled():
        assert cb_gcal is not None
        new_state = var_gcal.get()
        if new_state and not settings.get("gcal_enabled"):
            cb_gcal.config(state="disabled")

            def _do_oauth():
                err, tb = None, ""
                try:
                    from src import gcal
                    gcal.get_calendar_service(
                        os.path.join(base_path, "credentials.json"),
                        os.path.join(base_path, "token.json"),
                        sync_enabled=settings.get("sync_enabled"),
                    )
                except Exception as e:
                    err, tb = e, traceback.format_exc()
                dialog.after(0, lambda: _finish_gcal_oauth(err, tb))

            threading.Thread(target=_do_oauth, daemon=True).start()
            return
        if not new_state and settings.get("gcal_enabled"):
            settings.set("gcal_enabled", False)

    cb_gcal = tk.Checkbutton(
        dialog, text="Reservierungen mit Google Kalender abgleichen",
        variable=var_gcal, font=FONT,
        bg=BG, fg=TEXT, selectcolor=CELL_BG,
        activebackground=BG, activeforeground=TEXT,
        cursor="hand2", command=_on_gcal_toggled,
    )
    cb_gcal.grid(row=28, column=0, columnspan=2, padx=10, pady=(4, 0), sticky="w")

    if settings.get("gcal_enabled"):
        _load_calendars()
```

- [ ] **Step 3: `btn_frame`-Zeile anpassen**

Im `btn_frame`-Block (am Dateiende) `row=27` auf `row=31` ändern:

```python
    btn_frame = tk.Frame(dialog, bg=BG)
    btn_frame.grid(row=31, column=0, columnspan=2, pady=12)
```

- [ ] **Step 4: `gcal_calendar_id` beim Speichern persistieren**

In `save_settings()` nach der `synced_updates`/`plain_updates`-Aufteilung, vor `on_change()`, ergänzen:

```python
        # Kalender-Auswahl: Klarname zurück auf ID mappen, als Sync-Setting
        # speichern (reist über die Drive-Settings-Sync mit).
        if settings.get("gcal_enabled"):
            selected_cal_id = cal_map.get(
                cal_var.get(), settings.get("gcal_calendar_id") or "primary")
            if selected_cal_id != settings.get("gcal_calendar_id"):
                settings.set_synced("gcal_calendar_id", selected_cal_id)
```

- [ ] **Step 5: Sanity-Check**

Run: `python -c "import src.dialogs.settings_dialog"`
Expected: kein Fehler

Run: `python -m src.main` — App starten, Zahnrad öffnen → Bereich „Google Kalender" mit Checkbox + Dropdown sichtbar. Schließen.

- [ ] **Step 6: Volle Test-Suite**

Run: `pytest -q`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add src/dialogs/settings_dialog.py
git commit -m "feat(settings-ui): add Google Calendar section with calendar picker"
```

---

## Task 14: `ui.py` — Grid-Darstellung + Reconcile-Trigger

**Files:**
- Modify: `src/ui.py`

- [ ] **Step 1: Import ergänzen**

Im `theme`-Import von `src/ui.py` die Reservierungs-Konstanten hinzufügen — ergänze in der `from src.theme import (...)`-Liste:

```python
    RESERVATION_BG, RESERVATION_BG_HOVER, RESERVATION_ACCENT,
```

- [ ] **Step 2: `App.__init__` — `reservation_store`-Parameter**

Die Signatur ändern:

```python
    def __init__(self, root, storage, settings, base_path=".", conflicts_store=None,
                 reservation_store=None):
```

Direkt nach `self.conflicts_store = conflicts_store` einfügen:

```python
        self.reservation_store = reservation_store
```

Am Ende von `__init__`, nach `self._proactive_update_check()`, einfügen:

```python
        self._proactive_calendar_reconcile()
```

- [ ] **Step 3: Reconcile-Methoden ergänzen** (nach `_proactive_update_check`)

```python
    def _proactive_calendar_reconcile(self):
        """Gleicht beim App-Start die Reservierungen mit dem Google Kalender ab.

        Läuft im Hintergrund. Fehler werden STILL geloggt (ein Offline-Start
        darf nicht nerven — analog Token-Refresh/Update-Check).
        """
        if self.reservation_store is None:
            return
        if not self.settings.get("gcal_enabled"):
            return

        def worker():
            from src.main import run_calendar_reconcile
            result = run_calendar_reconcile(
                self.reservation_store, self.settings, self.base_path)
            if result.get("ok"):
                self.root.after(0, self._refresh)

        threading.Thread(target=worker, daemon=True).start()

    def _trigger_calendar_reconcile(self):
        """Stößt nach einer Reservierungsänderung den Kalender-Abgleich an.

        Fehler werden hier ALS MESSAGEBOX gezeigt — der User hat aktiv
        gespeichert und erwartet Feedback (CLAUDE.md: Sendepfad-Fehler sichtbar).
        """
        if self.reservation_store is None or not self.settings.get("gcal_enabled"):
            return

        def worker():
            from src.main import run_calendar_reconcile
            result = run_calendar_reconcile(
                self.reservation_store, self.settings, self.base_path)
            self.root.after(0, lambda: self._on_reconcile_done(result))

        threading.Thread(target=worker, daemon=True).start()

    def _on_reconcile_done(self, result):
        if not result.get("ok"):
            messagebox.showerror(
                "Google-Kalender-Abgleich fehlgeschlagen",
                f"Die Reservierung wurde lokal gespeichert, der Kalender-Abgleich "
                f"ist aber fehlgeschlagen:\n\n{result.get('error', '?')}\n\n"
                f"{result.get('tb', '')}\n\n"
                "Der Abgleich wird beim nächsten Start erneut versucht.",
            )
        self._refresh()
```

- [ ] **Step 4: `_open_dialog` — Reservierungs-Argumente durchreichen**

`_open_dialog` ersetzen:

```python
    def _open_dialog(self, date_str):
        open_entry_dialog(
            self.root, date_str, self.storage, self.settings,
            on_change=self._refresh,
            reservation_store=self.reservation_store,
            trigger_reconcile=self._trigger_calendar_reconcile,
        )
```

- [ ] **Step 5: `_build_day_cell` — Reservierung berücksichtigen**

`_build_day_cell` ersetzen:

```python
    def _build_day_cell(self, parent, date_str, day_text, day_date, is_weekend,
                        entry, holidays_map, pad,
                        holiday_max_len, cell_size, conflict_dates=None,
                        entry_time_font=FONT_TINY, holiday_name_font=FONT_SMALL,
                        reservation=None):
        """Dispatcht auf Entry-, Reservierungs-, Holiday- oder Empty-Zelle.

        reservation: optionales {start, end} für den Tag. Hat der Tag eine
        Ist-Zeit UND eine Reservierung, wird die Ist-Zeitzelle gebaut und mit
        einem Eck-Marker versehen; nur-Reservierungs-Tage bekommen eine eigene
        violette Zelle.
        """
        if entry:
            cell = self._build_entry_cell(
                parent, date_str, day_text, entry, is_weekend, pad,
                cell_size=cell_size, time_font=entry_time_font,
            )
            if reservation is not None:
                self._add_reservation_marker(cell)
                attach_tooltip(
                    cell,
                    f"Reservierung: {reservation['start']}-{reservation['end']}")
            elif day_date in holidays_map:
                attach_tooltip(cell, f"Feiertag: {holidays_map[day_date]}")
        elif reservation is not None:
            cell = self._build_reservation_cell(
                parent, date_str, day_text, reservation, pad,
                cell_size=cell_size, time_font=entry_time_font,
            )
            if day_date in holidays_map:
                attach_tooltip(cell, f"Feiertag: {holidays_map[day_date]}")
        elif day_date in holidays_map:
            cell = self._build_holiday_cell(
                parent, day_text=day_text,
                name=holidays_map[day_date], max_name_len=holiday_max_len,
                on_click=lambda d=date_str: self._open_dialog(d),
                cell_size=cell_size,
                name_font=holiday_name_font,
            )
        else:
            cell = self._build_empty_cell(
                parent, date_str, day_text, is_weekend, cell_size,
            )

        if conflict_dates and date_str in conflict_dates:
            cell.configure(highlightbackground="orange", highlightthickness=2)
            attach_tooltip(cell, "Konflikt — bitte auflösen")

        return cell
```

- [ ] **Step 6: `_build_reservation_cell` + `_add_reservation_marker` ergänzen** (nach `_build_entry_cell`)

```python
    def _build_reservation_cell(self, parent, date_str, day_text, reservation,
                                pad, cell_size=None, time_font=FONT_TINY):
        """Violette „geplant"-Zelle für einen Tag mit nur einer Reservierung.
        Layout analog zu _build_entry_cell."""
        bg = RESERVATION_BG
        hover_bg = RESERVATION_BG_HOVER
        cell = tk.Frame(
            parent, bg=bg, relief=tk.SOLID,
            highlightbackground=RESERVATION_ACCENT, highlightthickness=1,
            cursor="hand2",
        )
        if cell_size is not None:
            cell.config(width=cell_size[0], height=cell_size[1])
            cell.pack_propagate(False)
        day_lbl = tk.Label(cell, text=day_text, font=FONT, bg=bg, fg=TEXT,
                           cursor="hand2")
        day_lbl.pack(pady=(pad, 0))
        time_lbl = tk.Label(
            cell, text=f"{reservation['start']}-{reservation['end']}",
            font=time_font, bg=bg, fg=TEXT_MUTED, cursor="hand2",
        )
        time_lbl.pack(pady=(0, pad))
        for w in (cell, day_lbl, time_lbl):
            w.bind("<Button-1>", lambda e, d=date_str: self._open_dialog(d))
            w.bind("<Enter>", lambda e, c=cell, dl=day_lbl, tl=time_lbl, hb=hover_bg:
                   self._cell_hover(c, dl, tl, hb))
            w.bind("<Leave>", lambda e, c=cell, dl=day_lbl, tl=time_lbl, ob=bg:
                   self._cell_hover(c, dl, tl, ob))
        return cell

    def _add_reservation_marker(self, cell):
        """Kleiner Eck-Marker auf einer Ist-Zeitzelle, die zusätzlich eine
        Reservierung hat. place() überlagert die gepackten Kind-Widgets."""
        marker = tk.Label(
            cell, text="•", font=FONT_BOLD,
            bg=cell.cget("bg"), fg=RESERVATION_ACCENT,
        )
        marker.place(relx=1.0, x=-3, y=-1, anchor="ne")
```

- [ ] **Step 7: `_refresh_month` — Reservierungen laden und durchreichen**

In `_refresh_month`, nach `entries = self.storage.get_all()` einfügen:

```python
        reservations = (
            self.reservation_store.get_all() if self.reservation_store else {})
```

Im `_build_day_cell`-Aufruf innerhalb der Schleife das Argument `reservation=` ergänzen:

```python
                cell = self._build_day_cell(
                    new_frame, date_str, str(day), day_date,
                    is_weekend=col >= 5, entry=entry, holidays_map=holidays_map,
                    pad=4,
                    holiday_max_len=12 if wide_cells else 9,
                    cell_size=cell_size,
                    conflict_dates=conflict_dates,
                    entry_time_font=entry_time_font,
                    holiday_name_font=holiday_name_font,
                    reservation=reservations.get(date_str),
                )
```

- [ ] **Step 8: `_refresh_week` — Reservierungen laden und durchreichen**

In `_refresh_week`, nach `entries = self.storage.get_all()` einfügen:

```python
        reservations = (
            self.reservation_store.get_all() if self.reservation_store else {})
```

Im `_build_day_cell`-Aufruf innerhalb der Schleife das Argument `reservation=` ergänzen:

```python
            cell = self._build_day_cell(
                new_frame, date_str, day_text, day_date,
                is_weekend=col >= 5, entry=entry, holidays_map=holidays_map,
                pad=8,
                holiday_max_len=14 if wide_cells else 12,
                cell_size=cell_size,
                conflict_dates=conflict_dates,
                entry_time_font=entry_time_font,
                holiday_name_font=holiday_name_font,
                reservation=reservations.get(date_str),
            )
```

- [ ] **Step 9: Sanity-Check**

Run: `python -c "import src.ui"`
Expected: kein Fehler

- [ ] **Step 10: Volle Test-Suite**

Run: `pytest -q`
Expected: PASS

- [ ] **Step 11: Commit**

```bash
git add src/ui.py
git commit -m "feat(ui): render reservations in calendar grid, wire reconcile triggers"
```

---

## Task 15: `main.py` — `ReservationStore` instanzieren und an `App` übergeben

**Files:**
- Modify: `src/main.py`

- [ ] **Step 1: Import ergänzen**

In `src/main.py` bei den `src`-Imports einfügen:

```python
from src.reservations import ReservationStore
```

- [ ] **Step 2: Store anlegen und durchreichen**

In `main()`, nach `conflicts_store = ConflictsStore(...)`, einfügen:

```python
    reservation_store = ReservationStore(os.path.join(base, "reservations.json"))
```

Den `App(...)`-Aufruf ersetzen:

```python
    app = App(root, storage, settings, base_path=base, conflicts_store=conflicts_store,
              reservation_store=reservation_store)
```

- [ ] **Step 3: Sanity-Check**

Run: `python -c "import src.main"`
Expected: kein Fehler

Run: `python -m src.main` — App startet; einen heutigen/zukünftigen Tag anklicken → der „Reservierung"-Block ist jetzt sichtbar. Eine Reservierung speichern (ohne aktivierten Google Kalender) → die Zelle wird violett dargestellt. Fenster schließen.

- [ ] **Step 4: Volle Test-Suite**

Run: `pytest -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/main.py
git commit -m "feat(main): instantiate ReservationStore and pass it to App"
```

---

## Task 16: Abschluss — CHANGELOG, Version, manuelle Verifikation

**Files:**
- Modify: `CHANGELOG.md`
- Modify: `src/version.py`

- [ ] **Step 1: Dependencies bestätigen (keine Änderung erwartet)**

`requirements.txt` listet bereits `google-auth-oauthlib>=1.0.0` und
`google-api-python-client>=2.0.0` — die Calendar API nutzt dieselbe
`googleapiclient`-Lib wie Gmail/Drive. **Keine neue Dependency**, `requirements.txt`
bleibt unverändert.

- [ ] **Step 2: Volle Test-Suite + Sammel-Check ohne Google-Libs-Abhängigkeit**

Run: `pytest -q`
Expected: PASS (alle Tests grün)

Run: `python -c "import src.gcal; import src.reservations; import src.reservations_sync"`
Expected: kein Fehler (die Google-Imports in `gcal.py` sind lazy — der Modul-Import darf nicht crashen).

- [ ] **Step 3: `CHANGELOG.md` ergänzen**

Oben einen neuen Abschnitt einfügen (Stil an bestehende Einträge anpassen):

```markdown
## [Unreleased]

### Hinzugefügt
- Reservierungen: zukünftige Arbeitszeiten lassen sich pro Tag im Tages-Dialog
  reservieren. Reservierungen sind ein eigenständiges Konzept neben den
  erfassten Ist-Zeiten und werden im Kalender violett dargestellt.
- Google-Kalender-Anbindung: in den Einstellungen aktivierbar; Reservierungen
  werden mit einem wählbaren Google Kalender abgeglichen (Push überschreibt,
  geräteübergreifend über den Kalender).
```

- [ ] **Step 4: `src/version.py` bumpen**

Aktuell `VERSION = "1.12.0"` — auf die nächste Minor-Version erhöhen (neues Feature):

```python
VERSION = "1.13.0"
```

- [ ] **Step 5: Manuelle End-to-End-Verifikation** (erfordert echte `credentials.json` mit aktivierter Google Calendar API)

1. `python -m src.main`
2. Einstellungen → „Reservierungen mit Google Kalender abgleichen" aktivieren → OAuth-Flow im Browser durchlaufen → Kalender im Dropdown wählen → Speichern.
3. Einen zukünftigen Tag anklicken → Reservierung eintragen → speichern.
4. Google Kalender im Browser öffnen → Event „Arbeitszeit (reserviert)" am gewählten Tag prüfen.
5. Reservierung in der App ändern → Event im Kalender aktualisiert sich.
6. Reservierung in der App löschen → Event verschwindet aus dem Kalender.
7. App schließen und neu starten → Reservierung weiterhin sichtbar (aus dem Kalender gepullt).

- [ ] **Step 6: Commit**

```bash
git add CHANGELOG.md src/version.py
git commit -m "chore: bump version and changelog for Google Calendar reservations"
```

---

## Hinweis zum Release

Vor dem Merge nach `master` muss am PR ein `release:minor`-Label gesetzt werden (siehe CLAUDE.md „Release-Prozess"). Der Workflow liest die Version aus `src/version.py`.
