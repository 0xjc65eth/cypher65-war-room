#!/usr/bin/env node
/**
 * CYPHER65 // WAR ROOM — Axe Gate Self-Test
 * ==========================================
 *
 * Protects scripts/check-axe.cjs (Issue #244) from regressions in the gate
 * itself. Runs the REAL gate binary (subprocess, not mocks) against
 * disposable fixture files (file:// via --fixture) and asserts exit codes:
 *
 *   1. Fixture limpa (h1 + nav label + botão nomeado + contraste ok)  → exit 0
 *   2. Fixture com botão ícone-only sem nome                          → exit 1 (button-name)
 *   3. Fixture com 2 textos de baixo contraste                        → exit 1 (score < 90)
 *   4. --report na fixture limpa                                      → exit 0 + GUARD_REPORT ok:true
 *   5. --report na fixture com button-name                            → exit 1 + GUARD_REPORT ok:false
 *   6. --report na fixture de contraste                               → exit 1 + GUARD_REPORT ok:false
 *   7. Fixture fora de landmark (regressão do CI #245: wallet-cta     → exit 1 (region, score < 90)
 *      visível no estado logged-out sem <main>/<nav>)
 *
 * Caso real coberto pelo teste 7: no CI o servidor renderiza o estado
 * logged-out e o CTA de wallet ficava fora de qualquer landmark → a regra
 * `region` derrubava o score para 88 (falha que quebrou a 1ª rodada de CI
 * do PR #245). O fixture reproduz essa classe de falha sem depender de
 * estado de servidor.
 *
 * Run: node tests/test_axe_gate.js   (wired into check_frontend.sh)
 */

'use strict';

import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(__dirname, '..');
const GATE = path.join(ROOT, 'scripts', 'check-axe.cjs');

let passed = 0;
let failed = 0;
const failures = [];

function assertEqual(label, actual, expected) {
  if (actual === expected) {
    passed++;
  } else {
    failed++;
    failures.push(`  ❌ ${label}: expected ${expected}, got ${actual}`);
  }
}

function assertMatch(label, haystack, re) {
  if (re.test(haystack)) {
    passed++;
  } else {
    failed++;
    failures.push(`  ❌ ${label}: não casou ${re} em:\n${haystack.slice(0, 400)}`);
  }
}

function runGate(fixturePath, report) {
  const args = [];
  if (fixturePath) args.push('--fixture', fixturePath);
  if (report) args.push('--report');
  const r = spawnSync('node', [GATE, ...args], { encoding: 'utf-8', timeout: 90000 });
  return { code: r.status, out: String(r.stdout || '') + String(r.stderr || '') };
}

const FIX_OK = `<!DOCTYPE html>
<html lang="pt-BR">
<head><meta charset="utf-8"><title>OK</title>
<style>body{background:#070808;color:#eaeaea;font-family:sans-serif;margin:0}
nav,main{display:block}p{color:#eaeaea}</style>
</head>
<body>
<nav aria-label="Principal"><a href="#a">Início</a></nav>
<main>
<h1>Título da página</h1>
<p>Texto com contraste ok</p>
<button type="button">Ação principal</button>
</main>
</body>
</html>`;

const FIX_BAD_NAME = `<!DOCTYPE html>
<html lang="pt-BR">
<head><meta charset="utf-8"><title>BadName</title></head>
<body>
<main>
<h1>Teste</h1>
<button type="button"><svg width="16" height="16"><rect width="16" height="16"/></svg></button>
</main>
</body>
</html>`;

const FIX_BAD_CONTRAST = `<!DOCTYPE html>
<html lang="pt-BR">
<head><meta charset="utf-8"><title>BadContrast</title>
<style>body{background:#070808;margin:0;font-family:sans-serif}</style>
</head>
<body>
<main>
<h1>Teste</h1>
<p style="color:#5c5e62">texto apagado um</p>
<p style="color:#5c5e62">texto apagado dois</p>
</main>
</body>
</html>`;

