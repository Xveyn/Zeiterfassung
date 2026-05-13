# macOS Button-Styling Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Alle `tk.Button` in der Anwendung durch Label-basierte Custom-Buttons ersetzen, damit das Dark-Theme auch unter macOS Aqua greift (statt nativ weiß zu rendern). Zusätzlich Font-Familie plattformabhängig setzen.

**Architecture:** Neuer öffentlicher Helper `label_button` in `src/theme.py` baut ein `tk.Frame` + inneres `tk.Label` mit Klick-/Hover-Bindings. Die vier vorhandenen Wrapper (`primary_button`, `secondary_button`, `icon_button`, `toggle_button`) delegieren darauf und behalten ihre Aufruf-Signaturen. `set_toggle_active` mutiert einen `_colors`-Dict am Frame statt Bindings zu rebinden (verträglich mit `attach_tooltip` via `add="+"`).

**Tech Stack:** Python 3.10+, tkinter (kein ttk), keine neuen Dependencies. Spec: `docs/superpowers/specs/2026-05-13-macos-button-styling-design.md`.

---

## File Structure

| Datei | Verantwortung |
|-------|---------------|
| `src/theme.py` | Plattform-Switch für `_FONT_FAMILY`, alle `FONT*`-Konstanten daraus abgeleitet; neuer `label_button`-Helper; vier Wrapper umgebaut; `set_toggle_active` umgebaut |
| `src/ui.py` | Import erweitern um `label_button`; zwei inline `tk.Button` in `_show_update_banner` ersetzen |
| `src/tooltip.py` | Hardcoded `("Segoe UI", 9)` auf Plattform-Font umstellen (sonst Tooltip-Inkonsistenz auf Mac) |
| `src/version.py` | `VERSION = "1.11.0"` |
| `CHANGELOG.md` | Neuer Eintrag |

**Testing-Strategie:** Keine neuen pytest-Tests. Die CI hat keinen Tk-Display (Ubuntu-Runner ohne xvfb, siehe `.github/workflows/test.yml`), und alle Buttons sind reine Tk-Widget-Konstruktion ohne isolierbare Logik. Verifikation läuft manuell auf den drei Zielplattformen (siehe Task 9). Die bestehende pytest-Suite muss grün bleiben — sie deckt indirekt Import-Fehler in `src/theme.py` und `src/ui.py` ab.

---

## Chunk 1: Font-Switch + Button-Helper

### Task 1: Font-Familie plattformabhängig setzen

**Files:**
- Modify: `src/theme.py` (Top des Files, vor den Farbkonstanten)

- [ ] **Step 1: `import platform` hinzufügen und Font-Familie ableiten**

Datei `src/theme.py`, ersetze die Zeile `from tkinter import ttk` durch:

```python
import platform
import tkinter as tk
from tkinter import ttk

_system = platform.system()
if _system == "Darwin":
    FONT_FAMILY = "Helvetica Neue"
elif _system == "Linux":
    FONT_FAMILY = "DejaVu Sans"
else:
    FONT_FAMILY = "Segoe UI"
```

(Der vorhandene `import tkinter as tk` muss erhalten bleiben — falls noch nicht vorhanden, ergänzen. Die Reihenfolge ist `import platform; import tkinter as tk; from tkinter import ttk` plus die `_FONT_FAMILY`-Logik darunter.)

- [ ] **Step 2: Font-Konstanten auf `_FONT_FAMILY` umstellen**

Ersetze die vorhandenen Font-Zeilen (aktuell `FONT = ("Segoe UI", 10)` etc.) durch:

```python
FONT = (FONT_FAMILY, 10)
FONT_SMALL = (FONT_FAMILY, 8)
FONT_TINY = (FONT_FAMILY, 7)
FONT_BOLD = (FONT_FAMILY, 10, "bold")
FONT_HEADER = (FONT_FAMILY, 16, "bold")
FONT_HEADER_SMALL = (FONT_FAMILY, 12, "bold")
FONT_FOOTER = (FONT_FAMILY, 12, "bold")
```

- [ ] **Step 3: pytest laufen lassen**

Run: `pytest tests/ -q`
Expected: alle Tests grün (Import-Smoke über alle Module die `src.theme` ziehen).

- [ ] **Step 4: Commit**

