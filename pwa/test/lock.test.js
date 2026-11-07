// pwa/test/lock.test.js
import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
  DEFAULT_LOCK_DELAY_MS, LOCK_DELAYS, createLockController, createLockCredential, disableLock, enableLock, lockActive,
  lockErrorText, lockModel, lockSupport, normalizeLockDelay, shouldLock, unlockWithCredential,
} from '../lock.js';
import { b64d, b64e } from '../crypto.js';

const RP = 'xveyn.github.io';
const ID = Uint8Array.from({ length: 32 }, (_, i) => i + 1);
const ID_TEXT = b64e(ID);
const utf8 = (text) => new TextEncoder().encode(text);

async function authenticatorData(flags, rpId = RP) {
  const out = new Uint8Array(37);
  out.set(new Uint8Array(await crypto.subtle.digest('SHA-256', utf8(rpId))));
  out[32] = flags;
  return out.buffer;
}

/** Ein Browser-`credentials`, der Anfragen mitschreibt und eine echte Form der Antwort baut. Die Abweichungen
 *  (`flags`, `rpId`, `type` …) lassen einzelne Prüfungen von `unlockWithCredential` kippen. */
function fakeCredentials({ flags = 0x05, rpId = RP, type = 'webauthn.get', rawId = ID, createFails, getFails, challenge,
  getResult } = {}) {
  const calls = { create: [], get: [] };
  return {
    calls,
    async create(options) {
      calls.create.push(options);
      if (createFails) throw createFails;
      return { type: 'public-key', rawId: rawId.buffer, response: {} };
    },
    async get(options) {
      calls.get.push(options);
      if (getFails) throw getFails;
      if (getResult !== undefined) return getResult;
      const sent = b64e(new Uint8Array(options.publicKey.challenge));
      return {
        type: 'public-key',
        rawId: rawId.buffer,
        response: {
          clientDataJSON: utf8(JSON.stringify({ type, challenge: challenge ?? sent, origin: `https://${RP}` })).buffer,
          authenticatorData: await authenticatorData(flags, rpId),
        },
      };
    },
  };
}

const bad = (name) => new DOMException('abgelehnt', name);

// --- Frist ------------------------------------------------------------------------------------------

test('only the offered delays are valid, anything else falls back to the default', () => {
  assert.deepEqual([...LOCK_DELAYS], [0, 60_000, 300_000]);
  assert.equal(DEFAULT_LOCK_DELAY_MS, 60_000);
  for (const value of LOCK_DELAYS) assert.equal(normalizeLockDelay(value), value);
  for (const value of [-1, 1, 59_999, '60000', null, undefined, NaN, Infinity, {}]) {
    assert.equal(normalizeLockDelay(value), DEFAULT_LOCK_DELAY_MS, String(value));
  }
});

test('the lock is active only with the switch on and a credential', () => {
  assert.equal(lockActive({ lock_enabled: true, lock_credential: ID_TEXT }), true);
  assert.equal(lockActive({ lock_enabled: true, lock_credential: '' }), false);
  assert.equal(lockActive({ lock_enabled: false, lock_credential: ID_TEXT }), false);
  assert.equal(lockActive({ lock_enabled: 'ja', lock_credential: ID_TEXT }), false);
  assert.equal(lockActive({ lock_enabled: true, lock_credential: 7 }), false);
  assert.equal(lockActive({}), false);
  assert.equal(lockActive(null), false);
});

test('shouldLock follows the delay and fails closed when the clock went backwards', () => {
  const base = { active: true, hiddenAt: 1_000_000, delayMs: 60_000 };
  assert.equal(shouldLock({ ...base, now: 1_000_000 + 59_999 }), false);
  assert.equal(shouldLock({ ...base, now: 1_000_000 + 60_000 }), true);
  assert.equal(shouldLock({ ...base, now: 1_000_000 + 600_000 }), true);
  assert.equal(shouldLock({ ...base, delayMs: 0, now: 1_000_000 }), true);                // „Sofort“
  assert.equal(shouldLock({ ...base, now: 1_000_000 - 1 }), true);                        // Uhr zurückgestellt
  assert.equal(shouldLock({ ...base, delayMs: 'kaputt', now: 1_000_000 + 59_999 }), false);   // Standardfrist gilt
  assert.equal(shouldLock({ ...base, delayMs: 'kaputt', now: 1_000_000 + 60_000 }), true);
});

