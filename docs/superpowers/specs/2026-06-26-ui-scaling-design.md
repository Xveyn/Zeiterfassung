# UI-Skalierungsoption — Design

Datum: 2026-06-26

Issue: #78

## Problem

Die Fenstergröße ist bewusst **fix** (kein freies Resizing) und soll es
bleiben. Auf HiDPI-Displays oder kleinen Laptop-Bildschirmen wirkt die App
dadurch aber **sehr klein** und ist schwer ablesbar. Es fehlt eine
Möglichkeit, die UI-Größe anzupassen, ohne das Fixed-Window-Modell aufzugeben.

## Scope

Eine **Skalierungsoption** in den Einstellungen: ein Slider, der einen Faktor
zwischen **0.75 und 2.0** setzt. Der Faktor zieht Schriftgrößen **und**
Fenstergeometrie gemeinsam hoch — das Fenster bleibt fix, nur eben auf einer
größeren (bzw. kleineren) Stufe. Der Faktor ist **gerätespezifisch** und wird
**nicht** über Drive synchronisiert.

Eine geänderte Skalierung wird **sofort** wirksam, indem die App sich selbst
**neu startet** (das Fenster schließt und öffnet sich in neuer Größe).

**Nicht im Scope (YAGNI):**
- Automatische DPI-Erkennung als Default (rein manuell; Default = 1.0).
- Feste Stufen/Presets (es ist ein freier Slider mit Min/Max).
- Skalierung einzelner Pixel-Paddings (`padx`/`pady`) — siehe „Bekannte
  Grenze".
- Live-Skalierung **ohne** Neustart (In-Process-Rebuild).

## Entscheidungen (aus Brainstorming)

- **Skalier-Mechanismus:** `root.tk.call("tk", "scaling", base * faktor)`,
  **einmalig** beim Start gesetzt — *vor* dem Aufbau der `App`-Widgets. Weil
  alle Fonts in `theme.py` **punkt-basiert** sind und `measure_max_width` die
  Fensterbreite *misst* (Probe-Label → `winfo_reqwidth()`), kaskadiert das
  automatisch: größere Fonts → größere Zellen → größeres Fenster. `theme.py`
  und `measure_max_width` bleiben **unangetastet**.
- **Faktor relativ zur System-DPI:** `base = root.tk.call("tk", "scaling")`
  (vom Tk aus der Bildschirm-DPI initialisiert), multipliziert mit dem
  Nutzer-Faktor. Bei Faktor **1.0** ist das Verhalten **exakt** wie heute —
  Bestandsnutzer merken nichts.
- **Wahl-Mechanik:** freier Slider, begrenzt 0.75–2.0. Intern als
  **Prozent-Slider 75–200, Schritt 5** umgesetzt (= Faktor 0.75–2.0 in
  0.05-Schritten) — ganzzahlige Anzeige, keine krummen Float-Zwischenwerte.
- **Default:** `ui_scale = 1.0`, rein manuell (kein DPI-Auto-Detect).
- **Persistenz:** neuer lokaler Settings-Key `ui_scale` (Float). **Nicht** in
  `SYNCED_SETTING_KEYS` — gerätespezifisch wie Autostart/Standardzeiten.
- **Wirksam ab:** sofort, via **Prozess-Neustart** (nicht In-Process-Rebuild).
  Der frische Prozess setzt `tk scaling` am natürlichen Punkt vor jedem Widget
  → identisch zum normalen Start, kein fragiles Re-Wiring von
  Tray/Grid/Sync-Threads.

## Verworfene Alternativen

- **Font-Punktgrößen in `theme.py` aus dem Faktor berechnen.** `theme.py`
  müsste Settings beim Import lesen (bricht Headless-Imports/CI, stateful beim
  Import) und erfasst ttk-Combobox-Interna nicht. → `tk scaling` ist die eine
  Stelle, die alles Punkt-basierte erfasst.
- **In-Process-Rebuild (sofort ohne Neustart).** Vermeidet das Schließen/Öffnen
  des Fensters, ist aber fragil: Tray stop/restart, erneutes Laufen der
  Startup-Tasks (Token-Refresh, Update-Check, Reconcile, Sync-Pull) und „tk
  scaling *nach* existierenden Widgets" ist plattformabhängig unsicher. Der
  Neustart umgeht all das.

