// relay/src/schedule.js
// Die Entscheidungen des Alarms: was ist fällig, was bleibt, wann klingelt es als Nächstes, und was
// geschieht nach einem Fehlschlag. Reine Funktionen mit Zeiten in Millisekunden; das Durable Object
// (`device.js`) ruft sie nur auf.
import { LIMITS } from './validate.js';

const DAY_MS = 86_400_000;
const BACKOFF_SECONDS = [30, 120, 600];

/** Ein Eintrag zählt von seiner ersten Fälligkeit an: ein Wiederholungsversuch verschiebt `fireAt`,
 *  nicht die Frist (`dueAt`). */
const deadline = (item) => (item.dueAt ?? item.fireAt) + LIMITS.graceSeconds * 1000;

export const idleAt = (now) => now + LIMITS.idleDays * DAY_MS;

/** `due`: jetzt zu senden; `keep`: noch nicht fällig; abgelaufene Einträge fallen weg. `alarmAt` ist
 *  der nächste Zeitpunkt, der Leerlauf-Ablauf `idleAt` ist die Obergrenze (er räumt verlassene Geräte auf). */
export function planAlarm(items, now, idleAtMs) {
  const due = [];
  const keep = [];
  for (const item of items) {
    if (item.fireAt > now) keep.push(item);
    else if (now <= deadline(item)) due.push(item);
  }
  const next = keep.reduce((earliest, item) => Math.min(earliest, item.fireAt), Infinity);
  return { due, keep, alarmAt: Math.min(next, idleAtMs) };
}

/** Der Eintrag nach einem fehlgeschlagenen Senden, oder `null`, wenn er aufgegeben wird (keine
 *  Backoff-Stufe mehr, oder der nächste Versuch läge hinter der 15-Minuten-Frist). */
export function afterFailure(item, now) {
  const attempts = (item.attempts ?? 0) + 1;
  const wait = BACKOFF_SECONDS[attempts - 1];
  if (wait === undefined) return null;
  const retryAt = now + wait * 1000;
  if (retryAt > deadline(item)) return null;
  return { ...item, attempts, fireAt: retryAt, dueAt: item.dueAt ?? item.fireAt };
}
