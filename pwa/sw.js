// pwa/sw.js
// Service Worker: legt die App-Dateien in einen versionierten Cache und liefert sie offline aus.
// Die Entscheidungen stehen in `sw-core.js` (getestet). Ein neuer Service Worker wartet, bis die
// Seite „Neu laden“ bestätigt (Nachricht `SKIP_WAITING`) — nie mitten in einer Eingabe.
import { CACHE_NAME, CACHE_PREFIX, PRECACHE, shouldHandle } from './sw-core.js';

self.addEventListener('install', (event) => {
  event.waitUntil(caches.open(CACHE_NAME).then((cache) => cache.addAll(PRECACHE)));
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
