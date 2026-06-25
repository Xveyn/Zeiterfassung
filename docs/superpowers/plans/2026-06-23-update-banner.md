# UpdateBanner-Extraktion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Den Update-Banner-Cluster aus `src/ui.py` in eine eigene Komponente `UpdateBanner` (`src/update_banner.py`) auslagern — dritter Schritt der ui.py-Entflechtung (#49).

**Architecture:** Neues Tk-nutzendes Modul (kein `src.ui`-Import → kein Circular-Import) mit der Klasse `UpdateBanner`, die den Banner-Frame-Lebenszyklus und die Anzeige-/Dismiss-/Download-Logik kapselt. `App` konstruiert die Komponente und übergibt die `check_update`-Ergebnisse an sie. Verhalten unverändert.

**Tech Stack:** Python 3, Tkinter, pytest.

## Global Constraints

- Verhalten unverändert (reiner Refactor) — Strings/Farben/Fonts byte-identisch; UI manuell verifiziert (mind. App-Start ohne Fehler; Banner-Pfad ist nur bei verfügbarem Update sichtbar).
- `src/update_banner.py`: module-level `import tkinter`/`src.theme`/`src.tooltip`/`src.updater` ist OK; **kein** `src.ui`-Import.
- Datum intern ISO (`today_iso`), UI deutsch — hier nicht berührt.
- Lint: `python -m ruff check .` (ganzes Repo) grün. Tests: `python -m pytest` grün.
- Commit-Messages enden mit `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`.
- PowerShell 5.1: kein `&&`; `;` oder `if ($?) { }`. Match Edits **by content**, nicht by Zeilennummer (`~` = ungefähr).

---

### Task 1: `src/update_banner.py` + Tests

**Files:**
- Create: `src/update_banner.py`
- Test: `tests/test_update_banner.py` (neu)

**Interfaces:**
- Produces: `UpdateBanner(root, settings, get_anchor)` mit `handle_check_result(release, newer)`, `_show(release)`, `_open_download(release)`, `_dismiss(version)`. `get_anchor()` liefert das Widget, vor dem der Banner gepackt wird.

- [ ] **Step 1: Failing tests schreiben**

`tests/test_update_banner.py`:
```python
"""UpdateBanner: Entscheidungslogik (handle_check_result) und Download-URL-Wahl
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


def test_handle_check_result_persists_check_date(monkeypatch):
    monkeypatch.setattr(ub, "today_iso", lambda: "2026-06-23")
    s = _FakeSettings()
    b = _banner(s)
    b.handle_check_result(_release(), newer=False)
    assert s.get("last_update_check_at") == "2026-06-23"


def test_handle_check_result_not_newer_does_not_show(monkeypatch):
    monkeypatch.setattr(ub, "today_iso", lambda: "2026-06-23")
    b = _banner(_FakeSettings())
    b.handle_check_result(_release(), newer=False)
    b._show.assert_not_called()


def test_handle_check_result_dismissed_version_does_not_show(monkeypatch):
    monkeypatch.setattr(ub, "today_iso", lambda: "2026-06-23")
    b = _banner(_FakeSettings(dismissed_version="1.2.0"))
    b.handle_check_result(_release(version="1.2.0"), newer=True)
    b._show.assert_not_called()


def test_handle_check_result_new_version_shows(monkeypatch):
    monkeypatch.setattr(ub, "today_iso", lambda: "2026-06-23")
    b = _banner(_FakeSettings(dismissed_version="1.1.0"))
    rel = _release(version="1.2.0")
    b.handle_check_result(rel, newer=True)
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
```

- [ ] **Step 2: Tests failen sehen**

Run: `python -m pytest tests/test_update_banner.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.update_banner'`.

- [ ] **Step 3: Modul implementieren**

