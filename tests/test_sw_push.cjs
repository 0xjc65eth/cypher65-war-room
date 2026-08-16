#!/usr/bin/env node
/**
 * CYPHER65 // SW Web Push invariants (Issue #15)
 * ===============================================
 * Guards the service worker contract that makes REAL Web Push work:
 *   - a `push` event listener must exist (without it the browser silently
 *     drops every VAPID push — subscriptions would exist but no notification
 *     would ever appear)
 *   - notifications must use a real PNG icon (not manifest.json, which is not
 *     a valid icon resource)
 *   - clicking a notification must focus/open the dashboard
 *
 * Run: node tests/test_sw_push.js
 */

'use strict';

const fs = require('fs');
const path = require('path');

let passed = 0;
let failed = 0;
const failures = [];

function check(label, ok) {
  if (ok) { passed++; }
  else { failed++; failures.push(`  ❌ ${label}`); }
}

const swPath = path.join(__dirname, '..', 'static', 'sw.js');
const src = fs.readFileSync(swPath, 'utf-8');

// 1. Real push event listener present (the critical missing piece).
check('sw.js registers a "push" event listener',
  /addEventListener\('push'/.test(src));
check('sw.js parses the payload as JSON (event.data.json)',
  /event\.data\.json\(\)/.test(src));
check('sw.js calls showNotification from the push handler',
  /registration\.showNotification/.test(src));
check('push handler gates on Notification permission',
  /Notification\.permission/.test(src));

// 1b. Severity contract — the backend nests severity at payload.data.severity;
// the handler must read the NESTED shape (else CRIT degrades to WARN).
check('push handler reads nested severity (payload.data.severity)',
  /nested\.severity/.test(src));
check('push handler forwards nested url (data.data.url)',
  /nested\.url/.test(src));

// 2. Icon contract — real PNG, never manifest.json.
check('push/notification icon is a real PNG (icon-192x192.png)',
  src.includes('/static/icon-192x192.png'));
check('no manifest.json used as icon/badge',
  !/icon:\s*'\/static\/manifest\.json'/.test(src) &&
  !/badge:\s*'\/static\/manifest\.json'/.test(src));

// 3. Click behavior — focus or open the dashboard.
check('notificationclick handler present',
  /addEventListener\('notificationclick'/.test(src));
check('click focuses existing window or opens a new one',
  /clients\.matchAll/.test(src) && /openWindow/.test(src));

// 4. Cache bump present (SW changed → cache name must change so offline
//    users never get the old SW assets).
check('cache version bumped (cypher65-v12+)',
  /cypher65-v1[2-9]/.test(src));

// ── RESULTS ─────────────────────────────────────────────────────────────
console.log('\n' + '='.repeat(50));
if (failed === 0) {
  console.log(`✅ SW PUSH: ALL ${passed} TESTS PASSED`);
} else {
  console.log(`❌ SW PUSH: ${failed}/${passed + failed} TESTS FAILED`);
  failures.forEach(f => console.log(f));
}
process.exit(failed > 0 ? 1 : 0);
