# Einstellungen und Kategorien in der Handy-PWA

Stand: 2026-10-13. Zwei PRs (Desktop zuerst, dann PWA).

## Ziel

Die Handy-PWA wird ein Stück eigenständiger. Der Button unten links heißt
„Einstellungen“ statt „Verbindung“ und öffnet einen Dialog mit Reitern. Neu ist
die **Kategorien-Verwaltung**: Kategorien anlegen, umbenennen, löschen,
sortieren und je Kategorie Start, Ende und Pause festlegen, wie im
Kategorie-Dialog am Desktop. Zeiten eintragen, bearbeiten und löschen kann die
PWA schon.

Bewusst am Desktop bleiben: Versand (Gmail, SMTP, Webhooks), Google-Zugang und
alle Zugangsdaten, die Wochentag-Standards, Wochenlimit, Pausenwarnung und
Erinnerungen. Der Desktop bleibt die Quelle der Wahrheit; die PWA schreibt nur
`categories` und `category_times` dorthin zurück.

## Ist-Zustand (Kurzfassung)

- `categories` und `category_times` sind **synchronisierte Einstellungen**
  (`SYNCED_SETTING_KEYS`) mit Stempel je Schlüssel (`Settings._synced_meta`:
  `modified_at`, `device_id`). Den Merge zwischen zwei Desktops macht
  `sync.merge` (`kind: "setting"`, Konflikte im Desktop-Dialog), das Anwenden
  `Settings.apply_synced` (typgeprüft über `_coerce`).
- Das Handy ist im Abgleich schon `local` des Merges, sein Dokument trägt aber
  `"settings": {}` (`mobile_sync._phone_doc`). Die Antwort trägt `categories`
  und `defaults.category_times`; die PWA liest sie nur.
- `mobile_routes._sync` berechnet `categories=category_names(settings)` **vor**
  `perform_sync`. Nach einer Änderung vom Handy käme der alte Stand zurück
  (Fehler im Entwurf, wird mit behoben).
- `collect_categories` (Normalisierung) lebt in `category_dialog.py`, das Tk
  importiert; seine Eingabe sind Dialog-Zeilen, nicht die Form auf dem Draht.
  `mobile_sync._clean_category_times` bereinigt dagegen großzügig für die
  Antwort.

## PR 1: Desktop

Additiv, `PROTOCOL` bleibt 2. **Zuerst** die aktuelle Form unter
`pwa/test/fixtures/compat/*-pre-settings.json` einfrieren.

- **Anfrage** (optional): `settings: {categories: {value, modified_at},
  category_times: {value, modified_at}}`. Beide Schlüssel einzeln optional,
  **andere Schlüssel sind `422`** — das Handy kann nie mehr als diese zwei
  Einstellungen setzen.
- **Neues Modul `src/mobile_settings.py`** (Tk-frei): `parse_settings` prüft als
  Fremddaten, strikt, `422 invalid_entry`-Fehler mit dem Schlüssel in der
  Meldung (`Einstellung categories: …`):
  - `categories`: Liste von höchstens 100 Namen, je getrimmt, nicht leer,
    höchstens 100 Zeichen, ohne Unicode-Klassen `Cc`/`Cs` (wie
    `api_entry_write`), eindeutig.
  - `category_times`: Objekt `{Name: Eintrag}`; jeder Name steht in
    `categories` (der **neue** Stand, falls beide Schlüssel kommen; sonst der
    aktuelle Desktop-Stand), Eintrag allgemein `{start?, end?, pause?}` oder
    `{mode: "per_day", days: {Wochentag: {start?, end?}}, pause?}` mit
    `HH:MM`, Pause 0–1440, höchstens ein Eintrag je Name.
  - `modified_at` im festen UTC-Format, höchstens 15 Minuten in der Zukunft
    (die Uhrregel `clock_skew` greift vorher).
  - Die Hilfen `_clock`, `_pause`, `_clean_category_times` ziehen aus
    `mobile_sync` hierher um (Importzyklus vermeiden); `mobile_sync` importiert
    sie von dort.
