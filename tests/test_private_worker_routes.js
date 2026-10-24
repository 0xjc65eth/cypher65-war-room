/** Issue #863: exercise the actual composed service worker, not a copied policy. */
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

const workerPath = fileURLToPath(new URL('../static/sw.js', import.meta.url));
const origin = 'https://fixture.test';
const families = ['mini-war-room', 'thermal-timeline', 'energy-advisor'];

function harness() {
  const handlers = {}, stores = new Map(), fetches = [], lookups = [], deleted = [];
  let online = true, claimed = 0;
  const absolute = key => typeof key === 'string' ? new URL(key, origin).href : key.url;
  const cache = name => {
    if (!stores.has(name)) stores.set(name, new Map());
    const entries = stores.get(name);
    return {
      async addAll(paths) { for (const path of paths) entries.set(absolute(path), new Response('PUBLIC:' + path)); },
      async put(key, value) { entries.set(absolute(key), value.clone()); },
    };
  };
  vm.runInNewContext(fs.readFileSync(workerPath, 'utf8'), {
    URL, Request, Response, Promise, console,
    self: { location: { origin }, skipWaiting: async () => {},
      clients: { claim: async () => { claimed++; } },
      addEventListener: (name, callback) => { handlers[name] = callback; } },
    caches: {
      async open(name) { return cache(name); },
      async keys() { return [...stores.keys()]; },
      async delete(name) { deleted.push(name); return stores.delete(name); },
      async match(key) {
        const url = absolute(key); lookups.push(url);
        for (const entries of stores.values()) if (entries.has(url)) return entries.get(url).clone();
      },
    },
    fetch: async request => {
      fetches.push(request.url);
      if (!online) throw Error('fixture offline');
      return new Response('NETWORK:' + request.url);
    },
  }, { filename: workerPath });
  return {
    stores, fetches, lookups, deleted,
    offline() { online = false; },
    get claimed() { return claimed; },
    async lifecycle(name) { const pending = []; handlers[name]({ waitUntil: value => pending.push(value) }); await Promise.all(pending); },
    async request(url, method = 'GET') {
      let intercepted = false, response;
      handlers.fetch({ request: { url, method }, respondWith(value) { intercepted = true; response = value; } });
      return { intercepted, response: await response };
    },
    async seed(name, path, value) { await cache(name).put(path, new Response(value)); },
  };
}

for (const family of families) {
  test(`production SW bypasses every private ${family} page/API alias`, async () => {
    const h = harness();
    const encoded = '%' + family.charCodeAt(0).toString(16) + family.slice(1);
    const paths = [
      `/${family}`, `/${family}/`, `/${family}/private-child`, `//${family}///?mode=obs`, `/${encoded}?view=private`,
      `/api/${family}`, `/api/${family}/?tenant=ignored`, `/api/${family}/devices`,
      `/api/${encoded}/snapshot?device_id=a`, `/%61pi/${family}`, `/api//${family}///devices`,
      `/api/%2f${family}/devices`, `/%2f${encoded}/`,
    ];
    for (const path of paths) {
      const { intercepted } = await h.request(origin + path);
      assert.equal(intercepted, false, path);
    }
    assert.deepEqual(h.fetches, []); assert.deepEqual(h.lookups, []); assert.equal(h.stores.size, 0);
  });
}

test('actual SW rejects foreign origins, malformed URLs/encoding and non-GET methods', async () => {
  const h = harness();
  for (const url of [
    origin + '.evil.test/static/app.js', 'https://fixture.test@evil.test/static/app.js',
    'https://fixture.test:444/static/app.js', 'http://fixture.test/static/app.js',
    origin + '/api/%zz', origin + '/static/%E0%A4%A', 'not an absolute URL',
  ]) assert.equal((await h.request(url)).intercepted, false, url);
  assert.equal((await h.request(origin + '/static/app.js', 'POST')).intercepted, false);
  assert.deepEqual(h.fetches, []); assert.deepEqual(h.lookups, []); assert.equal(h.stores.size, 0);
});

test('generation activation evicts obsolete owned caches and preserves foreign stores', async () => {
  const h = harness();
  await h.seed('cypher65-v12', '/api/mini-war-room', 'PRIVATE-OLD');
  await h.seed('unrelated-app-data', '/foreign', 'OTHER-APP');
  await h.seed('cypher65-v12-other-app', '/foreign-prefix', 'OTHER-APP-PREFIX');
  await h.lifecycle('install'); await h.lifecycle('activate');
  assert.equal(h.stores.has('cypher65-v12'), false);
  assert.equal(h.stores.has('cypher65-v13'), true);
  assert.equal(h.stores.has('unrelated-app-data'), true);
  assert.equal(h.stores.has('cypher65-v12-other-app'), true);
  assert.deepEqual(h.deleted, ['cypher65-v12']); assert.equal(h.claimed, 1);
});

test('seeded private entries cannot reach offline fallback, public static still works', async () => {
  const h = harness();
  for (const family of families) await h.seed('cypher65-v12', `/api/${family}`, 'PRIVATE-' + family);
  await h.seed('cypher65-v13', '/static/style.css', 'PUBLIC-CSS');
  h.offline();
  for (const family of families) assert.equal((await h.request(origin + `/api/${family}`)).intercepted, false);
  assert.deepEqual(h.fetches, []); assert.deepEqual(h.lookups, []);
  const publicResult = await h.request(origin + '/static/style.css?revision=fixture');
  assert.equal(publicResult.intercepted, true); assert.equal(await publicResult.response.text(), 'PUBLIC-CSS');
  const missing = await h.request(origin + '/static/missing-public.txt');
  assert.equal(missing.response.status, 503);
});

test('online public static/API caching and segment-boundary lookalikes are preserved', async () => {
  const h = harness();
  for (const path of ['/static/app.js', '/api/healthz', '/api/mini-war-room-extra']) {
    const result = await h.request(origin + path);
    assert.equal(result.intercepted, true); assert.match(await result.response.text(), /^NETWORK:/);
  }
  await Promise.resolve(); await Promise.resolve();
  assert.equal(h.stores.has('cypher65-v13'), true);
  assert.equal(h.stores.get('cypher65-v13').size, 3);
});
