# Wochenende ausblenden — Design Spec

## Overview

Nicht jeder arbeitet am Wochenende. Aktuell zeigt die Kalender-UI starr alle 7 Wochentage (Mo–So) in der Monats- und Wochenansicht. Diese Spec fügt eine bool-Option `show_weekend` zu den Settings hinzu. Wenn deaktiviert, fallen die Sa/So-Spalten aus der UI weg; Storage, Defaults und Mail-/PDF-Export bleiben unberührt.

**Scope:** Nur die Anzeige in Monats- und Wochenansicht. Keine Änderung an Storage-Format, PDF-Layout, Mail-Body, Entry-Dialog oder Standard-Arbeitszeiten pro Wochentag.

**Out-of-Scope (bewusst):**
- Per-Wochentag-Toggle (z.B. nur Sa ausblenden, So zeigen) — YAGNI; lässt sich später erweitern, wenn echter Bedarf existiert.
- Wochenend-Einträge aus dem Mail-/PDF-Bericht herausfiltern.
- Settings-Migration für Bestandsnutzer (Default `True` = unverändertes Verhalten).

## Scope decisions

| # | Decision | Consequence |
|---|----------|-------------|
| 1 | Neuer Settings-Key `show_weekend: bool`, Default `True` | Bestandsnutzer sehen keine Änderung; passt ins bestehende flache `_coerce`-Schema (`bool` strict) |
| 2 | Wochenende = Sa + So (Index 5, 6 nach `datetime.weekday()`) | Konsistent mit bestehender `is_weekend=col >= 5`-Logik im UI |
| 3 | Footer-Summe summiert nur sichtbare Einträge (Mo–Fr) bei `show_weekend=False` | WYSIWYG — Nutzer ohne Wochenend-Arbeit will keine Geister-Stunden im Total |
| 4 | PDF/Mail-Export bleibt unverändert — exportiert weiterhin alle Einträge inkl. Wochenende | Datenintegrität; ein versehentlich erfasster Sa-Eintrag geht nicht still verloren |
| 5 | Storage bleibt unberührt — Wochenend-Einträge bleiben in `entries.json` | Toggle ist reversibel ohne Datenverlust |
| 6 | Dynamisches 5- vs. 7-Spalten-Grid statt `grid_remove()` auf Sa/So | Kein Probe-Cell-Width-Drift, sauberes `winfo_reqwidth()` für Window-Resize |
| 7 | `_refresh` triggert Window-Geometry-Resize zusätzlich bei Spaltenzahl-Wechsel (nicht nur View-Wechsel) | Fenster schrumpft beim Toggle korrekt auf 5-Spalten-Breite |
| 8 | Versions-Bump auf `1.11.1` (Patch), Changelog-Eintrag, `release:patch`-Label | User-facing additive Option, keine breaking changes |

## 1) Datenmodell

### Settings-Key

In `src/settings.py` wird ein einzelner Key zu `DEFAULTS` hinzugefügt:

```python
DEFAULTS = {
    # ... unverändert ...
    "show_weekend": True,
}
```

Keine Migration nötig: fehlt der Key in einer alten `settings.json`, greift der Default `True` über die bestehende DEFAULTS-Loop in `Settings._load`. Bestandsnutzer sehen exakt dasselbe Verhalten wie heute.

`_coerce` mit `target_type=bool` lehnt strikt nicht-bool ab (siehe `settings.py:48`), d.h. ein manuell auf `"true"` (String) editiertes Feld fällt auf den Default zurück — wie alle anderen Bool-Keys.

## 2) UI: Monats- und Wochenansicht

### Helper

In `src/ui.py` kommt eine zentrale Helper-Methode auf `App`, die alle Render-Pfade abfragen:

```python
def _visible_day_count(self):
    return 7 if self.settings.get("show_weekend") else 5
```

5 = Mo–Fr (`datetime.weekday()` 0..4). 7 = Mo–So.

### `_build_grid_header` (`src/ui.py:383`)

Iteriert nur über die sichtbaren Tage. `is_weekend` (Sa/So-Färbung) entfällt automatisch, weil die Spalten gar nicht mehr existieren:

```python
def _build_grid_header(self, parent):
    n = self._visible_day_count()
    for col, day_name in enumerate(DAYS_DE[:n]):
        fg = TEXT_MUTED if col < 5 else WEEKEND_FG
        tk.Label(
            parent, text=day_name, font=FONT_BOLD, bg=BG, fg=fg,
        ).grid(row=0, column=col, sticky="nsew", padx=2, pady=2)
```

`col < 5` bleibt als Bedingung — bei `n=5` ist sie immer wahr, bei `n=7` greift WEEKEND_FG für Sa/So.

### `_refresh_month` (`src/ui.py:495`)

`monthdayscalendar()` liefert weiterhin 7-spaltige Reihen — wir überspringen die Wochenend-Tage beim Rendern und gridden auf neue Spaltenindizes 0..n-1:

```python
n = self._visible_day_count()
weeks = cal.monthdayscalendar(self.year, self.month)
while len(weeks) < 6:
    weeks.append([0] * 7)

for row, week in enumerate(weeks, start=1):
    for col, day in enumerate(week[:n]):
        # ... bestehende Logik, is_weekend=col >= 5 (greift nur bei n=7)
```

`week[:n]` schneidet die Sa/So-Tage ab. `is_weekend=col >= 5` bleibt als Bedingung — bei `n=5` nie wahr, bei `n=7` wie heute.

### `_refresh_week` (`src/ui.py:555`)

Analog — `dates[:n]` statt `dates`:

```python
n = self._visible_day_count()
for col, day_date in enumerate(dates[:n]):
    # ... bestehende Logik
```

### `_build_grid` (`src/ui.py:242`)

Die `columnconfigure(col, weight=1)`-Schleife wird auf die aktuell sichtbare Spaltenzahl angepasst — und zwar in `_refresh`, weil das Setting zur Build-Zeit noch nicht zwingend stimmt (z.B. nach Toggle).

Aktuelle Logik gridded 7 Spalten beim Frame-Build (`src/ui.py:255-256`). Da überschüssige `columnconfigure`-Einträge bei weniger genutzten Spalten kein Layout-Problem machen (nur leere weitere Spalten würden Platz beanspruchen, aber es gibt keine Children dort), bleibt die initiale 7er-Configure stehen. Entscheidend: **gerendert** wird nur in `0..n-1`.

### `_refresh` (`src/ui.py:334`) — Window-Geometry bei Toggle

Aktuell triggert `_refresh` nur beim View-Wechsel ein explizites `root.geometry()`-Set (`_last_refresh_view`-Check, `src/ui.py:357`). Beim Toggle von `show_weekend` ändert sich nicht der View, sondern die Spaltenzahl — also zusätzliches Tracking:

```python
current_cols = self._visible_day_count()
view_changed = getattr(self, "_last_refresh_view", None) != self.view_mode
cols_changed = getattr(self, "_last_refresh_columns", None) != current_cols

if view_changed or cols_changed:
    self._last_refresh_view = self.view_mode
    self._last_refresh_columns = current_cols
    # ... bestehender Resize-Pfad: inactive-Buffer ersetzen, geometry setzen
```

Der bestehende Resize-Pfad (Destroy inactive Frame, neuer Frame, `root.update_idletasks()`, `root.geometry(reqw × reqh)`) ist bereits robust gegen Cache-Probleme — dieselbe Logik fängt jetzt auch den Spaltenwechsel ab.

### Footer-Summe (`src/ui.py:495-553`, `src/ui.py:555-594`)

Da Wochenend-Tage gar nicht mehr durch die Render-Schleife laufen, wenn `n=5`, werden ihre Stunden auch nicht mehr aufaddiert — `total_hours += self._entry_hours(entry)` wird nur für sichtbare `col`s erreicht. Footer zeigt automatisch nur die sichtbare Summe. Keine Extra-Logik nötig.

## 3) Settings-Dialog

### Aktuelle Struktur (`src/dialogs/settings_dialog.py:178-185`)

Heute gibt es genau eine Checkbox (Autostart) in Row 16. Die neue `show_weekend`-Checkbox kommt direkt darüber (Row 15, ersetzt die aktuelle Platzhalter-Label-Zeile mit den `{zeitraum}`/`{gesamt}`-Hinweisen — die rutscht eine Position).

