// pwa/test/shift-policy.test.js
import { test } from 'node:test';
import assert from 'node:assert/strict';

import { EDGE_PX } from '../swipe-policy.js';
import {
  DEFAULT_SHIFT_STEP, SHIFT_STEPS, STEP_PX, mayStartShift, normalizeShiftStep, shiftLabel, shiftOptions, shiftWindow,
  stepsForDistance,
} from '../shift-policy.js';

test('the step is one of the offered values, anything else is the default', () => {
  assert.deepEqual(SHIFT_STEPS, [0, 5, 10, 15, 30, 60]);
  assert.equal(DEFAULT_SHIFT_STEP, 10);
  for (const step of SHIFT_STEPS) assert.equal(normalizeShiftStep(step), step);
  for (const bad of [undefined, null, '10', 7, -5, 1.5, NaN, 120]) assert.equal(normalizeShiftStep(bad), 10);
});

test('every offered step keeps times on the five-minute grid', () => {
  for (const step of SHIFT_STEPS) assert.equal(step % 5, 0);
});

test('only a finger or pen away from the screen edge starts a shift', () => {
  const start = (extra) => mayStartShift({ pointerType: 'touch', width: 400, startX: 200, ...extra });
  assert.equal(start(), true);
  assert.equal(start({ pointerType: 'pen' }), true);
  assert.equal(start({ pointerType: 'mouse' }), false);
  assert.equal(start({ startX: EDGE_PX - 1 }), false);
  assert.equal(start({ startX: EDGE_PX }), true);
  assert.equal(start({ startX: 400 - EDGE_PX + 1 }), false);
  assert.equal(start({ width: 0 }), false);
  assert.equal(start({ startX: NaN }), false);
  assert.equal(mayStartShift(), false);
});

test('the distance snaps to whole steps, towards zero', () => {
  assert.equal(stepsForDistance(0), 0);
  assert.equal(stepsForDistance(STEP_PX - 1), 0);
  assert.equal(stepsForDistance(STEP_PX), 1);
  assert.equal(stepsForDistance(STEP_PX * 4 + 3), 4);
  assert.equal(stepsForDistance(-(STEP_PX - 1)), 0);
  assert.equal(stepsForDistance(-STEP_PX * 2), -2);
  assert.equal(stepsForDistance(NaN), 0);
});

test('right is later, left is earlier, and the duration stays', () => {
  assert.deepEqual(shiftWindow('09:00', '17:00', 4, 10), { start: '09:40', end: '17:40', steps: 4 });
  assert.deepEqual(shiftWindow('09:00', '17:00', -2, 10), { start: '08:40', end: '16:40', steps: -2 });
  assert.deepEqual(shiftWindow('09:00', '17:00', 1, 60), { start: '10:00', end: '18:00', steps: 1 });
  assert.deepEqual(shiftWindow('09:00', '17:00', 0, 10), { start: '09:00', end: '17:00', steps: 0 });
});

test('the window stops at the end of the day in whole steps and never shrinks', () => {
  assert.deepEqual(shiftWindow('22:30', '23:50', 1, 10), { start: '22:30', end: '23:50', steps: 0 });
  assert.deepEqual(shiftWindow('22:30', '23:40', 5, 10), { start: '22:40', end: '23:50', steps: 1 });
  assert.deepEqual(shiftWindow('22:30', '23:49', 9, 10), { start: '22:40', end: '23:59', steps: 1 });
  assert.deepEqual(shiftWindow('20:00', '21:00', 99, 60), { start: '22:00', end: '23:00', steps: 2 });
});

test('the window stops at the start of the day in whole steps', () => {
  assert.deepEqual(shiftWindow('00:05', '08:00', -1, 10), { start: '00:05', end: '08:00', steps: 0 });
  assert.deepEqual(shiftWindow('00:20', '08:00', -5, 10), { start: '00:00', end: '07:40', steps: -2 });
  assert.deepEqual(shiftWindow('00:00', '23:59', 3, 5), { start: '00:00', end: '23:59', steps: 0 });
});

test('times off the grid keep their offset', () => {
  assert.deepEqual(shiftWindow('08:03', '16:33', 1, 10), { start: '08:13', end: '16:43', steps: 1 });
});

test('an incomplete or invalid row is not shifted', () => {
  assert.equal(shiftWindow('', '17:00', 1, 10), null);
  assert.equal(shiftWindow('09:00', '', 1, 10), null);
  assert.equal(shiftWindow('17:00', '09:00', 1, 10), null);
  assert.equal(shiftWindow('09:00', '09:00', 1, 10), null);
  assert.equal(shiftWindow('9:00', '17:00', 1, 10), null);
  assert.equal(shiftWindow('09:00', '17:00', 1, 0), null);
  assert.equal(shiftWindow('09:00', '17:00', 1.5, 10), null);
  assert.equal(shiftWindow(null, undefined, 1, 10), null);
});

test('the live label names the shift in minutes with a real minus sign', () => {
  assert.equal(shiftLabel(20), '+20 min');
  assert.equal(shiftLabel(-10), '−10 min');
  assert.equal(shiftLabel(0), '±0 min');
  assert.equal(shiftLabel(90), '+90 min');
});

test('the settings offer every step with a readable label, off first', () => {
  assert.deepEqual(shiftOptions(), [
    { value: 0, label: 'Aus' },
    { value: 5, label: '5 Minuten je Schritt' },
    { value: 10, label: '10 Minuten je Schritt' },
    { value: 15, label: '15 Minuten je Schritt' },
    { value: 30, label: '30 Minuten je Schritt' },
    { value: 60, label: '60 Minuten je Schritt' },
  ]);
});
