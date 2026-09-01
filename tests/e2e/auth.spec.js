/**
 * CYPHER65 War Room — E2E: Tenant Login (Fase 4 · B1-frontend)
 * ===========================================================
 * Tests the tenant-auth UI added in the B1-frontend block:
 *   - open / close the auth modal from the topbar toggle (key icon + LOGIN)
 *   - login with an API key → badge + toggle + logout button update
 *   - the `Authorization: Bearer` header is attached to /api/axe-fleet/*
 *     (the core B1-frontend goal — makes backend tenant isolation visible)
 *   - session persists in localStorage across a hard reload
 *   - logout resets the UI back to the default tenant
 *   - empty / invalid API key error states
 *
 * The /api/auth/* endpoints are MOCKED via page.route so the suite is
 * hermetic (no real API key needed) — same convention as webln.spec.js,
 * which mocks the WebLN provider. Backend isolation itself is already
 * covered by tests/test_tenant_b2_isolation.py.
 *
 * Prerequisites: Flask server running on BASE_URL (default http://127.0.0.1:8765)
 * IMPORTANT: start the server with RATE_LIMIT_PER_MINUTE=1000 (as run-e2e.sh
 * does) — the default 300/min limit returns 429 for GET / under E2E load and
 * the dashboard will never render (#app-shell missing).
 *
 * Run:  npx playwright test tests/e2e/auth.spec.js --project=chromium --workers=1
 * CI:   bash run-e2e.sh --file auth.spec.js
 */

import { test, expect } from '@playwright/test';

const BASE_URL = process.env.BASE_URL || 'http://127.0.0.1:8765';

// Mocked tenant + JWT payload returned by the fake /api/auth/login.
const MOCK_TENANT = 'acme';
const MOCK_ACCESS = 'mock-access-token-' + MOCK_TENANT;
const MOCK_REFRESH = 'mock-refresh-token-' + MOCK_TENANT;

// ── Helpers ──────────────────────────────────────────────────────────────

async function waitForDashboard(page) {
  try {
    await page.waitForSelector('#app-shell', { timeout: 20000 });
  } catch (e) {
    // Dev-server resilience: under sequential E2E load the Flask dev server can
    // briefly stall and the browser may show an error page instead of the
    // dashboard. Retry once with a fresh navigation before giving up.
    if (e.name !== 'TimeoutError') throw e; // surface real selector bugs fast
    await page.goto(BASE_URL, { waitUntil: 'domcontentloaded' });
    await page.waitForSelector('#app-shell', { timeout: 30000 });
  }
  await page.waitForSelector('#auth-toggle', { timeout: 10000 });
  await page.waitForFunction(() => {
    return document.querySelectorAll('.skel-overlay').length === 0;
  }, { timeout: 10000 }).catch(() => {});
  await page.waitForTimeout(800); // let the IIFE wire all handlers
}

/**
 * Mock the axe-fleet telemetry endpoints so dashboard boot is fast and
 * deterministic. The REAL /api/axe-fleet/health triggers connector fetches
 * with 5s timeouts per device (unreachable LAN IPs), which stalls the dev
 * server under sequential E2E load and made full-suite runs flaky. These
 * tests only exercise the tenant-auth UI — fleet telemetry is out of scope
 * (covered by tests/test_tenant_b2_isolation.py), so mocking it is safe.
 */
async function mockFleetEndpoints(page) {
  await page.route('**/api/axe-fleet/health', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ fleet_stats: { online: 0, warning: 0, offline: 0, total: 0 }, devices: [] }),
    });
  });
  await page.route('**/api/axe-fleet/devices**', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify([]),
    });
  });
}

async function expectModalOpen(page, id) {
  const modal = page.locator(`#${id}`);
  await expect(modal).toHaveClass(/modal--open/, { timeout: 5000 });
  await expect(modal).toBeVisible({ timeout: 5000 });
  await expect(modal).toHaveCSS('opacity', '1');          // ← the invisible-modal bug
  await expect(modal).toHaveCSS('pointer-events', 'auto'); // ← the un-clickable overlay bug
}

