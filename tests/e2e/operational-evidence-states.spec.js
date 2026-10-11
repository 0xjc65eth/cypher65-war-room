import { test, expect } from '@playwright/test';
import { clickToolbarAction } from './support/toolbar.js';
test.use({ serviceWorkers: 'block' });

const modules = ['dashboard', 'fleet', 'live', 'analysis', 'wallet', 'probability', 'market', 'rentals', 'alerts', 'automations', 'docs', 'learning', 'admin', 'support'];
const now = () => Math.floor(Date.now() / 1000);
const device = { id: 'fixture-A', name: 'Synthetic device A', model: 'fixture', status: 'ONLINE', capabilities: [], ip_address: '192.0.2.1' };

async function fixture(page) {
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.route('**/api/stream*', route => route.abort());
  await page.route('**/api/axe-fleet/summary', route => route.fulfill({ json: { devices: [{ ...device, _telemetry: { hashrate_hs: 0, temperature: 40 } }] } }));
  await page.route('**/api/axe-fleet/health*', route => route.fulfill({ json: {
    fleet_stats: { total_devices: 1 }, device_health: [{ ...device, telemetry: { ts: now(), hashrate_hs: 0, temperature: 40, power_watts: 0 } }],
  } }));
  await page.route('**/api/axe-fleet/devices/fixture-A', route => route.fulfill({ json: { device, latest_telemetry: { hashrate_hs: 0 } } }));
  await page.route('**/api/axe-fleet/devices/fixture-A/history*', route => route.fulfill({ json: {
    device_id: device.id, history: [{ ts: now() - 60, hashrate: 0, temperature: 40, efficiency_jth: 25 }],
  } }));
  await page.route('**/api/admin/**', route => route.fulfill({ json: {} }));
  await page.route('**/api/snapshot*', route => route.fulfill({ json: {
    ts: now(), btc_address: '', worker: null, all_workers: [], alerts_recent: [],
    network: { height: 969641, difficulty: 132.76e12, hashrate: 897e18 },
    pool: { hashrate: 323e15, workers: 4944, users: 2323 },
  } }));
  await page.goto('/');
  await expect(page.locator('#n-height')).toHaveText('#969641');
  return errors;
}

async function openModule(page, name) {
  const toggle = page.locator('#sidebar-mobile-toggle');
  if (await toggle.isVisible() && !(await page.locator('#sidebar').evaluate(element => element.classList.contains('open')))) await toggle.click();
  await page.locator('.sidebar__link[data-module="' + name + '"]').click();
  await expect(page.locator('body')).toHaveAttribute('data-active-module', name);
}

for (const theme of ['dark', 'light']) {
  for (const reducedMotion of ['reduce', 'no-preference']) {
    test('14 modules have real sections and source context: ' + theme + ', ' + reducedMotion, async ({ page }, info) => {
      await page.emulateMedia({ reducedMotion });
      const errors = await fixture(page);
      if (theme === 'light') await page.locator('#theme-toggle').click();
      for (const name of modules) {
        await openModule(page, name);
        await expect(page.locator('#module-source-context')).not.toBeEmpty();
        const links = page.locator('#module-section-nav a');
        await expect(links.first()).toBeVisible();
        const targets = await links.evaluateAll(elements => elements.map(element => element.getAttribute('href').slice(1)));
        for (const id of targets) {
          await expect(page.locator('[id="' + id + '"]')).toHaveCount(1);
          await expect(page.locator('[id="' + id + '"]')).toBeVisible();
          if (id === 'worker-details') {
            await page.locator('#module-section-nav a[href="#worker-details"]').click();
            await expect(page.locator('#worker-details')).toHaveAttribute('open', '');
            await expect(page.locator('#hero-worker')).toBeVisible();
          }
        }
        if (name === 'support') await page.locator('#support-panel .modal__close').click();
        await links.first().click();
        if (name === 'support') {
          await expect(page.locator('#support-panel')).toBeVisible();
          await expect.poll(() => page.evaluate(() => document.getElementById('support-panel').contains(document.activeElement))).toBe(true);
        } else {
          await expect(page.locator('[id="' + targets[0] + '"]')).toBeFocused();
        }
        const overflow = await page.evaluate(() => ({
          width: innerWidth, scrollWidth: document.documentElement.scrollWidth,
          elements: Array.from(document.querySelectorAll('body *')).filter(element => {
            const rect = element.getBoundingClientRect();
            return rect.width > 0 && rect.right > innerWidth + 1 && getComputedStyle(element).visibility !== 'hidden';
          }).slice(0, 18).map(element => ({ tag: element.tagName, id: element.id, className: element.className, width: element.getBoundingClientRect().width })),
        }));
        expect(overflow.scrollWidth <= overflow.width + 1, name + ': ' + JSON.stringify(overflow)).toBe(true);
        if (name === 'support') await page.locator('#support-panel .modal__close').click();
      }
      expect(errors).toEqual([]);
      await openModule(page, 'fleet');
      await expect(page.locator('#axe-fleet-status-badge')).toHaveText('UNKNOWN');
      await page.screenshot({ path: info.outputPath('fleet-source-sections.png'), fullPage: true });
    });
  }
}

