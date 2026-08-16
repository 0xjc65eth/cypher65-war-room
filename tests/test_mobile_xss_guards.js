#!/usr/bin/env node
/**
 * CYPHER65 // WAR ROOM — Mobile XSS Guards Self-Test
 * ==================================================
 *
 * Protects scripts/check-mobile-xss.cjs from regressions in the guard
 * itself. Runs the REAL guard binary (subprocess, not mocks) against
 * disposable fixture files in a temp dir via the GUARD_MOBILE_ROOT env
 * override, and asserts the exit codes:
 *
 *   1. Baseline (safe RN code)                       → exit 0 (PASS)
 *   2. WebView source={{ html: `…${item.title}…` }}  → exit 1 (XSS TL)
 *   3. WebView source={{ html: '<div>' + item.title + '</div>' }} → exit 1
 *      (concat — unknown construction in an HTML value)
 *   4. source={{ html: '<div>static</div>' }}        → exit 0 (literal)
 *   5. source={{ html: buildSafeHtml(item.title) }}  → exit 0 (builder)
 *   6. source={{ html: rawHtml }} + rawHtml = `<b>${x.name}</b>` → exit 1
 *      (bare-id declaration-following)
 *   7. source={{ html: rawHtml }} + rawHtml = '<b>static</b>' → exit 0
 *   8. Multi-line source={{ html: `…${x.t}…` }}      → exit 1 (join)
 *   9. injectedJavaScript={`window.foo('${name}')`}  → exit 1 (JS inject)
 *  10. injectedJavaScript="window.__init();"         → exit 0 (literal)
 *  11. dangerouslySetInnerHTML={{ __html: x.html }}  → exit 1 (review gate)
 *  12. renderHTML from react-native-render-html      → exit 1 (review gate)
 *  13. eval(response.data)                           → exit 1 (banned)
 *  14. new Function('return ' + code)                → exit 1 (banned)
 *  15. Linking.openURL('javascript:alert(1)')        → exit 1 (scheme XSS)
 *  16. Linking.openURL('https://braiins.com')        → exit 0 (literal URL)
 *  17. Linking.openURL(`https://x/${id}`)            → exit 1 (interp URL)
 *  18. source={{ uri: 'javascript:…' }}              → exit 1 (scheme)
 *  19. Comment mentioning source={{ html: `${x}` }}  → exit 0 (no FP)
 *  20. source={{ html }} + html = '<b>static</b>'    → exit 0 (shorthand)
 *  21. source={{ html }} + html = `<b>${x.name}</b>` → exit 1 (shorthand)
 *  22. source={{ html: `…${escapeHtml(item.title)}…` }} → exit 0 (escaped)
 *  23. Trailing inline comment mentioning openURL('javascript:…') → exit 0
 *      (comments stripped string-aware — no FP)
 *  24. openURL('https://x/' + id) — concat chain STARTING with a literal
 *      → exit 1 (string-aware concat detection, no leading-quote escape)
 *  25. openURL('https://x/search?a=1+2&b=3') — '+' INSIDE a pure literal
 *      URL query → exit 0 (no FP)
 *
 * Run: node tests/test_mobile_xss_guards.js   (also wired into CI gate)
 */

'use strict';

import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

const ROOT = path.resolve(__dirname, '..');
const GUARD = path.join(ROOT, 'scripts', 'check-mobile-xss.cjs');

// ── Test counters (same harness pattern as test_dom_guards.js) ─────────
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

// Safe baseline — plain RN code with no XSS sinks.
const BASELINE = `import React from 'react';
import { Text } from 'react-native';

export default function Screen({ item }) {
  return <Text>{item.title}</Text>;
}
`;

