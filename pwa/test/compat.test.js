// pwa/test/compat.test.js
// Verträglichkeit mit älteren Desktops (#290). Die Dateien unter fixtures/compat/ sind EINGEFROREN: Kopien
// der Vertragsbeispiele zu dem Zeitpunkt, an dem die Form galt. Sie werden nicht mitgezogen, wenn sich
// das Live-Beispiel (fixtures/sync-response.json) ändert — genau dann sollen sie zeigen, ob die PWA die
// alte Form noch versteht. Regeln: pwa/CLAUDE.md, Abschnitt „Kompatibilität“.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

import { parseSyncResponse } from '../sync.js';

const frozen = (name) => JSON.parse(readFileSync(new URL(`./fixtures/compat/${name}`, import.meta.url)));

test('the response of a desktop before #288 (no defaults, no desktop info) is still understood', () => {
  const parsed = parseSyncResponse(frozen('sync-response-pre-288.json'));
  assert.equal(parsed.defaults, null);
  assert.deepEqual(parsed.desktop, { name: '', version: '', platform: '' });
  assert.deepEqual(Object.keys(parsed.entries), ['2026-10-07', '2026-10-06']);
  assert.equal(parsed.token.length, 43);
});

test('every frozen response keeps the fields the phone relies on', () => {
  const doc = frozen('sync-response-pre-288.json');
  for (const key of ['protocol', 'server_time', 'last_pull_at', 'excluded', 'window_days', 'entries', 'conflicts', 'categories']) {
    assert.ok(key in doc, key);
  }
});
