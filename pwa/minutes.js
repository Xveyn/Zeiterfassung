// pwa/minutes.js
// Rechenregeln der Handy-Erfassung: Zeiten, Minuten, Validierung, Datum. Rein, ohne DOM.
//
// Summen laufen NUR über ganze Minuten je Slot, nie über Dezimalstunden — dieselbe Regel
// wie am Desktop (`time_utils.hours_to_minutes`). Die Validierung entspricht dem Server
// (`api_entry_write.parse_slots`), die Meldungen der Zeitregeln sind wortgleich mit
// `time_utils.validate_slots`. Beides prüft `tests/test_mobile_contract.py` gegen
// `test/fixtures/minutes-cases.json`.

import { formatDate } from './locale.js';
import { t } from './i18n.js';

export const MAX_SLOTS = 50;
export const MAX_CATEGORY_LENGTH = 100;
const MAX_PAUSE_MINUTES = 24 * 60;
const TIME_RE = /^[0-9]{2}:[0-9]{2}$/;
const DATE_RE = /^[0-9]{4}-[0-9]{2}-[0-9]{2}$/;
const DAY_MS = 86400000;

/** `HH:MM` (genau zwei Ziffern je Teil) → Minuten seit 0:00, sonst `null`. */
export function parseTime(text) {
  if (typeof text !== 'string' || !TIME_RE.test(text)) return null;
  const hours = Number(text.slice(0, 2));
  const minutes = Number(text.slice(3));
  if (hours > 23 || minutes > 59) return null;
  return hours * 60 + minutes;
}

/** Schrittweite der Zeitauswahl: 5 Minuten wie am Desktop (`theme.palette.TIME_VALUES`). */
export const TIME_STEP_MINUTES = 5;

/** Rundet `HH:MM` auf das nächste Vielfache von `step` Minuten; nach 23:55 gibt es keinen Schritt mehr
 *  (`24:00` ist keine Uhrzeit). Leeres oder unbrauchbares bleibt unverändert, das prüft die Validierung. */
export function snapTime(text, step = TIME_STEP_MINUTES) {
  const total = parseTime(text);
  if (total === null) return text;
  const snapped = Math.min(Math.round(total / step) * step, Math.floor(1439 / step) * step);
  return `${String(Math.floor(snapped / 60)).padStart(2, '0')}:${String(snapped % 60).padStart(2, '0')}`;
}

/** Rundet eine Pause in ganzen Minuten auf das nächste Vielfache von `step` (Desktop: 0–120 in 5er-Schritten,
 *  `theme.palette.PAUSE_VALUES`). Leeres oder unbrauchbares bleibt unverändert, das prüft die Validierung. */
export function snapPause(text, step = TIME_STEP_MINUTES) {
  if (typeof text !== 'string' || !/^\d+$/.test(text)) return text;
  return String(Math.round(Number(text) / step) * step);
}

function usablePause(pause) {
  return Number.isInteger(pause) && pause >= 0 && pause <= MAX_PAUSE_MINUTES ? pause : 0;
}

/** Netto-Minuten eines Slots. Ein unbrauchbarer Slot zählt 0, eine unbrauchbare Pause 0
 *  (wie `storage.sanitize_slot` am Desktop): die Anzeige darf nie werfen. */
export function slotMinutes(slot) {
  const start = parseTime(slot?.start);
  const end = parseTime(slot?.end);
  if (start === null || end === null) return 0;
  return Math.max(0, end - start - usablePause(slot.pause));
}

export function dayMinutes(slots) {
  return slots.reduce((sum, slot) => sum + slotMinutes(slot), 0);
}

/** Ganze Minuten → `h:mm` (`7:30`, `0:05`, `100:00`). */
export function formatMinutes(total) {
  const whole = Math.max(0, Math.trunc(total));
  return `${Math.floor(whole / 60)}:${String(whole % 60).padStart(2, '0')}`;
}

/** Aus Formularwerten die vier Felder des Protokolls machen (Standard: Pause 0, Kategorie
 *  leer, Kategorie getrimmt wie am Server). Unbrauchbares bleibt unverändert und fällt
 *  in `validateSlots` auf. */
export function normalizeSlots(raw) {
  if (!Array.isArray(raw)) return [];
  return raw.map((item) => {
    if (item === null || typeof item !== 'object') return item;
    const kategorie = item.kategorie === undefined || item.kategorie === null ? '' : item.kategorie;
    return {
      start: item.start,
      end: item.end,
      pause: item.pause === undefined ? 0 : item.pause,
      kategorie: typeof kategorie === 'string' ? kategorie.trim() : kategorie,
    };
  });
}

