// @ts-check
// Issue #838: presentation fixtures are not hardware/integration certification.
import { test, expect } from '@playwright/test';
import { createRequire } from 'node:module';
const require = createRequire(import.meta.url);
test.use({ serviceWorkers: 'block', contextOptions: { reducedMotion: 'reduce' } });

function history(id = 'axe-a', hours = 6) {
  const now = Math.floor(Date.now() / 1000);
  const samples = Array.from({ length: 120 }, (_, i) => ({
    ts: now - (120 - i) * 25 + 10, temperature_c: 44 + Math.round(Math.sin(i / 10) * 4) + (i > 60 ? 10 : 0),
    hashrate_hs: 1e12 + Math.sin(i / 12) * 1e11, power_watts: 15 + i / 30,
    fan_rpm: 2200 + i * 5, fan_speed: 45, frequency_mhz: i > 60 ? 525 : 500, voltage_mv: 1100,
    source: 'axe_telemetry', window_seconds: null, gap_before_seconds: null,
  })).filter((_, i) => i < 30 || i > 70);
  samples[0].temperature_c = 42; samples[0].power_watts = 0; samples[0].fan_rpm = 0;
  samples[30].gap_before_seconds = samples[30].ts - samples[29].ts;
  Object.assign(samples.at(-1), { temperature_c: 55, fan_rpm: null, fan_speed: 65 });
  return { schema_version: 1, generated_at: now, source: 'local_telemetry_history', hours,
    device: { id, name: 'Bancada de teste', status: 'ONLINE' }, samples,
    markers: [{ ts: samples[10].ts, kind: 'maintenance', type: 'cleaning' },
      { ts: samples[31].ts, kind: 'observed_configuration_change', changes: [{ field: 'frequency_mhz', before: 500, after: 525 }] }],
    coverage: { returned: samples.length, scanned: samples.length, skipped: 1, gaps: 1, truncated: false },
    latest_sample_ts: samples.at(-1).ts, age_seconds: 15, stale_after_s: 900, state: 'current',
    maintenance_context: 'available', maintenance_truncated: false };
}

async function fixtures(page) {
  await page.route('**/api/thermal-timeline/devices', route => route.fulfill({ json: { devices: [{ id: 'axe-a', name: 'Bancada de teste' }, { id: 'axe-b', name: 'Segundo equipamento' }], truncated: false } }));
  await page.route('**/api/thermal-timeline?*', route => {
    const url = new URL(route.request().url()); return route.fulfill({ json: history(url.searchParams.get('device_id'), Number(url.searchParams.get('hours'))) });
  });
}

test('synchronized evidence lanes, real zero, PWM distinction, keyboard and accessible original layout', async ({ page }, info) => {
  const requests = []; page.on('request', request => { if (request.url().includes('/api/')) requests.push(request); });
  await fixtures(page); await page.goto('/thermal-timeline');
  await expect(page.locator('#thermal-state')).toContainText('observações recentes');
  await expect(page.locator('.thermal-lane')).toHaveCount(4);
  await expect(page.locator('#thermal-values')).toContainText('55 °C');
  await expect(page.locator('#thermal-values')).toContainText('65 %');
  const fan = page.locator('.thermal-value').filter({ hasText: 'Ventilação medida' });
  await expect(fan.locator('dd')).toHaveText('—');
  await expect(page.locator('#thermal-events')).toContainText('Limpeza registrada');
  await expect(page.locator('#thermal-events')).toContainText('500 MHz → 525 MHz');
  await expect(page.locator('#thermal-coverage')).toContainText('1 lacunas');
  expect(await page.locator('.thermal-lane').first().locator('polyline').count()).toBeGreaterThanOrEqual(2);
  await expect(page.locator('#thermal-charts')).toContainText('Recorte observado');
  expect(await page.locator('svg rect[data-gap]').count()).toBe(4);
  await page.locator('#thermal-focus').click(); await expect(page.locator('#thermal-charts')).toContainText('Janela inteira consultada');
  await page.locator('#thermal-focus').click(); await expect(page.locator('#thermal-charts')).toContainText('Recorte observado');
  await page.locator('#thermal-cursor').focus(); await page.keyboard.press('Home');
  await expect(page.locator('#thermal-values')).toContainText('42 °C');
  await expect(page.locator('#thermal-values')).toContainText('0 W');
  await expect(page.locator('#thermal-values')).toContainText('0 RPM');
  await page.keyboard.press('End');
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  expect(await page.locator('.thermal-header').evaluate(el => getComputedStyle(el).animationName)).toBe('none');
  await page.addScriptTag({ path: require.resolve('axe-core') });
  const violations = await page.evaluate(async () => (await window.axe.run(document)).violations.map(v => ({ id: v.id, impact: v.impact })));
  expect(violations).toEqual([]);
  expect(requests.every(request => request.method() === 'GET' && request.url().includes('/api/thermal-timeline'))).toBe(true);
  await page.screenshot({ path: info.outputPath('thermal-timeline.png'), fullPage: true });
});

