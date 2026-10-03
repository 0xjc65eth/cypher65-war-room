import { test, expect } from '@playwright/test';
test.use({serviceWorkers:'block'});

const now = () => Date.now()/1000;
function fleet(stale=false) {
  return {fleet_stats:{total_devices:2},agent:{last_seen:now()-5},device_health:[
    {id:'desk-01',name:'Mesa 01',model:'Bitaxe Gamma',status:'ONLINE',telemetry:{ts:now()-(stale?600:10),hashrate_hs:1.2e12,temperature:53,power_watts:19,shares_accepted:125,shares_rejected:0}},
    {id:'rack-02',name:'Rack 02',model:'Antminer S21',status:'OFFLINE',telemetry:{ts:now()-(stale?620:30),hashrate_hs:0,last_known_hashrate_hs:200e12,temperature:62,power_watts:3500}}
  ]};
}
async function fixture(page, {local=null,address=true,workers=true}={}) {
  await page.route('**/api/stream*',r=>r.abort());
  await page.route('**/api/axe-fleet/health*',r=>r.fulfill({json:local||{fleet_stats:{total_devices:0},device_health:[]}}));
  await page.route('**/api/snapshot*',r=>r.fulfill({json:{
    ts:now(),btc_address:address?'bc1qpc3832jcu6m8qpqjvz5lkuydwjzv8v5vq5t5rs':'',
    worker:workers?{name:'worker-01',hashrate:82e12,bestDifficulty:85e9,lastSubmission:now()-60}:null,
    all_workers:workers?[{name:'worker-01',hashrate:82e12,lastSubmission:now()-60,is_primary:true},{name:'worker-02',hashrate:14e12,lastSubmission:now()-130}]:[],
    network:{height:969641,difficulty:132.76e12,hashrate:897e18},pool:{hashrate:323e15,highestDiff:63e12,workers:4944,users:2323},btc_price:{usd:84537}
  }}));
  await page.goto('/');
  await expect(page.locator('#n-height')).toHaveText('#969641');
  await expect(page.locator('#console-fleet-source')).not.toContainText('aguardando');
}
async function openModule(page,name) {
  const toggle=page.locator('#sidebar-mobile-toggle');
  if(await toggle.isVisible() && !(await page.locator('#sidebar').evaluate(e=>e.classList.contains('open')))) await toggle.click();
  await page.locator('.sidebar__link[data-module="'+name+'"]').click();
  await expect(page.locator('body')).toHaveAttribute('data-active-module',name);
}
async function noOverflow(page) {
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1)).toBe(true);
}

test('pool-only operation has one summary and identified workers',async({page},info)=>{
  await fixture(page);
  await expect(page.locator('#operation-console')).toHaveAttribute('data-source','pool');
  await expect(page.locator('#kpi-hashrate')).toHaveText('82.00 TH/s');
  await expect(page.locator('#console-table-body tr')).toHaveCount(2);
  await expect(page.locator('#console-table-body tr').nth(1)).toContainText('14.00 TH/s');
  await expect(page.locator('#console-fleet-source')).toContainText('nenhum cadastrado');
  await expect(page.locator('#console-source-fleet')).toBeDisabled();
  for(const id of ['hero-worker','operational-overview','network-panel','pool-overview','console-fleet-summary','tbar-status','tbar-hr']) await expect(page.locator('#'+id)).toBeHidden();
  expect(await page.locator('.console-entity').first().evaluate(e=>parseFloat(getComputedStyle(e).fontSize))).toBeGreaterThanOrEqual(12);
  await noOverflow(page);
  const firstRow = await page.locator('#console-table-body tr').first().boundingBox();
  expect(firstRow.y + firstRow.height).toBeLessThan(page.viewportSize().height);
  await expect(page.locator('#console-worker-scope')).toHaveText('worker · worker-01');
  await page.screenshot({path:info.outputPath('pool-operation.png'),fullPage:true});
  await page.locator('#console-search').fill('worker-02');
  await expect(page.locator('#console-table-body tr')).toHaveCount(1);
  await expect(page.locator('#console-table-body')).toContainText('worker-02');
  await page.locator('#console-search').fill('');
  await page.locator('#console-open-analysis').click();
  await expect(page.locator('#network-panel')).toBeVisible();
  await expect(page.locator('#operation-console')).toBeHidden();
});

