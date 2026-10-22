// pwa/push-blob.js
// Der Text einer Push-Benachrichtigung reist verschlüsselt durch den Relay: AES-256-GCM mit einem
// eigenen, nicht extrahierbaren Schlüssel, den nur dieses Gerät kennt (Seite und Service Worker
// lesen ihn aus derselben IndexedDB). Bewusst nicht `k_dev` der Kopplung: der Desktop braucht
// diesen Schlüssel nie. Läuft in der Seite **und** im Service Worker, daher keine DOM-API.
export const MAX_BLOB = 1024;        // Grenze des Relays (`LIMITS.maxBlob`)
const IV_BYTES = 12;
const DB_NAME = 'zeiterfassung-push';
const STORE = 'keys';
const KEY_ID = 'blob';

/** Ablage des Schlüssels in IndexedDB. Eigene Datenbank, damit die der Daten unverändert bleibt. */
export function idbKeyStore(indexedDB = globalThis.indexedDB) {
  const openDb = () => new Promise((resolve, reject) => {
    const request = indexedDB.open(DB_NAME, 1);
    request.onupgradeneeded = () => request.result.createObjectStore(STORE);
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
  return {
    async get() {
      const db = await openDb();
      return new Promise((resolve, reject) => {
        const request = db.transaction(STORE).objectStore(STORE).get(KEY_ID);
        request.onsuccess = () => resolve(request.result);
        request.onerror = () => reject(request.error);
      });
    },
    async put(key) {
      const db = await openDb();
      return new Promise((resolve, reject) => {
        const tx = db.transaction(STORE, 'readwrite');
        tx.objectStore(STORE).put(key, KEY_ID);
        tx.oncomplete = () => resolve();
        tx.onerror = () => reject(tx.error);
      });
    },
  };
}

/** Dieselbe Schnittstelle im Speicher (Tests). */
export function memoryKeyStore() {
  let key;
  return { get: async () => key, put: async (value) => { key = value; } };
}

async function keyFor(keys, create) {
  const existing = await keys.get();
  if (existing || !create) return existing;
  const key = await crypto.subtle.generateKey({ name: 'AES-GCM', length: 256 }, false, ['encrypt', 'decrypt']);
  await keys.put(key);
  return key;
}

const toBase64 = (bytes) => btoa(String.fromCharCode(...bytes));

/** Objekt → Blob (Base64 von `iv ‖ Chiffretext`). Wirft, wenn er die Grenze des Relays überschritte. */
export async function seal(keys, plain) {
  const iv = crypto.getRandomValues(new Uint8Array(IV_BYTES));
  const text = new TextEncoder().encode(JSON.stringify(plain));
  const cipher = new Uint8Array(await crypto.subtle.encrypt({ name: 'AES-GCM', iv }, await keyFor(keys, true), text));
  const all = new Uint8Array(IV_BYTES + cipher.length);
  all.set(iv);
  all.set(cipher, IV_BYTES);
  const blob = toBase64(all);
  if (blob.length > MAX_BLOB) throw new Error('Der Text der Benachrichtigung ist zu groß.');
  return blob;
}

/** Blob → Objekt; wirft bei fremdem, beschädigtem oder fehlendem Schlüssel. */
export async function open(keys, blob) {
  const key = await keyFor(keys, false);
  if (!key) throw new Error('Kein Schlüssel für Benachrichtigungen.');
  const raw = Uint8Array.from(atob(blob), (c) => c.charCodeAt(0));
  if (raw.length <= IV_BYTES) throw new Error('Blob zu kurz.');
  const plain = await crypto.subtle.decrypt({ name: 'AES-GCM', iv: raw.slice(0, IV_BYTES) }, key, raw.slice(IV_BYTES));
  return JSON.parse(new TextDecoder().decode(plain));
}
