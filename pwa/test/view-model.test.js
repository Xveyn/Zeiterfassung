// pwa/test/view-model.test.js
import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
  SETTINGS_TABS, categoriesModel, categoryRemovalText, categoryRenameHint, settingsTabLabel,
  WEEKDAYS, categoryLabel, categoryOptions, conflictsModel, dayChanged, editorRows, focusKeyToRestore, hintKey, hintsModel, desktopHint, localTime, nextRow, olderModel, pickCategory, rowsToSlots, slotText,
  statusModel, validateRows, weekModel, windowRow, reservationRows, reservationRowsToSlots, validateReservationRows,
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

test('reservation rows start from the weekday defaults and carry no pause on save', () => {
  const defaults = { pause: 30, weekdays: { fr: { start: '09:00', end: '17:00' } }, category_times: {} };
  const rows = reservationRows(null, defaults, 'fr');
  assert.equal(rows.length, 1);
  assert.deepEqual(reservationRowsToSlots(rows), [{ start: '09:00', end: '17:00', kategorie: '' }]);
});

test('saved reservation rows show their slots and a blank new row is dropped', () => {
  const rows = reservationRows(reserved([RES_SLOT]), null, 'mo');
  assert.deepEqual(reservationRowsToSlots(rows), [RES_SLOT]);
  const added = [...rows, { start: '', end: '', pause: '0', kategorie: '' }];
  assert.deepEqual(reservationRowsToSlots(added), [RES_SLOT]);
  assert.equal(validateReservationRows(added).ok, true);
});

test('a reservation row with times but a stray default pause validates', () => {
  const rows = [{ start: '09:00', end: '10:00', pause: '30', kategorie: '' }];
  assert.equal(validateReservationRows(rows).ok, true);          // die Pause zählt bei Reservierungen nicht
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
