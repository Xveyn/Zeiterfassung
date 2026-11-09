// pwa/view-model.js
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
import { describeError } from './messages.js';
import { openReservationSlots, pendingReservationMinutes, reservationBlockVisible, validateReservationSlots } from './reservations.js';
import { describeState } from './push-policy.js';
import { LEGACY_AHEAD_DAYS, aheadDays, olderState } from './window-policy.js';

export const WEEKDAYS = ['Mo', 'Di', 'Mi', 'Do', 'Fr', 'Sa', 'So'];

/** Titel des Tages-Editors: Wochentag (Kurzform wie in der Wochenliste) und deutsches Datum,
 *  `Mi, 04.11.2026`. Was kein ISO-Datum ist, bleibt, wie es ist. */
export function dayTitle(iso) {
  if (!isIsoDate(iso)) return iso;
  return `${WEEKDAYS[WEEKDAY_KEYS.indexOf(weekdayKey(iso))]}, ${formatDateDe(iso)}`;
}
const SKEW_WARN_MS = 120000;

const isObject = (value) => value !== null && typeof value === 'object' && !Array.isArray(value);

export function slotText(slot) {
  const pause = Number.isInteger(slot.pause) && slot.pause > 0 ? ` · ${slot.pause} min Pause` : '';
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
  return current ? current : 'Wählen';
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
  return new Intl.DateTimeFormat('de-DE', { hour: '2-digit', minute: '2-digit', timeZone }).format(new Date(time));
}

function stampLabel(iso, timeZone) {
  const time = localTime(iso, timeZone);
  return time ? `${formatDateDe(iso.slice(0, 10))} ${time}` : '';
}

// --- Woche ---------------------------------------------------------------------------------------

// `aheadDays`: wie weit nach heute das Handy Ist-Zeiten kennt (`window-policy.aheadDays`, #265); Tage dahinter räumt der
// Abgleich wieder auf.
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
      weekday: WEEKDAYS[index],
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
        ? (visible ? 'Eintragen oder planen' : 'Eintragen') : '',
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
    title: `KW ${isoWeek(anchor).week}`,
    range: `${formatDateDe(dates[0]).slice(0, 6)}–${formatDateDe(dates[6])}`,
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
  const pendingText = pending === 0 ? '' : pending === 1 ? '1 Änderung nicht übertragen'
    : `${pending} Änderungen nicht übertragen`;
  const last = lastSyncAt ? localTime(lastSyncAt, timeZone) : '';
  return {
    paired, online, syncing, pendingText,
    lastText: last ? `zuletzt abgeglichen um ${last}` : 'noch nicht abgeglichen',
    connection: !paired ? 'Nicht gekoppelt' : syncing ? 'Gleiche ab …' : online ? 'Online' : 'Offline',
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
  if (updateReady) hints.push({ id: 'update', kind: 'info', text: 'Neue Version verfügbar.', action: 'reload' });
  if (conflictCount > 0) {
    hints.push({ id: 'conflicts', kind: 'warn', action: 'conflicts',
      text: `${conflictCount} ${conflictCount === 1 ? 'Konflikt' : 'Konflikte'}: am Desktop lösen.` });
  }
  if (errorDays > 0) {
    hints.push({ id: 'rejected', kind: 'warn', action: null,
      text: `${errorDays} ${errorDays === 1 ? 'Tag wurde' : 'Tage wurden'} vom Desktop abgelehnt — bitte prüfen.` });
  }
  if (excluded) {
    hints.push({ id: 'excluded', kind: 'info', action: null,
      text: 'Dieses Handy war länger offline als die letzte Kompaktierung am Desktop. Am Desktop gelöschte Einträge bleiben gelöscht.' });
  }
  if (Math.abs(skewMs || 0) >= SKEW_WARN_MS) {
    hints.push({ id: 'skew', kind: 'warn', action: null,
      text: `Die Uhr des Handys weicht um etwa ${Math.round(Math.abs(skewMs) / 60000)} Minuten von der des Desktops ab. Datum und Uhrzeit am Handy prüfen.` });
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
  if (row.start === '') problems.start = 'Start fehlt';
  if (row.end === '') problems.end = 'Ende fehlt';
  else if (start !== null && end !== null && end <= start) problems.end = 'Ende muss nach dem Start liegen';
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
  return `${date} · ${kind === 'reservation' ? 'Reservierung' : 'Arbeitszeit'}`;
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
  return known ? '' : 'Die Desktop-App ist älter als diese Seite, einige Funktionen fehlen (z. B. die Vorbelegung der Zeiten). Bitte die Desktop-App aktualisieren.';
}

/** Auf iOS gehören Safari-Tab und installierte Web-App nicht zusammen (getrennter Speicher), und iOS löscht
 *  den Speicher im Tab nach sieben Tagen ohne Nutzung. Der Hinweis steht deshalb vor dem Koppeln und im
 *  Wochenbild, solange die Seite im Browser läuft; `standalone` muss ausdrücklich `false` sein (unbekannt
 *  heißt kein Hinweis). */
export function iosInstallHint({ browser, standalone } = {}) {
  if (browser !== 'ios' || standalone !== false) return '';
  return 'Auf dem iPhone und iPad zuerst zum Home-Bildschirm hinzufügen (Teilen → „Zum Home-Bildschirm“) und von dort öffnen, dann dort mit „QR-Code scannen“ koppeln (die Kamera-App geht oft auch, aber nicht immer: je nach iOS-Version öffnet sie den Link im Browser statt in der installierten Web-App). Im Browser gespeicherte Daten gehören nicht zur installierten Web-App, und iOS löscht sie dort nach sieben Tagen ohne Nutzung.';
}

/** Welche Felder die Koppel-Seite zeigt: ein Relay-Link bringt Geheimnis und Code mit, beides bleibt
 *  unsichtbar (das Geheimnis steht nie auf dem Bildschirm); bei LAN werden Adresse und Code getippt. */
export function pairFields({ relay = false } = {}) {
  return { address: !relay, code: !relay };
}

// --- Einrichtungs-Screen (#496) -----------------------------------------------------------------------

const SETUP_TITLE = 'Zeiterfassung App';
const SETUP_LEAD = 'Zeiten nachtragen, auch ohne Netz. Der Desktop bleibt die Quelle.';

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
  title: 'QR-Code scannen',
  text: canScan
    ? 'Der Code erscheint am Desktop.'
    : 'Keine Kamera verfügbar: den QR-Code vom Desktop mit der Kamera-App des Handys öffnen.',
  state: 'focus',
});

