// pwa/sync.js
// Der Sync-Client der Handy-Erfassung: Koppeln, Erreichbarkeit, Abgleich. Kennt nur
// `Store`, `fetch` und die Uhr (beides wird hereingereicht) — kein DOM, kein globaler
// Zustand. Fehler werden eingeordnet (`SyncError.kind`), die Oberfläche (PR 7) zeigt je Art
// den passenden Hinweis; die lokalen, nicht übertragenen Einträge bleiben in JEDEM
// Fehlerfall erhalten.
//
// Die Fehlerarten stehen in `test/fixtures/errors.json`; `tests/test_mobile_contract.py`
// verlangt dort jedes (Status, Code)-Paar, das der Server senden kann.
import { CryptoFailure, b64d, deviceKeys, isEnvelope, openEnvelope, pairKeys, seal } from './crypto.js';
import { parseDefaults, parseDesktopInfo } from './defaults.js';
import { isIsoDate, localIsoDate, utcStamp } from './minutes.js';
import {
  PROTOCOL, baseUrl, isLanAddress, isValidDeviceId, newDeviceId, normalizeCode, pairRequestBody,
} from './pairing.js';

export const SKEW_WARN_MS = 120000;
const MAX_WINDOW_DAYS = 3650;
const MAX_DAYS_PER_REQUEST = 400;         // Gegenstück zu `MAX_ENTRIES` in src/mobile_sync.py
const STAMP_RE = /^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$/;
const TOKEN_RE = /^[A-Za-z0-9_-]{16,256}$/;
const KEY_RE = /^[A-Za-z0-9_-]{43}$/;                            // 32 Bytes, base64url ohne Padding

export class SyncError extends Error {
  constructor({ kind, status = 0, code = '', message = '', needsRepair = false, retryable = false, day = null, dayKind = null, setting = null, supportedProtocol = null }) {
    super(message);
    this.name = 'SyncError';
    Object.assign(this, { kind, status, code, needsRepair, retryable, day, dayKind, setting, supportedProtocol });
  }
}

// Code → Art. Alles, was hier fehlt, ordnet der Rückfall nach Statusbereich ein.
const KINDS = {
  incomplete_body: 'transient', request_timeout: 'transient', busy: 'transient', shutting_down: 'transient',
  unauthorized: 'repair', token_expired: 'repair', token_revoked: 'repair',
  bad_host: 'address', bad_origin: 'address', browser_request: 'browser',
  invalid_code: 'invalid_code', clock_skew: 'clock_skew',
  invalid_entry: 'invalid_entry', invalid_protocol: 'protocol', not_found: 'protocol',
  method_not_allowed: 'protocol', internal_error: 'server',
  // Verschlüsselung (#249): ein Umschlag, den der Desktop nicht öffnen kann, ein wiedereingespielter
  // Zähler, eine Kopplung ohne Schlüssel — in allen drei Fällen hilft nur neu koppeln.
  invalid_envelope: 'protocol', decrypt_failed: 'crypto', replay: 'crypto', encryption_required: 'encryption',
  key_unavailable: 'transient',
};
const REPAIR_KINDS = new Set(['repair', 'crypto', 'encryption']);
// Diese Codes entstehen am Desktop erst NACH dem Entschlüsseln und gehen deshalb nur als Umschlag
// zurück. Im Klartext kämen sie von einem Dritten im WLAN: geglaubt, markierte `invalid_entry` einen
// Tag als abgelehnt (er würde nicht mehr gesendet) und `clock_skew`/`busy` führten in die Irre.
const SEALED_ONLY_CODES = new Set(['invalid_entry', 'clock_skew', 'busy']);

function fallbackKind(status) {
  if (status === 401) return 'repair';
  if (status >= 500) return 'server';
  return 'client_error';
}

