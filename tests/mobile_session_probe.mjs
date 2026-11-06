// Hilfsskript für tests/test_mobile_reservation_pause_e2e.py: ein Handy der echten PWA-Logik
// (Store + parseSyncResponse + snapshotReservations) über mehrere Abgleiche.
// Zeilenprotokoll: je Zeile auf stdin ein JSON-Befehl {cmd, ...}, je Antwort eine Zeile auf stdout.
//   clock {now}                      Uhr des Handys (UTC-Text) setzen
//   save {date, slots}               Reservierung speichern (wirft bei ungültigen Slots)
//   request {}                       -> {reservations, last_pull_at}: was der nächste Abgleich sendet
//   apply {response}                 die Antwort des Desktops zum letzten `request` anwenden
//   state {}                         -> {reservations: {date: {slots, dirty}}, dirty_count, flag, ...}
import { createInterface } from 'node:readline';
import { Store } from '../pwa/store.js';
import { createMemoryAdapter } from '../pwa/memory-adapter.js';
import { parseSyncResponse } from '../pwa/sync.js';

let clock = new Date('2026-10-08T12:00:00Z');
const store = new Store(createMemoryAdapter(), () => clock);
await store.load();
await store.setMeta({ device_id: 'phone-0001', token: 'T0' });
let snapshot = { entries: {}, versions: {}, reservations: {}, reservationVersions: {} };

function state() {
  const reservations = {};
  for (const date of store.reservationDates()) {
    const r = store.getReservation(date);
    reservations[date] = { slots: r.slots, modified_at: r.modified_at, deleted: r.deleted, dirty: r.dirty };
  }
  const meta = store.getMeta();
  return { reservations, dirty_count: store.pendingCount(), flag: meta.reservation_pause,
    enabled: meta.reservations_enabled, last_pull_at: meta.last_pull_at };
}

const handlers = {
  async clock({ now }) { clock = new Date(now); return {}; },
  async save({ date, slots }) { await store.saveReservation(date, slots); return state(); },
  async request() {
    snapshot = { entries: {}, versions: {}, ...store.snapshotReservations() };
    return { reservations: snapshot.reservations, last_pull_at: store.getMeta().last_pull_at || '' };
  },
  async apply({ response }) {
    const today = clock.toISOString().slice(0, 10);
    const parsed = parseSyncResponse({ ...response, token: 'T1'.padEnd(43, 'x'), expires_at: '2026-11-07T12:00:00Z' });
    await store.applyResponse(parsed, snapshot, today);
    return state();
  },
  async state() { return state(); },
};

for await (const line of createInterface({ input: process.stdin })) {
  if (!line.trim()) continue;
  const { cmd, ...args } = JSON.parse(line);
  let out;
  try { out = { ok: await handlers[cmd](args) }; } catch (error) { out = { error: String(error.message || error) }; }
  console.log(JSON.stringify(out));
}
