# Push-Relay (Cloudflare Worker) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Der Relay aus dem Design (`relay/`): ein Worker mit einem Durable Object je Handy, der den Zeitplan hält und zur Fälligkeit verschlüsselte Web-Push-Nachrichten sendet. PR 2 von 5; noch ohne Verbraucher (PWA und Desktop folgen).

**Architecture:** Reine Module (`validate`, `schedule`, `push`) tragen die Entscheidungen und sind mit `node --test` getestet; `device.js` (Durable Object) und `worker.js` sind dünne Hüllen darüber, getestet mit einem In-Memory-Speicher statt `workerd`. Der Alarm steht immer auf dem nächsten `fire_at`, ersatzweise auf dem Leerlauf-Ablauf.

**Tech Stack:** Cloudflare Workers + SQLite-gestützte Durable Objects, `@block65/webcrypto-web-push` 2.0.0 (gepinnt), `wrangler` (Node ≥ 22), `node --test`, keine weiteren Laufzeit-Abhängigkeiten.

**Spec:** `docs/superpowers/specs/2026-10-21-pwa-push-erinnerungen-design.md` (Abschnitte „Relay“, „Was der Relay sieht“, „CI und Veröffentlichung“, „Was du einrichten musst“)

## Global Constraints

- Routen (JSON): `PUT /v1/device`, `PUT /v1/schedule`, `DELETE /v1/device`; CORS **nur** für `https://xveyn.github.io` (plus `http://localhost:8099` nur bei gesetzter Variable `DEV_ORIGIN`).
- Auth: Bearer-Geheimnis, 43 Zeichen base64url (256 Bit); das Durable Object heißt `sha256(Geheimnis)` als Hex. Es gibt keine getrennte Geräte-ID.
- Grenzen: höchstens **200** Einträge, `fire_at` höchstens **90 Tage** voraus, Blob höchstens **1024** Zeichen; `fire_at` im Format `YYYY-MM-DDTHH:MM:SSZ`; Eintrags-`id` `[A-Za-z0-9_-]{1,64}`.
- Überfällige Einträge: bis **15 min** (900 s) nach `fire_at` noch senden, danach verwerfen.
- Push-Antworten: `404`/`410` → Abo tot, alles löschen; `429`/`5xx`/Netzfehler → Wiederholung mit Backoff **30 s, 120 s, 600 s** (danach verworfen oder durch das 15-min-Fenster); andere `4xx` → Eintrag verwerfen.
- Selbstreinigung: Leerlauf-Ablauf **90 Tage** nach der letzten Aktualisierung löscht das Objekt.
- Push-Parameter: `ttl` 300, `urgency: 'high'`; VAPID aus `env.VAPID_PUBLIC`, `env.VAPID_PRIVATE`, `env.VAPID_SUBJECT`.
- **Kein Logging** von Abo, Blob, Zeitplan oder Geheimnis.
- Node ≥ 22 für `wrangler`; Tests laufen mit `node --test` ohne `wrangler`.
- Kommentare, Fehlertexte und Doku auf Deutsch, Code-Stil wie `pwa/` (ESM, reine Module ohne Browser-API).

## Review Focus

- Zwei Anfragen mit **verschiedenen** Geheimnissen dürfen nie dasselbe Objekt erreichen (Objektname aus dem Hash, nicht aus dem Rohwert); getestet in Task 6.
- `PUT /v1/schedule` ohne vorheriges `PUT /v1/device` darf kein Objekt mit leerem Abo hinterlassen, das später sendet oder abstürzt (Antwort `409 no_subscription`); Task 5/6.
- Ein **leerer** Zeitplan (`items: []`) ersetzt den alten (löscht ihn) und lässt nur den Leerlauf-Ablauf stehen; Task 5.
- Ein `fire_at` in der Vergangenheit, innerhalb von 15 min, wird beim Speichern **nicht** verworfen und beim nächsten Alarm gesendet; ein älteres schon; Task 3.
- Ein Push-Fehler bei **einem** Eintrag verhindert nicht das Senden der übrigen fälligen; Task 5.
- Überlange oder falsch typisierte Felder (`blob` Zahl, `items` Objekt, doppelte `id`) liefern `400 invalid_request`, nie eine 500; Task 2/6.
- Ein vom Browser verworfenes Abo (`410`) räumt das Objekt auf, ohne dass der nächste Alarm einen Fehler wirft; Task 5.

---

### Task 1: Gerüst, CI-Job und VAPID-Skript

**Files:**
- Create: `relay/package.json`, `relay/wrangler.toml`, `relay/.gitignore`, `relay/scripts/gen-vapid.mjs`
- Create: `relay/test/gen-vapid.test.js`
- Modify: `.github/workflows/test.yml` (Job `relay` nach dem Muster von `pwa`, Zeile 228ff)

