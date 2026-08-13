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
    return false;
  }
  console.log('  ✅ GUARD 2 — all ' + concatCount + ' innerHTML concat block(s) escaped or literal-safe.');
  return true;
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
    return false;
  }
  console.log('  ✅ GUARD 2 — all ' + tlCount + ' innerHTML template-literal interpolations escaped or literal-safe.');
  return true;
}

// ── Main ───────────────────────────────────────────────────────────────
function main() {
  console.log('\n  ' + '='.repeat(58));
  console.log('  CYPHER65 — DOM Regression Guards');
  console.log('  ' + '='.repeat(58));
  const ok1 = checkDuplicateIds();
  const ok2 = checkInnerHtmlEscaping();
  const ok3 = checkConcatEscaping();
  console.log('  ' + '='.repeat(58));
  if (ok1 && ok2 && ok3) {
    console.log('  ✅ PASS — all DOM regression guards green\n');
    process.exit(0);
  }
  console.log('  ❌ FAIL — fix the regressions above before merging\n');
  process.exit(1);
}

main();
