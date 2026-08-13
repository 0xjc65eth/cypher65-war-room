#!/usr/bin/env node
/**
 * check-mobile-xss.cjs
 *
 * CI regression guard for the React Native app (mobile/) — the same XSS
 * vectors the web guard (check-dom-regression.cjs) blocks, expressed in
 * React Native terms:
 *
 *   WEBV-HTML   WebView source={{ html: <expr> }} / source={{ html }}
 *               — HTML injected into a WebView is the RN equivalent of
 *                 innerHTML. The expr is analysed the same way: pure
 *                 literal = safe, whitelisted HTML builder = safe, bare
 *                 identifier = declaration-followed (bounded by the
 *                 enclosing component/function), template-literal
 *                 interpolation of external record data = FLAG, any
 *                 other construction (concat, unknown call) = FLAG.
 *   WEBV-JS     injectedJavaScript / injectedJavaScriptBeforeContentLoaded
 *               — JS code injected into the WebView page. Same analysis.
 *   DSIH        dangerouslySetInnerHTML — React DOM sink; usage is a
 *               review gate (RN has no DOM outside WebView).
 *   RHTM        react-native-render-html (renderHTML(, <RenderHTML,
 *               import … 'react-native-render-html') — HTML rendering;
 *               usage is a review gate.
 *   EVAL        eval( / new Function( — code injection (also rejected by
 *               the app stores); usage is a review gate.
 *   OURL        Linking.openURL(...) / openURL(...) — a literal
 *               'javascript:' scheme in the argument is a real XSS
 *               vector; a URL built from external data (template-literal
 *               interpolation or '+' concat) is a scheme-injection review
 *               gate. Pure literals and whitelisted builders pass.
 *   URIJS       WebView source={{ uri: 'javascript:…' }} — scheme vector.
 *
 * Safe constructs accepted WITHOUT escape:
 *   - pure string literals ('<div>static</div>', "https://…", backticks
 *     with NO ${} interpolation)
 *   - whitelisted HTML builders — escapeHtml, buildSafeHtml, sanitizeHtml,
 *     htmlEscape, stripHtml, buildHtmlSafely (their ARGUMENTS are NOT
 *     re-checked; the contract is that they escape internally)
 *   - bare identifiers inside ${} (a variable is assumed pre-escaped by
 *     its builder — same contract as the web guard)
 *   - numeric literals
 *
 * Deliberately stricter than the web guard (this is a prevention net for
 * a codebase with ZERO such sinks today): member reads of external
 * records (item.title, data.html), unknown calls and '+' concat inside a
 * WebView HTML/JS value are FLAGGED unless wrapped in a whitelisted
 * builder. A future dev that needs an interpolated value must route it
 * through buildSafeHtml(...) / escapeHtml(...) — the same discipline the
 * web guard enforces.
 *
 * Declaration-following: `const raw = <expr>` is searched backward
 * (bounded by the nearest preceding component/function boundary line and
 * 400 lines) and its RHS is analysed in place of the bare id. `var`-
 * hoisted declarations after the sink are not seen (documented).
 *
 * Usage:
 *   node scripts/check-mobile-xss.cjs
 *
 * Env overrides (used by the committed self-test):
 *   GUARD_MOBILE_ROOT  — mobile/ dir to scan (default: ./mobile)
 *
 * Exit codes:
 *   0 — all guards pass
 *   1 — at least one XSS vector found
 *   2 — script error
 */
'use strict';

const fs = require('fs');
const path = require('path');

const ROOT = path.resolve(__dirname, '..');
const MOBILE_ROOT = process.env.GUARD_MOBILE_ROOT || path.join(ROOT, 'mobile');

// Whitelisted HTML/JS builders — the ONLY way to feed external data into
// a WebView html/injectedJavaScript value. Their args are not re-checked.
const SAFE_BUILDERS = /^(?:escapeHtml|buildSafeHtml|sanitizeHtml|htmlEscape|stripHtml|buildHtmlSafely)\s*\(/;

// ── File walk ───────────────────────────────────────────────────────────
function walkTs(dir, out) {
  for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
    const p = path.join(dir, e.name);
    if (e.isDirectory()) {
      if (e.name === 'node_modules') continue;
      walkTs(p, out);
    } else if (/\.(ts|tsx)$/.test(e.name)) {
      out.push(p);
    }
  }
  return out;
}

