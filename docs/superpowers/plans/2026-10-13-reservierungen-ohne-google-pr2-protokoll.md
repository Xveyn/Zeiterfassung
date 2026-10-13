# Reservierungen in der Handy-Erfassung: Protokoll und Merge am Desktop (PR 2/3)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `POST /v1/sync` nimmt Reservierungen vom Handy entgegen, merged sie per LWW in den `ReservationStore` und liefert alle aktiven Reservierungstage (heute bis heute + 365) zurück — nur wenn `reservations_enabled` an ist.

**Architecture:** Additiv, `PROTOCOL` bleibt 2. Die neue, Tk-freie Logik (Fremddaten prüfen, LWW, Antwort bauen) liegt in einem neuen Modul `src/mobile_reservations.py`; `mobile_sync.py` ruft sie nur. Der Merge selbst ist eine Methode des Stores (`ReservationStore.merge_phone`), damit er unter dessen Lock atomar ist und `gcal_event_id`/`send_reminder_minutes` per Index erhalten bleiben. Der Kalender-Abgleich wird nach dem Merge über einen neuen Context-Hook angestoßen.

**Tech Stack:** Python 3.12, pytest, nur stdlib. Keine neue Abhängigkeit.

**Spec:** `docs/superpowers/specs/2026-10-12-reservierungen-ohne-google-design.md`, Abschnitt „PR 2: Protokoll und Merge am Desktop". PR 1 ist als #308 gemerged. PR 3 (PWA) folgt und ist nicht Teil dieses Plans.

## Global Constraints