/** Antwort mit Fehlerstatus → `SyncError`. Der Text kommt vom Server (deutsch). */
export function classifyHttpError(status, body) {
  const detail = body && typeof body === 'object' && body.error && typeof body.error === 'object' ? body.error : {};
  const code = typeof detail.code === 'string' ? detail.code : '';
  const message = typeof detail.message === 'string' ? detail.message : '';
  const kind = KINDS[code] ?? fallbackKind(status);
  // Der Desktop nennt den Tag vorn in der Meldung; eine Reservierung mit dem Vorsatz „Reservierung“.
  const named = kind === 'invalid_entry' ? /^(Reservierung )?(\d{4}-\d{2}-\d{2}):/.exec(message) : null;
  const day = named?.[2] ?? null;
  const dayKind = day ? (named[1] ? 'reservation' : 'entry') : null;
  // Eine abgelehnte Einstellung nennt der Desktop vorn: „Einstellung categories: …“.
  const setting = kind === 'invalid_entry' ? (/^Einstellung (categories|category_times)[: ]/.exec(message)?.[1] ?? null) : null;
  const protocolNumber = detail.supported_protocol;
  const supportedProtocol = code === 'invalid_protocol' && Number.isInteger(protocolNumber) && protocolNumber > 0 && protocolNumber < 1000 ? protocolNumber : null;
  return new SyncError({
    kind, status, code, message,
    needsRepair: REPAIR_KINDS.has(kind),
    retryable: kind === 'transient' || kind === 'server',
    day, dayKind, setting, supportedProtocol,
  });
}

/** Keine Antwort (Verbindung, Abbruch) → `offline`, nie ein Absturz. Eine Zeitüberschreitung hat eine
 *  eigene Art (#292): dahinter steckt entweder ein unerreichbarer Desktop oder eine zu große Antwort bei
 *  schwachem WLAN — der Text nennt beides und zeigt, wo sich der Verlauf verkleinern lässt. */
export function classifyNetworkError(error) {
  const timedOut = error?.name === 'TimeoutError';
  return new SyncError({
    kind: timedOut ? 'timeout' : 'offline', message: 'Der Desktop ist nicht erreichbar.', retryable: true,
    code: error?.name ?? '',
  });
}

const isObject = (value) => value !== null && typeof value === 'object' && !Array.isArray(value);
const protocolError = (message) => new SyncError({ kind: 'protocol', message });

function parseEntry(date, raw) {
  if (!isIsoDate(date)) throw protocolError(`Ungültiger Tag in der Antwort: ${String(date).slice(0, 20)}`);
  if (!isObject(raw) || !Array.isArray(raw.slots) || typeof raw.modified_at !== 'string'
    || typeof raw.device_id !== 'string' || typeof raw.deleted !== 'boolean') {
    throw protocolError(`Ungültiger Eintrag in der Antwort: ${date}`);
  }
  return { slots: cleanSlots(raw.slots), modified_at: cleanStamp(raw.modified_at), device_id: raw.device_id, deleted: raw.deleted };
}

/** Ein Zeitstempel wie ihn der Desktop schreibt, sonst leer (der Desktop schickt `""` für einen
 *  Eintrag ohne Stempel). Fremdes landete sonst im Store und in `_stampAfter`. */
const cleanStamp = (value) => (typeof value === 'string' && STAMP_RE.test(value) ? value : '');

/** Nur die vier Felder des Protokolls, mit ihren Typen; Unbrauchbares wird zu einem leeren
 *  Wert (die Anzeige rendert die Slots). Eine Ablehnung der ganzen Antwort wegen eines
 *  Slots wäre schlimmer: der Abgleich scheiterte dann bei jedem Versuch. */
function cleanSlots(slots) {
  const text = (value) => (typeof value === 'string' ? value : '');
  return slots.filter(isObject).map((slot) => ({
    start: text(slot.start), end: text(slot.end),
    pause: Number.isInteger(slot.pause) ? slot.pause : 0, kategorie: text(slot.kategorie),
  }));
}