function hasForbiddenCharacter(text) {
  // `for…of` zählt Code Points: ein einzelnes Surrogat bleibt ein eigenes Element.
  for (const character of text) {
    const code = character.codePointAt(0);
    if (code <= 0x1f || (code >= 0x7f && code <= 0x9f) || (code >= 0xd800 && code <= 0xdfff)) {
      return true;
    }
  }
  return false;
}

const fail = (message) => ({ ok: false, message });

/** Prüft normalisierte Slots; liefert `{ok, message}` (`message` leer bei `ok`). */
export function validateSlots(slots) {
  if (!Array.isArray(slots)) return fail(t('slots.fehler.ungueltig'));
  if (slots.length === 0) {
    return fail(t('slots.fehler.mindestens_einer'));
  }
  if (slots.length > MAX_SLOTS) return fail(t('slots.fehler.zu_viele', { max: MAX_SLOTS }));
  for (const slot of slots) {
    if (slot === null || typeof slot !== 'object') return fail(t('slots.fehler.slot_ungueltig'));
    const start = parseTime(slot.start);
    if (start === null) return fail(t('slots.fehler.start'));
    const end = parseTime(slot.end);
    if (end === null) return fail(t('slots.fehler.ende'));
    if (end <= start) return fail(t('slots.fehler.ende_nach_start'));
    if (!Number.isInteger(slot.pause)) return fail(t('slots.fehler.pause_ganzzahl'));
    if (slot.pause < 0) return fail(t('slots.fehler.pause_negativ'));
    const working = end - start;
    if (slot.pause >= working) {
      return fail(t('slots.fehler.pause_zu_lang', { pause: slot.pause, arbeit: working }));
    }
    if (typeof slot.kategorie !== 'string') return fail(t('slots.fehler.kategorie_text'));
    if ([...slot.kategorie].length > MAX_CATEGORY_LENGTH) {
      return fail(t('slots.fehler.kategorie_laenge', { max: MAX_CATEGORY_LENGTH }));
    }
    if (hasForbiddenCharacter(slot.kategorie)) return fail(t('slots.fehler.kategorie_zeichen'));
  }
  const intervals = slots.map((slot) => [parseTime(slot.start), parseTime(slot.end)])
    .sort((a, b) => a[0] - b[0] || a[1] - b[1]);
  for (let i = 1; i < intervals.length; i += 1) {
    if (intervals[i][0] < intervals[i - 1][1]) {
      return fail(t('slots.fehler.ueberlappung'));
    }
  }
  return { ok: true, message: '' };
}

// --- Datum ---------------------------------------------------------------------------------------

/** Kalenderdatum `YYYY-MM-DD` im Bereich 2000 bis 2100 (wie `check_date_range` am Server). */
export function isIsoDate(text) {
  if (typeof text !== 'string' || !DATE_RE.test(text)) return false;
  const [year, month, day] = text.split('-').map(Number);
  if (year < 2000 || year > 2100) return false;
  const date = new Date(Date.UTC(year, month - 1, day));
  return date.getUTCFullYear() === year && date.getUTCMonth() === month - 1
    && date.getUTCDate() === day;
}

function toUtc(iso) {
  const [year, month, day] = iso.split('-').map(Number);
  return new Date(Date.UTC(year, month - 1, day));
}

/** `iso` plus `n` Tage, gerechnet in UTC (keine Sommerzeit-Sprünge). */
export function addDays(iso, n) {
  const date = toUtc(iso);
  date.setUTCDate(date.getUTCDate() + n);
  return date.toISOString().slice(0, 10);
}

export function mondayOf(iso) {
  return addDays(iso, -((toUtc(iso).getUTCDay() + 6) % 7));
}

export function weekDays(iso) {
  const monday = mondayOf(iso);
  return Array.from({ length: 7 }, (_, i) => addDays(monday, i));
}

/** ISO-Kalenderwoche (Woche mit dem ersten Donnerstag). */
export function isoWeek(iso) {
  const thursday = toUtc(addDays(iso, 3 - ((toUtc(iso).getUTCDay() + 6) % 7)));
  const year = thursday.getUTCFullYear();
  const firstThursday = toUtc(`${year}-01-04`);
  const offset = (firstThursday.getUTCDay() + 6) % 7;
  const week = 1 + Math.round(((thursday - firstThursday) / DAY_MS - 3 + offset) / 7);
  return { year, week };
}

export function formatDateDe(iso) {
  return isIsoDate(iso) ? formatDate(iso) : iso;
}

/** Lokales Datum des Handys als ISO. */
export function localIsoDate(date) {
  const pad = (n) => String(n).padStart(2, '0');
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
}

/** UTC-Zeitstempel im festen Format `YYYY-MM-DDTHH:MM:SSZ` (nur dann ist der String-Vergleich
 *  korrekt — die LWW-Entscheidung am Desktop hängt daran). */
export function utcStamp(date) {
  return `${date.toISOString().slice(0, 19)}Z`;
}