test('Fleet prioritizes exceptions and opens an accessible detail without commands',async({page},info)=>{
  const writes=[];page.on('request',r=>{if(r.url().includes('/api/axe-fleet')&&r.method()!=='GET')writes.push(r.method());});
  await fixture(page,{local:fleet()});
  await expect(page.locator('#operation-console')).toHaveAttribute('data-source','fleet');
  await expect(page.locator('#console-table-body tr').first()).toContainText('Rack 02');
  await expect(page.locator('#console-table-body tr').first()).toContainText('última observação');
  await expect(page.locator('#console-hashrate')).toHaveText('1.20 TH/s');
  await expect(page.locator('#console-attention-count')).toHaveText('1');
  await expect(page.locator('#kpi-row')).toBeHidden();
  await noOverflow(page);
  await page.screenshot({path:info.outputPath('fleet-operation.png'),fullPage:true});
  const entity=page.locator('[data-console-id="rack-02"]');
  await entity.focus();await entity.press('Enter');
  await expect(page.getByRole('dialog',{name:'Rack 02'})).toBeVisible();
  await expect(page.locator('#console-detail')).toHaveClass(/console-detail--instant/);
  await expect(page.locator('#console-detail-fields')).toContainText('200.0 TH/s');
  await expect(page.locator('#console-detail-close')).toBeFocused();
  await page.screenshot({path:info.outputPath('fleet-detail.png'),fullPage:true});
  // Exercise the real refresh path while the dialog is open, as a background poll would.
  await page.evaluate(()=>document.getElementById('refresh-now').click());
  await expect(page.locator('#console-table-body tr')).toHaveCount(2);
  await page.keyboard.press('Escape');
  await expect(page.locator('#console-detail')).toBeHidden();
  await expect(entity).toBeFocused();
  expect(writes).toEqual([]);
  await page.locator('#console-source-pool').click();
  await expect(page.locator('#operation-console')).toHaveAttribute('data-source','pool');
});

test('old Fleet observations do not present current health or current hashrate',async({page},info)=>{
  await fixture(page,{local:fleet(true)});
  await expect(page.locator('#console-notice')).toContainText('Telemetria local incompleta ou antiga');
  await expect(page.locator('#console-attention-count')).toHaveText('—');
  await expect(page.locator('#console-hashrate')).toHaveText('—');
  await expect(page.locator('#console-measured')).toHaveText('0 / 2');
  await expect(page.locator('#console-table-body')).toContainText('amostra antiga ou idade não informada');
  await page.screenshot({path:info.outputPath('fleet-stale.png'),fullPage:true});
});

test('failed Fleet refresh retains observations and recovery confirms the source',async({page},info)=>{
  await fixture(page,{local:fleet()});
  await page.route('**/api/axe-fleet/health*',r=>r.fulfill({status:503,json:{error:'fixture unavailable'}}));
  await page.locator('#refresh-now').click();
  await expect(page.locator('#console-notice-title')).toHaveText('Consulta à frota indisponível');
  await expect(page.locator('#console-table-body tr')).toHaveCount(2);
  await expect(page.locator('#console-table-body')).toContainText('consulta indisponível');
  await expect(page.locator('#console-hashrate')).toHaveText('—');
  await expect(page.locator('#console-measured')).toHaveText('2 / 2');
  await expect(page.locator('#console-recent-scope')).toContainText('estado atual não confirmado');
  await expect(page.locator('#console-table-body')).toContainText('Último estado: Online');
  await page.screenshot({path:info.outputPath('fleet-failed.png'),fullPage:true});
  await page.locator('[data-console-id="desk-01"]').click();
  await expect(page.locator('#console-detail-status')).toContainText('último estado informado: Online');
  await page.keyboard.press('Escape');
  await page.route('**/api/axe-fleet/health*',r=>r.fulfill({json:fleet()}));
  await page.locator('#console-notice-action').click();
  await expect(page.locator('#console-hashrate')).toHaveText('1.20 TH/s');
});

test('all 14 modules remain reachable with reduced motion',async({page})=>{
  await page.emulateMedia({reducedMotion:'reduce'});await fixture(page);
  for(const name of ['fleet','analysis','live','wallet','probability','market','rentals','alerts','automations','docs','learning','admin','support','dashboard']) {
    await openModule(page,name);await expect(page.locator('#module-header-title')).not.toBeEmpty();await noOverflow(page);
    if(name==='support') await page.locator('#support-panel .modal__close').click();
  }
  await page.locator('[data-console-id="worker-01"]').click();
  await expect(page.locator('#console-detail')).toHaveCSS('animation-name','none');
});

test('light theme and 200 percent CSS zoom retain readable controls',async({page},info)=>{
  await page.setViewportSize({width:1440,height:900});await fixture(page);
  await page.locator('#theme-toggle').click();await expect(page.locator('html')).toHaveAttribute('data-theme','light');
  await page.screenshot({path:info.outputPath('pool-light.png'),fullPage:true});
  await page.evaluate(()=>document.documentElement.style.zoom='2');
  await noOverflow(page);await expect(page.locator('#refresh-now')).toBeVisible();
  await page.screenshot({path:info.outputPath('pool-zoom-200.png'),fullPage:true});
});

test('empty pool retains setup and does not invent healthy equipment',async({page})=>{
  await fixture(page,{address:false,workers:false});
  await expect(page.locator('#wallet-cta')).toBeVisible();await expect(page.locator('#kpi-hashrate')).toHaveText('—');
  await expect(page.locator('#console-table-body')).toContainText('Nenhum worker identificado');
  await expect(page.locator('#console-fleet-source')).toContainText('nenhum cadastrado');
  await page.locator('#wallet-cta-open').click();await expect(page.locator('#wallet-modal')).toBeVisible();
  await page.locator('#wallet-modal .modal__close').click();await expect(page.locator('#wallet-modal')).toBeHidden();await noOverflow(page);
});
