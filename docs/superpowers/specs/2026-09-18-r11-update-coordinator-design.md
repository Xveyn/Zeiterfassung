# R11: `UpdateCoordinator` als fünfte App-Komponente — Design

**Datum:** 2026-09-18
**Status:** Design abgestimmt, Implementierungsplan folgt
**Branch:** `refactor/r11-update-coordinator`
**Issue:** Xveyn/Zeiterfassung#123, Punkt R11 (baut auf R9, #134)

## Problem

`src/ui.py::App` ist nach dem Split aus #51 ein schlanker Koordinator über vier
Komponenten (`GridRenderer`, `BackgroundTaskRunner`, `SyncOrchestrator`,
`UpdateBanner`). Das Selbst-Update hat seitdem eine neue, zusammenhängende
Verantwortlichkeit zurück in den Koordinator gelegt — rund 130 LOC:

| Heute in `ui.py` | Rolle |
|---|---|
| `_route_update_notification` (Modulfunktion) | Toast vs. Banner vs. schon gemeldet |
| `App._on_update_check_result` | Ergebnis des Start-Checks: `last_update_check_at`, Routing, `auto_updater.maybe_start` |
| `App._tray_check_update` + `_update_check_running` | Tray-Menüpunkt „Nach Updates suchen", Doppelklick-Guard |
| `App._on_tray_check_update_result` | Ergebnis des Tray-Checks: immer ein Toast |
| `App._apply_pending_update` | vorbereitetes Update beim Beenden anwenden |
| in `App.__init__`: `AutoUpdater(...)`, `_bg.check_update(...)` | Bau der Policy (R9), Start-Check |
| in `App._quit_with_sync_push`: `pending_update_path` lesen + Gurt | Einstieg ins Anwenden beim Beenden |

`ui.py` ist mit 111 Commits in zwölf Monaten die Datei mit dem meisten Churn im
Repo. R9 hat die *Policy* aus App und Updates-Tab gezogen; der Rest des
Update-Lebenszyklus sitzt weiter im Koordinator.

## Ziel

Eine fünfte Komponente `UpdateCoordinator` in `src/update_coordinator.py`, gebaut
wie `SyncOrchestrator`: Konstruktor-Injektion, Rückweg über injizierte
Callables, kein Import von `src.ui`. `App` behält nur noch das Wiring.

**Strikt verhaltensneutral.** Keine Änderung an Texten, Reihenfolgen,
Settings-Keys oder Fehlerpfaden. Beleg ist, dass die bestehenden Tests nur ihr
Bindungsziel wechseln (`App` → `UpdateCoordinator`), nicht ihre Assertions.

Zwei Abweichungen sind unvermeidlich bzw. harmlos und werden bewusst in Kauf
genommen (im Plan-Review gefunden):

- **Loggername.** Die Einträge „Manueller Update-Check fehlgeschlagen" und
  „Vorbereitetes Update …" erscheinen im Logfile unter `src.update_coordinator`
  statt `src.ui` (Format `%(name)s` in `logging_setup.py`).
- **Der Gurt fängt etwas mehr.** Vorher lag `settings.get("pending_update_path")`
  vor dem `try`; jetzt liest `apply_pending_on_quit()` den Pfad innerhalb des
  Gurts. Fängt mehr, nie weniger.

## Architektur

### `src/update_coordinator.py` (neu, Tk-frei)

Einen Schritt weiter als `SyncOrchestrator`: die Komponente braucht weder
`root` noch eigene Widgets und ist deshalb **Tk-frei** und **vollständig
annotiert** (Eintrag in `tests/test_type_annotations.py::ANNOTATED_MODULES`).
Die Abhängigkeiten kommen als `Protocol`s herein.

