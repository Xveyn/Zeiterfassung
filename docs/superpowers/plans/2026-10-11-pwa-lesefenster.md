# PWA-Lesefenster Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Der Desktop gibt eine einstellbare Obergrenze für das Lesefenster der Handy-PWA vor (Standard 365 Tage); das Handy wünscht sein Fenster innerhalb dieser Grenze und lädt ältere Zeiten nach — ohne dass die Datenmenge je einen Abgleich zum Scheitern bringt.

**Architecture:** Additive Protokollfelder (`PROTOCOL` bleibt 2): Anfrage `window_days` (Wunsch), Antwort `window_days` (gewährt) und `window_max_days` (Obergrenze). Reine Funktionen auf dem Desktop (`grant_window`, `fit_window`) klemmen den Wunsch auf die Obergrenze und kürzen das Fenster, wenn die Einträge ein Budget von 768 KiB sprengen. Die PWA hält Wunsch und Maximum im Meta, entscheidet DOM-frei in `window-policy.js` und zeigt in der Wochenansicht „Ältere Zeiten laden“.

**Tech Stack:** Python 3.12 / Tkinter (Desktop), reines JavaScript / `node --test` (PWA), pytest.

**Spec:** `docs/superpowers/specs/2026-10-11-pwa-lesefenster-design.md`

## Global Constraints

- `PROTOCOL = 2` bleibt (`src/mobile_sync.py`, `src/mobile_crypto.py`, `pwa/pairing.js`); nur additive Felder (`pwa/CLAUDE.md`, „Kompatibilität“).
- Obergrenze: Auswahl **30 / 90 / 180 / 365** Tage, Standard **365**, hart gedeckelt auf **365**; Einstellung `mobile_window_max_days`, gerätelokal, **nicht** in `SYNCED_SETTING_KEYS`.
- Standardfenster ohne Wunsch: **90** (`WINDOW_DAYS`), gedeckelt auf die Obergrenze.
- Mengenlimit: `MAX_RESPONSE_ENTRY_BYTES = 768 * 1024` (Klartext der Einträge im Fenster); das Standardfenster bleibt immer, auch wenn es allein größer ist.
- Der Wunsch wird **geklemmt, nicht abgelehnt**: kein neuer Fehlercode, `errors.json` unverändert.
- Stufen der PWA: `[90, 180, 365]`; Wunsch-Standard **90**.
- Fehlt `window_max_days` (älterer Desktop), ändert die PWA ihr Fenster nie und zeigt einen Hinweis statt eines wirkungslosen Knopfes.
- Umlaute in der UI (`ä ö ü ß`), Datumsanzeige deutsch; Tk-Code nur Labels/Widgets, Logik Tk-frei (`tab_rules.py`).
- Eingefrorene Fixtures unter `pwa/test/fixtures/compat/` werden **nie** mitgezogen; die Form **vor** der Änderung wird eingefroren.
- Kein Release, kein Versionsbump, kein CHANGELOG in diesem Plan.

## Review Focus

Eingaben und Zustände, die die Spec nahelegt und die ein Nutzer wirklich trifft; jede Zeile hat ihren Test in der genannten Task:

1. **Absurde Wünsche** (`0`, `-5`, `True`, `"365"`, `1e9`, `None`, `3.5`) → Standard bzw. Obergrenze, nie ein Fehler (Task 1).
2. **Schwere Einträge** (50 Slots/Tag, 100-Zeichen-Kategorie, 365 Tage) → Antwort bleibt unter dem Budget, Fenster ≥ Standardfenster, PWA-Timeout (15 s) bei 0,6 Mbit/s erreichbar (Task 2).
3. **Obergrenze am Desktop sinkt unter das Handyfenster, während das Handy unübertragene Tage außerhalb hat** → sauber aufgeräumt, unübertragene bleiben (Task 5).
4. **Alter Desktop ohne `window_max_days`** → kein Fensterwunsch wirkt, Hinweis statt Knopf, kein Absturz (Task 5/6).
5. **Wochenrand**: Woche liegt teilweise im Fenster → Hinweis erscheint nur, wenn der Wochenanfang außerhalb liegt; nach dem Nachladen verschwindet er; bei erreichter Grenze kein endloser Knopf (Task 5/6).
6. **Ungültige Einstellung im Desktop** (`mobile_window_max_days` = `7`, `"abc"`, `None` in der `settings.json`) → 365 (Task 1/4).

## File Structure

| Datei | Verantwortung |
|---|---|
| `src/settings.py` | Default `mobile_window_max_days` |
| `src/mobile_sync.py` | Konstanten, `window_cap`, `grant_window`, `fit_window`, Wunsch in `SyncRequest`, `build_response` |
| `src/mobile_routes.py` | Obergrenze je Abgleich aus den Settings lesen; Pair/Ping nennen das Standardfenster |
| `src/dialogs/settings_dialog/tab_rules.py`, `tab_mobile.py` | Auswahl „Verlauf auf dem Handy bis zu“ (Tk-frei getestet) |
| `pwa/window-policy.js` (neu) | Stufen, `stepFor`, `olderState` — DOM-frei |
| `pwa/sync.js`, `pwa/store.js` | Wunsch senden, `window_max_days` lesen, Meta |
| `pwa/view-model.js`, `views.js`, `app.js` | Hinweis/Knopf „Ältere Zeiten laden“, Zeile „Verlauf“ im Verbindungsdialog |
| `tests/test_mobile_window.py` (neu), `tests/test_mobile_volume.py` (neu) | Fensterrechnung; Datenmenge/Budget |
| `pwa/test/fixtures/**` | Live-Beispiele erweitern, Vorgänger einfrieren |
| `pwa/CLAUDE.md`, `src/CLAUDE.md`, `README.md`, `docs/known-limitations.md`, `tests/test_pwa_claude_md_claims.py` | Doku und Behauptungstests |

---

### Task 1: Fensterrechnung auf dem Desktop (rein)

**Files:**
- Modify: `src/settings.py` (DEFAULTS, bei den `mobile_*`-Einträgen)
- Modify: `src/mobile_sync.py` (Konstanten ab Zeile 43, `SyncRequest`, `parse_request`, neue Funktionen)
- Create: `tests/test_mobile_window.py`

**Interfaces:**
- Produces (für Task 2): `mobile_sync.WINDOW_DAYS = 90`, `HARD_MAX_WINDOW_DAYS = 365`, `WINDOW_CAP_CHOICES = (30, 90, 180, 365)`, `MAX_RESPONSE_ENTRY_BYTES = 768 * 1024`, `window_cap(raw: object) -> int`, `grant_window(wish: object, cap: int) -> int`, `fit_window(sizes: Mapping[str, int], *, today: datetime.date, window_days: int, floor_days: int, budget: int) -> int`, `SyncRequest.window_days: int | None` (Default `None`).

- [ ] **Step 1: Failing tests schreiben** — `tests/test_mobile_window.py`

