// pwa/test/swipe-policy.test.js
import { test } from 'node:test';
import assert from 'node:assert/strict';

import { EDGE_PX, MIN_DISTANCE_PX, swipeDirection } from '../swipe-policy.js';

const base = { pointerType: 'touch', width: 400, startX: 200, startY: 300, endX: 200, endY: 300, durationMs: 200 };
const swipe = (dx, dy = 0, extra = {}) => swipeDirection({ ...base, endX: base.startX + dx, endY: base.startY + dy, ...extra });

test('a swipe to the left shows the next week, to the right the previous one', () => {
  assert.equal(swipe(-120), 'next');
  assert.equal(swipe(120), 'previous');
});

test('a short move is not a swipe', () => {
  assert.equal(swipe(-(MIN_DISTANCE_PX - 1)), null);
  assert.equal(swipe(-MIN_DISTANCE_PX), 'next');
  assert.equal(swipe(0), null);
});

test('a quick flick counts even if it is short', () => {
  assert.equal(swipe(-40, 0, { durationMs: 100 }), 'next');
  assert.equal(swipe(-40, 0, { durationMs: 400 }), null);
  assert.equal(swipe(-10, 0, { durationMs: 20 }), null);
});

test('a mostly vertical move is a scroll, not a swipe', () => {
  assert.equal(swipe(-100, 100), null);
  assert.equal(swipe(-100, 51), null);
  assert.equal(swipe(-100, 50), 'next');
  assert.equal(swipe(-100, -80), null);
});

test('a start in the edge strip belongs to the system back gesture', () => {
  assert.equal(swipe(120, 0, { startX: EDGE_PX - 1, endX: EDGE_PX - 1 + 120 }), null);
  assert.equal(swipe(-120, 0, { startX: 400 - EDGE_PX + 1, endX: 400 - EDGE_PX + 1 - 120 }), null);
  assert.equal(swipe(120, 0, { startX: EDGE_PX, endX: EDGE_PX + 120 }), 'previous');
});

test('only fingers and pens swipe, a mouse drag does not', () => {
  assert.equal(swipe(-120, 0, { pointerType: 'mouse' }), null);
  assert.equal(swipe(-120, 0, { pointerType: 'pen' }), 'next');
});

test('garbage input is no swipe', () => {
  assert.equal(swipeDirection({}), null);
  assert.equal(swipe(NaN), null);
  assert.equal(swipe(-120, 0, { width: 0 }), null);
});