/** Der Einrichtungs-Screen ohne DOM: Variante, Schritte, Hauptknopf, Nebenwege (eingeklappt, grau) und Hinweis.
 *  `lan`: Chromium und unbekannte Browser; `relay`: Engines, die das WLAN sperren (`blocksLan`); `install`: iOS im
 *  Browser-Tab, erst installieren. Ein unbekannter Anzeigemodus (`standalone` nicht `false`) gilt nicht als „nicht
 *  installiert“. Der Relay-Weg hat keine Eingabe von Hand: er läuft nur über den QR-Link des Desktops. */
export function setupModel({ browser, standalone, canScan = false } = {}) {
  const base = { title: SETUP_TITLE, lead: SETUP_LEAD };
  const nameStep = (text) => ({ title: 'Handy benennen', text, state: 'todo' });
  if (browser === 'ios' && standalone === false) {
    return {
      ...base, variant: 'install', scan: false,
      steps: [
        { title: 'Zum Home-Bildschirm', text: 'Teilen-Symbol antippen → „Zum Home-Bildschirm“, dann von dort öffnen.', state: 'focus' },
        { title: 'Am Desktop öffnen', text: 'Einstellungen → Mobil → „Über Relay koppeln“', state: 'later' },
        { title: 'QR-Code scannen', text: 'In dieser Web-App, nicht mit der Kamera-App.', state: 'later' },
        { title: 'Handy benennen', text: 'Dann koppeln.', state: 'later' },
      ],
      alternatives: [{ id: 'browser-anyway', title: 'Trotzdem im Browser koppeln', text: 'Die Daten bleiben dann nur im Browser.', action: 'scan' }],
      note: { kind: 'warn', text: 'Safari löscht Daten im Tab nach 7 Tagen ohne Nutzung. Erst als App installiert bleiben Einträge und Erinnerungen erhalten.' },
    };
  }
  if (blocksLan(browser)) {
    return {
      ...base, variant: 'relay', scan: canScan,
      steps: [
        { title: 'Am Desktop öffnen', text: 'Einstellungen → Mobil → „Über Relay koppeln“', state: 'todo' },
        scanStep(canScan),
        nameStep('Dann koppeln.'),
      ],
      alternatives: [],
      note: { kind: 'info', text: 'Dieser Browser erreicht den Desktop nicht direkt im WLAN. Der Abgleich läuft deshalb verschlüsselt über das Internet.' },
    };
  }
  return {
    ...base, variant: 'lan', scan: canScan,
    steps: [
      { title: 'Am Desktop öffnen', text: 'Einstellungen → Mobil → „Gerät koppeln“', state: 'todo' },
      scanStep(canScan),
      nameStep('Dann koppeln.'),
    ],
    alternatives: [
      { id: 'relay-hint', title: 'Nicht im selben WLAN?', text: 'Am Desktop stattdessen „Über Relay koppeln“ wählen und den QR-Code scannen.', action: null },
      { id: 'manual', title: 'Adresse und Code eintippen', text: 'Nur im selben WLAN.', action: 'manual' },
    ],
    note: null,
  };
}

