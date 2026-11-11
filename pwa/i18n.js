// @ts-check
// pwa/i18n.js
// Textschicht: `t('schlüssel', {param})` liefert den Text der gewählten Sprache. Schlüssel stehen
// nur als Literal im Aufruf (die Ratsche in test/i18n-literals.test.js liest sie am Quelltext).
// Läuft auch im Service Worker (eigene Modulinstanz, kein `document`).
import de from './i18n/de.js';

export const DEFAULT_LANGUAGE = 'de';

/** @type {Record<string, Record<string, string>>} */
const CATALOGS = { de };

/** Die wählbaren Sprachen (Codes der Kataloge). */
export const LANGUAGES = Object.keys(CATALOGS);

let current = DEFAULT_LANGUAGE;

/** Ein Sprachcode des Katalogs; alles andere (auch `de-AT`, Groß-/Kleinschreibung) fällt auf den Basiscode, sonst Deutsch.
 * @param {unknown} value */
export function normalizeLanguage(value) {
  if (typeof value !== 'string') return DEFAULT_LANGUAGE;
  const base = value.trim().toLowerCase().split(/[-_]/)[0];
  return Object.hasOwn(CATALOGS, base) ? base : DEFAULT_LANGUAGE;
}

/** @param {string} lang */
export function setLanguage(lang) {
  current = normalizeLanguage(lang);
  try {
    if (typeof document !== 'undefined' && document.documentElement) document.documentElement.lang = current;
  } catch (error) {
    console.warn('[Zeiterfassung] lang nicht gesetzt', error);   // Anzeige-Attribut; die Sprache gilt trotzdem
  }
}

export function getLanguage() {
  return current;
}

/**
 * @param {string} key
 * @param {Record<string, string | number>} [params]
 */
export function t(key, params) {
  const text = CATALOGS[current]?.[key] ?? CATALOGS[DEFAULT_LANGUAGE][key];
  if (typeof text !== 'string') {
    console.warn(`[Zeiterfassung] Text fehlt im Katalog: ${key}`);
    return key;
  }
  if (!params) return text;
  return text.replace(/\{(\w+)\}/g, (whole, name) => (Object.hasOwn(params, name) ? String(params[name]) : whole));
}
