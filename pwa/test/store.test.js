// pwa/test/store.test.js
import { test } from 'node:test';
import assert from 'node:assert/strict';

import { Store } from '../store.js';
import { createMemoryAdapter } from '../memory-adapter.js';

const SLOT = { start: '08:00', end: '12:00', pause: 0, kategorie: 'Projekt' };
const OTHER = { start: '13:00', end: '17:00', pause: 0, kategorie: '' };

function clock(startIso = '2026-10-08T12:00:00Z') {
  let current = new Date(startIso);
  const now = () => new Date(current);
  now.set = (iso) => { current = new Date(iso); };
  now.advance = (ms) => { current = new Date(current.getTime() + ms); };
  return now;
}

async function make({ adapter = createMemoryAdapter(), now = clock() } = {}) {
  const store = new Store(adapter, now);
  await store.load();
  await store.setMeta({ device_id: 'phone-0001', token: 'T0', address: { host: '192.168.1.20', port: 17654 } });
  return { store, adapter, now };
}

function parsedResponse(over = {}) {
  return {
    protocol: 1, server_time: '2026-10-08T12:00:00Z', last_pull_at: '2026-10-08T12:00:00Z',
    excluded: false, window_days: 90, entries: {}, conflicts: [], categories: ['Projekt'],
    token: 'T1', expires_at: '2026-11-07T12:00:00Z', ...over,
  };
}

const remoteDay = (slots = [OTHER], over = {}) => ({
  slots, modified_at: '2026-10-07T20:00:00Z', device_id: 'DESK', deleted: false, ...over,
});

const TODAY = '2026-10-08';

// --- Erfassen -------------------------------------------------------------------------------------

test('saving a day marks it dirty and stamps it in UTC with the device id', async () => {
  const { store } = await make();
  await store.saveDay('2026-10-07', [SLOT]);

  const day = store.getDay('2026-10-07');
  assert.deepEqual(day.slots, [SLOT]);
  assert.equal(day.dirty, true);
  assert.equal(day.deleted, false);
  assert.equal(day.modified_at, '2026-10-08T12:00:00Z');
  assert.deepEqual(store.dirtyDates(), ['2026-10-07']);
  assert.deepEqual(store.snapshotDirty().entries['2026-10-07'], {
    slots: [SLOT], modified_at: '2026-10-08T12:00:00Z', device_id: 'phone-0001', deleted: false });
});

test('saving identical slots changes nothing, even in another order', async () => {
  const { store, now } = await make();
  await store.saveDay('2026-10-07', [SLOT, OTHER]);
  const before = store.snapshotDirty();
  now.advance(60000);

  await store.saveDay('2026-10-07', [OTHER, SLOT]);

  assert.deepEqual(store.snapshotDirty(), before);
});

test('modified_at never runs backwards: at least one second after the previous stamp', async () => {
  const { store, now } = await make();
  await store.saveDay('2026-10-07', [SLOT]);
  await store.saveDay('2026-10-07', [OTHER]);                       // gleiche Sekunde
  assert.equal(store.getDay('2026-10-07').modified_at, '2026-10-08T12:00:01Z');

  now.set('2026-10-08T11:00:00Z');                                  // Uhr zurückgestellt
  await store.saveDay('2026-10-07', [SLOT]);
  assert.equal(store.getDay('2026-10-07').modified_at, '2026-10-08T12:00:02Z');
});

test('clearing a day makes a dirty tombstone; clearing it again is a no-op', async () => {
  const { store } = await make();
  await store.saveDay('2026-10-07', [SLOT]);
  await store.clearDay('2026-10-07');

  const day = store.getDay('2026-10-07');
  assert.equal(day.deleted, true);
  assert.deepEqual(day.slots, []);
  assert.equal(day.dirty, true);
  const snapshot = store.snapshotDirty();
  await store.clearDay('2026-10-07');
  assert.deepEqual(store.snapshotDirty(), snapshot);
  await store.clearDay('2026-10-01');                               // gab es nie
  assert.equal(store.getDay('2026-10-01'), null);
});

test('saving a day again after clearing revives it', async () => {
  const { store } = await make();
  await store.clearDay('2026-10-07');
  await store.saveDay('2026-10-07', [SLOT]);                        // nichts da: neuer Tag
  await store.clearDay('2026-10-07');
  await store.saveDay('2026-10-07', [SLOT]);
  assert.equal(store.getDay('2026-10-07').deleted, false);
});

