// pwa/test/sick.test.js
import { test } from 'node:test';
import assert from 'node:assert/strict';

import { blockOf, parseSickBlock, reservationDatesIn, sickRange, workBlockedDates } from '../sick.js';

const STAMP = '2026-10-07T18:50:00Z';
const live = { minutes: 450, modified_at: STAMP, deleted: false };

// --- parseSickBlock --------------------------------------------------------------------------------

test('a block that is no object means the desktop sends none', () => {
  for (const raw of [undefined, null, [], 'sick', 3, true]) assert.equal(parseSickBlock(raw), null, String(raw));
});

test('the sick block keeps live days and tombstones and drops unknown fields', () => {
  const parsed = parseSickBlock({
    '2026-10-01': { ...live, device_id: 'DESK', extra: '<b>' },
    '2026-10-02': { minutes: 0, modified_at: STAMP, deleted: true },
  });
  assert.deepEqual(parsed, {
    '2026-10-01': { minutes: 450, modified_at: STAMP, deleted: false },
    '2026-10-02': { minutes: 0, modified_at: STAMP, deleted: true },
  });
});

test('a tombstone carries no minutes, whatever the desktop sent', () => {
  assert.equal(parseSickBlock({ '2026-10-02': { minutes: 300, modified_at: STAMP, deleted: true } })['2026-10-02'].minutes, 0);
});

test('broken days from the desktop are dropped, the rest of the block stays', () => {
  const broken = {
    'kein-datum': live,
    '2026-02-30': live,
    '1999-12-31': live,
    '2026-10-03': 'krank',
    '2026-10-04': null,
    '2026-10-05': { ...live, minutes: -1 },
    '2026-10-06': { ...live, minutes: 1441 },
    '2026-10-07': { ...live, minutes: 7.5 },
    '2026-10-08': { ...live, minutes: '450' },
    '2026-10-09': { ...live, minutes: true },
    '2026-10-10': { ...live, modified_at: 'gestern' },
    '2026-10-11': { ...live, modified_at: 5 },
    '2026-10-12': { minutes: 450, deleted: false },
    '2026-10-13': { ...live, deleted: 'nein' },
    '2026-10-14': { minutes: 450, modified_at: STAMP },
  };
  const parsed = parseSickBlock({ ...broken, '2026-10-15': live, '2026-10-16': { ...live, minutes: 1440 } });
  assert.deepEqual(Object.keys(parsed).sort(), ['2026-10-15', '2026-10-16']);
});

// --- sickRange -------------------------------------------------------------------------------------

test('a range lists every calendar day, across the month', () => {
  assert.deepEqual(sickRange('2026-02-27', '2026-03-02'), ['2026-02-27', '2026-02-28', '2026-03-01', '2026-03-02']);
  assert.deepEqual(sickRange('2026-03-02', '2026-03-02'), ['2026-03-02']);
});

test('a range that makes no sense is empty', () => {
  assert.deepEqual(sickRange('2026-03-02', '2026-03-01'), []);
  assert.deepEqual(sickRange('2026-02-30', '2026-03-02'), []);
  assert.deepEqual(sickRange('2026-03-01', 'morgen'), []);
});

// --- blockOf ---------------------------------------------------------------------------------------

const DAYS = {
  '2026-02-25': { deleted: false },
  // 26.02. fehlt: Lücke
  '2026-02-27': { deleted: false },
  '2026-02-28': { deleted: false },
  '2026-03-01': { deleted: false },
  '2026-03-02': { deleted: false },
  '2026-03-03': { deleted: true },
  '2026-03-04': { deleted: false },
};

test('the block of a day reaches over the month change and stops at a gap or a tombstone', () => {
  const expected = { from: '2026-02-27', to: '2026-03-02', dates: ['2026-02-27', '2026-02-28', '2026-03-01', '2026-03-02'] };
  assert.deepEqual(blockOf(DAYS, '2026-03-01'), expected);
  assert.deepEqual(blockOf(DAYS, '2026-02-27'), expected);
  assert.deepEqual(blockOf(DAYS, '2026-03-02'), expected);
});

test('a single live day is its own block', () => {
  assert.deepEqual(blockOf(DAYS, '2026-02-25'), { from: '2026-02-25', to: '2026-02-25', dates: ['2026-02-25'] });
  assert.deepEqual(blockOf(DAYS, '2026-03-04'), { from: '2026-03-04', to: '2026-03-04', dates: ['2026-03-04'] });
});

test('a tombstone, a missing day or no date at all has no block', () => {
  assert.equal(blockOf(DAYS, '2026-03-03'), null);
  assert.equal(blockOf(DAYS, '2026-02-26'), null);
  assert.equal(blockOf(DAYS, 'kein-datum'), null);
  assert.equal(blockOf({}, '2026-03-01'), null);
});

// --- Sperren und Reservierungen --------------------------------------------------------------------

const SLOT = { start: '08:00', end: '12:00', pause: 0, kategorie: 'Projekt' };

test('only days with work time block a sick report', () => {
  const days = {
    '2026-03-02': { slots: [SLOT], deleted: false },
    '2026-03-03': { slots: [], deleted: true },          // geleert
    '2026-03-04': { slots: [], deleted: false },
  };
  const getDay = (date) => days[date] ?? null;
  assert.deepEqual(workBlockedDates(['2026-03-01', '2026-03-02', '2026-03-03', '2026-03-04'], getDay), ['2026-03-02']);
  assert.deepEqual(workBlockedDates([], getDay), []);
});

test('the reservations of a range are the days with live reservation slots', () => {
  const res = { start: '09:00', end: '12:00', kategorie: 'Projekt', pause: 0 };
  const reservations = {
    '2026-03-02': { slots: [res], deleted: false },
    '2026-03-03': { slots: [], deleted: true },
  };
  const getReservation = (date) => reservations[date] ?? null;
  assert.deepEqual(reservationDatesIn(['2026-03-01', '2026-03-02', '2026-03-03'], getReservation), ['2026-03-02']);
});
