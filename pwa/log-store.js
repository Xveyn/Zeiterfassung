// pwa/log-store.js
// Ablage des Debug-Protokolls: Einträge `{id, at, kind, fields}` und eine kleine Konfiguration.
// Eigene Datenbank, damit `zeiterfassung` (Daten) und `zeiterfassung-push` unverändert bleiben.
// Läuft in der Seite **und** im Service Worker, daher keine DOM-API.
const DB_NAME = 'zeiterfassung-log';
const DB_VERSION = 1;
const ENTRIES = 'entries';
const CONFIG = 'config';

/** Ablage in IndexedDB. Geöffnet wird erst beim ersten Aufruf: der Service Worker zahlt beim Kaltstart nichts. */
export function idbLogStore(indexedDB = globalThis.indexedDB) {
  let opening = null;
  const openDb = () => {
    if (opening) return opening;
    opening = new Promise((resolve, reject) => {
      const request = indexedDB.open(DB_NAME, DB_VERSION);
      request.onupgradeneeded = () => {
        const db = request.result;
        db.createObjectStore(ENTRIES, { keyPath: 'id', autoIncrement: true });
        db.createObjectStore(CONFIG);
      };
      request.onsuccess = () => {
        const db = request.result;
        // Ein Versionssprung anderswo darf nicht an unserer offenen Verbindung hängen bleiben.
        db.onversionchange = () => { db.close(); opening = null; };
        resolve(db);
      };
      request.onerror = () => reject(request.error);
    });
    // Ein Fehlschlag wird nicht gemerkt: der nächste Aufruf versucht es erneut (etwa nach freigegebenem Speicher).
    opening.catch(() => { opening = null; });
    return opening;
  };

  // Eine Transaktion; geliefert wird das Ergebnis der Anfrage, aber erst nach `oncomplete` (dann ist es festgeschrieben).
  const run = async (names, mode, work) => {
    const db = await openDb();
    return new Promise((resolve, reject) => {
      const tx = db.transaction(names, mode);
      let result;
      const request = work(tx);
      if (request) request.onsuccess = () => { result = request.result; };
      tx.oncomplete = () => resolve(result);
      tx.onerror = () => reject(tx.error);
      tx.onabort = () => reject(tx.error);
    });
  };

  return {
    // Ohne `id`: die Nummer vergibt der Store (aufsteigend, auch nach `remove` nie wieder verwendet).
    add: ({ at, kind, fields }) => run(ENTRIES, 'readwrite', (tx) => tx.objectStore(ENTRIES).add({ at, kind, fields })).then(() => {}),
    all: () => run(ENTRIES, 'readonly', (tx) => tx.objectStore(ENTRIES).getAll()),
    remove: (ids) => run(ENTRIES, 'readwrite', (tx) => {
      const store = tx.objectStore(ENTRIES);
      for (const id of ids) store.delete(id);
      return null;
    }).then(() => {}),
    clear: () => run(ENTRIES, 'readwrite', (tx) => tx.objectStore(ENTRIES).clear()).then(() => {}),
    getConfig: (key) => run(CONFIG, 'readonly', (tx) => tx.objectStore(CONFIG).get(key)),
    setConfig: (key, value) => run(CONFIG, 'readwrite', (tx) => tx.objectStore(CONFIG).put(value, key)).then(() => {}),
  };
}

/** Dieselbe Schnittstelle im Speicher (Tests). */
export function memoryLogStore() {
  let rows = [];
  let next = 1;
  const config = new Map();
  return {
    async add({ at, kind, fields }) { rows.push(structuredClone({ id: next++, at, kind, fields })); },
    async all() { return structuredClone(rows); },
    async remove(ids) { const drop = new Set(ids); rows = rows.filter((r) => !drop.has(r.id)); },
    async clear() { rows = []; },
    async getConfig(key) { return config.get(key); },
    async setConfig(key, value) { config.set(key, value); },
  };
}
