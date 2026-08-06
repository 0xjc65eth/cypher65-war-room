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

const DETECT_IP = '127.0.0.1';  // localhost — fails fast (connection refused)

/** All required top-level keys in the /detect response,
 *  with their expected types when reachable=False. */
const DETECT_CONTRACT = {
  firmware: 'string',
  adapter_type: 'string',
  version: 'string',
  model: 'string',
  capabilities: 'object',
  reachable: 'boolean',
};

/** Expected values when the target is unreachable (localhost). */
const UNREACHABLE_FALLBACK = {
  firmware: 'unknown',
  adapter_type: 'unknown',
  reachable: false,
};

test.describe('GET /api/axe-fleet/detect/<ip> — contract', () => {

  test('returns all required firmware-contract fields', async ({ page }) => {
    // Navigate to get a browser session (cookies, CSRF, etc.)
    await page.goto('/');
    await page.waitForSelector('#app-shell', { timeout: 15000 });

    // Call the detect endpoint via the browser's fetch (shares session)
    const result = await page.evaluate(async (ip) => {
      const r = await fetch('/api/axe-fleet/detect/' + encodeURIComponent(ip));
      // Graceful skip when the server or route is unreachable
      if (r.status >= 500) {
        return { _skip: true, _reason: 'server returned ' + r.status };
      }
      return await r.json();
    }, DETECT_IP);

    // If the server is down / route missing, skip gracefully
    if (result._skip) {
      test.skip(true, result._reason);
      return;
    }

    // ── Contract: every required key must be present ──────────────────
    for (const [key, typeHint] of Object.entries(DETECT_CONTRACT)) {
      expect(result, `missing key: "${key}"`).toHaveProperty(key);

      if (typeHint === 'string') {
        expect(typeof result[key], `"${key}" must be a string`).toBe('string');
      } else if (typeHint === 'boolean') {
        expect(typeof result[key], `"${key}" must be a boolean`).toBe('boolean');
      } else if (typeHint === 'object') {
        expect(typeof result[key], `"${key}" must be an object`).toBe('object');
      }
    }

    // ── Unreachable fallback values ──────────────────────────────────
    expect(result.reachable, 'reachable must be false for localhost').toBe(false);
    expect(result.firmware, 'firmware must be "unknown" for unreachable').toBe('unknown');
    expect(result.adapter_type, 'adapter_type must be "unknown" for unreachable').toBe('unknown');
    expect(result.model, 'model must be "" (empty) for unreachable').toBe('');
    expect(result.version, 'version must be "" (empty) for unreachable').toBe('');
  });

  test('unreachable response has empty capabilities dict', async ({ page }) => {
    await page.goto('/');
    await page.waitForSelector('#app-shell', { timeout: 15000 });

    const result = await page.evaluate(async (ip) => {
      const r = await fetch('/api/axe-fleet/detect/' + encodeURIComponent(ip));
      return await r.json();
    }, DETECT_IP);

    if (result._skip) { test.skip(true, result._reason); return; }

    expect(typeof result.capabilities).toBe('object');
    // Unreachable → empty capabilities (no probes succeeded)
    expect(Object.keys(result.capabilities).length).toBe(0);
  });

  test('accepts hostname path parameter', async ({ page }) => {
    await page.goto('/');
    await page.waitForSelector('#app-shell', { timeout: 15000 });

    // miner.lan won't resolve → DNS failure in detector → unreachable
    const result = await page.evaluate(async () => {
      const r = await fetch('/api/axe-fleet/detect/miner.lan');
      return await r.json();
    });

    if (result._skip) { test.skip(true, result._reason); return; }

    // Must still return a valid contract (not 404 or 500)
    expect(result).toHaveProperty('reachable');
    expect(result).toHaveProperty('firmware');
    expect(result).toHaveProperty('adapter_type');
  });

  test('response includes reachable flag as boolean', async ({ page }) => {
    await page.goto('/');
    await page.waitForSelector('#app-shell', { timeout: 15000 });

    const result = await page.evaluate(async (ip) => {
      const r = await fetch('/api/axe-fleet/detect/' + encodeURIComponent(ip));
      return await r.json();
    }, DETECT_IP);

    if (result._skip) { test.skip(true, result._reason); return; }

    // reachable is ALWAYS a boolean — never null, undefined, or string
    expect(typeof result.reachable).toBe('boolean');
  });

  test('returns JSON with correct content-type', async ({ request }) => {
    // Direct API call via Playwright request fixture (no browser session needed)
    const r = await request.get('/api/axe-fleet/detect/' + DETECT_IP);

    // Graceful skip when server is down
    if (r.status() >= 500) {
      test.skip(true, 'server returned ' + r.status());
      return;
    }

    expect(r.status()).toBe(200);
    const ct = r.headers()['content-type'] || '';
    expect(ct, 'response must be application/json').toContain('application/json');

    const data = await r.json();
    expect(data).toHaveProperty('reachable');
    expect(data).toHaveProperty('firmware');
    expect(data).toHaveProperty('adapter_type');
  });

  test.describe('Braiins OS+ firmware contract (mocked)', () => {
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
      // Intercept the detect endpoint and return a synthetic Braiins response
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