**Interfaces:**
- Produces: `generateVapid(): Promise<{ publicKey: string, privateKey: string }>` aus `relay/scripts/gen-vapid.mjs` (Public = Base64url der 65 Roh-Bytes, Private = Base64url von `d`, 43 Zeichen); das Skript druckt bei direktem Aufruf `VAPID_PUBLIC=…` / `VAPID_PRIVATE=…`.

- [ ] **Step 1: Test `generateVapid returns a P-256 pair in the format the push library imports`** — Public dekodiert zu 65 Bytes mit erstem Byte `0x04`, Private zu 32 Bytes, beide ohne `=`/`+`/`/`, und die beiden importieren sich als ECDSA-JWK (`x`/`y` aus Public, `d` aus Private) ohne Fehler.
- [ ] **Step 2: Test laufen lassen** — `node --test` in `relay/` → FAIL (Modul fehlt).
- [ ] **Step 3: `package.json` anlegen** — `"private": true`, `"type": "module"`, `"engines": {"node": ">=22"}`, Skripte `test` (`node --test`) und `dev` (`wrangler dev`), Abhängigkeiten **exakt** gepinnt: `@block65/webcrypto-web-push` `2.0.0`, `wrangler` als devDependency (aktuelle Version zum Zeitpunkt der Umsetzung, exakt). `wrangler.toml`: Name `zeiterfassung-push`, `main = "src/worker.js"`, aktuelles `compatibility_date`, Binding `DEVICE` → Klasse `Device`, Migration `v1` mit `new_sqlite_classes = ["Device"]`, `[vars] DEV_ORIGIN = ""`, `VAPID_SUBJECT` bewusst **nicht** committet (Secret/Var beim Einrichten). `.gitignore`: `node_modules`, `.dev.vars`, `.wrangler`.
- [ ] **Step 4: `generateVapid` in `scripts/gen-vapid.mjs` implementieren** (Vorlage: Spike, ECDSA P-256 über `crypto.subtle`, `export` der Funktion, Ausgabe nur bei direktem Aufruf).
- [ ] **Step 5: Job `relay` in `test.yml`** — `needs: changes`, `if: needs.changes.outputs.code == 'true'`, `actions/setup-node@v7` mit `node-version: '22'`, `npm ci` und `node --test` mit `working-directory: relay`; Kommentar wie bei `pwa` (kein Required Check, Aufnahme entscheidet der Maintainer). `package-lock.json` erzeugen und einchecken.
- [ ] **Step 6: Verifizieren** — `cd relay && npm ci && node --test` → PASS; `npx yaml-lint`/`ruff` nicht nötig, `python -m pytest tests/test_claude_md_claims.py -q` → PASS (die Workflow-Behauptungen bleiben gültig).
- [ ] **Step 7: Commit** `feat(relay): Gerüst, CI-Job und VAPID-Skript (#331)`

### Task 2: Anfragen prüfen (`relay/src/validate.js`)

**Files:**
- Create: `relay/src/validate.js`, `relay/test/validate.test.js`

**Interfaces:**
- Produces:
  - `export const LIMITS = { maxItems: 200, maxAheadDays: 90, maxBlob: 1024, graceSeconds: 900, idleDays: 90 }`
  - `export class InvalidRequest extends Error` (`message` auf Deutsch)
  - `parseSubscription(body: unknown): { endpoint: string, keys: { p256dh: string, auth: string } }` — `endpoint` muss `https:` sein, `p256dh` Base64url (65 Bytes), `auth` Base64url (16 Bytes)
  - `parseSchedule(body: unknown, now: number): Array<{ id: string, fireAt: number, blob: string }>` — `fireAt` in ms; Einträge, die älter als `graceSeconds` sind, werden **still verworfen**; Einträge hinter `maxAheadDays` oder Überschreiten der Grenzen werfen `InvalidRequest`
  - `parseSecret(header: string | null): string` — 43 Zeichen Base64url, sonst `InvalidRequest`

- [ ] **Step 1: Tests** — je Fall ein Test mit dem Namen der Regel: `rejects a non-https endpoint`, `rejects keys of the wrong length`, `rejects duplicate ids`, `rejects more than 200 items`, `rejects fire_at beyond 90 days`, `silently drops items older than 15 minutes`, `keeps an item 14 minutes late`, `accepts an empty items list`, `rejects blob of 1025 characters`, `rejects non-object body`, `rejects fire_at that is not YYYY-MM-DDTHH:MM:SSZ (including a valid-looking 2026-09-31)`, `parseSecret rejects a short, long or non-base64url secret`.
- [ ] **Step 2: FAIL sehen**, **Step 3:** `validate.js` implementieren (reine Funktionen, Datum streng mit Rundlauf-Prüfung wie `isIsoDate` in `pwa/minutes.js`), **Step 4:** PASS, **Step 5:** Commit `feat(relay): Anfragen prüfen (#331)`.

