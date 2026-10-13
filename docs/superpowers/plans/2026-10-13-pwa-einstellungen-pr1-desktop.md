# Einstellungen und Kategorien in der Handy-PWA — PR 1: Desktop

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `POST /v1/sync` nimmt `categories` und `category_times` vom Handy entgegen, merged sie über die vorhandene Sync-Logik in die Desktop-Einstellungen und liefert den Stand **nach** dem Anwenden zurück.

**Architecture:** Additiv, `PROTOCOL` bleibt 2. Neues Tk-freies Modul `src/mobile_settings.py` prüft die Anfrage als Fremddaten (und übernimmt die Bereinigungs-Helfer aus `mobile_sync`, Importzyklus vermeiden). `mobile_sync._phone_doc` setzt `settings` aus der Anfrage; `sync.merge` entscheidet, `apply_merged_doc_journaled` schreibt, alles unter dem vorhandenen `data_lock`. Die Antwort berechnet Kategorien und `defaults` erst nach dem Anwenden.

**Tech Stack:** Python 3.12, pytest, nur stdlib.

**Spec:** `docs/superpowers/specs/2026-10-13-pwa-einstellungen-kategorien-design.md`, Abschnitt „PR 1: Desktop“. PR 2 (die PWA) folgt und ist nicht Teil dieses Plans.

## Global Constraints

- `PROTOCOL` bleibt `2`; Änderungen rein additiv (`pwa/CLAUDE.md`, „Kompatibilität“, Regeln 1–2). **Zuerst** die aktuelle Form unter `pwa/test/fixtures/compat/*-pre-settings.json` einfrieren.
- Anfrage: `settings: {categories?: {value, modified_at}, category_times?: {value, modified_at}}`. **Andere Schlüssel sind `422`**; zusätzliche Felder im Payload (z. B. `device_id`) entfallen still.
- Fehler als `SyncError(422, "invalid_entry", …)` — `test_mobile_contract.py` sammelt jedes `SyncError(status, "code", …)` aus dem Quelltext; ein neuer Code bräuchte einen Eintrag in `pwa/test/fixtures/errors.json`. Die Meldung beginnt mit `Einstellung <Schlüssel>:`.
- `categories`: Liste, höchstens 100 Namen, je getrimmt, nicht leer, höchstens 100 Zeichen (Code Points), ohne Unicode-Klassen `Cc`/`Cs`, eindeutig. `category_times`: Objekt `{Name: Eintrag}`, Namen wie oben und (falls `categories` mitkommt) darin enthalten; Eintrag allgemein `{start?, end?, pause?}` oder `{mode: "per_day", days: {Wochentag: {start?, end?}}, pause?}`; Uhrzeit `HH:MM`, Pause ganze Zahl 0–1440 (kein `bool`).
- `modified_at` im festen Format `YYYY-MM-DDTHH:MM:SSZ`, höchstens 15 Minuten in der Zukunft; die Uhrregel `clock_skew` greift vor den Einstellungen.
- Der Stempel eines Handy-Werts wird auf `last_pull_at + 1 s` angehoben (zwei Uhren, wie bei Ist-Zeiten und Reservierungen).
- Sperrreihenfolge `devices_lock` → `sync_guard` → `data_lock` bleibt; Callbacks erst nach Freigabe.
- Neue Module Tk-frei; `mobile_settings.py` kommt in die Whitelist von `tests/test_type_annotations.py` (vollständige Annotationen). Jeder Catch-all loggt oder trägt eine Begründung.
- Kommentare/Docstrings deutsch, Stil wie `mobile_sync.py`. Branch `feat/pwa-einstellungen-kategorien`, Commits `type(scope): …` auf Deutsch.

## Review Focus

1. Das Handy schickt **nur** `category_times` mit einem Namen, den der Desktop nicht (mehr) kennt: `422`, nichts angewendet (auch die Ist-Zeiten der Anfrage nicht). → Task 3
2. Eine `per_day`-Kategorie, die das Handy unverändert zurückschickt, bleibt am Desktop **bitgleich** erhalten (keine verlorenen Wochentag-Zeiten). → Task 3
3. Änderung am Desktop **und** am Handy seit dem letzten Abgleich: ein Konflikt `kind: "setting"` entsteht, der Sieger gilt vorläufig, der Abgleich scheitert nicht. → Task 3
4. Dieselbe Anfrage zweimal (Antwort ging verloren): kein zweiter Konflikt, kein erneutes Schreiben. → Task 3
5. Die Antwort enthält die Kategorien **nach** dem Anwenden (der alte Fehler: sie wurden vor `perform_sync` berechnet). → Task 3 und 4

---

## Dateien

| Datei | Verantwortung |
|---|---|
| `pwa/test/fixtures/compat/*-pre-settings.json` (neu, 2) | Eingefrorene Vorgänger-Form |
| `src/mobile_settings.py` (neu) | Prüfung der Anfrage-Einstellungen; Bereinigungs-Helfer aus `mobile_sync` |
| `src/mobile_sync.py` | `SyncRequest.settings`, `parse_request`, `_phone_doc`, `perform_sync` |
| `src/mobile_routes.py` | übergibt `categories` nicht mehr |
| `tests/test_mobile_settings.py` (neu), `tests/test_mobile_sync.py`, `tests/test_mobile_routes.py`, `tests/test_mobile_contract.py`, `tests/test_type_annotations.py` | Tests |
| `src/CLAUDE.md`, `pwa/CLAUDE.md`, `CLAUDE.md` | Doku |

