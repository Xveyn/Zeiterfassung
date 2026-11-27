// Hilfsskript für tests/test_mobile_sick_e2e.py: ein Handy der echten PWA-Logik mit Krankheitstagen über mehrere
// Abgleiche (Store, parseSyncResponse, sickDialogModel, blockOf, editLock).
// Zeilenprotokoll wie mobile_session_probe.mjs: je Zeile auf stdin ein JSON-Befehl {cmd, ...}, je Antwort eine Zeile.
//   clock {now}                          Uhr des Handys (UTC-Text) setzen; das Datum daraus ist „heute“ des Handys
//   report {from, to, deleteReservations}
//                                        „Krank melden“ in der Reihenfolge von App.reportSick: das Modell vor
//                                        `markSick`, danach die angebotenen Reservierungen löschen -> {offered, state}
//   remove {date}                        „Krankheit entfernen“ wie App.removeSick: der ganze Block -> {block, state}
//   lock {date}                          -> {lock, canReport, startTab}: Sperre, Knopf „Krank melden“, erster Reiter
//   request {}                           -> {entries, reservations, sick, last_pull_at}: das erste Päckchen des
//                                        nächsten Abgleichs, gebaut wie SyncClient._runOnce (Krankheit nur mit Fähigkeit)
//   apply {response}                     die Antwort des Desktops zum letzten `request` anwenden -> state
//   state {}                             -> {sick, capable, pending, reservations, last_pull_at}
import { createInterface } from 'node:readline';
import { Store } from '../pwa/store.js';
import { createMemoryAdapter } from '../pwa/memory-adapter.js';
import { parseSyncResponse } from '../pwa/sync.js';
import { blockOf } from '../pwa/sick.js';
import { canReportSick, editLock, editorStartTab, sickDialogModel } from '../pwa/view-model.js';
import { reservationEditable } from '../pwa/reservations.js';

let clock = new Date('2026-10-08T12:00:00Z');
const today = () => clock.toISOString().slice(0, 10);
const store = new Store(createMemoryAdapter(), () => clock);
await store.load();
await store.setMeta({ device_id: 'phone-0001', token: 'T0' });
let snapshot = { entries: {}, versions: {}, reservations: {}, reservationVersions: {}, sick: {}, sickVersions: {} };

function state() {
  const meta = store.getMeta();
  const reservations = {};
  for (const date of store.reservationDates()) {
    const r = store.getReservation(date);
    reservations[date] = { slots: r.slots, deleted: r.deleted, dirty: r.dirty };
  }
  return { sick: store.sickDays(), capable: meta.sick_capable, pending: store.pendingCount(), reservations,
    last_pull_at: meta.last_pull_at };
}

const handlers = {
  async clock({ now }) { clock = new Date(now); return {}; },
  async report({ from, to, deleteReservations }) {
    const model = sickDialogModel({ date: from, to, today: today(), meta: store.getMeta(),
      getDay: (day) => store.getDay(day), getReservation: (day) => store.getReservation(day) });
    if (!model.canSave) throw new Error(model.error);
    await store.markSick(from, to);
    if (deleteReservations) for (const day of model.reservations.dates) await store.clearReservation(day);
    return { offered: model.reservations, state: state() };
  },
  async remove({ date }) {
    const block = blockOf(store.sickDays(), date);
    if (block) await store.clearSick(block.dates);
    return { block, state: state() };
  },
  async lock({ date }) {
    const meta = store.getMeta();
    const lock = editLock({ date, today: today(), meta, hasRecord: Boolean(store.getDay(date)) });
    const reservationOn = Boolean(meta.reservations_enabled) && reservationEditable(date, today());
    return { lock, canReport: canReportSick({ date, today: today(), meta }),
      startTab: editorStartTab({ date, today: today(), reservationOn, lock }) };
  },
  async request() {
    const meta = store.getMeta();
    snapshot = { ...store.snapshotDirty(400, new Set()), ...store.snapshotReservations(),
      ...(meta.sick_capable ? store.snapshotSick() : { sick: {}, sickVersions: {} }) };
    return { entries: snapshot.entries, reservations: snapshot.reservations, sick: snapshot.sick,
      last_pull_at: meta.last_pull_at || '' };
  },
  async apply({ response }) {
    const parsed = parseSyncResponse({ ...response, token: 'T1'.padEnd(43, 'x'), expires_at: '2026-11-07T12:00:00Z' });
    await store.applyResponse(parsed, snapshot, today());
    return state();
  },
  async state() { return state(); },
};

for await (const line of createInterface({ input: process.stdin })) {
  if (!line.trim()) continue;
  const { cmd, ...args } = JSON.parse(line);
  let out;
  try { out = { ok: (await handlers[cmd](args)) ?? null }; } catch (error) { out = { error: String(error.message || error) }; }
  console.log(JSON.stringify(out));
}
