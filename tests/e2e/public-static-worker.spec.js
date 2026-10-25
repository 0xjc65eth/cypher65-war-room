// @ts-check
/** #868: real production SW + Flask headers + CacheAPI, synthetic A/B identities.
 * Fixture imports Flask without background workers; no external request/account.
 */
import { test, expect } from '@playwright/test';
import { spawn } from 'node:child_process';
import { existsSync } from 'node:fs';
import { createInterface } from 'node:readline';

test.use({ serviceWorkers: 'allow' });
let server, origin, tokens;
test.beforeAll(async () => {
  const python = process.env.CYPHER65_TEST_PYTHON || ['.venv/bin/python', 'venv/bin/python'].find(existsSync) || 'python3';
  server = spawn(python, ['tests/e2e/support/public_static_cache_fixture.py'], {
    // Do not inherit provider/cloud credentials into this synthetic fixture.
    env: { PATH: process.env.PATH, PYTHONUNBUFFERED: '1', PYTHONDONTWRITEBYTECODE: '1' },
    stdio: ['ignore', 'pipe', 'pipe'],
  });
  const lines = createInterface({ input: server.stdout });
  let errors = ''; server.stderr.on('data', data => { errors += data; });
  const ready = await new Promise((resolve, reject) => {
    const timeout = setTimeout(() => reject(Error('Flask fixture startup timeout')), 20000);
    lines.on('line', line => {
      try {
        const result = JSON.parse(line);
        if (result.origin && result.tokens) { clearTimeout(timeout); resolve(result); }
      } catch { /* Framework startup text is not the ready contract. */ }
    });
    server.once('error', error => { clearTimeout(timeout); reject(error); });
    server.once('exit', code => { clearTimeout(timeout); reject(Error('Flask fixture exited ' + code + ': ' + errors)); });
  });
  origin = ready.origin; tokens = ready.tokens;
});
test.afterAll(async () => {
  if (server && server.exitCode === null) {
    const exit = new Promise(resolve => server.once('exit', resolve)); server.kill('SIGTERM'); await exit;
  }
});