```python
"""Fensterrechnung der Handy-Erfassung (#250): Obergrenze, Wunsch, Mengenlimit."""
import datetime
import json

import pytest

from src import mobile_sync
from src.mobile_sync import fit_window, grant_window, window_cap
from src.settings import SYNCED_SETTING_KEYS, DEFAULTS

TODAY = datetime.date(2026, 10, 8)


def test_the_cap_setting_defaults_to_365_and_stays_device_local():
    assert DEFAULTS["mobile_window_max_days"] == 365
    assert "mobile_window_max_days" not in SYNCED_SETTING_KEYS


@pytest.mark.parametrize("raw,expected", [
    (30, 30), (90, 90), (180, 180), (365, 365),
    (7, 365), (0, 365), (-1, 365), (366, 365), (10_000, 365),   # nicht in der Auswahl
    (True, 365), ("180", 365), ("abc", 365), (None, 365), (3.5, 365),
])
def test_the_cap_comes_only_from_the_offered_values(raw, expected):
    assert window_cap(raw) == expected


@pytest.mark.parametrize("wish,cap,expected", [
    (None, 365, 90),                 # kein Wunsch: Standardfenster
    (None, 30, 30),                  # ... gedeckelt auf die Obergrenze
    (180, 365, 180),
    (365, 365, 365),
    (400, 365, 365),                 # über der Obergrenze: Obergrenze
    (10**9, 365, 365),
    (1, 365, 1),
    (0, 365, 90), (-5, 365, 90),     # ungültig: Standardfenster
    (True, 365, 90), ("365", 365, 90), (3.5, 365, 90), ([], 365, 90),
    (180, 90, 90),                   # Obergrenze 90: nie mehr
])
def test_grant_window_clamps_the_wish_and_never_raises(wish, cap, expected):
    assert grant_window(wish, cap) == expected


def sizes_for(days, size):
    return {(TODAY - datetime.timedelta(days=i)).isoformat(): size for i in range(days + 1)}


def test_fit_window_keeps_the_whole_window_when_it_fits():
    assert fit_window(sizes_for(365, 100), today=TODAY, window_days=365, floor_days=90,
                      budget=100 * 400) == 365


def test_fit_window_ends_before_the_first_day_that_breaks_the_budget():
    # Budget für 10 Tage (heute zählt mit): der 11. Tag zurück passt nicht mehr hinein.
    granted = fit_window(sizes_for(365, 100), today=TODAY, window_days=365, floor_days=1,
                         budget=100 * 10)
    assert granted == 9
    first = (TODAY - datetime.timedelta(days=granted)).isoformat()
    kept = [d for d in sizes_for(365, 100) if first <= d <= TODAY.isoformat()]
    assert sum(100 for _ in kept) <= 100 * 10


def test_fit_window_never_goes_below_the_floor():
    assert fit_window(sizes_for(365, 10_000), today=TODAY, window_days=365, floor_days=90,
                      budget=1) == 90


def test_fit_window_floor_is_capped_by_the_requested_window():
    # Obergrenze 30: das Standardfenster von 90 darf das gewährte Fenster nicht über 30 heben.
    assert fit_window(sizes_for(30, 10_000), today=TODAY, window_days=30, floor_days=min(90, 30),
                      budget=1) == 30


def test_fit_window_ignores_days_outside_the_window_and_in_the_future():
    sizes = {**sizes_for(30, 100), (TODAY + datetime.timedelta(days=3)).isoformat(): 10**9,
             (TODAY - datetime.timedelta(days=200)).isoformat(): 10**9}
    assert fit_window(sizes, today=TODAY, window_days=30, floor_days=1, budget=100 * 40) == 30


def test_fit_window_with_nothing_to_send_keeps_the_window():
    assert fit_window({}, today=TODAY, window_days=180, floor_days=90, budget=1) == 180


def test_the_constants_match_the_spec():
    assert mobile_sync.WINDOW_DAYS == 90
    assert mobile_sync.HARD_MAX_WINDOW_DAYS == 365
    assert mobile_sync.WINDOW_CAP_CHOICES == (30, 90, 180, 365)
    assert mobile_sync.MAX_RESPONSE_ENTRY_BYTES == 768 * 1024


def _body(**over):
    doc = {"protocol": 2, "client_time": "2026-10-08T12:00:00Z", "last_pull_at": "", "entries": {}}
    doc.update(over)
    return json.dumps(doc).encode()


@pytest.mark.parametrize("sent,expected", [
    (180, 180), (365, 365), (1, 1),
    (None, None), (0, None), (-3, None), (True, None), ("365", None), (2.5, None), ([], None),
])
def test_parse_request_reads_the_window_wish_tolerantly(sent, expected):
    over = {} if sent is None else {"window_days": sent}
    parsed = mobile_sync.parse_request(_body(**over), now="2026-10-08T12:00:00Z")
    assert parsed.window_days == expected


def test_a_request_without_the_wish_is_still_valid():
    parsed = mobile_sync.parse_request(_body(), now="2026-10-08T12:00:00Z")
    assert parsed.window_days is None
```

- [ ] **Step 2: Rot sehen**

Run: `pytest tests/test_mobile_window.py -q`
Expected: FAIL (`ImportError: cannot import name 'fit_window'` bzw. `KeyError: 'mobile_window_max_days'`).

- [ ] **Step 3: Implementieren**

`src/settings.py` — bei den `mobile_*`-Defaults ergänzen:

```python
    # Obergrenze des Lesefensters der Handy-PWA in Tagen (#250): 30/90/180/365. Gerätelokal wie
    # die übrigen mobile_*; das Handy wünscht, der Desktop deckelt.
    "mobile_window_max_days": 365,
```

`src/mobile_sync.py` — oben `import json` ergänzen und nach den Konstanten (Zeile 43/44):

```python
WINDOW_DAYS = 90                    # Standardfenster, wenn das Handy keinen Wunsch äußert
HARD_MAX_WINDOW_DAYS = 365          # weiter geht kein Fenster, auch nicht per Einstellung
WINDOW_CAP_CHOICES = (30, 90, 180, 365)
MAX_RESPONSE_ENTRY_BYTES = 768 * 1024   # Klartext der Einträge im Fenster; s. fit_window
```

`SyncRequest` erweitern:

```python
@dataclass(frozen=True)
class SyncRequest:
    client_time: str
    entries: dict[str, dict[str, Any]]
    window_days: int | None = None      # Wunsch des Handys (#250); `None` = keiner/ungültig
```

In `parse_request` die Rückgabe ersetzen:

```python
    wish = data.get("window_days")
    window_days = wish if isinstance(wish, int) and not isinstance(wish, bool) and wish >= 1 else None
    return SyncRequest(str(data["client_time"]), entries, window_days)
```

Neue Funktionen (vor `build_response`):

```python
def window_cap(raw: object) -> int:
    """Die Obergrenze aus der Einstellung. Nur die angebotenen Werte gelten; alles andere
    (handbearbeitete `settings.json`, Fremdwert) fällt auf das Maximum zurück."""
    if isinstance(raw, int) and not isinstance(raw, bool) and raw in WINDOW_CAP_CHOICES:
        return raw
    return HARD_MAX_WINDOW_DAYS


def grant_window(wish: object, cap: int) -> int:
    """Das gewährte Fenster: der Wunsch (sonst das Standardfenster), auf `1..cap` geklemmt.
    Ein ungültiger Wunsch ist kein Fehler — das Handy bekommt dann das Standardfenster."""
    base = wish if isinstance(wish, int) and not isinstance(wish, bool) and wish >= 1 else WINDOW_DAYS
    return max(1, min(base, cap))


def fit_window(sizes: Mapping[str, int], *, today: datetime.date, window_days: int,
               floor_days: int, budget: int) -> int:
    """Kürzt das Fenster, wenn seine Einträge mehr als `budget` Byte ergäben.

    `sizes` ist die serialisierte Größe je Datum. Gezählt wird von heute rückwärts; das Fenster
    endet vor dem ersten Tag, der das Budget sprengt. Nie unter `floor_days` (das Standardfenster
    bleibt, wie es immer war), nie über `window_days`. Tage außerhalb von `[heute − window_days,
    heute]` zählen nicht."""
    first = (today - datetime.timedelta(days=window_days)).isoformat()
    last = today.isoformat()
    used = 0
    for date in sorted((d for d in sizes if first <= d <= last), reverse=True):
        used += sizes[date]
        if used > budget:
            cutoff = datetime.date.fromisoformat(date)       # dieser Tag passt nicht mehr hinein
            return min(window_days, max((today - cutoff).days - 1, floor_days))
    return window_days
```

- [ ] **Step 4: Grün sehen**

Run: `pytest tests/test_mobile_window.py -q`
Expected: PASS (alle).

