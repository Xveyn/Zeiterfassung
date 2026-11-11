// pwa/push-message.js
// Was in einer Push-Benachrichtigung steht, ohne Browser-API: die Seite macht aus einem Plan-Eintrag
// den kleinen Klartext für den verschlüsselten Blob (`messageFor`), der Service Worker macht daraus
// Titel, Text und Klick-Ziel (`describe`, `clickTarget`). Die Texte entstehen erst dort, damit der
// Blob klein bleibt und ein Textwechsel keinen neuen Zeitplan braucht.
// Der Service Worker liest keine gespeicherte Sprache und zeigt daher die Standardsprache des Katalogs.
import { t } from './i18n.js';
import { MAX_CATEGORY_LENGTH, isIsoDate, parseTime } from './minutes.js';

const general = () => ({ title: t('push.benachrichtigung.allgemein.titel'), body: t('push.benachrichtigung.allgemein.text') });
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
    return { title: t('push.benachrichtigung.bald.titel', { category: fields.category }),
      body: t('push.benachrichtigung.bald.text', { end: fields.end }),
      tag: `upcoming-${fields.date}-${fields.end}-${fields.category}` };
  }
  if (plain?.k === 'missed' && fields) {
    return { title: t('push.benachrichtigung.verpasst.titel', { category: fields.category }),
      body: t('push.benachrichtigung.verpasst.text', { end: fields.end }),
      tag: `missed-${fields.date}-${fields.end}-${fields.category}` };
  }
  if (plain?.k === 'send' && Number.isInteger(plain.t)) {
    return { title: t('push.benachrichtigung.senden.titel'), body: t('push.benachrichtigung.senden.text'), tag: `send-${plain.t}` };
  }
  return general();
}

/** Adresse, die ein Klick öffnet: bei Reservierungs-Erinnerungen der Tag, sonst die App. */
export function clickTarget(plain, scope) {
  if ((plain?.k === 'upcoming' || plain?.k === 'missed') && isIsoDate(plain.d)) return `${scope}?open=${plain.d}`;
  return scope;
}

// --- Testbenachrichtigung (#340) -----------------------------------------------------------------

/** Die feste Nutzlast, die der Relay bei `POST /v1/test` sendet (`relay/src/push.js`; ein Test hält
 *  beide gleich). Der Service Worker erkennt sie vor dem Entschlüsseln. */
export const TEST_PAYLOAD = 'zeiterfassung-test';

export function describeTest() {
  return { title: t('push.benachrichtigung.test.titel'), body: t('push.benachrichtigung.test.text'), tag: 'test' };
}

const TEST_TEXTS = {
  ok: () => t('push.test.ok'),
  no_subscription: () => t('push.test.no_subscription'),
  gone: () => t('push.test.gone'),
  too_soon: () => t('push.test.too_soon'),
  rate_limited: () => t('push.test.rate_limited'),
  unknown_route: () => t('push.test.unknown_route'),
  offline: () => t('push.test.offline'),
  push_failed: () => t('push.test.push_failed'),
  unauthorized: () => t('push.test.unauthorized'),
};

const CAUSE_TEXTS = { network: () => t('push.test.ursache.network'), build: () => t('push.test.ursache.build') };

/** Der Text zum Ergebnis des Tests (`ok` oder die `kind` eines `RelayError`). Bei `push_failed` nennt
 *  `cause` (Status des Push-Dienstes, `network`, `build`), woran es lag; Gleichlauf mit `tab_rules.test_push_text`. */
export function testResultText(kind, cause) {
  const text = (TEST_TEXTS[kind] ?? (() => t('push.test.sonst')))();
  if (kind !== 'push_failed') return text;
  const detail = Number.isInteger(cause) ? t('push.test.antwort', { status: cause }) : CAUSE_TEXTS[cause]?.();
  return detail === undefined ? text : t('push.test.mit_ursache', { text: text.slice(0, -1), detail });
}
