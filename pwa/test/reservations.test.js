// pwa/test/reservations.test.js
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

import {
  RESERVATION_HORIZON_DAYS, normalizeReservationSlots, openReservationSlots, pendingReservationMinutes, reservationBlockVisible, reservationEditable, reservationSignature,
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

// --- Erledigt durch Ist-Zeit derselben Kategorie ---------------------------------------------------

const planned = (start, end, kategorie) => ({ start, end, kategorie });
const actual = (start, end, kategorie) => ({ start, end, pause: 0, kategorie });

test('today a reservation slot is done once actual time with the same category exists, whatever the time', () => {
  const open = openReservationSlots([planned('09:00', '12:00', 'Projekt')], [actual('13:00', '17:00', 'Projekt')], true);
  assert.deepEqual(open, []);
});

test('another category, or no category on either side, does not link the two', () => {
  const slot = planned('09:00', '12:00', 'Projekt');
  assert.deepEqual(openReservationSlots([slot], [actual('09:00', '12:00', 'Support')], true), [slot]);
  const bare = planned('09:00', '12:00', '');
  assert.deepEqual(openReservationSlots([bare], [actual('09:00', '12:00', '')], true), [bare]);
  assert.deepEqual(openReservationSlots([bare], [actual('09:00', '12:00', undefined)], true), [bare]);
});

test('one actual slot completes one reservation slot of its category', () => {
  const morning = planned('08:00', '10:00', 'Projekt');
  const afternoon = planned('13:00', '15:00', 'Projekt');
  assert.deepEqual(openReservationSlots([afternoon, morning], [actual('09:00', '10:00', 'Projekt')], true), [afternoon]);
  assert.deepEqual(openReservationSlots([morning, afternoon], [actual('09:00', '10:00', 'Projekt'), actual('14:00', '15:00', 'Projekt')], true), []);
});

test('on a future day actual time never completes a reservation', () => {
  const slot = planned('09:00', '12:00', 'Projekt');
  assert.deepEqual(openReservationSlots([slot], [actual('09:00', '12:00', 'Projekt')], false), [slot]);
});

test('pending minutes count only the open slots', () => {
  const slots = [planned('08:00', '10:00', 'Projekt'), planned('13:00', '15:30', 'Support')];
  assert.equal(pendingReservationMinutes(slots, [actual('18:00', '19:00', 'Projekt')], true), 150);
  assert.equal(pendingReservationMinutes(slots, [], true), 270);
});
