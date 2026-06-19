# AP7 — gcal Multi-Event + reservations_sync (Slots) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Den Google-Kalender-Abgleich der Reservierungen auf das Multi-Slot-Modell heben: jeder Reservierungs-Slot ↔ ein Kalender-Event (mit Kategorie im Titel/Marker), `gcal_event_id` pro Slot; `merge_reservations`/`reconcile_reservations` rechnen auf Slot-Ebene (Matching über `gcal_event_id`, Datum-Level-LWW).

**Architecture:** `gcal.py`-Pure-Helfer (`event_payload`/`parse_event`) und `reservations_sync.py` (`merge_reservations`) sind reine Funktionen → voll unit-getestet. Der `reconcile_reservations`-Orchestrator wird mit gemockten gcal-I/O-Funktionen getestet. Damit schließt AP7 auch die zwei in AP5 verschobenen Reservierungs-Import-Tests (Reconcile-Pfad).

**Tech Stack:** Python stdlib, pytest. gcal-Google-Imports bleiben lazy (CI ohne requirements.txt).

## Global Constraints

- **Reservierungs-Record (AP1):** `{date: {slots: [{start, end, kategorie, gcal_event_id}], modified_at, deleted}}`. `gcal_event_id` ist `None`, bis der Slot erstmals als Event gepusht wurde.
- **Ein Event pro Slot.** Matching lokaler Slot ↔ Remote-Event über `gcal_event_id` / `event_id`.
- **Kategorie im Event:** `event_payload` setzt `summary = "{EVENT_SUMMARY} — {kategorie}"` (ohne Kategorie nur `EVENT_SUMMARY`) und `extendedProperties.private["kategorie"]`. `parse_event` liefert `kategorie` mit zurück.
- **gcal-Signaturen:** `event_payload(date, start, end, kategorie, modified_at)`, `parse_event(event) -> {date,start,end,kategorie,modified_at,event_id}`, `create_event(service, cal, date, start, end, kategorie, modified_at)`, `update_event(service, cal, event_id, date, start, end, kategorie, modified_at)`. `list_app_events`/`delete_event` unverändert in der Signatur.
- **Datum-Level-LWW:** Pro Datum entscheidet `modified_at` (App ist bei Gleichstand autoritativ), wie bisher. Gewinnt lokal → Slots gegen Remote-Events diffen (create/update/delete pro Slot). Gewinnt remote → die Remote-Events des Tages werden als Slots übernommen (`_adopt_remote`).
- **Plan-Format:** `create: {date, slot_index, start, end, kategorie, modified_at}`; `update: {event_id, date, start, end, kategorie, modified_at}`; `delete: {event_id}`. `slot_index` zeigt in `merged[date]["slots"]`, damit der Reconcile die neue `event_id` zurückschreibt.
- **Rebase (concurrent local save)** bleibt: Datum, das seit dem Snapshot lokal jünger wurde, überschreibt das Merge-Ergebnis.
- **Mehrere Events/Tag sind normal** — die alte „Duplikat-Event-Selbstheilung pro Tag" entfällt (mehrere Events = mehrere Slots).
- **Datumsformat:** intern ISO; UI deutsch.
- **Ziel:** Nach AP7 ist die GESAMTE Test-Suite grün und das Feature komplett.

## Forward-Dependencies / Notes (für den Plan-Review)

- AP5 hatte zwei Reservierungs-Import-Tests nach AP7 verschoben (gcal_event_id-Erhalt + Reconcile-Plan-Update). AP7 deckt deren Kern ab: ein importiertes Reservierungs-Update wird beim nächsten Reconcile als `update` (gleiche event_id) geplant — Test `test_reconcile_imported_update_plans_update` in Task 2.
- `event_payload` neue Arg-Position: `kategorie` kommt VOR `modified_at` (analog zu create/update). Alle Aufrufer (gcal.create_event/update_event, reconcile) übergeben sie.

---

## Dateistruktur

- `src/gcal.py` — `event_payload`/`parse_event`/`create_event`/`update_event` um `kategorie` erweitert. Rest unverändert.
- `tests/test_gcal.py` — auf neue Signaturen + Kategorie umgestellt.
- `src/reservations_sync.py` — `merge_reservations`/`_merge_one_date`/`reconcile_reservations` slot-fähig (Neufassung).
- `tests/test_reservations_sync.py` — auf Slot-Records umgestellt + Reconcile-Tests.

Task 1 (gcal) ist unabhängig. Task 2 (reservations_sync) konsumiert die neuen gcal-Signaturen.

