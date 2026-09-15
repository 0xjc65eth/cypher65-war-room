/**
 * CYPHER65 War Room — E2E: KPI cards from a deterministic snapshot
 * ==============================================================
 *
 * Guards `renderKpiCards()` — R31 of the Dashboard domain, hoje em
 * `static/src/39b-dashboard.js` (RFC #478 · PR 10) — de forma **incondicional**.
 *
 * Por que um spec dedicado: o `dashboard.spec.js` só asserta o texto dos KPIs
 * **quando há um worker conectado** (`#hud-hashrate` visível) — um guard honesto
 * de empty state, mas que faz o servidor local de e2e (sem worker) nunca
 * exercitar a escrita. A mutação que o PR 10 usou para provar o movimento —
 * desligar a escrita de `#kpi-hashrate` — **sobreviveu** à suíte inteira (achado
 * registrado no RFC #478 / Issue #561). Este fixture injeta os campos de
 * worker/pool/proximity, então a asserção sempre roda.
 *
 * Cadeia exercitada: `fetchSnapshot()` (R24) → `render(snap)` → o god file
 * reescreve `render` (`40-app-logic.js`) para também chamar `renderKpiCards(snap)`
 * (chamada cross-fragment, dependente de hoisting).
 *
 * Os valores esperados vêm do `fmt` real:
 *   fmt.hashrate(2e12) = '2.00 TH/s' · fmt.diff(5e6) = '5.00 M' · 42/h
 *
 * Prerequisites: Flask server running on BASE_URL (see playwright.config.js).
 *
 * Run:  npx playwright test tests/e2e/dashboard-kpi-cards.spec.js
 */

import { test, expect } from '@playwright/test';
import { denyServiceWorker } from './support/sw-guard.js';

const WORKER_HASHRATE = 2e12;   // → '2.00 TH/s'
const BEST_DIFF = 5e6;          // → '5.00 M'
const POOL_HASHRATE = 3e12;     // → '3.00 TH/s'

/**
 * Load the dashboard with a deterministic snapshot.
 *
 * @param {import('@playwright/test').Page} page
 * @param {{ shareRate?: number, sharesSoFar?: number }} [opts]
 */
async function openWithFixture(page, opts = {}) {
  const shareRate = opts.shareRate === undefined ? 42 : opts.shareRate;
  const sharesSoFar = opts.sharesSoFar === undefined ? 0 : opts.sharesSoFar;

  // `page.route` não vê fetch originado do SW — e o SW também responde
  // /api/snapshot do cache. Negar o registro é a guarda compartilhada.
  await denyServiceWorker(page);
  // Corta o SSE para o poll mockado ser a única fonte de dados.
  await page.route('**/api/stream*', (route) => route.abort());
  await page.route('**/api/snapshot*', async (route) => {
    const response = await route.fetch();
    const snap = await response.json();
    snap.worker = Object.assign({}, snap.worker, {
      hashrate: WORKER_HASHRATE,
      bestDifficulty: BEST_DIFF,
      best_diff: BEST_DIFF,
    });
    snap.pool = Object.assign({}, snap.pool, { hashrate: POOL_HASHRATE });
    snap.proximity = Object.assign({}, snap.proximity, {
      share_rate_hourly: shareRate,
      live_calc: { session_totals: { shares_so_far: sharesSoFar } },
    });
    await route.fulfill({ json: snap });
  });

  await page.goto('/');
  await page.waitForSelector('#app-shell', { timeout: 20000 });
  // Espera o primeiro render aterrissar no KPI (o template começa em '—').
  // Nota: `waitForFunction(fn, arg, options)` — o objeto de options é o 3º
  // parâmetro; passá-lo em 2º (como `arg`) não aplica o timeout.
  await page.waitForFunction(() => {
    const el = document.getElementById('kpi-hashrate');
    const txt = el && el.textContent ? el.textContent.trim() : '';
    return txt !== '' && txt !== '\u2014';
  }, null, { timeout: 15000 });
}

test.describe('KPI cards — snapshot determinístico (renderKpiCards · R31)', () => {

  test('worker hashrate / best diff / pool hashrate / share rate carregam os valores do fixture', async ({ page }) => {
    await openWithFixture(page, { shareRate: 42 });

    await expect(page.locator('#kpi-hashrate')).toHaveText('2.00 TH/s');
    await expect(page.locator('#kpi-bestdiff')).toHaveText('5.00 M');
    await expect(page.locator('#kpi-poolhr')).toHaveText('3.00 TH/s');
    await expect(page.locator('#kpi-shares')).toHaveText('42/h');
  });

  test('sem share rate mas com shares na sessão, o KPI cai no total (não no em-dash)', async ({ page }) => {
    await openWithFixture(page, { shareRate: 0, sharesSoFar: 1234 });

    await expect(page.locator('#kpi-shares')).toHaveText('1234 total');
    // As outras três células continuam preenchidas pelo fixture.
    await expect(page.locator('#kpi-hashrate')).toHaveText('2.00 TH/s');
  });
});
