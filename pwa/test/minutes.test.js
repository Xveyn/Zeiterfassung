// pwa/test/minutes.test.js
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

import {
  MAX_SLOTS, addDays, dayMinutes, formatDateDe, formatMinutes, isIsoDate, isoWeek, localIsoDate,
  mondayOf, normalizeSlots, parseTime, slotMinutes, utcStamp, validateSlots, weekDays,
} from '../minutes.js';

const cases = JSON.parse(readFileSync(new URL('./fixtures/minutes-cases.json', import.meta.url)));

test('parseTime is strict HH:MM', () => {
  assert.equal(parseTime('00:00'), 0);
  assert.equal(parseTime('08:30'), 510);
  assert.equal(parseTime('23:59'), 1439);
  for (const bad of ['8:30', '24:00', '08:60', '08:5', '0830', '08-30', ' 08:30', '08:30 ', '', null,
    undefined, 830, '٠٨:٣٠', '08:30\n']) {
    assert.equal(parseTime(bad), null, String(bad));
  }
});

for (const row of cases.slot_minutes) {
  test(`slotMinutes ${row.start}-${row.end} pause ${row.pause}`, () => {
    assert.equal(slotMinutes(row), row.minutes);
  });
}

test('slotMinutes tolerates broken slots', () => {
  assert.equal(slotMinutes({ start: 'x', end: '12:00', pause: 0 }), 0);
  assert.equal(slotMinutes({ start: '12:00', end: '08:00', pause: 0 }), 0);
  assert.equal(slotMinutes({ start: '08:00', end: '09:00', pause: 90 }), 0);
  assert.equal(slotMinutes({ start: '08:00', end: '12:00', pause: 'abc' }), 240);   // wie sanitize_slot: Pause 0
  assert.equal(slotMinutes({ start: '08:00', end: '12:00', pause: -5 }), 240);
  assert.equal(slotMinutes({ start: '08:00', end: '12:00', pause: 1.5 }), 240);
  assert.equal(slotMinutes(null), 0);
  assert.equal(slotMinutes(undefined), 0);
});

test('a day sums whole minutes per slot, never decimal hours', () => {
  const slots = [{ start: '08:00', end: '10:20', pause: 0 }, { start: '10:30', end: '12:07', pause: 0 }];
  assert.equal(dayMinutes(slots), 140 + 97);
  assert.equal(dayMinutes([]), 0);
});

test('formatMinutes pads the minutes and keeps the hours', () => {
  assert.equal(formatMinutes(0), '0:00');
  assert.equal(formatMinutes(450), '7:30');
  assert.equal(formatMinutes(61), '1:01');
  assert.equal(formatMinutes(6000), '100:00');
  assert.equal(formatMinutes(-5), '0:00');
  assert.equal(formatMinutes(59.9), '0:59');
});

for (const row of cases.validation) {
  test(`validateSlots: ${row.name}`, () => {
    const result = validateSlots(normalizeSlots(row.slots));
    assert.equal(result.ok, row.ok, result.message);
    if (row.message) assert.equal(result.message, row.message);
    if (row.ok) assert.equal(result.message, '');
  });
}

test('validateSlots rejects an empty set and more than 50 slots', () => {
  assert.equal(validateSlots([]).ok, false);
  const many = (n) => Array.from({ length: n }, (_, i) => ({
    start: `${String(Math.floor(i / 60)).padStart(2, '0')}:${String(i % 60).padStart(2, '0')}`,
    end: `${String(Math.floor((i + 1) / 60)).padStart(2, '0')}:${String((i + 1) % 60).padStart(2, '0')}`,
    pause: 0, kategorie: '',
  }));
  assert.equal(MAX_SLOTS, 50);
  assert.equal(validateSlots(many(50)).ok, true);
  assert.equal(validateSlots(many(51)).ok, false);
});

test('validateSlots refuses non-lists and non-objects', () => {
  assert.equal(validateSlots(null).ok, false);
  assert.equal(validateSlots('x').ok, false);
  assert.equal(validateSlots([null]).ok, false);
  assert.equal(validateSlots([5]).ok, false);
});

test('normalizeSlots keeps exactly the four wire fields and trims the category', () => {
  const [slot] = normalizeSlots([{ start: '08:00', end: '12:00', extra: 1, kategorie: '  A ' }]);
  assert.deepEqual(slot, { start: '08:00', end: '12:00', pause: 0, kategorie: 'A' });
  assert.deepEqual(normalizeSlots('x'), []);
});

test('isIsoDate accepts real calendar days from 2000 to 2100', () => {
  for (const ok of ['2026-10-08', '2000-01-01', '2100-12-31', '2024-02-29']) assert.equal(isIsoDate(ok), true, ok);
  for (const bad of ['2026-02-30', '2025-02-29', '1999-12-31', '2101-01-01', '2026-13-01', '2026-1-01',
    '20261008', '2026-10-08 ', '', null, 5, '٢٠٢٦-١٠-٠٨']) assert.equal(isIsoDate(bad), false, String(bad));
});

test('date arithmetic runs in UTC and crosses month and year ends', () => {
  assert.equal(addDays('2026-10-08', 1), '2026-10-09');
  assert.equal(addDays('2026-10-31', 1), '2026-11-01');
  assert.equal(addDays('2026-12-31', 1), '2027-01-01');
  assert.equal(addDays('2026-03-01', -1), '2026-02-28');
  assert.equal(addDays('2024-03-01', -1), '2024-02-29');
  assert.equal(addDays('2026-10-08', -90), '2026-07-10');
});

test('weeks start on Monday', () => {
  assert.equal(mondayOf('2026-10-08'), '2026-10-05');           // Donnerstag
  assert.equal(mondayOf('2026-10-05'), '2026-10-05');
  assert.equal(mondayOf('2026-10-11'), '2026-10-05');           // Sonntag
  assert.deepEqual(weekDays('2026-10-08'), [
    '2026-10-05', '2026-10-06', '2026-10-07', '2026-10-08', '2026-10-09', '2026-10-10', '2026-10-11']);
});

for (const row of cases.iso_weeks) {
  test(`isoWeek ${row.date}`, () => {
    assert.deepEqual(isoWeek(row.date), { year: row.year, week: row.week });
  });
}

test('German date format and the two clock helpers', () => {
  assert.equal(formatDateDe('2026-10-08'), '08.10.2026');
  assert.equal(formatDateDe('nonsense'), 'nonsense');
  assert.equal(utcStamp(new Date(Date.UTC(2026, 9, 8, 12, 0, 5, 999))), '2026-10-08T12:00:05Z');
  assert.equal(localIsoDate(new Date(2026, 9, 8, 23, 59, 59)), '2026-10-08');
  assert.equal(localIsoDate(new Date(2026, 0, 5, 0, 0, 0)), '2026-01-05');
});
