// Issue #843: synthetic contracts only, no provider account or purchase calls.
import { test, expect } from '@playwright/test';

test.use({ serviceWorkers: 'block', contextOptions: { reducedMotion: 'reduce' } });

for (const scenario of [
  { name: 'BTC verified', currency: 'BTC', unit: 'th', algorithm: 'sha256', paid: '10000 sats', priced: true },
  { name: 'LTC preserved', currency: 'LTC', unit: 'th', algorithm: 'sha256', paid: '0,0001 LTC' },
  { name: 'currency missing', currency: null, unit: 'th', algorithm: 'sha256', paid: '—' },
  { name: 'unit unknown', currency: 'BTC', unit: 'unverified', algorithm: 'sha256', paid: '10000 sats' },
  { name: 'algorithm unverified', currency: 'BTC', unit: 'th', algorithm: 'scrypt', paid: '10000 sats' },
  { name: 'currency literal HTML', currency: '<SVG DATA-PROVIDER-CURRENCY>', unit: 'th', algorithm: 'sha256', paid: '0,0001 <SVG DATA-PROVIDER-CURRENCY>' },
]) {
  test(scenario.name + ' never fabricates BTC model economics', async ({ page }) => {
    const mutationRequests = [];
    await page.route('**/api/**', route => {
      if (!['GET', 'HEAD'].includes(route.request().method())) mutationRequests.push(route.request().url());
      return route.fulfill({ json: {} });
    });
    await page.route('**/api/rentals', route => route.fulfill({ json: {
      success: true, rentals_payload_version: 2, updated_at: Date.now() / 1000,
      mrr: { needs_auth: false, active: [{
        id: '843', ended: false, price_currency: scenario.currency,
        price_paid_amount: 0.0001, price_paid_btc: scenario.currency === 'BTC' ? 0.0001 : null,
        hashrate_advertised_th: 100, hashrate_average_th: 90, hashrate_percent: 90,
        rig: { id: 'fixture843', name: 'Fixture 843', type: scenario.algorithm },
      }], history: [], owner: [], total_active: 1, total_history: 0, total_owner: 0 },
      braiins: { needs_auth: false, contracts: [] },
    } }));
    await page.route('**/api/rentals/detail*', route => route.fulfill({ json: {
      success: true, provider: 'mrr', detail: {
        id: '843', price: { paid: '0.0001', currency: scenario.currency },
        length: 2, rig: { type: scenario.algorithm },
        hashrate: { advertised: { hash: 100, type: scenario.unit },
          average: { hash: 90, type: scenario.unit, percent: 90 } },
      },
      // Contradictory legacy/cache economics must not override raw denomination.
      perf: { avg_th: 90, delivered_thh: 180, percent: 90, cost_sats_per_thh: 55.56 },
      pl: { available: true, pl_sats: 123, expected_yield_sats_per_thh: 10 },
      market: { available: true, price_sats_per_thh: 10 },
    } }));
    await page.goto('/');
    await page.waitForSelector('#sidebar', { timeout: 25000 });
    await page.locator('.sidebar__link[data-module="rentals"]').evaluate(el => el.click());
    await expect(page.locator('#rentals-list [data-provider-currency]')).toHaveCount(0);
    await page.locator('#rentals-list .rentals-item[data-rental-id="843"]').click();
    await expect(page.locator('#rentals-detail')).toBeVisible();
    const paidRow = page.locator('#rentals-detail-grid .rentals-detail__row').filter({ hasText: 'Pago' });
    await expect(paidRow.locator('strong')).toHaveText(scenario.paid);
    const cells = page.locator('#rentals-detail-perf .rentals-perf__cell');
    await expect(cells).toHaveCount(7);
    if (scenario.priced) {
      await expect(cells.nth(2)).toContainText('55.56 sats/TH/h');
    } else {
      await expect(cells.nth(2).locator('strong')).toHaveText('—');
      await expect(cells.nth(5).locator('strong')).toHaveText('—');
      await expect(cells.nth(6).locator('strong')).toHaveText('—');
    }
    expect(mutationRequests.filter(url => /bid|purchase|command|payout/.test(url))).toEqual([]);
  });
}
