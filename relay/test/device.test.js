// relay/test/device.test.js
import assert from 'node:assert/strict';
import test from 'node:test';
import { Device } from '../src/device.js';
import { fakeStorage } from './fake-storage.js';

const T0 = Date.parse('2026-10-21T12:00:00Z');
const MIN = 60_000;
const stamp = (ms) => new Date(ms).toISOString().replace(/\.\d{3}Z$/, 'Z');
const b64 = (n) => Buffer.alloc(n, 7).toString('base64url');
const SUB = { endpoint: 'https://fcm.googleapis.com/fcm/send/abc', keys: { p256dh: b64(65), auth: b64(16) } };

function setup() {
  const clock = { now: T0 };
  const sent = [];
  const answers = {};                                   // blob → Ergebnis, sonst 'ok'
  const send = async (sub, blob) => {
    sent.push(blob);
    if (answers[blob] instanceof Error) throw answers[blob];
    return answers[blob] ?? 'ok';
  };
  const storage = fakeStorage();
  const device = new Device({ storage }, {}, { now: () => clock.now, send });
  const call = (method, path, body) => device.fetch(new Request(`https://relay${path}`, {
    method, body: body === undefined ? undefined : JSON.stringify(body) }));
  const items = (...list) => ({ items: list.map(([id, offsetMs]) => ({ id, fire_at: stamp(T0 + offsetMs), blob: id })) });
  return { clock, sent, answers, storage, device, call, items };
}

const IDLE = T0 + 90 * 86_400_000;

test('registering stores the subscription and arms the idle alarm', async () => {
  const { call, storage } = setup();
  assert.equal((await call('PUT', '/v1/device', SUB)).status, 204);
  assert.deepEqual((await storage.get('sub')).endpoint, SUB.endpoint);
  assert.equal(await storage.getAlarm(), IDLE);
});

test('schedule without a subscription is 409 and leaves no state', async () => {
  const { call, storage, items } = setup();
  const response = await call('PUT', '/v1/schedule', items(['a', MIN]));
  assert.equal(response.status, 409);
  assert.deepEqual(await response.json(), { error: 'no_subscription' });
  assert.deepEqual(storage.keys(), []);
  assert.equal(await storage.getAlarm(), null);
});

test('schedule replaces the previous one and arms the alarm at the earliest item', async () => {
  const { call, storage, items } = setup();
  await call('PUT', '/v1/device', SUB);
  await call('PUT', '/v1/schedule', items(['a', 5 * MIN], ['b', 9 * MIN]));
  await call('PUT', '/v1/schedule', items(['c', 2 * MIN]));
  assert.deepEqual((await storage.get('items')).map((i) => i.id), ['c']);
  assert.equal(await storage.getAlarm(), T0 + 2 * MIN);
});

test('an empty schedule clears items and leaves only the idle alarm', async () => {
  const { call, storage, items } = setup();
  await call('PUT', '/v1/device', SUB);
  await call('PUT', '/v1/schedule', items(['a', MIN]));
  assert.equal((await call('PUT', '/v1/schedule', { items: [] })).status, 204);
  assert.deepEqual(await storage.get('items'), []);
  assert.equal(await storage.getAlarm(), IDLE);
});

test('an item that is already due arms the alarm for now', async () => {
  const { call, storage, items } = setup();
  await call('PUT', '/v1/device', SUB);
  await call('PUT', '/v1/schedule', items(['late', -5 * MIN]));
  assert.equal(await storage.getAlarm(), T0);
});

test('alarm sends each due item once and sets the alarm to the next', async () => {
  const { call, storage, items, clock, sent, device } = setup();
  await call('PUT', '/v1/device', SUB);
  await call('PUT', '/v1/schedule', items(['a', MIN], ['b', 2 * MIN], ['c', 10 * MIN]));
  clock.now = T0 + 2 * MIN;
  await device.alarm();
  assert.deepEqual(sent, ['a', 'b']);
  assert.deepEqual((await storage.get('items')).map((i) => i.id), ['c']);
  assert.equal(await storage.getAlarm(), T0 + 10 * MIN);
  await device.alarm();
  assert.deepEqual(sent, ['a', 'b']);
});

test('a failing item does not stop the others', async () => {
  const { call, items, clock, sent, answers, device } = setup();
  await call('PUT', '/v1/device', SUB);
  await call('PUT', '/v1/schedule', items(['a', MIN], ['b', MIN], ['c', MIN]));
  answers.a = 'drop';
  answers.b = new Error('boom');
  clock.now = T0 + MIN;
  await device.alarm();
  assert.deepEqual(sent, ['a', 'b', 'c']);
});

test('gone deletes everything and leaves no alarm', async () => {
  const { call, storage, items, clock, answers, device } = setup();
  await call('PUT', '/v1/device', SUB);
  await call('PUT', '/v1/schedule', items(['a', MIN], ['b', MIN]));
  answers.a = 'gone';
  clock.now = T0 + MIN;
  await device.alarm();
  assert.deepEqual(storage.keys(), []);
  assert.equal(await storage.getAlarm(), null);
});