/** Mock /api/auth/* so the suite runs without a real API key. */
async function mockAuthEndpoints(page, { loginStatus = 200 } = {}) {
  await page.route('**/api/auth/login', async (route) => {
    if (loginStatus !== 200) {
      await route.fulfill({
        status: loginStatus,
        contentType: 'application/json',
        body: JSON.stringify({ error: 'invalid api_key' }),
      });
      return;
    }
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        success: true,
        access_token: MOCK_ACCESS,
        refresh_token: MOCK_REFRESH,
        expires_at: Math.floor(Date.now() / 1000) + 3600,
        token_type: 'Bearer',
        tenant_id: MOCK_TENANT,
      }),
    });
  });
  await page.route('**/api/auth/refresh', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        success: true,
        access_token: MOCK_ACCESS + '-rotated',
        expires_at: Math.floor(Date.now() / 1000) + 3600,
        token_type: 'Bearer',
        tenant_id: MOCK_TENANT,
      }),
    });
  });
  await page.route('**/api/auth/logout', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ success: true }),
    });
  });
}

async function openAuthModal(page) {
  await page.locator('#auth-toggle').click();
  await expectModalOpen(page, 'auth-modal');
}

async function loginAs(page, apiKey) {
  await openAuthModal(page);
  await page.locator('#auth-api-key').fill(apiKey);
  await page.locator('#auth-login').click();
  await expect(page.locator('#auth-status')).toContainText('connected as', { timeout: 5000 });
}

/**
 * authUpdateUi() sets #auth-logout's inline style.display directly
 * ('' when connected, 'none' when not). Assert the inline style instead of
 * toBeVisible() — the logout button lives INSIDE the modal, which the login
 * handler auto-closes after 400ms, so element visibility is state-dependent
 * and racy. The inline style is deterministic.
 */
async function expectLogoutDisplay(page, value) {
  await expect.poll(async () =>
    page.locator('#auth-logout').evaluate((el) => el.style.display)
  ).toBe(value);
}

async function expectAuthToggle(page, label) {
  const toggle = page.locator('#auth-toggle');
  await expect(toggle).toHaveText(label);
  await expect(toggle).toHaveAccessibleName(label);
}

// ══════════════════════════════════════════════════════════════════════
//  Suite
// ══════════════════════════════════════════════════════════════════════