### Task 3: Zeitplan-Logik (`relay/src/schedule.js`)

**Files:**
- Create: `relay/src/schedule.js`, `relay/test/schedule.test.js`

**Interfaces:**
- Consumes: `LIMITS` aus `validate.js`.
- Produces:
  - `planAlarm(items: Item[], now: number, idleAt: number): { due: Item[], keep: Item[], alarmAt: number }` — `due` = alle mit `fireAt <= now` und `now - fireAt <= graceSeconds*1000`; ältere fallen weg; `keep` = noch nicht fällige; `alarmAt` = frühester `fireAt` in `keep`, sonst `idleAt`, nie später als `idleAt`.
  - `afterFailure(item: Item & { attempts?: number }, now: number): (Item & { attempts: number }) | null` — erhöht `attempts`, setzt `fireAt = now + Backoff[attempts]` (30 s, 120 s, 600 s) und gibt `null` zurück, wenn die Frist (`originalFireAt + graceSeconds`) überschritten wäre oder keine Stufe mehr da ist. Das ursprüngliche `fireAt` bleibt als `dueAt` erhalten, damit die 15 Minuten ab der **ersten** Fälligkeit zählen.
  - `idleAt(now: number): number` = `now + idleDays` Tage.

- [ ] **Step 1: Tests** — `due and keep are split at now`, `an item 16 minutes late is dropped, 14 minutes late is due`, `alarmAt is the earliest keep item`, `alarmAt falls back to idleAt for an empty plan`, `alarmAt never exceeds idleAt`, `afterFailure backs off 30 s then 120 s then 600 s`, `afterFailure returns null once 15 minutes after the first due time have passed`, `dueAt survives repeated failures`.
- [ ] **Step 2–4:** FAIL → implementieren → PASS. **Step 5:** Commit `feat(relay): Zeitplan-Logik (#331)`.

### Task 4: Push senden (`relay/src/push.js`)

**Files:**
- Create: `relay/src/push.js`, `relay/test/push.test.js`

**Interfaces:**
- Consumes: `buildPushPayload` aus `@block65/webcrypto-web-push`.
- Produces: `sendPush(subscription, blob: string, env: { VAPID_PUBLIC, VAPID_PRIVATE, VAPID_SUBJECT }, fetchFn = fetch): Promise<'ok' | 'gone' | 'retry' | 'drop'>` — `2xx` → `ok`, `404`/`410` → `gone`, `429`/`5xx`/geworfener Netzfehler → `retry`, übrige → `drop`. Nachricht `{ data: blob, options: { ttl: 300, urgency: 'high' } }`. Wirft nie.

- [ ] **Step 1: Tests mit gefälschtem `fetchFn` und einem echten, im Test erzeugten Abo-Paar** (ECDH P-256 + 16 zufällige Auth-Bytes): `maps 201 to ok`, `maps 404 and 410 to gone`, `maps 429, 500 and 503 to retry`, `maps 400 and 413 to drop`, `maps a thrown fetch to retry`, `sends an aes128gcm body with a vapid authorization header` (Header beginnt mit `vapid t=`, enthält `k=` mit dem öffentlichen Schlüssel; `content-encoding: aes128gcm`; `ttl` 300), `does not throw for a malformed key`.
- [ ] **Step 2–4:** FAIL → `sendPush` implementieren → PASS. **Step 5:** Commit `feat(relay): Push senden und Antwort einordnen (#331)`.

### Task 5: Durable Object (`relay/src/device.js`)

**Files:**
- Create: `relay/src/device.js`, `relay/test/device.test.js`, `relay/test/fake-storage.js` (In-Memory-Ersatz für `ctx.storage` mit `get`/`put`/`delete`/`deleteAll`/`setAlarm`/`getAlarm`/`deleteAlarm`)

**Interfaces:**
- Consumes: `parseSubscription`, `parseSchedule`, `LIMITS` (Task 2); `planAlarm`, `afterFailure`, `idleAt` (Task 3); `sendPush` (Task 4).
- Produces: `export class Device` mit
  - `constructor(ctx, env, { now = Date.now, send = sendPush } = {})`
  - `fetch(request: Request): Promise<Response>` — intern: `PUT /v1/device` → speichert Abo, setzt Leerlauf-Alarm, `204`; `PUT /v1/schedule` → ohne Abo `409 { error: 'no_subscription' }`, sonst ersetzt den Zeitplan, setzt `planAlarm`, `204`; `DELETE /v1/device` → `deleteAll()` + `deleteAlarm()`, `204`; ungültige Eingabe `400 { error: 'invalid_request', message }`
  - `alarm(): Promise<void>` — sendet alle `due` einzeln (ein Fehler stoppt die übrigen nicht), `gone` → `deleteAll`, `retry` → `afterFailure`, setzt den nächsten Alarm; **wirft nie** (sonst begrenzt die Plattform die Wiederholungen auf 6).
  - Beim Start prüft `constructor`/Zugriff `getAlarm()`, bevor `setAlarm` gesetzt wird (nie einen anstehenden Alarm überschreiben).

