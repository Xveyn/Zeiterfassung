// pwa/sw-core.js
// Kern des Service Workers: Cache-Name, Vorab-Cache-Liste und die Entscheidung, welche
// Anfragen er überhaupt anfasst. Ohne Browser-API, damit er in Node getestet werden kann
// (`test/shell.test.js`); `sw.js` ist nur die dünne Hülle mit den Ereignissen.
//
// `BUILD` ist im Repository ein Platzhalter. Der Pages-Workflow setzt beim Veröffentlichen die
// Commit-Kennung ein: jeder Deploy bekommt damit einen eigenen Cache und löst ein Update aus.
// (Der Browser vergleicht `sw.js` samt importierter Module Byte für Byte.)
export const BUILD = '__BUILD__';
export const CACHE_PREFIX = 'zeiterfassung-pwa-';
export const CACHE_NAME = `${CACHE_PREFIX}${BUILD}`;

// Genau die Laufzeitdateien (ein Test hält Liste und Dateisystem zusammen). Relativ, weil die
// Seite unter /Zeiterfassung/ liegt.
export const PRECACHE = [
  './',
  './index.html',
  './app.css',
  './manifest.webmanifest',
  './app.js',
  './views.js',
  './dom.js',
  './scanner.js',
  './view-model.js',
  './messages.js',
  './sync-policy.js',
  './minutes.js',
  './pairing.js',
  './crypto.js',
  './store.js',
  './db.js',
  './sync.js',
  './sw-core.js',
  './icons/icon-192.png',
  './icons/icon-512.png',
  './icons/icon-maskable-512.png',
];

/** Nur eigene, vorab gecachte GET-Anfragen. Alles andere — vor allem die Anfragen an den
 *  Desktop (`http://<LAN-IP>`) — läuft am Service Worker vorbei: API-Antworten werden nie
 *  gecacht. */
export function shouldHandle(method, url, selfUrl) {
  if (method !== 'GET') return false;
  let target;
  let self;
  try {
    target = new URL(url);
    self = new URL(selfUrl);
  } catch {
    return false;                              // kaputte URL: nicht anfassen
  }
  if (target.origin !== self.origin) return false;
  const base = new URL('./', self);
  return PRECACHE.some((entry) => new URL(entry, base).pathname === target.pathname);
}
