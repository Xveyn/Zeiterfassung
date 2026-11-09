// pwa/lock.js
// App-Sperre über die Geräte-Entsperrung (#490, Stufe 2): WebAuthn mit einem Plattform-Authenticator
// (Face ID/Touch ID, Android-Biometrie, Windows Hello) und `userVerification: required`. Die Biometrie bleibt auf dem
// Gerät, die Seite erfährt nur, dass der Nutzer verifiziert wurde. Verifizierung kann auch die Geräte-PIN sein; der Text
// sagt deshalb „Geräte-Entsperrung“ und nie „Biometrie“.
//
// Das ist eine **Komfort-Sperre** für die Oberfläche, kein Schutz der gespeicherten Daten: ohne Server gibt es keinen
// Prüfer, der die Signatur der Antwort einem anderen Beteiligten gegenüber belegen könnte, und Skript in der Seite kann die
// Sperre ohnehin umgehen. Geprüft werden Challenge, Typ, Herkunft des Authenticators (rpId-Hash), Credential-ID und die
// Flags „Anwesenheit“ und „Verifizierung“ — nicht die Signatur.
//
// DOM-frei: Browser-Schnittstellen (`credentials`, `PublicKeyCredential`) kommen als Parameter herein (Tests).
import { b64d, b64e } from './crypto.js';

export const LOCK_DELAYS = Object.freeze([0, 60_000, 300_000]);   // Sofort, 1 Minute, 5 Minuten
export const DEFAULT_LOCK_DELAY_MS = 60_000;
const DELAY_LABELS = new Map([[0, 'Sofort'], [60_000, 'Nach 1 Minute'], [300_000, 'Nach 5 Minuten']]);
const TIMEOUT_MS = 60_000;
const ABORT_AFTER_MS = 65_000;             // etwas länger als `timeout` der Abfrage: ein Browser, der es ignoriert, hinge sonst ewig
const FLAG_UP = 0x01;                      // user present
const FLAG_UV = 0x04;                      // user verified
const encoder = new TextEncoder();
const decoder = new TextDecoder();
const randomBytes = (length) => crypto.getRandomValues(new Uint8Array(length));

/** Nur die angebotenen Fristen gelten; alles andere (gespeichert von einem anderen Stand) zeigt die Standardfrist. */
export function normalizeLockDelay(value) {
  return LOCK_DELAYS.includes(value) ? value : DEFAULT_LOCK_DELAY_MS;
}

/** Die Sperre gilt nur mit eingeschaltetem Schalter **und** gespeicherter Credential-ID. */
export function lockActive(meta) {
  return meta !== null && typeof meta === 'object' && meta.lock_enabled === true
    && typeof meta.lock_credential === 'string' && meta.lock_credential !== '';
}

/** Soll nach dem Zurückkehren gesperrt werden? `hiddenAt`: wann die Seite unsichtbar wurde (ms, `Date.now()`). Eine
 *  zurückgestellte Uhr sperrt (im Zweifel zu), sie verlängert die Frist nie. */
export function shouldLock({ active, hiddenAt, now, delayMs }) {
  if (!active || typeof hiddenAt !== 'number' || !Number.isFinite(hiddenAt)) return false;
  if (now < hiddenAt) return true;
  return now - hiddenAt >= normalizeLockDelay(delayMs);
}

/** Kann dieses Gerät die Sperre anbieten? `reason`: `insecure` | `no_api` | `no_authenticator` | `null`. */
export async function lockSupport({ credentials, publicKeyCredential, secure }) {
  if (secure !== true) return { available: false, reason: 'insecure' };
  if (!credentials || typeof credentials.create !== 'function' || typeof credentials.get !== 'function' || !publicKeyCredential) {
    return { available: false, reason: 'no_api' };
  }
  try {
    if (await publicKeyCredential.isUserVerifyingPlatformAuthenticatorAvailable?.() === true) return { available: true, reason: null };
  } catch {
    // Bewusst alles: ein Browser, der die Abfrage selbst nicht beantworten kann, bietet die Sperre nicht an.
  }
  return { available: false, reason: 'no_authenticator' };
}

