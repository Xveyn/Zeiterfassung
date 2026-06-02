# Design: Reservierungen beim Teilen mitschicken

**Datum:** 2026-06-02
**Status:** Entwurf (genehmigt zur Planung)

## Ziel

Das bestehende Feature „Arbeitszeiten teilen" (Gmail-Anhang, `share.py` /
`share_dialog.py` / `import_dialog.py`) wird erweitert, sodass der Nutzer
**Arbeitszeiten, Reservierungen oder beides** verschicken kann. Beim Import kann
der Empfänger beide Datentypen mit der gewohnten Konflikt-Behandlung übernehmen.

### Nicht-Ziel / bewusst verworfen

Direkter Datei-Austausch über Google Drive wurde geprüft und **verworfen**:

- Der bestehende Drive-Code (`drive.py`) nutzt den `appDataFolder`-Scope
  (`drive.appdata`). Diese Dateien sind pro Nutzer + pro App isoliert und lassen
  sich technisch **nicht** mit einem fremden Google-Account teilen.
- Echtes Drive-Sharing bräuchte einen neuen, breiteren Scope (`drive.file`),
  einen Permission-Handshake (Empfänger-Mail → `permissions.create`) und müsste
  die File-ID/den Link trotzdem per Mail übertragen.
- Für ein **einmaliges Teilen** ersetzt Drive den „etwas verschicken"-Schritt
  also nicht, sondern fügt nur Scope- und Rechte-Komplexität hinzu. Der
  vorhandene Gmail-Anhang ist schlanker und bereits „nahtlos".

Drive würde sich nur für einen **dauerhaft geteilten Live-Stand** lohnen — ein
deutlich größeres Feature, das hier nicht gewünscht ist.

## Kontext (Ist-Zustand)

| Mechanismus | Modul | Transport | Inhalt |
|---|---|---|---|
| Teilen | `share.py`, `share_dialog.py` | Gmail-Anhang | nur `entries` (start/end/pause) |
| Reservierungen | `reservations.py`, `reservations_sync.py` | Google **Kalender** (LWW) | {start, end} |
| Multi-Device-Sync | `sync.py`, `drive.py` | Drive `appDataFolder` | entries + settings + conflicts |

- Reservierungen werden aktuell **nicht** geteilt — das Share-Doc enthält nur
  `entries`.
- Reservierungen sind im UI nur „aktiv", wenn `gcal_enabled` an ist
  (`ui.py::_reservations_active`).
- Der Teilen-Dialog (`ui.py:1098`) und der Import-Dialog
  (`settings_dialog.py:459`) bekommen aktuell nur `storage`, **nicht** den
  `reservation_store`.

## Entwurf

### 1. Wire-Format (`share.py`, `schema_version` 1 → 2)

```jsonc
{
  "schema_version": 2,
  "kind": "zeiterfassung-share",
  "exported_at": "<UTC-ISO>",
  "exported_by": "<email or empty>",
  "entries":      { "YYYY-MM-DD": { "start": "HH:MM", "end": "HH:MM", "pause": int>=0 } },
  "reservations": { "YYYY-MM-DD": { "start": "HH:MM", "end": "HH:MM" } }
}
```

- `entries` und `reservations` sind **beide optional**, aber mindestens eines
  muss vorhanden und nicht-leer sein.
- Reservierungen haben **keine** `pause`. Schema exakt `{start, end}`.
- `schema_version` steigt auf `2`. Die bestehende strikte Versionsprüfung in
  `parse_share_doc` sorgt dafür, dass eine ältere App eine v2-Datei mit
  „Diese Datei wurde mit einer neueren Version erstellt. Bitte App
  aktualisieren." ablehnt — gewünschtes Verhalten.

#### Validierung (`parse_share_doc`)

- `schema_version` wird **lesend abwärtskompatibel** akzeptiert: `1` und `2`
  sind gültig; `>2` → „neuere Version" (Update nötig); `<1` / `0` →
  „unbekannte schema_version".
  - **v1:** `entries` ist Pflicht (wie bisher), `reservations` existiert nicht.
  - **v2:** `entries` und `reservations` beide optional, mindestens eines
    nicht-leer.
  - Geschrieben werden ausschließlich v2-Dateien. Die v1-Akzeptanz dient nur
    dem Import bereits verschickter Alt-Dateien (keine Regression).
- `entries` (falls vorhanden) wird wie bisher validiert.
- `reservations` (nur v2, falls vorhanden) analog, aber mit Schlüssel-Set
  `{start, end}` (Datums-Regex, Zeit-Regex, `datetime`-Parse-Check).
