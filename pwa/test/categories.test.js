// pwa/test/categories.test.js
import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
  MAX_CATEGORIES, blockSignature, categoryRows, moveRow, rowsToBlock, timesSummary, validateCategoryRows,
} from '../categories.js';

const PER_DAY = { mode: 'per_day', pause: 15, days: { fri: { start: '07:00', end: '11:00' }, mon: {} } };
const TIMES = { Projekt: { start: '09:00', end: '17:00', pause: 45 }, Support: PER_DAY };

test('rows read names in order with general times as text and per_day entries kept raw', () => {
  const rows = categoryRows(['Projekt', 'Intern', 'Support'], TIMES);

  assert.deepEqual(rows.map((r) => [r.name, r.mode]), [['Projekt', 'general'], ['Intern', 'general'], ['Support', 'per_day']]);
  assert.deepEqual([rows[0].start, rows[0].end, rows[0].pause], ['09:00', '17:00', '45']);
  assert.deepEqual([rows[1].start, rows[1].end, rows[1].pause], ['', '', '']);
  assert.deepEqual(rows[2].raw, PER_DAY);
});

test('the block round trip keeps names, order and a per_day entry bit-identical', () => {
  const rows = categoryRows(['Projekt', 'Intern', 'Support'], TIMES);

  const block = rowsToBlock(rows);

  assert.deepEqual(block.categories, ['Projekt', 'Intern', 'Support']);
  assert.deepEqual(block.category_times, TIMES);
  assert.notEqual(block.category_times.Support, PER_DAY);           // eine Kopie, nicht dieselbe Referenz
});

test('renaming or moving a per_day row does not touch its times', () => {
  let rows = categoryRows(['Support', 'Projekt'], TIMES);
  rows[0].name = '  Support neu ';
  rows = moveRow(rows, 0, +1);

  const block = rowsToBlock(rows);

  assert.deepEqual(block.categories, ['Projekt', 'Support neu']);
  assert.deepEqual(block.category_times['Support neu'], PER_DAY);
});

test('general rows keep only the fields that are set; pause 0 is a value', () => {
  const rows = categoryRows(['A', 'B', 'C'], {});
  rows[0].start = '08:00';
  rows[1].pause = '0';

  assert.deepEqual(rowsToBlock(rows).category_times, { A: { start: '08:00' }, B: { pause: 0 } });
});

test('moving a row swaps neighbours and ignores moves past the ends', () => {
  const rows = categoryRows(['A', 'B', 'C'], {});
  assert.deepEqual(moveRow(rows, 1, -1).map((r) => r.name), ['B', 'A', 'C']);
  assert.deepEqual(moveRow(rows, 1, +1).map((r) => r.name), ['A', 'C', 'B']);
  assert.equal(moveRow(rows, 0, -1), rows);
  assert.equal(moveRow(rows, 2, +1), rows);
});

const row = (over = {}) => ({ name: 'A', mode: 'general', start: '', end: '', pause: '', raw: null, ...over });

test('a valid list passes', () => {
  assert.equal(validateCategoryRows([row(), row({ name: 'B', start: '08:00', end: '16:00', pause: '30' })]).ok, true);
});

for (const [label, rows, part] of [
  ['an empty name', [row({ name: '  ' })], 'Name'],
  ['a duplicate after trimming', [row(), row({ name: ' A ' })], 'doppelt'],
  ['a name over 100 characters', [row({ name: 'x'.repeat(101) })], '100'],
  ['a control character in the name', [row({ name: 'a\tb' })], 'Zeichen'],
  ['101 categories', Array.from({ length: MAX_CATEGORIES + 1 }, (_, i) => row({ name: `K${i}` })), '100'],
  ['a start that is not HH:MM', [row({ start: '9:00' })], 'Start'],
  ['an end that is not HH:MM', [row({ end: '25:00' })], 'Ende'],
  ['an end before the start', [row({ start: '12:00', end: '09:00' })], 'Ende'],
  ['an end equal to the start', [row({ start: '12:00', end: '12:00' })], 'Ende'],
  ['a negative pause', [row({ pause: '-1' })], 'Pause'],
  ['a pause over 1440', [row({ pause: '1441' })], 'Pause'],
  ['a pause that is not a whole number', [row({ pause: '1.5' })], 'Pause'],
  ['a pause that is text', [row({ pause: 'abc' })], 'Pause'],
]) {
  test(`validation rejects ${label}`, () => {
    const check = validateCategoryRows(rows);
    assert.equal(check.ok, false);
    assert.match(check.message, new RegExp(part));
  });
}

test('start and end alone are fine, a per_day row is not checked for times', () => {
  assert.equal(validateCategoryRows([row({ start: '08:00' }), row({ name: 'B', end: '16:00' })]).ok, true);
  assert.equal(validateCategoryRows([row({ name: 'P', mode: 'per_day', raw: PER_DAY })]).ok, true);
});

test('the summary reads the times in one short line', () => {
  assert.equal(timesSummary(row({ start: '08:00', end: '16:00', pause: '30' })), '08:00–16:00, 30 min Pause');
  assert.equal(timesSummary(row({ start: '08:00' })), 'ab 08:00');
  assert.equal(timesSummary(row({ end: '16:00' })), 'bis 16:00');
  assert.equal(timesSummary(row({ pause: '0' })), '0 min Pause');
  assert.equal(timesSummary(row()), '—');
  assert.equal(timesSummary(row({ mode: 'per_day', raw: PER_DAY })), 'pro Wochentag');
});

test('the signature depends on the order of names but not on the key order of the times', () => {
  assert.equal(blockSignature(['A', 'B'], { A: { start: '08:00', end: '09:00' } }),
    blockSignature(['A', 'B'], { A: { end: '09:00', start: '08:00' } }));
  assert.notEqual(blockSignature(['A', 'B'], {}), blockSignature(['B', 'A'], {}));
});