- [ ] **Step 5: Commit**

```bash
git add src/settings.py src/mobile_sync.py tests/test_mobile_window.py
git commit -m "feat(mobil): Fensterrechnung für die Handy-Erfassung (Obergrenze, Wunsch, Mengenlimit) (#250)"
```

---

### Task 2: Antwort und Routen nutzen das Fenster; Datenmenge belegt

**Files:**
- Modify: `src/mobile_sync.py` (`build_response`, `perform_sync`)
- Modify: `src/mobile_routes.py` (Import Zeile 43, Ping ~134, Pair ~218)
- Modify: `tests/test_mobile_sync.py` (Helfer `respond`, Erwartung der Antwortfelder)
- Create: `tests/test_mobile_volume.py`

**Interfaces:**
- Consumes: Task 1 (`window_cap`, `grant_window`, `fit_window`, `SyncRequest.window_days`, Konstanten).
- Produces: `build_response(merged, *, sent_dates, today, now, excluded, categories, defaults, desktop, window_days: int, window_max_days: int)`; die Antwort trägt `window_days` (gewährt **und** gekürzt) und `window_max_days`.

- [ ] **Step 1: Failing tests** 

In `tests/test_mobile_sync.py`: Helfer und Erwartung anpassen —

```python
def respond(merged, *, sent=(), excluded=False, categories=("Projekt",), window_days=90, window_max_days=365):
    merged = {"entries": {}, "conflicts": [], "devices": {}, **merged}
    return mobile_sync.build_response(merged, sent_dates=sent, today=TODAY, now=NOW,
                                      excluded=excluded, categories=list(categories),
                                      defaults=DEFAULTS, desktop=DESKTOP,
                                      window_days=window_days, window_max_days=window_max_days)
```

und in `test_the_response_carries_the_protocol_fields_and_no_token` die erwartete Antwort um `"window_max_days": 365` ergänzen (`"window_days": 90` bleibt). Neue Tests ans Dateiende:

```python
def test_the_window_follows_the_granted_days_not_the_constant():
    merged = {"entries": {_iso(-100): _entry(_iso(-100)), _iso(-10): _entry(_iso(-10))}}

    assert sorted(respond(merged, window_days=90)["entries"]) == [_iso(-10)]
    wide = respond(merged, window_days=180)
    assert sorted(wide["entries"]) == [_iso(-100), _iso(-10)] and wide["window_days"] == 180


def test_perform_sync_grants_the_wish_up_to_the_setting(env):
    env.settings.set("mobile_window_max_days", 180)

    assert run(env, {}, window_days=365)["window_days"] == 180      # Wunsch über der Obergrenze
    assert run(env, {}, window_days=120)["window_days"] == 120
    assert run(env, {})["window_days"] == 90                          # kein Wunsch
    assert run(env, {})["window_max_days"] == 180


def test_perform_sync_reads_the_setting_on_every_call(env):
    assert run(env, {}, window_days=365)["window_days"] == 365
    env.settings.set("mobile_window_max_days", 30)
    assert run(env, {}, window_days=365)["window_days"] == 30
```

`run` muss den Wunsch durchreichen — im Helfer `run(env, entries, *, last_pull_at="", now=NOW, window_days=None, **over)`: den Body mit `body(entries, **({} if window_days is None else {"window_days": window_days}))` bauen (der Helfer `body(entries=None, **over)` existiert).

`tests/test_mobile_volume.py` (neu):

```python
"""Datenmenge der Sync-Antwort (#250): das Budget schützt vor der Zeitüberschreitung der PWA."""
import datetime
import json

import pytest

from src import mobile_crypto as mc
from src import mobile_sync

TODAY = datetime.date(2026, 10, 8)
NOW = "2026-10-08T12:00:00Z"
DEFAULTS = {"pause": 30, "weekdays": {}, "category_times": {}}
DESKTOP = {"name": "PC", "version": "1.0.0", "platform": "Linux"}
PWA_TIMEOUT_S = 15                      # AbortSignal.timeout in pwa/sync.js
WEAK_WLAN_BYTES_PER_S = 0.6e6 / 8       # 0,6 Mbit/s
MAX_WIRE_BYTES = PWA_TIMEOUT_S * WEAK_WLAN_BYTES_PER_S    # ≈ 1,1 MB


def entries(days, slots, *, every_day=True, category="Projekt"):
    out = {}
    for i in range(days + 1):
        if not every_day and i % 7 >= 5:
            continue
        date = (TODAY - datetime.timedelta(days=i)).isoformat()
        out[date] = {"slots": [{"start": f"{8 + k % 10:02d}:00", "end": f"{9 + k % 10:02d}:00",
                                "pause": 0, "kategorie": category} for k in range(slots)],
                     "modified_at": "2026-10-07T18:30:00Z", "device_id": "DESK", "deleted": False}
    return out


def wire_size(response):
    key = mc.new_device_key()
    _, response_key = mc.device_keys(key)
    envelope = mc.seal(response_key, direction="res", method="POST", path="/v1/sync",
                       device_id="d", seq=1, plaintext=json.dumps(response).encode())
    return len(json.dumps(envelope).encode())


def build(merged_entries, window_days=365):
    return mobile_sync.build_response(
        {"entries": merged_entries, "conflicts": [], "devices": {}}, sent_dates=[], today=TODAY,
        now=NOW, excluded=False, categories=["Projekt"], defaults=DEFAULTS, desktop=DESKTOP,
        window_days=window_days, window_max_days=365)


def test_a_realistic_year_is_granted_in_full_and_small():
    response = build(entries(365, 2, every_day=False))

    assert response["window_days"] == 365
    assert wire_size(response) < 150 * 1024          # gemessen: ≈ 96 KB


@pytest.mark.parametrize("slots,category", [(6, "Projekt"), (20, "Projekt"), (50, "Projekt"),
                                            (50, "Kategorie-" + "x" * 90)])
def test_heavy_data_never_exceeds_what_the_phone_can_fetch_in_time(slots, category):
    response = build(entries(365, slots, category=category))

    assert wire_size(response) <= MAX_WIRE_BYTES
    assert 90 <= response["window_days"] <= 365


def test_the_trimmed_window_is_what_the_entries_show():
    response = build(entries(365, 50, category="Kategorie-" + "x" * 90))
    first = (TODAY - datetime.timedelta(days=response["window_days"])).isoformat()

    assert response["window_days"] < 365
    assert min(response["entries"]) >= first                  # nichts jenseits des gemeldeten Fensters
    assert (TODAY - datetime.timedelta(days=response["window_days"] - 1)).isoformat() in response["entries"]


def test_the_default_window_stays_even_if_it_alone_is_too_big(monkeypatch):
    monkeypatch.setattr(mobile_sync, "MAX_RESPONSE_ENTRY_BYTES", 1000)

    assert build(entries(365, 50))["window_days"] == 90


def test_days_the_phone_sent_come_back_even_outside_the_trimmed_window(monkeypatch):
    monkeypatch.setattr(mobile_sync, "MAX_RESPONSE_ENTRY_BYTES", 1000)
    old = (TODAY - datetime.timedelta(days=300)).isoformat()

    response = mobile_sync.build_response(
        {"entries": entries(365, 50), "conflicts": [], "devices": {}}, sent_dates=[old], today=TODAY,
        now=NOW, excluded=False, categories=["Projekt"], defaults=DEFAULTS, desktop=DESKTOP,
        window_days=365, window_max_days=365)

    assert old in response["entries"] and response["window_days"] == 90
```

- [ ] **Step 2: Rot sehen** — `pytest tests/test_mobile_sync.py tests/test_mobile_volume.py -q` → FAIL (`build_response() got an unexpected keyword argument 'window_days'`).

- [ ] **Step 3: Implementieren** — `build_response` ersetzen:

```python
def _entry_bytes(date: str, clean: Mapping[str, Any]) -> int:
    """Serialisierte Größe eines Eintrags in der Antwort (wie `json.dumps` sie schreibt)."""
    return len(json.dumps({date: clean}).encode())


def build_response(merged: Mapping[str, Any], *, sent_dates: Iterable[str],
                   today: datetime.date, now: str, excluded: bool,
                   categories: list[str], defaults: Mapping[str, Any],
                   desktop: Mapping[str, str], window_days: int,
                   window_max_days: int) -> dict[str, Any]:
    """Die Antwort des Abgleichs aus dem Merge-Ergebnis, ohne `token`/`expires_at`
    (die ergänzt die Route). Fenster `[heute − Fenster, heute]` (heute ist das lokale
    Datum des Desktops) plus alle gesendeten Tage — beides für Einträge **und**
    Konflikte: ein Konflikt auf einem gesendeten Tag außerhalb des Fensters bliebe
    sonst unsichtbar. Ein gesendeter Tag, den der Merge verworfen hat (Self-Heal bei
    `excluded`), fehlt in `entries`.

    `window_days` ist das **gewährte** Fenster (`grant_window`); `fit_window` kürzt es,
    wenn die Einträge mehr als `MAX_RESPONSE_ENTRY_BYTES` ergäben (#250). Die Antwort
    nennt das Fenster, das tatsächlich gilt."""
    sent = set(sent_dates)
    last = today.isoformat()

    clean_entries: dict[str, dict[str, Any]] = {}
    for date, entry in (merged.get("entries") or {}).items():
        if isinstance(date, str) and _DATE_RE.fullmatch(date) and isinstance(entry, dict):
            clean = _clean_entry(entry)
            if clean is not None:
                clean_entries[date] = clean
    sizes = {date: _entry_bytes(date, clean) for date, clean in clean_entries.items()
             if date not in sent}
    granted = fit_window(sizes, today=today, window_days=window_days,
                         floor_days=min(WINDOW_DAYS, window_days),
                         budget=MAX_RESPONSE_ENTRY_BYTES)
    first = (today - datetime.timedelta(days=granted)).isoformat()

    def visible(date: str) -> bool:
        return date in sent or first <= date <= last

    entries = {date: clean for date, clean in sorted(clean_entries.items()) if visible(date)}
    return {
        "protocol": PROTOCOL,
        "server_time": now,
        "last_pull_at": now,
        "excluded": excluded,
        "window_days": granted,
        "window_max_days": window_max_days,
        "entries": entries,
        "conflicts": _conflict_views(merged, visible),
        "categories": list(categories),
        "defaults": dict(defaults),
        "desktop": dict(desktop),
    }
```

`perform_sync` — vor dem `try` bzw. vor dem Aufruf von `build_response`:

```python
        cap = window_cap(settings.get("mobile_window_max_days"))
        return build_response(merged, sent_dates=request.entries, today=today, now=now,
                              excluded=excluded, categories=categories,
                              defaults=build_defaults(settings, categories), desktop=desktop,
                              window_days=grant_window(request.window_days, cap),
                              window_max_days=cap)
```

`src/mobile_routes.py`: Import `from src.mobile_sync import WINDOW_DAYS, SyncError` → `from src.mobile_sync import SyncError, grant_window, window_cap`. Ping (`_ping`) und Pair (`_pair`) nennen das gewährte Standardfenster:

```python
def _standard_window(ctx: MobileContext) -> int:
    """Das Fenster ohne Wunsch (Ping und Kopplung): Standardfenster, gedeckelt auf die Obergrenze."""
    return grant_window(None, window_cap(ctx.settings.get("mobile_window_max_days")))
```

und `"window_days": WINDOW_DAYS` an beiden Stellen durch `_standard_window(ctx)` ersetzen. (Prüfen: `grep -n "WINDOW_DAYS" src tests` — alle übrigen Treffer in Tests auf `mobile_sync.WINDOW_DAYS` bleiben gültig, die Konstante existiert weiter.)

- [ ] **Step 4: Grün sehen** — `pytest tests/test_mobile_sync.py tests/test_mobile_volume.py tests/test_mobile_routes.py tests/test_mobile_contract.py -q`. Erwartet: PASS bis auf die Vertrags-Formtests (Task 3). Schlägt der Wire-Test auf `MAX_WIRE_BYTES` knapp fehl, **nicht** das Budget im Test lockern: `MAX_RESPONSE_ENTRY_BYTES` so weit senken, dass die Messung grün ist, und die Spec (Tabelle/Budget) nachziehen.

- [ ] **Step 5: Commit**

```bash
git add src tests/test_mobile_sync.py tests/test_mobile_volume.py
git commit -m "feat(mobil): Antwort mit gewährtem Fenster und Mengenlimit, Routen lesen die Obergrenze (#250)"
```

---

### Task 3: Vertragsbeispiele erweitern, Vorgänger einfrieren

**Files:**
- Create: `pwa/test/fixtures/compat/sync-response-pre-250.json`, `pwa/test/fixtures/compat/sync-request-pre-250.json` (Kopien der **aktuellen** Live-Beispiele, **vor** der Änderung)
- Modify: `pwa/test/fixtures/sync-request.json` (`"window_days": 180`), `pwa/test/fixtures/sync-response.json` (`"window_max_days": 365`)
- Modify: `tests/test_mobile_routes.py` (`sync_doc` trägt `"window_days": 90`), `tests/test_mobile_contract.py`, `pwa/test/compat.test.js`

**Interfaces:**
- Consumes: Task 2 (Antwort trägt `window_max_days`).
- Produces: Live-Fixtures mit den neuen Feldern; eingefrorene Vorgänger für Task 5.

- [ ] **Step 1: Vorgänger einfrieren (vor jeder Änderung an den Live-Dateien)**

```bash
cp pwa/test/fixtures/sync-response.json pwa/test/fixtures/compat/sync-response-pre-250.json
cp pwa/test/fixtures/sync-request.json  pwa/test/fixtures/compat/sync-request-pre-250.json
```

- [ ] **Step 2: Failing tests** — `tests/test_mobile_contract.py` am Ende:

```python
def test_the_desktop_still_accepts_the_request_of_a_phone_without_the_window_wish():
    example = load("compat/sync-request-pre-250.json")
    assert "window_days" not in example

    parsed = mobile_sync.parse_request(json.dumps(example).encode(), now=example["client_time"])

    assert parsed.window_days is None
    assert sorted(parsed.entries) == sorted(example["entries"])


def test_the_live_request_example_carries_the_wish_the_server_reads():
    example = load("sync-request.json")

    parsed = mobile_sync.parse_request(json.dumps(example).encode(), now=example["client_time"])

    assert parsed.window_days == example["window_days"]
```

`pwa/test/compat.test.js` ergänzen:

```js
test('the response of a desktop before the window wish (#250) is still understood', () => {
  const doc = frozen('sync-response-pre-250.json');
  assert.ok(!('window_max_days' in doc));
  const parsed = parseSyncResponse(doc);
  assert.equal(parsed.window_max, null);                 // unbekannt = älterer Desktop
  assert.equal(parsed.window_days, 90);
  assert.deepEqual(Object.keys(parsed.entries), ['2026-10-07', '2026-10-06']);
});
```

- [ ] **Step 3: Live-Fixtures ändern** — in `sync-request.json` nach `last_pull_at` `"window_days": 180`; in `sync-response.json` nach `window_days` `"window_max_days": 365`. In `tests/test_mobile_routes.py` den Helfer `sync_doc` (Zeile ~417) um `"window_days": 90` ergänzen:

```python
    doc = {"protocol": 2, "client_time": env.clock["now"], "last_pull_at": "", "window_days": 90,
           "entries": entries or {}}
```

- [ ] **Step 4: Prüfen**