/** Der Weg zum Desktop als Anzeige: die LAN-Adresse (`host:port`) oder „Relay“, nie das Geheimnis. */
export function connectionLabel(meta) {
  if (meta?.transport === 'relay') return 'Relay (über das Internet)';
  return meta?.address ? `${meta.address.host}:${meta.address.port}` : '';
}

// --- Lesefenster (#250) --------------------------------------------------------------------------

/** Text und Aktion für den Rand des Fensters (`window-policy.olderState`); `null`, wenn nichts zu sagen ist. */
export function olderModel(state) {
  switch (state.kind) {
    case 'load':
      return { text: 'Ältere Zeiten sind noch nicht geladen.', action: 'older', wish: state.wish,
        buttonText: `Ältere Zeiten laden (bis ${state.wish} Tage)` };
    case 'capped':
      // 365 ist das Maximum der Desktop-Einstellung: dorthin zu verweisen führt ins Leere.
      if (state.days >= 365) return { text: 'Mehr als 365 Tage gibt es nur am Desktop.', action: null };
      return { text: `Der Desktop liefert höchstens ${state.days} Tage. Die Obergrenze lässt sich am Desktop unter Einstellungen → Mobil ändern.`, action: null };
    case 'trimmed':
      return { text: `Der Desktop liefert wegen der Datenmenge nur ${state.days} Tage.`, action: null };
    case 'unknown':
      return { text: 'Ältere Zeiten sind noch nicht geladen. Sobald der Abgleich mit dem Desktop gelaufen ist, lässt sich der Verlauf erweitern.', action: null };
    case 'old_desktop':
      return { text: 'Dieser Desktop kann nicht mehr als 90 Tage liefern. Bitte die Desktop-App aktualisieren.', action: null };
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
      text: `Dieser Tag lässt sich hier nicht bearbeiten: die Arbeitszeit geht nur bis ${ahead === 1 ? '1 Tag' : `${ahead} Tage`} im Voraus.` };
  }
  const state = olderState({ firstDay: date, today, windowDays: meta.window_days, windowMax: meta.window_max,
    maxKnown: meta.window_max_known, acked: meta.window_wish_acked });
  const older = olderModel(state);
  if (!older) return null;
  return { kind: 'older', action: older.action, wish: older.wish, buttonText: older.buttonText,
    text: `Dieser Tag liegt vor dem Zeitraum, den das Handy vom Desktop kennt, und lässt sich hier nicht bearbeiten, damit kein Eintrag am Desktop überschrieben wird. ${older.text}` };
}

/** Die Zeile „Verlauf“ im Reiter „Verbindung“. */
export function windowRow({ days, max, wish, ahead = null }) {
  const parts = [];
  if (Number.isInteger(wish) && wish !== days) parts.push(`gewünscht ${wish}`);
  if (Number.isInteger(max)) parts.push(`Desktop erlaubt bis ${max}`);
  return {
    text: (parts.length ? `${days} Tage (${parts.join(', ')})` : `${days} Tage`)
      + (Number.isInteger(ahead) && ahead > 0 ? `, dazu ${ahead} Tage voraus` : ''),
    canReset: Number.isInteger(wish) && wish > 90,
  };
}

// --- Einstellungen ---------------------------------------------------------------------------------

export const SETTINGS_TABS = ['connection', 'categories', 'updates', 'debug'];
const TAB_LABELS = { connection: 'Verbindung', categories: 'Kategorien', updates: 'Updates', debug: 'Debug' };
export const retentionLabel = (days) => (days === 1 ? '1 Tag' : `${days} Tage`);
export const settingsTabLabel = (key) => TAB_LABELS[key];

