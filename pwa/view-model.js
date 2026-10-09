// pwa/view-model.js
// Alles, was die Oberfläche anzeigt, als reine Daten: Wochenliste, Statuszeile, Hinweise,
// Konfliktliste, Editor-Zeilen. Kein DOM — die dünne Schicht in `views.js` macht daraus
// Elemente. Summen nur über ganze Minuten (`minutes.js`).
import {
  addDays, dayMinutes, formatDateDe, formatMinutes, isoWeek, mondayOf, normalizeSlots,
  validateSlots, weekDays,
} from './minutes.js';
import { describeError } from './messages.js';

export const WEEKDAYS = ['Mo', 'Di', 'Mi', 'Do', 'Fr', 'Sa', 'So'];
const SKEW_WARN_MS = 120000;
// Wie `store.js`: Tage nach heute + 1 räumt der Abgleich am Handy wieder auf (#265).
const VISIBLE_AHEAD_DAYS = 1;

const isObject = (value) => value !== null && typeof value === 'object' && !Array.isArray(value);

export function slotText(slot) {
  const pause = Number.isInteger(slot.pause) && slot.pause > 0 ? ` · ${slot.pause} min Pause` : '';
  const category = typeof slot.kategorie === 'string' && slot.kategorie ? ` · ${slot.kategorie}` : '';
  return `${slot.start}–${slot.end}${pause}${category}`;
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

export function weekModel({ getDay, anchor, today, conflictDates = [], windowDays = 0 }) {
  const conflicts = new Set(conflictDates);
  const dates = weekDays(anchor);
  const week = dates.map((date, index) => {
    const day = getDay(date);
    const cleared = Boolean(day?.deleted);
    const slots = day && !cleared ? day.slots : [];
    const minutes = dayMinutes(slots);
    return {
      date,
      weekday: WEEKDAYS[index],
      label: formatDateDe(date),
      isToday: date === today,
      isWeekend: index >= 5,
      beyondWindow: date > addDays(today, VISIBLE_AHEAD_DAYS),
      // Außerhalb dessen, was das Handy vom Desktop kennt: ein leer wirkender Tag kann dort Einträge
      // haben, und Speichern ersetzt sie (der Handy-Stand gewinnt ohne Konflikt).
      outsideWindow: date > addDays(today, VISIBLE_AHEAD_DAYS) || (windowDays > 0 && date < addDays(today, -windowDays)),
      slots: slots.map(slotText),
      minutes,
      minutesLabel: minutes > 0 ? formatMinutes(minutes) : '',
      state: !day ? 'empty' : cleared ? 'cleared' : 'filled',
      dirty: Boolean(day?.dirty),
      error: day?.error ?? null,
      conflict: conflicts.has(date),
    };
  });
  const total = week.reduce((sum, day) => sum + day.minutes, 0);
  return {
    title: `KW ${isoWeek(anchor).week}`,
    range: `${formatDateDe(dates[0]).slice(0, 6)}–${formatDateDe(dates[6])}`,
    anchor: mondayOf(anchor),
    isCurrent: dates.includes(today),
    days: week,
    totalMinutes: total,
    totalLabel: formatMinutes(total),
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

export function hintsModel({ lastError, excluded, skewMs, persistent, updateReady, conflictCount, errorDays }) {
  const hints = [];
  if (lastError) {
    const { text, action } = describeError(lastError);
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
  if (persistent === false) {
    hints.push({ id: 'storage', kind: 'warn', action: null,
      text: 'Der Browser sichert die Daten nicht dauerhaft. Nicht übertragene Einträge können bei Speichermangel verloren gehen.' });
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

export function blankRow(previous) {
  const start = previous && previous.end ? previous.end : '';
  return { start, end: '', pause: '0', kategorie: previous?.kategorie ?? '' };
}

export function editorRows(day) {
  if (!day || day.deleted || day.slots.length === 0) return [blankRow()];
  return day.slots.map((slot) => ({
    start: slot.start, end: slot.end, pause: String(slot.pause ?? 0), kategorie: slot.kategorie ?? '',
  }));
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
