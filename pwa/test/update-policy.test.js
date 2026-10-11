// pwa/test/update-policy.test.js
import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
  UPDATE_CHECK_INTERVAL_MS, shouldApplyUpdate, shouldCheckForUpdate, updateStatusText,
} from '../update-policy.js';

const base = { trigger: 'visible', now: 10_000_000, lastCheckAt: 0, online: true, checking: false, supported: true };

test('the update check runs at most every 30 minutes on its own', () => {
  assert.equal(UPDATE_CHECK_INTERVAL_MS, 30 * 60 * 1000);
  assert.equal(shouldCheckForUpdate(base), true);
  assert.equal(shouldCheckForUpdate({ ...base, lastCheckAt: base.now - UPDATE_CHECK_INTERVAL_MS + 1 }), false);
  assert.equal(shouldCheckForUpdate({ ...base, lastCheckAt: base.now - UPDATE_CHECK_INTERVAL_MS }), true);
  assert.equal(shouldCheckForUpdate({ ...base, trigger: 'start', lastCheckAt: base.now - 1000 }), false);
});

test('a manual check ignores the interval but not a running check', () => {
  assert.equal(shouldCheckForUpdate({ ...base, trigger: 'manual', lastCheckAt: base.now - 1000 }), true);
  assert.equal(shouldCheckForUpdate({ ...base, trigger: 'manual', checking: true }), false);
});

test('no check without a service worker, and none on its own while offline', () => {
  assert.equal(shouldCheckForUpdate({ ...base, supported: false, trigger: 'manual' }), false);
  assert.equal(shouldCheckForUpdate({ ...base, online: false }), false);
  assert.equal(shouldCheckForUpdate({ ...base, online: false, trigger: 'manual' }), true);   // der Nutzer will die Antwort „offline“ sehen
});

test('unknown triggers never check', () => {
  assert.equal(shouldCheckForUpdate({ ...base, trigger: 'save' }), false);
});

const ready = { autoUpdate: true, updateReady: true, dialogOpen: false, syncing: false, requested: false };

test('a waiting update is applied automatically only at a safe moment', () => {
  assert.equal(shouldApplyUpdate(ready), true);
  assert.equal(shouldApplyUpdate({ ...ready, autoUpdate: false }), false);       // Standard: Nutzer entscheidet
  assert.equal(shouldApplyUpdate({ ...ready, updateReady: false }), false);
  assert.equal(shouldApplyUpdate({ ...ready, dialogOpen: true }), false);        // offene Eingabe
  assert.equal(shouldApplyUpdate({ ...ready, syncing: true }), false);
  assert.equal(shouldApplyUpdate({ ...ready, requested: true }), false);         // pro Worker genau einmal
});

test('the status text names every state', () => {
  const texts = ['idle', 'checking', 'current', 'available', 'offline', 'error', 'unsupported']
    .map((state) => updateStatusText(state));
  assert.equal(new Set(texts).size, texts.length);
  for (const text of texts) assert.ok(text.length > 3);
  assert.match(updateStatusText('available'), /Neue Version/);
  assert.equal(updateStatusText('völlig_neu'), updateStatusText('idle'));
});
