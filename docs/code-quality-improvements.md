# Code-Quality-Improvements

Hygiene-Befunde aus dem Review vom 2026-05-17. Priorisiert nach Hebelwirkung
(großer Effekt / kleiner Aufwand zuerst). Reine Hygiene-Punkte — Kernfunktionalität
ist stabil, das hier sind keine Bug-Reports.

> **Stand nachgeprüft am 2026-09-12, offene Punkte am 2026-10-26 erneut.**
> Neun der zehn Punkte hat die Zeit erledigt (der Font im Settings-Dialog zuletzt) — die großen Umbauten danach (R1 `sync_runtime`, R2 `json_store`,
> R3 `theme/`, die `GridRenderer`-Extraktion, Audit N17) haben den Code an
> genau diesen Stellen ohnehin angefasst. Einer steht noch, und er ist klein.
> Die Zeilennummern von 2026-05-17 waren durchweg verrutscht und sind
> nachgezogen; wo eine Datei seither Paket geworden ist, steht der neue Pfad.

## Duplikate (klein, hoher Effekt)

- [x] **`SYNCED_SETTING_KEYS` doppelt definiert** — erledigt (Issue #48)
  In `settings.py` belassen, aus `sync.py` raus und importiert. Schutz-Test
  `test_sync_reexports_settings_whitelist` erzwingt jetzt Identität (`is`)
  statt nur Wertgleichheit.

- [x] **`_utc_now_iso()` dreifach kopiert** — erledigt (Audit N17)
  Liegt als `time_utils.utc_now_iso()` genau einmal; die privaten Kopien sind
  weg. Der Docstring dort hält fest, dass es zuletzt **sechs** waren — die
  Zahl war zwischen Review und Behebung noch gewachsen.

- [x] **Probe-Label-Block in `_refresh_month`/`_refresh_week` gespiegelt** —
  gegenstandslos. Beide Methoden gibt es in `ui.py` nicht mehr; das Rendering
  inklusive der Mess-Probe liegt seit der Komponenten-Extraktion in
  `grid_renderer.py` (`measure_max_width`), und zwar einmal.

- [x] **Lokale `import tkinter.messagebox as mb`** — erledigt. `ui.py` nutzt
  durchgehend das Top-Level-`from tkinter import messagebox`.

## Verdächtige Stellen (Klärung nötig)

- [ ] **`_strip_for_candidate` ist ein No-op**
  `src/sync.py:200` ist `{k: v for k, v in item.items()}`, also nur ein
  shallow copy. Der Name impliziert Filter-Logik, die fehlt. Einziger
  Aufrufer ist `sync.py:189` (Aufbau von `conflict["candidates"]`). Entweder
  Funktion löschen und die Callsite auf `dict(...)` ändern, oder fehlende
  Strip-Logik nachziehen. Vorher klären, ob Strip versehentlich entfernt wurde.
  **Weiterhin offen** — am 2026-10-26 gegengeprüft, die Funktion ist unverändert ein reiner Shallow-Copy.

- [x] **`_measure_max_width` greift auf `settings._data` direkt** — erledigt.
  Die Messung liegt in `grid_renderer.py`; ein Zugriff auf `settings._data`
  existiert in `src/` nirgends mehr.

- [x] **Zirkuläre Imports zwischen `ui` und `main`** — erledigt (R1,
  margenheld/Zeiterfassung#181 bzw. Xveyn#49). Genau die hier vorgeschlagene
  Auslagerung, nur unter anderem Namen: die Flows liegen in
  `src/sync_runtime.py`, `main.py` ist wieder reiner Bootstrap, und in `src/`
  steht kein einziges lazy `from src.main import …` mehr.

- [x] **Instance-State über `getattr`-Defaults** — erledigt. Weder
  `_last_refresh_view`/`_last_refresh_columns` noch `_suppress_geometry`
  werden noch über `getattr`-Defaults gelesen.

## Kleinkram

- [x] **Magic numbers ohne Kommentar** (`height=3`/`height=5`) —
  gegenstandslos, siehe Probe-Label-Block oben.

- [x] **Hardcoded Font im Settings-Dialog** — gegenstandslos.
  `tab_mail.py` gibt es nicht mehr (die Tabs heißen `tab_sending` & Co.), und
  `grep -rn "Segoe UI" src/dialogs` findet nichts mehr.

## Bewusst nicht angefasst

- **`src/ui.py`** war beim Review ~1050 Zeilen; heute sind es ~1200 — aber die
  damals genannte Sorge hat sich anders aufgelöst als vorgeschlagen: statt
  eines Mixins sind die Sync-Methoden in die eigene Komponente
  `sync_orchestrator.py` gewandert (dazu `grid_renderer.py`,
  `background_tasks.py`, `update_banner.py`, seit R11 `update_coordinator.py`). `App` ist seither Koordinator,
  keine God-Class — die Zeilen sind Chrome-Aufbau und Dialog-Routing. Der
  Schnitt steht in [`src/CLAUDE.md`](../src/CLAUDE.md).
- ~~Fehlender „Abbrechen"-Button im Entry-Dialog~~ — überholt: seit #320
  (Commit 361d904) hat der Tages-Dialog einen „Abbrechen"-Knopf
  (`src/dialogs/entry_dialog.py`).
