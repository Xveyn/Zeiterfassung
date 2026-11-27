// pwa/test/compat.test.js
// Verträglichkeit mit älteren Desktops (#290). Die Dateien unter fixtures/compat/ sind EINGEFROREN: Kopien
// der Vertragsbeispiele zu dem Zeitpunkt, an dem die Form galt. Sie werden nicht mitgezogen, wenn sich
// das Live-Beispiel (fixtures/sync-response.json) ändert — genau dann sollen sie zeigen, ob die PWA die
// alte Form noch versteht. Regeln: pwa/CLAUDE.md, Abschnitt „Kompatibilität“.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

import { parseSyncResponse } from '../sync.js';
import { Store } from '../store.js';
import { createMemoryAdapter } from '../memory-adapter.js';

const frozen = (name) => JSON.parse(readFileSync(new URL(`./fixtures/compat/${name}`, import.meta.url)));

test('the response of a desktop before #288 (no defaults, no desktop info) is still understood', () => {
  const parsed = parseSyncResponse(frozen('sync-response-pre-288.json'));
  assert.equal(parsed.defaults, null);
  assert.deepEqual(parsed.desktop, { name: '', version: '', platform: '' });
  assert.deepEqual(Object.keys(parsed.entries), ['2026-10-07', '2026-10-06']);
  assert.equal(parsed.token.length, 43);
});

test('every frozen response keeps the fields the phone relies on', () => {
  const doc = frozen('sync-response-pre-288.json');
  for (const key of ['protocol', 'server_time', 'last_pull_at', 'excluded', 'window_days', 'entries', 'conflicts', 'categories']) {
    assert.ok(key in doc, key);
  }
});

test('the response of a desktop before the window wish (#250) is still understood', () => {
  const doc = frozen('sync-response-pre-250.json');
  assert.ok(!('window_max_days' in doc));
  const parsed = parseSyncResponse(doc);
  assert.equal(parsed.window_max, null);                 // unbekannt = älterer Desktop
  assert.equal(parsed.window_days, 90);
  assert.deepEqual(Object.keys(parsed.entries), ['2026-10-07', '2026-10-06']);
});

test('the response of a desktop before the reservations is still understood and keeps the feature hidden', () => {
  const doc = frozen('sync-response-pre-reservations.json');
  assert.ok(!('reservations' in doc));
  const parsed = parseSyncResponse(doc);
  assert.equal(parsed.reservations, null);
  assert.deepEqual(Object.keys(parsed.entries), ['2026-10-07', '2026-10-06']);
});

test('the response of a desktop before the settings is still understood and offers nothing to write', () => {
  const doc = frozen('sync-response-pre-settings.json');
  assert.ok(!('writable_settings' in doc));
  const parsed = parseSyncResponse(doc);
  assert.deepEqual(parsed.writable_settings, []);
  assert.deepEqual(Object.keys(parsed.entries), ['2026-10-07', '2026-10-06']);
});

test('the response of a desktop before the forward window (#265) is still understood and shows no future days', () => {
  const doc = frozen('sync-response-pre-ahead.json');
  assert.ok(!('window_ahead_days' in doc));
  const parsed = parseSyncResponse(doc);
  assert.equal(parsed.window_ahead, null);               // unbekannt = älterer Desktop
  assert.deepEqual(Object.keys(parsed.entries), ['2026-10-07', '2026-10-06']);
});

test('the response of a desktop before the reservation pause is still understood and sends no pause', () => {
  const doc = frozen('sync-response-pre-pause.json');
  assert.ok(!('reservation_pause' in doc));
  assert.ok(Object.keys(doc.reservations).length > 0);
  for (const day of Object.values(doc.reservations)) {
    for (const slot of day.slots) assert.ok(!('pause' in slot));
  }
  const parsed = parseSyncResponse(doc);
  assert.equal(parsed.reservation_pause, false);
  for (const day of Object.values(parsed.reservations)) {
    for (const slot of day.slots) assert.equal(slot.pause, 0);
  }
});

test('the response of a desktop before the slot order (#520) is still understood and sorts chronologically', () => {
  const doc = frozen('sync-response-pre-slot-order.json');
  assert.ok(!('slot_order' in doc));
  assert.equal(parseSyncResponse(doc).slot_order, 'chrono');
});

test('the slot order of the response is read, anything unknown counts as chronological', () => {
  const doc = frozen('sync-response-pre-slot-order.json');
  for (const [raw, expected] of [['category', 'category'], ['custom', 'custom'], ['chrono', 'chrono'],
    ['alphabetisch', 'chrono'], [3, 'chrono'], [null, 'chrono']]) {
    assert.equal(parseSyncResponse({ ...doc, slot_order: raw }).slot_order, expected, String(raw));
  }
});

test('the response of a desktop before slot notes (#519) is still understood', () => {
  const doc = frozen('sync-response-pre-notes.json');
  assert.ok(!('slot_notes' in doc));
  for (const day of Object.values(doc.entries)) {
    for (const slot of day.slots) assert.ok(!('notiz' in slot));
  }
  const parsed = parseSyncResponse(doc);
  assert.deepEqual(Object.keys(parsed.entries).sort(), Object.keys(doc.entries).sort());
  assert.equal(parsed.conflicts.length, doc.conflicts.length);
});

test('the response of a desktop before sick days leaves the feature off and keeps every stored sick day', async () => {
  const doc = frozen('sync-response-pre-sick.json');
  assert.ok(!('sick_days' in doc) && !('sick' in doc));
  const parsed = parseSyncResponse(doc);
  assert.equal(parsed.sick_days, false);
  assert.equal(parsed.sick, null);

  const store = new Store(createMemoryAdapter(), () => new Date(doc.server_time));
  await store.load();
  await store.setMeta({ sick_capable: true });                      // ein neuerer Desktop war vorher gekoppelt
  await store.markSick('2026-10-01', '2026-10-02');
  const before = store.sickDays();
  await store.applyResponse(parsed, { entries: {}, versions: {}, ...store.snapshotSick() }, doc.server_time.slice(0, 10));
  assert.equal(store.getMeta().sick_capable, false);
  assert.deepEqual(store.sickDays(), before);                       // nichts gelöscht, nichts bestätigt
});

test('the frozen request before slot notes is still what the phone sends without slot_notes', async () => {
  const example = frozen('sync-request-pre-notes.json');
  const store = new Store(createMemoryAdapter(), () => new Date(example.client_time));
  await store.load();                                               // nie eine Antwort mit slot_notes gesehen
  await store.setMeta({ device_id: example.entries['2026-10-07'].device_id });
  for (const [date, entry] of Object.entries(example.entries)) {
    if (entry.deleted) {
      await store.saveDay(date, [{ start: '08:00', end: '09:00', pause: 0, kategorie: '' }]);
      await store.clearDay(date);
    } else {
      await store.saveDay(date, entry.slots, { notesKnown: true });   // auch ein bekannter Tag: ohne Fähigkeit keine Notiz
    }
  }
  const { entries } = store.snapshotDirty();
  assert.deepEqual(Object.keys(entries).sort(), Object.keys(example.entries).sort());
  for (const [date, entry] of Object.entries(example.entries)) {
    assert.deepEqual(Object.keys(entries[date]).sort(), Object.keys(entry).sort(), date);
    assert.deepEqual(entries[date].slots, entry.slots, date);
    assert.equal(entries[date].deleted, entry.deleted, date);
  }
});
