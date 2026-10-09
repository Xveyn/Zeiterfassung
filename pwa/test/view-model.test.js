// pwa/test/view-model.test.js
import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
  WEEKDAYS, blankRow, conflictsModel, editorRows, hintsModel, localTime, rowsToSlots, slotText,
  statusModel, validateRows, weekModel,
} from '../view-model.js';
import { SyncError } from '../sync.js';

const SLOT = { start: '08:00', end: '12:00', pause: 0, kategorie: 'Projekt' };
const days = (map) => (date) => map[date] ?? null;
const live = (slots, over = {}) => ({ slots, deleted: false, dirty: false, error: null, modified_at: 'x', ...over });

// --- Woche -----------------------------------------------------------------------------------------

test('a slot reads start–end, pause and category', () => {
  assert.equal(slotText(SLOT), '08:00–12:00 · Projekt');
  assert.equal(slotText({ start: '08:00', end: '16:30', pause: 30, kategorie: '' }), '08:00–16:30 · 30 min Pause');
  assert.equal(slotText({ start: '08:00', end: '12:00', pause: 15, kategorie: 'A' }), '08:00–12:00 · 15 min Pause · A');
  assert.equal(slotText({ start: '08:00', end: '12:00', pause: 'x', kategorie: 5 }), '08:00–12:00');
});

test('the week model lists Monday to Sunday with German dates and the ISO week', () => {
  const week = weekModel({ getDay: days({}), anchor: '2026-10-08', today: '2026-10-08' });
  assert.equal(week.title, 'KW 41');
  assert.equal(week.range, '05.10.–11.10.2026');
  assert.equal(week.anchor, '2026-10-05');
  assert.equal(week.isCurrent, true);
  assert.deepEqual(week.days.map((d) => d.weekday), WEEKDAYS);
  assert.deepEqual(week.days.map((d) => d.date), [
    '2026-10-05', '2026-10-06', '2026-10-07', '2026-10-08', '2026-10-09', '2026-10-10', '2026-10-11']);
  assert.equal(week.days[3].isToday, true);
  assert.deepEqual(week.days.map((d) => d.isWeekend), [false, false, false, false, false, true, true]);
  assert.equal(week.days[3].label, '08.10.2026');
});

test('a week that does not contain today is not current', () => {
  assert.equal(weekModel({ getDay: days({}), anchor: '2026-09-30', today: '2026-10-08' }).isCurrent, false);
});

test('sums are whole minutes per day and for the week', () => {
  const getDay = days({
    '2026-10-05': live([{ start: '08:00', end: '10:20', pause: 0, kategorie: '' }, { start: '10:30', end: '12:07', pause: 0, kategorie: '' }]),
    '2026-10-06': live([{ start: '09:00', end: '17:30', pause: 30, kategorie: '' }]),
  });
  const week = weekModel({ getDay, anchor: '2026-10-05', today: '2026-10-08' });
  assert.equal(week.days[0].minutes, 140 + 97);
  assert.equal(week.days[0].minutesLabel, '3:57');
  assert.equal(week.days[1].minutesLabel, '8:00');
  assert.equal(week.totalMinutes, 237 + 480);
  assert.equal(week.totalLabel, '11:57');
  assert.equal(week.days[2].minutesLabel, '');
});

test('day states: empty, filled, cleared; flags for pending, error and conflict', () => {
  const getDay = days({
    '2026-10-05': live([SLOT], { dirty: true }),
    '2026-10-06': live([], { deleted: true }),
    '2026-10-07': live([SLOT], { error: 'abgelehnt' }),
  });
  const week = weekModel({ getDay, anchor: '2026-10-05', today: '2026-10-08', conflictDates: ['2026-10-07'] });
  assert.deepEqual(week.days.slice(0, 4).map((d) => d.state), ['filled', 'cleared', 'filled', 'empty']);
  assert.equal(week.days[0].dirty, true);
  assert.equal(week.days[1].minutes, 0);
  assert.equal(week.days[2].error, 'abgelehnt');
  assert.equal(week.days[2].conflict, true);
  assert.equal(week.days[0].conflict, false);
});

test('days after tomorrow are marked as beyond the window', () => {
  const week = weekModel({ getDay: days({}), anchor: '2026-10-08', today: '2026-10-08' });
  assert.deepEqual(week.days.map((d) => d.beyondWindow), [false, false, false, false, false, true, true]);
});

test('the sum ignores broken stored slots instead of throwing', () => {
  const getDay = days({ '2026-10-05': live([{ start: 'x', end: null, pause: 'a' }, SLOT]) });
  assert.equal(weekModel({ getDay, anchor: '2026-10-05', today: '2026-10-05' }).totalMinutes, 240);
});

