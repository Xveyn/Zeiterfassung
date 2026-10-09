// pwa/test/sync.test.js
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

import { Store } from '../store.js';
import { createMemoryAdapter } from '../memory-adapter.js';
import {
  SKEW_WARN_MS, SyncClient, SyncError, classifyHttpError, classifyNetworkError, clockSkewMs,
  parseSyncResponse,
} from '../sync.js';

const fixture = (name) => JSON.parse(readFileSync(new URL(`./fixtures/${name}`, import.meta.url)));
const SLOT = { start: '08:00', end: '12:00', pause: 0, kategorie: 'Projekt' };
const NOW = '2026-10-08T12:00:00Z';

/** Eine Antwort-Attrappe für `fetch`. */
function reply(status, body) {
  return { status, body };
}

function fakeFetch(handler) {
  const calls = [];
  const fn = async (url, init) => {
    calls.push({ url, init, body: init.body ? JSON.parse(init.body) : null });
    const result = await handler(url, init, calls.length);
    if (result instanceof Error) throw result;
    return {
      ok: result.status >= 200 && result.status < 300,
      status: result.status,
      json: async () => {
        if (result.body === undefined) throw new SyntaxError('kein JSON');
        return structuredClone(result.body);
      },
    };
  };
  fn.calls = calls;
  return fn;
}

async function make({ handler = () => reply(200, fixture('sync-response.json')), paired = true, adapter } = {}) {
  const store = new Store(adapter ?? createMemoryAdapter(), () => new Date(NOW));
  await store.load();
  if (paired) {
    await store.setMeta({ device_id: '6f1c2b9e-3d4a-4b5c-8d7e-9f0a1b2c3d4e', token: 'T0',
      address: { host: '192.168.1.20', port: 17654 } });
  }
  const fetchFn = fakeFetch(handler);
  const client = new SyncClient({ store, fetchFn, now: () => new Date(NOW), timeoutMs: 1000 });
  return { store, client, fetchFn };
}

const shape = (value) => {
  if (Array.isArray(value)) return value.length ? [shape(value[0])] : [];
  if (value !== null && typeof value === 'object') {
    return Object.fromEntries(Object.keys(value).sort().map((k) => [k, shape(value[k])]));
  }
  return typeof value;
};

const keysOf = (value) => Object.keys(value).sort();

// --- Fehler einordnen ------------------------------------------------------------------------------

for (const row of fixture('errors.json')) {
  test(`classify ${row.status} ${row.code}`, () => {
    const error = classifyHttpError(row.status, { error: { code: row.code, message: 'Text vom Server' } });
    assert.ok(error instanceof SyncError);
    assert.equal(error.kind, row.kind);
    assert.equal(error.needsRepair, row.needs_repair);
    assert.equal(error.retryable, row.retryable);
    assert.equal(error.status, row.status);
    assert.equal(error.code, row.code);
    assert.equal(error.message, 'Text vom Server');
  });
}

test('an unknown code falls back to the status range', () => {
  assert.equal(classifyHttpError(401, { error: { code: 'neu', message: 'x' } }).kind, 'repair');
  assert.equal(classifyHttpError(418, { error: { code: 'neu', message: 'x' } }).kind, 'client_error');
  assert.equal(classifyHttpError(502, { error: { code: 'neu', message: 'x' } }).kind, 'server');
  assert.equal(classifyHttpError(502, null).kind, 'server');
  assert.equal(classifyHttpError(401, 'kein Objekt').kind, 'repair');
  assert.equal(classifyHttpError(500, { error: 5 }).code, '');
});

test('an invalid_entry error carries the day from the message', () => {
  const error = classifyHttpError(422, { error: { code: 'invalid_entry', message: '2026-10-07: Endzeit muss nach Startzeit liegen' } });
  assert.equal(error.day, '2026-10-07');
  assert.equal(classifyHttpError(422, { error: { code: 'invalid_entry', message: "'x': kaputt" } }).day, null);
});

test('a missing answer is offline, whatever the reason', () => {
  for (const error of [new TypeError('Failed to fetch'), new DOMException('x', 'AbortError'),
    new DOMException('x', 'TimeoutError'), new Error('irgendwas')]) {
    const result = classifyNetworkError(error);
    assert.equal(result.kind, 'offline');
    assert.equal(result.retryable, true);
    assert.equal(result.needsRepair, false);
  }
});

