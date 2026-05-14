# Wochenende ausblenden Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Neuer Settings-Toggle `show_weekend`, der die Sa/So-Spalten aus Monats- und Wochenansicht entfernt, ohne Storage, PDF/Mail-Export oder Defaults zu berühren.

**Architecture:** Boolean-Setting (Default `True`, Backward-Compat) wird in `src/settings.py` ergänzt. Ein zentraler Helper `App._visible_day_count()` liefert 5 oder 7. Render-Loops in `_build_grid_header`, `_refresh_month`, `_refresh_week` schneiden ihre Iteration auf `n` Tage; Footer-Summe ergibt sich automatisch, weil unsichtbare Tage nicht durch die Loop laufen. `_refresh` erzwingt Window-Geometry-Resize zusätzlich bei Wechsel der Spaltenzahl.

**Tech Stack:** Python 3, Tkinter, pytest.

**Spec:** `docs/superpowers/specs/2026-05-14-hide-weekends-design.md`

---

## File Structure

| File | Action | Responsibility |
|------|--------|----------------|
| `src/settings.py` | Modify | `DEFAULTS["show_weekend"] = True` |
| `tests/test_settings.py` | Modify | 4 neue Tests (Default, Persistenz, Bool-Strictness, Missing-Key-Fallback) |
| `src/ui.py` | Modify | Helper `_visible_day_count`, Render-Loops mit `[:n]`, Geometry-Resize bei Cols-Wechsel |
| `src/dialogs/settings_dialog.py` | Modify | Neue Checkbox; Row-Shift für Autostart/Buttons; Save-Pfad |
| `src/version.py` | Modify | `VERSION = "1.11.1"` |
| `CHANGELOG.md` | Modify | Neuer Top-Entry für `v1.11.1` |

Keine neuen Dateien, keine Tests-Datei-Splits — alle Änderungen sind additiv und lokal.

---

### Task 1: Settings-Key `show_weekend` mit Tests

**Files:**
- Modify: `src/settings.py` — `DEFAULTS`-Dict
- Test: `tests/test_settings.py` — neue Tests am Ende

- [ ] **Step 1: Failing Tests schreiben**

In `tests/test_settings.py` ans Ende anhängen:

```python


# --- show_weekend (1.11.1) ---


def test_show_weekend_default_is_true(tmp_settings):
    """Frische Settings haben show_weekend=True (Backward-Compat)."""
    assert tmp_settings.get("show_weekend") is True


def test_show_weekend_persists_false(tmp_path):
    """set(False) persistiert über einen Reload."""
    path = str(tmp_path / "settings.json")
    s1 = Settings(path)
    s1.set("show_weekend", False)
    s2 = Settings(path)
    assert s2.get("show_weekend") is False


def test_show_weekend_string_falls_back_to_default(tmp_path, caplog):
    """JSON mit String 'false' wird von _coerce abgelehnt → Default True."""
    path = _write_json(tmp_path, json.dumps({"show_weekend": "false"}))
    with caplog.at_level("WARNING"):
        s = Settings(path)
    assert s.get("show_weekend") is True
    assert any("show_weekend" in rec.message for rec in caplog.records)


def test_show_weekend_missing_key_uses_default(tmp_path):
    """settings.json ohne show_weekend → Default True (alte Installationen)."""
    path = _write_json(tmp_path, json.dumps({"email": "a@b.de"}))
    s = Settings(path)
    assert s.get("show_weekend") is True
```

- [ ] **Step 2: Tests laufen lassen, FAIL erwarten**

Run: `pytest tests/test_settings.py -k show_weekend -v`

Expected: 4× FAIL — `KeyError`/`None`, weil Key noch nicht in `DEFAULTS` ist (bzw. `test_show_weekend_default_is_true` failed mit `None is not True`).

- [ ] **Step 3: Setting hinzufügen**

In `src/settings.py`, in `DEFAULTS`-Dict am Ende einen Eintrag ergänzen (zwischen `default_end_sun` und der schließenden Klammer):

