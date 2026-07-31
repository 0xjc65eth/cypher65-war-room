/**
 * CYPHER65 War Room — E2E Modal Tests
 * ====================================
 *
 * Prerequisites: Flask server running on BASE_URL (default http://127.0.0.1:8765)
 *
 * Run:  npx playwright test tests/e2e/modals.spec.js --project=chromium --workers=1
 *
 * Covers the Connect Wallet fix regression surface:
 *   - wallet / settings / export modals open VISIBLY (class modal--open + visible)
 *   - each closes via the ✕ button and via the Escape key
 *   - overlay isolation: a closed modal never leaves a lingering overlay that
 *     blocks subsequent clicks on other topbar buttons
 */

import { test, expect } from '@playwright/test';

const BASE_URL = process.env.BASE_URL || 'http://127.0.0.1:8765';

// ══════════════════════════════════════════════════════════════════════
//  Helpers
// ══════════════════════════════════════════════════════════════════════

/** Wait for the app shell + topbar to be ready (no data dependency). */
async function waitForDashboard(page) {
  await page.waitForSelector('#app-shell', { timeout: 15000 });
  await page.waitForSelector('#open-wallet', { timeout: 10000 });
  // Wait for skeleton loading overlays to detach so they can never race a
  // click (skeletons are now pointer-events:none too, so this is belt+braces).
  // Timeout kept short: skeletons normally detach after the first poll render,
  // and the CSS fix already guarantees they cannot intercept clicks.
  await page.waitForFunction(() => {
    return document.querySelectorAll('.skel-overlay').length === 0;
  }, { timeout: 10000 }).catch(() => {});
  await page.waitForTimeout(800); // let the IIFE wire all handlers
}

/**
 * Assert a modal is open: has modal--open AND is actually visible.
 * This is the regression assertion — before the CSS fix the modal got
 * modal--open but stayed invisible (opacity:0 / pointer-events:none).
 * Note: Playwright treats opacity:0 as "visible", so we explicitly assert
 * the computed styles that were broken (opacity 1 + interactive).
 */
async function expectModalOpen(page, id) {
  const modal = page.locator(`#${id}`);
  await expect(modal).toHaveClass(/modal--open/, { timeout: 5000 });
  await expect(modal).toBeVisible({ timeout: 5000 });
  await expect(modal).toHaveCSS('opacity', '1');          // ← the invisible-modal bug
  await expect(modal).toHaveCSS('pointer-events', 'auto'); // ← the un-clickable overlay bug
}

/** Assert a modal is fully closed (no modal--open, not visible). */
async function expectModalClosed(page, id) {
  const modal = page.locator(`#${id}`);
  await expect(modal).not.toHaveClass(/modal--open/, { timeout: 5000 });
  await expect(modal).not.toBeVisible({ timeout: 5000 });
}

/** Close the currently open modal by clicking its ✕ close button. */
async function closeViaXButton(page, id) {
  const modal = page.locator(`#${id}`);
  // Wallet/settings use .modal__close; export uses [data-close].
  const closeBtn = modal.locator('.modal__close').first();
  await closeBtn.click();
}

/** Attach console + pageerror listeners and return captured errors. */
function setupErrorCapture(page) {
  const errors = [];
  page.on('console', msg => {
    if (msg.type() === 'error') errors.push(msg.text());
  });
  page.on('pageerror', err => errors.push(err.message));
  return {
    all() { return errors; },
    critical() {
      return errors.filter(e =>
        !e.includes('[boot]') && !e.includes('ServiceWorker') && !e.includes('404')
      );
    },
  };
}

// ══════════════════════════════════════════════════════════════════════
//  Tests
// ══════════════════════════════════════════════════════════════════════

