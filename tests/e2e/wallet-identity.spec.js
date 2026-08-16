/**
 * CYPHER65 War Room — E2E: WALLET IDENTITY CARD (P0-4)
 * ====================================================
 * Valida de ponta a ponta o card WALLET IDENTITY do modal CONNECT WALLET:
 *
 *   UI (⚡ CONNECT → colar endereço → SAVE)
 *     → POST /api/set-address            (validação real no backend)
 *     → toast "Wallet connectada" + modal fecha sozinho
 *     → card identidade: QR escaneável (SVG inline gerado por encoder JS
 *       puro), endereço com CHECKSUM destacado (.addr-ck), botão COPY e
 *       strip de HEALTH com 6 checks honestos
 *     → status bar também destaca os check-digits (.addr-ck em #sb-wallet-addr)
 *
 * O encoder QR é validado CELL-FOR-CELL contra golden fixtures (lib
 * independente) em tests/test_app_js_core.js — este spec prova que o card
 * renderiza de verdade no browser com um endereço real conectado via API.
 *
 * Endereço de teste: bech32 válido (validação backend confirmada) e o mesmo
 * usado nas golden fixtures do QR core (size 29×29 ECC M) — o viewBox do SVG
 * é determinístico (0 0 37 37 = 29 módulos + quiet zone 4) para este texto.
 *
 * Cleanup: o teste restaura o endereço anterior (ou limpa a chave persistida
 * quando não havia wallet) em `finally`, para nunca poluir o DB do dev entre
 * execuções do run-e2e.sh.
 *
 * Prerequisites: Flask server running on BASE_URL (default http://127.0.0.1:8765).
 * The server MUST be started via `bash run-e2e.sh` (RATE_LIMIT_PER_MINUTE=1000
 * — an env var that wins over .env). A plain dev server loads `.env` via
 * load_dotenv() (config.py), and if `.env` sets RATE_LIMIT_PER_MINUTE=60 the
 * dashboard polling + this suite's API calls exhaust that budget mid-run,
 * which 429s the SECOND project's POST /api/set-address (silent failure: no
 * toast). Keep the dev `.env` at >= 300.
 * Run:  npx playwright test tests/e2e/wallet-identity.spec.js
 * CI:   bash run-e2e.sh
 */

import { test, expect } from '@playwright/test';

const BASE_URL = process.env.BASE_URL || 'http://127.0.0.1:8765';

// Bech32 válido (BIP-173 sample) — checksum = últimos 6 chars = 'hx0wlh'.
// Mesmo texto da fixture golden `bech32M` (29×29 módulos ECC M).
const TEST_ADDR = 'bc1qxy2kgdygjrsqtzq2n0yrf2493p83kkfjhx0wlh';
const TEST_ADDR_CK = TEST_ADDR.slice(-6); // 'hx0wlh'

// ══════════════════════════════════════════════════════════════════════
//  Helpers (mesmas convenções de modals.spec.js / live-mining.spec.js)
// ══════════════════════════════════════════════════════════════════════

/** Wait for the app shell + topbar to be ready (no data dependency). */
async function waitForDashboard(page) {
  await page.waitForSelector('#app-shell', { timeout: 15000 });
  await page.waitForSelector('#open-wallet', { timeout: 10000 });
  await page.waitForFunction(() => {
    return document.querySelectorAll('.skel-overlay').length === 0;
  }, { timeout: 10000 }).catch(() => {});
  await page.waitForTimeout(800); // let the IIFE wire all handlers
}

/** Assert a modal is fully open (class + visible + interactive styles). */
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

/** Attach console + page error listeners and return captured errors. */
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
 * Restore wallet state for future runs — ONLY when this test changed it.
 *
 *  - If the server already had an address before us (previousAddr non-empty
 *    and != TEST_ADDR), reconnect it (resets the in-memory global AND the
 *    persisted row — /api/set-address does both).
 *  - If the server was empty before us, clear the persisted row so the next
 *    boot starts clean. (The in-memory global is NOT reset by /api/settings,
 *    but the E2E server is short-lived and the next run's decision is made
 *    from the DB-derived snapshot — actually the GLOBAL — see idempotency
 *    comment in the test; either way the next boot is clean.)
 *  - If we did NOT connect (already-connected rerun), touch nothing.
 */
async function restoreWalletState(page, previousAddr, didConnect) {
  if (!didConnect) return;
  try {
    if (previousAddr && previousAddr.toLowerCase() !== TEST_ADDR.toLowerCase()) {
      await page.request.post(`${BASE_URL}/api/set-address`, {
        data: { address: previousAddr },
      });
    } else {
      await page.request.post(`${BASE_URL}/api/settings`, {
        data: { _wallet_address: '', _wallet_worker: '' },
      });
    }
  } catch (e) {
    console.warn('[wallet-identity] cleanup falhou (best-effort):', e.message);
  }
}

// ══════════════════════════════════════════════════════════════════════
//  Tests
// ══════════════════════════════════════════════════════════════════════

