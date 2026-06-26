# UI-Skalierungsoption Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eine Skalierungsoption (Slider 0.75–2.0) in den Einstellungen, die Fonts + Fenstergeometrie gemeinsam hochzieht; gerätelokal gespeichert, sofort per Prozess-Neustart wirksam.

**Architecture:** `tk scaling` wird einmalig beim Start auf System-DPI × Faktor gesetzt (vor dem App-Aufbau) — weil alle Fonts in `theme.py` punkt-basiert sind und `measure_max_width` die Geometrie *misst*, kaskadiert das automatisch. Ein geänderter Faktor wird wirksam, indem `App` den Prozess neu startet (`subprocess.Popen` → Tray-Stop → `root.destroy()`). Pure Helfer (`clamp_ui_scale`, `relaunch_command`) sind headless getestet; die Tk-/Prozess-Integration manuell.

**Tech Stack:** Python 3.11, Tkinter, pytest. Keine neuen Dependencies.

## Global Constraints

- `src/settings.py` bleibt **stdlib-only** (kein holidays/google-Import) — `sync.py` importiert es; CI installiert `requirements.txt` nicht. `clamp_ui_scale` nutzt nur Builtins.
- Neuer Key `ui_scale` darf **nicht** in `SYNCED_SETTING_KEYS` stehen (gerätespezifisch, reist nicht per Drive).
- Faktor ist **relativ** zur System-DPI: `tk scaling = base × faktor`. Bei Faktor **1.0** muss das Verhalten **exakt** wie heute sein.
- Slider intern **Prozent 75–200, Schritt 5** = Faktor **0.75–2.0** in 0.05-Schritten. Faktor wird als Float in `settings.json` gespeichert (z.B. `1.25`).
- Beim Neustart-Kommando wird `--minimized` aus den Argumenten entfernt.
- Konversation/UI **Deutsch** (ü ö ä ß korrekt), Code + Commit-Typ **Englisch** (`feat:`/`fix:`/`test:`), Body Deutsch ok.
- Alle Tests müssen vor PR-Merge grün sein; `ruff check .` sauber.
- **Kein** Versionsbump / **kein** CHANGELOG-Eintrag / **kein** `release:*`-Label in diesem Plan (Release nur auf Bedarf, wie bei den letzten Feature-PRs).

---

## Dateien-Überblick

| Datei | Änderung |
|-------|----------|
| `src/settings.py` | `"ui_scale": 1.0` in `DEFAULTS`; reiner Helfer `clamp_ui_scale`. |
| `tests/test_settings.py` | Tests für Default, Nicht-Sync, `clamp_ui_scale`. |
| `src/main.py` | Reiner Helfer `relaunch_command`; `_apply_ui_scaling`; Aufruf in `main()` nach `tk.Tk()`. |
| `tests/test_main_relaunch.py` | **Neu** — Tests für `relaunch_command`. |
| `src/ui.py` | `import sys`/`import subprocess`; Methode `App.restart_for_scaling`; `_open_settings` reicht `on_request_restart` durch. |
| `src/dialogs/settings_dialog.py` | Param `on_request_restart`; „Darstellung"-Slider-Sektion; Save-Logik. |

---

### Task 1: `ui_scale`-Setting + `clamp_ui_scale`

**Files:**
- Modify: `src/settings.py` (DEFAULTS-Dict endet bei Zeile 56; pure Helfer nach `resolve_calendar_id`, Zeile 147)
- Test: `tests/test_settings.py`

**Interfaces:**
- Produces: `clamp_ui_scale(value) -> float` — castet zu float, klemmt auf `[0.75, 2.0]`, nicht-castbar/None → `1.0`. Default-Setting `ui_scale = 1.0`, **nicht** in `SYNCED_SETTING_KEYS`.

- [ ] **Step 1: Failing Tests schreiben**

In `tests/test_settings.py` ans Dateiende anhängen:

```python
def test_ui_scale_default(tmp_settings):
    assert tmp_settings.get("ui_scale") == 1.0


def test_ui_scale_is_not_synced():
    # Gerätespezifisch -> darf nicht per Drive synchronisieren.
    assert "ui_scale" not in SYNCED_SETTING_KEYS


def test_clamp_ui_scale_within_range():
    from src.settings import clamp_ui_scale
    assert clamp_ui_scale(1.25) == 1.25
    assert clamp_ui_scale(0.75) == 0.75
    assert clamp_ui_scale(2.0) == 2.0


def test_clamp_ui_scale_below_min_clamps_to_075():
    from src.settings import clamp_ui_scale
    assert clamp_ui_scale(0.5) == 0.75


def test_clamp_ui_scale_above_max_clamps_to_2():
    from src.settings import clamp_ui_scale
    assert clamp_ui_scale(3.0) == 2.0


def test_clamp_ui_scale_string_is_cast():
    from src.settings import clamp_ui_scale
    assert clamp_ui_scale("1.5") == 1.5


def test_clamp_ui_scale_invalid_falls_back_to_1():
    from src.settings import clamp_ui_scale
    assert clamp_ui_scale(None) == 1.0
    assert clamp_ui_scale("abc") == 1.0
```

- [ ] **Step 2: Tests laufen lassen — müssen fehlschlagen**

