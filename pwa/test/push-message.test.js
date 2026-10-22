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

// --- Testbenachrichtigung (#340) ----------------------------------------------------------------

import { TEST_PAYLOAD, describeTest, testResultText } from '../push-message.js';
import { readFileSync } from 'node:fs';

test('the test notification has its own title, text and tag', () => {
  assert.deepEqual(describeTest(), {
    title: 'Testbenachrichtigung', body: 'Der Weg Relay → Handy funktioniert.', tag: 'test' });
});

test('the test payload is the one the relay sends', () => {
  const source = readFileSync(new URL('../../relay/src/push.js', import.meta.url), 'utf8');
  const match = source.match(/export const TEST_PAYLOAD = '([^']+)'/);
  assert.ok(match);
  assert.equal(TEST_PAYLOAD, match[1]);
});

test('every outcome of the test has a text', () => {
  assert.equal(testResultText('ok'), 'Testbenachrichtigung gesendet. Sie sollte in wenigen Sekunden erscheinen.');
  assert.equal(testResultText('no_subscription'),
    'Der Relay kennt dieses Gerät nicht (mehr). Am Handy die Benachrichtigungen aus- und wieder einschalten.');
  assert.equal(testResultText('gone'),
    'Das Abo des Handys ist abgelaufen. Am Handy die Benachrichtigungen neu erlauben.');
  assert.equal(testResultText('too_soon'), 'Bitte einen Moment warten und dann erneut versuchen.');
  assert.equal(testResultText('rate_limited'), 'Zu viele Anfragen an den Relay, später erneut versuchen.');
  assert.equal(testResultText('unknown_route'),
    'Der Relay kennt den Test noch nicht (muss neu ausgerollt werden).');
  assert.equal(testResultText('offline'), 'Der Relay ist nicht erreichbar.');
  assert.equal(testResultText('push_failed'), 'Der Push-Dienst hat die Nachricht nicht angenommen.');
  for (const kind of ['unauthorized', 'server', 'irgendwas']) assert.ok(testResultText(kind).length > 10, kind);
});
