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
7. **Messen** (einmalig, bevor die PWA ihn benutzt): ein Testgerät registrieren und einen Zeitplan
   `jetzt + 60 s` senden — der Push muss ankommen. Im Dashboard (Workers → zeiterfassung-push →
   Metrics) die **CPU-Zeit** je Anfrage und je Alarm ablesen (Free-Plan: 10 ms je HTTP-Anfrage) und in
   `relay/CLAUDE.md` unter „Gemessen" eintragen.
8. **Optional, später:** Deploy aus GitHub Actions (API-Token mit der Vorlage „Edit Cloudflare Workers" und
   die Konto-ID als Repo-Secrets `CLOUDFLARE_API_TOKEN` und `CLOUDFLARE_ACCOUNT_ID`) und eine
   Rate-Limit-Regel im Dashboard gegen Massen-Registrierung.

## Lokal ausprobieren

`.dev.vars` (ignoriert) mit `VAPID_PUBLIC`, `VAPID_PRIVATE`, `VAPID_SUBJECT` anlegen, dann `npx wrangler dev`.
Für die PWA vom Dev-Server (`http://localhost:8099`) `DEV_ORIGIN` setzen.