test('retry reschedules with backoff and keeps the original due time', async () => {
  const { call, storage, items, clock, answers, device } = setup();
  await call('PUT', '/v1/device', SUB);
  await call('PUT', '/v1/schedule', items(['a', MIN]));
  answers.a = 'retry';
  clock.now = T0 + MIN;
  await device.alarm();
  const [kept] = await storage.get('items');
  assert.equal(kept.attempts, 1);
  assert.equal(kept.fireAt, T0 + MIN + 30_000);
  assert.equal(kept.dueAt, T0 + MIN);
  assert.equal(await storage.getAlarm(), T0 + MIN + 30_000);
});

test('an item more than 15 minutes late is dropped without sending', async () => {
  const { call, storage, items, clock, sent, device } = setup();
  await call('PUT', '/v1/device', SUB);
  await call('PUT', '/v1/schedule', items(['a', MIN]));
  clock.now = T0 + 20 * MIN;
  await device.alarm();
  assert.deepEqual(sent, []);
  assert.deepEqual(await storage.get('items'), []);
  assert.equal(await storage.getAlarm(), IDLE);
});

test('alarm never throws, even when send throws or storage fails', async () => {
  const { call, items, clock, answers, device, storage } = setup();
  await call('PUT', '/v1/device', SUB);
  await call('PUT', '/v1/schedule', items(['a', MIN]));
  answers.a = new Error('boom');
  clock.now = T0 + MIN;
  await device.alarm();
  const get = storage.get;
  storage.get = async () => { throw new Error('storage down'); };
  await device.alarm();
  storage.get = get;
});

test('the idle alarm removes the device', async () => {
  const { call, storage, clock, device } = setup();
  await call('PUT', '/v1/device', SUB);
  clock.now = IDLE;
  await device.alarm();
  assert.deepEqual(storage.keys(), []);
  assert.equal(await storage.getAlarm(), null);
});

test('delete removes state and alarm', async () => {
  const { call, storage, items } = setup();
  await call('PUT', '/v1/device', SUB);
  await call('PUT', '/v1/schedule', items(['a', MIN]));
  assert.equal((await call('DELETE', '/v1/device')).status, 204);
  assert.deepEqual(storage.keys(), []);
  assert.equal(await storage.getAlarm(), null);
});

test('invalid body is 400 with a German message, not a throw', async () => {
  const { call, device, items } = setup();
  const bad = await call('PUT', '/v1/device', { endpoint: 'http://x', keys: {} });
  assert.equal(bad.status, 400);
  const body = await bad.json();
  assert.equal(body.error, 'invalid_request');
  assert.match(body.message, /\S/);
  await call('PUT', '/v1/device', SUB);
  assert.equal((await call('PUT', '/v1/schedule', { items: 'x' })).status, 400);
  const notJson = await device.fetch(new Request('https://relay/v1/schedule', { method: 'PUT', body: '{nope' }));
  assert.equal(notJson.status, 400);
  assert.equal((await call('PUT', '/v1/schedule', items(['a', MIN]))).status, 204);
});

test('schedule update moves the idle expiry', async () => {
  const { call, storage, clock } = setup();
  await call('PUT', '/v1/device', SUB);
  clock.now = T0 + 10 * 86_400_000;
  await call('PUT', '/v1/schedule', { items: [] });
  assert.equal(await storage.getAlarm(), IDLE + 10 * 86_400_000);
});

// --- Nebenläufigkeit: während `send` auf das Netz wartet, laufen andere Anfragen (offene Eingabe-Schranke).
function gated() {
  const ctx = setup();
  let release;
  const gate = new Promise((resolve) => { release = resolve; });
  const device = new Device({ storage: ctx.storage }, {}, {
    now: () => ctx.clock.now,
    send: async (sub, blob) => { ctx.sent.push(blob); await gate; return ctx.answers[blob] ?? 'ok'; },
  });
  const call = (method, path, body) => device.fetch(new Request(`https://relay${path}`, {
    method, body: body === undefined ? undefined : JSON.stringify(body) }));
  return { ...ctx, device, call, release };
}

test('a schedule uploaded while a push is in flight survives the alarm (I1)', async () => {
  const { call, items, clock, storage, device, release } = gated();
  await call('PUT', '/v1/device', SUB);
  await call('PUT', '/v1/schedule', items(['a', MIN]));
  clock.now = T0 + MIN;
  const running = device.alarm();
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal((await call('PUT', '/v1/schedule', items(['n1', 10 * MIN]))).status, 204);
  release();
  await running;
  assert.deepEqual((await storage.get('items')).map((i) => i.id), ['n1']);
  assert.equal(await storage.getAlarm(), T0 + 10 * MIN);
});

test('a gone for the old endpoint does not wipe a subscription registered meanwhile (I1)', async () => {
  const { call, items, clock, storage, device, release, answers } = gated();
  await call('PUT', '/v1/device', SUB);
  await call('PUT', '/v1/schedule', items(['a', MIN]));
  answers.a = 'gone';
  clock.now = T0 + MIN;
  const running = device.alarm();
  await new Promise((resolve) => setImmediate(resolve));
  const fresh = { ...SUB, endpoint: 'https://fcm.googleapis.com/fcm/send/rotated' };
  await call('PUT', '/v1/device', fresh);
  release();
  await running;
  assert.equal((await storage.get('sub')).endpoint, fresh.endpoint);
});

