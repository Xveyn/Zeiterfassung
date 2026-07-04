# Design: conflicts_dialog ans Dialog-Theme + create_dialog-Helfer (Audit H3 + M13)

> Stand 2026-07-04 · Ansatz A aus dem Brainstorming zum Audit
> `AUDIT-2026-07-04.md` (Findings H3, M13; Empfehlung #2).

## Voraussetzungen / Sequenzierung

**Dieser Durchgang setzt zwei offene PRs voraus und startet erst, wenn beide
in `master` sind:**

- **PR #119** (`fix/dialog-accent-bar`): entfernt den Akzentbalken in
  `theme.py`s Warn-/Fehler-Dialogen — exakt die Funktionsregion, die M13
  migriert — und enthält den CLAUDE.md-Konventionstext „ein gemeinsames
  Dialog-Theme", auf den sich H3 stützt.
- **PR #121** (`fix/datenschicht-threadsicherheit`): hat
  `conflicts_dialog.py` um den `data_lock`-Parameter erweitert; das Theming
  baut auf diesem Stand auf.

Branch: `fix/dialog-theme-helper` ab `master` (kein Fork-Stacking;
sequenzielle PRs). Spec + Plan werden sofort auf diesem Branch committet
(reine Docs, konfliktfrei); die **Implementierung startet erst**, nachdem
#119 und #121 gemerged sind und `master` in den Branch gemergt wurde —
alle Zeilennummern/Code-Zitate sind dann gegen den aktualisierten Stand zu
verifizieren.

## Problem

- **H3:** `src/dialogs/conflicts_dialog.py` verstößt komplett gegen das
  gemeinsame Dialog-Theme: native `tk.Frame`/`Label`/`Listbox`/`Button` ohne
  `BG`, kein `apply_dark_titlebar`/`disable_min_max`, kein
  `resizable(False, False)`, kein `center_dialog_on_parent` — einziger
  Theme-Aufruf ist `apply_app_icon` (Z. 51). Ergebnis: hellgrauer
  System-Dialog mitten in der Dark-App. Alle anderen Dialoge halten die
  Konvention ein.
- **M13:** Die 8-Zeilen-Chrome-Boilerplate (`Toplevel → title → resizable →
  grab_set/focus_set → configure(bg=BG) → apply_dark_titlebar →
  disable_min_max → apply_app_icon`) ist ~12× dupliziert
  (`entry_dialog.py:101`, `settings_dialog.py:47`, `send_dialog.py:22` und
  `:84`, `export_dialog.py:21`, `share_dialog.py:43`, `import_dialog.py:101`
  und `:411`, `category_dialog.py:145`, 3× `theme.py` in den themed-Dialogen
  — Zeilennummern: master-Stand `86cd70d`, verschieben sich durch #119/#121
  leicht). Genau diese fehlende Struktur ist die Lücke, durch die H3
  gerutscht ist.

## Ziele / Nicht-Ziele

**Ziele:** conflicts_dialog vollständig ans Theme; `create_dialog`-Helfer,
der die Chrome-Konvention strukturell erzwingt; alle 12 Bestandsstellen
**verhaltensgleich** migriert; Konvention in CLAUDE.md um den Helfer ergänzt.

**Nicht-Ziele:**
- Kein Layout-/UX-Umbau des conflicts_dialog (Liste links, Details rechts,
  A/B + Schließen bleiben).
- Content-Styles bleiben Call-Site-Sache: `apply_combobox_style`,
  `apply_notebook_style`, `attach_unfocus_on_click` und
  `center_dialog_on_parent` (braucht die fertige Dialog-Größe → nach dem
  Build) wandern NICHT in den Helfer.
- Keine neuen Farben/Fonts außerhalb der bestehenden Palette.
- Kein Tk-UI-Test-Framework (Chrome ist headless untestbar, wie gehabt —
  Audit M16 bleibt offen).

## Design

### 1. `theme.create_dialog(...)` — der Chrome-Helfer

```python
def create_dialog(parent, title, *, resizable=False, modal=True,
                  escape_closes=True):
    """Erzeugt einen konventionskonformen Dialog-Toplevel (Chrome komplett):
    title → [resizable(False, False)] → [grab_set] → focus_set →
    configure(bg=BG) → apply_dark_titlebar → disable_min_max →
    apply_app_icon → [<Escape>-Bind auf destroy]. Liefert das Toplevel.

    focus_set() MUSS nach grab_set() laufen, sonst feuern Tastatur-
    Bindungen (z.B. Escape) am Dialog nie (Kommentar aus entry_dialog
    hierher übernommen — er gilt für alle Dialoge).

    KEIN transient-Param: transient setzt center_dialog_on_parent —
    bewusst gated auf sichtbaren Parent (Tray-Fall, siehe dessen
    Docstring). Ein ungegatetes transient hier wäre genau die Falle,
    die das Gating verhindert.

    Content-Styles (apply_combobox_style/apply_notebook_style/
    attach_unfocus_on_click) und center_dialog_on_parent (braucht die
    fertige Größe) bleiben bewusst beim Aufrufer."""
```

Parameter-Semantik (bildet die reale Varianz der 12 Stellen ab):
- `resizable=False` → ruft `resizable(False, False)`; `resizable=True` →
  ruft **nichts** (Tk-Default bleibt, verhaltensgleich zu heutigen Stellen
  ohne resizable-Zeile).
- `modal=True` → `grab_set()`; `modal=False` → kein grab. Die
  theme-internen Dialoge nutzen `modal=False`: ihr grab läuft heute am
  **Ende** (`center_dialog_on_parent → grab_set → wait_window`,
  theme.py:864-866) und bleibt dort — der Helfer ersetzt nur ihre
  Chrome-Präambel.
- `escape_closes=True` → `dialog.bind("<Escape>", lambda _e:
  dialog.destroy())`; `False` → kein Bind. `False` gilt für settings,
  send:22 (heute kein Escape) UND die theme-internen Dialoge (deren
  Escape bindet auf `click_no()`/Result-Semantik + `WM_DELETE_WINDOW`-
  Protocol — bleibt vollständig an der Call-Site).
- **Kein `transient`-Param** (siehe Docstring). `import_dialog.py:411`
  behält seine heutige ungegatete `self.top.transient(parent)`-Zeile
  explizit an der Call-Site (Verhaltensgleichheit); alle zentrierenden
  Dialoge bekommen transient ohnehin korrekt gated über
  `center_dialog_on_parent`.
- Reihenfolge im Helfer ist fix (siehe Docstring). Sie entspricht dem
  Muster der `dialogs/`-Stellen; bei den theme-internen Stellen steht
  `focus_set` heute am Ende der Präambel statt vor `configure(bg)` —
  funktionsneutral (kein grab beteiligt), wird als bekannte, unschädliche
  Reihenfolgen-Abweichung akzeptiert.

Lage in `theme.py`: bei den anderen Fenster-Chrome-Helfern
(`apply_dark_titlebar`/`disable_min_max`/…).

### 2. `set_secondary_button_enabled(btn, enabled)` — bestehendes Muster verallgemeinern

Die A/B-Buttons des conflicts_dialog brauchen Enabled/Disabled. Das Repo
hat dafür **bereits ein etabliertes Muster**: `set_primary_button_enabled`
(theme.py:353-371) — **Optik-only** (mutiert `_colors`, dimmt auf
Disabled-Farben, Cursor arrow, kein Hover-Wechsel); die Klick-Bindung
bleibt aktiv, und **der Callback selbst muss bei disabled ein No-op sein**
(so dokumentiert es der bestehende Docstring). KEINE Änderung an
`label_button`, KEIN neues `_enabled`-Flag — wir folgen dem Muster:

```python
def set_secondary_button_enabled(btn, enabled):
    """Pendant zu set_primary_button_enabled für secondary_buttons:
    enabled = CELL_BG/TEXT mit ENTRY_BG-Hover; disabled = CELL_BG/
    TEXT_MUTED ohne Hover-Wechsel + Pfeil-Cursor. Nur Optik — der
    Callback muss bei disabled selbst ein No-op machen (Muster von
    set_primary_button_enabled)."""
```

**Callback-No-op-Vertrag im conflicts_dialog:** der bestehende Guard
`if self._selected is None: return` in `_resolve_with_candidate` trägt
das — **aber nur, wenn der Erfolgspfad `self._selected = None` setzt**
(heute schützt `tk.Button(state="disabled")` hart; nach der Migration
schützt der Guard, also MUSS nach erfolgreicher Resolution
`self._selected = None` gesetzt werden, sonst löst ein Klick auf den
gedimmten Button den alten Konflikt erneut aus). Diese eine Zeile ist
die einzige beabsichtigte Logik-Änderung im Dialog.

### 3. conflicts_dialog ans Theme (H3)

Layout unverändert; nur Chrome + Widget-Theming:

- Chrome: `self.top = create_dialog(parent, "Konflikte auflösen")`
  (modal + Escape wie heute; NEU dazu: bg, dunkle Titelleiste,
  disable_min_max, `resizable(False, False)`); nach `self._build()` NEU:
  `center_dialog_on_parent(self.top, parent)` — das ersetzt zugleich das
  heutige ungegatete `transient(parent)` durch die gegatete Variante
  (Verhaltensänderung nur im Tray-Fall, dort die korrektere; der
  reale Parent ist der immer sichtbare Settings-Dialog).
- Frames: `bg=BG`. Labels: `bg=BG, fg=TEXT, font=FONT` („Offene Konflikte"
  als `FONT_BOLD` analog zu Section-Headern anderer Dialoge).
- **Listbox** (einzige im Repo — Palette-Anwendung, kein neues Konzept):
  `bg=ENTRY_BG, fg=TEXT, selectbackground=ACCENT,
  selectforeground="#ffffff", relief="flat", highlightthickness=0,
  font=FONT`.
- Buttons: `secondary_button` für „Version A übernehmen", „Version B
  übernehmen" und „Schließen" (zwei gleichwertige Wahloptionen — bewusst
  kein Primary-Akzent). A/B starten disabled
  (`set_secondary_button_enabled(btn, False)`), werden bei Auswahl
  enabled, nach Resolution wieder disabled + `self._selected = None`
  (siehe Abschnitt 2 — ersetzt die heutige harte `state`-Sperre).
- `data_lock`-Durchreichung aus PR #121 bleibt unangetastet.

### 4. Migration der 12 Bestandsstellen (M13)

**Eiserne Regel: verhaltensgleich pro Stelle.** Der Helfer wird mit exakt
den Parametern aufgerufen, die den Ist-Zustand reproduzieren; was der
Helfer nicht abdeckt, bleibt als Folgezeile an der Call-Site. Konkret
(Ist-Stand master; vor der Umsetzung pro Stelle gegen den dann aktuellen
Code verifizieren, v. a. nach #119):

| Stelle | create_dialog-Params | bleibt an der Call-Site |
|---|---|---|
| `category_dialog.py:145` | Defaults | `attach_unfocus_on_click`, center (existiert) |
| `import_dialog.py:101` | Defaults | combobox, unfocus, center |
| `import_dialog.py:411` | `resizable=True` | explizite `self.top.transient(parent)`-Zeile (heutiges ungegatetes Verhalten), center |
| `share_dialog.py:43` | Defaults | unfocus, center |
| `export_dialog.py:21` | Defaults | combobox, unfocus, center |
| `settings_dialog.py:47` | `escape_closes=False` | combobox, notebook, center |
| `entry_dialog.py:101` | Defaults | combobox, unfocus, center; Warum-Kommentar zu focus-nach-grab wandert in den Helfer-Docstring |
| `send_dialog.py:22` | `escape_closes=False` | center |
| `send_dialog.py:84` | Defaults | combobox, unfocus, center |
| `theme.py` themed_askyesno / themed_ask_delete_choice / `_themed_ok_dialog` (3 Stellen) | `modal=False, escape_closes=False` (verifiziert an themed_askyesno, theme.py:820-866; die anderen beiden folgen demselben Aufbau — beim Migrieren gegenprüfen) | komplette Ende-Mechanik: `<Return>`→click_yes, `<Escape>`→click_no, `WM_DELETE_WINDOW`-Protocol, `center_dialog_on_parent → grab_set → wait_window`; Body/Buttons |

Sonderfälle, die die Params erzwingen (keine stillen „Verbesserungen"):
settings/send:22 binden Escape separat weiter unten (nicht in der
Chrome-Präambel) → `escape_closes=False` vermeidet einen Doppel-Bind;
import:411 hat heute **kein** `resizable(False, False)` und sein transient
bleibt als explizite Zeile; die theme-internen Dialoge grabben am Ende. Wer
beim Migrieren eine Abweichung „reparieren" will, tut das NICHT in diesem PR
(Verhaltensgleichheit ist das Review-Kriterium).

### 5. Doku

- Root-`CLAUDE.md`, Abschnitt „Dialog-Styling: ein gemeinsames Theme"
  (kommt mit #119): `create_dialog` als Pflicht-Einstieg für neue Dialoge
  ergänzen („Neue Dialoge entstehen über `theme.create_dialog(...)`, nicht
  über handgebaute Toplevel-Boilerplate").
- `src/CLAUDE.md`: Dialog-Abschnitt um einen Satz zum Helfer ergänzen.

## Verifikation

- `pytest` (Gesamtsuite grün — Dialog-Chrome ist Tk-gebunden, es gibt
  bewusst keine neuen Headless-Tests; `set_secondary_button_enabled` ist
  ebenfalls Tk-gebunden) + `ruff check .`.
- **Screenshot-Abnahme** (Windows, etablierter Workflow): conflicts_dialog
  vorher/nachher; Stichproben der migrierten Dialoge (entry, settings,
  send, ein themed_showinfo), um Verhaltens-/Optikgleichheit zu belegen.
  Dafür braucht der conflicts_dialog Testdaten: einen Konflikt lokal in
  `conflicts.json` einspielen (dev-data-Modus, vgl. `--dev`-Branch-Ansatz —
  oder minimal: temporäre conflicts.json mit einem unresolved-Eintrag).
- Manueller Smoke: App-Start, Settings öffnen/schließen, Tages-Dialog
  öffnen/speichern, Escape-Verhalten stichprobenartig (settings darf
  NICHT auf Escape schließen — heutiges Verhalten).

## Risiken

- **Merge-Reihenfolge:** startet erst nach #119 + #121 (siehe
  Voraussetzungen); Zeilennummern in dieser Spec verschieben sich —
  Migrationsregel gilt gegen den dann aktuellen Code.
- **theme.py-interne Dialoge:** deren Ende-Mechanik (center → grab →
  wait_window) bleibt komplett an der Call-Site — der Helfer ersetzt nur
  die Präambel; beim Migrieren pro Stelle gegen den Post-#119-Code prüfen.
- **Optik-only-Disable:** ohne die neue Zeile `self._selected = None`
  nach der Resolution wäre der gedimmte A/B-Button klickbar-wirksam
  (Guard griffe nicht) — im Review explizit gegenprüfen.
