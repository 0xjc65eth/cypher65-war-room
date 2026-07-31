/* ════════════════════════════════════════════════════════════════════════
   CYPHER65 · SERVICE WORKER · v2 — cache busted
   ════════════════════════════════════════════════════════════════════════
   - Caches static assets on install for offline resilience
   - VERSION = 2026-07-27 (bump this when CSS/JS/HTML changes)
   - Listens for 'show-notification' messages from the client to display
     OS-level notifications for critical mining alerts
   - Clicking a notification focuses / opens the dashboard
   ════════════════════════════════════════════════════════════════════════ */

const CACHE_NAME = 'cypher65-v3';
const ASSETS_TO_CACHE = [
  '/',
  '/static/style.css',
  '/static/app.js',
  '/static/manifest.json',
  '/api/healthz',
];

// ── Install: pre-cache key assets ──────────────────────────────────────
self.addEventListener('install', (event) => {
  self.skipWaiting();
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => {
      return cache.addAll(ASSETS_TO_CACHE).catch((err) => {
        // Non-critical: offline still works, just less resilient
        console.warn('[SW] cache addAll partial:', err);
      });
    })
  );
});

// ── Activate: clean old caches ─────────────────────────────────────────
self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) => {
      return Promise.all(
        keys.filter((k) => k !== CACHE_NAME).map((k) => caches.delete(k))
      );
    })
  );
  return self.clients.claim();
});

// ── Fetch: network-first, cache fallback ───────────────────────────────
self.addEventListener('fetch', (event) => {
  // Only cache GET requests to same origin
  if (event.request.method !== 'GET') return;
  if (!event.request.url.startsWith(self.location.origin)) return;

  event.respondWith(
    fetch(event.request)
      .then((response) => {
        // Cache successful responses for future offline use
        if (response.ok) {
          const clone = response.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put(event.request, clone));
        }
        return response;
      })
      .catch(() => {
        // Offline: serve from cache
        return caches.match(event.request).then((cached) => {
          return cached || new Response('Offline', { status: 503 });
        });
      })
  );
});

// ── Message: show notification from client ─────────────────────────────
self.addEventListener('message', (event) => {
  if (!event.data || !event.data.type) return;

  const { type, title, body, severity, tag } = event.data;

  if (type === 'show-notification') {
    const options = {
      body: body || '',
      tag: tag || 'cypher65-alert',
      icon: '/static/manifest.json',  // browser falls back to page icon
      badge: '/static/manifest.json',
      vibrate: severity === 'CRIT' ? [200, 100, 200] : [100, 50, 100],
      requireInteraction: severity === 'CRIT',
      data: { url: event.data.url || '/' },
      silent: false,
    };

    self.registration.showNotification(title || 'CYPHER65', options);
  }
});

// ── Notification click: focus or open dashboard ────────────────────────
self.addEventListener('notificationclick', (event) => {
  event.notification.close();

  const targetUrl = event.notification.data?.url || '/';

  event.waitUntil(
    clients.matchAll({ type: 'window', includeUncontrolled: true }).then((windowClients) => {
      // Focus existing tab if available
      for (const client of windowClients) {
        if (client.url.includes(self.location.host) && 'focus' in client) {
          return client.focus().then((focused) => {
            if (focused && 'navigate' in focused && focused.url !== targetUrl) {
              focused.navigate(targetUrl);
            }
            return focused;
          });
        }
      }
      // Open new tab
      if (clients.openWindow) {
        return clients.openWindow(targetUrl);
      }
    })
  );
});
