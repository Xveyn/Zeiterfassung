# Handy-Abgleich über den Relay (iOS) — Design

Stand: 2026-11-02 · Entwurf, nach Code-Prüfung überarbeitet · Issue #358 · baut auf #221, #249, #331 auf

## Ziel

Die Handy-PWA gleicht auch dann mit dem Desktop ab, wenn sie keine `http://<LAN-IP>`-Verbindung
aufbauen darf (iOS/Safari: Mixed Content; Firefox ebenso). Der Weg läuft über den bestehenden Cloudflare
Worker (`relay/`), **Ende-zu-Ende verschlüsselt**; der Relay sieht Pfad, Statuscode, `seq`, `n`, Nonce,
Feldnamen, Größe, Zeitpunkte, IP, und das Gerätetoken im Klartext; nie den Inhalt. Das LAN-Verfahren
bleibt für Android/Chrome unverändert. Für iOS ist der Relay-Weg Pflicht, sonst optional.

Nicht Ziel: der Relay versteht, merged oder speichert Zeiteinträge im Klartext; ein Konto-System;
mehr als ein Handy je Kopplung (wie heute).

## Leitidee: Der Relay ist ein Tunnel für das bestehende Protokoll

Kein neues Datenmodell. Die verschlüsselten Umschläge (`pair`, `sync`, Protokoll 2) bleiben, ebenso
`sync.merge`, `mobile_sync` und `mobile_routes` (`dispatch(ApiRequest, MobileContext, Principal)` ist schon
nahezu eine reine Funktion). Neu ist nur der **Transport**: statt `fetch("http://lan:port/v1/sync")` legt
das Handy den Umschlag beim Relay ab, der Desktop holt ihn dort ab, verarbeitet ihn wie heute und legt die
Antwort ab. Der Relay kennt zwei Plätze je Kopplung: `req` (Handy → Desktop) und `res` (Desktop → Handy),
je **ein Slot, neuer ersetzt alten** (kein Queue-Modell).

**Geprüft (Code, 2026-11-02): ein ersetzbares `req` verliert keine Daten.** Die PWA sendet zustandsbasiert:
alles mit `dirty_version > synced_version` geht in jede Anfrage, bestätigt wird erst nach einer geöffneten
Antwort (`store.applyResponse`); `perform_sync` ist idempotent, die Antwort ein Fenster, kein Delta.
Daraus folgen vier Regeln für den Tunnel:

**Beide Seiten speichern `have` dauerhaft** (Handy in der Meta, Desktop in einer gerätelokalen Ablage), also den
`ver` des zuletzt empfangenen `slot`. Ohne das stellt die Box nach jedem Neustart den letzten Slot erneut zu; mit
ihm sind die Regeln 2 und 3 nur noch Gürtel und Hosenträger für den Fall, dass `have` verloren geht.

1. **Veraltetes `res` nie an `openEnvelope`.** Die Antwort-AAD enthält die `seq` der Anfrage; ein spätes `res`
   zu einer älteren Anfrage ließe `open` mit `needsRepair` scheitern („neu koppeln“). Der Transport vergleicht
   das Klartext-Feld `n` des `res` (die vom Desktop zurückgegebene Nonce) mit der Nonce der offenen Anfrage und
   verwirft Abweichendes (`isCurrentResponse`). Nicht `seq`: Kopplung und erster Abgleich tragen beide `seq` 1.
2. **Der Desktop überspringt ein `req` mit `seq <= last_seq` ohne zu antworten**, sonst überschreibt ein
   unverschlüsseltes `409 replay` das gute `res`. `last_seq` ist dabei das **gespeicherte** `record["last_seq"]`
   des Gerätedatensatzes (nach jedem entschlüsselten Paket geschrieben), nie ein Zähler im Speicher: nach
   Absturz und Neustart beantwortete der Desktop ein erneut zugestelltes, schon angewendetes `req` sonst mit
   `409 replay` und überschriebe das gute `res`.
3. **Pairing ist nicht wiederholbar** (`try_open` verbraucht den Code vor der Zustellung). Der Desktop-Adapter
   hält die versiegelte Pair-Antwort vor und liefert sie bei identischem `req` erneut aus.
