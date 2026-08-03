/**
 * CYPHER65 War Room — E2E WebLN Tests
 * ====================================
 *
 * Prerequisites: Flask server running on BASE_URL (default http://127.0.0.1:8765)
 *
 * Run:  npx playwright test tests/e2e/webln.spec.js --project=chromium --workers=1
 *
 * What this covers
 * ---------------
 * Real browser extensions (Alby / Joule) cannot be installed at runtime in a
 * headless E2E run. The industry-standard approach — and exactly what Alby/Joule
 * expose to web pages — is `window.webln` with `enable()`, `getInfo()`,
 * `sendPayment()`, `makeInvoice()`, `getBalance()`, `signMessage()` plus the
 * `webln:ready` document event. This spec injects a spec-compliant mock provider
 * via `page.addInitScript` and validates the full `connectWebLN()` flow:
 *
 *   - detection (sync provider AND late `webln:ready` injection)
 *   - permission request (`enable()`)
 *   - node info preview + CONFIRM / CANCEL
 *   - CONFIRM with a `walletAddress` (auto-fill + auto-save)
 *   - CONFIRM WITHOUT a `walletAddress` — the REAL Alby behavior, since the
 *     WebLN spec getInfo() returns only { node: { alias, pubkey } } — which
 *     must fall back to the "enter it manually" info message
 *   - permission denied and getInfo failure error states
 *   - sendPayment() from the support panel (BOLT11 invoice)
 *   - no critical console errors throughout
 */

import { test, expect } from '@playwright/test';

const BASE_URL = process.env.BASE_URL || 'http://127.0.0.1:8765';

// Valid bech32 address (known-valid test vector used across the test suite).
const VALID_BTC = 'bc1qar0srrr7xfkvy5l643lydnw9re59gtzzwf5mdq';

// ══════════════════════════════════════════════════════════════════════
//  Helpers
// ══════════════════════════════════════════════════════════════════════

/** Wait for the app shell + topbar to be ready (no data dependency). */
async function waitForDashboard(page) {
  await page.waitForSelector('#app-shell', { timeout: 15000 });
  await page.waitForSelector('#open-wallet', { timeout: 10000 });
  // Skeletons are pointer-events:none now, but wait for them to detach so a
  // click can never race the first render.
  await page.waitForFunction(() => {
    return document.querySelectorAll('.skel-overlay').length === 0;
  }, { timeout: 10000 }).catch(() => {});
  await page.waitForTimeout(800); // let the IIFE wire all handlers
}

/** Assert a modal is open AND actually interactive (regression guard). */
async function expectModalOpen(page, id) {
  const modal = page.locator(`#${id}`);
  await expect(modal).toHaveClass(/modal--open/, { timeout: 5000 });
  await expect(modal).toBeVisible({ timeout: 5000 });
  await expect(modal).toHaveCSS('opacity', '1');
  await expect(modal).toHaveCSS('pointer-events', 'auto');
}

/** Assert a modal is fully closed. */
async function expectModalClosed(page, id) {
  const modal = page.locator(`#${id}`);
  await expect(modal).not.toHaveClass(/modal--open/, { timeout: 5000 });
  await expect(modal).not.toBeVisible({ timeout: 5000 });
}

/** Attach console + pageerror listeners and return captured errors. */
function setupErrorCapture(page) {
  const errors = [];
  page.on('console', msg => {
    if (msg.type() === 'error') errors.push(msg.text());
  });
  page.on('pageerror', err => errors.push(err.message));
  return {
    all() { return errors; },
    critical() {
      return errors.filter(e =>
        !e.includes('[boot]') && !e.includes('ServiceWorker') && !e.includes('404')
      );
    },
  };
}

/**
 * Inject a spec-compliant WebLN provider BEFORE the page scripts run.
 * `opts`:
 *   - denyEnable   : enable() rejects with `denyError` (default 'user cancelled')
 *   - getInfoError : getInfo() rejects with this message
 *   - walletAddress: if set, getInfo() also returns a walletAddress
 *   - alias/pubkey : node identity used in the preview
 *   - preimage     : sendPayment() success preimage
 *   - late         : do NOT set window.webln at load; expose window.__injectWebLN()
 *                    which sets it + dispatches the `webln:ready` event
 */