```python
DEFAULTS = {
    # ... unverändert ...
    "default_end_sun": "16:00",
    "show_weekend": True,
}
```

- [ ] **Step 4: Tests laufen lassen, PASS erwarten**

Run: `pytest tests/test_settings.py -v`

Expected: alle Tests grün (insbesondere die 4 neuen + keine Regressionen).

- [ ] **Step 5: Commit**

```
git add src/settings.py tests/test_settings.py
git commit -m "feat(settings): add show_weekend toggle (default True)"
```

---

### Task 2: UI-Helper und Render-Loops auf dynamische Spaltenzahl

**Files:**
- Modify: `src/ui.py` — `_build_grid_header`, `_refresh_month`, `_refresh_week`, neuer Helper `_visible_day_count`

Diese Task hat keine automatisierten Tests — der Tk-Renderpfad ist im Repo bisher nur manuell smoke-getestet (siehe `tests/`-Liste). Die Verifikation erfolgt nach Task 4 in einem manuellen Smoke-Test-Block.

- [ ] **Step 1: Helper `_visible_day_count` hinzufügen**

In `src/ui.py`, direkt vor `_build_grid_header` (zwischen `_refresh` und `_build_grid_header`, also vor Zeile 383), einfügen:

```python
    def _visible_day_count(self):
        """Sichtbare Wochentag-Spalten (5 bei show_weekend=False, sonst 7).

        Wird von _build_grid_header und den Refresh-Pfaden als einzige
        Quelle der Wahrheit konsultiert.
        """
        return 7 if self.settings.get("show_weekend") else 5
```

- [ ] **Step 2: `_build_grid_header` auf `DAYS_DE[:n]` umstellen**

Ersetze in `src/ui.py` die Methode `_build_grid_header` (Zeilen 383–388):

```python
    def _build_grid_header(self, parent):
        n = self._visible_day_count()
        for col, day_name in enumerate(DAYS_DE[:n]):
            fg = TEXT_MUTED if col < 5 else WEEKEND_FG
            tk.Label(
                parent, text=day_name, font=FONT_BOLD, bg=BG, fg=fg,
            ).grid(row=0, column=col, sticky="nsew", padx=2, pady=2)
```

Die `col < 5`-Bedingung bleibt — bei `n=5` ist sie für alle gerenderten Spalten erfüllt (TEXT_MUTED), bei `n=7` greift WEEKEND_FG für Sa (col=5) und So (col=6).

- [ ] **Step 3: `_refresh_month` auf `week[:n]` umstellen**

In `src/ui.py`, in `_refresh_month` direkt vor der `for row, week in enumerate(weeks, start=1):`-Schleife (vor Zeile 526) `n` ermitteln, und in der inneren Schleife `week[:n]` iterieren:

Vorher (Zeilen 522–546):
```python
        weeks = cal.monthdayscalendar(self.year, self.month)
        while len(weeks) < 6:
            weeks.append([0] * 7)

        for row, week in enumerate(weeks, start=1):
            for col, day in enumerate(week):
                if day == 0:
                    tk.Label(new_frame, text="", bg=BG, relief=tk.FLAT).grid(
                        row=row, column=col, sticky="nsew", padx=2, pady=2)
                    continue
                # ... bestehende Zellen-Logik
```

Nachher:
```python
        n = self._visible_day_count()
        weeks = cal.monthdayscalendar(self.year, self.month)
        while len(weeks) < 6:
            weeks.append([0] * 7)

        for row, week in enumerate(weeks, start=1):
            for col, day in enumerate(week[:n]):
                if day == 0:
                    tk.Label(new_frame, text="", bg=BG, relief=tk.FLAT).grid(
                        row=row, column=col, sticky="nsew", padx=2, pady=2)
                    continue
                # ... bestehende Zellen-Logik unverändert (is_weekend=col >= 5 bleibt)
```

Die einzige Änderung am Iterator ist `week` → `week[:n]`. Alles innerhalb der Schleife bleibt unverändert — `is_weekend=col >= 5` wertet bei `n=5` zu `False`, bei `n=7` greift es für Sa/So wie heute.