test('picker error can recover with Atualizar without a page reload', async ({ page }) => {
  let calls = 0;
  await fixtures(page);
  await page.route('**/api/thermal-timeline/devices', route => ++calls === 1 ? route.fulfill({ status: 503, json: {} }) : route.fulfill({ json: { devices: [{ id: 'axe-a', name: 'Recovered device' }], truncated: false } }));
  await page.goto('/thermal-timeline'); await expect(page.locator('#thermal-state')).toContainText('indisponível');
  await page.locator('#thermal-refresh').click();
  await expect.poll(() => calls).toBe(2);
  await expect(page.locator('#thermal-device')).toHaveValue('axe-a');
  await expect(page.locator('#thermal-values')).toContainText('55 °C');
});

test('blocked localStorage getter produces an explicit safe session state without anonymous requests', async ({ page }) => {
  let requests = 0; const errors = [];
  page.on('request', request => { if (request.url().includes('/api/thermal-timeline')) requests++; });
  page.on('pageerror', error => errors.push(error.message));
  await page.addInitScript(() => Object.defineProperty(window, 'localStorage', { configurable: true, get() { throw new DOMException('Storage blocked', 'SecurityError'); } }));
  await page.goto('/thermal-timeline');
  await expect(page.locator('#thermal-state')).toContainText('Sessão necessária');
  await expect(page.locator('#thermal-refresh')).toBeEnabled();
  expect(requests).toBe(0); expect(errors).toEqual([]);
});

test('range/device changes are fenced against delayed older JSON and names render only as text', async ({ page }) => {
  let release, delayed = true;
  await fixtures(page);
  await page.route('**/api/thermal-timeline/devices', route => route.fulfill({ json: { devices: [{ id: 'axe-a', name: '<img src=x onerror=alert(1)>' }, { id: 'axe-b', name: 'Segundo' }], truncated: false } }));
  await page.route('**/api/thermal-timeline?*', async route => {
    const url = new URL(route.request().url());
    if (delayed) { delayed = false; await new Promise(resolve => { release = resolve; }); }
    await route.fulfill({ json: history(url.searchParams.get('device_id'), Number(url.searchParams.get('hours'))) }).catch(() => {});
  });
  await page.goto('/thermal-timeline'); await expect.poll(() => typeof release).toBe('function');
  await page.selectOption('#thermal-device', 'axe-b'); await page.selectOption('#thermal-hours', '1'); release();
  await expect(page.locator('#thermal-values')).toContainText('55 °C');
  await expect(page.locator('#thermal-device')).toHaveValue('axe-b');
  expect(await page.locator('#thermal-device img').count()).toBe(0);
  await expect(page.locator('#thermal-config')).toContainText('axe_telemetry');
});

test('stale/missing/legacy context and truncation are explicit; no unsupported failure forecast', async ({ page }) => {
  await fixtures(page);
  await page.route('**/api/thermal-timeline?*', route => {
    const data = history(); data.state = 'stale'; data.samples.forEach(sample => { sample.ts -= 1500; });
    data.latest_sample_ts = data.samples.at(-1).ts; data.markers = []; data.maintenance_context = 'legacy_unscoped'; data.coverage.truncated = true;
    return route.fulfill({ json: data });
  });
  await page.goto('/thermal-timeline'); await expect(page.locator('#thermal-state')).toContainText('antiga');
  await expect(page.locator('#thermal-maintenance')).toContainText('sem tenant');
  await expect(page.locator('#thermal-coverage')).toContainText('Limite atingido');
  await expect(page.locator('#thermal-events')).toContainText('Nenhum marco comprovado');
});

