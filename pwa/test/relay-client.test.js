// pwa/test/relay-client.test.js
import { test } from 'node:test';
import assert from 'node:assert/strict';

import { RELAY_URL, RelayClient, RelayError, VAPID_PUBLIC, newSecret, syncSchedule } from '../relay-client.js';

const SECRET = 'A'.repeat(43);
const SUBSCRIPTION = { endpoint: 'https://fcm.googleapis.com/fcm/send/geheim-endpoint', keys: { p256dh: 'p', auth: 'a' } };
const ITEMS = [{ id: 'r1', fire_at: '2026-10-22T10:00:00Z', blob: 'abc' }];

function fakeFetch(...statuses) {
  const calls = [];
  const fn = async (url, options) => {
    calls.push({ url, method: options.method, auth: options.headers.authorization, body: options.body });
    const next = statuses.shift();
    if (next instanceof Error) throw next;
    const [status, body] = Array.isArray(next) ? next : [next ?? 204, null];
    return new Response(body === null ? null : JSON.stringify(body), { status });
  };
  fn.calls = calls;
  return fn;
}

test('constants: relay address and the public VAPID key', () => {
  assert.equal(RELAY_URL, 'https://zeiterfassung-push.svenbirkendahl.workers.dev');
  assert.match(VAPID_PUBLIC, /^[A-Za-z0-9_-]{87}$/);
});

test('newSecret is 43 characters of base64url and different every time', () => {
  const a = newSecret();
  assert.match(a, /^[A-Za-z0-9_-]{43}$/);
  assert.notEqual(a, newSecret());
});

test('the three calls use the right method, path, bearer and body', async () => {
  const fetchFn = fakeFetch(204, 204, 204);
  const client = new RelayClient({ fetchFn });
  await client.registerDevice(SECRET, SUBSCRIPTION);
  await client.putSchedule(SECRET, ITEMS);
  await client.deleteDevice(SECRET);
  assert.deepEqual(fetchFn.calls.map((c) => [c.method, c.url, c.auth]), [
    ['PUT', `${RELAY_URL}/v1/device`, `Bearer ${SECRET}`],
    ['PUT', `${RELAY_URL}/v1/schedule`, `Bearer ${SECRET}`],
    ['DELETE', `${RELAY_URL}/v1/device`, `Bearer ${SECRET}`],
  ]);
  assert.deepEqual(JSON.parse(fetchFn.calls[0].body), SUBSCRIPTION);
  assert.deepEqual(JSON.parse(fetchFn.calls[1].body), { items: ITEMS });
  assert.equal(fetchFn.calls[2].body, undefined);
});

for (const [status, body, kind] of [
  [401, { error: 'unauthorized' }, 'unauthorized'], [409, { error: 'no_subscription' }, 'no_subscription'],
  [413, { error: 'too_large' }, 'too_large'], [429, { error: 'rate_limited' }, 'rate_limited'],
  [400, { error: 'invalid_request', message: 'items muss eine Liste sein.' }, 'invalid'],
  [500, { error: 'internal' }, 'server'], [503, null, 'server'],
]) {
  test(`status ${status} is ${kind}`, async () => {
    const client = new RelayClient({ fetchFn: fakeFetch([status, body]) });
    await assert.rejects(client.putSchedule(SECRET, ITEMS), (error) => error instanceof RelayError && error.kind === kind);
  });
}

test('a network error is offline', async () => {
  const client = new RelayClient({ fetchFn: fakeFetch(new TypeError('Failed to fetch')) });
  await assert.rejects(client.putSchedule(SECRET, ITEMS), (error) => error.kind === 'offline');
});

test('error texts never carry the secret or the endpoint', async () => {
  for (const status of [400, 401, 409, 413, 429, 500]) {
    const client = new RelayClient({ fetchFn: fakeFetch([status, { error: 'x', message: SECRET }]) });
    await assert.rejects(client.putSchedule(SECRET, ITEMS), (error) => !error.message.includes(SECRET) && !error.message.includes('geheim-endpoint'));
  }
});

test('a lost subscription is registered once more and the schedule sent again', async () => {
  const fetchFn = fakeFetch([409, { error: 'no_subscription' }], 204, 204);
  await syncSchedule({ client: new RelayClient({ fetchFn }), secret: SECRET, subscription: SUBSCRIPTION, items: ITEMS });
  assert.deepEqual(fetchFn.calls.map((c) => `${c.method} ${new URL(c.url).pathname}`), ['PUT /v1/schedule', 'PUT /v1/device', 'PUT /v1/schedule']);
});

test('a second 409 is an error, not a loop', async () => {
  const fetchFn = fakeFetch([409, { error: 'no_subscription' }], 204, [409, { error: 'no_subscription' }]);
  await assert.rejects(
    syncSchedule({ client: new RelayClient({ fetchFn }), secret: SECRET, subscription: SUBSCRIPTION, items: ITEMS }),
    (error) => error.kind === 'no_subscription');
  assert.equal(fetchFn.calls.length, 3);
});

test('other errors are passed on without re-registering', async () => {
  const fetchFn = fakeFetch([429, { error: 'rate_limited' }]);
  await assert.rejects(
    syncSchedule({ client: new RelayClient({ fetchFn }), secret: SECRET, subscription: SUBSCRIPTION, items: ITEMS }),
    (error) => error.kind === 'rate_limited');
  assert.equal(fetchFn.calls.length, 1);
});