/** Reservierungen der Antwort: `null`, wenn das Feld fehlt oder kein Objekt ist (der Desktop bietet
 *  sie nicht an, Feature-Erkennung). Einzelne unbrauchbare Tage entfallen, statt die Antwort zu kippen. */
function parseReservations(raw) {
  if (!isObject(raw)) return null;
  const text = (value) => (typeof value === 'string' ? value : '');
  const out = {};
  for (const [date, entry] of Object.entries(raw)) {
    if (!isIsoDate(date) || !isObject(entry) || !Array.isArray(entry.slots)) continue;
    const slots = entry.slots.filter(isObject).map((slot) => ({
      start: text(slot.start), end: text(slot.end), kategorie: text(slot.kategorie) }));
    if (slots.length === 0) continue;
    out[date] = { slots, modified_at: cleanStamp(entry.modified_at) };
  }
  return out;
}

/** Prüft eine Sync-Antwort vollständig, BEVOR sie den Zustand anfasst. Die Antwort kommt vom
 *  Desktop, kann aber von einer anderen Version stammen; eine halbe Anwendung wäre schlimmer
 *  als eine Ablehnung. Unbekannte Felder werden verworfen. */
export function parseSyncResponse(raw) {
  if (!isObject(raw) || raw.protocol !== PROTOCOL) throw protocolError('Unbekanntes Protokoll des Desktops.');
  if (typeof raw.token !== 'string' || !TOKEN_RE.test(raw.token)) throw protocolError('Antwort ohne gültiges Token.');
  if (typeof raw.expires_at !== 'string' || !STAMP_RE.test(raw.expires_at)) throw protocolError('Antwort ohne Ablauf.');
  if (typeof raw.server_time !== 'string' || !STAMP_RE.test(raw.server_time)) throw protocolError('Antwort ohne Serverzeit.');
  if (typeof raw.last_pull_at !== 'string' || !STAMP_RE.test(raw.last_pull_at)) throw protocolError('Antwort ohne last_pull_at.');
  if (typeof raw.excluded !== 'boolean') throw protocolError('Antwort ohne excluded.');
  if (!Number.isInteger(raw.window_days) || raw.window_days < 1 || raw.window_days > MAX_WINDOW_DAYS) {
    throw protocolError('Antwort mit ungültigem Lesefenster.');
  }
  if (!isObject(raw.entries)) throw protocolError('Antwort ohne Einträge.');
  if (!Array.isArray(raw.categories) || !raw.categories.every((c) => typeof c === 'string')) {
    throw protocolError('Antwort mit ungültigen Kategorien.');
  }
  if (!Array.isArray(raw.conflicts)) throw protocolError('Antwort ohne Konfliktliste.');
  const entries = {};
  for (const [date, entry] of Object.entries(raw.entries)) entries[date] = parseEntry(date, entry);
  const conflicts = raw.conflicts.map((conflict) => {
    if (!isObject(conflict) || typeof conflict.id !== 'string' || !isIsoDate(conflict.date)
      || !Array.isArray(conflict.versions)) throw protocolError('Ungültiger Konflikt in der Antwort.');
    return { id: conflict.id, date: conflict.date, versions: conflict.versions.filter(isObject).map((v) => ({
      device: typeof v.device === 'string' ? v.device : '', name: typeof v.name === 'string' ? v.name : '',
      modified_at: cleanStamp(v.modified_at), slots: Array.isArray(v.slots) ? cleanSlots(v.slots) : [] })) };
  });
  const max = raw.window_max_days;
  const windowMax = Number.isInteger(max) && max >= 1 && max <= MAX_WINDOW_DAYS ? max : null;   // fehlt bei älterem Desktop
  return {
    protocol: PROTOCOL, server_time: raw.server_time, last_pull_at: raw.last_pull_at,
    excluded: raw.excluded, window_days: raw.window_days, window_max: windowMax, entries, conflicts,
    categories: [...raw.categories], token: raw.token, expires_at: raw.expires_at,
    defaults: parseDefaults(raw.defaults), desktop: parseDesktopInfo(raw.desktop),
    reservations: parseReservations(raw.reservations),
    writable_settings: Array.isArray(raw.writable_settings) ? raw.writable_settings.filter((key) => typeof key === 'string') : [],
  };
}

