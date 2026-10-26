# Push-Relay einrichten

Der Relay ist ein Cloudflare Worker (kostenloser Plan genügt). Er hält je Handy ein Abo und einen
Zeitplan und sendet zur Fälligkeit eine verschlüsselte Web-Push-Nachricht. Er sieht **Zeitpunkte, das
Abo und ein verschlüsseltes Blob**, keine Arbeitszeiten, Kategorien oder Namen.

Das braucht nur, wer den Relay selbst betreibt. Für die Entwicklung und die Tests ist nichts davon nötig
(`cd relay && npm ci && node --test`).

1. **Cloudflare-Konto** (kostenlos) auf dash.cloudflare.com anlegen.
2. **Node ≥ 22 und `wrangler`**: `cd relay && npm ci`, dann `npx wrangler login` (öffnet den Browser).
   Hat der Rechner nur Node 20: `npm i --no-save node@22` legt Node 22 nach `node_modules/node/bin`, das
   man für die `wrangler`-Befehle vorn in den `PATH` setzt.
3. **VAPID-Schlüssel erzeugen:** `node scripts/gen-vapid.mjs`. Der **öffentliche** Schlüssel
   (`VAPID_PUBLIC`) kommt in `wrangler.toml` unter `[vars]` und in die PWA, der **private** nur als
   Secret (Schritt 5). Den privaten Schlüssel nie einchecken und nicht in ein Chatfenster kopieren, und nach
   dem Veröffentlichen **nie wechseln**: alle Abos hängen am öffentlichen.
4. **Veröffentlichen:** `npx wrangler deploy`. Beim ersten Mal fragt `wrangler` nach der
   workers.dev-Subdomain (einmalig, ein frei gewählter Name); daraus entsteht
   `https://zeiterfassung-push.<subdomain>.workers.dev`, die ausgegebene URL ist die des Relays.
   Zuerst veröffentlichen, dann die Secrets setzen: sie gehören zu einem bestehenden Worker.
5. **Secrets setzen:** `npx wrangler secret put VAPID_PRIVATE` (den privaten Schlüssel einfügen) und
   `npx wrangler secret put VAPID_SUBJECT` mit `mailto:<adresse>` (Push-Dienste dürfen den Betreiber
   darüber erreichen; die Adresse sollte öffentlich sein dürfen). Secrets wirken ohne erneutes `deploy`.
6. **Prüfen:** `curl -i -X PUT <url>/v1/device` ohne Header muss `401 {"error":"unauthorized"}` liefern.
7. **Messen** (nur bei einem eigenen Relay oder geänderter Blobgröße, Anzahl oder Sendeweg): ein Testgerät
   registrieren und einen Zeitplan `jetzt + 60 s` senden — der Push muss ankommen. Im Dashboard
   (Workers → zeiterfassung-push → Metrics) die **CPU-Zeit** je Anfrage und je Alarm ablesen (Free-Plan:
   10 ms je HTTP-Anfrage). Die Messung für den Relay des Projekts (2026-10-22: P99 3,5 ms) steht in
   `relay/CLAUDE.md` unter „Gemessen"; dort nachschlagen, nur bei neuer Messung ergänzen.
8. **Optional, erst danach:** Deploy aus GitHub Actions, s. „Deploy aus GitHub Actions“ unten. Gegen Massen-Registrierung begrenzt der Relay selbst je Absender-Adresse (`[[ratelimits]]` in `wrangler.toml`); eine Regel im Dashboard braucht eine eigene Domain und entfällt.

## Deploy aus GitHub Actions

Der Workflow `.github/workflows/relay-deploy.yml` rollt den Relay nach einem Merge auf `master` aus, sobald sich etwas unter `relay/` (oder am Workflow) ändert; von Hand geht es über Actions → „Relay veröffentlichen“ → „Run workflow“. Ein Job: `npm ci`, `node --test`, `wrangler deploy`, danach ein Smoke-Check (`PUT /v1/device` ohne Header muss `401` liefern). Das Gate ist der Merge selbst; eine zweite Freigabe je Deploy gibt es nicht. **Der erste Deploy (Schritt 4 oben, der die workers.dev-Subdomain anlegt) und das Setzen der Worker-Secrets (Schritt 5) erfolgen von Hand;** der Workflow ersetzt sie nicht, er rollt nur Änderungen an einem bestehenden Worker aus. Im PR prüft der `relay`-Job die Konfiguration mit `wrangler deploy --dry-run`, ohne Token.

**Einmalig einrichten** (steht nicht im Code):
1. Cloudflare → My Profile → API Tokens → neuen Token aus der Vorlage „Edit Cloudflare Workers“ anlegen, auf dein Konto beschränkt. Ein eigener Token nur für die CI, damit er sich getrennt widerrufen lässt. Die Konto-ID steht in der Dashboard-URL.
2. GitHub → Settings → Environments → **`relay-production`** anlegen. „Deployment branches“: nur `master`. **Keine** Required reviewers nötig (der Merge ist das Gate).
3. Die zwei Secrets **im Environment** setzen (nicht im Repo), im eigenen Terminal, damit nichts im Chat landet:
   `gh secret set CLOUDFLARE_API_TOKEN --env relay-production` und
   `gh secret set CLOUDFLARE_ACCOUNT_ID --env relay-production`.

Fehlt eines der Secrets, scheitert der Lauf mit einer klaren Meldung, bevor etwas ausgerollt wird. Die Worker-Secrets (`VAPID_PRIVATE`, `VAPID_SUBJECT`) und die Daten bleiben bei Cloudflare und werden vom Deploy nicht angefasst. Der Token liegt nur im Schritt „Ausrollen“, nie in einem Schritt, der Code aus `node_modules` ausführt.

## Aktualisieren

Nach einer Änderung am Relay **zuerst den Relay ausrollen** (hast du Schritt 8 eingerichtet, geschieht das automatisch nach dem Merge; sonst von Hand: `git pull`, dann `cd relay && npm ci && npx wrangler deploy`), erst dann Web-App und Desktop: neue Routen (zuletzt `POST /v1/test`) kennt ein alter Relay nicht und antwortet `404 not_found`; Web-App und Desktop melden das als „Der Relay kennt den Test noch nicht“. Die Secrets (`VAPID_PRIVATE`, `VAPID_SUBJECT`) und die Durable-Object-Daten bleiben beim Deploy erhalten.

## Lokal ausprobieren

`.dev.vars` (ignoriert) mit `VAPID_PUBLIC`, `VAPID_PRIVATE`, `VAPID_SUBJECT` anlegen, dann `npx wrangler dev`.
Für die PWA vom Dev-Server (`http://localhost:8099`) `DEV_ORIGIN` setzen.
