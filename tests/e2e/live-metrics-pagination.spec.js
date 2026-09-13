import { test, expect } from '@playwright/test';

test.describe('live metrics patch + leaderboard pagination (Issue #539)', () => {
  test('SSE live event patches only high-frequency metrics without motion', async ({ page }) => {
    await page.addInitScript(() => {
      class FakeEventSource {
        constructor(url) {
          this.url = url;
          this.onmessage = null;
          this.onerror = null;
          window.__fakeEventSource = this;
        }
        close() {}
      }
      window.EventSource = FakeEventSource;
      window.__emitLiveMetric = (payload) => {
        window.__fakeEventSource.onmessage({ data: JSON.stringify(payload) });
      };
    });

    await page.goto('/');
    await page.waitForFunction(() => window.__fakeEventSource && window.__fakeEventSource.onmessage);
    const networkHeightBefore = await page.locator('#n-height').textContent();

    await page.evaluate(() => window.__emitLiveMetric({
      type: 'live',
      ts: Math.floor(Date.now() / 1000),
      worker_hashrate: 2_000_000_000_000,
      pool_hashrate: 3_000_000_000_000,
      fleet_avg_temp: 64.5,
      network: { height: 1 },
    }));

    await expect(page.locator('#tbar-hr')).toContainText('TH/s');
    await expect(page.locator('#tbar-temp')).toHaveText('64.5°C');
    await expect(page.locator('#p-hashrate')).toContainText('TH/s');
    await expect(page.locator('#n-height')).toHaveText(networkHeightBefore || '—');
    const motion = await page.locator('#tbar-hr').evaluate((el) => {
      const style = getComputedStyle(el);
      return { animationName: style.animationName, transitionDuration: style.transitionDuration };
    });
    expect(motion).toEqual({ animationName: 'none', transitionDuration: '0s' });
  });

  test('leaderboard loads 50 more rows and is not truncated by the legacy binder', async ({ page }) => {
    const addresses = Array.from({ length: 80 }, (_, i) => ({
      address: `bc1qissue539${String(i).padStart(3, '0')}`,
      diff_rank: i + 1,
      loyalty_rank: i + 1,
      combined_score: 80 - i,
      total_blocks: i,
    }));
    await page.addInitScript((rows) => {
      const nativeFetch = window.fetch.bind(window);
      window.fetch = async (input, init) => {
        const rawUrl = typeof input === 'string' ? input : input.url;
        const url = new URL(rawUrl, window.location.href);
        if (url.pathname === '/api/snapshot') {
          const response = await nativeFetch(input, init);
          const snapshot = await response.clone().json();
          return new Response(JSON.stringify({
            ...snapshot,
            leaderboard_table_top_30: rows.slice(0, 30),
            leaderboard_total: rows.length,
          }), { status: response.status, headers: { 'Content-Type': 'application/json' } });
        }
        if (url.pathname === '/api/leaderboard') {
          window.__leaderboardPageRequest = url.search;
          return new Response(JSON.stringify({
            entries: rows.slice(30),
            offset: 30,
            limit: 50,
            total: rows.length,
            has_more: false,
          }), { status: 200, headers: { 'Content-Type': 'application/json' } });
        }
        return nativeFetch(input, init);
      };
    }, addresses);

    await page.goto('/');
    await expect(page.locator('#lb-tbody tr')).toHaveCount(30);
    await expect(page.locator('#leaderboard-total')).toHaveText('30 / 80 miners');
    await expect(page.locator('#lb-load-more')).toBeVisible();

    await page.locator('#lb-load-more').click();

    await expect(page.locator('#lb-tbody tr')).toHaveCount(80);
    await expect(page.locator('#leaderboard-total')).toHaveText('80 miners');
    await expect(page.locator('#lb-load-more')).toBeHidden();
    await expect.poll(() => page.evaluate(() => window.__leaderboardPageRequest)).toContain('offset=30&limit=50');
  });
});
