/**
 * CYPHER65 War Room — E2E RENTALS: recomendações ACEITAS (Issue #78)
 * ==================================================================
 *
 * Guards the new "RECOMENDAÇÕES ACEITAS" block in the RENTALS panel:
 *   - renders rigs the operator blacklisted after the pilot flagged them
 *     (source badge MANUAL/AUTO + acceptance date);
 *   - shows the delivery outcome AFTER the decision (EVITADO / MELHOROU /
 *     PIOROU verdicts with 'entrega antes → depois');
 *   - clicking a card opens the rig track record modal;
 *   - hides when there are no accepted recommendations.
 *
 * /api/rentals + /api/rentals/rig are mocked → deterministic, no real
 * MRR/Braiins credentials needed.
 *
 * NOTE: serviceWorkers must be 'block' — static/sw.js fetches bypass
 * page.route (learned in tests/e2e/live-mining.spec.js).
 *
 * Prerequisites: Flask server running on BASE_URL (see playwright.config.js).
 * Run: npx playwright test tests/e2e/rentals-accepted.spec.js
 */
import { test, expect } from '@playwright/test';

test.use({ serviceWorkers: 'block' });

const ACCEPTED_PAYLOAD = {
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
  rig_blacklist: ['376882', '401234'],
  rig_auto_blacklist: ['401234'],
  accepted_recos: {
    count: 2,
    accepted: [
      { rig_id: '376882', name: 'Antminer S19 Pro', ts: 1800000000,
        source: 'manual', delivery_pct: 74.5, samples: 6, grade: 'F',
        pilot_flagged: true, delivery_after_pct: null,
        cost_after_sats_per_thh: null, verdict: 'avoided' },
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

const RIG_PAYLOAD = {
  trust: { grade: 'F', label: 'AVOID', median_pct: 74.5, samples: 6 },
  summary: { rig_id: '376882', name: 'Antminer S19 Pro', rentals: 6,
             avg_delivery_pct: 74.5 },
  history: [],
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

test.describe('RENTALS — recomendações aceitas (Issue #78)', () => {
  test('bloco renderiza verdicts + clique abre track record', async ({ page }) => {
    await page.route('**/api/rentals**', async (route) => {
      await route.fulfill({ json: ACCEPTED_PAYLOAD });
    });
    await page.route('**/api/rentals/rig**', async (route) => {
      await route.fulfill({ json: RIG_PAYLOAD });
    });
    await openRentals(page);

    const block = page.locator('#rentals-accepted');
    await expect(block).toBeVisible({ timeout: 15000 });

    // Meta: '2 aceitas · 1 evitada'
    await expect(page.locator('#rentals-accepted-meta')).toContainText('2 aceitas');

    // Two cards with names + verdicts + source badges
    await expect(page.locator('#rentals-accepted-list .rentals-accepted__card')).toHaveCount(2);
    await expect(page.locator('#rentals-accepted-list')).toContainText('Antminer S19 Pro');
    await expect(page.locator('#rentals-accepted-list')).toContainText('WhatsMiner M30S');
    await expect(page.locator('#rentals-accepted-list')).toContainText('EVITADO');
    await expect(page.locator('#rentals-accepted-list')).toContainText('MELHOROU');
    await expect(page.locator('#rentals-accepted-list .rentals-accepted__src.is-manual')).toHaveCount(1);
    await expect(page.locator('#rentals-accepted-list .rentals-accepted__src.is-auto')).toHaveCount(1);
    // Honest framing: a blacklisted rig the pilot never flagged renders
    // 'não sugerido' (not an accepted recommendation).
    await expect(page.locator('#rentals-accepted-list .rentals-accepted__src.is-ns')).toHaveCount(1);
    await expect(page.locator('#rentals-accepted-list')).toContainText('NÃO SUGERIDO');

    // Click a card → rig track record modal opens (title = rig name, body
    // shows the trust verdict from the rig endpoint).
    await page.click('#rentals-accepted-list .rentals-accepted__card >> nth=0');
    await expect(page.locator('#rentals-rig-modal')).toHaveClass(/active/, { timeout: 10000 });
    await expect(page.locator('#rentals-rig-modal-title')).toContainText('Antminer S19 Pro', { timeout: 10000 });
    await expect(page.locator('#rentals-rig-modal-body')).toContainText('6 amostras', { timeout: 10000 });
  });

  test('bloco oculto quando não há aceitas', async ({ page }) => {
    const payload = JSON.parse(JSON.stringify(ACCEPTED_PAYLOAD));
    payload.accepted_recos = { count: 0, accepted: [] };
    await page.route('**/api/rentals**', async (route) => {
      await route.fulfill({ json: payload });
    });
    await openRentals(page);
    // Wait for the module fetch + render pass to settle.
    await expect(page.locator('#rentals-list .empty-state')).toBeVisible({ timeout: 15000 });
    await page.waitForTimeout(800);
    await expect(page.locator('#rentals-accepted')).toBeHidden();
  });
});
