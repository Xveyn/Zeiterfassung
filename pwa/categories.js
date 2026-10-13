// pwa/categories.js
// Kategorien und ihre Standardzeiten ohne DOM: Zeilen für den Editor, der Block für den Abgleich,
// die Prüfung und die Kurzfassung. Gegenstück zu `src/mobile_settings.py` (Prüfung der Anfrage) und
// zu `collect_categories` am Desktop. Eine Kategorie im Modus „pro Wochentag“ (`per_day`) bearbeitet
// die PWA nicht: ihr Eintrag wandert unverändert durch (`raw`).
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
  if (rows.length > MAX_CATEGORIES) return { ok: false, message: `Höchstens ${MAX_CATEGORIES} Kategorien.` };
  const seen = new Set();
  for (const row of rows) {
    const name = row.name.trim();
    if (name === '') return { ok: false, message: 'Der Name einer Kategorie darf nicht leer sein.' };
    if ([...name].length > MAX_NAME_LENGTH) {
      return { ok: false, message: `Der Name „${name.slice(0, 20)}…“ ist länger als ${MAX_NAME_LENGTH} Zeichen (höchstens ${MAX_NAME_LENGTH}).` };
    }
    if ([...name].some(isControl)) return { ok: false, message: `Der Name „${name}“ enthält ungültige Zeichen.` };
    if (seen.has(name)) return { ok: false, message: `Der Name „${name}“ kommt doppelt vor.` };
    seen.add(name);
    if (row.mode === 'per_day') continue;
    const start = row.start === '' ? null : parseTime(row.start);
    const end = row.end === '' ? null : parseTime(row.end);
    if (row.start !== '' && start === null) return { ok: false, message: `„${name}“: Start muss HH:MM sein.` };
    if (row.end !== '' && end === null) return { ok: false, message: `„${name}“: Ende muss HH:MM sein.` };
    if (start !== null && end !== null && end <= start) {
      return { ok: false, message: `„${name}“: Ende muss nach dem Start liegen. Ende und Start tauschen oder eine Zeit leeren.` };
    }
    if (row.pause !== '') {
      const pause = Number(row.pause);
      if (!/^[0-9]+$/.test(row.pause) || !Number.isInteger(pause) || pause > MAX_PAUSE) {
        return { ok: false, message: `„${name}“: Pause muss eine ganze Zahl von 0 bis ${MAX_PAUSE} Minuten sein.` };
      }
    }
  }
  return { ok: true, message: '' };
}

/** Die Zeiten einer Zeile in einer kurzen Zeile. */
export function timesSummary(row) {
  if (row.mode === 'per_day') return 'pro Wochentag';
  const parts = [];
  if (row.start && row.end) parts.push(`${row.start}–${row.end}`);
  else if (row.start) parts.push(`ab ${row.start}`);
  else if (row.end) parts.push(`bis ${row.end}`);
  if (row.pause !== '') parts.push(`${row.pause} min Pause`);
  return parts.length ? parts.join(', ') : '—';
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
