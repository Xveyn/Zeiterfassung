// pwa/view-model.js
// @ts-check
// Alles, was die Oberfläche anzeigt, als reine Daten: Wochenliste, Statuszeile, Hinweise,
// Konfliktliste, Editor-Zeilen. Kein DOM — die dünne Schicht in `views.js` macht daraus
// Elemente. Summen nur über ganze Minuten (`minutes.js`).
import {
  addDays, dayMinutes, formatDateDe, formatMinutes, isIsoDate, isoWeek, mondayOf, normalizeSlots,
  parseTime, slotMinutes, snapTime, validateSlots, weekDays,
} from './minutes.js';
import { blocksLan } from './browser-policy.js';
import { categoryRows, timesSummary } from './categories.js';
import { WEEKDAY_KEYS, resolveSlotDefaults, weekdayKey } from './defaults.js';
import { formatClock, formatDateShort, getLocale, weekdayShort } from './locale.js';
import { t } from './i18n.js';
import { describeError } from './messages.js';
import { openReservationSlots, pendingReservationMinutes, reservationBlockVisible, validateReservationSlots } from './reservations.js';
import { describeState } from './push-policy.js';
import { LEGACY_AHEAD_DAYS, aheadDays, olderState } from './window-policy.js';

/** Kurzer Wochentag (0 = Montag): deutsch wie bisher, sonst aus der Locale. */
function weekdayName(index) {
  const tag = getLocale();
  if (!tag.startsWith('de')) return weekdayShort(index, tag);
  return [t('woche.tag.kurz.mo'), t('woche.tag.kurz.di'), t('woche.tag.kurz.mi'), t('woche.tag.kurz.do'),
    t('woche.tag.kurz.fr'), t('woche.tag.kurz.sa'), t('woche.tag.kurz.so')][index];
}

/** Titel des Tages-Editors: Wochentag (Kurzform wie in der Wochenliste) und deutsches Datum,
 *  `Mi, 04.11.2026`. Was kein ISO-Datum ist, bleibt, wie es ist. */
export function dayTitle(iso) {
  if (!isIsoDate(iso)) return iso;
  return `${weekdayName(WEEKDAY_KEYS.indexOf(weekdayKey(iso)))}, ${formatDateDe(iso)}`;
}
const SKEW_WARN_MS = 120000;

const isObject = (value) => value !== null && typeof value === 'object' && !Array.isArray(value);

export function slotText(slot) {
  const pause = Number.isInteger(slot.pause) && slot.pause > 0 ? t('woche.slot.pause', { minutes: slot.pause }) : '';
  const category = typeof slot.kategorie === 'string' && slot.kategorie ? ` · ${slot.kategorie}` : '';
  return `${slot.start}–${slot.end}${pause}${category}`;
}

/** Zeilen des Kategorie-Modals: alle bekannten Kategorien in Server-Reihenfolge. Steht am Tag eine,
 *  die der Server nicht listet (frei eingegeben, vom Desktop), hängt sie hinten dran — sonst fehlte
 *  im Modal ausgerechnet die aktuelle Auswahl. */
export function categoryOptions(categories, current) {
  const options = categories.map((name) => ({ name, active: name === current }));
  if (current && !categories.includes(current)) options.push({ name: current, active: true });
  return options;
}

export function categoryLabel(current) {
  return current ? current : t('editor.kategorie.waehlen');
}

/** Label des Kategorie-Buttons einer Zeile. Wie `slot_category_display` am Desktop hängt es ein `*`
 *  an, wenn Start/Ende (bei Ist-Zeit mit `withPause` auch die Pause) von den Standardzeiten der
 *  Kategorie abweichen. Reine Anzeige: `row.kategorie` und das Gespeicherte bleiben der Klarname.
 *  Ohne Standardwerte (älterer Desktop) gibt es nie ein Sternchen. */
export function categoryDisplay(row, defaults, weekday, withPause) {
  const name = categoryLabel(row.kategorie);
  if (!row.kategorie || !defaults) return name;
  const target = resolveSlotDefaults(defaults, row.kategorie, weekday);
  const overridden = row.start !== target.start || row.end !== target.end
    || (withPause && String(row.pause) !== String(target.pause));
  return overridden ? `${name}*` : name;
}

export function localTime(iso, timeZone) {
  const time = Date.parse(iso);
  if (Number.isNaN(time)) return '';
  return formatClock(time, timeZone);
}

function stampLabel(iso, timeZone) {
  const time = localTime(iso, timeZone);
  return time ? `${formatDateDe(iso.slice(0, 10))} ${time}` : '';
}

// --- Woche ---------------------------------------------------------------------------------------

