# Mobile Erfassung, PR 3 von 8: `mobile_sync` — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Der fachliche Kern von `POST /v1/sync` (#221): das Handy-Dokument prüfen, durch `sync.merge` schicken, über die journalisierte Pipeline anwenden und die Antwort bauen. Noch kein Server, keine Routen, keine UI.

**Architecture:** `mobile_sync.py` ist Tk-frei und ohne Socket. `parse_request` macht aus dem Body geprüfte Einträge (Fremddaten!), `build_response` ist eine reine Funktion über das Merge-Ergebnis, `perform_sync` klammert Guard und `data_lock` und ruft `sync.build_local_doc` → `sync.merge` → `sync_journal.apply_merged_doc_journaled`. Die Slot-Regeln sind die der lokalen API (`api_entry_write`), dafür werden dort zwei Helfer öffentlich (`parse_slots`, `load_json_body`). Token, Gerätedatensatz und `last_pull_at` des Handys gehören der Route (PR 4): `perform_sync` bekommt sie als Parameter und liefert die Antwort **ohne** `token`/`expires_at`.

**Tech Stack:** Python 3.12, stdlib. Keine neue Abhängigkeit.

**Spec:** `docs/superpowers/specs/2026-10-08-mobile-pwa-design.md` (Abschnitt „Protokoll", `POST /v1/sync`, Schritte 1–5). PR 3 des PR-Zuschnitts dort.

**Voraussetzung:** PR 2 (#252, `mobile_pairing`/`mobile_store`) ist gemergt. `mobile_sync` importiert aus beiden nichts; die Doku-Edits in Task 5 haken aber an Texten an, die #252 mitbringt.

**Branching:** `feat/mobile-sync` vom dann aktuellen `master`; der PR zielt auf `master`, trägt `Refs #221`, kein `Closes`. Kein Versionsbump.

## Rulings aus der Planung

- **Die Uhr wird vor den Einträgen geprüft** (die Spec nennt die Reihenfolge Prüfen → Uhr). Geht die Handy-Uhr eine Stunde vor, tragen ihre `modified_at` Zukunftswerte; mit der Spec-Reihenfolge käme dann `422 invalid_entry` statt des hilfreichen `409 clock_skew`. Die Spec wird in Task 5 nachgezogen.
- **`modified_at` darf höchstens 15 Minuten in der Zukunft liegen** (`CLOCK_SKEW_LIMIT`, `422 invalid_entry`). Die Spec schweigt dazu. Ohne die Grenze gewänne ein Eintrag mit `modified_at` im Jahr 2099 jeden späteren LWW-Vergleich dauerhaft, auch wenn `client_time` stimmt.
- **Die Geräte-ID kommt nie aus dem Body.** `parse_request` übernimmt nur `slots`, `modified_at`, `deleted`; `perform_sync` setzt `device_id` aus dem Token. Ein Handy kann damit nicht als anderes Gerät schreiben.
- **Ein Tag ohne Slots muss `deleted: true` sein, ein gelöschter Tag muss `slots: []` tragen.** Sonst entstünde ein „lebender" Tag ohne Inhalt oder ein Tombstone mit Daten.
- **Nach jedem erfolgreichen Abgleich `sync_history.mark_synced(base)`.** Der Startup-Sweep (`main._sweep_orphan_tombstones`) verwirft Tombstones auf Rechnern, die „nie gesynct" haben. Ein Rechner, der nur mit dem Handy abgleicht, hätte sonst nach dem nächsten Start keine Tombstones mehr, und ein am Desktop gelöschter Tag käme vom Handy zurück. Die Wurzel-`CLAUDE.md` verlangt das ausdrücklich: „Ein neuer Sync/Reconcile-Pfad muss ihn mitsetzen." Preis: Tombstones bleiben dann bis zu einer Kompaktierung liegen (die hängt am Google-Tab).
- **Das Antwortfenster nimmt auch die vom Handy gesendeten Tage mit**, Einträge wie offene Konflikte (die Spec sagt es nur für die Einträge). Ein Konflikt auf einem Tag außerhalb der 90 Tage bliebe sonst unsichtbar.
- **Ein gesendeter Tag, der im Merge-Ergebnis fehlt** (Self-Heal bei `excluded`), steht nicht in der Antwort. Das Handy erkennt ihn am Flag `excluded: true`; das Verhalten der PWA ist Sache von PR 6.
- **Die Stempel der gesendeten Tage werden auf `last_pull_at + 1 s` angehoben** (Befund des Reviews): der Merge vergleicht `modified_at` (Handy-Uhr) mit `last_pull_at` (Desktop-Uhr); bei einem nachgehenden Handy verlöre eine Änderung nach dem Abgleich still gegen die Desktop-Version. Bei `excluded` bleiben die Stempel unangetastet (Self-Heal).
- **Die Antwort sanitisiert alles, was vom Desktop kommt** (`storage.sanitize_slot`, nur die vier Slot-Felder): gespeicherte Slots sind Fremddaten aus dem Drive-Sync.
- **`on_change` (UI-Refresh) ruft die Route**, nicht `perform_sync`: es soll nach Freigabe von Guard und Lock laufen.

## Global Constraints

- Tk-frei, stdlib-only, vollständig annotiert (`src/mobile_sync.py` kommt in `ANNOTATED_MODULES`); `ruff check .` und `pyright 1.1.411` sauber.
- Alle Zeitstempel im festen Format `YYYY-MM-DDTHH:MM:SSZ` (`time_utils.utc_now_iso`); Daten ISO mit ASCII-Ziffern, Jahr 2000–2100.
- Kein `except Exception`; `except` nur eng (`ValueError`, `WriteError`) und mit Begründung. Weder Slot-Inhalte noch Kategorien im Log.
- Jede Ablehnung hat die Form `SyncError(status, code, message)` aus der Statuscode-Liste der Spec (`400 invalid_json|invalid_protocol`, `409 clock_skew`, `422 invalid_entry`, `503 busy`); bei einer Ablehnung wird nichts angewendet.
- Der Sync-Guard (`sync_guard`) wird nicht-blockierend genommen und im `finally` desselben Threads freigegeben, der `data_lock` nie über etwas anderes als Snapshot → Merge → Apply gehalten.

## Review Focus

1. **Fremdes JSON:** Datum `2026-02-30`, `٢٠٢٦-١٠-٠٧`, `20261007`, Jahr 1999/2101, 401 Tage, doppelte Schlüssel, Lone Surrogate im Datumsschlüssel, 100 000 verschachtelte `[`, `NaN` → immer 4xx mit Text, nie 500, nie etwas angewendet. Task 2.
2. **Uhr:** Handy eine Stunde vor → `409 clock_skew` (nicht `invalid_entry`); `modified_at` 15 min 1 s in der Zukunft → `422`. Task 2.
3. **Identität:** `device_id` im Body wird ignoriert, im Store steht die ID aus dem Token. Task 4.
4. **Wiederholung und Erstabgleich:** derselbe Request zweimal erzeugt keinen zweiten Konflikt; `last_pull_at` leer + abweichender Tag = genau ein Konflikt. Task 4.
5. **Zu lange offline:** `last_pull_at` vor dem `gc_watermark` des Desktops → ein gesendeter, alter lebender Tag wird nicht wiederbelebt, `excluded: true`. Task 4.
6. **Fehler mitten im Apply:** der Guard ist danach frei, das Journal bleibt für die Recovery. Task 4.
7. **Antwort aus Fremddaten:** ein Desktop-Slot mit `pause: "abc"` und Zusatzfeldern kommt als `pause: 0` und nur mit den vier Feldern an. Task 3.

---

### Task 1: Öffentliche Helfer in `api_entry_write`

**Files:**
- Modify: `src/api_entry_write.py`
- Test: `tests/test_api_entry_write.py` (existiert nicht? dann `tests/test_mobile_sync.py` verwenden — s. Step 1)

**Interfaces:** Produces: `load_json_body(body: bytes) -> Any` (vorher `_load_json`, Verhalten unverändert), `parse_slots(raw: list[Any]) -> list[dict[str, Any]]` (wirft `WriteError` 422: `too_many_slots`, `invalid_slot`, `invalid_time`, `invalid_pause`, `invalid_category`, `invalid_slots`). `parse_day_body` ruft `parse_slots`.

- [ ] **Step 1: Write the failing tests**

Prüfe, ob `tests/test_api_entry_write.py` existiert (`ls tests | grep entry_write`). Wenn ja, hänge die Tests dort an, sonst lege `tests/test_api_entry_write.py` mit dem Kopf `import pytest` an.

```python
from src import api_entry_write as w


def test_parse_slots_returns_checked_slots_with_all_four_fields():
    slots = w.parse_slots([{"start": "08:00", "end": "12:00"}])
    assert slots == [{"start": "08:00", "end": "12:00", "pause": 0, "kategorie": ""}]


@pytest.mark.parametrize("raw,code", [
    ([{"start": "8:00", "end": "12:00"}], "invalid_time"),
    ([{"start": "08:00", "end": "12:00", "pause": -1}], "invalid_pause"),
    ([{"start": "08:00", "end": "12:00", "x": 1}], "invalid_slot"),
    ([{"start": "08:00", "end": "12:00"}, {"start": "11:00", "end": "13:00"}], "invalid_slots"),
    ([{"start": "00:00", "end": "00:01"}] * (w.MAX_SLOTS + 1), "too_many_slots"),
])
def test_parse_slots_rejects_with_a_write_error(raw, code):
    with pytest.raises(w.WriteError) as excinfo:
        w.parse_slots(raw)
    assert excinfo.value.status == 422 and excinfo.value.code == code


def test_load_json_body_is_strict():
    assert w.load_json_body(b'{"a": 1}') == {"a": 1}
    for body in (b"{kaputt", b'{"a": NaN}', b'{"a": 1, "a": 2}', b"[" * 100000, b"\xff"):
        with pytest.raises(w.WriteError):
            w.load_json_body(body)
```

- [ ] **Step 2: Run to verify they fail**

Run: `python3 -m pytest tests/test_api_entry_write.py -q -p no:cacheprovider -x`
Expected: FAIL: `AttributeError: module 'src.api_entry_write' has no attribute 'parse_slots'`.

- [ ] **Step 3: Implement**

In `src/api_entry_write.py` ersetze `def _load_json(body: bytes) -> Any:` durch `def load_json_body(body: bytes) -> Any:` und `data = _load_json(body)` durch `data = load_json_body(body)`. Prüfe vorher mit `grep -rn "_load_json" src tests`, dass sonst niemand den alten Namen nutzt (Treffer anpassen).

Ersetze in `parse_day_body` den Block

```python
    if len(raw) > MAX_SLOTS:
        raise WriteError(422, "too_many_slots", f"Höchstens {MAX_SLOTS} Slots je Tag.")
    slots = [_parse_slot(item, i + 1) for i, item in enumerate(raw)]
    ok, message = validate_slots(slots, with_pause=True)
    if not ok:
        raise WriteError(422, "invalid_slots", message)
    return slots
```

durch

```python
    return parse_slots(raw)
```

und füge **vor** `def parse_day_body` ein:

```python
def parse_slots(raw: list[Any]) -> list[dict[str, Any]]:
    """Geprüfte Slots (`{start, end, pause, kategorie}`, alle vier Felder) aus einer
    Liste von Fremddaten. Wirft `WriteError` 422. Eine leere Liste ist hier gültig;
    ob ein Tag ohne Slots erlaubt ist, entscheidet der Aufrufer."""
    if len(raw) > MAX_SLOTS:
        raise WriteError(422, "too_many_slots", f"Höchstens {MAX_SLOTS} Slots je Tag.")
    slots = [_parse_slot(item, i + 1) for i, item in enumerate(raw)]
    ok, message = validate_slots(slots, with_pause=True)
    if not ok:
        raise WriteError(422, "invalid_slots", message)
    return slots
```

- [ ] **Step 4: Run to verify they pass**

Run: `python3 -m pytest tests/test_api_entry_write.py -q -p no:cacheprovider` und danach `python3 -m pytest -q -p no:cacheprovider && ruff check .`
Expected: PASS (die bestehenden API-Tests bleiben grün), `All checks passed!`.

- [ ] **Step 5: Commit**

~~~bash
git add src/api_entry_write.py tests/test_api_entry_write.py
git commit -m "refactor(api): parse_slots und load_json_body öffentlich (#221)

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
~~~

---

### Task 2: `parse_request` — Body → geprüfte Einträge

**Files:**
- Create: `src/mobile_sync.py`
- Create: `tests/test_mobile_sync.py`

**Interfaces:** Consumes: `api_entry_write.load_json_body`, `parse_slots`, `check_date_range`, `WriteError`. Produces: `PROTOCOL = 1`, `WINDOW_DAYS = 90`, `MAX_ENTRIES = 400`, `CLOCK_SKEW_LIMIT` (`timedelta(minutes=15)`), `SyncError(status, code, message)` mit Attributen `.status/.code/.message`, `SyncRequest(client_time: str, entries: dict[str, dict[str, Any]])` (frozen dataclass; `entries[date] = {"slots", "modified_at", "deleted"}` — **kein** `device_id`), `parse_request(body: bytes, *, now: str) -> SyncRequest`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_mobile_sync.py`:

```python
# tests/test_mobile_sync.py
import datetime
import json
import threading
import types

import pytest

from src import mobile_sync, sync_history, sync_journal
from src.conflicts_store import ConflictsStore
from src.mobile_sync import SyncError
from src.settings import Settings
from src.storage import Storage

NOW = "2026-10-08T12:00:00Z"
TODAY = datetime.date(2026, 10, 8)
SLOT = {"start": "08:00", "end": "12:00", "pause": 0, "kategorie": "Projekt"}


def body(entries=None, **over):
    doc = {"protocol": 1, "client_time": NOW, "last_pull_at": "", "entries": entries or {}}
    doc.update(over)
    return json.dumps(doc).encode()


def day(*, slots=(SLOT,), modified_at="2026-10-07T18:30:00Z", deleted=False, **extra):
    return {"slots": list(slots), "modified_at": modified_at, "deleted": deleted, **extra}


def tomb(modified_at="2026-10-07T18:30:00Z"):
    return day(slots=(), modified_at=modified_at, deleted=True)


def parse(entries=None, **over):
    return mobile_sync.parse_request(body(entries, **over), now=NOW)


def rejected(raw_body):
    with pytest.raises(SyncError) as excinfo:
        mobile_sync.parse_request(raw_body, now=NOW)
    return excinfo.value


# --- Form des Requests ------------------------------------------------------------------------

def test_a_valid_request_is_parsed_without_a_device_id():
    request = parse({"2026-10-07": day(device_id="evil"), "2026-10-06": tomb()})

    assert request.client_time == NOW
    assert request.entries["2026-10-07"] == {
        "slots": [SLOT], "modified_at": "2026-10-07T18:30:00Z", "deleted": False}
    assert request.entries["2026-10-06"] == {
        "slots": [], "modified_at": "2026-10-07T18:30:00Z", "deleted": True}


def test_a_request_without_entries_is_fine():
    doc = json.loads(body())
    del doc["entries"]
    assert mobile_sync.parse_request(json.dumps(doc).encode(), now=NOW).entries == {}


@pytest.mark.parametrize("raw", [
    b"{kaputt", b"[]", b'"text"', b"\xff", b'{"protocol": NaN}', b"[" * 100000,
    body(client_time="gestern"), body(client_time=None), body(client_time="2026-10-08 12:00:00"),
    body(entries=[]), body(entries="x"),
    b'{"protocol":1,"client_time":"' + NOW.encode() + b'","entries":{"2026-10-07":{},"2026-10-07":{}}}',
])
def test_a_malformed_request_is_400_invalid_json(raw):
    error = rejected(raw)
    assert (error.status, error.code) == (400, "invalid_json") and error.message


@pytest.mark.parametrize("protocol", [None, 0, 2, "1", 1.0, True, [1]])
def test_a_wrong_protocol_is_400_invalid_protocol(protocol):
    error = rejected(body(protocol=protocol))
    assert (error.status, error.code) == (400, "invalid_protocol")


def test_a_missing_protocol_is_400_invalid_protocol():
    doc = json.loads(body())
    del doc["protocol"]
    assert rejected(json.dumps(doc).encode()).code == "invalid_protocol"


# --- Uhr ---------------------------------------------------------------------------------------------

@pytest.mark.parametrize("client_time,ok", [
    ("2026-10-08T12:15:00Z", True), ("2026-10-08T11:45:00Z", True),
    ("2026-10-08T12:15:01Z", False), ("2026-10-08T11:44:59Z", False),
])
def test_the_clock_skew_limit_is_fifteen_minutes(client_time, ok):
    if ok:
        assert parse(client_time=client_time).client_time == client_time
    else:
        error = rejected(body(client_time=client_time))
        assert (error.status, error.code) == (409, "clock_skew")


def test_a_skewed_clock_is_reported_as_skew_not_as_an_invalid_entry():
    late = "2026-10-08T13:00:00Z"
    error = rejected(body({"2026-10-08": day(modified_at=late)}, client_time=late))
    assert (error.status, error.code) == (409, "clock_skew")


@pytest.mark.parametrize("modified_at,ok", [
    ("2026-10-08T12:15:00Z", True), ("2026-10-08T12:15:01Z", False),
])
def test_a_modified_at_in_the_future_is_rejected(modified_at, ok):
    entries = {"2026-10-08": day(modified_at=modified_at)}
    if ok:
        assert parse(entries).entries["2026-10-08"]["modified_at"] == modified_at
    else:
        assert rejected(body(entries)).code == "invalid_entry"


# --- Einträge ----------------------------------------------------------------------------------------

@pytest.mark.parametrize("key", [
    "2026-02-30", "20261007", "2026-10-7", "٢٠٢٦-١٠-٠٧", "1999-12-31", "2101-01-01",
    "2026-10-07 ", "", "\ud800", "x" * 5000,
])
def test_a_bad_date_key_is_422_with_the_date_in_the_message(key):
    error = rejected(body({key: day()}))
    assert (error.status, error.code) == (422, "invalid_entry")
    error.message.encode("utf-8")                       # nie ein Surrogat in der Antwort
    assert len(error.message) < 200


@pytest.mark.parametrize("entry", [
    5, None, [], "x",
    {"slots": [SLOT], "modified_at": "2026-10-07T18:30:00Z"},                              # deleted fehlt
    day(deleted="nein"), day(deleted=1),
    day(modified_at="2026-10-07 18:30:00"), day(modified_at="2026-10-07T18:30:00+00:00"),
    day(modified_at="٢026-10-07T18:30:00Z"), day(modified_at=None), day(modified_at="2026-13-07T18:30:00Z"),
    {"slots": "x", "modified_at": "2026-10-07T18:30:00Z", "deleted": False},
    day(slots=()),                                                  # lebender Tag ohne Slots
    day(slots=(SLOT,), deleted=True),                               # Tombstone mit Slots
    day(slots=({"start": "09:00", "end": "08:00"},)),
    day(slots=({"start": "08:00", "end": "12:00", "pause": "x"},)),
    day(slots=({"start": "08:00", "end": "12:00", "kategorie": "a\x00b"},)),
    day(slots=({"start": "08:00", "end": "12:00", "extra": 1},)),
    day(slots=({"start": "08:00", "end": "10:00"}, {"start": "09:00", "end": "11:00"})),
    day(slots=({"start": "00:00", "end": "00:01"},) * 51),
])
def test_a_bad_entry_is_422_invalid_entry(entry):
    error = rejected(body({"2026-10-07": entry}))
    assert (error.status, error.code) == (422, "invalid_entry")
    assert error.message.startswith("2026-10-07:")


def test_one_bad_day_rejects_the_whole_request():
    error = rejected(body({"2026-10-07": day(), "2026-10-06": day(slots=())}))
    assert error.code == "invalid_entry"


def test_at_most_400_days_per_request():
    dates = [(TODAY - datetime.timedelta(days=i)).isoformat() for i in range(401)]
    assert len(parse({d: day() for d in dates[:400]}).entries) == 400
    error = rejected(body({d: day() for d in dates}))
    assert (error.status, error.code) == (422, "invalid_entry")
```

- [ ] **Step 2: Run to verify they fail**

Run: `python3 -m pytest tests/test_mobile_sync.py -q -p no:cacheprovider -x`
Expected: ERROR beim Sammeln: `ImportError: cannot import name 'mobile_sync' from 'src'`.

- [ ] **Step 3: Implement**

Create `src/mobile_sync.py`:

```python
# src/mobile_sync.py
"""Fachlicher Kern von `POST /v1/sync` der Handy-Erfassung (#221), Tk-frei, ohne Socket.

Drei Dinge liegen hier:

- `parse_request`: der Body vom Handy ist **Fremddaten**. Er wird mit denselben
  Regeln wie `PUT /v1/entries` geprüft (`api_entry_write`), dazu Datum, Zeitstempel,
  Tag-Obergrenze und die Uhr. Eine Ablehnung ist ein `SyncError`; dann wurde
  nichts angewendet.
- `build_response`: die Antwort aus dem Merge-Ergebnis (Lesefenster, offene
  Konflikte). Rein.
- `perform_sync`: Guard und Lock, `sync.merge` mit dem Handy als `local`, die
  journalisierte Anwendung. Token, Gerätedatensatz und `last_pull_at` des Handys
  gehören der Route: sie kommen als Parameter herein, die Antwort enthält
  `token`/`expires_at` **nicht**.

Es gibt keinen Merge in JavaScript und keinen zweiten hier: Konfliktlogik bleibt
`sync.merge`.
"""
from __future__ import annotations

import datetime
import re
from dataclasses import dataclass
from typing import Any

from src.api_entry_write import WriteError, check_date_range, load_json_body, parse_slots

PROTOCOL = 1
WINDOW_DAYS = 90
MAX_ENTRIES = 400
# LWW vertraut `modified_at`: eine falsche Uhr würde echte Einträge überschreiben.
CLOCK_SKEW_LIMIT = datetime.timedelta(minutes=15)

_TIME_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
# Nur ASCII-Ziffern: `\d` matcht auch andere Schriften.
_TIME_RE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z")
_DATE_RE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
_ECHO_MAX = 40


class SyncError(Exception):
    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


@dataclass(frozen=True)
class SyncRequest:
    client_time: str
    # {date: {slots, modified_at, deleted}} — bewusst ohne `device_id`: die setzt
    # `perform_sync` aus dem Token, nie aus dem Body.
    entries: dict[str, dict[str, Any]]


def _parse_utc(text: object) -> datetime.datetime | None:
    if not isinstance(text, str) or not _TIME_RE.fullmatch(text):
        return None
    try:
        return datetime.datetime.strptime(text, _TIME_FORMAT)
    except ValueError:
        return None


def _parse_entry(date: str, raw: object, now_dt: datetime.datetime) -> dict[str, Any]:
    # `ascii()` escaped auch Surrogate: die Meldung bleibt als UTF-8 schreibbar.
    label = ascii(date)[1:-1][:_ECHO_MAX]

    def bad(reason: str) -> SyncError:
        return SyncError(422, "invalid_entry", f"{label}: {reason}")

    if not _DATE_RE.fullmatch(date):
        raise bad("Datum muss YYYY-MM-DD sein.")
    try:
        day = datetime.date.fromisoformat(date)
    except ValueError:
        raise bad("kein gültiges Datum.") from None
    try:
        check_date_range(day)
    except WriteError as error:
        raise bad(error.message) from None
    if not isinstance(raw, dict):
        raise bad("Eintrag muss ein Objekt sein.")
    deleted = raw.get("deleted")
    if not isinstance(deleted, bool):
        raise bad("deleted muss true oder false sein.")
    modified = _parse_utc(raw.get("modified_at"))
    if modified is None:
        raise bad("modified_at muss YYYY-MM-DDTHH:MM:SSZ sein.")
    if modified - now_dt > CLOCK_SKEW_LIMIT:
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
            slots = parse_slots(slots_raw)
        except WriteError as error:
            raise bad(error.message) from None
    return {"slots": slots, "modified_at": str(raw["modified_at"]), "deleted": deleted}


def parse_request(body: bytes, *, now: str) -> SyncRequest:
    """Body → geprüfte Einträge. `now` ist die Desktop-Zeit (UTC-Text). Wirft `SyncError`."""
    try:
        data = load_json_body(body)
    except WriteError as error:
        raise SyncError(400, "invalid_json", error.message) from None
    if not isinstance(data, dict):
        raise SyncError(400, "invalid_json", "Erwartet wird ein JSON-Objekt.")
    protocol = data.get("protocol")
    if not isinstance(protocol, int) or isinstance(protocol, bool) or protocol != PROTOCOL:
        raise SyncError(400, "invalid_protocol", f"Unterstützt wird protocol {PROTOCOL}.")
    client = _parse_utc(data.get("client_time"))
    if client is None:
        raise SyncError(400, "invalid_json",
                        "client_time fehlt oder ist kein UTC-Zeitstempel (YYYY-MM-DDTHH:MM:SSZ).")
    raw_entries = data.get("entries", {})
    if not isinstance(raw_entries, dict):
        raise SyncError(400, "invalid_json", "entries muss ein Objekt sein.")
    now_dt = datetime.datetime.strptime(now, _TIME_FORMAT)
    # Die Uhr zuerst: ein vorgehendes Handy trägt Zukunftsstempel, und „modified_at
    # liegt in der Zukunft" wäre dann die irreführende der beiden Meldungen.
    if abs(client - now_dt) > CLOCK_SKEW_LIMIT:
        raise SyncError(409, "clock_skew",
                        "Die Uhr des Handys weicht mehr als 15 Minuten von der des Desktops ab. "
                        "Bitte Datum und Uhrzeit am Handy prüfen.")
    if len(raw_entries) > MAX_ENTRIES:
        raise SyncError(422, "invalid_entry", f"Höchstens {MAX_ENTRIES} Tage je Anfrage.")
    entries = {date: _parse_entry(date, raw, now_dt) for date, raw in raw_entries.items()}
    return SyncRequest(str(data["client_time"]), entries)
```

(Die weiteren Importe legt der Task an, der sie nutzt: Ruff meldet ungenutzte sonst.)

- [ ] **Step 4: Run to verify they pass**

Run: `python3 -m pytest tests/test_mobile_sync.py -q -p no:cacheprovider` und danach `python3 -m pytest -q -p no:cacheprovider && ruff check . && npx --yes pyright@1.1.411 src/mobile_sync.py`
Expected: PASS, `All checks passed!`, `0 errors`.

- [ ] **Step 5: Commit**

~~~bash
git add src/mobile_sync.py tests/test_mobile_sync.py
git commit -m "feat(mobile): Request-Prüfung für den Abgleich mit dem Handy (#221)

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
~~~

---

### Task 3: `build_response` — Lesefenster und Konflikte

**Files:**
- Modify: `src/mobile_sync.py`
- Modify: `tests/test_mobile_sync.py`

**Interfaces:** Consumes: `sync.Doc`-Form des Merge-Ergebnisses (`entries`, `conflicts`, `devices`), `storage.sanitize_slot`, `devices.sanitize_registry`. Produces: `build_response(merged: Mapping[str, Any], *, sent_dates: Iterable[str], today: datetime.date, now: str, excluded: bool, categories: list[str]) -> dict[str, Any]` mit den Schlüsseln `protocol`, `server_time`, `last_pull_at`, `excluded`, `window_days`, `entries`, `conflicts`, `categories` (ohne `token`/`expires_at`).

- [ ] **Step 1: Write the failing tests**

Hänge an `tests/test_mobile_sync.py` an:

```python
# --- build_response ----------------------------------------------------------------------------

def _entry(date, *, slots=(SLOT,), modified_at="2026-10-01T10:00:00Z", device="DESK", deleted=False):
    return {"slots": [dict(s) for s in slots], "modified_at": modified_at,
            "device_id": device, "deleted": deleted}


def _iso(offset):
    return (TODAY + datetime.timedelta(days=offset)).isoformat()


def respond(merged, *, sent=(), excluded=False, categories=("Projekt",)):
    merged = {"entries": {}, "conflicts": [], "devices": {}, **merged}
    return mobile_sync.build_response(merged, sent_dates=sent, today=TODAY, now=NOW,
                                      excluded=excluded, categories=list(categories))


def test_the_response_carries_the_protocol_fields_and_no_token():
    response = respond({})

    assert response == {
        "protocol": 1, "server_time": NOW, "last_pull_at": NOW, "excluded": False,
        "window_days": 90, "entries": {}, "conflicts": [], "categories": ["Projekt"]}


def test_the_window_is_today_minus_90_days_through_today():
    merged = {"entries": {
        _iso(-91): _entry(_iso(-91)), _iso(-90): _entry(_iso(-90)),
        _iso(0): _entry(_iso(0)), _iso(1): _entry(_iso(1)),
        _iso(-30): _entry(_iso(-30), slots=(), deleted=True)}}

    entries = respond(merged)["entries"]

    assert sorted(entries) == sorted([_iso(-90), _iso(-30), _iso(0)])
    assert entries[_iso(-30)]["deleted"] is True            # Tombstones im Fenster reisen mit


def test_days_the_phone_sent_are_included_outside_the_window():
    merged = {"entries": {"2025-01-15": _entry("2025-01-15"), _iso(-200): _entry(_iso(-200))}}

    entries = respond(merged, sent=["2025-01-15"])["entries"]

    assert sorted(entries) == ["2025-01-15"]


def test_entries_are_sorted_and_use_only_the_four_entry_fields():
    merged = {"entries": {_iso(0): _entry(_iso(0)), _iso(-1): _entry(_iso(-1))}}

    entries = respond(merged)["entries"]

    assert list(entries) == [_iso(-1), _iso(0)]
    assert set(entries[_iso(0)]) == {"slots", "modified_at", "device_id", "deleted"}


def test_foreign_slot_values_are_sanitised_in_the_response():
    dirty = {"start": "08:00", "end": "12:00", "pause": "abc", "kategorie": 5, "send_reminder_minutes": 10}
    merged = {"entries": {_iso(0): _entry(_iso(0), slots=(dirty, "kein Objekt"))}}

    slots = respond(merged)["entries"][_iso(0)]["slots"]

    assert slots == [{"start": "08:00", "end": "12:00", "pause": 0, "kategorie": ""}]


def _conflict(key, *, resolved=False, kind="entry"):
    return {"id": f"c-{key}", "kind": kind, "key": key, "resolved": resolved,
            "candidates": [
                _entry(key, modified_at="2026-10-07T18:30:00Z", device="PHONE-0001"),
                _entry(key, slots=({"start": "09:00", "end": "13:00", "pause": 0, "kategorie": ""},),
                       modified_at="2026-10-07T20:00:00Z", device="DESK")]}


def test_open_entry_conflicts_in_the_window_are_listed_with_device_names():
    merged = {"conflicts": [_conflict(_iso(-1))],
              "devices": {"PHONE-0001": {"name": "Pixel", "updated_at": NOW}}}

    conflicts = respond(merged)["conflicts"]

    assert conflicts == [{"id": f"c-{_iso(-1)}", "date": _iso(-1), "versions": [
        {"device": "PHONE-0001", "name": "Pixel", "modified_at": "2026-10-07T18:30:00Z",
         "slots": [SLOT]},
        {"device": "DESK", "name": "", "modified_at": "2026-10-07T20:00:00Z",
         "slots": [{"start": "09:00", "end": "13:00", "pause": 0, "kategorie": ""}]}]}]


def test_resolved_setting_and_out_of_window_conflicts_are_left_out():
    merged = {"conflicts": [
        _conflict(_iso(-1), resolved=True), _conflict("recipient", kind="setting"),
        _conflict(_iso(-200)), _conflict("2025-01-15"), "kein Objekt", {"kind": "entry", "key": 5}]}

    assert [c["date"] for c in respond(merged, sent=["2025-01-15"])["conflicts"]] == ["2025-01-15"]


def test_the_excluded_flag_and_categories_are_passed_through():
    response = respond({}, excluded=True, categories=["A", "B"])
    assert response["excluded"] is True and response["categories"] == ["A", "B"]
```

- [ ] **Step 2: Run to verify they fail**

Run: `python3 -m pytest tests/test_mobile_sync.py -q -p no:cacheprovider -x`
Expected: FAIL: `AttributeError: module 'src.mobile_sync' has no attribute 'build_response'`.

- [ ] **Step 3: Implement**

In `src/mobile_sync.py` ergänze die Importe (alphabetisch einsortiert)

```python
from collections.abc import Iterable, Mapping

from src.devices import sanitize_registry
from src.storage import sanitize_slot
```

und hänge ans Ende an:

```python
def _clean_slots(raw: object) -> list[dict[str, Any]]:
    """Gespeicherte Slots sind Fremddaten (Drive-Sync, Handbearbeitung): bereinigen
    und auf die vier Felder des Protokolls beschränken."""
    if not isinstance(raw, list):
        return []
    slots = []
    for item in raw:
        clean = sanitize_slot(item)
        if clean is not None:
            slots.append({key: clean[key] for key in ("start", "end", "pause", "kategorie")})
    return slots


def _clean_entry(entry: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "slots": _clean_slots(entry.get("slots")),
        "modified_at": str(entry.get("modified_at") or ""),
        "device_id": str(entry.get("device_id") or ""),
        "deleted": bool(entry.get("deleted")),
    }


def _conflict_views(merged: Mapping[str, Any], visible: Any) -> list[dict[str, Any]]:
    registry = sanitize_registry(merged.get("devices"))
    views = []
    for conflict in merged.get("conflicts") or []:
        if not isinstance(conflict, dict) or conflict.get("kind") != "entry" or conflict.get("resolved"):
            continue
        key = conflict.get("key")
        if not isinstance(key, str) or not visible(key):
            continue
        versions = []
        for candidate in conflict.get("candidates") or []:
            if not isinstance(candidate, dict):
                continue
            device = candidate.get("device_id")
            device = device if isinstance(device, str) else ""
            versions.append({
                "device": device,
                "name": registry.get(device, {}).get("name", ""),
                "modified_at": str(candidate.get("modified_at") or ""),
                "slots": _clean_slots(candidate.get("slots")),
            })
        views.append({"id": str(conflict.get("id") or ""), "date": key, "versions": versions})
    return sorted(views, key=lambda view: view["date"])


def build_response(merged: Mapping[str, Any], *, sent_dates: Iterable[str],
                   today: datetime.date, now: str, excluded: bool,
                   categories: list[str]) -> dict[str, Any]:
    """Die Antwort des Abgleichs aus dem Merge-Ergebnis, ohne `token`/`expires_at`
    (die ergänzt die Route). Fenster `[heute − 90, heute]` (heute ist das lokale
    Datum des Desktops) plus alle gesendeten Tage — beides für Einträge **und**
    Konflikte: ein Konflikt auf einem gesendeten Tag außerhalb des Fensters bliebe
    sonst unsichtbar. Ein gesendeter Tag, den der Merge verworfen hat (Self-Heal bei
    `excluded`), fehlt in `entries`."""
    sent = set(sent_dates)
    first = (today - datetime.timedelta(days=WINDOW_DAYS)).isoformat()
    last = today.isoformat()

    def visible(date: str) -> bool:
        return date in sent or first <= date <= last

    entries = {
        date: _clean_entry(entry)
        for date, entry in sorted((merged.get("entries") or {}).items())
        if isinstance(date, str) and isinstance(entry, dict) and visible(date)
    }
    return {
        "protocol": PROTOCOL,
        "server_time": now,
        "last_pull_at": now,
        "excluded": excluded,
        "window_days": WINDOW_DAYS,
        "entries": entries,
        "conflicts": _conflict_views(merged, visible),
        "categories": list(categories),
    }
```

- [ ] **Step 4: Run to verify they pass**

Run: `python3 -m pytest tests/test_mobile_sync.py -q -p no:cacheprovider` und danach `python3 -m pytest -q -p no:cacheprovider && ruff check . && npx --yes pyright@1.1.411 src/mobile_sync.py`
Expected: PASS, `All checks passed!`, `0 errors`.

- [ ] **Step 5: Commit**

~~~bash
git add src/mobile_sync.py tests/test_mobile_sync.py
git commit -m "feat(mobile): Antwort des Abgleichs mit Lesefenster und Konflikten (#221)

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
~~~

---

### Task 4: `perform_sync` — Guard, Merge, journalisierte Anwendung

**Files:**
- Modify: `src/mobile_sync.py`
- Modify: `tests/test_mobile_sync.py`

**Interfaces:** Consumes: `parse_request`/`SyncRequest` (Task 2), `build_response` (Task 3), `sync.build_local_doc`, `sync.merge`, `sync_journal.apply_merged_doc_journaled`, `sync_journal.JOURNAL_FILENAME`, `sync_history.mark_synced`, `devices.with_own_entry`. Produces: `perform_sync(request, *, device_id, device_name, last_pull_at, categories, storage, settings, conflicts_store, base, now, today, data_lock=None, sync_guard=None) -> dict[str, Any]` (die Antwort aus `build_response`; wirft `SyncError(503, "busy", …)`, wenn der Guard belegt ist).

- [ ] **Step 1: Write the failing tests**

Hänge an `tests/test_mobile_sync.py` an:

```python
# --- perform_sync ---------------------------------------------------------------------------------

PHONE = "phone-0001"


@pytest.fixture
def env(tmp_path):
    settings = Settings(str(tmp_path / "settings.json"))
    settings.device_id_for_sync = "DESK"
    return types.SimpleNamespace(
        storage=Storage(str(tmp_path / "zeiterfassung.json"), device_id="DESK"),
        settings=settings,
        conflicts=ConflictsStore(str(tmp_path / "conflicts.json")),
        base=str(tmp_path))


def put_desktop(env, date, *, slots=(SLOT,), modified_at, device="DESK", deleted=False):
    raw = dict(env.storage.get_all_raw())
    raw[date] = {"slots": [dict(s) for s in slots], "modified_at": modified_at,
                 "device_id": device, "deleted": deleted}
    env.storage.apply_merge(raw)


def run(env, entries, *, last_pull_at="", now=NOW, **over):
    request = mobile_sync.parse_request(body(entries), now=now)
    kwargs = dict(device_id=PHONE, device_name="Pixel", last_pull_at=last_pull_at,
                  categories=["Projekt"], storage=env.storage, settings=env.settings,
                  conflicts_store=env.conflicts, base=env.base, now=now, today=TODAY)
    kwargs.update(over)
    return mobile_sync.perform_sync(request, **kwargs)


def test_a_new_day_from_the_phone_is_stored_under_the_device_of_the_token(env):
    response = run(env, {"2026-10-07": day(device_id="evil")})

    stored = env.storage.get_all_raw()["2026-10-07"]
    assert stored["device_id"] == PHONE and stored["slots"] == [SLOT] and not stored["deleted"]
    assert response["entries"]["2026-10-07"]["device_id"] == PHONE


def test_the_phone_appears_with_its_name_in_the_device_registry(env):
    run(env, {"2026-10-07": day()})
    assert env.settings.get("known_devices")[PHONE]["name"] == "Pixel"


def test_a_newer_phone_change_wins_without_a_conflict(env):
    put_desktop(env, "2026-10-07", modified_at="2026-10-01T10:00:00Z")

    run(env, {"2026-10-07": day(slots=({"start": "07:00", "end": "11:00"},),
                                modified_at="2026-10-07T18:30:00Z")},
        last_pull_at="2026-10-05T00:00:00Z")

    assert env.storage.get("2026-10-07")["slots"][0]["start"] == "07:00"
    assert env.conflicts.get_all() == []


def test_a_phone_tombstone_deletes_an_older_desktop_day(env):
    put_desktop(env, "2026-10-05", modified_at="2026-10-05T10:00:00Z")

    response = run(env, {"2026-10-05": tomb("2026-10-07T18:30:00Z")},
                   last_pull_at="2026-10-06T00:00:00Z")

    assert env.storage.get("2026-10-05") is None
    assert env.storage.get_all_raw()["2026-10-05"]["deleted"] is True
    assert response["entries"]["2026-10-05"]["deleted"] is True


def test_a_change_on_both_sides_becomes_a_conflict(env):
    put_desktop(env, "2026-10-07", modified_at="2026-10-07T20:00:00Z",
                slots=({"start": "09:00", "end": "13:00", "pause": 0, "kategorie": ""},))

    response = run(env, {"2026-10-07": day(modified_at="2026-10-07T18:30:00Z")},
                   last_pull_at="2026-10-06T00:00:00Z")

    stored = env.conflicts.get_all()
    assert len(stored) == 1 and stored[0]["key"] == "2026-10-07" and not stored[0]["resolved"]
    assert [c["date"] for c in response["conflicts"]] == ["2026-10-07"]
    assert {v["device"] for v in response["conflicts"][0]["versions"]} == {PHONE, "DESK"}
    assert response["entries"]["2026-10-07"]["slots"][0]["start"] == "09:00"    # LWW: der jüngere


def test_the_first_sync_turns_every_differing_day_into_a_conflict(env):
    put_desktop(env, "2026-10-07", modified_at="2026-10-01T10:00:00Z",
                slots=({"start": "09:00", "end": "13:00", "pause": 0, "kategorie": ""},))

    run(env, {"2026-10-07": day(modified_at="2026-10-07T18:30:00Z")}, last_pull_at="")

    assert len(env.conflicts.get_all()) == 1


def test_the_same_request_twice_changes_nothing_and_adds_no_conflict(env):
    put_desktop(env, "2026-10-07", modified_at="2026-10-07T20:00:00Z",
                slots=({"start": "09:00", "end": "13:00", "pause": 0, "kategorie": ""},))
    entries = {"2026-10-07": day(modified_at="2026-10-07T18:30:00Z"), "2026-10-06": day()}

    first = run(env, entries, last_pull_at="")
    stored = dict(env.storage.get_all_raw())
    second = run(env, entries, last_pull_at="")

    assert len(env.conflicts.get_all()) == 1
    assert env.storage.get_all_raw() == stored
    assert second["entries"] == first["entries"]


def test_a_phone_offline_longer_than_the_last_compaction_cannot_resurrect_a_day(env):
    env.settings.set("gc_watermark", "2026-10-01T00:00:00Z")

    response = run(env, {"2026-08-15": day(modified_at="2026-08-15T10:00:00Z")},
                   last_pull_at="2026-09-01T00:00:00Z")

    assert response["excluded"] is True
    assert "2026-08-15" not in env.storage.get_all_raw()
    assert "2026-08-15" not in response["entries"]


def test_excluded_is_false_without_or_after_the_watermark(env):
    env.settings.set("gc_watermark", "2026-10-01T00:00:00Z")
    assert run(env, {}, last_pull_at="")["excluded"] is False
    assert run(env, {}, last_pull_at="2026-10-02T00:00:00Z")["excluded"] is False


def test_a_successful_sync_leaves_no_journal_and_marks_the_machine_as_synced(env):
    assert not sync_history.ever_synced(env.base)

    run(env, {"2026-10-07": day()})

    assert not (sync_journal.JOURNAL_FILENAME in __import__("os").listdir(env.base))
    assert sync_history.ever_synced(env.base)


def test_a_busy_guard_is_503_and_nothing_is_applied(env):
    guard = threading.Lock()
    guard.acquire()

    with pytest.raises(SyncError) as excinfo:
        run(env, {"2026-10-07": day()}, sync_guard=guard)

    assert (excinfo.value.status, excinfo.value.code) == (503, "busy")
    assert env.storage.get_all_raw() == {} and not sync_history.ever_synced(env.base)
    assert guard.locked()                                      # der fremde Halter bleibt Halter


def test_the_guard_is_released_after_success_and_after_an_error(env, monkeypatch):
    guard = threading.Lock()
    run(env, {"2026-10-07": day()}, sync_guard=guard)
    assert guard.acquire(blocking=False)
    guard.release()

    def boom(*args, **kwargs):
        raise RuntimeError("Platte voll")
    monkeypatch.setattr(sync_journal, "apply_merged_doc_journaled", boom)
    with pytest.raises(RuntimeError):
        run(env, {"2026-10-06": day()}, sync_guard=guard)
    assert guard.acquire(blocking=False)


def test_snapshot_merge_and_apply_run_under_the_data_lock(env, monkeypatch):
    lock = threading.RLock()
    seen = {}
    real = sync_journal.apply_merged_doc_journaled

    def spy(*args, **kwargs):
        seen["owned"] = lock._is_owned()
        return real(*args, **kwargs)
    monkeypatch.setattr(sync_journal, "apply_merged_doc_journaled", spy)

    run(env, {"2026-10-07": day()}, data_lock=lock)

    assert seen == {"owned": True}
    assert lock.acquire(blocking=False)                        # und danach wieder frei


def test_the_response_has_the_window_and_the_categories(env):
    put_desktop(env, "2026-10-01", modified_at="2026-10-01T10:00:00Z")
    put_desktop(env, "2025-01-15", modified_at="2025-01-15T10:00:00Z")

    response = run(env, {}, last_pull_at="2026-10-02T00:00:00Z")

    assert sorted(response["entries"]) == ["2026-10-01"]
    assert response["categories"] == ["Projekt"] and response["last_pull_at"] == NOW
```

- [ ] **Step 2: Run to verify they fail**

Run: `python3 -m pytest tests/test_mobile_sync.py -q -p no:cacheprovider -x`
Expected: FAIL: `AttributeError: module 'src.mobile_sync' has no attribute 'perform_sync'`.

- [ ] **Step 3: Implement**

In `src/mobile_sync.py` ergänze die Importe

```python
import contextlib
import os
import threading
from typing import TYPE_CHECKING

from src import sync, sync_history, sync_journal
from src.devices import sanitize_registry, with_own_entry   # ersetzt den Import aus Task 3

if TYPE_CHECKING:
    from src.conflicts_store import ConflictsStore
    from src.settings import Settings
    from src.storage import Storage
```

(`Any` ist schon importiert) und hänge ans Ende an:

```python
def _phone_doc(request: SyncRequest, device_id: str, device_name: str, now: str) -> dict[str, Any]:
    """Das Handy als `local` des Merges: nur die geschickten Tage, die Geräte-ID aus
    dem Token. So wirkt die Self-Heal-Regel (`excluded`) für das Handy richtig."""
    return {
        "schema_version": sync.SCHEMA_VERSION,
        "entries": {
            date: {**entry, "device_id": device_id}
            for date, entry in request.entries.items()
        },
        "settings": {},
        "conflicts": [],
        "devices": with_own_entry(None, device_id, device_name, now),
        "meta": {"gc_watermark": ""},
    }


def perform_sync(request: SyncRequest, *, device_id: str, device_name: str,
                 last_pull_at: str, categories: list[str], storage: Storage,
                 settings: Settings, conflicts_store: ConflictsStore, base: str,
                 now: str, today: datetime.date,
                 data_lock: threading.RLock | None = None,
                 sync_guard: threading.Lock | None = None) -> dict[str, Any]:
    """Wendet den Abgleich an und liefert die Antwort (ohne `token`/`expires_at`).

    `last_pull_at` ist der Stand aus dem Gerätespeicher des Desktops, nie der Wert
    aus dem Body. `sync_guard` (derselbe wie Drive-Sync, Kompaktierung, Quit-Push)
    wird nicht-blockierend genommen und im `finally` dieses Threads freigegeben;
    belegt → `SyncError` 503. `data_lock` klammert Snapshot → Merge → Apply. Die
    Route ruft `on_change` erst danach.

    Idempotent: derselbe Request liefert dasselbe Ergebnis (der Merge ist es, und
    `merge` dedupliziert gleichwertige offene Konflikte)."""
    if sync_guard is not None and not sync_guard.acquire(blocking=False):
        raise SyncError(503, "busy", "Ein anderer Abgleich läuft gerade. Bitte später erneut versuchen.")
    try:
        phone_doc = _phone_doc(request, device_id, device_name, now)
        with (data_lock if data_lock is not None else contextlib.nullcontext()):
            desktop_doc = sync.build_local_doc(storage, settings, conflicts_store)
            merged = sync.merge(phone_doc, desktop_doc, last_pull_at)
            sync_journal.apply_merged_doc_journaled(
                merged, storage, settings, conflicts_store,
                os.path.join(base, sync_journal.JOURNAL_FILENAME))
            # Der Startup-Sweep verwirft Tombstones auf Rechnern, die „nie gesynct"
            # haben: nach einem Abgleich mit dem Handy haben sie einen Abnehmer.
            sync_history.mark_synced(base)
        watermark = (desktop_doc.get("meta") or {}).get("gc_watermark") or ""
        excluded = bool(last_pull_at) and last_pull_at < watermark
        return build_response(merged, sent_dates=request.entries, today=today, now=now,
                              excluded=excluded, categories=categories)
    finally:
        if sync_guard is not None:
            sync_guard.release()
```

Ersetze in den Tests `__import__("os").listdir(env.base)` durch `os.listdir(env.base)` und füge `import os` oben in `tests/test_mobile_sync.py` ein (Aufräumen des Test-Codes aus Step 1).

- [ ] **Step 4: Run to verify they pass**

Run: `python3 -m pytest tests/test_mobile_sync.py -q -p no:cacheprovider` und danach `python3 -m pytest -q -p no:cacheprovider && ruff check . && npx --yes pyright@1.1.411 src/mobile_sync.py`
Expected: PASS, `All checks passed!`, `0 errors`. Weicht ein Test von der Erwartung ab (z. B. die Reihenfolge der Versionen eines Konflikts), liegt die Ursache im Merge, nicht im Test: erst `systematic-debugging`, dann Test oder Plan per Ruling anpassen.

- [ ] **Step 5: Commit**

~~~bash
git add src/mobile_sync.py tests/test_mobile_sync.py
git commit -m "feat(mobile): Abgleich mit dem Handy über Merge und Journal (#221)

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
~~~

---

### Task 5: Annotationen, Doku, Spec nachziehen

**Files:**
- Modify: `tests/test_type_annotations.py`
- Modify: `CLAUDE.md`, `src/CLAUDE.md`
- Modify: `docs/superpowers/specs/2026-10-08-mobile-pwa-design.md`

**Interfaces:** Produces: `src/mobile_sync.py` in `ANNOTATED_MODULES`; Doku in `src/CLAUDE.md`/`CLAUDE.md`; die beiden Rulings (Uhr zuerst, Zukunftsgrenze) in der Spec.

- [ ] **Step 1: Write the failing test**

Die Whitelist ist der Test: trage zuerst das Modul ein (Edit in Step 3 vorziehen) und starte `python3 -m pytest tests/test_type_annotations.py -q -p no:cacheprovider`. Ist `mobile_sync.py` voll annotiert, ist der Test sofort grün; fehlt eine Annotation (z. B. an `bad` in `_parse_entry`, `visible` in `build_response`), nenne sie dort explizit. In `tests/test_type_annotations.py` ersetze

```python
    "src/api_summary.py",
```

durch

```python
    "src/api_summary.py",
    "src/mobile_sync.py",
```

- [ ] **Step 2: Run to verify**

Run: `python3 -m pytest tests/test_type_annotations.py -q -p no:cacheprovider`
Expected: PASS; sonst fehlende Annotationen in `src/mobile_sync.py` ergänzen (`def bad(reason: str) -> SyncError`, `def visible(date: str) -> bool` sind bereits annotiert; `_conflict_views(…, visible: Any)` ggf. präzisieren auf `Callable[[str], bool]` mit `from collections.abc import Callable`).

- [ ] **Step 3: Docs**

In `CLAUDE.md` ersetze

```markdown
- `src/keyring_store.py` — Passwörter im OS-Schlüsselbund
```

durch

```markdown
- `src/mobile_sync.py` — fachlicher Kern von `POST /v1/sync` der Handy-Erfassung (#221): `parse_request` prüft den Body (Fremddaten, Regeln der lokalen API), `perform_sync` merged das Handy als `local` über `sync.merge` und wendet über `sync_journal` an, `build_response` baut Lesefenster und Konflikte. Tk-frei; Token und Gerätedatensatz gehören der Route (s. `src/CLAUDE.md`)
- `src/keyring_store.py` — Passwörter im OS-Schlüsselbund
```

In `src/CLAUDE.md` ersetze

```markdown
  `clean_device_name`). Design: `docs/superpowers/specs/2026-10-08-mobile-pwa-design.md`.
```

durch

```markdown
  `clean_device_name`). Design: `docs/superpowers/specs/2026-10-08-mobile-pwa-design.md`.

  `mobile_sync.py` — Abgleich mit dem Handy (`POST /v1/sync`), Tk-frei, ohne Socket. Der Body ist
  Fremddaten: `parse_request` prüft ihn mit den Regeln der lokalen API (`api_entry_write.parse_slots`),
  dazu Datum, Zeitstempel, höchstens 400 Tage, die Uhr (15 Minuten, **vor** den Einträgen, damit ein
  vorgehendes Handy `clock_skew` statt `invalid_entry` bekommt) und `modified_at` höchstens 15 Minuten in
  der Zukunft (sonst gewänne ein Zukunftsstempel jeden LWW-Vergleich). Die Geräte-ID kommt aus dem Token,
  nie aus dem Body. `perform_sync` nimmt den `sync_guard` nicht-blockierend (belegt → 503 `busy`),
  klammert Snapshot → `sync.merge(local=Handy, remote=Desktop)` → `apply_merged_doc_journaled` mit dem
  `data_lock` und setzt danach `sync_history.mark_synced` (der Startup-Sweep darf die Tombstones eines
  Rechners, der mit dem Handy abgleicht, nicht verwerfen). Das Handy als `local` lässt die Self-Heal-Regel
  (`excluded`) richtig wirken; das `last_pull_at` kommt aus dem Gerätespeicher, nie aus dem Body.
  `build_response` ist rein: Fenster `[heute − 90, heute]` plus gesendete Tage, offene Eintrags-Konflikte
  mit Gerätenamen aus der Registry, alle Slots über `storage.sanitize_slot`. `on_change` ruft die Route
  nach Freigabe von Guard und Lock.
```

In `docs/superpowers/specs/2026-10-08-mobile-pwa-design.md` ersetze

```markdown
`modified_at` exakt im Format `YYYY-MM-DDTHH:MM:SSZ`;
```

durch

```markdown
`modified_at` exakt im Format `YYYY-MM-DDTHH:MM:SSZ` und höchstens 15 Minuten in der Zukunft (sonst gewänne ein Zukunftsstempel jeden LWW-Vergleich); ein Tag ohne Slots muss `deleted: true` sein und umgekehrt;
```

und ersetze

```markdown
2. **Uhr:** weicht
```

durch

```markdown
2. **Uhr** (geprüft **vor** den Einträgen, damit ein vorgehendes Handy `clock_skew` statt `invalid_entry` bekommt): weicht
```

- [ ] **Step 4: Run to verify**

Run: `python3 -m pytest tests/test_type_annotations.py tests/test_claude_md_claims.py -q -p no:cacheprovider` und danach `python3 -m pytest -q -p no:cacheprovider && ruff check . && npx --yes pyright@1.1.411 src/mobile_sync.py`
Expected: PASS, `All checks passed!`, `0 errors`.

- [ ] **Step 5: Commit**

~~~bash
git add tests/test_type_annotations.py CLAUDE.md src/CLAUDE.md docs/superpowers/specs/2026-10-08-mobile-pwa-design.md
git commit -m "docs(mobile): mobile_sync in Annotations-Whitelist, CLAUDE.md und Spec (#221)

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
~~~

---

## Mutationsprüfung (nach Task 5, vor dem Review)

Jeden Mutanten einzeln anwenden (Datei kopieren, genau eine Ersetzung, **`__pycache__` vorher löschen oder `PYTHONDONTWRITEBYTECODE=1` setzen**, Tests laufen lassen, zurückkopieren). Jeder muss mindestens einen Test rot färben:

| Datei | Mutation | Erwartet rot |
|---|---|---|
| `mobile_sync.py` | `CLOCK_SKEW_LIMIT` auf 16 Minuten | `test_the_clock_skew_limit_is_fifteen_minutes` |
| `mobile_sync.py` | `abs(client - now_dt) >` → `client - now_dt >` | `test_the_clock_skew_limit_is_fifteen_minutes` |
| `mobile_sync.py` | Uhrprüfung hinter die Einträge verschieben | `test_a_skewed_clock_is_reported_as_skew_not_as_an_invalid_entry` |
| `mobile_sync.py` | Zukunftsprüfung von `modified_at` entfernen | `test_a_modified_at_in_the_future_is_rejected` |
| `mobile_sync.py` | `isinstance(protocol, bool)` entfernen | `test_a_wrong_protocol_is_400_invalid_protocol` |
| `mobile_sync.py` | `_DATE_RE` entfernen (nur `fromisoformat`) | `test_a_bad_date_key_is_422_with_the_date_in_the_message` |
| `mobile_sync.py` | `ascii(date)` → `date` | `test_a_bad_date_key_is_422_with_the_date_in_the_message` |
| `mobile_sync.py` | `MAX_ENTRIES`-Prüfung entfernen | `test_at_most_400_days_per_request` |
| `mobile_sync.py` | Tombstone mit Slots erlauben | `test_a_bad_entry_is_422_invalid_entry` |
| `mobile_sync.py` | `device_id` aus dem Body übernehmen (`{**entry}` statt Überschreiben) | `test_a_new_day_from_the_phone_is_stored_under_the_device_of_the_token` |
| `mobile_sync.py` | Fenster `<=` → `<` an der unteren Grenze | `test_the_window_is_today_minus_90_days_through_today` |
| `mobile_sync.py` | `date in sent or` entfernen | `test_days_the_phone_sent_are_included_outside_the_window` |
| `mobile_sync.py` | `sanitize_slot` weglassen | `test_foreign_slot_values_are_sanitised_in_the_response` |
| `mobile_sync.py` | `merge(desktop, phone)` statt `merge(phone, desktop)` | `test_a_phone_offline_longer_than_the_last_compaction_cannot_resurrect_a_day` |
| `mobile_sync.py` | `mark_synced` entfernen | `test_a_successful_sync_leaves_no_journal_and_marks_the_machine_as_synced` |
| `mobile_sync.py` | `sync_guard.release()` aus dem `finally` | `test_the_guard_is_released_after_success_and_after_an_error` |
| `mobile_sync.py` | `data_lock` weglassen | `test_snapshot_merge_and_apply_run_under_the_data_lock` |
| `mobile_sync.py` | `excluded` immer `False` | `test_a_phone_offline_longer_than_the_last_compaction_cannot_resurrect_a_day` |

Überlebt ein Mutant, ist das ein Testfehler (wie bei `close()` in PR 2): Test schärfen, gegen den Mutanten rot sehen, committen.

## Finale

Nach Task 5: Review über den ganzen Branch mit einem frischen Reviewer auf dem leistungsfähigsten Modell (Review Focus und Rulings mitgeben; aktiver Angriff mit hostilen Bodys, Uhren und Dateistand), Critical/Important in **einem** Fix-Durchlauf (je Fix ein Test, der zuerst rot war), Minors ins Ledger und in ein Issue. Danach `finishing-a-development-branch`: PR gegen `master` (`Refs #221`, „PR 3 von 8" im Titel).
