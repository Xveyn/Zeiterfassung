// pwa/reservations.js
// Reservierungen (zukünftige Soll-Zeiten) ohne DOM: wann der Block erscheint, wie Slots
// aussehen und geprüft werden. Gegenstück zu `reservation_block_visible` (Sichtbarkeit,
// Gleichlauf über `test/fixtures/reservation-visibility-cases.json`) und zu
// `src/mobile_reservations.py` (Form auf dem Draht).
import { addDays, normalizeSlots, slotMinutes, validateSlots } from './minutes.js';

/** So weit voraus nimmt der Desktop Reservierungen an und liefert sie zurück. */
export const RESERVATION_HORIZON_DAYS = 365;

/** Der Reservierungs-Block erscheint nur an heutigen und zukünftigen Tagen. Auch eine alte
 *  Reservierung wird in der Vergangenheit nicht gezeigt (wie am Desktop). ISO-Daten vergleichen
 *  sich als Text. */
export function reservationBlockVisible(day, today) {
  return day >= today;
}

/** Welche Tage das Handy anlegen und bearbeiten lässt: sichtbar **und** innerhalb dessen, was der
 *  Desktop annimmt. Der Desktop lehnt hinter heute + 365 die ganze Anfrage ab (auch die Ist-Zeiten);
 *  ein Tag Reserve fängt eine um einen Tag vorgehende Handy-Uhr ab. */
export function reservationEditable(day, today) {
  return reservationBlockVisible(day, today) && day <= addDays(today, RESERVATION_HORIZON_DAYS - 1);
}

/** Nur `start`, `end`, `kategorie`: `pause` gibt es bei Reservierungen nicht, und der Desktop
 *  lehnt jedes weitere Feld am Slot ab. */
export function normalizeReservationSlots(raw) {
  return normalizeSlots(raw).map((slot) => (slot !== null && typeof slot === 'object'
    ? { start: slot.start, end: slot.end, kategorie: slot.kategorie }
    : slot));
}

export function validateReservationSlots(slots) {
  if (!Array.isArray(slots)) return validateSlots(slots);
  return validateSlots(slots.map((slot) => (slot !== null && typeof slot === 'object' ? { ...slot, pause: 0 } : slot)));
}

/** Reihenfolge der Slots ist keine Änderung. */
export function reservationSignature(slots) {
  return JSON.stringify(slots.map((s) => [s.start, s.end, s.kategorie]).sort());
}

/** Die Slots einer Reservierung, die noch offen sind. Heute erledigt ein Ist-Slot derselben Kategorie genau
 *  einen Reservierungs-Slot, gleich zu welcher Zeit: Kategorie und das `*` der Abweichung sind die
 *  Verknüpfung, der Nutzer hat bewusst reserviert. Ohne Kategorie gibt es keine Verknüpfung; an künftigen
 *  Tagen zählt Ist-Zeit nie. Die Reihenfolge der Slots bleibt erhalten. */
export function openReservationSlots(reservationSlots, actualSlots, isToday) {
  if (!isToday) return reservationSlots;
  const unused = actualSlots.map((slot) => slot?.kategorie);
  const done = new Set();
  // Der früheste Slot einer Kategorie wird zuerst erledigt, gleich in welcher Reihenfolge sie vorliegen.
  const byStart = reservationSlots.map((slot, index) => ({ slot, index }))
    .sort((a, b) => String(a.slot.start).localeCompare(String(b.slot.start)));
  for (const { slot, index } of byStart) {
    if (!slot.kategorie) continue;
    const match = unused.indexOf(slot.kategorie);
    if (match < 0) continue;
    unused[match] = undefined;
    done.add(index);
  }
  return reservationSlots.filter((_slot, index) => !done.has(index));
}

/** Minuten einer Reservierung, die noch ausstehen (nur die offenen Slots). */
export function pendingReservationMinutes(reservationSlots, actualSlots, isToday) {
  return openReservationSlots(reservationSlots, actualSlots, isToday)
    .reduce((sum, slot) => sum + slotMinutes({ start: slot.start, end: slot.end }), 0);
}
