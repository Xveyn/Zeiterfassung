# macOS-Lösch-Button in der Tageszelle — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Auf macOS ein kleines ✕-Overlay oben links in jeder Tageszelle mit löschbaren Einträgen, das denselben Lösch-Pfad wie der Win/Linux-Rechtsklick auslöst, und die bisherige macOS-Dialog-Lösch-Ausnahme entfernen.

**Architecture:** Reine, testbare Sichtbarkeits-Funktion in `src/theme.py` (dep-frei, CI-sicher wie `_stray_click_suppressed`). Tkinter-Verdrahtung im Zell-Dispatcher `App._build_day_cell` über einen neuen `_add_delete_button`-Helfer (spiegelt das vorhandene `_add_reservation_marker`-Overlay-Muster). Hover-Repaint analog zum Reservierungs-Marker. macOS-Dialog-Ausnahme in `entry_dialog.py` entfällt.

**Tech Stack:** Python, Tkinter; pytest. Keine neuen Dependencies.

## Global Constraints

- macOS-exklusiv: alle Verhaltensänderungen gegated über `platform.system() == "Darwin"`. Win/Linux bleiben unverändert (Rechtsklick bleibt einziger Lösch-Pfad).
- Datumsformat intern ISO, UI deutsch (hier nicht betroffen — Button trägt kein Datum).
- Tkinter-Widget-Aufbau wird nicht automatisiert getestet (CI ohne Display). Auto-Tests nur für reine Logik; UI-Schicht per `py_compile`-Smoke + manuellem macOS-Test.
- CI installiert nur `pytest` + `holidays` (kein `requirements.txt`): Test-Code darf **nicht** `src.ui` importieren. Reine Helfer in `src/theme.py` ansiedeln.
- Lösch-*Mechanismus* (`App._delete_day`, `_delete_action`, `themed_ask_delete_choice`) bleibt unverändert — der Button ist nur ein weiterer Auslöser.
- Theme: keine neuen Tokens; nur vorhandene `TEXT_MUTED`/`ACCENT`/`FONT_TINY`.
- Shell ist PowerShell 5.1: keine `&&`-Verkettung (mit `;` trennen). Git-Commits enden mit `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`.

---

### Task 1: Reine Sichtbarkeits-Funktion `_should_show_delete_button`

**Files:**
- Modify: `src/theme.py` (neue Funktion neben `_stray_click_suppressed`)
- Test: `tests/test_delete_button.py` (neu)

**Interfaces:**
- Produces: `_should_show_delete_button(is_macos: bool, has_entry: bool, has_reservation: bool) -> bool` in `src/theme.py`. Wahr genau dann, wenn `is_macos and (has_entry or has_reservation)`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_delete_button.py`:

```python
"""Sichtbarkeit des macOS-Lösch-Buttons in der Tageszelle.

Reine Entscheidungslogik `_should_show_delete_button`. Die Tk-Verdrahtung
(_add_delete_button, Aufruf in _build_day_cell, Hover-Repaint) ist UI-Schicht
und wird wie üblich manuell auf macOS verifiziert.
"""
from src.theme import _should_show_delete_button


def test_not_macos_never_shows():
    assert _should_show_delete_button(False, True, True) is False
    assert _should_show_delete_button(False, True, False) is False
    assert _should_show_delete_button(False, False, True) is False


def test_macos_without_deletable_units_hidden():
    assert _should_show_delete_button(True, False, False) is False


def test_macos_with_entry_shows():
    assert _should_show_delete_button(True, True, False) is True


def test_macos_with_reservation_only_shows():
    assert _should_show_delete_button(True, False, True) is True


def test_macos_with_both_shows():
    assert _should_show_delete_button(True, True, True) is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_delete_button.py -v`
Expected: FAIL mit `ImportError: cannot import name '_should_show_delete_button' from 'src.theme'`

- [ ] **Step 3: Add the implementation**

In `src/theme.py`, direkt nach der Funktion `_stray_click_suppressed` einfügen:

```python
def _should_show_delete_button(is_macos, has_entry, has_reservation):
    """macOS-only Lösch-Button (✕) in der Tageszelle: nur auf macOS und nur,
    wenn der Tag löschbare Einheiten hat — Ist-Zeit ODER aktive Reservierung.
    Reine Logik, damit aus den Tests ohne Tk/UI-Deps prüfbar (vgl.
    _stray_click_suppressed)."""
    return is_macos and (has_entry or has_reservation)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_delete_button.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add src/theme.py tests/test_delete_button.py
