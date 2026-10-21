# Handy-Erfassung: Erinnerungen als Push-Benachrichtigung (Cloudflare Worker)

**Status:** freigegeben (Spike zuerst) · **Bezug:** #221 (PWA), #249 (Ende-zu-Ende-Verschlüsselung),
`src/reminders.py`, `src/send_reminder.py` (die Desktop-Erinnerungen), #331

## Ziel

Der Nutzer bekommt seine Erinnerungen **auch auf dem Handy**, als Push-Benachrichtigung
in Chrome und Firefox, und zwar **ohne dass der Desktop läuft**. Das ist der Sinn der
Handy-Erfassung: wer unterwegs ist, hat nur das Handy dabei.

Eingestellt wird es dort, wo der Nutzer seine Erinnerungen ohnehin einstellt: im Tab
„Erinnerungen“ des Desktops (Schalter „Auch aufs Handy senden“) und in der PWA
(Benachrichtigungen erlauben, pro Gerät). Betroffen sind **alle** Arten von
Erinnerung: die Reservierungs-Erinnerung (Toast, „N Minuten vor Ende“ bzw. „verpasst“),
die monatliche Sende-Erinnerung und die tagesbezogene Sende-Erinnerung an einem
markierten Reservierungs-Slot.

## Warum ein Relay

Ein Browser kann sich zu einer Uhrzeit nicht verlässlich selbst wecken. Gemessen an dem,
was es gibt:

| Weg | Chrome | Firefox | Urteil |
|---|---|---|---|
| Web Push (Push API, VAPID) | ja | ja | **einziger tragfähiger Weg** |
| Geplante Benachrichtigung (`showTrigger`) | nur experimentell, „Launch: Not started“ | nein | unbrauchbar |
| Periodic Background Sync | nur installierte PWA, Engagement-Score > 0, ca. ≥ 12 h Abstand | nicht belegt | zu unzuverlässig |

Web Push heißt: **jemand** schickt zur Fälligkeit eine verschlüsselte Nachricht an den
Push-Dienst des Browsers (FCM bei Chrome, Mozilla-Autopush bei Firefox). Der Desktop als
Absender scheidet aus (er müsste laufen), also braucht es einen kleinen Dienst im
Internet. Entschieden: **ein Cloudflare Worker**, vom Projekt betrieben und mitgeliefert.

## Ziele, Nicht-Ziele, Anti-Ziele

**Ziele**
- Erinnerungen kommen pünktlich (Sollgenauigkeit: Minuten) ohne laufenden Desktop.
- Der Relay lernt so wenig wie möglich: **Zeitpunkte, Gerät/Browser-Anbieter, einen
  undurchsichtigen Blob** — keine Namen, Kategorien oder Stunden im Klartext.
- Kein Konto, keine Registrierung: das Handy erzeugt ein Zufallsgeheimnis.
- Chrome und Firefox (Desktop und Android).

**Nicht-Ziele (erste Stufe)**
- Safari/iOS (nur installierte PWA, ab iOS 16.4; eigene Prüfung, der Relay bleibt gleich).
- Push für etwas anderes als Erinnerungen (Sync-Hinweise, Konflikte).
- Delta- oder Echtzeit-Sync über den Relay. **Der Relay transportiert nie Zeiteinträge.**
- Selbst-Hosting als unterstützter Weg (nicht verboten, aber ohne Einrichtungs-Assistent).

**Anti-Ziele (wäre ein Fehlschlag, auch wenn es technisch läuft)**
- Der Relay speichert oder sieht Arbeitszeiten, Kategorien oder Namen im Klartext.
- Eine Erinnerung kommt doppelt (Desktop-Toast **und** Push) ohne dass der Nutzer es so wollte.
- Der Relay ist Voraussetzung: ohne ihn muss alles wie bisher laufen (Desktop-Toasts,
  Handy-Erfassung, Abgleich).

## Architektur

```
Desktop ──(Abgleich, verschlüsselt, LAN)──▶ Handy (PWA) ──(HTTPS)──▶ Relay (Cloudflare Worker)
                                                                           │ Alarm zur Fälligkeit
                                                                           ▼
                                                              Push-Dienst (FCM / Mozilla) ──▶ Service Worker ──▶ Benachrichtigung
```

Das Handy ist die **Quelle des Zeitplans**: es kennt die Reservierungen (es bearbeitet sie
selbst) und bekommt vom Desktop im Abgleich, was nur der Desktop weiß. Nach jedem
Speichern und jedem Abgleich ersetzt es seinen Zeitplan beim Relay (idempotent, „ersetzen
statt ändern“).