- **Merge:** `_phone_doc` setzt `settings` aus der Anfrage, jeder Schlüssel als
  `{value, modified_at, device_id}`. Der Stempel wird wie bei den Ist-Zeiten auf
  `last_pull_at + 1 s` angehoben (zwei Uhren, `_phone_doc`). `sync.merge`
  entscheidet (neuerer Stempel gewinnt, bei Änderung auf beiden Seiten seit dem
  letzten Abgleich ein Konflikt `kind: "setting"` im Desktop-Dialog, vorläufig
  gilt der Sieger), `apply_merged_doc_journaled` schreibt unter dem
  `data_lock`. Sperrreihenfolge `devices_lock` → `sync_guard` → `data_lock`
  bleibt.
- **Antwort:** `categories` und `defaults` werden **nach** dem Anwenden berechnet
  (innerhalb von `perform_sync`; der Parameter `categories` der Funktion
  entfällt oder wird zum Aufruf). `defaults.category_times` bleibt wie bisher
  bereinigt und nur für bekannte Kategorien.
- **Nebenwirkungen am Desktop:** Nach einer Änderung ruft die Route `on_change`
  (Neuzeichnen). Über den Drive-Sync reist die Änderung an die anderen
  Desktops. Ein gerade offener Einstellungsdialog zeigt weiter seinen alten
  Stand (wie bei einem Pull); das ist unverändert und kein Teil dieser Arbeit.
- **Konflikte** vom Typ `setting` sieht das Handy nicht (`_conflict_views`
  filtert auf Einträge); sie werden am Desktop gelöst.
- **Tests:** `tests/test_mobile_settings.py` (Prüfung, Grenzen, per_day),
  `tests/test_mobile_sync.py` (Merge, Konflikt, Stempel-Anhebung, Antwort nach
  dem Anwenden, ignorierte unbekannte Schlüssel → `422`),
  `tests/test_mobile_routes.py`, `tests/test_mobile_contract.py` mit den
  eingefrorenen Vorgängern; Python-Beispiele für die PWA-Fixtures.

## PR 2: PWA

### Dialog und Reiter

Der Button unten links heißt „Einstellungen“. Der Dialog (`settingsDialog`,
ersetzt `connectionDialog`) hat Reiter im Stil der Reiter im Tages-Editor
(`role="tablist"`):

- **Verbindung:** das heutige Dialoginhalt (Desktop, Version, Plattform,
  Adresse, Kopplung gültig bis, dauerhafter Speicher, Verlauf, Hinweis zum
  älteren Desktop, „Neu koppeln“).
- **Kategorien:** neu, s. u.
- **Updates:** Handy-App-Version, „Nach Updates suchen“, „Jetzt neu laden“,
  automatisch einspielen.

Kein Reiter „Anzeige“ (er hätte nur den Verlauf). Der Dialog hält den Zustand
jedes Reiters selbst; ein Wechsel verliert keine Eingaben.

### Kategorien-Reiter

- Liste, eine Zeile je Kategorie: Name und Kurzfassung der Zeiten
  („08:00–16:00, 30 min Pause“ oder „—“). Pro Zeile Hoch/Runter zum Sortieren,
  kein Ziehen. Antippen öffnet die Kategorie (Name, Start, Ende, Pause; leere
  Zeitfelder heißen „globaler Standard“). „+ Kategorie“ legt eine an, Löschen
  fragt nach.
- **Modus „pro Wochentag“** (am Desktop eingestellt) bearbeitet die PWA nicht:
  solche Kategorien bleiben umbenenn-, sortier- und löschbar, ihre Zeiten
  stehen als „pro Wochentag, am Desktop bearbeiten“ und werden beim Speichern
  **unverändert** zurückgeschickt.
- Prüfung vor dem Speichern in der PWA (`categories.js`, rein): dieselben
  Grenzen wie am Desktop (Name nicht leer, ≤100 Zeichen, eindeutig, ≤100
  Kategorien; `HH:MM`; Pause 0–1440), zusätzlich Ende nach Start, wenn beide
  gesetzt sind. Fehler stehen im Dialog.
- Hinweis bei Umbenennen und Löschen: bestehende Einträge behalten ihren alten
  Namen (Kategorien sind am Desktop freier Text, es wird nichts umgeschrieben).
- „Speichern“ wirkt auf den Reiter wie am Desktop. Hat sich der Stand seit dem
  Öffnen durch einen Abgleich geändert, warnt die PWA wie bei den Tagen
  („inzwischen aktualisiert … nochmaliges Speichern überschreibt“,
  `dayChanged`-Muster). Danach wird ein Abgleich angestoßen.