// `aheadDays`: wie weit nach heute das Handy Ist-Zeiten kennt (`window-policy.aheadDays`, #265); Tage dahinter räumt der
// Abgleich wieder auf.
/** @param {{ getDay: (date: string) => any, getReservation?: (date: string) => any, [key: string]: any }} options */
export function weekModel({ getDay, anchor, today, conflictDates = [], windowDays = 0, aheadDays = LEGACY_AHEAD_DAYS,
  getReservation = () => null, reservationsEnabled = false }) {
  const conflicts = new Set(conflictDates);
  const dates = weekDays(anchor);
  const week = dates.map((date, index) => {
    const day = getDay(date);
    const cleared = Boolean(day?.deleted);
    const slots = day && !cleared ? day.slots : [];
    const minutes = dayMinutes(slots);
    const visible = reservationsEnabled && reservationBlockVisible(date, today);
    const planned = visible ? getReservation(date) : null;
    const reservation = planned && !planned.deleted && planned.slots.length > 0 ? planned : null;
    return {
      date,
      weekday: weekdayName(index),
      label: formatDateDe(date),
      isToday: date === today,
      isWeekend: index >= 5,
      beyondWindow: date > addDays(today, aheadDays),
      // Außerhalb dessen, was das Handy vom Desktop kennt: ein leer wirkender Tag kann dort Einträge
      // haben, und Speichern ersetzt sie (der Handy-Stand gewinnt ohne Konflikt).
      outsideWindow: date > addDays(today, aheadDays) || (windowDays > 0 && date < addDays(today, -windowDays)),
      slots: slots.map(slotText),
      minutes,
      minutesLabel: minutes > 0 ? formatMinutes(minutes) : '',
      // Ein Tombstone (am Desktop oder hier geleert) sieht aus wie ein leerer Tag (#353).
      state: !day || cleared ? 'empty' : 'filled',
      dirty: Boolean(day?.dirty),
      error: day?.error ?? null,
      conflict: conflicts.has(date),
      // Einladung auf leeren Tagen, an denen Eintragen geht (nicht außerhalb des Fensters, nicht mit Reservierung).
      addHint: (!day || cleared) && !reservation && !(date > addDays(today, aheadDays) || (windowDays > 0 && date < addDays(today, -windowDays)))
        ? (visible ? t('woche.eintragen_oder_planen') : t('woche.eintragen')) : '',
      // Reservierungen zählen nicht in `minutes`/`totalMinutes`; vergangene Tage zeigen nie eine.
      reservationVisible: visible,
      reservation: reservation && {
        slots: openReservationSlots(reservation.slots, slots, date === today).map(slotText), dirty: reservation.dirty, error: reservation.error },
      pendingMinutes: reservation ? pendingReservationMinutes(reservation.slots, slots, date === today) : 0,
    };
  });
  const total = week.reduce((sum, day) => sum + day.minutes, 0);
  const pending = week.reduce((sum, day) => sum + day.pendingMinutes, 0);
  return {
    title: t('woche.titel', { week: isoWeek(anchor).week }),
    range: `${formatDateShort(dates[0])}–${formatDateDe(dates[6])}`,
    anchor: mondayOf(anchor),
    isCurrent: dates.includes(today),
    days: week,
    totalMinutes: total,
    totalLabel: formatMinutes(total),
    pendingMinutes: pending,
    pendingLabel: formatMinutes(pending),
  };
}

// --- Status und Hinweise -------------------------------------------------------------------------

export function statusModel({ paired, online, syncing, pending, lastSyncAt, timeZone }) {
  const pendingText = pending === 0 ? '' : pending === 1 ? t('status.nicht_uebertragen.eins')
    : t('status.nicht_uebertragen.mehr', { count: pending });
  const last = lastSyncAt ? localTime(lastSyncAt, timeZone) : '';
  return {
    paired, online, syncing, pendingText,
    lastText: last ? t('status.zuletzt', { zeit: last }) : t('status.noch_nicht'),
    connection: !paired ? t('status.nicht_gekoppelt') : syncing ? t('status.gleiche_ab') : online ? t('status.online') : t('status.offline'),
    canSync: paired && !syncing,
  };
}

/** So lange bleibt der geschlossene Speicher-Hinweis weg (danach erinnert er wieder, solange der Zustand besteht). */
export const STORAGE_HINT_QUIET_MS = 7 * 86400000;

