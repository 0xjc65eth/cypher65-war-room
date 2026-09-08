// @ts-check
// Issue #424 — top-level Rentals fetch errors must never remain as "Loading".
import { test, expect } from '@playwright/test';

test.use({ serviceWorkers: 'block' });

async function openRentals(page) {
  await page.goto('/');
  await page.waitForSelector('#app-shell', { timeout: 25000 });
  const sidebarOpen = await page.evaluate(() => {
    const sidebar = document.getElementById('sidebar');
    return Boolean(sidebar && sidebar.classList.contains('open'));
  });
  if (!sidebarOpen) {
    const toggle = page.locator('#sidebar-mobile-toggle');
    if (await toggle.isVisible()) {
      await toggle.click();
      await page.waitForTimeout(400);
    }
  }
  await page.click('.sidebar__link[data-module="rentals"]');
}

test.describe('Rentals — unavailable and retry states', () => {
  test('HTTP error is explicit and retry recovers with real empty payload', async ({ page }) => {
    let requests = 0;
    const urls = [];
    await page.route(/\/api\/rentals(\?|$)/, async (route) => {
      requests += 1;
      urls.push(route.request().url());
      if (requests === 1) {
        await route.fulfill({ status: 503, json: { error: 'provider unavailable' } });
        return;
      }
      await new Promise((resolve) => setTimeout(resolve, 300));
      await route.fulfill({
        json: {
          success: true,
          updated_at: Math.floor(Date.now() / 1000),
          rentals_payload_version: 2,
          mrr: {
            needs_auth: false,
            active: [],
            history: [],
            owner: [],
            total_active: 0,
            total_history: 0,
            total_owner: 0,
            error: null,
          },
          braiins: { needs_auth: false, contracts: [], error: null },
        },
      });
    });

    await openRentals(page);

    await expect(page.locator('#rentals-list .empty-state__title')).toHaveText(
      'Rentals indisponível',
      { timeout: 10000 },
    );
    await expect(page.locator('#rentals-list .empty-state__desc')).toContainText('HTTP 503');
    await expect(page.locator('#rentals-count-badge')).toHaveText('erro');
    await expect(page.locator('#rentals-load-retry')).toBeVisible();

    await page.click('#rentals-load-retry');
    await expect(page.locator('#rentals-load-retry')).toBeDisabled();
    await expect(page.locator('#rentals-load-retry')).toHaveAttribute('aria-busy', 'true');
    await expect(page.locator('#rentals-load-retry')).toHaveText('CARREGANDO…');
    await expect(page.locator('#rentals-count-badge')).toHaveText('0 rentals', {
      timeout: 10000,
    });
    await expect(page.locator('#rentals-load-retry')).toHaveCount(0);
    expect(requests).toBe(2);
    expect(urls[1]).toContain('refresh=1');
  });
});
