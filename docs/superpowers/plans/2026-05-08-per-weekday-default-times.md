# Standard-Arbeitszeiten pro Wochentag — Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ersetze die zwei globalen Settings-Keys `default_start` / `default_end` durch 14 Per-Wochentag-Keys, mit nahtloser Migration und einer Mo–So-Tabelle im Settings-Dialog.

**Architecture:** Settings-Modell (flach, `WEEKDAY_KEYS`-Konstante + 14 DEFAULTS-Keys + Migrations-Pass in `_load`). Tk-Settings-Dialog: 7×3-Grid in einem Sub-Frame. Tk-Entry-Dialog: `weekday()` aus `date_str` indiziert das richtige Per-Tag-Setting. Tests pinnen Migration und Defaults.

**Tech Stack:** Python 3, Tkinter, pytest. Keine neuen Dependencies.

**Spec:** `docs/superpowers/specs/2026-05-08-per-weekday-default-times-design.md`

---

## File Structure

| File | Action | Responsibility |
|------|--------|----------------|
| `src/settings.py` | Modify | Neue `WEEKDAY_KEYS`-Konstante, DEFAULTS um 14 Keys erweitert, alte zwei Keys entfernt, `_migrate_legacy_default_times`-Helper, Aufruf in `_load` |
| `tests/test_settings.py` | Modify | Sieben neue Tests für Defaults und Migration |
| `src/dialogs/entry_dialog.py` | Modify | Wochentag aus `date_str` ableiten, passenden Per-Tag-Default ziehen, neue Import-Zeile |
| `src/dialogs/settings_dialog.py` | Modify | Zwei alte Felder durch 7×3-Sub-Frame ersetzen, Loop-Validierung, 14 Keys im `set_many` |
| `src/version.py` | Modify | `1.9.2` → `1.10.0` |
| `CHANGELOG.md` | Modify | Neuer `v1.10.0`-Block am Anfang |

---

## Chunk 1: Settings-Modell + Tests (TDD)

### Task 1: Tests für Per-Wochentag-Defaults und Migration schreiben

**Files:**
- Modify: `tests/test_settings.py` (am Ende anhängen, ohne bestehende Tests zu ändern)

- [ ] **Step 1: Tests anhängen**

An das Ende von `tests/test_settings.py` (nach `test_load_toplevel_not_dict_resets_to_defaults`) anhängen:

```python


# --- Per-Wochentag-Defaults (1.10.0) ---

WEEKDAY_SUFFIXES = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


def test_per_weekday_defaults_present(tmp_settings):
    """Frische Settings haben für alle 7 Tage je 08:00 / 16:00."""
    for day in WEEKDAY_SUFFIXES:
        assert tmp_settings.get(f"default_start_{day}") == "08:00"
        assert tmp_settings.get(f"default_end_{day}") == "16:00"


def test_old_default_start_end_no_longer_in_defaults(tmp_settings):
    """Die alten globalen Keys existieren nicht mehr — get liefert None."""
    assert tmp_settings.get("default_start") is None
    assert tmp_settings.get("default_end") is None


def test_migration_legacy_to_per_weekday(tmp_path):
    """Alte default_start/default_end werden auf alle 7 Tage gespiegelt."""
    path = _write_json(tmp_path, json.dumps({
        "default_start": "09:30",
        "default_end": "17:00",
    }))
    s = Settings(path)
    for day in WEEKDAY_SUFFIXES:
        assert s.get(f"default_start_{day}") == "09:30"
        assert s.get(f"default_end_{day}") == "17:00"


def test_migration_partial_legacy_only_start(tmp_path):
    """Nur default_start im JSON: alle 7 default_start_* migriert,
    default_end_* bleibt Default."""
    path = _write_json(tmp_path, json.dumps({"default_start": "07:15"}))
    s = Settings(path)
    for day in WEEKDAY_SUFFIXES:
        assert s.get(f"default_start_{day}") == "07:15"
        assert s.get(f"default_end_{day}") == "16:00"  # Default


def test_migration_partial_legacy_only_end(tmp_path):
    """Symmetrisch: nur default_end im JSON."""
    path = _write_json(tmp_path, json.dumps({"default_end": "18:30"}))
    s = Settings(path)
    for day in WEEKDAY_SUFFIXES:
        assert s.get(f"default_start_{day}") == "08:00"  # Default
        assert s.get(f"default_end_{day}") == "18:30"


def test_migration_per_day_wins_over_legacy(tmp_path):
    """Per-Tag-Keys schlagen das alte Globalfeld."""
    path = _write_json(tmp_path, json.dumps({
        "default_start": "09:00",
        "default_start_mon": "07:00",
    }))
    s = Settings(path)
    assert s.get("default_start_mon") == "07:00"
    for day in ("tue", "wed", "thu", "fri", "sat", "sun"):
        assert s.get(f"default_start_{day}") == "09:00"


def test_migration_drops_legacy_keys_on_save(tmp_path):
    """Nach Migration + irgendeinem set_many sind die alten Keys
    nicht mehr in settings.json."""
    path = _write_json(tmp_path, json.dumps({
        "default_start": "09:30",
        "default_end": "17:00",
    }))
    s = Settings(path)
    s.set("email", "trigger@save.de")  # erzwingt Disk-Write
    with open(path, "r", encoding="utf-8") as f:
        on_disk = json.load(f)
    assert "default_start" not in on_disk
    assert "default_end" not in on_disk
    # Per-Tag-Keys sind drin
    assert on_disk["default_start_mon"] == "09:30"
    assert on_disk["default_end_sun"] == "17:00"
```

