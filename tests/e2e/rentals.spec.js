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
      await expect(page.locator('[data-rentals-filter="history"]')).toHaveClass(/active/);
    }

    // Strip de resumo: MRR HISTORY deve ter contagem > 0 (a conta tem histórico real)
    const historyVal = await page.locator('#rentals-mrr-history').textContent();
    expect(parseInt((historyVal || '0').trim(), 10)).toBeGreaterThan(0);

    // Filtro History → cards de rentals renderizam
    await page.click('[data-rentals-filter="history"]');
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
    // Banner de performance: 5 células (PERFORMANCE / AVG / COST / DELIVERED / VS MARKET)
    await expect(page.locator('#rentals-detail-perf .rentals-perf__cell')).toHaveCount(5, { timeout: 5000 });
    // A célula VS MARKET existe (valor depende do market live — só checa o label)
    await expect(page.locator('#rentals-detail-perf .rentals-perf__cell').nth(4)).toContainText('VS MARKET');

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
    await page.click('[data-rentals-filter="contracts"]');
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
    await page.click('[data-rentals-filter="contracts"]');
    await expect(page.locator('#rentals-list .empty-state__title')).toHaveText(/API key rejected/, { timeout: 5000 });
    // Strip Braiins mostra ⚠ (erro) em vez de 🔑 (credencial ausente)
    await expect(page.locator('#rentals-braiins')).toHaveText('⚠', { timeout: 5000 });
    // O CTA para abrir Settings continua disponível
    await expect(page.locator('#rentals-open-settings')).toBeVisible({ timeout: 5000 });
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
        market: { available: true, price_sats_per_thh: 500, price_btc_per_th_day: 0.00012, provider: 'mrr' },
      })});
    });
    await page.goto('/');
    await page.waitForSelector('#sidebar', { timeout: 25000 });
    await ensureSidebarOpen(page);
    await page.click('.sidebar__link[data-module="rentals"]');
    await expect(page.locator('#rentals-count-badge')).not.toHaveText('—', { timeout: 15000 });
    // Auto-tab: 0 ativos + 1 contract → cai direto na aba Braiins
    await page.click('[data-rentals-filter="contracts"]');
    const cards = page.locator('#rentals-list .rentals-item');
    await expect(cards.first()).toBeVisible({ timeout: 5000 });
    await cards.first().click();
    await expect(page.locator('#rentals-detail')).toBeVisible({ timeout: 5000 });
    await expect(page.locator('#rentals-detail-title')).toHaveText(/Braiins contract #B123/);
    // Banner de performance com as 5 células preenchidas (incl. VS MARKET)
    const cells = page.locator('#rentals-detail-perf .rentals-perf__cell');
    await expect(cells).toHaveCount(5, { timeout: 5000 });
    const perfText = await page.locator('#rentals-detail-perf').textContent();
    expect(perfText).toMatch(/95\.0%/);
    expect(perfText).toMatch(/sats\/TH\/h/);
    expect(perfText).toMatch(/TH·h/);
    // VS MARKET: custo efetivo 526.3 sats/TH/h vs mercado 500 → +5% (is-bad)
    expect(perfText).toMatch(/\+5% vs mkt/);
    await expect(page.locator('#rentals-detail-perf .rentals-perf__cell').nth(4)).toHaveClass(/is-bad/);
  });
  });
});
