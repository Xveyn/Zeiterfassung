// relay/test/box.test.js
import assert from 'node:assert/strict';
import test from 'node:test';
import { Box } from '../src/box.js';
import { encodeOk, encodeSlot, FRAME } from '../src/frames.js';
import { LIMITS } from '../src/validate.js';
import { fakeContext, fakePlatform } from './box-fakes.js';

const T0 = Date.parse('2026-11-02T12:00:00Z');
const DAY = 86_400_000;
const IDLE = T0 + LIMITS.idleDays * DAY;

// Erwarteter `ver` des ersten put zum Zeitpunkt `ms` (Uhr als Untergrenze, s. VER_EPOCH in box.js).
const verAt = (ms) => Math.max(1, Math.floor((ms - Date.UTC(2026, 0, 1)) / 1000));
const V0 = verAt(T0);

const put = (...bytes) => new Uint8Array([FRAME.put, ...bytes]).buffer;

function setup() {
  const clock = { now: T0 };
  const ctx = fakeContext();
  let setAlarmCalls = 0;
  const realSetAlarm = ctx.storage.setAlarm;
  ctx.storage.setAlarm = async (ms) => { setAlarmCalls += 1; return realSetAlarm(ms); };
  let putCalls = 0;
  const realPut = ctx.storage.put;
  ctx.storage.put = async (key, value) => { putCalls += 1; return realPut(key, value); };
  const box = new Box(ctx, {}, { now: () => clock.now, platform: fakePlatform() });
  const request = (method, path, headers = {}) => box.fetch(new Request(`https://relay${path}`, { method, headers }));
  /** Verbindet eine Rolle und liefert den Server-Socket, den die Box angenommen hat. */
  const connect = async (role, have) => {
    const query = have === undefined ? `role=${role}` : `role=${role}&have=${have}`;
    const response = await request('GET', `/v1/box/ws?${query}`, { upgrade: 'websocket' });
    assert.equal(response.status, 101);
    assert.equal(response.protocol, 'zeit.v1');
    return ctx.sockets.at(-1).ws;
  };
  return { clock, ctx, box, request, connect, alarms: () => setAlarmCalls, puts: () => putCalls };
}