---

## Task 1: `gcal.py` — Kategorie in Events

**Files:**
- Modify: `src/gcal.py` (`event_payload`, `parse_event`, `create_event`, `update_event`)
- Test: `tests/test_gcal.py` (Neufassung)

**Interfaces:**
- Produces: `event_payload(date, start, end, kategorie, modified_at)`, `parse_event -> {…, kategorie, …}`, `create_event(service, cal, date, start, end, kategorie, modified_at) -> id`, `update_event(service, cal, event_id, date, start, end, kategorie, modified_at)`.

- [ ] **Step 1: `tests/test_gcal.py` neu schreiben**

Ersetze den **kompletten** Inhalt von `tests/test_gcal.py` durch:

```python
from src import gcal


def test_event_payload_has_summary_and_marker():
    body = gcal.event_payload("2026-06-01", "09:00", "17:00", "", "2026-05-20T10:00:00Z")
    assert body["summary"] == gcal.EVENT_SUMMARY
    private = body["extendedProperties"]["private"]
    assert private[gcal.APP_MARKER_KEY] == gcal.APP_MARKER_VALUE
    assert private["kategorie"] == ""
    assert private["modified_at"] == "2026-05-20T10:00:00Z"


def test_event_payload_summary_includes_kategorie():
    body = gcal.event_payload("2026-06-01", "09:00", "17:00", "Büro", "2026-05-20T10:00:00Z")
    assert body["summary"] == f"{gcal.EVENT_SUMMARY} — Büro"
    assert body["extendedProperties"]["private"]["kategorie"] == "Büro"


def test_event_payload_datetime_encodes_date_and_time():
    body = gcal.event_payload("2026-06-01", "09:30", "17:45", "", "2026-05-20T10:00:00Z")
    assert body["start"]["dateTime"].startswith("2026-06-01T09:30:00")
    assert body["end"]["dateTime"].startswith("2026-06-01T17:45:00")


def test_parse_event_roundtrips_payload_with_kategorie():
    body = gcal.event_payload("2026-06-01", "09:00", "17:00", "Büro", "2026-05-20T10:00:00Z")
    body["id"] = "ev-42"
    parsed = gcal.parse_event(body)
    assert parsed == {
        "date": "2026-06-01", "start": "09:00", "end": "17:00",
        "kategorie": "Büro", "modified_at": "2026-05-20T10:00:00Z", "event_id": "ev-42",
    }


def test_parse_event_missing_kategorie_defaults_empty():
    # Event ohne kategorie-Property (z.B. von einer älteren App-Version)
    body = {
        "id": "ev-1",
        "start": {"dateTime": "2026-06-01T09:00:00+02:00"},
        "end": {"dateTime": "2026-06-01T17:00:00+02:00"},
        "extendedProperties": {"private": {
            gcal.APP_MARKER_KEY: gcal.APP_MARKER_VALUE,
            "modified_at": "2026-05-20T10:00:00Z",
        }},
    }
    assert gcal.parse_event(body)["kategorie"] == ""


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


def test_parse_event_ignores_event_with_null_extended_properties():
    ev = {"id": "x", "extendedProperties": None,
          "start": {"dateTime": "2026-06-01T09:00:00+02:00"},
          "end": {"dateTime": "2026-06-01T17:00:00+02:00"}}
    assert gcal.parse_event(ev) is None


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
    body = gcal.event_payload("2026-06-01", "09:00", "17:00", "", "2026-05-20T10:00:00Z")
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
        service, "cal-1", "2026-06-01", "09:00", "17:00", "Büro", "2026-05-20T10:00:00Z")
    assert event_id == "created-id"
    assert recorder[0][0] == "insert"
    assert recorder[0][1]["body"]["extendedProperties"]["private"]["kategorie"] == "Büro"


def test_update_event_sends_kategorie():
    recorder = []
    service = _FakeService(recorder)
    gcal.update_event(
        service, "cal-1", "ev-1", "2026-06-01", "09:00", "17:00", "HO", "2026-05-20T10:00:00Z")
    assert recorder[0][0] == "update"
    assert recorder[0][1]["eventId"] == "ev-1"
    assert recorder[0][1]["body"]["extendedProperties"]["private"]["kategorie"] == "HO"


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

    gcal.delete_event(_GoneService(), "cal-1", "ev-x")
```

- [ ] **Step 2: Tests laufen lassen — müssen FEHLSCHLAGEN**

