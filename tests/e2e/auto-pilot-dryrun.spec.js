/**
 * CYPHER65 War Room — E2E Auto-Pilot DRY-RUN (Issue #76 · Fase 3)
 * ==============================================================
 *
 * Guards the DRY-RUN panel in the AUTOMATIONS module:
 *
 *   - Panel renders with the "SIMULAÇÃO" badge (nothing executes).
 *   - SIMULAR loads /api/automation/dry-run (now) + /dry-run/replay (24h).
 *   - Each simulated action card shows the predicted outcome, the condition
 *     (actual vs threshold), and the Safety verdict chips (APROVADO /
 *     BLOQUEADO) — with NO real execution anywhere.
 *   - Replay rows show how many times each rule WOULD have fired.
 *
 * Endpoint mocks make the test deterministic and independent of real rules.
 * NOTE: serviceWorkers must be 'block' (learned in live-mining.spec.js).
 *
 * Run:  npx playwright test tests/e2e/auto-pilot-dryrun.spec.js
 */

import { test, expect } from '@playwright/test';

test.use({ serviceWorkers: 'block' });

test.describe('Auto-Pilot dry-run — simulação do piloto (Issue #76)', () => {
  /** Open the dashboard and land on the Automations module. */
  async function openAutomations(page) {
    await page.goto('/');
    await page.waitForSelector('#app-shell', { timeout: 15000 });
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
    await page.click('.sidebar__link[data-module="automations"]');
    await expect(page.locator('#ap-dryrun-panel')).toBeVisible({ timeout: 8000 });
  }

  test('dry-run panel renders simulated actions with outcomes and replay', async ({ page }) => {
    // ── Deterministic API mocks (now + replay) ──
    await page.route(/\/api\/automation\/dry-run(\?|$)/, async (route) => {
      await route.fulfill({
        contentType: 'application/json',
        body: JSON.stringify({
          simulated: true, armed: false, count: 2, would_execute: 1,
          budget_remaining: true, max_actions_per_window: 10,
          action_window_seconds: 900,
          actions: [
            {
              rule_id: 1, rule_name: 'restart-quente', device_id: 'dev-1',
              device_name: 'Garage Bitaxe', condition_metric: 'temperature',
              condition_operator: '>', condition_value: 70, actual_value: 75,
              action_command: 'restart',
              predicted_outcome: 'ASIC reinicia — hashrate volta ao normal em ~60-120s (janela curta de offline durante o reboot)',
              safety_verdict: 'approved', safety_reason: '',
              budget: 'would_consume', conflict: null,
            },
            {
              rule_id: 2, rule_name: 'cool-fan', device_id: 'dev-1',
              device_name: 'Garage Bitaxe', condition_metric: 'temperature',
              condition_operator: '>', condition_value: 70, actual_value: 75,
              action_command: 'underclock',
              predicted_outcome: 'Frequência/voltagem caem — temperatura e consumo reduzem (hashrate menor)',
              safety_verdict: 'blocked', safety_reason: 'Temperature too high',
              budget: 'would_consume', conflict: null,
            },
          ],
        }),
      });
    });
    await page.route(/\/api\/automation\/dry-run\/replay(\?|$)/, async (route) => {
      await route.fulfill({
        contentType: 'application/json',
        body: JSON.stringify({
          simulated: true, window_hours: 24, samples: 288, total_fires: 17,
          total_rate_limited: 3,
          per_rule: [
            { rule_id: 1, rule_name: 'restart-quente', device_id: 'dev-1',
              device_name: 'Garage Bitaxe', action_command: 'restart',
              fires: 12, rate_limited: 2, first_ts: 1700000000,
              last_ts: 1700086400 },
            { rule_id: 2, rule_name: 'cool-fan', device_id: 'dev-1',
              device_name: 'Garage Bitaxe', action_command: 'underclock',
              fires: 5, rate_limited: 1, first_ts: 1700000600,
              last_ts: 1700086400 },
          ],
        }),
      });
    });

    await openAutomations(page);

    // Panel + badge: simulation, not execution.
    await expect(page.locator('#ap-dr-badge')).toContainText('SIMULAÇÃO');
    await expect(page.locator('.ap-dr-banner')).toContainText('sem executar nada');

    // SIMULAR triggers both endpoints → action cards render.
    await page.click('#ap-dr-refresh');
    await expect(page.locator('#ap-dr-now-list .ap-dr-card')).toHaveCount(2, { timeout: 8000 });
    await expect(page.locator('#ap-dr-now-list .ap-dr-card').first()).toContainText('restart-quente');
    await expect(page.locator('#ap-dr-now-list .ap-dr-card').first()).toContainText('ASIC reinicia');
    await expect(page.locator('#ap-dr-now-list .ap-dr-card').first()).toContainText('safety: APROVADO');

    // Blocked action surfaces the Safety verdict + motivo.
    await expect(page.locator('#ap-dr-now-list .ap-dr-card').nth(1)).toContainText('safety: BLOQUEADO');

    // Replay 24h: per-rule would-fire counts.
    await expect(page.locator('#ap-dr-replay-list .ap-dr-replay__row')).toHaveCount(2);
    await expect(page.locator('#ap-dr-replay-count')).toContainText('17 disparos');
    await expect(page.locator('#ap-dr-replay-list .ap-dr-replay__row').first()).toContainText('12×');
  });
});
