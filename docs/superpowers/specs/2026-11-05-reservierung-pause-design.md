# Pause an Reservierungen — Design

Stand: 2026-11-05. Integrationsbranch: `feat/reservierung-pause` (geht nicht nach
`master`, bevor alles fertig ist; Schritte kommen als kleine PRs mit Ziel dieses
Branches).

## Anlass

Eine Reservierung ist heute eine reine Brutto-Zeitspanne (`start`, `end`,
`kategorie`). Wer für eine Woche 2 × 7:30 h und 1 × 6:30 h reserviert, jeweils mit
30 min Pause, sieht in der PWA unter „Noch ausstehend“ 21:30 h statt der
tatsächlich zu leistenden 20:00 h. Der Grund ist das Datenmodell: eine
Reservierung hat keine Pause, also hat die Rechnung nichts zum Abziehen.

## Ziele

- Ein Reservierungs-Slot trägt eine optionale **Pause** (ganze Minuten, wie bei
  Ist-Zeit-Slots). „Noch ausstehend“ in der PWA zählt **netto**
  (`Ende − Start − Pause`).
- Die Pause lässt sich am Desktop (Tages-Dialog, Reservierungs-Block), am Handy
  (Reiter „Reservierung“) und über die lokale API setzen und lesen.
- Wird aus einer Reservierung eine Ist-Zeit, übernimmt der Vorschlag die
  Reservierungs-Pause statt der Standardpause (Desktop `entry_dialog`, PWA
  `suggestedRow`).
- **Abwärtskompatibilität ist die wichtigste Eigenschaft** (s. unten). Kein
  bestehender Nutzer verliert Daten oder bekommt eine neue Fehlermeldung, weil
  nur eine der beiden Seiten aktualisiert ist.

## Nicht-Ziele

- Reservierungen fließen weiterhin in **keine** Summe, keinen Bericht, kein
  Wochenlimit und keine Pausenpflicht-Prüfung (`weekly_limit`,
  `pause_requirement`, `report`, `webhook`, `api_summary` bleiben unberührt).
- Erinnerungen (`reminders.py`, `send_reminder.py`, `mobile_reminders.py`,
  `pwa/reminders-plan.js`) lesen nur `start`/`end`/`kategorie`/
  `send_reminder_minutes` und bleiben unverändert.
- **Teilen** (`share.py`) bleibt unverändert, ohne Pause (siehe „Meine Entscheidungen“).
- Der Relay kennt keine Reservierungsdaten und ändert sich nicht.
- Der Google-Kalender-Termin zieht die Pause **nicht** von der Zeit ab (s. unten).

## Rollout: getrennt, Desktop zuerst

Die PWA ist mit dem Merge nach `master` sofort bei allen Nutzern, der Desktop
hängt hinterher (macOS ohne Selbst-Update). Deshalb zwei Stränge:

1. **Desktop-Release** (Minor, neue Funktion): nimmt `pause` an, liefert es
   zurück und meldet die Fähigkeit in der Abgleich-Antwort.
2. **PWA** erst nach diesem Release: zeigt das Pausenfeld und sendet `pause`
   nur, wenn der gekoppelte Desktop die Fähigkeit meldet.

Der Integrationsbranch wird entsprechend in zwei PR-Stränge nach `master`
zerlegt. Der Desktop-Strand enthält das Release (`src/version.py`,
`CHANGELOG.md`, `resolve_readme_version.py`, README-Marker `*(ab --VERSION--)*`).
Die PWA trägt keine eigene Version.

## Abwärtskompatibilität

Befund aus dem Code (nicht geraten):

- Ein **alter Desktop verwirft `pause` im Handy-Abgleich still**:
  `mobile_reservations._parse_day` nimmt aus `parse_slots` nur `start`, `end`,
  `kategorie`, die Antwort (`_clean_slots`) liefert kein `pause`, und die PWA
  ersetzt ihren Slot durch den Desktop-Stand (`store._applyReservations`). Eine
  neue PWA gegen einen alten Desktop würde die Pause also **kommentarlos
  verlieren**.
- Ein alter Desktop lehnt `pause` in der **lokalen API** ab (422
  `invalid_slot`).
- Eine **alte PWA** projiziert die Antwort auf drei Felder (`parseReservations`)
  und sendet nie `pause`.

Daraus folgen diese Regeln (Muster aus `pwa/CLAUDE.md`, „Kompatibilität“):

