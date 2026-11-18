// pwa/slot-order.js
// @ts-check
// Reihenfolge der Slots eines Tages (#520): chronologisch nach Startzeit. Gegenstück zu
// `src/slot_order.py`; den Gleichlauf hält `test/fixtures/slot-order-cases.json` (Python und
// JavaScript lesen dieselbe Datei). Gespeichert wird weiter die Listenreihenfolge, sortiert wird
// bei Anzeige und beim Speichern eines Tages.

const text = (value) => (typeof value === 'string' && value !== '' ? value : null);

/** Sortierschlüssel `chrono`: Start, Ende, Kategorie, Listenposition. `HH:MM` ist validiert, der
 *  Textvergleich entspricht dem Zeitvergleich. Ohne lesbare Startzeit: ans Ende. */
function key(slot, index) {
  if (slot === null || typeof slot !== 'object') return [1, '', '', '', index];
  const start = text(slot.start);
  return [start === null ? 1 : 0, start ?? '', text(slot.end) ?? '', text(slot.kategorie) ?? '', index];
}

function compare(a, b) {
  for (let i = 0; i < a.length; i += 1) {
    if (a[i] < b[i]) return -1;
    if (a[i] > b[i]) return 1;
  }
  return 0;
}

/** Die Slots chronologisch (dieselben Objekte, die Eingabe bleibt unverändert). Kein Array → `[]`. */
export function sortedSlots(slots) {
  if (!Array.isArray(slots)) return [];
  return slots
    .map((slot, index) => ({ slot, k: key(slot, index) }))
    .sort((a, b) => compare(a.k, b.k))
    .map(({ slot }) => slot);
}