- Ein älterer Desktop (Antwort ohne `category_times`): Reiter lesbar, Bearbeiten
  aus, Hinweis „Desktop aktualisieren“ (Muster `desktopHint`).

### Store und Abgleich

- Der Store hält die Kategorien als **einen Block** `{categories,
  category_times}` mit `dirty_version`/`synced_version`/`error` und `modified_at`
  (Muster der Reservierungen). Er liegt in der Meta, weil die Meta ohnehin in
  der Transaktion der Antwort geschrieben wird; ein eigener Object Store (und
  ein weiteres IndexedDB-Upgrade) ist dafür nicht nötig. Ein Speichern setzt den
  Stempel nach `_stampAfter`.
- Der Abgleich sendet `settings` nur bei nicht übertragenem Block, mit denselben
  zwei Schlüsseln und demselben `modified_at`. Beim Anwenden der Antwort ersetzt
  der Desktop-Stand die lokale Fassung, **außer** der Block wurde seit dem
  Senden erneut geändert (dann bleibt die lokale Fassung dirty).
- `422` für den Block (`Einstellung <Schlüssel>: …`) markiert ihn als
  abgelehnt; er wird erst nach erneutem Speichern gesendet und blockiert die
  Tage nicht dauerhaft (wie `markDayError`).
- Die Feature-Erkennung hängt an `category_times` in `defaults`; ein Desktop
  ohne diese Änderung ignoriert `settings` in der Anfrage.

### Tests

- Python wie in PR 1; JS für `categories.js` (Prüfung, Kurzfassung, per_day-Erhalt),
  Store (Dirty-Block, Race „während des Requests geändert“, Ablehnung),
  `sync.js` (Senden, `422`), `view-model` und die eingefrorenen Vorgänger.
- Die DOM-Schicht wird wie bisher von Hand im Browser geprüft
  (`scripts/pwa_devserver.py`; `pwa/CLAUDE.md`, „Entwickeln und prüfen“).

## Dokumentation (Pflicht)

Das Verhalten wird im selben PR dokumentiert:

- `pwa/CLAUDE.md`: neuer Abschnitt „Einstellungen und Kategorien“ (Reiter, Merge,
  Grenzen, per_day-Erhalt, Älterer-Desktop-Fall, zwei Uhren, Konflikte nur am
  Desktop) und die Kompatibilitätsregel 4 um den dritten eingefrorenen Stand.
- `src/CLAUDE.md`: `mobile_sync`-Absatz (Einstellungen, Berechnung nach dem
  Anwenden), `mobile_settings.py`.
- Wurzel-`CLAUDE.md`: Modulliste (`mobile_settings.py`, `pwa/categories.js`).
- `README.md`, Abschnitt „Handy-Erfassung“: ein Satz, dass sich Kategorien auch
  am Handy verwalten lassen, mit `*(ab --VERSION--)*`.

## Nicht Teil dieser Arbeit

- Wochentag-Standards und die globale Pause bearbeiten.
- Umbenennen mit Umschreiben bestehender Einträge.
- Bearbeiten der Modus-„pro Wochentag“-Kategorien auf dem Handy.
- Konflikte vom Typ `setting` auf dem Handy anzeigen oder lösen.
- Weitere Einstellungen (Erinnerungen, Wochenlimit, Versand).

## Risiken

- **Zwei getrennte Schlüssel:** `categories` und `category_times` werden einzeln
  gemerged. Ändert der Desktop nur die Namen und das Handy nur die Zeiten,
  können sie kurz auseinanderlaufen (am Desktop zwischen zwei Rechnern genauso).
  Die Prüfung verlangt deshalb, dass jeder Name in `category_times` in
  `categories` steht; die Antwort filtert ohnehin auf bekannte Namen.
- **Stiller Verlust von per_day-Zeiten** durch ein Speichern am Handy wird nur
  durch das unveränderte Zurückschicken verhindert. Test mit einer Kategorie im
  Modus „pro Wochentag“ ist Pflicht.
- **Handy-Uhr:** der Stempel eines Handy-Blocks gewinnt gegen eine spätere
  Desktop-Änderung nur durch die Anhebung auf `last_pull_at + 1 s`; bei falscher
  Uhr hilft nur die 15-Minuten-Regel (`clock_skew`).
- **Windows-Plattform:** nichts plattformspezifisch; ein Pre-Release über alle
  Plattformen ist nicht nötig.