Run: `python -m pytest tests/test_gcal.py -q`
Expected: FAIL — `event_payload`/`create_event`/`update_event` haben den `kategorie`-Parameter noch nicht; `parse_event` liefert kein `kategorie`.

- [ ] **Step 3: `src/gcal.py` anpassen**

In `src/gcal.py`, ersetze `event_payload` (aktuell):

```python
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
```

durch:

```python
def event_payload(date_str, start, end, kategorie, modified_at):
    """Baut den Calendar-API-Event-Body aus einem Reservierungs-Slot.

    date_str ISO ('YYYY-MM-DD'), start/end 'HH:MM'. Die dateTime-Werte tragen
    den lokalen UTC-Offset (`astimezone()`) — kein IANA-Zeitzonenname nötig.
    Die Kategorie steht im Titel (für die Kalender-Anzeige) UND als private
    Property (damit parse_event sie verlustfrei zurückliest).
    """
    day = datetime.date.fromisoformat(date_str)
    sh, sm = (int(p) for p in start.split(":"))
    eh, em = (int(p) for p in end.split(":"))
    start_dt = datetime.datetime(day.year, day.month, day.day, sh, sm).astimezone()
    end_dt = datetime.datetime(day.year, day.month, day.day, eh, em).astimezone()
    summary = f"{EVENT_SUMMARY} — {kategorie}" if kategorie else EVENT_SUMMARY
    return {
        "summary": summary,
        "description": EVENT_DESCRIPTION,
        "start": {"dateTime": start_dt.isoformat()},
        "end": {"dateTime": end_dt.isoformat()},
        "extendedProperties": {
            "private": {
                APP_MARKER_KEY: APP_MARKER_VALUE,
                "kategorie": kategorie,
                "modified_at": modified_at,
            },
        },
    }
```

Ersetze in `parse_event` den Return (aktuell):

```python
    return {
        "date": start_dt.date().isoformat(),
        "start": start_dt.strftime("%H:%M"),
        "end": end_dt.strftime("%H:%M"),
        "modified_at": private.get("modified_at", ""),
        "event_id": event.get("id", ""),
    }
```

durch:

```python
    return {
        "date": start_dt.date().isoformat(),
        "start": start_dt.strftime("%H:%M"),
        "end": end_dt.strftime("%H:%M"),
        "kategorie": private.get("kategorie", ""),
        "modified_at": private.get("modified_at", ""),
        "event_id": event.get("id", ""),
    }
```

Ersetze `create_event` (aktuell):

```python
def create_event(service, calendar_id, date_str, start, end, modified_at):
    """Legt ein Event an und liefert dessen event_id."""
    body = event_payload(date_str, start, end, modified_at)
    created = service.events().insert(calendarId=calendar_id, body=body).execute()
    return created["id"]
```

durch:

```python
def create_event(service, calendar_id, date_str, start, end, kategorie, modified_at):
    """Legt ein Event an und liefert dessen event_id."""
    body = event_payload(date_str, start, end, kategorie, modified_at)
    created = service.events().insert(calendarId=calendar_id, body=body).execute()
    return created["id"]
```

Ersetze `update_event` (aktuell):

```python
def update_event(service, calendar_id, event_id, date_str, start, end, modified_at):
    """Überschreibt ein bestehendes Event mit den Reservierungs-Werten."""
    body = event_payload(date_str, start, end, modified_at)
    service.events().update(
        calendarId=calendar_id, eventId=event_id, body=body,
    ).execute()
```

durch:

```python
def update_event(service, calendar_id, event_id, date_str, start, end, kategorie, modified_at):
    """Überschreibt ein bestehendes Event mit den Reservierungs-Werten."""
    body = event_payload(date_str, start, end, kategorie, modified_at)
    service.events().update(
        calendarId=calendar_id, eventId=event_id, body=body,
    ).execute()
```

- [ ] **Step 4: Tests laufen lassen — müssen BESTEHEN**

Run: `python -m pytest tests/test_gcal.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/gcal.py tests/test_gcal.py
git commit -m "feat(gcal): Kategorie in Kalender-Events (Titel + Property) (#53)

event_payload/parse_event/create_event/update_event tragen die Kategorie
(Summary 'Arbeitszeit (reserviert) — <Kat>' + extendedProperties.private).
Teil von AP7.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 2: `reservations_sync.py` — Slot↔Event-Merge

**Files:**
- Modify: `src/reservations_sync.py` (komplette Neufassung der Merge-/Reconcile-Logik)
- Test: `tests/test_reservations_sync.py` (Neufassung)

**Interfaces:**
- Consumes: gcal-Signaturen aus Task 1; AP1-Reservierungs-Records.
- Produces:
  - `merge_reservations(local_raw, remote_events, watermark) -> {"merged": {...}, "plan": {...}}` auf Slot-Ebene.
  - `reconcile_reservations(service, calendar_id, store, settings)` (führt Plan aus, schreibt event_ids pro Slot zurück).

- [ ] **Step 1: `tests/test_reservations_sync.py` neu schreiben**

Ersetze den **kompletten** Inhalt von `tests/test_reservations_sync.py` durch:

```python
from src.reservations_sync import merge_reservations