---

### Task 1: Vorgänger-Form einfrieren

**Files:**
- Create: `pwa/test/fixtures/compat/sync-request-pre-settings.json`, `pwa/test/fixtures/compat/sync-response-pre-settings.json`
- Modify: `tests/test_mobile_contract.py`

- [ ] **Step 1: Kopieren, bevor irgendetwas anderes geändert wird**

```bash
cd pwa/test/fixtures
cp sync-request.json  compat/sync-request-pre-settings.json
cp sync-response.json compat/sync-response-pre-settings.json
cd ../../..
git status --short   # nur die zwei neuen Dateien
```

- [ ] **Step 2: Test, dass der Desktop die alte Anfrage weiter annimmt und keine Einstellungen liest**

An `tests/test_mobile_contract.py` anhängen:

```python
def test_the_desktop_still_accepts_the_request_of_a_phone_without_settings():
    example = load("compat/sync-request-pre-settings.json")
    assert "settings" not in example

    parsed = mobile_sync.parse_request(json.dumps(example).encode(), now=example["client_time"])

    assert sorted(parsed.entries) == sorted(example["entries"])
    assert parsed.settings == {}
```

- [ ] **Step 3: Test läuft rot, Fixtures committen (den Test erst in Task 3 mit committen)**

Run: `pytest tests/test_mobile_contract.py::test_the_desktop_still_accepts_the_request_of_a_phone_without_settings -v`
Expected: FAIL (`SyncRequest` hat kein Attribut `settings`).

```bash
git add pwa/test/fixtures/compat/sync-request-pre-settings.json pwa/test/fixtures/compat/sync-response-pre-settings.json
git commit -m "test(mobil): Vertragsbeispiele vor den Einstellungen eingefroren"
```

---

### Task 2: `src/mobile_settings.py`

**Files:**
- Create: `src/mobile_settings.py`
- Modify: `src/mobile_sync.py` (Helfer ziehen um), `tests/test_type_annotations.py`
- Test: `tests/test_mobile_settings.py`

**Interfaces:**
- Consumes: `src.settings.WEEKDAY_KEYS`.
- Produces (`src/mobile_settings.py`):
  - `SETTING_KEYS = ("categories", "category_times")`, `MAX_CATEGORIES = 100`, `MAX_CATEGORY_NAME = 100`, `MAX_DEFAULT_PAUSE = 24 * 60`
  - `class SettingsError(Exception)` mit `.message: str`
  - `parse_settings(raw: object, *, now_dt: datetime.datetime, parse_utc: Callable[[object], datetime.datetime | None], skew_limit: datetime.timedelta) -> dict[str, dict[str, Any]]` — `{key: {"value": <geprüft>, "modified_at": str}}`
  - `check_times_names(times: Mapping[str, Any], categories: Iterable[str]) -> None` — wirft `SettingsError`, wenn ein Name nicht in `categories` steht
  - Umgezogen aus `mobile_sync`: `clock(value) -> str` (ehem. `_clock`), `pause(value) -> int | None` (ehem. `_pause`), `clean_category_times(entry) -> dict[str, Any]` (ehem. `_clean_category_times`), `MAX_DEFAULT_PAUSE`

- [ ] **Step 1: Failing tests**

