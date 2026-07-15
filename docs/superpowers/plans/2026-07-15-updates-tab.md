# Updates-Tab + Toast/Banner-Routing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ein neuer 5. Settings-Tab „Updates" zeigt den Update-Status samt Changelog der neuen Version und macht die Check-Häufigkeit konfigurierbar; das bestehende Update-Banner wird zum Fallback für Plattformen ohne aktiven Toast-Kanal (Tray) — ist ein Tray aktiv, übernimmt ein einmaliger Toast.

**Architecture:** Neues stdlib-only Modul `src/changelog.py` (Fetch + Parsing des Changelog-Abschnitts einer Version) neben dem bestehenden `src/updater.py` (erweitert um konfigurierbare Check-Häufigkeit). `UpdateBanner` wird auf reine Anzeige-Logik verschlankt (`show_if_newer`); die Routing-Entscheidung Toast-vs-Banner lebt als reine, Tk-freie Funktion `_route_update_notification` direkt in `ui.py` (analog `_delete_action`), aufgerufen von einer dünnen `App`-Methode. Der neue Tab folgt exakt dem Muster der bestehenden `tab_*.py`-Dateien im Settings-Dialog-Paket.

**Tech Stack:** Python 3.10, Tkinter, pytest. Keine neuen Abhängigkeiten (nur stdlib `urllib`/`re`, wie `updater.py`).

## Global Constraints