def _lslot(start="09:00", end="17:00", kategorie="", event_id=None):
    return {"start": start, "end": end, "kategorie": kategorie, "gcal_event_id": event_id}


def _local(slots=None, modified_at="2026-05-20T10:00:00Z", deleted=False):
    return {
        "slots": slots if slots is not None else [_lslot()],
        "modified_at": modified_at, "deleted": deleted,
    }


def _remote(date="2026-06-01", start="09:00", end="17:00", kategorie="",
            modified_at="2026-05-20T10:00:00Z", event_id="ev1"):
    return {"date": date, "start": start, "end": end, "kategorie": kategorie,
            "modified_at": modified_at, "event_id": event_id}


def test_local_only_new_creates_event_per_slot():
    res = merge_reservations(
        {"2026-06-01": _local(slots=[_lslot(kategorie="Büro")],
                              modified_at="2026-05-20T10:00:00Z")},
        [], "2026-05-19T00:00:00Z")
    assert res["plan"]["create"] == [{
        "date": "2026-06-01", "slot_index": 0, "start": "09:00", "end": "17:00",
        "kategorie": "Büro", "modified_at": "2026-05-20T10:00:00Z"}]
    assert "2026-06-01" in res["merged"]


def test_local_only_stale_is_dropped():
    res = merge_reservations(
        {"2026-06-01": _local(modified_at="2026-05-10T10:00:00Z")},
        [], "2026-05-19T00:00:00Z")
    assert res["merged"] == {}
    assert res["plan"]["create"] == []


def test_local_only_exactly_at_watermark_is_dropped():
    res = merge_reservations(
        {"2026-06-01": _local(modified_at="2026-05-19T00:00:00Z")},
        [], "2026-05-19T00:00:00Z")
    assert res["merged"] == {}
    assert res["plan"]["create"] == []


def test_remote_only_is_imported_as_slots():
    res = merge_reservations({}, [_remote(kategorie="HO")], "2026-05-19T00:00:00Z")
    slots = res["merged"]["2026-06-01"]["slots"]
    assert slots == [{"start": "09:00", "end": "17:00", "kategorie": "HO", "gcal_event_id": "ev1"}]
    assert res["plan"] == {"create": [], "update": [], "delete": []}


def test_remote_only_multiple_events_become_multiple_slots():
    res = merge_reservations(
        {},
        [_remote(start="08:00", end="12:00", event_id="a"),
         _remote(start="13:00", end="17:00", event_id="b")],
        "2026-05-19T00:00:00Z")
    ids = sorted(s["gcal_event_id"] for s in res["merged"]["2026-06-01"]["slots"])
    assert ids == ["a", "b"]
    assert res["plan"] == {"create": [], "update": [], "delete": []}


def test_local_wins_updates_matched_slot():
    res = merge_reservations(
        {"2026-06-01": _local(slots=[_lslot(start="08:00", event_id="ev1")],
                              modified_at="2026-05-21T10:00:00Z")},
        [_remote(start="09:00", modified_at="2026-05-20T10:00:00Z", event_id="ev1")],
        "2026-05-19T00:00:00Z")
    assert res["plan"]["update"] == [{
        "event_id": "ev1", "date": "2026-06-01", "start": "08:00", "end": "17:00",
        "kategorie": "", "modified_at": "2026-05-21T10:00:00Z"}]
    assert res["merged"]["2026-06-01"]["slots"][0]["gcal_event_id"] == "ev1"


def test_local_wins_category_change_updates():
    res = merge_reservations(
        {"2026-06-01": _local(slots=[_lslot(kategorie="HO", event_id="ev1")],
                              modified_at="2026-05-21T10:00:00Z")},
        [_remote(kategorie="Büro", modified_at="2026-05-20T10:00:00Z", event_id="ev1")],
        "2026-05-19T00:00:00Z")
    assert len(res["plan"]["update"]) == 1
    assert res["plan"]["update"][0]["kategorie"] == "HO"