- [ ] **Step 4: `_refresh_week` auf `dates[:n]` umstellen**

In `src/ui.py`, in `_refresh_week` ändere die `for col, day_date in enumerate(dates):`-Schleife (Zeile 577):

Vorher:
```python
        for col, day_date in enumerate(dates):
            # ... bestehende Logik
```

Nachher:
```python
        n = self._visible_day_count()
        for col, day_date in enumerate(dates[:n]):
            # ... bestehende Logik unverändert
```

`n` wird hier separat ermittelt (statt aus Task 1 zu erben), weil die Refreshes voneinander unabhängig laufen. Es kostet effektiv nichts und hält die Methoden lokal lesbar.

- [ ] **Step 5: Bestehende Tests laufen lassen — keine Regressionen**

Run: `pytest -v`

Expected: alle Tests grün. Diese Änderungen berühren keine Test-Pfade direkt.

- [ ] **Step 6: Commit**

```
git add src/ui.py
git commit -m "feat(ui): render grid with dynamic column count based on show_weekend"
```

---

### Task 3: Window-Geometry-Resize bei Spaltenwechsel

**Files:**
- Modify: `src/ui.py` — `_refresh`

Heute löst `_refresh` nur beim View-Wechsel (`_last_refresh_view`-Check) ein explizites Window-Resize aus. Beim Toggle der `show_weekend`-Checkbox ändert sich der View nicht, aber die natürliche Grid-Breite. Ohne den Resize-Trigger bleibt das Fenster auf der alten Breite stehen.

- [ ] **Step 1: Resize-Trigger in `_refresh` erweitern**

In `src/ui.py`, ersetze den Block ab Zeile 357 (Beginn des `if getattr(...)`-Blocks) bis Ende der Methode `_refresh` (Zeile 381):

Vorher:
```python
        # Geometry nur beim First-Render und bei View-Wechsel neu setzen.
        # Innerhalb derselben View ist die natürliche Größe seit Pad- und
        # Minsize-Fix konstant; ein erneuter `geometry("")`-Aufruf triggert
        # trotzdem einen WM-Repaint und erzeugt sichtbares Flackern.
        if getattr(self, "_last_refresh_view", None) != self.view_mode:
            self._last_refresh_view = self.view_mode
            # Beim View-Wechsel hält der jetzt-inaktive Buffer noch den alten
            # View (z.B. 6-Wochen-Monat während die Wochenansicht aktiv ist).
            # ... Resize-Pfad ...
```

