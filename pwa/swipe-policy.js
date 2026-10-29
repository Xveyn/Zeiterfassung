// pwa/swipe-policy.js
// Ist eine Berührung ein Wisch, der die Woche wechseln soll? Reine Entscheidung ohne Browser-API
// (getestet in test/swipe-policy.test.js); `app.js` sammelt Start und Ende und führt aus.

export const MIN_DISTANCE_PX = 60;
/** Ein kurzer, schneller Zug (Flick) genügt auch unter der Mindestdistanz. */
export const FLICK_DISTANCE_PX = 30;
export const FLICK_MAX_MS = 150;
/** Wie viel stärker die Bewegung waagerecht als senkrecht sein muss, sonst ist es Scrollen. */
export const DOMINANCE = 2;
/** Ein Start in diesem Randstreifen gehört der System-Zurück-Geste (Android, iOS) und zählt nie. */
export const EDGE_PX = 24;

const FINGERS = new Set(['touch', 'pen']);

/** `'next'` (Wisch nach links), `'previous'` (Wisch nach rechts) oder `null`. */
export function swipeDirection({ pointerType, width, startX, startY, endX, endY, durationMs } = {}) {
  if (!FINGERS.has(pointerType)) return null;
  const numbers = [width, startX, startY, endX, endY, durationMs];
  if (!numbers.every(Number.isFinite) || width <= 0) return null;
  if (startX < EDGE_PX || startX > width - EDGE_PX) return null;
  const dx = endX - startX;
  const dy = endY - startY;
  const distance = Math.abs(dx);
  if (Math.abs(dy) * DOMINANCE > distance) return null;
  const far = distance >= MIN_DISTANCE_PX;
  const flick = distance >= FLICK_DISTANCE_PX && durationMs <= FLICK_MAX_MS;
  if (!far && !flick) return null;
  return dx < 0 ? 'next' : 'previous';
}