def test_local_wins_equal_values_no_update():
    res = merge_reservations(
        {"2026-06-01": _local(slots=[_lslot(event_id="ev1")],
                              modified_at="2026-05-21T10:00:00Z")},
        [_remote(modified_at="2026-05-20T10:00:00Z", event_id="ev1")],
        "2026-05-19T00:00:00Z")
    assert res["plan"]["update"] == []
    assert res["merged"]["2026-06-01"]["slots"][0]["gcal_event_id"] == "ev1"


def test_local_wins_new_slot_creates_extra_event():
    res = merge_reservations(
        {"2026-06-01": _local(
            slots=[_lslot(start="08:00", end="12:00", event_id="ev1"),
                   _lslot(start="13:00", end="17:00", event_id=None)],
            modified_at="2026-05-21T10:00:00Z")},
        [_remote(start="08:00", end="12:00", modified_at="2026-05-20T10:00:00Z", event_id="ev1")],
        "2026-05-19T00:00:00Z")
    assert res["plan"]["update"] == []
    assert res["plan"]["create"] == [{
        "date": "2026-06-01", "slot_index": 1, "start": "13:00", "end": "17:00",
        "kategorie": "", "modified_at": "2026-05-21T10:00:00Z"}]
    assert res["plan"]["delete"] == []


def test_local_wins_removed_slot_deletes_orphan_event():
    res = merge_reservations(
        {"2026-06-01": _local(slots=[_lslot(start="08:00", end="12:00", event_id="ev1")],
                              modified_at="2026-05-21T10:00:00Z")},
        [_remote(start="08:00", end="12:00", modified_at="2026-05-20T10:00:00Z", event_id="ev1"),
         _remote(start="13:00", end="17:00", modified_at="2026-05-20T10:00:00Z", event_id="ev2")],
        "2026-05-19T00:00:00Z")
    assert res["plan"]["delete"] == [{"event_id": "ev2"}]
    assert [s["gcal_event_id"] for s in res["merged"]["2026-06-01"]["slots"]] == ["ev1"]


def test_remote_wins_adopts_remote_slots():
    res = merge_reservations(
        {"2026-06-01": _local(slots=[_lslot(start="08:00", event_id="ev1")],
                              modified_at="2026-05-20T10:00:00Z")},
        [_remote(start="09:00", modified_at="2026-05-21T10:00:00Z", event_id="ev1")],
        "2026-05-19T00:00:00Z")
    assert res["merged"]["2026-06-01"]["slots"][0]["start"] == "09:00"
    assert res["plan"]["update"] == []


def test_tombstone_newer_deletes_all_events():
    res = merge_reservations(
        {"2026-06-01": _local(slots=[], deleted=True, modified_at="2026-05-21T10:00:00Z")},
        [_remote(modified_at="2026-05-20T10:00:00Z", event_id="ev1"),
         _remote(start="13:00", modified_at="2026-05-20T10:00:00Z", event_id="ev2")],
        "2026-05-19T00:00:00Z")
    deleted = sorted(d["event_id"] for d in res["plan"]["delete"])
    assert deleted == ["ev1", "ev2"]
    assert "2026-06-01" not in res["merged"]


def test_tombstone_older_than_remote_is_dropped():
    res = merge_reservations(
        {"2026-06-01": _local(slots=[], deleted=True, modified_at="2026-05-20T10:00:00Z")},
        [_remote(modified_at="2026-05-21T10:00:00Z", event_id="ev1")],
        "2026-05-19T00:00:00Z")
    assert res["plan"]["delete"] == []
    assert res["merged"]["2026-06-01"]["slots"][0]["start"] == "09:00"


def test_tombstone_without_remote_is_noop():
    res = merge_reservations(
        {"2026-06-01": _local(slots=[], deleted=True, modified_at="2026-05-21T10:00:00Z")},
        [], "2026-05-19T00:00:00Z")
    assert res["merged"] == {}
    assert res["plan"] == {"create": [], "update": [], "delete": []}


# --- reconcile (mit gemockten gcal-I/O) ---