/** Wie `Promise.race` gegen eine Frist; ein Ablauf zählt wie ein Abbruch (`AbortError`). */
function withTimeout(promise, ms) {
  let timer;
  const expired = new Promise((_, reject) => { timer = setTimeout(() => reject(new DOMException('Zeitüberschreitung', 'AbortError')), ms); });
  return Promise.race([promise, expired]).finally(() => clearTimeout(timer));
}

/** Abgebrochen (Nutzer, Zeitüberschreitung, und bei einem unbekannten Passkey auch das — Browser liefern dafür
 *  absichtlich denselben Fehler) oder kaputt. */
const reasonOf = (error) => (error?.name === 'NotAllowedError' || error?.name === 'AbortError' ? 'cancelled' : 'failed');
const FAILED = Object.freeze({ ok: false, reason: 'failed' });

/** Ergebnis für eine Ausnahme; nur ein unerwarteter Fehler (nicht „abgebrochen“) geht an `onError` (das Debug-Protokoll). */
function failure(error, onError) {
  const reason = reasonOf(error);
  if (reason === 'failed') onError?.(error);
  return { ok: false, reason };
}

/** Legt den Passkey für die Sperre an. `{ok: true, id}` mit der Credential-ID (base64url) oder `{ok: false, reason}`. */
export async function createLockCredential({ credentials, rpId, random = randomBytes, timeoutMs = ABORT_AFTER_MS, onError }) {
  let credential;
  try {
    credential = await withTimeout(credentials.create({ publicKey: {
      rp: { id: rpId, name: 'Zeiterfassung' },
      user: { id: random(16), name: 'zeiterfassung', displayName: 'Zeiterfassung' },
      challenge: random(32),
      pubKeyCredParams: [{ type: 'public-key', alg: -7 }, { type: 'public-key', alg: -257 }],
      authenticatorSelection: { authenticatorAttachment: 'platform', userVerification: 'required', residentKey: 'discouraged' },
      attestation: 'none',
      timeout: TIMEOUT_MS,
    } }), timeoutMs);
    if (!credential || credential.type !== 'public-key') return FAILED;
    return { ok: true, id: b64e(new Uint8Array(credential.rawId)) };
  } catch (error) {
    return failure(error, onError);
  }
}

const sameBytes = (a, b) => a.length === b.length && a.every((value, index) => value === b[index]);

async function verifyAssertion(result, { rpId, challenge, id }) {
  try {
    if (!result || result.type !== 'public-key' || !result.response) return FAILED;
    if (b64e(new Uint8Array(result.rawId)) !== id) return FAILED;
    const client = JSON.parse(decoder.decode(result.response.clientDataJSON));
    if (client.type !== 'webauthn.get' || client.challenge !== b64e(challenge)) return FAILED;
    const data = new Uint8Array(result.response.authenticatorData);
    if (data.length < 37) return FAILED;
    const expected = new Uint8Array(await crypto.subtle.digest('SHA-256', encoder.encode(rpId)));
    if (!sameBytes(data.subarray(0, 32), expected)) return FAILED;
    return (data[32] & (FLAG_UP | FLAG_UV)) === (FLAG_UP | FLAG_UV) ? { ok: true } : { ok: false, reason: 'unverified' };
  } catch {
    // Bewusst alles: eine Antwort in unerwarteter Form (kein JSON, abgeschnittene Daten) entsperrt nie.
    return FAILED;
  }
}

/** Fragt die Geräte-Entsperrung ab. `{ok: true}` nur, wenn die Antwort zu dieser Anfrage, diesem Passkey und dieser Seite
 *  gehört und der Authenticator Anwesenheit **und** Verifizierung meldet. Wirft nie. */
