/**
 * CYPHER65 War Room — E2E BTC Upgrade Tab (Issue #249)
 * ======================================================
 *
 * Prerequisites: Flask server running on BASE_URL (default http://127.0.0.1:8765)
 *
 * Run:  npx playwright test tests/e2e/upgrade-btc.spec.js --project=chromium --workers=1
 *
 * What this covers
 * ----------------
 * The Bitcoin tab of the PRO upgrade modal (P4 #249):
 *   - Bitcoin is the DEFAULT tab; Card is a discreet fallback
 *   - BTCPay checkout → pending state (amount in sats, QR, countdown,
 *     OPEN CHECKOUT, copy) and the status poll flipping to Settled →
 *     "PRO ATIVADO ✓" with the license key applied (X-License-Key)
 *   - pending (New) status renders "Aguardando pagamento..."
 *   - WebLN fallback: BOLT-11 QR + "PAY WITH LIGHTNING" CTA that pays via
 *     window.webln.sendPayment and activates through /api/upgrade/webln/confirm
 *   - WebLN ABSENT → CTA disappears (never errors) — issue acceptance
 *   - Card tab switch still shows the Lemon Squeezy buy button
 *
 * API is route-mocked (hermetic — no real BTCPay/LS/WebLN involved).
 */

import { test, expect } from '@playwright/test';

const BASE_URL = process.env.BASE_URL || 'http://127.0.0.1:8765';

const KEY = 'C65-AAAA-BBBB-CCCC-DDDD';
const LICENSE_STORAGE_KEY = '_cypher65_license';
const BOLT11 = 'lnbc12000n1pjmockupgradebolt11invoiceqqqq';

/** License-status payload: BTC live (BTCPay), no card provider. */
function licenseStatusBtcOnly() {
  return {
    mode: 'licensed', tier: 'free', pro: false, premium: false,
    license_state: 'license_required', key_valid: false,
    checkout_state: 'available', payment_state: 'not_started',
    ai_configured: false, payments: null, payment_plans: { pro: false, premium: false }, btcpay: true, webln: false,
    payment_btc_address: '35gjAoadgQxrNc1Kx6QiSLx7wCCXRnRFkM',
    upgrade: { plan: 'PRO', price_usd_month: 9 },
  };
}
/** License-status payload: BTC live + already PRO (activation assertions). */
function licenseStatusPro() {
  const b = licenseStatusBtcOnly();
  b.pro = true; b.tier = 'pro'; b.license_state = 'paid_active'; b.key_valid = true; b.payment_state = 'confirmed';
  return b;
}
/** License-status payload: both BTC and card providers live. */
function licenseStatusBoth() {
  const b = licenseStatusBtcOnly();
  b.payments = 'lemon_squeezy';
  b.payment_plans = { pro: true, premium: false };
  return b;
}

function licenseStatusUnavailable() {
  return {
    mode: 'open', tier: 'premium', pro: true, premium: true,
    license_state: 'trial_active', key_valid: null, access_source: 'open_beta',
    checkout_state: 'unavailable', payment_state: 'checkout_unavailable',
    ai_configured: false, payments: null, payment_plans: { pro: false, premium: false },
    btcpay: false, webln: false, upgrade: null,
  };
}

/** BTCPay checkout payload (mirrors services/btcpay.py contract). */
function checkoutBtcpay(invoiceId = 'inv_e2e_1') {
  return {
    ok: true, method: 'btc', provider: 'btcpay', plan: 'pro',
    invoice_id: invoiceId,
    status_token: 'e2e-status-token',
    checkout_url: `https://btcpay.example.com/i/${invoiceId}`,
    amount_sat: 12000, expires_in_min: 15, checkout_state: 'ready', payment_state: 'pending',
  };
}
/** WebLN fallback checkout payload (BOLT-11). */
function checkoutWebln() {
  return {
    ok: true, method: 'lightning', provider: 'webln', plan: 'pro',
    bolt11: BOLT11, amount_sat: 12000, payment_hash: 'ab'.repeat(32),
    checkout_state: 'ready', payment_state: 'pending',
  };
}

async function waitForDashboard(page) {
  await page.waitForSelector('#app-shell', { timeout: 15000 });
  await page.waitForSelector('#open-wallet', { timeout: 10000 });
  await page.waitForFunction(() => {
    return document.querySelectorAll('.skel-overlay').length === 0;
  }, { timeout: 10000 }).catch(() => {});
  await page.waitForTimeout(800); // let the IIFE wire all handlers
}

