// pwa/window-policy.js
// Lesefenster der PWA (#250): welche Stufe wird gewünscht, wann zeigt die Wochenansicht „Ältere Zeiten
// laden“, und was sagt sie, wenn der Desktop nicht mehr liefert? Reine Entscheidungen ohne Browser-API
// (getestet in test/window-policy.test.js). Das Fenster selbst bestimmt immer der Desktop: die Antwort
// nennt das gewährte `window_days` und die Obergrenze `window_max_days`.
import { isIsoDate } from './minutes.js';

export const WINDOW_STEPS = [90, 180, 365];
export const DEFAULT_WISH = 90;

/** Kalendertage von `iso` bis `today` (positiv = in der Vergangenheit). */
export function daysBack(today, iso) {
  return Math.round((Date.parse(`${today}T00:00:00Z`) - Date.parse(`${iso}T00:00:00Z`)) / 86400000);
}

/** Kleinste Stufe, die `needDays` abdeckt, höchstens `max` (die Obergrenze des Desktops). */
export function stepFor(needDays, max) {
  const step = WINDOW_STEPS.find((candidate) => candidate >= needDays) ?? WINDOW_STEPS.at(-1);
  return Math.min(step, max);
}

/** Was die Wochenansicht zum Rand des Fensters sagt. `firstDay` ist der Wochenanfang. */
export function olderState({ firstDay, today, windowDays, windowMax, wish }) {
  if (!isIsoDate(firstDay) || !isIsoDate(today) || !Number.isInteger(windowDays)) return { kind: 'none' };
  const need = daysBack(today, firstDay);
  if (need <= windowDays) return { kind: 'none' };
  if (!Number.isInteger(windowMax)) return { kind: 'old_desktop' };
  const target = stepFor(need, windowMax);
  if (wish >= target) {
    // Der Wunsch deckt die Woche schon ab und das Fenster ist trotzdem zu klein: der Desktop liefert nicht mehr.
    return windowDays >= windowMax ? { kind: 'capped', days: windowMax } : { kind: 'trimmed', days: windowDays };
  }
  return { kind: 'load', wish: target };
}
