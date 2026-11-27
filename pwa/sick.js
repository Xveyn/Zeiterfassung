// pwa/sick.js
// @ts-check
// Krankheitstage ohne DOM: der Block `sick` der Antwort (Fremddaten), Zeiträume, Blöcke und die
// lokale Sperre durch Ist-Zeit. Gegenstück zu `src/mobile_sick.py` (Form auf dem Draht) und
// `src/sick_days.py` (`clean_record`, `runs`). Die Minuten rechnet der Desktop; das Handy kennt
// weder Feiertage noch die Regel „Stunden je Krankheitstag“.
import { addDays, isIsoDate } from './minutes.js';

/** Längster Zeitraum, den das Handy auf einmal meldet (Gegenstück zu `sick_plan.MAX_BLOCK_DAYS`). */
export const MAX_SICK_BLOCK_DAYS = 366;

/** Höchstens so viele Minuten trägt ein Krankheitstag (Gegenstück zu `sick_days.MAX_MINUTES`). */
const MAX_MINUTES = 1440;

// Das feste Format des Desktops; nur damit ist der String-Vergleich der Stempel korrekt.
const STAMP_RE = /^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$/;

const isObject = (value) => value !== null && typeof value === 'object' && !Array.isArray(value);

/** @typedef {{ minutes: number, modified_at: string, deleted: boolean }} WireSickDay */

/** Der Block `sick` der Antwort: `null`, wenn er kein Objekt ist. Ein Tag braucht ein Datum, Minuten als ganze
 *  Zahl 0–1440, einen Stempel im Format des Desktops und `deleted` als Wahrheitswert, sonst entfällt er (wie
 *  `clean_record` am Desktop); unbekannte Felder entfallen, ein Tombstone trägt 0 Minuten.
 *  @param {unknown} raw
 *  @returns {Record<string, WireSickDay> | null} */
export function parseSickBlock(raw) {
  if (!isObject(raw)) return null;
  /** @type {Record<string, WireSickDay>} */
  const out = {};
  for (const [date, day] of Object.entries(/** @type {Record<string, unknown>} */ (raw))) {
    if (!isIsoDate(date) || !isObject(day)) continue;
    const { minutes, modified_at: stamp, deleted } = /** @type {Record<string, unknown>} */ (day);
    if (!Number.isInteger(minutes) || /** @type {number} */ (minutes) < 0 || /** @type {number} */ (minutes) > MAX_MINUTES) continue;
    if (typeof stamp !== 'string' || !STAMP_RE.test(stamp) || typeof deleted !== 'boolean') continue;
    out[date] = { minutes: deleted ? 0 : /** @type {number} */ (minutes), modified_at: stamp, deleted };
  }
  return out;
}

/** Alle Kalendertage von `from` bis `to` (einschließlich); leer, wenn der Zeitraum keinen Sinn ergibt.
 *  @param {string} from
 *  @param {string} to
 *  @returns {string[]} */
export function sickRange(from, to) {
  if (!isIsoDate(from) || !isIsoDate(to) || from > to) return [];
  const dates = [];
  for (let date = from; date <= to; date = addDays(date, 1)) dates.push(date);
  return dates;
}

/** Der Block um `date`: die lückenlose Folge lebender Krankheitstage, in der er liegt; `null`, wenn `date`
 *  kein lebender Krankheitstag ist. Ein Tombstone oder ein fehlender Tag beendet den Block.
 *  @param {Record<string, { deleted: boolean }>} days
 *  @param {string} date
 *  @returns {{ from: string, to: string, dates: string[] } | null} */
export function blockOf(days, date) {
  const live = (/** @type {string} */ day) => Object.hasOwn(days, day) && isObject(days[day]) && days[day].deleted === false;
  if (!isIsoDate(date) || !live(date)) return null;
  let from = date;
  while (live(addDays(from, -1))) from = addDays(from, -1);
  let to = date;
  while (live(addDays(to, 1))) to = addDays(to, 1);
  return { from, to, dates: sickRange(from, to) };
}

/** Ein Tag mit Slots, der nicht gelöscht ist (Ist-Zeit oder Reservierung). */
const hasSlots = (day) => isObject(day) && day.deleted !== true && Array.isArray(day.slots) && day.slots.length > 0;

/** Die Tage aus `dates`, an denen schon Ist-Zeit liegt: dort lässt sich keine Krankheit melden. Das Handy
 *  kennt die Minuten des Desktops nicht (Wochenende, Feiertag), es sperrt also jeden Tag mit Ist-Zeit.
 *  @param {string[]} dates
 *  @param {(date: string) => any} getDay
 *  @returns {string[]} */
export function workBlockedDates(dates, getDay) {
  return dates.filter((date) => hasSlots(getDay(date)));
}

/** Die Tage aus `dates` mit einer Reservierung (für „Reservierungen in diesem Zeitraum löschen“).
 *  @param {string[]} dates
 *  @param {(date: string) => any} getReservation
 *  @returns {string[]} */
export function reservationDatesIn(dates, getReservation) {
  return dates.filter((date) => hasSlots(getReservation(date)));
}
