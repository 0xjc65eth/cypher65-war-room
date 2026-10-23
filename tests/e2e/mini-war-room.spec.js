// @ts-check
// Issue #836: browser contract/UI fixtures, not a physical ASIC integration.
import { test, expect } from '@playwright/test';
import { createRequire } from 'node:module';
const require = createRequire(import.meta.url);

test.use({ serviceWorkers: 'block', contextOptions: { reducedMotion: 'reduce' } });

function snapshot(state = 'current') {
  const now = Date.now() / 1000;
  const present = ['current', 'partial'].includes(state);
  return { schema_version: 1, generated_at: now, stale_after_s: 900, state,
    counts: { total: state === 'empty' ? 0 : 1, current: present ? 1 : 0,
      stale: state === 'stale' ? 1 : 0, offline: state === 'offline' ? 1 : 0, unknown: state === 'unknown' ? 1 : 0 },
    metrics: Object.fromEntries([['hashrate', 'H/s', 1e12], ['power', 'W', 0], ['temperature', '°C', 62]].map(([key, unit, value]) =>
      [key, { value: present ? value : null, unit, contributors: present ? 1 : 0,
        oldest_observed_at: present ? now - 10 : null, newest_observed_at: present ? now - 10 : null }])) };
}

test('compact monitor shows only aggregate observations, zero and provenance without overflow or commands', async ({ page }, testInfo) => {
  const requests = [];
  page.on('request', request => { if (request.url().includes('/api/')) requests.push({ url: request.url(), method: request.method() }); });
  await page.route('**/api/mini-war-room', route => route.fulfill({ json: snapshot() }));
  await page.goto('/mini-war-room');
  await expect(page.locator('#mini-state')).toHaveText('Observações recentes');
  await expect(page.locator('#mini-hashrate')).toHaveText('1 TH/s');
  await expect(page.locator('#mini-power')).toHaveText('0 W');
  await expect(page.locator('#mini-temperature')).toHaveText('62 °C');
  await expect(page.locator('#mini-time')).toContainText('UTC');
  await expect(page.locator('footer')).toContainText('Janela média: não informada');
  await expect(page.locator('#mini-hashrate-detail')).toContainText('observação mais antiga');
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  expect(await page.locator('#mini-war-room').evaluate(el => getComputedStyle(el).transitionDuration)).toBe('0s');
  expect(requests).toHaveLength(1); expect(requests[0].method).toBe('GET');
  expect(requests[0].url).toMatch(/\/api\/mini-war-room$/);
  await page.addScriptTag({ path: require.resolve('axe-core') });
  const violations = await page.evaluate(async () => (await window.axe.run(document)).violations.map(v => ({ id: v.id, impact: v.impact })));
  expect(violations).toEqual([]);
  await page.screenshot({ path: testInfo.outputPath('mini-war-room.png'), fullPage: true });
  await expect(page.locator('body')).not.toContainText(/bc1q|192\.168\.|wallet_address|api_key|reboot|overclock/i);
  await page.locator('#mini-pause').focus(); await page.keyboard.press('Enter');
  await expect(page.locator('#mini-state')).toHaveText('Consultas pausadas');
  await expect(page.locator('#mini-hashrate')).toHaveText('—');
});

test('all unavailable states clear current measurements and loading has a static skeleton', async ({ page }) => {
  let state = 'current';
  let release;
  await page.route('**/api/mini-war-room', async route => { if (release === undefined) await new Promise(resolve => { release = resolve; }); await route.fulfill({ json: snapshot(state) }); });
  await page.goto('/mini-war-room');
  await expect(page.locator('#mini-metrics')).toHaveAttribute('aria-busy', 'true');
  await expect(page.locator('#mini-refresh')).toBeDisabled();
  await expect.poll(() => typeof release).toBe('function'); release();
  await expect(page.locator('#mini-state')).toHaveText('Observações recentes');
  for (const [next, label] of [['empty', 'Nenhum dispositivo'], ['unknown', 'Observações indisponíveis'], ['stale', 'Dados antigos'], ['offline', 'Sem conexão']]) {
    state = next; await page.locator('#mini-refresh').click();
    await expect(page.locator('#mini-state')).toContainText(label);
    await expect(page.locator('#mini-hashrate')).toHaveText('—');
  }
});

test('transparent OBS uses the same authenticated context; rejection clears prior observations', async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem('_cypher65_auth_session', JSON.stringify({ access_token: 'test-only-tenant-a' })));
  let denied = false, auth;
  await page.route('**/api/mini-war-room', route => {
    auth = route.request().headers().authorization;
    return denied ? route.fulfill({ status: 401, json: { error: 'authentication required' } }) : route.fulfill({ json: snapshot() });
  });
  await page.goto('/mini-war-room?presentation=obs');
  await expect(page.locator('#mini-state')).toHaveText('Observações recentes');
  expect(auth).toBe('Bearer test-only-tenant-a');
  expect(await page.locator('body').evaluate(el => getComputedStyle(el).backgroundColor)).toBe('rgba(0, 0, 0, 0)');
  expect(await page.locator('html').evaluate(el => getComputedStyle(el).backgroundColor)).toBe('rgba(0, 0, 0, 0)');
  await expect(page.locator('.mini-help')).toContainText('mesmo contexto');
  denied = true; await page.locator('#mini-refresh').click();
  await expect(page.locator('#mini-state')).toContainText('Sessão necessária');
  await expect(page.locator('#mini-hashrate')).toHaveText('—');
  expect(page.url()).not.toContain('test-only-tenant-a');
});