test('days() is sorted', async () => {
  const { store } = await make();
  await store.saveDay('2026-10-07', [SLOT]);
  await store.saveDay('2026-09-30', [SLOT]);
  await store.saveDay('2026-10-08', [SLOT]);
  assert.deepEqual(store.days(), ['2026-09-30', '2026-10-07', '2026-10-08']);
});

test('a day with an error is not sent until it is edited', async () => {
  const { store } = await make();
  await store.saveDay('2026-10-07', [SLOT]);
  await store.saveDay('2026-10-06', [SLOT]);
  await store.markDayError('2026-10-07', 'abgelehnt');

  assert.deepEqual(Object.keys(store.snapshotDirty().entries), ['2026-10-06']);
  assert.equal(store.getDay('2026-10-07').error, 'abgelehnt');
  assert.equal(store.getDay('2026-10-07').dirty, true);              // bleibt „nicht übertragen“

  await store.saveDay('2026-10-07', [OTHER]);
  assert.equal(store.getDay('2026-10-07').error, null);
  assert.deepEqual(Object.keys(store.snapshotDirty().entries).sort(), ['2026-10-06', '2026-10-07']);
});

// --- Antwort anwenden: Tage ------------------------------------------------------------------------

test('a sent day that stayed unchanged is replaced by the desktop state and becomes clean', async () => {
  const { store } = await make();
  await store.saveDay('2026-10-07', [SLOT]);
  const snapshot = store.snapshotDirty();

  await store.applyResponse(parsedResponse({ entries: { '2026-10-07': remoteDay([OTHER]) } }), snapshot, TODAY);

  const day = store.getDay('2026-10-07');
  assert.deepEqual(day.slots, [OTHER]);
  assert.equal(day.dirty, false);
  assert.deepEqual(store.dirtyDates(), []);
});

test('a day edited while the request was in flight stays local and dirty', async () => {
  const { store, now } = await make();
  await store.saveDay('2026-10-07', [SLOT]);
  const snapshot = store.snapshotDirty();
  now.advance(5000);
  await store.saveDay('2026-10-07', [OTHER]);                       // während des Sendens

  await store.applyResponse(parsedResponse({ entries: { '2026-10-07': remoteDay([SLOT]) } }), snapshot, TODAY);

  assert.deepEqual(store.getDay('2026-10-07').slots, [OTHER]);
  assert.equal(store.getDay('2026-10-07').dirty, true);
});

test('a day cleared while the request was in flight is not revived by the response', async () => {
  const { store } = await make();
  await store.saveDay('2026-10-07', [SLOT]);
  const snapshot = store.snapshotDirty();
  await store.clearDay('2026-10-07');

  await store.applyResponse(parsedResponse({ entries: { '2026-10-07': remoteDay([SLOT]) } }), snapshot, TODAY);

  assert.equal(store.getDay('2026-10-07').deleted, true);
  assert.equal(store.getDay('2026-10-07').dirty, true);
});

test('a dirty day that was not part of the request keeps the local version', async () => {
  const { store } = await make();
  const snapshot = store.snapshotDirty();                           // leer
  await store.saveDay('2026-10-07', [SLOT]);

  await store.applyResponse(parsedResponse({ entries: { '2026-10-07': remoteDay([OTHER]) } }), snapshot, TODAY);

  assert.deepEqual(store.getDay('2026-10-07').slots, [SLOT]);
  assert.equal(store.getDay('2026-10-07').dirty, true);
});

test('a desktop day that is new to the phone is added clean', async () => {
  const { store } = await make();
  await store.applyResponse(parsedResponse({ entries: { '2026-10-05': remoteDay() } }), store.snapshotDirty(), TODAY);
  assert.equal(store.getDay('2026-10-05').dirty, false);
  assert.deepEqual(store.getDay('2026-10-05').slots, [OTHER]);
});

test('a desktop tombstone arrives as a clean deleted day', async () => {
  const { store } = await make();
  await store.applyResponse(
    parsedResponse({ entries: { '2026-10-05': remoteDay([], { deleted: true }) } }), store.snapshotDirty(), TODAY);
  assert.equal(store.getDay('2026-10-05').deleted, true);
  assert.equal(store.getDay('2026-10-05').dirty, false);
});

// --- Antwort anwenden: Fenster ---------------------------------------------------------------------

