// relay/src/push.js
// Sendet eine Web-Push-Nachricht (RFC 8291 aes128gcm, VAPID nach RFC 8292) und ordnet die Antwort des
// Push-Dienstes für das Durable Object ein. Wirft nie: ein Fehler ist ein Ergebnis, kein Absturz.
import { buildPushPayload } from '@block65/webcrypto-web-push';

const TTL_SECONDS = 300;

/** `ok` gesendet · `gone` Abo ist tot (404/410) · `retry` später noch einmal (429, 5xx, Netzfehler) ·
 *  `drop` der Dienst lehnt diese Nachricht ab (übrige 4xx), ein Wiederholen ändert nichts. */
export async function sendPush(subscription, blob, env, fetchFn = fetch) {
  let request;
  try {
    request = await buildPushPayload(
      { data: blob, options: { ttl: TTL_SECONDS, urgency: 'high' } },
      { endpoint: subscription.endpoint, expirationTime: null, keys: subscription.keys },
      { subject: env.VAPID_SUBJECT, publicKey: env.VAPID_PUBLIC, privateKey: env.VAPID_PRIVATE },
    );
  } catch {
    return 'drop';          // unbrauchbare Schlüssel: ein Wiederholen ändert nichts
  }
  let response;
  try {
    response = await fetchFn(subscription.endpoint, request);
  } catch {
    return 'retry';         // Netzfehler: ein kurzer Ausfall des Push-Dienstes soll die Erinnerung nicht kosten
  }
  if (response.ok) return 'ok';
  if (response.status === 404 || response.status === 410) return 'gone';
  if (response.status === 429 || response.status >= 500) return 'retry';
  return 'drop';
}