- [ ] **Step 2: Tests laufen lassen — müssen FEHLEN**

Run: `pytest tests/test_settings.py -v`
Expected: 7 neue Tests FAIL (z.B. `assert "08:00" == None` oder `KeyError`), alle bestehenden grün.

- [ ] **Step 3: Commit (red phase)**

```bash
git add tests/test_settings.py
git commit -m "test(settings): per-weekday defaults + legacy migration (red)"
```

---

### Task 2: Settings.py — WEEKDAY_KEYS, neue DEFAULTS, Migration

**Files:**
- Modify: `src/settings.py` — DEFAULTS, neue Konstante, `_migrate_legacy_default_times`, Aufruf in `_load`

- [ ] **Step 1: WEEKDAY_KEYS-Konstante hinzufügen**

In `src/settings.py` direkt **vor** dem `DEFAULTS = {`-Block (also vor Zeile 5):

```python
WEEKDAY_KEYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")  # Index = datetime.weekday()
```

- [ ] **Step 2: DEFAULTS-Dict ändern**

In `src/settings.py` die Zeilen 5–21 (`DEFAULTS = { ... }`) wie folgt ersetzen:

```python
DEFAULTS = {
    "email": "",
    "default_pause": 30,
    "recipient": "",
    "autostart": False,
    "name": "",
    "mail_subject": "Zeiterfassung — {zeitraum}",
    "mail_greeting": "Sehr geehrte Damen und Herren,",
    "mail_content": "anbei erhalten Sie meine Zeiterfassung für den Zeitraum {zeitraum}.",
    "mail_closing": "Mit freundlichen Grüßen",
    "hourly_rate": 0.0,
    "state": "",
    "last_update_check_at": "",
    "dismissed_version": "",
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
```

(Die alten `"default_start"` / `"default_end"`-Zeilen sind damit raus.)

- [ ] **Step 3: Migrations-Helper definieren**

In `src/settings.py` direkt **nach** dem `_coerce`-Block (nach Zeile 47), **vor** `class Settings`:

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

- [ ] **Step 4: Migration in `_load` aufrufen**

In `Settings._load` (`src/settings.py:56`) den Aufruf direkt nach dem `isinstance(loaded, dict)`-Guard und vor der DEFAULTS-Loop einfügen. Konkret zwischen den heutigen Zeilen 74 und 76 (also zwischen `return` und dem `for key, default_value in DEFAULTS.items():`):

```python
        if not isinstance(loaded, dict):
            log.warning(
                "settings.json hat unerwartetes Toplevel-Format (%s), "
                "verwerfe Inhalt und verwende Defaults",
                type(loaded).__name__,
            )
            self._data = dict(DEFAULTS)
            return

        _migrate_legacy_default_times(loaded)  # <- NEU

        for key, default_value in DEFAULTS.items():
            ...
```

- [ ] **Step 5: Tests laufen lassen — müssen GRÜN sein**

Run: `pytest tests/test_settings.py -v`
Expected: alle Tests passen (alte + 7 neue).

- [ ] **Step 6: Commit (green phase)**

```bash
git add src/settings.py
git commit -m "feat(settings): per-weekday default times + legacy migration"
```

---

## Chunk 2: Entry-Dialog (Wochentag-Lookup)

### Task 3: Entry-Dialog auf Per-Wochentag-Defaults umstellen

**Files:**
- Modify: `src/dialogs/entry_dialog.py` — Import + zwei Zeilen

