# Design: macOS-Lösch-Button in der Tageszelle (✕ oben links)

Datum: 2026-06-20
Branch: `feat/multi-timeslots-kategorien`

## Problem

Das Kalender-Modell ist „Linksklick = anlegen/bearbeiten, Rechtsklick = löschen".
Auf macOS ist `<Button-3>` unzuverlässig (Sekundärklick je nach Tk-Version
`<Button-2>` bzw. Control-Klick). Damit Löschen auf dem Mac erreichbar bleibt,
zeigt der Tages-Dialog dort als Ausnahme zusätzliche Lösch-Buttons
(`_SHOW_DELETE_IN_DIALOG = platform.system() == "Darwin"` in
`src/dialogs/entry_dialog.py`).

Mit dem Multi-Slot-Feature ist Löschen über den Linksklick-Dialog konzeptionell
unsauber: Der Dialog ist auf Win/Linux bewusst rein zum Speichern, und das
Slot-Modell macht „was genau löschen" zu einer eigenen Auswahl (siehe
`App._delete_day`). Die macOS-Dialog-Buttons löschen dagegen den ganzen Block.

## Ziel

Die macOS-Dialog-Lösch-Buttons durch einen kleinen ✕-Button **oben links** in
der Tageszelle ersetzen. Der Button triggert exakt denselben Lösch-Pfad wie der
Rechtsklick auf Win/Linux (`App._delete_day`), inklusive Bestätigung und
Mehr-Slot-Auswahldialog. Damit gilt auf allen drei Plattformen derselbe
Lösch-*Mechanismus*; nur der *Auslöser* unterscheidet sich (Rechtsklick vs.
Button), weil macOS-Rechtsklick unzuverlässig ist.

Design-Regel des Projekts: „bestmöglich gleich auf allen drei Plattformen; wenn
nicht möglich, exklusive Anpassung." Dies ist eine saubere macOS-exklusive
Ergänzung — Win/Linux bleiben unverändert.

## Verhalten

- **Nur macOS.** Gegated über `platform.system() == "Darwin"`. Auf Win/Linux
  ändert sich nichts; Rechtsklick bleibt der einzige Lösch-Pfad.
- **Sichtbarkeit:** Der Button ist dauerhaft sichtbar (kein Hover-Reveal),
  sobald ein Tag löschbare Einheiten hat — also Ist-Zeit-Slots **oder** eine
  aktive Reservierung (`_reservations_active()`). Auf Tagen ohne löschbare
  Einheiten erscheint er nicht.
- **Abdeckung:** Volle Parität zum Rechtsklick. Erscheint auch auf reinen
  Reservierungstagen (optisch leere/Feiertags-Zellen mit violettem Eckpunkt).
- **Klick:** ruft `App._delete_day(date_str)` auf — bei genau einer löschbaren
  Einheit Ja/Nein-Abfrage, bei mehreren der Checkbox-Auswahldialog
  (`themed_ask_delete_choice`) mit 600 ms Button-Lock. Identisch zum
  Win/Linux-Rechtsklick.
- **Kein Doppel-Effekt:** Ein Klick auf den Button öffnet **nicht** zusätzlich
  den Bearbeiten-Dialog. Der Button ist ein eigenes, über den Zell-Bindings
  liegendes Widget; Tk liefert das Event an das oberste Widget (den Button), die
  Zell-`<Button-1>`-Bindung feuert nicht. Defensiv gibt der Handler `"break"`
  zurück.

## Optik

- Umsetzung als `tk.Label` (kein `tk.Button` — der bringt auf macOS native
  Chrome/Rahmen mit). Spiegelt das vorhandene `_add_reservation_marker`-Muster
  (Overlay via `place()`).
- Glyph: `✕`, Font `FONT_TINY`.
- Platzierung: oben links, `place(relx=0.0, x=3, y=2, anchor="nw")`. Kollidiert
  nicht mit dem Reservierungs-Eckpunkt (oben rechts, `anchor="ne"`).
- Farbe: Ruhezustand `TEXT_MUTED` (grau); beim Hover über das ✕-Symbol selbst
  `ACCENT` (rot) als Lösch-Affordance. `cursor="hand2"`.
- Hintergrund folgt der Zellfarbe und wird beim Zell-Hover mitgefärbt (siehe
  Hover-Integration).
- Kein runder Badge/Hintergrundkreis — die Zelle ist pixel-fixiert und eng.
- Kein neuer Theme-Token; vorhandene `TEXT_MUTED`/`ACCENT` aus `theme.py`.

## Architektur / betroffene Stellen

Einziger funktionaler Einhängepunkt ist der Zell-Dispatcher `App._build_day_cell`
(`src/ui.py`), die einzige Stelle, die sowohl `entry` als auch `reservation`
kennt und bereits `_add_reservation_marker` aufruft.