```bash
git add src/theme.py
git commit -m "feat(theme): plattformabhängige Font-Familie

macOS hat kein 'Segoe UI'; ohne expliziten Switch fällt Tk still auf
einen System-Default, was die Probe-Label-basierten Pixel-Zellgrößen
verschieben kann. Linux nutzt 'DejaVu Sans' (Default), macOS 'Helvetica
Neue' (auf allen unterstützten Versionen vorinstalliert)."
```

---

### Task 2: `label_button`-Helper schreiben

**Files:**
- Modify: `src/theme.py` (neuer Helper am Ende, nach den vorhandenen Helpern oder oberhalb der vier Wrapper)

- [ ] **Step 1: Helper-Funktion einfügen**

Vor der vorhandenen `primary_button`-Definition (oder an einer logischen Stelle im File) einfügen:

```python
def label_button(
    parent, text, command, *,
    bg, fg, hover_bg, hover_fg,
    font,
    label_padx=0, label_pady=0,
    width=None,
):
    """Frame+Label-Konstrukt als Button-Ersatz.

    `tk.Button` ignoriert auf macOS bg/fg (Aqua-Backend zeichnet nativ).
    `tk.Label` respektiert bg/fg auf allen Plattformen — daher Label
    mit Klick-Bindings statt echtem Button.

    Rückgabe: tk.Frame mit Attributen `_label` (inneres Label) und
    `_colors` (dict mit bg/fg/hover_bg/hover_fg). set_toggle_active
    mutiert `_colors`; die in dieser Funktion gesetzten Bindings lesen
    daraus — kein Unbind nötig, attach_tooltip (add="+") bleibt
    funktional.
    """
    frame = tk.Frame(parent, bg=bg, cursor="hand2")
    label = tk.Label(
        frame, text=text, font=font,
        bg=bg, fg=fg, cursor="hand2",
        width=width,
    )
    label.pack(padx=label_padx, pady=label_pady)
    frame._label = label
    frame._colors = {
        "bg": bg, "fg": fg,
        "hover_bg": hover_bg, "hover_fg": hover_fg,
    }

    def on_click(_e):
        command()

    def on_enter(_e):
        c = frame._colors
        frame.config(bg=c["hover_bg"])
        label.config(bg=c["hover_bg"], fg=c["hover_fg"])

    def on_leave(_e):
        c = frame._colors
        frame.config(bg=c["bg"])
        label.config(bg=c["bg"], fg=c["fg"])

    for w in (frame, label):
        w.bind("<Button-1>", on_click)
        w.bind("<Enter>", on_enter)
        w.bind("<Leave>", on_leave)

    return frame
```

- [ ] **Step 2: pytest laufen lassen (Smoke)**

Run: `pytest tests/ -q`
Expected: alle Tests grün — `label_button` wird noch nicht verwendet, nur Import sollte clean sein.

- [ ] **Step 3: Commit**

```bash
git add src/theme.py
git commit -m "feat(theme): label_button helper für plattformneutrale Buttons

Frame+Label-Konstrukt mit Klick- und Hover-Bindings. _colors-Dict am
Frame ermöglicht spätere Restyles über set_toggle_active ohne unbind."
```

---

## Chunk 2: Wrapper umbauen

### Task 3: `primary_button` umstellen

**Files:**
- Modify: `src/theme.py:89-98` (aktuelle `primary_button`-Definition)

- [ ] **Step 1: Funktion ersetzen**

Ersetze:

```python
def primary_button(parent, text, command, **kw):
    kw.setdefault("font", FONT_BOLD)
    kw.setdefault("padx", 16)
    kw.setdefault("pady", 4)
    return tk.Button(
        parent, text=text, command=command,
        bg=ACCENT, fg="#ffffff",
        activebackground=ACCENT_HOVER, activeforeground="#ffffff",
        relief=tk.FLAT, cursor="hand2", **kw,
    )
```

durch:

```python
def primary_button(parent, text, command, font=FONT_BOLD, padx=16, pady=4):
    return label_button(
        parent, text, command,
        bg=ACCENT, fg="#ffffff",
        hover_bg=ACCENT_HOVER, hover_fg="#ffffff",
        font=font,
        label_padx=padx, label_pady=pady,
    )
```