test('single zero history point survives; HTTP failure clears the old chart', async ({ page }, info) => {
  const errors = await fixture(page);
  await openModule(page, 'fleet');
  await page.locator('#axe-grid .axe-card[data-device-id="fixture-A"]').click();
  await expect(page.locator('#axe-detail-chart-count')).toHaveText('1 point');
  const data = await page.evaluate(() => {
    const chart = window.Chart.getChart('axe-detail-chart');
    return { zero: chart.data.datasets[0].data[0], radius: chart.data.datasets[0].pointRadius, axes: chart.data.datasets.map(dataset => dataset.yAxisID), animation: chart.options.animation };
  });
  expect(data.zero).toBe(0);
  expect(data.radius).toBeGreaterThan(0);
  expect(data.axes[1]).not.toBe(data.axes[2]);
  await page.screenshot({ path: info.outputPath('device-single-zero.png'), fullPage: true });
  await page.route('**/api/axe-fleet/devices/fixture-A/history*', route => route.fulfill({ status: 503, json: { error: 'synthetic unavailable' } }));
  await page.locator('#axe-detail-close').click();
  await page.locator('#axe-grid .axe-card[data-device-id="fixture-A"]').click();
  await expect(page.locator('#axe-detail-chart-status')).toContainText('HTTP 503');
  await expect(page.locator('#axe-detail-chart')).toBeHidden();
  expect(await page.evaluate(() => !!window.Chart.getChart('axe-detail-chart'))).toBe(false);
  expect(errors).toEqual([]);
});

test('partial Admin source failure is explicit and a healthy empty response recovers', async ({ page }, info) => {
  const errors = await fixture(page);
  await page.route('**/api/admin/error-rate*', route => route.fulfill({ status: 503, json: { error: 'synthetic unavailable' } }));
  await openModule(page, 'admin');
  await expect(page.locator('#admin-gate-badge')).toHaveText('partial');
  await expect(page.locator('#admin-error')).toContainText('error-rate: HTTP 503');
  await expect(page.locator('#admin-err-total')).toHaveText('—');
  await expect(page.locator('#admin-error-rate-empty')).toContainText('Source unavailable');
  await page.screenshot({ path: info.outputPath('admin-partial.png'), fullPage: true });
  await page.route('**/api/admin/error-rate*', route => route.fulfill({ json: { total: 0, buckets: [], recent: [] } }));
  await page.locator('#admin-refresh-btn').click();
  await expect(page.locator('#admin-gate-badge')).toHaveText('ok');
  await expect(page.locator('#admin-error')).toBeHidden();
  await expect(page.locator('#admin-err-total')).toHaveText('0');
  await expect(page.locator('#admin-error-rate-empty')).not.toContainText('Source unavailable');
  expect(errors).toEqual([]);
});