const scenarios = {
  async 'connecting without upgrade header is 426'() {
    const { request, ctx } = setup();
    const response = await request('GET', '/v1/box/ws?role=phone');
    assert.equal(response.status, 426);
    assert.equal(ctx.sockets.length, 0);
  },

  async 'invalid role or have is 400 and accepts nothing'() {
    const { request, ctx } = setup();
    for (const query of ['role=tablet', '', 'role=phone&have=-1', 'role=desktop&have=abc']) {
      const response = await request('GET', `/v1/box/ws?${query}`, { upgrade: 'websocket' });
      assert.equal(response.status, 400, query);
      assert.equal((await response.json()).error, 'invalid_request');
    }
    assert.equal(ctx.sockets.length, 0);
    assert.deepEqual(ctx.storage.keys(), []);
  },

  async 'unknown route is 404'() {
    const { request } = setup();
    const response = await request('GET', '/v1/box/other');
    assert.equal(response.status, 404);
    assert.deepEqual(await response.json(), { error: 'not_found' });
  },

  async 'put from phone writes req, answers ok(ver 1), and delivers slot(ver 1) to the connected desktop'() {
    const { box, ctx, connect } = setup();
    const desktop = await connect('desktop');
    const phone = await connect('phone');
    await box.webSocketMessage(phone, put(7, 8, 9));
    const stored = await ctx.storage.get('req');
    assert.equal(stored.ver, V0);
    assert.deepEqual([...stored.data], [7, 8, 9]);
    assert.deepEqual(phone.sent, [encodeOk(V0)]);
    assert.deepEqual(desktop.sent, [encodeSlot(V0, new Uint8Array([7, 8, 9]))]);
  },

  async 'second put replaces: ver 2, storage holds only the newer payload'() {
    const { box, ctx, connect } = setup();
    const phone = await connect('phone');
    await box.webSocketMessage(phone, put(1));
    await box.webSocketMessage(phone, put(2, 2));
    const stored = await ctx.storage.get('req');
    assert.equal(stored.ver, V0 + 1);
    assert.deepEqual([...stored.data], [2, 2]);
    assert.deepEqual(ctx.storage.keys().sort(), ['idle', 'req']);
    assert.deepEqual(phone.sent.at(-1), encodeOk(V0 + 1));
  },

  async 'put with no peer connected stores and acks; peer connecting later gets the slot'() {
    const { box, connect } = setup();
    const phone = await connect('phone');
    await box.webSocketMessage(phone, put(5));
    assert.deepEqual(phone.sent, [encodeOk(V0)]);
    const desktop = await connect('desktop');
    assert.deepEqual(desktop.sent, [encodeSlot(V0, new Uint8Array([5]))]);
  },

  async 'connecting with have >= ver delivers nothing; have < ver delivers once'() {
    const { box, connect } = setup();
    const phone = await connect('phone');
    await box.webSocketMessage(phone, put(1));
    await box.webSocketMessage(phone, put(2));                // ver V0 + 1
    assert.deepEqual((await connect('desktop', V0 + 1)).sent, []);
    assert.deepEqual((await connect('desktop', V0 + 2)).sent, []);
    assert.deepEqual((await connect('desktop', V0)).sent, [encodeSlot(V0 + 1, new Uint8Array([2]))]);
  },

  async 'desktop put writes res and goes to the phone, never to the desktop itself'() {
    const { box, ctx, connect } = setup();
    const phone = await connect('phone');
    const desktop = await connect('desktop');
    await box.webSocketMessage(desktop, put(4, 4));
    assert.equal((await ctx.storage.get('res')).ver, V0);
    assert.equal(await ctx.storage.get('req'), undefined);
    assert.deepEqual(phone.sent, [encodeSlot(V0, new Uint8Array([4, 4]))]);
    assert.deepEqual(desktop.sent, [encodeOk(V0)]);
  },

  async 'second connection of the same role closes the first with 1000 and keeps slots'() {
    const { box, ctx, connect } = setup();
    const desktop = await connect('desktop');
    await box.webSocketMessage(desktop, put(3));
    const first = await connect('phone');
    const second = await connect('phone');
    assert.deepEqual(first.closed, [1000, 'replaced']);
    assert.equal(second.closed, null);
    assert.equal(desktop.closed, null);
    assert.deepEqual(second.sent, [encodeSlot(V0, new Uint8Array([3]))]);
    assert.equal((await ctx.storage.get('res')).ver, V0);
    // Die Plattform meldet das Schließen des ersetzten Sockets: harmlos.
    await box.webSocketClose(first, 1000, 'replaced', true);
    assert.equal(second.closed, null);
    assert.equal((await ctx.storage.get('res')).ver, V0);
    await box.webSocketMessage(desktop, put(6));
    assert.deepEqual(second.sent.at(-1), encodeSlot(V0 + 1, new Uint8Array([6])));
    assert.equal(first.sent.length, 1);
  },

  async 'message of maxFrame+1 bytes closes 1009 and writes nothing; maxFrame bytes is accepted'() {
    const { box, ctx, connect } = setup();
    const tooBig = await connect('phone');
    const big = new Uint8Array(LIMITS.maxFrame + 1);
    big[0] = FRAME.put;
    let reads = 0;
    const realGet = ctx.storage.get;
    ctx.storage.get = async (key) => { reads += 1; return realGet(key); };
    await box.webSocketMessage(tooBig, big.buffer);
    assert.equal(tooBig.closed[0], 1009);
    assert.equal(reads, 0);
    assert.deepEqual(ctx.storage.keys(), []);
    assert.equal(await ctx.storage.getAlarm(), null);

    const phone = await connect('phone');
    const exact = new Uint8Array(LIMITS.maxFrame);
    exact[0] = FRAME.put;
    await box.webSocketMessage(phone, exact.buffer);
    assert.equal(phone.closed, null);
    assert.equal((await ctx.storage.get('req')).data.length, LIMITS.maxFrame - 1);
  },

  async 'text message closes 1003; unknown type byte is ignored (no write, no close)'() {
    const { box, ctx, connect } = setup();
    const text = await connect('phone');
    await box.webSocketMessage(text, 'hello');
    assert.equal(text.closed[0], 1003);
    const phone = await connect('phone');
    await box.webSocketMessage(phone, new Uint8Array([0x7f, 1, 2]).buffer);
    await box.webSocketMessage(phone, new Uint8Array([FRAME.ok, 0, 0, 0, 1]).buffer);
    await box.webSocketMessage(phone, new ArrayBuffer(0));
    assert.equal(phone.closed, null);
    assert.deepEqual(phone.sent, []);
    assert.deepEqual(ctx.storage.keys(), []);
  },

  async 'put arms the idle alarm once; a second put the same day does not call setAlarm again'() {
    const { box, ctx, clock, connect, alarms, puts } = setup();
    const phone = await connect('phone');
    await box.webSocketMessage(phone, put(1));
    assert.equal(puts(), 2);                                  // Slot + idle
    assert.equal(await ctx.storage.get('idle'), IDLE);
    assert.equal(await ctx.storage.getAlarm(), IDLE);
    clock.now = T0 + 23 * 3_600_000;
    await box.webSocketMessage(phone, put(2));
    assert.equal(alarms(), 1);
    assert.equal(puts(), 3);                                  // nur der Slot
    assert.equal(await ctx.storage.get('idle'), IDLE);
  },

  async 'put after more than a day moves the alarm again'() {
    const { box, ctx, clock, connect, alarms } = setup();
    const phone = await connect('phone');
    await box.webSocketMessage(phone, put(1));
    clock.now = T0 + DAY + 1;
    await box.webSocketMessage(phone, put(2));
    assert.equal(alarms(), 2);
    assert.equal(await ctx.storage.get('idle'), IDLE + DAY + 1);
    assert.equal(await ctx.storage.getAlarm(), IDLE + DAY + 1);
  },

  async 'alarm() before idle re-arms for idle; at/after idle wipes slots and sockets'() {
    const { box, ctx, clock, connect } = setup();
    const phone = await connect('phone');
    const desktop = await connect('desktop');
    await box.webSocketMessage(phone, put(1));
    clock.now = IDLE - 1;
    await box.alarm();
    assert.equal(await ctx.storage.getAlarm(), IDLE);
    assert.equal((await ctx.storage.get('req')).ver, V0);
    assert.equal(phone.closed, null);
    clock.now = IDLE;
    await box.alarm();
    assert.deepEqual(ctx.storage.keys(), []);
    assert.equal(await ctx.storage.getAlarm(), null);
    assert.equal(phone.closed[0], 1000);
    assert.equal(desktop.closed[0], 1000);
  },

  async 'DELETE /v1/box wipes storage, alarm and closes all sockets with 1000'() {
    const { box, ctx, request, connect } = setup();
    const phone = await connect('phone');
    const desktop = await connect('desktop');
    await box.webSocketMessage(phone, put(1));
    await box.webSocketMessage(desktop, put(2));
    const response = await request('DELETE', '/v1/box');
    assert.equal(response.status, 204);
    assert.deepEqual(ctx.storage.keys(), []);
    assert.equal(await ctx.storage.getAlarm(), null);
    assert.equal(phone.closed[0], 1000);
    assert.equal(desktop.closed[0], 1000);
    // Die Plattform meldet danach das Schließen beider Sockets: harmlos.
    await box.webSocketClose(phone, 1000, '', true);
    await box.webSocketError(desktop);
    assert.deepEqual(ctx.storage.keys(), []);
  },

  async 'ver after an idle wipe or DELETE /v1/box is greater than any ver before it'() {
    const { box, ctx, clock, connect, request } = setup();
    const phone = await connect('phone');
    for (let i = 0; i < 40; i += 1) await box.webSocketMessage(phone, put(i));
    const before = (await ctx.storage.get('req')).ver;          // V0 + 39
    assert.equal(before, V0 + 39);

    clock.now = IDLE;                                           // Leerlauf: alles wird geräumt
    await box.alarm();
    assert.deepEqual(ctx.storage.keys(), []);
    const afterIdle = await connect('phone');
    const desktop = await connect('desktop', before);           // `have` aus der Zeit vor dem Aufräumen
    await box.webSocketMessage(afterIdle, put(1));
    const idleVer = (await ctx.storage.get('req')).ver;
    assert.ok(idleVer > before);
    assert.deepEqual(desktop.sent, [encodeSlot(idleVer, new Uint8Array([1]))]);
    assert.deepEqual((await connect('desktop', before)).sent, [encodeSlot(idleVer, new Uint8Array([1]))]);

    clock.now += 1000;
    await request('DELETE', '/v1/box');
    const afterDelete = await connect('phone');
    await box.webSocketMessage(afterDelete, put(2));
    assert.ok((await ctx.storage.get('req')).ver > idleVer);
  },

  async 'two puts within the same second get strictly increasing ver'() {
    const { box, ctx, clock, connect } = setup();
    const phone = await connect('phone');
    await box.webSocketMessage(phone, put(1));
    clock.now = T0 + 999;                                        // dieselbe Sekunde
    await box.webSocketMessage(phone, put(2));
    assert.equal((await ctx.storage.get('req')).ver, V0 + 1);
    assert.deepEqual(phone.sent, [encodeOk(V0), encodeOk(V0 + 1)]);
  },

  async 'verAt pins VER_EPOCH to 2026-01-01 UTC'() {
    // Fester Wert für die Testuhr (2026-11-02T12:00:00Z = 305,5 Tage nach 2026-01-01): hält VER_EPOCH in box.js fest.
    assert.equal(verAt(T0), 26_395_200);
    const { box, ctx, connect } = setup();
    await box.webSocketMessage(await connect('phone'), put(1));
    assert.equal((await ctx.storage.get('req')).ver, 26_395_200);
  },

  async 'put over putsPerMinute closes 1008 and writes nothing'() {
    const { box, ctx, connect } = setup();
    const phone = await connect('phone');
    const desktop = await connect('desktop');
    for (let i = 0; i < LIMITS.putsPerMinute; i += 1) await box.webSocketMessage(phone, put(i));
    assert.equal(phone.closed, null);
    const last = await ctx.storage.get('req');
    let reads = 0;
    const realGet = ctx.storage.get;
    ctx.storage.get = async (key) => { reads += 1; return realGet(key); };
    await box.webSocketMessage(phone, put(0xff));
    assert.deepEqual(phone.closed, [1008, 'too many']);
    assert.equal(reads, 0);
    ctx.storage.get = realGet;
    assert.deepEqual(await ctx.storage.get('req'), last);
    assert.equal(desktop.sent.length, LIMITS.putsPerMinute);
    assert.equal(phone.sent.length, LIMITS.putsPerMinute);
  },

  async 'budget refills over time (a put after 60 s is accepted again)'() {
    const { box, ctx, clock, connect } = setup();
    const phone = await connect('phone');
    for (let i = 0; i < LIMITS.putsPerMinute; i += 1) await box.webSocketMessage(phone, put(i));
    clock.now = T0 + 60_000;
    for (let i = 0; i < LIMITS.putsPerMinute; i += 1) await box.webSocketMessage(phone, put(i));
    assert.equal(phone.closed, null);
    assert.equal(phone.sent.length, 2 * LIMITS.putsPerMinute);
    clock.now += 1_000;                                          // eine Sekunde = ein Token
    await box.webSocketMessage(phone, put(1));
    assert.equal(phone.closed, null);
    await box.webSocketMessage(phone, put(2));
    assert.deepEqual(phone.closed, [1008, 'too many']);
    assert.equal(phone.sent.length, 2 * LIMITS.putsPerMinute + 1);
    assert.ok((await ctx.storage.get('req')) !== undefined);
  },

  async 'the budget is per socket (a second socket is not throttled by the first)'() {
    const { box, ctx, connect } = setup();
    const phone = await connect('phone');
    const desktop = await connect('desktop');
    for (let i = 0; i <= LIMITS.putsPerMinute; i += 1) await box.webSocketMessage(phone, put(i));
    assert.deepEqual(phone.closed, [1008, 'too many']);
    await box.webSocketMessage(desktop, put(9));
    assert.equal(desktop.closed, null);
    assert.equal((await ctx.storage.get('res')).ver, V0);
    // Auch ein neuer Socket derselben Rolle beginnt mit vollem Eimer.
    const again = await connect('phone');
    await box.webSocketMessage(again, put(7));
    assert.equal(again.closed, null);
    assert.deepEqual([...(await ctx.storage.get('req')).data], [7]);
  },

  async 'no throttle state survives closing a socket'() {
    const { box, connect, request } = setup();
    const a = await connect('phone');
    const b = await connect('desktop');
    await box.webSocketMessage(a, put(1));
    await box.webSocketMessage(b, put(1));
    assert.equal(box.buckets.size, 2);
    await box.webSocketClose(a, 1000, '', true);
    await box.webSocketError(b);
    assert.equal(box.buckets.size, 0);
    const c = await connect('phone');
    await box.webSocketMessage(c, put(1));
    await connect('phone');                                      // ersetzt c
    assert.equal(box.buckets.size, 0);
    const d = await connect('desktop');
    await box.webSocketMessage(d, put(1));
    await request('DELETE', '/v1/box');
    assert.equal(box.buckets.size, 0);
  },
};

for (const [name, run] of Object.entries(scenarios)) test(name, run);

test('no console output on any path', async (t) => {
  const calls = [];
  for (const method of ['log', 'info', 'warn', 'error', 'debug']) {
    t.mock.method(console, method, (...args) => calls.push([method, args]));
  }
  for (const run of Object.values(scenarios)) await run();
  assert.equal(calls.length, 0);
});
