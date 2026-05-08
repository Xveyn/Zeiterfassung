# Standard-Arbeitszeiten pro Wochentag — Design Spec

## Overview

Das Tool kennt heute zwei globale Settings für die Default-Arbeitszeit eines neuen Eintrags: `default_start` und `default_end`. Diese Defaults werden im Settings-Dialog gepflegt und im Entry-Dialog für noch nicht erfasste Tage vorbelegt.

Diese Spec ersetzt die zwei globalen Werte durch **14 Per-Wochentag-Werte** (Start und Ende für Mo–So). Begründung: typische Arbeitswochen haben unterschiedliche Tage (z.B. langer Montag, kurzer Freitag, Sa/So 0 h), und manuelles Korrigieren der Default-Werte beim jedem Eintrag-Anlegen ist Reibung.

Out-of-Scope (bewusst): Pause pro Wochentag, „arbeitsfreie Tage" (Sa/So leer / kein Default), Profile (Sommer/Winter, Urlaubsmodus). YAGNI — kann nachgezogen werden, wenn konkret gewünscht.

## Scope decisions

| # | Decision | Consequence |
|---|----------|-------------|
| 1 | 14 flache Settings-Keys (`default_start_<day>`, `default_end_<day>`) statt verschachteltes Dict | Passt ohne Refactor in `settings.py`'s flaches `_coerce`-Schema; jede einzelne Validierung läuft durch die bestehende Type-Cast-Pipeline |
| 2 | Tag-Suffix: `mon`, `tue`, `wed`, `thu`, `fri`, `sat`, `sun` | Stabil, locale-unabhängig, kompakt; matcht ISO-Wochentag (`datetime.weekday()` 0..6) |
| 3 | Default-Werte: `08:00` / `16:00` für alle 7 Tage | Identisch zu den heutigen globalen Defaults — kein Verhaltenssprung für frische Installationen |
| 4 | Migration in `Settings._load`: alte `default_start` / `default_end` werden auf alle 7 Tage gespiegelt, alte Keys verschwinden beim nächsten Save | Bestehende Nutzer behalten exakt ihr aktuelles Verhalten; alte Keys werden nicht ewig mitgeschleppt |
| 5 | Wenn Per-Tag-Keys teilweise vorhanden sind: Per-Tag-Keys gewinnen, fehlende Tage erben aus altem `default_start`/`default_end`, sonst aus `DEFAULTS` | Robust gegen halbe Migrationen (z.B. nach manuellem JSON-Edit) |
| 6 | Settings-Dialog: Tabelle Mo–So × Start/Ende ersetzt die zwei aktuellen Felder | Kompakt, alle 7 Tage gleichzeitig sichtbar; Sa/So unten passt zur deutschen Lese-Konvention |
| 7 | Entry-Dialog liest Wochentag aus `date_str` und zieht den passenden Per-Tag-Key | Korrekter Default ohne weitere Abhängigkeit |
| 8 | Keine UI-Anzeige des „alten" globalen Default-Wertes nach Migration | YAGNI — nach erstem Save sind die alten Keys weg, der Nutzer sieht nur noch die neue Tabelle |
| 9 | Versions-Bump auf `1.10.0`, CHANGELOG-Eintrag, `release:minor`-Label | User-facing Feature-Erweiterung; keine breaking changes durch Migration |

## 1) Datenmodell

### Settings-Keys

In `src/settings.py` werden die zwei alten Keys aus `DEFAULTS` entfernt und durch 14 neue ersetzt:

```python
DEFAULTS = {
    # ... unverändert: email, default_pause, recipient, autostart, name,
    #     mail_subject, mail_greeting, mail_content, mail_closing,
    #     hourly_rate, state, last_update_check_at, dismissed_version

    "default_start_mon": "08:00",
    "default_start_tue": "08:00",
    "default_start_wed": "08:00",
    "default_start_thu": "08:00",
    "default_start_fri": "08:00",
    "default_start_sat": "08:00",
    "default_start_sun": "08:00",

    "default_end_mon": "16:00",
    "default_end_tue": "16:00",
    "default_end_wed": "16:00",
    "default_end_thu": "16:00",
    "default_end_fri": "16:00",
    "default_end_sat": "16:00",
    "default_end_sun": "16:00",
}

WEEKDAY_KEYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")  # Index = datetime.weekday()
```

`WEEKDAY_KEYS` wird als Modul-Konstante exportiert, damit Settings-Dialog und Entry-Dialog dieselbe Reihenfolge nutzen.

### Migration

`Settings._load` bekommt einen Migrations-Pass **direkt nach dem `isinstance(loaded, dict)`-Guard** (nach `settings.py:74`) und **vor** der DEFAULTS-Loop (vor `settings.py:76`). Wenn das geladene JSON noch alte globale Keys enthält und für einen Tag noch kein Per-Tag-Wert vorliegt, wird der globale Wert hochkopiert:

```python
def _migrate_legacy_default_times(loaded):
    """Spiegelt alte globale default_start/default_end auf Per-Tag-Keys.

    Modifiziert `loaded` in-place. Per-Tag-Keys haben Priorität — wenn ein
    Tag schon einen Wert hat, wird er nicht überschrieben.
    """
    legacy_start = loaded.get("default_start")
    legacy_end = loaded.get("default_end")
    if not (legacy_start or legacy_end):
        return
    for day in WEEKDAY_KEYS:
        if legacy_start and f"default_start_{day}" not in loaded:
            loaded[f"default_start_{day}"] = legacy_start
        if legacy_end and f"default_end_{day}" not in loaded:
            loaded[f"default_end_{day}"] = legacy_end
```

Die alten Keys `default_start` / `default_end` sind nicht mehr in `DEFAULTS`. Die DEFAULTS-Loop ignoriert unbekannte Keys (siehe `settings.py:89`), d.h. sie wandern nicht in `_data`. Beim nächsten `_save_to_disk` werden sie aus dem JSON entfernt — automatisch und sauber.

## 2) Settings-Dialog UI

### Aktuelle Struktur (Zeilen 81–87)

```python
label("Standard-Start:", row=3)
start_var = tk.StringVar(value=settings.get("default_start"))
dark_combo(dialog, start_var, TIME_VALUES).grid(row=3, column=1, padx=10, pady=8)

label("Standard-Ende:", row=4)
end_var = tk.StringVar(value=settings.get("default_end"))
dark_combo(dialog, end_var, TIME_VALUES).grid(row=4, column=1, padx=10, pady=8)
```

### Neue Struktur

Die zwei Zeilen werden durch einen Sub-Frame ersetzt, der alle 7 Wochentage als Tabelle zeigt:

```
Standardzeiten:        Start         Ende
                   Mo  [08:00 v]  [16:00 v]
                   Di  [08:00 v]  [16:00 v]
                   Mi  [08:00 v]  [16:00 v]
                   Do  [08:00 v]  [16:00 v]
                   Fr  [08:00 v]  [16:00 v]
                   Sa  [08:00 v]  [16:00 v]
                   So  [08:00 v]  [16:00 v]
```

Die Header-Zeile (`Start` / `Ende`) sitzt als kleines `FONT_SMALL`-Label oberhalb der jeweiligen Spalte — aus dem Skizze-Code unten ist das die `i=-1`-Zeile vor dem Hauptloop:

```python
tk.Label(times_frame, text="Start", font=FONT_SMALL, bg=BG, fg=TEXT_MUTED).grid(
    row=0, column=1, padx=2)
tk.Label(times_frame, text="Ende", font=FONT_SMALL, bg=BG, fg=TEXT_MUTED).grid(
    row=0, column=2, padx=2)
# Wochentags-Loop dann ab row=1.
```

Skizze (gekürzt):

```python
WEEKDAY_LABELS = ("Mo", "Di", "Mi", "Do", "Fr", "Sa", "So")

label("Standardzeiten:", row=3, sticky="nw", pady=4)

times_frame = tk.Frame(dialog, bg=BG)
times_frame.grid(row=3, column=1, padx=10, pady=4, sticky="w")

tk.Label(times_frame, text="Start", font=FONT_SMALL, bg=BG, fg=TEXT_MUTED).grid(
    row=0, column=1, padx=2)
tk.Label(times_frame, text="Ende", font=FONT_SMALL, bg=BG, fg=TEXT_MUTED).grid(
    row=0, column=2, padx=2)

start_vars = {}
end_vars = {}
for i, (key, lbl) in enumerate(zip(WEEKDAY_KEYS, WEEKDAY_LABELS), start=1):
    tk.Label(times_frame, text=lbl, font=FONT, bg=BG, fg=TEXT, width=3, anchor="w").grid(
        row=i, column=0, padx=(0, 8), pady=2)
    start_vars[key] = tk.StringVar(value=settings.get(f"default_start_{key}"))
    dark_combo(times_frame, start_vars[key], TIME_VALUES).grid(row=i, column=1, padx=2, pady=2)
    end_vars[key] = tk.StringVar(value=settings.get(f"default_end_{key}"))
    dark_combo(times_frame, end_vars[key], TIME_VALUES).grid(row=i, column=2, padx=2, pady=2)
```

Alle nachfolgenden `row=`-Indizes (Standard-Pause, Empfänger, Name, …) bleiben unverändert — der Sub-Frame nimmt nur eine Grid-Zelle ein. Der Dialog wird nur leicht höher (7 schmale Zeilen statt 2 normale + 5 schmale ≈ +5 Zeilenhöhen).

### Validierung

Beim Save läuft jede der 7 Zeilen durch `validate_entry(start, end)`. Schlägt eine fehl, wird sie mit Wochentags-Label genannt und der Save abgebrochen:

```python
for key, lbl in zip(WEEKDAY_KEYS, WEEKDAY_LABELS):
    ok, msg = validate_entry(start_vars[key].get(), end_vars[key].get())
    if not ok:
        messagebox.showerror(
            "Standard-Arbeitszeit ungültig",
            f"{lbl}: {msg}",
            parent=dialog,
        )
        return
```

Der bisherige Single-Validation-Block (Zeilen 157–160) wird durch obigen Loop ersetzt.

