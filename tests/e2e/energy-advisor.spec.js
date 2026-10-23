// @ts-check
// Browser contract fixtures are not certification of ASIC or MQTT integrations.
import { test, expect } from '@playwright/test';
import { createRequire } from 'node:module';
const require = createRequire(import.meta.url);
test.use({ serviceWorkers: 'block', contextOptions: { reducedMotion: 'reduce' } });

const device = (id = 'a') => ({ id, name: id === 'a' ? 'Bitaxe — bancada de teste' : 'Segundo dispositivo', model: 'Gamma', firmware: 'AxeOS', firmware_version: '2.9', capabilities: ['telemetry'] });
function snapshot(id = 'a') {
  const now = Math.floor(Date.now() / 1000);
  return { schema_version: 1, generated_at: now, device: device(id), telemetry: { state: 'current', source: 'axe_telemetry', observed_at: now - 30, age_seconds: 30, stale_after_s: 900, power_watts: 125.5, hashrate_hs: 1e12, temperature_c: 42 },
    solar: { state: 'not_configured', source: 'local_agent', observed_at: null, age_seconds: null, power_watts: null } };
}
function evaluated(body) {
  const d = snapshot(body.device_id);
  return { ...d, mode: 'read_only', currency: body.tariff.currency, hours: body.hours, tariff_state: 'current', tariff: body.tariff,
    expires_at: Math.min(d.telemetry.observed_at + 900, body.tariff.valid_until), baseline: { state: 'available', energy_kwh: '0.753000', cost: '0.225900', cost_below_resolution: false, energy_below_resolution: false },
    profiles: body.profiles.map(p => ({ ...p, eligible: p.approved, reasons: p.approved ? [] : ['not_operator_approved'], energy_kwh: '0.600000', cost: '0.180000', cost_below_resolution: false, energy_below_resolution: false })),
    suggestion: { type: 'review_candidates', profile_id: null, eligible_profile_ids: body.profiles.filter(p => p.approved).map(p => p.id) } };
}
async function fixtures(page) {
  await page.route('**/api/energy-advisor/devices', route => route.fulfill({ json: { devices: [device(), device('b')], truncated: false } }));
  await page.route('**/api/energy-advisor/snapshot?*', route => route.fulfill({ json: snapshot(new URL(route.request().url()).searchParams.get('device_id')) }));
  await page.route('**/api/energy-advisor/evaluate', route => route.fulfill({ json: evaluated(route.request().postDataJSON()) }));
}
async function inputs(page) {
  await page.locator('#energy-tariff').fill('0.3'); await page.locator('#energy-currency').selectOption('EUR');
  await page.locator('#energy-hours').fill('6'); await page.locator('#energy-validity').fill('60');
  await page.locator('#energy-max-power').fill('150'); await page.locator('#energy-max-cost').fill('1');
  await page.locator('.profile-name').first().fill('Perfil revisado de laboratório'); await page.locator('.profile-power').first().fill('100');
  await page.locator('.profile-approved').first().check();
}

