// pwa/crypto.js
// Gegenstück zu src/mobile_crypto.py (#249): AES-256-GCM, HKDF-SHA-256, Umschlag
// {v: 2, seq, n, c}. Gleichlauf mit Python über test/fixtures/crypto-vectors.json — dieselbe
// Datei prüft tests/test_mobile_crypto.py. WebCrypto gibt es nur in sicheren Kontexten: die
// Seite kommt über https (Pages) oder von localhost (Dev-Server).
//
// Je Nachricht eine zufällige 96-Bit-Nonce; Anfrage und Antwort haben getrennte Schlüssel;
// die Zusatzdaten (AAD) binden Richtung, Methode, Pfad, Geräte-ID und Zähler.
// Nichts hier loggt oder speichert einen Schlüssel.
export const PROTOCOL = 2;
const NONCE_BYTES = 12;
const TAG_BYTES = 16;
const MAX_SEQ = Number.MAX_SAFE_INTEGER;
const B64URL = /^[A-Za-z0-9_-]*$/;
const ENVELOPE_KEYS = ['c', 'n', 'seq', 'v'];
const encoder = new TextEncoder();

export class CryptoFailure extends Error {
  /** `invalid_envelope`: die Form stimmt nicht. `decrypt_failed`: Schlüssel, Zusatzdaten oder
   *  Inhalt passen nicht (Fälschung, falscher Schlüssel, umgeleiteter Umschlag). */
  constructor(code, message) {
    super(message);
    this.name = 'CryptoFailure';
    this.code = code;
  }
}

export function b64e(bytes) {
  let binary = '';
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

/** Strenges base64url ohne Padding; auch die kanonische Form wird verlangt (die letzten Bits
 *  dürfen nicht gesetzt sein): es gibt genau eine Schreibweise. */
export function b64d(text) {
  if (typeof text !== 'string' || !B64URL.test(text) || text.length % 4 === 1) {
    throw new CryptoFailure('invalid_envelope', 'Ungültige Kodierung.');
  }
  const padded = text.replace(/-/g, '+').replace(/_/g, '/') + '='.repeat((4 - (text.length % 4)) % 4);
  const binary = atob(padded);
  const bytes = Uint8Array.from(binary, (character) => character.charCodeAt(0));
  if (b64e(bytes) !== text) throw new CryptoFailure('invalid_envelope', 'Ungültige Kodierung.');
  return bytes;
}

export async function deriveKey(secret, label) {
  const base = await crypto.subtle.importKey('raw', secret, 'HKDF', false, ['deriveBits']);
  const bits = await crypto.subtle.deriveBits(
    { name: 'HKDF', hash: 'SHA-256', salt: new Uint8Array(0), info: encoder.encode(`zeit-mobile/2/${label}`) },
    base, 256);
  return new Uint8Array(bits);
}

/** (Anfrage-, Antwortschlüssel) der Kopplung aus dem kanonischen Kopplungscode. */
export async function pairKeys(code) {
  const secret = encoder.encode(`code:${code}`);
  return [await deriveKey(secret, 'pair/request'), await deriveKey(secret, 'pair/response')];
}

/** (Anfrage-, Antwortschlüssel) des Abgleichs aus dem Geräteschlüssel `k_dev`. */
export async function deviceKeys(key) {
  return [await deriveKey(key, 'sync/request'), await deriveKey(key, 'sync/response')];
}

const validSeq = (value) => Number.isInteger(value) && value >= 1 && value <= MAX_SEQ;

/** Form eines Umschlags, ohne zu entschlüsseln: genau vier Felder, Version 2, Zähler ≥ 1,
 *  Nonce genau 12 Bytes, Chiffretext mindestens ein Tag. */
export function isEnvelope(obj) {
  if (obj === null || typeof obj !== 'object' || Array.isArray(obj)) return false;
  if (Object.keys(obj).sort().join() !== ENVELOPE_KEYS.join()) return false;
  if (obj.v !== PROTOCOL || !validSeq(obj.seq)) return false;
  try {
    return b64d(obj.n).length === NONCE_BYTES && b64d(obj.c).length >= TAG_BYTES;
  } catch {
    return false;
  }
}

function aad({ direction, method, path, deviceId, seq }) {
  return encoder.encode(`zeit-mobile/2|${direction}|${method}|${path}|${deviceId}|${seq}`);
}

const aesKey = (raw, usage) => crypto.subtle.importKey('raw', raw, 'AES-GCM', false, [usage]);

/** Verschlüsselt `plaintext` (Uint8Array). `nonce` nur für die Testvektoren; sonst zufällig. */
export async function seal(key, { direction, method, path, deviceId, seq, plaintext, nonce }) {
  if (!validSeq(seq)) throw new CryptoFailure('invalid_envelope', 'Ungültiger Zähler.');
  const iv = nonce ?? crypto.getRandomValues(new Uint8Array(NONCE_BYTES));
  const cipher = await crypto.subtle.encrypt(
    { name: 'AES-GCM', iv, additionalData: aad({ direction, method, path, deviceId, seq }), tagLength: 128 },
    await aesKey(key, 'encrypt'), plaintext);
  return { v: PROTOCOL, seq, n: b64e(iv), c: b64e(new Uint8Array(cipher)) };
}

/** Entschlüsselt. `seq = null`: der Zähler aus dem Umschlag; sonst muss er dem erwarteten
 *  entsprechen (Antwort: der Zähler der Anfrage). */
export async function openEnvelope(key, envelope, { direction, method, path, deviceId, seq = null }) {
  if (!isEnvelope(envelope)) throw new CryptoFailure('invalid_envelope', 'Ungültiger Umschlag.');
  if (seq !== null && envelope.seq !== seq) {
    throw new CryptoFailure('decrypt_failed', 'Die Nachricht passt nicht zur Anfrage.');
  }
  try {
    const plain = await crypto.subtle.decrypt(
      { name: 'AES-GCM', iv: b64d(envelope.n), tagLength: 128,
        additionalData: aad({ direction, method, path, deviceId, seq: envelope.seq }) },
      await aesKey(key, 'decrypt'), b64d(envelope.c));
    return new Uint8Array(plain);
  } catch (error) {
    if (error instanceof CryptoFailure) throw error;
    throw new CryptoFailure('decrypt_failed', 'Die Nachricht konnte nicht entschlüsselt werden.');
  }
}
