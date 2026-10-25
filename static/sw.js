/* ════════════════════════════════════════════════════════════════════════
   CYPHER65 · SERVICE WORKER · v14 — public static files only
   ════════════════════════════════════════════════════════════════════════
   - Caches static assets on install for offline resilience
   - Listens for REAL Web Push events (VAPID, Issue #15) and for
     'show-notification' messages from the client (legacy in-page alerts)
   - Clicking a notification focuses / opens the dashboard
   ════════════════════════════════════════════════════════════════════════ */

// Never precache '/', documents or APIs: their representation may be private.
const CACHE_NAME = 'cypher65-v14';
const PUBLIC_TYPES = {
  '/static/style.css': ['text/css'],
  '/static/app.js': ['text/javascript', 'application/javascript'],
  '/static/manifest.json': ['application/json', 'application/manifest+json'],
  '/static/icon-32x32.png': ['image/png'],
  '/static/icon-192x192.png': ['image/png'],
  '/static/icon-512x512.png': ['image/png'],
};
const ASSETS_TO_CACHE = Object.keys(PUBLIC_TYPES);

/** Return an exact public asset key, or null; e.g. style.css?v763 -> style.css.
 * Only the existing bounded version query is canonicalized. No API/document,
 * arbitrary query, double encoding, credentials or malformed path is admitted.
 * @param {string} value Absolute request/response URL.
 * @returns {string|null} Same-origin canonical asset URL.
 */
function publicAssetKey(value) {
  try {
    const url = new URL(value);
    if (url.origin !== self.location.origin || url.username || url.password || url.hash) return null;
    if (url.search && !/^\?v=?[a-zA-Z0-9._-]{1,128}$/.test(url.search)) return null;
    const path = decodeURIComponent(url.pathname).replace(/\/{2,}/g, '/');
    return Object.hasOwn(PUBLIC_TYPES, path) ? url.origin + path : null;
  } catch { return null; }
}

/** Apply the same response policy on write AND read; no-store is not automatic
 * in Cache API. Example: a cached CSS response marked private is unavailable.
 * @param {Response|undefined} response Network or current-owned-cache response.
 * @param {string} key Canonical public asset URL.
 * @returns {boolean} Whether this public static response may be stored/served.
 */
function publicStaticResponse(response, key) {
  if (!response || response.status !== 200 || response.redirected ||
      !['basic', 'default'].includes(response.type)) return false;
  if (response.url && publicAssetKey(response.url) !== key) return false;
  const control = response.headers.get('Cache-Control') || '';
  if (/(?:^|,)\s*(?:no-store|private)\s*(?:=|,|$)/i.test(control)) return false;
  const vary = (response.headers.get('Vary') || '').split(',').map(value => value.trim().toLowerCase());
  if (vary.some(value => ['*', 'authorization', 'cookie'].includes(value))) return false;
  const type = (response.headers.get('Content-Type') || '').split(';')[0].trim().toLowerCase();
  return PUBLIC_TYPES[new URL(key).pathname].includes(type);
}

// ── Install: pre-cache key assets ──────────────────────────────────────
self.addEventListener('install', (event) => {
  self.skipWaiting();
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => {
      return Promise.all(ASSETS_TO_CACHE.map(async (path) => {
        const key = self.location.origin + path;
        try {
          const response = await fetch(new Request(key, { credentials: 'omit', cache: 'reload' }));
          if (publicStaticResponse(response, key)) await cache.put(key, response);
        } catch { /* Best-effort public asset warmup; never cache a private fallback. */ }
      }));
    })
  );
});

// ── Activate: clean old caches ─────────────────────────────────────────
self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) => {
      return Promise.all(
        keys.filter((k) => /^cypher65-v\d+$/.test(k) && k !== CACHE_NAME)
          .map((k) => caches.delete(k))
      );
    }).then(() => self.clients.claim())
  );
});

// ── Fetch: network-first, cache fallback ───────────────────────────────
self.addEventListener('fetch', (event) => {
  // A single public-static policy subsumes all private page/API exclusions.
  // Bypass before respondWith, so old/foreign private entries cannot be read.
  if (event.request.method !== 'GET') return;
  if (event.request.mode === 'navigate' || event.request.destination === 'document' || event.request.cache === 'no-store') return;
  if (event.request.headers?.has('Authorization')) return;
  const key = publicAssetKey(event.request.url);
  if (!key) return;

  event.respondWith(
    fetch(event.request)
      .then((response) => {
        // Cache successful responses for future offline use
        if (publicStaticResponse(response, key)) {
          const clone = response.clone();
          event.waitUntil(caches.open(CACHE_NAME).then((cache) => cache.put(key, clone))
            .catch(() => {})); // Best-effort static cache; never replace a valid network response.
        }
        return response;
      })
      .catch(() => {
        // Only this generation's public cache is eligible, with read defenses.
        // Never search all caches: an unrelated application may own those rows.
        return caches.open(CACHE_NAME).then(cache => cache.match(key))
          .then(cached => publicStaticResponse(cached, key) ? cached : new Response('Offline', { status: 503 }))
          .catch(() => new Response('Offline', { status: 503 }));
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