export function hintsModel({ lastError, excluded, skewMs, persistent, updateReady, conflictCount, errorDays, errorEnv = {},
  dismissedAt = 0, now = Date.now(), persistRefused = false }) {
  const hints = [];
  const install = iosInstallHint(errorEnv);
  if (install) hints.push({ id: 'ios-install', kind: 'info', text: install, action: null });
  if (lastError) {
    const { text, action } = describeError(lastError, errorEnv);
    hints.push({ id: 'error', kind: 'error', text, action });
  }
  if (updateReady) hints.push({ id: 'update', kind: 'info', text: t('hinweis.update'), action: 'reload' });
  if (conflictCount > 0) {
    hints.push({ id: 'conflicts', kind: 'warn', action: 'conflicts',
      text: conflictCount === 1 ? t('hinweis.konflikt.eins', { count: conflictCount }) : t('hinweis.konflikt.mehr', { count: conflictCount }) });
  }
  if (errorDays > 0) {
    hints.push({ id: 'rejected', kind: 'warn', action: null,
      text: errorDays === 1 ? t('hinweis.abgelehnt.eins', { count: errorDays }) : t('hinweis.abgelehnt.mehr', { count: errorDays }) });
  }
  if (excluded) {
    hints.push({ id: 'excluded', kind: 'info', action: null,
      text: t('hinweis.ausgeschlossen') });
  }
  if (Math.abs(skewMs || 0) >= SKEW_WARN_MS) {
    hints.push({ id: 'skew', kind: 'warn', action: null,
      text: t('hinweis.uhr_weicht_ab', { minutes: Math.round(Math.abs(skewMs) / 60000) }) });
  }
  // Eine Uhr, die hinter den Zeitpunkt des Schließens zurückgestellt wurde, verbirgt den Hinweis nicht für immer.
  const quiet = dismissedAt > 0 && dismissedAt <= now && now - dismissedAt < STORAGE_HINT_QUIET_MS;
  if (persistent === false && !quiet) {
    hints.push({ id: 'storage', kind: 'warn', dismissible: true, ...storageNotice(false, { refused: persistRefused }) });
  }
  return hints;
}

// --- Konflikte -----------------------------------------------------------------------------------

export function conflictsModel(conflicts, timeZone) {
  if (!Array.isArray(conflicts)) return [];
  return conflicts
    .filter((conflict) => isObject(conflict) && typeof conflict.date === 'string')
    .map((conflict) => ({
      id: String(conflict.id),
      date: conflict.date,
      dateLabel: formatDateDe(conflict.date),
      versions: (Array.isArray(conflict.versions) ? conflict.versions : []).filter(isObject).map((version) => {
        const slots = Array.isArray(version.slots) ? version.slots.filter(isObject) : [];
        return {
          who: version.name || String(version.device ?? '').slice(0, 8),
          when: stampLabel(String(version.modified_at ?? ''), timeZone),
          slots: slots.map(slotText),
          minutesLabel: formatMinutes(dayMinutes(slots)),
        };
      }),
    }))
    .sort((a, b) => a.date.localeCompare(b.date));
}

// --- Editor --------------------------------------------------------------------------------------

/** Eine frische Zeile. Mit Standardzeiten des Desktops (#288) ist sie wie am Desktop vorbelegt;
 *  `base` merkt sich, was zuletzt vorbelegt wurde: `pickCategory` überschreibt nur Felder, die noch
 *  darauf stehen. Ohne Standardwerte (älterer Desktop) bleibt sie leer wie zuvor. */
function freshRow(defaults, weekday) {
  const d = defaults ? resolveSlotDefaults(defaults, '', weekday) : { start: '', end: '', pause: 0 };
  const row = { start: d.start, end: d.end, pause: String(d.pause), kategorie: '' };
  return { ...row, base: { start: row.start, end: row.end, pause: row.pause } };
}

/** Ist-Zeile aus einer Reservierung (wie `entry_dialog` am Desktop): Zeiten des ersten Slots, Pause aus
 *  dem Standard, die Kategorie nur bei genau einem Slot (`suggest_ist_category`) — bei mehreren wäre
 *  unklar, welcher gemeint ist. `base` steht auf dem Vorschlag, eine später gewählte Kategorie zieht
 *  also wie bei jeder frischen Zeile ihre Standardzeiten nach. */
function suggestedRow(slots, defaults, weekday) {
  const row = freshRow(defaults, weekday);
  row.start = slots[0].start ?? '';
  row.end = slots[0].end ?? '';
  // Eine geplante Pause (#455) gilt; ältere Reservierungen tragen 0 und behalten die Standardpause.
  if (Number.isInteger(slots[0].pause) && slots[0].pause > 0) row.pause = String(slots[0].pause);
  row.kategorie = slots.length === 1 ? slots[0].kategorie ?? '' : '';
  row.base = { start: row.start, end: row.end, pause: row.pause };
  return row;
}

/** Zeilen des Ist-Zeit-Reiters. Ohne gespeicherte Ist-Zeit schlägt eine vorhandene Reservierung
 *  (`reservation`, nur wenn der Tag sie zeigt) die Zeile vor, sonst gilt die Standardzeile. */
export function editorRows(day, defaults = null, weekday = '', reservation = null) {
  if (!day || day.deleted || day.slots.length === 0) {
    const planned = reservation && !reservation.deleted && reservation.slots.length > 0;
    return [planned ? suggestedRow(reservation.slots, defaults, weekday) : freshRow(defaults, weekday)];
  }
  return day.slots.map((slot) => ({
    start: slot.start, end: slot.end, pause: String(slot.pause ?? 0), kategorie: slot.kategorie ?? '',
  }));
}