- Changelog-Quelle: `CHANGELOG.md` wird zur Laufzeit vom GitHub-Tag `v{version}` per `raw.githubusercontent.com` geladen (stdlib `urllib`, kein Base64-Decoding).
- Banner-vs-Toast-Gate: entscheidet sich an `App._tray is not None` zum Zeitpunkt des Check-Ergebnisses — nicht an reiner Plattform-Fähigkeit (`tray.is_supported()`).
- Toast einmalig pro Version: neues Settings-Feld `update_toast_shown_version` verhindert wiederholtes Feuern durch den täglichen Hintergrund-Check.
- Updates-Tab prüft **live**, sobald er erstmals ausgewählt wird (`<<NotebookTabChanged>>`, nicht beim bloßen Öffnen des Settings-Dialogs — sonst würde jedes Öffnen der Einstellungen still die „gesehen"-Markierung setzen, Review-Fund W3) + manueller „Jetzt prüfen"-Button mit Re-Entry-Guard. Kein Release-Snapshot wird über Neustarts hinweg in Settings zwischengespeichert.
- Konfigurierbare Check-Häufigkeit: neues Settings-Feld `update_check_frequency` (`"daily"`/`"weekly"`/`"monthly"`/`"never"`, Default `"daily"` = heutiges Verhalten unverändert) steuert **nur** den Hintergrund-Check (Banner/Toast-Trigger), nicht den Tab-Live-Check.
- Findet der Live-Check im Updates-Tab eine neuere Version, wird das sofort als `dismissed_version` **und** `update_toast_shown_version` vermerkt (direkter Settings-Write, nicht an den Save-Button gekoppelt) — kein doppeltes Nerven durch Banner/Toast für eine im Tab bereits gesehene Version.
- `UpdateBanner.handle_check_result` (persistiert `last_update_check_at` UND entscheidet über Anzeige) wird aufgeteilt: Persistenz wandert zum Aufrufer in `ui.py`; `UpdateBanner` behält nur `show_if_newer(release)` (prüft `dismissed_version`, ruft `_show`).
- Alle neuen Settings-Keys sind gerätelokal — **nicht** in `SYNCED_SETTING_KEYS`.
- Toast und Banner sind pro Check-Ergebnis gegenseitig exklusiv (nie beide für denselben Fund in einem Durchlauf).

---

## Task 1: Changelog-Fetch + Parsing (`src/changelog.py`)

**Files:**
- Create: `src/changelog.py`
- Test: `tests/test_changelog.py`

**Interfaces:**
- Produces:
  - `extract_version_section(changelog_text: str, version: str) -> str | None`
  - `fetch_changelog_entry(repo: str, version: str, timeout: float = 5.0) -> str | None`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_changelog.py`:

```python
import socket
from io import BytesIO
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from src.changelog import extract_version_section, fetch_changelog_entry


CHANGELOG_FIXTURE = """# Changelog

## 1.18.0 — 2026-07-20

### Hinzugefügt
- **Updates-Tab**: Neuer Tab zeigt den Update-Status.

### Behoben
- Kleinere Fehler behoben.

## 1.17.0 — 2026-07-03

### Hinzugefügt
- **PDF-Export**: Bericht als PDF speichern.
"""

LAST_ENTRY_FIXTURE = """# Changelog

## 1.0.0 — 2026-01-01

### Hinzugefügt
- Erste Version.
"""


class TestExtractVersionSection:
    def test_middle_version_stops_at_next_heading(self):
        section = extract_version_section(CHANGELOG_FIXTURE, "1.18.0")
        assert section is not None
        assert section.startswith("## 1.18.0")
        assert "Updates-Tab" in section
        assert "PDF-Export" not in section

    def test_last_version_reads_to_end_of_file(self):
        section = extract_version_section(CHANGELOG_FIXTURE, "1.17.0")
        assert section is not None
        assert section.startswith("## 1.17.0")
        assert "PDF-Export" in section

    def test_single_entry_file_reads_to_end(self):
        section = extract_version_section(LAST_ENTRY_FIXTURE, "1.0.0")
        assert section is not None
        assert "Erste Version" in section

    def test_missing_version_returns_none(self):
        assert extract_version_section(CHANGELOG_FIXTURE, "9.9.9") is None

    def test_empty_text_returns_none(self):
        assert extract_version_section("", "1.0.0") is None


def _text_response(text: str) -> BytesIO:
    return BytesIO(text.encode("utf-8"))


class TestFetchChangelogEntry:
    def test_happy_path_returns_parsed_section(self):
        with patch("src.changelog.urlopen", return_value=_text_response(CHANGELOG_FIXTURE)):
            entry = fetch_changelog_entry("MargenHeld/Zeiterfassung", "1.18.0")
        assert entry is not None
        assert "Updates-Tab" in entry

    def test_url_error_returns_none(self):
        with patch("src.changelog.urlopen", side_effect=URLError("offline")):
            assert fetch_changelog_entry("any/repo", "1.0.0") is None

    def test_http_404_returns_none(self):
        err = HTTPError(url="x", code=404, msg="Not Found", hdrs=None, fp=None)
        with patch("src.changelog.urlopen", side_effect=err):
            assert fetch_changelog_entry("any/repo", "1.0.0") is None

    def test_socket_timeout_returns_none(self):
        with patch("src.changelog.urlopen", side_effect=socket.timeout()):
            assert fetch_changelog_entry("any/repo", "1.0.0") is None

    def test_invalid_utf8_returns_none(self):
        with patch("src.changelog.urlopen", return_value=BytesIO(b"\xff\xfe\x00\x00")):
            assert fetch_changelog_entry("any/repo", "1.0.0") is None

    def test_version_not_in_fetched_text_returns_none(self):
        with patch("src.changelog.urlopen", return_value=_text_response(CHANGELOG_FIXTURE)):
            assert fetch_changelog_entry("any/repo", "9.9.9") is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_changelog.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.changelog'`

- [ ] **Step 3: Write the implementation**

Create `src/changelog.py`:

```python
"""Changelog-Eintrag einer Release-Version laden (stdlib-only, Tk-frei).

CHANGELOG.md wird im Repo gepflegt und ist im gebauten Artefakt auf dem
Stand der installierten Version eingefroren — den Eintrag einer neueren,
noch nicht heruntergeladenen Version gibt es dort nicht. Dieses Modul lädt
die Datei zur Laufzeit vom GitHub-Tag der Zielversion und extrahiert nur
deren Abschnitt.
"""
import re
from urllib.error import URLError
from urllib.request import Request, urlopen

from src.version import VERSION

_RAW_URL = "https://raw.githubusercontent.com/{repo}/v{version}/CHANGELOG.md"
_VERSION_HEADING = re.compile(r"^##\s+(\S+)\s", re.MULTILINE)


def extract_version_section(changelog_text, version):
    """Extrahiert den Abschnitt zu `version` aus dem vollen CHANGELOG.md-Text:
    von der Zeile '## {version} ...' bis zur nächsten '## '-Überschrift oder
    zum Dateiende. None, wenn `version` nicht als Überschrift vorkommt."""
    headings = list(_VERSION_HEADING.finditer(changelog_text))
    for i, m in enumerate(headings):
        if m.group(1) != version:
            continue
        start = m.start()
        end = headings[i + 1].start() if i + 1 < len(headings) else len(changelog_text)
        return changelog_text[start:end].strip()
    return None


def fetch_changelog_entry(repo, version, timeout=5.0):
    """Lädt CHANGELOG.md vom Release-Tag `v{version}` und liefert den
    Abschnitt dieser Version. None bei jedem Fehler (Netzwerk, HTTP-Fehler,
    Decode-Fehler, Version nicht im Text gefunden) — nie eine Exception nach
    außen, analog updater.py::check_latest_release."""
    url = _RAW_URL.format(repo=repo, version=version)
    request = Request(url, headers={"User-Agent": f"Zeiterfassung/{VERSION}"})
    try:
        with urlopen(request, timeout=timeout) as response:
            text = response.read().decode("utf-8")
    except (URLError, OSError, UnicodeDecodeError):
        return None
    return extract_version_section(text, version)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_changelog.py -v`
Expected: PASS — 11 passed

- [ ] **Step 5: Commit**

```bash
git add src/changelog.py tests/test_changelog.py
git commit -m "$(cat <<'EOF'
feat(updates-tab): Changelog-Fetch + Parsing für eine Release-Version

Lädt CHANGELOG.md vom GitHub-Tag der Zielversion und extrahiert nur
deren Abschnitt (bis zur nächsten Versions-Überschrift). Fehlertolerant
wie updater.py::check_latest_release.
EOF
)"
```

---

## Task 2: `updater.py` erweitern (Check-Häufigkeit, Toast-Text, Repo-Konstante)

**Files:**
- Modify: `src/updater.py`
- Modify: `tests/test_updater.py`

**Interfaces:**
- Produces:
  - `REPO = "MargenHeld/Zeiterfassung"` (String-Konstante)
  - `FREQUENCY_OPTIONS: list[tuple[str, str]]` (Value/Label-Paare, Reihenfolge = Dropdown-Reihenfolge)
  - `frequency_for_label(label: str) -> str`
  - `should_check(last_check: str | None, frequency: str, today: date | None = None) -> bool` (ersetzt `should_check_today`)
  - `update_toast_text(release: Release) -> str`
- Removes: `should_check_today` (einziger Call-Site wird in Task 3 angepasst)

- [ ] **Step 1: Write the failing tests**

In `tests/test_updater.py`, Zeile 8 (Import) ändern von:

```python
from src.updater import Asset, check_latest_release, is_newer, pick_asset_url, should_check_today, today_iso
```

zu:

```python
from src.updater import (
    REPO, Asset, check_latest_release, frequency_for_label, is_newer,
    pick_asset_url, should_check, today_iso, update_toast_text,
)
```

Den bestehenden Block `class TestShouldCheckToday:` (Zeilen 35-49) komplett ersetzen durch:

```python
class TestShouldCheck:
    def test_empty_string_daily_returns_true(self):
        assert should_check("", "daily", today=date(2026, 4, 28)) is True

    def test_none_daily_returns_true(self):
        assert should_check(None, "daily", today=date(2026, 4, 28)) is True

    def test_daily_yesterday_returns_true(self):
        assert should_check("2026-04-27", "daily", today=date(2026, 4, 28)) is True

    def test_daily_today_returns_false(self):
        assert should_check("2026-04-28", "daily", today=date(2026, 4, 28)) is False

    def test_daily_invalid_string_returns_true(self):
        assert should_check("not-a-date", "daily", today=date(2026, 4, 28)) is True

    def test_weekly_six_days_ago_returns_false(self):
        assert should_check("2026-04-22", "weekly", today=date(2026, 4, 28)) is False

    def test_weekly_seven_days_ago_returns_true(self):
        assert should_check("2026-04-21", "weekly", today=date(2026, 4, 28)) is True

    def test_monthly_twenty_nine_days_ago_returns_false(self):
        assert should_check("2026-03-31", "monthly", today=date(2026, 4, 29)) is False

    def test_monthly_thirty_days_ago_returns_true(self):
        assert should_check("2026-03-30", "monthly", today=date(2026, 4, 29)) is True

    def test_never_returns_false_even_without_last_check(self):
        assert should_check("", "never", today=date(2026, 4, 28)) is False

    def test_never_returns_false_even_long_overdue(self):
        assert should_check("2020-01-01", "never", today=date(2026, 4, 28)) is False


class TestFrequencyForLabel:
    def test_known_label_maps_to_value(self):
        assert frequency_for_label("Wöchentlich") == "weekly"

    def test_unknown_label_falls_back_to_daily(self):
        assert frequency_for_label("Quatsch") == "daily"


class TestUpdateToastText:
    def test_contains_version_and_hint(self):
        from src.updater import Release
        release = Release(version="1.9.0", html_url="https://x", assets=())
        text = update_toast_text(release)
        assert "1.9.0" in text
        assert "Updates" in text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_updater.py -v`
Expected: FAIL — `ImportError: cannot import name 'REPO' from 'src.updater'`

- [ ] **Step 3: Write the implementation**

In `src/updater.py`, Zeile 30-44 (bestehende `should_check_today`-Funktion):

```python
def should_check_today(last_check: str | None, today: date | None = None) -> bool:
    """True, wenn der letzte Check vor dem heutigen Kalendertag lag.

    Drosselung pro Kalendertag (lokale Zeit), nicht pro 24-h-Fenster.
    Bei leerem oder ungültigem `last_check` wird ebenfalls True geliefert,
    damit ein einmal kaputter Wert nicht den Check für immer blockiert.
    """
    if not last_check:
        return True
    today = today or date.today()
    try:
        last = date.fromisoformat(last_check)
    except ValueError:
        return True
    return last < today
```

komplett ersetzen durch:

```python
REPO = "MargenHeld/Zeiterfassung"

FREQUENCY_OPTIONS: list[tuple[str, str]] = [
    ("daily", "Täglich"),
    ("weekly", "Wöchentlich"),
    ("monthly", "Monatlich"),
    ("never", "Nie"),
]

_FREQUENCY_INTERVAL_DAYS = {"daily": 1, "weekly": 7, "monthly": 30}


def frequency_for_label(label: str) -> str:
    """Mappt ein im Updates-Tab gewähltes Klartext-Label (z.B. 'Wöchentlich')
    zurück auf den internen Frequency-Value ('weekly'). Unbekanntes Label
    -> 'daily' (sicherer Default, analog holidays_de.code_for_state_label)."""
    return next((value for value, lbl in FREQUENCY_OPTIONS if lbl == label), "daily")


def should_check(last_check: str | None, frequency: str, today: date | None = None) -> bool:
    """True, wenn laut `frequency` ein Update-Check fällig ist.

    `frequency` in {"daily","weekly","monthly","never"} (siehe
    FREQUENCY_OPTIONS). "never" -> immer False. Sonst True, wenn
    `last_check` leer/ungültig ist ODER seit `last_check` mindestens das
    Intervall in Tagen vergangen ist (lokale Kalendertage).
    """
    if frequency == "never":
        return False
    interval_days = _FREQUENCY_INTERVAL_DAYS.get(frequency, 1)
    if not last_check:
        return True
    today = today or date.today()
    try:
        last = date.fromisoformat(last_check)
    except ValueError:
        return True
    return (today - last).days >= interval_days
```

Danach, direkt nach der `Release`-Dataclass (nach der Zeile `assets: tuple[Asset, ...]`), folgenden neuen Text-Helfer einfügen:

```python
def update_toast_text(release: "Release") -> str:
    """Deutscher Toast-Text für ein gefundenes Update (kein Klick-Handler —
    der Toast verweist auf den Updates-Tab)."""
    return (
        f"Version {release.version} verfügbar — "
        "Details unter Einstellungen → Updates."
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_updater.py -v`
Expected: PASS — 35 passed

- [ ] **Step 5: Commit**

```bash
git add src/updater.py tests/test_updater.py
git commit -m "$(cat <<'EOF'
feat(updates-tab): konfigurierbare Check-Häufigkeit in updater.py

should_check_today -> should_check(last_check, frequency) mit
daily/weekly/monthly/never. Neue REPO-Konstante (bisher in
background_tasks.py hart codiert) und update_toast_text-Helfer.
EOF
)"
```

---

## Task 3: `background_tasks.py::check_update` an neue Signatur anpassen

**Files:**
- Modify: `src/background_tasks.py`
- Modify: `tests/test_background_tasks.py`

**Interfaces:**
- Consumes: `src.updater.should_check(last_check, frequency, today=None)`, `src.updater.REPO` (Task 2).
- Produces: `BackgroundTaskRunner.check_update(on_result)` unverändertes äußeres Verhalten/Signatur, liest jetzt zusätzlich `settings.get("update_check_frequency")`.

- [ ] **Step 1: Write the failing test**

In `tests/test_background_tasks.py`, den bestehenden Test `test_check_update_skips_when_not_due` (Zeilen 67-78) ersetzen durch:

```python
def test_check_update_skips_when_not_due(monkeypatch):
    import src.background_tasks as bg
    monkeypatch.setattr(bg, "should_check", lambda last, freq: False)
    called = {"n": 0}
    monkeypatch.setattr(bg, "check_latest_release",
                        lambda repo: called.__setitem__("n", called["n"] + 1))
    r = _runner(settings={
        "last_update_check_at": None, "update_check_frequency": "daily",
    })
    r.check_update(on_result=lambda rel, newer: None)
    import time
    time.sleep(0.2)
    assert called["n"] == 0


def test_check_update_reads_frequency_from_settings(monkeypatch):
    import src.background_tasks as bg
    seen = {}

    def fake_should_check(last, freq):
        seen["frequency"] = freq
        return False

    monkeypatch.setattr(bg, "should_check", fake_should_check)
    r = _runner(settings={
        "last_update_check_at": None, "update_check_frequency": "weekly",
    })
    r.check_update(on_result=lambda rel, newer: None)
    import time
    time.sleep(0.2)
    assert seen["frequency"] == "weekly"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_background_tasks.py -v`
Expected: FAIL — `AttributeError: <module 'src.background_tasks'> does not have the attribute 'should_check'`

- [ ] **Step 3: Write the implementation**

In `src/background_tasks.py`, Zeile 16 ändern von:

```python
from src.updater import check_latest_release, is_newer, should_check_today
```

zu:

```python
from src.updater import REPO, check_latest_release, is_newer, should_check
```

Zeilen 113-128 (`check_update`-Methode, Header + Drosselungs-Check + `fn`):

```python
    def check_update(self, on_result):
        """Fragt 1x pro Kalendertag GitHub nach einer neueren Version. `is_newer`
        wird bereits im Worker ausgewertet, damit on_result(release, newer) im
        UI-Thread keine ungeschuetzte Logik mehr ausfuehrt. Fehler still."""
        if not should_check_today(self._settings.get("last_update_check_at")):
            return

        def fn():
            try:
                release = check_latest_release("MargenHeld/Zeiterfassung")
                if release is None:
                    return None
                return (release, is_newer(VERSION, release.version))
            except Exception:
                log.exception("Update-Check fehlgeschlagen")
                return None
```

ersetzen durch:

```python
    def check_update(self, on_result):
        """Fragt laut `update_check_frequency`-Setting nach einer neueren
        Version (Default: 1x pro Kalendertag). `is_newer` wird bereits im
        Worker ausgewertet, damit on_result(release, newer) im UI-Thread
        keine ungeschuetzte Logik mehr ausfuehrt. Fehler still."""
        frequency = self._settings.get("update_check_frequency")
        if not should_check(self._settings.get("last_update_check_at"), frequency):
            return

        def fn():
            try:
                release = check_latest_release(REPO)
                if release is None:
                    return None
                return (release, is_newer(VERSION, release.version))
            except Exception:
                log.exception("Update-Check fehlgeschlagen")
                return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_background_tasks.py -v`
Expected: PASS — 9 passed

- [ ] **Step 5: Commit**

```bash
git add src/background_tasks.py tests/test_background_tasks.py
git commit -m "$(cat <<'EOF'
feat(updates-tab): check_update liest konfigurierbare Frequenz

should_check_today -> should_check(last, frequency); Repo-String kommt
jetzt aus der updater.REPO-Konstante statt hart codiert.
EOF
)"
```

---

## Task 4: Settings-Defaults (`src/settings.py`)

**Files:**
- Modify: `src/settings.py:34-37`
- Test: `tests/test_settings.py`

**Interfaces:**
- Produces: `DEFAULTS["update_check_frequency"] == "daily"`, `DEFAULTS["update_toast_shown_version"] == ""`. Keine der beiden Keys in `SYNCED_SETTING_KEYS`.

- [ ] **Step 1: Write the failing test**

In `tests/test_settings.py`, direkt nach `test_send_reminder_defaults_present_and_device_local` (endet bei Zeile 765) einfügen:

```python
def test_update_tab_defaults_present_and_device_local():
    from src.settings import DEFAULTS, SYNCED_SETTING_KEYS
    assert DEFAULTS["update_check_frequency"] == "daily"
    assert DEFAULTS["update_toast_shown_version"] == ""
    assert "update_check_frequency" not in SYNCED_SETTING_KEYS
    assert "update_toast_shown_version" not in SYNCED_SETTING_KEYS
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_settings.py::test_update_tab_defaults_present_and_device_local -v`
Expected: FAIL — `KeyError: 'update_check_frequency'`

- [ ] **Step 3: Add the defaults**

In `src/settings.py`, Zeile 34-37 sind aktuell:

```python
    "state": "",
    "last_update_check_at": "",
    "dismissed_version": "",
    "default_start_mon": "08:00",
```

Ändern zu (neue Keys direkt nach `dismissed_version`, thematisch gruppiert — die Datei gruppiert nach Thema, nicht alphabetisch):

```python
    "state": "",
    "last_update_check_at": "",
    "dismissed_version": "",
    "update_check_frequency": "daily",
    "update_toast_shown_version": "",
    "default_start_mon": "08:00",
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_settings.py::test_update_tab_defaults_present_and_device_local -v`
Expected: PASS — 1 passed

Run: `pytest tests/test_settings.py -v`
Expected: alle Tests weiterhin PASS

- [ ] **Step 5: Commit**

```bash
git add src/settings.py tests/test_settings.py
git commit -m "$(cat <<'EOF'
feat(updates-tab): Settings-Defaults für Updates-Tab

Zwei neue gerätelokale Keys: update_check_frequency (Default "daily")
und update_toast_shown_version.
EOF
)"
```

---

## Task 5: `UpdateBanner` verschlanken (`show_if_newer`)

**Files:**
- Modify: `src/update_banner.py`
- Modify: `tests/test_update_banner.py`

**Interfaces:**
- Removes: `UpdateBanner.handle_check_result(release, newer)`
- Produces: `UpdateBanner.show_if_newer(release)` — prüft `dismissed_version`, ruft bei Bedarf `_show(release)`. Persistiert **nicht** mehr `last_update_check_at` (wandert zum Aufrufer, Task 6).

- [ ] **Step 1: Write the failing tests**

`tests/test_update_banner.py` komplett durch folgenden Inhalt ersetzen:

```python
"""UpdateBanner: Entscheidungslogik (show_if_newer) und Download-URL-Wahl
ohne Tk — _show wird gemockt, webbrowser/pick_asset_url gepatcht."""

from unittest.mock import MagicMock

import src.update_banner as ub
from src.update_banner import UpdateBanner


class _FakeSettings:
    def __init__(self, dismissed_version=None):
        self._d = {"dismissed_version": dismissed_version}

    def get(self, key, default=None):
        return self._d.get(key, default)

    def set(self, key, value):
        self._d[key] = value


def _release(version="1.2.0", html_url="https://example/r", assets=None):
    r = MagicMock()
    r.version = version
    r.html_url = html_url
    r.assets = assets if assets is not None else []
    return r


def _banner(settings):
    b = UpdateBanner(root=object(), settings=settings, get_anchor=lambda: object())
    b._show = MagicMock()
    return b


def test_show_if_newer_dismissed_version_does_not_show():
    b = _banner(_FakeSettings(dismissed_version="1.2.0"))
    b.show_if_newer(_release(version="1.2.0"))
    b._show.assert_not_called()


def test_show_if_newer_new_version_shows():
    b = _banner(_FakeSettings(dismissed_version="1.1.0"))
    rel = _release(version="1.2.0")
    b.show_if_newer(rel)
    b._show.assert_called_once_with(rel)


def test_open_download_uses_asset_url(monkeypatch):
    opened = []
    monkeypatch.setattr(ub.webbrowser, "open", lambda url: opened.append(url))
    monkeypatch.setattr(ub, "pick_asset_url",
                        lambda assets, sysname, ver: "https://asset/dl")
    b = UpdateBanner(root=object(), settings=_FakeSettings(),
                     get_anchor=lambda: object())
    b._open_download(_release())
    assert opened == ["https://asset/dl"]


def test_open_download_falls_back_to_html_url(monkeypatch):
    opened = []
    monkeypatch.setattr(ub.webbrowser, "open", lambda url: opened.append(url))
    monkeypatch.setattr(ub, "pick_asset_url", lambda assets, sysname, ver: None)
    b = UpdateBanner(root=object(), settings=_FakeSettings(),
                     get_anchor=lambda: object())
    b._open_download(_release(html_url="https://example/r"))
    assert opened == ["https://example/r"]


def test_show_triggers_resize(monkeypatch):
    # Banner einblenden muss die Fenstergeometrie neu pinnen, sonst wächst das
    # fixe Fenster (resizable(False, False)) nicht und der zuletzt gepackte
    # Footer (Summen-Zeile) wird abgeschnitten (#92).
    monkeypatch.setattr(ub.tk, "Frame", lambda *a, **k: MagicMock())
    monkeypatch.setattr(ub.tk, "Label", lambda *a, **k: MagicMock())
    monkeypatch.setattr(ub, "label_button", lambda *a, **k: MagicMock())
    monkeypatch.setattr(ub, "attach_tooltip", lambda *a, **k: None)
    resized = []
    b = UpdateBanner(root=object(), settings=_FakeSettings(),
                     get_anchor=lambda: object(),
                     on_resize=lambda: resized.append(True))
    b._show(_release())
    assert resized == [True]


def test_dismiss_triggers_resize():
    # Banner ausblenden muss die Geometrie zurückpinnen, damit das Fenster
    # wieder auf die Höhe ohne Banner schrumpft (Gegenstück zu _show).
    resized = []
    b = UpdateBanner(root=object(), settings=_FakeSettings(),
                     get_anchor=lambda: object(),
                     on_resize=lambda: resized.append(True))
    b._banner = MagicMock()
    b._dismiss("1.2.0")
    assert b._banner is None
    assert resized == [True]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_update_banner.py -v`
Expected: FAIL — `AttributeError: 'UpdateBanner' object has no attribute 'show_if_newer'`

- [ ] **Step 3: Write the implementation**

In `src/update_banner.py`, Zeile 14 ändern von:

```python
from src.updater import pick_asset_url, today_iso
```

zu:

```python
from src.updater import pick_asset_url
```

(`today_iso` wird hier nicht mehr gebraucht — die Persistenz wandert nach `ui.py`.)

Zeilen 29-39 (`handle_check_result`) komplett ersetzen durch:

```python
    def show_if_newer(self, release):
        """Zeigt den Banner, wenn `release` noch nicht per `dismissed_version`
        ausgeblendet wurde. Der Aufrufer (ui.py::App._on_update_check_result)
        hat bereits geprüft, dass `release` neuer als die installierte
        Version ist, und routet nur hierher, wenn kein aktiver Toast-Kanal
        verfügbar ist."""
        if release.version == self._settings.get("dismissed_version"):
            return
        self._show(release)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_update_banner.py -v`
Expected: PASS — 6 passed

- [ ] **Step 5: Commit**

```bash
git add src/update_banner.py tests/test_update_banner.py
git commit -m "$(cat <<'EOF'
refactor(updates-tab): UpdateBanner auf show_if_newer verschlankt

handle_check_result trug bisher zwei Zuständigkeiten (last_update_check_at
persistieren + Anzeige-Entscheidung). Die Persistenz wandert in die neue
Toast/Banner-Routing-Stelle in ui.py (Task 6) — UpdateBanner bleibt rein
für die Banner-Anzeige zuständig.
EOF
)"
```

---

## Task 6: Toast/Banner-Routing (`src/ui.py`)

**Files:**
- Modify: `src/ui.py`
- Test: `tests/test_ui_update_routing.py` (neu)

**Interfaces:**
- Consumes: `src.updater.today_iso`, `src.updater.update_toast_text` (Task 2); `UpdateBanner.show_if_newer` (Task 5).
- Produces: modulweite Funktion `_route_update_notification(release, tray_active, toast_shown_version) -> tuple[str, str | None]` (Rückgabe `("toast", text)` / `("banner", None)` / `("none", None)`); `App._on_update_check_result(release, newer)`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_ui_update_routing.py`:

```python
"""Reine Routing-Entscheidung für Update-Benachrichtigungen (Toast vs.
Banner vs. schon gesehen) — Tk-frei testbar wie _delete_action — plus die
Verdrahtung App._on_update_check_result gegen ein Duck-Typed-App-Double
(kein echtes Tk nötig, die Methode greift nur auf self.settings/self._tray/
self._update_banner zu)."""
from unittest.mock import MagicMock

from src.ui import App, _route_update_notification


class _Rel:
    def __init__(self, version):
        self.version = version


class _FakeSettings:
    def __init__(self, data):
        self._data = data

    def get(self, key):
        return self._data.get(key, "")

    def set(self, key, value):
        self._data[key] = value


class _FakeApp:
    """Duck-Typed Stand-in für App — trägt nur die drei Attribute, die
    _on_update_check_result liest/schreibt."""
    def __init__(self, tray, settings_data):
        self.settings = _FakeSettings(settings_data)
        self._tray = tray
        self._update_banner = MagicMock()


class _FakeTray:
    def __init__(self):
        self.messages = []

    def notify(self, message, title="Zeiterfassung"):
        self.messages.append(message)


def test_tray_active_and_not_yet_shown_fires_toast():
    action, text = _route_update_notification(_Rel("1.9.0"), True, "")
    assert action == "toast"
    assert "1.9.0" in text


def test_tray_active_and_already_shown_does_nothing():
    action, text = _route_update_notification(_Rel("1.9.0"), True, "1.9.0")
    assert action == "none"
    assert text is None


def test_tray_active_different_version_already_shown_fires_toast():
    action, text = _route_update_notification(_Rel("1.9.0"), True, "1.8.0")
    assert action == "toast"


def test_no_tray_routes_to_banner():
    action, text = _route_update_notification(_Rel("1.9.0"), False, "")
    assert action == "banner"
    assert text is None


def test_no_tray_routes_to_banner_even_if_already_toast_shown():
    # Toast-Tracking ist unabhängig vom Banner-eigenen dismissed_version.
    action, text = _route_update_notification(_Rel("1.9.0"), False, "1.9.0")
    assert action == "banner"


def test_on_update_check_result_persists_check_date_even_when_not_newer(monkeypatch):
    import src.ui as ui_module
    monkeypatch.setattr(ui_module, "today_iso", lambda: "2026-07-15")
    fake = _FakeApp(tray=None, settings_data={})
    App._on_update_check_result(fake, _Rel("1.9.0"), False)
    assert fake.settings.get("last_update_check_at") == "2026-07-15"
    fake._update_banner.show_if_newer.assert_not_called()


def test_on_update_check_result_tray_active_fires_toast_and_persists(monkeypatch):
    import src.ui as ui_module
    monkeypatch.setattr(ui_module, "today_iso", lambda: "2026-07-15")
    tray = _FakeTray()
    fake = _FakeApp(tray=tray, settings_data={"update_toast_shown_version": ""})
    App._on_update_check_result(fake, _Rel("1.9.0"), True)
    assert len(tray.messages) == 1 and "1.9.0" in tray.messages[0]
    assert fake.settings.get("update_toast_shown_version") == "1.9.0"
    fake._update_banner.show_if_newer.assert_not_called()


def test_on_update_check_result_no_tray_routes_to_banner(monkeypatch):
    import src.ui as ui_module
    monkeypatch.setattr(ui_module, "today_iso", lambda: "2026-07-15")
    fake = _FakeApp(tray=None, settings_data={"update_toast_shown_version": ""})
    rel = _Rel("1.9.0")
    App._on_update_check_result(fake, rel, True)
    fake._update_banner.show_if_newer.assert_called_once_with(rel)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_ui_update_routing.py -v`
Expected: FAIL — `ImportError: cannot import name '_route_update_notification' from 'src.ui'`

- [ ] **Step 3: Write the implementation**

In `src/ui.py`, Zeile 22 ändern von:

```python
from src.update_banner import UpdateBanner
```

zu:

```python
from src.update_banner import UpdateBanner
from src.updater import today_iso, update_toast_text
```

Direkt nach `_delete_action` (endet aktuell bei `return "save", keep`, vor `class App:`) folgende neue Funktion einfügen:

```python
def _route_update_notification(release, tray_active, toast_shown_version):
    """Entscheidet, wie auf ein 'neuere Version gefunden'-Ergebnis reagiert
    wird. Liefert (action, text): action in {'toast','banner','none'}.

    'toast' nur, wenn tray_active UND release.version noch nicht in
    toast_shown_version steht (sonst 'none' — schon benachrichtigt).
    'banner' immer, wenn kein Tray aktiv ist (das Banner regelt sein eigenes
    dismissed_version selbst, s. UpdateBanner.show_if_newer)."""
    if tray_active:
        if release.version == toast_shown_version:
            return "none", None
        return "toast", update_toast_text(release)
    return "banner", None
```

In der `App`-Klasse, Zeile 146 ändern von:

```python
        self._bg.check_update(on_result=self._update_banner.handle_check_result)
```

zu:

```python
        self._bg.check_update(on_result=self._on_update_check_result)
```

Und direkt nach `_apply_send_reminder_setting` (vor `def _restore_from_tray`) folgende neue Methode einfügen:

```python
    def _on_update_check_result(self, release, newer):
        """`on_result` von `BackgroundTaskRunner.check_update`. Persistiert
        den Check-Zeitpunkt unabhängig vom Ergebnis; ist eine neuere Version
        da, routet `_route_update_notification` zwischen Toast (aktiver
        Tray) und Banner (kein Tray)."""
        self.settings.set("last_update_check_at", today_iso())
        if not newer:
            return
        action, text = _route_update_notification(
            release, self._tray is not None,
            self.settings.get("update_toast_shown_version"))
        if action == "toast":
            self._tray.notify(text)
            self.settings.set("update_toast_shown_version", release.version)
        elif action == "banner":
            self._update_banner.show_if_newer(release)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_ui_update_routing.py -v`
Expected: PASS — 8 passed

Run: `python -c "import src.ui"`
Expected: kein Output, Exit-Code 0

Run: `ruff check src/ui.py`
Expected: `All checks passed!`

- [ ] **Step 5: Commit**

```bash
git add src/ui.py tests/test_ui_update_routing.py
git commit -m "$(cat <<'EOF'
feat(updates-tab): Toast/Banner-Routing für Update-Benachrichtigungen

_route_update_notification (pur, Tk-frei) entscheidet je nach aktivem
Tray zwischen Toast und Banner; App._on_update_check_result verdrahtet
das mit dem bestehenden check_update-Ergebnis und übernimmt die
last_update_check_at-Persistenz von UpdateBanner.
EOF
)"
```

---

## Task 7: Settings-Dialog-UI (neuer Tab „Updates")

**Files:**
- Create: `src/dialogs/settings_dialog/tab_updates.py`
- Modify: `src/dialogs/settings_dialog/dialog.py`

**Interfaces:**
- Consumes: `src.changelog.fetch_changelog_entry` (Task 1); `src.updater.{REPO, FREQUENCY_OPTIONS, check_latest_release, is_newer, pick_asset_url}` (Task 2, teils bestehend); `src.updater.frequency_for_label` (Task 2, nur in `dialog.py` gebraucht — **nicht** in `tab_updates.py` importieren, dort ungenutzt); `src.version.VERSION`.
- Produces: `UpdatesTab(frame, settings, runner)` exponiert `.frame`, `.frequency_var` (`tk.StringVar`, Werte aus `FREQUENCY_OPTIONS`-Labels) für `save_settings`, und `.on_tab_selected()` (löst den Live-Check aus, idempotent pro Dialog-Öffnung).

Kein automatisierter Test (Tk-Widget-Code, Projekt-Konvention — wie die anderen `tab_*.py`). Verifikation über Import-Check + `ruff` + vollen `pytest`-Lauf.

**Wichtig — Lazy-Check statt Eager-Check:** `dialog.py` baut alle Tabs beim
Öffnen des Dialogs sofort auf (`WorkTab`/`MailTab`/`GoogleTab`/`AppTab` laufen
alle in `__init__`, unabhängig davon, welcher Tab sichtbar ist). Würde
`UpdatesTab.__init__` selbst sofort `_check_now()` aufrufen, liefe der
Live-Check — und damit das sofortige „gesehen"-Markieren
(`dismissed_version`/`update_toast_shown_version`) — bei **jedem** Öffnen der
Einstellungen, auch wenn der Nutzer den Updates-Tab nie ansieht. Das würde
Banner/Toast für die aktuell neueste Version stillschweigend unterdrücken,
ohne dass der Nutzer je etwas gesehen hat. Deshalb: `UpdatesTab` baut nur die
UI in `__init__` auf und ruft **nicht** selbst `_check_now()`; `dialog.py`
löst den Check erst über `<<NotebookTabChanged>>` aus, wenn der Updates-Tab
tatsächlich ausgewählt wird (Schritt 2).

- [ ] **Step 1: `UpdatesTab` erstellen**

Create `src/dialogs/settings_dialog/tab_updates.py`:

```python
"""Tab „Updates": Update-Status, Changelog der neuen Version, Check-Häufigkeit.

Prüft live gegen GitHub, sobald der Tab erstmals ausgewählt wird (umgeht die
Tagesdrosselung des Hintergrund-Checks — explizite Nutzeraktion; siehe
`on_tab_selected`, aufgerufen von dialog.py's `<<NotebookTabChanged>>`-Bindung,
NICHT automatisch beim Dialog-Öffnen). Findet der Live-Check eine neuere
Version, gilt sie sofort als „gesehen" (dismissed_version UND
update_toast_shown_version werden direkt gesetzt, unabhängig vom
Save-Button) — kein doppeltes Nerven durch Banner/Toast danach.
"""