test('bounded picker and maintenance context disclose truncation without hidden expansion', async ({ page }) => {
  await fixtures(page);
  await page.route('**/api/thermal-timeline/devices', route => route.fulfill({ json: { devices: [{ id: 'axe-a', name: 'A' }], truncated: true } }));
  await page.route('**/api/thermal-timeline?*', route => { const data = history(); data.maintenance_truncated = true; return route.fulfill({ json: data }); });
  await page.goto('/thermal-timeline'); await expect(page.locator('#thermal-source')).toContainText('100 primeiros dispositivos');
  await expect(page.locator('#thermal-maintenance')).toContainText('200 manutenções mais recentes');
  await expect(page.locator('#thermal-maintenance')).toContainText('não é atestado físico');
});

test('session rejection clears private device names, values and context; offline is explicit', async ({ page, context }) => {
  let reject = false;
  await fixtures(page);
  await page.route('**/api/thermal-timeline?*', route => reject ? route.fulfill({ status: 401, json: {} }) : route.fulfill({ json: history() }));
  await page.goto('/thermal-timeline'); await expect(page.locator('#thermal-values')).toContainText('55 °C');
  reject = true; await page.locator('#thermal-refresh').click();
  await expect(page.locator('#thermal-state')).toContainText('Sessão necessária');
  await expect(page.locator('#thermal-values')).toBeEmpty(); await expect(page.locator('#thermal-events')).toBeEmpty();
  await expect(page.locator('#thermal-device')).not.toContainText('Bancada de teste');
  await context.setOffline(true); await expect(page.locator('#thermal-state')).toContainText('offline');
});

test('fallback without JavaScript and dashboard entry remain accessible', async ({ browser, baseURL, page }) => {
  const response = await page.request.get('/'); expect(await response.text()).toContain('id="thermal-timeline-link"');
  const context = await browser.newContext({ javaScriptEnabled: false, baseURL });
  try { const fallback = await context.newPage(); await fallback.goto('/thermal-timeline'); await expect(fallback.locator('h1')).toBeVisible(); await expect(fallback.locator('noscript')).toBeVisible(); }
  finally { await context.close(); }
});

test.describe('real SW private history', () => {
  test.use({ serviceWorkers: 'allow' });
  test('history aliases cannot be stored, and an old private cache entry cannot be served offline', async ({ page, context }) => {
    await page.goto('/thermal-timeline');
    await page.evaluate(async () => {
      await navigator.serviceWorker.register('/sw.js', { scope: '/' }); await navigator.serviceWorker.ready;
      if (!navigator.serviceWorker.controller) await new Promise(resolve => navigator.serviceWorker.addEventListener('controllerchange', resolve, { once: true }));
    });
    const outcome = await page.evaluate(async () => {
      const cache = await caches.open('thermal-test'); const results = [];
      for (const path of ['/api/thermal-timeline/devices', '/api/%74hermal-timeline/devices', '/api//thermal-timeline/devices', '/%74hermal-timeline']) {
        const response = await fetch(path); let rejected = false;
        try { await cache.put(path, response.clone()); } catch (error) { rejected = error.name === 'TypeError'; }
        results.push({ status: response.status, rejected });
      }
      await caches.delete('thermal-test'); return results;
    });
    expect(outcome.every(result => result.status === 200 && result.rejected)).toBe(true);
    await page.evaluate(async () => (await caches.open('cypher65-v12')).put('/api/%74hermal-timeline/devices', new Response('PRIVATE-TEST-MARKER')));
    await context.setOffline(true);
    expect(await page.evaluate(async () => { try { return await (await fetch('/api/%74hermal-timeline/devices')).text(); } catch { return 'unavailable'; } })).toBe('unavailable');
  });
});
