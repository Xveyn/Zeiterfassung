// pwa/test/defaults.test.js
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

import { parseDefaults, parseDesktopInfo, resolveSlotDefaults, weekdayKey } from '../defaults.js';

const cases = JSON.parse(readFileSync(new URL('./fixtures/category-defaults-cases.json', import.meta.url)));

// Dieselben Fälle prüft tests/test_mobile_contract.py gegen category_defaults.resolve_slot_defaults.
for (const c of cases) {
  test(`resolveSlotDefaults: ${c.name}`, () => {
    assert.deepEqual(resolveSlotDefaults(c.defaults, c.kategorie, c.weekday), c.expected);
  });
}

test('weekdayKey maps an ISO date to the desktop weekday key', () => {
  assert.equal(weekdayKey('2026-10-05'), 'mon');
  assert.equal(weekdayKey('2026-10-09'), 'fri');
  assert.equal(weekdayKey('2026-10-11'), 'sun');
});

test('resolveSlotDefaults ignores prototype keys as category names', () => {
  const defaults = parseDefaults({ pause: 30, weekdays: {}, category_times: {} });
  assert.deepEqual(resolveSlotDefaults(defaults, '__proto__', 'mon'), { start: '', end: '', pause: 30 });
  assert.deepEqual(resolveSlotDefaults(defaults, 'constructor', 'mon'), { start: '', end: '', pause: 30 });
});

test('parseDefaults keeps a valid document', () => {
  const raw = JSON.parse(readFileSync(new URL('./fixtures/sync-response.json', import.meta.url))).defaults;
  const parsed = parseDefaults(raw);
  assert.equal(parsed.pause, 30);
  assert.deepEqual(parsed.weekdays.mon, { start: '08:00', end: '16:00' });
  assert.deepEqual(parsed.category_times.Projekt, { start: '09:00', end: '17:00', pause: 45 });
});

test('parseDefaults returns null for anything that is not a document (older desktop, garbage)', () => {
  for (const bad of [undefined, null, 'x', 5, [], { pause: 'x' }, { pause: 30 }, { pause: 30, weekdays: [] }]) {
    assert.equal(parseDefaults(bad), null, JSON.stringify(bad));
  }
});

test('parseDefaults drops invalid fields instead of passing them on', () => {
  const parsed = parseDefaults({
    pause: 30,
    weekdays: { mon: { start: '8:00', end: '16:00' }, xyz: { start: '09:00' } },
    category_times: {
      A: { start: '25:00', end: '12:00', pause: -1, evil: 1 },
      B: { mode: 'per_day', days: { tue: { start: '07:00' }, bogus: { start: '01:00' } } },
      C: 'x',
    },
  });
  assert.deepEqual(parsed.weekdays.mon, { start: '', end: '16:00' });
  assert.equal(parsed.weekdays.xyz, undefined);
  assert.deepEqual(parsed.category_times.A, { end: '12:00' });
  assert.deepEqual(parsed.category_times.B, { mode: 'per_day', days: { tue: { start: '07:00' } } });
  assert.equal(Object.hasOwn(parsed.category_times, 'C'), false);
});

test('parseDesktopInfo accepts strings and falls back to empty values', () => {
  assert.deepEqual(parseDesktopInfo({ name: 'PC', version: '1.24.0', platform: 'Linux' }),
    { name: 'PC', version: '1.24.0', platform: 'Linux' });
  assert.deepEqual(parseDesktopInfo(undefined), { name: '', version: '', platform: '' });
  assert.deepEqual(parseDesktopInfo({ name: 5, version: null, platform: 'x'.repeat(500) }),
    { name: '', version: '', platform: '' });
});
