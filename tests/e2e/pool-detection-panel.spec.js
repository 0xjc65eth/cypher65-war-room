/**
 * CYPHER65 War Room — E2E: pool detectada a partir do report do ASIC (Issue #574)
 * ==============================================================================
 *
 * Guards `renderPoolDetection()` — o painel que responde três perguntas sobre a
 * pool em que a carteira minera: QUAL pool, em qual CHAIN, e se os números vêm
 * da API pública da pool ou do PRÓPRIO minerador.
 *
 * Por que um spec dedicado com fixture: nenhum servidor de e2e tem telemetria de
 * frota, então `snap.pool_detection` chega `null` e a faixa fica oculta. Sem
 * injetar o report, nada aqui seria exercitado — inclusive o caso que mais
 * importa, que é o mais fácil de errar: uma pool que PUBLICA API e ainda assim
 * respondeu pelo ASIC não é "pool sem API", é API que falhou.
 *
 * Cadeia exercitada: `fetchSnapshot()` → `render(snap)` → `renderPoolDetection()`
 * (fragmento `static/src/39b-dashboard.js`).
 *
 * Prerequisites: Flask server running on BASE_URL (see playwright.config.js).
 *
 * Run:  npx playwright test tests/e2e/pool-detection-panel.spec.js
 */

import { test, expect } from '@playwright/test';
import { denyServiceWorker } from './support/sw-guard.js';

/**
 * Load the dashboard with a deterministic pool report.
 *
 * @param {import('@playwright/test').Page} page
 * @param {{ detection?: object|null, worker?: object|null }} [fixture]
 */
async function openWithPoolReport(page, fixture = {}) {
  const detection = fixture.detection === undefined ? null : fixture.detection;
  const worker = fixture.worker === undefined ? null : fixture.worker;

  // `page.route` não vê fetch originado do SW, e o SW responde /api/snapshot do
  // cache: negar o registro é a guarda compartilhada (Issue #562).
  await denyServiceWorker(page);
  // Corta o SSE para o poll mockado ser a única fonte de dados.
  await page.route('**/api/stream*', (route) => route.abort());
  await page.route('**/api/snapshot*', async (route) => {
    const response = await route.fetch();
    const snap = await response.json();
    snap.pool_detection = detection;
    snap.pool_worker = worker;
    await route.fulfill({ json: snap });
  });

  await page.goto('/');
  await page.waitForSelector('#app-shell', { timeout: 20000 });
}

/** Wait for the strip to reflect a detected pool (não fica presa no `hidden`). */
async function waitForStrip(page) {
  await page.waitForFunction(() => {
    const el = document.getElementById('pool-detect');
    return !!el && !el.hasAttribute('hidden');
  }, null, { timeout: 15000 });
}

const PARASITE_DETECTION = {
  provider_id: 'parasite',
  label: 'Parasite',
  kind: 'solo',
  chain: 'btc',
  chain_source: 'provider_registry',
  host: 'parasite.space',
  matched_pattern: 'parasite.space',
  stats_url: 'https://parasite.space/api/address/{address}',
  has_stats_api: true,
  docs: '',
};

