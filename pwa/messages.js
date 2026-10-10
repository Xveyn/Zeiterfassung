// pwa/messages.js
// Fehler einordnen für Menschen: jede `SyncError.kind` bekommt einen deutschen Text und einen
// Ausweg. Die Arten stehen in `test/fixtures/errors.json`; der Test verlangt für jede einen
// eigenen Text, damit ein neuer Fehlercode im Server nicht als „unbekannter Fehler" endet.

const DEFAULT = { text: 'Der Abgleich ist fehlgeschlagen. Bitte später erneut versuchen.', action: 'retry' };

const REPAIR = {
  token_revoked: 'Dieses Handy wurde am Desktop widerrufen. Bitte neu koppeln — Ihre nicht übertragenen Einträge bleiben erhalten.',
  token_expired: 'Die Kopplung ist abgelaufen. Bitte neu koppeln — Ihre nicht übertragenen Einträge bleiben erhalten.',
};
const REPAIR_FALLBACK = 'Die Kopplung wird vom Desktop nicht mehr akzeptiert (neu gekoppelt?). Bitte neu koppeln — Ihre nicht übertragenen Einträge bleiben erhalten.';

/** @param {unknown} error */
export function describeError(error) {
  if (!error || typeof error !== 'object' || typeof error.kind !== 'string') return DEFAULT;
  const server = typeof error.message === 'string' ? error.message : '';
  switch (error.kind) {
    case 'offline':
      return { text: 'Der Desktop ist nicht erreichbar. Läuft die App am Rechner, und sind Handy und Rechner im selben WLAN?', action: 'rescan' };
    case 'address':
      return { text: 'Falscher Desktop oder falsche Adresse. Den QR-Code am Desktop neu scannen.', action: 'rescan' };
    case 'repair':
      return { text: REPAIR[error.code] ?? REPAIR_FALLBACK, action: 'pair' };
    case 'not_paired':
      return { text: 'Dieses Handy ist noch nicht gekoppelt.', action: 'pair' };
    case 'browser':
      return { text: 'Dieser Browser sendet die Anfrage als seitenübergreifend (Sec-Fetch-Site) und der Desktop lehnt sie ab. Bitte Chrome auf Android verwenden.', action: null };
    case 'invalid_code':
      return { text: 'Der Code ist ungültig oder abgelaufen. Am Desktop einen neuen Code erzeugen.', action: 'pair' };
    case 'clock_skew':
      return { text: 'Die Uhr des Handys weicht mehr als 15 Minuten von der des Desktops ab. Datum und Uhrzeit am Handy prüfen.', action: null };
    case 'invalid_entry':
      return { text: `Der Desktop hat einen Tag abgelehnt: ${server || 'ungültiger Eintrag'}`, action: null };
    case 'crypto':
      return { text: 'Die Verschlüsselung zwischen Handy und Desktop passt nicht mehr (Handy oder Rechner wurden zurückgesetzt?). Bitte neu koppeln — Ihre nicht übertragenen Einträge bleiben erhalten.', action: 'pair' };
    case 'encryption':
      return { text: 'Diese Kopplung ist noch nicht verschlüsselt. Bitte neu koppeln — Ihre nicht übertragenen Einträge bleiben erhalten.', action: 'pair' };
    case 'transient':
      if (error.code === 'key_unavailable') {
        return { text: 'Der Schlüsselbund am Rechner antwortet gerade nicht (gesperrt?). Bitte gleich erneut versuchen.', action: 'retry' };
      }
      return { text: 'Der Desktop ist gerade beschäftigt. Bitte gleich erneut versuchen.', action: 'retry' };
    case 'server':
      return { text: 'Der Desktop meldet einen internen Fehler. Details stehen im Protokoll der Desktop-App.', action: 'retry' };
    case 'protocol':
      return { text: 'Die App-Versionen von Handy und Desktop passen nicht zusammen. Desktop-App und diese Seite aktualisieren.', action: null };
    case 'client_error':
      return { text: `Anfrage abgelehnt: ${server || 'unbekannter Grund'}`, action: null };
    default:
      return DEFAULT;
  }
}
