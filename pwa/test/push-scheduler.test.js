// pwa/test/push-scheduler.test.js
import { test } from 'node:test';
import assert from 'node:assert/strict';

import { RETRY_DELAYS_MS, createPushScheduler } from '../push-scheduler.js';

/** Ein Versand, den der Test von Hand beendet, und Timer, die er von Hand auslöst. */
function setup({ outcomes = [] } = {}) {
  const runs = [];
  const timers = [];
  const run = () => new Promise((resolve, reject) => {
    const preset = outcomes.shift();
    if (preset !== undefined) {
      runs.push({ done: true });
      if (preset instanceof Error) reject(preset); else resolve(preset);
      return;
    }
    runs.push({ resolve, reject, done: false });
  });
  const scheduler = createPushScheduler({
    run,
    setTimer: (fn, ms) => { const timer = { fn, ms, cleared: false }; timers.push(timer); return timer; },
    clearTimer: (timer) => { if (timer) timer.cleared = true; },
  });
  const live = () => timers.filter((timer) => !timer.cleared && !timer.fired);
  const fire = (timer) => { timer.fired = true; timer.fn(); };
  return { scheduler, runs, timers, live, fire };
}

const settle = () => new Promise((resolve) => setTimeout(resolve, 0));

test('a request sends at once, without a delay timer', async () => {
  const { scheduler, runs, timers } = setup();

  scheduler.request();

  assert.equal(runs.length, 1);
  assert.equal(timers.length, 0);
});

test('requests during a running send are not lost: exactly one more send follows', async () => {
  const { scheduler, runs } = setup();
  scheduler.request();
  scheduler.request();
  scheduler.request();
  assert.equal(runs.length, 1);                    // nie zwei zugleich

  runs[0].resolve('sent');
  await settle();

  assert.equal(runs.length, 2);                    // der Stand nach dem letzten Speichern geht hinaus
  runs[1].resolve('unchanged');
  await settle();
  assert.equal(runs.length, 2);                    // und danach nichts mehr
});

test('idle resolves only when nothing is running or queued', async () => {
  const { scheduler, runs } = setup();
  scheduler.request();
  scheduler.request();
  let idle = false;
  void scheduler.idle().then(() => { idle = true; });
  await settle();
  assert.equal(idle, false);

  runs[0].resolve('sent');
  await settle();
  assert.equal(idle, false);                       // der nachgeholte Lauf läuft noch
  runs[1].resolve('sent');
  await settle();
  assert.equal(idle, true);
});

test('idle resolves at once when nothing was requested', async () => {
  const { scheduler } = setup();
  await scheduler.idle();
});

test('a failed send is retried with growing delays and then given up', async () => {
  const { scheduler, runs, live, fire } = setup({ outcomes: ['retry', 'retry', 'retry', 'retry'] });

  scheduler.request();
  await settle();
  for (const expected of RETRY_DELAYS_MS) {
    assert.deepEqual(live().map((timer) => timer.ms), [expected]);
    fire(live()[0]);
    await settle();
  }

  assert.equal(runs.length, 1 + RETRY_DELAYS_MS.length);
  assert.deepEqual(live(), []);                    // aufgegeben, bis der nächste Auslöser kommt
});

test('a throwing send counts as failed and never rejects', async () => {
  const { scheduler, live } = setup({ outcomes: [new Error('kaputt')] });

  scheduler.request();
  await scheduler.idle();

  assert.deepEqual(live().map((timer) => timer.ms), [RETRY_DELAYS_MS[0]]);
});

test('a success after a failure stops retrying and resets the delays', async () => {
  const { scheduler, live, fire } = setup({ outcomes: ['retry', 'sent', 'retry'] });
  scheduler.request();
  await settle();
  fire(live()[0]);
  await settle();
  assert.deepEqual(live(), []);

  scheduler.request();
  await settle();
  assert.deepEqual(live().map((timer) => timer.ms), [RETRY_DELAYS_MS[0]]);   // wieder die erste Stufe
});

test('a new request while waiting for a retry sends now and drops the timer', async () => {
  const { scheduler, runs, timers, live } = setup({ outcomes: ['retry'] });
  scheduler.request();
  await settle();
  assert.equal(live().length, 1);

  scheduler.request();

  assert.equal(runs.length, 2);
  assert.equal(timers[0].cleared, true);
});

test('a retry timer that fires while a send is running does not start a second one', async () => {
  const { scheduler, runs, timers, fire } = setup({ outcomes: ['retry'] });
  scheduler.request();
  await settle();
  const stale = timers[0];
  scheduler.request();                             // läuft jetzt (offen)
  fire(stale);                                     // der alte Timer kommt trotzdem noch

  assert.equal(runs.length, 2);
});

test('after stop nothing is sent any more: no queued send, no retry, no new request', async () => {
  const { scheduler, runs, live } = setup();
  scheduler.request();
  scheduler.request();

  scheduler.stop();
  runs[0].resolve('retry');
  await settle();
  scheduler.request();

  assert.equal(runs.length, 1);
  assert.deepEqual(live(), []);
  await scheduler.idle();
});
