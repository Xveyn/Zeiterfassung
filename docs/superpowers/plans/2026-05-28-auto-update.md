# Auto-Update Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Klick auf den "Download"-Button im Update-Banner lädt das neue Release herunter, verifiziert SHA256, und startet den Installer (Windows: Inno Setup silent / Linux: AppImage-Replace) statt nur die Release-Seite im Browser zu öffnen. macOS bleibt beim Browser-Verhalten.

**Architektur:** Trennung in pure Logik (`src/update/`, ohne Tk) und UI-Schicht (`src/dialogs/update_dialog.py`). Bestehendes `src/updater.py` wird zu `src/update/release.py` migriert und um `Asset.digest`, `Asset.size`, `Release.body` erweitert. Neuer `src/update/installer.py` kapselt Download + Hash-Check + Plattform-Dispatch. Inno-Setup-Skript bekommt eine zweite `[Run]`-Zeile mit `Check: WizardSilent` für Auto-Restart nach Silent-Install.

**Tech Stack:** Python 3 stdlib (`urllib`, `hashlib`, `tempfile`, `subprocess`, `threading`, `tkinter`, `tkinter.ttk`), Inno Setup 6, PyInstaller. **Keine neuen Abhängigkeiten.**

**Spec-Referenz:** `docs/superpowers/specs/2026-05-28-auto-update-design.md`

---

## Chunk 1: Aufräumen + Release-Modul-Migration

Vor der Implementierung wird die Repo-Hygiene wiederhergestellt und das bestehende `updater.py` ins neue `src/update/`-Subpackage migriert — inklusive Erweiterung der Dataclasses um `digest`, `size`, `body` und Umbenennung `pick_asset_url` → `pick_asset`.

---

### Task 1.1: Junk-Datei im Repo-Root löschen

**Kontext:** Im Repo-Root liegt eine ~28 KB Datei namens `C:UsersmargeZeiterfassunglogspr22_ui.py` (Doppelpunkt = Unicode-FullWidth-Colon, deshalb in `git status` als `"C\357\200\272Users..."`). Sie würde den repo-weiten `pick_asset_url`-Grep verwirren. Erster Schritt.

**Files:**
- Delete: `C:UsersmargeZeiterfassunglogspr22_ui.py` (Repo-Root)

- [ ] **Step 1: Datei lokalisieren**

PowerShell:
```powershell
Get-ChildItem -Filter "C*Users*" | Select-Object Name, Length
```
Erwartete Ausgabe:
```
Name                                    Length
----                                    ------
CUsersmargeZeiterfassunglogspr22_ui.py  27927
```

- [ ] **Step 2: Datei löschen**

PowerShell:
```powershell
Remove-Item -LiteralPath "CUsersmargeZeiterfassunglogspr22_ui.py" -Force
```

- [ ] **Step 3: Verifikation**

PowerShell:
```powershell
git status --short
```
Erwartet: Die `"C\357\200\272Users..."`-Zeile ist weg.

- [ ] **Step 4: Kein Commit**

Die Datei war untracked — es gibt nichts zu committen. Weiter mit Task 1.2.

---

### Task 1.2: Caller-Grep für die Refactor-Liste

**Kontext:** Gemäß CLAUDE.md ("Refactor-Caller-Grep") muss vor jedem Refactor, der etwas umbenennt/entfernt, ein repo-weiter Grep die vollständige Caller-Liste liefern. Diese Liste ist die Grundlage für Task 1.3 (Migration), sodass kein Caller durchrutscht.

**Files:** keine Änderungen — reine Recherche.

- [ ] **Step 1: Repo-weiten Grep ausführen**

PowerShell (Grep-Tool ist hier bewusst nicht der Bash-Befehl — ein normaler `Select-String` reicht, aber der Plan empfiehlt das Grep-Tool wegen Performance):

Verwende das Grep-Tool mit Pattern `pick_asset_url|from src.updater|from src import updater` über `src/` und `tests/`. Erwartete Treffer (Stand 2026-05-28):

- `src/ui.py:21` — `from src.updater import (`
- `src/ui.py:24` — `    pick_asset_url,`
- `src/ui.py:308` — `        url = pick_asset_url(`
- `src/updater.py:60` — `def pick_asset_url(assets, system: str, latest_version: str) -> str | None:`
- `tests/test_updater.py:8` — `from src.updater import Asset, Release, ..., pick_asset_url, ...`
- `tests/test_updater.py:60-83` — Test-Klasse `TestPickAssetUrl` mit 6 Tests

Treffer in `docs/superpowers/plans/2026-04-28-update-check.md` und `docs/superpowers/specs/2026-04-28-update-check-design.md` sind reine Historie (alter Plan + alte Spec) — werden nicht angefasst.

- [ ] **Step 2: Caller-Liste notieren**

Wenn die Treffer-Liste vom Erwartungswert abweicht (z.B. zwischenzeitlich neue Caller dazugekommen): Plan-Tasks 1.3 ff. entsprechend ergänzen. Sonst weiter wie geplant.

---

### Task 1.3: `src/updater.py` → `src/update/release.py` migrieren

**Kontext:** Modul-Umzug ohne API-Änderung. Die Dataclass-Erweiterungen und Funktionsumbenennung kommen in Task 1.4/1.5 — hier zuerst nur der Move, damit das Diff sauber bleibt.

**Files:**
- Create: `src/update/__init__.py`
- Rename: `src/updater.py` → `src/update/release.py`
- Rename: `tests/test_updater.py` → `tests/test_release.py`
- Modify: `src/ui.py:21` (Import-Pfad), `tests/test_release.py:8` (Import-Pfad)

- [ ] **Step 1: Subpackage anlegen**

PowerShell:
```powershell
New-Item -ItemType Directory -Force "src/update" | Out-Null
```

- [ ] **Step 2: Modul umziehen**

```powershell
git mv src/updater.py src/update/release.py
git mv tests/test_updater.py tests/test_release.py
```

- [ ] **Step 3: `src/update/__init__.py` schreiben**

Verwende Write-Tool, Pfad `src/update/__init__.py`:

```python
"""Update-Subpaket.

Re-exports der öffentlichen API, damit Call-Sites mit einem einzigen Import-Block
arbeiten können. Konkrete Module:
- src.update.release  — GitHub-API-Layer (Versions-Check, Asset-Pick)
- src.update.installer — Download + Hash-Verify + Plattform-Dispatch (kommt später)
"""

from src.update.release import (
    Asset,
    Release,
    check_latest_release,
    is_newer,
    pick_asset_url,
    should_check_today,
    today_iso,
)

__all__ = [
    "Asset",
    "Release",
    "check_latest_release",
    "is_newer",
    "pick_asset_url",
    "should_check_today",
    "today_iso",
]
```

Hinweis: `pick_asset_url` bleibt vorerst exportiert — die Umbenennung auf `pick_asset` passiert in Task 1.5. Damit ist Task 1.3 ein reiner Move ohne API-Bruch.

- [ ] **Step 4: Import-Pfade in `src/ui.py` und `tests/test_release.py` anpassen**

In `src/ui.py:21` ersetzen:
```python
from src.updater import (
```
durch
```python
from src.update import (
```

In `tests/test_release.py:8` ersetzen:
```python
from src.updater import Asset, Release, check_latest_release, is_newer, pick_asset_url, should_check_today, today_iso
```
durch
```python
from src.update import Asset, Release, check_latest_release, is_newer, pick_asset_url, should_check_today, today_iso
```

Wichtig: Die `patch("src.updater.urlopen", ...)`-Aufrufe in den Tests müssen ebenfalls auf den neuen Pfad geändert werden. Mit dem Edit-Tool, `replace_all: true`, in `tests/test_release.py`:
- alt: `src.updater.urlopen`
- neu: `src.update.release.urlopen`

- [ ] **Step 5: Tests laufen lassen**

```powershell
pytest tests/test_release.py -v
```
Erwartet: Alle bisherigen Tests grün (12 Tests aus der `TestPickAssetUrl`-, `TestCheckLatestRelease`-, `TestIsNewer`-, `TestTodayIso`-, `TestShouldCheckToday`-Klasse).

- [ ] **Step 6: App-Smoke-Test**

```powershell
python -m src.main
```
Erwartet: App startet, kein `ImportError`. Fenster wieder schließen.

- [ ] **Step 7: Commit**

```powershell
git add src/update/__init__.py src/ui.py tests/test_release.py
git status
git commit -m "refactor(update): src/updater.py → src/update/release.py (reiner move, API unverändert)"
```

Hinweis zur git-Reihenfolge: `git mv` aus Step 2 hat die Renames bereits gestaged (sowohl `src/update/release.py` als auch `tests/test_release.py`). Der `git add` hier fügt nur die neu erzeugte `__init__.py` und die geänderte `ui.py` dazu. `git status` vor dem Commit zeigt erwartet: `renamed: src/updater.py -> src/update/release.py`, `renamed: tests/test_updater.py -> tests/test_release.py`, `new file: src/update/__init__.py`, `modified: src/ui.py` (und `modified: tests/test_release.py` für die Patch-Pfad-Anpassung in Step 4).

---

### Task 1.4: `Asset`-Dataclass um `digest` und `size` erweitern (TDD)

**Kontext:** GitHub liefert seit 2025-06-03 GA das Feld `digest: "sha256:<hex>"` und seit jeher `size: int` pro Asset. Beide werden in `installer.py` gebraucht (Hash-Verifikation, Progressbar). Spec sagt: `digest` ist optional (`None` für Pre-GA-Releases), `size` ist `int` (Default 0 wenn fehlend, dann Indeterminate-Mode in der Progressbar).

**Files:**
- Modify: `src/update/release.py` (Asset-Dataclass + `check_latest_release` Parsing)
- Modify: `tests/test_release.py` (neue Tests)

- [ ] **Step 1: Failing Test in `tests/test_release.py` schreiben**

Direkt am Ende von `tests/test_release.py` anhängen (nach der bestehenden `TestCheckLatestRelease`-Klasse):

```python
class TestAssetDigestAndSize:
    """Asset trägt SHA256-Digest und Größe für den Installer."""

    def test_check_latest_release_parses_digest_and_size(self):
        payload = {
            "tag_name": "v2.0.0",
            "html_url": "https://example.com",
            "assets": [
                {
                    "name": "Zeiterfassung_Setup.exe",
                    "browser_download_url": "https://example.com/exe",
                    "digest": "sha256:abc123",
                    "size": 31457280,
                },
            ],
        }
        with patch("src.update.release.urlopen", return_value=_api_response(payload)):
            release = check_latest_release("any/repo")
        assert release is not None
        assert release.assets[0].digest == "sha256:abc123"
        assert release.assets[0].size == 31457280

    def test_check_latest_release_tolerates_missing_digest(self):
        # Pre-GA-Releases haben kein digest-Feld → None, kein Fehler
        payload = {
            "tag_name": "v2.0.0",
            "html_url": "https://example.com",
            "assets": [
                {
                    "name": "Zeiterfassung_Setup.exe",
                    "browser_download_url": "https://example.com/exe",
                    "size": 31457280,
                },
            ],
        }
        with patch("src.update.release.urlopen", return_value=_api_response(payload)):
            release = check_latest_release("any/repo")
        assert release is not None
        assert release.assets[0].digest is None
        assert release.assets[0].size == 31457280

    def test_check_latest_release_tolerates_missing_size(self):
        # Sehr defensiv — size sollte immer da sein, aber Fallback 0
        payload = {
            "tag_name": "v2.0.0",
            "html_url": "https://example.com",
            "assets": [
                {
                    "name": "Zeiterfassung_Setup.exe",
                    "browser_download_url": "https://example.com/exe",
                },
            ],
        }
        with patch("src.update.release.urlopen", return_value=_api_response(payload)):
            release = check_latest_release("any/repo")
        assert release is not None
        assert release.assets[0].digest is None
        assert release.assets[0].size == 0
```

