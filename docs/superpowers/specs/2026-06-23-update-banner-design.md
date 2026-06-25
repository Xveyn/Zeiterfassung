# Design: ui.py entflechten — UpdateBanner

**Issue:** #49 (ui.py God-Object entflechten), **dritter Extraktions-Schritt** nach
`BackgroundTaskRunner` (#70) und `SyncOrchestrator` (#71).
**Branch:** `refactor/ui-update-banner`, gestackt auf `refactor/ui-sync-orchestrator` (#71).

**Leitprinzip:** Verhalten unverändert. Die kleine, eigenständige Update-Banner-
Verantwortlichkeit (GitHub-Release-Hinweis: anzeigen, Download öffnen, ausblenden) aus
`App` in eine eigene Komponente `UpdateBanner` ziehen.

## Ausgangslage

`src/ui.py` ist nach #71 bei ~1211 Zeilen. Der Update-Banner-Cluster (~60 Zeilen) ist sehr
gut abgegrenzt:

- `_handle_update_check_result(release, newer)` — persistiert `last_update_check_at`,
  zeigt den Banner falls neuer + nicht ausgeblendet.
- `_show_update_banner(release)` — baut den Banner-Frame (Version-Label, Download-Button,
  ✕-Dismiss), gepackt `before=self.grid_container`.
- `_open_update_download(release)` — wählt die Asset-URL (oder `html_url`-Fallback) und
  öffnet sie im Browser.
- `_dismiss_update_banner(version)` — merkt die ausgeblendete Version, zerstört den Frame.

Kopplung: `self.root` (Parent des Banner-Frames), `self.grid_container` (Pack-Anker — in
`_build_grid` erzeugt), `self.settings` (`last_update_check_at`, `dismissed_version`), der
Banner-Frame-Ref `self._update_banner`, sowie `today_iso`, `pick_asset_url` (aus
`src.updater`), `webbrowser`, `platform`, Theme (`ACCENT`, `ACCENT_HOVER`, `FONT_BOLD`,
`label_button`) und `attach_tooltip`.

Aufrufer: `self._bg.check_update(on_result=self._handle_update_check_result)` in `__init__`;
`self._update_banner = None` initialisiert dort den Frame-Ref.

## Neues Modul `src/update_banner.py`

Tk-nutzend, aber **kein** `src.ui`-Import → kein Circular-Import. Module-Level-Imports:
`tkinter as tk`, `webbrowser`, `platform`, `from src.theme import ACCENT, ACCENT_HOVER,
FONT_BOLD, label_button`, `from src.tooltip import attach_tooltip`, `from src.updater import
pick_asset_url, today_iso`.

```python
class UpdateBanner:
    """GitHub-Release-Hinweis als Banner über dem Kalender. Hält den Frame-
    Lebenszyklus; der Pack-Anker (App.grid_container) wird lazy über get_anchor
    gelesen, da er erst nach dem Grid-Build existiert."""

    def __init__(self, root, settings, get_anchor):
        self._root = root
        self._settings = settings
        self._get_anchor = get_anchor    # lambda: App.grid_container
        self._banner = None              # Frame oder None (None = nicht sichtbar)

    def handle_check_result(self, release, newer):
        """Läuft im UI-Thread (on_result von BackgroundTaskRunner.check_update).
        Persistiert den Check-Stand und zeigt ggf. den Banner. `newer` ist bereits
        im Worker ausgewertet."""
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
        self._banner.pack(before=self._get_anchor(), fill=tk.X, padx=10, pady=(5, 0))
        # Version-Label (links), Download-Button + ✕-Dismiss (rechts) — verbatim
        # aus dem bisherigen _show_update_banner, inkl. Tooltip am ✕.

    def _open_download(self, release):
        url = pick_asset_url(
            release.assets, platform.system(), release.version) or release.html_url
        webbrowser.open(url)

    def _dismiss(self, version):
        self._settings.set("dismissed_version", version)
        if self._banner is not None:
            self._banner.destroy()
            self._banner = None
```

Die Button-Callbacks im `_show` binden `lambda: self._dismiss(release.version)` bzw.
`lambda: self._open_download(release)` (analog Bestand). Strings/Farben/Fonts byte-identisch.

## App-Wiring

- `__init__`: das bisherige `self._update_banner = None` ersetzen durch
  ```python
  self._update_banner = UpdateBanner(
      self.root, self.settings, lambda: self.grid_container)
  ```
  (`self._update_banner` ist jetzt die **Komponente** statt des Frames; den Frame hält die
  Komponente intern.)
- `self._bg.check_update(on_result=self._handle_update_check_result)` →
  `self._bg.check_update(on_result=self._update_banner.handle_check_result)`.
- Import ergänzen: `from src.update_banner import UpdateBanner`.
- **Entfernt aus `App`:** `_handle_update_check_result`, `_show_update_banner`,
  `_open_update_download`, `_dismiss_update_banner`.

Imports, die dadurch in `ui.py` ggf. ungenutzt werden (`webbrowser`, `pick_asset_url`,
`today_iso`, ggf. `Release`-Annotation), per Lint/F401 prüfen und trimmen. `platform`,
`ACCENT`, `FONT_BOLD`, `label_button`, `attach_tooltip` bleiben sehr wahrscheinlich
anderweitig in `ui.py` genutzt — nur tatsächlich ungenutzte entfernen.

## Tests (`tests/test_update_banner.py`, ohne Tk)

- `handle_check_result` (mit Fake-`settings` + gemocktem `_show` auf der Instanz):
  - setzt `last_update_check_at` **immer** (auch wenn nicht neuer / ausgeblendet);
  - `newer=False` → `_show` **nicht** aufgerufen;
  - `release.version == dismissed_version` → `_show` **nicht** aufgerufen;
  - neu + nicht ausgeblendet → `_show` **einmal** aufgerufen.
- `_open_download` (Monkeypatch `webbrowser.open` + `pick_asset_url`):
  - URL = Rückgabe von `pick_asset_url`;
  - `pick_asset_url` liefert `None` → Fallback auf `release.html_url`.

Fakes: `_FakeSettings` mit `get`/`set` (dict-gestützt); `release` als einfaches Objekt mit
`version`/`assets`/`html_url`.

## Verifikation (AC — Verhalten unverändert)

- Volle Suite grün, `ruff check .` sauber, Import-Smoke (`import src.ui`,
  `import src.update_banner` — kein Circular-Import).
- Manueller App-Start (Banner-Pfad ist nur bei verfügbarem Update + 1×/Tag sichtbar; mind.
  Start ohne Fehler verifizieren).

## Nicht-Ziele (Folge-PR)

- `GridRenderer` (Rendering-Extraktion) — der verbleibende große Block.
