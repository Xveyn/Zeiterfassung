// pwa/db.js
// IndexedDB-Adapter für `store.js`: zwei Object Stores (`entries`: Schlüssel = Datum,
// `meta`: ein Datensatz unter dem Schlüssel `meta`). `batch(ops)` wendet alle Operationen
// in EINER Transaktion an: ein Tag und das neue Token werden nie getrennt geschrieben.
//
// Dünne Schicht ohne eigene Logik — die steckt in `store.js` und ist in Node getestet.
// Hier prüft nur ein Test mit einer Attrappe Form und Fehlerpfade; das echte IndexedDB
// wird von Hand im Browser geprüft.

const VERSION = 1;
const STORES = ['entries', 'meta'];

function requestResult(request) {
  return new Promise((resolve, reject) => {
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}

function transactionDone(transaction) {
  return new Promise((resolve, reject) => {
    transaction.oncomplete = () => resolve();
    transaction.onerror = () => reject(transaction.error);
    transaction.onabort = () => reject(transaction.error ?? new Error('Transaktion abgebrochen'));
  });
}

export function openDatabase(factory = globalThis.indexedDB, name = 'zeiterfassung') {
  return new Promise((resolve, reject) => {
    if (!factory) {
      reject(new Error('IndexedDB ist nicht verfügbar'));
      return;
    }
    const request = factory.open(name, VERSION);
    request.onupgradeneeded = () => {
      for (const store of STORES) {
        if (!request.result.objectStoreNames.contains(store)) request.result.createObjectStore(store);
      }
    };
    request.onerror = () => reject(request.error);
    request.onblocked = () => reject(new Error('IndexedDB ist von einem anderen Tab blockiert'));
    request.onsuccess = () => {
      const database = request.result;
      resolve({
        async getAll(storeName) {
          const transaction = database.transaction(storeName, 'readonly');
          const store = transaction.objectStore(storeName);
          const [keys, values] = await Promise.all(
            [requestResult(store.getAllKeys()), requestResult(store.getAll())]);
          return keys.map((key, index) => ({ key, value: values[index] }));
        },
        async batch(ops) {
          if (ops.length === 0) return;
          // Vor der Transaktion prüfen: eine abgebrochene Transaktion mit unbehandelter
          // Ablehnung wäre schlimmer als ein früher Fehler.
          for (const { op } of ops) {
            if (op !== 'put' && op !== 'delete') throw new Error(`unbekannte Operation: ${op}`);
          }
          const transaction = database.transaction(STORES, 'readwrite');
          const done = transactionDone(transaction);
          for (const { store, op, key, value } of ops) {
            const target = transaction.objectStore(store);
            if (op === 'put') target.put(value, key);
            else target.delete(key);
          }
          await done;
        },
      });
    };
  });
}

/** Bittet den Browser, die Daten nicht bei Platzmangel zu räumen. `false`, wenn er ablehnt
 *  oder die Funktion fehlt — die Oberfläche zeigt das an (nicht übertragene Einträge sind
 *  sonst ungeschützt). */
export async function requestPersistentStorage(storage = globalThis.navigator?.storage) {
  if (!storage || typeof storage.persist !== 'function') return false;
  try {
    return Boolean(await storage.persist());
  } catch {
    return false;                              // ablehnen und Fehler sehen für die UI gleich aus
  }
}
