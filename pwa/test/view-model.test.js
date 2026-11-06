// pwa/test/view-model.test.js
import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
  SETTINGS_TABS, categoriesModel, categoryRemovalText, categoryRenameHint, settingsTabLabel,
  WEEKDAYS, categoryDisplay, categoryLabel, categoryOptions, conflictsModel, dayChanged, editLock, editorRows, focusKeyToRestore, hintKey, hintsModel, desktopHint, localTime, nextRow, olderModel, pickCategory, rowsToSlots, slotText,
  statusModel, validateRows, weekModel, windowRow, reservationRows, reservationRowsToSlots, validateReservationRows,
} from '../view-model.js';
import { SyncError } from '../sync.js';
import { formatMinutes } from '../minutes.js';

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

test('day states: empty, filled; a cleared day looks empty; flags for pending, error and conflict', () => {
  const getDay = days({
    '2026-10-05': live([SLOT], { dirty: true }),
    '2026-10-06': live([], { deleted: true }),
    '2026-10-07': live([SLOT], { error: 'abgelehnt' }),
  });
  const week = weekModel({ getDay, anchor: '2026-10-05', today: '2026-10-08', conflictDates: ['2026-10-07'] });
  assert.deepEqual(week.days.slice(0, 4).map((d) => d.state), ['filled', 'empty', 'filled', 'empty']);
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

test('with a forward window the days inside it are shown like any other day (#265)', () => {
  const week = weekModel({ getDay: days({}), anchor: '2026-10-08', today: '2026-10-08', aheadDays: 14 });
  assert.deepEqual(week.days.map((d) => d.beyondWindow), [false, false, false, false, false, false, false]);
  assert.deepEqual(week.days.map((d) => d.outsideWindow), [false, false, false, false, false, false, false]);
  const far = weekModel({ getDay: days({}), anchor: '2026-10-19', today: '2026-10-08', aheadDays: 14 });
  assert.deepEqual(far.days.map((d) => d.beyondWindow), [false, false, false, false, true, true, true]);   // ab 23.10.
  assert.deepEqual(far.days.map((d) => d.outsideWindow), [false, false, false, false, true, true, true]);
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
  assert.deepEqual(ids({ skewMs: 119999 }), []);
  assert.deepEqual(ids({ skewMs: 120000 }), ['skew']);
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

const plain = ({ start, end, pause, kategorie }) => ({ start, end, pause, kategorie });

test('the editor starts from the stored slots or from one blank row', () => {
  assert.deepEqual(editorRows(null).map(plain), [{ start: '', end: '', pause: '0', kategorie: '' }]);
  assert.deepEqual(editorRows(live([], { deleted: true })).map(plain), [{ start: '', end: '', pause: '0', kategorie: '' }]);
  assert.deepEqual(editorRows(live([{ start: '08:00', end: '12:00', pause: 15, kategorie: 'A' }])),
    [{ start: '08:00', end: '12:00', pause: '15', kategorie: 'A' }]);
});

test('a new row continues after the previous one', () => {
  assert.deepEqual(plain(nextRow({ start: '08:00', end: '12:00', pause: '0', kategorie: 'A' })),
    { start: '12:00', end: '', pause: '0', kategorie: 'A' });
  assert.deepEqual(plain(nextRow({ start: '08:00', end: '', pause: '0', kategorie: '' })),
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
  assert.equal(validateRows([{ start: '', end: '', pause: '0', kategorie: '' }]).ok, false);
  assert.match(validateRows([{ start: '', end: '', pause: '0', kategorie: '' }]).message, /Mindestens ein Slot/);
  assert.equal(validateRows([{ ...ok[0], end: '07:00' }]).message, 'Endzeit muss nach Startzeit liegen');
  assert.equal(validateRows([{ ...ok[0], start: '' }]).message, 'Startzeit ungültig (Format: HH:MM)');
  assert.equal(validateRows([{ ...ok[0], pause: '1.5' }]).ok, false);
  assert.equal(validateRows([{ ...ok[0], pause: 'abc' }]).ok, false);
  assert.equal(validateRows([{ ...ok[0], pause: '240' }]).ok, false);
  assert.equal(validateRows([ok[0], { start: '11:00', end: '13:00', pause: '0', kategorie: '' }]).message,
    'Zeitslots dürfen sich zeitlich nicht überlappen.');
  assert.equal(validateRows([{ ...ok[0], kategorie: 'x'.repeat(101) }]).ok, false);
});

test('days outside the read window are marked, because saving there can replace desktop entries', () => {
  const week = weekModel({ getDay: days({}), anchor: '2026-07-06', today: '2026-10-08', windowDays: 90 });
  // Fenster: ab 2026-07-10 (heute − 90)
  assert.deepEqual(week.days.map((d) => d.outsideWindow), [true, true, true, true, false, false, false]);
  const current = weekModel({ getDay: days({}), anchor: '2026-10-08', today: '2026-10-08', windowDays: 90 });
  assert.deepEqual(current.days.map((d) => d.outsideWindow), [false, false, false, false, false, true, true]);
});

test('without a known window nothing is marked before it', () => {
  const week = weekModel({ getDay: days({}), anchor: '2026-01-05', today: '2026-10-08' });
  assert.equal(week.days.every((d) => d.outsideWindow === false), true);
});

// --- Kategorie-Auswahl -----------------------------------------------------------------------------

test('category options keep the server order and mark the current one', () => {
  assert.deepEqual(categoryOptions(['A', 'B'], 'B'), [{ name: 'A', active: false }, { name: 'B', active: true }]);
  assert.deepEqual(categoryOptions(['A', 'B'], ''), [{ name: 'A', active: false }, { name: 'B', active: false }]);
  assert.deepEqual(categoryOptions([], ''), []);
});

test('a current category the server does not list is appended, not lost', () => {
  assert.deepEqual(categoryOptions(['A'], 'Frei'), [{ name: 'A', active: false }, { name: 'Frei', active: true }]);
  assert.deepEqual(categoryOptions(['A'], 'a'), [{ name: 'A', active: false }, { name: 'a', active: true }]);
  assert.deepEqual(categoryOptions([], 'Frei'), [{ name: 'Frei', active: true }]);
});

test('the category button label names the category or invites to choose one', () => {
  assert.equal(categoryLabel('Projekt'), 'Projekt');
  assert.equal(categoryLabel(''), 'Wählen');
  assert.equal(categoryLabel(undefined), 'Wählen');
});

// --- Tag seit dem Öffnen des Editors geändert? ---------------------------------------------------------

test('a day is unchanged when nothing about its content differs', () => {
  assert.equal(dayChanged(null, null), false);
  assert.equal(dayChanged(live([SLOT]), live([SLOT])), false);
});

test('a pending flag turning off after an acknowledged sync is not a change', () => {
  assert.equal(dayChanged(live([SLOT], { dirty: true }), live([SLOT], { dirty: false })), false);
});

test('a newer modified_at, different slots or a deletion count as changed', () => {
  assert.equal(dayChanged(live([SLOT]), live([SLOT], { modified_at: 'y' })), true);
  assert.equal(dayChanged(live([SLOT]), live([{ ...SLOT, end: '13:00' }])), true);
  assert.equal(dayChanged(live([SLOT]), live([SLOT], { deleted: true })), true);
});

test('a day that appeared or vanished since opening counts as changed', () => {
  assert.equal(dayChanged(null, live([SLOT])), true);
  assert.equal(dayChanged(live([SLOT]), null), true);
});

// --- Hinweise: Identität -------------------------------------------------------------------------------

test('a hint keeps its key while id, text and action stay the same', () => {
  const hint = { id: 'error', kind: 'error', text: 'Offline', action: 'retry' };
  assert.equal(hintKey(hint), hintKey({ ...hint }));
  assert.notEqual(hintKey(hint), hintKey({ ...hint, text: 'Server nicht erreichbar' }));
  assert.notEqual(hintKey(hint), hintKey({ ...hint, action: null }));
  assert.notEqual(hintKey(hint), hintKey({ ...hint, id: 'other' }));
});

// --- Fokus über Renders hinweg -------------------------------------------------------------------------

test('focus inside the app is restored by its key', () => {
  assert.equal(focusKeyToRestore({ activeKey: 'sync', inRoot: true, isBody: false, last: 'x' }), 'sync');
});

test('focus lost to the body (element disabled or removed) falls back to the last key', () => {
  assert.equal(focusKeyToRestore({ activeKey: null, inRoot: false, isBody: true, last: 'sync' }), 'sync');
  assert.equal(focusKeyToRestore({ activeKey: null, inRoot: false, isBody: true, last: null }), null);
});

test('focus in a dialog or elsewhere is left alone and forgets the last key', () => {
  assert.equal(focusKeyToRestore({ activeKey: null, inRoot: false, isBody: false, last: 'sync' }), null);
  assert.equal(focusKeyToRestore({ activeKey: null, inRoot: true, isBody: false, last: 'sync' }), null);
});

// --- Vorbelegung (#288) --------------------------------------------------------------------------

const DEFAULTS = {
  pause: 30,
  weekdays: { mon: { start: '08:00', end: '16:00' }, fri: { start: '08:00', end: '13:00' } },
  category_times: { Büro: { start: '09:00', end: '17:00', pause: 45 } },
};

test('a new day starts with the weekday defaults', () => {
  const [row] = editorRows(null, DEFAULTS, 'fri');
  assert.deepEqual({ start: row.start, end: row.end, pause: row.pause, kategorie: row.kategorie },
    { start: '08:00', end: '13:00', pause: '30', kategorie: '' });
});

test('without defaults (older desktop) a new day stays blank as before', () => {
  const [row] = editorRows(null, null, 'mon');
  assert.deepEqual({ start: row.start, end: row.end, pause: row.pause }, { start: '', end: '', pause: '0' });
  assert.deepEqual(editorRows(null)[0].start, '');
});

test('a deleted or empty day is prefilled like a new one', () => {
  assert.equal(editorRows({ deleted: true, slots: [] }, DEFAULTS, 'mon')[0].end, '16:00');
  assert.equal(editorRows({ deleted: false, slots: [] }, DEFAULTS, 'mon')[0].end, '16:00');
});

test('saved slots are shown as they are', () => {
  const [row] = editorRows(live([SLOT]), DEFAULTS, 'mon');
  assert.deepEqual({ start: row.start, end: row.end, pause: row.pause }, { start: '08:00', end: '12:00', pause: '0' });
});

test('picking a category fills the fields that are still untouched', () => {
  const [row] = editorRows(null, DEFAULTS, 'mon');
  pickCategory(row, 'Büro', DEFAULTS, 'mon');
  assert.deepEqual({ start: row.start, end: row.end, pause: row.pause, kategorie: row.kategorie },
    { start: '09:00', end: '17:00', pause: '45', kategorie: 'Büro' });
});

test('picking a category keeps fields the user already changed', () => {
  const [row] = editorRows(null, DEFAULTS, 'mon');
  row.start = '07:30';
  pickCategory(row, 'Büro', DEFAULTS, 'mon');
  assert.equal(row.start, '07:30');
  assert.equal(row.end, '17:00');
});

test('a second pick applies again as long as the fields stayed on the applied values', () => {
  const [row] = editorRows(null, DEFAULTS, 'mon');
  pickCategory(row, 'Büro', DEFAULTS, 'mon');
  pickCategory(row, '', DEFAULTS, 'mon');
  assert.deepEqual({ start: row.start, end: row.end, pause: row.pause, kategorie: row.kategorie },
    { start: '08:00', end: '16:00', pause: '30', kategorie: '' });
});

test('a saved slot keeps its times when the category changes', () => {
  const [row] = editorRows(live([SLOT]), DEFAULTS, 'mon');
  pickCategory(row, 'Büro', DEFAULTS, 'mon');
  assert.deepEqual({ start: row.start, end: row.end, pause: row.pause, kategorie: row.kategorie },
    { start: '08:00', end: '12:00', pause: '0', kategorie: 'Büro' });
});

test('picking a category without defaults only sets the name', () => {
  const [row] = editorRows(null, null, 'mon');
  pickCategory(row, 'Büro', null, 'mon');
  assert.deepEqual({ start: row.start, end: row.end, pause: row.pause, kategorie: row.kategorie },
    { start: '', end: '', pause: '0', kategorie: 'Büro' });
});

test('an added slot keeps the previous end as start and only takes end and pause from the category', () => {
  const next = nextRow({ start: '08:00', end: '12:00', pause: '0', kategorie: '' });
  assert.deepEqual({ start: next.start, end: next.end, pause: next.pause }, { start: '12:00', end: '', pause: '0' });
  pickCategory(next, 'Büro', DEFAULTS, 'mon');
  assert.deepEqual({ start: next.start, end: next.end, pause: next.pause }, { start: '12:00', end: '17:00', pause: '45' });
});

test('rowsToSlots ignores the bookkeeping of a row', () => {
  const [row] = editorRows(null, DEFAULTS, 'mon');
  assert.deepEqual(Object.keys(rowsToSlots([row])[0]).sort(), ['end', 'kategorie', 'pause', 'start']);
});

// --- Hinweis bei älterem Desktop (#290) ----------------------------------------------------------

test('an old desktop is recognised by the missing desktop info after a sync', () => {
  const synced = { last_pull_at: '2026-10-08T12:00:00Z', desktop: { name: '', version: '', platform: '' }, defaults: null };
  assert.match(desktopHint(synced), /Desktop-App ist älter/);
  assert.equal(desktopHint({ ...synced, desktop: { name: 'PC', version: '1.25.0', platform: 'Linux' } }), '');
});

test('no hint before the first sync (nothing is known yet)', () => {
  assert.equal(desktopHint({ last_pull_at: '', desktop: { name: '', version: '', platform: '' }, defaults: null }), '');
  assert.equal(desktopHint({}), '');
});

// --- Ältere Zeiten (#250) ----------------------------------------------------------------------

test('nothing is shown while the week is inside the window', () => {
  assert.equal(olderModel({ kind: 'none' }), null);
});

test('the load notice names the step and offers the button', () => {
  const model = olderModel({ kind: 'load', wish: 180 });
  assert.match(model.text, /noch nicht geladen/);
  assert.equal(model.action, 'older');
  assert.equal(model.wish, 180);
  assert.match(model.buttonText, /180 Tage/);
});

test('capped, trimmed and old-desktop notices explain instead of offering a dead button', () => {
  const capped = olderModel({ kind: 'capped', days: 180 });
  assert.match(capped.text, /höchstens 180 Tage/);
  assert.match(capped.text, /Einstellungen → Mobil/);
  assert.equal(capped.action, null);
  // Bei 365 (Maximum der Desktop-Einstellung) gibt es nichts mehr einzustellen.
  const atMaximum = olderModel({ kind: 'capped', days: 365 });
  assert.equal(atMaximum.text, 'Mehr als 365 Tage gibt es nur am Desktop.');
  assert.doesNotMatch(atMaximum.text, /Einstellungen/);
  assert.equal(atMaximum.action, null);

  const trimmed = olderModel({ kind: 'trimmed', days: 120 });
  assert.match(trimmed.text, /wegen der Datenmenge nur 120 Tage/);
  assert.equal(trimmed.action, null);

  const old = olderModel({ kind: 'old_desktop' });
  assert.match(old.text, /Desktop-App aktualisieren/);
  assert.equal(old.action, null);
});

test('the connection row reads the window and offers a reset only when it is above the default', () => {
  assert.deepEqual(windowRow({ days: 90, max: 365, wish: 90 }), { text: '90 Tage (Desktop erlaubt bis 365)', canReset: false });
  assert.deepEqual(windowRow({ days: 180, max: 365, wish: 180 }), { text: '180 Tage (Desktop erlaubt bis 365)', canReset: true });
  assert.deepEqual(windowRow({ days: 90, max: null, wish: 90 }), { text: '90 Tage', canReset: false });
  assert.deepEqual(windowRow({ days: 120, max: 365, wish: 365 }),
    { text: '120 Tage (gewünscht 365, Desktop erlaubt bis 365)', canReset: true });
});

test('the connection row names the forward window when the desktop has one (#265)', () => {
  assert.equal(windowRow({ days: 90, max: 365, wish: 90, ahead: 14 }).text, '90 Tage (Desktop erlaubt bis 365), dazu 14 Tage voraus');
  assert.equal(windowRow({ days: 90, max: null, wish: 90, ahead: 14 }).text, '90 Tage, dazu 14 Tage voraus');
  assert.equal(windowRow({ days: 90, max: 365, wish: 90, ahead: null }).text, '90 Tage (Desktop erlaubt bis 365)');
  assert.equal(windowRow({ days: 90, max: 365, wish: 90, ahead: 0 }).text, '90 Tage (Desktop erlaubt bis 365)');
});

test('an unknown maximum asks for a sync first instead of blaming the desktop (#292)', () => {
  const model = olderModel({ kind: 'unknown' });
  assert.match(model.text, /abgleich/i);
  assert.doesNotMatch(model.text, /aktualisieren/);
  assert.equal(model.action, null);
});

// --- Reservierungen ---------------------------------------------------------------------------------

const RES_SLOT = { start: '09:00', end: '12:00', kategorie: 'Projekt' };
const reservations = (map) => (date) => map[date] ?? null;
const reserved = (slots, over = {}) => ({ slots, deleted: false, dirty: false, error: null, modified_at: 'x', ...over });

test('a reservation shows on today and future days when the feature is on, and not in the total', () => {
  const week = weekModel({
    getDay: days({ '2026-10-08': live([SLOT]) }), anchor: '2026-10-08', today: '2026-10-08',
    getReservation: reservations({ '2026-10-09': reserved([RES_SLOT], { dirty: true }) }), reservationsEnabled: true });

  assert.deepEqual(week.days[4].reservation.slots, ['09:00–12:00 · Projekt']);
  assert.equal(week.days[4].reservation.dirty, true);
  assert.equal(week.days[4].minutes, 0);
  assert.equal(week.totalMinutes, week.days[3].minutes);
});

const pendingWeek = (reservationMap, extra = {}) => weekModel({
  getDay: days(extra.days ?? {}), anchor: '2026-10-08', today: '2026-10-08',
  getReservation: reservations(reservationMap), reservationsEnabled: extra.enabled ?? true });

test('the week lists what is still pending from reservations, kept out of the total (#329)', () => {
  const week = pendingWeek({ '2026-10-09': reserved([RES_SLOT]), '2026-10-10': reserved([RES_SLOT, { start: '13:00', end: '14:30' }]) });
  assert.equal(week.pendingMinutes, 3 * 60 + 4.5 * 60);
  assert.equal(week.pendingLabel, '7:30');
  assert.equal(week.totalMinutes, 0);
});

test('nothing pending means no pending figure (#329)', () => {
  assert.equal(pendingWeek({}).pendingMinutes, 0);
  assert.equal(pendingWeek({ '2026-10-09': reserved([RES_SLOT]) }, { enabled: false }).pendingMinutes, 0);
  assert.equal(pendingWeek({ '2026-10-07': reserved([RES_SLOT]) }).pendingMinutes, 0);        // gestern
  assert.equal(pendingWeek({ '2026-10-09': reserved([], { deleted: true }) }).pendingMinutes, 0);
});

test('today only a reservation slot without matching actual time is pending (#329)', () => {
  const afternoon = { start: '13:00', end: '17:00', kategorie: 'Projekt' };
  const reservation = { '2026-10-08': reserved([RES_SLOT, afternoon]) };
  // Vormittag schon erfasst (leicht abweichend): nur der Nachmittag steht noch aus.
  const partly = pendingWeek(reservation, { days: { '2026-10-08': live([{ start: '09:05', end: '11:50', pause: 0, kategorie: 'Projekt' }]) } });
  assert.equal(partly.pendingMinutes, 4 * 60);
  assert.equal(pendingWeek(reservation).pendingMinutes, 7 * 60);
  // An einem künftigen Tag zählt Ist-Zeit nie.
  assert.equal(pendingWeek({ '2026-10-09': reserved([RES_SLOT]) },
    { days: { '2026-10-09': live([SLOT]) } }).pendingMinutes, 3 * 60);
});

test('reservations are hidden when the feature is off or the day is in the past', () => {
  const get = reservations({ '2026-10-07': reserved([RES_SLOT]), '2026-10-09': reserved([RES_SLOT]) });
  const off = weekModel({ getDay: days({}), anchor: '2026-10-08', today: '2026-10-08', getReservation: get, reservationsEnabled: false });
  const on = weekModel({ getDay: days({}), anchor: '2026-10-08', today: '2026-10-08', getReservation: get, reservationsEnabled: true });

  assert.ok(off.days.every((d) => d.reservation === null && d.reservationVisible === false));
  assert.equal(on.days[2].reservation, null);              // gestern: nichts, auch keine vorhandene
  assert.equal(on.days[2].reservationVisible, false);
  assert.notEqual(on.days[4].reservation, null);
  assert.equal(on.days[3].reservationVisible, true);       // heute
});

test('a cleared reservation is not shown', () => {
  const week = weekModel({ getDay: days({}), anchor: '2026-10-08', today: '2026-10-08',
    getReservation: reservations({ '2026-10-09': reserved([], { deleted: true }) }), reservationsEnabled: true });
  assert.equal(week.days[4].reservation, null);
});

const PAUSE_DEFAULTS = { pause: 30, weekdays: { fr: { start: '09:00', end: '17:00' } }, category_times: {} };

test('new reservation rows carry the default pause only with the flag, and nothing is stored without it', () => {
  const on = reservationRows(null, PAUSE_DEFAULTS, 'fr', { pauseEnabled: true });
  assert.equal(on[0].pause, '30');
  assert.deepEqual(reservationRowsToSlots(on, { pauseEnabled: true }),
    [{ start: '09:00', end: '17:00', kategorie: '', pause: 30 }]);
  const off = reservationRows(null, PAUSE_DEFAULTS, 'fr');
  assert.equal(off[0].pause, '0');
  assert.deepEqual(reservationRowsToSlots(off), [{ start: '09:00', end: '17:00', kategorie: '' }]);
  // Auch eine von Hand befüllte Pause geht ohne Flag nie in den Slot.
  assert.deepEqual(Object.keys(reservationRowsToSlots(on)[0]).sort(), ['end', 'kategorie', 'start']);
});

test('saved reservation rows show their slots and a blank new row is dropped', () => {
  const rows = reservationRows(reserved([RES_SLOT]), null, 'mo');
  assert.deepEqual(reservationRowsToSlots(rows), [RES_SLOT]);
  const added = [...rows, { start: '', end: '', pause: '0', kategorie: '' }];
  assert.deepEqual(reservationRowsToSlots(added), [RES_SLOT]);
  assert.equal(validateReservationRows(added).ok, true);
});

test('reservation pause rows: empty and zero become 0, text input never yields NaN', () => {
  const row = (pause) => ({ start: '09:00', end: '12:00', pause, kategorie: '' });
  const pauseOf = (pause) => reservationRowsToSlots([row(pause)], { pauseEnabled: true })[0].pause;
  assert.equal(pauseOf(''), 0);
  assert.equal(pauseOf('0'), 0);
  assert.equal(pauseOf('30'), 30);
  assert.equal(pauseOf('  '), 0);
});

test('an invalid reservation pause errors like the Ist tab instead of becoming 0', () => {
  const rows = (pause) => [{ start: '09:00', end: '12:00', pause, kategorie: '' }];
  for (const pause of ['-30', '12.5', 'abc']) {
    const res = validateReservationRows(rows(pause), { pauseEnabled: true });
    assert.equal(res.ok, false, pause);
    assert.equal(res.message, validateRows(rows(pause)).message, pause);
  }
  assert.equal(validateReservationRows(rows(''), { pauseEnabled: true }).ok, true);
  assert.equal(validateReservationRows(rows('-30')).ok, true);       // ohne Flag zählt die Pause nicht
});

test('a stray pause validates without the flag, and with it must be shorter than the span', () => {
  const rows = [{ start: '09:00', end: '10:00', pause: '30', kategorie: '' }];
  assert.equal(validateReservationRows(rows).ok, true);
  assert.equal(validateReservationRows(rows, { pauseEnabled: true }).ok, true);
  const long = [{ start: '09:00', end: '10:00', pause: '60', kategorie: '' }];
  const bad = validateReservationRows(long, { pauseEnabled: true });
  assert.equal(bad.ok, false);
  assert.equal(bad.message, validateRows(long).message);
});

test('slotText names the pause of a reservation slot like an actual slot', () => {
  assert.equal(slotText({ start: '08:00', end: '15:30', kategorie: 'Projekt', pause: 30 }), '08:00–15:30 · 30 min Pause · Projekt');
  assert.equal(slotText({ start: '08:00', end: '15:30', kategorie: 'Projekt', pause: 0 }), '08:00–15:30 · Projekt');
  assert.equal(slotText({ start: '08:00', end: '15:30', kategorie: 'Projekt' }), '08:00–15:30 · Projekt');
});

test('the actual-time suggestion takes the reservation pause, or the default for older reservations', () => {
  const pauseOfSuggestion = (slot) => editorRows(null, PAUSE_DEFAULTS, 'fr', reserved([slot]))[0].pause;
  assert.equal(pauseOfSuggestion({ start: '08:00', end: '15:30', kategorie: '', pause: 45 }), '45');
  assert.equal(pauseOfSuggestion({ start: '08:00', end: '15:30', kategorie: '', pause: 0 }), '30');
  assert.equal(pauseOfSuggestion({ start: '08:00', end: '15:30', kategorie: '' }), '30');
  const row = editorRows(null, PAUSE_DEFAULTS, 'fr', reserved([{ start: '08:00', end: '15:30', kategorie: '', pause: 45 }]))[0];
  assert.equal(row.base.pause, '45');
});

test('the week nets the pause of reservations in "Noch ausstehend"', () => {
  const slot = (end) => ({ start: '08:00', end, kategorie: 'Projekt', pause: 30 });
  const week = pendingWeek({ '2026-10-09': reserved([slot('15:30')]), '2026-10-10': reserved([slot('15:30')]),
    '2026-10-11': reserved([slot('14:30')]) });
  assert.equal(week.pendingMinutes, 1200);
  assert.equal(week.pendingLabel, formatMinutes(1200));
});

// --- Einstellungen / Kategorien -----------------------------------------------------------------------

test('the settings tabs are connection, categories, updates, in that order, with German labels', () => {
  assert.deepEqual(SETTINGS_TABS, ['connection', 'categories', 'updates']);
  assert.deepEqual(SETTINGS_TABS.map(settingsTabLabel), ['Verbindung', 'Kategorien', 'Updates']);
});

test('the categories model lists rows with a summary and is editable with a writable desktop', () => {
  const model = categoriesModel({ categories: ['Projekt', 'Support'], writable: true,
    defaults: { category_times: { Projekt: { start: '09:00', end: '17:00', pause: 45 },
      Support: { mode: 'per_day', days: {} } } }, edit: null });

  assert.equal(model.editable, true);
  assert.deepEqual(model.rows.map((r) => r.summary), ['09:00–17:00, 45 min Pause', 'pro Wochentag']);
  assert.equal(model.hint, '');
  assert.equal(model.dirty, false);
});

test('an older desktop leaves the list readable but not editable, with a hint', () => {
  const model = categoriesModel({ categories: ['A'], writable: false, defaults: { category_times: {} }, edit: null });
  assert.equal(model.editable, false);
  assert.match(model.hint, /Desktop-App/);
  assert.equal(model.rows.length, 1);
});

test('without any defaults the list is still readable', () => {
  const model = categoriesModel({ categories: ['A'], writable: true, defaults: null, edit: null });
  assert.equal(model.editable, false);
  assert.equal(model.rows[0].summary, '—');
});

test('a writable desktop without defaults yet asks for a sync instead of blaming an older desktop', () => {
  const model = categoriesModel({ categories: ['A'], writable: true, defaults: null, edit: null });
  assert.equal(model.editable, false);
  assert.equal(model.hint, 'Die Kategorien sind noch nicht abgeglichen. Bitte erst abgleichen.');
  assert.doesNotMatch(model.hint, /älter/);
});

test('the model reports a dirty and a rejected block', () => {
  const model = categoriesModel({ categories: ['A'], writable: true, defaults: { category_times: {} },
    edit: { modified_at: 'x', dirty_version: 2, synced_version: 1, error: 'Einstellung categories: zu viele' } });
  assert.equal(model.dirty, true);
  assert.equal(model.error, 'Einstellung categories: zu viele');
});

test('removing and renaming say that existing entries keep the old name', () => {
  assert.match(categoryRemovalText('Projekt'), /Projekt/);
  assert.match(categoryRemovalText('Projekt'), /behalten/);
  assert.match(categoryRenameHint, /alten Namen/);
});

// --- Benachrichtigungen (#331) -------------------------------------------------------------------

import { pushModel } from '../view-model.js';

test('the push model offers enabling when off and disabling when on', () => {
  assert.deepEqual(pushModel({ state: 'off', lastError: null, desktopReady: true }).action, 'enable');
  assert.equal(pushModel({ state: 'off', lastError: null, desktopReady: true }).actionLabel, 'Benachrichtigungen erlauben');
  assert.equal(pushModel({ state: 'on', lastError: null, desktopReady: true }).action, 'disable');
  assert.equal(pushModel({ state: 'on', lastError: null, desktopReady: true }).actionLabel, 'Ausschalten');
});

test('a denied or unsupported browser offers no button', () => {
  for (const state of ['denied', 'unsupported']) {
    const model = pushModel({ state, lastError: null, desktopReady: true });
    assert.equal(model.action, null);
    assert.equal(model.actionLabel, '');
  }
});

test('a relay error is shown with the state', () => {
  assert.match(pushModel({ state: 'on', lastError: 'Der Relay ist nicht erreichbar.', desktopReady: true }).text, /nicht erreichbar/);
});

test('switched on but the desktop sends no reminders yet: the text says what is missing', () => {
  const model = pushModel({ state: 'on', lastError: null, desktopReady: false });
  assert.match(model.text, /Desktop/);
  assert.doesNotMatch(pushModel({ state: 'on', lastError: null, desktopReady: true }).text, /Desktop-App/);
});

test('the push model offers the test only when on and the secret exists', () => {
  assert.equal(pushModel({ state: 'on', lastError: null, desktopReady: true, canTest: true }).canTest, true);
  assert.equal(pushModel({ state: 'on', lastError: null, desktopReady: true, canTest: false }).canTest, false);
  for (const state of ['off', 'denied', 'unsupported', 'needs_resubscribe']) {
    assert.equal(pushModel({ state, lastError: null, desktopReady: true, canTest: true }).canTest, false, state);
  }
});

// --- Vorschlag aus der Reservierung und Override-Sternchen (#376) ---------------------------------

const plain3 = (row) => ({ start: row.start, end: row.end, pause: row.pause, kategorie: row.kategorie });
const resv = (slots, over = {}) => ({ slots, deleted: false, dirty: false, error: null, modified_at: 'x', ...over });

test('a day with a reservation but no actual time suggests its first slot, category included', () => {
  const [row] = editorRows(null, DEFAULTS, 'mon', resv([{ start: '10:00', end: '14:00', kategorie: 'Büro' }]));
  assert.deepEqual(plain3(row), { start: '10:00', end: '14:00', pause: '30', kategorie: 'Büro' });
});

test('with several reservation slots the times come from the first, the category stays open', () => {
  const [row] = editorRows(null, DEFAULTS, 'mon', resv([
    { start: '10:00', end: '12:00', kategorie: 'Büro' }, { start: '13:00', end: '15:00', kategorie: 'Büro' }]));
  assert.deepEqual(plain3(row), { start: '10:00', end: '12:00', pause: '30', kategorie: '' });
});

test('the suggestion keeps a blank category and works without defaults', () => {
  const [row] = editorRows(null, null, 'mon', resv([{ start: '10:00', end: '14:00', kategorie: '' }]));
  assert.deepEqual(plain3(row), { start: '10:00', end: '14:00', pause: '0', kategorie: '' });
});

test('a deleted or empty reservation suggests nothing', () => {
  assert.equal(editorRows(null, DEFAULTS, 'mon', resv([{ start: '10:00', end: '14:00', kategorie: 'Büro' }], { deleted: true }))[0].start, '08:00');
  assert.equal(editorRows(null, DEFAULTS, 'mon', resv([]))[0].start, '08:00');
});

test('saved actual time wins over the reservation and stays untouched', () => {
  const rows = editorRows(live([SLOT]), DEFAULTS, 'mon', resv([{ start: '10:00', end: '14:00', kategorie: 'Büro' }]));
  assert.deepEqual(rows.map(plain3), [{ start: '08:00', end: '12:00', pause: '0', kategorie: 'Projekt' }]);
  assert.equal(rows[0].base, undefined);
});

test('a suggested row still takes the defaults of a newly picked category', () => {
  const [row] = editorRows(null, DEFAULTS, 'mon', resv([{ start: '10:00', end: '14:00', kategorie: 'Büro' }]));
  pickCategory(row, 'Büro', DEFAULTS, 'mon');
  assert.deepEqual(plain3(row), { start: '09:00', end: '17:00', pause: '45', kategorie: 'Büro' });
});

test('the category label carries a star when times differ from the category defaults', () => {
  const row = { start: '09:00', end: '17:00', pause: '45', kategorie: 'Büro' };
  assert.equal(categoryDisplay(row, DEFAULTS, 'mon', true), 'Büro');
  assert.equal(categoryDisplay({ ...row, start: '09:30' }, DEFAULTS, 'mon', true), 'Büro*');
  assert.equal(categoryDisplay({ ...row, end: '18:00' }, DEFAULTS, 'mon', true), 'Büro*');
  assert.equal(categoryDisplay({ ...row, pause: '30' }, DEFAULTS, 'mon', true), 'Büro*');
});

test('the pause only counts for actual time, not for reservations', () => {
  const row = { start: '09:00', end: '17:00', pause: '0', kategorie: 'Büro' };
  assert.equal(categoryDisplay(row, DEFAULTS, 'mon', false), 'Büro');
});

test('no category reads Wählen, and without defaults there is never a star', () => {
  assert.equal(categoryDisplay({ start: '08:00', end: '16:00', pause: '30', kategorie: '' }, DEFAULTS, 'mon', true), 'Wählen');
  assert.equal(categoryDisplay({ start: '01:00', end: '02:00', pause: '0', kategorie: 'Büro' }, null, 'mon', true), 'Büro');
});

test('a category unknown to the defaults compares against the weekday defaults', () => {
  const row = { start: '08:00', end: '16:00', pause: '30', kategorie: 'Frei' };
  assert.equal(categoryDisplay(row, DEFAULTS, 'mon', true), 'Frei');
  assert.equal(categoryDisplay({ ...row, end: '15:00' }, DEFAULTS, 'mon', true), 'Frei*');
});

// --- Bearbeiten außerhalb des Fensters (#273) ------------------------------------------------------------

const LOCK_TODAY = '2026-10-08';
const lockMeta = (over = {}) => ({ window_days: 90, window_ahead: 14, window_max: 365, window_max_known: true,
  window_wish_acked: 90, ...over });
const lock = (date, over = {}, hasRecord = false) => editLock({ date, today: LOCK_TODAY, meta: lockMeta(over), hasRecord });

test('a day inside the window, including both edges, is editable', () => {
  assert.equal(lock('2026-10-08'), null);
  assert.equal(lock('2026-07-10'), null);                 // heute − 90
  assert.equal(lock('2026-10-22'), null);                 // heute + 14
});

test('a day before the window is locked with the way out: load older times (#273)', () => {
  const model = lock('2026-07-09');                       // heute − 91
  assert.equal(model.kind, 'older');
  assert.equal(model.action, 'older');
  assert.equal(model.wish, 180);
  assert.equal(model.buttonText, 'Ältere Zeiten laden (bis 180 Tage)');
  assert.match(model.text, /lässt sich hier nicht bearbeiten/);
  assert.match(model.text, /nicht geladen/);
  assert.equal(lock('2026-01-01').wish, 365);             // 280 Tage zurück: die kleinste Stufe, die reicht
});

test('a day before the window the desktop will not deliver can only be edited there', () => {
  const capped = lock('2026-01-01', { window_days: 180, window_max: 180 });
  assert.equal(capped.action, null);
  assert.match(capped.text, /höchstens 180 Tage/);
  const atMaximum = lock('2025-01-01', { window_days: 365 });
  assert.equal(atMaximum.action, null);
  assert.match(atMaximum.text, /nur am Desktop/);
  const trimmed = lock('2026-04-01', { window_days: 120, window_wish_acked: 365 });
  assert.equal(trimmed.action, null);
  assert.match(trimmed.text, /wegen der Datenmenge nur 120 Tage/);
  const old = lock('2026-07-09', { window_max: null });
  assert.equal(old.action, null);
  assert.match(old.text, /Desktop-App aktualisieren/);
});

test('before the first sync the lock asks for a sync instead of blaming the desktop', () => {
  const model = lock('2026-07-09', { window_max_known: false, window_max: null });
  assert.equal(model.action, null);
  assert.match(model.text, /Abgleich/);
  assert.doesNotMatch(model.text, /aktualisieren/);
});

test('a day after the forward window is locked and names the limit (#265, #273)', () => {
  const model = lock('2026-10-23');                       // heute + 15
  assert.equal(model.kind, 'future');
  assert.equal(model.action, null);
  assert.match(model.text, /14 Tage im Voraus/);
  const older = lock('2026-10-10', { window_ahead: null });   // ältere Desktop: nur bis morgen
  assert.match(older.text, /1 Tag im Voraus/);
  assert.equal(lock('2026-10-09', { window_ahead: null }), null);
});

test('a day the phone already holds stays editable even outside the window', () => {
  assert.equal(lock('2026-05-01', {}, true), null);
  assert.equal(lock('2026-12-01', {}, true), null);
});

test('the error hint passes the browser and address on to the message (#275)', () => {
  const none = { lastError: new SyncError({ kind: 'offline' }), excluded: false, skewMs: 0, persistent: true,
    updateReady: false, conflictCount: 0, errorDays: 0 };
  const hint = hintsModel({ ...none, errorEnv: { browser: 'firefox', address: '192.168.178.20:17654' } }).find((h) => h.id === 'error');
  assert.match(hint.text, /vermutlich/);
  assert.match(hint.text, /192\.168\.178\.20:17654\/v1\/ping/);
  assert.match(hintsModel(none).find((h) => h.id === 'error').text, /nicht erreichbar/);
});

// --- Relay: Koppel-Seite und Verbindungsanzeige (#358) -----------------------------------------------

import { connectionLabel, pairFields } from '../view-model.js';

test('the pair page of a relay link has neither an address nor a code field', () => {
  assert.deepEqual(pairFields({ relay: true }), { address: false, code: false });
  assert.deepEqual(pairFields({ relay: false }), { address: true, code: true });
  assert.deepEqual(pairFields({}), { address: true, code: true });
});

test('connectionLabel names the way, never the secret', () => {
  const secret = 'S'.repeat(43);
  assert.equal(connectionLabel({ transport: 'relay', box_secret: secret, address: null }), 'Relay (über das Internet)');
  assert.equal(connectionLabel({ transport: 'lan', address: { host: '192.168.1.2', port: 17654 } }), '192.168.1.2:17654');
  assert.equal(connectionLabel({ address: { host: '192.168.1.2', port: 17654 } }), '192.168.1.2:17654');
  assert.equal(connectionLabel({ transport: 'lan', address: null }), '');
  assert.equal(connectionLabel({ transport: 'relay', box_secret: secret }).includes(secret), false);
});

// --- iOS: Installation auf den Home-Bildschirm (#358) -------------------------------------------------

import { iosInstallHint } from '../view-model.js';

test('iOS in a browser tab is told to install first, and why', () => {
  const text = iosInstallHint({ browser: 'ios', standalone: false });
  assert.match(text, /Home-Bildschirm/);
  assert.match(text, /sieben Tage/);
  assert.match(text, /koppeln/);
});

test('no install hint in the installed web app, on other browsers or when the mode is unknown', () => {
  assert.equal(iosInstallHint({ browser: 'ios', standalone: true }), '');
  for (const browser of ['chromium', 'firefox', 'safari', 'unknown', undefined]) {
    assert.equal(iosInstallHint({ browser, standalone: false }), '', String(browser));
  }
  assert.equal(iosInstallHint({ browser: 'ios' }), '');
  assert.equal(iosInstallHint(), '');
});

test('hintsModel carries the install hint as an info hint without action, only where it applies', () => {
  const none = { lastError: null, excluded: false, skewMs: 0, persistent: true, updateReady: false, conflictCount: 0, errorDays: 0 };
  const hint = hintsModel({ ...none, errorEnv: { browser: 'ios', standalone: false } }).find((item) => item.id === 'ios-install');
  assert.equal(hint.kind, 'info');
  assert.equal(hint.action, null);
  assert.match(hint.text, /Home-Bildschirm/);
  for (const env of [{ browser: 'ios', standalone: true }, { browser: 'chromium', standalone: false }, { browser: 'firefox', standalone: false }, {}]) {
    assert.equal(hintsModel({ ...none, errorEnv: env }).some((item) => item.id === 'ios-install'), false, JSON.stringify(env));
  }
});

test('the iOS install hint says to scan inside the installed app, not with the camera app', () => {
  const text = iosInstallHint({ browser: 'ios', standalone: false });
  assert.match(text, /QR-Code scannen/);
  assert.match(text, /Kamera-App/);
  assert.match(text, /nicht immer/);             // die Kamera-App geht (iPhone geprüft), je nach iOS aber nicht immer
  assert.doesNotMatch(text, /nicht mit der Kamera-App/);
});

test('today the planned line goes away once actual time with that category exists, whatever the time', () => {
  const week = pendingWeek({ '2026-10-08': reserved([RES_SLOT], { dirty: true }) },
    { days: { '2026-10-08': live([{ start: '13:00', end: '17:00', pause: 0, kategorie: 'Projekt' }]) } });
  const today = week.days[3];
  assert.deepEqual(today.reservation.slots, []);
  assert.equal(today.reservation.dirty, true);          // die Markierung „nicht übertragen“ bleibt
  assert.equal(today.pendingMinutes, 0);
  assert.equal(week.pendingMinutes, 0);
});

test('today the planned line stays for another category and for the slot nothing has completed', () => {
  const afternoon = { start: '13:00', end: '17:00', kategorie: 'Projekt' };
  const other = pendingWeek({ '2026-10-08': reserved([RES_SLOT]) },
    { days: { '2026-10-08': live([{ start: '09:00', end: '12:00', pause: 0, kategorie: 'Support' }]) } });
  assert.deepEqual(other.days[3].reservation.slots, ['09:00–12:00 · Projekt']);
  assert.equal(other.pendingMinutes, 3 * 60);
  const partly = pendingWeek({ '2026-10-08': reserved([RES_SLOT, afternoon]) },
    { days: { '2026-10-08': live([{ start: '15:00', end: '18:00', pause: 0, kategorie: 'Projekt' }]) } });
  assert.deepEqual(partly.days[3].reservation.slots, ['13:00–17:00 · Projekt']);
});

test('a future day keeps its planned line even with actual time of that category', () => {
  const week = pendingWeek({ '2026-10-09': reserved([RES_SLOT]) },
    { days: { '2026-10-09': live([{ start: '09:00', end: '12:00', pause: 0, kategorie: 'Projekt' }]) } });
  assert.deepEqual(week.days[4].reservation.slots, ['09:00–12:00 · Projekt']);
});

test('in the reservation tab (withPause false) the pause never sets the category asterisk', () => {
  const defaults = { pause: 0, weekdays: {}, category_times: { Projekt: { mode: 'general', start: '09:00', end: '12:00', pause: 30 } } };
  const row = (pause) => ({ start: '09:00', end: '12:00', pause, kategorie: 'Projekt' });
  assert.equal(categoryDisplay(row('0'), defaults, 'mo', false), 'Projekt');
  assert.equal(categoryDisplay(row('45'), defaults, 'mo', false), 'Projekt');
  assert.equal(categoryDisplay(row('0'), defaults, 'mo', true), 'Projekt*');
  assert.equal(categoryDisplay({ ...row('30'), start: '10:00' }, defaults, 'mo', false), 'Projekt*');
});

// --- Woche: Speicher-Hinweis schließbar, leere Tage laden ein (#461) -----------------------------

const DAY_MS_T = 86400000;

test('the storage hint can be dismissed and offers to ask the browser again', () => {
  const find = (over) => hintsModel({ ...none, persistent: false, now: 10 * DAY_MS_T, ...over }).find((hint) => hint.id === 'storage');
  const hint = find({});
  assert.equal(hint.dismissible, true);
  assert.equal(hint.action, 'persist');
  assert.equal(find({ dismissedAt: 10 * DAY_MS_T - DAY_MS_T }), undefined);                  // gestern geschlossen: bleibt weg
  assert.equal(find({ dismissedAt: 10 * DAY_MS_T - 7 * DAY_MS_T + 1 }), undefined);          // knapp unter 7 Tage
  assert.ok(find({ dismissedAt: 10 * DAY_MS_T - 7 * DAY_MS_T }));                            // nach 7 Tagen wieder da
  assert.ok(find({ dismissedAt: 11 * DAY_MS_T }));                                           // Uhr zurückgestellt: nie ewig verborgen
});

test('after the browser refuses, the storage hint says what helps instead of offering the same button', () => {
  const hint = hintsModel({ ...none, persistent: false, persistRefused: true }).find((item) => item.id === 'storage');
  assert.equal(hint.action, null);
  assert.equal(hint.dismissible, true);
  assert.match(hint.text, /abgelehnt/);
  assert.match(hint.text, /Startbildschirm/);
});

test('other hints are not dismissible', () => {
  const hints = hintsModel({ ...none, conflictCount: 1, excluded: true });
  assert.ok(hints.length > 0);
  assert.ok(hints.every((hint) => !hint.dismissible));
});

test('empty days invite to add something, only where adding is possible', () => {
  const week = (over = {}) => weekModel({ getDay: days({ '2026-10-08': live([SLOT]) }), anchor: '2026-10-08', today: '2026-10-08',
    windowDays: 90, ...over });
  const day = (model, date) => model.days.find((item) => item.date === date);
  assert.equal(day(week(), '2026-10-09').addHint, 'Eintragen');                              // leer, in der Zukunft, ohne Reservierungen
  assert.equal(day(week(), '2026-10-08').addHint, '');                                       // gefüllt
  assert.equal(day(week({ reservationsEnabled: true }), '2026-10-09').addHint, 'Eintragen oder planen');
  assert.equal(day(week({ reservationsEnabled: true }), '2026-10-06').addHint, 'Eintragen'); // vergangen: keine Reservierung möglich
  assert.equal(day(week({ windowDays: 2 }), '2026-10-05').addHint, '');                      // außerhalb des Fensters: gesperrt
  assert.equal(day(week({ aheadDays: 0 }), '2026-10-10').addHint, '');                       // hinter dem Vorschaufenster
});

test('a cleared day also invites, a day with only a reservation does not', () => {
  const cleared = weekModel({ getDay: days({ '2026-10-08': live([], { deleted: true }) }), anchor: '2026-10-08', today: '2026-10-08', windowDays: 90 });
  assert.equal(cleared.days.find((item) => item.date === '2026-10-08').addHint, 'Eintragen');
  const planned = weekModel({ getDay: days({}), anchor: '2026-10-08', today: '2026-10-07', windowDays: 90, reservationsEnabled: true,
    getReservation: (date) => (date === '2026-10-09' ? live([SLOT]) : null) });
  assert.equal(planned.days.find((item) => item.date === '2026-10-09').addHint, '');
});

// --- Editor: Netto, Feldfehler, Schnellwahl (#461) -------------------------------------------------

import { QUICK_END_MINUTES, QUICK_PAUSES, addToTime, dayNetMinutes, rowNetMinutes, rowProblems, editorTitle } from '../view-model.js';

test('the net minutes of a row are span minus pause, never negative, null while unusable', () => {
  assert.equal(rowNetMinutes({ start: '08:00', end: '16:00', pause: '30' }), 450);
  assert.equal(rowNetMinutes({ start: '08:00', end: '08:30', pause: '45' }), 0);
  assert.equal(rowNetMinutes({ start: '08:00', end: '', pause: '0' }), null);
  assert.equal(rowNetMinutes({ start: '08:00', end: '09:00', pause: 'x' }), 60);
});

test('the day total sums whole minutes of the usable rows, and ignores the pause without the flag', () => {
  const rows = [{ start: '08:00', end: '12:00', pause: '0' }, { start: '12:30', end: '17:00', pause: '30' }, { start: '17:00', end: '', pause: '0' }];
  assert.equal(dayNetMinutes(rows), 240 + 240);
  assert.equal(dayNetMinutes(rows, { withPause: false }), 240 + 270);
});

test('row problems name the field: missing start or end, end not after start; blank rows have none', () => {
  assert.deepEqual(rowProblems({ start: '', end: '', pause: '0', kategorie: '' }), {});
  assert.deepEqual(rowProblems({ start: '16:00', end: '', pause: '0', kategorie: '' }), { end: 'Ende fehlt' });
  assert.deepEqual(rowProblems({ start: '', end: '16:00', pause: '0', kategorie: '' }), { start: 'Start fehlt' });
  assert.deepEqual(rowProblems({ start: '16:00', end: '15:00', pause: '0', kategorie: '' }), { end: 'Ende muss nach dem Start liegen' });
  assert.deepEqual(rowProblems({ start: '08:00', end: '16:00', pause: '0', kategorie: '' }), {});
});

test('quick end adds minutes to the start and stops at 23:55', () => {
  assert.deepEqual(QUICK_END_MINUTES, [30, 60, 240, 480]);
  assert.deepEqual(QUICK_PAUSES, [0, 30, 45]);
  assert.equal(addToTime('08:00', 480), '16:00');
  assert.equal(addToTime('08:00', 30), '08:30');
  assert.equal(addToTime('20:00', 480), '23:55');
  assert.equal(addToTime('', 60), '');
});

test('the editor title names the type only where both exist', () => {
  assert.equal(editorTitle('07.11.2026', 'work', false), '07.11.2026');
  assert.equal(editorTitle('07.11.2026', 'reservation', true), '07.11.2026 · Reservierung');
  assert.equal(editorTitle('07.11.2026', 'work', true), '07.11.2026 · Arbeitszeit');
});

// --- Einstellungen › Verbindung (#461) -------------------------------------------------------------

import { connectionSummary, storageNotice } from '../view-model.js';

test('the connection summary says the state first: connected or offline, then when it last synced', () => {
  const ok = connectionSummary({ online: true, desktopName: 'Desktop (Dev)', lastSyncAt: '2026-11-06T16:36:00Z', tokenUntil: '06.12.2026', timeZone: 'UTC' });
  assert.equal(ok.pill, 'Verbunden');
  assert.equal(ok.kind, 'ok');
  assert.equal(ok.name, 'Desktop (Dev)');
  assert.equal(ok.detail, 'zuletzt abgeglichen um 16:36 · Kopplung gültig bis 06.12.2026');
  const off = connectionSummary({ online: false, desktopName: '', lastSyncAt: '', tokenUntil: '' });
  assert.equal(off.pill, 'Offline');
  assert.equal(off.kind, 'warn');
  assert.equal(off.name, 'Desktop');                                                   // ohne Namen nicht leer
  assert.equal(off.detail, 'noch nicht abgeglichen');
});

test('the storage notice appears only when the browser refuses to keep the data, with the way out', () => {
  assert.equal(storageNotice(true), null);
  assert.equal(storageNotice(null), null);                                              // noch nicht gefragt
  const notice = storageNotice(false);
  assert.equal(notice.action, 'persist');
  assert.match(notice.text, /nicht dauerhaft/);
  assert.match(storageNotice(false, { refused: true }).text, /abgelehnt/);
  assert.equal(storageNotice(false, { refused: true }).action, null);
});

test('the push model exposes the switch position and whether it can be flipped', () => {
  const base = { desktopReady: true };
  assert.deepEqual([pushModel({ ...base, state: 'on' }).on, pushModel({ ...base, state: 'on' }).toggle], [true, true]);
  assert.deepEqual([pushModel({ ...base, state: 'off' }).on, pushModel({ ...base, state: 'off' }).toggle], [false, true]);
  assert.deepEqual([pushModel({ ...base, state: 'denied' }).on, pushModel({ ...base, state: 'denied' }).toggle], [false, false]);
  assert.deepEqual([pushModel({ ...base, state: 'unsupported' }).on, pushModel({ ...base, state: 'unsupported' }).toggle], [false, false]);
});
