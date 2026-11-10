// pwa/test/push-sync.test.js
// Das Szenario aus #507: unterwegs, der Desktop ist aus, die Zeit wird am Handy eingetragen. Die Erinnerung
// darf dann nicht mehr kommen. Echter Store und echte Planung, nur der Relay ist eine Attrappe.
import { test } from 'node:test';
import assert from 'node:assert/strict';

import { Store } from '../store.js';
import { createMemoryAdapter } from '../memory-adapter.js';
import { memoryKeyStore, open } from '../push-blob.js';
import { RelayError } from '../relay-client.js';
import { localIsoDate } from '../minutes.js';
import { syncPushPlan } from '../push-sync.js';

const SECRET = 'R'.repeat(43);
const SUBSCRIPTION = { endpoint: 'https://fcm.googleapis.com/fcm/send/abc', keys: { p256dh: 'p', auth: 'a' } };
const REMINDERS = { reservation: { enabled: true, minutes_before: 15 }, send: { enabled: false, at: [] } };
const RESERVED = { start: '13:00', end: '17:00', kategorie: 'Support' };
const WORKED = { start: '13:00', end: '17:00', pause: 0, kategorie: 'Support' };

/** Ein Handy am Vormittag: gekoppelt, Push an, eine Reservierung heute 13–17 Uhr. Der Desktop antwortet nie:
 *  kein Abgleich läuft, der Tag bleibt „nicht übertragen“. */
async function phone({ hour = 9, meta = {} } = {}) {
  const clock = { now: new Date(2026, 10, 10, hour, 0) };
  const today = localIsoDate(clock.now);
  const store = new Store(createMemoryAdapter(), () => clock.now);
  await store.load();
  await store.setMeta({ device_id: 'phone-0001', token: 'T0', key: 'a'.repeat(43), transport: 'relay', box_secret: 'B'.repeat(43),
    reservations_enabled: true, reminders: REMINDERS, push_enabled: true, relay_secret: SECRET, ...meta });
  await store.saveReservation(today, [RESERVED]);
  const keys = memoryKeyStore();
  const relay = { plans: [], fail: null, registered: 0,
    async putSchedule(secret, items) {
      if (relay.fail) throw relay.fail;
      relay.plans.push({ secret, items });
    },
    async registerDevice() { relay.registered += 1; },
  };
  const sync = (over = {}) => syncPushPlan({
    store, state: 'on', client: relay, keys, getSubscription: async () => SUBSCRIPTION, now: () => clock.now, ...over });
  const kinds = async (plan) => Promise.all(plan.items.map(async (item) => (await open(keys, item.blob)).k));
  return { store, relay, sync, clock, today, keys, kinds };
}

test('before anything is entered the relay gets both reminders of the reservation', async () => {
  const { relay, sync, kinds } = await phone();

  assert.equal(await sync(), 'sent');

  assert.equal(relay.plans.length, 1);
  assert.equal(relay.plans[0].secret, SECRET);
  assert.deepEqual((await kinds(relay.plans[0])).sort(), ['missed', 'upcoming']);
});

test('entering the time on the phone removes the reminders at the relay, without any desktop', async () => {
  const { store, relay, sync, today } = await phone();
  await sync();

  await store.saveDay(today, [WORKED]);
  const result = await sync();

  assert.equal(result, 'sent');
  assert.deepEqual(relay.plans.at(-1).items, []);                 // ein leerer Plan ersetzt den alten: nichts klingelt mehr
  assert.equal(store.getDay(today).dirty, true);                  // der Desktop hat den Tag nie gesehen
});

test('the time entered before the first plan ever went out never produces a reminder', async () => {
  const { store, relay, sync, today } = await phone();
  await store.saveDay(today, [WORKED]);

  await sync();

  assert.deepEqual(relay.plans.at(-1)?.items ?? [], []);
});

test('a time of another category or without one keeps the reminder (same rule as the desktop)', async () => {
  const { store, relay, sync, today } = await phone();
  await store.saveDay(today, [{ ...WORKED, kategorie: 'Projekt' }, { start: '08:00', end: '09:00', pause: 0, kategorie: '' }]);

  await sync();

  assert.equal(relay.plans.at(-1).items.length, 2);
});

test('clearing the day again brings the reminder back', async () => {
  const { store, relay, sync, today } = await phone();
  await store.saveDay(today, [WORKED]);
  await sync();
  assert.deepEqual(relay.plans.at(-1)?.items ?? [], []);

  await store.clearDay(today);
  await sync();

  assert.equal(relay.plans.at(-1).items.length, 2);
});

test('with two reservations only the one whose category was entered falls away', async () => {
  const { store, relay, sync, today, kinds, keys } = await phone();
  await store.saveReservation(today, [RESERVED, { start: '17:30', end: '19:00', kategorie: 'Projekt' }]);
  await store.saveDay(today, [WORKED]);

  await sync();

  const plan = relay.plans.at(-1);
  assert.deepEqual((await kinds(plan)).sort(), ['missed', 'upcoming']);
  for (const item of plan.items) assert.equal((await open(keys, item.blob)).c, 'Projekt');
});

test('an unchanged plan is not sent again', async () => {
  const { relay, sync } = await phone();
  await sync();

  assert.equal(await sync(), 'unchanged');
  assert.equal(relay.plans.length, 1);
});

test('a failed send leaves the plan as not sent, so the next attempt sends the current state', async () => {
  const { store, relay, sync, today } = await phone();
  await sync();
  await store.saveDay(today, [WORKED]);
  relay.fail = new RelayError('offline');

  await assert.rejects(sync(), (error) => error instanceof RelayError);
  relay.fail = null;
  const result = await sync();

  assert.equal(result, 'sent');
  assert.deepEqual(relay.plans.at(-1).items, []);
});

test('nothing is sent while push is off, the desktop sends no reminders block or there is no relay secret', async () => {
  for (const over of [{ state: 'off' }, { state: 'denied' }]) {
    const { relay, sync } = await phone();
    assert.equal(await sync(over), 'skipped');
    assert.equal(relay.plans.length, 0);
  }
  for (const meta of [{ reminders: null }, { relay_secret: '' }]) {
    const { relay, sync } = await phone({ meta });
    assert.equal(await sync(), 'skipped');
    assert.equal(relay.plans.length, 0);
  }
});

test('a successful send remembers the signature and the time; a skipped or failed one does not', async () => {
  const { store, sync, relay, clock } = await phone();
  relay.fail = new RelayError('server', 503);
  await assert.rejects(sync());
  assert.equal(store.getMeta().push_signature, null);

  relay.fail = null;
  await sync();

  assert.equal(typeof store.getMeta().push_signature, 'string');
  assert.equal(store.getMeta().push_sent_at, clock.now.getTime());
});

test('the abort check runs right before the relay call and before the meta write', async () => {
  const { store, relay, sync } = await phone();
  let checks = 0;

  const result = await sync({ aborted: () => { checks += 1; return checks >= 1; } });

  assert.equal(result, 'skipped');
  assert.equal(relay.plans.length, 0);
  assert.equal(store.getMeta().push_signature, null);
});

test('after the reservation has ended nothing is planned for it any more', async () => {
  const { relay, sync } = await phone({ hour: 18 });

  await sync();

  assert.deepEqual(relay.plans.at(-1)?.items ?? [], []);
});
