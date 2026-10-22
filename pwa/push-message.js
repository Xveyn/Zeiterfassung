// pwa/push-message.js
// Was in einer Push-Benachrichtigung steht, ohne Browser-API: die Seite macht aus einem Plan-Eintrag
// den kleinen Klartext für den verschlüsselten Blob (`messageFor`), der Service Worker macht daraus
// Titel, Text und Klick-Ziel (`describe`, `clickTarget`). Die Texte entstehen erst dort, damit der
// Blob klein bleibt und ein Textwechsel keinen neuen Zeitplan braucht.
import { MAX_CATEGORY_LENGTH, isIsoDate, parseTime } from './minutes.js';

const GENERAL = { title: 'Erinnerung', body: 'Zeiterfassung öffnen.' };
const isText = (value) => typeof value === 'string' && value.length > 0;

/** Plan-Eintrag → Klartext des Blobs. */
export function messageFor(item) {
  if (item.kind === 'send') return { k: 'send', t: Math.floor(item.fireAt.getTime() / 1000) };
  return { k: item.kind, c: item.category.slice(0, MAX_CATEGORY_LENGTH), e: item.end, d: item.date };
}

function reservationFields(plain) {
  if (!plain || !isText(plain.c) || parseTime(plain.e) === null) return null;
  return { category: plain.c, end: plain.e, date: plain.d };
}

/** Klartext → `{title, body, tag?}`. Unbrauchbares wird zur allgemeinen Benachrichtigung: der
 *  Service Worker darf einen Push nie unsichtbar lassen (Chrome verlangt eine Anzeige). */
export function describe(plain) {
  const fields = plain && typeof plain === 'object' ? reservationFields(plain) : null;
  if (plain?.k === 'upcoming' && fields) {
    return { title: `Erinnerung: ${fields.category}`, body: `Deine Reservierung endet um ${fields.end} Uhr.`,
      tag: `upcoming-${fields.date}-${fields.end}-${fields.category}` };
  }
  if (plain?.k === 'missed' && fields) {
    return { title: `Zeit nicht erfasst: ${fields.category}`,
      body: `Die Reservierung bis ${fields.end} Uhr ist vorbei, es fehlt die Ist-Zeit.`,
      tag: `missed-${fields.date}-${fields.end}-${fields.category}` };
  }
  if (plain?.k === 'send' && Number.isInteger(plain.t)) {
    return { title: 'Arbeitszeiten senden', body: 'Zeit, die Arbeitszeiten zu senden.', tag: `send-${plain.t}` };
  }
  return { ...GENERAL };
}

/** Adresse, die ein Klick öffnet: bei Reservierungs-Erinnerungen der Tag, sonst die App. */
export function clickTarget(plain, scope) {
  if ((plain?.k === 'upcoming' || plain?.k === 'missed') && isIsoDate(plain.d)) return `${scope}?open=${plain.d}`;
  return scope;
}