4. **Token, Methode und Pfad reisen neben dem Umschlag** (`{path, token, envelope}`; Token steht nur im
   Authorization-Header, Methode und Pfad in der AAD). Der Relay behandelt das als opake Bytes. Der Relay
   sieht damit das Gerätetoken; er kann ohne `k_dev` nichts lesen, und Replay stoppt `last_seq`.
   Zusätzlich: Timeout der PWA (heute fest 15 s) wird einstellbar; Chunks bleiben strikt nacheinander.

## Budget: „leicht auf dem Worker“ (Workers Free, Doku-Stand 2026-11-02)

| Grenze (Free) | Wert | Konsequenz |
|---|---|---|
| Workers-Anfragen | 100 000/Tag | **bindend**, gilt für alle Nutzer zusammen; Zählung der DO-Anfragen dagegen unbestätigt |
| DO-Anfragen | 100 000/Tag; WebSocket-Eingang 20:1 | Nachrichten sind billig, Verbindungsaufbau kostet je eine Anfrage |
| DO-Zeilen geschrieben | 100 000/Tag (Löschen und `setAlarm` zählen) | je Nachricht 1 Schreibvorgang, Alarm höchstens einmal am Tag |
| DO-Dauer | 13 000 GB-s/Tag; ruhend/hibernierend nicht berechnet | **Hibernation API Pflicht**, kein Long-Poll |
| Zeile/Wert | 2 MB | Nachricht begrenzen auf 1 MiB |
| CPU je Anfrage | 10 ms | **kein JSON-Parsen, keine Kryptografie im Worker**, Bytes durchreichen |

1. **Kein Polling, kein Long-Poll.** 60-s-Polling eines Desktops = 1 440 Anfragen/Tag (~70 Desktops füllen das
   Kontingent); ein Long-Poll hielte das DO wach (25 s ≈ 3 GB-s je Warten).
2. **Beide Seiten sprechen WebSocket** (Hibernation API): Handy und Desktop halten je eine Verbindung zum selben
   DO. Schreiben (`put`) und Zustellung laufen als WebSocket-Nachrichten (Eingang 1/20 Anfrage, Ausgang frei).
   Heartbeat über `setWebSocketAutoResponse`.
3. **Ereignisgetrieben**: Last entsteht nur, wenn jemand abgleicht.
4. **Opake Bytes**, binär gerahmt; ein **Größenwächter** statt Kompression: Kodieren wirft `FrameTooLarge`
   (`RelayFrameError('too_large')` in der PWA), wenn die Nutzlast `MAX_PAYLOAD` (1 048 575 Bytes) überschreitet.
   Grund: eine Anfrage trägt höchstens `MAX_DAYS_PER_REQUEST = 400` Tage, **typisch** rund 100 KB gegen 1 MiB.
   Das ist nicht die Obergrenze: im Extremfall (400 gesendete Tage × 50 Slots, die gesendeten Tage zählen nicht
   ins 768-KiB-Budget des Fensters, `pwa/CLAUDE.md` „Datenmenge“) kommt eine **Antwort** auf rund 5,4 MB. Passt
   die versiegelte Antwort nicht in `MAX_PAYLOAD`, schickt der Desktop stattdessen den Ersatzrahmen
   `encode_too_large_response(seq, n)`: `413` mit `{"error": {"code": "response_too_large", "message": …}}`
   (deutscher Hinweis, passt immer). Gzip nur, wenn eine Messung es verlangt.

Größenordnung (Schätzung): ~20 Anfragen je aktivem Nutzer und Tag tragen mehrere Tausend Nutzer; wird es knapp,
ist der Paid-Plan die Antwort, nicht ein anderes Design.

## Relay-Schnittstelle (neues DO `Box`, Binding `BOX`, Migration `v2`; `Device` bleibt unberührt)

**Ein** Geheimnis je Kopplung: 43 Zeichen Base64url (256 Bit) wie beim Push, das DO heißt `sha256(Geheimnis)`.
Der Desktop erzeugt es beim Koppeln, es reist im QR-Code zum Handy. Keine Rollen-Token: Rolle ergibt sich aus dem
Query-Parameter, und ein Dritter ohne Geheimnis erreicht das Objekt nicht (zur Härtung später: der Desktop tauscht
das Geheimnis in der versiegelten Pair-Antwort gegen ein neues aus).

