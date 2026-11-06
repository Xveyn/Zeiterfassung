// relay/src/push.js
// Sendet eine Web-Push-Nachricht (RFC 8291 aes128gcm, VAPID nach RFC 8292) und ordnet die Antwort des
// Push-Dienstes für das Durable Object ein. Wirft nie: ein Fehler ist ein Ergebnis, kein Absturz.
import { buildPushPayload } from '@block65/webcrypto-web-push';

const TTL_SECONDS = 300;

/** Die feste Nutzlast der Testroute (`POST /v1/test`). Unverschlüsselt im Sinn der PWA: der Service Worker
 *  erkennt sie vor dem Entschlüsseln. Sie verrät nichts; nur der Relay mit dem VAPID-Schlüssel kann senden.
 *  Gleichlauf mit `pwa/push-message.js`, ein Test hält beide zusammen. */
export const TEST_PAYLOAD = 'zeiterfassung-test';

/** `report(cause)` wird bei `retry` und `drop` einmal gerufen: mit dem HTTP-Status des Push-Dienstes, `network`
 *  (kein Status) oder `build` (Nachricht nicht baubar). Nie Text, Endpoint oder Header: der Relay loggt nichts,
 *  und die Ursache ist das Einzige, das die Testroute dem Nutzer verrät.
 *
 *  `ok` gesendet · `gone` Abo ist tot (404/410) · `retry` später noch einmal (429, 5xx, Netzfehler) ·
 *  `drop` der Dienst lehnt diese Nachricht ab (übrige 4xx), ein Wiederholen ändert nichts. */
export async function sendPush(subscription, blob, env, fetchFn = fetch, report = () => {}) {
  let request;
  try {
    request = await buildPushPayload(
      { data: blob, options: { ttl: TTL_SECONDS, urgency: 'high' } },
      { endpoint: subscription.endpoint, expirationTime: null, keys: subscription.keys },
      { subject: env.VAPID_SUBJECT, publicKey: env.VAPID_PUBLIC, privateKey: env.VAPID_PRIVATE },
    );
  } catch {
    report('build');
    return 'drop';          // unbrauchbare Schlüssel: ein Wiederholen ändert nichts
  }
  let response;
  try {
    response = await fetchFn(subscription.endpoint, request);
  } catch {
    report('network');
    return 'retry';         // Netzfehler: ein kurzer Ausfall des Push-Dienstes soll die Erinnerung nicht kosten
  }
  if (response.ok) return 'ok';
  if (response.status === 404 || response.status === 410) return 'gone';
  report(response.status);
  if (response.status === 429 || response.status >= 500) return 'retry';
  return 'drop';
}
