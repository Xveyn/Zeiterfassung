// pwa/test/relay-frame.test.js
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

import {
  MAX_FRAME, MAX_PAYLOAD, PUTS_PER_MINUTE, RelayFrameError, SUBPROTOCOL, TYPE,
  decodeMessage, decodeRequest, decodeResponse, encodePut, encodeRequest, envelopeSeq, isCurrentResponse,
} from '../relay-frame.js';

const fixture = JSON.parse(readFileSync(new URL('./fixtures/relay-frames.json', import.meta.url)));
const enc = new TextEncoder();
const fromHex = (hex) => Uint8Array.from(hex.match(/../g) ?? [], (h) => parseInt(h, 16));
const toHex = (bytes) => Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('');
const isInvalid = (error) => error instanceof RelayFrameError && error.code === 'invalid_frame';
const isTooLarge = (error) => error instanceof RelayFrameError && error.code === 'too_large';

const TOKEN = 'Zm9vYmFyYmF6cXV4Zm9vYmFyYmF6cXV4Zm9vYmFyYmE';
const ENVELOPE = { v: 2, seq: 7, n: 'AAECAwQFBgcICQoL', c: 'q83vASNFZ4mrze8BI0VniQ' };
const requestBytes = (envelope, path = '/v1/sync', token = TOKEN) =>
  enc.encode(JSON.stringify({ v: 1, path, token, envelope }));

test('constants match the fixture and the relay', () => {
  const c = fixture.constants;
  assert.equal(SUBPROTOCOL, c.subprotocol);
  assert.equal(MAX_FRAME, c.max_frame);
  assert.equal(MAX_PAYLOAD, c.max_payload);
  assert.equal(PUTS_PER_MINUTE, c.puts_per_minute);
  assert.deepEqual(TYPE, c.types);
  const source = readFileSync(new URL('../../relay/src/validate.js', import.meta.url), 'utf8');
  assert.equal(Number(/maxFrame:\s*([\d_]+)/.exec(source)[1].replaceAll('_', '')), MAX_FRAME);
  assert.equal(Number(/putsPerMinute:\s*(\d+)/.exec(source)[1]), PUTS_PER_MINUTE);
});

test('encodePut prefixes the type byte; empty payload is allowed; MAX_PAYLOAD is accepted and +1 throws too_large', () => {
  for (const row of fixture.puts) {
    assert.equal(toHex(encodePut(fromHex(row.payload_hex))), row.hex, row.name);
  }
  assert.equal(encodePut(new Uint8Array(0)).length, 1);
  const full = encodePut(new Uint8Array(MAX_PAYLOAD));
  assert.equal(full.length, MAX_FRAME);
  assert.equal(full[0], 1);
  assert.throws(() => encodePut(new Uint8Array(MAX_PAYLOAD + 1)), isTooLarge);
});

test('decodeMessage matches every fixture message (slot, ok, ignored cases)', () => {
  for (const row of fixture.messages) {
    const got = decodeMessage(fromHex(row.hex));
    if (row.decoded === null) {
      assert.equal(got, null, row.name);
      continue;
    }
    assert.equal(got.kind, row.decoded.kind, row.name);
    assert.equal(got.ver, row.decoded.ver, row.name);
    if (row.decoded.kind === 'slot') assert.equal(toHex(got.data), row.decoded.data_hex ?? '', row.name);
    else assert.equal('data' in got, false, row.name);
  }
});

test('decodeMessage accepts ArrayBuffer and returns a copy of the data', () => {
  const bytes = fromHex('02000000010102');
  const got = decodeMessage(bytes.buffer);
  assert.deepEqual([...got.data], [1, 2]);
  got.data[0] = 9;
  assert.equal(bytes[5], 1);
  const viaView = decodeMessage(bytes);
  viaView.data[0] = 9;
  assert.equal(bytes[5], 1);
});

test('decodeMessage ignores strings and never throws', () => {
  for (const junk of ['ping', '', null, undefined, 5, {}, [], true]) assert.equal(decodeMessage(junk), null);
});

test('decodeRequest accepts every ok:true fixture request and returns path, token, seq', () => {
  for (const row of fixture.requests.filter((r) => r.ok)) {
    const got = decodeRequest(enc.encode(row.json));
    assert.equal(got.path, row.path, row.name);
    assert.equal(got.token, row.token, row.name);
    assert.equal(got.seq, row.seq, row.name);
    assert.equal(typeof got.envelope, 'object', row.name);
  }
});

test('decodeRequest rejects every ok:false fixture request with RelayFrameError invalid_frame', () => {
  for (const row of fixture.requests.filter((r) => !r.ok)) {
    assert.throws(() => decodeRequest(enc.encode(row.json)), isInvalid, row.name);
  }
});

test('decodeRequest never leaks foreign exceptions', () => {
  const junk = [new Uint8Array(0), Uint8Array.of(0xff, 0xfe, 0x7b), enc.encode('null'), enc.encode('5'),
    enc.encode('"x"'), enc.encode('{"v":1,"path":5,"token":null,"envelope":{}}'), null, 'text'];
  for (const bytes of junk) assert.throws(() => decodeRequest(bytes), isInvalid);
});