// --- Antwort prüfen --------------------------------------------------------------------------------

test('the example response is accepted', () => {
  const parsed = parseSyncResponse(fixture('sync-response.json'));
  assert.equal(parsed.token.length, 43);
  assert.deepEqual(Object.keys(parsed.entries), ['2026-10-07', '2026-10-06']);
});

const broken = (mutate) => {
  const doc = fixture('sync-response.json');
  mutate(doc);
  return doc;
};

for (const [name, doc] of [
  ['protocol 2', broken((d) => { d.protocol = 2; })],
  ['no token', broken((d) => { delete d.token; })],
  ['token with spaces', broken((d) => { d.token = 'x y'; })],
  ['empty token', broken((d) => { d.token = ''; })],
  ['entries as list', broken((d) => { d.entries = []; })],
  ['bad date key', broken((d) => { d.entries = { 'kein-datum': d.entries['2026-10-07'] }; })],
  ['entry without slots', broken((d) => { delete d.entries['2026-10-07'].slots; })],
  ['slots not a list', broken((d) => { d.entries['2026-10-07'].slots = 'x'; })],
  ['deleted not a bool', broken((d) => { d.entries['2026-10-07'].deleted = 'nein'; })],
  ['modified_at not text', broken((d) => { d.entries['2026-10-07'].modified_at = 5; })],
  ['excluded not a bool', broken((d) => { d.excluded = 1; })],
  ['window_days zero', broken((d) => { d.window_days = 0; })],
  ['window_days huge', broken((d) => { d.window_days = 1e9; })],
  ['window_days float', broken((d) => { d.window_days = 90.5; })],
  ['categories not a list', broken((d) => { d.categories = 'x'; })],
  ['category not text', broken((d) => { d.categories = [1]; })],
  ['conflicts not a list', broken((d) => { d.conflicts = {}; })],
  ['conflict without versions', broken((d) => { delete d.conflicts[0].versions; })],
  ['conflict with bad date', broken((d) => { d.conflicts[0].date = 'x'; })],
  ['last_pull_at missing', broken((d) => { delete d.last_pull_at; })],
  ['server_time not a stamp', broken((d) => { d.server_time = 'gestern'; })],
  ['expires_at missing', broken((d) => { delete d.expires_at; })],
  ['not an object', 'text'],
  ['null', null],
  ['list', []],
]) {
  test(`parseSyncResponse refuses: ${name}`, () => {
    assert.throws(() => parseSyncResponse(doc), (error) => error instanceof SyncError && error.kind === 'protocol');
  });
}

test('parseSyncResponse drops unknown top-level fields', () => {
  const parsed = parseSyncResponse(broken((d) => { d.extra = { gefährlich: true }; }));
  assert.equal('extra' in parsed, false);
});

test('clock skew is server minus phone and warns from two minutes', () => {
  assert.equal(clockSkewMs('2026-10-08T12:00:00Z', new Date('2026-10-08T11:59:00Z')), 60000);
  assert.equal(clockSkewMs('2026-10-08T12:00:00Z', new Date('2026-10-08T12:01:00Z')), -60000);
  assert.equal(SKEW_WARN_MS, 120000);
  assert.equal(Number.isNaN(clockSkewMs('kaputt', new Date(NOW))), true);
});

// --- Koppeln ---------------------------------------------------------------------------------------

test('pairing stores address, token and the permanent device id; no Authorization header', async () => {
  const { store, client, fetchFn } = await make({
    paired: false, handler: () => reply(200, fixture('pair-response.json')) });

  const result = await client.pair({ host: '192.168.1.20', port: 17654, code: 'k7m2-9qxa', deviceName: 'Pixel' });

  const call = fetchFn.calls[0];
  assert.equal(call.url, 'http://192.168.1.20:17654/v1/pair');
  assert.equal(call.init.method, 'POST');
  assert.equal('Authorization' in call.init.headers, false);
  assert.equal(call.init.headers['Content-Type'], 'application/json');
  assert.equal(call.init.credentials, 'omit');
  assert.equal(call.init.cache, 'no-store');
  assert.equal(call.body.code, 'K7M29QXA');                         // normalisiert
  assert.deepEqual(shape(call.body), shape(fixture('pair-request.json')));
  assert.equal(result.desktopName, 'Desktop');
  const meta = store.getMeta();
  assert.deepEqual(meta.address, { host: '192.168.1.20', port: 17654 });
  assert.equal(meta.token, fixture('pair-response.json').token);
  assert.equal(meta.desktop_name, 'Desktop');
  assert.equal(meta.window_days, 90);
  assert.match(meta.device_id, /^[A-Za-z0-9-]{8,64}$/);
});

