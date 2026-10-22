// pwa/test/sync.test.js
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

import { Store } from '../store.js';
import { createMemoryAdapter } from '../memory-adapter.js';
import { b64d, b64e, deviceKeys, isEnvelope, openEnvelope, pairKeys, seal } from '../crypto.js';
import {
  SKEW_WARN_MS, SyncClient, SyncError, classifyHttpError, classifyNetworkError, clockSkewMs,
  parseSyncResponse,
} from '../sync.js';

const fixture = (name) => JSON.parse(readFileSync(new URL(`./fixtures/${name}`, import.meta.url)));
const SLOT = { start: '08:00', end: '12:00', pause: 0, kategorie: 'Projekt' };
const NOW = '2026-10-08T12:00:00Z';
const RES = { start: '09:00', end: '12:00', kategorie: 'Projekt' };

const DEVICE_ID = '6f1c2b9e-3d4a-4b5c-8d7e-9f0a1b2c3d4e';
const CODE = 'K7M29QXA'.repeat(3) + 'K7M2';
const DEVICE_KEY = Uint8Array.from({ length: 32 }, (_, i) => 255 - i);
const KEY_TEXT = b64e(DEVICE_KEY);
const NEW_KEY = Uint8Array.from({ length: 32 }, (_, i) => i + 1);
const utf8 = (value) => new TextEncoder().encode(JSON.stringify(value));
const unjson = (bytes) => JSON.parse(new TextDecoder().decode(bytes));

/** Eine Antwort-Attrappe für `fetch`: `body` ist der **Klartext**; der Fake-Server verschlüsselt ihn
 *  (Erfolg immer, ein Fehler nur mit `sealed: true`, wie der echte Server nach dem Entschlüsseln). */
function reply(status, body, { sealed = false } = {}) {
  return { status, body, sealed };
}

/** Ein Fake-Server mit Verschlüsselung (Gegenstück zu src/mobile_routes.py): öffnet Anfragen an
 *  /v1/pair (mit dem Code) und /v1/sync (mit dem Geräteschlüssel), reicht den Klartext als `plain`
 *  an den Handler und verschlüsselt dessen Antwort. Alles andere (Ping) bleibt Klartext. */
function fakeFetch(handler, { deviceKey = DEVICE_KEY } = {}) {
  const calls = [];
  const fn = async (url, init) => {
    const path = new URL(url).pathname;
    const raw = init.body ? JSON.parse(init.body) : null;
    const call = { url, init, body: raw, plain: null, seq: null, envelope: raw };
    calls.push(call);
    let context = null;
    if (init.method === 'POST' && (path === '/v1/pair' || path === '/v1/sync')) {
      if (!isEnvelope(raw)) throw new Error(`Klartext-Anfrage an ${path}: ${init.body}`);
      const [requestKey, responseKey] = path === '/v1/pair' ? await pairKeys(CODE) : await deviceKeys(deviceKey);
      const aadDevice = path === '/v1/pair' ? '-' : DEVICE_ID;
      call.plain = unjson(await openEnvelope(requestKey, raw, { direction: 'req', method: 'POST', path, deviceId: aadDevice }));
      call.seq = raw.seq;
      context = { path, responseKey, deviceId: path === '/v1/pair' ? call.plain.device_id : DEVICE_ID, seq: raw.seq };
    }
    const result = await handler(url, init, calls.length, call);
    if (result instanceof Error) throw result;
    let body = result.body;
    if (context && result.body !== undefined && (result.status === 200 || result.sealed)) {
      const payload = result.status === 200 ? result.body : result.body;
      body = await seal(context.responseKey, { direction: 'res', method: 'POST', path: context.path,
        deviceId: context.deviceId, seq: context.seq, plaintext: utf8(payload) });
    }
    return {
      ok: result.status >= 200 && result.status < 300,
      status: result.status,
      json: async () => {
        if (body === undefined) throw new SyntaxError('kein JSON');
        return structuredClone(body);
      },
    };
  };
  fn.calls = calls;
  return fn;
}

const PAIR_ANSWER = () => ({ ...fixture('pair-response.json'), key: b64e(NEW_KEY) });

