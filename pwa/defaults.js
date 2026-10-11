// pwa/defaults.js
// Standardzeiten des Desktops (#288): Wochentag-Standards, globale Pause und die Zeiten je Kategorie.
// `resolveSlotDefaults` ist das Gegenstück zu `src/category_defaults.resolve_slot_defaults`; der
// Gleichlauf hängt an `test/fixtures/category-defaults-cases.json`, das der JS- und der Python-Test
// lesen. Wer die Auflösung ändert, ändert beide Seiten und das Fixture.
// Alles hier ist DOM-frei. Die Daten kommen vom Desktop, können aber von einer anderen Version stammen
// oder fehlen: `parseDefaults` verwirft Ungültiges feldweise (kein Protokollfehler — die Vorbelegung ist
// ein Komfort, ein kaputtes Feld darf den Abgleich nicht blockieren).

export const WEEKDAY_KEYS = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun'];
const CLOCK_RE = /^([01]\d|2[0-3]):[0-5]\d$/;
const MAX_PAUSE = 24 * 60;
const MAX_TEXT = 100;

const isObject = (value) => value !== null && typeof value === 'object' && !Array.isArray(value);
const clock = (value) => (typeof value === 'string' && CLOCK_RE.test(value) ? value : '');
const pauseOf = (value) => (Number.isInteger(value) && value >= 0 && value <= MAX_PAUSE ? value : null);

/** Wochentag-Schlüssel des Desktops (`mon` … `sun`) zu einem ISO-Datum. */
export function weekdayKey(iso) {
  return WEEKDAY_KEYS[(new Date(`${iso}T00:00:00Z`).getUTCDay() + 6) % 7];
}

function parseClocks(raw, into) {
  if (!isObject(raw)) return into;
  for (const field of ['start', 'end']) {
    const value = clock(raw[field]);
    if (value) into[field] = value;
  }
  return into;
}

function parseCategory(raw) {
  const out = {};
  if (raw.mode === 'per_day') {
    out.mode = 'per_day';
    out.days = {};
    if (isObject(raw.days)) {
      for (const key of WEEKDAY_KEYS) {
        if (Object.hasOwn(raw.days, key)) out.days[key] = parseClocks(raw.days[key], {});
      }
    }
  } else {
    parseClocks(raw, out);
  }
  const pause = pauseOf(raw.pause);
  if (pause !== null) out.pause = pause;
  return out;
}

/** Prüft das `defaults`-Feld der Sync-Antwort. `null`, wenn es fehlt (älterer Desktop) oder kein
 *  Dokument ist — die PWA belegt dann nichts vor, wie vor #288. */
export function parseDefaults(raw) {
  const pause = isObject(raw) ? pauseOf(raw.pause) : null;
  if (pause === null || !isObject(raw.weekdays) || !isObject(raw.category_times)) return null;
  const weekdays = {};
  for (const key of WEEKDAY_KEYS) {
    if (Object.hasOwn(raw.weekdays, key)) {
      const day = isObject(raw.weekdays[key]) ? raw.weekdays[key] : {};
      weekdays[key] = { start: clock(day.start), end: clock(day.end) };
    }
  }
  const category_times = {};
  for (const [name, entry] of Object.entries(raw.category_times)) {
    if (name.length <= MAX_TEXT && name !== '__proto__' && isObject(entry)) {
      Object.defineProperty(category_times, name, {
        value: parseCategory(entry), enumerable: true, writable: true, configurable: true,
      });
    }
  }
  return { pause, weekdays, category_times };
}

/** Name, Version und Plattform des Desktops für den Verbindungsdialog; Ungültiges wird leer. */
export function parseDesktopInfo(raw) {
  const text = (value) => (typeof value === 'string' && value.length <= MAX_TEXT ? value : '');
  const info = isObject(raw) ? raw : {};
  return { name: text(info.name), version: text(info.version), platform: text(info.platform) };
}

/** Start, Ende und Pause für einen Slot der Kategorie (`''` = keine) an einem Wochentag. Ein leeres
 *  oder fehlendes Feld fällt einzeln auf den globalen Standard zurück; Pause 0 ist ein gültiger Wert. */
export function resolveSlotDefaults(defaults, kategorie, weekday) {
  const day = Object.hasOwn(defaults.weekdays, weekday) ? defaults.weekdays[weekday] : {};
  const global = { start: day.start || '', end: day.end || '', pause: defaults.pause };
  const entry = kategorie && Object.hasOwn(defaults.category_times, kategorie)
    ? defaults.category_times[kategorie] : null;
  if (!entry) return global;
  const source = entry.mode === 'per_day'
    ? (entry.days && Object.hasOwn(entry.days, weekday) ? entry.days[weekday] : {})
    : entry;
  return {
    start: source.start || global.start,
    end: source.end || global.end,
    pause: entry.pause ?? global.pause,
  };
}