1. **Additiv, `PROTOCOL` bleibt 2.** Die Sync-Antwort trägt ein neues
   Top-Level-Feld `reservation_pause: true` (Name ist mein Vorschlag). Es steht
   nur, wenn die Reservierungen an sind. Die Reservierungs-Slots der Antwort
   tragen dann `pause` (immer, auch 0).
2. **Feature-Erkennung statt Versionsvergleich.** Die PWA blendet das
   Pausenfeld nur ein, wenn `reservation_pause` in der letzten Antwort stand
   (Meta-Flag wie `settings_writable`). Ohne das Feld: alles wie heute, Brutto,
   kein Feld, „Noch ausstehend“ unverändert.
3. **Fehlendes `pause` heißt „nicht angegeben“, nicht 0.** Sendet eine alte PWA
   einen Slot ohne `pause`, übernimmt der Desktop die bisherige Pause des Slots
   **positionsweise** (wie `send_reminder_minutes`), statt sie auf 0 zu setzen.
   Sonst würde jede alte PWA beim ersten Abgleich die am Desktop gesetzten Pausen
   löschen. Ein vorhandenes `pause` (auch 0) wird übernommen. Dasselbe gilt für
   `PUT /v1/reservations/{date}` der lokalen API.
4. **Eingefrorene Vorgänger.** Vor der Änderung wird `compat/*-pre-pause.json`
   eingefroren (Request und Response mit der heutigen Reservierungsform). Die
   PWA muss die alte Antwort weiter verstehen, der Desktop die alte Anfrage
   (`tests/test_mobile_contract.py`, `pwa/test/compat.test.js`).
5. **Persistierte Daten bleiben gültig.** Bestehende Reservierungen ohne `pause`
   laden mit 0. Die IndexedDB-`VERSION` und das Schema von `reservations.json`
   brauchen keine Migration.

Unvermeidbar und akzeptiert: ein **alter Desktop** adoptiert einen vom neuen
Desktop geschriebenen Kalendertermin beim Remote-gewinnt-Abgleich ohne Pause.
Betrifft nur Nutzer mit zwei Desktops in unterschiedlichen Versionen.

## Änderungen im Desktop

Die Stellen stammen aus einem Inventar des Codes (Dateien, nicht Zeilen, da der
Code sich bis zur Umsetzung ändert).

- `reservations.py`: `pause` im Slot-Schema (Standard 0): `_normalize_slot`,
  Migration alter Einträge, `get_all`-Projektion. **`_phone_key`** (LWW-Signatur)
  zählt `pause` mit, sonst würde eine reine Pausen-Änderung bei gleichem
  Zeitstempel als „nicht größer“ verworfen. `merge_phone` übernimmt `pause` aus
  dem Handy (Regel 3 oben für den Fall „fehlt“).
- `mobile_reservations.py`: `parse_reservations` erlaubt `pause` (Regeln der
  Ist-Zeit-Slots über `parse_slots`, `0 ≤ pause < Arbeitszeit`),
  `build_reservations`/`_clean_slots` liefern es; die Docstrings („pause gibt es
  nicht“) werden korrigiert. `mobile_sync.py` setzt `reservation_pause`.
- `api_reservation_write.py` und `api_routes.py`: `pause` im Body optional
  (statt 422), in `_wire_reservation_slots` (GET und PUT-Antwort), positionsweises
  Erben wie bei `send_reminder_minutes`.
- `dialogs/entry_dialog.py` und `slot_rows.py`: die Reservierungs-`SlotRowList`
  bekommt die Pause-Spalte (`with_pause`), `plan_entry_save` validiert mit Pause,
  `save_all` schreibt sie. Der Ist-Zeit-Vorschlag aus einer Reservierung nimmt
  deren Pause. Im Block steht ein Hinweis (s. Kalender).
- `grid_renderer._fmt_slot_line`: der Tooltip nennt die Pause, wenn sie größer
  als 0 ist.
- `gcal.py` und `reservations_sync.py`: s. nächster Abschnitt.
- `time_utils.validate_slots`: Reservierungen laufen mit `with_pause=True`.

## Google-Kalender: Termin bleibt brutto, und das sagt die App

Der Termin deckt weiter `Start–Ende` ab, die Pause wird **nicht** abgezogen
(Entscheidung des Nutzers). Das wird dem Nutzer an zwei Stellen gesagt:

- Dort, wo die Pause eingetragen wird (Desktop-Reservierungsblock, PWA-Reiter
  „Reservierung“): ein kurzer Hinweis „Der Google-Kalender-Termin zeigt die
  volle Zeitspanne, die Pause wird dort nicht abgezogen.“ — nur sichtbar, wenn
  der Kalender-Abgleich an ist (Desktop).
- Im Termin selbst: die **Beschreibung** nennt bei Pause > 0 „Zeitspanne brutto,
  Pause N min nicht abgezogen“. Der Titel bleibt unverändert (meine Entscheidung,
  der Titel ist die Zeile in der Kalenderübersicht und soll nicht länger werden).

Technisch: `gcal.event_payload` bekommt `pause` als Parameter und legt sie in
`extendedProperties.private` ab. `parse_event` liest sie. In
`reservations_sync` gilt: der **Update-Vergleich** schließt `pause` ein (sonst gäbe
es bei einer reinen Pausen-Änderung kein Update), `_adopt_remote` baut den Slot
aus dem Termin und übernimmt `pause` aus der privaten Eigenschaft, hilfsweise
über die `event_id` vom lokalen Slot (wie `send_reminder_minutes`).

## Änderungen in der PWA

- `reservations.js`: `normalizeReservationSlots` und `reservationSignature`
  führen `pause` mit; `validateReservationSlots` prüft sie wie bei Ist-Zeiten
  (Pause ≥ 0, < Arbeitszeit) statt sie auf 0 zu setzen;
  `pendingReservationMinutes` rechnet `slotMinutes({start, end, pause})` (netto).
  Der Kommentar „der Desktop lehnt jedes weitere Feld ab“ stimmt dann nicht mehr
  und wird korrigiert.
- `sync.js`: `parseReservations` übernimmt `pause` (Ganzzahl, sonst 0). Das
  Feature-Flag `reservation_pause` aus der Antwort geht in die Meta.
- `view-model.js` und `views.js`: Reiter „Reservierung“ mit Pause-Feld (`step`
  5 wie `snapPause`) **nur mit** Flag; `suggestedRow` nimmt die Pause der
  Reservierung; die Slot-Anzeige „geplant …“ nennt die Pause wie `slotText`.
  Hinweis zum Kalender-Termin.
- Ohne Flag (älterer Desktop): unverändert, ohne Feld, ohne Netto-Rechnung.
- `pwa/CLAUDE.md`: Abschnitt „Reservierungen“, „Kompatibilität“ und die
  Fixture-Liste aktualisieren.

## Tests (Auswahl, Muster der bestehenden)

- Bestehende Tests, die die alte Form festnageln, werden bewusst geändert:
  `tests/test_mobile_reservations.py` (Pause wird nicht mehr verworfen),
  `tests/test_api_reservation_write.py` (kein 422 mehr), `pwa/test/reservations.test.js`,
  `pwa/test/store.test.js`. `tests/test_share.py` bleibt unverändert (Share
  bleibt ohne Pause).
- Neu: Vertrag `reservation_pause` in `sync-response.json` (beide Seiten),
  eingefrorenes `compat/*-pre-pause.json`; alte PWA gegen neuen Desktop (Pause
  bleibt erhalten); neue PWA gegen alten Desktop (Fixture ohne Flag, kein Feld,
  nichts gesendet); `_phone_key` mit reiner Pausen-Änderung; Kalender-Payload und
  Update-Vergleich; Netto-Rechnung für das Beispiel aus dem Anlass
  (2 × 7:30 + 6:30 mit je 30 min Pause = 20:00 h).
- Geprüft wird außerdem im Dev-Setup: `scripts/pwa_devserver.py --reservations`
  gegen die echte Handy-Instanz; den Relay-Weg der PWA kann der Dev-Server nicht
  prüfen (`pwa/CLAUDE.md`), dafür `wrangler dev` mit `DEV_ORIGIN`.

## Meine Entscheidungen (zum Prüfen)

- **Teilen bleibt ohne Pause.** `share.py` lehnt unbekannte Felder streng ab
  (`_check_keys`): eine Datei mit `pause` würde bei jedem alten Empfänger
  komplett abgelehnt. Ein Schema-Bump ist für einen reinen Komfortwert zu teuer.
  Folge: eine geteilte Reservierung kommt ohne Pause an (0). *Korrektur zu meiner
  früheren Aussage:* das Share-Doc kennt Reservierungen sehr wohl, nur ohne
  Pause.
