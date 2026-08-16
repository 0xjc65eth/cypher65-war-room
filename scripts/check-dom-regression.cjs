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
 *     Every place the code injects external data into an .innerHTML string
 *     must escape it. Two syntaxes are scanned:
 *
 *     (a) Template literals — every `${...}` interpolation must either be
 *         wrapped in escapeHtml(...) or be a provably safe expression
 *         (whitelisted number-only formatter like fmt.age, acFormatTime,
 *         local CSS map, numeric/string literal, bare pre-escaped fragment,
 *         counter).
 *     (b) String concatenation with '+' outside template literals — e.g.
 *         rows.map(x => '<td>' + x.msg + '</td>').join(''). Each operand
 *         adjacent to the static HTML fragments is checked with the same
 *         allowlist philosophy: a read of an external record field
 *         (x.msg, entry.worker, entry.address.slice(0,10), ...) without
 *         escapeHtml(...) is FLAGGED — that is what turns a stored/API
 *         string into an XSS vector.
 *     (c) Other HTML sinks — insertAdjacentHTML('pos', HTML) (2nd arg) and
 *         innerHTML/outerHTML whose RHS is a bare identifier or a local
 *         builder call. For bare identifiers the guard follows the nearest
 *         preceding const/let/var declaration (bounded by the enclosing
 *         function) and scans the HTML it builds — closing the blind spot
 *         where `rows` is built in a template literal and injected via
 *         insertAdjacentHTML or `el.innerHTML = rows`. Local builder
 *         functions (function nameHtml(...) {...}) have their bodies
 *         scanned too (no builder-following inside builder bodies).
 *     (d) textContent — a text-only sink (XSS-safe by construction), but
 *         assigning HTML MARKUP to it is an anti-pattern (tags render as
 *         literal text and signal text/HTML confusion that tends to get
 *         copy-pasted into innerHTML later). The guard flags RHS string
 *         literals containing real HTML tags (<b>, </div>…), while plain
 *         data (el.textContent = x.name) and comparison literals
 *         ('REPORTED < OBSERVED') stay clean.
 *
 *     Safe constructs accepted WITHOUT escapeHtml in concat operands:
 *       - escapeHtml(...) calls (removed before the check)
 *       - whitelisted number-only formatters (fmt.age/hashrate/uptime/
 *         secsToHuman/pct/usd/expectedBlock, acFormatTime, severityClass[...])
 *         — their ARGUMENTS are never interpolated (verified: each formatter
 *         coerces to a number/unit or renders a dash for non-finite input;
 *         none echoes its input back). fmt.diff()/fmt.shortAddr()/chunkAddr()
 *         DO echo raw substrings, so they are deliberately NOT whitelisted.
 *       - numeric coercion/output: .length, .toFixed(...), Number(...),
 *         Math.*
 *       - transform chains .map(...)/.join(...)/.filter(...)/.sort(...)/
 *         .reduce(...)/.forEach(...)/.concat(...) — a prop access chained
 *         into one of these is a data SOURCE (callback must escape its
 *         members, which the scanner checks independently), not a raw
 *         interpolation
 *       - string/number literals, ternary conditions are NOT interpolated
 *         (only the ternary ARMS are checked), bare pre-escaped identifiers
 *         (rows, items, list)
 *     Known limitation (documented tradeoff): concat operands that are map
 *     CALLBACK BLOCKS are truncated at the LAST `return` before scanning, so
 *     a setup statement BEFORE `return` that builds an unescaped fragment
 *     (const raw = '<td>' + x.msg;) is not scanned. This kills false
 *     positives from setup consts (const dlv = r.avg_delivery_pct != null
 *     ? Number(...).toFixed(1) + '%' : '—';) at the cost of that hole — the
 *     guidance is: keep every field interpolation inside the `return`
 *     expression (escaped) and never build HTML fragments in setup consts.
 *
 *     Declaration-following tradeoffs (heuristic, by design):
 *       - Arrow-callback scopes (list.forEach(x => { const rows = … })) are
 *         NOT boundaries for the backward search — a sibling-callback
 *         declaration may be followed (surface for false positives) and an
 *         enclosing-scope declaration is missed when the sink sits inside a
 *         nested NAMED function (surface for false negatives). Named
 *         `function NAME(` lines are the boundary.
 *       - `outerHTML` inline concat/TL is only scanned for bare-id/call RHS
 *         (no current usage — the legacy passes cover innerHTML inline).
 *       - `var`-hoisted declarations AFTER the sink are not seen.
 *
 * Usage:
 *   node scripts/check-dom-regression.js [--report]
 *
 *   --report  prints a 📊 DOM Guard Report (counts of TL interpolations,
 *             concat blocks, insertAdjacentHTML, bare-id/call innerHTML and
 *             textContent-markup scans) as a table + a grep-able JSON line
 *             `GUARD_REPORT {...}` for trend aggregation, plus a GitHub
 *             Actions ::notice:: annotation and a markdown block appended to
 *             GITHUB_STEP_SUMMARY when running in CI. Exit codes are
 *             UNCHANGED — the report never alters the merge gate.
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

// ── Guard 2: innerHTML escaping — template literals AND '+' concat ──────
const RE_TL = /\$\{([^}]*)\}/g;

