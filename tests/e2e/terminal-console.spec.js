import { test, expect } from '@playwright/test';
import { clickToolbarAction } from './support/toolbar.js';
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
  await page.route('**/api/axe-fleet/devices/*/history*',r=>{
    const id=decodeURIComponent(new URL(r.request().url()).pathname.split('/')[4]);
    const base=id==='desk-01'?1.2e12:200e12;
    r.fulfill({json:{device_id:id,history:Array.from({length:18},(_,i)=>({ts:now()-((18-i)*60),hashrate:i===8?0:base*(.96+Math.sin(i*.8)*.04),temperature:51+i*.15,power_watts:id==='desk-01'?19+i*.1:3500}))}});
  });
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
  const visual = await page.locator('#console-visual').boundingBox();
  expect(visual.y + visual.height).toBeLessThan(page.viewportSize().height);
  if(info.project.name==='chromium') {
    const firstRow=await page.locator('#console-table-body tr').first().boundingBox();
    expect(firstRow.y+firstRow.height).toBeLessThan(page.viewportSize().height);
  }
  await expect(page.locator('#console-worker-count')).toHaveText('2');
  await expect(page.locator('.console-bar')).toHaveCount(2);
  await expect(page.locator('#console-visual')).toContainText('82.00 TH/s');
  await expect(page.locator('#console-visual')).toContainText('14.00 TH/s');
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
  await expect(page.locator('#console-power')).toHaveText('19 W');
  await expect(page.locator('#console-visual circle')).toHaveCount(18);
  await expect(page.locator('#console-history-device')).toHaveValue('desk-01');
  await expect(page.locator('#console-history-stats')).toContainText('0.00 H/s');
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

test('individual history switches metrics and never connects missing or delayed samples',async({page},info)=>{
  await fixture(page,{local:fleet()});
  await expect(page.locator('#console-visual circle')).toHaveCount(18);
  await page.locator('#console-history-metric').selectOption('temperature');
  await expect(page.locator('#console-history-stats')).toContainText('°C');
  await expect(page.locator('#console-history-stats')).not.toContainText('TH/s');
  await page.locator('#console-history-metric').selectOption('power_watts');
  await expect(page.locator('#console-history-stats')).toContainText(' W');
  await page.route('**/api/axe-fleet/devices/rack-02/history*',r=>r.fulfill({json:{device_id:'rack-02',history:[
    {ts:now()-700,hashrate:200e12},{ts:now()-650,hashrate:null},{ts:now()-600,hashrate:0},{ts:now()-550,hashrate:180e12},{ts:now()-10,hashrate:190e12}
  ]}}));
  await page.locator('#console-history-metric').selectOption('hashrate');
  await page.locator('#console-history-device').selectOption('rack-02');
  await expect(page.locator('#console-visual circle')).toHaveCount(4);
  await expect(page.locator('#console-visual polyline')).toHaveCount(1);
  await expect(page.locator('#console-history-stats')).toContainText('200.0 TH/s');
  await expect(page.locator('#console-visual-note')).toContainText('lacunas >150 s não conectadas');
  await page.locator('#console-history-data summary').click();
  await expect(page.locator('#console-history-samples')).toContainText('0.00 H/s');
  await expect(page.locator('#console-history-samples')).toContainText('—');
  await noOverflow(page);
  await page.screenshot({path:info.outputPath('fleet-history-gaps.png'),fullPage:true});
});

test('one observation draws one point and failed refresh retains clearly dated history',async({page},info)=>{
  await fixture(page,{local:fleet()});
  await page.route('**/api/axe-fleet/devices/desk-01/history*',r=>r.fulfill({json:{device_id:'desk-01',history:[{ts:now()-600,hashrate:1e12}]}}));
  await page.locator('#console-history-refresh').click();
  await expect(page.locator('#console-visual circle')).toHaveCount(1);
  await expect(page.locator('#console-visual polyline')).toHaveCount(0);
  await expect(page.locator('#console-visual-note')).toContainText('1 amostras');
  await page.route('**/api/axe-fleet/devices/desk-01/history*',r=>r.fulfill({status:503,json:{error:'unavailable'}}));
  await page.locator('#console-history-refresh').click();
  await expect(page.locator('#console-visual-note')).toContainText('Consulta indisponível');
  await expect(page.locator('#console-visual circle')).toHaveCount(1);
  await expect(page.locator('#console-hashrate')).toHaveText('1.20 TH/s');
  await page.screenshot({path:info.outputPath('history-failed.png'),fullPage:true});
  await page.route('**/api/axe-fleet/devices/desk-01/history*',r=>r.fulfill({status:403,json:{error:'denied'}}));
  await page.locator('#console-history-refresh').click();
  await expect(page.locator('#console-visual')).toContainText('Histórico indisponível');
  await expect(page.locator('#console-visual circle')).toHaveCount(0);
});

