/**
 * CYPHER65 War Room — E2E: Hash Market one-click affiliate BUY
 * =============================================================
 * P0-4: the same market_data.affiliate payload that powers the Decision
 * Matrix CTA now also renders a ⚡ BUY button on the matching offer card in
 * the market grid. Clicking it must open the operator-configured affiliate
 * URL in a NEW TAB.
 *
 * Determinism strategy (learned from dashboard.spec.js): the app registers a
 * Service Worker whose network-first fetch is NOT intercepted by page.route,
 * and it subscribes to the live /api/stream SSE. We neutralize BOTH via
 * page.addInitScript (no-op SW register + no-op EventSource) so the only
 * snapshot path is plain fetch('/api/snapshot'), which page.route CAN mock.
 *
 * Run:  npx playwright test tests/e2e/market-affiliate.spec.js
 * CI:   bash run-e2e.sh
 */

import { test, expect } from '@playwright/test';

const BASE_URL = process.env.BASE_URL || 'http://127.0.0.1:8765';
const AFF_URL = 'https://www.miningrigrentals.com/?ref=e2e-affiliate-test';

// Crafted snapshot: MRR is both the cheapest offer AND the configured
// affiliate provider → the BUY button must land on the best offer card.
const SNAPSHOT = {
  worker: { hashrate: 100e12 },
  pool: { hashrate: 1e15, workers: 3 },
  network: { difficulty: 7.2e13 },
  btc_price: { usd: 65000 },
  all_workers: [],
  market_data: {
    affiliate: { provider: 'mrr', url: AFF_URL, price_per_th_day: 1.2e-8 },
    offers: [
      { provider: 'MRR', source: 'mrr', price_per_th_day: 1.2e-8, hashrate: 100, fee_pct: 3, duration_days: 30, estimated: false, metrics: { score: 95 } },
      { provider: 'NiceHash', source: 'nicehash', price_per_th_day: 2.0e-8, hashrate: 80, fee_pct: 2, duration_days: 30, estimated: false, metrics: { score: 80 } },
      { provider: 'Braiins', source: 'braiins', price_per_th_day: 3.0e-8, hashrate: 60, fee_pct: 4, duration_days: 30, estimated: true, metrics: { score: 60 } },
    ],
  },
  profitability: {
    decision_matrix: {
      best_option: 'lease',
      recommendation: 'lease',
      affiliate: { provider: 'mrr', url: AFF_URL },
    },
  },
};

/** Ensure the sidebar is open so the market link is clickable (mobile off-canvas) */
async function ensureSidebarOpen(page) {
  const isOpen = await page.evaluate(() => {
    const sb = document.getElementById('sidebar');
    return sb && sb.classList.contains('open');
  });
  if (!isOpen) {
    const toggle = page.locator('#sidebar-mobile-toggle');
    if (await toggle.isVisible()) {
      await toggle.click();
      await page.waitForTimeout(400);
    }
  }
}

test.describe('Hash Market — affiliate BUY (P0-4)', () => {

  test('best offer card shows ⚡ BUY and opens the affiliate URL in a new tab', async ({ page }) => {
    // Neutralize Service Worker (network-first fetch bypasses page.route)
    // and EventSource (live SSE would overwrite the mocked snapshot).
    await page.addInitScript(() => {
      if ('serviceWorker' in navigator) {
        Object.defineProperty(navigator, 'serviceWorker', {
          value: {
            register: () => Promise.resolve(),
            getRegistrations: () => Promise.resolve([]),
            addEventListener: () => {},
          },
          configurable: true,
        });
      }
      window.EventSource = class {
        constructor() {}
        close() {}
        addEventListener() {}
      };
    });

    await page.route('**/api/snapshot', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(SNAPSHOT),
      });
    });
    // Hermetic: stub the affiliate landing page at the CONTEXT level so the
    // popup (a separate page opened via window.open) is intercepted too —
    // page-scoped routes do not reliably cover popup requests.
    await page.context().route(/ref=e2e-affiliate-test/, (route) =>
      route.fulfill({ status: 200, contentType: 'text/html', body: '<html>affiliate landing</html>' })
    );

    await page.goto(BASE_URL);
    await page.waitForSelector('#app-shell', { timeout: 15000 });
    await ensureSidebarOpen(page);
    await page.locator('.sidebar__link[data-module="market"]').click();
    await page.waitForTimeout(800);

    const grid = page.locator('#mkt-grid');
    await expect(grid).toBeVisible({ timeout: 10000 });

    // The affiliate BUY button must sit on the BEST offer card (the card
    // whose provider matches market_data.affiliate.provider — MRR is both
    // cheapest and highest-scored in the crafted snapshot).
    const buyBtn = page.locator('.mkt-card__buy');
    await expect(buyBtn).toHaveCount(1, { timeout: 10000 });
    await expect(buyBtn).toContainText('BUY MRR');
    await expect(buyBtn).toHaveAttribute('data-aff-url', AFF_URL);
    await expect(buyBtn.locator('xpath=ancestor::*[contains(@class, "mkt-card--best")]')).toHaveCount(1);

    // Click → a NEW TAB must open with the affiliate URL.
    const [popup] = await Promise.all([
      page.waitForEvent('popup'),
      buyBtn.click(),
    ]);
    await popup.waitForLoadState('domcontentloaded');
    expect(popup.url()).toBe(AFF_URL);
    await popup.close();
  });

  test('card of a NON-configured provider never gets a BUY button', async ({ page }) => {
    await page.addInitScript(() => {
      if ('serviceWorker' in navigator) {
        Object.defineProperty(navigator, 'serviceWorker', {
          value: {
            register: () => Promise.resolve(),
            getRegistrations: () => Promise.resolve([]),
            addEventListener: () => {},
          },
          configurable: true,
        });
      }
      window.EventSource = class {
        constructor() {}
        close() {}
        addEventListener() {}
      };
    });

    // Affiliate provider is mrr → NiceHash/Braiins cards must stay clean.
    await page.route('**/api/snapshot', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(SNAPSHOT),
      });
    });
    await page.goto(BASE_URL);
    await page.waitForSelector('#app-shell', { timeout: 15000 });
    await ensureSidebarOpen(page);
    await page.locator('.sidebar__link[data-module="market"]').click();
    await page.waitForTimeout(800);

    const cards = page.locator('#mkt-grid .mkt-card');
    await expect(cards).toHaveCount(3, { timeout: 10000 });
    const cardBtns = await cards.evaluateAll((els) =>
      els.map((el) => ({
        provider: (el.querySelector('.mkt-card__provider') || {}).textContent || '',
        hasBuy: !!el.querySelector('.mkt-card__buy'),
      }))
    );
    const mrr = cardBtns.find((c) => c.provider.trim().toLowerCase() === 'mrr');
    const others = cardBtns.filter((c) => c.provider.trim().toLowerCase() !== 'mrr');
    expect(mrr && mrr.hasBuy).toBe(true);
    others.forEach((c) => expect(c.hasBuy).toBe(false));
  });
});