- [ ] **Step 1: Bestehende Tests laufen lassen (Baseline)**

Run: `pytest -v`
Expected: alles grün. Wenn nicht: STOP — vor der Änderung Baseline reparieren.

- [ ] **Step 2: Import ergänzen**

In `src/dialogs/entry_dialog.py` nach dem bestehenden `from src.holidays_de import get_holidays` (Zeile 5) eine neue Zeile einfügen:

```python
from src.settings import WEEKDAY_KEYS
```

Resultierender Import-Block (Zeilen 1–11):

```python
import datetime
import tkinter as tk
from tkinter import messagebox

from src.holidays_de import get_holidays
from src.settings import WEEKDAY_KEYS
from src.theme import (
    BG, FONT, PAUSE_VALUES, TEXT, TIME_VALUES,
    apply_combobox_style, center_dialog_on_parent,
    dark_combo, primary_button, secondary_button,
)
from src.time_utils import validate_entry
```

- [ ] **Step 3: Default-Lookup pro Wochentag**

In `src/dialogs/entry_dialog.py` die Zeilen 32 und 37 ersetzen. Der ganze Block sieht danach so aus (Zeilen ~30–38):

```python
    tk.Label(dialog, text="Start:", font=FONT, bg=BG, fg=TEXT).grid(
        row=0, column=0, padx=10, pady=8, sticky="w")
    weekday_key = WEEKDAY_KEYS[datetime.date.fromisoformat(date_str).weekday()]
    start_var = tk.StringVar(
        value=entry["start"] if entry else settings.get(f"default_start_{weekday_key}")
    )
    dark_combo(dialog, start_var, TIME_VALUES).grid(row=0, column=1, padx=10, pady=8)

    tk.Label(dialog, text="Ende:", font=FONT, bg=BG, fg=TEXT).grid(
        row=1, column=0, padx=10, pady=8, sticky="w")
    end_var = tk.StringVar(
        value=entry["end"] if entry else settings.get(f"default_end_{weekday_key}")
    )
    dark_combo(dialog, end_var, TIME_VALUES).grid(row=1, column=1, padx=10, pady=8)
```

`weekday_key` wird einmal berechnet und für beide Lookups genutzt.

- [ ] **Step 4: Pytest erneut laufen lassen**

Run: `pytest -v`
Expected: alles grün (entry_dialog.py hat keine direkten Tests, aber Import-Pfad-Fehler würden auffliegen).

- [ ] **Step 5: Manueller Smoke-Test**

App starten:
```bash
python -m src.main
```
- Auf einen **Mittwoch** klicken (im Kalender) → Eintrag-Dialog: Start zeigt aktuell konfigurierten `default_start_wed`-Wert.
- Auf einen **Sonntag** klicken → Start zeigt `default_start_sun`-Wert.
- Auf einen **bestehenden** Eintrag klicken → zeigt die gespeicherten Werte (nicht die Defaults).

Wenn alle drei Fälle stimmen: weiter. Sonst zurück zu Step 3.

- [ ] **Step 6: Commit**

```bash
git add src/dialogs/entry_dialog.py
git commit -m "feat(entry-dialog): pull default times by weekday"
```

---

## Chunk 3: Settings-Dialog UI

### Task 4: Settings-Dialog auf 7×Mo–So-Tabelle umbauen

**Files:**
- Modify: `src/dialogs/settings_dialog.py` — Imports, Zeilen 81–87, Validation 157–160, Save 197–198

- [ ] **Step 1: Imports erweitern**

In `src/dialogs/settings_dialog.py` Zeile 11 (theme-Import) um `FONT_SMALL` und `TEXT_MUTED` ergänzen, falls noch nicht drin:

```python
from src.theme import (
    ACCENT, BG, CELL_BG, FONT, FONT_BOLD, FONT_SMALL,
    PAUSE_VALUES, STATUS_OK, TEXT, TEXT_MUTED, TIME_VALUES,
    apply_combobox_style, center_dialog_on_parent,
    dark_combo, dark_entry, dark_text,
    primary_button, secondary_button,
)
```

(Beide existieren bereits im Import-Block — verifizieren mit `grep "FONT_SMALL\|TEXT_MUTED" src/dialogs/settings_dialog.py`. Falls schon vorhanden: Step skippen.)

Zusätzlich `WEEKDAY_KEYS` aus settings importieren — neue Zeile nach `from src.holidays_de import STATES`:

```python
from src.settings import WEEKDAY_KEYS
```