// Reproduz o estado logged-out/empty-state do CI: conteúdo fora de qualquer
// landmark (sem <main>/<nav>) → regra `region` (moderate) derruba o score
// abaixo de 90. Foi exatamente o que quebrou a 1ª rodada de CI do PR #245
// (wallet-cta visível sem sessão).
const FIX_BAD_REGION = `<!DOCTYPE html>
<html lang="pt-BR">
<head><meta charset="utf-8"><title>BadRegion</title>
<style>body{background:#070808;color:#eaeaea;margin:0;font-family:sans-serif}</style>
</head>
<body>
<div class="cta">
  <div>Conteúdo solto um — fora de landmark</div>
  <div>Conteúdo solto dois — fora de landmark</div>
  <div>Conteúdo solto três — fora de landmark</div>
</div>
</body>
</html>`;

const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'axe-gate-test-'));
const files = {
  ok: path.join(tmp, 'ok.html'),
  badName: path.join(tmp, 'bad-name.html'),
  badContrast: path.join(tmp, 'bad-contrast.html'),
  badRegion: path.join(tmp, 'bad-region.html'),
};
fs.writeFileSync(files.ok, FIX_OK);
fs.writeFileSync(files.badName, FIX_BAD_NAME);
fs.writeFileSync(files.badContrast, FIX_BAD_CONTRAST);
fs.writeFileSync(files.badRegion, FIX_BAD_REGION);

try {
  // 1. limpa → exit 0
  let r = runGate(files.ok, false);
  assertEqual('fixture limpa → exit 0', r.code, 0);

  // 2. button-name → exit 1
  r = runGate(files.badName, false);
  assertEqual('fixture button-name → exit 1', r.code, 1);
  assertMatch('saída cita button-name', r.out, /button-name/);

  // 3. contraste → exit 1 (score < 90)
  r = runGate(files.badContrast, false);
  assertEqual('fixture contraste → exit 1', r.code, 1);
  assertMatch('saída cita color-contrast', r.out, /color-contrast/);

  // 4. --report limpa → ok:true
  r = runGate(files.ok, true);
  assertEqual('--report limpa → exit 0', r.code, 0);
  assertMatch('--report ok:true', r.out, /GUARD_REPORT \{"guard":"axe","ok":true/);

  // 5. --report button-name → ok:false
  r = runGate(files.badName, true);
  assertEqual('--report button-name → exit 1', r.code, 1);
  assertMatch('--report ok:false', r.out, /GUARD_REPORT \{"guard":"axe","ok":false/);

  // 6. --report contraste → ok:false
  r = runGate(files.badContrast, true);
  assertEqual('--report contraste → exit 1', r.code, 1);
  assertMatch('--report contraste ok:false', r.out, /GUARD_REPORT \{"guard":"axe","ok":false/);

  // 7. regressão do CI (#245): conteúdo fora de landmark (estado logged-out)
  //    → regra `region` derruba o score < 90 → exit 1
  r = runGate(files.badRegion, false);
  assertEqual('fixture region (fora de landmark) → exit 1', r.code, 1);
  assertMatch('saída cita region', r.out, /region/);

  // 8. --report na fixture region → ok:false (GUARD_REPORT para o pipeline)
  r = runGate(files.badRegion, true);
  assertEqual('--report region → exit 1', r.code, 1);
  assertMatch('--report region ok:false', r.out, /GUARD_REPORT \{"guard":"axe","ok":false/);
} finally {
  fs.rmSync(tmp, { recursive: true, force: true });
}

console.log(`\n════════════════════════════════════════════════════════`);
console.log(failed === 0
  ? `✅ ALL ${passed} AXE GATE TESTS PASSED`
  : `❌ ${failed}/${passed + failed} TESTS FAILED`);
console.log(`════════════════════════════════════════════════════════`);
for (const f of failures) console.log(f);
process.exit(failed === 0 ? 0 : 1);