test('history is scoped to the selected equipment and late responses cannot replace it',async({page})=>{
  await fixture(page,{local:fleet()});
  await expect(page.locator('#console-visual circle')).toHaveCount(18);
  let release; const gate=new Promise(resolve=>release=resolve);
  await page.route('**/api/axe-fleet/devices/desk-01/history*',async r=>{await gate;await r.fulfill({json:{device_id:'desk-01',history:[{ts:now()-10,hashrate:99e12}]}}).catch(()=>{});});
  await page.locator('#console-history-refresh').click();
  await page.locator('#console-history-device').selectOption('rack-02');
  await expect(page.locator('#console-visual circle')).toHaveCount(18);
  await expect(page.locator('#console-history-stats')).toContainText('TH/s');
  const late=page.waitForResponse(r=>r.url().includes('/desk-01/history'));
  release();await late;
  await expect(page.locator('#console-history-device')).toHaveValue('rack-02');
  await expect(page.locator('#console-history-stats')).not.toContainText('99.00 TH/s');
  await page.route('**/api/axe-fleet/devices/rack-02/history*',r=>r.fulfill({json:{device_id:'another-device',history:[{ts:now()-5,hashrate:999e12}]}}));
  await page.locator('#console-history-refresh').click();
  await expect(page.locator('#console-visual-note')).toContainText('Consulta indisponível');
  await expect(page.locator('#console-history-stats')).not.toContainText('999');
});


test('history age follows the last valid metric and all plotted samples have a text alternative',async({page},info)=>{
  await fixture(page,{local:fleet()});
  await expect(page.locator('#console-visual circle')).toHaveCount(18);
  const fixed=now();
  const rows=Array.from({length:120},(_,i)=>({ts:fixed-1000+i*5,hashrate:1e12+i*1e9}));
  rows.push({ts:fixed-10,hashrate:null});
  await page.route('**/api/axe-fleet/devices/desk-01/history*',r=>r.fulfill({json:{device_id:'desk-01',history:rows}}));
  await page.locator('#console-history-refresh').click();
  await expect(page.locator('#console-visual-note')).toContainText('última medição válida há');
  await expect(page.locator('#console-visual-note')).not.toContainText('há 10.0s');
  const note=await page.locator('#console-visual-note').textContent();
  expect(note).toMatch(/última medição válida há [6-9]\.\d+m/);
  await page.locator('#console-history-data summary').click();
  await expect(page.locator('#console-history-samples tbody tr')).toHaveCount(120);
  await expect(page.locator('#console-history-samples')).toContainText('Todas as 120 amostras');
  await page.screenshot({path:info.outputPath('history-text-alternative.png'),fullPage:true});
});

test('summary cards use native keyboard navigation with destinations matching their labels',async({page})=>{
  await fixture(page);
  const lastShare=page.locator('#kpi-row button.kpi-card').nth(3);
  await expect(lastShare).toContainText('Última share');
  await lastShare.focus();await lastShare.press('Enter');
  await expect(page.locator('body')).toHaveAttribute('data-active-module','live');
  await openModule(page,'dashboard');
  const workers=page.locator('#kpi-row button.kpi-card').nth(2);
  await workers.focus();await workers.press('Space');
  await expect(page.locator('body')).toHaveAttribute('data-active-module','live');
});


test('real login and logout invalidate a pending history response across tenants',async({page})=>{
  await fixture(page,{local:fleet()});
  await expect(page.locator('#console-visual circle')).toHaveCount(18);
  let release;const gate=new Promise(resolve=>release=resolve);
  await page.route('**/api/axe-fleet/devices/desk-01/history*',async r=>{await gate;await r.fulfill({json:{device_id:'desk-01',history:[{ts:now()-10,hashrate:99e12}]}}).catch(()=>{});});
  await page.locator('#console-history-refresh').click();
  const next={fleet_stats:{total_devices:1},device_health:[{id:'acme-one',name:'ACME miner',status:'ONLINE',telemetry:{ts:now()-5,hashrate_hs:2e12}}]};
  await page.route('**/api/axe-fleet/health*',r=>r.fulfill({json:next}));
  await page.route('**/api/axe-fleet/devices/acme-one/history*',r=>r.fulfill({json:{device_id:'acme-one',history:[{ts:now()-10,hashrate:2e12}]}}));
  await page.route('**/api/auth/login',r=>r.fulfill({json:{success:true,access_token:'fixture-acme',refresh_token:'fixture-refresh',expires_at:Math.floor(now())+3600,tenant_id:'acme'}}));
  await page.route('**/api/auth/logout',r=>r.fulfill({json:{success:true}}));
  await clickToolbarAction(page,'#auth-toggle');
  await page.locator('#auth-api-key').fill('fixture-key');await page.locator('#auth-login').click();
  await expect(page.locator('#console-history-device')).toHaveValue('acme-one');
  await expect(page.locator('#console-history-stats')).toContainText('2.00 TH/s');
  const late=page.waitForResponse(r=>r.url().includes('/desk-01/history'));release();await late;
  await expect(page.locator('#console-history-stats')).not.toContainText('99.00 TH/s');
  await clickToolbarAction(page,'#auth-toggle');await page.locator('#auth-logout').click();
  await expect(page.locator('#console-visual circle')).toHaveCount(0);
});