/** Zeilen der Reservierung: wie `editorRows`. Die Standardpause belegt eine neue Zeile nur mit dem Flag
 *  (`pauseEnabled`, #455); ohne es steht die Pause auf 0 und geht nie in einen Slot. */
export function reservationRows(reservation, defaults = null, weekday = '', { pauseEnabled = false } = {}) {
  const rows = editorRows(reservation, defaults, weekday);
  if (pauseEnabled) return rows;
  return rows.map((row) => ({ ...row, pause: '0', base: row.base && { ...row.base, pause: '0' } }));
}

const isBlankReservation = (row) => row.start === '' && row.end === '' && row.kategorie === '';

// Leer heißt 0; sonst gilt, was getippt wurde (wie `rowsToSlots` der Ist-Zeit) — ungültige Eingabe
// (-30, 12.5, Text) bleibt ungültig und fällt der Prüfung auf, statt zu 0 zu werden.
const pauseMinutes = (text) => (String(text).trim() === '' ? 0 : Number(text));

/** Mit `pauseEnabled` trägt der Slot die Pause (leer oder Text = 0), sonst genau `{start, end, kategorie}`. */
export function reservationRowsToSlots(rows, { pauseEnabled = false } = {}) {
  return rows.filter((row) => !isBlankReservation(row)).map((row) => ({
    start: row.start, end: row.end, kategorie: row.kategorie,
    ...(pauseEnabled ? { pause: pauseMinutes(row.pause) } : {}) }));
}

export function validateReservationRows(rows, { pauseEnabled = false } = {}) {
  return validateReservationSlots(normalizeSlots(reservationRowsToSlots(rows, { pauseEnabled })));
}

/** „+ Slot“: der Start ist das Ende des vorigen und wird von einer Kategorie nie überschrieben. */
export function nextRow(previous) {
  const start = previous.end ?? '';
  return { start, end: '', pause: '0', kategorie: previous.kategorie ?? '',
    base: { start: null, end: '', pause: '0' } };
}

/** Kategorie setzen und, wie am Desktop, Start/Ende/Pause aus den Standardzeiten übernehmen — aber nur
 *  in Feldern, die noch auf dem zuletzt vorbelegten Wert stehen. Gespeicherte Slots haben kein `base`:
 *  ihre Zeiten sind bewusst gesetzt und bleiben unangetastet. */
export function pickCategory(row, name, defaults, weekday) {
  row.kategorie = name;
  if (!defaults || !row.base) return;
  const next = resolveSlotDefaults(defaults, name, weekday);
  for (const [field, value] of [['start', next.start], ['end', next.end], ['pause', String(next.pause)]]) {
    if (row.base[field] !== null && row[field] === row.base[field]) {
      row[field] = value;
      row.base[field] = value;
    }
  }
}

const isBlank = (row) => row.start === '' && row.end === '' && (row.pause === '' || row.pause === '0')
  && row.kategorie === '';

/** Formularzeilen → Slots für `Store.saveDay` (das normalisiert und prüft erneut). Ganz leere
 *  Zeilen entfallen, damit ein vergessenes „+ Slot“ nicht stört. */
export function rowsToSlots(rows) {
  return rows.filter((row) => !isBlank(row)).map((row) => ({
    start: row.start, end: row.end,
    pause: row.pause === '' ? 0 : Number(row.pause),
    kategorie: row.kategorie,
  }));
}

export function validateRows(rows) {
  return validateSlots(normalizeSlots(rowsToSlots(rows)));
}

// --- Editor: Netto, Feldfehler, Schnellwahl (#461) ---------------------------------------------------

/** Schnellwahl für das Ende (Minuten nach dem Start) und für die Pause. */
export const QUICK_END_MINUTES = [30, 60, 240, 480];
export const QUICK_PAUSES = [0, 30, 45];

const isBlankRow = (row) => row.start === '' && row.end === '' && row.kategorie === ''
  && (row.pause === '' || row.pause === '0');

/** Netto-Minuten einer Formularzeile (Spanne minus Pause), `null` solange Start oder Ende unbrauchbar sind.
 *  Eine Pause, die keine Zahl ist, zählt 0 — die Prüfung beim Speichern meldet sie. */
export function rowNetMinutes(row) {
  if (parseTime(row.start) === null || parseTime(row.end) === null) return null;
  const pause = Number(row.pause);
  return slotMinutes({ start: row.start, end: row.end, pause: Number.isInteger(pause) ? pause : 0 });
}

/** Summe der brauchbaren Zeilen in ganzen Minuten. `withPause: false` (Reservierung ohne Pausenfeld) zählt die Pause nicht. */
export function dayNetMinutes(rows, { withPause = true } = {}) {
  return rows.reduce((sum, row) => sum + (rowNetMinutes(withPause ? row : { ...row, pause: '0' }) ?? 0), 0);
}

