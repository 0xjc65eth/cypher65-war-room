/* ════════════════════════════════════════════════════════════════════════
   CYPHER65 · Service Worker · v1.0.0
   ════════════════════════════════════════════════════════════════════════
   Cache-first for static assets, network-first for API calls.
   Falls back to cached content when offline.
   ════════════════════════════════════════════════════════════════════════ */

const CACHE_NAME = 'cypher65-v1';
const STATIC_ASSETS = [
  '/',
  '/static/style.css',
  '/static/app.js',
  '/static/manifest.json',
];

// ── Install: pre-cache static shell ────────────────────────────────────
self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => {
      return cache.addAll(STATIC_ASSETS);
    }).then(() => {
      return self.skipWaiting();
    })
  );
});

// ── Activate: clean old caches ─────────────────────────────────────────
self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) => {
      return Promise.all(
        keys.filter((key) => key !== CACHE_NAME)
          .map((key) => caches.delete(key))
      );
    }).then(() => {
      return self.clients.claim();
    })
  );
});

// ── Fetch: cache-first for static, network-first for API ───────────────
self.addEventListener('fetch', (event) => {
  const url = new URL(event.request.url);

  // Skip non-GET and extension-less same-origin requests
  if (event.request.method !== 'GET') return;

  // API calls: network-first with cache fallback
  if (url.pathname.startsWith('/api/')) {
    event.respondWith(
      fetch(event.request)
        .then((response) => {
          // Cache successful API responses for offline fallback
          if (response.ok) {
            const clone = response.clone();
            caches.open(CACHE_NAME).then((cache) => {
              cache.put(event.request, clone);
            });
          }
          return response;
        })
        .catch(() => {
          return caches.match(event.request).then((cached) => {
            return cached || new Response(
              JSON.stringify({ error: 'offline', message: 'Network unavailable. Data may be stale.' }),
              { status: 503, headers: { 'Content-Type': 'application/json' } }
            );
          });
        })
    );
    return;
  }

  // Static assets (CSS, JS, manifest): cache-first
  if (url.pathname.startsWith('/static/') || url.pathname === '/') {
    event.respondWith(
      caches.match(event.request).then((cached) => {
        return cached || fetch(event.request).then((response) => {
          return caches.open(CACHE_NAME).then((cache) => {
            cache.put(event.request, response.clone());
            return response;
          });
        });
      })
    );
    return;
  }

  // Everything else: network-only (fonts, CDN scripts, etc.)
  // No cache fallback to avoid stale third-party content
});