// ── Value extraction ────────────────────────────────────────────────────

// Extracts the html value of `source={{ html: <value> }}`: from the char
// AFTER 'html:' (or 'html=') up to the closing '}}'. The '{{' opened BEFORE
// fromIdx, so depth starts at 2 and the value ends right before the first
// '}' at depth 2 (the first char of the closing '}}'). String/template-
// aware so a '}}' or '{{' inside a literal or ${...} never truncates early.
// Returns { value, closed } — `closed` is false when the text ran out
// before the closing '}}' (caller must append the following lines).
function extractHtmlValue(text, fromIdx) {
  let depth = 2, q = null, i = fromIdx;
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
    if (c === '{') { depth++; i++; continue; }
    if (c === '}') {
      if (depth === 2) return { value: text.slice(fromIdx, i).trim(), closed: true };
      depth--;
      i++;
      continue;
    }
    i++;
  }
  return { value: text.slice(fromIdx).trim(), closed: false };
}

// Extracts a quoted/template literal starting at `fromIdx` (after optional
// whitespace): up to the closing quote (string-aware; ${...} skipped inside
// backticks). Returns '' when the next non-space char is not a quote.
// Used for prop values assigned WITHOUT braces: injectedJavaScript="…".
function extractQuotedValue(text, fromIdx) {
  let i = fromIdx;
  while (i < text.length && /\s/.test(text[i])) i++;
  const q0 = text[i];
  if (q0 !== "'" && q0 !== '"' && q0 !== '`') return '';
  const start = i;
  i++;
  let q = q0;
  while (i < text.length) {
    const c = text[i];
    if (q === '`' && c === '$' && text[i + 1] === '{') {
      let bd = 1, k = i + 2;
      while (k < text.length && bd > 0) {
        if (text[k] === '{') bd++;
        else if (text[k] === '}') bd--;
        k++;
      }
      i = k;
      continue;
    }
    if (c === q && text[i - 1] !== '\\') return text.slice(start, i + 1);
    i++;
  }
  return text.slice(start);
}

// Extracts the value of `prop={ <value> }` (single-brace): from the char
// after '=', skipping whitespace and the optional '{', up to the matching
// '}' at depth 0, outside strings/templates.
function extractBraceValue(text, fromIdx) {
  let i = fromIdx;
  while (i < text.length && /\s/.test(text[i])) i++;
  if (text[i] === '{') i++;
  let depth = 0, q = null;
  const start = i;
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
    if (c === '{') { depth++; i++; continue; }
    if (c === '}') {
      if (depth === 0) return text.slice(start, i).trim();
      depth--;
      i++;
      continue;
    }
    i++;
  }
  return text.slice(start).trim();
}

// ── Interpolation analysis ──────────────────────────────────────────────