```python
# tests/test_mobile_settings.py
import datetime

import pytest

from src import mobile_settings as ms

NOW_DT = datetime.datetime(2026, 10, 13, 12, 0, 0)
STAMP = "2026-10-13T11:00:00Z"


def parse_utc(text):
    try:
        return datetime.datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ")
    except (TypeError, ValueError):
        return None


def parse(raw):
    return ms.parse_settings(raw, now_dt=NOW_DT, parse_utc=parse_utc,
                             skew_limit=datetime.timedelta(minutes=15))


def block(value, modified_at=STAMP, **extra):
    return {"value": value, "modified_at": modified_at, **extra}


def bad(raw):
    with pytest.raises(ms.SettingsError) as excinfo:
        parse(raw)
    return excinfo.value.message


def test_both_keys_are_parsed_and_the_stamp_is_kept():
    out = parse({"categories": block(["Projekt", "Intern"]),
                 "category_times": block({"Projekt": {"start": "09:00", "end": "17:00", "pause": 30}})})

    assert out == {"categories": {"value": ["Projekt", "Intern"], "modified_at": STAMP},
                   "category_times": {"value": {"Projekt": {"start": "09:00", "end": "17:00", "pause": 30}},
                                      "modified_at": STAMP}}


def test_extra_payload_fields_are_dropped_silently():
    out = parse({"categories": block(["A"], device_id="evil", foo=1)})
    assert out == {"categories": {"value": ["A"], "modified_at": STAMP}}


def test_a_single_key_is_fine_and_an_empty_settings_object_too():
    assert list(parse({"categories": block([])})) == ["categories"]
    assert parse({}) == {}


@pytest.mark.parametrize("key", ["hourly_rate", "gcal_enabled", "device_name", "__proto__", ""])
def test_any_other_key_is_rejected_and_named(key):
    assert f"Einstellung {key}" in bad({key: block("x")})


def test_the_name_in_the_message_is_cut_and_safe():
    message = bad({"x" * 500 + "\ud800": block(1)})
    assert len(message) < 200
    message.encode("utf-8")                                    # kein Surrogat in der Meldung


@pytest.mark.parametrize("raw", [[], "x", 1, None])
def test_settings_must_be_an_object(raw):
    assert "Objekt" in bad(raw)


@pytest.mark.parametrize("payload", [None, [], "x", {"value": ["A"]}, {"modified_at": STAMP}])
def test_a_payload_needs_value_and_modified_at(payload):
    bad({"categories": payload})


@pytest.mark.parametrize("stamp,ok", [
    ("2026-10-13T12:15:00Z", True),        # genau 15 Minuten voraus
    ("2026-10-13T12:15:01Z", False),
    ("gestern", False),
    ("2026-10-13 11:00:00", False),
    (None, False),
])
def test_the_stamp_may_be_at_most_fifteen_minutes_ahead(stamp, ok):
    raw = {"categories": block(["A"], modified_at=stamp)}
    if ok:
        parse(raw)
    else:
        bad(raw)


@pytest.mark.parametrize("value", [
    "x", {"a": 1}, [1], [None], [""], ["  "], ["A", "A"], ["A", " A "],
    ["x" * 101], ["tab\there"], ["lone\ud800"],
    [f"K{i}" for i in range(101)],
])
def test_bad_category_lists_are_rejected(value):
    bad({"categories": block(value)})


def test_names_are_trimmed_and_the_limits_are_inclusive():
    out = parse({"categories": block(["  Projekt  ", "x" * 100, *[f"K{i}" for i in range(98)]])})
    assert out["categories"]["value"][0] == "Projekt"
    assert len(out["categories"]["value"]) == 100


@pytest.mark.parametrize("value", [
    [], "x", {"A": "x"}, {"A": []}, {"": {}}, {"A": {"start": "25:00"}}, {"A": {"start": "9:00"}},
    {"A": {"end": 900}}, {"A": {"pause": -1}}, {"A": {"pause": 1441}}, {"A": {"pause": True}},
    {"A": {"pause": "30"}}, {"A": {"pause": 1.5}}, {"A": {"foo": 1}}, {"A": {"mode": "general"}},
    {"A": {"mode": "per_day", "days": []}}, {"A": {"mode": "per_day", "days": {"xxx": {}}}},
    {"A": {"mode": "per_day", "days": {"mon": {"start": "99:00"}}}},
    {"A": {"mode": "per_day", "days": {"mon": {"foo": 1}}}},
    {"A": {"mode": "per_day", "start": "09:00"}},
])
def test_bad_category_times_are_rejected(value):
    bad({"category_times": block(value)})


def test_general_and_per_day_entries_survive_unchanged():
    times = {
        "Projekt": {"start": "09:00", "end": "17:00", "pause": 45},
        "Nur Pause": {"pause": 0},
        "Support": {"mode": "per_day", "pause": 15,
                    "days": {"fri": {"start": "07:00", "end": "11:00"}, "mon": {"start": "08:00"}}},
        "Tage ohne Zeit": {"mode": "per_day", "days": {}},
    }
    assert parse({"category_times": block(times)})["category_times"]["value"] == times


def test_an_empty_entry_is_dropped_like_the_desktop_dialog_does():
    out = parse({"category_times": block({"A": {}, "B": {"pause": 5}})})
    assert out["category_times"]["value"] == {"B": {"pause": 5}}


def test_times_names_must_be_in_the_same_requests_categories():
    bad({"categories": block(["A"]), "category_times": block({"B": {"pause": 5}})})


def test_check_times_names_against_the_current_desktop_categories():
    ms.check_times_names({"A": {"pause": 5}}, ["A", "B"])
    with pytest.raises(ms.SettingsError) as excinfo:
        ms.check_times_names({"C": {"pause": 5}}, ["A", "B"])
    assert "category_times" in excinfo.value.message and "C" in excinfo.value.message
```

Und für die umgezogenen Helfer (Verhalten unverändert; `tests/test_mobile_defaults.py` deckt `build_defaults` weiter ab):

```python
def test_the_moved_helpers_behave_as_before():
    assert ms.clock("09:30") == "09:30" and ms.clock("9:30") == "" and ms.clock(None) == ""
    assert ms.pause(30) == 30 and ms.pause("45") == 45 and ms.pause(True) is None
    assert ms.pause(1441) is None and ms.pause(-1) is None
    assert ms.clean_category_times({"start": "09:00", "pause": "x", "foo": 1}) == {"start": "09:00"}
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_mobile_settings.py -q`
Expected: FAIL (`ModuleNotFoundError: src.mobile_settings`).

- [ ] **Step 3: Implementation**

Zuerst die Helfer aus `src/mobile_sync.py` **ausschneiden** (`_CLOCK_RE`, `MAX_DEFAULT_PAUSE`, `_clock`, `_pause`, `_clean_category_times`; `_PLATFORMS` bleibt) und in das neue Modul einfügen (Namen ohne Unterstrich, Logik unverändert). Dann:

```python
# src/mobile_settings.py
"""Einstellungen im Abgleich mit dem Handy (PWA-Einstellungen), Tk-frei und ohne I/O.

Das Handy darf genau zwei Einstellungen setzen: `categories` und `category_times`. Der Teil
`settings` der Anfrage ist **Fremddaten** und wird strikt geprüft (`parse_settings`); den Merge
macht `sync.merge` wie zwischen zwei Desktops. Hier liegen außerdem die Helfer, mit denen die
Antwort die Standardzeiten bereinigt (`clean_category_times`).

Der Fehler ist ein `SettingsError`, den `mobile_sync` in `SyncError(422, "invalid_entry", …)`
übersetzt (ein eigener Code brauchte einen Eintrag in `pwa/test/fixtures/errors.json`)."""
from __future__ import annotations

import datetime
import re
import unicodedata
from collections.abc import Callable, Iterable, Mapping
from typing import Any

from src.settings import WEEKDAY_KEYS

SETTING_KEYS = ("categories", "category_times")
MAX_CATEGORIES = 100
MAX_CATEGORY_NAME = 100
MAX_DEFAULT_PAUSE = 24 * 60

_CLOCK_RE = re.compile(r"([01]\d|2[0-3]):[0-5]\d")
_ECHO_MAX = 40


class SettingsError(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


def clock(value: Any) -> str:
    return value if isinstance(value, str) and _CLOCK_RE.fullmatch(value) else ""


def pause(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        return None
    try:
        minutes = int(value)
    except ValueError:
        return None
    return minutes if 0 <= minutes <= MAX_DEFAULT_PAUSE else None


def clean_category_times(entry: Any) -> dict[str, Any]:
    """…  (Körper unverändert aus `mobile_sync._clean_category_times`, mit `clock`/`pause`)"""


def _label(text: object) -> str:
    # `ascii()` escaped auch Surrogate: die Meldung bleibt als UTF-8 schreibbar.
    return ascii(text)[1:-1][:_ECHO_MAX]


def _name(value: object, where: str) -> str:
    if not isinstance(value, str):
        raise SettingsError(f"{where}: Namen müssen Text sein.")
    name = value.strip()
    if not name:
        raise SettingsError(f"{where}: Namen dürfen nicht leer sein.")
    if len(name) > MAX_CATEGORY_NAME:
        raise SettingsError(f"{where}: Namen dürfen höchstens {MAX_CATEGORY_NAME} Zeichen haben.")
    # Cc: Steuerzeichen; Cs: Surrogate. Ein einzelnes Surrogat ließe sich nicht als UTF-8
    # schreiben und machte jedes spätere Speichern der Einstellungen unmöglich.
    if any(unicodedata.category(ch) in ("Cc", "Cs") for ch in name):
        raise SettingsError(f"{where}: Namen dürfen keine Steuerzeichen oder ungültigen Unicode-Zeichen enthalten.")
    return name


def _parse_categories(value: object) -> list[str]:
    where = "Einstellung categories"
    if not isinstance(value, list):
        raise SettingsError(f"{where}: muss eine Liste sein.")
    if len(value) > MAX_CATEGORIES:
        raise SettingsError(f"{where}: höchstens {MAX_CATEGORIES} Kategorien.")
    names: list[str] = []
    for item in value:
        name = _name(item, where)
        if name in names:
            raise SettingsError(f"{where}: {_label(name)!s} kommt doppelt vor.")
        names.append(name)
    return names


def _time_field(value: object, where: str, label: str) -> str:
    if not isinstance(value, str) or not _CLOCK_RE.fullmatch(value):
        raise SettingsError(f"{where}: {label} muss genau HH:MM sein.")
    return value


def _clocks(raw: object, where: str, allowed: tuple[str, ...] = ("start", "end")) -> dict[str, str]:
    if not isinstance(raw, dict):
        raise SettingsError(f"{where}: muss ein Objekt sein.")
    unknown = sorted(str(key)[:_ECHO_MAX] for key in raw if key not in allowed)
    if unknown:
        raise SettingsError(f"{where}: unbekannte Felder {unknown[:5]}.")
    return {field: _time_field(raw[field], where, field) for field in allowed if field in raw}


def _parse_category_times(value: object) -> dict[str, dict[str, Any]]:
    where = "Einstellung category_times"
    if not isinstance(value, dict):
        raise SettingsError(f"{where}: muss ein Objekt sein.")
    if len(value) > MAX_CATEGORIES:
        raise SettingsError(f"{where}: höchstens {MAX_CATEGORIES} Kategorien.")
    out: dict[str, dict[str, Any]] = {}
    for raw_name, raw in value.items():
        name = _name(raw_name, where)
        entry_where = f"{where} {_label(name)}"
        if not isinstance(raw, dict):
            raise SettingsError(f"{entry_where}: Eintrag muss ein Objekt sein.")
        entry: dict[str, Any]
        if raw.get("mode") == "per_day":
            unknown = sorted(str(key)[:_ECHO_MAX] for key in raw if key not in ("mode", "days", "pause"))
            if unknown:
                raise SettingsError(f"{entry_where}: unbekannte Felder {unknown[:5]}.")
            days_raw = raw.get("days", {})
            if not isinstance(days_raw, dict):
                raise SettingsError(f"{entry_where}: days muss ein Objekt sein.")
            days: dict[str, dict[str, str]] = {}
            for key, day in days_raw.items():
                if key not in WEEKDAY_KEYS:
                    raise SettingsError(f"{entry_where}: unbekannter Wochentag {_label(key)}.")
                days[key] = _clocks(day, f"{entry_where} {key}")
            entry = {"mode": "per_day", "days": days}
        elif "mode" in raw:
            raise SettingsError(f"{entry_where}: mode darf nur per_day sein.")
        else:
            entry = _clocks({key: val for key, val in raw.items() if key != "pause"}, entry_where)
        if "pause" in raw:
            minutes = raw["pause"]
            if isinstance(minutes, bool) or not isinstance(minutes, int) or not 0 <= minutes <= MAX_DEFAULT_PAUSE:
                raise SettingsError(f"{entry_where}: pause muss eine ganze Zahl von 0 bis {MAX_DEFAULT_PAUSE} sein.")
            entry["pause"] = minutes
        # Ein leerer allgemeiner Eintrag entfällt (wie `collect_categories` am Desktop); ein
        # `per_day`-Eintrag bleibt auch ohne Tage erhalten (`test_general_and_per_day_…`).
        if entry or raw.get("mode") == "per_day":
            out[name] = entry
    return out
```

