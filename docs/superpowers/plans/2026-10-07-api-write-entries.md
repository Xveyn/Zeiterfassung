# Lokale API, PR 4: Schreibende Ist-Zeit-Endpunkte Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Die lokale API kann Ist-Zeiten schreiben: `PUT /v1/entries/{date}` (Tag ersetzen, idempotent) und `DELETE /v1/entries/{date}` (Tombstone), mit allen Regeln, die die UI an ihren Eingängen heute durchsetzt (Validierung, Sync-Konflikt-Sperre, Urlaubssperre, nicht blockierende Wochenlimit-/Pausen-Warnungen).

**Architecture:** Ein neues Tk-freies Modul `api_entry_write` (Body → geprüfte Slots, Tagesprüfung, Warnungen), dünne `PUT`/`DELETE`-Handler in `api_routes`, die Prüfen, Konfliktcheck und Speichern unter dem **einen** geteilten `data_lock` ausführen und danach `ctx.on_change` melden. `ApiContext` bekommt `data_lock`, `conflicts_store`, `vacation_store`, `on_change`; `ui.py` füllt sie. Dazu zwei Punkte aus #233: `authorize` vergleicht die Methode exakt, und `shutdown()` steht in `_quit_with_sync_push` **vor** dem Push.

**Tech Stack:** Python 3.12, stdlib (`json`), pytest. Keine neue Abhängigkeit.

