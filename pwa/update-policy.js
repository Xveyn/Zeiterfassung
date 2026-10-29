// pwa/update-policy.js
// Wann sucht die PWA nach einer neuen Version, und wann spielt sie eine wartende von selbst ein?
// Reine Entscheidungen ohne Browser-API (getestet in test/update-policy.test.js); `app.js` führt aus.
//
// Der Browser prüft `sw.js` von sich aus nur bei einer Navigation und höchstens alle 24 Stunden.
// Eine installierte PWA, die nur aus dem Hintergrund nach vorn kommt, merkt ein neues Deploy deshalb
// spät: die App stößt die Prüfung selbst an.

export const UPDATE_CHECK_INTERVAL_MS = 30 * 60 * 1000;
const AUTOMATIC = new Set(['start', 'visible']);

export function shouldCheckForUpdate({ trigger, now, lastCheckAt, online, checking, supported }) {
  if (!supported || checking) return false;
  if (trigger === 'manual') return true;                       // der Nutzer will die Antwort sehen, auch „offline“
  if (!AUTOMATIC.has(trigger) || !online) return false;
  return now - lastCheckAt >= UPDATE_CHECK_INTERVAL_MS;
}

/** Automatisch einspielen nur, wenn der Nutzer es eingeschaltet hat und es gerade nichts stört: ein
 *  offener Dialog kann eine halbe Eingabe halten, ein laufender Abgleich soll nicht abreißen. Nicht
 *  übertragene Tage liegen in IndexedDB und überstehen das Neuladen. `requested` hält fest, dass für den
 *  wartenden Worker schon ein `SKIP_WAITING` raus ist (sonst gäbe es eine Neulade-Schleife). */
export function shouldApplyUpdate({ autoUpdate, updateReady, dialogOpen, syncing, requested }) {
  return Boolean(autoUpdate && updateReady && !dialogOpen && !syncing && !requested);
}

const STATUS = {
  idle: 'Noch nicht geprüft.',
  checking: 'Es wird nach einer neuen Version gesucht …',
  current: 'Diese Seite ist aktuell.',
  available: 'Neue Version verfügbar.',
  offline: 'Offline — die Suche war nicht möglich.',
  error: 'Die Suche nach einer neuen Version ist fehlgeschlagen.',
  unsupported: 'Dieser Browser unterstützt keine Updates im Hintergrund.',
};

/** `detail` (die Ursache, s. `diagnose.js`) hängt nur an einer fehlgeschlagenen Suche. */
export function updateStatusText(state, detail = '') {
  if (state === 'error' && detail) return `${STATUS.error.replace(/\.$/, '')} (${detail}).`;
  return STATUS[state] ?? STATUS.idle;
}
