/**
 * CYPHER65 War Room — keyboard and accessibility E2E for miner commands.
 * Covers native modal focus containment, keyboard cancellation/confirmation,
 * live status announcements, reduced motion, and critical Axe violations.
 */

import { test, expect } from '@playwright/test';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const axeSource = require.resolve('axe-core');
const BASE_URL = process.env.BASE_URL || 'http://127.0.0.1:8765';

test.use({ serviceWorkers: 'block' });

async function waitForDashboard(page) {
  await page.waitForSelector('#app-shell', { timeout: 15000 });
  await page.waitForSelector('#status-bar', { timeout: 15000 });
}

async function expectNoCriticalAxeViolations(page, contextName) {
  const report = await page.evaluate(async () => window.axe.run(document));
  const critical = report.violations.filter(violation => violation.impact === 'critical');
  expect(
    critical.map(({ id, help, nodes }) => ({
      id,
      help,
      elements: nodes.map(node => node.target),
    })),
    'Critical Axe violations in ' + contextName,
  ).toEqual([]);
}

async function tabToLocator(page, locator, limit = 100) {
  for (let count = 0; count < limit; count += 1) {
    if (await locator.evaluate(element => element === document.activeElement)) return;
    await page.keyboard.press('Tab');
  }
  throw new Error('Keyboard Tab did not reach ' + await locator.getAttribute('class'));
}

test('miner command confirmation is keyboard accessible and honors reduced motion', async ({ page }) => {
  test.setTimeout(60000);
  await page.emulateMedia({ reducedMotion: 'reduce' });

  const fired = { pause: 0 };
  await page.route(/\/api\/axe-fleet\/summary/, route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({
      total_devices: 1,
      online: 1,
      warning: 0,
      offline: 0,
      total_hashrate_hs: 5200000000000,
      devices: [{
        id: 'e2e-a11y-device',
        name: 'A11y Miner',
        ip_address: '192.0.2.62',
        model: 'Bitaxe',
        manufacturer: 'Bitaxe',
        status: 'ONLINE',
        agent_managed: 0,
        capabilities: ['pause'],
        latency_ms: 4,
        advice: [],
        _health: { score: 92, label: 'healthy', issues: [] },
        _telemetry: {
          hashrate_hs: 5200000000000,
          hashrate_str: '5.2 TH/s',
          temperature: 62,
          power_watts: 42,
          efficiency_jth: 8.08,
          shares_accepted: 15823,
          shares_rejected: 47,
          shares_stale: 0,
          uptime_seconds: 259200,
          ts: Math.floor(Date.now() / 1000),
        },
      }],
    }),
  }));
  await page.route(/\/api\/axe-fleet\/devices\/[^/]+\/pause/, async route => {
    fired.pause += 1;
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ success: true, message: 'Pause queued for local agent' }),
    });
  });

  await page.goto(BASE_URL);
  await waitForDashboard(page);
  await page.addScriptTag({ path: axeSource });
  await expectNoCriticalAxeViolations(page, 'dashboard');

  const liveLink = page.locator('.sidebar__link[data-module="live"]');
  await liveLink.focus();
  await page.keyboard.press('Enter');
  const card = page.locator('#lm-workers-grid .fcc-card').filter({ hasText: 'A11y Miner' });
  await expect(card).toBeVisible({ timeout: 30000 });
  const pauseButton = card.locator('.axe-cmd-btn--pause');
  await expect(pauseButton).toHaveAccessibleName(/Pause/);
  await tabToLocator(page, pauseButton);
  await page.keyboard.press('Enter');

  const dialog = page.getByRole('dialog', { name: 'Confirmar comando no minerador' });
  const cancel = dialog.getByRole('button', { name: 'Cancelar' });
  const confirm = dialog.getByRole('button', { name: 'Confirmar pausa', exact: true });
  await expect(dialog).toBeVisible();
  await expect(cancel).toBeFocused();

  // Native modal dialogs keep sequential keyboard focus inside their top layer.
  await page.keyboard.press('Shift+Tab');
  await expect(confirm).toBeFocused();
  await page.keyboard.press('Tab');
  await expect(cancel).toBeFocused();
  await expectNoCriticalAxeViolations(page, 'open command confirmation');

  // Escape cancels the physical action and restores focus to its trigger.
  await page.keyboard.press('Escape');
  await expect(dialog).toBeHidden();
  expect(fired.pause).toBe(0);
  await expect(pauseButton).toBeFocused();

  // Re-open and confirm with Enter; the status region must announce the result.
  await page.keyboard.press('Enter');
  await expect(dialog).toBeVisible();
  await page.keyboard.press('Shift+Tab');
  await expect(confirm).toBeFocused();
  await page.keyboard.press('Enter');
  await expect(dialog).toBeHidden();
  await expect.poll(() => fired.pause).toBe(1);

  const status = page.locator('#toast-container[role="status"]');
  await expect(status).toContainText('Pause queued for local agent');
  await expect(pauseButton).toBeFocused();
  await expectNoCriticalAxeViolations(page, 'command result announcement');

  const motion = await status.locator('.toast').evaluate(element => {
    const style = getComputedStyle(element);
    return {
      reducedMotion: matchMedia('(prefers-reduced-motion: reduce)').matches,
      transitionMs: style.transitionDuration.split(',').map(value => parseFloat(value) * 1000),
      animationMs: style.animationDuration.split(',').map(value => parseFloat(value) * 1000),
    };
  });
  expect(motion.reducedMotion).toBe(true);
  expect(motion.transitionMs.every(duration => duration <= 0.1)).toBe(true);
  expect(motion.animationMs.every(duration => duration <= 0.1)).toBe(true);
});
