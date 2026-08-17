#!/usr/bin/env node
/**
 * check-a11y.cjs — CI accessibility regression guards (Issue #235)
 * ==============================================================
 *
 *   GUARD 1 — <html lang>
 *     The UI is pt-BR; the document language must be declared exactly as
 *     `pt-BR` so screen readers and translation tooling pick the right
 *     language. lang="en" or a missing lang attribute FAILS.
 *
 *   GUARD 2 — Icon-only interactive elements
 *     A <button> or <a> whose accessible name is empty FAILS. A name
 *     comes from aria-label / aria-labelledby / title OR from visible
 *     text content. Emoji, glyphs (☰ ☀ ⛌ × ✕ →) and <svg> alone do NOT
 *     name a control — a blind user hears "button, button, button".
 *
 *   GUARD 3 — Orphaned <label>
 *     A <label> with no `for` attribute AND no nested form control
 *     (input/select/textarea/button/meter/output/progress) names nothing
 *     and FAILS. Both legit patterns (for="id" and wrapping) pass.
 *
 * Scanning is single-pass and comment-aware: HTML comments are skipped
 * IN PLACE so reported line numbers are real file lines.
 *
 * Scans ONLY the live templates (dashboard.html, agent_guide.html) —
 * *.backup* files are historical snapshots, not shipped UI.
 *
 * Known tradeoffs (documented, mirroring check-dom-regression.cjs):
 *   - aria-labelledby is accepted by PRESENCE — the reference is not
 *     resolved/validated (deep name-computation is axe-core territory).
 *   - Descendant text alternatives are not resolved: an element whose
 *     only name comes from a CHILD aria-label (<a><span aria-label="X">…
 *     </span></a>) is a theoretical false positive (none today).
 *   - Unclosed <button>/<a>/<label> (missing close tag) are skipped —
 *     the guard does not balance tags (same policy as the DOM guard).
 *
 * Env overrides (self-test pattern, mirrors check-dom-regression.cjs):
 *   GUARD_TPL_DIR  — directory whose *.html files are scanned instead
 *                    (used by tests/test_a11y_guards.js with fixtures)
 *
 * Exit codes:
 *   0 — clean
 *   1 — violations found (merge gate)
 *   2 — IO/parse error
 */

'use strict';

const fs = require('node:fs');
const path = require('node:path');

const ROOT = path.join(__dirname, '..');
const TPL_DIR = process.env.GUARD_TPL_DIR || path.join(ROOT, 'templates');
const REPORT = process.argv.includes('--report');

const LANG_EXPECTED = 'pt-BR';
// Form controls that make a <label> wrapping pattern valid.
const LABEL_CONTROLS = /<(input|select|textarea|button|meter|output|progress)\b/i;

const violations = [];
const stats = { files: 0, buttons: 0, links: 0, labels: 0 };

function collectFiles(dir) {
  let names;
  try {
    names = fs.readdirSync(dir);
  } catch (e) {
    console.error(`[a11y] cannot read template dir ${dir}: ${e.message}`);
    process.exit(2);
  }
  return names
    .filter((f) => f.endsWith('.html') && !f.includes('.backup'))
    .sort()
    .map((f) => path.join(dir, f));
}

function lineAt(src, index) {
  return src.slice(0, index).split('\n').length;
}

function attr(attrs, name) {
  const m = attrs.match(new RegExp(name + '\\s*=\\s*("[^"]*"|\'[^\']*\')', 'i'));
  return m ? m[1].slice(1, -1) : '';
}