Außerdem: Helper `_three_assets` (Zeile 52) erstellt heute `Asset(name=..., url=...)` ohne `digest`/`size`. Damit das Asset-Konstrukt mit neuen Pflicht-Feldern weiterhin funktioniert: bestehende Helper-Aufrufe um `digest=None, size=0` ergänzen — passiert sauberer, wenn die Felder optional mit Default sind. Implementation in Step 3 macht beide Felder mit Defaults, also kein Anpassungsbedarf am Helper.

- [ ] **Step 2: Test laufen lassen — muss fehlschlagen**

```powershell
pytest tests/test_release.py::TestAssetDigestAndSize -v
```
Erwartet: 3 FAIL mit `AttributeError: 'Asset' object has no attribute 'digest'` (oder ähnlich).

- [ ] **Step 3: Implementation in `src/update/release.py`**

Asset-Dataclass erweitern (aktuell Zeilen 47-50):

```python
@dataclass(frozen=True)
class Asset:
    name: str
    url: str
    digest: str | None = None
    size: int = 0
```

`check_latest_release` (aktuell Zeilen 100-105) — Asset-Konstruktion erweitern:

alt:
```python
assets = tuple(
    Asset(name=a["name"], url=a["browser_download_url"])
    for a in raw_assets
    if isinstance(a, dict) and "name" in a and "browser_download_url" in a
)
```

neu:
```python
assets = tuple(
    Asset(
        name=a["name"],
        url=a["browser_download_url"],
        digest=a.get("digest"),
        size=_safe_size(a.get("size")),
    )
    for a in raw_assets
    if isinstance(a, dict) and "name" in a and "browser_download_url" in a
)
```

Plus oberhalb von `check_latest_release` (auf Modulebene) den Helper einfügen:

```python
def _safe_size(value) -> int:
    """Robust int-Konvertierung. None / Strings / falsche Typen → 0.

    Wir wollen kein Asset wegen einer nicht-int size verlieren, weil
    der einzige Use-Case für size eine Progressbar ist (Default 0 = indeterminate).
    """
    try:
        return int(value) if value is not None else 0
    except (TypeError, ValueError):
        return 0
```

Begründung: `int("abc")` würde `ValueError` werfen, was vom `except`-Block in `check_latest_release` (Zeile 107: nur `URLError, OSError, json.JSONDecodeError, TypeError, KeyError, AttributeError`) **nicht** gefangen wird und damit die ganze Funktion brechen würde. Der Helper degradiert kaputte `size`-Werte zu `0`, statt das Asset oder das ganze Release zu verlieren.

- [ ] **Step 4: Edge-Case-Test für `_safe_size` ergänzen**

In `tests/test_release.py` (am Dateiende) zur `TestAssetDigestAndSize`-Klasse hinzufügen:

```python
    def test_check_latest_release_handles_garbage_size(self):
        # size als String mit Buchstaben würde int() crashen; _safe_size fängt das
        payload = {
            "tag_name": "v2.0.0",
            "html_url": "https://example.com",
            "assets": [
                {
                    "name": "Zeiterfassung_Setup.exe",
                    "browser_download_url": "https://example.com/exe",
                    "size": "not-a-number",
                },
            ],
        }
        with patch("src.update.release.urlopen", return_value=_api_response(payload)):
            release = check_latest_release("any/repo")
        assert release is not None  # Funktion bricht NICHT mit ValueError
        assert release.assets[0].size == 0
```

- [ ] **Step 5: Tests grün**

```powershell
pytest tests/test_release.py -v
```
Erwartet: alle bisherigen Tests + die 4 neuen Tests aus `TestAssetDigestAndSize` grün, keine FAIL/ERROR.

- [ ] **Step 6: Commit**

```powershell
git add src/update/release.py tests/test_release.py
git commit -m "feat(update): Asset trägt digest und size für Auto-Install"
```

---

### Task 1.5: `Release.body` und Umbenennung `pick_asset_url` → `pick_asset` (TDD)

**Kontext:** Der Dialog zeigt den Changelog (`release.body` aus GitHub). Und der einzige Call-Site bekommt statt der nackten URL das ganze `Asset`-Objekt zurück (damit `digest`/`size` mit durchgereicht werden). Beide Änderungen in einem Commit, weil sie zusammen den `Release`/`Asset`-Vertrag final formen.

**Files:**
- Modify: `src/update/release.py` (Release-Dataclass, `pick_asset_url` → `pick_asset`, `check_latest_release` parsed `body`)
- Modify: `src/update/__init__.py` (Re-Export `pick_asset` statt `pick_asset_url`)
- Modify: `tests/test_release.py` (Tests umbenennen + erweitern)
- Modify: `src/ui.py:21-28, 308` (Import + Call-Site)

- [ ] **Step 1: Failing Tests in `tests/test_release.py`**

Test-Klasse `TestPickAssetUrl` (Zeilen 60-83) komplett ersetzen durch `TestPickAsset`. Das ist der einfachste Pfad — `replace_all` schneidet zu viel, also Edit-Tool mit eindeutigem Block:

```python
class TestPickAsset:
    """pick_asset liefert das ganze Asset-Objekt (oder None)."""

    def test_windows_picks_exe_asset(self):
        assets = _three_assets("1.9.0")
        result = pick_asset(assets, "Windows", "1.9.0")
        assert result is not None
        assert result.name == "Zeiterfassung_Setup.exe"
        assert result.url == "https://example.com/exe"

    def test_darwin_picks_arm_dmg_asset(self):
        assets = _three_assets("1.9.0")
        result = pick_asset(assets, "Darwin", "1.9.0")
        assert result is not None
        assert result.name == "Zeiterfassung-1.9.0-arm64.dmg"

    def test_linux_picks_appimage_asset(self):
        assets = _three_assets("1.9.0")
        result = pick_asset(assets, "Linux", "1.9.0")
        assert result is not None
        assert result.name == "Zeiterfassung-1.9.0-x86_64.AppImage"

    def test_unknown_system_returns_none(self):
        assets = _three_assets("1.9.0")
        assert pick_asset(assets, "FreeBSD", "1.9.0") is None

    def test_missing_asset_returns_none(self):
        assets = [Asset(name="Zeiterfassung-1.9.0-x86_64.AppImage", url="u")]
        assert pick_asset(assets, "Windows", "1.9.0") is None

    def test_version_mismatch_in_dmg_name_returns_none(self):
        assets = [Asset(name="Zeiterfassung-1.8.0-arm64.dmg", url="u")]
        assert pick_asset(assets, "Darwin", "1.9.0") is None
```

Und Import-Zeile (Zeile 8) anpassen:
- alt: `..., pick_asset_url, ...`
- neu: `..., pick_asset, ...`

Außerdem: neuen Test für `Release.body` anhängen, am besten als eigene Klasse:

```python
class TestReleaseBody:
    def test_check_latest_release_parses_body(self):
        payload = {
            "tag_name": "v2.0.0",
            "html_url": "https://example.com",
            "body": "## Changes\n- Feature X\n- Bugfix Y",
            "assets": [],
        }
        with patch("src.update.release.urlopen", return_value=_api_response(payload)):
            release = check_latest_release("any/repo")
        assert release is not None
        assert release.body == "## Changes\n- Feature X\n- Bugfix Y"

    def test_check_latest_release_body_defaults_empty_when_missing(self):
        payload = {
            "tag_name": "v2.0.0",
            "html_url": "https://example.com",
            "assets": [],
        }
        with patch("src.update.release.urlopen", return_value=_api_response(payload)):
            release = check_latest_release("any/repo")
        assert release is not None
        assert release.body == ""
```

- [ ] **Step 2: Tests laufen — müssen fehlschlagen**

```powershell
pytest tests/test_release.py::TestPickAsset tests/test_release.py::TestReleaseBody -v
```
Erwartet: alle FAIL mit `ImportError: cannot import name 'pick_asset'` bzw. `AttributeError: ... 'body'`.

- [ ] **Step 3: Implementation in `src/update/release.py`**

`Release`-Dataclass (aktuell Zeilen 53-57) um `body` erweitern:

```python
@dataclass(frozen=True)
class Release:
    version: str        # ohne v-Prefix, z.B. "1.9.0"
    html_url: str       # Release-Page auf GitHub
    body: str           # Changelog-Markdown aus GitHub-Release
    assets: tuple[Asset, ...]
```

Funktion `pick_asset_url` (Zeilen 60-72) umbenennen in `pick_asset`, Return-Typ ändern:

```python
def pick_asset(assets, system: str, latest_version: str) -> Asset | None:
    """Liefert das Plattform-Asset oder None.

    Match per exaktem Dateinamen aus dem bekannten Schema je Plattform.
    """
    expected_name = {
        "Windows": "Zeiterfassung_Setup.exe",
        "Darwin": f"Zeiterfassung-{latest_version}-arm64.dmg",
        "Linux": f"Zeiterfassung-{latest_version}-x86_64.AppImage",
    }.get(system)
    if expected_name is None:
        return None
    for asset in assets:
        if asset.name == expected_name:
            return asset
    return None
```

`check_latest_release` (Zeile 106) — Release-Konstruktor um `body=` erweitern:

alt:
```python
return Release(version=tag, html_url=html_url, assets=assets)
```

neu:
```python
return Release(
    version=tag,
    html_url=html_url,
    body=payload.get("body") or "",
    assets=assets,
)
```

- [ ] **Step 4: `src/update/__init__.py` anpassen**

`pick_asset_url` → `pick_asset` im Import-Block und in `__all__`. Mit Edit-Tool, beide Vorkommen einzeln.

- [ ] **Step 5: `src/ui.py` Call-Site anpassen**

Import-Block Zeile 21-28:

alt:
```python
from src.update import (
    check_latest_release,
    is_newer,
    pick_asset_url,
    should_check_today,
    today_iso,
    Release,
)
```

neu:
```python
from src.update import (
    check_latest_release,
    is_newer,
    pick_asset,
    should_check_today,
    today_iso,
    Release,
)
```

Call-Site bei Zeile 307-311 (`_open_update_download`):

alt:
```python
def _open_update_download(self, release: "Release"):
    url = pick_asset_url(
        release.assets, platform.system(), release.version,
    ) or release.html_url
    webbrowser.open(url)
```

neu:
```python
def _open_update_download(self, release: "Release"):
    asset = pick_asset(release.assets, platform.system(), release.version)
    url = asset.url if asset else release.html_url
    webbrowser.open(url)
```

Hinweis: Der Inhalt der Methode wird in Chunk 3 (Task 3.x) noch einmal komplett ersetzt durch den Dialog-Aufruf. Dieser Zwischenschritt hält den Refactor an dieser Stelle aber sauber kompilierbar und der Banner-Pfad bleibt funktional.

- [ ] **Step 6: Tests grün**

