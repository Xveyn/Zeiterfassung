// relay/test/validate.test.js
import assert from 'node:assert/strict';
import test from 'node:test';
import {
  InvalidRequest, LIMITS, parseSchedule, parseSecret, parseSubscription,
} from '../src/validate.js';

const NOW = Date.parse('2026-10-21T12:00:00Z');
const stamp = (ms) => new Date(ms).toISOString().replace(/\.\d{3}Z$/, 'Z');
const item = (over = {}) => ({ id: 'a1', fire_at: stamp(NOW + 60_000), blob: 'AAAA', ...over });
const schedule = (items) => parseSchedule({ items }, NOW);
const b64 = (n) => Buffer.alloc(n, 7).toString('base64url');
const sub = (over = {}) => ({
  endpoint: 'https://fcm.googleapis.com/fcm/send/abc', keys: { p256dh: b64(65), auth: b64(16) }, ...over,
});

test('rejects a non-https endpoint', () => {
  assert.throws(() => parseSubscription(sub({ endpoint: 'http://push.example/x' })), InvalidRequest);
  assert.throws(() => parseSubscription(sub({ endpoint: 'not a url' })), InvalidRequest);
});

test('accepts the endpoints of the known push services', () => {
  for (const endpoint of ['https://fcm.googleapis.com/fcm/send/abc',
    'https://updates.push.services.mozilla.com/wpush/v2/xyz',
    'https://foo.push.services.mozilla.com/wpush/v2/xyz',
    'https://web.push.apple.com/QGx', 'https://wns2-par02p.notify.windows.com/w/?token=abc']) {
    assert.equal(parseSubscription(sub({ endpoint })).endpoint, endpoint);
  }
});

test('rejects endpoints of unknown hosts, so the relay is no open POST proxy', () => {
  for (const endpoint of ['https://evil.example/x', 'https://fcm.googleapis.com.evil.example/x',
    'https://evilfcm.googleapis.com/x', 'https://push.services.mozilla.com.evil.example/x',
    'https://notpush.apple.com/x', 'https://169.254.169.254/latest', 'https://localhost/x']) {
    assert.throws(() => parseSubscription(sub({ endpoint })), InvalidRequest, endpoint);
  }
});

test('rejects userinfo, explicit ports, IP literals and overlong endpoints', () => {
  for (const endpoint of ['https://fcm.googleapis.com@evil.example/x', 'https://user:pw@fcm.googleapis.com/x',
    'https://fcm.googleapis.com:8443/x', 'https://[::1]/x', 'https://1.2.3.4/x',
    `https://fcm.googleapis.com/${'a'.repeat(2048)}`]) {
    assert.throws(() => parseSubscription(sub({ endpoint })), InvalidRequest, endpoint.slice(0, 60));
  }
});

test('rejects an endpoint that is not a string, so arrays cannot bypass the length cap (I2)', () => {
  const url = 'https://fcm.googleapis.com/fcm/send/abc';
  for (const endpoint of [[url], { toString: () => url }, 5, null, undefined]) {
    assert.throws(() => parseSubscription(sub({ endpoint })), InvalidRequest, String(endpoint));
  }
  assert.throws(() => parseSubscription(sub({ endpoint: [`https://fcm.googleapis.com/${'a'.repeat(5000)}`] })), InvalidRequest);
});

test('stores the normalized URL that was validated, not the raw input (I2)', () => {
  const parsed = parseSubscription(sub({ endpoint: 'HTTPS://FCM.googleapis.com/fcm/send/abc' }));
  assert.equal(parsed.endpoint, 'https://fcm.googleapis.com/fcm/send/abc');
});

test('accepts a well-formed subscription and returns only the three fields', () => {
  const parsed = parseSubscription({ ...sub(), expirationTime: null, extra: 1 });
  assert.deepEqual(parsed, sub());
});

