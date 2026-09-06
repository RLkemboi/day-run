/* Day Run — service worker.
 *
 * The brief is a once-a-day read that often gets opened on a phone with bad
 * signal over breakfast, so the shell is cached and served network-first:
 * fresh when there's a connection, yesterday's page when there isn't, never a
 * spinner. Bump CACHE when the shell changes so old copies get evicted.
 */
const CACHE = 'day-run-v1';
const SHELL = [
  './',
  './index.html',
  './manifest.webmanifest',
  './favicon.svg',
  './icons/icon-192.png',
  './icons/icon-512.png',
  './icons/apple-touch-icon-180.png',
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE)
      .then((cache) => cache.addAll(SHELL))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (event) => {
  const { request } = event;
  if (request.method !== 'GET') return;

  event.respondWith(
    fetch(request)
      .then((response) => {
        // Keep the cache warm with whatever we just fetched successfully.
        const copy = response.clone();
        caches.open(CACHE).then((cache) => cache.put(request, copy)).catch(() => {});
        return response;
      })
      .catch(() =>
        caches.match(request).then(
          (hit) => hit || caches.match('./index.html')
        )
      )
  );
});
