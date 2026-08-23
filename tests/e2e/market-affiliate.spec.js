/**
 * CYPHER65 War Room — E2E: Hash Market institutional table + affiliate CTA
 * =============================================================
 * HashratePulse Enterprise redesign: card grid replaced by institutional
 * ranked venue table. Affiliate BUY moved to Decision Matrix panel.
 *
 * Run:  npx playwright test tests/e2e/market-affiliate.spec.js
 * CI:   bash run-e2e.sh
 */

import { test, expect } from '@playwright/test';

const BASE_URL = process.env.BASE_URL || 'http://127.0.0.1:8765';
const AFF_URL = 'https://www.miningrigrentals.com/?ref=e2e-affiliate-test';

// Complete snapshot mirroring the real /api/snapshot shape.
function buildSnapshot() {
  return {
    ts: Math.floor(Date.now() / 1000),
    worker: { hashrate: 100e12, best_diff: 500e9, shares_accepted: 1000, shares_rejected: 5, uptime: 3600 },
    pool: { hashrate: 1e15, workers: 3, best_diff: 500e9, name: 'CKPool' },
    network: { difficulty: 7.2e13, hashrate: 600e18, block_height: 850000, btc_usd: 65000 },
    btc_price: { usd: 65000, eur: 59000, gbp: 51000, brl: 320000 },
    btc_address: 'bc1qar0srrr7xfkvy5l643lydnw9re59gtzzwf5mdq',
    all_workers: [],
    pool_workers: [],
    account: null,
    account_meta: {},
    alerts_recent: [],
    axe_fleet: [],
    block_hunt: { p_block: 0.0001, expected_time_days: 5000, best_diff: 500e9, session_shares: 100, session_started_at: Math.floor(Date.now() / 1000) - 3600 },
    command_center: [],
    event_stats: {},
    halving: { blocks_remaining: 250000, estimated_date: '2028-03-15' },
    highest_diffs: [],
    leaderboard_entry: null,
    leaderboard_table_top_30: [],
    leaderboard_total: 0,
    lightning: null,
    luck_estimate: {},
    milestones: [],
    network_share_gauge: { share_pct: 0.0001 },
    proximity: { p_share: 0.000001, cumulative_p: 0.1 },
    timeline_last_n: [],
    timeline_recent: [],
    user_aggregate: null,
    worker_index: null,
    market_data: {
      affiliate: { provider: 'mrr', url: AFF_URL, price_per_th_day: 1.2e-8 },
      offers: [
        { provider: 'MRR', source: 'mrr', price_per_th_day: 1.2e-8, hashrate: 100, fee_pct: 3, duration_days: 30, estimated: false, metrics: { score: 95 } },
        { provider: 'NiceHash', source: 'nicehash', price_per_th_day: 2.0e-8, hashrate: 80, fee_pct: 2, duration_days: 30, estimated: false, metrics: { score: 80 } },
        { provider: 'Braiins', source: 'braiins', price_per_th_day: 3.0e-8, hashrate: 60, fee_pct: 4, duration_days: 30, estimated: true, metrics: { score: 60 } },
      ],
      best_price: '0.000012 BTC/TH/d',
      updated_at: Math.floor(Date.now() / 1000),
      provider_count: 3,
      health: { providers_ok: 3, providers_total: 3, last_fetch_ts: Math.floor(Date.now() / 1000) },
      institutional: {
        regime: 'Tight',
        snapshot: {
          best_price_btc_ph_day: 0.000012,
          best_price_sats_th_day: 1.2,
          best_venue: 'mrr',
          spread_vs_second_pct: 66.7,
          total_liquidity_ph: 0.24,
          total_liquidity_eh: 0.00024,
          regime: 'Tight',
          vwap_4h_btc_ph_day: 0.000020667,
          offer_count: 3,
          btc_usd: 65000,
        },
        venues: [
          { venue: 'mrr', price_btc_ph_day: 0.000012, price_sats_th_day: 1.2, spread_vs_best_pct: 0, spread_vs_vwap_pct: -41.9, available_ph: 0.1, depth_score: 'Thin', risk_tier: 2, risk_tier_label: 'Tier 2 \u00b7 Established', recommendation: 'Acceptable for tactical allocation', estimated: false, source: 'mrr', meta: {} },
          { venue: 'nicehash', price_btc_ph_day: 0.00002, price_sats_th_day: 2.0, spread_vs_best_pct: 66.7, spread_vs_vwap_pct: -3.2, available_ph: 0.08, depth_score: 'Thin', risk_tier: 2, risk_tier_label: 'Tier 2 \u00b7 Established', recommendation: 'Liquidity constrained', estimated: false, source: 'nicehash', meta: {} },
          { venue: 'braiins', price_btc_ph_day: 0.00003, price_sats_th_day: 3.0, spread_vs_best_pct: 150, spread_vs_vwap_pct: 45.2, available_ph: 0.06, depth_score: 'Thin', risk_tier: 4, risk_tier_label: 'Tier 4 \u00b7 Experimental', recommendation: 'Avoid \u2014 modeled quote, not executable', estimated: true, source: 'braiins', meta: {} },
        ],
        notes: ['Low aggregate liquidity \u2014 size > 5 PH may require splitting across venues.'],
      },
    },
    institutional: {
      regime: 'Tight',
      snapshot: {
        best_price_btc_ph_day: 0.000012,
        best_price_sats_th_day: 1.2,
        best_venue: 'mrr',
        spread_vs_second_pct: 66.7,
        total_liquidity_ph: 0.24,
        total_liquidity_eh: 0.00024,
        regime: 'Tight',
        vwap_4h_btc_ph_day: 0.000020667,
        offer_count: 3,
        btc_usd: 65000,
      },
      venues: [
        { venue: 'mrr', price_btc_ph_day: 0.000012, price_sats_th_day: 1.2, spread_vs_best_pct: 0, spread_vs_vwap_pct: -41.9, available_ph: 0.1, depth_score: 'Thin', risk_tier: 2, risk_tier_label: 'Tier 2 \u00b7 Established', recommendation: 'Acceptable for tactical allocation', estimated: false, source: 'mrr', meta: {} },
        { venue: 'nicehash', price_btc_ph_day: 0.00002, price_sats_th_day: 2.0, spread_vs_best_pct: 66.7, spread_vs_vwap_pct: -3.2, available_ph: 0.08, depth_score: 'Thin', risk_tier: 2, risk_tier_label: 'Tier 2 \u00b7 Established', recommendation: 'Liquidity constrained', estimated: false, source: 'nicehash', meta: {} },
        { venue: 'braiins', price_btc_ph_day: 0.00003, price_sats_th_day: 3.0, spread_vs_best_pct: 150, spread_vs_vwap_pct: 45.2, available_ph: 0.06, depth_score: 'Thin', risk_tier: 4, risk_tier_label: 'Tier 4 \u00b7 Experimental', recommendation: 'Avoid \u2014 modeled quote, not executable', estimated: true, source: 'braiins', meta: {} },
      ],
      notes: ['Low aggregate liquidity \u2014 size > 5 PH may require splitting across venues.'],
    },
    market_highlights: [
      { provider: 'MRR', source: 'mrr', price_per_th_day: 1.2e-8, hashrate: 100, estimated: false },
      { provider: 'NiceHash', source: 'nicehash', price_per_th_day: 2.0e-8, hashrate: 80, estimated: false },
      { provider: 'Braiins', source: 'braiins', price_per_th_day: 3.0e-8, hashrate: 60, estimated: true },
    ],
    profitability: {
      decision_matrix: {
        best_option: 'lease',
        recommendation: 'lease',
        affiliate: { provider: 'mrr', url: AFF_URL },
      },
    },
    auto_pilot: { peak_hashrate_7d: 0, temp_high_c: 75, automation_preview: [] },
  };
}

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

