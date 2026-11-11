// pwa/categories.js
// Kategorien und ihre Standardzeiten ohne DOM: Zeilen für den Editor, der Block für den Abgleich,
// die Prüfung und die Kurzfassung. Gegenstück zu `src/mobile_settings.py` (Prüfung der Anfrage) und
// zu `collect_categories` am Desktop. Eine Kategorie im Modus „pro Wochentag“ (`per_day`) bearbeitet
// die PWA nicht: ihr Eintrag wandert unverändert durch (`raw`).
import { t } from './i18n.js';
import { parseTime } from './minutes.js';

export const MAX_CATEGORIES = 100;
export const MAX_NAME_LENGTH = 100;
export const MAX_PAUSE = 1440;

const isObject = (value) => value !== null && typeof value === 'object' && !Array.isArray(value);
const hasOwn = (object, key) => Object.hasOwn(object, key);

/** Namen in Reihenfolge → Editor-Zeilen; Zeiten als Text (`''` = Standard). */
export function categoryRows(categories, categoryTimes) {
  const times = isObject(categoryTimes) ? categoryTimes : {};
  return categories.map((name) => {
    const entry = hasOwn(times, name) && isObject(times[name]) ? times[name] : null;
    if (entry && entry.mode === 'per_day') {
      return { name, mode: 'per_day', start: '', end: '', pause: '', raw: structuredClone(entry) };
    }
    return {
      name, mode: 'general', raw: null,
      start: entry?.start ?? '', end: entry?.end ?? '',
      pause: Number.isInteger(entry?.pause) ? String(entry.pause) : '',
    };
  });
}

/** Zeilen → Block für den Desktop: getrimmte Namen, `per_day` unverändert, leere Zeiten entfallen. */
export function rowsToBlock(rows) {
  const categories = [];
  const category_times = {};
  for (const row of rows) {
    const name = row.name.trim();
    categories.push(name);
    if (row.mode === 'per_day') {
      category_times[name] = structuredClone(row.raw);
      continue;
    }
    const entry = {};
    if (row.start !== '') entry.start = row.start;
    if (row.end !== '') entry.end = row.end;
    if (row.pause !== '') entry.pause = Number(row.pause);
    if (Object.keys(entry).length > 0) category_times[name] = entry;
  }
  return { categories, category_times };
}

function isControl(character) {
  const code = character.codePointAt(0);
  return code < 0x20 || (code >= 0x7f && code <= 0x9f) || (code >= 0xd800 && code <= 0xdfff);
}

/** Prüft die Zeilen wie der Server (`mobile_settings`), dazu: Ende nach Start, wenn beide gesetzt sind.
 *  Uhrzeiten prüft `parseTime` streng (genau `HH:MM`, also nicht `9:00`). */
export function validateCategoryRows(rows) {
  if (rows.length > MAX_CATEGORIES) return { ok: false, message: t('kategorien.pruefung.zu_viele', { max: MAX_CATEGORIES }) };
  const seen = new Set();
  for (const row of rows) {
    const name = row.name.trim();
    if (name === '') return { ok: false, message: t('kategorien.pruefung.name_leer') };
    if ([...name].length > MAX_NAME_LENGTH) {
      return { ok: false, message: t('kategorien.pruefung.name_zu_lang', { name: name.slice(0, 20), max: MAX_NAME_LENGTH }) };
    }
    if ([...name].some(isControl)) return { ok: false, message: t('kategorien.pruefung.name_zeichen', { name }) };
    if (seen.has(name)) return { ok: false, message: t('kategorien.pruefung.name_doppelt', { name }) };
    seen.add(name);
    if (row.mode === 'per_day') continue;
    const start = row.start === '' ? null : parseTime(row.start);
    const end = row.end === '' ? null : parseTime(row.end);
    if (row.start !== '' && start === null) return { ok: false, message: t('kategorien.pruefung.start_format', { name }) };
    if (row.end !== '' && end === null) return { ok: false, message: t('kategorien.pruefung.ende_format', { name }) };
    if (start !== null && end !== null && end <= start) {
      return { ok: false, message: t('kategorien.pruefung.ende_nach_start', { name }) };
    }
    if (row.pause !== '') {
      const pause = Number(row.pause);
      if (!/^[0-9]+$/.test(row.pause) || !Number.isInteger(pause) || pause > MAX_PAUSE) {
        return { ok: false, message: t('kategorien.pruefung.pause', { name, max: MAX_PAUSE }) };
      }
    }
  }
  return { ok: true, message: '' };
}

