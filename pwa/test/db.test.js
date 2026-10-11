// pwa/test/db.test.js
import { test } from 'node:test';
import assert from 'node:assert/strict';

import { openDatabase, requestPersistentStorage } from '../db.js';

/** Minimale Attrappe der IndexedDB-Schnittstelle: genug für Form und Fehlerpfade. Die Handler
 *  werden von `db.js` NACH dem Aufruf zugewiesen, deshalb feuern die Attrappen per Microtask. */
function fakeFactory({ failOpen = false, throwOnSecondPut = false, failRequest = false, blocked = false } = {}) {
  const data = { entries: new Map(), meta: new Map() };
  const created = [];
  const log = { aborted: false, closed: 0 };
  let puts = 0;
  const factory = {
    open() {
      const request = {};
      queueMicrotask(() => {
        if (failOpen) {
          request.error = new Error('kaputt');
          request.onerror();
          return;
        }
        request.result = {
          objectStoreNames: { contains: (name) => created.includes(name) },
          createObjectStore: (name) => created.push(name),
          close: () => { log.closed += 1; },
          transaction(_names, mode) {
            const transaction = {
              objectStore: (name) => ({
                put: (value, key) => {
                  puts += 1;
                  if (throwOnSecondPut && puts === 2) throw new Error('DataCloneError');
                  data[name].set(key, value);
                },
                delete: (key) => data[name].delete(key),
                getAllKeys: () => {
                  const r = {};
                  queueMicrotask(() => { r.result = [...data[name].keys()]; r.onsuccess(); });
                  return r;
                },
                getAll: () => {
                  const r = {};
                  queueMicrotask(() => { r.result = [...data[name].values()]; r.onsuccess(); });
                  return r;
                },
              }),
            };
            transaction.abort = () => { log.aborted = true; queueMicrotask(() => transaction.onabort?.()); };
            if (mode === 'readwrite' && failRequest) {
              // Wie der Browser: der Fehler steht am Auslöser, `transaction.error` ist noch leer.
              queueMicrotask(() => transaction.onerror({ target: { error: new Error('QuotaExceededError') } }));
            } else if (mode === 'readwrite') {
              queueMicrotask(() => queueMicrotask(() => { if (!log.aborted) transaction.oncomplete(); }));
            }
            return transaction;
          },
        };
        log.database = request.result;
        request.onupgradeneeded();
        if (blocked) {
          request.onblocked();
          queueMicrotask(() => request.onsuccess());
          return;
        }
        request.onsuccess();
      });
      return request;
    },
  };
  return { factory, data, created, log };
}

test('opening creates both object stores', async () => {
  const { factory, created } = fakeFactory();
  await openDatabase(factory);
  assert.deepEqual(created.sort(), ['entries', 'meta']);
});

test('a batch writes puts and deletes and getAll reads them back', async () => {
  const { factory } = fakeFactory();
  const adapter = await openDatabase(factory);
  await adapter.batch([
    { store: 'entries', op: 'put', key: '2026-10-07', value: { a: 1 } },
    { store: 'meta', op: 'put', key: 'meta', value: { token: 'T' } },
  ]);
  assert.deepEqual(await adapter.getAll('entries'), [{ key: '2026-10-07', value: { a: 1 } }]);
  await adapter.batch([{ store: 'entries', op: 'delete', key: '2026-10-07' }]);
  assert.deepEqual(await adapter.getAll('entries'), []);
});

test('an empty batch does nothing', async () => {
  const adapter = await openDatabase(fakeFactory().factory);
  await adapter.batch([]);
});

test('opening fails clearly without IndexedDB or on an error', async () => {
  await assert.rejects(openDatabase(null), /nicht verfügbar/);
  await assert.rejects(openDatabase(fakeFactory({ failOpen: true }).factory), /kaputt/);
});

test('an unknown operation is refused', async () => {
  const adapter = await openDatabase(fakeFactory().factory);
  await assert.rejects(adapter.batch([{ store: 'entries', op: 'merge', key: 'x', value: 1 }]), /unbekannte Operation/);
});

test('persistent storage: granted, refused, missing, failing', async () => {
  assert.equal(await requestPersistentStorage({ persist: async () => true }), true);
  assert.equal(await requestPersistentStorage({ persist: async () => false }), false);
  assert.equal(await requestPersistentStorage(undefined), false);
  assert.equal(await requestPersistentStorage({}), false);
  assert.equal(await requestPersistentStorage({ persist: async () => { throw new Error('x'); } }), false);
});

test('a request error rejects with the real error, not null', async () => {
  const { factory } = fakeFactory({ failRequest: true });
  const db = await openDatabase(factory);

  await assert.rejects(() => db.batch([{ store: 'entries', op: 'put', key: 'a', value: 1 }]),
    (error) => error instanceof Error && error.message === 'QuotaExceededError');
});

test('a throw in the middle of a batch aborts the transaction', async () => {
  const { factory, log } = fakeFactory({ throwOnSecondPut: true });
  const db = await openDatabase(factory);

  await assert.rejects(() => db.batch([
    { store: 'entries', op: 'put', key: 'a', value: 1 },
    { store: 'entries', op: 'put', key: 'b', value: 2 }]), /DataCloneError/);

  assert.equal(log.aborted, true);
});

test('a connection that arrives after a blocked open is closed, not leaked', async () => {
  const { factory, log } = fakeFactory({ blocked: true });

  await assert.rejects(() => openDatabase(factory), /blockiert/);
  await new Promise((resolve) => setTimeout(resolve, 5));

  assert.equal(log.closed, 1);
});

test('the connection lets go when another tab upgrades the schema', async () => {
  const { factory, log } = fakeFactory();
  await openDatabase(factory);

  log.database.onversionchange();

  assert.equal(log.closed, 1);
});