| Route | Zweck |
|---|---|
| `GET /v1/box/ws?role=phone\|desktop[&have=<ver>]` | WebSocket-Upgrade. Geheimnis im Subprotocol (Browser können keine Header setzen): `Sec-WebSocket-Protocol: zeit.v1, <Geheimnis>`; geantwortet wird `zeit.v1`. Je Rolle höchstens eine Verbindung, eine neue ersetzt die alte. |
| `DELETE /v1/box` | alles löschen (`Authorization: Bearer <Geheimnis>`) |

Nachrichten (binär, 1 Byte Typ):

| Richtung | Typ | Inhalt |
|---|---|---|
| Client → Relay | `0x01 put` | Nutzbytes (höchstens `maxFrame − 1` = 1 048 575 Bytes; die ganze Nachricht samt Typ-Byte höchstens 1 MiB). Der Relay schreibt sie in den Slot der Absender-Rolle (`phone`→`req`, `desktop`→`res`), vergibt ein neues, größeres `ver` (s. u.), stellt sie dem Gegenüber zu und quittiert. |
| Relay → Gegenüber | `0x02 slot` | `ver` (4 Byte, big-endian) + Nutzbytes |
| Relay → Absender | `0x03 ok` | `ver` (4 Byte, big-endian) |

**`ver` ist zeitbasiert:** mindestens die Sekunden seit 2026-01-01 UTC, sonst Vorgänger + 1. So bleibt es auch
über das Aufräumen (Leerlauf, `DELETE`) hinweg monoton, obwohl der Zähler dabei mit gelöscht wird und das `have`
der Clients bleibt. Clients dürfen nur „größer“ annehmen, keine +1-Schritte; `have` ist auf 2^31 − 1 begrenzt,
das reicht bis ca. 2094.

**Put-Drossel:** höchstens 60 `put` je Socket und Minute (`putsPerMinute`, Token-Eimer); darüber wird nicht
geschrieben und die Box schließt mit 1008.

Beim Verbinden schickt der Relay den Slot des Gegenübers, wenn dessen `ver` größer ist als `have` (Standard 0).
Ist das Gegenüber offline, bleibt der Slot liegen und kommt beim nächsten Verbinden. Fehler beim Aufbau:
`401 unauthorized`, `400 invalid_request`, `403` (fremde Origin), `426` (kein Upgrade), `429 rate_limited`;
zu große Nachricht schließt mit 1009. „Kein Logging“, Rate-Limit je Adresse und die Origin-Prüfung
(Pages-Origin, Anfragen ohne `Origin` = Desktop erlaubt) übernimmt der Relay aus `relay/CLAUDE.md`.
Selbstreinigung: Alarm alle `idleDays`, höchstens einmal am Tag neu gesetzt.

## Desktop

- Tk-freier Baustein (Arbeitstitel `relay_link.py`, PR 3b): hält die WebSocket (Wiederverbinden mit Backoff), baut
  aus jedem `req` einen `ApiRequest`, ruft `mobile_routes.dispatch`, verpackt die Antwort als `res`. Regeln 2 und 3
  oben. Lebenszyklus wie `MobileService`; braucht einen WebSocket-Client (neue, gepinnte Abhängigkeit,
  3.12-Gegencheck, Eintrag in `CONTRIBUTING.md`).
- **Der Antwort-Kern ist PR 3a** (`src/relay_adapter.py`, `RelayAdapter.handle(payload) -> bytes | None`): Regeln 2
  und 3, `n` in jeder Antwort, 413-Ersatzrahmen; noch nicht verdrahtet. `src/box_relay.py` löscht eine Box
  (`DELETE /v1/box`, best effort), `src/mobile_box_store.py` hält die Box-Geheimnisse, `src/pwa_constants.py` die
  Adresse der PWA.
- **Thread-Modell (3b): Leser-Thread plus ein Arbeits-Thread.** Der Leser liest die WebSocket und ruft **nie**
  `dispatch`/`perform_sync`: er muss den Text `ping` alle 60–120 s senden und Schließen/Fehler bemerken, und ein
  Abgleich kann Sekunden dauern. Er legt das `req` in **einen einzelnen Slot** („neuester gewinnt“, ein älteres,
  noch nicht begonnenes `req` fällt weg; die PWA sendet zustandsbasiert, das verliert nichts). Ein Arbeits-Thread
  holt es ab und ruft `RelayAdapter.handle` **nacheinander**.