```python
def check_times_names(times: Mapping[str, Any], categories: Iterable[str]) -> None:
    """Jeder Name in `category_times` muss eine bekannte Kategorie sein (sonst `SettingsError`)."""
    known = set(categories)
    for name in times:
        if name not in known:
            raise SettingsError(f"Einstellung category_times: {_label(name)} steht nicht in categories.")


def parse_settings(raw: object, *, now_dt: datetime.datetime,
                   parse_utc: Callable[[object], datetime.datetime | None],
                   skew_limit: datetime.timedelta) -> dict[str, dict[str, Any]]:
    """`settings` der Anfrage → `{key: {"value", "modified_at"}}`. Wirft `SettingsError`; dann wurde
    nichts angewendet. Nur `SETTING_KEYS` sind erlaubt."""
    if not isinstance(raw, dict):
        raise SettingsError("settings muss ein Objekt sein.")
    for key in raw:
        if key not in SETTING_KEYS:
            raise SettingsError(f"Einstellung {_label(key)}: nicht erlaubt (erlaubt: "
                                f"{', '.join(SETTING_KEYS)}).")
    out: dict[str, dict[str, Any]] = {}
    for key in SETTING_KEYS:
        if key not in raw:
            continue
        payload = raw[key]
        if not isinstance(payload, dict) or "value" not in payload or "modified_at" not in payload:
            raise SettingsError(f"Einstellung {key}: erwartet wird {{value, modified_at}}.")
        modified = parse_utc(payload["modified_at"])
        if modified is None:
            raise SettingsError(f"Einstellung {key}: modified_at muss YYYY-MM-DDTHH:MM:SSZ sein.")
        if modified - now_dt > skew_limit:
            raise SettingsError(f"Einstellung {key}: modified_at liegt in der Zukunft.")
        value = _parse_categories(payload["value"]) if key == "categories" else _parse_category_times(payload["value"])
        out[key] = {"value": value, "modified_at": str(payload["modified_at"])}
    if "categories" in out and "category_times" in out:
        check_times_names(out["category_times"]["value"], out["categories"]["value"])
    return out
```

Den Docstring-Rumpf von `clean_category_times` durch den kopierten Körper aus `mobile_sync` ersetzen (nicht kürzen). In `src/mobile_sync.py` die Importe ergänzen:

```python
from src import mobile_pairing, mobile_reservations, mobile_settings, sync, sync_history, sync_journal
from src.mobile_settings import clean_category_times, clock, pause
```

und `_clock(`→`clock(`, `_pause(`→`pause(`, `_clean_category_times(`→`clean_category_times(` in `build_defaults` ersetzen; `MAX_DEFAULT_PAUSE` wird, falls noch irgendwo gelesen, aus `mobile_settings` importiert (`grep -rn MAX_DEFAULT_PAUSE src tests`).

`tests/test_type_annotations.py`: `"src/mobile_settings.py",` neben `"src/mobile_sync.py",` eintragen.

- [ ] **Step 4: Run to verify pass**

Run: `pytest tests/test_mobile_settings.py tests/test_mobile_defaults.py tests/test_type_annotations.py -q && ruff check .`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/mobile_settings.py src/mobile_sync.py tests/test_mobile_settings.py tests/test_type_annotations.py
git commit -m "feat(mobil): Einstellungen vom Handy prüfen — categories und category_times als Fremddaten"
```

---

### Task 3: In `mobile_sync` einhängen

**Files:**
- Modify: `src/mobile_sync.py`
- Test: `tests/test_mobile_sync.py`, `tests/test_mobile_contract.py` (Test aus Task 1 jetzt mit anlegen)

**Interfaces:**
- Consumes: Task 2 (`parse_settings`, `check_times_names`, `SettingsError`, `clean_category_times`).
- Produces:
  - `SyncRequest.settings: dict[str, dict[str, Any]] = field(default_factory=dict)` (`{key: {"value", "modified_at"}}`)
  - `parse_request` liest `settings` immer (kein Schalter); Fehler → `SyncError(422, "invalid_entry", …)`, **nach** der Uhrregel und den Einträgen
  - `perform_sync(..., categories: list[str] | None = None, ...)`: `None` → `category_names(settings)` **nach** dem Anwenden; ein übergebener Wert gilt weiter (Tests)

- [ ] **Step 1: Failing tests** (`tests/test_mobile_sync.py`; Helfer `body`, `rejected`, `env`, `run`, `put_desktop`, `DESKTOP`, `NOW`, `TODAY` stehen in der Datei)

```python
# --- Einstellungen --------------------------------------------------------------------------------

SET_STAMP = "2026-10-08T11:00:00Z"


def setting(value, modified_at=SET_STAMP):
    return {"value": value, "modified_at": modified_at}


def desktop_setting(env, key, value, modified_at):
    env.settings.apply_synced({key: {"value": value, "modified_at": modified_at, "device_id": "DESK"}})


def run_settings(env, settings, *, last_pull_at="", **over):
    request = mobile_sync.parse_request(body({}, settings=settings), now=NOW, today=TODAY)
    kwargs = dict(device_id=PHONE, device_name="Pixel", last_pull_at=last_pull_at,
                  storage=env.storage, settings=env.settings, conflicts_store=env.conflicts,
                  base=env.base, now=NOW, today=TODAY, desktop=DESKTOP)
    kwargs.update(over)
    return mobile_sync.perform_sync(request, **kwargs)


