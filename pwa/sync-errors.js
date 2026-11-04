// pwa/sync-errors.js
// Fehlerart des Abgleichs: `SyncError` und die Einordnung von Antworten und Netzfehlern. Eigene Datei,
// damit die Transporte (`transport.js`, `relay-transport.js`) `SyncError` werfen können, ohne `sync.js`
// zu importieren (das importiert sie). `sync.js` führt die Namen weiter aus.

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
  // Relay-Weg (#358): die versiegelte Antwort passte nicht in eine Nachricht der Box (`413` des Desktops).
  response_too_large: 'too_large',
  // Verschlüsselung (#249): ein Umschlag, den der Desktop nicht öffnen kann, ein wiedereingespielter
  // Zähler, eine Kopplung ohne Schlüssel — in allen drei Fällen hilft nur neu koppeln.
  invalid_envelope: 'protocol', decrypt_failed: 'crypto', replay: 'crypto', encryption_required: 'encryption',
  key_unavailable: 'transient',
};
const REPAIR_KINDS = new Set(['repair', 'crypto', 'encryption']);

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