**`default_pause` bleibt global.** Pause-Zeit wird _nicht_ pro Wochentag geführt (siehe Out-of-Scope). Der bestehende Pause-Combobox in Zeile 89–91 bleibt unverändert. Das hier ist eine bewusste Asymmetrie — vorzeitige Symmetrie wäre Over-Engineering.

### Persistierung

Im `set_many`-Aufruf werden die alten Keys durch 14 Per-Tag-Keys ersetzt:

```python
updates = {
    "autostart": new_autostart,
    "email": email_var.get(),
    "default_pause": int(pause_var.get()),
    # ... rest unverändert
}
for key in WEEKDAY_KEYS:
    updates[f"default_start_{key}"] = start_vars[key].get()
    updates[f"default_end_{key}"] = end_vars[key].get()
settings.set_many(updates)
```

## 3) Entry-Dialog: Wochentag-bezogene Defaults

### Aktuelle Struktur (`src/dialogs/entry_dialog.py:32, 37`)

```python
start_var = tk.StringVar(value=entry["start"] if entry else settings.get("default_start"))
end_var = tk.StringVar(value=entry["end"] if entry else settings.get("default_end"))
```

### Neue Struktur

Wochentag aus `date_str` ableiten, passenden Suffix mappen:

```python
weekday_idx = datetime.date.fromisoformat(date_str).weekday()  # 0=Mo, 6=So
weekday_key = WEEKDAY_KEYS[weekday_idx]

start_var = tk.StringVar(
    value=entry["start"] if entry else settings.get(f"default_start_{weekday_key}")
)
end_var = tk.StringVar(
    value=entry["end"] if entry else settings.get(f"default_end_{weekday_key}")
)
```

`WEEKDAY_KEYS` wird aus `src.settings` importiert. `entry_dialog.py` importiert bisher nichts aus `src.settings` — es kommt also eine **neue** Import-Zeile dazu:

```python
from src.settings import WEEKDAY_KEYS
```

`datetime` wird im Dialog bereits importiert (Zeile 1).

## 4) Tests

Neue/geänderte Tests in `tests/test_settings.py`:

| Test | Zweck |
|------|-------|
| `test_per_weekday_defaults_present` | Frische `Settings` hat alle 14 Per-Tag-Keys, jeweils `"08:00"` / `"16:00"` |
| `test_old_default_start_end_no_longer_in_defaults` | `Settings.get("default_start")` / `default_end` liefert `None` (keine globalen Keys mehr) |
| `test_migration_legacy_to_per_weekday` | `settings.json` mit `{"default_start": "09:30", "default_end": "17:00"}` → nach Load: alle 7 Tage haben `09:30` / `17:00` |
| `test_migration_partial_legacy_only_start` | Nur `default_start` im JSON → alle 7 `default_start_*` migriert, `default_end_*` bleibt Default |
| `test_migration_partial_legacy_only_end` | Symmetrischer Fall: nur `default_end` im JSON → alle 7 `default_end_*` migriert, `default_start_*` bleibt Default |
| `test_migration_per_day_wins_over_legacy` | JSON mit `{"default_start": "09:00", "default_start_mon": "07:00"}` → `mon` bleibt `07:00`, andere Tage `09:00` |
| `test_migration_drops_legacy_keys_on_save` | Nach Migration + irgendeinem `set_many` enthält `settings.json` keine `default_start` / `default_end` Keys mehr |

Geänderte Tests:
- `test_load_unknown_key_is_ignored` (`tests/test_settings.py:125`) bleibt unverändert in der Logik, aber das Beispiel `old_field` ist weiter unbekannt.

Manuelle Smoke-Tests (nicht automatisierbar, da Tk-GUI):
- Settings-Dialog: alle 7 Wochentage editierbar, ungültige Eingabe (z.B. Ende vor Start) wirft Fehlermeldung mit Wochentags-Label.
- Entry-Dialog: an einem Mittwoch geöffnet → Default zieht `default_start_wed`. An einem Sonntag → `default_start_sun`.
- Bestehende `settings.json` (vor Update): alte Werte werden auf alle 7 Tage übernommen, beim ersten Save sind alte Keys weg.

## 5) Versionierung

- `src/version.py`: `VERSION = "1.10.0"`
- `CHANGELOG.md`: neuer Block für `1.10.0` mit User-facing Beschreibung („Standard-Arbeitszeiten lassen sich jetzt pro Wochentag konfigurieren") und Migrations-Hinweis („Bestehende globale Werte werden automatisch auf alle Wochentage übernommen").
- PR-Label: `release:minor`

## Open questions

Keine.

## Implementation order

1. `src/settings.py`: `WEEKDAY_KEYS`, neue DEFAULTS, alte Keys raus, Migration in `_load`.
2. Tests in `tests/test_settings.py` schreiben & grün.
3. `src/dialogs/entry_dialog.py`: Wochentag-Lookup.
4. `src/dialogs/settings_dialog.py`: Tabellen-UI + Loop-Validation + neue Save-Logik.
5. Manuelle Smoke-Tests (Tk).
6. `src/version.py` + `CHANGELOG.md` + Label.