def test_settings_are_parsed_next_to_the_entries():
    request = mobile_sync.parse_request(body({}, settings={"categories": setting(["A"])}), now=NOW, today=TODAY)
    assert request.settings == {"categories": {"value": ["A"], "modified_at": SET_STAMP}}


def test_a_request_without_settings_has_none():
    assert parse({}).settings == {}


def test_a_forbidden_setting_key_is_422_invalid_entry_and_names_the_key():
    error = rejected(body({}, settings={"hourly_rate": setting(100)}))
    assert (error.status, error.code) == (422, "invalid_entry")
    assert "hourly_rate" in error.message


def test_the_clock_check_comes_before_the_settings():
    error = rejected(body({}, client_time="2026-10-08T13:00:00Z", settings={"hourly_rate": setting(1)}))
    assert error.code == "clock_skew"


def test_a_phone_change_wins_and_the_response_has_the_state_after_applying(env):
    desktop_setting(env, "categories", ["Alt"], "2026-10-01T10:00:00Z")

    response = run_settings(env, {"categories": setting(["Neu", "Intern"]),
                                  "category_times": setting({"Neu": {"start": "09:00", "pause": 30}})},
                            last_pull_at="2026-10-05T00:00:00Z")

    assert env.settings.get("categories") == ["Neu", "Intern"]
    assert response["categories"] == ["Neu", "Intern"]
    assert response["defaults"]["category_times"] == {"Neu": {"start": "09:00", "pause": 30}}


def test_a_slow_phone_clock_still_wins_against_an_older_desktop_value(env):
    desktop_setting(env, "categories", ["Alt"], "2026-10-04T10:00:00Z")

    # Das Handy hat nach dem letzten Abgleich (10-05) geändert, seine Uhr geht nach.
    run_settings(env, {"categories": setting(["Neu"], modified_at="2026-10-03T00:00:00Z")},
                 last_pull_at="2026-10-05T00:00:00Z")

    assert env.settings.get("categories") == ["Neu"]


def test_a_change_on_both_sides_becomes_a_setting_conflict_and_the_newer_wins(env):
    desktop_setting(env, "categories", ["Desktop"], "2026-10-06T10:00:00Z")

    response = run_settings(env, {"categories": setting(["Handy"], modified_at="2026-10-08T10:00:00Z")},
                            last_pull_at="2026-10-05T00:00:00Z")

    conflicts = env.conflicts.get_all()
    assert [(c["kind"], c["key"]) for c in conflicts] == [("setting", "categories")]
    assert env.settings.get("categories") == ["Handy"]
    assert response["conflicts"] == []                     # das Handy zeigt nur Einträge


def test_the_same_request_twice_changes_nothing_and_makes_no_second_conflict(env):
    desktop_setting(env, "categories", ["Alt"], "2026-10-01T10:00:00Z")
    first = run_settings(env, {"categories": setting(["Neu"])}, last_pull_at="2026-10-05T00:00:00Z")
    before = (env.settings.get("categories"), len(env.conflicts.get_all()))

    again = run_settings(env, {"categories": setting(["Neu"])}, last_pull_at="2026-10-05T00:00:00Z")

    assert (env.settings.get("categories"), len(env.conflicts.get_all())) == before
    assert again["categories"] == first["categories"]


def test_a_per_day_category_the_phone_sends_back_stays_bit_identical(env):
    times = {"Support": {"mode": "per_day", "pause": 15,
                         "days": {"fri": {"start": "07:00", "end": "11:00"}}},
             "Projekt": {"start": "09:00", "end": "17:00", "pause": 45}}
    desktop_setting(env, "categories", ["Support", "Projekt"], "2026-10-01T10:00:00Z")
    desktop_setting(env, "category_times", times, "2026-10-01T10:00:00Z")

    run_settings(env, {"categories": setting(["Support", "Projekt", "Neu"]), "category_times": setting(times)},
                 last_pull_at="2026-10-05T00:00:00Z")

    assert env.settings.get("category_times") == times


def test_category_times_alone_with_an_unknown_name_is_422_and_applies_nothing(env):
    desktop_setting(env, "categories", ["A"], "2026-10-01T10:00:00Z")
    request = mobile_sync.parse_request(
        body({"2026-10-07": day()}, settings={"category_times": setting({"Fremd": {"pause": 5}})}),
        now=NOW, today=TODAY)

    with pytest.raises(SyncError) as excinfo:
        mobile_sync.perform_sync(request, device_id=PHONE, device_name="Pixel", last_pull_at="",
                                 storage=env.storage, settings=env.settings, conflicts_store=env.conflicts,
                                 base=env.base, now=NOW, today=TODAY, desktop=DESKTOP)

    assert (excinfo.value.status, excinfo.value.code) == (422, "invalid_entry")
    assert env.storage.get("2026-10-07") is None
    assert env.settings.get("category_times") == {}


def test_without_a_categories_argument_the_response_reads_the_settings(env):
    desktop_setting(env, "categories", ["Aus den Einstellungen"], "2026-10-01T10:00:00Z")
    assert run_settings(env, {})["categories"] == ["Aus den Einstellungen"]
```

Dazu `tests/test_mobile_contract.py`: der Test aus Task 1 Step 2 (jetzt grün) wird mit diesem Task committet.

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_mobile_sync.py tests/test_mobile_contract.py -q`
Expected: FAIL (`parse_request` kennt `settings` nicht; `perform_sync` verlangt `categories`).