1. **`src/ui.py` — neuer Helfer `App._add_delete_button(cell, date_str)`**
   Baut das ✕-`tk.Label`, platziert es oben links, bindet `<Button-1>` →
   `self._delete_day(date_str)` (mit `return "break"`), bindet `<Enter>`/
   `<Leave>` für die Rot-Hover-Färbung des Glyphs, und taggt es als
   `cell._delete_button` (analog `cell._reservation_marker`).

2. **`src/ui.py` — `App._build_day_cell`**
   Nach dem Aufbau der Zelle und dem optionalen `_add_reservation_marker`: wenn
   macOS **und** (`entry` vorhanden **oder** `reservation` aktiv vorhanden),
   `self._add_delete_button(cell, date_str)` aufrufen.
   - macOS-Erkennung über ein Modul-Konstanten-Flag (z. B. `_IS_MACOS =
     platform.system() == "Darwin"`); `platform` ist in `ui.py` zu importieren,
     falls noch nicht vorhanden.
   - Die Reservierungs-Bedingung muss zur bereits im Dispatcher verwendeten
     `reservation`-Logik passen (der `reservation`-Parameter wird nur bei
     aktivem Kalender-Sync übergeben — siehe vorhandener Marker-Pfad).

3. **`src/ui.py` — `_cell_hover` und `_empty_hover`**
   Zusätzlich zu `_reservation_marker` auch `_delete_button` einsammeln und beim
   Hover dessen `bg` mitfärben (sonst bleibt ein andersfarbiges Rechteck hinter
   dem Glyph stehen). Wichtig: nur `bg` setzen, **nicht** `fg` — die `fg` steuert
   der eigene `<Enter>`/`<Leave>`-Handler des Buttons (Rot beim Symbol-Hover).

4. **`src/dialogs/entry_dialog.py` — macOS-Ausnahme entfernen**
   `_SHOW_DELETE_IN_DIALOG` auf `False` setzen bzw. die Konstante und die beiden
   davon abhängigen Lösch-Button-Blöcke (`delete_ist`, `delete_reservation`)
   entfernen. Der Dialog ist dann auf **allen** Plattformen rein zum Speichern.
   Die zugehörigen Kommentare/Docstrings (Dialog „außer macOS") anpassen.

5. **`CLAUDE.md` — Doku aktualisieren**
   Abschnitt „Kalender-Interaktion / Plattform-Ausnahme macOS" anpassen: Die
   macOS-Ausnahme ist nicht mehr „Lösch-Buttons im Dialog", sondern „✕-Button
   oben links in der Tageszelle".

## Fehlerbehandlung / Edge Cases

- **Stray-Click nach Dialog-Schluss:** `_delete_day` ist bereits über
  `_stray_click_suppressed` abgesichert — der Button erbt diesen Schutz, da er
  denselben Pfad nutzt. Keine zusätzliche Behandlung nötig.
- **Hover-Rechteck:** Durch die `_delete_button`-Behandlung in den Hover-Helfern
  vermieden (siehe Punkt 3).
- **Zerstörte Widgets / after-Callbacks:** unverändert; der Button hängt am
  Zell-Lebenszyklus wie der Marker.

## Tests

- Die Lösch-*Logik* (`_delete_action`, Auswahl, Slot-Erhalt) ist bereits durch
  bestehende Tests (`tests/test_click_guard.py` u. a.) abgedeckt und wird nicht
  verändert — der Button ist nur ein weiterer Auslöser desselben Pfads.
- Tkinter-Widget-Aufbau wird im Projekt nicht automatisiert getestet (CI ohne
  Display). Verifikation des Buttons: Import-Smoke (Modul lädt) + **manueller
  Test auf macOS** (Sichtbarkeit nur bei löschbaren Tagen, Position, Hover-Farbe,
  Klick löst Auswahl-/Bestätigungsdialog aus, kein paralleler Bearbeiten-Dialog).
- Falls eine kleine pure Prüfung sinnvoll ist: die Sichtbarkeitsbedingung
  (`macOS and (entry or aktive reservation)`) ließe sich als reine Funktion
  auslagern und testen; optional, da trivial.

## Bewusst nicht enthalten (YAGNI)

- Kein Hover-Reveal (Button ist immer sichtbar, wenn löschbar).
- Kein eigener Lösch-Button pro Slot direkt in der Zelle — die Slot-Auswahl
  bleibt im bestehenden `themed_ask_delete_choice`-Dialog.
- Keine Änderung am Win/Linux-Verhalten.
- Kein neuer Theme-Token, kein Badge-Hintergrund.