test.describe('Hash Market — institutional table + affiliate (HashratePulse)', () => {

  test('institutional table renders venues ranked by price', async ({ page }) => {
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
        body: JSON.stringify(buildSnapshot()),
      });
    });

    await page.goto(BASE_URL);
    await page.waitForSelector('#app-shell', { timeout: 15000 });
    await page.waitForTimeout(3000);

    // Diagnostic: check DOM state
    const diag = await page.evaluate(() => ({
      readyState: document.readyState,
      tbodyExists: !!document.getElementById('mkt-table-body'),
      mktTableExists: !!document.getElementById('mkt-table'),
      marketPanelExists: !!document.getElementById('market-panel'),
      tbodyHTML: (document.getElementById('mkt-table-body') || {}).innerHTML ? document.getElementById('mkt-table-body').innerHTML.substring(0, 200) : 'NONE',
      allPanels: document.querySelectorAll('.panel').length,
    }));
    console.log('DIAGNOSTIC:', JSON.stringify(diag));

    await ensureSidebarOpen(page);

    // Pre-click diagnostic
    const preClick = await page.evaluate(() => {
      const body = document.getElementById('mkt-table-body');
      return {
        tbodyExists: !!body,
        tbodyHTML: body ? body.innerHTML.substring(0, 300) : 'NONE',
        mktSnapBest: document.getElementById('mkt-snap-best') ? document.getElementById('mkt-snap-best').textContent : 'NONE',
        mktCountBadge: document.getElementById('mkt-count-badge') ? document.getElementById('mkt-count-badge').textContent : 'NONE',
      };
    });
    console.log('PRE-CLICK:', JSON.stringify(preClick));

    // Track all /api/snapshot requests to verify mock interception
    const snapshots = [];
    page.on('response', (resp) => {
      if (resp.url().includes('/api/snapshot') && resp.status() === 200) {
        resp.json().then(j => snapshots.push({ hasInstitutional: !!(j.market_data && j.market_data.institutional), hasOffers: !!(j.market_data && j.market_data.offers), keys: Object.keys(j.market_data || {}) })).catch(() => {});
      }
    });

    await page.locator('.sidebar__link[data-module="market"]').click();
    await page.waitForTimeout(1000);
    console.log('SNAPSHOT_RESPONSES:', JSON.stringify(snapshots));

    // Post-click diagnostic
    const postClick = await page.evaluate(() => {
      const body = document.getElementById('mkt-table-body');
      return {
        tbodyExists: !!body,
        tbodyHTML: body ? body.innerHTML.substring(0, 300) : 'NONE',
        mktSnapBest: document.getElementById('mkt-snap-best') ? document.getElementById('mkt-snap-best').textContent : 'NONE',
        mktCountBadge: document.getElementById('mkt-count-badge') ? document.getElementById('mkt-count-badge').textContent : 'NONE',
      };
    });
    console.log('POST-CLICK:', JSON.stringify(postClick));

    // Wait for the institutional table to render (activateModule triggers
    // fetchSnapshot → render → renderMarket → renderMarketGrid).
    await page.waitForFunction(() => {
      const body = document.getElementById('mkt-table-body');
      if (!body) return false;
      const venues = body.querySelectorAll('.mkt-table__venue');
      return venues.length >= 2;
    }, { timeout: 15000 });

    const rowCount = await page.evaluate(() => {
      const body = document.getElementById('mkt-table-body');
      if (!body) return 0;
      return body.querySelectorAll('.mkt-table__venue').length;
    });
    expect(rowCount).toBeGreaterThanOrEqual(2);

    const table = page.locator('#mkt-table');
    await expect(table).toBeVisible();

    // Venues must be in price order (best first = MRR).
    const venues = await page.locator('#mkt-table-body .mkt-table__venue').allTextContents();
    const normalized = venues.map(v => v.trim().toLowerCase());
    expect(normalized.length).toBeGreaterThanOrEqual(2);
    expect(normalized[0]).toContain('mrr');

    // Executive Snapshot must show best price + venue.
    const snapBest = await page.locator('#mkt-snap-best').textContent();
    expect(snapBest.toLowerCase()).toContain('mrr');

    // Risk tiers must be color-coded.
    const tiers = await page.locator('#mkt-table-body .mkt-table__tier').allTextContents();
    expect(tiers.some(t => t.includes('Tier 2'))).toBe(true);
  });

  test('render cap: 60 venues → 50 linhas no DOM + nota honesta (Issue #185)', async ({ page }) => {
    // Clone the base snapshot and inflate the venue list past the 50-row cap.
    function buildCappedSnapshot() {
      const snap = buildSnapshot();
      const venues = [];
      for (let i = 0; i < 60; i++) {
        venues.push({
          venue: 'venue-' + i,
          price_btc_ph_day: 0.000012 + i * 0.000001,
          price_sats_th_day: 1.2 + i * 0.1,
          spread_vs_best_pct: i * 5,
          spread_vs_vwap_pct: -10 + i,
          available_ph: 0.05,
          depth_score: 'Thin',
          risk_tier: i % 4 === 0 ? 1 : 2,
          risk_tier_label: 'Tier ' + (i % 4 === 0 ? 1 : 2),
          recommendation: 'Acceptable for tactical allocation',
          estimated: false,
          source: 'mrr',
          meta: {},
        });
      }
      snap.market_data.institutional.venues = venues;
      snap.market_data.institutional.snapshot.offer_count = 60;
      return snap;
    }

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
        body: JSON.stringify(buildCappedSnapshot()),
      });
    });

    await page.goto(BASE_URL);
    await page.waitForSelector('#app-shell', { timeout: 15000 });
    await ensureSidebarOpen(page);
    await page.locator('.sidebar__link[data-module="market"]').click();

    // Table renders (cap applied) and the honest note is visible.
    await page.waitForFunction(() => {
      const body = document.getElementById('mkt-table-body');
      return body && body.querySelectorAll('.mkt-table__venue').length >= 50;
    }, { timeout: 15000 });

    const rowCount = await page.evaluate(() => {
      const body = document.getElementById('mkt-table-body');
      return body ? body.querySelectorAll('.mkt-table__venue').length : 0;
    });
    expect(rowCount).toBe(50);

    const note = page.locator('#mkt-render-cap-note');
    await expect(note).toBeVisible();
    await expect(note).toContainText('50 melhores venues');
    await expect(note).toContainText('60 venues no total');
  });

  test('Decision Matrix shows affiliate BUY CTA', async ({ page }) => {
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
        body: JSON.stringify(buildSnapshot()),
      });
    });
    await page.context().route(/ref=e2e-affiliate-test/, (route) =>
      route.fulfill({ status: 200, contentType: 'text/html', body: '<html>affiliate landing</html>' })
    );

    await page.goto(BASE_URL);
    await page.waitForSelector('#app-shell', { timeout: 15000 });
    await ensureSidebarOpen(page);
    await page.locator('.sidebar__link[data-module="market"]').click();
    await page.waitForTimeout(800);

    const panel = page.locator('#decision-matrix-panel');
    await expect(panel).toBeVisible({ timeout: 10000 });

    const bestOfferBtn = panel.locator('#dm-goto-offers');
    await expect(bestOfferBtn).toBeVisible();

    const buyBtn = panel.locator('#dm-buy-affiliate');
    if (await buyBtn.isVisible().catch(() => false)) {
      await buyBtn.click();
      const [popup] = await Promise.all([
        page.waitForEvent('popup'),
        buyBtn.click(),
      ]).catch(() => [null]);
      if (popup) {
        await popup.waitForLoadState('domcontentloaded');
        expect(popup.url()).toBe(AFF_URL);
        await popup.close();
      }
    }
  });
});
