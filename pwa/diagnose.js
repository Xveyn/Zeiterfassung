// pwa/diagnose.js
// Warum ist etwas fehlgeschlagen? Ein Fehler, den die App abfängt, soll seine Ursache nicht
// verlieren: sie steht im Log und, wo ein Text angezeigt wird, kurz daneben. Ohne Browser-API
// (getestet in test/diagnose.test.js).
//
// Nur für Fehler der Browser-Schnittstellen (Service Worker, Push, Kamera, Speicher). Fehler des
// Desktops und des Relays (`SyncError`, `RelayError`) haben eigene, kuratierte Texte und kommen
// hier nicht hinein.

export const MAX_DETAIL_LENGTH = 160;

/** „Name: Meldung“ in einer Zeile und gekürzt; leer, wenn es nichts zu sagen gibt. */
export function errorDetail(error) {
  let text = '';
  if (typeof error === 'string') {
    text = error;
  } else if (error && typeof error === 'object') {
    const name = typeof error.name === 'string' ? error.name : '';
    const message = typeof error.message === 'string' ? error.message : '';
    text = name && message ? `${name}: ${message}` : name || message;
  }
  text = text.replace(/\s+/g, ' ').trim();
  return text.length > MAX_DETAIL_LENGTH ? `${text.slice(0, MAX_DETAIL_LENGTH - 1)}…` : text;
}

/** Ein Meldungstext mit der Ursache dahinter: „Text (Name: Meldung)“; ohne Ursache der Text allein. */
export function withDetail(text, error) {
  const detail = errorDetail(error);
  return detail ? `${text.replace(/\.$/, '')} (${detail}).` : text;
}

/** Die Ursache in die Konsole (`chrome://inspect` am Handy). Wirft nie. */
export function logFailure(context, error, log = globalThis.console) {
  try {
    log.warn(`[Zeiterfassung] ${context}: ${errorDetail(error)}`);
  } catch {
    // Die Diagnose darf den Pfad, den sie beschreibt, nicht selbst zum Absturz bringen.
  }
}