// Expressions that are provably safe to interpolate into innerHTML:
//   - fmt.<SAFE>(...)    → whitelisted formatters that emit numbers/units
//                          ONLY (age, hashrate, uptime, secsToHuman, pct,
//                          usd, expectedBlock). fmt.diff() echoes raw input
//                          strings and fmt.shortAddr()/chunkAddr() return
//                          raw substrings — those MUST stay behind
//                          escapeHtml(...), so they are NOT whitelisted.
//   - acFormatTime(...)  → whitelisted local formatter
//   - acExecStatusClass()→ local CSS-class mapper (hardcoded class names)
//   - severityClass[...]  → local CSS-class map (values are hardcoded)
//   - bare identifiers    → pre-escaped HTML fragments (rows, parts) or
//                           counter/index variables
//   - numeric/string literals and simple arithmetic (i+1)
// Anything that READS A RECORD FIELD (e.block_height, a.category, m.tier)
// without escapeHtml() is flagged as external data.
const SAFE_FORMATTERS = /^(fmt\.(age|hashrate|uptime|secsToHuman|pct|usd|expectedBlock)\(|acFormatTime\(|acExecStatusClass\(|severityClass\[)/;
// Presence-check regex (matches a prop access anywhere). The CONCAT hunt
// uses RE_PROP_FULL below — one-char properties would break chain detection.
const RE_PROP_ACCESS = /[a-zA-Z_$][\w$]*\.[a-zA-Z_$]|\[[\s]*['"][^'"]+['"]\]/;

// ── Concat ('+') scanner ────────────────────────────────────────────────

// Methods whose result is a transformed/aggregated string BUILT from the
// members (callback must escape them — the scanner checks those separately).
// A prop access chained into one of these is a data source, not a raw
// interpolation. Methods that RETURN RAW DATA (slice, substring, replace…)
// are deliberately NOT here.
const TRANSFORM_METHODS = new Set([
  'map', 'join', 'filter', 'sort', 'reduce', 'forEach', 'concat', 'flatMap',
]);

// String-aware lexical state of a snippet: does it END inside an open
// template literal, and what is the paren depth OUTSIDE strings?
// Counting parens naively breaks on string literals that contain '(' / ')'
// (e.g. style="color:var(--text-muted)"), so quotes/templates are skipped.
function lexicalState(snippet) {
  let depth = 0, i = 0, q = null;
  while (i < snippet.length) {
    const c = snippet[i];
    if (q === "'" || q === '"') {
      if (c === q && snippet[i - 1] !== '\\') q = null;
      i++;
      continue;
    }
    if (q === '`') {
      if (c === '$' && snippet[i + 1] === '{') {
        // Consume ${...} (may contain quotes/parens).
        let bd = 1, k = i + 2;
        while (k < snippet.length && bd > 0) {
          if (snippet[k] === '{') bd++;
          else if (snippet[k] === '}') bd--;
          k++;
        }
        i = k;
        continue;
      }
      if (c === '`') q = null;
      i++;
      continue;
    }
    if (c === "'" || c === '"' || c === '`') { q = c; i++; continue; }
    if (c === '(' || c === '[') { depth++; i++; continue; }
    if (c === ')' || c === ']') { depth = Math.max(0, depth - 1); i++; continue; }
    i++;
  }
  return { templateOpen: q === '`', depth };
}

// Joins multi-line innerHTML assignment blocks: template literals spanning
// lines, continuation chains ('+' at EOL, map callbacks, ternaries) and
// unbalanced parens (ternary/function args spanning lines). String-aware so
// '(' inside string literals never triggers a runaway join. Hard-capped — no
// legit block spans more than 60 lines.
function joinInnerHtmlBlock(lines, start) {
  const MAX_BLOCK = 60;
  let joined = lines[start];
  let j = start;
  // Anchored at EOL: the last non-space char must be a continuation marker
  // (+ , ( [ = : ? { or a logical operator / arrow). Unanchored, an '='
  // anywhere in the line would falsely continue the join.
  // Lines are joined with '\n' so `//` comments stay line-scoped when the
  // scanners strip them.
  const eolContinues = () => /[\+(,\[=:?{]\s*$|(?:&&|\|\||=>)\s*$/.test(joined.trimEnd());
  while (j + 1 < lines.length && j - start < MAX_BLOCK) {
    const st = lexicalState(joined);
    if (!st.templateOpen && st.depth === 0 && !eolContinues()) break;
    joined += '\n' + lines[++j];
  }
  return { joined, end: j };
}

// Strips JS comments (// to EOL and /* … */) — they carry no runtime value,
// so a comment mentioning `ident.ident` must never produce a flag.
// String-aware: a `//` INSIDE a string literal (e.g. 'https://…') must not
// be treated as a comment — the strip would delete the closing quote and
// corrupt template/backtick counting on that line.
function stripComments(s) {
  let out = '', i = 0, q = null;
  while (i < s.length) {
    const c = s[i];
    if (q === "'" || q === '"') {
      out += c;
      if (c === q && s[i - 1] !== '\\') q = null;
      i++;
      continue;
    }
    if (q === '`') {
      if (c === '$' && s[i + 1] === '{') {
        let bd = 1, k = i + 2;
        while (k < s.length && bd > 0) {
          if (s[k] === '{') bd++;
          else if (s[k] === '}') bd--;
          k++;
        }
        out += s.slice(i, k);
        i = k;
        continue;
      }
      out += c;
      if (c === '`') q = null;
      i++;
      continue;
    }
    if (c === "'" || c === '"' || c === '`') { q = c; out += c; i++; continue; }
    if (c === '/' && s[i + 1] === '/') {
      while (i < s.length && s[i] !== '\n') i++;
      out += ' ';
      continue;
    }
    if (c === '/' && s[i + 1] === '*') {
      const end = s.indexOf('*/', i + 2);
      i = end === -1 ? s.length : end + 2;
      out += ' ';
      continue;
    }
    out += c;
    i++;
  }
  return out;
}

// Splits an RHS expression on '+' at paren/bracket depth 0, outside string
// and template literals. `+` at deeper levels (map callbacks, ternaries)
// stays inside the operand and is checked by the prop-access hunt.
function splitConcatOperands(rhs) {
  const ops = [];
  let depth = 0, cur = '', i = 0, q = null;
  while (i < rhs.length) {
    const c = rhs[i];
    if (q === "'" || q === '"') {
      cur += c;
      if (c === q && rhs[i - 1] !== '\\') q = null;
      i++;
      continue;
    }
    if (q === '`') {
      if (c === '$' && rhs[i + 1] === '{') {
        // Consume ${...} inside the template literal (may contain quotes).
        let bd = 1, k = i + 2;
        while (k < rhs.length && bd > 0) {
          if (rhs[k] === '{') bd++;
          else if (rhs[k] === '}') bd--;
          k++;
        }
        cur += rhs.slice(i, k);
        i = k;
        continue;
      }
      cur += c;
      if (c === '`') q = null;
      i++;
      continue;
    }
    if (c === "'" || c === '"' || c === '`') { q = c; cur += c; i++; continue; }
    if (c === '(' || c === '[') { depth++; cur += c; i++; continue; }
    if (c === ')' || c === ']') { depth = Math.max(0, depth - 1); cur += c; i++; continue; }
    if (c === '+' && depth === 0) { ops.push(cur); cur = ''; i++; continue; }
    cur += c;
    i++;
  }
  ops.push(cur);
  return ops;
}

// True if the RHS uses '+' at any depth outside string/template literals.
// Gates the concat scanner (pure literals / template literals / direct
// assignments are handled elsewhere or need no scanning).
function hasConcatOperator(rhs) {
  let depth = 0, i = 0, q = null;
  while (i < rhs.length) {
    const c = rhs[i];
    if (q === "'" || q === '"') {
      if (c === q && rhs[i - 1] !== '\\') q = null;
      i++;
      continue;
    }
    if (q === '`') {
      if (c === '$' && rhs[i + 1] === '{') {
        let bd = 1, k = i + 2;
        while (k < rhs.length && bd > 0) {
          if (rhs[k] === '{') bd++;
          else if (rhs[k] === '}') bd--;
          k++;
        }
        i = k;
        continue;
      }
      if (c === '`') q = null;
      i++;
      continue;
    }
    if (c === "'" || c === '"' || c === '`') { q = c; i++; continue; }
    if (c === '(' || c === '[') { depth++; i++; continue; }
    if (c === ')' || c === ']') { depth = Math.max(0, depth - 1); i++; continue; }
    if (c === '+') return true;
    i++;
  }
  return false;
}

// Removes provably-safe sub-expressions so the remaining prop accesses are
// real interpolations. The .toFixed()/Number()/Math./.length forms are
// numeric output — the whole coercion chain (including its base field) is
// removed, not just the call.
function stripSafeConcatSubexprs(op) {
  return op
    .replace(/escapeHtml\([^)]*\)/g, '')                    // explicitly escaped
    .replace(/acExecStatusClass\([^)]*\)/g, '')              // local CSS-class mapper
    .replace(/docsHighlight\([^)]*\)/g, '')                  // doc search — escapes internally
    .replace(/\bfmt\.(?:age|hashrate|uptime|secsToHuman|pct|usd|expectedBlock)\([^)]*\)/g, '') // whitelisted number-only formatters
    .replace(/acFormatTime\([^)]*\)/g, '')                   // whitelisted local formatter
    .replace(/severityClass\[[^\]]*\]/g, '')                // local CSS-class map lookup
    .replace(/[a-zA-Z_$][\w$]*(?:\.[a-zA-Z_$][\w$]*)*\.toFixed\([^)]*\)/g, '') // numeric format
    .replace(/Number\([^)]*\)/g, '')                         // numeric coercion
    .replace(/Math\.[a-zA-Z_$][\w$]*/g, '')                  // numeric global
    .replace(/\.length\b/g, '')                              // always a number
    .replace(/\?\./g, '.')                                   // optional chaining → plain access
    // String literals — quote-aware so a literal containing the OTHER quote
    // type ('<a href="https://…">') is fully removed. Naive ['"][^'"]*['"]
    // would stop at the inner quote and leave a fragment like
    // https://example.com — which then looks like a prop access.
    .replace(/'(?:[^'\\]|\\.)*'|"(?:[^"\\]|\\.)*"/g, '');
}

