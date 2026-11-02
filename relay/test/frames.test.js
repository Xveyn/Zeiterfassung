// relay/test/frames.test.js
import assert from 'node:assert/strict';
import test from 'node:test';
import { FRAME, decodePut, encodeOk, encodeSlot } from '../src/frames.js';

const bytes = (a) => Uint8Array.from(a);

test('FRAME has the three message types', () => {
  assert.deepEqual(FRAME, { put: 0x01, slot: 0x02, ok: 0x03 });
});

test('encodeSlot lays out type, 4-byte big-endian ver, payload', () => {
  assert.deepEqual(encodeSlot(0x01020304, bytes([9, 8])), bytes([2, 1, 2, 3, 4, 9, 8]));
});

test('encodeOk lays out type and 4-byte big-endian ver', () => {
  assert.deepEqual(encodeOk(258), bytes([3, 0, 0, 1, 2]));
});

test('decodePut returns payload for [1,5,6]', () => {
  assert.deepEqual(decodePut(bytes([1, 5, 6]).buffer), bytes([5, 6]));
  assert.deepEqual(decodePut(bytes([1, 5, 6])), bytes([5, 6]));
});

test('decodePut allows empty payload', () => {
  const out = decodePut(bytes([1]));
  assert.ok(out instanceof Uint8Array);
  assert.equal(out.length, 0);
});

test('decodePut returns null for string, for [2,1], for empty buffer, for null', () => {
  assert.equal(decodePut('text'), null);
  assert.equal(decodePut(bytes([2, 1])), null);
  assert.equal(decodePut(new ArrayBuffer(0)), null);
  assert.equal(decodePut(null), null);
});