function cleanText(inner) {
  return inner
    .replace(/<svg[\s\S]*?<\/svg>/gi, '')
    .replace(/<[^>]*>/g, '')
    .replace(/&amp;/g, '&')
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>')
    .replace(/&quot;/g, '"')
    .replace(/&#0?39;/g, "'")
    .replace(/&nbsp;/g, ' ')
    // Entidades numéricas (&#10095; / &#x2B;) — decodifica ANTES do teste
    // alfanumérico: o literal "&#10095;" contém dígitos e passaria como texto
    // nomeado (false negative) — exatamente a classe de ícone que o guard vigia.
    .replace(/&#x([0-9a-fA-F]+);/g, (_, h) => { const c = parseInt(h, 16); return c <= 0x10FFFF ? String.fromCodePoint(c) : ''; })
    .replace(/&#(\d+);/g, (_, d) => { const c = parseInt(d, 10); return c <= 0x10FFFF ? String.fromCodePoint(c) : ''; })
    .trim();
}

function flag(src, index, msg, hint) {
  violations.push(`  ${lineAt(src, index)}  ${msg}${hint ? `  (${hint})` : ''}`);
}

function scanFile(file) {
  let src;
  try {
    src = fs.readFileSync(file, 'utf8');
  } catch (e) {
    console.error(`[a11y] cannot read ${file}: ${e.message}`);
    process.exit(2);
  }
  stats.files += 1;

  // ── GUARD 1: <html lang> (na src original — o <html> precede comentários) ──
  const htmlTag = src.match(/<html\b[^>]*>/i);
  if (!htmlTag) {
    flag(src, 0, 'GUARD 1 — <html> tag não encontrada', 'adicione <html lang="pt-BR">');
  } else {
    const lang = attr(htmlTag[0], 'lang');
    if (lang !== LANG_EXPECTED) {
      flag(src, htmlTag.index, `GUARD 1 — lang="${lang || '(ausente)'}" esperado "${LANG_EXPECTED}"`, 'UI é pt-BR');
    }
  }

  // ── GUARD 2 + 3: single-pass, comentários pulados in place ──────────────
  // Cada alternativa é autocontida (grupos fixos por branch) — sem \1 cruzado.
  const TOKEN = /<!--[\s\S]*?-->|<button\b((?:[^>"']|"[^"]*"|'[^']*')*)>([\s\S]*?)<\/button>|<a\b((?:[^>"']|"[^"]*"|'[^']*')*)>([\s\S]*?)<\/a>|<label\b((?:[^>"']|"[^"]*"|'[^']*')*)>([\s\S]*?)<\/label>/gi;
  let m;
  while ((m = TOKEN.exec(src)) !== null) {
    const tok = m[0];
    if (tok.startsWith('<!--')) continue;

    if (tok.startsWith('<button')) {
      const attrs = m[1]; const inner = m[2];
      stats.buttons += 1;
      const hasName = !!(attr(attrs, 'aria-label') || attr(attrs, 'aria-labelledby') || attr(attrs, 'title'));
      const text = cleanText(inner);
      if (!hasName && !/\p{L}|\p{N}/u.test(text)) {
        const hint = `id="${attr(attrs, 'id')}" class="${attr(attrs, 'class')}" conteúdo="${text || (inner.match(/<svg/i) ? '<svg>' : (inner.trim() || 'vazio'))}"`;
        flag(src, m.index, 'GUARD 2 — button ícone-only sem nome acessível', hint.trim());
      }
    } else if (tok.startsWith('<a')) {
      const attrs = m[3]; const inner = m[4];
      stats.links += 1;
      const hasName = !!(attr(attrs, 'aria-label') || attr(attrs, 'aria-labelledby') || attr(attrs, 'title'));
      const text = cleanText(inner);
      if (!hasName && !/\p{L}|\p{N}/u.test(text)) {
        const hint = `href="${attr(attrs, 'href')}" class="${attr(attrs, 'class')}"`;
        flag(src, m.index, 'GUARD 2 — a ícone-only sem nome acessível', hint.trim());
      }
    } else {
      // <label>
      const attrs = m[5]; const inner = m[6];
      stats.labels += 1;
      if (!attr(attrs, 'for') && !LABEL_CONTROLS.test(inner)) {
        flag(src, m.index, 'GUARD 3 — <label> órfão (sem for e sem controle aninhado)', `class="${attr(attrs, 'class')}"`);
      }
    }
  }
}

for (const file of collectFiles(TPL_DIR)) scanFile(file);

const ok = violations.length === 0;
if (REPORT) {
  console.log(`GUARD_REPORT ${JSON.stringify({ guard: 'a11y', ok, violations: violations.length, stats })}`);
}
for (const v of violations) console.log(v);

if (!ok) {
  console.error(`\n❌ [a11y] ${violations.length} violação(ões) — GUARD 1 lang · GUARD 2 ícone-only · GUARD 3 label órfão`);
  process.exit(1);
}
console.log(`✅ [a11y] guards OK (${stats.files} arquivo(s) · ${stats.buttons} buttons · ${stats.links} links · ${stats.labels} labels · lang="${LANG_EXPECTED}")`);
process.exit(0);
