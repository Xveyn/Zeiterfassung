// pwa/test/push-blob.test.js
import { test } from 'node:test';
import assert from 'node:assert/strict';

import { MAX_BLOB, memoryKeyStore, open, seal } from '../push-blob.js';

const plain = { k: 'upcoming', c: 'Projekt', e: '12:00', d: '2026-10-22' };

test('a sealed blob opens to the same object', async () => {
  const keys = memoryKeyStore();
  assert.deepEqual(await open(keys, await seal(keys, plain)), plain);
});

test('every blob differs, even for the same text', async () => {
  const keys = memoryKeyStore();
  assert.notEqual(await seal(keys, plain), await seal(keys, plain));
});

test('the blob does not contain the text', async () => {
  const keys = memoryKeyStore();
  const blob = await seal(keys, plain);
  assert.ok(!blob.includes('Projekt'));
  assert.ok(!atob(blob).includes('Projekt'));
});

test('a blob under another key, a damaged blob and a non-blob do not open', async () => {
  const mine = memoryKeyStore();
  const blob = await seal(mine, plain);
  await assert.rejects(open(memoryKeyStore(), blob));
  const bytes = Uint8Array.from(atob(blob), (c) => c.charCodeAt(0));
  bytes[bytes.length - 1] ^= 1;
  await assert.rejects(open(mine, btoa(String.fromCharCode(...bytes))));
  await assert.rejects(open(mine, 'kein-base64!'));
  await assert.rejects(open(mine, ''));
});

test('the key is created once and reused', async () => {
  const keys = memoryKeyStore();
  const first = await seal(keys, plain);
  const second = await seal(keys, plain);
  assert.deepEqual(await open(keys, first), await open(keys, second));
});

test('the key cannot be exported', async () => {
  const keys = memoryKeyStore();
  await seal(keys, plain);
  await assert.rejects(crypto.subtle.exportKey('raw', await keys.get()));
});

test('a plain text that would exceed the relay limit is refused', async () => {
  const keys = memoryKeyStore();
  await assert.rejects(seal(keys, { c: 'x'.repeat(MAX_BLOB) }), /zu groß/);
  assert.ok((await seal(keys, plain)).length <= MAX_BLOB);
});