test('shouldLock never locks an inactive lock or an app that was not hidden', () => {
  assert.equal(shouldLock({ active: false, hiddenAt: 0, now: 1e12, delayMs: 0 }), false);
  assert.equal(shouldLock({ active: true, hiddenAt: null, now: 1e12, delayMs: 0 }), false);
  assert.equal(shouldLock({ active: true, hiddenAt: undefined, now: 1e12, delayMs: 0 }), false);
  assert.equal(shouldLock({ active: true, hiddenAt: NaN, now: 1e12, delayMs: 0 }), false);
});

// --- Unterstützung ----------------------------------------------------------------------------------

test('lockSupport names why the lock is not available', async () => {
  const credentials = fakeCredentials();
  const platform = (available) => ({ isUserVerifyingPlatformAuthenticatorAvailable: async () => available });
  assert.deepEqual(await lockSupport({ credentials, publicKeyCredential: platform(true), secure: false }),
    { available: false, reason: 'insecure' });
  assert.deepEqual(await lockSupport({ credentials: undefined, publicKeyCredential: platform(true), secure: true }),
    { available: false, reason: 'no_api' });
  assert.deepEqual(await lockSupport({ credentials, publicKeyCredential: undefined, secure: true }),
    { available: false, reason: 'no_api' });
  assert.deepEqual(await lockSupport({ credentials, publicKeyCredential: platform(false), secure: true }),
    { available: false, reason: 'no_authenticator' });
  assert.deepEqual(await lockSupport({ credentials, publicKeyCredential: {}, secure: true }),
    { available: false, reason: 'no_authenticator' });
  assert.deepEqual(await lockSupport({ credentials, secure: true, publicKeyCredential: {
    isUserVerifyingPlatformAuthenticatorAvailable: async () => { throw new Error('kaputt'); } } }),
  { available: false, reason: 'no_authenticator' });
  assert.deepEqual(await lockSupport({ credentials, publicKeyCredential: platform(true), secure: true }),
    { available: true, reason: null });
});

// --- Anlegen ----------------------------------------------------------------------------------------

test('creating the credential asks for a platform authenticator with user verification', async () => {
  const credentials = fakeCredentials();
  const result = await createLockCredential({ credentials, rpId: RP });

  assert.deepEqual(result, { ok: true, id: ID_TEXT });
  const { publicKey } = credentials.calls.create[0];
  assert.equal(publicKey.rp.id, RP);
  assert.equal(publicKey.authenticatorSelection.authenticatorAttachment, 'platform');
  assert.equal(publicKey.authenticatorSelection.userVerification, 'required');
  assert.equal(publicKey.authenticatorSelection.residentKey, 'discouraged');
  assert.equal(publicKey.attestation, 'none');
  assert.deepEqual(publicKey.pubKeyCredParams.map((p) => p.alg).sort(), [-257, -7]);
  assert.equal(new Uint8Array(publicKey.challenge).length, 32);
  assert.equal(new Uint8Array(publicKey.user.id).length, 16);
});

test('every creation uses a fresh challenge and user id', async () => {
  const credentials = fakeCredentials();
  await createLockCredential({ credentials, rpId: RP });
  await createLockCredential({ credentials, rpId: RP });
  const [a, b] = credentials.calls.create.map((c) => c.publicKey);
  assert.notDeepEqual(new Uint8Array(a.challenge), new Uint8Array(b.challenge));
  assert.notDeepEqual(new Uint8Array(a.user.id), new Uint8Array(b.user.id));
});

