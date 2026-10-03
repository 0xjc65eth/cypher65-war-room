import { test, expect } from '@playwright/test';
test.use({ serviceWorkers: 'block' });

test('legacy comparison payloads remain unranked and uncomparable', async ({ page }, testInfo) => {
  await page.route('**/api/stream*', route => route.abort());
  await page.route('**/api/snapshot*', route => route.fulfill({json: {
    ts: Math.floor(Date.now() / 1000),
    worker: {hashrate: 82.2e12},
    all_workers: [],
    proximity: {live_calc: {ticker: [{instantaneous_hr_hps: 3.19e18}]}},
    profitability: {decision_matrix: {best_option: 'solo', recommendation: 'Only probabilistic data', rows: {solo: {expected_time_days: 200, p_year_pct: 20}}}},
  }}));
  await page.goto('/');
  await expect(page.locator('#hr-deviation-val')).toHaveText('—');
  await expect(page.locator('#hr-deviation-badge')).toHaveText('NOT COMPARABLE');
  await expect(page.locator('#hr-observed')).toHaveText('—');
  await expect(page.locator('#dm-best-badge')).toHaveText('INSUFFICIENT DATA');
  await expect(page.locator('#dm-reco')).toContainText('not a deadline');
  await expect(page.locator('#dm-solo-time')).toHaveText('200d');
  await page.screenshot({path: testInfo.outputPath('comparison.png'), fullPage: true});
});
