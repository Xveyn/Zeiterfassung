// pwa/relay-client.js
// Gespräch mit dem Push-Relay (`relay/`, ein Cloudflare Worker): Gerät anmelden, Zeitplan
// ersetzen, alles löschen. Das Geheimnis dieses Handys ist Identität und Bearer zugleich; es
// kommt in keinen Fehlertext. Fehler bleiben lokal: der Relay ist nie Voraussetzung.
export const RELAY_URL = 'https://zeiterfassung-push.svenbirkendahl.workers.dev';
// Die Datenschutzhinweise zum Relay: eigene Seite der Web-App (`datenschutz.html`, Inhalt aus `docs/datenschutz.md`)
// und das Dokument im Projekt (dieselbe Adresse wie `PRIVACY_DOC_URL` am Desktop) als Ersatz, wenn die Seite es nicht laden kann.
export const PRIVACY_URL = './datenschutz.html';
export const PRIVACY_SOURCE_URL = 'https://github.com/Xveyn/Zeiterfassung/blob/master/docs/datenschutz.md';
// Der öffentliche VAPID-Schlüssel des Relays. Alle Abos hängen an ihm: nie wechseln (`relay/README.md`).
export const VAPID_PUBLIC = 'BMZUZQIW3QNwt2vJp3q47zAAx4lLADWA0_r3kQQeyMT3d_GXsyyTjNlgBd1fOMtuZvlJhsLu1QRbHsT0hQHzC20';
const TIMEOUT_MS = 15000;
// Mit `keepalive` überlebt eine Anfrage das Schließen der Seite (Zeit eingetragen, App sofort weggewischt: der neue
// Zeitplan muss den Relay trotzdem erreichen, #507). Browser begrenzen solche Anfragen auf 64 KiB und lehnen größere
// ab; ein großer Plan geht deshalb ohne hinaus.
const KEEPALIVE_MAX_BYTES = 60000;

const MESSAGES = {
  unauthorized: 'Der Relay hat das Gerät nicht erkannt.',
  no_subscription: 'Der Relay kennt dieses Abo nicht mehr.',
  too_large: 'Der Zeitplan ist für den Relay zu groß.',
  rate_limited: 'Zu viele Anfragen an den Relay, später wieder.',
  invalid: 'Der Relay hat den Zeitplan abgelehnt.',
  server: 'Der Relay antwortet gerade nicht.',
  offline: 'Der Relay ist nicht erreichbar.',
  gone: 'Das Abo dieses Geräts ist abgelaufen.',
  too_soon: 'Bitte einen Moment warten.',
  unknown_route: 'Der Relay kennt diese Funktion noch nicht.',
  push_failed: 'Der Push-Dienst hat die Nachricht nicht angenommen.',
};

export class RelayError extends Error {
  constructor(kind, status, cause) {
    super(MESSAGES[kind] ?? MESSAGES.server);
    this.name = 'RelayError';
    this.kind = kind;
    this.status = status;       // HTTP-Status der Antwort; fehlt bei `offline`
    this.cause = cause;         // nur bei `push_failed`: Status des Push-Dienstes, `network` oder `build`
  }
}

/** Die Art des Fehlers aus Status und Fehlercode des Relays (`{error: 'too_soon'}` …). Der Code
 *  unterscheidet nur, was der Status allein nicht trennt: die beiden `429` und `410`/`502` der Testroute. */
function kindOf(status, code) {
  if (status === 401) return 'unauthorized';
  if (status === 409) return 'no_subscription';
  if (status === 410) return 'gone';
  if (status === 413) return 'too_large';
  if (status === 429) return code === 'too_soon' ? 'too_soon' : 'rate_limited';
  if (status === 502 && code === 'push_failed') return 'push_failed';
  if (status >= 400 && status < 500) return 'invalid';
  return 'server';
}

/** Die Ursache aus der Antwort der Testroute; nur ein HTTP-Status, `network` oder `build` zählt. */
function causeOf(body) {
  const cause = body?.cause;
  if (Number.isInteger(cause) && cause >= 100 && cause <= 599) return cause;
  return cause === 'network' || cause === 'build' ? cause : undefined;
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
    const text = body === undefined ? undefined : JSON.stringify(body);
    try {
      response = await this._fetch(`${this._url}${path}`, {
        method,
        headers: { authorization: `Bearer ${secret}`, ...(text === undefined ? {} : { 'content-type': 'application/json' }) },
        body: text,
        keepalive: text === undefined || new TextEncoder().encode(text).length <= KEEPALIVE_MAX_BYTES,
        signal: AbortSignal.timeout(TIMEOUT_MS),
      });
    } catch {
      throw new RelayError('offline');
    }
    if (!response.ok) {
      const body = await response.json().catch(() => undefined);
      const kind = kindOf(response.status, body?.error);
      throw new RelayError(kind, response.status, kind === 'push_failed' ? causeOf(body) : undefined);
    }
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

  /** Lässt den Relay sofort eine Testbenachrichtigung senden (`POST /v1/test`), ohne den Zeitplan
   *  anzufassen. Ein alter Relay kennt die Route nicht (`404`): `unknown_route`. */
  async sendTest(secret) {
    try {
      await this._call('POST', '/v1/test', secret);
    } catch (error) {
      if (error instanceof RelayError && error.status === 404) {
        throw new RelayError('unknown_route');
      }
      throw error;
    }
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