async function withCleanDays(dates) {
  const made = await make();
  const entries = Object.fromEntries(dates.map((d) => [d, remoteDay()]));
  await made.store.applyResponse(parsedResponse({ entries }), made.store.snapshotDirty(), TODAY);
  return made;
}

test('a clean day inside the window that the response lacks is removed', async () => {
  const { store } = await withCleanDays(['2026-10-05', '2026-10-06']);
  await store.applyResponse(parsedResponse({ entries: { '2026-10-06': remoteDay() } }), store.snapshotDirty(), TODAY);
  assert.equal(store.getDay('2026-10-05'), null);
  assert.notEqual(store.getDay('2026-10-06'), null);
});

test('a dirty day that the response lacks is kept', async () => {
  const { store } = await make();
  await store.saveDay('2026-10-05', [SLOT]);
  await store.applyResponse(parsedResponse(), { entries: {}, versions: {} }, TODAY);   // nicht mitgeschickt
  assert.equal(store.getDay('2026-10-05').dirty, true);
});

test('only the inner window is cleaned: the boundary days are never deleted by absence', async () => {
  // window_days 90, heute 2026-10-08 → Fenster 2026-07-10 … 2026-10-08;
  // innen: 2026-07-11 … 2026-10-07. Die Ränder gehören dem Desktop.
  const { store } = await withCleanDays(['2026-07-10', '2026-07-11', '2026-10-07', '2026-10-08']);
  await store.applyResponse(parsedResponse(), store.snapshotDirty(), TODAY);
  assert.notEqual(store.getDay('2026-07-10'), null);
  assert.equal(store.getDay('2026-07-11'), null);
  assert.equal(store.getDay('2026-10-07'), null);
  assert.notEqual(store.getDay('2026-10-08'), null);
});

test('clean days far outside the window are removed, dirty ones stay', async () => {
  const { store } = await make();
  await store.applyResponse(parsedResponse({
    entries: { '2026-06-01': remoteDay(), '2026-07-09': remoteDay(), '2026-10-10': remoteDay() } }),
    store.snapshotDirty(), TODAY);
  assert.equal(store.getDay('2026-06-01'), null);                    // weit außerhalb
  assert.notEqual(store.getDay('2026-07-09'), null);                 // eine Zeile Rand: bleibt
  assert.equal(store.getDay('2026-10-10'), null);                    // > heute + 1

  await store.saveDay('2026-05-01', [SLOT]);
  await store.applyResponse(parsedResponse(), { entries: {}, versions: {} }, TODAY);
  assert.equal(store.getDay('2026-05-01').dirty, true);
});

test('a sent day outside the window is clean afterwards but then pruned', async () => {
  const { store } = await make();
  await store.saveDay('2026-01-15', [SLOT]);
  const snapshot = store.snapshotDirty();
  await store.applyResponse(parsedResponse({ entries: { '2026-01-15': remoteDay([SLOT]) } }), snapshot, TODAY);
  assert.equal(store.getDay('2026-01-15'), null);
  assert.deepEqual(store.dirtyDates(), []);
});

test('a sent day the desktop dropped (self-heal) is removed when unchanged', async () => {
  const { store } = await make();
  await store.saveDay('2026-09-01', [SLOT]);
  const snapshot = store.snapshotDirty();
  await store.applyResponse(parsedResponse({ excluded: true }), snapshot, TODAY);
  assert.equal(store.getDay('2026-09-01'), null);
  assert.equal(store.getMeta().excluded, true);
});

test('a sent day the desktop dropped is kept when it was edited meanwhile', async () => {
  const { store, now } = await make();
  await store.saveDay('2026-09-01', [SLOT]);
  const snapshot = store.snapshotDirty();
  now.advance(5000);
  await store.saveDay('2026-09-01', [OTHER]);
  await store.applyResponse(parsedResponse({ excluded: true }), snapshot, TODAY);
  assert.deepEqual(store.getDay('2026-09-01').slots, [OTHER]);
});

// --- Antwort anwenden: Meta und Persistenz ---------------------------------------------------------

