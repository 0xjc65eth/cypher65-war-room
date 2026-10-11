/** Issue #787: real evidence calculation reaches the snapshot renderer.
 * Inputs are synthetic retained shares; this does not attest mining hardware.
 */
import { test, expect } from '@playwright/test';
import { denyServiceWorker } from './support/sw-guard.js';

async function calculate(request, history, overrides = {}) {
  const response = await request.post('/api/block-probability-lab/session-evidence', {
    data: {
      user_hashrate: 100,
      network_hashrate: 1000,
      session_share_count: 500,
      share_calc_history: history,
      ...overrides,
    },
  });
  expect(response.status()).toBe(200);
  return (await response.json()).session_evidence;
}

async function showEvidence(page, evidence) {
  await denyServiceWorker(page);
  await page.route('**/api/stream', route => route.abort());
  const response = await page.request.get('/api/snapshot');
  expect(response.ok()).toBeTruthy();
  const snapshot = await response.json();
  snapshot.proximity = { ...snapshot.proximity, session_evidence: evidence };
  await page.route('**/api/snapshot', route => route.fulfill({ json: snapshot }));
  await page.goto('/');
  await page.waitForSelector('#app-shell');
  const sidebar = page.locator('#sidebar');
  if (!(await sidebar.evaluate(el => el.classList.contains('open')))) {
    const toggle = page.locator('#sidebar-mobile-toggle');
    if (await toggle.isVisible()) await toggle.click();
  }
  await page.locator('.sidebar__link[data-module="probability"]').click();
  await expect(page.locator('#se-evidence-state')).toBeVisible();
  return snapshot;
}

test('future timestamps remain unknown; valid retained observations recover coverage', async ({ page }) => {
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  const now = Math.floor(Date.now() / 1000);
  const future = Array.from({ length: 100 }, (_, i) => ({
    ts: now + 3600 + i, share_diff_raw: i + 1,
  }));
  const invalid = await calculate(page.request, future, { age_seconds: 0 });
  expect(invalid.evidence_state).toBe('PARTIAL');
  const snapshot = await showEvidence(page, invalid);
  await expect(page.locator('#se-session-shares')).toHaveText('500');
  await expect(page.locator('#se-sample-count')).toHaveText('100');
  await expect(page.locator('#se-last-share-age')).toHaveText('—');
  await expect(page.locator('#se-observed-window')).toHaveText('—');
  await expect(page.locator('#se-evidence-state2')).toHaveText('PARTIAL');

  const validHistory = Array.from({ length: 100 }, (_, i) => ({
    ts: now - 200 + i, share_diff_raw: i + 1,
  }));
  const valid = await calculate(page.request, validHistory);
  expect(valid.evidence_state).toBe('GOOD COVERAGE');
  await page.unroute('**/api/snapshot');
  await page.route('**/api/snapshot', route => route.fulfill({
    json: { ...snapshot, proximity: { ...snapshot.proximity, session_evidence: valid } },
  }));
  await page.reload();
  await expect(page.locator('#se-evidence-state2')).toHaveText('GOOD COVERAGE');
  await expect(page.locator('#se-last-share-age')).toHaveText(valid.last_share_age);
  await expect(page.locator('#se-observed-window')).toHaveText('99s');
  expect(errors).toEqual([]);
});

test('stale retained shares override a fresh age hint in the rendered panel', async ({ page }) => {
  const now = Math.floor(Date.now() / 1000);
  const evidence = await calculate(page.request, [
    { ts: now - 7200, share_diff_raw: 1 },
    { ts: now - 7199, share_diff_raw: 3 },
  ], { age_seconds: 0 });
  expect(evidence.evidence_state).toBe('STALE');
  expect(evidence.last_share_age_seconds).toBeGreaterThan(3600);
  await showEvidence(page, evidence);
  await expect(page.locator('#se-evidence-state2')).toHaveText('STALE');
  await expect(page.locator('#se-last-share-age')).toHaveText(evidence.last_share_age);
  await expect(page.locator('#se-data-gaps')).toHaveText('—');
  await expect(page.locator('#se-sample-count')).toHaveText('2');
});