export async function unlockWithCredential({ credentials, rpId, id, random = randomBytes, timeoutMs = ABORT_AFTER_MS, onError }) {
  let credentialId;
  try {
    credentialId = b64d(id);
  } catch {
    return FAILED;                                      // eine unlesbare gespeicherte ID kann nichts entsperren
  }
  const challenge = random(32);
  let result;
  try {
    result = await withTimeout(credentials.get({ publicKey: {
      rpId,
      challenge,
      allowCredentials: [{ type: 'public-key', id: credentialId, transports: ['internal'] }],
      userVerification: 'required',
      timeout: TIMEOUT_MS,
    } }), timeoutMs);
  } catch (error) {
    return failure(error, onError);
  }
  return verifyAssertion(result, { rpId, challenge, id });
}

/** Einschalten, zweiter Schritt: erst nach einer gelungenen Probe-Entsperrung gilt die Sperre. `probe(id)` fragt den Passkey ab. */
export async function enableLock({ id, probe, setMeta }) {
  const result = await probe(id);
  if (!result.ok) return { ok: false, reason: result.reason };
  await setMeta({ lock_enabled: true, lock_credential: id });
  return { ok: true };
}

/** Ausschalten verlangt die Entsperrung: wer die offene App in der Hand hat, soll die Sperre nicht einfach abschalten. */
export async function disableLock({ meta, probe, setMeta }) {
  const result = await probe(meta.lock_credential);
  if (!result.ok) return { ok: false, reason: result.reason };
  await setMeta({ lock_enabled: false, lock_credential: '' });
  return { ok: true };
}

/** Ein Merker für eine Zahl (ms) in `sessionStorage`: überlebt das Neuladen des Tabs, nicht sein Schließen. `getStorage`
 *  liefert den Speicher (oder wirft, etwa im privaten Fenster); jeder Fehler heißt „nichts gemerkt“. Gelesen wird nur eine
 *  endliche Zahl. */
export function createSessionSlot(getStorage, key) {
  return {
    read() {
      try {
        const raw = getStorage().getItem(key);
        if (raw === null || raw === '') return null;
        const value = Number(raw);
        return Number.isFinite(value) ? value : null;
      } catch {
        return null;
      }
    },
    write(value) {
      try {
        const storage = getStorage();
        if (value === null) storage.removeItem(key);
        else storage.setItem(key, String(value));
      } catch {
        // Kein Speicher: dann sperrt ein Neuladen wie bisher.
      }
    },
  };
}

/** Der Ablauf der Sperre ohne Oberfläche: wann gesperrt wird, was ein Entsperren tut, und ein Tag, der währenddessen geöffnet
 *  werden soll. Die Oberfläche hängt sich über `onLock`/`onUnlock` ein; `onUnlock(day)` läuft, **nachdem** `locked` falsch ist
 *  (der Dialog öffnet sich sonst in seinem `close`-Handler wieder). `now` ist die Uhr (ms). */
