/* ════════════════════════════════════════════════════════════════════════
   CYPHER65 · SERVICE WORKER · v6 — cache busted
   ════════════════════════════════════════════════════════════════════════
   - Caches static assets on install for offline resilience
   - Listens for REAL Web Push events (VAPID, Issue #15) and for
     'show-notification' messages from the client (legacy in-page alerts)
   - Clicking a notification focuses / opens the dashboard
   ════════════════════════════════════════════════════════════════════════ */

const CACHE_NAME = 'cypher65-v12';  // v11 P0-6 terminal pro · v12 Web Push (VAPID)
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
        // Offline: serve from cache (exact match, then query-stripped)
        return caches.match(event.request).then((cached) => {
          if (cached) return cached;
          // The page requests versioned URLs (e.g. /static/app.js?v34) but
          // the SW pre-caches the un-versioned paths — fall back to those.
          const url = new URL(event.request.url);
          url.search = '';
          return caches.match(new Request(url.href, { method: 'GET' })).then((c2) => {
            return c2 || new Response('Offline', { status: 503 });
          });
        });
      })
  );
});

// ── Push: REAL Web Push from the server (VAPID, Issue #15) ─────────────
// The backend sends an encrypted JSON payload via pywebpush:
//   { title, body, tag, data: {url}, requireInteraction, renotify, vibrate }
// Without this listener the browser silently drops every push — the VAPID
// subscription would exist but NO notification would ever appear.
self.addEventListener('push', (event) => {
  if (!self.Notification || self.Notification.permission !== 'granted') return;

  let data = {};
  try {
    data = event.data ? event.data.json() : {};
  } catch (err) {
    // Non-JSON payload — still show a generic alert rather than drop it.
    data = {};
  }

  // Severity arrives NESTED (payload.data.severity) — also accept the
  // top-level shape for robustness, and forward severity/category into the
  // notification data so a future click handler can branch on them.
  const nested = data.data || {};
  const sev = (nested.severity || data.severity || 'WARN').toUpperCase();
  const critical = sev === 'CRIT' || sev === 'CRITICAL';
  const options = {
    body: data.body || 'Novo alerta de mineração',
    tag: data.tag || 'cypher65-' + Math.floor(Date.now() / 300000),
    icon: '/static/icon-192x192.png',
    badge: '/static/icon-192x192.png',
    vibrate: Array.isArray(data.vibrate)
      ? data.vibrate
      : (critical ? [300, 100, 300] : [200, 100, 200]),
    requireInteraction: critical || !!data.requireInteraction,
    renotify: true,
    data: {
      url: nested.url || data.url || '/',
      severity: sev,
      category: nested.category || data.category || '',
    },
  };

  event.waitUntil(
    self.registration.showNotification(data.title || 'CYPHER65', options)
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
      icon: '/static/icon-192x192.png',
      badge: '/static/icon-192x192.png',
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
