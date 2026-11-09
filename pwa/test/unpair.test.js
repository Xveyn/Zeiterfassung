// pwa/test/unpair.test.js
import { test } from 'node:test';
import assert from 'node:assert/strict';

import { createUnpairRunner } from '../unpair.js';

function setup(over = {}) {
  const calls = [];
  const logs = [];
  const step = (name, result) => async () => { calls.push(name); return result; };
  const steps = {
    notifyDesktop: step('notifyDesktop', 'queued'),
    disablePush: step('disablePush'),
    clearSession: step('clearSession'),
    clearDebug: step('clearDebug'),
    wipe: step('wipe'),
    reload: step('reload'),
    log: (label, error) => logs.push([label, String(error?.message ?? error)]),
    ...over,
  };
  return { calls, logs, run: createUnpairRunner(steps) };
}

test('the steps run in the specified order and the result carries the desktop state', async () => {
  const { calls, run } = setup();

  const result = await run();

  assert.deepEqual(calls, ['notifyDesktop', 'disablePush', 'clearSession', 'clearDebug', 'wipe', 'reload']);
  assert.deepEqual(result, { ok: true, notified: 'queued' });
});

for (const name of ['notifyDesktop', 'disablePush', 'clearSession', 'clearDebug']) {
  test(`a failing ${name} is logged and stops nothing`, async () => {
    const calls = [];
    const { logs, run } = setup({ [name]: async () => { calls.push(name); throw new Error(`${name} kaputt`); } });

    const result = await run();

    assert.equal(result.ok, true);
    assert.equal(calls.includes(name), true);
    assert.equal(logs.length, 1);
    assert.match(logs[0][1], /kaputt/);
  });
}

test('a throwing notifyDesktop reads as failed', async () => {
  const { run } = setup({ notifyDesktop: async () => { throw new Error('x'); } });
  assert.deepEqual(await run(), { ok: true, notified: 'failed' });
});

test('a failing wipe is not ok, never reloads and reports the error', async () => {
  const calls = [];
  const { run } = setup({ wipe: async () => { calls.push('wipe'); throw new Error('IndexedDB voll'); },
    reload: async () => { calls.push('reload'); } });

  const result = await run();

  assert.equal(result.ok, false);
  assert.equal(result.error.message, 'IndexedDB voll');
  assert.deepEqual(calls, ['wipe']);
});

test('a second call while the first runs shares it: one notification, one wipe', async () => {
  const calls = [];
  let release;
  const gate = new Promise((resolve) => { release = resolve; });
  const { run } = setup({
    notifyDesktop: async () => { calls.push('notifyDesktop'); await gate; return 'sent'; },
    wipe: async () => { calls.push('wipe'); },
  });

  const first = run();
  const second = run();
  release();
  const [a, b] = await Promise.all([first, second]);

  assert.deepEqual(calls, ['notifyDesktop', 'wipe']);
  assert.deepEqual(a, b);
});

test('after a failed wipe a new attempt runs again', async () => {
  let attempts = 0;
  const { run } = setup({ wipe: async () => { attempts += 1; if (attempts === 1) throw new Error('x'); } });

  assert.equal((await run()).ok, false);
  assert.equal((await run()).ok, true);
  assert.equal(attempts, 2);
});