test('session invalidation clears DOM and pending older JSON cannot republish', async ({ page }) => {
  let release;
  await page.route('**/api/mini-war-room', async route => {
    await new Promise(resolve => { release = resolve; });
    await route.fulfill({ json: snapshot() }).catch(() => {});
  });
  await page.goto('/mini-war-room');
  await expect.poll(() => typeof release).toBe('function');
  await page.evaluate(() => {
    localStorage.setItem('_cypher65_auth_session', '{}');
    window.dispatchEvent(new StorageEvent('storage', { key: '_cypher65_auth_session' }));
  });
  release();
  await expect(page.locator('#mini-state')).toContainText('Sessão necessária');
  await expect(page.locator('#mini-hashrate')).toHaveText('—');
});

test('transport errors and actual offline event do not retain current capacity', async ({ page, context }) => {
  let failed = false;
  await page.route('**/api/mini-war-room', route => failed ? route.fulfill({ status: 503, json: {} }) : route.fulfill({ json: snapshot() }));
  await page.goto('/mini-war-room'); await expect(page.locator('#mini-state')).toHaveText('Observações recentes');
  failed = true; await page.locator('#mini-refresh').click();
  await expect(page.locator('#mini-state')).toContainText('Falha na consulta');
  await expect(page.locator('#mini-power')).toHaveText('—');
  await context.setOffline(true);
  await expect(page.locator('#mini-state')).toContainText('Sem conexão');
});

test('disabled JavaScript keeps the monitor and fallback instructions visible', async ({ browser, baseURL }) => {
  const context = await browser.newContext({ javaScriptEnabled: false, baseURL });
  try {
    const page = await context.newPage(); await page.goto('/mini-war-room');
    await expect(page.locator('h1')).toBeVisible();
    await expect(page.locator('noscript')).toBeVisible();
    expect(await page.locator('#mini-war-room').evaluate(el => getComputedStyle(el).opacity)).toBe('1');
  } finally { await context.close(); }
});

test.describe('real service-worker private route aliases', () => {
  test.use({ serviceWorkers: 'allow' });
  test('does not cache private aliases or recover even a preseeded private response offline', async ({ page, context }) => {
    await page.goto('/mini-war-room');
    await page.evaluate(async () => {
      await navigator.serviceWorker.register('/sw.js', { scope: '/' });
      await navigator.serviceWorker.ready;
      if (!navigator.serviceWorker.controller) await new Promise(resolve => navigator.serviceWorker.addEventListener('controllerchange', resolve, { once: true }));
    });
    const paths = ['/api/mini-war-room', '/api/%6dini-war-room', '/%61pi/mini-war-room', '/api//mini-war-room', '/api/%2fmini-war-room', '/%6dini-war-room?presentation=obs'];
    const results = await page.evaluate(async paths => {
      const results = [];
      for (const path of paths) {
        const response = await fetch(path, { cache: 'no-store' });
        const cache = await caches.open('mini-legacy-put-probe');
        let rejected = false;
        try { await cache.put(path, response.clone()); } catch (error) { rejected = error.name === 'TypeError'; }
        await response.text(); results.push({ status: response.status, cache: response.headers.get('cache-control'), rejected });
      }
      await caches.delete('mini-legacy-put-probe');
      return results;
    }, paths);
    for (const result of results) { expect(result.status).toBe(200); expect(result.cache).toContain('no-store'); expect(result.rejected).toBe(true); }
    const retained = await page.evaluate(async () => {
      const keys = [];
      for (const name of await caches.keys()) for (const request of await (await caches.open(name)).keys()) keys.push(request.url);
      return keys.filter(key => decodeURIComponent(new URL(key).pathname).replace(/\/{2,}/g, '/').includes('mini-war-room'));
    });
    expect(retained).toEqual([]);
    // Synthetic private marker: proves the fallback cannot recover an old entry.
    await page.evaluate(async () => {
      const cache = await caches.open('cypher65-v12');
      await cache.put('/api/%6dini-war-room', new Response('PRIVATE-TEST-MARKER'));
    });
    await context.setOffline(true);
    const offline = await page.evaluate(async () => {
      try { return await (await fetch('/api/%6dini-war-room')).text(); } catch { return 'network-unavailable'; }
    });
    expect(offline).toBe('network-unavailable');
  });
});
