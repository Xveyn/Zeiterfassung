// pwa/messages.js
// Fehler einordnen für Menschen: jede `SyncError.kind` bekommt einen deutschen Text und einen
// Ausweg. Die Arten stehen in `test/fixtures/errors.json`; der Test verlangt für jede einen
// eigenen Text, damit ein neuer Fehlercode im Server nicht als „unbekannter Fehler" endet.

import { PROTOCOL } from './pairing.js';

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
    case 'timeout':
      return { text: 'Zeitüberschreitung: der Desktop hat nicht rechtzeitig geantwortet. Läuft die App am Rechner, und ist das WLAN stabil? Bei einem großen Verlauf kann auch die Datenmenge der Grund sein: unter „Verbindung“ lässt er sich auf 90 Tage zurücksetzen.', action: 'retry' };
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
    case 'protocol': {
      // Nennt der Desktop sein Protokoll (#290), sagen wir, welche Seite die ältere ist. Die Zahl kommt im
      // Klartext und ist damit nur ein Hinweis, kein Beleg.
      const theirs = error.supportedProtocol;
      if (Number.isInteger(theirs) && theirs > 0 && theirs < PROTOCOL) {
        return { text: 'Die Desktop-App ist älter als diese Seite und spricht ein anderes Protokoll. Bitte die Desktop-App aktualisieren.', action: null };
      }
      if (Number.isInteger(theirs) && theirs > PROTOCOL) {
        return { text: 'Die Desktop-App ist neuer als diese Seite. Bitte diese Seite neu laden bzw. aktualisieren.', action: 'reload' };
      }
      return { text: 'Die App-Versionen von Handy und Desktop passen nicht zusammen. Desktop-App und diese Seite aktualisieren.', action: null };
    }
    case 'client_error':
      return { text: `Anfrage abgelehnt: ${server || 'unbekannter Grund'}`, action: null };
    default:
      return DEFAULT;
  }
}
