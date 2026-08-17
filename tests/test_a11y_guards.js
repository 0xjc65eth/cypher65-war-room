#!/usr/bin/env node
/**
 * CYPHER65 // WAR ROOM — A11y Guards Self-Test
 * =============================================
 *
 * Protects scripts/check-a11y.cjs from regressions in the guard itself.
 * Runs the REAL guard binary (subprocess, not mocks) against disposable
 * fixture files in a temp dir via the GUARD_TPL_DIR env override, and
 * asserts the exit codes / flagged guards:
 *
 *   1. Baseline clean (lang pt-BR + named buttons + valid labels) → exit 0
 *   2. lang="en"                       → exit 1 (GUARD 1)
 *   3. <button>☰</button> icon-only    → exit 1 (GUARD 2)
 *   4. <button title="X">☰</button>    → exit 0 (title = accessible name)
 *   5. <button>⚡ CONNECT</button>      → exit 0 (emoji + text = nomeado)
 *   6. <button><svg/></button>         → exit 1 (GUARD 2)
 *   7. <a href="#"><svg/></a>          → exit 1 (GUARD 2, links também)
 *   8. <a aria-label="GitHub"><svg/></a> → exit 0
 *   9. <label>texto</label> órfão      → exit 1 (GUARD 3)
 *  10. <label for="x">texto</label>    → exit 0
 *  11. <label><input/></label> wrap    → exit 0
 *  12. --report em fixture limpo       → exit 0 AND GUARD_REPORT ok:true
 *  13. --report em fixture sujo        → exit 1 AND GUARD_REPORT ok:false
 *  14. Templates reais (sem override)  → exit 0 (dashboard está limpo)
 *
 * Run: node tests/test_a11y_guards.js   (wired into check_frontend.sh)
 */

'use strict';

import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(__dirname, '..');
const GUARD = path.join(ROOT, 'scripts', 'check-a11y.cjs');

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
    failures.push(`  ❌ ${label}: padrão ${re} não encontrado na saída`);
  }
}

// Run the real guard against a fixture dashboard.html in a temp dir.
function runGuard(html, args = []) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'a11y-fixture-'));
  fs.writeFileSync(path.join(dir, 'dashboard.html'), html);
  const res = spawnSync(process.execPath, [GUARD, ...args], {
    cwd: ROOT,
    env: { ...process.env, GUARD_TPL_DIR: dir },
    encoding: 'utf8',
  });
  fs.rmSync(dir, { recursive: true, force: true });
  return res;
}

const SHELL = (inner) => `<!doctype html>\n<html lang="pt-BR">\n<body>\n${inner}\n</body>\n</html>\n`;

// 1. Baseline clean — todos os padrões válidos juntos.
{
  const res = runGuard(SHELL(`
    <button aria-label="Menu">☰</button>
    <button title="Fechar">×</button>
    <button>⚡ CONNECT</button>
    <label for="x">Nome</label><input id="x">
    <label>Termos <input type="checkbox" id="y"></label>
  `));
  assertEqual('1 · baseline limpo exit 0', res.status, 0);
}

// 2. lang errado.
{
  const res = runGuard(SHELL('<button aria-label="Menu">☰</button>').replace('lang="pt-BR"', 'lang="en"'));
  assertEqual('2 · lang="en" exit 1', res.status, 1);
  assertMatch('2 · flag GUARD 1', res.stdout, /GUARD 1 — lang="en"/);
}

// 3. Botão ícone-only sem nome.
{
  const res = runGuard(SHELL('<button>☰</button>'));
  assertEqual('3 · ícone-only exit 1', res.status, 1);
  assertMatch('3 · flag GUARD 2', res.stdout, /GUARD 2 — button ícone-only/);
}

// 4. Ícone-only com title = nome acessível válido.
{
  const res = runGuard(SHELL('<button title="Abrir menu">☰</button>'));
  assertEqual('4 · title nomeia exit 0', res.status, 0);
}