const DAY_ORDER = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun'];

/** Kurzname des Wochentags nach Position in `DAY_ORDER`, zum Aufrufzeitpunkt in der gewählten Sprache. */
function dayName(index) {
  return [t('woche.tag.kurz.mo'), t('woche.tag.kurz.di'), t('woche.tag.kurz.mi'), t('woche.tag.kurz.do'),
    t('woche.tag.kurz.fr'), t('woche.tag.kurz.sa'), t('woche.tag.kurz.so')][index];
}

function clockText(day) {
  if (day.start && day.end) return `${day.start}–${day.end}`;
  if (day.start) return t('kategorien.zeit.ab', { zeit: day.start });
  if (day.end) return t('kategorien.zeit.bis', { zeit: day.end });
  return '';
}

/** Tage mit gleichen Zeiten zusammengefasst, aufeinanderfolgende als Bereich: „Mo–Do 09:00–17:00 · Fr 07:00–11:00“,
 *  „Mo, Mi 09:00–17:00“. Nur Tage mit eigenen Zeiten (für die übrigen gilt der globale Standard); `''` ohne solche.
 *  Fremddaten: wirft nie. */
function perDayText(raw) {
  const days = isObject(raw?.days) ? raw.days : {};
  const groups = new Map();
  DAY_ORDER.forEach((key, index) => {
    const text = isObject(days[key]) ? clockText(days[key]) : '';
    if (text) groups.set(text, [...(groups.get(text) ?? []), index]);
  });
  const names = (indexes) => {
    const runs = [];
    for (const index of indexes) {
      const run = runs.at(-1);
      if (run && run.at(-1) === index - 1) run.push(index); else runs.push([index]);
    }
    return runs.map((run) => (run.length > 2 ? `${dayName(run[0])}–${dayName(run.at(-1))}`
      : run.map((index) => dayName(index)).join(', '))).join(', ');
  };
  return [...groups].map(([text, indexes]) => `${names(indexes)} ${text}`).join(' · ');
}

/** Die Zeiten einer Zeile in einer kurzen Zeile. Auch „pro Wochentag“ ist lesbar (am Handy nicht bearbeitbar). */
export function timesSummary(row) {
  if (row.mode === 'per_day') {
    const parts = [perDayText(row.raw) || t('kategorien.pro_wochentag')];
    if (Number.isInteger(row.raw?.pause)) parts.push(t('kategorien.pause_min', { min: row.raw.pause }));
    return parts.join(', ');
  }
  const parts = [];
  if (row.start && row.end) parts.push(`${row.start}–${row.end}`);
  else if (row.start) parts.push(t('kategorien.zeit.ab', { zeit: row.start }));
  else if (row.end) parts.push(t('kategorien.zeit.bis', { zeit: row.end }));
  if (row.pause !== '') parts.push(t('kategorien.pause_min', { min: row.pause }));
  return parts.length ? parts.join(', ') : t('kategorien.keine_standardzeiten');
}

/** Vertauscht die Zeile mit ihrem Nachbarn; eine ungültige Bewegung gibt das Original zurück. */
export function moveRow(rows, index, direction) {
  const target = index + direction;
  if (target < 0 || target >= rows.length) return rows;
  const next = [...rows];
  [next[index], next[target]] = [next[target], next[index]];
  return next;
}

function stable(value) {
  if (Array.isArray(value)) return value.map(stable);
  if (isObject(value)) return Object.fromEntries(Object.keys(value).sort().map((key) => [key, stable(value[key])]));
  return value;
}

/** Gleichheit zweier Blöcke: Reihenfolge der Namen zählt, die Schlüsselreihenfolge der Zeiten nicht. */
export function blockSignature(categories, categoryTimes) {
  return JSON.stringify([categories, stable(categoryTimes ?? {})]);
}