test('a refused or broken creation is reported without throwing', async () => {
  assert.deepEqual(await createLockCredential({ credentials: fakeCredentials({ createFails: bad('NotAllowedError') }), rpId: RP }),
    { ok: false, reason: 'cancelled' });
  assert.deepEqual(await createLockCredential({ credentials: fakeCredentials({ createFails: bad('AbortError') }), rpId: RP }),
    { ok: false, reason: 'cancelled' });
  for (const name of ['SecurityError', 'NotSupportedError', 'ConstraintError', 'InvalidStateError']) {
    assert.deepEqual(await createLockCredential({ credentials: fakeCredentials({ createFails: bad(name) }), rpId: RP }),
      { ok: false, reason: 'failed' }, name);
  }
  assert.deepEqual(await createLockCredential({ credentials: { create: async () => null }, rpId: RP }), { ok: false, reason: 'failed' });
  assert.deepEqual(await createLockCredential({ credentials: { create: async () => { throw new Error('x'); } }, rpId: RP }),
    { ok: false, reason: 'failed' });
});

// --- Entsperren -------------------------------------------------------------------------------------

test('unlocking asks for exactly the stored credential with user verification', async () => {
  const credentials = fakeCredentials();
  const result = await unlockWithCredential({ credentials, rpId: RP, id: ID_TEXT });

  assert.deepEqual(result, { ok: true });
  const { publicKey } = credentials.calls.get[0];
  assert.equal(publicKey.rpId, RP);
  assert.equal(publicKey.userVerification, 'required');
  assert.equal(publicKey.allowCredentials.length, 1);
  assert.deepEqual(new Uint8Array(publicKey.allowCredentials[0].id), ID);
  assert.equal(publicKey.allowCredentials[0].type, 'public-key');
  assert.deepEqual(publicKey.allowCredentials[0].transports, ['internal']);
  assert.equal(new Uint8Array(publicKey.challenge).length, 32);
});

test('every unlock uses a fresh challenge', async () => {
  const credentials = fakeCredentials();
  await unlockWithCredential({ credentials, rpId: RP, id: ID_TEXT });
  await unlockWithCredential({ credentials, rpId: RP, id: ID_TEXT });
  const [a, b] = credentials.calls.get.map((c) => new Uint8Array(c.publicKey.challenge));
  assert.notDeepEqual(a, b);
});

test('an answer without user verification or presence does not unlock', async () => {
  for (const flags of [0x01, 0x04, 0x00]) {            // nur Anwesenheit, nur Verifizierung, nichts
    assert.deepEqual(await unlockWithCredential({ credentials: fakeCredentials({ flags }), rpId: RP, id: ID_TEXT }),
      { ok: false, reason: 'unverified' }, `flags ${flags}`);
  }
  assert.deepEqual(await unlockWithCredential({ credentials: fakeCredentials({ flags: 0x45 }), rpId: RP, id: ID_TEXT }), { ok: true });
});

test('an answer for another site, challenge, type or credential does not unlock', async () => {
  const cases = {
    'fremde rpId': { rpId: 'evil.example' },
    'falsche Challenge': { challenge: b64e(new Uint8Array(32)) },
    'falscher Typ': { type: 'webauthn.create' },
    'fremde Credential-ID': { rawId: Uint8Array.from({ length: 32 }, () => 9) },
  };
  for (const [name, options] of Object.entries(cases)) {
    assert.deepEqual(await unlockWithCredential({ credentials: fakeCredentials(options), rpId: RP, id: ID_TEXT }),
      { ok: false, reason: 'failed' }, name);
  }
});

test('a missing or malformed answer does not unlock', async () => {
  const cases = [
    null,
    { type: 'public-key', rawId: ID.buffer },
    { type: 'public-key', rawId: ID.buffer, response: { clientDataJSON: utf8('kein json').buffer, authenticatorData: new ArrayBuffer(37) } },
    { type: 'public-key', rawId: ID.buffer, response: { clientDataJSON: utf8('{}').buffer, authenticatorData: new ArrayBuffer(10) } },
    { type: 'password', rawId: ID.buffer, response: {} },
  ];
  for (const getResult of cases) {
    assert.deepEqual(await unlockWithCredential({ credentials: fakeCredentials({ getResult }), rpId: RP, id: ID_TEXT }),
      { ok: false, reason: 'failed' });
  }
});