test.describe('WALLET IDENTITY — QR + checksum + health (P0-4)', () => {

  test('conectar wallet → card identidade renderiza QR, checksum e health', async ({ page }) => {
    test.setTimeout(120000);
    const capture = setupErrorCapture(page);
    await page.goto(BASE_URL, { waitUntil: 'domcontentloaded' });
    await waitForDashboard(page);

    // ── Estado anterior do SERVIDOR (fonte da verdade — não window.BTC_ADDRESS,
    //    que só é populado no primeiro render e geraria race). ──
    let previousAddr = '';
    try {
      const snap = await (await page.request.get(`${BASE_URL}/api/snapshot`)).json();
      previousAddr = (snap && snap.btc_address) || '';
    } catch { /* snapshot indisponível — assume sem wallet */ }

    let didConnect = false;
    try {
      // ── Já conectado ao endereço de teste? Decisão pelo SNAPSHOT do servidor
      //    (authoritative): reruns não quebram com "address is the same as
      //    current", e um endereço real pré-existente nunca é sobrescrito. ──
      const alreadyConnected =
        String(previousAddr).toLowerCase() === TEST_ADDR.toLowerCase();

      if (!alreadyConnected) {
        didConnect = true;
        // ── CONNECT via UI: modal → endereço → SAVE ──
        await page.locator('#open-wallet').click();
        await expectModalOpen(page, 'wallet-modal');

        await page.locator('#wallet-address-input').fill(TEST_ADDR);
        await page.locator('#wallet-save').click();

        // Sucesso = toast do servidor + modal fecha sozinho (~300ms). Se o
        // backend rejeitasse, o modal ficaria aberto com erro no #wallet-status.
        await expect(
          page.locator('#toast-container div', { hasText: 'Wallet connectada' })
        ).toBeVisible({ timeout: 10000 });
        await expectModalClosed(page, 'wallet-modal');
      } else {
        // Já conectado (rerun no mesmo server): abre o modal direto.
        await page.locator('#open-wallet').click();
        await expectModalOpen(page, 'wallet-modal');
      }

      // ── Garante o modal aberto (renderWalletIdentity roda no open): no
      //    ramo connect o modal fechou sozinho após o SAVE; no rerun
      //    já-conectado ele já está aberto. ──
      if (!(await page.locator('#wallet-modal').evaluate(el => el.classList.contains('modal--open')))) {
        await page.locator('#open-wallet').click();
        await expectModalOpen(page, 'wallet-modal');
      }

      // ── WALLET IDENTITY card visível ──
      const card = page.locator('#wallet-id');
      await expect(card).toBeVisible({ timeout: 15000 });

      // ── QR: SVG inline do encoder puro (29×29 módulos + quiet zone 4 → 37) ──
      const qrSvg = page.locator('#wallet-id-qr svg');
      await expect(qrSvg).toBeVisible({ timeout: 10000 });
      await expect(qrSvg).toHaveAttribute('viewBox', '0 0 37 37');
      await expect(qrSvg).toHaveAttribute('role', 'img');
      const qrPath = qrSvg.locator('path');
      await expect(qrPath).toHaveCount(1);
      const dLen = (await qrPath.getAttribute('d') || '').length;
      expect(dLen, `QR path deve ter centenas de células (d length), got ${dLen}`)
        .toBeGreaterThan(200);

      // ── Checksum split: bc1 | corpo | 6 check-digits destacados ──
      await expect(page.locator('#wallet-id-addr .addr-pfx')).toHaveText('bc1');
      await expect(page.locator('#wallet-id-addr .addr-ck')).toHaveText(TEST_ADDR_CK);
      const fullReassembled = await page.locator('#wallet-id-addr').evaluate(el =>
        el.textContent.replace(/\s+/g, '')
      );
      expect(fullReassembled).toBe(TEST_ADDR);

      // ── COPY button visível ──
      await expect(page.locator('#wallet-id-copy')).toBeVisible();

      // ── Health strip: conectado (qualquer status honesto ≥ connected),
      //    com contagem de checks — nunca fabrica dados. Timeout generoso:
      //    o refreshUntilWalletReady pós-connect retenta por ~30s até o
      //    snapshot carregar o endereço + ts>0 (poll_once roda fetches
      //    externos que podem levar 10-30s em rede lenta). ──
      const healthEl = page.locator('#wallet-id-health');
      await expect(healthEl).toBeVisible({ timeout: 30000 });
      await expect(healthEl).toContainText(/\(\d+\/6 checks\)/, { timeout: 30000 });
      await expect(healthEl).not.toContainText('NO WALLET');
      // Os 6 checks honestos renderizados como lista.
      await expect(page.locator('#wallet-id-checks li')).toHaveCount(6, { timeout: 30000 });
      // Primeiro check = "Address set" (sempre ok quando conectado).
      await expect(page.locator('#wallet-id-checks li').first()).toContainText('Address set');
      await expect(page.locator('#wallet-id-checks li').first()).toHaveClass(/--ok/);

      // ── Status bar: check-digits também destacados no endereço curto ──
      await expect(page.locator('#sb-wallet-addr .addr-ck')).toHaveText(TEST_ADDR_CK, { timeout: 30000 });

      // ── Sem erros críticos de console (QR encoder + render limpos) ──
      const critical = capture.critical();
      expect(critical.length).toBe(0,
        `Critical console errors: ${JSON.stringify(critical)}`);
    } finally {
      await restoreWalletState(page, previousAddr, didConnect);
    }
  });
});
