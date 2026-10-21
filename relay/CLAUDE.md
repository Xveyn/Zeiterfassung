# CLAUDE.md — `relay/` (Push-Relay)

Cloudflare Worker, der Erinnerungen als Web-Push an die Handy-PWA schickt, **ohne dass der Desktop
läuft** (#331). Wird wie `pwa/` nicht in die App gebündelt und von keinem Python-Modul importiert.
Design: `docs/superpowers/specs/2026-10-21-pwa-push-erinnerungen-design.md`; Einrichtung: `README.md`.

## Modell

Das Handy ersetzt seinen Zeitplan beim Relay (`PUT /v1/schedule`), der Relay sendet zur Fälligkeit.
**Es gibt keine Konten und keine Geräte-ID:** das Handy erzeugt ein Geheimnis (43 Zeichen
Base64url, 256 Bit), und das Durable Object heißt `sha256(Geheimnis)`. Wer das Geheimnis nicht
kennt, erreicht das Objekt nicht und kann es nicht besetzen.

| Route | Zweck |
|---|---|
| `PUT /v1/device` | Abo (`endpoint`, `keys.p256dh`, `keys.auth`) registrieren oder erneuern |
| `PUT /v1/schedule` | Zeitplan **ersetzen**: `{items: [{id, fire_at, blob}]}` |
| `DELETE /v1/device` | alles löschen |

Fehler: `401 unauthorized` (Geheimnis fehlt/ungültig), `400 invalid_request` (mit deutscher
`message`), `409 no_subscription` (Zeitplan vor Abo), `404`, `405`, `500 internal` (ohne Details).

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
- `src/worker.js` — Routen, Auth, CORS. CORS nur für `https://xveyn.github.io` (und `DEV_ORIGIN`).
- `scripts/gen-vapid.mjs` — erzeugt das VAPID-Paar.

## Regeln

- **Kein Logging** von Geheimnis, Abo, Blob oder Zeitplan, auch nicht in Fehlerpfaden. Ein
  Test (`worker.test.js`) hält das fest.
- **Kein `Buffer`** im Laufzeitcode: Workers kennt es nur mit `nodejs_compat`. Test-Code darf es.
- **KV ist ungeeignet** (laut Sekundärquellen nur 1.000 Schreibvorgänge/Tag auf dem Free-Plan);
  Zustand liegt im SQLite-gestützten Durable Object.
- Die Tests laufen mit `node --test` ohne `wrangler`; `device.js` wird mit einem In-Memory-Speicher
  (`test/fake-storage.js`) getestet. `wrangler dev` braucht **Node ≥ 22** (`engines`).
- Wer eine Konstante in `LIMITS` oder die Routen ändert, zieht die PWA und das Design mit.

## Gemessen

Offen bis zum ersten Deploy (`README.md`, Schritt „Messen"): CPU-Zeit gegen das Limit von 10 ms je
Anfrage (Free-Plan) und das Alarmverhalten dort. Hier eintragen, sobald gemessen.