test('a cancelled prompt is distinguished from a broken one and nothing throws', async () => {
  for (const name of ['NotAllowedError', 'AbortError']) {
    assert.deepEqual(await unlockWithCredential({ credentials: fakeCredentials({ getFails: bad(name) }), rpId: RP, id: ID_TEXT }),
      { ok: false, reason: 'cancelled' }, name);
  }
  for (const name of ['SecurityError', 'InvalidStateError', 'NotSupportedError']) {
    assert.deepEqual(await unlockWithCredential({ credentials: fakeCredentials({ getFails: bad(name) }), rpId: RP, id: ID_TEXT }),
      { ok: false, reason: 'failed' }, name);
  }
  assert.deepEqual(await unlockWithCredential({ credentials: fakeCredentials(), rpId: RP, id: 'kein-base64!' }),
    { ok: false, reason: 'failed' });
  assert.deepEqual(await unlockWithCredential({ credentials: undefined, rpId: RP, id: ID_TEXT }), { ok: false, reason: 'failed' });
});

// --- Reiter -----------------------------------------------------------------------------------------

test('the settings model reflects availability, switch and delay', () => {
  const meta = { lock_enabled: false, lock_credential: '', lock_delay_ms: 300_000 };
  const unsupported = lockModel({ meta, support: { available: false, reason: 'no_authenticator' } });
  assert.equal(unsupported.available, false);
  assert.equal(unsupported.canChange, false);
  assert.equal(unsupported.hint, lockErrorText('no_authenticator'));

  const off = lockModel({ meta, support: { available: true, reason: null } });
  assert.equal(off.on, false);
  assert.equal(off.canChange, true);
  assert.equal(off.delayDisabled, true);                 // ohne Sperre nichts einzustellen
  assert.equal(off.delayMs, 300_000);
  assert.deepEqual(off.delayOptions.map((o) => o.value), [0, 60_000, 300_000]);
  assert.ok(off.delayOptions.every((o) => typeof o.label === 'string' && o.label.length > 0));

  const on = lockModel({ meta: { ...meta, lock_enabled: true, lock_credential: ID_TEXT }, support: { available: true, reason: null } });
  assert.equal(on.on, true);
  assert.equal(on.delayDisabled, false);

  const busy = lockModel({ meta: { ...meta, lock_enabled: true, lock_credential: ID_TEXT }, support: { available: true, reason: null }, busy: true });
  assert.equal(busy.canChange, false);
  assert.equal(busy.delayDisabled, true);
});

test('the model says plainly that this is a screen lock and does not protect the stored data', () => {
  const model = lockModel({ meta: {}, support: { available: true, reason: null } });
  assert.match(model.note, /Oberfläche/);
  assert.match(model.note, /nicht/);
  assert.doesNotMatch(model.note, /biometr/i);           // Verifizierung kann auch die Geräte-PIN sein
});

test('a stored delay that is not offered shows the default', () => {
  const model = lockModel({ meta: { lock_enabled: true, lock_credential: ID_TEXT, lock_delay_ms: 12345 }, support: { available: true, reason: null } });
  assert.equal(model.delayMs, DEFAULT_LOCK_DELAY_MS);
});

test('every failure has its own text, an unknown one falls back to the generic text', () => {
  const reasons = ['insecure', 'no_api', 'no_authenticator', 'pending', 'cancelled', 'failed', 'unverified'];
  const texts = reasons.map(lockErrorText);
  assert.equal(new Set(texts).size, reasons.length);
  assert.equal(lockErrorText('irgendwas'), lockErrorText('failed'));
  assert.equal(lockErrorText(undefined), lockErrorText('failed'));
});

test('the credential id round-trips through the base64url form', () => {
  assert.deepEqual(b64d(ID_TEXT), ID);
});


// --- Zeitgrenzen und Optionen ---------------------------------------------------------------------

test('both prompts ask the browser for 60 seconds', async () => {
  const credentials = fakeCredentials();
  await createLockCredential({ credentials, rpId: RP });
  await unlockWithCredential({ credentials, rpId: RP, id: ID_TEXT });
  assert.equal(credentials.calls.create[0].publicKey.timeout, 60_000);
  assert.equal(credentials.calls.get[0].publicKey.timeout, 60_000);
});

