// pwa/test/slot-order.test.js
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

import { sortedSlots } from '../slot-order.js';

const cases = JSON.parse(readFileSync(new URL('./fixtures/slot-order-cases.json', import.meta.url)));

for (const row of cases.chrono) {
  test(`sortedSlots: ${row.name}`, () => {
    assert.deepEqual(sortedSlots(row.slots), row.order.map((i) => row.slots[i]));
  });
}

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
