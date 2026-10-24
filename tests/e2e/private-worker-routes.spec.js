// @ts-check
/** Issue #863: real SW/Cache API against a local fixture server, no providers.
 * The production worker and public assets are served unchanged. Private HTTP
 * responses are synthetic no-store/Vary:* fixtures, not Flask auth evidence.
 */
import { test, expect } from '@playwright/test';
import { createServer } from 'node:http';
import { readFile } from 'node:fs/promises';

test.use({ serviceWorkers: 'allow' });
let server, origin;
const publicFiles = new Map([
  ['/sw.js', ['../../static/sw.js', 'text/javascript']],
  ['/static/style.css', ['../../static/style.css', 'text/css']],
  ['/static/app.js', ['../../static/app.js', 'text/javascript']],
  ['/static/manifest.json', ['../../static/manifest.json', 'application/json']],
]);

test.beforeAll(async () => {
  server = createServer(async (request, response) => {
    const path = new URL(request.url, 'http://fixture.test').pathname;
    const file = publicFiles.get(path);
    if (file) {
      response.writeHead(200, { 'Content-Type': file[1], 'Cache-Control': 'no-cache', 'Service-Worker-Allowed': '/' });
      response.end(await readFile(new URL(file[0], import.meta.url)));
    } else if (path === '/') {
      response.writeHead(200, { 'Content-Type': 'text/html', 'Cache-Control': 'no-store' });
      response.end('<!doctype html><html lang="en"><title>Local worker boundary fixture</title><body>Service worker probe</body></html>');
    } else if (path === '/api/healthz') {
      response.writeHead(200, { 'Content-Type': 'application/json' }); response.end('{"fixture":true}');
    } else {
      response.writeHead(200, { 'Content-Type': 'application/json', 'Cache-Control': 'no-store, private', Vary: '*' });
      response.end('{"fixture":"SYNTHETIC-PRIVATE-NETWORK"}');
    }
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  origin = 'http://127.0.0.1:' + server.address().port;
});

test.afterAll(async () => { if (server) await new Promise(resolve => server.close(resolve)); });

test('obsolete cache eviction, private seeded offline denial and public offline control', async ({ page, context }) => {
  await page.goto(origin);
  const privatePaths = [
    '/mini-war-room', '/mini-war-room/private-child', '/api/mini-war-room?fixture=private', '/api/%6dini-war-room', '/api//mini-war-room/',
    '/thermal-timeline/', '/thermal-timeline/private-child', '/api/thermal-timeline?device_id=fixture', '/api/%74hermal-timeline/devices',
    '/energy-advisor', '/energy-advisor/private-child', '/api/energy-advisor/snapshot?device_id=fixture', '/api/%65nergy-advisor/devices',
  ];
  await page.evaluate(async paths => {
    localStorage.setItem('fixture-user-preference', 'preserve');
    const obsolete = await caches.open('cypher65-v12');
    for (const path of paths) await obsolete.put(path, new Response('PRIVATE-OBSOLETE'));
    await (await caches.open('unrelated-app-data')).put('/foreign-fixture', new Response('FOREIGN-PRESERVE'));
    await (await caches.open('cypher65-v12-other-app')).put('/foreign-prefix', new Response('FOREIGN-PREFIX-PRESERVE'));
    await navigator.serviceWorker.register('/sw.js', { scope: '/' }); await navigator.serviceWorker.ready;
    if (!navigator.serviceWorker.controller) await new Promise(resolve => navigator.serviceWorker.addEventListener('controllerchange', resolve, { once: true }));
  }, privatePaths);

  const migration = await page.evaluate(async () => ({ names: await caches.keys(), preference: localStorage.getItem('fixture-user-preference') }));
  expect(migration.names).not.toContain('cypher65-v12'); expect(migration.names).toContain('cypher65-v13');
  expect(migration.names).toContain('unrelated-app-data'); expect(migration.names).toContain('cypher65-v12-other-app');
  expect(migration.preference).toBe('preserve');

  // Verify actual browser Cache API admission without intercepting responses.
  const admissions = await page.evaluate(async paths => {
    const cache = await caches.open('fixture-admission-probe'), results = [];
    for (const path of paths) {
      const response = await fetch(path); let rejected = false;
      try { await cache.put(path, response.clone()); } catch (error) { rejected = error.name === 'TypeError'; }
      results.push({ status: response.status, rejected });
    }
    await caches.delete('fixture-admission-probe'); return results;
  }, privatePaths);
  expect(admissions.every(result => result.status === 200 && result.rejected)).toBe(true);

  // Re-seed AFTER activation: eviction alone must not make this test pass.
  await page.evaluate(async paths => {
    for (const name of ['cypher65-v12', 'cypher65-v13', 'unrelated-app-data']) {
      const cache = await caches.open(name);
      for (const path of paths) await cache.put(path, new Response('PRIVATE-SEEDED-AFTER-CLAIM'));
    }
    const response = await fetch('/static/style.css?fixture=public-control');
    window.publicControl = await response.text();
  }, privatePaths);
  await expect.poll(() => page.evaluate(async () => !!await (await caches.open('cypher65-v13')).match('/static/style.css?fixture=public-control'))).toBe(true);
  await context.setOffline(true);
  const offline = await page.evaluate(async paths => {
    const results = [];
    for (const path of paths) {
      try { results.push(await (await fetch(path)).text()); } catch { results.push('UNAVAILABLE'); }
    }
    const publicResponse = await fetch('/static/style.css?fixture=public-control');
    const unversioned = await fetch('/static/manifest.json?fixture=uncached-query');
    const missing = await fetch('/static/missing-public-fixture');
    return { results, publicStatus: publicResponse.status, publicMatches: await publicResponse.text() === window.publicControl,
      manifestStatus: unversioned.status, missingStatus: missing.status };
  }, privatePaths);
  expect(offline.results).toEqual(privatePaths.map(() => 'UNAVAILABLE'));
  expect(offline.publicStatus).toBe(200); expect(offline.publicMatches).toBe(true);
  expect(offline.manifestStatus).toBe(200); expect(offline.missingStatus).toBe(503);
});
