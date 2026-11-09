// pwa/test/vault.test.js
import { test } from 'node:test';
import assert from 'node:assert/strict';

import { ENCRYPT_AT_REST, VaultError, createVaultAdapter, idbVaultKeyStore, isSealed, memoryVaultKeyStore } from '../vault.js';
import { Store } from '../store.js';
import { createMemoryAdapter } from '../memory-adapter.js';
import { isPaired } from '../transport.js';

const SLOT = { start: '08:00', end: '12:00', pause: 0, kategorie: 'Projekt' };
const RECORD = { entry: { slots: [SLOT], modified_at: '2026-10-08T12:00:00Z', deleted: false }, dirty_version: 1, synced_version: 0, error: null };
const META = { token: 'T0-geheimes-token', key: 'a'.repeat(43), box_secret: '', device_id: 'phone-0001' };

const raw = async (inner) => JSON.stringify({
  entries: await inner.getAll('entries'), meta: await inner.getAll('meta'), reservations: await inner.getAll('reservations') });

function make({ encrypt = true, inner = createMemoryAdapter(), keys = memoryVaultKeyStore() } = {}) {
  return { inner, keys, vault: createVaultAdapter(inner, { keys, encrypt }) };
}

test('writing stays off until the follow-up change switches it on', () => {
  assert.equal(ENCRYPT_AT_REST, false);
});

test('a sealed record round-trips and the inner adapter holds no plain text', async () => {
  const { vault, inner } = make();
  await vault.batch([
    { store: 'entries', op: 'put', key: '2026-10-08', value: RECORD },
    { store: 'meta', op: 'put', key: 'meta', value: META },
  ]);

  assert.deepEqual(await vault.getAll('entries'), [{ key: '2026-10-08', value: RECORD }]);
  assert.deepEqual(await vault.getAll('meta'), [{ key: 'meta', value: META }]);
  const stored = await raw(inner);
  assert.ok(!stored.includes('T0-geheimes-token') && !stored.includes('Projekt'));
  const [{ value }] = await inner.getAll('meta');
  assert.ok(isSealed(value));
  assert.deepEqual(Object.keys(value).sort(), ['ct', 'iv', 'kid', 'vault']);
});

test('the key is not extractable', async () => {
  const { vault, keys } = make();
  await vault.batch([{ store: 'meta', op: 'put', key: 'meta', value: META }]);
  const { key } = await keys.get();
  assert.equal(key.extractable, false);
  await assert.rejects(crypto.subtle.exportKey('raw', key));
});

test('every write uses a fresh IV', async () => {
  const { vault, inner } = make();
  const ivs = new Set();
  for (let i = 0; i < 3; i += 1) {
    await vault.batch([{ store: 'meta', op: 'put', key: 'meta', value: META }]);
    ivs.add((await inner.getAll('meta'))[0].value.iv);
  }
  assert.equal(ivs.size, 3);
});

test('plain records stay readable next to sealed ones (mixed state)', async () => {
  const { vault, inner } = make();
  await inner.batch([{ store: 'entries', op: 'put', key: '2026-10-07', value: RECORD }]);
  await vault.batch([{ store: 'entries', op: 'put', key: '2026-10-08', value: RECORD }]);

  const rows = await vault.getAll('entries');

  assert.deepEqual(rows.map((row) => row.key).sort(), ['2026-10-07', '2026-10-08']);
  assert.ok(rows.every((row) => JSON.stringify(row.value) === JSON.stringify(RECORD)));
});

test('with writing off a record is stored plain, but sealed ones are still read', async () => {
  const keys = memoryVaultKeyStore();
  const on = make({ keys });
  await on.vault.batch([{ store: 'meta', op: 'put', key: 'meta', value: META }]);
  const off = make({ encrypt: false, inner: on.inner, keys });

  assert.deepEqual((await off.vault.getAll('meta'))[0].value, META);
  await off.vault.batch([{ store: 'entries', op: 'put', key: '2026-10-08', value: RECORD }]);
  assert.ok(!isSealed((await on.inner.getAll('entries'))[0].value));
});

test('no key is created while writing is off', async () => {
  const { vault, keys } = make({ encrypt: false });
  await vault.batch([{ store: 'meta', op: 'put', key: 'meta', value: META }]);
  assert.equal(await keys.get(), undefined);
});

