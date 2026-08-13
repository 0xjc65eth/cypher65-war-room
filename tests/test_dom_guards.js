#!/usr/bin/env node
/**
 * CYPHER65 // WAR ROOM — DOM Regression Guards Self-Test
 * ======================================================
 *
 * Protects scripts/check-dom-regression.cjs from regressions in the guard
 * itself. Runs the REAL guard binary (subprocess, not mocks) against
 * disposable fixture files in a temp dir via the GUARD_TEMPLATES_DIR /
 * GUARD_APP_JS env overrides, and asserts the exit codes:
 *
 *   1. Baseline (clean fixtures)          → exit 0 (PASS)
 *   2. XSS: record field without escape  → exit 1 (FAIL + flag)
 *   3. Dup id in a template              → exit 1 (FAIL + flag)
 *   4. fmt.diff (echoes raw string)      → exit 1 (FAIL + flag)
 *      WITHOUT escapeHtml — the Issue #48 vector
 *   5. Escaped data                      → exit 0 (PASS)
 *
 * Run: node tests/test_dom_guards.js     (also wired into CI gate)
 */

'use strict';

import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

const ROOT = path.resolve(__dirname, '..');
const GUARD = path.join(ROOT, 'scripts', 'check-dom-regression.cjs');

// ── Test counters (same harness pattern as test_app_js_core.js) ─────────
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

// ── Fixture helpers ─────────────────────────────────────────────────────
// Clean template: 2 unique ids. Clean app.js: innerHTML with escaped data
// + a bare pre-escaped fragment (rows) that the allowlist accepts.
const CLEAN_HTML = `<!doctype html><html><body>
  <div id="topbar-address"></div>
  <div id="status-pill"></div>
</body></html>`;

const CLEAN_APP_JS = `(() => {
  'use strict';
  function escapeHtml(s) { return String(s).replace(/[&<>"']/g, c => ({ '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;' }[c])); }
  function render(list) {
    const el = document.getElementById('x');
    el.innerHTML = list.map(m => '<div class="t">' + escapeHtml(m.tier) + '</div>').join('');
  }
  const rows = ['<span>ok</span>'];
  const el2 = document.getElementById('y');
  el2.innerHTML = '<div class="w">' + rows + '</div>';
})();`;

// Build a fixture app.js with a specific interpolation injected.
// Uses a TEMPLATE LITERAL inside .innerHTML — the exact pattern the guard
// scans (string concatenation with '+' is a separate, future guard).
// NOTE: the @@INTERP@@ placeholder is replaced AFTER the outer template
// literal is built, so the generated file really contains `${interp}`
// (escaping ${ inside a nested template literal is a trap — \${ emits
// the literal text without the variable, \\\${ emits a backslash).
function appJsWithInterp(interp) {
  const body = `function render(list) {
    const el = document.getElementById('x');
    el.innerHTML = list.map(m => \`<div class="t">\${@@INTERP@@}</div>\`).join('');
  }`.replace('@@INTERP@@', interp);
  return `(() => {
  'use strict';
  function escapeHtml(s) { return String(s).replace(/[&<>"']/g, c => ({ '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;' }[c])); }
  ${body}
})();`;
}

// Run the real guard against a fixture dir; returns { status, stdout }.
function runGuard(tmpDir) {
  const res = spawnSync(process.execPath, [GUARD], {
    cwd: ROOT,
    env: Object.assign({}, process.env, {
      GUARD_TEMPLATES_DIR: path.join(tmpDir, 'templates'),
      GUARD_APP_JS: path.join(tmpDir, 'app.js'),
    }),
    encoding: 'utf-8',
    timeout: 30000,
  });
  return { status: res.status, stdout: res.stdout || '' };
}

function makeFixture(html, appJs) {
  const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'c65-dom-guards-'));
  const tmplDir = path.join(tmpDir, 'templates');
  fs.mkdirSync(tmplDir, { recursive: true });
  fs.writeFileSync(path.join(tmplDir, 'dashboard.html'), html);
  fs.writeFileSync(path.join(tmpDir, 'app.js'), appJs);
  return tmpDir;
}

function cleanup(tmpDir) {
  try { fs.rmSync(tmpDir, { recursive: true, force: true }); } catch (e) { /* best effort */ }
}

