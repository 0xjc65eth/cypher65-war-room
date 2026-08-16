/**
 * CYPHER65 War Room — E2E Auto-Pilot Arm Toggle
 * =============================================
 *
 * Guards the Auto-Pilot arm/disarm control in the AUTOMATIONS panel
 * (AI OPERATOR header):
 *
 *   - Toggle renders with the fail-closed default OFF.
 *   - Arming requires TYPED confirmation ("ARMAR") — wrong text keeps the
 *     confirm button disabled, correct text fires POST /api/automation/arm
 *     with {armed: true}, and the label flips to ARM.
 *   - The action-budget badge reflects the status endpoint.
 *   - Disarming is a direct toggle (safe action, no confirmation) → OFF.
 *
 * Endpoint mocks (status/arm/snapshot) make the test deterministic and
 * independent of real tenant auth; the snapshot is proxied and patched so
 * the poll-driven render agrees with the mocked armed state.
 *
 * NOTE: serviceWorkers must be 'block' — static/sw.js fetches bypass
 * page.route (learned in tests/e2e/live-mining.spec.js).
 *
 * Prerequisites: Flask server running on BASE_URL (see playwright.config.js).
 *
 * Run:  npx playwright test tests/e2e/automations-arm.spec.js
 */

import { test, expect } from '@playwright/test';

test.use({ serviceWorkers: 'block' });

test.describe('Auto-Pilot arm toggle — automations panel', () => {
  let armedState = false;
  let actionsInWindow = 0;

  /** Open the dashboard and land on the Automations module. */
  async function openAutomations(page) {
    await page.goto('/');
    await page.waitForSelector('#app-shell', { timeout: 15000 });
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
    await page.click('.sidebar__link[data-module="automations"]');
    await expect(page.locator('#ap-armed-btn')).toBeVisible({ timeout: 8000 });
  }

  test('arm via typed confirmation, then disarm directly', async ({ page }) => {
    armedState = false;
    actionsInWindow = 0;

    // ── Deterministic API mocks ──
    await page.route(/\/api\/automation\/status(\?|$)/, async (route) => {
      await route.fulfill({
        json: {
          armed: armedState,
          max_actions_per_window: 20,
          action_window_seconds: 3600,
          actions_in_window: actionsInWindow,
        },
      });
    });
    await page.route(/\/api\/automation\/arm(\?|$)/, async (route) => {
      const body = (route.request().postDataJSON && route.request().postDataJSON()) || {};
      armedState = !!body.armed;
      if (body.armed) actionsInWindow = 1;
      await route.fulfill({ json: { success: true, armed: armedState } });
    });
    // Snapshot: proxy the real payload but pin auto_pilot.armed to the mock
    // state so the server-truth render never fights the toggle.
    await page.route(/\/api\/snapshot(\?|$)/, async (route) => {
      const resp = await page.request.get(route.request().url());
      const body = await resp.json();
      body.auto_pilot = body.auto_pilot || {};
      body.auto_pilot.armed = armedState;
      await route.fulfill({ json: body });
    });

    await openAutomations(page);

    // ── Default: OFF (fail-closed) + budget from status ──
    await expect(page.locator('#ap-armed-label')).toHaveText('OFF');
    await expect(page.locator('#ap-budget-badge')).toContainText('0/20');

    // ── Click → typed-confirm modal opens ──
    await page.click('#ap-armed-btn');
    await expect(page.locator('#ap-arm-modal.modal--open')).toBeVisible();

    // Wrong text keeps the confirm disabled
    const typeInput = page.locator('#ap-arm-type');
    const confirmBtn = page.locator('#ap-arm-confirm');
    await typeInput.fill('ARM');
    await expect(confirmBtn).toBeDisabled();

    // Typing ARMAR enables the button; confirming fires the POST and flips the label
    await typeInput.fill('ARMAR');
    await expect(confirmBtn).toBeEnabled();
    const [req] = await Promise.all([
      page.waitForRequest(r => r.url().includes('/api/automation/arm') && r.method() === 'POST'),
      confirmBtn.click(),
    ]);
    expect(JSON.parse(req.postData())).toEqual({ armed: true });
    await expect(page.locator('#ap-arm-modal.modal--open')).toBeHidden();
    await expect(page.locator('#ap-armed-label')).toHaveText('ARM');
    await expect(page.locator('#ap-budget-badge')).toContainText('1/20');

    // ── Disarm: safe action, direct toggle (no modal) ──
    await page.click('#ap-armed-btn');
    await expect(page.locator('#ap-arm-modal.modal--open')).toBeHidden();
    await expect(page.locator('#ap-armed-label')).toHaveText('OFF');
  });
});