### Relay (`relay/`, neu, wie `pwa/` nicht in die App gebündelt)

Ein Worker plus eine **Durable Object-Klasse** (SQLite-gestützt, auf dem Free-Plan
erlaubt). **Ein Objekt je Handy**, benannt nach der Geräte-ID.

**Das Geheimnis ist die Identität:** das Handy erzeugt 256 Bit Zufall, das Objekt ist nach dem
Hash des Geheimnisses benannt. Es gibt keine getrennte Geräte-ID und damit nichts, was ein
Dritter besetzen oder erraten könnte.

Ein Durable Object trägt: Abo (Endpoint, `p256dh`, `auth`) und die Liste `{id, fire_at, blob}`. **Der Alarm steht immer auf dem nächsten `fire_at`.** Bei
Alarm: fällige Einträge senden, entfernen, Alarm auf den nächsten setzen. Das ersetzt Cron
und gibt minutengenaue Zustellung ohne Dauer-Polling.

Routen (alle `POST`/`PUT`/`DELETE` mit JSON, CORS nur für `https://xveyn.github.io`):

| Route | Zweck |
|---|---|
| `PUT /v1/device` | Abo registrieren/erneuern |
| `PUT /v1/schedule` | Zeitplan **ersetzen**: `[{id, fire_at (UTC), blob}]` |
| `DELETE /v1/device` | alles löschen (Abmelden, Widerruf) |

Regeln:
- **Auth:** das Geheimnis als Bearer; es wählt zugleich das Objekt. Ein Aufruf mit unbekanntem
  Geheimnis legt ein Objekt an (Registrierung); gegen Massenanlage helfen Grenzen unten und die
  Selbstreinigung. Ein Rate-Limit im Dashboard ist optional.
- **Grenzen:** höchstens 200 Einträge, `fire_at` höchstens 90 Tage voraus, Blob höchstens 1 KB.
- **Fehler des Push-Dienstes:** `404`/`410` → Abo ist tot, Objekt räumt sich auf.
  `429`/`5xx` → Wiederholung mit Backoff (der Alarm wird neu gesetzt, nicht dem Retry-Limit
  der Plattform überlassen: sie wiederholt nur 6-mal).
- **Überfällige Einträge** (Alarm verspätet): bis 15 min nach `fire_at` noch senden, danach
  verwerfen. Eine Erinnerung von gestern ist keine.
- **Selbstreinigung:** ein Leerlauf-Alarm (90 Tage nach der letzten Aktualisierung) löscht
  das Objekt. Ohne ihn blieben verlassene Geräte für immer.
- **Kein Logging** von Abo, Blob oder Zeitplan.
- VAPID: der private Schlüssel liegt als Worker-Secret, der öffentliche ist in der PWA
  fest eingetragen (wie `PWA_ORIGIN`).

### PWA

- **Service Worker:** `push`- und `notificationclick`-Handler (Klick öffnet die App am
  betroffenen Tag). Chrome verlangt, dass jeder Push eine sichtbare Benachrichtigung
  zeigt (`userVisibleOnly`): wir **unterdrücken also nie** im Handler, sondern halten den
  Zeitplan aktuell (s. u.).
- **Einstellung in der PWA** (pro Gerät, Erlaubnis ist es auch): ein Knopf „Benachrichtigungen
  erlauben“ in „Verbindung“ — die Erlaubnis braucht eine Nutzergeste. Zustände: nicht
  unterstützt, abgelehnt, erteilt, Abo erneuert.
- **Zeitzone:** Reservierungen sind Wanduhrzeiten. Die **Zeitzone des Handys gilt** für den
  Reservierungs-Zeitplan; er wird bei jedem Abgleich und jeder Änderung neu berechnet, ein
  Zonenwechsel wirkt also beim nächsten Öffnen. Die Sende-Zeitpunkte rechnet der Desktop in
  **seiner** Zone und schickt absolute UTC-Zeitpunkte. *Meine Festlegung.*
- **Umfang des Zeitplans:** Reservierungstage von heute bis **heute + 14**, je Slot ein
  Eintrag „upcoming“ und einer „verpasst“, **nur zukünftige** `fire_at` (eine beim ersten
  Abgleich schon verpasste Erinnerung wird nicht nachgeholt). Ist die Kategorie am Tag
  erfasst, entfallen beide. Bei mehr als 200 Einträgen zählen die frühesten.
  *Meine Festlegung.*
