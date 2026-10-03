import { test, expect } from '@playwright/test';

// Keep fixture snapshots isolated: service-worker fetches bypass page.route.
test.use({ serviceWorkers: 'block' });

test('snapshot render preserves units, block semantics and topbar scope', async ({ page }, testInfo) => {
  await page.route('**/api/stream*', route => route.abort());
  await page.route('**/api/snapshot*', route => route.fulfill({ json: {
    ts: Math.floor(Date.now() / 1000),
    worker: { hashrate: 82e12, bestDifficulty: 85e9, lastSubmission: Date.now() / 1000 - 60 },
    all_workers: [{ name: 'one' }, { name: 'two' }],
    network: { height: 969641, difficulty: 132.76e12, hashrate: 897e18 },
    pool: { hashrate: 323e15, highestDiff: 63e12, lastBlockTime: 958527 },
    btc_price: { usd: 84537 },
    axe_fleet: [],
  } }));
  const response = await page.goto('/');
  expect(response.status()).toBe(200);
  await expect(page.locator('#n-height')).toHaveText('#969641');
  await page.screenshot({ path: testInfo.outputPath('dashboard.png'), fullPage: true });
  await expect(page.locator('#n-diff')).not.toContainText('H/s');
  await expect(page.locator('#hc-network')).toHaveText('#969641');
  await expect(page.locator('#p-last-block')).toContainText('958');
  await expect(page.locator('#p-last-block-time')).not.toContainText('ago');
  await expect(page.locator('#tbar-status')).toHaveText('ONLINE');
  await expect(page.locator('#tbar-best')).toContainText('85');
  await expect(page.locator('#tbar-workers')).toHaveText('2');
  await expect(page.locator('#tbar-btc')).toContainText('84');
  await expect(page.locator('.kpi-sub').filter({ hasText: '161.6' })).toHaveCount(0);
});