test('source-tagged read-only comparison, keyboard, accessible mobile layout and contained motion', async ({ page }, info) => {
  const requests = []; page.on('request', request => { if (request.url().includes('/api/')) requests.push(request); });
  await fixtures(page); await page.goto('/energy-advisor'); await expect(page.locator('#energy-state')).toContainText('Evidência recente');
  await expect(page.locator('#energy-baseline')).toContainText('125,5 W'); await expect(page.locator('#energy-freshness')).toContainText('não é medição de tomada');
  await inputs(page); await page.locator('#energy-evaluate').focus(); await page.keyboard.press('Enter');
  await expect(page.locator('.scenario')).toHaveCount(2); await expect(page.locator('.scenario').last()).toContainText('Atende aos critérios informados');
  await expect(page.locator('#energy-result-state')).toContainText('Sem ranking'); await expect(page.locator('.scenario').last()).toContainText('0,18');
  expect(requests.every(r => r.url().includes('/api/energy-advisor/') && (r.method() === 'GET' || r.url().endsWith('/evaluate') && r.method() === 'POST'))).toBe(true);
  expect(requests.find(r => r.method() === 'POST').postDataJSON().profiles[0].approved).toBe(true);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  expect(await page.locator('.energy-header').evaluate(el => getComputedStyle(el).animationName)).toBe('none');
  await page.addScriptTag({ path: require.resolve('axe-core') });
  expect(await page.evaluate(async () => (await window.axe.run(document)).violations.map(v => ({ id: v.id, impact: v.impact })))).toEqual([]);
  await page.screenshot({ path: info.outputPath('energy-advisor.png'), fullPage: true });
  await page.locator('#energy-tariff').fill('0.4'); await expect(page.locator('.scenario')).toHaveCount(0);
});
test('same-device firmware change invalidates the prior explicit profile review', async ({ page }) => {
  let changed = false, body;
  await fixtures(page); await page.route('**/api/energy-advisor/snapshot?*', route => { const data = snapshot(); if (changed) data.device.firmware_version = '2.10'; return route.fulfill({ json: data }); });
  await page.route('**/api/energy-advisor/evaluate', route => { body = route.request().postDataJSON(); return route.fulfill({ json: evaluated(body) }); });
  await page.goto('/energy-advisor'); await expect(page.locator('#energy-evaluate')).toBeEnabled(); await inputs(page);
  changed = true; await page.locator('#energy-refresh').click(); await expect(page.locator('#energy-identity')).toContainText('2.10');
  await expect(page.locator('.profile-approved').first()).not.toBeChecked(); await page.locator('#energy-evaluate').click();
  await expect.poll(() => body?.profiles[0].approved).toBe(false); await expect(page.locator('.scenario').last()).toContainText('Revisão do operador pendente');
});
test('blocked storage is explicit and never turns into anonymous private requests', async ({ page }) => {
  let calls = 0; const errors = []; page.on('pageerror', error => errors.push(error.message));
  page.on('request', request => { if (request.url().includes('/api/energy-advisor/')) calls++; });
  await page.addInitScript(() => Object.defineProperty(window, 'localStorage', { configurable: true, get() { throw new DOMException('Blocked', 'SecurityError'); } }));
  await page.goto('/energy-advisor'); await expect(page.locator('#energy-state')).toContainText('Sessão necessária'); expect(calls).toBe(0); expect(errors).toEqual([]);
});
test('picker transient failure retries once, and metadata is rendered only as text', async ({ page }) => {
  let calls = 0; await fixtures(page);
  await page.route('**/api/energy-advisor/devices', route => ++calls === 1 ? route.fulfill({ status: 503, json: {} }) : route.fulfill({ json: { devices: [{ ...device(), name: '<img src=x onerror=alert(1)>' }], truncated: true } }));
  await page.goto('/energy-advisor'); await expect(page.locator('#energy-state')).toContainText('Evidência recente'); expect(calls).toBe(2);
  await expect(page.locator('#energy-source')).toContainText('100 primeiros'); expect(await page.locator('#energy-device img').count()).toBe(0);
});
test('old selection cannot render after delayed snapshot or edited computational POST', async ({ page }) => {
  let release, delayed = true; await fixtures(page);
  await page.route('**/api/energy-advisor/snapshot?*', async route => {
    if (delayed) { delayed = false; await new Promise(resolve => { release = resolve; }); }
    await route.fulfill({ json: snapshot(new URL(route.request().url()).searchParams.get('device_id')) }).catch(() => {});
  });
  await page.goto('/energy-advisor'); await expect.poll(() => typeof release).toBe('function');
  await page.selectOption('#energy-device', 'b'); release(); await expect(page.locator('#energy-evaluate')).toBeEnabled(); await inputs(page);
  let releasePost; await page.route('**/api/energy-advisor/evaluate', async route => { const body = route.request().postDataJSON(); await new Promise(resolve => { releasePost = resolve; }); await route.fulfill({ json: evaluated(body) }).catch(() => {}); });
  await page.locator('#energy-evaluate').click(); await expect.poll(() => typeof releasePost).toBe('function');
  await page.locator('#energy-tariff').fill('0.4'); releasePost(); await expect(page.locator('#energy-result-state')).toContainText('alteradas'); await expect(page.locator('.scenario')).toHaveCount(0);
});
test('stale telemetry blocks comparison, zero power remains zero, and expiry removes computed evidence', async ({ page }) => {
  await page.clock.install(); await fixtures(page); let stale = true;
  await page.route('**/api/energy-advisor/snapshot?*', route => {
    const d = snapshot(); if (stale) { d.telemetry.observed_at -= 1000; d.telemetry.age_seconds += 1000; d.telemetry.state = 'stale'; } else { d.telemetry.power_watts = 0; d.telemetry.hashrate_hs = 0; }
    return route.fulfill({ json: d });
  });
  await page.goto('/energy-advisor'); await expect(page.locator('#energy-state')).toContainText('antiga'); await expect(page.locator('#energy-evaluate')).toBeDisabled();
  stale = false; await page.locator('#energy-refresh').click(); await expect(page.locator('#energy-baseline')).toContainText('0 W'); await expect(page.locator('#energy-evaluate')).toBeEnabled();
  await inputs(page); await page.locator('#energy-evaluate').click(); await expect(page.locator('.scenario')).toHaveCount(2);
  await page.clock.fastForward(901000); await expect(page.locator('.scenario')).toHaveCount(0); await expect(page.locator('#energy-evaluate')).toBeDisabled();
});
test('session removal clears private evidence and invalidates approvals', async ({ page }) => {
  await fixtures(page); await page.goto('/energy-advisor'); await expect(page.locator('#energy-evaluate')).toBeEnabled(); await inputs(page);
  await page.locator('#energy-evaluate').click(); await expect(page.locator('.scenario')).toHaveCount(2);
  await page.route('**/api/energy-advisor/devices', route => route.fulfill({ status: 401, json: {} }));
  await page.evaluate(() => window.dispatchEvent(new StorageEvent('storage', { key: '_cypher65_auth_session', newValue: null })));
  await expect(page.locator('#energy-state')).toContainText('Sessão necessária'); await expect(page.locator('.scenario')).toHaveCount(0); await expect(page.locator('#energy-baseline')).toBeEmpty();
  await expect(page.locator('.profile-approved').first()).not.toBeChecked();
});
test('profile input edit invalidates its review and profile rows remain bounded', async ({ page }) => {
  await fixtures(page); await page.goto('/energy-advisor'); await expect(page.locator('#energy-evaluate')).toBeEnabled(); await inputs(page);
  await page.locator('.profile-power').first().fill('101'); await expect(page.locator('.profile-approved').first()).not.toBeChecked();
  await page.locator('#energy-add-profile').click(); await page.locator('#energy-add-profile').click(); await expect(page.locator('.profile-row')).toHaveCount(3); await expect(page.locator('#energy-add-profile')).toBeDisabled();
  await page.locator('.remove-profile').last().click(); await expect(page.locator('#energy-add-profile')).toBeEnabled();
});