Run: `pytest tests/test_mobile_contract.py tests/test_mobile_routes.py -q` → PASS. `cd pwa && node --test` → der neue Compat-Test ist **rot**, bis Task 5 `window_max` in `parseSyncResponse` liefert (erwartet); alle anderen grün. Falls `sync.test.js` einen Formvergleich der Anfrage hat (`keysOf(call.plain)` gegen `sync-request.json`), ist er bis Task 5 ebenfalls rot — beides schließt Task 5.

- [ ] **Step 5: Commit**

```bash
git add pwa/test tests
git commit -m "test(mobil): Vertragsbeispiele um das Fenster erweitert, Vorgänger eingefroren (#250)"
```

---

### Task 4: Auswahl „Verlauf auf dem Handy“ im Tab „Mobil“

**Files:**
- Modify: `src/dialogs/settings_dialog/tab_rules.py` (`mobile_updates`, neue Helfer neben `address_from_choice`)
- Modify: `src/dialogs/settings_dialog/tab_mobile.py` (Variable, Zeile im Formular, `FieldSet`)
- Modify: `tests/test_tab_rules.py` (`mobile_raw`, neue Tests), ggf. `tests/test_mobile_tab_wiring.py`

**Interfaces:**
- Consumes: `mobile_sync.WINDOW_CAP_CHOICES`, `mobile_sync.window_cap`.
- Produces: `tab_rules.window_cap_options() -> list[str]`, `window_cap_to_choice(days: object) -> str`, `window_cap_from_choice(choice: object) -> int`; `mobile_updates` liefert `"mobile_window_max_days": int`.

- [ ] **Step 1: Failing tests** — in `tests/test_tab_rules.py` (`mobile_raw` bekommt `"mobile_window_max_days": "365 Tage"` als Standardwert; dort steht der bestehende Helfer) und neu:

```python
def test_the_window_cap_choices_are_the_four_offered_values():
    assert tr.window_cap_options() == ["30 Tage", "90 Tage", "180 Tage", "365 Tage"]


@pytest.mark.parametrize("days,label", [(30, "30 Tage"), (365, "365 Tage"), (7, "365 Tage"),
                                        (None, "365 Tage"), ("x", "365 Tage"), (True, "365 Tage")])
def test_the_window_cap_shows_as_a_label_and_falls_back_to_the_maximum(days, label):
    assert tr.window_cap_to_choice(days) == label


@pytest.mark.parametrize("choice,days", [("30 Tage", 30), ("180 Tage", 180), ("365 Tage", 365),
                                         ("", 365), ("abc", 365), (None, 365), ("7 Tage", 365)])
def test_the_window_cap_choice_parses_tolerantly(choice, days):
    assert tr.window_cap_from_choice(choice) == days


def test_mobile_updates_carries_the_window_cap():
    assert tr.mobile_updates(mobile_raw(mobile_window_max_days="180 Tage"))["mobile_window_max_days"] == 180
    assert tr.mobile_updates(mobile_raw(mobile_window_max_days="kaputt"))["mobile_window_max_days"] == 365
```

(Der bestehende Test `assert tr.mobile_updates(mobile_raw()) == {…}` bei Zeile ~455 bekommt `"mobile_window_max_days": 365` in der erwarteten Map.)

- [ ] **Step 2: Rot** — `pytest tests/test_tab_rules.py -q` → FAIL (`AttributeError … window_cap_options`).

- [ ] **Step 3: Implementieren** — `tab_rules.py` (Import `from src.mobile_sync import WINDOW_CAP_CHOICES, window_cap`; dort, wo der Import zum Rest des Moduls passt):

```python
def window_cap_options() -> list[str]:
    """Die Auswahl der Combobox „Verlauf auf dem Handy bis zu“."""
    return [f"{days} Tage" for days in WINDOW_CAP_CHOICES]


def window_cap_to_choice(days: object) -> str:
    return f"{window_cap(days)} Tage"


def window_cap_from_choice(choice: object) -> int:
    """Die Obergrenze zu einer Auswahl; alles Unlesbare ist das Maximum."""
    head = str(choice or "").split(" ", 1)[0]
    return window_cap(int(head)) if head.isdigit() else window_cap(None)
```

`mobile_updates` um `"mobile_window_max_days": window_cap_from_choice(raw["mobile_window_max_days"]),` erweitern.

`tab_mobile.py` (Import der drei Helfer aus `tab_rules`): nach `address_var` anlegen

```python
        window_var = tk.StringVar(
            value=window_cap_to_choice(settings.get("mobile_window_max_days")))
```

im Formular unter „Adresse“ (innerhalb `with form.depends_on(enabled_var):`):

```python
            form.row("Verlauf bis zu:", dark_combo(body, window_var, window_cap_options(), width=12))
            form.hint("So viele Tage kann das Handy höchstens laden. Größere Fenster machen "
                      "jeden Abgleich größer (365 Tage ≈ 100 KB); das Handy wählt selbst, wie "
                      "viel es braucht.")
```

und `fields.add("mobile_window_max_days", window_var)`.

- [ ] **Step 4: Grün** — `pytest tests/test_tab_rules.py tests/test_mobile_tab_wiring.py -q` → PASS. Danach kurz von Hand: `python -m src.main` → Einstellungen → Mobil zeigt die Auswahl, Standard „365 Tage“, nach Speichern und Neuöffnen bleibt der Wert.

- [ ] **Step 5: Commit**

```bash
git add src/dialogs tests
git commit -m "feat(mobil): Obergrenze des Handy-Verlaufs im Tab Mobil einstellbar (#250)"
```

---

### Task 5: PWA — Wunsch senden, Maximum lesen, Entscheidungen

**Files:**
- Create: `pwa/window-policy.js`, `pwa/test/window-policy.test.js`
- Modify: `pwa/sync.js` (Anfrage ~Zeile 285, `parseSyncResponse` ~Zeile 119), `pwa/store.js` (`DEFAULT_META`, `applyResponse`), `pwa/sw-core.js` (`PRECACHE` + `'./window-policy.js'`)
- Modify: `pwa/test/sync.test.js`, `pwa/test/store.test.js`

**Interfaces:**
- Produces (für Task 6): `WINDOW_STEPS = [90, 180, 365]`, `DEFAULT_WISH = 90`, `daysBack(today: string, iso: string): number`, `stepFor(needDays: number, max: number): number`, `olderState({ firstDay, today, windowDays, windowMax, wish }): { kind: 'none'|'load'|'trimmed'|'capped'|'old_desktop', wish?: number, days?: number }`; Meta `window_wish: number` (Standard 90), `window_max: number|null`; `parseSyncResponse` liefert `window_max`.

- [ ] **Step 1: Failing tests** — `pwa/test/window-policy.test.js`:

```js
// pwa/test/window-policy.test.js
import { test } from 'node:test';
import assert from 'node:assert/strict';

import { DEFAULT_WISH, WINDOW_STEPS, daysBack, olderState, stepFor } from '../window-policy.js';

const TODAY = '2026-10-08';

test('the steps and the default wish', () => {
  assert.deepEqual(WINDOW_STEPS, [90, 180, 365]);
  assert.equal(DEFAULT_WISH, 90);
});

test('daysBack counts calendar days', () => {
  assert.equal(daysBack(TODAY, '2026-10-08'), 0);
  assert.equal(daysBack(TODAY, '2026-10-01'), 7);
  assert.equal(daysBack(TODAY, '2025-10-08'), 365);
  assert.equal(daysBack(TODAY, '2026-10-09'), -1);
});

test('stepFor takes the smallest step that covers the need, capped by the maximum', () => {
  assert.equal(stepFor(91, 365), 180);
  assert.equal(stepFor(180, 365), 180);
  assert.equal(stepFor(181, 365), 365);
  assert.equal(stepFor(1000, 365), 365);                 // jenseits: die größte Stufe
  assert.equal(stepFor(200, 180), 180);                  // Obergrenze des Desktops
  assert.equal(stepFor(100, 90), 90);
  assert.equal(stepFor(100, 30), 30);                    // Obergrenze unter dem Standard
});

const base = { today: TODAY, windowDays: 90, windowMax: 365, wish: 90 };

test('a week inside the window needs nothing', () => {
  assert.deepEqual(olderState({ ...base, firstDay: '2026-07-13' }), { kind: 'none' });   // 87 Tage zurück
  assert.deepEqual(olderState({ ...base, firstDay: '2026-10-05' }), { kind: 'none' });
  assert.deepEqual(olderState({ ...base, firstDay: '2026-10-12' }), { kind: 'none' });   // Zukunft
});

test('a week before the window offers to load older times with the right step', () => {
  assert.deepEqual(olderState({ ...base, firstDay: '2026-07-06' }), { kind: 'load', wish: 180 });  // 94 Tage
  assert.deepEqual(olderState({ ...base, firstDay: '2026-01-05' }), { kind: 'load', wish: 365 });  // 276 Tage
});

test('an old desktop (no maximum) cannot load more', () => {
  assert.deepEqual(olderState({ ...base, windowMax: null, firstDay: '2026-07-06' }), { kind: 'old_desktop' });
});

test('when the wish already covers the week but the window did not grow it was capped or trimmed', () => {
  // Obergrenze erreicht: der Desktop kann nicht mehr liefern.
  assert.deepEqual(olderState({ ...base, windowDays: 180, windowMax: 180, wish: 365, firstDay: '2025-12-01' }),
    { kind: 'capped', days: 180 });
  // Wunsch ist erfüllbar, aber die Antwort wurde wegen der Menge gekürzt.
  assert.deepEqual(olderState({ ...base, windowDays: 120, windowMax: 365, wish: 365, firstDay: '2026-01-05' }),
    { kind: 'trimmed', days: 120 });
});

test('after loading, the notice disappears once the week is inside the window', () => {
  assert.deepEqual(olderState({ ...base, windowDays: 180, wish: 180, firstDay: '2026-07-06' }), { kind: 'none' });
});

test('absurd inputs never throw', () => {
  for (const firstDay of ['', 'kaputt', null, undefined]) {
    assert.deepEqual(olderState({ ...base, firstDay }), { kind: 'none' });
  }
  assert.deepEqual(olderState({ ...base, windowDays: 'x', firstDay: '2026-07-06' }), { kind: 'none' });
});
```

`pwa/test/sync.test.js` (Test `make()` liefert `{ store, client, fetchFn }`; `fetchFn.calls[…].plain` ist der entschlüsselte Request):

```js
test('the request carries the window wish of the phone (#250)', async () => {
  const { store, client, fetchFn } = await make();
  await store.setMeta({ window_wish: 180 });

  await client.sync();

  assert.equal(fetchFn.calls.at(-1).plain.window_days, 180);
});

test('a fresh phone wishes the default window', async () => {
  const { client, fetchFn } = await make();
  await client.sync();
  assert.equal(fetchFn.calls.at(-1).plain.window_days, 90);
});

test('parseSyncResponse reads the maximum tolerantly', () => {
  const doc = fixture('sync-response.json');
  assert.equal(parseSyncResponse(doc).window_max, 365);
  for (const bad of [undefined, null, 0, -1, 'x', 1.5, 99999, true]) {
    const copy = fixture('sync-response.json');
    if (bad === undefined) delete copy.window_max_days; else copy.window_max_days = bad;
    assert.equal(parseSyncResponse(copy).window_max, null, String(bad));
  }
});
```

`pwa/test/store.test.js`:

```js
test('the wish defaults to 90, survives a restart, and the maximum comes from the response (#250)', async () => {
  const adapter = createMemoryAdapter();
  const { store } = await make({ adapter });
  assert.equal(store.getMeta().window_wish, 90);
  assert.equal(store.getMeta().window_max, null);

  await store.setMeta({ window_wish: 365 });
  await store.applyResponse(parsedResponse({ window_max: 180, window_days: 180 }), store.snapshotDirty(), TODAY);
  const again = new Store(adapter, clock());
  await again.load();
  assert.equal(again.getMeta().window_wish, 365);          // der Wunsch bleibt, auch über der Obergrenze
  assert.equal(again.getMeta().window_max, 180);
});

test('a shrinking window removes clean days outside it but keeps unsent ones (#250)', async () => {
  const { store } = await make();
  await store.applyResponse(parsedResponse({ window_days: 365, window_max: 365, entries: {
    '2026-03-02': remoteDay(), '2026-09-30': remoteDay() } }), store.snapshotDirty(), TODAY);
  await store.saveDay('2026-03-03', [SLOT]);                 // unübertragen, ebenfalls weit zurück
  assert.deepEqual(store.days().sort(), ['2026-03-02', '2026-03-03', '2026-09-30']);

  await store.applyResponse(parsedResponse({ window_days: 90, window_max: 90, entries: {
    '2026-09-30': remoteDay() } }), store.snapshotDirty(), TODAY);

  assert.deepEqual(store.days().sort(), ['2026-03-03', '2026-09-30']);   // sauber → weg, unübertragen → bleibt
});
```

(`parsedResponse(over)` aus `store.test.js` bekommt die Standardwerte `window_max: 365`; dort das Feld ergänzen.)

- [ ] **Step 2: Rot** — `cd pwa && node --test` → FAIL (`Cannot find module '../window-policy.js'`, `window_max` undefined …).

- [ ] **Step 3: Implementieren** — `pwa/window-policy.js`:

```js
// pwa/window-policy.js
// Lesefenster der PWA (#250): welche Stufe wird gewünscht, wann zeigt die Wochenansicht „Ältere Zeiten
// laden“, und was sagt sie, wenn der Desktop nicht mehr liefert? Reine Entscheidungen ohne Browser-API
// (getestet in test/window-policy.test.js). Das Fenster selbst bestimmt immer der Desktop: die Antwort
// nennt das gewährte `window_days` und die Obergrenze `window_max_days`.
import { isIsoDate } from './minutes.js';

export const WINDOW_STEPS = [90, 180, 365];
export const DEFAULT_WISH = 90;

/** Kalendertage von `iso` bis `today` (positiv = in der Vergangenheit). */
export function daysBack(today, iso) {
  return Math.round((Date.parse(`${today}T00:00:00Z`) - Date.parse(`${iso}T00:00:00Z`)) / 86400000);
}

/** Kleinste Stufe, die `needDays` abdeckt, höchstens `max` (die Obergrenze des Desktops). */
export function stepFor(needDays, max) {
  const step = WINDOW_STEPS.find((candidate) => candidate >= needDays) ?? WINDOW_STEPS.at(-1);
  return Math.min(step, max);
}

/** Was die Wochenansicht zum Rand des Fensters sagt. `firstDay` ist der Wochenanfang. */
export function olderState({ firstDay, today, windowDays, windowMax, wish }) {
  if (!isIsoDate(firstDay) || !isIsoDate(today) || !Number.isInteger(windowDays)) return { kind: 'none' };
  const need = daysBack(today, firstDay);
  if (need <= windowDays) return { kind: 'none' };
  if (!Number.isInteger(windowMax)) return { kind: 'old_desktop' };
  const target = stepFor(need, windowMax);
  if (wish >= target) {
    // Der Wunsch deckt die Woche schon ab und das Fenster ist trotzdem zu klein: der Desktop liefert nicht mehr.
    return windowDays >= windowMax ? { kind: 'capped', days: windowMax } : { kind: 'trimmed', days: windowDays };
  }
  return { kind: 'load', wish: target };
}
```

`pwa/sync.js` — Anfrage: im `payload` `window_days: meta.window_wish ?? 90,` nach `last_pull_at` ergänzen. `parseSyncResponse` — vor dem `return`:

```js
  const max = raw.window_max_days;
  const windowMax = Number.isInteger(max) && max >= 1 && max <= MAX_WINDOW_DAYS ? max : null;
```

und im Rückgabeobjekt `window_max: windowMax,`.

`pwa/store.js` — `DEFAULT_META` nach `window_days: 90,`:

```js
  window_wish: 90,         // gewünschtes Fenster in Tagen (#250); der Desktop deckelt
  window_max: null,        // Obergrenze des Desktops; null = unbekannt (älterer Desktop)
```

`applyResponse`: in `this._meta = {…}` `window_max: parsed.window_max ?? null,` ergänzen. `pwa/sw-core.js`: `'./window-policy.js',` in `PRECACHE`.

- [ ] **Step 4: Grün** — `cd pwa && node --test` → PASS (inkl. des Compat-Tests aus Task 3).

- [ ] **Step 5: Commit**

```bash
git add pwa
git commit -m "feat(pwa): Fensterwunsch senden, Obergrenze lesen, window-policy (#250)"
```

---

### Task 6: PWA — „Ältere Zeiten laden“ und Zeile „Verlauf“

**Files:**
- Modify: `pwa/view-model.js` (neue `olderModel`), `pwa/views.js` (`weekView`, `connectionDialog`), `pwa/app.js` (Render, Handler), `pwa/app.css` (falls nötig)
- Modify: `pwa/test/view-model.test.js`

**Interfaces:**
- Consumes: Task 5 (`olderState`, Meta `window_wish`/`window_max`/`window_days`).
- Produces: `view-model.olderModel(state, { windowDays }): { text: string, action: string|null, wish?: number }`; `connectionDialog` nimmt `{ …, window: { days, max, wish } }` und Handler `resetWindow`.

- [ ] **Step 1: Failing tests** — `pwa/test/view-model.test.js` (Import `olderModel`):

```js
// --- Ältere Zeiten (#250) ----------------------------------------------------------------------

test('nothing is shown while the week is inside the window', () => {
  assert.equal(olderModel({ kind: 'none' }), null);
});

test('the load notice names the step and offers the button', () => {
  const model = olderModel({ kind: 'load', wish: 180 });
  assert.match(model.text, /noch nicht geladen/);
  assert.equal(model.action, 'older');
  assert.equal(model.wish, 180);
  assert.match(model.buttonText, /180 Tage/);
});

test('capped, trimmed and old-desktop notices explain instead of offering a dead button', () => {
  const capped = olderModel({ kind: 'capped', days: 180 });
  assert.match(capped.text, /höchstens 180 Tage/);
  assert.match(capped.text, /Einstellungen → Mobil/);
  assert.equal(capped.action, null);

  const trimmed = olderModel({ kind: 'trimmed', days: 120 });
  assert.match(trimmed.text, /wegen der Datenmenge nur 120 Tage/);
  assert.equal(trimmed.action, null);

  const old = olderModel({ kind: 'old_desktop' });
  assert.match(old.text, /Desktop-App aktualisieren/);
  assert.equal(old.action, null);
});

test('the connection row reads the window and offers a reset only when it is above the default', () => {
  assert.deepEqual(windowRow({ days: 90, max: 365, wish: 90 }), { text: '90 Tage (Desktop erlaubt bis 365)', canReset: false });
  assert.deepEqual(windowRow({ days: 180, max: 365, wish: 180 }), { text: '180 Tage (Desktop erlaubt bis 365)', canReset: true });
  assert.deepEqual(windowRow({ days: 90, max: null, wish: 90 }), { text: '90 Tage', canReset: false });
  assert.deepEqual(windowRow({ days: 120, max: 365, wish: 365 }),
    { text: '120 Tage (gewünscht 365, Desktop erlaubt bis 365)', canReset: true });
});
```

(Import `windowRow` ebenfalls.)

- [ ] **Step 2: Rot** — `cd pwa && node --test` → FAIL (`olderModel is not a function`).

- [ ] **Step 3: Implementieren**

`pwa/view-model.js` (am Ende):

```js
// --- Lesefenster (#250) --------------------------------------------------------------------------

/** Text und Aktion für den Rand des Fensters (`window-policy.olderState`); `null`, wenn nichts zu sagen ist. */
export function olderModel(state) {
  switch (state.kind) {
    case 'load':
      return { text: 'Ältere Zeiten sind noch nicht geladen.', action: 'older', wish: state.wish,
        buttonText: `Ältere Zeiten laden (bis ${state.wish} Tage)` };
    case 'capped':
      return { text: `Der Desktop liefert höchstens ${state.days} Tage. Die Obergrenze lässt sich am Desktop unter Einstellungen → Mobil ändern.`, action: null };
    case 'trimmed':
      return { text: `Der Desktop liefert wegen der Datenmenge nur ${state.days} Tage.`, action: null };
    case 'old_desktop':
      return { text: 'Dieser Desktop kann nicht mehr als 90 Tage liefern. Bitte die Desktop-App aktualisieren.', action: null };
    default:
      return null;
  }
}

/** Die Zeile „Verlauf“ im Verbindungsdialog. */
export function windowRow({ days, max, wish }) {
  const parts = [];
  if (Number.isInteger(wish) && wish !== days) parts.push(`gewünscht ${wish}`);
  if (Number.isInteger(max)) parts.push(`Desktop erlaubt bis ${max}`);
  return {
    text: parts.length ? `${days} Tage (${parts.join(', ')})` : `${days} Tage`,
    canReset: Number.isInteger(wish) && wish > 90,
  };
}
```

`pwa/views.js`: `weekView(model, handlers)` rendert nach `h('ul', { class: 'days' }, …)` den Hinweis:

```js
    model.older && h('div', { class: 'hint older', role: 'status' },
      h('span', {}, model.older.text),
      model.older.action === 'older' && button(model.older.buttonText, () => handlers.older(model.older.wish), 'link', { 'data-focus': 'older' })),
```

`connectionDialog({ …, window: windowInfo }, handlers)` — nach der Zeile „Updates“ in der `dl`:

```js
      h('dt', { class: 'muted' }, 'Verlauf'), windowCell),
```

mit, vor dem `dialog`:

```js
  const row = windowRow(windowInfo);
  const reset = button('Auf 90 Tage zurücksetzen', () => { handlers.resetWindow(); dialog.close(); });
  reset.hidden = !row.canReset;
  const windowCell = h('dd', {}, row.text, ' ', reset);
```

`pwa/app.js` — im Render: nach `const model = weekModel({…})`:

```js
    const older = olderModel(olderState({
      firstDay: model.days[0].date, today: localIsoDate(new Date()), windowDays: meta.window_days,
      windowMax: meta.window_max, wish: meta.window_wish,
    }));
    model.older = older;
```

Handler im `weekView(model, {…})`-Objekt: `older: (wish) => this.loadOlder(wish),`. Neue Methoden:

```js
  async loadOlder(wish) {
    await this.store.setMeta({ window_wish: wish });
    this.trigger('manual');
  }

  async resetWindow() {
    await this.store.setMeta({ window_wish: DEFAULT_WISH });
    this.trigger('manual');
  }
```

In `openConnection()` dem Dialog `window: { days: meta.window_days, max: meta.window_max, wish: meta.window_wish }` und `resetWindow: () => this.resetWindow()` mitgeben. Imports: `olderState, DEFAULT_WISH` aus `./window-policy.js`; `olderModel` (und `windowRow` in `views.js`) aus `./view-model.js`.

- [ ] **Step 4: Grün** — `cd pwa && node --test` → PASS. Dann im Browser (Task 7, Schritt 3).

- [ ] **Step 5: Commit**

```bash
git add pwa
git commit -m "feat(pwa): Ältere Zeiten nachladen und Verlauf-Zeile im Verbindungsdialog (#250)"
```

---