`src/update_banner.py`:
```python
"""GitHub-Release-Hinweis als Banner über dem Kalender (anzeigen, Download
öffnen, ausblenden). Eigenständig herausgelöst aus der App (#49).

Tk-nutzend, aber ohne src.ui-Import (kein Circular-Import). Der Pack-Anker
(App.grid_container) wird lazy über get_anchor gelesen, weil er erst nach dem
Grid-Build existiert."""

import platform
import tkinter as tk
import webbrowser

from src.theme import ACCENT, ACCENT_HOVER, FONT_BOLD, label_button
from src.tooltip import attach_tooltip
from src.updater import pick_asset_url, today_iso


class UpdateBanner:
    def __init__(self, root, settings, get_anchor):
        self._root = root
        self._settings = settings
        self._get_anchor = get_anchor    # lambda: App.grid_container
        self._banner = None              # Frame oder None (None = nicht sichtbar)

    def handle_check_result(self, release, newer):
        """Läuft im UI-Thread (on_result von BackgroundTaskRunner.check_update).
        Persistiert den Check-Stand und zeigt ggf. den Banner. `newer` ist bereits
        im Worker ausgewertet, damit hier keine ungeschützte Logik im Tk-Event-
        Loop läuft."""
        self._settings.set("last_update_check_at", today_iso())
        if not newer:
            return
        if release.version == self._settings.get("dismissed_version"):
            return
        self._show(release)

    def _show(self, release):
        if self._banner is not None:
            return
        self._banner = tk.Frame(self._root, bg=ACCENT)
        self._banner.pack(
            before=self._get_anchor(), fill=tk.X, padx=10, pady=(5, 0),
        )

        tk.Label(
            self._banner,
            text=f"Version {release.version} verfügbar",
            bg=ACCENT, fg="#ffffff", font=FONT_BOLD,
        ).pack(side=tk.LEFT, padx=10, pady=6)

        dismiss_btn = label_button(
            self._banner, "✕",
            lambda: self._dismiss(release.version),
            bg=ACCENT, fg="#ffffff",
            hover_bg=ACCENT_HOVER, hover_fg="#ffffff",
            font=FONT_BOLD,
            label_padx=8,
        )
        dismiss_btn.pack(side=tk.RIGHT, padx=(0, 4), pady=6)
        attach_tooltip(dismiss_btn, "Diese Version ausblenden")

        label_button(
            self._banner, "Download",
            lambda: self._open_download(release),
            bg="#ffffff", fg=ACCENT,
            hover_bg="#f0f0f0", hover_fg=ACCENT_HOVER,
            font=FONT_BOLD,
            label_padx=14, label_pady=2,
        ).pack(side=tk.RIGHT, padx=8, pady=4)

    def _open_download(self, release):
        url = pick_asset_url(
            release.assets, platform.system(), release.version,
        ) or release.html_url
        webbrowser.open(url)

    def _dismiss(self, version):
        self._settings.set("dismissed_version", version)
        if self._banner is not None:
            self._banner.destroy()
            self._banner = None
```

- [ ] **Step 4: Tests grün + Lint + Import-Smoke**

Run:
```
python -m pytest tests/test_update_banner.py -q
python -m ruff check src/update_banner.py tests/test_update_banner.py
python -c "import src.update_banner"
```
Expected: 6 Tests PASS; Lint sauber; Import ohne Fehler.

- [ ] **Step 5: Commit**

```
git add src/update_banner.py tests/test_update_banner.py
git commit -m "feat(ui): UpdateBanner-Komponente fuer Release-Hinweis (#49)"
```

---

### Task 2: `App` verdrahten, alte Methoden + Imports entfernen

**Files:**
- Modify: `src/ui.py` (`__init__`-Wiring; vier Methoden entfernen; zwei Import-Statements entfernen)

**Interfaces:**
- Consumes: `UpdateBanner` (Task 1).

- [ ] **Step 1: Import ergänzen**

In `src/ui.py` bei den `from src...`-Imports ergänzen:
```python
from src.update_banner import UpdateBanner
```

- [ ] **Step 2: `__init__`-Wiring**