test('a prompt that never answers ends as cancelled instead of hanging the lock screen', async () => {
  const hanging = { create: () => new Promise(() => {}), get: () => new Promise(() => {}) };
  assert.deepEqual(await unlockWithCredential({ credentials: hanging, rpId: RP, id: ID_TEXT, timeoutMs: 20 }), { ok: false, reason: 'cancelled' });
  assert.deepEqual(await createLockCredential({ credentials: hanging, rpId: RP, timeoutMs: 20 }), { ok: false, reason: 'cancelled' });
});

test('an unexpected failure is handed to onError, a cancelled prompt is not', async () => {
  const seen = [];
  const onError = (error) => seen.push(error.name);
  await unlockWithCredential({ credentials: fakeCredentials({ getFails: bad('NotAllowedError') }), rpId: RP, id: ID_TEXT, onError });
  await unlockWithCredential({ credentials: fakeCredentials({ getFails: bad('SecurityError') }), rpId: RP, id: ID_TEXT, onError });
  await createLockCredential({ credentials: fakeCredentials({ createFails: bad('AbortError') }), rpId: RP, onError });
  await createLockCredential({ credentials: fakeCredentials({ createFails: bad('NotSupportedError') }), rpId: RP, onError });
  assert.deepEqual(seen, ['SecurityError', 'NotSupportedError']);
});

// --- Einschalten und Ausschalten --------------------------------------------------------------------

function recorder() {
  const patches = [];
  return { patches, setMeta: async (patch) => { patches.push(patch); } };
}

test('the lock is only switched on after a successful test unlock', async () => {
  const ok = recorder();
  assert.deepEqual(await enableLock({ id: ID_TEXT, probe: async () => ({ ok: true }), setMeta: ok.setMeta }), { ok: true });
  assert.deepEqual(ok.patches, [{ lock_enabled: true, lock_credential: ID_TEXT }]);

  const refused = recorder();
  assert.deepEqual(await enableLock({ id: ID_TEXT, probe: async () => ({ ok: false, reason: 'cancelled' }), setMeta: refused.setMeta }),
    { ok: false, reason: 'cancelled' });
  assert.deepEqual(refused.patches, []);
});

test('the lock is only switched off after the device was unlocked, and the credential id is forgotten', async () => {
  const asked = [];
  const ok = recorder();
  const probe = async (id) => { asked.push(id); return { ok: true }; };
  assert.deepEqual(await disableLock({ meta: { lock_credential: ID_TEXT }, probe, setMeta: ok.setMeta }), { ok: true });
  assert.deepEqual(asked, [ID_TEXT]);                                       // gefragt wird nach dem gespeicherten Passkey
  assert.deepEqual(ok.patches, [{ lock_enabled: false, lock_credential: '' }]);

  const refused = recorder();
  assert.deepEqual(await disableLock({ meta: { lock_credential: ID_TEXT }, setMeta: refused.setMeta,
    probe: async () => ({ ok: false, reason: 'unverified' }) }), { ok: false, reason: 'unverified' });
  assert.deepEqual(refused.patches, []);
});

// --- Ablauf der Sperre (ohne Oberfläche) ------------------------------------------------------------

function controller({ meta = { lock_enabled: true, lock_credential: ID_TEXT, lock_delay_ms: 60_000 }, unlockResult = { ok: true } } = {}) {
  const log = { locks: 0, unlocks: [], lockedDuringUnlock: [] };
  const clock = { now: 1_000_000 };
  const state = { meta, unlockResult };
  const ctl = createLockController({
    getMeta: () => state.meta,
    now: () => clock.now,
    unlockCredential: async (id) => { log.asked = id; return state.unlockResult; },
    onLock: () => { log.locks += 1; },
    onUnlock: (day) => { log.unlocks.push(day); log.lockedDuringUnlock.push(ctl.locked); },
  });
  return { ctl, log, clock, state };
}

test('an active lock locks at start, an inactive one never does', () => {
  const on = controller();
  assert.equal(on.ctl.start(), true);
  assert.equal(on.ctl.locked, true);
  assert.equal(on.log.locks, 1);
  for (const meta of [{ lock_enabled: false, lock_credential: ID_TEXT }, { lock_enabled: true, lock_credential: '' }, {}]) {
    const off = controller({ meta });
    assert.equal(off.ctl.start(), false);
    assert.equal(off.ctl.locked, false);
    assert.equal(off.log.locks, 0);
  }
});

