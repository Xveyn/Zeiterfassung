# Mobile Erfassung, PR 7 von 9: PWA-Oberfläche, Service Worker, Pages — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Die Handy-PWA (#221) wird benutzbar und auslieferbar: `index.html`, Oberfläche (Koppeln, Woche, Tag bearbeiten, Konflikte, Verbindung), Service Worker für den Offline-Start, Manifest und Icons, und ein Workflow, der `pwa/` nach GitHub Pages veröffentlicht. Dazu ein Dev-Server, mit dem sich die PWA gegen die **echte** Desktop-Logik im Browser prüfen lässt.

**Architecture:** Alles Entscheidbare bleibt DOM-frei und in Node getestet: `view-model.js` (Wochenmodell, Statuszeile, Hinweise, Konfliktliste, Editor-Zeilen), `messages.js` (jede Fehlerart → Text und Ausweg), `sync-policy.js` (wann ein Abgleich laufen darf), `sw-core.js` (Cache-Name, Vorab-Cache-Liste, welche Anfragen der Service Worker anfasst). Die DOM-Schicht (`dom.js`, `views.js`, `app.js`, `scanner.js`) ist dünn, baut **nur** über `createElement`/Textknoten (kein `innerHTML`) und wird im echten Chromium gegen den Dev-Server geprüft. Der Service Worker ist ein ES-Modul (`type: "module"`) und importiert `sw-core.js`; der Pages-Workflow setzt beim Veröffentlichen die Build-Kennung in `sw-core.js` ein, damit jeder Deploy einen neuen Cache und ein Update auslöst.

**Tech Stack:** JavaScript (ES-Module, kein Build, keine Abhängigkeiten), HTML, CSS, Service Worker, Web App Manifest, GitHub Actions (`upload-pages-artifact`, `deploy-pages`), Pillow (einmalig für die Icons).

**Spec:** `docs/superpowers/specs/2026-10-08-mobile-pwa-design.md` (Abschnitte „PWA", „Auslieferung und Zuschnitt", „Sicherheit und Grenzen"). PR 7 des PR-Zuschnitts dort (hier „7 von 9").