```powershell
pytest tests/test_release.py -v
```
Erwartet: alle Tests grün. Wichtig ist, dass keine `FAIL` und keine `ERROR` auftauchen — die genaue Test-Zahl bleibt unkommentiert (Variabilität durch frühere Iterationen).

- [ ] **Step 7: App-Smoke-Test**

```powershell
python -m src.main
```
Erwartet: App startet, kein `ImportError`, kein `AttributeError` beim Update-Check. Fenster schließen.

- [ ] **Step 8: Commit**

```powershell
git add src/update/ src/ui.py tests/test_release.py
git commit -m "feat(update): Release.body + pick_asset (statt pick_asset_url) für Auto-Install-Vorbereitung"
```

---

**Ende Chunk 1.** Nächster Chunk: Installer-Modul (`src/update/installer.py`) mit Download, Hash-Verifikation, Plattform-Dispatch.

---

## Chunk 2: Installer-Modul (`src/update/installer.py`)

Pure Logik ohne Tk-Abhängigkeit. Aufgaben: SHA256-Verifikation, Download mit Progress-Callback und Cancel-Event, Plattform-Dispatch (`_install_windows`, `_install_linux`), `can_auto_install`-Capability-Check, Orchestrierungs-Funktion `download_and_install`.

Test-Strategie: Alles unit-testbar mit `unittest.mock.patch` über `urlopen` und `subprocess.Popen`. Keine echte Netzwerk-Aktion und kein echter Installer-Start in den Tests.

---

### Task 2.1: Modul-Skeleton mit `InstallError` und `can_auto_install` (TDD)

**Kontext:** Bevor irgendetwas heruntergeladen werden kann, muss der Dialog wissen, ob die Plattform Auto-Install überhaupt unterstützt. Auf macOS, im Repo-Modus oder auf Linux ohne `$APPIMAGE` soll der Dialog gar nicht erst öffnen — `ui._open_update_download` fällt dann zurück auf `webbrowser.open`.

**Files:**
- Create: `src/update/installer.py`
- Create: `tests/test_installer.py`
- Modify: `src/update/__init__.py` (Re-Export)

- [ ] **Step 1: Failing Test in `tests/test_installer.py` schreiben**

```python
import os
import sys
from unittest.mock import patch

import pytest

from src.update.installer import InstallError, can_auto_install


class TestCanAutoInstall:
    """can_auto_install gibt True nur in Konstellationen zurück, in denen
    der Plattform-Dispatch in installer.py tatsächlich funktionieren kann."""

    def test_repo_mode_returns_false(self):
        # In der Dev-Umgebung ist sys.frozen nicht gesetzt → False, egal welche Plattform
        with patch.object(sys, "frozen", False, create=True):
            with patch("src.update.installer.platform.system", return_value="Windows"):
                assert can_auto_install() is False

    def test_frozen_windows_returns_true(self):
        with patch.object(sys, "frozen", True, create=True):
            with patch("src.update.installer.platform.system", return_value="Windows"):
                assert can_auto_install() is True

    def test_frozen_darwin_returns_false(self):
        # macOS hat keinen Auto-Install-Pfad — Spec
        with patch.object(sys, "frozen", True, create=True):
            with patch("src.update.installer.platform.system", return_value="Darwin"):
                assert can_auto_install() is False

    def test_frozen_linux_with_appimage_returns_true(self, tmp_path):
        appimage = tmp_path / "Zeiterfassung.AppImage"
        appimage.write_text("")
        with patch.object(sys, "frozen", True, create=True):
            with patch("src.update.installer.platform.system", return_value="Linux"):
                with patch.dict(os.environ, {"APPIMAGE": str(appimage)}):
                    assert can_auto_install() is True

    def test_frozen_linux_without_appimage_returns_false(self):
        with patch.object(sys, "frozen", True, create=True):
            with patch("src.update.installer.platform.system", return_value="Linux"):
                env_without_appimage = {k: v for k, v in os.environ.items() if k != "APPIMAGE"}
                with patch.dict(os.environ, env_without_appimage, clear=True):
                    assert can_auto_install() is False

    @pytest.mark.skipif(sys.platform == "win32", reason="chmod-based readonly check is POSIX-only")
    def test_frozen_linux_with_readonly_parent_returns_false(self, tmp_path):
        readonly_dir = tmp_path / "readonly"
        readonly_dir.mkdir()
        appimage = readonly_dir / "Zeiterfassung.AppImage"
        appimage.write_text("")
        os.chmod(readonly_dir, 0o555)  # r-xr-xr-x
        try:
            with patch.object(sys, "frozen", True, create=True):
                with patch("src.update.installer.platform.system", return_value="Linux"):
                    with patch.dict(os.environ, {"APPIMAGE": str(appimage)}):
                        assert can_auto_install() is False
        finally:
            os.chmod(readonly_dir, 0o755)  # cleanup, sonst kann tmp nicht entfernt werden


class TestInstallError:
    def test_install_error_is_exception(self):
        with pytest.raises(InstallError, match="boom"):
            raise InstallError("boom")

    def test_integrity_error_is_install_error_subclass(self):
        # Dialog prüft via isinstance — Subclass-Beziehung ist Spec-Pflicht
        from src.update.installer import IntegrityError
        assert issubclass(IntegrityError, InstallError)
```

- [ ] **Step 2: Test laufen — muss fehlschlagen**

```powershell
pytest tests/test_installer.py -v
```
Erwartet: `ImportError: cannot import name 'InstallError'` (Modul existiert noch nicht).

- [ ] **Step 3: `src/update/installer.py` schreiben**

```python
"""Download, Hash-Verifikation und Plattform-Dispatch für Auto-Install.

Single Purpose: pure Logik ohne Tk-Abhängigkeit. UI-Layer ruft
`download_and_install` aus einem Worker-Thread.

Plattform-Strategie:
- Windows: Inno Setup `/VERYSILENT /SUPPRESSMSGBOXES /CLOSEAPPLICATIONS
           /FORCECLOSEAPPLICATIONS /NORESTART` — der Installer übernimmt
           File-Lock-Replace und Restart (via [Run] in installer.iss).
- Linux:   Neue AppImage neben der laufenden ablegen, atomic os.replace,
           neue Instanz starten. Erfordert schreibbares Verzeichnis.
- Darwin:  Kein Auto-Install (Spec) — can_auto_install() → False.
"""

import logging
import os
import platform
import sys

logger = logging.getLogger(__name__)


class InstallError(Exception):
    """Nutzerlesbare deutsche Message in args[0]. UI zeigt die Message
    direkt im Fehler-Dialog."""


class IntegrityError(InstallError):
    """Hash-Mismatch oder Digest-Format-Fehler. Wird vom Dialog
    speziell behandelt: KEIN Browser-Fallback, weil wir den Nutzer
    nicht auf einen potenziell kompromittierten Pfad lenken wollen."""


def can_auto_install() -> bool:
    """True, wenn die laufende App Auto-Install unterstützt.

    Repo-Modus (nicht frozen) → False: Auto-Install ergibt nur Sinn im
    gebauten Artefakt, sonst würde ein dev-installer im src/ landen.
    """
    if not getattr(sys, "frozen", False):
        return False

    system = platform.system()
    if system == "Windows":
        return True
    if system == "Linux":
        appimage = os.environ.get("APPIMAGE")
        if not appimage:
            return False
        parent = os.path.dirname(appimage)
        return os.access(parent, os.W_OK)
    return False
```

- [ ] **Step 4: Tests grün**

```powershell
pytest tests/test_installer.py -v
```
Erwartet: alle 7 Tests grün (6 in `TestCanAutoInstall` + 1 in `TestInstallError`).

- [ ] **Step 5: Re-Export in `src/update/__init__.py`**

Den Import-Block erweitern:

```python
from src.update.release import (
    Asset,
    Release,
    check_latest_release,
    is_newer,
    pick_asset,
    should_check_today,
    today_iso,
)
from src.update.installer import (
    InstallError,
    IntegrityError,
    can_auto_install,
)
```

Und `__all__` entsprechend ergänzen:

```python
__all__ = [
    "Asset",
    "Release",
    "check_latest_release",
    "is_newer",
    "pick_asset",
    "should_check_today",
    "today_iso",
    "InstallError",
    "IntegrityError",
    "can_auto_install",
]
```

- [ ] **Step 6: App-Smoke-Test**

```powershell
python -m src.main
```
Erwartet: App startet ohne ImportError. Fenster wieder schließen.

- [ ] **Step 7: Commit**

```powershell
git add src/update/ tests/test_installer.py
git commit -m "feat(update): installer-modul-skeleton mit can_auto_install + InstallError"
```

---

### Task 2.2: `_verify_sha256` mit allen Edge-Cases (TDD)

**Kontext:** Zweite Verteidigungslinie nach TLS. GitHub-Format ist `"sha256:<64-hex>"`. Hash-Mismatch → `InstallError` mit deutscher Message. Fehlendes Digest (`None`) → Log-Warning, kein Fehler (Pre-GA-Releases). Ungültiges Format → `InstallError`.

**Files:**
- Modify: `src/update/installer.py`
- Modify: `tests/test_installer.py`

- [ ] **Step 1: Failing Tests in `tests/test_installer.py`**

Am Dateiende anhängen:

```python
import hashlib
import logging

from src.update.installer import IntegrityError, _verify_sha256


def _hash_for(content: bytes) -> str:
    return "sha256:" + hashlib.sha256(content).hexdigest()


class TestVerifySha256:
    def test_correct_hash_passes_silently(self, tmp_path):
        path = tmp_path / "asset.bin"
        path.write_bytes(b"hello world")
        _verify_sha256(path, _hash_for(b"hello world"))
        # kein Fehler = pass

    def test_wrong_hash_raises_integrity_error(self, tmp_path):
        path = tmp_path / "asset.bin"
        path.write_bytes(b"hello world")
        wrong = "sha256:" + ("0" * 64)
        with pytest.raises(IntegrityError, match="Sicherheitsprüfung"):
            _verify_sha256(path, wrong)

    def test_none_digest_logs_warning_and_passes(self, tmp_path, caplog):
        path = tmp_path / "asset.bin"
        path.write_bytes(b"hello world")
        with caplog.at_level(logging.WARNING, logger="src.update.installer"):
            _verify_sha256(path, None)
        assert any("digest" in r.message.lower() for r in caplog.records)

    def test_invalid_format_no_prefix_raises(self, tmp_path):
        path = tmp_path / "asset.bin"
        path.write_bytes(b"hello world")
        with pytest.raises(IntegrityError, match="ungültig"):
            _verify_sha256(path, "abc123")  # kein "sha256:"-Prefix

    def test_invalid_format_wrong_algo_raises(self, tmp_path):
        path = tmp_path / "asset.bin"
        path.write_bytes(b"hello world")
        with pytest.raises(IntegrityError, match="ungültig"):
            _verify_sha256(path, "md5:abc123")

    def test_invalid_format_short_hex_raises(self, tmp_path):
        path = tmp_path / "asset.bin"
        path.write_bytes(b"hello world")
        with pytest.raises(IntegrityError, match="ungültig"):
            _verify_sha256(path, "sha256:abc")  # 3 Hex-Zeichen, nicht 64
```

- [ ] **Step 2: Tests laufen — müssen fehlschlagen**

