// pwa/sync-policy.js
// Wann darf ein Abgleich laufen? Die Spec erlaubt genau diese Auslöser: Start, Sichtbarwerden,
// `online`-Ereignis, 2 s nach dem Speichern, Knopfdruck — kein Hintergrund-Sync. Diese Funktion
// verhindert, dass die automatischen Auslöser bei Fehlern im Dauerfeuer laufen.

export const AUTO_COOLDOWN_MS = 5000;
export const OFFLINE_BACKOFF_MS = 30000;
const AUTOMATIC = new Set(['start', 'visible', 'online']);

export function shouldSync({ trigger, paired, syncing, online, now, lastAttemptAt, lastError }) {
  if (!paired || syncing) return false;
  if (trigger === 'manual' || trigger === 'save') return true;       // der Nutzer hat es gewollt
  if (!AUTOMATIC.has(trigger)) return false;
  if (lastError?.needsRepair) return false;                          // totes Token: erst neu koppeln
  if (trigger !== 'online' && !online) return false;
  if (now - lastAttemptAt < AUTO_COOLDOWN_MS) return false;
  if (trigger !== 'online' && lastError?.kind === 'offline' && now - lastAttemptAt < OFFLINE_BACKOFF_MS) {
    return false;
  }
  return true;
}