test('an invalid envelope seq is still a valid request with seq null', () => {
  for (const seq of [1.5, -1, '1', 2 ** 53, 0, true, null]) {
    const got = decodeRequest(requestBytes({ ...ENVELOPE, seq }));
    assert.equal(got.seq, null, String(seq));
  }
  assert.equal(decodeRequest(requestBytes({ ...ENVELOPE, seq: 2 ** 53 - 1 })).seq, 2 ** 53 - 1);
  assert.equal(decodeRequest(requestBytes({ v: 2, n: 'x', c: 'y' })).seq, null);
});

test('decodeResponse accepts every ok:true fixture response and rejects every ok:false one', () => {
  for (const row of fixture.responses) {
    if (row.ok) {
      const got = decodeResponse(enc.encode(row.json));
      assert.equal(got.status, row.status, row.name);
      assert.equal(got.seq, row.seq, row.name);
      assert.deepEqual(got.body, row.body, row.name);
    } else {
      assert.throws(() => decodeResponse(enc.encode(row.json)), isInvalid, row.name);
    }
  }
});

test('decodeResponse rejects invalid seq values and never leaks foreign exceptions', () => {
  const make = (seq) => enc.encode(JSON.stringify({ v: 1, status: 200, seq, body: {} }));
  for (const seq of [0, -1, '1', 1.5, true, 2 ** 53]) assert.throws(() => decodeResponse(make(seq)), isInvalid, String(seq));
  assert.equal(decodeResponse(make(2 ** 53 - 1)).seq, 2 ** 53 - 1);
  for (const bytes of [new Uint8Array(0), Uint8Array.of(0xff), enc.encode('null'), null, 'x']) {
    assert.throws(() => decodeResponse(bytes), isInvalid);
  }
});

test('encodeRequest then decodeRequest round-trips, counts UTF-8 bytes against MAX_PAYLOAD', () => {
  const envelope = { ...ENVELOPE, c: 'Größe €' };
  const bytes = encodeRequest({ path: '/v1/sync', token: TOKEN, envelope });
  assert.equal(new TextDecoder().decode(bytes).startsWith('{"v":1,"path":"/v1/sync","token":"'), true);
  assert.deepEqual(decodeRequest(bytes), { path: '/v1/sync', token: TOKEN, envelope, seq: 7 });
  const pair = decodeRequest(encodeRequest({ path: '/v1/pair', token: null, envelope }));
  assert.equal(pair.token, null);

  // Größe in Bytes: Rahmen ohne Füllung messen, dann auf genau MAX_PAYLOAD bzw. +1 füllen.
  const build = (pad) => ({ path: '/v1/sync', token: TOKEN, envelope: { ...ENVELOPE, x: pad } });
  const base = encodeRequest(build('')).length;
  const fill = MAX_PAYLOAD - base;
  assert.equal(encodeRequest(build('a'.repeat(fill))).length, MAX_PAYLOAD);
  assert.throws(() => encodeRequest(build('a'.repeat(fill + 1))), isTooLarge);
  // Mehrbyte-Zeichen: in Zeichen unter der Grenze, in Bytes darüber.
  const euros = '€'.repeat(Math.floor(fill / 3) + 1);
  assert.ok(base + euros.length < MAX_PAYLOAD);
  assert.throws(() => encodeRequest(build(euros)), isTooLarge);
  assert.throws(() => decodeRequest(new Uint8Array(MAX_PAYLOAD + 1)), RelayFrameError);
});

test('encodeRequest enforces the same rules as decodeRequest', () => {
  const bad = [
    { path: '/v1/ping', token: TOKEN, envelope: ENVELOPE },
    { path: '/v1/sync', token: null, envelope: ENVELOPE },
    { path: '/v1/sync', token: '', envelope: ENVELOPE },
    { path: '/v1/sync', token: 'a b', envelope: ENVELOPE },
    { path: '/v1/sync', token: 'x'.repeat(513), envelope: ENVELOPE },
    { path: '/v1/pair', token: 'a b', envelope: ENVELOPE },
    { path: '/v1/sync', token: TOKEN, envelope: [] },
    { path: '/v1/sync', token: TOKEN, envelope: null },
    { path: '/v1/sync', token: TOKEN, envelope: 'x' },
    null,
  ];
  for (const args of bad) assert.throws(() => encodeRequest(args), isInvalid);
  assert.doesNotThrow(() => encodeRequest({ path: '/v1/pair', token: TOKEN, envelope: ENVELOPE }));
});

test('envelopeSeq rejects 0, -1, "1", 1.5, true, 2**53, NaN', () => {
  for (const seq of [0, -1, '1', 1.5, true, 2 ** 53, NaN, Infinity, null, undefined, {}, []]) {
    assert.equal(envelopeSeq({ seq }), null, String(seq));
  }
  for (const junk of [null, undefined, 5, 'x', []]) assert.equal(envelopeSeq(junk), null);
  assert.equal(envelopeSeq({ seq: 1 }), 1);
  assert.equal(envelopeSeq({ seq: Number.MAX_SAFE_INTEGER }), Number.MAX_SAFE_INTEGER);
});

test('isCurrentResponse: equal seq true, different seq false, null seq only with status >= 400', () => {
  assert.equal(isCurrentResponse({ status: 200, seq: 5 }, 5), true);
  assert.equal(isCurrentResponse({ status: 200, seq: 4 }, 5), false);
  assert.equal(isCurrentResponse({ status: 200, seq: null }, 5), false);
  assert.equal(isCurrentResponse({ status: 399, seq: null }, 5), false);
  assert.equal(isCurrentResponse({ status: 400, seq: null }, 5), true);
  assert.equal(isCurrentResponse({ status: 401, seq: 4 }, 5), false);
});