def test_reconcile_creates_event_and_persists_event_id_per_slot(tmp_path, monkeypatch):
    from src import gcal, reservations_sync
    from src.reservations import ReservationStore
    from src.settings import Settings

    store = ReservationStore(str(tmp_path / "res.json"))
    store.save("2026-06-01", [{"start": "09:00", "end": "17:00", "kategorie": "Büro"}])
    settings = Settings(str(tmp_path / "set.json"))

    monkeypatch.setattr(gcal, "list_app_events", lambda s, c: [])
    monkeypatch.setattr(gcal, "update_event", lambda *a: None)
    monkeypatch.setattr(gcal, "delete_event", lambda *a: None)
    monkeypatch.setattr(
        gcal, "create_event",
        lambda s, c, date, start, end, kategorie, modified_at: "new-event-id")

    reservations_sync.reconcile_reservations(object(), "cal-1", store, settings)

    raw = store.get_all_raw()["2026-06-01"]
    assert raw["slots"][0]["gcal_event_id"] == "new-event-id"
    assert settings.get("last_calendar_sync_at") != ""


def test_reconcile_imported_update_plans_update(tmp_path, monkeypatch):
    """AP5-Forward-Test: ein lokal geändertes (jüngeres) Slot mit bestehender
    event_id wird beim Reconcile als update geplant (kein Duplikat)."""
    from src import gcal, reservations_sync
    from src.reservations import ReservationStore
    from src.settings import Settings

    store = ReservationStore(str(tmp_path / "res.json"))
    # Slot mit bereits bekannter event_id (wie nach einem früheren Reconcile).
    store.save("2026-06-01", [{"start": "10:00", "end": "14:00",
                               "kategorie": "", "gcal_event_id": "evt-1"}])
    settings = Settings(str(tmp_path / "set.json"))

    updated = []
    remote = {"date": "2026-06-01", "start": "08:00", "end": "12:00",
              "kategorie": "", "modified_at": "2020-01-01T00:00:00Z", "event_id": "evt-1"}
    monkeypatch.setattr(gcal, "list_app_events", lambda s, c: [remote])
    monkeypatch.setattr(gcal, "create_event", lambda *a: "x")
    monkeypatch.setattr(gcal, "delete_event", lambda *a: None)
    monkeypatch.setattr(
        gcal, "update_event",
        lambda s, c, event_id, *a: updated.append(event_id))

    reservations_sync.reconcile_reservations(object(), "cal-1", store, settings)

    assert updated == ["evt-1"]
    assert store.get_all_raw()["2026-06-01"]["slots"][0]["start"] == "10:00"


def test_reconcile_preserves_concurrent_local_save(tmp_path, monkeypatch):
    from src import gcal, reservations_sync
    from src.reservations import ReservationStore
    from src.settings import Settings

    store = ReservationStore(str(tmp_path / "res.json"))
    settings = Settings(str(tmp_path / "set.json"))

    def fake_list(s, c):
        store.save("2026-07-01", [{"start": "10:00", "end": "18:00", "kategorie": ""}])
        return []

    monkeypatch.setattr(gcal, "list_app_events", fake_list)
    monkeypatch.setattr(gcal, "create_event", lambda *a: "ev")
    monkeypatch.setattr(gcal, "update_event", lambda *a: None)
    monkeypatch.setattr(gcal, "delete_event", lambda *a: None)

    reservations_sync.reconcile_reservations(object(), "cal-1", store, settings)

    assert store.get("2026-07-01") == {"slots": [{"start": "10:00", "end": "18:00", "kategorie": ""}]}
```

- [ ] **Step 2: Tests laufen lassen — müssen FEHLSCHLAGEN**

Run: `python -m pytest tests/test_reservations_sync.py -q`
Expected: FAIL — `merge_reservations` rechnet noch per-Datum auf der alten Shape.

- [ ] **Step 3: `src/reservations_sync.py` neu schreiben**

Ersetze den **kompletten** Inhalt von `src/reservations_sync.py` durch:

```python
# src/reservations_sync.py
"""Reservierungs-Abgleich mit dem Google Kalender (Slot-Modell).

Jeder Reservierungs-Slot ↔ ein Kalender-Event (Matching über gcal_event_id).
`merge_reservations()` ist eine pure LWW-Merge-Funktion (kein I/O): pro Datum
entscheidet `modified_at` (App autoritativ bei Gleichstand), ob die lokalen
Slots oder die Remote-Events gewinnen. `reconcile_reservations()` orchestriert
pull → merge → push und schreibt neue event_ids pro Slot zurück.
"""

import datetime


def _utc_now_iso():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _slot_from_event(ev):
    """Reservierungs-Slot aus einem geparsten Kalender-Event."""
    return {
        "start": ev["start"], "end": ev["end"],
        "kategorie": ev.get("kategorie", ""), "gcal_event_id": ev["event_id"],
    }


