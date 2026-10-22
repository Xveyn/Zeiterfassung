// pwa/relay-client.js
// Gespräch mit dem Push-Relay (`relay/`, ein Cloudflare Worker): Gerät anmelden, Zeitplan
// ersetzen, alles löschen. Das Geheimnis dieses Handys ist Identität und Bearer zugleich; es
// kommt in keinen Fehlertext. Fehler bleiben lokal: der Relay ist nie Voraussetzung.
export const RELAY_URL = 'https://zeiterfassung-push.svenbirkendahl.workers.dev';
// Der öffentliche VAPID-Schlüssel des Relays. Alle Abos hängen an ihm: nie wechseln (`relay/README.md`).
export const VAPID_PUBLIC = 'BMZUZQIW3QNwt2vJp3q47zAAx4lLADWA0_r3kQQeyMT3d_GXsyyTjNlgBd1fOMtuZvlJhsLu1QRbHsT0hQHzC20';
const TIMEOUT_MS = 15000;

const MESSAGES = {
  unauthorized: 'Der Relay hat das Gerät nicht erkannt.',
  no_subscription: 'Der Relay kennt dieses Abo nicht mehr.',
  too_large: 'Der Zeitplan ist für den Relay zu groß.',
  rate_limited: 'Zu viele Anfragen an den Relay, später wieder.',
  invalid: 'Der Relay hat den Zeitplan abgelehnt.',
  server: 'Der Relay antwortet gerade nicht.',
  offline: 'Der Relay ist nicht erreichbar.',
};

export class RelayError extends Error {
  constructor(kind) {
    super(MESSAGES[kind] ?? MESSAGES.server);
    this.name = 'RelayError';
    this.kind = kind;
  }
}

function kindOf(status) {
  if (status === 401) return 'unauthorized';
  if (status === 409) return 'no_subscription';
  if (status === 413) return 'too_large';
  if (status === 429) return 'rate_limited';
  if (status >= 400 && status < 500) return 'invalid';
  return 'server';
}

/** 32 Zufallsbytes als base64url (43 Zeichen): die Form, die der Relay als Bearer erwartet. */
export function newSecret(random = (bytes) => crypto.getRandomValues(bytes)) {
  const bytes = random(new Uint8Array(32));
  return btoa(String.fromCharCode(...bytes)).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

export class RelayClient {
  constructor({ fetchFn = (...args) => fetch(...args), relayUrl = RELAY_URL } = {}) {
    this._fetch = fetchFn;
    this._url = relayUrl;
  }

  async _call(method, path, secret, body) {
    let response;
    try {
      response = await this._fetch(`${this._url}${path}`, {
        method,
        headers: { authorization: `Bearer ${secret}`, ...(body === undefined ? {} : { 'content-type': 'application/json' }) },
        body: body === undefined ? undefined : JSON.stringify(body),
        signal: AbortSignal.timeout(TIMEOUT_MS),
      });
    } catch {
      throw new RelayError('offline');
    }
    if (!response.ok) throw new RelayError(kindOf(response.status));
  }

  registerDevice(secret, subscription) {
    return this._call('PUT', '/v1/device', secret, subscription);
  }

  putSchedule(secret, items) {
    return this._call('PUT', '/v1/schedule', secret, { items });
  }

  deleteDevice(secret) {
    return this._call('DELETE', '/v1/device', secret);
  }
}

/** Zeitplan senden. Kennt der Relay das Abo nicht (mehr), einmal neu anmelden und wiederholen. */
export async function syncSchedule({ client, secret, subscription, items }) {
  try {
    await client.putSchedule(secret, items);
  } catch (error) {
    if (!(error instanceof RelayError) || error.kind !== 'no_subscription') throw error;
    await client.registerDevice(secret, subscription);
    await client.putSchedule(secret, items);
  }
}
