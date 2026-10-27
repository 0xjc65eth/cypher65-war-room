import { test, expect } from '@playwright/test';

// Synthetic browser contracts exercise the real generated application bundle.
// No device, provider, credential, physical command or background collector is used.
test.use({ serviceWorkers: 'block' });

function device(status, overrides = {}) {
  return { id: 'synthetic-' + status, name: 'Synthetic ' + status, status, capabilities: [],
    latency_ms: 20, _telemetry: { hashrate_hs: 1e12, temperature: 60, power_watts: 100,
      efficiency_jth: 25, shares_accepted: 9, shares_rejected: 1, shares_stale: 2 }, ...overrides };
}

async function openFleetKpis(page, devices) {
  const errors = [], mutations = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.route('**/api/**', async route => {
    const request = route.request(), path = new URL(request.url()).pathname;
    // Existing navigation analytics is fulfilled locally, never sent to a real
    // sink. Any other mutation remains blocked and fails the no-command check.
    if (request.method() === 'POST' && path === '/api/analytics/track') return route.fulfill({ json: { success: true } });
    if (request.method() !== 'GET') { mutations.push(request.method() + ' ' + path); return route.abort(); }
    if (path === '/api/stream') return route.abort();
    if (path === '/api/axe-fleet/summary') return route.fulfill({ json: { devices } });
    if (path === '/api/axe-fleet/health') return route.fulfill({ json: {
      fleet_stats: { total_devices: 0, online: 0, warning: 0, offline: 0 }, device_health: [],
    } });
    if (path === '/api/snapshot') return route.fulfill({ json: {
      ts: Math.floor(Date.now() / 1000), btc_address: '', worker: null, all_workers: [], alerts_recent: [],
      network: { height: 969641, difficulty: 132.76e12, hashrate: 897e18 },
      pool: { hashrate: 323e15, workers: 4944, users: 2323 },
    } });
    return route.fulfill({ json: {} });
  });
  await page.goto('/');
  await expect(page.locator('#n-height')).toHaveText('#969641');
  const toggle = page.locator('#sidebar-mobile-toggle');
  if (await toggle.isVisible()) await toggle.click();
  await page.locator('.sidebar__link[data-module="live"]').click();
  await expect(page.locator('body')).toHaveAttribute('data-active-module', 'live');
  return { errors, mutations };
}

for (const status of ['ONLINE', 'HASHING', 'WARNING']) {
  test('reachable ' + status + ' contributes without relabeling warning as healthy', async ({ page }) => {
    const result = await openFleetKpis(page, [device(status)]);
    await expect(page.locator('#fcc-summary-temp')).toHaveText('60.0°C');
    await expect(page.locator('#fcc-summary-power')).toHaveText('0.10 kW');
    await expect(page.locator('#fcc-summary-eff')).toHaveText('25.0 J/TH');
    await expect(page.locator('#fcc-summary-ping')).toHaveText('20ms');
    await expect(page.locator('#fcc-summary-online')).toHaveText(status === 'WARNING' ? '0' : '1');
    await expect(page.locator('#fcc-summary-warn')).toHaveText(status === 'WARNING' ? '1' : '0');
    await expect(page.locator('#fcc-summary-offline')).toHaveText('0');
    expect(result.errors).toEqual([]); expect(result.mutations).toEqual([]);
  });
}

test('measured zero remains visible for reachable metrics and rounded latency', async ({ page }, info) => {
  const result = await openFleetKpis(page, [device('HASHING', { latency_ms: 0,
    _telemetry: { hashrate_hs: 0, temperature: 0, power_watts: 0, efficiency_jth: 0 },
  })]);
  await expect(page.locator('#fcc-summary-hr')).toHaveText('0.00 H/s');
  await expect(page.locator('#fcc-summary-power')).toHaveText('0.00 kW');
  await expect(page.locator('#fcc-summary-temp')).toHaveText('0.0°C');
  await expect(page.locator('#fcc-summary-eff')).toHaveText('0.0 J/TH');
  await expect(page.locator('#fcc-summary-ping')).toHaveText('0ms');
  await page.screenshot({ path: info.outputPath('measured-zero-kpis.png'), fullPage: true });
  expect(result.errors).toEqual([]); expect(result.mutations).toEqual([]);
});

test('unreachable and unknown observations do not become live thermal or power', async ({ page }) => {
  const devices = ['STALE', 'OFFLINE', 'PAUSED', 'UNKNOWN', 'IDLE'].map(status => device(status, {
    _telemetry: { hashrate_hs: 0, last_known_hashrate_hs: 9e15, power_watts: 999,
      temperature: 99, efficiency_jth: 99, shares_accepted: 999, shares_rejected: 999 },
  }));
  const result = await openFleetKpis(page, devices);
  await expect(page.locator('#fcc-summary-offline')).toHaveText('5');
  await expect(page.locator('#fcc-summary-hr')).toHaveText('0.00 H/s');
  for (const id of ['temp', 'power', 'eff', 'ping']) await expect(page.locator('#fcc-summary-' + id)).toHaveText('—');
  expect(result.errors).toEqual([]); expect(result.mutations).toEqual([]);
});
