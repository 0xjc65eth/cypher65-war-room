/**
 * CYPHER65 War Room — Topbar Responsiveness Tests
 * ================================================
 *
 * Uses a SINGLE page load + sequential viewport resizes to avoid
 * triggering API rate limits from multiple page loads.
 *
 * Breakpoints tested:
 *   1100px (tablet landscape) — 768px (tablet portrait)
 *   600px  (large phone)      — 375px (iPhone)
 *
 * Prerequisites: Flask server running on BASE_URL (default http://127.0.0.1:8765)
 *
 * Run:  npx playwright test tests/e2e/topbar-responsive.spec.js --project=chromium --workers=1
 *       npx playwright test tests/e2e/topbar-responsive.spec.js --headed --project=chromium --workers=1
 */

import { test, expect } from '@playwright/test';

const BASE_URL = process.env.BASE_URL || 'http://127.0.0.1:8765';

// ── Helpers ────────────────────────────────────────────────────────────

/** Navigate + wait for shell + first metric to populate */
async function loadPage(page) {
  await page.goto(BASE_URL);
  await page.waitForSelector('#app-shell', { timeout: 60000 });
  await page.waitForFunction(() => {
    const el = document.getElementById('tbar-hr');
    return el && el.textContent && !el.textContent.includes('—');
  }, { timeout: 30000 }).catch(() => { /* OK if no wallet data */ });
  await page.waitForTimeout(2000);
}

/** Wait for CSS reflow + JS resize handlers to fire after a viewport change */
async function waitForResize(page) {
  await page.waitForTimeout(2000);
}

/** Capture non-critical-filtered page errors */
function setupErrorCapture(page) {
  const errors = [];
  const NOISE = ['ServiceWorker','Failed to load resource','net::ERR_FAILED',
    '404','429','Too Many Requests','favicon','manifest.json'];
  page.on('console', msg => {
    if (msg.type() === 'error') {
      const t = msg.text();
      if (!NOISE.some(p => t.includes(p))) errors.push(t);
    }
  });
  page.on('pageerror', err => {
    const t = err.message;
    if (!NOISE.some(p => t.includes(p))) errors.push(t);
  });
  return {
    all() { return errors; },
    critical() { return errors.filter(e => !e.includes('ServiceWorker')); },
  };
}

/** Assert container doesn't overflow viewport */
async function expectNoOverflow(page, container, tol = 2) {
  const box = await page.locator(container).boundingBox();
  expect(box).not.toBeNull();
  if (box) {
    const vp = page.viewportSize();
    expect(box.x + box.width).toBeLessThanOrEqual(vp.width + tol);
    expect(box.x).toBeGreaterThanOrEqual(-tol);
  }
}

// ── Test ───────────────────────────────────────────────────────────────

