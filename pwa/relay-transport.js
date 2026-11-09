// pwa/relay-transport.js
// Der Weg zum Desktop über die Box des Relays (#358): je Austausch eine WebSocket, ein `put` mit der
// Anfrage, dann warten, bis das `res` mit der Nonce dieser Anfrage zugestellt wird. Gegenstück am
// Desktop: `src/relay_link.py`/`src/relay_adapter.py`; die Box: `relay/`. Kein DOM, die WebSocket kommt
// als Fabrik herein (Tests).
//
// Regeln (Spec „Leitidee“): Antworten zu einer anderen Anfrage (falsches `n`) werden übergangen und nie
// geöffnet; bei einem Abriss vor der Antwort geht **dieselbe** Anfrage noch einmal hinaus (der Desktop
// liefert die versiegelte Kopplungsantwort nur bei identischen Bytes erneut aus); `have` rückt mit jedem
// empfangenen `slot` vor, auch einem fremden. Das Geheimnis steht nur im Subprotocol, nie in URL, Log
// oder Fehlertext.
import { logFailure } from './diagnose.js';
import {
  RelayFrameError, SUBPROTOCOL, decodeMessage, decodeResponse, encodePut, encodeRequest, envelopeNonce,
  isCurrentResponse,
} from './relay-frame.js';
import { RELAY_URL } from './relay-client.js';
import { SyncError } from './sync-errors.js';

const MAX_HAVE = 2 ** 31 - 1;                 // `have` ist auf 2^31 − 1 begrenzt (Spec)

/** Nur der Name des Fehlers geht ins Log: Chromes Meldungstext zu einer WebSocket kann das Subprotocol nennen,
 *  also das Geheimnis. Der Name (`SecurityError`, `SyntaxError`) reicht, um zu sehen, woran es liegt. */
const nameOnly = (error) => ({ name: typeof error?.name === 'string' ? error.name : 'Error' });

const failure = (kind, code, message, retryable = false) => new SyncError({ kind, code, message, retryable });

const ERRORS = {
  unreachable: () => failure('offline', 'relay_unreachable', 'Der Relay ist nicht erreichbar.', true),
  silent: () => failure('desktop_silent', 'desktop_silent', 'Der Desktop antwortet nicht.', true),
  throttled: () => failure('throttled', 'throttled', 'Zu viele Anfragen an den Relay.', true),
  replaced: () => failure('transient', 'replaced', 'Eine zweite Verbindung dieser Web-App hat übernommen.', true),
  refused: () => failure('protocol', 'relay_protocol', 'Der Relay hat die Verbindung abgelehnt.'),
  tooLarge: () => failure('too_large', 'request_too_large', 'Die Anfrage ist für den Relay zu groß.'),
  notPost: () => failure('protocol', 'relay_protocol', 'Der Relay kennt nur POST-Anfragen.'),
};

function socketUrl(relayUrl, have) {
  const url = new URL(relayUrl);
  url.protocol = url.protocol === 'http:' ? 'ws:' : 'wss:';
  url.pathname = '/v1/box/ws';
  url.searchParams.set('role', 'phone');
  if (have > 0) url.searchParams.set('have', String(have));
  return url.toString();
}

export class RelayTransport {
  constructor({ webSocketFactory = (url, protocols) => new globalThis.WebSocket(url, protocols),
    relayUrl = RELAY_URL, timeoutMs = 15000, attempts = 2, log = logFailure } = {}) {
    this._factory = webSocketFactory;
    this._relayUrl = relayUrl;
    this._timeoutMs = timeoutMs;
    this._attempts = attempts;
    this._log = log;
  }

