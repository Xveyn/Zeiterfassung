// pwa/push-policy.js
// Wann die PWA den Zeitplan an den Relay schickt und was der Reiter über die Benachrichtigungen
// sagt. Rein, ohne Browser-API: die Seite liest Berechtigung und Abo und fragt hier nur noch.
import { t } from './i18n.js';

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
  unsupported: [() => t('push.zustand.unsupported'), null],
  denied: [() => t('push.zustand.denied'), null],
  off: [() => t('push.zustand.off'), 'enable'],
  needs_resubscribe: [() => t('push.zustand.needs_resubscribe'), 'enable'],
  on: [() => t('push.zustand.on'), 'disable'],
};

/** Text und Aktion (`enable` | `disable` | `null`) für den Reiter; ein Fehler des Relays hängt am Text. */
export function describeState(state, lastError) {
  const [textOf, action] = TEXTS[state] ?? TEXTS.off;
  const text = textOf();
  return { text: lastError ? `${text} ${lastError}` : text, action };
}