test('a delete during an alarm leaves nothing behind (I1)', async () => {
  const { call, items, clock, storage, device, release } = gated();
  await call('PUT', '/v1/device', SUB);
  await call('PUT', '/v1/schedule', items(['a', MIN], ['b', 20 * MIN]));
  clock.now = T0 + MIN;
  const running = device.alarm();
  await new Promise((resolve) => setImmediate(resolve));
  await call('DELETE', '/v1/device');
  release();
  await running;
  assert.deepEqual(storage.keys(), []);
  assert.equal(await storage.getAlarm(), null);
});

test('the 409 answer still reads the request body (I3)', async () => {
  const { device } = setup();
  const request = new Request('https://relay/v1/schedule', { method: 'PUT', body: '{"items":[]}' });
  assert.equal((await device.fetch(request)).status, 409);
  assert.equal(request.bodyUsed, true);
});

// --- Testroute (#340) ---------------------------------------------------------------------------

import { TEST_PAYLOAD } from '../src/push.js';

test('a test push sends the fixed payload at once and leaves schedule and alarm alone', async () => {
  const { call, sent, storage, items } = setup();
  await call('PUT', '/v1/device', SUB);
  await call('PUT', '/v1/schedule', items(['a', 5 * MIN]));
  const before = { items: await storage.get('items'), alarm: await storage.getAlarm(), idle: await storage.get('idle') };
  const response = await call('POST', '/v1/test');
  assert.equal(response.status, 204);
  assert.deepEqual(sent, [TEST_PAYLOAD]);
  assert.deepEqual(await storage.get('items'), before.items);
  assert.equal(await storage.getAlarm(), before.alarm);
  assert.equal(await storage.get('idle'), before.idle);
});

test('a test push without a subscription is 409 and sends nothing', async () => {
  const { call, sent, storage } = setup();
  const response = await call('POST', '/v1/test');
  assert.equal(response.status, 409);
  assert.deepEqual(await response.json(), { error: 'no_subscription' });
  assert.deepEqual(sent, []);
  assert.deepEqual(storage.keys(), []);
});

test('a dead subscription is 410 and the object cleans up', async () => {
  const { call, answers, storage } = setup();
  await call('PUT', '/v1/device', SUB);
  answers[TEST_PAYLOAD] = 'gone';
  const response = await call('POST', '/v1/test');
  assert.equal(response.status, 410);
  assert.deepEqual(await response.json(), { error: 'gone' });
  assert.deepEqual(storage.keys(), []);
  assert.equal(await storage.getAlarm(), null);
});

test('a push service that refuses or fails is 502 and the subscription stays', async () => {
  for (const answer of ['retry', 'drop', new Error('kaputt')]) {
    const { call, answers, storage } = setup();
    await call('PUT', '/v1/device', SUB);
    answers[TEST_PAYLOAD] = answer;
    const response = await call('POST', '/v1/test');
    assert.equal(response.status, 502);
    assert.deepEqual(await response.json(), { error: 'push_failed' });
    assert.ok(await storage.get('sub'));
  }
});

test('a second test within ten seconds is 429 too_soon and sends nothing', async () => {
  const { call, sent, clock } = setup();
  await call('PUT', '/v1/device', SUB);
  assert.equal((await call('POST', '/v1/test')).status, 204);
  clock.now += 9_000;
  const again = await call('POST', '/v1/test');
  assert.equal(again.status, 429);
  assert.deepEqual(await again.json(), { error: 'too_soon' });
  assert.equal(sent.length, 1);
  clock.now += 1_000;
  assert.equal((await call('POST', '/v1/test')).status, 204);
  assert.equal(sent.length, 2);
});

test('the cooldown belongs to the object: another device can test right away', async () => {
  const one = setup();
  const two = setup();
  await one.call('PUT', '/v1/device', SUB);
  await two.call('PUT', '/v1/device', SUB);
  assert.equal((await one.call('POST', '/v1/test')).status, 204);
  assert.equal((await two.call('POST', '/v1/test')).status, 204);
});

test('a failed test does not start the cooldown, so the next try goes through', async () => {
  const { call, answers, clock } = setup();
  await call('PUT', '/v1/device', SUB);
  answers[TEST_PAYLOAD] = 'retry';
  assert.equal((await call('POST', '/v1/test')).status, 502);
  delete answers[TEST_PAYLOAD];
  clock.now += 1_000;
  assert.equal((await call('POST', '/v1/test')).status, 204);
});

test('the test route ignores a body and still answers', async () => {
  const { call } = setup();
  await call('PUT', '/v1/device', SUB);
  assert.equal((await call('POST', '/v1/test', { egal: true })).status, 204);
});

test('the other methods on the test path are unknown', async () => {
  const { call } = setup();
  assert.equal((await call('GET', '/v1/test')).status, 404);
});
