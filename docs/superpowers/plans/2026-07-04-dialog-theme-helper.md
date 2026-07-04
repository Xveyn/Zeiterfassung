# Dialog-Theme-Helfer + conflicts_dialog (Audit H3/M13) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `conflicts_dialog` vollständig ans gemeinsame Dark-Dialog-Theme anschließen (H3) und die 12-fach duplizierte Chrome-Boilerplate durch einen `theme.create_dialog(...)`-Helfer ersetzen (M13), der die Konvention strukturell erzwingt.

**Architecture:** Ein schlanker Chrome-Helfer in `theme.py` (title/resizable/grab/focus/bg/titlebar/minmax/icon/Escape); Content-Styles und `center_dialog_on_parent` bleiben Call-Site. Button-Disable folgt dem bestehenden Optik-only-Muster (`set_primary_button_enabled`) via neuem `set_secondary_button_enabled`. Migration strikt verhaltensgleich pro Stelle. Spec: `docs/superpowers/specs/2026-07-04-dialog-theme-helper-design.md`.

**Tech Stack:** Python 3.10+ / Tkinter; Screenshots via Pillow `ImageGrab` (bereits Dependency); keine neuen Dependencies.

## Global Constraints

- **Gate:** Implementierung startet erst, wenn PR #119 UND PR #121 in `master` sind und `master` in diesen Branch gemergt wurde (Task 0). Alle Zeilennummern gelten „Stand nach Master-Merge — vor dem Edit verifizieren".
- **Verhaltensgleichheit pro Migrationsstelle** ist das Review-Kriterium: settings und send:22 haben KEIN Escape-Bind; import:411 bleibt resizable und behält seine ungegatete `transient(parent)`-Zeile; theme-interne Dialoge grabben am ENDE (center → grab_set → wait_window) — nichts davon „reparieren".
- `create_dialog` hat **keinen** transient-Param (transient setzt `center_dialog_on_parent`, gated auf sichtbaren Parent — Tray-Fall).
- Button-Disable ist **Optik-only** (Muster `set_primary_button_enabled`): Callback muss bei disabled selbst No-op sein.
- Keine neuen Farben/Fonts außerhalb der Palette (`BG`, `ENTRY_BG`, `CELL_BG`, `ACCENT`, `TEXT`, `TEXT_MUTED`, `FONT`, `FONT_BOLD`).
- Keine neuen Headless-Tests (Dialog-Chrome ist Tk-gebunden); Verifikation = Gesamtsuite grün + `ruff check .` + Tk-Smoke-Skripte + Screenshots auf der Windows-Dev-Maschine. Smoke-/Screenshot-Skripte leben im Scratchpad, werden NICHT committet.
- Kommentare/Docstrings deutsch, Stil der umliegenden Dateien.
- Shell ist PowerShell 5.1: **kein `&&`** — `;` oder separate Befehle.
- Commit-Messages deutsch mit Conventional-Prefix; jede endet mit `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>` (als zweites `-m`).

---

### Task 0: Gate prüfen, master mergen, Baseline

**Files:** keine Quell-Änderungen (ggf. Merge-Commit).

**Interfaces:**
- Produces: Branch-Stand mit #119 (`_themed_ok_dialog` ohne accent-Param, `WARNING`-Konstante entfernt) und #121 (`conflicts_dialog` mit `data_lock`-Param) — die Basis aller Code-Zitate in Tasks 1–5.

- [ ] **Step 1: Gate prüfen**

Run: `gh pr view 119 --repo margenheld/Zeiterfassung --json state ; gh pr view 121 --repo margenheld/Zeiterfassung --json state`
Expected: beide `"state": "MERGED"`. Wenn nicht: **STOPP** — Task nicht fortsetzen, Controller informieren (BLOCKED).

- [ ] **Step 2: master in den Branch mergen**

