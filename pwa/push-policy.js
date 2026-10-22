// pwa/push-policy.js
// Wann die PWA den Zeitplan an den Relay schickt und was der Reiter über die Benachrichtigungen
// sagt. Rein, ohne Browser-API: die Seite liest Berechtigung und Abo und fragt hier nur noch.
export const RESEND_AFTER_MS = 12 * 60 * 60 * 1000;   // auch ein unveränderter Plan wird erneuert (hält das Objekt am Relay am Leben)

/** `unsupported` | `denied` | `off` | `needs_resubscribe` | `on`. `enabled` ist der Wunsch des
 *  Nutzers in diesem Gerät, `permission` die Antwort des Browsers, `subscribed` ob ein Abo besteht. */
export function permissionState({ supported, permission, subscribed, enabled }) {
  if (!supported) return 'unsupported';
  if (permission === 'denied') return 'denied';
  if (!enabled || permission !== 'granted') return 'off';
  return subscribed ? 'on' : 'needs_resubscribe';
}

/** Soll jetzt gesendet werden? Nur bei `on`, nur wenn der Desktop die Erinnerungen kennt
 *  (`remindersPresent`), und nur bei neuem Plan oder nach `RESEND_AFTER_MS`. */
export function shouldSchedule({ state, remindersPresent, lastSignature, signature, lastSentAt, now }) {
  if (state !== 'on' || !remindersPresent) return false;
  if (lastSignature === null || lastSignature === undefined || lastSignature !== signature) return true;
  return now - lastSentAt >= RESEND_AFTER_MS;
}

const TEXTS = {
  unsupported: ['Dieser Browser kann keine Benachrichtigungen anzeigen.', null],
  denied: ['Benachrichtigungen sind für diese Seite gesperrt. In den Einstellungen des Browsers lassen sie sich wieder erlauben.', null],
  off: ['Aus. Erinnerungen kommen nur am Desktop.', 'enable'],
  needs_resubscribe: ['Das Abo ist abgelaufen. Erneut erlauben, dann kommen die Erinnerungen wieder.', 'enable'],
  on: ['An. Erinnerungen kommen auch dann, wenn der Desktop aus ist.', 'disable'],
};

/** Text und Aktion (`enable` | `disable` | `null`) für den Reiter; ein Fehler des Relays hängt am Text. */
export function describeState(state, lastError) {
  const [text, action] = TEXTS[state] ?? TEXTS.off;
  return { text: lastError ? `${text} ${lastError}` : text, action };
}
