// pwa/test/debug-log.test.js
import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
  DEFAULT_RETENTION_DAYS,
  MAX_ENTRIES,
  RETENTION_CHOICES,
  createDebugLog,
  deliverExport,
  errorEvent,
  formatEntry,
  formatExport,
  syncEvent,
} from '../debug-log.js';

const DAY = 86_400_000;
const NOW = new Date('2026-11-06T14:02:11.789Z');

// Attrappe des Speichers aus Task 3: Ids vergibt der Speicher, `all` liefert aufsteigend.
function fakeStore({ failAdd = false } = {}) {
  const rows = [];
  const config = new Map();
  let nextId = 1;
  return {
    rows,
    async add(entry) {
      if (failAdd) throw new Error('quota');
      rows.push({ id: nextId++, ...entry });
    },
    async all() {
      return rows.map((r) => ({ ...r }));
    },
    async remove(ids) {
      for (const id of ids) {
        const i = rows.findIndex((r) => r.id === id);
        if (i >= 0) rows.splice(i, 1);
      }
    },
    async clear() {
      rows.length = 0;
    },
    async getConfig(key) {
      return config.get(key);
    },
    async setConfig(key, value) {
      config.set(key, value);
    },
  };
}

const at = (daysAgo) => new Date(NOW.getTime() - daysAgo * DAY).toISOString().replace(/\.\d{3}Z$/, 'Z');

test('constants', () => {
  assert.deepEqual(RETENTION_CHOICES, [1, 7, 30]);
  assert.equal(DEFAULT_RETENTION_DAYS, 7);
  assert.equal(MAX_ENTRIES, 500);
});

test('errorEvent scrubs context and detail and validates the name', () => {
  assert.deepEqual(errorEvent('Update-Suche', new TypeError('Failed https://x.example/a')), {
    kind: 'error',
    fields: { context: 'Update-Suche', name: 'TypeError', detail: 'Failed <url>' },
  });
  assert.deepEqual(errorEvent('Kontext 10.0.0.1', 'kaputt'), {
    kind: 'error',
    fields: { context: 'Kontext <ip>', name: '', detail: 'kaputt' },
  });
  const odd = Object.assign(new Error('x'), { name: 'bad name!' });
  assert.equal(errorEvent('c', odd).fields.name, '');
});

test('syncEvent keeps only the allow-listed fields', () => {
  assert.deepEqual(syncEvent({ result: 'ok', ms: 412, sent: 3, received: 5, conflicts: 0, window: 14, device: 'Max' }), {
    kind: 'sync',
    fields: { result: 'ok', ms: 412, sent: 3, received: 5, conflicts: 0, window: 14 },
  });
  assert.deepEqual(syncEvent({ result: 'Bad Value!', ms: -1, sent: NaN }).fields, {
    result: 'error', ms: 0, sent: 0, received: 0, conflicts: 0, window: 0,
  });
});

test('retention defaults to 7 days and rejects other values', async () => {
  const log = createDebugLog({ store: fakeStore(), now: () => NOW });
  assert.equal(await log.retentionDays(), 7);
  await assert.rejects(log.setRetentionDays(3), RangeError);
  assert.equal(await log.retentionDays(), 7);
});

test('prune drops entries older than the retention time', async () => {
  const store = fakeStore();
  const log = createDebugLog({ store, now: () => NOW });
  await store.add({ at: at(8), kind: 'error', fields: { context: 'alt' } });
  await store.add({ at: at(6), kind: 'error', fields: { context: 'neu' } });
  await log.prune();
  assert.deepEqual((await store.all()).map((r) => r.fields.context), ['neu']);
});

test('setRetentionDays stores the value and prunes at once', async () => {
  const store = fakeStore();
  const log = createDebugLog({ store, now: () => NOW });
  await store.add({ at: at(2), kind: 'error', fields: { context: 'alt' } });
  await log.setRetentionDays(1);
  assert.equal(await store.getConfig('log_retention_days'), 1);
  assert.equal(await log.retentionDays(), 1);
  assert.equal((await store.all()).length, 0);
});

