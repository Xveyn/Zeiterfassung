# macOS Button-Styling Fix — Design Spec

## Overview

Auf macOS rendern `tk.Button`-Widgets immer als native Aqua-Buttons und ignorieren `bg`, `fg`, `relief=tk.FLAT` sowie `highlightthickness`. Konsequenz im aktuellen Build (siehe Screenshots in der Brainstorm-Session): die Header-Buttons (`‹`, `›`, `⚙`), der `Monat`/`Woche`-Toggle, `Monat senden` im Footer, sowie die Buttons im Update-Banner und in Dialogen erscheinen als weiße System-Buttons. Bei aktiven Toggles und Primary-Buttons (`bg=ACCENT`, `fg="#ffffff"`) ist der Text "weiß auf weiß" — praktisch unsichtbar.

Diese Spec ersetzt alle `tk.Button` in der Anwendung durch Label-basierte Custom-Buttons (`tk.Frame` + inneres `tk.Label`), zentral in `src/theme.py`. Labels und Frames respektieren `bg`/`fg` auch unter Aqua, das gesamte Grid besteht bereits aus diesen Widget-Typen und sieht auf Mac korrekt aus. Außerdem wird die Font-Familie plattformabhängig gesetzt, damit `"Segoe UI"` (existiert auf macOS nicht) nicht auf einen unbekannten Fallback fällt und die pixel-fixierten Zellgrößen kippen.

Out-of-Scope (bewusst): `tk.Checkbutton` im Settings-Dialog (Aqua-Default ist auf dunklem Hintergrund lesbar), Tastatur-Aktivierung der neuen Buttons (Space/Enter/Focus-Ring — die App hat heute keine Tastatur-Navigation außer Pfeile), Linux-Look-Verbesserungen (Tk auf Linux respektiert `tk.Button`-Styling bereits), visueller Press-State (alte `tk.Button` zeigten kurzes `activebackground`-Flash beim Klick — Label-basierte Buttons haben nur Hover, kein Press-State; für ein Zeit-Tracking-Tool akzeptabel).

## Scope decisions

| # | Decision | Consequence |
|---|----------|-------------|
| 1 | `tk.Label` als Button-Basis statt `ttk.Button`, `tkmacosx` oder `tk.Canvas` | Labels respektieren `bg`/`fg` plattformübergreifend identisch; keine externe Dependency; keine Build-Komplikation; das Grid besteht bereits aus Labels und funktioniert auf Mac einwandfrei |
| 2 | Öffentlicher Helper `label_button(parent, text, command, *, bg, fg, hover_bg, hover_fg, font, ...) -> tk.Frame` als Single-Source (kein Unterstrich, weil außerhalb von `theme.py` verwendet — für die Update-Banner-Buttons in `ui.py`) | Vier vorhandene Wrapper (`primary_button`, `secondary_button`, `toggle_button`, `icon_button`) bleiben dünn; ein Punkt für Verhaltensänderung |
| 3 | Outer `tk.Frame` + inneres `tk.Label`, beide mit `<Button-1>` und `<Enter>`/`<Leave>` gebunden | Frame trägt den Hintergrund-Rahmen (Padding), Label den Text; ohne Bindings auf beiden würden Hover/Click bei Cursor-Bewegung über das innere Label nicht zuverlässig auslösen |
| 4 | Drop-in-Signaturen für die vier vorhandenen Wrapper, aber **kein** `**kw`-Passthrough mehr — nur explizit unterstützte Parameter (heute: `font`, `padx`, `pady`, `fg`, `hover_fg`, `active`) | Heutige Caller (grep-verifiziert über `src/`) übergeben ausschließlich diese Parameter. `**kw` würde silent-drop sein und schlechte Erwartungen wecken. Falls künftig ein weiterer Parameter gebraucht wird: explizit ergänzen |
| 5 | Rückgabe-Typ: `tk.Frame` mit Attributen `_label` (inneres Label) und `_colors` (dict mit `bg`, `fg`, `hover_bg`, `hover_fg`) | `set_toggle_active` mutiert nur `_colors` + setzt aktuelle Farben neu; Enter/Leave-Handler lesen aus `_colors` statt aus Closure-Variablen. So bleiben die bei Konstruktion gesetzten Bindings stabil und `attach_tooltip(btn, ...)` (das via `add="+"` zusätzliche Enter/Leave-Handler bindet) wird nicht durch ein Unbind kaputtgemacht |
| 6 | `set_toggle_active` mutiert `btn._colors` und schreibt die aktuelle Nicht-Hover-Variante zurück auf Frame + Label | Einzige Stelle für nachträgliches Restyling; keine Bindings werden angefasst |
| 7 | Font-Familie plattformabhängig in `theme.py`: `"Helvetica Neue"` auf macOS, `"DejaVu Sans"` auf Linux, `"Segoe UI"` auf Windows | Vermeidet stille Fallbacks mit abweichender Metrik; "Helvetica Neue" ist auf allen unterstützten macOS-Versionen vorinstalliert |
| 8 | Schriftgrößen unverändert lassen | Probe-Label-basierte Pixel-Größen in `_refresh_month`/`_refresh_week` bleiben stabil — keine Layout-Anpassung nötig |
| 9 | Die zwei inline `tk.Button` in `ui.py::_show_update_banner` (Download, Dismiss) werden auf die Helper umgestellt | Kein neuer Helper nötig — `primary_button`-artige Farben für "Download", `icon_button`-artige für "✕"; konsistent zum Rest |
| 10 | `tk.Checkbutton` im Settings-Dialog (Autostart) wird **nicht** ersetzt | Aqua-Default ist laut Screenshot lesbar/bedienbar; Custom-Checkbox wäre eigene Mini-Architektur, die hier YAGNI ist |
| 11 | Versions-Bump auf `1.11.0`, CHANGELOG-Eintrag, `release:minor`-Label | Sichtbare UI-Verbesserung auf einer Plattform; keine breaking changes |

