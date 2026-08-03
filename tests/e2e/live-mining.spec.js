/**
 * CYPHER65 War Room — E2E: LIVE MINING / Worker Intelligence
 * ==========================================================
 * Covers the FASE_2 Worker Intelligence panel: opening the LIVE MINING
 * tab with seeded fleet devices and validating that the per-worker rows
 * (table) and the Hash Flow raster (one row per worker × 24 tick cells)
 * render from real /api/axe-fleet/summary data.
 *
 * Seeding is done through the public API because the E2E runner boots the
 * server WITHOUT DEBUG_MOCK (run-e2e.sh) — a fresh server has an empty
 * fleet, so the panel's honest empty state is the only deterministic
 * outcome unless the test registers devices itself.
 *
 * Prerequisites: Flask server running on BASE_URL (default http://127.0.0.1:8765)
 * Run:  npx playwright test tests/e2e/live-mining.spec.js
 * CI:   bash run-e2e.sh
 */

import { test, expect } from '@playwright/test';

const BASE_URL = process.env.BASE_URL || 'http://127.0.0.1:8765';

// ══════════════════════════════════════════════════════════════════════
//  Helpers (same conventions as dashboard.spec.js / terminal.spec.js)
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

/**
 * Seed a fleet device via the public API. Tolerant of a 409 left over from a
 * previous (possibly crashed) run — in that case the existing row is reused
 * so the assertions still hold. Returns { id } for cleanup.
 */
async function seedDevice(page, ip, name) {
  const res = await page.request.post(`${BASE_URL}/api/axe-fleet/devices`, {
    data: { ip_address: ip, name },
  });
  if (res.status() === 201) {
    const body = await res.json();
    const id = body.device && body.device.id;
    if (!id) throw new Error(`seed ${name}: 201 without device.id: ${JSON.stringify(body)}`);
    return { id, ip, name, existing: false };
  }
  if (res.status() === 409) {
    const listRes = await page.request.get(`${BASE_URL}/api/axe-fleet/devices`);
    const list = await listRes.json();
    const dev = (list.devices || []).find(d => d.ip_address === ip);
    if (dev && dev.id) return { id: dev.id, ip, name, existing: true };
    throw new Error(`seed ${name}: 409 but no matching device found for ${ip}`);
  }
  throw new Error(`seed ${name} failed: HTTP ${res.status()} ${await res.text()}`);
}

// ══════════════════════════════════════════════════════════════════════
//  Tests
// ══════════════════════════════════════════════════════════════════════

test.describe('LIVE MINING — Worker Intelligence', () => {

  test('worker rows and hash-flow raster render from seeded fleet devices', async ({ page }) => {
    // Seed + open tab + up to one full POLL_INTERVAL (15s) before the first
    // /summary fetch picks the devices up. Budget generously.
    test.setTimeout(90000);

    const capture = setupErrorCapture(page);
    await page.goto(BASE_URL);
    await waitForDashboard(page);

    // ── Seed 2 deterministic devices (see header comment). IPs use the
    //    RFC 5737 TEST-NET-1 range (192.0.2.0/24) — reserved for docs/tests
    //    and unroutable, so a real miner can never collide with them. Cleaned
    //    up in the finally block so repeated runs never hit the FREE cap (5). ──
    const seeded = [];
    try {
      seeded.push(await seedDevice(page, '192.0.2.10', 'E2E Alpha'));
      seeded.push(await seedDevice(page, '192.0.2.11', 'E2E Beta'));

      // ── Open the LIVE MINING module (sidebar) ──
      await ensureSidebarOpen(page);
      await page.locator('.sidebar__link[data-module="live"]').click();
      await page.waitForTimeout(600);

      // ── Worker rows render. The panel starts with the honest empty state
      //    (#lm-workers display:none) and renderWorkerIntelligence() flips it
      //    to block only when /summary returns devices — so visibility IS the
      //    wait-for-data signal. Timeout covers one full poll cycle. ──
      await expect(page.locator('#lm-workers-grid .lm-w__row--head')).toBeVisible({ timeout: 30000 });
      await expect(
        page.locator('#lm-workers-grid .lm-w__row:not(.lm-w__row--head)').first()
      ).toBeVisible({ timeout: 30000 });

      // Head row carries the intelligence columns (not just a bare grid).
      const headRow = page.locator('#lm-workers-grid .lm-w__row--head');
      await expect(headRow).toContainText('SHARES A/R/S');
      await expect(headRow).toContainText('REJ%');

      // Each seeded worker renders its own row with name (+ IP in the cell).
      for (const s of seeded) {
        await expect(
          page.locator('#lm-workers-grid .lm-w__name', { hasText: s.name })
        ).toBeVisible({ timeout: 15000 });
      }
      const bodyRows = page.locator('#lm-workers-grid .lm-w__row:not(.lm-w__row--head)');
      const rowCount = await bodyRows.count();
      expect(rowCount).toBeGreaterThanOrEqual(seeded.length,
        `expected at least ${seeded.length} worker rows, got ${rowCount}`);

      // ── Hash Flow raster: one row per worker, exactly 24 tick cells each
      //    (_LM_FLOW_MAX). Unfilled slots render 'mute' so the grid never
      //    collapses while the ring buffer warms up. ──
      await expect(page.locator('#lm-flow')).toBeVisible({ timeout: 15000 });
      const rasterRows = page.locator('#lm-flow-raster .lm-flow__row');
      expect(await rasterRows.count()).toBe(rowCount,
        'raster must draw exactly one row per worker');
      const cellCounts = await rasterRows.evaluateAll(rows =>
        rows.map(r => r.querySelectorAll('.lm-flow__cell').length)
      );
      cellCounts.forEach((n, i) => {
        expect(n, `raster row ${i} must draw 24 cells, got ${n}`).toBe(24);
      });

      // Legend communicates the share-quality color coding (ok/rej/stale).
      await expect(page.locator('.lm-flow__dot--ok')).toBeVisible();
      await expect(page.locator('.lm-flow__dot--rej')).toBeVisible();
      await expect(page.locator('.lm-flow__dot--stale')).toBeVisible();

      // ── The panel renders without console errors ──
      const critical = capture.getCritical();
      expect(critical.length).toBe(0,
        `Critical console errors: ${JSON.stringify(critical)}`);
    } finally {
      // ── Cleanup: delete ONLY devices this run created (201 path). A
      //    reused leftover (409 → existing:true) is left alone — it is at
      //    worst a harmless artifact of a previous crashed run (same fixed
      //    TEST-NET IP, self-healing on the next run) and at best a device
      //    we never created and must not remove. ──
      for (const s of seeded) {
        if (s && s.id && !s.existing) {
          await page.request
            .delete(`${BASE_URL}/api/axe-fleet/devices/${s.id}`)
            .catch(() => { /* best-effort: 404 means already gone */ });
        }
      }
    }
  });
});
