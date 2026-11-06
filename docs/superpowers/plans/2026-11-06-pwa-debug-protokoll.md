# PWA Debug-Protokoll Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Vierter Einstellungs-Reiter „Debug“ der Handy-Web-App mit technischem Zustand und einem lokalen, bereinigten Protokoll aus Fehlern und Abgleich-Zusammenfassungen (Closes #477).

**Architecture:** `diagnose.logFailure` bekommt eine austauschbare Senke; Seite und Service Worker setzen sie auf ein DOM-freies Modul `debug-log.js`, das Ereignisse nach einer Positivliste baut, freien Text durch `log-scrub.js` schickt und in einer eigenen IndexedDB (`zeiterfassung-log`) ablegt. Der Reiter zeigt Zustand und Einträge, kopiert, teilt, löscht und stellt die Haltezeit ein.

**Tech Stack:** Reines JavaScript ohne Build (ES-Module), `node --test`, IndexedDB, Service Worker.

**Spec:** `docs/superpowers/specs/2026-11-06-pwa-debug-protokoll-design.md`

## Global Constraints

- Arbeitsverzeichnis `pwa/`, Tests laufen mit `cd pwa && node --test` (Node 22; unter Linux ggf. `. ~/.nvm/nvm.sh && nvm use 22`). Keine Abhängigkeiten, kein Build.
- Neue Module sind DOM-frei, Umgebung kommt als Parameter herein (Muster `diagnose.js`, `browser-policy.js`); jedes neue Laufzeitmodul gehört in `PRECACHE` (`sw-core.js`) und in die Modulliste von `pwa/CLAUDE.md`.
- Datenbank `zeiterfassung-log` (Version 1), Stores `entries` und `config`; die Datenbank `zeiterfassung` (Version 2) bleibt unverändert.
- Haltezeit `log_retention_days`: Auswahl **1 / 7 / 30** Tage, Standard **7**; harte Obergrenze **500** Einträge; `detail` höchstens **240** Zeichen.
- Platzhalter genau: `<url>`, `<ip>`, `<mail>`, `<schlüssel>`, `<datum>`, `<zeit>`, `<pfad>`, `<host>`, `<text>`.
- Ereignisse: `error` (`context`, `name`, `detail`) und `sync` (`result`, `ms`, `sent`, `received`, `conflicts`, `window`); Stufen im Export `WARN` für Fehler, `INFO` für Abgleiche.
- Exportdatei heißt fest `zeiterfassung-debug.txt`. Nichts wird gesendet, nur Kopieren/Teilen auf Knopfdruck. Kein Gerätemodell, kein Gerätename, keine Adresse, keine Geräte-ID im Protokoll oder Zustand.
- Commits deutsch nach Repo-Stil (`feat(pwa): …`), mit der Attributionszeile der Sitzung; Branch `feat/pwa-debug-protokoll`, PR mit `Closes #477`.

## Review Focus

- **URL mit Token in der Fehlermeldung** (`…/push?token=abc#frag`): die ganze Adresse wird `<url>`, kein Rest bleibt. → Task 1.
- **IPv6 und `host:port`** (`[fe80::1]:8080`, `192.168.1.5:17654`, `localhost:8099`): alles `<ip>`/`<host>`, Statuscodes, Versionen und Dateinamen (`sw.js`) bleiben. → Task 1.
- **Echtes Datum und Uhrzeit eines Eintrags im Text** (`Tag 2026-11-04 08:00–16:30`): `<datum>`/`<zeit>`. → Task 1.
- **IndexedDB nicht verfügbar** (privates Fenster, Speicher voll): Protokollieren wirft nie, das Protokoll bleibt im Speicher, der Reiter sagt es. → Task 2, 7.
- **Browser-Fehler, die Eingabetext zitieren** (`Unexpected token 'S', "Sende Max" is not valid JSON`): Text in Anführungszeichen wird `<text>`, sonst stünde Nutzerinhalt im Protokoll. → Task 1.

---

### Task 1: Bereinigung `log-scrub.js`

**Files:**
- Create: `pwa/log-scrub.js`
- Test: `pwa/test/log-scrub.test.js`

**Interfaces:**
- Produces: `scrubText(value: unknown, maxLength?: number): string` (Standard 240; Nicht-Text → `''`; Whitespace zu einem Leerzeichen, gekürzt mit `…`).