test('unknown firmware prevents profile comparison without hiding the measured reference', async ({ page }) => {
  await fixtures(page); await page.route('**/api/energy-advisor/snapshot?*', route => { const d = snapshot(); d.device.firmware_version = ''; return route.fulfill({ json: d }); });
  await page.goto('/energy-advisor'); await expect(page.locator('#energy-state')).toContainText('Cadastro incompleto');
  await expect(page.locator('#energy-baseline')).toContainText('125,5 W'); await expect(page.locator('#energy-evaluate')).toBeDisabled();
});

test('adding a profile fences a delayed comparison and removes obsolete results', async ({ page }) => {
  let release; await fixtures(page);
  await page.route('**/api/energy-advisor/evaluate', async route => { const body = route.request().postDataJSON(); await new Promise(resolve => { release = resolve; }); await route.fulfill({ json: evaluated(body) }).catch(() => {}); });
  await page.goto('/energy-advisor'); await expect(page.locator('#energy-evaluate')).toBeEnabled(); await inputs(page);
  await page.locator('#energy-evaluate').click(); await expect.poll(() => typeof release).toBe('function');
  await page.locator('#energy-add-profile').click(); release();
  await expect(page.locator('#energy-result-state')).toContainText('alteradas'); await expect(page.locator('.scenario')).toHaveCount(0);
});

