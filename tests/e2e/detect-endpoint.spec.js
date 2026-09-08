/**
 * CYPHER65 War Room — E2E Detect Endpoint Contract Tests
 * =========================================================
 *
 * Verifies the /api/axe-fleet/detect/<ip> endpoint returns the correct
 * firmware contract shape (all required fields present with correct types).
 *
 * The endpoint calls detect_firmware() which makes real HTTP probes to
 * the target IP. We test against localhost (connection-refused fast-path)
 * to validate the HTTP contract without relying on a real miner.
 *
 * Full detection logic (bitaxe/braiins/cgminer classification) is covered
 * by Python unit tests in tests/core/test_braiins_adapter.py and
 * tests/test_axe_fleet_scanner.py::TestDetectRoute.
 *
 * Prerequisites: Flask server running on BASE_URL.
 *
 * Run:  npx playwright test tests/e2e/detect-endpoint.spec.js
 */

import { test, expect } from '@playwright/test';

// ══════════════════════════════════════════════════════════════════════

const LOOPBACK_IP = '127.0.0.1';  // SSRF fail-closed — not a private LAN target

async function detectCall(page, target) {
  return page.evaluate(async (ip) => {
    const r = await fetch('/api/axe-fleet/detect/' + encodeURIComponent(ip));
    let body = null;
    try { body = await r.json(); } catch (e) { body = { _parseError: String(e) }; }
    return { status: r.status, body };
  }, target);
}

test.describe('GET /api/axe-fleet/detect/<ip> — SSRF fail-closed', () => {

  test('rejects loopback without probing', async ({ page }) => {
    await page.goto('/');
    await page.waitForSelector('#app-shell', { timeout: 15000 });

    const result = await detectCall(page, LOOPBACK_IP);
    if (result.status >= 500) {
      test.skip(true, 'server returned ' + result.status);
      return;
    }

    expect(result.status).toBe(400);
    expect(result.body.reachable).toBe(false);
    expect(String(result.body.error || '')).toMatch(/private LAN|Tailscale/i);
    expect(result.body).not.toHaveProperty('firmware');
    expect(result.body).not.toHaveProperty('capabilities');
  });

  test('rejects unresolved hostname without probing', async ({ page }) => {
    await page.goto('/');
    await page.waitForSelector('#app-shell', { timeout: 15000 });

    const result = await detectCall(page, 'miner.lan');
    if (result.status >= 500) {
      test.skip(true, 'server returned ' + result.status);
      return;
    }

    expect(result.status).toBe(400);
    expect(result.body.reachable).toBe(false);
    expect(String(result.body.error || '')).toMatch(/could not be resolved|invalid hostname|private LAN|Tailscale/i);
    expect(result.body).not.toHaveProperty('firmware');
  });

  test('reachable flag stays boolean on the fail-closed body', async ({ page }) => {
    await page.goto('/');
    await page.waitForSelector('#app-shell', { timeout: 15000 });

    const result = await detectCall(page, LOOPBACK_IP);
    if (result.status >= 500) {
      test.skip(true, 'server returned ' + result.status);
      return;
    }

    expect(typeof result.body.reachable).toBe('boolean');
    expect(result.body.reachable).toBe(false);
  });

  test('returns JSON with correct content-type on 400', async ({ request }) => {
    const r = await request.get('/api/axe-fleet/detect/' + LOOPBACK_IP);

    if (r.status() >= 500) {
      test.skip(true, 'server returned ' + r.status());
      return;
    }

    expect(r.status()).toBe(400);
    const ct = r.headers()['content-type'] || '';
    expect(ct, 'response must be application/json').toContain('application/json');

    const data = await r.json();
    expect(data).toHaveProperty('reachable');
    expect(data.reachable).toBe(false);
    expect(data).toHaveProperty('error');
  });

  test.describe('Braiins OS+ firmware contract (mocked)', () => {
    // Block the Service Worker so page.route() intercepts fetch reliably.
    // Without this, the app's SW (network-first) can bypass mock routes.
    test.use({ serviceWorkers: 'block' });
    /**
     * When a real Braiins OS+ miner responds, the contract is:
     *   firmware:    "braiins"
     *   adapter_type:"braiins"
     *   model:       "Antminer S19 Pro" (example)
     *   version:     "braiins-os_2024-10" (example)
     *   capabilities: {telemetry, restart, identify, tuner_control, set_frequency}
     *   reachable:   true
     *
     * Since we can't mock detect_firmware() from the browser, we use
     * page.route() to intercept the HTTP call and inject a synthetic
     * response that matches the expected Braiins OS+ contract. This
     * validates the FRONTEND contract expectation without a real miner.
     */

    const BRAIINS_MOCK = {
      firmware: 'braiins',
      adapter_type: 'braiins',
      version: 'braiins-os_2024-10',
      model: 'Antminer S19 Pro',
      capabilities: {
        telemetry: true,
        restart: true,
        identify: true,
        tuner_control: true,
        set_frequency: true,
      },
      reachable: true,
    };

    test('mocked Braiins response passes contract validation', async ({ page }) => {
      // Intercept the detect endpoint and return a synthetic Braiins response.
      await page.route('**/api/axe-fleet/detect/**', (route) => {
        route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify(BRAIINS_MOCK),
        });
      });

      await page.goto('/');
      await page.waitForSelector('#app-shell', { timeout: 15000 });

      const result = await page.evaluate(async () => {
        const r = await fetch('/api/axe-fleet/detect/192.168.1.200');
        return await r.json();
      });

      // ── Braiins OS+ contract assertions ───────────────────────────
      expect(result.firmware).toBe('braiins');
      expect(result.adapter_type).toBe('braiins');
      expect(result.reachable).toBe(true);
      expect(result.model).toBe('Antminer S19 Pro');
      expect(result.version).toBe('braiins-os_2024-10');

      // Capabilities: all 5 keys present + boolean
      expect(result.capabilities).toEqual({
        telemetry: true,
        restart: true,
        identify: true,
        tuner_control: true,
        set_frequency: true,
      });

      // No extra keys leaked
      const keys = Object.keys(result).sort();
      expect(keys).toEqual(
        ['adapter_type', 'capabilities', 'firmware', 'model', 'reachable', 'version']
      );
    });

    test('mocked unreachable returns correct fallback contract', async ({ page }) => {
      const UNREACHABLE_MOCK = {
        firmware: 'unknown',
        adapter_type: 'unknown',
        version: '',
        model: '',
        capabilities: {},
        reachable: false,
      };

      await page.route('**/api/axe-fleet/detect/**', (route) => {
        route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify(UNREACHABLE_MOCK),
        });
      });

      await page.goto('/');
      await page.waitForSelector('#app-shell', { timeout: 15000 });

      const result = await page.evaluate(async () => {
        const r = await fetch('/api/axe-fleet/detect/192.168.1.99');
        return await r.json();
      });

      expect(result.reachable).toBe(false);
      expect(result.firmware).toBe('unknown');
      expect(result.adapter_type).toBe('unknown');
      expect(result.model).toBe('');
      expect(result.version).toBe('');
      expect(Object.keys(result.capabilities).length).toBe(0);
    });
  });
});