**Voraussetzung:** PR 2 bis 6 (#252, #255, #257, #259, #261, #263) sind gemergt. **Pages ist noch nicht aktiviert** (#266, Settings → Pages → Source „GitHub Actions"): der Workflow ist erst nach dem Merge **und** dieser Einstellung lauffähig. Zum Entwickeln und Testen braucht es Pages nicht (Dev-Server in Task 5).

**Branching:** `feat/pwa-oberflaeche` vom aktuellen `master`; der PR zielt auf `master`, trägt `Refs #221`, kein `Closes`. Kein Versionsbump. Die Desktop-App ändert sich nicht.

## Rulings aus der Planung

- **Kein `innerHTML` und keine verwandten APIs, nirgends.** Kategorienamen, Gerätenamen und Fehlertexte kommen vom Desktop beziehungsweise aus einem QR-Code (Fremddaten). Alles läuft über `createElement` und Textknoten; ein Node-Test scannt die Laufzeitdateien nach `innerHTML`, `outerHTML`, `insertAdjacentHTML`, `document.write`, `eval` und `new Function`.
- **Weitere Module flach in `pwa/`**, wie in PR 6: `view-model.js`, `messages.js`, `sync-policy.js`, `scanner.js`, `dom.js`, `views.js`, `app.js`, `sw.js`, `sw-core.js`. Die Spec nennt `app.js` und „Oberfläche"; die Aufteilung in testbare Modelle und dünne DOM-Schicht ist die Umsetzung des Grundsatzes „Getestet wird Logik, nicht UI" für JavaScript.
- **Vorab-Cache-Liste und Dateien dürfen nicht auseinanderlaufen:** ein Test verlangt, dass jede Datei unter `pwa/` (außer `test/`, `package.json`, `sw.js`, `memory-adapter.js`) in `PRECACHE` steht und jeder Eintrag existiert. Der Workflow kopiert denselben Dateisatz.
- **Build-Kennung per Platzhalter:** `sw-core.js` trägt `export const BUILD = '__BUILD__'`; der Workflow ersetzt ihn durch die ersten 12 Zeichen des Commits. Ein Test verlangt den Platzhalter genau einmal und den `sed`-Aufruf im Workflow (sonst läge dauerhaft derselbe Cache, und neue Versionen kämen nie an). Im Dev bleibt der Platzhalter stehen.
- **Update ohne Überraschung:** ein neuer Service Worker wartet (`skipWaiting` nur auf Nachricht). Die App zeigt „Neue Version verfügbar" mit „Neu laden"; erst der Klick schickt `SKIP_WAITING` und lädt nach `controllerchange` neu. Nie mitten in einer Eingabe.
- **Der Service Worker fasst nur eigene Anfragen an** (`GET`, gleiche Origin, Pfad in der Vorab-Cache-Liste). Alles andere, vor allem die Anfragen an den Desktop (`http://<LAN-IP>`), läuft am Service Worker vorbei: **API-Antworten werden nie gecacht** (Spec).
- **Der Editor ist ein `<dialog>`** und wird nur beim Öffnen gebaut; die Statuszeile und die Wochenliste rendern im Hintergrund neu, ohne Eingaben zu stören.
- **Zukunftstage (#265) bleiben vorerst wie in der Spec:** Tage nach `heute + 1` verschwinden nach dem Abgleich am Handy (der Desktop hat sie). Der Editor warnt ausdrücklich, wenn man einen solchen Tag bearbeitet; die Entscheidung über das Fenster nach vorn bleibt in #265. Wird dort anders entschieden, ändert das `store.js` und die Warnung, nicht die Oberfläche.
- **Automatischer Abgleich nur wie in der Spec:** beim Start, beim Sichtbarwerden, beim `online`-Ereignis, 2 Sekunden nach dem Speichern, auf Knopfdruck; kein Hintergrund-Sync. `sync-policy.js` begrenzt die automatischen Auslöser (Wartezeit 5 s, nach Netzfehlern 30 s, nie mit totem Token) und lässt „Speichern" und „Knopfdruck" immer durch.
- **Koppeln aus dem Link:** ein Fragment `#pair=…` füllt das Formular nur **vor** (keine automatische Anfrage), danach entfernt `history.replaceState` das Fragment aus der Adresszeile. Zusätzlich liest ein QR-Scan (`BarcodeDetector`, nur wo vorhanden) denselben Link; wo er fehlt, bleibt die Kamera-App des Handys der Weg.
- **Icons aus dem Markenbild** (`assets/margenheld-icon.png`, 300 × 297): das 512er-Icon ist hochskaliert und etwas weich; ein Original in höherer Auflösung ersetzt es später ohne Codeänderung. Das maskierbare Icon legt das Motiv auf 70 % der Fläche vor den Hintergrund `#1a1a2e`.
- **Dark-Theme wie am Desktop** (Palette aus `src/theme/palette.py`), einziges Theme; `color-scheme: dark`. Tippziele mindestens 44 px, 16 px Seitenrand, kein horizontales Scrollen bei 320 px Breite.
- **Dev-Server als Werkzeug im Repo:** `scripts/pwa_devserver.py` startet die **echte** Handy-Instanz (`MobileService`, mit der Dev-Origin als erlaubter Origin) und serviert `pwa/` statisch. Er gehört wie die anderen Test-Server unter `scripts/` (nicht gebündelt). Damit lässt sich die PWA samt Service Worker auf `localhost` (sichere Origin) gegen echte Server-Logik prüfen, auch mit Playwright.

## Global Constraints

- Reines JavaScript/HTML/CSS, keine npm-Abhängigkeit, kein Build-Schritt; die Laufzeitdateien sind genau die Dateien unter `pwa/` außerhalb von `test/` und `package.json`.
- Kein `innerHTML` & Co. (Test); jede Zeichenkette aus Daten wird als Textknoten eingefügt.
- Pfade in `index.html`, Manifest, Service Worker und Modulen sind **relativ** (`./…`): die Seite liegt unter `/Zeiterfassung/`.
- Summen nur über ganze Minuten (Regel aus PR 6); Datum deutsch, Speicherung ISO.
- Kein Token, kein Code, kein Gerätename in `console.*`.
- Python: `ruff check .` und `pyright 1.1.411` sauber; die Desktop-Tests bleiben unverändert grün.
- Der Workflow `pages.yml` pusht nichts nach `master` und hat nur `contents: read`, `pages: write`, `id-token: write`.

## Review Focus

1. **Datenverlust in der Oberfläche:** ein ungespeicherter Editor-Inhalt geht bei einem Hintergrund-Render nicht verloren; „Speichern" legt nie einen ungültigen Tag an; „Tag leeren" fragt nach; nach `401`, Offline und `422` bleiben alle lokalen Einträge sichtbar. Tasks 2 und 4.
2. **Fremddaten im DOM:** Kategorienamen, Gerätenamen, Konflikt-Versionen und Fehlertexte vom Desktop sowie der QR-/Link-Inhalt erscheinen nur als Text; ein `<img onerror=…>` im Namen bleibt Text. Task 4 (Test und Browser-Check).
3. **Service Worker:** Offline-Start funktioniert; API-Antworten werden nie gecacht und Anfragen an den Desktop gehen am Service Worker vorbei; ein neuer Deploy ersetzt den Cache nur nach „Neu laden"; ein alter Cache wird aufgeräumt; kein Update-Schleifenbruch. Tasks 3 und 5.
4. **Koppeln:** das Fragment wird nach dem Lesen entfernt; ein manipulierter Link mit fremdem Host wird nicht gesendet (Prüfung aus PR 6); der Geräte-Name ist bearbeitbar und ≤ 60 Zeichen; nach „Neu koppeln" bleiben nicht übertragene Tage. Tasks 1, 4, 5.
5. **Abgleichauslöser:** kein Dauerfeuer bei Fehlern, kein Abgleich mit totem Token, `save` und `manual` kommen immer durch, kein Doppel-Abgleich. Tasks 1 und 4.
6. **Barrierefreiheit und Mobilgerät:** Beschriftungen an allen Feldern, `aria-live` an der Statuszeile, Fokus im Dialog, Tippziele, Layout bei 320 px, Tastatur (`type="time"`, `inputmode="numeric"`). Tasks 3 und 4.
7. **Auslieferung:** Workflow läuft ohne Python/Node-Abhängigkeiten, setzt die Build-Kennung, veröffentlicht nur Laufzeitdateien (kein `test/`); `PWA_URL`/`PWA_ORIGIN` des Desktops passen zur tatsächlichen Adresse. Task 6.

---

### Task 1: `messages.js`, `sync-policy.js` und `parseQrText`

**Files:**
- Create: `pwa/messages.js`, `pwa/sync-policy.js`, `pwa/test/messages.test.js`, `pwa/test/sync-policy.test.js`
- Modify: `pwa/pairing.js`, `pwa/test/pairing.test.js`

**Interfaces:** Produces: `describeError(error) -> {text, action}` (`action`: `null | 'pair' | 'rescan' | 'retry'`); `shouldSync({trigger, paired, syncing, online, now, lastAttemptAt, lastError}) -> boolean` mit `AUTO_COOLDOWN_MS = 5000`, `OFFLINE_BACKOFF_MS = 30000`; in `pairing.js` `parseQrText(text) -> {host, port, code}|null` (der gescannte Text ist der volle Link; ausgewertet wird nur das Fragment).

- [ ] **Step 1: Write the failing tests**

Create `pwa/test/messages.test.js`:

```js
// pwa/test/messages.test.js
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

import { describeError } from '../messages.js';
import { SyncError } from '../sync.js';

const errors = JSON.parse(readFileSync(new URL('./fixtures/errors.json', import.meta.url)));

test('every error kind the server can produce has its own text', () => {
  const kinds = new Set(errors.map((row) => row.kind));
  for (const extra of ['offline', 'not_paired']) kinds.add(extra);
  const fallback = describeError(new SyncError({ kind: 'völlig_neu' })).text;
  for (const kind of kinds) {
    const { text } = describeError(new SyncError({ kind, message: 'Text vom Server', code: '' }));
    assert.ok(text.length > 10, kind);
    assert.notEqual(text, fallback, `${kind} fällt auf den Standardtext zurück`);
  }
});

test('re-pairing is offered for every case where the token is no longer accepted', () => {
  for (const code of ['unauthorized', 'token_expired', 'token_revoked']) {
    const result = describeError(new SyncError({ kind: 'repair', code, needsRepair: true }));
    assert.equal(result.action, 'pair', code);
  }
});

test('the revoked, expired and replaced cases are told apart', () => {
  const text = (code) => describeError(new SyncError({ kind: 'repair', code })).text;
  assert.match(text('token_revoked'), /widerrufen/);
  assert.match(text('token_expired'), /abgelaufen/);
  assert.match(text('unauthorized'), /nicht mehr akzeptiert/);
});

test('an unreachable desktop offers a new scan', () => {
  assert.equal(describeError(new SyncError({ kind: 'offline' })).action, 'rescan');
  assert.equal(describeError(new SyncError({ kind: 'address' })).action, 'rescan');
});

test('server texts are passed through for invalid entries and client errors', () => {
  assert.match(describeError(new SyncError({ kind: 'invalid_entry', message: '2026-10-07: Endzeit muss nach Startzeit liegen' })).text,
    /Endzeit muss nach Startzeit liegen/);
  assert.match(describeError(new SyncError({ kind: 'client_error', message: 'Body ist zu groß.' })).text, /Body ist zu groß/);
});

test('clock skew and locked pairing say what to do', () => {
  assert.match(describeError(new SyncError({ kind: 'clock_skew' })).text, /Uhr/);
  assert.match(describeError(new SyncError({ kind: 'pairing_locked' })).text, /neuen Code/);
  assert.match(describeError(new SyncError({ kind: 'invalid_code' })).text, /neuen Code/);
});

test('transient and server errors may be retried', () => {
  assert.equal(describeError(new SyncError({ kind: 'transient', code: 'busy' })).action, 'retry');
  assert.equal(describeError(new SyncError({ kind: 'server' })).action, 'retry');
});

test('anything that is not a SyncError still gets a text', () => {
  assert.ok(describeError(new Error('kaputt')).text.length > 10);
  assert.ok(describeError(null).text.length > 10);
  assert.ok(describeError(undefined).text.length > 10);
});
```

Create `pwa/test/sync-policy.test.js`:

```js
// pwa/test/sync-policy.test.js
import { test } from 'node:test';
import assert from 'node:assert/strict';

import { AUTO_COOLDOWN_MS, OFFLINE_BACKOFF_MS, shouldSync } from '../sync-policy.js';

const base = { paired: true, syncing: false, online: true, now: 1_000_000, lastAttemptAt: 0, lastError: null };
const ask = (over) => shouldSync({ ...base, ...over });

test('nothing runs without a pairing or while a sync is running', () => {
  for (const trigger of ['start', 'visible', 'online', 'save', 'manual']) {
    assert.equal(ask({ trigger, paired: false }), false, trigger);
    assert.equal(ask({ trigger, syncing: true }), false, trigger);
  }
});

test('manual and save always run, even right after an attempt, offline or with a dead token', () => {
  const hostile = { lastAttemptAt: base.now - 1, online: false, lastError: { kind: 'repair', needsRepair: true } };
  assert.equal(ask({ trigger: 'manual', ...hostile }), true);
  assert.equal(ask({ trigger: 'save', ...hostile, online: true }), true);
});

test('save does not wait for the cooldown', () => {
  assert.equal(ask({ trigger: 'save', lastAttemptAt: base.now - 100 }), true);
});

test('automatic triggers wait for the cooldown', () => {
  for (const trigger of ['start', 'visible', 'online']) {
    assert.equal(ask({ trigger, lastAttemptAt: base.now - (AUTO_COOLDOWN_MS - 1) }), false, trigger);
    assert.equal(ask({ trigger, lastAttemptAt: base.now - AUTO_COOLDOWN_MS }), true, trigger);
  }
});

test('automatic triggers stay quiet while the browser says offline, except the online event', () => {
  assert.equal(ask({ trigger: 'start', online: false }), false);
  assert.equal(ask({ trigger: 'visible', online: false }), false);
  assert.equal(ask({ trigger: 'online', online: true }), true);
});

test('after a network failure start and visible back off, the online event does not', () => {
  const lastError = { kind: 'offline', needsRepair: false };
  const recent = base.now - (OFFLINE_BACKOFF_MS - 1000);
  assert.equal(ask({ trigger: 'start', lastError, lastAttemptAt: recent }), false);
  assert.equal(ask({ trigger: 'visible', lastError, lastAttemptAt: recent }), false);
  assert.equal(ask({ trigger: 'online', lastError, lastAttemptAt: base.now - AUTO_COOLDOWN_MS }), true);
  assert.equal(ask({ trigger: 'start', lastError, lastAttemptAt: base.now - OFFLINE_BACKOFF_MS }), true);
});

test('a dead token stops every automatic trigger until the user pairs again', () => {
  const lastError = { kind: 'repair', needsRepair: true };
  for (const trigger of ['start', 'visible', 'online']) {
    assert.equal(ask({ trigger, lastError }), false, trigger);
  }
});

test('an unknown trigger does nothing', () => {
  assert.equal(ask({ trigger: 'zufall' }), false);
});
```

Hänge an `pwa/test/pairing.test.js` an (und ergänze `parseQrText` in der Importliste):

```js
test('a scanned QR text is the full link; only its fragment counts', () => {
  assert.deepEqual(parseQrText('https://xveyn.github.io/Zeiterfassung/#pair=192.168.178.20:17654:K7M29QXA'),
    { host: '192.168.178.20', port: 17654, code: 'K7M29QXA' });
  assert.deepEqual(parseQrText('http://localhost:8099/#pair=10.0.0.5:20000:23456789'),
    { host: '10.0.0.5', port: 20000, code: '23456789' });
  for (const bad of ['', 'kein link', 'https://x.example/#pair=8.8.8.8:17654:K7M29QXA',
    'https://x.example/#pair=192.168.1.20:80:K7M29QXA', 'https://x.example/', 'https://x.example/#other=1',
    null, undefined, 5, 'http://[::1', 'a'.repeat(5000)]) {
    assert.equal(parseQrText(bad), null, String(bad).slice(0, 30));
  }
});
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd pwa && node --test 2>&1 | grep -E "ERR_MODULE|^# (pass|fail)" | head -4`
Expected: `ERR_MODULE_NOT_FOUND` für `../messages.js` (und `../sync-policy.js`); der Import `parseQrText` fehlt.

- [ ] **Step 3: Implement**

Create `pwa/messages.js`:

```js
// pwa/messages.js
// Fehler einordnen für Menschen: jede `SyncError.kind` bekommt einen deutschen Text und einen
// Ausweg. Die Arten stehen in `test/fixtures/errors.json`; der Test verlangt für jede einen
// eigenen Text, damit ein neuer Fehlercode im Server nicht als „unbekannter Fehler" endet.

const DEFAULT = { text: 'Der Abgleich ist fehlgeschlagen. Bitte später erneut versuchen.', action: 'retry' };

const REPAIR = {
  token_revoked: 'Dieses Handy wurde am Desktop widerrufen. Bitte neu koppeln — Ihre nicht übertragenen Einträge bleiben erhalten.',
  token_expired: 'Die Kopplung ist abgelaufen. Bitte neu koppeln — Ihre nicht übertragenen Einträge bleiben erhalten.',
};
const REPAIR_FALLBACK = 'Der Desktop akzeptiert die Kopplung nicht mehr (neu gekoppelt?). Bitte neu koppeln — Ihre nicht übertragenen Einträge bleiben erhalten.';

/** @param {unknown} error */
export function describeError(error) {
  if (!error || typeof error !== 'object' || typeof error.kind !== 'string') return DEFAULT;
  const server = typeof error.message === 'string' ? error.message : '';
  switch (error.kind) {
    case 'offline':
      return { text: 'Der Desktop ist nicht erreichbar. Läuft die App am Rechner, und sind Handy und Rechner im selben WLAN?', action: 'rescan' };
    case 'address':
      return { text: 'Falscher Desktop oder falsche Adresse. Den QR-Code am Desktop neu scannen.', action: 'rescan' };
    case 'repair':
      return { text: REPAIR[error.code] ?? REPAIR_FALLBACK, action: 'pair' };
    case 'not_paired':
      return { text: 'Dieses Handy ist noch nicht gekoppelt.', action: 'pair' };
    case 'browser':
      return { text: 'Dieser Browser sendet die Anfrage als seitenübergreifend (Sec-Fetch-Site) und der Desktop lehnt sie ab. Bitte Chrome auf Android verwenden.', action: null };
    case 'invalid_code':
      return { text: 'Der Code ist ungültig oder abgelaufen. Am Desktop einen neuen Code erzeugen.', action: 'pair' };
    case 'pairing_locked':
      return { text: 'Zu viele Fehlversuche. Am Desktop einen neuen Code erzeugen.', action: 'pair' };
    case 'clock_skew':
      return { text: 'Die Uhr des Handys weicht mehr als 15 Minuten von der des Desktops ab. Datum und Uhrzeit am Handy prüfen.', action: null };
    case 'invalid_entry':
      return { text: `Der Desktop hat einen Tag abgelehnt: ${server || 'ungültiger Eintrag'}`, action: null };
    case 'transient':
      return { text: 'Der Desktop ist gerade beschäftigt. Bitte gleich erneut versuchen.', action: 'retry' };
    case 'server':
      return { text: 'Der Desktop meldet einen internen Fehler. Details stehen im Protokoll der Desktop-App.', action: 'retry' };
    case 'protocol':
      return { text: 'Die App-Versionen von Handy und Desktop passen nicht zusammen. Desktop-App und diese Seite aktualisieren.', action: null };
    case 'client_error':
      return { text: `Anfrage abgelehnt: ${server || 'unbekannter Grund'}`, action: null };
    default:
      return DEFAULT;
  }
}
```

Create `pwa/sync-policy.js`:

```js
// pwa/sync-policy.js
// Wann darf ein Abgleich laufen? Die Spec erlaubt genau diese Auslöser: Start, Sichtbarwerden,
// `online`-Ereignis, 2 s nach dem Speichern, Knopfdruck — kein Hintergrund-Sync. Diese Funktion
// verhindert, dass die automatischen Auslöser bei Fehlern im Dauerfeuer laufen.

export const AUTO_COOLDOWN_MS = 5000;
export const OFFLINE_BACKOFF_MS = 30000;
const AUTOMATIC = new Set(['start', 'visible', 'online']);

export function shouldSync({ trigger, paired, syncing, online, now, lastAttemptAt, lastError }) {
  if (!paired || syncing) return false;
  if (trigger === 'manual' || trigger === 'save') return true;       // der Nutzer hat es gewollt
  if (!AUTOMATIC.has(trigger)) return false;
  if (lastError?.needsRepair) return false;                          // totes Token: erst neu koppeln
  if (trigger !== 'online' && !online) return false;
  if (now - lastAttemptAt < AUTO_COOLDOWN_MS) return false;
  if (trigger !== 'online' && lastError?.kind === 'offline' && now - lastAttemptAt < OFFLINE_BACKOFF_MS) {
    return false;
  }
  return true;
}
```

In `pwa/pairing.js` füge nach `parsePairFragment` ein:

```js

/** Gescannter QR-Text (der volle Link) → `{host, port, code}` oder `null`. Nur das Fragment
 *  zählt; Schema, Host und Pfad der Seite sind egal (Dev-Server, Pages, spätere Umzüge). */
export function parseQrText(text) {
  if (typeof text !== 'string' || text.length > 512) return null;
  const hash = text.indexOf('#');
  return hash === -1 ? null : parsePairFragment(text.slice(hash));
}
```

- [ ] **Step 4: Run to verify they pass**

Run: `cd pwa && node --test 2>&1 | grep -E "^not ok|^# (pass|fail)"`
Expected: `# fail 0`.

- [ ] **Step 5: Commit**

~~~bash
git add pwa/messages.js pwa/sync-policy.js pwa/pairing.js pwa/test/messages.test.js pwa/test/sync-policy.test.js pwa/test/pairing.test.js
git commit -m "feat(pwa): Fehlertexte, Abgleich-Regeln und QR-Text (#221)

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
~~~

---

### Task 2: `view-model.js`

**Files:**
- Create: `pwa/view-model.js`, `pwa/test/view-model.test.js`

**Interfaces:** Consumes: `minutes.js`, `messages.js`. Produces: `WEEKDAYS`; `slotText(slot)`; `localTime(iso, timeZone?)`; `weekModel({getDay, anchor, today, conflictDates}) -> {title, range, anchor, isCurrent, days, totalMinutes, totalLabel}` mit `days[i] = {date, weekday, label, isToday, isWeekend, beyondWindow, slots, minutes, minutesLabel, state, dirty, error, conflict}`; `statusModel({paired, online, syncing, pending, lastSyncAt, timeZone?})`; `hintsModel({lastError, excluded, skewMs, persistent, updateReady, conflictCount, errorDays}) -> [{id, kind, text, action}]`; `conflictsModel(conflicts, timeZone?)`; `editorRows(day)`, `blankRow(previous?)`, `rowsToSlots(rows)`, `validateRows(rows) -> {ok, message}`.

- [ ] **Step 1: Write the failing tests**

Create `pwa/test/view-model.test.js`:

```js
// pwa/test/view-model.test.js
import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
  WEEKDAYS, blankRow, conflictsModel, editorRows, hintsModel, localTime, rowsToSlots, slotText,
  statusModel, validateRows, weekModel,
} from '../view-model.js';
import { SyncError } from '../sync.js';

const SLOT = { start: '08:00', end: '12:00', pause: 0, kategorie: 'Projekt' };
const days = (map) => (date) => map[date] ?? null;
const live = (slots, over = {}) => ({ slots, deleted: false, dirty: false, error: null, modified_at: 'x', ...over });

// --- Woche -----------------------------------------------------------------------------------------

test('a slot reads start–end, pause and category', () => {
  assert.equal(slotText(SLOT), '08:00–12:00 · Projekt');
  assert.equal(slotText({ start: '08:00', end: '16:30', pause: 30, kategorie: '' }), '08:00–16:30 · 30 min Pause');
  assert.equal(slotText({ start: '08:00', end: '12:00', pause: 15, kategorie: 'A' }), '08:00–12:00 · 15 min Pause · A');
  assert.equal(slotText({ start: '08:00', end: '12:00', pause: 'x', kategorie: 5 }), '08:00–12:00');
});

test('the week model lists Monday to Sunday with German dates and the ISO week', () => {
  const week = weekModel({ getDay: days({}), anchor: '2026-10-08', today: '2026-10-08' });
  assert.equal(week.title, 'KW 41');
  assert.equal(week.range, '05.10.–11.10.2026');
  assert.equal(week.anchor, '2026-10-05');
  assert.equal(week.isCurrent, true);
  assert.deepEqual(week.days.map((d) => d.weekday), WEEKDAYS);
  assert.deepEqual(week.days.map((d) => d.date), [
    '2026-10-05', '2026-10-06', '2026-10-07', '2026-10-08', '2026-10-09', '2026-10-10', '2026-10-11']);
  assert.equal(week.days[3].isToday, true);
  assert.deepEqual(week.days.map((d) => d.isWeekend), [false, false, false, false, false, true, true]);
  assert.equal(week.days[3].label, '08.10.2026');
});

test('a week that does not contain today is not current', () => {
  assert.equal(weekModel({ getDay: days({}), anchor: '2026-09-30', today: '2026-10-08' }).isCurrent, false);
});

test('sums are whole minutes per day and for the week', () => {
  const getDay = days({
    '2026-10-05': live([{ start: '08:00', end: '10:20', pause: 0, kategorie: '' }, { start: '10:30', end: '12:07', pause: 0, kategorie: '' }]),
    '2026-10-06': live([{ start: '09:00', end: '17:30', pause: 30, kategorie: '' }]),
  });
  const week = weekModel({ getDay, anchor: '2026-10-05', today: '2026-10-08' });
  assert.equal(week.days[0].minutes, 140 + 97);
  assert.equal(week.days[0].minutesLabel, '3:57');
  assert.equal(week.days[1].minutesLabel, '8:00');
  assert.equal(week.totalMinutes, 237 + 480);
  assert.equal(week.totalLabel, '11:57');
  assert.equal(week.days[2].minutesLabel, '');
});

test('day states: empty, filled, cleared; flags for pending, error and conflict', () => {
  const getDay = days({
    '2026-10-05': live([SLOT], { dirty: true }),
    '2026-10-06': live([], { deleted: true }),
    '2026-10-07': live([SLOT], { error: 'abgelehnt' }),
  });
  const week = weekModel({ getDay, anchor: '2026-10-05', today: '2026-10-08', conflictDates: ['2026-10-07'] });
  assert.deepEqual(week.days.slice(0, 4).map((d) => d.state), ['filled', 'cleared', 'filled', 'empty']);
  assert.equal(week.days[0].dirty, true);
  assert.equal(week.days[1].minutes, 0);
  assert.equal(week.days[2].error, 'abgelehnt');
  assert.equal(week.days[2].conflict, true);
  assert.equal(week.days[0].conflict, false);
});

test('days after tomorrow are marked as beyond the window', () => {
  const week = weekModel({ getDay: days({}), anchor: '2026-10-08', today: '2026-10-08' });
  assert.deepEqual(week.days.map((d) => d.beyondWindow), [false, false, false, false, false, true, true]);
});

test('the sum ignores broken stored slots instead of throwing', () => {
  const getDay = days({ '2026-10-05': live([{ start: 'x', end: null, pause: 'a' }, SLOT]) });
  assert.equal(weekModel({ getDay, anchor: '2026-10-05', today: '2026-10-05' }).totalMinutes, 240);
});

// --- Status ----------------------------------------------------------------------------------------

test('the local time is shown in the given zone', () => {
  assert.equal(localTime('2026-10-08T12:34:56Z', 'UTC'), '12:34');
  assert.equal(localTime('2026-10-08T12:34:56Z', 'Europe/Berlin'), '14:34');
  assert.equal(localTime('kaputt', 'UTC'), '');
});

test('the status line says online, pending changes and the last sync', () => {
  const status = statusModel({ paired: true, online: true, syncing: false, pending: 3,
    lastSyncAt: '2026-10-08T12:34:00Z', timeZone: 'UTC' });
  assert.equal(status.connection, 'Online');
  assert.equal(status.pendingText, '3 Änderungen nicht übertragen');
  assert.equal(status.lastText, 'zuletzt abgeglichen um 12:34');
  assert.equal(status.canSync, true);
});

test('status line variants', () => {
  const base = { paired: true, online: true, syncing: false, pending: 0, lastSyncAt: '', timeZone: 'UTC' };
  assert.equal(statusModel({ ...base, pending: 1 }).pendingText, '1 Änderung nicht übertragen');
  assert.equal(statusModel(base).pendingText, '');
  assert.equal(statusModel(base).lastText, 'noch nicht abgeglichen');
  assert.equal(statusModel({ ...base, online: false }).connection, 'Offline');
  assert.equal(statusModel({ ...base, syncing: true }).connection, 'Gleiche ab …');
  assert.equal(statusModel({ ...base, syncing: true }).canSync, false);
  assert.equal(statusModel({ ...base, paired: false }).connection, 'Nicht gekoppelt');
  assert.equal(statusModel({ ...base, paired: false }).canSync, false);
});

// --- Hinweise --------------------------------------------------------------------------------------

const none = { lastError: null, excluded: false, skewMs: 0, persistent: true, updateReady: false, conflictCount: 0, errorDays: 0 };

test('no hints when everything is fine', () => {
  assert.deepEqual(hintsModel(none), []);
});

test('each situation gets its hint and way out', () => {
  const ids = (over) => hintsModel({ ...none, ...over }).map((hint) => hint.id);
  assert.deepEqual(ids({ lastError: new SyncError({ kind: 'offline' }) }), ['error']);
  assert.deepEqual(ids({ excluded: true }), ['excluded']);
  assert.deepEqual(ids({ skewMs: 180000 }), ['skew']);
  assert.deepEqual(ids({ skewMs: -180000 }), ['skew']);
  assert.deepEqual(ids({ skewMs: 60000 }), []);
  assert.deepEqual(ids({ persistent: false }), ['storage']);
  assert.deepEqual(ids({ persistent: null }), []);                  // noch nicht gefragt
  assert.deepEqual(ids({ updateReady: true }), ['update']);
  assert.deepEqual(ids({ conflictCount: 2 }), ['conflicts']);
  assert.deepEqual(ids({ errorDays: 1 }), ['rejected']);
});

test('hint texts and actions', () => {
  const find = (over, id) => hintsModel({ ...none, ...over }).find((hint) => hint.id === id);
  assert.equal(find({ lastError: new SyncError({ kind: 'repair', code: 'token_expired' }) }, 'error').action, 'pair');
  assert.equal(find({ lastError: new SyncError({ kind: 'offline' }) }, 'error').action, 'rescan');
  assert.match(find({ excluded: true }, 'excluded').text, /Am Desktop gelöschte Einträge bleiben gelöscht/);
  assert.match(find({ skewMs: 180000 }, 'skew').text, /3 Minuten/);
  assert.match(find({ persistent: false }, 'storage').text, /dauerhaft/);
  assert.equal(find({ updateReady: true }, 'update').action, 'reload');
  assert.equal(find({ conflictCount: 1 }, 'conflicts').text, '1 Konflikt: am Desktop lösen.');
  assert.equal(find({ conflictCount: 3 }, 'conflicts').text, '3 Konflikte: am Desktop lösen.');
  assert.equal(find({ conflictCount: 3 }, 'conflicts').action, 'conflicts');
  assert.equal(find({ errorDays: 2 }, 'rejected').text, '2 Tage wurden vom Desktop abgelehnt — bitte prüfen.');
});

test('an error hint comes first', () => {
  const hints = hintsModel({ ...none, lastError: new SyncError({ kind: 'offline' }), conflictCount: 1, updateReady: true });
  assert.equal(hints[0].id, 'error');
});

// --- Konflikte -------------------------------------------------------------------------------------

test('a conflict shows both versions read-only with names, times and sums', () => {
  const conflicts = [{ id: 'c1', date: '2026-10-05', versions: [
    { device: '6f1c2b9e-3d4a-4b5c', name: 'Pixel von Sven', modified_at: '2026-10-07T18:30:00Z', slots: [SLOT] },
    { device: 'DESKTOP-ABCDEF', name: '', modified_at: '2026-10-07T20:00:00Z',
      slots: [{ start: '09:00', end: '13:00', pause: 0, kategorie: '' }] },
  ] }];
  const [model] = conflictsModel(conflicts, 'UTC');
  assert.equal(model.id, 'c1');
  assert.equal(model.dateLabel, '05.10.2026');
  assert.equal(model.versions[0].who, 'Pixel von Sven');
  assert.equal(model.versions[1].who, 'DESKTOP-');                  // ohne Namen: gekürzte ID
  assert.equal(model.versions[0].when, '07.10.2026 18:30');
  assert.deepEqual(model.versions[0].slots, ['08:00–12:00 · Projekt']);
  assert.equal(model.versions[0].minutesLabel, '4:00');
});

test('a conflict with a deleted version says so', () => {
  const [model] = conflictsModel([{ id: 'c', date: '2026-10-05', versions: [
    { device: 'A', name: 'A', modified_at: '2026-10-07T18:30:00Z', slots: [] }] }], 'UTC');
  assert.deepEqual(model.versions[0].slots, []);
  assert.equal(model.versions[0].minutesLabel, '0:00');
});

test('conflicts are sorted by date and junk is skipped', () => {
  const models = conflictsModel([
    { id: 'b', date: '2026-10-06', versions: [] }, null, 'x', { id: 'a', date: '2026-10-05', versions: 'x' },
  ], 'UTC');
  assert.deepEqual(models.map((m) => m.id), ['a', 'b']);
});

// --- Editor ----------------------------------------------------------------------------------------

test('the editor starts from the stored slots or from one blank row', () => {
  assert.deepEqual(editorRows(null), [blankRow()]);
  assert.deepEqual(editorRows(live([], { deleted: true })), [blankRow()]);
  assert.deepEqual(editorRows(live([{ start: '08:00', end: '12:00', pause: 15, kategorie: 'A' }])),
    [{ start: '08:00', end: '12:00', pause: '15', kategorie: 'A' }]);
});

test('a new row continues after the previous one', () => {
  assert.deepEqual(blankRow(), { start: '', end: '', pause: '0', kategorie: '' });
  assert.deepEqual(blankRow({ start: '08:00', end: '12:00', pause: '0', kategorie: 'A' }),
    { start: '12:00', end: '', pause: '0', kategorie: 'A' });
  assert.deepEqual(blankRow({ start: '08:00', end: '', pause: '0', kategorie: '' }),
    { start: '', end: '', pause: '0', kategorie: '' });
});

test('rows become wire slots; blank rows are dropped', () => {
  const rows = [
    { start: '08:00', end: '12:00', pause: '15', kategorie: ' Projekt ' },
    { start: '', end: '', pause: '0', kategorie: '' },
    { start: '13:00', end: '17:00', pause: '', kategorie: '' },
  ];
  assert.deepEqual(rowsToSlots(rows), [
    { start: '08:00', end: '12:00', pause: 15, kategorie: ' Projekt ' },
    { start: '13:00', end: '17:00', pause: 0, kategorie: '' },
  ]);
});

test('validation uses the same rules as the server and speaks German', () => {
  const ok = [{ start: '08:00', end: '12:00', pause: '0', kategorie: 'A' }];
  assert.deepEqual(validateRows(ok), { ok: true, message: '' });
  assert.equal(validateRows([blankRow()]).ok, false);
  assert.match(validateRows([blankRow()]).message, /Mindestens ein Slot/);
  assert.equal(validateRows([{ ...ok[0], end: '07:00' }]).message, 'Endzeit muss nach Startzeit liegen');
  assert.equal(validateRows([{ ...ok[0], start: '' }]).message, 'Startzeit ungültig (Format: HH:MM)');
  assert.equal(validateRows([{ ...ok[0], pause: '1.5' }]).ok, false);
  assert.equal(validateRows([{ ...ok[0], pause: 'abc' }]).ok, false);
  assert.equal(validateRows([{ ...ok[0], pause: '240' }]).ok, false);
  assert.equal(validateRows([ok[0], { start: '11:00', end: '13:00', pause: '0', kategorie: '' }]).message,
    'Zeitslots dürfen sich zeitlich nicht überlappen.');
  assert.equal(validateRows([{ ...ok[0], kategorie: 'x'.repeat(101) }]).ok, false);
});
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd pwa && node --test test/view-model.test.js 2>&1 | grep -E "ERR_MODULE|^# (pass|fail)" | head -3`
Expected: `ERR_MODULE_NOT_FOUND` für `../view-model.js`.

- [ ] **Step 3: Implement**

Create `pwa/view-model.js`:

```js
// pwa/view-model.js
// Alles, was die Oberfläche anzeigt, als reine Daten: Wochenliste, Statuszeile, Hinweise,
// Konfliktliste, Editor-Zeilen. Kein DOM — die dünne Schicht in `views.js` macht daraus
// Elemente. Summen nur über ganze Minuten (`minutes.js`).
import {
  addDays, dayMinutes, formatDateDe, formatMinutes, isoWeek, mondayOf, normalizeSlots,
  validateSlots, weekDays,
} from './minutes.js';
import { describeError } from './messages.js';

export const WEEKDAYS = ['Mo', 'Di', 'Mi', 'Do', 'Fr', 'Sa', 'So'];
const SKEW_WARN_MS = 120000;
// Wie `store.js`: Tage nach heute + 1 räumt der Abgleich am Handy wieder auf (#265).
const VISIBLE_AHEAD_DAYS = 1;

const isObject = (value) => value !== null && typeof value === 'object' && !Array.isArray(value);

export function slotText(slot) {
  const pause = Number.isInteger(slot.pause) && slot.pause > 0 ? ` · ${slot.pause} min Pause` : '';
  const category = typeof slot.kategorie === 'string' && slot.kategorie ? ` · ${slot.kategorie}` : '';
  return `${slot.start}–${slot.end}${pause}${category}`;
}

export function localTime(iso, timeZone) {
  const time = Date.parse(iso);
  if (Number.isNaN(time)) return '';
  return new Intl.DateTimeFormat('de-DE', { hour: '2-digit', minute: '2-digit', timeZone }).format(new Date(time));
}

function stampLabel(iso, timeZone) {
  const time = localTime(iso, timeZone);
  return time ? `${formatDateDe(iso.slice(0, 10))} ${time}` : '';
}

// --- Woche ---------------------------------------------------------------------------------------

export function weekModel({ getDay, anchor, today, conflictDates = [] }) {
  const conflicts = new Set(conflictDates);
  const dates = weekDays(anchor);
  const week = dates.map((date, index) => {
    const day = getDay(date);
    const cleared = Boolean(day?.deleted);
    const slots = day && !cleared ? day.slots : [];
    const minutes = dayMinutes(slots);
    return {
      date,
      weekday: WEEKDAYS[index],
      label: formatDateDe(date),
      isToday: date === today,
      isWeekend: index >= 5,
      beyondWindow: date > addDays(today, VISIBLE_AHEAD_DAYS),
      slots: slots.map(slotText),
      minutes,
      minutesLabel: minutes > 0 ? formatMinutes(minutes) : '',
      state: !day ? 'empty' : cleared ? 'cleared' : 'filled',
      dirty: Boolean(day?.dirty),
      error: day?.error ?? null,
      conflict: conflicts.has(date),
    };
  });
  const total = week.reduce((sum, day) => sum + day.minutes, 0);
  return {
    title: `KW ${isoWeek(anchor).week}`,
    range: `${formatDateDe(dates[0]).slice(0, 6)}–${formatDateDe(dates[6])}`,
    anchor: mondayOf(anchor),
    isCurrent: dates.includes(today),
    days: week,
    totalMinutes: total,
    totalLabel: formatMinutes(total),
  };
}

// --- Status und Hinweise -------------------------------------------------------------------------

export function statusModel({ paired, online, syncing, pending, lastSyncAt, timeZone }) {
  const pendingText = pending === 0 ? '' : pending === 1 ? '1 Änderung nicht übertragen'
    : `${pending} Änderungen nicht übertragen`;
  const last = lastSyncAt ? localTime(lastSyncAt, timeZone) : '';
  return {
    paired, online, syncing, pendingText,
    lastText: last ? `zuletzt abgeglichen um ${last}` : 'noch nicht abgeglichen',
    connection: !paired ? 'Nicht gekoppelt' : syncing ? 'Gleiche ab …' : online ? 'Online' : 'Offline',
    canSync: paired && !syncing,
  };
}

export function hintsModel({ lastError, excluded, skewMs, persistent, updateReady, conflictCount, errorDays }) {
  const hints = [];
  if (lastError) {
    const { text, action } = describeError(lastError);
    hints.push({ id: 'error', kind: 'error', text, action });
  }
  if (updateReady) hints.push({ id: 'update', kind: 'info', text: 'Neue Version verfügbar.', action: 'reload' });
  if (conflictCount > 0) {
    hints.push({ id: 'conflicts', kind: 'warn', action: 'conflicts',
      text: `${conflictCount} ${conflictCount === 1 ? 'Konflikt' : 'Konflikte'}: am Desktop lösen.` });
  }
  if (errorDays > 0) {
    hints.push({ id: 'rejected', kind: 'warn', action: null,
      text: `${errorDays} ${errorDays === 1 ? 'Tag wurde' : 'Tage wurden'} vom Desktop abgelehnt — bitte prüfen.` });
  }
  if (excluded) {
    hints.push({ id: 'excluded', kind: 'info', action: null,
      text: 'Dieses Handy war länger offline als die letzte Kompaktierung am Desktop. Am Desktop gelöschte Einträge bleiben gelöscht.' });
  }
  if (Math.abs(skewMs || 0) >= SKEW_WARN_MS) {
    hints.push({ id: 'skew', kind: 'warn', action: null,
      text: `Die Uhr des Handys weicht um etwa ${Math.round(Math.abs(skewMs) / 60000)} Minuten von der des Desktops ab. Datum und Uhrzeit am Handy prüfen.` });
  }
  if (persistent === false) {
    hints.push({ id: 'storage', kind: 'warn', action: null,
      text: 'Der Browser sichert die Daten nicht dauerhaft. Nicht übertragene Einträge können bei Speichermangel verloren gehen.' });
  }
  return hints;
}

// --- Konflikte -----------------------------------------------------------------------------------

export function conflictsModel(conflicts, timeZone) {
  if (!Array.isArray(conflicts)) return [];
  return conflicts
    .filter((conflict) => isObject(conflict) && typeof conflict.date === 'string' && Array.isArray(conflict.versions))
    .map((conflict) => ({
      id: String(conflict.id),
      date: conflict.date,
      dateLabel: formatDateDe(conflict.date),
      versions: conflict.versions.filter(isObject).map((version) => {
        const slots = Array.isArray(version.slots) ? version.slots.filter(isObject) : [];
        return {
          who: version.name || String(version.device ?? '').slice(0, 8),
          when: stampLabel(String(version.modified_at ?? ''), timeZone),
          slots: slots.map(slotText),
          minutesLabel: formatMinutes(dayMinutes(slots)),
        };
      }),
    }))
    .sort((a, b) => a.date.localeCompare(b.date));
}

// --- Editor --------------------------------------------------------------------------------------

export function blankRow(previous) {
  const start = previous && previous.end ? previous.end : '';
  return { start, end: '', pause: '0', kategorie: previous?.kategorie ?? '' };
}

export function editorRows(day) {
  if (!day || day.deleted || day.slots.length === 0) return [blankRow()];
  return day.slots.map((slot) => ({
    start: slot.start, end: slot.end, pause: String(slot.pause ?? 0), kategorie: slot.kategorie ?? '',
  }));
}

const isBlank = (row) => row.start === '' && row.end === '' && (row.pause === '' || row.pause === '0')
  && row.kategorie === '';

/** Formularzeilen → Slots für `Store.saveDay` (das normalisiert und prüft erneut). Ganz leere
 *  Zeilen entfallen, damit ein vergessenes „+ Slot“ nicht stört. */
export function rowsToSlots(rows) {
  return rows.filter((row) => !isBlank(row)).map((row) => ({
    start: row.start, end: row.end,
    pause: row.pause === '' ? 0 : Number(row.pause),
    kategorie: row.kategorie,
  }));
}

export function validateRows(rows) {
  return validateSlots(normalizeSlots(rowsToSlots(rows)));
}
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd pwa && node --test 2>&1 | grep -E "^not ok|^# (pass|fail)"`
Expected: `# fail 0`. Schlägt `localTime(..., 'Europe/Berlin')` fehl, weil Node ohne vollständige ICU-Daten läuft, melde das als Befund (Node 20 hat volle ICU); der Test bleibt.

- [ ] **Step 5: Commit**

~~~bash
git add pwa/view-model.js pwa/test/view-model.test.js
git commit -m "feat(pwa): Anzeige-Modelle für Woche, Status, Hinweise, Konflikte und Editor (#221)

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
~~~

---

### Task 3: Hülle — `index.html`, CSS, Manifest, Icons, Service Worker

**Files:**
- Create: `pwa/index.html`, `pwa/app.css`, `pwa/manifest.webmanifest`, `pwa/sw-core.js`, `pwa/sw.js`, `pwa/icons/icon-192.png`, `pwa/icons/icon-512.png`, `pwa/icons/icon-maskable-512.png`
- Create: `scripts/pwa_icons.py`
- Create: `pwa/test/shell.test.js`

**Interfaces:** Produces: `sw-core.js`: `BUILD`, `CACHE_PREFIX`, `CACHE_NAME`, `PRECACHE`, `shouldHandle(method, url, selfUrl) -> boolean`. `index.html` lädt `./app.js` (Task 4) und trägt `<div id="app">`.

- [ ] **Step 1: Write the failing tests**

Create `pwa/test/shell.test.js`:

```js
// pwa/test/shell.test.js
// Die Hülle der PWA: Manifest, Icons, Service-Worker-Kern, index.html — alles, was ohne
// Browser prüfbar ist, damit Auslieferungsfehler (fehlende Datei, vergessener Cache-Eintrag,
// Platzhalter) in der CI auffallen statt auf dem Handy.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { existsSync, readFileSync, readdirSync, statSync } from 'node:fs';
import { join, relative } from 'node:path';

import { BUILD, CACHE_NAME, CACHE_PREFIX, PRECACHE, shouldHandle } from '../sw-core.js';

const root = new URL('..', import.meta.url).pathname;
const read = (name) => readFileSync(join(root, name), 'utf8');

function walk(dir) {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    return statSync(path).isDirectory() ? walk(path) : [path];
  });
}

const EXCLUDED = new Set(['package.json', 'sw.js', 'memory-adapter.js']);
const runtimeFiles = () => walk(root)
  .map((path) => relative(root, path))
  .filter((path) => !path.startsWith('test/') && !path.startsWith('node_modules/') && !EXCLUDED.has(path))
  .sort();

// --- Vorab-Cache -----------------------------------------------------------------------------------

test('every runtime file is precached and every precache entry exists', () => {
  const listed = PRECACHE.filter((entry) => entry !== './').map((entry) => entry.replace(/^\.\//, '')).sort();
  assert.deepEqual(listed, runtimeFiles());
  assert.ok(PRECACHE.includes('./'), 'die Startseite unter dem Ordner-Pfad fehlt');
  for (const entry of listed) assert.ok(existsSync(join(root, entry)), entry);
});

test('precache entries are relative so the site works under /Zeiterfassung/', () => {
  for (const entry of PRECACHE) assert.match(entry, /^\.\//, entry);
});

test('the build id is a placeholder in the repository and part of the cache name', () => {
  assert.equal(BUILD, '__BUILD__');
  assert.equal(CACHE_NAME, `${CACHE_PREFIX}${BUILD}`);
  assert.equal(read('sw-core.js').split('__BUILD__').length - 1, 1, 'der Platzhalter muss genau einmal vorkommen');
});

// --- Welche Anfragen der Service Worker anfasst ---------------------------------------------------

const SELF = 'https://xveyn.github.io/Zeiterfassung/sw.js';

test('the service worker handles only its own precached GET requests', () => {
  const yes = ['https://xveyn.github.io/Zeiterfassung/', 'https://xveyn.github.io/Zeiterfassung/index.html',
    'https://xveyn.github.io/Zeiterfassung/app.js', 'https://xveyn.github.io/Zeiterfassung/icons/icon-192.png',
    'https://xveyn.github.io/Zeiterfassung/index.html?x=1', 'https://xveyn.github.io/Zeiterfassung/#pair=1'];
  for (const url of yes) assert.equal(shouldHandle('GET', url, SELF), true, url);
});

test('requests to the desktop and anything foreign pass by the service worker', () => {
  const no = ['http://192.168.178.20:17654/v1/sync', 'http://192.168.178.20:17654/v1/ping',
    'https://example.org/Zeiterfassung/app.js', 'https://xveyn.github.io/anderes-projekt/app.js',
    'https://xveyn.github.io/Zeiterfassung/unbekannt.js', 'https://xveyn.github.io/Zeiterfassung/test/store.test.js'];
  for (const url of no) assert.equal(shouldHandle('GET', url, SELF), false, url);
});

test('only GET is handled', () => {
  for (const method of ['POST', 'PUT', 'DELETE', 'HEAD', 'OPTIONS']) {
    assert.equal(shouldHandle(method, 'https://xveyn.github.io/Zeiterfassung/app.js', SELF), false, method);
  }
});

test('a broken URL never throws', () => {
  assert.equal(shouldHandle('GET', 'kein url', SELF), false);
  assert.equal(shouldHandle('GET', 'https://xveyn.github.io/Zeiterfassung/app.js', 'kaputt'), false);
});

test('the service worker also works on the local dev origin', () => {
  assert.equal(shouldHandle('GET', 'http://localhost:8099/app.js', 'http://localhost:8099/sw.js'), true);
  assert.equal(shouldHandle('GET', 'http://localhost:8099/', 'http://localhost:8099/sw.js'), true);
});

// --- Manifest und Icons ----------------------------------------------------------------------------

function pngSize(path) {
  const buffer = readFileSync(path);
  assert.equal(buffer.subarray(1, 4).toString(), 'PNG', path);
  return [buffer.readUInt32BE(16), buffer.readUInt32BE(20)];
}

test('the manifest is installable', () => {
  const manifest = JSON.parse(read('manifest.webmanifest'));
  assert.equal(manifest.name, 'Zeiterfassung');
  assert.ok(manifest.short_name.length <= 12);
  assert.equal(manifest.start_url, './');
  assert.equal(manifest.scope, './');
  assert.equal(manifest.display, 'standalone');
  assert.equal(manifest.lang, 'de');
  const css = read('app.css');
  assert.equal(manifest.background_color, /--bg:\s*(#[0-9a-f]{6})/i.exec(css)[1]);
  assert.equal(manifest.theme_color, manifest.background_color);
  const sizes = new Map(manifest.icons.map((icon) => [icon.src, icon]));
  for (const [src, expected, purpose] of [
    ['icons/icon-192.png', [192, 192], 'any'], ['icons/icon-512.png', [512, 512], 'any'],
    ['icons/icon-maskable-512.png', [512, 512], 'maskable']]) {
    const icon = sizes.get(src);
    assert.ok(icon, src);
    assert.equal(icon.type, 'image/png');
    assert.equal(icon.purpose, purpose);
    assert.equal(icon.sizes, `${expected[0]}x${expected[1]}`);
    assert.deepEqual(pngSize(join(root, src)), expected, src);
  }
});

// --- index.html --------------------------------------------------------------------------------------

test('index.html wires manifest, icons, styles and the app module with relative paths', () => {
  const html = read('index.html');
  assert.match(html, /<html lang="de"/);
  assert.match(html, /<meta name="viewport" content="width=device-width, initial-scale=1/);
  assert.match(html, /<meta name="theme-color" content="#1a1a2e"/);
  assert.match(html, /<link rel="manifest" href="manifest\.webmanifest"/);
  assert.match(html, /<link rel="stylesheet" href="app\.css"/);
  assert.match(html, /<script type="module" src="app\.js"/);
  assert.match(html, /<div id="app"/);
  assert.match(html, /<noscript>/);
  assert.doesNotMatch(html, /(?:src|href)="\//, 'absolute Pfade brechen unter /Zeiterfassung/');
  assert.doesNotMatch(html, /<script(?![^>]*\bsrc=)[^>]*>/, 'kein Inline-Skript');
});

// --- Keine HTML-Einschleusung ---------------------------------------------------------------------------

test('no runtime script uses an HTML-injection API', () => {
  const forbidden = /\binnerHTML\b|\bouterHTML\b|\binsertAdjacentHTML\b|document\.write|\beval\s*\(|new Function\s*\(/;
  for (const file of runtimeFiles().filter((path) => path.endsWith('.js'))) {
    assert.doesNotMatch(read(file), forbidden, file);
  }
});

test('the app logs no secrets', () => {
  for (const file of runtimeFiles().filter((path) => path.endsWith('.js'))) {
    assert.doesNotMatch(read(file), /console\.\w+\([^)]*(token|code|device_name)/i, file);
  }
});
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd pwa && node --test test/shell.test.js 2>&1 | grep -E "ERR_MODULE|^# (pass|fail)" | head -3`
Expected: `ERR_MODULE_NOT_FOUND` für `../sw-core.js`.

- [ ] **Step 3: Implement**

Create `scripts/pwa_icons.py` (Werkzeug, einmalig; die erzeugten PNGs liegen im Repo):

```python
#!/usr/bin/env python3
"""Erzeugt die PWA-Icons aus dem Markenbild `assets/margenheld-icon.png`.

    python scripts/pwa_icons.py

Schreibt nach `pwa/icons/`: `icon-192.png`, `icon-512.png` und `icon-maskable-512.png`
(Motiv auf 70 % der Fläche vor dem Theme-Hintergrund, damit die runde Maske nichts abschneidet).
Das Quellbild ist 300 × 297 Pixel groß: die 512er-Icons sind hochskaliert und etwas weich; ein
größeres Original ersetzt sie ohne Codeänderung. Nicht Teil der App, nicht gebündelt.
"""
from __future__ import annotations

import pathlib

from PIL import Image

ROOT = pathlib.Path(__file__).resolve().parent.parent
SOURCE = ROOT / "assets" / "margenheld-icon.png"
TARGET = ROOT / "pwa" / "icons"
BACKGROUND = (0x1A, 0x1A, 0x2E, 255)          # --bg der PWA und BG des Desktop-Themes


def _square(image: Image.Image, size: int) -> Image.Image:
    """Das Motiv, auf `size` × `size` skaliert (Seitenverhältnis bleibt, transparent aufgefüllt)."""
    ratio = min(size / image.width, size / image.height)
    scaled = image.resize((round(image.width * ratio), round(image.height * ratio)), Image.LANCZOS)
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    canvas.paste(scaled, ((size - scaled.width) // 2, (size - scaled.height) // 2), scaled)
    return canvas


def main() -> None:
    source = Image.open(SOURCE).convert("RGBA")
    TARGET.mkdir(parents=True, exist_ok=True)
    for size in (192, 512):
        _square(source, size).save(TARGET / f"icon-{size}.png", optimize=True)
    maskable = Image.new("RGBA", (512, 512), BACKGROUND)
    motif = _square(source, round(512 * 0.7))
    maskable.paste(motif, ((512 - motif.width) // 2, (512 - motif.height) // 2), motif)
    maskable.save(TARGET / "icon-maskable-512.png", optimize=True)
    print(f"Icons nach {TARGET} geschrieben.")


if __name__ == "__main__":
    main()
```

Run: `python3 scripts/pwa_icons.py`
Expected: `Icons nach …/pwa/icons geschrieben.` und drei PNGs.

Create `pwa/manifest.webmanifest`:

```json
{
  "name": "Zeiterfassung",
  "short_name": "Zeiterfassung",
  "description": "Arbeitszeiten unterwegs erfassen und mit dem Desktop abgleichen.",
  "lang": "de",
  "start_url": "./",
  "scope": "./",
  "display": "standalone",
  "orientation": "portrait",
  "background_color": "#1a1a2e",
  "theme_color": "#1a1a2e",
  "icons": [
    {"src": "icons/icon-192.png", "sizes": "192x192", "type": "image/png", "purpose": "any"},
    {"src": "icons/icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any"},
    {"src": "icons/icon-maskable-512.png", "sizes": "512x512", "type": "image/png", "purpose": "maskable"}
  ]
}
```

Create `pwa/sw-core.js`:

```js
// pwa/sw-core.js
// Kern des Service Workers: Cache-Name, Vorab-Cache-Liste und die Entscheidung, welche
// Anfragen er überhaupt anfasst. Ohne Browser-API, damit er in Node getestet werden kann
// (`test/shell.test.js`); `sw.js` ist nur die dünne Hülle mit den Ereignissen.
//
// `BUILD` ist im Repository ein Platzhalter. Der Pages-Workflow setzt beim Veröffentlichen die
// Commit-Kennung ein: jeder Deploy bekommt damit einen eigenen Cache und löst ein Update aus.
// (Der Browser vergleicht `sw.js` samt importierter Module Byte für Byte.)
export const BUILD = '__BUILD__';
export const CACHE_PREFIX = 'zeiterfassung-pwa-';
export const CACHE_NAME = `${CACHE_PREFIX}${BUILD}`;

// Genau die Laufzeitdateien (ein Test hält Liste und Dateisystem zusammen). Relativ, weil die
// Seite unter /Zeiterfassung/ liegt.
export const PRECACHE = [
  './',
  './index.html',
  './app.css',
  './manifest.webmanifest',
  './app.js',
  './views.js',
  './dom.js',
  './scanner.js',
  './view-model.js',
  './messages.js',
  './sync-policy.js',
  './minutes.js',
  './pairing.js',
  './store.js',
  './db.js',
  './sync.js',
  './sw-core.js',
  './icons/icon-192.png',
  './icons/icon-512.png',
  './icons/icon-maskable-512.png',
];

/** Nur eigene, vorab gecachte GET-Anfragen. Alles andere — vor allem die Anfragen an den
 *  Desktop (`http://<LAN-IP>`) — läuft am Service Worker vorbei: API-Antworten werden nie
 *  gecacht. */
export function shouldHandle(method, url, selfUrl) {
  if (method !== 'GET') return false;
  let target;
  let self;
  try {
    target = new URL(url);
    self = new URL(selfUrl);
  } catch {
    return false;                              // kaputte URL: nicht anfassen
  }
  if (target.origin !== self.origin) return false;
  const base = new URL('./', self);
  return PRECACHE.some((entry) => new URL(entry, base).pathname === target.pathname);
}
```

Create `pwa/sw.js`:

```js
// pwa/sw.js
// Service Worker: legt die App-Dateien in einen versionierten Cache und liefert sie offline aus.
// Die Entscheidungen stehen in `sw-core.js` (getestet). Ein neuer Service Worker wartet, bis die
// Seite „Neu laden“ bestätigt (Nachricht `SKIP_WAITING`) — nie mitten in einer Eingabe.
import { CACHE_NAME, CACHE_PREFIX, PRECACHE, shouldHandle } from './sw-core.js';

self.addEventListener('install', (event) => {
  event.waitUntil(caches.open(CACHE_NAME).then((cache) => cache.addAll(PRECACHE)));
});

self.addEventListener('activate', (event) => {
  event.waitUntil((async () => {
    for (const key of await caches.keys()) {
      if (key.startsWith(CACHE_PREFIX) && key !== CACHE_NAME) await caches.delete(key);
    }
    await self.clients.claim();
  })());
});

self.addEventListener('message', (event) => {
  if (event.data && event.data.type === 'SKIP_WAITING') self.skipWaiting();
});

self.addEventListener('fetch', (event) => {
  const { request } = event;
  if (!shouldHandle(request.method, request.url, self.location.href)) return;
  event.respondWith((async () => {
    const cache = await caches.open(CACHE_NAME);
    const hit = await cache.match(request, { ignoreSearch: true });
    if (hit) return hit;
    if (request.mode === 'navigate') {
      const shell = await cache.match('./index.html');
      if (shell) return shell;
    }
    return fetch(request);
  })());
});
```

Create `pwa/index.html`:

```html
<!doctype html>
<html lang="de">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
  <meta name="theme-color" content="#1a1a2e">
  <meta name="color-scheme" content="dark">
  <title>Zeiterfassung</title>
  <link rel="manifest" href="manifest.webmanifest">
  <link rel="icon" type="image/png" sizes="192x192" href="icons/icon-192.png">
  <link rel="apple-touch-icon" href="icons/icon-192.png">
  <link rel="stylesheet" href="app.css">
</head>
<body>
  <div id="app"></div>
  <noscript>Diese Seite braucht JavaScript.</noscript>
  <script type="module" src="app.js"></script>
</body>
</html>
```

Create `pwa/app.css`:

```css
/* pwa/app.css — Dark-Theme wie am Desktop (src/theme/palette.py), mobil zuerst. */
:root {
  --bg: #1a1a2e;
  --cell: #16213e;
  --cell-hover: #1e2d52;
  --weekend: #0f3460;
  --entry: #1a3a5c;
  --accent: #e94560;
  --accent-hover: #c73550;
  --text: #e0e0e0;
  --muted: #8a8a9a;
  --ok: #4ade80;
  --warn: #fbbf24;
  --gutter: 16px;
  --tap: 44px;
  color-scheme: dark;
}
* { box-sizing: border-box; }
html { -webkit-text-size-adjust: 100%; }
body {
  margin: 0; background: var(--bg); color: var(--text);
  font: 16px/1.4 system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
  padding-bottom: env(safe-area-inset-bottom);
}
#app { min-height: 100vh; display: flex; flex-direction: column; }
main { flex: 1; padding: var(--gutter); padding-bottom: calc(var(--gutter) + 72px); max-width: 640px; width: 100%; margin: 0 auto; }
h1, h2 { font-size: 1.15rem; margin: 0 0 8px; }
p { margin: 0 0 12px; }
.muted { color: var(--muted); }

button, input, select, textarea { font: inherit; color: inherit; }
button {
  min-height: var(--tap); padding: 0 16px; border: 0; border-radius: 8px;
  background: var(--cell); color: var(--text); cursor: pointer;
}
button:hover { background: var(--cell-hover); }
button.primary { background: var(--accent); color: #fff; font-weight: 600; }
button.primary:hover { background: var(--accent-hover); }
button.link { background: none; color: var(--accent); min-height: var(--tap); padding: 0 8px; text-decoration: underline; }
button:disabled { opacity: .5; cursor: default; }
:focus-visible { outline: 2px solid var(--warn); outline-offset: 2px; }

label { display: block; margin: 0 0 4px; font-size: .9rem; color: var(--muted); }
input, select {
  width: 100%; min-height: var(--tap); padding: 0 10px; border: 1px solid #2a3a5a; border-radius: 8px;
  background: var(--cell); margin-bottom: 12px;
}
input[type="time"], input[type="number"] { min-width: 0; }
form .row { display: flex; gap: 8px; }
form .row > div { flex: 1; min-width: 0; }

.hint { padding: 10px 12px; border-radius: 8px; margin: 0 0 8px; background: var(--cell); border-left: 4px solid var(--muted); }
.hint.error { border-color: var(--accent); }
.hint.warn { border-color: var(--warn); }
.hint.info { border-color: #60a5fa; }
.hint .actions { margin-top: 6px; display: flex; gap: 8px; flex-wrap: wrap; }

.weekbar { display: flex; align-items: center; gap: 8px; margin-bottom: 12px; }
.weekbar .title { flex: 1; text-align: center; }
.weekbar .title strong { display: block; }
.weekbar button { min-width: var(--tap); }

.days { list-style: none; margin: 0; padding: 0; }
.day {
  display: grid; grid-template-columns: 48px 1fr auto; gap: 4px 8px; width: 100%; text-align: left;
  padding: 10px 12px; margin-bottom: 6px; border-radius: 8px; background: var(--cell); min-height: var(--tap);
}
.day.weekend { background: var(--weekend); }
.day.filled { background: var(--entry); }
.day.today { outline: 2px solid var(--accent); }
.day .wd { font-weight: 700; }
.day .date { color: var(--muted); font-size: .85rem; }
.day .slots { grid-column: 2; margin: 0; padding: 0; list-style: none; font-size: .95rem; }
.day .sum { grid-column: 3; grid-row: 1; font-weight: 700; align-self: start; }
.day .marks { grid-column: 3; grid-row: 2; justify-self: end; font-size: .85rem; }
.day .err { grid-column: 2 / 4; color: var(--accent); font-size: .9rem; }
.mark-dirty { color: var(--warn); }
.mark-conflict { color: var(--warn); font-weight: 700; }
.day.cleared .slots li { color: var(--muted); text-decoration: line-through; }
.day.future { opacity: .75; }
.total { display: flex; justify-content: space-between; padding: 8px 12px; font-weight: 700; }

.statusbar {
  position: fixed; left: 0; right: 0; bottom: 0; z-index: 5;
  padding: 8px var(--gutter) calc(8px + env(safe-area-inset-bottom));
  background: #101a30; border-top: 1px solid #2a3a5a; display: flex; align-items: center; gap: 12px;
}
.statusbar .text { flex: 1; font-size: .85rem; min-width: 0; }
.statusbar .online { color: var(--ok); } .statusbar .offline { color: var(--warn); }

dialog {
  width: min(100vw - 24px, 560px); max-height: 92vh; padding: var(--gutter); border: 1px solid #2a3a5a;
  border-radius: 12px; background: var(--bg); color: var(--text);
}
dialog::backdrop { background: rgba(0, 0, 0, .65); }
dialog .buttons { display: flex; gap: 8px; justify-content: flex-end; flex-wrap: wrap; margin-top: 12px; }
.slot { border: 1px solid #2a3a5a; border-radius: 8px; padding: 10px; margin-bottom: 10px; }
.slot .remove { float: right; }
.error-text { color: var(--accent); min-height: 1.4em; }
.version { background: var(--cell); border-radius: 8px; padding: 10px; margin-bottom: 8px; }
.version ul { margin: 4px 0 0; padding-left: 18px; }
video { width: 100%; border-radius: 8px; background: #000; }
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd pwa && node --test 2>&1 | grep -E "^not ok|^# (pass|fail)"` und `python3 -m pytest -q -p no:cacheprovider && ruff check .`
Expected: Node `# fail 0` — **mit Ausnahme** des Tests `every runtime file is precached…`, solange `views.js`, `dom.js`, `scanner.js`, `app.js` noch fehlen (sie stehen in `PRECACHE`, der Test verlangt, dass jeder Eintrag existiert). Lege dafür in diesem Task **leere Platzhalterdateien nicht an**, sondern führe Task 3 und 4 zusammen aus (Commit nach Task 4), oder committe Task 3 mit dem roten Test und markiere das im Ledger — empfohlen: Task 4 vor dem Commit abschließen und beides in zwei Commits aufteilen (`git add -p`).

- [ ] **Step 5: Commit** (nach Task 4, wenn die Dateien existieren)

~~~bash
git add pwa/index.html pwa/app.css pwa/manifest.webmanifest pwa/sw-core.js pwa/sw.js pwa/icons scripts/pwa_icons.py pwa/test/shell.test.js
git commit -m "feat(pwa): Hülle — index.html, Theme, Manifest, Icons, Service Worker (#221)

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
~~~

---

### Task 4: DOM-Schicht — `dom.js`, `views.js`, `scanner.js`, `app.js`

**Files:**
- Create: `pwa/dom.js`, `pwa/views.js`, `pwa/scanner.js`, `pwa/app.js`

**Interfaces:** Consumes: alle Module aus PR 6 und Tasks 1 bis 3. Produces: die lauffähige App. Die DOM-Dateien haben keine Node-Tests (entschiedene Scope-Grenze für UI); getestet werden sie in Task 5 im echten Browser, und das „kein `innerHTML`" sichert der Test aus Task 3.

- [ ] **Step 1: Write the DOM helpers**

Create `pwa/dom.js`:

```js
// pwa/dom.js
// Der einzige Weg, Elemente zu bauen: `createElement` und Textknoten. Kein `innerHTML` — Namen,
// Kategorien und Fehlertexte kommen vom Desktop beziehungsweise aus einem QR-Code (Fremddaten)
// und erscheinen deshalb immer als Text.

/** @param {string} tag @param {Record<string, unknown>} [attrs] @param {...unknown} children */
export function h(tag, attrs = {}, ...children) {
  const element = document.createElement(tag);
  for (const [name, value] of Object.entries(attrs)) {
    if (value === null || value === undefined || value === false) continue;
    if (name === 'class') element.className = String(value);
    else if (name.startsWith('on') && typeof value === 'function') element.addEventListener(name.slice(2), value);
    else if (value === true) element.setAttribute(name, '');
    else element.setAttribute(name, String(value));
  }
  for (const child of children.flat()) {
    if (child === null || child === undefined || child === false) continue;
    element.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return element;
}

export function clear(element) {
  while (element.firstChild) element.firstChild.remove();
}
```

- [ ] **Step 2: Write the views**

Create `pwa/views.js`:

```js
// pwa/views.js
// Dünne DOM-Schicht: macht aus den Modellen von `view-model.js` Elemente. Keine Logik, die
// sich ohne Browser testen ließe — die steckt in `view-model.js`. Jede Funktion bekommt ihre
// Handler als Parameter; nichts hier kennt den Store oder das Netz.
import { h } from './dom.js';
import { MAX_CATEGORY_LENGTH } from './minutes.js';

const button = (label, onclick, className = '', extra = {}) =>
  h('button', { type: 'button', class: className, onclick, ...extra }, label);

// --- Hinweise und Statuszeile -----------------------------------------------------------------------

const ACTION_LABELS = { pair: 'Neu koppeln', rescan: 'QR neu scannen', retry: 'Erneut versuchen', reload: 'Neu laden', conflicts: 'Anzeigen' };

export function hintsView(hints, handlers) {
  return h('div', { class: 'hints' }, hints.map((hint) => h('div', { class: `hint ${hint.kind}`, role: hint.kind === 'error' ? 'alert' : 'status' },
    h('div', {}, hint.text),
    hint.action && h('div', { class: 'actions' },
      button(ACTION_LABELS[hint.action], () => handlers[hint.action](), 'link')))));
}

export function statusBar(status, handlers) {
  return h('footer', { class: 'statusbar' },
    h('div', { class: 'text', 'aria-live': 'polite' },
      h('div', { class: status.online ? 'online' : 'offline' }, status.connection),
      status.pendingText && h('div', {}, status.pendingText),
      h('div', { class: 'muted' }, status.lastText)),
    button('Verbindung', handlers.connection),
    button('Jetzt abgleichen', handlers.sync, 'primary', { disabled: !status.canSync }));
}

// --- Koppeln ----------------------------------------------------------------------------------------

export function pairView({ address, code, deviceName, busy, canScan, canCancel }, handlers) {
  const addressInput = h('input', { id: 'pair-address', name: 'address', value: address, inputmode: 'decimal',
    autocomplete: 'off', placeholder: '192.168.178.20:17654', required: true });
  const codeInput = h('input', { id: 'pair-code', name: 'code', value: code, autocapitalize: 'characters',
    autocomplete: 'off', spellcheck: 'false', placeholder: 'K7M2-9QXA', required: true });
  const nameInput = h('input', { id: 'pair-name', name: 'name', value: deviceName, maxlength: 60, autocomplete: 'off' });
  return h('main', {},
    h('h1', {}, 'Mit dem Desktop koppeln'),
    h('p', { class: 'muted' }, 'Am Desktop: Einstellungen → Mobil → „Gerät koppeln …“. Dann den QR-Code scannen oder Adresse und Code eintippen.'),
    canScan && button('QR-Code scannen', handlers.scan, 'primary'),
    h('form', { onsubmit: (event) => { event.preventDefault(); handlers.submit({ address: addressInput.value, code: codeInput.value, deviceName: nameInput.value }); } },
      h('label', { for: 'pair-address' }, 'Adresse des Desktops'), addressInput,
      h('label', { for: 'pair-code' }, 'Code'), codeInput,
      h('label', { for: 'pair-name' }, 'Name dieses Handys'), nameInput,
      h('div', { class: 'error-text', role: 'alert', id: 'pair-error' }),
      h('div', { class: 'buttons' },
        canCancel && button('Abbrechen', handlers.cancel),
        h('button', { type: 'submit', class: 'primary', disabled: busy }, busy ? 'Koppele …' : 'Koppeln'))));
}

export function setPairError(text) {
  const element = document.getElementById('pair-error');
  if (element) element.textContent = text;
}

// --- Woche ---------------------------------------------------------------------------------------------

function dayRow(day, handlers) {
  const classes = ['day', day.state, day.isWeekend && 'weekend', day.isToday && 'today', day.beyondWindow && 'future'];
  return h('li', {}, h('button', { type: 'button', class: classes.filter(Boolean).join(' '),
    'aria-label': `${day.weekday} ${day.label}${day.minutesLabel ? `, ${day.minutesLabel} Stunden` : ''}`,
    onclick: () => handlers.openDay(day.date) },
    h('span', {}, h('div', { class: 'wd' }, day.weekday), h('div', { class: 'date' }, day.label.slice(0, 6))),
    h('ul', { class: 'slots' }, day.state === 'cleared' ? h('li', {}, 'geleert') : day.slots.map((text) => h('li', {}, text))),
    h('span', { class: 'sum' }, day.minutesLabel),
    h('span', { class: 'marks' },
      day.dirty && h('span', { class: 'mark-dirty', title: 'nicht übertragen' }, '● '),
      day.conflict && h('span', { class: 'mark-conflict', title: 'Konflikt' }, '⚠')),
    day.error && h('span', { class: 'err' }, day.error)));
}

export function weekView(model, handlers) {
  return h('main', {},
    h('div', { class: 'weekbar' },
      button('‹', handlers.previous, '', { 'aria-label': 'Vorherige Woche' }),
      h('div', { class: 'title' }, h('strong', {}, model.title), h('span', { class: 'muted' }, model.range)),
      button('›', handlers.next, '', { 'aria-label': 'Nächste Woche' })),
    !model.isCurrent && button('Zur aktuellen Woche', handlers.today, 'link'),
    h('ul', { class: 'days' }, model.days.map((day) => dayRow(day, handlers))),
    h('div', { class: 'total' }, h('span', {}, 'Woche gesamt'), h('span', {}, model.totalLabel)));
}

// --- Dialoge -----------------------------------------------------------------------------------------------

function openDialog(dialog) {
  document.body.append(dialog);
  dialog.addEventListener('close', () => dialog.remove());
  dialog.showModal();
  return dialog;
}

/** Tag bearbeiten. Der Dialog hält seine Zeilen selbst (Eingaben gehen bei Hintergrund-Renders
 *  nicht verloren). `handlers.save(rows)` liefert `null` bei Erfolg oder eine Fehlermeldung. */
export function editorDialog({ title, rows, categories, error, beyondWindow, canClear, validate }, handlers) {
  const list = h('div', {});
  const message = h('div', { class: 'error-text', role: 'alert' }, error ?? '');
  const datalist = h('datalist', { id: 'categories' }, categories.map((name) => h('option', { value: name })));
  const save = h('button', { type: 'submit', class: 'primary' }, 'Speichern');
  const state = rows.map((row) => ({ ...row }));
  const dialog = h('dialog', { 'aria-labelledby': 'editor-title' });

  const refresh = () => {
    const check = validate(state);
    save.disabled = !check.ok;
    if (!error || check.ok) message.textContent = check.ok ? '' : check.message;
  };
  const field = (index, key, label, attrs) => {
    const id = `slot-${index}-${key}`;
    const input = h('input', { id, value: state[index][key], ...attrs,
      oninput: () => { state[index][key] = input.value; refresh(); } });
    return h('div', {}, h('label', { for: id }, label), input);
  };
  const build = () => {
    list.replaceChildren(...state.map((_, index) => h('fieldset', { class: 'slot' },
      state.length > 1 && button('×', () => { state.splice(index, 1); build(); refresh(); }, 'remove', { 'aria-label': 'Slot entfernen' }),
      h('div', { class: 'row' },
        field(index, 'start', 'von', { type: 'time', step: 60 }),
        field(index, 'end', 'bis', { type: 'time', step: 60 })),
      h('div', { class: 'row' },
        field(index, 'pause', 'Pause (Min)', { type: 'number', inputmode: 'numeric', min: 0, step: 1 }),
        field(index, 'kategorie', 'Kategorie', { type: 'text', list: 'categories', maxlength: MAX_CATEGORY_LENGTH, autocomplete: 'off' })))));
  };
  build();
  refresh();

  dialog.append(
    h('form', { method: 'dialog', onsubmit: async (event) => {
      event.preventDefault();
      const failure = await handlers.save(state);
      if (failure) message.textContent = failure; else dialog.close();
    } },
      h('h2', { id: 'editor-title' }, title),
      beyondWindow && h('p', { class: 'hint warn' }, 'Dieser Tag liegt nach morgen: am Desktop gespeichert, nach dem nächsten Abgleich aber nicht mehr hier sichtbar.'),
      list, datalist,
      button('+ Slot', () => { state.push({ start: state.at(-1)?.end ?? '', end: '', pause: '0', kategorie: state.at(-1)?.kategorie ?? '' }); build(); refresh(); }),
      message,
      h('div', { class: 'buttons' },
        canClear && button('Tag leeren', () => handlers.clear(dialog), 'link'),
        button('Abbrechen', () => dialog.close()),
        save)));
  return openDialog(dialog);
}

export function confirmDialog({ title, text, confirmLabel }, onConfirm) {
  const dialog = h('dialog', { 'aria-labelledby': 'confirm-title' },
    h('h2', { id: 'confirm-title' }, title), h('p', {}, text),
    h('div', { class: 'buttons' },
      button('Abbrechen', () => dialog.close()),
      button(confirmLabel, () => { dialog.close(); onConfirm(); }, 'primary')));
  return openDialog(dialog);
}

export function conflictsDialog(conflicts, handlers) {
  const dialog = h('dialog', { 'aria-labelledby': 'conflicts-title' },
    h('h2', { id: 'conflicts-title' }, 'Konflikte'),
    h('p', { class: 'muted' }, 'Beide Fassungen sind gespeichert. Gelöst wird am Desktop (Einstellungen → Google → „Konflikte ansehen“ oder Klick auf den Tag).'),
    conflicts.length === 0 && h('p', {}, 'Keine offenen Konflikte.'),
    conflicts.map((conflict) => h('section', {},
      h('h2', {}, conflict.dateLabel),
      conflict.versions.map((version) => h('div', { class: 'version' },
        h('strong', {}, version.who), h('span', { class: 'muted' }, ` · ${version.when}`),
        version.slots.length === 0 ? h('p', {}, 'gelöscht') : h('ul', {}, version.slots.map((text) => h('li', {}, text))),
        h('div', {}, `Summe ${version.minutesLabel}`))),
      button('Zu diesem Tag', () => { dialog.close(); handlers.openDay(conflict.date); }, 'link'))),
    h('div', { class: 'buttons' }, button('Schließen', () => dialog.close())));
  return openDialog(dialog);
}

export function connectionDialog({ desktopName, address, build, persistent, tokenUntil }, handlers) {
  const dialog = h('dialog', { 'aria-labelledby': 'connection-title' },
    h('h2', { id: 'connection-title' }, 'Verbindung'),
    h('dl', {},
      h('dt', { class: 'muted' }, 'Desktop'), h('dd', {}, desktopName || '—'),
      h('dt', { class: 'muted' }, 'Adresse'), h('dd', {}, address || '—'),
      h('dt', { class: 'muted' }, 'Kopplung gültig bis'), h('dd', {}, tokenUntil || '—'),
      h('dt', { class: 'muted' }, 'Dauerhafter Speicher'), h('dd', {}, persistent === null ? 'unbekannt' : persistent ? 'ja' : 'nein'),
      h('dt', { class: 'muted' }, 'Version'), h('dd', {}, build)),
    h('div', { class: 'buttons' },
      button('QR neu scannen / Neu koppeln', () => { dialog.close(); handlers.pair(); }),
      button('Schließen', () => dialog.close(), 'primary')));
  return openDialog(dialog);
}

export function scanDialog(onClose) {
  const video = h('video', { playsinline: true, muted: true });
  const message = h('p', { class: 'muted', role: 'status' }, 'Kamera wird gestartet …');
  const dialog = h('dialog', { 'aria-labelledby': 'scan-title' },
    h('h2', { id: 'scan-title' }, 'QR-Code scannen'), video, message,
    h('div', { class: 'buttons' }, button('Abbrechen', () => dialog.close())));
  dialog.addEventListener('close', onClose);
  openDialog(dialog);
  return { dialog, video, message };
}

export function fatalView(text) {
  return h('main', {}, h('h1', {}, 'Zeiterfassung'), h('p', { class: 'hint error', role: 'alert' }, text));
}
```

Create `pwa/scanner.js`:

```js
// pwa/scanner.js
// QR-Scan über die Kamera (`BarcodeDetector`, nur wo vorhanden — Chrome auf Android). Wo er fehlt,
// bleibt die Kamera-App des Handys: sie öffnet den Link, dessen Fragment `app.js` ausliest.
import { parseQrText } from './pairing.js';

export const canScan = () => 'BarcodeDetector' in globalThis && Boolean(navigator.mediaDevices?.getUserMedia);

/** Liest Bilder aus `video`, bis ein Koppel-Link erkannt wird oder `signal` abbricht.
 *  Löst mit `{host, port, code}` auf, wirft bei fehlender Kamera-Berechtigung. */
export async function scanForPairLink(video, signal, onStatus = () => {}) {
  const stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: 'environment' }, audio: false });
  try {
    video.srcObject = stream;
    await video.play();
    onStatus('Den QR-Code vom Desktop in das Bild halten.');
    const detector = new globalThis.BarcodeDetector({ formats: ['qr_code'] });
    while (!signal.aborted) {
      const codes = await detector.detect(video);
      for (const code of codes) {
        const link = parseQrText(code.rawValue);
        if (link) return link;
        onStatus('Das ist kein Koppel-Code dieser App.');
      }
      await new Promise((resolve) => setTimeout(resolve, 250));
    }
    return null;
  } finally {
    for (const track of stream.getTracks()) track.stop();
    video.srcObject = null;
  }
}
```

- [ ] **Step 2: Write the app**

Create `pwa/app.js`:

```js
// pwa/app.js
// Verdrahtung: Zustand der Oberfläche, Ereignisse, Abgleich-Auslöser, Service Worker. Die
// Entscheidungen stehen in den getesteten Modulen (`view-model.js`, `sync-policy.js`,
// `messages.js`); hier wird nur zusammengesteckt.
import { addDays, formatDateDe, localIsoDate, mondayOf } from './minutes.js';
import { deviceNameFromUserAgent, parseHostPort, parsePairFragment } from './pairing.js';
import { openDatabase, requestPersistentStorage } from './db.js';
import { Store } from './store.js';
import { SyncClient, SyncError, clockSkewMs } from './sync.js';
import { shouldSync } from './sync-policy.js';
import {
  conflictsModel, editorRows, hintsModel, rowsToSlots, statusModel, validateRows, weekModel,
} from './view-model.js';
import { BUILD } from './sw-core.js';
import { clear } from './dom.js';
import {
  conflictsDialog, confirmDialog, connectionDialog, editorDialog, fatalView, hintsView, pairView,
  scanDialog, setPairError, statusBar, weekView,
} from './views.js';
import { canScan, scanForPairLink } from './scanner.js';
import { describeError } from './messages.js';

const SAVE_SYNC_DELAY_MS = 2000;

class App {
  constructor(root, store, client) {
    this.root = root;
    this.store = store;
    this.client = client;
    this.screen = 'week';
    this.anchor = localIsoDate(new Date());
    this.online = navigator.onLine !== false;
    this.syncing = false;
    this.lastError = null;
    this.lastAttemptAt = 0;
    this.skewMs = 0;
    this.persistent = null;
    this.updateReady = false;
    this.pairing = { address: '', code: '', busy: false };
    this.saveTimer = null;
  }

  get paired() {
    const meta = this.store.getMeta();
    return Boolean(meta.token && meta.address);
  }

  async start() {
    this.captureFragment();
    if (!this.paired) this.screen = 'pair';
    window.addEventListener('online', () => { this.online = true; this.trigger('online'); this.render(); });
    window.addEventListener('offline', () => { this.online = false; this.render(); });
    document.addEventListener('visibilitychange', () => { if (document.visibilityState === 'visible') this.trigger('visible'); });
    this.registerServiceWorker();
    this.render();
    this.persistent = await requestPersistentStorage();
    this.render();
    this.trigger('start');
  }

  // --- Koppeln über den Link -------------------------------------------------------------------

  captureFragment() {
    const link = parsePairFragment(location.hash);
    if (!link) return;
    this.pairing = { ...this.pairing, address: `${link.host}:${link.port}`, code: link.code };
    this.screen = 'pair';
    // Das Fragment trägt den Einmalcode: nicht in der Adresszeile oder im Verlauf stehen lassen.
    history.replaceState(null, '', location.pathname + location.search);
  }

  async submitPairing({ address, code, deviceName }) {
    const target = parseHostPort(address);
    if (!target) {
      setPairError('Die Adresse muss eine private IPv4-Adresse sein, zum Beispiel 192.168.178.20:17654.');
      return;
    }
    this.pairing = { address, code, busy: true };
    this.render();
    try {
      await this.client.pair({ host: target.host, port: target.port, code, deviceName: deviceName.trim() || 'Android-Handy' });
      await this.store.setMeta({ device_name: deviceName.trim() });
      this.pairing = { address: '', code: '', busy: false };
      this.lastError = null;
      this.screen = 'week';
      this.render();
      this.trigger('manual');
    } catch (error) {
      this.pairing = { address, code, busy: false };
      this.render();
      setPairError(describeError(error).text);
    }
  }

  async scanPairing() {
    const abort = new AbortController();
    const { video, message } = scanDialog(() => abort.abort());
    try {
      const link = await scanForPairLink(video, abort.signal, (text) => { message.textContent = text; });
      if (link) {
        document.querySelector('dialog[open]')?.close();
        this.pairing = { ...this.pairing, address: `${link.host}:${link.port}`, code: link.code };
        this.render();
      }
    } catch {
      message.textContent = 'Die Kamera ist nicht verfügbar oder nicht freigegeben. Bitte Adresse und Code eintippen oder die Kamera-App benutzen.';
    }
  }

  // --- Abgleich ----------------------------------------------------------------------------------

  trigger(name) {
    const allowed = shouldSync({
      trigger: name, paired: this.paired, syncing: this.syncing, online: this.online,
      now: Date.now(), lastAttemptAt: this.lastAttemptAt, lastError: this.lastError,
    });
    if (allowed) this.runSync();
  }

  scheduleSyncAfterSave() {
    clearTimeout(this.saveTimer);
    this.saveTimer = setTimeout(() => this.trigger('save'), SAVE_SYNC_DELAY_MS);
  }

  async runSync() {
    this.syncing = true;
    this.lastAttemptAt = Date.now();
    this.render();
    try {
      const result = await this.client.sync();
      this.lastError = null;
      if (!result.discarded) this.skewMs = clockSkewMs(this.store.getMeta().server_time, new Date());
    } catch (error) {
      this.lastError = error instanceof SyncError ? error
        : new SyncError({ kind: 'client_error', message: String(error?.message ?? error) });
    } finally {
      this.syncing = false;
      this.render();
    }
  }

  // --- Anzeige -----------------------------------------------------------------------------------

  conflictList() {
    return conflictsModel(this.store.getMeta().conflicts);
  }

  render() {
    clear(this.root);
    if (this.screen === 'pair') {
      this.root.append(pairView({
        address: this.pairing.address, code: this.pairing.code,
        deviceName: this.store.getMeta().device_name || deviceNameFromUserAgent(navigator.userAgent),
        busy: this.pairing.busy, canScan: canScan(), canCancel: this.paired,
      }, {
        submit: (values) => this.submitPairing(values),
        scan: () => this.scanPairing(),
        cancel: () => { this.screen = 'week'; this.render(); },
      }));
      return;
    }
    const meta = this.store.getMeta();
    const conflicts = this.conflictList();
    const model = weekModel({
      getDay: (date) => this.store.getDay(date), anchor: this.anchor, today: localIsoDate(new Date()),
      conflictDates: conflicts.map((conflict) => conflict.date),
    });
    const hints = hintsModel({
      lastError: this.lastError, excluded: meta.excluded, skewMs: this.skewMs, persistent: this.persistent,
      updateReady: this.updateReady, conflictCount: conflicts.length,
      errorDays: this.store.days().filter((date) => this.store.getDay(date).error).length,
    });
    const handlers = {
      pair: () => { this.screen = 'pair'; this.render(); },
      rescan: () => { this.screen = 'pair'; this.render(); },
      retry: () => this.trigger('manual'),
      reload: () => this.reloadForUpdate(),
      conflicts: () => conflictsDialog(conflicts, { openDay: (date) => this.openDay(date) }),
    };
    const main = weekView(model, {
      previous: () => { this.anchor = addDays(this.anchor, -7); this.render(); },
      next: () => { this.anchor = addDays(this.anchor, 7); this.render(); },
      today: () => { this.anchor = localIsoDate(new Date()); this.render(); },
      openDay: (date) => this.openDay(date),
    });
    main.prepend(hintsView(hints, handlers));
    this.root.append(main, statusBar(statusModel({
      paired: this.paired, online: this.online, syncing: this.syncing, pending: this.store.dirtyDates().length,
      lastSyncAt: meta.server_time,
    }), {
      sync: () => this.trigger('manual'),
      connection: () => this.openConnection(),
    }));
  }

  openConnection() {
    const meta = this.store.getMeta();
    connectionDialog({
      desktopName: meta.desktop_name,
      address: meta.address ? `${meta.address.host}:${meta.address.port}` : '',
      build: BUILD,
      persistent: this.persistent,
      tokenUntil: meta.token_expires_at ? formatDateDe(meta.token_expires_at.slice(0, 10)) : '',
    }, { pair: () => { this.screen = 'pair'; this.render(); } });
  }

  openDay(date) {
    const day = this.store.getDay(date);
    const meta = this.store.getMeta();
    const beyondWindow = date > addDays(localIsoDate(new Date()), 1);
    editorDialog({
      title: `${formatDateDe(date)}`,
      rows: editorRows(day),
      categories: meta.categories,
      error: day?.error ?? null,
      beyondWindow,
      canClear: Boolean(day && !day.deleted),
      validate: (rows) => validateRows(rows),
    }, {
      save: async (rows) => {
        try {
          await this.store.saveDay(date, rowsToSlots(rows));
        } catch (error) {
          return String(error?.message ?? error);
        }
        this.render();
        this.scheduleSyncAfterSave();
        return null;
      },
      clear: (dialog) => confirmDialog({
        title: 'Tag leeren?', text: `Alle Einträge vom ${formatDateDe(date)} werden gelöscht (beim nächsten Abgleich auch am Desktop).`,
        confirmLabel: 'Tag leeren',
      }, async () => {
        await this.store.clearDay(date);
        dialog.close();
        this.render();
        this.scheduleSyncAfterSave();
      }),
    });
  }

  // --- Service Worker ----------------------------------------------------------------------------

  async registerServiceWorker() {
    if (!('serviceWorker' in navigator)) return;
    try {
      const registration = await navigator.serviceWorker.register('./sw.js', { type: 'module' });
      const watch = (worker) => worker?.addEventListener('statechange', () => {
        if (worker.state === 'installed' && navigator.serviceWorker.controller) {
          this.updateReady = true;
          this.render();
        }
      });
      if (registration.waiting && navigator.serviceWorker.controller) { this.updateReady = true; this.render(); }
      watch(registration.installing);
      registration.addEventListener('updatefound', () => watch(registration.installing));
      navigator.serviceWorker.addEventListener('controllerchange', () => { if (this.reloading) location.reload(); });
    } catch {
      // Ohne Service Worker läuft die App online weiter; offline starten kann sie dann nicht.
      this.persistentSwFailed = true;
    }
  }

  async reloadForUpdate() {
    const registration = await navigator.serviceWorker.getRegistration();
    if (!registration?.waiting) { location.reload(); return; }
    this.reloading = true;
    registration.waiting.postMessage({ type: 'SKIP_WAITING' });
  }
}

async function main() {
  const root = document.getElementById('app');
  let store;
  try {
    store = new Store(await openDatabase());
    await store.load();
  } catch {
    root.append(fatalView('Der Speicher des Browsers ist nicht verfügbar (privates Fenster oder gesperrt?). Ohne ihn kann diese App keine Einträge sichern.'));
    return;
  }
  await new App(root, store, new SyncClient({ store })).start();
}

main();
```

- [ ] **Step 3: Run the static checks**

Run: `cd pwa && node --test 2>&1 | grep -E "^not ok|^# (pass|fail)"` und `for f in dom views scanner app; do node --check pwa/$f.js && echo "$f ok"; done`
Expected: `# fail 0` (jetzt auch der Vorab-Cache-Test, weil alle Dateien da sind), `node --check` meldet keine Syntaxfehler. (`app.js` kann in Node nicht laufen, es braucht ein DOM: `--check` prüft nur die Syntax.)

- [ ] **Step 4: Commit** (zwei Commits: erst Task 3 per `git add -p`/Dateiliste, dann dieser)

~~~bash
git add pwa/dom.js pwa/views.js pwa/scanner.js pwa/app.js
git commit -m "feat(pwa): Oberfläche — Koppeln, Woche, Editor, Konflikte, Verbindung (#221)

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
~~~

---

### Task 5: Dev-Server und Prüfung im echten Browser

**Files:**
- Create: `scripts/pwa_devserver.py`, `tests/test_pwa_devserver.py`
- Modify: `scripts/README.md` (falls dort die Skripte gelistet sind; sonst nur `CLAUDE.md` in Task 6)

**Interfaces:** Produces: `scripts/pwa_devserver.py` mit `--port` (Web, Standard 8099), `--api-port` (Handy-Instanz, Standard 17654), `--address` (Standard: erste LAN-Adresse, sonst `127.0.0.1`), `--data-dir`; druckt Web-Adresse, Koppel-Link und Code.

- [ ] **Step 1: Write the failing test**

Create `tests/test_pwa_devserver.py`:

```python
# tests/test_pwa_devserver.py
import importlib.util
import json
import pathlib
import urllib.error
import urllib.request

import pytest

SCRIPT = pathlib.Path(__file__).resolve().parent.parent / "scripts" / "pwa_devserver.py"


@pytest.fixture(scope="module")
def devserver():
    spec = importlib.util.spec_from_file_location("pwa_devserver", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def get(url):
    with urllib.request.urlopen(url, timeout=5) as response:
        return response.status, response.headers, response.read()


def test_the_static_server_serves_the_pwa_with_module_friendly_types(devserver, tmp_path):
    with devserver.running(tmp_path, web_port=0, api_port=0, address="127.0.0.1") as dev:
        status, headers, body = get(f"http://127.0.0.1:{dev.web_port}/index.html")
        assert status == 200 and b'<div id="app">' in body
        assert get(f"http://127.0.0.1:{dev.web_port}/app.js")[1]["Content-Type"].startswith("text/javascript")
        assert "manifest+json" in get(f"http://127.0.0.1:{dev.web_port}/manifest.webmanifest")[1]["Content-Type"]
        assert headers["Cache-Control"] == "no-store"


def test_the_static_server_does_not_leak_outside_the_pwa_folder(devserver, tmp_path):
    with devserver.running(tmp_path, web_port=0, api_port=0, address="127.0.0.1") as dev:
        for path in ("/../src/main.py", "/%2e%2e/src/main.py", "/test/../../CLAUDE.md"):
            with pytest.raises(urllib.error.HTTPError):
                get(f"http://127.0.0.1:{dev.web_port}{path}")


def test_the_phone_server_accepts_exactly_the_dev_origin(devserver, tmp_path):
    with devserver.running(tmp_path, web_port=0, api_port=0, address="127.0.0.1") as dev:
        origin = f"http://localhost:{dev.web_port}"
        request = urllib.request.Request(
            f"http://127.0.0.1:{dev.api_port}/v1/sync", method="OPTIONS",
            headers={"Origin": origin, "Access-Control-Request-Method": "POST"})
        with urllib.request.urlopen(request, timeout=5) as response:
            assert response.status == 204
            assert response.headers["Access-Control-Allow-Origin"] == origin
        bad = urllib.request.Request(
            f"http://127.0.0.1:{dev.api_port}/v1/sync", method="OPTIONS",
            headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "POST"})
        with pytest.raises(urllib.error.HTTPError) as excinfo:
            urllib.request.urlopen(bad, timeout=5)
        assert excinfo.value.code == 403


def test_a_pair_code_is_available_and_the_link_points_at_the_dev_site(devserver, tmp_path):
    with devserver.running(tmp_path, web_port=0, api_port=0, address="127.0.0.1") as dev:
        code = dev.new_code()
        link = dev.pair_link(code)
        assert link.startswith(f"http://localhost:{dev.web_port}/#pair=127.0.0.1:{dev.api_port}:")
        body = json.dumps({"protocol": 1, "code": code, "device_name": "Dev", "device_id": "dev-device-0001"}).encode()
        request = urllib.request.Request(
            f"http://127.0.0.1:{dev.api_port}/v1/pair", data=body, method="POST",
            headers={"Content-Type": "application/json", "Origin": f"http://localhost:{dev.web_port}"})
        with urllib.request.urlopen(request, timeout=5) as response:
            assert response.status == 200 and "token" in json.loads(response.read())
```

- [ ] **Step 2: Run to verify it fails**

Run: `python3 -m pytest tests/test_pwa_devserver.py -q -p no:cacheprovider -x`
Expected: FAIL: `FileNotFoundError` für `scripts/pwa_devserver.py` beim Laden des Moduls.

- [ ] **Step 3: Implement**

Create `scripts/pwa_devserver.py`:

```python
#!/usr/bin/env python3
"""Dev-Server für die Handy-PWA: die ECHTE Handy-Instanz plus `pwa/` statisch.

    python scripts/pwa_devserver.py                 # Web :8099, Handy-Server :17654
    python scripts/pwa_devserver.py --address 127.0.0.1

Startet den `MobileService` der App (gleiche Routen, gleiche Prüfungen, gleiche Sync-Logik) auf
einer temporären Datenablage und serviert `pwa/` unter `http://localhost:<port>/`. `localhost`
ist eine sichere Origin: der Service Worker läuft dort. Die erlaubte Origin des Handy-Servers
ist die Dev-Adresse (statt `https://xveyn.github.io`). Gedruckt werden die Adresse, ein Koppel-Link
mit frischem Code und der Ordner der Desktop-Daten (`zeiterfassung.json` zum Nachsehen).

Werkzeug zum Entwickeln und für Browser-Tests (auch Playwright); nicht Teil der App, nicht
gebündelt. Reine stdlib plus die App-Module.
"""
from __future__ import annotations

import argparse
import contextlib
import functools
import http.server
import pathlib
import sys
import tempfile
import threading
from collections.abc import Iterator

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
PWA = ROOT / "pwa"

from src import mobile_routes, netinfo  # noqa: E402
from src.conflicts_store import ConflictsStore  # noqa: E402
from src.mobile_service import STATE_RUNNING, MobileService  # noqa: E402
from src.mobile_store import MobileStore  # noqa: E402
from src.mobile_pairing import PairingSession  # noqa: E402
from src.settings import Settings  # noqa: E402
from src.storage import Storage  # noqa: E402


class _Handler(http.server.SimpleHTTPRequestHandler):
    extensions_map = {**http.server.SimpleHTTPRequestHandler.extensions_map,
                      ".webmanifest": "application/manifest+json", ".js": "text/javascript",
                      ".mjs": "text/javascript", ".json": "application/json", ".png": "image/png"}

    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-store")            # Dev: immer frisch
        super().end_headers()

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        return None


class Dev:
    def __init__(self, service: MobileService, web: http.server.ThreadingHTTPServer,
                 web_port: int, api_port: int, address: str, data_dir: pathlib.Path) -> None:
        self.service, self._web = service, web
        self.web_port, self.api_port, self.address, self.data_dir = web_port, api_port, address, data_dir

    def new_code(self) -> str:
        return self.service.pairing.open()

    def pair_link(self, code: str) -> str | None:
        return self.service.pair_link(code)


@contextlib.contextmanager
def running(data_dir: pathlib.Path, *, web_port: int, api_port: int, address: str) -> Iterator[Dev]:
    """Startet beide Server und räumt sie wieder ab. Port 0 = frei wählen."""
    handler = functools.partial(_Handler, directory=str(PWA))
    web = http.server.ThreadingHTTPServer(("127.0.0.1", web_port), handler)
    web_port = web.server_address[1]
    threading.Thread(target=web.serve_forever, daemon=True, name="pwa-web").start()
    origin = f"http://localhost:{web_port}"
    # Die Handy-Instanz liest beides beim Start; nur dieses Skript ändert es.
    mobile_routes.PWA_ORIGIN, mobile_routes.PWA_URL = origin, f"{origin}/"
    data_dir.mkdir(parents=True, exist_ok=True)
    settings = Settings(str(data_dir / "settings.json"))
    settings.device_id_for_sync = "DESKTOP-DEV"
    settings.set_many({"mobile_enabled": True, "mobile_port": api_port or 17654,
                       "mobile_address": address, "mobile_notice_accepted": True,
                       "categories": ["Projekt", "Intern", "Support"]})
    context = mobile_routes.MobileContext(
        pairing=PairingSession(), devices=MobileStore(str(data_dir / "mobile_devices.json")),
        devices_lock=threading.RLock(), storage=Storage(str(data_dir / "zeiterfassung.json"), device_id="DESKTOP-DEV"),
        settings=settings, conflicts_store=ConflictsStore(str(data_dir / "conflicts.json")),
        base=str(data_dir), desktop_name=lambda: "Desktop (Dev)")

    def run(fn, done=None):
        result = fn()
        if done is not None:
            done(result)

    service = MobileService(settings, context, run=run, lan_candidates=lambda: [address])
    try:
        if api_port == 0:
            api_port = _free_port(address)
            settings.set("mobile_port", api_port)
        service.apply()
        if service.status.state != STATE_RUNNING:
            raise RuntimeError(f"Handy-Server startet nicht: {service.status}")
        yield Dev(service, web, web_port, service.status.port, address, data_dir)
    finally:
        service.shutdown()
        web.shutdown()
        web.server_close()


def _free_port(address: str) -> int:
    import socket
    with socket.socket() as sock:
        sock.bind((address, 0))
        return int(sock.getsockname()[1])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--port", type=int, default=8099, help="Port der Web-Seite (Standard 8099)")
    parser.add_argument("--api-port", type=int, default=17654, help="Port der Handy-Instanz (Standard 17654)")
    parser.add_argument("--address", default=None,
                        help="LAN-Adresse der Handy-Instanz (Standard: erste gefundene, sonst 127.0.0.1)")
    parser.add_argument("--data-dir", type=pathlib.Path, default=None, help="Datenordner (Standard: temporär)")
    args = parser.parse_args(argv)
    address = args.address or (netinfo.lan_candidates() or ["127.0.0.1"])[0]
    data_dir = args.data_dir or pathlib.Path(tempfile.mkdtemp(prefix="zeiterfassung-pwa-dev-"))
    with running(data_dir, web_port=args.port, api_port=args.api_port, address=address) as dev:
        code = dev.new_code()
        print(f"PWA:           http://localhost:{dev.web_port}/")
        print(f"Handy-Server:  http://{address}:{dev.api_port}")
        print(f"Koppel-Link:   {dev.pair_link(code)}")
        print(f"Code:          {code}")
        print(f"Desktop-Daten: {dev.data_dir}")
        print("Strg+C beendet.")
        try:
            threading.Event().wait()
        except KeyboardInterrupt:
            print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run to verify it passes**

Run: `python3 -m pytest tests/test_pwa_devserver.py -q -p no:cacheprovider && ruff check . && python3 -m pytest -q -p no:cacheprovider`
Expected: PASS, `All checks passed!`. (`--directory` verhindert Pfad-Ausbrüche in `SimpleHTTPRequestHandler`; der Test hält das fest. Meldet `ruff` E402/Import-Reihenfolge in `scripts/`, übernimm das Muster der anderen Skripte mit Root-Bootstrap.)

- [ ] **Step 5: Verify in a real browser (Playwright)**

Lade die Werkzeuge: `ToolSearch("select:mcp__plugin_playwright_playwright__browser_navigate,mcp__plugin_playwright_playwright__browser_snapshot,mcp__plugin_playwright_playwright__browser_click,mcp__plugin_playwright_playwright__browser_type,mcp__plugin_playwright_playwright__browser_fill_form,mcp__plugin_playwright_playwright__browser_evaluate,mcp__plugin_playwright_playwright__browser_resize,mcp__plugin_playwright_playwright__browser_take_screenshot,mcp__plugin_playwright_playwright__browser_close,mcp__plugin_playwright_playwright__browser_console_messages,mcp__plugin_playwright_playwright__browser_wait_for")`. Starte den Dev-Server im Hintergrund (`python3 scripts/pwa_devserver.py --address 127.0.0.1 --data-dir $SCRATCH/dev-data > $SCRATCH/dev.log 2>&1 &`, Ausgabe lesen für den Code), Fenstergröße 360 × 740, und prüfe der Reihe nach (Ergebnisse ins Ledger, Fehler als Befund beheben):

1. `http://localhost:8099/#pair=127.0.0.1:17654:<CODE>` öffnen: Koppel-Formular mit vorbelegter Adresse und Code; die Adresszeile zeigt **kein** Fragment mehr (`location.hash === ''`). „Koppeln" → Wochenansicht, Statuszeile „Online", kein Fehler in der Konsole.
2. Einen Tag öffnen, einen Slot 08:00–12:00 mit Kategorie „Projekt" eintragen (Datalist zeigt „Intern", „Support"): „Speichern" ist erst bei gültiger Eingabe aktiv, Fehlermeldungen deutsch; nach dem Speichern erscheint der Tag mit Summe `4:00` und `●`; nach ~2 s verschwindet `●` und die Statuszeile zeigt die Abgleichzeit. `zeiterfassung.json` im Datenordner enthält den Tag mit der Geräte-ID des Handys.
3. Am Desktop-Stand (per Python-Skript im Datenordner mit `Storage`) einen anderen Tag anlegen, „Jetzt abgleichen": der Tag erscheint.
4. Konflikt: denselben Tag am „Desktop" (Storage) und im Handy verschieden ändern (Handy zuerst offline speichern, dann abgleichen): Hinweis „1 Konflikt: am Desktop lösen.", `⚠` an der Zeile, „Anzeigen" zeigt beide Fassungen nur lesend.
5. Offline: den Dev-Server-Handy-Teil beenden (oder `browser_evaluate` mit `navigator`-Override ist unnötig: Server stoppen) → Abgleich zeigt Hinweis „Der Desktop ist nicht erreichbar …" mit „QR neu scannen"; **alle lokalen Einträge bleiben sichtbar**; neu starten → nach „Jetzt abgleichen" verschwindet der Hinweis.
6. Widerruf: im Dev-Skript `service.revoke_all()` (oder Datensatz in `mobile_devices.json` auf `revoked`) → Hinweis „… widerrufen. Bitte neu koppeln"; nicht übertragene Tage bleiben; „Neu koppeln" mit neuem Code funktioniert, `device_id` bleibt gleich.
7. Fremddaten: Kategorie `<img src=x onerror=alert(1)>` am Desktop-Stand und Gerätename desgleichen: erscheint als Text, kein Dialog, kein Element.
8. Service Worker: nach dem ersten Laden `navigator.serviceWorker.controller` gesetzt; `caches.keys()` enthält `zeiterfassung-pwa-__BUILD__`; Dev-Server-Webteil stoppen und Seite neu laden → die App startet **offline** aus dem Cache; Anfragen an `127.0.0.1:17654` tauchen nie im Cache auf (`caches.open(...).then(c => c.keys())` enthält nur eigene Dateien).
9. Layout: bei 320 px Breite kein horizontales Scrollen (`document.documentElement.scrollWidth <= innerWidth`), Tippziele ≥ 44 px (`getBoundingClientRect().height` der Buttons).
10. Konsole: keine Fehler und keine Warnungen aus eigenem Code; kein Token/Code in `console_messages`.

Beende Dev-Server und Browser (`browser_close`, `pkill -f pwa_devserver`) und entferne ein vom Werkzeug angelegtes `.playwright-mcp/` aus dem Repo.

- [ ] **Step 6: Commit**

~~~bash
git add scripts/pwa_devserver.py tests/test_pwa_devserver.py
git commit -m "feat(pwa): Dev-Server mit echter Handy-Instanz für Browser-Tests (#221)

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
~~~

---

### Task 6: Pages-Workflow und Doku

**Files:**
- Create: `.github/workflows/pages.yml`, `tests/test_pwa_pages.py`
- Modify: `CLAUDE.md`, `docs/superpowers/specs/2026-10-08-mobile-pwa-design.md`

**Interfaces:** Produces: Workflow `pages.yml` (Trigger: Push auf `master` mit Änderungen unter `pwa/**` oder am Workflow selbst, plus `workflow_dispatch`).

- [ ] **Step 1: Write the failing test**

Create `tests/test_pwa_pages.py`:

```python
# tests/test_pwa_pages.py
"""Der Pages-Workflow und die Laufzeitdateien der PWA müssen zusammenpassen: ohne den
Platzhalter in `sw-core.js` oder ohne den `sed`-Aufruf bekäme jeder Deploy denselben Cache,
und neue Versionen kämen nie auf den Handys an."""
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
WORKFLOW = (ROOT / ".github" / "workflows" / "pages.yml").read_text(encoding="utf-8")


def test_the_build_placeholder_is_replaced_by_the_workflow():
    core = (ROOT / "pwa" / "sw-core.js").read_text(encoding="utf-8")
    assert core.count("__BUILD__") == 1
    assert "sed -i" in WORKFLOW and "__BUILD__" in WORKFLOW and "sw-core.js" in WORKFLOW
    assert re.search(r"grep -q .*sw-core\.js", WORKFLOW), "der Workflow muss prüfen, dass der Platzhalter ersetzt wurde"


def test_only_runtime_files_are_published():
    assert re.search(r"--exclude\s+'?test/'?", WORKFLOW)
    assert re.search(r"--exclude\s+'?package\.json'?", WORKFLOW)
    assert "path: _site" in WORKFLOW


def test_the_workflow_triggers_on_pwa_changes_and_manually_and_pushes_nothing():
    assert re.search(r"branches:\s*\[master\]", WORKFLOW)
    assert "'pwa/**'" in WORKFLOW
    assert "workflow_dispatch" in WORKFLOW
    assert "git push" not in WORKFLOW


def test_the_permissions_are_minimal():
    top = WORKFLOW.split("jobs:")[0]
    for line in ("contents: read", "pages: write", "id-token: write"):
        assert line in top, line
    assert "contents: write" not in WORKFLOW


def test_deploys_do_not_overlap():
    assert "concurrency:" in WORKFLOW and "group: pages" in WORKFLOW
    assert "cancel-in-progress: false" in WORKFLOW


def test_the_desktop_knows_the_address_the_workflow_publishes():
    # Die Seite erscheint unter https://<owner>.github.io/<repo>/; der Desktop trägt dieselbe
    # Origin als einzig erlaubte und denselben Pfad im Koppel-Link.
    from src import mobile_routes
    assert mobile_routes.PWA_ORIGIN == "https://xveyn.github.io"
    assert mobile_routes.PWA_URL == "https://xveyn.github.io/Zeiterfassung/"
```

- [ ] **Step 2: Run to verify it fails**

Run: `python3 -m pytest tests/test_pwa_pages.py -q -p no:cacheprovider -x`
Expected: FAIL: `FileNotFoundError` für `pages.yml`.

- [ ] **Step 3: Implement**

Prüfe die aktuellen Action-Versionen (gleiche Konvention wie `checkout@v7`: Major-Tag): `gh api repos/actions/upload-pages-artifact/releases/latest -q .tag_name` und `gh api repos/actions/deploy-pages/releases/latest -q .tag_name`; nimm deren Major-Tags (Stand der Planung: `upload-pages-artifact` v5, `deploy-pages` v5).

Create `.github/workflows/pages.yml`:

```yaml
name: PWA veröffentlichen

# Veröffentlicht den Ordner pwa/ (die Handy-PWA) nach GitHub Pages unter
# https://xveyn.github.io/Zeiterfassung/. Braucht eine Repo-Einstellung, die nicht im Code
# steht: Settings → Pages → Source: „GitHub Actions“ (Issue #266). Ohne sie scheitert
# deploy-pages. Der Workflow pusht NICHTS nach master.

on:
  push:
    branches: [master]
    paths:
      - 'pwa/**'
      - '.github/workflows/pages.yml'
  workflow_dispatch:

permissions:
  contents: read
  pages: write
  id-token: write

# Ein Deploy nach dem anderen; ein laufender wird nicht abgebrochen (halb veröffentlicht
# wäre schlimmer als verzögert).
concurrency:
  group: pages
  cancel-in-progress: false

jobs:
  deploy:
    runs-on: ubuntu-latest
    environment:
      name: github-pages
      url: ${{ steps.deployment.outputs.page_url }}
    steps:
      - uses: actions/checkout@v7
      - name: Laufzeitdateien zusammenstellen und Build-Kennung einsetzen
        run: |
          set -euo pipefail
          mkdir _site
          # Nur, was die App zur Laufzeit braucht: kein test/, kein package.json.
          rsync -a --exclude 'test/' --exclude 'package.json' --exclude 'node_modules/' pwa/ _site/
          # Jeder Deploy bekommt einen eigenen Cache (sw-core.js trägt den Platzhalter __BUILD__).
          sed -i "s/__BUILD__/${GITHUB_SHA::12}/" _site/sw-core.js
          grep -q "${GITHUB_SHA::12}" _site/sw-core.js
          if grep -q "__BUILD__" _site/sw-core.js; then echo "Platzhalter nicht ersetzt" >&2; exit 1; fi
          ls -R _site
      - uses: actions/upload-pages-artifact@v5
        with:
          path: _site
      - id: deployment
        uses: actions/deploy-pages@v5
```

In `CLAUDE.md` ersetze den Satz im `pwa/`-Eintrag, der mit „Tests: `cd pwa && node --test`" beginnt, so, dass die neuen Dateien und der Workflow genannt werden: füge **nach** dem Satz „Regeln, die nur in der PWA gelten: …" ein:

```markdown
Oberfläche und Auslieferung (PR 7): `index.html`, `app.css`, `manifest.webmanifest`, `icons/` (erzeugt von `scripts/pwa_icons.py` aus dem Markenbild), `sw.js` (Service Worker, ES-Modul) mit dem getesteten Kern `sw-core.js` (Cache-Name, Vorab-Cache-Liste `PRECACHE`, `shouldHandle`: nur eigene, vorab gecachte GET-Anfragen — **API-Antworten und Anfragen an den Desktop gehen nie durch den Service Worker**). Anzeige-Logik DOM-frei und getestet in `view-model.js`, `messages.js`, `sync-policy.js`; die DOM-Schicht `dom.js`/`views.js`/`scanner.js`/`app.js` baut Elemente **nur** über `createElement` und Textknoten (ein Test verbietet `innerHTML` & Co.; Namen, Kategorien und Fehlertexte sind Fremddaten). `PRECACHE` und die Dateien unter `pwa/` müssen übereinstimmen (Test: jede Laufzeitdatei außer `test/`, `package.json`, `sw.js`, `memory-adapter.js` ist gelistet). **Veröffentlichung:** `.github/workflows/pages.yml` (Push auf `master` mit Änderungen unter `pwa/**`, oder von Hand) kopiert die Laufzeitdateien nach `_site/` (ohne `test/` und `package.json`), ersetzt in `sw-core.js` den Platzhalter `__BUILD__` durch die Commit-Kennung (sonst liefe jeder Deploy mit demselben Cache, und Updates kämen nie an) und veröffentlicht per `deploy-pages`. **Braucht eine Repo-Einstellung, die nicht im Code steht:** Settings → Pages → Source „GitHub Actions“ (#266); ohne sie scheitert der Deploy, und der Workflow ist erst nach dem Merge nach `master` über „Run workflow“ erreichbar. Die Adresse `https://xveyn.github.io/Zeiterfassung/` steht als `PWA_ORIGIN`/`PWA_URL` in `src/mobile_routes.py` (einzig erlaubte Origin des Handy-Servers, Basis des Koppel-Links); zieht das Repo um, müssen beide mit. **Entwickeln und prüfen:** `python scripts/pwa_devserver.py` startet die echte Handy-Instanz (`MobileService`, Dev-Origin statt Pages) plus `pwa/` statisch auf `http://localhost:8099/` (sichere Origin, Service Worker läuft) und druckt einen Koppel-Link mit frischem Code — auch für Browser-Tests mit Playwright.
```

In `docs/superpowers/specs/2026-10-08-mobile-pwa-design.md` ergänze am Ende des Absatzes „**Umsetzung (PR 6):**" einen Absatz:

```markdown

**Umsetzung (PR 7):** Die Oberfläche baut Elemente ausschließlich über `createElement` und Textknoten (Namen, Kategorien und Fehlertexte sind Fremddaten); der Editor ist ein `<dialog>`, der seine Zeilen selbst hält. Der Service Worker (ES-Modul) fasst nur eigene, vorab gecachte GET-Anfragen an; Anfragen an den Desktop gehen an ihm vorbei. Ein neuer Service Worker wartet, bis die Seite „Neu laden" bestätigt. Die Build-Kennung (`sw-core.js`, Platzhalter `__BUILD__`) setzt der Pages-Workflow beim Veröffentlichen. Ein `#pair=`-Fragment füllt das Formular nur vor und wird danach aus der Adresszeile entfernt. Die Auslöser des automatischen Abgleichs regelt `sync-policy.js`: Wartezeit 5 s, nach Netzfehlern 30 s, nie mit totem Token; „Speichern" und „Jetzt abgleichen" kommen immer durch. Tage nach `heute + 1` bleiben nach dem Abgleich nicht auf dem Handy (Spec; #265); der Editor warnt davor.
```

- [ ] **Step 4: Run to verify**

Run: `python3 -m pytest tests/test_pwa_pages.py tests/test_claude_md_claims.py -q -p no:cacheprovider && python3 -m pytest -q -p no:cacheprovider && ruff check . && (cd pwa && node --test 2>&1 | grep -E "^# (pass|fail)")`
Expected: PASS, `All checks passed!`, Node `# fail 0`. Schlägt `test_claude_md_claims` an einer Workflow-Zählung (z. B. Zahl der Workflows oder Aktionen) an, ist das ein gewollter Hinweis: prüfe, welche Behauptung die neue Datei berührt, und passe die Aussage in der `CLAUDE.md` an (nicht den Test).

- [ ] **Step 5: Commit**

~~~bash
git add .github/workflows/pages.yml tests/test_pwa_pages.py CLAUDE.md docs/superpowers/specs/2026-10-08-mobile-pwa-design.md
git commit -m "feat(pwa): Pages-Workflow und Doku (#221)

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
~~~

---

## Mutationsprüfung (nach Task 6, vor dem Review)

Für die DOM-freien Teile wie bisher (Datei sichern, genau eine Ersetzung, `cd pwa && node --test` bzw. `pytest`, zurückkopieren; **nicht parallel zu anderen Arbeiten am Arbeitsbaum**). Jeder muss mindestens einen Test rot färben:

| Datei | Mutation | Erwartet rot |
|---|---|---|
| `messages.js` | `case 'repair'` liefert für alle Codes denselben Text | `the revoked, expired and replaced cases are told apart` |
| `messages.js` | `action: 'pair'` im `repair`-Zweig entfernen | `re-pairing is offered …` |
| `messages.js` | `case 'clock_skew'` entfernen | `every error kind … has its own text` |
| `sync-policy.js` | `if (lastError?.needsRepair) return false;` entfernen | `a dead token stops every automatic trigger` |
| `sync-policy.js` | `trigger === 'manual' \|\| trigger === 'save'` → nur `manual` | `save does not wait for the cooldown` |
| `sync-policy.js` | `AUTO_COOLDOWN_MS` auf 0 | `automatic triggers wait for the cooldown` |
| `sync-policy.js` | `trigger !== 'online' && !online` → `!online` | `… except the online event` |
| `pairing.js` | `parseQrText`: Fragment-Suche entfernen (ganzer Text) | `a scanned QR text is the full link` |
| `view-model.js` | `isCurrent` immer `true` | `a week that does not contain today is not current` |
| `view-model.js` | Wochensumme über Dezimalstunden | `sums are whole minutes …` |
| `view-model.js` | `VISIBLE_AHEAD_DAYS = 2` | `days after tomorrow are marked …` |
| `view-model.js` | `Math.abs(skewMs …) >= SKEW_WARN_MS` → `>` bei 120000-Test (Grenzwert) | `each situation gets its hint` (ggf. Grenzwert-Test ergänzen) |
| `view-model.js` | Reihenfolge: Fehlerhinweis ans Ende | `an error hint comes first` |
| `view-model.js` | `isBlank`: leere Zeilen nicht entfernen | `rows become wire slots; blank rows are dropped` |
| `view-model.js` | `conflictsModel` ohne `sort` | `conflicts are sorted by date …` |
| `sw-core.js` | `shouldHandle`: Origin-Prüfung entfernen | `requests to the desktop and anything foreign pass by` |
| `sw-core.js` | `shouldHandle`: `method !== 'GET'` entfernen | `only GET is handled` |
| `sw-core.js` | einen Eintrag aus `PRECACHE` löschen | `every runtime file is precached …` |
| `sw-core.js` | `BUILD` durch eine feste Zahl ersetzen | `the build id is a placeholder …` |
| `manifest.webmanifest` | `start_url` auf `/` | `the manifest is installable` |
| `index.html` | `href="manifest.webmanifest"` auf `/manifest.webmanifest` | `index.html wires …` |
| `pages.yml` | `sed`-Zeile entfernen | `tests/test_pwa_pages.py::test_the_build_placeholder_is_replaced_by_the_workflow` |
| `pages.yml` | `--exclude 'test/'` entfernen | `test_only_runtime_files_are_published` |
| `pages.yml` | `contents: write` ergänzen | `test_the_permissions_are_minimal` |
| `dom.js` | irgendwo `innerHTML` einführen | `no runtime script uses an HTML-injection API` |

Überlebt ein Mutant, ist das ein Testfehler: Test schärfen, gegen den Mutanten rot sehen, committen. Die DOM-Dateien (`views.js`, `app.js`, `scanner.js`) sind **nicht** mutationsgeprüft; sie decken die Browser-Prüfungen aus Task 5 ab.

## Finale

Nach Task 6: Review über den ganzen Branch mit einem frischen Reviewer auf dem leistungsfähigsten Modell (Review Focus und Rulings mitgeben; der Reviewer prüft die DOM-Dateien durch Lesen **und** durch Ausführen im Browser gegen `scripts/pwa_devserver.py` mit Playwright — Fremddaten im DOM, Service-Worker-Update, Offline-Start, Fokus im Dialog, 320 px Layout). Critical/Important in **einem** Fix-Durchlauf (je Fix ein Test, der zuerst rot war, wo der Code DOM-frei ist; sonst ein Browser-Nachweis), Minors ins Ledger und in ein Issue. Danach `finishing-a-development-branch`: PR gegen `master` (`Refs #221`, „PR 7 von 9" im Titel) **mit dem Hinweis, dass der Deploy erst nach der Pages-Einstellung (#266) läuft** und dass ein Pre-Release samt Android-Gerätetest vor dem Release nötig ist (Prüfliste #267). Der PR ändert **kein** Verhalten der Desktop-App.

**Danach PR 8/9 (Doku):** README (`*(ab --VERSION--)*`-Marker), `known-limitations`, Erweiterung der Prüfliste #248/#267.