export const categoryRenameHint = 'Bestehende Einträge behalten den alten Namen.';

export function categoryRemovalText(name) {
  return `Die Kategorie „${name}“ wird gelöscht. Bestehende Einträge behalten ihren Namen, sie erscheint nur nicht mehr in der Auswahl.`;
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
  if (!writable) hint = 'Die Desktop-App ist älter als diese Seite: Kategorien lassen sich nur dort bearbeiten. Bitte die Desktop-App aktualisieren.';
  else if (!synced) hint = 'Die Kategorien sind noch nicht abgeglichen. Bitte erst abgleichen.';
  return {
    rows,
    editable,
    hint,
    error: edit?.error ?? null,
    dirty: Boolean(edit) && edit.dirty_version > edit.synced_version,
  };
}

// --- Benachrichtigungen (#331) -------------------------------------------------------------------

const PUSH_LABELS = { enable: 'Benachrichtigungen erlauben', disable: 'Ausschalten' };

/** Anzeige des Abschnitts „Benachrichtigungen“ im Reiter Verbindung. `desktopReady` heißt: die letzte
 *  Antwort trug einen `reminders`-Block (der Desktop kennt die Handy-Erinnerungen). */
export function pushModel({ state, lastError, desktopReady, canTest = false }) {
  const { text, action } = describeState(state, lastError);
  const hint = state === 'on' && !desktopReady
    ? ' Der Desktop sendet noch keine Erinnerungen für das Handy: dort „Auch aufs Handy senden“ einschalten und die Desktop-App aktualisieren.'
    : '';
  return { text: `${text}${hint}`, action, actionLabel: action ? PUSH_LABELS[action] : '', canTest: state === 'on' && canTest,
    // Schalter: Stellung und ob er sich umlegen lässt (gesperrt/nicht unterstützt: nur der Text).
    on: state === 'on', toggle: action !== null };
}

/** Kopf des Reiters „Verbindung“: erst der Zustand, dann der Desktop und wann zuletzt abgeglichen wurde. */
export function connectionSummary({ online, desktopName, lastSyncAt, tokenUntil, timeZone }) {
  const last = lastSyncAt ? localTime(lastSyncAt, timeZone) : '';
  const parts = [last ? `zuletzt abgeglichen um ${last}` : 'noch nicht abgeglichen'];
  if (tokenUntil) parts.push(`Kopplung gültig bis ${tokenUntil}`);
  return { pill: online ? 'Verbunden' : 'Offline', kind: online ? 'ok' : 'warn', name: desktopName || 'Desktop', detail: parts.join(' · ') };
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
export function unpairDialogModel({ reached, openDays = 0, desktopUnpair = false } = {}) {
  const open = Number.isInteger(openDays) && openDays > 0 ? openDays : 0;
  const summary = open > 0
    ? { kind: 'warn', text: open === 1 ? '1 Änderung ist noch nicht am Desktop.' : `${open} Änderungen sind noch nicht am Desktop.` }
    : { kind: 'ok', text: 'Alle Tage sind am Desktop gesichert.' };
  const notifiesDesktop = desktopUnpair === true && reached === true;
  return {
    summary,
    notifiesDesktop,
    warnDesktop: notifiesDesktop ? null
      : 'Der Desktop erfährt nichts vom Trennen. Das Gerät bleibt dort in der Liste, bis du es unter Einstellungen → Mobil entfernst oder widerrufst.',
    canRetry: open > 0,
    confirmLabel: open > 0 ? 'Trotzdem löschen' : 'Ja, trennen und löschen',
  };
}

/** Warnung im Reiter „Verbindung“, wenn der Browser die Daten nicht dauerhaft sichert (`persistent === false`);
 *  `refused`: die erneute Anfrage wurde abgelehnt, dann gibt es keinen Knopf mehr. */
export function storageNotice(persistent, { refused = false } = {}) {
  if (persistent !== false) return null;
  return refused
    ? { text: 'Der Browser hat die Anfrage abgelehnt. Hilfreich: die App zum Startbildschirm hinzufügen und regelmäßig abgleichen.', action: null }
    : { text: 'Der Browser sichert die Daten nicht dauerhaft. Nicht übertragene Einträge können bei Speichermangel verloren gehen.', action: 'persist' };
}
