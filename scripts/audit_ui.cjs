#!/usr/bin/env node
/**
 * audit_ui.cjs — CYPHER65 · UI AUDIT (Playwright)
 * ===============================================
 *
 * Auditoria visual reutilizável do dashboard: console errors, page errors,
 * overflow horizontal, elementos truncados/estourados, status bar e presença
 * de skeletons nos módulos tardios. Também injeta falha no primeiro fetch
 * (/api/snapshot → 500) para provar que os skeletons do boot são escondidos
 * no caminho de ERRO (Sev-1 da auditoria 2026-08 — nunca skeleton eterno).
 * Usado na rodada de auditoria 2026-08 (docs/AUDITORIA_2026-08.md), sob
 * demanda ou no CI (check_frontend.sh).
 *
 * Pré-requisito: servidor Flask rodando (padrão http://127.0.0.1:8765).
 *
 * Uso:
 *   node scripts/audit_ui.cjs                          # viewport desktop
 *   node scripts/audit_ui.cjs --mobile                 # viewport 375x812
 *   node scripts/audit_ui.cjs --all                    # desktop + mobile
 *   AUDIT_URL=http://localhost:5000 node scripts/audit_ui.cjs
 *
 * Flags:
 *   --mobile    audita só o viewport mobile (375x812)
 *   --all       roda desktop + mobile
 *   --strict    exit 1 se QUALQUER console error/warning aparecer
 *               (padrão: exit 1 só para overflow/truncamento/page error)
 *
 * Exit codes (CI-friendly):
 *   0 — passou (ou achou apenas avisos não-estritos)
 *   1 — problemas encontrados (overflow, truncamento, page error, console
 *       error em --strict)
 *   2 — erro de execução (servidor fora do ar, script quebrou)
 */

'use strict';
const { chromium } = require('@playwright/test');

const BASE_URL = process.env.AUDIT_URL || 'http://127.0.0.1:8765';
const ARGS = process.argv.slice(2);
const ALLOW_MOBILE = ARGS.includes('--all');
const ONLY_MOBILE = ARGS.includes('--mobile');
const STRICT = ARGS.includes('--strict');

const VIEWPORTS = [];
if (!ONLY_MOBILE) VIEWPORTS.push({ name: 'desktop', width: 1440, height: 900 });
if (ALLOW_MOBILE || ONLY_MOBILE) VIEWPORTS.push({ name: 'mobile', width: 375, height: 812 });

let exitCode = 0;

function fail(problem) {
  exitCode = 1;
  console.log(`\n  ❌ ${problem}`);
}

