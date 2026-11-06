// relay/test/push.test.js
import assert from 'node:assert/strict';
import test from 'node:test';
import { generateVapid } from '../scripts/gen-vapid.mjs';
import { sendPush } from '../src/push.js';

async function makeEnv() {
  const { publicKey, privateKey } = await generateVapid();
  return { VAPID_PUBLIC: publicKey, VAPID_PRIVATE: privateKey, VAPID_SUBJECT: 'mailto:test@example.com' };
}

const subscriptionSecrets = new WeakMap();      // Abo → privater Schlüssel, nur für den Entschlüsselungstest

async function makeSubscription(endpoint = 'https://fcm.googleapis.com/fcm/send/abc') {
  const pair = await crypto.subtle.generateKey({ name: 'ECDH', namedCurve: 'P-256' }, true, ['deriveBits']);
  const raw = new Uint8Array(await crypto.subtle.exportKey('raw', pair.publicKey));
  const subscription = {
    endpoint,
    keys: { p256dh: Buffer.from(raw).toString('base64url'), auth: Buffer.from(crypto.getRandomValues(new Uint8Array(16))).toString('base64url') },
  };
  subscriptionSecrets.set(subscription, pair.privateKey);
  return subscription;
}

async function hkdf(salt, ikm, info, length) {
  const key = await crypto.subtle.importKey('raw', ikm, 'HKDF', false, ['deriveBits']);
  return new Uint8Array(await crypto.subtle.deriveBits({ name: 'HKDF', hash: 'SHA-256', salt, info }, key, length * 8));
}

/** RFC 8291 beim Empfänger: der Body (RFC 8188, ein Datensatz) → der Klartext. */
async function decryptBody(subscription, body) {
  const salt = body.slice(0, 16);
  const idLength = body[20];
  const senderPublic = body.slice(21, 21 + idLength);
  const record = body.slice(21 + idLength);
  const userPublic = Buffer.from(subscription.keys.p256dh, 'base64url');
  const auth = Buffer.from(subscription.keys.auth, 'base64url');
  const sender = await crypto.subtle.importKey('raw', senderPublic, { name: 'ECDH', namedCurve: 'P-256' }, false, []);
  const shared = new Uint8Array(await crypto.subtle.deriveBits({ name: 'ECDH', public: sender }, subscriptionSecrets.get(subscription), 256));
  const keyInfo = new Uint8Array([...Buffer.from('WebPush: info\0'), ...userPublic, ...senderPublic]);
  const ikm = await hkdf(auth, shared, keyInfo, 32);
  const cek = await hkdf(salt, ikm, Buffer.from('Content-Encoding: aes128gcm\0'), 16);
  const nonce = await hkdf(salt, ikm, Buffer.from('Content-Encoding: nonce\0'), 12);
  const key = await crypto.subtle.importKey('raw', cek, 'AES-GCM', false, ['decrypt']);
  const padded = new Uint8Array(await crypto.subtle.decrypt({ name: 'AES-GCM', iv: nonce }, key, record));
  const end = padded.lastIndexOf(0x02);
  return Buffer.from(padded.slice(0, end)).toString('utf8');
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

test('reports the status of a refusing or failing push service, and only then', async () => {
  for (const [status, result] of [[403, 'drop'], [401, 'drop'], [503, 'retry'], [429, 'retry']]) {
    const causes = [];
    const got = await sendPush(await makeSubscription(), 'blob', await makeEnv(), answering(status).fetchFn, (cause) => causes.push(cause));
    assert.equal(got, result);
    assert.deepEqual(causes, [status], String(status));
  }
  for (const status of [201, 404, 410]) {
    const causes = [];
    await sendPush(await makeSubscription(), 'blob', await makeEnv(), answering(status).fetchFn, (cause) => causes.push(cause));
    assert.deepEqual(causes, [], String(status));
  }
});

test('reports network for a thrown fetch and build for unusable keys, never the error text', async () => {
  const causes = [];
  const down = async () => { throw new TypeError('network down https://secret.example/endpoint'); };
  await sendPush(await makeSubscription(), 'blob', await makeEnv(), down, (cause) => causes.push(cause));
  const broken = { VAPID_PUBLIC: 'x', VAPID_PRIVATE: 'y', VAPID_SUBJECT: 'mailto:test@example.com' };
  assert.equal(await sendPush(await makeSubscription(), 'blob', broken, answering(201).fetchFn, (cause) => causes.push(cause)), 'drop');
  assert.deepEqual(causes, ['network', 'build']);
});

test('the body is as small as the message, not padded to 4096 bytes (Mozilla answers 413 to that)', async () => {
  const sub = await makeSubscription('https://updates.push.services.mozilla.com/wpush/v2/xyz');
  const { fetchFn, calls } = answering(201);
  await sendPush(sub, 'zeiterfassung-test', await makeEnv(), fetchFn);
  const { body, headers } = calls[0].init;
  assert.ok(body.byteLength < 256, `body is ${body.byteLength} bytes`);
  assert.equal(new Headers(headers).get('content-length'), String(body.byteLength));
});

test('the message still decrypts at the subscriber, also a long one', async () => {
  for (const message of ['zeiterfassung-test', 'Ü'.repeat(1500)]) {
    const sub = await makeSubscription();
    const { fetchFn, calls } = answering(201);
    await sendPush(sub, message, await makeEnv(), fetchFn);
    assert.equal(await decryptBody(sub, calls[0].init.body), message);
  }
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

// --- Test-Nutzlast (#340) -----------------------------------------------------------------------

import { TEST_PAYLOAD } from '../src/push.js';
import { LIMITS } from '../src/validate.js';

test('the test payload is a short fixed text', () => {
  assert.equal(TEST_PAYLOAD, 'zeiterfassung-test');
  assert.ok(TEST_PAYLOAD.length > 0 && TEST_PAYLOAD.length <= LIMITS.maxBlob);
  assert.equal(LIMITS.testCooldownSeconds, 10);
});
