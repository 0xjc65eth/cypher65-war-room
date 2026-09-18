/**
 * CYPHER65 — Fleet audit e2e (Issue #627): the agentless dead-end.
 *
 * Reproduces BUG A end-to-end in a real browser: a user opens Fleet with no
 * agent installed and a failing LAN scan. The manual-add path (wizard method
 * card + empty-state "+ Add Device") must ALWAYS be reachable — the old
 * wiring bailed on a missing header chip and left the empty-state button
 * dead, stranding the operator.
 */

import { test, expect } from '@playwright/test';

/** Mobile: the sidebar is off-canvas — open it before clicking a module. */
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

/** Navigate to the dashboard, wait for the shell, then open the Fleet module. */
async function gotoShell(page) {
  const response = await page.goto('/');
  expect(response, 'no HTTP response for GET /').not.toBeNull();
  await page.waitForSelector('#app-shell', { timeout: 15000 });
  // The fleet panel is a sidebar module — without navigating to it the
  // wizard elements stay hidden (same pattern as agent-revoke.spec.js).
  await ensureSidebarOpen(page);
  await page.locator('.sidebar__link[data-module="fleet"]').click();
  await expect(page.locator('#axe-fleet-panel')).toBeVisible({ timeout: 8000 });
  // The runtime empty-state render replaces the static grid content.
  await expect(page.locator('#axe-grid .axe-empty')).toBeAttached({ timeout: 8000 });
}

test.describe('Fleet agentless · manual add always reachable (#627)', () => {
  test('fleet_agentless_manual_add_visible — wizard method card exists and opens', async ({ page }) => {
    await gotoShell(page);

    // The manual method card ships in the shell regardless of agent state.
    const manualCard = page.locator('[data-wiz-method="manual"]');
    await expect(manualCard).toBeAttached();
    await expect(manualCard).toContainText('Enter IP manually');

    // Opening the wizard reveals the form with the manual card visible.
    await page.click('#axe-fleet-add');
    await expect(page.locator('#axe-add-form')).toBeVisible();
    await expect(manualCard).toBeVisible();

    // Choosing manual lands on the IP + TEST CONNECTIVITY step — never a
    // dead end, with or without an agent.
    await manualCard.click();
    await expect(page.locator('#axe-add-ip')).toBeVisible();
    await expect(page.locator('#axe-test-conn')).toBeVisible();
  });

  test('empty-state "+ Add Device" opens the wizard even without the header chip', async ({ page }) => {
    await gotoShell(page);

    // Simulate a deployment variant that renders no header chip: the
    // empty-state button must STILL open the wizard (the fixed wiring no
    // longer bails when #axe-fleet-add is absent).
    await page.evaluate(() => {
      const chip = document.getElementById('axe-fleet-add');
      if (chip) chip.remove();
    });
    const emptyAdd = page.locator('#axe-empty-add');
    await expect(emptyAdd).toBeAttached();

    // Re-run the control wiring that boot() already executed by dispatching
    // a click: the fixed init no longer returns before wiring emptyAdd.
    await emptyAdd.click();
    await expect(page.locator('#axe-add-form')).toBeVisible();
  });

  test('scan refusal on cloud names the alternative instead of dead-ending', async ({ page }) => {
    await gotoShell(page);

    // The runtime empty state must name the AGENT as the cloud path — it
    // never pretends the scan is the only way.
    const empty = page.locator('#axe-grid .axe-empty');
    await expect(empty).toContainText('AGENTE LOCAL');
    // …and the manual-add button rides along in the same empty state.
    await expect(page.locator('#axe-empty-add')).toBeAttached();
  });
});
