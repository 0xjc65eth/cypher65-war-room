/**
 * CYPHER65 War Room — Operational Overview (#367)
 *
 * The first test uses the real project endpoints. Deterministic route
 * injection is reserved for UI branches (critical/offline and 503) that the
 * local machine cannot safely reproduce with physical hardware. Backend loss
 * math is covered against the real Flask route in Python integration tests.
 */

import { test, expect } from '@playwright/test';

test.use({ serviceWorkers: 'block' });

async function realSnapshotWith(page, overrides) {
  const response = await page.request.get('/api/snapshot');
  expect(response.ok()).toBeTruthy();
  const snapshot = await response.json();
  return Object.assign(snapshot, overrides || {});
}

test.describe('Operational Overview — real data and critical states', () => {
  test('real endpoints leave loading and expose all six decision signals without overflow', async ({ page }) => {
    await page.goto('/');
    const overview = page.locator('#operational-overview');
    await expect(overview).toBeVisible({ timeout: 15000 });
    await expect(overview).toHaveAttribute('aria-busy', 'false', { timeout: 15000 });
    await expect(page.locator('#op-overall-status')).not.toHaveText('LOADING');

    for (const selector of [
      '#op-health', '#op-attention', '#op-lost-hashrate', '#op-cost',
      '#op-freshness', '#op-action-title',
    ]) {
      await expect(page.locator(selector)).toBeVisible();
      await expect(page.locator(selector)).not.toBeEmpty();
    }
    await expect(overview.locator('.skel')).toHaveCount(0);
    await expect(page.locator('#op-evidence-coverage')).toContainText('/5 domains fully observed');
    for (const domain of ['MINING', 'FLEET', 'POOL', 'DATA', 'ECONOMICS']) {
      await expect(page.locator('.op-evidence__domain').filter({ hasText: domain })).toBeVisible();
    }
    await expect(page.locator('#op-evidence-limits')).toContainText('No cause inferred');

    const box = await overview.boundingBox();
    const viewport = page.viewportSize();
    expect(box).not.toBeNull();
    expect(box.x).toBeGreaterThanOrEqual(0);
    expect(box.x + box.width).toBeLessThanOrEqual(viewport.width + 1);

    // Desktop is a compact 3-column scan; the mobile project stacks cards.
    const columns = await page.locator('.operational-overview__grid').evaluate((node) =>
      getComputedStyle(node).gridTemplateColumns.split(' ').length
    );
    expect(columns).toBe(test.info().project.name === 'mobile-chrome' ? 2 : 5);
    const evidenceColumns = await page.locator('.op-evidence__domains').evaluate((node) =>
      getComputedStyle(node).gridTemplateColumns.split(' ').length
    );
    expect(evidenceColumns).toBe(test.info().project.name === 'mobile-chrome' ? 1 : 5);

    const networkEvidence = page.locator('.op-evidence__domain').filter({ hasText: 'DATA' }).getByRole('button', { name: 'Open evidence' });
    await expect(networkEvidence).toBeVisible();
    await networkEvidence.click();
    await expect(page.locator('#network-panel')).toBeVisible({ timeout: 5000 });
  });

  test('offline ASIC shows measured loss and CTA only navigates to Fleet', async ({ page }) => {
    const dangerousRequests = [];
    page.on('request', (request) => {
      if (request.method() !== 'GET' && /\/(restart|pause|resume|power-cycle|config|command)(\/|\?|$)/.test(request.url())) {
        dangerousRequests.push(request.method() + ' ' + request.url());
      }
    });

    await page.route(/\/api\/snapshot(?:\?|$)/, async (route) => {
      const snapshot = await realSnapshotWith(page, {
        ts: Math.floor(Date.now() / 1000),
        profitability: {
          cost_model_configured: true,
          cost_per_day_usd: 8.5,
          cost_label: '$0.1000/kWh power (3500W)',
        },
        operations_overview: {
          schema_version: 1,
          status: 'partial',
          domains: [
            { id: 'mining', label: 'MINING', status: 'observed', source: 'test pool worker', signals: [{ name: 'worker_hashrate', value: 4e12, unit: 'H/s', source: 'test.worker.hashrate', age_seconds: 20, window: 'point sample' }], missing_signals: [], evidence_target: 'hero-worker' },
            { id: 'fleet', label: 'FLEET', status: 'partial', source: 'test fleet', signals: [{ name: 'device_status_counts', value: { ONLINE: 1, OFFLINE: 1 }, source: 'test fleet status', age_seconds: 20, window: 'point-in-time' }], missing_signals: [], evidence_target: 'axe-fleet-panel' },
            { id: 'pool', label: 'POOL', status: 'observed', source: 'test pool', signals: [{ name: 'pool_hashrate', value: 4e12, unit: 'H/s', source: 'test.pool.hashrate', age_seconds: 20, window: 'point sample' }], missing_signals: [], evidence_target: 'pool-overview' },
            { id: 'data', label: 'DATA', status: 'partial', source: 'test data', signals: [], missing_signals: ['network data'], evidence_target: 'network-panel' },
            { id: 'economics', label: 'ECONOMICS', status: 'observed', source: 'test cost model', signals: [{ name: 'cost_model_configured', value: true, source: 'test.profitability', age_seconds: 20, window: 'configuration' }, { name: 'configured_cost_per_day', value: 8.5, unit: 'USD/day', source: 'test.profitability.cost_per_day_usd', age_seconds: 20, window: 'per-day estimate' }], missing_signals: [], evidence_target: 'profit-panel' },
          ],
          change_comparison: { status: 'not_available', reason: 'No comparable prior-window evidence supplied' },
          anomalies: [{ id: 'fleet_status_offline', status: 'OFFLINE', count: 1, age_seconds: 20 }],
          explanations: [],
          economic_impact: null,
          economic_impact_status: 'not_established',
        },
        command_center: [{
          title: 'Commercial offer', target: 'market', panel: 'market-panel',
          url: 'https://example.invalid/affiliate',
        }],
      });
      await route.fulfill({ json: snapshot });
    });
    await page.route(/\/api\/axe-fleet\/health(?:\?|$)/, async (route) => {
      await route.fulfill({ json: {
        fleet_stats: {
          total_devices: 2, online: 1, warning: 0, offline: 1,
          avg_health_score: 48, total_hashrate_hs: 4e12,
          total_hashrate_str: '4.00 TH/s', total_power_w: 3200,
          avg_temperature_c: 66, best_diff: '', efficiency_jth: 800,
          hashrate_lost_hs: 1.5e12, hashrate_lost_str: '1.50 TH/s',
          hashrate_loss_baseline_devices: 2,
          hashrate_loss_basis: '1h_or_last_known',
        },
        device_health: [
          {
            id: 'online-1', name: 'Rack A', status: 'ONLINE', health_score: 90,
            capabilities: [], telemetry: { hashrate_hs: 4e12, hashrate_str: '4.00 TH/s', age_seconds: 20 },
          },
          {
            id: 'offline-1', name: 'Rack B', status: 'OFFLINE', health_score: 0,
            capabilities: [], telemetry: { hashrate_hs: 0, hashrate_str: '0 H/s', age_seconds: 20 },
          },
        ],
        groups: { online: ['online-1'], warning: [], offline: ['offline-1'] },
      } });
    });

    await page.goto('/');
    await expect(page.locator('#op-overall-status')).toHaveText('CRITICAL', { timeout: 15000 });
    await expect(page.locator('#op-attention')).toHaveText('1');
    await expect(page.locator('#op-lost-hashrate')).toHaveText('1.50 TH/s');
    await expect(page.locator('#op-cost')).toHaveText('$8.50/day');
    await expect(page.locator('#op-action-title')).toContainText('ASIC EXCEPTION');
    await expect(page.locator('#op-state')).toContainText('require operator diagnosis');
    await expect(page.locator('#op-state')).not.toContainText('Loading');
    await expect(page.locator('#op-evidence-limits')).toContainText('1 OFFLINE device exception');
    await expect(page.locator('.op-evidence__domain').filter({ hasText: 'FLEET' })).toContainText('ONLINE');
    await expect(page.locator('.op-evidence__domain').filter({ hasText: 'FLEET' })).toContainText('OFFLINE');
    await expect(page.locator('.op-evidence__domain').filter({ hasText: 'ECONOMICS' })).toContainText('OBSERVED');
    await expect(page.locator('.op-evidence__domain').filter({ hasText: 'ECONOMICS' })).toContainText('cost model configured');
    await expect(page.locator('#op-evidence-limits')).toContainText('No cause inferred');

    await page.locator('#op-action').click();
    await expect(page.locator('#axe-fleet-panel')).toBeVisible({ timeout: 5000 });
    expect(dangerousRequests).toEqual([]);
  });

  test('fleet outage is explicit and does not leave a frozen loading state', async ({ page }) => {
    await page.route(/\/api\/axe-fleet\/health(?:\?|$)/, async (route) => {
      await route.fulfill({ status: 503, json: { error: 'fleet unavailable' } });
    });

    await page.goto('/');
    const overview = page.locator('#operational-overview');
    await expect(overview).toHaveAttribute('aria-busy', 'false', { timeout: 15000 });
    await expect(page.locator('#op-overall-status')).toHaveText('UNAVAILABLE');
    await expect(page.locator('#op-health')).toHaveText('UNAVAILABLE');
    await expect(page.locator('#op-attention')).toHaveText('INDISPONÍVEL');
    await expect(page.locator('#op-lost-hashrate')).toHaveText('—');
    await expect(page.locator('#op-freshness')).toContainText('PARTIAL');
    await expect(page.locator('#op-state')).toContainText('could not be loaded');
    await expect(page.locator('#op-action')).toBeEnabled();
    await expect(page.locator('.op-evidence__domain').filter({ hasText: 'FLEET' })).toContainText('MISSING');
    await expect(page.locator('#op-evidence-limits')).toContainText('Economic impact not established');
  });
});