async function expectModalOpen(page, id) {
  const modal = page.locator(`#${id}`);
  await expect(modal).toHaveClass(/modal--open/, { timeout: 5000 });
  await expect(modal).toBeVisible({ timeout: 5000 });
}

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

/** Mock the API surface the BTC tab depends on. */
async function mockApi(page, { license, status, checkout, weblnConfirm, donations } = {}) {
  await page.route('**/api/license-status', route => {
    const body = typeof license === 'function' ? license(route.request()) : license;
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) });
  });
  if (checkout) {
    await page.route('**/api/upgrade/checkout', route => {
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(checkout) });
    });
  }
  if (status) {
    await page.route('**/api/upgrade/status/**', route => {
      expect(route.request().headers()['x-checkout-token']).toBe('e2e-status-token');
      expect(route.request().url()).not.toContain('token=');
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(status) });
    });
  }
  if (weblnConfirm) {
    await page.route('**/api/upgrade/webln/confirm', route => {
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(weblnConfirm) });
    });
  }
  if (donations) {
    await page.route('**/api/donations', route => {
      route.fulfill({ status: 201, contentType: 'application/json', body: JSON.stringify({ success: true }) });
    });
  }
  // Funnel telemetry is best-effort — keep it quiet.
  await page.route('**/api/conversion/track', route => {
    route.fulfill({ status: 200, contentType: 'application/json', body: '{}' });
  });
}