### Task 7: Doku, Behauptungstests, Browser-Prüfung, PR

**Files:**
- Modify: `pwa/CLAUDE.md`, `src/CLAUDE.md`, `README.md`, `docs/known-limitations.md`, `tests/test_pwa_claude_md_claims.py`, `scripts/pwa_devserver.py`

**Interfaces:**
- Consumes: alles vorherige.

- [ ] **Step 1: Failing Behauptungstests** — in `tests/test_pwa_claude_md_claims.py`:

```python
def test_the_documented_window_steps_match_the_policy():
    documented = [int(n) for n in _claim(r"Stufen \*\*(\d+) / (\d+) / (\d+)\*\* Tage", "die Fensterstufen").groups()]
    found = re.search(r"WINDOW_STEPS = \[([\d, ]+)\]", _read("pwa/window-policy.js"))
    assert found, "Parser gescheitert: WINDOW_STEPS in pwa/window-policy.js"
    assert [int(n) for n in found.group(1).split(",")] == documented, (
        f"pwa/CLAUDE.md sagt {documented}, window-policy.js sagt {found.group(1)}")


def test_the_documented_window_budget_matches_the_desktop():
    documented = int(_claim(r"Budget von (\d+) KiB", "das Mengenlimit").group(1))
    found = re.search(r"^MAX_RESPONSE_ENTRY_BYTES = (\d+) \* 1024", _read("src/mobile_sync.py"), re.M)
    assert found, "Parser gescheitert: MAX_RESPONSE_ENTRY_BYTES in src/mobile_sync.py"
    assert int(found.group(1)) == documented, (
        f"pwa/CLAUDE.md sagt {documented} KiB, mobile_sync.py sagt {found.group(1)}")


def test_the_documented_window_cap_choices_match_the_desktop():
    documented = [int(n) for n in _claim(r"Obergrenze \*\*(\d+) / (\d+) / (\d+) / (\d+)\*\* Tage", "die Obergrenzen").groups()]
    found = re.search(r"^WINDOW_CAP_CHOICES = \(([\d, ]+)\)", _read("src/mobile_sync.py"), re.M)
    assert found, "Parser gescheitert: WINDOW_CAP_CHOICES in src/mobile_sync.py"
    assert [int(n) for n in found.group(1).split(",")] == documented
```

- [ ] **Step 2: Rot** — `pytest tests/test_pwa_claude_md_claims.py -q` → FAIL (Parser gescheitert).

- [ ] **Step 3: Doku schreiben**
  - `pwa/CLAUDE.md`: im Modul-Abschnitt `window-policy.js` ergänzen; neuer Abschnitt „Lesefenster“ mit: Protokollfelder (`window_days` Anfrage/Antwort, `window_max_days`), „Das Handy wünscht, der Desktop deckelt“, Stufen **90 / 180 / 365** Tage, Obergrenze **30 / 90 / 180 / 365** Tage (Standard 365), ein **Budget von 768 KiB** für die Einträge (gemessen: realistisch 96 KB auf dem Draht bei 365 Tagen, extrem 4 MB → gekürzt; PWA-Timeout 15 s), Verhalten bei fehlendem `window_max_days` (alter Desktop), Zurücksetzen; im Kompatibilitätsabschnitt den eingefrorenen Stand `sync-*-pre-250.json` nennen.
  - `src/CLAUDE.md`: im `mobile_sync`-/`mobile_routes`-Eintrag `grant_window`/`fit_window`, die Einstellung `mobile_window_max_days` und den Verweis auf `pwa/CLAUDE.md`.
  - `README.md` Zeile „Das Handy sieht die letzten 90 Tage“ → „Das Handy sieht standardmäßig die letzten 90 Tage und kann bis zur eingestellten Obergrenze (Einstellungen → Mobil, höchstens 365 Tage) ältere Zeiten nachladen“.
  - `docs/known-limitations.md` (Abschnitt „Handy-Erfassung“, Punkt „Das Handy kennt nur die letzten 90 Tage“): auf „bis zur Obergrenze, höchstens 365 Tage; darüber hinaus nur am Desktop“ ändern; die Datenmenge (Budget, Kürzung) nennen.

- [ ] **Step 4: Dev-Server und Browser** — `scripts/pwa_devserver.py` bekommt `--seed-days N` (Standard 0): legt für die letzten N Werktage je einen Eintrag (08:00–16:30, Pause 30, Kategorie „Projekt“) über `Storage.apply_merge` an. Prüfablauf (Playwright, Koppel-Link aus der Ausgabe, LAN-Adresse, nicht 8099/17654):
  1. `python -u scripts/pwa_devserver.py --port 8196 --api-port 17696 --seed-days 400`
  2. Koppeln; Wochenansicht auf eine Woche vor 90 Tagen blättern → Hinweis + „Ältere Zeiten laden (bis 180 Tage)“.
  3. Tippen → Abgleich; die Tage erscheinen; Verbindungsdialog zeigt „180 Tage (Desktop erlaubt bis 365)“ und „Auf 90 Tage zurücksetzen“.
  4. Zurücksetzen → die alten Wochen leeren sich wieder, ein unübertragener Alttag (vorher dort gespeichert) bleibt.
  5. Obergrenze serverseitig senken (`settings.set("mobile_window_max_days", 90)` im Dev-Server oder Datei `settings.json` im Datenordner) → nächster Abgleich: Hinweis „Der Desktop liefert höchstens 90 Tage …“, kein Knopf.
  6. Mengenlimit: `--seed-days 400 --seed-slots 50` → die Antwort wird gekürzt, Hinweis „… wegen der Datenmenge nur N Tage.“ (dafür bekommt `--seed-slots` ebenfalls einen Default 1).

- [ ] **Step 5: Gesamtlauf, Commit, PR**

Run: `pytest -q && ruff check . && (cd pwa && node --test)` → alles grün. `pyright` läuft nur in der CI.

```bash
git add -A docs README.md src pwa scripts tests
git commit -m "docs(pwa): Lesefenster dokumentiert, Behauptungen getestet, Dev-Server mit Beispieldaten (#250)"
git push -u origin HEAD
```

PR gegen `master`: Beschreibung nennt die Messwerte (Spec-Tabelle), das Budget, die Verträglichkeitstabelle; **Kein Release** (kein Label/Bump/CHANGELOG). Entscheidung zu #250 (Option B): ein **neues** Issue „PWA: Lesefenster dynamisch nachladen (Refs #250)“ anlegen, der PR schließt dieses; #250 danach auf die Restpunkte kürzen (volle Historie/Seiten, Delta, Randwochen-Summen).

---

## Self-Review

- **Spec-Abdeckung:** Obergrenze + Einstellung (T1, T4), Wunsch/Antwortfelder (T1–T3), Mengenlimit (T1, T2), Messwerte/Budget-Test (T2), PWA-Wunsch/Maximum (T5), Nachladen/Reset/Hinweise (T5–T6), Kompatibilität/eingefrorene Fixtures (T3), Doku/Claims (T7), Abgrenzung (nur Text). Lücken: keine.
- **Platzhalter:** keine; der Hinweis in T6 zu `windowRow` legt das Format über die Tests fest.
- **Typ-Konsistenz:** `grant_window(wish, cap)`, `fit_window(sizes, *, today, window_days, floor_days, budget)`, `build_response(…, window_days, window_max_days)`; PWA `olderState({ firstDay, today, windowDays, windowMax, wish })`, Meta `window_wish`/`window_max`, Antwortfeld `window_max_days` ↔ geparst als `window_max`. Konsistent über T1–T6.
- **Review Focus:** Zeilen 1–6 haben je einen Test (T1 absurde Wünsche und Einstellungen, T2 schwere Einträge und Timeout-Budget, T5 schrumpfendes Fenster mit unübertragenen Tagen, alter Desktop und Wochenrand, T4 ungültige Einstellung).