```python
def route_update_notification(release, tray_active: bool,
                              toast_shown_version: str) -> tuple[str, str | None]

class UpdateCoordinator:
    def __init__(self, settings, runner, banner,
                 get_tray: Callable[[], _Tray | None]) -> None
    auto_updater: AutoUpdater                 # für open_settings_dialog
    def start(self) -> None                   # Start-Check anstoßen
    def on_check_result(self, release, newer: bool) -> None
    def tray_check(self) -> None              # Tray-Menü „Nach Updates suchen"
    def apply_pending_on_quit(self) -> None   # beim Beenden, best-effort
    # privat:
    def _on_tray_check_result(self, release) -> None
    def _apply_pending_update(self, path: str) -> None
```

| Abhängigkeit | Protocol | In der App |
|---|---|---|
| `settings` | `get`, `set`, `set_many` | `App.settings` |
| `runner` | `run(fn, on_done)`, `check_update(on_result)` | `App._bg` |
| `banner` | `show_if_newer(release)`, `show_ready_to_install(release)` | das `UpdateBanner`-Exemplar |
| `get_tray` | `() -> Tray \| None`, Tray hat `notify(text)` | `lambda: App._tray` |

`get_tray` ist **lazy**, aus demselben Grund wie bei `SyncOrchestrator` und
`ReminderScheduler`: `App._tray` wird zur Laufzeit an- und abgeschaltet
(`_apply_tray_setting`), die einzige Quelle bleibt das App-Attribut.

**Was umzieht, und wie:**

- `route_update_notification` — unverändert, nur ohne führenden Unterstrich,
  weil es jetzt die Modul-Schnittstelle ist, gegen die Tests laufen.
- `on_check_result` — Körper von `App._on_update_check_result`; `self._tray` wird
  zu `self._get_tray()`, `self._update_banner` zu `self._banner`,
  `self._auto_updater` zu `self.auto_updater`.
- `tray_check` / `_on_tray_check_result` — Körper von `_tray_check_update` /
  `_on_tray_check_update_result`, samt `_update_check_running`. Die Prüfung
  „Tray vorhanden?" bleibt drin (Tray kann zwischen Klick und Ergebnis
  abgeschaltet worden sein).
- `start` — der bisherige Aufruf `self._bg.check_update(on_result=…)` aus
  `App.__init__`.
- `apply_pending_on_quit` — liest `pending_update_path` und ruft
  `_apply_pending_update`, wenn einer gesetzt ist. `_apply_pending_update`
  selbst zieht unverändert um, inklusive Docstring und aller
  `discard_download`-Pfade.
- Der Bau des `AutoUpdater` (R9) wandert in den Konstruktor:
  `AutoUpdater(settings, runner, on_ready=banner.show_ready_to_install)`.

### Was in `App` bleibt

- **Den Banner baut weiter `App`.** Er braucht `root`, den Renderer
  (`get_anchor`, `on_resize`) und `_open_settings` — alles App-Zustand. Er wird
  fertig an den Coordinator gereicht. `self._update_banner` bleibt als
  Attribut, obwohl danach nur noch `__init__` es liest (das Renderer-/Resize-
  Wiring hängt an den Konstruktor-Argumenten des Banners, nicht am Attribut) —
  harmlos, und es hält die Referenz lesbar am Ort ihres Baus.
- `self._updates = UpdateCoordinator(self.settings, self._bg,
  self._update_banner, lambda: self._tray)`, danach `self._updates.start()` an
  der Stelle des heutigen `check_update`-Aufrufs — die Reihenfolge der
  Start-Tasks ändert sich nicht.
- `_tray_actions`: der Eintrag „Nach Updates suchen" ruft
  `lambda: self.root.after(0, self._updates.tray_check)` — das Marshalling auf
  den UI-Thread bleibt in der App, wie bei allen anderen Tray-Einträgen.
