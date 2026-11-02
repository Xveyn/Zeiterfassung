# CLAUDE.md — `relay/` (Push-Relay)

Cloudflare Worker, der Erinnerungen als Web-Push an die Handy-PWA schickt, **ohne dass der Desktop
läuft** (#331), und hält seit #358 außerdem die **Box** für den Abgleich zwischen Handy und Desktop
ohne LAN (s. Abschnitt „Box“). Wird wie `pwa/` nicht in die App gebündelt und von keinem Python-Modul
importiert. Design: `docs/superpowers/specs/2026-10-21-pwa-push-erinnerungen-design.md` (Push) und
`docs/superpowers/specs/2026-11-02-ios-relay-abgleich-design.md` (Box); Einrichtung: `README.md`.

## Modell

Push: das Handy ersetzt seinen Zeitplan beim Relay (`PUT /v1/schedule`), der Relay sendet zur Fälligkeit.
Der Abgleich über die Box folgt demselben Geheimnis-Modell mit eigenem Geheimnis (s. „Box“).
**Es gibt keine Konten und keine Geräte-ID:** das Handy erzeugt ein Geheimnis (43 Zeichen
Base64url, 256 Bit), und das Durable Object heißt `sha256(Geheimnis)`. Wer das Geheimnis nicht
kennt, erreicht das Objekt nicht und kann es nicht besetzen.

| Route | Zweck |
|---|---|
| `PUT /v1/device` | Abo (`endpoint`, `keys.p256dh`, `keys.auth`) registrieren oder erneuern |
| `PUT /v1/schedule` | Zeitplan **ersetzen**: `{items: [{id, fire_at, blob}]}` |
| `DELETE /v1/device` | alles löschen |
| `POST /v1/test` | sofort einen Test-Push mit der festen Nutzlast `TEST_PAYLOAD` (`push.js`) senden, ohne Zeitplan und Alarm anzufassen. Je Gerät höchstens alle `LIMITS.testCooldownSeconds` (10 s). Antworten: `204` gesendet · `409 no_subscription` · `410 gone` (Abo tot, Objekt geräumt) · `429 too_soon` · `502 push_failed` (Push-Dienst nahm es nicht an; ein misslungener Versuch startet die Abkühlzeit nicht). Die Web-App erkennt die Nutzlast im Service Worker (`pwa/push-message.js`, ein Test hält die Konstante gleich) und der Desktop ruft die Route aus Einstellungen → Mobil (`src/push_relay.py`) |

Fehler (alle als `{error: …}`): `401 unauthorized` (Geheimnis fehlt/ungültig), `400 invalid_request`
(mit deutscher `message`), `409 no_subscription` (Zeitplan vor Abo), `404 not_found`,
`405 method_not_allowed` (mit `Allow`), `413 too_large` (Body über `LIMITS.maxBody`),
`429 rate_limited` (Rate-Limit je Absender-Adresse, `worker.js`) bzw. `429 too_soon` (Abkühlzeit von
`POST /v1/test`, `device.js`), `500 internal` (ohne Details); dazu `410 gone` und `502 push_failed`
von `POST /v1/test`. Reihenfolge im Worker: Route, `OPTIONS`, Methode, Rate-Limit, Geheimnis, Body.

### Grenzen (`LIMITS` in `src/validate.js`)

| Konstante | Wert | Bedeutung |
|---|---|---|
| `maxItems` | 200 | Einträge je Zeitplan |
| `maxAheadDays` | 90 | `fire_at` höchstens so viele Tage voraus, sonst wird der Zeitplan abgelehnt |
| `maxBlob` | 1024 | Zeichen des verschlüsselten `blob` je Eintrag |
| `maxBody` | 300 000 | Bytes eines Request-Bodys (200 Einträge mit vollem Blob liegen bei ca. 235 KB) |
| `graceSeconds` | 900 | so lange nach `fire_at` (bzw. der ersten Fälligkeit) wird noch gesendet |
| `idleDays` | 90 | so lange nach der letzten Aktualisierung räumt sich ein Gerät selbst auf |
| `testCooldownSeconds` | 10 | Sperre von `POST /v1/test` nach einem gelungenen Test |
| `maxFrame` | 1 048 576 | Bytes einer WebSocket-Nachricht der Box, **ganz** (Typ-Byte inklusive; Nutzbytes also höchstens `maxFrame − 1`) |
| `putsPerMinute` | 60 | `put` je Socket und Minute (Token-Eimer, Stoß bis 60); darüber schließt die Box mit 1008 |

Wiederholung nach einem Fehlschlag (`BACKOFF_SECONDS` in `src/schedule.js`): nach 30 s, 2 min und
10 min; danach, oder wenn der Versuch hinter der Frist läge, wird der Eintrag aufgegeben.

**Konstante ändern heißt PWA/Desktop mitziehen:** `pwa/reminders-plan.js` spiegelt `maxItems` als `MAX_ITEMS`
(200) und `maxAheadDays` als `MAX_AHEAD_MS` (89 Tage, einen Tag unter der Grenze). Das Rate-Limit (30 Anfragen/60 s) steht in `wrangler.toml`.

### Werte, die zusammenpassen müssen

- `[vars] VAPID_PUBLIC` in `wrangler.toml` = `VAPID_PUBLIC` in `pwa/relay-client.js`. Nie wechseln:
  alle Abos hängen am öffentlichen Schlüssel. Kein Test hält die beiden zusammen.
- `PAGES_ORIGIN` (`https://xveyn.github.io`) in `src/worker.js` ist die einzige erlaubte CORS-Origin
  (dazu `DEV_ORIGIN` aus `[vars]`, im Betrieb leer); zieht die PWA um, muss sie mit.
- `RELAY_URL` in `pwa/relay-client.js` = `RELAY_URL` in `src/push_relay.py` (Test in
  `tests/test_push_relay.py`).

## Box (Handy-Abgleich)

Das Durable Object `Box` (Binding `BOX`, Migration `v2`) ist ein Tunnel für den Abgleich zwischen Handy
und Desktop, wenn kein LAN dazwischen liegt (iOS, #358; Design `docs/superpowers/specs/2026-11-02-ios-relay-abgleich-design.md`).
Es hält **zwei ersetzbare Slots**: `req` (schreibt das Handy) und `res` (schreibt der Desktop), je
`{ver, data}`; es gibt keine Historie. Beide Seiten halten eine WebSocket über die **Hibernation API**
(Rolle = Tag am Socket, je Rolle höchstens eine Verbindung, eine neue ersetzt die alte). Die Nutzbytes sind
opak: kein JSON, keine Kryptografie im Relay, kein Logging.

**Ein** Geheimnis je Kopplung (43 Zeichen Base64url), das Objekt heißt `sha256(Geheimnis)`. Es steht im
Header `Sec-WebSocket-Protocol: zeit.v1, <Geheimnis>` (Browser können keine Header setzen); der Relay
antwortet `zeit.v1`.

| Route | Zweck |
|---|---|
| `GET /v1/box/ws?role=phone\|desktop[&have=<ver>]` | WebSocket-Upgrade. Beim Verbinden schickt der Relay den Slot des Gegenübers, wenn dessen `ver` größer als `have` ist (Standard 0). Fehler: `401 unauthorized`, `400 invalid_request`, `403 forbidden_origin`, `426 upgrade_required`, `429 rate_limited` |
| `DELETE /v1/box` | alles löschen (`Authorization: Bearer <Geheimnis>`), schließt beide Verbindungen |

Nachrichten sind binär, das erste Byte ist der Typ: `0x01 put` (Client → Relay, danach die Nutzbytes; der
Relay ersetzt den Slot der Absender-Rolle, zählt `ver` hoch, stellt dem Gegenüber zu und quittiert),
`0x02 slot` (Relay → Gegenüber: `ver` als 4 Byte big-endian + Nutzbytes), `0x03 ok` (Relay → Absender: `ver`
4 Byte big-endian). Unbekannte Typen werden still übergangen, Text schließt mit 1003.

- **`maxFrame`** (`LIMITS.maxFrame`, 1 048 576) gilt für die **ganze** Nachricht samt Typ-Byte; die Nutzbytes
  eines `put` sind also höchstens `maxFrame − 1`. Größer schließt mit 1009 (die Laufzeit kann schon früher
  mit 1009 schließen).
- **Put-Drossel** (`LIMITS.putsPerMinute`, 60): je Socket ein Token-Eimer im Speicher, der sich laufend
  auffüllt (Stoß bis 60). Ein `put` darüber wird weder geschrieben noch zugestellt, die Box schließt mit
  `1008 too many`. Grund: ein Socket mit gültigem Geheimnis könnte sonst das gemeinsame Schreibkontingent
  des Free-Plans (100 000 Zeilen/Tag) leeren. Der Stand liegt nur im Speicher; geht er im Ruhezustand
  verloren, beginnt der Eimer voll — harmlos, weil Senden im Drossel-Tempo das Objekt ohnehin wach hält.
- **Heartbeat:** der Client sendet eine **Text**-Nachricht, genau `ping`; die Plattform antwortet `pong`
  (`setWebSocketAutoResponse`), ohne das Objekt zu wecken, und der Ping zählt nicht gegen die Drossel.
  Jede andere Text-Nachricht schließt mit 1003.
- **`ver` ist monoton und zeitbasiert:** mindestens Sekunden seit 2026-01-01 UTC (`VER_EPOCH` in `box.js`),
  sonst Vorgänger + 1. Grund: das Aufräumen (Leerlauf, `DELETE /v1/box`) löscht den Zähler, das `have` der
  Clients bleibt; finge `ver` wieder bei 1 an, hielte ein Client jeden neuen Slot für bekannt. **Clients
  dürfen keine +1-Schritte annehmen**, nur „größer“ (bis ca. 2094 unter 2^31, der Grenze von `have`).
- **EU-Jurisdiktion:** das Objekt wird in Produktion **nur** über `env.BOX.jurisdiction('eu')` gewählt, nie über
  `idFromName` direkt. Das ist **nicht nachrüstbar** (gleicher Name = andere ID, die alten Slots wären
  weg). Der Worker selbst läuft pro Anfrage am nächsten Rand; die IP wird dort verarbeitet. Gesteuert über
  `[vars] BOX_JURISDICTION = "eu"` (`wrangler.toml`, Test hält es fest): `eu` (Standard) oder `none`, jeder
  andere Wert wirft (`500 internal`). `none` gibt es **nur** für `wrangler dev --var BOX_JURISDICTION:none`,
  weil das lokale workerd keine Jurisdiktionen kennt („not implemented in workerd“). **Produktion nie `none`.**
  `BOX_JURISDICTION` **nie im Cloudflare-Dashboard setzen:** das nächste `wrangler deploy` setzt den Wert
  zwar zurück, bis dahin legte `none` dort neue Objekte aber außerhalb der EU-Jurisdiktion an.
- **Selbstreinigung:** Alarm nach `idleDays` (90) ohne Aktivität, höchstens einmal am Tag neu gesetzt (jeder
  `setAlarm` ist ein Schreibvorgang im Kontingent).
- **`observability` bleibt aus** (`wrangler.toml`), und **das Subprotocol und die Query werden nie
  geloggt** (das Geheimnis steht im Header). „Kein Logging“ gilt für unseren Code; was die Plattform
  mitschreibt, steht in `docs/datenschutz.md`.
- **Konstante ändern heißt PWA/Desktop mitziehen:** `zeit.v1`, die Typ-Bytes, die Byte-Reihenfolge von `ver`,
  `maxFrame`, `putsPerMinute`, `ping`/`pong` und die Schließ-Codes (s. „Für die Clients“) stehen auf beiden Seiten (Desktop `relay_link.py` und PWA `RelayTransport`, spätere PRs).

### Für die Clients

Schließ-Codes der Box (`box.js`) und was der Client darauf tun muss:

| Code | Grund | Client |
|---|---|---|
| 1000 | `replaced` | eine neuere Verbindung derselben Rolle hat übernommen. **Nicht** automatisch neu verbinden: zwei Instanzen würden sich sonst endlos gegenseitig verdrängen |
| 1000 | `wiped` | die Box wurde geleert (`DELETE /v1/box` oder Leerlauf). `have` auf 0 setzen und normal weitermachen |
| 1003 | `binary only` | Text außer `ping` gesendet — Fehler im Client |
| 1008 | `too many` | über `putsPerMinute` gesendet. Zurückhalten (mindestens 60 s), dann neu verbinden |
| 1009 | `too large` | Nachricht über `maxFrame` — Fehler im Client (zu viel gesendet) |
| 1011 | (leer) | Fehler am Socket (`webSocketError`); mit Backoff neu verbinden |

- **`have` ist der `ver` des zuletzt empfangenen `slot`** des Gegenübers, **nicht** der `ver` aus einem `ok`:
  die beiden Slots zählen unabhängig.
- Rahmen-Typen vom Relay, die der Client nicht kennt, **muss** er übergehen — so kann später z. B. ein
  `0x04 peer` (Anwesenheit) dazukommen, ohne alte Clients zu brechen.
- PR 4 (Aufteilung großer Nachrichten) muss seinen Takt **unter** `putsPerMinute` (60/min) halten.

- Ablauf-Test: `node scripts/box-smoke.mjs [baseUrl]` gegen `npx wrangler dev --var BOX_JURISDICTION:none` prüft Zustellung, Wiederaufnahme
  mit `have`, falsches Subprotocol, `maxFrame + 1` und `DELETE`. Ein vom Server ausgelöstes Schließen
  (`DELETE`) sieht der Client erst nach rund 10 s (in `wrangler dev` und auf dem deployten Relay beobachtet, 2026-11-02).

## Dateien

- `src/validate.js` — Grenzen (`LIMITS`) und Prüfung aller Eingaben. Das Abo-Ziel ist auf die
  Push-Dienste der Browser **eingeschränkt** (FCM, `*.push.services.mozilla.com`,
  `*.push.apple.com`, `*.notify.windows.com`; kein Port, keine Zugangsdaten in der URL): ohne diese
  Liste wäre der Relay ein offener POST-Absender, der jede https-Adresse mit einem von uns signierten
  VAPID-Token anspricht. Ein neuer Push-Dienst muss hier eingetragen werden.
- `src/schedule.js` — was ist fällig, wann klingelt es, was nach einem Fehlschlag. Die **15 Minuten**
  Frist zählen ab der ersten Fälligkeit (`dueAt`), nicht ab einem Wiederholungsversuch.
- `src/push.js` — `sendPush` → `ok` / `gone` (404, 410) / `retry` (429, 5xx, Netzfehler) / `drop`.
  Wirft nie.
- `src/device.js` — das Durable Object. Der Alarm wird **immer aus dem gespeicherten Zustand neu
  berechnet** (nie im Konstruktor gesetzt), `alarm()` wirft nie (die Plattform begrenzt
  Wiederholungen auf 6; ein unbegrenzter Neustart verbrauchte die Anfragen des Free-Plans).
- `src/box.js` — das Durable Object `Box` (Handy-Abgleich, s. „Box“ oben).
- `src/frames.js` — Nachrichtenrahmen der Box (`put`/`slot`/`ok`); nur `Uint8Array`/`DataView`.
- `src/ws-platform.js` — die zwei Plattformaufrufe, die Node nicht kennt (`WebSocketPair`, `Response` mit Status 101); die Tests ersetzen sie durch `test/box-fakes.js`.
- `scripts/box-smoke.mjs` — Ablauf-Test der Box gegen ein laufendes `npx wrangler dev` (echtes workerd; die Unit-Tests nutzen Fakes).
- `src/worker.js` — Routen, Auth, CORS. CORS (Antwort-Header) nur für `https://xveyn.github.io` (und `DEV_ORIGIN`); beim WebSocket-Upgrade der Box gilt dieselbe Liste als Origin-Prüfung (fremde Origin → `403 forbidden_origin`, keine Origin = Desktop erlaubt).
  Davor das Rate-Limit je Absender-Adresse, IPv6 als /64 (Binding `LIMITER`, 30 Anfragen/60 s; fehlt es oder wirft es,
  geht die Anfrage durch). Je Adresse, nicht je Geheimnis — ein Angreifer erfindet beliebig viele Geheimnisse.
  Eine WAF-Regel im Dashboard geht hier nicht: sie braucht eine Zone, `workers.dev` ist keine.
- `scripts/gen-vapid.mjs` — erzeugt das VAPID-Paar.

## Regeln

- **Kein Logging** von Geheimnis, Abo, Blob oder Zeitplan, auch nicht in Fehlerpfaden. Ein
  Test (`worker.test.js`) hält das fest.
- **Kein `Buffer`** im Laufzeitcode: Workers kennt es nur mit `nodejs_compat`. Test-Code darf es.
- **KV ist ungeeignet** (laut Sekundärquellen nur 1.000 Schreibvorgänge/Tag auf dem Free-Plan);
  Zustand liegt im SQLite-gestützten Durable Object.
- **Ausgerollt wird von `.github/workflows/relay-deploy.yml`** nach dem Merge auf `master` (Environment `relay-production`, Secrets `CLOUDFLARE_API_TOKEN`/`CLOUDFLARE_ACCOUNT_ID` nur im Schritt „Ausrollen“; Einrichtung in `README.md`). Ein Test hält die Sicherheitsmerkmale fest (`tests/test_relay_deploy.py`). Von Hand geht `npx wrangler deploy` weiter.
- Die Tests laufen mit `node --test` ohne `wrangler`; `device.js` wird mit einem In-Memory-Speicher
  (`test/fake-storage.js`) getestet. `wrangler dev` braucht **Node ≥ 22** (`engines`).
- Wer eine Konstante in `LIMITS` oder die Routen ändert, zieht die PWA und das Design mit (s. „Konstante ändern heißt PWA mitziehen“ oben).

## Gemessen

Am 2026-10-22 auf dem Free-Plan, Chrome (FCM): ein Gerät, erst 1 Erinnerung (`jetzt + 60 s`), dann der
Worst Case aus 200 Erinnerungen zu je 1024 Zeichen (erste nach 60 s, weitere im 5-s-Takt).

- **CPU-Zeit** (Dashboard, Worker): P50 3,3 ms, P90/P99/P999 je 3,47 ms — unter dem Limit von 10 ms.
- **Wall-Time** P99 5,1 s (Warten auf den Push-Dienst, auf Free nicht begrenzt), **Speicher** P99 2,1 MB.
- **Fehler:** 0 (kein `exceededCpu`). Ob alle 200 Benachrichtigungen ankamen, wurde nicht Stück für Stück gezählt.

Gemessen mit einer lokalen Testseite gegen den deployten Relay, nicht mit dem Ablauf der PWA: Blob
und Zeitplan waren Platzhalter. Ändern sich Blobgröße, Anzahl oder Sendeweg, neu messen.

Am 2026-11-02 gegen den deployten Relay (Node-Client, `wss://`, 25 min untätig, je eine Box-Verbindung):

- **Heartbeat:** Text `ping` wird immer mit `pong` beantwortet (49/49 bei 30 s, 24/24 bei 60 s, 12/12 bei 120 s).
- **Leerlauf:** Verbindungen **ohne** Heartbeat blieben die 25 min offen; die Plattform schließt eine ruhende Box-WebSocket nicht von sich aus. Ein Lauf verlor die 60-s-Verbindung nach 1417 s mit 1006 (Verbindungsabbruch, nicht vom Relay) — Clients müssen jederzeit wiederverbinden (mit `have`). Ein Heartbeat von 60–120 s ist für Mobilnetze und NAT sinnvoll, der Relay braucht ihn nicht.
- **Serverseitiges Schließen** (`DELETE /v1/box`) erreicht den Client erst nach rund 10 s (auch deployt).
- **Smoke-Test** (`scripts/box-smoke.mjs`, deployt): alle Prüfungen bestanden, 1-MiB-Nachricht, EU-Jurisdiktion ohne Fehler.
- **Dashboard (Worker, Version d41abbe8, ca. 34 min nach dem Deploy, Smoke-Test + 2 Heartbeat-Läufe):** 28 Aufrufe, 24 Subrequests, 0 Fehler (kein `exceededCpu`, kein `exceededMemory`). **CPU-Zeit** P50 1,67 ms, P90 3,2 ms, P99/P999 5,74 ms (Grenze 10 ms); **Speicher** P50 1,66 MB, P90/P99 1,9 MB; **Anfragedauer** P50 0, P90 2,53 ms, P99 65,19 ms; **Wall-Time** P50 10 s, P90/P99 ca. 2 000 s (offene WebSocket-Verbindungen zählen als Wall-Time des Aufrufs; auf Free nicht begrenzt).
- **Heartbeats zählen nicht als Aufrufe:** die drei Läufe schickten über 170 `ping` je Lauf, im Dashboard stehen insgesamt nur 28 Aufrufe — Auto-Response-Nachrichten und `put`/`slot` über eine bestehende Verbindung erscheinen nicht als Worker-Aufrufe (nur der Verbindungsaufbau).
- **Nicht gemessen:** das Worker-Dashboard zeigt **nicht** das Durable Object. CPU-Zeit je 1-MiB-`put`, Dauer (GB-s) im Leerlauf und DO-Anfragen/Zeilen stehen unter Workers → Durable Objects → `Box` (Metrics) und sind noch nicht abgelesen; ebenso ob Auto-Responses das 20:1-Kontingent der DO-Anfragen berühren.