- **`reminders-plan.js`** (rein, ohne Browser-API, getestet): baut aus Reservierungen,
  Ist-Zeiten und den Desktop-Angaben den Zeitplan. Die Berechnung entspricht
  `src/reminders.py` („N Minuten vor Ende“ nur mit Kategorie und nur, solange die Kategorie
  am Tag nicht als Ist-Zeit erfasst ist, sonst „verpasst“ zum Slot-Ende). **Gleichlauf über
  Fixtures**, wie bei den übrigen Verträgen (`pwa/CLAUDE.md`).
- **Blob:** der Text der Benachrichtigung, **mit einem eigenen Zufallsschlüssel** der PWA
  verschlüsselt (AES-256-GCM, in IndexedDB, für den Service Worker lesbar). Der Relay reicht
  ihn als Nutzlast durch, der Service Worker entschlüsselt. **Bewusst nicht `k_dev`:** der
  Schlüssel muss nur Handy und Service Worker bekannt sein, der Desktop braucht ihn nie. Das
  erspart eine Abhängigkeit von `crypto.js` und ihren Vektoren. *Meine Festlegung.*
- **Aufräumen:** Widerruf eines Geräts am Desktop und Abmelden der PWA rufen
  `DELETE /v1/device`.
- **Das Relay-Geheimnis gehört der PWA** und wird beim Koppeln neu erzeugt. Es geht verschlüsselt
  im Abgleich an den Desktop, der es beim Gerät speichert (`mobile_devices.json`-Datensatz,
  gehärtet).

### Desktop

- **Widerruf:** der Desktop löscht beim Widerrufen eines Geräts dessen Relay-Objekt
  (`DELETE /v1/device` mit dem gespeicherten Geheimnis), best effort; scheitert es (offline),
  räumt sich das Objekt nach spätestens 90 Tagen selbst auf. *Meine Festlegung.*
- **Einstellung** im Tab „Erinnerungen“: Abschnitt „Handy“ mit Schalter
  `mobile_push_enabled` — **gerätelokal**, nicht in `SYNCED_SETTING_KEYS` (wie
  `auto_update_enabled`), nur sichtbar, wenn die Handy-Erfassung an ist. Für Reservierungs-
  und Sende-Erinnerung je ein Häkchen, was aufs Handy geht.
- **Abgleich-Antwort** trägt additiv (`PROTOCOL` bleibt 2) einen Block `reminders`:
  `{reservation: {enabled, minutes_before}, send: {enabled, at: [<UTC-Zeitpunkte der nächsten
  62 Tage>]}}`. Die Häkchen „Reservierung“ und „Sende-Erinnerung“ sind getrennte `enabled`-Felder.
  Die tagesbezogene Sende-Erinnerung (`send_reminder_minutes` ist gerätelokal und geht nie ans
  Handy) rechnet der Desktop in `at` mit ein. Die
  **Sende-Zeitpunkte rechnet der Desktop** (er kennt Feiertage, Wochenend-Verschiebung und
  den markierten Slot); die PWA kennt `holidays` nicht und soll sie nicht nachbauen.
- **Doppelte Meldung:** der Desktop zeigt seinen Toast weiter. Dazu ein Schalter „Toast am
  Desktop unterdrücken, wenn aufs Handy gesendet wird“ (`mobile_push_suppress_toast`,
  gerätelokal, **Standard aus**) — **vom Nutzer so entschieden**. Ein Anpingen des Handys durch den
  Desktop ist nicht möglich (eine PWA nimmt keine eingehenden Verbindungen an), und Unterdrücken
  nach veralteter Anwesenheit (`last_seen`) wäre die gefährliche Richtung: der Push entfiele nicht,
  aber niemand säße am Desktop. Eine **sichere** Verfeinerung ist die Quittung (Spike 5): der
  Service Worker meldet nach dem Anzeigen dem Desktop im LAN den Empfang, nur dann unterdrückt
  der Desktop seinen Toast; ohne Quittung bleibt er. Schlimmstenfalls zwei Meldungen, nie keine.
- Kompatibilität nach den Regeln aus `pwa/CLAUDE.md`: Fixtures für den Stand vor dem
  Feature, ältere Desktops ohne `reminders`-Block lassen das Handy ohne Zeitplan.

### Bekannte Grenze

Wird eine Ist-Zeit am **Desktop** erfasst und noch nicht abgeglichen, kommt die schon
eingeplante „verpasst“-Erinnerung des Handys trotzdem. Das ist hinnehmbar, die Meldung ist
ein Hinweis; der nächste Abgleich korrigiert den Zeitplan.

