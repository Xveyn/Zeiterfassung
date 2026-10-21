// relay/src/validate.js
// Alles, was von außen kommt, ist Fremddaten: Geheimnis, Abo und Zeitplan werden hier geprüft,
// bevor irgendetwas gespeichert wird. Reine Funktionen, keine Plattform-API (getestet mit `node --test`).
export const LIMITS = {
  maxItems: 200,
  maxAheadDays: 90,
  maxBlob: 1024,
  graceSeconds: 900,       // so lange nach `fire_at` wird eine Erinnerung noch gesendet
  idleDays: 90,            // so lange nach der letzten Aktualisierung räumt sich ein Gerät selbst auf
};

const DAY_MS = 86_400_000;
const BASE64URL = /^[A-Za-z0-9_-]+$/;
const STAMP = /^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$/;
const ID = /^[A-Za-z0-9_-]{1,64}$/;

export class InvalidRequest extends Error {}

const isObject = (value) => value !== null && typeof value === 'object' && !Array.isArray(value);

function bytes(text, length, name) {
  if (typeof text !== 'string' || !BASE64URL.test(text) || Buffer.from(text, 'base64url').length !== length) {
    throw new InvalidRequest(`${name} ist kein Base64url-Wert mit ${length} Bytes.`);
  }
  return text;
}

/** `Authorization: Bearer <43 Zeichen Base64url>` (256 Bit) → das Geheimnis. */
export function parseSecret(header) {
  const match = typeof header === 'string' ? /^Bearer ([A-Za-z0-9_-]{43})$/.exec(header) : null;
  if (!match) throw new InvalidRequest('Kein gültiges Geheimnis im Authorization-Header.');
  return match[1];
}

/** Das Abo, wie `PushSubscription.toJSON()` es liefert; übernommen werden nur diese drei Werte. */
export function parseSubscription(body) {
  if (!isObject(body)) throw new InvalidRequest('Der Body muss ein Objekt sein.');
  let url;
  try {
    url = new URL(body.endpoint);
  } catch {
    throw new InvalidRequest('endpoint ist keine URL.');
  }
  if (url.protocol !== 'https:') throw new InvalidRequest('endpoint muss https sein.');
  if (!isObject(body.keys)) throw new InvalidRequest('keys fehlt.');
  return {
    endpoint: body.endpoint,
    keys: { p256dh: bytes(body.keys.p256dh, 65, 'keys.p256dh'), auth: bytes(body.keys.auth, 16, 'keys.auth') },
  };
}

// Streng wie `isIsoDate` der PWA: das Muster allein ließe „2026-09-31“ durch, `Date` rechnet es still um.
function parseStamp(text) {
  if (typeof text !== 'string' || !STAMP.test(text)) throw new InvalidRequest('fire_at muss YYYY-MM-DDTHH:MM:SSZ sein.');
  const ms = Date.parse(text);
  if (Number.isNaN(ms) || new Date(ms).toISOString().replace('.000Z', 'Z') !== text) {
    throw new InvalidRequest('fire_at ist kein gültiger Zeitpunkt.');
  }
  return ms;
}

/** `{items: [{id, fire_at, blob}]}` → `[{id, fireAt (ms), blob}]`. Einträge, die schon länger als die
 *  Frist her sind, entfallen still: eine Erinnerung von gestern ist keine. */
export function parseSchedule(body, now) {
  if (!isObject(body) || !Array.isArray(body.items)) throw new InvalidRequest('items muss eine Liste sein.');
  if (body.items.length > LIMITS.maxItems) throw new InvalidRequest(`Höchstens ${LIMITS.maxItems} Einträge.`);
  const seen = new Set();
  const out = [];
  for (const raw of body.items) {
    if (!isObject(raw)) throw new InvalidRequest('Ein Eintrag muss ein Objekt sein.');
    if (typeof raw.id !== 'string' || !ID.test(raw.id)) throw new InvalidRequest('id ist ungültig.');
    if (seen.has(raw.id)) throw new InvalidRequest(`id ${raw.id} kommt doppelt vor.`);
    seen.add(raw.id);
    if (typeof raw.blob !== 'string' || raw.blob.length > LIMITS.maxBlob) {
      throw new InvalidRequest(`blob muss ein Text bis ${LIMITS.maxBlob} Zeichen sein.`);
    }
    const fireAt = parseStamp(raw.fire_at);
    if (fireAt > now + LIMITS.maxAheadDays * DAY_MS) {
      throw new InvalidRequest(`fire_at höchstens ${LIMITS.maxAheadDays} Tage voraus.`);
    }
    if (now - fireAt > LIMITS.graceSeconds * 1000) continue;
    out.push({ id: raw.id, fireAt, blob: raw.blob });
  }
  return out;
}