async function make({ handler = () => reply(200, fixture('sync-response.json')), paired = true, adapter } = {}) {
  const store = new Store(adapter ?? createMemoryAdapter(), () => new Date(NOW));
  await store.load();
  if (paired) {
    await store.setMeta({ device_id: DEVICE_ID, token: 'T0', key: KEY_TEXT, seq: 0,
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
    new Error('irgendwas')]) {
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

test('the example response carries the defaults and the desktop info (#288)', () => {
  const parsed = parseSyncResponse(fixture('sync-response.json'));
  assert.equal(parsed.defaults.pause, 30);
  assert.deepEqual(parsed.defaults.category_times.Projekt, { start: '09:00', end: '17:00', pause: 45 });
  assert.deepEqual(parsed.desktop, { name: 'Büro-PC', version: '1.24.0', platform: 'Linux' });
});

test('a response from an older desktop without defaults and desktop info is still accepted', () => {
  const doc = fixture('sync-response.json');
  delete doc.defaults;
  delete doc.desktop;
  const parsed = parseSyncResponse(doc);
  assert.equal(parsed.defaults, null);
  assert.deepEqual(parsed.desktop, { name: '', version: '', platform: '' });
});

test('garbage in defaults does not refuse the response', () => {
  const doc = fixture('sync-response.json');
  doc.defaults = 'kaputt';
  assert.equal(parseSyncResponse(doc).defaults, null);
});

const broken = (mutate) => {
  const doc = fixture('sync-response.json');
  mutate(doc);
  return doc;
};

for (const [name, doc] of [
  ['protocol 1', broken((d) => { d.protocol = 1; })],
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

test('pairing sends one sealed envelope, stores token, key and the permanent device id; no Authorization header', async () => {
  const { store, client, fetchFn } = await make({
    paired: false, handler: () => reply(200, PAIR_ANSWER()) });

  const result = await client.pair({ host: '192.168.1.20', port: 17654, code: CODE.toLowerCase(), deviceName: 'Pixel' });

  const call = fetchFn.calls[0];
  assert.equal(call.url, 'http://192.168.1.20:17654/v1/pair');
  assert.equal(call.init.method, 'POST');
  assert.equal('Authorization' in call.init.headers, false);
  assert.equal(call.init.headers['Content-Type'], 'application/json');
  assert.equal(call.init.credentials, 'omit');
  assert.equal(call.init.cache, 'no-store');
  assert.deepEqual(Object.keys(call.body).sort(), ['c', 'n', 'seq', 'v']);        // nichts im Klartext
  assert.equal(call.seq, 1);
  const wire = JSON.stringify(call.body);
  for (const secret of [CODE, 'Pixel', store.getMeta().device_id, 'device_name', 'code']) {
    assert.equal(wire.includes(secret), false, secret);
  }
  assert.deepEqual(shape(call.plain), shape(fixture('pair-request.json')));       // der Klartext hat die Form des Vertrags
  assert.equal(JSON.stringify(call.plain).includes(CODE), false);                 // der Code ist nur Schlüssel
  assert.equal(result.desktopName, 'Desktop');
  const meta = store.getMeta();
  assert.deepEqual(meta.address, { host: '192.168.1.20', port: 17654 });
  assert.equal(meta.token, fixture('pair-response.json').token);
  assert.equal(meta.key, b64e(NEW_KEY));
  assert.equal(meta.seq, 0);
  assert.equal(meta.desktop_name, 'Desktop');
  assert.equal(meta.window_days, 90);
  assert.match(meta.device_id, /^[A-Za-z0-9-]{8,64}$/);
  assert.equal(call.plain.device_id, meta.device_id);
});

test('a pair answer without a valid key is a protocol error and changes nothing', async () => {
  for (const key of [undefined, '', 'zu kurz', 'B'.repeat(42), 'B'.repeat(44), 5, `${'B'.repeat(42)}=`]) {
    const answer = PAIR_ANSWER();
    if (key === undefined) delete answer.key; else answer.key = key;
    const { store, client } = await make({ handler: () => reply(200, answer) });
    await assert.rejects(client.pair({ host: '192.168.1.20', port: 17654, code: CODE, deviceName: 'P' }),
      (e) => e.kind === 'protocol', String(key));
    assert.equal(store.getMeta().token, 'T0');
    assert.equal(store.getMeta().key, KEY_TEXT);
  }
});

test('a pair answer sealed with the wrong key is a crypto error and changes nothing', async () => {
  const { store, client } = await make({ handler: async () => ({
    status: 200, body: undefined, forged: true }) });
  const forging = async () => {
    const [, responseKey] = await pairKeys('A'.repeat(28));
    return seal(responseKey, { direction: 'res', method: 'POST', path: '/v1/pair', deviceId: DEVICE_ID, seq: 1,
      plaintext: utf8(PAIR_ANSWER()) });
  };
  const forged = await forging();
  const fetchFn = async () => ({ ok: true, status: 200, json: async () => forged });
  const attacked = new SyncClient({ store, fetchFn, now: () => new Date(NOW), timeoutMs: 1000 });
  await assert.rejects(attacked.pair({ host: '192.168.1.20', port: 17654, code: CODE, deviceName: 'P' }),
    (e) => e.kind === 'crypto');
  assert.equal(store.getMeta().token, 'T0');
  assert.equal(client instanceof SyncClient, true);
});

test('a plaintext pair answer is a protocol error', async () => {
  const { store } = await make({ paired: false });
  const fetchFn = async () => ({ ok: true, status: 200, json: async () => PAIR_ANSWER() });
  const client = new SyncClient({ store, fetchFn, now: () => new Date(NOW), timeoutMs: 1000 });
  await assert.rejects(client.pair({ host: '192.168.1.20', port: 17654, code: CODE, deviceName: 'P' }),
    (e) => e.kind === 'protocol');
  assert.equal(store.getMeta().token, '');
});

test('re-pairing keeps the device id and the unsent days', async () => {
  const { store, client } = await make({ handler: () => reply(200, PAIR_ANSWER()) });
  await store.saveDay('2026-10-07', [SLOT]);
  const before = store.getMeta().device_id;

  await client.pair({ host: '192.168.1.21', port: 17655, code: CODE, deviceName: 'Pixel' });

  assert.equal(store.getMeta().device_id, before);
  assert.deepEqual(store.getMeta().address, { host: '192.168.1.21', port: 17655 });
  assert.deepEqual(store.dirtyDates(), ['2026-10-07']);
});

test('pairing refuses a bad code or address before any request', async () => {
  const { client, fetchFn } = await make({ paired: false });
  await assert.rejects(client.pair({ host: '192.168.1.20', port: 17654, code: `${CODE.slice(0, -1)}0`, deviceName: 'P' }),
    (e) => e.kind === 'invalid_code');
  await assert.rejects(client.pair({ host: '8.8.8.8', port: 17654, code: CODE, deviceName: 'P' }),
    (e) => e.kind === 'address');
  assert.equal(fetchFn.calls.length, 0);
});

test('a refused pairing leaves token and address untouched', async () => {
  const { store, client } = await make({
    handler: () => reply(403, { error: { code: 'invalid_code', message: 'Der Code ist ungültig oder abgelaufen.' } }) });

  await assert.rejects(client.pair({ host: '192.168.1.20', port: 17654, code: CODE, deviceName: 'P' }),
    (e) => e.kind === 'invalid_code');

  assert.equal(store.getMeta().token, 'T0');
});

test('a malformed pair answer is a protocol error and changes nothing', async () => {
  const { store, client } = await make({ handler: () => reply(200, { token: 5 }) });
  await assert.rejects(client.pair({ host: '192.168.1.20', port: 17654, code: CODE, deviceName: 'P' }),
    (e) => e.kind === 'protocol');
  assert.equal(store.getMeta().token, 'T0');
});

// --- Abgleich --------------------------------------------------------------------------------------

test('a sync sends bearer, request shape and the dirty days, then applies the answer', async () => {
  // Der 16.10. ist am Desktop bekannt (bestätigt): nur dann schickt „leeren“ einen Tombstone.
  const adapter = createMemoryAdapter();
  await adapter.batch([{ store: 'reservations', op: 'put', key: '2026-10-16', value: {
    entry: { slots: [RES], modified_at: '2026-10-07T00:00:00Z', deleted: false },
    dirty_version: 1, synced_version: 1, error: null } }]);
  const { store, client, fetchFn } = await make({ adapter });
  await store.saveDay('2026-10-07', [SLOT]);
  await store.saveDay('2026-10-06', [SLOT]);
  await store.clearDay('2026-10-06');                                // Tombstone
  await store.saveReservation('2026-10-15', [RES]);
  await store.clearReservation('2026-10-16');                        // Tombstone der Reservierung
  await store.applyResponse(parseSyncResponse(fixture('sync-response.json')),   // Desktop bietet Kategorien an
    { entries: {}, versions: {}, reservations: {}, reservationVersions: {} }, '2026-10-08');
  await store.setMeta({ token: 'T0', last_pull_at: '' });          // die Hilfsantwort hat beides verstellt
  await store.saveCategories({ categories: ['Neu'], category_times: { Neu: { start: '09:00' } } });

  const result = await client.sync();

  const call = fetchFn.calls[0];
  assert.equal(call.url, 'http://192.168.1.20:17654/v1/sync');
  assert.equal(call.init.headers.Authorization, 'Bearer T0');
  assert.equal(call.init.targetAddressSpace, 'local');
  assert.ok(call.init.signal);
  assert.deepEqual(Object.keys(call.body).sort(), ['c', 'n', 'seq', 'v']);        // auf dem Draht nur der Umschlag
  for (const secret of ['2026-10-07', 'entries', 'Projekt', 'last_pull_at']) {
    assert.equal(JSON.stringify(call.body).includes(secret), false, secret);
  }
  const example = fixture('sync-request.json');
  assert.deepEqual(keysOf(call.plain), keysOf(example));
  assert.deepEqual(Object.keys(call.plain.entries).sort(), Object.keys(example.entries).sort());
  for (const date of Object.keys(example.entries)) {
    assert.deepEqual(keysOf(call.plain.entries[date]), keysOf(example.entries[date]), date);
  }
  assert.deepEqual(Object.keys(call.plain.reservations).sort(), Object.keys(example.reservations).sort());
  for (const date of Object.keys(example.reservations)) {
    assert.deepEqual(keysOf(call.plain.reservations[date]), keysOf(example.reservations[date]), date);
  }
  assert.deepEqual(Object.keys(call.plain.settings).sort(), Object.keys(example.settings).sort());
  for (const key of Object.keys(example.settings)) {
    assert.deepEqual(keysOf(call.plain.settings[key]), keysOf(example.settings[key]), key);
  }
  assert.deepEqual(call.plain.reservations['2026-10-15'].slots, [RES]);
  assert.equal(call.plain.reservations['2026-10-16'].deleted, true);
  assert.equal(call.plain.entries['2026-10-06'].deleted, true);
  assert.deepEqual(call.plain.entries['2026-10-06'].slots, []);
  assert.equal(call.plain.client_time, NOW);
  assert.equal(call.plain.protocol, 2);
  assert.deepEqual(result, { sent: 2, conflicts: 1, excluded: false });
  assert.equal(store.getMeta().token, fixture('sync-response.json').token);   // erneuert
  assert.deepEqual(store.dirtyDates(), []);
});

test('the request fixture matches what the store builds', async () => {
  const { store, client, fetchFn } = await make();
  await store.saveDay('2026-10-07', [SLOT]);
  await client.sync();
  const sent = fetchFn.calls[0].plain.entries['2026-10-07'];
  const example = fixture('sync-request.json').entries['2026-10-07'];
  assert.deepEqual(Object.keys(sent).sort(), Object.keys(example).sort());
  assert.deepEqual(sent.slots, example.slots);
});

test('a sync without anything to send still pulls', async () => {
  const { client, fetchFn } = await make();
  await client.sync();
  assert.deepEqual(fetchFn.calls[0].plain.entries, {});
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
  ['clock skew (sealed)', () => reply(409, { error: { code: 'clock_skew', message: 'x' } }, { sealed: true }), 'clock_skew', false],
  ['busy (sealed)', () => reply(503, { error: { code: 'busy', message: 'x' } }, { sealed: true }), 'transient', false],
  ['replay', () => reply(409, { error: { code: 'replay', message: 'x' } }), 'crypto', true],
  ['decrypt failed', () => reply(400, { error: { code: 'decrypt_failed', message: 'x' } }), 'crypto', true],
  ['encryption required', () => reply(401, { error: { code: 'encryption_required', message: 'x' } }), 'encryption', true],
  ['key unavailable', () => reply(503, { error: { code: 'key_unavailable', message: 'x' } }), 'transient', false],
  ['plaintext protocol refusal', () => reply(400, { error: { code: 'invalid_protocol', message: 'x' } }), 'protocol', false],
  ['broken answer', () => reply(200, { protocol: 1 }), 'protocol', false],
  ['html answer', () => reply(200, undefined), 'protocol', false],
  ['server error without json', () => reply(500, undefined), 'server', false],
]) {
  test(`${name}: the error is classified and no local day is lost`, async () => {
    const { store, client } = await make({ handler });
    await store.saveDay('2026-10-07', [SLOT]);
    await store.applyResponse({ protocol: 2, server_time: NOW, last_pull_at: NOW, excluded: false,
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
      return reply(422, { error: { code: 'invalid_entry', message: '2026-10-07: Endzeit muss nach Startzeit liegen' } }, { sealed: true });
    }
    return reply(200, fixture('sync-response.json'));
  } });
  await store.saveDay('2026-10-07', [SLOT]);
  await store.saveDay('2026-10-06', [SLOT]);

  await assert.rejects(client.sync(), (e) => e.kind === 'invalid_entry' && e.day === '2026-10-07');
  assert.equal(store.getDay('2026-10-07').error, '2026-10-07: Endzeit muss nach Startzeit liegen');
  assert.equal(store.getDay('2026-10-07').dirty, true);

  await client.sync();
  assert.deepEqual(Object.keys(fetchFn.calls[1].plain.entries), ['2026-10-06']);   // fehlerhafter Tag bleibt draußen
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

  assert.equal(batches.length, 2);                                   // erst der Zähler, dann die Antwort in EINER Transaktion
  assert.deepEqual(batches[0].map((op) => op.store), ['meta']);
  assert.equal(batches[0][0].value.seq, 1);
  assert.ok(batches[1].some((op) => op.store === 'meta' && op.value.token === fixture('sync-response.json').token));
  assert.ok(batches[1].some((op) => op.store === 'entries'));         // Token und Tage zusammen
});

// --- Erreichbarkeit --------------------------------------------------------------------------------

test('ping reports the clock skew and remembers it', async () => {
  const { store, client, fetchFn } = await make({ handler: () => reply(200, {
    protocol: 2, server_time: '2026-10-08T12:03:00Z', window_days: 90 }) });

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
    protocol: 2, server_time: '2026-10-08T12:00:30Z', window_days: 90 }) });
  assert.equal((await client.ping()).skewWarning, false);
});

