/**
 * CYPHER65 War Room — E2E: Admin audit trail (Issue #96)
 * =====================================================
 *
 * Guards the admin panel's "AUDIT DE RECOMENDAÇÕES ACEITAS" section:
 *   - the accepted-recos endpoint is fetched alongside sessions/conversion
 *     when the Admin module activates;
 *   - the decisions table renders (tenant, rig, verdict badges);
 *   - the tenant + verdict filters narrow the table client-side;
 *   - the weekly mini-chart canvas exists (Chart.js bar).
 *
 * All three admin endpoints are mocked → deterministic, no real DB.
 *
 * Prerequisites: Flask server running on BASE_URL (see playwright.config.js).
 * Run: npx playwright test tests/e2e/admin-audit.spec.js
 */
import { test, expect } from '@playwright/test';

test.use({ serviceWorkers: 'block' });

const DECISIONS = [
  { ts: 1784505600, tenant_id: 'tenant-a', rig_id: '2001', name: 'Rig F2 Bad',
    source: 'auto', grade: 'F', pilot_flagged: true, delivery_pct: 55.0,
    delivery_after_pct: 48.0, verdict: 'worse' },
  { ts: 1785110400, tenant_id: 'tenant-a', rig_id: '1001', name: 'S19 Good',
    source: 'manual', grade: 'A', pilot_flagged: false, delivery_pct: 60.0,
    delivery_after_pct: 96.0, verdict: 'improved' },
  { ts: 1785110400 + 86400, tenant_id: 'default', rig_id: '3001', name: 'Rig Mid',
    source: 'manual', grade: 'D', pilot_flagged: true, delivery_pct: 80.0,
    delivery_after_pct: null, verdict: 'avoided' },
];

const AUDIT = {
  count: 3,
  by_source: { auto: 1, manual: 2 },
  by_verdict: { worse: 1, improved: 1, avoided: 1 },
  by_tenant: [
    { tenant_id: 'tenant-a', count: 2 },
    { tenant_id: 'default', count: 1 },
  ],
  pilot_flagged: 2,
  avg_delivery_before: 65.0,
  avg_delivery_after: 72.0,
  days: null,
  decisions: DECISIONS,
  worse_concentration: { count: 1, tenants: [], min_worse: 2, worse_ratio: 0.5, days: null },
};

test.describe('ADMIN — audit trail de recomendações aceitas (Issue #96)', () => {
  test('tabela renderiza, filtros filtram e o chart semanal existe', async ({ page }) => {
    // Mock all three admin endpoints the panel fetches on activation.
    await page.route('**/api/admin/sessions**', (route) =>
      route.fulfill({ json: { pool: { sessions_active: 3, polls_per_sec: 1.2,
        queue_pending: 0, workers_alive: 4, pool_size: 8, uptime_secs: 300,
        stalled: false } } }));
    await page.route('**/api/admin/conversion**', (route) =>
      route.fulfill({ json: { funnel: {}, economics: {} } }));
    await page.route('**/api/admin/rentals/accepted-recos**', (route) => {
      const url = route.request().url();
      if (url.includes('format=csv')) {
        // CSV export — served as an attachment (blob download path).
        route.fulfill({ status: 200, headers: { 'Content-Type': 'text/csv' },
          body: '\ufefftenant_id,accepted_ts,rig_id\n' });
        return;
      }
      route.fulfill({ json: AUDIT });
    });

    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await page.waitForSelector('#app-shell', { timeout: 15000 });
    await page.waitForSelector('#open-wallet', { timeout: 10000 });
    await page.waitForFunction(() => {
      return document.querySelectorAll('.skel-overlay').length === 0;
    }, { timeout: 10000 }).catch(() => {});
    await page.waitForTimeout(500);

    // Navigate to the Admin module.
    await page.click('.sidebar__link[data-module="admin"]');
    const audit = page.locator('#admin-audit');
    await expect(audit).toBeVisible({ timeout: 10000 });

    // The section title renders.
    await expect(page.locator('#admin-panel .panel__subtitle').last())
      .toContainText('AUDIT DE RECOMENDAÇÕES ACEITAS');

    // Weekly chart canvas exists (Chart.js bar).
    await expect(page.locator('#admin-audit-chart')).toBeVisible();

    // Table: 3 decision rows (plus thead). Verdict badges + tenant present.
    const rows = page.locator('#admin-audit-tbody tr');
    await expect(rows).toHaveCount(3);
    await expect(page.locator('#admin-audit-tbody')).toContainText('tenant-a');
    await expect(page.locator('#admin-audit-tbody')).toContainText('Rig F2 Bad');
    await expect(page.locator('#admin-audit-tbody')).toContainText('WORSE');
    await expect(page.locator('#admin-audit-tbody')).toContainText('IMPROVED');
    await expect(page.locator('#admin-audit-tbody')).toContainText('AVOIDED');

    // Tenant filter: tenant-a only → 2 rows.
    await page.selectOption('#admin-audit-tenant', 'tenant-a');
    await expect(rows).toHaveCount(2);
    await expect(page.locator('#admin-audit-tbody')).not.toContainText('Rig Mid');

    // Verdict filter adds AND semantics: tenant-a + improved → 1 row.
    await page.selectOption('#admin-audit-verdict', 'improved');
    await expect(rows).toHaveCount(1);
    await expect(page.locator('#admin-audit-tbody')).toContainText('S19 Good');

    // Reset → all rows again.
    await page.selectOption('#admin-audit-tenant', '');
    await page.selectOption('#admin-audit-verdict', '');
    await expect(rows).toHaveCount(3);

    // CSV button exists (export path is admin-gated server-side).
    await expect(page.locator('#admin-audit-csv')).toBeVisible();
  });

  test('403 do audit esconde a seção e mostra o erro do gate', async ({ page }) => {
    // Only the audit endpoint is forbidden — the panel must fall back to the
    // existing "restricted" state and never render the audit section.
    await page.route('**/api/admin/sessions**', (route) =>
      route.fulfill({ json: { pool: {} } }));
    await page.route('**/api/admin/conversion**', (route) =>
      route.fulfill({ json: { funnel: {}, economics: {} } }));
    await page.route('**/api/admin/rentals/accepted-recos**', (route) =>
      route.fulfill({ status: 403, json: { error: 'admin access required' } }));

    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await page.waitForSelector('#app-shell', { timeout: 15000 });
    await page.click('.sidebar__link[data-module="admin"]');

    await expect(page.locator('#admin-gate-badge')).toHaveText('restricted', { timeout: 10000 });
    await expect(page.locator('#admin-error')).toBeVisible();
    await expect(page.locator('#admin-audit')).toBeHidden();
  });
});
