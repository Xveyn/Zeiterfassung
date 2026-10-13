// pwa/test/reservations.test.js
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

import {
  RESERVATION_HORIZON_DAYS, normalizeReservationSlots, reservationBlockVisible, reservationEditable, reservationSignature,
  validateReservationSlots,
} from '../reservations.js';

const fixture = (name) => JSON.parse(readFileSync(new URL(`./fixtures/${name}`, import.meta.url)));

for (const c of fixture('reservation-visibility-cases.json')) {
  test(`block visibility: ${c.name}`, () => {
    assert.equal(reservationBlockVisible(c.day, c.today), c.visible);
  });
}

test('the horizon is a year', () => {
  assert.equal(RESERVATION_HORIZON_DAYS, 365);
});

test('normalising keeps exactly start, end and a trimmed category', () => {
  assert.deepEqual(
    normalizeReservationSlots([{ start: '09:00', end: '12:00', pause: 30, kategorie: ' Projekt ', gcal_event_id: 'x' }]),
    [{ start: '09:00', end: '12:00', kategorie: 'Projekt' }]);
  assert.deepEqual(normalizeReservationSlots([{ start: '09:00', end: '12:00' }]),
    [{ start: '09:00', end: '12:00', kategorie: '' }]);
  assert.deepEqual(normalizeReservationSlots('kaputt'), []);
});

test('validation reuses the slot rules without a pause', () => {
  assert.equal(validateReservationSlots([{ start: '09:00', end: '12:00', kategorie: '' }]).ok, true);
  assert.equal(validateReservationSlots([]).ok, false);
  assert.equal(validateReservationSlots([{ start: '12:00', end: '09:00', kategorie: '' }]).ok, false);
  assert.equal(validateReservationSlots([
    { start: '09:00', end: '12:00', kategorie: '' }, { start: '11:00', end: '13:00', kategorie: '' }]).ok, false);
});

test('the signature ignores the order of slots', () => {
  const a = { start: '09:00', end: '10:00', kategorie: 'A' };
  const b = { start: '11:00', end: '12:00', kategorie: 'B' };
  assert.equal(reservationSignature([a, b]), reservationSignature([b, a]));
  assert.notEqual(reservationSignature([a]), reservationSignature([b]));
});

test('the phone only offers days the desktop will accept, with a day of margin for clock differences', () => {
  assert.equal(reservationEditable('2026-10-13', '2026-10-13'), true);
  assert.equal(reservationEditable('2027-10-12', '2026-10-13'), true);      // heute + 364
  assert.equal(reservationEditable('2027-10-13', '2026-10-13'), false);     // heute + 365: der Desktop rechnet knapp
  assert.equal(reservationEditable('2026-10-12', '2026-10-13'), false);
});