test('a bad ping answer is a protocol error', async () => {
  const { client } = await make({ handler: () => reply(200, { protocol: 1 }) });
  await assert.rejects(client.ping(), (e) => e.kind === 'protocol');
});

test('re-pairing during a running sync discards the old answer', async () => {
  let release;
  const gate = new Promise((resolve) => { release = resolve; });
  const { store, client } = await make({ handler: async (url) => {
    if (url.endsWith('/v1/pair')) return reply(200, PAIR_ANSWER());
    await gate;
    return reply(200, fixture('sync-response.json'));
  } });
  await store.saveDay('2026-10-07', [SLOT]);

  const running = client.sync();
  await client.pair({ host: '192.168.1.99', port: 17655, code: CODE, deviceName: 'P' });
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
    return reply(422, { error: { code: 'invalid_entry', message: '2026-10-07: Endzeit muss nach Startzeit liegen' } }, { sealed: true });
  } });
  await store.saveDay('2026-10-07', [SLOT]);

  const running = client.sync();
  await store.saveDay('2026-10-07', [{ start: '07:00', end: '11:00', pause: 0, kategorie: '' }]);
  release();
  await assert.rejects(running, (e) => e.kind === 'invalid_entry');

  assert.equal(store.getDay('2026-10-07').error, null);
  assert.deepEqual(Object.keys(store.snapshotDirty().entries), ['2026-10-07']);
});