- [ ] **Step 1: Failing tests** in `log-scrub.test.js`, je eine Eingabe → exakte Ausgabe:
  - `'Failed to fetch https://updates.push.services.mozilla.com/wpush/v2/abc?x=1#f'` → `'Failed to fetch <url>'`; `'ws://localhost:8099/x'` → `'<url>'`.
  - `'connect 192.168.1.20:17654 refused'` → `'connect <ip> refused'`; `'[fe80::1]:8080'` und `'fe80::1ff:fe23:4567:890a'` → `'<ip>'`.
  - `'an max@example.com'` → `'an <mail>'`; `'xveyn.github.io'` → `'<host>'`; `'localhost:8099'` → `'<host>'`.
  - Schlüssel: ein 43-stelliger Base64url-Text und ein 32-stelliger Hex-Text → `'<schlüssel>'`.
  - `'Tag 2026-11-04 08:00–16:30, 04.11.2026'` → `'Tag <datum> <zeit>–<zeit>, <datum>'`.
  - Bleibt unverändert: `'status 413 version 131.0.6778 port 8080 errno 109 in sw.js line 12'`.
  - Anführungszeichen: `'Unexpected token \'S\', "Sende Max" is not valid JSON'` → `'Unexpected token \'S\', <text> is not valid JSON'` (jeder Text in doppelten Anführungszeichen wird `<text>`).
  - Typische Browsermeldungen bleiben unverändert: `'ServiceWorker cannot be started'`, `'Failed to update a ServiceWorker: An unknown error occurred when fetching the script.'`, `'Registration failed - push service error'`, `'The operation is insecure.'`, `'TypeError: Failed to fetch'`.
  - `scrubText(undefined)` und `scrubText({})` → `''`; 1000 × `x` → 240 Zeichen, endet auf `…`.
  - Idempotenz: `scrubText(scrubText(s)) === scrubText(s)` für alle Beispiele.
- [ ] **Step 2: Run** `cd pwa && node --test test/log-scrub.test.js` → FAIL (Modul fehlt).
- [ ] **Step 3: Implement** `scrubText` in `pwa/log-scrub.js`: Reihenfolge URLs → E-Mail → IP (v4 mit optionalem Port, v6, in Klammern) → Hostnamen (Label mit Buchstaben-TLD; Dateinamen mit `js|mjs|json|css|html|txt` bleiben) → Schlüssel (≥ 20 Zeichen Base64url/Hex) → Datum (`JJJJ-MM-TT`, `TT.MM.JJJJ`) → Uhrzeit (`H:MM`/`HH:MM`); dann Whitespace normalisieren, kürzen.
- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `feat(pwa): Bereinigung für das Debug-Protokoll`.

### Task 2: Kern `debug-log.js` (Ereignisse, Aufräumen, Export)

**Files:**
- Create: `pwa/debug-log.js`
- Test: `pwa/test/debug-log.test.js`

**Interfaces:**
- Consumes: `scrubText` (Task 1); Speicher-Schnittstelle (Task 3): `add(entry): Promise<void>`, `all(): Promise<Array<{id:number, at:string, kind:string, fields:object}>>` (aufsteigend), `remove(ids:number[]): Promise<void>`, `clear(): Promise<void>`, `getConfig(key): Promise<unknown>`, `setConfig(key, value): Promise<void>`.
- Produces:
  - `RETENTION_CHOICES = [1, 7, 30]`, `DEFAULT_RETENTION_DAYS = 7`, `MAX_ENTRIES = 500`.
  - `errorEvent(context: unknown, error: unknown): {kind:'error', fields:{context:string, name:string, detail:string}}` — `context` und `detail` durch `scrubText`; `name` nur `^[A-Za-z][A-Za-z0-9_.]{0,59}$`, sonst `''`; `detail` ist die Meldung (Text oder `error.message`).
  - `syncEvent(summary: object): {kind:'sync', fields:{result:string, ms:number, sent:number, received:number, conflicts:number, window:number}}` — Positivliste, unbekannte Felder entfallen, Zahlen ganzzahlig ≥ 0 (sonst 0), `result` nur `^[a-z_]{1,40}$` (sonst `'error'`).
  - `createDebugLog({store, now = () => new Date()})` → `{ recordError(context, error): Promise<void>, recordSync(summary): Promise<void>, entries(): Promise<Entry[]> (neueste zuerst), clear(): Promise<void>, retentionDays(): Promise<number>, setRetentionDays(days): Promise<void>, prune(): Promise<void>, isPersistent(): boolean }`. `recordError`/`recordSync`/`prune` werfen nie; `setRetentionDays` lehnt Werte außerhalb `RETENTION_CHOICES` ab (`RangeError`), speichert sonst und räumt sofort auf.
  - `formatEntry(entry): string`, `formatExport({info: Array<{label,value}>, entries}): string`, `deliverExport(text, {canShare, share, download}): Promise<'shared'|'downloaded'|'cancelled'>`.