test('private A/B/no-auth API/documents never survive offline; only current public static files do', async ({ page, context }) => {
  await context.route('**/*', route => new URL(route.request().url()).origin === origin ? route.continue() : route.abort());
  await page.goto(origin + '/__public-cache-probe');
  const evidence = await page.evaluate(async ({ tokens }) => {
    const responses = {};
    for (const owner of ['synthetic-owner-A', 'synthetic-owner-B']) {
      const response = await fetch('/api/settings', { headers: { Authorization: 'Bearer ' + tokens[owner] } });
      const body = await response.clone().json();
      responses[owner] = { status: response.status, tenant: body.tenant_id,
        marker: body.settings.find(setting => setting.key === 'webhook_url').value,
        control: response.headers.get('Cache-Control'), vary: response.headers.get('Vary') };
    }
    // Actual Flask root is rendered but never executed as a browser document.
    const root = await fetch('/');
    responses.root = { status: root.status, control: root.headers.get('Cache-Control'),
      settingsBinding: (await root.text()).includes('window.SETTINGS_CACHE') };
    localStorage.setItem('fixture-preference', 'preserve');
    const db = await new Promise((resolve, reject) => {
      const request = indexedDB.open('unrelated-preferences', 1);
      request.onupgradeneeded = () => request.result.createObjectStore('values');
      request.onsuccess = () => resolve(request.result); request.onerror = () => reject(request.error);
    });
    await new Promise((resolve, reject) => {
      const transaction = db.transaction('values', 'readwrite'); transaction.objectStore('values').put('preserve', 'setting');
      transaction.oncomplete = resolve; transaction.onerror = () => reject(transaction.error);
    }); db.close();
    await (await caches.open('cypher65-v12')).put('/api/settings', new Response('PRIVATE-PRE-ACTIVATION'));
    await (await caches.open('cypher65-v13')).put('/', new Response('PRIVATE-ROOT-PRE-ACTIVATION'));
    await (await caches.open('unrelated-app-data')).put('/foreign-marker', new Response('FOREIGN-PRESERVE'));
    await (await caches.open('cypher65-v13-other-app')).put('/foreign-prefix', new Response('PREFIX-PRESERVE'));
    await navigator.serviceWorker.register('/sw.js', { scope: '/' }); await navigator.serviceWorker.ready;
    if (!navigator.serviceWorker.controller) await new Promise(resolve => navigator.serviceWorker.addEventListener('controllerchange', resolve, { once: true }));
    return responses;
  }, { tokens });
  expect(evidence['synthetic-owner-A']).toMatchObject({ status: 200, tenant: 'synthetic-owner-A', marker: 'https://synthetic-owner-a.invalid/hook' });
  expect(evidence['synthetic-owner-B']).toMatchObject({ status: 200, tenant: 'synthetic-owner-B', marker: 'https://synthetic-owner-b.invalid/hook' });
  expect(evidence['synthetic-owner-A'].control).toContain('no-store');
  expect(evidence['synthetic-owner-A'].vary).not.toContain('*');
  expect(evidence.root).toMatchObject({ status: 200, settingsBinding: true });
  expect(evidence.root.control).toContain('no-store');
  const migration = await page.evaluate(async () => ({ names: await caches.keys(), preference: localStorage.getItem('fixture-preference') }));
  expect(migration.names).not.toContain('cypher65-v12'); expect(migration.names).not.toContain('cypher65-v13');
  expect(migration.names).toContain('cypher65-v14'); expect(migration.names).toContain('unrelated-app-data');
  expect(migration.names).toContain('cypher65-v13-other-app'); expect(migration.preference).toBe('preserve');

  const paths = ['/', '/login', '/api/settings', '/api/fleet/summary', '/api/healthz', '/api/%73ettings',
    '/mini-war-room', '/api/mini-war-room', '/thermal-timeline', '/api/thermal-timeline/devices',
    '/energy-advisor', '/api/energy-advisor/snapshot'];
  const seeded = await page.evaluate(async ({ paths, tokens }) => {
    // Capture the actual Flask private response, not a synthetic header clone.
    const privateResponse = await fetch('/api/settings', { headers: { Authorization: 'Bearer ' + tokens['synthetic-owner-A'] } });
    const root = await fetch('/');
    const privateBody = await privateResponse.clone().text();
    for (const name of ['cypher65-v12', 'cypher65-v13', 'cypher65-v14', 'unrelated-app-data']) {
      const cache = await caches.open(name);
      // Re-seed AFTER activation, including the new generation: migration alone cannot pass.
      for (const path of paths) await cache.put(path, path === '/' ? root.clone() : privateResponse.clone());
    }
    const raw = await (await caches.open('unrelated-app-data')).match('/api/settings');
    const proof = await raw.text();
    const css = await fetch('/static/style.css?v763'); const cssText = await css.text();
    const other = await caches.open('unrelated-app-data');
    await other.put('/static/app.js', new Response('FOREIGN-PUBLIC-PATH', { headers: { 'Content-Type': 'text/javascript' } }));
    const current = await caches.open('cypher65-v14'); await current.delete('/static/app.js');
    await current.put('/static/icon-32x32.png', new Response('PRIVATE-PUBLIC-PATH', { headers: { 'Content-Type': 'image/png', 'Cache-Control': 'private="field"' } }));
    await current.put('/static/icon-192x192.png', new Response('NO-STORE-PUBLIC-PATH', { headers: { 'Content-Type': 'image/png', 'Cache-Control': 'no-store' } }));
    await current.put('/static/icon-512x512.png', new Response('AUTH-VARY-PUBLIC-PATH', { headers: { 'Content-Type': 'image/png', Vary: 'Authorization' } }));
    return { privateAdmitted: proof === privateBody, cssText };
  }, { paths, tokens });
  expect(seeded.privateAdmitted).toBe(true);
  await expect.poll(() => page.evaluate(async () => !!await (await caches.open('cypher65-v14')).match('/static/style.css'))).toBe(true);
  await context.setOffline(true);
  const offline = await page.evaluate(async ({ paths, tokens }) => {
    async function read(path, owner) {
      try { const response = await fetch(path, { headers: owner ? { Authorization: 'Bearer ' + tokens[owner] } : {} });
        return { status: response.status, body: await response.text() }; }
      catch { return { status: 0, body: 'UNAVAILABLE' }; }
    }
    const denied = [];
    for (const owner of [null, 'synthetic-owner-A', 'synthetic-owner-B']) {
      for (const path of paths) denied.push(await read(path, owner));
      if (owner) denied.push(await read('/static/style.css?v763', owner));
    }
    const db = await new Promise(resolve => { const request = indexedDB.open('unrelated-preferences', 1); request.onsuccess = () => resolve(request.result); });
    const preference = await new Promise(resolve => { const request = db.transaction('values').objectStore('values').get('setting'); request.onsuccess = () => resolve(request.result); }); db.close();
    return { denied, css: await read('/static/style.css?v763'), foreign: await read('/static/app.js'),
      privateHeader: await read('/static/icon-32x32.png'), unknown: await read('/static/unknown.js'),
      noStore: await read('/static/icon-192x192.png'), authVary: await read('/static/icon-512x512.png'),
      preference, foreignMarker: await (await (await caches.open('unrelated-app-data')).match('/foreign-marker')).text() };
  }, { paths, tokens });
  expect(offline.denied.every(result => result.status === 0 && result.body === 'UNAVAILABLE')).toBe(true);
  expect(offline.css).toEqual({ status: 200, body: seeded.cssText });
  expect(offline.foreign.status).toBe(503); expect(offline.privateHeader.status).toBe(503);
  expect(offline.noStore.status).toBe(503); expect(offline.authVary.status).toBe(503);
  expect(offline.unknown.status).toBe(0); expect(offline.preference).toBe('preserve'); expect(offline.foreignMarker).toBe('FOREIGN-PRESERVE');
});
