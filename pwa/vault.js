// pwa/vault.js
// Verschlüsselung der IndexedDB-Inhalte auf dem Handy (#490, Stufe 1): eine Schicht um den Adapter des
// Stores (`getAll`/`batch`), `store.js` bleibt unverändert. AES-256-GCM mit einem **nicht extrahierbaren**
// Gerätschlüssel in einer eigenen Datenbank (wie `push-blob.js`); je Datensatz eine frische IV, und die
// Zusatzdaten (AAD) binden Store und Schlüssel: ein Datensatz lässt sich nicht an einen anderen Tag oder in
// einen anderen Store verschieben. Die Tagesdaten als Schlüssel bleiben lesbar.
//
// Das ist Schutz vor einer Kopie des Speichers, nicht vor Skript im selben Ursprung: der Schlüssel lässt sich
// dort benutzen, nur nicht auslesen. Kein DOM, damit es in Node getestet werden kann.
//
// **Zweistufig ausgerollt** (`pwa/CLAUDE.md`, „Lokale Verschlüsselung“): Lesen geht immer, Schreiben nur mit
// `ENCRYPT_AT_REST`. Ein älterer Stand liest einen verschlüsselten Datensatz als „nicht gekoppelt“ und
// überschriebe ihn beim nächsten Speichern mit Klartext-Standardwerten.
import { b64d, b64e } from './crypto.js';
import { t } from './i18n.js';

export const ENCRYPT_AT_REST = false;

const FORMAT = 1;
const KID = 'dev1';                       // Kennung des Gerätschlüssels; spätere Schlüssel bekommen eine andere
const IV_BYTES = 12;
const STORES = ['entries', 'meta', 'reservations'];
const DB_NAME = 'zeiterfassung-vault';
const STORE = 'keys';
const KEY_ID = 'data';
const encoder = new TextEncoder();
const decoder = new TextDecoder();

/** `code`: `key_unavailable` (verschlüsselte Daten, aber kein passender Schlüssel), `unreadable` (beschädigt,
 *  verändert oder an eine andere Stelle verschoben), `unsupported` (Format einer neueren Version). */
export class VaultError extends Error {
  constructor(code, message) {
    super(message);
    this.name = 'VaultError';
    this.code = code;
  }
}

const isObject = (value) => typeof value === 'object' && value !== null && !Array.isArray(value);

/** Jeder Wert mit `vault`-Feld gilt als versiegelt, auch in einem unbekannten Format: er darf nie als Klartext
 *  durchgehen (ein Klartext-Datensatz trägt kein solches Feld). */
export const isSealed = (value) => isObject(value) && Object.hasOwn(value, 'vault');

const aad = (store, key) => encoder.encode(`zeit-vault/${FORMAT}/${store}/${key}`);

async function sealRecord(record, store, key, value) {
  const iv = crypto.getRandomValues(new Uint8Array(IV_BYTES));
  const plain = encoder.encode(JSON.stringify(value));
  const cipher = await crypto.subtle.encrypt({ name: 'AES-GCM', iv, additionalData: aad(store, key) }, record.key, plain);
  return { vault: FORMAT, kid: record.kid, iv: b64e(iv), ct: b64e(new Uint8Array(cipher)) };
}

function openRecord(record, store, key, sealed) {
  if (sealed.vault !== FORMAT) throw new VaultError('unsupported', t('vault.fehler.neueres_format'));
  if (!record || record.kid !== sealed.kid) throw new VaultError('key_unavailable', t('vault.fehler.schluessel_fehlt'));
  return decryptRecord(record, store, key, sealed);
}

async function decryptRecord(record, store, key, sealed) {
  try {
    const plain = await crypto.subtle.decrypt(
      { name: 'AES-GCM', iv: b64d(sealed.iv), additionalData: aad(store, key) }, record.key, b64d(sealed.ct));
    return JSON.parse(decoder.decode(plain));
  } catch {
    // Bewusst alles: falsche Kodierung, Prüfsumme, JSON — für den Aufrufer ist es dasselbe, ein Datensatz, der sich
    // nicht öffnen lässt. Ein Text (Inhalt, Schlüssel) steht nie in der Meldung.
    throw new VaultError('unreadable', t('vault.fehler.beschaedigt'));
  }
}

/** Ablage des Schlüssels in IndexedDB (eigene Datenbank, `{kid, key}` unter einem festen Schlüssel).
 *  `putIfAbsent` ist atomar (eine Transaktion): zwei Tabs, die gleichzeitig den ersten Schlüssel anlegen, behalten
 *  denselben. */