- `at` ist UTC-ISO **ohne Millisekunden** (`2026-11-06T14:02:11Z`) aus `now()`. `formatExport` bereinigt nur die Einträge; die Zeilen von `info` kommen aus festen, geprüften Werten und laufen unverändert durch.

- [ ] **Step 1: Failing tests** in `debug-log.test.js` (Speicher: kleine Attrappe im Test, `at` aus `now`):
  - `errorEvent('Update-Suche', new TypeError('Failed https://x.example/a'))` → `{kind:'error', fields:{context:'Update-Suche', name:'TypeError', detail:'Failed <url>'}}`; `errorEvent('Kontext 10.0.0.1', 'kaputt')` scrubbt den Kontext und hat `name:''`, `detail:'kaputt'`.
  - `syncEvent({result:'ok', ms:412, sent:3, received:5, conflicts:0, window:14, device:'Max'})` → genau die sechs Felder; `{result:'Bad Value!', ms:-1, sent:NaN}` → `result:'error'`, Zahlen `0`.
  - Haltezeit: Standard `7`; `setRetentionDays(3)` rejected mit `RangeError`; Einträge von vor 8 Tagen fallen bei `prune()` weg, von vor 6 Tagen bleiben; `setRetentionDays(1)` räumt Einträge von vor 2 Tagen sofort weg.
  - Obergrenze: 501 × `recordError` → `entries()` hat 500, der älteste fehlt.
  - Ausfall: Speicher, dessen `add` ablehnt → `recordError` löst auf, `isPersistent()` ist `false`, `entries()` liefert den Eintrag trotzdem (aus dem Speicher der Seite); ein Fehlerobjekt mit Zirkelbezug oder einem `message`-Getter, der wirft, wirft nicht; `at` hat keine Millisekunden.
  - `formatEntry`: `{at:'2026-11-06T14:02:11Z', kind:'error', fields:{context:'Update-Suche', name:'TypeError', detail:'x'}}` → `'2026-11-06T14:02:11Z WARN Update-Suche: TypeError: x'`; ohne `name` → `'… WARN Update-Suche: x'`; Abgleich → `'2026-11-06T14:02:11Z INFO Abgleich ok, 412 ms, gesendet 3, empfangen 5, Konflikte 0, Fenster 14'`.
  - `formatExport`: `info`-Zeilen wie `{label:'Build', value:'12/1.27.0 (a1b2c3d)'}` erscheinen unverändert; zuerst je Zeile `Label: Wert`, Leerzeile, dann Einträge neueste zuerst; ein **bereits gespeicherter** Eintrag mit `detail:'bei 192.168.1.5'` erscheint als `bei <ip>` (Export bereinigt erneut).
  - `deliverExport`: `canShare()` false → `download` wird gerufen, Ergebnis `'downloaded'`; `share` wirft `DOMException('x','AbortError')` → `'cancelled'`, kein Download; `share` wirft anderen Fehler → Download, `'downloaded'`; sonst `'shared'`.
- [ ] **Step 2: Run** `node --test test/debug-log.test.js` → FAIL.
- [ ] **Step 3: Implement** in `pwa/debug-log.js`. Bei Speicherfehler schaltet der Kern auf ein Array im Speicher um (`isPersistent()` false). `prune`: nach Alter (`now - at > Haltezeit`) und Obergrenze, in einem `remove`.
- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `feat(pwa): Kern des Debug-Protokolls (Ereignisse, Aufräumen, Export)`.