test('an error from a sync that was running while re-pairing is discarded, not thrown', async () => {
  let release;
  const gate = new Promise((resolve) => { release = resolve; });
  const { store, client } = await make({ handler: async (url) => {
    if (url.endsWith('/v1/pair')) return reply(200, PAIR_ANSWER());
    await gate;
    return reply(401, { error: { code: 'unauthorized', message: 'nein' } });
  } });
  await store.saveDay('2026-10-07', [SLOT]);

  const running = client.sync();
  await client.pair({ host: '192.168.1.99', port: 17655, code: CODE, deviceName: 'P' });
  release();
  const result = await running;

  assert.equal(result.discarded, true);
  assert.equal(store.getMeta().token, fixture('pair-response.json').token);
});


// --- Verschlüsselung des Abgleichs (#249) ---------------------------------------------------------------

test('the request counter is stored before the request goes out and grows with every sync', async () => {
  const seen = [];
  const { store, client } = await make({ handler: () => {
    seen.push(store.getMeta().seq);                      // zum Zeitpunkt des Sendens schon abgelegt
    return reply(200, fixture('sync-response.json'));
  } });

  await client.sync();
  await client.sync();

  assert.deepEqual(seen, [1, 2]);
  assert.equal(store.getMeta().seq, 2);
});

test('a failed request still consumed its counter: it is never used again', async () => {
  let attempt = 0;
  const { store, client, fetchFn } = await make({ handler: () => {
    attempt += 1;
    return attempt === 1 ? new TypeError('Failed to fetch') : reply(200, fixture('sync-response.json'));
  } });

  await assert.rejects(client.sync(), (e) => e.kind === 'offline');
  await client.sync();

  assert.deepEqual(fetchFn.calls.map((call) => call.seq), [1, 2]);
  assert.equal(store.getMeta().seq, 2);
});

test('the sealed request carries the counter and binds device, path and direction', async () => {
  const { client, fetchFn } = await make();
  await client.sync();
  const call = fetchFn.calls[0];
  const [requestKey, responseKey] = await deviceKeys(DEVICE_KEY);
  const parts = { direction: 'req', method: 'POST', path: '/v1/sync', deviceId: DEVICE_ID };
  assert.equal(call.body.seq, 1);
  await openEnvelope(requestKey, call.body, parts);                                  // geht
  await assert.rejects(openEnvelope(responseKey, call.body, parts));                  // falscher Schlüssel
  await assert.rejects(openEnvelope(requestKey, call.body, { ...parts, path: '/v1/ping' }));
  await assert.rejects(openEnvelope(requestKey, call.body, { ...parts, deviceId: 'phone-0002' }));
});

test('a sealed error is opened and classified by its inner code, with the day', async () => {
  const { store, client } = await make({ handler: () => reply(422, { error: {
    code: 'invalid_entry', message: '2026-10-07: Endzeit muss nach Startzeit liegen' } }, { sealed: true }) });
  await store.saveDay('2026-10-07', [SLOT]);
  await assert.rejects(client.sync(), (e) => e.kind === 'invalid_entry' && e.day === '2026-10-07' && e.status === 422);
  assert.equal(store.getDay('2026-10-07').error, '2026-10-07: Endzeit muss nach Startzeit liegen');
});

