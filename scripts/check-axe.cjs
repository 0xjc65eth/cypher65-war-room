#!/usr/bin/env node
/**
 * check-axe.cjs — GATE de acessibilidade com axe-core REAL (Issue #244)
 * ================================================================
 * Roda axe-core (WCAG 2.0/2.1 A/AA + best-practice) nos viewports desktop
 * (1440×900) e mobile (375×812) e FALHA (exit 1) se:
 *   - qualquer viewport tiver violações da regra `button-name` (> 0), OU
 *   - o score proxy de qualquer viewport for < 90.
 *
 * Score proxy (axe não tem score nativo — documentado aqui):
 *   score = max(0, 100 − (critical×20 + serious×10 + moderate×4 + minor×1))
 *
 * Padrão dos guards irmãos: check-a11y.cjs / check-tokens-hex.sh / check-dom.
 * Dependências (devDeps): @playwright/test + axe-core.
 *
 * Uso:
 *   node scripts/check-axe.cjs                 # servidor em AUDIT_URL (padrão :8765)
 *   node scripts/check-axe.cjs --report        # + JSON de resumo no stdout
 *   node scripts/check-axe.cjs --fixture f.html  # mede um arquivo local (self-test)
 *   AUDIT_URL=http://localhost:5000 node scripts/check-axe.cjs
 *
 * Exit codes:
 *   0 — gate verde (0 button-name, score ≥ 90 nos 2 viewports)
 *   1 — violações acima do limite (merge bloqueado)
 *   2 — erro de execução (axe-core/Playwright ausentes, servidor fora do ar)
 */
'use strict';
const fs = require('fs');
const path = require('path');
const { chromium } = require('@playwright/test');

const BASE_URL = process.env.AUDIT_URL || 'http://127.0.0.1:8765';
const ARGS = process.argv.slice(2);
const REPORT = ARGS.includes('--report');
const FIXTURE_IDX = ARGS.indexOf('--fixture');
const FIXTURE = FIXTURE_IDX >= 0 ? ARGS[FIXTURE_IDX + 1] || null : null;
const AXE_SRC = path.join(__dirname, '..', 'node_modules', 'axe-core', 'axe.min.js');

const VIEWPORTS = [
  { name: 'desktop', width: 1440, height: 900 },
  { name: 'mobile', width: 375, height: 812 },
];

const IMPACT_PENALTY = { critical: 20, serious: 10, moderate: 4, minor: 1 };
const MIN_SCORE = 90;

function scoreOf(byImpact) {
  return Math.max(0, 100
    - (byImpact.critical || 0) * IMPACT_PENALTY.critical
    - (byImpact.serious || 0) * IMPACT_PENALTY.serious
    - (byImpact.moderate || 0) * IMPACT_PENALTY.moderate
    - (byImpact.minor || 0) * IMPACT_PENALTY.minor);
}

(async () => {
  if (!fs.existsSync(AXE_SRC)) {
    console.error('❌ [axe] axe-core ausente — rode: npm install (devDep axe-core)');
    process.exit(2);
  }
  const axeSource = fs.readFileSync(AXE_SRC, 'utf-8');
  const browser = await chromium.launch();
  let worst = { score: 100, buttonName: 0, violations: 0 };
  const results = [];

  for (const vp of VIEWPORTS) {
    const page = await browser.newPage({ viewport: { width: vp.width, height: vp.height } });
    console.log(`\n${'═'.repeat(60)}`);
    console.log(`  VIEWPORT ${vp.name.toUpperCase()} — ${vp.width}x${vp.height}`);
    console.log(`${'═'.repeat(60)}`);
    try {
      if (FIXTURE) {
        await page.goto('file://' + path.resolve(FIXTURE), { waitUntil: 'load', timeout: 15000 });
        await page.waitForTimeout(300);
      } else {
        await page.goto(BASE_URL, { waitUntil: 'domcontentloaded', timeout: 20000 });
        await page.waitForTimeout(6500); // boot + primeiro poll
      }
    } catch (e) {
      console.error(`  ✗ não abriu o alvo: ${e.message.split('\n')[0]}`);
      await browser.close();
      process.exit(2);
    }
    await page.addScriptTag({ content: axeSource });
    const res = await page.evaluate(async () => {
      const r = await window.axe.run(document, {
        runOnly: { type: 'tag', values: ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'best-practice'] },
      });
      return {
        violations: r.violations.map((v) => ({
          id: v.id, impact: v.impact, nodes: v.nodes.length,
          targets: v.nodes.slice(0, 3).map((n) => (n.target || []).join(' ')),
        })),
        passes: r.passes.length,
        incomplete: r.incomplete.length,
      };
    });
    const byImpact = { critical: 0, serious: 0, moderate: 0, minor: 0 };
    for (const v of res.violations) byImpact[v.impact] = (byImpact[v.impact] || 0) + v.nodes;
    const score = scoreOf(byImpact);
    const buttonName = (res.violations.find((v) => v.id === 'button-name') || { nodes: 0 }).nodes;

    console.log(`  violações: ${res.violations.length} regra(s) / ${res.violations.reduce((a, v) => a + v.nodes, 0)} nó(s) · passes: ${res.passes} · incomplete: ${res.incomplete}`);
    console.log(`  critical=${byImpact.critical || 0} serious=${byImpact.serious || 0} moderate=${byImpact.moderate || 0} minor=${byImpact.minor || 0}`);
    console.log(`  button-name: ${buttonName} · SCORE proxy: ${score}/100`);
    if (res.violations.length) {
      console.log('  ── violações ──');
      for (const v of res.violations) {
        console.log(`   [${v.impact}] ${v.id} (${v.nodes} nó(s))`);
        for (const t of v.targets) console.log(`        → ${t}`);
      }
    }
    results.push({ vp: vp.name, score, buttonName, violations: res.violations.length });
    if (score < worst.score) worst.score = score;
    if (buttonName > worst.buttonName) worst.buttonName = buttonName;
    await page.close();
  }

  const ok = worst.buttonName === 0 && worst.score >= MIN_SCORE;
  console.log(`\n${'═'.repeat(60)}`);
  console.log(`  GATE: button-name máx=${worst.buttonName} (limite 0) · score mín=${worst.score} (limite ${MIN_SCORE}) → ${ok ? '✅ PASS' : '❌ FAIL'}`);
  console.log(`${'═'.repeat(60)}`);
  if (REPORT) {
    console.log('GUARD_REPORT ' + JSON.stringify({ guard: 'axe', ok, views: results.map((r) => ({ vp: r.vp, score: r.score, buttonName: r.buttonName, violations: r.violations })) }));
  }
  await browser.close();
  process.exit(ok ? 0 : 1);
})();