- [ ] **Step 2: pytest laufen lassen**

Run: `pytest tests/ -q`
Expected: grün.

---

### Task 4: `secondary_button` umstellen

**Files:**
- Modify: `src/theme.py:101-110` (aktuelle `secondary_button`-Definition)

- [ ] **Step 1: Funktion ersetzen**

Ersetze:

```python
def secondary_button(parent, text, command, **kw):
    kw.setdefault("font", FONT)
    kw.setdefault("padx", 16)
    kw.setdefault("pady", 4)
    return tk.Button(
        parent, text=text, command=command,
        bg=CELL_BG, fg=TEXT,
        activebackground=ENTRY_BG, activeforeground=TEXT,
        relief=tk.FLAT, cursor="hand2", **kw,
    )
```

durch:

```python
def secondary_button(parent, text, command, font=FONT, padx=16, pady=4):
    return label_button(
        parent, text, command,
        bg=CELL_BG, fg=TEXT,
        hover_bg=ENTRY_BG, hover_fg=TEXT,
        font=font,
        label_padx=padx, label_pady=pady,
    )
```

- [ ] **Step 2: pytest laufen lassen**

Run: `pytest tests/ -q`
Expected: grün.

---

### Task 5: `icon_button` umstellen

**Files:**
- Modify: `src/theme.py:166-176` (aktuelle `icon_button`-Definition)

- [ ] **Step 1: Funktion ersetzen**

Ersetze:

```python
def icon_button(parent, text, command, fg=ACCENT, hover_fg=None, **kw):
    """Compact icon-style button used in the header (‹ › ⚙)."""
    if hover_fg is None:
        hover_fg = fg
    return tk.Button(
        parent, text=text, command=command, width=3,
        font=FONT_BOLD, bg=CELL_BG, fg=fg,
        activebackground=ENTRY_BG, activeforeground=hover_fg,
        relief=tk.FLAT, cursor="hand2", **kw,
    )
```

durch:

```python
def icon_button(parent, text, command, fg=ACCENT, hover_fg=None):
    """Compact icon-style button used in the header (‹ › ⚙)."""
    if hover_fg is None:
        hover_fg = fg
    return label_button(
        parent, text, command,
        bg=CELL_BG, fg=fg,
        hover_bg=ENTRY_BG, hover_fg=hover_fg,
        font=FONT_BOLD,
        width=3,
    )
```

- [ ] **Step 2: pytest laufen lassen**

Run: `pytest tests/ -q`
Expected: grün.

---

### Task 6: `toggle_button` + `set_toggle_active` umstellen

**Files:**
- Modify: `src/theme.py:113-136` (aktuelle `toggle_button` + `set_toggle_active`-Definitionen)

- [ ] **Step 1: `toggle_button` ersetzen**

Ersetze:

```python
def toggle_button(parent, text, command, active=False, **kw):
    """Two-state segmented button used for the Monat/Woche switcher.

    Re-style with set_toggle_active(btn, bool) when state changes.
    """
    btn = tk.Button(
        parent, text=text, command=command,
        font=FONT_SMALL, width=6, relief=tk.FLAT, cursor="hand2", **kw,
    )
    set_toggle_active(btn, active)
    return btn
```

durch:

```python
def toggle_button(parent, text, command, active=False):
    """Two-state segmented button used for the Monat/Woche switcher.

    Re-style with set_toggle_active(btn, bool) when state changes.
    """
    if active:
        bg, fg, hover_bg, hover_fg = ACCENT, "#ffffff", ACCENT, "#ffffff"
    else:
        bg, fg, hover_bg, hover_fg = CELL_BG, TEXT_MUTED, ENTRY_BG, TEXT
    return label_button(
        parent, text, command,
        bg=bg, fg=fg, hover_bg=hover_bg, hover_fg=hover_fg,
        font=FONT_SMALL, width=6,
    )
```

- [ ] **Step 2: `set_toggle_active` ersetzen**

Ersetze:

```python
def set_toggle_active(btn, active):
    if active:
        btn.config(
            bg=ACCENT, fg="#ffffff",
            activebackground=ACCENT, activeforeground="#ffffff",
        )
    else:
        btn.config(
            bg=CELL_BG, fg=TEXT_MUTED,
            activebackground=ENTRY_BG, activeforeground=TEXT,
        )
```