- [ ] **Step 3: Implementation** (`src/mobile_sync.py`)

`SyncRequest` um ein Feld ergänzen (hinter `reservations`):

```python
    # {key: {value, modified_at}} der Einstellungen, die das Handy setzen darf (`categories`,
    # `category_times`); leer, wenn es keine sendet. Geprüft von `mobile_settings.parse_settings`.
    settings: dict[str, dict[str, Any]] = field(default_factory=dict)
```

In `parse_request` hinter dem Reservierungs-Block, vor `wish = …`:

```python
    settings: dict[str, dict[str, Any]] = {}
    if "settings" in data:
        try:
            settings = mobile_settings.parse_settings(
                data["settings"], now_dt=now_dt, parse_utc=_parse_utc, skew_limit=CLOCK_SKEW_LIMIT)
        except mobile_settings.SettingsError as error:
            raise SyncError(422, "invalid_entry", error.message) from None
```

und den `SyncRequest(...)`-Aufruf um `settings` ergänzen. Docstring von `parse_request` ergänzen: „`settings` darf nur `categories`/`category_times` enthalten.“

`_phone_doc`: statt `"settings": {}`

```python
        "settings": {
            key: {"value": payload["value"], "modified_at": max(payload["modified_at"], floor),
                  "device_id": device_id}
            for key, payload in request.settings.items()
        },
```

und den Docstring um einen Satz ergänzen: die Einstellungen bekommen denselben angehobenen Stempel.

`perform_sync`: Signatur `categories: list[str] | None = None`; direkt nach `try:`/`with`-Beginn **vor** dem Snapshot, damit nichts angewendet wird:

```python
            if "category_times" in request.settings and "categories" not in request.settings:
                try:
                    mobile_settings.check_times_names(
                        request.settings["category_times"]["value"], category_names(settings))
                except mobile_settings.SettingsError as error:
                    raise SyncError(422, "invalid_entry", error.message) from None
```

Nach dem Lock-Block (dort, wo `cap = window_cap(…)` steht) die Namen bestimmen und verwenden:

```python
        names = categories if categories is not None else category_names(settings)
        …
        return build_response(merged, …, categories=names,
                              defaults=build_defaults(settings, names), …)
```

(`defaults=build_defaults(settings, categories)` und `categories=categories` durch `names` ersetzen.) Import: `from src.api_summary import category_names` zu den Importen — bei einem Importzyklus (`pytest` meldet ihn sofort) stattdessen `category_names` nach `mobile_settings` verschieben und von dort importieren; `api_summary` re-exportiert es dann nicht, `api_routes`/Tests importieren es weiter aus `api_summary` (Funktion dort lassen, in `mobile_settings` nur einen dünnen Import-freien Nachbau vermeiden — erst bei tatsächlichem Zyklus anfassen).

- [ ] **Step 4: Run to verify pass**

Run: `pytest tests/test_mobile_sync.py tests/test_mobile_contract.py tests/test_mobile_defaults.py tests/test_mobile_settings.py -q && ruff check .`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/mobile_sync.py tests/test_mobile_sync.py tests/test_mobile_contract.py
git commit -m "feat(mobil): Einstellungen im Abgleich — Merge über sync.merge, Antwort nach dem Anwenden"
```

---

### Task 4: Route und Vertragsbeispiele

**Files:**
- Modify: `src/mobile_routes.py`
- Test: `tests/test_mobile_routes.py`, `tests/test_mobile_contract.py`

**Interfaces:**
- Consumes: Task 3.
- Produces: `/v1/sync` ohne Parameter `categories=`; die Route reicht `settings` nur durch `parse_request`.

- [ ] **Step 1: Failing tests** (`tests/test_mobile_routes.py`, Helfer `sync`, `add_device`, `error_code`, `opened`, `call`, `sync_body`)

```python
# --- Einstellungen --------------------------------------------------------------------------------

SETTING_STAMP = "2026-10-08T11:00:00Z"


def test_a_sync_with_settings_changes_the_desktop_and_answers_with_the_new_state(env):
    _record, token = add_device(env)

    response = sync(env, token, settings={
        "categories": {"value": ["Neu"], "modified_at": SETTING_STAMP},
        "category_times": {"value": {"Neu": {"start": "09:00", "pause": 30}}, "modified_at": SETTING_STAMP}})

    assert response.status == 200
    assert env.ctx.settings.get("categories") == ["Neu"]
    assert response.body["categories"] == ["Neu"]
    assert response.body["defaults"]["category_times"] == {"Neu": {"start": "09:00", "pause": 30}}


def test_a_forbidden_setting_is_an_encrypted_422_and_changes_nothing(env):
    _record, token = add_device(env)

    response = sync(env, token, {"2026-10-07": day()},
                    settings={"hourly_rate": {"value": 100, "modified_at": SETTING_STAMP}})

    assert response.status == 422 and error_code(response) == "invalid_entry"
    assert "2026-10-07" not in env.ctx.storage.get_all_raw()
    assert env.ctx.settings.get("hourly_rate") != 100
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_mobile_routes.py -q -k "setting"`
Expected: Der erste Test kann bereits grün sein (die Route reicht `categories=` durch, und `perform_sync` rechnet danach); der Fehler zeigt sich im zweiten oder, falls beide grün sind, im Quelltext-Schritt unten. Beides ist in Ordnung — Step 3 räumt die Route trotzdem auf.

- [ ] **Step 3: Implementation** (`src/mobile_routes.py`)

Im Aufruf von `mobile_sync.perform_sync(...)` den Parameter `categories=category_names(ctx.settings),` **entfernen** (er schriebe sonst den Stand von vor dem Anwenden fest). Wird `category_names` danach in `mobile_routes.py` nicht mehr gebraucht, den Import entfernen (`ruff check .` meldet es).

Zusätzlich ein Regressionstest für genau diesen Fehler:

```python
def test_the_route_does_not_pin_the_categories_before_applying(env):
    import inspect
    assert "categories=category_names" not in inspect.getsource(mobile_routes._sync)
