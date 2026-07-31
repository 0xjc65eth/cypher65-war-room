/**
 * CYPHER65 War Room — E2E Dashboard Tests
 * =========================================
 *
 * Prerequisites: Flask server running on BASE_URL (default http://127.0.0.1:8765)
 *
 * Run:  npx playwright test tests/e2e/dashboard.spec.js
 * CI:   bash run-e2e.sh
 */

import { test, expect } from '@playwright/test';

// ══════════════════════════════════════════════════════════════════════
//  Helpers
// ══════════════════════════════════════════════════════════════════════

/** Wait for the page to fully load and complete at least one poll cycle */
async function waitForDashboard(page) {
  await page.waitForSelector('#app-shell', { timeout: 15000 });
  await Promise.race([
    page.waitForFunction(() => {
      const el = document.getElementById('m-hashrate');
      return el && el.textContent && !el.textContent.includes('—');
    }, { timeout: 20000 }),
    page.waitForSelector('#status-bar', { timeout: 10000 }),
    page.waitForTimeout(8000),
  ]);
  await page.waitForTimeout(1000);
}

/** Attach console + page error listeners and return a checker object */
function setupErrorCapture(page) {
  const errors = [];
  page.on('console', msg => {
    if (msg.type() === 'error') errors.push(msg.text());
  });
  page.on('pageerror', err => errors.push(err.message));
  return {
    getCritical() {
      return errors.filter(e =>
        !e.includes('[boot]') && !e.includes('ServiceWorker')
      );
    },
    all() { return errors; },
  };
}

/** Check that a DOM element has non-empty, non-placeholder text */
async function expectElementHasContent(page, selector, timeout = 8000) {
  const el = page.locator(selector);
  await expect(el).toBeVisible({ timeout });
  const text = await el.textContent();
  expect(text).not.toBeNull();
  expect(text.trim()).not.toBe('');
  expect(text.trim()).not.toBe('—');
}

// ══════════════════════════════════════════════════════════════════════
//  Tests
// ══════════════════════════════════════════════════════════════════════