// --- Status ----------------------------------------------------------------------------------------

test('the local time is shown in the given zone', () => {
  assert.equal(localTime('2026-10-08T12:34:56Z', 'UTC'), '12:34');
  assert.equal(localTime('2026-10-08T12:34:56Z', 'Europe/Berlin'), '14:34');
  assert.equal(localTime('kaputt', 'UTC'), '');
});

test('the status line says online, pending changes and the last sync', () => {
  const status = statusModel({ paired: true, online: true, syncing: false, pending: 3,
    lastSyncAt: '2026-10-08T12:34:00Z', timeZone: 'UTC' });
  assert.equal(status.connection, 'Online');
  assert.equal(status.pendingText, '3 Änderungen nicht übertragen');
  assert.equal(status.lastText, 'zuletzt abgeglichen um 12:34');
  assert.equal(status.canSync, true);
});

test('status line variants', () => {
  const base = { paired: true, online: true, syncing: false, pending: 0, lastSyncAt: '', timeZone: 'UTC' };
  assert.equal(statusModel({ ...base, pending: 1 }).pendingText, '1 Änderung nicht übertragen');
  assert.equal(statusModel(base).pendingText, '');
  assert.equal(statusModel(base).lastText, 'noch nicht abgeglichen');
  assert.equal(statusModel({ ...base, online: false }).connection, 'Offline');
  assert.equal(statusModel({ ...base, syncing: true }).connection, 'Gleiche ab …');
  assert.equal(statusModel({ ...base, syncing: true }).canSync, false);
  assert.equal(statusModel({ ...base, paired: false }).connection, 'Nicht gekoppelt');
  assert.equal(statusModel({ ...base, paired: false }).canSync, false);
});

// --- Hinweise --------------------------------------------------------------------------------------

const none = { lastError: null, excluded: false, skewMs: 0, persistent: true, updateReady: false, conflictCount: 0, errorDays: 0 };

test('no hints when everything is fine', () => {
  assert.deepEqual(hintsModel(none), []);
});

test('each situation gets its hint and way out', () => {
  const ids = (over) => hintsModel({ ...none, ...over }).map((hint) => hint.id);
  assert.deepEqual(ids({ lastError: new SyncError({ kind: 'offline' }) }), ['error']);
  assert.deepEqual(ids({ excluded: true }), ['excluded']);
  assert.deepEqual(ids({ skewMs: 180000 }), ['skew']);
  assert.deepEqual(ids({ skewMs: -180000 }), ['skew']);
  assert.deepEqual(ids({ skewMs: 60000 }), []);
  assert.deepEqual(ids({ persistent: false }), ['storage']);
  assert.deepEqual(ids({ persistent: null }), []);                  // noch nicht gefragt
  assert.deepEqual(ids({ updateReady: true }), ['update']);
  assert.deepEqual(ids({ conflictCount: 2 }), ['conflicts']);
  assert.deepEqual(ids({ errorDays: 1 }), ['rejected']);
});

test('hint texts and actions', () => {
  const find = (over, id) => hintsModel({ ...none, ...over }).find((hint) => hint.id === id);
  assert.equal(find({ lastError: new SyncError({ kind: 'repair', code: 'token_expired' }) }, 'error').action, 'pair');
  assert.equal(find({ lastError: new SyncError({ kind: 'offline' }) }, 'error').action, 'rescan');
  assert.match(find({ excluded: true }, 'excluded').text, /Am Desktop gelöschte Einträge bleiben gelöscht/);
  assert.match(find({ skewMs: 180000 }, 'skew').text, /3 Minuten/);
  assert.match(find({ persistent: false }, 'storage').text, /dauerhaft/);
  assert.equal(find({ updateReady: true }, 'update').action, 'reload');
  assert.equal(find({ conflictCount: 1 }, 'conflicts').text, '1 Konflikt: am Desktop lösen.');
  assert.equal(find({ conflictCount: 3 }, 'conflicts').text, '3 Konflikte: am Desktop lösen.');
  assert.equal(find({ conflictCount: 3 }, 'conflicts').action, 'conflicts');
  assert.equal(find({ errorDays: 2 }, 'rejected').text, '2 Tage wurden vom Desktop abgelehnt — bitte prüfen.');
});

test('an error hint comes first', () => {
  const hints = hintsModel({ ...none, lastError: new SyncError({ kind: 'offline' }), conflictCount: 1, updateReady: true });
  assert.equal(hints[0].id, 'error');
});

// --- Konflikte -------------------------------------------------------------------------------------