## Architektur / Komponenten

### 1 · `src/settings.py`

- Neuer Eintrag in `DEFAULTS`: `"ui_scale": 1.0`. **Nicht** in
  `SYNCED_SETTING_KEYS`. `_coerce` casted den Float beim Laden automatisch;
  ein nicht-castbarer Wert fällt auf den Default zurück (bestehende Mechanik).
- Reiner Helfer `clamp_ui_scale(value)`:
  - Versucht `float(value)`; bei `TypeError`/`ValueError` → `1.0`.
  - Klemmt auf `[0.75, 2.0]` (`max(0.75, min(2.0, f))`).
  - Liefert den geklemmten Float.
  - Zweck: manuell editierte/korrupte `settings.json`-Werte und die
    Slider-Eingabe defensiv normalisieren, bevor sie an `tk scaling` gehen.

### 2 · `src/main.py`

- Neuer modul-level Helfer `relaunch_command(argv, executable, frozen)` (rein,
  headless testbar):
  - `frozen=True` → `[executable] + rest`
  - `frozen=False` → `[executable, "-m", "src.main"] + rest`
  - wobei `rest` = `argv[1:]` **ohne** `"--minimized"` (der Nutzer ändert die
    Skalierung interaktiv und will das Ergebnis sehen, nicht ein erneut
    minimiertes Fenster).
- `main()`: nach `root = tk.Tk()` und **vor** `app = App(...)`:
  ```python
  _apply_ui_scaling(root, settings.get("ui_scale"))
  ```
  mit lokalem Helfer
  ```python
  def _apply_ui_scaling(root, factor):
      f = clamp_ui_scale(factor)
      base = root.tk.call("tk", "scaling")
      root.tk.call("tk", "scaling", base * f)
  ```
  (Bei `f == 1.0` ist `base * 1.0 == base` → unverändert.)

### 3 · `src/ui.py` (`App`)

- Neue Methode `restart_for_scaling()` — Reihenfolge so gewählt, dass der
  Fehlerpfad keinen halben Teardown hinterlässt (erst spawnen, dann erst
  abbauen):
  1. Kommando bauen via
     `relaunch_command(sys.argv, sys.executable, getattr(sys, "frozen", False))`.
  2. Neuen Prozess starten: `subprocess.Popen(cmd)` in `try/except`.
  3. **Erst nach erfolgreichem `Popen`:** Tray stoppen (`self._tray.stop()`,
     falls vorhanden), dann `self.root.destroy()` (altes Fenster schließt,
     `main()` kehrt zurück, Prozess endet).
  - **Kein** Sync-Push (der Faktor ist lokal; ein 5-s-Push würde den Neustart
    nur verzögern). Bewusst abweichend vom normalen Quit-Pfad.
  - **Fallback:** wirft `Popen` (`OSError`/Sonstiges), bleibt die laufende App
    **vollständig intakt** (Tray läuft noch, `root` nicht zerstört — weil der
    Abbau erst *nach* dem Spawn passiert); stattdessen ein themed Hinweis: „Die
    Skalierung wird beim nächsten Start der App wirksam." → sauberes Degradieren
    auf „apply on next start", ohne die laufende App zu killen.
- `_open_settings`: reicht den neuen Callback `on_request_restart` an
  `open_settings_dialog` durch (= `self.restart_for_scaling`).

### 4 · `src/dialogs/settings_dialog.py`

- Neuer Parameter `on_request_restart` an `open_settings_dialog(...)`
  (keyword-only, Default `None` → rückwärtskompatibel/headless-tolerant).
