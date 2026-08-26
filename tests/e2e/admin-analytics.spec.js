/**
 * CYPHER65 War Room — E2E: protected beta analytics dashboard (Issue #361)
 *
 * This test exercises the real Flask endpoints and SQLite aggregation. It
 * deliberately does not route/mock the analytics response.
 */
import { test, expect } from '@playwright/test';

test.use({ serviceWorkers: 'block' });

async function ensureSidebarOpen(page) {
  const open = await page.locator('#sidebar').evaluate((el) => el.classList.contains('open'));
  if (!open && await page.locator('#sidebar-mobile-toggle').isVisible()) {
    await page.locator('#sidebar-mobile-toggle').click();
    await page.waitForTimeout(300);
  }
}

async function openAdmin(page) {
  await page.goto('/', { waitUntil: 'domcontentloaded' });
  await expect(page.locator('#app-shell')).toBeVisible({ timeout: 15000 });
  await ensureSidebarOpen(page);
  await page.locator('.sidebar__link[data-module="admin"]').click();
  await expect(page.locator('#admin-analytics')).toBeVisible();
}

test('renders real admin analytics with loading settled and no page overflow', async ({ page, request }) => {
  // Respect the production 1 event/s limiter while creating real report data.
  await request.post('/api/analytics/track', { data: { event: 'boot', meta: { vw: 'e2e' } } });
  await page.waitForTimeout(1100);
  await request.post('/api/analytics/track', { data: { event: 'module_switch', meta: { from: 'dashboard', to: 'admin-e2e' } } });
  await page.waitForTimeout(1100);
  await request.post('/api/analytics/track', { data: { event: 'module_time', meta: { module: 'admin-e2e', seconds: 75 } } });

  await openAdmin(page);

  const analytics = page.locator('#admin-analytics');
  await expect(analytics).toBeVisible();
  await expect(analytics).toHaveAttribute('aria-busy', 'false', { timeout: 15000 });
  await expect(page.locator('[data-analytics-skeleton]:visible')).toHaveCount(0);
  await expect(page.locator('#admin-analytics-state')).toContainText('eventos reais');
  await expect(page.locator('#admin-analytics-boots')).not.toHaveText('—');
  await expect(page.locator('#admin-analytics-top-module')).toContainText('admin-e2e');
  await expect(page.locator('#admin-analytics-modules-chart')).toBeVisible();
  await expect(page.locator('#admin-analytics-boots-chart')).toBeVisible();
  await expect(page.locator('#admin-analytics-dropoff-chart')).toBeVisible();
  await expect(page.locator('#admin-analytics-table-body')).toContainText('admin-e2e');

  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow).toBeLessThanOrEqual(1);
});

test('shows explicit empty states without placeholder metrics', async ({ page }) => {
  await page.route('**/api/admin/analytics**', (route) => route.fulfill({
    json: {
      days: 30, total_events: 0, boot_count: 0, dau: [], wau: [],
      boots_by_day: [], module_usage: {}, module_time: {},
      dropoff: { boot_total: 0, boot_without_switch: 0, rate: 0 },
    },
  }));

  await openAdmin(page);
  await expect(page.locator('#admin-analytics')).toHaveAttribute('aria-busy', 'false');
  await expect(page.locator('#admin-analytics-state')).toContainText('Sem eventos reais');
  await expect(page.locator('[data-analytics-empty]:visible')).toHaveCount(3);
  await expect(page.locator('#admin-analytics-table-wrap')).toBeHidden();
});

test('settles skeletons and surfaces an analytics API failure', async ({ page }) => {
  await page.route('**/api/admin/analytics**', (route) => route.fulfill({
    status: 503,
    json: { error: 'temporarily unavailable' },
  }));

  await openAdmin(page);
  await expect(page.locator('#admin-analytics')).toHaveAttribute('aria-busy', 'false');
  await expect(page.locator('[data-analytics-skeleton]:visible')).toHaveCount(0);
  await expect(page.locator('#admin-analytics-state')).toContainText('analytics request failed (503)');
  await expect(page.locator('#admin-analytics-state')).toHaveClass(/admin-analytics__state--error/);
});
