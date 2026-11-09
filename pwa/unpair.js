// pwa/unpair.js
// Der Ablauf von „Trennen und lokale Daten löschen“ (#499), ohne DOM: die Schritte kommen als Funktionen herein,
// die Reihenfolge und die Fehlerregeln stehen hier.

/** `steps`: `notifyDesktop() → 'sent' | 'queued' | 'failed'`, `disablePush()`, `clearSession()`, `clearDebug()`,
 *  `wipe()`, `reload()`, `log(label, error)`. Liefert `run()`: `{ ok, notified }` oder `{ ok: false, error }`.
 *
 *  Die ersten vier Schritte sind best effort: ein Fehler wird geloggt und hält nichts auf, der Nutzer hat
 *  bestätigt. Scheitert `wipe()`, wird nicht neu geladen und nichts als gelöscht gemeldet. Ein Aufruf während
 *  eines laufenden teilt dessen Ergebnis, die Abmeldung geht nie zweimal hinaus. */
export function createUnpairRunner({ notifyDesktop, disablePush, clearSession, clearDebug, wipe, reload, log }) {
  let running = null;

  const attempt = async (label, work) => {
    try {
      return await work();
    } catch (error) {
      log(label, error);
      return undefined;
    }
  };

  const once = async () => {
    // Zuerst der Desktop: danach darf keine Anfrage mehr an die Box gehen (ein `put` ersetzte den Slot).
    const notified = (await attempt('Abmeldung am Desktop', notifyDesktop)) ?? 'failed';
    await attempt('Push abmelden', disablePush);
    await attempt('Sitzungsmerker löschen', clearSession);
    await attempt('Protokoll löschen', clearDebug);
    try {
      await wipe();
    } catch (error) {
      log('Lokale Daten löschen', error);
      return { ok: false, error };
    }
    await attempt('Neu laden', reload);
    return { ok: true, notified };
  };

  return function run() {
    if (!running) running = once().finally(() => { running = null; });
    return running;
  };
}