// Is one ${...} interpolation expression provably safe?
//   - wrapped in a whitelisted builder          → safe
//   - string/numeric literal                    → safe
//   - ternary: only the ARMS are checked        → safe iff both arms safe
//   - anything else (bare variable, member read, unknown call, concat…)
//     → unsafe — a WebView HTML/JS value is a code-execution boundary;
//     interpolated data must pass through a whitelisted builder. This is
//     deliberately stricter than the web guard: mobile has ZERO such sinks
//     today, so the safe path is a builder or a literal, nothing else.
function safeInterpExpr(e) {
  const t = e.trim();
  if (!t) return true;
  if (SAFE_BUILDERS.test(t) && /\)$/.test(t)) return true;
  if (/^'(?:[^'\\]|\\.)*'$/.test(t) || /^"(?:[^"\\]|\\.)*"$/.test(t)) return true;
  if (/^`[^`]*`$/.test(t)) return true;
  if (/^[-+]?[0-9]/.test(t)) return true;
  // ternary: condition is a read, never interpolated — check arms.
  const qIdx = t.indexOf('?');
  const colonIdx = t.indexOf(':');
  if (qIdx !== -1 && colonIdx > qIdx) {
    return safeInterpExpr(t.slice(qIdx + 1, colonIdx))
      && safeInterpExpr(t.slice(colonIdx + 1));
  }
  return false;
}

// Analyses a WebView HTML/JS value. Returns true when safe, else pushes
// findings. `resolveId` follows bare identifiers to their declaration.
function analyzeValue(v, file, line, flags, ctx) {
  const t = v.trim();
  if (!t) return true;
  // Pure single/double-quoted literal — no interpolation possible.
  if (/^'(?:[^'\\]|\\.)*'$/.test(t) || /^"(?:[^"\\]|\\.)*"$/.test(t)) return true;
  // Backtick literal — safe iff it has NO ${} at all (pure literal text).
  if (/^`[^`]*`$/.test(t) && !/\$\{/.test(t)) return true;
  // Whole value is a whitelisted builder call (e.g. source={{ html: buildSafeHtml(x) }}).
  if (SAFE_BUILDERS.test(t) && /\)$/.test(t)) return true;
  // Bare identifier → declaration-follow (the `source={{ html: rawHtml }}` shape).
  if (/^[a-zA-Z_$][\w$]*$/.test(t)) {
    // Cycle / depth guards: `const a = b; const b = a;` would otherwise
    // recurse forever (stack overflow = false FAIL). A name is followed at
    // most once per file; a global hop cap catches deep chains.
    if (ctx.followed.has(t) || ctx.hops > 12) return true;
    ctx.followed.add(t);
    ctx.hops++;
    const decl = findDeclaredRhs(t, ctx);
    if (decl) {
      return analyzeValue(decl.rhs, file, decl.line, flags, ctx);
    }
    return true; // unresolved bare id = pre-escaped fragment (same contract as web guard)
  }
  // Template literal with ${…} → check every interpolation.
  if (t.startsWith('`')) {
    let ok = true;
    const re = /\$\{([^}]*)\}/g;
    let m;
    while ((m = re.exec(t)) !== null) {
      if (!safeInterpExpr(m[1])) {
        pushFlag(flags, { file, line, expr: '${' + m[1].slice(0, 60) + '}', kind: 'interpolation' });
        ok = false;
      }
    }
    return ok;
  }
  // Anything else (concat chain, unknown call, object…) → review gate.
  pushFlag(flags, { file, line, expr: t.slice(0, 80), kind: 'value' });
  return false;
}

// ── Declaration following ────────────────────────────────────────────────

// Finds `const rawHtml = <expr>;` backward from `lineIdx`, bounded by the
// nearest preceding component/function boundary (a line that STARTS a
// function or arrow-const component) and a 400-line cap. Returns
// { rhs, line } or null.
function findDeclaredRhs(name, ctx) {
  const startIdx = Math.max(0, ctx.lineIdx - 1);
  const re = new RegExp('(?:const|let|var)\\s+' + name + '\\s*=');
  let boundary = -1;
  for (let i = startIdx; i >= 0 && startIdx - i < 400; i--) {
    const ln = ctx.lines[i];
    if (/^(export\s+)?(function\s+[a-zA-Z_$]|const\s+[a-zA-Z_$][\w$]*\s*=\s*(\([^)]*\)|[\w$]+)\s*=>)/.test(ln)) {
      boundary = i;
      break;
    }
  }
  for (let i = startIdx; i > boundary; i--) {
    const ln = ctx.lines[i];
    if (/^\s*(\/\/|\*)/.test(ln)) continue; // comment line
    if (!re.test(ln)) continue;
    const eq = ln.indexOf('=');
    const rhs = ln.slice(eq + 1).replace(/;\s*$/, '').trim();
    if (!rhs) continue;
    return { rhs, line: i + 1 };
  }
  return null;
}

// ── Findings ────────────────────────────────────────────────────────────

const _flagKeys = new Set();
function pushFlag(flags, f) {
  const key = f.file + ':' + f.line + ':' + f.kind + ':' + f.expr;
  if (_flagKeys.has(key)) return;
  _flagKeys.add(key);
  flags.push(f);
}

// ── Comment stripping (string-aware) ────────────────────────────────────

