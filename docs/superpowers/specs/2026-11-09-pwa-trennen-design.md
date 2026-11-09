# Handy-Web-App: Trennen und lokale Daten löschen

Stand: 2026-11-09 · Status: Entwurf, noch nicht freigegeben · Issue #499

## Anlass und Ziel

Wer ein Handy nicht mehr nutzen will, kann heute nur neu koppeln (löscht nichts) oder im Fehler-/Sperr-Bildschirm
alles lokal verwerfen (`resetLocalData`, ohne Wissen des Desktops). Das Gerät bleibt am Desktop als gekoppelt
stehen, samt Relay-Box und Push-Geheimnis.

Ziel: Unter Einstellungen → Verbindung gibt es **„Trennen und lokale Daten löschen“**. Nach ausdrücklicher
Bestätigung meldet sich das Handy beim Desktop ab (über den Relay auch dann, wenn der Desktop gerade aus ist),
löscht alle lokalen Daten und landet auf dem Einrichtungs-Screen (#496). Der Desktop widerruft das Gerät und sagt
dem Nutzer Bescheid.

## Entscheidungen des Nutzers

- Die Abmeldung läuft **über den Relay**; der Desktop verarbeitet sie, sobald er online ist und die App läuft.
- Der Desktop meldet das per **Toast**; dabei sind die Besonderheiten von Windows, macOS und Linux zu beachten.
- **Ausdrückliche Bestätigung** nach dem Knopf.
- **Erst abgleichen versuchen**; misslingt das, warnen (mit Zahl der betroffenen Tage), Löschen bleibt möglich.
- Das Verhalten wird mit Tests abgesichert.

## Ziele, Nicht-Ziele, Anti-Ziele

Ziele
- Ein Fehlklick löscht nie etwas: ohne die zweite, ausdrückliche Bestätigung bleibt alles unangetastet.
- Nach dem Trennen kennt der Desktop das Gerät als widerrufen, die Relay-Box und das Push-Geheimnis sind
  abgeräumt, und die Geräteliste sagt „vom Handy getrennt“.
- Nichts Persönliches bleibt auf dem Handy: Einträge, Reservierungen, Kategorien, Schlüssel, Kopplung,
  Protokolle, Einstellungen der Sperre, Push-Abo.

Nicht-Ziele
- Keine Löschung von Daten am Desktop (er behält Einträge und Reservierungen).
- Kein Löschen der Passkeys der Sperre (aus dem Web nicht möglich); nur die zugehörigen Einstellungen.
- Kein Service-Worker- oder Cache-Reset; die App-Hülle bleibt (sie enthält nichts Persönliches).
- Kein Default-Flip des macOS-Trays.

Anti-Ziele (Misserfolg, auch wenn es technisch läuft)
- Daten gelöscht, ohne dass der Nutzer die Folgen kannte (nicht übertragene Tage).
- Der Desktop bleibt für immer im Glauben, das Handy sei gekoppelt, **ohne dass das Handy es wusste**: scheitert
  die Abmeldung, sagt die Rückfrage das vorher.
- Ein Toast oder Log, der Token, Schlüssel oder Box-Geheimnis enthält.

## Ablauf am Handy

1. **Knopf** im Reiter „Verbindung“ (eigener Abschnitt „Trennen“ unten, grau/rot gerahmt, nicht der Hauptknopf).
   Er öffnet nur die Rückfrage.
2. **Rückfrage** (Dialog), je nach Lage (Mockups: `.superpowers/brainstorm/…/trennen-dialog.html`):
   - *Alles übertragen* (Abgleich gelang oder nichts offen): Folgen, grüner Hinweis, „Abbrechen“ /
     „Ja, trennen und löschen“.
   - *Abgleich gescheitert, N Tage offen*: gelbe Warnung mit der Zahl, „Erneut abgleichen“,
     „Abbrechen“ / „Trotzdem löschen“.
   - *LAN-Kopplung, Desktop nicht erreichbar*: Warnung, dass der Desktop nichts erfährt und das Gerät dort
     widerrufen werden muss.
   „Abbrechen“ ist vorausgewählt; der Löschknopf ist rot. Escape und Klick auf den Hintergrund brechen ab.
3. **Abgleich zuerst:** Beim Öffnen der Rückfrage läuft ein Abgleich (bestehender `SyncClient`-Weg), die
   Rückfrage zeigt „gleicht ab …“, bis das Ergebnis da ist. Gibt es keine nicht übertragenen Tage
   (`dirty_version > synced_version`, auch `categories_edit`), entfällt er.
4. **Nach der Bestätigung**, in dieser Reihenfolge, jeder Schritt best effort außer dem letzten:
   1. Abmeldung an den Desktop (s. u.).
   2. Push abmelden: Abo kündigen, `DELETE /v1/device` am Relay (wie „Benachrichtigungen aus“).
   3. Sperre: ihre Einstellungen und der Slot in `sessionStorage` (`lock.js`).
   4. Protokoll (`log-store`) und Debug-Daten.
   5. `vault.wipe()`, dann `location.reload()` → Einrichtungs-Screen.
   Ein Fehler in 1–4 wird geloggt und bricht nie ab; scheitert `wipe()`, zeigt die App den Fehler und bietet
   den bestehenden Notausgang an (der Nutzer hat bestätigt, Löschen ist das Ziel).
5. Während des Ablaufs sind alle Knöpfe des Dialogs gesperrt (kein Doppelklick).

## Abmeldung über den Relay

- **Neue Route** `POST /v1/unpair` (Arbeitstitel), gleicher verschlüsselter Umschlag und gleiche Auth wie
  `/v1/sync` (`{v: 2, seq, n, c}`, AAD aus Methode, Pfad, Geräte-ID, Zähler); Anfrage ohne Inhalt, Antwort
  `{ok: true}`. Additiv, `PROTOCOL` bleibt 2, keine Schema-Änderung des Sync-Dokuments.
- **Relay-Kopplung:** Die PWA legt die Anfrage per `put` in den `req`-Slot der Box und wartet **nur auf das
  `ok` des Relays**, nicht auf eine Antwort des Desktops. Der Slot bleibt liegen, bis der Desktop sich
  verbindet und ihn über seinen `have`-Cursor abholt.
- **Die PWA löscht die Box nicht selbst**, sonst wäre die Abmeldung weg. Die Box räumt der Desktop nach dem
  Verarbeiten ab (`delete_box`, wie beim Widerruf); verbindet er sich nie, verfällt sie nach 90 Tagen.
- **LAN-Kopplung:** direkter Aufruf; scheitert er (nicht erreichbar), gilt die Warnung der Rückfrage und es
  wird trotzdem lokal gelöscht. Es gibt keinen Zwischenspeicher.
- **Älterer Desktop** (`404 not_found`): Die Sync-Antwort trägt additiv die Fähigkeit `unpair` (Muster
  `reservation_pause`). Fehlt sie, warnt die Rückfrage **vorher**, dass der Desktop nichts erfährt und das Gerät
  dort widerrufen werden muss (Lage wie bei LAN, nicht erreichbar). Nach dem Löschen bleibt nichts, was man
  noch zeigen könnte.
- Abgelaufenes oder bereits widerrufenes Token: der Desktop antwortet `token_expired`/`token_revoked`; für die
  PWA ist das Ergebnis dasselbe (Gerät ist dort nicht mehr gültig), sie löscht trotzdem.

## Desktop

- **Route** (`mobile_routes.py`, Handler wie `_sync` unter `devices_lock`): prüft Token wie bisher, widerruft
  den Datensatz (`mobile_pairing.revoke`) mit zusätzlichem Kennzeichen `revoked_by = "device"` und
  Zeitstempel, räumt über den vorhandenen Hook Relay-Box und Push-Geheimnis ab, antwortet verschlüsselt `ok`
  und meldet das Ereignis an die UI (Callback am `MobileService`, Muster `set_box_cleaner`).
- **Datensatz:** `revoked_by`/`revoked_at` additiv; der Store prüft Fremddaten wie bisher
  (`mobile_store._valid_record` o. ä.), unbekannte Werte werden zu „unbekannt“.
- **Hinweis an den Nutzer** (`ui.App`, Aufruf aus dem Server-/Relay-Thread über `_marshal_to_ui`), Weg wie
  `_notify_storage_repaired`: Dialog bei sichtbarem Fenster, Tray-Toast bei verstecktem Fenster, sonst Log.
  Text nennt nur den Gerätenamen, nie Token, Geräte-ID, Box- oder Push-Geheimnis.
- **Geräteliste** (Einstellungen → Mobil): ein von Handy getrenntes Gerät zeigt „vom Handy getrennt am …“
  statt nur „widerrufen“.

### Toast je Plattform (Verhalten, das ein Test festhält)

| Plattform | Toast | Fällt zurück auf |
|---|---|---|
| Windows | `pystray`-Toast, solange das Tray läuft (`minimize_to_tray` oder `reminders_enabled`) | Dialog (Fenster sichtbar), sonst Log |
| Linux | `org.freedesktop.Notifications` über das Tray-Backend, nur mit StatusNotifierWatcher | Dialog, sonst Log; kein Fehler ohne Dienst |
| macOS | Tray hinter `ZEIT_MACOS_TRAY=1`; ohne Opt-in kein Tray, also kein Toast | Dialog, sonst Log; Geräteliste zeigt es immer |

Regel: Die Wahl (Dialog / Toast / Log) ist eine **reine Funktion** aus Fensterstatus und Tray-Vorhandensein,
Tk-frei testbar. `tray.notify` darf auf keiner Plattform werfen. Ohne Toast geht nichts verloren, die
Geräteliste trägt den Zustand dauerhaft.

## Tests

PWA (`node --test`)
- Rückfrage: ohne Bestätigung ändert sich nichts (Knopf allein löscht nicht); „Abbrechen“/Escape lassen alles.
- Reihenfolge Abgleich → Abmeldung → Push → Sperre/Protokoll → Wipe → Reload; jeder Fehler vor dem Wipe wird
  geloggt und stoppt nichts.
- Lagen der Rückfrage: nichts offen, offen und Abgleich gelang, offen und gescheitert (Zahl), LAN
  nicht erreichbar, `404`.
- Doppelklick sendet die Abmeldung nur einmal.
- Danach: `store.load()` leer, Zustand = `isSetupPhase`.
- Vertrags-Fixture für Route und Antwort (`pwa/test/fixtures`, gelesen von `tests/test_mobile_contract.py`).

Desktop (`pytest`)
- Route widerruft, setzt `revoked_by`, räumt Box/Push ab; `replay`, abgelaufenes und bereits widerrufenes
  Token; Antwort verschlüsselt; Fremddaten im Datensatz.
- Hinweis-Wahl pro Zustand (Fenster sichtbar/versteckt × Tray ja/nein), Text ohne Geheimnisse; `notify` wirft
  nie (Backends als Attrappen je Plattform).
- `tests/test_mobile_relay_e2e.py`: Handy sendet, **dann erst** verbindet sich der Desktop; er holt die
  Anfrage ab und widerruft.

## Festlegungen des Entwurfs (Annahmen, vom Nutzer nicht einzeln entschieden)

- **Reihenfolge Abgleich / Abmeldung.** Der Abgleich vor dem Löschen ist Anfrage und Antwort: die PWA wartet auf die
  Antwort des Desktops, **erst danach** geht die Abmeldung in den Slot. Scheitert der Abgleich, liegt seine Anfrage
  unabgeholt im Slot, und die Abmeldung ersetzt sie; das ist hinnehmbar, weil die Rückfrage genau diesen Verlust
  vorher benannt hat. Die Zahl der offenen Tage wird nach dem Abgleich neu gelesen, nie vorher gezählt.
- **Replay und Neu-Koppeln.** Die Abmeldung gilt nur mit dem Token des aktuellen Datensatzes (Token-Hash und `seq >
  last_seq` wie beim Abgleich). Wurde das Gerät inzwischen neu gekoppelt, passt der Hash nicht mehr und die alte
  Abmeldung wird abgewiesen; eine neue Box gibt es ohnehin je Kopplung.
- **Reste am Relay.** Die Box hält nur verschlüsselte Rahmen, kein Push-Geheimnis. Das Push-Objekt ist ein eigenes
  Objekt: die PWA löscht es best effort, und der Desktop räumt es beim Widerruf ebenfalls ab (`push_relay.delete_device`,
  vorhandener Pfad von `revoke`); ein Rest verfällt nach 90 Tagen von selbst.
- **Kein Abbrechen nach der Bestätigung.** Ab „Ja, trennen und löschen“ ist der Dialog nicht mehr schließbar
  (kein Escape, kein Klick daneben); davor bricht beides ab.
- **Laufender Abgleich.** Die Rückfrage nutzt den einen Abgleich-Guard der App: läuft schon einer, wird er
  abgewartet statt ein zweiter gestartet. Hintergrundarbeit des Push-Abos wird vor dem `wipe()` abgewartet,
  höchstens kurz (Frist wie bei den Einstellungen).
- **Umfang des Löschens.** Der Bauende prüft alles, was die App in `localStorage`, `sessionStorage` und
  IndexedDB ablegt (Sperre #490, Einrichtung #496, Protokoll, Debug), und ein Test hält fest, dass nach dem Trennen
  keiner dieser Schlüssel mehr persönliche Daten trägt. Der Service-Worker-Cache bleibt.
- **Gerät mit `revoked_by = "device"`** verhält sich wie ein widerrufenes: Datensatz bleibt, Neu-Koppeln erzeugt
  ein neues Token, der `relay_link` räumt über den bestehenden Hook (`forget_devices`) die Verbindung ab.

## Offene Punkte (Sache des Bauenden, bei Zweifel zurückfragen)

- Genaue Namen der Route, des Kennzeichens (`revoked_by`) und der Texte.
- Ob der Abgleich-vor-dem-Löschen den normalen Schloss-/Fortschrittsweg wiederverwendet (`app.js` Sync-Knopf).
- Geprüft (2026-11-09): Die Box hält `req` im Durable-Object-Speicher; verbindet sich der Desktop, bekommt er
  den Slot, sobald dessen `ver` größer ist als sein `have` (`relay/src/box.js`, `relay_link` übergibt den Cursor
  aus `mobile_box_cursor`). Die Abmeldung muss deshalb die **letzte** Anfrage des Handys sein (ein späteres
  `put` ersetzt den Slot); die PWA sendet danach nichts mehr. Eine nie abgeholte Box verfällt nach 90 Tagen.