def _adopt_remote(date, remotes, merged):
    """Remote gewinnt: die Slots des Tages = die Remote-Events."""
    merged[date] = {
        "slots": [_slot_from_event(ev) for ev in remotes],
        "modified_at": max(ev["modified_at"] for ev in remotes),
        "deleted": False,
    }


def _merge_one_date(date, local, remotes, watermark, merged, plan):
    """Mergt einen einzelnen Tag (Slot-Ebene). Mutiert `merged`/`plan`.

    local   — Reservierungs-Record {slots, modified_at, deleted} oder None
    remotes — Liste geparster Kalender-Events dieses Tages (evtl. leer)
    """
    is_tombstone = local is not None and local.get("deleted")
    local_mod = local["modified_at"] if local is not None else None
    remote_mod = max((ev["modified_at"] for ev in remotes), default=None)

    # Fall 1: nichts vorhanden.
    if local is None and not remotes:
        return

    # Fall 2: nur remote → als Slots übernehmen.
    if local is None:
        _adopt_remote(date, remotes, merged)
        return

    # Fall 3: lokaler Tombstone.
    if is_tombstone:
        if not remotes:
            return  # Tombstone fällt weg.
        if local_mod >= remote_mod:
            for ev in remotes:
                plan["delete"].append({"event_id": ev["event_id"]})
            return  # Löschung gewinnt.
        _adopt_remote(date, remotes, merged)  # Remote-Update jünger.
        return

    # Fall 4: lokal (echt), keine Remote-Events.
    if not remotes:
        if local_mod > watermark:
            merged[date] = {
                "slots": [dict(s) for s in local["slots"]],
                "modified_at": local_mod, "deleted": False,
            }
            for i, s in enumerate(local["slots"]):
                plan["create"].append({
                    "date": date, "slot_index": i,
                    "start": s["start"], "end": s["end"],
                    "kategorie": s.get("kategorie", ""), "modified_at": local_mod,
                })
        # sonst: war beim letzten Sync da, remote jetzt weg → verwerfen.
        return

    # Fall 5: lokal (echt) + Remote-Events.
    if remote_mod > local_mod:
        _adopt_remote(date, remotes, merged)
        return

    # Lokal gewinnt (inkl. Gleichstand — App autoritativ): Slots ↔ Events über
    # gcal_event_id matchen.
    remote_by_id = {ev["event_id"]: ev for ev in remotes}
    matched_ids = set()
    merged_slots = []
    for i, s in enumerate(local["slots"]):
        eid = s.get("gcal_event_id")
        slot_copy = dict(s)
        if eid and eid in remote_by_id:
            matched_ids.add(eid)
            ev = remote_by_id[eid]
            if (s["start"] != ev["start"] or s["end"] != ev["end"]
                    or s.get("kategorie", "") != ev.get("kategorie", "")):
                plan["update"].append({
                    "event_id": eid, "date": date,
                    "start": s["start"], "end": s["end"],
                    "kategorie": s.get("kategorie", ""), "modified_at": local_mod,
                })
        else:
            # Neuer Slot (noch kein Event oder verwaiste id) → create.
            slot_copy["gcal_event_id"] = None
            plan["create"].append({
                "date": date, "slot_index": i,
                "start": s["start"], "end": s["end"],
                "kategorie": s.get("kategorie", ""), "modified_at": local_mod,
            })
        merged_slots.append(slot_copy)

    # Remote-Events ohne lokalen Slot → löschen.
    for ev in remotes:
        if ev["event_id"] not in matched_ids:
            plan["delete"].append({"event_id": ev["event_id"]})

    merged[date] = {"slots": merged_slots, "modified_at": local_mod, "deleted": False}


def merge_reservations(local_raw, remote_events, watermark):
    """Pure Merge zwischen lokalen Reservierungs-Records und Kalender-Events.

    local_raw:     {date: {slots: [{start,end,kategorie,gcal_event_id}],
                           modified_at, deleted}}
    remote_events: Liste von {date, start, end, kategorie, modified_at, event_id}
    watermark:     last_calendar_sync_at (ISO-String, "" beim Erststart)

    Liefert {"merged": {...}, "plan": {"create": [...], "update": [...],
    "delete": [...]}}.
    """
    plan = {"create": [], "update": [], "delete": []}

    remote_by_date = {}
    for ev in remote_events:
        remote_by_date.setdefault(ev["date"], []).append(ev)

    merged = {}
    for date in set(local_raw.keys()) | set(remote_by_date.keys()):
        _merge_one_date(
            date, local_raw.get(date), remote_by_date.get(date, []),
            watermark, merged, plan,
        )
    return {"merged": merged, "plan": plan}


