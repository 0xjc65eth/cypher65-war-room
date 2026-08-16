/**
 * CYPHER65 War Room — E2E: Conversion funnel + Admin CFO panel
 * =============================================================
 *
 * Prerequisites: Flask server running on BASE_URL (default http://127.0.0.1:8765)
 *
 * Run:  npx playwright test tests/e2e/conversion-admin.spec.js --project=chromium --workers=1
 *
 * Covers:
 *   - Upgrade modal opens and fires the modal_open funnel event
 *     (POST /api/conversion/track — public endpoint)
 *   - The Admin sidebar module renders (pool health KPIs + funnel section)
 *   - Admin endpoints respond (200 from localhost test client / gated 403
 *     behavior is covered by unit tests; here we assert the module renders)
 */

import { test, expect } from '@playwright/test';

const BASE_URL = process.env.BASE_URL || 'http://127.0.0.1:8765';

/** Wait for the app shell + topbar to be ready. */
async function waitForDashboard(page) {
  await page.waitForSelector('#app-shell', { timeout: 15000 });
  await page.waitForSelector('#open-wallet', { timeout: 10000 });
  await page.waitForFunction(() => {
    return document.querySelectorAll('.skel-overlay').length === 0;
  }, { timeout: 10000 }).catch(() => {});
  await page.waitForTimeout(800);
}

test('upgrade modal opens and fires funnel event', async ({ page }) => {
  // Listen for the conversion track POST before clicking anything.
  const fired = page.waitForResponse(
    (resp) => resp.url().includes('/api/conversion/track') &&
              resp.request().method() === 'POST' &&
              resp.request().postDataJSON()?.event === 'modal_open',
    { timeout: 10000 },
  );

  await page.goto(BASE_URL, { waitUntil: 'domcontentloaded' });
  await waitForDashboard(page);

  // Open the upgrade modal through the exposed JS API. The PRO badge's own
  // onclick is wired by the async initLicensing() and may not be ready yet;
  // window.openUpgradeModal is available as soon as app.js boots.
  await page.evaluate(() => {
    if (typeof window.openUpgradeModal === 'function') window.openUpgradeModal();
  });

  await expect(page.locator('#upgrade-modal')).toHaveClass(/modal--open/, { timeout: 5000 });
  await fired;  // modal_open fired to the funnel endpoint
});

test('admin module renders pool + funnel KPIs', async ({ page }) => {
  await page.goto(BASE_URL, { waitUntil: 'domcontentloaded' });
  await waitForDashboard(page);

  // Navigate to the Admin module via the sidebar link.
  const adminLink = page.locator('.sidebar__link[data-module="admin"]');
  await adminLink.click();
  await expect(page.locator('#admin-panel')).toBeVisible({ timeout: 5000 });

  // KPI cards exist and are populated (— before data, real values after).
  await expect(page.locator('#admin-sessions')).toBeVisible();
  await expect(page.locator('#admin-polls-per-sec')).toBeVisible();
  await expect(page.locator('#admin-funnel-list')).toBeVisible();

  // Refresh button exists and is wired (click must not throw).
  await page.locator('#admin-refresh-btn').click();
  await expect(page.locator('#admin-gate-badge')).toBeVisible();
});
