#!/usr/bin/env node
/**
 * CYPHER65 — One-time golden fixture generator for the QR core (P0-4).
 * =====================================================================
 * The encoder in static/app.js is validated CELL-FOR-CELL against golden
 * matrices produced by an INDEPENDENT implementation: Kazuhiko Arase's
 * QRCode (MIT), vendored inside `qrcode-terminal` (a root devDependency).
 *
 * This script generates the v7-10 fixtures — the version range where the
 * encoder runs its BCH version-info (type number) + placement code, the
 * least-covered path of the QR core. v1-6 fixtures were generated the same
 * way when the feature shipped (see tests/test_app_js_core.js QR_GOLDEN).
 *
 *   Usage:  node scripts/gen_qr_golden.cjs
 *   Output: a JSON object {name: {text, level, rows}} on stdout — paste the
 *           entries into `QR_GOLDEN` in tests/test_app_js_core.js.
 *
 * Each case targets an exact version (byte-mode capacity + 8-bit length
 * indicator for v7-9, 16-bit for v10). The script asserts the vendor picked
 * the expected version before emitting, so a wrong length never silently
 * produces a fixture for the wrong matrix size.
 */
'use strict';

const QRCode = require('qrcode-terminal/vendor/QRCode');
const ECL = require('qrcode-terminal/vendor/QRCode/QRErrorCorrectLevel');

const PATTERN = 'abcdefghijklmnopqrstuvwxyz0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ';

function textOf(n) {
  let s = '';
  for (let i = 0; i < n; i++) s += PATTERN[i % PATTERN.length];
  return s;
}

// Version -> ECC level -> max byte-mode payload (n chars) that still fits.
// Lengths chosen are mid-range within each target version so the auto
// type-number selection cannot wobble between runs.
const CASES = [
  { name: 'v7M',  version: 7,  level: 'M', n: 115 },
  { name: 'v8L',  version: 8,  level: 'L', n: 170 },
  { name: 'v9Q',  version: 9,  level: 'Q', n: 120 },
  { name: 'v10H', version: 10, level: 'H', n: 100 },
];

const ECL_BY_LETTER = { L: ECL.L, M: ECL.M, Q: ECL.Q, H: ECL.H };

const out = {};
for (const c of CASES) {
  const qr = new QRCode(-1, ECL_BY_LETTER[c.level]); // typeNumber -1 = auto
  qr.addData(textOf(c.n));
  qr.make();
  const size = qr.getModuleCount();
  const version = (size - 17) / 4;
  if (version !== c.version) {
    throw new Error(
      `${c.name}: expected version ${c.version} but the vendor chose ` +
      `${version} (size ${size}) — adjust n=${c.n}`
    );
  }
  const rows = [];
  for (let r = 0; r < size; r++) {
    let row = '';
    for (let col = 0; col < size; col++) row += qr.isDark(r, col) ? '1' : '0';
    rows.push(row);
  }
  out[c.name] = { text: textOf(c.n), level: c.level, rows };
  console.error(`✓ ${c.name}: v${c.version} (${size}×${size}, ECC ${c.level}, ${c.n} chars)`);
}

console.log(JSON.stringify(out));