- `_open_settings`: `auto_updater=self._updates.auto_updater`.
- **Der Gurt im Beenden-Pfad bleibt in `App._quit_with_sync_push`**, direkt vor
  `root.destroy()`:

  ```python
  try:
      self._updates.apply_pending_on_quit()
  except Exception:
      logging.getLogger(__name__).exception(
          "Vorbereitetes Update konnte nicht angewendet werden")
  self.root.destroy()
  ```

  Begründung: die Zusage „NICHTS darf das Beenden aufhalten" gilt dem
  `destroy()`, und der gehört der App. Läge der Gurt im Coordinator, hinge die
  Zusage an einer Eigenschaft einer anderen Datei. Der bestehende Test
  `test_quit_with_sync_push_destroys_the_window_even_if_applying_raises` bleibt
  damit App-seitig und wechselt nur, was er werfen lässt
  (`fake._updates.apply_pending_on_quit` statt `fake._apply_pending_update`).
  (Abweichung vom ersten Chat-Entwurf, der den Gurt in den Coordinator legen
  wollte — beim Lesen der Tests präzisiert.)

- Importe, die nur noch der Coordinator braucht, fallen aus `ui.py` weg:
  `AutoUpdater`, `apply_linux`, `apply_windows`, `discard_download`,
  `verify_file`, `REPO`, `check_for_update`, `is_newer`,
  `manual_check_toast_text`, `today_iso`, `update_toast_text`,
  `installed_release_id` — soweit `ruff` sie danach als unbenutzt meldet
  (`installed_release_id`/`today_iso` vorher auf weitere Nutzer prüfen).

### Datenfluss

```
App.__init__
  ├─ UpdateBanner(root, …)                       (App baut)
  ├─ UpdateCoordinator(settings, _bg, banner, lambda: _tray)
  │     └─ AutoUpdater(settings, _bg, on_ready=banner.show_ready_to_install)
  └─ _updates.start() ──► _bg.check_update(on_result=_updates.on_check_result)
                                  │ (UI-Thread)
                                  ▼
                        on_check_result: Datum, Toast/Banner, auto_updater.maybe_start

Tray „Nach Updates suchen" ─root.after─► _updates.tray_check ─_bg.run─► _on_tray_check_result ─► Toast
Einstellungen ─► open_settings_dialog(auto_updater=_updates.auto_updater)
Beenden ─► App._quit_with_sync_push ─try─► _updates.apply_pending_on_quit ─► destroy()
```

## Fehlerverhalten

Unverändert. Explizit festgehalten, weil es beim Umzug nicht kippen darf:

- Tray-Check: Lauf-Flag wird **zuerst** freigegeben, auch im Fehlerfall; eine
  gescheiterte Abfrage setzt `last_update_check_at` nicht.
- `_apply_pending_update`: jeder Fehlerpfad räumt seine Datei weg, Settings
  werden **vor** der Prüfung geleert, Windows mit `restart=False`.
- Beenden: der Gurt bleibt in `App` (s.o.).
- `tests/test_catch_all_handlers.py` prüft Catch-alls weiter; der Gurt bleibt
  derselbe Handler mit derselben Log-Zeile, nur mit anderem Aufruf im `try`.

## Tests

Refactoring nach TDD: die Tests wechseln **zuerst** ihr Ziel (rot, weil
`src.update_coordinator` fehlt), dann zieht der Code um (grün).

| Heute | Danach |
|---|---|
| `tests/test_ui_update_routing.py` | `git mv` → `tests/test_update_coordinator.py`; Routing-, Check-Ergebnis-, Tray-Check- und Auto-Trigger-Tests gegen `UpdateCoordinator` mit Fakes für Settings/Runner/Banner/Tray. `monkeypatch`-Ziele wechseln von `src.ui` auf `src.update_coordinator`. |
| `tests/test_ui_apply_pending_update.py` | `git mv` → `tests/test_update_coordinator_apply_pending.py`; die `_apply_pending_update`-Tests gegen den Coordinator. |
| App-seitig: `test_tray_menu_offers_update_check`, `test_quit_with_sync_push_destroys_the_window_even_if_applying_raises` | bleiben `App`-Tests, zusammen in `tests/test_ui_update_wiring.py`. |

**Assertions bleiben wortgleich** — geändert werden nur Aufbau (Fake statt
`_FakeApp`) und Aufruf (`coordinator.on_check_result(...)` statt
`App._on_update_check_result(fake, ...)`).