- `PROTOCOL` bleibt `2`; Änderungen sind rein additiv (`pwa/CLAUDE.md`, „Kompatibilität", Regel 1).
- **Zuerst** die aktuelle Form unter `pwa/test/fixtures/compat/*-pre-reservations.json` einfrieren, bevor ein Live-Beispiel geändert wird (Regel 4).
- Anfrage: `reservations: {ISO: {slots: [{start, end, kategorie}], modified_at, deleted}}`. Datum heute bis heute + 365, sonst `422` für den Tag. Slot-Regeln wie bei Ist-Zeiten (`api_entry_write.parse_slots`, höchstens `MAX_SLOTS`). `modified_at` höchstens 15 Minuten in der Zukunft. Die Uhrregel `clock_skew` greift vor den Einträgen. Nie `gcal_event_id` oder `send_reminder_minutes` vom Handy.
- Antwort: `reservations` mit allen aktiven Tagen von heute bis heute + 365, gleiche Form wie die Anfrage, **nur wenn** `reservations_enabled` an ist. Reservierungen zählen nicht ins Mengenbudget der Ist-Zeiten (`MAX_RESPONSE_ENTRY_BYTES`).
- Ist `reservations_enabled` aus: gesendete Reservierungen werden **ignoriert, nicht abgelehnt**; die Antwort enthält kein Feld.
- Sperrreihenfolge `devices_lock` → `sync_guard` → `data_lock` bleibt. Callbacks (`on_change` & Co.) laufen erst nach Freigabe aller Sperren.
- Fehlercodes nur aus `pwa/test/fixtures/errors.json`: `test_mobile_contract.py` sammelt jedes `SyncError(status, "code", …)` per Regex aus dem Quelltext. Neue Reservierungsfehler verwenden deshalb `422 invalid_entry`.
- Jeder Catch-all loggt oder trägt eine Begründung (`tests/test_catch_all_handlers.py`). Neue Module Tk-frei; `mobile_reservations.py` kommt in die Whitelist von `tests/test_type_annotations.py` (vollständige Annotationen).
- Kommentare/Docstrings deutsch, Stil wie `mobile_sync.py`. Commit-Messages `type(scope): …` auf Deutsch, Branch `feat/reservierungen-handy-protokoll`.

## Review Focus

Eingaben, die die Spec voraussetzt, aber kein Task-Test von selbst abdeckt; jede Zeile bekommt einen Test in dem Task, dem der Code gehört:

1. Das Handy sendet **denselben** Reservierungstag zweimal (Wiederholung nach Timeout): zweiter Aufruf ändert nichts, `changed` bleibt `False`, kein zweiter Kalender-Abgleich. → Task 2
2. Das Handy überschreibt einen Tag, dessen Slots am Desktop schon einen Kalender-Event tragen oder eine Sende-Erinnerung: beides bleibt per Index erhalten. → Task 2
3. Ein Tombstone vom Handy für einen Tag, den der Desktop nicht kennt, legt **keinen** Eintrag an. → Task 2
4. Reservierungen aus, Handy sendet trotzdem (auch kaputte): keine Ablehnung, kein Schreiben, kein Feld in der Antwort. → Task 4
5. Ein Reservierungstag **vor heute** oder mehr als 365 Tage voraus: `422`; die Ist-Zeiten derselben Anfrage werden dann nicht angewendet (wie bei Ist-Zeiten, „ein schlechter Tag lehnt alles ab"). → Task 3

## Offene Entscheidung (vor Task 3 klären)

Die Spec sagt `422` für Tage außerhalb von heute…heute + 365, und die Risiko-Zeile sagt, das blockiere „nur diesen Tag". Beides passt nicht zusammen: `parse_request` lehnt bei **einem** schlechten Tag die **ganze** Anfrage ab (so ist es bei Ist-Zeiten, `test_one_bad_day_rejects_the_whole_request`). Ein Handy, das um Mitternacht noch einen schmutzigen Reservierungstag von „gestern" trägt, bekäme dann bei jedem Abgleich `422` und könnte auch seine Ist-Zeiten nicht mehr senden.

Der Plan setzt zunächst die **Spec wörtlich** um (ganze Anfrage `422`, Task 3). Empfehlung: Tage **vor heute** stattdessen stillschweigend verwerfen (Handy-Uhr/Tagesgrenze, der Tag ist ohnehin nicht mehr bearbeitbar) und nur Tage **hinter** heute + 365 sowie Formfehler mit `422` ablehnen. Das ist eine Zeile in `parse_reservations` (Task 3, Schritt 3, markiert). Bitte vor der Umsetzung entscheiden.

## Dateien

| Datei | Verantwortung |
|---|---|
| `pwa/test/fixtures/compat/*-pre-reservations.json` (neu, 2) | Eingefrorene Vorgänger-Form |
| `pwa/test/fixtures/sync-request.json`, `sync-response.json` | Live-Beispiele um `reservations` erweitert |
| `src/reservations.py` | `ReservationStore.merge_phone` (LWW, atomar, erhält Ids) |
| `src/mobile_reservations.py` (neu) | `parse_reservations` (Fremddaten), `build_reservations` (Antwort) |
| `src/mobile_sync.py` | `SyncRequest.reservations`, `parse_request(today=, accept_reservations=)`, `perform_sync(reservation_store=, report=)`, `build_response(reservations=)` |
| `src/mobile_routes.py` | `MobileContext.reservation_store`, `on_reservations_change`; Route reicht durch und meldet |
| `src/ui.py` | Store in den Context, `_on_mobile_reservations_changed` |
| `tests/test_reservations.py`, `tests/test_mobile_reservations.py` (neu), `tests/test_mobile_sync.py`, `tests/test_mobile_routes.py`, `tests/test_mobile_contract.py`, `tests/test_mobile_wiring.py` | Tests |
| `src/CLAUDE.md`, `pwa/CLAUDE.md`, `CLAUDE.md` | Doku |

---

### Task 1: Vorgänger-Form einfrieren

**Files:**
- Create: `pwa/test/fixtures/compat/sync-request-pre-reservations.json`, `pwa/test/fixtures/compat/sync-response-pre-reservations.json`
- Modify: `tests/test_mobile_contract.py` (neuer Test), `pwa/test/compat.test.js` (nur wenn er die Dateien aufzählt, sonst nicht)

**Interfaces:**
- Produces: die zwei eingefrorenen Dateien, byte-gleich zu den Live-Beispielen **vor** diesem PR.

- [ ] **Step 1: Kopieren, bevor irgendetwas anderes geändert wird**

```bash
cd pwa/test/fixtures
cp sync-request.json  compat/sync-request-pre-reservations.json
cp sync-response.json compat/sync-response-pre-reservations.json
cd ../../..
git diff --stat   # nur die zwei neuen Dateien
```

- [ ] **Step 2: Test, dass der Desktop die alte Anfrage weiter annimmt und **keine** Reservierungen liest**

In `tests/test_mobile_contract.py` hinter `test_the_desktop_still_accepts_the_request_of_a_phone_without_the_window_wish`:

```python
def test_the_desktop_still_accepts_the_request_of_a_phone_without_reservations():
    example = load("compat/sync-request-pre-reservations.json")
    assert "reservations" not in example

    parsed = mobile_sync.parse_request(json.dumps(example).encode(), now=example["client_time"])

    assert sorted(parsed.entries) == sorted(example["entries"])
    assert parsed.reservations == {}
```

- [ ] **Step 3: Test laufen lassen — er schlägt fehl**

Run: `pytest tests/test_mobile_contract.py::test_the_desktop_still_accepts_the_request_of_a_phone_without_reservations -v`
Expected: FAIL (`SyncRequest` hat kein Attribut `reservations`). Der Test wird in Task 4 grün; **hier nicht committen**, sondern nur die Fixtures (Step 4).

- [ ] **Step 4: Nur die Fixtures committen**

```bash
git add pwa/test/fixtures/compat/sync-request-pre-reservations.json pwa/test/fixtures/compat/sync-response-pre-reservations.json
git commit -m "test(mobil): Vertragsbeispiele vor den Reservierungen eingefroren"
```

(Den Test aus Step 2 bis Task 4 ungestaged lassen oder dort erst anlegen.)

---

### Task 2: `ReservationStore.merge_phone`

**Files:**
- Modify: `src/reservations.py` (neue Methode nach `delete`)
- Test: `tests/test_reservations.py`

**Interfaces:**
- Produces: `ReservationStore.merge_phone(days: dict[str, Reservation]) -> bool` — `days` ist `{ISO: {"slots": [{start, end, kategorie}], "modified_at": str, "deleted": bool}}`, bereits geprüft. Gibt `True` zurück, wenn sich der Store geändert hat (dann ist geschrieben). Schreibt mit dem `modified_at` **des Handys**, nicht `utc_now_iso()`.

Regeln: Der Tag wird übernommen, wenn der Schlüssel `(modified_at, kanonischer Inhalt)` des Handys **größer** ist als der des Desktops (Gleichstand ändert nichts → idempotent). Kanonischer Inhalt = `json.dumps` der projizierten `{slots: [{start,end,kategorie}], deleted}` mit `sort_keys=True`. Ein Tombstone für einen unbekannten Tag wird verworfen. Slots erben `gcal_event_id` und `send_reminder_minutes` per Index vom alten Stand (wie `save`). Ein Tombstone ersetzt den Tag durch `{"slots": [], "modified_at": …, "deleted": True}`.

- [ ] **Step 1: Failing tests**

```python
# tests/test_reservations.py (anhängen)
def _store(tmp_path):
    return ReservationStore(str(tmp_path / "reservations.json"))


def _phone(*slots, modified_at="2026-10-13T10:00:00Z", deleted=False):
    return {"slots": [dict(s) for s in slots], "modified_at": modified_at, "deleted": deleted}


SLOT_A = {"start": "09:00", "end": "12:00", "kategorie": "Projekt"}


def test_merge_phone_adds_a_new_day_with_the_phones_timestamp(tmp_path):
    store = _store(tmp_path)

    changed = store.merge_phone({"2026-10-20": _phone(SLOT_A)})

    assert changed is True
    raw = store.get_all_raw()["2026-10-20"]
    assert raw["modified_at"] == "2026-10-13T10:00:00Z"
    assert raw["deleted"] is False
    assert raw["slots"] == [{"start": "09:00", "end": "12:00", "kategorie": "Projekt",
                             "gcal_event_id": None, "send_reminder_minutes": None}]


def test_merge_phone_is_idempotent(tmp_path):
    store = _store(tmp_path)
    store.merge_phone({"2026-10-20": _phone(SLOT_A)})
    before = (tmp_path / "reservations.json").read_bytes()

    changed = store.merge_phone({"2026-10-20": _phone(SLOT_A)})

    assert changed is False
    assert (tmp_path / "reservations.json").read_bytes() == before


def test_merge_phone_keeps_calendar_ids_and_reminders_by_index(tmp_path):
    store = _store(tmp_path)
    store.apply_reconciled({"2026-10-20": {
        "slots": [{"start": "09:00", "end": "12:00", "kategorie": "Projekt",
                   "gcal_event_id": "ev1", "send_reminder_minutes": 15}],
        "modified_at": "2026-10-12T08:00:00Z", "deleted": False}})

    changed = store.merge_phone({"2026-10-20": _phone(
        {"start": "09:30", "end": "12:00", "kategorie": "Projekt"})})

    assert changed is True
    slot = store.get_all_raw()["2026-10-20"]["slots"][0]
    assert slot["start"] == "09:30"
    assert slot["gcal_event_id"] == "ev1"
    assert slot["send_reminder_minutes"] == 15


def test_merge_phone_loses_against_a_newer_desktop_day(tmp_path):
    store = _store(tmp_path)
    store.apply_reconciled({"2026-10-20": {
        "slots": [{"start": "08:00", "end": "09:00", "kategorie": "",
                   "gcal_event_id": None, "send_reminder_minutes": None}],
        "modified_at": "2026-10-13T11:00:00Z", "deleted": False}})

    changed = store.merge_phone({"2026-10-20": _phone(SLOT_A, modified_at="2026-10-13T10:00:00Z")})

    assert changed is False
    assert store.get_all_raw()["2026-10-20"]["slots"][0]["start"] == "08:00"


def test_merge_phone_tombstone_deletes_a_known_day(tmp_path):
    store = _store(tmp_path)
    store.merge_phone({"2026-10-20": _phone(SLOT_A)})

    changed = store.merge_phone({"2026-10-20": _phone(modified_at="2026-10-13T12:00:00Z", deleted=True)})

    assert changed is True
    assert store.get_all_raw()["2026-10-20"] == {
        "slots": [], "modified_at": "2026-10-13T12:00:00Z", "deleted": True}
    assert store.get("2026-10-20") is None


def test_merge_phone_ignores_a_tombstone_for_an_unknown_day(tmp_path):
    store = _store(tmp_path)

    changed = store.merge_phone({"2026-10-20": _phone(modified_at="2026-10-13T12:00:00Z", deleted=True)})

    assert changed is False
    assert store.get_all_raw() == {}


def test_merge_phone_keeps_memory_unchanged_when_the_write_fails(tmp_path, monkeypatch):
    store = _store(tmp_path)

    def boom(*_args, **_kwargs):
        raise OSError("Platte voll")

    monkeypatch.setattr("src.reservations.atomic_write_json", boom)

    with pytest.raises(OSError):
        store.merge_phone({"2026-10-20": _phone(SLOT_A)})

    assert store.get_all_raw() == {}
```

(`pytest`, `ReservationStore` sind in der Datei bereits importiert; sonst ergänzen.)

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_reservations.py -k merge_phone -v`
Expected: FAIL — `AttributeError: 'ReservationStore' object has no attribute 'merge_phone'`.

- [ ] **Step 3: Implementation**

In `src/reservations.py` `import json` ergänzen, dann hinter `delete`:

```python
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

    def merge_phone(self, days: dict[str, Reservation]) -> bool:
        """Übernimmt vom Handy gesendete Tage per LWW. `days` ist bereits geprüft
        (`mobile_reservations.parse_reservations`). Ein Tag gewinnt nur mit einem
        **größeren** Schlüssel als der Desktop-Stand: dieselbe Anfrage zweimal ist
        damit ein No-op, ohne Schreiben und ohne Kalender-Abgleich. Der Zeitstempel
        bleibt der des Handys (`save` setzte `utc_now_iso()` — das Handy sendete den
        Tag beim nächsten Abgleich als neuer erkannt zurück).

        Slots erben `gcal_event_id` und `send_reminder_minutes` per Index (wie
        `save`). Ein Tombstone für einen unbekannten Tag wird verworfen: es gibt
        draußen nichts aufzuräumen. Geschrieben wird erst auf die Platte, dann
        in den Speicher — scheitert das Schreiben, bleibt der Stand unverändert.
        Liefert, ob sich etwas geändert hat."""
        with self._lock:
            merged = dict(self._data)
            changed = False
            for date, incoming in days.items():
                current = merged.get(date)
                if incoming.get("deleted") is True and current is None:
                    continue
                if current is not None and self._phone_key(incoming) <= self._phone_key(current):
                    continue
                if incoming.get("deleted") is True:
                    merged[date] = {"slots": [], "modified_at": incoming["modified_at"],
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
                    merged[date] = {"slots": new_slots, "modified_at": incoming["modified_at"],
                                    "deleted": False}
                changed = True
            if changed:
                atomic_write_json(self.filepath, merged)
                self._data = merged
            return changed
```

- [ ] **Step 4: Run to verify pass**

Run: `pytest tests/test_reservations.py -v`
Expected: PASS (alle, auch die bestehenden).

- [ ] **Step 5: Commit**

```bash
git add src/reservations.py tests/test_reservations.py
git commit -m "feat(reservierungen): ReservationStore.merge_phone — LWW mit Zeitstempel des Handys"
```

---

### Task 3: `mobile_reservations.py` — Fremddaten prüfen und Antwort bauen

**Files:**
- Create: `src/mobile_reservations.py`
- Modify: `tests/test_type_annotations.py` (Whitelist)
- Test: `tests/test_mobile_reservations.py`

**Interfaces:**
- Consumes: `api_entry_write.parse_slots`, `WriteError`; `mobile_sync.SyncError`/`CLOCK_SKEW_LIMIT` **nicht** (Zyklus: `mobile_sync` importiert dieses Modul) — deshalb bekommt `parse_reservations` die Fehlerklasse nicht, sondern wirft ein eigenes `ReservationError(label, reason)`, das `mobile_sync` in `SyncError(422, "invalid_entry", …)` übersetzt.
- Produces:
  - `MAX_RESERVATIONS = 400`, `HORIZON_DAYS = 365`
  - `class ReservationError(Exception)` mit `.message: str`
  - `parse_reservations(raw: object, *, today: datetime.date, now_dt: datetime.datetime, parse_utc: Callable[[object], datetime.datetime | None], skew_limit: datetime.timedelta) -> dict[str, dict[str, Any]]`
  - `build_reservations(store_raw: Mapping[str, Any], *, today: datetime.date) -> dict[str, dict[str, Any]]`

- [ ] **Step 1: Failing tests**

```python
# tests/test_mobile_reservations.py
import datetime

import pytest

from src import mobile_reservations as mr

TODAY = datetime.date(2026, 10, 13)
NOW = datetime.datetime(2026, 10, 13, 12, 0, 0)
SLOT = {"start": "09:00", "end": "12:00", "kategorie": "Projekt"}
STAMP = "2026-10-13T11:00:00Z"


def parse_utc(text):
    try:
        return datetime.datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ")
    except (TypeError, ValueError):
        return None


def parse(raw):
    return mr.parse_reservations(raw, today=TODAY, now_dt=NOW, parse_utc=parse_utc,
                                 skew_limit=datetime.timedelta(minutes=15))


def day(*slots, modified_at=STAMP, deleted=False, **extra):
    return {"slots": list(slots), "modified_at": modified_at, "deleted": deleted, **extra}


def test_a_valid_day_is_parsed_to_the_three_phone_fields():
    out = parse({"2026-10-20": day({**SLOT, "pause": 30})})

    assert out == {"2026-10-20": {"slots": [SLOT], "modified_at": STAMP, "deleted": False}}


def test_today_and_today_plus_365_are_allowed_and_the_day_after_is_not():
    last = (TODAY + datetime.timedelta(days=365)).isoformat()
    assert last in parse({TODAY.isoformat(): day(SLOT), last: day(SLOT)})
    with pytest.raises(mr.ReservationError):
        parse({(TODAY + datetime.timedelta(days=366)).isoformat(): day(SLOT)})


def test_a_day_before_today_is_rejected():
    with pytest.raises(mr.ReservationError) as excinfo:
        parse({(TODAY - datetime.timedelta(days=1)).isoformat(): day(SLOT)})
    assert "2026-10-12" in excinfo.value.message


@pytest.mark.parametrize("entry", [
    day(SLOT, send_reminder_minutes=15),               # Feld gehört dem Desktop
    day({**SLOT, "gcal_event_id": "x"}),               # ebenso
    day(),                                              # lebender Tag ohne Slots
    day(SLOT, deleted=True),                            # Tombstone mit Slots
    day(SLOT, modified_at="2026-10-13T12:20:00Z"),     # 20 Minuten in der Zukunft
    day(SLOT, modified_at="gestern"),
    day({**SLOT, "start": "25:00"}),
    "kein Objekt",
])
def test_a_bad_day_is_rejected(entry):
    with pytest.raises(mr.ReservationError):
        parse({"2026-10-20": entry})
```

Hinweis: `send_reminder_minutes` als Zusatzschlüssel **am Tag** (nicht am Slot) darf stillschweigend entfallen, wie `device_id` bei Ist-Zeiten (`test_a_valid_request_is_parsed_without_a_device_id`); am **Slot** lehnt `parse_slots` es ab (`invalid_slot`). Die erste Parameterzeile oben deshalb so schreiben, dass der Slot das Feld trägt:

```python
    day({**SLOT, "send_reminder_minutes": 15}),
```

(und die Zeile mit dem Tag-Feld in einen eigenen Test `test_unknown_day_fields_are_dropped` verschieben, der `out == {…}` ohne das Feld erwartet).

Weitere Tests:

```python
def test_a_tombstone_carries_no_slots():
    out = parse({"2026-10-20": day(deleted=True)})
    assert out["2026-10-20"] == {"slots": [], "modified_at": STAMP, "deleted": True}


def test_more_than_the_cap_is_rejected():
    start = TODAY
    raw = {(start + datetime.timedelta(days=i % 365)).isoformat() + ("" if i < 365 else f"x{i}"): day(SLOT)
           for i in range(mr.MAX_RESERVATIONS + 1)}
    with pytest.raises(mr.ReservationError):
        parse(raw)


def test_a_non_object_is_rejected():
    with pytest.raises(mr.ReservationError):
        parse(["2026-10-20"])


def test_build_returns_active_days_from_today_through_the_horizon_only():
    store = {
        "2026-10-12": {"slots": [dict(SLOT, gcal_event_id=None, send_reminder_minutes=None)],
                       "modified_at": STAMP, "deleted": False},          # gestern
        "2026-10-13": {"slots": [dict(SLOT, gcal_event_id="e", send_reminder_minutes=15)],
                       "modified_at": STAMP, "deleted": False},          # heute
        "2026-10-14": {"slots": [], "modified_at": STAMP, "deleted": True},   # Tombstone
        "2027-10-14": {"slots": [dict(SLOT)], "modified_at": STAMP, "deleted": False},  # > 365
    }

    out = mr.build_reservations(store, today=TODAY)

    assert out == {"2026-10-13": {"slots": [SLOT], "modified_at": STAMP, "deleted": False}}


def test_build_drops_unusable_slots_and_days_and_never_leaks_desktop_fields():
    store = {
        "2026-10-20": {"slots": [{"start": "09:00", "end": "kaputt", "kategorie": "x"},
                                 {"start": "10:00", "end": "11:00", "kategorie": 5,
                                  "gcal_event_id": "e"}],
                       "modified_at": STAMP, "deleted": False},
        "2026-10-21": {"slots": ["kein Objekt"], "modified_at": STAMP, "deleted": False},
        "kein-datum": {"slots": [dict(SLOT)], "modified_at": STAMP, "deleted": False},
    }

    out = mr.build_reservations(store, today=TODAY)

    assert out == {"2026-10-20": {"slots": [{"start": "10:00", "end": "11:00", "kategorie": ""}],
                                  "modified_at": STAMP, "deleted": False}}
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_mobile_reservations.py -v`
Expected: FAIL (`ModuleNotFoundError: src.mobile_reservations`).

- [ ] **Step 3: Implementation**

```python
# src/mobile_reservations.py
"""Reservierungen im Abgleich mit dem Handy (PR 2/3 von „Reservierungen ohne Google"),
Tk-frei und ohne I/O.

Zwei Dinge liegen hier, beide für `mobile_sync`:

- `parse_reservations`: der Teil `reservations` der Anfrage ist **Fremddaten**. Die
  Slot-Regeln sind die der Ist-Zeiten (`api_entry_write.parse_slots`); übernommen
  werden nur `start`, `end`, `kategorie` — `pause` gibt es bei Reservierungen nicht,
  `gcal_event_id` und `send_reminder_minutes` gehören dem Desktop und werden vom
  Slot-Parser als unbekannte Felder abgelehnt.
- `build_reservations`: die Antwort aus dem Store, nur aktive Tage von heute bis
  heute + `HORIZON_DAYS`, in derselben Form wie die Anfrage.

Den Merge macht `ReservationStore.merge_phone`; der Fehler hier ist ein
`ReservationError`, den `mobile_sync` in `SyncError(422, "invalid_entry", …)` übersetzt
(ein eigener Fehlercode brauchte einen Eintrag in `pwa/test/fixtures/errors.json`).
"""
from __future__ import annotations

import datetime
import re
from collections.abc import Callable, Mapping
from typing import Any

from src.api_entry_write import WriteError, parse_slots

MAX_RESERVATIONS = 400
HORIZON_DAYS = 365

_DATE_RE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
_CLOCK_RE = re.compile(r"([01]\d|2[0-3]):[0-5]\d")
_ECHO_MAX = 40


class ReservationError(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


def _label(date: object) -> str:
    # `ascii()` escaped auch Surrogate: die Meldung bleibt als UTF-8 schreibbar.
    return ascii(date)[1:-1][:_ECHO_MAX]


def _parse_day(date: str, raw: object, *, today: datetime.date, now_dt: datetime.datetime,
               parse_utc: Callable[[object], datetime.datetime | None],
               skew_limit: datetime.timedelta) -> dict[str, Any]:
    label = _label(date)

    def bad(reason: str) -> ReservationError:
        return ReservationError(f"Reservierung {label}: {reason}")

    if not _DATE_RE.fullmatch(date):
        raise bad("Datum muss YYYY-MM-DD sein.")
    try:
        day = datetime.date.fromisoformat(date)
    except ValueError:
        raise bad("kein gültiges Datum.") from None
    if not today <= day <= today + datetime.timedelta(days=HORIZON_DAYS):
        raise bad(f"nur von heute bis {HORIZON_DAYS} Tage voraus erlaubt.")
    if not isinstance(raw, dict):
        raise bad("Eintrag muss ein Objekt sein.")
    deleted = raw.get("deleted")
    if not isinstance(deleted, bool):
        raise bad("deleted muss true oder false sein.")
    modified = parse_utc(raw.get("modified_at"))
    if modified is None:
        raise bad("modified_at muss YYYY-MM-DDTHH:MM:SSZ sein.")
    if modified - now_dt > skew_limit:
        raise bad("modified_at liegt in der Zukunft.")
    slots_raw = raw.get("slots")
    if not isinstance(slots_raw, list):
        raise bad("slots muss eine Liste sein.")
    slots: list[dict[str, Any]] = []
    if deleted:
        if slots_raw:
            raise bad("Ein gelöschter Tag darf keine Slots tragen.")
    else:
        if not slots_raw:
            raise bad("Ein Tag ohne Slots ist gelöscht (deleted: true).")
        try:
            parsed = parse_slots(slots_raw)
        except WriteError as error:
            raise bad(error.message) from None
        slots = [{"start": s["start"], "end": s["end"], "kategorie": s["kategorie"]}
                 for s in parsed]
    return {"slots": slots, "modified_at": str(raw["modified_at"]), "deleted": deleted}


def parse_reservations(raw: object, *, today: datetime.date, now_dt: datetime.datetime,
                       parse_utc: Callable[[object], datetime.datetime | None],
                       skew_limit: datetime.timedelta) -> dict[str, dict[str, Any]]:
    """`reservations` der Anfrage → geprüfte Tage `{ISO: {slots, modified_at, deleted}}`.
    Wirft `ReservationError`; dann wurde nichts angewendet. `today` ist das lokale Datum
    des Desktops, `now_dt` seine UTC-Zeit."""
    if not isinstance(raw, dict):
        raise ReservationError("reservations muss ein Objekt sein.")
    if len(raw) > MAX_RESERVATIONS:
        raise ReservationError(f"Höchstens {MAX_RESERVATIONS} Reservierungstage je Anfrage.")
    # Unbekannte Felder am Tag (z. B. `device_id`) entfallen still, wie bei Ist-Zeiten.
    return {date: _parse_day(date, entry, today=today, now_dt=now_dt, parse_utc=parse_utc,
                             skew_limit=skew_limit)
            for date, entry in raw.items()}


def _clean_slots(raw: object) -> list[dict[str, str]]:
    """Gespeicherte Slots sind Fremddaten (Handbearbeitung, Kalender-Abgleich): nur die
    drei Felder des Protokolls, und nur mit gültiger Uhrzeit."""
    if not isinstance(raw, list):
        return []
    slots = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        start, end = item.get("start"), item.get("end")
        if not (isinstance(start, str) and _CLOCK_RE.fullmatch(start)
                and isinstance(end, str) and _CLOCK_RE.fullmatch(end)):
            continue
        category = item.get("kategorie")
        slots.append({"start": start, "end": end,
                      "kategorie": category if isinstance(category, str) else ""})
    return slots


def build_reservations(store_raw: Mapping[str, Any], *,
                       today: datetime.date) -> dict[str, dict[str, Any]]:
    """Alle aktiven Tage von heute bis heute + `HORIZON_DAYS`, sortiert. Tombstones und
    Tage ohne brauchbare Slots entfallen — ein Tag, der fehlt, löscht ihn in der PWA nur
    im Zukunftsfenster, ein Tombstone wäre dafür unnötig."""
    first = today.isoformat()
    last = (today + datetime.timedelta(days=HORIZON_DAYS)).isoformat()
    out: dict[str, dict[str, Any]] = {}
    for date in sorted(store_raw):
        entry = store_raw[date]
        if not (isinstance(date, str) and _DATE_RE.fullmatch(date) and first <= date <= last):
            continue
        if not isinstance(entry, dict) or entry.get("deleted") is True:
            continue
        slots = _clean_slots(entry.get("slots"))
        if not slots:
            continue
        out[date] = {"slots": slots, "modified_at": str(entry.get("modified_at") or ""),
                     "deleted": False}
    return out
```

> **Zu „Offene Entscheidung":** soll `parse_reservations` Tage vor heute stillschweigend verwerfen, ersetzt man in `_parse_day` die Bereichsprüfung durch `if day < today: return None` (und filtert `None` in der Dict-Komprehension). Der Test `test_a_day_before_today_is_rejected` wird dann zu `…_is_dropped`.

- [ ] **Step 4: Whitelist ergänzen und Tests laufen lassen**

In `tests/test_type_annotations.py` den Modulnamen `"mobile_reservations"` in die Whitelist aufnehmen (Schreibweise der vorhandenen Einträge übernehmen, z. B. neben `"mobile_sync"`).

Run: `pytest tests/test_mobile_reservations.py tests/test_type_annotations.py -v && ruff check src tests`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/mobile_reservations.py tests/test_mobile_reservations.py tests/test_type_annotations.py
git commit -m "feat(mobil): Reservierungen vom Handy prüfen und für die Antwort aufbereiten"
```

---

### Task 4: In `mobile_sync` einhängen

**Files:**
- Modify: `src/mobile_sync.py`
- Test: `tests/test_mobile_sync.py`, `tests/test_mobile_contract.py` (Test aus Task 1 Step 2 jetzt anlegen)

**Interfaces:**
- Consumes: `mobile_reservations.parse_reservations/build_reservations/ReservationError`, `ReservationStore.merge_phone`, `reservations.reservations_active(store, settings)`.
- Produces:
  - `SyncRequest.reservations: dict[str, dict[str, Any]] = field(default_factory=dict)`
  - `parse_request(body, *, now, today=None, accept_reservations=True)` — `today` Standard: UTC-Datum aus `now`; bei `accept_reservations=False` wird das Feld **gar nicht gelesen**.
  - `@dataclass class SyncReport: reservations_changed: bool = False`
  - `perform_sync(..., reservation_store=None, report=None)`
  - `build_response(..., reservations: Mapping[str, Any] | None = None)` — Schlüssel `reservations` nur, wenn nicht `None`.

- [ ] **Step 1: Failing tests** (`tests/test_mobile_sync.py`, Helfer `body`/`day`/`parse` existieren)

```python
RES = {"start": "09:00", "end": "12:00", "kategorie": "Projekt"}


def res_day(*, slots=(RES,), modified_at="2026-10-08T11:00:00Z", deleted=False):
    return {"slots": list(slots), "modified_at": modified_at, "deleted": deleted}


def test_reservations_are_parsed_next_to_the_entries():
    request = mobile_sync.parse_request(
        body({}, reservations={"2026-10-20": res_day()}), now=NOW, today=TODAY)

    assert request.reservations == {"2026-10-20": res_day()}


def test_a_request_without_reservations_has_none():
    assert parse({}).reservations == {}


def test_a_bad_reservation_is_422_invalid_entry_and_names_the_day():
    error = rejected(body({}, reservations={"2026-10-01": res_day()}))   # vor TODAY

    assert (error.status, error.code) == (422, "invalid_entry")
    assert "2026-10-01" in error.message


def test_the_clock_check_comes_before_the_reservations():
    error = rejected(body({}, client_time="2026-10-08T13:00:00Z",
                          reservations={"2026-10-01": res_day()}))

    assert error.code == "clock_skew"


def test_reservations_are_ignored_not_rejected_when_the_feature_is_off():
    request = mobile_sync.parse_request(
        body({}, reservations={"2026-10-01": res_day(), "x": 1}), now=NOW, today=TODAY,
        accept_reservations=False)

    assert request.reservations == {}
```

`perform_sync`-Tests: es gibt in der Datei eine Hilfsfunktion zum Aufbau von Storage/Settings/ConflictsStore (nach `grep -n "def sync\|def run\|perform_sync" tests/test_mobile_sync.py` das vorhandene Muster übernehmen und um `reservation_store` erweitern). Die Tests:

```python
def test_perform_sync_merges_reservations_and_returns_the_active_days(env):
    store = ReservationStore(os.path.join(env.base, "reservations.json"))
    env.settings.set_many({"reservations_enabled": True})
    request = mobile_sync.parse_request(
        body({}, reservations={"2026-10-20": res_day()}), now=NOW, today=TODAY)
    report = mobile_sync.SyncReport()

    response = env.sync(request, reservation_store=store, report=report)

    assert report.reservations_changed is True
    assert response["reservations"] == {"2026-10-20": res_day()}
    assert store.get("2026-10-20") is not None


def test_perform_sync_repeating_the_same_request_reports_no_change(env):
    ...  # zweimal dieselbe Anfrage; zweiter report.reservations_changed is False


def test_perform_sync_leaves_reservations_alone_when_the_feature_is_off(env):
    store = ReservationStore(os.path.join(env.base, "reservations.json"))      # Schalter aus
    request = mobile_sync.parse_request(
        body({}, reservations={"2026-10-20": res_day()}), now=NOW, today=TODAY)
    report = mobile_sync.SyncReport()

    response = env.sync(request, reservation_store=store, report=report)

    assert "reservations" not in response
    assert report.reservations_changed is False
    assert store.get_all_raw() == {}


def test_perform_sync_without_a_store_has_no_reservations_field(env):
    response = env.sync(parse({}))
    assert "reservations" not in response


def test_perform_sync_applies_entries_and_reservations_under_one_data_lock(env):
    ...  # data_lock = Spion-RLock, der mitzählt; beide Schreibvorgänge liegen innerhalb
```

(Die `env`-Fixture: falls keine existiert, in der Datei eine kleine anlegen, die `Storage`, `Settings`, `ConflictsStore` unter `tmp_path` baut und `sync(request, **extra)` als Wrapper um `perform_sync` mit den üblichen Parametern bereitstellt — die konkreten Parameter aus dem bestehenden Aufruf in dieser Datei übernehmen.)

Aus Task 1 Step 2 zusätzlich anlegen: `test_the_desktop_still_accepts_the_request_of_a_phone_without_reservations` in `tests/test_mobile_contract.py`.

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_mobile_sync.py tests/test_mobile_contract.py -v`
Expected: FAIL (fehlende Attribute/Parameter).

- [ ] **Step 3: Implementation**

In `src/mobile_sync.py`:

```python
from dataclasses import dataclass, field
...
from src import mobile_pairing, mobile_reservations, sync, sync_history, sync_journal
from src.reservations import reservations_active

if TYPE_CHECKING:
    ...
    from src.reservations import ReservationStore
```

`SyncRequest` erweitern:

```python
    window_days: int | None = None
    # {date: {slots, modified_at, deleted}} der Reservierungen; leer, wenn das Handy keine
    # sendet oder der Desktop sie nicht annimmt (`accept_reservations=False`).
    reservations: dict[str, dict[str, Any]] = field(default_factory=dict)


@dataclass
class SyncReport:
    """Was `perform_sync` außer der Antwort bewirkt hat — für den Aufrufer, der nach der
    Freigabe aller Sperren reagiert. Nicht Teil der Antwort ans Handy."""
    reservations_changed: bool = False
```

`parse_request` bekommt die zwei Parameter und, hinter den Einträgen:

```python
def parse_request(body: bytes, *, now: str, today: datetime.date | None = None,
                  accept_reservations: bool = True) -> SyncRequest:
    ...
    entries = {date: _parse_entry(date, raw, now_dt) for date, raw in raw_entries.items()}
    reservations: dict[str, dict[str, Any]] = {}
    if accept_reservations and "reservations" in data:
        try:
            reservations = mobile_reservations.parse_reservations(
                data["reservations"], today=today or now_dt.date(), now_dt=now_dt,
                parse_utc=_parse_utc, skew_limit=CLOCK_SKEW_LIMIT)
        except mobile_reservations.ReservationError as error:
            raise SyncError(422, "invalid_entry", error.message) from None
    wish = ...
    return SyncRequest(str(data["client_time"]), entries, window_days, reservations)
```

`build_response` bekommt `reservations: Mapping[str, Any] | None = None` und am Ende:

```python
    response = {...}      # das bestehende Dict
    if reservations is not None:
        response["reservations"] = dict(reservations)
    return response
```

(das bestehende `return {…}` in eine Variable umbauen.)

`perform_sync` bekommt `reservation_store: ReservationStore | None = None, report: SyncReport | None = None`. Im `with data_lock`-Block, direkt nach `apply_merged_doc_journaled`:

```python
            active = reservations_active(reservation_store, settings)
            if active and request.reservations:
                changed = reservation_store.merge_phone(request.reservations)
                if report is not None:
                    report.reservations_changed = changed
```

(Pyright: `reservation_store` ist hier nach `reservations_active` nicht eingegrenzt — `assert reservation_store is not None` oder `if reservation_store is not None and reservations_active(…)` schreiben.)

Nach dem Lock-Block, vor `build_response`:

```python
        reservations = (mobile_reservations.build_reservations(
            reservation_store.get_all_raw(), today=today) if active else None)
```

`active` vor dem `with` initialisieren (`active = False`), und `reservations=reservations` an `build_response` durchreichen. `get_all_raw` nimmt den Store-Lock selbst (derselbe `data_lock`), die Kopie ist flach — `build_reservations` liest nur.

- [ ] **Step 4: Run to verify pass**

Run: `pytest tests/test_mobile_sync.py tests/test_mobile_contract.py tests/test_mobile_reservations.py tests/test_reservations.py -v && ruff check . && pyright src/mobile_sync.py src/mobile_reservations.py src/reservations.py`
Expected: PASS, keine Fehler.

- [ ] **Step 5: Commit**

```bash
git add src/mobile_sync.py tests/test_mobile_sync.py tests/test_mobile_contract.py
git commit -m "feat(mobil): Reservierungen im Abgleich — parse, Merge unter data_lock, Antwortfeld"
```

---

### Task 5: Route, Context und UI verdrahten

**Files:**
- Modify: `src/mobile_routes.py` (`MobileContext`, `/v1/sync`-Handler, neuer `_notify_reservations`), `src/ui.py` (Context-Aufbau, neue Methode)
- Test: `tests/test_mobile_routes.py`, `tests/test_mobile_wiring.py`

**Interfaces:**
- Consumes: `mobile_sync.SyncReport`, `parse_request(today=, accept_reservations=)`, `perform_sync(reservation_store=, report=)`, `reservations_active`.
- Produces: `MobileContext.reservation_store: Any = None`, `MobileContext.on_reservations_change: Callable[[], None] = _no_change`; `App._on_mobile_reservations_changed()`.

- [ ] **Step 1: Failing tests**

In `tests/test_mobile_routes.py` das vorhandene Muster eines erfolgreichen Sync-Aufrufs (Helfer zum Koppeln und Senden per `grep -n "def .*sync" tests/test_mobile_routes.py`) nutzen:

```python
def test_a_sync_with_reservations_merges_them_and_reports_the_change_after_the_locks(ctx_env):
    calls = []
    ctx = ctx_env.context(reservation_store=ctx_env.reservations,
                          on_reservations_change=lambda: calls.append(ctx_env.locks_free()))
    ctx_env.settings.set_many({"reservations_enabled": True})

    status, payload = ctx_env.sync(ctx, reservations={"2026-10-20": RES_DAY})

    assert status == 200
    assert payload["reservations"]["2026-10-20"]["slots"][0]["start"] == "09:00"
    assert calls == [True]            # genau einmal, und erst nach Freigabe von Guard und Lock


def test_a_repeated_sync_does_not_report_a_second_change(ctx_env):
    ...  # zweimal dieselbe Anfrage (neues seq) → calls hat genau einen Eintrag


def test_a_rejected_reservation_is_an_encrypted_422_and_changes_nothing(ctx_env):
    ...  # Tag vor heute → status 422, error.code == "invalid_entry", Store leer, calls == []


def test_a_failing_reservation_hook_does_not_turn_the_sync_into_a_500(ctx_env):
    ...  # on_reservations_change wirft → Antwort bleibt 200
```

In `tests/test_mobile_wiring.py` (Quelltext-Test, Muster der Datei) ergänzen:

```python
def test_app_passes_the_reservation_store_and_the_hook_to_the_mobile_context():
    source = Path("src/ui.py").read_text(encoding="utf-8")
    assert "reservation_store=self.reservation_store" in source.split("MobileContext(")[1].split("run=self._bg.run")[0]
    assert "on_reservations_change=self._on_mobile_reservations_changed" in source
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_mobile_routes.py tests/test_mobile_wiring.py -v`
Expected: FAIL.

- [ ] **Step 3: Implementation**

`src/mobile_routes.py`: in `MobileContext` nach `sync_guard`

```python
    reservation_store: Any = None
```

und nach `on_change`

```python
    # Nach einem Abgleich, der Reservierungen verändert hat, außerhalb aller Sperren: die UI
    # stößt damit den Kalender-Abgleich an (falls aktiv).
    on_reservations_change: Callable[[], None] = _no_change
```

Im Handler (Zeile ~310):

```python
            reservations_on = reservations_active(ctx.reservation_store, ctx.settings)
            parsed = mobile_sync.parse_request(
                plain, now=now, today=ctx.today(), accept_reservations=reservations_on)
            report = mobile_sync.SyncReport()
            response = mobile_sync.perform_sync(
                parsed, ..., sync_guard=ctx.sync_guard,
                reservation_store=ctx.reservation_store, report=report)
```

`report` muss vor dem `try` existieren (`report = mobile_sync.SyncReport()` vor `try:`), damit der Code hinter dem Block darauf zugreifen kann. Nach `ctx.devices.save(renewed)` und der Freigabe der Sperren, neben `_notify(ctx)`:

```python
    if report.reservations_changed:
        _notify_reservations(ctx)
```

```python
def _notify_reservations(ctx: MobileContext) -> None:
    try:
        ctx.on_reservations_change()
    except Exception:
        # Der Abgleich ist angewendet und gespeichert; ein Fehler beim Anstoßen des
        # Kalender-Abgleichs darf daraus keine 500 machen (das Handy wiederholte ihn).
        _log.exception("Handy-Abgleich: on_reservations_change fehlgeschlagen")
```

Import `from src.reservations import reservations_active`. Die Stelle `notify = True`/`_notify` nach Zeile ~335 prüfen: `report` muss dort im Scope sein (gleiche Funktion).

`src/ui.py`: im `MobileContext(...)`-Aufruf

```python
                    data_lock=self._data_lock, sync_guard=self._sync_guard,
                    reservation_store=self.reservation_store,
                    on_change=self._api_refresh.request,
                    on_reservations_change=self._on_mobile_reservations_changed),
```

und neben `_on_vacation_change`:

```python
    def _on_mobile_reservations_changed(self):
        """Das Handy hat Reservierungen verändert: Kalender-Push anstoßen. Läuft im
        Server-Thread, deshalb über `_marshal_to_ui`; `trigger_reconcile` gatet selbst
        auf `gcal_enabled` und den Reservierungs-Store. Das Neuzeichnen kommt schon
        über `on_change`."""
        self._marshal_to_ui(lambda: self._bg.trigger_reconcile(self._on_reconcile_done))
```

(`_bg` wird vor dem `MobileContext` gebaut — `run=self._bg.run` steht im selben Aufruf; die Methode wird erst später aufgerufen.)

- [ ] **Step 4: Run to verify pass**

Run: `pytest tests/test_mobile_routes.py tests/test_mobile_wiring.py tests/test_ui_delete.py -v && ruff check .`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/mobile_routes.py src/ui.py tests/test_mobile_routes.py tests/test_mobile_wiring.py
git commit -m "feat(mobil): Route reicht den Reservierungs-Store durch und stößt den Kalender-Abgleich an"
```

---

### Task 6: Live-Vertragsbeispiele und Contract-Tests

**Files:**
- Modify: `pwa/test/fixtures/sync-request.json`, `pwa/test/fixtures/sync-response.json`, `tests/test_mobile_contract.py`

Die eingefrorenen Dateien aus Task 1 bleiben unangetastet.

- [ ] **Step 1: Failing tests**

```python
def test_the_live_request_example_carries_reservations_the_server_reads():
    example = load("sync-request.json")
    assert example["reservations"]

    parsed = mobile_sync.parse_request(
        json.dumps(example).encode(), now=example["client_time"],
        today=datetime.date.fromisoformat(example["client_time"][:10]))

    assert sorted(parsed.reservations) == sorted(example["reservations"])


def test_the_live_response_example_has_the_shape_build_reservations_emits():
    example = load("sync-response.json")
    today = datetime.date.fromisoformat(example["server_time"][:10])

    rebuilt = mobile_reservations.build_reservations(
        {d: {**v, "deleted": False} for d, v in example["reservations"].items()}, today=today)

    assert rebuilt == example["reservations"]
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_mobile_contract.py -v`
Expected: FAIL (`KeyError: 'reservations'`).

- [ ] **Step 3: Beispiele erweitern**

`sync-request.json` (client_time `2026-10-08T12:00:00Z`) um

```json
  "reservations": {
    "2026-10-15": {
      "slots": [{"start": "09:00", "end": "12:00", "kategorie": "Projekt"}],
      "modified_at": "2026-10-07T18:40:00Z",
      "deleted": false
    },
    "2026-10-16": {
      "slots": [],
      "modified_at": "2026-10-07T18:41:00Z",
      "deleted": true
    }
  }
```

`sync-response.json` um

```json
  "reservations": {
    "2026-10-15": {
      "slots": [{"start": "09:00", "end": "12:00", "kategorie": "Projekt"}],
      "modified_at": "2026-10-07T18:40:00Z",
      "deleted": false
    }
  }
```

(Einrückung und Reihenfolge wie die vorhandene Datei; das Formatierungsmuster der JSON-Dateien beibehalten.)

- [ ] **Step 4: Gesamtlauf inklusive PWA-Tests**

Die PWA liest diese Fixtures in ihren eigenen Tests; unbekannte Felder müssen dort ignoriert werden (Regel 1).

Run: `pytest -q --ignore=tests/test_qr.py && (cd pwa && node --test) && ruff check . && pyright`
Expected: alles PASS. Schlägt ein PWA-Test wegen des neuen Feldes fehl, ist das ein echter Kompatibilitätsbefund: **nicht** die PWA hier anpassen (das ist PR 3), sondern melden.

- [ ] **Step 5: Commit**

```bash
git add pwa/test/fixtures/sync-request.json pwa/test/fixtures/sync-response.json tests/test_mobile_contract.py
git commit -m "test(mobil): Vertragsbeispiele um Reservierungen erweitert"
```

---

### Task 7: Doku

**Files:**
- Modify: `src/CLAUDE.md` (Absatz `mobile_sync.py` unter „Daten- & Persistenz-Schicht" und `mobile_routes.py`), `pwa/CLAUDE.md` (Abschnitt „Kompatibilität", Regel 4: dritten eingefrorenen Stand nennen), `CLAUDE.md` (Zeilen zu `mobile_sync.py` und neuer Eintrag `mobile_reservations.py`)

- [ ] **Step 1: `src/CLAUDE.md`**

Im `mobile_sync.py`-Absatz ergänzen: Reservierungen reisen additiv mit (`reservations`, `PROTOCOL` 2 bleibt); `parse_request` liest sie nur mit `accept_reservations` (die Route übergibt `reservations_active`); Merge über `ReservationStore.merge_phone` unter demselben `data_lock` wie die Ist-Zeiten, mit dem Zeitstempel des Handys; `build_response` trägt das Feld nur bei aktivem Schalter; `SyncReport.reservations_changed` löst nach Freigabe der Sperren `on_reservations_change` aus (Kalender-Push). Im `mobile_routes.py`-Absatz `reservation_store`/`on_reservations_change` erwähnen.

- [ ] **Step 2: `pwa/CLAUDE.md`**

In Regel 4 den Stand „vor den Reservierungen (`compat/*-pre-reservations.json`, ohne `reservations`)" anfügen.

- [ ] **Step 3: Wurzel-`CLAUDE.md`**

Zeile `src/mobile_sync.py` um „und der Reservierungs-Teil (`reservations`)" ergänzen; neue Zeile `src/mobile_reservations.py — …` direkt dahinter (Fremddaten-Prüfung und Antwortaufbau der Reservierungen, Tk-frei).

- [ ] **Step 4: Prüfen**

Run: `pytest tests/test_claude_md_claims.py -q && ruff check .`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add CLAUDE.md src/CLAUDE.md pwa/CLAUDE.md
git commit -m "docs(mobil): Reservierungen im Handy-Abgleich"
```

---

## Abschluss

- [ ] Vollständiger Lauf: `pytest -q --ignore=tests/test_qr.py` (lokal fehlt `segno`), `ruff check .`, `pyright`, `(cd pwa && node --test)`.
- [ ] Manuell mit `tests/mobile_phone.py` (existiert als Handy-Simulator): Reservierungen senden, in der App sichtbar, zurück-synchronisieren. UI wird nicht automatisiert getestet (Scope-Grenze).
- [ ] PR gegen `master`, Titel `feat(reservierungen): Reservierungen im Handy-Abgleich (PR 2/3: Protokoll)`, kein `release:*`-Label (PR 3 und der Release-Bump folgen). Kein Plattform-Label: nichts plattformspezifisch.

## Self-Review

- **Spec-Abdeckung:** Einfrieren → T1; Anfrageform/Prüfungen → T3/T4; Merge LWW + Ids per Index + Tombstone → T2; Antwort + Gate + Budget → T3/T4 (Reservierungen laufen an `fit_window`/`sizes` vorbei, weil sie nicht in `entries` liegen); ignorieren bei aus → T4; `on_change`/Kalender-Abgleich → T5; Tests/Fixtures/Lock-Reihenfolge → T4–T6; Doku → T7.
- **Platzhalter-Scan:** In T4 und T5 verweisen drei Testrümpfe (`...`) auf das vorhandene Fixture-Muster der Testdateien, dessen Aufbau ich beim Schreiben nicht ausgelesen habe; der Ausführende liest die Datei zuerst (`grep` steht im Schritt). Das ist die einzige Lücke, sie ist benannt.
- **Typkonsistenz:** `merge_phone(days) -> bool`, `SyncReport.reservations_changed`, `parse_reservations(...) -> dict`, `build_reservations(store_raw, *, today)`, `ReservationError.message` werden in allen Tasks gleich verwendet.