export function createLockController({ getMeta, now, unlockCredential, onLock, onUnlock, session = null }) {
  let locked = false;
  let hiddenAt = null;
  let pendingDay = null;
  // `session` (Merker, der ein Neuladen des Tabs übersteht, `createSessionSlot`) hält fest, **wann die entsperrte Seite
  // verlassen wurde**. Ein Neuladen (Wischen zum Aktualisieren) gilt dann wie ein Zurückkehren: innerhalb der Frist keine neue
  // Abfrage. Er wird beim Start, beim Zurückkehren und beim Entsperren verbraucht; gesperrt wird nie etwas gemerkt, und ein
  // Fehler des Speichers heißt immer „nichts gemerkt“ (also sperren).
  const remember = (value) => {
    try { session?.write(value); } catch { /* Speicher gesperrt oder privates Fenster: dann gilt der Start wie bisher */ }
  };
  const recall = () => {
    try { return session?.read() ?? null; } catch { return null; }
  };
  const lock = () => {
    if (locked) return;
    locked = true;
    onLock();
  };
  return {
    get locked() { return locked; },
    /** Bei einem Start: gesperrt, sobald die Sperre eingeschaltet ist — außer dies ist ein Neuladen innerhalb der Frist
     *  (die entsperrte Seite wurde gerade erst verlassen). */
    start() {
      const meta = getMeta();
      if (!lockActive(meta)) return locked;
      const leftAt = recall();
      remember(null);
      // Nur eine echte Zahl zählt: `shouldLock` liest eine unbrauchbare Zeit als „nie verlassen“ und sperrte dann nicht.
      const resumed = typeof leftAt === 'number' && Number.isFinite(leftAt)
        && !shouldLock({ active: true, hiddenAt: leftAt, now: now(), delayMs: meta.lock_delay_ms });
      if (!resumed) lock();
      return locked;
    },
    hidden() {
      hiddenAt = now();
      remember(locked ? null : hiddenAt);
    },
    /** Nach dem Zurückkehren: ist die Frist abgelaufen, sperrt es. Die Verlassen-Zeit gilt danach als verbraucht. */
    visible() {
      const meta = getMeta();
      if (shouldLock({ active: lockActive(meta), hiddenAt, now: now(), delayMs: meta.lock_delay_ms })) lock();
      hiddenAt = null;
      remember(null);
      return locked;
    },
    async unlock() {
      const result = await unlockCredential(getMeta().lock_credential);
      if (!result.ok) return result;
      locked = false;
      // Zeigt der Browser während der Abfrage `hidden` und danach `visible`, würde „Sofort“ sonst gleich wieder sperren.
      hiddenAt = null;
      remember(null);
      const day = pendingDay;
      pendingDay = null;
      onUnlock(day);
      return result;
    },
    /** Öffnet `date` über `open`, außer es ist gesperrt: dann wird der Tag (der letzte) für nach dem Entsperren vorgemerkt. */
    openDay(date, open) {
      if (locked) {
        pendingDay = date;
        return false;
      }
      open(date);
      return true;
    },
  };
}

const ERROR_TEXTS = {
  insecure: 'Die Sperre braucht eine sichere Verbindung (https).',
  no_api: 'Dieser Browser unterstützt die Geräte-Entsperrung nicht.',
  no_authenticator: 'Auf diesem Gerät ist keine Bildschirmsperre oder Biometrie eingerichtet, die der Browser dafür nutzen kann.',
  pending: 'Die Prüfung, ob dieses Gerät die Entsperrung anbietet, läuft noch. Einstellungen später noch einmal öffnen.',
  cancelled: 'Die Entsperrung wurde nicht bestätigt.',
  failed: 'Die Entsperrung hat nicht funktioniert.',
  unverified: 'Das Gerät hat nicht bestätigt, dass du es entsperrt hast.',
};

export const lockErrorText = (reason) => ERROR_TEXTS[reason] ?? ERROR_TEXTS.failed;

const NOTE = 'Sperrt die Oberfläche der App, bis du das Gerät entsperrst (Fingerabdruck, Gesicht oder Geräte-PIN, je nach Handy). Die gespeicherten Daten werden dadurch nicht verschlüsselt oder geschützt.';

/** Was der Abschnitt „Sperre“ im Reiter „Verbindung“ zeigt. */
export function lockModel({ meta, support, busy = false }) {
  const stored = meta ?? {};
  const available = support?.available === true;
  const on = lockActive(stored);
  return {
    available,
    on,
    canChange: available && !busy,
    delayMs: normalizeLockDelay(stored.lock_delay_ms),
    delayDisabled: !on || busy,
    delayOptions: LOCK_DELAYS.map((value) => ({ value, label: DELAY_LABELS.get(value) })),
    hint: available ? '' : lockErrorText(support?.reason),
    note: NOTE,
  };
}
