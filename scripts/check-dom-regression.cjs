#!/usr/bin/env node
/**
 * check-dom-regression.js
 *
 * CI regression guards for the dashboard frontend:
 *
 *   GUARD 1 — Duplicate id="..." in templates/*.html
 *     A duplicated id breaks querySelector / getElementById lookups (the
 *     first match wins), so two elements with the same id is always a bug.
 *
 *   GUARD 2 — innerHTML with unescaped external data
 *     Every `${...}` interpolation inside an .innerHTML template literal
 *     must either be wrapped in escapeHtml(...) or be a provably safe
 *     expression (whitelisted number-only formatter like fmt.age,
 *     acFormatTime, local CSS map, numeric/string literal, bare
 *     pre-escaped fragment, counter). Note: fmt.diff/fmt.shortAddr echo
 *     raw input strings, so they are deliberately NOT whitelisted — they
 *     must always stay behind escapeHtml(...). Property accesses on record
 *     fields (e.block_height, a.category, m.tier, ...) are treated as
 *     external data and FLAGGED when not escaped — this is what turns a
 *     stored/API string into an XSS vector.
 *
 * Usage:
 *   node scripts/check-dom-regression.js
 *
 * Env overrides (used by the committed self-test):
 *   GUARD_TEMPLATES_DIR  — templates dir to scan (default: ./templates)
 *   GUARD_APP_JS         — app.js to scan (default: ./static/app.js)
 *
 * Exit codes:
 *   0 — all guards pass
 *   1 — at least one regression found
 *   2 — script error
 */
'use strict';

const fs = require('fs');
const path = require('path');

const ROOT = path.resolve(__dirname, '..');

// Paths are overridable via env for self-tests (tests/test_dom_guards.js
// points the guard at disposable fixture files in a temp dir).
const TEMPLATES_GLOB = process.env.GUARD_TEMPLATES_DIR || path.join(ROOT, 'templates');
const APP_JS = process.env.GUARD_APP_JS || path.join(ROOT, 'static', 'app.js');

// ── Guard 1: duplicate ids across every template ───────────────────────
function checkDuplicateIds() {
  const files = fs.readdirSync(TEMPLATES_GLOB).filter(f => f.endsWith('.html'));
  const seen = new Map(); // id -> { file, line }
  const dups = [];
  for (const file of files) {
    const text = fs.readFileSync(path.join(TEMPLATES_GLOB, file), 'utf-8');
    const lines = text.split('\n');
    lines.forEach((line, i) => {
      const re = /id="([a-zA-Z0-9_-]+)"/g;
      let m;
      while ((m = re.exec(line)) !== null) {
        const id = m[1];
        if (seen.has(id)) {
          dups.push({ id, first: seen.get(id), second: { file, line: i + 1 } });
        } else {
          seen.set(id, { file, line: i + 1 });
        }
      }
    });
  }
  if (dups.length) {
    console.log('  ❌ GUARD 1 — duplicate id="" found:');
    for (const d of dups) {
      console.log(`     #${d.id}  (${d.first.file}:${d.first.line} and ${d.second.file}:${d.second.line})`);
    }
    return false;
  }
  console.log('  ✅ GUARD 1 — no duplicate ids across ' + files.length + ' template(s).');
  return true;
}

// ── Guard 2: innerHTML interpolation escaping ──────────────────────────
const RE_TL = /\$\{([^}]*)\}/g;