/** Feldfehler einer nicht leeren Zeile: `{start?, end?}` mit dem Text für das Feld. Die vollständige Prüfung
 *  bleibt `validateRows`; das hier sagt nur, *welches* Feld fehlt. */
export function rowProblems(row) {
  if (isBlankRow(row)) return {};
  const problems = {};
  const start = parseTime(row.start);
  const end = parseTime(row.end);
  if (row.start === '') problems.start = t('editor.problem.start_fehlt');
  if (row.end === '') problems.end = t('editor.problem.ende_fehlt');
  else if (start !== null && end !== null && end <= start) problems.end = t('editor.problem.ende_nach_start');
  return problems;
}

/** Start plus Minuten als `HH:MM`, höchstens 23:55 (wie `snapTime`); `''` ohne brauchbaren Start. */
export function addToTime(start, minutes) {
  const base = parseTime(start);
  if (base === null) return '';
  const total = Math.min(base + minutes, 1439);
  return snapTime(`${String(Math.floor(total / 60)).padStart(2, '0')}:${String(total % 60).padStart(2, '0')}`);
}

/** Dialogtitel: das Datum, bei zwei Reitern mit dem aktiven Typ dahinter. */
export function editorTitle(date, kind, hasBoth) {
  if (!hasBoth) return date;
  return kind === 'reservation' ? t('editor.titel.reservierung', { date }) : t('editor.titel.arbeitszeit', { date });
}

// --- Tag seit dem Öffnen des Editors geändert? -----------------------------------------------------

/** Hat sich der Inhalt eines Tages geändert (Abgleich, anderer Tab), seit der Editor ihn gelesen hat?
 *  Das „nicht übertragen“-Kennzeichen zählt nicht: es fällt nach einem bestätigten Abgleich, ohne
 *  dass sich am Tag etwas ändert. */
export function dayChanged(opened, current) {
  if (!opened || !current) return Boolean(opened) !== Boolean(current);
  return opened.modified_at !== current.modified_at || opened.deleted !== current.deleted
    || JSON.stringify(opened.slots) !== JSON.stringify(current.slots);
}

// --- Stabile Oberfläche über Renders hinweg ----------------------------------------------------------

/** Identität eines Hinweises: gleicher Schlüssel, gleiches Element — es wird nicht neu eingefügt und
 *  damit auch nicht erneut angesagt. */
export const hintKey = (hint) => `${hint.id}|${hint.kind}|${hint.action ?? ''}|${hint.text}`;

/** Welches Element bekommt nach einem Render den Fokus zurück (`data-focus`-Schlüssel) oder `null`?
 *  Liegt der Fokus im Body, war das fokussierte Element weg oder gesperrt: dann gilt der letzte
 *  Schlüssel. Liegt er in einem Dialog oder sonstwo, bleibt er unangetastet. */
export function focusKeyToRestore({ activeKey, inRoot, isBody, last }) {
  if (inRoot && activeKey) return activeKey;
  return isBody ? last : null;
}

// --- Reiter „Verbindung“ ---------------------------------------------------------------------------

/** Hinweis für den Reiter „Verbindung“ der Einstellungen, wenn der Desktop älter ist als diese Seite: er schickt weder
 *  `desktop` noch `defaults` (#288). Erkannt wird das an den fehlenden Feldern, nicht an einer Version
 *  (Feature-Erkennung, s. pwa/CLAUDE.md „Kompatibilität“). Vor dem ersten Abgleich weiß man nichts. */
export function desktopHint(meta) {
  if (!meta || !meta.last_pull_at) return '';
  const known = Boolean(meta.desktop && meta.desktop.version);
  return known ? '' : t('hinweis.desktop_aelter');
}

/** Auf iOS gehören Safari-Tab und installierte Web-App nicht zusammen (getrennter Speicher), und iOS löscht
 *  den Speicher im Tab nach sieben Tagen ohne Nutzung. Der Hinweis steht deshalb vor dem Koppeln und im
 *  Wochenbild, solange die Seite im Browser läuft; `standalone` muss ausdrücklich `false` sein (unbekannt
 *  heißt kein Hinweis). */
/** @param {{ browser?: string, standalone?: boolean }} [state] */
export function iosInstallHint({ browser, standalone } = {}) {
  if (browser !== 'ios' || standalone !== false) return '';
  return t('hinweis.ios_installieren');
}

/** Welche Felder die Koppel-Seite zeigt: ein Relay-Link bringt Geheimnis und Code mit, beides bleibt
 *  unsichtbar (das Geheimnis steht nie auf dem Bildschirm); bei LAN werden Adresse und Code getippt. */
export function pairFields({ relay = false } = {}) {
  return { address: !relay, code: !relay };
}