durch:

```python
def set_toggle_active(btn, active):
    """Mutiert die in `label_button` gesetzten `_colors`. Die Enter/Leave-
    Handler lesen bei jedem Hover frisch daraus — kein Unbind nötig,
    keine Closures mit alten Farben."""
    if active:
        btn._colors = {
            "bg": ACCENT, "fg": "#ffffff",
            "hover_bg": ACCENT, "hover_fg": "#ffffff",
        }
    else:
        btn._colors = {
            "bg": CELL_BG, "fg": TEXT_MUTED,
            "hover_bg": ENTRY_BG, "hover_fg": TEXT,
        }
    c = btn._colors
    btn.config(bg=c["bg"])
    btn._label.config(bg=c["bg"], fg=c["fg"])
```

- [ ] **Step 3: pytest laufen lassen**

Run: `pytest tests/ -q`
Expected: grün.

- [ ] **Step 4: Commit**

```bash
git add src/theme.py
git commit -m "feat(theme): vier Button-Wrapper auf label_button umgestellt

primary_/secondary_/icon_/toggle_button delegieren jetzt an
label_button und behalten Drop-in-Signaturen für vorhandene Caller.
set_toggle_active mutiert _colors statt Bindings zu rebinden —
verträglich mit attach_tooltip (add=+)."
```

---

## Chunk 3: UI-Anpassung + Tooltip + Release

### Task 7: Update-Banner-Buttons in `ui.py` umstellen

**Files:**
- Modify: `src/ui.py:33-40` (Import-Liste)
- Modify: `src/ui.py:175-191` (zwei inline `tk.Button` in `_show_update_banner`)

- [ ] **Step 1: Import erweitern**

In der aktuellen Import-Liste am Top von `src/ui.py`:

```python
from src.theme import (
    BG, CELL_BG, WEEKEND_BG, ACCENT, ACCENT_HOVER, TEXT, TEXT_MUTED,
    ENTRY_BG, WEEKEND_ENTRY_BG, WEEKEND_FG,
    HOLIDAY_BG, HOLIDAY_BG_HOVER, HOLIDAY_ACCENT,
    FONT, FONT_BOLD, FONT_HEADER, FONT_HEADER_SMALL, FONT_FOOTER, FONT_SMALL, FONT_TINY,
    CELL_BG_HOVER, WEEKEND_BG_HOVER, ENTRY_BG_HOVER, WEEKEND_ENTRY_BG_HOVER,
    icon_button, secondary_button, set_toggle_active, toggle_button,
)
```

ersetze die letzte Zeile durch:

```python
    icon_button, label_button, secondary_button, set_toggle_active, toggle_button,
```

- [ ] **Step 2: Dismiss-Button ersetzen**

Aktueller Code (in `_show_update_banner`, ca. Zeile 175–183):

```python
dismiss_btn = tk.Button(
    self._update_banner, text="✕",
    command=lambda: self._dismiss_update_banner(release.version),
    font=FONT_BOLD, bg=ACCENT, fg="#ffffff",
    activebackground=ACCENT_HOVER, activeforeground="#ffffff",
    relief=tk.FLAT, cursor="hand2", bd=0, padx=8,
)
dismiss_btn.pack(side=tk.RIGHT, padx=(0, 4))
attach_tooltip(dismiss_btn, "Diese Version ausblenden")
```

ersetzen durch:

```python
dismiss_btn = label_button(
    self._update_banner, "✕",
    lambda: self._dismiss_update_banner(release.version),
    bg=ACCENT, fg="#ffffff",
    hover_bg=ACCENT_HOVER, hover_fg="#ffffff",
    font=FONT_BOLD,
    label_padx=8,
)
dismiss_btn.pack(side=tk.RIGHT, padx=(0, 4), pady=6)
attach_tooltip(dismiss_btn, "Diese Version ausblenden")
```

- [ ] **Step 3: Download-Button ersetzen**

Aktueller Code (in `_show_update_banner`, ca. Zeile 185–191):

```python
tk.Button(
    self._update_banner, text="Download",
    command=lambda: self._open_update_download(release),
    font=FONT_BOLD, bg="#ffffff", fg=ACCENT,
    activebackground="#f0f0f0", activeforeground=ACCENT_HOVER,
    relief=tk.FLAT, cursor="hand2", bd=0, padx=14, pady=2,
).pack(side=tk.RIGHT, padx=8, pady=4)
```

