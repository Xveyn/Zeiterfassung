// relay/test/fake-storage.js
// In-Memory-Ersatz für `ctx.storage` eines Durable Objects (nur die Teile, die `device.js` nutzt).
// Werte werden wie in der Plattform kopiert, damit ein Test nie einen geteilten Verweis behält.
export function fakeStorage() {
  const map = new Map();
  let alarm = null;
  return {
    async get(key) { return map.has(key) ? structuredClone(map.get(key)) : undefined; },
    async put(key, value) { map.set(key, structuredClone(value)); },
    async delete(key) { return map.delete(key); },
    async deleteAll() { map.clear(); },
    async setAlarm(ms) { alarm = ms; },
    async getAlarm() { return alarm; },
    async deleteAlarm() { alarm = null; },
    keys: () => [...map.keys()],
  };
}
