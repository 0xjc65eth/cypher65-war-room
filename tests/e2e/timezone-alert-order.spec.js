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
    before: '2017-10-15T02:59:59Z',
    after: '2017-10-15T03:00:00Z',
  },
  {
    timezoneId: 'Europe/Brussels',
    before: '2026-03-29T00:59:59Z',
    after: '2026-03-29T01:00:00Z',
  },
];

// test-requirement: TIME-001 status=partial
test('same-severity alerts keep epoch order across DST in named browser zones', async ({ browser }) => {
  test.setTimeout(60000);

  for (const { timezoneId, before, after } of DST_CASES) {
    const context = await browser.newContext({ timezoneId, serviceWorkers: 'block' });
    const page = await context.newPage();
    const alerts = [
      { severity: 'WARN', message: 'newer alert after DST', ts: Date.parse(after) / 1000 },
      { severity: 'WARN', message: 'older alert before DST', ts: Date.parse(before) / 1000 },
    ];

    await page.route('**/api/snapshot*', async route => {
      const response = await route.fetch();
      const snapshot = await response.json();
      snapshot.alerts_recent = alerts;
      await route.fulfill({ response, body: JSON.stringify(snapshot) });
    });

    try {
      await page.goto(BASE_URL);
      await page.waitForSelector('#app-shell', { timeout: 15000 });
      const renderedAlerts = page.locator('#alerts-list .alert-item .alert-msg');
      await expect(renderedAlerts).toHaveCount(2, { timeout: 20000 });
      await expect(renderedAlerts.nth(0)).toContainText('newer alert after DST');
      await expect(renderedAlerts.nth(1)).toContainText('older alert before DST');
    } finally {
      await context.close();
    }
  }
});