## 1) Widget-Architektur

### Öffentlicher Helper

In `src/theme.py`:

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
    mutiert `_colors`, die Bindings lesen daraus — so kein Unbind nötig
    und attach_tooltip (add="+") bleibt funktional.
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

### Öffentliche Wrapper

Die vier bisherigen Helper behalten ihre Aufruf-Signatur (für vorhandene Caller), nehmen aber **keinen** `**kw`-Passthrough an. Heutige Caller (grep-verifiziert) übergeben ausschließlich `font`, `padx`, `pady`, `fg`, `hover_fg`, `active` — exakt das, was die Helper explizit annehmen:

```python
def primary_button(parent, text, command, font=FONT_BOLD, padx=16, pady=4):
    return label_button(
        parent, text, command,
        bg=ACCENT, fg="#ffffff",
        hover_bg=ACCENT_HOVER, hover_fg="#ffffff",
        font=font,
        label_padx=padx, label_pady=pady,
    )

def secondary_button(parent, text, command, font=FONT, padx=16, pady=4):
    return label_button(
        parent, text, command,
        bg=CELL_BG, fg=TEXT,
        hover_bg=ENTRY_BG, hover_fg=TEXT,
        font=font,
        label_padx=padx, label_pady=pady,
    )

def icon_button(parent, text, command, fg=ACCENT, hover_fg=None):
    if hover_fg is None:
        hover_fg = fg
    return label_button(
        parent, text, command,
        bg=CELL_BG, fg=fg,
        hover_bg=ENTRY_BG, hover_fg=hover_fg,
        font=FONT_BOLD,
        width=3,
    )

def toggle_button(parent, text, command, active=False):
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

### Toggle-Restyling

```python
def set_toggle_active(btn, active):
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

Die in `label_button` gesetzten Enter/Leave-Bindings lesen bei jedem Hover frisch aus `btn._colors` — kein Unbind, keine Closures mit alten Farben, kein Konflikt mit etwaigen späteren `attach_tooltip`-Bindings (die via `add="+"` zusätzliche Handler anhängen).

### Caller-Übersicht (grep-verifiziert)

| Helper | Caller-Sites | Übergebene Parameter |
|--------|--------------|----------------------|
| `primary_button` | `src/dialogs/send_dialog.py:54` (`"Datenordner öffnen"`); `src/dialogs/send_dialog.py:201` (`"Senden"`); `src/dialogs/settings_dialog.py:253` (`"Speichern"`); `src/dialogs/entry_dialog.py:92` (`"Speichern"`) | nur positional |
| `secondary_button` | `src/ui.py:273` (`"Monat senden"`, `padx=12`); `src/dialogs/settings_dialog.py:62` (`"Ordner öffnen"`, `padx=12, pady=2`); `src/dialogs/send_dialog.py:55` (`"OK"`); `src/dialogs/send_dialog.py:202` (`"Abbrechen"`); `src/dialogs/settings_dialog.py:254` (`"Abbrechen"`); `src/dialogs/entry_dialog.py:94` (`"Löschen"`) | nur `padx`/`pady` |
| `icon_button` | `src/ui.py:209, 233, 238` | nur `fg`/`hover_fg` (eine Stelle) |
| `toggle_button` | `src/ui.py:214, 219` | nur `active` |
| `set_toggle_active` | `src/ui.py:323, 324` | — |
| `label_button` (neu) | `src/ui.py:_show_update_banner` (2×) | direkt aufgerufen |

