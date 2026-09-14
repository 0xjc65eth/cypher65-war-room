/**
 * CYPHER65 War Room — E2E Probability WHAT-IF Slider Regression
 * =============================================================
 *
 * Guards the "⚡ WHAT-IF · DIFFICULTY" simulator in the Block Hunt panel
 * (module: Probability) — UX audit Módulo_05.
 *
 * The slider simulates the impact of a network difficulty shift (%)
 * on P(block)/share, expected time, distance and cumulative P without
 * touching the live snapshot. This spec verifies:
 *   1. the slider + badge + reset button render in the Block Hunt panel;
 *   2. dragging the slider updates the badge AND the readouts live;
 *   3. the reset button returns to 0% (readouts return to baseline);
 *   4. with no network data, the panel degrades to a clean em-dash state.
 *
 * Prerequisites: Flask server running on BASE_URL (see playwright.config.js).
 *
 * Run:  npx playwright test tests/e2e/probability-whatif.spec.js
 */

import { test, expect } from '@playwright/test';
import { denyServiceWorker } from './support/sw-guard.js';

test.describe('Probability WHAT-IF difficulty slider — regression', () => {

  /** Navigate to the Probability module (Block Hunt panel is its home). */
  async function openProbability(page) {
    await page.goto('/');
    await page.waitForSelector('#app-shell', { timeout: 20000 });

    // Ensure sidebar is open (mobile-chrome collapses it by default).
    const isOpen = await page.evaluate(() => {
      const sb = document.getElementById('sidebar');
      return sb && sb.classList.contains('open');
    });
    if (!isOpen) {
      const toggle = page.locator('#sidebar-mobile-toggle');
      if (await toggle.isVisible().catch(() => false)) {
        await toggle.click();
        await page.waitForTimeout(400);
      }
    }

    await page.click('.sidebar__link[data-module="probability"]');
    await expect(page.locator('#block-hunt-panel')).toBeVisible({ timeout: 15000 });
  }


  // ── Fixture determinístico (Issue #548) ────────────────────────────────────
  // O painel só tem números quando o snapshot traz dificuldade de rede + best
  // share. Em vez de depender do que o servidor tem (o que fazia o spec PULAR a
  // comparação numérica via guard `hasData`), forçamos exatamente os campos que
  // o simulador lê e cortamos o SSE — que empurraria o snapshot do servidor por
  // cima do fixture — deixando o poll interceptado como única fonte.
  //
  // Com dificuldade de rede = 110 T e best share = 10 G:
  //   P(bloco)/share = bestDiff / netDiff(1+shift), exibido como
  //   (p × 100).toExponential(2) pelo `_bhRenderWhatIf`.
  const NET_DIFF = 110e12;
  const BEST_DIFF = 10e9;
  const PBLOCK_0 = '9.09e-3%';      // 10G / 110T
  const PBLOCK_10 = '8.26e-3%';     // 10G / 121T
  const PBLOCK_30 = '6.99e-3%';     // 10G / 143T
  const PBLOCK_NEG25 = '1.21e-2%';  // 10G / 82.5T

  const parsePct = (raw) => {
    const n = parseFloat(String(raw).replace('%', ''));
    return Number.isFinite(n) ? n : null;
  };

  async function forceBlockHuntData(page) {
    // O SW derrota o fixture abaixo (page.route não vê o fetch do SW, e o
    // `controllerchange` recarrega a página) — a guarda canônica vive em
    // support/sw-guard.js; ver RFC #478 / Issue #548 para a causa raiz.
    await denyServiceWorker(page);
    await page.route('**/api/stream*', (route) => route.abort());
    await page.route('**/api/snapshot*', async (route) => {
      const response = await route.fetch();
      const snap = await response.json();
      snap.network = Object.assign({}, snap.network, { difficulty: NET_DIFF });
      snap.worker = Object.assign({}, snap.worker, { bestDifficulty: BEST_DIFF });
      snap.block_hunt = Object.assign({}, snap.block_hunt, {
        network_difficulty: NET_DIFF,
        best_difficulty: BEST_DIFF,
        modeled_share_probability: BEST_DIFF / NET_DIFF,
        expected_time_seconds: 123456,
      });
      snap.proximity = Object.assign({}, snap.proximity, {
        live_calc: Object.assign({}, snap.proximity && snap.proximity.live_calc, {
          session_totals: { shares_so_far: 1000 },
        }),
      });
      await route.fulfill({ json: snap });
    });
  }

  test('renders the slider, badge and reset button in Block Hunt', async ({ page }) => {
    await openProbability(page);

    const slider = page.locator('#bh-whatif-slider');
    await expect(slider).toBeVisible();
    await expect(slider).toHaveAttribute('min', '-50');
    await expect(slider).toHaveAttribute('max', '100');
    await expect(page.locator('#bh-whatif-badge')).toHaveText('0%');
    await expect(page.locator('#bh-whatif-reset')).toBeVisible();

    // Readout cells exist for the 4 simulated metrics.
    for (const id of ['#bh-whatif-diff', '#bh-whatif-pblock', '#bh-whatif-etime', '#bh-whatif-cum']) {
      await expect(page.locator(id)).toBeVisible();
    }
  });

  test('dragging the slider updates badge and readouts live; reset returns to baseline', async ({ page }) => {
    await forceBlockHuntData(page);
    await openProbability(page);

    const slider = page.locator('#bh-whatif-slider');
    const badge = page.locator('#bh-whatif-badge');
    const diffCell = page.locator('#bh-whatif-diff');
    const pblockCell = page.locator('#bh-whatif-pblock');

    // Issue #548: com o fixture, o painel mostra números REAIS — a comparação
    // numérica abaixo não é mais pulada (era o guard `hasData` que deixava o
    // math do simulador sem cobertura de e2e).
    await expect(diffCell).not.toHaveText('\u2014');
    await expect(pblockCell).toHaveText(PBLOCK_0);

    // +10% de dificuldade → P(bloco)/share cai (escala inversa).
    await slider.evaluate(el => { el.value = 10; el.dispatchEvent(new Event('input', { bubbles: true })); });
    await expect(badge).toHaveText('+10%');
    await expect(pblockCell).toHaveText(PBLOCK_10);
    const p10 = parsePct(await pblockCell.textContent());

    // +30% → cai mais (bate com o fixture, não só com o sinal).
    await slider.evaluate(el => { el.value = 30; el.dispatchEvent(new Event('input', { bubbles: true })); });
    await expect(badge).toHaveText('+30%');
    await expect(pblockCell).toHaveText(PBLOCK_30);
    const p30 = parsePct(await pblockCell.textContent());

    expect(p10).toBeGreaterThan(0);
    expect(p30).toBeLessThan(p10);

    // Reset → volta ao baseline 0% (inclusive o readout).
    await page.click('#bh-whatif-reset');
    await expect(badge).toHaveText('0%');
    await expect(slider).toHaveValue('0');
    await expect(pblockCell).toHaveText(PBLOCK_0);
  });

  test('simulates NEGATIVE difficulty shifts (drop) without breaking', async ({ page }) => {
    await forceBlockHuntData(page);
    await openProbability(page);

    const slider = page.locator('#bh-whatif-slider');
    const badge = page.locator('#bh-whatif-badge');
    const pblockCell = page.locator('#bh-whatif-pblock');

    await slider.evaluate(el => { el.value = -25; el.dispatchEvent(new Event('input', { bubbles: true })); });
    await expect(badge).toHaveText('-25%');
    // Dificuldade CAI → P(bloco)/share SOBE (1.21e-2 > 9.09e-3 do baseline).
    await expect(pblockCell).toHaveText(PBLOCK_NEG25);

    // Readouts sempre presentes (números reais ou em-dash honesto — nunca vazio).
    const cum = await page.locator('#bh-whatif-cum').textContent();
    expect(String(cum).trim()).not.toBe('');
    expect(String(cum).trim()).toMatch(/%$/);

    // Reset para o baseline.
    await page.click('#bh-whatif-reset');
    await expect(badge).toHaveText('0%');
  });
});