test('a conflict shows both versions read-only with names, times and sums', () => {
  const conflicts = [{ id: 'c1', date: '2026-10-05', versions: [
    { device: '6f1c2b9e-3d4a-4b5c', name: 'Pixel von Sven', modified_at: '2026-10-07T18:30:00Z', slots: [SLOT] },
    { device: 'DESKTOP-ABCDEF', name: '', modified_at: '2026-10-07T20:00:00Z',
      slots: [{ start: '09:00', end: '13:00', pause: 0, kategorie: '' }] },
  ] }];
  const [model] = conflictsModel(conflicts, 'UTC');
  assert.equal(model.id, 'c1');
  assert.equal(model.dateLabel, '05.10.2026');
  assert.equal(model.versions[0].who, 'Pixel von Sven');
  assert.equal(model.versions[1].who, 'DESKTOP-');                  // ohne Namen: gekürzte ID
  assert.equal(model.versions[0].when, '07.10.2026 18:30');
  assert.deepEqual(model.versions[0].slots, ['08:00–12:00 · Projekt']);
  assert.equal(model.versions[0].minutesLabel, '4:00');
});

test('a conflict with a deleted version says so', () => {
  const [model] = conflictsModel([{ id: 'c', date: '2026-10-05', versions: [
    { device: 'A', name: 'A', modified_at: '2026-10-07T18:30:00Z', slots: [] }] }], 'UTC');
  assert.deepEqual(model.versions[0].slots, []);
  assert.equal(model.versions[0].minutesLabel, '0:00');
});

test('conflicts are sorted by date and junk is skipped', () => {
  const models = conflictsModel([
    { id: 'b', date: '2026-10-06', versions: [] }, null, 'x', { id: 'a', date: '2026-10-05', versions: 'x' },
  ], 'UTC');
  assert.deepEqual(models.map((m) => m.id), ['a', 'b']);
});

// --- Editor ----------------------------------------------------------------------------------------

test('the editor starts from the stored slots or from one blank row', () => {
  assert.deepEqual(editorRows(null), [blankRow()]);
  assert.deepEqual(editorRows(live([], { deleted: true })), [blankRow()]);
  assert.deepEqual(editorRows(live([{ start: '08:00', end: '12:00', pause: 15, kategorie: 'A' }])),
    [{ start: '08:00', end: '12:00', pause: '15', kategorie: 'A' }]);
});

test('a new row continues after the previous one', () => {
  assert.deepEqual(blankRow(), { start: '', end: '', pause: '0', kategorie: '' });
  assert.deepEqual(blankRow({ start: '08:00', end: '12:00', pause: '0', kategorie: 'A' }),
    { start: '12:00', end: '', pause: '0', kategorie: 'A' });
  assert.deepEqual(blankRow({ start: '08:00', end: '', pause: '0', kategorie: '' }),
    { start: '', end: '', pause: '0', kategorie: '' });
});

test('rows become wire slots; blank rows are dropped', () => {
  const rows = [
    { start: '08:00', end: '12:00', pause: '15', kategorie: ' Projekt ' },
    { start: '', end: '', pause: '0', kategorie: '' },
    { start: '13:00', end: '17:00', pause: '', kategorie: '' },
  ];
  assert.deepEqual(rowsToSlots(rows), [
    { start: '08:00', end: '12:00', pause: 15, kategorie: ' Projekt ' },
    { start: '13:00', end: '17:00', pause: 0, kategorie: '' },
  ]);
});

test('validation uses the same rules as the server and speaks German', () => {
  const ok = [{ start: '08:00', end: '12:00', pause: '0', kategorie: 'A' }];
  assert.deepEqual(validateRows(ok), { ok: true, message: '' });
  assert.equal(validateRows([blankRow()]).ok, false);
  assert.match(validateRows([blankRow()]).message, /Mindestens ein Slot/);
  assert.equal(validateRows([{ ...ok[0], end: '07:00' }]).message, 'Endzeit muss nach Startzeit liegen');
  assert.equal(validateRows([{ ...ok[0], start: '' }]).message, 'Startzeit ungültig (Format: HH:MM)');
  assert.equal(validateRows([{ ...ok[0], pause: '1.5' }]).ok, false);
  assert.equal(validateRows([{ ...ok[0], pause: 'abc' }]).ok, false);
  assert.equal(validateRows([{ ...ok[0], pause: '240' }]).ok, false);
  assert.equal(validateRows([ok[0], { start: '11:00', end: '13:00', pause: '0', kategorie: '' }]).message,
    'Zeitslots dürfen sich zeitlich nicht überlappen.');
  assert.equal(validateRows([{ ...ok[0], kategorie: 'x'.repeat(101) }]).ok, false);
});
