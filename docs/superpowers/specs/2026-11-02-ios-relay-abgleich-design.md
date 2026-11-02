# Handy-Abgleich über den Relay (iOS) — Design

Stand: 2026-11-02 · Entwurf, nach Code-Prüfung überarbeitet · Issue #358 · baut auf #221, #249, #331 auf

## Ziel

Die Handy-PWA gleicht auch dann mit dem Desktop ab, wenn sie keine `http://<LAN-IP>`-Verbindung
aufbauen darf (iOS/Safari: Mixed Content; Firefox ebenso). Der Weg läuft über den bestehenden Cloudflare
Worker (`relay/`), **Ende-zu-Ende verschlüsselt**; der Relay sieht nur Chiffretext. Das LAN-Verfahren
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

1. **Veraltetes `res` nie an `openEnvelope`.** Die Antwort-AAD enthält die `seq` der Anfrage; ein spätes `res`
   zu seq N nach dem Senden von N+1 ließe `open` mit `needsRepair` scheitern („neu koppeln“). Der Transport
   vergleicht die Klartext-`seq` des `res` mit der offenen Anfrage und verwirft Abweichendes.
2. **Der Desktop überspringt ein `req` mit `seq <= last_seq` ohne zu antworten**, sonst überschreibt ein
   unverschlüsseltes `409 replay` das gute `res`.
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
4. **Opake Bytes**, binär gerahmt; Gzip vor dem Verschlüsseln (Client), damit ein Monat weit unter 1 MiB bleibt.

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

- Tk-freier Baustein (Arbeitstitel `relay_link.py`): hält die WebSocket (Wiederverbinden mit Backoff), baut aus
  jedem `req` einen `ApiRequest`, ruft `mobile_routes.dispatch`, verpackt die Antwort als `res`. Regeln 2 und 3 oben.
  Lebenszyklus wie `MobileService`; braucht einen WebSocket-Client (neue, gepinnte Abhängigkeit, 3.12-Gegencheck,
  Eintrag in `CONTRIBUTING.md`).
- Einstellungen → Mobil: Verbindungsart (LAN / Relay) je Kopplung; Aufteilung Android/iOS **später**.
- `RELAY_URL` bleibt Konstante.

## PWA

- `SyncClient._sealedPost` (`pwa/sync.js:248`) ruft einen **Transport** auf: `LanTransport` (heutiges `fetch`) und
  `RelayTransport` (WebSocket). Rückgabe wie heute `{status, json}`; Regel 1 sitzt im `RelayTransport`.