```powershell
pytest tests/test_installer.py::TestVerifySha256 -v
```
Erwartet: `ImportError: cannot import name '_verify_sha256'`.

- [ ] **Step 3: Implementation in `src/update/installer.py`**

Imports oben in der bestehenden Import-Sektion ergänzen:

```python
import hashlib
import re
from pathlib import Path
```

Helper-Block + Funktion am Modul-Ende anhängen:

```python
_SHA256_PATTERN = re.compile(r"^sha256:[0-9a-fA-F]{64}$")


def _verify_sha256(path: Path, expected_digest: str | None) -> None:
    """Wirft InstallError bei Format-Fehler oder Hash-Mismatch.

    Fehlendes digest (None) ist KEIN Fehler — wir loggen eine Warning und
    fahren fort. Grund: Pre-GA-Releases (vor GitHub's digest-GA am
    2025-06-03) haben das Feld nicht. TLS-Validation bleibt als erste
    Verteidigungslinie.
    """
    if expected_digest is None:
        logger.warning(
            "Asset hat kein digest-Feld — SHA256-Prüfung übersprungen (Pre-GA-Release?)"
        )
        return

    if not _SHA256_PATTERN.match(expected_digest):
        raise IntegrityError(f"Digest-Format ungültig: {expected_digest!r}")

    expected_hex = expected_digest.split(":", 1)[1].lower()
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(64 * 1024), b""):
            h.update(chunk)
    actual_hex = h.hexdigest()

    if actual_hex != expected_hex:
        raise IntegrityError(
            "Sicherheitsprüfung fehlgeschlagen — die heruntergeladene Datei "
            "wurde unterwegs verändert."
        )
```


- [ ] **Step 4: Tests grün**

```powershell
pytest tests/test_installer.py -v
```
Erwartet: 7 alte + 6 neue Tests grün.

- [ ] **Step 5: Commit**

```powershell
git add src/update/installer.py tests/test_installer.py
git commit -m "feat(installer): _verify_sha256 mit format-check und mismatch-handling"
```

---

### Task 2.3: `_download` mit Progress, Cancel, Fehlerpfaden (TDD)

**Kontext:** Lädt eine URL in einen Pfad. Ruft `on_progress(bytes_done, bytes_total)` pro Chunk. Prüft `cancel_event` pro Chunk. Bei jeder Exception (`URLError`, `OSError`, `HTTPError`) wird die Temp-Datei gelöscht und ein `InstallError` mit deutscher Message geworfen.

**Files:**
- Modify: `src/update/installer.py`
- Modify: `tests/test_installer.py`

- [ ] **Step 1: Failing Tests**

Am Dateiende von `tests/test_installer.py` anhängen:

```python
import threading
from io import BytesIO
from unittest.mock import MagicMock
from urllib.error import HTTPError, URLError

from src.update.installer import _download


def _fake_response(payload: bytes) -> MagicMock:
    """Minimaler urlopen-Return: read(n) liefert Chunks."""
    response = MagicMock()
    response.__enter__ = lambda self: self
    response.__exit__ = lambda self, *a: False
    stream = BytesIO(payload)
    response.read = stream.read
    return response


class TestDownload:
    def test_writes_complete_file(self, tmp_path):
        dest = tmp_path / "asset.bin"
        payload = b"x" * 10_000
        cancel = threading.Event()
        with patch("src.update.installer.urlopen", return_value=_fake_response(payload)):
            _download("https://example.com/asset", dest, len(payload), lambda d, t: None, cancel)
        assert dest.read_bytes() == payload

    def test_calls_progress_with_cumulative_bytes(self, tmp_path):
        dest = tmp_path / "asset.bin"
        payload = b"x" * 20_000  # > 2 Chunks bei 8 KiB
        cancel = threading.Event()
        progress_calls = []
        with patch("src.update.installer.urlopen", return_value=_fake_response(payload)):
            _download("https://example.com/asset", dest, len(payload),
                      lambda d, t: progress_calls.append((d, t)), cancel)
        assert progress_calls[-1] == (20_000, 20_000)
        # Mindestens zwei Progress-Updates (Chunked-Download)
        assert len(progress_calls) >= 2
        # Total bleibt konstant
        assert all(t == 20_000 for _d, t in progress_calls)
        # Done ist monoton steigend
        dones = [d for d, _t in progress_calls]
        assert dones == sorted(dones)

    def test_cancel_event_set_aborts_and_cleans_up(self, tmp_path):
        dest = tmp_path / "asset.bin"
        payload = b"x" * 100_000
        cancel = threading.Event()
        cancel.set()  # vorher gesetzt → erster Loop-Check bricht ab

        with patch("src.update.installer.urlopen", return_value=_fake_response(payload)):
            with pytest.raises(InstallError, match="abgebrochen"):
                _download("https://example.com/asset", dest, len(payload),
                          lambda d, t: None, cancel)
        assert not dest.exists()

    def test_url_error_raises_install_error_and_cleans_up(self, tmp_path):
        dest = tmp_path / "asset.bin"
        cancel = threading.Event()
        with patch("src.update.installer.urlopen", side_effect=URLError("offline")):
            with pytest.raises(InstallError, match="Netzwerkproblem"):
                _download("https://example.com/asset", dest, 100, lambda d, t: None, cancel)
        assert not dest.exists()

    def test_http_error_includes_code(self, tmp_path):
        dest = tmp_path / "asset.bin"
        cancel = threading.Event()
        err = HTTPError(url="x", code=503, msg="boom", hdrs=None, fp=None)
        with patch("src.update.installer.urlopen", side_effect=err):
            with pytest.raises(InstallError, match="HTTP 503"):
                _download("https://example.com/asset", dest, 100, lambda d, t: None, cancel)
        assert not dest.exists()

    def test_os_error_during_write_cleans_up(self, tmp_path):
        # Ziel ist read-only (Verzeichnis existiert nicht)
        dest = tmp_path / "nonexistent_dir" / "asset.bin"
        cancel = threading.Event()
        with patch("src.update.installer.urlopen", return_value=_fake_response(b"x" * 100)):
            with pytest.raises(InstallError, match="gespeichert"):
                _download("https://example.com/asset", dest, 100, lambda d, t: None, cancel)
        # Datei wurde nicht erzeugt
        assert not dest.exists()
```

- [ ] **Step 2: Tests laufen — müssen fehlschlagen**

```powershell
pytest tests/test_installer.py::TestDownload -v
```
Erwartet: `ImportError: cannot import name '_download'`.

- [ ] **Step 3: Implementation in `src/update/installer.py`**

Imports oben in der bestehenden Import-Sektion ergänzen:

```python
import threading
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
```

`_download` ans Modul-Ende anhängen:

```python
_CHUNK_SIZE = 8 * 1024  # 8 KiB


def _download(
    url: str,
    dest: Path,
    expected_size: int,
    on_progress: Callable[[int, int], None],
    cancel_event: threading.Event,
) -> None:
    """Lädt url nach dest. Ruft on_progress(done, total) pro Chunk.
    Prüft cancel_event pro Chunk. Bei Fehler oder Cancel wird dest gelöscht.

    expected_size kann 0 sein (wenn die API-Response kein size-Feld liefert) —
    in dem Fall ist die Progressbar im Indeterminate-Mode, wir geben aber
    trotzdem (done, 0) durch.
    """
    request = Request(
        url,
        headers={"User-Agent": "Zeiterfassung-Updater"},
    )
    done = 0
    try:
        with urlopen(request, timeout=30) as response:
            with open(dest, "wb") as f:
                while True:
                    if cancel_event.is_set():
                        raise InstallError("Download abgebrochen.")
                    chunk = response.read(_CHUNK_SIZE)
                    if not chunk:
                        break
                    f.write(chunk)
                    done += len(chunk)
                    on_progress(done, expected_size)
    except InstallError:
        _cleanup(dest)
        raise
    except HTTPError as e:
        _cleanup(dest)
        raise InstallError(f"Download fehlgeschlagen: Server-Fehler (HTTP {e.code}).") from e
    except URLError as e:
        _cleanup(dest)
        raise InstallError("Download fehlgeschlagen: Netzwerkproblem.") from e
    except OSError as e:
        _cleanup(dest)
        raise InstallError("Download fehlgeschlagen: Datei konnte nicht gespeichert werden.") from e


def _cleanup(path) -> None:
    """Best-effort. Schlägt nie fehl."""
    try:
        os.remove(path)
    except OSError:
        pass
```

Hinweis: Reihenfolge der `except`-Blöcke ist KRITISCH. `HTTPError` ist Subclass von `URLError`, und `URLError` ist Subclass von `OSError` (Python 3, MRO: `URLError → OSError`). Wenn die Reihenfolge invertiert wird (`OSError` vor `URLError`), würde jeder Netzwerk-Fehler in die "Datei konnte nicht gespeichert werden"-Message fallen statt in "Netzwerkproblem". Reihenfolge `HTTPError → URLError → OSError` ist Pflicht.

- [ ] **Step 4: Tests grün**

```powershell
pytest tests/test_installer.py -v
```
Erwartet: alle bisherigen + 6 neue TestDownload-Tests grün.

- [ ] **Step 5: Commit**

```powershell
git add src/update/installer.py tests/test_installer.py
git commit -m "feat(installer): _download mit progress, cancel und fehlerpfaden"
```

---

### Task 2.4: `_install_windows` (TDD)

**Kontext:** Startet den Inno-Setup-Installer detached mit Silent-Flags. Worker-Thread kehrt zurück, Caller (Dialog) ruft anschließend `root.destroy()` mit kleinem Delay.

**Files:**
- Modify: `src/update/installer.py`
- Modify: `tests/test_installer.py`

- [ ] **Step 1: Failing Tests**

Am Dateiende anhängen:

```python
from src.update.installer import _install_windows


class TestInstallWindows:
    def test_popen_called_with_silent_flags(self, tmp_path):
        setup = tmp_path / "Zeiterfassung_Setup.exe"
        setup.write_bytes(b"fake-installer")
        with patch("src.update.installer.subprocess.Popen") as popen:
            _install_windows(setup)
        assert popen.called
        args, kwargs = popen.call_args
        cmd = args[0]
        assert cmd[0] == str(setup)
        for flag in ("/VERYSILENT", "/SUPPRESSMSGBOXES", "/CLOSEAPPLICATIONS",
                     "/FORCECLOSEAPPLICATIONS", "/NORESTART"):
            assert flag in cmd, f"{flag} fehlt in {cmd!r}"

    def test_popen_uses_detached_creationflags(self, tmp_path):
        setup = tmp_path / "Zeiterfassung_Setup.exe"
        setup.write_bytes(b"fake-installer")
        with patch("src.update.installer.subprocess.Popen") as popen:
            _install_windows(setup)
        _args, kwargs = popen.call_args
        # creationflags = DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
        # DETACHED_PROCESS = 0x00000008
        # CREATE_NEW_PROCESS_GROUP = 0x00000200
        assert kwargs.get("creationflags", 0) & 0x00000008
        assert kwargs.get("creationflags", 0) & 0x00000200
        assert kwargs.get("close_fds") is True

    def test_popen_failure_raises_install_error(self, tmp_path):
        setup = tmp_path / "Zeiterfassung_Setup.exe"
        setup.write_bytes(b"fake-installer")
        with patch("src.update.installer.subprocess.Popen", side_effect=OSError("denied")):
            with pytest.raises(InstallError, match="Installer konnte nicht gestartet werden"):
                _install_windows(setup)
```