## Was der Relay sieht

Endpoint des Push-Dienstes, `p256dh`/`auth`, Geheimnis-Hash, Zeitpunkte, verschlüsselte Blobs.
Das genügt, um zu sehen: *es gibt ein Gerät, das zu diesen Zeiten benachrichtigt wird.*
Nicht: Arbeitszeiten, Kategorien, Namen. Das ist ein neuer Vertrauens-Ort neben GitHub Pages
und gehört in `docs/known-limitations.md` und `pwa/CLAUDE.md` („kein Server“ stimmt dann
nicht mehr). Die Push-Dienste (Google, Mozilla) sehen zusätzlich Metadaten, den Inhalt nicht.

## Spike (zuerst, vor allem anderen)

Lokal mit `wrangler dev`, kein Cloudflare-Konto nötig:
1. Kann der Worker verschlüsselte Pushes an **FCM** und **Mozilla** senden (RFC 8291/8292)?
   Kandidaten: `@block65/webcrypto-web-push`, `@daaku/webpush` oder eigene WebCrypto-Lösung.
   Bekannte Stolperfalle: ein älteres VAPID-Header-Format wird von FCM mit 403 abgelehnt.
2. CPU-Zeit des Sendens (Free-Plan: 10 ms je HTTP-Anfrage; Alarme haben laut Dokumentation
   30 s) — gemessen, nicht angenommen.
3. Funktioniert ein Durable-Object-Alarm im Free-Plan wie beschrieben, auch nach Verspätung?
4. Kann der Service Worker den Blob-Schlüssel aus IndexedDB lesen und entschlüsseln (Chrome und Firefox)?
5. (Optional) Kann ein durch Push gestarteter Service Worker den Desktop im LAN erreichen
   (Mixed Content, Private Network Access) und rechtzeitig quittieren? Nur wenn ja, wird die
   Quittung gebaut.

Fällt **1, 2 oder 3** durch (z. B. CPU über dem Limit, Alarme unzuverlässig), kommt die
Entscheidung zurück zu dir, bevor irgendetwas gebaut wird. Ein Wechsel auf den bezahlten Plan oder auf
Cron ist **deine** Entscheidung, keine des Builders.

## Spike-Ergebnis (2026-10-21, lokal mit `wrangler dev`, Chrome und Firefox)

- **Bestanden:** Ein Worker sendet verschlüsselte Pushes an **FCM** und **Mozilla** (beide HTTP 201),
  sofort und per Durable-Object-Alarm (3 ms Verspätung lokal). `@block65/webcrypto-web-push`
  2.0.0 genügt (aes128gcm, VAPID `vapid t=…, k=…`), keine eigene Kryptographie nötig.
- **Bestanden:** Der Service Worker liest den Blob-Schlüssel aus IndexedDB (nicht extrahierbarer
  `CryptoKey`) und entschlüsselt ein vom Relay durchgereichtes Blob — in Chrome und Firefox.
- **Offen bis zum ersten Deploy:** CPU-Zeit gegen das 10-ms-Limit des Free-Plans (lokal nicht
  messbar: `Date.now()` rückt in Workers nur bei I/O vor) und das Alarmverhalten auf dem
  Free-Plan. Beides wird im Relay-PR gemessen; fällt es durch, entscheidet der Nutzer.
- **Gestrichen: die Quittung im LAN** (ehem. Spike 5). Ein durch Push gestarteter Service Worker
  kann die Berechtigung für Zugriffe im lokalen Netz nicht abfragen; es bleibt bei dem einfachen
  Schalter. (Der Absatz „Doppelte Meldung“ oben nennt sie nur noch als Möglichkeit.)
- **Werkzeug:** `wrangler` verlangt Node ≥ 22 (lokal Node 20 → Node 22 per npm-Paket `node@22`).

## Abhängigkeit: Firefox

