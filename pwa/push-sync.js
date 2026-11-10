// pwa/push-sync.js
// Ein Durchgang „Zeitplan der Erinnerungen an den Relay“, ohne Browser-API: Plan aus dem lokalen Stand rechnen und,
// wenn er sich geändert hat, verschlüsselt senden. Der Plan hängt nur am Speicher des Handys: eine eben eingetragene
// Zeit nimmt ihre Erinnerung heraus, auch wenn der Desktop sie nie gesehen hat (#507).
import { localIsoDate, utcStamp } from './minutes.js';
import { planReminders, signature } from './reminders-plan.js';
import { messageFor } from './push-message.js';
import { seal } from './push-blob.js';
import { shouldSchedule } from './push-policy.js';
import { syncSchedule } from './relay-client.js';

/** Liefert `'skipped'` (Push aus, Desktop kennt keine Erinnerungen, kein Geheimnis oder `aborted()`), `'unchanged'`
 *  oder `'sent'`; wirft, wenn der Relay nicht annimmt (der Plan gilt dann weiter als nicht gesendet).
 *  `state`: Ergebnis von `permissionState`; `getSubscription()`: das Abo als JSON; `aborted()`: wird direkt vor dem
 *  Senden und vor dem Merken gefragt (Trennen: weder ein Relay-Objekt neu anlegen noch die Meta zurückschreiben). */
export async function syncPushPlan({ store, state, client, keys, getSubscription, now = () => new Date(), aborted = () => false }) {
  const meta = store.getMeta();
  if (state !== 'on' || !meta.reminders || !meta.relay_secret) return 'skipped';
  const moment = now();
  const today = localIsoDate(moment);
  const since = (dates) => dates.filter((date) => date >= today);
  const items = planReminders({
    reservations: meta.reservations_enabled
      ? Object.fromEntries(since(store.reservationDates()).map((date) => [date, store.getReservation(date)])) : {},
    entries: Object.fromEntries(since(store.days()).map((date) => [date, store.getDay(date)])),
    reminders: meta.reminders, now: moment,
  });
  const plan = signature(items);
  const sentAt = moment.getTime();
  if (!shouldSchedule({ state, remindersPresent: true, lastSignature: meta.push_signature, signature: plan,
    lastSentAt: meta.push_sent_at, now: sentAt })) return 'unchanged';
  const subscription = await getSubscription();
  const blobs = [];
  for (const item of items) blobs.push({ id: item.id, fire_at: utcStamp(item.fireAt), blob: await seal(keys, messageFor(item)) });
  if (aborted()) return 'skipped';
  await syncSchedule({ client, secret: meta.relay_secret, subscription, items: blobs });
  if (aborted()) return 'skipped';
  await store.setMeta({ push_signature: plan, push_sent_at: sentAt });
  return 'sent';
}
