// relay/test/gen-vapid.test.js
import assert from 'node:assert/strict';
import test from 'node:test';
import { generateVapid } from '../scripts/gen-vapid.mjs';

const bytes = (text) => Buffer.from(text, 'base64url');

test('generateVapid returns a P-256 pair in the format the push library imports', async () => {
  const { publicKey, privateKey } = await generateVapid();
  for (const key of [publicKey, privateKey]) assert.match(key, /^[A-Za-z0-9_-]+$/);
  const pub = bytes(publicKey);
  assert.equal(pub.length, 65);
  assert.equal(pub[0], 0x04);
  assert.equal(bytes(privateKey).length, 32);
  // Wie `vapidHeaders` der Bibliothek es importiert: x/y aus dem öffentlichen Schlüssel, d aus dem privaten.
  await crypto.subtle.importKey('jwk', {
    kty: 'EC', crv: 'P-256', x: pub.subarray(1, 33).toString('base64url'),
    y: pub.subarray(33, 65).toString('base64url'), d: privateKey,
  }, { name: 'ECDSA', namedCurve: 'P-256' }, false, ['sign']);
});