git commit -m "feat(theme): reine Sichtbarkeitslogik fuer macOS-Loesch-Button

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 2: `_add_delete_button`-Helfer + Verdrahtung in `_build_day_cell` + Hover-Repaint

**Files:**
- Modify: `src/ui.py` — Import aus `src.theme`; neuer Helfer `App._add_delete_button`; Aufruf in `App._build_day_cell`; `_cell_hover` und `_empty_hover` um `_delete_button` erweitern.

**Interfaces:**
- Consumes: `_should_show_delete_button` aus `src.theme` (Task 1); `App._delete_day(date_str)`, `App._add_reservation_marker` (bestehend).
- Produces: `App._add_delete_button(self, cell, date_str) -> None` — setzt ein `tk.Label` „✕" oben links, bindet Klick auf `_delete_day`, taggt `cell._delete_button`.

- [ ] **Step 1: Import der Sichtbarkeitslogik ergänzen**

In `src/ui.py` den `from src.theme import (...)`-Block (beginnt bei Zeile 35) um `_should_show_delete_button` erweitern. Konkret die vorhandene Zeile

```python
    BG, CELL_BG, WEEKEND_BG, ACCENT, ACCENT_HOVER, TEXT, TEXT_MUTED,
```

ersetzen durch:

```python
    BG, CELL_BG, WEEKEND_BG, ACCENT, ACCENT_HOVER, TEXT, TEXT_MUTED,
    _should_show_delete_button,
```

(`platform`, `ACCENT`, `TEXT_MUTED`, `FONT_TINY` sind in `ui.py` bereits importiert.)

- [ ] **Step 2: Helfer `_add_delete_button` hinzufügen**

In `src/ui.py` direkt **nach** der Methode `_add_reservation_marker` (endet mit `cell._reservation_marker = marker`, Zeile 883) einfügen:

```python
    def _add_delete_button(self, cell, date_str):
        """macOS-only: kleines ✕ oben links, das den Lösch-Pfad auslöst.

        <Button-3> ist auf macOS unzuverlässig (Sekundärklick je nach Tk-Version
        <Button-2>/Control-Klick); dieser Button gibt dort einen verlässlichen
        Lösch-Auslöser, ohne den Linksklick-Dialog mit Lösch-Buttons zu belasten.
        Klick ruft denselben _delete_day-Pfad wie der Win/Linux-Rechtsklick
        (Ja/Nein bzw. Slot-Auswahl). Getaggt als cell._delete_button, damit
        _cell_hover/_empty_hover seinen Hintergrund beim Hover mitfärben."""
        bg = cell.cget("bg")
        btn = tk.Label(
            cell, text="✕", font=FONT_TINY, bg=bg, fg=TEXT_MUTED, cursor="hand2",
        )
        btn.place(relx=0.0, x=3, y=2, anchor="nw")
        # "break" stoppt jede Propagation, damit der Klick nicht zusätzlich als
        # Zell-Linksklick (Bearbeiten-Dialog) durchschlägt.
        btn.bind("<Button-1>",
                 lambda e, d=date_str: (self._delete_day(d), "break")[1])
        # fg-Hover (rot als Lösch-Affordance) steuert der Button selbst; den bg
        # färbt _cell_hover/_empty_hover mit der Zelle.
        btn.bind("<Enter>", lambda e: btn.config(fg=ACCENT))
        btn.bind("<Leave>", lambda e: btn.config(fg=TEXT_MUTED))
        cell._delete_button = btn
```

- [ ] **Step 3: Aufruf in `_build_day_cell` ergänzen**

In `src/ui.py` in `_build_day_cell` am Ende des Tooltip-Blocks. Vorhandene Stelle (Zeile 971-972):

```python
        if tip_parts:
            attach_tooltip(cell, "\n".join(tip_parts))
```

ergänzen zu:

```python
        if tip_parts:
            attach_tooltip(cell, "\n".join(tip_parts))

        # macOS-only Lösch-Button (✕) oben links, sobald der Tag löschbare
        # Einheiten hat (Ist-Zeit ODER aktive Reservierung). reservation wird
        # nur bei aktivem Kalender-Sync übergeben (vgl. _add_reservation_marker),
        # daher deckt `reservation is not None` die aktive Reservierung ab.
        if _should_show_delete_button(
            platform.system() == "Darwin", bool(entry), reservation is not None
        ):
            self._add_delete_button(cell, date_str)
```

- [ ] **Step 4: `_cell_hover` um `_delete_button` erweitern**

In `src/ui.py` die Methode `_cell_hover` (Zeile 1244-1252). Vorhandenen Body:

```python
    def _cell_hover(frame, day_lbl, time_lbl, bg):
        frame.config(bg=bg)
        day_lbl.config(bg=bg)
        time_lbl.config(bg=bg)
        # Eck-Marker (nur auf Entry-Zellen mit zusätzlicher Reservierung)
        # mitfärben, sonst bleibt beim Hover ein andersfarbiges Rechteck stehen.
        marker = getattr(frame, "_reservation_marker", None)
        if marker is not None:
            marker.config(bg=bg)
```

ersetzen durch:

```python
    def _cell_hover(frame, day_lbl, time_lbl, bg):
        frame.config(bg=bg)
        day_lbl.config(bg=bg)
        time_lbl.config(bg=bg)
        # Eck-Overlays (Reservierungs-Marker, macOS-Lösch-Button) mitfärben,
        # sonst bleibt beim Hover ein andersfarbiges Rechteck stehen. Nur bg —
        # die fg des Lösch-Buttons steuert dessen eigener Enter/Leave-Handler.
        marker = getattr(frame, "_reservation_marker", None)
        if marker is not None:
            marker.config(bg=bg)
        del_btn = getattr(frame, "_delete_button", None)
        if del_btn is not None:
            del_btn.config(bg=bg)
```

- [ ] **Step 5: `_empty_hover` um `_delete_button` erweitern**

In `src/ui.py` die Methode `_empty_hover` (Zeile 1254-1263). Vorhandenen Body:

```python
    @staticmethod
    def _empty_hover(frame, day_lbl, bg):
        frame.config(bg=bg)
        day_lbl.config(bg=bg)
        # Reservierungs-Eck-Punkt mitfärben — Nur-Reservierungs-Tage sind
        # Empty-Zellen mit Marker; sonst bliebe beim Hover ein andersfarbiges
        # Rechteck hinter dem Punkt stehen.
        marker = getattr(frame, "_reservation_marker", None)
        if marker is not None:
            marker.config(bg=bg)
```

ersetzen durch:

```python
    @staticmethod
    def _empty_hover(frame, day_lbl, bg):
        frame.config(bg=bg)
        day_lbl.config(bg=bg)
        # Eck-Overlays mitfärben — Nur-Reservierungs-Tage sind Empty-Zellen mit
        # Marker (und auf macOS zusätzlich dem Lösch-Button); sonst bliebe beim
        # Hover ein andersfarbiges Rechteck dahinter stehen. Nur bg.
        marker = getattr(frame, "_reservation_marker", None)
        if marker is not None:
            marker.config(bg=bg)
        del_btn = getattr(frame, "_delete_button", None)
        if del_btn is not None:
            del_btn.config(bg=bg)
```

- [ ] **Step 6: Syntax-Smoke**

Run: `python -m py_compile src/ui.py`
Expected: kein Output, Exit 0 (importiert keine schweren Deps, prüft nur Syntax).

- [ ] **Step 7: Commit**