test.describe('Pool detectada pelo ASIC — faixa do painel Pool Context', () => {

  test('API pública respondeu: provider, chain e fonte API', async ({ page }) => {
    await openWithPoolReport(page, {
      detection: PARASITE_DETECTION,
      worker: {
        provider_id: 'parasite',
        label: 'Parasite',
        chain: 'btc',
        kind: 'solo',
        source: 'api',
        stats_url: 'https://parasite.space/api/address/bc1qxyz',
        error: '',
      },
    });
    await waitForStrip(page);

    await expect(page.locator('#pd-provider')).toHaveText('Parasite');
    await expect(page.locator('#pd-provider-sub')).toHaveText('parasite.space · SOLO');
    await expect(page.locator('#pd-chain')).toHaveText('BTC');
    await expect(page.locator('#pd-chain-sub')).toHaveText('pool do registro');
    await expect(page.locator('#pd-source')).toHaveText('API DA POOL');
    await expect(page.locator('#pd-source-sub')).toHaveText('dados públicos da pool');
    // A faixa não é aviso: borda padrão, sem a variante âmbar/neutra.
    await expect(page.locator('#pool-detect')).not.toHaveClass(/pool-detect--degraded/);
    await expect(page.locator('#pool-detect')).not.toHaveClass(/pool-detect--unknown/);
  });

  test('pool sem API pública: a fonte honesta é o ASIC', async ({ page }) => {
    await openWithPoolReport(page, {
      detection: {
        provider_id: 'ocean', label: 'OCEAN', kind: 'pool', chain: 'btc',
        chain_source: 'provider_registry', host: 'ocean.xyz',
        matched_pattern: 'ocean.xyz', stats_url: '', has_stats_api: false, docs: '',
      },
      worker: {
        provider_id: 'ocean', label: 'OCEAN', chain: 'btc', kind: 'pool',
        source: 'asic', stats_url: '', error: '',
      },
    });
    await waitForStrip(page);

    await expect(page.locator('#pd-provider')).toHaveText('OCEAN');
    await expect(page.locator('#pd-source')).toHaveText('ASIC');
    await expect(page.locator('#pd-source-sub')).toHaveText('pool sem API pública');
    // `stratum_only` é o estado normal — não vira aviso.
    await expect(page.locator('#pool-detect')).not.toHaveClass(/pool-detect--degraded/);
  });

  test('pool COM API que não respondeu: aviso âmbar, não "sem API"', async ({ page }) => {
    await openWithPoolReport(page, {
      detection: {
        provider_id: 'ckpool_bsv', label: 'CKPool BSV (solo)', kind: 'solo', chain: 'bsv',
        chain_source: 'provider_registry', host: 'solo.bsv.ckpool.org',
        matched_pattern: 'solo.bsv.ckpool.org', stats_url: '', has_stats_api: true, docs: '',
      },
      worker: {
        provider_id: 'ckpool_bsv', label: 'CKPool BSV (solo)', chain: 'bsv', kind: 'solo',
        source: 'asic', stats_url: '', error: 'timeout',
      },
    });
    await waitForStrip(page);

    await expect(page.locator('#pd-source')).toHaveText('ASIC');
    await expect(page.locator('#pd-source-sub')).toHaveText('API da pool não respondeu');
    await expect(page.locator('#pool-detect')).toHaveClass(/pool-detect--degraded/);
    // A chain vem do REGISTRO, não do endereço: BSV é declarado, não adivinhado.
    await expect(page.locator('#pd-chain')).toHaveText('BSV');
    await expect(page.locator('#pd-chain-sub')).toHaveText('pool do registro');
  });

  test('host fora do registro: diz que não conhece e não inventa chain', async ({ page }) => {
    await openWithPoolReport(page, {
      detection: {
        provider_id: 'unknown', label: 'minha.pool.local', kind: null, chain: null,
        chain_source: 'unknown', host: 'minha.pool.local', matched_pattern: '',
        stats_url: '', has_stats_api: false, docs: '',
      },
      worker: {
        provider_id: 'unknown', label: 'minha.pool.local', chain: '', kind: null,
        source: 'asic', stats_url: '', error: '',
      },
    });
    await waitForStrip(page);

    await expect(page.locator('#pd-provider')).toHaveText('minha.pool.local');
    await expect(page.locator('#pd-provider-sub')).toHaveText('minha.pool.local · fora do registro');
    await expect(page.locator('#pd-chain')).toHaveText('não declarada');
    await expect(page.locator('#pool-detect')).toHaveClass(/pool-detect--unknown/);
  });

  test('rótulo/host longos: clipe com ellipsis, sem estourar a faixa', async ({ page }) => {
    // O guard de truncamento do audit visual roda com a faixa OCULTA (nenhum
    // servidor de e2e tem telemetria de frota), então o único lugar onde esta
    // célula existe de verdade com texto longo é aqui. Sem este teste, um host
    // de 200 caracteres só apareceria em produção.
    const LONG = 'pool-com-nome-extremamente-longo' + '-segmento'.repeat(8) + '.exemplo.net.br';
    await openWithPoolReport(page, {
      detection: {
        provider_id: 'unknown', label: LONG, kind: 'both', chain: 'bsv',
        chain_source: 'host_label', host: LONG, matched_pattern: '',
        stats_url: '', has_stats_api: false, docs: '',
      },
      worker: {
        provider_id: 'unknown', label: LONG, chain: 'bsv', kind: 'both',
        source: 'asic', stats_url: '', error: '',
      },
    });
    await waitForStrip(page);

    const geom = await page.evaluate(() => {
      const strip = document.getElementById('pool-detect');
      const stripBox = strip.getBoundingClientRect();
      const lines = ['pd-provider', 'pd-provider-sub', 'pd-chain', 'pd-chain-sub', 'pd-source-sub'];
      return {
        // 1px de tolerância para arredondamento de layout.
        stripSpills: strip.scrollWidth - strip.clientWidth > 1,
        cellsOutside: Array.from(strip.querySelectorAll('.pool-detect__cell')).filter((cell) => {
          const box = cell.getBoundingClientRect();
          return box.right - stripBox.right > 1 || stripBox.left - box.left > 1;
        }).length,
        // Linha cliade continua sendo UMA linha (nada de quebrar em 2–3).
        wrapped: lines.filter((id) => {
          const el = document.getElementById(id);
          const lh = parseFloat(getComputedStyle(el).lineHeight) || 0;
          return lh > 0 && el.clientHeight > lh * 1.5;
        }),
        clipped: lines.filter((id) => {
          const el = document.getElementById(id);
          return getComputedStyle(el).textOverflow === 'ellipsis' && el.scrollWidth > el.clientWidth;
        }),
      };
    });
    expect(geom.stripSpills).toBe(false);
    expect(geom.cellsOutside).toBe(0);
    expect(geom.wrapped).toEqual([]);
    // As duas linhas com o texto longo são RECORTADAS com ellipsis (o resto é curto).
    expect(geom.clipped).toEqual(['pd-provider', 'pd-provider-sub']);
    await expect(page.locator('#pd-provider')).toHaveText(LONG);
    await expect(page.locator('#pd-chain')).toHaveText('BSV');
    await expect(page.locator('#pd-chain-sub')).toHaveText('pelo host do ASIC');
  });

  test('sem report do ASIC a faixa fica oculta (não mostra zero como fato)', async ({ page }) => {
    await openWithPoolReport(page);
    // Espera um render real aterrissar antes de afirmar a ausência.
    await page.waitForFunction(() => {
      const el = document.getElementById('p-hashrate');
      return !!el && el.textContent.trim() !== '';
    }, null, { timeout: 15000 });

    await expect(page.locator('#pool-detect')).toHaveAttribute('hidden', '');
  });
});
