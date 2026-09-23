# Einstellungs-Dialog #132 — PR 1: Formular-Bausteine — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Gemeinsame Formular-Bausteine im Theme (`Form`, Ausgrauen, Scroll-Container mit Mausrad, Leertext, themed Speichern-Rückfrage) plus ihre Tk-freie, getestete Logik — ohne sichtbare Änderung an bestehenden Dialogen.

**Architecture:** Tk-freie Entscheidungen liegen in `src/theme/form_logic.py` (Theme-intern) und `src/dialogs/settings_dialog/form_model.py` (Dialog-spezifisch, `is_dirty`); beide vollständig annotiert und getestet. `src/theme/form.py` ist eine neue Theme-Schicht über `widgets`, die diese Entscheidungen in Tk umsetzt. Alles wird über `src/theme/__init__.py` re-exportiert.

**Tech Stack:** Python 3.12, Tkinter/ttk (clam-Theme), pytest, ruff, pyright 1.1.411.

**Spec:** `docs/superpowers/specs/2026-09-18-einstellungsdialog-132-design.md` (Abschnitt „PR 1 — Bausteine")

## Global Constraints

- Branch: `feat/einstellungen-132` (existiert, enthält die Spec). Nicht auf `master` committen.
- Farben und Schriften bleiben; neu in `src/theme/palette.py` sind **nur** `SEPARATOR = "#2e3150"` und `TEXT_DISABLED = "#5c5c70"`.
- Importiert wird über `from src.theme import …`; jeder neue öffentliche Name wird in `src/theme/__init__.py` importiert **und** in `__all__` eingetragen.
- Theme-Schichtung bleibt zyklenfrei: `form_logic` hängt an nichts (reine stdlib); `form` importiert `palette`, `fonts`, `widgets`, `form_logic`. Das Theme importiert nie aus `src/dialogs/`.
- Tk-freie Module (`src/theme/form_logic.py`, `src/dialogs/settings_dialog/form_model.py`) sind vollständig annotiert (Rückgabetyp + alle Parameter) und stehen in `ANNOTATED_MODULES` in `tests/test_type_annotations.py`.
- Wer `create_dialog` ruft, ruft `center_dialog_on_parent` (Paarungsregel, `tests/test_dialog_reveal.py`).
- Kein stummes `except`: jeder Handler loggt (`log.debug(..., exc_info=True)`) oder trägt eine Begründung im Handler (`tests/test_catch_all_handlers.py`).
- Bestehende Dialoge ändern sich sichtbar **nicht** — mit einer Ausnahme, die erst im Final Review auffiel: der Tages-Dialog deaktiviert die Erinnerungs-Combobox, solange der Reservierungsblock leer ist (`entry_dialog.py`); ihr Pfeil ist mit den neuen Combobox-Disabled-Farben gedämpft statt rot. Gewollt (gesperrt sieht jetzt gesperrt aus), in der PR-Beschreibung offengelegt.
- Kommentare/Docstrings deutsch, im Stil der Umgebung (erklären das Warum).
- Commits: Nachricht per Datei (`git commit -F <datei>`), nie per Heredoc/`-m` mit Zeilenumbrüchen. Temp-Datei: `C:/Users/SvenB/.claude/jobs/58e9cd06/tmp/commit-msg.txt`. Jede Nachricht endet mit der Leerzeile + `Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>`.
- Nach jeder Aufgabe grün: `python -m pytest -q`, `ruff check .`, `npx --yes pyright@1.1.411` (0 errors). Alle aus dem Repo-Root `D:\Programme (x86)\Zeiterfassung_Repo\Zeiterfassung`.
- Keine echten Nutzerdaten: das Smoke-Skript (Task 6) baut nur Theme-Widgets, keine `Settings`/`Storage`.

---

## File Structure

| Datei | Verantwortung |
|---|---|
| `src/theme/form_logic.py` (neu) | Tk-frei: aktive Gruppen, Mausrad-Schritte und -Ziel, Tk-Pfad-Vergleich, Körperhöhe |
| `src/dialogs/settings_dialog/form_model.py` (neu) | Tk-frei: `is_dirty` (ab PR 2 auch `SaveCoordinator`) |
| `src/theme/palette.py` | + `SEPARATOR`, `TEXT_DISABLED` |
| `src/theme/widgets.py` | `_LabelButton` bekommt `_zeit_disabled`/`_zeit_colors`; `label_button` ignoriert Klicks im gesperrten Zustand; Combobox-Disabled-Farben |
| `src/theme/form.py` (neu) | `set_enabled`, `Form`, `empty_state` |
| `src/theme/messagebox.py` | + `themed_ask_save_changes` |
| `src/theme/__init__.py` | Re-Exporte, Schichtungs-Docstring |
| `tests/test_form_logic.py` (neu) | Tests zu `form_logic` |
| `tests/test_form_model.py` (neu) | Tests zu `is_dirty` |
| `tests/test_type_annotations.py` | Whitelist + 2 Module |
| `src/CLAUDE.md`, `CLAUDE.md` | Doku der neuen Schicht |

---

### Task 1: Tk-freie Theme-Logik `form_logic.py`

**Files:**
- Create: `src/theme/form_logic.py`
- Create: `tests/test_form_logic.py`
- Modify: `tests/test_type_annotations.py` (Liste `ANNOTATED_MODULES`)

**Interfaces:**
- Produces:
  - `BODY_MAX_HEIGHT: int = 600`, `SCREEN_MARGIN: int = 160`, `MIN_BODY_HEIGHT: int = 200`
  - `WheelRoute = Literal["widget", "form", "form_block"]`
  - `enabled_states(parents: Mapping[str, str | None], values: Mapping[str, bool]) -> dict[str, bool]`
  - `wheel_units(system: str, delta: int, num: int | None) -> int`
  - `wheel_route(widget_class: str) -> WheelRoute`
  - `is_descendant(path: str, ancestor: str) -> bool`
  - `body_height(natural: int, scale: float, screen_height: int) -> int`

- [ ] **Step 1: Write the failing tests**

`tests/test_form_logic.py`:

```python
"""Tests der Tk-freien Formular-Logik (theme/form_logic.py, #132)."""

import pytest

from src.theme.form_logic import (
    BODY_MAX_HEIGHT,
    MIN_BODY_HEIGHT,
    SCREEN_MARGIN,
    body_height,
    enabled_states,
    is_descendant,
    wheel_route,
    wheel_units,
)


# --- enabled_states ---------------------------------------------------------

def test_top_level_group_follows_its_switch():
    assert enabled_states({"g0": None}, {"g0": True}) == {"g0": True}
    assert enabled_states({"g0": None}, {"g0": False}) == {"g0": False}


def test_nested_group_needs_every_switch_above():
    parents = {"g0": None, "g1": "g0"}
    assert enabled_states(parents, {"g0": True, "g1": True}) == {"g0": True, "g1": True}
    # Unterpunkt an, Hauptpunkt aus → Unterpunkt bleibt grau.
    assert enabled_states(parents, {"g0": False, "g1": True})["g1"] is False
    assert enabled_states(parents, {"g0": True, "g1": False})["g1"] is False


def test_three_levels_deep():
    parents = {"a": None, "b": "a", "c": "b"}
    values = {"a": True, "b": False, "c": True}
    assert enabled_states(parents, values) == {"a": True, "b": False, "c": False}


def test_missing_switch_value_counts_as_off():
    assert enabled_states({"g0": None, "g1": "g0"}, {"g1": True}) == {"g0": False, "g1": False}


def test_cycle_is_a_programming_error():
    with pytest.raises(ValueError):
        enabled_states({"a": "b", "b": "a"}, {"a": True, "b": True})


# --- wheel_units ------------------------------------------------------------

def test_x11_buttons_4_and_5():
    assert wheel_units("Linux", 0, 4) == -1
    assert wheel_units("Linux", 0, 5) == 1


def test_windows_delta_in_multiples_of_120():
    assert wheel_units("Windows", 120, None) == -1
    assert wheel_units("Windows", -240, None) == 2


def test_windows_touchpad_fraction_still_moves_one_step():
    assert wheel_units("Windows", 30, None) == -1
    assert wheel_units("Windows", -30, None) == 1


def test_macos_raw_delta():
    assert wheel_units("Darwin", 3, None) == -3
    assert wheel_units("Darwin", -1, None) == 1


def test_zero_delta_does_not_scroll():
    assert wheel_units("Windows", 0, None) == 0
    assert wheel_units("Darwin", 0, None) == 0


# --- wheel_route ------------------------------------------------------------

def test_self_scrolling_widgets_keep_the_wheel():
    assert wheel_route("Text") == "widget"
    assert wheel_route("Listbox") == "widget"


def test_combobox_is_protected():
    assert wheel_route("TCombobox") == "form_block"


def test_everything_else_scrolls_the_form():
    for cls in ("Label", "Frame", "Entry", "Checkbutton", "Canvas", "TScrollbar"):
        assert wheel_route(cls) == "form"


# --- is_descendant ----------------------------------------------------------

def test_descendant_by_tk_path():
    assert is_descendant(".!toplevel.!canvas.!frame.!label", ".!toplevel.!canvas")
    assert is_descendant(".!toplevel.!canvas", ".!toplevel.!canvas")


def test_sibling_with_common_prefix_is_not_a_descendant():
    # ".!canvas2" beginnt mit ".!canvas", ist aber ein Geschwister.
    assert not is_descendant(".!toplevel.!canvas2.!label", ".!toplevel.!canvas")


def test_everything_descends_from_root():
    assert is_descendant(".!toplevel", ".")


# --- body_height ------------------------------------------------------------

def test_short_content_keeps_its_natural_height():
    assert body_height(300, 1.0, 1440) == 300


def test_capped_at_max_height_times_scale():
    assert body_height(2000, 1.0, 1440) == BODY_MAX_HEIGHT
    assert body_height(2000, 1.5, 1440) == round(BODY_MAX_HEIGHT * 1.5)


def test_capped_by_screen_height():
    # 1.5 × 600 = 900, aber 1000 − 1.5 × 160 = 760 ist enger.
    assert body_height(2000, 1.5, 1000) == 1000 - round(SCREEN_MARGIN * 1.5)


def test_tiny_screen_keeps_a_usable_minimum():
    assert body_height(2000, 2.0, 400) == MIN_BODY_HEIGHT


def test_minimum_never_pads_short_content():
    assert body_height(120, 2.0, 400) == 120
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_form_logic.py -q`
Expected: FAIL / collection error `ModuleNotFoundError: No module named 'src.theme.form_logic'`

- [ ] **Step 3: Write the implementation**

`src/theme/form_logic.py`:

```python
# src/theme/form_logic.py
"""Tk-freie Entscheidungen der Formular-Bausteine (`theme/form.py`, #132).

Was hier liegt, braucht kein Fenster und ist deshalb getestet
(`tests/test_form_logic.py`): welche abhängigen Optionen aktiv sind, wohin ein
Mausrad-Schritt geht und wie hoch ein scrollbarer Tab-Körper werden darf.
`form.py` ruft nur noch hierher und setzt das Ergebnis in Tk um.

Unterste Schicht neben `palette`: reine stdlib, hängt an nichts.
"""

from collections.abc import Mapping
from typing import Literal

# Höhe eines scrollbaren Formular-Körpers bei 100 % Skalierung. 600 px
# entsprechen in etwa dem heutigen Tab-Körper des App-Tabs — der Dialog wird
# durch den Umbau also nie höher als vorher.
BODY_MAX_HEIGHT = 600
# Abstand, den der Körper zum Bildschirmrand lassen muss: Titelleiste,
# Reiterleiste, Knopfreihe und Taskleiste.
SCREEN_MARGIN = 160
# Untergrenze auf winzigen Bildschirmen — darunter wäre der Körper nicht
# mehr bedienbar, selbst mit Scrollleiste.
MIN_BODY_HEIGHT = 200

WheelRoute = Literal["widget", "form", "form_block"]

# Widgets, die das Mausrad selbst auswerten (eigene Klassen-Bindings).
_SELF_SCROLLING = frozenset({"Text", "Listbox"})
# Widgets, die beim Rad ihren WERT ändern — beim Scrollen des Formulars
# verstellte man sie sonst versehentlich.
_VALUE_ON_WHEEL = frozenset({"TCombobox"})


def enabled_states(
    parents: Mapping[str, str | None], values: Mapping[str, bool],
) -> dict[str, bool]:
    """Welche Gruppen abhängiger Optionen aktiv sind.

    `parents` ordnet jeder Gruppe ihre übergeordnete Gruppe zu (None = oberste
    Ebene), `values` den Zustand ihres Schalters. Aktiv ist eine Gruppe genau
    dann, wenn ihr eigener Schalter UND alle Schalter darüber an sind — ein
    eingeschalteter Unterpunkt unter einem ausgeschalteten Hauptpunkt bleibt
    grau. Fehlt ein Schalterwert, gilt er als aus. Ein Zyklus ist ein
    Programmierfehler und wirft ValueError."""
    result: dict[str, bool] = {}

    def resolve(group: str, seen: frozenset[str]) -> bool:
        if group in result:
            return result[group]
        if group in seen:
            raise ValueError(f"Zyklus in den Abhängigkeiten bei {group!r}")
        parent = parents.get(group)
        active = bool(values.get(group, False))
        if parent is not None:
            active = resolve(parent, seen | {group}) and active
        result[group] = active
        return active

    for group in parents:
        resolve(group, frozenset())
    return {group: result[group] for group in parents}


def wheel_units(system: str, delta: int, num: int | None) -> int:
    """Scrollschritte (`yview_scroll`-Einheiten, positiv = nach unten) aus
    einem Mausrad-Event.

    X11 meldet das Rad als Taste 4 (hoch) / 5 (runter), Windows als `delta`
    in Vielfachen von 120, macOS als kleine Rohwerte. Touchpads unter Windows
    liefern Bruchteile von 120 — die zählen als ein Schritt statt als null,
    sonst stünde das Formular beim sanften Wischen still."""
    if num == 4:
        return -1
    if num == 5:
        return 1
    if delta == 0:
        return 0
    if system == "Darwin":
        return -delta
    steps = int(delta / 120)
    if steps == 0:
        steps = 1 if delta > 0 else -1
    return -steps


def wheel_route(widget_class: str) -> WheelRoute:
    """Wohin ein Mausrad-Schritt über einem Widget dieser Klasse geht:
    `"widget"` — das Widget scrollt selbst, das Formular bleibt stehen;
    `"form_block"` — das Formular scrollt, das Widget darf den Schritt NICHT
    sehen; `"form"` — das Formular scrollt."""
    if widget_class in _SELF_SCROLLING:
        return "widget"
    if widget_class in _VALUE_ON_WHEEL:
        return "form_block"
    return "form"


def is_descendant(path: str, ancestor: str) -> bool:
    """True, wenn der Tk-Pfad `path` das Widget `ancestor` selbst oder eines
    seiner Kinder bezeichnet. Verglichen wird komponentenweise — `.!canvas2`
    ist kein Kind von `.!canvas`, auch wenn der String so beginnt."""
    if ancestor == ".":
        return path.startswith(".")
    return path == ancestor or path.startswith(ancestor + ".")


def body_height(natural: int, scale: float, screen_height: int) -> int:
    """Sichtbare Höhe eines scrollbaren Formular-Körpers.

    Höchstens `BODY_MAX_HEIGHT` (mitskaliert) und höchstens so viel, wie der
    Bildschirm abzüglich `SCREEN_MARGIN` hergibt — aber nie weniger als
    `MIN_BODY_HEIGHT`. Kurze Formulare behalten ihre natürliche Höhe; die
    Untergrenze polstert sie nicht auf."""
    cap = round(BODY_MAX_HEIGHT * scale)
    room = screen_height - round(SCREEN_MARGIN * scale)
    limit = max(MIN_BODY_HEIGHT, min(cap, room))
    return min(natural, limit)
```

Then add to `ANNOTATED_MODULES` in `tests/test_type_annotations.py`, directly after `"src/platform_open.py",`:

```python
    # Einstellungs-Dialog-Bausteine (#132)
    "src/theme/form_logic.py",
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_form_logic.py tests/test_type_annotations.py -q`
Expected: all PASS

- [ ] **Step 5: Full checks**

Run: `python -m pytest -q` ; `ruff check .` ; `npx --yes pyright@1.1.411`
Expected: all green, pyright `0 errors`

- [ ] **Step 6: Commit**

Nachricht (in `C:/Users/SvenB/.claude/jobs/58e9cd06/tmp/commit-msg.txt`):

```
feat(theme): Tk-freie Formular-Logik für die Einstellungs-Bausteine (#132)

enabled_states (verschachtelte Abhängigkeiten), wheel_units/wheel_route
(Mausrad je Plattform und Widget), is_descendant (Tk-Pfad) und body_height
(Höhe des scrollbaren Tab-Körpers). Reine stdlib, getestet, annotiert.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
```

```
git add src/theme/form_logic.py tests/test_form_logic.py tests/test_type_annotations.py
git commit -F "C:/Users/SvenB/.claude/jobs/58e9cd06/tmp/commit-msg.txt"
```

---

### Task 2: `is_dirty` in `form_model.py`

**Files:**
- Create: `src/dialogs/settings_dialog/form_model.py`
- Create: `tests/test_form_model.py`
- Modify: `tests/test_type_annotations.py` (Liste `ANNOTATED_MODULES`)

**Interfaces:**
- Produces:
  - `normalize(value: Any) -> Any`
  - `is_dirty(baseline: Mapping[str, Any], current: Mapping[str, Any]) -> bool`

- [ ] **Step 1: Write the failing tests**

`tests/test_form_model.py`:

```python
"""Tests der Tk-freien Logik des Einstellungs-Dialogs (form_model.py, #132)."""

from src.dialogs.settings_dialog.form_model import is_dirty


def test_identical_values_are_clean():
    assert not is_dirty({"a": 1, "b": "x"}, {"a": 1, "b": "x"})


def test_changed_value_is_dirty():
    assert is_dirty({"name": "Anna"}, {"name": "Ben"})


def test_number_and_numeric_string_are_equal():
    # Settings speichern 20.0, ein Entry liefert "20" — keine Änderung.
    assert not is_dirty({"h": 20.0}, {"h": "20"})
    assert not is_dirty({"h": 20}, {"h": 20.0})
    assert not is_dirty({"h": "20.5"}, {"h": 20.5})
    assert not is_dirty({"h": " 20 "}, {"h": 20})


def test_time_string_stays_a_string():
    assert not is_dirty({"t": "08:00"}, {"t": "08:00"})
    assert is_dirty({"t": "08:00"}, {"t": "08:30"})


def test_bool_is_not_confused_with_number():
    assert is_dirty({"on": True}, {"on": 1})
    assert is_dirty({"on": False}, {"on": "0"})


def test_line_endings_are_normalized():
    assert not is_dirty({"text": "a\r\nb"}, {"text": "a\nb"})


def test_trailing_whitespace_in_text_counts():
    assert is_dirty({"text": "Gruß"}, {"text": "Gruß "})


def test_missing_or_extra_key_is_dirty():
    assert is_dirty({"a": 1}, {"a": 1, "b": 2})
    assert is_dirty({"a": 1, "b": 2}, {"a": 1})


def test_nested_structures_are_compared_deeply():
    assert not is_dirty({"d": {"x": "1"}}, {"d": {"x": 1}})
    assert is_dirty({"l": [1, 2]}, {"l": [1, 3]})


def test_none_is_its_own_value():
    assert not is_dirty({"v": None}, {"v": None})
    assert is_dirty({"v": None}, {"v": ""})
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_form_model.py -q`
Expected: collection error `ModuleNotFoundError: No module named 'src.dialogs.settings_dialog.form_model'`

- [ ] **Step 3: Write the implementation**

`src/dialogs/settings_dialog/form_model.py`:

```python
"""Tk-freie Logik des Einstellungs-Dialogs (#132).

Hier entscheidet sich, ob ein Tab ungespeicherte Änderungen hat. PR 2 ergänzt
den `SaveCoordinator` (Speichern je Tab, Rückfrage beim Verlassen).
"""

import re
from collections.abc import Mapping
from typing import Any

# Nur schlichte Dezimalzahlen gelten als Zahl — "08:00", "nan" oder "1e3"
# bleiben Text. So wird aus einer Uhrzeit nie versehentlich eine Zahl.
_NUMBER = re.compile(r"-?\d+(\.\d+)?")


def normalize(value: Any) -> Any:
    """Vergleichsform eines Formularwerts.

    Ein Tk-Entry liefert Text, `settings.json` hält Zahlen: `"20"`, `20` und
    `20.0` sind derselbe gespeicherte Wert und dürfen nicht als Änderung
    zählen. Bools bleiben eigen (`True` ist hier nicht `1`), Zeilenenden
    werden vereinheitlicht (Tk-Text liefert `\\n`, eine alte Datei evtl.
    `\\r\\n`). Leerzeichen in Text bleiben signifikant — wer sie tippt,
    ändert etwas."""
    if isinstance(value, bool):
        return ("bool", value)
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        text = value.replace("\r\n", "\n")
        stripped = text.strip()
        if _NUMBER.fullmatch(stripped):
            return float(stripped)
        return text
    if isinstance(value, Mapping):
        return {key: normalize(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [normalize(item) for item in value]
    return value


def is_dirty(baseline: Mapping[str, Any], current: Mapping[str, Any]) -> bool:
    """True, wenn sich der Formularstand `current` vom gespeicherten Stand
    `baseline` unterscheidet (Vergleich über `normalize`). Ein fehlender oder
    zusätzlicher Schlüssel zählt als Änderung."""
    return normalize(baseline) != normalize(current)
```

Add to `ANNOTATED_MODULES` in `tests/test_type_annotations.py`, directly after the `"src/theme/form_logic.py",` line from Task 1:

```python
    "src/dialogs/settings_dialog/form_model.py",
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_form_model.py tests/test_type_annotations.py -q`
Expected: all PASS

- [ ] **Step 5: Full checks**

Run: `python -m pytest -q` ; `ruff check .` ; `npx --yes pyright@1.1.411`
Expected: all green

- [ ] **Step 6: Commit**

```
feat(einstellungen): is_dirty als Grundlage für Speichern je Tab (#132)

Vergleicht Formularstand und gespeicherten Stand typ-normalisiert: "20",
20 und 20.0 sind gleich, Uhrzeiten bleiben Text, Bools bleiben eigen,
Zeilenenden werden vereinheitlicht.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
```

```
git add src/dialogs/settings_dialog/form_model.py tests/test_form_model.py tests/test_type_annotations.py
git commit -F "C:/Users/SvenB/.claude/jobs/58e9cd06/tmp/commit-msg.txt"
```

---

### Task 3: Palette, gesperrte Label-Buttons, Combobox-Disabled-Farben und `set_enabled`

**Files:**
- Modify: `src/theme/palette.py` (ans Ende)
- Modify: `src/theme/widgets.py` (`_LabelButton`, `label_button.on_click`, `apply_combobox_style` → `style.map("Dark.TCombobox", …)`)
- Create: `src/theme/form.py` (zunächst nur `set_enabled`)
- Modify: `src/theme/__init__.py` (Re-Exporte)

**Interfaces:**
- Consumes: nichts aus Task 1/2.
- Produces:
  - `SEPARATOR: str`, `TEXT_DISABLED: str` (aus `src.theme`)
  - `set_enabled(widget, on: bool) -> None` (aus `src.theme`)
  - `_LabelButton._zeit_disabled: bool` (Default `False`) — `label_button` ruft seinen `command` nicht, solange es `True` ist.

Diese Aufgabe hat keine Tk-freie Logik und damit keinen Unit-Test (Scope-Grenze „Getestet wird Logik, nicht UI"). Geprüft wird sie im Smoke-Skript (Task 6). Bestehende Tests müssen grün bleiben.

- [ ] **Step 1: Palette ergänzen**

Ans Ende von `src/theme/palette.py`:

```python
# Formular-Bausteine (theme/form.py, #132): die feine Linie hinter
# Abschnitts-Überschriften und die Farbe ausgegrauter Felder. Beide bewusst
# dunkler als TEXT_MUTED — ein Hinweistext (gedämpft) soll lesbar bleiben,
# ein ausgegrautes Feld klar zurücktreten.
SEPARATOR = "#2e3150"
TEXT_DISABLED = "#5c5c70"
```

- [ ] **Step 2: `_LabelButton` und `label_button` erweitern**

In `src/theme/widgets.py` die Klasse ersetzen:

```python
class _LabelButton(tk.Frame):
    """tk.Frame mit zusätzlichen Attributen für das label_button-Konstrukt."""
    _label: tk.Label
    _colors: _ToggleColors
    # Von `theme.form.set_enabled` gesetzt: gesperrt heißt auch der Klick
    # tut nichts. Die set_*_button_enabled-Helfer unten ändern dagegen nur
    # die Optik und verlangen einen Callback, der selbst prüft.
    _zeit_disabled: bool = False
    _zeit_colors: _ToggleColors
```

und in `label_button` den Klick-Handler ersetzen:

```python
    def on_click(_e):
        if frame._zeit_disabled:
            return
        command()
```

- [ ] **Step 3: Combobox-Disabled-Farben**

In `apply_combobox_style` den `style.map("Dark.TCombobox", …)`-Aufruf ersetzen durch (ttk nimmt den ERSTEN passenden Zustand — ein deaktiviertes readonly-Feld trägt beide Zustände, also muss `disabled` vorne stehen):

```python
    # "disabled" steht jeweils VOR "readonly": ttk nimmt den ersten passenden
    # Zustand, und ein ausgegrautes Feld (theme.form.set_enabled) ist
    # zugleich readonly — sonst bliebe sein Text in voller Helligkeit.
    style.map("Dark.TCombobox",
        fieldbackground=[("readonly", CELL_BG)],
        background=[("readonly", CELL_BG), ("active", CELL_BG)],
        foreground=[("disabled", TEXT_DISABLED)],
        selectbackground=[("readonly", CELL_BG)],
        selectforeground=[("disabled", TEXT_DISABLED), ("readonly", TEXT)],
        bordercolor=[("focus", ACCENT)],
        arrowcolor=[("disabled", TEXT_DISABLED), ("readonly", ACCENT), ("active", ACCENT)],
    )
```

und `TEXT_DISABLED` zum Import aus `src.theme.palette` oben in `widgets.py` hinzufügen.

- [ ] **Step 4: `src/theme/form.py` mit `set_enabled` anlegen**

```python
# src/theme/form.py
"""Formular-Bausteine des Dark-Themes (#132).

Ein Formular ist ein Raster mit zwei Spalten — links die Beschriftung, rechts
das Bedienelement —, gegliedert in linksbündige Abschnitte. Abhängige Optionen
werden eingerückt und ausgegraut, solange ihr Schalter aus ist. Auf Wunsch
scrollt der Formular-Körper, statt den Dialog aus dem Bildschirm wachsen zu
lassen.

Die Entscheidungen dahinter liegen Tk-frei in `form_logic.py` und sind dort
getestet; hier steht nur ihre Umsetzung in Tk.
"""

import logging
import tkinter as tk
from tkinter import ttk

from src.theme.palette import CELL_BG, TEXT, TEXT_DISABLED
from src.theme.widgets import _LabelButton, _ToggleColors

log = logging.getLogger(__name__)


def set_enabled(widget, on):
    """Schaltet ein Widget bedienbar oder ausgegraut — Zustand UND Farbe.

    Kennt jede Widget-Art der Dialoge: die Label-Buttons aus `widgets`, alle
    ttk-Widgets (Combobox), `tk.Entry`, Check-/Radiobuttons, `tk.Text`,
    `tk.Label` und Container (`tk.Frame`), deren Kinder rekursiv folgen. Ein
    ausgegrautes Feld behält seinen Wert."""
    if isinstance(widget, _LabelButton):
        _set_label_button_enabled(widget, on)
        return
    if isinstance(widget, ttk.Widget):
        widget.state(["!disabled"] if on else ["disabled"])
        return
    state = tk.NORMAL if on else tk.DISABLED
    if isinstance(widget, tk.Entry):
        widget.config(state=state, disabledbackground=CELL_BG,
                      disabledforeground=TEXT_DISABLED)
    elif isinstance(widget, (tk.Checkbutton, tk.Radiobutton)):
        widget.config(state=state, disabledforeground=TEXT_DISABLED)
    elif isinstance(widget, tk.Text):
        widget.config(state=state, fg=TEXT if on else TEXT_DISABLED)
    elif isinstance(widget, tk.Label):
        _set_label_enabled(widget, on)
    elif isinstance(widget, tk.Frame):
        for child in widget.winfo_children():
            set_enabled(child, on)
    else:
        try:
            widget.config(state=state)
        except tk.TclError:
            # Widget ohne -state (etwa ein Canvas): bleibt, wie es ist.
            log.debug("set_enabled: %s kennt keinen state",
                      widget.winfo_class(), exc_info=True)


def _set_label_enabled(label, on):
    """Labels kennen keinen gesperrten Zustand mit eigener Farbe — also die
    Schriftfarbe tauschen und die ursprüngliche merken (ein Hinweis ist
    gedämpft, eine Beschriftung nicht; beide sollen zurück)."""
    if not on:
        if getattr(label, "_zeit_fg", None) is None:
            setattr(label, "_zeit_fg", label.cget("fg"))
        label.config(fg=TEXT_DISABLED)
    else:
        original = getattr(label, "_zeit_fg", None)
        if original is not None:
            label.config(fg=original)


def _set_label_button_enabled(btn: _LabelButton, on):
    """Gesperrt: Schrift in TEXT_DISABLED, kein Hover-Wechsel, Pfeil-Cursor,
    und der Klick tut nichts (`label_button` prüft `_zeit_disabled`). Die
    Farben davor werden gemerkt und beim Entsperren zurückgesetzt."""
    if on == (not btn._zeit_disabled):
        return
    if not on:
        btn._zeit_colors = btn._colors
        bg = btn._colors["bg"]
        btn._colors = _ToggleColors(
            bg=bg, fg=TEXT_DISABLED, hover_bg=bg, hover_fg=TEXT_DISABLED)
    else:
        btn._colors = btn._zeit_colors
    btn._zeit_disabled = not on
    cursor = "hand2" if on else "arrow"
    c = btn._colors
    btn.config(bg=c["bg"], cursor=cursor)
    btn._label.config(bg=c["bg"], fg=c["fg"], cursor=cursor)
```

- [ ] **Step 5: Re-Exporte**

In `src/theme/__init__.py`:
- im `palette`-Import `SEPARATOR` und `TEXT_DISABLED` ergänzen (alphabetisch einsortiert),
- nach dem `widgets`-Import einfügen:

```python
from src.theme.form import (  # noqa: F401
    set_enabled,
)
```

- in `__all__`: unter `# palette` `"SEPARATOR"` und `"TEXT_DISABLED"` ergänzen; nach dem `# widgets`-Block einen Block

```python
    # form
    "set_enabled",
```

- [ ] **Step 6: Full checks**

Run: `python -m pytest -q` ; `ruff check .` ; `npx --yes pyright@1.1.411`
Expected: all green. Zusätzlich: `python -c "import src.theme as t; print(t.set_enabled, t.SEPARATOR, t.TEXT_DISABLED)"` läuft ohne Fehler.

- [ ] **Step 7: Commit**

```
feat(theme): set_enabled, gesperrte Label-Buttons, Disabled-Farben (#132)

Ein zentraler Helfer schaltet jedes Dialog-Widget bedienbar oder grau.
Label-Buttons ignorieren im gesperrten Zustand auch den Klick; deaktivierte
Comboboxen bekommen gedämpfte Farben. Palette: SEPARATOR, TEXT_DISABLED.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
```

```
git add src/theme/palette.py src/theme/widgets.py src/theme/form.py src/theme/__init__.py
git commit -F "C:/Users/SvenB/.claude/jobs/58e9cd06/tmp/commit-msg.txt"
```

---

### Task 4: `Form` (Raster, Abschnitte, Abhängigkeiten, Scroll-Container) und `empty_state`

**Files:**
- Modify: `src/theme/form.py` (ergänzen)
- Modify: `src/theme/__init__.py` (Re-Exporte `Form`, `empty_state`)

**Interfaces:**
- Consumes: `enabled_states`, `wheel_units`, `wheel_route`, `is_descendant`, `body_height` (Task 1); `set_enabled`, `SEPARATOR` (Task 3); `secondary_button`, `FONT`, `FONT_BOLD`, `FONT_SMALL`, `BG`, `CELL_BG`, `TEXT`, `TEXT_MUTED`.
- Produces (PR 2/3 bauen darauf):
  - `class Form(parent, *, scroll: bool = False, scale: float = 1.0)`
    - `form.frame` — äußeres Widget (vom Aufrufer zu packen/ins Notebook zu legen)
    - `form.body` — Parent für alle Widgets, die an `row`/`block` gehen
    - `form.section(title: str, hint: str | None = None) -> tk.Frame`
    - `form.row(label: str, widget) -> tk.Label`
    - `form.check(text: str, var) -> tk.Checkbutton`
    - `form.hint(text: str) -> tk.Label`
    - `form.buttons(*specs: tuple[str, Callable[[], None]]) -> list`
    - `form.block(widget, *, pady=4)` — Widget über beide Spalten, gibt es zurück
    - `form.depends_on(var)` — Kontextmanager
    - `form.refresh_enabled() -> None`
  - `empty_state(parent, text: str, *, bg: str = BG) -> tk.Label`

- [ ] **Step 1: Imports in `src/theme/form.py` erweitern**

Den Importblock von `form.py` ersetzen durch:

```python
import logging
import platform
import tkinter as tk
from collections.abc import Callable
from contextlib import contextmanager
from tkinter import ttk

from src.theme.palette import BG, CELL_BG, SEPARATOR, TEXT, TEXT_DISABLED, TEXT_MUTED
from src.theme.fonts import FONT, FONT_BOLD, FONT_SMALL
from src.theme.widgets import _LabelButton, _ToggleColors, secondary_button
from src.theme.form_logic import (
    body_height, enabled_states, is_descendant, wheel_route, wheel_units,
)
```

- [ ] **Step 2: `Form` und `empty_state` ans Ende von `form.py` anfügen**

```python
# Einrückung je Abhängigkeitsebene (Basis 100 %, mitskaliert).
INDENT = 22
# Rand links/rechts innerhalb des Formulars.
_EDGE = 12
# Abstand vor jeder Abschnitts-Überschrift außer der ersten.
_SECTION_GAP = 16
# Kleinste Umbruchbreite eines Hinweises, bevor das Formular gemessen ist.
_MIN_WRAP = 200
_WHEEL_EVENTS = ("<MouseWheel>", "<Button-4>", "<Button-5>")


class Form:
    """Ein Formular = ein Raster mit zwei Spalten, gegliedert in Abschnitte.

    Weil alle Abschnitte im selben Raster liegen, fluchten die Beschriftungen
    über das ganze Formular; die Spaltenbreite ergibt sich aus der längsten
    Beschriftung. Zeilen zählt `Form` selbst.

        form = Form(tab_frame, scroll=True, scale=ui_scale)
        form.frame.pack(fill="both", expand=True)
        form.section("Werkstudenten-Limit")
        form.check("Wochenlimit prüfen", wsl_var)
        with form.depends_on(wsl_var):
            form.row("Max. Stunden", dark_entry(form.body, hours_var, width=6))

    Widgets für `row`/`block` werden mit `form.body` als Parent gebaut.

    `scroll=True` legt den Körper in einen Canvas mit Scrollleiste: er wird
    höchstens `form_logic.body_height` hoch, die Leiste erscheint nur, wenn
    der Inhalt nicht hineinpasst. Das Mausrad scrollt das Formular, außer über
    Widgets, die selbst scrollen (Text, Listbox); über einer Combobox scrollt
    das Formular, und die Combobox ändert ihren Wert nicht.
    """

    def __init__(self, parent, *, scroll=False, scale=1.0):
        self._scale = scale
        self._row = 0
        self._sections = 0
        self._parents: dict[str, str | None] = {}
        self._vars: dict[str, tk.Variable] = {}
        self._members: dict[str, list] = {}
        self._stack: list[str] = []
        self._hints: list[tuple[tk.Label, int]] = []
        self._wrap = 0
        self._scrollable = False
        self._canvas = None
        if scroll:
            self.frame = tk.Frame(parent, bg=BG)
            self._canvas = tk.Canvas(self.frame, bg=BG, highlightthickness=0, bd=0)
            self._bar = ttk.Scrollbar(self.frame, orient="vertical",
                                      command=self._canvas.yview,
                                      style="Vertical.TScrollbar")
            self._canvas.configure(yscrollcommand=self._bar.set)
            self._canvas.grid(row=0, column=0, sticky="nsew")
            self.frame.grid_rowconfigure(0, weight=1)
            self.frame.grid_columnconfigure(0, weight=1)
            self.body = tk.Frame(self._canvas, bg=BG)
            self._canvas.create_window((0, 0), window=self.body, anchor="nw")
            self.body.bind("<Configure>", self._fit_canvas, add="+")
            # Am Toplevel statt per <Enter>/<Leave>: die feuern auch beim
            # Wechsel auf ein Kind-Widget. Jedes Form prüft selbst, ob das
            # Event in seinem Canvas liegt (mehrere Forms je Dialog).
            top = self.frame.winfo_toplevel()
            for seq in _WHEEL_EVENTS:
                top.bind(seq, self._on_wheel, add="+")
        else:
            self.frame = tk.Frame(parent, bg=BG)
            self.body = self.frame
        self.body.grid_columnconfigure(1, weight=1)
        self.body.bind("<Configure>", self._rewrap, add="+")

    # ---- Aufbau --------------------------------------------------------

    def section(self, title, hint=None):
        """Überschrift links, fett, mit feiner Linie bis zum rechten Rand."""
        top = 4 if self._sections == 0 else _SECTION_GAP
        self._sections += 1
        head = tk.Frame(self.body, bg=BG)
        tk.Label(head, text=title, font=FONT_BOLD, bg=BG, fg=TEXT).pack(side=tk.LEFT)
        tk.Frame(head, bg=SEPARATOR, height=1).pack(
            side=tk.LEFT, fill=tk.X, expand=True, padx=(8, 0), pady=(2, 0))
        head.grid(row=self._next_row(), column=0, columnspan=2, sticky="ew",
                  padx=_EDGE, pady=(top, 4))
        if hint:
            self.hint(hint)
        return head

    def row(self, label, widget):
        """Beschriftung in Spalte 0, `widget` (Parent `form.body`) in Spalte 1."""
        r = self._next_row()
        lbl = tk.Label(self.body, text=label, font=FONT, bg=BG, fg=TEXT)
        lbl.grid(row=r, column=0, sticky="w", padx=(self._indent(), 8), pady=4)
        widget.grid(row=r, column=1, sticky="w", padx=(0, _EDGE), pady=4)
        self._register(lbl, widget)
        return lbl

    def check(self, text, var):
        """Checkbox über beide Spalten."""
        cb = tk.Checkbutton(
            self.body, text=text, variable=var, font=FONT,
            bg=BG, fg=TEXT, selectcolor=CELL_BG,
            activebackground=BG, activeforeground=TEXT,
            disabledforeground=TEXT_DISABLED, cursor="hand2",
        )
        cb.grid(row=self._next_row(), column=0, columnspan=2, sticky="w",
                padx=(self._indent(), _EDGE), pady=2)
        self._register(cb)
        return cb

    def hint(self, text):
        """Kleiner, gedämpfter Hinweis über beide Spalten; bricht mit der
        Formularbreite um."""
        indent = self._indent()
        lbl = tk.Label(self.body, text=text, font=FONT_SMALL, bg=BG,
                       fg=TEXT_MUTED, justify="left", anchor="w",
                       wraplength=self._wrap_for(indent))
        lbl.grid(row=self._next_row(), column=0, columnspan=2, sticky="w",
                 padx=(indent, _EDGE), pady=(0, 4))
        self._hints.append((lbl, indent))
        self._register(lbl)
        return lbl

    def buttons(self, *specs: tuple[str, Callable[[], None]]):
        """Linksbündige Knopfreihe über beide Spalten."""
        bar = tk.Frame(self.body, bg=BG)
        made = []
        for text, command in specs:
            btn = secondary_button(bar, text, command)
            btn.pack(side=tk.LEFT, padx=(0, 6))
            made.append(btn)
        bar.grid(row=self._next_row(), column=0, columnspan=2, sticky="w",
                 padx=(self._indent(), _EDGE), pady=(6, 4))
        self._register(*made)
        return made

    def block(self, widget, *, pady=4):
        """Ein eigenes Widget (Parent `form.body`) über beide Spalten —
        Tabellen, Listen, Textfelder."""
        widget.grid(row=self._next_row(), column=0, columnspan=2, sticky="ew",
                    padx=(self._indent(), _EDGE), pady=pady)
        self._register(widget)
        return widget

    @contextmanager
    def depends_on(self, var):
        """Alles, was im `with`-Block entsteht, wird eingerückt und ist nur
        aktiv, solange `var` wahr ist (und alle Schalter darüber). Die
        Variable hält `Form` fest — sie braucht eine lebende Referenz, sonst
        löscht der GC die Tcl-Variable (s. src/CLAUDE.md, Dialoge)."""
        group = f"g{len(self._parents)}"
        self._parents[group] = self._stack[-1] if self._stack else None
        self._vars[group] = var
        self._members[group] = []
        self._stack.append(group)
        try:
            yield
        finally:
            self._stack.pop()
        var.trace_add("write", lambda *_: self.refresh_enabled())
        self.refresh_enabled()

    def refresh_enabled(self):
        """Wendet den aktuellen Zustand aller Schalter auf ihre Gruppen an."""
        values = {}
        for group, var in self._vars.items():
            try:
                values[group] = bool(var.get())
            except tk.TclError:
                # Leeres/ungültiges Feld hinter einer Int-/Double-Variable:
                # gilt als aus, statt den Aufbau abzubrechen.
                values[group] = False
        states = enabled_states(self._parents, values)
        for group, members in self._members.items():
            for widget in members:
                set_enabled(widget, states[group])

    # ---- intern --------------------------------------------------------

    def _next_row(self):
        r = self._row
        self._row += 1
        return r

    def _indent(self):
        return _EDGE + round(INDENT * self._scale) * len(self._stack)

    def _register(self, *widgets):
        if self._canvas is not None:
            for widget in widgets:
                self._guard_value_wheel(widget)
        if self._stack:
            self._members[self._stack[-1]].extend(widgets)

    def _guard_value_wheel(self, widget):
        """Widgets, die beim Rad ihren Wert ändern (Combobox), bekommen eine
        eigene Bindung, die das Formular scrollt und mit "break" das
        Klassen-Binding überspringt — die Toplevel-Bindung käme zu spät, die
        Klasse hätte den Wert dann schon verstellt."""
        if wheel_route(widget.winfo_class()) == "form_block":
            for seq in _WHEEL_EVENTS:
                widget.bind(seq, self._on_blocked_wheel)
        for child in widget.winfo_children():
            self._guard_value_wheel(child)

    def _wrap_for(self, indent):
        """Umbruchbreite eines Hinweises: Formularbreite abzüglich seiner
        Einrückung. Vor der ersten Messung ein fester, mitskalierter Wert."""
        floor = round(_MIN_WRAP * self._scale)
        if not self._wrap:
            return max(floor, round(420 * self._scale))
        return max(floor, self._wrap - indent - _EDGE)

    def _rewrap(self, _event=None):
        width = self.body.winfo_width()
        if width <= 1 or width == self._wrap:
            return
        self._wrap = width
        for lbl, indent in self._hints:
            lbl.config(wraplength=self._wrap_for(indent))

    def _fit_canvas(self, _event=None):
        canvas = self._canvas
        if canvas is None:
            return
        width = self.body.winfo_reqwidth()
        natural = self.body.winfo_reqheight()
        height = body_height(natural, self._scale, canvas.winfo_screenheight())
        canvas.configure(width=width, height=height,
                         scrollregion=(0, 0, width, natural))
        needed = natural > height
        if needed == self._scrollable:
            return
        self._scrollable = needed
        if needed:
            self._bar.grid(row=0, column=1, sticky="ns")
        else:
            self._bar.grid_remove()
            canvas.yview_moveto(0)

    def _scroll(self, event):
        if self._canvas is None or not self._scrollable:
            return
        num = event.num if event.num in (4, 5) else None
        units = wheel_units(platform.system(), int(getattr(event, "delta", 0) or 0), num)
        if units:
            self._canvas.yview_scroll(units, "units")

    def _on_wheel(self, event):
        canvas = self._canvas
        widget = event.widget
        if canvas is None or isinstance(widget, str):
            # Ein während des Events zerstörtes Widget kommt als Pfad-String
            # (s. widgets._click_keeps_focus) — nichts zu scrollen.
            return None
        try:
            if not canvas.winfo_exists():
                return None
            inside = is_descendant(str(widget), str(canvas))
            cls = widget.winfo_class()
        except tk.TclError:
            log.debug("Mausrad: Widget nicht mehr abfragbar", exc_info=True)
            return None
        if inside and wheel_route(cls) == "form":
            self._scroll(event)
        return None

    def _on_blocked_wheel(self, event):
        self._scroll(event)
        return "break"


def empty_state(parent, text, *, bg=BG):
    """Gedämpfter Leertext für eine leere Liste — statt einer leeren Fläche
    ("Noch kein SMTP-Konto angelegt.")."""
    return tk.Label(parent, text=text, font=FONT, bg=bg, fg=TEXT_MUTED,
                    justify="center")
```

- [ ] **Step 3: Re-Exporte**

In `src/theme/__init__.py` den `form`-Import erweitern:

```python
from src.theme.form import (  # noqa: F401
    Form,
    empty_state,
    set_enabled,
)
```

und in `__all__` den `# form`-Block zu `"Form", "empty_state", "set_enabled",` erweitern.

- [ ] **Step 4: Full checks**

Run: `python -m pytest -q` ; `ruff check .` ; `npx --yes pyright@1.1.411`
Expected: all green. `python -c "from src.theme import Form, empty_state"` läuft.

- [ ] **Step 5: Commit**

```
feat(theme): Form — Raster, Abschnitte, Abhängigkeiten, Scroll-Container (#132)

Ein Formular ist ein Raster mit Beschriftungs- und Feldspalte, gegliedert in
linksbündige Abschnitte mit Trennlinie. depends_on rückt abhängige Optionen
ein und graut sie aus. scroll=True begrenzt die Höhe (body_height) und
scrollt per Mausrad; Comboboxen verstellen sich dabei nicht. Dazu
empty_state für leere Listen.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
```

```
git add src/theme/form.py src/theme/__init__.py
git commit -F "C:/Users/SvenB/.claude/jobs/58e9cd06/tmp/commit-msg.txt"
```

---

### Task 5: `themed_ask_save_changes`

**Files:**
- Modify: `src/theme/messagebox.py`
- Modify: `src/theme/__init__.py`

**Interfaces:**
- Produces: `themed_ask_save_changes(parent, tab_title: str) -> Literal["save", "discard", "cancel"]` (aus `src.theme`); `SaveChoice = Literal["save", "discard", "cancel"]` in `messagebox.py`.

Kein Unit-Test (Tk-Aufbau); `tests/test_dialog_reveal.py` prüft die Paarungsregel automatisch. Sichtprüfung in Task 6.

- [ ] **Step 1: Implementierung**

In `src/theme/messagebox.py` den Import `from typing import Literal` ergänzen und nach `themed_ask_delete_choice` einfügen:

```python
SaveChoice = Literal["save", "discard", "cancel"]


def themed_ask_save_changes(parent, tab_title: str) -> SaveChoice:
    """Rückfrage beim Verlassen eines Tabs mit ungespeicherten Änderungen
    (Einstellungs-Dialog, #132): „Speichern" · „Verwerfen" · „Zurück".

    Rückgabe `"save"`, `"discard"` oder `"cancel"`. Escape, das X und
    „Zurück" sind `"cancel"` — wer nur weg will, verliert dabei nichts.
    Enter ist „Speichern", der hervorgehobene Knopf."""
    dialog = create_dialog(parent, "Ungespeicherte Änderungen",
                           modal=False, escape_closes=False)

    result: dict[str, SaveChoice] = {"value": "cancel"}

    tk.Label(
        dialog,
        text=(f"Im Tab „{tab_title}“ gibt es ungespeicherte Änderungen.\n"
              "Sollen sie gespeichert werden?"),
        font=FONT, bg=BG, fg=TEXT, wraplength=380, justify="left",
    ).pack(padx=24, pady=(20, 14))

    def choose(value: SaveChoice):
        result["value"] = value
        dialog.destroy()

    btn_frame = tk.Frame(dialog, bg=BG)
    btn_frame.pack(pady=(0, 18))
    primary_button(btn_frame, "Speichern", lambda: choose("save")).pack(
        side=tk.LEFT, padx=6)
    secondary_button(btn_frame, "Verwerfen", lambda: choose("discard")).pack(
        side=tk.LEFT, padx=6)
    secondary_button(btn_frame, "Zurück", lambda: choose("cancel")).pack(
        side=tk.LEFT, padx=6)

    dialog.bind("<Return>", lambda e: choose("save"))
    dialog.bind("<Escape>", lambda e: choose("cancel"))
    dialog.protocol("WM_DELETE_WINDOW", lambda: choose("cancel"))

    center_dialog_on_parent(dialog, parent)
    dialog.grab_set()
    dialog.wait_window()
    return result["value"]
```

- [ ] **Step 2: Re-Export**

In `src/theme/__init__.py` im `messagebox`-Import `themed_ask_save_changes` ergänzen (nach `themed_ask_delete_choice`) und in `__all__` unter `# messagebox` `"themed_ask_save_changes"` eintragen.

- [ ] **Step 3: Full checks**

Run: `python -m pytest -q` ; `ruff check .` ; `npx --yes pyright@1.1.411`
Expected: all green (inkl. `tests/test_dialog_reveal.py`).

- [ ] **Step 4: Commit**

```
feat(theme): themed_ask_save_changes — Speichern · Verwerfen · Zurück (#132)

Die Rückfrage für ungespeicherte Änderungen, die der Einstellungs-Dialog
in PR 2 beim Tab-Wechsel und beim Schließen stellt.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
```

```
git add src/theme/messagebox.py src/theme/__init__.py
git commit -F "C:/Users/SvenB/.claude/jobs/58e9cd06/tmp/commit-msg.txt"
```

---

### Task 6: Smoke-Skript mit Screenshots (nicht eingecheckt)

**Files:**
- Create (außerhalb des Repos): `C:\Users\SvenB\AppData\Local\Temp\zeit132\form_demo.py`
- Ausgabe: `C:\Users\SvenB\AppData\Local\Temp\zeit132\form_100.png`, `form_150.png`, `form_150_unten.png`, `ask_save.png`

**Interfaces:**
- Consumes: alles aus Task 3–5 über `from src.theme import …`.

Zweck: die Tk-Teile, die kein Unit-Test abdeckt, einmal real prüfen und für den PR belegen. Das Skript fasst keine Nutzerdaten an (kein `Settings`, kein `Storage`).

- [ ] **Step 1: Skript schreiben**

```python
"""Smoke-Test der Formular-Bausteine (#132) — nicht eingecheckt.

    python form_demo.py <scale>
"""
import ctypes
import ctypes.wintypes as wt
import os
import sys
import tkinter as tk

REPO = r"D:\Programme (x86)\Zeiterfassung_Repo\Zeiterfassung"
HERE = os.path.dirname(os.path.abspath(__file__))
SCALE = float(sys.argv[1]) if len(sys.argv) > 1 else 1.0
TAG = str(round(SCALE * 100))
sys.path.insert(0, REPO)

from PIL import ImageGrab  # noqa: E402

from src.theme import (  # noqa: E402
    Form, apply_combobox_style, apply_widget_defaults, center_dialog_on_parent,
    create_dialog, dark_combo, dark_entry, dark_text, empty_state, init_fonts,
    set_enabled, themed_ask_save_changes, TIME_VALUES,
)

errors = []


def check(cond, msg):
    print(("OK   " if cond else "FAIL ") + msg, flush=True)
    if not cond:
        errors.append(msg)


def grab(win, name):
    win.update()
    rect = wt.RECT()
    ctypes.windll.user32.GetWindowRect(int(win.wm_frame(), 16), ctypes.byref(rect))
    ImageGrab.grab(bbox=(rect.left, rect.top, rect.right, rect.bottom)).save(
        os.path.join(HERE, f"{name}.png"))


root = tk.Tk()
init_fonts(root, SCALE)
apply_widget_defaults(root)
root.geometry("200x100+50+50")

dlg = create_dialog(root, "Form-Demo", modal=False, escape_closes=False)
apply_combobox_style(dlg)
form = Form(dlg, scroll=True, scale=SCALE)
form.frame.pack(fill="both", expand=True, padx=8, pady=8)

workweek = tk.BooleanVar(value=False)
form.section("Arbeitswoche")
form.check("Nur Werktage (Mo–Fr)", workweek)
form.hint("Wochenenden im Kalender und im Bericht ausblenden. Ein längerer "
          "Satz, damit man den Umbruch mit der Formularbreite sieht.")
state_var = tk.StringVar(value="Nordrhein-Westfalen")
form.row("Bundesland", dark_combo(form.body, state_var,
                                   ["Bayern", "Nordrhein-Westfalen"], width=24))

form.section("Standardzeiten")
time_vars = []
for day in ("Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"):
    v = tk.StringVar(value="08:00")
    time_vars.append(v)
    form.row(day, dark_combo(form.body, v, TIME_VALUES, width=6))
combo_var = time_vars[0]

wsl = tk.BooleanVar(value=False)
form.section("Werkstudenten-Limit", hint="Warnt, wenn eine Woche das Limit überschreitet.")
form.check("Wochenlimit prüfen", wsl)
hours = tk.StringVar(value="20")
with form.depends_on(wsl):
    hours_entry = dark_entry(form.body, hours, width=6)
    form.row("Max. Stunden", hours_entry)
    notify = tk.BooleanVar(value=False)
    notify_cb = form.check("Zusätzlich benachrichtigen", notify)
    with form.depends_on(notify):
        minutes = tk.StringVar(value="30")
        minutes_entry = dark_entry(form.body, minutes, width=4)
        form.row("Minuten vorher", minutes_entry)
    clicked = []
    (manage_btn,) = form.buttons(("Verwalten…", lambda: clicked.append(1)))

form.section("Vorlage")
text = dark_text(form.body, width=40, height=4)
text.insert("1.0", "\n".join(f"Zeile {i}" for i in range(20)))
form.block(text)
listbox = tk.Listbox(form.body, height=3)
for i in range(10):
    listbox.insert("end", f"Eintrag {i}")
form.block(listbox)
box = tk.Frame(form.body, bg="#16213e", height=60)
form.block(box)
empty_state(box, "Noch kein SMTP-Konto angelegt.", bg="#16213e").place(
    relx=0.5, rely=0.5, anchor="center")

center_dialog_on_parent(dlg, root)
dlg.update()

# --- Ausgrauen --------------------------------------------------------------
check(str(hours_entry.cget("state")) == "disabled", "Entry grau, solange Schalter aus")
check(str(notify_cb.cget("state")) == "disabled", "verschachtelte Checkbox grau")
manage_btn._label.event_generate("<Button-1>")
dlg.update()
check(clicked == [], "gesperrter Label-Button ignoriert Klick")
wsl.set(True)
dlg.update()
check(str(hours_entry.cget("state")) == "normal", "Entry aktiv nach Schalter an")
check(str(minutes_entry.cget("state")) == "disabled", "innere Gruppe bleibt grau (eigener Schalter aus)")
notify.set(True)
dlg.update()
check(str(minutes_entry.cget("state")) == "normal", "innere Gruppe aktiv, wenn beide an")
wsl.set(False)
dlg.update()
check(str(minutes_entry.cget("state")) == "disabled", "innere Gruppe grau, wenn äußerer Schalter aus")
wsl.set(True)
dlg.update()

grab(dlg, f"form_{TAG}")

# --- Mausrad ----------------------------------------------------------------
canvas = form._canvas
check(form._scrollable, "Inhalt höher als Körper → Scrollleiste sichtbar")
check(canvas.winfo_height() <= round(600 * SCALE) + 2, "Körperhöhe begrenzt")

def wheel(widget, delta):
    widget.event_generate("<MouseWheel>", delta=delta, x=2, y=2)
    dlg.update()

label = form.body.grid_slaves(row=0, column=0)[0]
before = canvas.yview()[0]
wheel(label, -120)
check(canvas.yview()[0] > before, "Rad über Label scrollt das Formular")

combo = form.body.grid_slaves(row=5, column=1)[0]
value_before = combo_var.get()
before = canvas.yview()[0]
wheel(combo, -120)
check(combo_var.get() == value_before, "Combobox ändert Wert beim Rad NICHT")
check(canvas.yview()[0] >= before, "Rad über Combobox scrollt das Formular")

canvas.yview_moveto(1.0)
dlg.update()
before = canvas.yview()[0]
text.yview_moveto(0)
wheel(text, -120)
check(canvas.yview()[0] == before, "Rad über Text scrollt NICHT das Formular")
grab(dlg, f"form_{TAG}_unten")

# --- Rückfrage --------------------------------------------------------------
def shoot_and_cancel():
    tops = [w for w in dlg.winfo_children() if isinstance(w, tk.Toplevel)]
    if tops:
        grab(tops[-1], "ask_save")
        tops[-1].event_generate("<Escape>")
    else:
        dlg.after(200, shoot_and_cancel)

dlg.after(600, shoot_and_cancel)
answer = themed_ask_save_changes(dlg, "Arbeitszeit")
check(answer == "cancel", "Escape in der Rückfrage = cancel")

set_enabled(manage_btn, True)
manage_btn._label.event_generate("<Button-1>")
dlg.update()
check(clicked == [1], "entsperrter Label-Button klickt wieder")

root.destroy()
print("FEHLER:", errors if errors else "keine", flush=True)
sys.exit(1 if errors else 0)
```

Falls `event_generate("<MouseWheel>")` unter Windows das Event nicht an das Ziel-Widget liefert (Tk leitet echte Rad-Events an das Widget unter dem Zeiger), statt dessen den Zeiger per `ctypes.windll.user32.SetCursorPos` über das Widget setzen und das Event erneut erzeugen. Die Zeilennummern in `grid_slaves(row=…)` hängen am Aufbau oben (Zeile 5 = erste Standardzeit-Combobox): Section 0, Check 1, Hint 2, Bundesland 3, Section 4, Mo 5.

- [ ] **Step 2: Bei 100 % und 150 % laufen lassen**

Run (aus `C:\Users\SvenB\AppData\Local\Temp\zeit132`): `python form_demo.py 1.0` und `python form_demo.py 1.5`
Expected: jede Zeile `OK`, letzte Zeile `FEHLER: keine`, Exit-Code 0; Screenshots `form_100.png`, `form_100_unten.png`, `form_150.png`, `form_150_unten.png`, `ask_save.png` existieren.

- [ ] **Step 3: Screenshots sichten**

Mit dem Read-Tool jede PNG ansehen und im Report kurz festhalten: Überschriften links mit Linie; Beschriftungen fluchten; eingerückte Zeilen sichtbar eingerückt; ausgegraute Felder deutlich dunkler; Scrollleiste dunkel; Leertext mittig; Rückfrage mit drei Knöpfen. Schlägt ein `FAIL` oder ein optischer Befund zu, in `src/theme/form.py` bzw. `messagebox.py` beheben, Task-3–5-Checks wiederholen und mit einem `fix(theme): …`-Commit nachziehen.

Kein Commit für das Skript selbst.

---

### Task 7: Doku

**Files:**
- Modify: `src/theme/__init__.py` (Modul-Docstring, Schichtung)
- Modify: `src/CLAUDE.md` (Abschnitt „Berichte & Plattform/Infra" → Absatz `theme/`)
- Modify: `CLAUDE.md` (Abschnitt „Dialog-Styling: ein gemeinsames Theme")

- [ ] **Step 1: Schichtung im Docstring von `src/theme/__init__.py`**

Den Block

```
    palette      nur Konstanten, hängt an nichts
      └ fonts        benannte Tk-Fonts + Skalierung
          └ widgets      Widget-Fabriken, ttk-Styles
```

ersetzen durch

```
    palette      nur Konstanten, hängt an nichts
      └ fonts        benannte Tk-Fonts + Skalierung
          └ widgets      Widget-Fabriken, ttk-Styles
              └ form         Formular-Bausteine (Form, set_enabled, empty_state)
    form_logic   Tk-freie Entscheidungen der Formular-Bausteine, hängt an nichts
```

- [ ] **Step 2: `src/CLAUDE.md`**

Im Absatz, der mit `` - `theme/` — Dark-Theme als Paket (R3`` beginnt, den Satz

```
`messagebox` (themed Drop-ins, nutzt chrome/widgets/geometry). Die Schichtung ist
  zyklenfrei und in genau dieser Reihenfolge importierbar.
```

ersetzen durch

```
`messagebox` (themed Drop-ins, nutzt chrome/widgets/geometry) und — seit #132 —
  `form` (Formular-Bausteine über `widgets`: `Form`, `set_enabled`, `empty_state`)
  mit seiner Tk-freien Logik in `form_logic` (hängt an nichts, getestet in
  `tests/test_form_logic.py`). Die Schichtung ist zyklenfrei und in genau dieser
  Reihenfolge importierbar; das Theme importiert nie aus `src/dialogs/`.
```

- [ ] **Step 3: Root-`CLAUDE.md`**

Im Abschnitt „Dialog-Styling: ein gemeinsames Theme" nach dem Absatz, der mit „Neue Dialoge entstehen über `theme.create_dialog(parent, title, …)`" beginnt (endet mit „`center_dialog_on_parent` nach dem Widget-Aufbau bleibt Aufgabe des Dialogs."), einen Absatz einfügen:

```markdown
**Formulare bauen auf `theme.Form`** (`src/theme/form.py`, #132): ein Raster
mit Beschriftungs- und Feldspalte, linksbündige Abschnitte mit Trennlinie,
abhängige Optionen über `form.depends_on(var)` (eingerückt, ausgegraut
solange der Schalter aus ist) und auf Wunsch ein scrollbarer Körper
(`scroll=True`), der den Dialog nie über den Bildschirm wachsen lässt.
Ausgegraut wird über `set_enabled`, leere Listen zeigen `empty_state` — nicht
über eigene Farben je Dialog.
```

- [ ] **Step 4: Full checks**

Run: `python -m pytest -q` (inkl. `tests/test_claude_md_claims.py`) ; `ruff check .`
Expected: all green.

- [ ] **Step 5: Commit**

```
docs: Formular-Bausteine im Theme dokumentieren (#132)

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
```

```
git add src/theme/__init__.py src/CLAUDE.md CLAUDE.md
git commit -F "C:/Users/SvenB/.claude/jobs/58e9cd06/tmp/commit-msg.txt"
```
