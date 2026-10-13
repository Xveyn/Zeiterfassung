# Reservierungen in der Handy-PWA (PR 3/3)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Die Handy-PWA kann Reservierungen (zukünftige Soll-Zeiten) wie der Desktop anlegen, ändern und löschen, gleicht sie mit dem Desktop ab und zeigt sie in Wochenansicht und Tages-Editor — nur wenn der Desktop sie anbietet.

**Architecture:** Reservierungen sind eine **eigene Sammlung** im lokalen Store (`reservations` in IndexedDB, `dirty_version`/`synced_version` wie bei den Ist-Zeiten), angewendet in derselben Transaktion wie die übrige Sync-Antwort. Die Logik ohne DOM steht in einem neuen Modul `reservations.js` (Sichtbarkeit, Slot-Normalisierung, Prüfung) und in `store.js`/`sync.js`/`view-model.js`; die DOM-Schicht (`views.js`, `app.js`) bekommt nur Verdrahtung. Feature-Erkennung: fehlt `reservations` in der Antwort, bleibt alles verborgen.

**Tech Stack:** reines JavaScript (ES-Module, kein Build), `node --test`; Python-Gegenprobe in `tests/test_mobile_contract.py`.

**Spec:** `docs/superpowers/specs/2026-10-12-reservierungen-ohne-google-design.md`, Abschnitt „PR 3: PWA". Der Desktop-Teil (Protokoll, Merge) ist mit #309 gemerged: Anfrage- und Antwortform stehen in `src/mobile_reservations.py` und `src/CLAUDE.md`.

## Global Constraints