test('re-pairing keeps the device id and the unsent days', async () => {
  const { store, client } = await make({ handler: () => reply(200, fixture('pair-response.json')) });
  await store.saveDay('2026-10-07', [SLOT]);
  const before = store.getMeta().device_id;

  await client.pair({ host: '192.168.1.21', port: 17655, code: 'K7M2-9QXA', deviceName: 'Pixel' });

  assert.equal(store.getMeta().device_id, before);
  assert.deepEqual(store.getMeta().address, { host: '192.168.1.21', port: 17655 });
  assert.deepEqual(store.dirtyDates(), ['2026-10-07']);
});

test('pairing refuses a bad code or address before any request', async () => {
  const { client, fetchFn } = await make({ paired: false });
  await assert.rejects(client.pair({ host: '192.168.1.20', port: 17654, code: 'K7M2-9QX0', deviceName: 'P' }),
    (e) => e.kind === 'invalid_code');
  await assert.rejects(client.pair({ host: '8.8.8.8', port: 17654, code: 'K7M2-9QXA', deviceName: 'P' }),
    (e) => e.kind === 'address');
  assert.equal(fetchFn.calls.length, 0);
});

test('a refused pairing leaves token and address untouched', async () => {
  const { store, client } = await make({
    handler: () => reply(403, { error: { code: 'invalid_code', message: 'Der Code ist ungültig oder abgelaufen.' } }) });

  await assert.rejects(client.pair({ host: '192.168.1.20', port: 17654, code: 'K7M2-9QXA', deviceName: 'P' }),
    (e) => e.kind === 'invalid_code');

  assert.equal(store.getMeta().token, 'T0');
});

test('a malformed pair answer is a protocol error and changes nothing', async () => {
  const { store, client } = await make({ handler: () => reply(200, { token: 5 }) });
  await assert.rejects(client.pair({ host: '192.168.1.20', port: 17654, code: 'K7M2-9QXA', deviceName: 'P' }),
    (e) => e.kind === 'protocol');
  assert.equal(store.getMeta().token, 'T0');
});

// --- Abgleich --------------------------------------------------------------------------------------

test('a sync sends bearer, request shape and the dirty days, then applies the answer', async () => {
  const { store, client, fetchFn } = await make();
  await store.saveDay('2026-10-07', [SLOT]);
  await store.saveDay('2026-10-06', [SLOT]);
  await store.clearDay('2026-10-06');                                // Tombstone

  const result = await client.sync();

  const call = fetchFn.calls[0];
  assert.equal(call.url, 'http://192.168.1.20:17654/v1/sync');
  assert.equal(call.init.headers.Authorization, 'Bearer T0');
  assert.equal(call.init.targetAddressSpace, 'local');
  assert.ok(call.init.signal);
  const example = fixture('sync-request.json');
  assert.deepEqual(keysOf(call.body), keysOf(example));
  assert.deepEqual(Object.keys(call.body.entries).sort(), Object.keys(example.entries).sort());
  for (const date of Object.keys(example.entries)) {
    assert.deepEqual(keysOf(call.body.entries[date]), keysOf(example.entries[date]), date);
  }
  assert.equal(call.body.entries['2026-10-06'].deleted, true);
  assert.deepEqual(call.body.entries['2026-10-06'].slots, []);
  assert.equal(call.body.client_time, NOW);
  assert.equal(call.body.protocol, 1);
  assert.deepEqual(result, { sent: 2, conflicts: 1, excluded: false });
  assert.equal(store.getMeta().token, fixture('sync-response.json').token);   // erneuert
  assert.deepEqual(store.dirtyDates(), []);
});

