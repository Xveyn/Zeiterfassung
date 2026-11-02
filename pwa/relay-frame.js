// pwa/relay-frame.js
// Codec für den Abgleich über die Box des Relays (#358): Nachrichtenrahmen (1 Byte Typ + Nutzbytes)
// und die Nutzlast der Anfrage/Antwort (JSON in UTF-8). Reine Funktionen ohne Netz und DOM.
// Gegenstück am Desktop: `src/mobile_relay_codec.py`; den Gleichlauf hält
// `test/fixtures/relay-frames.json`. Die Box selbst: `relay/src/frames.js`.
export const SUBPROTOCOL = 'zeit.v1';
export const MAX_FRAME = 1_048_576;          // ganze Nachricht samt Typ-Byte (`LIMITS.maxFrame`)
export const MAX_PAYLOAD = MAX_FRAME - 1;    // Nutzbytes eines `put`
export const PUTS_PER_MINUTE = 60;           // `LIMITS.putsPerMinute`
export const TYPE = { put: 1, slot: 2, ok: 3 };

const PATHS = new Set(['/v1/pair', '/v1/sync']);
const TOKEN_RE = /^[\x21-\x7e]{1,512}$/;

const encoder = new TextEncoder();

export class RelayFrameError extends Error {
  constructor(code, message) {
    super(message ?? code);
    this.name = 'RelayFrameError';
    this.code = code;
  }
}

const invalid = (message) => new RelayFrameError('invalid_frame', message);
const tooLarge = () => new RelayFrameError('too_large', 'Nutzlast zu groß');

function isPlainObject(value) {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function isValidSeq(value) {
  return typeof value === 'number' && Number.isSafeInteger(value) && value >= 1;
}

/** Das gültige `seq` eines Umschlags (ganze Zahl 1…2^53−1) oder `null`. */
export function envelopeSeq(envelope) {
  if (!isPlainObject(envelope)) return null;
  return isValidSeq(envelope.seq) ? envelope.seq : null;
}

/** Typ-Byte + Nutzlast. Größer als `MAX_PAYLOAD` Bytes wirft `too_large`. */
export function encodePut(payload) {
  if (!(payload instanceof Uint8Array)) throw invalid('Nutzlast muss Uint8Array sein');
  if (payload.length > MAX_PAYLOAD) throw tooLarge();
  const out = new Uint8Array(1 + payload.length);
  out[0] = TYPE.put;
  out.set(payload, 1);
  return out;
}

/** Nachricht der Box; `null` für Text, Unbekanntes, Abgeschnittenes und Leeres. Wirft nie. */
export function decodeMessage(data) {
  try {
    let view;
    if (data instanceof ArrayBuffer) view = new Uint8Array(data);
    else if (data instanceof Uint8Array) view = data;
    else return null;
    if (view.length < 5) return null;
    const type = view[0];
    if (type !== TYPE.slot && type !== TYPE.ok) return null;
    const ver = new DataView(view.buffer, view.byteOffset, view.byteLength).getUint32(1, false);
    if (type === TYPE.ok) return { kind: 'ok', ver };
    return { kind: 'slot', ver, data: view.slice(5) };
  } catch {
    // Fremde Eingabe (z. B. abgetrennter Puffer): wie ein unbekannter Rahmen übergehen.
    return null;
  }
}

function parseJson(bytes) {
  if (!(bytes instanceof Uint8Array)) throw invalid('Bytes erwartet');
  if (bytes.length > MAX_PAYLOAD) throw tooLarge();
  let value;
  try {
    value = JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(bytes));
  } catch {
    throw invalid('Kein gültiges JSON in UTF-8');
  }
  if (!isPlainObject(value)) throw invalid('JSON-Objekt erwartet');
  return value;
}

function checkRequest(path, token, envelope) {
  if (typeof path !== 'string' || !PATHS.has(path)) throw invalid('Pfad nicht erlaubt');
  if (token === null) {
    if (path !== '/v1/pair') throw invalid('Token fehlt');
  } else if (typeof token !== 'string' || !TOKEN_RE.test(token)) {
    throw invalid('Token ungültig');
  }
  if (!isPlainObject(envelope)) throw invalid('Umschlag muss ein Objekt sein');
}

/** Anfrage-Nutzlast (UTF-8-JSON, Schlüsselreihenfolge fest); gleiche Regeln wie `decodeRequest`. */
export function encodeRequest(request) {
  if (!isPlainObject(request)) throw invalid('Anfrage muss ein Objekt sein');
  const { path, token, envelope } = request;
  checkRequest(path, token, envelope);
  let text;
  try {
    text = JSON.stringify({ v: 1, path, token, envelope });
  } catch {
    throw invalid('Umschlag nicht serialisierbar');
  }
  const bytes = encoder.encode(text);
  if (bytes.length > MAX_PAYLOAD) throw tooLarge();
  return bytes;
}

/** Anfrage lesen (Tests und Rundlauf). Ungültiges `seq` im Umschlag ergibt `seq: null`, keinen Fehler. */
export function decodeRequest(bytes) {
  const value = parseJson(bytes);
  if (value.v !== 1) throw invalid('v muss 1 sein');
  const { path, token, envelope } = value;
  checkRequest(path, token, envelope);
  return { path, token, envelope, seq: envelopeSeq(envelope) };
}

/** Antwort lesen. `seq` ist `null` oder gültig; `status` ganze Zahl 100…599. */
export function decodeResponse(bytes) {
  const value = parseJson(bytes);
  if (value.v !== 1) throw invalid('v muss 1 sein');
  const { status, seq, body } = value;
  if (!Number.isInteger(status) || status < 100 || status > 599) throw invalid('status ungültig');
  if (seq !== null && !isValidSeq(seq)) throw invalid('seq ungültig');
  if (!isPlainObject(body)) throw invalid('body muss ein Objekt sein');
  return { status, seq, body };
}

/** Gehört die Antwort zur offenen Anfrage? Ein `null`-`seq` gilt nur bei Fehlerstatus (>= 400). */
export function isCurrentResponse(frame, pendingSeq) {
  return frame.seq === pendingSeq || (frame.seq === null && frame.status >= 400);
}