// --- Einrichtungs-Screen (#496) -----------------------------------------------------------------------

/** Ob die Koppel-Seite noch den Einrichtungs-Screen zeigt: solange nichts gelesen, getippt oder fehlgeschlagen ist.
 *  Danach (Link gescannt, „Adresse und Code eintippen“, laufende oder gescheiterte Kopplung) folgt das Formular. */
export function isSetupPhase({ relay = null, address = '', code = '', manual = false, busy = false, error = '' } = {}) {
  return !relay && !address && !code && !manual && !busy && !error;
}

/** Der Koppel-Zustand nach „Zurück“ aus dem Formular: wieder der Einrichtungs-Screen. Eingetipptes, ein gelesener Link
 *  (auch das Relay-Geheimnis) und ein Fehler entfallen; nur der Gerätename bleibt, den der Nutzer schon getippt hat. */
export function pairingAfterBack(pairing = {}) {
  const deviceName = typeof pairing?.deviceName === 'string' ? pairing.deviceName : '';
  return { address: '', code: '', deviceName, busy: false, error: '', relay: null, manual: false };
}

const scanStep = (canScan) => ({
  title: t('einrichtung.scan.titel'),
  text: canScan
    ? t('einrichtung.scan.text_kamera')
    : t('einrichtung.scan.text_ohne_kamera'),
  state: 'focus',
});

/** Der Einrichtungs-Screen ohne DOM: Variante, Schritte, Hauptknopf, Nebenwege (eingeklappt, grau) und Hinweis.
 *  `lan`: Chromium und unbekannte Browser; `relay`: Engines, die das WLAN sperren (`blocksLan`); `install`: iOS im
 *  Browser-Tab, erst installieren. Ein unbekannter Anzeigemodus (`standalone` nicht `false`) gilt nicht als „nicht
 *  installiert“. Der Relay-Weg hat keine Eingabe von Hand: er läuft nur über den QR-Link des Desktops. */
/** @param {{ browser?: string, standalone?: boolean, canScan?: boolean }} [state] */
export function setupModel({ browser, standalone, canScan = false } = {}) {
  const base = { title: t('einrichtung.titel'), lead: t('einrichtung.lead') };
  const nameStep = (text) => ({ title: t('einrichtung.benennen.titel'), text, state: 'todo' });
  if (browser === 'ios' && standalone === false) {
    return {
      ...base, variant: 'install', scan: false,
      steps: [
        { title: t('einrichtung.install.home_titel'), text: t('einrichtung.install.home_text'), state: 'focus' },
        { title: t('einrichtung.desktop.titel'), text: t('einrichtung.desktop.text_relay'), state: 'later' },
        { title: t('einrichtung.scan.titel'), text: t('einrichtung.install.scan_text'), state: 'later' },
        { title: t('einrichtung.benennen.titel'), text: t('einrichtung.benennen.text'), state: 'later' },
      ],
      alternatives: [{ id: 'browser-anyway', title: t('einrichtung.alt.browser_titel'), text: t('einrichtung.alt.browser_text'), action: 'scan' }],
      note: { kind: 'warn', text: t('einrichtung.note.install') },
    };
  }
  if (blocksLan(browser)) {
    return {
      ...base, variant: 'relay', scan: canScan,
      steps: [
        { title: t('einrichtung.desktop.titel'), text: t('einrichtung.desktop.text_relay'), state: 'todo' },
        scanStep(canScan),
        nameStep(t('einrichtung.benennen.text')),
      ],
      alternatives: [],
      note: { kind: 'info', text: t('einrichtung.note.relay') },
    };
  }
  return {
    ...base, variant: 'lan', scan: canScan,
    steps: [
      { title: t('einrichtung.desktop.titel'), text: t('einrichtung.desktop.text_lan'), state: 'todo' },
      scanStep(canScan),
      nameStep(t('einrichtung.benennen.text')),
    ],
    alternatives: [
      { id: 'relay-hint', title: t('einrichtung.alt.relay_titel'), text: t('einrichtung.alt.relay_text'), action: null },
      { id: 'manual', title: t('einrichtung.alt.manuell_titel'), text: t('einrichtung.alt.manuell_text'), action: 'manual' },
    ],
    note: null,
  };
}

/** Der Weg zum Desktop als Anzeige: die LAN-Adresse (`host:port`) oder „Relay“, nie das Geheimnis. */
export function connectionLabel(meta) {
  if (meta?.transport === 'relay') return t('verbindung.relay');
  return meta?.address ? `${meta.address.host}:${meta.address.port}` : '';
}

// --- Lesefenster (#250) --------------------------------------------------------------------------