// Returns the non-comment prefix of a line. Tracks quote/template state so
// a '//' INSIDE a string literal ('https://…') is not treated as a comment.
// Block comments persist across lines via the caller's `st.inBlock`.
function codePrefix(line, st) {
  let out = '', i = 0, q = null;
  if (st.inBlock) {
    const end = line.indexOf('*/');
    if (end === -1) return '';
    st.inBlock = false;
    i = end + 2;
  }
  while (i < line.length) {
    const c = line[i];
    if (q === "'" || q === '"') {
      out += c;
      if (c === q && line[i - 1] !== '\\') q = null;
      i++;
      continue;
    }
    if (q === '`') {
      if (c === '$' && line[i + 1] === '{') {
        let bd = 1, k = i + 2;
        while (k < line.length && bd > 0) {
          if (line[k] === '{') bd++;
          else if (line[k] === '}') bd--;
          k++;
        }
        out += line.slice(i, k);
        i = k;
        continue;
      }
      out += c;
      if (c === '`') q = null;
      i++;
      continue;
    }
    if (c === "'" || c === '"' || c === '`') { q = c; out += c; i++; continue; }
    if (c === '/' && line[i + 1] === '/') return out;       // line comment
    if (c === '/' && line[i + 1] === '*') {
      const end = line.indexOf('*/', i + 2);
      if (end === -1) { st.inBlock = true; return out; }
      i = end + 2;                                          // inline block comment
      continue;
    }
    out += c;
    i++;
  }
  return out;
}

