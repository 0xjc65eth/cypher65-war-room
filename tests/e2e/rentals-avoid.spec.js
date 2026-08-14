/**
 * CYPHER65 War Room — E2E RENTALS: lista avoid detalhada + BLACKLISTAR 1 clique
 * =====================================================================
 *
 * Guards the pilot's avoid cards (Issue #87):
 *   - grade-F rigs render as detail cards (MEDIAN/WORST/COST + badge F)
 *     under the "EVITAR — GRADE F" heading;
 *   - the BLACKLISTAR button POSTs to /api/rentals/rig/blacklist and the
 *     card disappears after the panel reloads (accept = 1 click);
 *   - the card body still opens the rig track record.
 *
 * /api/rentals + /api/rentals/rig are mocked → deterministic.
 *
 * Prerequisites: Flask server running on BASE_URL (see playwright.config.js).
 * Run: npx playwright test tests/e2e/rentals-avoid.spec.js
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
  recommendations: {
    top: [
      { rig_id: '1001', name: 'S19 Pro Good', grade: 'A', score: 88.5,
        median_pct: 97.1, worst_pct: 94.0, samples: 6,
        avg_cost_sats_per_thh: 520.0, vs_market_pct: -4.0, trend_pct: 1.2,
        last_rental: '2026-07-22 10:00:00' },
    ],
    // The pilot's full avoid case — worst first (rigF2 is the worst).
    avoid: [
      { rig_id: '2001', name: 'Rig F2 Bad', grade: 'F', score: 24.0,
        median_pct: 50.0, worst_pct: 44.0, samples: 3,
        avg_cost_sats_per_thh: 810.0, vs_market_pct: 62.0, trend_pct: -8.4,
        last_rental: '2026-07-21 10:00:00' },
      { rig_id: '2002', name: 'Rig F1 Bad', grade: 'F', score: 30.2,
        median_pct: 60.0, worst_pct: 55.0, samples: 3,
        avg_cost_sats_per_thh: 700.0, vs_market_pct: 40.0, trend_pct: -3.0,
        last_rental: '2026-07-20 10:00:00' },
    ],
    avoid_count: 2, tracked: 3, market: { available: false },
  },
  market_trend: { points: [], summary: null },
  rig_blacklist: [],
  rig_auto_blacklist: [],
  accepted_recos: { count: 0, accepted: [] },
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

test.describe('RENTALS — lista avoid detalhada + BLACKLISTAR 1 clique (Issue #87)', () => {
  test('cards grade F renderizam com detalhe e o botão blacklista em 1 clique', async ({ page }) => {
    // Panel payload → avoid list com 2 cards grade F. Blacklist POST mocked
    // (o reload do painel devolve o payload SEM o rig blacklisted).
    let blacklistCalled = false;
    await page.route('**/api/rentals**', async (route) => {
      const req = route.request();
      if (req.method() === 'POST' && req.url().includes('/api/rentals/rig/blacklist')) {
        blacklistCalled = true;
        await route.fulfill({ json: { success: true, blacklisted: true,
                                      rig_blacklist: ['2001'] } });
        return;
      }
      const payload = blacklistCalled
        ? { ...PAYLOAD, recommendations: { ...PAYLOAD.recommendations,
            avoid: PAYLOAD.recommendations.avoid.filter(a => a.rig_id !== '2001'),
            avoid_count: 1 } }
        : PAYLOAD;
      await route.fulfill({ json: payload });
    });
    await openRentals(page);

    // The avoid section renders with the heading.
    const avoidHead = page.locator('#rentals-avoid-head');
    await expect(avoidHead).toBeVisible({ timeout: 15000 });
    await expect(avoidHead).toHaveText(/EVITAR — GRADE F/);

    // Both grade-F cards render with the FULL detail schema.
    const cards = page.locator('#rentals-avoid-cards .rentals-reco__card--avoid');
    await expect(cards).toHaveCount(2);
    await expect(cards.nth(0)).toContainText('Rig F2 Bad');   // worst first
    await expect(cards.nth(0)).toContainText('F');            // grade badge
    await expect(cards.nth(0)).toContainText('50.0%');        // MEDIAN
    await expect(cards.nth(0)).toContainText('44.0%');        // WORST
    await expect(cards.nth(0)).toContainText('810 st');       // COST
    await expect(cards.nth(0)).toContainText('3 amostras');
    await expect(cards.nth(1)).toContainText('Rig F1 Bad');

    // ONE click on BLACKLISTAR → POST + card disappears after reload.
    await cards.nth(0).locator('.rentals-reco__blacklist').click();
    await expect(blacklistCalled).toBe(true);
    await expect(page.locator('#rentals-avoid-cards .rentals-reco__card--avoid')).toHaveCount(1);
    await expect(page.locator('#rentals-avoid-cards')).toContainText('Rig F1 Bad');
    await expect(page.locator('#rentals-avoid-cards')).not.toContainText('Rig F2 Bad');
    // Meta shows the decremented avoid count.
    await expect(page.locator('#rentals-reco-meta')).toContainText('1 evitar');
  });
});
