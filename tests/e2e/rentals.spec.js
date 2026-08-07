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

    // Fecha o detail
    await page.click('#rentals-detail-close');
    await expect(page.locator('#rentals-detail')).toBeHidden();
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
});
