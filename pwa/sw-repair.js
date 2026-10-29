// pwa/sw-repair.js
// „Reparieren“ im Reiter „Updates“ (#390): den Service Worker neu einrichten, wenn Chrome ihn nicht mehr
// starten kann („ServiceWorker cannot be started“). Angefasst werden nur die Registrierung und die eigenen
// Caches; Einträge und Kopplung liegen in IndexedDB und bleiben unberührt. Ohne Browser-API (die Umgebung
// kommt als Parameter herein), getestet in test/sw-repair.test.js.
//
// Die Reihenfolge ist der Kern: erst prüfen, dann abmelden. Ein abgemeldeter Worker ohne Cache heißt, dass die
// Web-App offline nicht mehr startet; deshalb nichts anfassen, solange das Netz fehlt oder `sw.js` nicht
// abrufbar ist.

import { withDetail } from './diagnose.js';

export class RepairError extends Error {
  /** @param {'offline'|'unreachable'|'unsupported'|'failed'} kind */
  constructor(kind, cause) {
    super(kind);
    this.name = 'RepairError';
    this.kind = kind;
    this.cause = cause;
  }
}

/** Liefert `{ unregistered, caches }` oder wirft einen `RepairError`. Danach muss die Seite neu geladen werden. */
export async function repairServiceWorker({ serviceWorker, cacheStorage, prefix, scriptUrl, fetchFn, online }) {
  if (!serviceWorker || !cacheStorage) throw new RepairError('unsupported');
  if (online === false) throw new RepairError('offline');
  let response;
  try {
    response = await fetchFn(scriptUrl, { cache: 'reload' });
  } catch (error) {
    throw new RepairError('unreachable', error);
  }
  if (!response.ok) throw new RepairError('unreachable', new Error(`HTTP ${response.status}`));
  try {
    const registrations = await serviceWorker.getRegistrations();
    for (const registration of registrations) await registration.unregister();
    const names = (await cacheStorage.keys()).filter((name) => name.startsWith(prefix));
    for (const name of names) await cacheStorage.delete(name);
    await serviceWorker.register(scriptUrl, { type: 'module' });
    return { unregistered: registrations.length, caches: names.length };
  } catch (error) {
    throw new RepairError('failed', error);
  }
}

/** Der Text für die Anzeige. */
export function describeRepair(error) {
  if (!(error instanceof RepairError)) return withDetail('Die Reparatur ist fehlgeschlagen.', error);
  switch (error.kind) {
    case 'offline':
      return 'Reparieren braucht eine Internetverbindung, damit die Web-App danach auch offline startet. Bitte online erneut versuchen.';
    case 'unreachable':
      return `${withDetail('Die Seite ist gerade nicht erreichbar.', error.cause)} Es wurde nichts verändert.`;
    case 'unsupported':
      return 'Dieser Browser unterstützt keine Service Worker, es gibt nichts zu reparieren.';
    default:
      return `${withDetail('Die Reparatur ist fehlgeschlagen.', error.cause)} Einträge und Kopplung bleiben erhalten. Chrome und die Web-App schließen und neu öffnen.`;
  }
}
