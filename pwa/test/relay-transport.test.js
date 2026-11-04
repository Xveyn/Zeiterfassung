// pwa/test/relay-transport.test.js
import { test } from 'node:test';
import assert from 'node:assert/strict';

import { RelayTransport } from '../relay-transport.js';
import { SyncError } from '../sync-errors.js';
import { MAX_PAYLOAD, decodeRequest } from '../relay-frame.js';

const SECRET = `sEcReT${'x'.repeat(37)}`;                 // 43 Zeichen, leicht wiederzuerkennen
const NONCE = 'AAAAAAAAAAAAAAAA';
const ENVELOPE = { v: 2, seq: 1, n: NONCE, c: 'QQ' };
const RELAY = 'https://relay.example.workers.dev';

class FakeSocket {
  constructor(url, protocols) {
    this.url = url;
    this.protocols = protocols;
    this.sent = [];
    this.closed = false;
    this.listeners = {};
    this.binaryType = '';
  }

  addEventListener(type, fn) { (this.listeners[type] ??= []).push(fn); }

  send(data) { this.sent.push(data); }

  close() { this.closed = true; }

  emit(type, event = {}) { for (const fn of this.listeners[type] ?? []) fn(event); }

  open() { this.emit('open'); }

  message(bytes) { this.emit('message', { data: bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength) }); }

  ok(ver) { this.message(frame(3, ver, new Uint8Array(0))); }

  slot(ver, response) {
    const body = response instanceof Uint8Array ? response : new TextEncoder().encode(JSON.stringify(response));
    this.message(frame(2, ver, body));
  }

  serverClose(code, reason = '') { this.emit('close', { code, reason }); }
}

function frame(type, ver, payload) {
  const out = new Uint8Array(5 + payload.length);
  out[0] = type;
  new DataView(out.buffer).setUint32(1, ver, false);
  out.set(payload, 5);
  return out;
}

const answer = (overrides = {}) => ({ v: 1, status: 200, seq: 1, n: NONCE, body: { ok: true }, ...overrides });
const tick = () => new Promise((resolve) => setTimeout(resolve, 0));

function setup({ timeoutMs = 2000, attempts = 2, have = 0 } = {}) {
  const sockets = [];
  const logs = [];
  const haves = [];
  const transport = new RelayTransport({
    webSocketFactory: (url, protocols) => { const s = new FakeSocket(url, protocols); sockets.push(s); return s; },
    relayUrl: RELAY, timeoutMs, attempts, log: (what, error) => logs.push([what, String(error?.message ?? error)]),
  });
  const endpoint = { kind: 'relay', secret: SECRET, have, onHave: (ver) => haves.push(ver) };
  const run = (overrides = {}) => transport.exchange({
    method: 'POST', path: '/v1/sync', token: 'T'.repeat(20), body: ENVELOPE, endpoint, ...overrides });
  return { sockets, logs, haves, run, endpoint };
}

const everything = (error) => JSON.stringify([error.message, error.code, error.kind]);

test('a current response resolves with status and body', async () => {
  const { sockets, run } = setup();
  const pending = run();
  const ws = sockets[0];
  assert.equal(ws.binaryType, 'arraybuffer');
  ws.open();
  assert.equal(ws.sent.length, 1);
  const sent = decodeRequest(ws.sent[0].subarray(1));
  assert.equal(sent.path, '/v1/sync');
  assert.equal(sent.token, 'T'.repeat(20));
  ws.ok(1);
  ws.slot(2, answer({ status: 409, body: { error: { code: 'replay' } } }));
  assert.deepEqual(await pending, { status: 409, json: { error: { code: 'replay' } } });
  assert.equal(ws.closed, true);
});

test('the url carries role and have but never the secret', async () => {
  const first = setup({ have: 0 });
  first.run().catch(() => {});
  assert.equal(new URL(first.sockets[0].url).searchParams.get('role'), 'phone');
  assert.equal(new URL(first.sockets[0].url).protocol, 'wss:');
  assert.equal(new URL(first.sockets[0].url).searchParams.has('have'), false);
  assert.deepEqual(first.sockets[0].protocols, ['zeit.v1', SECRET]);
  const second = setup({ have: 7 });
  second.run().catch(() => {});
  assert.equal(new URL(second.sockets[0].url).searchParams.get('have'), '7');
  for (const s of [first.sockets[0], second.sockets[0]]) assert.equal(s.url.includes(SECRET), false);
});

test('a stale or foreign response is skipped and logged, the current one wins', async () => {
  const { sockets, logs, run } = setup();
  const pending = run();
  const ws = sockets[0];
  ws.open();
  ws.ok(1);
  ws.slot(2, answer({ n: 'BBBBBBBBBBBBBBBB' }));                 // falsches n
  ws.slot(3, answer({ n: null }));                               // nie aktuell
  ws.slot(4, new TextEncoder().encode('{kaputt'));               // kein JSON
  ws.slot(5, new TextEncoder().encode('[1,2]'));                 // kein Objekt
  ws.slot(6, answer({ status: 200, body: { winner: true } }));
  assert.deepEqual(await pending, { status: 200, json: { winner: true } });
  assert.ok(logs.length >= 4);
});

