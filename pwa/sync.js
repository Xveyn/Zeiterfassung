// pwa/sync.js
// Der Sync-Client der Handy-Erfassung: Koppeln, Erreichbarkeit, Abgleich. Kennt nur
// `Store`, `fetch` und die Uhr (beides wird hereingereicht) — kein DOM, kein globaler
// Zustand. Fehler werden eingeordnet (`SyncError.kind`), die Oberfläche (PR 7) zeigt je Art
// den passenden Hinweis; die lokalen, nicht übertragenen Einträge bleiben in JEDEM
// Fehlerfall erhalten.
//
// Die Fehlerarten stehen in `test/fixtures/errors.json`; `tests/test_mobile_contract.py`
// verlangt dort jedes (Status, Code)-Paar, das der Server senden kann.
import { isIsoDate, localIsoDate, utcStamp } from './minutes.js';
import {
  PROTOCOL, baseUrl, isLanAddress, isValidDeviceId, newDeviceId, normalizeCode, pairRequestBody,
} from './pairing.js';

export const SKEW_WARN_MS = 120000;
const MAX_WINDOW_DAYS = 3650;
const STAMP_RE = /^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$/;
const TOKEN_RE = /^[A-Za-z0-9_-]{16,256}$/;

export class SyncError extends Error {
  constructor({ kind, status = 0, code = '', message = '', needsRepair = false, retryable = false, day = null }) {
    super(message);
    this.name = 'SyncError';
    Object.assign(this, { kind, status, code, needsRepair, retryable, day });
  }
}

// Code → Art. Alles, was hier fehlt, ordnet der Rückfall nach Statusbereich ein.
const KINDS = {
  incomplete_body: 'transient', request_timeout: 'transient', busy: 'transient', shutting_down: 'transient',
  unauthorized: 'repair', token_expired: 'repair', token_revoked: 'repair',
  bad_host: 'address', bad_origin: 'address', browser_request: 'browser',
  invalid_code: 'invalid_code', pairing_locked: 'pairing_locked', clock_skew: 'clock_skew',
  invalid_entry: 'invalid_entry', invalid_protocol: 'protocol', not_found: 'protocol',
  method_not_allowed: 'protocol', internal_error: 'server',
};

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
  const day = kind === 'invalid_entry' ? (/^(\d{4}-\d{2}-\d{2}):/.exec(message)?.[1] ?? null) : null;
  return new SyncError({
    kind, status, code, message,
    needsRepair: kind === 'repair',
    retryable: kind === 'transient' || kind === 'server',
    day,
  });
}

/** Keine Antwort (Verbindung, Zeitüberschreitung, Abbruch) → immer `offline`, nie ein Absturz. */
export function classifyNetworkError(error) {
  return new SyncError({
    kind: 'offline', message: 'Der Desktop ist nicht erreichbar.', retryable: true,
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
  return { slots: raw.slots.map((s) => ({ ...s })), modified_at: raw.modified_at, device_id: raw.device_id, deleted: raw.deleted };
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
    return { id: conflict.id, date: conflict.date, versions: conflict.versions.map((v) => ({ ...v })) };
  });
  return {
    protocol: PROTOCOL, server_time: raw.server_time, last_pull_at: raw.last_pull_at,
    excluded: raw.excluded, window_days: raw.window_days, entries, conflicts,
    categories: [...raw.categories], token: raw.token, expires_at: raw.expires_at,
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

  async _request(method, path, address, { token = null, body = null } = {}) {
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
    if (!response.ok) throw classifyHttpError(response.status, json);
    return json;
  }

  /** Koppelt mit dem Code: legt Adresse, Token und (einmalig) die Geräte-ID ab. Die Geräte-ID
   *  bleibt über erneutes Koppeln erhalten; nicht übertragene Tage bleiben liegen. */
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
    const answer = await this._request('POST', '/v1/pair', { host, port }, {
      body: pairRequestBody({ code: normalized, deviceName, deviceId }) });
    if (!isObject(answer) || answer.protocol !== PROTOCOL || typeof answer.token !== 'string'
      || !TOKEN_RE.test(answer.token) || typeof answer.expires_at !== 'string'
      || !Number.isInteger(answer.window_days) || typeof answer.desktop_name !== 'string') {
      throw protocolError('Ungültige Antwort beim Koppeln.');
    }
    await this._store.setMeta({
      address: { host, port }, token: answer.token, token_expires_at: answer.expires_at,
      desktop_name: answer.desktop_name, window_days: answer.window_days,
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

  async _run() {
    const meta = this._store.getMeta();
    if (!meta.address || !meta.token) throw new SyncError({ kind: 'not_paired', message: 'Noch nicht gekoppelt.' });
    const snapshot = this._store.snapshotDirty();
    const now = this._now();
    let raw;
    try {
      raw = await this._request('POST', '/v1/sync', meta.address, { token: meta.token, body: {
        protocol: PROTOCOL, client_time: utcStamp(now), last_pull_at: meta.last_pull_at || '',
        entries: snapshot.entries } });
    } catch (error) {
      // Währenddessen neu gekoppelt: der Fehler gehört zum alten Server/Token und darf weder
      // den Zustand der neuen Kopplung markieren noch als deren Fehler erscheinen.
      if (this._pairingChanged(meta)) return DISCARDED();
      if (error instanceof SyncError && error.kind === 'invalid_entry' && error.day) {
        await this._store.markDayError(error.day, error.message, snapshot.versions[error.day]);
      }
      throw error;
    }
    const parsed = parseSyncResponse(raw);
    if (this._pairingChanged(meta)) {
      // Währenddessen wurde neu gekoppelt: die Antwort gehört zum alten Server/Token. Sie
      // anzuwenden legte das alte Token über das neue und markierte Tage als übertragen,
      // die ein anderer Desktop nie bekam. Die Tage bleiben „nicht übertragen“.
      return DISCARDED();
    }
    await this._store.applyResponse(parsed, snapshot, localIsoDate(now));
    return { sent: Object.keys(snapshot.entries).length, conflicts: parsed.conflicts.length, excluded: parsed.excluded };
  }
}