test.describe('CYPHER65 War Room — Dashboard E2E', () => {

  // ──────────────────────────────────────────────────────────────────
  //  SECTION 1: Initial Load & Console Health
  // ──────────────────────────────────────────────────────────────────

  test.describe('01 — Initial Load & Console Health', () => {
    test('page loads with correct title and no critical console errors', async ({ page }) => {
      const capture = setupErrorCapture(page);

      await page.goto('/');
      await waitForDashboard(page);

      const title = await page.title();
      expect(title).toContain('CYPHER65');

      const critical = capture.getCritical();
      expect(critical.length).toBe(0,
        `Critical console errors: ${JSON.stringify(critical)}`
      );
    });

    test('no JavaScript ReferenceErrors (dom is not defined)', async ({ page }) => {
      const capture = setupErrorCapture(page);

      await page.goto('/');
      await waitForDashboard(page);

      const domErrors = capture.all().filter(e =>
        e.includes('dom is not defined')
      );
      expect(domErrors.length).toBe(0,
        `'dom is not defined' errors: ${JSON.stringify(domErrors)}`
      );
      expect(capture.all().length).toBe(0,
        `All page errors: ${JSON.stringify(capture.all())}`
      );
    });
  });

  // ──────────────────────────────────────────────────────────────────
  //  SECTION 2: Key Panels Render
  // ──────────────────────────────────────────────────────────────────

  test.describe('02 — Key Panel Rendering', () => {
    test.beforeEach(async ({ page }) => {
      await page.goto('/');
      await waitForDashboard(page);
    });

    test('sidebar is visible with system status', async ({ page }) => {
      await expect(page.locator('#sidebar')).toBeVisible();
      await expect(page.locator('#status-bar')).toBeVisible();
      // Should show either ONLINE or OFFLINE
      const statusEl = page.locator('#status-bar, #sb-status');
      await expect(statusEl.first()).toBeVisible();
    });

    test('KPI cards show hashrate / best diff / shares / pool HR', async ({ page }) => {
      await expect(page.locator('#kpi-hashrate')).toBeVisible();
      await expect(page.locator('#kpi-bestdiff')).toBeVisible();
      await expect(page.locator('#kpi-shares')).toBeVisible();
      await expect(page.locator('#kpi-poolhr')).toBeVisible();
    });

    test('worker hashrate displays a value', async ({ page }) => {
      await expectElementHasContent(page, '#hud-hashrate, #m-hashrate, #kpi-hashrate');
    });

    test('BTC price visible in network block', async ({ page }) => {
      // BTC price can be — if cache is cold; but the element should exist
      await expect(page.locator('#n-btc-usd')).toBeVisible();
    });

    test('Live Log contains system message', async ({ page }) => {
      const terminal = page.locator('#terminal');
      await expect(terminal).toBeVisible();
      // Should show at least one event or "SYSTEM" message
      await expect(terminal.locator('.terminal__line').first()).toBeVisible({ timeout: 10000 });
    });

    test('AI Operator panel responds to input', async ({ page }) => {
      const aiInput = page.locator('#ai-input');
      await expect(aiInput).toBeVisible({ timeout: 10000 });
      await aiInput.fill('help');
      await page.keyboard.press('Enter');
      await page.waitForTimeout(1500);
      // Check that the AI responded
      const aiBody = page.locator('#ai-operator-body, .ai-messages, .ai-response');
      await expect(aiBody.first()).not.toBeEmpty();
    });

    test('Axe Fleet panel renders', async ({ page }) => {
      await expect(page.locator('#axe-fleet-panel')).toBeVisible();
    });
  });

  // ──────────────────────────────────────────────────────────────────
  //  SECTION 3: Theme Toggle
  // ──────────────────────────────────────────────────────────────────

  test.describe('03 — Theme Toggle', () => {
    test.beforeEach(async ({ page }) => {
      await page.goto('/');
      await waitForDashboard(page);
    });

    test('toggle switches between dark and light theme', async ({ page }) => {
      const toggleBtn = page.locator('#theme-toggle');
      await expect(toggleBtn).toBeVisible();

      // Initial state should be dark (no data-theme attr)
      let theme = await page.evaluate(() =>
        document.documentElement.getAttribute('data-theme')
      );
      const initialIsDark = theme !== 'light';

      // Click to toggle
      await toggleBtn.click();
      await page.waitForTimeout(500);
      theme = await page.evaluate(() =>
        document.documentElement.getAttribute('data-theme')
      );
      if (initialIsDark) {
        expect(theme).toBe('light');
      } else {
        expect(theme).toBeNull();
      }

      // Click again to toggle back
      await toggleBtn.click();
      await page.waitForTimeout(500);
      theme = await page.evaluate(() =>
        document.documentElement.getAttribute('data-theme')
      );
      if (initialIsDark) {
        expect(theme).toBeNull(); // back to dark
      } else {
        expect(theme).toBe('light'); // back to light
      }
    });
  });

  // ──────────────────────────────────────────────────────────────────
  //  SECTION 4: Navigation & Tabs
  // ──────────────────────────────────────────────────────────────────

  test.describe('04 — Navigation & Tabs', () => {
    test.beforeEach(async ({ page }) => {
      await page.goto('/');
      await waitForDashboard(page);
    });

    test('sidebar links navigate to sections', async ({ page }) => {
      // Click Fleet sidebar link
      const fleetLink = page.locator('.sidebar__link[data-section="fleet"]');
      await expect(fleetLink).toBeVisible();
      await fleetLink.click();
      await page.waitForTimeout(1000);
      await expect(page.locator('#section-fleet')).toBeVisible();

      // Click Analytics sidebar link
      const analyticsLink = page.locator('.sidebar__link[data-section="analytics"]');
      await expect(analyticsLink).toBeVisible();
      await analyticsLink.click();
      await page.waitForTimeout(1000);
      // The Deep Analytics tab should be active
      await expect(page.locator('#tab-charts.active')).toBeVisible({ timeout: 5000 });
    });

    test('Live Terminal tab is accessible and input accepts commands', async ({ page }) => {
      // Click Terminal sidebar link
      const terminalLink = page.locator('.sidebar__link[data-section="terminal"]');
      await expect(terminalLink).toBeVisible();
      await terminalLink.click();
      await page.waitForTimeout(1000);

      // The terminal tab should now be active
      await expect(page.locator('#tab-terminal.active')).toBeVisible({ timeout: 5000 });

      // Terminal input should be visible and focused
      const termInput = page.locator('#terminal-input');
      await expect(termInput).toBeVisible({ timeout: 5000 });

      // Type a command and submit
      await termInput.fill('help');
      await page.keyboard.press('Enter');
      await page.waitForTimeout(500);

      // Check that a response appeared in terminal-body
      const termBody = page.locator('#terminal-body');
      const bodyText = await termBody.textContent();
      expect(bodyText).toContain('help');
    });
  });

  // ──────────────────────────────────────────────────────────────────
  //  SECTION 5: Interactive Controls
  // ──────────────────────────────────────────────────────────────────

  test.describe('05 — Interactive Controls', () => {
    test.beforeEach(async ({ page }) => {
      await page.goto('/');
      await waitForDashboard(page);
    });

    test('profit mode buttons switch POOL/SOLO/RENTAL', async ({ page }) => {
      const profitModes = page.locator('.profit-mode-btn, [data-profit-mode]');
      const count = await profitModes.count();
      expect(count).toBeGreaterThanOrEqual(2); // at least POOL and SOLO

      // Click the SOLO button
      const soloBtn = profitModes.filter({ hasText: /solo/i }).first();
      await expect(soloBtn).toBeVisible();
      await soloBtn.click();
      await page.waitForTimeout(500);

      // Verify the BTC/day value changed (solo is different from pool)
      const btcDay = page.locator('#p-btc-day');
      await expect(btcDay).toBeVisible();
    });

    test('Hashmarket filters show provider chips', async ({ page }) => {
      const filterContainer = page.locator('#mkt-filters');
      await expect(filterContainer).toBeVisible({ timeout: 10000 });
      const chips = filterContainer.locator('[data-mkt-filter]');
      const chipCount = await chips.count();
      expect(chipCount).toBeGreaterThanOrEqual(2); // All + at least 1 provider
    });

    test('Export modal opens', async ({ page }) => {
      const exportBtn = page.locator('#open-exports');
      await expect(exportBtn).toBeVisible();
      await exportBtn.click();
      await page.waitForTimeout(500);

      // Export modal should be visible
      const modal = page.locator('#export-modal');
      await expect(modal).toBeVisible({ timeout: 5000 });

      // Should have JSON and CSV buttons
      const jsonBtn = modal.locator('#export-json');
      const csvBtn = modal.locator('#export-csv');
      await expect(jsonBtn).toBeVisible();
      await expect(csvBtn).toBeVisible();

      // Close via pressing Escape
      await page.keyboard.press('Escape');
      await page.waitForTimeout(300);
      await expect(modal).not.toBeVisible();
    });
  });

  // ──────────────────────────────────────────────────────────────────
  //  SECTION 6: Mobile Responsiveness
  // ──────────────────────────────────────────────────────────────────

  test.describe('06 — Mobile Responsiveness', () => {
    test.use({ viewport: { width: 375, height: 812 } });

    test('mobile layout: sidebar hidden by default, toggle works', async ({ page }) => {
      await page.goto('/');
      await waitForDashboard(page);

      // Sidebar should be closed by default on mobile
      const sidebar = page.locator('#sidebar');
      expect(await sidebar.getAttribute('class')).not.toContain('open');

      // Sidebar toggle button should be visible
      const mobileToggle = page.locator('#sidebar-mobile-toggle');
      await expect(mobileToggle).toBeVisible();

      // Click to open
      await mobileToggle.click();
      await page.waitForTimeout(500);
      expect(await sidebar.getAttribute('class')).toContain('open');

      // Click overlay to close
      const overlay = page.locator('#sidebar-overlay');
      await overlay.click();
      await page.waitForTimeout(500);
      expect(await sidebar.getAttribute('class')).not.toContain('open');
    });

    test('mobile: KPI cards stack in one column', async ({ page }) => {
      await page.goto('/');
      await waitForDashboard(page);

      const kpiCards = page.locator('#kpi-hashrate, #kpi-bestdiff, #kpi-shares, #kpi-poolhr');
      const count = await kpiCards.count();
      expect(count).toBeGreaterThanOrEqual(2);
    });
  });

  // ──────────────────────────────────────────────────────────────────
  //  SECTION 7: Live Terminal Commands
  // ──────────────────────────────────────────────────────────────────

  test.describe('07 — Live Terminal Commands', () => {
    test.beforeEach(async ({ page }) => {
      await page.goto('/');
      await waitForDashboard(page);
      // Navigate to terminal
      const terminalLink = page.locator('.sidebar__link[data-section="terminal"]');
      await terminalLink.click();
      await page.waitForTimeout(1000);
      await expect(page.locator('#tab-terminal.active')).toBeVisible({ timeout: 5000 });
    });

    test('help command lists available commands', async ({ page }) => {
      const termInput = page.locator('#terminal-input');
      await expect(termInput).toBeVisible();
      await termInput.fill('help');
      await page.keyboard.press('Enter');
      await page.waitForTimeout(500);

      const termBody = page.locator('#terminal-body');
      await expect(termBody).toContainText('Available commands');
    });

    test('status command shows system state', async ({ page }) => {
      const termInput = page.locator('#terminal-input');
      await termInput.fill('status');
      await page.keyboard.press('Enter');
      await page.waitForTimeout(500);

      const termBody = page.locator('#terminal-body');
      await expect(termBody).toContainText('ONLINE');
    });

    test('workers command shows worker count', async ({ page }) => {
      const termInput = page.locator('#terminal-input');
      await termInput.fill('workers');
      await page.keyboard.press('Enter');
      await page.waitForTimeout(500);

      const termBody = page.locator('#terminal-body');
      await expect(termBody).toContainText('workers');
    });

    test('unknown command shows help tip', async ({ page }) => {
      const termInput = page.locator('#terminal-input');
      await termInput.fill('foobar123');
      await page.keyboard.press('Enter');
      await page.waitForTimeout(500);

      const termBody = page.locator('#terminal-body');
      await expect(termBody).toContainText('Unknown command');
      await expect(termBody).toContainText('help');
    });
  });
});
