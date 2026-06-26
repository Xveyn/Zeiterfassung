# PDF-Export — Design

Datum: 2026-06-26

## Problem

Im Hauptfenster gibt es im Footer zwei Aktionen: „Arbeitszeiten senden" (PDF
per Gmail) und „Teilen" (Daten als JSON-Anhang per Gmail). Beide Pfade
**mailen** — es gibt keinen Weg, den PDF-Bericht **lokal** zu erzeugen und zu
speichern. Nutzer ohne eingerichteten Gmail-Versand (oder die einfach nur eine
Datei wollen) haben keine Möglichkeit, an die PDF zu kommen.

## Scope

Eine dritte Footer-Aktion **„Export"**: öffnet ein Modal mit Zeitraum +
Kategorie-Auswahl (identisch zur Senden-Maske), erzeugt daraus die PDF und
speichert sie über einen „Speichern unter"-Dialog lokal auf die Platte.

Die PDF-Erzeugung existiert bereits (`report.generate_pdf` liefert fertige
Bytes); neu ist allein der **lokale Speicher-Pfad** (bisher mailen beide
Aktionen).

**Nicht im Scope (YAGNI):** Auto-Öffnen der PDF nach dem Speichern,
Mehrfach-/Batch-Export, Format-/Layout-Optionen, Persistenz eines
Export-Verzeichnisses in den Settings.

## Entscheidungen (aus Brainstorming)

- **Speicherort:** nativer „Speichern unter"-Dialog
  (`tkinter.filedialog.asksaveasfilename`) mit vorbefülltem Namen
  `Zeiterfassung_<VON>_<BIS>.pdf`. Nutzer wählt Ordner + Name frei.
  (Konsistent zu `import_dialog.py`, das bereits `askopenfilename` nutzt.)
