// pwa/test/push-policy.test.js
import { test } from 'node:test';
import assert from 'node:assert/strict';

import { RESEND_AFTER_MS, describeState, permissionState, shouldSchedule } from '../push-policy.js';

const base = { supported: true, permission: 'granted', subscribed: true, enabled: true };

test('permission states', () => {
  assert.equal(permissionState({ ...base, supported: false }), 'unsupported');
  assert.equal(permissionState({ ...base, permission: 'denied' }), 'denied');
  assert.equal(permissionState({ ...base, enabled: false }), 'off');
  assert.equal(permissionState({ ...base, permission: 'default' }), 'off');
  assert.equal(permissionState(base), 'on');
  assert.equal(permissionState({ ...base, subscribed: false }), 'needs_resubscribe');
});

test('a switched-on feature whose permission was withdrawn is denied, not silently off', () => {
  assert.equal(permissionState({ ...base, permission: 'denied', subscribed: false }), 'denied');
});

const when = { state: 'on', remindersPresent: true, lastSignature: 'a', signature: 'a', lastSentAt: 1000, now: 1000 + 60000 };

test('nothing is sent while unchanged and recent', () => {
  assert.equal(shouldSchedule(when), false);
});

test('a changed plan is sent', () => {
  assert.equal(shouldSchedule({ ...when, signature: 'b' }), true);
});

test('an unchanged plan is sent again after twelve hours', () => {
  assert.equal(RESEND_AFTER_MS, 12 * 60 * 60 * 1000);
  assert.equal(shouldSchedule({ ...when, now: 1000 + RESEND_AFTER_MS - 1 }), false);
  assert.equal(shouldSchedule({ ...when, now: 1000 + RESEND_AFTER_MS }), true);
});

test('never sent before means send', () => {
  assert.equal(shouldSchedule({ ...when, lastSignature: null, lastSentAt: 0 }), true);
});

test('no sending without an enabled state or without the desktop block', () => {
  for (const state of ['off', 'denied', 'unsupported', 'needs_resubscribe']) {
    assert.equal(shouldSchedule({ ...when, state, signature: 'b' }), false, state);
  }
  assert.equal(shouldSchedule({ ...when, remindersPresent: false, signature: 'b' }), false);
});

test('every state has a text and the right action', () => {
  assert.deepEqual(describeState('on', null).action, 'disable');
  assert.deepEqual(describeState('off', null).action, 'enable');
  assert.deepEqual(describeState('needs_resubscribe', null).action, 'enable');
  assert.equal(describeState('denied', null).action, null);
  assert.equal(describeState('unsupported', null).action, null);
  for (const state of ['on', 'off', 'denied', 'unsupported', 'needs_resubscribe']) {
    assert.ok(describeState(state, null).text.length > 10, state);
  }
});

test('an error text is added to the state text', () => {
  assert.match(describeState('on', 'Der Relay ist nicht erreichbar.').text, /Der Relay ist nicht erreichbar\./);
  assert.doesNotMatch(describeState('on', null).text, /Relay/);
});