async function injectMockWebLN(page, opts = {}) {
  await page.addInitScript((cfg) => {
    const provider = {
      _calls: { enable: 0, getInfo: 0, sendPayment: 0 },
      enable: async () => {
        provider._calls.enable++;
        if (cfg.denyEnable) throw new Error(cfg.denyError || 'user cancelled');
      },
      getInfo: async () => {
        provider._calls.getInfo++;
        if (cfg.getInfoError) throw new Error(cfg.getInfoError);
        const info = {
          providerName: cfg.providerName || 'Mock Alby',
          node: {
            alias: cfg.alias || 'mock-alby-node',
            pubkey: cfg.pubkey || '02f1a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d7e8f9a0b1c2d3e4f5a6b7c8d9e0f1a2',
            color: '#f5b942',
          },
        };
        if (cfg.walletAddress) info.walletAddress = cfg.walletAddress;
        return info;
      },
      sendPayment: async (invoice) => {
        provider._calls.sendPayment++;
        return { preimage: cfg.preimage || '0123456789abcdef0123456789abcdef' };
      },
      makeInvoice: async () => ({ paymentRequest: 'lnbc1mockinvoice' }),
      getBalance: async () => ({ balance: 21000 }),
      signMessage: async () => ({ signature: 'mock-signature' }),
      methods: ['getInfo', 'enable', 'sendPayment', 'makeInvoice', 'getBalance', 'signMessage'],
    };
    if (cfg.late) {
      window.__injectWebLN = () => {
        window.webln = provider;
        document.dispatchEvent(new Event('webln:ready'));
      };
    } else {
      window.webln = provider;
      window.__weblnMock = provider;
    }
  }, opts);
}

/** Open the wallet modal + click ⚡ LN WALLET (entry point of connectWebLN). */
async function startConnectWebLN(page) {
  await page.locator('#open-wallet').click();
  await expectModalOpen(page, 'wallet-modal');
  await page.locator('#webln-connect-btn').click();
}

// ══════════════════════════════════════════════════════════════════════
//  Tests
// ══════════════════════════════════════════════════════════════════════

