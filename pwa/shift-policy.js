// pwa/shift-policy.js
// Ein waagerechter Zug auf den Zeitfeldern eines Slots verschiebt Start und Ende gemeinsam (#500):
// rechts später, links früher, die Dauer bleibt. Reine Entscheidung ohne Browser-API; `views.js`
// sammelt die Pointer-Events und schreibt das Ergebnis in die Zeile.

import { t } from './i18n.js';
import { parseTime } from './minutes.js';
import { EDGE_PX } from './swipe-policy.js';

/** Wählbare Schrittweiten in Minuten; 0 schaltet die Geste aus. Alle liegen im 5-Minuten-Raster der Zeiten. */
export const SHIFT_STEPS = Object.freeze([0, 5, 10, 15, 30, 60]);
export const DEFAULT_SHIFT_STEP = 10;
/** So viele Pixel Zug ergeben einen Schritt. */
export const STEP_PX = 28;

const FINGERS = new Set(['touch', 'pen']);
const LAST_MINUTE = 24 * 60 - 1;

/** Fremddaten aus dem Speicher: alles außer einer angebotenen Schrittweite ist der Standard. */
export function normalizeShiftStep(value) {
  return SHIFT_STEPS.includes(value) ? value : DEFAULT_SHIFT_STEP;
}

/** Auswahl im Abschnitt „Zeiten verschieben“ der Einstellungen. */
export function shiftOptions() {
  return SHIFT_STEPS.map((value) => ({ value, label: value === 0 ? t('verschieben.aus') : t('verschieben.schritt', { value }) }));
}

/** Darf hier ein Zug beginnen? Nur Finger/Stift, und nie im Randstreifen der System-Zurück-Geste. */
export function mayStartShift({ pointerType, width, startX } = {}) {
  if (!FINGERS.has(pointerType)) return false;
  if (!Number.isFinite(width) || !Number.isFinite(startX) || width <= 0) return false;
  return startX >= EDGE_PX && startX <= width - EDGE_PX;
}

/** Ganze Schritte für eine Strecke in Pixeln (rechts positiv), zur Null hin gerundet. */
export function stepsForDistance(dx) {
  return Number.isFinite(dx) ? Math.trunc(dx / STEP_PX) + 0 : 0;      // `+ 0` macht aus -0 eine 0
}

const format = (minutes) => `${String(Math.floor(minutes / 60)).padStart(2, '0')}:${String(minutes % 60).padStart(2, '0')}`;

/** Verschiebt das Fenster um `steps` Schritte zu `stepMinutes`. An den Tagesgrenzen (00:00, 23:59) bleibt es
 *  nach dem letzten ganzen Schritt stehen; die Dauer wird nie gekürzt. Liefert `{start, end, steps}` mit den
 *  tatsächlich gegangenen Schritten, oder `null` für eine Zeile, die sich nicht verschieben lässt. */
export function shiftWindow(start, end, steps, stepMinutes) {
  const from = parseTime(start);
  const to = parseTime(end);
  if (from === null || to === null || to <= from) return null;
  if (!Number.isInteger(steps) || !Number.isInteger(stepMinutes) || stepMinutes <= 0) return null;
  const earliest = -Math.floor(from / stepMinutes);
  const latest = Math.floor((LAST_MINUTE - to) / stepMinutes);
  const taken = Math.max(earliest, Math.min(latest, steps)) + 0;     // `+ 0` macht aus -0 eine 0
  return { start: format(from + taken * stepMinutes), end: format(to + taken * stepMinutes), steps: taken };
}

/** Text der Live-Anzeige beim Ziehen: `+20 min`, `−10 min`, `±0 min`. */
export function shiftLabel(minutes) {
  if (minutes === 0) return t('verschieben.null');
  return minutes > 0 ? t('verschieben.plus', { value: minutes }) : t('verschieben.minus', { value: -minutes });
}
