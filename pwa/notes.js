// pwa/notes.js — Regeln der optionalen Notiz an einem Ist-Zeit-Slot.
// Gegenstück zu src/slot_notes.py; die gemeinsamen Fälle stehen in test/fixtures/note-cases.json.

export const MAX_NOTE_LEN = 200;

// Steuerzeichen und Zeilentrenner: die Notiz ist einzeilig.
const REJECTED = /[\p{Cc}\p{Cs}\p{Zl}\p{Zp}]/u;
const REJECTED_ALL = /[\p{Cc}\p{Cs}\p{Zl}\p{Zp}]/gu;

/** Bereinigt gespeicherte Daten (Fremddaten): Steuerzeichen raus, trimmen, auf 200 Code Points kürzen. */
export function cleanNote(value) {
  if (typeof value !== 'string') return '';
  const text = value.replace(REJECTED_ALL, '').trim();
  return [...text].slice(0, MAX_NOTE_LEN).join('').trim();
}

/** Prüft eine Eingabe: `{ok: true, note}` (getrimmt) oder `{ok: false, message}`. */
export function checkNote(value) {
  if (typeof value !== 'string') return { ok: false, message: 'Die Notiz muss Text sein.' };
  const text = value.trim();
  if (REJECTED.test(text)) return { ok: false, message: 'Nur eine Zeile, keine Steuerzeichen.' };
  if ([...text].length > MAX_NOTE_LEN) return { ok: false, message: `Höchstens ${MAX_NOTE_LEN} Zeichen.` };
  return { ok: true, note: text };
}

/** Gruppierschlüssel gleicher Notizen (bewusst `toLowerCase`, wie `lower` in Python). */
export function groupKey(note) {
  return String(note).trim().toLowerCase();
}

function isObject(v) {
  return v !== null && typeof v === 'object' && !Array.isArray(v);
}

/**
 * Bisherige Notizen, je Gruppierschlüssel einmal: erst die der Kategorie, dann alle übrigen,
 * je neueste Tage zuerst, innerhalb eines Tages in gespeicherter Reihenfolge.
 * @param {unknown} days  `{ISO: {slots, deleted}}`
 * @param {string} kategorie
 * @param {number} [limit]
 * @returns {string[]}
 */
export function noteSuggestions(days, kategorie, limit = 20) {
  if (!isObject(days)) return [];
  const slots = [];
  for (const iso of Object.keys(days).sort().reverse()) {
    const day = days[iso];
    if (!isObject(day) || day.deleted === true || !Array.isArray(day.slots)) continue;
    for (const s of day.slots) if (isObject(s)) slots.push(s);
  }
  const cat = (s) => (typeof s.kategorie === 'string' ? s.kategorie : '');
  const ordered = [...slots.filter((s) => cat(s) === kategorie), ...slots.filter((s) => cat(s) !== kategorie)];
  const seen = new Set();
  const result = [];
  for (const slot of ordered) {
    const note = cleanNote(slot.notiz);
    const key = groupKey(note);
    if (!note || seen.has(key)) continue;
    seen.add(key);
    result.push(note);
    if (result.length >= limit) break;
  }
  return result;
}
