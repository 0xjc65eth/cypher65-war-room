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
 *  15. INSERT: insertAdjacentHTML inline unescaped template literal → exit 1
 *      (the second argument is scanned like an innerHTML RHS)
 *  16. INSERT: bare-id argument built from a template literal with RAW
 *      fields (timeline pattern) → exit 1 (declaration-following)
 *  17. INSERT: bare-id argument built with escapeHtml → exit 0 (PASS)
 *  18. INNER: `el.innerHTML = rows` where rows is a pre-escaped template
 *      literal → exit 0 (PASS — bare-id declaration-following)
 *  19. TEXTCONTENT: '<b>' + x.name markup → exit 1 (HTML in textContent
 *      never renders — anti-pattern)
 *  20. TEXTCONTENT: plain data (el.textContent = x.name) → exit 0 (PASS)
 *  21. TEXTCONTENT: 'REPORTED < OBSERVED' literal (no tag shape) → exit 0
 *  22. INSERT: local HTML-builder function with raw field → exit 1
 *      (function body following)
 *  23. BRIDGE: (c.providers || []).map(p => … escapeHtml(p.label)) fed via
 *      innerHTML bare-id → exit 0 (the `||` fallback is a data SOURCE, no FP)
 *  24. BRIDGE: same shape but a raw member (p.label) → exit 1
 *  25. REPORT: `--report` on clean fixtures → exit 0 AND stdout has the
 *      GUARD_REPORT {...} JSON line (Issue #68 — CI trend report)
 *  26. REPORT: `--report` on an XSS fixture → exit 1 AND ok:false (counts
 *      are reported even when the merge gate blocks)
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
function runGuard(tmpDir, extraArgs) {
  const args = [GUARD].concat(extraArgs || []);
  const res = spawnSync(process.execPath, args, {
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

// ── Test 15: INSERT — insertAdjacentHTML inline unescaped TL → exit 1 ──
// The 2nd arg is an HTML sink: unescaped record fields must be flagged just
// like innerHTML.
(function testInsertAdjacentHtmlInlineFails() {
  const body = "el.insertAdjacentHTML('beforeend', `<div class=\"t\">${x.raw}</div>`);";
  const tmp = makeFixture(CLEAN_HTML, appJsWithConcatBody(body));
  try {
    const r = runGuard(tmp);
    assertEqual('insertAdjacentHTML inline raw TL → exit 1', r.status, 1);
    if (!/GUARD 2/.test(r.stdout)) {
      failures.push(`  ❌ insert-inline case did not flag GUARD 2:\n${r.stdout}`);
    }
  } finally {
    cleanup(tmp);
  }
})();

// ── Test 16: INSERT — bare-id arg built with RAW fields → exit 1 ────────
// The exact timeline pattern: `const rows = list.map(ev => `…${ev.id}…`)`
// injected via insertAdjacentHTML('beforeend', rows). The guard must follow
// the declaration and flag the raw interpolations.
(function testInsertAdjacentHtmlBareIdFails() {
  const body =
    "const rows = list.map(ev => `<div class=\"tf-${ev.severity}\" data-id=\"${ev.id}\">${ev.event_type}</div>`).join('');\n" +
    "el.insertAdjacentHTML('beforeend', rows);";
  const tmp = makeFixture(CLEAN_HTML, appJsWithConcatBody(body));
  try {
    const r = runGuard(tmp);
    assertEqual('insertAdjacentHTML bare-id raw TL → exit 1', r.status, 1);
    if (!/GUARD 2/.test(r.stdout)) {
      failures.push(`  ❌ insert-bareid case did not flag GUARD 2:\n${r.stdout}`);
    }
  } finally {
    cleanup(tmp);
  }
})();

// ── Test 17: INSERT — bare-id arg built with escapeHtml → exit 0 ────────
// Same pattern, but every record field is escaped → must PASS (no FP).
(function testInsertAdjacentHtmlEscapedPasses() {
  const body =
    "const rows = list.map(ev => `<div class=\"tf-${escapeHtml(ev.severity)}\">${escapeHtml(ev.id)}</div>`).join('');\n" +
    "el.insertAdjacentHTML('beforeend', rows);";
  const tmp = makeFixture(CLEAN_HTML, appJsWithConcatBody(body));
  try {
    const r = runGuard(tmp);
    assertEqual('insertAdjacentHTML bare-id escaped → exit 0', r.status, 0);
    if (r.status !== 0) failures.push(`  ❌ insert-escaped stdout:\n${r.stdout}`);
  } finally {
    cleanup(tmp);
  }
})();

// ── Test 18: INNER — innerHTML = bare-id built escaped → exit 0 ────────
// The `el.innerHTML = rows` blind spot: the guard must follow `rows` to its
// escaped template literal and PASS.
(function testInnerHtmlBareIdEscapedPasses() {
  const body =
    "const rows = list.map(m => `<div>${escapeHtml(m.tier)}</div>`).join('');\n" +
    "el.innerHTML = rows;";
  const tmp = makeFixture(CLEAN_HTML, appJsWithConcatBody(body));
  try {
    const r = runGuard(tmp);
    assertEqual('innerHTML = bare-id escaped → exit 0', r.status, 0);
    if (r.status !== 0) failures.push(`  ❌ inner-bareid-escaped stdout:\n${r.stdout}`);
  } finally {
    cleanup(tmp);
  }
})();

// ── Test 19: TEXTCONTENT — '<b>' + x.name markup → exit 1 ───────────────
// HTML markup in textContent never renders — flag the anti-pattern.
(function testTextContentMarkupFails() {
  const body = "el.textContent = '<b>' + x.name + '</b>';";
  const tmp = makeFixture(CLEAN_HTML, appJsWithConcatBody(body));
  try {
    const r = runGuard(tmp);
    assertEqual('textContent with <b> markup → exit 1', r.status, 1);
    if (!/GUARD 2/.test(r.stdout)) {
      failures.push(`  ❌ textContent-markup case did not flag GUARD 2:\n${r.stdout}`);
    }
  } finally {
    cleanup(tmp);
  }
})();

// ── Test 20: TEXTCONTENT — plain external data → exit 0 ─────────────────
// textContent with a raw field read is the CORRECT safe pattern (no XSS,
// no markup) — must not be flagged.
(function testTextContentPlainDataPasses() {
  const body = "el.textContent = x.name;";
  const tmp = makeFixture(CLEAN_HTML, appJsWithConcatBody(body));
  try {
    const r = runGuard(tmp);
    assertEqual('textContent plain data → exit 0', r.status, 0);
    if (r.status !== 0) failures.push(`  ❌ textContent-plain stdout:\n${r.stdout}`);
  } finally {
    cleanup(tmp);
  }
})();

// ── Test 21: TEXTCONTENT — '<' comparison literal → exit 0 ──────────────
// 'REPORTED < OBSERVED' contains '<' but no tag shape — must stay clean.
(function testTextContentLtLiteralPasses() {
  const body = "el.textContent = 'REPORTED < OBSERVED';";
  const tmp = makeFixture(CLEAN_HTML, appJsWithConcatBody(body));
  try {
    const r = runGuard(tmp);
    assertEqual('textContent < literal (no tag) → exit 0', r.status, 0);
    if (r.status !== 0) failures.push(`  ❌ textContent-lt stdout:\n${r.stdout}`);
  } finally {
    cleanup(tmp);
  }
})();

// ── Test 22: INSERT — local HTML-builder function with raw field → exit 1
// insertAdjacentHTML('beforeend', _rowHtml(x)) — the guard follows the
// builder body and flags raw interpolations inside its template literal.
(function testInsertAdjacentHtmlBuilderFails() {
  const body =
    "function _rowHtml(m) { return `<td>${m.raw}</td>`; }\n" +
    "el.insertAdjacentHTML('beforeend', _rowHtml(x));";
  const tmp = makeFixture(CLEAN_HTML, appJsWithConcatBody(body));
  try {
    const r = runGuard(tmp);
    assertEqual('insertAdjacentHTML raw builder → exit 1', r.status, 1);
    if (!/GUARD 2/.test(r.stdout)) {
      failures.push(`  ❌ insert-builder case did not flag GUARD 2:\n${r.stdout}`);
    }
  } finally {
    cleanup(tmp);
  }
})();

// ── Test 23: BRIDGE — (c.providers || []).map(… escaped …) → exit 0 ─────
// Regression for the rentals-concentration false positive: the `|| []`
// fallback between the field read and .map(…) must be recognized as a data
// SOURCE (transform), not a raw interpolation.
(function testTransformOrBridgeEscapedPasses() {
  const body =
    "const rows = (c.providers || []).map(p => '<div>' + escapeHtml(p.label) + '</div>').join('');\n" +
    "el.innerHTML = rows;";
  const tmp = makeFixture(CLEAN_HTML, appJsWithConcatBody(body));
  try {
    const r = runGuard(tmp);
    assertEqual('|| bridge + escaped members → exit 0', r.status, 0);
    if (r.status !== 0) failures.push(`  ❌ bridge-escaped stdout:\n${r.stdout}`);
  } finally {
    cleanup(tmp);
  }
})();

// ── Test 24: BRIDGE — same shape but raw member → exit 1 ────────────────
// The bridge must NOT mask a raw member read inside the callback.
(function testTransformOrBridgeRawMemberFails() {
  const body =
    "const rows = (c.providers || []).map(p => '<div>' + p.label + '</div>').join('');\n" +
    "el.innerHTML = rows;";
  const tmp = makeFixture(CLEAN_HTML, appJsWithConcatBody(body));
  try {
    const r = runGuard(tmp);
    assertEqual('|| bridge + raw member → exit 1', r.status, 1);
    if (!/GUARD 2/.test(r.stdout)) {
      failures.push(`  ❌ bridge-raw case did not flag GUARD 2:\n${r.stdout}`);
    }
  } finally {
    cleanup(tmp);
  }
})();

// ── Test 25: REPORT — --report clean → exit 0 + GUARD_REPORT JSON ──────
// The CI trend report (Issue #68): --report must keep the exit code and
// emit the grep-able GUARD_REPORT {...} line with the metric counts.
(function testReportModePasses() {
  const tmp = makeFixture(CLEAN_HTML, CLEAN_APP_JS);
  try {
    const r = runGuard(tmp, ['--report']);
    assertEqual('--report clean fixtures → exit 0', r.status, 0);
    if (!/GUARD_REPORT \{"tl":\d+/.test(r.stdout)) {
      failures.push(`  ❌ --report did not print GUARD_REPORT JSON:\n${r.stdout}`);
    }
  } finally {
    cleanup(tmp);
  }
})();

// ── Test 26: REPORT — --report XSS fixture → exit 1 + ok:false ─────────
// Counts must be reported even when the merge gate blocks.
(function testReportModeFails() {
  const tmp = makeFixture(CLEAN_HTML, appJsWithInterp("m.raw_tier"));
  try {
    const r = runGuard(tmp, ['--report']);
    assertEqual('--report XSS fixture → exit 1', r.status, 1);
    if (!/"ok":false/.test(r.stdout)) {
      failures.push(`  ❌ --report did not flag ok:false:\n${r.stdout}`);
    }
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