// String-aware check: does the arg contain '+' at depth 0 OUTSIDE quotes
// and template literals? A pure literal URL with '+' in the query
// ('https://x?a=1+2') must NOT count; a concat chain ('https://x/' + id)
// MUST count even when it STARTS with a literal.
function hasConcatOperator(arg) {
  let depth = 0, i = 0, q = null;
  while (i < arg.length) {
    const c = arg[i];
    if (q === "'" || q === '"') {
      if (c === q && arg[i - 1] !== '\\') q = null;
      i++;
      continue;
    }
    if (q === '`') {
      if (c === '$' && arg[i + 1] === '{') {
        let bd = 1, k = i + 2;
        while (k < arg.length && bd > 0) {
          if (arg[k] === '{') bd++;
          else if (arg[k] === '}') bd--;
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
    if (c === '+' && depth === 0) return true;
    i++;
  }
  return false;
}

// ── Per-file scan ───────────────────────────────────────────────────────

function scanFile(file, flags) {
  const text = fs.readFileSync(file, 'utf-8');
  const lines = text.split('\n');
  const ctx = { lines, lineIdx: 0, followed: new Set(), hops: 0 };
  const st = { inBlock: false };

  for (let i = 0; i < lines.length; i++) {
    const raw = lines[i];
    // Comments stripped STRING-AWARE so comment content never flags —
    // full-line, trailing inline (`…; // Linking.openURL('javascript:…')`)
    // and block comments included.
    const code = codePrefix(raw, st);
    if (!code.trim()) continue; // whole line is a comment
    ctx.lineIdx = i;

    // ── source={{ html: … }} — same line OR source={{ opened with
    //    html: on a following line (template literals span lines). ──
    const srcHtml = code.match(/source\s*=\s*\{\s*\{\s*html\s*[:=]/);
    const srcHtmlOpen = code.match(/source\s*=\s*\{\s*\{\s*$/);
    let skipTo = -1;
    if (srcHtml || srcHtmlOpen) {
      const maxK = Math.min(i + 9, lines.length - 1);
      let joined = code, k = i;
      let from = srcHtml ? srcHtml.index + srcHtml[0].length : -1;
      if (!srcHtml) {
        // `source={{` then `html:` on a later line — anchor to a line that
        // STARTS with the prop (avoids matching 'html:' inside a literal).
        while (k < maxK) {
          k++;
          joined += '\n' + lines[k];
          if (/^\s*html\s*[:=]/.test(lines[k])) {
            const hm = lines[k].match(/html\s*[:=]/);
            from = joined.length - lines[k].length + hm.index + hm[0].length;
            break;
          }
        }
      }
      if (from !== -1) {
        let r = extractHtmlValue(joined, from);
        while (!r.closed && k < maxK) {
          k++;
          joined += '\n' + lines[k];
          r = extractHtmlValue(joined, from);
        }
        analyzeValue(r.value, file, i + 1, flags, ctx);
      }
      skipTo = k;
    }
    if (skipTo > i) { i = skipTo; continue; } // multi-line block consumed
    // NOTE: when the value closed on the SAME line (skipTo === i) we fall
    // through so OTHER sinks on the same line (e.g. injectedJavaScript)
    // are still scanned — `source={{ html: … }} injectedJavaScript=…`.

    // ── source={{ html }} — shorthand (the variable IS the value). No
    //    `continue` — other sinks on the same line are still scanned. ──
    if (/source\s*=\s*\{\s*\{\s*html\s*\}\}/.test(code)) {
      analyzeValue('html', file, i + 1, flags, ctx);
    }

    // ── source={{ uri: 'javascript:…' }} ──
    if (/source\s*=\s*\{\s*\{\s*uri\s*:\s*['"`][^'"`]*javascript:/i.test(code)) {
      pushFlag(flags, { file, line: i + 1, expr: code.trim().slice(0, 80), kind: 'uri-javascript' });
      continue;
    }

    // ── injectedJavaScript / injectedJavaScriptBeforeContentLoaded ──
    const injM = code.match(/injectedJavaScript(?:BeforeContentLoaded)?\s*=\s*/);
    if (injM) {
      const fromIdx = injM.index + injM[0].length;
      const after = code.slice(fromIdx).trim();
      let v;
      if (after.startsWith('{')) v = extractBraceValue(code, fromIdx);
      else v = extractQuotedValue(code, fromIdx);
      if (!v) v = after.replace(/;\s*$/, ''); // fallback — raw remainder
      analyzeValue(v, file, i + 1, flags, ctx);
      continue;
    }

    // ── dangerouslySetInnerHTML ──
    if (/dangerouslySetInnerHTML/.test(code)) {
      pushFlag(flags, { file, line: i + 1, expr: code.trim().slice(0, 80), kind: 'dsih' });
      continue;
    }
    // ── react-native-render-html ──
    if (/renderHTML\s*\(/.test(code) || /<RenderHTML\b/.test(code) || /from\s*['"]react-native-render-html['"]/.test(code)) {
      pushFlag(flags, { file, line: i + 1, expr: code.trim().slice(0, 80), kind: 'render-html' });
      continue;
    }
    // ── eval / new Function ──
    if (/\beval\s*\(/.test(code) || /new\s+Function\s*\(/.test(code)) {
      pushFlag(flags, { file, line: i + 1, expr: code.trim().slice(0, 80), kind: 'eval' });
      continue;
    }
    // ── Linking.openURL / openURL ──
    const urlM = code.match(/(?:Linking\s*\.\s*)?openURL\s*\(/);
    if (urlM) {
      const after = code.slice(urlM.index + urlM[0].length);
      const arg = after.replace(/[;)]\s*$/, '').trim();
      if (/javascript:/i.test(arg)) {
        pushFlag(flags, { file, line: i + 1, expr: arg.slice(0, 80), kind: 'openurl-javascript' });
        continue;
      }
      if (/\$\{/.test(arg) || hasConcatOperator(arg)) {
        pushFlag(flags, { file, line: i + 1, expr: arg.slice(0, 80), kind: 'openurl-interpolated' });
        continue;
      }
    }
  }
  return flags;
}

// ── Main ────────────────────────────────────────────────────────────────

function main() {
  console.log('\n  ' + '='.repeat(58));
  console.log('  CYPHER65 — Mobile XSS Guards (React Native)');
  console.log('  ' + '='.repeat(58));
  const files = walkTs(MOBILE_ROOT, []);
  const flags = [];
  for (const f of files) scanFile(f, flags);

  if (flags.length) {
    const counts = {};
    for (const fl of flags) counts[fl.kind] = (counts[fl.kind] || 0) + 1;
    console.log('  ❌ FAIL — ' + flags.length + ' XSS vector(s) found:');
    const seen = new Set();
    for (const fl of flags) {
      const key = fl.file + ':' + fl.line;
      if (seen.has(key)) continue;
      seen.add(key);
      console.log('     ' + path.relative(ROOT, fl.file) + ':' + fl.line + '  ' + fl.kind + '  ' + fl.expr);
    }
    console.log('  ' + '-'.repeat(58));
    for (const [kind, n] of Object.entries(counts)) {
      console.log('     ' + String(n).padStart(3) + ' × ' + kind);
    }
    console.log('  ' + '='.repeat(58));
    console.log('  ❌ FAIL — ' + flags.length + ' XSS vector(s) in ' + files.length + ' file(s).');
    console.log('       WebView html/JS values MUST be literals or route through');
    console.log('       buildSafeHtml()/escapeHtml(); eval/new Function/openURL(' + "'javascript:'" + ')');
    console.log('       are banned. Fix before merging.\n');
    process.exit(1);
  }
  console.log('  ✅ PASS — ' + files.length + ' mobile file(s) scanned, 0 XSS vectors.');
  console.log('  ' + '='.repeat(58));
  console.log('  ✅ PASS — mobile XSS guard green\n');
  process.exit(0);
}

main();