/** Text und Aktion für den Rand des Fensters (`window-policy.olderState`); `null`, wenn nichts zu sagen ist. */
export function olderModel(state) {
  switch (state.kind) {
    case 'load':
      return { text: t('fenster.aelter.nicht_geladen'), action: 'older', wish: state.wish,
        buttonText: t('fenster.aelter.laden', { wish: state.wish }) };
    case 'capped':
      // 365 ist das Maximum der Desktop-Einstellung: dorthin zu verweisen führt ins Leere.
      if (state.days >= 365) return { text: t('fenster.mehr_als_365'), action: null };
      return { text: t('fenster.hoechstens', { days: state.days }), action: null };
    case 'trimmed':
      return { text: t('fenster.datenmenge', { days: state.days }), action: null };
    case 'unknown':
      return { text: t('fenster.unbekannt'), action: null };
    case 'old_desktop':
      return { text: t('fenster.alter_desktop'), action: null };
    default:
      return null;
  }
}

/** Darf die Arbeitszeit dieses Tages hier bearbeitet werden? `null` ja, sonst Sperre mit Text und, wo es
 *  einen Ausweg gibt, der Aktion „Ältere Zeiten laden“ (#273).
 *
 *  Das Handy kennt vom Desktop nur `[heute − Fenster, heute + Vorschau]`. Ein Tag dahinter sieht leer aus,
 *  obwohl der Desktop dort Einträge haben kann, und ein Speichern ersetzte sie ohne Konflikt (der Desktop
 *  nimmt an, das Handy habe alles seit dem letzten Abgleich gesehen). Deshalb gesperrt — außer das Handy hält
 *  den Tag schon (`hasRecord`: auch ein nicht übertragener oder geleerter Tag muss korrigierbar bleiben).
 *  Reservierungen haben ein eigenes Fenster und sind davon nicht betroffen. */
export function editLock({ date, today, meta, hasRecord = false }) {
  if (hasRecord) return null;
  const ahead = aheadDays(meta.window_ahead);
  if (date > addDays(today, ahead)) {
    return { kind: 'future', action: null,
      text: ahead === 1 ? t('sperre.zukunft.eins') : t('sperre.zukunft.mehr', { days: ahead }) };
  }
  const state = olderState({ firstDay: date, today, windowDays: meta.window_days, windowMax: meta.window_max,
    maxKnown: meta.window_max_known, acked: meta.window_wish_acked });
  const older = olderModel(state);
  if (!older) return null;
  return { kind: 'older', action: older.action, wish: older.wish, buttonText: older.buttonText,
    text: t('sperre.aelter', { grund: older.text }) };
}

/** Die Zeile „Verlauf“ im Reiter „Verbindung“. */
export function windowRow({ days, max, wish, ahead = null }) {
  const parts = [];
  if (Number.isInteger(wish) && wish !== days) parts.push(t('fenster.zeile.gewuenscht', { wish }));
  if (Number.isInteger(max)) parts.push(t('fenster.zeile.erlaubt', { max }));
  return {
    text: (parts.length ? t('fenster.zeile.mit_zusatz', { days, parts: parts.join(', ') }) : t('fenster.zeile.tage', { days }))
      + (Number.isInteger(ahead) && ahead > 0 ? t('fenster.zeile.voraus', { ahead }) : ''),
    canReset: Number.isInteger(wish) && wish > 90,
  };
}

// --- Einstellungen ---------------------------------------------------------------------------------

export const SETTINGS_TABS = ['connection', 'categories', 'updates', 'debug'];
export const retentionLabel = (days) => (days === 1 ? t('einstellungen.aufbewahrung.eins') : t('einstellungen.aufbewahrung.mehr', { days }));
export function settingsTabLabel(key) {
  switch (key) {
    case 'connection': return t('einstellungen.tab.verbindung');
    case 'categories': return t('einstellungen.tab.kategorien');
    case 'updates': return t('einstellungen.tab.updates');
    case 'debug': return t('einstellungen.tab.debug');
    default: return undefined;
  }
}

export const categoryRenameHint = () => t('kategorien.umbenennen_hinweis');

export function categoryRemovalText(name) {
  return t('einstellungen.kategorien.entfernen_text', { name });
}

/** Der Reiter „Kategorien“: Zeilen mit Kurzfassung, ob bearbeitet werden darf (der Desktop versteht
 *  `settings`) und der Zustand des Blocks. Ein älterer Desktop lässt die Liste lesbar, aber nicht
 *  bearbeitbar (Feature-Erkennung wie bei den Reservierungen). */
export function categoriesModel({ categories, defaults, writable, edit }) {
  const rows = categoryRows(categories, defaults?.category_times ?? {}).map((row) => ({
    ...row, summary: timesSummary(row) }));
  const synced = defaults !== null && defaults !== undefined;
  const editable = Boolean(writable) && synced;
  let hint = '';
  if (!writable) hint = t('einstellungen.kategorien.hinweis_alt');
  else if (!synced) hint = t('einstellungen.kategorien.hinweis_nicht_abgeglichen');
  return {
    rows,
    editable,
    hint,
    error: edit?.error ?? null,
    dirty: Boolean(edit) && edit.dirty_version > edit.synced_version,
  };
}

