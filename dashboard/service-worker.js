const CACHE_NAME = 'eagleeye-v3.3'; // bump version
const OFFLINE_URL = '/offline.html';

const PRECACHE_URLS = [
  '/',
  '/offline.html',
  '/static/css/base.css',
  '/static/css/navbar.css',
  '/static/css/statsbar.css',
  '/static/css/sidebar.css',
  '/static/css/modals.css',
  '/static/js/utils/state.js',
  '/static/js/utils/helpers.js',
  '/static/js/utils/auth.js',
  '/static/js/utils/api.js',
  '/static/js/components/authModal.js',
  '/static/js/components/navbar.js',
  '/static/js/components/statsBar.js',
  '/static/js/components/mapView.js',
  '/static/js/components/sidebar.js',
  '/static/js/app.js',
];

// ── Install: pre-cache with error handling ──
self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then(async (cache) => {
      // Cache individually so one failure doesn't kill everything
      const results = await Promise.allSettled(
        PRECACHE_URLS.map(async (url) => {
          try {
            const response = await fetch(url);
            if (!response.ok) {
              console.warn(
                `[SW] Failed to precache ${url}: ${response.status}`,
              );
              return;
            }
            await cache.put(url, response);
          } catch (err) {
            console.warn(`[SW] Failed to fetch for precache: ${url}`, err);
          }
        }),
      );
      console.log('[SW] Precache complete', results);
    }),
  );
  self.skipWaiting();
});

// ── Activate: purge old caches ──
self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) =>
        Promise.all(
          keys.filter((k) => k !== CACHE_NAME).map((k) => caches.delete(k)),
        ),
      ),
  );
  self.clients.claim();
});

// ── Fetch handler ──
self.addEventListener('fetch', (event) => {
  if (event.request.method !== 'GET') return;

  const url = event.request.url;

  // Skip API & health — always network
  if (url.includes('/api/') || url.includes('/health')) {
    return;
  }

  // CDN assets — cache-first with network fallback
  if (
    url.includes('unpkg.com') ||
    url.includes('cdnjs.cloudflare.com') ||
    url.includes('fonts.googleapis.com') ||
    url.includes('fonts.gstatic.com') ||
    url.includes('basemaps.cartocdn.com') ||
    url.includes('arcgisonline.com')
  ) {
    event.respondWith(
      caches.match(event.request).then((cached) => {
        if (cached) return cached;
        return fetch(event.request)
          .then((response) => {
            if (response.ok) {
              const clone = response.clone();
              caches.open(CACHE_NAME).then((c) => c.put(event.request, clone));
            }
            return response;
          })
          .catch(() => {
            // Return empty response instead of throwing
            console.warn('[SW] CDN fetch failed:', url);
            return new Response('', {
              status: 503,
              statusText: 'Service Unavailable',
            });
          });
      }),
    );
    return;
  }

  // App shell — cache-first, network fallback, offline page as last resort
  event.respondWith(
    caches.match(event.request).then((cached) => {
      if (cached) return cached;

      return fetch(event.request)
        .then((response) => {
          if (response.ok) {
            const clone = response.clone();
            caches.open(CACHE_NAME).then((c) => c.put(event.request, clone));
          }
          return response;
        })
        .catch(() => {
          // Navigation → offline page
          if (event.request.mode === 'navigate') {
            return caches.match(OFFLINE_URL);
          }
          // Sub-resources → return empty response instead of undefined
          console.warn('[SW] Fetch failed for:', url);
          return new Response('', {
            status: 503,
            statusText: 'Offline',
            headers: { 'Content-Type': 'text/plain' },
          });
        });
    }),
  );
});
