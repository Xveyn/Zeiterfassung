// pwa/window-policy.js
// Lesefenster der PWA (#250): welche Stufe wird gewünscht, wann zeigt die Wochenansicht „Ältere Zeiten
// laden“, und was sagt sie, wenn der Desktop nicht mehr liefert? Reine Entscheidungen ohne Browser-API
// (getestet in test/window-policy.test.js). Das Fenster selbst bestimmt immer der Desktop: die Antwort
// nennt das gewährte `window_days` und die Obergrenze `window_max_days`.
import { isIsoDate } from './minutes.js';

export const WINDOW_STEPS = [90, 180, 365];
export const DEFAULT_WISH = 90;

/** Wie weit nach heute das Handy Ist-Zeiten kennt (#265): das Fenster nach vorn, das der Desktop
 *  mitschickt (`window_ahead_days`). Ein Desktop ohne das Feld liefert nichts nach heute; die PWA
 *  zeigt und behält dann nur noch heute + 1 (Spielraum für eine um einen Tag vorgehende Handy-Uhr). */
export const LEGACY_AHEAD_DAYS = 1;
export function aheadDays(value) {
  return Number.isInteger(value) && value >= 1 ? value : LEGACY_AHEAD_DAYS;
}

/** Kalendertage von `iso` bis `today` (positiv = in der Vergangenheit). */
export function daysBack(today, iso) {
  return Math.round((Date.parse(`${today}T00:00:00Z`) - Date.parse(`${iso}T00:00:00Z`)) / 86400000);
}

/** Kleinste Stufe, die `needDays` abdeckt, höchstens `max` (die Obergrenze des Desktops). */
export function stepFor(needDays, max) {
  const step = WINDOW_STEPS.find((candidate) => candidate >= needDays) ?? WINDOW_STEPS.at(-1);
  return Math.min(step, max);
}

/** Was die Wochenansicht zum Rand des Fensters sagt. `firstDay` ist der Wochenanfang, `windowDays` das
 *  zuletzt gewährte Fenster, `acked` der Wunsch, zu dem diese Antwort gehört (nicht der gerade getippte:
 *  ein noch unbeantworteter Wunsch darf nie als „gekürzt“ erscheinen), `maxKnown` ob schon eine Antwort
 *  da war (vorher ist die Obergrenze unbekannt, nicht „älterer Desktop“). */
export function olderState({ firstDay, today, windowDays, windowMax, maxKnown, acked }) {
  if (!isIsoDate(firstDay) || !isIsoDate(today) || !Number.isInteger(windowDays)) return { kind: 'none' };
  const need = daysBack(today, firstDay);
  if (need <= windowDays) return { kind: 'none' };
  if (!maxKnown) return { kind: 'unknown' };
  if (!Number.isInteger(windowMax)) return { kind: 'old_desktop' };
  if (windowDays >= windowMax) return { kind: 'capped', days: windowMax };
  const asked = Number.isInteger(acked) ? acked : DEFAULT_WISH;
  // Der Desktop hat weniger gegeben, als erbeten und erlaubt war: die Datenmenge. Eine größere Stufe änderte nichts.
  if (windowDays < Math.min(asked, windowMax)) return { kind: 'trimmed', days: windowDays };
  return { kind: 'load', wish: stepFor(need, windowMax) };
}