test('rejects keys of the wrong length', () => {
  assert.throws(() => parseSubscription(sub({ keys: { p256dh: b64(64), auth: b64(16) } })), InvalidRequest);
  assert.throws(() => parseSubscription(sub({ keys: { p256dh: b64(65), auth: b64(15) } })), InvalidRequest);
  assert.throws(() => parseSubscription(sub({ keys: null })), InvalidRequest);
});

test('rejects a non-object body', () => {
  for (const body of [null, 'x', 5, [], undefined]) {
    assert.throws(() => parseSubscription(body), InvalidRequest);
    assert.throws(() => parseSchedule(body, NOW), InvalidRequest);
  }
  assert.throws(() => parseSchedule({ items: {} }, NOW), InvalidRequest);
});

test('accepts an empty items list', () => {
  assert.deepEqual(schedule([]), []);
});

test('returns id, fireAt in ms and blob', () => {
  assert.deepEqual(schedule([item()]), [{ id: 'a1', fireAt: NOW + 60_000, blob: 'AAAA' }]);
});

test('rejects duplicate ids', () => {
  assert.throws(() => schedule([item(), item()]), InvalidRequest);
});

test('rejects more than 200 items', () => {
  const many = (n) => Array.from({ length: n }, (_, i) => item({ id: `i${i}` }));
  assert.equal(schedule(many(LIMITS.maxItems)).length, 200);
  assert.throws(() => schedule(many(LIMITS.maxItems + 1)), InvalidRequest);
});

test('rejects fire_at beyond 90 days', () => {
  const day = 86_400_000;
  assert.equal(schedule([item({ fire_at: stamp(NOW + 90 * day) })]).length, 1);
  assert.throws(() => schedule([item({ fire_at: stamp(NOW + 90 * day + 1000) })]), InvalidRequest);
});

test('silently drops items older than 15 minutes', () => {
  assert.deepEqual(schedule([item({ fire_at: stamp(NOW - 901_000) })]), []);
});

test('keeps an item 14 minutes late', () => {
  assert.equal(schedule([item({ fire_at: stamp(NOW - 14 * 60_000) })]).length, 1);
});

test('rejects fire_at that is not YYYY-MM-DDTHH:MM:SSZ (including a valid-looking 2026-09-31)', () => {
  for (const bad of ['2026-09-31T10:00:00Z', '2026-10-21 10:00:00Z', '2026-10-21T10:00:00+02:00',
    '2026-10-21T10:00:00.000Z', '2026-10-21T10:00Z', 1792584000, null, '']) {
    assert.throws(() => schedule([item({ fire_at: bad })]), InvalidRequest, String(bad));
  }
});

test('rejects bad ids and blobs of the wrong type or length', () => {
  assert.equal(schedule([item({ blob: 'x'.repeat(1024) })]).length, 1);
  assert.throws(() => schedule([item({ blob: 'x'.repeat(1025) })]), InvalidRequest);
  assert.throws(() => schedule([item({ blob: 5 })]), InvalidRequest);
  assert.throws(() => schedule([item({ id: '' })]), InvalidRequest);
  assert.throws(() => schedule([item({ id: 'a'.repeat(65) })]), InvalidRequest);
  assert.throws(() => schedule([item({ id: 'a b' })]), InvalidRequest);
  assert.throws(() => schedule([null]), InvalidRequest);
});

test('parseSecret takes a 43 character base64url Bearer token', () => {
  const secret = b64(32);
  assert.equal(secret.length, 43);
  assert.equal(parseSecret(`Bearer ${secret}`), secret);
});

test('parseSecret rejects a short, long or non-base64url secret', () => {
  for (const header of [null, undefined, '', 'Bearer', secret(42), secret(44), `Bearer ${'+'.repeat(43)}`,
    `Basic ${b64(32)}`, b64(32)]) {
    assert.throws(() => parseSecret(header), InvalidRequest, String(header));
  }
  function secret(n) { return `Bearer ${'a'.repeat(n)}`; }
});
