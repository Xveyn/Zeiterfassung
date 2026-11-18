// pwa/slot-order.js
// @ts-check
// Reihenfolge der Slots eines Tages (#520): chronologisch nach Startzeit. Gegenstück zu
// `src/slot_order.py`; den Gleichlauf hält `test/fixtures/slot-order-cases.json` (Python und
// JavaScript lesen dieselbe Datei). Gespeichert wird weiter die Listenreihenfolge, sortiert wird
// bei Anzeige und beim Speichern eines Tages.

const text = (value) => (typeof value === 'string' && value !== '' ? value : null);

/** Sortierschlüssel `chrono`: Start, Ende, Kategorie, Listenposition. `HH:MM` ist validiert, der
 *  Textvergleich entspricht dem Zeitvergleich. Ohne lesbare Startzeit: ans Ende, in Listenreihenfolge. */
function key(slot, index) {
  const start = slot !== null && typeof slot === 'object' ? text(slot.start) : null;
  if (start === null) return [1, '', '', '', index];
  return [0, start, text(slot.end) ?? '', text(slot.kategorie) ?? '', index];
}

/** Wie Pythons Vergleich: nach Codepoints, nicht nach UTF-16-Einheiten (`<` auf Strings). */
function compareText(a, b) {
  const left = Array.from(a);
  const right = Array.from(b);
  const length = Math.min(left.length, right.length);
  for (let i = 0; i < length; i += 1) {
    const x = left[i].codePointAt(0);
    const y = right[i].codePointAt(0);
    if (x !== y) return x < y ? -1 : 1;
  }
  return left.length - right.length;
}

function compare(a, b) {
  for (let i = 0; i < a.length; i += 1) {
    if (a[i] === b[i]) continue;
    if (typeof a[i] === 'string') return compareText(a[i], b[i]);
    return a[i] < b[i] ? -1 : 1;
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
