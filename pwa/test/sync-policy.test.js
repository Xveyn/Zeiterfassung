// pwa/test/sync-policy.test.js
import { test } from 'node:test';
import assert from 'node:assert/strict';

import { AUTO_COOLDOWN_MS, OFFLINE_BACKOFF_MS, shouldQueue, shouldSync } from '../sync-policy.js';

const base = { paired: true, syncing: false, online: true, now: 1_000_000, lastAttemptAt: 0, lastError: null };
const ask = (over) => shouldSync({ ...base, ...over });

test('nothing runs without a pairing or while a sync is running', () => {
  for (const trigger of ['start', 'visible', 'online', 'save', 'manual']) {
    assert.equal(ask({ trigger, paired: false }), false, trigger);
    assert.equal(ask({ trigger, syncing: true }), false, trigger);
  }
});

test('manual and save always run, even right after an attempt, offline or with a dead token', () => {
  const hostile = { lastAttemptAt: base.now - 1, online: false, lastError: { kind: 'repair', needsRepair: true } };
  assert.equal(ask({ trigger: 'manual', ...hostile }), true);
  assert.equal(ask({ trigger: 'save', ...hostile, online: true }), true);
});

test('save does not wait for the cooldown', () => {
  assert.equal(ask({ trigger: 'save', lastAttemptAt: base.now - 100 }), true);
});

test('automatic triggers wait for the cooldown', () => {
  for (const trigger of ['start', 'visible', 'online']) {
    assert.equal(ask({ trigger, lastAttemptAt: base.now - 4999 }), false, trigger);
    assert.equal(ask({ trigger, lastAttemptAt: base.now - 5000 }), true, trigger);
    assert.equal(AUTO_COOLDOWN_MS, 5000);
  }
});

test('automatic triggers stay quiet while the browser says offline, except the online event', () => {
  assert.equal(ask({ trigger: 'start', online: false }), false);
  assert.equal(ask({ trigger: 'visible', online: false }), false);
  assert.equal(ask({ trigger: 'online', online: true }), true);
  assert.equal(ask({ trigger: 'online', online: false }), true);   // das Ereignis kommt vor navigator.onLine
});

test('after a network failure start and visible back off, the online event does not', () => {
  const lastError = { kind: 'offline', needsRepair: false };
  const recent = base.now - (OFFLINE_BACKOFF_MS - 1000);
  assert.equal(ask({ trigger: 'start', lastError, lastAttemptAt: recent }), false);
  assert.equal(ask({ trigger: 'visible', lastError, lastAttemptAt: recent }), false);
  assert.equal(ask({ trigger: 'online', lastError, lastAttemptAt: base.now - AUTO_COOLDOWN_MS }), true);
  assert.equal(ask({ trigger: 'start', lastError, lastAttemptAt: base.now - OFFLINE_BACKOFF_MS }), true);
});

test('a dead token stops every automatic trigger until the user pairs again', () => {
  const lastError = { kind: 'repair', needsRepair: true };
  for (const trigger of ['start', 'visible', 'online']) {
    assert.equal(ask({ trigger, lastError }), false, trigger);
  }
});

test('an unknown trigger does nothing', () => {
  assert.equal(ask({ trigger: 'zufall' }), false);
});

test('save and manual are remembered while a sync runs, automatic triggers are not', () => {
  const queue = (trigger, over = {}) => shouldQueue({ trigger, paired: true, syncing: true, ...over });
  assert.equal(queue('save'), true);
  assert.equal(queue('manual'), true);
  for (const trigger of ['start', 'visible', 'online', 'zufall']) assert.equal(queue(trigger), false, trigger);
  assert.equal(queue('save', { syncing: false }), false);
  assert.equal(queue('save', { paired: false }), false);
});
