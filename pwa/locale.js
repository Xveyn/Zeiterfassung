// @ts-check
// pwa/locale.js
// Locale der Oberfläche (BCP-47-Tag aus Sprache und Land, z. B. `de-DE`) und die Formatierer für
// Datum und Uhrzeit. Ein Tag, kein eigener Datumsformat-Schalter: das Format folgt Sprache + Land.
// `Intl` wirft bei kaputten Tags `RangeError` (auch `supportedLocalesOf`), deshalb prüft `localeTag`
// per Regex und jeder Formatierer fängt den Wurf und fällt auf `DEFAULT_LOCALE`.

export const DEFAULT_LOCALE = 'de-DE';
const TAG_RE = /^[a-z]{2,3}(-[A-Z]{2})?$/;
const ISO_RE = /^[0-9]{4}-[0-9]{2}-[0-9]{2}$/;

/** @param {string} tag */
function safeTag(tag) {
  if (!TAG_RE.test(tag)) return DEFAULT_LOCALE;
  try {
    return Intl.DateTimeFormat.supportedLocalesOf([tag]).length ? tag : DEFAULT_LOCALE;
  } catch (error) {
    console.debug('locale: unbrauchbarer Tag', error);
    return DEFAULT_LOCALE;
  }
}

/** Sprache + Land → Tag. Alles Unbrauchbare ergibt `de-DE`; wirft nie.
 *  @param {unknown} language @param {unknown} country @returns {string} */
export function localeTag(language, country) {
  if (typeof language !== 'string' || typeof country !== 'string') return DEFAULT_LOCALE;
  return safeTag(`${language}-${country}`);
}

let current = DEFAULT_LOCALE;

/** Setzt die Locale der Oberfläche; ein unbrauchbarer Tag lässt `de-DE`.
 *  @param {string} tag @returns {void} */
export function setLocale(tag) {
  current = typeof tag === 'string' ? safeTag(tag) : DEFAULT_LOCALE;
}

/** @returns {string} */
export function getLocale() {
  return current;
}

/** @param {string} tag @param {Intl.DateTimeFormatOptions} options @param {Date} date */
function format(tag, options, date) {
  try {
    return new Intl.DateTimeFormat(tag, options).format(date);
  } catch (error) {
    console.debug('locale: Formatierung fiel auf de-DE zurück', error);
    return new Intl.DateTimeFormat(DEFAULT_LOCALE, options).format(date);
  }
}

/** @param {string} iso */
function utcDate(iso) {
  const [year, month, day] = iso.split('-').map(Number);
  return new Date(Date.UTC(year, month - 1, day));
}

/** ISO-Datum → Anzeige (`de-DE`: `TT.MM.JJJJ`). Was kein ISO-Datum ist, bleibt, wie es ist.
 *  @param {string} iso @param {string} [tag] @returns {string} */
export function formatDate(iso, tag = current) {
  if (typeof iso !== 'string' || !ISO_RE.test(iso)) return iso;
  return format(tag, { day: '2-digit', month: '2-digit', year: 'numeric', timeZone: 'UTC' }, utcDate(iso));
}

/** Kurzdatum ohne Jahr (`de-DE`: `02.06.`).
 *  @param {string} iso @param {string} [tag] @returns {string} */
export function formatDateShort(iso, tag = current) {
  if (typeof iso !== 'string' || !ISO_RE.test(iso)) return iso;
  return format(tag, { day: '2-digit', month: '2-digit', timeZone: 'UTC' }, utcDate(iso));
}

/** Uhrzeit eines Zeitpunkts (ms seit Epoche) in `timeZone` (leer = Zeitzone des Geräts).
 *  @param {number} time @param {string | undefined} timeZone @param {string} [tag] @returns {string} */
export function formatClock(time, timeZone, tag = current) {
  return format(tag, { hour: '2-digit', minute: '2-digit', timeZone }, new Date(time));
}

/** Kurzer Wochentagsname (0 = Montag) in der Locale.
 *  @param {number} index @param {string} [tag] @returns {string} */
export function weekdayShort(index, tag = current) {
  return format(tag, { weekday: 'short', timeZone: 'UTC' }, new Date(Date.UTC(2024, 0, 1 + index)));
}
