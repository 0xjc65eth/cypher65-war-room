/**
 * test_disconnect_wallet.js — Node.js unit test for _disconnectWallet()
 *
 * Runs standalone: node tests/test_disconnect_wallet.js
 * Eval's the IIFE from app.js with comprehensive browser API mocks.
 */

let passed = 0;
let failed = 0;

function assertEqual(label, actual, expected) {
  if (actual === expected) { passed++; }
  else {
    failed++;
    console.error(`  ❌ FAIL: ${label} — expected ${JSON.stringify(expected)}, got ${JSON.stringify(actual)}`);
  }
}

// ── Make a stub object that can safely receive any method call ──
function stub(el) {
  return new Proxy(el || {}, {
    get(target, prop) {
      if (prop in target) return target[prop];
      if (prop === 'addEventListener') return () => {};
      if (prop === 'removeEventListener') return () => {};
      if (prop === 'getContext') return () => ctx2d;
      if (prop === 'setAttribute') return () => {};
      if (prop === 'getAttribute') return () => null;
      if (prop === 'querySelector') return () => null;
      if (prop === 'querySelectorAll') return () => ({ forEach() {}, length: 0 });
      if (prop === 'insertAdjacentHTML') return () => {};
      if (prop === 'appendChild') return () => {};
      if (prop === 'removeChild') return () => {};
      if (prop === 'remove') return () => {};
      if (prop === 'classList') return classListMock;
      if (prop === 'style') return styleMock;
      if (prop === 'focus') return () => {};
      if (prop === 'cloneNode') return () => stub();
      if (typeof prop === 'string' && prop.startsWith('getElementsBy')) return () => [];
      return () => {};
    },
    set(target, prop, val) { target[prop] = val; return true; },
  });
}

const classListMock = stub({ add() {}, remove() {}, contains() { return false; }, toggle() {} });
const styleMock = stub({ display: '', width: '', height: '', color: '', background: '', borderColor: '', transform: '' });
const ctx2d = stub({
  setTransform() {}, clearRect() {}, beginPath() {}, moveTo() {}, lineTo() {},
  closePath() {}, fill() {}, stroke() {}, arc() {}, fillText() {}, createLinearGradient() { return { addColorStop() {} }; },
});

// ── Mock DOM ──
const _banner = stub({ style: stub({ display: 'block' }) });
const _dcBtn = stub({ style: stub({ display: '' }) });
const _topbarAddr = stub({ textContent: '—' });

const _mockDoc = {
  body: stub(),
  documentElement: stub(),
  head: stub(),
  addEventListener() {},
  removeEventListener() {},
  createElement() { return stub(); },
  getElementById(id) {
    const map = {
      'disconnect-wallet': _dcBtn,
      'wallet-banner': _banner,
      'topbar-address': _topbarAddr,
      'clear-logs': null,
    };
    return map[id] !== undefined ? map[id] : stub();
  },
  querySelector(s) { 
    // Handle #id selectors like getElementById
    if (typeof s === 'string' && s.startsWith('#')) {
      return this.getElementById(s.slice(1));
    }
    return null;
  },
  querySelectorAll() { return stub({ forEach() {}, length: 0 }); },
};
globalThis.document = _mockDoc;

// ── Mock confirm ──
let _confirmResult = true;
globalThis.confirm = (msg) => _confirmResult;

// ── Mock localStorage ──
let _storage = {};
globalThis.localStorage = {
  getItem(k) { return _storage[k] || null; },
  setItem(k, v) { _storage[k] = String(v); },
  removeItem(k) { delete _storage[k]; },
  clear() { _storage = {}; },
  get length() { return Object.keys(_storage).length; },
  key(i) { return Object.keys(_storage)[i] || null; },
};

// ── Mock fetch ──
let _fetchCalls = [];
globalThis.fetch = (url, opts) => {
  _fetchCalls.push({ url, opts });
  return Promise.resolve(stub({ ok: true, json: () => Promise.resolve({ history: [] }) }));
};

