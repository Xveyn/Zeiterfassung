// pwa/test/reminders-plan.test.js
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

import { MAX_ITEMS, planReminders, signature } from '../reminders-plan.js';
import { localIsoDate } from '../minutes.js';

const cases = JSON.parse(readFileSync(new URL('./fixtures/reminder-plan-cases.json', import.meta.url)));

/** 'YYYY-MM-DDTHH:MM' als lokale Wanduhrzeit des Rechners. */
const wall = (text) => {
  const [date, time] = text.split('T');
  const [y, m, d] = date.split('-').map(Number);
  const [h, mi] = time.split(':').map(Number);
  return new Date(y, m - 1, d, h, mi);
};
const wallText = (date) => `${localIsoDate(date)}T${String(date.getHours()).padStart(2, '0')}:${String(date.getMinutes()).padStart(2, '0')}`;
const block = (c) => ({
  reservation: { enabled: c.reservation_enabled !== false, minutes_before: c.minutes_before },
  send: { enabled: c.send_at.length > 0, at: c.send_at },
});

for (const c of cases) {
  test(`plan: ${c.name}`, () => {
    const items = planReminders({ reservations: c.reservations, entries: c.entries, reminders: block(c), now: wall(c.now) });
    assert.deepEqual(
      items.map((i) => ({ kind: i.kind, date: i.date, category: i.category, end: i.end, fire: wallText(i.fireAt) })),
      c.expected);
  });
}

const slot = (start, end) => ({ slots: [{ start, end, kategorie: 'Projekt' }], deleted: false });
const reminders = { reservation: { enabled: true, minutes_before: 15 }, send: { enabled: false, at: [] } };

test('send reminders come from the desktop list, only future and only when enabled', () => {
  const now = wall('2026-10-22T08:00');
  const at = ['2026-10-22T05:00:00Z', '2026-11-01T07:00:00Z'];
  const on = planReminders({ reservations: {}, entries: {}, reminders: { ...reminders, send: { enabled: true, at } }, now: new Date('2026-10-22T06:00:00Z') });
  assert.deepEqual(on.map((i) => [i.kind, i.fireAt.toISOString()]), [['send', '2026-11-01T07:00:00.000Z']]);
  const off = planReminders({ reservations: {}, entries: {}, reminders: { ...reminders, send: { enabled: false, at } }, now });
  assert.deepEqual(off, []);
});

test('ids are unique and valid for the relay', () => {
  const reservations = { '2026-10-22': { slots: [
    { start: '09:00', end: '10:00', kategorie: 'A' }, { start: '10:00', end: '11:00', kategorie: 'B' }], deleted: false } };
  const items = planReminders({ reservations, entries: {}, reminders, now: wall('2026-10-22T08:00') });
  assert.equal(items.length, 4);
  assert.equal(new Set(items.map((i) => i.id)).size, 4);
  for (const item of items) assert.match(item.id, /^[A-Za-z0-9_-]{1,64}$/);
});

test('with more than 200 items the earliest ones stay, in order', () => {
  const reservations = {};
  const at = Array.from({ length: 300 }, (_, i) => new Date(Date.UTC(2026, 10, 1, 0, i)).toISOString().replace(/\.\d+Z$/, 'Z'));
  const items = planReminders({
    reservations, entries: {}, reminders: { ...reminders, send: { enabled: true, at } }, now: new Date('2026-10-22T06:00:00Z'),
  });
  assert.equal(items.length, MAX_ITEMS);
  assert.equal(items[0].fireAt.toISOString(), '2026-11-01T00:00:00.000Z');
  assert.equal(items.at(-1).fireAt.toISOString(), '2026-11-01T03:19:00.000Z');
});

test('the signature changes with the plan and not with the order of input days', () => {
  const now = wall('2026-10-22T08:00');
  const a = planReminders({ reservations: { '2026-10-22': slot('09:00', '12:00') }, entries: {}, reminders, now });
  const b = planReminders({ reservations: { '2026-10-22': slot('09:00', '12:30') }, entries: {}, reminders, now });
  assert.notEqual(signature(a), signature(b));
  assert.equal(signature(a), signature([...a]));
  assert.equal(signature([]), signature([]));
});

test('slots with an unusable time are skipped instead of throwing', () => {
  const reservations = { '2026-10-22': { slots: [{ start: 'kaputt', end: '12:00', kategorie: 'Projekt' }], deleted: false } };
  assert.deepEqual(planReminders({ reservations, entries: {}, reminders, now: wall('2026-10-22T08:00') }), []);
});

test('nothing further than 89 days ahead is planned: the relay would refuse the whole schedule', () => {
  const now = new Date('2026-10-22T06:00:00Z');
  const at = ['2027-01-15T07:00:00Z', '2027-01-21T07:00:00Z'];     // +85 und +91 Tage
  const items = planReminders({ reservations: {}, entries: {}, reminders: { ...reminders, send: { enabled: true, at } }, now });
  assert.deepEqual(items.map((i) => i.fireAt.toISOString()), ['2027-01-15T07:00:00.000Z']);
});