ersetzen durch:

```python
label_button(
    self._update_banner, "Download",
    lambda: self._open_update_download(release),
    bg="#ffffff", fg=ACCENT,
    hover_bg="#f0f0f0", hover_fg=ACCENT_HOVER,
    font=FONT_BOLD,
    label_padx=14, label_pady=2,
).pack(side=tk.RIGHT, padx=8, pady=4)
```

- [ ] **Step 4: pytest laufen lassen**

Run: `pytest tests/ -q`
Expected: grün — `src.ui`-Import wird durch viele Tests indirekt getriggert.

- [ ] **Step 5: Commit**

```bash
git add src/ui.py
git commit -m "feat(ui): Update-Banner-Buttons auf label_button umgestellt

Dismiss + Download nutzen jetzt den Frame+Label-Helper aus theme.py.
pady=6 am Dismiss-Pack richtet ihn vertikal am Titel-Label aus
(das ebenfalls pady=6 hat)."
```

---

### Task 8: Tooltip-Font auf Plattform-Familie umstellen

**Files:**
- Modify: `src/tooltip.py:1` (Import) und `src/tooltip.py:43` (Font-Tupel)

- [ ] **Step 1: Import ergänzen**

Am Top von `src/tooltip.py` (vor oder nach `import tkinter as tk`):

```python
from src.theme import FONT_FAMILY
```

- [ ] **Step 2: Font-Tupel umstellen**

Ersetze `font=("Segoe UI", 9)` (Zeile 43) durch:

```python
font=(FONT_FAMILY, 9),
```

- [ ] **Step 3: pytest laufen lassen**

Run: `pytest tests/ -q`
Expected: grün.

- [ ] **Step 4: Commit**

```bash
git add src/tooltip.py
git commit -m "fix(tooltip): plattformabhängige Font-Familie nutzen

Hardcoded 'Segoe UI' führte zu Font-Inkonsistenz zwischen App-Body
(Helvetica Neue auf Mac) und Tooltip (Segoe-Fallback)."
```

---

### Task 9: Version-Bump + CHANGELOG

**Files:**
- Modify: `src/version.py`
- Modify: `CHANGELOG.md`

- [ ] **Step 1: Aktuelle Version in `src/version.py` lesen**

Run: `cat src/version.py` oder `Read` auf die Datei.
Expected: aktuell `VERSION = "1.10.3"`.

- [ ] **Step 2: Version auf 1.11.0 setzen**

Ersetze die Zeile mit `VERSION = "..."` in `src/version.py` durch:

```python
VERSION = "1.11.0"
```

- [ ] **Step 3: CHANGELOG.md ergänzen**

Lies zunächst `CHANGELOG.md` und prüfe, mit welchem Präfix der Top-Eintrag versehen ist (Konvention im Repo: `## v1.10.3`). Den neuen Block in identischem Format oberhalb einfügen:

```markdown
## v1.11.0

- macOS: alle Buttons rendern jetzt im Dark-Theme statt als native Aqua-Buttons (Header `‹ › ⚙`, Monat/Woche-Toggle, Footer "Monat senden", Dialog-Buttons, Update-Banner). Bisher war der Text auf primären/aktiven Buttons unter macOS weiß auf weiß und damit unlesbar.
- Font-Familie wird plattformabhängig gewählt: Windows "Segoe UI", macOS "Helvetica Neue", Linux "DejaVu Sans".
```

- [ ] **Step 4: pytest laufen lassen**

Run: `pytest tests/ -q`
Expected: grün.

- [ ] **Step 5: Commit**

```bash
git add src/version.py CHANGELOG.md
git commit -m "release: v1.11.0 — macOS button styling fix"
```

---

### Task 10: Manuelle Verifikation (vor PR-Merge)

**Files:** keine — diese Task ist Verifikation, keine Code-Änderung.

- [ ] **Step 1: Lokaler App-Start auf der aktuellen Plattform**

Run: `python -m src.main`
Expected: App öffnet, kein Crash. Alle Buttons sind im Dark-Theme (rot/dunkelblau), kein weiß-auf-weiß.

