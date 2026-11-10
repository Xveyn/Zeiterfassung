// pwa/test/push-wiring.test.js
// `app.js` hat keinen Test mit Browser; die Auslöser des Zeitplan-Versands (#507) werden deshalb am Quelltext
// festgehalten. Das Verhalten selbst prüfen push-scheduler.test.js und push-sync.test.js.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const source = readFileSync(new URL('../app.js', import.meta.url), 'utf8');
const method = (name) => {
  const start = source.indexOf(`\n  ${name}(`);
  assert.notEqual(start, -1, `${name} fehlt`);
  return source.slice(start, source.indexOf('\n  }\n', start));
};

test('saving sends the plan at once: no timer stands between the entry and the relay', () => {
  assert.match(method('scheduleSyncAfterSave'), /this\.schedulePushUpdate\(\)/);
  assert.match(method('schedulePushUpdate'), /this\.pushScheduler\.request\(\)/);
  assert.doesNotMatch(method('schedulePushUpdate'), /setTimeout/);
  assert.doesNotMatch(source, /setTimeout\(\(\) => this\.updatePushSchedule\(\)/);
});

test('every send goes through the one scheduler, there is no second busy flag that drops requests', () => {
  assert.match(source, /createPushScheduler\(\{ run: \(\) => this\.sendPushPlan\(\) \}\)/);
  assert.doesNotMatch(source, /pushBusy/);
  assert.match(method('updatePushSchedule'), /this\.pushScheduler\.request\(\)/);
});

test('coming back online and hiding the app both send the plan, independent of the desktop sync', () => {
  const online = /addEventListener\('online', \(\) => \{([^\n]*)\}\);/.exec(source);
  assert.ok(online, 'online-Handler fehlt');
  assert.match(online[1], /this\.updatePushSchedule\(\)/);
  const hidden = /if \(document\.visibilityState !== 'visible'\) \{([\s\S]*?)return;/.exec(source);
  assert.ok(hidden, 'Zweig für die versteckte App fehlt');
  assert.match(hidden[1], /this\.updatePushSchedule\(\)/);
});

test('the plan is computed from the local store only: the sender takes no sync result', () => {
  const send = method('async sendPushPlan');
  assert.match(send, /syncPushPlan\(\{/);
  assert.match(send, /store: this\.store/);
  assert.doesNotMatch(send, /lastError|this\.syncing|this\.online/);
});

test('unpairing stops the scheduler before the data is wiped', () => {
  const stop = source.indexOf('this.pushScheduler.stop()');
  const run = source.indexOf('const result = await runner();');
  assert.ok(stop !== -1 && run !== -1 && stop < run);
});