import platform
import tkinter as tk
import webbrowser

from src.changelog import fetch_changelog_entry
from src.dialogs.settings_dialog._shared import label
from src.theme import (
    BG, FONT, TEXT, TEXT_MUTED,
    dark_combo, dark_text, primary_button, secondary_button,
    set_button_text, set_primary_button_enabled,
)
from src.updater import (
    FREQUENCY_OPTIONS, REPO, check_latest_release, is_newer, pick_asset_url,
)
from src.version import VERSION


class UpdatesTab:
    """Baut den Updates-Tab; exponiert `frequency_var` für save_settings und
    `on_tab_selected()` für die Lazy-Check-Bindung in dialog.py."""

    def __init__(self, frame, settings, runner):
        self.frame = frame
        self._settings = settings
        self._runner = runner
        self._latest_release = None
        self._checked = False    # verhindert Mehrfach-Check bei Tab-Rückkehr
        self._checking = False   # Re-Entry-Guard, solange ein Check läuft

        label(frame, f"Installierte Version: {VERSION}", row=0)

        self._status_label = tk.Label(
            frame, text="", font=FONT, bg=BG, fg=TEXT_MUTED,
        )
        self._status_label.grid(row=1, column=0, columnspan=2, padx=10, pady=4, sticky="w")

        btn_row = tk.Frame(frame, bg=BG)
        btn_row.grid(row=2, column=0, columnspan=2, padx=10, pady=4, sticky="w")
        self._check_btn = primary_button(btn_row, "Jetzt prüfen", self._check_now)
        self._check_btn.pack(side=tk.LEFT)
        self._download_btn = secondary_button(btn_row, "Download", lambda: None)
        # Wird erst gepackt, wenn eine neuere Version gefunden wird (Schritt in on_done).

        freq_row = tk.Frame(frame, bg=BG)
        freq_row.grid(row=3, column=0, columnspan=2, padx=10, pady=(12, 4), sticky="w")
        tk.Label(
            freq_row, text="Automatisch prüfen:", font=FONT, bg=BG, fg=TEXT,
        ).pack(side=tk.LEFT, padx=(0, 8))
        current_frequency = settings.get("update_check_frequency")
        current_label = next(
            (lbl for value, lbl in FREQUENCY_OPTIONS if value == current_frequency),
            FREQUENCY_OPTIONS[0][1],
        )
        self.frequency_var = tk.StringVar(value=current_label)
        dark_combo(
            freq_row, self.frequency_var,
            [lbl for _, lbl in FREQUENCY_OPTIONS], width=14,
        ).pack(side=tk.LEFT)

        tk.Label(
            frame, text="Changelog:", font=FONT, bg=BG, fg=TEXT,
        ).grid(row=4, column=0, padx=10, pady=(12, 4), sticky="nw")
        self._changelog_text = dark_text(frame, 50, 12)
        self._changelog_text.grid(row=5, column=0, columnspan=2, padx=10, pady=4)
        self._changelog_text.config(state="disabled")

    def on_tab_selected(self):
        """Von dialog.py bei `<<NotebookTabChanged>>` aufgerufen, wenn dieser
        Tab sichtbar wird. Löst den Live-Check nur beim ERSTEN Sichtbarwerden
        pro Dialog-Öffnung aus (kein Re-Check bei jedem Zurück-Klicken)."""
        if self._checked:
            return
        self._checked = True
        self._check_now()

    def _finish_checking(self):
        self._checking = False
        set_primary_button_enabled(self._check_btn, True)
        set_button_text(self._check_btn, "Jetzt prüfen")

    def _set_changelog(self, text):
        self._changelog_text.config(state="normal")
        self._changelog_text.delete("1.0", "end")
        self._changelog_text.insert("1.0", text)
        self._changelog_text.config(state="disabled")

    def _check_now(self):
        if self._checking:
            return
        self._checking = True
        set_primary_button_enabled(self._check_btn, False)
        set_button_text(self._check_btn, "Prüfe…")
        self._status_label.config(text="Prüfe…")
        self._download_btn.pack_forget()
        self._set_changelog("")

        def fn():
            return check_latest_release(REPO)

        def on_done(release):
            if not self.frame.winfo_exists():
                return
            if release is None:
                self._finish_checking()
                self._status_label.config(text="Prüfung fehlgeschlagen — keine Verbindung?")
                return
            if not is_newer(VERSION, release.version):
                self._finish_checking()
                self._status_label.config(text=f"Du hast die aktuelle Version ({VERSION}).")
                return
            self._latest_release = release
            self._status_label.config(text=f"Version {release.version} verfügbar")
            self._download_btn.configure(command=lambda: self._open_download(release))
            self._download_btn.pack(side=tk.LEFT, padx=(8, 0))
            self._settings.set_many({
                "dismissed_version": release.version,
                "update_toast_shown_version": release.version,
            })
            self._fetch_changelog(release.version)
            # _checking bleibt True, bis der Changelog-Fetch (unten) fertig ist —
            # verhindert überlappende "Jetzt prüfen"-Klicks während der zweiten,
            # verketteten Netzwerk-Anfrage.

        self._runner.run(fn, on_done)

    def _fetch_changelog(self, version):
        def fn():
            return fetch_changelog_entry(REPO, version)

        def on_done(text):
            if not self.frame.winfo_exists():
                return
            self._finish_checking()
            self._set_changelog(text or "Changelog konnte nicht geladen werden.")

        self._runner.run(fn, on_done)

    def _open_download(self, release):
        url = pick_asset_url(
            release.assets, platform.system(), release.version,
        ) or release.html_url
        webbrowser.open(url)
