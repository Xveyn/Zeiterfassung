// pwa/memory-adapter.js
// Speicher-Adapter für Tests (und als Referenz der Adapter-Schnittstelle, die auch
// `db.js` erfüllt): `getAll(store)` und `batch(ops)`, wobei `batch` alle Operationen
// gemeinsam anwendet (bei IndexedDB eine Transaktion).

export function createMemoryAdapter() {
  const stores = { entries: new Map(), meta: new Map() };
  return {
    async getAll(name) {
      return [...stores[name]].map(([key, value]) => ({ key, value: structuredClone(value) }));
    },
    async batch(ops) {
      for (const { store, op, key, value } of ops) {
        if (op === 'put') stores[store].set(key, structuredClone(value));
        else if (op === 'delete') stores[store].delete(key);
        else throw new Error(`unbekannte Operation: ${op}`);
      }
    },
  };
}