test.describe('CYPHER65 — Modals (wallet / settings / export)', () => {

  test.beforeEach(async ({ page }) => {
    await page.goto(BASE_URL);
    await waitForDashboard(page);
  });

  // ──────────────────────────────────────────────────────────────────
  //  SECTION 1: Wallet Modal
  // ──────────────────────────────────────────────────────────────────

  test.describe('01 — Wallet Modal', () => {

    test('opens VISIBLY when clicking CONNECT and shows its title', async ({ page }) => {
      await page.locator('#open-wallet').click();
      await expectModalOpen(page, 'wallet-modal');
      await expect(page.locator('#wallet-modal .modal__title')).toContainText('CONNECT WALLET');
    });

    test('closes via the ✕ close button', async ({ page }) => {
      await page.locator('#open-wallet').click();
      await expectModalOpen(page, 'wallet-modal');

      await closeViaXButton(page, 'wallet-modal');
      await expectModalClosed(page, 'wallet-modal');
    });

    test('closes via the Escape key', async ({ page }) => {
      await page.locator('#open-wallet').click();
      await expectModalOpen(page, 'wallet-modal');

      await page.keyboard.press('Escape');
      await expectModalClosed(page, 'wallet-modal');
    });
  });

  // ──────────────────────────────────────────────────────────────────
  //  SECTION 2: Settings Modal
  // ──────────────────────────────────────────────────────────────────

  test.describe('02 — Settings Modal', () => {

    test('opens VISIBLY when clicking the settings button', async ({ page }) => {
      await page.locator('#open-settings').click();
      await expectModalOpen(page, 'settings-modal');
      await expect(page.locator('#settings-modal .modal__title')).toContainText('SETTINGS');
    });

    test('closes via the ✕ close button', async ({ page }) => {
      await page.locator('#open-settings').click();
      await expectModalOpen(page, 'settings-modal');

      await closeViaXButton(page, 'settings-modal');
      await expectModalClosed(page, 'settings-modal');
    });

    test('closes via the Escape key', async ({ page }) => {
      await page.locator('#open-settings').click();
      await expectModalOpen(page, 'settings-modal');

      await page.keyboard.press('Escape');
      await expectModalClosed(page, 'settings-modal');
    });
  });

  // ──────────────────────────────────────────────────────────────────
  //  SECTION 3: Export Modal
  // ──────────────────────────────────────────────────────────────────

  test.describe('03 — Export Modal', () => {

    test('opens VISIBLY and shows JSON/CSV export buttons', async ({ page }) => {
      // Use button#open-exports: a stray <span id="open-exports"> exists in
      // the DOM, so the bare #open-exports selector would be ambiguous.
      await page.locator('button#open-exports').click();
      await expectModalOpen(page, 'export-modal');
      await expect(page.locator('#export-modal .modal__title')).toContainText('EXPORT');
      await expect(page.locator('#export-json')).toBeVisible();
      await expect(page.locator('#export-csv')).toBeVisible();
    });

    test('closes via the ✕ close button (data-close)', async ({ page }) => {
      await page.locator('button#open-exports').click();
      await expectModalOpen(page, 'export-modal');

      await page.locator('#export-modal [data-close]').click();
      await expectModalClosed(page, 'export-modal');
    });

    test('closes via the Escape key', async ({ page }) => {
      await page.locator('button#open-exports').click();
      await expectModalOpen(page, 'export-modal');

      await page.keyboard.press('Escape');
      await expectModalClosed(page, 'export-modal');
    });
  });

  // ──────────────────────────────────────────────────────────────────
  //  SECTION 4: Overlay Isolation — the core regression surface
  // ──────────────────────────────────────────────────────────────────

  test.describe('04 — Overlay Isolation', () => {

    test('sequential open/close across all modals leaves no lingering overlay', async ({ page }) => {
      // wallet → close → settings → close → export → close → wallet again
      await page.locator('#open-wallet').click();
      await expectModalOpen(page, 'wallet-modal');
      await closeViaXButton(page, 'wallet-modal');
      await expectModalClosed(page, 'wallet-modal');

      await page.locator('#open-settings').click();
      await expectModalOpen(page, 'settings-modal');
      await closeViaXButton(page, 'settings-modal');
      await expectModalClosed(page, 'settings-modal');

      await page.locator('button#open-exports').click();
      await expectModalOpen(page, 'export-modal');
      await page.locator('#export-modal [data-close]').click();
      await expectModalClosed(page, 'export-modal');

      // Everything closed again → every topbar button still reachable
      await page.locator('#open-wallet').click();
      await expectModalOpen(page, 'wallet-modal');

      // No modal may remain open at the end
      const openCount = await page.locator('.modal-overlay.modal--open').count();
      expect(openCount).toBe(1); // only the wallet modal just opened
    });

    test('while a modal is open, its overlay blocks other topbar buttons', async ({ page }) => {
      await page.locator('#open-wallet').click();
      await expectModalOpen(page, 'wallet-modal');

      // Force the click through the overlay (a real user click would land on
      // the overlay, not the button) → the settings modal must NOT open.
      await page.locator('#open-settings').click({ force: true });
      await page.waitForTimeout(400);
      await expectModalClosed(page, 'settings-modal');

      // And the wallet modal is still the only one open
      await expectModalOpen(page, 'wallet-modal');
    });

    test('after closing, a previously blocked button works immediately', async ({ page }) => {
      await page.locator('#open-wallet').click();
      await expectModalOpen(page, 'wallet-modal');

      // Simulate a click that lands on the overlay (no-op)
      await page.locator('#open-settings').click({ force: true });
      await page.waitForTimeout(300);

      // Close the wallet modal properly
      await closeViaXButton(page, 'wallet-modal');
      await expectModalClosed(page, 'wallet-modal');

      // The settings button must now work — regression for the old bug where
      // the invisible overlay (opacity:0 + pointer-events:none) stayed behind
      // and swallowed subsequent clicks.
      await page.locator('#open-settings').click();
      await expectModalOpen(page, 'settings-modal');
    });

    test('no critical console errors during modal interactions', async ({ page }) => {
      const capture = setupErrorCapture(page);

      await page.locator('#open-wallet').click();
      await expectModalOpen(page, 'wallet-modal');
      await closeViaXButton(page, 'wallet-modal');

      await page.locator('#open-settings').click();
      await expectModalOpen(page, 'settings-modal');
      await page.keyboard.press('Escape');

      await page.locator('button#open-exports').click();
      await expectModalOpen(page, 'export-modal');
      await page.locator('#export-modal [data-close]').click();

      const critical = capture.critical();
      expect(critical.length).toBe(0,
        `Critical console errors during modal interactions: ${JSON.stringify(critical)}`
      );
    });
  });
});