**Neu** (Verträge, die es bisher nicht als Test gab):

- `apply_pending_on_quit` ohne `pending_update_path` fasst nichts an (kein
  `set_many`, kein Anwenden).
- `apply_pending_on_quit` mit Pfad wendet genau diese Datei an.
- `start()` stößt genau einen Check an, dessen Ergebnis in
  `on_check_result` landet.
- Der Tray-Eintrag der App ruft `_updates.tray_check` (über `root.after`).
- Der vom Coordinator gebaute `AutoUpdater` meldet „bereit" an den Banner
  (`on_ready` ist `banner.show_ready_to_install`).
- `App._open_settings` reicht **denselben** `AutoUpdater` an den Dialog
  (`auto_updater is _updates.auto_updater`) — sonst gäbe es wieder zwei
  Guards. Nötig als Test, weil pyright einen Tippfehler dort nur als Warnung
  meldet (`reportAttributeAccessIssue = "warning"`).
- Beim Beenden gilt die Reihenfolge „erst anwenden, dann `destroy()`".

## Verifikation vor dem Merge

- `pytest`, `ruff check .`, `pyright` grün.
- **Echte App** (Harness mit `ZEITERFASSUNG_DATA_DIR` im Scratchpad; Netz —
  fester Release statt GitHub-API — und Plattform gefälscht; Toasts und Banner
  auf stdout gespiegelt), zwei Läufe:
  - mit Tray: Start-Check → Toast; der **echte** Tray-Menüeintrag „Nach Updates
    suchen" → Toast; Beenden mit gesetztem `pending_update_path` →
    `apply_windows` (neutralisiert) mit `restart=False`, Fenster geht zu;
  - ohne Tray (Default-Nutzer): Start-Check → Banner.
- Kein Pre-Release nötig über den R9-Gate hinaus: die Plattformzweige in
  `_apply_pending_update` ziehen unverändert um. Der offene R9-Pre-Release
  deckt sie ohnehin mit ab.

## Dokumentation

- `src/CLAUDE.md`: Schichten-Überblick „fünf Komponenten", neuer Abschnitt
  „UpdateCoordinator (`update_coordinator.py`)" mit Verträgen (Tk-frei,
  `get_tray` lazy, Banner injiziert, Gurt bleibt in `App`); UpdateBanner-
  Abschnitt (Routing liegt nicht mehr in `ui.py`), Tray-Absatz
  (`_tray_check_update` → `UpdateCoordinator.tray_check`),
  `auto_update.py`-Eintrag (Aufrufer).
- `CLAUDE.md`: Strukturliste (`ui.py`-Zeile nennt fünf Komponenten, neuer
  Eintrag `update_coordinator.py`), „Update-Weg" (`ui.App._apply_pending_update`
  → `UpdateCoordinator._apply_pending_update`).
- Docstrings/Kommentare mit `ui.App._apply_pending_update` bzw.
  `App._on_update_check_result`: `self_update.py`, `auto_update.py`,
  `tab_updates.py`.
- `tests/test_claude_md_claims.py` läuft mit; bricht er, wird das Muster
  nachgezogen.

## Bewusst nicht dabei (YAGNI)

- **Den Banner in den Coordinator ziehen.** Er ist Tk-Code mit App-Anker
  (`grid_container`, `repin_geometry`) und bleibt eigene Komponente; der
  Coordinator hielte sonst Widgets und wäre nicht mehr Tk-frei.
- **`BackgroundTaskRunner.check_update` in den Coordinator ziehen.** Der Task
  gehört zur Familie der Startup-Tasks im Runner (`refresh_token`,
  `reconcile_on_start`, …); ihn zu verschieben wäre ein zweiter Umbau.
- **Den manuellen Tray-Check an den `AutoUpdater` koppeln.** Heute löst er
  bewusst keinen stillen Download aus; das zu ändern wäre eine
  Verhaltensänderung und gehört nicht in ein Refactoring.