- [ ] **Step 2: Tests laufen — müssen fehlschlagen**

```powershell
pytest tests/test_installer.py::TestInstallWindows -v
```
Erwartet: `ImportError: cannot import name '_install_windows'`.

- [ ] **Step 3: Implementation**

Imports oben in der bestehenden Import-Sektion ergänzen:

```python
import subprocess
```

Implementation ans Ende anhängen:

```python
# Windows process creation flags (siehe MSDN)
# Wir importieren NICHT aus subprocess (das Attribut existiert nur auf Windows),
# damit das Modul auch unter Linux/macOS importierbar bleibt.
_DETACHED_PROCESS = 0x00000008
_CREATE_NEW_PROCESS_GROUP = 0x00000200


def _install_windows(setup_exe: Path) -> None:
    """Startet Inno-Setup-Installer detached und kehrt sofort zurück.

    Der Installer kümmert sich um File-Lock-Replace (CloseApplications=force)
    und Restart (zweite [Run]-Zeile in installer.iss mit Check: WizardSilent).
    """
    try:
        subprocess.Popen(
            [
                str(setup_exe),
                "/VERYSILENT",
                "/SUPPRESSMSGBOXES",
                "/CLOSEAPPLICATIONS",
                "/FORCECLOSEAPPLICATIONS",
                "/NORESTART",
            ],
            creationflags=_DETACHED_PROCESS | _CREATE_NEW_PROCESS_GROUP,
            close_fds=True,
        )
    except OSError as e:
        raise InstallError("Installer konnte nicht gestartet werden.") from e
```

- [ ] **Step 4: Tests grün**

```powershell
pytest tests/test_installer.py -v
```

- [ ] **Step 5: Commit**

```powershell
git add src/update/installer.py tests/test_installer.py
git commit -m "feat(installer): _install_windows mit inno-setup silent-flags"
```

---

### Task 2.5: `_install_linux` (TDD)

**Kontext:** Lädt neue AppImage neben der laufenden ab (gleicher Pfad + `.new`), `chmod +x`, `os.replace` atomar, neue Instanz starten. Spec: tmp_path muss zwingend im selben Verzeichnis liegen wie `$APPIMAGE`, sonst `OSError: Invalid cross-device link`. Verantwortung für die Tempfile-Lage liegt allerdings beim Caller (`download_and_install`), nicht beim `_install_linux` — der erwartet einen schon richtig platzierten `tmp_path`.

**Files:**
- Modify: `src/update/installer.py`
- Modify: `tests/test_installer.py`

- [ ] **Step 1: Failing Tests**

Am Dateiende anhängen:

```python
from src.update.installer import _install_linux


class TestInstallLinux:
    def test_replaces_appimage_and_starts_new_instance(self, tmp_path):
        appimage = tmp_path / "Zeiterfassung.AppImage"
        appimage.write_bytes(b"old-version")
        new_image = tmp_path / "Zeiterfassung.AppImage.tmp"
        new_image.write_bytes(b"new-version")

        with patch.dict(os.environ, {"APPIMAGE": str(appimage)}):
            with patch("src.update.installer.subprocess.Popen") as popen:
                _install_linux(new_image)

        # AppImage wurde durch neue Version ersetzt
        assert appimage.read_bytes() == b"new-version"
        # Popen wurde mit der AppImage und start_new_session aufgerufen
        args, kwargs = popen.call_args
        assert args[0] == [str(appimage)]
        assert kwargs.get("start_new_session") is True
        assert kwargs.get("close_fds") is True

    def test_chmod_executable_before_replace(self, tmp_path):
        # AppImage muss vor dem Replace +x sein, sonst wird sie als non-executable installiert.
        # Test prüft den Modus nach _install_linux indirekt.
        if sys.platform == "win32":
            pytest.skip("chmod-Verhalten ist POSIX-spezifisch")
        appimage = tmp_path / "Zeiterfassung.AppImage"
        appimage.write_bytes(b"old")
        new_image = tmp_path / "Zeiterfassung.AppImage.tmp"
        new_image.write_bytes(b"new")
        os.chmod(new_image, 0o644)  # ohne +x

        with patch.dict(os.environ, {"APPIMAGE": str(appimage)}):
            with patch("src.update.installer.subprocess.Popen"):
                _install_linux(new_image)

        mode = os.stat(appimage).st_mode & 0o777
        # Mindestens user-execute gesetzt
        assert mode & 0o100, f"Mode {oct(mode)} hat kein user-execute"

    def test_no_appimage_env_raises(self, tmp_path):
        new_image = tmp_path / "x.tmp"
        new_image.write_bytes(b"")
        env_without_appimage = {k: v for k, v in os.environ.items() if k != "APPIMAGE"}
        with patch.dict(os.environ, env_without_appimage, clear=True):
            with pytest.raises(InstallError, match="AppImage"):
                _install_linux(new_image)

    def test_popen_failure_raises_install_error(self, tmp_path):
        appimage = tmp_path / "Zeiterfassung.AppImage"
        appimage.write_bytes(b"old")
        new_image = tmp_path / "Zeiterfassung.AppImage.tmp"
        new_image.write_bytes(b"new")
        with patch.dict(os.environ, {"APPIMAGE": str(appimage)}):
            with patch("src.update.installer.subprocess.Popen", side_effect=OSError("denied")):
                with pytest.raises(InstallError, match="Neue AppImage konnte nicht gestartet werden"):
                    _install_linux(new_image)
```

- [ ] **Step 2: Tests laufen — müssen fehlschlagen**

```powershell
pytest tests/test_installer.py::TestInstallLinux -v
```
Erwartet: `ImportError: cannot import name '_install_linux'`.

- [ ] **Step 3: Implementation**

Imports oben in der bestehenden Import-Sektion ergänzen:

```python
import stat as _stat
```

Ans Modul-Ende anhängen:

```python
def _install_linux(new_image: Path) -> None:
    """Ersetzt $APPIMAGE durch new_image und startet die neue Instanz.

    Voraussetzung: new_image liegt im SELBEN Verzeichnis wie $APPIMAGE
    (sonst ist os.replace nicht atomar — OSError: Invalid cross-device link).
    Die Verantwortung dafür liegt beim Caller (download_and_install).
    """
    appimage = os.environ.get("APPIMAGE")
    if not appimage:
        raise InstallError("Auto-Update funktioniert nur in der gepackten AppImage.")

    try:
        current_mode = os.stat(new_image).st_mode
        os.chmod(new_image, current_mode | _stat.S_IXUSR | _stat.S_IXGRP | _stat.S_IXOTH)
        os.replace(new_image, appimage)
    except OSError as e:
        raise InstallError(f"AppImage konnte nicht ersetzt werden: {e}") from e

    try:
        subprocess.Popen(
            [appimage],
            start_new_session=True,
            close_fds=True,
        )
    except OSError as e:
        raise InstallError("Neue AppImage konnte nicht gestartet werden.") from e
```

- [ ] **Step 4: Tests grün**

```powershell
pytest tests/test_installer.py -v
```

- [ ] **Step 5: Commit**

```powershell
git add src/update/installer.py tests/test_installer.py
git commit -m "feat(installer): _install_linux mit atomic replace und neustart"
```

---

### Task 2.6: `download_and_install`-Orchestrierung mit Tempfile-Platzierung (TDD)

**Kontext:** Bringt alle Bausteine zusammen. Wählt Plattform-Asset, legt Tempfile am richtigen Ort an (Windows: `%TEMP%`, Linux: `dirname($APPIMAGE)` — kritisch für `os.replace`-Atomarität), startet Download, verifiziert Hash, prüft Cancel ein letztes Mal vor Popen, dispatcht zu `_install_*`.

**Files:**
- Modify: `src/update/installer.py`
- Modify: `tests/test_installer.py`

- [ ] **Step 1: Failing Tests**

Am Dateiende anhängen:

```python
from src.update.installer import download_and_install
from src.update.release import Asset, Release


def _release_with_windows_asset(digest=None, size=0):
    return Release(
        version="2.0.0",
        html_url="https://example.com",
        body="",
        assets=(
            Asset(
                name="Zeiterfassung_Setup.exe",
                url="https://example.com/exe",
                digest=digest,
                size=size,
            ),
        ),
    )


class TestDownloadAndInstall:
    def test_happy_path_windows(self, tmp_path):
        release = _release_with_windows_asset(
            digest=_hash_for(b"fake-installer"),
            size=len(b"fake-installer"),
        )
        cancel = threading.Event()

        with patch("src.update.installer.platform.system", return_value="Windows"):
            with patch("src.update.installer.tempfile.NamedTemporaryFile") as nt:
                # tempfile soll in tmp_path landen, damit der Test es prüfen kann
                fake_path = tmp_path / "Zeiterfassung_Setup.exe"
                nt_handle = MagicMock()
                nt_handle.name = str(fake_path)
                nt.return_value.__enter__ = MagicMock(return_value=nt_handle)
                nt.return_value.__exit__ = MagicMock(return_value=False)
                with patch("src.update.installer.urlopen",
                           return_value=_fake_response(b"fake-installer")):
                    with patch("src.update.installer.subprocess.Popen") as popen:
                        download_and_install(release, lambda d, t: None, cancel)

        # tempfile.NamedTemporaryFile wurde aufgerufen mit delete=False und suffix=.exe
        _args, kwargs = nt.call_args
        assert kwargs.get("delete") is False
        assert kwargs.get("suffix") == ".exe"
        # Popen ist gerufen MIT dem korrekten Pfad (kein heimlicher Pfad-Refactor)
        popen_args, _popen_kwargs = popen.call_args
        assert popen_args[0][0] == str(fake_path)

    def test_no_asset_for_platform_raises(self):
        release = _release_with_windows_asset()
        cancel = threading.Event()
        # Auf Darwin gibt es kein passendes Asset
        with patch("src.update.installer.platform.system", return_value="Darwin"):
            with pytest.raises(InstallError, match="kein Installer"):
                download_and_install(release, lambda d, t: None, cancel)

    def test_hash_mismatch_does_not_call_popen(self, tmp_path):
        release = _release_with_windows_asset(
            digest="sha256:" + ("f" * 64),  # falscher Hash
            size=len(b"fake-installer"),
        )
        cancel = threading.Event()

        with patch("src.update.installer.platform.system", return_value="Windows"):
            fake_path = tmp_path / "Zeiterfassung_Setup.exe"
            with patch("src.update.installer.tempfile.NamedTemporaryFile") as nt:
                nt_handle = MagicMock(); nt_handle.name = str(fake_path)
                nt.return_value.__enter__ = MagicMock(return_value=nt_handle)
                nt.return_value.__exit__ = MagicMock(return_value=False)
                with patch("src.update.installer.urlopen",
                           return_value=_fake_response(b"fake-installer")):
                    with patch("src.update.installer.subprocess.Popen") as popen:
                        with pytest.raises(InstallError, match="Sicherheitsprüfung"):
                            download_and_install(release, lambda d, t: None, cancel)
        popen.assert_not_called()

    def test_cancel_after_hash_before_popen(self, tmp_path):
        """Cancel-Event wird gesetzt, NACHDEM Download+Hash durch sind, aber bevor Popen kommt.
        Verifiziert den 3a-Cancel-Check aus der Spec."""
        release = _release_with_windows_asset(
            digest=_hash_for(b"fake-installer"),
            size=len(b"fake-installer"),
        )
        cancel = threading.Event()

        # Trick: _verify_sha256 patchen, sodass es cancel setzt, dann normal returnt
        original_verify = _verify_sha256
        def verify_then_cancel(path, digest):
            original_verify(path, digest)
            cancel.set()

        with patch("src.update.installer.platform.system", return_value="Windows"):
            fake_path = tmp_path / "Zeiterfassung_Setup.exe"
            with patch("src.update.installer.tempfile.NamedTemporaryFile") as nt:
                nt_handle = MagicMock(); nt_handle.name = str(fake_path)
                nt.return_value.__enter__ = MagicMock(return_value=nt_handle)
                nt.return_value.__exit__ = MagicMock(return_value=False)
                with patch("src.update.installer.urlopen",
                           return_value=_fake_response(b"fake-installer")):
                    with patch("src.update.installer._verify_sha256", side_effect=verify_then_cancel):
                        with patch("src.update.installer.subprocess.Popen") as popen:
                            with pytest.raises(InstallError, match="abgebrochen"):
                                download_and_install(release, lambda d, t: None, cancel)
        popen.assert_not_called()

    def test_tempfile_dir_for_linux_is_appimage_parent(self, tmp_path):
        """Spec-kritisch: tempfile muss neben $APPIMAGE liegen, sonst zerbricht os.replace."""
        appimage = tmp_path / "Zeiterfassung.AppImage"
        appimage.write_bytes(b"old")
        release = Release(
            version="2.0.0", html_url="x", body="",
            assets=(Asset(
                name="Zeiterfassung-2.0.0-x86_64.AppImage",
                url="https://example.com/img",
                digest=_hash_for(b"new"),
                size=3,
            ),),
        )
        cancel = threading.Event()

        with patch("src.update.installer.platform.system", return_value="Linux"):
            with patch.dict(os.environ, {"APPIMAGE": str(appimage)}):
                with patch("src.update.installer.tempfile.NamedTemporaryFile") as nt:
                    fake_path = tmp_path / "fake.AppImage.tmp"
                    nt_handle = MagicMock(); nt_handle.name = str(fake_path)
                    nt.return_value.__enter__ = MagicMock(return_value=nt_handle)
                    nt.return_value.__exit__ = MagicMock(return_value=False)
                    with patch("src.update.installer.urlopen",
                               return_value=_fake_response(b"new")):
                        with patch("src.update.installer.subprocess.Popen"):
                            with patch("src.update.installer._install_linux"):
                                download_and_install(release, lambda d, t: None, cancel)

        _args, kwargs = nt.call_args
        assert kwargs.get("dir") == str(tmp_path), \
            f"tempfile.dir war {kwargs.get('dir')!r}, erwartet {str(tmp_path)!r}"
        assert kwargs.get("suffix") == ".AppImage"
```