// ── Mock window ──
let _BTC_ADDRESS = null;
let _userConnectedWallet = false;

globalThis.window = stub({
  BTC_ADDRESS: null,
  _userConnectedWallet: false,
  POLL_INTERVAL_MS: 15000,
  devicePixelRatio: 1,
  innerWidth: 1024,
  innerHeight: 768,
  loadMonteCarlo() {},
  setProfitMode() {},
  __lastSnapshotHr: 0,
  __lastSnapshotDiff: 0,
});

// ── Mock timing ──
const _now = 1700000000000;
Date.now = () => _now;
Date.parse = Date.parse || ((s) => NaN);
globalThis.performance = { now: () => _now };

globalThis.requestAnimationFrame = (fn) => { fn(_now); return 1; };
globalThis.cancelAnimationFrame = () => {};

globalThis.matchMedia = () => stub({ matches: false, addListener() {}, removeListener() {} });

// ── Mock setTimeout/setInterval ──
let _timerId = 1;
globalThis.setTimeout = (fn, ms) => { return _timerId++; };
globalThis.clearTimeout = (id) => {};
globalThis.setInterval = (fn, ms) => { return _timerId++; };
globalThis.clearInterval = (id) => {};

// ── Mock Chart.js ──
globalThis.Chart = class {
  constructor(ctx, opts) { this.ctx = ctx; this.opts = opts; this.data = opts.data; }
  update() {}
  destroy() {}
};

// ── Execute the IIFE ──
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';
const __dirname = path.dirname(fileURLToPath(import.meta.url));
const jsCode = fs.readFileSync(path.join(__dirname, '/../static/app.js'), 'utf8');
eval(jsCode);

// ── Tests ─────────────────────────────────────────────────────────

console.log('\n=== _disconnectWallet() Unit Tests ===\n');

// Test 1: No wallet connected
console.log('--- Test 1: No wallet connected ---');
_confirmResult = true;
window.BTC_ADDRESS = null;
window._disconnectWallet();
assertEqual('confirm should NOT be called when no wallet', _confirmResult, true);
assertEqual('fetch should NOT be called when no wallet', _fetchCalls.length, 0);

// Test 2: confirm(false) — cancels
console.log('\n--- Test 2: confirm(false) cancels ---');
_confirmResult = false;
window.BTC_ADDRESS = 'bc1qtest';
_fetchCalls = [];
window._disconnectWallet();
assertEqual('confirm(false) preserves BTC_ADDRESS', window.BTC_ADDRESS, 'bc1qtest');
assertEqual('confirm(false) skips fetch', _fetchCalls.length, 0);

// Test 3: confirm(true) — full disconnect
console.log('\n--- Test 3: confirm(true) disconnects ---');
_storage['cypher65_wallet'] = 'bc1qwallet';
window.BTC_ADDRESS = 'bc1qwallet';
window._userConnectedWallet = true;
_banner.style.display = 'none';
_dcBtn.style.display = '';
_confirmResult = true;
_fetchCalls = [];
// Reset for the test
_topbarAddr.textContent = 'bc1qwallet…';

window._disconnectWallet();

assertEqual('BTC_ADDRESS cleared', window.BTC_ADDRESS, null);
assertEqual('_userConnectedWallet cleared', window._userConnectedWallet, false);
assertEqual('localStorage cleared', _storage['cypher65_wallet'], undefined);
assertEqual('topbar shows —', _topbarAddr.textContent, '—');
assertEqual('banner visible', _banner.style.display, '');
assertEqual('disconnect button hidden', _dcBtn.style.display, 'none');
assertEqual('fetch called', _fetchCalls.length, 1);
assertEqual('fetch to set-address', _fetchCalls[0].url, '/api/set-address');
assertEqual('fetch body address empty', JSON.parse(_fetchCalls[0].opts.body).address, '');

// ── Summary ─────────────────────────────────────────────────────
console.log(`\n=== Results: ${passed} passed, ${failed} failed ===\n`);
process.exit(failed > 0 ? 1 : 0);