test('the request fixture matches what the store builds', async () => {
  const { store, client, fetchFn } = await make();
  await store.saveDay('2026-10-07', [SLOT]);
  await client.sync();
  const sent = fetchFn.calls[0].body.entries['2026-10-07'];
  const example = fixture('sync-request.json').entries['2026-10-07'];
  assert.deepEqual(Object.keys(sent).sort(), Object.keys(example).sort());
  assert.deepEqual(sent.slots, example.slots);
});

test('a sync without anything to send still pulls', async () => {
  const { client, fetchFn } = await make();
  await client.sync();
  assert.deepEqual(fetchFn.calls[0].body.entries, {});
});

test('two sync calls at once send one request and share the result', async () => {
  const { client, fetchFn } = await make();
  const [a, b] = await Promise.all([client.sync(), client.sync()]);
  assert.equal(fetchFn.calls.length, 1);
  assert.deepEqual(a, b);
  await client.sync();                                              // danach wieder möglich
  assert.equal(fetchFn.calls.length, 2);
});

test('an unpaired phone cannot sync', async () => {
  const { client, fetchFn } = await make({ paired: false });
  await assert.rejects(client.sync(), (e) => e.kind === 'not_paired');
  assert.equal(fetchFn.calls.length, 0);
});

for (const [name, handler, kind, repair] of [
  ['offline', () => new TypeError('Failed to fetch'), 'offline', false],
  ['expired token', () => reply(401, { error: { code: 'token_expired', message: 'x' } }), 'repair', true],
  ['revoked token', () => reply(401, { error: { code: 'token_revoked', message: 'x' } }), 'repair', true],
  ['replaced token', () => reply(401, { error: { code: 'unauthorized', message: 'x' } }), 'repair', true],
  ['clock skew', () => reply(409, { error: { code: 'clock_skew', message: 'x' } }), 'clock_skew', false],
  ['busy', () => reply(503, { error: { code: 'busy', message: 'x' } }), 'transient', false],
  ['broken answer', () => reply(200, { protocol: 1 }), 'protocol', false],
  ['html answer', () => reply(200, undefined), 'protocol', false],
  ['server error without json', () => reply(500, undefined), 'server', false],
]) {
  test(`${name}: the error is classified and no local day is lost`, async () => {
    const { store, client } = await make({ handler });
    await store.saveDay('2026-10-07', [SLOT]);
    await store.applyResponse({ protocol: 1, server_time: NOW, last_pull_at: NOW, excluded: false,
      window_days: 90, entries: { '2026-10-05': { slots: [SLOT], modified_at: NOW, device_id: 'D', deleted: false } },
      conflicts: [], categories: [], token: 'T0', expires_at: NOW }, { entries: {}, versions: {} }, '2026-10-08');
    const metaBefore = store.getMeta();

    await assert.rejects(client.sync(), (error) => error instanceof SyncError && error.kind === kind
      && error.needsRepair === repair);

    assert.deepEqual(store.dirtyDates(), ['2026-10-07']);           // nichts verloren
    assert.notEqual(store.getDay('2026-10-05'), null);
    assert.equal(store.getMeta().token, metaBefore.token);          // Token unverändert
  });
}

test('a 422 marks only that day; the others sync on the next try', async () => {
  let attempt = 0;
  const { store, client, fetchFn } = await make({ handler: (url, init) => {
    attempt += 1;
    if (attempt === 1) {
      return reply(422, { error: { code: 'invalid_entry', message: '2026-10-07: Endzeit muss nach Startzeit liegen' } });
    }
    return reply(200, fixture('sync-response.json'));
  } });
  await store.saveDay('2026-10-07', [SLOT]);
  await store.saveDay('2026-10-06', [SLOT]);

  await assert.rejects(client.sync(), (e) => e.kind === 'invalid_entry' && e.day === '2026-10-07');
  assert.equal(store.getDay('2026-10-07').error, '2026-10-07: Endzeit muss nach Startzeit liegen');
  assert.equal(store.getDay('2026-10-07').dirty, true);

  await client.sync();
  assert.deepEqual(Object.keys(fetchFn.calls[1].body.entries), ['2026-10-06']);   // fehlerhafter Tag bleibt draußen
  assert.equal(store.getDay('2026-10-07').dirty, true);
});

