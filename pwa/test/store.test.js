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
    excluded: false, window_days: 90, window_max: 365, entries: {}, conflicts: [], categories: ['Projekt'],
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

test('excluded: a sent day the desktop dropped stays dirty so the next sync can send it again', async () => {
  // Das Handy schickt nur Tage, die es seit dem letzten Abgleich geändert hat — nie einen
  // veralteten. Verwirft der Desktop sie wegen `excluded` (Kompaktierung), ist das keine
  // Wiederbelebung, sondern echte Arbeit: sie darf nicht lokal gelöscht werden. Der nächste
  // Abgleich nimmt sie an (last_pull_at liegt dann hinter dem Watermark).
  const { store } = await make();
  await store.saveDay('2026-09-01', [SLOT]);
  const snapshot = store.snapshotDirty();
  await store.applyResponse(parsedResponse({ excluded: true }), snapshot, TODAY);
  assert.deepEqual(store.getDay('2026-09-01').slots, [SLOT]);
  assert.equal(store.getDay('2026-09-01').dirty, true);
  assert.equal(store.getMeta().excluded, true);
});

test('a sent day the desktop dropped without excluded (settled tombstone) is removed when unchanged', async () => {
  const { store } = await make();
  await store.saveDay('2026-09-01', [SLOT]);
  await store.clearDay('2026-09-01');
  const snapshot = store.snapshotDirty();
  await store.applyResponse(parsedResponse(), snapshot, TODAY);
  assert.equal(store.getDay('2026-09-01'), null);
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

test('the response stores the defaults and the desktop info, and an older desktop clears them (#288)', async () => {
  const { store } = await make();
  const defaults = { pause: 30, weekdays: {}, category_times: {} };
  const desktop = { name: 'PC', version: '1.24.0', platform: 'Linux' };

  await store.applyResponse(parsedResponse({ defaults, desktop }), store.snapshotDirty(), TODAY);
  assert.deepEqual(store.getMeta().defaults, defaults);
  assert.deepEqual(store.getMeta().desktop, desktop);

  await store.applyResponse(parsedResponse({ defaults: null, desktop: { name: '', version: '', platform: '' } }),
    store.snapshotDirty(), TODAY);
  assert.equal(store.getMeta().defaults, null);
});

test('a store without the new meta fields starts with no defaults', async () => {
  const { store } = await make();
  assert.equal(store.getMeta().defaults, null);
  assert.deepEqual(store.getMeta().desktop, { name: '', version: '', platform: '' });
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

test('an error for an older version does not mark the newer edit', async () => {
  const { store, now } = await make();
  await store.saveDay('2026-10-07', [SLOT]);
  const { versions } = store.snapshotDirty();
  now.advance(5000);
  await store.saveDay('2026-10-07', [OTHER]);                       // Änderung während des Sendens

  await store.markDayError('2026-10-07', 'abgelehnt', versions['2026-10-07']);

  assert.equal(store.getDay('2026-10-07').error, null);
  assert.deepEqual(Object.keys(store.snapshotDirty().entries), ['2026-10-07']);
});

test('an error for the current version marks the day', async () => {
  const { store } = await make();
  await store.saveDay('2026-10-07', [SLOT]);
  const { versions } = store.snapshotDirty();
  await store.markDayError('2026-10-07', 'abgelehnt', versions['2026-10-07']);
  assert.equal(store.getDay('2026-10-07').error, 'abgelehnt');
});

test('saving the same slots again clears an error so the user can retry without changing anything', async () => {
  const { store } = await make();
  await store.saveDay('2026-10-07', [SLOT]);
  await store.markDayError('2026-10-07', 'abgelehnt');

  await store.saveDay('2026-10-07', [SLOT]);

  assert.equal(store.getDay('2026-10-07').error, null);
  assert.deepEqual(Object.keys(store.snapshotDirty().entries), ['2026-10-07']);
});

test('a stamp far in the future on the desktop does not push the phone stamp into the future', async () => {
  // Der Server lehnt modified_at mehr als 15 Minuten in der Zukunft ab. Stand der Tag mit
  // einem vorauslaufenden Stempel (Gerät mit falscher Uhr) in der Antwort, würde „+1 s“
  // jede Änderung daran zum dauerhaften 422 machen.
  const { store, now } = await make();
  await store.applyResponse(parsedResponse({ entries: {
    '2026-10-07': remoteDay([OTHER], { modified_at: '2026-10-08T14:00:00Z' }) } }),
    store.snapshotDirty(), TODAY);

  await store.saveDay('2026-10-07', [SLOT]);

  const stamp = Date.parse(store.getDay('2026-10-07').modified_at);
  assert.ok(stamp - now().getTime() <= 14 * 60 * 1000, store.getDay('2026-10-07').modified_at);
});

test('a broken stored stamp does not make the day uneditable', async () => {
  const { store } = await make();
  await store.applyResponse(parsedResponse({ entries: {
    '2026-10-07': remoteDay([OTHER], { modified_at: 'x' }) } }), store.snapshotDirty(), TODAY);
  await store.saveDay('2026-10-07', [SLOT]);
  assert.equal(store.getDay('2026-10-07').modified_at, '2026-10-08T12:00:00Z');
});

test('the meta knows the device key and the request counter, empty by default', async () => {
  const { store } = await make();
  assert.equal(store.getMeta().key, '');
  assert.equal(store.getMeta().seq, 0);
});

test('the device key and the counter survive a reload together with the token', async () => {
  const adapter = createMemoryAdapter();
  const first = new Store(adapter, () => new Date('2026-10-08T12:00:00Z'));
  await first.load();
  await first.setMeta({ key: 'B'.repeat(43), seq: 7, token: 'T0' });
  const second = new Store(adapter, () => new Date('2026-10-08T12:00:00Z'));
  await second.load();
  assert.deepEqual([second.getMeta().key, second.getMeta().seq, second.getMeta().token], ['B'.repeat(43), 7, 'T0']);
});

test('automatic updates are off by default and the choice survives a restart (#290)', async () => {
  const adapter = createMemoryAdapter();
  const { store } = await make({ adapter });
  assert.equal(store.getMeta().auto_update, false);

  await store.setMeta({ auto_update: true });
  const again = new Store(adapter, clock());
  await again.load();
  assert.equal(again.getMeta().auto_update, true);
});

test('the wish defaults to 90, survives a restart, and the maximum comes from the response (#250)', async () => {
  const adapter = createMemoryAdapter();
  const { store } = await make({ adapter });
  assert.equal(store.getMeta().window_wish, 90);
  assert.equal(store.getMeta().window_max, null);

  await store.setMeta({ window_wish: 365 });
  await store.applyResponse(parsedResponse({ window_max: 180, window_days: 180 }), store.snapshotDirty(), TODAY);
  const again = new Store(adapter, clock());
  await again.load();
  assert.equal(again.getMeta().window_wish, 365);          // der Wunsch bleibt, auch über der Obergrenze
  assert.equal(again.getMeta().window_max, 180);
});

test('a shrinking window removes clean days outside it but keeps unsent ones (#250)', async () => {
  const { store } = await make();
  await store.applyResponse(parsedResponse({ window_days: 365, window_max: 365, entries: {
    '2026-03-02': remoteDay(), '2026-09-30': remoteDay() } }), store.snapshotDirty(), TODAY);
  const snapshot = store.snapshotDirty();                    // ... der Abgleich läuft los ...
  await store.saveDay('2026-03-03', [SLOT]);                 // ... und währenddessen entsteht ein Tag, weit zurück
  assert.deepEqual(store.days().sort(), ['2026-03-02', '2026-03-03', '2026-09-30']);

  await store.applyResponse(parsedResponse({ window_days: 90, window_max: 90, entries: {
    '2026-09-30': remoteDay() } }), snapshot, TODAY);

  assert.deepEqual(store.days().sort(), ['2026-03-03', '2026-09-30']);   // sauber → weg, unübertragen → bleibt
});

test('the maximum is unknown until an answer arrived, and an answer without it means an old desktop (#292)', async () => {
  const { store } = await make();
  assert.equal(store.getMeta().window_max_known, false);
  assert.equal(store.getMeta().window_wish_acked, 90);

  await store.applyResponse(parsedResponse({ window_max: null, window_wish_sent: 120 }), store.snapshotDirty(), TODAY);

  assert.equal(store.getMeta().window_max_known, true);
  assert.equal(store.getMeta().window_max, null);
  assert.equal(store.getMeta().window_wish_acked, 120);
});

// --- Reservierungen ---------------------------------------------------------------------------------

const RES = { start: '09:00', end: '12:00', kategorie: 'Projekt' };
const RES_TODAY = '2026-10-13';
const parsedWith = (reservations, over = {}) => parsedResponse({ reservations, ...over });
const emptySnapshot = (extra = {}) => ({ entries: {}, versions: {}, reservations: {}, reservationVersions: {}, ...extra });

test('saving a reservation marks it dirty, strips everything but the three fields and stamps it', async () => {
  const { store } = await make();
  await store.saveReservation('2026-10-20', [{ ...RES, pause: 30, gcal_event_id: 'x' }]);

  const day = store.getReservation('2026-10-20');
  assert.deepEqual(day.slots, [RES]);
  assert.equal(day.dirty, true);
  assert.equal(day.deleted, false);
  assert.match(day.modified_at, /^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$/);
  assert.deepEqual(store.reservationDates(), ['2026-10-20']);
});

test('saving identical reservation slots changes nothing', async () => {
  const { store } = await make();
  await store.saveReservation('2026-10-20', [RES]);
  const first = store.getReservation('2026-10-20');

  await store.saveReservation('2026-10-20', [{ ...RES }]);

  assert.equal(store.getReservation('2026-10-20').modified_at, first.modified_at);
});

test('saving invalid reservation slots throws and stores nothing', async () => {
  const { store } = await make();
  await assert.rejects(() => store.saveReservation('2026-10-20', [{ start: '12:00', end: '09:00', kategorie: '' }]));
  assert.deepEqual(store.reservationDates(), []);
});

test('clearing a confirmed reservation makes a dirty tombstone; clearing again is a no-op', async () => {
  const { store } = await make();
  await store.saveReservation('2026-10-20', [RES]);
  await store.applyResponse(parsedWith({ '2026-10-20': { slots: [RES], modified_at: '2026-10-13T12:00:00Z' } }),
    emptySnapshot(store.snapshotReservations()), RES_TODAY);
  await store.clearReservation('2026-10-20');
  const cleared = store.getReservation('2026-10-20');
  assert.equal(cleared.deleted, true);
  assert.deepEqual(cleared.slots, []);
  assert.equal(cleared.dirty, true);

  await store.clearReservation('2026-10-20');
  assert.equal(store.getReservation('2026-10-20').modified_at, cleared.modified_at);
});

test('the snapshot holds dirty reservations without a device id or a pause, newest first, and skips errors', async () => {
  const { store } = await make();
  await store.saveReservation('2026-10-20', [RES]);
  await store.saveReservation('2026-10-21', [RES]);
  await store.saveReservation('2026-10-22', [RES]);
  await store.markReservationError('2026-10-22', 'abgelehnt');
  await store.setMeta({ reservations_enabled: true });

  const snapshot = store.snapshotReservations();

  assert.deepEqual(Object.keys(snapshot.reservations).sort(), ['2026-10-20', '2026-10-21']);
  assert.deepEqual(Object.keys(snapshot.reservations['2026-10-20']).sort(), ['deleted', 'modified_at', 'slots']);
  assert.deepEqual(Object.keys(snapshot.reservationVersions).sort(), ['2026-10-20', '2026-10-21']);
  assert.equal(Object.keys(store.snapshotReservations(1).reservations).length, 1);
  assert.equal(store.errorCount(), 1);
});

test('a sent reservation that stayed unchanged is replaced by the desktop state and becomes clean', async () => {
  const { store } = await make();
  await store.saveReservation('2026-10-20', [RES]);
  const snapshot = emptySnapshot(store.snapshotReservations());

  await store.applyResponse(parsedWith({
    '2026-10-20': { slots: [RES], modified_at: '2026-10-13T12:00:00Z' } }), snapshot, RES_TODAY);

  const day = store.getReservation('2026-10-20');
  assert.equal(day.dirty, false);
  assert.equal(day.modified_at, '2026-10-13T12:00:00Z');
  assert.equal(store.getMeta().reservations_enabled, true);
});

test('a reservation edited while the request was in flight stays local and dirty', async () => {
  const { store } = await make();
  await store.saveReservation('2026-10-20', [RES]);
  const snapshot = emptySnapshot(store.snapshotReservations());
  await store.saveReservation('2026-10-20', [{ ...RES, end: '13:00' }]);

  await store.applyResponse(parsedWith({
    '2026-10-20': { slots: [RES], modified_at: '2026-10-13T12:00:00Z' } }), snapshot, RES_TODAY);

  assert.equal(store.getReservation('2026-10-20').slots[0].end, '13:00');
  assert.equal(store.getReservation('2026-10-20').dirty, true);
});

test('a clean reservation the desktop no longer lists is removed inside the future window only', async () => {
  const { store } = await make();
  await store.applyResponse(parsedWith({
    '2026-10-20': { slots: [RES], modified_at: '2026-10-12T12:00:00Z' },
    '2027-10-14': { slots: [RES], modified_at: '2026-10-12T12:00:00Z' } }), emptySnapshot(), RES_TODAY);
  assert.deepEqual(store.reservationDates(), ['2026-10-20', '2027-10-14']);

  await store.applyResponse(parsedWith({}), emptySnapshot(), RES_TODAY);

  assert.deepEqual(store.reservationDates(), ['2027-10-14']);      // hinter heute + 365 gehört dem Desktop nicht
});

test('past reservations are cleaned up: clean ones by absence, sent dirty ones the desktop dropped', async () => {
  const { store } = await make();
  await store.applyResponse(parsedWith({ '2026-10-20': { slots: [RES], modified_at: '2026-10-12T12:00:00Z' } }),
    emptySnapshot(), RES_TODAY);
  await store.saveReservation('2026-10-21', [RES]);                       // wird dirty
  const snapshot = emptySnapshot(store.snapshotReservations());

  // zehn Tage später: beide sind vergangen, der Desktop liefert sie nicht mehr
  await store.applyResponse(parsedWith({}), snapshot, '2026-10-23');

  assert.deepEqual(store.reservationDates(), []);
});

test('a dirty reservation that was not part of the request survives a response without it', async () => {
  const { store } = await make();
  await store.saveReservation('2026-10-20', [RES]);

  await store.applyResponse(parsedWith({}), emptySnapshot(), RES_TODAY);

  assert.equal(store.getReservation('2026-10-20').dirty, true);
});

test('a desktop without reservations changes nothing locally and switches the feature off', async () => {
  const { store } = await make();
  await store.applyResponse(parsedWith({ '2026-10-20': { slots: [RES], modified_at: '2026-10-12T12:00:00Z' } }),
    emptySnapshot(), RES_TODAY);
  await store.saveReservation('2026-10-21', [RES]);

  await store.applyResponse(parsedWith(null), emptySnapshot(), RES_TODAY);

  assert.equal(store.getMeta().reservations_enabled, false);
  assert.deepEqual(store.reservationDates(), ['2026-10-20', '2026-10-21']);
  assert.equal(store.getReservation('2026-10-21').dirty, true);
});

test('reservations survive a reload', async () => {
  const { store, adapter } = await make();
  await store.saveReservation('2026-10-20', [RES]);

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

test('the pending count includes dirty days and dirty reservations', async () => {
  const { store } = await make();
  await store.saveDay('2026-10-07', [SLOT]);
  await store.saveReservation('2026-10-20', [RES]);
  await store.setMeta({ reservations_enabled: true });

  assert.equal(store.pendingCount(), 2);
});

test('a reservation beyond the horizon is refused on the phone', async () => {
  const { store, now } = await make({ now: clock('2026-10-13T10:00:00Z') });
  await assert.rejects(() => store.saveReservation('2027-12-01', [RES]), /365 Tage/);
  assert.deepEqual(store.reservationDates(), []);
  assert.ok(now);
});

test('clearing a reservation the desktop never confirmed just drops it', async () => {
  const { store } = await make();
  await store.saveReservation('2026-10-20', [RES]);

  await store.clearReservation('2026-10-20');

  assert.deepEqual(store.reservationDates(), []);                  // kein Tombstone ohne Gegenstelle
});

test('clearing a confirmed reservation still leaves a tombstone', async () => {
  const { store } = await make();
  await store.saveReservation('2026-10-20', [RES]);
  await store.applyResponse(parsedWith({ '2026-10-20': { slots: [RES], modified_at: '2026-10-13T12:00:00Z' } }),
    { ...emptySnapshot(store.snapshotReservations()) }, RES_TODAY);

  await store.clearReservation('2026-10-20');

  assert.equal(store.getReservation('2026-10-20').deleted, true);
});

test('a rejected reservation that is now in the past is cleaned up', async () => {
  const { store } = await make();
  await store.saveReservation('2026-10-15', [RES]);
  await store.markReservationError('2026-10-15', 'abgelehnt');

  await store.applyResponse(parsedWith({}), emptySnapshot(), '2026-10-16');

  assert.deepEqual(store.reservationDates(), []);
  assert.equal(store.errorCount(), 0);
});

test('with the feature off, reservations neither count as pending nor as rejected', async () => {
  const { store } = await make();
  await store.saveReservation('2026-10-20', [RES]);
  await store.markReservationError('2026-10-20', 'x');
  await store.setMeta({ reservations_enabled: true });
  assert.equal(store.pendingCount(), 1);                           // Funktion an: zählt
  await store.applyResponse(parsedWith(null), emptySnapshot(), RES_TODAY);

  assert.equal(store.pendingCount(), 0);
  assert.equal(store.errorCount(), 0);
});

// --- Kategorien-Block --------------------------------------------------------------------------------

const DEFAULTS = { pause: 0, weekdays: {}, category_times: { Projekt: { start: '09:00', end: '17:00', pause: 45 } } };
const withDesktop = (over = {}) => parsedResponse({
  categories: ['Projekt', 'Intern'], defaults: structuredClone(DEFAULTS),
  writable_settings: ['categories', 'category_times'], ...over });
const settingsSnapshot = (store) => ({ ...emptySnapshot(), ...(store.snapshotSettings() ?? {}) });

async function writable() {
  const made = await make();
  await made.store.applyResponse(withDesktop(), emptySnapshot(), RES_TODAY);
  return made;
}

test('saving categories changes the local view at once and marks the block dirty', async () => {
  const { store } = await writable();

  await store.saveCategories({ categories: ['Neu', 'Projekt'],
    category_times: { Projekt: { start: '08:00' } } });

  const meta = store.getMeta();
  assert.deepEqual(meta.categories, ['Neu', 'Projekt']);
  assert.deepEqual(meta.defaults.category_times, { Projekt: { start: '08:00' } });
  assert.equal(store.categoriesDirty(), true);
  assert.equal(store.pendingCount(), 1);
});

test('saving an unchanged block is a no-op', async () => {
  const { store } = await writable();
  await store.saveCategories({ categories: ['Projekt', 'Intern'], category_times: DEFAULTS.category_times });
  assert.equal(store.categoriesDirty(), false);
  assert.equal(store.getMeta().categories_edit, null);
});

test('an invalid block throws and changes nothing', async () => {
  const { store } = await writable();
  await assert.rejects(() => store.saveCategories({ categories: ['A', 'A'], category_times: {} }), /doppelt/);
  assert.deepEqual(store.getMeta().categories, ['Projekt', 'Intern']);
});

test('without writable_settings saving is refused', async () => {
  const { store } = await make();
  await store.applyResponse(withDesktop({ writable_settings: undefined }), emptySnapshot(), RES_TODAY);
  await assert.rejects(() => store.saveCategories({ categories: ['X'], category_times: {} }), /Desktop/);
  assert.equal(store.getMeta().settings_writable, false);
});

test('the snapshot carries both keys with one stamp and the version; clean or rejected blocks send nothing', async () => {
  const { store } = await writable();
  assert.equal(store.snapshotSettings(), null);
  await store.saveCategories({ categories: ['Neu'], category_times: {} });

  const snapshot = store.snapshotSettings();

  assert.deepEqual(Object.keys(snapshot.settings).sort(), ['categories', 'category_times']);
  assert.deepEqual(snapshot.settings.categories.value, ['Neu']);
  assert.equal(snapshot.settings.categories.modified_at, snapshot.settings.category_times.modified_at);
  assert.equal(snapshot.settingsVersion, 1);

  await store.markSettingsError('abgelehnt', snapshot.settingsVersion);
  assert.equal(store.snapshotSettings(), null);
  assert.equal(store.errorCount(), 1);
});

test('a confirmed block becomes clean and the desktop state replaces the local one', async () => {
  const { store } = await writable();
  await store.saveCategories({ categories: ['Neu'], category_times: {} });
  const snapshot = settingsSnapshot(store);

  await store.applyResponse(withDesktop({ categories: ['Neu'], defaults: { ...DEFAULTS, category_times: {} } }),
    snapshot, RES_TODAY);

  assert.equal(store.categoriesDirty(), false);
  assert.deepEqual(store.getMeta().categories, ['Neu']);
});

test('a block edited while the request was in flight stays local and dirty', async () => {
  const { store } = await writable();
  await store.saveCategories({ categories: ['Eins'], category_times: {} });
  const snapshot = settingsSnapshot(store);
  await store.saveCategories({ categories: ['Eins', 'Zwei'], category_times: {} });

  await store.applyResponse(withDesktop({ categories: ['Eins'], defaults: { ...DEFAULTS, category_times: {} } }),
    snapshot, RES_TODAY);

  assert.deepEqual(store.getMeta().categories, ['Eins', 'Zwei']);
  assert.equal(store.categoriesDirty(), true);
});

test('a dirty block that was not sent survives a response with other categories', async () => {
  const { store } = await writable();
  await store.saveCategories({ categories: ['Lokal'], category_times: {} });

  await store.applyResponse(withDesktop({ categories: ['Desktop'] }), emptySnapshot(), RES_TODAY);

  assert.deepEqual(store.getMeta().categories, ['Lokal']);
  assert.equal(store.categoriesDirty(), true);
});

test('other defaults still follow the desktop while the block is dirty', async () => {
  const { store } = await writable();
  await store.saveCategories({ categories: ['Lokal'], category_times: {} });

  await store.applyResponse(withDesktop({ defaults: { ...DEFAULTS, pause: 30 } }), emptySnapshot(), RES_TODAY);

  assert.equal(store.getMeta().defaults.pause, 30);
  assert.deepEqual(store.getMeta().defaults.category_times, {});
});

test('a desktop that drops writable_settings hides the block: it neither counts nor is sent', async () => {
  const { store } = await writable();
  await store.saveCategories({ categories: ['Lokal'], category_times: {} });

  await store.applyResponse(withDesktop({ writable_settings: undefined }), emptySnapshot(), RES_TODAY);

  assert.equal(store.pendingCount(), 0);
  assert.equal(store.snapshotSettings(), null);
  assert.equal(store.categoriesDirty(), true);                       // bleibt liegen für später
});

test('the category block survives a reload', async () => {
  const { store, adapter } = await writable();
  await store.saveCategories({ categories: ['Neu'], category_times: {} });

  const second = new Store(adapter);
  await second.load();

  assert.deepEqual(second.getMeta().categories, ['Neu']);
  assert.equal(second.categoriesDirty(), true);
});