test('positive sub-resolution costs and tariffs never appear as free energy', async ({ page }) => {
  await fixtures(page); await page.route('**/api/energy-advisor/evaluate', route => {
    const data = evaluated(route.request().postDataJSON()); data.tariff.value = .00000001;
    data.baseline.cost = '0.000000'; data.baseline.cost_below_resolution = true;
    data.profiles[0].cost = '0.000001'; return route.fulfill({ json: data });
  });
  await page.goto('/energy-advisor'); await expect(page.locator('#energy-evaluate')).toBeEnabled(); await inputs(page); await page.locator('#energy-evaluate').click();
  await expect(page.locator('#energy-result-state')).toContainText('< 0,001 EUR/kWh');
  await expect(page.locator('.scenario').first().locator('.cost')).toContainText('<'); await expect(page.locator('.scenario').first().locator('.cost')).toContainText('0,000001');
  await expect(page.locator('.scenario').last().locator('.cost')).toContainText('<');
});

test.describe('no-JavaScript fallback', () => {
  test.use({ javaScriptEnabled: false });
  test('never displays seeded measurements or enabled commands', async ({ page }) => {
    await page.goto('/energy-advisor'); await expect(page.locator('noscript')).toBeVisible();
    // Playwright's text matcher deliberately omits NOSCRIPT nodes; verify the
    // visible fallback using its actual DOM text instead of that matcher.
    expect(await page.locator('noscript').textContent()).toContain('Nenhum valor de exemplo');
    await expect(page.locator('#energy-baseline')).toBeEmpty(); await expect(page.locator('#energy-evaluate')).toBeDisabled();
  });
});

test.describe('real service-worker privacy, without intercepted private responses', () => {
  test.use({ serviceWorkers: 'allow' });
  test('private cache admission and preseeded offline fallback are both denied', async ({ page, context }) => {
    await page.goto('/energy-advisor');
    await page.evaluate(async () => { await navigator.serviceWorker.register('/sw.js', { scope: '/' }); await navigator.serviceWorker.ready;
      if (!navigator.serviceWorker.controller) await new Promise(resolve => navigator.serviceWorker.addEventListener('controllerchange', resolve, { once: true })); });
    const outcomes = await page.evaluate(async () => {
      const cache = await caches.open('energy-test'), results = [];
      for (const path of ['/api/energy-advisor/devices', '/api/%65nergy-advisor/devices', '/api//energy-advisor/devices', '/%65nergy-advisor']) {
        const response = await fetch(path); let rejected = false; try { await cache.put(path, response.clone()); } catch (error) { rejected = error.name === 'TypeError'; }
        results.push({ status: response.status, rejected });
      }
      await caches.delete('energy-test'); return results;
    });
    expect(outcomes.every(r => r.status === 200 && r.rejected)).toBe(true);
    await page.evaluate(async () => (await caches.open('cypher65-v12')).put('/api/%65nergy-advisor/devices', new Response('PRIVATE-ENERGY-MARKER')));
    await context.setOffline(true);
    expect(await page.evaluate(async () => { try { return await (await fetch('/api/%65nergy-advisor/devices')).text(); } catch { return 'unavailable'; } })).toBe('unavailable');
  });
});