**Spec:** `docs/superpowers/specs/2026-10-06-lokale-api-design.md` („Endpunkte", „Regeln, die die API nachbilden muss", „Threading"). Offene Punkte: Issue #233. Reservierungen, Urlaub und Auswertungen: Issue #239.

**Branching:** Stack. `git switch feat/api-settings-tab && git switch -c feat/api-write-entries`. PR 4 zielt auf `feat/api-settings-tab` (PR #238) und wird danach mit `POST /repos/Xveyn/Zeiterfassung/stacks/236/add` an den Stack gehängt. PR-Text enthält `Refs #92`, **kein** `Closes`.

## Entscheidungen (mit dem Nutzer abgestimmt)

- `PUT` mit leerer Slot-Liste ist **422** („zum Löschen DELETE benutzen"): wie die UI, die einen leeren Tag nicht speichert.
- **Identischer Inhalt schreibt nicht neu:** kein `modified_at`, kein `on_change`; Antwort `"changed": false`. Skripte, die zyklisch dasselbe senden, erzeugen sonst Schreibvorgänge und Sync-Konflikte aus dem Nichts.
- **Datumsbereich 2000-01-01 … 2100-12-31**, sonst 422. Ein Skript-Fehler mit Jahr 1970 würde sonst Daten und Tombstones dauerhaft im Sync hinterlassen.
- **Grenzen:** höchstens 50 Slots je Tag; Kategorie höchstens 100 Zeichen, ohne Steuerzeichen, sonst **frei** (die Berichte vereinigen Kategorien aus den Daten ohnehin mit der Liste aus den Einstellungen); umgebende Leerzeichen werden entfernt (wie in der UI).
- **Statuscodes:** `400` kaputtes JSON oder falsche Form, `422` ungültiger Slot oder Datum, `409` Konflikt- oder Urlaubstag.
- `DELETE` eines fehlenden (oder getombstonten) Tags ist **404**, wie `GET`.

## Global Constraints

- Tk-frei, stdlib-only, vollständig annotiert; `src/api_entry_write.py` kommt in `ANNOTATED_MODULES` (`tests/test_type_annotations.py`).
- Prüfen → Konfliktcheck → Speichern laufen unter **demselben** `ctx.data_lock` (ein `RLock`, nie über Netzwerkaufrufe). `ctx.on_change` wird **nach** dem Lock und **nur bei tatsächlicher Änderung** gerufen; ein Fehler darin macht aus einem gespeicherten Schreibzugriff keine 500 (geloggt).
- Die Sperren der UI gelten auch hier: ungelöster Sync-Konflikt am Tag → 409 (`PUT` und `DELETE`); Tag mit **Urlaubsminuten > 0** → 409 (`PUT`; 0-Minuten-Tage der Periode bleiben beschreibbar, Regel aus der Wurzel-`CLAUDE.md`).
- Wochenlimit und Pausenpflicht sind **Warnungen** (`warnings` in der Antwort), nie ein Fehler; geprüft wird gegen den simulierten Stand **nach** dem Speichern (der neue Tag ersetzt den alten, zählt nicht doppelt).
- Wire-Format der Slots: `{start, end, pause, kategorie}`; `start`/`end` genau `HH:MM` (zwei Ziffern, ASCII), `pause` ganze Minuten (kein Bool, keine Zahl als Text), unbekannte Felder sind 422. Zahlen in Antworten sind ganze Minuten.
- JSON strikt: kein `NaN`/`Infinity`, keine doppelten Schlüssel, kein `RecursionError` (tiefe Verschachtelung ist 400, nie 500).
- `authorize` vergleicht die Methode **exakt** (kein `.upper()`); `get`/`put`/`poſt` sind 405.
- `self._api.shutdown()` steht in `_quit_with_sync_push` vor `self._sync.push_on_quit()`.
- Jeder `except Exception`/`BaseException` loggt, meldet oder begründet im Handler; `ruff check .` sauber.

## Review Focus

Eingaben und Zustände, die die Spec nahelegt, aber keine Task erzwingt. Jede Zeile ist in der genannten Task gepinnt.

1. **Body-Form:** kaputtes JSON, `NaN`/`Infinity`, doppelte Schlüssel, 100 000-fach verschachtelte Arrays (`RecursionError`), `slots` als Objekt/Zahl, Slot als String, unbekannte/fehlende Felder, `pause` als Bool/Text/Float/negativ/größer als die Arbeitszeit, Zeiten wie `8:00`, `24:00`, `08:60`, `٠٨:٠٠`, `" 08:00"`, Kategorie mit `\n`/`\x00`/`\x7f` oder 101 Zeichen: immer definiertes 400/422, nie 500. Task 2.
2. **Sperren und Atomarität:** Konflikt-Tag und Urlaubstag (nur `minutes > 0`) → 409; Konflikt-Tag auch bei `DELETE`; Konfliktcheck **und** Speichern laufen unter demselben Lock (kein Zeitfenster dazwischen). Task 2 und 3.
3. **Idempotenz:** ein identischer `PUT` ruft weder `Storage.save` noch `on_change`; ein geänderter ruft beide genau einmal; ein Fehler in `on_change` lässt die Antwort 200. Task 3.
4. **Warnungen blockieren nie:** Wochenlimit/Pausenpflicht erscheinen in `warnings`, der Tag wird trotzdem gespeichert; der simulierte Stand ersetzt den alten Tag. Task 2 und 3.
5. **Grenzen und Tombstones:** Jahr < 2000 oder > 2100 → 422; `DELETE` auf fehlenden oder getombstonten Tag → 404; `PUT` auf einen getombstonten Tag legt ihn wieder an. Task 2 und 3.
6. **Auth am Draht:** `put` klein → 405; `PUT` ohne JSON-Content-Type → 415 vor jedem Body-Parsing (Server); ein unauthentifizierter `PUT` ändert nie etwas. Task 1 und 3.

---

### Task 1: `authorize` vergleicht die Methode exakt

**Files:**
- Modify: `src/api_auth.py`
- Modify: `tests/test_api_auth.py`

**Interfaces:**
- Consumes: `api_auth.authorize(method, headers, policy, verifier) -> AuthResult`, `ALLOWED_METHODS`.
- Produces: unverändertes Interface; `authorize("get", …)` ist jetzt 405. Der Server übergibt `self.command` roh, das Routing vergleicht exakt — es gibt damit nur noch **eine** Sicht auf die Methode.

- [ ] **Step 1: Failing tests schreiben**

In `tests/test_api_auth.py` den Test

```python
def test_method_name_is_case_insensitive():
    assert call("get").ok
```

ersetzen durch

```python
@pytest.mark.parametrize("method", ["get", "Get", "put", "pOST", "delete", "poſt"])
def test_method_names_are_case_sensitive(method):
    # RFC 9110: Methoden sind case-sensitive. `authorize` und das Routing
    # (exakter Vergleich) sehen sonst zwei verschiedene Anfragen — und mit
    # schreibenden Methoden zählt das.
    result = call(method)
    assert (result.status, result.code) == (405, "method_not_allowed")


@pytest.mark.parametrize("method", [None, 5, b"GET"])
def test_non_string_methods_are_405_not_an_exception(method):
    result = authorize(method, {"Host": GOOD_HOST, "Authorization": f"Bearer {TOKEN}"},
                       POLICY, VERIFY)
    assert result.status == 405
```

- [ ] **Step 2: Fehlschlag prüfen**

Run: `python3 -m pytest tests/test_api_auth.py -q -p no:cacheprovider`
Expected: FAIL (`test_method_names_are_case_sensitive[get]` liefert 200, die Nicht-String-Fälle werfen `AttributeError`).

- [ ] **Step 3: Implementieren**

In `src/api_auth.py`, in `authorize`, die Zeilen

```python
    method = method.upper()
    if method not in ALLOWED_METHODS:
        return AuthResult(405, "method_not_allowed")
```

ersetzen durch

```python
    # Methoden sind case-sensitive (RFC 9110): kein `.upper()`. Das Routing
    # vergleicht exakt; eine großgeschriebene Sicht hier und eine rohe dort wären
    # zwei Wahrheiten über dieselbe Anfrage.
    if method not in ALLOWED_METHODS:
        return AuthResult(405, "method_not_allowed")
```

- [ ] **Step 4: Tests laufen lassen**

Run: `python3 -m pytest tests/test_api_auth.py tests/test_api_server.py tests/test_type_annotations.py tests/test_catch_all_handlers.py -q -p no:cacheprovider`
Expected: alle PASS (der Server-Test `test_options_head_patch_trace_and_unknown_methods_are_405_with_allow` bleibt grün, er nutzt nur Großbuchstaben).

- [ ] **Step 5: Commit**

```bash
git add src/api_auth.py tests/test_api_auth.py
git commit -m "$(cat <<'EOF'
fix(api): authorize vergleicht die Methode exakt (#92)

Kein .upper(): Methoden sind case-sensitive, und authorize und das Routing
sollen dieselbe Sicht auf die Anfrage haben, jetzt wo es schreibende
Methoden gibt. Nicht-String-Methoden sind 405 statt einer Exception.

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: `api_entry_write` — Body, Tagesprüfung, Warnungen (Tk-frei)

**Files:**
- Create: `src/api_entry_write.py`
- Create: `tests/test_api_entry_write.py`
- Modify: `tests/test_type_annotations.py` (`"src/api_entry_write.py"` in `ANNOTATED_MODULES`)

**Interfaces:**
- Consumes: `time_utils.validate_slots(slots, with_pause=True) -> (ok, msg)`, `parse_time`; `weekly_limit.check_week_limit(settings, all_entries, date_str) -> dict | None`; `pause_requirement.check_day_pause(settings, slots) -> dict | None`; `ConflictsStore.unresolved_entry_keys() -> set[str]`; `VacationStore.period_for_date(date_str) -> dict | None` (mit `days: {ISO: minutes}`, `name`).
- Produces (Task 3 verlässt sich darauf):
  - `MIN_YEAR = 2000`, `MAX_YEAR = 2100`, `MAX_SLOTS = 50`, `MAX_CATEGORY_LEN = 100`
  - `WriteError(status: int, code: str, message: str)` (Exception mit Attributen `status`, `code`, `message`)
  - `parse_day_body(body: bytes) -> list[dict[str, Any]]` (Slots mit allen vier Schlüsseln; wirft `WriteError`)
  - `check_date_range(day: datetime.date) -> None` (wirft `WriteError` 422 `date_out_of_range`)
  - `check_day_writable(date_str: str, *, conflicts_store: Any, vacation_store: Any, for_save: bool) -> None` (wirft `WriteError` 409)
  - `warnings_for(settings: Any, all_entries: dict[str, Any], date_str: str, slots: list[dict[str, Any]]) -> list[dict[str, Any]]`

- [ ] **Step 1: Failing tests schreiben**

`tests/test_api_entry_write.py`:

```python
# tests/test_api_entry_write.py
import datetime
import json

import pytest

from src import api_entry_write as w
from src.api_entry_write import WriteError
from src.conflicts_store import ConflictsStore
from src.vacations import VacationStore


def body(slots=None, **extra):
    payload = {"slots": [{"start": "08:00", "end": "12:00"}] if slots is None else slots}
    payload.update(extra)
    return json.dumps(payload).encode("utf-8")


def error_of(callable_, *args, **kwargs):
    with pytest.raises(WriteError) as info:
        callable_(*args, **kwargs)
    return info.value


# --- parse_day_body: Erfolg ---------------------------------------------------------

def test_minimal_slot_gets_the_defaults():
    assert w.parse_day_body(body()) == [
        {"start": "08:00", "end": "12:00", "pause": 0, "kategorie": ""}]


def test_full_slot_and_the_category_is_stripped():
    slots = w.parse_day_body(body([
        {"start": "08:00", "end": "12:00", "pause": 15, "kategorie": "  Projekt A  "},
        {"start": "12:00", "end": "16:30"}]))      # angrenzend ist keine Überlappung

    assert slots == [
        {"start": "08:00", "end": "12:00", "pause": 15, "kategorie": "Projekt A"},
        {"start": "12:00", "end": "16:30", "pause": 0, "kategorie": ""}]


def test_a_non_ascii_category_is_fine():
    slots = w.parse_day_body(body([{"start": "08:00", "end": "09:00",
                                    "kategorie": "Büro – Übergabe ✓"}]))
    assert slots[0]["kategorie"] == "Büro – Übergabe ✓"


# --- Review Focus 1: Form des Bodys -------------------------------------------------------

@pytest.mark.parametrize("raw", [
    b"", b"{", b"\xff\xfe", b"nicht json", b"[]", b"null", b'"x"', b"5", b"true",
    b"{}", b'{"slots": 5}', b'{"slots": {}}', b'{"slots": "x"}', b'{"slots": null}',
    b'{"slots": [], "x": 1}', b'{"slotz": []}',
    b'{"slots": NaN}', b'{"slots": Infinity}', b'{"slots": [{"start": NaN}]}',
    b'{"slots": [], "slots": []}',                       # doppelter Schlüssel
])
def test_a_malformed_body_is_400(raw):
    error = error_of(w.parse_day_body, raw)
    assert error.status == 400 and error.code in {"invalid_json", "invalid_body"}


@pytest.mark.parametrize("raw", [
    b"[" * 100_000,                                       # RecursionError im Parser
    b'{"slots": ' + b"[" * 100_000 + b"}",
])
def test_deeply_nested_json_is_400_never_an_exception(raw):
    error = error_of(w.parse_day_body, raw)
    assert error.status == 400


def test_an_empty_slot_list_is_422_and_points_to_delete():
    error = error_of(w.parse_day_body, body([]))
    assert (error.status, error.code) == (422, "empty_slots")
    assert "DELETE" in error.message


def test_too_many_slots_is_422():
    slots = [{"start": f"{h:02d}:00", "end": f"{h:02d}:30"} for h in range(24)] * 3
    error = error_of(w.parse_day_body, body(slots))
    assert (error.status, error.code) == (422, "too_many_slots")


@pytest.mark.parametrize("slot", [
    "08:00", 5, None, [], [1, 2],
    {}, {"start": "08:00"}, {"end": "12:00"},
    {"start": "08:00", "end": "12:00", "extra": 1},
    {"start": "08:00", "end": "12:00", "Pause": 5},
])
def test_a_slot_of_the_wrong_shape_is_422(slot):
    error = error_of(w.parse_day_body, body([slot]))
    assert (error.status, error.code) == (422, "invalid_slot")


@pytest.mark.parametrize("value", [
    "8:00", "24:00", "08:60", "0800", "08:0", "08:000", " 08:00", "08:00 ", "08:00\n",
    "٠٨:٠٠", "", "ab:cd", 800, None, True, ["08:00"],
])
@pytest.mark.parametrize("field", ["start", "end"])
def test_times_must_be_exactly_hh_mm(field, value):
    slot = {"start": "08:00", "end": "12:00"}
    slot[field] = value
    error = error_of(w.parse_day_body, body([slot]))
    assert (error.status, error.code) == (422, "invalid_time")


@pytest.mark.parametrize("pause", [True, False, "30", 1.5, 30.0, -1, None, [5], {"m": 5}])
def test_pause_must_be_a_whole_number_of_minutes(pause):
    error = error_of(w.parse_day_body, body([{"start": "08:00", "end": "12:00", "pause": pause}]))
    assert (error.status, error.code) == (422, "invalid_pause")


@pytest.mark.parametrize("category", [5, None, ["a"], {"a": 1}, True,
                                      "a\nb", "a\x00b", "a\x7fb", "a\tb", "x" * 101])
def test_a_bad_category_is_422(category):
    error = error_of(w.parse_day_body, body([{"start": "08:00", "end": "12:00",
                                              "kategorie": category}]))
    assert (error.status, error.code) == (422, "invalid_category")


def test_a_category_of_exactly_100_characters_is_fine():
    slots = w.parse_day_body(body([{"start": "08:00", "end": "12:00", "kategorie": "x" * 100}]))
    assert len(slots[0]["kategorie"]) == 100


@pytest.mark.parametrize("slots", [
    [{"start": "12:00", "end": "08:00"}],                                     # Ende vor Start
    [{"start": "08:00", "end": "08:00"}],                                     # Ende = Start
    [{"start": "08:00", "end": "09:00", "pause": 60}],                        # Pause = Arbeitszeit
    [{"start": "08:00", "end": "12:00"}, {"start": "11:00", "end": "13:00"}],  # Überlappung
])
def test_the_ui_rules_for_slots_apply(slots):
    error = error_of(w.parse_day_body, body(slots))
    assert (error.status, error.code) == (422, "invalid_slots")
    assert error.message


# --- check_date_range ------------------------------------------------------------------------

@pytest.mark.parametrize("day", [datetime.date(2000, 1, 1), datetime.date(2026, 10, 7),
                                 datetime.date(2100, 12, 31)])
def test_dates_inside_the_range_pass(day):
    w.check_date_range(day)


@pytest.mark.parametrize("day", [datetime.date(1999, 12, 31), datetime.date(1970, 1, 1),
                                 datetime.date(2101, 1, 1), datetime.date(1, 1, 1)])
def test_dates_outside_the_range_are_422(day):
    error = error_of(w.check_date_range, day)
    assert (error.status, error.code) == (422, "date_out_of_range")


# --- check_day_writable ---------------------------------------------------------------------------

@pytest.fixture
def conflicts(tmp_path):
    store = ConflictsStore(str(tmp_path / "conflicts.json"))
    store.save_all([
        {"id": "c-1", "kind": "entry", "key": "2026-05-14", "resolved": False},
        {"id": "c-2", "kind": "entry", "key": "2026-05-15", "resolved": True},
        {"id": "c-3", "kind": "setting", "key": "2026-05-16", "resolved": False},
    ])
    return store


@pytest.fixture
def vacations(tmp_path):
    store = VacationStore(str(tmp_path / "vacations.json"))
    store.save(None, "Sommer", "2026-07-01", "2026-07-05", {
        "2026-07-01": 480, "2026-07-02": 480, "2026-07-03": 0,     # 3.: Feiertag/Wochenende
        "2026-07-04": 0, "2026-07-05": 0})
    return store


@pytest.mark.parametrize("for_save", [True, False])
def test_an_unresolved_entry_conflict_blocks_save_and_delete(conflicts, for_save):
    error = error_of(w.check_day_writable, "2026-05-14", conflicts_store=conflicts,
                     vacation_store=None, for_save=for_save)
    assert (error.status, error.code) == (409, "sync_conflict")


@pytest.mark.parametrize("day", ["2026-05-15", "2026-05-16", "2026-05-17"])
def test_resolved_other_kind_and_unrelated_days_are_free(conflicts, day):
    w.check_day_writable(day, conflicts_store=conflicts, vacation_store=None, for_save=True)


def test_a_vacation_day_with_minutes_blocks_saving(vacations):
    error = error_of(w.check_day_writable, "2026-07-01", conflicts_store=None,
                     vacation_store=vacations, for_save=True)
    assert (error.status, error.code) == (409, "vacation_day")
    assert "Sommer" in error.message


def test_a_vacation_day_does_not_block_deleting(vacations):
    w.check_day_writable("2026-07-01", conflicts_store=None, vacation_store=vacations,
                         for_save=False)


@pytest.mark.parametrize("day", ["2026-07-03", "2026-07-04", "2026-06-30", "2026-07-06"])
def test_zero_minute_days_and_days_outside_the_period_are_free(vacations, day):
    w.check_day_writable(day, conflicts_store=None, vacation_store=vacations, for_save=True)


def test_missing_stores_mean_no_extra_rules():
    w.check_day_writable("2026-05-14", conflicts_store=None, vacation_store=None, for_save=True)


# --- warnings_for ----------------------------------------------------------------------------------

LIMIT = {"werkstudent_limit_enabled": True, "werkstudent_limit_start": "2026-01-01",
         "werkstudent_limit_end": "2026-12-31", "werkstudent_limit_max_hours": 20,
         "pause_warning_enabled": True}


def five_hours(pause=30):
    return {"slots": [{"start": "09:00", "end": "14:00", "pause": pause, "kategorie": ""}]}


def week_entries():
    # Mo–Do 2026-10-05..08, je 5 h (Pause 30 min: netto 4:30 h)
    return {f"2026-10-0{d}": five_hours() for d in (5, 6, 7, 8)}


def test_the_weekly_limit_is_a_warning_with_the_new_day_counted():
    slots = [{"start": "08:00", "end": "13:00", "pause": 0, "kategorie": ""}]    # +5 h
    warnings = w.warnings_for(LIMIT, week_entries(), "2026-10-09", slots)

    limit = [x for x in warnings if x["code"] == "weekly_limit"]
    assert len(limit) == 1
    assert limit[0]["limit_minutes"] == 1200
    assert limit[0]["total_minutes"] == 4 * 270 + 300 and limit[0]["iso_week"] == 41


def test_the_new_day_replaces_the_old_one_instead_of_counting_twice():
    entries = week_entries()
    entries["2026-10-09"] = {"slots": [{"start": "06:00", "end": "20:00", "pause": 0,
                                        "kategorie": ""}]}          # 14 h, wird ersetzt
    slots = [{"start": "08:00", "end": "09:00", "pause": 0, "kategorie": ""}]

    warnings = w.warnings_for(LIMIT, entries, "2026-10-09", slots)

    assert [x for x in warnings if x["code"] == "weekly_limit"] == []


def test_the_pause_requirement_is_a_warning():
    slots = [{"start": "08:00", "end": "16:00", "pause": 0, "kategorie": ""}]    # 8 h ohne Pause

    warnings = w.warnings_for(LIMIT, {}, "2026-10-09", slots)

    assert {"code": "pause_requirement", "worked_minutes": 480,
            "actual_pause_minutes": 0, "required_pause_minutes": 30} in warnings


def test_a_sufficient_pause_gives_no_warning():
    slots = [{"start": "08:00", "end": "16:00", "pause": 30, "kategorie": ""}]
    assert w.warnings_for(LIMIT, {}, "2026-10-09", slots) == []


def test_disabled_checks_give_no_warnings():
    off = {**LIMIT, "werkstudent_limit_enabled": False, "pause_warning_enabled": False}
    slots = [{"start": "06:00", "end": "20:00", "pause": 0, "kategorie": ""}]
    assert w.warnings_for(off, week_entries(), "2026-10-09", slots) == []


def test_warnings_do_not_mutate_the_callers_entries():
    entries = week_entries()
    before = json.dumps(entries, sort_keys=True)
    w.warnings_for(LIMIT, entries, "2026-10-09",
                   [{"start": "08:00", "end": "13:00", "pause": 0, "kategorie": ""}])
    assert json.dumps(entries, sort_keys=True) == before
```

- [ ] **Step 2: Fehlschlag prüfen**

Run: `python3 -m pytest tests/test_api_entry_write.py -q -p no:cacheprovider`
Expected: FAIL beim Import (`ImportError: cannot import name 'api_entry_write'`).

- [ ] **Step 3: Implementieren**

`src/api_entry_write.py`:

```python
# src/api_entry_write.py
"""Schreibpfad der lokalen API für Ist-Zeiten (#92, PR 4), Tk-frei und ohne Socket.

Dieses Modul **nimmt Fremddaten** (der Body kommt von einem Skript) und bildet
die Regeln nach, die die UI an ihren Eingängen heute durchsetzt, weil `Storage`
sie nicht kennt:

- Validierung der Slots über `time_utils.validate_slots` (pro Slot Zeit/Pause,
  Überlappungsfreiheit) — dazu die Form (strenges JSON, genau `HH:MM`, nur die
  vier bekannten Felder) und Grenzen (Slot-Anzahl, Kategorielänge, Jahr);
- Sperren: ungelöster Sync-Konflikt am Tag (die UI öffnet dort den
  Konfliktdialog statt des Tages-Dialogs) und Urlaubsminuten > 0 (Urlaub und
  Arbeitszeit schließen sich aus; 0-Minuten-Tage einer Periode bleiben
  beschreibbar);
- Warnungen zu Wochenlimit und Pausenpflicht, nie ein Fehler — wie in der UI,
  wo sie nur nachfragen.

Fehler sind `WriteError` mit Status und Code; die Routen machen daraus die
JSON-Antwort. Nichts hier hält einen Lock — den nimmt der Aufrufer um Prüfen
und Speichern gemeinsam.
"""
from __future__ import annotations

import datetime
import json
import re
from typing import Any

from src.pause_requirement import check_day_pause
from src.time_utils import parse_time, validate_slots
from src.weekly_limit import check_week_limit

MIN_YEAR = 2000
MAX_YEAR = 2100
MAX_SLOTS = 50
MAX_CATEGORY_LEN = 100

# Nur ASCII-Ziffern: `\d` matcht auch Ziffern anderer Schriften, und
# `parse_time` akzeptiert "8:00" — gespeichert werden soll genau "08:00".
_TIME_RE = re.compile(r"[0-9]{2}:[0-9]{2}")
_SLOT_KEYS = frozenset({"start", "end", "pause", "kategorie"})
_REQUIRED_KEYS = frozenset({"start", "end"})


class WriteError(Exception):
    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


def _reject_constant(name: str) -> Any:
    raise ValueError(f"{name} ist kein gültiger JSON-Wert")


def _reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"doppelter Schlüssel {key!r}")
        result[key] = value
    return result


def _load_json(body: bytes) -> Any:
    try:
        return json.loads(body.decode("utf-8"), parse_constant=_reject_constant,
                          object_pairs_hook=_reject_duplicates)
    except (ValueError, RecursionError):
        # ValueError deckt kaputtes JSON, UnicodeDecodeError, NaN/Infinity und
        # doppelte Schlüssel; RecursionError die tiefe Verschachtelung (ein
        # 1-MiB-Body aus lauter "[" wäre sonst eine 500).
        raise WriteError(400, "invalid_json", "Der Body ist kein gültiges JSON.") from None


def _parse_time_field(value: Any, label: str, index: int) -> str:
    if not isinstance(value, str) or not _TIME_RE.fullmatch(value) or parse_time(value) is None:
        raise WriteError(422, "invalid_time",
                         f"Slot {index}: {label} muss genau HH:MM sein (00:00 bis 23:59).")
    return value


def _parse_category(value: Any, index: int) -> str:
    if not isinstance(value, str):
        raise WriteError(422, "invalid_category", f"Slot {index}: kategorie muss Text sein.")
    value = value.strip()
    if len(value) > MAX_CATEGORY_LEN:
        raise WriteError(422, "invalid_category",
                         f"Slot {index}: kategorie darf höchstens {MAX_CATEGORY_LEN} Zeichen haben.")
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in value):
        raise WriteError(422, "invalid_category",
                         f"Slot {index}: kategorie darf keine Steuerzeichen enthalten.")
    return value


def _parse_slot(item: Any, index: int) -> dict[str, Any]:
    if not isinstance(item, dict):
        raise WriteError(422, "invalid_slot", f"Slot {index} muss ein Objekt sein.")
    keys = set(item)
    if not _REQUIRED_KEYS <= keys or not keys <= _SLOT_KEYS:
        raise WriteError(
            422, "invalid_slot",
            f"Slot {index}: erlaubt sind start, end (Pflicht) sowie pause und kategorie; "
            f"gefunden: {sorted(keys)[:10]}.")
    pause = item.get("pause", 0)
    if not isinstance(pause, int) or isinstance(pause, bool):
        raise WriteError(422, "invalid_pause",
                         f"Slot {index}: pause muss eine ganze Zahl (Minuten) sein.")
    return {
        "start": _parse_time_field(item["start"], "start", index),
        "end": _parse_time_field(item["end"], "end", index),
        "pause": pause,
        "kategorie": _parse_category(item.get("kategorie", ""), index),
    }


def parse_day_body(body: bytes) -> list[dict[str, Any]]:
    """Body → geprüfte Slots (`{start, end, pause, kategorie}`, alle vier Felder).
    Wirft `WriteError`: 400 bei kaputtem JSON oder falscher Form, 422 bei
    ungültigem Slot."""
    data = _load_json(body)
    if not isinstance(data, dict) or set(data) != {"slots"} or not isinstance(data["slots"], list):
        raise WriteError(400, "invalid_body", 'Erwartet wird {"slots": [...]}.')
    raw = data["slots"]
    if not raw:
        raise WriteError(422, "empty_slots",
                         "Eine leere Slot-Liste speichert nichts — zum Löschen DELETE benutzen.")
    if len(raw) > MAX_SLOTS:
        raise WriteError(422, "too_many_slots", f"Höchstens {MAX_SLOTS} Slots je Tag.")
    slots = [_parse_slot(item, i + 1) for i, item in enumerate(raw)]
    ok, message = validate_slots(slots, with_pause=True)
    if not ok:
        raise WriteError(422, "invalid_slots", message)
    return slots


def check_date_range(day: datetime.date) -> None:
    """Ein Skript-Fehler mit Jahr 1970 würde sonst Daten und Tombstones dauerhaft
    im Sync hinterlassen."""
    if not MIN_YEAR <= day.year <= MAX_YEAR:
        raise WriteError(422, "date_out_of_range",
                         f"Das Jahr muss zwischen {MIN_YEAR} und {MAX_YEAR} liegen.")


def check_day_writable(date_str: str, *, conflicts_store: Any, vacation_store: Any,
                       for_save: bool) -> None:
    """Die Sperren der UI. Ungelöster Sync-Konflikt: `PUT` und `DELETE` — die
    Ist-Zeit steht zur Debatte, ein Schreiben würde einen Kandidaten
    überschreiben. Urlaubsminuten > 0: nur `PUT` (Löschen ist der Weg aus der
    Sackgasse); 0-Minuten-Tage einer Periode sind kein Urlaubstag."""
    if conflicts_store is not None and date_str in conflicts_store.unresolved_entry_keys():
        raise WriteError(409, "sync_conflict",
                         "Für diesen Tag gibt es einen ungelösten Sync-Konflikt. "
                         "Zuerst in der App auflösen.")
    if for_save and vacation_store is not None:
        period = vacation_store.period_for_date(date_str)
        if period is not None and period.get("days", {}).get(date_str, 0):
            raise WriteError(409, "vacation_day",
                             f"Für diesen Tag ist Urlaub eingetragen "
                             f"(„{period.get('name', '')}“). An einem Urlaubstag lässt sich "
                             "keine Arbeitszeit erfassen; den Urlaub zuerst in der App löschen.")


def warnings_for(settings: Any, all_entries: dict[str, Any], date_str: str,
                 slots: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Wochenlimit und Pausenpflicht gegen den simulierten Stand **nach** dem
    Speichern (der neue Tag ersetzt den alten). Nur Warnungen, nie ein Fehler."""
    simulated = dict(all_entries)
    simulated[date_str] = {"slots": slots}
    found: list[dict[str, Any]] = []
    overshoot = check_week_limit(settings, simulated, date_str)
    if overshoot is not None:
        found.append({"code": "weekly_limit", **overshoot})
    violation = check_day_pause(settings, slots)
    if violation is not None:
        found.append({"code": "pause_requirement", **violation})
    return found
```

In `tests/test_type_annotations.py` die Liste `ANNOTATED_MODULES` um `"src/api_entry_write.py",` ergänzen (hinter `"src/api_service.py",`).

- [ ] **Step 4: Tests laufen lassen**

Run: `python3 -m pytest tests/test_api_entry_write.py tests/test_type_annotations.py tests/test_catch_all_handlers.py -q -p no:cacheprovider`
Expected: alle PASS. Schlägt ein Test der tiefen Verschachtelung fehl, weil Python `RecursionError` an anderer Stelle wirft (z. B. beim Freigeben), den Fehler nicht wegfangen, sondern die Stelle bestimmen und dort abfangen.

- [ ] **Step 5: Commit**

```bash
git add src/api_entry_write.py tests/test_api_entry_write.py tests/test_type_annotations.py
git commit -m "$(cat <<'EOF'
feat(api): Schreibpfad für Ist-Zeiten, Tk-frei (#92)

Body → geprüfte Slots (strenges JSON, genau HH:MM, nur die vier Felder,
Grenzen), Sperren der UI (Sync-Konflikt, Urlaubsminuten > 0), Datumsbereich
2000–2100 und nicht blockierende Warnungen zu Wochenlimit und Pausenpflicht.

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: `PUT`/`DELETE /v1/entries/{date}` in `api_routes`

**Files:**
- Modify: `src/api_routes.py`
- Modify: `tests/test_api_routes.py`
- Modify: `tests/test_api_server.py`

**Interfaces:**
- Consumes: alles aus Task 2; `Storage.get(date) -> {"slots": [...]} | None`, `Storage.get_all()`, `Storage.save(date, slots)`, `Storage.delete(date)`.
- Produces (Task 4 verlässt sich darauf):
  - `ApiContext(storage, settings, app_version, now=…, data_lock=None, conflicts_store=None, vacation_store=None, on_change=<no-op>)` — die vier neuen Felder haben Defaults, bestehende Aufrufer bleiben gültig.
  - `PUT /v1/entries/{date}` → `200 {"date", "slots", "changed": bool, "warnings": [...]}`
  - `DELETE /v1/entries/{date}` → `200 {"date", "deleted": true}`
  - `handle` fängt `WriteError` neben `_ApiError`.

- [ ] **Step 1: Failing tests schreiben**

In `tests/test_api_routes.py` (Importe oben um `import logging`, `import threading`, `from src.conflicts_store import ConflictsStore`, `from src.vacations import VacationStore` ergänzen; `json` ist neu: `import json`):

Den bestehenden Test

```python
@pytest.mark.parametrize("path,allow", [("/v1/status", "GET"), ("/v1/entries", "GET"),
                                        ("/v1/entries/2026-01-05", "GET")])
@pytest.mark.parametrize("method", ["POST", "PUT", "DELETE"])
def test_wrong_method_on_a_known_path_is_405_with_allow(storage, path, allow, method):
    response = call(path, make_ctx(storage), method=method)
    assert (response.status, response.body["error"]["code"]) == (405, "method_not_allowed")
    assert response.headers["Allow"] == allow
```

ersetzen durch

```python
@pytest.mark.parametrize("path,allow,methods", [
    ("/v1/status", "GET", ["POST", "PUT", "DELETE"]),
    ("/v1/entries", "GET", ["POST", "PUT", "DELETE"]),
    ("/v1/entries/2026-01-05", "DELETE, GET, PUT", ["POST", "PATCH"]),
])
def test_wrong_method_on_a_known_path_is_405_with_allow(storage, path, allow, methods):
    for method in methods:
        response = call(path, make_ctx(storage), method=method)
        assert (response.status, response.body["error"]["code"]) == (405, "method_not_allowed")
        assert response.headers["Allow"] == allow


@pytest.mark.parametrize("method", ["put", "Put", "delete", "get"])
def test_method_names_are_matched_exactly(storage, method):
    response = call("/v1/entries/2026-01-05", make_ctx(storage), method=method)
    assert response.status == 405
```

Am Dateiende anfügen:

```python
# --- PUT/DELETE /v1/entries/{date} (PR 4) -----------------------------------------------------

DAY = "2026-10-07"
SLOTS_BODY = json.dumps({"slots": [
    {"start": "08:00", "end": "12:00", "pause": 0, "kategorie": "Projekt"}]}).encode()
OTHER_BODY = json.dumps({"slots": [{"start": "09:00", "end": "10:00"}]}).encode()


class TrackingLock:
    """Ein RLock, der mitzählt, ob er gerade gehalten wird."""

    def __init__(self):
        self._lock = threading.RLock()
        self.depth = 0

    def __enter__(self):
        self._lock.acquire()
        self.depth += 1
        return self

    def __exit__(self, *exc):
        self.depth -= 1
        self._lock.release()


class Env:
    """Echter Storage plus Konflikt- und Urlaubsstore, ein Zähler für on_change."""

    def __init__(self, tmp_path, settings=None):
        self.storage = Storage(str(tmp_path / "zeiterfassung.json"), device_id="dev")
        self.conflicts = ConflictsStore(str(tmp_path / "conflicts.json"))
        self.vacations = VacationStore(str(tmp_path / "vacations.json"))
        self.lock = TrackingLock()
        self.changes = 0
        self.ctx = ApiContext(
            storage=self.storage, settings={} if settings is None else settings,
            app_version=lambda: "t", data_lock=self.lock,
            conflicts_store=self.conflicts, vacation_store=self.vacations,
            on_change=self._on_change)

    def _on_change(self):
        self.changes += 1

    def put(self, body, day=DAY, query=None):
        return handle(ApiRequest("PUT", f"/v1/entries/{day}", query or {}, body), self.ctx, LOCAL)

    def delete(self, day=DAY):
        return handle(ApiRequest("DELETE", f"/v1/entries/{day}", {}), self.ctx, LOCAL)


@pytest.fixture
def env(tmp_path):
    return Env(tmp_path)


def code(response):
    return response.body["error"]["code"]


def test_put_creates_the_day_and_reports_it(env):
    response = env.put(SLOTS_BODY)

    assert response.status == 200
    assert response.body == {
        "date": DAY,
        "slots": [{"start": "08:00", "end": "12:00", "pause": 0, "kategorie": "Projekt"}],
        "changed": True, "warnings": []}
    assert env.storage.get(DAY)["slots"] == response.body["slots"]
    assert env.changes == 1


def test_put_replaces_the_whole_day(env):
    env.put(SLOTS_BODY)

    response = env.put(OTHER_BODY)

    assert response.body["changed"] is True
    assert env.storage.get(DAY)["slots"] == [
        {"start": "09:00", "end": "10:00", "pause": 0, "kategorie": ""}]


def test_an_identical_put_neither_saves_nor_notifies(env, monkeypatch):
    env.put(SLOTS_BODY)
    saves = []
    real_save = env.storage.save
    monkeypatch.setattr(env.storage, "save", lambda *a, **k: (saves.append(a), real_save(*a, **k)))
    changes_before = env.changes

    response = env.put(SLOTS_BODY)

    assert response.status == 200 and response.body["changed"] is False
    assert saves == [] and env.changes == changes_before


def test_a_changed_put_saves_exactly_once_and_notifies_once(env, monkeypatch):
    env.put(SLOTS_BODY)
    saves = []
    real_save = env.storage.save
    monkeypatch.setattr(env.storage, "save", lambda *a, **k: (saves.append(a), real_save(*a, **k)))
    changes_before = env.changes

    env.put(OTHER_BODY)

    assert len(saves) == 1 and env.changes == changes_before + 1


def test_the_get_after_a_put_returns_the_same_slots(env):
    env.put(SLOTS_BODY)
    got = handle(ApiRequest("GET", f"/v1/entries/{DAY}", {}), env.ctx, LOCAL)
    assert got.body["slots"] == env.put(SLOTS_BODY).body["slots"]


def test_put_revives_a_tombstoned_day(env):
    env.put(SLOTS_BODY)
    env.storage.delete(DAY)
    assert env.storage.get(DAY) is None

    response = env.put(OTHER_BODY)

    assert response.body["changed"] is True and env.storage.get(DAY) is not None


# --- Warnungen blockieren nie ----------------------------------------------------------------------

def test_warnings_are_reported_and_the_day_is_saved_anyway(tmp_path):
    env = Env(tmp_path, settings={"pause_warning_enabled": True})
    body = json.dumps({"slots": [{"start": "08:00", "end": "16:00"}]}).encode()   # 8 h, keine Pause

    response = env.put(body)

    assert response.status == 200
    assert [x["code"] for x in response.body["warnings"]] == ["pause_requirement"]
    assert env.storage.get(DAY) is not None and env.changes == 1


# --- Sperren ------------------------------------------------------------------------------------------

def test_put_on_a_conflict_day_is_409_and_changes_nothing(env):
    env.conflicts.save_all([{"id": "c", "kind": "entry", "key": DAY, "resolved": False}])

    response = env.put(SLOTS_BODY)

    assert (response.status, code(response)) == (409, "sync_conflict")
    assert env.storage.get(DAY) is None and env.changes == 0


def test_delete_on_a_conflict_day_is_409(env):
    env.storage.save(DAY, [{"start": "08:00", "end": "09:00"}])
    env.conflicts.save_all([{"id": "c", "kind": "entry", "key": DAY, "resolved": False}])

    response = env.delete()

    assert (response.status, code(response)) == (409, "sync_conflict")
    assert env.storage.get(DAY) is not None


def test_put_on_a_vacation_day_is_409_but_a_zero_minute_day_is_allowed(env):
    env.vacations.save(None, "Sommer", "2026-10-07", "2026-10-09",
                       {"2026-10-07": 480, "2026-10-08": 0, "2026-10-09": 480})

    blocked = env.put(SLOTS_BODY, day="2026-10-07")
    allowed = env.put(SLOTS_BODY, day="2026-10-08")

    assert (blocked.status, code(blocked)) == (409, "vacation_day")
    assert allowed.status == 200 and env.storage.get("2026-10-08") is not None
    assert env.storage.get("2026-10-07") is None


def test_checks_and_save_run_under_the_shared_lock(env, monkeypatch):
    held = []
    real_unresolved = env.conflicts.unresolved_entry_keys
    real_save = env.storage.save
    monkeypatch.setattr(env.conflicts, "unresolved_entry_keys",
                        lambda: (held.append(("check", env.lock.depth)), real_unresolved())[1])
    monkeypatch.setattr(env.storage, "save",
                        lambda *a, **k: (held.append(("save", env.lock.depth)), real_save(*a, **k)))

    env.put(SLOTS_BODY)

    assert held == [("check", 1), ("save", 1)]


def test_on_change_runs_after_the_lock_is_released(env):
    depths = []
    env.ctx = ApiContext(storage=env.storage, settings={}, app_version=lambda: "t",
                         data_lock=env.lock, conflicts_store=env.conflicts,
                         vacation_store=env.vacations,
                         on_change=lambda: depths.append(env.lock.depth))

    env.put(SLOTS_BODY)

    assert depths == [0]


def test_an_error_in_on_change_does_not_turn_a_saved_write_into_a_500(tmp_path, caplog):
    env = Env(tmp_path)

    def boom():
        raise RuntimeError("UI weg")

    env.ctx = ApiContext(storage=env.storage, settings={}, app_version=lambda: "t",
                         data_lock=env.lock, on_change=boom)

    with caplog.at_level(logging.ERROR):
        response = env.put(SLOTS_BODY)

    assert response.status == 200 and env.storage.get(DAY) is not None
    assert "on_change" in caplog.text


def test_put_works_without_lock_and_stores(tmp_path):
    storage = Storage(str(tmp_path / "z.json"), device_id="dev")
    ctx = ApiContext(storage=storage, settings={}, app_version=lambda: "t")

    response = handle(ApiRequest("PUT", f"/v1/entries/{DAY}", {}, SLOTS_BODY), ctx, LOCAL)

    assert response.status == 200 and storage.get(DAY) is not None


# --- Datum und Body ------------------------------------------------------------------------------------

@pytest.mark.parametrize("day,status,error", [
    ("2026-02-30", 400, "invalid_date"), ("20261007", 400, "invalid_date"), ("heute", 400, "invalid_date"),
    ("1999-12-31", 422, "date_out_of_range"), ("2101-01-01", 422, "date_out_of_range"),
    ("1970-01-01", 422, "date_out_of_range"),
])
def test_put_rejects_bad_dates(env, day, status, error):
    response = env.put(SLOTS_BODY, day=day)
    assert (response.status, code(response)) == (status, error)
    assert env.changes == 0


@pytest.mark.parametrize("body,status", [
    (b"{", 400), (b'{"slots": []}', 422),
    (json.dumps({"slots": [{"start": "8:00", "end": "12:00"}]}).encode(), 422),
])
def test_put_maps_body_errors_to_the_right_status(env, body, status):
    response = env.put(body)
    assert response.status == status
    assert env.storage.get(DAY) is None and env.changes == 0


def test_put_takes_no_query(env):
    response = env.put(SLOTS_BODY, query={"x": ["1"]})
    assert (response.status, code(response)) == (400, "unknown_parameter")


# --- DELETE ----------------------------------------------------------------------------------------------------

def test_delete_removes_the_day_and_leaves_a_tombstone(env):
    env.put(SLOTS_BODY)
    changes_before = env.changes

    response = env.delete()

    assert response.status == 200 and response.body == {"date": DAY, "deleted": True}
    assert env.storage.get(DAY) is None
    assert env.storage.get_all_raw()[DAY]["deleted"] is True
    assert env.changes == changes_before + 1


def test_delete_of_a_missing_or_tombstoned_day_is_404(env):
    assert env.delete().status == 404
    env.put(SLOTS_BODY)
    env.delete()
    changes = env.changes

    again = env.delete()

    assert (again.status, code(again)) == (404, "not_found") and env.changes == changes


def test_delete_with_a_bad_date_is_400(env):
    assert (env.delete("2026-02-30").status, code(env.delete("2026-02-30"))) == (400, "invalid_date")


def test_delete_runs_under_the_lock(env, monkeypatch):
    env.put(SLOTS_BODY)
    seen = []
    real_delete = env.storage.delete
    monkeypatch.setattr(env.storage, "delete",
                        lambda *a, **k: (seen.append(env.lock.depth), real_delete(*a, **k)))

    env.delete()

    assert seen == [1]
```

In `tests/test_api_server.py` am Dateiende anfügen (die Datei importiert `json`, `ApiServer`, `single_token_verifier`, `Storage`, `TOKEN`, `http_call`, `error_code`, `make_context`):

```python
# --- PUT/DELETE am Draht (PR 4) ------------------------------------------------------------------------

JSON_HEADERS = {"Content-Type": "application/json"}


def put_body(slots):
    return json.dumps({"slots": slots}).encode("utf-8")


def test_put_get_delete_roundtrip_over_http(tmp_path):
    changes = []
    context = make_context(tmp_path)
    context = ApiContext(storage=context.storage, settings=context.settings,
                         app_version=context.app_version, on_change=lambda: changes.append(1))
    srv = ApiServer(context, single_token_verifier(TOKEN))
    srv.start()
    try:
        slots = [{"start": "08:00", "end": "12:00", "pause": 0, "kategorie": "X"}]
        response, body, _ = http_call(srv, "PUT", "/v1/entries/2026-10-07", JSON_HEADERS,
                                      put_body(slots))
        assert response.status == 200 and body["changed"] is True and body["slots"] == slots

        got, got_body, _ = http_call(srv, "GET", "/v1/entries/2026-10-07")
        assert got.status == 200 and got_body["slots"] == slots

        deleted, deleted_body, _ = http_call(srv, "DELETE", "/v1/entries/2026-10-07")
        assert deleted.status == 200 and deleted_body["deleted"] is True
        assert http_call(srv, "GET", "/v1/entries/2026-10-07")[0].status == 404
        assert changes == [1, 1]
    finally:
        srv.stop()


def test_put_without_a_json_content_type_is_415_and_changes_nothing(server):
    response, body, _ = http_call(server, "PUT", "/v1/entries/2026-10-07",
                                  {"Content-Type": "text/plain"},
                                  put_body([{"start": "08:00", "end": "12:00"}]))
    assert (response.status, error_code(body)) == (415, "unsupported_media_type")
    assert http_call(server, "GET", "/v1/entries/2026-10-07")[0].status == 404


def test_an_unauthenticated_put_never_changes_anything(server):
    response, body, _ = http_call(server, "PUT", "/v1/entries/2026-10-07", JSON_HEADERS,
                                  put_body([{"start": "08:00", "end": "12:00"}]), token=None)
    assert response.status == 401
    assert http_call(server, "GET", "/v1/entries/2026-10-07")[0].status == 404


@pytest.mark.parametrize("method", ["put", "Put", "delete"])
def test_lowercase_write_methods_are_405_at_the_wire(server, method):
    response, _, _ = http_call(server, method, "/v1/entries/2026-10-07", JSON_HEADERS,
                               put_body([{"start": "08:00", "end": "12:00"}]))
    assert response.status == 405


def test_a_malformed_put_body_is_400_json(server):
    response, body, _ = http_call(server, "PUT", "/v1/entries/2026-10-07", JSON_HEADERS, b"{")
    assert (response.status, error_code(body)) == (400, "invalid_json")


def test_a_deeply_nested_put_body_is_400_not_500(server):
    response, body, _ = http_call(server, "PUT", "/v1/entries/2026-10-07", JSON_HEADERS,
                                  b"[" * 200_000)
    assert response.status == 400
```

Importzeile in `tests/test_api_server.py` ergänzen: `from src.api_routes import ApiContext` ist dort bereits importiert (prüfen, sonst ergänzen).

- [ ] **Step 2: Fehlschlag prüfen**

Run: `python3 -m pytest tests/test_api_routes.py tests/test_api_server.py -q -p no:cacheprovider`
Expected: FAIL (`ApiContext` kennt `data_lock` nicht, `PUT`/`DELETE` sind 405).

- [ ] **Step 3: Implementieren**

Alle Änderungen an `src/api_routes.py` als eindeutige Ersetzungen (jede muss genau einmal treffen):

1. Importe: `import datetime\nimport re\n` → `import contextlib\nimport datetime\nimport logging\nimport re\n`; hinter `from src.api_auth import SCOPE_LOCAL, Principal, require_scope` einfügen:
   ```python
   from src.api_entry_write import (
       WriteError, check_date_range, check_day_writable, parse_day_body, warnings_for,
   )
   ```
   und hinter den Importblock (vor `if TYPE_CHECKING:`): `_log = logging.getLogger(__name__)`.
2. Protokoll `EntryStore` um die Schreibmethoden erweitern: nach `def get(self, date_str: str) -> dict[str, Any] | None: ...` einfügen
   ```python

       def save(self, date_str: str, slots: list[dict[str, Any]]) -> None: ...

       def delete(self, date_str: str) -> None: ...
   ```
3. `ApiContext` ersetzen durch:
   ```python
   def _no_change() -> None:
       return None


   @dataclass(frozen=True)
   class ApiContext:
       storage: EntryStore
       settings: SettingsLike
       app_version: Callable[[], str]
       now: Callable[[], str] = utc_now_iso
       # Nur für schreibende Routen. `data_lock` ist der geteilte Store-`RLock`
       # der App (Prüfen, Konfliktcheck und Speichern laufen darunter);
       # `on_change` meldet der UI eine Änderung (App: `_marshal_to_ui(_refresh)`)
       # und läuft NACH dem Lock.
       data_lock: Any = None
       conflicts_store: Any = None
       vacation_store: Any = None
       on_change: Callable[[], None] = _no_change
   ```
4. Vor `@dataclass(frozen=True)\nclass Route:` einfügen:
   ```python
   def _locked(ctx: ApiContext) -> Any:
       return ctx.data_lock if ctx.data_lock is not None else contextlib.nullcontext()


   def _notify(ctx: ApiContext) -> None:
       try:
           ctx.on_change()
       except Exception:
           # Die Daten sind gespeichert; ein Fehler beim Neuzeichnen darf daraus
           # keine 500 machen (der Client würde den Schreibzugriff wiederholen).
           _log.exception("Lokale API: on_change nach dem Schreiben fehlgeschlagen")


   def _write_day(match: re.Match[str]) -> str:
       day_key = match.group(1)
       day = parse_date(day_key)
       if day is None:
           raise _ApiError(400, "invalid_date", "Erwartet YYYY-MM-DD.")
       check_date_range(day)
       return day_key


   def _put_entry(request: ApiRequest, ctx: ApiContext, match: re.Match[str]) -> ApiResponse:
       _only_params(request.query, frozenset())
       day_key = _write_day(match)
       slots = parse_day_body(request.body)
       with _locked(ctx):
           check_day_writable(day_key, conflicts_store=ctx.conflicts_store,
                              vacation_store=ctx.vacation_store, for_save=True)
           existing = ctx.storage.get(day_key)
           changed = existing is None or existing["slots"] != slots
           warnings = warnings_for(ctx.settings, ctx.storage.get_all(), day_key, slots)
           if changed:
               ctx.storage.save(day_key, slots)
           stored = ctx.storage.get(day_key)
       if changed:
           _notify(ctx)
       return ApiResponse(200, {"date": day_key,
                                "slots": stored["slots"] if stored else slots,
                                "changed": changed, "warnings": warnings})


   def _delete_entry(request: ApiRequest, ctx: ApiContext, match: re.Match[str]) -> ApiResponse:
       _only_params(request.query, frozenset())
       day_key = _write_day(match)
       with _locked(ctx):
           check_day_writable(day_key, conflicts_store=ctx.conflicts_store,
                              vacation_store=ctx.vacation_store, for_save=False)
           if ctx.storage.get(day_key) is None:
               raise _ApiError(404, "not_found", "Für diesen Tag gibt es keinen Eintrag.")
           ctx.storage.delete(day_key)
       _notify(ctx)
       return ApiResponse(200, {"date": day_key, "deleted": True})


   ```
5. Routentabelle: hinter der `Route("GET", re.compile(r"/v1/entries/([^/]+)"), _entry, SCOPE_LOCAL),`-Zeile einfügen
   ```python
       Route("PUT", re.compile(r"/v1/entries/([^/]+)"), _put_entry, SCOPE_LOCAL),
       Route("DELETE", re.compile(r"/v1/entries/([^/]+)"), _delete_entry, SCOPE_LOCAL),
   ```
6. In `handle`: `except _ApiError as exc:` → `except (_ApiError, WriteError) as exc:`.
7. Moduldocstring: den Absatz „Lesend: … und ändern nichts." ersetzen durch eine Fassung, die beide Seiten nennt: „Lesend: `GET /v1/status`, `/v1/entries`, `/v1/entries/{date}` (über `Storage.get_all()`/`get()`, ohne eigenen Lock). Schreibend: `PUT`/`DELETE /v1/entries/{date}`: Prüfen, Konfliktcheck und Speichern laufen unter `ctx.data_lock`, die Regeln der UI stehen in `api_entry_write`; `ctx.on_change` kommt danach, und nur bei einer Änderung.“

- [ ] **Step 4: Tests laufen lassen**

Run: `python3 -m pytest tests/test_api_routes.py tests/test_api_server.py tests/test_api_entry_write.py tests/test_api_auth.py tests/test_type_annotations.py tests/test_catch_all_handlers.py -q -p no:cacheprovider`
Expected: alle PASS. Danach die ganze Suite: `python3 -m pytest -q`.

- [ ] **Step 5: Commit**

```bash
git add src/api_routes.py tests/test_api_routes.py tests/test_api_server.py
git commit -m "$(cat <<'EOF'
feat(api): PUT und DELETE für Ist-Zeiten (#92)

Tag ersetzen (idempotent: identischer Inhalt schreibt nicht, on_change nur bei
Änderung) und löschen (Tombstone, 404 bei fehlendem Tag). Prüfen,
Konfliktcheck und Speichern laufen unter dem geteilten data_lock; Sync-Konflikt
und Urlaubsminuten sperren wie in der UI, Wochenlimit und Pausenpflicht
kommen als Warnungen.

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: Verdrahtung, Shutdown vor dem Push, Tab-Text

**Files:**
- Modify: `src/ui.py`
- Modify: `src/dialogs/settings_dialog/tab_api.py`
- Modify: `tests/test_api_wiring.py`

**Interfaces:**
- Consumes: `ApiContext(..., data_lock, conflicts_store, vacation_store, on_change)` (Task 3); `App._marshal_to_ui(fn, force=False)`, `App._refresh`, `self._data_lock`, `self.conflicts_store`, `self.vacation_store`.
- Produces: laufende API schreibt echte Daten; `_quit_with_sync_push` stoppt die API vor dem Sync-Push.

- [ ] **Step 1: Failing tests schreiben**

An `tests/test_api_wiring.py` anfügen:

```python
# --- PR 4: Schreibzugriff in der App ---------------------------------------------------------------

def test_the_api_context_carries_the_locks_stores_and_the_refresh_callback():
    init = _function("__init__")
    contexts = [n for n in ast.walk(init)
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                and n.func.id == "ApiContext"]
    assert len(contexts) == 1
    keywords = {kw.arg: ast.unparse(kw.value) for kw in contexts[0].keywords}
    assert keywords["data_lock"] == "self._data_lock"
    assert keywords["conflicts_store"] == "self.conflicts_store"
    assert keywords["vacation_store"] == "self.vacation_store"
    # Der Server-Thread berührt nie ein Widget: Neuzeichnen nur über den Marshal.
    assert keywords["on_change"] == "lambda: self._marshal_to_ui(self._refresh)"


def test_the_api_is_shut_down_before_the_final_sync_push():
    # Sonst könnte eine schreibende Route nach dem Push-Snapshot noch Daten
    # ändern, die dann nie mehr hochgeladen werden.
    func = _function("_quit_with_sync_push")
    shutdown = _top_level_statement(func, _self_calls(func, "_api", "shutdown")[0])
    push = _top_level_statement(func, _self_calls(func, "_sync", "push_on_quit")[0])
    assert func.body.index(shutdown) < func.body.index(push)
```

(`_top_level_statement` und `_self_calls` stehen schon in der Datei.)

- [ ] **Step 2: Fehlschlag prüfen**

Run: `python3 -m pytest tests/test_api_wiring.py -q -p no:cacheprovider`
Expected: FAIL (`KeyError: 'data_lock'` bzw. die Reihenfolge stimmt nicht).

- [ ] **Step 3: Verdrahten**

`src/ui.py`, drei Ersetzungen (jede genau einmal):

1. Kontext:
   ```python
           self._api = ApiService(
               self.settings, self.base_path,
               ApiContext(storage=self.storage, settings=self.settings,
                          app_version=installed_release_id),
               run=self._bg.run)
   ```
   wird zu
   ```python
           self._api = ApiService(
               self.settings, self.base_path,
               ApiContext(storage=self.storage, settings=self.settings,
                          app_version=installed_release_id,
                          data_lock=self._data_lock,
                          conflicts_store=self.conflicts_store,
                          vacation_store=self.vacation_store,
                          on_change=lambda: self._marshal_to_ui(self._refresh)),
               run=self._bg.run)
   ```
   (Der Kommentar über dem Block, „die Routen lesen über die Store-Methoden und halten keinen Lock", auf „lesende Routen halten keinen Lock, schreibende prüfen und speichern unter dem geteilten `data_lock`" anpassen.)
2. In `_quit_with_sync_push` die Zeilen
   ```python
           self._sync.push_on_quit()
           if self._tray is not None:
               self._tray.stop()
           self._api.shutdown()
           self._reminders.stop()
   ```
   ersetzen durch
   ```python
           # Zuerst die API: eine schreibende Route darf nach dem Push-Snapshot keine
           # Daten mehr ändern, die dann nie mehr hochgeladen würden.
           self._api.shutdown()
           self._sync.push_on_quit()
           if self._tray is not None:
               self._tray.stop()
           self._reminders.stop()
   ```

`src/dialogs/settings_dialog/tab_api.py`: im ersten `form.hint(...)` „können Zeiten lesen." → „können Zeiten lesen und eintragen."

- [ ] **Step 4: Tests laufen lassen**

Run: `python3 -m pytest tests/test_api_wiring.py tests/test_ui_delete.py tests/test_pixel_scaling.py -q -p no:cacheprovider`, danach `python3 -m pytest -q`.
Expected: alle PASS.

- [ ] **Step 5: Commit**

```bash
git add src/ui.py src/dialogs/settings_dialog/tab_api.py tests/test_api_wiring.py
git commit -m "$(cat <<'EOF'
feat(api): Schreibzugriff in die App verdrahten (#92)

ApiContext bekommt data_lock, Konflikt- und Urlaubsstore und ein
Neuzeichnen über _marshal_to_ui. Die API stoppt jetzt VOR dem finalen
Sync-Push, damit keine Route danach noch Daten ändert. Tab-Text: lesen und
eintragen.

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 5: Doku und Gesamtprüfung

**Files:**
- Modify: `README.md`, `docs/known-limitations.md`, `src/CLAUDE.md`, `docs/superpowers/specs/2026-10-06-lokale-api-design.md`

**Interfaces:** Consumes alles aus Task 1–4. Produces konsistente Doku; grüne Gesamtprüfung.

- [ ] **Step 1: Doku anpassen**

Als Wegwerf-Skript im Scratchpad ausführen (jede Ersetzung genau einmal; trifft ein Anker nicht, den Wortlaut in der Datei prüfen und den Anker anpassen, nie die Assertion entfernen):

```python
def rw(path):
    return open(path, encoding="utf-8", newline="").read()


def wr(path, text):
    open(path, "w", encoding="utf-8", newline="").write(text)


def sub(text, old, new, label):
    assert text.count(old) == 1, (label, text.count(old))
    return text.replace(old, new)


# --- README ---------------------------------------------------------------------------
s = rw("README.md")
s = sub(s, "deine Zeiten lesen können — nur mit Token (Einstellungen → API)",
        "deine Zeiten lesen und eintragen können — nur mit Token (Einstellungen → API)", "feature")
s = sub(s, "über die Skripte, Taskplaner oder andere Programme deine Zeiten lesen können.",
        "über die Skripte, Taskplaner oder andere Programme deine Zeiten lesen und eintragen können.", "intro")
s = sub(s, "| `GET /v1/entries/{YYYY-MM-DD}` | ein Tag (404, wenn es keinen Eintrag gibt) |\n",
        "| `GET /v1/entries/{YYYY-MM-DD}` | ein Tag (404, wenn es keinen Eintrag gibt) |\n"
        "| `PUT /v1/entries/{YYYY-MM-DD}` | Tag **ersetzen**, Body `{\"slots\": [...]}`; Antwort mit `changed` (ein identischer Tag wird nicht neu geschrieben) und `warnings` (Wochenlimit, Pausenpflicht — blockieren nie) |\n"
        "| `DELETE /v1/entries/{YYYY-MM-DD}` | Tag löschen (404, wenn es keinen Eintrag gibt) |\n", "table")
s = sub(s, "\nUnter Windows PowerShell heißt der Aufruf `curl.exe`",
        '''
Einen Tag eintragen (ersetzt den ganzen Tag; `pause` in Minuten und `kategorie` sind optional):

~~~
curl -X PUT -H "Authorization: Bearer <Token>" -H "Content-Type: application/json" \\
     -d '{"slots": [{"start": "08:00", "end": "12:00", "pause": 0, "kategorie": "Projekt"}]}' \\
     http://127.0.0.1:17653/v1/entries/2026-10-07
~~~

Fehler: `400` kaputtes JSON oder falsche Form, `422` ungültiger Slot oder Datum (Jahr 2000–2100, höchstens 50 Slots, Zeiten genau `HH:MM`), `409` der Tag hat einen ungelösten Sync-Konflikt oder Urlaub (dann in der App lösen). Eine leere Slot-Liste speichert nichts — zum Löschen `DELETE` benutzen.

Unter Windows PowerShell heißt der Aufruf `curl.exe`''', "curl put")
wr("README.md", s)

# --- known-limitations -------------------------------------------------------------------------
k = rw("docs/known-limitations.md")
k = sub(k, "- **Gerätelokal.** `api_enabled` und `api_port` reisen nicht per Drive-Sync.\n",
        "- **Schreiben ist Last-Write-Wins.** `PUT`/`DELETE /v1/entries/{date}` schreiben wie der Tages-Dialog: "
        "ist der Tag in der App gleichzeitig geöffnet, gewinnt, wer zuletzt speichert. Es gibt kein Rückgängig; "
        "wer sichergehen will, liest den Tag vorher. Wochenlimit und Pausenpflicht kommen nur als Warnung.\n"
        "- **Gerätelokal.** `api_enabled` und `api_port` reisen nicht per Drive-Sync.\n", "kl")
wr("docs/known-limitations.md", k)

# --- src/CLAUDE.md ---------------------------------------------------------------------------------
c = rw("src/CLAUDE.md")
c = sub(c, "die Routen halten\n  keinen Lock und ändern nichts.",
        "die lesenden Routen\n  halten keinen Lock. `PUT`/`DELETE /v1/entries/{date}` prüfen, machen den Konfliktcheck\n"
        "  und speichern unter `ctx.data_lock` (der geteilte Store-`RLock`) und melden `ctx.on_change`\n"
        "  erst NACH dem Lock und nur bei einer Änderung (App: `_marshal_to_ui(_refresh)`); ein Fehler\n"
        "  in `on_change` macht aus einem gespeicherten Schreibzugriff keine 500.", "routes")
c = sub(c, "- `api_server.py` — HTTP-Server der lokalen API:",
        "- `api_entry_write.py` — Schreibpfad der lokalen API für Ist-Zeiten (#92), Tk-frei: nimmt\n"
        "  **Fremddaten** und bildet die Regeln nach, die die UI an ihren Eingängen durchsetzt und\n"
        "  `Storage` nicht kennt. `parse_day_body` (strenges JSON — kein `NaN`, keine doppelten\n"
        "  Schlüssel, `RecursionError` ist 400 —, genau `HH:MM`, nur die vier Felder, `validate_slots`),\n"
        "  `check_date_range` (2000–2100), `check_day_writable` (ungelöster Sync-Konflikt: `PUT` und\n"
        "  `DELETE`; Urlaubsminuten > 0: nur `PUT`, 0-Minuten-Tage bleiben frei) und `warnings_for`\n"
        "  (Wochenlimit/Pausenpflicht gegen den simulierten Stand nach dem Speichern, nie ein Fehler).\n"
        "  Hält keinen Lock; den nimmt der Aufrufer um Prüfen und Speichern gemeinsam.\n"
        "- `api_server.py` — HTTP-Server der lokalen API:", "entry write")
c = sub(c, "Schreibende Routen (spätere PRs) führen Prüfen →\nKonfliktcheck → Speichern unter demselben `data_lock` aus und rufen die UI nur über\n`App._marshal_to_ui`.",
        "Schreibende Routen führen Prüfen →\nKonfliktcheck → Speichern unter demselben `data_lock` aus und rufen die UI nur über\n`App._marshal_to_ui` (`ctx.on_change`, nach dem Lock). `App._quit_with_sync_push` stoppt die API\nVOR dem finalen Push, damit nach dem Snapshot keine Route mehr schreibt.", "threading")
wr("src/CLAUDE.md", c)

# --- Spec: Stack ---------------------------------------------------------------------------------------
p = "docs/superpowers/specs/2026-10-06-lokale-api-design.md"
sp = rw(p)
i, j = sp.index("4. Schreibende Ist-Zeit-Endpunkte"), sp.index("## Offene Punkte")
sp = sp[:i] + (
    "4. Schreibende Ist-Zeit-Endpunkte (`PUT`/`DELETE /v1/entries/{date}`) samt den Regeln aus\n"
    "   „Regeln, die die API nachbilden muss“.\n"
    "5. Auswertungen (Summen, Wochenlimit, Pausenpflicht, Kategorien, Feiertage), dann\n"
    "   Reservierungen und Urlaub — Zuschnitt und offene Fragen in Issue #239.\n\n") + sp[j:]
wr(p, sp)
print("Doku angepasst")
```

- [ ] **Step 2: Gesamtprüfung**

Run:
```bash
python3 -m pytest -q
ruff check .
V=/tmp/claude-1000/-home-sven-projects-Zeiterfassung/560a12d5-c553-4c73-8987-d78214ab3424/scratchpad/covenv
$V/bin/python -m pytest tests/test_api_entry_write.py tests/test_api_routes.py tests/test_api_auth.py \
  --cov=src.api_entry_write --cov=src.api_routes --cov=src.api_auth --cov-branch \
  --cov-report=term-missing -q -p no:cacheprovider
rm -f .coverage
python3 -m pytest tests/test_readme_version.py tests/test_claude_md_claims.py -q
```
Expected: alle Tests grün, `ruff` sauber; `api_entry_write` ≥ 95 % (jede fehlende Zeile prüfen: ein echtes Verhalten bekommt einen Test, ein unerreichbarer Zweig bleibt offen und kommt ins Ledger), `api_routes` und `api_auth` bleiben ≥ 95 %. Ein `pyright`-Lauf ist lokal nicht installiert; wenn `npx` verfügbar ist: `npx pyright@1.1.411 src/api_entry_write.py src/api_routes.py src/api_auth.py`.

- [ ] **Step 3: Commit**

```bash
git add README.md docs/known-limitations.md src/CLAUDE.md docs/superpowers/specs/2026-10-06-lokale-api-design.md
git commit -m "$(cat <<'EOF'
docs(api): schreibende Ist-Zeit-Endpunkte dokumentiert (#92)

README: PUT/DELETE mit curl-Beispiel und Fehlercodes; known-limitations:
Last-Write-Wins und kein Rückgängig; src/CLAUDE.md: api_entry_write und der
Schreibpfad unter data_lock; Spec-Stack: Auswertungen, Reservierungen und
Urlaub über #239.

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>
EOF
)"
```

- [ ] **Step 4: PR vorbereiten (nicht ohne Freigabe pushen)**

PR 4 gegen `feat/api-settings-tab`, Titel `feat(api): Schreibende Ist-Zeit-Endpunkte der lokalen API (#92)`, Beschreibung mit `Refs #92`, Verweis auf #233 (erledigt: exakter Methodenvergleich, `shutdown` vor `push_on_quit`, Tab-Text) und #239 (Folgearbeit). Kein `release:*`-Label. Danach in den Stack hängen: `echo '{"pull_requests":[<PR4>]}' | gh api -X POST repos/Xveyn/Zeiterfassung/stacks/236/add --input -`. Ein Schreibzugriff-Pre-Release vor dem Release ist Teil des Gesamt-Pre-Release-Punkts in #233. Push und PR erst nach Rückfrage.

---

## Self-Review

**Spec-Abdeckung:** `PUT`/`DELETE /v1/entries/{date}` (Spec „Endpunkte"): Task 3. Regeln der UI nachbilden — Urlaubssperre (`minutes > 0`), Sync-Konflikt-Sperre, Validierung über `validate_slots`, nicht blockierende Warnungen, Statuscodes 400/409/422: Task 2 und 3. Threading unter dem geteilten `data_lock`, UI nur über `_marshal_to_ui`: Task 3 und 4. #233: exakter Methodenvergleich (Task 1), `shutdown` vor `push_on_quit` (Task 4), Tab-Text (Task 4). **Bewusst nicht in PR 4:** Reservierungen und Urlaub (Issue #239), Auswertungen, Bulk-Schreiben, `If-Match`, Sync-Push nach jedem Schreiben.

**Platzhalter:** keine.

**Typkonsistenz:** `WriteError(status, code, message)` und seine Attribute (Task 2) werden in `handle` über `exc.status/.code/.message` konsumiert (Task 3). `parse_day_body`, `check_date_range`, `check_day_writable(…, for_save=…)`, `warnings_for` (Task 2) sind in Task 3 mit denselben Namen und Argumenten aufgerufen. `ApiContext`-Felder `data_lock`, `conflicts_store`, `vacation_store`, `on_change` (Task 3) entsprechen den Keywords im AST-Test und in `ui.py` (Task 4).
