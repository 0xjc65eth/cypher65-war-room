/**
 * CYPHER65 War Room — E2E Alert Center Tabs Regression
 * =====================================================
 *
 * Guards the Alert Center tab strip (Active / History / Rules).
 *
 * Pre-existing bug found by the browser visual audit: the #ac-tabs
 * container shipped EMPTY in the template and nothing ever injected the
 * tab buttons — the History and Rules panes (incl. automation rules +
 * the execution log) were unreachable from the UI. The fix injects the
 * buttons on init when the container is empty (static/app.js).
 *
 * This spec is the permanent regression guard: if the tab strip ever
 * stops rendering, or a tab stops switching its pane, this fails.
 *
 * Prerequisites: Flask server running on BASE_URL (see playwright.config.js).
 *
 * Run:  npx playwright test tests/e2e/alert-center-tabs.spec.js
 */

import { test, expect } from '@playwright/test';

test.describe('Alert Center tab strip — regression', () => {

  /** The ⚠ RULES button lives in the AI OPERATOR panel (data-module="automations")
   *  — navigate there first so the button is visible, then open the modal. */
  async function openAlertCenter(page) {
    await page.goto('/');
    await page.waitForSelector('#app-shell', { timeout: 15000 });
    await page.click('.sidebar__link[data-module="automations"]');
    await expect(page.locator('#open-alert-center')).toBeVisible({ timeout: 8000 });
    await page.click('#open-alert-center');
    await page.waitForSelector('#alert-center-modal.modal--open', { timeout: 8000 });
  }

  test('renders the Active / History / Rules tabs and switches panes', async ({ page }) => {
    await openAlertCenter(page);
    await page.waitForSelector('#alert-center-modal.modal--open', { timeout: 8000 });

    // ── The tab strip must have been injected (regression guard) ──
    const tabs = page.locator('#ac-tabs .ac-tab');
    await expect(tabs).toHaveCount(3);
    await expect(tabs.nth(0)).toHaveText(/Active/);
    await expect(tabs.nth(1)).toHaveText(/History/);
    await expect(tabs.nth(2)).toHaveText(/Rules/);

    // Initial state: Active tab is selected and its pane visible
    await expect(tabs.nth(0)).toHaveClass(/active/);
    await expect(page.locator('#ac-active-pane')).toBeVisible();
    await expect(page.locator('#ac-history-pane')).toBeHidden();
    await expect(page.locator('#ac-rules-pane')).toBeHidden();

    // ── History tab → history pane visible, active hidden ──
    await tabs.nth(1).click();
    await expect(tabs.nth(1)).toHaveClass(/active/);
    await expect(tabs.nth(0)).not.toHaveClass(/active/);
    await expect(page.locator('#ac-history-pane')).toBeVisible();
    await expect(page.locator('#ac-active-pane')).toBeHidden();

    // ── Rules tab → rules pane visible + execution log strip present ──
    await tabs.nth(2).click();
    await expect(tabs.nth(2)).toHaveClass(/active/);
    await expect(page.locator('#ac-rules-pane')).toBeVisible();
    await expect(page.locator('#ac-history-pane')).toBeHidden();

    // The automation execution log lives in the Rules pane — it must be
    // present in the DOM (populated lazily by acLoadRules).
    await expect(page.locator('#ac-exec-strip')).toBeVisible();
    await expect(page.locator('#ac-exec-list')).toBeVisible();

    // ── Back to Active → round-trip works ──
    await tabs.nth(0).click();
    await expect(tabs.nth(0)).toHaveClass(/active/);
    await expect(page.locator('#ac-active-pane')).toBeVisible();
    await expect(page.locator('#ac-rules-pane')).toBeHidden();
  });

  test('tabs survive reopening the modal', async ({ page }) => {
    await openAlertCenter(page);

    // Switch to Rules, close, reopen — the strip must not duplicate
    await page.locator('#ac-tabs .ac-tab').nth(2).click();
    await expect(page.locator('#ac-rules-pane')).toBeVisible();

    await page.locator('#alert-center-modal .modal__close').first().click();
    await expect(page.locator('#alert-center-modal')).not.toHaveClass(/modal--open/);

    await page.click('#open-alert-center');
    await page.waitForSelector('#alert-center-modal.modal--open', { timeout: 8000 });

    // No duplicate buttons (the injection guard reuses the existing strip)
    await expect(page.locator('#ac-tabs .ac-tab')).toHaveCount(3);
  });
});
