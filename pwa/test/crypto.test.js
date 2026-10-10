// pwa/test/crypto.test.js
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

import {
  CryptoFailure, b64d, b64e, deviceKeys, isEnvelope, openEnvelope, pairKeys, seal,
} from '../crypto.js';

const V = JSON.parse(readFileSync(new URL('./fixtures/crypto-vectors.json', import.meta.url)));
const hex = (bytes) => Buffer.from(bytes).toString('hex');
const fromHex = (text) => new Uint8Array(Buffer.from(text, 'hex'));
const KEY = Uint8Array.from({ length: 32 }, (_, i) => i);
const PARTS = { direction: 'req', method: 'POST', path: '/v1/sync', deviceId: 'phone-0001' };
const text = (value) => new TextEncoder().encode(value);

const sealed = (plaintext = text('{"a":1}'), over = {}) => seal(KEY, { ...PARTS, seq: 7, plaintext, ...over });
const open = (envelope, over = {}) => openEnvelope(KEY, envelope, { ...PARTS, ...over });
const failure = (code) => (error) => error instanceof CryptoFailure && error.code === code;

test('key derivation matches the Python vectors', async () => {
  const [pr, ps] = await pairKeys(V.code);
  assert.equal(hex(pr), V.pair_request_key);
  assert.equal(hex(ps), V.pair_response_key);
  const [rq, rs] = await deviceKeys(fromHex(V.device_key));
  assert.equal(hex(rq), V.request_key);
  assert.equal(hex(rs), V.response_key);
});

test('sealing with the vector nonce gives exactly the Python envelope, and Python envelopes open', async () => {
  for (const c of V.cases) {
    const key = fromHex(c.key);
    const envelope = await seal(key, { direction: c.direction, method: c.method, path: c.path,
      deviceId: c.device_id, seq: c.seq, plaintext: text(c.plaintext), nonce: fromHex(c.nonce) });
    assert.deepEqual(envelope, c.envelope);
    const plain = await openEnvelope(key, c.envelope, { direction: c.direction, method: c.method, path: c.path,
      deviceId: c.device_id });
    assert.equal(new TextDecoder().decode(plain), c.plaintext);
  }
});

test('a round trip returns the plaintext and the envelope has exactly four fields', async () => {
  const envelope = await sealed();
  assert.deepEqual(Object.keys(envelope).sort(), ['c', 'n', 'seq', 'v']);
  assert.equal(envelope.v, 2);
  assert.equal(new TextDecoder().decode(await open(envelope)), '{"a":1}');
});

test('every message gets a fresh random nonce', async () => {
  const nonces = new Set();
  for (let i = 0; i < 200; i += 1) nonces.add((await sealed()).n);
  assert.equal(nonces.size, 200);
});

for (const [name, over] of [['direction', { direction: 'res' }], ['method', { method: 'GET' }],
  ['path', { path: '/v1/ping' }], ['device', { deviceId: 'phone-0002' }]]) {
  test(`aad binds the ${name}`, async () => {
    const envelope = await sealed();
    await assert.rejects(open(envelope, over), failure('decrypt_failed'));
  });
}

test('aad binds the sequence number', async () => {
  const envelope = await sealed();
  await assert.rejects(open({ ...envelope, seq: 8 }), failure('decrypt_failed'));
});

test('a flipped bit in nonce or ciphertext fails', async () => {
  for (const field of ['c', 'n']) {
    const envelope = await sealed();
    const raw = b64d(envelope[field]);
    raw[0] ^= 1;
    await assert.rejects(open({ ...envelope, [field]: b64e(raw) }), failure('decrypt_failed'));
  }
});

test('a wrong key fails', async () => {
  const envelope = await sealed();
  await assert.rejects(openEnvelope(new Uint8Array(32), envelope, PARTS), failure('decrypt_failed'));
});

test('a response only opens with the expected request sequence', async () => {
  const envelope = await sealed(text('x'), { direction: 'res' });
  await assert.rejects(open(envelope, { direction: 'res', seq: 8 }), failure('decrypt_failed'));
  assert.equal(new TextDecoder().decode(await open(envelope, { direction: 'res', seq: 7 })), 'x');
});

test('request and response keys differ and depend on the secret', async () => {
  const [rq, rs] = await deviceKeys(KEY);
  assert.notEqual(hex(rq), hex(rs));
  const [other] = await deviceKeys(new Uint8Array(32));
  assert.notEqual(hex(other), hex(rq));
  const [pr] = await pairKeys('K7M29QXA'.repeat(3) + 'K7M2');
  assert.notEqual(hex(pr), hex(rq));
});

test('a request cannot be replayed as a response', async () => {
  const [requestKey, responseKey] = await deviceKeys(KEY);
  const envelope = await seal(requestKey, { ...PARTS, seq: 7, plaintext: text('x') });
  await assert.rejects(openEnvelope(responseKey, envelope, { ...PARTS, direction: 'res' }), failure('decrypt_failed'));
});

const A16 = 'A'.repeat(16);
const A40 = 'A'.repeat(40);
const BAD_ENVELOPES = [
  null, [], 'x', {}, { v: 2 },
  { v: 1, seq: 1, n: A16, c: A40 }, { v: 2, seq: 0, n: A16, c: A40 }, { v: 2, seq: true, n: A16, c: A40 },
  { v: 2, seq: 2 ** 53, n: A16, c: A40 }, { v: 2, seq: 1.5, n: A16, c: A40 },
  { v: 2, seq: 1, n: 'AAAA', c: A40 }, { v: 2, seq: 1, n: A16, c: 'AAAA' },
  { v: 2, seq: 1, n: A16, c: A40, x: 1 }, { v: 2, seq: 1, n: `${'A'.repeat(15)}=`, c: A40 },
  { v: 2, seq: 1, n: A16, c: 'A!'.repeat(20) },
];

test('malformed envelopes are refused with invalid_envelope before decrypting', async () => {
  for (const bad of BAD_ENVELOPES) {
    assert.equal(isEnvelope(bad), false, JSON.stringify(bad));
    await assert.rejects(open(bad), failure('invalid_envelope'));
  }
});

test('base64url is strict and canonical', () => {
  assert.deepEqual(b64d(b64e(Uint8Array.from({ length: 40 }, (_, i) => i))), Uint8Array.from({ length: 40 }, (_, i) => i));
  for (const bad of ['AA==', 'A', 'AA AA', 'AA+/', 'é', 'AB']) {
    assert.throws(() => b64d(bad), failure('invalid_envelope'), bad);
  }
});

test('a valid envelope is recognised', async () => {
  assert.equal(isEnvelope(await sealed()), true);
});

test('sealing refuses an invalid sequence number', async () => {
  for (const seq of [0, -1, 1.5, 2 ** 53, '1', null]) {
    await assert.rejects(sealed(text('x'), { seq }), failure('invalid_envelope'));
  }
});