### Task 3: Speicher `log-store.js`

**Files:**
- Create: `pwa/log-store.js`
- Test: `pwa/test/log-store.test.js`

**Interfaces:**
- Produces: `memoryLogStore()` und `idbLogStore(indexedDB = globalThis.indexedDB)`, beide mit der Speicher-Schnittstelle aus Task 2. IndexedDB: Datenbank `zeiterfassung-log` Version 1, Store `entries` (`keyPath: 'id'`, `autoIncrement`), Store `config`. Geöffnet wird **erst beim ersten Aufruf** und die Verbindung gemerkt; scheitert das Öffnen, lehnen die Aufrufe ab (der Kern fängt es).

- [ ] **Step 1: Failing tests:** ein gemeinsamer Vertragstest, der gegen `memoryLogStore()` **und** gegen `idbLogStore(fakeFactory())` läuft (Attrappe im Stil von `test/db.test.js`): `add` dreimal, `all()` aufsteigend nach `id` mit den gespeicherten Feldern; `remove([id1])` entfernt genau diesen; `clear()` leert; `setConfig('log_retention_days', 30)`/`getConfig` Rundreise, fehlender Schlüssel → `undefined`. Dazu nur für IndexedDB: Fabrik wird vor dem ersten Aufruf nicht angerufen, öffnet `'zeiterfassung-log'` mit Version `1`; `failOpen` → `add` lehnt ab.
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement** beide Speicher (Muster `push-blob.idbKeyStore`, eigene Datenbank, `onversionchange` schließt).
- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `feat(pwa): Speicher für das Debug-Protokoll (IndexedDB zeiterfassung-log)`.

### Task 4: Senke und Verdrahtung in der Seite

**Files:**
- Modify: `pwa/diagnose.js` (`setLogSink`), `pwa/app.js` (Anlegen, Senke, `runSync`), `pwa/sync.js` (Rückgabe), `pwa/sw-core.js` (`PRECACHE`)
- Test: `pwa/test/diagnose.test.js`, `pwa/test/sync.test.js`, `pwa/test/log-contexts.test.js` (neu), `pwa/test/shell.test.js` (läuft mit)

**Interfaces:**
- Consumes: `createDebugLog`, `idbLogStore`.
- Produces: `setLogSink(sink: ((context: string, error: unknown) => void) | null): void` in `diagnose.js`; `Client.sync()` liefert zusätzlich `received: number` (Zahl der Tage in `parsed.entries`) und `window: number` (`parsed.window_days`).

- [ ] **Step 1: Failing tests:**
  - `diagnose.test.js`: `setLogSink(fn)`; `logFailure('K', err, silentLog)` ruft `fn('K', err)` genau einmal; wirft die Senke, wirft `logFailure` nicht; nach `setLogSink(null)` wird sie nicht mehr gerufen.
  - `sync.test.js`: ein erfolgreicher Abgleich liefert `{sent, conflicts, excluded, received, window}`, `received` = Zahl der Tage der Antwort, `window` = `window_days` der Antwort; bestehende Erwartungen auf das Ergebnis werden angepasst.
  - `log-contexts.test.js`: liest den Quelltext von `app.js`, `sw.js`, `sync.js`, `relay-transport.js` und verlangt, dass jeder Aufruf von `logFailure(` (bzw. `log(` in `relay-transport.js`) als **erstes Argument ein Textliteral** hat.
- [ ] **Step 2: Run** `node --test` → die neuen Tests FAIL.
- [ ] **Step 3: Implement:** `setLogSink` in `diagnose.js` (Senke in `try/catch` nach dem `console.warn`); `sync.js` ergänzt `received`/`window`; `app.js` legt `createDebugLog({store: idbLogStore()})` an, setzt `setLogSink((c, e) => debugLog.recordError(c, e))`, ruft `prune()` beim Start und in `runSync` nach dem Abgleich `recordSync({result: 'ok', ms, ...result})` bzw. im Fehlerfall `recordSync({result: error.kind ?? error.name, ms})` (Dauer mit `Date.now()` um `client.sync()`); `debug-log.js`, `log-store.js`, `log-scrub.js` in `PRECACHE`.
- [ ] **Step 4: Run** `node --test` → alles grün, auch `shell.test.js` (Liste = Dateisystem).
- [ ] **Step 5: Commit** `feat(pwa): logFailure schreibt ins Debug-Protokoll, Abgleich-Zusammenfassung`.

