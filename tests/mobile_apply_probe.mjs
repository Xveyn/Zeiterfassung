// Hilfsskript für tests/test_mobile_window_e2e.py: wendet echte Desktop-Antworten mit der
// echten PWA-Logik an (parseSyncResponse + Store.applyResponse) und nennt die Tage, die bleiben.
// stdin: {today, dirty_old, responses: [...]}  stdout: {days: [...]}
import { readFileSync } from 'node:fs';
import { Store } from '../pwa/store.js';
import { createMemoryAdapter } from '../pwa/memory-adapter.js';
import { parseSyncResponse } from '../pwa/sync.js';

const input = JSON.parse(readFileSync(0, 'utf8'));
const store = new Store(createMemoryAdapter(), () => new Date(`${input.today}T12:00:00Z`));
await store.load();
await store.setMeta({ device_id: 'phone-0001', token: 'T0' });
for (const date of input.dirty_old) {
  await store.saveDay(date, [{ start: '08:00', end: '09:00', pause: 0, kategorie: '' }]);
}
for (const raw of input.responses) {
  const snapshot = { entries: {}, versions: {} };         // nichts gesendet: nur die Antwort anwenden
  await store.applyResponse(parseSyncResponse({ ...raw, token: 'T1'.padEnd(43, 'x'), expires_at: '2026-11-07T12:00:00Z' }), snapshot, input.today);
}
console.log(JSON.stringify({ days: store.days(), window_days: store.getMeta().window_days }));