- iOS: Installation auf den Home-Bildschirm anleiten (Push und Schutz vor dem 7-Tage-Löschen brauchen sie);
  Fehlermeldung „Desktop nicht erreichbar“ nennt die Ursache (deckt #275 mit ab).

## Sicherheit

- Der Relay sieht Größe, Zeitpunkte und das Gerätetoken, nie Inhalt oder Schlüssel. AAD, `seq`-Replay-Schutz und
  Token-Rotation des Desktops gelten unverändert.
- Das Geheimnis steht im QR-Code; wer ihn sieht, kann Slots überschreiben (nicht lesen). Das ist ein Störer-,
  kein Datenleck-Risiko, und der Code läuft ohnehin ab. Härtung durch Austausch nach dem Koppeln: spätere Option.
- Kein Logging des Geheimnisses (auch nicht im Subprotocol/URL), kein Push-Bezug.

## Datenschutz

**Ein Ort:** `docs/datenschutz.md` (neu, Skelett in PR 1, jeder PR der Kette ergänzt seinen Teil; PR 5 verlinkt es
aus README und Koppel-Dialog). Es beschreibt **Datenflüsse, nicht Rechtsauskunft**: wer bekommt was, wo liegt es,
wie lange, wie wird es gelöscht. Die Datei ist die Quelle für Hinweistexte in der App, damit Text und Verhalten
nicht auseinanderlaufen (Muster `tests/test_claude_md_claims.py`: Zahlen wie 90 Tage und 1 MiB werden gegen den
Code geprüft). Zu beachten ist grundsätzlich:

1. **Was der Relay sieht — und was nicht.** Chiffretext (≤ 1 MiB je Slot), Zeitpunkte, Größen, das
   Gerätetoken im Rahmen, die IP-Adresse der Verbindung (Rate-Limit, Cloudflare-Plattform). Nie Einträge, Kategorien,
   Namen. Arbeitszeiten sind Beschäftigtendaten; Ende-zu-Ende ist die Hauptmaßnahme, und genau deshalb darf kein
   Klartext-Pfad entstehen (kein „Vorschau“-Feld, kein Debug-Dump).
2. **Aufbewahrung und Löschung.** Slots liegen höchstens bis zum Ersetzen, längstens `idleDays` (90) ohne
   Aktivität; `DELETE /v1/box` und „Kopplung entfernen“ löschen sofort; „Zeiterfassung entfernen“ (`removal.py`)
   und `--forget-secrets` müssen die Box mit abräumen (PR 3). Der Nutzer muss das im Dialog nachlesen können.
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
8. **Datensparsamkeit.** Nur ein Slot je Richtung (Ersetzen statt Historie), Gzip, kein zusätzliches Konto, keine
   Geräte-ID im Klartext außer dem Gerätetoken im Rahmen. Das Gerätetoken ist ein Auth-Mittel, kein Identifikator
   des Menschen — aber der Relay kann Verbindungen über Zeit verknüpfen; das ist als Metadatenrisiko zu benennen.
9. **Schlüssel und Wiederherstellung.** Geht das Handy verloren, wird die Kopplung am Desktop widerrufen (Token
   weg; zusätzlich Box löschen). Der Relay hält keine Schlüssel; es gibt keine Wiederherstellung durch uns, und das
   gehört in den Text.
10. **Push getrennt halten.** `Device` (Push) und `Box` (Abgleich) bleiben getrennte Objekte mit getrennten
    Geheimnissen; wer beides nutzt, gibt dem Relay zwei unverknüpfte Handles, nicht eins.

## Tests

- Relay: `node --test` mit In-Memory-Speicher und gefälschten WebSockets (`getWebSockets`/`acceptWebSocket`) —
  Slot-Semantik, Zustellung, Wiederaufnahme mit `have`, Größen, Auth, Alarm höchstens einmal am Tag, „kein Logging“.
  Hibernation und Quoten nur **gemessen** (`wrangler dev` für den Ablauf, deployter Relay für Zahlen), wie das
  `## Gemessen` in `relay/CLAUDE.md`.
- Protokoll: bestehende Vektoren bleiben; der Rahmen `{path, token, envelope}` bekommt Fixtures für beide Seiten.
- Desktop: `relay_link` Tk-frei mit gefälschter WebSocket; `tests/test_mobile_contract.py` um den Relay-Weg ergänzen.
- Echtgerät: iPhone über Pre-Release (Abgleich, Desktop offline, App-Neustart, Push); macOS bleibt nicht Pflicht.

## Offene Punkte

1. Zählen DO-Anfragen gegen die 100 000 Workers-Anfragen/Tag? Doku sagt es nicht; im Zweifel doppelt rechnen.
2. ~~Heartbeat-Intervall~~ **Gemessen (2026-11-02):** `ping`→`pong` funktioniert, auch ohne Heartbeat blieben Verbindungen 25 min offen; Clients verbinden bei Abbruch (1006) mit `have` neu, Heartbeat 60–120 s ist Empfehlung. Offen: zählen Auto-Responses gegen das 20:1-Kontingent (Dashboard).
3. Schließt iOS-Safari die WebSocket beim Hintergrund-Wechsel sauber? Annahme: ja, Wiederverbinden beim Öffnen
   mit `have`. Auf dem iPhone prüfen.
4. Soll der Desktop den Push-Zeitplan künftig selbst beim Relay ablegen? Eigene Entscheidung, nicht Teil von PR 1–4.
5. WebSocket-Client für den Desktop (`websockets` vs. `websocket-client`): Auswahl und Bündelung mit PyInstaller
   auf allen drei Plattformen im Plan zu PR 3.

## PR-Schnitt (`Refs #358`, der letzte `Closes #358`)

1. **Relay: `Box`-DO**, WebSocket-Route, EU-Jurisdiktion, `observability` aus, Tests, Messung, Skelett
   `docs/datenschutz.md` (Plan: `docs/superpowers/plans/2026-11-02-relay-box.md`).
2. Protokoll: Rahmen `{path, token, envelope}`, Gzip, Fixtures (Python + JS).
3. Desktop: `relay_link`, Kopplung über Relay, Einstellungen (minimal), WebSocket-Abhängigkeit.
4. PWA: `RelayTransport`, iOS-Hinweise, Fehlermeldung, einstellbares Timeout.
5. Doku (`known-limitations.md`, READMEs, CHANGELOG), Pre-Release-Test auf dem iPhone, `Closes #358`.

Pläne zu 2–5 entstehen nach PR 1, weil Messwerte (Offene Punkte 1–3) ihre Parameter bestimmen.