def reconcile_reservations(service, calendar_id, store, settings):
    """Voller Kalender-Abgleich: pull → merge → push.

    Mutiert store und settings. Wirft bei Netz-/API-Fehlern weiter — der Caller
    entscheidet, ob still geloggt oder als Messagebox gezeigt wird.
    """
    from src import gcal

    watermark = settings.get("last_calendar_sync_at") or ""
    local_snapshot = store.get_all_raw()
    remote_events = gcal.list_app_events(service, calendar_id)
    result = merge_reservations(local_snapshot, remote_events, watermark)
    merged, plan = result["merged"], result["plan"]

    for item in plan["delete"]:
        gcal.delete_event(service, calendar_id, item["event_id"])

    for item in plan["update"]:
        gcal.update_event(
            service, calendar_id, item["event_id"],
            item["date"], item["start"], item["end"],
            item["kategorie"], item["modified_at"],
        )

    for item in plan["create"]:
        event_id = gcal.create_event(
            service, calendar_id,
            item["date"], item["start"], item["end"],
            item["kategorie"], item["modified_at"],
        )
        merged[item["date"]]["slots"][item["slot_index"]]["gcal_event_id"] = event_id

    # Rebase: Reservierungen, die seit dem Snapshot lokal gespeichert/geändert
    # wurden (paralleler Reconcile / User-Save während des Netzwerkteils),
    # dürfen nicht durch den apply_reconciled-Replace verloren gehen.
    for date, entry in store.get_all_raw().items():
        snap = local_snapshot.get(date)
        if snap is None or entry.get("modified_at", "") > snap.get("modified_at", ""):
            merged[date] = entry

    store.apply_reconciled(merged)
    settings.set("last_calendar_sync_at", _utc_now_iso())
```

- [ ] **Step 4: Tests laufen lassen — müssen BESTEHEN**

Run: `python -m pytest tests/test_reservations_sync.py -q`
Expected: PASS.

- [ ] **Step 5: GESAMT-Regression (ganze Suite muss grün sein)**

Run: `python -m pytest tests/ -q`
Expected: PASS (alle Tests grün — AP7 schließt die letzten roten Dateien).

- [ ] **Step 6: Commit**

```bash
git add src/reservations_sync.py tests/test_reservations_sync.py
git commit -m "feat(gcal): Reservierungs-Reconcile auf Slot↔Event-Mapping (#53)

merge_reservations rechnet auf Slot-Ebene: pro Slot ein Event, Matching über
gcal_event_id, Datum-Level-LWW. reconcile schreibt neue event_ids pro Slot
zurück. Schließt die ganze Suite (inkl. der aus AP5 verschobenen Tests).
Teil von AP7.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Self-Review

**1. Spec-Coverage (Spec „gcal (gcal.py) + reservations_sync.py — mehrere Events pro Tag"):**
- Pro Reservierungs-Slot ein Event, `gcal_event_id` pro Slot → Task 2 (`_merge_one_date` create/update/delete pro Slot) ✓
- Event-Titel trägt Kategorie → Task 1 (`event_payload` summary + property) ✓
- merge/reconcile von „pro Tag" auf „pro Slot im Tag", Matching über event_id → Task 2 ✓
- `list_app_events`/`parse_event` liefern weiter pro Event ein Dict (jetzt inkl. kategorie) → Task 1 ✓
- AP5-verschobene Tests (gcal_event_id-Erhalt/Reconcile-Update) → `test_reconcile_imported_update_plans_update` ✓
- Ziel „ganze Suite grün" → Task 2 Step 5 ✓

**2. Placeholder-Scan:** Keine TBD/TODO; vollständiger Code + Tests in jedem Step. ✓

**3. Typ-Konsistenz:**
- `event_payload(date,start,end,kategorie,modified_at)` / `create_event(...,kategorie,modified_at)` / `update_event(...,kategorie,modified_at)` — identisch in gcal.py, test_gcal, reconcile-Aufrufen. ✓
- Plan `create`-Item `{date,slot_index,start,end,kategorie,modified_at}`; `slot_index` indexiert `merged[date]["slots"]` — reconcile schreibt event_id dorthin zurück. ✓
- Reservierungs-Record `{slots:[{start,end,kategorie,gcal_event_id}],modified_at,deleted}` — konsistent zu AP1 + apply_reconciled-Pflichtkeys. ✓
- `parse_event` liefert `{date,start,end,kategorie,modified_at,event_id}` — von `_slot_from_event` und dem Matching gelesen. ✓
