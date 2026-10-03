import { test, expect } from '@playwright/test';
test.use({serviceWorkers: 'block'});

async function fixture(page, worker = true, address = true) {
  await page.route('**/api/stream*', r => r.abort());
  await page.route('**/api/axe-fleet*', r => r.fulfill({json: {devices: [], summary: {total:0}, agents: []}}));
  await page.route('**/api/snapshot*', r => r.fulfill({json: {
    ts: Date.now()/1000, btc_address: address ? 'bc1qpc3832jcu6m8qpqjvz5lkuydwjzv8v5vq5t5rs' : '',
    worker: worker ? {hashrate:82e12, bestDifficulty:85e9, lastSubmission:Date.now()/1000-60} : null,
    all_workers: worker ? [{name:'worker-01'},{name:'worker-02'}] : [],
    network:{height:969641,difficulty:132.76e12,hashrate:897e18},
    pool:{hashrate:323e15,highestDiff:63e12,lastBlockTime:958527,workers:4944,users:2323},
    btc_price:{usd:84537}, axe_fleet:[],
  }}));
  await page.goto('/');
  await expect(page.locator('#n-height')).toHaveText('#969641');
}
async function openModule(page, name) {
  const toggle=page.locator('#sidebar-mobile-toggle');
  if (await toggle.isVisible()) {
    const sidebar = page.locator('#sidebar');
    if (!(await sidebar.evaluate(el => el.classList.contains('open')))) await toggle.click();
    await expect(sidebar).toHaveClass(/open/);
  }
  await page.locator('.sidebar__link[data-module="'+name+'"]').click();
  await expect(page.locator('.sidebar__link[data-module="'+name+'"]')).toHaveClass(/active/);
}

test('terminal layout keeps one primary worker surface and readable context', async ({page}, info) => {
  const width=info.project.name==='chromium'?1440:390;
  await page.setViewportSize({width,height:900});
  await fixture(page);
  if (width >= 1000) {
    // A resized browser can still be completing the inherited sidebar width transition.
    await expect.poll(() => page.locator('#sidebar').evaluate(el => el.getBoundingClientRect().width)).toBe(176);
    const clipped = await page.locator('.sidebar__link .label').evaluateAll(els => els.filter(el => el.getBoundingClientRect().right > el.closest('aside').getBoundingClientRect().right).map(el => el.textContent));
    expect(clipped).toEqual([]);
  }
  await page.screenshot({path:info.outputPath('terminal-'+width+'.png'),fullPage:true});
  await expect(page.locator('#kpi-hashrate')).toHaveText('82.00 TH/s');
  await expect(page.locator('#hero-worker')).not.toBeVisible();
  await expect(page.locator('#worker-details > summary')).toBeVisible();
  expect(await page.locator('.kpi-label').first().evaluate(e=>parseFloat(getComputedStyle(e).fontSize))).toBeGreaterThanOrEqual(11);
  const overflow=await page.evaluate(()=>({width:innerWidth,doc:document.documentElement.scrollWidth,items:Array.from(document.querySelectorAll('body *')).filter(e=>e.getBoundingClientRect().width && e.getBoundingClientRect().right>innerWidth+1).slice(0,10).map(e=>({id:e.id,cls:e.className,right:e.getBoundingClientRect().right}))}));
  expect(overflow.doc,JSON.stringify(overflow)).toBeLessThanOrEqual(overflow.width+1);
  if(width>=1000) {
    const pool=await page.locator('#pool-overview').boundingBox();
    const net=await page.locator('#network-panel').boundingBox();
    expect(Math.abs(pool.y-net.y)).toBeLessThan(2);
    expect(net.x).toBeGreaterThan(pool.x+pool.width);
  }
  const summary=page.locator('#worker-details > summary');
  await summary.focus();await summary.press('Enter');
  await expect(page.locator('#hero-worker')).toBeVisible();
  await expect(page.locator('#hc-network')).toHaveText('#969641');
  await expect(page.locator('#m-hashrate')).toHaveText('82.00 TH/s');
  await summary.press('Enter');
  await expect(page.locator('#hero-worker')).not.toBeVisible();
});

test('terminal navigation retains all modules and reduced-motion state', async ({page}) => {
  await page.emulateMedia({reducedMotion:'reduce'});
  await fixture(page);
  for(const name of ['fleet','live','wallet','probability','market','rentals','alerts','automations','docs','learning','admin','dashboard']) {
    await openModule(page,name);
    await expect(page.locator('body')).toHaveAttribute('data-active-module',name);
    await expect(page.locator('#module-header-title')).not.toBeEmpty();
    const overflow=await page.evaluate(()=>({width:innerWidth,doc:document.documentElement.scrollWidth,items:Array.from(document.querySelectorAll('body *')).filter(e=>e.getBoundingClientRect().width && e.getBoundingClientRect().right>innerWidth+1).slice(0,10).map(e=>({id:e.id,cls:e.className,right:e.getBoundingClientRect().right}))}));
  expect(overflow.doc,JSON.stringify({module:name,...overflow})).toBeLessThanOrEqual(overflow.width+1);
  }
  await openModule(page,'support');
  await expect(page.locator('#support-panel')).toBeVisible();
});

test('terminal light theme and 200 percent CSS zoom reflow', async ({page},info) => {
  await page.setViewportSize({width:1440,height:900});await fixture(page);
  await page.locator('#theme-toggle').click();
  await expect(page.locator('html')).toHaveAttribute('data-theme','light');
  await page.screenshot({path:info.outputPath('terminal-light.png'),fullPage:true});
  // CSS zoom is a controlled reflow check; it is not a browser UI zoom certification.
  await page.evaluate(()=>document.documentElement.style.zoom='2');
  const overflow=await page.evaluate(()=>({width:innerWidth,doc:document.documentElement.scrollWidth,items:Array.from(document.querySelectorAll('body *')).filter(e=>e.getBoundingClientRect().width && e.getBoundingClientRect().right>innerWidth+1).slice(0,10).map(e=>({id:e.id,cls:e.className,right:e.getBoundingClientRect().right}))}));
  expect(overflow.doc,JSON.stringify(overflow)).toBeLessThanOrEqual(overflow.width+1);
  await expect(page.locator('#refresh-now')).toBeVisible();
  await page.screenshot({path:info.outputPath('terminal-zoom-200.png'),fullPage:true});
});


test('terminal empty state keeps unavailable data honest and wallet setup reachable', async ({page}) => {
  await fixture(page, false, false);
  await expect(page.locator('#wallet-cta')).toBeVisible();
  await expect(page.locator('#kpi-hashrate')).toHaveText('—');
  await expect(page.locator('#cc-grid')).toContainText('Sem diagnósticos');
  await expect(page.locator('#cc-grid')).not.toContainText('All systems nominal');
  await page.locator('#wallet-cta-open').click();
  await expect(page.locator('#wallet-modal')).toBeVisible();
  await page.locator('#wallet-modal .modal__close').click();
  await expect(page.locator('#wallet-modal')).not.toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true);
});