test('a record cannot be moved to another day or store', async () => {
  const { vault, inner } = make();
  await vault.batch([{ store: 'entries', op: 'put', key: '2026-10-08', value: RECORD }]);
  const [{ value }] = await inner.getAll('entries');

  await inner.batch([{ store: 'reservations', op: 'put', key: '2026-10-08', value }]);
  await assert.rejects(vault.getAll('reservations'), (error) => error instanceof VaultError && error.code === 'unreadable');

  await inner.batch([{ store: 'entries', op: 'put', key: '2026-10-09', value }]);
  await assert.rejects(vault.getAll('entries'), (error) => error.code === 'unreadable');
});

test('a changed ciphertext is unreadable', async () => {
  const { vault, inner } = make();
  await vault.batch([{ store: 'meta', op: 'put', key: 'meta', value: META }]);
  const [{ value }] = await inner.getAll('meta');
  const flipped = value.ct.startsWith('A') ? `B${value.ct.slice(1)}` : `A${value.ct.slice(1)}`;
  await inner.batch([{ store: 'meta', op: 'put', key: 'meta', value: { ...value, ct: flipped } }]);

  await assert.rejects(vault.getAll('meta'), (error) => error.code === 'unreadable');
});

test('sealed data without the key is reported, never read as empty', async () => {
  const { vault, inner } = make();
  await vault.batch([{ store: 'meta', op: 'put', key: 'meta', value: META }]);
  const lost = createVaultAdapter(inner, { keys: memoryVaultKeyStore(), encrypt: true });

  await assert.rejects(lost.getAll('meta'), (error) => error instanceof VaultError && error.code === 'key_unavailable');
});

test('a key with another id does not open the record', async () => {
  const { vault, inner, keys } = make();
  await vault.batch([{ store: 'meta', op: 'put', key: 'meta', value: META }]);
  const record = await keys.get();
  const other = memoryVaultKeyStore();
  await other.putIfAbsent({ ...record, kid: 'dev2' });

  await assert.rejects(createVaultAdapter(inner, { keys: other }).getAll('meta'), (error) => error.code === 'key_unavailable');
});

test('a newer format is never mistaken for a plain record', async () => {
  const { vault, inner } = make({ encrypt: false });
  await inner.batch([{ store: 'meta', op: 'put', key: 'meta', value: { vault: 2, kid: 'x', iv: 'AA', ct: 'AA' } }]);

  await assert.rejects(vault.getAll('meta'), (error) => error instanceof VaultError && error.code === 'unsupported');
});

test('a batch is sealed before anything is written', async () => {
  const { vault, inner } = make();
  await assert.rejects(vault.batch([
    { store: 'entries', op: 'put', key: '2026-10-08', value: RECORD },
    { store: 'meta', op: 'put', key: 'meta', value: { broken: 1n } },     // JSON.stringify wirft
  ]));
  assert.deepEqual(await inner.getAll('entries'), []);
  assert.deepEqual(await inner.getAll('meta'), []);
});

test('deletes pass through and the batch stays one inner batch', async () => {
  const { vault, inner } = make();
  await vault.batch([{ store: 'entries', op: 'put', key: '2026-10-08', value: RECORD }]);
  const calls = [];
  const original = inner.batch.bind(inner);
  inner.batch = async (ops) => { calls.push(ops.length); return original(ops); };

  await vault.batch([
    { store: 'entries', op: 'delete', key: '2026-10-08' },
    { store: 'entries', op: 'put', key: '2026-10-09', value: RECORD },
    { store: 'meta', op: 'put', key: 'meta', value: META },
  ]);

  assert.deepEqual(calls, [3]);
  assert.deepEqual((await vault.getAll('entries')).map((row) => row.key), ['2026-10-09']);
});

test('parallel first writes share one key', async () => {
  const { vault, inner, keys } = make();
  await Promise.all([
    vault.batch([{ store: 'meta', op: 'put', key: 'meta', value: META }]),
    vault.batch([{ store: 'entries', op: 'put', key: '2026-10-08', value: RECORD }]),
    vault.batch([{ store: 'entries', op: 'put', key: '2026-10-09', value: RECORD }]),
  ]);
  const second = createVaultAdapter(inner, { keys, encrypt: true });
  assert.equal((await second.getAll('entries')).length, 2);
  assert.deepEqual((await second.getAll('meta'))[0].value, META);
});

test('two tabs creating the first key at once end up with one key', async () => {
  const inner = createMemoryAdapter();
  const keys = memoryVaultKeyStore();
  const a = createVaultAdapter(inner, { keys, encrypt: true });
  const b = createVaultAdapter(inner, { keys, encrypt: true });
  await Promise.all([
    a.batch([{ store: 'entries', op: 'put', key: '2026-10-08', value: RECORD }]),
    b.batch([{ store: 'entries', op: 'put', key: '2026-10-09', value: RECORD }]),
  ]);
  assert.equal((await a.getAll('entries')).length, 2);
  assert.equal((await b.getAll('entries')).length, 2);
});