Bessere Wahl: **Row 16**, Autostart auf **Row 17**, Buttons auf **Row 18**. Hält die bestehenden Mail-Vorlage-Rows (10–15) stabil und vermeidet das Verschieben zu vieler Indizes.

```python
show_weekend_var = tk.BooleanVar(value=settings.get("show_weekend"))
tk.Checkbutton(
    dialog, text="Wochenende (Sa/So) im Kalender anzeigen",
    variable=show_weekend_var, font=FONT,
    bg=BG, fg=TEXT, selectcolor=CELL_BG,
    activebackground=BG, activeforeground=TEXT,
    cursor="hand2",
).grid(row=16, column=0, columnspan=2, padx=10, pady=4, sticky="w")
```

Autostart-Checkbox auf `row=17`, Button-Frame auf `row=18`.

### Save-Pfad (`src/dialogs/settings_dialog.py:230-246`)

Neuer Key im `updates`-Dict:

```python
updates = {
    # ... unverändert ...
    "show_weekend": show_weekend_var.get(),
}
```

`on_change()` (= `App._refresh`) wird wie heute aufgerufen und rendert das Grid mit der neuen Spaltenzahl + triggert den Window-Resize über den `cols_changed`-Pfad.

## 4) Tests

Neue/geänderte Tests in `tests/test_settings.py`:

| Test | Zweck |
|------|-------|
| `test_show_weekend_default_is_true` | Frische `Settings` liefert `show_weekend == True` |
| `test_show_weekend_persists_false` | `set("show_weekend", False)` → neue `Settings`-Instanz aus derselben Datei liefert `False` |
| `test_show_weekend_string_falls_back_to_default` | JSON mit `"show_weekend": "false"` (String) → `_coerce` lehnt ab, Wert bleibt Default `True` |
| `test_show_weekend_missing_falls_back_to_default` | JSON ohne `show_weekend`-Key → `Settings.get("show_weekend") == True` |

Keine Änderungen an `tests/test_report.py`, `tests/test_storage.py` oder `tests/test_time_calc.py` — Storage und Export sind nicht betroffen.

Manuelle Smoke-Tests (Tk-GUI, nicht automatisierbar):
- Default-Verhalten: `show_weekend=True` → Grid zeigt Mo–So in Monats- und Wochenansicht (Regression-Check).
- Settings-Dialog → Checkbox abwählen → Speichern → Grid schrumpft auf 5 Spalten Mo–Fr, Fenster wird schmaler.
- Setting wieder aktivieren → Grid wird wieder 7-spaltig, Fenster wird breiter.
- View-Wechsel Monat ↔ Woche bei `show_weekend=False` funktioniert ohne Geometry-Glitches.
- Bestehender Sa-Eintrag bleibt in `entries.json` (mit Editor prüfen) während `show_weekend=False`.
- Mail-Versand bei `show_weekend=False` enthält weiterhin Wochenend-Einträge im PDF und im HTML-Body.

## 5) Versionierung

- `src/version.py`: `VERSION = "1.11.1"`
- `CHANGELOG.md`: neuer Block für `1.11.1`:
  - „Neue Option: Wochenende im Kalender ausblendbar (Einstellungen → ‚Wochenende (Sa/So) im Kalender anzeigen')"
  - Hinweis: „Wochenend-Einträge bleiben gespeichert und werden weiterhin in Mail/PDF exportiert — nur die Kalender-Anzeige ändert sich."
- PR-Label: `release:patch`

## Open questions

Keine.

## Implementation order

1. `src/settings.py`: `DEFAULTS["show_weekend"] = True` hinzufügen.
2. Tests in `tests/test_settings.py` schreiben & grün.
3. `src/ui.py`: Helper `_visible_day_count`, Render-Schleifen in `_build_grid_header` / `_refresh_month` / `_refresh_week` umstellen, Geometry-Resize-Pfad in `_refresh` um `cols_changed` erweitern.
4. `src/dialogs/settings_dialog.py`: Checkbox + Save-Pfad.
5. Manuelle Smoke-Tests (Tk).
6. `src/version.py` + `CHANGELOG.md` + Label.
