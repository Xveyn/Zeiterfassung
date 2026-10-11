// pwa/test/window-policy.test.js
import { test } from 'node:test';
import assert from 'node:assert/strict';

import { DEFAULT_WISH, WINDOW_STEPS, daysBack, olderState, stepFor } from '../window-policy.js';

const TODAY = '2026-10-08';

test('the steps and the default wish', () => {
  assert.deepEqual(WINDOW_STEPS, [90, 180, 365]);
  assert.equal(DEFAULT_WISH, 90);
});

test('daysBack counts calendar days', () => {
  assert.equal(daysBack(TODAY, '2026-10-08'), 0);
  assert.equal(daysBack(TODAY, '2026-10-01'), 7);
  assert.equal(daysBack(TODAY, '2025-10-08'), 365);
  assert.equal(daysBack(TODAY, '2026-10-09'), -1);
});

test('stepFor takes the smallest step that covers the need, capped by the maximum', () => {
  assert.equal(stepFor(91, 365), 180);
  assert.equal(stepFor(180, 365), 180);
  assert.equal(stepFor(181, 365), 365);
  assert.equal(stepFor(1000, 365), 365);                 // jenseits: die größte Stufe
  assert.equal(stepFor(200, 180), 180);                  // Obergrenze des Desktops
  assert.equal(stepFor(100, 90), 90);
  assert.equal(stepFor(100, 30), 30);                    // Obergrenze unter dem Standard
});

const base = { today: TODAY, windowDays: 90, windowMax: 365, wish: 90 };

test('a week inside the window needs nothing', () => {
  assert.deepEqual(olderState({ ...base, firstDay: '2026-07-13' }), { kind: 'none' });   // 87 Tage zurück
  assert.deepEqual(olderState({ ...base, firstDay: '2026-10-05' }), { kind: 'none' });
  assert.deepEqual(olderState({ ...base, firstDay: '2026-10-12' }), { kind: 'none' });   // Zukunft
});

test('a week before the window offers to load older times with the right step', () => {
  assert.deepEqual(olderState({ ...base, firstDay: '2026-07-06' }), { kind: 'load', wish: 180 });  // 94 Tage
  assert.deepEqual(olderState({ ...base, firstDay: '2026-01-05' }), { kind: 'load', wish: 365 });  // 276 Tage
});

test('an old desktop (no maximum) cannot load more', () => {
  assert.deepEqual(olderState({ ...base, windowMax: null, firstDay: '2026-07-06' }), { kind: 'old_desktop' });
});

test('when the wish already covers the week but the window did not grow it was capped or trimmed', () => {
  // Obergrenze erreicht: der Desktop kann nicht mehr liefern.
  assert.deepEqual(olderState({ ...base, windowDays: 180, windowMax: 180, wish: 365, firstDay: '2025-12-01' }),
    { kind: 'capped', days: 180 });
  // Wunsch ist erfüllbar, aber die Antwort wurde wegen der Menge gekürzt.
  assert.deepEqual(olderState({ ...base, windowDays: 120, windowMax: 365, wish: 365, firstDay: '2026-01-05' }),
    { kind: 'trimmed', days: 120 });
});

test('after loading, the notice disappears once the week is inside the window', () => {
  assert.deepEqual(olderState({ ...base, windowDays: 180, wish: 180, firstDay: '2026-07-06' }), { kind: 'none' });
});

test('absurd inputs never throw', () => {
  for (const firstDay of ['', 'kaputt', null, undefined]) {
    assert.deepEqual(olderState({ ...base, firstDay }), { kind: 'none' });
  }
  assert.deepEqual(olderState({ ...base, windowDays: 'x', firstDay: '2026-07-06' }), { kind: 'none' });
});