```

- [ ] **Step 2: Tab in `dialog.py` registrieren + Lazy-Check verdrahten**

In `src/dialogs/settings_dialog/dialog.py`, Zeile 20-24 (Import-Block) ändern von:

```python
from src.weekly_limit import format_limit_warnings, period_scan_needed, scan_period_for_warnings
from src.dialogs.settings_dialog.tab_app import AppTab
from src.dialogs.settings_dialog.tab_google import GoogleTab
from src.dialogs.settings_dialog.tab_mail import MailTab
from src.dialogs.settings_dialog.tab_work import WorkTab
```

zu:

```python
from src.updater import frequency_for_label
from src.weekly_limit import format_limit_warnings, period_scan_needed, scan_period_for_warnings
from src.dialogs.settings_dialog.tab_app import AppTab
from src.dialogs.settings_dialog.tab_google import GoogleTab
from src.dialogs.settings_dialog.tab_mail import MailTab
from src.dialogs.settings_dialog.tab_updates import UpdatesTab
from src.dialogs.settings_dialog.tab_work import WorkTab
```

Zeile 50-57 (Tab-Frames + Registrierung) ändern von:

```python
    tab_work = tk.Frame(notebook, bg=BG)
    tab_mail = tk.Frame(notebook, bg=BG)
    tab_google = tk.Frame(notebook, bg=BG)
    tab_app = tk.Frame(notebook, bg=BG)
    notebook.add(tab_work, text="Arbeitszeit")
    notebook.add(tab_mail, text="Bericht & Mail")
    notebook.add(tab_google, text="Google")
    notebook.add(tab_app, text="App")
