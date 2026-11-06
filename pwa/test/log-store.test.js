import { test } from 'node:test';
import assert from 'node:assert/strict';
import { memoryLogStore, idbLogStore } from '../log-store.js';

// Kleine IndexedDB-Attrappe: Versions-Öffnen mit upgradeneeded, Object Stores mit autoIncrement-keyPath
// und äußeren Schlüsseln, Transaktionen mit oncomplete, Anfragen mit onsuccess/onerror.
function fakeFactory({ failOpen = false } = {}) {
  const dbs = new Map();
  const calls = [];
  return {
    calls,
    dbsOpened: [],
    failRequests: false,
    open(name, version) {
      const self = this;
      calls.push([name, version]);
      const request = {};
      setTimeout(() => {
        if (failOpen) {
          request.error = new Error('open failed');
          request.onerror?.();
          return;
        }
        let data = dbs.get(name);
        const fresh = !data;
        if (fresh) { data = { stores: new Map() }; dbs.set(name, data); }
        const factory = self;
        const db = {
          onversionchange: null,
          onclose: null,
          close() { this.closed = true; },
          createObjectStore(storeName, opts = {}) {
            data.stores.set(storeName, { keyPath: opts.keyPath, auto: !!opts.autoIncrement, rows: new Map(), next: 1 });
          },
          transaction(names, mode = 'readonly') {
            const list = [].concat(names);
            const tx = { mode, pending: 0, finished: false };
            const settle = () => {
              if (tx.pending === 0 && !tx.finished) {
                tx.finished = true;
                tx.oncomplete?.();
              }
            };
            setTimeout(settle, 0);
            tx.objectStore = (storeName) => {
              assert.ok(list.includes(storeName));
              const s = data.stores.get(storeName);
              const req = (fn) => {
                const r = {};
                tx.pending++;
                setTimeout(() => {
                  if (factory.failRequests) {
                    // Wie IndexedDB: der Fehler hängt an der Anfrage (event.target), `tx.error` bleibt leer.
                    r.error = new Error('request failed');
                    tx.finished = true;
                    tx.onerror?.({ target: r });
                    tx.onabort?.({ target: r });
                    return;
                  }
                  r.result = fn();
                  r.onsuccess?.();
                  tx.pending--;
                  setTimeout(settle, 0);
                }, 0);
                return r;
              };
              const write = (value, key) => {
                if (s.keyPath) {
                  const v = structuredClone(value);
                  if (v[s.keyPath] === undefined) {
                    assert.ok(s.auto);
                    v[s.keyPath] = s.next++;
                  }
                  s.rows.set(v[s.keyPath], v);
                  return v[s.keyPath];
                }
                s.rows.set(key, structuredClone(value));
                return key;
              };
              return {
                add: (v, k) => req(() => write(v, k)),
                put: (v, k) => req(() => write(v, k)),
                get: (k) => req(() => (s.rows.has(k) ? structuredClone(s.rows.get(k)) : undefined)),
                getAll: () => req(() => [...s.rows.keys()].sort((a, b) => a - b).map((k) => structuredClone(s.rows.get(k)))),
                delete: (k) => req(() => { s.rows.delete(k); }),
                clear: () => req(() => { s.rows.clear(); }),
              };
            };
            return tx;
          },
        };
        request.result = db;
        self.dbsOpened.push(db);
        if (fresh) request.onupgradeneeded?.();
        request.onsuccess?.();
      }, 0);
      return request;
    },
  };
}

const kinds = {
  memory: () => memoryLogStore(),
  indexedDB: () => idbLogStore(fakeFactory()),
};