test('coming back locks only after the delay and clears the hidden time', () => {
  const t = controller();
  t.ctl.hidden();
  t.clock.now += 59_999;
  t.ctl.visible();
  assert.equal(t.ctl.locked, false);
  t.clock.now += 600_000;
  t.ctl.visible();                                         // ohne erneutes Verlassen zählt die alte Zeit nicht mehr
  assert.equal(t.ctl.locked, false);
  t.ctl.hidden();                                          // zweites Verlassen: die Frist beginnt neu
  t.clock.now += 60_000;
  t.ctl.visible();
  assert.equal(t.ctl.locked, true);
  assert.equal(t.log.locks, 1);
  t.ctl.visible();                                         // ohne erneutes Verlassen sperrt nichts ein zweites Mal
  assert.equal(t.log.locks, 1);
});

test('coming back without having left does not lock, and locking twice is one lock', () => {
  const t = controller({ meta: { lock_enabled: true, lock_credential: ID_TEXT, lock_delay_ms: 0 } });
  t.ctl.visible();
  assert.equal(t.ctl.locked, false);
  t.ctl.start();
  t.ctl.start();
  t.ctl.hidden();
  t.ctl.visible();
  assert.equal(t.log.locks, 1);
});

test('a failed unlock keeps the lock; a successful one opens it before the callback runs', async () => {
  const refused = controller({ unlockResult: { ok: false, reason: 'cancelled' } });
  refused.ctl.start();
  assert.deepEqual(await refused.ctl.unlock(), { ok: false, reason: 'cancelled' });
  assert.equal(refused.ctl.locked, true);
  assert.deepEqual(refused.log.unlocks, []);
  assert.equal(refused.log.asked, ID_TEXT);

  const t = controller();
  t.ctl.start();
  assert.deepEqual(await t.ctl.unlock(), { ok: true });
  assert.equal(t.ctl.locked, false);
  assert.deepEqual(t.log.unlocks, [null]);
  assert.deepEqual(t.log.lockedDuringUnlock, [false]);      // sonst öffnete sich die Sperre im `close`-Handler wieder
});

test('the hidden time seen during the prompt does not lock again right after a successful unlock', async () => {
  // Frist „Sofort“: zeigt der Browser während der Abfrage `hidden` und danach `visible`, darf das nicht in einer Schleife enden.
  for (const order of ['visible-before-success', 'visible-after-success']) {
    const t = controller({ meta: { lock_enabled: true, lock_credential: ID_TEXT, lock_delay_ms: 0 } });
    t.ctl.start();
    t.ctl.hidden();
    if (order === 'visible-before-success') t.ctl.visible();
    await t.ctl.unlock();
    t.ctl.visible();
    assert.equal(t.ctl.locked, false, order);
    assert.equal(t.log.locks, 1, order);
  }
});

test('a day requested while locked opens once after the unlock; unlocked it opens at once', async () => {
  const t = controller();
  const opened = [];
  assert.equal(t.ctl.openDay('2026-11-01', (d) => opened.push(d)), true);
  assert.deepEqual(opened, ['2026-11-01']);

  t.ctl.start();
  assert.equal(t.ctl.openDay('2026-11-02', (d) => opened.push(d)), false);
  assert.equal(t.ctl.openDay('2026-11-03', (d) => opened.push(d)), false);   // der letzte Klick gewinnt
  assert.deepEqual(opened, ['2026-11-01']);
  await t.ctl.unlock();
  assert.deepEqual(t.log.unlocks, ['2026-11-03']);
  assert.equal(t.ctl.openDay('2026-11-04', (d) => opened.push(d)), true);
  assert.deepEqual(opened, ['2026-11-01', '2026-11-04']);
  await t.ctl.unlock();                                                      // nichts mehr vorgemerkt
  assert.equal(t.log.unlocks.length, 2);
  assert.equal(t.log.unlocks.at(-1), null);
});