```

zu:

```python
    tab_work = tk.Frame(notebook, bg=BG)
    tab_mail = tk.Frame(notebook, bg=BG)
    tab_google = tk.Frame(notebook, bg=BG)
    tab_app = tk.Frame(notebook, bg=BG)
    tab_updates = tk.Frame(notebook, bg=BG)
    notebook.add(tab_work, text="Arbeitszeit")
    notebook.add(tab_mail, text="Bericht & Mail")
    notebook.add(tab_google, text="Google")
    notebook.add(tab_app, text="App")
    notebook.add(tab_updates, text="Updates")
```

Zeile 70-74 ändern von:

```python
    # ===================== Tab: App =====================
    app = AppTab(tab_app, settings)

    # ===================== Speichern / Buttons =====================
    tabs = {"work": work.frame, "mail": mail.frame, "google": google.frame, "app": app.frame}
```

zu (Achtung: die Tab-Instanz **nicht** `updates` nennen — `save_settings` benutzt weiter unten bereits einen lokalen Namen `updates` für das Settings-Dict; `updates_tab` vermeidet die Namenskollision):

```python
    # ===================== Tab: App =====================
    app = AppTab(tab_app, settings)

    # ===================== Tab: Updates =====================
    updates_tab = UpdatesTab(tab_updates, settings, runner)

    # Live-Check erst, wenn der Tab tatsächlich sichtbar wird (nicht beim
    # bloßen Dialog-Öffnen) — sonst würde jedes Öffnen der Einstellungen
    # still die "gesehen"-Markierung setzen, ohne dass der Nutzer den Tab
    # je angesehen hat.
    def _on_tab_changed(_event):
        if notebook.select() == str(tab_updates):
            updates_tab.on_tab_selected()
    notebook.bind("<<NotebookTabChanged>>", _on_tab_changed)

    # ===================== Speichern / Buttons =====================
    tabs = {
        "work": work.frame, "mail": mail.frame, "google": google.frame,
        "app": app.frame, "updates": updates_tab.frame,
    }
