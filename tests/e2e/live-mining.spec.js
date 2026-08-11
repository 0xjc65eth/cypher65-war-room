/**
 * CYPHER65 War Room — E2E: LIVE MINING / Worker Intelligence
 * ==========================================================
 * Covers the FLEET COMMAND CENTER (Live Mining) panel: opening the LIVE
 * MINING tab with seeded fleet devices and validating that the per-worker
 * cards + dense table (toggle) and the Hash Flow raster (one row per
 * worker × 24 tick cells) render from real /api/axe-fleet/summary data.
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

// The app registers /sw.js (static cache). Once the service worker takes
// control of the page, its fetches run OUTSIDE page.route (they don't come
// from the page's JS context), so route mocks silently lose authority — the
// grid would re-render with persisted DB devices instead of the mocked
// summary (diagnosed: INTERCEPTED:1 but 2 summary REQs, the 2nd via SW).
// Blocking SW at the context level keeps every request on the page path so
// the route mocks stay deterministic. Also relevant: glob patterns do NOT
// match in page.route() — use regex patterns (see the Pause/Resume test).
test.use({ serviceWorkers: 'block' });

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

      // ── Worker cards render (grid view é o default do FLEET COMMAND
      //    CENTER). #lm-workers flips para block só quando /summary devolve
      //    devices — visibilidade É o sinal de dados prontos. ──
      await expect(page.locator('#lm-workers-grid .fcc-card').first()).toBeVisible({ timeout: 30000 });

      // Each seeded worker renders its own card with its name.
      for (const s of seeded) {
        await expect(
          page.locator('#lm-workers-grid .fcc-card__name', { hasText: s.name })
        ).toBeVisible({ timeout: 15000 });
      }
      const cardCount = await page.locator('#lm-workers-grid .fcc-card').count();
      expect(cardCount).toBeGreaterThanOrEqual(seeded.length,
        `expected at least ${seeded.length} worker cards, got ${cardCount}`);

      // KPI strip fleet-fed reflete os devices (TOTAL HR / ONLINE etc.).
      await expect(page.locator('#fcc-summary-online')).toBeVisible({ timeout: 15000 });

      // ── Dense table view (HiveOS-style): toggle + colunas de inteligência ──
      await page.locator('.chip--view[data-cc-view="table"]').click();
      await expect(page.locator('#lm-workers-grid .fcc-t__row--head')).toBeVisible({ timeout: 5000 });
      const headRow = page.locator('#lm-workers-grid .fcc-t__row--head');
      await expect(headRow).toContainText('SHARES A/S/R');
      await expect(headRow).toContainText('REJ%');
      const tableRows = page.locator('#lm-workers-grid .fcc-t__row:not(.fcc-t__row--head)');
      const rowCount = await tableRows.count();
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

  test('Pause/Resume buttons render and fire with typed confirmation', async ({ page }) => {
    // The FLEET COMMAND CENTER cards are fed by /api/axe-fleet/summary.
    // A fresh server (run-e2e.sh boots WITHOUT DEBUG_MOCK) has an empty
    // fleet, so we mock the summary deterministically with ONE AxeOS device
    // that advertises the pause/resume capabilities — the exact shape
    // fleet_summary() serializes (capabilities flattened to an ARRAY by
    // _caps_supported_commands). The POST handlers are mocked too, so the
    // test proves the UI flow (button visible → confirm dialog → correct
    // endpoint fired) without needing a reachable miner on the LAN.
    // NB: glob patterns like '**/api/axe-fleet/summary**' do NOT match in
    // Playwright route() (diagnosed empirically — INTERCEPTED COUNT: 0 while
    // the request still fires). Regex patterns match reliably.
    const PAUSE_URL = /\/api\/axe-fleet\/devices\/[^/]+\/pause/;
    const RESUME_URL = /\/api\/axe-fleet\/devices\/[^/]+\/resume/;
    const fired = { pause: 0, resume: 0 };

    await page.route(/\/api\/axe-fleet\/summary/, async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          total_devices: 1, online: 1, warning: 0, offline: 0,
          total_hashrate_hs: 5200000000000,
          devices: [{
            id: 'e2e-pause-dev',
            name: 'E2E Pause Dev',
            ip_address: '192.0.2.30',
            model: 'Bitaxe ULP',
            manufacturer: 'Bitaxe',
            status: 'ONLINE',
            agent_managed: 0,
            capabilities: ['restart', 'identify', 'pause', 'resume'],
            latency_ms: 4,
            advice: [],
            _health: { score: 92, label: 'healthy', issues: [] },
            _telemetry: {
              hashrate_hs: 5200000000000,
              hashrate_str: '5.2 TH/s',
              temperature: 62, fan_rpm: 4200, power_watts: 42,
              efficiency_jth: 8.08, shares_accepted: 15823,
              shares_rejected: 47, shares_stale: 0,
              hw_error_pct: 0.3, stratum_status: 'connected',
              uptime_seconds: 259200, ts: Math.floor(Date.now() / 1000),
            },
          }],
        }),
      });
    });
    await page.route(PAUSE_URL, async (route) => {
      fired.pause += 1;
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ success: true,
          message: "'pause' enviado para o agente local executar" }),
      });
    });
    await page.route(RESUME_URL, async (route) => {
      fired.resume += 1;
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ success: true, message: 'resume sent' }),
      });
    });

    test.setTimeout(60000);
    const capture = setupErrorCapture(page);
    await page.goto(BASE_URL);
    await waitForDashboard(page);

    // ── Open the LIVE MINING module (FLEET COMMAND CENTER) ──
    await ensureSidebarOpen(page);
    await page.locator('.sidebar__link[data-module="live"]').click();
    await page.waitForTimeout(600);

    // ── The mocked AxeOS device renders a card with BOTH buttons ──
    const card = page.locator('#lm-workers-grid .fcc-card').first();
    await expect(card).toBeVisible({ timeout: 30000 });
    const pauseBtn = card.locator('.axe-cmd-btn--pause');
    const resumeBtn = card.locator('.axe-cmd-btn--resume');
    await expect(pauseBtn).toBeVisible({ timeout: 15000 });
    await expect(resumeBtn).toBeVisible({ timeout: 5000 });

    // ── Pause: confirm dialog must appear; dismissing it must NOT fire ──
    page.once('dialog', d => d.dismiss());
    await pauseBtn.click();
    await page.waitForTimeout(300);
    expect(fired.pause).toBe(0,
      'dismissing the confirm dialog must cancel the pause command');

    // ── Accepting the confirm fires the axe-fleet pause endpoint ──
    page.once('dialog', d => d.accept());
    await pauseBtn.click();
    await expect
      .poll(() => fired.pause, { timeout: 5000 })
      .toBeGreaterThanOrEqual(1);

    // Success toast confirms the round-trip reached the server response.
    const toast = page.locator('#toast-container div', { hasText: 'pause' });
    await expect(toast).toBeVisible({ timeout: 8000 });

    // ── Resume: no confirm dialog (safe action), fires the resume endpoint ──
    await resumeBtn.click();
    await expect
      .poll(() => fired.resume, { timeout: 5000 })
      .toBeGreaterThanOrEqual(1);

    // ── The panel renders without console errors ──
    const critical = capture.getCritical();
    expect(critical.length).toBe(0,
      `Critical console errors: ${JSON.stringify(critical)}`);
  });
});