Nachher:
```python
        # Geometry nur beim First-Render, bei View-Wechsel und bei Wechsel der
        # sichtbaren Spaltenzahl (show_weekend-Toggle) neu setzen. Innerhalb
        # derselben Kombination ist die natürliche Größe konstant; ein erneuter
        # `geometry("")`-Aufruf triggert trotzdem einen WM-Repaint und erzeugt
        # sichtbares Flackern.
        current_cols = self._visible_day_count()
        view_changed = getattr(self, "_last_refresh_view", None) != self.view_mode
        cols_changed = getattr(self, "_last_refresh_columns", None) != current_cols
        if view_changed or cols_changed:
            self._last_refresh_view = self.view_mode
            self._last_refresh_columns = current_cols
            # Beim View- oder Spalten-Wechsel hält der jetzt-inaktive Buffer
            # noch den alten Layout-Stand. Children destroyen + rowconfigure
            # zurücksetzen reicht NICHT: Tk's reqheight-Cache des Frames bleibt
            # auf der alten Höhe, `grid_container.reqheight = max(active,
            # inactive)` zieht das Window-Resize hoch. Den Inactive-Frame
            # komplett ersetzen umgeht den Cache — frischer Frame hat
            # reqheight = 0.
            inactive_idx = 1 - self._active_grid_idx
            self.grid_frames[inactive_idx].destroy()
            new_inactive = tk.Frame(self.grid_container, bg=BG)
            new_inactive.grid(row=0, column=0, sticky="nsew")
            for col in range(7):
                new_inactive.columnconfigure(col, weight=1)
            self.grid_frames[inactive_idx] = new_inactive
            # Frisch erstellter Frame liegt in der Stacking-Order obenauf und
            # würde den aktiven Frame verdecken — active wieder nach vorn.
            self.grid_frames[self._active_grid_idx].lift()
            self.root.update_idletasks()
            # Tk schrumpft Toplevels auf Windows nicht zuverlässig via
            # `geometry("")` — explizit auf reqsize setzen erzwingt Resize.
            self.root.geometry(
                f"{self.root.winfo_reqwidth()}x{self.root.winfo_reqheight()}"
            )
```

Die Resize-Logik selbst ist identisch zu vorher — der einzige neue Anteil ist die `cols_changed`-Bedingung und das `_last_refresh_columns`-Tracking.

- [ ] **Step 2: Bestehende Tests laufen lassen**

Run: `pytest -v`

Expected: alle Tests grün.

- [ ] **Step 3: Commit**

```
git add src/ui.py
git commit -m "fix(ui): resize window on show_weekend column-count change"
```

---

### Task 4: Settings-Dialog — Checkbox + Save-Pfad

**Files:**
- Modify: `src/dialogs/settings_dialog.py` — neue Checkbox, Row-Shift für Autostart und Button-Frame, `updates`-Dict

- [ ] **Step 1: Neue Checkbox einfügen, Autostart und Button-Frame verschieben**

In `src/dialogs/settings_dialog.py`, ersetze die Zeilen 178–185 (Autostart-Checkbox-Block):

Vorher:
```python
    autostart_var = tk.BooleanVar(value=settings.get("autostart"))
    tk.Checkbutton(
        dialog, text="Autostart (minimiert bei Anmeldung)",
        variable=autostart_var, font=FONT,
        bg=BG, fg=TEXT, selectcolor=CELL_BG,
        activebackground=BG, activeforeground=TEXT,
        cursor="hand2",
    ).grid(row=16, column=0, columnspan=2, padx=10, pady=8, sticky="w")
```

Nachher:
```python
    show_weekend_var = tk.BooleanVar(value=settings.get("show_weekend"))
    tk.Checkbutton(
        dialog, text="Wochenende (Sa/So) im Kalender anzeigen",
        variable=show_weekend_var, font=FONT,
        bg=BG, fg=TEXT, selectcolor=CELL_BG,
        activebackground=BG, activeforeground=TEXT,
        cursor="hand2",
    ).grid(row=16, column=0, columnspan=2, padx=10, pady=(8, 0), sticky="w")

    autostart_var = tk.BooleanVar(value=settings.get("autostart"))
    tk.Checkbutton(
        dialog, text="Autostart (minimiert bei Anmeldung)",
        variable=autostart_var, font=FONT,
        bg=BG, fg=TEXT, selectcolor=CELL_BG,
        activebackground=BG, activeforeground=TEXT,
        cursor="hand2",
    ).grid(row=17, column=0, columnspan=2, padx=10, pady=(0, 8), sticky="w")
```

- [ ] **Step 2: Button-Frame eine Row nach unten verschieben**

In derselben Datei, ändere den Button-Frame-Block (Zeilen 250–254):

Vorher:
```python
    btn_frame = tk.Frame(dialog, bg=BG)
    btn_frame.grid(row=17, column=0, columnspan=2, pady=12)
```

Nachher:
```python
    btn_frame = tk.Frame(dialog, bg=BG)
    btn_frame.grid(row=18, column=0, columnspan=2, pady=12)
```

- [ ] **Step 3: `show_weekend` ins `updates`-Dict aufnehmen**

In `save_settings` (Zeilen 230–242), ergänze im `updates`-Dict einen neuen Key. Zeile 241 ändern von:

```python
        "state": selected_code,
    }
```

zu:

```python
        "state": selected_code,
        "show_weekend": show_weekend_var.get(),
    }