// Expressions that are provably safe to interpolate into innerHTML:
//   - fmt.<SAFE>(...)    → whitelisted formatters that emit numbers/units
//                          ONLY (age, hashrate, uptime, secsToHuman, pct,
//                          usd, expectedBlock). fmt.diff() echoes raw input
//                          strings and fmt.shortAddr()/chunkAddr() return
//                          raw substrings — those MUST stay behind
//                          escapeHtml(...), so they are NOT whitelisted.
//   - acFormatTime(...)   → whitelisted local formatter
//   - severityClass[...]  → local CSS-class map (values are hardcoded)
//   - bare identifiers    → pre-escaped HTML fragments (rows, parts) or
//                           counter/index variables
//   - numeric/string literals and simple arithmetic (i+1)
// Anything that READS A RECORD FIELD (e.block_height, a.category, m.tier)
// without escapeHtml() is flagged as external data.
const SAFE_FORMATTERS = /^(fmt\.(age|hashrate|uptime|secsToHuman|pct|usd|expectedBlock)\(|acFormatTime\(|severityClass\[)/;
const RE_PROP_ACCESS = /[a-zA-Z_$][\w$]*\.[a-zA-Z_$]|\[[\s]*['"][^'"]+['"]\]/;

function isSafeInterpolation(expr) {
  const e = expr.trim();
  // 1. Explicitly escaped.
  if (e.includes('escapeHtml(')) return true;
  // 2. Whitelisted formatter call or local map lookup.
  if (SAFE_FORMATTERS.test(e)) return true;
  // 3. Numeric literal, arithmetic without property access (i+1, 42).
  if (/^[0-9]/.test(e) && !RE_PROP_ACCESS.test(e)) return true;
  // 4. String literal(s) only — e.g. 'YES' or '—'.
  if (/^['"]/.test(e) && !RE_PROP_ACCESS.test(e)) return true;
  // 5. Bare identifier(s) / simple math with no property access — e.g. rows,
  //    parts, i+1, count. (Pre-escaped fragments or counters.)
  if (!RE_PROP_ACCESS.test(e) && /^[a-zA-Z_$][\w$]*([\s]*[+\-]\s*[\w$()'"0-9]+)*$/.test(e)) return true;
  // 6. Ternary whose two arms are string/number literals (x ? 'YES' : 'NO').
  const tern = e.match(/^(.*?)\?\s*(['"][^'"]*['"]|\d+)\s*:\s*(['"][^'"]*['"]|\d+)\s*$/);
  if (tern && (/^['"]/.test(tern[2]) || /^\d/.test(tern[2]))) return true;
  // 7. Property access without escapeHtml → external data → FLAG.
  return false;
}

function checkInnerHtmlEscaping() {
  const text = fs.readFileSync(APP_JS, 'utf-8');
  const lines = text.split('\n');
  const flags = [];
  let tlCount = 0;

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    if (!/innerHTML\s*(\+=|=)/.test(line)) continue;
    // Join multi-line template literals: walk forward until the backtick
    // block closes (we count ${...} nesting conservatively — templates in
    // this codebase never nest backticks).
    let joined = line;
    let j = i;
    const opens = (joined.match(/`/g) || []).length;
    while (opens % 2 === 1 && j + 1 < lines.length) {
      joined += ' ' + lines[++j];
      if ((joined.match(/`/g) || []).length % 2 === 0) break;
    }
    // Collect interpolations that appear AFTER innerHTML on the same line block.
    const after = joined.slice(joined.indexOf('innerHTML'));
    tlCount += (after.match(/`/g) || []).length;
    const local = new RegExp(RE_TL.source, 'g');
    let m;
    while ((m = local.exec(after)) !== null) {
      const expr = m[1];
      if (!isSafeInterpolation(expr)) {
        flags.push({ line: i + 1, expr: expr.slice(0, 80) });
      }
    }
  }

  if (flags.length) {
    console.log('  ❌ GUARD 2 — unescaped innerHTML interpolation(s):');
    for (const f of flags) {
      console.log(`     app.js:${f.line}  \${${f.expr}}`);
      console.log('       → wrap in escapeHtml(...) or make it a literal');
    }
    return false;
  }
  console.log('  ✅ GUARD 2 — all ' + tlCount + ' innerHTML interpolations escaped or literal-safe.');
  return true;
}

// ── Main ───────────────────────────────────────────────────────────────
function main() {
  console.log('\n  ' + '='.repeat(58));
  console.log('  CYPHER65 — DOM Regression Guards');
  console.log('  ' + '='.repeat(58));
  const ok1 = checkDuplicateIds();
  const ok2 = checkInnerHtmlEscaping();
  console.log('  ' + '='.repeat(58));
  if (ok1 && ok2) {
    console.log('  ✅ PASS — all DOM regression guards green\n');
    process.exit(0);
  }
  console.log('  ❌ FAIL — fix the regressions above before merging\n');
  process.exit(1);
}

main();