```bash
git add src/ui.py
git commit -m "feat(ui): macOS-Loesch-Button (X) oben links in der Tageszelle

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 3: macOS-Dialog-Lösch-Ausnahme in `entry_dialog.py` entfernen

**Files:**
- Modify: `src/dialogs/entry_dialog.py` — `import platform` raus, `_SHOW_DELETE_IN_DIALOG` + Kommentarblock raus, `delete_ist`/`delete_reservation` + zugehörige Buttons raus, Docstring anpassen.

**Interfaces:**
- Consumes: nichts Neues. `secondary_button` bleibt importiert (an anderen Stellen genutzt: Zeilen 113, 129, 190, 201).

- [ ] **Step 1: `import platform` entfernen**

In `src/dialogs/entry_dialog.py` Zeile 2 löschen:

```python
import platform
```

(Wird nach Entfernen von `_SHOW_DELETE_IN_DIALOG` nirgends mehr genutzt.)

- [ ] **Step 2: Kommentarblock + Konstante entfernen**

In `src/dialogs/entry_dialog.py` die Zeilen 17-22 löschen:

```python
# Löschen folgt im Kalender dem Muster „Linksklick = speichern, Rechtsklick =
# löschen". Der Dialog (Linksklick) ist daher rein zum Anlegen/Bearbeiten — die
# Lösch-Buttons sind dort raus. AUSNAHME macOS: Tkinters Maustasten-Nummerierung
# macht den Rechtsklick (`<Button-3>`) dort unzuverlässig; damit Löschen auf dem
# Mac überhaupt erreichbar bleibt, behält der Dialog dort seine Lösch-Buttons.
_SHOW_DELETE_IN_DIALOG = platform.system() == "Darwin"
```

- [ ] **Step 3: Docstring anpassen**

In `src/dialogs/entry_dialog.py` (Docstring von `open_entry_dialog`) die Zeile

```python
    Liste. Entfernt man alle Zeilen eines Blocks und speichert, wird der Block
    gelöscht — kein separater Lösch-Button (außer macOS).
```

ersetzen durch:

```python
    Liste. Entfernt man alle Zeilen eines Blocks und speichert, wird der Block
    gelöscht — der Dialog hat keinen Lösch-Button (Löschen läuft im Kalender:
    Rechtsklick auf Win/Linux, ✕-Button in der Zelle auf macOS).
```

- [ ] **Step 4: `delete_ist` + Ist-Lösch-Button entfernen**

In `src/dialogs/entry_dialog.py` die Funktion `delete_ist` (Zeilen 154-157) löschen:

```python
    def delete_ist():
        storage.delete(date_str)
        dialog.destroy()
        on_change()
```

Und im Ist-Save-Block (Zeilen 159-163) die beiden Lösch-Zeilen löschen, sodass aus

```python
    ist_save = tk.Frame(outer, bg=BG)
    ist_save.pack(fill="x")
    primary_button(ist_save, "Speichern", save_ist).pack(side=tk.LEFT, padx=2)
    if entry is not None and _SHOW_DELETE_IN_DIALOG:
        secondary_button(ist_save, "Löschen", delete_ist).pack(side=tk.LEFT, padx=2)
```

wird:

```python
    ist_save = tk.Frame(outer, bg=BG)
    ist_save.pack(fill="x")
    primary_button(ist_save, "Speichern", save_ist).pack(side=tk.LEFT, padx=2)
```

- [ ] **Step 5: `delete_reservation` + Reservierungs-Lösch-Button entfernen**

In `src/dialogs/entry_dialog.py` die Funktion `delete_reservation` (Zeilen 229-234) löschen:

```python
        def delete_reservation():
            reservation_store.delete(date_str)
            dialog.destroy()
            on_change()
            if trigger_reconcile is not None:
                trigger_reconcile()
```

Und im Reservierungs-Save-Block (Zeilen 236-242) die Lösch-Zeilen löschen, sodass aus

```python
        res_save = tk.Frame(outer, bg=BG)
        res_save.pack(fill="x")
        primary_button(res_save, "Reservierung speichern",
                       save_reservation).pack(side=tk.LEFT, padx=2)
        if existing_reservation is not None and _SHOW_DELETE_IN_DIALOG:
            secondary_button(res_save, "Reservierung löschen",
                             delete_reservation).pack(side=tk.LEFT, padx=2)
```

wird:

```python
        res_save = tk.Frame(outer, bg=BG)
        res_save.pack(fill="x")
        primary_button(res_save, "Reservierung speichern",
                       save_reservation).pack(side=tk.LEFT, padx=2)