for (const [label, make] of Object.entries(kinds)) {
  test(`${label}: add/all liefert aufsteigend nach id mit den Feldern`, async () => {
    const store = make();
    await store.add({ at: 1, kind: 'a', fields: { x: 1 } });
    await store.add({ at: 2, kind: 'b', fields: { y: 'z' } });
    await store.add({ at: 3, kind: 'c', fields: {} });
    const all = await store.all();
    assert.equal(all.length, 3);
    assert.deepEqual(all.map((e) => e.kind), ['a', 'b', 'c']);
    assert.deepEqual(all.map((e) => e.at), [1, 2, 3]);
    assert.deepEqual(all[1].fields, { y: 'z' });
    assert.ok(all[0].id < all[1].id && all[1].id < all[2].id);
    assert.equal(typeof all[0].id, 'number');
  });

  test(`${label}: remove entfernt genau die genannten ids`, async () => {
    const store = make();
    for (const k of ['a', 'b', 'c']) await store.add({ at: 0, kind: k, fields: {} });
    const [first] = await store.all();
    await store.remove([first.id]);
    assert.deepEqual((await store.all()).map((e) => e.kind), ['b', 'c']);
    await store.remove([]);
    assert.equal((await store.all()).length, 2);
  });

  test(`${label}: clear leert die Einträge, nicht die Konfiguration`, async () => {
    const store = make();
    await store.add({ at: 0, kind: 'a', fields: {} });
    await store.setConfig('k', 1);
    await store.clear();
    assert.deepEqual(await store.all(), []);
    assert.equal(await store.getConfig('k'), 1);
  });

  test(`${label}: Konfiguration Rundreise, fehlender Schlüssel ist undefined`, async () => {
    const store = make();
    assert.equal(await store.getConfig('log_retention_days'), undefined);
    await store.setConfig('log_retention_days', 30);
    assert.equal(await store.getConfig('log_retention_days'), 30);
    await store.setConfig('log_retention_days', 7);
    assert.equal(await store.getConfig('log_retention_days'), 7);
  });

  test(`${label}: ids wachsen weiter, auch nach remove`, async () => {
    const store = make();
    await store.add({ at: 0, kind: 'a', fields: {} });
    const [a] = await store.all();
    await store.remove([a.id]);
    await store.add({ at: 0, kind: 'b', fields: {} });
    const [b] = await store.all();
    assert.ok(b.id > a.id);
  });
}

test('indexedDB: öffnet erst beim ersten Aufruf, mit Name und Version', async () => {
  const factory = fakeFactory();
  const store = idbLogStore(factory);
  assert.equal(factory.calls.length, 0);
  await store.all();
  assert.deepEqual(factory.calls, [['zeiterfassung-log', 1]]);
  await store.add({ at: 0, kind: 'a', fields: {} });
  assert.equal(factory.calls.length, 1);
});

test('indexedDB: ein gescheitertes Öffnen lässt den Aufruf ablehnen', async () => {
  const store = idbLogStore(fakeFactory({ failOpen: true }));
  await assert.rejects(store.add({ at: 0, kind: 'a', fields: {} }));
});

test('indexedDB: nach gescheitertem Öffnen ist ein neuer Versuch möglich', async () => {
  const factory = fakeFactory({ failOpen: true });
  const store = idbLogStore(factory);
  await assert.rejects(store.all());
  await assert.rejects(store.all());
  assert.equal(factory.calls.length, 2);
});

test('indexedDB: eine vom Browser geschlossene Verbindung wird beim nächsten Aufruf neu geöffnet', async () => {
  const factory = fakeFactory();
  const store = idbLogStore(factory);
  await store.add({ at: 0, kind: 'a', fields: {} });
  factory.dbsOpened[0].onclose();
  assert.equal((await store.all()).length, 1);
  assert.equal(factory.calls.length, 2);
});

test('indexedDB: der Fehler einer Anfrage kommt aus event.target.error', async () => {
  const factory = fakeFactory();
  const store = idbLogStore(factory);
  await store.all();
  factory.failRequests = true;
  await assert.rejects(store.add({ at: 0, kind: 'a', fields: {} }), (e) => e instanceof Error && e.message === 'request failed');
});
