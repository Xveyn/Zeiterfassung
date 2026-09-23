# Einstellungs-Dialog #132 — PR 3: Neuschnitt auf sechs Tabs — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Der Einstellungs-Dialog hat sechs inhaltlich geschnittene Tabs (Arbeitszeit · Erinnerungen · Versand · Google · App · Updates), alle gebaut mit `theme.Form(scroll=True)`: linksbündige Abschnitte, eine gemeinsame Beschriftungsspalte, abhängige Optionen eingerückt und ausgegraut, Leertext für leere Listen.

**Architecture:** Jeder Task **verschiebt** eine Gruppe von Feldern vom alten an den neuen Ort — Formular, `FieldSet`-Schlüssel und Umrechnung in `tab_rules.py` wandern zusammen, `dialog.py` wird im selben Task nachgezogen. So schreibt nach jedem Task jeder Settings-Schlüssel genau ein Tab (`test_tabs_together_write_exactly_the_legacy_keys`), und der Dialog ist nach jedem Task bedienbar. Die Tk-freie Logik der neuen `Form`-Fähigkeiten liegt in `theme/form_logic.py` und ist getestet; Tk-Aufbau wird per Smoke-Skript und Screenshots belegt (CLAUDE.md „Getestet wird Logik, nicht UI").

**Tech Stack:** Python 3.12, Tkinter/ttk, pytest, ruff, pyright 1.1.411.

**Spec:** `docs/superpowers/specs/2026-09-18-einstellungsdialog-132-design.md` (Abschnitt „PR 3 — Neuschnitt auf sechs Tabs"). Vorgänger-Pläne: `2026-09-18-einstellungsdialog-132-pr1-bausteine.md`, `2026-09-23-einstellungsdialog-132-pr2-speichern-je-tab.md`.

## Global Constraints

- Branch: `feat/einstellungen-132-pr3` (von `master` nach dem Merge von #159). Nicht auf `master` committen.
- Tabs und `initial_tab`-Schlüssel am Ende genau: `work` „Arbeitszeit" · `reminders` „Erinnerungen" · `sending` „Versand" · `google` „Google" · `app` „App" · `updates` „Updates". `initial_tab="updates"` (Update-Banner, `ui.py`) muss weiter funktionieren.
- Settings-Schlüssel und -Typen, die geschrieben werden, bleiben exakt die heutigen (`LEGACY_KEYS` in `tests/test_tab_rules.py`); jeder Schlüssel wird von genau einem Tab geschrieben.
- Was sofort gilt, bleibt sofort: SMTP-/Webhook-Einträge, Kategorien, Urlaub, die Google-Schalter für Sync und Kalender.
- **Entscheidung:** „Daten importieren" (künftig im App-Tab) lässt den Einstellungen-Dialog **offen** — nach dem Import nur `on_change()`, kein `dialog.destroy()` mehr.
- **Entscheidung:** Linux wird lokal geprüft (Smoke-Skript + Screenshots, Task 10); vor dem Merge triggert der Nutzer einen **Pre-Release** und testet Windows daraus. macOS bleibt ungetestet (Spec „Risiken").
- Kein neues visuelles Vokabular: Farben/Schriften bleiben, nur `Form`-Struktur (Spec „Nicht-Ziele").
- Tk-freie Module (`theme/form_logic.py`, `settings_dialog/tab_rules.py`) vollständig annotiert; sie stehen bereits in `ANNOTATED_MODULES`.
- Pixelangaben im Layout nur über `px()` (`tests/test_pixel_scaling.py`) — `wraplength=`/`length=` nie mit Zahlen-Literal.
- Themed Meldungen für bekannte Fehler, native `messagebox.showerror` mit Traceback für Catch-alls (Root-`CLAUDE.md` „Bekannt-themed / unerwartet-nativ"); kein stummes `except` (`tests/test_catch_all_handlers.py`).
- `Form`-Lebensdauer-Vertrag: ein `Form` je Tab, einmal im Konstruktor gebaut, nie in einer Refresh-Methode; `scroll=True`-Forms nicht verschachteln.
- `Form.depends_on`-Besitz-Vertrag: Widgets, die aus anderem Grund gesperrt werden (Sync-/Kalender-Schalter während des Consent), gehören in **keine** Gruppe.
- Kommentare/Docstrings deutsch, im Stil der Umgebung (erklären das Warum).
- Commits: Nachricht per Datei (`git commit -F <datei>`), Temp-Datei `/tmp/claude-1000/-home-sven-projects-Zeiterfassung/1f02e431-f93a-4538-9cdc-3ef037193ba0/scratchpad/commit-msg.txt`. Jede Nachricht endet mit Leerzeile + `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Nach jedem Task grün, aus `/home/sven/projects/Zeiterfassung`: `.venv/bin/python -m pytest -q`, `ruff check .`, `npx --yes pyright@1.1.411 --pythonpath .venv/bin/python` (0 errors, Warnungen nicht mehr als vorher: 28).
- Keine echten Nutzerdaten: Smoke-/Screenshot-Skripte laufen mit `ZEITERFASSUNG_DATA_DIR` auf einem Scratch-Verzeichnis, `PYTHONPATH=.`.

`SCRATCH` steht im Folgenden für `/tmp/claude-1000/-home-sven-projects-Zeiterfassung/1f02e431-f93a-4538-9cdc-3ef037193ba0/scratchpad`.

## Review Focus

- **„Nur Werktage" an → Verwerfen** → die Sa/So-Zeilen erscheinen wieder (der Trace auf `workweek_only_var` feuert auch bei `FieldSet.load`). Test: Task 10, Smoke-Schritt 2.
- **Ausgegraute Felder behalten ihren Wert und werden trotzdem gespeichert** (Reservierungs-Erinnerung aus, Minuten 15 → gespeichert bleibt 15). Test: Task 3, `test_reminders_updates_keeps_values_of_disabled_options`.
- **Mausrad über dem (kurzen) Inhalt-Textfeld im Versand-Tab** → das Formular scrollt; über einer Combobox scrollt es, ohne den Wert zu ändern. Test: Task 1 (`test_wheel_route_idle_self_scroller_goes_to_form`), Task 10 Smoke-Schritt 5.
- **„Daten importieren" mit ungespeicherter Änderung im App-Tab** → Dialog bleibt offen, die Änderung bleibt stehen (Knopf rot). Test: Task 10, Smoke-Schritt 6.
- **Wochenend-Verschiebung „nicht verschieben"** → „auch Feiertage" ist grau; jede andere Wahl macht es bedienbar. Test: Task 3, `test_shift_moves`.

---

## File Structure

| Datei | Verantwortung |
|---|---|
| `src/theme/form_logic.py` | + `wheel_route(..., can_scroll)`, `WHEEL_STEP`, `NOTCH_UNITS`, `scroll_units`, `scroll_target` (Task 1) |
| `src/theme/form.py` | + `FormRow`, `row(..., align_top)`, `depends_on(..., invert, indent)`, Fokus scrollt ins Bild, ruhende Text/Listbox geben das Rad ab, feste Schrittweite (Task 2) |
| `src/dialogs/date_row.py` | `label_text=None` baut keine eigene Beschriftung (Task 2) |
| `src/dialogs/settings_dialog/tab_rules.py` | je Task neu geschnitten: `validate_reminders`/`reminders_updates`/`shift_moves` (3), `sending_updates` (4), `work_updates` mit `state`/`show_weekend` (5), `app_updates` nur noch Fenster+Skalierung (3–5) |
| `src/dialogs/settings_dialog/tab_reminders.py` (neu) | `RemindersTab` (Task 3) |
| `src/dialogs/settings_dialog/tab_sending.py` (neu, ersetzt `tab_mail.py`) | `SendingTab` mit eingebetteten Listen (Task 4) |
| `src/dialogs/settings_dialog/_record_list_tab.py`, `tab_smtp.py`, `tab_webhooks.py` | Liste wird einbettbar (Abschnitt in `Form`), 3 Zeilen, Knöpfe rechts, Leertext; Datei-/Klassennamen bleiben (Task 4) |
| `src/dialogs/settings_dialog/tab_work.py` | Neuaufbau mit `Form` (Task 5) |
| `src/dialogs/settings_dialog/tab_app.py` | Neuaufbau mit `Form`, Abschnitt „Daten" (Task 6) |
| `src/dialogs/settings_dialog/tab_google.py` | Neuaufbau mit `Form`, „Erweitert" (Task 7) |
| `src/dialogs/settings_dialog/tab_updates.py` | Neuaufbau mit `Form`, Changelog nach oben (Task 8) |
| `src/dialogs/settings_dialog/dialog.py` | Tab-Liste je Task, am Ende die sechs (Task 3, 4, 6) |
| `src/dialogs/settings_dialog/_shared.py` | entfällt (Task 8) |
| Tests | `test_form_logic.py`, `test_tab_rules.py`, `test_record_list_tabs.py`, `test_import_apply_order.py` (Docstring) |
| Doku | `src/CLAUDE.md`, Root-`CLAUDE.md`, `README.md`, `send_dialog.py`-Hinweistext, Spec (Task 9) |

---

### Task 1: `form_logic` — Rad-Routing, Schrittweite, Fokus-Ziel (+ Vorher-Screenshots)

**Files:**
- Modify: `src/theme/form_logic.py`
- Test: `tests/test_form_logic.py`
- Create (nicht im Repo): `SCRATCH/shots.py`

**Interfaces:**
- Produces:
  - `wheel_route(widget_class: str, can_scroll: bool = True) -> WheelRoute` — `Text`/`Listbox` ohne Scrollbedarf → `"form"`.
  - `WHEEL_STEP: int = 20` (px bei 100 %, `yscrollincrement`), `NOTCH_UNITS: int = 3`.
  - `scroll_units(system: str, delta: int, num: int | None) -> int` — `wheel_units` × `NOTCH_UNITS`, außer macOS-Rohwerten.
  - `scroll_target(item_top: int, item_height: int, first: float, last: float, total: int) -> float | None` — neue `yview_moveto`-Position, damit das Feld sichtbar ist; `None`, wenn es schon sichtbar ist.

- [ ] **Step 1: Vorher-Screenshots** (Beleg für die PR, Spec „Tests" PR 3). `SCRATCH/shots.py` anlegen:

```python
"""Screenshots aller Einstellungs-Tabs (#132, PR 3). Nicht einchecken.

Aufruf aus dem Repo-Root:
  ZEITERFASSUNG_DATA_DIR=SCRATCH/data PYTHONPATH=. .venv/bin/python SCRATCH/shots.py <prefix> <scale>
"""
import os
import subprocess
import sys
import tkinter as tk
from tkinter import ttk

import src.dialogs.settings_dialog.dialog as dlg
from src.paths import get_base_path
from src.settings import Settings
from src.theme import init_fonts

prefix, scale = sys.argv[1], float(sys.argv[2])
out = os.path.dirname(os.path.abspath(__file__))
base = get_base_path()
assert os.environ.get("ZEITERFASSUNG_DATA_DIR") == base, "nur mit Scratch-Daten"


class Runner:            # kein Netz: Hintergrundaufgaben laufen nie zu Ende
    def run(self, fn, on_done=None):
        pass


class AutoUpdater:
    def maybe_start(self, *a, **k):
        return "disabled"


root = tk.Tk()
init_fonts(root, scale)
root.geometry("900x700+50+50")
settings = Settings(os.path.join(base, "settings.json"))
dlg.open_settings_dialog(root, settings, base, lambda: None,
                         runner=Runner(), auto_updater=AutoUpdater())
root.update()
dialog = [w for w in root.winfo_children() if isinstance(w, tk.Toplevel)][0]
notebook = next(w for w in dialog.winfo_children() if isinstance(w, ttk.Notebook))
for index in range(notebook.index("end")):
    notebook.select(index)
    for _ in range(5):
        root.update()
    name = notebook.tab(index, "text").replace(" ", "").replace("&", "")
    path = f"{out}/{prefix}-{round(scale * 100)}-{index}-{name}.png"
    subprocess.run(["import", "-window", dialog.wm_frame(), path], check=False)
    print(path, dialog.winfo_width(), "x", dialog.winfo_height())
root.destroy()
```

Laufen lassen (auf dem unveränderten Stand):

```bash
rm -rf SCRATCH/data && mkdir -p SCRATCH/data
for s in 1.0 1.5; do ZEITERFASSUNG_DATA_DIR=SCRATCH/data PYTHONPATH=. .venv/bin/python SCRATCH/shots.py vorher $s; done
```

Expected: 14 PNGs `vorher-100-*.png`/`vorher-150-*.png`, Dialoggrößen notiert (Referenz für Task 10).

- [ ] **Step 2: Failing tests** — ans Ende von `tests/test_form_logic.py` (Importzeile oben um die neuen Namen ergänzen: `NOTCH_UNITS, scroll_target, scroll_units`):

```python
def test_wheel_route_idle_self_scroller_goes_to_form():
    # Ein Textfeld ohne Überlauf fängt das Rad sonst still ab — mitten im
    # Formular stünde die Seite dann (Vorlagen-Felder im Versand-Tab).
    assert wheel_route("Text", can_scroll=False) == "form"
    assert wheel_route("Listbox", can_scroll=False) == "form"
    assert wheel_route("Text", can_scroll=True) == "widget"
    # Für alle anderen Klassen spielt can_scroll keine Rolle.
    assert wheel_route("TCombobox", can_scroll=False) == "form_block"
    assert wheel_route("Frame", can_scroll=False) == "form"


def test_scroll_units_notch_platforms_multiply():
    assert scroll_units("Windows", 120, None) == -NOTCH_UNITS
    assert scroll_units("Windows", -240, None) == 2 * NOTCH_UNITS
    assert scroll_units("Linux", 0, 5) == NOTCH_UNITS
    assert scroll_units("Linux", 0, 4) == -NOTCH_UNITS


def test_scroll_units_macos_keeps_raw_trackpad_values():
    # Trackpads liefern viele kleine Deltas — multipliziert spränge die Seite.
    assert scroll_units("Darwin", 2, None) == -2
    assert scroll_units("Darwin", 0, None) == 0


def test_scroll_target_visible_item_stays():
    # Sichtbar: 0–300 von 1000 px.
    assert scroll_target(100, 30, 0.0, 0.3, 1000) is None
    assert scroll_target(270, 30, 0.0, 0.3, 1000) is None


def test_scroll_target_item_above_aligns_top():
    assert scroll_target(100, 30, 0.5, 0.8, 1000) == 0.1


def test_scroll_target_item_below_aligns_bottom():
    # Unterkante 630 soll am Sichtrand liegen: erster sichtbarer Pixel 330.
    assert scroll_target(600, 30, 0.0, 0.3, 1000) == 0.33


def test_scroll_target_item_taller_than_view_aligns_top():
    assert scroll_target(400, 500, 0.0, 0.3, 1000) == 0.4


def test_scroll_target_degenerate_total():
    assert scroll_target(0, 10, 0.0, 1.0, 0) is None
```

- [ ] **Step 3: Run** `.venv/bin/python -m pytest tests/test_form_logic.py -q` → FAIL (ImportError `scroll_target`).

- [ ] **Step 4: Implementation** in `src/theme/form_logic.py`. Konstanten unter `MIN_BODY_HEIGHT`:

```python
# Scroll-Schrittweite eines Formulars bei 100 % (`yscrollincrement`, px,
# mitskaliert). Ohne feste Schrittweite rechnet der Canvas in Zehnteln der
# sichtbaren Höhe — auf einem macOS-Trackpad, das viele kleine Deltas
# schickt, sprang die Seite dadurch.
WHEEL_STEP = 20
# Schritte je Raste eines klassischen Mausrads (Windows, X11): drei mal
# `WHEEL_STEP` fühlt sich an wie in anderen Anwendungen.
NOTCH_UNITS = 3
```

`wheel_route` ersetzen:

```python
def wheel_route(widget_class: str, can_scroll: bool = True) -> WheelRoute:
    """Wohin ein Mausrad-Schritt über einem Widget dieser Klasse geht:
    `"widget"` — das Widget scrollt selbst, das Formular bleibt stehen;
    `"form_block"` — das Formular scrollt, das Widget darf den Schritt NICHT
    sehen; `"form"` — das Formular scrollt.

    `can_scroll=False` meldet ein Text/eine Listbox ohne Überlauf: das Rad
    ginge dort ins Leere, das Formular stünde still. Dann scrollt es."""
    if widget_class in _SELF_SCROLLING:
        return "widget" if can_scroll else "form"
    if widget_class in _VALUE_ON_WHEEL:
        return "form_block"
    return "form"
```

Nach `wheel_units`:

```python
def scroll_units(system: str, delta: int, num: int | None) -> int:
    """`yview_scroll`-Einheiten (à `WHEEL_STEP`) aus einem Mausrad-Event.

    Eine Raste (Windows, X11) zählt `NOTCH_UNITS` Einheiten. macOS liefert
    Rohwerte, die schon fein genug sind — die bleiben, wie `wheel_units` sie
    liest."""
    units = wheel_units(system, delta, num)
    if system == "Darwin" and num is None:
        return units
    return units * NOTCH_UNITS


def scroll_target(item_top: int, item_height: int, first: float, last: float,
                  total: int) -> float | None:
    """Wohin gescrollt werden muss, damit ein Feld sichtbar ist.

    `item_top`/`item_height` in px relativ zum Formularkörper, `first`/`last`
    der sichtbare Bereich als Anteil (`canvas.yview()`), `total` die volle
    Körperhöhe. Liefert den neuen `yview_moveto`-Wert oder `None`, wenn das
    Feld schon ganz sichtbar ist. Liegt es darüber (oder ist es höher als der
    Sichtbereich), kommt seine Oberkante an den oberen Rand, sonst seine
    Unterkante an den unteren."""
    if total <= 0:
        return None
    view_top = first * total
    view_height = (last - first) * total
    item_bottom = item_top + item_height
    if item_top >= view_top and item_bottom <= view_top + view_height:
        return None
    if item_top < view_top or item_height >= view_height:
        return max(0.0, item_top / total)
    return round(max(0.0, (item_bottom - view_height) / total), 6)
```

(`round(…, 6)` gegen Fließkomma-Reste wie `0.33000000000000007`; der Oberkanten-Zweig ist ein exakter Quotient.)

- [ ] **Step 5: Run** `.venv/bin/python -m pytest tests/test_form_logic.py -q` → PASS; dann komplett pytest/ruff/pyright.

- [ ] **Step 6: Commit** — „feat(theme): Rad-Routing, Schrittweite und Fokus-Ziel für Formulare (#132)"

---

### Task 2: `Form` — Zeilen-Handle, inverse Abhängigkeit, Fokus, Rad, Schrittweite; `date_row` ohne Beschriftung

**Files:**
- Modify: `src/theme/form.py`, `src/dialogs/date_row.py`
- Create (nicht im Repo): `SCRATCH/form_demo.py`

**Interfaces:**
- Consumes: Task 1.
- Produces:
  - `class FormRow` mit `label: tk.Label`, `widget`, `show(visible: bool) -> None` (per `grid()`/`grid_remove()`, behält die Grid-Optionen).
  - `Form.row(label, widget, *, align_top=False) -> FormRow` (**Rückgabe ändert sich** von `tk.Label` auf `FormRow`; bisher hat `row()` keinen Aufrufer).
  - `Form.depends_on(var, *, invert=False, indent=True)` — `invert=True`: aktiv, solange `var` **aus** ist; `indent=False`: keine zusätzliche Einrückung.
  - `build_date_row(parent, label_text: str | None, …)` — `None` baut keine Beschriftung.

Kein Unit-Test (Tk); die Entscheidungen sind in Task 1 getestet, das Verhalten prüft Step 5.

- [ ] **Step 1: `FormRow` und `row()`** — in `form.py` vor `class Form`:

```python
class FormRow:
    """Handle einer `Form.row`: Beschriftung und Bedienelement, gemeinsam
    ein- und ausblendbar — für Zeilen, die ein Schalter im selben Tab
    sichtbar macht (Sa/So bei „Nur Werktage")."""

    def __init__(self, label, widget):
        self.label = label
        self.widget = widget

    def show(self, visible):
        # grid_remove statt grid_forget: die Grid-Optionen (Zeile, Einzug)
        # bleiben gemerkt, ein nacktes grid() stellt die Zeile wieder her.
        for w in (self.label, self.widget):
            if visible:
                w.grid()
            else:
                w.grid_remove()
```

`Form.row` ersetzen:

```python
    def row(self, label, widget, *, align_top=False):
        """Beschriftung in Spalte 0, `widget` (Parent `form.body`) in Spalte 1.
        `align_top` hält die Beschriftung oben (mehrzeilige Textfelder)."""
        r = self._next_row()
        lbl = tk.Label(self.body, text=label, font=FONT, bg=BG, fg=TEXT)
        lbl.grid(row=r, column=0, sticky="nw" if align_top else "w",
                 padx=(self._indent(), 8), pady=4)
        widget.grid(row=r, column=1, sticky="w", padx=(0, _EDGE), pady=4)
        self._register(lbl, widget)
        return FormRow(lbl, widget)
```

Docstring-Beispiel der Klasse bleibt gültig (Rückgabe wird dort nicht benutzt).

- [ ] **Step 2: `depends_on(invert, indent)`** — in `__init__` neben `self._vars`: `self._invert: dict[str, bool] = {}` und `self._indents: dict[str, bool] = {}`. `depends_on`:

```python
    @contextmanager
    def depends_on(self, var, *, invert=False, indent=True):
        """Alles, was im `with`-Block entsteht, ist nur aktiv, solange `var`
        wahr ist (und alle Schalter darüber). `invert=True` dreht das um:
        aktiv, solange `var` AUS ist („Wochenende anzeigen" gegen „Nur
        Werktage"). `indent=False` rückt nicht ein — für eine Option, die
        neben ihrem Gegenspieler steht statt unter einem Hauptschalter.
        Die Variable hält `Form` fest — sie braucht eine lebende Referenz,
        sonst löscht der GC die Tcl-Variable (s. src/CLAUDE.md, Dialoge).
        …(Besitz-Vertrag wie bisher, unverändert)…"""
        group = f"g{len(self._parents)}"
        self._parents[group] = self._stack[-1] if self._stack else None
        self._vars[group] = var
        self._invert[group] = invert
        self._indents[group] = indent
        self._members[group] = []
        self._stack.append(group)
        try:
            yield
        finally:
            self._stack.pop()
        var.trace_add("write", lambda *_: self.refresh_enabled())
        self.refresh_enabled()
```

In `refresh_enabled` die Zuweisung `values[group] = bool(var.get())` ersetzen durch `values[group] = bool(var.get()) != self._invert[group]` (der `TclError`-Zweig bleibt `False`, auch bei `invert`: ein unlesbarer Schalter macht seine Gruppe im Zweifel grau). `_indent`:

```python
    def _indent(self):
        levels = sum(1 for group in self._stack if self._indents[group])
        return _EDGE + px(INDENT) * levels
```

- [ ] **Step 3: Schrittweite, ruhende Scroller, Fokus** — Importe: `from src.theme.form_logic import (WHEEL_STEP, body_height, enabled_states, is_descendant, scroll_target, scroll_units, wheel_route)` (`wheel_units` wird in `form.py` nicht mehr gebraucht). Im `scroll`-Zweig von `__init__`:
  - nach dem Anlegen des Canvas: `self._canvas.configure(yscrollincrement=px(WHEEL_STEP))`
  - in der Schleife über `_wheel_sequences(top)` bleibt alles; danach zusätzlich:

```python
            # Tab-Taste auf ein Feld außerhalb des Sichtbereichs: dorthin
            # scrollen, sonst tippt man blind (<FocusIn> des Toplevels sieht
            # die Fokuswechsel aller Kinder).
            top.bind("<FocusIn>", self._on_focus, add="+")
```

`_scroll`:

```python
    def _scroll(self, event):
        if self._canvas is None or not self._scrollable:
            return
        num = event.num if event.num in (4, 5) else None
        units = scroll_units(platform.system(),
                             int(getattr(event, "delta", 0) or 0), num)
        if units:
            self._canvas.yview_scroll(units, "units")
```

`_on_wheel` — im `try` nach `cls = widget.winfo_class()`:

```python
            # Ein Text/eine Listbox ohne Überlauf gibt das Rad ans Formular
            # ab (form_logic.wheel_route) — sonst stünde die Seite über den
            # Vorlagen-Feldern still.
            can_scroll = True
            if wheel_route(cls) == "widget":
                can_scroll = tuple(widget.yview()) != (0.0, 1.0)
```

und die Bedingung danach: `if inside and wheel_route(cls, can_scroll) == "form":`.

Neue Methode:

```python
    def _on_focus(self, event):
        canvas = self._canvas
        widget = event.widget
        if canvas is None or not self._scrollable or isinstance(widget, str):
            return
        try:
            if not is_descendant(str(widget), str(self.body)):
                return
            top = widget.winfo_rooty() - self.body.winfo_rooty()
            height = widget.winfo_height()
            total = self.body.winfo_reqheight()
            first, last = canvas.yview()
        except tk.TclError:
            log.debug("Fokus: Widget nicht mehr abfragbar", exc_info=True)
            return
        target = scroll_target(top, height, first, last, total)
        if target is not None:
            canvas.yview_moveto(target)
```

- [ ] **Step 4: `date_row`** — Signatur `label_text: str | None`; Label nur bauen, wenn nicht `None`:

```python
    frame = tk.Frame(parent, bg=BG)
    # None: die Beschriftung trägt der Aufrufer selbst (Form.row im
    # Einstellungs-Dialog) — sonst stünde sie doppelt da.
    if label_text is not None:
        tk.Label(frame, text=label_text, font=FONT, bg=BG, fg=TEXT,
                 width=label_width, anchor="w").pack(side=tk.LEFT, padx=(0, 5))
```

Docstring: „- label_text: Beschriftung links in der Zeile; `None` = keine."

- [ ] **Step 5: Demo prüfen** — `SCRATCH/form_demo.py`:

```python
import tkinter as tk
from src.theme import Form, apply_combobox_style, dark_combo, dark_entry, dark_text, init_fonts

root = tk.Tk(); init_fonts(root, 1.0); apply_combobox_style(root)
form = Form(root, scroll=True); form.frame.pack(fill="both", expand=True)
off = tk.BooleanVar(value=False); master = tk.BooleanVar(value=True)
form.section("A")
c0 = form.check("Gegenspieler", off)
with form.depends_on(off, invert=True, indent=False):
    inv = form.check("aktiv, solange Gegenspieler aus", tk.BooleanVar())
form.check("Hauptschalter", master)
with form.depends_on(master):
    r = form.row("Eintrag:", dark_entry(form.body, tk.StringVar(value="x")))
text = dark_text(form.body, 30, 3); form.row("Text:", text, align_top=True)
combo_var = tk.StringVar(value="1")
form.row("Combo:", dark_combo(form.body, combo_var, ["1", "2", "3"]))
last = dark_entry(form.body, tk.StringVar())
for i in range(40):
    form.row(f"Zeile {i}:", dark_entry(form.body, tk.StringVar()))
form.row("Letzte:", last)
root.update()
assert str(inv.cget("state")) == "normal"
off.set(True); root.update(); assert str(inv.cget("state")) == "disabled"
# indent=False: gleicher Einzug wie der Gegenspieler; normale Gruppe: tiefer.
assert inv.grid_info()["padx"] == c0.grid_info()["padx"]
assert r.label.grid_info()["padx"] != c0.grid_info()["padx"]
r.show(False); root.update(); assert not r.label.winfo_ismapped()
r.show(True); root.update(); assert r.label.winfo_ismapped()
canvas = form._canvas
assert float(canvas.cget("yscrollincrement")) > 0
before = canvas.yview()[0]
text.event_generate("<Button-5>" if root.tk.call("tk", "windowingsystem") == "x11" else "<MouseWheel>", delta=-120)
root.update(); assert canvas.yview()[0] > before, "leeres Textfeld muss das Rad abgeben"
last.focus_set(); root.update(); root.update()
top, bottom = canvas.yview(); assert bottom > 0.95, (top, bottom)
print("OK")
root.destroy()
```

Lauf: `PYTHONPATH=. .venv/bin/python SCRATCH/form_demo.py` → `OK`. Hinweis: `event_generate("<Button-5>")` auf dem Textfeld läuft durch dessen Bindtags bis zum Toplevel — genau der Weg eines echten Rad-Ereignisses unter X11.

- [ ] **Step 6: Grün** — pytest/ruff/pyright.

- [ ] **Step 7: Commit** — „feat(theme): Form — Zeilen-Handle, inverse Abhängigkeit, Fokus und Rad (#132)"

---

### Task 3: Tab „Erinnerungen" (aus dem App-Tab)

**Files:**
- Modify: `src/dialogs/settings_dialog/tab_rules.py`, `tab_app.py`, `dialog.py`
- Create: `src/dialogs/settings_dialog/tab_reminders.py`
- Test: `tests/test_tab_rules.py`

**Interfaces:**
- Consumes: `Form`, `FormRow`, `depends_on` (Task 2), `FieldSet`, `SaveOutcome`.
- Produces:
  - `tab_rules.REMINDER_KEYS: tuple[str, ...]`, `validate_reminders(raw) -> tuple[str, str] | None`, `reminders_updates(raw) -> dict[str, Any]`, `shift_moves(label: str) -> bool`.
  - `validate_app` **entfällt**; `app_updates` schreibt die Erinnerungs-Schlüssel nicht mehr.
  - `RemindersTab(frame, settings)` — `SettingsTab` (`title="Erinnerungen"`, `fields`, `values/load/validate/save`).

- [ ] **Step 1: Failing tests** — in `tests/test_tab_rules.py`:
  - `app_raw` aufteilen: die Schlüssel `reminders_enabled`, `reminder_minutes_before`, `send_reminder_*` (7 Stück) wandern in eine neue Fabrik:

```python
def reminders_raw(**overrides):
    raw = {
        "reminders_enabled": True, "reminder_minutes_before": "15",
        "send_reminder_enabled": True, "send_reminder_day": "28",
        "send_reminder_time": "09:00",
        "send_reminder_weekend_shift": SHIFT_LABELS["backward"],
        "send_reminder_shift_holidays": False,
        "send_reminder_reservations_enabled": True,
        "send_reminder_default_minutes": "30",
    }
    raw.update(overrides)
    return raw
```

  - `test_validate_app` → umbenennen in `test_validate_reminders`, Aufrufe `tr.validate_reminders(reminders_raw(reminder_minutes_before=bad))`, erster Assert `tr.validate_reminders(reminders_raw()) is None`.
  - Aus `test_app_updates_converts` die Asserts zu `reminder_minutes_before`, `send_reminder_day`, `send_reminder_weekend_shift`, `send_reminder_default_minutes` in einen neuen Test verschieben:

```python
def test_reminders_updates_converts():
    upd = tr.reminders_updates(reminders_raw())
    assert set(upd) == set(tr.REMINDER_KEYS)
    assert upd["reminder_minutes_before"] == 15
    assert upd["send_reminder_day"] == 28
    assert upd["send_reminder_weekend_shift"] == "backward"
    assert upd["send_reminder_default_minutes"] == 30


def test_reminders_updates_keeps_values_of_disabled_options():
    # Ausgegraut heißt nicht gelöscht: schaltet man die Erinnerung ab, bleiben
    # Minuten und Tag gespeichert und sind beim Wiedereinschalten da.
    upd = tr.reminders_updates(reminders_raw(
        reminders_enabled=False, send_reminder_enabled=False))
    assert upd["reminders_enabled"] is False
    assert upd["reminder_minutes_before"] == 15
    assert upd["send_reminder_day"] == 28


def test_shift_moves():
    assert tr.shift_moves(SHIFT_LABELS["none"]) is False
    assert tr.shift_moves(SHIFT_LABELS["backward"]) is True
    assert tr.shift_moves(SHIFT_LABELS["forward"]) is True
```

  - `test_tabs_together_write_exactly_the_legacy_keys`: in `written` nach dem `work_updates`-Eintrag `tr.reminders_updates(reminders_raw()),` ergänzen.

- [ ] **Step 2: Run** `.venv/bin/python -m pytest tests/test_tab_rules.py -q` → FAIL (`reminders_updates` fehlt).

- [ ] **Step 3: `tab_rules.py`** — Abschnitt `# ---- App ----` so umbauen (`validate_app` löschen, `app_updates` ohne die Erinnerungs-Schlüssel), davor neu:

```python
# ---- Erinnerungen --------------------------------------------------------

REMINDER_KEYS = (
    "reminders_enabled", "reminder_minutes_before",
    "send_reminder_enabled", "send_reminder_day", "send_reminder_time",
    "send_reminder_weekend_shift", "send_reminder_shift_holidays",
    "send_reminder_reservations_enabled", "send_reminder_default_minutes",
)


def shift_moves(label: str) -> bool:
    """Verschiebt die gewählte Wochenend-Regel den Termin überhaupt? Nur
    dann hat „auch Feiertage" eine Wirkung (und ist bedienbar)."""
    return shift_for_label(label) != "none"


def validate_reminders(raw: Mapping[str, Any]) -> tuple[str, str] | None:
    if parse_reminder_minutes(raw["reminder_minutes_before"]) is None:
        return ("Erinnerungszeit ungültig",
                "Bitte eine ganze Zahl zwischen 0 und 120 Minuten angeben.")
    return None


def reminders_updates(raw: Mapping[str, Any]) -> dict[str, Any]:
    """Settings-Werte des Erinnerungen-Tabs. Setzt `validate_reminders`
    voraus. Ausgegraute Optionen werden mitgeschrieben — ihr Wert bleibt
    erhalten, bis der Schalter wieder an ist."""
    minutes = parse_reminder_minutes(raw["reminder_minutes_before"])
    if minutes is None:
        raise ValueError("reminders_updates ohne vorheriges validate_reminders")
    return {
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
    }
```

`app_updates` danach:

```python
def app_updates(raw: Mapping[str, Any]) -> dict[str, Any]:
    """Settings-Werte des App-Tabs."""
    return {
        "autostart": bool(raw["autostart"]),
        "state": code_for_state_label(raw["state"]),
        "show_weekend": bool(raw["show_weekend"]),
        "always_on_top": bool(raw["always_on_top"]),
        "minimize_to_tray": bool(raw["minimize_to_tray"]),
        "ui_scale": clamp_ui_scale(slider_percent(float(raw["ui_scale"])) / 100),
        "send_period_from_last_reminder": bool(
            raw["send_period_from_last_reminder"]),
        "send_period_anchor_monthly": bool(raw["send_period_anchor_monthly"]),
    }
```

- [ ] **Step 4: Run** tests → PASS.

- [ ] **Step 5: `tab_reminders.py`** anlegen:

```python
"""Tab „Erinnerungen" (#132): Reservierungs-Erinnerung, monatliche
Sende-Erinnerung und die Sende-Erinnerung an Reservierungstagen.

Stand bis PR 3 im App-Tab, dort ohne Überschriften — zwei fast gleich
benannte Minuten-Einstellungen nebeneinander. Jede hat jetzt ihren Abschnitt.
"""

import tkinter as tk

from src.dialogs.settings_dialog.fields import FieldSet
from src.dialogs.settings_dialog.form_model import SaveOutcome
from src.dialogs.settings_dialog.tab_rules import (
    reminders_updates, shift_moves, validate_reminders,
)
from src.send_reminder import SHIFT_LABELS, label_for_shift
from src.theme import TIME_VALUES, Form, dark_combo

_MINUTES = [str(m) for m in range(0, 121, 5)]


class RemindersTab:
    """Baut den Erinnerungen-Tab; Tab-Schnittstelle für den
    `SaveCoordinator`."""

    def __init__(self, frame, settings):
        self.frame = frame
        self.title = "Erinnerungen"
        self._settings = settings

        form = Form(frame, scroll=True)
        form.frame.pack(fill="both", expand=True)
        body = form.body

        # --- Reservierungs-Erinnerung (Toast, gerätelokal) ---
        reminders_var = tk.BooleanVar(value=settings.get("reminders_enabled"))
        minutes_var = tk.StringVar(value=str(settings.get("reminder_minutes_before")))
        form.section("Reservierungen")
        form.check("Erinnerungen als Toast anzeigen", reminders_var)
        with form.depends_on(reminders_var):
            form.row("Minuten vor Ende:",
                     dark_combo(body, minutes_var, _MINUTES, width=4))
            form.hint("Nur für Reservierungen mit Kategorie, an denen noch "
                      "keine Ist-Zeit erfasst ist.")

        # --- Monatliche Sende-Erinnerung ---
        send_var = tk.BooleanVar(value=settings.get("send_reminder_enabled"))
        day_var = tk.StringVar(value=str(settings.get("send_reminder_day")))
        time_var = tk.StringVar(value=settings.get("send_reminder_time"))
        shift_var = tk.StringVar(
            value=label_for_shift(settings.get("send_reminder_weekend_shift")))
        holidays_var = tk.BooleanVar(
            value=settings.get("send_reminder_shift_holidays"))
        # Abgeleitet, kein Formularfeld: „auch Feiertage" hat nur Wirkung,
        # wenn überhaupt verschoben wird. Form hält die Variable fest.
        shift_active = tk.BooleanVar(value=shift_moves(shift_var.get()))
        shift_var.trace_add(
            "write", lambda *_: shift_active.set(shift_moves(shift_var.get())))

        form.section("Monatliche Sende-Erinnerung")
        form.check("Erinnerung zum Verschicken der Arbeitszeiten", send_var)
        with form.depends_on(send_var):
            form.row("Tag im Monat:", dark_combo(
                body, day_var, [str(d) for d in range(1, 32)], width=4))
            form.hint("Bei kürzeren Monaten wird auf den letzten Tag verschoben.")
            form.row("Uhrzeit:", dark_combo(body, time_var, TIME_VALUES, width=6))
            form.row("Fällt er aufs Wochenende:", dark_combo(
                body, shift_var,
                [SHIFT_LABELS[m] for m in ("none", "backward", "forward")],
                width=18))
            with form.depends_on(shift_active):
                form.check("auch Feiertage", holidays_var)

        # --- Sende-Erinnerung an Reservierungstagen ---
        res_var = tk.BooleanVar(
            value=settings.get("send_reminder_reservations_enabled"))
        default_minutes_var = tk.StringVar(
            value=str(settings.get("send_reminder_default_minutes")))
        form.section("An Reservierungstagen")
        form.check("Sende-Erinnerung am Ende einer markierten Reservierung",
                   res_var)
        with form.depends_on(res_var):
            form.row("Standard (Minuten vor Ende):", dark_combo(
                body, default_minutes_var, _MINUTES, width=4))
            # Ohne Kalender-Abgleich zeigt die App gar keine Reservierungen
            # (App._reservations_active) — der Schalter bliebe sonst
            # wirkungslos, ohne dass man sieht warum.
            hint = "Welche Tage erinnern, legst du im Tages-Dialog fest."
            if not settings.get("gcal_enabled"):
                hint += " Braucht den Kalender-Abgleich (Tab Google)."
            form.hint(hint)

        fields = FieldSet()
        fields.add("reminders_enabled", reminders_var)
        fields.add("reminder_minutes_before", minutes_var)
        fields.add("send_reminder_enabled", send_var)
        fields.add("send_reminder_day", day_var)
        fields.add("send_reminder_time", time_var)
        fields.add("send_reminder_weekend_shift", shift_var)
        fields.add("send_reminder_shift_holidays", holidays_var)
        fields.add("send_reminder_reservations_enabled", res_var)
        fields.add("send_reminder_default_minutes", default_minutes_var)
        self.fields = fields

    def values(self):
        return self.fields.values()

    def load(self, values):
        self.fields.load(values)

    def validate(self):
        return validate_reminders(self.values())

    def save(self):
        self._settings.apply_updates(reminders_updates(self.values()))
        return SaveOutcome(saved=True)
```

- [ ] **Step 6: `tab_app.py` ausdünnen** — den ganzen Block `# --- Benachrichtigungen …` bis einschließlich der beiden `send_reminder_*`-Zeilen (`res_hint`-Label) löschen, **aber** den `period_row` (`send_period_from_last_var`/`send_period_anchor_monthly_var`) stehen lassen (wandert in Task 4). Aus den Attributzuweisungen und `fields.add(...)` die neun Erinnerungs-Schlüssel entfernen. `validate()` → `return None`; Import `validate_app` entfernen, `label_for_shift`/`SHIFT_LABELS`/`TIME_VALUES`-Importe entfernen, falls ungenutzt (ruff meldet sie). Modul-Docstring: „Tab „App": Bundesland, UI-Optionen, Skalierung, Zeitraum-Vorbelegung."

- [ ] **Step 7: `dialog.py`** — Import `from src.dialogs.settings_dialog.tab_reminders import RemindersTab`. Nach `tab_work = …` ein `tab_reminders = tk.Frame(notebook, bg=BG)`, nach `notebook.add(tab_work, …)` `notebook.add(tab_reminders, text="Erinnerungen")`. Nach dem Bau von `work`: `reminders = RemindersTab(tab_reminders, settings)`. Im `tabs`-Dict nach `"work": work,` die Zeile `"reminders": reminders,` (Reihenfolge = Reiterreihenfolge; die `assert` in `dialog.py` fängt einen Fehler hier).

- [ ] **Step 8: Prüfen** — pytest/ruff/pyright grün. `ZEITERFASSUNG_DATA_DIR=SCRATCH/data PYTHONPATH=. .venv/bin/python SCRATCH/shots.py t3 1.0` → der neue Reiter „Erinnerungen" hat drei Abschnitte; Screenshot ansehen (`Read`): Unteroptionen eingerückt, bei ausgeschaltetem Schalter grau.

- [ ] **Step 9: Commit** — „feat(einstellungen): Tab „Erinnerungen" aus dem App-Tab (#132)"

---

### Task 4: Tab „Versand" — Mail, Zeitraum-Vorbelegung, SMTP- und Webhook-Liste

**Files:**
- Create: `src/dialogs/settings_dialog/tab_sending.py`
- Delete: `src/dialogs/settings_dialog/tab_mail.py`
- Modify: `tab_rules.py`, `_record_list_tab.py`, `tab_smtp.py`, `tab_webhooks.py`, `tab_app.py`, `dialog.py`
- Test: `tests/test_tab_rules.py`, `tests/test_record_list_tabs.py`

**Interfaces:**
- Consumes: `Form`, `empty_state`, Task 3.
- Produces:
  - `tab_rules.SENDING_KEYS` (= `MAIL_KEYS` + die zwei `send_period_*`), `sending_updates(raw) -> dict[str, Any]`; `mail_updates` **entfällt**; `app_updates` ohne `send_period_*`.
  - `RecordListKind` + `section: str`, `empty: str`; `intro` bleibt (wird zum Abschnitts-Hinweis).
  - `RecordListTab(form, dialog, store, runner, parent=None)` — baut Abschnitt + Liste in ein fremdes `Form`; **keine** `SettingsTab`-Schnittstelle mehr (`title`/`fields`/`values`/… entfallen, der Versand-Tab trägt sie). Datei- und Klassennamen (`SmtpTab`, `WebhooksTab`) bleiben: die Charakterisierungstests aus R12 hängen daran.
  - `SendingTab(frame, dialog, settings, webhook_store, smtp_store, runner, parent)` — `SettingsTab`, `title="Versand"`.

- [ ] **Step 1: Failing tests** — `tests/test_tab_rules.py`:
  - `test_mail_updates_passes_text_through` ersetzen durch:

```python
def sending_raw(**overrides):
    raw = {k: f"<{k}>" for k in tr.MAIL_KEYS}
    raw.update({"send_period_from_last_reminder": True,
                "send_period_anchor_monthly": False})
    raw.update(overrides)
    return raw


def test_sending_updates():
    upd = tr.sending_updates(sending_raw())
    assert set(upd) == set(tr.SENDING_KEYS)
    assert upd["mail_subject"] == "<mail_subject>"
    assert upd["send_period_from_last_reminder"] is True
    assert upd["send_period_anchor_monthly"] is False
```

  - `app_raw`: die beiden `send_period_*`-Schlüssel entfernen.
  - Legacy-Test: `tr.mail_updates({k: "" for k in tr.MAIL_KEYS}),` ersetzen durch `tr.sending_updates(sending_raw()),`.

  `tests/test_record_list_tabs.py`: in `_tab` nach `tab._listbox = MagicMock()` die Zeile `tab._empty = MagicMock()` ergänzen, und neu:

```python
@pytest.mark.parametrize("cls", [SmtpTab, WebhooksTab])
def test_empty_list_shows_the_empty_text(cls):
    tab = _tab(cls, [])

    tab.refresh()

    tab._empty.grid.assert_called_once_with()
    tab._empty.grid_remove.assert_not_called()


def test_filled_list_hides_the_empty_text():
    tab = _tab(SmtpTab, _SMTP)

    tab.refresh()

    tab._empty.grid_remove.assert_called_once_with()
    tab._empty.grid.assert_not_called()
```

- [ ] **Step 2: Run** `.venv/bin/python -m pytest tests/test_tab_rules.py tests/test_record_list_tabs.py -q` → FAIL.

- [ ] **Step 3: `tab_rules.py`** — Abschnitt `# ---- Bericht & Mail ----` ersetzen:

```python
# ---- Versand -------------------------------------------------------------

MAIL_KEYS = ("recipient", "name", "mail_subject", "mail_greeting",
             "mail_content", "mail_closing")
SENDING_KEYS = MAIL_KEYS + ("send_period_from_last_reminder",
                            "send_period_anchor_monthly")


def sending_updates(raw: Mapping[str, Any]) -> dict[str, Any]:
    updates: dict[str, Any] = {key: raw[key] for key in MAIL_KEYS}
    updates["send_period_from_last_reminder"] = bool(
        raw["send_period_from_last_reminder"])
    updates["send_period_anchor_monthly"] = bool(raw["send_period_anchor_monthly"])
    return updates
```

In `app_updates` die zwei `send_period_*`-Einträge löschen.

- [ ] **Step 4: `_record_list_tab.py`** — Modul-Docstring: „Gemeinsamer Aufbau der Listen „SMTP-Konten" und „Webhooks" im Versand-Tab (R12, Xveyn#123; seit #132 Abschnitte statt eigener Tabs) … Die Einträge speichern ihre Unterdialoge selbst — für den `SaveCoordinator` tragen die Listen keine Formularfelder." `RecordListKind` um zwei Felder ergänzen (nach `intro`):

```python
    section: str                                # Abschnitts-Überschrift
    empty: str                                  # Leertext der leeren Liste
```

Importe: `FieldSet`/`SaveOutcome` raus; aus `src.theme` zusätzlich `empty_state`, `px` wird nicht mehr gebraucht. `RecordListTab` ersetzen bis vor `refresh` (die Methoden `refresh` … `_remove` bleiben, `refresh` bekommt den Leertext):

```python
class RecordListTab:
    """Eine Liste über einem gerätelokalen Store, als Abschnitt in einem
    fremden `Form` (Versand-Tab); Unterklassen setzen `KIND`."""

    KIND: RecordListKind

    def __init__(self, form, dialog, store, runner, parent=None):
        self._dialog = dialog
        # Fallback-Ziel für Fehlermeldungen, falls der Einstellungen-Dialog
        # inzwischen geschlossen wurde (analog send_dialog.on_done).
        self._parent = parent if parent is not None else dialog
        self._store = store
        self._runner = runner

        form.section(self.KIND.section, hint=self.KIND.intro)
        box = tk.Frame(form.body, bg=BG)
        box.columnconfigure(0, weight=1)

        # Dieselbe Palette wie die Listbox im ConflictsDialog — zwei
        # Listboxen mit unterschiedlichem Styling wären ein
        # dialogspezifisches Stil-Extra. Drei Zeilen: im Versand-Tab stehen
        # zwei Listen unter der Mail-Vorlage, mehr Konten sind selten, und
        # die Listbox scrollt selbst, sobald es mehr werden.
        self._listbox = tk.Listbox(
            box, height=3, width=30, font=FONT,
            bg=ENTRY_BG, fg=TEXT, selectbackground=ACCENT,
            selectforeground="#ffffff", relief="flat",
            highlightthickness=0, activestyle="none",
        )
        self._listbox.grid(row=0, column=0, sticky="nsew")
        self._listbox.bind("<Double-Button-1>", lambda _e: self._edit())
        # Liegt in derselben Zelle über der Liste; `refresh` blendet ihn
        # aus, sobald es Einträge gibt.
        self._empty = empty_state(box, self.KIND.empty, bg=ENTRY_BG)
        self._empty.grid(row=0, column=0, sticky="nsew")

        btns = tk.Frame(box, bg=BG)
        btns.grid(row=0, column=1, sticky="n", padx=(8, 0))
        primary_button(btns, "Hinzufügen", self._add).pack(fill="x")
        secondary_button(btns, "Bearbeiten", self._edit).pack(fill="x", pady=(4, 0))
        secondary_button(btns, "Entfernen", self._remove).pack(fill="x", pady=(4, 0))
        form.block(box)

        self._records = []
        self.refresh()

    def refresh(self):
        self._records = self._store.get_all() if self._store else []
        self._listbox.delete(0, tk.END)
        for record in self._records:
            self._listbox.insert(
                tk.END, row_text(record, self.KIND.row_detail(record)))
        if self._records:
            self._empty.grid_remove()
        else:
            self._empty.grid()
```

(`values`/`load`/`validate`/`save`/`fields` und `title: str` löschen.)

- [ ] **Step 5: Kinds** — `tab_smtp.py`: `title = "SMTP"` löschen; in `SMTP_KIND` nach `intro=` ergänzen `section="SMTP-Konten",` und `empty="Noch kein Konto — „Hinzufügen“ legt eins an.",`; den Intro-Text kürzen auf:

```python
    intro=("Statt über die Gmail-API über einen eigenen Mail-Server senden. "
           "Jedes Konto hat seinen eigenen Empfänger und lässt sich beim "
           "Senden einzeln wählen. Gilt nur auf diesem Gerät und wird sofort "
           "gespeichert, unabhängig vom Knopf „Speichern“."),
```

  `tab_webhooks.py`: `title = "Webhooks"` löschen; `section="Webhooks",`, `empty="Noch kein Webhook — „Hinzufügen“ legt einen an.",`; Intro:

```python
    intro=("Den Bericht zusätzlich an HTTP-Endpunkte senden. Gilt nur auf "
           "diesem Gerät und wird sofort gespeichert, unabhängig vom Knopf "
           "„Speichern“."),
```

  Modul-Docstrings beider Dateien: „Tab …" → „Liste „SMTP-Konten" bzw. „Webhooks" im Versand-Tab".

- [ ] **Step 6: `tab_sending.py`** anlegen (`tab_mail.py` per `git rm` löschen; dessen Modul-Docstring-Absatz zum Stundenlohn fällt weg — der steht am Feld im Arbeitszeit-Tab):

```python
"""Tab „Versand" (#132): alles, was einen Bericht verschickt — Absender und
Empfänger, Mail-Vorlage, die Zeitraum-Vorbelegung des Sende-Dialogs und die
Kanäle SMTP und Webhooks.

Bis PR 3 verteilt auf „Bericht & Mail", „SMTP", „Webhooks" und den App-Tab.
Der Gmail-Absender bleibt im Google-Tab: er hängt an der Google-Anmeldung.
"""

import tkinter as tk

from src.dialogs.settings_dialog.fields import FieldSet
from src.dialogs.settings_dialog.form_model import SaveOutcome
from src.dialogs.settings_dialog.tab_rules import sending_updates
from src.dialogs.settings_dialog.tab_smtp import SmtpTab
from src.dialogs.settings_dialog.tab_webhooks import WebhooksTab
from src.theme import Form, dark_entry, dark_text


class SendingTab:
    """Baut den Versand-Tab; Tab-Schnittstelle für den `SaveCoordinator`.
    Die beiden Listen speichern selbst (eigener Klick, eigenes Speichern)
    und tragen nichts zu `values()` bei."""

    def __init__(self, frame, dialog, settings, webhook_store, smtp_store,
                 runner, parent):
        self.frame = frame
        self.title = "Versand"
        self._settings = settings

        form = Form(frame, scroll=True)
        form.frame.pack(fill="both", expand=True)
        body = form.body

        name_var = tk.StringVar(value=settings.get("name"))
        recipient_var = tk.StringVar(value=settings.get("recipient"))
        form.section("Absender & Empfänger")
        form.row("Dein Name:", dark_entry(body, name_var, width=35))
        form.row("Empfänger:", dark_entry(body, recipient_var, width=35))

        subject_var = tk.StringVar(value=settings.get("mail_subject"))
        greeting_var = tk.StringVar(value=settings.get("mail_greeting"))
        form.section("Mail-Vorlage")
        form.row("Betreff:", dark_entry(body, subject_var, width=35))
        form.row("Anrede:", dark_entry(body, greeting_var, width=35))
        content_text = dark_text(body, 35, 3)
        content_text.insert("1.0", settings.get("mail_content"))
        form.row("Inhalt:", content_text, align_top=True)
        closing_text = dark_text(body, 35, 2)
        closing_text.insert("1.0", settings.get("mail_closing"))
        form.row("Gruß:", closing_text, align_top=True)
        form.hint("Platzhalter in Betreff und Inhalt: {zeitraum}, {gesamt}")

        from_last_var = tk.BooleanVar(
            value=settings.get("send_period_from_last_reminder"))
        anchor_var = tk.BooleanVar(value=settings.get("send_period_anchor_monthly"))
        form.section("Zeitraum im Sende-Dialog")
        form.check("Zeitraum ab der letzten Erinnerung vorbelegen", from_last_var)
        with form.depends_on(from_last_var):
            form.check("inkl. Monatstermine der Sende-Erinnerung", anchor_var)

        self.smtp = SmtpTab(form, dialog, smtp_store, runner, parent)
        self.webhooks = WebhooksTab(form, dialog, webhook_store, runner, parent)

        # Für das Smoke-Skript (liest Felder direkt).
        self.content_text = content_text
        self.name_var = name_var

        fields = FieldSet()
        fields.add("recipient", recipient_var)
        fields.add("name", name_var)
        fields.add("mail_subject", subject_var)
        fields.add("mail_greeting", greeting_var)
        # Nach dem Einfügen des Anfangstexts — add_text setzt das
        # Modified-Flag zurück, das das Einfügen gesetzt hat.
        fields.add_text("mail_content", content_text)
        fields.add_text("mail_closing", closing_text)
        fields.add("send_period_from_last_reminder", from_last_var)
        fields.add("send_period_anchor_monthly", anchor_var)
        self.fields = fields

    def values(self):
        return self.fields.values()

    def load(self, values):
        self.fields.load(values)

    def validate(self):
        return None

    def save(self):
        self._settings.apply_updates(sending_updates(self.values()))
        return SaveOutcome(saved=True)
```

- [ ] **Step 7: `tab_app.py`** — `period_row` samt der beiden Variablen, Attribute und `fields.add(...)` löschen. Modul-Docstring: „Tab „App": Bundesland, UI-Optionen, Skalierung."

- [ ] **Step 8: `dialog.py`** — die sechs Tabs stehen damit fest; den Teil von `notebook = …` bis `updates_tab = UpdatesTab(…)` ersetzen durch:

```python
    notebook = ttk.Notebook(dialog, style="Dark.TNotebook")
    notebook.pack(fill="both", expand=True, padx=8, pady=(8, 0))

    frames = {key: tk.Frame(notebook, bg=BG) for key in
              ("work", "reminders", "sending", "google", "app", "updates")}

    work = WorkTab(frames["work"], dialog, settings, vacation_store,
                   on_vacation_change, storage, reservation_store, runner,
                   on_vacation_display_change)
    reminders = RemindersTab(frames["reminders"], settings)
    sending = SendingTab(frames["sending"], dialog, settings, webhook_store,
                         smtp_store, runner, parent)
    google = GoogleTab(
        frames["google"], dialog, settings, base_path, on_change, runner,
        storage, conflicts_store, reservation_store, data_lock, sync_guard)
    app = AppTab(frames["app"], settings, dialog, parent, base_path)
    updates_tab = UpdatesTab(frames["updates"], settings, runner, auto_updater)
```

und das `tabs`-Dict:

```python
    # Reihenfolge = Reiterreihenfolge: der Reiter-Klick unten rechnet über
    # den Index auf den Schlüssel um.
    tabs = {
        "work": work,
        "reminders": reminders,
        "sending": sending,
        "google": google,
        "app": app,
        "updates": updates_tab,
    }
    for tab in tabs.values():
        notebook.add(tab.frame, text=tab.title)
    keys = list(tabs)
```

(`notebook.add` wandert damit hinter den Bau der Tabs — die Reitertexte kommen aus `tab.title`, eine zweite Liste mit Namen gibt es nicht mehr. Die `assert len(keys) == notebook.index("end")` entfällt: sie prüfte genau die Doppelung, die es jetzt nicht mehr gibt.) `_on_tab_changed` und die Bindung `<<NotebookTabChanged>>` bleiben unverändert und stehen weiter **vor** dem initialen `notebook.select(...)` (Banner-Weg). Events, die schon beim `notebook.add` feuern, sind harmlos: `_refresh_save_button` prüft `coordinator is None`. Importe: `MailTab`/`SmtpTab`/`WebhooksTab` raus, `SendingTab` rein. Docstring von `open_settings_dialog`: „aufgeteilt auf sechs Tabs (Arbeitszeit / Erinnerungen / Versand / Google / App / Updates)".

- [ ] **Step 9: Prüfen** — pytest/ruff/pyright grün. `SCRATCH/shots.py t4 1.0` → Versand-Tab: vier Abschnitte + zwei Listen mit Leertext (Scratch-Daten haben keine Konten), Knöpfe rechts neben der Liste.

- [ ] **Step 10: Commit** — „feat(einstellungen): Tab „Versand" mit Mail-Vorlage, SMTP und Webhooks (#132)"

---

### Task 5: Tab „Arbeitszeit" mit `Form` — Arbeitswoche, Sa/So sofort, Werkstudenten-Limit grau

**Files:**
- Modify: `src/dialogs/settings_dialog/tab_work.py`, `tab_rules.py`, `tab_app.py`
- Test: `tests/test_tab_rules.py`

**Interfaces:**
- Consumes: `FormRow.show`, `depends_on(invert, indent)` (Task 2), `build_date_row(…, None, …)`.
- Produces: `work_updates` schreibt zusätzlich `state` und `show_weekend`; `app_updates` nicht mehr. `WorkTab` behält Signatur und Attribute (`start_vars`, `end_vars`, `wsl_start_vars`, `wsl_end_vars`, `workweek_only_var`, `rate_var`, …) — das Smoke-Skript liest sie; neu `show_weekend_var`, `state_var`.

- [ ] **Step 1: Failing tests** — `work_raw` um `"state": STATES[1][1], "show_weekend": True,` ergänzen; `app_raw` um diese zwei Schlüssel kürzen. Neu:

```python
def test_work_updates_carries_state_and_weekend():
    upd = tr.work_updates(work_raw(), OLD_WSL)
    assert upd["state"] == STATES[1][0]
    assert upd["show_weekend"] is True
```

In `test_app_updates_converts` den Assert auf `state` löschen. Run → FAIL.

- [ ] **Step 2: `tab_rules.py`** — in `work_updates` ins `updates`-Dict:

```python
        "state": code_for_state_label(raw["state"]),
        "show_weekend": bool(raw["show_weekend"]),
```

und aus `app_updates` die beiden Einträge löschen (bleiben: `autostart`, `always_on_top`, `minimize_to_tray`, `ui_scale`). Run → PASS.

- [ ] **Step 3: `tab_app.py`** — Bundesland-Zeile (`label(... "Bundesland:")`, `state_var`, `dark_combo`) und den `show_weekend`-Block samt „Durch „Nur Werktage" überstimmt"-Hinweis löschen; Attribute und `fields.add` der beiden Schlüssel entfernen; `STATES`-Import entfernen, falls ungenutzt. Das `app_frame` hängt dann an `row=0` statt `row=1`.

- [ ] **Step 4: `tab_work.py` neu aufbauen** — `__init__` bis vor `self.title = "Arbeitszeit"` ersetzen. Importe: `_shared` raus; `from src.holidays_de import STATES`; aus `src.theme`: `BG, FONT, PAUSE_VALUES, TEXT_MUTED, TIME_VALUES, Form, dark_combo, dark_entry, themed_showwarning` (`CELL_BG`, `FONT_SMALL`, `TEXT`, `secondary_button` raus, sofern ungenutzt). Code:

```python
        self.frame = frame
        form = Form(frame, scroll=True)
        form.frame.pack(fill="both", expand=True)
        body = form.body

        # --- Arbeitswoche ---
        workweek_only_var = tk.BooleanVar(value=settings.get("workweek_only"))
        show_weekend_var = tk.BooleanVar(value=settings.get("show_weekend"))
        state_labels = [lbl for _, lbl in STATES]
        current_state = settings.get("state")
        state_var = tk.StringVar(value=next(
            (lbl for code, lbl in STATES if code == current_state), STATES[0][1]))
        form.section("Arbeitswoche")
        form.check("Nur Werktage — Wochenende (Sa/So) komplett ausblenden",
                   workweek_only_var)
        # Stand bis PR 3 im App-Tab, mit einem Hinweis, der hierher verwies.
        # Neben „Nur Werktage" braucht es keinen: grau, solange der an ist.
        with form.depends_on(workweek_only_var, invert=True, indent=False):
            form.check("Wochenende (Sa/So) im Kalender anzeigen", show_weekend_var)
        form.row("Bundesland:", dark_combo(body, state_var, state_labels, width=22))
        form.hint("Für Feiertage und Urlaub.")

        # --- Standardzeiten ---
        form.section("Standardzeiten")
        start_vars = {}
        end_vars = {}
        day_rows = {}
        # Die StringVars entstehen für ALLE sieben Tage, auch für die
        # ausgeblendeten: `save` schreibt unverändert alle Wochentage zurück,
        # damit die Werte für Sa/So erhalten bleiben und sofort wieder da
        # sind, wenn "Nur Werktage" zurückgenommen wird.
        for key, lbl in zip(WEEKDAY_KEYS, DAYS_DE, strict=True):
            start_vars[key] = tk.StringVar(value=settings.get(f"default_start_{key}"))
            end_vars[key] = tk.StringVar(value=settings.get(f"default_end_{key}"))
            cell = tk.Frame(body, bg=BG)
            dark_combo(cell, start_vars[key], TIME_VALUES).pack(side=tk.LEFT)
            tk.Label(cell, text="–", font=FONT, bg=BG, fg=TEXT_MUTED).pack(
                side=tk.LEFT, padx=6)
            dark_combo(cell, end_vars[key], TIME_VALUES).pack(side=tk.LEFT)
            day_rows[key] = form.row(f"{lbl}:", cell)

        def _apply_workweek(*_args):
            # Sofort statt erst beim nächsten Öffnen (#132) — auch beim
            # Verwerfen, das die Variable über FieldSet.load zurücksetzt.
            visible = not workweek_only_var.get()
            for key in ("sat", "sun"):
                day_rows[key].show(visible)

        workweek_only_var.trace_add("write", _apply_workweek)
        _apply_workweek()

        pause_var = tk.StringVar(value=str(settings.get("default_pause")))
        form.row("Standard-Pause (Min):", dark_combo(body, pause_var, PAUSE_VALUES))
        pause_warning_var = tk.BooleanVar(value=settings.get("pause_warning_enabled"))
        form.check("Warnen, wenn die Pausenpflicht (§4 ArbZG) unterschritten wird",
                   pause_warning_var)

        # --- Vergütung ---
        # Der Stundenlohn stand früher im Bericht-&-Mail-Tab. Er beschreibt
        # aber die Arbeit, nicht den Bericht: gelesen wird er ausschließlich
        # vom Kalender-Footer (`grid_renderer`).
        rate_var = tk.StringVar(value=str(settings.get("hourly_rate") or ""))
        form.section("Vergütung")
        form.row("Stundenlohn (€):", dark_entry(body, rate_var, width=10))
        form.hint("Optional – nur für dich sichtbar, als Betrag neben der "
                  "Stundensumme im Kalender.")

        # --- Werkstudenten-Limit ---
        wsl_enabled_var = tk.BooleanVar(value=settings.get("werkstudent_limit_enabled"))
        wsl_hours_var = tk.StringVar(value=str(settings.get("werkstudent_limit_max_hours")))
        wsl_start_default = (
            datetime.date.fromisoformat(settings.get("werkstudent_limit_start"))
            if settings.get("werkstudent_limit_start") else datetime.date.today())
        wsl_end_default = (
            datetime.date.fromisoformat(settings.get("werkstudent_limit_end"))
            if settings.get("werkstudent_limit_end") else datetime.date.today())
        form.section("Werkstudenten-Limit")
        form.check("Wochenstunden-Limit aktivieren", wsl_enabled_var)
        with form.depends_on(wsl_enabled_var):
            # Gemeinsames Datums-Zeilen-Widget (Audit M14), ohne eigene
            # Beschriftung — die trägt die Formularspalte. Werkstudenten-
            # Limit erlaubt Zeiträume etwas weiter in die Zukunft.
            wsl_start_row = build_date_row(body, None, wsl_start_default,
                                           year_to_offset=3)
            form.row("Zeitraum von:", wsl_start_row.frame)
            wsl_end_row = build_date_row(body, None, wsl_end_default,
                                         year_to_offset=3)
            form.row("bis:", wsl_end_row.frame)
            form.row("Limit (Stunden/Woche):", dark_entry(body, wsl_hours_var, width=6))
        wsl_start_vars = wsl_start_row.vars
        wsl_end_vars = wsl_end_row.vars

        # --- Verwalten ---
        form.section("Verwalten")
        specs = [("Kategorien…", lambda: open_category_dialog(dialog, settings))]
        if vacation_store is not None:
            # storage/reservation_store nur für die Kollisionsprüfung beim
            # Speichern: Urlaub und Arbeitszeit schließen sich am selben Tag
            # aus. runner: der Kalender-Schalter im Dialog räumt beim
            # Abschalten über runner.purge_vacations auf (Audit H5).
            specs.append(("Urlaub…", lambda: open_vacation_dialog(
                dialog, vacation_store, settings, on_vacation_change,
                storage, reservation_store, runner,
                on_display_change=on_vacation_display_change)))
        form.buttons(*specs)

        self.start_vars = start_vars
        self.end_vars = end_vars
        self.pause_var = pause_var
        self.pause_warning_var = pause_warning_var
        self.rate_var = rate_var
        self.wsl_enabled_var = wsl_enabled_var
        self.wsl_start_vars = wsl_start_vars
        self.wsl_end_vars = wsl_end_vars
        self.wsl_hours_var = wsl_hours_var
        self.workweek_only_var = workweek_only_var
        self.show_weekend_var = show_weekend_var
        self.state_var = state_var
```

`FieldSet`: nach `fields.add("workweek_only", …)` zusätzlich `fields.add("show_weekend", show_weekend_var)` und `fields.add("state", state_var)`. `self.frame = frame` steht jetzt oben (die alte Zuweisung weiter unten entfernen). Modul-Docstring: „Tab „Arbeitszeit": Arbeitswoche, Standardzeiten, Vergütung, Werkstudenten-Limit, Kategorien und Urlaub."

- [ ] **Step 5: Prüfen** — pytest/ruff/pyright grün. `SCRATCH/shots.py t5 1.0`, dazu kurz von Hand (`ZEITERFASSUNG_DATA_DIR=SCRATCH/data .venv/bin/python -m src.main`, Zahnrad): „Nur Werktage" an → Sa/So verschwinden sofort, „Wochenende anzeigen" wird grau; Limit aus → Zeitraum/Limit grau.

- [ ] **Step 6: Commit** — „feat(einstellungen): Arbeitszeit-Tab mit Arbeitswoche, Sa/So sofort ausgeblendet (#132)"

---

### Task 6: Tab „App" mit `Form` — Fenster, Darstellung, Daten (Import lässt den Dialog offen)

**Files:**
- Modify: `src/dialogs/settings_dialog/tab_app.py`, `tab_google.py`, `dialog.py`, `tests/test_import_apply_order.py` (nur Docstring)

**Interfaces:**
- Produces: `AppTab(frame, settings, dialog, parent, base_path, *, storage=None, reservation_store=None, on_change=None)`. `GoogleTab._open_data_folder`/`_open_import_dialog` wandern nach `AppTab` (gleiche Namen).

- [ ] **Step 1: `tab_app.py` neu aufbauen** — `__init__` bis vor `self.title = "App"` ersetzen. Importe: `logging`, `traceback`, `from tkinter import messagebox, ttk`, `from src.platform_open import open_folder`; `_shared` raus; aus `src.theme`: `ACCENT, BG, CELL_BG, FONT, TEXT_MUTED, Form, px, scaled_window_fits, themed_askyesno, themed_showerror, workarea_for`.

```python
    def __init__(self, frame, settings, dialog, parent, base_path, *,
                 storage=None, reservation_store=None, on_change=None):
        self.frame = frame
        self._storage = storage
        self._reservation_store = reservation_store
        self._on_change = on_change
        form = Form(frame, scroll=True)
        form.frame.pack(fill="both", expand=True)
        body = form.body

        autostart_var = tk.BooleanVar(value=is_autostart_enabled())
        always_on_top_var = tk.BooleanVar(value=settings.get("always_on_top"))
        minimize_to_tray_var = tk.BooleanVar(value=settings.get("minimize_to_tray"))
        form.section("Fenster")
        form.check("Autostart (minimiert bei Anmeldung)", autostart_var)
        form.check("Immer im Vordergrund", always_on_top_var)
        form.check("Beim Schließen in den Infobereich minimieren", minimize_to_tray_var)

        # --- Darstellung (UI-Skalierung, gerätelokal) ---
        form.section("Darstellung")
        scale_cell = tk.Frame(body, bg=BG)
        # ttk.Scale statt klassischer tk.Scale: das clam-Theme ist via
        # apply_combobox_style aktiv, klassische tk.Scale rendert unter
        # Windows einen hellen System-Trough/-Regler. Wert in eigenem Label
        # (kein showvalue-Kasten); auf 5er-Schritte gerastert (ttk.Scale
        # kennt kein resolution). Akzent analog dark_entry: Ruhe TEXT_MUTED,
        # Press ACCENT.
        scale_style = ttk.Style(frame)
        …(die beiden scale_style.configure/map-Aufrufe unverändert übernehmen)…
        scale_var = tk.DoubleVar(value=round(settings.get("ui_scale") * 100))
        scale_value_label = tk.Label(
            scale_cell, text=f"{slider_percent(scale_var.get())} %", font=FONT,
            bg=BG, fg=TEXT_MUTED, width=5, anchor="w",
        )

        # Als Trace statt als `command`: `command` feuert nur bei einer
        # Bewegung des Nutzers, die Beschriftung muss aber auch beim
        # Verwerfen (`load`) mitziehen.
        def _on_scale(*_args):
            scale_value_label.config(text=f"{slider_percent(scale_var.get())} %")

        scale_var.trace_add("write", _on_scale)
        scale_widget = ttk.Scale(
            scale_cell, from_=75, to=200, orient="horizontal",
            variable=scale_var, length=px(200),
            style="Display.Horizontal.TScale",
        )
        …(die beiden <ButtonPress-1>/<ButtonRelease-1>-Bindings unverändert)…
        scale_widget.pack(side=tk.LEFT)
        scale_value_label.pack(side=tk.LEFT, padx=(8, 0))
        form.row("Skalierung:", scale_cell)
        form.hint("Änderung startet die App neu.")

        # --- Daten ---
        form.section("Daten")
        specs = [("Datenordner öffnen", self._open_data_folder)]
        if storage is not None:
            specs.append(("Daten importieren…", self._open_import_dialog))
        form.buttons(*specs)
        form.hint("Im Datenordner liegen Einträge, Einstellungen und "
                  "credentials.json. Importiert werden geteilte Arbeitszeiten "
                  "(JSON-Datei aus „Teilen“).")

        self.autostart_var = autostart_var
        self.always_on_top_var = always_on_top_var
        self.minimize_to_tray_var = minimize_to_tray_var
        self.scale_var = scale_var
```

Nach `self._base_path = base_path` bleibt alles; `FieldSet` enthält nur noch `autostart`, `always_on_top`, `minimize_to_tray`, `ui_scale` (mit `read=slider_percent`). Neue Methoden (aus `tab_google.py` übernommen, `_after_import` geändert):

```python
    def _open_data_folder(self):
        try:
            open_folder(self._base_path)
        except Exception as e:
            logging.getLogger(__name__).exception(
                "Datenordner konnte nicht geöffnet werden")
            messagebox.showerror(
                "Ordner konnte nicht geöffnet werden",
                f"{type(e).__name__}: {e}\n\n{traceback.format_exc()}",
                parent=self._dialog,
            )

    def _open_import_dialog(self):
        from src.dialogs.import_dialog import open_import_dialog

        # Der Einstellungen-Dialog bleibt nach dem Import offen (#132): er
        # schloss sich früher, und das nahm ungespeicherte Änderungen eines
        # Tabs ohne Rückfrage mit. on_change aktualisiert den Kalender.
        open_import_dialog(
            self._dialog, self._storage, self._settings,
            self._on_change or (lambda: None),
            reservation_store=self._reservation_store,
        )
```

Modul-Docstring: „Tab „App": Fenster, Darstellung (Skalierung) und Daten (Datenordner, Import)."

- [ ] **Step 2: `tab_google.py`** — `_open_data_folder` und `_open_import_dialog` löschen; im Konto-Abschnitt den „Ordner öffnen"-Knopf (die `creds_row` bleibt mit dem Status-Label) und in der Sync-Sektion den „Daten importieren"-Knopf löschen. Importe `open_folder`, `traceback`, `messagebox` nur löschen, wenn ruff sie als ungenutzt meldet (`messagebox` wird für andere Catch-alls weiter gebraucht). Die Zeile „Datenordner:" heißt jetzt „credentials.json:" und der Statustext `✓ vorhanden` / `✗ fehlt (Datenordner: Tab App)` (`_refresh_status`).

- [ ] **Step 3: `dialog.py`** — `app = AppTab(frames["app"], settings, dialog, parent, base_path, storage=storage, reservation_store=reservation_store, on_change=on_change)`.

- [ ] **Step 4: `tests/test_import_apply_order.py`** — Docstring anpassen: „…solange sein Parent (der Settings-Dialog) noch lebt. on_change() kann den Parent zerstören (früher schloss `_after_import` den Settings-Dialog; seit #132 bleibt er offen, die Reihenfolge bleibt trotzdem die sichere) — also muss themed_showinfo VOR on_change() laufen …". Test selbst unverändert.

- [ ] **Step 5: Prüfen** — pytest/ruff/pyright grün (Catch-all-Zahl unverändert: ein Handler zieht nur um). `SCRATCH/shots.py t6 1.0` → App-Tab: drei Abschnitte; Google-Tab ohne Ordner-/Import-Knopf.

- [ ] **Step 6: Commit** — „feat(einstellungen): App-Tab mit Fenster, Darstellung und Daten; Import lässt den Dialog offen (#132)"

---

### Task 7: Tab „Google" mit `Form` — Konto, Synchronisation, Kalender, Erweitert

**Files:**
- Modify: `src/dialogs/settings_dialog/tab_google.py`

**Interfaces:**
- Unverändert: Konstruktor-Signatur, `title`, `fields` (`device_name`, `gcal_calendar`), `on_calendars_loaded`, `cal_map`, `cal_var`, `device_name_var`, alle Worker-Methoden.

- [ ] **Step 1: Aufbau** — in `__init__` vor `self._build_account_section()`:

```python
        self._form = Form(frame, scroll=True)
        self._form.frame.pack(fill="both", expand=True)
```

und die drei Aufrufe ersetzen durch

```python
        self._build_account_section()
        self._build_sync_section()
        self._build_calendar_section()
        self._build_advanced_section()
```

Klassen-Docstring: den Absatz über Row-Nummern ersetzen durch „Die Sektionen bauen in ein gemeinsames `Form` (#132) — Zeilen zählt das Formular, keine Row-Nummern mehr von Hand." Importe: `_shared` raus, `Form` rein.

- [ ] **Step 2: `_build_account_section`** ersetzen:

```python
    def _build_account_section(self):
        form, settings = self._form, self._settings
        body = form.body
        form.section("Konto")

        self._status_label = tk.Label(body, text="", font=FONT_SMALL, bg=BG)
        form.row("credentials.json:", self._status_label)
        self._refresh_status()

        # Absender-Zeile: zeigt die authentifizierte E-Mail-Adresse, die ui.py
        # im Hintergrund über OAuth2-userinfo abruft und in settings cached.
        sender_row = tk.Frame(body, bg=BG)
        self._sender_label = tk.Label(
            sender_row,
            text=settings.get("sender_email") or "(noch nicht ermittelt)",
            font=FONT, bg=BG, fg=TEXT_MUTED,
        )
        self._sender_label.pack(side=tk.LEFT)
        self._sender_btn = secondary_button(
            sender_row,
            "Aktualisieren" if settings.get("sender_email") else "Anmelden",
            self._refresh_sender, padx=12, pady=2,
        )
        self._sender_btn.pack(side=tk.LEFT, padx=(10, 0))
        form.row("Absender:", sender_row)

        scopes_row = tk.Frame(body, bg=BG)
        secondary_button(
            scopes_row, "Anzeigen", self._open_scopes, padx=12, pady=2,
        ).pack(side=tk.LEFT)
        self._scopes_status = tk.Label(scopes_row, text="", font=FONT_SMALL, bg=BG)
        self._scopes_status.pack(side=tk.LEFT, padx=(10, 0))
        form.row("Berechtigungen:", scopes_row)
        self._refresh_scopes_status()

        # Anmeldung: trägt der Token noch? Ergänzt die Zeile darüber, ersetzt
        # sie nicht — die sagt, WELCHE Scopes gewährt sind, diese, OB der
        # Token überhaupt noch trägt (Xveyn#124). „Google neu verbinden"
        # steht direkt daneben: genau diese Zeile sagt, wann er nötig ist.
        token_row = tk.Frame(body, bg=BG)
        self._token_status = tk.Label(
            token_row, text="wird geprüft…", font=FONT_SMALL, bg=BG, fg=TEXT_MUTED)
        self._token_status.pack(side=tk.LEFT)
        secondary_button(
            token_row, "Google neu verbinden", self._reconnect_google,
            padx=12, pady=2,
        ).pack(side=tk.LEFT, padx=(10, 0))
        form.row("Anmeldung:", token_row)
        self._check_token()
```

`_refresh_status`: Texte `"✓ vorhanden"` (STATUS_OK) bzw. `"✗ fehlt (Datenordner: Tab App)"` (ACCENT) — falls in Task 6 schon gesetzt, bleibt es.

- [ ] **Step 3: `_build_sync_section`** ersetzen (keine Rückgabe mehr):

```python
    def _build_sync_section(self):
        form, settings = self._form, self._settings
        body = form.body
        form.section("Synchronisation",
                     hint="Der Schalter wirkt sofort (Anmeldung im Browser).")

        # Nicht in einer depends_on-Gruppe (Besitz-Vertrag): der Schalter
        # wird während des Consent-Flows selbst gesperrt (oauth_task).
        self._var_sync = tk.BooleanVar(value=settings.get("sync_enabled"))
        self._cb_sync = form.check("Mit Google Drive synchronisieren", self._var_sync)
        self._cb_sync.config(command=self._on_sync_toggled)

        # Gerätename: reist über die Sync-Registry mit und macht die
        # Geräte-ID im Konfliktdialog lesbar (s. devices.py). Leer lassen ist
        # erlaubt — dann zeigt der Dialog weiter nur die gekürzte ID.
        self.device_name_var = tk.StringVar(value=settings.get("device_name") or "")
        entry = dark_entry(body, self.device_name_var, width=24)
        …(Kommentar + entry.config(validate=…) unverändert, `frame.register` → `body.register`)…
        form.row("Gerät:", entry)
        …(Tooltip-Kommentar unverändert)…
        form.hint("Wird anderen Geräten bei Sync-Konflikten angezeigt.")

        device_id = settings.get("device_id") or "(noch nicht gesetzt)"
        device_id_short = device_id[:8] + "…" if len(device_id) > 8 else device_id
        form.row("Geräte-ID:", tk.Label(body, text=device_id_short, font=FONT,
                                        bg=BG, fg=TEXT_MUTED))

        # Lokales Datum wie im Header-Status-Label (s. sync_orchestrator.
        # _status_view) — zwei verschiedene Daten für denselben Wert wären
        # schlimmer als ein um Mitternacht schiefes.
        _pulled_on = local_date_of_iso(settings.get("last_pull_at"))
        last = format_date(_pulled_on) if _pulled_on else "noch nie"
        form.row("Letzte Synchronisation:", tk.Label(
            body, text=last, font=FONT, bg=BG, fg=TEXT_MUTED))

        unresolved = 0
        if self._conflicts_store is not None:
            unresolved = self._conflicts_store.count_unresolved()
        if unresolved > 0:
            form.buttons((f"Konflikte ansehen ({unresolved})",
                          self._open_conflicts_dialog))
```

- [ ] **Step 4: `_build_calendar_section`** ersetzen (Parameter `start_row` entfällt):

```python
    def _build_calendar_section(self):
        form, settings = self._form, self._settings
        body = form.body
        form.section("Kalender",
                     hint="Der Schalter wirkt sofort (Anmeldung im Browser).")

        self._var_gcal = tk.BooleanVar(value=settings.get("gcal_enabled"))
        # Kalender-Auswahl: Combobox zeigt Klarnamen, gespeichert wird die ID.
        # cal_map summary->id wird im Hintergrund per API befüllt.
        self.cal_map: dict[str, str] = {}
        self.cal_var = tk.StringVar(value=settings.get("gcal_calendar_id") or "primary")

        # Wie beim Sync: nicht in eine Gruppe, der Consent sperrt ihn selbst.
        self._cb_gcal = form.check(
            "Reservierungen mit Google Kalender abgleichen", self._var_gcal)
        self._cb_gcal.config(command=self._on_gcal_toggled)
        with form.depends_on(self._var_gcal):
            self._cal_combo = dark_combo(body, self.cal_var,
                                         [self.cal_var.get()], width=30)
            form.row("Kalender:", self._cal_combo)
        # Außerhalb der Gruppe: „nicht verfügbar" soll lesbar bleiben.
        self._cal_status = form.hint("")

        if settings.get("gcal_enabled"):
            # Beim Aufbau: nicht-interaktiv. Hier hat niemand geklickt, und
            # ein Consent-Flow riss bisher ungefragt den Browser auf, sobald
            # der Token nicht mehr trug (Xveyn#124).
            self._load_calendars(interactive=False)
```

Prüfen, dass `_cal_combo` nirgends sonst gesperrt/entsperrt wird (`grep -n "_cal_combo" tab_google.py` — erwartet: nur `winfo_exists` und `["values"]`); sonst verletzte das den Besitz-Vertrag.

- [ ] **Step 5: `_build_advanced_section`** neu (die Bedingung und ihr Kommentar kommen aus der alten Sync-Sektion):

```python
    def _build_advanced_section(self):
        # Nicht an sync_enabled hängen, sondern an "hat je gesynct" (Audit N6):
        # wer den Sync abschaltet, behält seine Tombstones (das Remote kennt
        # die gelöschten Tage weiter) — und braucht damit weiterhin einen Weg,
        # sie loszuwerden. …(restlicher Kommentar unverändert)…
        settings = self._settings
        ever_synced = settings.get("sync_enabled") or settings.get("last_pull_at")
        if not (ever_synced and self._storage is not None
                and self._conflicts_store is not None):
            return
        # Abgesetzt ganz unten (#132): die Aktion entfernt Einträge endgültig
        # und stand vorher zwischen alltäglichen Knöpfen.
        self._form.section(
            "Erweitert",
            hint="Entfernt alte gelöschte Einträge endgültig aus dem Sync — "
                 "nur, wenn alle Geräte aktuell sind und kürzlich "
                 "synchronisiert haben.")
        self._form.buttons(("Sync-Daten kompaktieren", self._on_compact_clicked))
```

- [ ] **Step 6: Prüfen** — pytest/ruff/pyright grün; `test_google_tab_task.py` betrifft nur die Tk-freien Kerne. `SCRATCH/shots.py t7 1.0` → Google-Tab: Konto (vier Zeilen, „Google neu verbinden" neben „Anmeldung"), Synchronisation, Kalender (Kalender-Zeile grau bei aus), kein „Erweitert" (Scratch-Daten haben nie gesynct).

- [ ] **Step 7: Commit** — „feat(einstellungen): Google-Tab mit Form, „neu verbinden" an der Anmeldung, Kompaktieren unter Erweitert (#132)"

---

### Task 8: Tab „Updates" mit `Form` — Changelog direkt unter dem Status; `_shared.py` entfällt

**Files:**
- Modify: `src/dialogs/settings_dialog/tab_updates.py`
- Delete: `src/dialogs/settings_dialog/_shared.py`

- [ ] **Step 1: Aufbau** — in `__init__` den Teil ab `frame.columnconfigure(0, weight=1)` bis einschließlich `self._changelog_text.config(state="disabled")` ersetzen; dazwischen stehende Logik (`self._can_self_update = …`, `_download_btn`-Erzeugung, `current_label`-Berechnung) bleibt inhaltlich gleich, nur der Parent wird `body`:

```python
        form = Form(frame, scroll=True)
        form.frame.pack(fill="both", expand=True)
        body = form.body

        form.row("Installierte Version:", tk.Label(
            body, text=installed_release_id(), font=FONT, bg=BG, fg=TEXT))

        self._status_label = tk.Label(
            body, text="", font=FONT, bg=BG, fg=TEXT_MUTED, anchor="w",
            justify="left",
        )
        form.block(self._status_label)

        btn_row = tk.Frame(body, bg=BG)
        self._check_btn = primary_button(btn_row, "Jetzt prüfen", self._check_now)
        self._check_btn.pack(side=tk.LEFT)
        self._can_self_update = supports_self_update(
            platform.system(), getattr(sys, "frozen", False))
        self._download_btn = secondary_button(
            btn_row,
            _LABEL_INSTALL if self._can_self_update else _LABEL_DOWNLOAD,
            self._open_latest_download,
        )
        form.block(btn_row)

        # Direkt unter Status und Knöpfen (#132): bisher trennten drei
        # Optionszeilen den Changelog von dem, wozu er gehört. Label + Text
        # bleiben immer gegridded (nie grid_remove()) — sonst verschwindet
        # ihr Breitenbeitrag kurzzeitig während eines Checks und die
        # Dialogbreite bricht ein.
        self._changelog_label = tk.Label(
            body, text=_LABEL_CHANGELOG, font=FONT, bg=BG, fg=TEXT, anchor="w",
        )
        form.block(self._changelog_label, pady=(12, 4))
        self._changelog_text = dark_text(body, 58, 12)
        form.block(self._changelog_text)
        self._changelog_text.tag_configure("heading", font=FONT_BOLD)
        self._changelog_text.tag_configure("bold", font=FONT_BOLD)
        self._changelog_text.tag_configure("hanging_indent", lmargin1=0, lmargin2=20)
        self._changelog_text.config(state="disabled")

        form.section("Optionen")
        current_frequency = settings.get("update_check_frequency")
        current_label = next(
            (lbl for value, lbl in FREQUENCY_OPTIONS if value == current_frequency),
            FREQUENCY_OPTIONS[0][1],
        )
        self.frequency_var = tk.StringVar(value=current_label)
        form.row("Automatisch prüfen:", dark_combo(
            body, self.frequency_var, [lbl for _, lbl in FREQUENCY_OPTIONS], width=14))

        # Opt-in für Pre-Releases: ohne Häkchen verhält sich der Tab exakt wie
        # bisher (nur echte Releases über /releases/latest).
        self.prerelease_var = tk.BooleanVar(
            value=settings.get("prerelease_updates_enabled"))
        form.check("Auch Vorabversionen (Pre-Releases) anbieten", self.prerelease_var)
        form.hint("Testbuilds vor dem echten Release — können Fehler enthalten.")

        # Nur bauen, wo Selbst-Update überhaupt möglich ist — ein Schalter
        # für ein Feature, das die Plattform nicht hat, ist Rauschen.
        self.auto_update_var = None
        if self._can_self_update:
            self.auto_update_var = tk.BooleanVar(
                value=bool(settings.get("auto_update_enabled")))
            form.check("Updates automatisch installieren", self.auto_update_var)
            form.hint("Lädt im Hintergrund und installiert beim nächsten "
                      "Beenden — nie mitten in der Arbeit.")
```

Die `FieldSet`-Registrierung (`self.title = "Updates"` …) folgt danach unverändert. `grep -n "\.grid(" tab_updates.py` muss danach leer sein; `_download_btn` wird weiter nur per `pack`/`pack_forget` in `btn_row` geschaltet — prüfen, dass die späteren Methoden daran nichts ändern. Importe: `_shared` raus, `Form` rein.

- [ ] **Step 2: `_shared.py` löschen** — `grep -rn "_shared" src tests` muss leer sein; `git rm src/dialogs/settings_dialog/_shared.py`.

- [ ] **Step 3: Prüfen** — pytest (insb. `test_tab_updates_apply.py`, `test_tab_updates_auto_update.py`: bauen den Tab über `__new__`, sollten unberührt sein), ruff, pyright. `SCRATCH/shots.py t8 1.0` → Updates: Version, Status, Knopf, Changelog-Box, darunter „Optionen".

- [ ] **Step 4: Commit** — „feat(einstellungen): Updates-Tab mit Changelog unter dem Status; _shared entfällt (#132)"

---

### Task 9: Doku und Texte, die auf alte Tabs zeigen

**Files:**
- Modify: `src/CLAUDE.md`, `CLAUDE.md`, `README.md`, `src/dialogs/send_dialog.py`, `src/dialogs/settings_dialog/__init__.py`, `src/dialogs/settings_dialog/dialog.py` (Docstring `initial_tab`), `docs/superpowers/specs/2026-09-18-einstellungsdialog-132-design.md`

- [ ] **Step 1: Verweise im Code** — `src/dialogs/send_dialog.py`: „Einstellungen → SMTP" → „Einstellungen → Versand". `dialog.py`-Docstring zu `initial_tab`: „einer der Schlüssel `work`/`reminders`/`sending`/`google`/`app`/`updates`". `grep -rn "Bericht & Mail\|Einstellungen → SMTP\|Tab „SMTP\|Tab „Webhooks" src tests` → leer. **Nicht** ändern: `share_message.py` („Einstellungen → Daten importieren") — die Mail geht an Empfänger mit beliebiger App-Version, der tab-neutrale Text stimmt für alle.

- [ ] **Step 2: `src/CLAUDE.md`** (Abschnitt „Dialoge", `settings_dialog/`-Absatz):
  - die Tab-Liste „`tab_work`/`tab_mail`/`tab_google`/`tab_app`/`tab_updates`/`tab_webhooks`/`tab_smtp`.py" → „`tab_work`/`tab_reminders`/`tab_sending`/`tab_google`/`tab_app`/`tab_updates`.py, alle gebaut mit `theme.Form(scroll=True)`";
  - der Satz zu `tab_webhooks`/`tab_smtp` wird: „SMTP-Konten und Webhooks sind Abschnitte im Versand-Tab (`tab_smtp.SmtpTab`/`tab_webhooks.WebhooksTab` über `_record_list_tab.RecordListTab`, eingebettet in dessen `Form`) und tragen **keine** Formularfelder: die Einträge liegen im jeweils eigenen Store und werden vom `webhook_dialog` bzw. `smtp_dialog` direkt gespeichert. Die Klassennamen tragen noch „Tab" aus R12 — die Charakterisierungstests hängen daran.";
  - „Seit R12 (Xveyn#123) teilen sich die beiden Tabs Aufbau und Ablauf …" → „… die beiden Listen …";
  - beim `scopes_dialog`-Absatz „(der ist mit 480 px schon der größte im Notebook)" → „(der Google-Tab ist schon voll; seit #132 scrollt er zwar, eine Scope-Liste darin wäre trotzdem eine Wand)";
  - neuer Satz nach dem `SaveCoordinator`-Teil: „Tab-Reihenfolge und `initial_tab`-Schlüssel: `work`, `reminders`, `sending`, `google`, `app`, `updates` — die Reitertexte kommen aus `tab.title`."
  - `theme/`-Absatz („Berichte & Plattform/Infra"): bei `form` ergänzen „(`FormRow`-Handle aus `row()`, `depends_on(invert=, indent=)`; Rad-Routing, Schrittweite und Fokus-Ziel Tk-frei in `form_logic`)".

- [ ] **Step 3: Root-`CLAUDE.md`** — „Einstieg: Einstellungen → Arbeitszeit → „Urlaub verwalten"" → „Einstieg: Einstellungen → Arbeitszeit → „Urlaub…"". `.venv/bin/python -m pytest tests/test_claude_md_claims.py -q` → grün.

- [ ] **Step 4: `README.md`** — „Einstellungen → **SMTP** → **Hinzufügen**" → „Einstellungen → **Versand** → **SMTP-Konten** → **Hinzufügen**". Den Screenshot `docs/screenshots/einstellungen-v1.21.0.png` **nicht** anfassen — ein neues Bild gehört zum Release (Hinweis in die PR-Beschreibung).

- [ ] **Step 5: `__init__.py`-Docstring** — „…die Tabs sind eigene Klassen-Module" → „…die sechs Tabs sind eigene Klassen-Module, gebaut mit `theme.Form`".

- [ ] **Step 6: Spec** — unter „PR 3" einen Absatz „**Umgesetzt**" (Plan-Link) mit den Abweichungen: (1) SMTP/Webhooks behalten Datei- und Klassennamen (`SmtpTab`/`WebhooksTab`) wegen der R12-Charakterisierungstests; (2) „Daten importieren" lässt den Dialog offen; (3) Reitertexte kommen aus `tab.title`; (4) die Knöpfe „Kategorien…"/„Urlaub…" statt „… verwalten" (Abschnitt heißt „Verwalten").

- [ ] **Step 7: Grün + Commit** — pytest/ruff/pyright. „docs(#132): sechs Tabs in src/CLAUDE.md, README und Spec"

---

### Task 10: Smoke-Skript, Nachher-Screenshots, Linux-Prüfung (nicht eingecheckt)

**Files:**
- Create: `SCRATCH/smoke_pr3.py` (nicht im Repo)

- [ ] **Step 1: Skript** — Grundgerüst wie `SCRATCH/smoke_pr2.py` aus PR 2 (aufzeichnender `SaveCoordinator` per Monkeypatch, skriptbare `themed_ask_save_changes`, `Runner`/`AutoUpdater`-Attrappen, `click_tab(index)` mit **y=15** — die Reiter beginnen durch das Notebook-Padding erst unterhalb von 5 px). Abläufe:

```python
# 1) Sechs Reiter in der richtigen Reihenfolge
assert [notebook.tab(i, "text") for i in range(notebook.index("end"))] == [
    "Arbeitszeit", "Erinnerungen", "Versand", "Google", "App", "Updates"]

def find(root_widget, pred):
    """Erstes Kind-Widget (rekursiv), für das pred(widget) wahr ist."""
    for c in root_widget.winfo_children():
        try:
            if pred(c):
                return c
        except tk.TclError:
            pass
        found = find(c, pred)
        if found is not None:
            return found
    return None


def by_var(frame, var):
    return find(frame, lambda w: "textvariable" in w.keys()
                and str(w.cget("textvariable")) == str(var))


def by_text(frame, text):
    return find(frame, lambda w: "text" in w.keys() and w.cget("text") == text)


# 2) Nur Werktage: sofort ausgeblendet, Verwerfen blendet wieder ein
work = tabs["work"]
sat_combo = by_var(work.frame, work.start_vars["sat"])
assert sat_combo.winfo_ismapped()
work.workweek_only_var.set(True); root.update()
assert not sat_combo.winfo_ismapped()
answers.append("discard"); click_tab(1)
assert work.workweek_only_var.get() is False
click_tab(0)
assert sat_combo.winfo_ismapped()

# 3) Werkstudenten-Limit aus → Datums-Combobox grau, Wert bleibt
work.wsl_enabled_var.set(False); root.update()
day_combo = by_var(work.frame, work.wsl_start_vars[0])
assert "disabled" in day_combo.state()
assert work.wsl_start_vars[0].get() != ""
answers.append("discard"); click_tab(1); click_tab(0)

# 4) Erinnerungen: Verschiebung „nicht verschieben" → „auch Feiertage" grau
click_tab(1)
rem = tabs["reminders"]
from src.send_reminder import SHIFT_LABELS
vals = rem.values()
vals["send_reminder_enabled"] = True
vals["send_reminder_weekend_shift"] = SHIFT_LABELS["none"]
rem.load(vals); root.update()
holidays_cb = by_text(rem.frame, "auch Feiertage")
assert str(holidays_cb.cget("state")) == "disabled"
vals["send_reminder_weekend_shift"] = SHIFT_LABELS["backward"]
rem.load(vals); root.update()
assert str(holidays_cb.cget("state")) == "normal"
answers.append("discard"); click_tab(2)

# 5) Versand: Rad über dem Inhalt-Textfeld scrollt das Formular
sending = tabs["sending"]
canvas = sending.frame.winfo_children()[0].winfo_children()[0]   # Form.frame → Canvas
assert canvas.yview() != (0.0, 1.0), "Versand-Tab sollte bei 100 % scrollen"
before = canvas.yview()[0]
sending.content_text.event_generate("<Button-5>"); root.update()
assert canvas.yview()[0] > before
# Combobox-Schutz: Rad über der Pause-Combobox im Arbeitszeit-Tab ändert
# den Wert nicht.
pause_combo = by_var(work.frame, work.pause_var)
value = work.pause_var.get()
pause_combo.event_generate("<Button-5>"); root.update()
assert work.pause_var.get() == value

# 6) Import lässt den Dialog offen, Änderung bleibt
click_tab(4)
app = tabs["app"]
app.always_on_top_var.set(not app.always_on_top_var.get()); root.update()
import src.dialogs.import_dialog as imp
imp.open_import_dialog = lambda parent, storage, settings, after, **kw: after()
app._open_import_dialog(); root.update()
assert dialog.winfo_exists() and coord.dirty()
answers.append("discard"); click_tab(0)

# 7) Banner-Weg: initial_tab="updates" → genau ein Live-Check (wie PR 2, Schritt 9)
# 8) Alle Tabs: values() → load() → values() identisch, kein Tab frisch „geändert"
for key, tab in coord._tabs.items():
    assert not coord.dirty(key), key
print("OK", asked)
```

Das Skript ist Werkzeug, kein Test im Repo — es darf pragmatisch sein, aber jeder Schritt hat eine echte Assertion. Schritt 7 übernimmt Schritt 9 aus `smoke_pr2.py` wörtlich (`UpdatesTab._check_now` durch einen Zähler ersetzen, `open_dialog(initial_tab="updates")`, `checks == [1]`).

- [ ] **Step 2: Laufen lassen** — `rm -rf SCRATCH/data && mkdir -p SCRATCH/data && ZEITERFASSUNG_DATA_DIR=SCRATCH/data PYTHONPATH=. .venv/bin/python SCRATCH/smoke_pr3.py` → `OK …`. Fehler, die dabei auffallen, als eigene Fix-Commits im betroffenen Tab.

- [ ] **Step 3: Nachher-Screenshots** — `for s in 1.0 1.5; do … shots.py nachher $s; done`. Jeden ansehen (`Read`) und gegen die Vorher-Bilder prüfen: linksbündige Überschriften mit Linie, gemeinsame Beschriftungsspalte je Tab, Einrückung, Grau, Leertext, keine abgeschnittenen Texte; Dialoghöhe bei 150 % ≤ der Vorher-Höhe (Spec: „der Dialog wird nie höher als heute"); Scrollleiste nur dort, wo nötig.

- [ ] **Step 4: Linux von Hand** — App mit Scratch-Daten starten, je Tab: Mausrad über Feldern, über einer Combobox (Wert bleibt), über den Vorlagen-Textfeldern (Formular scrollt), Tab-Taste durch den Versand-Tab (Fokus scrollt mit). Ergebnis in die PR-Beschreibung.

- [ ] **Step 5: Kein Commit.**

---

## Nach dem Plan

- PR gegen `master`: „feat(einstellungen): Neuschnitt auf sechs Tabs (#132, PR 3/3)", `Closes #132`. Beschreibung: neue Tab-Aufteilung (Tabelle), was Nutzer merken (Sa/So sofort, grau statt bedienbar, Leertexte, „Google neu verbinden" an der Anmeldung, Kompaktieren unter „Erweitert", Import lässt den Dialog offen), Abweichungen von der Spec, Vorher/Nachher-Screenshots (lokal im Scratchpad — `gh` kann keine Bilder hochladen, der Nutzer zieht sie in die Beschreibung), Linux-Prüfung.
- **Vor dem Merge: Pre-Release** (Actions → Release → „Run workflow" mit Häkchen *prerelease*) — Windows-Test durch den Nutzer: Mausrad, ausgegraute ttk-Widgets, Dialoghöhe bei 150 %. macOS bleibt offen.
- Kein `release:*`-Label in diesem PR. Der CHANGELOG-Eintrag kommt mit dem Release-PR, der PR 3 enthält (Spec „Doku"); das README-Bild `einstellungen-v1.21.0.png` dort erneuern.
