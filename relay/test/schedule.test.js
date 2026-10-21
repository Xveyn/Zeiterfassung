// relay/test/schedule.test.js
import assert from 'node:assert/strict';
import test from 'node:test';
import { afterFailure, idleAt, planAlarm } from '../src/schedule.js';

const NOW = Date.parse('2026-10-21T12:00:00Z');
const MIN = 60_000;
const item = (id, fireAt, over = {}) => ({ id, fireAt, blob: 'b', ...over });
const IDLE = NOW + 90 * 86_400_000;

test('idleAt is 90 days after the given time', () => {
  assert.equal(idleAt(NOW), IDLE);
});

test('due and keep are split at now', () => {
  const plan = planAlarm([item('past', NOW - MIN), item('now', NOW), item('later', NOW + MIN)], NOW, IDLE);
  assert.deepEqual(plan.due.map((i) => i.id), ['past', 'now']);
  assert.deepEqual(plan.keep.map((i) => i.id), ['later']);
});

test('an item 16 minutes late is dropped, 14 minutes late is due', () => {
  const plan = planAlarm([item('old', NOW - 16 * MIN), item('ok', NOW - 14 * MIN)], NOW, IDLE);
  assert.deepEqual(plan.due.map((i) => i.id), ['ok']);
  assert.deepEqual(plan.keep, []);
});

test('alarmAt is the earliest keep item', () => {
  const plan = planAlarm([item('b', NOW + 5 * MIN), item('a', NOW + 2 * MIN)], NOW, IDLE);
  assert.equal(plan.alarmAt, NOW + 2 * MIN);
});

test('alarmAt falls back to idleAt for an empty plan', () => {
  assert.equal(planAlarm([], NOW, IDLE).alarmAt, IDLE);
});

test('alarmAt never exceeds idleAt', () => {
  const plan = planAlarm([item('far', IDLE + MIN)], NOW, IDLE);
  assert.equal(plan.alarmAt, IDLE);
});

test('the 15 minutes count from the first due time, not from a retry time', () => {
  const retried = item('r', NOW + 30_000, { attempts: 1, dueAt: NOW - 16 * MIN });
  const plan = planAlarm([retried], NOW + 30_000, IDLE);
  assert.deepEqual(plan.due, []);
  assert.deepEqual(plan.keep, []);
});

test('afterFailure backs off 30 s then 120 s then 600 s', () => {
  const first = afterFailure(item('a', NOW), NOW);
  assert.equal(first.attempts, 1);
  assert.equal(first.fireAt, NOW + 30_000);
  const second = afterFailure(first, NOW + 30_000);
  assert.equal(second.attempts, 2);
  assert.equal(second.fireAt, NOW + 30_000 + 120_000);
});

test('afterFailure returns null once 15 minutes after the first due time have passed', () => {
  const late = item('a', NOW - 14 * MIN - 50_000);      // 30 s später wäre es hinter der Frist
  assert.equal(afterFailure(late, NOW), null);
  assert.equal(afterFailure(item('b', NOW), NOW + 14 * MIN + 40_000), null);
});

test('afterFailure returns null after the last backoff step', () => {
  const third = afterFailure({ ...item('a', NOW), attempts: 2, dueAt: NOW }, NOW + 150_000);
  assert.equal(third.attempts, 3);
  assert.equal(afterFailure(third, NOW + 750_000), null);
});

test('dueAt survives repeated failures', () => {
  const first = afterFailure(item('a', NOW), NOW);
  const second = afterFailure(first, first.fireAt);
  assert.equal(first.dueAt, NOW);
  assert.equal(second.dueAt, NOW);
});