// --- Benachrichtigungen (#331) -------------------------------------------------------------------

function pushActionLabel(action) {
  switch (action) {
    case 'enable': return t('push.aktion.erlauben');
    case 'disable': return t('push.aktion.ausschalten');
    default: return undefined;
  }
}

/** Anzeige des Abschnitts „Benachrichtigungen“ im Reiter Verbindung. `desktopReady` heißt: die letzte
 *  Antwort trug einen `reminders`-Block (der Desktop kennt die Handy-Erinnerungen). */
export function pushModel({ state, lastError, desktopReady, canTest = false }) {
  const { text, action } = describeState(state, lastError);
  const hint = state === 'on' && !desktopReady
    ? t('push.hinweis.desktop_ohne_erinnerungen')
    : '';
  return { text: `${text}${hint}`, action, actionLabel: action ? pushActionLabel(action) : '', canTest: state === 'on' && canTest,
    // Schalter: Stellung und ob er sich umlegen lässt (gesperrt/nicht unterstützt: nur der Text).
    on: state === 'on', toggle: action !== null };
}

/** Kopf des Reiters „Verbindung“: erst der Zustand, dann der Desktop und wann zuletzt abgeglichen wurde. */
export function connectionSummary({ online, desktopName, lastSyncAt, tokenUntil, timeZone }) {
  const last = lastSyncAt ? localTime(lastSyncAt, timeZone) : '';
  const parts = [last ? t('status.zuletzt', { zeit: last }) : t('status.noch_nicht')];
  if (tokenUntil) parts.push(t('verbindung.kopplung_bis', { datum: tokenUntil }));
  return { pill: online ? t('status.verbunden') : t('status.offline'), kind: online ? 'ok' : 'warn', name: desktopName || t('verbindung.desktop'), detail: parts.join(' · ') };
}

/** Hat der Abgleich vor dem Trennen den Desktop erreicht? Ja, wenn er mit einem Status geantwortet hat (auch mit
 *  einem Fehler wie „beschäftigt“ oder „Uhr weicht ab“: die Abmeldung käme an) und wenn der Relay die Anfrage
 *  angenommen hat, der Desktop aber schweigt (`desktop_silent`: sie liegt dann in der Box). Nein bei keiner Antwort
 *  und wenn die Antwort sagt, dass das Token nicht mehr gilt: dann widerrüfe der Desktop nichts. */
export function reachedAfterSyncError(error) {
  if (!error || typeof error !== 'object') return false;
  if (error.kind === 'desktop_silent') return true;
  if (error.code === 'token_expired' || error.code === 'token_revoked') return false;
  return Number.isInteger(error.status) && error.status > 0;
}

/** Die Rückfrage vor „Trennen und lokale Daten löschen“ (#499). `reached`: der Abgleich davor hat den Desktop erreicht
 *  (LAN) oder der Relay hat die Anfrage angenommen (auch wenn der Desktop schwieg: die Abmeldung liegt dann in der Box);
 *  `openDays`: danach noch nicht übertragene Tage; `desktopUnpair`: der Desktop kennt die Abmeldung. Der Desktop erfährt
 *  vom Trennen nur, wenn er sie kennt und der Weg dorthin offen war. Fehlt eine Angabe, gilt die vorsichtige Lesart. */
/** @param {{ reached?: boolean, openDays?: number, desktopUnpair?: boolean }} [state] */
export function unpairDialogModel({ reached, openDays = 0, desktopUnpair = false } = {}) {
  const open = Number.isInteger(openDays) && openDays > 0 ? openDays : 0;
  const summary = open > 0
    ? { kind: 'warn', text: open === 1 ? t('abmelden.offen.eins') : t('abmelden.offen.mehr', { count: open }) }
    : { kind: 'ok', text: t('abmelden.gesichert') };
  const notifiesDesktop = desktopUnpair === true && reached === true;
  return {
    summary,
    notifiesDesktop,
    warnDesktop: notifiesDesktop ? null
      : t('abmelden.desktop_erfaehrt_nichts'),
    canRetry: open > 0,
    confirmLabel: open > 0 ? t('abmelden.trotzdem') : t('abmelden.ja'),
  };
}

/** Warnung im Reiter „Verbindung“, wenn der Browser die Daten nicht dauerhaft sichert (`persistent === false`);
 *  `refused`: die erneute Anfrage wurde abgelehnt, dann gibt es keinen Knopf mehr. */
export function storageNotice(persistent, { refused = false } = {}) {
  if (persistent !== false) return null;
  return refused
    ? { text: t('speicher.abgelehnt'), action: null }
    : { text: t('speicher.nicht_dauerhaft'), action: 'persist' };
}