Alle Aufrufe sind mit den neuen, expliziten Signaturen abgedeckt. Kein heutiger Caller übergibt einen Parameter, der gedroppt würde.

## 2) Font-Plattform-Switch

Am Anfang von `src/theme.py` (nach den Tk-Imports, vor den Farbkonstanten):

```python
import platform

_system = platform.system()
if _system == "Darwin":
    _FONT_FAMILY = "Helvetica Neue"
elif _system == "Linux":
    _FONT_FAMILY = "DejaVu Sans"
else:
    _FONT_FAMILY = "Segoe UI"

FONT = (_FONT_FAMILY, 10)
FONT_SMALL = (_FONT_FAMILY, 8)
FONT_TINY = (_FONT_FAMILY, 7)
FONT_BOLD = (_FONT_FAMILY, 10, "bold")
FONT_HEADER = (_FONT_FAMILY, 16, "bold")
FONT_HEADER_SMALL = (_FONT_FAMILY, 12, "bold")
FONT_FOOTER = (_FONT_FAMILY, 12, "bold")
```

Modul-Top-Level — keine Lazy-Init. Grund: `src/ui.py` und die Dialog-Module machen `from src.theme import FONT, FONT_BOLD, ...`. Python bindet bei `from X import Y` den **Wert** zur Import-Zeit, nicht den Namen — eine spätere Reassignment von `theme.FONT` würde die schon importierten Konstanten in den anderen Modulen nicht aktualisieren. Daher: Konstanten müssen zur Import-Zeit ihren Endwert haben.

Größen bleiben identisch — Probe-Label-Berechnung in `_refresh_month`/`_refresh_week` bleibt stabil. Familien-Wechsel kann minimal die Pixel-Breite verschieben; falls auf einer Plattform `width=8` für die Standardzelle nicht reicht, ist das ein eigener Fix (nachweisbar nur mit Mac-Test).

**Linux-Fallback-Risiko (akzeptiert):** Auf den unterstützten Linux-Setups (Ubuntu/Debian/Mint mit X11) wird "DejaVu Sans" durch `fonts-dejavu-core` als Default mitgeliefert. Auf minimalen Container-Images ohne `fonts-dejavu-core` fällt Tk still auf einen System-Sans-Serif zurück (typischerweise "TkDefaultFont"). Die Metrik kann dann leicht abweichen, die App bleibt aber funktional — Buttons lesbar, Grid bedienbar, Probe-Label-Mechanismus passt sich der tatsächlichen Familie an. Kein Runtime-Resolver, weil `tkinter.font.families()` einen Tk-Root verlangt und die Import-Ordnung der Module die naheliegende Lösung sabotiert (Theme wird vor `tk.Tk()` aus `main.py` importiert).

## 3) Update-Banner-Buttons in `ui.py`

