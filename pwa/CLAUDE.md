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
  ganze Minuten.
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
  Slot-Normalisierung und -Prüfung ohne Pause (s. „Reservierungen“).
- `categories.js` — Kategorien-Verwaltung ohne DOM: Zeilen aus `categories` +
  `category_times` (`categoryRows`), zurück in den Block (`rowsToBlock`),
  Prüfung (`validateCategoryRows`), Kurzfassung der Zeiten (`timesSummary`),
  Sortieren (`moveRow`) und die Signatur zum Vergleichen (`blockSignature`).
  `per_day`-Kategorien laufen als `raw` durch und werden nie verändert (s.
  „Einstellungen und Kategorien“).
- `pairing.js` — Kopplungscode, Koppel-Link, Adressregel.
- `store.js` — lokaler Zustand: erfasste Tage und Reservierungen (zwei
  Sammlungen), `dirty_version`/`synced_version`, Anwenden der Sync-Antwort,
  Lesefenster. Mit
  `memory-adapter.js` (Tests) und `db.js` (IndexedDB-Adapter, eine Transaktion
  je `batch`).
- `sync.js` — Client: Koppeln, Ping, Abgleich, Einordnung der Server-Fehler in
  `SyncError.kind`.
- `crypto.js` — Gegenstück zu `src/mobile_crypto.py` (WebCrypto), s.
  „Verschlüsselung“.