- [ ] **Step 1: Tests (mit `fake-storage` und gefälschten `now`/`send`)** — `registering stores the subscription and arms the idle alarm`, `schedule without a subscription is 409 and leaves no state`, `schedule replaces the previous one`, `an empty schedule clears items and leaves only the idle alarm`, `alarm sends each due item once and sets the alarm to the next`, `a failing item does not stop the others`, `gone deletes everything and leaves no alarm`, `retry reschedules with backoff and keeps the original due time`, `an item more than 15 minutes late is dropped without sending`, `alarm never throws, even when send throws`, `delete removes state and alarm`, `invalid body is 400 with a German message, not a throw`, `schedule update moves the idle expiry`.
- [ ] **Step 2–4:** FAIL → implementieren (Zustand unter den Schlüsseln `sub`, `items`, `idle`) → PASS. **Step 5:** Commit `feat(relay): Durable Object je Handy mit Alarm (#331)`.

### Task 6: Worker (`relay/src/worker.js`)

**Files:**
- Create: `relay/src/worker.js`, `relay/test/worker.test.js`

**Interfaces:**
- Consumes: `parseSecret` (Task 2), `Device` (Task 5, re-exportiert für das Binding).
- Produces: `export { Device }`, `export default { fetch(request, env): Promise<Response> }`; zusätzlich `objectName(secret: string): Promise<string>` (`sha256` hex) für Tests.

- [ ] **Step 1: Tests mit gefälschtem `env.DEVICE` (`idFromName`/`get`)** — `routes the three endpoints to the device named after the secret hash`, `two different secrets reach two different objects`, `a missing or malformed Authorization header is 401 without touching a device`, `unknown routes are 404`, `wrong method is 405`, `preflight from the Pages origin gets CORS headers, other origins none`, `responses carry Access-Control-Allow-Origin only for the allowed origin`, `a thrown error inside the device is 500 without echoing details or the secret`, `no request path logs the secret` (Konsolen-Spion).
- [ ] **Step 2–4:** FAIL → implementieren → PASS. **Step 5:** Commit `feat(relay): Worker mit Routen, Auth und CORS (#331)`.

### Task 7: Dokumentation

**Files:**
- Create: `relay/CLAUDE.md`, `relay/README.md` (Einrichtung, Schritte 1–7 aus dem Design in der Reihenfolge, mit den Befehlen)
- Modify: `CLAUDE.md` (Eintrag `relay/` in „Struktur“ und der `relay`-Job in „Tests / CI“, Muster wie `pwa`), `docs/known-limitations.md` (neuer Abschnitt „Push-Relay: neuer Vertrauens-Ort“ — was der Relay sieht, nicht sieht, Betreiber, Abhängigkeit von Cloudflare)
- Test: `tests/test_claude_md_claims.py` bleibt grün

- [ ] **Step 1:** Texte schreiben (Abschnitt „Was der Relay sieht“ des Designs übernehmen, keine zweite Fassung erfinden), **Step 2:** `pytest tests/test_claude_md_claims.py tests/test_catch_all_handlers.py -q` → PASS und `cd relay && node --test` → PASS, **Step 3:** Commit `docs(relay): Einrichtung, Vertrauens-Ort, Struktur (#331)`.

### Task 8: Erster Deploy und Messung (manuell, mit dem Nutzer)

Kein Code, ein Prüfpunkt; ohne ihn ist der Relay **nicht** freigegeben.

- [ ] **Step 1:** Nutzer richtet Konto, Subdomain, VAPID-Secret ein (`relay/README.md`), `npx wrangler deploy`.
- [ ] **Step 2:** Zwei Testgeräte (Chrome, Firefox) registrieren sich über `curl`/Testseite, Zeitplan mit `fire_at = jetzt + 60 s` → Push kommt.
- [ ] **Step 3:** In Cloudflares Metriken die **CPU-Zeit** je Anfrage und Alarm ablesen (Free-Plan-Limit 10 ms je HTTP-Anfrage); Ergebnis in `relay/CLAUDE.md` eintragen. Überschreitung oder unzuverlässige Alarme → Entscheidung beim Nutzer (bezahlter Plan oder Cron), nicht beim Builder.
- [ ] **Step 4:** PR-Beschreibung nennt die gemessenen Werte; erst dann Merge.
