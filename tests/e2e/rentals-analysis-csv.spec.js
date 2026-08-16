// E2E: Rentals ANALYSIS export chip (Controle de Rendimento).
// Verifies the '📊 ANÁLISE' chip triggers a CSV download and the
// simple CSV chip still works (mode=simple is the default).
import { test, expect } from '@playwright/test';

const PASSWORD = 'Test1234!';

// Realistic MRR payloads for the mocked /api/rentals + /api/rentals/export.
const RENTALS_PAYLOAD = {
  success: true, needs_auth: false,
  rentals: [
    {
      id: '5657736', owner: 'almansoorii', renter: 'cypher',
      hashrate: {
        advertised: { hash: '0.165', type: 'ph', nice: '165.00T' },
        average: { hash: '0.15932150061561', type: 'ph', nice: '159.32T', percent: '96.56' },
      },
      price: { type: 'legacy', advertised: '0.00000000', paid: '0.00001404', currency: 'BTC' },
      length: '3.85', extended: '0', extensions: [],
      start: '2026-07-25 19:17:20 UTC', end: '2026-07-25 23:08:20 UTC',
      start_unix: '1785007040', end_unix: '1785020900', ended: true,
      rig: { id: '376882', name: 'A02 165TH', type: 'sha256ab',
             status: { status: 'available', rented: false, online: true },
             online: true, region: 'eu-de', rpi: '100.00' },
    },
  ],
  total: 1,
  provider_stats: { rentals: 1 },
};

// /api/rentals carries the blocks the RENTALS tab renders.
const RENTALS_TAB_PAYLOAD = {
  success: true, needs_auth: false,
  active: [], history: [], owner: [], contracts: [],
  recommendations: { top: [], avoid_count: 0, tracked: 0, market: { available: false } },
  accepted_recos: { count: 0, accepted: [] },
  market_trend: { points: [] },
  rig_blacklist: [], rig_auto_blacklist: [],
  series: { week: [], month: [] },
  providers: [],
  portfolio: {},
};

test.describe('Rentals analysis export', () => {
  test.use({ storageState: { cookies: [], origins: [] } });

  async function login(page) {
    await page.goto('/');
    // Open mode: the dashboard may boot without auth; if a login wall is
    // shown, register/log in with a fresh user.
    const loginBtn = page.locator('text=Entrar').first();
    if (await loginBtn.isVisible({ timeout: 3000 }).catch(() => false)) {
      await page.goto('/login');
      const email = `audit_${Date.now()}@test.com`;
      await page.fill('#username', email);
      await page.fill('#password', PASSWORD);
      const register = page.locator('button:has-text("Registrar")').first();
      if (await register.isVisible({ timeout: 2000 }).catch(() => false)) {
        await register.click();
      } else {
        await page.locator('button:has-text("Entrar")').first().click();
      }
      await page.waitForURL(/dashboard|localhost:8765\//, { timeout: 15000 });
    }
  }

  async function routeMocks(page, { exportMode } = {}) {
    await page.route('**/api/rentals', async (route) => {
      await route.fulfill({ json: RENTALS_TAB_PAYLOAD });
    });
    await page.route('**/api/rentals/export*', async (route) => {
      const url = route.request().url();
      const isAnalysis = url.includes('mode=analysis');
      if (exportMode && !url.includes('mode=analysis')) {
        // When testing the analysis chip, keep the simple route intact but
        // still serve it (no assertion on its content).
      }
      if (isAnalysis) {
        const csv = [
          'id,provider,status,start,end,length_hours,blacklisted,advertised_th,avg_th,delivery_pct,min_acceptable_delivery,performance_ok,cancelled_by_performance,paid_sats,refund_sats,expected_refund_sats,refund_pending_sats,cost_sats_per_thh,market_sats_per_thh,spread_sats,spread_pct,effective_cost_sats,loss_sats,loss_after_refund_sats,roi_pct,seller_reliability_score,risk_score,efficiency_score,should_blacklist,auto_action,notes',
          '5657736,mrr,completed,2026-07-25 19:17:20 UTC,2026-07-25 23:08:20 UTC,3.85,,165.0,159.32,96.56,90.0,1,,1404,,,,,,,,,,,,,,96.56,,ok,',
          '',
        ].join('\n');
        await route.fulfill({
          status: 200,
          contentType: 'text/csv',
          headers: { 'Content-Disposition': 'attachment; filename=rentals_analysis_operator_1785007040.csv' },
          body: '\ufeff' + csv,
        });
      } else {
        const csv = [
          'provider,id,bucket,start,end,length_hours,avg_th,advertised_th,delivery_pct,paid_sats,cost_sats_per_thh,blacklisted',
          'mrr,5657736,active,2026-07-25 19:17:20 UTC,2026-07-25 23:08:20 UTC,3.85,159.32,165.0,96.56,1404,,',
          '',
        ].join('\n');
        await route.fulfill({
          status: 200,
          contentType: 'text/csv',
          headers: { 'Content-Disposition': 'attachment; filename=rentals_operator_1785007040.csv' },
          body: '\ufeff' + csv,
        });
      }
    });
  }

  test('ANÁLISE chip downloads the yield-control CSV', async ({ page }) => {
    await login(page);
    await routeMocks(page, { exportMode: 'analysis' });
    await page.goto('/');

    // Open the RENTALS tab (nav).
    await page.locator('nav a:has-text("Rentals"), [data-module="rentals"]').first().click();
    const analysisChip = page.locator('#rentals-export-analysis');
    await expect(analysisChip).toBeVisible({ timeout: 15000 });

    // Click → the CSV download is triggered.
    const [download] = await Promise.all([
      page.waitForEvent('download', { timeout: 15000 }),
      analysisChip.click(),
    ]);
    expect(download.suggestedFilename()).toContain('rentals_analysis');
  });

  test('CSV chip still downloads the simple ledger', async ({ page }) => {
    await login(page);
    await routeMocks(page, {});
    await page.goto('/');
    await page.locator('nav a:has-text("Rentals"), [data-module="rentals"]').first().click();
    const csvChip = page.locator('#rentals-export');
    await expect(csvChip).toBeVisible({ timeout: 15000 });
    const [download] = await Promise.all([
      page.waitForEvent('download', { timeout: 15000 }),
      csvChip.click(),
    ]);
    expect(download.suggestedFilename()).toContain('rentals');
  });
});