// Replaces template literals (`` `...` `` incl. balanced `${...}`) with the
// marker 'TL' — the TL scanner already checks ${...} interpolations, so the
// concat scanner must not double-flag their content.
function stripTemplateLiterals(s) {
  let out = '', i = 0;
  while (i < s.length) {
    const idx = s.indexOf('`', i);
    if (idx === -1) { out += s.slice(i); break; }
    out += s.slice(i, idx);
    // Find the closing backtick (brace-aware for ${...}).
    let j = idx + 1;
    while (j < s.length) {
      if (s[j] === '`') break;
      if (s[j] === '$' && s[j + 1] === '{') {
        let bd = 1, k = j + 2;
        while (k < s.length && bd > 0) {
          if (s[k] === '{') bd++;
          else if (s[k] === '}') bd--;
          k++;
        }
        j = k;
        continue;
      }
      j++;
    }
    out += 'TL';
    i = j < s.length ? j + 1 : s.length;
  }
  return out;
}

// True when the prop-access match is a data SOURCE chained into a transform
// method (map/join/filter/...). Walks the method chain from the match: if
// ANY called method in the chain is a transform, the base feeds a
// transformation whose callback is checked separately — safe. If the chain
// ends without a transform, the value IS interpolated raw (slice/substring/
// a bare read...) — unsafe.
function isTransformSource(text, m) {
  let i = m.index + m.len;
  const names = [];
  if (text[i] === '(') names.push(m.lastProp); // A.b(...) — b is the call
  let ownCallPending = text[i] === '(';
  while (true) {
    while (i < text.length && /\s/.test(text[i])) i++;
    const c = text[i];
    if (c === '.') {
      const mm = text.slice(i + 1).match(/^([a-zA-Z_$][\w$]*)\s*\(/);
      if (!mm) return false; // dangling '.' — not a clean chain
      names.push(mm[1]);
      i += 1 + mm[0].length; // skip `.name(`
      let d = 1;
      while (i < text.length && d > 0) {
        if (text[i] === '(') d++;
        else if (text[i] === ')') d--;
        i++;
      }
      continue;
    }
    if (c === '(' && ownCallPending) {
      ownCallPending = false;
      let d = 1;
      i++; // past '('
      while (i < text.length && d > 0) {
        if (text[i] === '(') d++;
        else if (text[i] === ')') d--;
        i++;
      }
      continue;
    }
    // Fallback bridge: `ident || <expr>)` feeding a method chain — e.g.
    // (c.providers || []).map(p => …). The `||` guards an empty source;
    // the transform still applies to the read, so this is a data SOURCE.
    if (c === '|' && text[i + 1] === '|') {
      let d = 0, k = i + 2, q = null;
      while (k < text.length) {
        const cc = text[k];
        if (q === "'" || q === '"') {
          if (cc === q && text[k - 1] !== '\\') q = null;
          k++;
          continue;
        }
        if (cc === "'" || cc === '"') { q = cc; k++; continue; }
        if (cc === '(' || cc === '[') d++;
        else if (cc === ')' || cc === ']') { if (d === 0) break; d--; }
        k++;
      }
      i = k + 1; // skip past the closing ')'
      continue;
    }
    break;
  }
  return names.some(n => TRANSFORM_METHODS.has(n));
}

// Returns the first prop-access read that is NOT in a safe context, or null.
// Safe contexts: chained into a transform method (data SOURCE) or a TERNARY
// CONDITION (a read, not an interpolated value — only the arms interpolate).
function findUnsafePropRead(stripped) {
  const re = /[a-zA-Z_$][\w$]*\.[a-zA-Z_$][\w$]*|\[[\s]*['"][^'"]+['"]\]/g;
  let m, cursor = 0, depth = 0;
  while ((m = re.exec(stripped)) !== null) {
    depth = advanceDepth(stripped.slice(cursor, m.index), depth);
    cursor = m.index + m[0].length;
    const after = stripped.slice(cursor);
    // Whitelisted formatter CALL at this position (fmt.age(…), acFormatTime,
    // acExecStatusClass, severityClass[…]) → emits numbers/units/classes.
    if (SAFE_FORMATTERS.test(stripped.slice(m.index))) continue;
    // Lookup KEY read ({…}[row.method]) → the emitted value comes from the
    // container (a literal map), not from the key itself.
    if (/^\s*\]/.test(after)) continue;
    const match = {
      index: m.index,
      len: m[0].length,
      lastProp: m[0].split('.').pop().replace(/\[.*$/, ''),
    };
    // Data SOURCE chained into a transform (map/join/filter/...) → the
    // callback members are checked separately.
    if (isTransformSource(stripped, match)) continue;
    // Ternary CONDITION → a read, not an interpolated value.
    if (isTernaryCondition(stripped, cursor, depth)) continue;
    // Everything else: raw external field interpolated into innerHTML.
    return m[0];
  }
  return null;
}

// Advances `depth` by scanning plain text (parens outside strings). Used to
// keep track of the paren depth at each prop-access match position.
function advanceDepth(text, depth) {
  let d = depth, i = 0, q = null;
  while (i < text.length) {
    const c = text[i];
    if (q === "'" || q === '"') {
      if (c === q && text[i - 1] !== '\\') q = null;
      i++;
      continue;
    }
    if (c === "'" || c === '"') { q = c; i++; continue; }
    if (c === '(' || c === '[') { d++; i++; continue; }
    if (c === ')' || c === ']') { d = Math.max(0, d - 1); i++; continue; }
    i++;
  }
  return d;
}

// True when the text starting at `from` (at paren `baseDepth`) is part of a
// ternary CONDITION — i.e. a '?' (ternary, not '??') appears at the same
// depth before any value terminator (`+ , ; : ) ] }`). Comparison and logical
// operators, literals and further identifiers may appear in between (a
// condition like `d.pl_sats >= 0 ? '+' : ''` reads the field but never
// interpolates it).
function isTernaryCondition(text, from, baseDepth) {
  let d = baseDepth, i = from, q = null;
  while (i < text.length) {
    const c = text[i];
    if (q === "'" || q === '"') {
      if (c === q && text[i - 1] !== '\\') q = null;
      i++;
      continue;
    }
    if (c === "'" || c === '"') { q = c; i++; continue; }
    if (c === '(' || c === '[') { d++; i++; continue; }
    if (c === ')' || c === ']') { d = Math.max(0, d - 1); i++; continue; }
    if (d <= baseDepth) {
      // Value terminator at (or shallower than) the match depth → the read
      // is interpolated. Note: ':' ends an arm, and '?' (ternary, not '??')
      // at any depth ≤ baseDepth means this read feeds a condition.
      if (c === '+' || c === ',' || c === ';' || c === ':' || c === '}') return false;
      if (c === '?') return text[i + 1] !== '?'; // '??' interpolates the left side
    }
    i++;
  }
  return false;
}

// Find the index of a top-level '?' (ternary condition start) — depth 0,
// outside string/template literals. Returns -1 if none.
function findTopLevelQuestion(text) {
  let depth = 0, i = 0, q = null;
  while (i < text.length) {
    const c = text[i];
    if (q === "'" || q === '"') {
      if (c === q && text[i - 1] !== '\\') q = null;
      i++;
      continue;
    }
    if (q === '`') {
      if (c === '$' && text[i + 1] === '{') {
        let bd = 1, k = i + 2;
        while (k < text.length && bd > 0) {
          if (text[k] === '{') bd++;
          else if (text[k] === '}') bd--;
          k++;
        }
        i = k;
        continue;
      }
      if (c === '`') q = null;
      i++;
      continue;
    }
    if (c === "'" || c === '"' || c === '`') { q = c; i++; continue; }
    if (c === '(' || c === '[') { depth++; i++; continue; }
    if (c === ')' || c === ']') { depth = Math.max(0, depth - 1); i++; continue; }
    if (c === '?' && depth === 0) return i;
    i++;
  }
  return -1;
}

// Find the ':' matching the top-level '?' at `qIdx` (same depth, outside
// strings). Returns -1 if the ternary never closes (e.g. it is a `??` or
// optional-chain `?.` which we treat conservatively — full operand check).
function findMatchingColon(text, qIdx) {
  let depth = 0, i = qIdx + 1, q = null;
  while (i < text.length) {
    const c = text[i];
    if (q === "'" || q === '"') {
      if (c === q && text[i - 1] !== '\\') q = null;
      i++;
      continue;
    }
    if (q === '`') {
      if (c === '$' && text[i + 1] === '{') {
        let bd = 1, k = i + 2;
        while (k < text.length && bd > 0) {
          if (text[k] === '{') bd++;
          else if (text[k] === '}') bd--;
          k++;
        }
        i = k;
        continue;
      }
      if (c === '`') q = null;
      i++;
      continue;
    }
    if (c === "'" || c === '"' || c === '`') { q = c; i++; continue; }
    if (c === '(' || c === '[') { depth++; i++; continue; }
    if (c === ')' || c === ']') { depth = Math.max(0, depth - 1); i++; continue; }
    if (c === ':' && depth === 0) return i;
    i++;
  }
  return -1;
}

function matchingCloseParen(text) {
  let depth = 0, i = 0, q = null;
  while (i < text.length) {
    const c = text[i];
    if (q === "'" || q === '"') {
      if (c === q && text[i - 1] !== '\\') q = null;
      i++;
      continue;
    }
    if (q === '`') {
      if (c === '$' && text[i + 1] === '{') {
        let bd = 1, k = i + 2;
        while (k < text.length && bd > 0) {
          if (text[k] === '{') bd++;
          else if (text[k] === '}') bd--;
          k++;
        }
        i = k;
        continue;
      }
      if (c === '`') q = null;
      i++;
      continue;
    }
    if (c === "'" || c === '"' || c === '`') { q = c; i++; continue; }
    if (c === '(' || c === '[') { depth++; i++; continue; }
    if (c === ')' || c === ']') {
      if (depth === 0) return i;
      depth--;
      i++;
      continue;
    }
    i++;
  }
  return -1;
}

// Unified value-safety check used by BOTH scanners (template-literal
// interpolations and '+' concat operands). Returns the first unsafe
// record-field read (or null when safe):
//   - unwrap outer parens
//   - ternaries: the CONDITION is a read, never interpolated — check only
//     the arms (recursively)
//   - an expression that IS a single escapeHtml(...) call / whitelisted
//     formatter / literal / bare identifier / simple arithmetic → safe
//   - otherwise strip numeric/literal/escaped sub-expressions and hunt raw
//     record-field reads (transform sources + ternary conditions safe)
function firstUnsafeInValue(expr) {
  let e = expr.trim();
  if (!e) return null;
  // Unwrap outer parens (e.g. (entry.worker || ''), (s.done ? … : …)).
  while (e.startsWith('(')) {
    const close = matchingCloseParen(e);
    if (close !== e.length - 1) break;
    e = e.slice(1, -1).trim();
    if (!e) return null;
  }
  // Ternary: conditions are reads — check the ARMS only.
  const qIdx = findTopLevelQuestion(e);
  if (qIdx !== -1) {
    const colonIdx = findMatchingColon(e, qIdx);
    if (colonIdx !== -1) {
      return firstUnsafeInValue(e.slice(qIdx + 1, colonIdx))
        || firstUnsafeInValue(e.slice(colonIdx + 1));
    }
  }
  // The whole expression IS one escapeHtml(...) call → escaped.
  // (An expression that merely CONTAINS escapeHtml mixed with other fields
  // falls through to the strip+hunt below so nothing is masked.)
  if (/^escapeHtml\([^)]*\)$/.test(e)) return null;
  // Whitelisted formatter call or local map lookup.
  if (SAFE_FORMATTERS.test(e)) return null;
  // Numeric literal / string literal / simple arithmetic / bare id.
  if (/^[0-9]/.test(e) && !RE_PROP_ACCESS.test(e)) return null;
  if (/^['"]/.test(e) && !RE_PROP_ACCESS.test(e)) return null;
  if (!RE_PROP_ACCESS.test(e) && /^[a-zA-Z_$][\w$]*([\s]*[+\-]\s*[\w$()'"0-9]+)*$/.test(e)) return null;
  // Strip numeric/literal/escaped sub-expressions, then hunt unsafe reads.
  const stripped = stripSafeConcatSubexprs(e);
  return findUnsafePropRead(stripped);
}

function isSafeValue(expr) {
  return firstUnsafeInValue(expr) === null;
}

// Check one concat operand (ternary conditions handled in firstUnsafeInValue).
// Map callbacks frequently declare setup consts (`const x = r.field; …`)
// before `return …` — those reads are consumed by later code (often escaped
// at use), so scanning them as interpolations creates false positives.
// Truncate the operand at its last `return` (string-aware) and scan only the
// return expression.
function truncateAtReturn(s) {
  let last = -1, i = 0, q = null;
  while (i < s.length) {
    const c = s[i];
    if (q === "'" || q === '"') {
      if (c === q && s[i - 1] !== '\\') q = null;
      i++;
      continue;
    }
    if (q === '`') {
      if (c === '$' && s[i + 1] === '{') {
        let bd = 1, k = i + 2;
        while (k < s.length && bd > 0) {
          if (s[k] === '{') bd++;
          else if (s[k] === '}') bd--;
          k++;
        }
        i = k;
        continue;
      }
      if (c === '`') q = null;
      i++;
      continue;
    }
    if (c === "'" || c === '"' || c === '`') { q = c; i++; continue; }
    if (/[a-zA-Z_$]/.test(c) && /^return\b/.test(s.slice(i))) {
      last = i + 6;
    }
    i++;
  }
  return last === -1 ? s : s.slice(last);
}

function checkConcatOperand(op, line, flags) {
  const text = truncateAtReturn(stripTemplateLiterals(op)).trim();
  if (!text) return true;
  const bad = firstUnsafeInValue(text);
  if (bad) {
    flags.push({ line, expr: op.trim().slice(0, 80), field: bad });
    return false;
  }
  return true;
}

function checkConcatEscaping() {
  const text = fs.readFileSync(APP_JS, 'utf-8');
  const lines = text.split('\n');
  const flags = [];
  let concatCount = 0;

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    if (!/innerHTML\s*(\+=|=)/.test(line)) continue;
    const { joined, end } = joinInnerHtmlBlock(lines, i);
    const after = stripComments(joined.slice(joined.indexOf('innerHTML')));
    const rhs = after.replace(/^innerHTML\s*(\+=|=)\s*/, '');
    if (!hasConcatOperator(rhs)) continue;
    concatCount++;
    const operands = splitConcatOperands(rhs);
    for (const op of operands) {
      checkConcatOperand(op, i + 1, flags);
    }
    i = end; // skip already-joined lines
  }

  if (flags.length) {
    console.log('  ❌ GUARD 2 — unescaped innerHTML concatenation operand(s):');
    for (const f of flags) {
      console.log(`     app.js:${f.line}  + ${f.expr}`);
      console.log(`       → '${f.field}' is external data — wrap in escapeHtml(...)`);
    }
    return { ok: false, concat: concatCount }; // counts on FAIL too — the report needs them
  }
  console.log('  ✅ GUARD 2 — all ' + concatCount + ' innerHTML concat block(s) escaped or literal-safe.');
  return { ok: true, concat: concatCount };
}

function checkInnerHtmlEscaping() {
  const text = fs.readFileSync(APP_JS, 'utf-8');
  const lines = text.split('\n');
  const flags = [];
  let tlCount = 0;

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    if (!/innerHTML\s*(\+=|=)/.test(line)) continue;
    const { joined, end } = joinInnerHtmlBlock(lines, i);
    const after = stripComments(joined.slice(joined.indexOf('innerHTML')));
    tlCount += (after.match(/`/g) || []).length;
    const local = new RegExp(RE_TL.source, 'g');
    let m;
    while ((m = local.exec(after)) !== null) {
      const expr = m[1];
      if (!isSafeValue(expr)) {
        flags.push({ line: i + 1, expr: expr.slice(0, 80) });
      }
    }
    i = end; // skip already-joined lines
  }

  if (flags.length) {
    console.log('  ❌ GUARD 2 — unescaped innerHTML interpolation(s):');
    for (const f of flags) {
      console.log(`     app.js:${f.line}  \${${f.expr}}`);
      console.log('       → wrap in escapeHtml(...) or make it a literal');
    }
    return { ok: false, tl: tlCount }; // counts on FAIL too — the report needs them
  }
  console.log('  ✅ GUARD 2 — all ' + tlCount + ' innerHTML template-literal interpolations escaped or literal-safe.');
  return { ok: true, tl: tlCount };
}

// ── Extended sinks: insertAdjacentHTML + bare-id innerHTML + textContent ─

// Local functions / globals that never return HTML (escaping helpers,
// DOM/format globals, etc.) — never follow them as HTML builders.
const SAFE_CALL_NAMES = new Set([
  'escapeHtml', 'acFormatTime', 'acExecStatusClass', 'docsHighlight',
  'severityClass',
  'document', 'window', 'JSON', 'Object', 'Array', 'String', 'Number',
  'Math', 'Date', 'Boolean', 'Symbol', 'RegExp', 'Promise', 'fetch',
  'encodeURIComponent', 'decodeURIComponent', 'parseInt', 'parseFloat',
  'isNaN', 'isFinite', 'localStorage', 'sessionStorage', 'setTimeout',
  'setInterval', 'clearTimeout', 'set',
]);

function isKnownSafeCall(name) {
  return SAFE_CALL_NAMES.has(name) || /^fmt\./.test(name);
}

// Extracts the SECOND argument (the HTML string) of an insertAdjacentHTML
// call: skip the position string, capture up to the call's closing paren.
// Joined text has comments already stripped. String/template-aware.
function insertAdjacentHtmlArg(joined) {
  const m = joined.match(/insertAdjacentHTML\s*\(/);
  if (!m) return null;
  let depth = 0, q = null, argStart = -1, j = m.index + m[0].length;
  while (j < joined.length) {
    const c = joined[j];
    if (q === "'" || q === '"') {
      if (c === q && joined[j - 1] !== '\\') q = null;
      j++;
      continue;
    }
    if (q === '`') {
      if (c === '$' && joined[j + 1] === '{') {
        let bd = 1, k = j + 2;
        while (k < joined.length && bd > 0) {
          if (joined[k] === '{') bd++;
          else if (joined[k] === '}') bd--;
          k++;
        }
        j = k;
        continue;
      }
      if (c === '`') q = null;
      j++;
      continue;
    }
    if (c === "'" || c === '"' || c === '`') { q = c; j++; continue; }
    if (c === '(' || c === '[') { depth++; j++; continue; }
    if (c === ')' || c === ']') {
      if (depth === 0 && argStart !== -1) return joined.slice(argStart, j).trim();
      depth = Math.max(0, depth - 1);
      j++;
      continue;
    }
    if (c === ',' && depth === 0) { argStart = j + 1; j++; continue; }
    j++;
  }
  return null;
}

// Follows a bare identifier to its nearest preceding declaration
// (const/let/var NAME = …). The backward search is bounded by the nearest
// preceding `function NAME(` line so a declaration in a SIBLING function is
// never picked up — variable names (rows, line, list…) are reused across
// the file. Returns { rhs, line } or null.
function findDeclaredRhs(name, ctx, effLine) {
  // Built from char codes so NO backslash lives in this source line — the
  // pattern is (?:const|let|var) + \s + name + \s* = (string-built regexes
  // with literal backslashes get mangled by some editors' escaping layers).
  const BS = String.fromCharCode(92);
  const re = new RegExp('(?:const|let|var)' + BS + 's+' + name + BS + 's*=');
  const startIdx = Math.max(0, effLine - 1);
  let boundary = -1;
  for (let i = startIdx; i >= 0 && startIdx - i < 500; i--) {
    if (i < startIdx && /^\s*function\s+[a-zA-Z_$]/.test(ctx.lines[i])) { boundary = i; break; }
  }
  for (let i = startIdx; i > boundary; i--) {
    const ln = ctx.lines[i];
    if (/^\s*\/\//.test(ln) || /^\s*\*/.test(ln)) continue; // comment lines
    if (!re.test(ln)) continue;
    const { joined } = joinInnerHtmlBlock(ctx.lines, i);
    const eq = joined.indexOf('=');
    if (eq === -1) continue;
    const rhs = joined.slice(eq + 1).replace(/;\s*$/, '').trim();
    if (!rhs) continue;
    return { rhs, line: i + 1 };
  }
  return null;
}

// Finds `function NAME(...) { … }` anywhere in the file (hoisting) and
// returns the joined body text plus its first line. Brace-aware and
// string/template-aware.
function findBuilderBody(name, ctx) {
  // Same fromCharCode trick as findDeclaredRhs: pattern is
  // 'function' + \s + name + \s* + \( (no raw backslashes in source).
  const BS = String.fromCharCode(92);
  const re = new RegExp('function' + BS + 's+' + name + BS + 's*' + BS + '(');
  for (let i = 0; i < ctx.lines.length; i++) {
    if (!re.test(ctx.lines[i])) continue;
    let j = i, braceIdx = ctx.lines[i].indexOf('{');
    while (braceIdx === -1 && j + 1 < ctx.lines.length) braceIdx = ctx.lines[++j].indexOf('{');
    if (braceIdx === -1) continue;
    let depth = 0, k = braceIdx, q = null, lineIdx = j;
    while (lineIdx < ctx.lines.length) {
      const s = ctx.lines[lineIdx];
      while (k < s.length) {
        const c = s[k];
        if (q === "'" || q === '"') {
          if (c === q && s[k - 1] !== '\\') q = null;
          k++;
          continue;
        }
        if (q === '`') {
          if (c === '$' && s[k + 1] === '{') {
            let bd = 1, kk = k + 2;
            while (kk < s.length && bd > 0) {
              if (s[kk] === '{') bd++;
              else if (s[kk] === '}') bd--;
              kk++;
            }
            k = kk;
            continue;
          }
          if (c === '`') q = null;
          k++;
          continue;
        }
        if (c === "'" || c === '"' || c === '`') { q = c; k++; continue; }
        if (c === '{') { depth++; k++; continue; }
        if (c === '}') {
          depth--;
          if (depth === 0) return { body: ctx.lines.slice(j, lineIdx + 1).join('\n'), line: i + 1 };
          k++;
          continue;
        }
        k++;
      }
      k = 0;
      lineIdx++;
    }
  }
  return null;
}

// Splits a small JS body into top-level statements on ';' at depth 0.
function splitStatements(body) {
  const out = [];
  let depth = 0, cur = '', i = 0, q = null;
  while (i < body.length) {
    const c = body[i];
    if (q === "'" || q === '"') {
      cur += c;
      if (c === q && body[i - 1] !== '\\') q = null;
      i++;
      continue;
    }
    if (q === '`') {
      if (c === '$' && body[i + 1] === '{') {
        let bd = 1, k = i + 2;
        while (k < body.length && bd > 0) {
          if (body[k] === '{') bd++;
          else if (body[k] === '}') bd--;
          k++;
        }
        cur += body.slice(i, k);
        i = k;
        continue;
      }
      cur += c;
      if (c === '`') q = null;
      i++;
      continue;
    }
    if (c === "'" || c === '"' || c === '`') { q = c; cur += c; i++; continue; }
    if (c === '(' || c === '[' || c === '{') { depth++; cur += c; i++; continue; }
    if (c === ')' || c === ']' || c === '}') { depth = Math.max(0, depth - 1); cur += c; i++; continue; }
    if (c === ';' && depth === 0) { out.push(cur); cur = ''; i++; continue; }
    cur += c;
    i++;
  }
  if (cur.trim()) out.push(cur);
  return out;
}

// RHS of `const x = <rhs>;` / `return <rhs>;` statements — or null.
function statementRhs(stmt) {
  const t = stmt.trim();
  const ret = t.match(/^return\b\s*/);
  if (ret) return t.slice(ret[0].length).replace(/;\s*$/, '').trim();
  const decl = t.match(/^(?:const|let|var)\s+[a-zA-Z_$][\w$]*\s*=/);
  if (decl) return t.slice(decl[0].length).replace(/;\s*$/, '').trim();
  return null;
}

// Returns the first real HTML tag found inside the STRING LITERALS of an
// RHS, or null. Only literal text counts — comparisons like `a < b` or
// 'REPORTED < OBSERVED' (no tag shape) never match.
function findHtmlTagsInLiterals(rhs) {
  let i = 0, q = null, lit = '';
  const RE_TAG = /<\/?[a-zA-Z][a-zA-Z0-9-]*(\s+[^>]*)?\/?>/;
  const check = () => (RE_TAG.test(lit) ? (RE_TAG.exec(lit) || [''])[0] : null);
  while (i < rhs.length) {
    const c = rhs[i];
    if (q === "'" || q === '"') {
      if (c === q && rhs[i - 1] !== '\\') {
        q = null;
        const hit = check();
        if (hit) return hit; // tag found inside this closed literal
      } else lit += c;
      i++;
      continue;
    }
    if (q === '`') {
      if (c === '$' && rhs[i + 1] === '{') {
        let bd = 1, k = i + 2;
        while (k < rhs.length && bd > 0) {
          if (rhs[k] === '{') bd++;
          else if (rhs[k] === '}') bd--;
          k++;
        }
        lit += ' '; // interpolation content is not literal text
        i = k;
        continue;
      }
      if (c === '`') {
        q = null;
        const hit = check();
        if (hit) return hit;
      } else lit += c;
      i++;
      continue;
    }
    if (c === "'" || c === '"' || c === '`') { q = c; i++; continue; }
    if (c === ';' || c === '\n') lit = ''; // statement boundary
    i++;
  }
  return check();
}

// Deduplicated flag push (same line+expr+field across sink passes).
const _flagKeys = new Set();
function pushFlag(flags, f) {
  const key = f.line + ':' + f.expr + ':' + f.field;
  if (_flagKeys.has(key)) return;
  _flagKeys.add(key);
  flags.push(f);
}

// Scans a BUILDER FUNCTION BODY (multi-statement): template-literal
// interpolations anywhere + '+' concat inside each const/return statement's
// RHS. Builders are scanned without further builder-following (depth cap).
function scanHtmlBuilderBody(body, flags, ctx, effLine) {
  let ok = true;
  const local = new RegExp(RE_TL.source, 'g');
  let m;
  while ((m = local.exec(body)) !== null) {
    if (!isSafeValue(m[1])) {
      pushFlag(flags, { line: effLine, expr: m[1].slice(0, 80), field: m[1].slice(0, 40), sink: 'template-literal' });
      ok = false;
    }
  }
  for (const stmt of splitStatements(body)) {
    const rhs = statementRhs(stmt);
    if (!rhs || !hasConcatOperator(rhs)) continue;
    for (const op of splitConcatOperands(rhs)) {
      const opT = op.trim();
      if (!opT) continue;
      const bad = firstUnsafeInValue(truncateAtReturn(stripTemplateLiterals(opT)));
      if (bad) {
        pushFlag(flags, { line: effLine, expr: opT.slice(0, 80), field: bad, sink: 'concat' });
        ok = false;
      }
    }
  }
  return ok;
}

// Scans one HTML-string expression for unescaped external data, resolving
// bare identifiers to their declarations and local builder calls to their
// bodies (single hop, capped by ctx.visited). Returns true when safe.
// `effLine` is the source line to report findings on.
function scanHtmlExpr(expr, flags, ctx, effLine) {
  const t = expr.trim();
  if (!t) return true;
  let ok = true;

  // 1. Bare identifier → follow its declaration.
  if (/^[a-zA-Z_$][\w$]*$/.test(t)) {
    if (ctx.visited.has(t)) return true;
    ctx.visited.add(t);
    const decl = findDeclaredRhs(t, ctx, effLine);
    if (decl) return scanHtmlExpr(decl.rhs, flags, ctx, decl.line);
    return true; // unresolved bare id = pre-escaped fragment (documented)
  }

  // 2. Local builder call → scan the function body.
  const callM = t.match(/^([a-zA-Z_$][\w$]*)\s*\(/);
  if (callM && !isKnownSafeCall(callM[1]) && !ctx.visited.has(callM[1])) {
    ctx.visited.add(callM[1]);
    const fn = findBuilderBody(callM[1], ctx);
    if (fn) return scanHtmlBuilderBody(fn.body, flags, ctx, fn.line);
  }

  // 3. Inline scan: template-literal interpolations.
  const local = new RegExp(RE_TL.source, 'g');
  let m;
  while ((m = local.exec(t)) !== null) {
    if (!isSafeValue(m[1])) {
      pushFlag(flags, { line: effLine, expr: m[1].slice(0, 80), field: m[1].slice(0, 40), sink: 'template-literal' });
      ok = false;
    }
  }

  // 4. Inline scan: '+' concat operands (following bare-id / builder ops).
  if (hasConcatOperator(t)) {
    for (const op of splitConcatOperands(t)) {
      const opT = op.trim();
      if (!opT) continue;
      if (/^[a-zA-Z_$][\w$]*$/.test(opT)) {
        if (!ctx.visited.has(opT)) {
          ctx.visited.add(opT);
          const decl = findDeclaredRhs(opT, ctx, effLine);
          if (decl) { ok = scanHtmlExpr(decl.rhs, flags, ctx, decl.line) && ok; continue; }
        }
        continue; // bare id in concat — already visited / unresolved
      }
      const opCall = opT.match(/^([a-zA-Z_$][\w$]*)\s*\(/);
      if (opCall && !isKnownSafeCall(opCall[1]) && !ctx.visited.has(opCall[1])) {
        ctx.visited.add(opCall[1]);
        const fn = findBuilderBody(opCall[1], ctx);
        if (fn) { ok = scanHtmlBuilderBody(fn.body, flags, ctx, fn.line) && ok; continue; }
      }
      const bad = firstUnsafeInValue(truncateAtReturn(stripTemplateLiterals(opT)));
      if (bad) {
        pushFlag(flags, { line: effLine, expr: opT.slice(0, 80), field: bad, sink: 'concat' });
        ok = false;
      }
    }
  }
  return ok;
}

function checkHtmlSinkExtension() {
  const text = fs.readFileSync(APP_JS, 'utf-8');
  const lines = text.split('\n');
  const ctx = { lines, visited: new Set() };
  const flags = [];
  let adjCount = 0, bareCount = 0, tcCount = 0;

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];

    // ── insertAdjacentHTML('pos', HTML) ──
    if (/insertAdjacentHTML\s*\(/.test(line)) {
      const { joined, end } = joinInnerHtmlBlock(lines, i);
      const arg = insertAdjacentHtmlArg(stripComments(joined));
      if (arg) {
        adjCount++;
        scanHtmlExpr(arg, flags, ctx, i + 1);
      }
      i = end;
      continue;
    }

    // ── innerHTML / outerHTML with a bare-id or local-call RHS, or
    //    bare-id operands inside a concat chain (the `rows` blind spot) ──
    const kwM = line.match(/(?:innerHTML|outerHTML)\s*(\+=|=)/);
    if (kwM) {
      const kw = kwM[0].indexOf('outerHTML') !== -1 ? 'outerHTML' : 'innerHTML';
      const { joined, end } = joinInnerHtmlBlock(lines, i);
      const after = stripComments(joined.slice(joined.indexOf(kw)));
      const BS = String.fromCharCode(92);
      const rhs = after
        .replace(new RegExp('^' + kw + BS + 's*(\\+=|=)' + BS + 's*'), '')
        .replace(/;[\s]*$/, '').trim(); // drop trailing ';' so bare-id RHS still matches
      const t = rhs;
      if (/^[a-zA-Z_$][\w$]*$/.test(t) || /^[a-zA-Z_$][\w$]*\s*\(/.test(t)) {
        bareCount++;
        scanHtmlExpr(rhs, flags, ctx, i + 1);
      } else if (hasConcatOperator(rhs)) {
        for (const op of splitConcatOperands(rhs)) {
          const opT = op.trim();
          if (/^[a-zA-Z_$][\w$]*$/.test(opT) && !ctx.visited.has(opT)) {
            ctx.visited.add(opT);
            const decl = findDeclaredRhs(opT, ctx, i + 1);
            if (decl) {
              bareCount++;
              scanHtmlExpr(decl.rhs, flags, ctx, decl.line);
            }
          }
        }
      }
      i = end;
      continue;
    }

    // ── textContent: HTML markup anti-pattern ──
    if (/textContent\s*(\+=|=)/.test(line)) {
      const { joined, end } = joinInnerHtmlBlock(lines, i);
      const after = stripComments(joined.slice(joined.indexOf('textContent')));
      const rhs = after.replace(/^textContent\s*(\+=|=)\s*/, '');
      const tag = findHtmlTagsInLiterals(rhs);
      if (tag) {
        tcCount++;
        pushFlag(flags, { line: i + 1, expr: rhs.trim().slice(0, 80), field: tag, sink: 'textContent-markup' });
      }
      i = end;
      continue;
    }
  }

  if (flags.length) {
    console.log('  ❌ GUARD 2 — unescaped data in other DOM sinks (insertAdjacentHTML / bare-id innerHTML / textContent):');
    for (const f of flags) {
      const label = f.sink === 'textContent-markup' ? 'textContent' : (f.sink === 'template-literal' ? '\${…}' : 'concat');
      console.log(`     app.js:${f.line}  ${label}  ${f.expr}`);
      if (f.sink === 'textContent-markup') {
        console.log(`       → '${f.field}' is HTML markup in textContent — textContent never renders HTML; drop the markup or use innerHTML/insertAdjacentHTML with escapeHtml(...)`);
      } else {
        console.log(`       → '${f.field}' is external data — wrap in escapeHtml(...)`);
      }
    }
    return { ok: false, adj: adjCount, bare: bareCount, tc: tcCount }; // counts on FAIL too
  }
  console.log('  ✅ GUARD 2 — sinks ok: ' + adjCount + ' insertAdjacentHTML + ' + bareCount + ' bare-id/call innerHTML + ' + tcCount + ' textContent markup scan(s).');
  return { ok: true, adj: adjCount, bare: bareCount, tc: tcCount };
}

// ── Report (--report) ──────────────────────────────────────────────────
// Per-run surface metrics — the CI gate uses them to track how much DOM
// sink surface each PR introduces (proxy for XSS risk). Printed as a table,
// a grep-able JSON line, a GitHub ::notice:: annotation and (in CI) a
// markdown block appended to GITHUB_STEP_SUMMARY.
function printGuardReport(c, allOk) {
  const total = c.tl + c.concat + c.adj + c.bare + c.tc;
  console.log('\n  ' + '='.repeat(58));
  console.log('  📊 DOM Guard Report — sinks varridos neste PR');
  console.log('  ' + '='.repeat(58));
  const row = (label, v) => '    ' + String(v).padStart(4) + '  ' + label;
  console.log(row('interpolações em template literals (innerHTML)', c.tl));
  console.log(row('blocos de concatenação \'+\' (innerHTML)', c.concat));
  console.log(row('insertAdjacentHTML (2º arg varrido)', c.adj));
  console.log(row('innerHTML/outerHTML RHS identificador-nu/call', c.bare));
  console.log(row('textContent com markup HTML (anti-padrão)', c.tc));
  console.log(row('TOTAL sinks/blocos varridos', total));
  console.log('    ' + (allOk ? '✅ status: PASS' : '❌ status: FAIL'));
  console.log('  ' + '='.repeat(58));
  const json = JSON.stringify({
    tl: c.tl, concat: c.concat, insert_adjacent_html: c.adj,
    bare_id_inner_html: c.bare, text_content_markup: c.tc, total, ok: allOk,
  });
  console.log('GUARD_REPORT ' + json);
  if (process.env.GITHUB_ACTIONS === 'true') {
    console.log('::notice title=DOM Guard Report::' +
      'tl=' + c.tl + ' concat=' + c.concat + ' insertAdjacentHTML=' + c.adj +
      ' bareIdInnerHTML=' + c.bare + ' textContentMarkup=' + c.tc +
      ' total=' + total + ' ' + (allOk ? 'PASS' : 'FAIL'));
    const summaryFile = process.env.GITHUB_STEP_SUMMARY;
    if (summaryFile) {
      try {
        const md =
          '## 📊 DOM Guard Report\n\n' +
          '| Métrica | Valor |\n' +
          '|---|---:|\n' +
          `| Interpolações em template literals (innerHTML) | ${c.tl} |\n` +
          `| Blocos de concatenação \`+\` (innerHTML) | ${c.concat} |\n` +
          `| insertAdjacentHTML (2º arg varrido) | ${c.adj} |\n` +
          `| innerHTML/outerHTML RHS identificador-nu/call | ${c.bare} |\n` +
          `| textContent markup (anti-padrão) | ${c.tc} |\n` +
          `| **Total varrido** | **${total}** |\n` +
          `| Status | ${allOk ? '✅ PASS' : '❌ FAIL'} |\n`;
        fs.appendFileSync(summaryFile, md);
      } catch (e) { /* best effort — summary is non-critical */ }
    }
  }
}

// ── Main ───────────────────────────────────────────────────────────────
function main() {
  const reportMode = process.argv.includes('--report');
  console.log('\n  ' + '='.repeat(58));
  console.log('  CYPHER65 — DOM Regression Guards');
  console.log('  ' + '='.repeat(58));
  const ok1 = checkDuplicateIds();
  const r2 = checkInnerHtmlEscaping();
  const r3 = checkConcatEscaping();
  const r4 = checkHtmlSinkExtension();
  const allOk = ok1 && r2.ok && r3.ok && r4.ok;
  if (reportMode) {
    printGuardReport({
      tl: r2.tl, concat: r3.concat, adj: r4.adj, bare: r4.bare, tc: r4.tc,
    }, allOk);
  }
  console.log('  ' + '='.repeat(58));
  if (allOk) {
    console.log('  ✅ PASS — all DOM regression guards green\n');
    process.exit(0);
  }
  console.log('  ❌ FAIL — fix the regressions above before merging\n');
  process.exit(1);
}

main();
