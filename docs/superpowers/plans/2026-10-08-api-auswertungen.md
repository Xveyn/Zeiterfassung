# Lokale API, PR 5: Auswertungen Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Die lokale API liefert Auswertungen, rein lesend: Summen je Woche und Monat in ganzen Minuten (mit Tagen, Kategorien, Wochenlimit, Pausenwarnungen und dem Urlaub dieses Geräts), die konfigurierten Kategorien und die Feiertage des eingestellten Bundeslands.

**Architecture:** Ein neues Tk-freies Modul `api_summary` mit reinen Funktionen über einen `Storage.get_all()`-Snapshot (Pfad-Parser, `summarize`, `category_names`, `holidays_for`); in `api_routes` vier dünne `GET`-Handler, die Snapshot und Urlaubs-Snapshot (`vacation_store.day_minutes()`) holen und an das Modul reichen. Kein Lock, keine neuen Felder im `ApiContext`, keine Änderung an `ui.py`: der `vacation_store` ist seit PR 4 im Kontext.

**Tech Stack:** Python 3.12, stdlib, vorhandene Module (`weekly_limit`, `pause_requirement`, `vacations.cap_by_worktime`, `holidays_de`, `time_utils`). Keine neue Abhängigkeit.

**Spec:** `docs/superpowers/specs/2026-10-06-lokale-api-design.md` („Endpunkte“, Stack-Punkt 5). Zuschnitt und offene Fragen: Issue #239 (PR 5 = Auswertungen; Reservierungen und Urlaub folgen als PR 6/7). Die Antwortformen legt Task 4 in der Spec fest.

