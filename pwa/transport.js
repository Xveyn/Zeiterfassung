// pwa/transport.js
// Wie eine verschlüsselte Anfrage zum Desktop kommt: `LanTransport` (HTTP im WLAN, heutiges `fetch`)
// und, in `relay-transport.js`, der Weg über die Box des Relays (#358). Beide liefern `{status, json}`;
// die Einordnung von Fehlerstatus und die Verschlüsselung bleiben im `SyncClient`. Ein Netzfehler wird
// als `SyncError` geworfen, ein Fehlerstatus nicht.
import { baseUrl } from './pairing.js';
import { classifyNetworkError } from './sync-errors.js';

export class LanTransport {
  constructor({ fetchFn = (...args) => globalThis.fetch(...args), timeoutMs = 15000 } = {}) {
    this._fetch = fetchFn;
    this._timeoutMs = timeoutMs;
  }

  /** @param {{method: string, path: string, token?: string|null, body?: object|null,
   *  endpoint: {kind: 'lan', host: string, port: number}}} request */
  async exchange({ method, path, token = null, body = null, endpoint }) {
    const headers = { Accept: 'application/json' };
    if (token) headers.Authorization = `Bearer ${token}`;
    if (body !== null) headers['Content-Type'] = 'application/json';
    let response;
    try {
      response = await this._fetch(`${baseUrl(endpoint)}${path}`, {
        method, headers, body: body === null ? undefined : JSON.stringify(body),
        cache: 'no-store', credentials: 'omit',
        signal: AbortSignal.timeout(this._timeoutMs),
        targetAddressSpace: 'local',
      });
    } catch (error) {
      throw classifyNetworkError(error);
    }
    let json = null;
    try {
      json = await response.json();
    } catch {
      json = null;                                  // kein JSON: der Statuscode entscheidet
    }
    return { status: response.status, json };
  }
}

/** Wohin eine Kopplung spricht: `{kind: 'lan', host, port}` oder `null` (nicht gekoppelt). */
export function endpointOf(meta) {
  if (!meta || !meta.token || !meta.address) return null;
  return { kind: 'lan', host: meta.address.host, port: meta.address.port };
}

export function isPaired(meta) {
  return endpointOf(meta) !== null;
}