  /** `ackOnly`: löst beim `ok` des Relays mit `{status: 202, json: null}` auf, ohne auf eine Antwort des Desktops zu warten.
   *  @param {{method: string, path: string, token?: string|null, body: object, ackOnly?: boolean,
   *  endpoint: {kind: 'relay', secret: string, have?: number, onHave?: (ver: number) => void}}} request */
  async exchange({ method, path, token = null, body, endpoint, ackOnly = false }) {
    if (method !== 'POST') throw ERRORS.notPost();
    const nonce = envelopeNonce(body);
    if (nonce === null) throw ERRORS.refused();
    let payload;
    try {
      payload = encodePut(encodeRequest({ path, token, envelope: body }));
    } catch (error) {
      if (error instanceof RelayFrameError && error.code === 'too_large') throw ERRORS.tooLarge();
      throw ERRORS.refused();
    }
    const state = { have: Number.isInteger(endpoint.have) && endpoint.have > 0 ? endpoint.have : 0, accepted: false };
    const deadline = Date.now() + this._timeoutMs;
    for (let attempt = 0; attempt < this._attempts; attempt += 1) {
      const remaining = deadline - Date.now();
      if (remaining <= 0) break;
      // `ok` gilt für diesen Versuch: ein früheres `ok` macht einen nun unerreichbaren Relay nicht zum
      // schweigenden Desktop.
      state.accepted = false;
      const outcome = await this._attempt({ endpoint, payload, nonce, state, remaining, ackOnly });
      if (outcome.response) return outcome.response;
      if (outcome.timedOut) break;
    }
    throw state.accepted ? ERRORS.silent() : ERRORS.unreachable();
  }

  /** Eine Verbindung. Löst mit `{ response }` (fertig), `{ dropped: true }` (neu versuchen) oder
   *  `{ timedOut: true }` auf; wirft bei einem Schließcode, der kein Neuverbinden verträgt. */
  _attempt({ endpoint, payload, nonce, state, remaining, ackOnly }) {
    return new Promise((resolve, reject) => {
      let socket;
      let timer = null;
      let settled = false;
      const finish = (action) => {
        if (settled) return;
        settled = true;
        clearTimeout(timer);
        try {
          socket?.close();
        } catch {
          // Schon zu: nichts mehr zu schließen.
        }
        action();
      };
      const advance = (ver) => {
        if (ver > state.have && ver <= MAX_HAVE) {
          state.have = ver;
          endpoint.onHave?.(ver);
        }
      };
      try {
        socket = this._factory(socketUrl(this._relayUrl, state.have), [SUBPROTOCOL, endpoint.secret]);
      } catch (error) {
        this._log('Relay: WebSocket nicht aufgebaut', nameOnly(error));
        resolve({ dropped: true });
        return;
      }
      socket.binaryType = 'arraybuffer';
      timer = setTimeout(() => finish(() => resolve({ timedOut: true })), remaining);
      socket.addEventListener('open', () => {
        try {
          socket.send(payload);
        } catch (error) {
          this._log('Relay: Senden fehlgeschlagen', nameOnly(error));
          finish(() => resolve({ dropped: true }));
        }
      });
      socket.addEventListener('message', (event) => {
        const message = decodeMessage(event.data);
        if (message === null) return;
        if (message.kind === 'ok') {
          state.accepted = true;
          // Abmeldung (#499): die Anfrage liegt in der Box, der Desktop holt sie ab, wenn er verbindet; auf
          // seine Antwort wartet niemand, das Handy löscht danach seine Daten.
          if (ackOnly) finish(() => resolve({ response: { status: 202, json: null } }));
          return;
        }
        advance(message.ver);
        let frame;
        try {
          frame = decodeResponse(message.data);
        } catch (error) {
          this._log('Relay: Antwort übergangen', error instanceof RelayFrameError ? error : new Error('unlesbar'));
          return;
        }
        if (isCurrentResponse(frame, nonce)) {
          finish(() => resolve({ response: { status: frame.status, json: frame.body } }));
        } else {
          this._log('Relay: fremde Antwort übergangen', new Error('anderes n'));
        }
      });
      socket.addEventListener('close', (event) => {
        const code = event?.code;
        const reason = event?.reason;
        if (code === 1008) finish(() => reject(ERRORS.throttled()));
        else if (code === 1000 && reason === 'replaced') finish(() => reject(ERRORS.replaced()));
        else if (code === 1009 || code === 1003) finish(() => reject(ERRORS.refused()));
        else {
          if (code === 1000 && reason === 'wiped') {
            state.have = 0;
            endpoint.onHave?.(0);
          }
          finish(() => resolve({ dropped: true }));
        }
      });
    });
  }
}