- Bei v2: fehlen **beide** Felder oder sind beide leer → `ShareValidationError`
  („Datei enthält weder Arbeitszeiten noch Reservierungen.").

### 2. Diff-Engine generalisieren (`share.py`)

`diff_share_against_local` wird auf eine record-typ-neutrale Kernfunktion
gehoben. Parameter: die zu vergleichenden Share-Records, ein lokaler
Snapshot (`{date: record}`), eine Gleichheits-Funktion, sowie `date_from` /
`date_to`. Rückgabe unverändert: `additions`, `conflicts`, `untouched`,
`out_of_range`.

- **Arbeitszeiten:** Gleichheit über start/end/pause (bestehende
  `_entries_equal`), lokaler Snapshot aus `storage.get_all()`.
- **Reservierungen:** Gleichheit über start/end, lokaler Snapshot aus
  `reservation_store.get_all()` (liefert bereits `{date: {start, end}}` ohne
  Tombstones).

Die bestehende öffentliche Funktion `diff_share_against_local(share_entries,
storage, …)` bleibt als dünner Wrapper erhalten (Arbeitszeiten), damit
bestehende Tests/Aufrufer unverändert funktionieren.

#### Apply

- `apply_import(storage, decisions)` — unverändert (Arbeitszeiten via
  `storage.save_many`).
- **Neu** `apply_reservation_import(reservation_store, decisions)` — ruft pro
  Decision `reservation_store.save(date, start, end)` auf. Das setzt
  `modified_at` auf jetzt, `deleted=False`, und behält eine vorhandene
  `gcal_event_id`. Der nächste Kalender-Reconcile pusht die Reservierung dann.

### 3. Send-Dialog (`share_dialog.py`)

- `open_share_dialog` bekommt zusätzlich `reservation_store` (kann `None` sein).
- Zwei Checkboxen: **☑ Arbeitszeiten** / **☑ Reservierungen**.
  - Arbeitszeiten-Box nur aktiv/angeboten, wenn `storage.get_all()` nicht leer.
  - Reservierungs-Box nur aktiv/angeboten, wenn `reservation_store` vorhanden
    und `reservation_store.get_all()` nicht leer. (Keine harte Bindung an
    `gcal_enabled` — wer Reservierungen im Store hat, darf sie teilen.)
  - Default: vorhandene Typen angehakt.
  - Mindestens eine Box muss angehakt sein, sonst Fehlermeldung.
- Das Share-Doc wird je nach Auswahl gebaut (`entries` und/oder `reservations`).
- Betreff/Body passen sich an die Auswahl an („Arbeitszeiten und
  Reservierungen" / nur „Arbeitszeiten" / nur „Reservierungen").
- Wenn weder Einträge noch Reservierungen existieren → frühe Info-Meldung wie
  bisher („Nichts zum Teilen vorhanden.").

### 4. Import-Dialog (`import_dialog.py`) — symmetrisch

Der Dialog erkennt anhand des geparsten Docs, welche Typen vorhanden sind, und
zeigt **pro vorhandenem Typ einen Abschnitt** mit demselben Funktionsumfang wie
heute für Arbeitszeiten:

- gemeinsamer **Zeitraum-Filter** oben (gilt für beide Typen),
- pro Typ eine **Counts-Zeile** (neue / Konflikte / identisch / außerhalb),
- pro Typ **Konflikt-Modi** (alles Import / alles lokal / pro Tag),
- pro Typ ein **Pro-Tag-Modal** (`_PerDayDialog`) bei Modus „pro Tag".

„Weiter" verarbeitet zuerst Arbeitszeiten, dann Reservierungen (jeweils inkl.
etwaigem Pro-Tag-Modal), und wendet danach beide an. Wird ein Pro-Tag-Modal
abgebrochen, passiert insgesamt nichts (atomar pro Typ; Abbruch = kein Apply).

- `open_import_dialog` bekommt zusätzlich `reservation_store` (kann `None`
  sein). Ist es `None` (z.B. Plumbing-Fallback), wird der Reservierungs-Abschnitt
  nicht angeboten und Reservierungen aus der Datei werden ignoriert.
- Das `_PerDayDialog` wird leicht generalisiert, sodass es auch Records ohne
  `pause` darstellen kann (Reservierungs-Zeile zeigt nur `start—end`).
- Dialog-Titel wird neutraler: „Daten importieren" statt „Arbeitszeiten
  importieren". Der Menü-Button in den Settings analog („Daten importieren…").

### 5. Empfänger ohne Kalender-Sync (`gcal_enabled` aus)

Enthält die Datei Reservierungen und der Empfänger hat `gcal_enabled` aus:

- Die Reservierungen werden **trotzdem** in den `reservation_store` geschrieben
  (verlustfrei).
- Es erscheint ein **Hinweis**: „Reservierungen werden sichtbar und mit dem
  Kalender abgeglichen, sobald der Google-Kalender-Sync in den Einstellungen
  aktiviert ist."
- Kein stilles Verwerfen.

### 6. Plumbing

- `ui.py::_share` → `open_share_dialog(..., reservation_store=self.reservation_store)`.
- `ui.py` (Settings-Aufruf, ~Z. 515) → `open_settings_dialog(...,
  reservation_store=self.reservation_store)`.
- `settings_dialog.open_settings_dialog` nimmt `reservation_store=None` entgegen
  und reicht es an `open_import_dialog` weiter.

Hinweis: Die Dialoge erhalten den Store **unkonditioniert** (nicht über
`_reservations_active` gefiltert), damit Import bei Kalender-Sync-aus weiterhin
verlustfrei funktioniert (siehe Punkt 5). Die Send-Seite blendet die
Reservierungs-Option dynamisch über den Store-Inhalt ein/aus.

### 7. Tests (`tests/test_share.py`)

- `build_share_doc` mit beiden Feldern, nur Arbeitszeiten, nur Reservierungen.
- `parse_share_doc`: gültiges v2 mit beiden/einzelnen Feldern; Ablehnung wenn
  beide fehlen/leer; Reservierungs-Validierung (falsche Keys, ungültige Zeit,
  `pause` in Reservierung verboten); **v1-Datei wird weiterhin akzeptiert**
  (entries-only); `>2` wird abgelehnt.
- Diff-Generalisierung: Reservierungs-Diff (additions/conflicts/untouched/
  out_of_range) gegen einen `ReservationStore`-Snapshot.
- `apply_reservation_import` schreibt in den Store, behält `gcal_event_id`,
  setzt `modified_at`.
- Bestehende Arbeitszeiten-Tests bleiben grün (Wrapper-Kompatibilität).

Die Tkinter-Dialoge bleiben — wie bisher — ohne automatisierte UI-Tests.

## Offene Punkte

Keine. Geschrieben werden nur v2-Dateien; v1-Dateien bleiben lesbar
(entries-only, keine Import-Regression); ältere Apps lehnen v2-Dateien sauber
mit „bitte aktualisieren" ab.