- `window-policy.js` — Lesefenster (#250): Stufen, Wunsch, die Entscheidung der Wochenansicht
  am Fensterrand (s. „Lesefenster“).
- `view-model.js`, `messages.js`, `sync-policy.js`, `update-policy.js` —
  Anzeige- und Entscheidungslogik, DOM-frei und getestet.
- `reminders-plan.js`, `push-blob.js`, `push-message.js`, `relay-client.js`, `push-policy.js` —
  Benachrichtigungen (#331), DOM-frei und getestet, s. „Benachrichtigungen“.
- `dom.js`, `views.js`, `scanner.js`, `app.js` — die DOM-Schicht. Sie baut
  Elemente **nur** über `createElement` und Textknoten (ein Test verbietet
  `innerHTML` & Co.; Namen, Kategorien und Fehlertexte sind Fremddaten).
- `index.html`, `app.css`, `manifest.webmanifest`, `icons/` (erzeugt von
  `scripts/pwa_icons.py` aus dem Markenbild).
- `sw.js` — Service Worker (ES-Modul) mit dem getesteten Kern `sw-core.js`:
  Cache-Name, Vorab-Cache-Liste `PRECACHE`, `shouldHandle` (nur eigene, vorab
  gecachte GET-Anfragen). **API-Antworten und Anfragen an den Desktop gehen nie
  durch den Service Worker.**

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
verlangt sie in `errors.json`).

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

## Kompatibilität zu älteren und neueren Desktops

Die PWA kommt per Pages sofort bei jedem an, der Desktop hängt hinterher
(macOS hat kein Selbst-Update, Nutzer lassen Updates liegen). Der häufige Fall
ist also **neue PWA, alter Desktop**; der umgekehrte (gecachte alte PWA, neuer
Desktop) ist seltener, kommt aber vor. Sechs Regeln:

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
4. **Eingefrorene Vorgänger.** `test/fixtures/compat/` enthält Kopien der
   Vertragsbeispiele zu dem Zeitpunkt, an dem die Form galt. Sie werden **nie**
   mitgezogen, wenn sich das Live-Beispiel ändert: die PWA muss die alte Antwort
   weiter verstehen (`test/compat.test.js`), der Desktop die alte Anfrage
   (`tests/test_mobile_contract.py`). Wer den Vertrag erweitert, friert die
   Form **vor** der Änderung ein. Der erste eingefrorene Stand ist das
   Protokoll 2 vor #288 (ohne `defaults`/`desktop`); Protokoll 1 war nie in
   einem echten Release. Dazu kommt der Stand vor dem Lesefenster
   (`compat/*-pre-250.json`, ohne `window_days`/`window_max_days`) und der Stand vor den
   Reservierungen (`compat/*-pre-reservations.json`, ohne `reservations`) und der Stand vor den
   Einstellungen (`compat/*-pre-settings.json`, ohne `settings`).
7. **Neue PWA, alter Desktop.** Ein Desktop vor #311 ignoriert `settings` in der
   Anfrage und kennt `writable_settings` nicht. Die PWA bietet das Bearbeiten
   der Kategorien deshalb nur an, wenn die Antwort `writable_settings` mit
   `categories` und `category_times` nennt; sonst sind die Kategorien lesbar,
   aber nicht bearbeitbar (Hinweis „Desktop aktualisieren“). Das Feld statt
   „Antwort ohne `category_times`“, weil `defaults.category_times` schon seit
   #288 existiert und ein Desktop davor/danach nichts über das Schreiben sagte.
   Die IndexedDB-`VERSION` bleibt 2: der Block liegt in der Meta, kein neuer
   Object Store.
5. **Die Meldung nennt die ältere Seite.** Antwortet der Desktop auf einen
   falschen Umschlag mit `invalid_protocol`, steht im Klartext-Fehler
   `supported_protocol`; daraus macht `messages.js` „Desktop-App ist älter“
   (Desktop aktualisieren) bzw. „Desktop-App ist neuer“ (Seite neu laden). Die
   Zahl kommt im Klartext und ist nur ein Hinweis, kein Beleg. Fehlt sie
   (Desktop vor dieser Änderung), bleibt der allgemeine Text.
6. **Ein älterer Desktop wird angezeigt.** Schickt er weder `desktop` noch
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
  `{ISO: {slots: [{start, end, kategorie}], modified_at, deleted}}`, ohne
  `device_id`, ohne `pause`; der Desktop lehnt jedes weitere Feld am Slot ab.
  Gesendet wird im ersten Päckchen eines Abgleichs und nur, wenn welche
  nicht übertragen sind.
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
  Reservierungen zählen nicht in die Wochensumme.
- **Nur, was der Desktop annimmt.** Der Desktop lehnt hinter heute + 365 die **ganze**
  Anfrage ab (auch die Ist-Zeiten). Die PWA lässt deshalb nur bis heute + 364 zu
  (`reservationEditable`, ein Tag Reserve für eine vorgehende Handy-Uhr); `saveReservation` wirft
  sonst. Ein abgelehnter Tag, der inzwischen vergangen ist, wird aufgeräumt; ist die Funktion
  verborgen, zählen Reservierungen weder als „nicht übertragen“ noch als „abgelehnt“.
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
- **`relay-client.js`** — `RELAY_URL`, `VAPID_PUBLIC` (nie wechseln, alle Abos hängen daran), die drei
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

## Lesefenster (#250)

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

## Veröffentlichung

`.github/workflows/pages.yml` (Push auf `master` mit Änderungen unter `pwa/**`,
oder von Hand) kopiert die Laufzeitdateien nach `_site/` (ohne `test/`,
`package.json` und Markdown), ersetzt in `sw-core.js` den Platzhalter
`__BUILD__` durch die Build-Kennung (`scripts/pwa_stamp.py`; sonst liefe jeder
Deploy mit demselben Cache, und Updates kämen nie an) und veröffentlicht per
`deploy-pages`.

**Die Kennung heißt `P-N/X.Y.Z (sha)`** (#304), z. B. `1.0.0-12/1.26.2 (abc123…)`:
P ist die eigene Version der PWA (`version` in `pwa/package.json`, Semver), N die
Zahl der Commits unter `pwa/` seit dem letzten echten Desktop-Release, X.Y.Z
dessen Version, dazu der Commit. Jede Änderung unter `pwa/` geht sofort live,
deshalb zählt N sie einzeln; P wird nur im Release-PR gebumpt — zusammen mit
`src/version.py`, auch ohne PWA-Änderung, weil ein Release N auf 0 zurücksetzt
(`pwa-version.yml` erzwingt das). Nach dem Release stößt `release.yml`
`pages.yml` neu an, sonst stünde bis zum nächsten `pwa/`-Push eine Kennung mit
altem Anker und altem N im Netz.

**Braucht eine Repo-Einstellung, die nicht im Code steht:** Settings → Pages →
Source „GitHub Actions“ (#266). Ohne sie scheitert der Deploy, und der
Workflow ist erst nach dem Merge nach `master` über „Run workflow“ erreichbar.

Die Adresse `https://xveyn.github.io/Zeiterfassung/` steht als `PWA_ORIGIN`/
`PWA_URL` in `src/mobile_routes.py` (einzig erlaubte Origin des Handy-Servers,
Basis des Koppel-Links); zieht das Repo um, müssen beide mit.

## Entwickeln und prüfen

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
