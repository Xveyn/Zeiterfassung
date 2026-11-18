// pwa/slot-order.js
// @ts-check
// Reihenfolge der Slots eines Tages (#520). Gegenstück zu `src/slot_order.py`; den Gleichlauf hält
// `test/fixtures/slot-order-cases.json` (Python und JavaScript lesen dieselbe Datei). Drei Modi
// (`slot_order_mode` des Desktops): `chrono` (Standard), `category` (nach Kategoriename) und `custom`
// (gespeicherte Reihenfolge). Sortiert wird bei Anzeige und — außer in `custom` — beim Speichern eines Tages.

export const SLOT_ORDERS = ['chrono', 'category', 'custom'];
export const DEFAULT_SLOT_ORDER = 'chrono';

/** Ein Modus aus der Sync-Antwort oder den Einstellungen; Unbrauchbares gilt als `chrono`. */
export function normalizeSlotOrder(value) {
  return typeof value === 'string' && SLOT_ORDERS.includes(value) ? value : DEFAULT_SLOT_ORDER;
}

const text = (value) => (typeof value === 'string' && value !== '' ? value : null);

/** Kategoriename ohne Groß-/Kleinschreibung, ä/ö/ü wie a/o/u, ß wie ss (wie `fold_name` in Python). */
export function foldName(name) {
  return name.toLowerCase().replace(/ß/g, 'ss').replace(/ä/g, 'a').replace(/ö/g, 'o').replace(/ü/g, 'u');
}

/** Sortierschlüssel. `chrono`: Start, Ende, Kategorie, Position. `category`: benannte vor unbenannten
 *  Kategorien, Name gefaltet, dann Start, Ende, Position. `HH:MM` ist validiert, der Textvergleich
 *  entspricht dem Zeitvergleich. Ohne lesbare Startzeit: ans Ende, in Listenreihenfolge. */
function key(mode, slot, index) {
  const start = slot !== null && typeof slot === 'object' ? text(slot.start) : null;
  if (start === null) return [1, '', '', '', '', index];
  const end = text(slot.end) ?? '';
  const kategorie = text(slot.kategorie) ?? '';
  if (mode === 'category') return [0, kategorie === '' ? 1 : 0, foldName(kategorie), start, end, index];
  return [0, start, end, kategorie, '', index];
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

/** Die Slots in der Reihenfolge des Modus (dieselben Objekte, die Eingabe bleibt unverändert).
 *  Kein Array → `[]`; `custom` liefert die gespeicherte Reihenfolge.
 * @param {any} slots
 * @param {string} [mode]
 * @returns {any[]} */
export function sortedSlots(slots, mode = DEFAULT_SLOT_ORDER) {
  if (!Array.isArray(slots)) return [];
  const order = normalizeSlotOrder(mode);
  if (order === 'custom') return [...slots];
  return slots
    .map((slot, index) => ({ slot, k: key(order, slot, index) }))
    .sort((a, b) => compare(a.k, b.k))
    .map(({ slot }) => slot);
}