- [ ] **Step 2: Tests laufen — müssen fehlschlagen**

```powershell
pytest tests/test_installer.py::TestDownloadAndInstall -v
```
Erwartet: `ImportError: cannot import name 'download_and_install'`.

- [ ] **Step 3: Implementation**

Imports oben in der bestehenden Import-Sektion ergänzen:

```python
import tempfile

from src.update.release import Release, pick_asset
```

(`Release` brauchen wir nur für den Type-Hint. Kein Zirkular-Risiko: `release.py` importiert nichts aus `installer.py`.)

`download_and_install` ans Modul-Ende anhängen:

```python
def download_and_install(
    release: Release,
    on_progress: Callable[[int, int], None],
    cancel_event: threading.Event,
) -> None:
    """Lädt das Plattform-Asset, prüft SHA256, startet den Installer.

    Blocking — vom Caller im Worker-Thread ausführen. Bei Erfolg ist der
    Installer als separater Prozess gestartet; der Caller muss anschließend
    die App beenden (root.destroy mit kleinem Delay, damit der Installer
    Zeit hat, den Restart-Manager-Lock anzufordern).

    Wirft InstallError mit nutzerlesbarer deutscher Message bei jedem Fehler.
    """
    system = platform.system()
    asset = pick_asset(release.assets, system, release.version)
    if asset is None:
        raise InstallError("Für diese Plattform ist kein Installer im Release.")

    # Plattform-Dispatch für tempfile-Verzeichnis und Suffix.
    if system == "Windows":
        tmp_dir = None  # %TEMP% (Default)
        suffix = ".exe"
        installer_fn = _install_windows
    elif system == "Linux":
        appimage = os.environ.get("APPIMAGE")
        if not appimage:
            raise InstallError("Auto-Update funktioniert nur in der gepackten AppImage.")
        tmp_dir = os.path.dirname(appimage)  # ZWINGEND, sonst kein atomic os.replace
        suffix = ".AppImage"
        installer_fn = _install_linux
    else:
        raise InstallError(f"Plattform {system} unterstützt kein Auto-Update.")

    with tempfile.NamedTemporaryFile(delete=False, dir=tmp_dir, suffix=suffix) as tmp:
        tmp_path = tmp.name

    try:
        _download(asset.url, tmp_path, asset.size, on_progress, cancel_event)
        _verify_sha256(tmp_path, asset.digest)

        # Letzter Cancel-Check direkt vor Popen — schließt das Race-Fenster
        # zwischen Hash-Erfolg und Installer-Start.
        if cancel_event.is_set():
            _cleanup(tmp_path)
            raise InstallError("Download abgebrochen.")

        installer_fn(tmp_path)
    except InstallError:
        # _download/_verify haben tmp bereits aufgeräumt (oder nicht, je nach Pfad).
        # _install_* werfen nach erfolgreichem Popen NICHT — bei Pre-Popen-Fehler
        # ist tmp_path noch unangefasst, also defensiv aufräumen.
        _cleanup(tmp_path)
        raise
```

Hinweis: `_cleanup` ist idempotent (`OSError` swallow) — doppelter Aufruf ist harmlos.

- [ ] **Step 4: Tests grün**

```powershell
pytest tests/test_installer.py -v
```
Erwartet: alle Tests grün — `TestCanAutoInstall`, `TestInstallError`, `TestVerifySha256`, `TestDownload`, `TestInstallWindows`, `TestInstallLinux`, `TestDownloadAndInstall`.

- [ ] **Step 5: `download_and_install` in `src/update/__init__.py` re-exportieren**

`from src.update.installer import ...`-Block erweitern:

```python
from src.update.installer import (
    InstallError,
    can_auto_install,
    download_and_install,
)
```

Und `__all__` ergänzen mit `"download_and_install"`.

- [ ] **Step 6: App-Smoke-Test**

```powershell
python -m src.main
```
Erwartet: kein ImportError. Fenster wieder schließen.

- [ ] **Step 7: Commit**

```powershell
git add src/update/ tests/test_installer.py
git commit -m "feat(installer): download_and_install orchestriert download + hash + dispatch"
```

---

**Ende Chunk 2.** Nächster Chunk: Tk-Dialog (`src/dialogs/update_dialog.py`), `ui.py`-Integration, `installer.iss`-Patches, Versions-Bump.

---

## Chunk 3: Dialog, UI-Integration, Installer-Skript, Release-Vorbereitung

Der letzte Chunk verbindet die pure Installer-Logik mit dem UI: ein neuer Modal-Dialog im bestehenden `src/dialogs/`-Stil, Banner-Click in `src/ui.py` ruft den Dialog, `installer.iss` bekommt den `WizardSilent`-Restart-Pfad, und Versions-Bump + Changelog für den Release-Workflow.

Theme-Konventionen aus den bestehenden Dialogen (`entry_dialog`, `send_dialog`): `tk.Toplevel`, `grab_set()` + `focus_set()`, `apply_app_icon`, `apply_dark_titlebar`, `disable_min_max`, `center_dialog_on_parent`, `bg=BG`, `FONT`/`FONT_BOLD`. Buttons via `primary_button` / `secondary_button`. Dialoge sind nicht-resizable.

---

### Task 3.1: Dialog-Skeleton mit State 1 (Confirmation)

**Kontext:** Modaler Dialog zeigt Versionsnummer, Changelog (release.body) als readonly Text-Widget mit Scrollbar, Buttons "Abbrechen" / "Jetzt installieren". Worker-Spawn und Progress kommen in Task 3.2.

**Files:**
- Create: `src/dialogs/update_dialog.py`

- [ ] **Step 1: Dialog-Modul anlegen**

```python
"""Modaler Dialog: Auto-Download und Install einer neuen App-Version.

State-Machine:
  STATE_CONFIRM   → Versionsinfo + Changelog + [Abbrechen | Jetzt installieren]
  STATE_DOWNLOAD  → Progressbar + Byte-Anzeige + [Abbrechen]
  STATE_ERROR     → Fehlertext + [Im Browser öffnen | Schließen]
                    (Hash-Mismatch: nur [Schließen])

Worker-Thread macht den Download + Install. Alle Tk-Updates aus dem Worker
laufen über root.after(0, ...) — analog zum bestehenden Update-Check
in src/ui.py.
"""

import logging
import threading
import tkinter as tk
import webbrowser
from tkinter import messagebox, ttk

from src.theme import (
    BG, FONT, FONT_BOLD, FONT_HEADER_SMALL, TEXT, TEXT_MUTED,
    apply_app_icon, apply_dark_titlebar, center_dialog_on_parent,
    disable_min_max, primary_button, secondary_button,
)
from src.update import (
    InstallError, IntegrityError, Release, download_and_install,
)

logger = logging.getLogger(__name__)


def show_update_dialog(parent, release: Release) -> None:
    """Öffnet den modalen Dialog. Blocking aus Aufrufer-Sicht.

    Bei erfolgreichem Install beendet sich die App selbst (root.destroy
    mit kleinem after-Delay, siehe Spec). Bei Fehler bleibt die App offen,
    Dialog zeigt Fehlertext + Browser-Fallback.
    """
    _UpdateDialog(parent, release).run()


class _UpdateDialog:
    """Zustand und Widgets eines einzelnen Update-Dialogs."""

    STATE_CONFIRM = "confirm"
    STATE_DOWNLOAD = "download"
    STATE_ERROR = "error"

    def __init__(self, parent, release: Release):
        self.parent = parent
        self.release = release
        self.dialog = None
        self.cancel_event = threading.Event()
        self.worker = None

    def run(self) -> None:
        self.dialog = tk.Toplevel(self.parent)
        self.dialog.title(f"Update auf Version {self.release.version}")
        self.dialog.resizable(False, False)
        self.dialog.configure(bg=BG)
        self.dialog.grab_set()
        self.dialog.focus_set()
        apply_app_icon(self.dialog)
        apply_dark_titlebar(self.dialog)
        disable_min_max(self.dialog)
        self.dialog.protocol("WM_DELETE_WINDOW", self._on_close_request)
        # Escape-Konvention aus 1.12.1 — alle Modal-Dialoge per Esc schließbar
        self.dialog.bind("<Escape>", lambda _e: self._on_close_request())

        self._render_confirm_state()
        center_dialog_on_parent(self.dialog, self.parent)

    # ---------- State 1: Confirmation ---------- #

    def _render_confirm_state(self):
        self._clear()

        tk.Label(
            self.dialog,
            text=f"Version {self.release.version} verfügbar",
            bg=BG, fg=TEXT, font=FONT_HEADER_SMALL,
        ).pack(padx=20, pady=(20, 8), anchor="w")

        tk.Label(
            self.dialog,
            text="Änderungen in dieser Version:",
            bg=BG, fg=TEXT_MUTED, font=FONT,
        ).pack(padx=20, pady=(0, 6), anchor="w")

        # Changelog: readonly Text-Widget mit Scrollbar.
        body_frame = tk.Frame(self.dialog, bg=BG)
        body_frame.pack(padx=20, pady=(0, 16), fill=tk.BOTH, expand=False)

        scrollbar = ttk.Scrollbar(body_frame, orient=tk.VERTICAL)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        text = tk.Text(
            body_frame,
            width=60, height=12,
            bg="#0f1525", fg=TEXT, font=FONT,
            wrap=tk.WORD, bd=0, relief=tk.FLAT,
            yscrollcommand=scrollbar.set,
        )
        text.insert("1.0", self.release.body or "(kein Changelog)")
        text.configure(state=tk.DISABLED)
        text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.config(command=text.yview)

        btn_frame = tk.Frame(self.dialog, bg=BG)
        btn_frame.pack(padx=20, pady=(0, 20), fill=tk.X)

        secondary_button(btn_frame, "Abbrechen", self._on_close_request).pack(side=tk.RIGHT, padx=(8, 0))
        primary_button(btn_frame, "Jetzt installieren", self._start_install).pack(side=tk.RIGHT)

    # ---------- Stubs (kommen in Task 3.2/3.3) ---------- #

    def _start_install(self):
        """Wird in Task 3.2 ausgefüllt."""
        raise NotImplementedError

    def _on_close_request(self):
        """Wird in Task 3.2 ausgefüllt — kümmert sich um WM_DELETE_WINDOW + Abbrechen."""
        self.dialog.destroy()

    def _clear(self):
        for child in self.dialog.winfo_children():
            child.destroy()
```

