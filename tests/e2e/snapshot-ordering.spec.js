import {test, expect} from '@playwright/test';
test.use({serviceWorkers: 'block'});

test('freshness ages while the browser is offline and polling fails', async ({page, context}) => {
  await page.clock.install();
  await page.route('**/api/stream*', route => route.abort());
  await page.route('**/api/snapshot*', route => route.fulfill({json: {
    ts: Math.floor(Date.now()/1000), worker: {hashrate: 82e12}, network: {height:969640},
  }}));
  await page.goto('/');
  await expect(page.locator('#tbar-status')).toHaveText('ONLINE');
  await context.setOffline(true);
  await page.unroute('**/api/snapshot*');
  await page.clock.runFor(152000);
  await expect(page.locator('#topbar-freshness')).toContainText('DADOS ANTIGOS');
  await expect(page.locator('#tbar-status')).toHaveText('STALE');
  await expect(page.locator('#op-freshness')).toContainText('STALE');
  await context.setOffline(false);
});

test('a delayed poll and older SSE cannot replace a newer full snapshot', async ({page}) => {
  await page.addInitScript(() => {
    window.EventSource = class {
      constructor() { window.__labSSE = this; }
      close() {}
    };
  });
  const base = Math.floor(Date.now()/1000) - 20;
  let requests = 0;
  let release;
  const pending = new Promise(resolve => { release = resolve; });
  await page.route('**/api/snapshot*', async route => {
    requests++;
    if (requests > 1) await pending;
    await route.fulfill({json: {ts: base + requests - 1, network: {height: 969640 + requests - 1}}});
  });
  await page.goto('/');
  await expect(page.locator('#n-height')).toHaveText('#969640');
  await expect.poll(() => page.evaluate(() => typeof window.__labSSE?.onmessage)).toBe('function');
  await page.locator('#refresh-now').click();
  await expect.poll(() => requests).toBe(2);
  await page.evaluate(ts => window.__labSSE.onmessage({data: JSON.stringify({ts, network: {height: 969650}})}), base + 10);
  await expect(page.locator('#n-height')).toHaveText('#969650');
  const response = page.waitForResponse(r => r.url().includes('/api/snapshot'));
  release();
  await (await response).finished();
  // Let the response body resolve and the synchronous renderer finish.
  await page.waitForTimeout(200);
  await expect(page.locator('#n-height')).toHaveText('#969650');
  await page.evaluate(ts => window.__labSSE.onmessage({data: JSON.stringify({ts, network: {height: 969639}})}), base);
  await expect(page.locator('#n-height')).toHaveText('#969650');
  // An equal timestamp may carry a same-second update.
  await page.evaluate(ts => window.__labSSE.onmessage({data: JSON.stringify({ts, network: {height: 969651}})}), base + 10);
  await expect(page.locator('#n-height')).toHaveText('#969651');
  await page.evaluate(() => window.__labSSE.onmessage({data: JSON.stringify({ts: true, network: {height: 1}})}));
  await expect(page.locator('#n-height')).toHaveText('#969651');
  await page.evaluate(() => window.__labSSE.onmessage({data: '{'}));
  await expect(page.locator('#n-height')).toHaveText('#969651');
});
