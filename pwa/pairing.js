// pwa/pairing.js
// Koppeln: Einmalcode, Adresse, Koppel-Link. Rein, ohne DOM und ohne Netz.
//
// Der Koppel-Link (`#pair=<ip>:<port>:<code>`, 28 Zeichen) stammt aus einem QR-Code und ist
// Fremdeingabe. Ohne die Adressprüfung könnte ein manipulierter Link das Handy dazu
// bringen, Code, Gerätenamen und -ID an einen beliebigen Host zu senden — deshalb nur
// private IPv4-Adressen, dieselbe Regel wie `netinfo.is_lan_address` am Desktop. Die
// Regeln prüft `tests/test_mobile_contract.py` gegen `test/fixtures/pairing-cases.json`.

export const PROTOCOL = 2;
export const DEFAULT_PORT = 17654;
// Ziffern 2–9 und Buchstaben ohne I, L, O: keine Verwechslung 0/O, 1/I/L.
export const CODE_ALPHABET = '23456789ABCDEFGHJKMNPQRSTUVWXYZ';
// 28 Zeichen aus 31 (≈139 Bit): der Kopplungscode verschlüsselt die Kopplung (crypto.js) und
// steht deshalb nie im Netz; er lässt sich in Gruppen zu vier abtippen.
export const CODE_LENGTH = 28;
const MAX_RAW_CODE_LENGTH = 64;
const MIN_PORT = 1024;
const MAX_PORT = 65535;
const MAX_DEVICE_NAME = 60;
const DEVICE_ID_RE = /^[A-Za-z0-9-]{8,64}$/;
const IPV4_RE = /^(0|[1-9][0-9]{0,2})\.(0|[1-9][0-9]{0,2})\.(0|[1-9][0-9]{0,2})\.(0|[1-9][0-9]{0,2})$/;

/** Eingabe oder Link-Teil → kanonischer Code (28 Zeichen aus dem Alphabet) oder `null`.
 *  Groß-/Kleinschreibung, Bindestriche und Leerzeichen sind egal. */
export function normalizeCode(raw) {
  if (typeof raw !== 'string' || raw.length > MAX_RAW_CODE_LENGTH) return null;
  const code = raw.trim().toUpperCase().replace(/[- ]/g, '');
  if (code.length !== CODE_LENGTH) return null;
  for (const character of code) {
    if (!CODE_ALPHABET.includes(character)) return null;
  }
  return code;
}

/** Private IPv4-Adresse (`10/8`, `172.16/12`, `192.168/16`) in kanonischer Schreibweise. */
export function isLanAddress(text) {
  if (typeof text !== 'string') return false;
  const match = IPV4_RE.exec(text);
  if (!match) return false;
  const [a, b] = [Number(match[1]), Number(match[2])];
  if (match.slice(1).some((part) => Number(part) > 255)) return false;
  return a === 10 || (a === 172 && b >= 16 && b <= 31) || (a === 192 && b === 168);
}

function parsePort(text) {
  if (typeof text !== 'string' || !/^[0-9]{1,5}$/.test(text)) return null;
  const port = Number(text);
  return port >= MIN_PORT && port <= MAX_PORT ? port : null;
}

/** `ip` oder `ip:port` (manuelle Eingabe) → `{host, port}` oder `null`. */
export function parseHostPort(text, defaultPort = DEFAULT_PORT) {
  if (typeof text !== 'string') return null;
  const parts = text.trim().split(':');
  if (parts.length > 2 || !isLanAddress(parts[0])) return null;
  if (parts.length === 1) return { host: parts[0], port: defaultPort };
  const port = parsePort(parts[1]);
  return port === null ? null : { host: parts[0], port };
}

/** `location.hash` → `{host, port, code}` oder `null`. Das Fragment geht nie an einen
 *  Server und trägt nur Adresse und Einmalcode, kein Token. */
export function parsePairFragment(hash) {
  if (typeof hash !== 'string' || !hash.startsWith('#pair=')) return null;
  const parts = hash.slice('#pair='.length).split(':');
  if (parts.length !== 3) return null;
  const target = parseHostPort(`${parts[0]}:${parts[1]}`);
  const code = normalizeCode(parts[2]);
  if (target === null || code === null || !/^[0-9]{1,5}$/.test(parts[1])) return null;
  return { host: target.host, port: target.port, code };
}

/** Gescannter QR-Text (der volle Link) → `{host, port, code}` oder `null`. Nur das Fragment
 *  zählt; Schema, Host und Pfad der Seite sind egal (Dev-Server, Pages, spätere Umzüge). */
export function parseQrText(text) {
  if (typeof text !== 'string' || text.length > 512) return null;
  const hash = text.indexOf('#');
  return hash === -1 ? null : parsePairFragment(text.slice(hash));
}

export function baseUrl({ host, port }) {
  return `http://${host}:${port}`;
}

export function isValidDeviceId(text) {
  return typeof text === 'string' && DEVICE_ID_RE.test(text);
}

/** Die Geräte-ID wird einmalig erzeugt und bleibt dauerhaft (auch über erneutes Koppeln):
 *  an ihr hängt die LWW-Identität des Handys im Sync. */
export function newDeviceId(cryptoObject = globalThis.crypto) {
  if (cryptoObject && typeof cryptoObject.randomUUID === 'function') return cryptoObject.randomUUID();
  const bytes = cryptoObject.getRandomValues(new Uint8Array(16));
  bytes[6] = (bytes[6] & 0x0f) | 0x40;                 // Version 4
  bytes[8] = (bytes[8] & 0x3f) | 0x80;                 // Variante 10
  const hex = Array.from(bytes, (byte) => byte.toString(16).padStart(2, '0')).join('');
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

/** Vorschlag für den Gerätenamen aus dem User-Agent („Pixel 7"); Chromes reduzierter
 *  User-Agent liefert nur „K", dann bleibt der Standardname. */
export function deviceNameFromUserAgent(userAgent) {
  const fallback = 'Android-Handy';
  if (typeof userAgent !== 'string') return fallback;
  const match = /\(Linux; Android [^;)]+; ([^)]+)\)/.exec(userAgent);
  if (!match) return fallback;
  const model = match[1].replace(/\s+Build\/\S+/, '').replace(/;\s*wv$/, '').trim().slice(0, MAX_DEVICE_NAME);
  return model.length > 1 ? model : fallback;
}

/** Der Klartext der Kopplungsanfrage — er wird verschlüsselt gesendet; der Code selbst ist nur
 *  der Schlüssel und steht nicht darin. */
export function pairRequestBody({ deviceName, deviceId }) {
  return { protocol: PROTOCOL, device_name: deviceName, device_id: deviceId };
}
