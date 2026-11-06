// pwa/test/dialog-history.test.js
import { test } from 'node:test';
import assert from 'node:assert/strict';

import { createDialogHistory } from '../dialog-history.js';

/** Ein Browser-Verlauf wie im echten: `back()` wirkt asynchron und löst danach `popstate` aus; `gesture()` ist die Zurück-Geste. */
function fakeBrowser() {
  const entries = [null];
  let index = 0;
  const listeners = [];
  const settle = () => new Promise((resolve) => { setTimeout(resolve, 0); });
  const goBack = () => {
    if (index === 0) return;
    index -= 1;
    setTimeout(() => listeners.forEach((listener) => listener({ state: entries[index] })), 0);
  };
  const history = {
    pushState(state) { entries.splice(index + 1); entries.push(state); index += 1; },
    back: goBack,
  };
  return { history, addPopListener: (fn) => listeners.push(fn), gesture: goBack, settle, depth: () => index };
}

function fakeDialog() {
  const dialog = new EventTarget();
  dialog.open = true;
  dialog.closed = 0;
  dialog.close = () => { if (!dialog.open) return; dialog.open = false; dialog.closed += 1; dialog.dispatchEvent(new Event('close')); };
  return dialog;
}

test('opening a dialog adds one history entry and closing it by button takes it away again', async () => {
  const browser = fakeBrowser();
  const dialogs = createDialogHistory(browser);
  const dialog = fakeDialog();
  dialogs.attach(dialog);
  assert.equal(browser.depth(), 1);
  dialog.close();
  await browser.settle();
  assert.equal(browser.depth(), 0);
  assert.equal(dialog.closed, 1);
});

test('the back gesture closes the open dialog and leaves the history as it was', async () => {
  const browser = fakeBrowser();
  const dialogs = createDialogHistory(browser);
  const dialog = fakeDialog();
  dialogs.attach(dialog);
  browser.gesture();
  await browser.settle();
  await browser.settle();
  assert.equal(dialog.open, false);
  assert.equal(dialog.closed, 1);
  assert.equal(browser.depth(), 0);
});

test('a dialog that vetoes the close (unsaved changes) stays open, and the next gesture still works', async () => {
  const browser = fakeBrowser();
  const dialogs = createDialogHistory(browser);
  const dialog = fakeDialog();
  let veto = true;
  dialog.addEventListener('cancel', (event) => { if (veto) event.preventDefault(); });
  dialogs.attach(dialog);
  browser.gesture();
  await browser.settle();
  await browser.settle();
  assert.equal(dialog.open, true);
  assert.equal(browser.depth(), 1);              // der Eintrag ist wieder da: der Verlauf passt zum offenen Dialog
  veto = false;
  browser.gesture();
  await browser.settle();
  await browser.settle();
  assert.equal(dialog.open, false);
  assert.equal(browser.depth(), 0);
});

test('with nested dialogs a gesture closes only the topmost one', async () => {
  const browser = fakeBrowser();
  const dialogs = createDialogHistory(browser);
  const settings = fakeDialog();
  const edit = fakeDialog();
  dialogs.attach(settings);
  dialogs.attach(edit);
  assert.equal(browser.depth(), 2);
  browser.gesture();
  await browser.settle();
  await browser.settle();
  assert.deepEqual([settings.open, edit.open], [true, false]);
  assert.equal(browser.depth(), 1);
  browser.gesture();
  await browser.settle();
  await browser.settle();
  assert.deepEqual([settings.open, edit.open], [false, false]);
  assert.equal(browser.depth(), 0);
});

test('closing the lower dialog first keeps the count right: the other one is still closed by the gesture', async () => {
  const browser = fakeBrowser();
  const dialogs = createDialogHistory(browser);
  const lower = fakeDialog();
  const upper = fakeDialog();
  dialogs.attach(lower);
  dialogs.attach(upper);
  lower.close();
  await browser.settle();
  assert.equal(browser.depth(), 1);
  assert.equal(upper.open, true);
  browser.gesture();
  await browser.settle();
  await browser.settle();
  assert.equal(upper.open, false);
  assert.equal(browser.depth(), 0);
});

test('a gesture with no dialog open does nothing', async () => {
  const browser = fakeBrowser();
  createDialogHistory(browser);
  browser.history.pushState({}, '');            // z. B. ein Vorwärts-Eintrag aus einem früheren Dialog
  browser.gesture();
  await browser.settle();
  assert.equal(browser.depth(), 0);
});

test('closing the same dialog twice takes the entry away only once', async () => {
  const browser = fakeBrowser();
  const dialogs = createDialogHistory(browser);
  const a = fakeDialog();
  const b = fakeDialog();
  dialogs.attach(a);
  dialogs.attach(b);
  b.close();
  b.close();
  await browser.settle();
  assert.equal(browser.depth(), 1);
});

test('a self-made back that fires no popstate does not swallow a later real gesture', async () => {
  const browser = fakeBrowser();
  let clock = 0;
  const dialogs = createDialogHistory({ ...browser, now: () => clock });
  const first = fakeDialog();
  dialogs.attach(first);
  browser.history.back = () => {};              // der Verlauf reagiert nicht (kein popstate)
  first.close();
  await browser.settle();
  const second = fakeDialog();
  dialogs.attach(second);
  browser.history.back = browser.gesture;       // wieder normal
  clock = 5000;                                 // weit nach Ablauf
  browser.gesture();
  await browser.settle();
  await browser.settle();
  assert.equal(second.open, false);
});