```

- [ ] **Step 4: Tests laufen lassen — keine Regressionen**

Run: `pytest -v`

Expected: alle Tests grün. Der Settings-Dialog hat keine direkten Tests, die Settings-Persistenz wird durch Task 1 abgedeckt.

- [ ] **Step 5: Manueller Smoke-Test**

App starten:
```
python -m src.main
```

Folgendes prüfen (Häkchen-Liste — keine Code-Änderung in diesem Step):

- [ ] App startet, Default-Verhalten: Monatsansicht zeigt 7 Spalten Mo–So.
- [ ] Settings öffnen → neue Checkbox „Wochenende (Sa/So) im Kalender anzeigen" über der Autostart-Checkbox, **angehakt**.
- [ ] Haken raus, Speichern → Kalender zeigt sofort 5 Spalten Mo–Fr, Fenster wird schmaler.
- [ ] Auf Wochenansicht umschalten → 5 Zellen Mo–Fr.
- [ ] Pfeil rechts/links navigiert weiter wie gewohnt.
- [ ] Settings öffnen, Haken wieder rein, Speichern → Kalender zeigt wieder 7 Spalten, Fenster wird breiter.
- [ ] Auf Wochenansicht umschalten → 7 Zellen, KW-Label korrekt.
- [ ] Wenn `entries.json` einen Sa-Eintrag enthält: Toggle aus → Eintrag ist nicht sichtbar, Footer-Total reduziert sich um die Sa-Stunden. Toggle wieder an → Sa-Eintrag wieder sichtbar, Total korrekt.
- [ ] Mail-Versand (falls Setup vorhanden) bei `show_weekend=False` mit Sa-Eintrag: PDF/HTML enthält weiterhin den Sa-Eintrag (Datenintegrität).

Falls einer der Punkte fehlschlägt: Issue diagnostizieren, fixen, Smoke neu laufen lassen.

- [ ] **Step 6: Commit**

```
git add src/dialogs/settings_dialog.py
git commit -m "feat(settings-dialog): add show_weekend checkbox"
```

---

### Task 5: Version-Bump und Changelog

**Files:**
- Modify: `src/version.py`
- Modify: `CHANGELOG.md`

- [ ] **Step 1: Version anheben**

In `src/version.py`, ersetze die `VERSION`-Zeile:

Vorher:
```python
VERSION = "1.11.0"
```

Nachher:
```python
VERSION = "1.11.1"
```

- [ ] **Step 2: Changelog-Eintrag**

In `CHANGELOG.md`, direkt unter `# Changelog` und vor `## v1.11.0` neuen Block einfügen:

```markdown
## v1.11.1
- Neue Option in den Einstellungen: „Wochenende (Sa/So) im Kalender anzeigen". Wenn deaktiviert, fallen Sa und So aus der Monats- und Wochenansicht weg, das Fenster wird entsprechend schmaler. Bestehende Wochenend-Einträge bleiben gespeichert und werden weiterhin in Mail/PDF exportiert — nur die Kalender-Anzeige ändert sich. Default: angezeigt (kein Verhaltenssprung für Bestandsnutzer)
```

- [ ] **Step 3: Commit**

```
git add src/version.py CHANGELOG.md
git commit -m "chore: bump v1.11.1 + Changelog"
```

---

## Verification

Nach allen Tasks:

- [ ] `pytest -v` — alle Tests grün, insbesondere die 4 neuen `show_weekend`-Tests.
- [ ] Manuelle Smoke-Liste aus Task 4 Step 5 vollständig durchlaufen.
- [ ] `git log --oneline -5` zeigt 5 neue Commits in dieser Reihenfolge:
  - `chore: bump v1.11.1 + Changelog`
  - `feat(settings-dialog): add show_weekend checkbox`
  - `fix(ui): resize window on show_weekend column-count change`
  - `feat(ui): render grid with dynamic column count based on show_weekend`
  - `feat(settings): add show_weekend toggle (default True)`

## Release-Hinweis (außerhalb der Implementation)

Wenn der Feature-Branch nach upstream/master gemerged wird, am PR das Label `release:patch` setzen — `release.yml` baut dann den Installer und veröffentlicht `v1.11.1` automatisch (siehe `CLAUDE.md` Release-Prozess).