Der Relay stellt in Firefox zu, aber die PWA kann sich dort heute **nicht mit dem Desktop koppeln
oder abgleichen** (Mixed Content, `docs/known-limitations.md`, #249). Ohne Abgleich gibt es keine
Reservierungen und keine Sende-Zeitpunkte vom Desktop. Push in Firefox ist damit erst dann
nützlich, wenn der Desktop per HTTPS erreichbar ist (#249). Chrome auf Android ist der Weg der
ersten Stufe.

## Plattform-Grenzen (Stand der Recherche, nicht alles aus Primärquellen)

- **Free-Plan (offiziell):** 100.000 Anfragen/Tag, 10 ms CPU je Anfrage, 50 Unteranfragen je
  Aufruf, 5 Cron-Trigger je Konto (hier ungenutzt), Durable Objects nur SQLite-gestützt,
  100.000 geschriebene Zeilen/Tag, 100 Klassen. Jedes `setAlarm()` zählt als geschriebene
  Zeile und jeder Alarm als Anfrage.
- **KV ist ungeeignet:** laut Sekundärquellen nur 1.000 Schreibvorgänge/Tag auf dem Free-Plan.
- **Zustellung:** Energiesparmodi können Push verzögern; Firefox Desktop braucht einen
  laufenden Browser (Erfahrungswerte, nicht belegt).

## Was du einrichten musst

Das kann ich nicht für dich tun (Konto, Geheimnisse). **Für den Spike brauchst du nichts davon**,
erst ab dem Veröffentlichen:

1. **Cloudflare-Konto** (kostenlos) auf dash.cloudflare.com anlegen. Für Workers Free sollte
   keine Zahlungskarte nötig sein *(nicht geprüft)*.
2. **workers.dev-Subdomain wählen** (Dashboard → Workers & Pages → Subdomain, einmalig).
   Daraus entsteht `https://zeiterfassung-push.<deine-subdomain>.workers.dev`. Alternativ eigene
   Domain, nicht nötig.
3. **Node 22 und `wrangler`** lokal (Node hast du für `pwa/` ohnehin); `npx wrangler login`
   öffnet den Browser zur Anmeldung.
4. **VAPID-Schlüssel erzeugen:** `node relay/scripts/gen-vapid.mjs` (wird gebaut) druckt ein
   Paar. Der **öffentliche** Schlüssel kommt in die PWA (Commit), der **private** nur als
   Secret: `npx wrangler secret put VAPID_PRIVATE_KEY`. **Den privaten Schlüssel nirgends
   einchecken**, und nach dem Veröffentlichen nie wechseln: alle Abos hängen am öffentlichen.
5. **Kontakt für VAPID** (`VAPID_SUBJECT`, `mailto:…`): Push-Dienste dürfen darüber den
   Betreiber erreichen. Es sollte eine Adresse sein, die öffentlich sein darf. *Welche, entscheidest du.*
6. **`npx wrangler deploy`** (einmal von Hand). Danach die Worker-URL in `src/mobile_routes.py`/
   `pwa/` als Konstante eintragen (macht der PR) und in der CSP der PWA freigeben.
7. **Optional, später:** Deploy aus GitHub Actions (`relay.yml`): API-Token mit der Vorlage
   „Edit Cloudflare Workers“ und die Konto-ID als Repo-Secrets `CLOUDFLARE_API_TOKEN` und
   `CLOUDFLARE_ACCOUNT_ID`. Und ggf. eine **Rate-Limit-Regel** im Dashboard gegen
   Registrierungs-Missbrauch (ob das auf dem Free-Plan geht, ist ungeprüft).

## CI und Veröffentlichung

`relay/**` zählt als Code (nicht als Doku) und löst die ganze Matrix aus. Der Relay bekommt
einen eigenen Job `relay` in `test.yml` (Node 22, hinter `changes`, wie `pwa`), **nicht**
in den Required Checks (die Entscheidung liegt beim Maintainer, wie bei `pwa`). `wrangler` ist
Deploy-Werkzeug, die Tests laufen ohne ihn. Die Versionsregeln für die PWA
(`pwa-version.yml`) gelten, sobald `pwa/` sich ändert. *Meine Festlegung.*

## Umsetzungsreihenfolge (je ein PR)

1. Spike (verworfen oder behalten, nur Ergebnis im Issue).
2. Relay (`relay/`, Tests, Doku) — noch ohne Verbraucher.
3. PWA: Service Worker, Abo, Zeitplan (`reminders-plan.js`), Kompatibilität.
4. Desktop: Einstellung, `reminders`-Block im Abgleich, Sende-Zeitpunkte.
5. Doku (`known-limitations.md`, README, `src/CLAUDE.md`, `pwa/CLAUDE.md`).

## Offen für den Builder

- Genaue Texte der Benachrichtigungen und das Klick-Ziel je Art.
- Backoff-Werte bei `429`/`5xx`.
- Form der Fixtures für den Gleichlauf `reminders.py` ↔ `reminders-plan.js`.