**Branching:** Stack. Der Branch `feat/api-analytics` ist aus `feat/api-write-entries` (PR #240) abgezweigt und liegt schon an. PR 5 zielt auf `feat/api-write-entries` und wird danach mit `POST /repos/Xveyn/Zeiterfassung/stacks/236/add` an den Stack gehängt. PR-Text enthält `Refs #92`, **kein** `Closes`.

## Entscheidungen (mit dem Nutzer abgestimmt)

- **Endpunkte** (alle `GET`, Scope `local`): `/v1/summary/week/{YYYY-Www}`, `/v1/summary/month/{YYYY-MM}`, `/v1/categories`, `/v1/holidays/{YYYY}`.
- **Urlaub kommt lesend mit rein:** `vacation_minutes` (über `cap_by_worktime` um die erfasste Ist-Zeit desselben Tages gekappt, wie Mail, PDF und Webhook) und `payable_minutes` („Zu vergüten gesamt“). Sonst weicht die API-Summe vom Bericht desselben Zeitraums ab. Urlaub ist gerätelokal; das steht in der Doku.
- **`workweek_only` wird ignoriert** (Anzeigeeinstellung), **kein Stundenlohn und keine Geldbeträge**, **kein** Kategorie-Filter (`?categories=`).
- **Ohne gesetztes Bundesland** liefert `/v1/holidays/{YYYY}` eine leere Liste mit `"state": ""`.
- **Jahre 2000–2100** wie beim Schreiben (sonst 422); ungültige Pfadform ist 400; unbekannte Query-Parameter sind 400.

## Rulings aus der Planung (der Nutzer sieht sie hier zuerst)

- Das Wochenlimit steht als `weeks[]` (eine Zeile je ISO-Woche, die der Zeitraum berührt) statt als einzelnes `weekly_limit`-Feld: ein Monat berührt vier bis sechs Wochen, und das Limit gilt je Woche. Die Woche zählt als Ganzes (auch Tage außerhalb des Monats), wie `check_week_limit`. Ist das Limit aus oder liegt die Woche außerhalb seines Zeitraums, ist `limit_minutes` `null` und `exceeded` `false`.
- `by_category` ist nach Minuten absteigend sortiert, bei Gleichstand nach Name, die leere Kategorie (`""`) zuletzt. Das spiegelt den Bericht (dort „(ohne Kategorie)“ am Ende); die Übersetzung des Namens bleibt beim Client.
- Die Pfad-Parser akzeptieren Jahre 1–9998 (darüber liefe Sonntag = Montag + 6 aus dem Datumsbereich); die Route lehnt außerhalb 2000–2100 mit 422 ab. `0000-01` und `9999-01` sind damit 400, `1999-12` und `2101-01` 422. Das ist nur für absurde Werte sichtbar.
- Gespeicherte Slots sind Fremddaten: ein Slot mit ungewöhnlichem Inhalt (`pause: null`, fehlende Zeiten) zählt 0 Minuten und wird mit `WARNING` geloggt, ein Tag, dessen Pausenprüfung scheitert, fehlt in `pause_warnings` (geloggt mit `exception`). Eine lesende Route wird nie zur 500.

## Global Constraints

- Tk-frei, stdlib-only, vollständig annotiert; `src/api_summary.py` kommt in `ANNOTATED_MODULES` (`tests/test_type_annotations.py`) und ist `pyright 1.1.411`-sauber.
- **Summen NUR über Minuten:** jeder angezeigte Wert ist die Summe ganzer Slot-Minuten (`hours_to_minutes(calculate_hours(…))` je Slot), nie Dezimalstunden. Urlaub und Wochensumme verwenden dieselbe Auflösung.
- Lesende Routen halten **keinen** `data_lock` und rufen nie `ctx.on_change`; sie ändern nichts.
- Strikte Pfade: ASCII-Ziffern (`[0-9]`, nicht `\d`), `W` groß, zwei Stellen; `fromisocalendar` entscheidet über Woche 53.
- Jeder `except Exception`/`BaseException` loggt, meldet oder begründet im Handler (`tests/test_catch_all_handlers.py`); `ruff check .` sauber.
- Der Zeitraum ist einschließlich beider Grenzen; Tombstones gibt es in `get_all()` nicht.

## Review Focus

Eingaben und Zustände, die die Spec nahelegt, aber keine Task allein erzwingt. Jede Zeile ist in der genannten Task gepinnt.

1. **Fremddaten-Slots** (`pause: null`, fehlende Felder, `slots` als String, Eintrag `null`): 0 Minuten bzw. übersprungen, geloggt, nie 500. Task 2.
2. **Wochen-Randfälle:** KW 53 (2026 hat sie, 2025 nicht), Woche über den Jahreswechsel (KW 1 2026 beginnt am 29.12.2025), Januar berührt fünf Wochen, die Wochensumme zählt Tage außerhalb des Monats mit. Task 1 und 2.
3. **Rundung:** 100 + 100 + 160 Minuten sind 6:00 h, nicht 6,01 h; das Limit gilt „über“ 20 h, nicht „ab“. Task 2.
4. **Pfadform:** Unicode-Ziffern, Leerzeichen, `2026-1`, `2026-W1`, `2026-w01`, `0000`, `9999`, Jahr 1999/2101: immer ein definiertes 400/422. Task 1 und 3.
5. **Urlaub:** Kappung am Tag mit Arbeitszeit (und sichtbar in `vacation_capped_days`), 0-Minuten-Tage (Samstag im Urlaub) kappen nie, Urlaub außerhalb des Zeitraums zählt nicht, kaputte Werte werden ignoriert. Task 2.
6. **Unbekanntes oder fehlendes Bundesland:** leere Feiertage, kein Fehler. Task 1.

---

### Task 1: Pfad-Parser, Kategorien und Feiertage

**Files:**
- Create: `src/api_summary.py`
- Create: `tests/test_api_summary.py`
- Modify: `tests/test_type_annotations.py` (Whitelist)

**Interfaces:**
- Consumes: `src.holidays_de.get_holidays(state_code: str, year: int) -> dict[date, str]`; `SettingsLike` aus `src.settings`.
- Produces: `parse_month(raw) -> tuple[date, date] | None`, `parse_week(raw) -> tuple[date, date] | None`, `parse_year(raw) -> int | None`, `category_names(settings) -> list[str]`, `holidays_for(settings, year) -> dict[str, Any]`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_api_summary.py`:

```python
# tests/test_api_summary.py
import datetime

import pytest

from src.api_summary import category_names, holidays_for, parse_month, parse_week, parse_year

D = datetime.date


# --- Pfad-Parser ------------------------------------------------------------------

def test_parse_month_gives_first_and_last_day():
    assert parse_month("2026-02") == (D(2026, 2, 1), D(2026, 2, 28))
    assert parse_month("2024-02") == (D(2024, 2, 1), D(2024, 2, 29))
    assert parse_month("2026-12") == (D(2026, 12, 1), D(2026, 12, 31))


@pytest.mark.parametrize("raw", [
    "2026-13", "2026-00", "2026-1", "26-01", "2026-01-01", " 2026-01", "2026-01 ",
    "٢٠٢٦-٠١", "0000-01", "9999-01", "", "2026/01",
])
def test_parse_month_rejects_bad_input(raw):
    assert parse_month(raw) is None


def test_parse_week_gives_monday_and_sunday():
    assert parse_week("2026-W01") == (D(2025, 12, 29), D(2026, 1, 4))
    assert parse_week("2026-W53") == (D(2026, 12, 28), D(2027, 1, 3))   # 2026 hat 53 Wochen


@pytest.mark.parametrize("raw", [
    "2025-W53", "2026-W00", "2026-W54", "2026-w01", "2026-W1", "2026W01",
    "2026-W01-1", "٢٠٢٦-W01", "0000-W01", "9999-W01", "",
])
def test_parse_week_rejects_bad_input(raw):
    assert parse_week(raw) is None


def test_parse_year():
    assert parse_year("2026") == 2026
    for raw in ("26", "20260", "٢٠٢٦", " 2026", "2026 ", ""):
        assert parse_year(raw) is None


# --- Kategorien und Feiertage ---------------------------------------------------------

def test_category_names_keeps_order_and_drops_junk():
    settings = {"categories": ["Projekt", "", "  ", "Büro", "Projekt", 5, None]}
    assert category_names(settings) == ["Projekt", "Büro"]


@pytest.mark.parametrize("value", [None, "Projekt", 5, {"a": 1}])
def test_category_names_tolerates_a_non_list(value):
    assert category_names({"categories": value}) == []
    assert category_names({}) == []


def test_holidays_for_a_state_are_sorted_with_german_names():
    result = holidays_for({"state": "BY"}, 2026)
    dates = [h["date"] for h in result["holidays"]]
    assert result["year"] == 2026 and result["state"] == "BY"
    assert dates == sorted(dates)
    assert {"date": "2026-01-01", "name": "Neujahr"} in result["holidays"]
    assert "2026-01-06" in dates                       # Heilige Drei Könige gilt in Bayern
    assert "2026-11-01" in dates                       # Allerheiligen


def test_holidays_differ_by_state():
    bayern = {h["date"] for h in holidays_for({"state": "BY"}, 2026)["holidays"]}
    berlin = {h["date"] for h in holidays_for({"state": "BE"}, 2026)["holidays"]}
    assert "2026-01-06" in bayern and "2026-01-06" not in berlin


@pytest.mark.parametrize("settings", [{}, {"state": ""}, {"state": None}, {"state": 5},
                                      {"state": "XX"}])
def test_holidays_without_a_valid_state_are_empty(settings):
    result = holidays_for(settings, 2026)
    assert result["holidays"] == []
    assert result["state"] in ("", "XX")
```

- [ ] **Step 2: Run to verify it fails**

Run: `python3 -m pytest tests/test_api_summary.py -q -p no:cacheprovider`
Expected: FAIL / ERROR at collection with `ModuleNotFoundError: No module named 'src.api_summary'`.

- [ ] **Step 3: Write the module (Teil 1)**

Create `src/api_summary.py`:

```python
# src/api_summary.py
"""Auswertungen der lokalen HTTP-API (#92), Tk-frei, rein und ohne Socket.

Summen, Kategorien, Wochenlimit, Pausenpflicht und Urlaub für einen Zeitraum
sowie Kategorienliste und Feiertage. Alles läuft über einen `get_all()`-Snapshot,
den der Aufrufer reicht; gerechnet wird in ganzen MINUTEN je Slot (Regel
„Summen NUR über Minuten“ in der Wurzel-`CLAUDE.md`), Dezimalstunden kommen
nirgends vor.

Gespeicherte Slots sind Fremddaten (der Sync validiert ihren Inhalt nicht): ein
Slot mit ungewöhnlichem Inhalt zählt 0 Minuten und wird geloggt, er macht aus
einer lesenden Route keine 500.
"""
from __future__ import annotations

import calendar
import datetime
import re
from typing import TYPE_CHECKING, Any

from src.holidays_de import get_holidays

if TYPE_CHECKING:  # nur für die Signaturen
    from src.settings import SettingsLike

_MONTH_RE = re.compile(r"([0-9]{4})-([0-9]{2})")
_WEEK_RE = re.compile(r"([0-9]{4})-W([0-9]{2})")
_YEAR_RE = re.compile(r"[0-9]{4}")

# Darüber liefe `Sonntag = Montag + 6` aus dem darstellbaren Datumsbereich; die
# Routen lehnen ohnehin alles außerhalb 2000–2100 ab.
_MAX_PARSE_YEAR = 9998


def parse_month(raw: str) -> tuple[datetime.date, datetime.date] | None:
    """`YYYY-MM` → (erster, letzter Tag), sonst None. Nur ASCII-Ziffern."""
    match = _MONTH_RE.fullmatch(raw)
    if match is None:
        return None
    year, month = int(match[1]), int(match[2])
    if not 1 <= year <= _MAX_PARSE_YEAR or not 1 <= month <= 12:
        return None
    last_day = calendar.monthrange(year, month)[1]
    return datetime.date(year, month, 1), datetime.date(year, month, last_day)


def parse_week(raw: str) -> tuple[datetime.date, datetime.date] | None:
    """`YYYY-Www` (ISO-Woche) → (Montag, Sonntag), sonst None. Woche 53 gibt es
    nur in manchen Jahren; `fromisocalendar` lehnt die anderen ab."""
    match = _WEEK_RE.fullmatch(raw)
    if match is None:
        return None
    year, week = int(match[1]), int(match[2])
    if not 1 <= year <= _MAX_PARSE_YEAR:
        return None
    try:
        monday = datetime.date.fromisocalendar(year, week, 1)
    except ValueError:
        return None
    return monday, monday + datetime.timedelta(days=6)


def parse_year(raw: str) -> int | None:
    """`YYYY` (vier ASCII-Ziffern) → Jahr, sonst None."""
    return int(raw) if _YEAR_RE.fullmatch(raw) else None


def category_names(settings: SettingsLike) -> list[str]:
    """Die in den Einstellungen konfigurierten Kategorien, in ihrer Reihenfolge,
    ohne Leere und Doppelte. Kategorien, die nur in Ist-Zeiten vorkommen, stehen
    in der Summary unter `by_category`."""
    raw = settings.get("categories")
    if not isinstance(raw, list):
        return []
    names: list[str] = []
    for item in raw:
        if isinstance(item, str) and item.strip() and item not in names:
            names.append(item)
    return names


def holidays_for(settings: SettingsLike, year: int) -> dict[str, Any]:
    """Feiertage des eingestellten Bundeslands. Ohne gesetztes Bundesland ist die
    Liste leer und `state` ist `""` — so unterscheidet der Client „keine
    Feiertage“ von „Bundesland fehlt“ (dieselbe Lücke wie beim Urlaub)."""
    state = settings.get("state")
    if not isinstance(state, str):
        state = ""
    found = get_holidays(state, year)
    return {
        "year": year,
        "state": state,
        "holidays": [{"date": day.isoformat(), "name": name}
                     for day, name in sorted(found.items())],
    }
```

- [ ] **Step 4: Whitelist the module**

In `tests/test_type_annotations.py` ergänze in `ANNOTATED_MODULES` hinter `"src/api_entry_write.py",`:

```python
    "src/api_summary.py",
```

- [ ] **Step 5: Run to verify it passes**

Run: `python3 -m pytest tests/test_api_summary.py tests/test_type_annotations.py -q -p no:cacheprovider && ruff check src tests`
Expected: PASS (38 Tests in `test_api_summary.py`, dazu die Whitelist-Läufe), `All checks passed!`.

- [ ] **Step 6: Commit**

~~~bash
git add src/api_summary.py tests/test_api_summary.py tests/test_type_annotations.py
git commit -m "feat(api): Pfad-Parser, Kategorien und Feiertage für die Auswertungen (#92)

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
~~~

---

### Task 2: `summarize` — Summen, Kategorien, Wochenlimit, Pausenpflicht, Urlaub

**Files:**
- Modify: `src/api_summary.py`
- Modify: `tests/test_api_summary.py`

**Interfaces:**
- Consumes: Task 1 (Modul, Parser); `src.time_utils.calculate_hours/get_week_dates/hours_to_minutes`, `src.weekly_limit.is_limit_active`, `src.pause_requirement.check_day_pause`, `src.vacations.cap_by_worktime`.
- Produces: `summarize(date_from: date, date_to: date, entries: Mapping[str, Any], settings: SettingsLike, vacation_days: Mapping[str, int]) -> dict[str, Any]` mit den Schlüsseln `from`, `to`, `total_minutes`, `vacation_minutes`, `payable_minutes`, `vacation_capped_days`, `days`, `by_category`, `weeks`, `pause_warnings`.

- [ ] **Step 1: Write the failing tests**

In `tests/test_api_summary.py` ersetze den Kopf (Importblock bis `D = datetime.date`) durch:

```python
import datetime
import logging

import pytest

from src.api_summary import (
    category_names, holidays_for, parse_month, parse_week, parse_year, summarize,
)
from src.weekly_limit import week_ist_minutes
from tests.conftest import ist_slot

D = datetime.date
JAN = (D(2026, 1, 1), D(2026, 1, 31))
```

Hänge danach, hinter den Feiertags-Tests (Dateiende), die Helfer und die Tests an:

```python
def day(*slots):
    return {"slots": list(slots)}


def run(entries, settings=None, vacation=None, span=JAN):
    return summarize(span[0], span[1], entries, {} if settings is None else settings,
                     {} if vacation is None else vacation)
```

```python
# --- Summen -------------------------------------------------------------------------------

def test_totals_days_and_range_are_in_whole_minutes():
    entries = {
        "2026-01-05": day(ist_slot("08:00", "12:00", 0, "Projekt")),
        "2026-01-20": day(ist_slot("09:00", "17:00", 30, "Büro")),
        "2026-02-03": day(ist_slot("10:00", "11:00")),                 # außerhalb
    }

    result = run(entries)

    assert (result["from"], result["to"]) == ("2026-01-01", "2026-01-31")
    assert result["total_minutes"] == 240 + 450
    assert result["days"] == [
        {"date": "2026-01-05", "minutes": 240, "slots": 1},
        {"date": "2026-01-20", "minutes": 450, "slots": 1},
    ]


def test_range_bounds_are_inclusive():
    entries = {"2026-01-01": day(ist_slot("08:00", "09:00")),
               "2026-01-31": day(ist_slot("08:00", "09:00")),
               "2025-12-31": day(ist_slot("08:00", "09:00")),
               "2026-02-01": day(ist_slot("08:00", "09:00"))}
    assert [d["date"] for d in run(entries)["days"]] == ["2026-01-01", "2026-01-31"]


def test_sum_is_over_minutes_not_rounded_decimal_hours():
    # 100 + 100 + 160 Minuten: als Dezimalstunden je Slot gerundet ergäbe das 6,01 h
    entries = {"2026-01-05": day(ist_slot("08:00", "09:40"), ist_slot("10:00", "11:40"),
                                 ist_slot("12:00", "14:40"))}
    result = run(entries)
    assert result["total_minutes"] == 360
    assert result["days"][0] == {"date": "2026-01-05", "minutes": 360, "slots": 3}


def test_a_day_without_slots_is_left_out():
    result = run({"2026-01-05": {"slots": []}, "2026-01-06": day(ist_slot("08:00", "09:00"))})
    assert [d["date"] for d in result["days"]] == ["2026-01-06"]


def test_empty_store_gives_zeroes():
    result = run({})
    assert result["total_minutes"] == 0 and result["days"] == []
    assert result["by_category"] == [] and result["pause_warnings"] == []
    assert result["vacation_minutes"] == 0 and result["payable_minutes"] == 0


def test_keys_that_are_not_days_are_ignored():
    entries = {"kaputt": day(ist_slot("08:00", "09:00")),
               "20260105": day(ist_slot("08:00", "09:00")),
               "2026-01-05": day(ist_slot("08:00", "09:00"))}
    assert [d["date"] for d in run(entries)["days"]] == ["2026-01-05"]


def test_inputs_are_not_mutated():
    entries = {"2026-01-05": day(ist_slot("08:00", "12:00", 0, "A"))}
    vacation = {"2026-01-06": 480}
    before = (repr(entries), repr(vacation))
    run(entries, vacation=vacation)
    assert (repr(entries), repr(vacation)) == before


# --- Kategorien ---------------------------------------------------------------------------

def test_by_category_is_sorted_by_minutes_then_name_and_keeps_the_empty_one():
    entries = {"2026-01-05": day(
        ist_slot("08:00", "09:00", 0, "Büro"), ist_slot("09:00", "12:00", 0, "Projekt"),
        ist_slot("12:00", "13:00", 0, "Abwesend"), ist_slot("13:00", "14:00"))}
    assert run(entries)["by_category"] == [
        {"kategorie": "Projekt", "minutes": 180},
        {"kategorie": "Abwesend", "minutes": 60},
        {"kategorie": "Büro", "minutes": 60},
        {"kategorie": "", "minutes": 60},
    ]


def test_by_category_adds_up_across_days_and_equals_the_total():
    entries = {"2026-01-05": day(ist_slot("08:00", "10:00", 0, "A")),
               "2026-01-06": day(ist_slot("08:00", "09:30", 0, "A"), ist_slot("10:00", "11:00", 0, "B"))}
    result = run(entries)
    assert {c["kategorie"]: c["minutes"] for c in result["by_category"]} == {"A": 210, "B": 60}
    assert sum(c["minutes"] for c in result["by_category"]) == result["total_minutes"]


def test_a_non_string_category_counts_as_uncategorised():
    entries = {"2026-01-05": day({"start": "08:00", "end": "09:00", "pause": 0, "kategorie": 5})}
    assert run(entries)["by_category"] == [{"kategorie": "", "minutes": 60}]


# --- Wochen und Wochenlimit ------------------------------------------------------------------

def test_weeks_lists_every_iso_week_the_range_touches():
    weeks = run({})["weeks"]
    assert [(w["iso_year"], w["iso_week"]) for w in weeks] == [
        (2026, 1), (2026, 2), (2026, 3), (2026, 4), (2026, 5)]


def test_a_week_total_covers_the_whole_week_not_only_the_range():
    # 2025-12-30 liegt in KW 1 (29.12.–04.01.), aber nicht im Januar
    entries = {"2025-12-30": day(ist_slot("08:00", "10:00")),
               "2026-01-05": day(ist_slot("08:00", "09:00"))}

    result = run(entries)

    assert result["total_minutes"] == 60
    assert result["weeks"][0]["total_minutes"] == 120
    assert result["weeks"][1]["total_minutes"] == 60


def test_week_total_equals_the_weekly_limit_module():
    entries = {"2026-01-05": day(ist_slot("08:00", "09:40"), ist_slot("10:00", "11:40")),
               "2026-01-07": day(ist_slot("12:00", "14:40")),
               "2026-01-09": day(ist_slot("08:00", "13:00", 30))}
    result = run(entries)
    assert result["weeks"][1]["total_minutes"] == week_ist_minutes(entries, 2026, 2)


LIMIT = {"werkstudent_limit_enabled": True, "werkstudent_limit_start": "2026-01-01",
         "werkstudent_limit_end": "2026-12-31", "werkstudent_limit_max_hours": 20.0}


def test_limit_is_off_by_default():
    for week in run({"2026-01-05": day(ist_slot("08:00", "20:00"))})["weeks"]:
        assert week["limit_minutes"] is None and week["exceeded"] is False


def test_exceeding_the_limit_is_flagged_exactly_above_it():
    exactly = {"2026-01-05": day(ist_slot("08:00", "20:00")),                     # 12 h
               "2026-01-06": day(ist_slot("08:00", "16:00"))}                     # + 8 h = 20 h
    over = dict(exactly, **{"2026-01-07": day(ist_slot("08:00", "08:01"))})

    week = run(exactly, LIMIT)["weeks"][1]
    assert (week["limit_minutes"], week["total_minutes"], week["exceeded"]) == (1200, 1200, False)

    week = run(over, LIMIT)["weeks"][1]
    assert (week["total_minutes"], week["exceeded"]) == (1201, True)


def test_the_limit_applies_only_to_weeks_inside_its_period():
    settings = dict(LIMIT, werkstudent_limit_start="2026-01-12", werkstudent_limit_end="2026-01-18")
    limits = [w["limit_minutes"] for w in run({}, settings)["weeks"]]
    assert limits == [None, None, 1200, None, None]


def test_an_unreadable_limit_drops_the_limit_and_logs(caplog):
    with caplog.at_level(logging.WARNING, logger="src.api_summary"):
        result = run({"2026-01-05": day(ist_slot("08:00", "20:00"))},
                     dict(LIMIT, werkstudent_limit_max_hours=None))
    assert all(w["limit_minutes"] is None and not w["exceeded"] for w in result["weeks"])
    assert "werkstudent_limit_max_hours" in caplog.text


# --- Pausenpflicht -------------------------------------------------------------------------------

def test_pause_warning_names_the_day_and_the_numbers():
    entries = {"2026-01-06": day(ist_slot("08:00", "15:00", 0)),                    # 7 h ohne Pause
               "2026-01-05": day(ist_slot("08:00", "16:00", 30)),                   # 7,5 h, 30 Min: ok
               "2026-01-07": day(ist_slot("08:00", "19:00", 30))}                   # 10,5 h, 30 < 45
    result = run(entries, {"pause_warning_enabled": True})
    assert result["pause_warnings"] == [
        {"date": "2026-01-06", "worked_minutes": 420, "actual_pause_minutes": 0,
         "required_pause_minutes": 30},
        {"date": "2026-01-07", "worked_minutes": 630, "actual_pause_minutes": 30,
         "required_pause_minutes": 45},
    ]


def test_exactly_six_hours_needs_no_pause():
    entries = {"2026-01-06": day(ist_slot("08:00", "14:00", 0))}
    assert run(entries, {"pause_warning_enabled": True})["pause_warnings"] == []


def test_pause_warnings_follow_the_setting():
    entries = {"2026-01-06": day(ist_slot("08:00", "15:00", 0))}
    assert run(entries, {"pause_warning_enabled": False})["pause_warnings"] == []
    assert run(entries, {})["pause_warnings"] == []


# --- Urlaub ----------------------------------------------------------------------------------------

def test_without_vacation_payable_equals_total():
    result = run({"2026-01-05": day(ist_slot("08:00", "12:00"))})
    assert (result["vacation_minutes"], result["payable_minutes"]) == (0, 240)
    assert result["vacation_capped_days"] == []


def test_vacation_in_range_is_added_to_payable_but_not_to_total():
    entries = {"2026-01-05": day(ist_slot("08:00", "12:00"))}
    vacation = {"2026-01-12": 480, "2026-01-13": 480, "2026-01-17": 0,
                "2025-12-31": 480, "2026-02-02": 480}                        # die letzten zwei außerhalb

    result = run(entries, vacation=vacation)

    assert result["total_minutes"] == 240
    assert result["vacation_minutes"] == 960
    assert result["payable_minutes"] == 1200


def test_vacation_is_capped_by_the_work_on_the_same_day_and_says_so():
    entries = {"2026-01-12": day(ist_slot("08:00", "12:00"))}                 # 240 Min Arbeit
    result = run(entries, vacation={"2026-01-12": 480, "2026-01-13": 480})

    assert result["vacation_minutes"] == 240 + 480
    assert result["payable_minutes"] == 240 + 240 + 480
    assert result["vacation_capped_days"] == [
        {"date": "2026-01-12", "vacation_minutes": 480, "work_minutes": 240,
         "counted_minutes": 240}]


def test_zero_minute_vacation_days_do_not_cap_work():
    entries = {"2026-01-17": day(ist_slot("08:00", "12:00"))}                 # Samstag im Urlaub
    result = run(entries, vacation={"2026-01-17": 0})
    assert result["vacation_minutes"] == 0 and result["vacation_capped_days"] == []


def test_junk_vacation_values_are_ignored():
    vacation = {"2026-01-12": True, "2026-01-13": "480", "2026-01-14": 1.5, "kaputt": 480,
                "2026-01-15": 60}
    assert run({}, vacation=vacation)["vacation_minutes"] == 60


# --- Fremddaten ----------------------------------------------------------------------------------------

def test_an_odd_stored_slot_counts_zero_and_never_raises(caplog):
    entries = {"2026-01-05": day(ist_slot("08:00", "09:00"),
                                 {"start": "09:00", "end": "10:00", "pause": None},
                                 {"start": None, "end": None}, "kein-slot"),
               "2026-01-06": {"slots": "kaputt"}, "2026-01-07": "kaputt", "2026-01-08": None}

    with caplog.at_level(logging.WARNING, logger="src.api_summary"):
        result = run(entries, {"pause_warning_enabled": True})

    assert result["total_minutes"] == 60
    assert [d["date"] for d in result["days"]] == ["2026-01-05"]
    assert "Slot nicht berechenbar" in caplog.text


def test_odd_data_on_one_day_does_not_hide_the_pause_warning_of_another(caplog):
    entries = {"2026-01-05": day({"start": "08:00", "end": "17:00"}, {"end": "18:00"}),
               "2026-01-06": day(ist_slot("08:00", "15:00", 0))}
    with caplog.at_level(logging.ERROR, logger="src.api_summary"):
        result = run(entries, {"pause_warning_enabled": True})
    assert [w["date"] for w in result["pause_warnings"]] == ["2026-01-06"]
    assert result["total_minutes"] == 540 + 420
    assert "Pausenpflicht für 2026-01-05" in caplog.text
```

- [ ] **Step 2: Run to verify they fail**

Run: `python3 -m pytest tests/test_api_summary.py -q -p no:cacheprovider`
Expected: FAIL / ERROR at collection with `ImportError: cannot import name 'summarize' from 'src.api_summary'`.

- [ ] **Step 3: Implement `summarize`**

In `src/api_summary.py`: (a) ersetze den Importblock

```python
from __future__ import annotations

import calendar
import datetime
import re
from typing import TYPE_CHECKING, Any

from src.holidays_de import get_holidays
```

durch

```python
from __future__ import annotations

import calendar
import datetime
import logging
import re
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from src.holidays_de import get_holidays
from src.pause_requirement import check_day_pause
from src.time_utils import calculate_hours, get_week_dates, hours_to_minutes
from src.vacations import cap_by_worktime
from src.weekly_limit import is_limit_active
```

(b) füge direkt vor `_MONTH_RE = re.compile(…)` ein:

```python
_log = logging.getLogger(__name__)

_DAY_KEY_RE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
```

(c) hänge ans Dateiende an (zwei Leerzeilen Abstand):

```python
def _slots_of(entry: Any) -> list[dict[str, Any]]:
    slots = entry.get("slots") if isinstance(entry, dict) else None
    if not isinstance(slots, list):
        return []
    return [slot for slot in slots if isinstance(slot, dict)]


def _slot_minutes(slot: Mapping[str, Any]) -> int:
    try:
        return hours_to_minutes(calculate_hours(
            slot.get("start"), slot.get("end"), slot.get("pause", 0)))
    except (TypeError, ValueError, AttributeError):
        _log.warning("Lokale API: Slot nicht berechenbar, zählt 0 Minuten: %r",
                     slot, exc_info=True)
        return 0


def _day_minutes(entry: Any) -> int:
    return sum(_slot_minutes(slot) for slot in _slots_of(entry))


def _limit_minutes(settings: SettingsLike) -> int | None:
    try:
        return hours_to_minutes(settings.get("werkstudent_limit_max_hours"))
    except (TypeError, ValueError):
        _log.warning("Lokale API: werkstudent_limit_max_hours nicht lesbar, "
                     "Wochenlimit entfällt", exc_info=True)
        return None


def _week_row(iso_year: int, iso_week: int, entries: Mapping[str, Any],
              settings: SettingsLike) -> dict[str, Any]:
    dates = get_week_dates(iso_year, iso_week)
    total = sum(_day_minutes(entries.get(day.isoformat())) for day in dates)
    limit = None
    if any(is_limit_active(settings, day.isoformat()) for day in dates):
        limit = _limit_minutes(settings)
    return {
        "iso_year": iso_year, "iso_week": iso_week,
        "total_minutes": total, "limit_minutes": limit,
        "exceeded": limit is not None and total > limit,
    }


def _weeks_in(date_from: datetime.date, date_to: datetime.date) -> list[tuple[int, int]]:
    weeks: list[tuple[int, int]] = []
    day = date_from
    while day <= date_to:
        iso = day.isocalendar()
        if (iso.year, iso.week) not in weeks:
            weeks.append((iso.year, iso.week))
        day += datetime.timedelta(days=1)
    return weeks


def _pause_warnings(settings: SettingsLike,
                    in_range: Mapping[str, Any]) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    for day_key in sorted(in_range):
        try:
            violation = check_day_pause(settings, _slots_of(in_range[day_key]))
        except Exception:
            _log.exception("Lokale API: Pausenpflicht für %s nicht berechenbar", day_key)
            continue
        if violation is not None:
            found.append({"date": day_key, **violation})
    return found


def _vacation_part(vacation_days: Mapping[str, int], first: str, last: str,
                   in_range: dict[str, Any]) -> tuple[int, list[dict[str, Any]]]:
    """(Urlaubsminuten nach Kappung, gekappte Tage). Gekappt wird wie in Mail,
    PDF und Webhook gegen die erfasste Ist-Zeit desselben Ausschnitts, damit ein
    Kalendertag nie mehr Stunden hat, als er hat (`vacations.cap_by_worktime`)."""
    days = {key: minutes for key, minutes in vacation_days.items()
            if _DAY_KEY_RE.fullmatch(key) and first <= key <= last
            and isinstance(minutes, int) and not isinstance(minutes, bool)}
    try:
        capped, hits = cap_by_worktime(days, in_range)
    except Exception:
        _log.exception("Lokale API: Urlaubskappung nicht berechenbar, Urlaub ungekappt")
        capped, hits = dict(days), []
    return sum(capped.values()), [
        {"date": hit.date, "vacation_minutes": hit.vacation,
         "work_minutes": hit.work, "counted_minutes": hit.capped}
        for hit in hits]


def summarize(date_from: datetime.date, date_to: datetime.date,
              entries: Mapping[str, Any], settings: SettingsLike,
              vacation_days: Mapping[str, int]) -> dict[str, Any]:
    """Auswertung für [date_from, date_to] (beide einschließlich) über einen
    `Storage.get_all()`-Snapshot (ohne Tombstones) und den Urlaubs-Snapshot
    `{ISO: Minuten}`. `by_category` ist nach Minuten absteigend sortiert, bei
    Gleichstand nach Name, die leere Kategorie zuletzt (wie im Bericht). `weeks` führt jede ISO-Woche auf, die der Zeitraum
    berührt, mit der Summe der GANZEN Woche — das Wochenlimit gilt für die Woche,
    auch wenn der Monat sie nur teilweise enthält."""
    first, last = date_from.isoformat(), date_to.isoformat()
    in_range = {key: entry for key, entry in entries.items()
                if _DAY_KEY_RE.fullmatch(key) and first <= key <= last
                and _slots_of(entry)}
    days = []
    by_category: dict[str, int] = {}
    for key in sorted(in_range):
        slots = _slots_of(in_range[key])
        minutes = 0
        for slot in slots:
            slot_minutes = _slot_minutes(slot)
            minutes += slot_minutes
            name = slot.get("kategorie")
            name = name if isinstance(name, str) else ""
            by_category[name] = by_category.get(name, 0) + slot_minutes
        days.append({"date": key, "minutes": minutes, "slots": len(slots)})
    total = sum(day["minutes"] for day in days)
    vacation_minutes, capped_days = _vacation_part(vacation_days, first, last, in_range)
    return {
        "from": first,
        "to": last,
        "total_minutes": total,
        "vacation_minutes": vacation_minutes,
        "payable_minutes": total + vacation_minutes,
        "vacation_capped_days": capped_days,
        "days": days,
        "by_category": [{"kategorie": name, "minutes": minutes} for name, minutes
                        in sorted(by_category.items(),
                                  key=lambda kv: (-kv[1], kv[0] == "", kv[0]))],
        "weeks": [_week_row(year, week, entries, settings)
                  for year, week in _weeks_in(date_from, date_to)],
        "pause_warnings": _pause_warnings(settings, in_range),
    }
```

- [ ] **Step 4: Run to verify they pass**

Run: `python3 -m pytest tests/test_api_summary.py -q -p no:cacheprovider && ruff check src tests && npx --yes pyright@1.1.411 src/api_summary.py`
Expected: PASS (65 Tests), `All checks passed!`, `0 errors`.

- [ ] **Step 5: Commit**

~~~bash
git add src/api_summary.py tests/test_api_summary.py
git commit -m "feat(api): Summen, Wochenlimit, Pausenpflicht und Urlaub je Zeitraum (#92)

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
~~~

---

### Task 3: Die vier Routen

**Files:**
- Modify: `src/api_routes.py`
- Modify: `tests/test_api_routes.py`

**Interfaces:**
- Consumes: Task 1 und 2 (`parse_week`, `parse_month`, `parse_year`, `summarize`, `category_names`, `holidays_for`); `api_entry_write.MIN_YEAR/MAX_YEAR`; `ctx.vacation_store.day_minutes()`.
- Produces: `GET /v1/summary/week/{YYYY-Www}` (Antwort `{"week": raw, **summarize(...)}`), `GET /v1/summary/month/{YYYY-MM}` (`{"month": raw, ...}`), `GET /v1/categories` (`{"categories": [...]}`), `GET /v1/holidays/{YYYY}` (`holidays_for`). Fehler: `400 invalid_week|invalid_month|invalid_year|unknown_parameter`, `422 date_out_of_range`.

- [ ] **Step 1: Write the failing tests**

Hänge ans Ende von `tests/test_api_routes.py` an:

```python
# --- Auswertungen: /v1/summary, /v1/categories, /v1/holidays ---------------------------

def get(env, path, query=None, principal=LOCAL):
    return handle(ApiRequest("GET", path, query or {}), env.ctx, principal)


def seed_week(env):
    env.storage.save("2026-01-05", [ist_slot("08:00", "12:00", 0, "Projekt")])
    env.storage.save("2026-01-06", [ist_slot("09:00", "17:00", 30, "Büro")])


def test_week_summary_has_the_range_the_totals_and_the_label(env):
    seed_week(env)

    response = get(env, "/v1/summary/week/2026-W02")

    assert response.status == 200
    body = response.body
    assert body["week"] == "2026-W02"
    assert (body["from"], body["to"]) == ("2026-01-05", "2026-01-11")
    assert body["total_minutes"] == 240 + 450
    assert [d["date"] for d in body["days"]] == ["2026-01-05", "2026-01-06"]
    assert [(w["iso_year"], w["iso_week"]) for w in body["weeks"]] == [(2026, 2)]


def test_month_summary_covers_the_whole_month(env):
    seed_week(env)
    env.storage.save("2026-02-02", [ist_slot("08:00", "09:00")])

    response = get(env, "/v1/summary/month/2026-01")

    assert response.status == 200
    assert response.body["month"] == "2026-01"
    assert (response.body["from"], response.body["to"]) == ("2026-01-01", "2026-01-31")
    assert response.body["total_minutes"] == 690          # Februar zählt nicht
    assert len(response.body["weeks"]) == 5


def test_summary_total_matches_the_entries_route(env):
    seed_week(env)
    entries = get(env, "/v1/entries", {"from": ["2026-01-01"], "to": ["2026-01-31"]}).body["entries"]
    by_hand = sum(
        (int(s["end"][:2]) * 60 + int(s["end"][3:])) - (int(s["start"][:2]) * 60 + int(s["start"][3:])) - s["pause"]
        for e in entries.values() for s in e["slots"])
    assert get(env, "/v1/summary/month/2026-01").body["total_minutes"] == by_hand


def test_summary_includes_the_vacation_of_the_store(env):
    env.vacations.save(None, "Sommer", "2026-01-12", "2026-01-13",
                       {"2026-01-12": 480, "2026-01-13": 480})
    env.storage.save("2026-01-12", [ist_slot("08:00", "10:00")])

    body = get(env, "/v1/summary/month/2026-01").body

    assert body["total_minutes"] == 120
    assert body["vacation_minutes"] == 480 - 120 + 480          # 12.01. um die Arbeitszeit gekappt
    assert body["payable_minutes"] == 120 + body["vacation_minutes"]
    assert [d["date"] for d in body["vacation_capped_days"]] == ["2026-01-12"]


def test_summary_without_a_vacation_store_has_no_vacation(tmp_path):
    ctx = make_ctx(Storage(str(tmp_path / "z.json"), device_id="d"))
    body = handle(ApiRequest("GET", "/v1/summary/month/2026-01", {}), ctx, LOCAL).body
    assert (body["vacation_minutes"], body["payable_minutes"]) == (0, 0)


def test_summary_reports_the_weekly_limit_and_pause_warnings(tmp_path):
    env = Env(tmp_path, {
        "werkstudent_limit_enabled": True, "werkstudent_limit_start": "2026-01-01",
        "werkstudent_limit_end": "2026-12-31", "werkstudent_limit_max_hours": 5.0,
        "pause_warning_enabled": True})
    env.storage.save("2026-01-05", [ist_slot("08:00", "15:00", 0)])

    body = get(env, "/v1/summary/week/2026-W02").body

    assert body["weeks"] == [{"iso_year": 2026, "iso_week": 2, "total_minutes": 420,
                              "limit_minutes": 300, "exceeded": True}]
    assert body["pause_warnings"] == [{"date": "2026-01-05", "worked_minutes": 420,
                                       "actual_pause_minutes": 0, "required_pause_minutes": 30}]


@pytest.mark.parametrize("path,error", [
    ("/v1/summary/week/2026-W1", "invalid_week"), ("/v1/summary/week/2025-W53", "invalid_week"),
    ("/v1/summary/week/2026-01", "invalid_week"), ("/v1/summary/week/abc", "invalid_week"),
    ("/v1/summary/month/2026-13", "invalid_month"), ("/v1/summary/month/2026-W02", "invalid_month"),
    ("/v1/summary/month/2026-1", "invalid_month"), ("/v1/summary/month/9999-01", "invalid_month"),
    ("/v1/holidays/26", "invalid_year"), ("/v1/holidays/2026-01", "invalid_year"),
    ("/v1/holidays/abcd", "invalid_year"),
])
def test_malformed_summary_paths_are_400(env, path, error):
    response = get(env, path)
    assert (response.status, code(response)) == (400, error)


@pytest.mark.parametrize("path", [
    "/v1/summary/month/1999-12", "/v1/summary/month/2101-01", "/v1/summary/week/1999-W52",
    "/v1/summary/week/2101-W01", "/v1/holidays/1999", "/v1/holidays/2101",
])
def test_years_outside_2000_to_2100_are_422(env, path):
    response = get(env, path)
    assert (response.status, code(response)) == (422, "date_out_of_range")


@pytest.mark.parametrize("path", [
    "/v1/summary/month/2000-01", "/v1/summary/month/2100-12", "/v1/summary/week/2000-W01",
    "/v1/summary/week/2100-W01", "/v1/holidays/2000", "/v1/holidays/2100",
])
def test_the_edges_of_the_year_range_are_accepted(env, path):
    assert get(env, path).status == 200


@pytest.mark.parametrize("path", [
    "/v1/summary/week/2026-W02", "/v1/summary/month/2026-01", "/v1/categories",
    "/v1/holidays/2026",
])
def test_summary_routes_take_no_query(env, path):
    response = get(env, path, {"x": ["1"]})
    assert (response.status, code(response)) == (400, "unknown_parameter")


@pytest.mark.parametrize("path", [
    "/v1/summary/week/2026-W02", "/v1/summary/month/2026-01", "/v1/categories",
    "/v1/holidays/2026",
])
def test_summary_routes_are_read_only(env, path):
    response = handle(ApiRequest("PUT", path, {}, b"{}"), env.ctx, LOCAL)
    assert response.status == 405 and response.headers["Allow"] == "GET"


@pytest.mark.parametrize("path", [
    "/v1/summary/week/2026-W02", "/v1/summary/month/2026-01", "/v1/categories",
    "/v1/holidays/2026",
])
def test_summary_routes_need_the_local_scope(env, path):
    nobody = Principal("x", frozenset())
    assert get(env, path, principal=nobody).status == 403


def test_reading_a_summary_takes_no_data_lock_and_changes_nothing(env):
    seed_week(env)
    before = env.storage.get_all()

    get(env, "/v1/summary/month/2026-01")
    get(env, "/v1/summary/week/2026-W02")

    assert (env.lock.enters, env.changes) == (0, 0)
    assert env.storage.get_all() == before


def test_categories_come_from_the_settings(tmp_path):
    env = Env(tmp_path, {"categories": ["Projekt", "", "Büro", "Projekt"]})
    assert get(env, "/v1/categories").body == {"categories": ["Projekt", "Büro"]}


def test_categories_default_to_an_empty_list(env):
    assert get(env, "/v1/categories").body == {"categories": []}


def test_holidays_use_the_state_of_the_settings(tmp_path):
    env = Env(tmp_path, {"state": "BY"})
    body = get(env, "/v1/holidays/2026").body
    assert (body["year"], body["state"]) == (2026, "BY")
    assert {"date": "2026-01-01", "name": "Neujahr"} in body["holidays"]


def test_holidays_without_a_state_are_empty_and_say_so(env):
    assert get(env, "/v1/holidays/2026").body == {"year": 2026, "state": "", "holidays": []}
```

- [ ] **Step 2: Run to verify they fail**

Run: `python3 -m pytest tests/test_api_routes.py -q -p no:cacheprovider -k "summary or categories or holidays or year_range or years_outside or edges_of_the_year or malformed_summary"`
Expected: FAIL — die Antworten sind `404 not_found` (Route fehlt), die 405-Tests liefern 404 statt 405.

- [ ] **Step 3: Implement the routes**

In `src/api_routes.py`: (a) ersetze den Import von `src.api_entry_write` durch

```python
from src.api_entry_write import (
    MAX_YEAR, MIN_YEAR, WriteError, check_date_range, check_day_writable, parse_day_body,
    warnings_for,
)
from src.api_summary import (
    category_names, holidays_for, parse_month, parse_week, parse_year, summarize,
)
```

(b) füge direkt vor `def _locked(ctx: ApiContext) -> Any:` ein:

```python
def _check_year(year: int) -> None:
    if not MIN_YEAR <= year <= MAX_YEAR:
        raise _ApiError(422, "date_out_of_range",
                        f"Nur die Jahre {MIN_YEAR} bis {MAX_YEAR} werden unterstützt.")


def _summary(ctx: ApiContext, span: tuple[datetime.date, datetime.date]) -> dict[str, Any]:
    vacation = ctx.vacation_store.day_minutes() if ctx.vacation_store is not None else {}
    return summarize(span[0], span[1], ctx.storage.get_all(), ctx.settings, vacation)


def _summary_week(request: ApiRequest, ctx: ApiContext, match: re.Match[str]) -> ApiResponse:
    _only_params(request.query, frozenset())
    raw = match.group(1)
    span = parse_week(raw)
    if span is None:
        raise _ApiError(400, "invalid_week", "Erwartet YYYY-Www, zum Beispiel 2026-W01.")
    _check_year(int(raw[:4]))
    return ApiResponse(200, {"week": raw, **_summary(ctx, span)})


def _summary_month(request: ApiRequest, ctx: ApiContext, match: re.Match[str]) -> ApiResponse:
    _only_params(request.query, frozenset())
    raw = match.group(1)
    span = parse_month(raw)
    if span is None:
        raise _ApiError(400, "invalid_month", "Erwartet YYYY-MM, zum Beispiel 2026-01.")
    _check_year(span[0].year)
    return ApiResponse(200, {"month": raw, **_summary(ctx, span)})


def _categories(request: ApiRequest, ctx: ApiContext, _match: re.Match[str]) -> ApiResponse:
    _only_params(request.query, frozenset())
    return ApiResponse(200, {"categories": category_names(ctx.settings)})


def _holidays(request: ApiRequest, ctx: ApiContext, match: re.Match[str]) -> ApiResponse:
    _only_params(request.query, frozenset())
    year = parse_year(match.group(1))
    if year is None:
        raise _ApiError(400, "invalid_year", "Erwartet YYYY, zum Beispiel 2026.")
    _check_year(year)
    return ApiResponse(200, holidays_for(ctx.settings, year))
```

(c) ergänze die Routentabelle hinter der `DELETE`-Zeile um:

```python
    Route("GET", re.compile(r"/v1/summary/week/([^/]+)"), _summary_week, SCOPE_LOCAL),
    Route("GET", re.compile(r"/v1/summary/month/([^/]+)"), _summary_month, SCOPE_LOCAL),
    Route("GET", re.compile(r"/v1/categories"), _categories, SCOPE_LOCAL),
    Route("GET", re.compile(r"/v1/holidays/([^/]+)"), _holidays, SCOPE_LOCAL),
```

Ergänze außerdem im Modul-Docstring von `src/api_routes.py` hinter dem Satz über die lesenden Routen: `Auswertungen: `GET /v1/summary/week/{YYYY-Www}`, `/v1/summary/month/{YYYY-MM}`, `/v1/categories`, `/v1/holidays/{YYYY}` (Rechnung in `api_summary`).`

- [ ] **Step 4: Run to verify they pass**

Run: `python3 -m pytest tests/test_api_routes.py tests/test_api_summary.py tests/test_api_wiring.py tests/test_api_server.py -q -p no:cacheprovider && ruff check src tests && npx --yes pyright@1.1.411 src/api_routes.py src/api_summary.py`
Expected: PASS, `All checks passed!`, `0 errors`.

- [ ] **Step 5: Commit**

~~~bash
git add src/api_routes.py tests/test_api_routes.py
git commit -m "feat(api): Auswertungs-Routen (#92)

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
~~~

---

### Task 4: Dokumentation, Spec und Gesamtlauf

**Files:**
- Modify: `README.md`, `docs/known-limitations.md`, `src/CLAUDE.md`, `CLAUDE.md`, `docs/superpowers/specs/2026-10-06-lokale-api-design.md`

**Interfaces:** keine; hält Doku und Code zusammen.

- [ ] **Step 1: README**

In `README.md`, Abschnitt „Lokale HTTP-API (optional)“:

(a) Im ersten Codeblock ergänze hinter der `…/v1/entries/2026-10-06`-Zeile:

~~~
curl -H "Authorization: Bearer <Token>" http://127.0.0.1:17653/v1/summary/month/2026-10
~~~

(b) Ergänze in der Tabelle hinter der `DELETE`-Zeile:

~~~
| `GET /v1/summary/week/{YYYY-Www}` | Auswertung einer ISO-Woche (z. B. `2026-W41`) |
| `GET /v1/summary/month/{YYYY-MM}` | Auswertung eines Monats (z. B. `2026-10`) |
| `GET /v1/categories` | die in den Einstellungen konfigurierten Kategorien |
| `GET /v1/holidays/{YYYY}` | Feiertage des eingestellten Bundeslands (leer, solange keins gesetzt ist) |
~~~

(c) Füge hinter dem Absatz „Die Antwort enthält `warnings` …“ (vor dem PowerShell-Absatz) ein:

~~~
Die Auswertungen rechnen wie die App in **ganzen Minuten**: `total_minutes` (Ist-Zeit), `days[]` (je Tag mit Ist-Zeit), `by_category[]` (absteigend; `""` heißt „ohne Kategorie“), `weeks[]` (jede ISO-Woche, die der Zeitraum berührt, mit der Summe der **ganzen** Woche und, bei aktivem Werkstudenten-Limit, `limit_minutes` und `exceeded`) und `pause_warnings[]`. Dazu der **Urlaub dieses Geräts**: `vacation_minutes` (um die am selben Tag erfasste Ist-Zeit gekappt, die betroffenen Tage stehen in `vacation_capped_days`) und `payable_minutes` („Zu vergüten gesamt“, Ist-Zeit plus Urlaub). Es gelten die Jahre 2000–2100; ungültige Pfade sind `400`, Jahre außerhalb `422`.
~~~

- [ ] **Step 2: Bekannte Grenzen**

In `docs/known-limitations.md`, Abschnitt „Lokale API (#92): bekannte Grenzen“, ergänze hinter dem Punkt „Schreiben ist Last-Write-Wins.“:

~~~
- **Auswertungen sind eine Momentaufnahme dieses Geräts.** Ist-Zeit und Urlaub werden nacheinander gelesen, ein gleichzeitiges Speichern in der App kann dazwischen liegen. Der Urlaub ist gerätelokal (reist nicht per Drive-Sync): dieselbe Woche liefert auf dem Laptop und auf dem Desktop dieselbe Ist-Zeit, aber nur den eigenen Urlaub und damit ein anderes `payable_minutes`. Das Wochenlimit zählt nur Ist-Zeit (Urlaub ist keine geleistete Arbeit). `workweek_only` wirkt hier nicht: die API liefert alle Daten.
~~~

- [ ] **Step 3: Architektur-Doku**

In `src/CLAUDE.md` ergänze hinter dem `api_entry_write.py`-Bullet:

~~~
- `api_summary.py` — Auswertungen der lokalen API (#92), Tk-frei, rein: Pfad-Parser (`parse_week`, `parse_month`, `parse_year`, nur ASCII-Ziffern, `fromisocalendar` entscheidet über KW 53), `summarize` (Tage, Kategorien, `weeks[]` mit Wochenlimit, Pausenwarnungen, Urlaub über `vacations.cap_by_worktime`), `category_names`, `holidays_for`. Gerechnet wird über **Minuten je Slot**; gespeicherte Slots sind Fremddaten, ein ungewöhnlicher Slot zählt 0 Minuten und wird geloggt. Die Routen (`/v1/summary/week|month`, `/v1/categories`, `/v1/holidays`) in `api_routes` holen nur den Snapshot (`Storage.get_all()`, `VacationStore.day_minutes()`), halten keinen Lock und melden nie `on_change`.
~~~

und im `api_routes.py`-Bullet hinter „Lesend: `GET /v1/status`, `/v1/entries`, `/v1/entries/{date}`.“ den Satz „Auswertungen: `/v1/summary/…`, `/v1/categories`, `/v1/holidays/{year}` (Rechnung in `api_summary`).“.

In `CLAUDE.md` (Wurzel) im Bullet „`src/api_routes.py`, `src/api_server.py`, `src/api_service.py`“: `(GET /v1/status, /v1/entries)` ergänzen um „, `/v1/summary/…`“ und eine Zeile „`src/api_summary.py` — Rechnung der Auswertungen (rein, s. `src/CLAUDE.md`).“ dahinter.

- [ ] **Step 4: Spec**

In `docs/superpowers/specs/2026-10-06-lokale-api-design.md`: im Stack-Abschnitt Punkt 5 ersetzen durch:

~~~
5. Auswertungen (rein lesend): `GET /v1/summary/week/{YYYY-Www}`, `/v1/summary/month/{YYYY-MM}`, `/v1/categories`, `/v1/holidays/{YYYY}`. Danach Reservierungen und Urlaub — Zuschnitt und offene Fragen in Issue #239.
~~~

und hinter der Endpunkt-Tabelle einen Abschnitt „### Auswertungen“:

~~~
### Auswertungen

`summary/week` und `summary/month` liefern dieselbe Form (`week` bzw. `month` trägt das Pfadsegment): `from`, `to`, `total_minutes`, `vacation_minutes`, `payable_minutes`, `vacation_capped_days[]` (`date`, `vacation_minutes`, `work_minutes`, `counted_minutes`), `days[]` (`date`, `minutes`, `slots`), `by_category[]` (`kategorie`, `minutes`), `weeks[]` (`iso_year`, `iso_week`, `total_minutes`, `limit_minutes` oder `null`, `exceeded`) und `pause_warnings[]` (`date`, `worked_minutes`, `actual_pause_minutes`, `required_pause_minutes`). Alles in ganzen Minuten. Der Urlaub ist der dieses Geräts, gekappt wie in Bericht und Webhook. `weeks[]` führt jede ISO-Woche, die der Zeitraum berührt, mit der Summe der ganzen Woche. Jahre 2000–2100 (422), ungültige Pfadform 400. `/v1/holidays/{YYYY}` liefert `{year, state, holidays: [{date, name}]}`, ohne Bundesland eine leere Liste.
~~~

- [ ] **Step 5: Gesamtlauf**

Run: `python3 -m pytest -q -p no:cacheprovider && ruff check . && npx --yes pyright@1.1.411 src/api_summary.py src/api_routes.py`
Expected: alle Tests grün (3396 + die neuen), `All checks passed!`, `0 errors`. Fällt `tests/test_claude_md_claims.py` wegen der Catch-all-Zahl, die Zahl „rund 125“ in `CLAUDE.md` auf die gezählte Größenordnung nachziehen (Ruling ins Ledger).

- [ ] **Step 6: Commit**

~~~bash
git add README.md docs/known-limitations.md src/CLAUDE.md CLAUDE.md docs/superpowers/specs/2026-10-06-lokale-api-design.md
git commit -m "docs(api): Auswertungen dokumentiert (#92)

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
~~~

---

## Mutationsprüfung (nach Task 3, vor dem Review)

Jeden Mutanten einzeln anwenden (Datei kopieren, genau eine Ersetzung, Tests laufen lassen, Datei zurückkopieren). Jeder muss mindestens einen Test rot färben:

| Datei | Mutation | Erwartet rot |
|---|---|---|
| `api_summary.py` | `first <= key <= last` → `first < key <= last` (und `first <= key < last`) | `test_range_bounds_are_inclusive` |
| `api_summary.py` | Minuten je Slot → `round(calculate_hours(...) * 60)` aufsummiert über Stunden | `test_sum_is_over_minutes_not_rounded_decimal_hours` |
| `api_summary.py` | `total > limit` → `total >= limit` | `test_exceeding_the_limit_is_flagged_exactly_above_it` |
| `api_summary.py` | Wochensumme nur aus dem Zeitraum statt aus allen sieben Tagen | `test_a_week_total_covers_the_whole_week_not_only_the_range` |
| `api_summary.py` | `kv[0] == ""` aus dem Sortierschlüssel entfernen | `test_by_category_is_sorted_by_minutes_then_name_and_keeps_the_empty_one` |
| `api_summary.py` | `cap_by_worktime`-Aufruf weglassen (`capped = dict(days)`) | `test_vacation_is_capped_by_the_work_on_the_same_day_and_says_so` |
| `api_summary.py` | `payable_minutes` = `total` | `test_vacation_in_range_is_added_to_payable_but_not_to_total` |
| `api_summary.py` | `isinstance(minutes, int)` ohne `not isinstance(minutes, bool)` | `test_junk_vacation_values_are_ignored` |
| `api_summary.py` | `except (TypeError, ValueError, AttributeError)` in `_slot_minutes` → `except ZeroDivisionError` | `test_an_odd_stored_slot_counts_zero_and_never_raises` |
| `api_summary.py` | `try/except` in `_pause_warnings` entfernen | `test_odd_data_on_one_day_does_not_hide_the_pause_warning_of_another` |
| `api_summary.py` | `_MONTH_RE` mit `\d` statt `[0-9]` | `test_parse_month_rejects_bad_input[...]` (Unicode-Ziffern) |
| `api_summary.py` | `fromisocalendar` durch eigene 1..53-Prüfung ersetzen | `test_parse_week_rejects_bad_input[2025-W53]` |
| `api_routes.py` | `_check_year(...)` in `_summary_month` entfernen | `test_years_outside_2000_to_2100_are_422` |
| `api_routes.py` | `_only_params(...)` in `_categories` entfernen | `test_summary_routes_take_no_query` |
| `api_routes.py` | `_locked(ctx)` um den Snapshot legen | `test_reading_a_summary_takes_no_data_lock_and_changes_nothing` |
| `api_routes.py` | `ctx.vacation_store.day_minutes()` → `{}` | `test_summary_includes_the_vacation_of_the_store` |

## Finale

Nach Task 4: Review über den ganzen Branch mit einem frischen Reviewer auf dem leistungsfähigsten Modell (Review Focus oben und die Rulings aus dem Ledger mitgeben), Critical/Important in **einem** Fix-Durchlauf (je Fix ein Test, der zuerst rot war), Minors ins Ledger und in Issue #233 bzw. #239. Danach `finishing-a-development-branch`: PR gegen `feat/api-write-entries` (`Refs #92`), in den Stack #236 hängen.