In `src/ui.py` `__init__`:

(a) Die Zeile (~174) `self._update_banner = None` ersetzen durch:
```python
        self._update_banner = UpdateBanner(
            self.root, self.settings, lambda: self.grid_container)
```

(b) Die direkt folgende Zeile (~175)
```python
        self._bg.check_update(on_result=self._handle_update_check_result)
```
ersetzen durch:
```python
        self._bg.check_update(on_result=self._update_banner.handle_check_result)
```
(Reihenfolge bleibt: `self._update_banner` wird vor `check_update` konstruiert.)

- [ ] **Step 3: Vier Methoden entfernen**

In `src/ui.py` die Methoden `_handle_update_check_result` (~211-222), `_show_update_banner` (~224-256), `_open_update_download` (~258-262) und `_dismiss_update_banner` (~264-268) **komplett löschen**.

- [ ] **Step 4: Ungenutzte Imports entfernen**

`webbrowser`, `pick_asset_url`, `today_iso`, `Release` werden in `ui.py` nur noch von den gelöschten Methoden genutzt. Entfernen:
- `import webbrowser` (~Zeile 11) löschen.
- Den gesamten Block (~20-24)
  ```python
  from src.updater import (
      pick_asset_url,
      today_iso,
      Release,
  )
  ```
  löschen.

Per Lint (F401) bestätigen, dass danach nichts Verbliebenes diese Namen referenziert; falls doch eine Stelle einen davon noch nutzt, diesen einen Namen behalten.

- [ ] **Step 5: Grep-Kontrolle, Lint, volle Suite, Import-Smoke**

Run:
```
python -m ruff check .
python -m pytest -q
python -c "import src.ui"
python -c "import src.update_banner"
```
Grep-Kontrolle in `src/`: **kein** `_handle_update_check_result`, `_show_update_banner`, `_open_update_download`, `_dismiss_update_banner` mehr; **kein** `webbrowser` / `pick_asset_url` / `today_iso` / `Release` mehr in `src/ui.py`.
Expected: Lint sauber; volle Suite grün (unveränderte Zahl + Task-1-Tests); beide Import-Smokes ohne Fehler.

- [ ] **Step 6: Manuelle AC-Verifikation** *(führt der Controller aus, nicht der Implementer)*

`python -m src.main` starten und prüfen: Start ohne Fehler. (Der Banner erscheint nur bei verfügbarem Update + max. 1×/Tag — der Start-Smoke deckt die Konstruktion/Verdrahtung ab.)

- [ ] **Step 7: Commit**

```
git add src/ui.py
git commit -m "refactor(ui): App an UpdateBanner verdrahten, alte Methoden entfernen (#49)"
```

---

## Self-Review

**Spec coverage:**
- Modul `UpdateBanner` (Konstruktor, handle_check_result, _show, _open_download, _dismiss): Task 1. ✓
- App-Wiring (Konstruktion, check_update-Umbiegung, 4 Methoden + 2 Imports raus): Task 2. ✓
- Tests (Entscheidungslogik + URL-Fallback): Task 1. ✓
- AC manuell: Task 2 Step 6. ✓

**Type-Konsistenz:** `UpdateBanner(root, settings, get_anchor)`, `handle_check_result(release, newer)`, `_show(release)`, `_open_download(release)`, `_dismiss(version)` — über beide Tasks konsistent; `on_result=self._update_banner.handle_check_result` passt zur `check_update(on_result)`-Signatur (`on_result(release, newer)`).

**Platzhalter:** keine.

**Offene Risiken:**
- `self._update_banner` wechselt die Bedeutung (Frame → Komponente); alle alten Frame-Zugriffe (`is not None`, `.destroy()`) lagen ausschließlich in den entfernten Methoden — keine weiteren Stellen. Per Grep abgesichert (Task 2 Step 5).
- Import-Trim per F401 abgesichert (Task 2 Step 4-5).