`_show_update_banner` enthält zwei inline `tk.Button`-Konstruktionen. Diese werden durch Aufrufe von `label_button` ersetzt (kein neuer Wrapper, weil die Banner-Farben `bg=ACCENT` / `bg="#ffffff"` einzigartig sind):

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
```

```python
download_btn = label_button(
    self._update_banner, "Download",
    lambda: self._open_update_download(release),
    bg="#ffffff", fg=ACCENT,
    hover_bg="#f0f0f0", hover_fg=ACCENT_HOVER,
    font=FONT_BOLD,
    label_padx=14, label_pady=2,
)
download_btn.pack(side=tk.RIGHT, padx=8, pady=4)
```

`pady=6` am `.pack()` des Dismiss-Buttons gleicht den vertikalen Versatz zum Titel-Label aus, das mit `pady=6` gepackt ist (src/ui.py:173). `pady=4` am Download-Button entspricht der aktuellen Inline-`tk.Button`-Pack-Konfiguration (src/ui.py:191).

**Import-Anpassung in `src/ui.py`:**

Heutiger Import (src/ui.py:33–40):
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

Wird ergänzt um `label_button` in der letzten Zeile. Die Helfer `primary_button` werden in ui.py heute nicht verwendet — bleibt so.

**Tooltip-Kompatibilität:** `attach_tooltip(dismiss_btn, ...)` (src/ui.py:183) wird nach dem Umbau auf einen `tk.Frame` statt `tk.Button` angewendet. `attach_tooltip` (src/tooltip.py) bindet `<Enter>`/`<Leave>` mit `add="+"` — die in `label_button` gesetzten Handler bleiben unangetastet. Wenn der Cursor von Frame auf inneres Label wandert, feuert Tk `<Leave>` auf dem Frame; `attach_tooltip._maybe_close` prüft Pointer-in-Widget, sodass der Tooltip nicht fälschlich verschwindet, solange der Pointer noch im Label ist. Verifikations-Punkt: Tooltip am `✕` muss stehen bleiben, solange die Maus über dem Button ist.

## 4) Datei-Änderungen — Übersicht

| Datei | Änderung |
|-------|----------|
| `src/theme.py` | Plattform-Switch für `_FONT_FAMILY` am Modul-Top; alle `FONT*`-Konstanten nutzen sie; neuer Helper `label_button`; vier Wrapper-Funktionen umgebaut; `set_toggle_active` umgebaut |
| `src/ui.py` | Import `label_button` aus `theme`; zwei inline `tk.Button` in `_show_update_banner` durch `label_button`-Aufrufe ersetzt |
| `src/version.py` | `VERSION = "1.11.0"` |
| `CHANGELOG.md` | Eintrag `1.11.0` mit "macOS: alle Buttons im Dark-Theme statt nativ-Aqua; Font-Familie pro Plattform" |

Insgesamt ca. 80–100 geänderte Zeilen, kein Test-Code (UI-Tests existieren nicht). `main.py` bleibt unverändert.

## 5) Verifikations-Plan

**Automatisiert (CI):**
- `pytest` muss komplett grün durchlaufen — `src.theme`-Import wird durch viele Test-Module getriggert (über `src.ui`-Pfad), Import-Fehler würden hier auffallen.

**Manuell auf jeder Plattform (vor Release-Merge):**

1. **Windows** — App starten (`python -m src.main`), alle Buttons prüfen:
   - Header: `‹`, `›`, `⚙` — Hover-Farbe sichtbar
   - Toggle `Monat`/`Woche` — Switch klickbar, aktive Variante mit rotem Hintergrund + weißem Text, inaktive grau
   - Footer: `Monat senden` — Hover dunkler
   - Dialog `Eintrag bearbeiten`: `Speichern`/`Abbrechen` lesbar
   - Update-Banner (falls verfügbar): `Download` weiß auf rot, `✕` weiß auf rot

2. **macOS (primäres Ziel)** — gleiche Checkliste. Vorher-Screenshot vergleichen: kein weißer Aqua-Button mehr; alle Buttons im Dark-Theme; Texte lesbar.

3. **Linux** — gleiche Checkliste, Fokus auf "nichts kaputt gemacht": Buttons klickbar, Hover funktioniert, Grid-Zellgrößen okay. Wenn "DejaVu Sans" auf dem Testsystem fehlt, fällt Tk still auf die System-Default-Familie zurück — Funktionalität bleibt erhalten, Metrik kann minimal abweichen.

Kein UI-Automation-Test — der Wert wäre dem Aufwand nicht entsprechend.

## 6) Risiken & Mitigationen

| Risiko | Mitigation |
|--------|------------|
| Hover-Übergang flackert beim Wechsel Frame↔Label (Mauszeiger triggert beide Bindings) | Beide Bindings setzen exakt die gleichen Farben → idempotent, kein sichtbares Flackern |
| Padding auf Label statt Frame führt zu anderem Klick-Hit-Bereich als vorher | Klick-Binding ist *auf* dem Frame UND dem Label — gesamter sichtbarer Bereich ist klickbar wie bisher |
| Font-Familienwechsel verschiebt Pixel-Metriken auf Mac, Zellen werden zu schmal | Probe-Label-Mechanismus in `_refresh_month`/`_refresh_week` misst zur Laufzeit, passt sich automatisch an; nur falls `width=8` (Char-Einheit) bei einer Familie deutlich schmaler ist, kippt's — laut Screenshot mit aktuellem unbekanntem Fallback ist's okay, mit explizitem "Helvetica Neue" tendenziell stabiler |
| `tk.Frame` ohne explizite `width`/`height` zieht sich auf `0` bei leerem Label-Pad | Label hat immer Text + padx/pady → Frame bekommt natürliche Größe via Pack-Geometry |
| `transient()`/Dialog-Logik erwartet `tk.Button` als Default-Button | Wird nirgendwo getan — Dialoge binden nicht auf Button-Typen, sondern auf `<Return>`-Events am Toplevel |

## 7) Versions-Bump & Release

- `src/version.py`: `VERSION = "1.11.0"`
- `CHANGELOG.md`: neuer Eintrag unter `## 1.11.0`:
  > - macOS: alle Buttons rendern jetzt im Dark-Theme statt als native Aqua-Buttons (Header, Toggle, Footer, Dialog-Buttons, Update-Banner)
  > - Font-Familie wird plattformabhängig gewählt (Windows: Segoe UI, macOS: Helvetica Neue, Linux: DejaVu Sans)
- PR-Label: `release:minor` — sichtbare UI-Verbesserung, keine breaking changes
- Workflow erzeugt automatisch Tag + Release nach Merge
