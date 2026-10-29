// pwa/test/sw-repair.test.js
import { test } from 'node:test';
import assert from 'node:assert/strict';

import { RepairError, describeRepair, repairServiceWorker } from '../sw-repair.js';

const PREFIX = 'zeiterfassung-pwa-';

function make({ online = true, fetchOutcome = { ok: true, status: 200 }, unregisterFails = false, registerFails = false,
  cacheNames = [`${PREFIX}1/1.25.1 (abc)`, `${PREFIX}0/1.25.0 (old)`, 'andere-seite', 'workbox-x'] } = {}) {
  const calls = [];
  const registrations = [0, 1].map((index) => ({
    unregister: async () => { calls.push(`unregister:${index}`); if (unregisterFails) throw new Error('boom'); return true; },
  }));
  const names = [...cacheNames];
  const env = {
    online,
    prefix: PREFIX,
    scriptUrl: './sw.js',
    fetchFn: async (url, options) => {
      calls.push(`fetch:${url}:${options?.cache}`);
      if (fetchOutcome instanceof Error) throw fetchOutcome;
      return fetchOutcome;
    },
    serviceWorker: {
      getRegistrations: async () => registrations,
      register: async (url, options) => {
        calls.push(`register:${url}:${options?.type}`);
        if (registerFails) throw new TypeError('ServiceWorker cannot be started');
        return {};
      },
    },
    cacheStorage: {
      keys: async () => [...names],
      delete: async (name) => { calls.push(`delete:${name}`); names.splice(names.indexOf(name), 1); return true; },
    },
  };
  return { env, calls, names };
}

test('repair checks the script first, then unregisters, clears its own caches and registers again', async () => {
  const { env, calls, names } = make();
  const result = await repairServiceWorker(env);

  assert.deepEqual(calls, [
    'fetch:./sw.js:reload',
    'unregister:0', 'unregister:1',
    `delete:${PREFIX}1/1.25.1 (abc)`, `delete:${PREFIX}0/1.25.0 (old)`,
    'register:./sw.js:module',
  ]);
  assert.deepEqual(names, ['andere-seite', 'workbox-x']);          // fremde Caches bleiben
  assert.deepEqual(result, { unregistered: 2, caches: 2 });
});

test('offline nothing is touched, because the app could not start offline afterwards', async () => {
  const { env, calls } = make({ online: false });
  await assert.rejects(() => repairServiceWorker(env), (error) => error instanceof RepairError && error.kind === 'offline');
  assert.deepEqual(calls, []);
});

test('an unreachable script leaves everything as it was', async () => {
  for (const outcome of [new TypeError('Failed to fetch'), { ok: false, status: 503 }]) {
    const { env, calls } = make({ fetchOutcome: outcome });
    await assert.rejects(() => repairServiceWorker(env), (error) => error instanceof RepairError && error.kind === 'unreachable');
    assert.deepEqual(calls.filter((call) => !call.startsWith('fetch')), []);
  }
});

test('a failing unregister or register is a failed repair that carries the cause', async () => {
  const unregister = make({ unregisterFails: true });
  await assert.rejects(() => repairServiceWorker(unregister.env), (error) => error.kind === 'failed' && error.cause.message === 'boom');
  const register = make({ registerFails: true });
  await assert.rejects(() => repairServiceWorker(register.env),
    (error) => error.kind === 'failed' && /cannot be started/.test(error.cause.message));
});

test('without service worker support there is nothing to repair', async () => {
  const { env } = make();
  await assert.rejects(() => repairServiceWorker({ ...env, serviceWorker: undefined }),
    (error) => error instanceof RepairError && error.kind === 'unsupported');
});

test('every failure has a text that says what happened and what was left untouched', () => {
  assert.match(describeRepair(new RepairError('offline')), /Internetverbindung/);
  assert.match(describeRepair(new RepairError('unreachable', new TypeError('Failed to fetch'))), /nichts verändert/);
  assert.match(describeRepair(new RepairError('unreachable', new TypeError('Failed to fetch'))), /Failed to fetch/);
  assert.match(describeRepair(new RepairError('unsupported')), /unterstützt/);
  const failed = describeRepair(new RepairError('failed', new TypeError('ServiceWorker cannot be started')));
  assert.match(failed, /cannot be started/);
  assert.match(failed, /Einträge und Kopplung bleiben/);
  assert.match(describeRepair(new Error('irgendwas')), /fehlgeschlagen/);
});