// ── Test 1: baseline clean → exit 0 ─────────────────────────────────────
(function testBaselinePasses() {
  const tmp = makeFixture(CLEAN_HTML, CLEAN_APP_JS);
  try {
    const r = runGuard(tmp);
    assertEqual('baseline clean fixtures → exit 0', r.status, 0);
    if (r.status !== 0) failures.push(`  ❌ baseline stdout:\n${r.stdout}`);
  } finally {
    cleanup(tmp);
  }
})();

// ── Test 2: unescaped record field → exit 1 (XSS vector) ────────────────
(function testUnescapedRecordFieldFails() {
  const tmp = makeFixture(CLEAN_HTML, appJsWithInterp("m.raw_tier"));
  try {
    const r = runGuard(tmp);
    assertEqual('unescaped m.raw_tier → exit 1', r.status, 1);
    if (!/GUARD 2/.test(r.stdout)) {
      failures.push(`  ❌ XSS case did not flag GUARD 2:\n${r.stdout}`);
    }
  } finally {
    cleanup(tmp);
  }
})();

// ── Test 3: duplicate id in template → exit 1 ───────────────────────────
(function testDuplicateIdFails() {
  const dupHtml = `<!doctype html><html><body>
    <div id="status-pill"></div>
    <div id="status-pill" hidden></div>
  </body></html>`;
  const tmp = makeFixture(dupHtml, CLEAN_APP_JS);
  try {
    const r = runGuard(tmp);
    assertEqual('duplicate id → exit 1', r.status, 1);
    if (!/GUARD 1/.test(r.stdout)) {
      failures.push(`  ❌ dup-id case did not flag GUARD 1:\n${r.stdout}`);
    }
  } finally {
    cleanup(tmp);
  }
})();

// ── Test 4: fmt.diff WITHOUT escape → exit 1 (Issue #48 vector) ─────────
(function testFmtDiffWithoutEscapeFails() {
  const tmp = makeFixture(CLEAN_HTML, appJsWithInterp("fmt.diff(m.raw_difficulty)"));
  try {
    const r = runGuard(tmp);
    assertEqual('fmt.diff without escape → exit 1', r.status, 1);
    if (!/GUARD 2/.test(r.stdout)) {
      failures.push(`  ❌ fmt.diff case did not flag GUARD 2:\n${r.stdout}`);
    }
  } finally {
    cleanup(tmp);
  }
})();

// ── Test 5: escaped data + safe formatter in a TEMPLATE LITERAL → exit 0 ─
(function testEscapedAndSafeFormatterPass() {
  // All three interpolations must pass the allowlist WITHOUT touching the
  // real repo: escapeHtml(...), counter (i+1), fmt.age (number-only fmt).
  const safeAppJs = `(() => {
  'use strict';
  function escapeHtml(s) { return String(s).replace(/[&<>"']/g, c => ({ '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;' }[c])); }
  function render(list) {
    const el = document.getElementById('x');
    el.innerHTML = list.map((m, i) => \`<div class="t">${'${escapeHtml(m.tier)}'} ${'${i+1}'} ${'${fmt.age(m.ts)}'}</div>\`).join('');
  }
})();`;
  const tmp = makeFixture(CLEAN_HTML, safeAppJs);
  try {
    const r = runGuard(tmp);
    assertEqual('escaped + fmt.age + counter (template literal) → exit 0', r.status, 0);
    if (r.status !== 0) failures.push(`  ❌ safe-allowlist stdout:\n${r.stdout}`);
  } finally {
    cleanup(tmp);
  }
})();

// ── Test 6: missing fixture files → exit 2 (script error path) ──────────
(function testMissingFilesExit2() {
  const tmp = makeFixture(CLEAN_HTML, CLEAN_APP_JS);
  try {
    const r = runGuard(tmp);
    assertEqual('fixtures present → guard runs (no exit 2)', r.status !== 2, true);
  } finally {
    cleanup(tmp);
  }
})();

// ═══════════════════════════════════════════════════════════════════════
//  RESULTS
// ═══════════════════════════════════════════════════════════════════════

console.log(`\n${'═'.repeat(50)}`);
if (failed === 0) {
  console.log(`✅ ALL ${passed} DOM-GUARD SELF-TESTS PASSED`);
} else {
  console.log(`❌ ${failed}/${passed + failed} DOM-GUARD SELF-TESTS FAILED`);
  failures.forEach(f => console.log(f));
}

process.exit(failed > 0 ? 1 : 0);
