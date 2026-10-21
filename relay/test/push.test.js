// relay/test/push.test.js
import assert from 'node:assert/strict';
import test from 'node:test';
import { generateVapid } from '../scripts/gen-vapid.mjs';
import { sendPush } from '../src/push.js';

async function makeEnv() {
  const { publicKey, privateKey } = await generateVapid();
  return { VAPID_PUBLIC: publicKey, VAPID_PRIVATE: privateKey, VAPID_SUBJECT: 'mailto:test@example.com' };
}

async function makeSubscription(endpoint = 'https://fcm.googleapis.com/fcm/send/abc') {
  const pair = await crypto.subtle.generateKey({ name: 'ECDH', namedCurve: 'P-256' }, true, ['deriveBits']);
  const raw = new Uint8Array(await crypto.subtle.exportKey('raw', pair.publicKey));
  return {
    endpoint,
    keys: { p256dh: Buffer.from(raw).toString('base64url'), auth: Buffer.from(crypto.getRandomValues(new Uint8Array(16))).toString('base64url') },
  };
}

const answering = (status) => {
  const calls = [];
  const fetchFn = async (url, init) => { calls.push({ url, init }); return new Response('', { status }); };
  return { fetchFn, calls };
};

test('maps 201 to ok', async () => {
  const { fetchFn } = answering(201);
  assert.equal(await sendPush(await makeSubscription(), 'blob', await makeEnv(), fetchFn), 'ok');
});

test('maps 404 and 410 to gone', async () => {
  for (const status of [404, 410]) {
    assert.equal(await sendPush(await makeSubscription(), 'blob', await makeEnv(), answering(status).fetchFn), 'gone', String(status));
  }
});

test('maps 429, 500 and 503 to retry', async () => {
  for (const status of [429, 500, 503]) {
    assert.equal(await sendPush(await makeSubscription(), 'blob', await makeEnv(), answering(status).fetchFn), 'retry', String(status));
  }
});

test('maps 400 and 413 to drop', async () => {
  for (const status of [400, 403, 413]) {
    assert.equal(await sendPush(await makeSubscription(), 'blob', await makeEnv(), answering(status).fetchFn), 'drop', String(status));
  }
});

test('maps a thrown fetch to retry', async () => {
  const fetchFn = async () => { throw new TypeError('network down'); };
  assert.equal(await sendPush(await makeSubscription(), 'blob', await makeEnv(), fetchFn), 'retry');
});

test('sends an aes128gcm body with a vapid authorization header', async () => {
  const env = await makeEnv();
  const sub = await makeSubscription('https://updates.push.services.mozilla.com/wpush/v2/xyz');
  const { fetchFn, calls } = answering(201);
  await sendPush(sub, 'Reservierung 09:00 beginnt', env, fetchFn);
  assert.equal(calls.length, 1);
  assert.equal(calls[0].url, sub.endpoint);
  const headers = new Headers(calls[0].init.headers);
  assert.match(headers.get('authorization'), new RegExp(`^vapid t=[^,]+, k=${env.VAPID_PUBLIC}$`));
  assert.equal(headers.get('content-encoding'), 'aes128gcm');
  assert.equal(headers.get('ttl'), '300');
  assert.equal(headers.get('urgency'), 'high');
  assert.ok(calls[0].init.body.byteLength > 0);
});

test('does not throw for a malformed key', async () => {
  const sub = { endpoint: 'https://fcm.googleapis.com/x', keys: { p256dh: 'abc', auth: 'abc' } };
  const result = await sendPush(sub, 'blob', await makeEnv(), answering(201).fetchFn);
  assert.ok(['drop', 'retry'].includes(result));
});