test('the entry cap keeps the newest 500', async () => {
  const log = createDebugLog({ store: fakeStore(), now: () => NOW });
  for (let i = 0; i <= MAX_ENTRIES; i += 1) await log.recordError(`c${i}`, 'x');
  const entries = await log.entries();
  assert.equal(entries.length, 500);
  assert.equal(entries[0].fields.context, 'c500');
  assert.ok(!entries.some((e) => e.fields.context === 'c0'));
});

test('a failing store falls back to memory and never throws', async () => {
  const log = createDebugLog({ store: fakeStore({ failAdd: true }), now: () => NOW });
  assert.equal(log.isPersistent(), true);
  await log.recordError('Kontext', new Error('x'));
  assert.equal(log.isPersistent(), false);
  const entries = await log.entries();
  assert.equal(entries.length, 1);
  assert.equal(entries[0].at, '2026-11-06T14:02:11Z');
  assert.equal(entries[0].fields.detail, 'x');
});

test('hostile error objects do not throw', async () => {
  const log = createDebugLog({ store: fakeStore(), now: () => NOW });
  const circular = { name: 'Error' };
  circular.message = circular;
  circular.self = circular;
  const getter = { get message() { throw new Error('boom'); }, get name() { throw new Error('boom'); } };
  await log.recordError('a', circular);
  await log.recordError('b', getter);
  await log.recordSync(null);
  assert.equal((await log.entries()).length, 3);
});

test('formatEntry', () => {
  const error = { at: '2026-11-06T14:02:11Z', kind: 'error', fields: { context: 'Update-Suche', name: 'TypeError', detail: 'x' } };
  assert.equal(formatEntry(error), '2026-11-06T14:02:11Z WARN Update-Suche: TypeError: x');
  assert.equal(formatEntry({ ...error, fields: { context: 'Update-Suche', name: '', detail: 'x' } }), '2026-11-06T14:02:11Z WARN Update-Suche: x');
  const sync = { at: '2026-11-06T14:02:11Z', kind: 'sync', fields: { result: 'ok', ms: 412, sent: 3, received: 5, conflicts: 0, window: 14 } };
  assert.equal(formatEntry(sync), '2026-11-06T14:02:11Z INFO Abgleich ok, 412 ms, gesendet 3, empfangen 5, Konflikte 0, Fenster 14');
});

test('formatExport keeps info lines, lists newest first and scrubs entries again', () => {
  const entries = [
    { at: '2026-11-06T14:00:00Z', kind: 'error', fields: { context: 'neu', name: '', detail: 'bei 192.168.1.5' } },
    { at: '2026-11-05T14:00:00Z', kind: 'error', fields: { context: 'alt', name: '', detail: 'y' } },
  ];
  const text = formatExport({ info: [{ label: 'Build', value: '12/1.27.0 (a1b2c3d)' }], entries });
  const lines = text.split('\n');
  assert.equal(lines[0], 'Build: 12/1.27.0 (a1b2c3d)');
  assert.equal(lines[1], '');
  assert.equal(lines[2], '2026-11-06T14:00:00Z WARN neu: bei <ip>');
  assert.equal(lines[3], '2026-11-05T14:00:00Z WARN alt: y');
});

test('deliverExport', async () => {
  let downloads = 0;
  const download = () => { downloads += 1; };
  assert.equal(await deliverExport('t', { canShare: () => false, share: async () => {}, download }), 'downloaded');
  assert.equal(downloads, 1);
  const abort = async () => { throw new DOMException('x', 'AbortError'); };
  assert.equal(await deliverExport('t', { canShare: () => true, share: abort, download }), 'cancelled');
  assert.equal(downloads, 1);
  const broken = async () => { throw new Error('nope'); };
  assert.equal(await deliverExport('t', { canShare: () => true, share: broken, download }), 'downloaded');
  assert.equal(downloads, 2);
  assert.equal(await deliverExport('t', { canShare: () => true, share: async () => {}, download }), 'shared');
  assert.equal(downloads, 2);
});

