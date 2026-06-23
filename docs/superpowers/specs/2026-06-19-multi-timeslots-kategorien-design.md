# Mehrere Timeslots pro Tag mit benutzerdefinierten Kategorien

**Issue:** margenheld/Zeiterfassung#53
**Datum:** 2026-06-19
**Status:** Design abgenommen, bereit für Implementierungsplan

## Ziel

Pro Tag sollen statt genau **einer** Arbeitszeit **mehrere Timeslots** erfassbar sein,
jeder einer **benutzerdefinierten Kategorie** zugeordnet (z.B. „Büro", „Homeoffice",
„Kundentermin"). Gleiches gilt für **Reservierungen** (geplante Soll-Zeiten). Kategorien
pflegt der Nutzer selbst in den Settings. Über einen Zeitraum lässt sich gezielt nach
Kategorie aufsummieren, und beim Senden/Teilen können Kategorien gefiltert werden.

**Backwards-Compatibility ist Pflicht.** Hatte der Nutzer vorher keine Kategorien/mehreren
Slots, verhält sich alles wie vor der Migration: ein Tag = ein Slot mit leerer Kategorie.

## Leitentscheidungen (abgenommen)

1. **Sync-Granularität:** Der **Tag bleibt die Sync-/Konflikt-Einheit.** Der Eintragswert
   wird eine Slot-Liste. LWW-Merge vergleicht die ganze Liste; ein Konflikt ist weiterhin
   ein Tages-Konflikt. Kein Slot-level-Sync (bewusst YAGNI — vervielfachte Komplexität ohne
   realen Nutzen für ein persönliches Tool mit wenigen Geräten).
2. **Kategorie-Modell:** Der Slot speichert den Kategorie-**Namen als String**. Die
   Settings-Liste ist nur die Pickliste/Vorschlagsliste. Folgen: leer (`""`) = keine
   Kategorie = Verhalten wie heute; der Name reist mit dem Slot, daher kann „Kategorie
   existiert auf Gerät X nicht" konstruktiv nicht auftreten; ein Slot bleibt lesbar, auch
   wenn die Kategorie später aus der Pickliste entfernt wird.
3. **Pause** wird **pro Slot** geführt (jeder Ist-Zeit-Slot hat eigene Pause).
4. **Report:** voller Kategorie-Nutzen — Zeile pro Slot mit Kategorie-Spalte, Tages-Subtotal,
   KW-Summen, plus „Summe je Kategorie"-Block; Kategorie-Filter im Sende-/Teilen-Dialog.
5. **Non-Overlap:** Slots eines Tages dürfen sich **zeitlich nicht überlappen** — getrennt
   geprüft innerhalb der Ist-Zeit-Slots bzw. innerhalb der Reservierungs-Slots. Ist-Zeit und
   Reservierung dürfen sich (wie heute) am selben Tag überlagern. Gleiche Kategorie mehrfach
   zu verschiedenen, nicht-überlappenden Zeiten ist erlaubt und summiert sich.
6. **Löschen:** Rechtsklick auf eine Tageszelle bleibt das Lösch-Modell (CLAUDE.md).
   Der Bestätigungs-/Auswahl-Dialog zeigt **nur die am Tag tatsächlich vorhandenen Arten**
   (Arbeitszeit / Reservierung), differenziert wie heute. Einzelne Slots entfernt man im
   Links-Klick-Dialog durch Entfernen der Slot-Zeile + Speichern (Editieren, kein zweiter
   Löschpfad auf Win/Linux).
7. **Umfang:** Ein Branch, ein PR, intern in eigenständig verifizierte Arbeitspakete
   zerlegt. Reservierungen + Multi-Event-gcal sind **enthalten** (nicht abgespalten).

## Datenmodell

### Storage (`src/storage.py`)

Tag bleibt Sync-Einheit, Wert wird eine Slot-Liste:

```jsonc
"2026-06-19": {
  "slots": [
    {"start": "08:00", "end": "12:00", "pause": 0,  "kategorie": "Büro"},
    {"start": "13:00", "end": "17:00", "pause": 30, "kategorie": "Homeoffice"}
  ],
  "modified_at": "...", "device_id": "...", "deleted": false
}
```

- Slot-Schema: `{start, end, pause, kategorie}`. `kategorie` ist ein String, `""` = keine.
- `_REQUIRED_ENTRY_KEYS` → `{slots, modified_at, device_id, deleted}`.
- `_user_shape(entry)` → `{slots: [...]}` (Liste der reinen Slot-Dicts ohne Metadaten).
- `save(date, slots)` ersetzt die Tages-Signatur (`start, end, pause` → `slots`).
- `save_many(updates)`: `updates = {date: {slots: [...]}}`.
- `delete(date)`: Tombstone mit `slots: []`, `deleted: True`.
- `apply_merge`: Required-Key-Validierung auf neues Schema.

### Reservierungen (`src/reservations.py`)

Analog, **`gcal_event_id` pro Slot**:

```jsonc
"2026-06-25": {
  "slots": [
    {"start": "09:00", "end": "17:00", "kategorie": "Kundentermin", "gcal_event_id": null}
  ],
  "modified_at": "...", "deleted": false
}
```

- Slot-Schema: `{start, end, kategorie, gcal_event_id}` (kein `pause` bei Reservierungen,
  wie heute).
- `_REQUIRED_RESERVATION_KEYS`, `save`, `delete`, `apply_reconciled` analog zu Storage.

### Migration (idempotent)

Beim Laden, analog zu `Storage._migrate_legacy_entries` / dem Settings-Migrationsmuster:

- **Erkennung:** Hat ein Eintrag bereits einen `"slots"`-Key → schon migriert, unberührt.
- **Lebender Alt-Eintrag** `{start, end, pause, ...}` → `{slots: [{start, end, pause,
  kategorie: ""}], ...}` (Metadaten bleiben).
- **Alt-Tombstone** (`deleted: true`, `start: null`) → `{slots: [], deleted: true, ...}`.
- **Reservierungen:** Alt `{start, end, gcal_event_id, ...}` → `{slots: [{start, end,
  kategorie: "", gcal_event_id}], ...}`; Alt-Tombstone → `{slots: []}`.

Migration läuft rein lokal beim Laden; sie schreibt nicht selbst auf Platte, sondern wird
beim nächsten regulären Save persistiert (wie das bestehende Muster).

## Kategorien (Settings)

- Neuer Setting-Key `categories` = `list[str]`, Default `[]`. Reine Pickliste/Vorschläge,
  keine Stundensätze o.ä.
- In den Drive-Sync aufgenommen: `categories` zu `SYNCED_SETTING_KEYS` in **beiden** Stellen
  (`src/settings.py` *und* dem Duplikat in `src/sync.py`). Der Wert ist ein String-Array →
  `_values_equal_setting` (Vergleich per `==`) funktioniert ohne Änderung.
- `_coerce` in `settings.py` muss einen `list`-Default unterstützen (Listen-Typ als neuer
  Coerce-Fall; Nicht-Listen → Default).
- Verwaltung im `settings_dialog.py`: anlegen / umbenennen / entfernen. Umbenennen ändert
  **nicht** rückwirkend Slots (Slots tragen den Namen-String; Umbenennen passt nur die
  Pickliste an). Das ist akzeptiert und konsistent mit dem Name-am-Slot-Modell.

## Validierung (`src/time_utils.py`)

- Pro Slot wie heute: `validate_entry(start, end, pause)` — Ende > Start, Pause < Dauer.
- **Neu:** Hilfsfunktion, die eine Slot-Liste auf **zeitliche Überlappungsfreiheit** prüft
  (nach Start sortieren, benachbarte Paare vergleichen). Getrennt für Ist-Zeit-Slots und
  Reservierungs-Slots aufgerufen. Liefert (ok, Fehlermeldung) für die Dialog-Anzeige.
- Stundenberechnung: `calculate_hours` bleibt pro Slot; Tagessumme = Summe über Slots.

## Sync (`src/sync.py`) — `SCHEMA_VERSION` 2 → 3

- `_values_equal_entry(a, b)`: vergleicht statt `start/end/pause` jetzt die **Slot-Liste**
  (reihenfolge-normalisiert, z.B. nach `start` sortiert, Feld-für-Feld) **und** `deleted`.
- Day-level-LWW (`_merge_one`), Konflikt-Dedup, Watermark/Tombstone-Kompaktierung,
  Self-Heal (Regel 1/2) bleiben **strukturell unverändert** — sie operieren weiter pro Datum.
- **Konflikte (bewusst minimal gehalten):** Kandidaten (`_strip_for_candidate`) tragen die
  Slot-Liste. `resolve_conflict` (kind=`entry`) und der Resolution-Apply-Block in `merge()`
  schreiben eine **Slot-Liste** statt `{start, end, pause}`. `chosen_value` für Entry-Konflikte
  wird `{slots: [...], deleted?}`.
  > **Hinweis:** Der Konflikt-Auflösungs-Flow wird voraussichtlich demnächst überarbeitet.
  > Deshalb hier nur die minimal nötige Anpassung (Slot-Liste durchreichen), **keine** neuen
  > tiefen Annahmen über Konflikt-UI/-Granularität verankern.
- **Alt-Client-Schutz (Issue-Frage 5):** Neue Funktion `_remote_is_pre_v3(remote_doc)`
  analog zum bestehenden `_remote_is_pre_v2`. Sieht ein v3-Client ein v2-(oder älteres)-
  Remote-Doc — also ist gerade ein noch nicht aktualisiertes Gerät aktiv —, wird **die
  Kompaktierung ausgesetzt** und der Sync-Pfad zeigt einen Hinweis: „Ein anderes Gerät nutzt
  eine ältere Version — bitte dort aktualisieren, bevor Mehrfach-Slots verwendet werden."
  1-Slot-Tage bleiben dabei wire-lesbar; Multi-Slot-Tage versteht ein Alt-Client nicht
  korrekt. Voller bidirektionaler Cross-Version-Erhalt ist **bewusst nicht** Ziel
  (Over-Engineering für ein persönliches Tool) — die Empfehlung lautet: alle Geräte updaten.
- `build_local_doc` / `apply_merged_doc` unverändert in der Struktur (sie reichen
  `storage.get_all_raw()` bzw. das Merge-Ergebnis durch).

## Dialoge

### `src/dialogs/entry_dialog.py` — dynamische Slot-Zeilen

- Ist-Zeit **und** Reservierung werden je eine **Liste von Slot-Zeilen**.
- Slot-Zeile (Ist-Zeit): Start / Ende / Pause / **Kategorie** (editierbare Combobox, Werte
  aus `settings.categories` + Freitext) / „× entfernen".
- Slot-Zeile (Reservierung): Start / Ende / **Kategorie** / „× entfernen".
- „+ Slot hinzufügen"-Button je Block.
- Speichern: validiert alle Slots (pro Slot + Non-Overlap je Block) und schreibt die Liste
  via `storage.save(date, slots)` bzw. `reservation_store.save(date, slots)`; danach
  `trigger_reconcile()` für Reservierungen wie heute.
- Slot-Zeile entfernen + Speichern = Editieren (kein zweiter Löschpfad → CLAUDE.md-konform).
- Der erste Slot eines neuen Tages füllt Start/Ende/Pause aus den Per-Wochentag-Defaults
  (`default_start_{day}` etc.) wie heute.
- macOS (`_SHOW_DELETE_IN_DIALOG`) behält seine Lösch-Buttons; diese löschen die jeweilige
  **Art komplett** (alle Ist-Zeit-Slots bzw. alle Reservierungs-Slots).

### `src/dialogs/send_dialog.py` — Kategorie-Filter

- Zusätzlich zur Von/Bis-Auswahl eine **Mehrfachauswahl der Kategorien** (Default: alle
  ausgewählt; Quelle = im Zeitraum vorkommende Kategorien + `settings.categories`).
- Die Auswahl wird an `generate_report` / `generate_pdf` durchgereicht (Filter auf Slot-Ebene).

### `src/dialogs/settings_dialog.py` — Kategorie-Verwaltung

- Neue Sektion (eigene collapsible Section, analog „Mail-Vorlage") zum Pflegen der
  `categories`-Liste: Hinzufügen (Eingabe + Button), Umbenennen, Entfernen.

## Report (`src/report.py`)

- Tabelle: **eine Zeile je Slot** mit Spalten `Datum | Tag | Kategorie | Start | Ende |
  Stunden`. Bei einem Tag mit >1 Slot eine **Tages-Subtotal-Zeile**; KW-Summen wie heute.
- Am Ende ein **„Summe je Kategorie"-Block** über den ausgewählten Zeitraum (Kategorie →
  Gesamtstunden), `""`/keine Kategorie als „(ohne Kategorie)".
- **Kategorie-Filter:** `generate_report` / `generate_pdf` nehmen eine optionale
  Kategorie-Auswahl; `_filter_entries` filtert zusätzlich Slots, deren Kategorie nicht in der
  Auswahl ist (Default: alle Kategorien).
- `_entry_hours` / Tages- und KW-Summen summieren über (gefilterte) Slots.
- Beide Pfade (HTML `generate_report`, PDF `generate_pdf`) konsistent.

## Teilen (`src/share.py`) — Schema v3

- Neues Wire-Format v3:
  ```jsonc
  {
    "schema_version": 3, "kind": "zeiterfassung-share", "exported_at": "...", "exported_by": "...",
    "entries":      {"YYYY-MM-DD": {"slots": [{"start","end","pause","kategorie"}]}},
    "reservations": {"YYYY-MM-DD": {"slots": [{"start","end","kategorie"}]}}
  }
  ```
- **Export:** respektiert die Kategorie-Auswahl (nur passende Slots), `include_entries` /
  `include_reservations` wie heute.
- **Import:** Diff/Konflikt-Anzeige wie heute, aber auf Slot-Listen-Ebene
  (`_entries_equal` / `_reservations_equal` vergleichen Slot-Listen).
- **Abwärtskompat:** v1/v2-Dateien bleiben importierbar — beim Lesen werden ihre
  `{start,end,pause}` / `{start,end}` in 1-Slot-Listen (`kategorie:""`) gewrappt. v3-Validierung
  prüft Slot-Listen (`_validate_entries` / `_validate_reservations` angepasst).

## UI (`src/ui.py`)

- `_build_entry_cell`: bei mehreren Slots **kompakte Darstellung** — Tagessumme bleibt
  führend; angezeigt wird z.B. die erste Zeit plus „+N" (N = weitere Slots), der **Tooltip**
  listet alle Slots inkl. Kategorie. `_entry_hours` summiert über Slots.
- `_refresh_month` / Footer-Summen summieren über Slots.
- `_delete_day` (Rechtsklick): erweiterter Auswahl-Dialog, der **nur die am Tag vorhandenen
  Arten** zeigt (Arbeitszeit / Reservierung), differenziert wie heute (`themed_ask_delete_choice`
  bzw. einfacher Ja/Nein, wenn nur eine Art existiert). Löscht die gewählte(n) Art(en) komplett
  (= ganze Slot-Liste der Art).
- Reservierungs-Marker (violetter Eckpunkt) bleibt; Tooltip listet die Reservierungs-Slots.

## gcal (`src/gcal.py` + `src/reservations_sync.py`) — mehrere Events pro Tag

- Pro Reservierungs-Slot **ein** Kalender-Event, identifiziert über `gcal_event_id` **pro Slot**.
- `event_payload`: Event-Titel trägt die Kategorie, z.B. „Arbeitszeit (reserviert) — {Kategorie}"
  (ohne Kategorie wie heute „Arbeitszeit (reserviert)"). App-Marker (`extendedProperties.private`)
  unverändert.
- `merge_reservations` / `reconcile_reservations` rechnen von „pro Tag" auf „pro Slot im Tag" um:
  - **Matching** lokaler Slots ↔ Remote-Events über `gcal_event_id`.
  - Neuer Slot (event_id `null`) → `create_event`, gesetzte event_id zurückschreiben.
  - Entfernter Slot (lokal weg, Event noch da) → `delete_event`.
  - Geänderter Slot (Zeit/Kategorie) → `update_event`.
  - LWW pro Slot über `modified_at` des Tages (Tag bleibt Zeitstempel-Träger; Slot-Änderungen
    aktualisieren `modified_at` des Tages, wie heute der Save).
- `list_app_events` / `parse_event` unverändert in der Form (liefern weiter pro Event ein
  `{date, start, end, modified_at, event_id}`); die Zuordnung mehrerer Events zum selben Datum
  übernimmt der Reconcile.

## Arbeitspakete

Ein Branch (`feat/multi-timeslots-kategorien`), ein PR. Intern in eigenständig verifizierte
Pakete zerlegt; jedes Paket endet mit grünen Tests. Lokaler Test vor dem PR.

1. **Datenmodell + Migration** — `storage.py`, `reservations.py` + Tests.
2. **Sync v3 + Kategorien-Setting** — `sync.py` (`SCHEMA_VERSION`, `_values_equal_entry`,
   Konflikt-Durchreichung, `_remote_is_pre_v3`), `settings.py` (+ Duplikat `SYNCED_SETTING_KEYS`,
   `categories`-Default, list-Coerce) + Tests.
3. **entry_dialog Multi-Slot** + `time_utils`-Validierung (Non-Overlap) + Tests.
4. **report + send_dialog** (Kategorie-Spalte, Tages-Subtotal, „Summe je Kategorie", Filter) + Tests.
5. **share v3** (Export/Import + Filter, v1/v2-Kompat) + Tests.
6. **ui.py** (Zellen-Rendering, Rechtsklick-Löschen) + **settings_dialog** (Kategorie-Verwaltung) + Tests.
7. **gcal + reservations_sync** (Multi-Event pro Tag, Slot-Event-Mapping) + Tests.

Reihenfolge ist die Default-Abfolge (Fundament → außen); der Implementierungsplan kann sie
verfeinern. Pakete 1–2 sind harte Voraussetzung für die übrigen.

## Tests

Alle betroffenen Pfade haben Tests, die heute auf dem Ein-Eintrag-Modell beruhen
(`tests/`). Pro Paket:

- Bestehende Tests auf das Slot-Schema umstellen (nicht löschen — anpassen).
- **Migrations-Tests:** Alt-Eintrag/Alt-Tombstone → 1-Slot; idempotent bei erneutem Laden.
- **Non-Overlap-Tests:** überlappende Slots werden abgelehnt; angrenzende (Ende==Start) erlaubt.
- **Sync-Tests:** Slot-Listen-Gleichheit, Tages-Konflikt mit Slot-Kandidaten, `_remote_is_pre_v3`
  setzt Kompaktierung aus.
- **Report-Tests:** Zeile/Slot, Tages-Subtotal, Kategorie-Summen, Kategorie-Filter.
- **Share-Tests:** v3-Roundtrip, v1/v2-Import wird zu 1-Slot gewrappt.
- **gcal-Tests:** mehrere Events/Tag erzeugen/aktualisieren/löschen, Matching über event_id.

CI installiert weiter nur `pytest`+`holidays` (kein `requirements.txt`); `xhtml2pdf`-Import in
`report.py` bleibt lazy.

## Offene Punkte / bewusst nicht gelöst

- **Cross-Version-Sync** mit Alt-Clients: nur Schutz (Kompaktierung aussetzen + Hinweis), kein
  bidirektionaler Multi-Slot-Erhalt. Empfehlung „alle Geräte updaten".
- **Konflikt-Flow** wird voraussichtlich überarbeitet — Multi-Slot greift dort minimal ein.
- **Kategorie-Umbenennen** wirkt nicht rückwirkend auf bestehende Slots (Name-am-Slot-Modell).