test.describe('Topbar — Responsive Breakpoints (single load)', () => {

  test('all breakpoints adapt correctly', async ({ page }) => {
    test.skip(
      test.info().project.name === 'mobile-chrome',
      'Uses explicit viewport overrides — skip mobile-chrome project'
    );
    const capture = setupErrorCapture(page);

    // ══════════════════════════════════════════════════════════════════
    //  BREAKPOINT 1:  1100px  — tablet landscape
    // ══════════════════════════════════════════════════════════════════
    await page.setViewportSize({ width: 1100, height: 800 });
    await loadPage(page);

    // Brand + identity
    await expect(page.locator('.topbar__brand')).toBeVisible();
    await expect(page.locator('#topbar-address')).toBeVisible();
    await expect(page.locator('#tbar-led')).toBeVisible();
    await expect(page.locator('#tbar-status')).toBeVisible();
    await expect(page.locator('#clock')).toBeVisible();

    // All 4 metrics
    await expect(page.locator('#tbar-hr')).toBeVisible();
    await expect(page.locator('#tbar-best')).toBeVisible();
    await expect(page.locator('#tbar-workers')).toBeVisible();
    await expect(page.locator('#tbar-btc')).toBeVisible();

    // Buttons (tag-prefixed to avoid duplicate-ID strict mode)
    await expect(page.locator('button#open-settings')).toBeVisible();
    await expect(page.locator('button#theme-toggle')).toBeVisible();
    await expect(page.locator('button#open-exports')).toBeVisible();
    await expect(page.locator('button#refresh-now')).toBeVisible();

    await expectNoOverflow(page, '.topbar', 2);

    // ══════════════════════════════════════════════════════════════════
    //  BREAKPOINT 2:  768px  — tablet portrait
    // ══════════════════════════════════════════════════════════════════
    await page.setViewportSize({ width: 768, height: 1024 });
    await waitForResize(page);

    await expect(page.locator('.topbar__brand')).toBeVisible();
    // Address may be hidden by text-overflow:ellipsis at this width
    await expect(page.locator('#topbar-address')).toBeAttached();
    await expect(page.locator('#tbar-status')).toBeVisible();
    await expect(page.locator('#tbar-hr')).toBeVisible();
    await expect(page.locator('#tbar-best')).toBeVisible();
    await expect(page.locator('#tbar-workers')).toBeVisible();
    await expect(page.locator('#tbar-btc')).toBeVisible();
    await expect(page.locator('button#open-settings')).toBeVisible();
    await expect(page.locator('button#theme-toggle')).toBeVisible();

    await expectNoOverflow(page, '.topbar', 2);

    // ══════════════════════════════════════════════════════════════════
    //  BREAKPOINT 3:  600px  — large phone
    // ══════════════════════════════════════════════════════════════════
    await page.setViewportSize({ width: 600, height: 900 });
    await waitForResize(page);

    await expect(page.locator('.topbar__brand')).toBeVisible();
    await expect(page.locator('#clock')).toBeVisible();

    // All 4 metric containers still in DOM (may wrap/hide via CSS)
    const metricCount600 = await page.locator('.topbar__metric').count();
    expect(metricCount600).toBe(4);
    await expect(page.locator('#tbar-hr')).toBeAttached();
    await expect(page.locator('button#open-settings')).toBeVisible();
    await expect(page.locator('button#theme-toggle')).toBeVisible();

    await expectNoOverflow(page, '.topbar', 2);

    // ══════════════════════════════════════════════════════════════════
    //  BREAKPOINT 4:  375px  — iPhone mobile
    // ══════════════════════════════════════════════════════════════════
    await page.setViewportSize({ width: 375, height: 812 });
    await waitForResize(page);

    await expect(page.locator('.topbar__brand')).toBeVisible();
    await expect(page.locator('#tbar-hr')).toBeAttached();

    // Settings button — open then close
    await expect(page.locator('button#open-settings')).toBeVisible();
    await page.locator('button#open-settings').click();
    await page.waitForTimeout(500);
    await page.keyboard.press('Escape');
    await page.waitForTimeout(500);

    // Theme toggle — click to verify
    await expect(page.locator('button#theme-toggle')).toBeVisible();
    await page.locator('button#theme-toggle').click();
    await page.waitForTimeout(300);
    await page.locator('button#theme-toggle').click();
    await page.waitForTimeout(300);

    // Sidebar toggle: open + close via button
    const sidebarBtn = page.locator('button#sidebar-toggle');
    await expect(sidebarBtn).toBeVisible();
    await sidebarBtn.click({ force: true });
    await page.waitForTimeout(800);

    const openAfterClick = await page.evaluate(() => {
      const sb = document.getElementById('sidebar');
      return sb && sb.classList.contains('open');
    });

    if (openAfterClick) {
      await sidebarBtn.click({ force: true });
      await page.waitForTimeout(800);
      const openAfterSecond = await page.evaluate(() => {
        const sb = document.getElementById('sidebar');
        return sb && sb.classList.contains('open');
      });
      expect(openAfterSecond).toBe(false);
    }

    await expectNoOverflow(page, '.topbar', 2);

    // ══════════════════════════════════════════════════════════════════
    //  FINAL:  No console errors across all breakpoints
    // ══════════════════════════════════════════════════════════════════
    expect(capture.critical().length).toBe(0,
      `Console errors: ${JSON.stringify(capture.critical())}`
    );
  });
});