// 5. Emoji + texto = botão nomeado.
{
  const res = runGuard(SHELL('<button>⚡ CONNECT WALLET</button>'));
  assertEqual('5 · emoji+texto exit 0', res.status, 0);
}

// 6. SVG-only sem nome.
{
  const res = runGuard(SHELL('<button><svg xmlns="http://www.w3.org/2000/svg"><path d="M0 0"/></svg></button>'));
  assertEqual('6 · svg-only exit 1', res.status, 1);
  assertMatch('6 · flag GUARD 2', res.stdout, /GUARD 2/);
}

// 7. Link ícone-only sem nome.
{
  const res = runGuard(SHELL('<a href="#"><svg xmlns="http://www.w3.org/2000/svg"><path d="M0 0"/></svg></a>'));
  assertEqual('7 · a ícone-only exit 1', res.status, 1);
  assertMatch('7 · flag GUARD 2 em <a>', res.stdout, /GUARD 2 — a ícone-only/);
}

// 8. Link ícone-only com aria-label.
{
  const res = runGuard(SHELL('<a href="#" aria-label="GitHub"><svg xmlns="http://www.w3.org/2000/svg"><path d="M0 0"/></svg></a>'));
  assertEqual('8 · a com aria-label exit 0', res.status, 0);
}

// 9. Label órfão.
{
  const res = runGuard(SHELL('<label class="foo">texto solto</label>'));
  assertEqual('9 · label órfão exit 1', res.status, 1);
  assertMatch('9 · flag GUARD 3', res.stdout, /GUARD 3 — <label> órfão/);
}

// 10. Label com for.
{
  const res = runGuard(SHELL('<label for="x">Nome</label><input id="x">'));
  assertEqual('10 · label com for exit 0', res.status, 0);
}

// 10b. Botão ícone-only expresso como ENTIDADE NUMÉRICA (&#10095; = ❯) —
// o literal contém dígitos; sem o decode a guarda deixaria passar.
{
  const res = runGuard(SHELL('<button>&#10095;</button>'));
  assertEqual('10b · entidade numérica ícone-only exit 1', res.status, 1);
  assertMatch('10b · flag GUARD 2', res.stdout, /GUARD 2 — button ícone-only/);
}

// 11. Label que envolve o controle.
{
  const res = runGuard(SHELL('<label>Termos <input type="checkbox" id="y"></label>'));
  assertEqual('11 · label wrap exit 0', res.status, 0);
}

// 12. --report limpo.
{
  const res = runGuard(SHELL('<button aria-label="Menu">☰</button>'), ['--report']);
  assertEqual('12 · report limpo exit 0', res.status, 0);
  assertMatch('12 · GUARD_REPORT ok:true', res.stdout, /GUARD_REPORT \{"guard":"a11y","ok":true/);
}

// 13. --report sujo.
{
  const res = runGuard(SHELL('<button>☰</button>'), ['--report']);
  assertEqual('13 · report sujo exit 1', res.status, 1);
  assertMatch('13 · GUARD_REPORT ok:false', res.stdout, /GUARD_REPORT \{"guard":"a11y","ok":false/);
}

// 14. Templates reais (dashboard.html + agent_guide.html, sem override).
{
  const res = spawnSync(process.execPath, [GUARD], { cwd: ROOT, encoding: 'utf8' });
  assertEqual('14 · templates reais exit 0', res.status, 0);
}

// ═══════════════════════════════════════════════════════════════════════
//  RESULTS
// ═══════════════════════════════════════════════════════════════════════

console.log(`\n${'═'.repeat(50)}`);
if (failed === 0) {
  console.log(`✅ ALL ${passed} A11Y-GUARD SELF-TESTS PASSED`);
} else {
  console.log(`❌ ${failed}/${passed + failed} A11Y-GUARD SELF-TESTS FAILED`);
  failures.forEach((f) => console.log(f));
}

process.exit(failed > 0 ? 1 : 0);