async function auditViewport(browser, vp) {
  console.log(`\n${'═'.repeat(60)}`);
  console.log(`  VIEWPORT ${vp.name.toUpperCase()} — ${vp.width}x${vp.height}`);
  console.log(`${'═'.repeat(60)}`);

  const page = await browser.newPage({ viewport: { width: vp.width, height: vp.height } });
  const consoleErrors = [];
  const pageErrors = [];

  page.on('console', (m) => {
    if (m.type() === 'error') consoleErrors.push(m.text());
    else if (m.type() === 'warning' && STRICT) consoleErrors.push('[warn] ' + m.text());
  });
  page.on('pageerror', (e) => pageErrors.push(String(e)));

  try {
    await page.goto(BASE_URL, { waitUntil: 'domcontentloaded', timeout: 20000 });
  } catch (e) {
    console.error(`\n  ✗ Não consegui abrir ${BASE_URL} — servidor no ar? (${e.message.split('\n')[0]})`);
    return { fatal: true };
  }
  await page.waitForTimeout(6000); // boot + primeiro poll

  const report = { vp: vp.name };

  // 1) Overflow horizontal da página
  report.overflow = await page.evaluate(() => {
    const d = document.documentElement;
    return { scrollWidth: d.scrollWidth, clientWidth: d.clientWidth };
  });

  // 2) Elementos com texto estourando o box (leaf nodes)
  report.truncated = await page.evaluate(() => {
    const out = [];
    const els = document.querySelectorAll('span, div, button, a, td, th, strong');
    for (const el of els) {
      if (el.children.length) continue;
      const r = el.getBoundingClientRect();
      if (r.width < 8 || r.height < 4) continue;
      const sw = el.scrollWidth, cw = el.clientWidth;
      const clipped = getComputedStyle(el).overflow !== 'visible';
      if (sw > cw + 4 && !clipped) {
        if (out.length < 15) {
          out.push({
            tag: el.tagName,
            cls: (el.className || '').toString().slice(0, 40),
            text: (el.textContent || '').trim().slice(0, 40),
            overflowPx: Math.round(sw - cw),
          });
        }
      }
    }
    return out;
  });

  // 3) Status bar (valores principais)
  report.status = await page.evaluate(() => {
    const pick = (id) => {
      const el = document.getElementById(id);
      return el ? el.textContent.trim().slice(0, 24) : '(missing)';
    };
    return {
      sbStatus: pick('sb-status'),
      sbHashrate: pick('sb-hashrate'),
      sbBestdiff: pick('sb-bestdiff'),
      sbNetDiff: pick('sb-net-diff'),
      sbNetPrice: pick('sb-net-price'),
      heroHr: pick('m-hashrate'),
      heroState: pick('m-state'),
    };
  });

  // 4) Skeletons: overlays presentes após o boot devem ser ZERO
  report.skelLeftovers = await page.evaluate(() =>
    document.querySelectorAll('.skel-overlay').length
  );

  // 5b) Sev-1 regression (UI audit 2026-08): a FAILED first fetch must hide
  // the boot skeletons — never leave them stuck (mobile showed 40 overlays
  // frozen with the status bar at INIT). Intercept /api/snapshot → 500,
  // reload, and require ZERO skeleton leftovers after the error path runs.
  let failSkel = { leftovers: -1 };
  try {
    await page.route('**/api/snapshot', (route) =>
      route.fulfill({ status: 500, contentType: 'application/json', body: '{}' })
    );
    await page.reload({ waitUntil: 'domcontentloaded', timeout: 20000 });
    await page.waitForTimeout(3000); // fetch falha → catch → hideSkeletons()
    failSkel.leftovers = await page.evaluate(() =>
      document.querySelectorAll('.skel-overlay').length
    );
    await page.unroute('**/api/snapshot');
    await page.reload({ waitUntil: 'domcontentloaded', timeout: 20000 });
    await page.waitForTimeout(2000); // restaurar estado real p/ seção 6
  } catch (e) { /* não fatal — route/unroute pode falhar em viewports exóticos */ }

  // 5) Ativação de módulos tardios — skeleton aparece e some (market)
  let marketSkel = { shown: 0, after: 0 };
  try {
    await page.evaluate(() => { try { localStorage.removeItem('_active_module'); } catch (e) {} });
    // abre sidebar mobile se necessário e clica no módulo market
    await page.evaluate(() => { const b = document.getElementById('sidebar-mobile-toggle'); if (b) b.click(); });
    await page.waitForTimeout(200);
    await page.locator('.sidebar__link[data-module="market"]').click();
    await page.waitForTimeout(350);
    marketSkel.shown = await page.locator('#market-panel .skel-overlay').count();
    await page.waitForTimeout(1500);
    marketSkel.after = await page.locator('#market-panel .skel-overlay').count();
  } catch (e) { /* navegação pode variar por viewport — não fatal */ }

  // 6) Resultado
  const ov = report.overflow;
  const overflowBad = ov.scrollWidth > ov.clientWidth + 2;
  const truncBad = report.truncated.length > 0;
  const pageErrBad = pageErrors.length > 0;
  const consoleBad = consoleErrors.length > 0 && STRICT;

  console.log('\n  CONSOLE ERRORS' + (STRICT ? ' (incl. warnings — strict)' : ''));
  console.log(consoleErrors.length ? consoleErrors.slice(0, 12).join('\n    ') : '    (none)');
  console.log('  PAGE ERRORS');
  console.log(pageErrors.length ? pageErrors.slice(0, 6).join('\n    ') : '    (none)');
  console.log('  OVERFLOW:', JSON.stringify(ov), overflowBad ? ' ← BAD' : '');
  console.log('  TRUNCATED/OVERFLOWING ELEMENTS:', report.truncated.length
    ? '\n    ' + report.truncated.map(t => `${t.tag}.${t.cls} (+${t.overflowPx}px) "${t.text}"`).join('\n    ')
    : '    (none)');
  console.log('  STATUS BAR:', JSON.stringify(report.status));
  console.log('  SKELETON LEFTOVERS pós-boot:', report.skelLeftovers, report.skelLeftovers > 0 ? ' ← BAD' : '');
  console.log('  MARKET SKELETON: shown=' + marketSkel.shown, 'after=' + marketSkel.after);
  console.log('  SKELETON APÓS FETCH FALHANDO (500):', failSkel.leftovers, failSkel.leftovers > 0 ? ' ← BAD' : '');

  if (overflowBad) fail(`${vp.name}: overflow horizontal (${ov.scrollWidth} > ${ov.clientWidth})`);
  if (truncBad) fail(`${vp.name}: ${report.truncated.length} elemento(s) estourado(s)`);
  if (pageErrBad) fail(`${vp.name}: ${pageErrors.length} page error(s)`);
  if (consoleBad) fail(`${vp.name}: ${consoleErrors.length} console error(s) (strict)`);
  if (report.skelLeftovers > 0) fail(`${vp.name}: skeleton overlay(s) preso(s) após o boot`);
  if (failSkel.leftovers > 0) fail(`${vp.name}: ${failSkel.leftovers} skeleton(s) preso(s) após FETCH FALHAR (Sev-1 — hideSkeletons no catch)`);

  await page.close();
  return report;
}

(async () => {
  if (!VIEWPORTS.length) VIEWPORTS.push({ name: 'desktop', width: 1440, height: 900 });

  const browser = await chromium.launch();
  const results = [];
  for (const vp of VIEWPORTS) {
    const r = await auditViewport(browser, vp);
    if (r && r.fatal) { exitCode = 2; break; }
    if (r) results.push(r);
  }
  await browser.close();

  console.log(`\n${'═'.repeat(60)}`);
  console.log(`  AUDIT UI — ${results.length} viewport(s) · ${exitCode === 0 ? '✅ PASS' : exitCode === 1 ? '❌ ISSUES' : '✗ FATAL'}`);
  console.log(`${'═'.repeat(60)}\n`);
  process.exit(exitCode);
})().catch((e) => {
  console.error('AUDIT UI FAILED:', e.message);
  process.exit(2);
});
