/**
 * CYPHER65 War Room — E2E Auto-Pilot ADVISORY panel (Issue #20 · Fase 2)
 * ======================================================================
 *
 * Guards the per-device advisory recommendations in the AUTOMATIONS
 * module (AUTO-PILOT · ADVISORY MODE panel):
 *
 *   - Recommendations render as cards (one per issue/device) with a
 *     safe review + IGNORAR button each.
 *   - Reviewing records intent, fires POST
 *     /api/auto-pilot/recommendations/<id>/respond {decision:"accept"},
 *     and navigates to Fleet without executing a command.
 *   - Ignoring fires the same endpoint with {decision:"ignore"} and the
 *     audit trail appears in the AUDIT TRAIL · DECISÕES block.
 *
 * Endpoint mocks make the test deterministic (no axe registry, no real
 * fleet, no tenant auth).
 *
 * NOTE: serviceWorkers must be 'block' — static/sw.js fetches bypass
 * page.route (learned in tests/e2e/live-mining.spec.js).
 *
 * Prerequisites: Flask server running on BASE_URL (see playwright.config.js).
 *
 * Run:  npx playwright test tests/e2e/auto-pilot-advisory.spec.js
 */

import { test, expect } from '@playwright/test';

test.use({ serviceWorkers: 'block' });

test.describe('Auto-Pilot advisory — automations panel', () => {
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
    await expect(page.locator('#ap-advisory-panel')).toBeVisible({ timeout: 8000 });
  }

  test('renders recommendations with apply/ignore + audited trail', async ({ page }) => {
    const mockRecs = [
      {
        id: 'ap-offline-dev-1',
        device_id: 'dev-1',
        device_name: 'MINER-1',
        issue_type: 'offline',
        severity: 'crit',
        message: 'MINER-1 está OFFLINE — sem hashrate reportado.',
        action: { type: 'restart', label: 'REINICIAR' },
      },
      {
        id: 'ap-temp_high-dev-2',
        device_id: 'dev-2',
        device_name: 'MINER-2',
        issue_type: 'temp_high',
        severity: 'warn',
        message: 'MINER-2 a 81°C (limite 75°C) — risco térmico.',
        action: { type: 'pause', label: 'PAUSAR' },
      },
    ];
    let auditRows = [];
    let responded = [];

    await page.route(/\/api\/auto-pilot\/recommendations(\/audit)?(\?|$)/, async (route) => {
      const url = route.request().url();
      if (url.includes('/audit')) {
        await route.fulfill({ json: { audit: auditRows, count: auditRows.length } });
        return;
      }
      await route.fulfill({ json: { recommendations: mockRecs, count: mockRecs.length, armed: false } });
    });
    await page.route(/\/api\/auto-pilot\/recommendations\/[^/]+\/respond(\?|$)/, async (route) => {
      const body = route.request().postDataJSON ? route.request().postDataJSON() : {};
      const recId = decodeURIComponent(route.request().url().split('/recommendations/')[1].split('/')[0]);
      responded.push({ recId, decision: body.decision });
      auditRows.push({
        ts: Math.floor(Date.now() / 1000),
        device_name: recId.includes('temp') ? 'MINER-2' : 'MINER-1',
        issue_type: recId.includes('temp') ? 'temp_high' : 'offline',
        action_type: recId.includes('temp') ? 'pause' : 'restart',
        decision: body.decision,
      });
      await route.fulfill({
        json: {
          success: true,
          recorded: true,
          decision: body.decision,
          action_type: recId.includes('temp') ? 'pause' : 'restart',
          advisory_only: true,
          executed: false,
          navigate_to: body.decision === 'accept' ? 'fleet' : null,
          open_buy_flow: false,
          action_result: body.decision === 'accept'
            ? { ok: true, executed: false, reason: 'advisory_only', navigate_to: 'fleet' }
            : null,
        },
      });
    });
    // Snapshot proxy: keep auto_pilot.armed false so the render is stable.
    await page.route(/\/api\/snapshot(\?|$)/, async (route) => {
      const resp = await page.request.get(route.request().url());
      const body = await resp.json();
      body.auto_pilot = body.auto_pilot || {};
      body.auto_pilot.armed = false;
      await route.fulfill({ json: body });
    });

    await openAutomations(page);

    // ── Both mock recommendations render as cards ──
    await expect(page.locator('#ap-recs-badge')).toHaveText('2');
    await expect(page.locator('.ap-rec')).toHaveCount(2);
    await expect(page.locator('.ap-rec').first()).toContainText('MINER-1');
    await expect(page.locator('.ap-rec').first()).toContainText('REVISAR NO FLEET');
    await expect(page.locator('.ap-rec').nth(1)).toContainText('REVISAR NO FLEET');

    // ── Ignore: fires respond with ignore + audit trail appears ──
    await page.locator('.ap-rec').first().locator('.ap-rec-ignore').click();
    await expect(page.locator('#ap-audit-wrap')).toBeVisible();
    await expect(page.locator('#ap-audit-list')).toContainText('IGNORADO');
    await expect(page.locator('#ap-audit-list')).toContainText('MINER-1');
    expect(responded).toEqual([
      { recId: 'ap-offline-dev-1', decision: 'ignore' },
    ]);

    // ── Review: records accept and navigates; no command dialog/dispatch ──
    let dialogOpened = false;
    page.on('dialog', async (dialog) => {
      dialogOpened = true;
      await dialog.dismiss();
    });
    await page.locator('.ap-rec').nth(1).locator('.ap-rec-apply').click();
    await expect(page.locator('#ap-audit-list')).toContainText('ACEITO');
    await expect(page.locator('#ap-audit-list')).toContainText('MINER-2');
    await expect(page.locator('.sidebar__link[data-module="fleet"]')).toHaveClass(/active/);
    await expect(page.locator('#axe-fleet-panel')).toBeVisible();
    expect(dialogOpened).toBe(false);
    expect(responded).toEqual([
      { recId: 'ap-offline-dev-1', decision: 'ignore' },
      { recId: 'ap-temp_high-dev-2', decision: 'accept' },
    ]);

    // ── Empty state when there are no recommendations ──
    await page.route(/\/api\/auto-pilot\/recommendations(\?|$)/, async (route) => {
      await route.fulfill({ json: { recommendations: [], count: 0, armed: false } });
    });
    await openAutomations(page);
    await page.click('#ap-recs-refresh');
    await expect(page.locator('#ap-recs-badge')).toHaveText('0');
    await expect(page.locator('#ap-recs-list')).toContainText('Sem recomendações');
  });
});
