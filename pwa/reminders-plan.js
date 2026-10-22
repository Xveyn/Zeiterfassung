// pwa/reminders-plan.js
// Der Zeitplan der Erinnerungen, ohne Browser-API: aus Reservierungen, Ist-Zeiten und dem
// `reminders`-Block des Desktops die Zeitpunkte, zu denen der Relay einen Push schicken soll.
// Die Reservierungs-Regeln sind die von `src/reminders.py::due_reminders` (Gleichlauf über
// `test/fixtures/reminder-plan-cases.json`); die Sende-Zeitpunkte rechnet der Desktop (er kennt
// Feiertage), sie kommen fertig als UTC-Liste. Gerechnet wird in der Zeitzone des Handys.
import { addDays, localIsoDate, parseTime } from './minutes.js';

export const MAX_ITEMS = 200;        // Grenze des Relays (`LIMITS.maxItems`)
export const HORIZON_DAYS = 14;

/** Wanduhrzeit `HH:MM` am ISO-Tag als lokales `Date`. */
function wallTime(iso, minutes) {
  const [year, month, day] = iso.split('-').map(Number);
  return new Date(year, month - 1, day, Math.floor(minutes / 60), minutes % 60);
}

function loggedCategories(entry) {
  const names = new Set();
  if (!entry || entry.deleted) return names;
  for (const slot of entry.slots ?? []) {
    const name = typeof slot?.kategorie === 'string' ? slot.kategorie.trim() : '';
    if (name) names.add(name);
  }
  return names;
}

function reservationItems(reservations, entries, minutesBefore, now, horizonDays) {
  const items = [];
  const today = localIsoDate(now);
  const last = addDays(today, horizonDays);
  for (const date of Object.keys(reservations ?? {})) {
    const day = reservations[date];
    if (!day || day.deleted || date < today || date > last) continue;
    const logged = loggedCategories(entries?.[date]);
    (day.slots ?? []).forEach((slot, index) => {
      const category = typeof slot?.kategorie === 'string' ? slot.kategorie.trim() : '';
      const start = parseTime(slot?.start);
      const end = parseTime(slot?.end);
      if (!category || logged.has(category) || start === null || end === null) return;
      const base = `r${date.replace(/-/g, '')}-${index}`;
      const missed = { id: `${base}-m`, fireAt: wallTime(date, end), kind: 'missed', date, category, end: slot.end };
      items.push(missed);
      // Bei 0 Minuten fielen beide auf `end`; `due_reminders` meldet dort „verpasst“.
      if (minutesBefore > 0) {
        items.push({ id: `${base}-u`, fireAt: wallTime(date, Math.max(start, end - minutesBefore)), kind: 'upcoming', date, category, end: slot.end });
      }
    });
  }
  return items.filter((item) => item.fireAt > now);
}

function sendItems(at, now) {
  const items = [];
  for (const stamp of at ?? []) {
    const fireAt = new Date(stamp);
    if (Number.isNaN(fireAt.getTime()) || fireAt <= now) continue;
    items.push({ id: `s${Math.floor(fireAt.getTime() / 1000)}`, fireAt, kind: 'send', date: '', category: '', end: '' });
  }
  return items;
}

/** Der Plan, aufsteigend nach Zeitpunkt, höchstens `MAX_ITEMS` (die frühesten), nur Zukünftiges. */
export function planReminders({ reservations, entries, reminders, now, horizonDays = HORIZON_DAYS }) {
  if (!reminders) return [];
  const items = [];
  if (reminders.reservation?.enabled) {
    items.push(...reservationItems(reservations, entries, reminders.reservation.minutes_before, now, horizonDays));
  }
  if (reminders.send?.enabled) items.push(...sendItems(reminders.send.at, now));
  items.sort((a, b) => a.fireAt - b.fireAt || (a.id < b.id ? -1 : 1));
  return items.slice(0, MAX_ITEMS);
}

/** Stabile Kurzform des Plans: ändert sie sich nicht, muss der Relay nichts Neues erfahren. */
export function signature(items) {
  return items.map((i) => `${i.id}@${i.fireAt.getTime()}:${i.kind}:${i.category}:${i.end}`).join('|');
}
