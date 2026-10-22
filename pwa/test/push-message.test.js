// pwa/test/push-message.test.js
import { test } from 'node:test';
import assert from 'node:assert/strict';

import { clickTarget, describe, messageFor } from '../push-message.js';

const item = (kind, extra = {}) => ({
  id: 'x', fireAt: new Date('2026-10-22T10:00:00Z'), kind, date: '2026-10-22', category: 'Projekt', end: '12:00', ...extra,
});
const SCOPE = 'https://xveyn.github.io/Zeiterfassung/';

test('the plain text carries only what the notification needs', () => {
  assert.deepEqual(messageFor(item('upcoming')), { k: 'upcoming', c: 'Projekt', e: '12:00', d: '2026-10-22' });
  assert.deepEqual(messageFor(item('missed')), { k: 'missed', c: 'Projekt', e: '12:00', d: '2026-10-22' });
  assert.deepEqual(messageFor(item('send', { date: '', category: '', end: '' })), { k: 'send', t: 1792663200 });
});

test('a long category is cut to the allowed length', () => {
  assert.equal(messageFor(item('upcoming', { category: 'k'.repeat(300) })).c.length, 100);
});

test('texts per kind', () => {
  assert.deepEqual(describe({ k: 'upcoming', c: 'Projekt', e: '12:00', d: '2026-10-22' }), {
    title: 'Erinnerung: Projekt', body: 'Deine Reservierung endet um 12:00 Uhr.', tag: 'upcoming-2026-10-22-12:00-Projekt' });
  assert.deepEqual(describe({ k: 'missed', c: 'Projekt', e: '12:00', d: '2026-10-22' }), {
    title: 'Zeit nicht erfasst: Projekt', body: 'Die Reservierung bis 12:00 Uhr ist vorbei, es fehlt die Ist-Zeit.', tag: 'missed-2026-10-22-12:00-Projekt' });
  assert.deepEqual(describe({ k: 'send', t: 1792663200 }), {
    title: 'Arbeitszeiten senden', body: 'Zeit, die Arbeitszeiten zu senden.', tag: 'send-1792663200' });
});

test('anything unusable becomes the general notification', () => {
  const general = { title: 'Erinnerung', body: 'Zeiterfassung öffnen.' };
  for (const bad of [null, undefined, 5, 'text', [], {}, { k: 'unbekannt' }, { k: 'upcoming' }, { k: 'upcoming', c: 5, e: '12:00' }]) {
    assert.deepEqual(describe(bad), general, JSON.stringify(bad));
  }
});

test('the click opens the day for reservation reminders and the app otherwise', () => {
  assert.equal(clickTarget({ k: 'upcoming', c: 'P', e: '12:00', d: '2026-10-22' }, SCOPE), `${SCOPE}?open=2026-10-22`);
  assert.equal(clickTarget({ k: 'missed', c: 'P', e: '12:00', d: '2026-10-22' }, SCOPE), `${SCOPE}?open=2026-10-22`);
  assert.equal(clickTarget({ k: 'send', t: 1 }, SCOPE), SCOPE);
  assert.equal(clickTarget({ k: 'upcoming', d: 'morgen' }, SCOPE), SCOPE);
  assert.equal(clickTarget(null, SCOPE), SCOPE);
});