- [ ] **Step 2: WEEKDAY_LABELS-Konstante**

Direkt nach dem Import-Block in `src/dialogs/settings_dialog.py` (vor `def open_settings_dialog`):

```python
WEEKDAY_LABELS = ("Mo", "Di", "Mi", "Do", "Fr", "Sa", "So")
```

- [ ] **Step 3: Standardzeiten-Block ersetzen**

Die Zeilen 81–87 in `src/dialogs/settings_dialog.py`:

```python
    label("Standard-Start:", row=3)
    start_var = tk.StringVar(value=settings.get("default_start"))
    dark_combo(dialog, start_var, TIME_VALUES).grid(row=3, column=1, padx=10, pady=8)

    label("Standard-Ende:", row=4)
    end_var = tk.StringVar(value=settings.get("default_end"))
    dark_combo(dialog, end_var, TIME_VALUES).grid(row=4, column=1, padx=10, pady=8)
```

ersetzen durch:

```python
    label("Standardzeiten:", row=3, sticky="nw", pady=4)

    times_frame = tk.Frame(dialog, bg=BG)
    times_frame.grid(row=3, column=1, rowspan=2, padx=10, pady=4, sticky="w")

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
        dark_combo(times_frame, start_vars[key], TIME_VALUES).grid(
            row=i, column=1, padx=2, pady=2)
        end_vars[key] = tk.StringVar(value=settings.get(f"default_end_{key}"))
        dark_combo(times_frame, end_vars[key], TIME_VALUES).grid(
            row=i, column=2, padx=2, pady=2)
```

`rowspan=2` deckt die Zellen ab, die früher Standard-Start (row=3) und Standard-Ende (row=4) hatten — die nachfolgenden `row=5`-Zeilen (`default_pause`) bleiben dadurch unverändert. Falls das Layout zu eng wird (Sub-Frame hat 8 Zeilen, Grid-Cells nur 2): Sub-Frame darf bei `sticky="w"` über die Grid-Zelle hinauswachsen, das ist OK für Tk.

- [ ] **Step 4: Validation-Block ersetzen**

Die Zeilen 157–160 in `src/dialogs/settings_dialog.py`:

```python
        ok, msg = validate_entry(start_var.get(), end_var.get())
        if not ok:
            messagebox.showerror("Standard-Arbeitszeit ungültig", msg, parent=dialog)
            return
```

ersetzen durch:

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

- [ ] **Step 5: Save-Block (`set_many`) ersetzen**

In `src/dialogs/settings_dialog.py` die zwei Zeilen 197–198:

```python
            "default_start": start_var.get(),
            "default_end": end_var.get(),
```

durch nichts (entfernen) ersetzen — die Per-Tag-Keys werden in einem zweiten Schritt drangepappt.

Direkt **vor** dem `settings.set_many({...})`-Aufruf (also vor dem heutigen Zeile-194-`settings.set_many({`) ein Update-Dict aufbauen:

Konkret das ganze `set_many`-Konstrukt (Zeilen 194–208) so umbauen:

```python
        updates = {
            "autostart": new_autostart,
            "email": email_var.get(),
            "default_pause": int(pause_var.get()),
            "recipient": recipient_var.get(),
            "name": name_var.get(),
            "mail_subject": subject_var.get(),
            "mail_greeting": greeting_var.get(),
            "mail_content": content_text.get("1.0", "end-1c"),
            "mail_closing": closing_text.get("1.0", "end-1c"),
            "hourly_rate": hourly_rate,
            "state": selected_code,
        }
        for key in WEEKDAY_KEYS:
            updates[f"default_start_{key}"] = start_vars[key].get()
            updates[f"default_end_{key}"] = end_vars[key].get()
        settings.set_many(updates)
```

- [ ] **Step 6: Pytest laufen lassen**

Run: `pytest -v`
Expected: alles grün. settings_dialog.py hat keine direkten Tests, aber Import- oder Syntaxfehler würden auffliegen.

- [ ] **Step 7: Manueller Smoke-Test**

