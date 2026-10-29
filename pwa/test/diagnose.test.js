// pwa/test/diagnose.test.js
import { test } from 'node:test';
import assert from 'node:assert/strict';

import { MAX_DETAIL_LENGTH, errorDetail, logFailure, withDetail } from '../diagnose.js';
import { updateStatusText } from '../update-policy.js';

test('errorDetail names the error and keeps its message', () => {
  assert.equal(errorDetail(new TypeError('Failed to update a ServiceWorker')), 'TypeError: Failed to update a ServiceWorker');
  const dom = new DOMException('Registration failed - push service error', 'AbortError');
  assert.equal(errorDetail(dom), 'AbortError: Registration failed - push service error');
});

test('errorDetail copes with a missing message, odd values and whitespace', () => {
  assert.equal(errorDetail(new DOMException('', 'NotAllowedError')), 'NotAllowedError');
  assert.equal(errorDetail('kaputt'), 'kaputt');
  assert.equal(errorDetail(new Error('a\n  b\t c')), 'Error: a b c');
  assert.equal(errorDetail(undefined), '');
  assert.equal(errorDetail(null), '');
  assert.equal(errorDetail({}), '');
});

test('errorDetail shortens a long message', () => {
  const detail = errorDetail(new Error('x'.repeat(1000)));
  assert.equal(detail.length, MAX_DETAIL_LENGTH);
  assert.ok(detail.endsWith('…'));
});

test('logFailure warns with the context and the detail, and never throws', () => {
  const lines = [];
  logFailure('Update-Suche', new TypeError('boom'), { warn: (...args) => lines.push(args.join(' ')) });
  assert.deepEqual(lines, ['[Zeiterfassung] Update-Suche: TypeError: boom']);
  assert.doesNotThrow(() => logFailure('x', new Error('y'), { warn: () => { throw new Error('console kaputt'); } }));
  assert.doesNotThrow(() => logFailure('x', new Error('y'), undefined));
});

test('the update status text appends the reason only for a failed check', () => {
  assert.equal(updateStatusText('error'), 'Die Suche nach einer neuen Version ist fehlgeschlagen.');
  assert.equal(updateStatusText('error', 'TypeError: boom'), 'Die Suche nach einer neuen Version ist fehlgeschlagen (TypeError: boom).');
  assert.equal(updateStatusText('error', ''), 'Die Suche nach einer neuen Version ist fehlgeschlagen.');
  assert.equal(updateStatusText('current', 'TypeError: boom'), 'Diese Seite ist aktuell.');
});

test('withDetail puts the reason behind a message, before its final full stop', () => {
  assert.equal(withDetail('Die Kamera ist nicht verfügbar.', new DOMException('Permission denied', 'NotAllowedError')),
    'Die Kamera ist nicht verfügbar (NotAllowedError: Permission denied).');
  assert.equal(withDetail('Es ging schief', new Error('x')), 'Es ging schief (Error: x).');
  assert.equal(withDetail('Es ging schief.', undefined), 'Es ging schief.');
});
