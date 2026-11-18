// pwa/test/slot-order.test.js
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

import { normalizeSlotOrder, sortedSlots } from '../slot-order.js';

const cases = JSON.parse(readFileSync(new URL('./fixtures/slot-order-cases.json', import.meta.url)));

for (const [mode, rows] of Object.entries(cases)) {
  for (const row of rows) {
    test(`sortedSlots ${mode}: ${row.name}`, () => {
      assert.deepEqual(sortedSlots(row.slots, mode), row.order.map((i) => row.slots[i]));
    });
  }
}

test('ein unbekannter Modus sortiert chronologisch', () => {
  const slots = [{ start: '11:00', end: '12:00' }, { start: '09:00', end: '10:00' }];
  for (const mode of [undefined, null, '', 'quatsch', 3]) {
    assert.deepEqual(sortedSlots(slots, mode), [slots[1], slots[0]], String(mode));
  }
});

test('normalizeSlotOrder lässt nur die drei Modi zu', () => {
  assert.deepEqual(['chrono', 'category', 'custom'].map(normalizeSlotOrder), ['chrono', 'category', 'custom']);
  for (const bad of [undefined, null, '', 'Chrono', 3, ['custom']]) assert.equal(normalizeSlotOrder(bad), 'chrono');
});

test('sortedSlots ändert die Eingabe nicht und liefert dieselben Objekte', () => {
  const slots = [{ start: '11:00', end: '12:00' }, { start: '09:00', end: '10:00' }];
  const copy = structuredClone(slots);
  const result = sortedSlots(slots);
  assert.deepEqual(slots, copy);
  assert.equal(result[0], slots[1]);
});

test('sortedSlots mit Unbrauchbarem wirft nicht', () => {
  assert.deepEqual(sortedSlots(undefined), []);
  assert.deepEqual(sortedSlots(null), []);
  assert.equal(sortedSlots([null, { start: '08:00', end: '09:00' }])[0].start, '08:00');
});