- **Name der Fähigkeit:** `reservation_pause` (Top-Level-Feld der Antwort).
- **Kalender-Titel unverändert**, Hinweis nur in der Beschreibung.
- **Grenzen der Pause:** wie bei Ist-Zeiten (ganze Minuten, kleiner als die
  Spanne; Desktop-Auswahl 0–120 in 5er-Schritten wie `PAUSE_VALUES`, PWA `step` 5).
- **Ein Pausenwert je Slot**, nicht je Tag; mehrere Slots am Tag haben je eine.
- Der Vorschlag der Ist-Zeit nimmt die Pause des **ersten** Slots (wie schon
  Start/Ende).

## Weitere Entscheidungen aus der Prüfung (meine Calls)

- **Erben nur bei unverändertem Slot.** Fehlt `pause` in einem Slot der Anfrage
  (alte PWA, alte API-Clients), übernimmt der Desktop die bisherige Pause nur,
  wenn am **selben Index** ein Slot mit gleichem `start` und `end` steht.
  Wird mitten in der Liste ein Slot eingefügt oder entfernt, erbt kein Slot eine
  fremde Pause (dann 0). Das ist strenger als `send_reminder_minutes`
  (rein positionsweise), weil eine falsche Pause die Rechnung verfälscht, eine
  falsche Erinnerung nur eine Markierung.
- **Konflikte wie bisher:** Last-Writer-Wins über den ganzen Slot/Tag
  (`_phone_key`), keine Feldlogik in `merge_phone`.
- **Fehlt `reservation_pause` in einer späteren Antwort** (Reservierungen am
  Desktop aus, Desktop zurückgestuft): die PWA behält gespeicherte Pausen,
  blendet das Feld aus und **sendet keine** Pause mehr; „Noch ausstehend“ rechnet
  mit dem gespeicherten Wert netto weiter (lokale Daten werden nie gelöscht, wie
  bei `reservations_enabled`).
- **Validierung wie bei Ist-Zeiten** (`validate_entry`): Pause ganzzahlig,
  ≥ 0, kleiner als die Arbeitszeit; was Reservierungen heute zu `end ≤ start`
  sagen, bleibt unverändert. Die lokale API antwortet bei ungültiger Pause mit
  422 `invalid_slot`. Ein von außen gesetzter Wert, der nicht in
  `PAUSE_VALUES` liegt (z. B. 37), muss im Desktop-Dialog angezeigt werden und
  den Roundtrip überleben (Combobox mit freiem Wert, wie bei der Ist-Zeit).
- **Bestehende Kalendertermine ohne `pause`-Eigenschaft** gelten als Pause 0 und
  sind gleich einer lokalen Pause 0: der erste Abgleich nach dem Release
  schreibt **keinen** Termin um. Ein neuer Remote-Termin ohne lokalen Slot
  bekommt 0.
- **Release:** Minor (1.27.0), weil neue Funktion. Schritt 0 des Desktop-Strangs
  ist das Einfrieren von `compat/*-pre-pause.json` aus dem heutigen Stand,
  **bevor** der erste PR den Vertrag ändert. Der PWA-Strang wird erst nach der
  **Veröffentlichung** des Desktop-Releases gemergt, nicht schon nach dem Merge
  des Release-PRs.
- **Erinnerungen:** geprüft, der `reminders`-Block der Antwort trägt keine
  Slot-Form (`build_block` liest nur markierte Slots für die Sende-Zeitpunkte),
  `reminders-contract.json` ändert sich nicht.

## Offen für den Bauenden

- Konkrete Texte der Hinweise.
- Reihenfolge der PRs im Desktop-Strang (Vorschlag: 1. Datenmodell und Merge,
  2. Handy-Abgleich und Vertrag, 3. lokale API, 4. Dialog und Tooltip,
  5. Kalender, 6. Release) und im PWA-Strang (1. Modell und Rechnung, 2. Abgleich
  und Flag, 3. Oberfläche).
- Ob zum Desktop-Release ein Pre-Release über alle Plattformen sinnvoll ist
  (der Kalender-Abgleich und der Dialog sind plattformübergreifend, aber der
  Release-Prozess läuft ohnehin über `release.yml`).