test('migrate seals plain records once and is then a no-op', async () => {
  const { vault, inner } = make();
  await inner.batch([
    { store: 'entries', op: 'put', key: '2026-10-07', value: RECORD },
    { store: 'meta', op: 'put', key: 'meta', value: META },
  ]);

  assert.equal(await vault.migrate(), 2);
  assert.ok(!(await raw(inner)).includes('T0-geheimes-token'));
  assert.equal(await vault.migrate(), 0);
  assert.deepEqual((await vault.getAll('meta'))[0].value, META);
});

test('migrate does nothing while writing is off', async () => {
  const { vault, inner } = make({ encrypt: false });
  await inner.batch([{ store: 'meta', op: 'put', key: 'meta', value: META }]);
  assert.equal(await vault.migrate(), 0);
  assert.ok((await raw(inner)).includes('T0-geheimes-token'));
});

test('wipe removes every record and the key, even when nothing can be opened', async () => {
  const { vault, inner, keys } = make();
  await vault.batch([
    { store: 'entries', op: 'put', key: '2026-10-08', value: RECORD },
    { store: 'meta', op: 'put', key: 'meta', value: META },
  ]);
  const [{ value }] = await inner.getAll('meta');
  await inner.batch([{ store: 'meta', op: 'put', key: 'meta', value: { ...value, kid: 'dev0' } }]);   // nichts ist mehr lesbar
  await assert.rejects(vault.getAll('meta'));
  assert.ok(await keys.get());                                  // der Schlüssel ist da und muss von `wipe` kommen

  await vault.wipe();

  assert.deepEqual(await inner.getAll('entries'), []);
  assert.deepEqual(await inner.getAll('meta'), []);
  assert.equal(await keys.get(), undefined);
  await vault.batch([{ store: 'meta', op: 'put', key: 'meta', value: META }]);   // und es geht wieder
  assert.deepEqual((await vault.getAll('meta'))[0].value, META);
});

test('the Store works unchanged on top of the vault', async () => {
  const { vault, inner, keys } = make();
  const store = new Store(vault, () => new Date('2026-10-08T12:00:00Z'));
  await store.load();
  await store.setMeta({ device_id: 'phone-0001', token: 'T0-geheimes-token' });
  await store.saveDay('2026-10-08', [SLOT]);

  const reopened = new Store(createVaultAdapter(inner, { keys, encrypt: true }), () => new Date('2026-10-08T12:00:00Z'));
  await reopened.load();

  assert.deepEqual(reopened.days(), ['2026-10-08']);
  assert.equal(reopened.getMeta().token, 'T0-geheimes-token');
  assert.ok(!(await raw(inner)).includes('T0-geheimes-token'));
});

// --- IndexedDB-Ablage des Schlüssels --------------------------------------------------------------

/** Attrappe mit genau der Schnittstelle, die `idbVaultKeyStore` braucht, samt Versionen und `deleteDatabase`. Handler
 *  werden nach dem Aufruf zugewiesen, deshalb feuern sie per Microtask. `stray()` legt eine Datenbank ohne Object Store
 *  an, wie sie `indexedDB.open(name)` ohne Version hinterlässt. */
function fakeIndexedDb() {
  const db = { exists: false, version: 0, stores: new Set(), data: new Map() };
  const log = { opened: 0, deleted: 0 };
  return {
    db, log,
    stray() { db.exists = true; db.version = 1; db.stores.clear(); },
    deleteDatabase() {
      const request = {};
      queueMicrotask(() => { db.exists = false; db.version = 0; db.stores.clear(); db.data.clear(); log.deleted += 1; request.onsuccess(); });
      return request;
    },
    open(_name, version) {
      log.opened += 1;
      const request = {};
      queueMicrotask(() => {
        const upgrade = !db.exists;
        if (upgrade) { db.exists = true; db.version = version ?? 1; }
        request.result = {
          version: db.version,
          objectStoreNames: { contains: (name) => db.stores.has(name) },
          createObjectStore: (name) => db.stores.add(name),
          transaction() {
            const error = new Error('One of the specified object stores was not found.');
            error.name = 'NotFoundError';
            if (!db.stores.has('keys')) throw error;
            const transaction = {
              objectStore: () => ({
                get: (key) => {
                  const r = {};
                  queueMicrotask(() => { r.result = db.data.get(key); r.onsuccess(); });
                  return r;
                },
                put: (value, key) => { db.data.set(key, structuredClone(value)); },
                delete: (key) => { db.data.delete(key); },
              }),
            };
            queueMicrotask(() => queueMicrotask(() => queueMicrotask(() => transaction.oncomplete())));
            return transaction;
          },
          close: () => {},
        };
        if (upgrade) request.onupgradeneeded?.();
        request.onsuccess();
      });
      return request;
    },
  };
}