```

- [ ] **Step 4: Run to verify pass**

Run: `pytest -q --ignore=tests/test_qr.py && ruff check . && (cd pwa && node --test)`
Expected: PASS (lokal fehlt `segno` für `test_qr.py`).

- [ ] **Step 5: Commit**

```bash
git add src/mobile_routes.py tests/test_mobile_routes.py
git commit -m "fix(mobil): Route berechnet die Kategorien nicht mehr vor dem Anwenden"
```

---

### Task 5: Doku

**Files:**
- Modify: `src/CLAUDE.md`, `pwa/CLAUDE.md`, `CLAUDE.md`

- [ ] **Step 1: `src/CLAUDE.md`**

Im `mobile_sync.py`-Absatz (Daten- & Persistenz-Schicht) ergänzen: **Einstellungen reisen additiv mit** (`settings`, `PROTOCOL` 2): nur `categories` und `category_times`, alles andere `422`; Prüfung als Fremddaten in `mobile_settings.parse_settings` (Grenzen: ≤100 Namen à ≤100 Zeichen, eindeutig, Uhrzeiten `HH:MM`, Pause 0–1440, `per_day` erlaubt); Merge über `sync.merge` wie zwischen zwei Desktops (`_phone_doc` setzt `settings`, Stempel auf `last_pull_at + 1 s` angehoben), Konflikte `kind: "setting"` nur im Desktop-Dialog; `category_times` ohne `categories` prüft `perform_sync` gegen den Desktop-Stand; die Antwort berechnet Kategorien und `defaults` **nach** dem Anwenden (`categories=None`; die Route übergibt nichts mehr). Eine `per_day`-Kategorie, die das Handy unverändert zurückschickt, bleibt erhalten. Dazu ein Absatz `mobile_settings.py` (Tk-frei, Helfer `clock`/`pause`/`clean_category_times` von `mobile_sync` hierher).

- [ ] **Step 2: `pwa/CLAUDE.md`**

Kompatibilität, Regel 4: „…und der Stand vor den Einstellungen (`compat/*-pre-settings.json`, ohne `settings`)“.

- [ ] **Step 3: Wurzel-`CLAUDE.md`**

Neue Zeile `src/mobile_settings.py` hinter `src/mobile_reservations.py`: Prüfung der vom Handy gesendeten Einstellungen (`categories`, `category_times`) als Fremddaten, dazu die Bereinigungs-Helfer für die Standardzeiten der Antwort; Tk-frei. In der `mobile_sync.py`-Zeile „und der Einstellungs-Teil (`settings`)“ ergänzen.

- [ ] **Step 4: Prüfen und committen**

Run: `pytest tests/test_claude_md_claims.py -q && ruff check .`
Expected: PASS.

```bash
git add src/CLAUDE.md pwa/CLAUDE.md CLAUDE.md
git commit -m "docs(mobil): Einstellungen im Handy-Abgleich"
```

---

## Abschluss

- [ ] Vollständiger Lauf: `pytest -q --ignore=tests/test_qr.py`, `ruff check .`, `(cd pwa && node --test)`; `pyright` läuft in der CI.
- [ ] Manuell mit `tests/mobile_phone.py` oder dem Dev-Server (`scripts/pwa_devserver.py`): Kategorien senden, in `settings.json` des Desktops prüfen, Konflikt erzeugen (Desktop und Handy ändern nach dem letzten Abgleich).
- [ ] PR gegen `master`, Titel `feat(mobil): Kategorien vom Handy setzen (PR 1/2: Desktop)`, kein `release:*`-Label, kein Plattform-Label. Danach Pre-Release (Desktop), dann PR 2 (PWA).

## Self-Review

- **Spec-Abdeckung:** Einfrieren → T1; Anfrage mit Whitelist und Grenzen, `mobile_settings.py`, Umzug der Helfer → T2; `_phone_doc`/Stempel-Anhebung, Merge/Konflikt, Antwort nach dem Anwenden, `category_times` allein → T3; Route-Korrektur → T4; Tests und Doku → T3–T5. Nicht Teil: PWA (PR 2), Konflikte auf dem Handy, Wochentag-Standards.
- **Platzhalter-Scan:** Die Körper von `clean_category_times` und die Ersetzungen in `build_defaults` verweisen auf den vorhandenen Code in `mobile_sync.py` (Umzug, kein Neuschreiben); Task 3 Step 3 enthält eine Bedingung („bei Importzyklus“), die erst `pytest` entscheidet. Sonst keine offenen Stellen.
- **Typkonsistenz:** `parse_settings`/`check_times_names`/`SettingsError`/`clean_category_times` (T2) werden in T3 gleich benannt; `SyncRequest.settings` und `perform_sync(categories=None)` in T3 und T4 gleich; die Meldungen beginnen überall mit `Einstellung <Schlüssel>`.