- `PROTOCOL` bleibt `2`, alles additiv (`pwa/CLAUDE.md`, „Kompatibilität", Regeln 1–2): fehlt `reservations` in der Antwort, bleibt die Funktion verborgen (`parseReservations` liefert `null`).
- Form wie in der Anfrage des Desktops: `reservations: {ISO: {slots: [{start, end, kategorie}], modified_at, deleted}}`. **Kein** `device_id`, **kein** `pause`, nie `gcal_event_id`/`send_reminder_minutes` (der Desktop lehnt sie am Slot mit `422` ab).
- Antwort: nur aktive Tage von heute bis heute + 365, ohne Tombstones. Ein Tag, der fehlt, löscht ihn lokal **nur im Zukunftsfenster** (`today … today + 365`), nie außerhalb.
- Sichtbar nur für heute und Zukunft: `reservationBlockVisible(day, today) = day >= today`, Gleichlauf mit `reservation_block_visible` (`src/dialogs/entry_dialog.py`) über eine gemeinsame Fixture. In der Vergangenheit wird nichts gezeigt, auch keine vorhandene Reservierung.
- Löschen wie bei den Ist-Zeiten: „Tag leeren“ (Tombstone). Kein neuer Lösch-Weg.
- Reservierungen zählen **nicht** in die Wochensumme und nicht in `dayMinutes`.
- `PRECACHE` ergänzen (`shell.test.js` erzwingt Gleichstand mit den Dateien). **Keine** Version in `pwa/package.json` bumpen — das passiert im Release-PR (`pwa-version.yml`).
- Die DOM-Schicht baut Elemente nur über `h()`/`createElement` und Textknoten, nie `innerHTML` (ein Test verbietet es).
- Der Desktop lehnt bei einem schlechten Reservierungstag die **ganze** Anfrage ab (`422 invalid_entry`, Meldung beginnt `Reservierung <Datum>:`); die PWA markiert dann nur diesen Tag als abgelehnt (wie `markDayError` bei Ist-Zeiten), damit der nächste Abgleich durchgeht.
- Kommentare/Texte deutsch, Stil wie die vorhandenen Module. Branch `feat/reservierungen-pwa`, Commits `type(scope): …`.

## Review Focus

1. Reservierung offline angelegt, dann Abgleich: der Tag wird gesendet, kommt mit dem Empfangsstempel des Desktops zurück und ersetzt die lokale Fassung; **ein während der Anfrage erneut geänderter Tag bleibt lokal und dirty**. → Task 2
2. Der Desktop hat Reservierungen ausgeschaltet (Feld fehlt in der Antwort): lokale Reservierungen werden **nicht** gelöscht, Marker und Editor-Tab verschwinden, dirty Tage bleiben liegen und gehen beim Wiedereinschalten hinaus. → Task 2 und 3
3. Reservierung für gestern/vorgestern noch dirty (Offline-Nacht): der Desktop verwirft sie still, die PWA räumt sie nach dem Abgleich auf, statt sie ewig zu senden. → Task 2
4. Fremde Antwortdaten: kaputte Slots, Datum außerhalb, Zeitstempel ohne Format dürfen den Abgleich nicht kippen (Tag entfällt, kein Wurf). → Task 3
5. `422` für einen Reservierungstag blockiert die Ist-Zeiten nicht dauerhaft. → Task 3
6. Editor am Tag **nach** morgen: das Ablegen einer Reservierung legt **keine** Ist-Zeit an (die Ist-Zeilen sind mit Standardzeiten vorbelegt!). → Task 5

---

## Dateien

| Datei | Verantwortung |
|---|---|
| `pwa/reservations.js` (neu) | Sichtbarkeit, Normalisierung, Prüfung, Signatur — rein |
| `pwa/test/reservations.test.js` (neu) | Tests dazu |
| `pwa/test/fixtures/reservation-visibility-cases.json` (neu) | Gleichlauf-Fälle für JS und Python |
| `pwa/memory-adapter.js`, `pwa/db.js` | zusätzlicher Object Store `reservations` (IndexedDB `VERSION` 2) |
| `pwa/store.js` | Sammlung, Speichern/Leeren/Fehler, Snapshot, Anwenden |
| `pwa/sync.js` | `parseReservations`, Senden, Fehlerzuordnung |
| `pwa/view-model.js` | Wochenzeile, Editor-Zeilen der Reservierung |
| `pwa/views.js`, `pwa/app.js`, `pwa/app.css` | Tabs im Editor, Marker in der Woche, Verdrahtung |
| `pwa/sw-core.js` | `PRECACHE` |
| `pwa/test/fixtures/sync-request.json`, `sync-response.json` | Live-Beispiele um `reservations` erweitert |
| `tests/test_mobile_contract.py` | Gleichlauf-Test, Request-Beispiel liest der Desktop |
| `pwa/CLAUDE.md`, `src/CLAUDE.md`, `CLAUDE.md` | Doku |

---

### Task 1: `reservations.js` — rein, mit Gleichlauf zum Desktop

**Files:**
- Create: `pwa/reservations.js`, `pwa/test/reservations.test.js`, `pwa/test/fixtures/reservation-visibility-cases.json`
- Modify: `pwa/sw-core.js` (`PRECACHE`), `tests/test_mobile_contract.py`

**Interfaces:**
- Produces (`pwa/reservations.js`):
  - `RESERVATION_HORIZON_DAYS = 365`
  - `reservationBlockVisible(day: string, today: string): boolean` — `day >= today`
  - `normalizeReservationSlots(raw): Array<{start, end, kategorie}>` — nur diese drei Felder, `kategorie` getrimmt, fehlende → `''`; Nicht-Objekte bleiben unverändert stehen (die Prüfung lehnt sie ab)
  - `validateReservationSlots(slots): {ok: boolean, message?: string}` — wie `validateSlots`, aber ohne Pause (intern mit `pause: 0` geprüft)
  - `reservationSignature(slots): string` — reihenfolgeunabhängig

- [ ] **Step 1: Fixture und Failing tests**

`pwa/test/fixtures/reservation-visibility-cases.json`:

```json
[
  {"name": "yesterday is hidden", "day": "2026-10-12", "today": "2026-10-13", "visible": false},
  {"name": "today is shown", "day": "2026-10-13", "today": "2026-10-13", "visible": true},
  {"name": "tomorrow is shown", "day": "2026-10-14", "today": "2026-10-13", "visible": true},
  {"name": "a year ahead is shown", "day": "2027-10-13", "today": "2026-10-13", "visible": true},
  {"name": "across the month boundary", "day": "2026-11-01", "today": "2026-10-31", "visible": true},
  {"name": "across the year boundary, past", "day": "2026-12-31", "today": "2027-01-01", "visible": false}
]
```

`pwa/test/reservations.test.js`:

```js
// pwa/test/reservations.test.js
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

import {
  RESERVATION_HORIZON_DAYS, normalizeReservationSlots, reservationBlockVisible, reservationSignature,
  validateReservationSlots,
} from '../reservations.js';

const fixture = (name) => JSON.parse(readFileSync(new URL(`./fixtures/${name}`, import.meta.url)));

for (const c of fixture('reservation-visibility-cases.json')) {
  test(`block visibility: ${c.name}`, () => {
    assert.equal(reservationBlockVisible(c.day, c.today), c.visible);
  });
}

test('the horizon is a year', () => {
  assert.equal(RESERVATION_HORIZON_DAYS, 365);
});

test('normalising keeps exactly start, end and a trimmed category', () => {
  assert.deepEqual(
    normalizeReservationSlots([{ start: '09:00', end: '12:00', pause: 30, kategorie: ' Projekt ', gcal_event_id: 'x' }]),
    [{ start: '09:00', end: '12:00', kategorie: 'Projekt' }]);
  assert.deepEqual(normalizeReservationSlots([{ start: '09:00', end: '12:00' }]),
    [{ start: '09:00', end: '12:00', kategorie: '' }]);
  assert.deepEqual(normalizeReservationSlots('kaputt'), []);
});

test('validation reuses the slot rules without a pause', () => {
  assert.equal(validateReservationSlots([{ start: '09:00', end: '12:00', kategorie: '' }]).ok, true);
  assert.equal(validateReservationSlots([]).ok, false);
  assert.equal(validateReservationSlots([{ start: '12:00', end: '09:00', kategorie: '' }]).ok, false);
  assert.equal(validateReservationSlots([
    { start: '09:00', end: '12:00', kategorie: '' }, { start: '11:00', end: '13:00', kategorie: '' }]).ok, false);
});

test('the signature ignores the order of slots', () => {
  const a = { start: '09:00', end: '10:00', kategorie: 'A' };
  const b = { start: '11:00', end: '12:00', kategorie: 'B' };
  assert.equal(reservationSignature([a, b]), reservationSignature([b, a]));
  assert.notEqual(reservationSignature([a]), reservationSignature([b]));
});
```

Python-Gegenprobe, angehängt an `tests/test_mobile_contract.py` (Import `from src.dialogs.entry_dialog import reservation_block_visible` an die Importe der Datei, nach dem Muster der vorhandenen `resolve_slot_defaults`-Zeile):

```python
@pytest.mark.parametrize("case", load("reservation-visibility-cases.json"), ids=lambda case: case["name"])
def test_the_desktop_shows_the_reservation_block_like_the_phone_does(case):
    # Gleichlauf mit `pwa/reservations.js`: dieselben Fälle prüft der JS-Test.
    day = datetime.date.fromisoformat(case["day"])
    today = datetime.date.fromisoformat(case["today"])

    assert reservation_block_visible(day, today) is case["visible"]
```

- [ ] **Step 2: Run to verify failure**

Run: `cd pwa && node --test test/reservations.test.js`
Expected: FAIL (`Cannot find module '../reservations.js'`).

- [ ] **Step 3: Implementation**

```js
// pwa/reservations.js
// Reservierungen (zukünftige Soll-Zeiten) ohne DOM: wann der Block erscheint, wie Slots
// aussehen und geprüft werden. Gegenstück zu `reservation_block_visible` (Sichtbarkeit,
// Gleichlauf über `test/fixtures/reservation-visibility-cases.json`) und zu
// `src/mobile_reservations.py` (Form auf dem Draht).
import { normalizeSlots, validateSlots } from './minutes.js';

/** So weit voraus nimmt der Desktop Reservierungen an und liefert sie zurück. */
export const RESERVATION_HORIZON_DAYS = 365;

/** Der Reservierungs-Block erscheint nur an heutigen und zukünftigen Tagen. Auch eine alte
 *  Reservierung wird in der Vergangenheit nicht gezeigt (wie am Desktop). ISO-Daten vergleichen
 *  sich als Text. */
export function reservationBlockVisible(day, today) {
  return day >= today;
}

/** Nur `start`, `end`, `kategorie`: `pause` gibt es bei Reservierungen nicht, und der Desktop
 *  lehnt jedes weitere Feld am Slot ab. */
export function normalizeReservationSlots(raw) {
  return normalizeSlots(raw).map((slot) => (slot !== null && typeof slot === 'object'
    ? { start: slot.start, end: slot.end, kategorie: slot.kategorie }
    : slot));
}

export function validateReservationSlots(slots) {
  if (!Array.isArray(slots)) return validateSlots(slots);
  return validateSlots(slots.map((slot) => (slot !== null && typeof slot === 'object' ? { ...slot, pause: 0 } : slot)));
}

/** Reihenfolge der Slots ist keine Änderung. */
export function reservationSignature(slots) {
  return JSON.stringify(slots.map((s) => [s.start, s.end, s.kategorie]).sort());
}
```

`pwa/sw-core.js`: nach `'./minutes.js',` eintragen `'./reservations.js',`.

- [ ] **Step 4: Run to verify pass**

Run: `cd pwa && node --test && cd .. && pytest tests/test_mobile_contract.py -q`
Expected: PASS (inklusive `shell.test.js`).

- [ ] **Step 5: Commit**

```bash
git add pwa/reservations.js pwa/test/reservations.test.js pwa/test/fixtures/reservation-visibility-cases.json pwa/sw-core.js tests/test_mobile_contract.py
git commit -m "feat(pwa): Reservierungen — Sichtbarkeit und Slot-Regeln, Gleichlauf zum Desktop"
```

---

### Task 2: Speicher — Adapter und `Store`

**Files:**
- Modify: `pwa/memory-adapter.js`, `pwa/db.js`, `pwa/store.js`
- Test: `pwa/test/store.test.js`, `pwa/test/db.test.js`

**Interfaces:**
- Consumes: Task 1 (`normalizeReservationSlots`, `validateReservationSlots`, `reservationSignature`, `RESERVATION_HORIZON_DAYS`).
- Produces (`Store`):
  - Meta `reservations_enabled: false` (Default), gesetzt von `applyResponse`.
  - `getReservation(date) → {slots, modified_at, deleted, dirty, error} | null`
  - `reservationDates() → string[]` (sortiert)
  - `async saveReservation(date, slots)`, `async clearReservation(date)`, `async markReservationError(date, message, version)`
  - `snapshotReservations(limit = 400) → {reservations: {ISO: {slots, modified_at, deleted}}, reservationVersions: {ISO: number}}` — nur dirty Tage ohne Fehler, neueste zuerst.
  - `errorCount() → number` — Tage mit Fehler, Ist-Zeiten **und** Reservierungen.
  - `applyResponse(parsed, snapshot, today)` wendet zusätzlich `parsed.reservations` an (`null` oder fehlend → nichts anfassen, `reservations_enabled = false`).
- Adapter-Schnittstelle: Object Store `reservations` (Schlüssel = Datum), `getAll('reservations')` und `batch` mit `store: 'reservations'`.

- [ ] **Step 1: Failing tests** (`pwa/test/store.test.js`, Muster der vorhandenen Tests: Store über `createMemoryAdapter()`, feste Uhr). Die Datei hat Hilfen zum Aufbau; mit `grep -n "function make\|const make\|new Store" pwa/test/store.test.js` das Muster übernehmen und anhängen:

```js
const RES = { start: '09:00', end: '12:00', kategorie: 'Projekt' };
const parsedWith = (reservations, over = {}) => ({
  server_time: '2026-10-13T12:00:00Z', last_pull_at: '2026-10-13T12:00:00Z', excluded: false,
  window_days: 90, window_max: 365, entries: {}, conflicts: [], categories: [], defaults: null,
  desktop: { name: '', version: '', platform: '' }, token: 'T'.repeat(20),
  expires_at: '2026-11-13T12:00:00Z', reservations, ...over });
const emptySnapshot = (extra = {}) => ({ entries: {}, versions: {}, reservations: {}, reservationVersions: {}, ...extra });
const TODAY = '2026-10-13';

test('saving a reservation marks it dirty, strips everything but the three fields and stamps it', async () => {
  const { store } = await freshStore();                     // vorhandenen Hilfsaufbau benutzen
  await store.saveReservation('2026-10-20', [{ ...RES, pause: 30, gcal_event_id: 'x' }]);

  const day = store.getReservation('2026-10-20');
  assert.deepEqual(day.slots, [RES]);
  assert.equal(day.dirty, true);
  assert.equal(day.deleted, false);
  assert.match(day.modified_at, /^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$/);
  assert.deepEqual(store.reservationDates(), ['2026-10-20']);
});

test('saving identical reservation slots changes nothing', async () => {
  const { store } = await freshStore();
  await store.saveReservation('2026-10-20', [RES]);
  const first = store.getReservation('2026-10-20');

  await store.saveReservation('2026-10-20', [{ ...RES }]);

  assert.equal(store.getReservation('2026-10-20').modified_at, first.modified_at);
});

test('saving invalid reservation slots throws and stores nothing', async () => {
  const { store } = await freshStore();
  await assert.rejects(() => store.saveReservation('2026-10-20', [{ start: '12:00', end: '09:00', kategorie: '' }]));
  assert.deepEqual(store.reservationDates(), []);
});

test('clearing a reservation makes a dirty tombstone; clearing again is a no-op', async () => {
  const { store } = await freshStore();
  await store.saveReservation('2026-10-20', [RES]);
  await store.clearReservation('2026-10-20');
  const cleared = store.getReservation('2026-10-20');
  assert.equal(cleared.deleted, true);
  assert.deepEqual(cleared.slots, []);
  assert.equal(cleared.dirty, true);

  await store.clearReservation('2026-10-20');
  assert.equal(store.getReservation('2026-10-20').modified_at, cleared.modified_at);
});

test('the snapshot holds dirty reservations without a device id or a pause, newest first, and skips errors', async () => {
  const { store } = await freshStore();
  await store.saveReservation('2026-10-20', [RES]);
  await store.saveReservation('2026-10-21', [RES]);
  await store.saveReservation('2026-10-22', [RES]);
  await store.markReservationError('2026-10-22', 'abgelehnt');

  const snapshot = store.snapshotReservations();

  assert.deepEqual(Object.keys(snapshot.reservations).sort(), ['2026-10-20', '2026-10-21']);
  assert.deepEqual(Object.keys(snapshot.reservations['2026-10-20']).sort(), ['deleted', 'modified_at', 'slots']);
  assert.deepEqual(Object.keys(snapshot.reservationVersions).sort(), ['2026-10-20', '2026-10-21']);
  assert.equal(Object.keys(store.snapshotReservations(1).reservations).length, 1);
  assert.equal(store.errorCount(), 1);
});

test('a sent reservation that stayed unchanged is replaced by the desktop state and becomes clean', async () => {
  const { store } = await freshStore();
  await store.saveReservation('2026-10-20', [RES]);
  const snapshot = { ...emptySnapshot(), ...store.snapshotReservations() };

  await store.applyResponse(parsedWith({
    '2026-10-20': { slots: [RES], modified_at: '2026-10-13T12:00:00Z' } }), snapshot, TODAY);

  const day = store.getReservation('2026-10-20');
  assert.equal(day.dirty, false);
  assert.equal(day.modified_at, '2026-10-13T12:00:00Z');
  assert.equal(store.getMeta().reservations_enabled, true);
});

test('a reservation edited while the request was in flight stays local and dirty', async () => {
  const { store } = await freshStore();
  await store.saveReservation('2026-10-20', [RES]);
  const snapshot = { ...emptySnapshot(), ...store.snapshotReservations() };
  await store.saveReservation('2026-10-20', [{ ...RES, end: '13:00' }]);

  await store.applyResponse(parsedWith({
    '2026-10-20': { slots: [RES], modified_at: '2026-10-13T12:00:00Z' } }), snapshot, TODAY);

  assert.equal(store.getReservation('2026-10-20').slots[0].end, '13:00');
  assert.equal(store.getReservation('2026-10-20').dirty, true);
});

test('a clean reservation the desktop no longer lists is removed inside the future window only', async () => {
  const { store } = await freshStore();
  await store.applyResponse(parsedWith({
    '2026-10-20': { slots: [RES], modified_at: '2026-10-12T12:00:00Z' },
    '2027-10-13': { slots: [RES], modified_at: '2026-10-12T12:00:00Z' } }), emptySnapshot(), TODAY);
  assert.deepEqual(store.reservationDates(), ['2026-10-20', '2027-10-13']);

  await store.applyResponse(parsedWith({}), emptySnapshot(), TODAY);

  assert.deepEqual(store.reservationDates(), ['2027-10-13']);      // hinter heute + 365 gehört dem Desktop nicht
});

test('past reservations are cleaned up: clean ones by absence, sent dirty ones the desktop dropped', async () => {
  const { store } = await freshStore();
  await store.applyResponse(parsedWith({ '2026-10-20': { slots: [RES], modified_at: '2026-10-12T12:00:00Z' } }),
    emptySnapshot(), '2026-10-13');
  await store.saveReservation('2026-10-21', [RES]);                       // wird dirty
  const snapshot = { ...emptySnapshot(), ...store.snapshotReservations() };

  // zwei Tage später: beide sind vergangen, der Desktop liefert sie nicht mehr
  await store.applyResponse(parsedWith({}), snapshot, '2026-10-23');

  assert.deepEqual(store.reservationDates(), []);
});

test('a dirty reservation that was not part of the request survives a response without it', async () => {
  const { store } = await freshStore();
  await store.saveReservation('2026-10-20', [RES]);

  await store.applyResponse(parsedWith({}), emptySnapshot(), TODAY);

  assert.equal(store.getReservation('2026-10-20').dirty, true);
});

test('a desktop without reservations changes nothing locally and switches the feature off', async () => {
  const { store } = await freshStore();
  await store.applyResponse(parsedWith({ '2026-10-20': { slots: [RES], modified_at: '2026-10-12T12:00:00Z' } }),
    emptySnapshot(), TODAY);
  await store.saveReservation('2026-10-21', [RES]);

  await store.applyResponse(parsedWith(null), emptySnapshot(), TODAY);

  assert.equal(store.getMeta().reservations_enabled, false);
  assert.deepEqual(store.reservationDates(), ['2026-10-20', '2026-10-21']);
  assert.equal(store.getReservation('2026-10-21').dirty, true);
});

test('reservations survive a reload', async () => {
  const adapter = createMemoryAdapter();
  const first = new Store(adapter, () => new Date('2026-10-13T10:00:00Z'));
  await first.load();
  await first.saveReservation('2026-10-20', [RES]);

  const second = new Store(adapter);
  await second.load();

  assert.deepEqual(second.getReservation('2026-10-20').slots, [RES]);
});

test('a broken stored reservation row is skipped, not thrown', async () => {
  const adapter = createMemoryAdapter();
  await adapter.batch([{ store: 'reservations', op: 'put', key: '2026-10-20', value: { entry: 'kaputt' } }]);
  const store = new Store(adapter);

  await store.load();

  assert.deepEqual(store.reservationDates(), []);
});
```

`freshStore()` ist der vorhandene Hilfsaufbau der Testdatei (heißt dort ggf. anders: das Muster der Zeile `new Store(createMemoryAdapter(), …)` übernehmen; `createMemoryAdapter`/`Store` sind schon importiert).

`pwa/test/db.test.js`: die Attrappe prüft die Object Stores; Erwartung auf `['entries', 'meta', 'reservations']` und `VERSION` 2 anpassen (Test lesen, die Stelle ist die mit `createObjectStore`).

- [ ] **Step 2: Run to verify failure**

Run: `cd pwa && node --test test/store.test.js test/db.test.js`
Expected: FAIL (`store.saveReservation is not a function` u. a.).

- [ ] **Step 3: Implementation**

`pwa/memory-adapter.js`: `const stores = { entries: new Map(), meta: new Map(), reservations: new Map() };`

`pwa/db.js`: `const VERSION = 2;` und `const STORES = ['entries', 'meta', 'reservations'];` — `onupgradeneeded` legt fehlende Stores an, ein Upgrade von Version 1 lässt `entries`/`meta` unberührt.

`pwa/store.js`:

```js
import {
  RESERVATION_HORIZON_DAYS, normalizeReservationSlots, reservationSignature, validateReservationSlots,
} from './reservations.js';
const MAX_RESERVATIONS_PER_REQUEST = 400;      // Gegenstück zu `MAX_RESERVATIONS` in src/mobile_reservations.py
```

`DEFAULT_META` ergänzen: `reservations_enabled: false,   // Desktop bietet Reservierungen an (Feld in der Antwort); null/fehlt → verborgen`.

Konstruktor: `this._reservations = new Map();`

`load()`: nach den Einträgen

```js
    this._reservations.clear();
    for (const { key, value } of await this._adapter.getAll('reservations')) {
      const record = isObject(value) ? {
        entry: value.entry,
        dirty_version: value.dirty_version,
        synced_version: Number.isInteger(value.synced_version) ? value.synced_version : 0,
        error: typeof value.error === 'string' ? value.error : null,
      } : null;
      if (record && validRecord(key, record)) this._reservations.set(key, record);
    }
```

`_put` verallgemeinern (Wrapper bleibt, damit nichts anderes sich ändert):

```js
  _putIn(map, storeName, date, entry, ops) {
    const old = map.get(date);
    const record = {
      entry,
      dirty_version: (old ? old.dirty_version : 0) + 1,
      synced_version: old ? old.synced_version : 0,
      error: null,
    };
    map.set(date, record);
    ops.push({ store: storeName, op: 'put', key: date, value: record });
  }

  _put(date, entry, ops) {
    this._putIn(this._days, 'entries', date, entry, ops);
  }
```

Neue Methoden (nach `markDayError`):

```js
  // --- Reservierungen --------------------------------------------------------------------------

  reservationDates() {
    return [...this._reservations.keys()].sort();
  }

  getReservation(date) {
    const record = this._reservations.get(date);
    if (!record) return null;
    return {
      slots: structuredClone(record.entry.slots),
      modified_at: record.entry.modified_at,
      deleted: record.entry.deleted,
      dirty: isDirty(record),
      error: record.error,
    };
  }

  errorCount() {
    return [...this._days.values(), ...this._reservations.values()].filter((record) => record.error).length;
  }

  /** Speichert die Reservierung eines Tages. Wirft bei ungültigen Slots oder Datum. */
  async saveReservation(date, slots) {
    if (!isIsoDate(date)) throw new Error(`Ungültiges Datum: ${date}`);
    const normalized = normalizeReservationSlots(slots);
    const check = validateReservationSlots(normalized);
    if (!check.ok) throw new Error(check.message);
    const old = this._reservations.get(date);
    if (old && !old.entry.deleted && reservationSignature(old.entry.slots) === reservationSignature(normalized)) {
      if (old.error) {                                             // erneut speichern = erneut versuchen
        old.error = null;
        await this._adapter.batch([{ store: 'reservations', op: 'put', key: date, value: old }]);
      }
      return;
    }
    const ops = [];
    this._putIn(this._reservations, 'reservations', date, {
      slots: normalized, modified_at: this._stampAfter(old?.entry.modified_at), deleted: false,
    }, ops);
    await this._adapter.batch(ops);
  }

  /** „Tag leeren“ für die Reservierung: ein Tombstone, den der nächste Abgleich überträgt. */
  async clearReservation(date) {
    const old = this._reservations.get(date);
    if (!old || old.entry.deleted) return;
    const ops = [];
    this._putIn(this._reservations, 'reservations', date, {
      slots: [], modified_at: this._stampAfter(old.entry.modified_at), deleted: true,
    }, ops);
    await this._adapter.batch(ops);
  }

  async markReservationError(date, message, version) {
    const record = this._reservations.get(date);
    if (!record) return;
    if (version !== undefined && record.dirty_version !== version) return;
    record.error = String(message);
    await this._adapter.batch([{ store: 'reservations', op: 'put', key: date, value: record }]);
  }

  /** Was der nächste Abgleich an Reservierungen schickt: dirty Tage ohne Fehler, neueste zuerst,
   *  höchstens `limit` (der Desktop nimmt höchstens 400). Form der Anfrage: `{slots, modified_at,
   *  deleted}` — ohne `device_id`, ohne `pause`. */
  snapshotReservations(limit = MAX_RESERVATIONS_PER_REQUEST) {
    const reservations = {};
    const reservationVersions = {};
    for (const date of this.reservationDates().reverse()) {
      const record = this._reservations.get(date);
      if (!isDirty(record) || record.error) continue;
      if (Object.keys(reservations).length >= limit) break;
      reservations[date] = {
        slots: structuredClone(record.entry.slots),
        modified_at: record.entry.modified_at,
        deleted: record.entry.deleted,
      };
      reservationVersions[date] = record.dirty_version;
    }
    return { reservations, reservationVersions };
  }

  /** Wendet die `reservations` der Antwort an (`null`: der Desktop bietet sie nicht an — lokal bleibt
   *  alles stehen, nur die Funktion ist verborgen). Gleiche Regeln wie bei den Ist-Zeiten: ein
   *  gesendeter, unveränderter Tag wird vom Desktop-Stand ersetzt, ein inzwischen geänderter bleibt.
   *  Ein sauberer Tag, den die Antwort nicht kennt, ist am Desktop gelöscht — aber nur im
   *  Zukunftsfenster `[heute, heute + 365]` oder davor (vergangen); dahinter gehört er dem Desktop
   *  nicht. Ein gesendeter, unveränderter Tag, den die Antwort nicht kennt, ist verworfen (Tombstone
   *  eingelöst, oder vergangen und vom Desktop still verworfen). */
  _applyReservations(parsed, snapshot, today, ops) {
    if (parsed.reservations === null || parsed.reservations === undefined) return;
    const remote = new Map(Object.entries(parsed.reservations));
    const horizon = addDays(today, RESERVATION_HORIZON_DAYS);
    const sentVersions = snapshot.reservationVersions ?? {};

    for (const [date, entry] of remote) {
      if (!isIsoDate(date)) continue;
      const record = this._reservations.get(date);
      const sent = sentVersions[date];
      if (record && isDirty(record) && !(sent !== undefined && sent === record.dirty_version)) continue;
      const next = {
        entry: { slots: structuredClone(entry.slots), modified_at: entry.modified_at, deleted: false },
        dirty_version: record ? record.dirty_version : 0,
        synced_version: record ? record.dirty_version : 0,
        error: null,
      };
      this._reservations.set(date, next);
      ops.push({ store: 'reservations', op: 'put', key: date, value: next });
    }
    for (const [date, record] of [...this._reservations]) {
      if (remote.has(date)) continue;
      const sent = sentVersions[date];
      const dropSent = sent !== undefined && sent === record.dirty_version;
      const dropClean = !isDirty(record) && date <= horizon;
      if ((isDirty(record) && dropSent) || dropClean) {
        this._reservations.delete(date);
        ops.push({ store: 'reservations', op: 'delete', key: date });
      }
    }
  }
```

In `applyResponse` vor dem Setzen von `this._meta`:

```js
    this._applyReservations(parsed, snapshot, today, ops);
```

und im `_meta`-Objekt: `reservations_enabled: parsed.reservations !== null && parsed.reservations !== undefined,`.

> Prüfen: ein sauberer, vergangener Tag (`date < today`) fällt unter `date <= horizon` und wird entfernt — das ist gewollt (Test „past reservations are cleaned up“). Ein *dirty* vergangener Tag, der nicht gesendet wurde (z. B. wegen Fehlermarke), bleibt liegen.

- [ ] **Step 4: Run to verify pass**

Run: `cd pwa && node --test`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add pwa/memory-adapter.js pwa/db.js pwa/store.js pwa/test/store.test.js pwa/test/db.test.js
git commit -m "feat(pwa): Reservierungen im lokalen Store — eigene Sammlung, Anwenden der Antwort"
```

---

### Task 3: `sync.js` — Antwort lesen, Reservierungen senden, Ablehnung zuordnen

**Files:**
- Modify: `pwa/sync.js`, `pwa/test/fixtures/sync-request.json`, `pwa/test/fixtures/sync-response.json`
- Test: `pwa/test/sync.test.js`, `pwa/test/compat.test.js`, `tests/test_mobile_contract.py`

**Interfaces:**
- Consumes: Task 2 (`snapshotReservations`, `markReservationError`, `applyResponse` mit `parsed.reservations`).
- Produces: `parseSyncResponse` liefert `reservations: {ISO: {slots, modified_at}} | null`; `classifyHttpError` setzt `dayKind: 'reservation' | 'entry' | null`; `SyncClient` sendet `reservations` im ersten Päckchen.

- [ ] **Step 1: Failing tests**

`pwa/test/sync.test.js` (Muster: `reply`, `fakeFetch`, `fixture` der Datei; die vorhandenen Tests rund um `parseSyncResponse` und „a sync sends bearer, request shape and the dirty days“ zeigen den Aufbau):

```js
test('a response without reservations parses to null: the feature stays hidden', () => {
  const parsed = parseSyncResponse(fixture('compat/sync-response-pre-reservations.json'));
  assert.equal(parsed.reservations, null);
});

test('reservations in the response are cleaned: three slot fields, valid stamps, active days only', () => {
  const raw = { ...fixture('sync-response.json'), reservations: {
    '2026-10-15': { slots: [{ start: '09:00', end: '12:00', kategorie: 'Projekt', pause: 99, gcal_event_id: 'x' }],
      modified_at: '2026-10-08T11:00:00Z', deleted: false },
    '2026-10-16': { slots: [], modified_at: '2026-10-08T11:00:00Z', deleted: false },   // ohne Slots: entfällt
    kaputt: { slots: [{ start: '09:00', end: '12:00', kategorie: '' }], modified_at: 'x' },   // kein Datum: entfällt
    '2026-10-17': 'kein Objekt',
  } };

  const parsed = parseSyncResponse(raw);

  assert.deepEqual(parsed.reservations, {
    '2026-10-15': { slots: [{ start: '09:00', end: '12:00', kategorie: 'Projekt' }],
      modified_at: '2026-10-08T11:00:00Z' } });
});

test('a reservations field that is not an object counts as absent', () => {
  assert.equal(parseSyncResponse({ ...fixture('sync-response.json'), reservations: [1] }).reservations, null);
});

test('a rejected reservation day is told apart from a rejected work day', () => {
  const reservation = classifyHttpError(422, { error: { code: 'invalid_entry',
    message: 'Reservierung 2027-12-01: nur bis 365 Tage voraus erlaubt.' } });
  const entry = classifyHttpError(422, { error: { code: 'invalid_entry', message: '2026-10-07: kaputt' } });

  assert.deepEqual([reservation.day, reservation.dayKind], ['2027-12-01', 'reservation']);
  assert.deepEqual([entry.day, entry.dayKind], ['2026-10-07', 'entry']);
});
```

Client-Tests (mit dem Fake-Server aus der Datei):

```js
test('a sync sends the dirty reservations in the first request only, without device id or pause', async () => {
  // Store mit zwei dirty Ist-Tagen und einer dirty Reservierung aufbauen (Muster des Tests oben),
  // Fake-Server antwortet mit der Live-Fixture `sync-response.json`.
  // Erwartung: der entschlüsselte Request enthält
  //   reservations['2026-10-15'] = { slots: [{start,end,kategorie}], modified_at, deleted: false }
  // und KEIN device_id / pause in den Reservierungen.
});

test('a sync without dirty reservations sends no reservations field', async () => { /* … */ });

test('a 422 for a reservation day marks only that reservation and the next sync goes through', async () => {
  // Fake-Server antwortet beim ersten Aufruf verschlüsselt 422 invalid_entry
  // "Reservierung 2026-10-15: …". Erwartung: SyncError.kind 'invalid_entry'; store.getReservation(..).error gesetzt;
  // der zweite sync() sendet die Reservierung nicht mehr und ist erfolgreich.
});
```

(Die drei Rümpfe oben beim Schreiben ausformulieren: Aufbau und Hilfen stehen im Test „a sync sends bearer, request shape and the dirty days, then applies the answer“ in derselben Datei.)

`pwa/test/compat.test.js`: ein Test, dass die eingefrorene Antwort `compat/sync-response-pre-reservations.json` weiter angewendet wird und `reservations_enabled` falsch bleibt (nach dem Muster der vorhandenen `pre-250`-Tests).

Live-Beispiele erweitern (`pwa/test/fixtures/`, Einrückung wie bestehend):
- `sync-request.json`: `"reservations": {"2026-10-15": {"slots": [{"start": "09:00", "end": "12:00", "kategorie": "Projekt"}], "modified_at": "2026-10-07T18:40:00Z", "deleted": false}, "2026-10-16": {"slots": [], "modified_at": "2026-10-07T18:41:00Z", "deleted": true}}`
- `sync-response.json` hat `reservations` seit #309; unverändert.

Der vorhandene Formtest „sync request has the shape the phone sends“ (JS) vergleicht die Schlüssel des Beispiels mit dem echten Request; er braucht dafür im Testaufbau eine dirty Reservierung (oder der Test erwartet `reservations` nur bei dirty Reservierungen — dann die Fixture-Erwartung im Test so setzen, dass beide Fälle gelten). Die Python-Seite hat bereits `test_the_sync_request_example_has_the_shape_the_phone_sends`; zusätzlich in `tests/test_mobile_contract.py`:

```python
def test_the_live_request_example_carries_reservations_the_server_reads():
    example = load("sync-request.json")
    assert example["reservations"]

    parsed = mobile_sync.parse_request(
        json.dumps(example).encode(), now=example["client_time"],
        today=datetime.date.fromisoformat(example["client_time"][:10]))

    assert sorted(parsed.reservations) == sorted(example["reservations"])
```

- [ ] **Step 2: Run to verify failure**

Run: `cd pwa && node --test test/sync.test.js test/compat.test.js`
Expected: FAIL.

- [ ] **Step 3: Implementation** (`pwa/sync.js`)

Hilfsfunktionen vor `parseSyncResponse`:

```js
/** Reservierungen der Antwort: `null`, wenn das Feld fehlt oder kein Objekt ist (der Desktop bietet
 *  sie nicht an, Feature-Erkennung). Einzelne unbrauchbare Tage entfallen, statt die Antwort zu kippen. */
function parseReservations(raw) {
  if (!isObject(raw)) return null;
  const out = {};
  for (const [date, entry] of Object.entries(raw)) {
    if (!isIsoDate(date) || !isObject(entry) || !Array.isArray(entry.slots)) continue;
    const slots = cleanReservationSlots(entry.slots);
    if (slots.length === 0) continue;
    out[date] = { slots, modified_at: cleanStamp(entry.modified_at) };
  }
  return out;
}

function cleanReservationSlots(slots) {
  const text = (value) => (typeof value === 'string' ? value : '');
  return slots.filter(isObject).map((slot) => ({
    start: text(slot.start), end: text(slot.end), kategorie: text(slot.kategorie) }));
}
```

(`isObject` und `cleanStamp` sind in der Datei vor `parseEntry` definiert; die neuen Funktionen dahinter einsortieren.)

In `parseSyncResponse` dem Rückgabeobjekt `reservations: parseReservations(raw.reservations),` hinzufügen.

`classifyHttpError`: Tageserkennung und Art

```js
  const named = /^(Reservierung )?(\d{4}-\d{2}-\d{2}):/.exec(message);
  const day = kind === 'invalid_entry' ? (named?.[2] ?? null) : null;
  const dayKind = day ? (named[1] ? 'reservation' : 'entry') : null;
```

und `dayKind` in `SyncError` (Konstruktor-Parameter `dayKind = null`, in `Object.assign` aufnehmen).

`_run`: `includeReservations`:

```js
    let first = true;
    for (;;) {
      const result = await this._runOnce(MAX_DAYS_PER_REQUEST, done, first);
      first = false;
```

`_runOnce(limit, done, withReservations = false)`: nach `const snapshot = …`

```js
    const reserved = withReservations ? this._store.snapshotReservations() : { reservations: {}, reservationVersions: {} };
    Object.assign(snapshot, reserved);
```

Payload: `...(Object.keys(snapshot.reservations).length > 0 ? { reservations: snapshot.reservations } : {})` hinter `entries`.

Im `catch`: nach der `invalid_entry`-Behandlung der Tage

```js
      if (error instanceof SyncError && error.kind === 'invalid_entry' && error.day) {
        if (error.dayKind === 'reservation') {
          await this._store.markReservationError(error.day, error.message, snapshot.reservationVersions[error.day]);
        } else {
          await this._store.markDayError(error.day, error.message, snapshot.versions[error.day]);
        }
      }
```

(den bestehenden `markDayError`-Zweig dafür umbauen, nicht doppeln.)

- [ ] **Step 4: Run to verify pass**

Run: `cd pwa && node --test && cd .. && pytest tests/test_mobile_contract.py tests/test_mobile_sync.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add pwa/sync.js pwa/test tests/test_mobile_contract.py
git commit -m "feat(pwa): Reservierungen im Abgleich — senden, lesen, Ablehnung je Tag"
```

---

### Task 4: `view-model.js` — Wochenzeile und Editor-Zeilen

**Files:**
- Modify: `pwa/view-model.js`
- Test: `pwa/test/view-model.test.js`

**Interfaces:**
- Consumes: Task 1 (`reservationBlockVisible`, `normalizeReservationSlots`, `validateReservationSlots`), Task 2 (`getReservation`).
- Produces:
  - `weekModel({ …, getReservation = () => null, reservationsEnabled = false })`: jeder Tag trägt `reservation: {slots: string[], dirty, error, deleted} | null`; `null`, wenn die Funktion verborgen ist, der Tag vergangen ist oder keine lebende Reservierung existiert. `minutes`/`totalMinutes` bleiben unberührt. Zusätzlich `reservationVisible: boolean` je Tag (Editor-Tab erlaubt).
  - `reservationRows(reservation, defaults, weekday) → rows` (Form wie `editorRows`, mit `pause: '0'` im Zustand, aber ohne Pause im Anzeigefeld).
  - `reservationRowsToSlots(rows) → [{start, end, kategorie}]`, `validateReservationRows(rows)`.
  - `hintsModel` zählt `errorDays` weiter wie bisher (Aufrufer übergibt `store.errorCount()`).

- [ ] **Step 1: Failing tests**

```js
const RES_SLOT = { start: '09:00', end: '12:00', kategorie: 'Projekt' };
const reservations = (map) => (date) => map[date] ?? null;
const reserved = (slots, over = {}) => ({ slots, deleted: false, dirty: false, error: null, modified_at: 'x', ...over });

test('a reservation shows on today and future days when the feature is on, and not in the total', () => {
  const week = weekModel({
    getDay: days({ '2026-10-08': live([SLOT]) }), anchor: '2026-10-08', today: '2026-10-08',
    getReservation: reservations({ '2026-10-09': reserved([RES_SLOT], { dirty: true }) }), reservationsEnabled: true });

  assert.deepEqual(week.days[4].reservation.slots, ['09:00–12:00 · Projekt']);
  assert.equal(week.days[4].reservation.dirty, true);
  assert.equal(week.days[4].minutes, 0);
  assert.equal(week.totalMinutes, week.days[3].minutes);
});

test('reservations are hidden when the feature is off or the day is in the past', () => {
  const get = reservations({ '2026-10-07': reserved([RES_SLOT]), '2026-10-09': reserved([RES_SLOT]) });
  const off = weekModel({ getDay: days({}), anchor: '2026-10-08', today: '2026-10-08', getReservation: get, reservationsEnabled: false });
  const on = weekModel({ getDay: days({}), anchor: '2026-10-08', today: '2026-10-08', getReservation: get, reservationsEnabled: true });

  assert.ok(off.days.every((d) => d.reservation === null && d.reservationVisible === false));
  assert.equal(on.days[2].reservation, null);              // gestern: nichts, auch keine vorhandene
  assert.equal(on.days[2].reservationVisible, false);
  assert.notEqual(on.days[4].reservation, null);
  assert.equal(on.days[3].reservationVisible, true);       // heute
});

test('a cleared reservation is not shown', () => {
  const week = weekModel({ getDay: days({}), anchor: '2026-10-08', today: '2026-10-08',
    getReservation: reservations({ '2026-10-09': reserved([], { deleted: true }) }), reservationsEnabled: true });
  assert.equal(week.days[4].reservation, null);
});

test('reservation rows start from the weekday defaults and carry no pause on save', () => {
  const defaults = { pause: 30, weekdays: { fr: { start: '09:00', end: '17:00' } }, category_times: {} };
  const rows = reservationRows(null, defaults, 'fr');
  assert.equal(rows.length, 1);
  assert.deepEqual(reservationRowsToSlots(rows), [{ start: '09:00', end: '17:00', kategorie: '' }]);
});

test('saved reservation rows show their slots and a blank new row is dropped', () => {
  const rows = reservationRows(reserved([RES_SLOT]), null, 'mo');
  assert.deepEqual(reservationRowsToSlots(rows), [RES_SLOT]);
  const added = [...rows, { start: '', end: '', pause: '0', kategorie: '' }];
  assert.deepEqual(reservationRowsToSlots(added), [RES_SLOT]);
  assert.equal(validateReservationRows(added).ok, true);
});

test('a reservation row with times but a stray default pause validates', () => {
  const rows = [{ start: '09:00', end: '10:00', pause: '30', kategorie: '' }];
  assert.equal(validateReservationRows(rows).ok, true);          // die Pause zählt bei Reservierungen nicht
});
```

(Importe in der Testdatei ergänzen: `reservationRows`, `reservationRowsToSlots`, `validateReservationRows`.)

- [ ] **Step 2: Run to verify failure**

Run: `cd pwa && node --test test/view-model.test.js`
Expected: FAIL.

- [ ] **Step 3: Implementation**

Importe in `view-model.js`: `import { normalizeReservationSlots, reservationBlockVisible, validateReservationSlots } from './reservations.js';`

`weekModel`: Parameter `getReservation = () => null, reservationsEnabled = false`; in der Tagesschleife

```js
    const visible = reservationsEnabled && reservationBlockVisible(date, today);
    const reservation = visible ? getReservation(date) : null;
    const live = reservation && !reservation.deleted && reservation.slots.length > 0 ? reservation : null;
```

und im Tagesobjekt:

```js
      reservationVisible: visible,
      reservation: live && { slots: live.slots.map(slotText), dirty: live.dirty, error: live.error },
```

Neue Funktionen (neben `editorRows`):

```js
/** Zeilen der Reservierung. Wie `editorRows`, nur dass eine frische Zeile ohne Kategorie-Zeiten
 *  auskommt — die Pause bleibt im Zustand (die Vorbelegung liefert sie), wird aber nie angezeigt
 *  und nie gespeichert. */
export function reservationRows(reservation, defaults = null, weekday = '') {
  return editorRows(reservation, defaults, weekday);
}

const isBlankReservation = (row) => row.start === '' && row.end === '' && row.kategorie === '';

export function reservationRowsToSlots(rows) {
  return rows.filter((row) => !isBlankReservation(row)).map((row) => ({
    start: row.start, end: row.end, kategorie: row.kategorie }));
}

export function validateReservationRows(rows) {
  return validateReservationSlots(normalizeReservationSlots(reservationRowsToSlots(rows)));
}
```

(`editorRows` behandelt `day.deleted`/leere Slots als „frische Zeile“; `reservation` hat dieselben Felder, `slot.pause ?? 0` greift für fehlende Pausen.)

- [ ] **Step 4: Run to verify pass**

Run: `cd pwa && node --test`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add pwa/view-model.js pwa/test/view-model.test.js
git commit -m "feat(pwa): Reservierungen in Wochenmodell und Editor-Zeilen"
```

---

### Task 5: Oberfläche — Editor-Tabs, Wochenzeile, Verdrahtung

**Files:**
- Modify: `pwa/views.js`, `pwa/app.js`, `pwa/app.css`
- Test: `pwa/test/shell.test.js` bleibt grün (kein `innerHTML`); die DOM-Schicht wird wie bisher **nicht** automatisiert getestet, sondern von Hand im Browser (Step 5).

**Interfaces:**
- Consumes: Task 4 (`weekModel` mit `reservation`/`reservationVisible`, `reservationRows`, `reservationRowsToSlots`, `validateReservationRows`), Task 2 (`Store`-Methoden), `store.getMeta().reservations_enabled`.
- Produces: `editorDialog({ …, reservation })` mit optionalem Abschnitt `reservation: { rows, canClear, validate }`; Handler `save(kind, rows)` und `clear(kind, dialog)` mit `kind` `'work' | 'reservation'`.

**Entwurf des Editors.** Ein Dialog, zwei Abschnitte, ein Schalter (Tabs „Arbeitszeit“ / „Reservierung“) — nur wenn `reservation` übergeben wird (Funktion an, Tag heute oder Zukunft). Jeder Abschnitt hält seinen **eigenen** Zustand (Eingaben gehen beim Wechsel nicht verloren); „Speichern“ und „Tag leeren“ wirken auf den **aktiven** Abschnitt. Vorauswahl: Reservierung an Tagen **nach heute**, Arbeitszeit sonst. Grund (Review Focus 6): die Ist-Zeilen sind mit den Standardzeiten vorbelegt; ein Speichern in der falschen Ansicht dürfte nie still eine Ist-Zeit anlegen.

- [ ] **Step 1: `views.js` — Abschnitt als wiederverwendbare Einheit**

Die Zeilenliste von `editorDialog` (Funktionen `field`, `categoryField`, `build`, der `state`) wird zu einer Hilfsfunktion `slotSection({ rows, categories, defaults, weekday, withPause, onChange })`, die `{ element, state, refresh }` liefert; `withPause: false` lässt das Pausenfeld weg (in der Zeile steht dann nur das Kategoriefeld unter `von`/`bis`). Der Dialog baut eine Section für die Arbeitszeit und, falls übergeben, eine für die Reservierung:

```js
function slotSection({ rows, categories, defaults, weekday, withPause, onChange }) {
  const list = h('div', {});
  const state = rows.map((row) => ({ ...row, base: row.base && { ...row.base } }));
  const prefix = withPause ? 'slot' : 'res';
  const field = (index, key, label, attrs) => {
    const id = `${prefix}-${index}-${key}`;
    const input = h('input', { id, value: state[index][key], ...attrs,
      oninput: () => { state[index][key] = input.value; onChange(); } });
    return h('div', {}, h('label', { for: id }, label), input);
  };
  const categoryField = (index) => {
    const id = `${prefix}-${index}-kategorie`;
    const text = h('span', { class: 'text' }, categoryLabel(state[index].kategorie));
    const picker = button([text, h('span', { 'aria-hidden': 'true' }, '▾')], () => {
      categoryPickerDialog({ categories, current: state[index].kategorie }, (name) => {
        pickCategory(state[index], name, defaults, weekday);
        build();
        onChange();
        document.getElementById(id)?.focus();
      });
    }, 'picker', { id });
    return h('div', {}, h('label', { for: id }, 'Kategorie'), picker);
  };
  const build = () => {
    list.replaceChildren(...state.map((_, index) => h('fieldset', { class: 'slot' },
      state.length > 1 && button('×', () => { state.splice(index, 1); build(); onChange(); }, 'remove', { 'aria-label': 'Slot entfernen' }),
      h('div', { class: 'row' },
        field(index, 'start', 'von', { type: 'time', step: 60 }),
        field(index, 'end', 'bis', { type: 'time', step: 60 })),
      h('div', { class: 'row' },
        withPause && field(index, 'pause', 'Pause (Min)', { type: 'number', inputmode: 'numeric', min: 0, step: 1 }),
        categoryField(index)))));
  };
  build();
  const element = h('div', {}, list,
    button('+ Slot', () => { state.push(nextRow(state.at(-1))); build(); onChange(); }));
  return { element, state };
}
```

Der bisherige Code in `editorDialog` (Zeilen `field`/`categoryField`/`build`) entfällt zugunsten dieses Aufrufs; Verhalten und Element-IDs der Arbeitszeit-Ansicht bleiben unverändert (`slot-<i>-<feld>`; die Reservierung nutzt `res-…`, damit keine IDs kollidieren).

Der Dialog:

```js
export function editorDialog({ title, rows, categories, defaults = null, weekday = '', error, outsideWindow,
  canClear, validate, reservation = null, startWith = 'work' }, handlers) {
  const message = h('div', { class: 'error-text', role: 'alert' }, error ?? '');
  const save = h('button', { type: 'submit', class: 'primary' }, 'Speichern');
  const dialog = h('dialog', { 'aria-labelledby': 'editor-title' });
  let active = reservation ? startWith : 'work';

  const refresh = () => {
    const check = (active === 'work' ? validate(work.state) : reservation.validate(res.state));
    save.disabled = !check.ok;
    if (!error || check.ok) message.textContent = check.ok ? '' : check.message;
  };
  const work = slotSection({ rows, categories, defaults, weekday, withPause: true, onChange: () => refresh() });
  const res = reservation && slotSection({ rows: reservation.rows, categories, defaults, weekday,
    withPause: false, onChange: () => refresh() });
  const clearButton = button('Tag leeren', () => handlers.clear(active, dialog), 'link');
  const show = (kind) => {
    active = kind;
    work.element.hidden = kind !== 'work';
    if (res) res.element.hidden = kind !== 'reservation';
    tabs?.work.setAttribute('aria-selected', String(kind === 'work'));
    tabs?.reservation.setAttribute('aria-selected', String(kind === 'reservation'));
    clearButton.hidden = !(kind === 'work' ? canClear : reservation.canClear);
    refresh();
  };
  const tabs = reservation && {
    work: h('button', { type: 'button', role: 'tab', onclick: () => show('work') }, 'Arbeitszeit'),
    reservation: h('button', { type: 'button', role: 'tab', onclick: () => show('reservation') }, 'Reservierung'),
  };
  // … Aufbau wie bisher: Formular, Überschrift, Hinweis, dann
  //   tabs && h('div', { class: 'tabs', role: 'tablist' }, tabs.work, tabs.reservation),
  //   work.element, res?.element, message, Buttonzeile mit clearButton, Abbrechen, save.
  // `onsubmit`: await handlers.save(active, active === 'work' ? work.state : res.state)
  show(active);
  return openDialog(dialog);
}
```

Der Hinweis `outsideWindow` gilt nur für die Arbeitszeit (`hidden`, wenn die Reservierung aktiv ist).

- [ ] **Step 2: `views.js` — Wochenzeile**

In `dayRow` unter `ul.slots` Reservierungszeilen anzeigen:

```js
    day.reservation && h('ul', { class: 'slots reserved' },
      day.reservation.slots.map((text) => h('li', {}, `geplant ${text}`))),
```

und in `marks` ein Zeichen `○` bei `day.reservation?.dirty` (`title: 'Reservierung nicht übertragen'`); ein Fehler der Reservierung steht in `day.reservation.error` (zeigt dieselbe `.err`-Zeile).

- [ ] **Step 3: `app.js` — Verdrahtung**

- `weekModel({ …, getReservation: (date) => this.store.getReservation(date), reservationsEnabled: meta.reservations_enabled })`.
- `errorDays: this.store.errorCount()` statt `this.store.days().filter(…)`.
- `openDay(date)`:

```js
    const reservationOn = meta.reservations_enabled && reservationBlockVisible(date, today);
    const reservation = reservationOn ? this.store.getReservation(date) : null;
    let reservationBaseline = reservation;
    ...
    const dialog = editorDialog({
      …,
      reservation: reservationOn ? {
        rows: reservationRows(reservation, meta.defaults, weekdayKey(date)),
        canClear: Boolean(reservation && !reservation.deleted),
        validate: (rows) => validateReservationRows(rows),
      } : null,
      startWith: reservationOn && date > today ? 'reservation' : 'work',
      error: (reservationOn && date > today ? reservation?.error : day?.error) ?? null,
    }, {
      save: async (kind, rows) => {
        if (kind === 'reservation') {
          const current = this.store.getReservation(date);
          if (dayChanged(reservationBaseline, current)) {
            reservationBaseline = current;
            return 'Diese Reservierung wurde inzwischen aktualisiert (Abgleich). Nochmaliges Speichern überschreibt die neuere Fassung.';
          }
          try {
            await this.store.saveReservation(date, reservationRowsToSlots(rows));
          } catch (error) {
            return String(error?.message ?? error);
          }
        } else {
          /* bisheriger Zweig unverändert (dayChanged, saveDay) */
        }
        this.render();
        this.scheduleSyncAfterSave();
        return null;
      },
      clear: (kind, dialog) => confirmDialog({
        title: kind === 'reservation' ? 'Reservierung löschen?' : 'Tag leeren?',
        text: kind === 'reservation'
          ? `Die Reservierung vom ${formatDateDe(date)} wird gelöscht (beim nächsten Abgleich auch am Desktop).`
          : `Alle Einträge vom ${formatDateDe(date)} werden gelöscht (beim nächsten Abgleich auch am Desktop).`,
        confirmLabel: kind === 'reservation' ? 'Reservierung löschen' : 'Tag leeren',
      }, async () => { /* clearReservation bzw. clearDay, sonst wie bisher */ }),
    });
```

(`dayChanged` ist für beide Formen verwendbar: es vergleicht `modified_at`, `deleted` und `slots`.) Importe: `reservationBlockVisible` aus `./reservations.js`; `reservationRows`, `reservationRowsToSlots`, `validateReservationRows` aus `./view-model.js`.

- [ ] **Step 4: `app.css`**

```css
.tabs { display: flex; gap: .5rem; margin: .5rem 0; }
.tabs button { flex: 1; padding: .5rem; border: 1px solid var(--border, #888); background: transparent; color: inherit; border-radius: .4rem; }
.tabs button[aria-selected="true"] { background: var(--accent); color: var(--on-accent, #fff); border-color: var(--accent); }
.day .slots.reserved { color: var(--muted); font-style: italic; }
```

(Variablennamen an die vorhandenen in `app.css` anpassen: `grep -n "^:root" -A12 pwa/app.css`.)

- [ ] **Step 5: Prüfen**

Run: `cd pwa && node --test` — Expected: PASS (inkl. `shell.test.js`: kein `innerHTML`, `PRECACHE` vollständig).

Von Hand im Browser (UI wird nicht automatisiert getestet): `python scripts/pwa_devserver.py` starten, in den Desktop-Einstellungen „Reservierungen verwenden“ einschalten, per Playwright oder Handy koppeln und prüfen:
1. Wochenansicht zeigt eine Reservierung des Desktops als „geplant …“ an zukünftigen Tagen, nicht an vergangenen.
2. Editor an einem Zukunftstag öffnet mit dem Tab „Reservierung“; Speichern legt **keine** Ist-Zeit an (Wochenansicht zeigt nur „geplant …“).
3. Editor heute öffnet mit „Arbeitszeit“; Tab-Wechsel behält die Eingaben beider Tabs.
4. Reservierung am Handy anlegen → Abgleich → am Desktop sichtbar; am Desktop ändern → Abgleich → am Handy geändert; am Handy löschen → nach dem Abgleich am Desktop weg.
5. Reservierungen am Desktop ausschalten → Abgleich → Tab „Reservierung“ und „geplant“-Zeilen verschwinden, Daten bleiben.
6. Vergangener Tag: kein Tab.

- [ ] **Step 6: Commit**

```bash
git add pwa/views.js pwa/app.js pwa/app.css
git commit -m "feat(pwa): Reservierungen in Wochenansicht und Tages-Editor"
```

---

### Task 6: Doku

**Files:**
- Modify: `pwa/CLAUDE.md`, `src/CLAUDE.md`, `CLAUDE.md`

- [ ] **Step 1: `pwa/CLAUDE.md`**
  - Modulliste: `reservations.js` — Sichtbarkeit (`reservationBlockVisible`, Gleichlauf mit `reservation_block_visible` über `test/fixtures/reservation-visibility-cases.json`), Slot-Normalisierung/-Prüfung ohne Pause.
  - `store.js`-Absatz: eigene Sammlung `reservations` (IndexedDB `VERSION` 2), Anwenden in derselben Transaktion.
  - Neuer Abschnitt „Reservierungen“: Feature-Erkennung (`reservations` in der Antwort; fehlt es, bleibt alles verborgen, lokale Daten bleiben), nur heute und Zukunft, Löschen nur über „Tag leeren“, Anwenden nur im Zukunftsfenster, Form der Anfrage ohne `device_id`/`pause`, `422` je Tag über die Meldung `Reservierung <Datum>:`.
  - Kompatibilitäts-Abschnitt: „neue PWA, alter Desktop“: sendet Reservierungen nur, wenn welche dirty sind; ein Desktop vor #309 ignoriert das Feld.

- [ ] **Step 2: `src/CLAUDE.md`** — im `mobile_sync.py`-Absatz einen Satz: die PWA sendet und liest `reservations` seit PR 3; Verweis auf `pwa/CLAUDE.md`.

- [ ] **Step 3: Wurzel-`CLAUDE.md`** — Zeile `pwa/`: Reservierungen erwähnen; Zeile `src/mobile_reservations.py`: Gegenstück `pwa/reservations.js`.

- [ ] **Step 4: Prüfen und committen**

Run: `pytest tests/test_claude_md_claims.py -q && ruff check .`
Expected: PASS.

```bash
git add pwa/CLAUDE.md src/CLAUDE.md CLAUDE.md
git commit -m "docs(pwa): Reservierungen in der Handy-PWA"
```

---

## Abschluss

- [ ] Vollständiger Lauf: `pytest -q --ignore=tests/test_qr.py`, `ruff check .`, `(cd pwa && node --test)`.
- [ ] Browser-Prüfung aus Task 5, Step 5 ist Pflicht: die DOM-Schicht hat keinen automatisierten Test.
- [ ] PR gegen `master`, Titel `feat(pwa): Reservierungen in der Handy-PWA (PR 3/3)`, `Closes`-Zeile nur, falls ein Issue existiert. **Kein** `release:*`-Label, **kein** Versionsbump (kommt im Release-PR: `src/version.py`, `pwa/package.json`, CHANGELOG, `resolve_readme_version.py`). Die README hat ggf. Zeilen zur Handy-Erfassung; neue Aussagen dort mit `*(ab --VERSION--)*` markieren.
- [ ] Nach dem Merge ist die Pages-Veröffentlichung sofort live (`pages.yml`); ein Desktop ohne #309 ignoriert das Feld, die PWA zeigt die Funktion dort nie an (Feature-Erkennung).

## Self-Review

- **Spec-Abdeckung:** eigene Sammlung mit `dirty_version`/`synced_version` + Anwenden nur im Zukunftsfenster → T2; `memory-adapter.js`/Tests → T2; `sync.js` sendet geänderte Tage und wendet an, `parseReservations` → `null` → T2/T3; Marker in der Wochenansicht und Block im Editor nur für heute/Zukunft, `reservationBlockVisible` mit Fixture → T1/T4/T5; Löschen nur über die vorhandene Lösch-Geste, Vergangenheit nichts → T5; `PRECACHE` → T1; Version-Bump bewusst nicht (Release-PR) → Abschluss; `pwa/CLAUDE.md` → T6.
- **Platzhalter-Scan:** In T3 sind drei Client-Tests und in T5 die Dialog-Zusammensetzung (Kommentar „Aufbau wie bisher“) nur als Rumpf bzw. Skizze ausgeführt, weil ihr Aufbau an Hilfen hängt, die ich nicht vollständig ausgelesen habe (Fake-Server-Fixture in `sync.test.js`, Rest von `editorDialog`/`openDay`). Wer ausführt, liest die genannten Stellen zuerst. Sonst keine offenen Stellen.
- **Typkonsistenz:** `snapshotReservations() → {reservations, reservationVersions}` (T2) wird in T3 (`Object.assign(snapshot, …)`) und in `_applyReservations` (`snapshot.reservationVersions`) gleich benannt; `weekModel`-Felder `reservation`/`reservationVisible` (T4) werden in T5 gelesen; Handler-Signatur `save(kind, rows)`/`clear(kind, dialog)` in T5 durchgehend.