Run: `pytest tests/test_settings.py -k "ui_scale" -v`
Expected: FAIL (`test_ui_scale_default`: KeyError/None; `clamp_ui_scale`-Tests: ImportError „cannot import name 'clamp_ui_scale'").

- [ ] **Step 3: `ui_scale`-Default ergänzen**

In `src/settings.py`, im `DEFAULTS`-Dict (vor der schließenden `}` bei Zeile 56) eine Zeile ergänzen:

```python
    "category_times": {},
    "ui_scale": 1.0,
}
```

(`ui_scale` **nicht** zu `SYNCED_SETTING_KEYS` hinzufügen — bleibt gerätelokal.)

- [ ] **Step 4: `clamp_ui_scale` implementieren**

In `src/settings.py` nach der Funktion `resolve_calendar_id` (nach Zeile 147) einfügen:

```python
def clamp_ui_scale(value):
    """Normalisiert den UI-Skalierungsfaktor defensiv: castet zu float und
    klemmt auf [0.75, 2.0]. Nicht-castbare Werte (None, Müll-String) → 1.0
    (Default). Schützt das tk-scaling vor korrupten settings.json-Werten und
    Slider-Ausreißern."""
    try:
        f = float(value)
    except (TypeError, ValueError):
        return 1.0
    return max(0.75, min(2.0, f))
```

- [ ] **Step 5: Tests laufen lassen — müssen grün sein**

Run: `pytest tests/test_settings.py -k "ui_scale" -v`
Expected: PASS (7 Tests grün).

- [ ] **Step 6: Volle Settings-Suite + Lint**

Run: `pytest tests/test_settings.py -q && ruff check src/settings.py tests/test_settings.py`
Expected: alle grün, ruff ohne Findings.

- [ ] **Step 7: Commit**

```bash
git add src/settings.py tests/test_settings.py
git commit -m "feat(settings): lokaler ui_scale-Faktor + clamp_ui_scale-Helfer"
```

---

### Task 2: `relaunch_command`-Helfer

**Files:**
- Modify: `src/main.py` (modul-level Helfer, nach `_ensure_device_id`, vor `_parse_remote_or_quarantine` — also nach Zeile 36)
- Test: `tests/test_main_relaunch.py` (**neu**)

**Interfaces:**
- Produces: `relaunch_command(argv, executable, frozen) -> list[str]` — baut das Neustart-Kommando. `frozen=True` → `[executable, *rest]`; `frozen=False` → `[executable, "-m", "src.main", *rest]`; `rest = argv[1:]` ohne `"--minimized"`.

**Hinweis CI:** `tests/test_main_relaunch.py` importiert `src.main`. Das zieht die `src.ui`-Importkette (inkl. Google-Wrapper) — in CI vorhanden (`test.yml` installiert `google-api-python-client`/`google-auth`/`google-auth-oauthlib`), genau wie beim bestehenden `tests/test_ui_delete.py`. Kein Tk-Root beim Import → display-frei.

- [ ] **Step 1: Failing Tests schreiben**

`tests/test_main_relaunch.py` neu anlegen:

```python
from src.main import relaunch_command


def test_relaunch_command_frozen_uses_executable_directly():
    cmd = relaunch_command(["app.exe", "--foo"], "app.exe", True)
    assert cmd == ["app.exe", "--foo"]


def test_relaunch_command_repo_uses_module_invocation():
    cmd = relaunch_command(["src/main.py", "--foo"], "python", False)
    assert cmd == ["python", "-m", "src.main", "--foo"]


def test_relaunch_command_strips_minimized_frozen():
    cmd = relaunch_command(["app.exe", "--minimized", "--bar"], "app.exe", True)
    assert cmd == ["app.exe", "--bar"]


def test_relaunch_command_strips_minimized_repo():
    cmd = relaunch_command(["main.py", "--minimized"], "python", False)
    assert cmd == ["python", "-m", "src.main"]
```

- [ ] **Step 2: Tests laufen lassen — müssen fehlschlagen**

Run: `pytest tests/test_main_relaunch.py -v`
Expected: FAIL (ImportError „cannot import name 'relaunch_command'").

- [ ] **Step 3: `relaunch_command` implementieren**

In `src/main.py` nach `_ensure_device_id` (nach Zeile 36) einfügen:

```python
def relaunch_command(argv, executable, frozen):
    """Baut das Kommando, um die App neu zu starten (nach UI-Skalierungs-
    Änderung). Im Frozen-Build ist `executable` die App-Exe selbst; im
    Repo-Modus wird `python -m src.main` aufgerufen. `--minimized` wird
    entfernt, weil der Nutzer nach einer interaktiven Skalierungsänderung das
    Fenster sehen will, nicht ein erneut minimiertes."""
    rest = [a for a in argv[1:] if a != "--minimized"]
    if frozen:
        return [executable] + rest
    return [executable, "-m", "src.main"] + rest
```

- [ ] **Step 4: Tests laufen lassen — müssen grün sein**

Run: `pytest tests/test_main_relaunch.py -v`
Expected: PASS (4 Tests grün).

- [ ] **Step 5: Lint**

Run: `ruff check src/main.py tests/test_main_relaunch.py`
Expected: keine Findings.

- [ ] **Step 6: Commit**

```bash
git add src/main.py tests/test_main_relaunch.py
git commit -m "feat(main): relaunch_command für Neustart nach Skalierungsänderung"
```

---

### Task 3: Skalierung beim Start anwenden

**Files:**
- Modify: `src/main.py` — Import-Zeile 21 (`from src.settings import Settings`); neuer Helfer `_apply_ui_scaling`; Aufruf in `main()` zwischen Zeile 277 (`root = tk.Tk()`) und 278 (`app = App(...)`).

**Interfaces:**
- Consumes: `clamp_ui_scale` aus Task 1; `settings.get("ui_scale")`.
- Produces: `_apply_ui_scaling(root, factor)` — setzt `tk scaling` auf `base × clamp_ui_scale(factor)`.

**Verifikation:** Keine CI-Tests (braucht echten Tk-Root → kein Display in CI). Die reine Logik (`clamp_ui_scale`) ist in Task 1 getestet; die `tk`-Verdrahtung wird manuell verifiziert (Step 4).

- [ ] **Step 1: Import erweitern**

In `src/main.py` Zeile 21 ändern:

```python
from src.settings import Settings, clamp_ui_scale
```

- [ ] **Step 2: `_apply_ui_scaling` implementieren**

In `src/main.py` direkt **vor** `def main():` (vor Zeile 259) einfügen:

```python
def _apply_ui_scaling(root, factor):
    """Setzt tk-scaling einmalig auf System-DPI × Faktor. MUSS vor dem Aufbau
    der App-Widgets laufen, damit measure_max_width die skalierten Fonts misst
    und die Fenstergeometrie entsprechend pinnt. Bei Faktor 1.0 unverändert
    (base × 1.0 == base)."""
    f = clamp_ui_scale(factor)
    base = float(root.tk.call("tk", "scaling"))
    root.tk.call("tk", "scaling", base * f)
```

- [ ] **Step 3: Aufruf in `main()` einfügen**

In `src/main.py`, in `main()`, zwischen `root = tk.Tk()` (Zeile 277) und `app = App(...)` (Zeile 278):

```python
    root = tk.Tk()
    _apply_ui_scaling(root, settings.get("ui_scale"))
    app = App(root, storage, settings, base_path=base, conflicts_store=conflicts_store,
              reservation_store=reservation_store)
```

- [ ] **Step 4: Manuell verifizieren**

In `settings.json` (Repo-Root) probeweise `"ui_scale": 1.5` setzen (oder Datei anlegen mit `{"ui_scale": 1.5}`), dann:

Run: `python -m src.main`
Expected: Das Fenster (Kalender, Fonts, Buttons) erscheint **sichtbar größer** als bei `1.0`. Danach Wert wieder auf `1.0` setzen → Erscheinungsbild identisch zu vorher. Probe-Datei-Änderung anschließend verwerfen (nicht committen).

Run: `ruff check src/main.py`
Expected: keine Findings.

- [ ] **Step 5: Commit**

```bash
git add src/main.py
git commit -m "feat(main): ui_scale beim Start auf tk-scaling anwenden"
```

---

### Task 4: Slider in den Einstellungen + Neustart-Verdrahtung

**Files:**
- Modify: `src/ui.py` — Imports (nach Zeile 8); neue Methode `restart_for_scaling` (nach `_quit_with_sync_push`, Zeile 557); `_open_settings` (Zeile 323–329).
- Modify: `src/dialogs/settings_dialog.py` — Import (Zeile 23); Signatur (Zeile 28–30); neue „Darstellung"-Sektion + Reihen-Umnummerierung; `save_settings` (Zeile 713–776).

**Interfaces:**
- Consumes: `relaunch_command` aus Task 2 (lazy import in `restart_for_scaling`); `clamp_ui_scale` aus Task 1.
- Produces: `App.restart_for_scaling()`; `open_settings_dialog(..., on_request_restart=None)`.

**Verifikation:** End-to-End manuell (Tk-Slider + Prozess-Neustart, kein Display in CI). Die genutzten reinen Helfer sind in Task 1/2 getestet.

- [ ] **Step 1: ui.py — Imports ergänzen**

In `src/ui.py` nach Zeile 8 (`import time`) zwei Imports ergänzen (alphabetisch einsortiert in den bestehenden Block):

```python
import subprocess
import sys
import time
```

(Konkret: `import subprocess` und `import sys` zum bestehenden Import-Block hinzufügen — `time` ist bereits da.)

- [ ] **Step 2: ui.py — `restart_for_scaling` implementieren**

In `src/ui.py` direkt nach `_quit_with_sync_push` (nach Zeile 557) einfügen:

```python
    def restart_for_scaling(self):
        """Startet die App neu, damit eine geänderte UI-Skalierung greift
        (tk-scaling wird nur beim Start gesetzt). Erst den neuen Prozess
        spawnen, dann erst das alte Fenster abbauen — schlägt Popen fehl,
        bleibt die laufende App vollständig intakt (Tray läuft, Fenster offen)
        und der Nutzer bekommt einen Hinweis. Kein Sync-Push: der Faktor ist
        lokal, ein 5-s-Push würde den Neustart nur verzögern."""
        from src.main import relaunch_command
        cmd = relaunch_command(
            sys.argv, sys.executable, getattr(sys, "frozen", False))
        try:
            subprocess.Popen(cmd)
        except Exception:
            logging.getLogger(__name__).exception(
                "Neustart für UI-Skalierung fehlgeschlagen")
            themed_showinfo(
                self.root,
                "Neustart nötig",
                "Die Skalierung wird beim nächsten Start der App wirksam.",
            )
            return
        if self._tray is not None:
            self._tray.stop()
        self.root.destroy()
```

- [ ] **Step 3: ui.py — `_open_settings` reicht den Callback durch**

In `src/ui.py`, im `open_settings_dialog(...)`-Aufruf in `_open_settings` (Zeile 323–329), das Keyword `on_request_restart` ergänzen:

```python
        open_settings_dialog(
            self.root, self.settings, self.base_path,
            on_change=_on_change,
            conflicts_store=self.conflicts_store,
            storage=self.storage,
            reservation_store=self.reservation_store,
            on_request_restart=self.restart_for_scaling,
        )
```

- [ ] **Step 4: settings_dialog.py — Import + Signatur erweitern**

In `src/dialogs/settings_dialog.py` Zeile 23 ändern:

```python
from src.settings import WEEKDAY_KEYS, clamp_ui_scale, parse_hourly_rate, resolve_calendar_id
```

Signatur (Zeile 28–30) um den keyword-only Parameter erweitern:

```python
def open_settings_dialog(parent, settings, base_path, on_change, *,
                         conflicts_store=None, storage=None,
                         reservation_store=None, on_request_restart=None):
```

- [ ] **Step 5: settings_dialog.py — „Darstellung"-Sektion einfügen**

In `src/dialogs/settings_dialog.py` **direkt nach** dem `minimize_to_tray`-Checkbutton-Block (endet Zeile 368, `row=20`) und **vor** dem Synchronisations-Header (Zeile 371) einfügen:

```python
    # --- Darstellung (UI-Skalierung, gerätelokal) ---
    display_frame = tk.Frame(dialog, bg=BG)
    display_frame.grid(row=21, column=0, columnspan=2, padx=10, pady=(16, 4),
                       sticky="we")
    tk.Label(
        display_frame, text="— Darstellung —", font=FONT_BOLD,
        bg=BG, fg=TEXT_MUTED,
    ).pack(pady=(0, 4))
    scale_row = tk.Frame(display_frame, bg=BG)
    scale_row.pack(fill="x")
    tk.Label(
        scale_row, text="Skalierung (%):", font=FONT, bg=BG, fg=TEXT,
    ).pack(side=tk.LEFT, padx=(0, 8))
    scale_var = tk.IntVar(value=round(settings.get("ui_scale") * 100))
    tk.Scale(
        scale_row, from_=75, to=200, resolution=5, orient=tk.HORIZONTAL,
        variable=scale_var, length=200,
        bg=BG, fg=TEXT, troughcolor=CELL_BG, highlightthickness=0,
        activebackground=ACCENT, bd=0,
    ).pack(side=tk.LEFT)
    tk.Label(
        display_frame, text="Änderung startet die App neu.", font=FONT_SMALL,
        bg=BG, fg=TEXT_MUTED,
    ).pack(anchor="w", pady=(2, 0))
```

- [ ] **Step 6: settings_dialog.py — nachfolgende Grid-Reihen umnummerieren**

Die neue Sektion belegt Reihe 21. Alle folgenden `.grid(... row=N ...)`-Aufrufe um **+1** erhöhen. Konkret diese Werte ändern (current → neu):

- Synchronisation-Header (`row=21` → `row=22`)
- `cb_sync` (`row=22` → `row=23`)
- Geräte-ID-Label (`row=23` → `row=24`)
- „Letzte Synchronisation"-Label (`row=24` → `row=25`)
- „Konflikte ansehen"-Button (`row=25` → `row=26`)
- `btn_row` (reconnect/import) (`row=26` → `row=27`)
- „Sync-Daten kompaktieren"-Button (`row=27` → `row=28`)
- Google-Kalender-Header (`row=28` → `row=29`)
- `cb_gcal` (`row=29` → `row=30`)
- `cal_combo` (`row=30` → `row=31`)
- „Kalender:"-Label (`row=30` → `row=31`)
- `cal_status` (`row=31` → `row=32`)
- `btn_frame` (Speichern/Abbrechen) (`row=32` → `row=33`)

- [ ] **Step 7: settings_dialog.py — Save-Logik ergänzen**

In `save_settings` (Zeile 713). Direkt **vor** dem `updates = {...}`-Dict (vor Zeile 747) den alten Faktor und den neuen lesen:

```python
        old_scale = settings.get("ui_scale")
        new_scale = clamp_ui_scale(scale_var.get() / 100)
```

Im `updates`-Dict (Zeile 747–761) den Eintrag ergänzen:

```python
            "minimize_to_tray": minimize_to_tray_var.get(),
            "ui_scale": new_scale,
        }
```

Am Ende von `save_settings`, **nach** `dialog.destroy()` (Zeile 776), den Neustart anstoßen:

```python
        on_change()
        dialog.destroy()
        if on_request_restart is not None and new_scale != old_scale:
            on_request_restart()
```

(Reihenfolge wichtig: erst `apply_updates` persistiert den Faktor, dann schließt der Dialog, dann startet der neue Prozess — der den frischen Wert liest.)

- [ ] **Step 8: Volle Suite + Lint**

Run: `pytest -q && ruff check .`
Expected: alle Tests grün (inkl. der bestehenden `tests/test_ui_delete.py`, die `src.ui` importiert — die neuen ui.py/settings_dialog.py-Änderungen dürfen den Import nicht brechen), ruff ohne Findings.

- [ ] **Step 9: Manuell verifizieren (End-to-End)**

Run: `python -m src.main` → Zahnrad → Einstellungen.
- **Renumber-Kontrolle (wichtig, CI fängt das nicht):** den **gesamten** Dialog von oben bis unten durchsehen — alle Sektionen müssen vollständig und **ohne Überlappung/Lücke** rendern: Gmail-Zugangsdaten, Mail-Vorlage, die vier Anzeige-Checkboxen, **Darstellung**, Synchronisation (Checkbox + Geräte-ID + „Letzte Synchronisation" + ggf. Konflikte/Kompaktieren-Button), Google Kalender (Checkbox + „Kalender:"-Combobox + Status), Button-Reihe (Kategorien/Speichern/Abbrechen). Überlappen zwei Zeilen oder fehlt eine, wurde eine `row=`-Nummer falsch verschoben.
- „Darstellung"-Sektion erscheint zwischen den Anzeige-Checkboxen und „— Synchronisation —"; Slider steht auf dem gespeicherten Wert (Default 100).
- Slider auf 125 → „Speichern" → App **startet neu**, Fenster erscheint größer.
- Einstellungen erneut öffnen, **ohne** den Slider zu ändern → „Speichern" → **kein** Neustart, Dialog schließt normal.
- Slider zurück auf 100 → Speichern → App startet neu, Erscheinungsbild wie ursprünglich.

- [ ] **Step 10: Commit**

```bash
git add src/ui.py src/dialogs/settings_dialog.py
git commit -m "feat(ui): UI-Skalierungs-Slider in den Einstellungen + Neustart"
```

---

## Self-Review-Notiz (vom Plan-Autor)

- **Spec-Abdeckung:** Mechanik (T3), Persistenz/`clamp` (T1), Slider+Platzierung (T4), Sofort-Neustart+Fallback (T4 `restart_for_scaling`), `relaunch_command`/`--minimized`-Strip (T2). „Bekannte Grenze" (Paddings) ist bewusst kein Task.
- **Typ-Konsistenz:** `clamp_ui_scale(value)->float` (T1) wird in T3 (`_apply_ui_scaling`) und T4 (`save_settings`) identisch genutzt; `relaunch_command(argv, executable, frozen)->list` (T2) in T4 mit `(sys.argv, sys.executable, getattr(sys,"frozen",False))` aufgerufen.
- **Nicht im Plan:** Versionsbump, CHANGELOG, `release:*`-Label (Release auf Bedarf).