- [ ] **Step 2: Visuelle Prüfung der Hauptansicht**

Klicke und hovere folgende Elemente, prüfe:

| Element | Erwartung |
|---------|-----------|
| Header `‹` `›` | rot, Hover dunkler |
| Header `⚙` | grau, Hover heller |
| Toggle "Monat" / "Woche" | aktive Variante rot mit weißem Text, inaktive grau mit gemutetem Text |
| Toggle-Switch beim Klick | Farben tauschen — Text bleibt lesbar |
| Footer "Monat senden" | dunkler Hintergrund, Hover heller |
| Zellen-Hover im Grid | unverändert funktional |

- [ ] **Step 3: Dialog-Buttons**

Klicke auf eine Zelle → Entry-Dialog öffnet sich. Prüfe:
- "Speichern" (primary, rot/weiß) lesbar
- "Löschen" (secondary, dunkel/hell) lesbar — nur sichtbar wenn Eintrag existiert
- "Abbrechen" Logik im Settings/Send-Dialog gleich prüfen

Öffne Settings (`⚙`):
- "Speichern" / "Abbrechen" lesbar
- "Ordner öffnen" (neben Credentials) lesbar

- [ ] **Step 4: Update-Banner (sofern provozierbar)**

Setze `src/version.py` testweise auf `"0.0.1"` (oder lösche `last_update_check_at` aus settings.json), starte neu. Wenn ein neueres Release auf GitHub liegt, erscheint der rote Banner:
- "Download" weiß auf rot
- "✕" weiß auf rot, vertikal mittig zum Titel-Label
- Tooltip am "✕" erscheint und bleibt stehen, solange Maus drüber

**Wichtig:** `src/version.py` nach dem Test wieder auf `1.11.0` zurücksetzen.

- [ ] **Step 5: Cross-Platform — falls Mac/Linux verfügbar**

Wiederhole Step 1–4 auf macOS (primäres Fix-Ziel) und Linux. Auf jedem Mac/Linux mit Display:
- App öffnet, kein Crash
- Buttons im Dark-Theme — kein nativer Aqua-Button mehr
- Texte lesbar

Wenn Mac/Linux nicht verfügbar: im PR-Kommentar dokumentieren, dass nur Windows lokal getestet ist und Mac/Linux-Verifikation aussteht.

---

### Task 11: PR mit `release:minor`-Label öffnen

**Files:** keine — git/gh.

- [ ] **Step 1: Branch pushen**

Run: `git push -u origin <branch-name>`

- [ ] **Step 2: PR erstellen**

```bash
gh pr create --title "v1.11.0 — macOS Button-Styling Fix" --body "$(cat <<'EOF'
## Summary

- Alle `tk.Button` auf Label-basierte Custom-Buttons umgestellt (zentral in `src/theme.py::label_button`). macOS Aqua ignorierte `bg`/`fg` für `tk.Button`, was dazu führte, dass aktive/primäre Buttons auf Mac weiß-auf-weiß und damit unlesbar waren.
- Font-Familie plattformabhängig: Win "Segoe UI", macOS "Helvetica Neue", Linux "DejaVu Sans". Verhindert stille Fallback-Drift, die die Probe-Label-Pixelmetrik der Kalender-Zellen kippen kann.
- Tooltip-Font auf gleiche Plattform-Familie umgestellt.

## Test plan

- [x] `pytest tests/ -q` lokal grün
- [x] Visuelle Verifikation auf Windows (Header, Toggle, Footer, Dialoge, Update-Banner)
- [ ] Visuelle Verifikation auf macOS — primäres Fix-Ziel
- [ ] Visuelle Verifikation auf Linux

Spec: docs/superpowers/specs/2026-05-13-macos-button-styling-design.md
Plan: docs/superpowers/plans/2026-05-13-macos-button-styling.md

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Step 3: `release:minor`-Label setzen**

Run: `gh pr edit <pr-number> --add-label release:minor`

- [ ] **Step 4: CI abwarten**

Run: `gh pr checks <pr-number> --watch`
Expected: Tests-Workflow grün.

- [ ] **Step 5: PR mergen (nach Review)**

Sobald approved und CI grün — Merge. Der Release-Workflow erzeugt automatisch Tag `v1.11.0` und das Release.