- **Der Thread liegt außerhalb von `BackgroundTaskRunner`**: ein dritter Thread-Ort neben dem API-Server und
  `single_instance`, mit eigenem Lebenszyklus. `shutdown()` schließt den Socket und wartet kurz auf den Thread;
  `BackgroundTaskRunner.wait_idle` wartet **nicht** auf ihn.
- **Voraussetzungen, die der Adapter nennt:** ein Adapter je `MobileContext`; `handle` wird aus **genau einem**
  Thread gerufen. Gleichzeitige gleiche Kopplungs-Nutzlasten werden nicht zusammengelegt (die zweite bekäme
  `403 invalid_code`); die Serialisierung ist Sache der Verbindungsschicht.
- **Schließcodes der Box (für 3b):** `1000 replaced` ⇒ **nicht** automatisch neu verbinden; `1008` (Put-Drossel) ⇒
  mindestens 60 s warten; `wiped` ⇒ `have` zurücksetzen (die Box wurde geleert, ihr `ver` beginnt neu).
- **Entscheidung: Box-Geheimnis in gehärteter Datei (`mobile_box.json`), nicht im Schlüsselbund.** Gründe: wie das
  Push-Geheimnis (#331, `mobile_relay.json`); ein geleaktes Box-Geheimnis erlaubt, den Slot des Gegenübers zu
  lesen (Gerätetoken im Klartext, versiegelter Umschlag), Slots zu überschreiben, den Desktop zu verdrängen und
  unversiegelte Fehler zu fälschen — **nicht**, Inhalte zu lesen oder zu synchronisieren: das braucht `k_dev`, und
  der liegt im Schlüsselbund. Ein Schlüsselbund-Zugriff blockiert bis zu 30 s und darf den Verbindungs-Thread
  nicht aufhalten. Ein späterer Wechsel ist ein Backend-Tausch hinter derselben API von `MobileBoxStore`.
- Einstellungen → Mobil: Verbindungsart (LAN / Relay) je Kopplung; Aufteilung Android/iOS **später**.
- `RELAY_URL` bleibt Konstante.

## PWA

- `SyncClient._sealedPost` (`pwa/sync.js:248`) ruft einen **Transport** auf: `LanTransport` (heutiges `fetch`) und
  `RelayTransport` (WebSocket). Rückgabe wie heute `{status, json}`; Regel 1 sitzt im `RelayTransport`.
- iOS: Installation auf den Home-Bildschirm anleiten (Push und Schutz vor dem 7-Tage-Löschen brauchen sie);
  Fehlermeldung „Desktop nicht erreichbar“ nennt die Ursache (deckt #275 mit ab).

## Sicherheit

- Der Relay sieht Pfad, Statuscode, `seq`, `n`, Nonce, Feldnamen, Größe, Zeitpunkte, IP, und das Gerätetoken im
  Klartext; nie den Inhalt, nie einen Schlüssel. AAD, `seq`-Replay-Schutz und Token-Rotation des Desktops gelten
  unverändert.
- **Wer das Geheimnis der Box kennt** (wer den QR-Code sieht, der Betreiber des Relays), kann sich als jede der
  beiden Rollen verbinden und damit:
  - den Slot des Gegenübers **empfangen**: das Gerätetoken im Klartext und den versiegelten Umschlag, nicht dessen
    Inhalt;
  - Slots überschreiben;
  - den echten Desktop verdrängen (Schließen mit `1000 replaced`, auf das Clients **nicht** automatisch neu
    verbinden): der Abgleich steht, bis jemand von Hand neu verbindet;
  - unversiegelte Fehlerantworten fälschen. Mit der `n`-Regel muss er dafür zuerst das offene `req` lesen — was
    er kann;
  - `DELETE /v1/box` auslösen.
  Ein Leck des Inhalts entsteht nicht: `c` ist Ende-zu-Ende verschlüsselt. Es ist ein Störer- und
  Metadatenrisiko.
- **Das Ablaufen des Kopplungscodes (5 Minuten) begrenzt das Geheimnis der Box nicht**; es gilt, bis die Box
  gelöscht oder (spätere Härtung) nach dem Koppeln ausgetauscht wird.
- **Ein fotografierter QR-Code erlaubt das Koppeln von überall im Internet**, solange der Code gilt; der LAN-QR
  verlangte Zugang zum LAN. Das ist eine Erweiterung des Vertrauens gegenüber dem LAN und gehört in den
  Koppel-Dialog (PR 3c) sowie in `known-limitations.md` und `docs/datenschutz.md` (PR 5).
- Kein Logging des Geheimnisses (auch nicht im Subprotocol/URL), kein Push-Bezug.

## Datenschutz

**Ein Ort:** `docs/datenschutz.md` (neu, Skelett in PR 1, jeder PR der Kette ergänzt seinen Teil; PR 5 verlinkt es
aus README und Koppel-Dialog). Es beschreibt **Datenflüsse, nicht Rechtsauskunft**: wer bekommt was, wo liegt es,
wie lange, wie wird es gelöscht. Die Datei ist die Quelle für Hinweistexte in der App, damit Text und Verhalten
nicht auseinanderlaufen (Muster `tests/test_claude_md_claims.py`: Zahlen wie 90 Tage und 1 MiB werden gegen den
Code geprüft). Zu beachten ist grundsätzlich:

1. **Was der Relay sieht — und was nicht.** Pfad, Statuscode, `seq`, `n`, Nonce, Feldnamen, Größe (≤ 1 MiB je
   Slot), Zeitpunkte, IP (Rate-Limit, Cloudflare-Plattform), und das Gerätetoken im Klartext; nie den Inhalt
   (Einträge, Kategorien, Namen). Arbeitszeiten sind Beschäftigtendaten; Ende-zu-Ende ist die Hauptmaßnahme, und genau deshalb darf kein
   Klartext-Pfad entstehen (kein „Vorschau“-Feld, kein Debug-Dump).
2. **Aufbewahrung und Löschung.** Slots liegen höchstens bis zum Ersetzen, längstens `idleDays` (90) ohne
   Aktivität; `DELETE /v1/box` und „Kopplung entfernen“ löschen sofort; „Zeiterfassung entfernen“ (`removal.py`)
   und `--forget-secrets` müssen die Box mit abräumen (PR 3b). Der Nutzer muss das im Dialog nachlesen können.
3. **Plattform-Logs.** Cloudflare schreibt auf Wunsch Aufruf-Logs (URL, Metadaten, bis 7 Tage). Die Query trägt
   `role` und `have`, nie das Geheimnis (das steht im Subprotocol-Header), trotzdem: `observability` im Worker
   **ausdrücklich aus** (`wrangler.toml`), „kein Logging“ ist sonst nur halb wahr. Die App-Regel „kein Logging“
   gilt für unseren Code, nicht für das, was die Plattform von sich aus mitschreibt — das Dokument sagt beides.
4. **Standort.** Das DO kann per Jurisdiktion an die EU gebunden werden (`env.BOX.jurisdiction('eu')`); das gilt für
   Ausführung und Speicherung des Objekts, **nicht** für den Worker, der pro Anfrage am nächsten Rand läuft (die IP
   wird dort verarbeitet). Die Jurisdiktion lässt sich später **nicht** nachziehen (gleicher Name = andere ID):
   Entscheidung fällt in PR 1, nicht später. Das bestehende Push-Objekt `Device` bleibt, wie es ist.
5. **Auftragsverarbeiter und Drittländer.** Cloudflare (Relay), GitHub/Microsoft (Auslieferung der PWA über Pages:
   IP des Handys), Apple/Google/Mozilla (Web-Push-Dienste kennen den Abo-Endpunkt). Das Dokument führt sie auf und
   verlinkt deren Bedingungen; ob für einen Nutzer ein Auftragsverarbeitungsvertrag nötig ist, hängt davon ab, wer
   die App wofür einsetzt (privat, Werkstudent mit eigener Erfassung, Arbeitgeber) — das steht dort als Hinweis,
   nicht als Zusage.
6. **Wer ist verantwortlich?** Der Betreiber des öffentlichen Relays (heute der Maintainer) verarbeitet zumindest
   IP-Adressen und Metadaten. Dafür braucht ein öffentlicher Betrieb eine Datenschutzerklärung und Kontaktangabe;
   offene Frage für den Maintainer, ob Impressum/Erklärung am Pages-Auftritt hängen. **Selbst-Hosting**
   (`RELAY_URL` einstellbar) wäre die Antwort für Nutzer, die niemandem außer sich selbst vertrauen wollen — als
   Option dokumentieren, Umsetzung nicht Teil von PR 1–5.
7. **Freiwilligkeit und Transparenz.** Opt-in je Gerät, klare Sprache vor dem Einschalten (was geht über wen, was
   nicht), Ausschalten und Löschen jederzeit; auf iOS ist der Relay Pflicht für die Handy-Erfassung, das muss dort
   ehrlich so stehen („ohne Relay kein Abgleich“), nicht als Wahl getarnt.
8. **Datensparsamkeit.** Nur ein Slot je Richtung (Ersetzen statt Historie), kein zusätzliches Konto, keine
   Geräte-ID im Klartext außer dem Gerätetoken im Rahmen. Das Gerätetoken ist ein Auth-Mittel, kein Identifikator
   des Menschen — aber der Relay kann Verbindungen über Zeit verknüpfen; das ist als Metadatenrisiko zu benennen.
9. **Schlüssel und Wiederherstellung.** Geht das Handy verloren, wird die Kopplung am Desktop widerrufen (Token
   weg; zusätzlich Box löschen). Der Relay hält keine Schlüssel; es gibt keine Wiederherstellung durch uns, und das
   gehört in den Text.
10. **Push getrennt halten.** `Device` (Push) und `Box` (Abgleich) bleiben getrennte Objekte mit getrennten
    Geheimnissen; wer beides nutzt, gibt dem Relay zwei unverknüpfte Handles, nicht eins.

## Vertrag der Nutzlast (PR 2)

- **Anfrage:** `{"v":1,"path":"/v1/pair"|"/v1/sync","token":<String|null>,"envelope":{…}}`. Im Relay-Weg gibt es
  nur `/v1/pair` und `/v1/sync`, kein `/v1/ping`.
- **Antwort:** `{"v":1,"status":<100–599>,"seq":<Ganzzahl|null>,"n":<String|null>,"body":{…}}` (Reihenfolge
  v, status, seq, n, body). `seq` ist das `seq` des Anfrage-Umschlags, zurückgespiegelt, `null`, wenn die Anfrage
  kein gültiges `seq` trug; es ist nur noch Auskunft. `n` ist die Nonce des Anfrage-Umschlags (12 Byte, Base64url,
  genau 16 Zeichen `^[A-Za-z0-9_-]{16}$`), vom Desktop in **jeder** Antwort zurückgegeben, auch in unversiegelten
  Fehlern (401/409/400/413 …), sobald sich der Anfrage-Rahmen dekodieren ließ; `null` nur, wenn der Umschlag keine
  gültige Nonce trug (`envelope_nonce`/`envelopeNonce`, `RelayRequest.n`).
- **Link:** `https://xveyn.github.io/Zeiterfassung/#relay=<43 Zeichen Geheimnis>:<28 Zeichen Code>`.
- **Regel 1** `isCurrentResponse(frame, pendingN)`: genau dann, wenn `pendingN` eine gültige Nonce ist und
  `frame.n === pendingN`. `pendingN` ist das `n` aus dem Umschlag der offenen Anfrage, nie `null`. Es gibt
  **keine** Ausnahme mehr für Fehler ohne `seq`: eine Antwort mit `n: null` ist nie aktuell (sonst ließe sich
  ein unversiegeltes `401 token_revoked` unterschieben).
- **Regel 2** `should_answer(seq, last_seq)` (Desktop): beantwortet wird nur, was neuer ist als das zuletzt
  Beantwortete; `last_seq` ist das gespeicherte `record["last_seq"]` (s. Leitidee).
- **Zu große Antwort:** `encode_response` wirft `FrameTooLarge`; der Desktop schickt dann
  `encode_too_large_response(seq, n)` (`413 response_too_large`, s. Budget Punkt 4).
- **Byte-genaue Vektoren:** Fixture-Zeilen mit `"canonical": true` sind genau das, was unsere Kodierer
  ausgeben (kompakte Trenner, feste Schlüsselreihenfolge, `ensure_ascii=False`, UTF-8); JS prüft
  `encodeRequest`, Python `encode_response` byte-genau dagegen.
- Größe: siehe Budget Punkt 4 (Größenwächter).

### Hinweise für PR 3 (3a–3c) und PR 4

- **PR 3a (umgesetzt):** `PWA_URL` und `PWA_ORIGIN` liegen in `src/pwa_constants.py`, damit `mobile_relay_codec`
  nicht die ganze Routenebene importiert.
- **PR 3b:** die Koppel-Anfrage kommt auf einer Box an; gebunden wird das offene Geheimnis mit
  `MobileBoxStore.bind(device_id, expected=<Geheimnis der Box, auf der die Anfrage ankam>)`, damit ein
  zwischenzeitlich neu geöffnetes Pairing unangetastet bleibt. Die Geräte-ID dafür liefert
  `RelayAdapter.process(payload)` als `RelayResult.paired_device_id` (nur nach einer gelungenen Kopplung, auch bei
  der erneuten Zustellung aus dem Zwischenspeicher).
- **PR 3b, Lebenszyklus des offenen Geheimnisses:** der Kopplungscode lebt nur im Speicher; nach einem Neustart ist
  ein `pending` in `mobile_box.json` verwaist. 3b ruft beim Start und wenn der Koppel-Dialog schließt oder der Code
  abläuft `clear_pending()` und `box_relay.delete_box(...)` und verbindet sich nie mit einer offenen Box ohne offene
  Kopplungssitzung.
- **PR 3b, gescheitertes `bind`:** scheitert `bind` nach gelungener Kopplung (`OSError`), ist das Gerät gekoppelt,
  die Box aber noch `pending`; das nächste `open_pending` gäbe sie als „altes“ Geheimnis zurück. 3b loggt den
  Fehlschlag, wiederholt `bind` mit der `paired_device_id` einer erneuten Zustellung und löscht das „alte“
  Geheimnis nie, solange es gebunden oder in Benutzung ist (sonst verliert das Handy seine Box; heilbar durch
  Neu-Koppeln).
- **PR 3b/PR 4, `have`:** wird `have` gleich nach dem Lesen eines `req` gespeichert, stellt die Box dieses `req`
  nach einem `503 shutting_down` oder einem Absturz nie wieder zu — das Handy muss mit einem **neuen** `seq` neu
  senden (die PWA zählt `seq` je Versuch hoch).
- **PR 3c:** `mobile_relay_codec.relay_link` liest `pwa_constants.PWA_URL` und folgt **nicht** der Überschreibung von
  `mobile_routes.PWA_URL` durch den Dev-Server; den `#relay=`-QR des Dev-Servers regelt 3c.
- **PR 4:** `response_too_large` (Desktop) und `RelayFrameError('too_large')` (Handy, Anfrage zu groß) auf
  `SyncError`s mit Hinweis abbilden (`KINDS`/`messages.js`, `pwa/test/fixtures/errors.json`) — nicht in PR 2.
- **PR 4:** jedes nicht dekodierbare oder fremde `res` (kaputtes JSON, falsches `n`, `isEnvelope` scheitert) wird
  übergangen und geloggt, nie ein fataler `SyncError`.
- **PR 4:** `SyncClient.ping()` und die Uhrzeit-Prüfung im Reiter „Verbindung“ haben keine Relay-Route:
  `server_time` aus der Sync-Antwort ableiten oder die Prüfung ausblenden.
- **PR 4:** `pair()` verlangt `isLanAddress(host)`; die Kopplung über den Relay braucht einen eigenen Einstieg
  ohne Host und Port.

## Tests

- Relay: `node --test` mit In-Memory-Speicher und gefälschten WebSockets (`getWebSockets`/`acceptWebSocket`) —
  Slot-Semantik, Zustellung, Wiederaufnahme mit `have`, Größen, Auth, Alarm höchstens einmal am Tag, „kein Logging“.
  Hibernation und Quoten nur **gemessen** (`wrangler dev` für den Ablauf, deployter Relay für Zahlen), wie das
  `## Gemessen` in `relay/CLAUDE.md`.
- Protokoll: bestehende Vektoren bleiben; der Rahmen `{path, token, envelope}` hat Fixtures für beide Seiten
  (`pwa/test/fixtures/relay-frames.json`, auch vom Relay-Test geprüft).
- Desktop: `relay_link` Tk-frei mit gefälschter WebSocket; `tests/test_mobile_contract.py` um den Relay-Weg ergänzen.
- Echtgerät: iPhone über Pre-Release (Abgleich, Desktop offline, App-Neustart, Push); macOS bleibt nicht Pflicht.

## Offene Punkte

1. Zählen DO-Anfragen gegen die 100 000 Workers-Anfragen/Tag? Doku sagt es nicht; im Zweifel doppelt rechnen. **Gemessen (2026-11-02, Worker-Dashboard):** `put`/`slot`/Heartbeat über eine bestehende Verbindung erscheinen nicht als Worker-Aufrufe, nur der Verbindungsaufbau; Worker-CPU P99 5,74 ms. Offen: Zahlen des `Box`-Objekts (DO-Dashboard).
2. ~~Heartbeat-Intervall~~ **Gemessen (2026-11-02):** `ping`→`pong` funktioniert, auch ohne Heartbeat blieben Verbindungen 25 min offen; Clients verbinden bei Abbruch (1006) mit `have` neu, Heartbeat 60–120 s ist Empfehlung. Offen: zählen Auto-Responses gegen das 20:1-Kontingent (Dashboard).
3. Schließt iOS-Safari die WebSocket beim Hintergrund-Wechsel sauber? Annahme: ja, Wiederverbinden beim Öffnen
   mit `have`. Auf dem iPhone prüfen.
4. Soll der Desktop den Push-Zeitplan künftig selbst beim Relay ablegen? Eigene Entscheidung, nicht Teil von PR 1–4.
5. WebSocket-Client für den Desktop (`websockets` vs. `websocket-client`): Auswahl und Bündelung mit PyInstaller
   auf allen drei Plattformen im Plan zu PR 3b.

## PR-Schnitt (`Refs #358`, der letzte `Closes #358`)

1. **Relay: `Box`-DO**, WebSocket-Route, EU-Jurisdiktion, `observability` aus, Tests, Messung, Skelett
   `docs/datenschutz.md` (Plan: `docs/superpowers/plans/2026-11-02-relay-box.md`).
2. Protokoll und Vertrag — **umgesetzt in diesem Branch**: `src/mobile_relay_codec.py`, `pwa/relay-frame.js` und die
   Fixture `pwa/test/fixtures/relay-frames.json` (Python + JS, Rahmen `{path, token, envelope}`, Größenwächter statt Gzip).
3. Desktop, in drei Schritten:
   - **3a Desktop-Kern** — **umgesetzt in diesem Branch**: `src/pwa_constants.py`, `src/mobile_box_store.py`,
     `src/box_relay.py`, `src/relay_adapter.py`. Noch von keinem Aufrufer verwendet (kein Netz, kein Thread).
   - **3b Verbindung:** WebSocket-Bibliothek samt Auswahl und kurzem Spike (kein `Origin`-Header, Subprotocol
     `zeit.v1, <Geheimnis>`, Ping/Close, TLS-Prüfung an, Proxy-Verhalten, PyInstaller-Bündelung auf allen drei
     Plattformen); Thread `relay_link.py` (Leser-Thread plus **ein** Arbeits-Thread, „neuester gewinnt“ in einem
     Slot); Dienst und Verdrahtung in `App`/`main` an den drei Stellen `_quit_with_sync_push`,
     `remove_application` und `restart_for_scaling` samt `reopen`; `have` dauerhaft speichern; Binden der offenen
     Box über `MobileBoxStore.bind(..., expected=…)`; Widerruf, „Zeiterfassung entfernen“ und `--forget-secrets`
     löschen die Boxen über `box_relay.delete_box`; Abhängigkeit in `requirements.txt`, `CONTRIBUTING.md`,
     `scripts/build.py`, `Zeiterfassung.spec`; Pre-Release auf allen drei Plattformen.
   - **3c Oberfläche:** Einstellungen → Mobil, Koppel-Dialog mit dem `#relay=`-QR und dem Hinweis „ein
     fotografierter QR erlaubt das Koppeln von überall“, `FIRST_ENABLE_NOTICE`, Statusanzeige, Anpassung von
     `test_tab_rules`.
4. PWA: `RelayTransport`, iOS-Hinweise, Fehlermeldung, einstellbares Timeout.
5. Doku (`known-limitations.md`, READMEs, CHANGELOG), Pre-Release-Test auf dem iPhone, `Closes #358`.

Pläne zu 3b–5 entstehen nach PR 1, weil Messwerte (Offene Punkte 1–3) ihre Parameter bestimmen.