test('clear in fallback mode still empties the stored entries', async () => {
  const store = fakeStore({ failAdd: true });
  store.rows.push({ id: 7, at: at(0), kind: 'error', fields: { context: 'c', name: '', detail: 'alt' } });
  const log = createDebugLog({ store, now: () => NOW });
  await log.recordError('c', new Error('x'));   // add scheitert: Wechsel in den Speicher
  assert.equal(log.isPersistent(), false);
  await log.clear();
  assert.equal(store.rows.length, 0);
  assert.deepEqual(await log.entries(), []);
});

test('clear survives a failing store.clear', async () => {
  const store = fakeStore({ failAdd: true });
  store.clear = async () => { throw new Error('gone'); };
  const log = createDebugLog({ store, now: () => NOW });
  await log.recordError('c', new Error('x'));
  assert.equal(await log.clear(), false);       // der Speicher blieb ungeleert: ehrlich melden
  assert.deepEqual(await log.entries(), []);    // der Speicher der Seite ist trotzdem leer
});

test('clear resolves to true when the store was cleared', async () => {
  const log = createDebugLog({ store: fakeStore(), now: () => NOW });
  await log.recordError('c', new Error('x'));
  assert.equal(await log.clear(), true);
});

test('foreign error names stay as the sync result, garbage does not', () => {
  assert.equal(syncEvent({ result: 'TypeError' }).fields.result, 'TypeError');
  assert.equal(syncEvent({ result: 'client_error' }).fields.result, 'client_error');
  assert.equal(syncEvent({ result: 'Bad Value!' }).fields.result, 'error');
  assert.equal(syncEvent({ result: '1abc' }).fields.result, 'error');
});

test('error names never carry dots (no host names through the name field)', () => {
  assert.equal(errorEvent('c', { name: 'xveyn.github.io', message: 'x' }).fields.name, '');
  assert.equal(errorEvent('c', { name: 'TypeError', message: 'x' }).fields.name, 'TypeError');
});

test('end to end: the whole export contains none of the hostile substrings', async () => {
  const store = fakeStore();
  const log = createDebugLog({ store, now: () => NOW });
  const hostile = [
    'Failed https://updates.example.org/wpush/v2/AbCdEf0123456789?token=SECRETTOKEN#frag',
    'connect [::1]:8080 and fe80::1ff:fe23:4567:890a refused',
    'host:port meinrechner.local:17654 down',
    'mail max.mustermann@example.com',
    'am 2026-11-05T08:15:00Z und 05.11.2026 um 08:15 bis 17:30',
    'file /home/max/projekte/zeit.json and C:\\Users\\Max\\zeit.json',
    `Unexpected token 'S', "Sende Max" is not valid JSON`,
  ];
  for (const message of hostile) await log.recordError('ctx', { name: 'SyntaxError', message });
  await log.recordSync({ result: 'ok', ms: 5, sent: 1, extra: 'max@example.com', note: '/home/max/x/y', url: 'https://a.b/c' });
  const text = formatExport({ info: [{ label: 'Build', value: '1' }], entries: await log.entries() });
  const entriesPart = text.split('\n\n')[1];
  for (const bad of ['updates.example.org', 'SECRETTOKEN', 'frag', '::1', 'fe80', '8080', 'meinrechner', 'local:',
    '17654', 'max.mustermann', 'example.com', '2026-11-05', '05.11.2026', '08:15', '17:30', '/home/max', 'C:\\Users',
    'zeit.json', 'Sende Max', 'AbCdEf0123456789', 'a.b/c', 'extra']) {
    assert.ok(!entriesPart.includes(bad), `${bad} im Export: ${entriesPart}`);
  }
  for (const placeholder of ['<url>', '<ip>', '<mail>', '<datum>', '<zeit>', '<pfad>', '<text>']) {
    assert.ok(entriesPart.includes(placeholder), `${placeholder} fehlt: ${entriesPart}`);
  }
});