- **Nach dem Speichern:** nur eine themed Bestätigung („PDF gespeichert unter
  …"), **kein** Auto-Öffnen.
- **Kategorien:** volle Maske wie beim Senden (Zeitraum + Kategorie-Auswahl +
  Live-Stundenvorschau).
- **Modal-Struktur (Ansatz B):** geteilten Zeitraum+Kategorie+Vorschau-Picker
  in einen wiederverwendbaren Helfer extrahieren; **Senden** *und* **Export**
  nutzen ihn. DRY statt ~120 Zeilen Copy-Paste.

## Architektur

### Neue Module

**`src/dialogs/period_picker.py`** — geteilter Tk-Helfer.
- `build_period_picker(parent, storage, settings) -> (frame, handle)`
  - baut Von/Bis-Datumszeilen (Tag/Monat/Jahr-Combos), Kategorie-Checkboxen
    und die Live-Stundenvorschau in einen eigenen `tk.Frame(parent)`.
  - `handle.get_range() -> (date_from, date_to) | (None, None)` — `(None, None)`
    bei ungültiger/unparsebarer Datumskombination.
  - `handle.get_categories() -> set[str] | None` — `None`, wenn keine
    Kategorien existieren oder **alle** ausgewählt sind (= kein Filter; exakt
    die heutige `_selected_categories`-Semantik).
  - Live-Vorschau (Gesamtstunden über `report.total_hours`) und die
    `trace_add`-Verdrahtung leben **im Picker**, nicht im Aufrufer.
- Der Picker kennt weder Senden noch Export — er liefert nur Zeitraum +
  Kategorien. Ausgabe-Aktion + Buttons bleiben Sache des jeweiligen Dialogs.

**`src/dialogs/export_dialog.py`** — der Export-Dialog.
- `open_export_dialog(parent, storage, settings, base_path)`:
  - Dialog-Chrome wie `send_dialog` (Toplevel, Titel „Als PDF exportieren",
    `grab_set`, dark Titlebar, App-Icon, Escape schließt).
  - `build_period_picker(...)` einsetzen, darunter Buttons
    „Exportieren"/„Abbrechen".
  - `do_export()` (Flow siehe unten).
  - **Keine** Gmail-/Credentials-Abhängigkeit — Export funktioniert offline und
    ohne eingerichteten Versand.

### Erweiterungen bestehender Module

**`src/report.py`** — `default_pdf_filename(date_from, date_to) -> str`.
- Liefert `f"Zeiterfassung_{date_from:%Y%m%d}_{date_to:%Y%m%d}.pdf"`.
- Aus `send_dialog.py:266` extrahiert; Senden **und** Export nutzen sie
  (Dateiname bleibt konsistent zwischen Mail-Anhang und lokalem Export).

**`src/time_utils.py`** — `validate_period(date_from, date_to) -> (ok, msg)`.
- `(False, "Das Von-Datum muss vor dem Bis-Datum liegen.")` bei `von > bis`,
  sonst `(True, "")`. Aus `do_send` extrahiert; Senden + Export nutzen sie.
- Liegt bei den übrigen Validierern (`validate_entry`, `validate_slots`).

**`src/dialogs/send_dialog.py`** — Refactor auf den geteilten Picker.
- Inline-Maske (Datumszeilen, Kategorie-Checkboxen, Live-Vorschau,
  `_current_range`/`_selected_categories`) ersetzt durch
  `build_period_picker(...)`. `do_send` liest `handle.get_range()` /
  `handle.get_categories()` und nutzt `validate_period` +
  `default_pdf_filename`. **E-Mail-Pfad inhaltlich unverändert.**

**`src/ui.py`** — Footer-Button + Tray.
- Dritter `secondary_button` „Export" im Footer → `self._export`.
- `_export(self)` → `open_export_dialog(self.root, self.storage, self.settings,
  self.base_path)`.
- Tray-Menü: Eintrag „Export" analog zu „Arbeitszeiten senden"/„Teilen"
  (Konsistenz).
- Button-Reihenfolge im Footer (rechtsbündig): „Arbeitszeiten senden",
  „Export", „Teilen".

### Tests (neu, headless)

- `default_pdf_filename` → exakter String inkl. Datumsformat (`YYYYMMDD`).
- `validate_period` → `von > bis` ungültig, `von == bis` ok, `von < bis` ok.
- `generate_pdf`-`None`-Contract (keine Einträge → `None`) — vorhandene
  Abdeckung im Implementierungs-Plan bestätigen, sonst ergänzen.
- Picker-Logik, soweit Tk-frei testbar: die Kategorie-Auswahl-Semantik
  (`None` bei „alle ausgewählt") ist heute an `BooleanVar` gebunden — wird im
  Plan geprüft, ob ein Tk-freier Kern (Mengen-Logik) sinnvoll extrahierbar ist.
- Tk-Glue (`do_export`, Picker-Widgets, `do_send`-Refactor): im CI kein
  Display → **manuelles QA** (siehe unten). `ruff` fängt Verdrahtungsfehler
  (undefinierte/ungenutzte Namen).

## Flow im Detail — Export

`_export()` → `open_export_dialog` → Modal mit Zeitraum + Kategorien:

1. Klick „Exportieren" → `handle.get_range()`.
   - Ungültiges/leeres Datum → `themed_showerror("Ungültiges Datum", …)`,
     zurück.
   - `validate_period(von, bis)` fehlschlägt (`von > bis`) →
     `themed_showerror("Ungültiger Zeitraum", msg)`, zurück.
2. Einträge **frisch** aus `storage.get_all()` lesen (offener Dialog +
   Hintergrund-Drive-Sync könnte den Storage geändert haben).
3. `categories = handle.get_categories()`.
4. `pdf_bytes = generate_pdf(von, bis, entries, name=settings.get("name"),
   categories=categories)`.
   - `pdf_bytes is None` (keine Einträge im Zeitraum) →
     `themed_showinfo("Keine Einträge", …)`, **vor** dem Speichern-Dialog,
     kein Schreiben. Dialog bleibt offen.
   - **Erst generieren, dann nach dem Pfad fragen** — so wird der
     „Speichern unter"-Dialog bei leerem Zeitraum gar nicht erst gezeigt.
5. `path = asksaveasfilename(initialfile=default_pdf_filename(von, bis),
   defaultextension=".pdf", filetypes=[("PDF", "*.pdf")])`.
   - Abbruch (leerer Rückgabewert) → still zurück, Dialog bleibt offen.
6. Bytes schreiben: `with open(path, "wb") as f: f.write(pdf_bytes)`.
   - `OSError` (z.B. schreibgeschützter Pfad) →
     `themed_showerror("Export fehlgeschlagen", Klartext)`, zurück.
7. `dialog.destroy()` + `themed_showinfo(parent, "Exportiert",
   f"PDF gespeichert unter\n{path}")`.

## Edge-Cases

- **Leerer Zeitraum / keine Einträge:** abgefangen über `generate_pdf → None`
  in Schritt 4, vor dem Speichern-Dialog.
- **Speichern-Dialog abgebrochen:** kein Fehler, Dialog bleibt offen (Nutzer
  kann Zeitraum anpassen oder erneut exportieren).
- **Datei existiert bereits:** `asksaveasfilename` fragt OS-nativ nach
  Überschreiben — keine eigene Behandlung nötig.
- **Schreibfehler:** `OSError` → themed Fehlermeldung mit Klartext (kein
  stiller Fehlschlag; `--noconsole` würde stderr sonst verschlucken).
- **Picker-Refactor am Senden-Pfad:** Regressionsrisiko. Abgesichert über
  manuelles QA des Senden-Flows (Maske rendert, Vorschau aktualisiert,
  Versand mit Zeitraum + Kategorie-Filter funktioniert wie vorher).

## Interaktion mit bestehenden Features

- **Senden** teilt sich ab jetzt Picker, `validate_period` und
  `default_pdf_filename` mit Export — Verhalten unverändert, nur DRY.
- **Teilen** unberührt (eigener JSON-Pfad, andere Maske).
- **Kategorien-Setting / Multi-Slot:** Export nutzt dieselbe Kategorie-Logik
  wie Senden; keine neuen Settings, kein Sync-Bezug.

## Was wir NICHT bauen

- Kein Auto-Öffnen der PDF, kein „Ordner anzeigen".
- Keine Format-/Theme-Optionen im Export-Dialog (PDF-Layout bleibt wie beim
  Senden).
- Keine Persistenz des zuletzt gewählten Export-Ordners.
- Keine Änderung an `report.generate_pdf` selbst (bleibt I/O-frei, liefert
  Bytes; das Schreiben passiert im Dialog).
