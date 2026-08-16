/**
 * CYPHER65 War Room — E2E Docs Autocomplete Regression
 * =====================================================
 *
 * Guards the Docs search autocomplete (UX audit Módulo_09):
 *   1. typing in the docs search input renders a suggestion dropdown;
 *   2. suggestions rank title hits above body-only hits and highlight the
 *      query with <mark>;
 *   3. keyboard navigation (↓/↑/Enter) opens the selected section;
 *   4. Escape closes the dropdown; the ✕ clear restores every section;
 *   5. a query with no matches shows an honest empty state.
 *
 * Prerequisites: Flask server running on BASE_URL (see playwright.config.js).
 *
 * Run:  npx playwright test tests/e2e/docs-autocomplete.spec.js
 */

import { test, expect } from '@playwright/test';

test.describe('Docs autocomplete — regression', () => {

  /** Ensure the sidebar is open so sidebar links are clickable (mobile off-canvas).
   *  On the mobile-chrome project (≤768px) the sidebar is a hidden drawer —
   *  same helper as dashboard.spec.js. On desktop the toggle is invisible so
   *  this is a no-op. */
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

  /** Navigate to the Docs module and focus the search input. */
  async function openDocs(page) {
    await page.goto('/');
    await page.waitForSelector('#app-shell', { timeout: 15000 });
    await ensureSidebarOpen(page);
    await page.click('.sidebar__link[data-module="docs"]');
    await expect(page.locator('#section-docs')).toBeVisible({ timeout: 8000 });
    await page.click('#docs-search-input');
  }

  test('typing renders suggestions with the query highlighted', async ({ page }) => {
    await openDocs(page);

    await page.fill('#docs-search-input', 'latency');
    const box = page.locator('#docs-search-suggestions');
    await expect(box).toHaveClass(/open/, { timeout: 5000 });

    // The Latency section title must be suggested first (title hit).
    const first = box.locator('.docs-search__item').first();
    await expect(first.locator('.docs-search__item-title')).toContainText('Latency');
    // The query is wrapped in <mark> inside the suggestion.
    await expect(first.locator('mark').first()).toHaveText(/latency/i);
  });

  test('keyboard: ↓ + Enter opens the selected section', async ({ page }) => {
    await openDocs(page);

    await page.fill('#docs-search-input', 'probability');
    const box = page.locator('#docs-search-suggestions');
    await expect(box).toHaveClass(/open/, { timeout: 5000 });

    // Move the keyboard cursor down onto the first (only) suggestion.
    await page.keyboard.press('ArrowDown');
    await expect(box.locator('.docs-search__item').first()).toHaveClass(/active/);

    // Enter → navigates to the section and closes the dropdown.
    await page.keyboard.press('Enter');
    await expect(box).not.toHaveClass(/open/);
    await expect(page.locator('#docs-search-input')).toHaveAttribute('aria-expanded', 'false');
  });

  test('Escape closes the dropdown; clear restores every section', async ({ page }) => {
    await openDocs(page);

    await page.fill('#docs-search-input', 'pool');
    await expect(page.locator('#docs-search-suggestions')).toHaveClass(/open/, { timeout: 5000 });

    // Escape closes the dropdown but keeps the filter applied.
    await page.keyboard.press('Escape');
    await expect(page.locator('#docs-search-suggestions')).not.toHaveClass(/open/);

    // The ✕ clear empties the input → every section is visible again.
    await page.click('#docs-search-clear');
    await expect(page.locator('#docs-search-input')).toHaveValue('');
    const hiddenSections = await page.locator('.docs-content .doc-section').evaluateAll(
      els => els.filter(el => el.style.display === 'none').length
    );
    expect(hiddenSections).toBe(0);
  });

  test('no matches renders an honest empty state', async ({ page }) => {
    await openDocs(page);

    await page.fill('#docs-search-input', 'zzz-no-such-topic');
    const box = page.locator('#docs-search-suggestions');
    await expect(box).toHaveClass(/open/, { timeout: 5000 });
    await expect(box.locator('.docs-search__empty')).toBeVisible();
    await expect(box.locator('.docs-search__empty')).toContainText('no matches');
  });
});