// Fixture files keyed by name. Each case runs the guard against ONLY its
// own file so exit codes are attributable per case.
const CASES = [
  { name: '01-baseline.tsx', expect: 0, body: BASELINE },
  {
    name: '02-html-tl.tsx', expect: 1,
    body: `import { WebView } from 'react-native-webview';
export default function S({ item }) {
  return <WebView source={{ html: \`<div class="t">\${item.title}</div>\` }} />;
}
`,
  },
  {
    name: '03-html-concat.tsx', expect: 1,
    body: `import { WebView } from 'react-native-webview';
export default function S({ item }) {
  return <WebView source={{ html: '<div class="t">' + item.title + '</div>' }} />;
}
`,
  },
  {
    name: '04-html-literal.tsx', expect: 0,
    body: `import { WebView } from 'react-native-webview';
export default function S() {
  return <WebView source={{ html: '<div class="t">static</div>' }} />;
}
`,
  },
  {
    name: '05-html-builder.tsx', expect: 0,
    body: `import { WebView } from 'react-native-webview';
function buildSafeHtml(s) { return String(s).replace(/</g, '&lt;'); }
export default function S({ item }) {
  return <WebView source={{ html: buildSafeHtml(item.title) }} />;
}
`,
  },
  {
    name: '06-html-bareid-unsafe.tsx', expect: 1,
    body: `import { WebView } from 'react-native-webview';
export default function S({ x }) {
  const rawHtml = \`<b>\${x.name}</b>\`;
  return <WebView source={{ html: rawHtml }} />;
}
`,
  },
  {
    name: '07-html-bareid-safe.tsx', expect: 0,
    body: `import { WebView } from 'react-native-webview';
export default function S() {
  const rawHtml = '<b>static</b>';
  return <WebView source={{ html: rawHtml }} />;
}
`,
  },
  {
    name: '08-html-multiline.tsx', expect: 1,
    body: `import { WebView } from 'react-native-webview';
export default function S({ x }) {
  return (
    <WebView
      source={{
        html: \`
          <div class="card">
            <span>\${x.t}</span>
          </div>
        \`,
      }}
    />
  );
}
`,
  },
  {
    name: '09-injected-js.tsx', expect: 1,
    body: `import { WebView } from 'react-native-webview';
export default function S({ name }) {
  return <WebView source={{ html: '<div>x</div>' }} injectedJavaScript={\`window.foo('\${name}')\`} />;
}
`,
  },
  {
    name: '10-injected-js-literal.tsx', expect: 0,
    body: `import { WebView } from 'react-native-webview';
export default function S() {
  return <WebView source={{ html: '<div>x</div>' }} injectedJavaScript="window.__init();" />;
}
`,
  },
  {
    name: '11-dsih.tsx', expect: 1,
    body: `export default function S({ x }) {
  return <div dangerouslySetInnerHTML={{ __html: x.html }} />;
}
`,
  },
  {
    name: '12-render-html.tsx', expect: 1,
    body: `import { renderHTML } from 'react-native-render-html';
export default function S({ content }) {
  return renderHTML(content);
}
`,
  },
  {
    name: '13-eval.tsx', expect: 1,
    body: `export default function S({ data }) {
  eval(data.response);
  return null;
}
`,
  },
  {
    name: '14-new-function.tsx', expect: 1,
    body: `export default function S({ code }) {
  const f = new Function('return ' + code);
  return f;
}
`,
  },
  {
    name: '15-openurl-js.tsx', expect: 1,
    body: `import { Linking } from 'react-native';
export default function S() {
  Linking.openURL('javascript:alert(1)');
  return null;
}
`,
  },
  {
    name: '16-openurl-safe.tsx', expect: 0,
    body: `import { Linking } from 'react-native';
export default function S() {
  Linking.openURL('https://braiins.com');
  return null;
}
`,
  },
  {
    name: '17-openurl-interp.tsx', expect: 1,
    body: `import { Linking } from 'react-native';
export default function S({ id }) {
  Linking.openURL(\`https://x/\${id}\`);
  return null;
}
`,
  },
  {
    name: '18-uri-js.tsx', expect: 1,
    body: `import { WebView } from 'react-native-webview';
export default function S() {
  return <WebView source={{ uri: 'javascript:alert(1)' }} />;
}
`,
  },
  {
    name: '19-comment-only.tsx', expect: 0,
    body: `// source={{ html: \`<div>\${x}</div>\` }} — discussed in review, not used
// Linking.openURL('javascript:alert(1)') — banned, do not copy
export default function S() {
  return null;
}
`,
  },
  {
    name: '20-shorthand-safe.tsx', expect: 0,
    body: `import { WebView } from 'react-native-webview';
export default function S() {
  const html = '<b>static</b>';
  return <WebView source={{ html }} />;
}
`,
  },
  {
    name: '21-shorthand-unsafe.tsx', expect: 1,
    body: `import { WebView } from 'react-native-webview';
export default function S({ x }) {
  const html = \`<b>\${x.name}</b>\`;
  return <WebView source={{ html }} />;
}
`,
  },
  {
    name: '22-html-escaped-interp.tsx', expect: 0,
    body: `import { WebView } from 'react-native-webview';
function escapeHtml(s) { return String(s).replace(/</g, '&lt;'); }
export default function S({ item }) {
  return <WebView source={{ html: \`<div>\${escapeHtml(item.title)}</div>\` }} />;
}
`,
  },
  {
    name: '23-inline-comment.tsx', expect: 0,
    body: `import { Linking } from 'react-native';
export default function S() {
  const url = 'https://braiins.com'; // Linking.openURL('javascript:evil') noted in review
  // eslint-disable-next-line
  Linking.openURL(url);
  return null;
}
`,
  },
  {
    name: '24-openurl-concat-leading-literal.tsx', expect: 1,
    body: `import { Linking } from 'react-native';
export default function S({ id }) {
  Linking.openURL('https://x/' + id);
  return null;
}
`,
  },
  {
    name: '25-openurl-literal-plus-query.tsx', expect: 0,
    body: `import { Linking } from 'react-native';
export default function S() {
  Linking.openURL('https://x/search?a=1+2&b=3');
  return null;
}
`,
  },
];

// Run the real guard against a single fixture file; returns the exit code.
function runGuard(mobileDir) {
  const res = spawnSync(process.execPath, [GUARD], {
    cwd: ROOT,
    env: Object.assign({}, process.env, {
      GUARD_MOBILE_ROOT: mobileDir,
    }),
    encoding: 'utf-8',
    timeout: 30000,
  });
  return res.status;
}

// ── Run ─────────────────────────────────────────────────────────────────

const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'c65-mobile-xss-'));
try {
  for (const c of CASES) {
    fs.writeFileSync(path.join(tmpDir, c.name), c.body);
    const status = runGuard(tmpDir);
    assertEqual(`${c.name} → exit ${c.expect}`, status, c.expect);
    fs.rmSync(path.join(tmpDir, c.name), { force: true });
  }
} finally {
  try { fs.rmSync(tmpDir, { recursive: true, force: true }); } catch (e) { /* best effort */ }
}

console.log(`\n  mobile XSS guard self-test: ${passed} passed, ${failed} failed`);
if (failed) {
  console.log(failures.join('\n'));
  process.exit(1);
}
console.log('  ✅ mobile XSS guard self-test green\n');