```

Zeile 163-166 (in `save_settings`, im `updates`-Dict) ändern von:

```python
            "send_reminder_enabled": app.send_reminder_enabled_var.get(),
            "send_reminder_day": int(app.send_reminder_day_var.get()),
            "send_reminder_time": app.send_reminder_time_var.get(),
            "ui_scale": new_scale,
```

zu:

```python
            "send_reminder_enabled": app.send_reminder_enabled_var.get(),
            "send_reminder_day": int(app.send_reminder_day_var.get()),
            "send_reminder_time": app.send_reminder_time_var.get(),
            "update_check_frequency": frequency_for_label(updates_tab.frequency_var.get()),
            "ui_scale": new_scale,
```

- [ ] **Step 3: Import-Check + Lint + voller Testlauf**

Run: `python -c "import src.dialogs.settings_dialog.tab_updates; import src.dialogs.settings_dialog.dialog"`
Expected: kein Output, Exit-Code 0

Run: `ruff check src/dialogs/settings_dialog/tab_updates.py src/dialogs/settings_dialog/dialog.py`
Expected: `All checks passed!` (achte insbesondere auf F401 — `tab_updates.py` importiert bewusst **kein** `FONT_SMALL` und **kein** `frequency_for_label`, beide werden dort nicht verwendet)

Run: `pytest -q`
Expected: alle Tests grün (keine Regressionen)

- [ ] **Step 4: Commit**

```bash
git add src/dialogs/settings_dialog/tab_updates.py src/dialogs/settings_dialog/dialog.py
git commit -m "$(cat <<'EOF'
feat(updates-tab): neuer Settings-Tab "Updates"