const newKey = () => crypto.subtle.generateKey({ name: 'AES-GCM', length: 256 }, false, ['encrypt', 'decrypt']);

test('the IndexedDB key store keeps the first key and hands it out for a later one', async () => {
  const store = idbVaultKeyStore(fakeIndexedDb());
  const first = { kid: 'dev1', key: await newKey() };
  const second = { kid: 'dev1', key: await newKey() };
  assert.equal(await store.get(), undefined);

  await store.putIfAbsent(first);
  const returned = await store.putIfAbsent(second);

  // Identität, nicht Form: mit dem ersten Schlüssel versiegelt, mit dem zurückgegebenen geöffnet.
  const iv = new Uint8Array(12);
  const sealed = await crypto.subtle.encrypt({ name: 'AES-GCM', iv }, first.key, new TextEncoder().encode('x'));
  assert.equal(new TextDecoder().decode(await crypto.subtle.decrypt({ name: 'AES-GCM', iv }, returned.key, sealed)), 'x');
  await assert.rejects(crypto.subtle.decrypt({ name: 'AES-GCM', iv }, second.key, sealed));
  assert.ok((await store.get()).key instanceof CryptoKey);
  await store.clear();
  assert.equal(await store.get(), undefined);
});

test('a key database without its object store is rebuilt instead of failing for good', async () => {
  const idb = fakeIndexedDb();
  idb.stray();                                                  // z. B. `indexedDB.open('zeiterfassung-vault')` ohne Version
  const store = idbVaultKeyStore(idb);

  assert.equal(await store.get(), undefined);
  assert.equal(idb.log.deleted, 1);                             // ohne Object Store kann kein Schlüssel darin liegen
  const kept = await store.putIfAbsent({ kid: 'dev1', key: await newKey() });
  assert.equal(kept.kid, 'dev1');
  await store.clear();
  assert.equal(idb.log.deleted, 1);                             // eine gesunde Datenbank bleibt unangetastet
});

test('after a wipe a fresh store is unpaired and empty: the setup screen is what the next start shows (#499)', async () => {
  const { vault } = make();
  const store = new Store(vault, () => new Date('2026-10-08T12:00:00Z'));
  await store.load();
  await store.setMeta({ device_id: 'phone-0001', token: 'T0', key: 'a'.repeat(43), seq: 3, relay_secret: 'R'.repeat(43),
    transport: 'relay', box_secret: 'B'.repeat(43), lock_enabled: true, lock_credential: 'cred' });
  await store.saveDay('2026-10-07', [SLOT]);
  assert.equal(isPaired(store.getMeta()), true);

  await vault.wipe();
  const fresh = new Store(vault, () => new Date('2026-10-08T12:00:00Z'));
  await fresh.load();

  assert.equal(isPaired(fresh.getMeta()), false);
  assert.deepEqual(fresh.days(), []);
  assert.equal(fresh.pendingCount(), 0);
  const meta = fresh.getMeta();
  for (const key of ['token', 'key', 'device_id', 'relay_secret', 'box_secret', 'lock_credential']) {
    assert.equal(meta[key] === '' || meta[key] === undefined || meta[key] === null, true, key);
  }
  assert.equal(meta.lock_enabled, false);
});

test('a frozen store writes nothing after the wipe: a late setMeta, saveDay or batch cannot bring the pairing back (#499)', async () => {
  const { vault, inner } = make();
  const store = new Store(vault, () => new Date('2026-10-08T12:00:00Z'));
  await store.load();
  await store.setMeta({ device_id: 'phone-0001', token: 'T0', key: 'a'.repeat(43) });
  await vault.wipe();

  store.freeze();
  await store.setMeta({ push_signature: 'spät', push_sent_at: 1 });       // z. B. ein Zeitplan-Versand, der erst jetzt fertig wird
  await store.saveDay('2026-10-07', [SLOT]);

  assert.deepEqual(await inner.getAll('meta'), []);
  assert.deepEqual(await inner.getAll('entries'), []);
  const fresh = new Store(vault, () => new Date('2026-10-08T12:00:00Z'));
  await fresh.load();
  assert.equal(isPaired(fresh.getMeta()), false);
});