- [ ] **Step 2: Manueller Smoke-Test (ohne Auto-Install-Pfad)**

```powershell
python -m src.main
```

Im laufenden App-Fenster: in der Python-Konsole NICHT verfügbar (App läuft im GUI-Loop). Daher kein expliziter Test in diesem Schritt — Dialog wird in Task 4.1 über den Banner-Klick erreicht und dort manuell verifiziert. Hier reicht es, dass `python -m src.main` ohne `ImportError` startet.

- [ ] **Step 3: Commit**

```powershell
git add src/dialogs/update_dialog.py
git commit -m "feat(dialog): update-dialog-skeleton mit confirm-state (changelog + buttons)"
```

---

### Task 3.2: Worker-Spawn, State 2 (Progress), Cancel-Handling

**Kontext:** Klick auf "Jetzt installieren" startet den Worker-Thread und wechselt den Dialog in State 2 (Progressbar + Byte-Anzeige + Abbrechen-Button). Cancel-Klick und WM_DELETE_WINDOW setzen das `cancel_event` und schließen den Dialog erst, wenn der Worker zurück ist.

**Files:**
- Modify: `src/dialogs/update_dialog.py`

- [ ] **Step 1: `_start_install` und State-2-Render implementieren**

Im Dialog-Modul die Stubs `_start_install` und `_on_close_request` ersetzen, und neue Helper hinzufügen:

```python
    # ---------- State 1 → State 2 Transition ---------- #

    def _start_install(self):
        self._render_download_state()
        self.worker = threading.Thread(
            target=self._worker_body,
            daemon=True,
            name="update-installer",
        )
        self.worker.start()

    # ---------- State 2: Download Progress ---------- #

    def _render_download_state(self):
        self._clear()

        tk.Label(
            self.dialog,
            text=f"Lade Version {self.release.version}…",
            bg=BG, fg=TEXT, font=FONT_HEADER_SMALL,
        ).pack(padx=20, pady=(20, 16), anchor="w")

        self.progress = ttk.Progressbar(
            self.dialog, orient=tk.HORIZONTAL, length=500, mode="determinate",
        )
        self.progress.pack(padx=20, pady=(0, 8), fill=tk.X)

        self.progress_label = tk.Label(
            self.dialog, text="0 KiB / ? KiB",
            bg=BG, fg=TEXT_MUTED, font=FONT,
        )
        self.progress_label.pack(padx=20, pady=(0, 16), anchor="w")

        btn_frame = tk.Frame(self.dialog, bg=BG)
        btn_frame.pack(padx=20, pady=(0, 20), fill=tk.X)
        secondary_button(btn_frame, "Abbrechen", self._on_close_request).pack(side=tk.RIGHT)

    # ---------- Worker (im Daemon-Thread) ---------- #

    def _worker_body(self):
        try:
            download_and_install(
                self.release,
                on_progress=self._on_progress_from_worker,
                cancel_event=self.cancel_event,
            )
            self._post_to_ui(self._on_install_success)
        except InstallError as exc:
            self._post_to_ui(lambda: self._on_install_error(exc))
        except Exception:
            logger.exception("Unerwarteter Fehler im Update-Worker")
            self._post_to_ui(lambda: self._on_install_error(
                InstallError("Unerwarteter Fehler. Bitte erneut versuchen.")
            ))

    def _on_progress_from_worker(self, done: int, total: int):
        self._post_to_ui(lambda: self._update_progress(done, total))

    def _post_to_ui(self, fn):
        """Worker → UI-Thread via root.after(0, ...). Schutz gegen
        bereits-zerstörten Dialog (z.B. wenn App geschlossen wurde)."""
        try:
            self.dialog.after(0, fn)
        except (tk.TclError, RuntimeError):
            pass

    def _update_progress(self, done: int, total: int):
        if not self.dialog.winfo_exists():
            return
        if total > 0:
            self.progress.configure(mode="determinate", maximum=total, value=done)
            self.progress_label.configure(
                text=f"{done // 1024} KiB / {total // 1024} KiB"
            )
        else:
            # Total unbekannt — Indeterminate-Mode mit Byte-Counter
            if self.progress["mode"] != "indeterminate":
                self.progress.configure(mode="indeterminate")
                self.progress.start(50)
            self.progress_label.configure(text=f"{done // 1024} KiB geladen")

    # ---------- Cancel / Close ---------- #

    def _on_close_request(self):
        """WM_DELETE_WINDOW oder Abbrechen-Klick.
        Identisch behandelt: cancel_event setzen, Worker zurückwarten, Dialog schließen.

        Kein Hard-Timeout — der _download-Chunk-Loop reagiert pro 8-KiB-Chunk
        auf cancel_event, was praktisch <100 ms ist. Sollte der Worker
        hängen (z.B. blockierender Popen-Call nach Hash-Check), bleibt der
        Dialog offen und der User kann die ganze App schließen (Worker
        ist Daemon-Thread, wird mit dem Prozess beendet)."""
        self.cancel_event.set()
        if self.worker is not None and self.worker.is_alive():
            self.dialog.after(100, self._poll_worker_then_close)
        else:
            self.dialog.destroy()

    def _poll_worker_then_close(self):
        if self.worker is not None and self.worker.is_alive():
            self.dialog.after(100, self._poll_worker_then_close)
            return
        if self.dialog.winfo_exists():
            self.dialog.destroy()
```

- [ ] **Step 2: Manueller Smoke-Test**

```powershell
python -m src.main
```
Erwartet: kein ImportError. Dialog ist noch nicht über das UI erreichbar (Banner-Anbindung kommt in Task 4.1).

- [ ] **Step 3: Commit**

```powershell
git add src/dialogs/update_dialog.py
git commit -m "feat(dialog): worker-spawn, download-state mit progressbar und cancel"
```

---

### Task 3.3: Erfolgs- und Fehlerpfade (State 3 + Self-Destruct)

**Kontext:** Bei Erfolg: App beenden mit `after(300, destroy)` — Delay für Restart-Manager-Lock auf Windows. Bei Fehler: State 3 mit messagebox.showerror + Browser-Fallback. Hash-Mismatch-Spezialfall: kein Browser-Fallback.

**Files:**
- Modify: `src/dialogs/update_dialog.py`

- [ ] **Step 1: Erfolgs- und Fehler-Handler implementieren**

Im Dialog-Modul anhängen:

```python
    # ---------- Erfolg / Fehler ---------- #

    def _on_install_success(self):
        """Installer wurde gestartet — App muss sich beenden.

        300 ms Delay: gibt dem Installer (Inno Setup auf Windows) Zeit,
        den Restart-Manager-Lock anzufordern. Ohne Delay würde die App
        sich beenden, bevor der Installer den Lock-Request stellt, und
        die zweite [Run]-Zeile mit Check: WizardSilent würde ins Leere
        laufen.
        """
        if not self.dialog.winfo_exists():
            return
        root = self.parent.winfo_toplevel()
        root.after(300, root.destroy)

    def _on_install_error(self, exc: InstallError):
        if not self.dialog.winfo_exists():
            return

        # Robuster als String-Match: dedizierte Subklasse für Hash-Mismatch.
        # Spec: Hash-Mismatch hat KEINEN Browser-Fallback — Nutzer nicht auf
        # potenziell kompromittierten Pfad lenken.
        is_hash_error = isinstance(exc, IntegrityError)

        messagebox.showerror(
            "Update fehlgeschlagen",
            str(exc),
            parent=self.dialog,
        )

        self._render_error_state(allow_browser_fallback=not is_hash_error)

    # ---------- State 3: Error ---------- #

    def _render_error_state(self, allow_browser_fallback: bool):
        self._clear()

        tk.Label(
            self.dialog,
            text=f"Update auf {self.release.version} fehlgeschlagen",
            bg=BG, fg=TEXT, font=FONT_HEADER_SMALL,
        ).pack(padx=20, pady=(20, 16), anchor="w")

        info = (
            "Die automatische Installation war nicht möglich."
            if allow_browser_fallback else
            "Aus Sicherheitsgründen wird kein Browser-Fallback angeboten. "
            "Bitte später erneut versuchen."
        )
        tk.Label(
            self.dialog, text=info,
            bg=BG, fg=TEXT_MUTED, font=FONT,
            wraplength=500, justify=tk.LEFT,
        ).pack(padx=20, pady=(0, 16), anchor="w")

        btn_frame = tk.Frame(self.dialog, bg=BG)
        btn_frame.pack(padx=20, pady=(0, 20), fill=tk.X)

        secondary_button(btn_frame, "Schließen", self.dialog.destroy).pack(side=tk.RIGHT, padx=(8, 0))

        if allow_browser_fallback:
            primary_button(
                btn_frame, "Im Browser öffnen", self._open_in_browser,
            ).pack(side=tk.RIGHT)

    def _open_in_browser(self):
        webbrowser.open(self.release.html_url)
        if self.dialog.winfo_exists():
            self.dialog.destroy()
```

- [ ] **Step 2: Manueller Smoke-Test**

```powershell
python -m src.main
```
Erwartet: kein ImportError.

- [ ] **Step 3: Commit**

```powershell
git add src/dialogs/update_dialog.py
git commit -m "feat(dialog): erfolgs- und fehlerpfade (after-delay + browser-fallback)"
```

---

### Task 4.1: `ui.py` — Banner-Click ruft `show_update_dialog`