- Neue Sektion „— Darstellung —" (eigener `FONT_BOLD`-Header wie
  „— Synchronisation —"). **Platzierung:** direkt **nach** der Checkbox „Beim
  Schließen in den Infobereich minimieren" (`minimize_to_tray`, aktuell Reihe
  20) und **vor** dem Header „— Synchronisation —" (aktuell Reihe 21). Inhalt:
  - `tk.Scale`, horizontal, `from_=75, to=200, resolution=5`, Startwert
    `round(settings.get("ui_scale") * 100)`.
  - Kurzer Hinweis-Label, dass die Änderung beim Speichern einen Neustart
    auslöst (`FONT_SMALL`, `TEXT_MUTED`).
  - Alle nachfolgenden Grid-Reihen (ab „— Synchronisation —", aktuell Reihen
    21–32) werden um die Anzahl der neuen Reihen nach unten verschoben.
- `save_settings`:
  - `old_scale = settings.get("ui_scale")` **vor** dem Write merken.
  - `new_scale = clamp_ui_scale(scale_var.get() / 100)` ins `updates`-Dict
    (→ `apply_updates` → lokal via `set_many`, da nicht synced).
  - Nach `apply_updates(...)`, `on_change()` und `dialog.destroy()`:
    `if on_request_restart is not None and new_scale != old_scale:
    on_request_restart()`.
  - Reihenfolge ist wichtig: erst persistieren (der neue Prozess liest den
    frischen Wert), dann Dialog schließen, dann Neustart anstoßen.

## Datenfluss

```
Slider (75–200) ──speichern──> ui_scale (0.75–2.0) in settings.json (lokal)
                                   │
                          App.restart_for_scaling()
                                   │  subprocess.Popen(relaunch_command(...))
                                   ▼
                          neuer Prozess: main()
                                   │  _apply_ui_scaling(root, ui_scale)
                                   │  tk scaling = base * faktor   (vor App-Widgets)
                                   ▼
              App-Aufbau → measure_max_width misst größere Probe-Zellen
                                   ▼
                          Fenster pinnt größere Geometrie
```

## Fehlerbehandlung

- **Korrupter/extremer `ui_scale` in settings.json:** `_coerce` + `clamp_ui_scale`
  fangen ab → nie ein ungültiger Wert an `tk scaling`.
- **`Popen` schlägt beim Neustart fehl:** App bleibt am Leben, themed Hinweis
  „wird beim nächsten Start wirksam" (degradiert, kein Crash, kein
  verwaistes Fenster).
- **Sehr hoher Faktor auf kleinem Screen:** das fixe Fenster kann den
  Bildschirm überragen — bewusste Nutzerentscheidung, der Slider lässt sich
  zurückdrehen. Kein Schutz nötig.

## Tests

**Headless / TDD (laufen im CI):**
- `clamp_ui_scale`:
  - klemmt unter 0.75 auf 0.75, über 2.0 auf 2.0,
  - lässt 1.0 / 1.25 / 0.75 / 2.0 unverändert,
  - `None`/Müll-String → 1.0,
  - `"1.5"` (String) → 1.5.
- `relaunch_command`:
  - frozen → `[exe, *argv[1:]]`,
  - repo → `[python, "-m", "src.main", *argv[1:]]`,
  - `--minimized` wird in beiden Modi aus den Args entfernt.

**Manuell verifiziert (Tk/Prozess-Ebene, nicht im CI — wie die übrigen
Dialoge):**
- Slider rendert in „Darstellung", Startwert = gespeicherter Faktor.
- Speichern mit geändertem Faktor → App startet neu, Fenster erscheint in
  neuer Größe, Fonts + Geometrie skaliert.
- Speichern **ohne** Faktor-Änderung → **kein** Neustart.
- Faktor 1.0 → identisch zum heutigen Erscheinungsbild.
- Popen-Fallback (z.B. Executable künstlich unauffindbar) → App lebt, Hinweis
  erscheint.

## Bekannte Grenze

`tk scaling` vergrößert alle punkt-basierten Fonts (und dadurch die *gemessene*
Geometrie), aber **feste Pixel-Paddings** (`padx=10`, `pady=8`, …) skalieren
**nicht** mit. Bei hohen Faktoren (≈200 %) wirkt das Layout dadurch minimal
kompakter. Bewusst akzeptiert: jedes Padding faktorabhängig zu rechnen wäre
unverhältnismäßig viel invasive Änderung für einen kleinen optischen Gewinn
(YAGNI). Die Lesbarkeit — das Ziel des Issues — wird durch die Font-Skalierung
erreicht.