test('Market and automation sources expose failure and recover without fabricated empty data', async ({ page }) => {
  const errors = await fixture(page);
  await page.route('**/api/market/trend', route => route.fulfill({ status: 503, json: {} }));
  await openModule(page, 'market');
  await expect(page.locator('#mkt-trend-count')).toHaveText('ERROR');
  await expect(page.locator('#mkt-trend-legend')).toContainText('HTTP 503');
  await page.route('**/api/market/trend', route => route.fulfill({ json: { providers: { synthetic: [{ ts: now(), price_btc_per_th_day: 0 }] } } }));
  await openModule(page, 'alerts'); await openModule(page, 'market');
  await expect(page.locator('#mkt-trend-chart')).toBeVisible();
  expect(await page.evaluate(() => window._mktTrendChart.data.datasets[0].data[0])).toBe(0);
  expect(await page.evaluate(() => window._mktTrendChart.data.datasets[0].pointRadius[0])).toBeGreaterThan(0);
  await page.route('**/api/auto-pilot/recommendations', route => route.fulfill({ status: 403, json: {} }));
  await page.route('**/api/auto-pilot/recommendations/audit*', route => route.fulfill({ json: { audit: [] } }));
  await page.route('**/api/automation/dry-run', route => route.fulfill({ status: 503, json: {} }));
  await page.route('**/api/automation/dry-run/replay*', route => route.fulfill({ status: 503, json: {} }));
  await openModule(page, 'automations');
  await page.locator('#ap-recs-refresh').click(); await page.locator('#ap-dr-refresh').click();
  await expect(page.locator('#ap-recs-list')).toContainText('Access required');
  await expect(page.locator('#ap-recs-badge')).toHaveText('—');
  await expect(page.locator('#ap-audit-list')).toContainText('No recommendation audit entries');
  await expect(page.locator('#ap-dr-replay-list')).toContainText('HTTP 503');
  await page.route('**/api/auto-pilot/recommendations', route => route.fulfill({ json: { recommendations: [] } }));
  await page.route('**/api/automation/dry-run', route => route.fulfill({ json: { actions: [] } }));
  await page.route('**/api/automation/dry-run/replay*', route => route.fulfill({ json: { per_rule: [], total_fires: 0 } }));
  await page.locator('#ap-recs-refresh').click(); await page.locator('#ap-dr-refresh').click();
  await expect(page.locator('#ap-recs-badge')).toHaveText('0');
  await expect(page.locator('#ap-dr-now-count')).toHaveText('0');
  await expect(page.locator('#ap-dr-replay-count')).toHaveText('0 disparos');
  expect(errors).toEqual([]);
});

test('Wallet and Support display source failure separately from configured empty', async ({ page }) => {
  const errors = await fixture(page);
  await page.route('**/api/wallet/history', route => route.fulfill({ status: 403, json: {} }));
  await clickToolbarAction(page, '#open-wallet');
  await expect(page.locator('#wallet-history-list')).toContainText('Access required');
  await page.locator('#wallet-modal .modal__close').click();
  await page.route('**/api/wallet/history', route => route.fulfill({ json: { success: true, history: [] } }));
  await clickToolbarAction(page, '#open-wallet');
  await expect(page.locator('#wallet-history-list')).toHaveText('No saved wallets');
  await page.locator('#wallet-modal .modal__close').click();
  await page.route('**/api/support-config', route => route.fulfill({ status: 503, json: {} }));
  await openModule(page, 'support');
  await expect(page.locator('#support-modal-grid')).toContainText('HTTP 503');
  await page.locator('#support-panel .modal__close').click();
  await page.route('**/api/support-config', route => route.fulfill({ json: { methods: [], manifesto: '' } }));
  await openModule(page, 'support');
  await expect(page.locator('#support-modal-grid')).toHaveText('No support methods configured');
  expect(errors).toEqual([]);
});

test('rapid navigation keeps section links owned by the final module', async ({ page }) => {
  const errors = await fixture(page);
  await page.evaluate(() => {
    document.querySelector('.sidebar__link[data-module="fleet"]').click();
    document.querySelector('.sidebar__link[data-module="analysis"]').click();
  });
  await expect(page.locator('body')).toHaveAttribute('data-active-module', 'analysis');
  await expect(page.locator('#module-section-nav a[href="#network-panel"]')).toBeVisible();
  expect(await page.locator('#module-section-nav a').evaluateAll(links => links.every(link => {
    const target = document.getElementById(link.getAttribute('href').slice(1));
    return target && (target.getAttribute('data-module') || '').split(/\s+/).includes('analysis');
  }))).toBe(true);
  expect(errors).toEqual([]);
});