App starten:
```bash
python -m src.main
```
1. Einstellungen öffnen → Tabelle Mo–So mit Header `Start` / `Ende` ist sichtbar; alle 7 Zeilen tragen die aktuellen Default-Werte.
2. Mittwoch-Start auf `10:00` und Mittwoch-Ende auf `18:30` setzen → Speichern → Dialog schließt ohne Fehler.
3. Einstellungen erneut öffnen → Mittwochs-Werte sind persistiert.
4. Auf einen **Mittwoch** im Kalender klicken (neuer Tag, kein Eintrag) → Defaults im Entry-Dialog sind `10:00` / `18:30`.
5. Einstellungen → Mo-Ende auf `06:00` (also vor Start `08:00`) → Speichern → Fehlermeldung „Mo: ..." — Dialog bleibt offen.
6. `settings.json` (im Datenordner) öffnen und prüfen: alte `default_start` / `default_end`-Keys nicht mehr drin, nur die 14 neuen.

Wenn alle 6 Punkte stimmen: weiter. Sonst zurück zum richtigen Step.

- [ ] **Step 8: Commit**

```bash
git add src/dialogs/settings_dialog.py
git commit -m "feat(settings-dialog): per-weekday default times table (Mo–So)"
```

---

## Chunk 4: Versionierung & Release

### Task 5: Version + CHANGELOG

**Files:**
- Modify: `src/version.py`
- Modify: `CHANGELOG.md`

- [ ] **Step 1: Version bump**

`src/version.py`:
```python
VERSION = "1.10.0"
```

- [ ] **Step 2: CHANGELOG-Eintrag**

Ganz oben in `CHANGELOG.md` (direkt nach `# Changelog`-Header, vor `## v1.9.2`) einfügen:

```markdown
## v1.10.0
- Standard-Arbeitszeiten lassen sich jetzt **pro Wochentag** konfigurieren — der Settings-Dialog zeigt eine Tabelle Mo–So mit je einem Start- und Endefeld, die der Eintrags-Dialog beim Anlegen eines neuen Tages automatisch zieht. Bestehende globale Werte (`Standard-Start` / `Standard-Ende`) werden beim ersten App-Start auf alle sieben Wochentage übernommen, sodass sich für Bestandsnutzer nichts ändert, bis sie einzelne Tage abweichend einstellen. Pause bleibt eine globale Einstellung
```

- [ ] **Step 3: Pytest abschließend laufen lassen**

Run: `pytest -v`
Expected: 100% grün.

- [ ] **Step 4: Commit + Push**

```bash
git add src/version.py CHANGELOG.md
git commit -m "release: v1.10.0 (per-weekday default times)"
git push
```

**Branch-Hinweis:** Wenn die Arbeit auf `fix/codequality-runde-1` (1.9.2-Branch) gestartet wurde, sollte sie auf einen frischen Branch (z.B. `feat/per-weekday-default-times`) ausgelagert werden — das Feature hat thematisch nichts mit dem Codequality-Cleanup zu tun. Ein neuer Branch braucht beim ersten Push `-u`:

```bash
git push -u origin feat/per-weekday-default-times
```

- [ ] **Step 5: PR vorbereiten**

PR von `fix/codequality-runde-1` (oder neuem Branch je nach Workflow) gegen `master` öffnen. Label `release:minor` setzen — der Release-Workflow liest `VERSION` aus `src/version.py` und baut Tag/Release nach Merge.

```bash
gh pr create --title "feat: Standard-Arbeitszeiten pro Wochentag (1.10.0)" --body "$(cat <<'EOF'
## Summary
- 14 flache Per-Wochentag-Settings-Keys statt zwei globalen
- Migration spiegelt alte Werte beim ersten Laden auf alle sieben Tage
- Settings-Dialog: Mo–So-Tabelle ersetzt die zwei alten Felder
- Entry-Dialog: Default je nach Wochentag des Datums
- Pause bleibt bewusst global

## Test plan
- [x] `pytest` grün
- [x] Manueller Smoke: 7 Wochentage editierbar, Validation pro Zeile
- [x] Manueller Smoke: Bestands-`settings.json` migriert sauber, alte Keys verschwinden beim ersten Save
- [x] Manueller Smoke: Entry-Dialog zieht korrekten Wochentag-Default

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

Anschließend `release:minor`-Label im PR setzen (manuell im GitHub-UI oder via `gh pr edit <num> --add-label release:minor`).

---

## Done-Definition

- Alle pytest-Tests grün
- Settings-Dialog zeigt Mo–So-Tabelle, Werte persistieren in `settings.json`
- Entry-Dialog zieht je Wochentag den passenden Default
- `settings.json` einer migrieten Installation enthält **keine** `default_start` / `default_end`-Keys mehr nach erstem Save
- `src/version.py` = `1.10.0`, CHANGELOG-Eintrag vorhanden
- PR mit `release:minor`-Label gemerged → Release-Workflow baut Tag, Installer, Release