test.describe('CYPHER65 — Tenant Login (Fase 4 · B1-frontend)', () => {

  test.beforeEach(async ({ page }) => {
    await mockFleetEndpoints(page); // before goto, so boot requests are intercepted
    // waitUntil 'domcontentloaded': #app-shell is static HTML present at
    // DOMContentLoaded — no need to wait for external CDN resources (Google
    // Fonts / Chart.js) that can stall the 'load' event on slow networks.
    await page.goto(BASE_URL, { waitUntil: 'domcontentloaded' });
    await waitForDashboard(page);
  });

  test.describe('01 — Auth modal opens / closes', () => {

    test('topbar toggle opens the modal fully (class, visible, opacity, pointer-events)', async ({ page }) => {
      await openAuthModal(page);
      await expect(page.locator('#auth-modal .modal__title')).toHaveText('>> TENANT LOGIN');
      await expect(page.locator('#auth-current-tenant')).toHaveText('—');
    });

    test('X button closes the modal and removes the overlay state', async ({ page }) => {
      await openAuthModal(page);
      await page.locator('#auth-modal .modal__close').click();
      await expect(page.locator('#auth-modal')).not.toHaveClass(/modal--open/);
      await expect(page.locator('#auth-modal')).not.toBeVisible();
    });
  });

  test.describe('02 — Login updates the tenant UI', () => {

    test('successful login → badge TENANT: acme (green), toggle ACME, logout display:""', async ({ page }) => {
      await mockAuthEndpoints(page);
      await loginAs(page, 'key-acme-1');

      await expect(page.locator('#auth-status')).toHaveText('✓ connected as acme');
      await expect(page.locator('#axe-fleet-tenant-badge')).toHaveText('TENANT: acme');
      await expect(page.locator('#axe-fleet-tenant-badge')).toHaveClass(/badge--green/);
      await expectAuthToggle(page, 'ACME');
      await expect(page.locator('#auth-toggle')).toHaveClass(/is-authed/);
      await expect(page.locator('#auth-current-tenant')).toHaveText('acme');
      await expectLogoutDisplay(page, ''); // logout button enabled
    });

    test('session is persisted to localStorage (_cypher65_auth_session)', async ({ page }) => {
      await mockAuthEndpoints(page);
      await loginAs(page, 'key-acme-1');

      const session = await page.evaluate(() => {
        try { return JSON.parse(localStorage.getItem('_cypher65_auth_session')); }
        catch (e) { return null; }
      });
      expect(session).not.toBeNull();
      expect(session.access_token).toBe(MOCK_ACCESS);
      expect(session.tenant_id).toBe(MOCK_TENANT);
    });

    test('Authorization: Bearer header is attached to /api/axe-fleet/health after login', async ({ page }) => {
      await mockAuthEndpoints(page);

      // Capture every axe-fleet/health request (boot + post-login) and later
      // assert one carried the Bearer header — robust against request ordering.
      const seen = [];
      page.on('request', (req) => {
        if (req.url().includes('/api/axe-fleet/health')) {
          seen.push(req.headers()['authorization'] || '');
        }
      });

      await loginAs(page, 'key-acme-1');

      await expect.poll(() => seen.some((h) => h === 'Bearer ' + MOCK_ACCESS),
        { timeout: 10000 }).toBe(true);
    });

    test('empty API key → inline validation, no state change', async ({ page }) => {
      await openAuthModal(page);
      await page.locator('#auth-login').click();

      await expect(page.locator('#auth-status')).toHaveText('⚠ API key required');
      await expect(page.locator('#axe-fleet-tenant-badge')).toHaveText('TENANT: default');
      await expectAuthToggle(page, 'LOGIN');
    });

    test('invalid API key (401 mock) → error status, UI stays default', async ({ page }) => {
      await mockAuthEndpoints(page, { loginStatus: 401 });
      await openAuthModal(page);
      await page.locator('#auth-api-key').fill('wrong-key');
      await page.locator('#auth-login').click();

      await expect(page.locator('#auth-status')).toContainText('invalid api_key', { timeout: 5000 });
      await expect(page.locator('#auth-status')).toHaveClass(/modal__status--err/);
      await expect(page.locator('#axe-fleet-tenant-badge')).toHaveText('TENANT: default');
      await expectAuthToggle(page, 'LOGIN');
    });
  });

  test.describe('03 — Session persists across reload', () => {

    test('after login + hard reload the tenant badge/toggle survive', async ({ page }) => {
      await mockAuthEndpoints(page);
      await loginAs(page, 'key-acme-1');

      await page.reload({ waitUntil: 'domcontentloaded' });
      await waitForDashboard(page);

      await expect(page.locator('#axe-fleet-tenant-badge')).toHaveText('TENANT: acme', { timeout: 5000 });
      await expect(page.locator('#axe-fleet-tenant-badge')).toHaveClass(/badge--green/);
      await expectAuthToggle(page, 'ACME');
    });
  });

  test.describe('04 — Logout resets to default tenant', () => {

    test('logout clears session and returns UI to TENANT: default', async ({ page }) => {
      await mockAuthEndpoints(page);
      await loginAs(page, 'key-acme-1');

      // The login handler auto-closes the modal after 400ms, and the logout
      // button lives inside it — reopen the modal before clicking LOGOUT.
      await openAuthModal(page);
      await expectLogoutDisplay(page, ''); // enabled while connected
      await page.locator('#auth-logout').click();

      await expect(page.locator('#axe-fleet-tenant-badge')).toHaveText('TENANT: default', { timeout: 5000 });
      await expect(page.locator('#axe-fleet-tenant-badge')).toHaveClass(/badge--mute/);
      await expectAuthToggle(page, 'LOGIN');
      await expect(page.locator('#auth-current-tenant')).toHaveText('—');
      await expectLogoutDisplay(page, 'none'); // disabled after logout

      const session = await page.evaluate(() => localStorage.getItem('_cypher65_auth_session'));
      expect(session).toBeNull();
    });
  });

  test.describe('05 — No console noise during the auth flow', () => {

    test('login + logout produce no critical console errors', async ({ page }) => {
      await mockAuthEndpoints(page);
      const errors = [];
      page.on('console', (msg) => {
        if (msg.type() === 'error') errors.push(msg.text());
      });
      page.on('pageerror', (err) => errors.push('pageerror: ' + err.message));

      await loginAs(page, 'key-acme-1');
      await openAuthModal(page);
      await page.locator('#auth-logout').click();
      await page.waitForTimeout(600);

      expect(errors.length).toBe(0,
        `Critical console errors during auth flow: ${JSON.stringify(errors)}`
      );
    });
  });
});
