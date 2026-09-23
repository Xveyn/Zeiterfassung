# Einstellungs-Dialog #132 — PR 2: Speichern je Tab — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Der Einstellungs-Dialog speichert je Tab statt alles auf einmal: „Speichern" schreibt nur den aktiven Tab und lässt den Dialog offen, wer einen geänderten Tab verlässt oder den Dialog schließt, wird gefragt (Speichern · Verwerfen · Zurück). Die sieben Tabs bleiben, wie sie sind.

**Architecture:** Die Entscheidungen liegen Tk-frei und getestet an drei Stellen: `SaveCoordinator` in `form_model.py` (wann gefragt, gespeichert, verworfen wird), `FieldSet` in `fields.py` (Formularfelder eines Tabs als ein Dict lesen/zurücksetzen, Änderungen melden — duck-typed, mit Fakes getestet) und `tab_rules.py` (je Tab Prüfung und Umrechnung des Formularstands in Settings-Werte — der Inhalt des heutigen `save_settings`, aufgeteilt). Jede Tab-Klasse bekommt `title`/`fields`/`values()`/`validate()`/`save()`/`load()`; `dialog.py` verdrahtet Coordinator, Knöpfe, Reiter-Klick und Schließen.

**Tech Stack:** Python 3.12, Tkinter/ttk, pytest, ruff, pyright 1.1.411.

