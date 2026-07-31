#!/usr/bin/env node
/**
 * validate-dom-ids.js
 *
 * Validates that every jQuery selector ($('#id')) in the dom init block
 * of static/app.js has a matching id="id" element in templates/dashboard.html.
 *
 * Usage:
 *   node scripts/validate-dom-ids.js
 *
 * Exit codes:
 *   0 — all good
 *   1 — missing HTML elements found
 *   2 — script error
 */

const fs = require('fs');
const path = require('path');

const PROJECT_ROOT = path.resolve(__dirname, '..');
const APP_JS = path.join(PROJECT_ROOT, 'static', 'app.js');
const DASHBOARD_HTML = path.join(PROJECT_ROOT, 'templates', 'dashboard.html');

// ── Helpers ──────────────────────────────────────────────────────────────

/** Extract all jQuery selector IDs from text: $('#some-id') */
function extractJQueryIds(text) {
  const regex = /\$\(['"](#[a-zA-Z0-9_-]+)['"]\)/g;
  const ids = new Set();
  let match;
  while ((match = regex.exec(text)) !== null) {
    ids.add(match[1].replace(/^#/, ''));
  }
  return ids;
}

/** Extract all id="..." attribute values from HTML text */
function extractHtmlIds(text) {
  const regex = /id="([a-zA-Z0-9_-]+)"/g;
  const ids = new Set();
  let match;
  while ((match = regex.exec(text)) !== null) {
    ids.add(match[1]);
  }
  return ids;
}

/** Extract all document.getElementById('...') calls from JS text */
function extractGetElementById(text) {
  const regex = /getElementById\(['"]([a-zA-Z0-9_-]+)['"]\)/g;
  const ids = new Set();
  let match;
  while ((match = regex.exec(text)) !== null) {
    ids.add(match[1]);
  }
  return ids;
}

// ── Main ─────────────────────────────────────────────────────────────────

function main() {
  // Check files exist
  for (const f of [APP_JS, DASHBOARD_HTML]) {
    if (!fs.existsSync(f)) {
      console.error(`[dom-validate] ERROR: file not found: ${f}`);
      process.exit(2);
    }
  }

  const jsText = fs.readFileSync(APP_JS, 'utf-8');
  const htmlText = fs.readFileSync(DASHBOARD_HTML, 'utf-8');

  // Extract IDs from both sources
  const jsJqueryIds = extractJQueryIds(jsText);
  const jsGetElemIds = extractGetElementById(jsText);
  const htmlIds = extractHtmlIds(htmlText);

  console.log(`\n  ${'='.repeat(55)}`);
  console.log(`  CYPHER65 — DOM ID Validation`);
  console.log(`  ${'='.repeat(55)}`);
  console.log(`\n  📁 static/app.js:`);
  console.log(`     jQuery $('#id') selectors:    ${String(jsJqueryIds.size).padStart(3)}`);
  console.log(`     document.getElementById():    ${String(jsGetElemIds.size).padStart(3)}`);
  console.log(`  📁 templates/dashboard.html:`);
  console.log(`     HTML id=\"...\" attributes:     ${String(htmlIds.size).padStart(3)}`);

  // ── Check 1: jQuery selectors vs HTML ids ──
  const missingFromHtml = [...jsJqueryIds].filter(id => !htmlIds.has(id));

  if (missingFromHtml.length > 0) {
    console.log(`\n  ❌ jQuery selectors WITHOUT matching HTML id:`);
    console.log(`     ${missingFromHtml.length} missing\n`);
    for (const id of missingFromHtml) {
      console.log(`        #${id}`);
    }
  } else {
    console.log(`\n  ✅ All ${jsJqueryIds.size} jQuery selectors have matching HTML elements.`);
  }

  // ── Check 2: document.getElementById vs HTML ids ──
  const missingGetElem = [...jsGetElemIds].filter(id => !htmlIds.has(id));

  if (missingGetElem.length > 0) {
    console.log(`\n  ⚠️  document.getElementById() WITHOUT matching HTML id:`);
    console.log(`     ${missingGetElem.length} missing\n`);
    for (const id of missingGetElem) {
      // Find where it's used
      const lines = jsText.split('\n');
      const lineNum = lines.findIndex(l => l.includes(`getElementById('${id}')`) || l.includes(`getElementById("${id}")`));
      console.log(`        #${id}${lineNum >= 0 ? `  (app.js:${lineNum + 1})` : ''}`);
    }
  } else {
    console.log(`\n  ✅ All document.getElementById() calls have matching HTML elements.`);
  }

  // ── Check 3: Orphaned HTML elements (not referenced by either method) ──
  const allJsIds = new Set([...jsJqueryIds, ...jsGetElemIds]);
  const orphanedHtml = [...htmlIds].filter(id => !allJsIds.has(id));

  if (orphanedHtml.length > 0) {
    console.log(`\n  ℹ️  HTML elements NOT referenced by any JS selector:`);
    console.log(`     ${orphanedHtml.length} elements (may be used by innerHTML or styling)`);
    if (orphanedHtml.length <= 30) {
      for (const id of orphanedHtml.slice(0, 20)) {
        console.log(`        #${id}`);
      }
      if (orphanedHtml.length > 20) {
        console.log(`        ... and ${orphanedHtml.length - 20} more`);
      }
    }
  }

  // ── Summary ──
  const totalErrors = missingFromHtml.length + missingGetElem.length;

  console.log(`\n  ${'='.repeat(55)}`);
  if (totalErrors === 0) {
    console.log(`  ✅ PASS — all DOM references match HTML elements`);
  } else {
    console.log(`  ❌ FAIL — ${totalErrors} DOM reference${totalErrors > 1 ? 's' : ''} missing from HTML`);
  }
  console.log(`  ${'='.repeat(55)}\n`);

  process.exit(totalErrors > 0 ? 1 : 0);
}

main();
