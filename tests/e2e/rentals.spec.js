// @ts-check
// RENTALS panel (P2) — operator rental performance (MRR + Braiins).
//
// Run: BASE_URL=http://127.0.0.1:8765 npx playwright test tests/e2e/rentals.spec.js
// Requires: dev server up with MRR_API_KEY/SECRET in .env (the account has
// real rental history — the spec asserts the REAL data renders).
import { test, expect } from '@playwright/test';

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

test.describe('RENTALS — performance dos aluguéis (P2)', () => {
  test('módulo rentals renderiza histórico MRR real + detail com gráfico', async ({ page }) => {
    await page.goto('/');
    await page.waitForSelector('#sidebar', { timeout: 25000 });
    // Abre a sidebar (mobile off-canvas) e o módulo RENTALS
    await ensureSidebarOpen(page);
    await page.click('.sidebar__link[data-module="rentals"]');
    // Badge de contagem aparece (não fica em "Loading…")
    await expect(page.locator('#rentals-count-badge')).not.toHaveText('—', { timeout: 15000 });
    const countText = await page.locator('#rentals-count-badge').textContent();
    const total = parseInt((countText || '0').match(/\d+/)?.[0] || '0', 10);
    if (total === 0) {
      test.skip(true, 'No MRR rentals found (MRR_API_KEY may be unset on this server)');
      return;
    }
    expect(total).toBeGreaterThan(0);

    // UX: com 0 rentals ativos e histórico presente, o painel deve cair na
    // aba History automaticamente (nunca abrir num 'Active' vazio escondendo
    // os 34 rentals do histórico)
    const activeVal = await page.locator('#rentals-mrr-active').textContent();
    if (parseInt((activeVal || '0').trim(), 10) === 0) {
      await expect(page.locator('.rentals-strip__card[data-rentals-filter="history"]')).toHaveClass(/active/);
    }

    // Strip de resumo: MRR HISTORY deve ter contagem > 0 (a conta tem histórico real)
    const historyVal = await page.locator('#rentals-mrr-history').textContent();
    expect(parseInt((historyVal || '0').trim(), 10)).toBeGreaterThan(0);

    // Filtro History → cards de rentals renderizam
    await page.click('button[data-rentals-filter="history"]');
    const cards = page.locator('#rentals-list .rentals-item');
    await expect(cards.first()).toBeVisible({ timeout: 10000 });
    const cardCount = await cards.count();
    expect(cardCount).toBeGreaterThan(0);
    // O card mostra #id, status e métricas
    const firstCard = await cards.first().textContent();
    expect(firstCard).toMatch(/#\d+/);
    expect(firstCard).toMatch(/(ended|online|available)/);

    // Clique no primeiro card → detail abre com título, grid e canvas
    await cards.first().click();
    await expect(page.locator('#rentals-detail')).toBeVisible({ timeout: 10000 });
    const title = await page.locator('#rentals-detail-title').textContent();
    expect(title).toMatch(/MRR rental #\d+/);
    const gridText = await page.locator('#rentals-detail-grid').textContent();
    expect(gridText).not.toBe('');
    // Banner de performance: 7 células (PERFORMANCE / AVG / COST / YIELD(exp) /
    // DELIVERED / P/L / VS MARKET) — o P/L e o yield podem ser '—' numa box
    // fria (sem network hashrate), mas as células sempre renderizam.
    await expect(page.locator('#rentals-detail-perf .rentals-perf__cell')).toHaveCount(7, { timeout: 5000 });
    // A célula VS MARKET existe (valor depende do market live — só checa o label)
    await expect(page.locator('#rentals-detail-perf .rentals-perf__cell').nth(6)).toContainText('VS MARKET');

    // Fecha o detail
    await page.click('#rentals-detail-close');
    await expect(page.locator('#rentals-detail')).toBeHidden();
  });

  test('aba Braiins sem chave → CTA abre Settings (fluxo do usuário normal)', async ({ page }) => {
    await page.goto('/');
    await page.waitForSelector('#sidebar', { timeout: 25000 });
    await ensureSidebarOpen(page);
    await page.click('.sidebar__link[data-module="rentals"]');
    // Espera o painel carregar (o strip sai de '—' quando o payload chega)
    await expect(page.locator('#rentals-count-badge')).not.toHaveText('—', { timeout: 15000 });
    // Só valida quando o servidor NÃO tem a key (caso normal de primeiro uso)
    const braiinsStrip = await page.locator('#rentals-braiins').textContent();
    if (!(braiinsStrip || '').includes('🔑')) {
      test.skip(true, 'BRAIINS_API_KEY already configured on this server');
      return;
    }
    // Aba Braiins → estado "Credentials required" com CTA que abre o Settings
    await page.click('button[data-rentals-filter="contracts"]');
    await expect(page.locator('#rentals-open-settings')).toBeVisible({ timeout: 5000 });
    await page.click('#rentals-open-settings');
    await expect(page.locator('#settings-modal')).toHaveClass(/modal--open/, { timeout: 5000 });
  });

  test('modal Settings expõe o campo BRAIINS_API_KEY', async ({ page }) => {
    await page.goto('/');
    await page.waitForSelector('#open-settings', { timeout: 15000 });
    await page.click('#open-settings');
    await expect(page.locator('#settings-modal')).toHaveClass(/modal--open/, { timeout: 10000 });
    // O form é renderizado por JS a partir de /api/settings — aguarda o campo
    const field = page.locator('#settings-body input[name="braiins_api_key"]');
    await expect(field.first()).toBeVisible({ timeout: 10000 });
    const labelText = await page.locator('#settings-body').textContent();
    expect(labelText).toMatch(/Braiins Hashpower API key/i);
  });

  test.describe('fluxo Braiins com mock (SW bloqueado p/ intercept confiável)', () => {
  test.use({ serviceWorkers: 'block' });

  test('banner arbitragem: COMPRAR AGORA pré-preenche o modal Braiins com o preço atual', async ({ page }) => {
    // Intercepta /api/rentals com market_signals (dry-run) → o banner de
    // arbitragem deve aparecer com o botão ⚡ COMPRAR AGORA, que abre o modal
    // Braiins com TH + budget derivados do preço de mercado do sinal.
    await page.route('**/api/rentals', (route) => {
      route.fulfill({ contentType: 'application/json', body: JSON.stringify({
        success: true, updated_at: Date.now(),
        mrr: { needs_auth: false, active: [], history: [{ id: 'h1' }], owner: [], total_active: 0, total_history: 1, total_owner: 0, error: null },
        braiins: { needs_auth: true, contracts: [], error: null },
        market_signals: {
          overpay: [{ severity: 'WARN', rental_id: 'r9', overpay_pct: 150, message: 'Rental #r9 pagou 150% acima do mercado' }],
          arbitrage: [{ severity: 'GOLD', discount_pct: 73.3, ref_basis: 'last',
                        market_price_sats_per_thh: 40, avg_cost_sats_per_thh: 150,
                        effective_cost_sats_per_thh: 150, last_cost_sats_per_thh: 150,
                        suggested_th: 2500,
                        message: 'ARBITRAGEM: mercado a 40 sats/TH·h — 73% abaixo do seu custo médio' }],
        },
      })});
    });
    // Quote com saldo DISPONÍVEL de 500.000 sats — budget do prefill (2.4M)
    // excede → submit fica bloqueado (guarda de saldo) e o aviso aparece.
    await page.route('**/api/rentals/braiins/quote', (route) =>
      route.fulfill({ contentType: 'application/json', body: JSON.stringify({
        success: true, available: true,
        price_sats_per_thh: 40, price_sat_per_ph_day: 960000, price_unit: 'sats/PH/day',
        balance: { available: true, available_sat: 500000, total_sat: 500000, blocked_sat: 0 },
      }) }));
    await page.goto('/');
    await page.waitForSelector('#sidebar', { timeout: 25000 });
    await ensureSidebarOpen(page);
    await page.click('.sidebar__link[data-module="rentals"]');
    await expect(page.locator('#rentals-count-badge')).not.toHaveText('—', { timeout: 15000 });

    // Banner com os dois sinais: compras caras + janela de arbitragem.
    const signals = page.locator('#rentals-signals');
    await expect(signals).toBeVisible({ timeout: 5000 });
    await expect(signals.locator('.rentals-signals__item.is-overpay')).toContainText(/1 compra\(s\) cara\(s\) detectada\(s\)/);
    await expect(signals.locator('.rentals-signals__item.is-arb')).toContainText(/JANELA DE ARBITRAGEM ABERTA/);

    // Clica COMPRAR AGORA → modal Braiins abre com TH=2500 (TH típico do
    // usuário, do sinal) e budget = 40×2500×24.
    await signals.locator('.rentals-signals__buy').click();
    await expect(page.locator('#braiins-buy-modal')).toHaveClass(/modal--open/, { timeout: 5000 });
    await expect(page.locator('#braiins-buy-th')).toHaveValue('2500', { timeout: 5000 });
    const amount = await page.locator('#braiins-buy-amount').inputValue();
    expect(parseInt(amount, 10)).toBe(2400000);  // 40 sats/TH·h × 2500 TH × 24h
    // Saldo disponível exibido na linha dedicada…
    await expect(page.locator('#braiins-buy-balance')).toContainText(/SALDO DISPONÍVEL: 500,000 sats/, { timeout: 5000 });
    // …e o budget (2.4M) > saldo (500k) → submit BLOQUEADO + aviso no calc.
    await expect(page.locator('#braiins-buy-calc')).toContainText(/EXCEDE o saldo/, { timeout: 5000 });
    await expect(page.locator('#braiins-buy-submit')).toBeDisabled();
    // Guarda de estado: baixar o budget para < saldo limpa o aviso + o
    // estilo is-exceeded (nunca fica vermelho travado) e desbloqueia.
    await page.fill('#braiins-buy-amount', '300000');
    await expect(page.locator('#braiins-buy-calc')).not.toContainText(/EXCEDE/);
    await expect(page.locator('#braiins-buy-balance')).not.toHaveClass(/is-exceeded/);
  });

  test('saldo Braiins suficiente → submit desbloqueia após confirmação', async ({ page }) => {
    await page.route('**/api/rentals', (route) => {
      route.fulfill({ contentType: 'application/json', body: JSON.stringify({
        success: true, updated_at: Date.now(),
        mrr: { needs_auth: false, active: [], history: [{ id: 'h1' }], owner: [], total_active: 0, total_history: 1, total_owner: 0, error: null },
        braiins: { needs_auth: true, contracts: [], error: null },
        market_signals: {
          overpay: [],
          arbitrage: [{ severity: 'GOLD', discount_pct: 73.3, ref_basis: 'last',
                        market_price_sats_per_thh: 40, avg_cost_sats_per_thh: 150,
                        effective_cost_sats_per_thh: 150, last_cost_sats_per_thh: 150,
                        suggested_th: 2500,
                        message: 'ARBITRAGEM: mercado a 40 sats/TH·h — 73% abaixo do seu custo médio' }],
        },
      })});
    });
    // Saldo generoso (10M sats) → budget 2.4M NÃO excede.
    await page.route('**/api/rentals/braiins/quote', (route) =>
      route.fulfill({ contentType: 'application/json', body: JSON.stringify({
        success: true, available: true,
        price_sats_per_thh: 40, price_sat_per_ph_day: 960000, price_unit: 'sats/PH/day',
        balance: { available: true, available_sat: 10000000, total_sat: 10000000, blocked_sat: 0 },
      }) }));
    await page.goto('/');
    await page.waitForSelector('#sidebar', { timeout: 25000 });
    await ensureSidebarOpen(page);
    await page.click('.sidebar__link[data-module="rentals"]');
    await expect(page.locator('#rentals-count-badge')).not.toHaveText('—', { timeout: 15000 });
    await page.locator('#rentals-signals .rentals-signals__buy').click();
    await expect(page.locator('#braiins-buy-modal')).toHaveClass(/modal--open/, { timeout: 5000 });
    await expect(page.locator('#braiins-buy-balance')).toContainText(/SALDO DISPONÍVEL: 10,000,000 sats/, { timeout: 5000 });
    // Sem excesso → aviso ausente; ainda assim o submit exige stratum + ack + COMPRAR.
    await expect(page.locator('#braiins-buy-calc')).not.toContainText(/EXCEDE/);
    await expect(page.locator('#braiins-buy-submit')).toBeDisabled();
    await page.fill('#braiins-buy-stratum', 'stratum+tcp://pool.example:3333');
    await page.fill('#braiins-buy-identity', 'user.worker');  // F4: obrigatória
    await page.check('#braiins-buy-ack');
    await page.fill('#braiins-buy-type', 'COMPRAR');
    await expect(page.locator('#braiins-buy-submit')).toBeEnabled({ timeout: 5000 });
  });

  test('chave Braiins configurada mas REJEITADA (401) → mostra erro, não "No rentals"', async ({ page }) => {
    // Intercepta /api/rentals com um payload onde a chave EXISTE mas a API a
    // rejeita — o painel deve mostrar "API key rejected" com o motivo real em
    // vez de fingir uma conta vazia (bug do 401 engolido silenciosamente).
    await page.route('**/api/rentals', (route) => {
      route.fulfill({ contentType: 'application/json', body: JSON.stringify({
        success: true, updated_at: Date.now(),
        mrr: { needs_auth: false, active: [], history: [], owner: [], total_active: 0, total_history: 0, total_owner: 0, error: null },
        braiins: { needs_auth: true, contracts: [], error: 'Braiins API rejected the key (HTTP 401/403) — check the token in Settings' },
      })});
    });
    await page.goto('/');
    await page.waitForSelector('#sidebar', { timeout: 25000 });
    await ensureSidebarOpen(page);
    await page.click('.sidebar__link[data-module="rentals"]');
    await expect(page.locator('#rentals-count-badge')).not.toHaveText('—', { timeout: 15000 });
    // Aba Braiins → empty state com título "API key rejected" (não "No rentals")
    await page.click('button[data-rentals-filter="contracts"]');
    await expect(page.locator('#rentals-list .empty-state__title')).toHaveText(/API key rejected/, { timeout: 5000 });
    // Strip Braiins mostra ⚠ (erro) em vez de 🔑 (credencial ausente)
    await expect(page.locator('#rentals-braiins')).toHaveText('⚠', { timeout: 5000 });
    // O CTA para abrir Settings continua disponível
    await expect(page.locator('#rentals-open-settings')).toBeVisible({ timeout: 5000 });
  });

  test('payload stale (versão antiga, sem flags de credencial) → hint de configuração, não "No contracts"', async ({ page }) => {
    // Payload construído por UMA VERSÃO ANTIGA do servidor: sem
    // rentals_payload_version e sem needs_auth/error (pré-guard da #152) e
    // com updated_at velho — o painel NÃO pode fingir conta vazia: mostra o
    // hint de configuração + RECARREGAR (Issue #187).
    await page.route('**/api/rentals', (route) => {
      route.fulfill({ contentType: 'application/json', body: JSON.stringify({
        success: true, updated_at: Math.floor(Date.now() / 1000) - 3600,
        mrr: { needs_auth: false, active: [], history: [], owner: [], total_active: 0, total_history: 0, total_owner: 0, error: null },
        braiins: { needs_auth: false, contracts: [], error: null },
      })});
    });
    await page.goto('/');
    await page.waitForSelector('#sidebar', { timeout: 25000 });
    await ensureSidebarOpen(page);
    await page.click('.sidebar__link[data-module="rentals"]');
    await expect(page.locator('#rentals-count-badge')).not.toHaveText('—', { timeout: 15000 });
    // Aba Braiins → empty state com hint de configuração (nunca "No contracts")
    await page.click('button[data-rentals-filter="contracts"]');
    await expect(page.locator('#rentals-list .empty-state__title')).toHaveText(/Configuração não verificada/, { timeout: 5000 });
    await expect(page.locator('#rentals-list .empty-state__desc')).toContainText(/owner token Braiins/);
    await expect(page.locator('#rentals-list .empty-state__desc')).not.toContainText(/No contracts/);
    // CTA de recarregar presente (re-fetch ?refresh=1 sem reload da página)
    await expect(page.locator('#rentals-refresh-btn')).toBeVisible({ timeout: 5000 });
  });

  test('payload fresco e vazio (versão 2) → mantém "No contracts" (sem falso positivo)', async ({ page }) => {
    // Payload NOVO (rentals_payload_version: 2, updated_at recente) com a
    // conta Braiins genuinamente vazia — o empty-state genérico continua
    // correto; o hint de configuração só aparece para payload stale/antigo
    // (Issue #187, sem falso positivo em conta real vazia).
    await page.route('**/api/rentals', (route) => {
      route.fulfill({ contentType: 'application/json', body: JSON.stringify({
        success: true, updated_at: Math.floor(Date.now() / 1000), rentals_payload_version: 2,
        mrr: { needs_auth: false, active: [], history: [], owner: [], total_active: 0, total_history: 0, total_owner: 0, error: null },
        braiins: { needs_auth: false, contracts: [], error: null },
      })});
    });
    await page.goto('/');
    await page.waitForSelector('#sidebar', { timeout: 25000 });
    await ensureSidebarOpen(page);
    await page.click('.sidebar__link[data-module="rentals"]');
    await expect(page.locator('#rentals-count-badge')).not.toHaveText('—', { timeout: 15000 });
    await page.click('button[data-rentals-filter="contracts"]');
    await expect(page.locator('#rentals-list .empty-state__title')).toHaveText(/No rentals/, { timeout: 5000 });
    await expect(page.locator('#rentals-list .empty-state__desc')).toContainText(/No contracts rentals on this account/);
    // Nenhum CTA de configuração/reload nesse caso (payload confiável).
    await expect(page.locator('#rentals-refresh-btn')).toHaveCount(0);
  });

  test('detail Braiins mostra métricas de performance normalizadas (schema MRR)', async ({ page }) => {
    // Intercepta list + detail para simular um contract Braiins com speed
    // series — o detail deve renderizar o banner de performance (4 células).
    await page.route('**/api/rentals', (route) => {
      route.fulfill({ contentType: 'application/json', body: JSON.stringify({
        success: true, updated_at: Date.now(),
        mrr: { needs_auth: false, active: [], history: [], owner: [], total_active: 0, total_history: 0, total_owner: 0, error: null },
        braiins: { needs_auth: false, contracts: [{
          id: 'B123', status: 'ACTIVE', speed_limit_ph: 100, amount_sat: 50000000, price_sat: 50013000,
        }], error: null },
      })});
    });
    await page.route('**/api/rentals/detail*', (route) => {
      route.fulfill({ contentType: 'application/json', body: JSON.stringify({
        success: true, provider: 'braiins',
        detail: {
          id: 'B123', owner: 'Braiins Hashpower', renter: '—', ended: false,
          hashrate: { advertised: { hash: 100, type: 'ph', nice: '100 PH/s' },
                      average: { hash: 95, type: 'ph', percent: 95 } },
          price: { paid: 0.5, currency: 'BTC' },
          length: 1, rig: { name: 'Braiins contract', region: 'Braiins', status: 'ACTIVE' },
          perf: { percent: 95, avg_th: 95000, limit_th: 100000, delivered_thh: 95000, cost_sats_per_thh: 526.3 },
        },
        graph: { points: [{ ts: 1785007000, speed_ph: 95 }] },
        log: {},
        // P/L economics: 0.5 BTC (50M sats) paid for 95000 TH·h at an
        // expected yield of 18.75 sats/TH·h → yield 1.78M → loss −48.2M sats.
        pl: { expected_yield_sats_per_thh: 18.75, break_even_sats_per_thh: 18.75,
              yield_sats: 1781250, paid_sats: 50000000, pl_sats: -48218750, pl_pct: -96.4, available: true },
        // Speed-series stability (Braiins contracts have no rig identity).
        stability: { cv_pct: 2.1, mean_ph: 100, min_ph: 99, max_ph: 101,
                     grade: 'STABLE', label: 'STABLE' },
        market: { available: true, price_sats_per_thh: 500, price_btc_per_th_day: 0.00012, provider: 'mrr' },
      })});
    });
    await page.goto('/');
    await page.waitForSelector('#sidebar', { timeout: 25000 });
    await ensureSidebarOpen(page);
    await page.click('.sidebar__link[data-module="rentals"]');
    await expect(page.locator('#rentals-count-badge')).not.toHaveText('—', { timeout: 15000 });
    // Auto-tab: 0 ativos + 1 contract → cai direto na aba Braiins
    await page.click('button[data-rentals-filter="contracts"]');
    const cards = page.locator('#rentals-list .rentals-item');
    await expect(cards.first()).toBeVisible({ timeout: 5000 });
    await cards.first().click();
    await expect(page.locator('#rentals-detail')).toBeVisible({ timeout: 5000 });
    await expect(page.locator('#rentals-detail-title')).toHaveText(/Braiins contract #B123/);
    // Banner de performance com as 7 células (incl. YIELD, P/L e VS MARKET)
    const cells = page.locator('#rentals-detail-perf .rentals-perf__cell');
    await expect(cells).toHaveCount(7, { timeout: 5000 });
    const perfText = await page.locator('#rentals-detail-perf').textContent();
    expect(perfText).toMatch(/95\.0%/);
    expect(perfText).toMatch(/sats\/TH\/h/);
    expect(perfText).toMatch(/TH·h/);
    // P/L: 0.5 BTC paid → −48.2M sats de prejuízo estimado (is-bad)
    expect(perfText).toMatch(/48218750 sats/);
    // VS MARKET: custo efetivo 526.3 sats/TH/h vs mercado 500 → +5% (is-bad)
    expect(perfText).toMatch(/\+5% vs mkt/);
    await expect(page.locator('#rentals-detail-perf .rentals-perf__cell').nth(6)).toHaveClass(/is-bad/);
    // Estabilidade Braiins: a série de speed (CV 2.1%) renderiza o badge STABLE
    // no bloco de confiança (sem rig identity → stability no lugar do NO DATA).
    await expect(page.locator('#rentals-detail-trust')).toBeVisible({ timeout: 5000 });
    const trustText = await page.locator('#rentals-detail-trust').textContent();
    expect(trustText).toMatch(/STABLE/);
    expect(trustText).toMatch(/CV/);
  });

  test('auto-exclusão pelo detail mostra banner + toast + card na seção AUTO-EXCLUSÕES (Issue #110)', async ({ page }) => {
    // MRR detail que REALIZA a auto-exclusão: a resposta carrega o badge
    // payload (auto_excluded_now + entry do ledger) e o painel deve mostrar
    // o banner, o toast e pré-adicionar o card na seção AUTO-EXCLUSÕES sem
    // refresh — feedback visual imediato no mesmo local.
    await page.route('**/api/rentals', (route) => {
      route.fulfill({ contentType: 'application/json', body: JSON.stringify({
        success: true, updated_at: Date.now(),
        mrr: { needs_auth: false, active: [], owner: [], total_active: 0, total_history: 1, total_owner: 0, error: null,
               history: [{
                 id: 5657736, status: 'ended',
                 start: '2026-07-01 10:00', end: '2026-07-02 10:00', length_hours: 24,
                 hashrate_average_th: 57.5, hashrate_advertised_th: 100, hashrate_percent: 57.5,
                 price_paid_btc: 0.0001,
                 rig: { id: 'R1', name: 'Rig R1', region: 'US' },
               }] },
        braiins: { needs_auth: false, contracts: [], error: null },
      })});
    });
    // Stateful detail mock: the FIRST open performs the auto-exclusion; a
    // re-open after undo must NOT re-fire (auto_excluded_now false, rig
    // não está mais auto-excluído) — fidelidade ao fluxo real do #117.
    let detailCalls = 0;
    await page.route('**/api/rentals/detail*', (route) => {
      detailCalls += 1;
      const excluded = detailCalls === 1;
      route.fulfill({ contentType: 'application/json', body: JSON.stringify({
        success: true, provider: 'mrr',
        detail: {
          id: 5657736, owner: '—', renter: '—',
          hashrate: { advertised: { hash: 100, type: 'th', nice: '100 TH/s' },
                      average: { hash: 57.5, type: 'th', percent: 57.5 } },
          price: { paid: 0.0001 }, length: 24,
          rig: { id: 'R1', name: 'Rig R1', region: 'US' },
        },
        graph: {}, log: {},
        rig_analysis: {
          trust: { grade: 'F', samples: 2, median_pct: 57.5, worst_pct: 57.5, score: 12 },
          blacklisted: false, auto_blacklisted: excluded, summary: {},
          history: [],
        },
        rig_history: [],
        perf: { percent: 57.5, avg_th: 57.5, delivered_thh: 1380, cost_sats_per_thh: 300 },
        market: {},
        auto_excluded_now: excluded,
        auto_exclude_alert_dispatched: excluded ? 1 : 0,
        auto_exclude_rule: { grade_floor: 'F', min_samples: 2 },
        auto_exclude_entry: excluded ? {
          rig_id: 'R1', name: 'Rig R1', ts: 1786694400, grade: 'F',
          delivery_pct: 57.5, samples: 2, min_samples: 2, grade_floor: 'F',
          cause: 'sub-entrega (grade F)',
        } : {},
      })});
    });
    // DELETE counter — prova o gate de confirmação (nada sem confirm).
    let deleteCalls = 0;
    await page.route('**/api/rentals/rig/blacklist**', (route) => {
      deleteCalls += 1;
      route.fulfill({ contentType: 'application/json', body: JSON.stringify({ ok: true }) });
    });
    await page.goto('/');
    await page.waitForSelector('#sidebar', { timeout: 25000 });
    await ensureSidebarOpen(page);
    await page.click('.sidebar__link[data-module="rentals"]');
    // 1 history + 0 active → cai na aba History com o card clicável
    const cards = page.locator('#rentals-list .rentals-item');
    await expect(cards.first()).toBeVisible({ timeout: 10000 });
    await cards.first().click();
    await expect(page.locator('#rentals-detail')).toBeVisible({ timeout: 5000 });
    // Banner + toast (Issue #110)
    await expect(page.locator('#rentals-detail-autoex')).toBeVisible({ timeout: 5000 });
    await expect(page.locator('#rentals-detail-autoex')).toContainText('AUTO-EXCLUSÃO DISPARADA');
    await expect(page.locator('#rentals-detail-autoex')).toContainText('alerta webhook/push enviado');
    await expect(page.locator('#toast-container')).toContainText('auto-excluído', { timeout: 5000 });
    // Card pré-adicionado na seção AUTO-EXCLUSÕES (sem refresh), com a
    // entrega 57.5% e a régua floor F · mín 2
    await expect(page.locator('#rentals-autoex')).toBeVisible({ timeout: 5000 });
    await expect(page.locator('#rentals-autoex-list')).toContainText('Rig R1');
    await expect(page.locator('#rentals-autoex-list')).toContainText('57.5%');
    await expect(page.locator('#rentals-autoex-list')).toContainText('régua F · mín 2');
    // Confirmation gate (Issue #117): single dialog handler with a mutable
    // action — DISMISS → nada acontece (DELETE não dispara, banner continua
    // visível); ACCEPT → restaura.
    let dialogAction = 'dismiss';
    page.on('dialog', d => { if (dialogAction === 'accept') d.accept(); else d.dismiss(); });
    await page.click('#rentals-detail-autoex-undo');
    await page.waitForTimeout(400);
    expect(deleteCalls).toBe(0);
    await expect(page.locator('#rentals-detail-autoex')).toBeVisible();
    // ACCEPT → restaura o rig, o banner some (reset no re-open) e o trust
    // re-renderiza sem o estado AUTO-EXCLUÍDO.
    dialogAction = 'accept';
    await page.click('#rentals-detail-autoex-undo');
    await expect(page.locator('#toast-container')).toContainText('restaurado', { timeout: 5000 });
    await expect(page.locator('#rentals-detail-autoex')).toBeHidden({ timeout: 5000 });
    await expect(page.locator('#rentals-detail-trust')).not.toContainText('AUTO-EXCLUÍDO');
    expect(deleteCalls).toBe(1);
  });
  });
});