test('the response updates token, last_pull_at, categories, window and conflicts', async () => {
  const { store } = await make();
  const conflicts = [{ id: 'c1', date: '2026-10-05', versions: [] }];

  await store.applyResponse(parsedResponse({ conflicts, categories: ['A', 'B'], window_days: 60 }),
    store.snapshotDirty(), TODAY);

  const meta = store.getMeta();
  assert.equal(meta.token, 'T1');
  assert.equal(meta.token_expires_at, '2026-11-07T12:00:00Z');
  assert.equal(meta.last_pull_at, '2026-10-08T12:00:00Z');
  assert.deepEqual(meta.categories, ['A', 'B']);
  assert.equal(meta.window_days, 60);
  assert.deepEqual(meta.conflicts, conflicts);
  assert.equal(meta.excluded, false);
  assert.equal(meta.device_id, 'phone-0001');                        // bleibt
});

test('days and the new token are written in one batch', async () => {
  const adapter = createMemoryAdapter();
  const batches = [];
  const original = adapter.batch.bind(adapter);
  adapter.batch = async (ops) => { batches.push(ops); return original(ops); };
  const { store } = await make({ adapter });
  await store.saveDay('2026-10-07', [SLOT]);
  batches.length = 0;

  await store.applyResponse(parsedResponse({ entries: { '2026-10-07': remoteDay([SLOT]) } }),
    store.snapshotDirty(), TODAY);

  assert.equal(batches.length, 1);
  assert.ok(batches[0].some((op) => op.store === 'meta' && op.value.token === 'T1'));
  assert.ok(batches[0].some((op) => op.store === 'entries' && op.key === '2026-10-07'));
});

test('a new store over the same adapter restores days and meta', async () => {
  const { store, adapter } = await make();
  await store.saveDay('2026-10-07', [SLOT]);
  await store.setMeta({ categories: ['X'] });

  const again = new Store(adapter, clock());
  await again.load();

  assert.deepEqual(again.getDay('2026-10-07').slots, [SLOT]);
  assert.equal(again.getDay('2026-10-07').dirty, true);
  assert.equal(again.getMeta().token, 'T0');
  assert.deepEqual(again.getMeta().categories, ['X']);
});

test('load() ignores junk records instead of crashing', async () => {
  const adapter = createMemoryAdapter();
  await adapter.batch([
    { store: 'entries', op: 'put', key: 'kein-datum', value: { entry: { slots: [] } } },
    { store: 'entries', op: 'put', key: '2026-10-07', value: 'text' },
    { store: 'entries', op: 'put', key: '2026-10-06', value: { entry: { slots: 'x' }, dirty_version: 1 } },
    { store: 'entries', op: 'put', key: '2026-10-05', value: {
      entry: { slots: [SLOT], modified_at: '2026-10-05T10:00:00Z', device_id: 'x', deleted: false },
      dirty_version: 2, synced_version: 1, error: null } },
    { store: 'meta', op: 'put', key: 'meta', value: 'kaputt' },
  ]);

  const store = new Store(adapter, clock());
  await store.load();

  assert.deepEqual(store.days(), ['2026-10-05']);
  assert.equal(store.getDay('2026-10-05').dirty, true);
  assert.deepEqual(store.getMeta().categories, []);                 // Standardwerte statt Müll
});

test('getMeta returns a copy', async () => {
  const { store } = await make();
  store.getMeta().token = 'gestohlen';
  assert.equal(store.getMeta().token, 'T0');
});

test('a write error from the adapter is thrown to the caller', async () => {
  const adapter = createMemoryAdapter();
  const { store } = await make({ adapter });
  adapter.batch = async () => { throw new Error('QuotaExceededError'); };
  await assert.rejects(store.saveDay('2026-10-07', [SLOT]), /QuotaExceededError/);
});

test('keys like __proto__ cannot pollute the prototype', async () => {
  const { store } = await make();
  await store.applyResponse(parsedResponse({
    entries: JSON.parse('{"__proto__": {"slots": [], "modified_at": "x", "device_id": "x", "deleted": false}}'),
  }), store.snapshotDirty(), TODAY);
  assert.equal({}.slots, undefined);
  assert.equal(store.getDay('__proto__'), null);
});

test('a day edited during the request is kept even far outside the window and even if the response lists it', async () => {
  const { store, now } = await make();
  await store.saveDay('2026-01-15', [SLOT]);
  const snapshot = store.snapshotDirty();
  now.advance(5000);
  await store.saveDay('2026-01-15', [OTHER]);                       // während des Sendens

  await store.applyResponse(parsedResponse({ entries: { '2026-01-15': remoteDay([SLOT]) } }), snapshot, TODAY);

  assert.deepEqual(store.getDay('2026-01-15').slots, [OTHER]);
  assert.equal(store.getDay('2026-01-15').dirty, true);
});