test('an error envelope that does not open is a crypto error, not a classified server error', async () => {
  const { store } = await make();
  await store.saveDay('2026-10-07', [SLOT]);
  const forged = await seal(new Uint8Array(32), { direction: 'res', method: 'POST', path: '/v1/sync',
    deviceId: DEVICE_ID, seq: 1, plaintext: utf8({ error: { code: 'invalid_entry', message: '2026-10-07: x' } }) });
  const fetchFn = async () => ({ ok: false, status: 422, json: async () => forged });
  const client = new SyncClient({ store, fetchFn, now: () => new Date(NOW), timeoutMs: 1000 });
  await assert.rejects(client.sync(), (e) => e.kind === 'crypto' && e.needsRepair === true);
  assert.equal(store.getDay('2026-10-07').error, null);                                // nichts markiert
  assert.deepEqual(store.dirtyDates(), ['2026-10-07']);
});

test('an answer sealed for another request counter is a crypto error and changes nothing', async () => {
  const { store } = await make();
  await store.saveDay('2026-10-07', [SLOT]);
  const [, responseKey] = await deviceKeys(DEVICE_KEY);
  const wrongSeq = await seal(responseKey, { direction: 'res', method: 'POST', path: '/v1/sync',
    deviceId: DEVICE_ID, seq: 99, plaintext: utf8(fixture('sync-response.json')) });
  const fetchFn = async () => ({ ok: true, status: 200, json: async () => wrongSeq });
  const client = new SyncClient({ store, fetchFn, now: () => new Date(NOW), timeoutMs: 1000 });
  await assert.rejects(client.sync(), (e) => e.kind === 'crypto');
  assert.equal(store.getMeta().token, 'T0');
  assert.deepEqual(store.dirtyDates(), ['2026-10-07']);
});

test('a plaintext answer to a sync is refused: the token inside must not be trusted', async () => {
  const { store } = await make();
  await store.saveDay('2026-10-07', [SLOT]);
  const fetchFn = async () => ({ ok: true, status: 200, json: async () => fixture('sync-response.json') });
  const client = new SyncClient({ store, fetchFn, now: () => new Date(NOW), timeoutMs: 1000 });
  await assert.rejects(client.sync(), (e) => e.kind === 'protocol');
  assert.equal(store.getMeta().token, 'T0');
  assert.deepEqual(store.dirtyDates(), ['2026-10-07']);
});

test('a phone without a device key must pair again and sends nothing', async () => {
  const { store, client, fetchFn } = await make();
  await store.setMeta({ key: '' });
  await assert.rejects(client.sync(), (e) => e.kind === 'encryption' && e.needsRepair === true);
  assert.equal(fetchFn.calls.length, 0);
});

test('the response is opened with the key of the request, not with a key replaced meanwhile', async () => {
  let release;
  const gate = new Promise((resolve) => { release = resolve; });
  const { store, client } = await make({ handler: async (url) => {
    if (url.endsWith('/v1/pair')) return reply(200, PAIR_ANSWER());
    await gate;
    return reply(200, fixture('sync-response.json'));
  } });
  const running = client.sync();
  await client.pair({ host: '192.168.1.99', port: 17655, code: CODE, deviceName: 'P' });
  release();
  assert.equal((await running).discarded, true);
  assert.equal(store.getMeta().key, b64e(NEW_KEY));                                   // der neue Schlüssel bleibt
  assert.equal(store.getMeta().seq, 0);                                               // und sein Zähler
});

test('the key is never part of an error message or the stored error of a day', async () => {
  const { store, client } = await make({ handler: () => reply(422, { error: {
    code: 'invalid_entry', message: '2026-10-07: x' } }, { sealed: true }) });
  await store.saveDay('2026-10-07', [SLOT]);
  const error = await client.sync().catch((e) => e);
  for (const text of [error.message, store.getDay('2026-10-07').error, JSON.stringify(error)]) {
    assert.equal(String(text).includes(KEY_TEXT), false);
  }
  assert.equal(b64d(KEY_TEXT).length, 32);
});

for (const [code, status] of [['invalid_entry', 422], ['clock_skew', 409], ['busy', 503]]) {
  test(`a plaintext ${code} is never believed: the server only sends it sealed`, async () => {
    // Ein Angreifer im WLAN kann eine Klartext-Antwort fälschen. Würde die PWA `invalid_entry`
    // glauben, markierte sie einen Tag als abgelehnt und sendete ihn nicht mehr.
    const { store, client } = await make({ handler: () => reply(status, { error: {
      code, message: '2026-10-07: gefälscht' } }) });              // Klartext, nicht sealed
    await store.saveDay('2026-10-07', [SLOT]);

    await assert.rejects(client.sync(), (e) => e.kind === 'protocol' && e.day === null && e.needsRepair === false);

    assert.equal(store.getDay('2026-10-07').error, null);          // nichts markiert
    assert.deepEqual(Object.keys(store.snapshotDirty().entries), ['2026-10-07']);   // geht weiter mit
  });
}

test('plaintext errors the server really sends before decrypting are still classified', async () => {
  for (const [status, code, kind] of [[401, 'token_expired', 'repair'], [401, 'encryption_required', 'encryption'],
    [409, 'replay', 'crypto'], [400, 'decrypt_failed', 'crypto'], [503, 'key_unavailable', 'transient']]) {
    const { client } = await make({ handler: () => reply(status, { error: { code, message: 'x' } }) });
    await assert.rejects(client.sync(), (e) => e.kind === kind, code);
  }
});

test('classifyHttpError keeps the protocol number the desktop names (#290)', () => {
  const body = (supported) => ({ error: { code: 'invalid_protocol', message: 'x', supported_protocol: supported } });
  assert.equal(classifyHttpError(400, body(3)).supportedProtocol, 3);
  for (const bad of [undefined, null, 'x', 1.5, -2, 0, 99999]) {
    assert.equal(classifyHttpError(400, body(bad)).supportedProtocol, null, String(bad));
  }
  assert.equal(classifyHttpError(500, { error: { code: 'internal_error', message: 'x' } }).supportedProtocol, null);
});

test('the request carries the window wish of the phone (#250)', async () => {
  const { store, client, fetchFn } = await make();
  await store.setMeta({ window_wish: 180 });

  await client.sync();

  assert.equal(fetchFn.calls.at(-1).plain.window_days, 180);
});