/** Serverzeit minus Handy-Zeit in Millisekunden (`NaN` bei kaputter Serverzeit). */
export function clockSkewMs(serverTime, now) {
  return Date.parse(serverTime) - now.getTime();
}

const DISCARDED = () => ({ sent: 0, conflicts: 0, excluded: false, discarded: true });

export class SyncClient {
  constructor({ store, fetchFn = (...args) => globalThis.fetch(...args), now = () => new Date(), timeoutMs = 15000 }) {
    this._store = store;
    this._fetch = fetchFn;
    this._now = now;
    this._timeoutMs = timeoutMs;
    this._running = null;
  }

  async _request(method, path, address, { token = null, body = null, openError = null } = {}) {
    const headers = { Accept: 'application/json' };
    if (token) headers.Authorization = `Bearer ${token}`;
    if (body !== null) headers['Content-Type'] = 'application/json';
    let response;
    try {
      response = await this._fetch(`${baseUrl(address)}${path}`, {
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
    if (!response.ok) {
      // Fehler nach dem Entschlüsseln gehen verschlüsselt zurück: erst öffnen, dann einordnen.
      throw classifyHttpError(response.status, openError ? await openError(json) : json);
    }
    return json;
  }

  /** Eine verschlüsselte Anfrage (POST). `aadRequest`/`aadResponse` sind die Geräte-IDs in den
   *  Zusatzdaten (bei der Kopplung vorher `-`, die Antwort trägt die echte ID); `seq` der Zähler.
   *  Liefert den entschlüsselten Klartext (Objekt) der Erfolgsantwort; ein Fehler-Umschlag wird
   *  geöffnet und als `SyncError` geworfen. Was nicht zu öffnen ist, ist `crypto` — nie ein
   *  Klartext, dem man glauben dürfte. */
  async _sealedPost(path, address, { token, requestKey, responseKey, aadRequest, aadResponse, seq, payload }) {
    const envelope = await seal(requestKey, {
      direction: 'req', method: 'POST', path, deviceId: aadRequest, seq,
      plaintext: new TextEncoder().encode(JSON.stringify(payload)),
    });
    const open = async (json) => {
      try {
        const plain = await openEnvelope(responseKey, json, {
          direction: 'res', method: 'POST', path, deviceId: aadResponse, seq });
        return JSON.parse(new TextDecoder().decode(plain));
      } catch (error) {
        if (error instanceof CryptoFailure || error instanceof SyntaxError) {
          throw new SyncError({ kind: 'crypto', needsRepair: true,
            message: 'Die Antwort des Desktops ließ sich nicht entschlüsseln.' });
        }
        throw error;
      }
    };
    const openError = async (json) => {
      if (isEnvelope(json)) return open(json);
      const code = json && typeof json === 'object' && json.error && typeof json.error === 'object'
        ? json.error.code : '';
      if (SEALED_ONLY_CODES.has(code)) {
        throw new SyncError({ kind: 'protocol', message: 'Unerwartete, nicht verschlüsselte Fehlerantwort.' });
      }
      return json;                                     // Fehler vor dem Entschlüsseln: nur der Grund
    };
    const answer = await this._request('POST', path, address, { token, body: envelope, openError });
    if (!isEnvelope(answer)) throw protocolError('Die Antwort des Desktops ist nicht verschlüsselt.');
    return open(answer);
  }

  /** Koppelt mit dem Kopplungscode: legt Adresse, Token, den Geräteschlüssel und (einmalig) die
   *  Geräte-ID ab. Der Code geht nie über das Netz — er leitet nur die Schlüssel ab, mit denen
   *  Anfrage und Antwort verschlüsselt sind. Die Geräte-ID bleibt über erneutes Koppeln
   *  erhalten; nicht übertragene Tage bleiben liegen. Ein neuer Schlüssel setzt den Zähler zurück. */
  async pair({ host, port, code, deviceName }) {
    const normalized = normalizeCode(code);
    if (normalized === null) {
      throw new SyncError({ kind: 'invalid_code', message: 'Der Code hat nicht das richtige Format.' });
    }
    if (!isLanAddress(host)) {
      throw new SyncError({ kind: 'address', message: 'Die Adresse muss im privaten Netz liegen.' });
    }
    let { device_id: deviceId } = this._store.getMeta();
    if (!isValidDeviceId(deviceId)) {
      deviceId = newDeviceId();
      await this._store.setMeta({ device_id: deviceId });
    }
    const [requestKey, responseKey] = await pairKeys(normalized);
    const answer = await this._sealedPost('/v1/pair', { host, port }, {
      token: null, requestKey, responseKey, aadRequest: '-', aadResponse: deviceId, seq: 1,
      payload: pairRequestBody({ deviceName, deviceId }) });
    if (!isObject(answer) || answer.protocol !== PROTOCOL || typeof answer.token !== 'string'
      || !TOKEN_RE.test(answer.token) || typeof answer.expires_at !== 'string' || !STAMP_RE.test(answer.expires_at)
      || !Number.isInteger(answer.window_days) || answer.window_days < 1 || answer.window_days > MAX_WINDOW_DAYS || typeof answer.desktop_name !== 'string'
      || typeof answer.key !== 'string' || !KEY_RE.test(answer.key) || b64d(answer.key).length !== 32) {
      throw protocolError('Ungültige Antwort beim Koppeln.');
    }
    await this._store.setMeta({
      address: { host, port }, token: answer.token, token_expires_at: answer.expires_at,
      desktop_name: answer.desktop_name, window_days: answer.window_days, key: answer.key, seq: 0,
    });
    return { desktopName: answer.desktop_name };
  }

  /** Erreichbarkeits- und Uhrprüfung. */
  async ping() {
    const meta = this._store.getMeta();
    if (!meta.address || !meta.token) throw new SyncError({ kind: 'not_paired', message: 'Noch nicht gekoppelt.' });
    const answer = await this._request('GET', '/v1/ping', meta.address, { token: meta.token });
    if (!isObject(answer) || answer.protocol !== PROTOCOL || typeof answer.server_time !== 'string'
      || !STAMP_RE.test(answer.server_time)) throw protocolError('Ungültige Antwort auf die Erreichbarkeitsprüfung.');
    const skewMs = clockSkewMs(answer.server_time, this._now());
    await this._store.setMeta({ server_time: answer.server_time });
    return { skewMs, skewWarning: Math.abs(skewMs) >= SKEW_WARN_MS };
  }

  /** Gleicht ab. Gleichzeitige Aufrufe teilen sich EINEN Request. */
  sync() {
    if (!this._running) {
      this._running = this._run().finally(() => { this._running = null; });
    }
    return this._running;
  }

  _pairingChanged(meta) {
    const current = this._store.getMeta();
    return current.token !== meta.token || current.address?.host !== meta.address.host
      || current.address?.port !== meta.address.port;
  }

  /** Alle nicht übertragenen Tage, in Päckchen zu höchstens `MAX_DAYS_PER_REQUEST` (der Desktop
   *  lehnt mehr mit 422 ohne Tag ab, sonst scheiterte der Abgleich bei jedem Versuch). Das erste
   *  Päckchen holt zugleich die Antwort; ein späteres Päckchen, das scheitert, lässt die
   *  vorherigen angewendet und den Rest „nicht übertragen“. */
  async _run() {
    let total = { sent: 0, conflicts: 0, excluded: false };
    const done = new Set();         // schon gesendet: bei `excluded` bleiben sie „offen“, gingen sonst endlos hinaus
    let first = true;               // Reservierungen und Einstellungen gehen nur im ersten Päckchen hinaus
    for (;;) {
      const result = await this._runOnce(MAX_DAYS_PER_REQUEST, done, first);
      first = false;
      if (result.discarded) return result;
      total = { ...result, sent: total.sent + result.sent };
      if (result.sent < MAX_DAYS_PER_REQUEST
        || Object.keys(this._store.snapshotDirty(1, done).entries).length === 0) return total;
    }
  }

  async _runOnce(limit, done, first = false) {
    const meta = this._store.getMeta();
    if (!meta.address || !meta.token) throw new SyncError({ kind: 'not_paired', message: 'Noch nicht gekoppelt.' });
    if (!KEY_RE.test(meta.key || '')) {
      throw new SyncError({ kind: 'encryption', needsRepair: true,
        message: 'Diese Kopplung ist noch nicht verschlüsselt. Bitte neu koppeln.' });
    }
    const snapshot = this._store.snapshotDirty(limit, done);
    Object.assign(snapshot, first
      ? this._store.snapshotReservations() : { reservations: {}, reservationVersions: {} });
    const settings = first ? this._store.snapshotSettings() : null;
    if (settings) Object.assign(snapshot, settings); else snapshot.settingsVersion = undefined;
    const now = this._now();
    const wishSent = meta.window_wish ?? 90;
    // Den Zähler VOR dem Senden dauerhaft ablegen: ein Absturz mitten im Request darf ihn nie
    // wiederverwenden (der Desktop lehnt einen wiederholten Zähler als Replay ab).
    const seq = meta.seq + 1;
    await this._store.setMeta({ seq });
    const [requestKey, responseKey] = await deviceKeys(b64d(meta.key));
    let raw;
    try {
      raw = await this._sealedPost('/v1/sync', meta.address, {
        token: meta.token, requestKey, responseKey, aadRequest: meta.device_id, aadResponse: meta.device_id, seq,
        payload: { protocol: PROTOCOL, client_time: utcStamp(now), last_pull_at: meta.last_pull_at || '',
          window_days: wishSent, entries: snapshot.entries,
          ...(Object.keys(snapshot.reservations).length > 0 ? { reservations: snapshot.reservations } : {}),
          ...(settings ? { settings: settings.settings } : {}) } });
    } catch (error) {
      // Währenddessen neu gekoppelt: der Fehler gehört zum alten Server/Token und darf weder
      // den Zustand der neuen Kopplung markieren noch als deren Fehler erscheinen.
      if (this._pairingChanged(meta)) return DISCARDED();
      if (error instanceof SyncError && error.kind === 'invalid_entry' && error.day) {
        if (error.dayKind === 'reservation') {
          await this._store.markReservationError(error.day, error.message, snapshot.reservationVersions[error.day]);
        } else {
          await this._store.markDayError(error.day, error.message, snapshot.versions[error.day]);
        }
      }
      if (error instanceof SyncError && error.kind === 'invalid_entry' && error.setting && snapshot.settingsVersion !== undefined) {
        await this._store.markSettingsError(error.message, snapshot.settingsVersion);
      }
      throw error;
    }
    const parsed = parseSyncResponse(raw);
    parsed.window_wish_sent = wishSent;       // zu welchem Wunsch diese Antwort gehört (#292)
    if (this._pairingChanged(meta)) {
      // Währenddessen wurde neu gekoppelt: die Antwort gehört zum alten Server/Token. Sie
      // anzuwenden legte das alte Token über das neue und markierte Tage als übertragen,
      // die ein anderer Desktop nie bekam. Die Tage bleiben „nicht übertragen“.
      return DISCARDED();
    }
    await this._store.applyResponse(parsed, snapshot, localIsoDate(now));
    for (const date of Object.keys(snapshot.entries)) done.add(date);
    return { sent: Object.keys(snapshot.entries).length, conflicts: parsed.conflicts.length, excluded: parsed.excluded };
  }
}
