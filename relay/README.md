# Push-Relay einrichten

Der Relay ist ein Cloudflare Worker (kostenloser Plan genügt). Er hält je Handy ein Abo und einen
Zeitplan und sendet zur Fälligkeit eine verschlüsselte Web-Push-Nachricht. Er sieht **Zeitpunkte, das
Abo und ein verschlüsseltes Blob**, keine Arbeitszeiten, Kategorien oder Namen.

Das braucht nur, wer den Relay selbst betreibt. Für die Entwicklung und die Tests ist nichts davon nötig
(`cd relay && npm ci && node --test`).

1. **Cloudflare-Konto** (kostenlos) auf dash.cloudflare.com anlegen.
2. **workers.dev-Subdomain wählen** (Dashboard → Workers & Pages → Subdomain, einmalig). Daraus
   entsteht `https://zeiterfassung-push.<subdomain>.workers.dev`.
3. **Node ≥ 22 und `wrangler`**: `cd relay && npm ci`, dann `npx wrangler login` (öffnet den Browser).
4. **VAPID-Schlüssel erzeugen:** `node scripts/gen-vapid.mjs`. Der **öffentliche** Schlüssel
   (`VAPID_PUBLIC`) kommt in `wrangler.toml` unter `[vars]` und in die PWA, der **private** nur als
   Secret: `npx wrangler secret put VAPID_PRIVATE`. Den privaten Schlüssel nie einchecken, und nach dem
   Veröffentlichen **nie wechseln**: alle Abos hängen am öffentlichen.
5. **Kontakt festlegen:** `npx wrangler secret put VAPID_SUBJECT` mit `mailto:<adresse>`. Push-Dienste
   dürfen den Betreiber darüber erreichen; die Adresse sollte öffentlich sein dürfen.
6. **Veröffentlichen:** `npx wrangler deploy`. Die ausgegebene URL ist die des Relays.
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