export function idbVaultKeyStore(indexedDB = globalThis.indexedDB) {
  const connect = () => new Promise((resolve, reject) => {
    const request = indexedDB.open(DB_NAME, 1);
    request.onupgradeneeded = () => request.result.createObjectStore(STORE);
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
  const dropDb = () => new Promise((resolve, reject) => {
    const request = indexedDB.deleteDatabase(DB_NAME);
    request.onsuccess = () => resolve();
    request.onerror = () => reject(request.error);
  });
  const openDb = async () => {
    const db = await connect();
    if (db.objectStoreNames.contains(STORE)) return db;
    // Eine Datenbank ohne Object Store entsteht, wenn jemand sie ohne Version öffnet (`indexedDB.open(name)`).
    // Darin kann kein Schlüssel liegen, Löschen und Neuanlegen verliert also nichts; sonst scheiterte jeder Zugriff für immer.
    db.close();
    await dropDb();
    return connect();
  };
  const run = async (mode, work) => {
    const db = await openDb();
    try {
      return await new Promise((resolve, reject) => {
        const transaction = db.transaction(STORE, mode);
        let result;
        work(transaction.objectStore(STORE), (value) => { result = value; });
        transaction.oncomplete = () => resolve(result);
        transaction.onerror = () => reject(transaction.error);
        transaction.onabort = () => reject(transaction.error ?? new Error(t('vault.fehler.transaktion_abgebrochen')));
      });
    } finally {
      db.close();
    }
  };
  return {
    get: () => run('readonly', (store, out) => {
      const request = store.get(KEY_ID);
      request.onsuccess = () => out(request.result);
    }),
    putIfAbsent: (record) => run('readwrite', (store, out) => {
      const request = store.get(KEY_ID);
      request.onsuccess = () => {
        if (request.result === undefined) {
          store.put(record, KEY_ID);
          out(record);
        } else {
          out(request.result);
        }
      };
    }),
    clear: () => run('readwrite', (store) => { store.delete(KEY_ID); }),
  };
}

/** Dieselbe Schnittstelle im Speicher (Tests). */
export function memoryVaultKeyStore() {
  let record;
  return {
    get: async () => record,
    putIfAbsent: async (value) => { record ??= value; return record; },
    clear: async () => { record = undefined; },
  };
}

/** Der Adapter des Stores mit Verschlüsselung. Ohne `encrypt` wird Klartext geschrieben und kein Schlüssel
 *  angelegt, vorhandene verschlüsselte Datensätze werden trotzdem gelesen. Ein Datensatz, der sich nicht öffnen
 *  lässt, wirft `VaultError` — er gilt nie als leer, sonst überschriebe der nächste Speichervorgang ihn. */
export function createVaultAdapter(inner, { keys, encrypt = ENCRYPT_AT_REST } = {}) {
  async function ensureKey() {
    const existing = await keys.get();
    if (existing) return existing;
    const key = await crypto.subtle.generateKey({ name: 'AES-GCM', length: 256 }, false, ['encrypt', 'decrypt']);
    return keys.putIfAbsent({ kid: KID, key });       // hat ein anderer Tab gewonnen, gilt dessen Schlüssel
  }

  async function sealOps(ops) {
    if (!encrypt || !ops.some((op) => op.op === 'put')) return ops;
    const record = await ensureKey();
    // Erst alles versiegeln, dann schreiben: ein Fehler mittendrin schreibt nichts.
    return Promise.all(ops.map(async (op) => (
      op.op === 'put' ? { ...op, value: await sealRecord(record, op.store, op.key, op.value) } : op)));
  }

  const batch = async (ops) => { await inner.batch(await sealOps(ops)); };

  return {
    encrypting: encrypt,
    async getAll(store) {
      const rows = await inner.getAll(store);
      // Der Schlüssel einmal je Aufruf, nicht je Datensatz: `Store.load` läuft bei jedem Abgleich.
      const record = rows.some(({ value }) => isSealed(value) && value.vault === FORMAT) ? await keys.get() : undefined;
      return Promise.all(rows.map(async ({ key, value }) => ({
        key, value: isSealed(value) ? await openRecord(record, store, key, value) : value })));
    },
    batch,
    /** Schreibt alle Klartext-Datensätze versiegelt zurück; liefert ihre Zahl (0: nichts zu tun).
     *  Lücke, die vor dem Einschalten von `ENCRYPT_AT_REST` zu schließen ist: schreibt ein zweiter Tab zwischen
     *  `getAll` und `batch` denselben Schlüssel, überschreibt dieser Aufruf ihn mit dem alten Stand. */
    async migrate() {
      if (!encrypt) return 0;
      const ops = [];
      for (const store of STORES) {
        for (const { key, value } of await inner.getAll(store)) {
          if (!isSealed(value)) ops.push({ store, op: 'put', key, value });
        }
      }
      if (ops.length > 0) await batch(ops);
      return ops.length;
    },
    /** Löscht alle Datensätze und den Schlüssel, auch wenn sich nichts mehr öffnen lässt (Neu koppeln). */
    async wipe() {
      const ops = [];
      for (const store of STORES) {
        for (const { key } of await inner.getAll(store)) ops.push({ store, op: 'delete', key });
      }
      await inner.batch(ops);
      await keys.clear();
    },
  };
}