test('have only grows, follows foreign slots and ignores values above 2^31 - 1', async () => {
  const { sockets, haves, run } = setup();
  const pending = run();
  const ws = sockets[0];
  ws.open();
  ws.slot(5, answer({ n: 'BBBBBBBBBBBBBBBB' }));                 // fremd, schreibt have trotzdem fort
  ws.slot(3, answer({ n: 'BBBBBBBBBBBBBBBB' }));                 // kleiner: ignoriert
  ws.slot(2 ** 31, answer({ n: 'BBBBBBBBBBBBBBBB' }));           // über der Grenze: ignoriert
  ws.slot(9, answer());
  await pending;
  assert.deepEqual(haves, [5, 9]);
});

test('wiped resets have to 0 and the exchange goes on with a new attempt', async () => {
  const { sockets, haves, run } = setup({ have: 4 });
  const pending = run();
  sockets[0].open();
  sockets[0].serverClose(1000, 'wiped');
  await tick();
  assert.equal(new URL(sockets[1].url).searchParams.has('have'), false);
  sockets[1].open();
  sockets[1].slot(1, answer());
  await pending;
  assert.deepEqual(haves, [0, 1]);
});

test('a dropped connection resends the identical bytes', async () => {
  const { sockets, run } = setup();
  const pending = run();
  sockets[0].open();
  sockets[0].serverClose(1006);
  await tick();
  assert.equal(sockets.length, 2);
  sockets[1].open();
  assert.deepEqual(sockets[1].sent[0], sockets[0].sent[0]);
  sockets[1].slot(2, answer());
  await pending;
});

test('no ok means the relay is unreachable', async () => {
  const { run } = setup({ timeoutMs: 40 });
  await assert.rejects(run(), (error) => error instanceof SyncError && error.kind === 'offline'
    && error.code === 'relay_unreachable' && error.retryable);
});

test('ok without a response means the desktop is silent', async () => {
  const { sockets, run } = setup({ timeoutMs: 40 });
  const pending = run();
  sockets[0].open();
  sockets[0].ok(1);
  await assert.rejects(pending, (error) => error instanceof SyncError && error.kind === 'desktop_silent'
    && error.retryable);
});

test('close 1008 is throttled and not retried', async () => {
  const { sockets, run } = setup();
  const pending = run();
  sockets[0].open();
  sockets[0].serverClose(1008, 'too many');
  await assert.rejects(pending, (error) => error.kind === 'throttled' && error.retryable);
  assert.equal(sockets.length, 1);
});

test('close 1000 replaced is transient without reconnect', async () => {
  const { sockets, run } = setup();
  const pending = run();
  sockets[0].open();
  sockets[0].serverClose(1000, 'replaced');
  await assert.rejects(pending, (error) => error.kind === 'transient' && error.code === 'replaced');
  assert.equal(sockets.length, 1);
});

test('close 1009 and 1003 are protocol errors', async () => {
  for (const code of [1009, 1003]) {
    const { sockets, run } = setup();
    const pending = run();
    sockets[0].open();
    sockets[0].serverClose(code);
    await assert.rejects(pending, (error) => error.kind === 'protocol');
  }
});

test('an oversized request is too_large before anything is sent', async () => {
  const { sockets, run } = setup();
  const big = { v: 2, seq: 1, n: NONCE, c: 'x'.repeat(MAX_PAYLOAD) };
  await assert.rejects(run({ body: big }), (error) => error.kind === 'too_large' && error.code === 'request_too_large');
  assert.equal(sockets.length, 0);
});

test('an envelope without a valid nonce is a protocol error before anything is sent', async () => {
  const { sockets, run } = setup();
  await assert.rejects(run({ body: { v: 2, seq: 1, c: 'QQ' } }), (error) => error.kind === 'protocol');
  assert.equal(sockets.length, 0);
});

test('the secret appears in no error and no log line', async () => {
  const outcomes = [];
  for (const scenario of ['unreachable', 'silent', 'throttled', 'replaced', 'garbage']) {
    const { sockets, logs, run } = setup({ timeoutMs: 40 });
    const pending = run();
    const ws = sockets[0];
    if (scenario !== 'unreachable') ws.open();
    if (scenario === 'silent') ws.ok(1);
    if (scenario === 'throttled') ws.serverClose(1008);
    if (scenario === 'replaced') ws.serverClose(1000, 'replaced');
    if (scenario === 'garbage') { ws.slot(1, new TextEncoder().encode('nope')); ws.serverClose(1009); }
    const error = await pending.then(() => null, (e) => e);
    outcomes.push(everything(error), JSON.stringify(logs));
  }
  for (const text of outcomes) assert.equal(text.includes(SECRET), false);
});

test('the socket is closed on every outcome', async () => {
  const done = setup();
  const pending = done.run();
  done.sockets[0].open();
  done.sockets[0].slot(1, answer());
  await pending;
  assert.equal(done.sockets[0].closed, true);
  const failed = setup({ timeoutMs: 30 });
  await failed.run().catch(() => {});
  assert.ok(failed.sockets.every((s) => s.closed));
});
