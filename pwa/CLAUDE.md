# pwa/ — die Handy-PWA der Handy-Erfassung

Reines JavaScript ohne Build und ohne Abhängigkeiten (#221). Die PWA wird
**nicht** in die Desktop-App gebündelt und von keinem Python-Modul importiert;
sie läuft im Browser des Handys und spricht per HTTP mit der Handy-Instanz des
Desktops (`src/mobile_routes.py`, `src/mobile_service.py`; deren Verträge
stehen in `src/CLAUDE.md`). Diese Datei beschreibt die PWA-Seite und den
Vertrag zwischen beiden.

## Module

ES-Module flach im Ordner:

- `minutes.js` — Zeiten, Minuten, Validierung, ISO-Wochen. Summen nur über
  ganze Minuten. `snapTime`/`TIME_STEP_MINUTES`: die Zeitauswahl rastet auf **5 Minuten** wie die Auswahl am
  Desktop (`theme.palette.TIME_VALUES`): `step` 300 am `<input type="time">`, gerundet wird beim Übernehmen
  (`change`), nicht beim Tippen; bereits gespeicherte Zeiten (z. B. 08:03 vom Desktop) bleiben unverändert, bis das
  Feld geändert wird. Die Pause rastet ebenso (`snapPause`, `step` 5, Desktop: `PAUSE_VALUES`).
- `defaults.js` — Vorbelegung der Zeiten aus den Standardzeiten des Desktops
  (#288). `resolveSlotDefaults` ist das Gegenstück zu
  `category_defaults.resolve_slot_defaults`; der **Gleichlauf** hängt an
  `test/fixtures/category-defaults-cases.json`, das JS- und Python-Test lesen.
  Fehlt `defaults` in der Antwort (älterer Desktop), bleibt der Editor leer.
  Überschrieben werden nur Felder, die noch auf dem zuletzt vorbelegten Wert
  stehen, gespeicherte Slots nie.
- `reservations.js` — Reservierungen (zukünftige Soll-Zeiten) ohne DOM: wann der
  Block erscheint (`reservationBlockVisible`, Gleichlauf mit
  `reservation_block_visible` über `test/fixtures/reservation-visibility-cases.json`),
  Slot-Normalisierung und -Prüfung samt Pause (ganze Zahl ≥ 0, sonst 0; geprüft wie bei Ist-Zeiten),
  Signatur und die Netto-Rechnung für „Noch ausstehend“ (s. „Reservierungen“).
- `categories.js` — Kategorien-Verwaltung ohne DOM: Zeilen aus `categories` +
  `category_times` (`categoryRows`), zurück in den Block (`rowsToBlock`),
  Prüfung (`validateCategoryRows`), Kurzfassung der Zeiten (`timesSummary`),
  Sortieren (`moveRow`) und die Signatur zum Vergleichen (`blockSignature`).
  `per_day`-Kategorien laufen als `raw` durch und werden nie verändert (s.
  „Einstellungen und Kategorien“).
- `pairing.js` — Kopplungscode, Koppel-Link, Adressregel. `parsePairLink` erkennt beide Links: den LAN-Link
  (`#pair=…`, delegiert an `parseQrText`, Ergebnis `kind: 'lan'`) und den Relay-Link
  (`#relay=<43 Base64url>:<28 Zeichen Code>`, `kind: 'relay'`; Code schon in Großbuchstaben, kein Leerraum,
  der ganze Text höchstens 512 Zeichen). `parseQrText` bleibt unverändert und liefert für einen Relay-Link `null`.
- `relay-frame.js` — reiner Codec des Relay-Abgleichs: Nachrichtenrahmen, Nutzlast, Regeln (`isCurrentResponse`
  vergleicht die zurückgegebene Nonce `n`, nicht `seq`). Gegenstück
  `src/mobile_relay_codec.py`; der Gleichlauf hängt an `test/fixtures/relay-frames.json`.
- `store.js` — lokaler Zustand: erfasste Tage und Reservierungen (zwei
  Sammlungen), `dirty_version`/`synced_version`, Anwenden der Sync-Antwort,
  Lesefenster. Mit
  `memory-adapter.js` (Tests) und `db.js` (IndexedDB-Adapter, eine Transaktion
  je `batch`).
- `sync.js` — Client: Koppeln (`pair` im LAN, `pairRelay` über die Box), Ping, Abgleich; schickt jede
  verschlüsselte Anfrage über einen Transport. `sync-errors.js` — `SyncError` und die Einordnung der
  Server-Fehler in `SyncError.kind` (`sync.js` führt die Namen weiter aus). `transport.js` — `LanTransport`
  (HTTP im WLAN) sowie `endpointOf(meta, {onHave})`/`isPaired(meta)`: wohin eine Kopplung spricht und ob es sie gibt.
  `relay-transport.js` — `RelayTransport`, der Weg über die Box (s. „Relay-Abgleich“).
- `crypto.js` — Gegenstück zu `src/mobile_crypto.py` (WebCrypto), s.
  „Verschlüsselung“.
- `window-policy.js` — Lesefenster (#250): Stufen, Wunsch, die Entscheidung der Wochenansicht
  am Fensterrand (s. „Lesefenster“).
- `swipe-policy.js` — Wisch nach links/rechts wechselt die Woche (#381): `swipeDirection` entscheidet aus
  Start, Ende und Dauer (nur Finger/Stift, waagerecht mindestens doppelt so stark wie senkrecht, ≥ 60 px
  oder Flick ≥ 30 px in ≤ 150 ms, Start im 24-px-Randstreifen zählt nie — der gehört der System-Zurück-Geste).
  `app.js` (`watchSwipe`) bindet Pointer-Events einmal am `main`, `touch-action: pan-y` lässt das senkrechte
  Scrollen beim Browser; nur auf dem Wochen-Screen ohne offenen Dialog, ein Klick direkt nach dem Wisch wird
  verworfen. Wechsel beim Loslassen, die Woche folgt dem Finger nicht. Auf iOS ungeprüft (#358).
- `browser-policy.js` — Engine hinter dem Browser (`browserKind`: chromium / firefox / ios / safari / unknown;
  jeder Browser auf dem iPhone ist WebKit) und `blocksLan` (sperrt eine https-Seite den Zugriff auf
  `http://<LAN-IP>`?). Nur dazu, die Meldung „Desktop nicht erreichbar“ **nach** einem Fehlschlag um die
  wahrscheinliche Ursache und den Test `http://<Adresse>/v1/ping` zu ergänzen (#275, `messages.describeError(error,
  { browser, address })`); ein `fetch`-Fehler verrät den Grund nicht, vorab gewarnt wird nie.
- `sw-repair.js` — „Reparieren“ im Reiter „Updates“ (#390): den Service Worker neu einrichten, wenn Chrome ihn
  nicht starten kann („ServiceWorker cannot be started“). `repairServiceWorker` prüft **zuerst** (online, `sw.js`
  abrufbar — sonst wird nichts verändert, denn ein abgemeldeter Worker ohne Cache heißt: offline startet die
  Web-App nicht mehr), meldet dann alle Registrierungen ab, löscht nur die eigenen Caches (`zeiterfassung-pwa-*`)
  und registriert neu; danach lädt die Seite neu. Einträge und Kopplung liegen in IndexedDB und bleiben
  unberührt. Fehlerarten `offline`/`unreachable`/`unsupported`/`failed`, Texte in `describeRepair`.
- `diagnose.js` — Ursache statt nur „fehlgeschlagen“ (#383): `errorDetail` (Name + Meldung, eine Zeile,
  höchstens 240 Zeichen, Chromes Standardtext vor dem Grund eines fehlgeschlagenen `registration.update()` verdichtet), `withDetail` (Meldungstext mit der Ursache dahinter) und `logFailure`
  (`console.warn`, am Handy über `chrome://inspect` lesbar). Nur für Fehler der Browser-Schnittstellen
  (Service Worker, Push-Abo, Kamera, Speicher); `SyncError`/`RelayError` haben eigene kuratierte Texte und
  gehen hier nicht hinein — einzige Ausnahme: `relay-transport.js` loggt damit eine übergangene Relay-Antwort
  (`RelayFrameError`, nur der feste Text, nie Geheimnis oder Inhalt). Wer einen neuen Catch-all in `app.js` baut,
  loggt oder zeigt die Ursache.
- `view-model.js`, `messages.js`, `sync-policy.js`, `update-policy.js` —
  Anzeige- und Entscheidungslogik, DOM-frei und getestet.
- `reminders-plan.js`, `push-blob.js`, `push-message.js`, `relay-client.js`, `push-policy.js` —
  Benachrichtigungen (#331), DOM-frei und getestet, s. „Benachrichtigungen“.
- `qr-decode.js` — QR-Decoder in reinem JavaScript (#326), DOM-frei: Graubild rein, Text oder
  `null` raus (s. „QR-Decoder“). `scanner.js` nutzt ihn, wo der `BarcodeDetector` fehlt.
- `dom.js`, `views.js`, `scanner.js`, `app.js` — die DOM-Schicht. Sie baut
  Elemente **nur** über `createElement` und Textknoten (ein Test verbietet
  `innerHTML` & Co.; Namen, Kategorien und Fehlertexte sind Fremddaten).
- `index.html`, `app.css`, `manifest.webmanifest`, `icons/` (erzeugt von
  `scripts/pwa_icons.py` aus dem Markenbild).
- `sw.js` — Service Worker (ES-Modul) mit dem getesteten Kern `sw-core.js`:
  Cache-Name, Vorab-Cache-Liste `PRECACHE`, `shouldHandle` (nur eigene, vorab
  gecachte GET-Anfragen). **API-Antworten und Anfragen an den Desktop gehen nie
  durch den Service Worker.** Seit #331 trägt `sw.js` auch die Handler für `push`
  (zeigt **immer** eine Benachrichtigung) und `notificationclick` (öffnet die App am
  Tag), s. „Benachrichtigungen“. `sw.js` selbst ist nicht in `PRECACHE`.

`PRECACHE` und die Dateien unter `pwa/` müssen übereinstimmen: der Test
`test/shell.test.js` verlangt, dass jede Laufzeitdatei gelistet ist. Nicht
dazu zählen `test/`, `package.json`, `sw.js`, `memory-adapter.js` und
Markdown-Dateien wie diese.

## Tests

```
cd pwa && node --test
```

Der CI-Job `pwa` (`.github/workflows/test.yml`) läuft mit Node 22.

## Vertrag gegen Drift

Die JSON-Beispiele in `test/fixtures/` lesen die JS-Tests **und**
`tests/test_mobile_contract.py`: Validierung/Minuten, Code- und Adressregel,
Request/Response von `/v1/pair` und `/v1/sync`, die Liste aller Fehlercodes
(der Python-Test scannt die Server-Quellen nach `(Status, Code)`-Paaren und
verlangt sie in `errors.json`). Den Relay-Abgleich (#358) hält
`test/fixtures/relay-frames.json` zusammen: Nachrichtenrahmen, Anfrage
`{v, path, token, envelope}` und Antwort `{v, status, seq, n, body}`, Koppel-Links;
Zeilen mit `"canonical": true` sind byte-genaue Kodierer-Vektoren. Drei
Implementierungen lesen sie: `relay-frame.js` (`test/relay-frame.test.js`),
`src/mobile_relay_codec.py` (`tests/test_mobile_relay_codec.py`) und der Relay
(`relay/test/frames-contract.test.js`).

Regeln, die nur in der PWA gelten:

- Ein Koppel-Link wird nur mit privater IPv4-Adresse akzeptiert (das Fragment
  kommt aus einem QR-Code).
- `401 unauthorized` heißt ebenfalls „neu koppeln“.
- Ein `422` blockiert nur den betroffenen Tag. Mehr als 400 nicht übertragene Tage gehen in
  Päckchen zu höchstens 400 (`MAX_DAYS_PER_REQUEST`, neueste zuerst) innerhalb **eines**
  Abgleichs hinaus; scheitert ein späteres Päckchen, bleiben die vorherigen angewendet und der
  Rest „nicht übertragen“ bis zum nächsten Lauf.
- Fehlende Tage werden nur im **inneren** Lesefenster lokal gelöscht (Randtage
  gehören dem Desktop).
- **Ein gelöschter Tag sieht aus wie ein leerer Tag** (#353). Am Desktop gelöscht oder am Handy
  geleert ist ein Tombstone (`deleted: true`), der im Lesefenster bis zur Kompaktierung am Desktop
  stehen bleibt; `weekModel` macht daraus `state: 'empty'`, ohne Text und Durchstreichung. Der
  Datensatz bleibt für den Sync unverändert.

## Kompatibilität zu älteren und neueren Desktops

Die PWA kommt per Pages sofort bei jedem an, der Desktop hängt hinterher
(macOS hat kein Selbst-Update, Nutzer lassen Updates liegen). Der häufige Fall
ist also **neue PWA, alter Desktop**; der umgekehrte (gecachte alte PWA, neuer
Desktop) ist seltener, kommt aber vor. Sieben Regeln:

1. **Zwei Arten von Änderungen.** *Additiv* (ein neues Feld in Antwort oder
   Anfrage) ändert `PROTOCOL` nicht: beide Seiten ignorieren Unbekanntes und
   tolerieren Fehlendes. *Brechend* (Feld entfällt, Bedeutung ändert sich,
   Verschlüsselung) hebt `PROTOCOL`. Aktuell steht es auf `PROTOCOL` 2 —
   `pwa/pairing.js`, `src/mobile_sync.py` und `src/mobile_crypto.py` müssen
   übereinstimmen.
2. **Feature-Erkennung statt Versionsvergleich.** Die PWA fragt „ist `defaults`
   da?“, nicht „ist der Desktop ≥ 1.25?“. `desktop.version` ist nur Anzeige.
   Ein Feature, das ein neues Feld braucht, fällt ohne das Feld still auf das
   alte Verhalten zurück (so macht es `parseDefaults`: `null` statt Fehler).
3. **Brechende Änderungen nur als Expand/Contract:** erst ein Desktop-Release,
   das alt **und** neu spricht, dann die PWA mit dem Neuen, später das Alte
   entfernen. Umgekehrt ginge es nicht, weil sich der Desktop-Bestand nicht
   zwingen lässt.
4. **Eingefrorene Vorgänger.** (Das Live-Beispiel `sync-request.json` zeigt den **neuen** Vertrag inkl. `pause` an Reservierungen, das die ausgelieferte PWA noch nicht sendet; was sie heute schickt, steht in `compat/sync-request-pre-pause.json`.) `test/fixtures/compat/` enthält Kopien der
   Vertragsbeispiele zu dem Zeitpunkt, an dem die Form galt. Sie werden **nie**
   mitgezogen, wenn sich das Live-Beispiel ändert: die PWA muss die alte Antwort
   weiter verstehen (`test/compat.test.js`), der Desktop die alte Anfrage
   (`tests/test_mobile_contract.py`). Wer den Vertrag erweitert, friert die
   Form **vor** der Änderung ein. Der erste eingefrorene Stand ist das
   Protokoll 2 vor #288 (ohne `defaults`/`desktop`); Protokoll 1 war nie in
   einem echten Release. Dazu kommt der Stand vor dem Lesefenster
   (`compat/*-pre-250.json`, ohne `window_days`/`window_max_days`) und der Stand vor den
   Reservierungen (`compat/*-pre-reservations.json`, ohne `reservations`) der Stand vor den
   Einstellungen (`compat/*-pre-settings.json`, ohne `settings`) und der Stand vor dem Fenster nach
   vorn (`compat/sync-response-pre-ahead.json`, ohne `window_ahead_days`) und der Stand vor der Pause an
   Reservierungen (`compat/*-pre-pause.json`, ohne `reservation_pause` und ohne `pause` an Reservierungs-Slots;
   die PWA muss die Antwort verstehen, `test/compat.test.js`; dass ohne Flag keine `pause` auf den Draht geht, prüfen
   `test/sync.test.js` und `test/store.test.js`, den ganzen Zyklus mit der echten Handy-Instanz
   `tests/test_mobile_reservation_pause_e2e.py` über `tests/mobile_session_probe.mjs`).
   Die Fähigkeit `reservation_pause` ist Feature-Erkennung nach Regel 2: nicht „Desktop ≥ 1.27“, sondern
   „steht das Feld in der Antwort“.
5. **Neue PWA, alter Desktop.** Ein Desktop vor #311 ignoriert `settings` in der
   Anfrage und kennt `writable_settings` nicht. Die PWA bietet das Bearbeiten
   der Kategorien deshalb nur an, wenn die Antwort `writable_settings` mit
   `categories` und `category_times` nennt; sonst sind die Kategorien lesbar,
   aber nicht bearbeitbar (Hinweis „Desktop aktualisieren“). Das Feld statt
   „Antwort ohne `category_times`“, weil `defaults.category_times` schon seit
   #288 existiert und ein Desktop davor/danach nichts über das Schreiben sagte.
   Die IndexedDB-`VERSION` bleibt 2: der Block liegt in der Meta, kein neuer
   Object Store.
6. **Die Meldung nennt die ältere Seite.** Antwortet der Desktop auf einen
   falschen Umschlag mit `invalid_protocol`, steht im Klartext-Fehler
   `supported_protocol`; daraus macht `messages.js` „Desktop-App ist älter“
   (Desktop aktualisieren) bzw. „Desktop-App ist neuer“ (Seite neu laden). Die
   Zahl kommt im Klartext und ist nur ein Hinweis, kein Beleg. Fehlt sie
   (Desktop vor dieser Änderung), bleibt der allgemeine Text.
7. **Ein älterer Desktop wird angezeigt.** Schickt er weder `desktop` noch
   `defaults`, sagt der Reiter „Verbindung“ der Einstellungen das (`desktopHint`).

## Reservierungen

Reservierungen sind zukünftige Soll-Zeiten, eine **eigene Sammlung** neben den
Ist-Zeiten (Object Store `reservations`, IndexedDB `VERSION` 2; Schlüssel =
Datum, gleiche Felder `dirty_version`/`synced_version`/`error`). Der Desktop
bietet sie nur an, wenn „Reservierungen verwenden“ an ist.

- **Feature-Erkennung.** Trägt die Antwort ein Feld `reservations`, ist die
  Funktion an (Meta `reservations_enabled`); fehlt es (Reservierungen am
  Desktop aus, oder ein Desktop vor #309), bleibt alles verborgen — **lokale
  Reservierungen werden dabei nie gelöscht**, nicht übertragene gehen beim
  Wiedereinschalten hinaus. `parseReservations` liefert dafür `null`.
- **Form auf dem Draht** wie in der Anfrage des Desktops:
  `{ISO: {slots: [{start, end, kategorie, pause}], modified_at, deleted}}`, ohne
  `device_id`; `pause` sind Minuten (#455). Gesendet wird im ersten Päckchen eines
  Abgleichs und nur, wenn welche nicht übertragen sind.
- **Pause nur mit Fähigkeit** (#455). Die Antwort trägt `reservation_pause: true`, wenn der Desktop
  `pause` an Reservierungs-Slots versteht (Meta `reservation_pause`, bei jeder Antwort neu gesetzt;
  `PROTOCOL` bleibt 2). Ein älterer Desktop lehnt `pause` nicht ab, **verwirft sie aber still**
  (er liest nur `start`/`end`/`kategorie`), und der pausenlose Echo-Stand ersetzt danach den Slot der PWA;
  deshalb lässt `Store.snapshotReservations` `pause` ohne das Flag weg und bietet das Eingabefeld nicht an.
  Das Flag ist erst nach der ersten Antwort bekannt: auf einer **frischen Installation** geht die erste Anfrage
  noch ohne Pause hinaus (`pairingMeta` setzt das Flag bei einer erneuten Kopplung nicht zurück, dort gilt der alte Stand).
  **Nur eine Antwort mit `reservations` ändert das Flag** (ohne `reservation_pause: true` darin: aus); fehlt der
  Block, weil Reservierungen am Desktop vorübergehend aus sind, bleibt das Flag stehen — sonst ginge eine
  nicht übertragene Pause beim Wiedereinschalten ohne Pause hinaus und käme als 0 zurück. Ehrlich zum
  Downgrade (Reservierungen an, Flag fehlt): ein noch nicht gesendeter Tag behält seine Pause lokal (nicht gesendet,
  weiter netto gerechnet), aber das nächste Echo eines pausenlosen Desktops ersetzt saubere Reservierungen durch
  Pause 0. Fehlt `pause` an einem Slot der Antwort, ist es 0.
- **Netto-Rechnung.** „Noch ausstehend“ zählt je offenem Slot Spanne minus Pause
  (`pendingReservationMinutes`, nie negativ: eine Pause ab der Spanne aus Fremddaten zählt 0); die
  Tageszeile zeigt `08:00–15:30 · 30 min Pause`. Der **Google-Kalendertermin** bleibt brutto (volle
  Spanne), darauf weist unter dem Reservierungsblock ein Hinweis hin
  (`RESERVATION_CALENDAR_NOTE`, nur mit Flag; bewusst bedingt formuliert „Falls dein Desktop mit dem Google-Kalender abgleicht …“, weil die PWA nicht weiß, ob der Abgleich an ist — anders als die Desktop-Konstante).
- **Eingabefeld.** Das Feld „Pause (Min)“ erscheint im Reiter „Reservierung“ nur mit dem Flag
  (`pauseEnabled`); eine neue Zeile bekommt nur dann die Standardpause, ohne Flag steht sie auf 0 und
  geht nie in einen Slot (`reservationRows`/`reservationRowsToSlots`).
- **Anwenden** (`Store._applyReservations`, in derselben Transaktion wie der
  Rest der Antwort): ein gesendeter, unveränderter Tag wird vom Desktop-Stand
  ersetzt, ein inzwischen geänderter bleibt lokal. Ein sauberer Tag, den die
  Antwort nicht kennt, wird entfernt — das gilt bis heute + 365; dahinter
  gehört er dem Desktop nicht. Ein gesendeter, unveränderter Tag ohne Antwort
  ist erledigt (Tombstone eingelöst, oder vergangen und vom Desktop still
  verworfen).
- **Nur heute und Zukunft.** Marker in der Wochenansicht („geplant …“) und der
  Reiter im Tages-Editor erscheinen nur dann; vergangene Tage zeigen nichts,
  auch keine vorhandene Reservierung. Der Editor öffnet an Tagen **nach heute**
  bei der Reservierung (die Ist-Zeilen sind mit Standardzeiten vorbelegt, ein
  Speichern dort legte sonst still eine Ist-Zeit an), heute bei der Arbeitszeit.
  Reservierungen zählen nicht in die Wochensumme; stattdessen zeigt der Wochenfuß unter
  „Woche gesamt“ eine Zeile **„Noch ausstehend“** (#329, `pendingLabel` in `view-model.js`): die
  reservierte Zeit, die noch nicht erledigt ist — an künftigen Tagen die ganze Reservierung,
  heute nur die offenen Slots (`openReservationSlots`, `pendingReservationMinutes`): ein Ist-Slot derselben
  Kategorie erledigt je einen Reservierungs-Slot, **gleich zu welcher Zeit** (die Kategorie, im Editor als
  `Kategorie*` bei Abweichung, ist die Verknüpfung; ohne Kategorie keine). Erledigte Slots verschwinden aus
  „geplant …“; gelöscht wird nichts, die Reservierung bleibt im Speicher und am Desktop unverändert. Der
  frühere Slot einer Kategorie wird zuerst erledigt. An künftigen Tagen zählt Ist-Zeit nie.
- **Nur, was der Desktop annimmt.** Der Desktop lehnt hinter heute + 365 die **ganze**
  Anfrage ab (auch die Ist-Zeiten). Die PWA lässt deshalb nur bis heute + 364 zu
  (`reservationEditable`, ein Tag Reserve für eine vorgehende Handy-Uhr); `saveReservation` wirft
  sonst. Ein abgelehnter Tag, der inzwischen vergangen ist, wird aufgeräumt; ist die Funktion
  verborgen, zählen Reservierungen weder als „nicht übertragen“ noch als „abgelehnt“.
- **Vorschlag für die Ist-Zeit** (#376, wie `entry_dialog` am Desktop): hat ein Tag eine Reservierung, aber noch
  keine Ist-Zeit, ist die Zeile im Reiter „Arbeitszeit“ daraus vorbelegt — Start/Ende vom ersten Slot, Pause aus dem
  Standard — oder die geplante Pause, wenn der erste Slot eine > 0 trägt (#455) —, die Kategorie nur bei
  **genau einem** Slot (`suggest_ist_category`). `editorRows(…, reservation)` in
  `view-model.js`; gespeicherte Ist-Zeiten gewinnen immer.
- **Override-Sternchen** (#376): das Kategorie-Label trägt ein `*` (`Projekt*`), wenn Start/Ende (bei Ist-Zeit auch
  die Pause) von den Standardzeiten der Kategorie abweichen (`categoryDisplay`, Gegenstück zu
  `slot_category_display`). Reine Anzeige, `row.kategorie` und das Gespeicherte bleiben der Klarname; ohne
  `defaults` (älterer Desktop) nie ein Sternchen. Die Pause einer **Reservierung** setzt nie ein `*`
  (`withPause` ist dort falsch). `views.js` zieht das Label bei jeder Zeiteingabe nach.
- **Löschen** wie bei den Ist-Zeiten: „Tag leeren“ (am Reiter „Reservierung“
  mit eigener Bestätigung) schreibt einen Tombstone — außer der Desktop kennt den Tag nie
  (`synced_version` 0): dann wird er nur lokal verworfen.
- **Ablehnung je Tag.** Der Desktop nennt den Tag vorn in der Meldung
  (`Reservierung <Datum>: …`); `SyncError.dayKind` unterscheidet das von einem
  Ist-Tag, und nur dieser Tag wird als abgelehnt markiert.
- **Zwei Uhren.** Der Desktop hebt den Stempel eines Handy-Tags auf
  `last_pull_at + 1 s` und stempelt einen übernommenen Tag mindestens mit dem
  Empfangszeitpunkt (`ReservationStore.merge_phone`); die Antwort kann daher
  einen neueren `modified_at` tragen als gesendet.

## Einstellungen und Kategorien

Der Button unten links heißt „Einstellungen“. `settingsDialog` (ersetzt den
früheren Verbindungsdialog) hat drei Reiter (`role="tablist"`): **Verbindung**
(Desktop, Adresse, Kopplung, Speicher, Verlauf, Hinweis zum älteren Desktop,
„Neu koppeln“), **Kategorien** und **Updates** (Version, „Nach Updates suchen“,
automatisch einspielen). Der Dialog hält den Zustand jedes Reiters selbst; ein
Wechsel verliert keine Eingaben.

**Kategorien-Reiter.** Eine Zeile je Kategorie (Name, Kurzfassung der Zeiten),
Hoch/Runter zum Sortieren, Antippen öffnet `categoryEditDialog` (Name, Start,
Ende, Pause; leere Zeitfelder heißen „globaler Standard“), „+ Kategorie“, Löschen
mit Nachfrage. Das Handy schreibt `categories` und `category_times` zurück an
den Desktop (Desktop-Seite: #311, `src/CLAUDE.md`).

- **Der Block** `categories_edit` (`{modified_at, dirty_version, synced_version,
  error}`) liegt in der **Meta**, zusammen mit `settings_writable`; die Meta
  wird ohnehin in der Transaktion der Antwort geschrieben, ein eigener Object
  Store samt IndexedDB-Upgrade ist nicht nötig. `saveCategories` setzt ihn
  (Stempel nach `_stampAfter`), `snapshotSettings` liefert `{settings,
  settingsVersion}` für den Abgleich, `markSettingsError(message, version)`
  den abgelehnten Block.
- **Senden.** `settings` geht im **ersten** Päckchen eines Abgleichs hinaus
  (zusammen mit den Reservierungen), nur bei geändertem, nicht abgelehntem
  Block und nur wenn `settings_writable`. **Ein Stempel für beide Schlüssel**:
  `categories` und `category_times` tragen dasselbe `modified_at`.
- **Bestätigung.** Nach der Antwort ersetzt der Desktop-Stand die lokale
  Fassung — **außer** der Block wurde seit dem Senden erneut geändert („während
  des Requests geändert“, Vergleich über `settingsVersion`): dann bleibt er
  dirty und geht im nächsten Abgleich hinaus. Hat sich der Stand seit dem
  Öffnen des Reiters durch einen Abgleich geändert, warnt der Dialog wie bei
  den Tagen („inzwischen aktualisiert … nochmaliges Speichern überschreibt“).
- **`422` je Block.** `Einstellung <Schlüssel>: …` setzt `SyncError.setting`
  und markiert nur den Block (`markSettingsError`), keinen Tag; er wird erst
  nach erneutem Speichern wieder gesendet und blockiert die Tage nicht
  dauerhaft (wie `markDayError`).
- **Feature-Erkennung über `writable_settings`.** Nennt die Antwort die beiden
  Schlüssel, ist das Bearbeiten an (Meta `settings_writable`). Fehlt das Feld
  (älterer Desktop), ist die Liste leer: die Kategorien sind lesbar, aber nicht
  bearbeitbar, und ein dirty Block bleibt liegen, **ohne** als nicht
  übertragen zu zählen (kein Sync-Badge, kein Dauerwarten).
- **`per_day` wird nie verändert.** Kategorien im Modus „pro Wochentag“
  (am Desktop eingestellt) sind umbenenn-, sortier- und löschbar, ihre Zeiten
  stehen als „pro Wochentag, am Desktop bearbeiten“ und gehen als `raw`
  unverändert zurück.
- **Umbenennen und Löschen schreiben nichts um.** Bestehende Einträge behalten
  den alten Namen (Kategorien sind am Desktop freier Text); der Dialog sagt es.
- **Grenzen** wie am Desktop (`mobile_settings.py`): Name nicht leer, ≤ 100
  Zeichen, eindeutig, ≤ 100 Kategorien, Zeiten `HH:MM`, Pause 0–1440
  (`MAX_CATEGORIES`/`MAX_NAME_LENGTH`/`MAX_PAUSE`). Nur die PWA prüft zusätzlich
  **Ende nach Start**, wenn beide gesetzt sind.
- **Konflikte nur am Desktop.** Haben Desktop und Handy die Einstellung nach
  dem letzten Abgleich geändert, entsteht ein Konflikt `kind: "setting"`, den
  nur der Desktop-Dialog löst; die Antwort trägt ihn nicht, die PWA zeigt keinen.
- **Zwei Uhren.** Geht die Handy-Uhr vor (Stempel bis 15 Minuten in der Zukunft
  sind erlaubt), kann ein zweites Speichern kurz nach dem Abgleich einen
  Konflikt „Handy gegen Handy“ erzeugen; der neuere Stand gewinnt vorläufig,
  Daten gehen nicht verloren (wie bei den Tagen).

## Benachrichtigungen (#331)

Erinnerungen kommen als Web-Push **auch ohne laufenden Desktop**. Der Weg: die PWA berechnet ihren
Zeitplan und ersetzt ihn beim **Push-Relay** (`relay/`, ein Cloudflare Worker); der Relay sendet zur
Fälligkeit an den Push-Dienst des Browsers, der Service Worker zeigt die Benachrichtigung. Der Relay
ist nie Voraussetzung: ohne ihn läuft alles wie vorher, ein Fehler bleibt ein Hinweis im Reiter
„Verbindung“.

- **`reminders-plan.js`** — `planReminders` baut den Plan aus Reservierungen, Ist-Zeiten und dem
  `reminders`-Block des Desktops: je Reservierungs-Slot „vor Ende“ bei `max(start, Ende − N)` und
  „verpasst“ bei `Ende`, nur mit Kategorie und nur, solange die Kategorie am Tag nicht als Ist-Zeit
  erfasst ist; heute bis heute + 14, nur Zukünftiges, höchstens 200 Einträge (die frühesten), nichts
  über 89 Tage voraus (der Relay lehnte sonst den ganzen Plan ab). Bei N = 0 gibt es nur „verpasst“.
  **Gleichlauf mit `src/reminders.py::due_reminders`** über `test/fixtures/reminder-plan-cases.json`:
  der Python-Test in `tests/test_mobile_contract.py` prüft, dass jeder Eintrag am Desktop genau zu seinem
  Zeitpunkt fällig wird und eine Minute davor nicht. Gerechnet wird in der Zeitzone des Handys, bei
  jedem Abgleich und jeder Änderung neu. Die **Sende-Zeitpunkte** rechnet der Desktop (Feiertage,
  Wochenend-Verschiebung) und schickt sie als UTC-Liste.
- **`push-blob.js`** — der Text einer Benachrichtigung reist als AES-256-GCM-Blob durch den Relay,
  mit einem eigenen, nicht extrahierbaren Schlüssel in der eigenen IndexedDB `zeiterfassung-push`
  (Seite **und** Service Worker lesen sie; die Haupt-Datenbank behält ihre `VERSION`). Bewusst nicht
  `k_dev`: der Desktop braucht diesen Schlüssel nie.
- **`push-message.js`** — Klartext des Blobs (`{k, c, e, d}` bzw. `{k:'send', t}`), Texte und Klick-Ziel.
  Der Service Worker zeigt **immer** eine Benachrichtigung (Chrome verlangt das, `userVisibleOnly`):
  ist das Entschlüsseln gescheitert, die allgemeine „Erinnerung“. Gleicher `tag` ersetzt, statt zu
  verdoppeln. Ein Klick öffnet die App am Tag (`?open=<Tag>`, eine offene bekommt `OPEN_DAY`).
  **Bewusst kein `icon`** an `showNotification` (#355/#356): Chrome unter Android zeigt in der
  Kopfzeile ohnehin das App-Icon der installierten Web-App, das große `icon-192` erschien rechts
  ein zweites Mal. Seitdem erscheint dort ein grauer Kreis mit „X“ (vermutlich Chromes
  Buchstaben-Platzhalter aus der Domain `xveyn.github.io`, nicht belegt); Lösungen und das
  Verhalten in Firefox und Safari stehen in #357. Ein monochromes `badge` steuert nur das kleine
  Statusleisten-Icon.
- **`relay-client.js`** — `RELAY_URL`, `PRIVACY_URL` (`./datenschutz.html`, die eigene Datenschutzseite; Link im Koppel-Bildschirm und im Reiter Verbindung, s. „Datenschutzseite“), `PRIVACY_SOURCE_URL` (das Dokument im Projekt, Ersatz der Seite; dieselbe Adresse wie `privacy_doc.PRIVACY_DOC_URL` am Desktop, ein Test hält beide zusammen; Kontakt über GitHub, s. Abschnitt 6 des Dokuments), `VAPID_PUBLIC` (nie wechseln, alle Abos hängen daran), die drei
  Aufrufe und `syncSchedule` (bei `409 no_subscription` einmal neu anmelden und wiederholen). Das
  Geheimnis dieses Handys (`relay_secret` in der Meta) ist Identität und Bearer und steht in keinem
  Fehlertext.
- **`push-policy.js`** — Zustand (`unsupported`/`denied`/`off`/`needs_resubscribe`/`on`) und die
  Entscheidung, wann gesendet wird: nur bei `on` und vorhandenem `reminders`-Block, bei neuer
  Signatur oder nach 12 h.

**Testbenachrichtigung (#340).** Im Abschnitt „Benachrichtigungen“ (nur im Zustand `on` mit Relay-Geheimnis) sendet „Testbenachrichtigung senden“ über `RelayClient.sendTest` (`POST /v1/test`) sofort einen Push, ohne den Zeitplan anzufassen. Der Relay schickt die feste, unverschlüsselte Nutzlast `TEST_PAYLOAD` (`push-message.js`, ein Test hält sie gleich der des Relays, s. `relay/CLAUDE.md`); der Service Worker erkennt sie **vor** dem Entschlüsseln und zeigt `describeTest()`, eine ältere Web-App zeigt die allgemeine Benachrichtigung. Das Ergebnis steht als Text im Abschnitt (`testResultText`, gleiche Texte wie am Desktop, `tab_rules.test_push_text`). Die `RelayError`-Arten der Testroute: `gone`, `too_soon`, `rate_limited`, `unknown_route` (alter Relay), `push_failed`; die beiden `429` trennt der Fehlercode im Body.

**Feature-Erkennung.** Ohne `reminders` in der Antwort (älterer Desktop, oder am Desktop aus) plant die
PWA nichts und schickt dem Desktop auch kein Relay-Geheimnis: die Anfrage trägt `push:
{relay_secret}` nur, wenn die letzte Antwort einen `reminders`-Block hatte. Gegenstück am Desktop:
`src/mobile_reminders.py` (Block bauen, Geheimnis lesen), `src/mobile_relay_store.py` (Ablage),
`src/CLAUDE.md`. Der Desktop sendet den Block **immer**, auch ausgeschaltet (leer): fehlte er dann, bliebe
der alte Plan am Relay stehen. Vertrag: `test/fixtures/reminders-contract.json` (Python:
`tests/test_mobile_contract.py`) und das Beispiel `reminders` in `sync-response.json`; eingefroren sind
`compat/*-pre-reminders.json`.

**Berechtigung ist pro Gerät** und braucht eine Nutzergeste (Knopf „Benachrichtigungen erlauben“ im
Reiter „Verbindung“). Ausschalten meldet das Abo ab und löscht das Objekt am Relay.

## Datenschutzseite

`datenschutz.html` zeigt `docs/datenschutz.md` ab Abschnitt 1 (Titel, Zitat und Einleitung sind fürs Repository
geschrieben; der Desktop-Dialog macht es ebenso, `privacy_doc.sections_only`). `privacy-view.js` lädt
`./datenschutz.md`, zerlegt es mit `privacy-doc.js` und baut die Elemente über `dom.js` (Links nur `http(s)`,
`noopener`); scheitert das Laden, steht ein Ersatztext mit Link auf `PRIVACY_SOURCE_URL` da.

- **Eine Quelle.** `pages.yml` kopiert `docs/datenschutz.md` nach `_site/datenschutz.md` (nicht aus `pwa/`:
  Markdown ist vom rsync ausgenommen) und läuft auch bei Änderungen allein an dieser Datei. Im Dev-Server
  fehlt die Datei: dort erscheint der Ersatztext.
- **Gleichlauf der Parser.** `privacy-doc.js` ist das Gegenstück zu `src/privacy_doc.py`; die Blöcke des echten
  Dokuments und einiger Grenzfälle stehen in `test/fixtures/privacy-blocks.json` (erzeugt von
  `scripts/privacy_fixtures.py`, gelesen von `test/privacy-doc.test.js` und `tests/test_privacy_doc.py`). Wer
  das Dokument oder einen Parser ändert, erzeugt die Datei neu.
- **Offline.** Seite und Module sind in `PRECACHE`, das Dokument selbst nicht (es kommt per `fetch` mit
  `no-cache`); ohne Netz erscheint der Ersatztext.

## Relay-Abgleich (#358)

Safari/iOS und Firefox sperren den Zugriff der `https`-Seite auf `http://<LAN-IP>` (Mixed Content). Für sie
läuft der Abgleich über die **Box** des Relays (`relay/`, Cloudflare Worker): das Handy legt die
verschlüsselte Anfrage dort ab, der Desktop holt sie ab und legt die Antwort ab. Verschlüsselung, Zähler `seq`,
Merge und Protokoll sind dieselben wie im LAN (`crypto.js`, `src/mobile_sync.py`); neu ist nur der **Transport**.
Spec: `docs/superpowers/specs/2026-11-02-ios-relay-abgleich-design.md`.

- **Transport-Naht.** `SyncClient._request` ruft `transports[endpoint.kind].exchange({method, path, token, body,
  endpoint})` und bekommt `{status, json}`; Fehlerstatus ordnet weiter `SyncClient` ein (`classifyHttpError`),
  ein Netzfehler kommt als `SyncError` aus dem Transport. `endpointOf(meta)` liefert `{kind: 'lan', host, port}`
  oder `{kind: 'relay', secret, have, onHave}`; **jede** Stelle, die „gekoppelt?“ wissen will, fragt `isPaired(meta)`
  (nicht mehr `meta.address`). Die Zeitüberschreitung ist ein Parameter (`timeoutMs`, Standard 15 s) des Clients und
  der Transporte.
- **Meta.** `transport` (`'lan'` | `'relay'`, ältere Stände `'lan'`), `box_secret` (Geheimnis der Box, nur bei
  `relay`, **nie** angezeigt oder geloggt), `box_have`. Ein erneutes Koppeln setzt die jeweils andere Seite zurück
  (`pair` leert `box_*`, `pairRelay` die `address`) und den Zähler `seq` auf 0; nicht übertragene Tage bleiben.
- **`RelayTransport`.** Je Austausch eine WebSocket (`wss://<Relay>/v1/box/ws?role=phone[&have=<ver>]`,
  Subprotocol `['zeit.v1', <Geheimnis>]`, das Geheimnis steht nur dort): bei `open` ein `put` mit
  `encodeRequest({path, token, envelope})`, dann warten auf ein `slot`, dessen `res` die Nonce `n` der Anfrage
  zurückgibt (`isCurrentResponse`, Regel 1 der Spec). Fremde, veraltete oder unlesbare `res` werden übergangen
  und geloggt, nie ein Fehler. `have` rückt mit **jedem** empfangenen `slot` vor (auch einem fremden), nur nach oben,
  höchstens 2^31 − 1, bei `1000 wiped` auf 0. Reißt die Verbindung vor der Antwort ab, geht beim zweiten Versuch
  **dieselbe** Anfrage (identische Bytes) noch einmal hinaus: der Desktop liefert die versiegelte Kopplungsantwort
  nur bei identischem `req` erneut aus (Regel 3). Schließcodes: `1008` → Art `throttled`, `1000 replaced` →
  `transient`/`replaced` (nicht automatisch neu verbinden), `1009`/`1003` → `protocol`, alles andere →
  Wiederverbinden.
- **Fehlerarten** (`messages.js`): Relay nicht erreichbar (kein `ok`; `offline`, Code `relay_unreachable`, Text
  ohne „WLAN“), Desktop antwortet nicht (`ok` kam, kein `res`; `desktop_silent`), Box drosselt (`throttled`),
  Antwort bzw. Anfrage zu groß (`too_large`, Code `response_too_large` aus dem Ersatzrahmen des Desktops bzw.
  `request_too_large`). Der Text für „offline“ in Browsern, die das LAN sperren, nennt zusätzlich „Über Relay
  koppeln“ als Ausweg. `ok` gilt **je Versuch**: ein `ok` des ersten und ein unerreichbarer zweiter Versuch ergibt
  „Relay nicht erreichbar“, nicht „Desktop antwortet nicht“. Wirft der WebSocket-Konstruktor oder `send`
  (CSP, `SecurityError`, ungültige URL), steht im Log nur der **Name** des Fehlers: Chromes Meldungstext kann das
  Subprotocol, also das Geheimnis, nennen.
- **Koppel-Link.** Gelesen von `parsePairLink` (`pairing.js`), im Scanner **und** aus `location.hash`;
  `scanForPairLink` liefert `{kind: 'lan', …}` oder `{kind: 'relay', secret, code}`. Ein `#pair=`- oder `#relay=`-Fragment
  wird nach dem Lesen **immer** aus Adresszeile und Verlauf entfernt (auch bei unbrauchbarem Inhalt und bei
  schon gekoppelter Seite): es trägt Code und Geheimnis. Das geschieht in `main()` **vor** dem Öffnen des Speichers
  (`scrubPairFragment`, sonst bliebe es bei einem privaten Fenster stehen, in dem `fatalView` erscheint); das
  gelesene Fragment geht als `startHash` an die `App`. `box_have` einer laufenden Anfrage wird nur gemerkt, wenn
  die Kopplung noch dieselbe Box ist (`SyncClient._rememberHave`). Die Koppel-Seite zeigt bei einem Relay-Link nur den
  Gerätenamen, kein Adress- oder Code-Feld; das Geheimnis liegt nur im Speicher von `App.pairing`. Eine Kopplung
  über den Relay gibt es nur per Link, nicht per Eingabe von Hand.
- **`ping()`** hat im Relay-Weg keine Route und liefert ohne Netzanfrage `{skewMs: 0, skewWarning: false}`; die
  Uhrprüfung kommt aus `server_time` der Abgleich-Antwort (`app.js`).
- **iOS.** Safari-Tab und installierte Web-App haben getrennten Speicher, und iOS löscht den Speicher im Tab nach
  sieben Tagen ohne Nutzung. `iosInstallHint` (`view-model.js`, nur wenn `browser === 'ios'` und `standalone === false`)
  zeigt deshalb vor dem Koppeln (Koppel-Seite) und im Wochenbild den Hinweis „zum Home-Bildschirm hinzufügen“;
  `browser-policy.isStandalone` entscheidet aus `navigator.standalone` und `display-mode`. Push braucht die
  installierte Web-App ebenfalls.
- **Entwickeln.** Die Box lässt nur die Pages-Origin zu; der Dev-Server (`scripts/pwa_devserver.py`, nur LAN)
  kann den Relay-Weg nicht ausprobieren. Geprüft wird er mit der gehosteten PWA gegen einen Desktop mit eingeschalteter
  Handy-Erfassung („Über Relay koppeln“). Die Tests fahren eine WebSocket-Attrappe
  (`test/relay-transport.test.js`) und einen Fake-Desktop hinter `fakeFetch` (`test/sync.test.js`, „Abgleich über den Relay“).

## QR-Decoder (#326)

`qr-decode.js` liest den Koppel-QR-Code dort, wo es keinen `BarcodeDetector` gibt (Firefox,
Safari/iOS). **Der Scan klappt dort, der Abgleich im LAN danach nicht:** Safari und Firefox sperren den
Zugriff der `https`-Seite auf `http://<LAN-IP>` (Mixed Content, #358); auf einem iPhone mit Safari
am 2026-10-26 beobachtet. Der Relay-QR-Code (s. „Relay-Abgleich“) braucht den LAN-Zugriff nicht. Aus der Spezifikation geschrieben, ohne Fremdcode; Algorithmen und Konstanten nach
ISO/IEC 18004, ZXing und jsQR (beide Apache-2.0) und dem Thonky-Tutorial.

- **Umfang.** QR Model 2, Versionen 1–10, alle EC-Stufen und Masken, beliebige Drehung und
  Perspektive. Nur der **Byte-Modus**: ECI, Kanji, Numerisch, Alphanumerisch und Structured Append
  liefern `null`. Der Koppel-Link (93 Zeichen) ist bei EC `M` Version 6 (41×41 Module).
- **Schnittstelle.** `decodeQr(luminance, width, height)` → Text oder `null`, wirft nie.
  `decodeMatrix(matrix)` liest eine bereits abgetastete Matrix. Die Tabellen (`EC_TABLE`,
  `ALIGNMENT_CENTERS`) sind gegen `segno` geprüft und nicht von Hand zu ändern.
- **Ablauf.** Hybrid-Binarisierung (Blöcke 8×8, Mittel über 5×5, Kontrastgrenze 24) → Finder-Suche
  (1:1:3:1:1, quer bestätigt) → Ausrichtung per Kreuzprodukt → Dimension aus den Finder-Abständen,
  gemessen **entlang der Symbolachse** (die Läufe der Zeilensuche sind bei Drehung bis zu √2-mal
  zu lang) → Alignment-Muster (Fenster 4/8/16 Modulgrößen, sonst Parallelogramm) → Perspektive →
  Format-/Versionsinformation (BCH) → Entmaskieren → Reed-Solomon je Block (Euklid, Chien,
  Forney, danach Syndrome erneut geprüft) → Segmente.
- **Bewusst anders als ZXing.** Die Dimension aus den Finder-Abständen ist auf ±1–2 Module genau;
  der Decoder probiert deshalb die nächsten drei Kantenlängen, und Format- und Fehlerkorrektur
  entscheiden — statt der mod-4-Regel allein. Abgetastet wird das binarisierte Bild (Mehrheit aus
  fünf Punkten je Modul), nicht das Graubild.
- **Einbindung (`scanner.js`).** `BarcodeDetector` bleibt der bevorzugte Weg, **wenn** er QR-Codes liest
  (`getSupportedFormats`) und sich bauen lässt; sonst liest `canvas.getImageData` Bilder aus dem Video
  (auf höchstens 640 px Kantenlänge verkleinert, nach jedem Bild 200 ms Pause) und `decodeQr` dekodiert
  sie auf dem Hauptthread. `canScan` ist wahr, sobald Kamera und Canvas da sind. Das Ergebnis läuft
  weiter durch `parseQrText` (nur private IPv4). Das Video wird vor `play()` per Eigenschaft stumm
  gesetzt und trägt `playsinline`: das Attribut `muted` wirkt nur beim Parsen, Safari braucht beides.
  Die Umgebung (`navigator`, `document`, `BarcodeDetector`, Wartezeit) kommt als Parameter herein;
  `test/scanner.test.js` spielt damit eine Kamera mit gerenderten Bildern.
- **Alle Schleifen sind beschränkt** (Kandidaten, Dreiergruppen, Dimensionen): die Eingabe ist ein
  Kamerabild. Fehlschlag heißt `null`, der Aufrufer nimmt das nächste Videobild.
- **Tests.** `test/qr-decode.test.js` (Reed-Solomon mit eigenem Encoder und dem Thonky-Vektor,
  alle Fixture-Matrizen, Format-/Versionsinfo) und `test/qr-image.test.js` (gerenderte und
  verschlechterte Bilder; der Renderer `test/qr-render.js` ist ein Testhelfer, kein Test). Ground
  Truth sind Matrizen aus `segno` in `test/fixtures/qr-matrices.json`; erzeugt von
  `scripts/qr_fixtures.py`, gegen `src.qr.qr_matrix` und die installierte `segno`-Version gehalten
  von `tests/test_qr_fixtures.py` (nach einem `segno`-Bump die Datei neu erzeugen).
- **Gemessene Grenze** (Renderer, zufällige Mischung aus Drehung, Perspektive, Rauschen,
  Helligkeitsverlauf, Unschärfe; Koppel-Link): ab 5 Pixeln je Modul praktisch immer, bei 3–4 Pixeln
  mit Unschärfe und Rauschen gelingt etwa jedes vierte Bild nicht. Version 1 hat kein
  Alignment-Muster und verträgt starke Perspektive schlechter. Echte Kameraaufnahmen sind nicht
  belegt — das klärt der Gerätetest (#267).

## Lesefenster (#250)

**Nach vorn (#265).** Das Fenster reicht auch **14 Tage nach heute** (`WINDOW_AHEAD_DAYS` am Desktop,
fest, nicht einstellbar): Ist-Zeiten, die am Desktop für spätere Tage stehen (vorgetragener Urlaub,
Termine), sieht das Handy, und am Handy für diese Tage eingetragene bleiben nach dem Abgleich stehen.
Die Antwort nennt es additiv als `window_ahead_days` (`PROTOCOL` bleibt 2); die Tage zählen **nicht**
ins Mengenbudget (`fit_window` rechnet nur nach hinten, vorn sind es höchstens 14). Die PWA hält das als
`window_ahead` in der Meta; `window-policy.aheadDays` liefert die Grenze für Anzeige und Aufräumen
(Randtag `heute + 14` gehört dem Desktop, wie der Wochenanfang des Fensters). Ein Tag dahinter ist
„außerhalb des Fensters“ und abgedunkelt; sonst sehen Einträge nach heute aus wie alle anderen. **Ältere
Desktops** schicken das Feld nicht: die Grenze bleibt heute + 1 wie bisher (Feature-Erkennung, eingefroren
als `compat/sync-response-pre-ahead.json`). Der Reiter „Verbindung“ nennt es in der Zeile „Verlauf“
(„… , dazu 14 Tage voraus“). Reservierungen haben ihr eigenes Fenster (365 Tage) und sind unberührt.

Die PWA sieht standardmäßig die letzten 90 Tage (Standardfenster **90 Tage**,
`WINDOW_DAYS` am Desktop, `DEFAULT_WISH` im Handy). **Das Handy wünscht, der
Desktop deckelt:**

- **Anfrage** (optional): `window_days` — der Wunsch des Handys. Fehlt er oder ist
  er ungültig, gilt das Standardfenster.
- **Antwort:** `window_days` — das **gewährte** Fenster, `window_max_days` — die
  Obergrenze des Desktops. Der Wunsch wird geklemmt, nicht abgelehnt: kein neuer
  Fehlercode.
- **Obergrenze** am Desktop: Einstellung im Tab „Mobil“, Auswahl
  Obergrenze **30 / 90 / 180 / 365** Tage, Standard 365, gerätelokal
  (`mobile_window_max_days`, nicht in `SYNCED_SETTING_KEYS`).
- Die PWA kennt die Stufen **90 / 180 / 365** Tage (`WINDOW_STEPS`). „Ältere Zeiten
  laden“ erscheint, wenn der Wochenanfang vor dem Fenster liegt, und wählt die
  kleinste Stufe, die die Woche abdeckt, höchstens `window_max_days`. Das
  Wunschfenster bleibt auf dem Handy; der Reiter „Verbindung“ zeigt es in der
  Zeile „Verlauf“ mit „Auf 90 Tage zurücksetzen“.
- **Fehlt `window_max_days`** (älterer Desktop), ändert die PWA ihr Fenster nie
  und erklärt das, statt einen wirkungslosen Knopf zu zeigen (Feature-Erkennung).
- **Drei Zustände der Obergrenze.** Vor der ersten angewandten Antwort ist sie
  *unbekannt* (`window_max_known` falsch): die Wochenansicht bittet um einen
  Abgleich und beschuldigt keinen Desktop. Danach ist sie eine Zahl oder, wenn
  die Antwort sie nicht trug, `null` (älterer Desktop). Welche Meldung erscheint,
  entscheidet `olderState` aus dem **bestätigten** Wunsch (`window_wish_acked`,
  der Wunsch, zu dem die letzte Antwort gehört) und nicht aus dem gerade
  getippten: ein noch unbeantworteter oder fehlgeschlagener Abgleich darf nie
  „wegen der Datenmenge“ melden.
- **Zeitüberschreitung** (15 s) ist eine eigene Fehlerart (`timeout`): sie kann
  einen schlafenden Desktop oder eine zu große Antwort bei schwachem WLAN meinen.
  Der Text nennt beides und verweist auf „Verbindung“, wo sich der Verlauf auf
  90 Tage zurücksetzen lässt. Einen automatischen Rückfall gibt es bewusst nicht
  (er träfe auch den schlafenden Desktop).

**Bearbeiten außerhalb des Fensters (#273).** Die **Arbeitszeit** eines Tages, den das Handy nicht kennt (vor
`heute − Fenster` oder nach `heute + Vorschau`), ist **gesperrt** (`view-model.editLock`): der Desktop nimmt an,
das Handy habe alles seit dem letzten Abgleich gesehen, ein Speichern ersetzte einen unsichtbaren Desktop-Eintrag
also **ohne Konflikt** (im Browser nachgewiesen: 9 h wurden zu 1 h). Statt der Zeilen zeigt der Editor einen
Hinweis; vor dem Fenster mit dem Ausweg „Ältere Zeiten laden (bis N Tage)" (schließt den Dialog, wünscht die
nächste Stufe, danach den Tag neu öffnen), sonst — Obergrenze, Datenmenge, älterer Desktop, noch kein Abgleich,
zu weit in der Zukunft — mit dem Grund (`olderModel`-Texte). **Nicht gesperrt:** ein Tag, zu dem das Handy einen
Datensatz hält (auch nicht übertragen oder geleert: er muss korrigierbar bleiben), und der Reiter
„Reservierung" (eigenes Fenster). `App.openDay` prüft beim Speichern ein zweites Mal. Serverseitig bleibt die
Lücke für veraltete PWA-Stände offen (Konflikt statt stilles LWW wäre ein eigenes Issue).

**Datenmenge.** Jede Antwort enthält das ganze Fenster, kein Delta. Gemessen
(verschlüsselt auf dem Draht): realistisch 365 Tage ≈ 90 KB, 50 Slots je Tag
(`MAX_SLOTS`) und 365 Tage ≈ 1,8 MB, mit langen Kategorien ≈ 4 MB. Rechnen und
Speichern sind auf beiden Seiten vernachlässigbar; der Engpass ist die
Übertragung (die PWA bricht nach 15 s ab). Deshalb kürzt der Desktop das
gewährte Fenster, wenn die Einträge mehr als ein Budget von 768 KiB ergäben
(`MAX_RESPONSE_ENTRY_BYTES`, `fit_window`); das Standardfenster bleibt immer,
gesendete Tage kommen immer zurück — **sie und die Konflikt-Kandidaten zählen nicht
ins Budget** (Extremfall gemessen: 400 gesendete Tage × 50 Slots ≈ 5,4 MB; das Handy sendet
höchstens 400 Tage je Anfrage). Die Antwort nennt das tatsächliche Fenster;
liegt es unter dem Wunsch und unter der Obergrenze, sagt die Wochenansicht „wegen
der Datenmenge“. `tests/test_mobile_volume.py` hält das mit denselben Fällen fest.
Fenster über 365 Tage brauchen Delta-Antworten (die PWA deutet „Tag fehlt in der
Antwort“ heute als Löschen) und stehen weiter in #250.

## Updates der PWA

Der Browser prüft `sw.js` von sich aus nur bei einer Navigation und höchstens
alle 24 Stunden. Die App stößt die Prüfung deshalb selbst an
(`update-policy.js`): beim Start und beim Zurückkehren in den Vordergrund,
höchstens alle 30 Minuten (`UPDATE_CHECK_INTERVAL_MS`), und auf Knopfdruck im
Reiter „Updates“ der Einstellungen („Nach Updates suchen“; Zustände wird geprüft / aktuell /
Update verfügbar / offline). Ein neuer Worker wartet, bis die Seite ihn
freigibt (`SKIP_WAITING`) — nie mitten in einer Eingabe.

**Automatisch einspielen** ist ein Schalter im Reiter „Updates“ (Meta
`auto_update`, gerätelokal, Standard **aus**; dann bleibt es beim Hinweis
„Neue Version verfügbar“ mit „Neu laden“). Ist er an, spielt die PWA ein
wartendes Update nur an einem sicheren Zeitpunkt ein (`shouldApplyUpdate`):
kein Dialog offen (eine halbe Eingabe), kein Abgleich läuft. Beim Start
sofort, danach beim Zurückkehren in den Vordergrund, wenn ein Dialog schließt
und wenn ein Abgleich endet. Pro wartendem Worker genau ein `SKIP_WAITING`
(`applyRequested`), sonst gäbe es eine Neulade-Schleife. Nicht übertragene Tage
liegen in IndexedDB und überstehen das Neuladen.

Das Einspielen prüft **nicht**, ob die neue PWA dasselbe Protokoll spricht wie
der gekoppelte Desktop: die Seite kann das Protokoll des wartenden Workers
nicht sicher lesen, und die Regeln oben (Desktop zuerst, Meldung nennt die
ältere Seite) fangen den Fall ab.

## Verschlüsselung (#249)

`crypto.js` ist das Gegenstück zu `src/mobile_crypto.py`; wer eine Konstante,
die AAD oder die Ableitung ändert, ändert beide Seiten und erzeugt
`test/fixtures/crypto-vectors.json` neu. Kopplung und Abgleich in `sync.js`
laufen als Umschläge, der Zähler `seq` wird **vor** dem Senden dauerhaft
abgelegt, und die PWA glaubt im Klartext nur, was der Desktop vor dem
Entschlüsseln sendet (`invalid_entry`/`clock_skew`/`busy` nur als Umschlag —
sonst könnte ein Dritter im WLAN einen Tag als abgelehnt markieren lassen).

**Mehrere Tabs (#277).** Jeder Tab lädt die Meta einmal; ein zweiter sendete denselben `seq`
(`409 replay` → „neu koppeln“) und schriebe Zähler und Token des anderen zurück. `SyncClient.sync` läuft
deshalb unter einer Web-Locks-Sperre (`navigator.locks`, Name `zeiterfassung-sync`) und lädt den Stand
darunter frisch aus IndexedDB (`Store.load` tauscht die Maps atomar). Ohne Web Locks bleibt der alte
Ablauf; Tests übergeben `locks` (`null` oder eine Attrappe), damit sie nicht von der Node-Version abhängen.
Offen: andere Schreibwege eines veralteten Tabs (Tag speichern, Einstellungen) lesen den Stand weiter nur einmal.

## Veröffentlichung

`.github/workflows/pages.yml` (Push auf `master` mit Änderungen unter `pwa/**`,
oder von Hand) kopiert die Laufzeitdateien nach `_site/` (ohne `test/`,
`package.json` und Markdown), ersetzt in `sw-core.js` den Platzhalter
`__BUILD__` durch die Build-Kennung (`scripts/pwa_stamp.py`; sonst liefe jeder
Deploy mit demselben Cache, und Updates kämen nie an) und veröffentlicht per
`deploy-pages`.

**Die Kennung heißt `N/X.Y.Z (sha)`** (#280, #359), z. B. `12/1.26.2 (abc123…)`:
N ist die Zahl der Commits unter `pwa/` seit dem letzten echten Desktop-Release,
X.Y.Z dessen Version, dazu der Commit. Die PWA hat keine eigene Versionsnummer
(bis #359 stand ein `P` aus `pwa/package.json` davor und musste in jedem
Release-PR gebumpt werden; das warf Desktop und PWA zusammen). Jede Änderung
unter `pwa/` geht sofort live, deshalb zählt N sie einzeln; ein Release setzt N
auf 0 zurück. Nach dem Release stößt `release.yml`
`pages.yml` neu an, sonst stünde bis zum nächsten `pwa/`-Push eine Kennung mit
altem Anker und altem N im Netz.

**Braucht eine Repo-Einstellung, die nicht im Code steht:** Settings → Pages →
Source „GitHub Actions“ (#266). Ohne sie scheitert der Deploy, und der
Workflow ist erst nach dem Merge nach `master` über „Run workflow“ erreichbar.

Die Adresse `https://xveyn.github.io/Zeiterfassung/` steht als `PWA_ORIGIN`/
`PWA_URL` in `src/mobile_routes.py` (einzig erlaubte Origin des Handy-Servers,
Basis des Koppel-Links); zieht das Repo um, müssen beide mit. Die Adresse ist **case-sensitiv**
(großes „Z“): `…/zeiterfassung/` oder die Domain ohne Pfad liefert GitHubs 404-Seite „There isn't a
GitHub Pages site here“.

## Entwickeln und prüfen

**Layout prüfen (Playwright gegen den Dev-Server).** Breiten von 280 bis 1024 px, dazu Querformat (667 × 375);
Zustände: Woche, Tages-Editor mit mehreren Slots (beide Reiter), Einstellungen (alle drei Reiter), Fehlerhinweis.
Bei jedem Zustand prüfen: Zeitfelder breit genug für `08:00` (bei 320 px mindestens ~95 px), keine abgeschnittenen
Reiter oder Knöpfe, kein waagerechtes Scrollen, Aktionsknöpfe der Dialoge sichtbar. Fallen, die schon Zeit kosteten:
der Service Worker und der HTTP-Cache liefern nach einer Änderung die alte Fassung (vorher
`navigator.serviceWorker.getRegistrations()` abmelden, `caches` leeren und neu laden), und ein `goto` mit anderem
Hash lädt die Seite nicht neu. `test/layout.test.js` hält die Ursachen der gefundenen Fehler am Quelltext fest
(schwebender ×-Knopf im Slot, zweispaltige Liste der Einstellungen bei schmalen Breiten, nicht sichtbare Fußknöpfe
eines scrollenden Dialogs, überlaufende Hinweise).

`python scripts/pwa_devserver.py` startet die echte Handy-Instanz
(`MobileService`, Dev-Origin statt Pages) plus `pwa/` statisch auf
`http://localhost:8099/` (sichere Origin, Service Worker läuft) und druckt
einen Koppel-Link mit frischem Code — auch für Browser-Tests mit Playwright.
Die PWA lehnt Loopback-Adressen ab; der Server bindet deshalb an die
LAN-Adresse (`--address` nur mit einer privaten Adresse).

Der Dev-Server stempelt `__BUILD__` in `sw-core.js` beim Ausliefern selbst
(`dev-<Hash>` aus Pfad, Größe und mtime der App-Dateien, #272). Eine Änderung
unter `pwa/` löst damit den normalen Update-Weg aus: der neue Worker wartet,
„Neu laden“ übernimmt ihn — ohne Worker abzumelden oder Caches zu leeren.

`--reservations` schaltet den Reservierungs-Abgleich ein (wie „Reservierungen verwenden“
am Desktop); ohne den Schalter fehlt das Feld `reservations` in der Antwort.

Der Dev-Server legt Kategorien mit Standardzeiten an (Projekt mit festen
Zeiten, Intern ohne Eintrag, Support als `per_day`) und nennt die Einstellungen
der Antwort `writable_settings`; damit lässt sich der Kategorien-Reiter samt
Rückweg zum Desktop ausprobieren.
