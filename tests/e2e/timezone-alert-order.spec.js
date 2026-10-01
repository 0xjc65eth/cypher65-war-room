/**
 * CYPHER65 War Room — timezone-independent rendered alert ordering.
 * The snapshot is intercepted locally so the test never depends on a pool,
 * miner, market provider, or machine timezone.
 */

import { test, expect } from '@playwright/test';

const BASE_URL = process.env.BASE_URL || 'http://127.0.0.1:8765';

const DST_CASES = [
  {
    timezoneId: 'America/Sao_Paulo',
    now: '2018-02-18T02:10:00Z',
    newer: '2018-02-18T02:01:00Z',
    older: '2018-02-18T01:59:00Z',
    newerLabel: 'Sao Paulo alert after fallback',
    olderLabel: 'Sao Paulo alert before fallback',
  },
  {
    timezoneId: 'Europe/Brussels',
    now: '2026-10-25T01:10:00Z',
    newer: '2026-10-25T01:01:00Z',
    older: '2026-10-25T00:59:00Z',
    newerLabel: 'Brussels alert after fallback',
    olderLabel: 'Brussels alert before fallback',
  },
];

function buildSnapshot(alerts) {
  return {
    ts: Math.floor(Date.now() / 1000),
    worker: {},
    pool: {},
    network: {},
    btc_price: {},
    btc_address: '',
    all_workers: [],
    pool_workers: [],
    account: null,
    account_meta: {},
    alerts_recent: alerts,
    axe_fleet: [],
    block_hunt: {},
    command_center: [],
    event_stats: {},
    halving: {},
    highest_diffs: [],
    leaderboard_entry: null,
    leaderboard_table_top_30: [],
    leaderboard_total: 0,
    lightning: null,
    luck_estimate: {},
    milestones: [],
    mempool_fees: {},
    market_data: {},
    network_share_gauge: {},
    proximity: {},
    profitability: {},
    timeline_last_n: [],
    timeline_recent: [],
    user_aggregate: null,
    worker_index: null,
  };
}

// test-requirement: TIME-001 status=partial
test('same-severity alerts preserve epoch order through DST fall-back in named zones', async ({ browser }) => {
  test.setTimeout(60000);

  for (const dstCase of DST_CASES) {
    const { timezoneId, now, newer, older, newerLabel, olderLabel } = dstCase;
    const alerts = [
      { severity: 'WARN', message: olderLabel, ts: Date.parse(older) / 1000 },
      { severity: 'WARN', message: newerLabel, ts: Date.parse(newer) / 1000 },
    ];
    const context = await browser.newContext({ timezoneId, serviceWorkers: 'block' });
    const page = await context.newPage();
    const appOrigin = new URL(BASE_URL).origin;

    await context.route('**/*', route => {
      const url = new URL(route.request().url());
      if (url.origin !== appOrigin) return route.abort();
      if (url.pathname === '/' || url.pathname.startsWith('/static/')) return route.continue();
      if (url.pathname === '/api/snapshot') return route.continue();
      return route.abort();
    });
    await page.route('**/api/stream*', route => route.abort());
    await page.route('**/api/snapshot*', async route => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(buildSnapshot(alerts)),
      });
    });

    try {
      await page.clock.install({ time: new Date(now) });
      await page.goto(BASE_URL);
      await page.waitForSelector('#app-shell', { timeout: 15000 });
      const renderedAlerts = page.locator('#alerts-list .alert-item .alert-msg');
      await expect(renderedAlerts).toHaveCount(2, { timeout: 20000 });
      await expect(renderedAlerts.nth(0)).toContainText(newerLabel);
      await expect(renderedAlerts.nth(1)).toContainText(olderLabel);
      const alertAges = page.locator('#alerts-list .alert-time');
      await expect(alertAges.nth(0)).toHaveText('9m ago');
      await expect(alertAges.nth(1)).toHaveText('11m ago');
    } finally {
      await context.close();
    }
  }

});