**Spec:** `docs/superpowers/specs/2026-09-18-einstellungsdialog-132-design.md` (Abschnitt „PR 2 — Speichern je Tab")

## Global Constraints

- Branch: `feat/einstellungen-132-pr2` (von `master` nach dem Merge von #155). Nicht auf `master` committen.
- Die sieben Tabs und ihr Aufbau bleiben sichtbar unverändert — neu sind nur die Knöpfe unten („Speichern" · „Schließen"), die Rückfrage und die beiden Hinweistexte in Webhooks/SMTP (Task 7). Der Neuschnitt ist PR 3.
- Gespeichert wird **nur der aktive Tab**. Validierungsfehler springen nicht in fremde Tabs.
- Was heute sofort gilt, bleibt sofort: SMTP-/Webhook-Einträge, Kategorien, Urlaub, die Google-Schalter für Sync und Kalender.
- Settings-Schlüssel und -Typen, die geschrieben werden, sind exakt die des heutigen `save_settings` (Task 3 hält das als Test fest).
- Tk-freie Module (`form_model.py`, `fields.py`, `tab_rules.py` unter `src/dialogs/settings_dialog/`) sind vollständig annotiert und stehen in `ANNOTATED_MODULES` in `tests/test_type_annotations.py`.
- Themed Meldungen für bekannte Fehler (`themed_showerror`/`themed_showwarning`/`themed_askyesno`/`themed_ask_save_changes`), s. Root-`CLAUDE.md` „Bekannt-themed / unerwartet-nativ".
- Kein stummes `except` (`tests/test_catch_all_handlers.py`): jeder Catch-all loggt, meldet (`showerror` o. ä.) oder trägt eine Begründung im Handler.
- Pixelangaben im Layout nur über `px()` (`tests/test_pixel_scaling.py`); PR 2 fügt keine neuen hinzu.
- Kommentare/Docstrings deutsch, im Stil der Umgebung (erklären das Warum).
- Commits: Nachricht per Datei (`git commit -F <datei>`), Temp-Datei `/tmp/claude-1000/-home-sven-projects-Zeiterfassung/25a16373-79f3-4ef9-a20f-7dd7e0d2d8a5/scratchpad/commit-msg.txt`. Jede Nachricht endet mit Leerzeile + `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Nach jeder Aufgabe grün, aus dem Repo-Root `/home/sven/projects/Zeiterfassung`: `.venv/bin/python -m pytest -q`, `ruff check .`, `npx --yes pyright@1.1.411 --pythonpath .venv/bin/python` (0 errors).
- Keine echten Nutzerdaten: das Smoke-Skript (Task 8) läuft mit `ZEITERFASSUNG_DATA_DIR` auf einem Scratch-Verzeichnis.

## Abweichungen von der Spec (bewusst, in der PR-Beschreibung offenlegen)

1. **`values()` liefert den rohen Formularstand, nicht die Settings-Form.** `values()` läuft bei jedem Tastendruck (Dirty-Anzeige des Speichern-Knopfs) und darf nicht werfen — „abc" im Stundenfeld oder ein halb getipptes Datum wären in Settings-Form nicht darstellbar. Verglichen wird ohnehin nur `values()` mit `values()` (die Baseline stammt aus demselben Aufruf), die Settings-Form entsteht erst in `save()` über `tab_rules`. Die Schlüssel sind trotzdem die Settings-Schlüssel, wo es sie 1:1 gibt.
2. **`reset()` heißt `load(values)`** und bekommt den Stand vom Coordinator, der die Baseline ohnehin hält — der Tab muss sich keinen zweiten merken.
3. **`rebaseline(tab, fields=None)`** nimmt optional die Felder, die neu gesetzt werden: die Kalenderliste lädt im Hintergrund nach, und wer in der Zeit den Gerätenamen ändert, darf diese Änderung durch das Nachladen nicht verlieren.
4. **`SaveOutcome.saved`** zusätzlich zu `restart`: `save()` kann selbst abbrechen (Autostart scheitert, Skalierungs-Rückfrage verneint) — dann bleibt der Tab geändert und es gibt kein `on_change`.
5. **App-Tab: Skalierungs-Rückfrage vor dem Autostart-Umschalten** (heute umgekehrt). Heute ist der Autostart schon umgeschaltet, wenn der Nutzer die Skalierung danach ablehnt — und dann wird nichts gespeichert. Erst die Frage ohne Nebenwirkung, dann der Schritt mit.

## Review Focus

- **Unsinn im Stundenfeld / Wochenlimit („abc", „20,5")** → Dirty-Anzeige wirft nicht, Speichern schreibt wie heute den Fallback (Stundenlohn 0.0, Wochenlimit alter Wert). Tests: Task 2 (`values()` parst nicht), Task 3 (`test_work_updates_falls_back_on_bad_numbers`).
- **Verwerfen nach Monatswechsel im Werkstudenten-Zeitraum** (31.01. → Februar, der Tag klemmt auf 28) → „Verwerfen" stellt 31.01. wieder her. Die Datumszeile klemmt bei **jedem** Schreibzugriff; `load` muss Jahr/Monat vor dem Tag setzen. Tests: Task 2 (`test_load_follows_registration_order`), Task 5 registriert Jahr → Monat → Tag.
- **Kalenderliste lädt nach, während der Gerätename schon geändert ist** → der Tab bleibt geändert, nur das Kalenderfeld wird neu eingelesen. Test: Task 1 (`test_rebaseline_fields_keeps_other_edits`).
- **Skalierung beim Tab-Verlassen gespeichert („Speichern" in der Rückfrage)** → App startet neu, der Dialog ist weg; kein `notebook.select` auf einen zerstörten Dialog. Tests: Task 1 (`test_switch_with_restart_returns_false`), Task 6 prüft `winfo_exists`.
- **Autostart scheitert / Skalierungs-Rückfrage verneint** → nichts gespeichert, Tab bleibt geändert, kein `on_change`. Test: Task 1 (`test_save_aborted_by_tab_keeps_dirty`).

---

## File Structure

| Datei | Verantwortung |
|---|---|
| `src/dialogs/settings_dialog/form_model.py` | + `SaveChoice`, `SaveOutcome`, `SettingsTab` (Protocol), `SaveCoordinator` |
| `src/dialogs/settings_dialog/fields.py` (neu) | `FieldSet`: Felder eines Tabs lesen/laden, Änderungen melden |
| `src/dialogs/settings_dialog/tab_rules.py` (neu) | je Tab `validate_*` und `*_updates` — der aufgeteilte Inhalt von `save_settings` |
| `src/dialogs/settings_dialog/tab_work.py`, `tab_mail.py` | Tab-Schnittstelle (Task 5) |
| `src/dialogs/settings_dialog/tab_google.py`, `tab_app.py`, `tab_updates.py`, `_record_list_tab.py`, `tab_webhooks.py`, `tab_smtp.py` | Tab-Schnittstelle (Task 6) |
| `src/dialogs/settings_dialog/dialog.py` | Coordinator, Knöpfe, Reiter-Klick, Schließen; `save_settings` entfällt (Task 7) |
| `tests/test_form_model.py`, `tests/test_fields.py` (neu), `tests/test_tab_rules.py` (neu), `tests/test_type_annotations.py` | Tests, Whitelist |
| `src/CLAUDE.md`, `src/dialogs/settings_dialog/__init__.py` | Doku (Task 9) |

---

### Task 1: `SaveCoordinator` in `form_model.py`

**Files:**
- Modify: `src/dialogs/settings_dialog/form_model.py`
- Test: `tests/test_form_model.py`

**Interfaces:**
- Consumes: `is_dirty` (existiert).
- Produces:
  - `SaveChoice = Literal["save", "discard", "cancel"]`
  - `@dataclass(frozen=True) class SaveOutcome: saved: bool; restart: bool = False`
  - `class SettingsTab(Protocol): title: str; values() -> dict[str, Any]; validate() -> tuple[str, str] | None; save() -> SaveOutcome; load(values: Mapping[str, Any]) -> None`
  - `SaveCoordinator(tabs: Mapping[str, SettingsTab], current: str, *, ask: Callable[[str], SaveChoice], show_error: Callable[[str, str], None], on_change: Callable[[], None], on_restart: Callable[[], None])` mit `current` (Property), `dirty(key: str | None = None) -> bool`, `rebaseline(key: str, fields: Iterable[str] | None = None) -> None`, `save_current() -> bool`, `request_switch(target: str) -> bool`, `request_close() -> bool`.

- [ ] **Step 1: Failing Tests anhängen** — ans Ende von `tests/test_form_model.py`; den Import oben um die neuen Namen erweitern:

```python
from src.dialogs.settings_dialog.form_model import SaveCoordinator, SaveOutcome, is_dirty
```

```python
# ---- SaveCoordinator (PR 2) ------------------------------------------------


class FakeTab:
    """Tab-Attrappe: `state` ist der Formularstand, `save` protokolliert."""

    def __init__(self, title="Tab", values=None, error=None, outcome=None):
        self.title = title
        self.state = dict(values or {})
        self.error = error
        self.outcome = outcome or SaveOutcome(saved=True)
        self.saved = []
        self.loaded = []

    def values(self):
        return dict(self.state)

    def validate(self):
        return self.error

    def save(self):
        self.saved.append(dict(self.state))
        return self.outcome

    def load(self, values):
        self.loaded.append(dict(values))
        self.state = dict(values)


def make(tabs, current="a", answer="cancel"):
    log = {"asked": [], "errors": [], "changes": 0, "restarts": 0}

    def ask(title):
        log["asked"].append(title)
        return answer

    def on_change():
        log["changes"] += 1

    def on_restart():
        log["restarts"] += 1

    coord = SaveCoordinator(
        tabs, current, ask=ask,
        show_error=lambda title, msg: log["errors"].append((title, msg)),
        on_change=on_change, on_restart=on_restart)
    return coord, log


def test_fresh_tabs_are_clean():
    coord, _ = make({"a": FakeTab(values={"x": "1"}), "b": FakeTab()})
    assert not coord.dirty()
    assert not coord.dirty("b")


def test_unknown_current_raises():
    with pytest.raises(KeyError):
        make({"a": FakeTab()}, current="zzz")


def test_edit_makes_current_dirty_and_undo_cleans():
    tab = FakeTab(values={"x": "1"})
    coord, _ = make({"a": tab})
    tab.state["x"] = "2"
    assert coord.dirty()
    tab.state["x"] = "1"
    assert not coord.dirty()


def test_switch_from_clean_tab_does_not_ask():
    coord, log = make({"a": FakeTab(), "b": FakeTab()})
    assert coord.request_switch("b")
    assert coord.current == "b"
    assert log["asked"] == []


def test_switch_to_current_tab_is_a_no_op():
    tab = FakeTab(values={"x": "1"})
    coord, log = make({"a": tab})
    tab.state["x"] = "2"
    assert coord.request_switch("a")
    assert log["asked"] == []


def test_switch_cancel_stays():
    tab = FakeTab(title="Arbeitszeit", values={"x": "1"})
    coord, log = make({"a": tab, "b": FakeTab()}, answer="cancel")
    tab.state["x"] = "2"
    assert not coord.request_switch("b")
    assert coord.current == "a"
    assert log["asked"] == ["Arbeitszeit"]
    assert tab.saved == [] and tab.loaded == []


def test_switch_discard_loads_baseline_and_moves_on():
    tab = FakeTab(values={"x": "1"})
    coord, log = make({"a": tab, "b": FakeTab()}, answer="discard")
    tab.state["x"] = "2"
    assert coord.request_switch("b")
    assert coord.current == "b"
    assert tab.loaded == [{"x": "1"}]
    assert tab.saved == []
    assert log["changes"] == 0


def test_switch_save_saves_rebaselines_and_moves_on():
    tab = FakeTab(values={"x": "1"})
    coord, log = make({"a": tab, "b": FakeTab()}, answer="save")
    tab.state["x"] = "2"
    assert coord.request_switch("b")
    assert tab.saved == [{"x": "2"}]
    assert log["changes"] == 1
    assert not coord.dirty("a")


def test_switch_save_with_validation_error_stays():
    tab = FakeTab(values={"x": "1"}, error=("Ungültig", "Mo: Ende vor Start"))
    coord, log = make({"a": tab, "b": FakeTab()}, answer="save")
    tab.state["x"] = "2"
    assert not coord.request_switch("b")
    assert coord.current == "a"
    assert log["errors"] == [("Ungültig", "Mo: Ende vor Start")]
    assert tab.saved == []
    assert coord.dirty()


def test_save_aborted_by_tab_keeps_dirty():
    # Autostart scheitert / Skalierungs-Rückfrage verneint: der Tab bricht
    # selbst ab (und hat seine Meldung schon gezeigt).
    tab = FakeTab(values={"x": "1"}, outcome=SaveOutcome(saved=False))
    coord, log = make({"a": tab, "b": FakeTab()}, answer="save")
    tab.state["x"] = "2"
    assert not coord.request_switch("b")
    assert not coord.save_current()
    assert coord.dirty()
    assert log["changes"] == 0
    assert log["errors"] == []


def test_switch_with_restart_returns_false():
    # Skalierung gespeichert: die App startet neu, der Dialog geht mit —
    # ein anschließendes Umschalten liefe ins Leere.
    tab = FakeTab(values={"s": 100}, outcome=SaveOutcome(saved=True, restart=True))
    coord, log = make({"a": tab, "b": FakeTab()}, answer="save")
    tab.state["s"] = 150
    assert not coord.request_switch("b")
    assert log["changes"] == 1
    assert log["restarts"] == 1


def test_save_current_on_clean_tab_does_nothing():
    tab = FakeTab(values={"x": "1"})
    coord, log = make({"a": tab})
    assert coord.save_current()
    assert tab.saved == []
    assert log["changes"] == 0


def test_save_current_saves_once_and_does_not_ask():
    tab = FakeTab(values={"x": "1"})
    coord, log = make({"a": tab})
    tab.state["x"] = "2"
    assert coord.save_current()
    assert tab.saved == [{"x": "2"}]
    assert log["changes"] == 1
    assert log["asked"] == []
    assert not coord.dirty()


def test_save_current_validation_error():
    tab = FakeTab(values={"x": "1"}, error=("T", "M"))
    coord, log = make({"a": tab})
    tab.state["x"] = "2"
    assert not coord.save_current()
    assert log["errors"] == [("T", "M")]


def test_save_current_with_restart_reports_success():
    tab = FakeTab(values={"s": 100}, outcome=SaveOutcome(saved=True, restart=True))
    coord, log = make({"a": tab})
    tab.state["s"] = 150
    assert coord.save_current()
    assert log["restarts"] == 1


def test_close_clean_does_not_ask():
    coord, log = make({"a": FakeTab()})
    assert coord.request_close()
    assert log["asked"] == []


def test_close_dirty_follows_answer():
    for answer, expected in (("cancel", False), ("discard", True), ("save", True)):
        tab = FakeTab(values={"x": "1"})
        coord, _ = make({"a": tab}, answer=answer)
        tab.state["x"] = "2"
        assert coord.request_close() is expected, answer


def test_only_current_tab_is_asked_about():
    # Ein anderer Tab mit Änderungen kann gar nicht entstehen (Verlassen
    # fragt) — aber wenn doch, entscheidet nur der aktive.
    a, b = FakeTab(values={"x": "1"}), FakeTab(values={"y": "1"})
    coord, log = make({"a": a, "b": b})
    b.state["y"] = "2"
    assert coord.request_close()
    assert log["asked"] == []


def test_tab_without_values_is_never_dirty():
    coord, log = make({"a": FakeTab(values={}), "b": FakeTab()})
    assert coord.request_switch("b")
    assert log["asked"] == []


def test_rebaseline_whole_tab():
    tab = FakeTab(values={"cal": "primary"})
    coord, _ = make({"a": tab})
    tab.state["cal"] = "Arbeit"          # Liste nachgeladen, Klarname statt ID
    coord.rebaseline("a")
    assert not coord.dirty()


def test_rebaseline_fields_keeps_other_edits():
    tab = FakeTab(values={"cal": "primary", "device_name": ""})
    coord, _ = make({"a": tab})
    tab.state["device_name"] = "Laptop"  # Nutzer tippt …
    tab.state["cal"] = "Arbeit"          # … während die Liste nachlädt
    coord.rebaseline("a", ["cal"])
    assert coord.dirty()
    tab.state["device_name"] = ""
    assert not coord.dirty()


def test_switch_after_move_asks_about_new_current():
    a = FakeTab(title="A", values={"x": "1"})
    b = FakeTab(title="B", values={"y": "1"})
    coord, log = make({"a": a, "b": b}, answer="cancel")
    assert coord.request_switch("b")
    b.state["y"] = "2"
    assert not coord.request_switch("a")
    assert log["asked"] == ["B"]
```

Oben in der Datei `import pytest` ergänzen, falls nicht vorhanden.

- [ ] **Step 2: Rot sehen**

Run: `.venv/bin/python -m pytest tests/test_form_model.py -q`
Expected: FAIL mit `ImportError: cannot import name 'SaveCoordinator'`

- [ ] **Step 3: Implementieren** — Modul-Docstring anpassen (der Satz „PR 2 ergänzt den `SaveCoordinator` …" wird zu einer Beschreibung dessen, was jetzt da ist), Imports erweitern und ans Ende anhängen:

```python
"""Tk-freie Logik des Einstellungs-Dialogs (#132).

Hier entscheidet sich, ob ein Tab ungespeicherte Änderungen hat
(`is_dirty`), und was beim Speichern, Verlassen eines Tabs und Schließen
des Dialogs geschieht (`SaveCoordinator`). Der Dialog selbst (`dialog.py`)
setzt diese Entscheidungen nur in Tk um.
"""

import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any, Literal, Protocol
```

```python
SaveChoice = Literal["save", "discard", "cancel"]


@dataclass(frozen=True)
class SaveOutcome:
    """Ausgang von `SettingsTab.save`.

    `saved=False`: der Tab hat selbst abgebrochen (Autostart ließ sich nicht
    umschalten, Skalierungs-Rückfrage verneint) und seine Meldung schon
    gezeigt — geschrieben ist nichts, der Tab bleibt geändert.
    `restart`: die gespeicherte Änderung braucht einen Neustart (Skalierung)."""

    saved: bool
    restart: bool = False


class SettingsTab(Protocol):
    """Was der Coordinator von einem Tab braucht.

    `values()` ist der **rohe** Formularstand (was in den Feldern steht),
    nicht die Settings-Form: es läuft bei jedem Tastendruck und darf auch
    bei „abc" im Stundenfeld nicht werfen. Umgerechnet wird erst in `save()`."""

    title: str

    def values(self) -> dict[str, Any]: ...

    def validate(self) -> tuple[str, str] | None: ...

    def save(self) -> SaveOutcome: ...

    def load(self, values: Mapping[str, Any]) -> None: ...


class SaveCoordinator:
    """Speichern je Tab (#132): hält je Tab den zuletzt gespeicherten Stand
    (Baseline) und entscheidet, ob ein Tab-Wechsel oder das Schließen
    erlaubt ist.

    Gefragt wird nur nach dem **aktiven** Tab — andere können keine
    Änderungen tragen, weil sie nur über dieses Tor verlassen werden.
    `ask`, `show_error`, `on_change` und `on_restart` sind injiziert; der
    Coordinator kennt kein Tk. `on_restart` beendet den Dialog: danach
    liefern `request_switch`/`request_close` `False`, damit der Aufrufer
    nichts mehr an einem zerstörten Fenster tut."""

    def __init__(self, tabs: Mapping[str, SettingsTab], current: str, *,
                 ask: Callable[[str], SaveChoice],
                 show_error: Callable[[str, str], None],
                 on_change: Callable[[], None],
                 on_restart: Callable[[], None]) -> None:
        if current not in tabs:
            raise KeyError(current)
        self._tabs = dict(tabs)
        self._current = current
        self._ask = ask
        self._show_error = show_error
        self._on_change = on_change
        self._on_restart = on_restart
        self._baselines: dict[str, dict[str, Any]] = {
            key: dict(tab.values()) for key, tab in self._tabs.items()}

    @property
    def current(self) -> str:
        return self._current

    def dirty(self, key: str | None = None) -> bool:
        """Hat der Tab `key` (Default: der aktive) ungespeicherte Änderungen?"""
        key = self._current if key is None else key
        return is_dirty(self._baselines[key], self._tabs[key].values())

    def rebaseline(self, key: str, fields: Iterable[str] | None = None) -> None:
        """Übernimmt den aktuellen Stand als gespeichert — für Werte, die im
        Hintergrund nachgeladen werden (Kalenderliste). Mit `fields` nur diese
        Felder: eine Änderung, die der Nutzer in der Zwischenzeit an einem
        anderen Feld gemacht hat, bleibt eine Änderung."""
        current = self._tabs[key].values()
        if fields is None:
            self._baselines[key] = dict(current)
            return
        for field in fields:
            if field in current:
                self._baselines[key][field] = current[field]

    def save_current(self) -> bool:
        """Knopf „Speichern": ohne Rückfrage. True, wenn danach nichts
        Ungespeichertes mehr übrig ist (auch: es gab nichts zu speichern)."""
        if not self.dirty():
            return True
        return self._save(self._current) != "failed"

    def request_switch(self, target: str) -> bool:
        """Darf auf `target` gewechselt werden? Bei True ist `target` aktiv."""
        if target not in self._tabs:
            raise KeyError(target)
        if target == self._current:
            return True
        if not self._leave():
            return False
        self._current = target
        return True

    def request_close(self) -> bool:
        """Darf der Dialog geschlossen werden?"""
        return self._leave()

    def _leave(self) -> bool:
        key = self._current
        if not self.dirty(key):
            return True
        choice = self._ask(self._tabs[key].title)
        if choice == "discard":
            self._tabs[key].load(self._baselines[key])
            return True
        if choice == "save":
            return self._save(key) == "saved"
        return False

    def _save(self, key: str) -> Literal["saved", "failed", "restart"]:
        tab = self._tabs[key]
        error = tab.validate()
        if error is not None:
            self._show_error(*error)
            return "failed"
        outcome = tab.save()
        if not outcome.saved:
            return "failed"
        self._baselines[key] = dict(tab.values())
        self._on_change()
        if outcome.restart:
            self._on_restart()
            return "restart"
        return "saved"
```

- [ ] **Step 4: Grün sehen**

Run: `.venv/bin/python -m pytest tests/test_form_model.py tests/test_type_annotations.py -q`
Expected: PASS (`form_model.py` steht schon in der Whitelist).

- [ ] **Step 5: ruff + pyright, dann Commit**

```bash
ruff check . && npx --yes pyright@1.1.411 --pythonpath .venv/bin/python
git add src/dialogs/settings_dialog/form_model.py tests/test_form_model.py
git commit -F <commit-msg.txt>   # "feat(einstellungen): SaveCoordinator — Speichern je Tab mit Rückfrage (#132)"
```

---

### Task 2: `FieldSet` in `fields.py`

**Files:**
- Create: `src/dialogs/settings_dialog/fields.py`
- Test: `tests/test_fields.py`
- Modify: `tests/test_type_annotations.py` (`"src/dialogs/settings_dialog/fields.py"` in `ANNOTATED_MODULES`)

**Interfaces:**
- Produces: `FieldSet()` mit `add(key: str, var: Any, *, read: Callable[[Any], Any] | None = None) -> Any` (gibt `var` zurück), `add_text(key: str, widget: Any) -> Any`, `on_edit(callback: Callable[[], None]) -> None`, `values() -> dict[str, Any]`, `load(values: Mapping[str, Any]) -> None`, `keys() -> list[str]`.
- Duck-Typing: `var` braucht `get()`, `set(v)`, `trace_add("write", cb)`; `widget` braucht `get("1.0", "end-1c")`, `delete`, `insert`, `bind(seq, fn, add="+")`, `edit_modified(flag=None)`. Das Modul importiert **kein** `tkinter` — daher mit Fakes testbar.

- [ ] **Step 1: Failing Tests** — `tests/test_fields.py`:

```python
"""Tests für FieldSet (settings_dialog/fields.py, #132) — mit Fakes statt Tk."""

import pytest

from src.dialogs.settings_dialog.fields import FieldSet


class FakeVar:
    def __init__(self, value):
        self.value = value
        self.traces = []
        self.set_log = []

    def get(self):
        return self.value

    def set(self, value):
        self.value = value
        self.set_log.append(value)
        for cb in self.traces:
            cb("PY_VAR0", "", "write")

    def trace_add(self, mode, cb):
        assert mode == "write"
        self.traces.append(cb)


class FakeEvent:
    def __init__(self, widget):
        self.widget = widget


class FakeText:
    """Ahmt tk.Text nach: Modified-Flag + <<Modified>> bei jedem Flag-Wechsel."""

    def __init__(self, content=""):
        self.content = content
        self.modified = bool(content)   # insert beim Aufbau setzt das Flag
        self.handlers = []

    def get(self, start, end):
        assert (start, end) == ("1.0", "end-1c")
        return self.content

    def delete(self, start, end):
        self._change("")

    def insert(self, index, text):
        self._change(self.content + text)

    def bind(self, seq, fn, add=None):
        assert seq == "<<Modified>>" and add == "+"
        self.handlers.append(fn)

    def edit_modified(self, flag=None):
        if flag is None:
            return self.modified
        if flag != self.modified:
            self.modified = flag
            self._fire()

    def type(self, text):
        self._change(self.content + text)

    def _change(self, content):
        self.content = content
        if not self.modified:
            self.modified = True
            self._fire()

    def _fire(self):
        for fn in list(self.handlers):
            fn(FakeEvent(self))


def test_values_reads_vars_and_texts():
    fs = FieldSet()
    fs.add("name", FakeVar("Anna"))
    fs.add("on", FakeVar(True))
    fs.add_text("body", FakeText("Hallo\nWelt"))
    assert fs.values() == {"name": "Anna", "on": True, "body": "Hallo\nWelt"}


def test_values_never_parses():
    # "abc" im Stundenfeld bleibt Text — values() läuft bei jedem Tastendruck
    # und darf nicht werfen.
    fs = FieldSet()
    fs.add("hours", FakeVar("abc"))
    assert fs.values() == {"hours": "abc"}


def test_read_transforms_the_value():
    fs = FieldSet()
    fs.add("scale", FakeVar(101.3), read=lambda v: round(v / 5) * 5)
    assert fs.values() == {"scale": 100}


def test_add_returns_the_var():
    var = FakeVar("x")
    assert FieldSet().add("k", var) is var


def test_duplicate_key_raises():
    fs = FieldSet()
    fs.add("k", FakeVar(1))
    with pytest.raises(ValueError):
        fs.add("k", FakeVar(2))
    with pytest.raises(ValueError):
        fs.add_text("k", FakeText())


def test_var_write_notifies():
    fs = FieldSet()
    var = fs.add("k", FakeVar("a"))
    calls = []
    fs.on_edit(lambda: calls.append(1))
    var.set("b")
    assert calls == [1]


def test_text_typing_notifies_every_time():
    fs = FieldSet()
    text = fs.add_text("body", FakeText("Hallo"))
    calls = []
    fs.on_edit(lambda: calls.append(1))
    text.type("!")
    text.type("?")
    # Ohne Zurücksetzen des Modified-Flags käme nur das erste Tippen an.
    assert calls == [1, 1]


def test_add_text_resets_flag_from_initial_insert():
    text = FakeText("vorbelegt")
    FieldSet().add_text("body", text)
    assert text.modified is False


def test_load_sets_vars_and_texts():
    fs = FieldSet()
    var = fs.add("name", FakeVar("Ben"))
    text = fs.add_text("body", FakeText("neu"))
    fs.load({"name": "Anna", "body": "alt"})
    assert var.value == "Anna"
    assert text.content == "alt"


def test_load_ignores_unknown_and_missing_keys():
    fs = FieldSet()
    var = fs.add("name", FakeVar("Ben"))
    fs.load({"other": 1})
    assert var.value == "Ben"


def test_load_follows_registration_order():
    # Die Datumszeile klemmt den Tag bei JEDEM Schreibzugriff auf die
    # Monatslänge — Jahr und Monat müssen vor dem Tag stehen, egal in
    # welcher Reihenfolge das Dict kommt.
    order = []
    fs = FieldSet()
    for key in ("year", "month", "day"):
        var = fs.add(key, FakeVar("0"))
        var.traces.append(lambda *_a, k=key: order.append(k))
    fs.load({"day": "31", "month": "1", "year": "2026"})
    assert order == ["year", "month", "day"]


def test_keys_in_registration_order():
    fs = FieldSet()
    fs.add("b", FakeVar(1))
    fs.add_text("a", FakeText())
    assert fs.keys() == ["b", "a"]


def test_empty_fieldset():
    fs = FieldSet()
    assert fs.values() == {}
    fs.load({"x": 1})
```

- [ ] **Step 2: Rot sehen**

Run: `.venv/bin/python -m pytest tests/test_fields.py -q`
Expected: FAIL mit `ModuleNotFoundError: No module named 'src.dialogs.settings_dialog.fields'`

- [ ] **Step 3: Implementieren** — `src/dialogs/settings_dialog/fields.py`:

```python
"""Die Formularfelder eines Einstellungs-Tabs als ein Dict (#132).

Ein Tab registriert seine Tk-Variablen und Textfelder unter einem Schlüssel;
daraus entstehen `values()` (der rohe Formularstand, den der
`SaveCoordinator` mit der Baseline vergleicht) und `load()` (Verwerfen).
Jede Änderung meldet `on_edit` — daran hängt der Speichern-Knopf.

Bewusst ohne `import tkinter`: gebraucht wird nur die Schnittstelle von
`tk.Variable` (`get`/`set`/`trace_add`) und `tk.Text`. So lässt sich das
Modul mit Attrappen testen, obwohl es Tk-Objekte verwaltet.
"""

from collections.abc import Callable, Mapping
from typing import Any


class FieldSet:
    """Schlüssel → Tk-Variable bzw. Textfeld, in Registrierungsreihenfolge."""

    def __init__(self) -> None:
        # Ein Dict statt zweier: die Reihenfolge über beide Arten hinweg ist
        # die von `load` (s. dort).
        self._fields: dict[str, tuple[str, Any, Callable[[Any], Any] | None]] = {}
        self._listeners: list[Callable[[], None]] = []

    def add(self, key: str, var: Any, *,
            read: Callable[[Any], Any] | None = None) -> Any:
        """Registriert eine Tk-Variable. `read` bildet den gelesenen Wert auf
        seine Vergleichsform ab (Schieberegler: auf 5er-Schritte gerastert,
        sonst wäre ein hin- und zurückgezogener Regler „geändert")."""
        self._check_new(key)
        self._fields[key] = ("var", var, read)
        var.trace_add("write", self._on_var_write)
        return var

    def add_text(self, key: str, widget: Any) -> Any:
        """Registriert ein `tk.Text`. Aufrufen, NACHDEM der Anfangstext
        eingefügt ist — das Einfügen setzt das Modified-Flag, das hier
        zurückgesetzt wird."""
        self._check_new(key)
        self._fields[key] = ("text", widget, None)
        widget.edit_modified(False)
        widget.bind("<<Modified>>", self._on_text_modified, add="+")
        return widget

    def on_edit(self, callback: Callable[[], None]) -> None:
        self._listeners.append(callback)

    def keys(self) -> list[str]:
        return list(self._fields)

    def values(self) -> dict[str, Any]:
        """Roher Formularstand — ohne Parsen, darf nicht werfen."""
        out: dict[str, Any] = {}
        for key, (kind, obj, read) in self._fields.items():
            if kind == "text":
                out[key] = obj.get("1.0", "end-1c")
                continue
            value = obj.get()
            out[key] = read(value) if read is not None else value
        return out

    def load(self, values: Mapping[str, Any]) -> None:
        """Setzt die Felder auf `values` — in **Registrierungsreihenfolge**,
        nicht in der des Dicts: die Datumszeile klemmt den Tag bei jedem
        Schreibzugriff auf die Monatslänge, ein Tag vor seinem Monat würde
        also verfälscht. Unbekannte Schlüssel werden übergangen."""
        for key, (kind, obj, _read) in self._fields.items():
            if key not in values:
                continue
            if kind == "text":
                obj.delete("1.0", "end")
                obj.insert("1.0", values[key])
            else:
                obj.set(values[key])

    def _check_new(self, key: str) -> None:
        if key in self._fields:
            raise ValueError(f"Feld {key!r} ist schon registriert")

    def _on_var_write(self, *_args: Any) -> None:
        self._notify()

    def _on_text_modified(self, event: Any) -> None:
        # tk.Text meldet <<Modified>> nur, wenn das Flag WECHSELT. Ohne
        # Zurücksetzen käme also nur der erste Tastendruck an. Das
        # Zurücksetzen löst selbst wieder <<Modified>> aus — das fängt die
        # Abfrage des Flags ab.
        widget = event.widget
        if not widget.edit_modified():
            return
        widget.edit_modified(False)
        self._notify()

    def _notify(self) -> None:
        for callback in list(self._listeners):
            callback()
```

`"src/dialogs/settings_dialog/fields.py",` in `ANNOTATED_MODULES` eintragen (neben `form_model.py`).

- [ ] **Step 4: Grün sehen**

Run: `.venv/bin/python -m pytest tests/test_fields.py tests/test_type_annotations.py -q`
Expected: PASS

- [ ] **Step 5: ruff + pyright, Commit** — „feat(einstellungen): FieldSet — Formularfelder eines Tabs als Dict (#132)"

---

### Task 3: `tab_rules.py` — Arbeitszeit

**Files:**
- Create: `src/dialogs/settings_dialog/tab_rules.py`
- Test: `tests/test_tab_rules.py`
- Modify: `tests/test_type_annotations.py` (`"src/dialogs/settings_dialog/tab_rules.py"`)

**Interfaces:**
- Consumes: `validate_entry`, `validate_period`, `DAYS_DE` (`src.time_utils`), `WEEKDAY_KEYS`, `parse_hourly_rate` (`src.settings`).
- Produces (Rohschlüssel des Arbeitszeit-Tabs, genutzt in Task 5):
  `workweek_only`, `default_start_<tag>`/`default_end_<tag>` für alle sieben `WEEKDAY_KEYS`, `default_pause`, `pause_warning_enabled`, `hourly_rate`, `werkstudent_limit_enabled`, `werkstudent_limit_start.year|.month|.day`, `werkstudent_limit_end.year|.month|.day`, `werkstudent_limit_max_hours`.
  - `WSL_KEYS: tuple[str, ...]` = die vier `werkstudent_limit_*`-Settings-Schlüssel
  - `date_iso(day: str, month: str, year: str) -> str | None`
  - `validate_work(raw: Mapping[str, Any]) -> tuple[str, str] | None`
  - `work_updates(raw: Mapping[str, Any], old: Mapping[str, Any]) -> dict[str, Any]` (`old` = die aktuellen Settings-Werte der `WSL_KEYS`, für die Fallbacks)
  - `wsl_snapshot(values: Mapping[str, Any]) -> dict[str, Any]` (Eingabe für `weekly_limit.period_scan_needed`)

- [ ] **Step 1: Failing Tests** — `tests/test_tab_rules.py`:

```python
"""Tests für tab_rules.py (#132, PR 2): Prüfung und Umrechnung je Tab —
der aufgeteilte Inhalt des früheren `save_settings`."""

from src.dialogs.settings_dialog import tab_rules as tr
from src.settings import WEEKDAY_KEYS


def work_raw(**overrides):
    raw = {
        "workweek_only": False,
        "default_pause": "30",
        "pause_warning_enabled": True,
        "hourly_rate": "15.5",
        "werkstudent_limit_enabled": False,
        "werkstudent_limit_start.year": "2026",
        "werkstudent_limit_start.month": "4",
        "werkstudent_limit_start.day": "1",
        "werkstudent_limit_end.year": "2026",
        "werkstudent_limit_end.month": "9",
        "werkstudent_limit_end.day": "30",
        "werkstudent_limit_max_hours": "20",
    }
    for key in WEEKDAY_KEYS:
        raw[f"default_start_{key}"] = "08:00"
        raw[f"default_end_{key}"] = "16:00"
    raw.update(overrides)
    return raw


OLD_WSL = {
    "werkstudent_limit_enabled": False,
    "werkstudent_limit_start": "2025-10-01",
    "werkstudent_limit_end": "2026-03-31",
    "werkstudent_limit_max_hours": 20.0,
}


def test_date_iso():
    assert tr.date_iso("1", "4", "2026") == "2026-04-01"
    assert tr.date_iso("31", "2", "2026") is None
    assert tr.date_iso("", "4", "2026") is None
    assert tr.date_iso("x", "4", "2026") is None


def test_validate_work_ok():
    assert tr.validate_work(work_raw()) is None


def test_validate_work_names_the_weekday():
    raw = work_raw(default_start_wed="17:00", default_end_wed="09:00")
    title, msg = tr.validate_work(raw)
    assert title == "Standard-Arbeitszeit ungültig"
    assert msg.startswith("Mi: ")


def test_validate_work_checks_period_only_when_enabled():
    backwards = {"werkstudent_limit_end.year": "2025"}
    assert tr.validate_work(work_raw(**backwards)) is None
    title, _ = tr.validate_work(work_raw(werkstudent_limit_enabled=True, **backwards))
    assert title == "Werkstudenten-Limit-Zeitraum ungültig"


def test_validate_work_rejects_unparseable_date_when_enabled():
    raw = work_raw(werkstudent_limit_enabled=True,
                   **{"werkstudent_limit_start.day": ""})
    title, _ = tr.validate_work(raw)
    assert title == "Werkstudenten-Limit-Zeitraum ungültig"


def test_work_updates_converts_types():
    upd = tr.work_updates(work_raw(), OLD_WSL)
    assert upd["default_pause"] == 30
    assert upd["hourly_rate"] == 15.5
    assert upd["werkstudent_limit_start"] == "2026-04-01"
    assert upd["werkstudent_limit_end"] == "2026-09-30"
    assert upd["werkstudent_limit_max_hours"] == 20.0
    assert upd["default_start_sat"] == "08:00"
    assert upd["pause_warning_enabled"] is True
    assert upd["workweek_only"] is False


def test_work_updates_falls_back_on_bad_numbers():
    # Wie das frühere save_settings: Stundenlohn tolerant auf 0.0,
    # Wochenlimit auf den bisherigen Wert.
    upd = tr.work_updates(
        work_raw(hourly_rate="abc", werkstudent_limit_max_hours="20,5"), OLD_WSL)
    assert upd["hourly_rate"] == 0.0
    assert upd["werkstudent_limit_max_hours"] == 20.0


def test_work_updates_keeps_old_date_when_unparseable():
    upd = tr.work_updates(
        work_raw(**{"werkstudent_limit_end.day": "x"}), OLD_WSL)
    assert upd["werkstudent_limit_end"] == "2026-03-31"


def test_wsl_snapshot_from_settings_and_updates_agree():
    upd = tr.work_updates(work_raw(), OLD_WSL)
    assert tr.wsl_snapshot(upd) == {
        "enabled": False, "start": "2026-04-01", "end": "2026-09-30",
        "max_hours": 20.0}
    assert tr.wsl_snapshot(OLD_WSL)["start"] == "2025-10-01"
```

- [ ] **Step 2: Rot sehen** — `.venv/bin/python -m pytest tests/test_tab_rules.py -q` → `ModuleNotFoundError`.

- [ ] **Step 3: Implementieren** — `src/dialogs/settings_dialog/tab_rules.py`:

```python
"""Prüfung und Umrechnung des Formularstands je Einstellungs-Tab (#132).

Der Inhalt des früheren `dialog.save_settings`, aufgeteilt auf die Tabs,
die ihn tragen. Jeder Tab liefert seinen **rohen** Formularstand
(`FieldSet.values()` — Text aus Entries/Comboboxen, Bools aus Häkchen);
hier wird er geprüft (`validate_*` → `(Titel, Meldung)` oder `None`) und in
Settings-Werte umgerechnet (`*_updates` → Dict für `Settings.apply_updates`).

Tk-frei und getestet. Die Umrechnung ist so tolerant wie vorher: was
`save_settings` still auf einen Fallback setzte, tut es hier auch.
"""

import datetime
from collections.abc import Mapping
from typing import Any

from src.settings import WEEKDAY_KEYS, parse_hourly_rate
from src.time_utils import DAYS_DE, validate_entry, validate_period

WSL_KEYS = (
    "werkstudent_limit_enabled", "werkstudent_limit_start",
    "werkstudent_limit_end", "werkstudent_limit_max_hours",
)


def date_iso(day: str, month: str, year: str) -> str | None:
    """ISO-Datum aus den drei Combobox-Werten, `None` bei Unsinn/31.02."""
    try:
        return datetime.date(int(year), int(month), int(day)).isoformat()
    except (TypeError, ValueError):
        return None


def _wsl_date(raw: Mapping[str, Any], which: str) -> str | None:
    prefix = f"werkstudent_limit_{which}"
    return date_iso(raw[f"{prefix}.day"], raw[f"{prefix}.month"],
                    raw[f"{prefix}.year"])


def validate_work(raw: Mapping[str, Any]) -> tuple[str, str] | None:
    for key, label in zip(WEEKDAY_KEYS, DAYS_DE, strict=True):
        ok, msg = validate_entry(raw[f"default_start_{key}"],
                                 raw[f"default_end_{key}"])
        if not ok:
            return "Standard-Arbeitszeit ungültig", f"{label}: {msg}"
    # Der Zeitraum zählt nur, wenn das Limit an ist — wie bisher.
    if raw["werkstudent_limit_enabled"]:
        start, end = _wsl_date(raw, "start"), _wsl_date(raw, "end")
        if start is None or end is None:
            return ("Werkstudenten-Limit-Zeitraum ungültig",
                    "Bitte ein gültiges Datum wählen.")
        ok, msg = validate_period(start, end)
        if not ok:
            return "Werkstudenten-Limit-Zeitraum ungültig", msg
    return None


def work_updates(raw: Mapping[str, Any],
                 old: Mapping[str, Any]) -> dict[str, Any]:
    """Settings-Werte des Arbeitszeit-Tabs. `old` trägt die bisherigen
    `WSL_KEYS`-Werte: ein nicht lesbares Wochenlimit oder Datum behält den
    gespeicherten Wert, statt zu werfen."""
    try:
        max_hours = float(raw["werkstudent_limit_max_hours"])
    except (TypeError, ValueError):
        max_hours = old["werkstudent_limit_max_hours"]
    updates: dict[str, Any] = {
        "default_pause": int(raw["default_pause"]),
        "pause_warning_enabled": bool(raw["pause_warning_enabled"]),
        "hourly_rate": parse_hourly_rate(raw["hourly_rate"]),
        "werkstudent_limit_enabled": bool(raw["werkstudent_limit_enabled"]),
        "werkstudent_limit_start": (_wsl_date(raw, "start")
                                    or old["werkstudent_limit_start"]),
        "werkstudent_limit_end": (_wsl_date(raw, "end")
                                  or old["werkstudent_limit_end"]),
        "werkstudent_limit_max_hours": max_hours,
        "workweek_only": bool(raw["workweek_only"]),
    }
    # Alle sieben Tage, auch Sa/So bei „Nur Werktage": die Werte bleiben so
    # erhalten und sind sofort wieder da, wenn der Modus zurückgenommen wird.
    for key in WEEKDAY_KEYS:
        updates[f"default_start_{key}"] = raw[f"default_start_{key}"]
        updates[f"default_end_{key}"] = raw[f"default_end_{key}"]
    return updates


def wsl_snapshot(values: Mapping[str, Any]) -> dict[str, Any]:
    """Die Form, die `weekly_limit.period_scan_needed` vergleicht — aus
    Settings-Werten oder aus `work_updates`."""
    return {
        "enabled": values["werkstudent_limit_enabled"],
        "start": values["werkstudent_limit_start"],
        "end": values["werkstudent_limit_end"],
        "max_hours": values["werkstudent_limit_max_hours"],
    }
```

`default_pause` kommt aus einer schreibgeschützten Combobox (`dark_combo`, `state="readonly"`, Werte aus `PAUSE_VALUES`) — `int()` ist dort so sicher wie im alten `save_settings`.

Whitelist-Eintrag ergänzen.

- [ ] **Step 4: Grün sehen** — `.venv/bin/python -m pytest tests/test_tab_rules.py tests/test_type_annotations.py -q` → PASS.

- [ ] **Step 5: ruff + pyright, Commit** — „feat(einstellungen): Prüfung und Umrechnung des Arbeitszeit-Tabs Tk-frei (#132)"

---

### Task 4: `tab_rules.py` — Mail, Google, App, Updates und der Schlüssel-Vertrag

**Files:**
- Modify: `src/dialogs/settings_dialog/tab_rules.py`
- Test: `tests/test_tab_rules.py`

**Interfaces:**
- Consumes: `parse_reminder_minutes`, `clamp_ui_scale`, `resolve_calendar_id` (`src.settings`), `code_for_state_label` (`src.holidays_de`), `shift_for_label` (`src.send_reminder`), `frequency_for_label` (`src.updater`), `sanitize_device_name` (`src.devices`).
- Produces (Rohschlüssel in Klammern; genutzt in Task 5/6):
  - `MAIL_KEYS` = `("recipient", "name", "mail_subject", "mail_greeting", "mail_content", "mail_closing")`; `mail_updates(raw) -> dict[str, Any]`
  - Google-Rohschlüssel `device_name`, `gcal_calendar` (Klarname **oder** ID, s. `cal_var`); `google_updates(raw) -> dict[str, Any]`; `calendar_update(cal_map: Mapping[str, str], selected: str, stored_id: str | None, gcal_enabled: bool) -> str | None`
  - App-Rohschlüssel `state` (Label), `show_weekend`, `autostart`, `always_on_top`, `minimize_to_tray`, `ui_scale` (Prozent, gerastert), `reminders_enabled`, `reminder_minutes_before`, `send_reminder_enabled`, `send_reminder_day`, `send_reminder_time`, `send_reminder_weekend_shift` (Label), `send_reminder_shift_holidays`, `send_reminder_reservations_enabled`, `send_reminder_default_minutes`, `send_period_from_last_reminder`, `send_period_anchor_monthly`; `slider_percent(value: float) -> int`; `validate_app(raw) -> tuple[str, str] | None`; `app_updates(raw) -> dict[str, Any]`
  - Updates-Rohschlüssel `update_check_frequency` (Label), `prerelease_updates_enabled`, optional `auto_update_enabled`; `update_tab_updates(raw) -> dict[str, Any]`

- [ ] **Step 1: Failing Tests anhängen**:

```python
from src.holidays_de import STATES
from src.updater import FREQUENCY_OPTIONS
from src.send_reminder import SHIFT_LABELS


def app_raw(**overrides):
    raw = {
        "state": STATES[1][1], "show_weekend": True, "autostart": False,
        "always_on_top": False, "minimize_to_tray": True, "ui_scale": 125,
        "reminders_enabled": True, "reminder_minutes_before": "15",
        "send_reminder_enabled": True, "send_reminder_day": "28",
        "send_reminder_time": "09:00",
        "send_reminder_weekend_shift": SHIFT_LABELS["backward"],
        "send_reminder_shift_holidays": False,
        "send_reminder_reservations_enabled": True,
        "send_reminder_default_minutes": "30",
        "send_period_from_last_reminder": True,
        "send_period_anchor_monthly": False,
    }
    raw.update(overrides)
    return raw


def test_slider_percent_snaps_to_five():
    assert tr.slider_percent(101.3) == 100
    assert tr.slider_percent(103.0) == 105
    assert tr.slider_percent(200.0) == 200


def test_validate_app():
    assert tr.validate_app(app_raw()) is None
    for bad in ("abc", "-5", "121", "7.5", ""):
        title, _ = tr.validate_app(app_raw(reminder_minutes_before=bad))
        assert title == "Erinnerungszeit ungültig"


def test_app_updates_converts():
    upd = tr.app_updates(app_raw())
    assert upd["state"] == STATES[1][0]
    assert upd["ui_scale"] == 1.25
    assert upd["reminder_minutes_before"] == 15
    assert upd["send_reminder_day"] == 28
    assert upd["send_reminder_weekend_shift"] == "backward"
    assert upd["send_reminder_default_minutes"] == 30
    assert upd["autostart"] is False


def test_app_updates_clamps_scale():
    assert tr.app_updates(app_raw(ui_scale=500))["ui_scale"] == 2.0


def test_mail_updates_passes_text_through():
    raw = {k: f"<{k}>" for k in tr.MAIL_KEYS}
    assert tr.mail_updates(raw) == raw


def test_google_updates_sanitizes_device_name():
    upd = tr.google_updates({"device_name": "  Laptop\x07 ", "gcal_calendar": "x"})
    assert upd == {"device_name": "Laptop"}


def test_calendar_update():
    cal_map = {"Arbeit": "abc@group", "Privat": "primary"}
    assert tr.calendar_update(cal_map, "Arbeit", "primary", True) == "abc@group"
    assert tr.calendar_update(cal_map, "Privat", "primary", True) is None
    # Liste noch nicht geladen: nie vorschnell "primary" festschreiben.
    assert tr.calendar_update({}, "primary", "abc@group", True) is None
    assert tr.calendar_update(cal_map, "Arbeit", "primary", False) is None


def test_update_tab_updates():
    raw = {"update_check_frequency": FREQUENCY_OPTIONS[1][1],
           "prerelease_updates_enabled": True}
    assert tr.update_tab_updates(raw) == {
        "update_check_frequency": FREQUENCY_OPTIONS[1][0],
        "prerelease_updates_enabled": True}
    raw["auto_update_enabled"] = False
    assert tr.update_tab_updates(raw)["auto_update_enabled"] is False


# Die Schlüssel, die das frühere dialog.save_settings geschrieben hat —
# wörtlich aus dessen `updates`-Dict (plus die Wochentage und die beiden
# Sonderfälle auto_update_enabled und gcal_calendar_id). Speichern je Tab
# darf keinen davon verlieren und keinen dazuerfinden.
LEGACY_KEYS = {
    "autostart", "default_pause", "recipient", "name", "mail_subject",
    "mail_greeting", "mail_content", "mail_closing", "hourly_rate", "state",
    "show_weekend", "always_on_top", "minimize_to_tray", "reminders_enabled",
    "reminder_minutes_before", "send_reminder_enabled", "send_reminder_day",
    "send_reminder_time", "send_reminder_weekend_shift",
    "send_reminder_shift_holidays", "send_reminder_reservations_enabled",
    "send_reminder_default_minutes", "send_period_from_last_reminder",
    "send_period_anchor_monthly", "update_check_frequency",
    "prerelease_updates_enabled", "ui_scale", "werkstudent_limit_enabled",
    "werkstudent_limit_start", "werkstudent_limit_end",
    "werkstudent_limit_max_hours", "pause_warning_enabled", "workweek_only",
    "device_name", "auto_update_enabled",
    *(f"default_start_{k}" for k in WEEKDAY_KEYS),
    *(f"default_end_{k}" for k in WEEKDAY_KEYS),
}


def test_tabs_together_write_exactly_the_legacy_keys():
    written = [
        tr.work_updates(work_raw(), OLD_WSL),
        tr.mail_updates({k: "" for k in tr.MAIL_KEYS}),
        tr.google_updates({"device_name": "", "gcal_calendar": ""}),
        tr.app_updates(app_raw()),
        tr.update_tab_updates({"update_check_frequency": FREQUENCY_OPTIONS[0][1],
                               "prerelease_updates_enabled": False,
                               "auto_update_enabled": True}),
    ]
    keys = [k for upd in written for k in upd]
    assert len(keys) == len(set(keys)), "ein Schlüssel in zwei Tabs"
    assert set(keys) == LEGACY_KEYS
```

- [ ] **Step 2: Rot sehen** — `AttributeError: module ... has no attribute 'slider_percent'`.

- [ ] **Step 3: Implementieren** — Imports oben ergänzen:

```python
from src.devices import sanitize_device_name
from src.holidays_de import code_for_state_label
from src.send_reminder import shift_for_label
from src.settings import (
    WEEKDAY_KEYS, clamp_ui_scale, parse_hourly_rate, parse_reminder_minutes,
    resolve_calendar_id,
)
from src.updater import frequency_for_label
```

und ans Ende:

```python
# ---- Bericht & Mail ------------------------------------------------------

MAIL_KEYS = ("recipient", "name", "mail_subject", "mail_greeting",
             "mail_content", "mail_closing")


def mail_updates(raw: Mapping[str, Any]) -> dict[str, Any]:
    return {key: raw[key] for key in MAIL_KEYS}


# ---- Google --------------------------------------------------------------

def google_updates(raw: Mapping[str, Any]) -> dict[str, Any]:
    # Am Rand saniert (Länge, Steuerzeichen): der Name reist über die
    # Sync-Registry zu anderen Geräten und landet dort in einem Label.
    return {"device_name": sanitize_device_name(raw["device_name"])}


def calendar_update(cal_map: Mapping[str, str], selected: str,
                    stored_id: str | None, gcal_enabled: bool) -> str | None:
    """Neue Kalender-ID, falls sie sich ändert, sonst `None`.

    Nur mit geladener Liste (`cal_map` gefüllt): davor steht in der Combobox
    die gespeicherte ID statt eines Klarnamens, und ein vorschnelles
    Speichern schriebe über `resolve_calendar_id` "primary" fest."""
    if not gcal_enabled or not cal_map:
        return None
    new_id = resolve_calendar_id(dict(cal_map), selected, stored_id or "")
    return new_id if new_id != stored_id else None


# ---- App -----------------------------------------------------------------

def slider_percent(value: float) -> int:
    """Skalierungs-Regler auf 5er-Schritte (ttk.Scale kennt kein
    `resolution`)."""
    return round(value / 5) * 5


def validate_app(raw: Mapping[str, Any]) -> tuple[str, str] | None:
    if parse_reminder_minutes(raw["reminder_minutes_before"]) is None:
        return ("Erinnerungszeit ungültig",
                "Bitte eine ganze Zahl zwischen 0 und 120 Minuten angeben.")
    return None


def app_updates(raw: Mapping[str, Any]) -> dict[str, Any]:
    """Settings-Werte des App-Tabs. Setzt `validate_app` voraus."""
    minutes = parse_reminder_minutes(raw["reminder_minutes_before"])
    if minutes is None:
        raise ValueError("app_updates ohne vorheriges validate_app")
    return {
        "autostart": bool(raw["autostart"]),
        "state": code_for_state_label(raw["state"]),
        "show_weekend": bool(raw["show_weekend"]),
        "always_on_top": bool(raw["always_on_top"]),
        "minimize_to_tray": bool(raw["minimize_to_tray"]),
        "ui_scale": clamp_ui_scale(slider_percent(float(raw["ui_scale"])) / 100),
        "reminders_enabled": bool(raw["reminders_enabled"]),
        "reminder_minutes_before": minutes,
        "send_reminder_enabled": bool(raw["send_reminder_enabled"]),
        "send_reminder_day": int(raw["send_reminder_day"]),
        "send_reminder_time": raw["send_reminder_time"],
        "send_reminder_weekend_shift": shift_for_label(
            raw["send_reminder_weekend_shift"]),
        "send_reminder_shift_holidays": bool(raw["send_reminder_shift_holidays"]),
        "send_reminder_reservations_enabled": bool(
            raw["send_reminder_reservations_enabled"]),
        "send_reminder_default_minutes": int(raw["send_reminder_default_minutes"]),
        "send_period_from_last_reminder": bool(
            raw["send_period_from_last_reminder"]),
        "send_period_anchor_monthly": bool(raw["send_period_anchor_monthly"]),
    }


# ---- Updates -------------------------------------------------------------

def update_tab_updates(raw: Mapping[str, Any]) -> dict[str, Any]:
    updates: dict[str, Any] = {
        "update_check_frequency": frequency_for_label(raw["update_check_frequency"]),
        "prerelease_updates_enabled": bool(raw["prerelease_updates_enabled"]),
    }
    # Fehlt, wo die Plattform kein Selbst-Update kann (der Tab baut den
    # Schalter dann gar nicht) — der gespeicherte Wert bleibt unangetastet.
    if "auto_update_enabled" in raw:
        updates["auto_update_enabled"] = bool(raw["auto_update_enabled"])
    return updates
```

Prüfen, dass `sanitize_device_name("  Laptop\x07 ")` wirklich `"Laptop"` liefert (`src/devices.py:49`); falls es Steuerzeichen durch Leerzeichen ersetzt statt entfernt, den Erwartungswert im Test an das tatsächliche, dort dokumentierte Verhalten anpassen — der Test prüft nur, dass saniert wird. `send_reminder_day`/`send_reminder_default_minutes` kommen aus schreibgeschützten Comboboxen — `int()` wie bisher.

- [ ] **Step 4: Grün sehen** — `.venv/bin/python -m pytest tests/test_tab_rules.py tests/test_type_annotations.py -q` → PASS.

- [ ] **Step 5: ruff + pyright, Commit** — „feat(einstellungen): Prüfung und Umrechnung der übrigen Tabs, Schlüssel-Vertrag als Test (#132)"

---

### Task 5: Tab-Schnittstelle — Arbeitszeit und Bericht & Mail

**Files:**
- Modify: `src/dialogs/settings_dialog/tab_work.py`, `src/dialogs/settings_dialog/tab_mail.py`

**Interfaces:**
- Consumes: `FieldSet` (Task 2), `SaveOutcome` (Task 1), `validate_work`/`work_updates`/`wsl_snapshot`/`WSL_KEYS`/`MAIL_KEYS`/`mail_updates` (Task 3/4).
- Produces: `WorkTab` und `MailTab` erfüllen `SettingsTab` und tragen `fields: FieldSet`. Die bisherigen Variablen-Attribute (`start_vars`, `rate_var`, …) **bleiben** bis Task 7 — das alte `save_settings` liest sie noch, die App bleibt zwischen den Tasks lauffähig.

Kein Unit-Test (Tk-Aufbau, s. Spec „Tests"); die Logik ist in Task 1–4 getestet, das Zusammenspiel prüft Task 8.

- [ ] **Step 1: `WorkTab`** — Imports ergänzen:

```python
from src.dialogs.settings_dialog.fields import FieldSet
from src.dialogs.settings_dialog.form_model import SaveOutcome
from src.dialogs.settings_dialog.tab_rules import (
    WSL_KEYS, validate_work, work_updates, wsl_snapshot,
)
from src.theme import themed_showwarning      # in den bestehenden theme-Import
from src.weekly_limit import (
    format_limit_warnings, period_scan_needed, scan_period_for_warnings,
)
```

Klassen-Docstring: „Baut den Arbeitszeit-Tab; Tab-Schnittstelle für den `SaveCoordinator` (#132)." Am Ende von `__init__` (nach den bestehenden `self.…`-Zuweisungen):

```python
        self.title = "Arbeitszeit"
        self._dialog = dialog
        self._settings = settings
        self._storage = storage

        fields = FieldSet()
        fields.add("workweek_only", workweek_only_var)
        for key in WEEKDAY_KEYS:
            fields.add(f"default_start_{key}", start_vars[key])
            fields.add(f"default_end_{key}", end_vars[key])
        fields.add("default_pause", pause_var)
        fields.add("pause_warning_enabled", pause_warning_var)
        fields.add("hourly_rate", rate_var)
        fields.add("werkstudent_limit_enabled", wsl_enabled_var)
        # Jahr → Monat → Tag ist Absicht: die Datumszeile klemmt den Tag bei
        # jedem Schreibzugriff auf die Monatslänge, und `FieldSet.load`
        # schreibt in dieser Reihenfolge zurück (Verwerfen nach 31.01. →
        # Februar ergäbe sonst den 28.01.).
        for which, (day, month, year) in (("start", wsl_start_vars),
                                          ("end", wsl_end_vars)):
            fields.add(f"werkstudent_limit_{which}.year", year)
            fields.add(f"werkstudent_limit_{which}.month", month)
            fields.add(f"werkstudent_limit_{which}.day", day)
        fields.add("werkstudent_limit_max_hours", wsl_hours_var)
        self.fields = fields
```

und die Methoden:

```python
    def values(self):
        return self.fields.values()

    def load(self, values):
        self.fields.load(values)

    def validate(self):
        return validate_work(self.values())

    def save(self):
        settings = self._settings
        old = {key: settings.get(key) for key in WSL_KEYS}
        updates = work_updates(self.values(), old)
        settings.apply_updates(updates)
        # Geänderter Limit-Zeitraum: bereits erfasste Wochen darin prüfen —
        # sonst fiele eine Überschreitung erst beim nächsten Eintrag auf.
        if self._storage is not None and period_scan_needed(
                wsl_snapshot(old), wsl_snapshot(updates)):
            warnings = scan_period_for_warnings(settings, self._storage.get_all())
            if warnings:
                themed_showwarning(
                    self._dialog, "Wochenlimit überschritten",
                    "Im konfigurierten Zeitraum liegen bereits erfasste Wochen "
                    f"über dem Limit:\n\n{format_limit_warnings(warnings)}\n\n"
                    "Grobe Näherung, keine rechtliche Bewertung.",
                )
        return SaveOutcome(saved=True)
```

`wsl_start_vars` ist `(day, month, year)` (`DateRow.vars`) — die Entpackung oben entspricht dem.

- [ ] **Step 2: `MailTab`** — Imports:

```python
from src.dialogs.settings_dialog.fields import FieldSet
from src.dialogs.settings_dialog.form_model import SaveOutcome
from src.dialogs.settings_dialog.tab_rules import mail_updates
```

Am Ende von `__init__`:

```python
        self.title = "Bericht & Mail"
        self._settings = settings
        fields = FieldSet()
        fields.add("recipient", recipient_var)
        fields.add("name", name_var)
        fields.add("mail_subject", subject_var)
        fields.add("mail_greeting", greeting_var)
        # Nach dem Einfügen des Anfangstexts (oben) — add_text setzt das
        # Modified-Flag zurück, das das Einfügen gesetzt hat.
        fields.add_text("mail_content", content_text)
        fields.add_text("mail_closing", closing_text)
        self.fields = fields

    def values(self):
        return self.fields.values()

    def load(self, values):
        self.fields.load(values)

    def validate(self):
        return None

    def save(self):
        self._settings.apply_updates(mail_updates(self.values()))
        return SaveOutcome(saved=True)
```

Klassen-Docstring anpassen wie bei `WorkTab`.

- [ ] **Step 3: Lauffähigkeit prüfen** — `.venv/bin/python -m pytest -q`, `ruff check .`, pyright. Kurz `ZEITERFASSUNG_DATA_DIR=<scratchpad>/data .venv/bin/python -m src.main` starten, Einstellungen öffnen: der Dialog baut sich wie bisher (alter Speichern-Weg aktiv).

- [ ] **Step 4: Commit** — „feat(einstellungen): Arbeitszeit- und Mail-Tab mit Tab-Schnittstelle (#132)"

---

### Task 6: Tab-Schnittstelle — Google, App, Updates, Webhooks/SMTP

**Files:**
- Modify: `src/dialogs/settings_dialog/tab_google.py`, `tab_app.py`, `tab_updates.py`, `_record_list_tab.py`, `tab_webhooks.py`, `tab_smtp.py`

**Interfaces:**
- Consumes: wie Task 5, dazu `google_updates`/`calendar_update`/`validate_app`/`app_updates`/`slider_percent`/`update_tab_updates`.
- Produces:
  - `GoogleTab`: `SettingsTab` + `fields`; neues Attribut `on_calendars_loaded: Callable[[], None] | None` (Default `None`), gerufen am Ende von `_populate_calendars`.
  - `AppTab(frame, settings, dialog, parent, base_path)` — **neue Signatur**; `SettingsTab` + `fields`.
  - `UpdatesTab`: `SettingsTab` + `fields`.
  - `RecordListTab`: `SettingsTab` + leeres `fields`; `WebhooksTab.title = "Webhooks"`, `SmtpTab.title = "SMTP"`.

- [ ] **Step 1: `GoogleTab`** — Imports:

```python
from src.dialogs.settings_dialog.fields import FieldSet
from src.dialogs.settings_dialog.form_model import SaveOutcome
from src.dialogs.settings_dialog.tab_rules import calendar_update, google_updates
```

In `__init__` vor `self._build_account_section()`:

```python
        self.title = "Google"
        # Setzt der Dialog: nach dem Nachladen der Kalenderliste steht in
        # `cal_var` der Klarname statt der ID — das ist keine Änderung des
        # Nutzers, der Coordinator übernimmt es als gespeichert.
        self.on_calendars_loaded = None
```

nach `self._build_calendar_section(next_row)`:

```python
        fields = FieldSet()
        fields.add("device_name", self.device_name_var)
        fields.add("gcal_calendar", self.cal_var)
        self.fields = fields
```

Am Ende von `_populate_calendars` (nach `self._cal_status.config(text="")`):

```python
        if self.on_calendars_loaded is not None:
            self.on_calendars_loaded()
```

Methoden:

```python
    def values(self):
        return self.fields.values()

    def load(self, values):
        self.fields.load(values)

    def validate(self):
        return None

    def save(self):
        settings = self._settings
        raw = self.values()
        settings.apply_updates(google_updates(raw))
        new_id = calendar_update(
            self.cal_map, raw["gcal_calendar"],
            settings.get("gcal_calendar_id"), bool(settings.get("gcal_enabled")))
        if new_id is not None:
            settings.set_synced("gcal_calendar_id", new_id)
        return SaveOutcome(saved=True)
```

Kommentar am Gerätenamen-Feld (`# … (der Dialog schließt beim Speichern, das Ergebnis sähe man erst beim nächsten Öffnen).`) auf den neuen Stand bringen: der Dialog bleibt offen, gekürzt würde trotzdem erst beim Speichern — sichtbar machen bleibt richtig.

- [ ] **Step 2: `AppTab`** — Signatur `def __init__(self, frame, settings, dialog, parent, base_path):`. Imports:

```python
from src.autostart import (
    disable_autostart, enable_autostart, is_autostart_enabled,
    resolve_autostart_target,
)
from src.dialogs.settings_dialog.fields import FieldSet
from src.dialogs.settings_dialog.form_model import SaveOutcome
from src.dialogs.settings_dialog.tab_rules import (
    app_updates, slider_percent, validate_app,
)
from src.theme import (…bestehend…, scaled_window_fits, themed_askyesno,
                       themed_showerror, workarea_for)
```

Den Prozent-Label-Abgleich des Reglers von `command=_on_scale` auf einen Trace umstellen, damit er auch beim Verwerfen (`load`) mitzieht — `command` feuert nur bei Benutzerbewegung:

```python
        def _on_scale(*_args):
            scale_value_label.config(text=f"{slider_percent(scale_var.get())} %")

        scale_var.trace_add("write", _on_scale)
```

(`command=_on_scale` am `ttk.Scale` entfernen; die initiale Beschriftung nutzt ebenfalls `slider_percent`.)

Am Ende von `__init__`:

```python
        self.title = "App"
        self._settings = settings
        self._dialog = dialog
        self._parent = parent
        self._base_path = base_path

        fields = FieldSet()
        fields.add("state", state_var)
        fields.add("show_weekend", show_weekend_var)
        fields.add("autostart", autostart_var)
        fields.add("always_on_top", always_on_top_var)
        fields.add("minimize_to_tray", minimize_to_tray_var)
        # Gerastert gelesen: ein hin- und zurückgezogener Regler ist keine
        # Änderung.
        fields.add("ui_scale", scale_var, read=slider_percent)
        fields.add("reminders_enabled", reminders_enabled_var)
        fields.add("reminder_minutes_before", reminder_minutes_var)
        fields.add("send_reminder_enabled", send_reminder_enabled_var)
        fields.add("send_reminder_day", send_reminder_day_var)
        fields.add("send_reminder_time", send_reminder_time_var)
        fields.add("send_reminder_weekend_shift", send_reminder_shift_var)
        fields.add("send_reminder_shift_holidays", send_reminder_shift_holidays_var)
        fields.add("send_reminder_reservations_enabled", send_reminder_reservations_var)
        fields.add("send_reminder_default_minutes", send_reminder_default_minutes_var)
        fields.add("send_period_from_last_reminder", send_period_from_last_var)
        fields.add("send_period_anchor_monthly", send_period_anchor_monthly_var)
        self.fields = fields
```

Methoden — die Logik aus dem alten `save_settings`, in neuer Reihenfolge (Rückfrage vor Nebenwirkung, s. „Abweichungen" Punkt 5):

```python
    def values(self):
        return self.fields.values()

    def load(self, values):
        self.fields.load(values)

    def validate(self):
        return validate_app(self.values())

    def save(self):
        settings = self._settings
        updates = app_updates(self.values())
        old_scale = settings.get("ui_scale")
        new_scale = updates["ui_scale"]
        # Erst die Frage, dann die Nebenwirkung: wer die Skalierung hier
        # ablehnt, soll keinen bereits umgeschalteten Autostart zurückbehalten.
        if new_scale > old_scale and not self._scale_confirmed(old_scale, new_scale):
            return SaveOutcome(saved=False)
        # Autostart vor dem Schreiben: scheitert er, wird nichts gespeichert.
        new_autostart = updates["autostart"]
        if new_autostart != is_autostart_enabled():
            try:
                if new_autostart:
                    target, arguments = resolve_autostart_target(self._base_path)
                    enable_autostart(target, arguments)
                else:
                    disable_autostart()
            except Exception as e:
                themed_showerror(
                    self._dialog, "Autostart-Fehler",
                    f"Autostart konnte nicht geändert werden:\n{e}",
                )
                return SaveOutcome(saved=False)
        settings.apply_updates(updates)
        return SaveOutcome(saved=True, restart=new_scale != old_scale)

    def _scale_confirmed(self, old_scale, new_scale):
        """Passt die größere Skalierung auf den Bildschirm? Sonst fragen.

        Das Hauptfenster ist `resizable(False, False)` und wird auf seine
        angeforderte Größe gepinnt — bei 200 % auf einem 1080p-Schirm ist die
        Fußzeile abgeschnitten. Verhindert wird nichts: die Entscheidung
        gehört dem Nutzer, und sie ist umkehrbar, weil das Zahnrad im Header
        sitzt."""
        _, wa_top, _, wa_bottom = workarea_for(self._parent)
        available = wa_bottom - wa_top
        needed, fits = scaled_window_fits(
            self._parent.winfo_height(), old_scale, new_scale, available)
        if fits:
            return True
        return themed_askyesno(
            self._dialog, "Passt nicht auf den Bildschirm",
            f"Bei {round(new_scale * 100)} % braucht das Fenster etwa "
            f"{needed} Pixel Höhe — dein Bildschirm bietet "
            f"{available}.\n\nDie Fußzeile mit "
            "„Arbeitszeiten senden“, „Export“ und „Teilen“ wäre dann "
            "abgeschnitten. Die Einstellungen bleiben über das Zahnrad "
            "oben erreichbar.\n\nTrotzdem übernehmen?",
        )
```

Den Meldungstext **wortgleich** aus `dialog.py` übernehmen (dort vor dem Löschen in Task 7 vergleichen).

- [ ] **Step 3: `UpdatesTab`** — Imports `FieldSet`, `SaveOutcome`, `update_tab_updates`. Nach dem Aufbau des Schalters `auto_update_var`:

```python
        self.title = "Updates"
        fields = FieldSet()
        fields.add("update_check_frequency", self.frequency_var)
        fields.add("prerelease_updates_enabled", self.prerelease_var)
        if self.auto_update_var is not None:
            fields.add("auto_update_enabled", self.auto_update_var)
        self.fields = fields
```

Methoden:

```python
    def values(self):
        return self.fields.values()

    def load(self, values):
        self.fields.load(values)

    def validate(self):
        return None

    def save(self):
        self._settings.apply_updates(update_tab_updates(self.values()))
        return SaveOutcome(saved=True)
```

Klassen-Docstring „exponiert `frequency_var` für save_settings" → „Tab-Schnittstelle für den `SaveCoordinator` (#132)".

- [ ] **Step 4: `RecordListTab`** — Imports `FieldSet`, `SaveOutcome`. Ans Ende von `__init__`:

```python
        # Keine Formularfelder: Einträge speichern ihre Unterdialoge selbst
        # (eigener Klick, eigenes Speichern). Der Tab ist nie „geändert".
        self.fields = FieldSet()
```

Methoden:

```python
    def values(self):
        return {}

    def load(self, values):
        pass  # nichts zu laden — s. `fields`

    def validate(self):
        return None

    def save(self):
        return SaveOutcome(saved=True)
```

Klassenattribut `title: str` in `RecordListTab` deklarieren; `WebhooksTab.title = "Webhooks"`, `SmtpTab.title = "SMTP"`.

- [ ] **Step 5: `dialog.py` minimal nachziehen** — nur der geänderte Konstruktor: `AppTab(tab_app, settings, dialog, parent, base_path)`. Der Rest folgt in Task 7.

- [ ] **Step 6: Lauffähigkeit prüfen** — pytest/ruff/pyright grün; App mit Scratch-Daten starten, Einstellungen öffnen, alter Speichern-Weg funktioniert noch, Regler-Prozent zieht beim Bewegen mit.

- [ ] **Step 7: Commit** — „feat(einstellungen): Google-, App-, Updates- und Listen-Tabs mit Tab-Schnittstelle (#132)"

---

### Task 7: `dialog.py` — Coordinator verdrahten, `save_settings` entfernen

**Files:**
- Modify: `src/dialogs/settings_dialog/dialog.py`, `tab_webhooks.py`, `tab_smtp.py`, `tab_work.py`, `tab_mail.py`, `tab_app.py`, `tab_updates.py`, `tab_google.py`

**Interfaces:**
- Consumes: `SaveCoordinator` (Task 1), alle Tabs (Task 5/6), `themed_ask_save_changes`, `set_primary_button_enabled` (Theme).
- Produces: `open_settings_dialog` mit unveränderter Signatur; `initial_tab` akzeptiert zusätzlich `"smtp"`.

- [ ] **Step 1: Importe** — in `dialog.py` entfallen alle Importe, die nur `save_settings` brauchte (`datetime`, `autostart`, `sanitize_device_name`, `frequency_for_label`, `shift_for_label`, `code_for_state_label`, `settings`-Helfer, `validate_period`, `validate_entry`, `DAYS_DE`, `weekly_limit`, `scaled_window_fits`, `workarea_for`, `themed_askyesno`, `themed_showwarning`). Neu:

```python
from src.dialogs.settings_dialog.form_model import SaveCoordinator
from src.theme import (
    BG,
    apply_combobox_style, apply_notebook_style, attach_unfocus_on_click,
    center_dialog_on_parent, create_dialog,
    primary_button, secondary_button, set_primary_button_enabled,
    themed_ask_save_changes, themed_showerror,
)
```

`ruff check .` meldet übrig gebliebene.

- [ ] **Step 2: Docstring** von `open_settings_dialog`: „on_change wird nach erfolgreichem Speichern aufgerufen" → „… nach jedem erfolgreichen Speichern eines Tabs aufgerufen (der Dialog bleibt offen)". Ergänzen: „Gespeichert wird je Tab (#132): „Speichern" schreibt nur den aktiven Tab; wer einen geänderten Tab verlässt oder den Dialog schließt, wird gefragt (`form_model.SaveCoordinator`)."

- [ ] **Step 3: Tabs sammeln, Coordinator bauen** — `SmtpTab(...)` bekommt eine Variable: `smtp = SmtpTab(tab_smtp, dialog, smtp_store, runner, parent)`. Alles ab `def _on_tab_changed` bis zum Ende der Funktion ersetzen durch:

```python
    # Vor dem initialen select deklariert und gebunden (wie bisher): der
    # Banner-Weg (initial_tab="updates") startet so seinen Live-Check über
    # <<NotebookTabChanged>>. on_tab_selected ist idempotent (self._checked).
    coordinator = None

    def _refresh_save_button():
        if coordinator is None or not dialog.winfo_exists():
            return
        set_primary_button_enabled(save_btn, coordinator.dirty())

    def _on_tab_changed(_event):
        if notebook.select() == str(updates_tab.frame):
            updates_tab.on_tab_selected()
        _refresh_save_button()

    notebook.bind("<<NotebookTabChanged>>", _on_tab_changed)

    # Reihenfolge = Reiterreihenfolge im Notebook: der Reiter-Klick unten
    # rechnet über den Index auf den Schlüssel um.
    tabs = {
        "work": work,
        "mail": mail,
        "webhooks": hooks,
        "smtp": smtp,
        "google": google,
        "app": app,
        "updates": updates_tab,
    }
    keys = list(tabs)
    assert len(keys) == notebook.index("end"), "tabs und Notebook laufen auseinander"

    # Springt direkt auf den gewünschten Tab, statt den Nutzer beim Default
    # ("Arbeitszeit") suchen zu lassen. Läuft vor dem ersten Edit — der
    # Coordinator braucht hier nicht zu fragen.
    current = initial_tab if initial_tab in tabs else "work"
    notebook.select(tabs[current].frame)

    def _restart():
        # Der Neustart nimmt den Dialog mit; der Coordinator liefert danach
        # False, damit niemand mehr an diesem Fenster etwas tut.
        dialog.destroy()
        if on_request_restart is not None:
            on_request_restart()

    coordinator = SaveCoordinator(
        tabs, current,
        ask=lambda title: themed_ask_save_changes(dialog, title),
        show_error=lambda title, msg: themed_showerror(dialog, title, msg),
        on_change=on_change,
        on_restart=_restart,
    )

    def _save():
        # Ein grauer Knopf ist nur optisch gesperrt (set_primary_button_enabled)
        # — ohne Änderungen ist save_current ein No-op.
        coordinator.save_current()
        _refresh_save_button()

    def _close():
        if coordinator.request_close() and dialog.winfo_exists():
            dialog.destroy()

    btn_frame = tk.Frame(dialog, bg=BG)
    btn_frame.pack(pady=12)
    save_btn = primary_button(btn_frame, "Speichern", _save)
    save_btn.pack(side=tk.LEFT, padx=5)
    secondary_button(btn_frame, "Schließen", _close).pack(side=tk.LEFT, padx=5)

    for tab in tabs.values():
        tab.fields.on_edit(_refresh_save_button)

    def _on_calendars_loaded():
        coordinator.rebaseline("google", ["gcal_calendar"])
        _refresh_save_button()

    google.on_calendars_loaded = _on_calendars_loaded

    def _on_tab_click(event):
        """Fängt den Reiter-Klick VOR dem Wechsel ab: ttk.Notebook kennt kein
        Veto, `<<NotebookTabChanged>>` käme erst danach. Die Widget-Bindung
        läuft vor der Klassenbindung des Notebooks; "break" verhindert den
        Wechsel. Tastatur-Traversal (enable_traversal) ist nicht aktiv."""
        try:
            index = notebook.index(f"@{event.x},{event.y}")
        except tk.TclError:
            return None   # Klick neben die Reiter: das Notebook tut nichts
        target = keys[index]
        if target == coordinator.current:
            return None
        if coordinator.request_switch(target) and dialog.winfo_exists():
            notebook.select(tabs[target].frame)
        return "break"

    notebook.bind("<Button-1>", _on_tab_click)
    _refresh_save_button()

    attach_unfocus_on_click(dialog)
    dialog.protocol("WM_DELETE_WINDOW", _close)
    dialog.bind("<Escape>", lambda _e: _close())
    center_dialog_on_parent(dialog, parent)
```

`_refresh_save_button` liest `coordinator` und `save_btn` erst beim Aufruf — beide existieren dann (der erste Aufruf über `<<NotebookTabChanged>>` kommt asynchron über die Event-Queue, frühestens nach dem Aufbau; die `None`-Prüfung ist die Absicherung dafür und hält pyright zufrieden). Sollte pyright `save_btn` als „possibly unbound" melden, `save_btn = None` neben `coordinator = None` deklarieren und in der Prüfung mitnehmen.

- [ ] **Step 4: Veraltete Texte** — `tab_webhooks.py`/`tab_smtp.py`: „— unabhängig vom „Abbrechen“ dieses Einstellungen-Dialogs." → „— unabhängig vom „Speichern“ dieses Einstellungen-Dialogs." Die Variablen-Attribute der Tabs (`start_vars`, `rate_var`, `content_text`, `scale_var`, …) **bleiben** — die Tabs nutzen sie teils selbst, das Smoke-Skript in Task 8 liest sie, und sie kosten nichts. Nur Docstrings und Kommentare, die sie „für save_settings" erklären, auf die Tab-Schnittstelle umstellen: `grep -rn "save_settings" src tests` muss danach leer sein (außer in historischen Kommentaren, die ausdrücklich „früher" sagen).

- [ ] **Step 5: Grün** — pytest/ruff/pyright. `tests/test_dialog_reveal.py` muss weiter grün sein (die Paarung `create_dialog`/`center_dialog_on_parent` bleibt in `open_settings_dialog`).

- [ ] **Step 6: Commit** — „feat(einstellungen): Speichern je Tab — Rückfrage beim Verlassen, Dialog bleibt offen (#132)"

---

### Task 8: Smoke-Skript (nicht eingecheckt) — Abläufe im echten Tk

**Files:**
- Create: `<scratchpad>/smoke_pr2.py` (nicht im Repo)

Prüft im echten Tk, was die Unit-Tests nicht sehen: Reiter-Klick-Abfangen, Knopf-Zustand, Text-`<<Modified>>`, Verwerfen der Datumszeile, Banner-Weg. Läuft mit `ZEITERFASSUNG_DATA_DIR` auf Scratch-Daten; `themed_ask_save_changes` wird durch eine skriptbare Antwort ersetzt.

- [ ] **Step 1: Skript schreiben** — `<scratchpad>/smoke_pr2.py`. An die Tabs kommt das Skript über einen aufzeichnenden Coordinator (Unterklasse, per Monkeypatch in `dialog.py` eingesetzt) — `open_settings_dialog` wird für den Test **nicht** umgebaut.

```python
"""Smoke-Test PR 2 (#132): Speichern je Tab im echten Tk. Nicht einchecken.

Aufruf aus dem Repo-Root:
  ZEITERFASSUNG_DATA_DIR=<scratch>/data .venv/bin/python <scratch>/smoke_pr2.py
"""
import os
import sys
import tkinter as tk

sys.path.insert(0, os.getcwd())

import src.dialogs.settings_dialog.dialog as dlg
from src.paths import get_base_path
from src.settings import Settings
from src.theme import init_fonts

answers, asked, errors = [], [], []
dlg.themed_ask_save_changes = lambda parent, title: (asked.append(title), answers.pop(0))[1]
dlg.themed_showerror = lambda parent, title, msg: errors.append(title)


class Recording(dlg.SaveCoordinator):
    last = None

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        Recording.last = self


dlg.SaveCoordinator = Recording


class Runner:            # kein Netz: Hintergrundaufgaben laufen nie zu Ende
    def run(self, fn, on_done):
        pass


class AutoUpdater:
    def maybe_start(self, *a, **k):
        return "disabled"


base = get_base_path()
assert os.environ.get("ZEITERFASSUNG_DATA_DIR") == base, "nur mit Scratch-Daten"
root = tk.Tk()
init_fonts(root, 1.0)
settings = Settings(os.path.join(base, "settings.json"))
changes = []


def open_dialog(**kw):
    dlg.open_settings_dialog(root, settings, base, lambda: changes.append(1),
                             runner=Runner(), auto_updater=AutoUpdater(), **kw)
    root.update()
    coord = Recording.last
    dialog = coord._tabs["work"].frame.winfo_toplevel()
    notebook = coord._tabs["work"].frame.master
    return coord, dialog, notebook


coord, dialog, notebook = open_dialog()
tabs = coord._tabs


def click_tab(index):
    for x in range(2, notebook.winfo_width()):
        try:
            if notebook.index(f"@{x},5") == index:
                break
        except tk.TclError:
            continue
    else:
        raise AssertionError(index)
    notebook.event_generate("<Button-1>", x=x + 3, y=5)
    notebook.event_generate("<ButtonRelease-1>", x=x + 3, y=5)
    root.update()


def save_enabled():
    # set_primary_button_enabled schaltet den Cursor mit (hand2 ↔ arrow).
    btns = [w for w in dialog.winfo_children() if isinstance(w, tk.Frame)]
    save_btn = btns[-1].winfo_children()[0]
    return save_btn.cget("cursor") == "hand2"


# 1) Frisch: Knopf grau, Wechsel ohne Rückfrage
assert not save_enabled()
click_tab(1)
assert notebook.index("current") == 1 and asked == [], asked

# 2) Mail-Text tippen → Knopf aktiv, Wechsel fragt, "cancel" bleibt
mail = tabs["mail"]
mail.content_text.insert("end", " geändert")
root.update()
assert save_enabled()
answers.append("cancel")
click_tab(0)
assert notebook.index("current") == 1 and asked == ["Bericht & Mail"], asked

# 3) "discard" stellt den Text wieder her und wechselt
answers.append("discard")
click_tab(0)
assert notebook.index("current") == 0
assert "geändert" not in mail.content_text.get("1.0", "end-1c")

# 4) "save" schreibt nur diesen Tab, on_change genau einmal
click_tab(1)
mail.content_text.insert("end", " X")
root.update()
answers.append("save")
before = len(changes)
click_tab(0)
assert settings.get("mail_content").endswith(" X")
assert len(changes) == before + 1

# 5) Datumszeile: Verwerfen nach Monatswechsel stellt den 31. wieder her
work = tabs["work"]
day, month, year = work.wsl_start_vars
year.set("2026"); month.set("1"); day.set("31")
assert coord.save_current()
month.set("2")
assert day.get() == "28"
answers.append("discard")
click_tab(1)
assert (day.get(), month.get()) == ("31", "1"), (day.get(), month.get())
click_tab(0)

# 6) Validierungsfehler hält fest
work.start_vars["mon"].set("17:00"); work.end_vars["mon"].set("09:00")
answers.append("save")
click_tab(1)
assert notebook.index("current") == 0 and errors == ["Standard-Arbeitszeit ungültig"]
answers.append("discard")
click_tab(1)

# 7) Regler: 101 ist keine Änderung, 125 schon; Verwerfen setzt zurück
app = tabs["app"]
coord.request_switch("app"); notebook.select(app.frame); root.update()
app.scale_var.set(101)
assert not coord.dirty()
app.scale_var.set(125)
assert coord.dirty()

# 8) Schließen über X mit Änderung: "cancel" lässt offen, "discard" schließt
answers.append("cancel")
dialog.tk.eval(dialog.protocol("WM_DELETE_WINDOW"))
root.update()
assert dialog.winfo_exists()
answers.append("discard")
dialog.tk.eval(dialog.protocol("WM_DELETE_WINDOW"))
root.update()
assert not dialog.winfo_exists()

# 9) Banner-Weg: genau ein Live-Check
checks = []
orig = dlg.UpdatesTab._check_now
dlg.UpdatesTab._check_now = lambda self: checks.append(1)
coord, dialog, notebook = open_dialog(initial_tab="updates")
root.update()
assert checks == [1], checks
dlg.UpdatesTab._check_now = orig

print("OK", asked)
root.destroy()
```

Die Tab-Attribute, die das Skript liest (`content_text`, `wsl_start_vars`, `start_vars`, `end_vars`, `scale_var`), müssen dafür nach Task 7 noch existieren: in Task 7 Step 4 **nicht** entfernen — oder dort, wo sie entfallen, im Skript über `tab.fields` gehen. Weicht die Knopf-Erkennung in `save_enabled` ab (Aufbau von `primary_button`), dort an `theme/widgets.py` anpassen, nicht am Dialog.

- [ ] **Step 2: Sichtprüfung** — die App mit Scratch-Daten starten, einmal von Hand: Feld ändern → Knopf wird rot, anderen Reiter klicken → Rückfrage, Speichern → Dialog bleibt offen. Screenshot der Rückfrage (`import -window root <scratch>/pr2-rueckfrage.png`) für die PR-Beschreibung.

- [ ] **Step 3: Laufen lassen** — `mkdir -p <scratch>/data && ZEITERFASSUNG_DATA_DIR=<scratch>/data .venv/bin/python <scratch>/smoke_pr2.py` → `OK …`.

- [ ] **Step 4: Kein Commit** (Skript bleibt im Scratchpad). Gefundene Fehler als eigene Fix-Commits in den betroffenen Tasks-Dateien.

---

### Task 9: Doku

**Files:**
- Modify: `src/CLAUDE.md` (Abschnitt „Dialoge", `settings_dialog/`-Absatz), `src/dialogs/settings_dialog/__init__.py` (Docstring), `src/dialogs/settings_dialog/tab_work.py` (Kommentar „save_settings schreibt unverändert alle Wochentage zurück" → `tab_rules.work_updates`)

- [ ] **Step 1: `src/CLAUDE.md`** — im `settings_dialog/`-Absatz „`dialog.py` trägt Chrome + zentrales, ablaufidentisches `save_settings`; je Tab eine Klasse …, die ihre Tk-Variablen als Attribute für `save_settings` exponiert — **außer** `tab_webhooks` und `tab_smtp`: beide exponieren dafür **keine** Variablen …" ersetzen durch:

> `dialog.py` trägt Chrome und verdrahtet das **Speichern je Tab** (#132); je Tab eine Klasse in `tab_work`/`tab_mail`/`tab_google`/`tab_app`/`tab_updates`/`tab_webhooks`/`tab_smtp`.py mit derselben Schnittstelle: `title`, `fields` (`fields.FieldSet` — die Tk-Variablen und Textfelder des Tabs unter einem Schlüssel), `values()` (roher Formularstand, darf nicht werfen), `validate()`, `save() -> SaveOutcome`, `load(values)`. Prüfung und Umrechnung in Settings-Werte liegen Tk-frei in `tab_rules.py` (je Tab `validate_*`/`*_updates`, der frühere Inhalt von `save_settings`; `test_tabs_together_write_exactly_the_legacy_keys` hält den Schlüsselsatz fest). Wann gefragt, gespeichert oder verworfen wird, entscheidet `form_model.SaveCoordinator`: „Speichern" schreibt nur den aktiven Tab und lässt den Dialog offen; wer einen geänderten Tab verlässt (Reiter-Klick, vor dem Wechsel über `<Button-1>` abgefangen — `ttk.Notebook` kennt kein Veto) oder den Dialog schließt (Knopf, X, Escape), wird gefragt. Werte, die im Hintergrund nachgeladen werden (Kalenderliste), übernimmt `rebaseline` feldweise als gespeichert. `tab_webhooks` und `tab_smtp` haben **keine** Formularfelder (`values()` ist `{}`, nie geändert): Webhooks bzw. SMTP-Konten liegen im jeweils eigenen Store und werden vom `webhook_dialog` bzw. `smtp_dialog` direkt gespeichert.

Den Rest des Absatzes (R12/`RecordListTab`, Updates-Live-Check, `oauth_task`) unverändert lassen.

- [ ] **Step 2: `__init__.py`-Docstring** — „dialog.py trägt Chrome + zentrales save_settings, die vier Tabs sind eigene Klassen-Module" → „dialog.py trägt Chrome und das Speichern je Tab (`form_model.SaveCoordinator`), die Tabs sind eigene Klassen-Module".

- [ ] **Step 3: Spec-Status** — in `docs/superpowers/specs/2026-09-18-einstellungsdialog-132-design.md` unter „PR 2" einen kurzen Absatz „**Umgesetzt mit fünf bewussten Abweichungen**" mit den Punkten 1–5 aus „Abweichungen von der Spec" dieses Plans (je ein Satz).

- [ ] **Step 4: Grün** — pytest (inkl. `test_claude_md_claims.py`), ruff, pyright.

- [ ] **Step 5: Commit** — „docs(#132): Speichern je Tab in src/CLAUDE.md und Spec"

---

## Nach dem Plan

- PR gegen `master`: „feat(einstellungen): Speichern je Tab (#132, PR 2/3)". Beschreibung: was sich für Nutzer ändert (Knöpfe, Rückfrage, Dialog bleibt offen), die Abweichungen von der Spec, der Screenshot aus Task 8. Kein `release:*`-Label; kein CHANGELOG (kommt mit PR 3, s. Spec „Doku").
- Kein plattformspezifischer Code → kein Pre-Release nötig (der steht laut Spec vor PR 3 an).
