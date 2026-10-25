/** Issue #868: execute the production worker, never a mirrored policy. */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const origin = 'https://fixture.test';
const source = fs.readFileSync(new URL('../static/sw.js', import.meta.url), 'utf8');
function worker({ offline = false, fetchImpl, putFails = false, openFails = false } = {}) {
  const handlers = {}, calls = [], stores = new Map(), deleted = [], puts = [];
  const caches = {
    async open(name) {
      if (openFails) throw Error('fixture storage unavailable');
      if (!stores.has(name)) stores.set(name, new Map());
      const entries = stores.get(name);
      return { put: async (key, value) => { if (putFails) throw Error('fixture quota exceeded'); puts.push(key); entries.set(String(key), value); },
        match: async key => entries.get(String(key)) };
    },
    keys: async () => [...stores.keys()],
    delete: async name => { deleted.push(name); return stores.delete(name); },
    match() { throw Error('Global CacheStorage.match must never be used'); },
  };
  const policy = vm.runInNewContext(source + '; ({ publicAssetKey, publicStaticResponse, CACHE_NAME, ASSETS_TO_CACHE })', {
    URL, Request, Response, Headers,
    self: { location: { origin }, addEventListener: (name, fn) => { handlers[name] = fn; },
      skipWaiting() {}, clients: { claim: async () => { calls.push('claim'); } } },
    fetch: request => {
      calls.push(request);
      if (fetchImpl) return fetchImpl(request);
      return offline ? Promise.reject(Error('fixture offline')) : Promise.resolve(new Response('public', { headers: { 'Content-Type': 'text/css' } }));
    },
    caches,
  }, { filename: 'static/sw.js' });
  async function dispatch(request) {
    let response;
    const waits = [];
    handlers.fetch({ request, respondWith: value => { response = value; }, waitUntil: value => waits.push(value) });
    response = await response; await Promise.all(waits); return response;
  }
  return { handlers, calls, stores, deleted, puts, policy, caches, dispatch };
}

test('all private API/document families bypass respondWith, including authenticated public paths', () => {
  const { handlers, calls } = worker();
  let interceptions = 0;
  for (const path of ['/', '/login', '/api/settings', '/api/fleet/summary', '/api/healthz',
    '/mini-war-room', '/thermal-timeline', '/energy-advisor', '/api/%73ettings', '/%61pi//settings']) {
    for (const authorization of [undefined, 'Bearer SYNTHETIC-A', 'Bearer SYNTHETIC-B']) {
      const request = new Request(origin + path, { headers: authorization ? { Authorization: authorization } : {} });
      handlers.fetch({ request, respondWith: () => { interceptions++; } });
    }
  }
  for (const value of ['', 'Bearer SYNTHETIC-A']) {
    handlers.fetch({ request: new Request(origin + '/static/style.css', { headers: { Authorization: value } }),
      respondWith: () => { interceptions++; } });
  }
  assert.equal(interceptions, 0);
  assert.equal(calls.length, 0);
});

test('the worker does not precache documents or APIs', () => {
  const assets = vm.runInNewContext(source + '; ASSETS_TO_CACHE', {
    self: { addEventListener() {}, location: { origin } },
  });
  assert.equal(assets.some(path => path === '/' || path.startsWith('/api/')), false);
  assert.ok(assets.includes('/static/style.css'));
});

test('exact-origin canonical public paths do not expand to dynamic documents or arbitrary queries', () => {
  const { publicAssetKey: key } = worker().policy;
  for (const path of ['/static/style.css', '/static/style.css?v763', '/static/style.css?v=763',
    '/%73tatic/style.css', '/static//style.css']) assert.equal(key(origin + path), origin + '/static/style.css');
  for (const value of [origin + '.evil/static/style.css', 'http://fixture.test/static/style.css',
    'https://user@fixture.test/static/style.css', origin + '/static/style.css#fragment',
    origin + '/static/style.css?tenant=A', origin + '/static/style.css?v=1&token=synthetic',
    origin + '/static/style.css?v=' + 'x'.repeat(129), origin + '/static/%zz',
    origin + '/static/%252e%252e/api/settings', origin + '/static/%2e%2e/api/settings',
    origin + '/static/style.css/private', origin + '/static/sw.js', 'invalid']) assert.equal(key(value), null, value);
});

test('public responses enforce MIME and private/no-store/Vary defenses on both admission and fallback', () => {
  const { publicStaticResponse: allowed } = worker().policy;
  const key = origin + '/static/style.css';
  assert.equal(allowed(new Response('CSS', { headers: { 'Content-Type': 'TEXT/CSS; charset=utf-8', Vary: 'Accept-Encoding' } }), key), true);
  for (const headers of [
    { 'Cache-Control': 'no-store' }, { 'Cache-Control': 'public, No-StOrE' },
    { 'Cache-Control': 'private="field"' }, { 'Cache-Control': 'public, PRIVATE = "field"' },
    { Vary: '*' }, { Vary: 'Accept-Encoding, AUTHORIZATION' }, { Vary: 'Cookie' },
    { 'Content-Type': 'text/html' }, { 'Content-Type': 'application/json' },
  ]) assert.equal(allowed(new Response('PRIVATE', { headers: { 'Content-Type': 'text/css', ...headers } }), key), false);
  assert.equal(allowed(new Response('missing', { status: 404, headers: { 'Content-Type': 'text/css' } }), key), false);
  assert.equal(allowed(undefined, key), false);
  for (const properties of [{ redirected: true }, { type: 'opaque' }, { type: 'opaqueredirect' },
    { url: 'https://other.invalid/static/style.css' }, { url: origin + '/api/settings' }]) {
    const response = new Response('not public', { headers: { 'Content-Type': 'text/css' } });
    for (const [name, value] of Object.entries(properties)) Object.defineProperty(response, name, { value });
    assert.equal(allowed(response, key), false);
  }
});

