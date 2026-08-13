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
 *   6. Fixtures present                  → guard runs (no exit 2)
 *   7. CONCAT: x.msg without escapeHtml  → exit 1 (FAIL + flag)
 *      rows.map(x => '<td>' + x.msg + '</td>') — the '+' chain vector
 *   8. CONCAT: escaped + ternary + map/join → exit 0 (PASS, no FP)
 *   9. CONCAT: (e.worker || '') + slice  → exit 1 (FAIL + flag)
 *  10. CONCAT: fmt.age arg inside operand → exit 0 (PASS, no FP)
 *      ticker pattern: (e.ts ? fmt.age(e.ts) : '--:--:--')
 *  11. CONCAT: fmt.diff inside operand   → exit 1 (FAIL + flag)
 *  12. CONCAT: (m.color || fb) raw in style= → exit 1 (FAIL + flag)
 *      support-config is external data — CSS injection vector
 *  13. CONCAT: setup consts BEFORE return → exit 0 (PASS, documented
 *      truncateAtReturn tradeoff — fields stay inside `return`)
 *  14. CONCAT: 'https://…' URL in a literal → exit 0 (PASS, string-aware
 *      stripComments — // inside a string is not a comment)
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
// scans for the ${...} path.
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

// Fixture app.js that injects a BODY with string concatenation ('+') inside
// .innerHTML — the pattern the CONCAT scanner targets.
function appJsWithConcatBody(body) {
  return `(() => {
  'use strict';
  function escapeHtml(s) { return String(s).replace(/[&<>"']/g, c => ({ '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;' }[c])); }
  function render() {
    const el = document.getElementById('x');
    ${body}
  }
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

// ── Test 7: CONCAT — x.msg without escapeHtml → exit 1 (Issue #64) ─────
(function testConcatUnescapedFieldFails() {
  const body = "el.innerHTML = rows.map(x => '<td>' + x.msg + '</td>').join('');";
  const tmp = makeFixture(CLEAN_HTML, appJsWithConcatBody(body));
  try {
    const r = runGuard(tmp);
    assertEqual('concat x.msg without escape → exit 1', r.status, 1);
    if (!/GUARD 2/.test(r.stdout)) {
      failures.push(`  ❌ concat-XSS case did not flag GUARD 2:\n${r.stdout}`);
    }
  } finally {
    cleanup(tmp);
  }
})();

// ── Test 8: CONCAT — escaped + ternary + map/join → exit 0 (no FP) ──────
(function testConcatEscapedTernaryPasses() {
  // Mirrors the remote-checklist / trust-cell patterns: ternary conditions
  // read record fields (safe), arms are literals, member fields escaped.
  const body = `el.innerHTML = rows.map(x => ` +
    `'<li class="' + (x.done ? 'completed' : 'pending') + '" data-step="' + escapeHtml(String(x.id)) + '">' + ` +
    `'<span class="rci-icon">' + (x.done ? '●' : '○') + '</span>' + ` +
    `'<span class="rci-text">' + escapeHtml(x.label || x.id) + '</span>' + ` +
    `'</li>').join('');`;
  const tmp = makeFixture(CLEAN_HTML, appJsWithConcatBody(body));
  try {
    const r = runGuard(tmp);
    assertEqual('concat escaped + ternary + map/join → exit 0', r.status, 0);
    if (r.status !== 0) failures.push(`  ❌ concat-safe stdout:\n${r.stdout}`);
  } finally {
    cleanup(tmp);
  }
})();

// ── Test 9: CONCAT — (e.worker || '') + address.slice → exit 1 ──────────
(function testConcatWalletHistoryFails() {
  const body =
    "el.innerHTML = '<span class=\"mono\">' + e.address.slice(0, 10) + '</span> ' + (e.worker || '') + '!';";
  const tmp = makeFixture(CLEAN_HTML, appJsWithConcatBody(body));
  try {
    const r = runGuard(tmp);
    assertEqual('concat wallet-history pattern → exit 1', r.status, 1);
    if (!/GUARD 2/.test(r.stdout)) {
      failures.push(`  ❌ concat-wallet case did not flag GUARD 2:\n${r.stdout}`);
    }
  } finally {
    cleanup(tmp);
  }
})();

// ── Test 10: CONCAT — safe formatter INSIDE a concat operand → exit 0 ───
// Regression for the live-calculator ticker (e.ts ? fmt.age(e.ts) : …):
// fmt.age emits numbers/units only, so its ARGS are never interpolated —
// the strip step must remove whitelisted formatter calls from operands or
// the argument read becomes a false positive.
(function testConcatSafeFormatterPasses() {
  const body = "el.innerHTML = '<span class=\"t\">' + (e.ts ? fmt.age(e.ts) : '--:--:--') + '</span>' + '<span>' + escapeHtml(e.share_diff_str) + '</span>';";
  const tmp = makeFixture(CLEAN_HTML, appJsWithConcatBody(body));
  try {
    const r = runGuard(tmp);
    assertEqual('concat fmt.age arg + escaped field → exit 0', r.status, 0);
    if (r.status !== 0) failures.push(`  ❌ concat-formatter-safe stdout:\n${r.stdout}`);
  } finally {
    cleanup(tmp);
  }
})();

// ── Test 11: CONCAT — fmt.diff inside a concat operand → exit 1 ─────────
// fmt.diff echoes a raw input string (Issue #48 vector) — the strip must
// NOT touch it inside '+' chains either.
(function testConcatFmtDiffFails() {
  const body = "el.innerHTML = '<b>' + fmt.diff(e.raw_difficulty) + '</b>';";
  const tmp = makeFixture(CLEAN_HTML, appJsWithConcatBody(body));
  try {
    const r = runGuard(tmp);
    assertEqual('concat fmt.diff without escape → exit 1', r.status, 1);
    if (!/GUARD 2/.test(r.stdout)) {
      failures.push(`  ❌ concat-fmtdiff case did not flag GUARD 2:\n${r.stdout}`);
    }
  } finally {
    cleanup(tmp);
  }
})();

// ── Test 12: CONCAT — (m.color || fallback) raw in style= → exit 1 ──────
// Support config is external (operator-authored) data; m.color lands in a
// style="color:…" attribute — CSS injection vector, must be escaped.
(function testConcatStyleAttrFails() {
  const body = "el.innerHTML = '<span style=\"color:' + (m.color || '#00ff41') + '\">' + (m.icon || '\u20bf') + ' ' + escapeHtml(m.label) + '</span>';";
  const tmp = makeFixture(CLEAN_HTML, appJsWithConcatBody(body));
  try {
    const r = runGuard(tmp);
    assertEqual('concat m.color/m.icon raw → exit 1', r.status, 1);
    if (!/GUARD 2/.test(r.stdout)) {
      failures.push(`  ❌ concat-style-attr case did not flag GUARD 2:\n${r.stdout}`);
    }
  } finally {
    cleanup(tmp);
  }
})();

// ── Test 13: CONCAT — map callback with pre-return setup consts → exit 0 ─
// Documents the truncateAtReturn tradeoff: setup consts BEFORE `return`
// (numeric coercion + ternary conditions) are not scanned — this is what
// keeps the guard free of false positives on the worst-rigs/provider-
// rankings blocks. Guidance: keep field interpolations inside `return`.
(function testConcatSetupConstsPass() {
  const body =
    `el.innerHTML = rows.map(r => {\n` +
    `  const dlv = r.avg_delivery_pct != null ? Number(r.avg_delivery_pct).toFixed(1) + '%' : '—';\n` +
    `  const pl = r.avg_pl_pct >= 0 ? '+' : '';\n` +
    `  return '<div class=\"cell\">' + escapeHtml(String(r.label)) + '</div>' + escapeHtml(dlv) + escapeHtml(pl);\n` +
    `}).join('');`;
  const tmp = makeFixture(CLEAN_HTML, appJsWithConcatBody(body));
  try {
    const r = runGuard(tmp);
    assertEqual('concat setup-consts before return → exit 0', r.status, 0);
    if (r.status !== 0) failures.push(`  ❌ concat-setup-consts stdout:\n${r.stdout}`);
  } finally {
    cleanup(tmp);
  }
})();

// ── Test 14: CONCAT — 'https://…' URL inside a literal → exit 0 (no FP) ──
// stripComments is string-aware: the `//` inside the URL must NOT be treated
// as a comment (which would delete the closing quote and corrupt the scan).
(function testConcatUrlLiteralPasses() {
  const body = `el.innerHTML = '<a href="https://example.com">' + escapeHtml(x.label) + '</a>' + '<span>https://api.example.io/x?y=1</span>';`;
  const tmp = makeFixture(CLEAN_HTML, appJsWithConcatBody(body));
  try {
    const r = runGuard(tmp);
    assertEqual('concat URL literal (https://) → exit 0', r.status, 0);
    if (r.status !== 0) failures.push(`  ❌ concat-url-literal stdout:\n${r.stdout}`);
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