test.describe('CYPHER65 — WebLN flow (mock Alby/Joule provider)', () => {

  // ──────────────────────────────────────────────────────────────────
  //  SECTION 1: Detection + errors
  // ──────────────────────────────────────────────────────────────────

  test.describe('01 — Detection & error states', () => {

    test('shows a clear error when no WebLN wallet is installed', async ({ page }) => {
      await page.goto(BASE_URL);
      await waitForDashboard(page);
      await startConnectWebLN(page);

      // detectWebLN times out after 4s with no provider.
      const status = page.locator('#webln-status');
      await expect(status).toContainText('No WebLN wallet detected', { timeout: 10000 });
      await expect(status).toHaveClass(/webln-status--error/);
    });

    test('detects a sync provider, requests permission and shows the preview', async ({ page }) => {
      await injectMockWebLN(page, { alias: 'alby-test-node' });
      await page.goto(BASE_URL);
      await waitForDashboard(page);
      await startConnectWebLN(page);

      const status = page.locator('#webln-status');
      await expect(status).toContainText('WebLN wallet ready — review and confirm', { timeout: 10000 });
      await expect(status).toHaveClass(/webln-status--success/);

      // Preview shows provider + node identity and the CONFIRM / CANCEL actions.
      const preview = page.locator('#webln-preview');
      await expect(preview).toBeVisible({ timeout: 5000 });
      await expect(preview).toContainText('Mock Alby');
      await expect(preview).toContainText('alby-test-node');
      await expect(page.locator('#webln-confirm-btn')).toBeVisible();
      await expect(page.locator('#webln-cancel-btn')).toBeVisible();

      // Permission request actually happened (enable() was called).
      const calls = await page.evaluate(() => window.__weblnMock._calls.enable);
      expect(calls).toBeGreaterThanOrEqual(1);
    });

    test('shows a permission denied error when enable() rejects', async ({ page }) => {
      await injectMockWebLN(page, { denyEnable: true, denyError: 'user rejected the prompt' });
      await page.goto(BASE_URL);
      await waitForDashboard(page);
      await startConnectWebLN(page);

      const status = page.locator('#webln-status');
      await expect(status).toContainText('Permission denied', { timeout: 10000 });
      await expect(status).toContainText('user rejected the prompt');
      await expect(status).toHaveClass(/webln-status--error/);
    });

    test('shows a node-info error when getInfo() rejects', async ({ page }) => {
      await injectMockWebLN(page, { getInfoError: 'node unreachable' });
      await page.goto(BASE_URL);
      await waitForDashboard(page);
      await startConnectWebLN(page);

      const status = page.locator('#webln-status');
      await expect(status).toContainText('Failed to get node info', { timeout: 10000 });
      await expect(status).toContainText('node unreachable');
      await expect(status).toHaveClass(/webln-status--error/);
    });

    test('detects a provider injected LATE via the webln:ready event', async ({ page }) => {
      await injectMockWebLN(page, { late: true, alias: 'late-alby' });
      await page.goto(BASE_URL);
      await waitForDashboard(page);

      // Start detection with NO provider present (the 4s listen window opens)…
      await page.locator('#open-wallet').click();
      await expectModalOpen(page, 'wallet-modal');
      await page.locator('#webln-connect-btn').click();

      // …wait until detection is actively listening for the event, then the
      // extension appears and dispatches webln:ready (Alby/Joule do exactly
      // this when their content script finishes loading).
      await expect(page.locator('#webln-status')).toContainText('Detecting Lightning wallet', { timeout: 5000 });
      await page.evaluate(() => window.__injectWebLN());

      const status = page.locator('#webln-status');
      await expect(status).toContainText('WebLN wallet ready — review and confirm', { timeout: 10000 });
      await expect(page.locator('#webln-preview')).toContainText('late-alby');
    });
  });

  // ──────────────────────────────────────────────────────────────────
  //  SECTION 2: Confirm / Cancel flows
  // ──────────────────────────────────────────────────────────────────

  test.describe('02 — Confirm & Cancel', () => {

    test('CONFIRM without walletAddress falls back to manual entry (real Alby behavior)', async ({ page }) => {
      // The WebLN spec getInfo() does NOT return walletAddress — only node
      // identity. This is the exact shape a real Alby/Joule returns.
      await injectMockWebLN(page, { alias: 'real-alby' });
      await page.goto(BASE_URL);
      await waitForDashboard(page);
      await startConnectWebLN(page);

      await expect(page.locator('#webln-status')).toContainText('WebLN wallet ready', { timeout: 10000 });
      await page.locator('#webln-confirm-btn').click();

      const status = page.locator('#webln-status');
      await expect(status).toContainText('did not provide a BTC address', { timeout: 5000 });
      await expect(status).toContainText('Enter it manually above');
      await expect(status).toHaveClass(/webln-status--info/);

      // Preview dismissed, focus moved to the address input for manual entry.
      await expect(page.locator('#webln-preview')).toBeHidden({ timeout: 5000 });
      await page.waitForFunction(() => {
        const input = document.getElementById('wallet-address-input');
        return document.activeElement === input;
      }, { timeout: 5000 });
    });

    test('CONFIRM with walletAddress auto-fills the input, validates it and saves', async ({ page }) => {
      await injectMockWebLN(page, { walletAddress: VALID_BTC });
      await page.goto(BASE_URL);
      await waitForDashboard(page);
      await startConnectWebLN(page);

      await expect(page.locator('#webln-status')).toContainText('WebLN wallet ready', { timeout: 10000 });
      await page.locator('#webln-confirm-btn').click();

      // The address input is filled by the WebLN flow…
      const input = page.locator('#wallet-address-input');
      await expect(input).toHaveValue(VALID_BTC, { timeout: 5000 });

      // …real-time validation flags it as a valid Bech32 address…
      const validation = page.locator('#wallet-validation-status');
      await expect(validation).toHaveClass(/wallet-validation-status--valid/, { timeout: 5000 });
      await expect(validation).toContainText('Valid Bech32 address');

      // …and walletSave is auto-clicked (status becomes non-empty: connecting
      // or connected — the exact text depends on the backend's response, which
      // we do not hard-assert here).
      await page.waitForFunction(() => {
        const s = document.getElementById('wallet-status');
        return s && s.textContent.trim().length > 0;
      }, { timeout: 8000 });
    });

    test('CANCEL hides the preview and clears the state', async ({ page }) => {
      await injectMockWebLN(page, { alias: 'cancel-node' });
      await page.goto(BASE_URL);
      await waitForDashboard(page);
      await startConnectWebLN(page);

      await expect(page.locator('#webln-preview')).toBeVisible({ timeout: 10000 });
      await page.locator('#webln-cancel-btn').click();

      await expect(page.locator('#webln-preview')).toBeHidden({ timeout: 5000 });
      await expect(page.locator('#webln-status')).toHaveText('');

      // State reset: a second attempt re-detects cleanly.
      await page.locator('#webln-connect-btn').click();
      await expect(page.locator('#webln-preview')).toBeVisible({ timeout: 10000 });
    });
  });

  // ──────────────────────────────────────────────────────────────────
  //  SECTION 3: sendPayment via the Support panel
  // ──────────────────────────────────────────────────────────────────

  test.describe('03 — sendPayment (support panel)', () => {

    test('support panel opens from the ◈ Details button (display:none fix regression)', async ({ page }) => {
      await page.goto(BASE_URL);
      await waitForDashboard(page);
      await page.locator('#support-expand-btn').click();
      await expectModalOpen(page, 'support-panel');
    });

    test('pays a BOLT11 invoice and shows the preimage', async ({ page }) => {
      await injectMockWebLN(page, { preimage: 'deadbeef0123456789abcdef0123456789' });
      await page.goto(BASE_URL);
      await waitForDashboard(page);

      await page.locator('#support-expand-btn').click();
      await expectModalOpen(page, 'support-panel');

      await page.locator('#ln-invoice-input').fill('lnbc1mockinvoice');
      await page.locator('#ln-pay-btn').click();

      const status = page.locator('#ln-payment-status');
      await expect(status).toContainText('Payment sent!', { timeout: 10000 });
      // The app shortens the preimage display to its first 16 chars + ellipsis.
      await expect(status).toContainText('deadbeef01234567');
      await expect(status).toHaveClass(/support-modal__ln-status--success/);
    });

    test('rejects an empty invoice without calling the provider', async ({ page }) => {
      await injectMockWebLN(page, {});
      await page.goto(BASE_URL);
      await waitForDashboard(page);

      await page.locator('#support-expand-btn').click();
      await expectModalOpen(page, 'support-panel');

      await page.locator('#ln-pay-btn').click();

      const status = page.locator('#ln-payment-status');
      await expect(status).toContainText('Please paste a BOLT11 invoice', { timeout: 5000 });
      await expect(status).toHaveClass(/support-modal__ln-status--error/);

      const calls = await page.evaluate(() => window.__weblnMock._calls.sendPayment);
      expect(calls).toBe(0);
    });

    test('rejects a non-BOLT11 invoice without calling the provider', async ({ page }) => {
      await injectMockWebLN(page, {});
      await page.goto(BASE_URL);
      await waitForDashboard(page);

      await page.locator('#support-expand-btn').click();
      await expectModalOpen(page, 'support-panel');

      await page.locator('#ln-invoice-input').fill('not-an-invoice');
      await page.locator('#ln-pay-btn').click();

      const status = page.locator('#ln-payment-status');
      // PT-BR app copy (the UI is localized; the test previously asserted the
      // old EN text). Only the actionable parts are matched so a copy tweak
      // does not break the E2E.
      await expect(status).toContainText('lnbc1 (mainnet) ou lntb1', { timeout: 5000 });
      await expect(status).toHaveClass(/support-modal__ln-status--error/);

      const calls = await page.evaluate(() => window.__weblnMock._calls.sendPayment);
      expect(calls).toBe(0);
    });
  });

  // ──────────────────────────────────────────────────────────────────
  //  SECTION 4: Console hygiene
  // ──────────────────────────────────────────────────────────────────

  test.describe('04 — Console hygiene', () => {

    test('no critical console errors across the full WebLN interaction', async ({ page }) => {
      // Unique preimage per run: the backend dedupes donations by txid/
      // preimage (honest-telemetry design). Reusing the mock's constant
      // default across runs against a persistent DB made the donation POST
      // return 409 on the second run — a console error that is EXPECTED app
      // behavior, not a bug. A per-run preimage keeps the POST a 201.
      const uniquePreimage = 'e2e' + Date.now().toString(16).slice(-28);
      await injectMockWebLN(page, { alias: 'hygiene-node', preimage: uniquePreimage });
      const capture = setupErrorCapture(page);

      await page.goto(BASE_URL);
      await waitForDashboard(page);

      // connectWebLN: detect → preview → confirm (manual-entry fallback)
      await startConnectWebLN(page);
      await expect(page.locator('#webln-preview')).toBeVisible({ timeout: 10000 });
      await page.locator('#webln-confirm-btn').click();
      await expect(page.locator('#webln-status')).toContainText('did not provide a BTC address', { timeout: 5000 });

      // Close the wallet modal via ✕ (deterministic — does not depend on the
      // Escape key's sidebar-vs-modal precedence) so its overlay cannot
      // intercept the next click.
      await page.locator('#wallet-modal .modal__close').click();
      await expectModalClosed(page, 'wallet-modal');

      // support panel: open + pay
      await page.locator('#support-expand-btn').click();
      await expectModalOpen(page, 'support-panel');
      await page.locator('#ln-invoice-input').fill('lnbc1mockinvoice');
      await page.locator('#ln-pay-btn').click();
      await expect(page.locator('#ln-payment-status')).toContainText('Payment sent!', { timeout: 10000 });

      const critical = capture.critical();
      expect(critical.length).toBe(0,
        `Critical console errors during WebLN interactions: ${JSON.stringify(critical)}`
      );
    });
  });
});