```powershell
git checkout master ; git pull ; git checkout fix/dialog-theme-helper ; git merge master
```
Expected: Merge ohne Konflikte (Branch enthält bisher nur Docs).

- [ ] **Step 3: Basis verifizieren**

Run: `python -m pytest -q ; ruff check .`
Expected: 0 failed (≥744 passed), „All checks passed".
Zusätzlich prüfen (Read): `src/theme.py` enthält KEINE `WARNING`-Konstante mehr und `_themed_ok_dialog(parent, title, message)` hat keinen accent-Param (#119 da); `src/dialogs/conflicts_dialog.py::__init__` hat `data_lock=None` (#121 da).

---

### Task 1: `create_dialog` + `set_secondary_button_enabled` in theme.py

**Files:**
- Modify: `src/theme.py` (Helfer nach `set_primary_button_enabled` ~Z. 353-371 bzw. vor `themed_askyesno`)

**Interfaces:**
- Produces: `create_dialog(parent, title, *, resizable=False, modal=True, escape_closes=True) -> tk.Toplevel` und `set_secondary_button_enabled(btn, enabled) -> None`. Tasks 2–4 konsumieren beide.
- Consumes: bestehende `apply_dark_titlebar`, `disable_min_max`, `apply_app_icon`, `BG`, `CELL_BG`, `ENTRY_BG`, `TEXT`, `TEXT_MUTED`.

- [ ] **Step 1: `set_secondary_button_enabled` einfügen (direkt nach `set_primary_button_enabled`)**

```python
def set_secondary_button_enabled(btn, enabled):
    """Pendant zu set_primary_button_enabled für `secondary_button`:
    deaktiviert = gedämpfte Schrift (TEXT_MUTED) + Pfeil-Cursor, kein
    Hover-Wechsel. Mutiert `_colors` (Enter/Leave lesen frisch daraus).
    Wichtig: nur die OPTIK — die `command`/on_click-Bindung bleibt aktiv,
    daher muss der Callback selbst bei disabled ein No-op machen."""
    cursor = "hand2" if enabled else "arrow"
    c = (
        {"bg": CELL_BG, "fg": TEXT,
         "hover_bg": ENTRY_BG, "hover_fg": TEXT}
        if enabled else
        {"bg": CELL_BG, "fg": TEXT_MUTED,
         "hover_bg": CELL_BG, "hover_fg": TEXT_MUTED}
    )
    btn._colors = c
    btn.config(bg=c["bg"], cursor=cursor)
    btn._label.config(bg=c["bg"], fg=c["fg"], cursor=cursor)
```

- [ ] **Step 2: `create_dialog` einfügen (direkt vor `themed_askyesno`)**

```python
def create_dialog(parent, title, *, resizable=False, modal=True,
                  escape_closes=True):
    """Erzeugt einen konventionskonformen Dialog-Toplevel — DER Einstieg
    für neue Dialoge (ersetzt die frühere 8-Zeilen-Chrome-Boilerplate).

    Chrome in fester Reihenfolge: title → resizable(False, False) →
    grab_set → focus_set → configure(bg=BG) → apply_dark_titlebar →
    disable_min_max → apply_app_icon → <Escape>-Bind auf destroy.
    focus_set() MUSS nach grab_set() laufen, sonst feuern Tastatur-
    Bindungen (z.B. Escape) am Dialog nie.

    resizable=True ruft resizable() bewusst NICHT auf (Tk-Default bleibt).
    modal=False lässt grab_set() weg — für Dialoge, die wie die themed_*-
    Familie am Ende selbst center→grab_set→wait_window fahren.
    escape_closes=False lässt den Escape-Bind weg — für Dialoge ohne
    Escape (Settings) oder mit eigener Escape-Semantik (themed_*).

    KEIN transient-Param: transient setzt center_dialog_on_parent —
    bewusst gated auf sichtbaren Parent (Tray-Fall, siehe dort).
    Content-Styles (apply_combobox_style/apply_notebook_style/
    attach_unfocus_on_click) und center_dialog_on_parent (braucht die
    fertige Größe) bleiben beim Aufrufer."""
    dialog = tk.Toplevel(parent)
    dialog.title(title)
    if not resizable:
        dialog.resizable(False, False)
    if modal:
        dialog.grab_set()
    dialog.focus_set()
    dialog.configure(bg=BG)
    apply_dark_titlebar(dialog)
    disable_min_max(dialog)
    apply_app_icon(dialog)
    if escape_closes:
        dialog.bind("<Escape>", lambda _e: dialog.destroy())
    return dialog
```

- [ ] **Step 3: Tk-Smoke-Skript ausführen (Scratchpad, nicht committen)**

Datei `<scratchpad>\smoke_create_dialog.py`:

```python
import sys
sys.path.insert(0, r"D:\Programme (x86)\Zeiterfassung_Repo\Zeiterfassung")
import tkinter as tk
from src.theme import BG, create_dialog

root = tk.Tk()
root.withdraw()

d1 = create_dialog(root, "Smoke-Default", modal=False)
assert d1.title() == "Smoke-Default"
assert d1.cget("bg") == BG
assert "<Escape>" in d1.bind()
d1.destroy()

d2 = create_dialog(root, "Smoke-Var", modal=False, escape_closes=False,
                   resizable=True)
assert "<Escape>" not in d2.bind()
d2.destroy()

root.destroy()
print("SMOKE OK")
```

Run: `python <scratchpad>\smoke_create_dialog.py`
Expected: `SMOKE OK` (kein Traceback).

- [ ] **Step 4: Suite + Lint**

Run: `python -m pytest -q ; ruff check .`
Expected: 0 failed, lint clean.

- [ ] **Step 5: Commit**

```powershell
git add src/theme.py
git commit -m "feat(theme): create_dialog-Chrome-Helfer + set_secondary_button_enabled (Audit M13-Basis)" -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: conflicts_dialog ans Theme (H3)

**Files:**
- Modify: `src/dialogs/conflicts_dialog.py` (Imports, `__init__`, `_build`, `_on_select`, `_resolve_with_candidate`)

**Interfaces:**
- Consumes: `create_dialog`, `set_secondary_button_enabled`, `secondary_button`, `center_dialog_on_parent`, Palette (Task 1 / Bestand).
- Produces: identische öffentliche API (`ConflictsDialog(parent, storage, settings, conflicts_store, data_lock=None)`); `data_lock`-Durchreichung aus #121 unangetastet.

- [ ] **Step 1: Vorher-Screenshot (Scratchpad-Skript, wird in Step 4 wiederverwendet)**

Datei `<scratchpad>\shot_conflicts_dialog.py`:

```python
import json, os, sys, tempfile
sys.path.insert(0, r"D:\Programme (x86)\Zeiterfassung_Repo\Zeiterfassung")
import tkinter as tk
from src.storage import Storage
from src.settings import Settings
from src.conflicts_store import ConflictsStore
from src.dialogs.conflicts_dialog import ConflictsDialog
from src.theme import init_fonts

OUT = sys.argv[1] if len(sys.argv) > 1 else "conflicts_dialog.png"

tmp = tempfile.mkdtemp()
conflict = {
    "id": "c-demo", "kind": "entry", "key": "2026-07-01",
    "candidates": [
        {"slots": [{"start": "08:00", "end": "16:00", "pause": 30, "kategorie": ""}],
         "modified_at": "2026-07-01T10:00:00Z", "device_id": "device-A", "deleted": False},
        {"slots": [{"start": "09:00", "end": "17:30", "pause": 45, "kategorie": "Büro"}],
         "modified_at": "2026-07-01T11:00:00Z", "device_id": "device-B", "deleted": False},
    ],
    "detected_at": "2026-07-01T12:00:00Z",
    "resolved": False, "resolution": None, "resolved_at": None, "resolved_by": None,
}
with open(os.path.join(tmp, "conflicts.json"), "w", encoding="utf-8") as f:
    json.dump([conflict], f)

root = tk.Tk()
root.withdraw()
init_fonts(root, 1.0)
dlg = ConflictsDialog(
    root,
    Storage(os.path.join(tmp, "z.json"), device_id="local"),
    Settings(os.path.join(tmp, "s.json")),
    ConflictsStore(os.path.join(tmp, "conflicts.json")),
)
dlg.top.update_idletasks()
dlg.top.update()

from PIL import ImageGrab
x, y = dlg.top.winfo_rootx(), dlg.top.winfo_rooty()
w, h = dlg.top.winfo_width(), dlg.top.winfo_height()
ImageGrab.grab(bbox=(x - 8, y - 40, x + w + 8, y + h + 8)).save(OUT)
print("SHOT OK:", OUT)
```

Run: `python <scratchpad>\shot_conflicts_dialog.py <scratchpad>\conflicts_vorher.png`
Expected: `SHOT OK` + PNG des heutigen (hellen) Dialogs.

- [ ] **Step 2: Imports + `__init__` umstellen**

Import-Block ersetzen:

```python
import tkinter as tk

from src import sync
from src.theme import (
    ACCENT, BG, ENTRY_BG, FONT, FONT_BOLD, TEXT,
    center_dialog_on_parent, create_dialog, secondary_button,
    set_secondary_button_enabled, themed_showerror,
)
from src.time_utils import format_iso_datetime
```

In `__init__` den Chrome-Block (heute: `self.top = tk.Toplevel(parent)` … `self.top.bind("<Escape>", …)`) ersetzen durch:

```python
        # Chrome komplett über den Konventions-Helfer (Audit H3): bringt
        # NEU dunkle Titelleiste, BG, disable_min_max, resizable(False).
        # transient übernimmt center_dialog_on_parent (gated, Tray-sicher).
        self.top = create_dialog(parent, "Konflikte auflösen")

        self._build()
        self._refresh_list()
        center_dialog_on_parent(self.top, parent)
```

(Der alte `self._build()`/`self._refresh_list()`-Aufruf am Ende von `__init__` entfällt zugunsten dieser Reihenfolge — `center` NACH dem Build, wie überall.)

- [ ] **Step 3: `_build`, `_on_select`, `_resolve_with_candidate` themen**

`_build` komplett ersetzen:

```python
    def _build(self):
        left = tk.Frame(self.top, bg=BG)
        left.pack(side="left", fill="y", padx=8, pady=8)

        tk.Label(left, text="Offene Konflikte", font=FONT_BOLD,
                 bg=BG, fg=TEXT).pack(anchor="w")
        # Einzige Listbox der App: dunkel über die Palette (ENTRY_BG wie
        # Eingabefelder, ACCENT-Selektion), flach ohne Fokusrahmen.
        self.listbox = tk.Listbox(
            left, width=40, height=15, font=FONT,
            bg=ENTRY_BG, fg=TEXT,
            selectbackground=ACCENT, selectforeground="#ffffff",
            relief="flat", highlightthickness=0,
        )
        self.listbox.pack(fill="y", expand=True)
        self.listbox.bind("<<ListboxSelect>>", lambda _e: self._on_select())

        self.right = tk.Frame(self.top, bg=BG)
        self.right.pack(side="right", fill="both", expand=True, padx=8, pady=8)

        self.detail_label = tk.Label(self.right, text="Wähle einen Konflikt links.",
                                      wraplength=400, justify="left",
                                      font=FONT, bg=BG, fg=TEXT)
        self.detail_label.pack(anchor="nw")

        button_row = tk.Frame(self.right, bg=BG)
        button_row.pack(side="bottom", fill="x", pady=(8, 0))
        self.btn_a = secondary_button(
            button_row, "Version A übernehmen",
            lambda: self._resolve_with_candidate(0))
        self.btn_b = secondary_button(
            button_row, "Version B übernehmen",
            lambda: self._resolve_with_candidate(1))
        self.btn_a.pack(side="left", padx=4)
        self.btn_b.pack(side="left", padx=4)
        # Optik-only-Disable (Muster set_primary_button_enabled) — der
        # No-op bei disabled läuft über den _selected-Guard im Callback.
        set_secondary_button_enabled(self.btn_a, False)
        set_secondary_button_enabled(self.btn_b, False)
        secondary_button(button_row, "Schließen",
                         self.top.destroy).pack(side="right")
```

In `_on_select` die zwei `config(state="normal")`-Zeilen ersetzen:

```python
        set_secondary_button_enabled(self.btn_a, True)
        set_secondary_button_enabled(self.btn_b, True)
```

In `_resolve_with_candidate` den Erfolgs-Schluss ersetzen:

```python
        self._refresh_list()
        # Guard-Reset ist PFLICHT: die gedimmten Buttons sind Optik-only —
        # ohne _selected=None würde ein Klick den alten Konflikt erneut
        # auflösen (die frühere state="disabled"-Sperre entfällt).
        self._selected = None
        set_secondary_button_enabled(self.btn_a, False)
        set_secondary_button_enabled(self.btn_b, False)
        self.detail_label.config(text="Konflikt aufgelöst. Wähle den nächsten.")
```

- [ ] **Step 4: Nachher-Screenshot + Funktions-Smoke**

Run: `python <scratchpad>\shot_conflicts_dialog.py <scratchpad>\conflicts_nachher.png`
Expected: `SHOT OK`; PNG zeigt dunklen Dialog (BG-Flächen, dunkle Listbox, gedimmte A/B-Buttons).
Manueller Smoke im selben Skript-Setup optional per App; Pflicht-Check: Konflikt in der Liste anklicken → A/B werden hell; „Version A übernehmen" → Liste leer, Buttons wieder gedimmt, erneuter Klick auf gedimmtes A tut NICHTS (Guard).

- [ ] **Step 5: Suite + Lint + Commit**

Run: `python -m pytest -q ; ruff check .`
Expected: 0 failed (inkl. `tests/test_conflicts_dialog.py`), lint clean.

```powershell
git add src/dialogs/conflicts_dialog.py
git commit -m "fix(theme): conflicts_dialog ans gemeinsame Dialog-Theme (Audit H3)" -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Migration der `dialogs/`-Boilerplate (9 Stellen, M13)

**Files:**
- Modify: `src/dialogs/category_dialog.py:145-155`, `src/dialogs/import_dialog.py:101-112` und `:411-420`, `src/dialogs/share_dialog.py:43-53`, `src/dialogs/export_dialog.py:21-32`, `src/dialogs/settings_dialog.py:47-58`, `src/dialogs/entry_dialog.py:101-114`, `src/dialogs/send_dialog.py:22-30` und `:84-96` (Zeilennummern ≈ Stand master — nach Task 0 pro Stelle verifizieren)

**Interfaces:**
- Consumes: `create_dialog` (Task 1).
- Produces: verhaltensgleiche Dialoge; keine API-Änderung.

**Migrationsregel für jede Stelle:** Der Block von `tk.Toplevel(parent)` bis einschließlich `apply_app_icon(...)` (+ ggf. `resizable`/`grab_set`/`focus_set`/`configure(bg=BG)`/Escape-Bind) wird durch EINEN `create_dialog`-Aufruf ersetzt; alles andere (combobox/notebook/unfocus/center/transient) bleibt als Folgezeile stehen. Danach pro Datei den `from src.theme import …`-Block bereinigen: `create_dialog` ergänzen, jetzt ungenutzte Namen entfernen (`ruff check .` meldet F401 exakt; `BG` bleibt fast überall wegen Content-Frames in Benutzung).

- [ ] **Step 1: `category_dialog.py` (Z. 145-155)**

```python
    dialog = create_dialog(parent, "Kategorien verwalten")
    attach_unfocus_on_click(dialog)
```

- [ ] **Step 2: `import_dialog.py:101-112` (Import-Hauptdialog)**

```python
        self.top = create_dialog(parent, "Daten importieren")
        apply_combobox_style(self.top)
        attach_unfocus_on_click(self.top)
```

- [ ] **Step 3: `import_dialog.py:411-420` (Pro-Tag-Dialog)**

```python
        self.top = create_dialog(parent, f"Pro Tag entscheiden — {type_label}",
                                 resizable=True)
        # Ungegatetes transient wie bisher (Verhaltensgleichheit; das
        # gegatete transient kommt zusätzlich über center_dialog_on_parent).
        self.top.transient(parent)
```

- [ ] **Step 4: `share_dialog.py:43-53`**

```python
    dialog = create_dialog(parent, "Teilen")
    attach_unfocus_on_click(dialog)
```

- [ ] **Step 5: `export_dialog.py:21-32`**

```python
    dialog = create_dialog(parent, "Als PDF exportieren")
    apply_combobox_style(dialog)
    attach_unfocus_on_click(dialog)
```

- [ ] **Step 6: `settings_dialog.py:47-58` (KEIN Escape — heutiges Verhalten!)**

```python
    dialog = create_dialog(parent, "Einstellungen", escape_closes=False)

    apply_combobox_style(dialog)
    apply_notebook_style(dialog)
```

- [ ] **Step 7: `entry_dialog.py:101-114`** (der focus-nach-grab-Kommentar ist in den Helfer-Docstring gewandert und entfällt hier)

```python
    dialog = create_dialog(parent, format_iso_weekday_date(date_str))
    apply_combobox_style(dialog)
    attach_unfocus_on_click(dialog)
```

- [ ] **Step 8: `send_dialog.py:22-30` (KEIN Escape) und `:84-96`**

```python
    dialog = create_dialog(parent, "Keine Zugangsdaten", escape_closes=False)
```

```python
    dialog = create_dialog(parent, "Zeitraum wählen")

    apply_combobox_style(dialog)
    attach_unfocus_on_click(dialog)
```

- [ ] **Step 9: Imports bereinigen + Verifikation**

Run: `ruff check .` → F401-Meldungen pro Datei abarbeiten (ungenutzte `apply_dark_titlebar`/`disable_min_max`/`apply_app_icon`-Importe entfernen), dann:
Run: `python -m pytest -q ; ruff check .`
Expected: 0 failed, lint clean.

- [ ] **Step 10: App-Smoke (Stichproben)**

Run: `python -m src.main` — öffnen/schließen: Tages-Dialog (Escape schließt), Einstellungen (Escape schließt NICHT), Senden→Zeitraum, Export. Optik unverändert dunkel, Dialoge zentriert.

- [ ] **Step 11: Commit**

```powershell
git add src/dialogs
git commit -m "refactor(dialogs): Chrome-Boilerplate auf theme.create_dialog migriert (Audit M13)" -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: Migration der theme-internen Dialoge (3 Stellen, M13)

**Files:**
- Modify: `src/theme.py` — `themed_askyesno` (~Z. 820-827), `themed_ask_delete_choice` (~Z. 882-889), `_themed_ok_dialog` (~Z. 966-973, Stand nach #119 ohne accent) — pro Stelle gegen Post-Merge-Code verifizieren.

**Interfaces:**
- Consumes: `create_dialog` (gleiche Datei).
- Produces: verhaltensgleiche themed_*-Familie.

**Regel:** NUR die Präambel (`dialog = tk.Toplevel(parent)` … `dialog.focus_set()`) ersetzen; die komplette Ende-Mechanik (`<Return>`→click_yes, `<Escape>`→click_no, `WM_DELETE_WINDOW`, `center_dialog_on_parent → grab_set → wait_window`) und der Body bleiben unangetastet.

- [ ] **Step 1: In allen drei Funktionen die Präambel ersetzen durch**

```python
    dialog = create_dialog(parent, title, modal=False, escape_closes=False)
```

(`modal=False`: grab läuft wie bisher am Ende vor `wait_window`; `escape_closes=False`: Escape bindet weiter unten auf `click_no`-Semantik. Bekannte, funktionsneutrale Abweichung: `focus_set` läuft jetzt vor `configure(bg)` statt am Präambel-Ende — dokumentiert in der Spec.)

- [ ] **Step 2: Verifikation**

Run: `python -m pytest -q ; ruff check .`
Expected: 0 failed, lint clean.
App-Smoke: Sync-Button bei deaktiviertem Sync klicken → themed_showinfo erscheint dunkel, zentriert, OK/Enter/Escape schließen; Rechtsklick-Löschen auf einem Tag mit Eintrag → themed_askyesno erscheint, „Nein"/Escape bricht ab.

- [ ] **Step 3: Commit**

```powershell
git add src/theme.py
git commit -m "refactor(theme): themed-Dialoge nutzen create_dialog (Audit M13)" -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: Doku + Abschluss-Verifikation

**Files:**
- Modify: `CLAUDE.md` (Abschnitt „Dialog-Styling: ein gemeinsames Theme", kommt mit #119), `src/CLAUDE.md` (Abschnitt „Dialoge (`src/dialogs/`)")

**Interfaces:** keine Code-Änderungen.

- [ ] **Step 1: Root-`CLAUDE.md` ergänzen**

Im Abschnitt „Dialog-Styling: ein gemeinsames Theme" nach dem Satz über die Fenster-Chrome-Helfer einfügen:

```markdown
Neue Dialoge entstehen über `theme.create_dialog(parent, title, …)` —
nicht über handgebaute `Toplevel`-Boilerplate; der Helfer setzt die
komplette Fenster-Chrome (BG, dunkle Titelleiste, disable_min_max,
App-Icon, modal/Escape) konventionskonform. `center_dialog_on_parent`
nach dem Widget-Aufbau bleibt Aufgabe des Dialogs.
```

- [ ] **Step 2: `src/CLAUDE.md` ergänzen**

Im Abschnitt „Dialoge (`src/dialogs/`)" anfügen:

```markdown
Alle Dialoge beziehen ihre Fenster-Chrome über `theme.create_dialog(...)`
(Audit M13); Content-Styles (`apply_combobox_style`/`apply_notebook_style`/
`attach_unfocus_on_click`) und `center_dialog_on_parent` ruft jeder Dialog
selbst nach dem Aufbau.
```

- [ ] **Step 3: Gesamtverifikation**

Run: `python -m pytest -q ; ruff check .`
Expected: 0 failed, lint clean.
Grep-Check: `Grep "tk.Toplevel(" src/` → nur noch `tooltip.py` (kein Dialog) und `theme.py::create_dialog` selbst.

- [ ] **Step 4: Commit**

```powershell
git add CLAUDE.md src/CLAUDE.md
git commit -m "docs: create_dialog als Dialog-Konvention in CLAUDE.md verankert" -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Abschluss

Nach Task 5: finaler Whole-Branch-Review, dann Screenshot-Abnahme durch den
Nutzer (conflicts vorher/nachher via `SendUserFile`), dann
`superpowers:finishing-a-development-branch` — Branch nach `origin` (Fork),
PR gegen `margenheld/Zeiterfassung` `master` (Memory `pr-workflow-upstream`),
kein `release:*`-Label. PR-Text: H3/M13 referenzieren, Spec verlinken,
Verhaltensgleichheits-Garantie + die eine bewusste Logik-Änderung
(`_selected = None`) benennen.
