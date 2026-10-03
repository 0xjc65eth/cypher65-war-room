import { test, expect } from '@playwright/test';

test.use({ serviceWorkers: 'block' });

const viewports = [
  {width: 1440, height: 900}, {width: 1280, height: 800},
  {width: 768, height: 1024}, {width: 390, height: 844},
];

test('AI drawer keyboard access, reduced motion and reflow', async ({page}) => {
  await page.setViewportSize({width: 390, height: 844});
  await page.emulateMedia({reducedMotion: 'reduce'});
  await page.route('**/api/stream*', route => route.abort());
  await page.route('**/api/snapshot*', route => route.fulfill({json: {ts: Date.now()/1000}}));
  await page.goto('/');
  const drawer = page.locator('#off-canvas-ai');
  const toggle = page.locator('#ai-panel-toggle');
  await expect(drawer).not.toBeVisible();
  await toggle.press('Enter');
  await expect(drawer).toBeVisible();
  await expect(page.locator('#ai-input-offcanvas')).toBeFocused();
  expect(await drawer.evaluate(el => getComputedStyle(el).transitionDuration)).toBe('0s');
  expect(await drawer.evaluate(el => el.getBoundingClientRect().right <= window.innerWidth + 1)).toBe(true);
  await page.locator('#ai-input-offcanvas').fill('hello');
  await page.locator('#ai-input-offcanvas').press('Enter');
  await expect(page.locator('#ai-messages-offcanvas')).toContainText('Local guide');
  await expect(page.locator('#ai-messages-offcanvas')).toContainText('no provider response');
  await expect(page.locator('#ai-send-offcanvas')).toBeEnabled();
  await page.locator('#ai-input-offcanvas').press('Escape');
  await expect(drawer).not.toBeVisible();
  await expect(toggle).toBeFocused();
});

async function openModule(page, name) {
  const toggle = page.locator('#sidebar-mobile-toggle');
  const link = page.locator('.sidebar__link[data-module="' + name + '"]');
  if (await toggle.isVisible() && !(await page.locator('#sidebar').evaluate(el => el.classList.contains('open')))) await toggle.click();
  await link.click();
  await expect(link).toHaveClass(/active/);
}

for (const viewport of viewports) {
  test('early Fleet click while snapshot is pending at ' + viewport.width, async ({ page }, testInfo) => {
    await page.setViewportSize(viewport);
    let release;
    const pending = new Promise(resolve => { release = resolve; });
    let requested = false;
    await page.route('**/api/stream*', route => route.abort());
    await page.route('**/api/snapshot*', async route => {
      requested = true;
      await pending;
      await route.fulfill({json: {ts: Date.now()/1000, worker: null, all_workers: []}});
    });
    await page.goto('/', {waitUntil: 'domcontentloaded'});
    await expect.poll(() => requested).toBe(true);
    try {
      await openModule(page, 'fleet');
      await expect(page.locator('#axe-fleet-panel')).toBeVisible();
      await expect(page.locator('#hero-worker')).not.toBeVisible();
    } finally { release(); }
    await expect(page.locator('#axe-fleet-add')).toBeVisible();
    await page.screenshot({path: testInfo.outputPath('fleet-' + viewport.width + '.png'), fullPage: true});
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBe(true);
    await page.reload({waitUntil: 'domcontentloaded'});
    await expect(page.locator('#axe-fleet-panel')).toBeVisible();
  });
}

for (const status of [401, 403, 429, 500]) {
  test('navigation survives snapshot HTTP ' + status, async ({page}) => {
    await page.route('**/api/stream*', route => route.abort());
    await page.route('**/api/snapshot*', route => route.fulfill({status, json: {error: 'lab fault'}}));
    await page.goto('/');
    await openModule(page, 'fleet');
    await expect(page.locator('#axe-fleet-panel')).toBeVisible();
    await expect(page.locator('#axe-fleet-add')).toBeVisible();
    await openModule(page, 'docs');
    await expect(page.locator('#module-header-title')).toContainText('DOCS');
  });
}

test('operational labels name the entity and the displayed market unit', async ({page}) => {
  await page.goto('/');
  await expect(page.locator('#hero-worker .panel__eyebrow')).toHaveText('TELEMETRIA DO WORKER');
  await expect(page.locator('#hero-worker .host-core__title')).toHaveText('Estado do worker');
  await openModule(page, 'market');
  await expect(page.locator('#market-panel .panel__eyebrow')).toHaveText('HASH MARKET · SHA-256');
  await expect(page.locator('#mkt-footnote')).toContainText('BTC/TH/dia');
  await expect(page.locator('#mkt-footnote')).not.toContainText('Enterprise');
});
