// @ts-check
// pwa/language.js
// Sprache und Land der PWA: die Sprache gehört der PWA (eigene Einstellung), der Desktop liefert nur den
// Vorschlag beim ersten Koppeln; das Land kommt immer vom Desktop. Ohne Desktop-Angaben gilt `de`/`DE`.
import { DEFAULT_LANGUAGE, normalizeLanguage, setLanguage } from './i18n.js';
import { localeTag, setLocale } from './locale.js';

export const DEFAULT_COUNTRY = 'DE';
const COUNTRY_RE = /^[A-Z]{2}$/;

/** @param {unknown} value @returns {string} ein ISO-Ländercode oder '' */
export function cleanCountry(value) {
  return typeof value === 'string' && COUNTRY_RE.test(value) ? value : '';
}

/**
 * Was der Desktop an Sprache und Land in die Meta übernimmt. `language` nur, solange die PWA nie eine gewählt hat
 * (`null`) und der Desktop eine nennt; `country` folgt dem Desktop, fehlt es, bleibt der Stand.
 * @param {{ language?: string | null, country?: string }} meta
 * @param {{ language?: string, country?: string } | null | undefined} desktop
 * @returns {{ language: string | null, country: string }}
 */
export function adoptDesktopLanguage(meta, desktop) {
  const offered = typeof desktop?.language === 'string' && desktop.language ? normalizeLanguage(desktop.language) : null;
  const language = meta.language ?? offered;
  const country = cleanCountry(desktop?.country) || cleanCountry(meta.country) || DEFAULT_COUNTRY;
  return { language, country };
}

/** Setzt Textsprache und Datums-Locale nach der Meta; eine Meta ohne die Felder (ältere PWA) gilt als `de`/`DE`.
 *  @param {{ language?: string | null, country?: string }} meta */
export function applyLocale(meta) {
  const language = meta.language ?? DEFAULT_LANGUAGE;
  setLanguage(language);
  setLocale(localeTag(normalizeLanguage(language), meta.country));
}
