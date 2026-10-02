// @ts-check
// Issue #722: activate the real Rentals UI with synthetic data before
// measuring toolbar/document bounds. No vendor account or wallet is used.
import { test, expect } from '@playwright/test';

const CONTROLS = [
  ['rentals-buy', 'Comprar hashrate'],
  ['rentals-backtest', 'Abrir backtest de aluguel'],
  ['rentals-export', 'Exportar CSV de aluguéis'],
  ['rentals-export-analysis', 'Exportar análise de rendimento'],
  ['rentals-refresh', 'Atualizar aluguéis'],
];

/**
 * Keep the rendered rental and export responses deterministic.
 * @param {import('@playwright/test').Page} page
 * @example await mockRentals(page);
 */
async function mockRentals(page) {
  await page.route('**/api/rentals', route => route.fulfill({ json: {
    success: true, rentals_payload_version: 2, updated_at: Date.now() / 1000,
    mrr: { needs_auth: false, active: [{
      id: '101', ended: false, hashrate_average_th: 100,
      hashrate_advertised_th: 100, hashrate_percent: 100,
      price_paid_btc: 0.0001, length_hours: 1,
      rig: { id: 'fixture-rig', name: 'Synthetic rig', status: 'running' },
    }], history: [], owner: [], total_active: 1, total_history: 0,
    total_owner: 0, error: null },
    braiins: { needs_auth: false, contracts: [], error: null },
  } }));
  await page.route('**/api/rentals/export*', route => route.fulfill({
    contentType: 'text/csv',
    body: 'provider,id\nmrr,101\n',
  }));
}

/**
 * Activate Rentals through the actual sidebar, including the mobile drawer.
 * @param {import('@playwright/test').Page} page
 * @example await activateRentals(page);
 */
async function activateRentals(page) {
  await page.goto('/');
  const toggle = page.locator('#sidebar-mobile-toggle');
  if (await toggle.isVisible() && !(await page.locator('#sidebar').evaluate(el => el.classList.contains('open')))) {
    await toggle.click();
  }
  await page.locator('.sidebar__link[data-module="rentals"]').click();
  await expect(page.locator('#rentals-list .rentals-item[data-rental-id="101"]')).toBeVisible();
  await expect(page.locator('#rentals-count-badge')).toHaveText('1 rentals');
  await expect(page.locator('#rentals-panel .skel-overlay')).toHaveCount(0);
}

for (const viewport of [
  { name: 'mobile 375px', width: 375, height: 812 },
  { name: 'desktop 1440px', width: 1440, height: 900 },
]) {
  test.describe(`Rentals toolbar — ${viewport.name}`, () => {
    // Explicit viewports also exercise mobile in the chromium-only CI job.
    test.use({ viewport: { width: viewport.width, height: viewport.height },
      serviceWorkers: 'block', contextOptions: { reducedMotion: 'reduce' } });

    test.beforeEach(async ({ page }) => {
      await mockRentals(page);
      await activateRentals(page);
    });

    test('activated toolbar and every control stay within the viewport', async ({ page }, testInfo) => {
      const metrics = await page.evaluate(() => {
        const root = document.documentElement;
        const header = document.querySelector('#rentals-panel > .panel__header');
        const toolbar = header.querySelector('.panel__tools');
        const bounds = el => {
          const rect = el.getBoundingClientRect();
          return { id: el.id, left: rect.left, right: rect.right,
            top: rect.top, width: rect.width, height: rect.height };
        };
        return { documentWidth: root.scrollWidth, viewportWidth: root.clientWidth,
          header: bounds(header), toolbar: bounds(toolbar),
          controls: Array.from(toolbar.children).map(bounds),
          reducedMotion: matchMedia('(prefers-reduced-motion: reduce)').matches,
          animation: getComputedStyle(toolbar).animationName,
        };
      });
      await testInfo.attach('toolbar-bounds', {
        body: JSON.stringify(metrics, null, 2), contentType: 'application/json',
      });
      expect(metrics.documentWidth).toBeLessThanOrEqual(metrics.viewportWidth);
      expect(metrics.toolbar.left).toBeGreaterThanOrEqual(metrics.header.left);
      expect(metrics.toolbar.right).toBeLessThanOrEqual(metrics.header.right + 1);
      for (const control of metrics.controls) {
        expect(control.left, `${control.id}: left edge`).toBeGreaterThanOrEqual(0);
        expect(control.right, `${control.id}: right edge`).toBeLessThanOrEqual(metrics.viewportWidth);
        if (viewport.width === 375 && control.id !== 'rentals-count-badge') {
          expect(control.width, `${control.id}: touch width`).toBeGreaterThanOrEqual(44);
          expect(control.height, `${control.id}: touch height`).toBeGreaterThanOrEqual(44);
        }
      }
      if (viewport.width === 1440) {
        expect(new Set(metrics.controls.map(control => Math.round(control.top))).size).toBe(1);
      }
      expect(metrics.reducedMotion).toBe(true);
      expect(metrics.animation).toBe('none');
      for (const [id, label] of CONTROLS) {
        await expect(page.locator(`#${id}`)).toBeVisible();
        await expect(page.locator(`#${id}`)).toHaveAccessibleName(label);
      }
      await testInfo.attach('activated-rentals', {
        body: await page.locator('#rentals-panel').screenshot(), contentType: 'image/png',
      });
    });

    test('keyboard order retains both CSV downloads and refresh', async ({ page }) => {
      // Establish keyboard input modality before programmatically choosing
      // the starting control, so :focus-visible represents keyboard use.
      await page.keyboard.press('Tab');
      await page.locator('#rentals-buy').focus();
      for (let index = 0; index < CONTROLS.length; index++) {
        if (index) await page.keyboard.press('Tab');
        const [id] = CONTROLS[index];
        const control = page.locator(`#${id}`);
        await expect(control).toBeFocused();
        const focusStyle = await control.evaluate(el => {
          const style = getComputedStyle(el);
          return { visible: el.matches(':focus-visible'), outline: style.outlineStyle,
            width: parseFloat(style.outlineWidth) };
        });
        expect(focusStyle.visible).toBe(true);
        expect(focusStyle.outline).not.toBe('none');
        expect(focusStyle.width).toBeGreaterThanOrEqual(2);
      }
      for (const [id, filename, query] of [
        ['rentals-export', 'rentals.csv', ''],
        ['rentals-export-analysis', 'rentals_analysis.csv', '?mode=analysis'],
      ]) {
        await page.locator(`#${id}`).focus();
        const [download, request] = await Promise.all([
          page.waitForEvent('download'),
          page.waitForRequest(req => new URL(req.url()).pathname === '/api/rentals/export'),
          page.keyboard.press('Enter'),
        ]);
        expect(download.suggestedFilename()).toBe(filename);
        expect(new URL(request.url()).search).toBe(query);
      }
      await page.locator('#rentals-refresh').focus();
      await Promise.all([
        page.waitForRequest(req => new URL(req.url()).pathname === '/api/rentals'),
        page.keyboard.press('Enter'),
      ]);
      await expect(page.locator('#rentals-count-badge')).toHaveText('1 rentals');
      await expect(page.locator('#rentals-panel .skel-overlay')).toHaveCount(0);
    });
  });
}