```

- [ ] **Step 6: Syntax-Smoke + bestehende Tests**

Run: `python -m py_compile src/dialogs/entry_dialog.py`
Expected: kein Output, Exit 0.

Run: `pytest -q`
Expected: alle Tests grün (inkl. `tests/test_delete_button.py`); keine Regression durch den Umbau (die Lösch-Logik selbst ist unverändert).

- [ ] **Step 7: Commit**

```bash
git add src/dialogs/entry_dialog.py
git commit -m "refactor(ui): macOS-Dialog-Loeschbuttons entfernen (Zell-Button ersetzt sie)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 4: Doku in `CLAUDE.md` aktualisieren

**Files:**
- Modify: `CLAUDE.md` — Abschnitt „Plattform-Ausnahme macOS".

**Interfaces:** keine.

- [ ] **Step 1: Abschnitt anpassen**

In `CLAUDE.md` den Absatz unter „Kalender-Interaktion: Linksklick speichert, Rechtsklick löscht". Vorhandenen Text:

```markdown
**Plattform-Ausnahme macOS:** Tkinters Maustasten-Nummerierung macht den
Rechtsklick (`<Button-3>`) auf macOS unzuverlässig (Sekundärklick ist je nach
Tk-Version `<Button-2>` bzw. Control-Klick). Damit Löschen auf dem Mac
überhaupt erreichbar bleibt, behält der Dialog **dort** seine Lösch-Buttons
(„Löschen" / „Reservierung löschen"). Gesteuert über
`_SHOW_DELETE_IN_DIALOG = platform.system() == "Darwin"` in `entry_dialog.py`.
Auf Windows/Linux ist Löschen ausschließlich der Rechtsklick.
```

ersetzen durch:

```markdown
**Plattform-Ausnahme macOS:** Tkinters Maustasten-Nummerierung macht den
Rechtsklick (`<Button-3>`) auf macOS unzuverlässig (Sekundärklick ist je nach
Tk-Version `<Button-2>` bzw. Control-Klick). Damit Löschen auf dem Mac
erreichbar bleibt, zeigt die Tageszelle **dort** ein kleines ✕ oben links,
sobald der Tag löschbare Einheiten hat (Ist-Zeit oder aktive Reservierung).
Der ✕-Button löst denselben Lösch-Pfad wie der Rechtsklick aus
(`App._delete_day` inkl. Bestätigung/Slot-Auswahl). Gesteuert über
`_should_show_delete_button` (`theme.py`) + `App._add_delete_button` (`ui.py`).
Der Tages-Dialog hat auf **allen** Plattformen keine Lösch-Buttons. Auf
Windows/Linux ist Löschen ausschließlich der Rechtsklick.
```

- [ ] **Step 2: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: macOS-Loeschen ueber Zell-Button statt Dialog-Buttons

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Manuelle Verifikation (macOS, nach allen Tasks)

Auf einem Mac (`python -m src.main`) prüfen — kann auf Windows nicht automatisiert werden:

1. Tag mit Ist-Zeit: ✕ oben links sichtbar; Klick → „Arbeitszeit löschen?"-Ja/Nein; Bestätigen löscht.
2. Tag mit mehreren Slots: Klick auf ✕ → Checkbox-Auswahldialog (600 ms-Lock), nicht-gewählte Slots bleiben.
3. Reiner Reservierungstag (leere/Feiertags-Zelle mit violettem Punkt): ✕ sichtbar; löscht die Reservierung.
4. Tag mit Ist-Zeit **und** Reservierung: ✕ links + violetter Punkt rechts; Auswahldialog bietet beide.
5. Leerer Tag: **kein** ✕.
6. ✕ färbt sich beim Hover über das Symbol rot; Zell-Hover lässt **kein** andersfarbiges Rechteck hinter dem ✕ stehen. Falls beim Hover über das ✕ die Zelle kurz ihre Hervorhebung verliert (Tk `<Leave>` mit `NotifyInferior` beim Eintritt in das Kind-Widget): als Detail notieren — kein Blocker, ggf. Folge-Fix.
7. Linksklick auf die Zelle (nicht auf das ✕) öffnet weiterhin den Bearbeiten-Dialog; Klick auf das ✕ öffnet den Dialog **nicht**.
8. Tages-Dialog hat keine Lösch-Buttons mehr.

Win/Linux-Regressionscheck: keine ✕ in den Zellen; Rechtsklick löscht wie bisher; Dialog ohne Lösch-Buttons.
