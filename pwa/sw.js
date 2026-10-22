// pwa/sw.js
// Service Worker: legt die App-Dateien in einen versionierten Cache und liefert sie offline aus.
// Die Entscheidungen stehen in `sw-core.js` (getestet). Ein neuer Service Worker wartet, bis die
// Seite „Neu laden“ bestätigt (Nachricht `SKIP_WAITING`) — nie mitten in einer Eingabe.
import { CACHE_NAME, CACHE_PREFIX, PRECACHE, shouldHandle } from './sw-core.js';
import { idbKeyStore, open } from './push-blob.js';
import { TEST_PAYLOAD, clickTarget, describe, describeTest } from './push-message.js';

// `cache: 'reload'` umgeht den HTTP-Cache (GitHub Pages: max-age=600): sonst könnte ein neuer
// Worker Dateien aus dem Cache der vorigen Installation einsammeln und eine Mischung aus alten
// und neuen Modulen festschreiben.
self.addEventListener('install', (event) => {
  event.waitUntil(caches.open(CACHE_NAME).then((cache) => cache.addAll(PRECACHE.map((url) => new Request(url, { cache: 'reload' })))));
});

self.addEventListener('activate', (event) => {
  event.waitUntil((async () => {
    for (const key of await caches.keys()) {
      if (key.startsWith(CACHE_PREFIX) && key !== CACHE_NAME) await caches.delete(key);
    }
    await self.clients.claim();
  })());
});

self.addEventListener('message', (event) => {
  if (event.data && event.data.type === 'SKIP_WAITING') self.skipWaiting();
});

self.addEventListener('fetch', (event) => {
  const { request } = event;
  if (!shouldHandle(request.method, request.url, self.location.href)) return;
  event.respondWith((async () => {
    const cache = await caches.open(CACHE_NAME);
    const hit = await cache.match(request, { ignoreSearch: true });
    if (hit) return hit;
    if (request.mode === 'navigate') {
      const shell = await cache.match('./index.html');
      if (shell) return shell;
    }
    return fetch(request);
  })());
});

// Push vom Relay (Erinnerungen). Chrome verlangt je Push eine sichtbare Benachrichtigung
// (`userVisibleOnly`): ist das Entschlüsseln gescheitert (Schlüssel fehlt, Blob beschädigt), zeigt
// `describe(null)` die allgemeine. Der gleiche `tag` ersetzt eine Benachrichtigung, statt sie zu verdoppeln.
self.addEventListener('push', (event) => {
  event.waitUntil((async () => {
    const text = event.data ? event.data.text() : '';
    if (text === TEST_PAYLOAD) {                       // Testbenachrichtigung vom Relay: unverschlüsselt, fest
      const { title, body, tag } = describeTest();
      await self.registration.showNotification(title, {
        body, tag, data: null, icon: new URL('./icons/icon-192.png', self.registration.scope).href });
      return;
    }
    let plain = null;
    try {
      plain = await open(idbKeyStore(), text);
    } catch {
      // Kein Schlüssel oder fremder Blob: bewusst keine Details, es folgt die allgemeine Anzeige.
    }
    const { title, body, tag } = describe(plain);
    await self.registration.showNotification(title, {
      body, tag, renotify: false, data: plain, icon: new URL('./icons/icon-192.png', self.registration.scope).href,
    });
  })());
});

// Klick: ein offenes Fenster bekommt den Tag per Nachricht, sonst öffnet sich die App am Tag.
self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  const scope = self.registration.scope;
  const target = clickTarget(event.notification.data, scope);
  event.waitUntil((async () => {
    const windows = await self.clients.matchAll({ type: 'window', includeUncontrolled: true });
    const mine = windows.find((client) => client.url.startsWith(scope));
    if (!mine) {
      await self.clients.openWindow(target);
      return;
    }
    await mine.focus();
    const date = new URL(target).searchParams.get('open');
    if (date) mine.postMessage({ type: 'OPEN_DAY', date });
  })());
});
