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

/** Ensure the sidebar is open so sidebar links are clickable (mobile off-canvas).
 * Same pattern as dashboard.spec.js — without it the mobile-chrome project
 * times out clicking .sidebar__link (sidebar is translateX(-100%) off-canvas). */
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
        stalled: false, auto_exclude_alerts: { sweep: 2, panel: 1, total: 3 } } } }));
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
    await ensureSidebarOpen(page);
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

  test('decisões com ts=0/nulo aparecem na nota "sem data" (Issue #205)', async ({ page }) => {
    // Sev-3 #205 honest telemetry: decisions without a valid ts must NEVER
    // vanish silently from the weekly chart — they surface as a visible
    // undercount note, while the table still renders the rows (date '—').
    await page.route('**/api/admin/sessions**', (route) =>
      route.fulfill({ json: { pool: { auto_exclude_alerts: { sweep: 0, panel: 0, total: 0 } } } }));
    await page.route('**/api/admin/conversion**', (route) =>
      route.fulfill({ json: { funnel: {}, economics: {} } }));
    await page.route('**/api/admin/rentals/accepted-recos**', (route) =>
      route.fulfill({ json: {
        ...AUDIT,
        count: 5,
        decisions: [
          ...DECISIONS,
          { ts: 0, tenant_id: 'tenant-a', rig_id: '4001', name: 'Rig NoDate zero',
            source: 'auto', grade: 'C', pilot_flagged: false, delivery_pct: 70.0,
            delivery_after_pct: 71.0, verdict: 'same' },
          { ts: null, tenant_id: 'default', rig_id: '4002', name: 'Rig NoDate null',
            source: 'manual', grade: 'B', pilot_flagged: false, delivery_pct: 80.0,
            delivery_after_pct: 82.0, verdict: 'improved' },
        ],
      } }));

    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await page.waitForSelector('#app-shell', { timeout: 15000 });
    await page.waitForSelector('#open-wallet', { timeout: 10000 });
    await page.waitForFunction(() => {
      return document.querySelectorAll('.skel-overlay').length === 0;
    }, { timeout: 10000 }).catch(() => {});
    await page.waitForTimeout(500);

    await ensureSidebarOpen(page);
    await page.click('.sidebar__link[data-module="admin"]');
    await expect(page.locator('#admin-audit')).toBeVisible({ timeout: 10000 });

    // Undercount note is visible and honest (never a silent drop).
    const note = page.locator('#admin-audit-note');
    await expect(note).toBeVisible();
    await expect(note).toContainText('2 decisões sem data');
    await expect(note).toContainText('fora do gráfico semanal');

    // The without-date rows still render in the table (date cell '—').
    await expect(page.locator('#admin-audit-tbody tr')).toHaveCount(5);
    await expect(page.locator('#admin-audit-tbody')).toContainText('Rig NoDate zero');
    await expect(page.locator('#admin-audit-tbody')).toContainText('Rig NoDate null');
  });

  test('auto-exclusões renderizam no RENTALS (tenant) e no admin (global, Issue #100)', async ({ page }) => {
    // RENTALS payload with the tenant-scoped auto-exclusion history.
    await page.route('**/api/rentals**', (route) => {
      const url = route.request().url();
      if (url.includes('accepted-recos') || url.includes('/rig/')) {
        route.continue();
        return;
      }
      route.fulfill({ json: {
        success: true,
        mrr: { needs_auth: false, active: [], history: [], owner: [],
               total_active: 0, total_history: 0, total_owner: 0, error: null },
        braiins: { needs_auth: false, contracts: [], error: null },
        portfolio: { spend: {}, income: {}, split: {}, counts: {} },
        portfolio_series: { bucket: 'week', estimate: true, points: [], totals: {} },
        recommendations: { top: [], avoid: [], avoid_count: 0, tracked: 0,
                            market: { available: false } },
        market_trend: { points: [], summary: null },
        rig_blacklist: [],
        rig_auto_blacklist: ['rig-b'],
        accepted_recos: { count: 0, accepted: [] },
        auto_exclusions: {
          count: 1,
          exclusions: [{
            rig_id: 'rig-b', name: 'Rig B Auto', ts: 1785110400, grade: 'F',
            delivery_pct: 55.0, samples: 1, min_samples: 2, grade_floor: 'F',
            cause: 'grade F · entrega 55.0% · 1 amostras — régua: floor F, mín 2',
          }],
        },
      } });
    });
    // Admin endpoints — audit carries the GLOBAL auto-exclusion history.
    await page.route('**/api/admin/sessions**', (route) =>
      route.fulfill({ json: { pool: { auto_exclude_alerts: { sweep: 2, panel: 1, total: 3 } } } }));
    await page.route('**/api/admin/conversion**', (route) =>
      route.fulfill({ json: { funnel: {}, economics: {} } }));
    await page.route('**/api/admin/rentals/accepted-recos**', (route) =>
      route.fulfill({ json: {
        ...AUDIT,
        auto_exclusions: {
          count: 2,
          exclusions: [
            { tenant_id: 'tenant-a', rig_id: '2001', name: 'Rig F2 Bad',
              ts: 1785110400, grade: 'F', delivery_pct: 48.0, samples: 2,
              cause: 'grade F · entrega 48.0% · 2 amostras — régua: floor D, mín 3' },
            { tenant_id: 'default', rig_id: 'rig-b', name: 'Rig B Auto',
              ts: 1785110400 - 86400, grade: 'D', delivery_pct: 70.0,
              samples: 1, cause: 'grade D · entrega 70.0% · 1 amostras' },
          ],
        },
      } }));

    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await page.waitForSelector('#app-shell', { timeout: 15000 });
    await page.waitForSelector('#open-wallet', { timeout: 10000 });
    await page.waitForFunction(() => {
      return document.querySelectorAll('.skel-overlay').length === 0;
    }, { timeout: 10000 }).catch(() => {});
    await page.waitForTimeout(500);

    // RENTALS panel — tenant-scoped auto-exclusion cards.
    await ensureSidebarOpen(page);
    await page.click('.sidebar__link[data-module="rentals"]');
    const rentalsEx = page.locator('#rentals-autoex');
    await expect(rentalsEx).toBeVisible({ timeout: 10000 });
    await expect(rentalsEx).toContainText('AUTO-EXCLUSÕES DO PILOTO');
    await expect(rentalsEx).toContainText('Rig B Auto');
    await expect(rentalsEx).toContainText('régua F · mín 2');
    await expect(rentalsEx).toContainText('entrega 55.0%');
    await expect(rentalsEx).toContainText('régua: floor F, mín 2');

    // Admin panel — global auto-exclusion block with tenant tags.
    await ensureSidebarOpen(page);
    await page.click('.sidebar__link[data-module="admin"]');
    const adminEx = page.locator('#admin-autoex');
    await expect(adminEx).toBeVisible({ timeout: 10000 });
    await expect(adminEx).toContainText('AUTO-EXCLUSÕES DO PILOTO (global)');
    await expect(adminEx).toContainText('2 auto-exclusões (global)');
    await expect(adminEx).toContainText('tenant-a');
    await expect(adminEx).toContainText('Rig F2 Bad');
    await expect(adminEx).toContainText('régua: floor D, mín 3');
    await expect(adminEx).toContainText('default');
    await expect(adminEx).toContainText('Rig B Auto');
    // KPI card: alertas de auto-exclusão por caminho (Issue #112) —
    // total 3 · sweep 2 / painel 1.
    await expect(page.locator('#admin-autoex-alerts')).toHaveText('3 · s2/p1');
  });

  test('concentração de auto-exclusões renderiza barras por tenant/régua + rigs reincidentes (Issue #106)', async ({ page }) => {
    await page.route('**/api/admin/sessions**', (route) =>
      route.fulfill({ json: { pool: { auto_exclude_alerts: { sweep: 0, panel: 0, total: 0 } } } }));
    await page.route('**/api/admin/conversion**', (route) =>
      route.fulfill({ json: { funnel: {}, economics: {} } }));
    await page.route('**/api/admin/rentals/accepted-recos**', (route) =>
      route.fulfill({ json: {
        ...AUDIT,
        auto_exclusions: {
          count: 4,
          exclusions: [
            { tenant_id: 'tenant-a', rig_id: 'rig-x', name: 'Rig X', ts: 1785110400, grade: 'F', delivery_pct: 48.0, samples: 2, min_samples: 2, grade_floor: 'F', cause: 'grade F' },
            { tenant_id: 'default', rig_id: 'rig-x', name: 'Rig X', ts: 1785110400 - 86400, grade: 'F', delivery_pct: 45.0, samples: 2, min_samples: 2, grade_floor: 'F', cause: 'grade F' },
            { tenant_id: 'tenant-a', rig_id: 'rig-b', name: 'Rig B', ts: 1785110400 - 2 * 86400, grade: 'F', delivery_pct: 55.0, samples: 2, min_samples: 2, grade_floor: 'F', cause: 'grade F' },
            { tenant_id: 'default', rig_id: 'rig-d', name: 'Rig D', ts: 1785110400 - 3 * 86400, grade: 'D', delivery_pct: 70.0, samples: 3, min_samples: 3, grade_floor: 'D', cause: 'grade D' },
          ],
        },
        auto_exclusion_aggregates: {
          count: 4,
          by_tenant: [
            { tenant_id: 'tenant-a', count: 2, pct: 50.0, rigs: 2, top_grade: 'F', delivery_avg_pct: 51.5 },
            { tenant_id: 'default', count: 2, pct: 50.0, rigs: 2, top_grade: 'F', delivery_avg_pct: 57.5 },
          ],
          by_rule: [
            { grade_floor: 'F', min_samples: 2, count: 3, pct: 75.0, tenants: 2, delivery_avg_pct: 49.3 },
            { grade_floor: 'D', min_samples: 3, count: 1, pct: 25.0, tenants: 1, delivery_avg_pct: 70.0 },
          ],
          top_rigs: [
            { rig_id: 'rig-x', name: 'Rig X', tenant_count: 2, tenants: ['default', 'tenant-a'], total_count: 2, last_ts: 1785110400 },
          ],
          days: null,
        },
      } }));

    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await page.waitForSelector('#app-shell', { timeout: 15000 });
    await page.waitForSelector('#open-wallet', { timeout: 10000 });
    await page.waitForFunction(() => {
      return document.querySelectorAll('.skel-overlay').length === 0;
    }, { timeout: 10000 }).catch(() => {});
    await page.waitForTimeout(500);

    await ensureSidebarOpen(page);
    await page.click('.sidebar__link[data-module="admin"]');
    const agg = page.locator('#admin-autoex-agg');
    await expect(agg).toBeVisible({ timeout: 10000 });
    await expect(agg).toContainText('CONCENTRAÇÃO POR TENANT');
    await expect(agg).toContainText('tenant-a');
    await expect(agg).toContainText('2x');
    await expect(agg).toContainText('CONCENTRAÇÃO POR RÉGUA');
    await expect(agg).toContainText('floor F · mín 2');
    await expect(agg).toContainText('floor D · mín 3');
    // Systemic-problem rig: same rig auto-excluded in 2 tenants.
    const topCol = page.locator('#admin-autoex-toprigs-col');
    await expect(topCol).toBeVisible();
    await expect(topCol).toContainText('RIGS REINCIDENTES');
    await expect(topCol).toContainText('Rig X');
    await expect(topCol).toContainText('2 tenants · 2x');
  });

  test('403 do audit esconde a seção e mostra o erro do gate', async ({ page }) => {
    // Only the audit endpoint is forbidden — the panel must fall back to the
    // existing "restricted" state and never render the audit section.
    await page.route('**/api/admin/sessions**', (route) =>
      route.fulfill({ json: { pool: { auto_exclude_alerts: { sweep: 0, panel: 0, total: 0 } } } }));
    await page.route('**/api/admin/conversion**', (route) =>
      route.fulfill({ json: { funnel: {}, economics: {} } }));
    await page.route('**/api/admin/rentals/accepted-recos**', (route) =>
      route.fulfill({ status: 403, json: { error: 'admin access required' } }));

    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await page.waitForSelector('#app-shell', { timeout: 15000 });
    await ensureSidebarOpen(page);
    await page.click('.sidebar__link[data-module="admin"]');

    await expect(page.locator('#admin-gate-badge')).toHaveText('restricted', { timeout: 10000 });
    await expect(page.locator('#admin-error')).toBeVisible();
    await expect(page.locator('#admin-audit')).toBeHidden();
  });
});