**Kontext:** `_open_update_download` in `src/ui.py` (Zeilen 307-311 nach Chunk 1) ist heute eine 4-Zeilen-Methode mit `pick_asset` + `webbrowser.open`. Jetzt wird sie zum Dispatcher: wenn `can_auto_install()` → Dialog, sonst Browser wie bisher.

**Files:**
- Modify: `src/ui.py:21-28` (Import), `src/ui.py:307-311` (Methode)

- [ ] **Step 1: Imports erweitern**

In `src/ui.py` den Import-Block ergänzen — `can_auto_install` aus `src.update` und `show_update_dialog` aus dem neuen Dialog-Modul:

alt (nach Chunk 1):
```python
from src.update import (
    check_latest_release,
    is_newer,
    pick_asset,
    should_check_today,
    today_iso,
    Release,
)
```

neu:
```python
from src.update import (
    can_auto_install,
    check_latest_release,
    is_newer,
    pick_asset,
    should_check_today,
    today_iso,
    Release,
)
from src.dialogs.update_dialog import show_update_dialog
```

Hinweis: `pick_asset` wird in `_open_update_download` nur noch im Browser-Fallback-Pfad genutzt — daher behält den Import.

- [ ] **Step 2: `_open_update_download` umbauen**

In `src/ui.py:307-311` (Zeilennummern können nach Chunk 1 leicht verschoben sein; die Methode ist eindeutig identifizierbar):

alt:
```python
def _open_update_download(self, release: "Release"):
    asset = pick_asset(release.assets, platform.system(), release.version)
    url = asset.url if asset else release.html_url
    webbrowser.open(url)
```

neu:
```python
def _open_update_download(self, release: "Release"):
    """Banner-Klick: Auto-Install-Dialog wenn möglich, sonst Browser.

    can_auto_install() kapselt die Plattform-/Frozen-/AppImage-Logik —
    auf macOS, im Repo-Modus oder ohne $APPIMAGE landet der Nutzer im
    Browser auf der Release-Seite (unverändertes Verhalten vor Auto-Update).
    """
    if can_auto_install():
        show_update_dialog(self.root, release)
        return
    asset = pick_asset(release.assets, platform.system(), release.version)
    url = asset.url if asset else release.html_url
    webbrowser.open(url)
```

- [ ] **Step 3: Bestehende Tests laufen lassen**

```powershell
pytest -v
```
Erwartet: alles grün — Release-Tests, Installer-Tests, alle anderen Tests.

- [ ] **Step 4: Manueller UI-Smoke-Test**

```powershell
python -m src.main
```

Erwartet: App startet. Banner kann manuell getestet werden, indem temporär in `src/version.py` eine niedrigere Version eingetragen wird (z.B. `VERSION = "0.0.1"`), `last_update_check_at` aus den Settings entfernt wird, und die App neu gestartet wird. Beim Erscheinen des Banners → Klick auf "Download" → Dialog öffnet sich mit Versionsnummer und Changelog.

**Im Repo-Modus** (kein `sys.frozen`): `can_auto_install()` liefert `False` → Browser öffnet sich (alter Pfad). Das ist erwartetes Verhalten — der Auto-Install-Dialog wird nur im gebauten Artefakt sichtbar.

Vor Commit: `src/version.py` wieder auf den echten Wert zurücksetzen.

- [ ] **Step 5: Commit**

```powershell
git add src/ui.py
git commit -m "feat(ui): update-banner ruft auto-install-dialog wenn plattform unterstützt"
```

---

### Task 4.2: `installer.iss` — Silent-Restart und CloseApplications=force

**Kontext:** Bisheriger Stand (`installer.iss` Zeilen 1-40):
- `[Setup]`: kein `CloseApplications`, kein `RestartApplications` → Inno-Standard-Verhalten (interaktiv: Frage stellen).
- `[Run]`: eine Zeile mit `Flags: nowait postinstall skipifsilent` → läuft NUR im interaktiven Modus.

Nach Patch:
- `CloseApplications=force` + `RestartApplications=no` → im Silent-Modus die laufende Exe ohne Dialog killen, Restart kontrollieren wir selbst.
- Zwei `[Run]`-Zeilen: erste mit `skipifsilent` (interaktiver Postinstall-Checkbox), zweite mit `Check: WizardSilent` (nur Silent-Auto-Restart). **Mutual exclusive** — sonst Double-Launch im interaktiven Modus.

**Files:**
- Modify: `installer.iss:1-15` (`[Setup]`-Block), `installer.iss:38-39` (`[Run]`-Block)

- [ ] **Step 1: `[Setup]`-Block erweitern**

In `installer.iss` nach Zeile 15 (`PrivilegesRequiredOverridesAllowed=dialog`) und vor Zeile 16 (`WizardStyle=modern`) zwei Zeilen einfügen, damit der Privileges-Block zusammenbleibt:

```ini
CloseApplications=force
RestartApplications=no
```

- [ ] **Step 2: `[Run]`-Block durch zwei Zeilen ersetzen**

Aktuelle Zeile 39 (`Filename: "{app}\Zeiterfassung.exe"; Description: ...`) bleibt unverändert. Direkt danach eine zweite Zeile einfügen:

```ini
Filename: "{app}\Zeiterfassung.exe"; Flags: nowait runasoriginaluser; Check: WizardSilent
```

Resultat-Block (`[Run]`-Sektion):
```ini
[Run]
Filename: "{app}\Zeiterfassung.exe"; Description: "Zeiterfassung jetzt starten"; Flags: nowait postinstall skipifsilent
Filename: "{app}\Zeiterfassung.exe"; Flags: nowait runasoriginaluser; Check: WizardSilent
```

- [ ] **Step 3: Verifikation per Inno-Setup-Build (Windows-only)**

```powershell
python build.py
```
Erwartet: PyInstaller läuft durch + Inno Setup compiles ohne Fehler. Ausgabe-Pfad: `dist/Zeiterfassung_Setup.exe`.

Wenn die Linux-/macOS-CI das durchläuft, ist diese Step im CI ein No-Op (build.py dispatched plattformabhängig).

Wenn lokal kein Inno Setup installiert ist: Hinweis-Output "Inno Setup not found ... skipping installer" — Step trotzdem als erledigt markieren (Verifikation passiert dann beim Release-Build im CI).

- [ ] **Step 4: Commit**

```powershell
git add installer.iss
git commit -m "build(installer): closeapplications=force + zweite [run]-zeile für silent-restart"
```

---

### Task 4.3: Versions-Bump + CHANGELOG

**Kontext:** Der Release-Workflow (`.github/workflows/release.yml`) zieht die Version aus `src/version.py` und löst auf einen `release:minor`-Label-Trigger. Aktuelle Version (Stand 2026-05-28): `1.12.1`. Neuer Wert: `1.13.0` (neues Feature → minor).

**Files:**
- Modify: `src/version.py`
- Modify: `CHANGELOG.md`

- [ ] **Step 1: `src/version.py` auf `1.13.0` setzen**

Datei-Inhalt komplett ersetzen:

```python
VERSION = "1.13.0"
```

- [ ] **Step 2: `CHANGELOG.md` ergänzen**

Direkt nach Zeile 2 (`# Changelog`) und vor Zeile 3 (`## 1.12.1 — 2026-05-28`) einen neuen Block einfügen:

```markdown
## 1.13.0 — 2026-05-28

### Hinzugefügt
- Klick auf "Download" im Update-Banner installiert die neue Version
  jetzt direkt (Windows + Linux). Dialog zeigt Changelog vorab und
  prüft den Download per SHA256 (zweite Verteidigungslinie nach TLS).
  Bei Erfolg startet die neue Version automatisch.
- macOS bleibt vorerst beim "Im Browser öffnen"-Verhalten.

```

- [ ] **Step 3: Smoke-Test**

```powershell
python -m src.main
```
Erwartet: App startet mit Version `1.13.0`.

- [ ] **Step 4: Commit**

```powershell
git add src/version.py CHANGELOG.md
git commit -m "release: v1.13.0 — auto-update install per klick (windows + linux)"
```

---

### Task 5: Manuelle Verifikations-Checkliste (vor PR-Merge)

**Kontext:** Spec definiert eine Verifikations-Checkliste für den PR-Body, weil Tk-Dialoge und subprocess-Pfade nicht unit-testbar sind. Diese Checkliste wird Teil des PR-Bodies.

**Files:** keine — reiner PR-Body-Inhalt.

- [ ] **Step 1: PR-Body als Vorlage notieren**

Wenn der PR über `gh pr create` erstellt wird, folgenden Body verwenden (kopierbar):

```markdown
## Summary
- Klick auf "Download" im Update-Banner lädt das neue Release herunter und installiert es direkt (Windows: Inno Setup silent, Linux: AppImage-Replace).
- SHA256-Verifikation gegen GitHub-API-Digest als zweite Verteidigungslinie nach TLS.
- macOS bleibt unverändert (Browser-Fallback).
- Spec: `docs/superpowers/specs/2026-05-28-auto-update-design.md`
- Plan: `docs/superpowers/plans/2026-05-28-auto-update.md`

## Test plan
- [ ] `pytest` lokal komplett grün
- [ ] **Windows**: Installer baut (`python build.py`), Banner erscheint nach simuliertem alten `src/version.py`, "Jetzt installieren" → App schließt → neue Version startet automatisch
- [ ] **Windows**: Kein UAC-Prompt während Silent-Install (Test in `%LOCALAPPDATA%\Programs\Zeiterfassung\`)
- [ ] **Linux**: Gleiche Probe in einer gepackten AppImage (nicht Repo-Modus)
- [ ] **Beide**: Hash-Mismatch (per Hand Temp-Datei zwischen Download und Install korrumpieren) → Sicherheitsdialog ohne Browser-Fallback
- [ ] **Beide**: Netzwerk-Abbruch (Wifi aus während Download) → Fehlerdialog mit Browser-Fallback
- [ ] **Beide**: Abbrechen-Button während Download → Dialog kehrt zurück, Temp-Datei weg
- [ ] **Beide**: Fenster-X während Download = identisches Verhalten wie Abbrechen
- [ ] **Windows**: Interaktiver Setup-Wizard (`python build.py` lokal, manuell durchklicken) → App startet **nur einmal** am Ende (kein Double-Launch durch `WizardSilent`-Fix)
- [ ] **Linux Repo-Modus** (`python -m src.main`): Klick auf "Download" öffnet weiterhin Browser (kein Dialog)
- [ ] **macOS**: Verhalten unverändert (Browser öffnet sich)

## Label
`release:minor` setzen — Workflow liest Version aus `src/version.py = 1.13.0`.
```

- [ ] **Step 2: Final-Verifikation aller Tests**

```powershell
pytest -v
```
Erwartet: alles grün.

- [ ] **Step 3: PR erstellen**

Verwende `commit-commands:commit-push-pr` oder manuell `gh pr create` mit obigem Body. Branch sollte ein Feature-Branch sein — nicht direkt nach `master` (Branch Protection laut CLAUDE.md).

---

**Ende Chunk 3. Plan abgeschlossen.** Nach Merge des PR triggert der Workflow `release.yml` den Release-Build (Inno Setup auf Windows, create-dmg auf macOS, appimagetool auf Linux), publiziert das Release auf GitHub, und alle installierten App-Instanzen sehen beim nächsten Update-Check (täglich) das neue Release — diesmal mit Auto-Install.