Live-Check erst beim tatsächlichen Auswählen des Tabs (nicht beim bloßen
Öffnen der Einstellungen) + "Jetzt prüfen"-Button mit Re-Entry-Guard +
Frequenz-Dropdown. Findet der Check eine neuere Version, zeigt der Tab
den geladenen Changelog-Abschnitt und markiert die Version sofort als
gesehen (dismissed_version + update_toast_shown_version in einem
Schreibvorgang), damit Banner/Toast danach nicht erneut für dieselbe
Version feuern.
EOF
)"
```

- [ ] **Step 5: Manueller Smoke-Test**

App starten: `python -m src.main`

1. Einstellungen öffnen → neuer Tab „Updates" ganz rechts sichtbar, aber
   noch **leer** (kein „Prüfe…", keine Statuszeile) — der Live-Check läuft
   bewusst noch nicht, solange der Tab nicht angeklickt wurde. Auf einen
   anderen Tab (z.B. „Arbeitszeit") wechseln, kurz warten, `settings.json`
   inspizieren → `dismissed_version`/`update_toast_shown_version` dürfen
   sich **nicht** geändert haben (Beleg für den Lazy-Fix aus dem Review).
2. Jetzt „Updates" anklicken → zeigt kurz „Prüfe…", danach entweder „Du hast
   die aktuelle Version (X.Y.Z)." oder eine neuere Version mit
   Download-Button + Changelog-Text.
3. Auf „Arbeitszeit" und zurück zu „Updates" wechseln → **kein** erneuter
   Netzwerk-Check (Statuszeile bleibt stehen, kein zweites „Prüfe…").
4. „Jetzt prüfen" mehrfach schnell hintereinander klicken → nur ein Ablauf
   läuft (Button bleibt bis zum Ende durchgängig deaktiviert, kein
   überlappender zweiter Lauf).
5. Frequenz-Dropdown auf „Wöchentlich" stellen, Speichern, Einstellungen neu
   öffnen → Auswahl bleibt erhalten.
6. Wurde in Schritt 2 eine neuere Version gefunden: Einstellungen schließen,
   App-Neustart erzwingen (oder `_apply_reminder_setting`-Pfad antriggern) —
   der tägliche Hintergrund-Check darf für **dieselbe** Version **keinen**
   Banner/Toast mehr zeigen (Beleg für Entscheidung 6 „gesehen = keine
   erneute Nachricht").
7. Für den Chicken-and-egg-Test (siehe Spec): in `src/version.py` `VERSION`
   testweise unterhalb einer echten alten Tag-Version setzen (z.B.
   `"1.0.0"`), App starten, Updates-Tab anklicken → sollte den echten
   Changelog-Abschnitt der jeweils neuesten echten Version laden und
   anzeigen. Änderung an `version.py` danach wieder rückgängig machen, nicht
   committen.

---

## Task 8: Dokumentation (`CLAUDE.md` / `src/CLAUDE.md`)

**Files:**
- Modify: `CLAUDE.md:306`
- Modify: `src/CLAUDE.md:86-91`, `:188-191`

Kein Test — reine Doku-Pflege, aber von beiden `CLAUDE.md`-Dateien explizit
verlangt ("Diese Datei pflegen").

- [ ] **Step 1: Root-`CLAUDE.md` Modulliste ergänzen**

`CLAUDE.md:306` ist aktuell:

```
- `src/updater.py` — GitHub-Releases-Check (stdlib-only, gedrosselt 1×/Tag)
```

Ändern zu:

```
- `src/updater.py` — GitHub-Releases-Check (stdlib-only, Check-Häufigkeit über `update_check_frequency` konfigurierbar, Default 1×/Tag); `src/changelog.py` — lädt und parst den Changelog-Abschnitt einer Release-Version vom GitHub-Tag (stdlib-only)
```

- [ ] **Step 2: `src/CLAUDE.md` UpdateBanner-Abschnitt aktualisieren**

`src/CLAUDE.md:86-91` ist aktuell:

```
### UpdateBanner (`update_banner.py`)
Banner über dem Kalender (anzeigen/Download/ausblenden). `handle_check_result(release, newer)`
ist das `on_result` von `BackgroundTaskRunner.check_update`. Pack-Anker **lazy** über
`get_anchor=lambda: App._renderer.grid_container` (Grid existiert erst nach dem Build).
`on_resize` (= `App._renderer.repin_geometry`) wird in `_show`/`_dismiss` aufgerufen, damit
das fixe Fenster auf die geänderte Banner-Höhe nachzieht (sonst Footer abgeschnitten, #92).
```

Ändern zu:

```
### UpdateBanner (`update_banner.py`)
Banner über dem Kalender (anzeigen/Download/ausblenden) — **Fallback-Kanal**, nur wenn
kein Tray läuft. `show_if_newer(release)` prüft `dismissed_version` und zeigt ggf. den
Banner; `App._on_update_check_result` (das eigentliche `on_result` von
`BackgroundTaskRunner.check_update`) routet dorthin nur, wenn `App._tray is None` —
läuft ein Tray, feuert stattdessen ein Toast (`_route_update_notification` in `ui.py`,
`update_toast_shown_version` verhindert Wiederholung). Pack-Anker **lazy** über
`get_anchor=lambda: App._renderer.grid_container` (Grid existiert erst nach dem Build).
`on_resize` (= `App._renderer.repin_geometry`) wird in `_show`/`_dismiss` aufgerufen, damit
das fixe Fenster auf die geänderte Banner-Höhe nachzieht (sonst Footer abgeschnitten, #92).
```

- [ ] **Step 3: `src/CLAUDE.md` Tab-Liste ergänzen**

`src/CLAUDE.md:188-191` ist aktuell:

```
`settings_dialog/` (Paket, Audit H4: `dialog.py` trägt Chrome + zentrales,
ablaufidentisches `save_settings`; je Tab eine Klasse in `tab_work/`
`tab_mail`/`tab_google`/`tab_app`.py, die ihre Tk-Variablen als Attribute
für `save_settings` exponiert; `oauth_task.py` = H5-OAuth-Toggle-Builder;
```

Ändern zu:

```
`settings_dialog/` (Paket, Audit H4: `dialog.py` trägt Chrome + zentrales,
ablaufidentisches `save_settings`; je Tab eine Klasse in `tab_work/`
`tab_mail`/`tab_google`/`tab_app`/`tab_updates`.py, die ihre Tk-Variablen als
Attribute für `save_settings` exponiert (`tab_updates` zusätzlich mit eigenem
Live-Check via `runner`, analog Google-Tab); `oauth_task.py` = H5-OAuth-Toggle-Builder;
```

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md src/CLAUDE.md
git commit -m "$(cat <<'EOF'
docs: Updates-Tab + Toast/Banner-Routing in Architektur-Docs aufnehmen

EOF
)"
```
