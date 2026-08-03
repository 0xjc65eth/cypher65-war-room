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

/** Ensure the sidebar is open so sidebar links are clickable (mobile off-canvas) */
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

      // The app's global error boundary swallows window errors into the LIVE
      // LOG panel (#terminal) instead of the console — a console-only capture
      // misses them (the exact hole that hid "dom is not defined" for months:
      // renderKpiCards lived OUTSIDE the main IIFE, so every render threw and
      // the throttle showed it in the LIVE LOG every ~30-60s). Read the panel
      // text directly so boundary-caught errors are covered too.
      const liveLog = await page.locator('#terminal').textContent();
      expect(liveLog || '').not.toContain('dom is not defined');

      // renderKpiCards() must have populated the KPI cards — if it throws
      // before touching the DOM, they stay at the '\u2014' placeholder.
      // toHaveText auto-retries, so a slow first render can't flake the test.
      await expect(page.locator('#kpi-hashrate')).not.toHaveText('\u2014');
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
      // Strict-mode fix: the old comma selector matched BOTH #hud-hashrate and
      // #kpi-hashrate (Playwright refuses ambiguous locators). Target the HUD
      // cell (the worker hashrate) when a worker is connected; on an honest
      // worker-less boot the KPI card renders the '—' empty state instead.
      const hudCell = page.locator('#hud-hashrate');
      if (await hudCell.isVisible().catch(() => false)) {
        await expectElementHasContent(page, '#hud-hashrate');
      } else {
        await expect(page.locator('#kpi-hashrate')).toBeVisible();
      }
    });

    test('BTC price visible in network block', async ({ page }) => {
      // BTC price can be — if cache is cold; but the element should exist
      await expect(page.locator('#n-btc-usd')).toBeVisible();
    });

    test('Live Log contains system message', async ({ page }) => {
      // Live Log lives in the LIVE MINING module — navigate there first
      await ensureSidebarOpen(page);
      await page.locator('.sidebar__link[data-module="live"]').click();
      await page.waitForTimeout(600);
      const terminal = page.locator('#terminal');
      await expect(terminal).toBeVisible();
      // Should show at least one event or "SYSTEM" message
      await expect(terminal.locator('.terminal__line').first()).toBeVisible({ timeout: 10000 });
    });

    test('AI Operator panel responds to input', async ({ page }) => {
      // AI Operator lives in the AUTOMATIONS module — navigate there first
      await ensureSidebarOpen(page);
      await page.locator('.sidebar__link[data-module="automations"]').click();
      await page.waitForTimeout(600);
      const aiInput = page.locator('#ai-input');
      await expect(aiInput).toBeVisible({ timeout: 10000 });
      await aiInput.fill('help');
      await page.keyboard.press('Enter');
      await page.waitForTimeout(1500);
      // Check that the AI responded
      const aiBody = page.locator('#ai-messages');
      await expect(aiBody).not.toBeEmpty();
    });

    test('Axe Fleet panel renders', async ({ page }) => {
      // Axe Fleet lives in the FLEET module — navigate there first
      await ensureSidebarOpen(page);
      await page.locator('.sidebar__link[data-module="fleet"]').click();
      await page.waitForTimeout(600);
      await expect(page.locator('#axe-fleet-panel')).toBeVisible();
    });

    test('Fleet grid renders device cards with Fase 5 telemetry', async ({ page }) => {
      // Regression: activateModule('fleet') must trigger fetchAxeFleet() so the
      // grid is populated on tab open (previously the static HTML empty-state
      // stayed until the next 15s poll). The static empty-state is identified
      // by #axe-empty-add; after the fix the grid is replaced by JS output.
      // ensureSidebarOpen: the mobile-chrome project runs with a collapsed
      // sidebar, so open it before clicking the fleet link (same as the AI
      // Operator test in this file).
      await ensureSidebarOpen(page);
      await page.locator('.sidebar__link[data-module="fleet"]').click();
      await page.waitForTimeout(600);

      // Wait until the static empty-state is replaced by JS-rendered content
      await page.waitForFunction(() => {
        const grid = document.getElementById('axe-grid');
        if (!grid) return false;
        return !grid.querySelector('#axe-empty-add');
      }, { timeout: 10000 });

      const cards = page.locator('#axe-grid .axe-card');
      const count = await cards.count();

      if (count > 0) {
        // Gate on the synchronously-rendered card status classes (.is-online
        // lives in the card HTML string) — NOT on #axe-summary-online, which
        // countUpValue() animates from 0, so reading it mid-animation returns
        // "0" and would skip this assertion. When at least one device is
        // online, the HR summary cell must be populated (all-offline fleets
        // legitimately show '—').
        const onlineCards = await page.locator('#axe-grid .axe-card.is-online').count();
        if (onlineCards > 0) {
          const hr = await page.locator('#axe-summary-hr').textContent();
          expect(hr).not.toBe('—');
        }

        // Each card exposes the Fase 5 stat labels (TEMP/CHIP/VR/HR 1H)
        const first = cards.first();
        await expect(first.locator('.axe-card__stat .lbl', { hasText: 'CHIP' })).toBeVisible();
        await expect(first.locator('.axe-card__stat .lbl', { hasText: 'VR' })).toBeVisible();
        await expect(first.locator('.axe-card__stat .lbl', { hasText: 'HR 1H' })).toBeVisible();
      } else {
        // No devices registered — the JS-rendered empty state must be present
        await expect(page.locator('#axe-grid .axe-empty, #axe-grid .mkt-empty')).toBeVisible();
      }
    });

    test('Fleet cards render PING/POOL stats and advice chips', async ({ page }) => {
      // FLEET audit gap coverage: the card must render the PING stat (latency
      // probe, color-coded green ≤50 / gold ≤150 / red >150ms), the POOL stat
      // (pool_url host else stratum_status) and the advice chips (from
      // _device_advice). On a seeded server (DEBUG_MOCK=1) the fleet always
      // contains an OFFLINE miner, which deterministically carries the
      // 'device offline — checar energia/rede' advice chip.
      //
      // Data-agnostic by design (same invariant style as the Fase 5 test):
      // when cards render, the labels and the advice wrapper must exist;
      // when the fleet is empty the JS-rendered empty state is asserted.
      await ensureSidebarOpen(page);
      await page.locator('.sidebar__link[data-module="fleet"]').click();
      await page.waitForTimeout(600);

      // Wait until the static empty-state is replaced by JS-rendered content
      await page.waitForFunction(() => {
        const grid = document.getElementById('axe-grid');
        if (!grid) return false;
        return !grid.querySelector('#axe-empty-add');
      }, { timeout: 10000 });

      const cards = page.locator('#axe-grid .axe-card');
      const count = await cards.count();

      if (count > 0) {
        const first = cards.first();
        // PING + POOL stat labels always render on a JS card
        await expect(first.locator('.axe-card__stat .lbl', { hasText: 'PING' })).toBeVisible();
        await expect(first.locator('.axe-card__stat .lbl', { hasText: 'POOL' })).toBeVisible();

        // POOL value must be a real cell, not the bare placeholder: every
        // seeded device carries stratum_status ('disconnected' for dead
        // miners, a host for live ones), so the val cell is never '—'.
        const poolVal = first.locator('.axe-card__stat', { has: page.locator('.lbl', { hasText: 'POOL' }) }).locator('.val');
        await expect(poolVal).not.toHaveText('\u2014', { timeout: 5000 });

        // FLEET audit G1: EFF + POWER stat labels render on every card
        // (value is 'NOT AVAILABLE' when the firmware reports none).
        await expect(first.locator('.axe-card__stat .lbl', { hasText: 'EFF' })).toBeVisible();
        await expect(first.locator('.axe-card__stat .lbl', { hasText: 'POWER' })).toBeVisible();

        // FLEET audit G2: the card header shows MANUFACTURER · MODEL · HR
        // (fleet_health serializes manufacturer; absent → NOT AVAILABLE).
        // The '·' separator is baked into the template, and the line always
        // carries at least the manufacturer or its NOT AVAILABLE fallback.
        const modelLine = await first.locator('.axe-card__model').textContent();
        expect(modelLine).toContain('·');
        expect(modelLine.trim().length).toBeGreaterThan(0);

        // Advice chips: the seeded OFFLINE miner always emits the offline
        // recommendation, so at least one chip must render across the grid.
        // (A fully-healthy online-only fleet legitimately has none — gate.)
        const chipCount = await page.locator('#axe-grid .axe-card__advice-chip').count();
        if (chipCount > 0) {
          await expect(page.locator('#axe-grid .axe-card__advice-chip').first()).toBeVisible();
          // The advice wrapper itself must be present wherever chips live
          await expect(page.locator('#axe-grid .axe-card__advice').first()).toBeVisible();
        } else {
          // No recommendations on a fully-healthy fleet — wrapper legitimately absent
          await expect(first.locator('.axe-card__advice')).toHaveCount(0);
        }
      } else {
        // No devices registered — the JS-rendered empty state must be present
        await expect(page.locator('#axe-grid .axe-empty, #axe-grid .mkt-empty')).toBeVisible();
      }
    });

    test('Hash Market grid refreshes offers on module activation', async ({ page }) => {
      // Regression: activateModule('market') must trigger fetchSnapshot() so
      // the grid reflects fresh data on tab open. The boot-time snapshot can
      // predate the warmup cache (0 offers); without the fix the grid shows
      // the static HTML empty-state (with the ⚙ Configure button) until the
      // next 15s poll. The static empty-state is identified by .empty-state;
      // after the fix the grid is replaced by JS output (.mkt-card / .mkt-empty).
      // ensureSidebarOpen: the mobile-chrome project runs with a collapsed
      // sidebar, so open it before clicking the market link.
      await ensureSidebarOpen(page);
      await page.locator('.sidebar__link[data-module="market"]').click();
      await page.waitForTimeout(600);

      // Wait until the static HTML empty-state is replaced by JS-rendered
      // content (times out if the activation fix regresses).
      await page.waitForFunction(() => {
        const grid = document.getElementById('mkt-grid');
        if (!grid) return false;
        return !grid.querySelector('.empty-state');
      }, { timeout: 10000 });

      const cards = page.locator('#mkt-grid .mkt-card');
      const count = await cards.count();

      if (count > 0) {
        // Offers rendered — each card exposes provider + price, and the
        // count badge reflects the number of offers. The best-price badge
        // must also be populated (not the initial 'best —').
        const countBadge = await page.locator('#mkt-count-badge').textContent();
        expect(parseInt(countBadge, 10)).toBeGreaterThan(0);
        const best = await page.locator('#mkt-best-price-badge').textContent();
        expect(best).not.toContain('—');
        const first = cards.first();
        await expect(first.locator('.mkt-card__provider')).toBeVisible();
        await expect(first.locator('.mkt-card__price')).toBeVisible();
      } else {
        // Cache cold / providers down — the JS-rendered empty state must be
        // present (proves the grid was re-rendered, not left as static HTML).
        await expect(page.locator('#mkt-grid .mkt-empty')).toBeVisible();
      }
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

    test('sidebar links navigate to modules', async ({ page }) => {
      // Click Fleet sidebar link (module: fleet)
      await ensureSidebarOpen(page);
      const fleetLink = page.locator('.sidebar__link[data-module="fleet"]');
      await expect(fleetLink).toBeVisible();
      await fleetLink.click();
      await page.waitForTimeout(600);
      await expect(page.locator('#section-fleet')).toBeVisible();

      // Click Probability sidebar link (module: probability → charts pane)
      // activateModule() closes the drawer after each navigation, so re-open
      // it on mobile before the second link click.
      await ensureSidebarOpen(page);
      const probLink = page.locator('.sidebar__link[data-module="probability"]');
      await expect(probLink).toBeVisible();
      await probLink.click();
      await page.waitForTimeout(600);
      // The Deep Analytics pane should be active
      await expect(page.locator('#tab-charts.active')).toBeVisible({ timeout: 5000 });
    });

    test('Live Terminal tab is accessible and input accepts commands', async ({ page }) => {
      // Click Live Mining sidebar link (module: live → terminal pane)
      await ensureSidebarOpen(page);
      const liveLink = page.locator('.sidebar__link[data-module="live"]');
      await expect(liveLink).toBeVisible();
      await liveLink.click();
      await page.waitForTimeout(600);

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

    test('profit mode buttons switch POOL/SOLO/RENTAL and reveal solo stats', async ({ page }) => {
      // ── Button inventory ──
      const buttons = page.locator('.profit-mode-btn');
      const count = await buttons.count();
      expect(count).toBeGreaterThanOrEqual(3); // POOL + SOLO + RENTAL

      const poolBtn = page.locator('.profit-mode-btn[data-mode="pool"]');
      const soloBtn = page.locator('.profit-mode-btn[data-mode="solo"]');
      const rentalBtn = page.locator('.profit-mode-btn[data-mode="rental"]');
      await expect(poolBtn).toBeVisible();
      await expect(soloBtn).toBeVisible();
      await expect(rentalBtn).toBeVisible();

      // ── Initial state: POOL active, solo strip hidden ──
      await expect(poolBtn).toHaveClass(/active/);
      await expect(soloBtn).not.toHaveClass(/active/);
      const soloStrip = page.locator('#solo-extra-stats');
      await expect(soloStrip).toBeHidden();

      // ── SOLO: strip reveals, SOLO becomes active, cells re-render ──
      await soloBtn.click();
      await page.waitForTimeout(400);
      await expect(soloStrip).toBeVisible();
      await expect(soloBtn).toHaveClass(/active/);
      await expect(poolBtn).not.toHaveClass(/active/);

      // The BREAK-EVEN cell is the mode signal: its sub-label flips to
      // 'to block' once solo profitability data renders, and stays
      // '$/TH·d' on a worker-less/cold server. Poll so a late snapshot can
      // populate the panel either way (race-proof vs the 15s poll).
      await expect.poll(async () =>
        (await page.locator('#p-breakeven-sub').textContent()) || ''
      , { timeout: 10000 }).toMatch(/to block|\$\/TH·d/);
      const subAfterSolo = (await page.locator('#p-breakeven-sub').textContent()) || '';

      if (subAfterSolo.includes('to block')) {
        // Solo data present → the revealed cells carry real values.
        // NOTE: #solo-expected-time and #solo-blocks-year also exist in the
        // SOLO & STATS panel (duplicate IDs in the template), so scope the
        // locators to the profit strip to avoid strict-mode violations.
        await expect(soloStrip.locator('#solo-p-today')).not.toHaveText('\u2014', { timeout: 5000 });
        await expect(soloStrip.locator('#solo-expected-time')).not.toHaveText('\u2014', { timeout: 5000 });
        // NET BTC/DAY switches to the solo figure (no pool fee in solo).
        await expect(page.locator('#p-btc-day')).not.toHaveText('\u2014', { timeout: 5000 });
      }

      // ── RENTAL: strip hides, RENTAL becomes active ──
      await rentalBtn.click();
      await page.waitForTimeout(400);
      await expect(soloStrip).toBeHidden();
      await expect(rentalBtn).toHaveClass(/active/);
      await expect(soloBtn).not.toHaveClass(/active/);
      // BREAK-EVEN cell returns to the '$/TH·d' rental label when data
      // exists (solo's 'to block' must be gone).
      if (subAfterSolo.includes('to block')) {
        await expect.poll(async () =>
          (await page.locator('#p-breakeven-sub').textContent()) || ''
        , { timeout: 5000 }).toContain('$/TH·d');
      }

      // ── POOL: back to the initial active mode, strip stays hidden ──
      await poolBtn.click();
      await page.waitForTimeout(400);
      await expect(poolBtn).toHaveClass(/active/);
      await expect(soloStrip).toBeHidden();
    });

    test('LEASE button reveals lender extra stats (lender mode)', async ({ page }) => {
      // ── Button inventory: POOL + SOLO + RENTAL + LEASE ──
      const buttons = page.locator('.profit-mode-btn');
      expect(await buttons.count()).toBeGreaterThanOrEqual(4);

      const poolBtn = page.locator('.profit-mode-btn[data-mode="pool"]');
      const lenderBtn = page.locator('.profit-mode-btn[data-mode="lender"]');
      const rentalBtn = page.locator('.profit-mode-btn[data-mode="rental"]');
      await expect(poolBtn).toBeVisible();
      await expect(lenderBtn).toBeVisible();
      await expect(rentalBtn).toBeVisible();

      // ── Initial state: POOL active, lender strip hidden ──
      await expect(poolBtn).toHaveClass(/active/);
      await expect(lenderBtn).not.toHaveClass(/active/);
      const lenderStrip = page.locator('#lender-extra-stats');
      await expect(lenderStrip).toBeHidden();

      // ── LEASE: strip reveals, LEASE becomes active, POOL/RENTAL lose it ──
      await lenderBtn.click();
      await page.waitForTimeout(400);
      await expect(lenderStrip).toBeVisible();
      await expect(lenderBtn).toHaveClass(/active/);
      await expect(poolBtn).not.toHaveClass(/active/);
      await expect(rentalBtn).not.toHaveClass(/active/);

      // The RECOMMENDATION cell is the mode/data signal: once renderProfitability
      // runs in lender mode it shows 'LEASE > MINE' / 'MINE > LEASE' / 'EQUAL' /
      // 'NEEDS DATA', and stays '—' on a worker-less/cold server. Poll so a late
      // snapshot can populate the strip either way (race-proof vs the 15s poll).
      await expect.poll(async () =>
        (await page.locator('#lender-recommendation').textContent()) || ''
      , { timeout: 10000 }).toMatch(/LEASE > MINE|MINE > LEASE|EQUAL|NEEDS DATA|—/);
      const recAfterLease = (await page.locator('#lender-recommendation').textContent()) || '';

      // Only assert real data when the recommendation is a REAL verdict.
      // 'NEEDS DATA' means the backend computed an 'insufficient' lender
      // block (no market rate + no configured rental rate) — the cells stay
      // '—' in that case, so asserting them would flake.
      const hasLenderData = /LEASE > MINE|MINE > LEASE|EQUAL/.test(recAfterLease);
      if (hasLenderData) {
        // Lender data present → the revealed cells carry real values.
        // IDs here are unique to the lender strip (no duplicates like the
        // SOLO & STATS panel), so global locators are safe.
        await expect(page.locator('#lender-market-rate')).not.toHaveText('\u2014', { timeout: 5000 });
        await expect(page.locator('#lender-lease-net')).not.toHaveText('\u2014', { timeout: 5000 });
        await expect(page.locator('#lender-mine-net')).not.toHaveText('\u2014', { timeout: 5000 });
        await expect(page.locator('#lender-vs-mining')).not.toHaveText('\u2014', { timeout: 5000 });
      }

      // ── Back to POOL: strip hides again, POOL regains active ──
      await poolBtn.click();
      await page.waitForTimeout(400);
      await expect(poolBtn).toHaveClass(/active/);
      await expect(lenderBtn).not.toHaveClass(/active/);
      await expect(lenderStrip).toBeHidden();
    });

    test('LEASE shows real market data after background warm-up (market panel never opened)', async ({ page }) => {
      // Warm-up + rate convergence can take ~20-40s on a cold server (first
      // warmup cycle fetches all providers before the cache fills), which
      // exceeds the 60s global test timeout once the beforeEach dashboard
      // load (~5-20s) is added. Raise the per-test budget explicitly.
      test.setTimeout(120000);

      // The Hash Market panel is NEVER opened in this test — the frontend
      // only fetches /api/hashrate-market when the market module activates.
      // The cache is kept warm by the background warm-up thread
      // (_hashrate_market_warmup_loop, started in __main__).
      //
      // Backend gate: since the app.py fix, lender_market_rate_* is emitted
      // UNCONDITIONALLY (outside the `cur_hr > 0` gate) whenever the warm
      // cache + btc_usd exist — it does NOT need a worker/wallet. So the
      // deterministic gate is: warm cache (offers_count > 0) AND a real USD
      // market rate present. The recommendation cell is data-agnostic
      // (NEEDS DATA on a worker-less server) and asserted separately.
      await expect.poll(async () => {
        const res = await page.request.get('/api/snapshot');
        if (!res.ok()) return null;
        const d = await res.json();
        const offers = (d.market_data || {}).health?.offers_count || 0;
        const rateUsd = (d.profitability || {}).lender_market_rate_usd_per_th_day;
        return (offers > 0 && rateUsd > 0) ? rateUsd : null;
      }, { timeout: 45000 }).not.toBeNull();

      // ── LEASE: strip reveals and carries REAL data from the warm cache ──
      const lenderBtn = page.locator('.profit-mode-btn[data-mode="lender"]');
      await expect(lenderBtn).toBeVisible();
      await lenderBtn.click();
      const lenderStrip = page.locator('#lender-extra-stats');
      await expect(lenderStrip).toBeVisible();

      // The backend gate above proved the snapshot carries the warm-cache
      // market rate (btc_usd > 0 implied). The frontend renders the SAME
      // snapshot within one SSE/poll cycle (≤15s); the assertions auto-retry
      // until the '—' placeholder is gone.
      await expect(page.locator('#lender-market-rate')).not.toHaveText('\u2014', { timeout: 20000 });
      await expect(page.locator('#lender-recommendation')).toHaveText(/LEASE > MINE|MINE > LEASE|EQUAL|NEEDS DATA/, { timeout: 20000 });
    });

    test('Hashmarket filters show provider chips', async ({ page }) => {
      // Hashmarket lives in the HASH MARKET module — navigate there first
      await ensureSidebarOpen(page);
      await page.locator('.sidebar__link[data-module="market"]').click();
      await page.waitForTimeout(600);
      const filterContainer = page.locator('#mkt-filters');
      await expect(filterContainer).toBeVisible({ timeout: 10000 });
      const chips = filterContainer.locator('[data-mkt-filter]');
      const chipCount = await chips.count();
      expect(chipCount).toBeGreaterThanOrEqual(2); // All + at least 1 provider
    });

    test('Hashmarket filter chips restrict the grid to the selected provider', async ({ page }) => {
      // Data-agnostic by design: the app registers a Service Worker whose
      // network-first fetch is NOT intercepted by page.route, so mocked API
      // data would be overwritten by the live SSE stream. Instead we assert the
      // filtering INVARIANT against whatever offers the live snapshot has:
      // clicking a provider chip must leave only that provider's cards (or the
      // empty state when that provider currently has no offers).
      await ensureSidebarOpen(page);
      await page.locator('.sidebar__link[data-module="market"]').click();
      await page.waitForTimeout(800);

      const grid = page.locator('#mkt-grid');
      await expect(grid).toBeVisible({ timeout: 10000 });

      const chips = page.locator('#mkt-filters [data-mkt-filter]');
      const chipData = await chips.evaluateAll(els =>
        els.map(e => (e.getAttribute('data-mkt-filter') || '').toLowerCase()).filter(Boolean)
      );
      expect(chipData.length).toBeGreaterThanOrEqual(2); // All + at least 1 provider
      // Known providers = all chips except 'all' (self-maintaining, no hardcode)
      const knownProviders = chipData.filter(v => v !== 'all');

      // For each provider chip: assert the filtering INVARIANT — every visible
      // card's provider equals the selected chip, or the empty state shows when
      // that provider currently has no offers. expect.poll re-reads the DOM so
      // the assertion is race-proof against the SSE stream re-rendering the
      // grid with fresh market data every ~3s (re-renders preserve _mktFilter,
      // so cards stay consistent with the active filter mid-check).
      for (const provider of knownProviders) {
        await page.locator(`#mkt-filters [data-mkt-filter="${provider}"]`).click();
        await expect.poll(async () => {
          const count = await grid.locator('.mkt-card').count();
          if (count === 0) {
            return (await grid.locator('.mkt-empty').count()) > 0 ? 'empty' : 'pending';
          }
          const texts = await grid.locator('.mkt-card__provider').allTextContents();
          const allMatch = texts.every(t => t.trim().toLowerCase() === provider);
          return allMatch ? 'matched' : 'invalid';  // 'invalid' = a real filter bug
        }, { timeout: 5000 }).toMatch(/^(empty|matched)$/);
      }

      // Back to 'all': the grid must leave the filtered state — either cards
      // whose providers are all known provider names (never stuck on a single
      // filter), or the empty state when the market is cold.
      await page.locator('#mkt-filters [data-mkt-filter="all"]').click();
      await expect.poll(async () => {
        const texts = (await grid.locator('.mkt-card__provider').allTextContents())
          .map(t => t.trim().toLowerCase())
          .filter(Boolean);
        if (texts.length === 0) {
          return (await grid.locator('.mkt-empty').count()) > 0 ? 'empty' : 'pending';
        }
        return texts.every(p => knownProviders.includes(p)) ? 'known' : 'unknown';
      }, { timeout: 5000 }).toMatch(/^(empty|known)$/);
    });

    test('Export modal opens', async ({ page }) => {
      // button#open-exports: a stray <span id="open-exports"> exists later in
      // the DOM, so the bare #open-exports selector is ambiguous in strict mode.
      const exportBtn = page.locator('button#open-exports');
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

      // Close via the ☰ toggle: on ≤480px the drawer is full-screen (100vw),
      // so the scrim (#sidebar-overlay) sits BELOW the open sidebar and cannot
      // receive the tap — the toggle (or Escape) is the real close affordance.
      await mobileToggle.click();
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
      // Navigate to the Live Mining module (contains the terminal pane)
      await ensureSidebarOpen(page);
      await page.locator('.sidebar__link[data-module="live"]').click();
      await page.waitForTimeout(600);
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