test('a fresh phone wishes the default window', async () => {
  const { client, fetchFn } = await make();
  await client.sync();
  assert.equal(fetchFn.calls.at(-1).plain.window_days, 90);
});

test('parseSyncResponse reads the maximum tolerantly', () => {
  assert.equal(parseSyncResponse(fixture('sync-response.json')).window_max, 365);
  for (const bad of [undefined, null, 0, -1, 'x', 1.5, 99999, true]) {
    const copy = fixture('sync-response.json');
    if (bad === undefined) delete copy.window_max_days; else copy.window_max_days = bad;
    assert.equal(parseSyncResponse(copy).window_max, null, String(bad));
  }
});

test('a timeout is its own kind, so the message can point at the history size (#292)', () => {
  const result = classifyNetworkError(new DOMException('x', 'TimeoutError'));
  assert.equal(result.kind, 'timeout');
  assert.equal(result.retryable, true);
  assert.equal(result.needsRepair, false);
});

test('a sync records which wish the answer belongs to and that the desktop has answered (#292)', async () => {
  const { store, client } = await make();
  await store.setMeta({ window_wish: 180 });
  assert.equal(store.getMeta().window_wish_acked, 90);
  assert.equal(store.getMeta().window_max_known, false);

  await client.sync();

  assert.equal(store.getMeta().window_wish_acked, 180);
  assert.equal(store.getMeta().window_max_known, true);
});

test('an old desktop answer still marks the maximum as known (and absent)', async () => {
  const doc = fixture('compat/sync-response-pre-250.json');
  const { store, client } = await make({ handler: () => reply(200, doc) });

  await client.sync();

  assert.equal(store.getMeta().window_max_known, true);
  assert.equal(store.getMeta().window_max, null);
});

// --- Mehr als 400 nicht übertragene Tage (#262) -----------------------------------------------------

test('more than 400 untransferred days go out in chunks within one sync, newest first', async () => {
  const { store, client, fetchFn } = await make();
  const dates = Array.from({ length: 450 }, (_, i) => {
    const day = new Date(Date.UTC(2025, 0, 1 + i));
    return day.toISOString().slice(0, 10);
  });
  for (const date of dates) await store.saveDay(date, [SLOT]);

  const result = await client.sync();

  const sent = fetchFn.calls.filter((c) => c.url.endsWith('/v1/sync')).map((c) => Object.keys(c.plain.entries));
  assert.deepEqual(sent.map((chunk) => chunk.length), [400, 50]);
  assert.ok(sent[0].includes(dates.at(-1)) && !sent[1].includes(dates.at(-1)));   // zuerst die neuesten
  assert.equal(new Set(sent.flat()).size, 450);                                   // jeder Tag genau einmal
  assert.equal(result.sent, 450);
  assert.deepEqual(store.dirtyDates(), []);
});

test('a failing later chunk keeps the first one applied and the rest untransferred', async () => {
  let call = 0;
  const { store, client } = await make({ handler: () => (++call === 1
    ? reply(200, fixture('sync-response.json'))
    : reply(503, { error: { code: 'busy', message: 'beschäftigt' } }, { sealed: true })) });
  const dates = Array.from({ length: 450 }, (_, i) => new Date(Date.UTC(2025, 0, 1 + i)).toISOString().slice(0, 10));
  for (const date of dates) await store.saveDay(date, [SLOT]);

  await assert.rejects(() => client.sync(), SyncError);

  assert.equal(store.dirtyDates().length, 50);          // 400 sind durch, 50 warten auf den nächsten Lauf
});

test('with `excluded` the sent days stay open, yet no chunk is sent twice', async () => {
  const { store, client, fetchFn } = await make({ handler: () => reply(200, { ...fixture('sync-response.json'), excluded: true }) });
  const dates = Array.from({ length: 450 }, (_, i) => new Date(Date.UTC(2025, 0, 1 + i)).toISOString().slice(0, 10));
  for (const date of dates) await store.saveDay(date, [SLOT]);

  await client.sync();

  const sent = fetchFn.calls.filter((c) => c.url.endsWith('/v1/sync')).map((c) => Object.keys(c.plain.entries));
  assert.deepEqual(sent.map((chunk) => chunk.length), [400, 50]);
});

test('exactly 400 untransferred days need one request, not two', async () => {
  const { store, client, fetchFn } = await make();
  for (let i = 0; i < 400; i += 1) await store.saveDay(new Date(Date.UTC(2025, 0, 1 + i)).toISOString().slice(0, 10), [SLOT]);

  await client.sync();

  assert.equal(fetchFn.calls.filter((c) => c.url.endsWith('/v1/sync')).length, 1);
});

// --- Inhalte der Antwort prüfen (#262) --------------------------------------------------------------

test('foreign values in slots, stamps and conflict versions never reach the store as they are', () => {
  const doc = fixture('sync-response.json');
  doc.entries['2026-10-07'].modified_at = 'x';
  doc.entries['2026-10-07'].slots = [{ start: 5, end: null, pause: 'viel', kategorie: { a: 1 }, extra: '<b>' }, 'kaputt', null];
  doc.conflicts[0].versions = [{ device: 7, name: ['x'], modified_at: 'nie', slots: 'kein Array', extra: 1 }, 'text'];

  const parsed = parseSyncResponse(doc);

  assert.equal(parsed.entries['2026-10-07'].modified_at, '');
  assert.deepEqual(parsed.entries['2026-10-07'].slots, [{ start: '', end: '', pause: 0, kategorie: '' }]);
  assert.deepEqual(parsed.conflicts[0].versions, [{ device: '', name: '', modified_at: '', slots: [] }]);
});

test('valid values pass through unchanged', () => {
  const doc = fixture('sync-response.json');

  const parsed = parseSyncResponse(doc);

  assert.deepEqual(parsed.entries['2026-10-07'], doc.entries['2026-10-07']);
  assert.deepEqual(parsed.conflicts[0].versions, doc.conflicts[0].versions);
});