test('fallback never searches foreign/old caches and rechecks current owned response headers', async () => {
  const h = worker({ offline: true }), key = origin + '/static/style.css';
  for (const name of ['other-app', 'cypher65-v12', 'cypher65-v13'])
    await (await h.caches.open(name)).put(key, new Response('FOREIGN-OR-OLD', { headers: { 'Content-Type': 'text/css' } }));
  assert.equal((await h.dispatch(new Request(key))).status, 503);
  const cache = await h.caches.open(h.policy.CACHE_NAME);
  for (const headers of [{ 'Cache-Control': 'no-store' }, { 'Cache-Control': 'private' }, { Vary: 'Authorization' }, { Vary: '*' }, { 'Content-Type': 'text/html' }]) {
    await cache.put(key, new Response('PRIVATE', { headers: { 'Content-Type': 'text/css', ...headers } }));
    assert.equal((await h.dispatch(new Request(key))).status, 503);
  }
  await cache.put(key, new Response('PUBLIC-CURRENT', { headers: { 'Content-Type': 'text/css' } }));
  assert.equal(await (await h.dispatch(new Request(key + '?v763'))).text(), 'PUBLIC-CURRENT');
  assert.equal(await h.dispatch(new Request(key, { headers: { Authorization: '' } })), undefined);
  assert.equal(await h.dispatch(new Request(key, { cache: 'no-store' })), undefined);
  assert.equal(await h.dispatch({ method: 'GET', url: key, mode: 'navigate' }), undefined);
  assert.equal(await h.dispatch({ method: 'GET', url: key, destination: 'document' }), undefined);
  assert.equal(await h.dispatch({ method: 'POST', url: key }), undefined);
});

test('only successful public static network responses enter the canonical owned key', async () => {
  const h = worker(), key = origin + '/static/style.css';
  assert.equal((await h.dispatch(new Request(key + '?v763'))).status, 200);
  assert.deepEqual(h.puts, [key]);
  assert.equal(await (await h.caches.open(h.policy.CACHE_NAME)).match(key).then(r => r.text()), 'public');
});

test('activation removes only obsolete owned generations and awaits claim', async () => {
  const h = worker();
  for (const name of ['cypher65-v12', 'cypher65-v13', h.policy.CACHE_NAME, 'other-app', 'cypher65-v12-other']) await h.caches.open(name);
  let completion; h.handlers.activate({ waitUntil: promise => { completion = promise; } }); await completion;
  assert.deepEqual(h.deleted.sort(), ['cypher65-v12', 'cypher65-v13']);
  assert.deepEqual([...h.stores.keys()].sort(), [h.policy.CACHE_NAME, 'other-app', 'cypher65-v12-other'].sort());
  assert.equal(h.calls.at(-1), 'claim');
});

test('install warms only public files without cookies; bad MIME/private/fetch failures are never cached', async () => {
  const h = worker(); let completion;
  h.handlers.install({ waitUntil: promise => { completion = promise; } }); await completion;
  assert.equal(h.calls.length, 6); assert.deepEqual(h.puts, [origin + '/static/style.css']);
  for (const request of h.calls) { assert.equal(request.credentials, 'omit'); assert.equal(request.cache, 'reload'); }
  const rejected = worker({ fetchImpl: async request => {
    if (request.url.endsWith('style.css')) throw Error('fixture offline');
    return new Response('PRIVATE', { headers: { 'Content-Type': 'text/javascript', 'Cache-Control': 'private' } });
  } });
  rejected.handlers.install({ waitUntil: promise => { completion = promise; } }); await completion;
  assert.deepEqual(rejected.puts, []);
});

test('network responses cannot enter cache with private headers, missing MIME or redirects', async () => {
  for (const headers of [{ 'Cache-Control': 'no-store' }, { 'Cache-Control': 'private="field"' },
    { Vary: '*' }, { Vary: 'Cookie' }, { Vary: 'Authorization' }, { 'Content-Type': '' }]) {
    const h = worker({ fetchImpl: async () => new Response('NETWORK-ONLY', { headers: { 'Content-Type': 'text/css', ...headers } }) });
    assert.equal(await (await h.dispatch(new Request(origin + '/static/style.css'))).text(), 'NETWORK-ONLY');
    assert.deepEqual(h.puts, []);
  }
  const response = new Response('redirect', { headers: { 'Content-Type': 'text/css' } });
  Object.defineProperty(response, 'redirected', { value: true });
  const h = worker({ fetchImpl: async () => response });
  assert.equal((await h.dispatch(new Request(origin + '/static/style.css'))).status, 200);
  assert.deepEqual(h.puts, []);
});

test('storage failures never replace a valid network response or expose fallback data', async () => {
  const write = worker({ putFails: true });
  assert.equal((await write.dispatch(new Request(origin + '/static/style.css'))).status, 200);
  const read = worker({ offline: true, openFails: true });
  assert.equal((await read.dispatch(new Request(origin + '/static/style.css'))).status, 503);
});