test('a day edited during the request stays dirty after the answer', async () => {
  let release;
  const gate = new Promise((resolve) => { release = resolve; });
  const { store, client } = await make({ handler: async () => { await gate; return reply(200, fixture('sync-response.json')); } });
  await store.saveDay('2026-10-07', [SLOT]);

  const running = client.sync();
  await Promise.resolve();
  await store.saveDay('2026-10-07', [{ start: '07:00', end: '11:00', pause: 0, kategorie: '' }]);
  release();
  await running;

  assert.equal(store.getDay('2026-10-07').dirty, true);
  assert.equal(store.getDay('2026-10-07').slots[0].start, '07:00');
});

test('the token in the answer is stored together with the days', async () => {
  const adapter = createMemoryAdapter();
  const batches = [];
  const original = adapter.batch.bind(adapter);
  adapter.batch = async (ops) => { batches.push(ops); return original(ops); };
  const { client } = await make({ adapter });
  batches.length = 0;

  await client.sync();

  assert.equal(batches.length, 1);
  assert.ok(batches[0].some((op) => op.store === 'meta' && op.value.token === fixture('sync-response.json').token));
});

// --- Erreichbarkeit --------------------------------------------------------------------------------

test('ping reports the clock skew and remembers it', async () => {
  const { store, client, fetchFn } = await make({ handler: () => reply(200, {
    protocol: 1, server_time: '2026-10-08T12:03:00Z', window_days: 90 }) });

  const result = await client.ping();

  assert.equal(fetchFn.calls[0].init.method, 'GET');
  assert.equal(fetchFn.calls[0].url, 'http://192.168.1.20:17654/v1/ping');
  assert.equal(fetchFn.calls[0].init.headers.Authorization, 'Bearer T0');
  assert.equal(fetchFn.calls[0].init.body, undefined);
  assert.equal(result.skewMs, 180000);
  assert.equal(result.skewWarning, true);
  assert.equal(store.getMeta().server_time, '2026-10-08T12:03:00Z');
});

test('a ping with a small skew does not warn', async () => {
  const { client } = await make({ handler: () => reply(200, {
    protocol: 1, server_time: '2026-10-08T12:00:30Z', window_days: 90 }) });
  assert.equal((await client.ping()).skewWarning, false);
});

test('a bad ping answer is a protocol error', async () => {
  const { client } = await make({ handler: () => reply(200, { protocol: 2 }) });
  await assert.rejects(client.ping(), (e) => e.kind === 'protocol');
});

test('re-pairing during a running sync discards the old answer', async () => {
  let release;
  const gate = new Promise((resolve) => { release = resolve; });
  const { store, client } = await make({ handler: async (url) => {
    if (url.endsWith('/v1/pair')) return reply(200, fixture('pair-response.json'));
    await gate;
    return reply(200, fixture('sync-response.json'));
  } });
  await store.saveDay('2026-10-07', [SLOT]);

  const running = client.sync();
  await client.pair({ host: '192.168.1.99', port: 17655, code: 'K7M2-9QXA', deviceName: 'P' });
  release();
  const result = await running;

  assert.equal(result.discarded, true);
  const meta = store.getMeta();
  assert.equal(meta.token, fixture('pair-response.json').token);        // das neue Token bleibt
  assert.deepEqual(meta.address, { host: '192.168.1.99', port: 17655 });
  assert.deepEqual(store.dirtyDates(), ['2026-10-07']);                  // nichts als übertragen markiert
});

test('a 422 for a day that was edited meanwhile does not mark the new version', async () => {
  let release;
  const gate = new Promise((resolve) => { release = resolve; });
  const { store, client } = await make({ handler: async () => {
    await gate;
    return reply(422, { error: { code: 'invalid_entry', message: '2026-10-07: Endzeit muss nach Startzeit liegen' } });
  } });
  await store.saveDay('2026-10-07', [SLOT]);

  const running = client.sync();
  await store.saveDay('2026-10-07', [{ start: '07:00', end: '11:00', pause: 0, kategorie: '' }]);
  release();
  await assert.rejects(running, (e) => e.kind === 'invalid_entry');

  assert.equal(store.getDay('2026-10-07').error, null);
  assert.deepEqual(Object.keys(store.snapshotDirty().entries), ['2026-10-07']);
});