test.describe('BTC upgrade tab (P4 #249)', () => {
  // Block the Service Worker so page.route() intercepts fetch reliably
  // (the app's SW is network-first and can bypass mock routes).
  test.use({ serviceWorkers: 'block' });
  test('Bitcoin is the default tab; Card is hidden without a card provider', async ({ page }) => {
    await mockApi(page, { license: licenseStatusBtcOnly() });
    await page.goto(BASE_URL);
    await waitForDashboard(page);
    const errors = setupErrorCapture(page);

    await page.evaluate(() => window.openUpgradeModal());
    await expectModalOpen(page, 'upgrade-modal');

    const btcTab = page.locator('#upgrade-tab-btc');
    const cardTab = page.locator('#upgrade-tab-card');
    await expect(btcTab).toBeVisible();
    await expect(btcTab).toHaveClass(/is-active/);
    await expect(btcTab).toHaveAttribute('aria-selected', 'true');
    // Card provider absent → Card tab hidden; BTC pane visible with price.
    await expect(cardTab).toBeHidden();
    await expect(page.locator('#upgrade-pane-btc')).toBeVisible();
    await expect(page.locator('#upgrade-pane-card')).toBeHidden();
    await expect(page.locator('#upgrade-btc-price')).toHaveText('PRO — $9/mo via Bitcoin');
    await expect(page.locator('#upgrade-btc-start-btn')).toBeVisible();
    // Card Buy button is NOT reachable without a provider.
    await expect(page.locator('#upgrade-buy-btn')).toBeHidden();
    expect(errors.critical()).toEqual([]);
  });

  test('BTCPay checkout renders amount in sats, QR, countdown, OPEN CHECKOUT and copy', async ({ page }) => {
    await mockApi(page, {
      license: licenseStatusBtcOnly(),
      checkout: checkoutBtcpay(),
      status: { ok: true, invoice_id: 'inv_e2e_1', status: 'New', payment_state: 'pending', amount: '0.00012', license_key: '' },
    });
    await page.context().grantPermissions(['clipboard-read', 'clipboard-write'], { origin: BASE_URL });
    await page.goto(BASE_URL);
    await waitForDashboard(page);
    const errors = setupErrorCapture(page);

    await page.evaluate(() => window.openUpgradeModal());
    await expectModalOpen(page, 'upgrade-modal');
    await page.locator('#upgrade-btc-start-btn').click();

    await expect(page.locator('#upgrade-btc-pending')).toBeVisible();
    await expect(page.locator('#upgrade-btc-start')).toBeHidden();
    // Amount: exact sats from the checkout payload + USD reference.
    await expect(page.locator('#upgrade-btc-amount')).toHaveText('12,000 sats · ≈ $9/mo');
    // QR renders (SVG from the pure-JS encoder).
    await expect(page.locator('#upgrade-btc-qr svg')).toBeVisible();
    // Countdown ticking (mm:ss).
    await expect(page.locator('#upgrade-btc-countdown')).toHaveText(/^\d{2}:\d{2}$/);
    // BTCPay path: hosted checkout CTA + copy link, no WebLN CTA.
    await expect(page.locator('#upgrade-btc-open')).toBeVisible();
    await expect(page.locator('#upgrade-btc-webln')).toBeHidden();
    // Copy feedback (clipboard or execCommand fallback).
    await page.locator('#upgrade-btc-copy').click();
    await expect(page.locator('#upgrade-btc-copy')).toHaveText('✓ copiado');
    expect(errors.critical()).toEqual([]);
  });

  test('status poll Settled → "PRO ATIVADO" with the license key applied', async ({ page }) => {
    await mockApi(page, {
      license: licenseStatusPro(),
      checkout: checkoutBtcpay(),
      status: { ok: true, invoice_id: 'inv_e2e_1', status: 'Settled', payment_state: 'confirmed', amount: '0.00012', license_key: KEY },
    });
    await page.goto(BASE_URL);
    await waitForDashboard(page);
    const errors = setupErrorCapture(page);

    await page.evaluate(() => window.openUpgradeModal());
    await expectModalOpen(page, 'upgrade-modal');
    await page.locator('#upgrade-btc-start-btn').click();

    // The immediate poll sees Settled + key → activated state.
    await expect(page.locator('#upgrade-btc-paid')).toBeVisible({ timeout: 10000 });
    await expect(page.locator('#upgrade-btc-paid')).toContainText('PRO ATIVADO');
    await expect(page.locator('#upgrade-btc-paid-key')).toHaveText(KEY);
    // Key applied to localStorage (X-License-Key rides on every API call).
    const stored = await page.evaluate(k => localStorage.getItem(k), LICENSE_STORAGE_KEY);
    expect(stored).toBe(KEY);
    expect(errors.critical()).toEqual([]);
  });

  test('pending status renders "Aguardando pagamento..."', async ({ page }) => {
    await mockApi(page, {
      license: licenseStatusBtcOnly(),
      checkout: checkoutBtcpay('inv_e2e_pending'),
      status: { ok: true, invoice_id: 'inv_e2e_pending', status: 'New', payment_state: 'pending', amount: '0.00012', license_key: '' },
    });
    await page.goto(BASE_URL);
    await waitForDashboard(page);

    await page.evaluate(() => window.openUpgradeModal());
    await expectModalOpen(page, 'upgrade-modal');
    await page.locator('#upgrade-btc-start-btn').click();
    await expect(page.locator('#upgrade-btc-status')).toContainText('Aguardando pagamento', { timeout: 10000 });
  });

  test('WebLN fallback: CTA pays via sendPayment and activates PRO', async ({ page }) => {
    // Inject a spec-compliant provider BEFORE the page scripts run.
    await page.addInitScript(() => {
      const provider = {
        _calls: { enable: 0, sendPayment: 0 },
        enable: async () => { provider._calls.enable++; },
        getInfo: async () => ({ node: { alias: 'E2E Mock', pubkey: 'x'.repeat(66) } }),
        sendPayment: async () => {
          provider._calls.sendPayment++;
          return { preimage: 'ab'.repeat(32) }; // 32-byte hex preimage
        },
      };
      window.webln = provider;
    });
    await mockApi(page, {
      license: request => request.headers()['x-license-key'] ? licenseStatusPro() : licenseStatusBtcOnly(),
      checkout: checkoutWebln(),
      weblnConfirm: { ok: true, payment_state: 'confirmed', license_key: 'C65-WEBN-1111-2222-3333' },
      donations: true,
    });
    await page.goto(BASE_URL);
    await waitForDashboard(page);
    const errors = setupErrorCapture(page);

    await page.evaluate(() => window.openUpgradeModal());
    await expectModalOpen(page, 'upgrade-modal');
    await page.locator('#upgrade-btc-start-btn').click();

    // WebLN fallback: BOLT-11 QR + PAY WITH LIGHTNING CTA (webln present).
    await expect(page.locator('#upgrade-btc-webln')).toBeVisible();
    await expect(page.locator('#upgrade-btc-open')).toBeHidden();
    await expect(page.locator('#upgrade-btc-qr svg')).toBeVisible();

    await page.locator('#upgrade-btc-webln').click();
    // Preimage proof → server confirms → key applied → activated.
    await expect(page.locator('#upgrade-btc-paid')).toBeVisible({ timeout: 10000 });
    await expect(page.locator('#upgrade-btc-paid')).toContainText('PRO ATIVADO');
    const stored = await page.evaluate(k => localStorage.getItem(k), LICENSE_STORAGE_KEY);
    expect(stored).toBe('C65-WEBN-1111-2222-3333');
    expect(errors.critical()).toEqual([]);
  });

  test('WebLN absent → PAY WITH LIGHTNING CTA disappears, no errors', async ({ page }) => {
    await mockApi(page, { license: licenseStatusBtcOnly(), checkout: checkoutWebln() });
    await page.goto(BASE_URL);
    await waitForDashboard(page);
    const errors = setupErrorCapture(page);

    await page.evaluate(() => window.openUpgradeModal());
    await expectModalOpen(page, 'upgrade-modal');
    await page.locator('#upgrade-btc-start-btn').click();

    // No window.webln → CTA hidden (issue acceptance), rest still renders.
    await expect(page.locator('#upgrade-btc-webln')).toBeHidden();
    await expect(page.locator('#upgrade-btc-qr svg')).toBeVisible();
    await expect(page.locator('#upgrade-btc-copy')).toHaveText('⧉ COPIAR INVOICE');
    expect(errors.critical()).toEqual([]);
  });

  test('Card tab switch shows the Lemon Squeezy Buy button', async ({ page }) => {
    await mockApi(page, { license: licenseStatusBoth() });
    await page.goto(BASE_URL);
    await waitForDashboard(page);
    const errors = setupErrorCapture(page);

    await page.evaluate(() => window.openUpgradeModal());
    await expectModalOpen(page, 'upgrade-modal');

    // Bitcoin default, then switch to Card.
    await expect(page.locator('#upgrade-tab-btc')).toHaveClass(/is-active/);
    await page.locator('#upgrade-tab-card').click();
    await expect(page.locator('#upgrade-tab-card')).toHaveClass(/is-active/);
    await expect(page.locator('#upgrade-pane-btc')).toBeHidden();
    await expect(page.locator('#upgrade-pane-card')).toBeVisible();
    await expect(page.locator('#upgrade-buy-btn')).toBeVisible();

    // And back to Bitcoin.
    await page.locator('#upgrade-tab-btc').click();
    await expect(page.locator('#upgrade-pane-btc')).toBeVisible();
    expect(errors.critical()).toEqual([]);
  });

  test('no provider shows beta/trial copy and never exposes a purchase CTA', async ({ page }) => {
    await mockApi(page, { license: licenseStatusUnavailable() });
    await page.goto(BASE_URL);
    await waitForDashboard(page);
    await page.evaluate(() => window.openUpgradeModal());
    await expectModalOpen(page, 'upgrade-modal');
    await expect(page.locator('#upgrade-unavailable')).toBeVisible();
    await expect(page.locator('#upgrade-unavailable')).toContainText('Checkout indisponível');
    await expect(page.locator('#upgrade-tabs')).toBeHidden();
    await expect(page.locator('#upgrade-btc-start-btn')).toBeHidden();
    await expect(page.locator('#upgrade-buy-btn')).toBeHidden();
    await expect(page.locator('#upgrade-premium-buy-btn')).toBeHidden();
    await expect(page.locator('#upgrade-redeem-btn')).toBeVisible();
  });

  test('invalid frontend key is rejected before localStorage changes', async ({ page }) => {
    await mockApi(page, {
      license: request => request.headers()['x-license-key']
        ? { ...licenseStatusUnavailable(), submitted_license_state: 'invalid', key_valid: false }
        : licenseStatusUnavailable(),
    });
    await page.goto(BASE_URL);
    await waitForDashboard(page);
    await page.evaluate(() => window.openUpgradeModal());
    await page.locator('#upgrade-key-input').fill('C65-FAKE-FAKE-FAKE-FAKE');
    await page.locator('#upgrade-redeem-btn').click();
    await expect(page.locator('#upgrade-status')).toContainText('Licença inválida');
    const stored = await page.evaluate(k => localStorage.getItem(k), LICENSE_STORAGE_KEY);
    expect(stored).toBeNull();
    await expect(page.locator('#upgrade-modal')).toHaveClass(/modal--open/);
  });
});