### Task 5: Service Worker schreibt Fehler ins Protokoll (eigene Aufgabe, einzeln rückbaubar)

**Warum eigene Aufgabe:** Der Service Worker ist ein Modul-Worker mit statischen Imports (`import()` ist dort verboten). Chrome holt beim Update-Check Skript **und** alle Imports; drei weitere Module vergrößern den Import-Baum von `sw.js` (heute vier) und könnten genau das Chrome-Problem verschärfen, das dieses Protokoll aufklären soll (Update-Suche, #390). Der Fehler der Update-Suche wird in der **Seite** protokolliert (`app.js`, `checkForUpdate`), nicht im Worker; im Worker gibt es heute nur `logFailure('Push entschlüsseln', …)`. Diese Aufgabe darf deshalb einzeln zurückgenommen werden, ohne den Rest zu berühren.

**Files:**
- Modify: `pwa/sw.js`
- Test: `pwa/test/log-contexts.test.js` (erweitert)

**Interfaces:**
- Consumes: `setLogSink`, `createDebugLog`, `idbLogStore`.

- [ ] **Step 1: Failing test:** in `log-contexts.test.js`: `sw.js` importiert höchstens `./sw-core.js`, `./push-blob.js`, `./diagnose.js`, `./push-message.js` und `./debug-log.js` (keine weiteren Module); `sw.js` ruft `setLogSink` mit einer Senke, die ein `createDebugLog({store: idbLogStore()})` füttert.
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement** in `sw.js`: eigene `createDebugLog`-Instanz über `idbLogStore()` (öffnet erst beim ersten Schreiben) und `setLogSink`. `debug-log.js` zieht `log-scrub.js` und `log-store.js` selbst herein.
- [ ] **Step 4: Run** `node --test` → grün. Im Browser: Push mit beschädigtem Blob auslösen, der Fehler `Push entschlüsseln` erscheint (bereinigt) im Reiter, sobald Task 7 steht.
- [ ] **Step 5: Commit** `feat(pwa): Service Worker schreibt Fehler ins Debug-Protokoll`.

### Task 6: Technischer Zustand `debug-info.js`

**Files:**
- Create: `pwa/debug-info.js`
- Modify: `pwa/app.js` (Parameter sammeln), `pwa/sw-core.js` (`PRECACHE`)
- Test: `pwa/test/debug-info.test.js`

**Interfaces:**
- Produces: `describeEnvironment(env): Array<{label: string, value: string}>` mit `env = {userAgent, userAgentData?, platformVersion?, standalone, online, language, screen:{width,height}, build, worker: {active, waiting}|null, notification: 'granted'|'denied'|'default'|null, subscribed: boolean|null, storage: {persisted: boolean|null, usage: number|null}|null, pairing: 'lan'|'relay'|null, protocol: number|null}`. Alles Fehlende zeigt `'unbekannt'`. Zeilen (Labels fest): Browser, Betriebssystem, Als App installiert, Online, Sprache, Bildschirm, Build, Service Worker, Benachrichtigungen, Speicher, Kopplungsweg, Protokoll.

- [ ] **Step 1: Failing tests:** Chrome-Android-UA mit `platformVersion:'14.0.0'` → Browser `Chrome 131`, Betriebssystem `Android 14`; Firefox-Android-UA → `Firefox <Hauptversion>`; weder `Pixel`/`SM-` noch Gerätemodell in irgendeinem Wert; alles `null` → jede Zeile `unbekannt`; Speicher `{persisted:true, usage:8388608}` → `dauerhaft ja, 8 MB`; kein Wert enthält einen Doppelpunkt-Port oder `http`.
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement** `describeEnvironment`; `app.js` sammelt die Parameter (`navigator.serviceWorker.getRegistration()`, `Notification.permission`, `pushManager.getSubscription()`, `navigator.storage.estimate()`/`persisted()`, `matchMedia('(display-mode: standalone)')`; von `userAgentData.getHighEntropyValues` **nur** `platformVersion`, nie `model`); jeder Fehler beim Sammeln ergibt `null`.
- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `feat(pwa): technischer Zustand für den Debug-Reiter`.

### Task 7: Reiter „Debug“

**Files:**
- Modify: `pwa/view-model.js` (`SETTINGS_TABS`, `TAB_LABELS`), `pwa/views.js` (`debugPanel`, `settingsDialog`), `pwa/app.js` (Modell, Handler), `pwa/app.css` (nur falls nötig)
- Test: `pwa/test/view-model.test.js`

**Interfaces:**
- Consumes: `describeEnvironment` (Task 6), `createDebugLog`/`formatExport`/`deliverExport`/`RETENTION_CHOICES` (Task 2).
- Produces: `SETTINGS_TABS = ['connection','categories','updates','debug']`, `settingsTabLabel('debug') === 'Debug'`; `settingsDialog({tab, connection, updates, categories, debug}, handlers)` mit `debug = {info, entries, retention, persistent}` und Handlern `copyDebug(): Promise<'copied'|'failed'>`, `shareDebug(): Promise<'shared'|'downloaded'|'cancelled'>`, `clearDebug(): Promise<void>`, `setRetention(days: number): Promise<void>`.

- [ ] **Step 1: Failing tests** in `view-model.test.js`: die Reihenfolge von `SETTINGS_TABS` und das Label `Debug`.
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement:** `debugPanel` in `views.js` (Zustand als Liste, Einträge neueste zuerst mit `formatEntry`, bei `persistent === false` ein Hinweis „Das Protokoll liegt nur im Speicher dieser Seite“, Auswahl der Haltezeit aus `RETENTION_CHOICES`, Knöpfe Kopieren/Als Datei teilen/Löschen; Löschen über `confirmDialog`); `app.js` baut das Modell (`entries()`, `retentionDays()`, `isPersistent()`) und die Handler (Kopieren über `navigator.clipboard.writeText` mit Fallback; Teilen über `deliverExport` mit `navigator.canShare({files})`/`share` und Download-Fallback, Datei `zeiterfassung-debug.txt`).
- [ ] **Step 4: Run** `node --test` → grün; im Browser prüfen (`python scripts/pwa_devserver.py`): vierter Reiter erscheint, Kopieren/Teilen/Löschen/Haltezeit gehen, Fehler `Update-Suche` erscheint bereinigt.
- [ ] **Step 5: Commit** `feat(pwa): Reiter „Debug“ mit Zustand und Protokoll`.

### Task 8: Doku und Datenschutz

**Files:**
- Modify: `pwa/CLAUDE.md` (Modulliste, Abschnitt „Debug-Protokoll“), `docs/datenschutz.md` (neuer Abschnitt zum lokalen Protokoll der Web-App), `pwa/test/fixtures/privacy-blocks.json` (nur falls der Vertragstest es verlangt)
- Test: `tests/test_privacy_doc.py`, `pwa/test/privacy-doc.test.js`

- [ ] **Step 1:** Abschnitt in `docs/datenschutz.md` (nach „8. Datensparsamkeit“ oder als neuer Abschnitt, Nummerierung fortführen): das Protokoll liegt nur auf dem Gerät, enthält nur Fehler und Abgleich-Zusammenfassungen ohne Adressen, Namen, Einträge, Haltezeit 1/7/30 Tage (Standard 7), Löschen im Reiter, Weitergabe nur auf Knopfdruck. Die Zusage zu den Geheimnissen („in kein Log und keinen Fehlertext“) bleibt unverändert.
- [ ] **Step 2: Run** `pytest tests/test_privacy_doc.py -q` und `cd pwa && node --test` → grün (Fixture nachziehen, falls rot, dann erneut).
- [ ] **Step 3:** `pwa/CLAUDE.md`: Modulliste (`log-scrub.js`, `debug-log.js`, `log-store.js`, `debug-info.js`), Abschnitt „Debug-Protokoll“ mit den Regeln (feste Kontexte, Positivliste, Haltezeit in der Log-Datenbank, Service Worker schreibt nur Fehler).
- [ ] **Step 4: Gesamtlauf** `cd pwa && node --test` und `pytest -q` und `ruff check .` → grün.
- [ ] **Step 5: Commit** `docs(pwa): Debug-Protokoll in Datenschutzhinweisen und Entwickler-Doku`; danach PR mit `Closes #477`.
