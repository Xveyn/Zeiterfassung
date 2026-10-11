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

const base = { today: TODAY, windowDays: 90, windowMax: 365, maxKnown: true, acked: 90 };

test('a week inside the window needs nothing', () => {
  assert.deepEqual(olderState({ ...base, firstDay: '2026-07-13' }), { kind: 'none' });   // 87 Tage zurück
  assert.deepEqual(olderState({ ...base, firstDay: '2026-10-05' }), { kind: 'none' });
  assert.deepEqual(olderState({ ...base, firstDay: '2026-10-12' }), { kind: 'none' });   // Zukunft
});

test('a week before the window offers to load older times with the right step', () => {
  assert.deepEqual(olderState({ ...base, firstDay: '2026-07-06' }), { kind: 'load', wish: 180 });  // 94 Tage
  assert.deepEqual(olderState({ ...base, firstDay: '2026-01-05' }), { kind: 'load', wish: 365 });  // 276 Tage
});

test('an old desktop (answered without a maximum) cannot load more', () => {
  assert.deepEqual(olderState({ ...base, windowMax: null, firstDay: '2026-07-06' }), { kind: 'old_desktop' });
});

test('before the first answer the maximum is unknown, which is not the same as an old desktop (#292)', () => {
  assert.deepEqual(olderState({ ...base, windowMax: null, maxKnown: false, firstDay: '2026-07-06' }), { kind: 'unknown' });
});

test('a window that already equals the desktop maximum is capped', () => {
  assert.deepEqual(olderState({ ...base, windowDays: 180, windowMax: 180, acked: 365, firstDay: '2025-12-01' }),
    { kind: 'capped', days: 180 });
  assert.deepEqual(olderState({ ...base, windowDays: 90, windowMax: 90, firstDay: '2026-07-06' }),
    { kind: 'capped', days: 90 });
});

test('a window below what was asked for and below the maximum was cut by the data volume', () => {
  assert.deepEqual(olderState({ ...base, windowDays: 120, acked: 365, firstDay: '2026-01-05' }),
    { kind: 'trimmed', days: 120 });
  // ... auch dann, wenn eine noch größere Stufe angeboten würde: sie änderte nichts.
  assert.deepEqual(olderState({ ...base, windowDays: 120, acked: 180, firstDay: '2025-12-01' }),
    { kind: 'trimmed', days: 120 });
});

test('a wish the desktop has not answered yet is never reported as trimmed (#292)', () => {
  // Der Nutzer hat gerade „laden (bis 180)“ getippt (Wunsch 180), die Antwort fehlt noch oder der
  // Abgleich ist fehlgeschlagen: das letzte bestätigte Fenster war 90 mit Wunsch 90.
  assert.deepEqual(olderState({ ...base, acked: 90, firstDay: '2026-07-06' }), { kind: 'load', wish: 180 });
});

test('after loading, the notice disappears once the week is inside the window', () => {
  assert.deepEqual(olderState({ ...base, windowDays: 180, acked: 180, firstDay: '2026-07-06' }), { kind: 'none' });
});

test('absurd inputs never throw', () => {
  for (const firstDay of ['', 'kaputt', null, undefined]) {
    assert.deepEqual(olderState({ ...base, firstDay }), { kind: 'none' });
  }
  assert.deepEqual(olderState({ ...base, windowDays: 'x', firstDay: '2026-07-06' }), { kind: 'none' });
  assert.deepEqual(olderState({ ...base, acked: 'x', firstDay: '2026-07-06' }), { kind: 'load', wish: 180 });
});
