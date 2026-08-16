/**
 * CYPHER65 War Room — E2E RENTALS: veredito REVOGADA (Issue #84)
 * ==================================================================
 *
 * Guards the 'restored' marker on accepted-recommendation entries:
 *   - a ledger entry with restored=true renders the REVOGADA verdict
 *     (decision was reversed, not evaluated by the delivery afterwards);
 *   - the tooltip explains the reversal.
 *
 * /api/rentals + /api/rentals/rig are mocked → deterministic.
 *
 * Prerequisites: Flask server running on BASE_URL (see playwright.config.js).
 * Run: npx playwright test tests/e2e/rentals-accepted-restored.spec.js
 */
import { test, expect } from '@playwright/test';

test.use({ serviceWorkers: 'block' });

const PAYLOAD = {
  success: true,
  updated_at: 1800000000,
  mrr: {
    needs_auth: false, active: [], history: [], owner: [],
    total_active: 0, total_history: 2, total_owner: 0, error: null,
  },
  braiins: { needs_auth: false, contracts: [], error: null },
  portfolio: {
    spend: { count: 2, spent_sats: 12000, delivered_thh: 4.2,
             avg_cost_sats_per_thh: 2857.1, avg_delivery_pct: 91.0 },
    income: { count: 0, spent_sats: 0 },
    split: { mrr: 2, braiins: 0 },
    counts: { active: 0, history: 2, owner: 0, contracts: 0 },
  },
  portfolio_series: { bucket: 'week', estimate: true, points: [], totals: {} },
  recommendations: { top: [], avoid_count: 1, tracked: 2, market: { available: false } },
  market_trend: { points: [], summary: null },
  rig_blacklist: [],
  rig_auto_blacklist: [],
  accepted_recos: {
    count: 2,
    accepted: [
      // REVOKED: the operator restored this rig after blacklisting it —
      // verdict must read 'revoked', NOT the delivery outcome after.
      { rig_id: '376882', name: 'Antminer S19 Pro', ts: 1800000000,
        source: 'manual', delivery_pct: 74.5, samples: 6, grade: 'F',
        pilot_flagged: true, restored: true, restored_ts: 1801000000,
        delivery_after_pct: 95.2, cost_after_sats_per_thh: 3100.0,
        verdict: 'revoked' },
      // Still accepted (never restored) — verdict derives from delivery.
      { rig_id: '401234', name: 'WhatsMiner M30S', ts: 1790000000,
        source: 'auto', delivery_pct: 80.0, samples: 4, grade: 'D',
        pilot_flagged: false, delivery_after_pct: 95.2,
        cost_after_sats_per_thh: 3100.0, verdict: 'improved' },
    ],
  },
  provider_rankings: [], rig_heatmap: [], expiring: [],
  worst_rigs: { worst: [], count: 0 },
  concentration: { available: false },
  difficulty_forecast: { available: false },
  risk_alerts_fired: [], market_signals: { overpay: [], arbitrage: [] },
};

/** Open the dashboard and land on the RENTALS module. */
async function openRentals(page) {
  await page.goto('/');
  await page.waitForSelector('#sidebar', { timeout: 25000 });
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
  await page.click('.sidebar__link[data-module="rentals"]');
}

test.describe('RENTALS — veredito REVOGADA (Issue #84)', () => {
  test('restored entry renders REVOGADA with the reversal tooltip', async ({ page }) => {
    await page.route('**/api/rentals**', async (route) => {
      await route.fulfill({ json: PAYLOAD });
    });
    await openRentals(page);

    const block = page.locator('#rentals-accepted');
    await expect(block).toBeVisible({ timeout: 15000 });

    // Both cards render; the restored one carries the REVOGADA verdict.
    await expect(page.locator('#rentals-accepted-list .rentals-accepted__card')).toHaveCount(2);
    const list = page.locator('#rentals-accepted-list');
    await expect(list).toContainText('REVOGADA');
    await expect(list).toContainText('MELHOROU');  // the non-restored one

    // The REVOGADA verdict carries the honest tooltip.
    const revoked = page.locator('#rentals-accepted-list .rentals-accepted__verdict.is-warn');
    await expect(revoked).toHaveCount(1);
    await expect(revoked).toHaveText('REVOGADA');
    await expect(revoked).toHaveAttribute('title', /revogada/);

    // Delivery-outcome fields still shown for reference (antes → depois).
    await expect(list).toContainText('74.5% → 95.2%');
  });
});