for (const [name, change] of [
  ['expires_at without a stamp', (d) => { d.expires_at = 'morgen'; }],
  ['window_days of zero', (d) => { d.window_days = 0; }],
  ['window_days absurdly high', (d) => { d.window_days = 1e9; }],
]) {
  test(`pairing refuses an answer with ${name}`, async () => {
    const answer = PAIR_ANSWER();
    change(answer);
    const { client } = await make({ paired: false, handler: () => reply(200, answer) });

    await assert.rejects(client.pair({ host: '192.168.1.20', port: 17654, code: CODE, deviceName: 'P' }),
      (error) => error.kind === 'protocol');
  });
}

// --- Reservierungen ---------------------------------------------------------------------------------

test('a response without reservations parses to null: the feature stays hidden', () => {
  assert.equal(parseSyncResponse(fixture('compat/sync-response-pre-reservations.json')).reservations, null);
});

test('reservations in the response are cleaned: three slot fields, valid stamps, active days only', () => {
  const raw = { ...fixture('sync-response.json'), reservations: {
    '2026-10-15': { slots: [{ start: '09:00', end: '12:00', kategorie: 'Projekt', pause: 99, gcal_event_id: 'x' }],
      modified_at: '2026-10-08T11:00:00Z', deleted: false },
    '2026-10-16': { slots: [], modified_at: '2026-10-08T11:00:00Z', deleted: false },
    kaputt: { slots: [{ start: '09:00', end: '12:00', kategorie: '' }], modified_at: 'x' },
    '2026-10-17': 'kein Objekt',
  } };

  assert.deepEqual(parseSyncResponse(raw).reservations, {
    '2026-10-15': { slots: [RES], modified_at: '2026-10-08T11:00:00Z' } });
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

test('a sync without dirty reservations sends no reservations field', async () => {
  const { store, client, fetchFn } = await make();
  await store.saveDay('2026-10-07', [SLOT]);

  await client.sync();

  assert.equal('reservations' in fetchFn.calls[0].plain, false);
});

test('reservations go out in the first request only, and the answer applies them', async () => {
  const { store, client, fetchFn } = await make();
  await store.saveReservation('2026-10-15', [RES]);

  await client.sync();

  assert.deepEqual(Object.keys(fetchFn.calls[0].plain.reservations), ['2026-10-15']);
  assert.equal(store.getMeta().reservations_enabled, true);
  assert.equal(store.getReservation('2026-10-15').dirty, false);
});

test('a 422 for a reservation day marks only that reservation; the next sync goes through', async () => {
  let n = 0;
  const { store, client, fetchFn } = await make({ handler: () => {
    n += 1;
    return n === 1
      ? reply(422, { error: { code: 'invalid_entry', message: 'Reservierung 2026-10-15: kaputt.' } }, { sealed: true })
      : reply(200, fixture('sync-response.json'));
  } });
  await store.saveReservation('2026-10-15', [RES]);

  await assert.rejects(() => client.sync(), (error) => error.kind === 'invalid_entry' && error.dayKind === 'reservation');
  assert.ok(store.getReservation('2026-10-15').error);

  await client.sync();
  assert.equal('reservations' in fetchFn.calls[1].plain, false);
});

test('a work-day 422 still marks the work day', async () => {
  let n = 0;
  const { store, client } = await make({ handler: () => {
    n += 1;
    return n === 1
      ? reply(422, { error: { code: 'invalid_entry', message: '2026-10-07: kaputt.' } }, { sealed: true })
      : reply(200, fixture('sync-response.json'));
  } });
  await store.saveDay('2026-10-07', [SLOT]);

  await assert.rejects(() => client.sync(), (error) => error.dayKind === 'entry');
  assert.ok(store.getDay('2026-10-07').error);
});

// --- Einstellungen ----------------------------------------------------------------------------------

test('the response lists the writable settings; a response without the field gives an empty list', () => {
  assert.deepEqual(parseSyncResponse(fixture('sync-response.json')).writable_settings, ['categories', 'category_times']);
  assert.deepEqual(parseSyncResponse(fixture('compat/sync-response-pre-settings.json')).writable_settings, []);
  assert.deepEqual(parseSyncResponse({ ...fixture('sync-response.json'), writable_settings: ['x', 5] }).writable_settings, ['x']);
});

test('a rejected setting is told apart from a rejected day', () => {
  const reject = (message) => classifyHttpError(422, { error: { code: 'invalid_entry', message } });
  for (const [message, key] of [
    ['Einstellung categories: höchstens 100 Kategorien.', 'categories'],
    ['Einstellung category_times Foo: pause muss eine ganze Zahl von 0 bis 1440 sein.', 'category_times'],
  ]) {
    const error = reject(message);
    assert.deepEqual([error.setting, error.day, error.dayKind], [key, null, null], message);
  }
  assert.equal(reject('2026-10-07: kaputt').setting, null);
});

test('a dirty category block goes out in the first request only, with one stamp for both keys', async () => {
  const { store, client, fetchFn } = await make();
  await store.applyResponse(parseSyncResponse(fixture('sync-response.json')),
    { entries: {}, versions: {}, reservations: {}, reservationVersions: {} }, '2026-10-08');
  await store.saveCategories({ categories: ['Neu'], category_times: { Neu: { start: '09:00' } } });

  await client.sync();

  const sent = fetchFn.calls[0].plain.settings;
  assert.deepEqual(Object.keys(sent).sort(), ['categories', 'category_times']);
  assert.deepEqual(sent.categories.value, ['Neu']);
  assert.equal(sent.categories.modified_at, sent.category_times.modified_at);
  assert.equal(store.categoriesDirty(), false);
});

test('a sync without a dirty block sends no settings field', async () => {
  const { store, client, fetchFn } = await make();
  await store.saveDay('2026-10-07', [SLOT]);
  await client.sync();
  assert.equal('settings' in fetchFn.calls[0].plain, false);
});

test('a 422 for the block marks only the block; the next sync goes through without it', async () => {
  let n = 0;
  const { store, client, fetchFn } = await make({ handler: () => {
    n += 1;
    return n === 1
      ? reply(422, { error: { code: 'invalid_entry', message: 'Einstellung categories: höchstens 100 Kategorien.' } }, { sealed: true })
      : reply(200, fixture('sync-response.json'));
  } });
  await store.applyResponse(parseSyncResponse(fixture('sync-response.json')),
    { entries: {}, versions: {}, reservations: {}, reservationVersions: {} }, '2026-10-08');
  await store.saveCategories({ categories: ['Neu'], category_times: {} });

  await assert.rejects(() => client.sync(), (error) => error.kind === 'invalid_entry' && error.setting === 'categories');
  assert.equal(store.getMeta().categories_edit.error !== null, true);

  await client.sync();
  assert.equal('settings' in fetchFn.calls[1].plain, false);
});

test('a 422 in the per-entry form also marks the block; the next sync goes through without it', async () => {
  let n = 0;
  const { store, client, fetchFn } = await make({ handler: () => {
    n += 1;
    return n === 1
      ? reply(422, { error: { code: 'invalid_entry', message: 'Einstellung category_times Foo: pause muss eine ganze Zahl von 0 bis 1440 sein.' } }, { sealed: true })
      : reply(200, fixture('sync-response.json'));
  } });
  await store.applyResponse(parseSyncResponse(fixture('sync-response.json')),
    { entries: {}, versions: {}, reservations: {}, reservationVersions: {} }, '2026-10-08');
  await store.saveCategories({ categories: ['Foo'], category_times: { Foo: { start: '09:00' } } });

  await assert.rejects(() => client.sync(), (error) => error.setting === 'category_times');
  assert.equal(store.getMeta().categories_edit.error !== null, true);

  await client.sync();
  assert.equal('settings' in fetchFn.calls[1].plain, false);
});

// --- Erinnerungen (#331) ----------------------------------------------------------------------------

const REMINDERS = fixture('reminders-contract.json').response_reminders;
const withReminders = (value) => ({ ...fixture('sync-response.json'), reminders: value });

test('a response of a desktop before the reminders has no reminders block', () => {
  const doc = fixture('compat/sync-response-pre-reminders.json');
  assert.ok(!('reminders' in doc));
  assert.equal(parseSyncResponse(doc).reminders, null);
});

test('the reminders block is read as the desktop sends it', () => {
  assert.deepEqual(parseSyncResponse(withReminders(REMINDERS)).reminders, REMINDERS);
});

test('a reminders block that is not an object counts as absent', () => {
  for (const bad of [undefined, null, 5, 'x', [1]]) assert.equal(parseSyncResponse(withReminders(bad)).reminders, null, String(bad));
});

test('unusable parts of the reminders block switch that part off instead of failing the sync', () => {
  const parsed = parseSyncResponse(withReminders({
    reservation: { enabled: true, minutes_before: -5 }, send: { enabled: 'ja', at: 'bald' } })).reminders;
  assert.deepEqual(parsed, { reservation: { enabled: false, minutes_before: 0 }, send: { enabled: false, at: [] } });
  assert.deepEqual(parseSyncResponse(withReminders({})).reminders,
    { reservation: { enabled: false, minutes_before: 0 }, send: { enabled: false, at: [] } });
});

test('send times are valid stamps, unique, sorted and at most 200', () => {
  const at = ['2026-12-01T07:00:00Z', 'kaputt', '2026-11-02T07:00:00Z', '2026-12-01T07:00:00Z', 7,
    ...Array.from({ length: 300 }, (_, i) => new Date(Date.UTC(2027, 0, 1, 0, i)).toISOString().replace(/\.\d+Z$/, 'Z'))];
  const parsed = parseSyncResponse(withReminders({ send: { enabled: true, at } })).reminders.send.at;
  assert.equal(parsed.length, 200);
  assert.deepEqual(parsed.slice(0, 2), ['2026-11-02T07:00:00Z', '2026-12-01T07:00:00Z']);
  assert.deepEqual(parsed, [...parsed].sort());
});

test('minutes before is a whole number from 0 to 1440', () => {
  const minutes = (value) => parseSyncResponse(withReminders({ reservation: { enabled: true, minutes_before: value } }))
    .reminders.reservation.minutes_before;
  assert.equal(minutes(0), 0);
  assert.equal(minutes(1440), 1440);
  assert.equal(minutes(1441), 0);
  assert.equal(minutes(7.5), 0);
});

test('the store keeps the last block and forgets it when the desktop stops sending one', async () => {
  const { store } = await make();
  const empty = { entries: {}, versions: {}, reservations: {}, reservationVersions: {} };
  await store.applyResponse(parseSyncResponse(withReminders(REMINDERS)), empty, '2026-10-08');
  assert.deepEqual(store.getMeta().reminders, REMINDERS);
  await store.applyResponse(parseSyncResponse(fixture('compat/sync-response-pre-reminders.json')), empty, '2026-10-08');
  assert.equal(store.getMeta().reminders, null);
});

async function pushOf(setup) {
  const { store, client, fetchFn } = await make();
  const empty = { entries: {}, versions: {}, reservations: {}, reservationVersions: {} };
  await store.applyResponse(parseSyncResponse(withReminders(setup.block)), empty, '2026-10-08');
  await store.setMeta({ token: 'T0', last_pull_at: '', relay_secret: setup.secret });
  await client.sync();
  return fetchFn.calls[0].plain;
}

test('the relay secret goes to the desktop only after it has sent a reminders block', async () => {
  const secret = fixture('reminders-contract.json').request_push.relay_secret;
  assert.deepEqual((await pushOf({ block: REMINDERS, secret })).push, { relay_secret: secret });
  assert.ok(!('push' in await pushOf({ block: undefined, secret })));
  assert.ok(!('push' in await pushOf({ block: REMINDERS, secret: '' })));
});

test('the request before the reminders had no push field and the live example still has none', () => {
  assert.ok(!('push' in fixture('compat/sync-request-pre-reminders.json')));
  assert.ok(!('push' in fixture('sync-request.json')));
});
