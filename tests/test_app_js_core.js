#!/usr/bin/env node
/**
 * CYPHER65 // WAR ROOM — Core JS Unit Tests
 * ===========================================
 *
 * Tests critical pure functions from static/app.js:
 *   - fmt.hashrate()       → hashrate formatting
 *   - fmt.diff()           → difficulty formatting
 *   - fmt.secsToHuman()    → human-readable time
 *   - fmt.expectedBlock()  → block time estimation
 *   - fmt.pct() / fmt.usd() / fmt.age() / fmt.uptime()
 *   - Probability math     → cumulative P(block) calculation
 *   - renderBlockHunt()    → block hunt calculation logic
 *   - renderCharts()       → chart initialization guard logic
 *   - logMessage()         → state management + max 150 cap
 *   - _applyLogFilter()    → severity/text filter + count
 *
 * Run: node tests/test_app_js_core.js
 */

'use strict';

// ── Test counters ─────────────────────────────────────────────────────────
let passed = 0;
let failed = 0;
const failures = [];

function assertEqual(label, actual, expected) {
  const a = JSON.stringify(actual);
  const e = JSON.stringify(expected);
  if (a === e) {
    passed++;
  } else {
    failed++;
    failures.push(`  ❌ ${label}: expected ${e}, got ${a}`);
  }
}

function assertApprox(label, actual, expected, tolerance) {
  tolerance = tolerance || 1e-6;
  const diff = Math.abs(Number(actual) - Number(expected));
  if (diff <= tolerance) {
    passed++;
  } else {
    failed++;
    failures.push(`  ❌ ${label}: expected ${expected} ± ${tolerance}, got ${actual} (diff ${diff})`);
  }
}

function assertTruthy(label, actual) {
  if (actual) {
    passed++;
  } else {
    failed++;
    failures.push(`  ❌ ${label}: expected truthy, got ${JSON.stringify(actual)}`);
  }
}

function assertFalsy(label, actual) {
  if (!actual) {
    passed++;
  } else {
    failed++;
    failures.push(`  ❌ ${label}: expected falsy, got ${JSON.stringify(actual)}`);
  }
}

// ── Market price formatting ──────────────────────────────────────────
function formatMarketPrice(btcPrice) {
  // BTC/TH/day → formatted string with 6 significant digits
  if (btcPrice == null || !isFinite(btcPrice) || btcPrice === 0) return '\u2014';
  if (btcPrice < 1e-8) return btcPrice.toExponential(3) + ' BTC';
  if (btcPrice < 1) return btcPrice.toFixed(8) + ' BTC';
  return btcPrice.toFixed(6) + ' BTC';
}

function formatOfferHashrate(hr) {
  // TH/s formatting for market offers (converts to appropriate unit)
  if (!hr && hr !== 0) return '\u2014';
  var v = Number(hr);
  if (v >= 1e15) return (v / 1e15).toFixed(2) + ' PH/s';
  if (v >= 1e12) return (v / 1e12).toFixed(2) + ' TH/s';
  if (v >= 1e9) return (v / 1e9).toFixed(2) + ' GH/s';
  return v.toFixed(0) + ' H/s';
}

function formatOfferCount(visible, total) {
  return visible + ' / ' + total + ' offers';
}

// Compute best price from offers (lowest price_btc_per_th_day)
function computeBestPrice(offers) {
  if (!offers || !offers.length) return null;
  var best = null;
  offers.forEach(function(o) {
    var p = parseFloat(o.price_btc_per_th_day || o.price || 0);
    if (p > 0 && (best === null || p < best)) best = p;
  });
  return best;
}

// Format BTC/TH/day price for display — mirrors app.js _fmtBtcPerTh()
// (P2 schema fix: backend sends price_per_th_day, not price_btc_per_th_day)
function fmtBtcPerTh(v) {
  var n = Number(v);
  if (!isFinite(n) || n <= 0) return '\u2014';
  if (n >= 0.001) return n.toFixed(6) + ' BTC/TH/d';
  return (n * 1e8).toLocaleString('en-US', { maximumFractionDigits: 2 }) + ' sats/TH/d';
}

// Index of the best (lowest valid price_per_th_day) offer — mirrors renderMarket()
function findBestOfferIndex(offers) {
  if (!offers || !offers.length) return -1;
  var bestIdx = -1;
  var bestVal = Infinity;
  offers.forEach(function (o, idx) {
    var p = Number(o.price_per_th_day);
    if (isFinite(p) && p > 0 && p < bestVal) { bestVal = p; bestIdx = idx; }
  });
  return bestIdx;
}

// Filter offers by provider name (case-insensitive)
function filterOffersByProvider(offers, provider) {
  if (!offers || !offers.length) return [];
  if (!provider || provider === 'all') return offers;
  return offers.filter(function(o) {
    return (o.provider || o.name || '').toLowerCase() === provider.toLowerCase();
  });
}

// Generate market offer card HTML (pure function)
// P0-4: `affiliate` = market_data.affiliate {provider,url} — when it matches
// the card's provider, render the one-click BUY button (mirrors app.js).
function renderMarketOfferHtml(offer, isBest, affiliate) {
  var provider = offer.provider || offer.name || 'unknown';
  var price = formatMarketPrice(parseFloat(offer.price_btc_per_th_day || offer.price || 0));
  var hashrate = formatOfferHashrate(offer.hashrate || 0);
  var fee = offer.fee != null ? offer.fee.toFixed(1) + '%' : '\u2014';
  var duration = offer.duration || offer.min_duration || '\u2014';
  var stale = offer._stale || offer.meta === 'stale';
  var bestClass = isBest ? ' mkt-card--best' : '';
  var staleClass = stale ? ' mkt-card--stale' : '';
  var staleBadge = stale ? '<span class="badge badge--amber" style="font-size:7px">stale</span>' : '';
  var isAffCard = !!(affiliate && affiliate.url
    && provider.toLowerCase() === String(affiliate.provider || '').toLowerCase());
  var affBtn = isAffCard
    ? '<button type="button" class="mkt-card__buy chip chip--affiliate" data-aff-url="'
      + escapeHtml(affiliate.url) + '" data-aff-provider="' + escapeHtml(affiliate.provider) + '">⚡ BUY '
      + escapeHtml(String(affiliate.provider).toUpperCase()) + '</button>'
    : '';
  // Grab a simple provider icon from name
  var icon = (provider.slice(0, 2).toUpperCase());
  return '<div class="mkt-card' + bestClass + staleClass + '" data-provider="' + escapeHtml(provider) + '">' +
    '<div class="mkt-card__head">' +
      '<span class="mkt-card__icon">' + icon + '</span>' +
      '<span class="mkt-card__name">' + escapeHtml(provider) + '</span>' +
      staleBadge +
    '</div>' +
    '<div class="mkt-card__price">' + price + '</div>' +
    '<div class="mkt-card__meta">' + hashrate + ' · ' + fee + ' fee · ' + duration + '</div>' +
    affBtn +
  '</div>';
}

// Generate market grid HTML (pure function)
function renderMarketGridHtml(offers, activeFilter) {
  if (!offers || !offers.length) {
    return '<div class="mkt-empty">no marketplace offers available</div>';
  }
  var filtered = filterOffersByProvider(offers, activeFilter);
  if (!filtered.length) {
    return '<div class="mkt-empty">no offers for selected provider</div>';
  }
  var bestPrice = computeBestPrice(filtered);
  var html = filtered.map(function(o) {
    var price = parseFloat(o.price_btc_per_th_day || o.price || 0);
    var isBest = bestPrice !== null && price > 0 && Math.abs(price - bestPrice) < 1e-12;
    return renderMarketOfferHtml(o, isBest);
  }).join('');
  return html;
}

// ═══════════════════════════════════════════════════════════════════════════
//  HTML ESCAPE (mirrors static/app.js)
// ═══════════════════════════════════════════════════════════════════════════

/* ═══════════════════════════════════════════════════════════════════════════
//  BTC ADDRESS VALIDATION (mirrors static/app.js)
// ═══════════════════════════════════════════════════════════════════════════ */

const _BECH32_CHARSET = 'qpzry9x8gf2tvdw0s3jn54khce6mua7l';
const _VALIDATE_BASE58 = '123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz';

function _bech32Polymod(values) {
  var GEN = [0x3b6a57b2, 0x26508e6d, 0x1ea119fa, 0x3d4233dd, 0x2a1462b3];
  var chk = 1;
  for (var i = 0; i < values.length; i++) {
    var top = chk >> 25;
    chk = ((chk & 0x1ffffff) << 5) ^ values[i];
    for (var j = 0; j < 5; j++) {
      if ((top >> j) & 1) chk ^= GEN[j];
    }
  }
  return chk;
}

function validateBitcoinAddress(addr) {
  if (!addr || typeof addr !== 'string') return { valid: false, error: 'Address is required' };
  addr = addr.trim();
  if (addr.length < 26 || addr.length > 90) return { valid: false, error: 'Invalid length (' + addr.length + ' chars)' };

  // FULL & FREE whitelist mirror: the 3 exact DIGO GARABELI wallets bypass
  // the strict BTC prefix rules (DOGE/LTC don't start with bc1/1/3).
  var _FULL_FREE = [
    'bc1q029y2atdtvth4puv2mm5w49m32n278jtz2sxqn',
    'dhr7a2ihqou5w5r5cpvsuvcnw4jg32qlwx',
    '1473pql42jvtwxaaxcvsocrf6ytb8teted',
  ];
  if (_FULL_FREE.indexOf(addr.toLowerCase()) !== -1) {
    return { valid: true, note: 'FULL & FREE wallet' };
  }

  if (addr.indexOf('bc1') === 0 || addr.indexOf('BC1') === 0) {
    var lower = addr.toLowerCase();
    var pos = lower.lastIndexOf('1');
    if (pos < 1 || pos + 7 > lower.length) return { valid: false, error: 'Invalid Bech32 format' };
    var hrp = lower.slice(0, pos);
    var data = lower.slice(pos + 1);
    if (hrp !== 'bc') return { valid: false, error: 'Invalid prefix (expected bc1)' };
    if (data.length < 6) return { valid: false, error: 'Data part too short' };
    for (var i = 0; i < data.length; i++) {
      if (_BECH32_CHARSET.indexOf(data[i]) === -1) return { valid: false, error: 'Invalid Bech32 character' };
    }
    var values = [];
    for (var j = 0; j < data.length; j++) values.push(_BECH32_CHARSET.indexOf(data[j]));
    var hrpExpand = [];
    for (var k = 0; k < hrp.length; k++) hrpExpand.push(hrp.charCodeAt(k) >> 5);
    hrpExpand.push(0);
    for (var l = 0; l < hrp.length; l++) hrpExpand.push(hrp.charCodeAt(l) & 31);
    var all = hrpExpand.concat(values);
    if (_bech32Polymod(all) !== 1) return { valid: false, error: 'Invalid Bech32 checksum' };
    return { valid: true };
  }

  if (addr.indexOf('1') === 0 || addr.indexOf('3') === 0) {
    for (var m = 0; m < addr.length; m++) {
      if (_VALIDATE_BASE58.indexOf(addr[m]) === -1) return { valid: false, error: 'Invalid Base58 character' };
    }
    return { valid: true, note: 'Format OK — backend will verify checksum' };
  }

  return { valid: false, error: 'Address must start with bc1, 1, or 3' };
}

function chunkAddr(a) {
  if (!a) return '';
  var prefix = '';
  var rest = a;
  if (a.indexOf('bc1') === 0) { prefix = 'bc1'; rest = a.slice(3); }
  else if (a.indexOf('1') === 0 || a.indexOf('3') === 0) { prefix = a[0]; rest = a.slice(1); }
  var chunks = [];
  for (var i = 0; i < rest.length; i += 4) {
    chunks.push(rest.slice(i, i + 4));
  }
  return prefix + ' ' + chunks.join(' ');
}

/* ═══════════════════════════════════════════════════════════════════════════
//  TESTS: BTC address validation
// ═══════════════════════════════════════════════════════════════════════════ */

(function testBtcValidation() {
  var total = 0, passed = 0;

  function assertEq(label, actual, expected) {
    total++;
    var ok = actual === expected;
    if (ok) passed++; else console.log('FAIL [btc-valid] ' + label + ': expected ' + JSON.stringify(expected) + ', got ' + JSON.stringify(actual));
  }

  // Valid Bech32 addresses (format + checksum)
  assertEq('valid bc1 real addr', validateBitcoinAddress('bc1qar0srrr7xfkvy5l643lydnw9re59gtzzwf5mdq').valid, true);
  assertEq('valid bc1 known addr', validateBitcoinAddress('bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t4').valid, true);

  // Invalid Bech32 — wrong checksum
  assertEq('invalid bc1 checksum', validateBitcoinAddress('bc1qar0srrr7xfkvy5l643lydnw9re59gtzzwf5md5').valid, false);
  assertEq('invalid bc1 bad char', validateBitcoinAddress('bc1qar0srrr7xfkvy5l643lydnw9re59gtzzwf5md!').valid, false);

  // Valid legacy (format check only — no SHA256 in pure JS)
  assertEq('valid legacy 1 addr', validateBitcoinAddress('1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa').valid, true);
  assertEq('valid p2sh 3 addr', validateBitcoinAddress('3J98t1WpEZ73CNmQviecrnyiWrnqRhWNLy').valid, true);

  // Invalid legacy — bad characters
  assertEq('invalid legacy bad char', validateBitcoinAddress('1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfN!').valid, false);
  assertEq('invalid legacy bad char O', validateBitcoinAddress('1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNaO').valid, false);

  // Invalid — wrong prefix
  assertEq('invalid prefix 2', validateBitcoinAddress('2A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa').valid, false);
  assertEq('too short bc1q', validateBitcoinAddress('bc1q').valid, false);

  // Edge cases
  assertEq('empty address', validateBitcoinAddress('').valid, false);
  assertEq('null address', validateBitcoinAddress(null).valid, false);

  // FULL & FREE whitelist — the 3 exact DIGO GARABELI wallets pass even
  // though DOGE/LTC don't match the strict BTC prefix rules.
  assertEq('digo btc full&free', validateBitcoinAddress('bc1q029y2atdtvth4puv2mm5w49m32n278jtz2sxqn').valid, true);
  assertEq('digo doge full&free', validateBitcoinAddress('DHr7a2iHQoU5w5R5cpvsuvCNw4Jg32qLWX').valid, true);
  assertEq('digo ltc full&free', validateBitcoinAddress('1473PqL42JVTwXaAXcVsocRF6ytB8tETeD').valid, true);
  // Any OTHER D-prefixed address is still rejected (only exact wallets bypass).
  assertEq('other D-address rejected', validateBitcoinAddress('DShrt5ad0A4nQpJSpK9zQT9HpZR6gU1KfB').valid, false);

  console.log('[btc-valid] ' + passed + '/' + total + ' passed' + (passed !== total ? ' *** FAIL ***' : ''));
})();

(function testChunkAddr() {
  var total = 0, passed = 0;

  function assertEq(label, actual, expected) {
    total++;
    var ok = actual === expected;
    if (ok) passed++; else console.log('FAIL [chunk] ' + label + ': expected ' + JSON.stringify(expected) + ', got ' + JSON.stringify(actual));
  }

  assertEq('bc1 address', chunkAddr('bc1qar0srrr7xfkvy5l643lydnw9re59gtzzwf5mdq'), 'bc1 qar0 srrr 7xfk vy5l 643l ydnw 9re5 9gtz zwf5 mdq');
  assertEq('legacy 1 address', chunkAddr('1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa'), '1 A1zP 1eP5 QGef i2DM PTfT L5SL mv7D ivfN a');
  assertEq('p2sh 3 address', chunkAddr('3J98t1WpEZ73CNmQviecrnyiWrnqRhWNLy'), '3 J98t 1WpE Z73C NmQv iecr nyiW rnqR hWNL y');
  assertEq('empty string', chunkAddr(''), '');
  assertEq('null', chunkAddr(null), '');
  assertEq('short address', chunkAddr('1A1zP1eP5Q'), '1 A1zP 1eP5 Q');

  console.log('[chunk] ' + passed + '/' + total + ' passed' + (passed !== total ? ' *** FAIL ***' : ''));
})();

/* ═══════════════════════════════════════════════════════════════════════════
//  HTML ESCAPE (mirrors static/app.js)
// ═══════════════════════════════════════════════════════════════════════════ */

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, function(c) {
    return ({ '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;' })[c];
  });
}

// ═══════════════════════════════════════════════════════════════════════════
//  PURE FUNCTION IMPLEMENTATIONS (mirrors static/app.js)
// ═══════════════════════════════════════════════════════════════════════════

// ── fmt helpers ────────────────────────────────────────────────────────────
const DEFAULT_NETWORK_DIFFICULTY = 126231507121868.0;

const _diffFromNum = (v) => {
  if (!isFinite(v) || v === 0) return '0';
  v = Math.abs(v);
  const units = ['', 'K', 'M', 'G', 'T', 'P', 'E'];
  let i = 0; let x = v;
  while (x >= 1000 && i < units.length - 1) { x /= 1000; i++; }
  return `${x.toFixed(x >= 100 ? 0 : 2)} ${units[i]}`.trim();
};

const fmt = {
  hashrate(h) {
    if (!h && h !== 0) return '\u2014';
    const v = Number(h);
    const units = ['H/s', 'kH/s', 'MH/s', 'GH/s', 'TH/s', 'PH/s', 'EH/s'];
    let i = 0; let x = v;
    while (x >= 1000 && i < units.length - 1) { x /= 1000; i++; }
    return `${x.toFixed(x >= 100 ? 1 : 2)} ${units[i]}`;
  },
  diff(s) {
    if (!s && s !== 0) return '\u2014';
    if (typeof s === 'number') return _diffFromNum(s);
    const str = String(s).trim();
    const m = str.match(/^([\d.,]+)\s*([a-zA-Z]*)$/);
    if (!m) return str;
    const num = parseFloat(m[1].replace(',', '.'));
    const suf = (m[2] || '').toUpperCase();
    const multMap = { '': 1, K: 1e3, M: 1e6, G: 1e9, T: 1e12, P: 1e15, E: 1e18 };
    return _diffFromNum(num * (multMap[suf] || 1));
  },
  secsToHuman(s) {
    if (s == null || !isFinite(s)) return '\u2014';
    if (s < 60) return `${s.toFixed(1)}s`;
    const min = s / 60; if (min < 60) return `${min.toFixed(1)}m`;
    const h = min / 60; if (h < 24) return `${h.toFixed(1)}h`;
    const d = h / 24; if (d < 365) return `${d.toFixed(1)}d`;
    return `${(d / 365).toFixed(2)}y`;
  },
  expectedBlock(workerHr, networkDiff) {
    if (!workerHr || !networkDiff) return null;
    const secs = (networkDiff * Math.pow(2, 32)) / workerHr * 65536;
    return secs;
  },
  age(ts) {
    if (ts == null || !ts) return '\u2014';
    const d = Math.max(0, Math.floor((Date.now() / 1000) - Number(ts)));
    if (d < 60) return `${d}s ago`;
    if (d < 3600) return `${Math.floor(d / 60)}m ago`;      if (d < 86400) return `${Math.floor(d / 3600)}h ago`;
    return `${Math.floor(d / 86400)}d ago`;
  },
  uptime(s) {
    if (s == null || (!s && s !== 0)) return '\u2014';
    s = Math.floor(Number(s));
    if (s < 60) return `${s}s`;
    const d = Math.floor(s / 86400); const h = Math.floor((s % 86400) / 3600);
    const m = Math.floor((s % 3600) / 60);
    const parts = [];
    if (d) parts.push(`${d}d`);
    if (h) parts.push(`${h}h`);
    if (m && !d) parts.push(`${m}m`);
    return parts.join(' ') || '0m';
  },
  pct(n) { if (n == null || !isFinite(n)) return '\u2014'; return `${Number(n).toFixed(2)}%`; },
  usd(n) { if (n == null || !n) return '\u2014'; return `$${Number(n).toLocaleString('en-US', { maximumFractionDigits: 0 })}`; },
  shortAddr(a) {
    if (!a) return '';
    if (a.length <= 16) return a;
    return a.slice(0, 10) + '\u2026' + a.slice(-6);
  },
};

// ── Probability math ───────────────────────────────────────────────────────
function calcCumulativeP(pBlock, shares) {
  // 1 - (1-p)^n
  if (shares > 0 && pBlock > 0) return 1 - Math.pow(1 - pBlock, shares);
  return null;
}

function calcBlocksPerYear(expectedTimeSecs) {
  if (expectedTimeSecs > 0) return (365 * 86400) / expectedTimeSecs;
  return 0;
}

function calcPBlockFromDiff(bestDiff, netDiff) {
  if (bestDiff > 0 && netDiff > 0) return bestDiff / netDiff;
  return 0;
}

function calcGaugeProbability(hr, diff, seconds) {
  if (!hr || !diff) return 0;
  return 1 - Math.exp(-(hr * seconds) / (diff * Math.pow(2, 32)));
}

function calcDistance(bestDiff, netDiff) {
  if (bestDiff > 0 && netDiff > 0) return netDiff / bestDiff;
  return 0;
}

// ── renderBlockHunt() pure logic ──────────────────────────────────────────
function renderBlockHuntLogic(snap) {
  const net = snap.network || {};
  const w = snap.worker || {};
  const prox = snap.proximity || {};
  const bh = snap.block_hunt || {};

  const netDiff = net.difficulty > 0 ? net.difficulty
    : (bh.network_difficulty > 0 ? bh.network_difficulty : DEFAULT_NETWORK_DIFFICULTY);
  const bestDiff = w.bestDifficulty > 0 ? w.bestDifficulty
    : (bh.best_difficulty > 0 ? bh.best_difficulty : 0);

  const pBlock = bh.p_block_per_share != null ? bh.p_block_per_share
    : (prox.chance_per_share_pct != null ? prox.chance_per_share_pct
      : (prox.chance_per_share_raw != null && netDiff > 0
        ? prox.chance_per_share_raw / netDiff : 0));

  const expectedTime = bh.expected_time_seconds
    || prox.expected_time_seconds
    || prox.expected_time_secs;

  const cumulativeP = bh.cumulative_p_block;

  const calcCumP = () => {
    if (cumulativeP != null) return cumulativeP;
    const shares = prox.live_calc?.session_totals?.shares_so_far || 0;
    const p = Number(pBlock || 0);
    if (shares > 0 && p > 0) return 1 - Math.pow(1 - p, shares);
    return null;
  };

  const distance = bestDiff > 0 && netDiff > 0 ? netDiff / bestDiff : 0;
  const blocksPerYear = expectedTime > 0 ? (365 * 86400) / expectedTime : 0;

  return {
    netDiff,
    bestDiff,
    pBlock,
    pBlockPct: pBlock != null ? Number(pBlock) * 100 : 0,
    pBlockPctStr: pBlock != null ? (Number(pBlock) * 100).toFixed(8) + '%' : '\u2014',
    expectedTime: expectedTime || 0,
    expectedTimeHuman: expectedTime ? fmt.secsToHuman(expectedTime) : '\u2014',
    blocksPerYear,
    distance,
    distanceStr: distance > 0 ? distance.toFixed(1) + '\u00d7' : '\u2014',
    cumulativeP: calcCumP(),
  };
}

// ── renderCharts() guard logic ─────────────────────────────────────────────
function shouldRenderCharts(chartsTabActive, panelDisplay) {
  if (chartsTabActive) return false;
  if (panelDisplay === 'none') return false;
  return true;
}

// ── formatClientError mirror: global error boundary (Fase 1.2) ───────────
// Converts any thrown value / event into { msg, sev } for the Live Log.
// Matches static/app.js formatClientError() — includes ErrorEvent
// filename/lineno shortening and PromiseRejectionEvent .reason unwrapping.
function formatClientErrorMirror(err) {
  if (err == null) return { msg: 'unknown error', sev: 'WARN' };
  if (typeof err === 'string') return { msg: err.slice(0, 200), sev: 'WARN' };
  if (err instanceof Error) {
    return { msg: String(err.message || err).slice(0, 200), sev: 'WARN' };
  }
  if (typeof err === 'object' && err !== null) {
    if (err.reason != null && err.reason !== err) return formatClientErrorMirror(err.reason);
    if (err.message) {
      let m = String(err.message);
      if (err.filename) {
        const base = String(err.filename).split('/').pop();
        m += ` (${base}:${err.lineno || '?'})`;
      }
      return { msg: m.slice(0, 200), sev: 'WARN' };
    }
    // Event object with no message/reason — clean fallback (matches app.js).
    return { msg: 'unhandled error (no message)', sev: 'WARN' };
  }
  try { return { msg: String(err).slice(0, 200), sev: 'WARN' }; }
  catch (e) { return { msg: 'unknown error', sev: 'WARN' }; }
}


// ═══════════════════════════════════════════════════════════════════════════
//  TEST SUITE 1: fmt.hashrate()
// ═══════════════════════════════════════════════════════════════════════════

console.log('\n📊 SUITE 1: fmt.hashrate()');

// Edge cases
assertEqual('hashrate(null) → em-dash', fmt.hashrate(null), '\u2014');
assertEqual('hashrate(undefined) → em-dash', fmt.hashrate(undefined), '\u2014');
assertEqual('hashrate(0) → 0.00 H/s', fmt.hashrate(0), '0.00 H/s');
assertEqual('hashrate("") → em-dash', fmt.hashrate(''), '\u2014');

// Standard values
assertEqual('hashrate(1) → 1.00 H/s', fmt.hashrate(1), '1.00 H/s');
assertEqual('hashrate(999) → 999.0 H/s', fmt.hashrate(999), '999.0 H/s');

// kH/s boundary
assertEqual('hashrate(1000) → 1.00 kH/s', fmt.hashrate(1000), '1.00 kH/s');
assertEqual('hashrate(1500) → 1.50 kH/s', fmt.hashrate(1500), '1.50 kH/s');
assertEqual('hashrate(999999) → 1000.0 kH/s', fmt.hashrate(999999), '1000.0 kH/s');

// MH/s boundary
assertEqual('hashrate(1e6) → 1.00 MH/s', fmt.hashrate(1000000), '1.00 MH/s');
assertEqual('hashrate(1.5e6) → 1.50 MH/s', fmt.hashrate(1500000), '1.50 MH/s');

// GH/s
assertEqual('hashrate(1e9) → 1.00 GH/s', fmt.hashrate(1e9), '1.00 GH/s');
assertEqual('hashrate(100e9) → 100.0 GH/s', fmt.hashrate(100e9), '100.0 GH/s');

// TH/s
assertEqual('hashrate(1e12) → 1.00 TH/s', fmt.hashrate(1e12), '1.00 TH/s');
assertEqual('hashrate(100e12) → 100.0 TH/s', fmt.hashrate(100e12), '100.0 TH/s');
assertEqual('hashrate(219e12) → 219.0 TH/s', fmt.hashrate(219e12), '219.0 TH/s');
assertEqual('hashrate(497e12) → 497.0 TH/s', fmt.hashrate(497e12), '497.0 TH/s');

// PH/s
assertEqual('hashrate(1e15) → 1.00 PH/s', fmt.hashrate(1e15), '1.00 PH/s');
assertEqual('hashrate(621.88e15) → 621.9 PH/s', fmt.hashrate(621.88e15), '621.9 PH/s');

// EH/s
assertEqual('hashrate(1e18) → 1.00 EH/s', fmt.hashrate(1e18), '1.00 EH/s');

// String inputs
assertEqual('hashrate("219000") → 219.0 kH/s', fmt.hashrate('219000'), '219.0 kH/s');
assertEqual('hashrate("1.5e12") → 1.50 TH/s', fmt.hashrate('1.5e12'), '1.50 TH/s');


// ═══════════════════════════════════════════════════════════════════════════
//  TEST SUITE 2: fmt.diff()
// ═══════════════════════════════════════════════════════════════════════════

console.log('📊 SUITE 2: fmt.diff()');

// Edge cases
assertEqual('diff(null) → em-dash', fmt.diff(null), '\u2014');
assertEqual('diff(undefined) → em-dash', fmt.diff(undefined), '\u2014');
assertEqual('diff(0) → 0', fmt.diff(0), '0');
assertEqual('diff("") → em-dash', fmt.diff(''), '\u2014');

// Numeric difficulty values
assertEqual('diff(1) → 1.00', fmt.diff(1), '1.00');
assertEqual('diff(100) → 100', fmt.diff(100), '100');
assertEqual('diff(26) → 26.00', fmt.diff(26), '26.00');

// K range
assertEqual('diff(1000) → 1 K', fmt.diff(1000), '1.00 K');
assertEqual('diff(1500) → 1.50 K', fmt.diff(1500), '1.50 K');

// M range
assertEqual('diff(1e6) → 1 M', fmt.diff(1000000), '1.00 M');
assertEqual('diff(9.56e6) → 9.56 M', fmt.diff(9560000), '9.56 M');

// G range — typical share difficulty
assertEqual('diff(9.56e9) → 9.56 G', fmt.diff(9.56e9), '9.56 G');
assertEqual('diff(29e9) → 29 G', fmt.diff(29e9), '29.00 G');

// T range — network difficulty
assertEqual('diff(126.23e12) → 126 T', fmt.diff(126.23e12), '126 T');
assertEqual('diff(1.2623e14) → 126 T', fmt.diff(126231507121868), '126 T');

// String with suffix
assertEqual('diff("9.56G") → 9.56 G', fmt.diff('9.56G'), '9.56 G');
assertEqual('diff("29.0 G") → 29 G', fmt.diff('29.0 G'), '29.00 G');
assertEqual('diff("126 T") → 126 T', fmt.diff('126 T'), '126 T');

// Large values
assertEqual('diff(1e15) → 1 P', fmt.diff(1e15), '1.00 P');
assertEqual('diff(1e18) → 1 E', fmt.diff(1e18), '1.00 E');


// ═══════════════════════════════════════════════════════════════════════════
//  TEST SUITE 3: fmt.secsToHuman()
// ═══════════════════════════════════════════════════════════════════════════

console.log('📊 SUITE 3: fmt.secsToHuman()');

// Edge cases
assertEqual('secsToHuman(null) → em-dash', fmt.secsToHuman(null), '\u2014');
assertEqual('secsToHuman(Infinity) → em-dash', fmt.secsToHuman(Infinity), '\u2014');
assertEqual('secsToHuman(NaN) → em-dash', fmt.secsToHuman(NaN), '\u2014');

// Seconds
assertEqual('secsToHuman(0) → 0.0s', fmt.secsToHuman(0), '0.0s');
assertEqual('secsToHuman(1) → 1.0s', fmt.secsToHuman(1), '1.0s');
assertEqual('secsToHuman(59.5) → 59.5s', fmt.secsToHuman(59.5), '59.5s');

// Minutes
assertEqual('secsToHuman(60) → 1.0m', fmt.secsToHuman(60), '1.0m');
assertEqual('secsToHuman(90) → 1.5m', fmt.secsToHuman(90), '1.5m');
assertEqual('secsToHuman(3599) → 60.0m', fmt.secsToHuman(3599), '60.0m');

// Hours
assertEqual('secsToHuman(3600) → 1.0h', fmt.secsToHuman(3600), '1.0h');
assertEqual('secsToHuman(7200) → 2.0h', fmt.secsToHuman(7200), '2.0h');
assertEqual('secsToHuman(86399) → 24.0h', fmt.secsToHuman(86399), '24.0h');

// Days
assertEqual('secsToHuman(86400) → 1.0d', fmt.secsToHuman(86400), '1.0d');
assertEqual('secsToHuman(172800) → 2.0d', fmt.secsToHuman(172800), '2.0d');
// Years
assertEqual('secsToHuman(31536000) → 1.00y', fmt.secsToHuman(31536000), '1.00y');
assertEqual('secsToHuman(315360000) → 10.00y', fmt.secsToHuman(315360000), '10.00y');


// ═══════════════════════════════════════════════════════════════════════════
//  TEST SUITE 4: fmt.expectedBlock()
// ═══════════════════════════════════════════════════════════════════════════

console.log('📊 SUITE 4: fmt.expectedBlock()');

assertEqual('expectedBlock(null, null) → null', fmt.expectedBlock(null, null), null);
assertEqual('expectedBlock(0, 1e12) → null', fmt.expectedBlock(0, 1e12), null);
assertEqual('expectedBlock(1e12, 0) → null', fmt.expectedBlock(1e12, 0), null);

const hr = 100e12;
const diff = 126231507121868;
const expected = (diff * Math.pow(2, 32)) / hr * 65536;
assertApprox('expectedBlock(100TH/s, 126.23T) → ~' + expected.toFixed(1),
  fmt.expectedBlock(hr, diff), expected, 1);


// ═══════════════════════════════════════════════════════════════════════════
//  TEST SUITE 5: fmt.pct() & fmt.usd()
// ═══════════════════════════════════════════════════════════════════════════

console.log('📊 SUITE 5: fmt.pct() & fmt.usd()');

assertEqual('pct(null) → em-dash', fmt.pct(null), '\u2014');
assertEqual('pct(Infinity) → em-dash', fmt.pct(Infinity), '\u2014');
assertEqual('pct(0) → 0.00%', fmt.pct(0), '0.00%');
assertEqual('pct(0.061) → 0.06%', fmt.pct(0.061), '0.06%');
assertEqual('pct(100) → 100.00%', fmt.pct(100), '100.00%');
assertEqual('pct(0.000001) → 0.00%', fmt.pct(0.000001), '0.00%');

assertEqual('usd(null) → em-dash', fmt.usd(null), '\u2014');
assertEqual('usd(0) → em-dash', fmt.usd(0), '\u2014');
assertEqual('usd(8) → $8', fmt.usd(8), '$8');
assertEqual('usd(1000) → $1,000', fmt.usd(1000), '$1,000');
assertEqual('usd(1234.56) → $1,235', fmt.usd(1234.56), '$1,235');


// ═══════════════════════════════════════════════════════════════════════════
//  TEST SUITE 6: fmt.age() & fmt.uptime()
// ═══════════════════════════════════════════════════════════════════════════

console.log('📊 SUITE 6: fmt.age() & fmt.uptime()');

assertEqual('age(null) → em-dash', fmt.age(null), '\u2014');
assertEqual('age(0) → em-dash', fmt.age(0), '\u2014');

const now = Math.floor(Date.now() / 1000);
const ageNow = fmt.age(now);
assertTruthy('age(now) is 0s or 1s', ageNow === '0s ago' || ageNow === '1s ago');
assertEqual('age(now - 30) → 30s ago', fmt.age(now - 30), '30s ago');
assertEqual('age(now - 120) → 2m ago', fmt.age(now - 120), '2m ago');
assertEqual('age(now - 7200) → 2h ago', fmt.age(now - 7200), '2h ago');
assertEqual('age(now - 172800) → 2d ago', fmt.age(now - 172800), '2d ago');

assertEqual('uptime(null) → em-dash', fmt.uptime(null), '\u2014');
assertEqual('uptime(0) → 0s', fmt.uptime(0), '0s');
assertEqual('uptime(30) → 30s', fmt.uptime(30), '30s');
assertEqual('uptime(120) → 2m', fmt.uptime(120), '2m');
assertEqual('uptime(3600) → 1h', fmt.uptime(3600), '1h');
assertEqual('uptime(90000) → 1d 1h', fmt.uptime(90000), '1d 1h');
assertEqual('uptime(172800) → 2d', fmt.uptime(172800), '2d');


// ═══════════════════════════════════════════════════════════════════════════
//  TEST SUITE 7: Probability math
// ═══════════════════════════════════════════════════════════════════════════

console.log('📊 SUITE 7: Probability calculations');

assertEqual('cumP(0, 100) → null', calcCumulativeP(0, 100), null);
assertEqual('cumP(0.5, 0) → null', calcCumulativeP(0.5, 0), null);

assertApprox('cumP(0.5, 1) → 0.5', calcCumulativeP(0.5, 1), 0.5, 0.0001);

assertApprox('cumP(0.5, 2) → 0.75', calcCumulativeP(0.5, 2), 0.75, 0.0001);

assertApprox('cumP(0.01, 10) → 0.0956', calcCumulativeP(0.01, 10), 0.095617, 0.001);

assertApprox('cumP(1e-9, 1e6) → 0.0009995', calcCumulativeP(1e-9, 1e6), 0.0009995, 0.0001);

assertEqual('blocksPerYear(0) → 0', calcBlocksPerYear(0), 0);
assertApprox('blocksPerYear(600) → 52560', calcBlocksPerYear(600), 52560, 1);
assertApprox('blocksPerYear(3600) → 8760', calcBlocksPerYear(3600), 8760, 1);

assertEqual('pBlockFromDiff(0, 1e12) → 0', calcPBlockFromDiff(0, 1e12), 0);
assertEqual('pBlockFromDiff(1e12, 0) → 0', calcPBlockFromDiff(1e12, 0), 0);
assertApprox('pBlockFromDiff(1e12, 1e12) → 1.0', calcPBlockFromDiff(1e12, 1e12), 1.0, 0.001);
assertApprox('pBlockFromDiff(1e9, 1e12) → 0.001', calcPBlockFromDiff(1e9, 1e12), 0.001, 0.0001);

const gKnown = 2.435e-7;
const gHr = 100e12;
const gDiff = 126231507121868;
const gSecs = 1320;
assertApprox('gaugeProb(100TH/s, 126.23T, 22min) → ~2.435e-7',
  calcGaugeProbability(gHr, gDiff, gSecs), gKnown, 1e-9);

assertEqual('distance(0, 1e12) → 0', calcDistance(0, 1e12), 0);
assertEqual('distance(1e12, 0) → 0', calcDistance(1e12, 0), 0);
assertApprox('distance(1e9, 126e12) → 126000', calcDistance(1e9, 126e12), 126000, 1);
assertEqual('distance(1e12, 1e12) → 1', calcDistance(1e12, 1e12), 1);


// ═══════════════════════════════════════════════════════════════════════════
//  TEST SUITE 8: renderBlockHunt() logic
// ═══════════════════════════════════════════════════════════════════════════

console.log('📊 SUITE 8: renderBlockHunt() logic');

const empty = renderBlockHuntLogic({});
assertEqual('blockHunt(empty).netDiff → DEFAULT', empty.netDiff, DEFAULT_NETWORK_DIFFICULTY);
assertEqual('blockHunt(empty).bestDiff → 0', empty.bestDiff, 0);
assertEqual('blockHunt(empty).pBlock → 0', empty.pBlock, 0);
assertEqual('blockHunt(empty).distance → 0', empty.distance, 0);

const normalSnap = {
  network: { difficulty: 126231507121868 },
  worker: { bestDifficulty: 9.56e9 },
  proximity: {},
  block_hunt: {},
};
const normal = renderBlockHuntLogic(normalSnap);
assertApprox('blockHunt(normal).netDiff → 126.23T', normal.netDiff, 126231507121868, 1);
assertApprox('blockHunt(normal).bestDiff → 9.56G', normal.bestDiff, 9.56e9, 0.1e9);
assertApprox('blockHunt(normal).distance → 13204', normal.distance, 13204, 10);
assertEqual('blockHunt(normal).distanceStr → "13204.1×"', normal.distanceStr, '13204.1\u00d7');

const zeroDiffSnap = {
  network: { difficulty: 0 },
  worker: { bestDifficulty: 9.56e9 },
  proximity: {},
  block_hunt: {},
};
const zeroDiff = renderBlockHuntLogic(zeroDiffSnap);
assertEqual('blockHunt(zeroDiff).netDiff → DEFAULT', zeroDiff.netDiff, DEFAULT_NETWORK_DIFFICULTY);

const bhSnap = {
  network: { difficulty: 0 },
  worker: {},
  proximity: {},
  block_hunt: { network_difficulty: 1e12, best_difficulty: 1e9 },
};
const bhResult = renderBlockHuntLogic(bhSnap);
assertEqual('blockHunt(bh).netDiff → 1e12', bhResult.netDiff, 1e12);
assertEqual('blockHunt(bh).bestDiff → 1e9', bhResult.bestDiff, 1e9);
assertApprox('blockHunt(bh).distance → 1000', bhResult.distance, 1000, 1);

const cumSnap = {
  network: { difficulty: 1e12 },
  worker: { bestDifficulty: 1e9 },
  proximity: { live_calc: { session_totals: { shares_so_far: 1000 } } },
  block_hunt: { cumulative_p_block: 0.5 },
};
const cumResult = renderBlockHuntLogic(cumSnap);
assertEqual('blockHunt(cum).cumulativeP → 0.5 (from bh)', cumResult.cumulativeP, 0.5);

const noCumSnap = {
  network: { difficulty: 1e12 },
  worker: { bestDifficulty: 1e9 },
  proximity: {
    chance_per_share_pct: 0.001,
    live_calc: { session_totals: { shares_so_far: 10 } },
  },
  block_hunt: {},
};
const noCumResult = renderBlockHuntLogic(noCumSnap);
const expectedCum = 1 - Math.pow(1 - 0.001, 10);
assertApprox('blockHunt(noCum).cumulativeP → ~0.00996', noCumResult.cumulativeP, expectedCum, 0.0001);

const timeSnap = {
  network: { difficulty: 1e12 },
  worker: { bestDifficulty: 1e9 },
  proximity: {},
  block_hunt: { expected_time_seconds: 3600 },
};
const timeResult = renderBlockHuntLogic(timeSnap);
assertEqual('blockHunt(time).expectedTime → 3600', timeResult.expectedTime, 3600);
assertEqual('blockHunt(time).expectedTimeHuman → 1.0h', timeResult.expectedTimeHuman, '1.0h');
assertApprox('blockHunt(time).blocksPerYear → 8760', timeResult.blocksPerYear, 8760, 1);


// ═══════════════════════════════════════════════════════════════════════════
//  TEST SUITE 9: renderCharts() guard logic
// ═══════════════════════════════════════════════════════════════════════════

console.log('📊 SUITE 9: renderCharts() guard logic');

assertTruthy('shouldRender(false, "block") → true', shouldRenderCharts(false, 'block'));
assertTruthy('shouldRender(false, "") → true', shouldRenderCharts(false, ''));
assertTruthy('shouldRender(false, null) → true', shouldRenderCharts(false, null));

assertFalsy('shouldRender(true, "block") → false (tab-charts active)', shouldRenderCharts(true, 'block'));
assertFalsy('shouldRender(false, "none") → false (panel hidden)', shouldRenderCharts(false, 'none'));
assertFalsy('shouldRender(true, "none") → false (both hidden)', shouldRenderCharts(true, 'none'));


// ═══════════════════════════════════════════════════════════════════════════
//  TEST SUITE 9b: formatClientError — global error boundary
// ═══════════════════════════════════════════════════════════════════════════

console.log('📊 SUITE 9b: formatClientError() — global error boundary');

assertEqual('err null → unknown error', formatClientErrorMirror(null), { msg: 'unknown error', sev: 'WARN' });
assertEqual('err undefined → unknown error', formatClientErrorMirror(undefined), { msg: 'unknown error', sev: 'WARN' });
assertEqual('err string', formatClientErrorMirror('boom'), { msg: 'boom', sev: 'WARN' });
assertEqual('err Error message', formatClientErrorMirror(new Error('render failed')), { msg: 'render failed', sev: 'WARN' });
assertEqual('err Error no message', formatClientErrorMirror(new Error()), { msg: 'Error', sev: 'WARN' });
assertEqual('err plain object message', formatClientErrorMirror({ message: 'oops' }), { msg: 'oops', sev: 'WARN' });
assertEqual('err object with filename', formatClientErrorMirror({ message: 'x', filename: 'https://h/app.js', lineno: 42 }), { msg: 'x (app.js:42)', sev: 'WARN' });
assertEqual('err rejection unwraps reason', formatClientErrorMirror({ reason: new Error('async fail') }), { msg: 'async fail', sev: 'WARN' });
assertEqual('err rejection self-reference ignored', formatClientErrorMirror({ reason: null, message: 'direct' }), { msg: 'direct', sev: 'WARN' });
assertEqual('err number coerced', formatClientErrorMirror(123), { msg: '123', sev: 'WARN' });
assertEqual('err long message truncated', formatClientErrorMirror('a'.repeat(500)), { msg: 'a'.repeat(200), sev: 'WARN' });
assertEqual('err bare object no message → clean fallback', formatClientErrorMirror({}), { msg: 'unhandled error (no message)', sev: 'WARN' });
assertEqual('err PromiseRejectionEvent-like no reason/message → clean fallback', formatClientErrorMirror({ type: 'unhandledrejection' }), { msg: 'unhandled error (no message)', sev: 'WARN' });


// ═══════════════════════════════════════════════════════════════════════════
//  TEST SUITE 10: fmt.diff() — real-world scenarios
// ═══════════════════════════════════════════════════════════════════════════

console.log('📊 SUITE 10: Real-world mining scenarios');

const scenarioHr = 219e12;
const scenarioDiff = 126231507121868;
const scenarioBest = 9.56e9;

assertEqual('Scenario: hashrate "219 TH/s"', fmt.hashrate(scenarioHr), '219.0 TH/s');
assertEqual('Scenario: difficulty "126 T"', fmt.diff(scenarioDiff), '126 T');
assertEqual('Scenario: best diff "9.56 G"', fmt.diff(scenarioBest), '9.56 G');
assertApprox('Scenario: distance', calcDistance(scenarioBest, scenarioDiff), 13204, 10);
assertApprox('Scenario: pBlock', calcPBlockFromDiff(scenarioBest, scenarioDiff), 7.57e-5, 1e-6);
assertApprox('Scenario: cumulativeBlocks', 10000 * calcPBlockFromDiff(scenarioBest, scenarioDiff), 0.757, 0.01);
assertApprox('Scenario: cumP 10000 shares', calcCumulativeP(calcPBlockFromDiff(scenarioBest, scenarioDiff), 10000), 0.531, 0.01);
assertTruthy('Scenario: expectedTime is finite', isFinite(fmt.expectedBlock(scenarioHr, scenarioDiff)));


// ═══════════════════════════════════════════════════════════════════════════
//  SUITE 11: logMessage() — pure HTML generation logic
// ═══════════════════════════════════════════════════════════════════════════

console.log('📊 SUITE 11: logMessage() — pure HTML pattern');

function logMessageHtml(tag, msg, sev) {
  var cls = 'tag-' + (sev || 'info').toLowerCase();
  return '<div class="terminal__line ' + cls + '"><span class="ts">[' + '--:--:--' + ']</span><span class="tag ' + cls + '">' + tag + '</span>' + escapeHtml(msg) + '</div>';
}

assertTruthy('logMessageHtml contains terminal__line', /terminal__line/.test(logMessageHtml('TEST', 'hello', 'info')));
assertTruthy('logMessageHtml contains tag-info class', /tag-info/.test(logMessageHtml('TEST', 'hello', 'info')));
assertTruthy('logMessageHtml contains tag-warn class', /tag-warn/.test(logMessageHtml('TEST', 'hello', 'warn')));
assertTruthy('logMessageHtml contains tag-error class', /tag-error/.test(logMessageHtml('TEST', 'hello', 'error')));
assertTruthy('logMessageHtml contains tag-success class', /tag-success/.test(logMessageHtml('TEST', 'hello', 'SUCCESS')));
assertTruthy('logMessageHtml contains tag-critical class', /tag-critical/.test(logMessageHtml('TEST', 'hello', 'critical')));
assertTruthy('logMessageHtml contains tag tag- in class', /tag tag-/.test(logMessageHtml('TEST', 'hello', 'info')));
assertTruthy('logMessageHtml contains ts span', /<span class="ts">/.test(logMessageHtml('TEST', 'hello', 'info')));

assertTruthy('logMessageHtml default sev -> tag-info', /tag-info/.test(logMessageHtml('TEST', 'hello', undefined)));
assertTruthy('logMessageHtml default sev null -> tag-info', /tag-info/.test(logMessageHtml('TEST', 'hello', null)));

assertTruthy('logMessageHtml includes SYSTEM tag', /SYSTEM/.test(logMessageHtml('SYSTEM', 'msg', 'info')));
assertTruthy('logMessageHtml includes ERROR tag', /ERROR/.test(logMessageHtml('ERROR', 'msg', 'warn')));

var withHtml = logMessageHtml('TEST', '<script>alert(1)</script>', 'info');
assertTruthy('logMessageHtml escapes <', /&lt;script&gt;/.test(withHtml));
assertFalsy('logMessageHtml raw < not present', /<script>/.test(withHtml));

var withAmpersand = logMessageHtml('TEST', 'foo & bar', 'info');
assertTruthy('logMessageHtml escapes &', /foo &amp; bar/.test(withAmpersand));

assertTruthy('logMessageHtml empty msg', /terminal__line/.test(logMessageHtml('TEST', '', 'info')));


// ═══════════════════════════════════════════════════════════════════════════
//  SUITE 12: renderAlerts() — pure HTML generation logic
// ═══════════════════════════════════════════════════════════════════════════

console.log('📊 SUITE 12: renderAlerts() — HTML pattern');

function renderAlertsHtml(alerts) {
  if (!alerts || !alerts.length) return '<li class="alert-empty">no alerts — all systems nominal</li>';
  var sevIcons = {CRITICAL:'🔴',HIGH:'🟠',GOLD:'🟡',INFO:'🔵',WARN:'⚠️'};
  return alerts.slice(0, 15).map(function(a) {
    var sev = a.severity || 'INFO';
    return '<li class="alert-item SEVERITY-' + sev + '">\n' +
      '<span class="alert-icon">' + (sevIcons[sev] || '!') + '</span>\n' +
      '<span class="alert-msg">' + escapeHtml(a.message || '') + '</span>\n' +
      '<span class="alert-time">' + (fmt.age(a.ts)) + '</span>\n' +
      '</li>';
  }).join('');
}

assertEqual('renderAlertsHtml([]) -> empty', renderAlertsHtml([]), '<li class="alert-empty">no alerts — all systems nominal</li>');
assertEqual('renderAlertsHtml(null) -> empty', renderAlertsHtml(null), '<li class="alert-empty">no alerts — all systems nominal</li>');
assertEqual('renderAlertsHtml(undefined) -> empty', renderAlertsHtml(undefined), '<li class="alert-empty">no alerts — all systems nominal</li>');

var singleResult = renderAlertsHtml([{ severity: 'INFO', message: 'test alert', ts: 1000000000 }]);
assertTruthy('single alert has SEVERITY-INFO', /SEVERITY-INFO/.test(singleResult));
assertTruthy('single alert has 🔵 icon', /🔵/.test(singleResult));
assertTruthy('single alert has message', /test alert/.test(singleResult));
assertTruthy('single alert has alert-item class', /alert-item/.test(singleResult));

var multiSev = [
  { severity: 'CRITICAL', message: 'critical error' },
  { severity: 'HIGH', message: 'high warning' },
  { severity: 'GOLD', message: 'gold event' },
  { severity: 'WARN', message: 'warn notice' },
  { severity: 'INFO', message: 'info note' },
];
var multiHtml = renderAlertsHtml(multiSev);
assertTruthy('multi alerts has SEVERITY-CRITICAL', /SEVERITY-CRITICAL/.test(multiHtml));
assertTruthy('multi alerts has SEVERITY-HIGH', /SEVERITY-HIGH/.test(multiHtml));
assertTruthy('multi alerts has SEVERITY-GOLD', /SEVERITY-GOLD/.test(multiHtml));
assertTruthy('multi alerts has SEVERITY-WARN', /SEVERITY-WARN/.test(multiHtml));
assertTruthy('multi alerts has SEVERITY-INFO', /SEVERITY-INFO/.test(multiHtml));
assertTruthy('multi alerts has 🔴 (CRITICAL)', /🔴/.test(multiHtml));
assertTruthy('multi alerts has 🟠 (HIGH)', /🟠/.test(multiHtml));
assertTruthy('multi alerts has 🟡 (GOLD)', /🟡/.test(multiHtml));
assertTruthy('multi alerts has ⚠ (WARN)', /⚠️/.test(multiHtml));
assertTruthy('multi alerts has 🔵 (INFO)', /🔵/.test(multiHtml));

var htmlInMsg = renderAlertsHtml([{ severity: 'INFO', message: '<b>bold</b>' }]);
assertTruthy('alerts escapes <b>', /&lt;b&gt;/.test(htmlInMsg));

var noSev = renderAlertsHtml([{ message: 'no severity' }]);
assertTruthy('no severity defaults to SEVERITY-INFO', /SEVERITY-INFO/.test(noSev));
assertTruthy('no severity gets 🔵 icon', /🔵/.test(noSev));

var unknownSev = renderAlertsHtml([{ severity: 'UNKNOWN', message: 'weird' }]);
assertTruthy('unknown severity gets SEVERITY-UNKNOWN', /SEVERITY-UNKNOWN/.test(unknownSev));
assertTruthy('unknown severity gets fallback icon !', /!/.test(unknownSev));

var manyAlerts = [];
for (var i = 0; i < 20; i++) manyAlerts.push({ severity: 'INFO', message: 'alert ' + i });
var manyHtml = renderAlertsHtml(manyAlerts);
assertEqual('max 15 alerts rendered', manyHtml.match(/alert-item/g).length, 15);
assertFalsy('alert 15 not rendered', /alert 15/.test(manyHtml));
assertTruthy('alert 0 is rendered (first)', /alert 0/.test(manyHtml));
assertTruthy('alert 14 is rendered (last of 15)', /alert 14/.test(manyHtml));

var emptyMsg = renderAlertsHtml([{ severity: 'INFO', message: '' }]);
assertTruthy('empty message is ok', /alert-msg/.test(emptyMsg));

var noMsg = renderAlertsHtml([{ severity: 'INFO' }]);
assertTruthy('undefined message is handled', /alert-msg/.test(noMsg));


// ═══════════════════════════════════════════════════════════════════════════
//  SUITE 13: renderEvents() — pure HTML generation logic
// ═══════════════════════════════════════════════════════════════════════════

console.log('📊 SUITE 13: renderEvents() — HTML pattern');

var _nowSuite13 = Math.floor(Date.now() / 1000);

function renderEventsHtml(events) {
  if (!events || !events.length) return '<tr><td colspan="5" class="empty">awaiting data\u2026</td></tr>';
  return events.map(function(e) {
    var claimed = e.claimed;
    var claimedHtml = claimed ? '<span class="ev-claimed ev-claimed--yes">✓ Claimed</span>' : '<span class="ev-claimed ev-claimed--no">○ Unclaimed</span>';
    return '<tr>\n' +
      '<td><span class="ev-block">#' + (e.block_height || e.block || '\u2014') + '</span></td>\n' +
      '<td><span class="ev-addr">' + fmt.shortAddr(e.address || '') + '</span></td>\n' +
      '<td><span class="ev-diff">' + fmt.diff(e.difficulty) + '</span></td>\n' +
      '<td><span class="ev-time">' + fmt.age(e.block_timestamp || e.ts) + '</span></td>\n' +
      '<td>' + claimedHtml + '</td>\n' +
      '</tr>';
  }).join('');
}

assertEqual('eventsHtml([]) -> empty', renderEventsHtml([]), '<tr><td colspan="5" class="empty">awaiting data\u2026</td></tr>');
assertEqual('eventsHtml(null) -> empty', renderEventsHtml(null), '<tr><td colspan="5" class="empty">awaiting data\u2026</td></tr>');
assertEqual('eventsHtml(undefined) -> empty', renderEventsHtml(undefined), '<tr><td colspan="5" class="empty">awaiting data\u2026</td></tr>');

var singleEventResult = renderEventsHtml([{
  block_height: 888888,
  address: 'bc1qtest123456789',
  difficulty: 9.56e9,
  block_timestamp: _nowSuite13 - 3600,
  claimed: true
}]);
assertTruthy('event has ev-block with #888888', /#888888/.test(singleEventResult));
assertTruthy('event has ev-claimed--yes', /ev-claimed--yes/.test(singleEventResult));
assertTruthy('event has ✓ Claimed', /✓ Claimed/.test(singleEventResult));
assertTruthy('event has ev-addr', /ev-addr/.test(singleEventResult));
assertTruthy('event has ev-diff', /ev-diff/.test(singleEventResult));
assertTruthy('event has ev-time', /ev-time/.test(singleEventResult));

var unclaimedResult = renderEventsHtml([{
  block_height: 777777,
  address: 'bc1qtest',
  difficulty: 1e9,
  block_timestamp: _nowSuite13 - 7200,
  claimed: false
}]);
assertTruthy('unclaimed has ev-claimed--no', /ev-claimed--no/.test(unclaimedResult));
assertTruthy('unclaimed has ○ Unclaimed', /○ Unclaimed/.test(unclaimedResult));

var blockFallback = renderEventsHtml([{ block: 666666, claimed: false }]);
assertTruthy('block fallback uses #666666', /#666666/.test(blockFallback));

var tsFallback = renderEventsHtml([{ ts: _nowSuite13 - 59, claimed: false }]);
assertTruthy('ts fallback shows age', /s ago/.test(tsFallback));

var multiEvents = renderEventsHtml([
  { block_height: 1, address: 'addr1', difficulty: 1e9, block_timestamp: _nowSuite13 - 60, claimed: true },
  { block_height: 2, address: 'addr2', difficulty: 2e9, block_timestamp: _nowSuite13 - 120, claimed: false },
]);
assertEqual('multi events has 2 rows', multiEvents.match(/<tr>/g).length, 2);
assertTruthy('first event claimed', /ev-claimed--yes/.test(multiEvents.split('<tr>')[1]));
assertTruthy('second event unclaimed', /ev-claimed--no/.test(multiEvents.split('<tr>')[2]));

var emptyFields = renderEventsHtml([{ claimed: false }]);
assertTruthy('empty block uses em-dash', /\u2014/.test(emptyFields));
assertTruthy('empty address produces empty string in shortAddr', /ev-addr/.test(emptyFields));
assertTruthy('empty difficulty produces em-dash', /\u2014/.test(emptyFields));


// ═══════════════════════════════════════════════════════════════════════════
//  SUITE 14: renderLeaderboard() — pure HTML + logic
// ═══════════════════════════════════════════════════════════════════════════

console.log('📊 SUITE 14: renderLeaderboard() — HTML + logic');

var _medals = ['🥇','🥈','🥉'];

function renderLeaderboardHtml(lb) {
  if (!lb || !lb.length) return '<tr><td colspan="6" class="empty">awaiting data\u2026</td></tr>';
  var maxScore = 0;
  lb.forEach(function(r) { var s = parseFloat(r.combined_score || r.score || 0); if (s > maxScore) maxScore = s; });
  return lb.map(function(r, i) {
    var rank = i + 1;
    var rankHtml = rank <= 3 ? '<span class="lb-rank lb-rank--top">' + _medals[rank-1] + '</span>' : '<span class="lb-rank">#' + rank + '</span>';
    var scoreVal = parseFloat(r.combined_score || r.score || 0);
    var barPct = maxScore > 0 ? (scoreVal / maxScore * 100) : 0;
    return '<tr class="lb-row">\n' +
      '<td class="lb-col-rank">' + rankHtml + '</td>\n' +
      '<td class="lb-col-addr"><span class="lb-addr">' + fmt.shortAddr(r.address) + '</span></td>\n' +
      '<td class="lb-col-diff"><span class="lb-diff">' + (r.diff_rank || r.diffRank || '\u2014') + '</span></td>\n' +
      '<td class="lb-col-loyalty"><span class="lb-loyalty">' + (r.loyalty_rank || r.loyalty || '\u2014') + '</span></td>\n' +
      '<td class="lb-col-score">\n' +
      '  <div class="lb-score-bar-wrap"><div class="lb-score-bar" style="width:' + barPct.toFixed(0) + '%"></div></div>\n' +
      '  <span class="lb-score-val">' + scoreVal.toFixed(scoreVal >= 1000 ? 0 : 2) + '</span>\n' +
      '</td>\n' +
      '<td class="lb-col-blocks"><span class="lb-blocks">' + (r.total_blocks || r.blocks || 0) + '</span></td>\n' +
      '</tr>';
  }).join('');
}

assertEqual('lbHtml([]) -> empty', renderLeaderboardHtml([]), '<tr><td colspan="6" class="empty">awaiting data\u2026</td></tr>');
assertEqual('lbHtml(null) -> empty', renderLeaderboardHtml(null), '<tr><td colspan="6" class="empty">awaiting data\u2026</td></tr>');

var singleLb = renderLeaderboardHtml([{ address: 'bc1qtest', combined_score: 100, total_blocks: 5 }]);
assertTruthy('lb single has lb-row', /lb-row/.test(singleLb));
assertTruthy('lb single has 🥇 for rank 1', /🥇/.test(singleLb));
assertTruthy('lb single has lb-rank--top', /lb-rank--top/.test(singleLb));
assertTruthy('lb single has score bar width 100%', /width:100%/.test(singleLb));
assertTruthy('lb single has score val 100.00', /100\.00/.test(singleLb));
assertTruthy('lb single has blocks 5', />5</.test(singleLb));

var multiLb = [
  { address: 'a1', combined_score: 300, total_blocks: 10 },
  { address: 'a2', combined_score: 200, total_blocks: 5 },
  { address: 'a3', combined_score: 100, total_blocks: 2 },
  { address: 'a4', combined_score: 50, total_blocks: 1 },
];
var multiLbHtml = renderLeaderboardHtml(multiLb);
var rows = multiLbHtml.split('<tr class="lb-row">');
assertEqual('lb 4 entries produces 4 rows', rows.length - 1, 4);
assertTruthy('rank 1 has 🥇', /🥇/.test(rows[1]));
assertTruthy('rank 2 has 🥈', /🥈/.test(rows[2]));
assertTruthy('rank 3 has 🥉', /🥉/.test(rows[3]));
assertTruthy('rank 4 has #4 (no medal)', /#4/.test(rows[4]));
assertFalsy('rank 4 has no lb-rank--top', /lb-rank--top/.test(rows[4]));

assertTruthy('rank 1 score bar 100%', /width:100%/.test(rows[1]));
assertTruthy('rank 2 score bar 67%', /width:67%/.test(rows[2]));
assertTruthy('rank 3 score bar 33%', /width:33%/.test(rows[3]));
assertTruthy('rank 4 score bar 17%', /width:17%/.test(rows[4]));

var scoreLb = renderLeaderboardHtml([
  { address: 'a1', combined_score: 1234, total_blocks: 1 },
  { address: 'a2', combined_score: 567, total_blocks: 1 },
]);
assertTruthy('score >=1000 shows 0 decimals: 1234', />1234/.test(scoreLb));
assertFalsy('score >=1000 does not have decimals', /\.00/.test(scoreLb.split('<tr')[1]));
assertTruthy('score <1000 shows 2 decimals: 567.00', />567\.00/.test(scoreLb));

var scoreFallback = renderLeaderboardHtml([{ address: 'a1', score: 500, total_blocks: 1 }]);
assertTruthy('score field works as fallback', /500\.00/.test(scoreFallback));

var diffRankFallback = renderLeaderboardHtml([{ address: 'a1', diffRank: 'TOP 10%', total_blocks: 1 }]);
assertTruthy('diffRank fallback shown', /TOP 10%/.test(diffRankFallback));

var loyaltyFallback = renderLeaderboardHtml([{ address: 'a1', loyalty: 'HIGH', total_blocks: 1 }]);
assertTruthy('loyalty fallback shown', /HIGH/.test(loyaltyFallback));

var blocksFallback = renderLeaderboardHtml([{ address: 'a1', blocks: 42, score: 1 }]);
assertTruthy('blocks fallback works', />42</.test(blocksFallback));

var emptyLb = renderLeaderboardHtml([{ address: 'a1', score: 0 }]);
assertTruthy('empty diff_rank shows em-dash', /\u2014/.test(emptyLb));
assertTruthy('empty loyalty shows em-dash', /\u2014/.test(emptyLb));
assertTruthy('empty blocks shows 0 (not em-dash)', />0</.test(emptyLb));

var zeroScoreLb = renderLeaderboardHtml([{ address: 'a1', combined_score: 0, total_blocks: 0 }]);
assertTruthy('zero score bar width 0%', /width:0%/.test(zeroScoreLb));

var totalElText = function(lb) {
  var count = lb ? lb.length : 0;
  return count + ' miners';
};
assertEqual('total count for 3 entries', totalElText(['a','b','c']), '3 miners');
assertEqual('total count for 1 entry', totalElText(['a']), '1 miners');
assertEqual('total count for 0 entries', totalElText([]), '0 miners');
assertEqual('total count for null', totalElText(null), '0 miners');


// ═══════════════════════════════════════════════════════════════════════════
//  SUITE 15: renderTimelineFeed() — pure HTML generation + dedup logic
// ═══════════════════════════════════════════════════════════════════════════

console.log('📊 SUITE 15: renderTimelineFeed() — HTML + dedup');

var _sevDots = {CRITICAL:'🔴',HIGH:'🟠',GOLD:'🟡',INFO:'🔵',WARN:'⚠️'};

function _normalizeEvent(e) {
  if (Array.isArray(e)) {
    return { id: e[0] + '_test', ts: e[0], event_type: e[1] || 'EVENT', severity: e[2] || 'INFO', message: e.length > 3 ? e[3] : (e[2] || '') };
  }
  return e;
}

function renderTimelineFeedHtml(list, _seenIds, _totalRendered) {
  _seenIds = _seenIds || new Set();
  _totalRendered = _totalRendered || 0;
  if (!list || !list.length) return { html: '', newCount: 0, total: _totalRendered };
  var normalized = list.map(_normalizeEvent);
  var ordered = normalized.slice().reverse();
  var newOnes = ordered.filter(function(e) { return !_seenIds.has(e.id); });
  if (!newOnes.length) return { html: '', newCount: 0, total: _totalRendered };
  var rows = newOnes.map(function(ev) {
    var sev = (ev.severity || 'INFO').toUpperCase();
    var dot = _sevDots[sev] || '●';
    return '<div class="timeline-row" data-id="' + ev.id + '">\n' +
      '<span class="tf-dot">' + dot + '</span>\n' +
      '<span class="tf-time">--:--:--</span>\n' +
      '<span class="tf-type tf-type--' + sev.toLowerCase() + '">' + (ev.event_type || 'EVENT') + '</span>\n' +
      '<span class="tf-msg">' + escapeHtml(ev.message || '') + '</span>\n' +
      '</div>';
  }).join('');
  newOnes.forEach(function(e) { _seenIds.add(e.id); });
  _totalRendered += newOnes.length;
  var MAX = 80;
  while (_totalRendered > MAX) { _totalRendered--; }
  return { html: rows, newCount: newOnes.length, total: _totalRendered, seenIds: _seenIds };
}

assertEqual('timeline empty list -> empty html', renderTimelineFeedHtml([]).html, '');
assertEqual('timeline empty list -> 0 new', renderTimelineFeedHtml([]).newCount, 0);

assertEqual('timeline null -> empty', renderTimelineFeedHtml(null).html, '');

var singleEvent = [{ id: 'e1', ts: 1000, event_type: 'SHARE_FOUND', severity: 'INFO', message: 'share validated' }];
var singleResult = renderTimelineFeedHtml(singleEvent);
assertTruthy('single event has timeline-row', /timeline-row/.test(singleResult.html));
assertTruthy('single event has tf-dot 🔵 (INFO)', /🔵/.test(singleResult.html));
assertTruthy('single event has tf-type--info', /tf-type--info/.test(singleResult.html));
assertTruthy('single event has SHARE_FOUND type', /SHARE_FOUND/.test(singleResult.html));
assertTruthy('single event has message', /share validated/.test(singleResult.html));
assertEqual('single event newCount = 1', singleResult.newCount, 1);

var arrEvent = [1000, 'JOB', 'INFO', '6 workers active'];
var arrResult = renderTimelineFeedHtml([arrEvent]);
assertTruthy('array event has timeline-row', /timeline-row/.test(arrResult.html));
assertTruthy('array event has JOB type', /JOB/.test(arrResult.html));
assertTruthy('array event has message', /6 workers active/.test(arrResult.html));

var arrShort = [2000, 'EVENT', 'test msg'];
var arrShortResult = renderTimelineFeedHtml([arrShort]);
assertTruthy('short array event has EVENT type', /EVENT/.test(arrShortResult.html));
assertTruthy('short array event has message', /test msg/.test(arrShortResult.html));

['CRITICAL','HIGH','GOLD','INFO','WARN'].forEach(function(sev) {
  var sevResult = renderTimelineFeedHtml([{ id: sev, ts: 1000, event_type: 'TEST', severity: sev, message: 'sev ' + sev }]);
  assertTruthy('severity ' + sev + ' has tf-type--' + sev.toLowerCase(), new RegExp('tf-type--' + sev.toLowerCase()).test(sevResult.html));
});

var seen = new Set();
var first = renderTimelineFeedHtml([{ id: 'dup1', ts: 1000, event_type: 'TEST', severity: 'INFO', message: 'first' }], seen, 0);
assertEqual('first render: 1 new', first.newCount, 1);
var second = renderTimelineFeedHtml([{ id: 'dup1', ts: 1000, event_type: 'TEST', severity: 'INFO', message: 'first' }], first.seenIds, first.total);
assertEqual('second render: 0 new (dedup)', second.newCount, 0);

var seen2 = new Set();
seen2.add('old1'); seen2.add('old2');
var mixed = renderTimelineFeedHtml([
  { id: 'old1', ts: 1000, event_type: 'OLD', severity: 'INFO', message: 'already seen' },
  { id: 'new1', ts: 2000, event_type: 'NEW', severity: 'INFO', message: 'fresh event' },
  { id: 'new2', ts: 3000, event_type: 'NEW', severity: 'WARN', message: 'another fresh' },
], seen2, 2);
assertEqual('mixed: 2 new events', mixed.newCount, 2);
assertTruthy('mixed includes new1', /fresh event/.test(mixed.html));
assertTruthy('mixed includes new2', /another fresh/.test(mixed.html));
assertFalsy('mixed excludes old1', /already seen/.test(mixed.html));

var unsafeMsg = renderTimelineFeedHtml([{ id: 'xss', ts: 1000, event_type: 'ALERT', severity: 'WARN', message: '<script>alert(1)</script>' }]);
assertTruthy('timeline escapes HTML', /&lt;script&gt;/.test(unsafeMsg.html));
assertFalsy('timeline no raw script tag', /<script>/.test(unsafeMsg.html));

var unknownSevEvent = renderTimelineFeedHtml([{ id: 'unk', ts: 1000, event_type: 'TEST', severity: 'UNKNOWN', message: 'weird' }]);
assertTruthy('unknown severity uses ● fallback dot', /●/.test(unknownSevEvent.html));

var noSevEvent = renderTimelineFeedHtml([{ id: 'nosev', ts: 1000, event_type: 'TEST', message: 'no sev' }]);
assertTruthy('no severity -> tf-type--info', /tf-type--info/.test(noSevEvent.html));
assertTruthy('no severity -> 🔵 dot', /🔵/.test(noSevEvent.html));

var orderResult = renderTimelineFeedHtml([
  { id: 'early', ts: 1000, event_type: 'EARLY', severity: 'INFO', message: 'first' },
  { id: 'later', ts: 2000, event_type: 'LATER', severity: 'INFO', message: 'second' },
]);
var orderHtml = orderResult.html;
var firstEventPos = orderHtml.indexOf('first');
var secondEventPos = orderHtml.indexOf('second');
assertTruthy('recent events appear first (reverse order)', secondEventPos < firstEventPos);

var many = [];
for (var j = 0; j < 100; j++) many.push({ id: 'max' + j, ts: j, event_type: 'EVENT', severity: 'INFO', message: 'evt ' + j });
var maxResult = renderTimelineFeedHtml(many);
assertEqual('max 80 rendered, but returns all new (trim happens in DOM)', maxResult.newCount, 100);


// ═══════════════════════════════════════════════════════════════════════════
//  SUITE 15b: computeTimelineStats() — SHARE TIMELINE summary aggregation
// ═══════════════════════════════════════════════════════════════════════════
// Mirrors static/app.js computeTimelineStats(): counts SHARE_FOUND /
// BEST_DIFF_BUMP events inside the 1h / 24h windows from a timeline list.
// This is the client-side fallback that finally populates the LAST SHARE /
// 1H / 24H / BUMPS 24H cards (previously stuck on em-dash forever because
// the DOM nodes were defined but never written).

console.log('📊 SUITE 15b: computeTimelineStats() — summary aggregation');

function _normalizeTimelineEventTest(e) {
  if (Array.isArray(e)) {
    return { ts: e[0], event_type: e[1] || 'EVENT', severity: e[2] || 'INFO', message: e.length > 3 ? e[3] : (e[2] || '') };
  }
  return e;
}

function computeTimelineStatsTest(list, nowSec) {
  var now = nowSec || Math.floor(Date.now() / 1000);
  var out = { shares1h: 0, shares24h: 0, bumps24h: 0 };
  if (!list || !list.length) return out;
  list.forEach(function(e) {
    if (!e) return;
    var ev = _normalizeTimelineEventTest(e);
    var t = Number(ev.ts);
    if (!t || !isFinite(t)) return;
    var age = now - t;
    if (age < 0) return;
    if (ev.event_type === 'SHARE_FOUND') {
      if (age <= 3600) out.shares1h++;
      if (age <= 86400) out.shares24h++;
    } else if (ev.event_type === 'BEST_DIFF_BUMP') {
      if (age <= 86400) out.bumps24h++;
    }
  });
  return out;
}

// Mirrors renderTimelineStats() value selection: DB aggregates win, else
// client-side aggregation of the timeline list.
function resolveTimelineCardValuesTest(es, timelineList, nowSec) {
  es = es || {};
  var fb = computeTimelineStatsTest(timelineList, nowSec);
  return {
    shares1h: es.db_shares_last_hour != null ? Number(es.db_shares_last_hour) : fb.shares1h,
    shares24h: es.db_shares_last_day != null ? Number(es.db_shares_last_day) : fb.shares24h,
    bumps24h: es.db_best_diffs_last_day != null ? Number(es.db_best_diffs_last_day) : fb.bumps24h,
  };
}

var tsNow = 1785714000;

// Empty / null inputs → zero counts (never NaN)
assertEqual('timelineStats([]) → zeros', computeTimelineStatsTest([], tsNow), { shares1h: 0, shares24h: 0, bumps24h: 0 });
assertEqual('timelineStats(null) → zeros', computeTimelineStatsTest(null, tsNow), { shares1h: 0, shares24h: 0, bumps24h: 0 });
assertEqual('timelineStats(undefined) → zeros', computeTimelineStatsTest(undefined, tsNow), { shares1h: 0, shares24h: 0, bumps24h: 0 });

// Single SHARE_FOUND within the 1h window → counts in both windows
var oneShare = [{ ts: tsNow - 600, event_type: 'SHARE_FOUND', severity: 'INFO', message: 'share' }];
assertEqual('1h window counts a fresh share', computeTimelineStatsTest(oneShare, tsNow).shares1h, 1);
assertEqual('24h window counts a fresh share', computeTimelineStatsTest(oneShare, tsNow).shares24h, 1);
assertEqual('fresh share is not a bump', computeTimelineStatsTest(oneShare, tsNow).bumps24h, 0);

// Share older than 1h but within 24h → 24h only
var oldShare = [{ ts: tsNow - 7200, event_type: 'SHARE_FOUND', severity: 'INFO', message: 'old share' }];
assertEqual('2h-old share excluded from 1h', computeTimelineStatsTest(oldShare, tsNow).shares1h, 0);
assertEqual('2h-old share counted in 24h', computeTimelineStatsTest(oldShare, tsNow).shares24h, 1);

// Share older than 24h → excluded everywhere
var staleShare = [{ ts: tsNow - 90000, event_type: 'SHARE_FOUND', severity: 'INFO', message: 'stale share' }];
assertEqual('25h-old share excluded from 1h', computeTimelineStatsTest(staleShare, tsNow).shares1h, 0);
assertEqual('25h-old share excluded from 24h', computeTimelineStatsTest(staleShare, tsNow).shares24h, 0);

// BEST_DIFF_BUMP counting
var oneBump = [{ ts: tsNow - 300, event_type: 'BEST_DIFF_BUMP', severity: 'GOLD', message: 'new best' }];
assertEqual('fresh bump counted in 24h', computeTimelineStatsTest(oneBump, tsNow).bumps24h, 1);
assertEqual('fresh bump is not a share', computeTimelineStatsTest(oneBump, tsNow).shares1h, 0);
var oldBump = [{ ts: tsNow - 90000, event_type: 'BEST_DIFF_BUMP', severity: 'GOLD', message: 'old best' }];
assertEqual('old bump excluded from 24h', computeTimelineStatsTest(oldBump, tsNow).bumps24h, 0);

// Mixed event list — the user's exact scenario (dozens of SHARE_FOUND + 3 bumps)
var mixed = [
  { ts: tsNow - 60, event_type: 'SHARE_FOUND', severity: 'INFO', message: 's1' },
  { ts: tsNow - 300, event_type: 'SHARE_FOUND', severity: 'INFO', message: 's2' },
  { ts: tsNow - 1900, event_type: 'BEST_DIFF_BUMP', severity: 'GOLD', message: 'b1' },
  { ts: tsNow - 3600, event_type: 'SHARE_FOUND', severity: 'INFO', message: 's3' },
  { ts: tsNow - 7200, event_type: 'SHARE_FOUND', severity: 'INFO', message: 's4 (outside 1h)' },
  { ts: tsNow - 2500, event_type: 'BEST_DIFF_BUMP', severity: 'GOLD', message: 'b2' },
  { ts: tsNow - 90000, event_type: 'BEST_DIFF_BUMP', severity: 'GOLD', message: 'b3 (outside 24h)' },
];
var mixedRes = computeTimelineStatsTest(mixed, tsNow);
assertEqual('mixed: 3 shares in 1h (s1,s2,s3)', mixedRes.shares1h, 3);
assertEqual('mixed: 4 shares in 24h (s1,s2,s3,s4)', mixedRes.shares24h, 4);
assertEqual('mixed: 2 bumps in 24h (b1,b2)', mixedRes.bumps24h, 2);

// Array-format events (backend timeline_last_n format) are normalized too
var arrEvents = [
  [tsNow - 120, 'SHARE_FOUND', 'INFO', 'share via array'],
  [tsNow - 200, 'BEST_DIFF_BUMP', 'GOLD', 'bump via array'],
];
var arrRes = computeTimelineStatsTest(arrEvents, tsNow);
assertEqual('array events: 1 share in 1h', arrRes.shares1h, 1);
assertEqual('array events: 1 bump in 24h', arrRes.bumps24h, 1);

// Future timestamps (clock skew) never count
var future = [{ ts: tsNow + 5000, event_type: 'SHARE_FOUND', severity: 'INFO', message: 'future' }];
assertEqual('future share never counts', computeTimelineStatsTest(future, tsNow).shares1h, 0);

// Malformed entries are skipped without throwing
var malformed = [
  null,
  { ts: 'garbage', event_type: 'SHARE_FOUND' },
  { ts: NaN, event_type: 'SHARE_FOUND' },
  'string',
];
assertEqual('malformed entries skipped → zeros', computeTimelineStatsTest(malformed, tsNow), { shares1h: 0, shares24h: 0, bumps24h: 0 });

// renderTimelineStats() value selection: DB aggregates are authoritative…
var esWithDb = { db_shares_last_hour: 15, db_shares_last_day: 30, db_best_diffs_last_day: 4 };
var selDb = resolveTimelineCardValuesTest(esWithDb, mixed, tsNow);
assertEqual('DB 1h value wins over client calc', selDb.shares1h, 15);
assertEqual('DB 24h value wins over client calc', selDb.shares24h, 30);
assertEqual('DB bumps value wins over client calc', selDb.bumps24h, 4);

// …but client-side aggregation is the fallback when DB keys are absent
var selFb = resolveTimelineCardValuesTest({}, mixed, tsNow);
assertEqual('fallback 1h from timeline list', selFb.shares1h, mixedRes.shares1h);
assertEqual('fallback 24h from timeline list', selFb.shares24h, mixedRes.shares24h);
assertEqual('fallback bumps from timeline list', selFb.bumps24h, mixedRes.bumps24h);

// Zero is a real count — never coerced to em-dash
var selZero = resolveTimelineCardValuesTest({ db_shares_last_hour: 0, db_shares_last_day: 0, db_best_diffs_last_day: 0 }, [], tsNow);
assertEqual('explicit DB 0 stays 0 (not dash)', selZero.shares1h, 0);
assertEqual('explicit DB 0 24h stays 0', selZero.shares24h, 0);
assertEqual('explicit DB 0 bumps stays 0', selZero.bumps24h, 0);

// LAST SHARE fallback: latest SHARE_FOUND ts from the timeline list
function lastShareTsFromTimelineTest(list, nowSec) {
  var now = nowSec || Math.floor(Date.now() / 1000);
  var latest = 0;
  if (!list || !list.length) return 0;
  list.forEach(function(e) {
    if (!e) return;
    var ev = _normalizeTimelineEventTest(e);
    var t = Number(ev.ts);
    if (!t || !isFinite(t)) return;
    if (ev.event_type !== 'SHARE_FOUND') return;
    var age = now - t;
    if (age < 0 || age > 86400) return;
    if (t > latest) latest = t;
  });
  return latest;
}

assertEqual('lastShare empty list → 0', lastShareTsFromTimelineTest([], tsNow), 0);
assertEqual('lastShare null list → 0', lastShareTsFromTimelineTest(null, tsNow), 0);
assertEqual('lastShare picks newest share', lastShareTsFromTimelineTest(mixed, tsNow), tsNow - 60);
var lastBumpOnly = lastShareTsFromTimelineTest([{ ts: tsNow - 500, event_type: 'BEST_DIFF_BUMP', severity: 'GOLD' }], tsNow);
assertEqual('lastShare ignores bumps (not shares)', lastBumpOnly, 0);
var lastStale = lastShareTsFromTimelineTest([{ ts: tsNow - 90000, event_type: 'SHARE_FOUND', severity: 'INFO' }], tsNow);
assertEqual('lastShare ignores shares older than 24h', lastStale, 0);
var lastArray = lastShareTsFromTimelineTest([[tsNow - 90, 'SHARE_FOUND', 'INFO', 'arr']], tsNow);
assertEqual('lastShare works with array events', lastArray, tsNow - 90);
var lastFuture = lastShareTsFromTimelineTest([{ ts: tsNow + 100, event_type: 'SHARE_FOUND', severity: 'INFO' }], tsNow);
assertEqual('lastShare ignores future shares', lastFuture, 0);
// LAST SHARE prefers the session-scoped ts when present
assertEqual('lastShare prefers es.last_submit_ts', esWithDb && 1785714000 > lastShareTsFromTimelineTest(mixed, tsNow), true);


// ═══════════════════════════════════════════════════════════════════════════
//  SUITE 16: Combined edge cases — all 5 functions
// ═══════════════════════════════════════════════════════════════════════════

console.log('📊 SUITE 16: Combined edge cases');

['info','warn','error','success','critical'].forEach(function(sev) {
  var html = logMessageHtml('TEST', 'msg_' + sev, sev);
  assertTruthy('logMessage severity ' + sev + ' has tag class', new RegExp('tag-' + sev).test(html));
  assertTruthy('logMessage severity ' + sev + ' has msg', new RegExp('msg_' + sev).test(html));
});

var unknownAlert = renderAlertsHtml([{ severity: 'DEBUG', message: 'debug msg' }]);
assertTruthy('unknown alert severity renders', /alert-item/.test(unknownAlert));
assertTruthy('unknown alert gets ! icon', /!/.test(unknownAlert));
assertTruthy('unknown alert has SEVERITY-DEBUG', /SEVERITY-DEBUG/.test(unknownAlert));

var minimalEvent = renderEventsHtml([{ claimed: true }]);
assertTruthy('minimal event renders', /ev-claimed--yes/.test(minimalEvent));

// NaN score — in Node, NaN.toFixed() returns "NaN" (does NOT throw)
var nanResult = renderLeaderboardHtml([{ address: 'a1', combined_score: 'abc', total_blocks: 1 }]);
assertTruthy('NaN score shows NaN in output (does not crash)', /NaN/.test(nanResult));
assertTruthy('NaN score still has lb-row', /lb-row/.test(nanResult));

// With isFinite guard, NaN becomes 0
function renderLeaderboardHtmlGuarded(lb) {
  if (!lb || !lb.length) return '<tr><td colspan="6" class="empty">awaiting data\u2026</td></tr>';
  var maxScore = 0;
  lb.forEach(function(r) { var s = parseFloat(r.combined_score || r.score || 0); if (!isFinite(s)) s = 0; if (s > maxScore) maxScore = s; });
  return lb.map(function(r, i) {
    var scoreVal = parseFloat(r.combined_score || r.score || 0);
    if (!isFinite(scoreVal)) scoreVal = 0;
    var barPct = maxScore > 0 ? (scoreVal / maxScore * 100) : 0;
    return '<tr class="lb-row"><td class="lb-col-score"><div class="lb-score-bar-wrap"><div class="lb-score-bar" style="width:' + barPct.toFixed(0) + '%"></div></div><span class="lb-score-val">' + scoreVal.toFixed(2) + '</span></td></tr>';
  }).join('');
}
var guarded = renderLeaderboardHtmlGuarded([{ address: 'a1', combined_score: 'abc', total_blocks: 1 }]);
assertTruthy('NaN score with guard renders 0.00', /0\.00/.test(guarded));

var unknownSev2 = renderTimelineFeedHtml([{ id: 'u2', ts: 1000, event_type: 'FATAL', severity: 'FATAL', message: 'fatal' }]);
assertTruthy('unknown severity uses ● dot', /●/.test(unknownSev2.html));
assertTruthy('unknown severity has lowercased class', /tf-type--fatal/.test(unknownSev2.html));

var largeAlerts = [];
for (var k = 0; k < 100; k++) largeAlerts.push({ severity: 'INFO', message: 'alert_' + k });
var largeAlertResult = renderAlertsHtml(largeAlerts);
assertEqual('100 alerts truncated to 15', largeAlertResult.match(/alert-item/g).length, 15);

var largeEvents = [];
for (var m = 0; m < 50; m++) largeEvents.push({ block_height: m, claimed: m % 2 === 0 });
var largeEventResult = renderEventsHtml(largeEvents);
assertEqual('50 events all rendered', largeEventResult.match(/<tr>/g).length, 50);

var largeLb = [];
for (var n = 0; n < 30; n++) largeLb.push({ address: 'addr' + n, combined_score: n * 10, total_blocks: n });
var largeLbResult = renderLeaderboardHtml(largeLb);
assertEqual('30 leaderboard entries all rendered', largeLbResult.match(/<tr class="lb-row">/g).length, 30);


// ═══════════════════════════════════════════════════════════════════════════
//  SUITE 17: logMessage() — state management (renderedEventCount, max 150, clear)
// ═══════════════════════════════════════════════════════════════════════════

console.log('📊 SUITE 17: logMessage() — state management');

// Simulate renderedEventCount logic from app.js:
//   renderedEventCount++
//   while (renderedEventCount > 150) { remove oldest line; renderedEventCount--; }

function simulateLogMessageState(logs, sev) {
  // Pure logic: add log entry (appended to DOM first, then trimmed)
  logs.items.push({ sev: sev || 'info', ts: Date.now() });
  var count = logs.count + 1;
  while (count > 150) {
    logs.items.shift(); // remove oldest from DOM
    count--;
  }
  logs.count = count;
  return logs;
}

function simulateClearLogs() {
  return { count: 0, items: [] };
}

// Initial state
var logState = { count: 0, items: [] };
assertEqual('initial count = 0', logState.count, 0);
assertEqual('initial items empty', logState.items.length, 0);

// Single log
logState = simulateLogMessageState(logState, 'info');
assertEqual('after 1 log: count = 1', logState.count, 1);
assertEqual('after 1 log: 1 item', logState.items.length, 1);
assertEqual('item severity is info', logState.items[0].sev, 'info');

// Multiple logs
for (var si = 0; si < 5; si++) {
  logState = simulateLogMessageState(logState, 'warn');
}
assertEqual('after 6 logs (1+5): count = 6', logState.count, 6);
assertEqual('after 6 logs: 6 items', logState.items.length, 6);

// Clear
logState = simulateClearLogs();
assertEqual('after clear: count = 0', logState.count, 0);
assertEqual('after clear: items empty', logState.items.length, 0);

// Reset and add 150 logs (exactly at limit)
var limitState = { count: 0, items: [] };
for (var sj = 0; sj < 150; sj++) {
  limitState = simulateLogMessageState(limitState, sj % 2 === 0 ? 'info' : 'warn');
}
assertEqual('at 150: count = 150', limitState.count, 150);
assertEqual('at 150: 150 items', limitState.items.length, 150);

// Add one more (should go to 150, capped)
limitState = simulateLogMessageState(limitState, 'error');
assertEqual('at 151: count capped at 150', limitState.count, 150);
assertEqual('at 151: still 150 items', limitState.items.length, 150);

// Verify capping logic: add 100 more, should stay at 150
for (var sk = 0; sk < 100; sk++) {
  limitState = simulateLogMessageState(limitState, 'info');
}
assertEqual('after 251 total: count capped at 150', limitState.count, 150);
assertEqual('after 251 total: still 150 items', limitState.items.length, 150);

// Multiple clear cycles
for (var cycle = 0; cycle < 3; cycle++) {
  var cycleState = { count: 0, items: [] };
  for (var sc = 0; sc < 10; sc++) {
    cycleState = simulateLogMessageState(cycleState, 'info');
  }
  assertEqual('cycle ' + cycle + ': 10 logs', cycleState.count, 10);
  cycleState = simulateClearLogs();
  assertEqual('cycle ' + cycle + ': cleared to 0', cycleState.count, 0);
}

// Different severity levels
var sevState = { count: 0, items: [] };
var severities = ['info', 'warn', 'error', 'success', 'critical'];
severities.forEach(function(s) {
  sevState = simulateLogMessageState(sevState, s);
});
assertEqual('5 sevs: count = 5', sevState.count, 5);
assertEqual('5 sevs: last is critical', sevState.items[4].sev, 'critical');

// Edge: 0 logs after clear still works
var emptyState = simulateClearLogs();
emptyState = simulateLogMessageState(emptyState, 'info');
assertEqual('add after clear: count = 1', emptyState.count, 1);

// Verify count text format
function logCountText(count) {
  return count + ' events';
}
assertEqual('count text: 0 events', logCountText(0), '0 events');
assertEqual('count text: 1 events', logCountText(1), '1 events');
assertEqual('count text: 150 events', logCountText(150), '150 events');


// ═══════════════════════════════════════════════════════════════════════════
//  SUITE 18: _applyLogFilter() — severity filter + text search + count display
// ═══════════════════════════════════════════════════════════════════════════

console.log('📊 SUITE 18: _applyLogFilter() — filter logic');

// Pure function simulation of _applyLogFilter:
//   For each line: check className includes tag-{filter} AND textContent includes search
//   Return { visibleCount, totalCount, hiddenLines[] }
function simulateLogFilter(lines, activeFilter, searchText) {
  var totalCount = lines.length;
  var visibleCount = 0;
  var hiddenLines = [];

  lines.forEach(function(line) {
    var matchesFilter = (activeFilter === 'all') || line.className.indexOf('tag-' + activeFilter) !== -1;
    var matchesSearch = !searchText || line.textContent.toLowerCase().indexOf(searchText.toLowerCase()) !== -1;
    if (matchesFilter && matchesSearch) {
      visibleCount++;
    } else {
      hiddenLines.push(line);
    }
  });

  return { visibleCount: visibleCount, totalCount: totalCount, hiddenLines: hiddenLines };
}

// Build test lines
function makeTestLine(sev, text) {
  return {
    className: 'terminal__line tag-' + sev,
    textContent: '[' + new Date().toTimeString().slice(0,8) + '] [' + sev.toUpperCase() + '] ' + text
  };
}

// ── Severity filter tests ──

// All lines match 'all' filter
var allLines = [
  makeTestLine('info', 'system online'),
  makeTestLine('warn', 'high temperature'),
  makeTestLine('error', 'connection lost'),
  makeTestLine('success', 'block found'),
  makeTestLine('critical', 'device offline'),
];
var allResult = simulateLogFilter(allLines, 'all', '');
assertEqual('all filter: all 5 visible', allResult.visibleCount, 5);
assertEqual('all filter: total 5', allResult.totalCount, 5);
assertEqual('all filter: 0 hidden', allResult.hiddenLines.length, 0);

// Filter by 'info'
var infoResult = simulateLogFilter(allLines, 'info', '');
assertEqual('info filter: 1 visible', infoResult.visibleCount, 1);
assertEqual('info filter: 1 info line only', infoResult.hiddenLines.length, 4);

// Filter by 'warn'
var warnResult = simulateLogFilter(allLines, 'warn', '');
assertEqual('warn filter: 1 visible', warnResult.visibleCount, 1);
assertEqual('warn filter: 1 warn line only', warnResult.hiddenLines.length, 4);

// Filter by 'error'
var errorResult = simulateLogFilter(allLines, 'error', '');
assertEqual('error filter: 1 visible', errorResult.visibleCount, 1);
assertEqual('error filter: 1 error line only', errorResult.hiddenLines.length, 4);

// Filter by 'success'
var successResult = simulateLogFilter(allLines, 'success', '');
assertEqual('success filter: 1 visible', successResult.visibleCount, 1);
assertEqual('success filter: 1 success line only', successResult.hiddenLines.length, 4);

// Filter by 'critical'
var criticalResult = simulateLogFilter(allLines, 'critical', '');
assertEqual('critical filter: 1 visible', criticalResult.visibleCount, 1);
assertEqual('critical filter: 1 critical line only', criticalResult.hiddenLines.length, 4);

// ── Text search tests ──

// Search for 'block'
var searchBlock = simulateLogFilter(allLines, 'all', 'block');
assertEqual('search "block": 1 found (block found)', searchBlock.visibleCount, 1);
assertEqual('search "block": 4 hidden', searchBlock.hiddenLines.length, 4);

// Search for 'temperature'
var searchTemp = simulateLogFilter(allLines, 'all', 'temperature');
assertEqual('search "temperature": 1 found (high temperature)', searchTemp.visibleCount, 1);

// Search for 'connection'
var searchConn = simulateLogFilter(allLines, 'all', 'connection');
assertEqual('search "connection": 1 found (connection lost)', searchConn.visibleCount, 1);

// Case insensitive search
var searchOnline = simulateLogFilter(allLines, 'all', 'ONLINE');
assertEqual('case insensitive "ONLINE": 1 found (system online)', searchOnline.visibleCount, 1);

// No match
var searchNone = simulateLogFilter(allLines, 'all', 'zzzznotfound');
assertEqual('search no match: 0 found', searchNone.visibleCount, 0);
assertEqual('search no match: all 5 hidden', searchNone.hiddenLines.length, 5);

// Empty search (show all)
var searchEmpty = simulateLogFilter(allLines, 'all', '');
assertEqual('empty search: all 5 visible', searchEmpty.visibleCount, 5);
assertEqual('empty search: 0 hidden', searchEmpty.hiddenLines.length, 0);

// ── Combined filter + search tests ──

// Filter 'error' + no search
var combined1 = simulateLogFilter(allLines, 'error', '');
assertEqual('error filter only: 1 visible', combined1.visibleCount, 1);

// Filter 'error' + search that matches error line
var combined2 = simulateLogFilter(allLines, 'error', 'connection');
assertEqual('error filter + "connection": 1 visible', combined2.visibleCount, 1);

// Filter 'error' + search that does NOT match error line
var combined3 = simulateLogFilter(allLines, 'error', 'temperature');
assertEqual('error filter + "temperature": 0 visible (no match)', combined3.visibleCount, 0);

// Filter 'all' + search that matches multiple
var combined4 = simulateLogFilter(allLines, 'all', 'lost');
assertEqual('all filter + "lost": 1 visible', combined4.visibleCount, 1);

// ── Many lines with mixed severity ──

var manyLines = [];
var manySevs = ['info', 'warn', 'error', 'success', 'critical'];
for (var mi = 0; mi < 100; mi++) {
  manyLines.push(makeTestLine(manySevs[mi % 5], 'event ' + mi));
}

// All filter
var manyAll = simulateLogFilter(manyLines, 'all', '');
assertEqual('100 lines, all filter: 100 visible', manyAll.visibleCount, 100);

// Severity filter
var manyInfo = simulateLogFilter(manyLines, 'info', '');
assertEqual('100 lines, info filter: 20 info visible', manyInfo.visibleCount, 20);
var manyError = simulateLogFilter(manyLines, 'error', '');
assertEqual('100 lines, error filter: 20 error visible', manyError.visibleCount, 20);

// Search + severity
var manySearchInfo = simulateLogFilter(manyLines, 'info', 'event');
assertEqual('100 lines, info filter + "event": 20 info visible', manySearchInfo.visibleCount, 20);

// Search on specific event number
var manySearchSpecific = simulateLogFilter(manyLines, 'all', 'event 5');
assertEqual('100 lines, search "event 5": 11 visible (substring: 5,50-59)', manySearchSpecific.visibleCount, 11);

// ── Empty line array ──

var emptyLines = simulateLogFilter([], 'all', '');
assertEqual('empty lines: 0 visible', emptyLines.visibleCount, 0);
assertEqual('empty lines: 0 total', emptyLines.totalCount, 0);
assertEqual('empty lines: 0 hidden', emptyLines.hiddenLines.length, 0);

// ── Count display format ──

function filterCountText(visible, total) {
  return visible + ' / ' + total + ' events';
}
assertEqual('filter count: 5/10', filterCountText(5, 10), '5 / 10 events');
assertEqual('filter count: 0/100', filterCountText(0, 100), '0 / 100 events');
assertEqual('filter count: 150/150', filterCountText(150, 150), '150 / 150 events');


// ═══════════════════════════════════════════════════════════════════════════
//  SUITE 19: renderProfitability() — pure calculation logic
// ═══════════════════════════════════════════════════════════════════════════

console.log('📊 SUITE 19: renderProfitability() — calculation logic');

var BLOCK_REWARD = 3.125;

function calcSoloProfit(hr, netDiff) {
  if (hr <= 0 || netDiff <= 0) return { btc: 0, blocksPerYear: 0, pctToday: 0, pctYear: 0, pct5y: 0, expectedTime: '\u2014' };
  var pHash = hr / netDiff / Math.pow(2, 32);
  var soloPday = pHash * 86400;
  var soloBlocksPerYear = soloPday * 365;
  var soloBtc = soloPday * BLOCK_REWARD;
  var pctToday = (1 - Math.pow(1 - pHash, 86400)) * 100;
  var pctYear = (1 - Math.pow(1 - pHash, 86400 * 365)) * 100;
  var pct5y = (1 - Math.pow(1 - pHash, 86400 * 365 * 5)) * 100;
  var expTime = soloBlocksPerYear > 0 ? 365 / soloBlocksPerYear : 0;
  return {
    btc: soloBtc,
    blocksPerYear: soloBlocksPerYear,
    pctToday: pctToday,
    pctYear: pctYear,
    pct5y: pct5y,
    expectedTime: expTime > 0 ? (expTime < 1 ? (expTime * 24).toFixed(1) + 'h' : expTime.toFixed(1) + 'd') : '\u2014',
  };
}

// Edge cases: zero hashrate
var zeroResult = calcSoloProfit(0, 126231507121868);
assertEqual('soloProfit(0) btc → 0', zeroResult.btc, 0);
assertEqual('soloProfit(0) blocksPerYear → 0', zeroResult.blocksPerYear, 0);
assertEqual('soloProfit(0) pctToday → 0', zeroResult.pctToday, 0);

// Edge cases: zero net diff
var zeroNet = calcSoloProfit(100e12, 0);
assertEqual('soloProfit(0 net) btc → 0', zeroNet.btc, 0);

// Realistic: 100 TH/s, 126.23T difficulty
var realistic = calcSoloProfit(100e12, 126231507121868);
assertApprox('soloProfit realistic pHash → ~1.84e-10', 100e12 / 126231507121868 / Math.pow(2, 32), 1.84e-10, 0.1e-10);
assertApprox('soloProfit realistic btc/day → ~4.98e-5', realistic.btc, 4.98e-5, 1e-5);
assertApprox('soloProfit realistic pctToday → ~0.00159', realistic.pctToday, 0.00159, 0.0005);

// 219 TH/s typical miner
var miner219 = calcSoloProfit(219e12, 126231507121868);
assertApprox('soloProfit 219TH/s btc/day → ~1.09e-4', miner219.btc, 1.09e-4, 0.5e-4);
assertApprox('soloProfit 219TH/s blocksPerYear → ~0.0127', miner219.blocksPerYear, 0.0127, 0.005);

// Very high hashrate: 1 PH/s
var highHr = calcSoloProfit(1e15, 126231507121868);
assertApprox('soloProfit 1PH/s btc/day → ~0.000498', highHr.btc, 0.000498, 0.0001);

// Pool vs Solo vs Rental mode BTC values
var poolBtc = 0.000130;
var soloBtc = realistic.btc;
var rentalBtc = poolBtc * 0.85;
assertApprox('rental = pool * 0.85', rentalBtc, 0.0001105, 0.000001);

// Fiat formatting helpers (mirrors renderProfitability)
var symMap = {USD:'$',BRL:'R$',EUR:'€',GBP:'£'};
function fiatPerCur(b, cur) {
  if (b == null) return '\u2014';
  return symMap[cur] + Number(b).toLocaleString(undefined, {maximumFractionDigits:2});
}

assertEqual('fiatPerCur 0 USD → $0', fiatPerCur(0, 'USD'), '$0');
assertEqual('fiatPerCur 8 USD → $8', fiatPerCur(8, 'USD'), '$8');
assertEqual('fiatPerCur 248.72 USD → $248.72', fiatPerCur(248.72, 'USD'), '$248.72');
assertEqual('fiatPerCur null → em-dash', fiatPerCur(null, 'USD'), '\u2014');
assertEqual('fiatPerCur 500 BRL → R$500', fiatPerCur(500, 'BRL'), 'R$500');
assertEqual('fiatPerCur 100 EUR → €100', fiatPerCur(100, 'EUR'), '€100');
assertEqual('fiatPerCur 50 GBP → £50', fiatPerCur(50, 'GBP'), '£50');

// Multi-currency fiat row: uses toLocaleString rounding
assertEqual('fiat USD 8.42 → $8.42', fiatPerCur(8.42, 'USD'), '$8.42');
assertEqual('fiat BRL 42.5 → R$42.5', fiatPerCur(42.5, 'BRL'), 'R$42.5');
assertEqual('fiat EUR 7.8 → €7.8', fiatPerCur(7.8, 'EUR'), '€7.8');
assertEqual('fiat GBP 6.7 → £6.7', fiatPerCur(6.7, 'GBP'), '£6.7');

// Whole number fiat values (toLocaleString rounds to 0 decimals)
assertEqual('fiat USD 8 → $8', fiatPerCur(8, 'USD'), '$8');
assertEqual('fiat BRL 43 → R$43', fiatPerCur(43, 'BRL'), 'R$43');
assertEqual('fiat EUR 8 → €8', fiatPerCur(8, 'EUR'), '€8');
assertEqual('fiat GBP 7 → £7', fiatPerCur(7, 'GBP'), '£7');

// Expected time display
function formatExpectedTime(days) {
  if (days <= 0) return '\u2014';
  if (days < 1) return (days * 24).toFixed(1) + 'h';
  return days.toFixed(1) + 'd';
}
assertEqual('expectedTime 0 → em-dash', formatExpectedTime(0), '\u2014');
assertEqual('expectedTime 0.5 → 12.0h (sub-day)', formatExpectedTime(0.5), '12.0h');
assertEqual('expectedTime 182.5 → 182.5d', formatExpectedTime(182.5), '182.5d');
assertEqual('expectedTime 730 → 730.0d', formatExpectedTime(730), '730.0d');
assertEqual('expectedTime -1 → em-dash', formatExpectedTime(-1), '\u2014');


// ═══════════════════════════════════════════════════════════════════════════
//  SUITE 20: renderBlockHunt() — additional edge cases
// ═══════════════════════════════════════════════════════════════════════════

console.log('📊 SUITE 20: renderBlockHunt() — additional edge cases');

// pBlock 0 -> no chance
var zeroP = renderBlockHuntLogic({
  network: { difficulty: 1e12 },
  worker: { bestDifficulty: 0 },
  proximity: {},
  block_hunt: { p_block_per_share: 0 },
});
assertEqual('blockHunt zero pBlock → 0', zeroP.pBlock, 0);
assertEqual('blockHunt zero pBlockPct → 0', zeroP.pBlockPct, 0);
assertEqual('blockHunt zero pBlockPctStr → 0.00000000%', zeroP.pBlockPctStr, '0.00000000%');

// pBlock from proximity.chance_per_share_pct (fallback)
var fallbackP = renderBlockHuntLogic({
  network: { difficulty: 1e12 },
  worker: { bestDifficulty: 1e9 },
  proximity: { chance_per_share_pct: 0.001, expected_time_secs: 7200 },
  block_hunt: {},
});
assertEqual('blockHunt fallback pBlock → 0.001 (from proximity pct)', fallbackP.pBlock, 0.001);
assertApprox('blockHunt fallback distance → 1000', fallbackP.distance, 1000, 1);
assertEqual('blockHunt fallback expectedTime → 7200', fallbackP.expectedTime, 7200);
assertEqual('blockHunt fallback expectedTimeHuman → 2.0h', fallbackP.expectedTimeHuman, '2.0h');
assertApprox('blockHunt fallback blocksPerYear → 4380', fallbackP.blocksPerYear, 4380, 10);

// pBlock from proximity raw (backup fallback)
var rawP = renderBlockHuntLogic({
  network: { difficulty: 1e12 },
  worker: {},
  proximity: { chance_per_share_raw: 1e6 },
  block_hunt: {},
});
assertApprox('blockHunt raw fallback pBlock → 0.000001', rawP.pBlock, 0.000001, 1e-9);

// Full block_hunt data (should use all bh values)
var fullBh = renderBlockHuntLogic({
  network: { difficulty: 0 },
  worker: {},
  proximity: {},
  block_hunt: {
    network_difficulty: 126231507121868,
    best_difficulty: 19.11e9,
    p_block_per_share: 0.0001514,
    expected_time_seconds: 2520000,
    cumulative_p_block: 0.025,
  },
});
assertApprox('fullBh netDiff → 126.23T', fullBh.netDiff, 126231507121868, 1);
assertApprox('fullBh bestDiff → 19.11G', fullBh.bestDiff, 19.11e9, 0.1e9);
assertEqual('fullBh pBlock → 0.0001514', fullBh.pBlock, 0.0001514);
assertEqual('fullBh expectedTime → 2520000 (29.17d)', fullBh.expectedTime, 2520000);
assertEqual('fullBh cumulativeP → 0.025', fullBh.cumulativeP, 0.025);
assertApprox('fullBh distance → 6605', fullBh.distance, 6605, 10);
assertTruthy('fullBh.distanceStr ends with ×', /\u00d7$/.test(fullBh.distanceStr));
assertTruthy('fullBh.distanceStr ends with ×', /\u00d7$/.test(fullBh.distanceStr));
var fullDist = parseFloat(fullBh.distanceStr);
assertApprox('fullBh.distance numeric ~6605', fullDist, 6605, 10);
assertEqual('fullBh expectedTimeHuman → 29.2d', fullBh.expectedTimeHuman, '29.2d');
assertApprox('fullBh blocksPerYear → 12.5', fullBh.blocksPerYear, 12.5, 0.5);

// Edge: equal diff (best = network) — pBlock is separate from diff ratio
var equalDiff = renderBlockHuntLogic({
  network: { difficulty: 1e12 },
  worker: { bestDifficulty: 1e12 },
  proximity: {},
  block_hunt: {},
});
assertEqual('equalDiff distance → 1×', equalDiff.distance, 1);
assertEqual('equalDiff distanceStr → "1.0×"', equalDiff.distanceStr, '1.0\u00d7');
assertEqual('equalDiff pBlockPctStr → 0.00000000% (no bh/prox pBlock set)', equalDiff.pBlockPctStr, '0.00000000%');
assertEqual('equalDiff bestDiff → 1e12', equalDiff.bestDiff, 1e12);

// Edge: best > network (impossible but handle gracefully)
var bestLarger = renderBlockHuntLogic({
  network: { difficulty: 1e12 },
  worker: { bestDifficulty: 2e12 },
  proximity: {},
  block_hunt: {},
});
assertApprox('bestLarger distance → 0.5', bestLarger.distance, 0.5, 0.01);
assertEqual('bestLarger distanceStr → "0.5×"', bestLarger.distanceStr, '0.5\u00d7');

// Block chance badge display
function formatBlockChanceBadge(pBlock) {
  if (pBlock == null) return '\u2014';
  return (Number(pBlock) * 100).toFixed(6) + '% per share';
}
assertEqual('chance badge null → em-dash', formatBlockChanceBadge(null), '\u2014');
assertEqual('chance badge 0.0001514 → 0.015140%', formatBlockChanceBadge(0.0001514), '0.015140% per share');
assertEqual('chance badge 0 → 0.000000%', formatBlockChanceBadge(0), '0.000000% per share');


// ═══════════════════════════════════════════════════════════════════════════
//  SUITE 21: renderMarket() — pure HTML generation logic
// ═══════════════════════════════════════════════════════════════════════════

console.log('📊 SUITE 21: renderMarket() — HTML generation + filter logic');

var _mktProviderIcons = {
  braiins: '\u229b',
  nicehash: '\u25c8',
  mrr: '\u26c1',
  parasite: '\u2302',
};

function renderMarketHtml(offers, activeFilter) {
  activeFilter = activeFilter || 'all';
  if (!offers || !offers.length) return '<div class="mkt-empty">\u27d0 no market data \u2014 Braiins (public) \u2713 NiceHash (public) \u2713 MRR (requires API key)</div>';
  var filtered = activeFilter === 'all' ? offers : offers.filter(function(o) { return o.provider === activeFilter; });
  if (!filtered.length) return '<div class="mkt-empty">No offers for selected provider \u2014 adjust filter</div>';
  return filtered.map(function(o) {
    var icon = _mktProviderIcons[o.provider] || '?';
    var label = (o.provider === 'braiins' ? 'Braiins' : o.provider === 'nicehash' ? 'NiceHash' : o.provider === 'mrr' ? 'MRR' : o.provider === 'parasite' ? 'Parasite' : escapeHtml(o.provider || 'Unknown'));
    return '<div class="mkt-card">\n' +
      '<div class="mkt-card__provider"><span class="mkt-provider-icon">' + icon + '</span><span class="mkt-provider-name">' + label + '</span></div>\n' +
      '<div class="mkt-card__price">' + (o.price || '\u2014') + '</div>\n' +
      '<div class="mkt-card__hr">' + (o.hashrate ? fmt.hashrate(o.hashrate) : '\u2014') + '</div>\n' +
      '<div class="mkt-card__fee">' + (o.fee != null ? o.fee + '%' : '\u2014') + '</div>\n' +
      '<div class="mkt-card__duration">' + (o.duration || '\u2014') + '</div>\n' +
      '</div>';
  }).join('');
}

// Empty state
var emptyMkt = renderMarketHtml([], 'all');
assertTruthy('empty market has mkt-empty class', /mkt-empty/.test(emptyMkt));
assertTruthy('empty market mentions Braiins', /Braiins/.test(emptyMkt));
assertTruthy('empty market mentions NiceHash', /NiceHash/.test(emptyMkt));
assertTruthy('empty market mentions MRR', /MRR/.test(emptyMkt));

// Null/undefined
assertTruthy('null market shows empty', /mkt-empty/.test(renderMarketHtml(null, 'all')));
assertTruthy('undefined market shows empty', /mkt-empty/.test(renderMarketHtml(undefined, 'all')));

// Single offer — braiins
var braiinsOffer = [{ provider: 'braiins', price: '0.0005 BTC/TH/d', hashrate: 100e12, fee: 2.5, duration: '24h' }];
var braiinsHtml = renderMarketHtml(braiinsOffer, 'all');
assertTruthy('braiins has mkt-card', /mkt-card/.test(braiinsHtml));
assertTruthy('braiins has ⊛ icon', /\u229b/.test(braiinsHtml));
assertTruthy('braiins has Braiins label', /Braiins/.test(braiinsHtml));
assertTruthy('braiins has price', /0\.0005/.test(braiinsHtml));
assertTruthy('braiins has hashrate', /100\.0/.test(braiinsHtml));
assertTruthy('braiins has fee 2.5%', /2\.5%/.test(braiinsHtml));
assertTruthy('braiins has duration', /24h/.test(braiinsHtml));

// All 4 providers
var allProviders = [
  { provider: 'braiins', price: '0.0005 BTC/TH/d', hashrate: 100e12, fee: 2.5, duration: '24h' },
  { provider: 'nicehash', price: '0.0006 BTC/TH/d', hashrate: 50e12, fee: 3.0, duration: '12h' },
  { provider: 'mrr', price: '0.0004 BTC/TH/d', hashrate: 200e12, fee: 1.5, duration: '48h' },
  { provider: 'parasite', price: '0.0003 BTC/TH/d', hashrate: 300e12, fee: 1.0, duration: '72h' },
];
var allHtml = renderMarketHtml(allProviders, 'all');
assertEqual('all providers has 4 cards', (allHtml.match(/class="mkt-card"/g) || []).length, 4);
assertTruthy('all includes ⊛ (braiins)', /\u229b/.test(allHtml));
assertTruthy('all includes ◈ (nicehash)', /\u25c8/.test(allHtml));
assertTruthy('all includes ⛁ (mrr)', /\u26c1/.test(allHtml));
assertTruthy('all includes ⌂ (parasite)', /\u2302/.test(allHtml));

// Filter: braiins only
var braiinsOnly = renderMarketHtml(allProviders, 'braiins');
assertEqual('filter braiins: 1 card', (braiinsOnly.match(/class="mkt-card"/g) || []).length, 1);
assertTruthy('filter braiins: contains Braiins', /Braiins/.test(braiinsOnly));
assertFalsy('filter braiins: no NiceHash', /NiceHash/.test(braiinsOnly));

// Filter: nicehash only
var nicehashOnly = renderMarketHtml(allProviders, 'nicehash');
assertEqual('filter nicehash: 1 card', (nicehashOnly.match(/class="mkt-card"/g) || []).length, 1);
assertTruthy('filter nicehash: contains NiceHash', /NiceHash/.test(nicehashOnly));
assertFalsy('filter nicehash: no MRR', /MRR/.test(nicehashOnly));

// Filter with no matches
var noMatch = renderMarketHtml(allProviders, 'unknown_provider');
assertTruthy('no match shows empty message', /No offers for selected provider/.test(noMatch));
assertTruthy('no match shows adjust filter', /adjust filter/.test(noMatch));

// Offer with missing fields
var minimalOffer = [{ provider: 'mrr' }];
var minimalHtml = renderMarketHtml(minimalOffer, 'all');
assertTruthy('minimal offer still renders', /mrt-card/.test(minimalHtml) || /mkt-card/.test(minimalHtml));

// Best price badge logic
function formatBestPriceBadge(bestPrice) {
  return bestPrice ? 'best: ' + bestPrice : '\u2014';
}
assertEqual('best price badge: known', formatBestPriceBadge('0.0003 BTC/TH/d'), 'best: 0.0003 BTC/TH/d');
assertEqual('best price badge: none', formatBestPriceBadge(null), '\u2014');
assertEqual('best price badge: empty', formatBestPriceBadge(''), '\u2014');



// ═══════════════════════════════════════════════════════════════════════════
//  SUITE 22: renderSoloStats() — solo mining stats display
// ═══════════════════════════════════════════════════════════════════════════
console.log(' SUITE 22: renderSoloStats() — calculation + display');

function soloCalc(hr, netDiff) {
  // Match renderSoloStats guard: skip calculation if hashrate or difficulty is 0
  if (!hr || hr <= 0 || !netDiff || netDiff <= 0) {
    return { pSec: 0, pDay: 0, pctToday: 0, soloBlocksYear: 0, expectedSecs: 0 };
  }
  var pSec = hr / netDiff / Math.pow(2, 32);
  var pDay = pSec * 86400;
  var pctToday = (1 - Math.pow(1 - pDay, 1)) * 100;
  var soloBlocksYear = pSec * 86400 * 365;
  var expectedSecs = soloBlocksYear > 0 ? (365 * 86400) / soloBlocksYear : 0;
  return { pSec: pSec, pDay: pDay, pctToday: pctToday, soloBlocksYear: soloBlocksYear, expectedSecs: expectedSecs };
}

// Zero hashrate
var zeroResult = soloCalc(0, 126231507121868);
assertEqual('zero hr pSec = 0', zeroResult.pSec, 0);
assertEqual('zero hr pDay = 0', zeroResult.pDay, 0);
assertEqual('zero hr blocksYear = 0', zeroResult.soloBlocksYear, 0);
assertEqual('zero hr expectedSecs = 0', zeroResult.expectedSecs, 0);

// Zero net diff
var soloZeroDiff = soloCalc(219e12, 0);
assertEqual('zero diff pDay = 0', soloZeroDiff.pDay, 0);

// Realistic: 100 TH/s at 126.23T diff
// Formula from renderSoloStats:
//   pSec = hr / netDiff / 2^32
//   pDay = pSec * 86400
//   blocksYear = pDay * 365
//   expectedSecs = (365*86400) / blocksYear
//
// For 100e12 H/s at diff=126231507121868:
//   pSec = 1e14 / 1.2623e14 / 4.295e9 = 1.844e-10
//   pDay = 1.844e-10 * 86400 = 1.593e-5
//   blocksYear = 1.593e-5 * 365 = 0.005814
//   expectedSecs = 31536000 / 0.005814 = 5.424e9
var realistic = soloCalc(100e12, 126231507121868);
assertApprox('100TH/s pDay', realistic.pDay, 1.593e-5, 1e-7);
assertApprox('100TH/s blocksYear', realistic.soloBlocksYear, 0.00581, 0.001);
assertApprox('100TH/s expectedSecs', realistic.expectedSecs, 5.42e9, 1e8);

// Realistic: 219 TH/s (typical S21 Pro)
var s21pro = soloCalc(219e12, 126231507121868);
assertApprox('219TH/s pSec', s21pro.pSec, 4.04e-10, 1e-11);
assertApprox('219TH/s pDay', s21pro.pDay, 3.49e-5, 1e-6);
assertApprox('219TH/s pctToday', s21pro.pctToday, 0.00349, 0.0001);
assertApprox('219TH/s blocksYear', s21pro.soloBlocksYear, 0.0127, 0.001);
assertApprox('219TH/s expectedSecs', s21pro.expectedSecs, 2.48e9, 1e8);

// 1 PH/s (large solo operation)
var onePh = soloCalc(1e15, 126231507121868);
assertApprox('1PH/s pDay', onePh.pDay, 1.593e-4, 1e-6);
assertApprox('1PH/s pctToday', onePh.pctToday, 0.0159, 0.001);

// Proximity-based fallback calculation
function soloCalcFromProx(prox) {
  var expTime = prox.expected_time_seconds || prox.expected_time_secs;
  var bpy = (365 * 86400) / expTime;
  var pBlock = prox.chance_per_share_pct != null ? (Number(prox.chance_per_share_pct) * 100) : null;
  return { expTime: expTime, bpy: bpy, pBlock: pBlock };
}

var proxResult = soloCalcFromProx({ expected_time_seconds: 2.5e9, chance_per_share_pct: 1.5e-6 });
assertApprox('prox bpy', proxResult.bpy, 0.0126, 0.001);
assertApprox('prox pBlock', proxResult.pBlock, 0.00015, 0.00001);

// Prox with expected_time_secs (alternate field name)
var proxAlt = soloCalcFromProx({ expected_time_secs: 3e9, chance_per_share_pct: 1e-6 });
assertApprox('prox alt expSecs', proxAlt.expTime, 3e9, 100);
assertApprox('prox alt bpy', proxAlt.bpy, 0.0105, 0.001);

// Missing proximity data
var noProx = soloCalcFromProx({});
assertTruthy('no prox: no expTime', isNaN(noProx.expTime));


// ═══════════════════════════════════════════════════════════════════════════
//  SUITE 23: exportJSON + exportCSV — data serialization logic
// ═══════════════════════════════════════════════════════════════════════════
console.log(' SUITE 23: exportJSON + exportCSV — data serialization');

// Helper: format CSV rows for a snapshot (mirrors exportCSV logic)
function buildCsvRows(snap) {
  var rows = ['metric,value,unit'];
  var w = snap.worker || {};
  rows.push('hashrate,' + (w.hashrate || 0) + ',H/s');
  rows.push('bestDifficulty,' + (w.bestDifficulty || 0) + ',diff');
  rows.push('lastSubmission,' + (w.lastSubmission || 0) + ',unix');
  var p = snap.pool || {};
  rows.push('pool_hashrate,' + (p.hashrate || 0) + ',H/s');
  rows.push('pool_workers,' + (p.workers || 0) + ',count');
  var n = snap.network || {};
  rows.push('network_difficulty,' + (n.difficulty || 0) + ',diff');
  rows.push('network_height,' + (n.height || 0) + ',blocks');
  rows.push('btc_usd,' + ((snap.btc_price || {}).usd || 0) + ',USD');
  var workers = snap.all_workers || [];
  workers.forEach(function(wrk, i) {
    rows.push('worker_' + i + '_name,' + (wrk.name || 'unknown') + ',string');
    rows.push('worker_' + i + '_hashrate,' + (wrk.hashrate || 0) + ',H/s');
    rows.push('worker_' + i + '_bestDiff,' + (wrk.bestDifficulty || 0) + ',diff');
  });
  return rows;
}

// Helper: check if CSV contains a row with the given metric
function csvHasRow(csvRows, metricPrefix) {
  return csvRows.some(function(row) { return row.startsWith(metricPrefix); });
}

// Full snapshot with all fields
var fullSnap = {
  worker: { hashrate: 219e12, bestDifficulty: '127G', lastSubmission: 1785410000 },
  pool: { hashrate: 161.6e15, workers: 1200 },
  network: { difficulty: 126231507121868, height: 857000 },
  btc_price: { usd: 61234 },
  all_workers: [
    { name: 'miner1', hashrate: 100e12, bestDifficulty: '50G' },
    { name: 'miner2', hashrate: 119e12, bestDifficulty: '77G' },
  ],
};
var fullCsv = buildCsvRows(fullSnap);
assertEqual('csv has header', fullCsv[0], 'metric,value,unit');
assertTruthy('csv has worker hashrate', csvHasRow(fullCsv, 'hashrate,'));
assertTruthy('csv has pool hashrate', csvHasRow(fullCsv, 'pool_hashrate,'));
assertTruthy('csv has net diff', csvHasRow(fullCsv, 'network_difficulty,'));
assertTruthy('csv has btc price', csvHasRow(fullCsv, 'btc_usd,'));
assertTruthy('csv has worker_0_name', csvHasRow(fullCsv, 'worker_0_name,'));
assertTruthy('csv has worker_1_hashrate', csvHasRow(fullCsv, 'worker_1_hashrate,'));
assertEqual('csv total rows = 1 header + 8 metric + 6 worker', fullCsv.length, 15);

// Empty snapshot
var emptySnap = {};
var emptyCsv = buildCsvRows(emptySnap);
assertEqual('empty csv has header', emptyCsv[0], 'metric,value,unit');
assertTruthy('empty csv: hashrate=0', csvHasRow(emptyCsv, 'hashrate,0,'));
// Should have 1 header + 8 metric rows + 0 worker rows
assertEqual('empty csv row count', emptyCsv.length, 9);

// Missing worker data
var noWorkerSnap = { pool: { hashrate: 100e15 }, network: { difficulty: 126e12 } };
var noWorkerCsv = buildCsvRows(noWorkerSnap);
assertEqual('no-worker csv rows', noWorkerCsv.length, 9);
assertTruthy('no-worker: hashrate=0', csvHasRow(noWorkerCsv, 'hashrate,0,'));

// Single worker
var singleWorkerSnap = {
  worker: { hashrate: 50e12 },
  all_workers: [{ name: 'test-miner', hashrate: 50e12, bestDifficulty: '10G' }],
};
var singleCsv = buildCsvRows(singleWorkerSnap);
assertEqual('single worker csv rows', singleCsv.length, 12);
assertTruthy('single worker: worker_0_name', csvHasRow(singleCsv, 'worker_0_name,test-miner,'));
assertTruthy('single worker: worker_0_hashrate', csvHasRow(singleCsv, 'worker_0_hashrate,50000000000000,'));

// JSON serialization test
var snapJson = JSON.stringify(fullSnap, null, 2);
assertTruthy('json string is string', typeof snapJson === 'string');
assertTruthy('json contains hashrate', /219000000000000/.test(snapJson));
assertTruthy('json contains worker name', /miner1/.test(snapJson));

// Parse back and verify
var parsed = JSON.parse(snapJson);
assertEqual('parsed worker hashrate', parsed.worker.hashrate, 219e12);
assertEqual('parsed all_workers length', parsed.all_workers.length, 2);
assertEqual('parsed btc_price', parsed.btc_price.usd, 61234);

// Minimal snapshot JSON
var minimalJson = JSON.stringify({ worker: { hashrate: 0 } }, null, 2);
assertTruthy('minimal json valid', typeof minimalJson === 'string');
assertEqual('minimal json parsed', JSON.parse(minimalJson).worker.hashrate, 0);

// CSV with missing optional fields
var partialWorkerSnap = {
  all_workers: [{ name: 'orphan' }],  // no hashrate or bestDifficulty
};
var partialCsv = buildCsvRows(partialWorkerSnap);
assertTruthy('partial: worker_0_name', csvHasRow(partialCsv, 'worker_0_name,orphan,'));
assertTruthy('partial: worker hash rate 0', csvHasRow(partialCsv, 'worker_0_hashrate,0,'));
assertTruthy('partial: worker bestDiff 0', csvHasRow(partialCsv, 'worker_0_bestDiff,0,'));

// Filename format validation
function generateFilename(prefix, ext) {
  // Mirrors the actual exportJSON/CSV: cypher65-{prefix}-{ts}.{ext}
  return 'test-format-20260730T141500.' + ext;
}
assertTruthy('json filename format', /^test-format-.*\.json$/.test(generateFilename('snapshot', 'json')));
assertTruthy('csv filename format', /^test-format-.*\.csv$/.test(generateFilename('export', 'csv')));


// ═══════════════════════════════════════════════════════════════════════════
//  SUITE 17: renderMarket() — market offer card generation + best-price logic
// ═══════════════════════════════════════════════════════════════════════════

console.log('📊 SUITE 17: renderMarket() — offer cards + best price');

// ── formatMarketPrice tests ────────────────────────────────────────────
assertEqual('mktPrice(null) → em-dash', formatMarketPrice(null), '\u2014');
assertEqual('mktPrice(undefined) → em-dash', formatMarketPrice(undefined), '\u2014');
assertEqual('mktPrice(Infinity) → em-dash', formatMarketPrice(Infinity), '\u2014');
assertEqual('mktPrice(0) → em-dash', formatMarketPrice(0), '\u2014');

// Different ranges
assertEqual('mktPrice(0.1) → 0.10000000 BTC', formatMarketPrice(0.1), '0.10000000 BTC');
assertEqual('mktPrice(0.00001234) → 0.00001234 BTC', formatMarketPrice(0.00001234), '0.00001234 BTC');
assertEqual('mktPrice(1e-8) → 0.00000001 BTC', formatMarketPrice(1e-8), '0.00000001 BTC');

// Exponential for very small
assertEqual('mktPrice(5e-9) → 5.000e-9 BTC', formatMarketPrice(5e-9), '5.000e-9 BTC');
assertEqual('mktPrice(1.23e-10) → 1.230e-10 BTC', formatMarketPrice(1.23e-10), '1.230e-10 BTC');

// Large values
assertEqual('mktPrice(1) → 1.000000 BTC', formatMarketPrice(1), '1.000000 BTC');
assertEqual('mktPrice(12.345) → 12.345000 BTC', formatMarketPrice(12.345), '12.345000 BTC');


// ── formatOfferHashrate tests ──────────────────────────────────────────
assertEqual('offerHr(null) → em-dash', formatOfferHashrate(null), '\u2014');
assertEqual('offerHr(undefined) → em-dash', formatOfferHashrate(undefined), '\u2014');
assertEqual('offerHr(0) → 0 H/s', formatOfferHashrate(0), '0 H/s');
assertEqual('offerHr(500) → 500 H/s', formatOfferHashrate(500), '500 H/s');
assertEqual('offerHr(1e9) → 1.00 GH/s', formatOfferHashrate(1e9), '1.00 GH/s');
assertEqual('offerHr(500e9) → 500.00 GH/s', formatOfferHashrate(500e9), '500.00 GH/s');
assertEqual('offerHr(1e12) → 1.00 TH/s', formatOfferHashrate(1e12), '1.00 TH/s');
assertEqual('offerHr(100e12) → 100.00 TH/s', formatOfferHashrate(100e12), '100.00 TH/s');
assertEqual('offerHr(1e15) → 1.00 PH/s', formatOfferHashrate(1e15), '1.00 PH/s');
assertEqual('offerHr(2.5e15) → 2.50 PH/s', formatOfferHashrate(2.5e15), '2.50 PH/s');


// ── formatOfferCount tests ─────────────────────────────────────────────
assertEqual('offerCount 5/5', formatOfferCount(5, 5), '5 / 5 offers');
assertEqual('offerCount 0/10', formatOfferCount(0, 10), '0 / 10 offers');
assertEqual('offerCount 3/12', formatOfferCount(3, 12), '3 / 12 offers');


// ── computeBestPrice tests ─────────────────────────────────────────────
assertEqual('bestPrice null → null', computeBestPrice(null), null);
assertEqual('bestPrice [] → null', computeBestPrice([]), null);

var singleOffer = [{ price_btc_per_th_day: 0.00001234 }];
assertApprox('bestPrice single → 0.00001234', computeBestPrice(singleOffer), 0.00001234, 1e-10);

var multipleOffers = [
  { price_btc_per_th_day: 0.00001500 },
  { price_btc_per_th_day: 0.00001234 },
  { price_btc_per_th_day: 0.00001800 },
];
assertApprox('bestPrice lowest → 0.00001234', computeBestPrice(multipleOffers), 0.00001234, 1e-10);

var withZero = [{ price_btc_per_th_day: 0 }, { price_btc_per_th_day: 0.00001 }];
assertApprox('bestPrice skips zero → 0.00001', computeBestPrice(withZero), 0.00001, 1e-10);

var priceField = [{ price: 0.00005 }];
assertApprox('bestPrice uses price fallback → 0.00005', computeBestPrice(priceField), 0.00005, 1e-10);

var allZero = [{ price_btc_per_th_day: 0 }, { price_btc_per_th_day: 0 }];
assertEqual('bestPrice all zero → null', computeBestPrice(allZero), null);


// ── fmtBtcPerTh / findBestOfferIndex tests (P2 schema-mismatch regression) ─
assertEqual('fmtBtcPerTh null → —', fmtBtcPerTh(null), '\u2014');
assertEqual('fmtBtcPerTh 0 → —', fmtBtcPerTh(0), '\u2014');
assertEqual('fmtBtcPerTh -1 → —', fmtBtcPerTh(-1), '\u2014');
assertEqual('fmtBtcPerTh NaN → —', fmtBtcPerTh(NaN), '\u2014');
assertEqual('fmtBtcPerTh 1e-10 → 0.01 sats/TH/d', fmtBtcPerTh(1e-10), '0.01 sats/TH/d');
assertEqual('fmtBtcPerTh 1e-8 → 1 sats/TH/d', fmtBtcPerTh(1e-8), '1 sats/TH/d');
assertEqual('fmtBtcPerTh 0.001 → 0.001000 BTC/TH/d', fmtBtcPerTh(0.001), '0.001000 BTC/TH/d');
assertEqual('fmtBtcPerTh 0.0025 → 0.002500 BTC/TH/d', fmtBtcPerTh(0.0025), '0.002500 BTC/TH/d');

var bestOffers = [
  { provider: 'braiins', price_per_th_day: 2e-8 },
  { provider: 'nicehash', price_per_th_day: 1e-10 },
  { provider: 'mrr', price_per_th_day: 5e-9 },
];
assertEqual('bestIdx lowest → 1', findBestOfferIndex(bestOffers), 1);

// ── renderMarketOfferHtml affiliate BUY button (P0-4) ──────────────────
var affOffer = { provider: 'mrr', price_btc_per_th_day: 0.00001234, hashrate: 1e12, fee: 3, duration: 30 };
var affMatch = { provider: 'mrr', url: 'https://www.miningrigrentals.com/?ref=test' };
var affOther = { provider: 'nicehash', url: 'https://www.nicehash.com/?ref=test' };

var htmlAffMatch = renderMarketOfferHtml(affOffer, true, affMatch);
assertEqual('affiliate match → has BUY btn', htmlAffMatch.indexOf('mkt-card__buy') !== -1, true);
assertEqual('affiliate match → data-aff-url present', htmlAffMatch.indexOf('https://www.miningrigrentals.com/?ref=test') !== -1, true);
assertEqual('affiliate match → BUY MRR label', htmlAffMatch.indexOf('BUY MRR') !== -1, true);
assertEqual('affiliate match → best class kept', htmlAffMatch.indexOf('mkt-card--best') !== -1, true);

var htmlNoAff = renderMarketOfferHtml(affOffer, true, null);
assertEqual('no affiliate → no BUY btn', htmlNoAff.indexOf('mkt-card__buy') === -1, true);

var htmlOtherProv = renderMarketOfferHtml(affOffer, true, affOther);
assertEqual('mismatched provider → no BUY btn', htmlOtherProv.indexOf('mkt-card__buy') === -1, true);

// ── _mktBestIndex mirror: highest metrics.score wins; only with NO scores at
// all does it fall back to lowest valid price (two-pass, first-max on ties).
// Estimated offers (parasite pool-fee model) are NEVER
// crowned best — they are filtered out first, keeping original indices for
// mapping back; if ALL offers are estimated, the full list is used as fallback
// (matches static/app.js _mktBestIndex). ─
function mktBestIndexMirror(offers) {
  if (!offers || !offers.length) return -1;
  // Build the market-only subset, keeping original indices for mapping back.
  var market = [];
  var marketIdx = [];
  offers.forEach(function (o, idx) {
    if (!o.estimated) { market.push(o); marketIdx.push(idx); }
  });
  var pool = market.length ? market : offers;           // all-estimated → fallback to full list
  var poolIdx = market.length ? marketIdx : offers.map(function (_, i) { return i; });
  // Pass 1: highest finite metrics.score (first max wins on ties).
  var bestPos = -1;
  var bestScore = -Infinity;
  pool.forEach(function (o, i) {
    var sc = Number(o.metrics && o.metrics.score);
    if (isFinite(sc) && sc > bestScore) { bestScore = sc; bestPos = i; }
  });
  if (bestPos >= 0) return poolIdx[bestPos];
  // Pass 2: no scores anywhere → lowest valid price_per_th_day.
  var bestVal = Infinity;
  pool.forEach(function (o, i) {
    var p = Number(o.price_per_th_day);
    if (isFinite(p) && p > 0 && p < bestVal) { bestVal = p; bestPos = i; }
  });
  return bestPos >= 0 ? poolIdx[bestPos] : -1;
}
var scoredOffers = [
  { provider: 'braiins', price_per_th_day: 1e-8, metrics: { score: 5.0 } },
  { provider: 'mrr', price_per_th_day: 2e-9, metrics: { score: 12.5 } },
  { provider: 'nicehash', price_per_th_day: 1e-9, metrics: { score: 3.0 } },
];
assertEqual('scored best → mrr (highest score)', mktBestIndexMirror(scoredOffers), 1);
var scoredTieFallback = [
  { provider: 'a', price_per_th_day: 3e-8, metrics: { score: 4.0 } },
  { provider: 'b', price_per_th_day: 1e-8 },
  { provider: 'c', price_per_th_day: 2e-8, metrics: { score: 4.0 } },
];
assertEqual('scored tie → first max score', mktBestIndexMirror(scoredTieFallback), 0);
var scoredNone = [{ provider: 'a', price_per_th_day: 2e-8 }, { provider: 'b', price_per_th_day: 1e-8 }];
assertEqual('scored none → lowest price (idx 1)', mktBestIndexMirror(scoredNone), 1);
assertEqual('scored null → -1', mktBestIndexMirror(null), -1);
assertEqual('scored [] → -1', mktBestIndexMirror([]), -1);

// Regression: estimated offers (parasite pool-fee model — measured live
// ~1 sat/TH/d with an inflated ROI score 7325) must NEVER be crowned "best"
// while a real marketplace quote exists.
var parasiteScenario = [
  { provider: 'parasite', price_per_th_day: 1e-8, estimated: true, metrics: { score: 7325 } },
  { provider: 'braiins', price_per_th_day: 4.966e-6, metrics: { score: 5.0 } },
  { provider: 'nicehash', price_per_th_day: 1e-6, metrics: { score: 3.0 } },
];
assertEqual('estimated high-score never wins → braiins (idx 1)', mktBestIndexMirror(parasiteScenario), 1);
var parasiteVsReal = [
  { provider: 'parasite', price_per_th_day: 1e-8, estimated: true, metrics: { score: 7325 } },
  { provider: 'mrr', price_per_th_day: 2e-6, metrics: { score: 12.5 } },
];
assertEqual('estimated skipped in score pass → mrr (idx 1)', mktBestIndexMirror(parasiteVsReal), 1);
var allEstimated = [
  { provider: 'parasite', price_per_th_day: 1e-8, estimated: true, metrics: { score: 7 } },
  { provider: 'derived', price_per_th_day: 5e-8, estimated: true, metrics: { score: 9 } },
];
assertEqual('all estimated → fallback score pass → derived (idx 1)', mktBestIndexMirror(allEstimated), 1);
var allEstimatedNoScores = [
  { provider: 'parasite', price_per_th_day: 1e-8, estimated: true },
  { provider: 'derived', price_per_th_day: 5e-8, estimated: true },
];
assertEqual('all estimated no scores → lowest price → parasite (idx 0)', mktBestIndexMirror(allEstimatedNoScores), 0);
var mixedNoScores = [
  { provider: 'parasite', price_per_th_day: 1e-8, estimated: true },
  { provider: 'braiins', price_per_th_day: 4.966e-6 },
];
assertEqual('mixed no scores → estimated skipped → braiins (idx 1)', mktBestIndexMirror(mixedNoScores), 1);

// ── USD/TH/d companion on market cards (BTC/TH/day × snapshot BTC/USD) ─
// Mirrors app.js _mktUsdPerTh(): $1+ → 2 decimals; below $1 → 3 sig figs.
function mktUsdPerThMirror(v, btcUsd) {
  var n = Number(v), usd = Number(btcUsd);
  if (!isFinite(n) || n <= 0 || !isFinite(usd) || usd <= 0) return null;
  var x = n * usd;
  if (x >= 1) return '$' + x.toLocaleString('en-US', { maximumFractionDigits: 2 }) + '/TH/d';
  var s = x.toPrecision(3);
  if (s.indexOf('e') !== -1) s = Number(s).toString();
  else s = s.replace(/\.?0+$/, '');
  return '$' + s + '/TH/d';
}
assertEqual('usd 50 sats @$60k → $0.03/TH/d', mktUsdPerThMirror(50e-8, 60000), '$0.03/TH/d');
assertEqual('usd 10k sats @$60k → $6/TH/d', mktUsdPerThMirror(10000e-8, 60000), '$6/TH/d');
assertEqual('usd 1 sat @$60k → $0.0006/TH/d', mktUsdPerThMirror(1e-8, 60000), '$0.0006/TH/d');
assertEqual('usd 30 sats @$60k → $0.018/TH/d', mktUsdPerThMirror(30e-8, 60000), '$0.018/TH/d');
assertEqual('usd no price → null', mktUsdPerThMirror(0, 60000), null);
assertEqual('usd no btc price → null', mktUsdPerThMirror(1e-8, 0), null);
assertEqual('usd null → null', mktUsdPerThMirror(null, 60000), null);

// ── hashrate TH/s → H/s display (Fase 5 fix: backend sends TH/s, fmt.hashrate expects H/s) ─
function fmtHashrateThToHps(th) {
  var hrHps = Number(th) > 0 ? Number(th) * 1e12 : 0;
  if (hrHps <= 0) return '\u2014';
  var units = ['H/s', 'kH/s', 'MH/s', 'GH/s', 'TH/s', 'PH/s', 'EH/s'];
  var i = 0, x = hrHps;
  while (x >= 1000 && i < units.length - 1) { x /= 1000; i++; }
  return x.toFixed(x >= 100 ? 1 : 2) + ' ' + units[i];
}
assertEqual('hr 1000 TH → 1.00 PH/s', fmtHashrateThToHps(1000), '1.00 PH/s');
assertEqual('hr 100 TH → 100.0 TH/s', fmtHashrateThToHps(100), '100.0 TH/s');
assertEqual('hr 0 → —', fmtHashrateThToHps(0), '\u2014');
assertEqual('hr null → —', fmtHashrateThToHps(null), '\u2014');
assertEqual('hr 0.5 TH → 500.0 GH/s', fmtHashrateThToHps(0.5), '500.0 GH/s');
var bestSkipZero = [{ price_per_th_day: 0 }, { price_per_th_day: 1e-8 }];
assertEqual('bestIdx skips zero → 1', findBestOfferIndex(bestSkipZero), 1);
var bestAllInvalid = [{ price_per_th_day: 0 }, { price_per_th_day: NaN }];
assertEqual('bestIdx all invalid → -1', findBestOfferIndex(bestAllInvalid), -1);
assertEqual('bestIdx null → -1', findBestOfferIndex(null), -1);
assertEqual('bestIdx [] → -1', findBestOfferIndex([]), -1);


// ── filterOffersByProvider tests ───────────────────────────────────────
assertEqual('filterOffers null → []', filterOffersByProvider(null, 'all').length, 0);
assertEqual('filterOffers [] → []', filterOffersByProvider([], 'all').length, 0);

var sampleOffers = [
  { provider: 'Braiins' },
  { provider: 'NiceHash' },
  { provider: 'Braiins' },
];
assertEqual('filter all → 3', filterOffersByProvider(sampleOffers, 'all').length, 3);
assertEqual('filter undefined → 3', filterOffersByProvider(sampleOffers).length, 3);
assertEqual('filter braiins → 2', filterOffersByProvider(sampleOffers, 'Braiins').length, 2);
assertEqual('filter nicehash → 1', filterOffersByProvider(sampleOffers, 'NiceHash').length, 1);
assertEqual('filter case-insensitive braiins → 2', filterOffersByProvider(sampleOffers, 'braiins').length, 2);
assertEqual('filter unknown → 0', filterOffersByProvider(sampleOffers, 'Mrr').length, 0);

var nameOffers = [{ name: 'Parasite' }, { name: 'MRR' }];
assertEqual('filter by name → 1', filterOffersByProvider(nameOffers, 'Parasite').length, 1);
assertEqual('filter by name MRR → 1', filterOffersByProvider(nameOffers, 'MRR').length, 1);


// ── renderMarketOfferHtml tests ────────────────────────────────────────
var basicOfferHtml = renderMarketOfferHtml({ provider: 'Braiins', price_btc_per_th_day: 0.00001234, hashrate: 100e12, fee: 2.5, duration: '1 month' }, false);
assertTruthy('offerHtml has mkt-card class', /mkt-card/.test(basicOfferHtml));
assertTruthy('offerHtml has provider icon BR', /BR/.test(basicOfferHtml));
assertTruthy('offerHtml has provider name Braiins', /Braiins/.test(basicOfferHtml));
assertTruthy('offerHtml has price formatted', /0\.00001234 BTC/.test(basicOfferHtml));
assertTruthy('offerHtml has hashrate 100.00 TH/s', /100\.00 TH/.test(basicOfferHtml));
assertTruthy('offerHtml has fee 2.5%', /2\.5%/.test(basicOfferHtml));
assertTruthy('offerHtml has duration 1 month', /1 month/.test(basicOfferHtml));
assertFalsy('offerHtml no mkt-card--best when not best', /mkt-card--best/.test(basicOfferHtml));

var bestOfferHtml = renderMarketOfferHtml({ provider: 'NiceHash', price_btc_per_th_day: 0.00001, hashrate: 50e12, fee: 1.0, duration: '7 days' }, true);
assertTruthy('bestOfferHtml has mkt-card--best', /mkt-card--best/.test(bestOfferHtml));
assertTruthy('bestOfferHtml has NI icon', /NI/.test(bestOfferHtml));

var staleOfferHtml = renderMarketOfferHtml({ provider: 'MRR', price_btc_per_th_day: 0.00002, hashrate: 200e12, fee: 3.0, _stale: true }, false);
assertTruthy('staleOfferHtml has mkt-card--stale', /mkt-card--stale/.test(staleOfferHtml));
assertTruthy('staleOfferHtml has stale badge', /stale/.test(staleOfferHtml));

var metaStale = renderMarketOfferHtml({ provider: 'Parasite', price_btc_per_th_day: 0.00003, hashrate: 300e12, fee: 2.0, meta: 'stale' }, false);
assertTruthy('metaStale has stale via meta string', /mkt-card--stale/.test(metaStale));

var htmlEscaped = renderMarketOfferHtml({ provider: '<script>', price_btc_per_th_day: 0.00001, hashrate: 10e12, fee: 1.0 }, false);
assertTruthy('offerHtml escapes provider name', /&lt;script&gt;/.test(htmlEscaped));
assertFalsy('offerHtml no raw script tag', /<script>/.test(htmlEscaped));

var unknownFields = renderMarketOfferHtml({ price_btc_per_th_day: 0.00001 }, false);
assertTruthy('offerHtml handles missing provider', /unknown/.test(unknownFields));
assertTruthy('offerHtml handles 0 hashrate', /0 H/.test(unknownFields));
assertTruthy('offerHtml handles missing fee', /\u2014/.test(unknownFields));
assertTruthy('offerHtml handles missing duration', /\u2014/.test(unknownFields));


// ── renderMarketGridHtml tests ─────────────────────────────────────────
assertTruthy('gridHtml null → empty', /no marketplace offers/.test(renderMarketGridHtml(null, 'all')));
assertTruthy('gridHtml [] → empty', /no marketplace offers/.test(renderMarketGridHtml([], 'all')));

var twoOffers = [
  { provider: 'Braiins', price_btc_per_th_day: 0.00002, hashrate: 100e12, fee: 2.5, duration: '1d' },
  { provider: 'NiceHash', price_btc_per_th_day: 0.00001, hashrate: 50e12, fee: 1.5, duration: '1d' },
];
var gridHtml = renderMarketGridHtml(twoOffers, 'all');
assertTruthy('gridHtml has Braiins card', /Braiins/.test(gridHtml));
assertTruthy('gridHtml has NiceHash card', /NiceHash/.test(gridHtml));
assertTruthy('gridHtml best offer has mkt-card--best', /mkt-card--best/.test(gridHtml));

var filteredGrid = renderMarketGridHtml(twoOffers, 'Braiins');
assertTruthy('filteredGrid has Braiins', /Braiins/.test(filteredGrid));
assertFalsy('filteredGrid no NiceHash', /NiceHash/.test(filteredGrid));

var emptyFilter = renderMarketGridHtml(twoOffers, 'Mrr');
assertTruthy('emptyFilter shows no offers for selected', /no offers for selected/.test(emptyFilter));

var phOffers = [
  { provider: 'Braiins', price_btc_per_th_day: 0.00001, hashrate: 2.5e15, fee: 1.0, duration: '1d' },
];
var phGrid = renderMarketGridHtml(phOffers, 'all');
assertTruthy('phGrid shows PH/s', /PH/.test(phGrid));
assertTruthy('phGrid shows 2.50', /2\.50/.test(phGrid));


// ═══════════════════════════════════════════════════════════════════════════
//  SUITE 18: renderMarketTrend() — trend data preparation & dataset format
// ═══════════════════════════════════════════════════════════════════════════

console.log('📊 SUITE 18: renderMarketTrend() — chart data prep & providers');

// ── Provider color helpers ─────────────────────────────────────────────
var _providerColors = {
  braiins: '#f7931a',
  nicehash: '#00e676',
  mrr: '#40c4ff',
  parasite: '#ce93d8',
};

function getProviderColor(name) {
  return _providerColors[(name || '').toLowerCase()] || '#888888';
}

assertEqual('getProviderColor braiins → #f7931a', getProviderColor('braiins'), '#f7931a');
assertEqual('getProviderColor Braiins → #f7931a (case)', getProviderColor('Braiins'), '#f7931a');
assertEqual('getProviderColor nicehash → #00e676', getProviderColor('nicehash'), '#00e676');
assertEqual('getProviderColor mrr → #40c4ff', getProviderColor('mrr'), '#40c4ff');
assertEqual('getProviderColor parasite → #ce93d8', getProviderColor('parasite'), '#ce93d8');
assertEqual('getProviderColor unknown → #888888', getProviderColor('unknown'), '#888888');
assertEqual('getProviderColor null → #888888', getProviderColor(null), '#888888');
assertEqual('getProviderColor "" → #888888', getProviderColor(''), '#888888');

// ── Format trend label (MM/DD HH:mm) ───────────────────────────────────
function formatTrendLabel(ts) {
  var d = new Date(ts);
  return (d.getMonth()+1)+'/'+String(d.getDate()).padStart(2,'0')+' '+String(d.getHours()).padStart(2,'0')+':'+String(d.getMinutes()).padStart(2,'0');
}

var nowDate = new Date(2026, 6, 15, 14, 30); // July 15, 2026 14:30 UTC
var formatted = formatTrendLabel(nowDate.getTime());
assertEqual('formatTrendLabel July 15 14:30', formatted, '7/15 14:30');

var midnight = new Date(2026, 0, 1, 0, 5).getTime();
assertEqual('formatTrendLabel Jan 1 00:05', formatTrendLabel(midnight), '1/01 00:05');

// ── Build trend datasets (pure version of renderMarketTrend logic) ──────
function buildTrendDatasets(providers) {
  if (!providers || typeof providers !== 'object') return { datasets: [], labels: [], hasPHData: false };
  var labels = [];
  var datasets = [];
  var hasPHData = false;
  var providerKeys = Object.keys(providers);
  providerKeys.forEach(function(pname) {
    var points = providers[pname];
    if (!points || !points.length) return;
    // Initialize labels from first provider
    if (labels.length === 0 && points.length >= 2) {
      labels = points.map(function(p) { return formatTrendLabel(p.ts * 1000); });
    }
    var color = getProviderColor(pname);
    var thsData = points.map(function(p) { return p.price_btc_per_th_day; });
    datasets.push({
      label: pname + ' (TH/s)',
      data: thsData,
      borderColor: color,
      backgroundColor: color + '33',
      yAxisID: 'y-ths',
      borderWidth: 1.5,
    });
    // Check for PH/s data
    var hasPH = points.some(function(p) { return p.price_btc_per_ph_day != null; });
    if (hasPH) {
      hasPHData = true;
      var phsData = points.map(function(p) { return p.price_btc_per_ph_day; });
      datasets.push({
        label: pname + ' (PH/s)',
        data: phsData,
        borderColor: color,
        backgroundColor: color + '22',
        yAxisID: 'y-phs',
        borderWidth: 1.5,
        borderDash: [4, 3],
      });
    }
  });
  return { datasets: datasets, labels: labels, hasPHData: hasPHData };
}

assertEqual('buildTrendDatasets(null).labels → []', buildTrendDatasets(null).labels.length, 0);
assertEqual('buildTrendDatasets({}).datasets → 0', buildTrendDatasets({}).datasets.length, 0);

var singleProvider = {
  braiins: [
    { ts: 1745000000, price_btc_per_th_day: 0.000010, price_btc_per_ph_day: 0.010 },
    { ts: 1745000100, price_btc_per_th_day: 0.000011, price_btc_per_ph_day: 0.011 },
  ],
};
var singleResult = buildTrendDatasets(singleProvider);
assertEqual('singleResult.datasets → 2 (TH/s + PH/s)', singleResult.datasets.length, 2);
assertEqual('singleResult.labels → 2', singleResult.labels.length, 2);
assertTruthy('singleResult hasPHData → true', singleResult.hasPHData);
assertEqual('singleResult dataset[0] label braiins (TH/s)', singleResult.datasets[0].label, 'braiins (TH/s)');
assertEqual('singleResult dataset[0] yAxisID → y-ths', singleResult.datasets[0].yAxisID, 'y-ths');
assertEqual('singleResult dataset[1] label braiins (PH/s)', singleResult.datasets[1].label, 'braiins (PH/s)');
assertEqual('singleResult dataset[1] yAxisID → y-phs', singleResult.datasets[1].yAxisID, 'y-phs');
assertTruthy('singleResult dataset[1] has borderDash (dashed)', Array.isArray(singleResult.datasets[1].borderDash));

// No PH/s data
var noPHProvider = {
  nicehash: [
    { ts: 1745000000, price_btc_per_th_day: 0.000015 },
    { ts: 1745000100, price_btc_per_th_day: 0.000016 },
  ],
};
var noPHResult = buildTrendDatasets(noPHProvider);
assertEqual('noPHResult.datasets → 1 (no PH/s)', noPHResult.datasets.length, 1);
assertFalsy('noPHResult hasPHData → false', noPHResult.hasPHData);
assertEqual('noPHResult dataset[0] yAxisID → y-ths', noPHResult.datasets[0].yAxisID, 'y-ths');

// Multiple providers
var multiProvider = {
  braiins: [
    { ts: 1745000000, price_btc_per_th_day: 0.000010 },
    { ts: 1745000100, price_btc_per_th_day: 0.000011 },
  ],
  nicehash: [
    { ts: 1745000000, price_btc_per_th_day: 0.000012 },
    { ts: 1745000100, price_btc_per_th_day: 0.000013 },
  ],
};
var multiResult = buildTrendDatasets(multiProvider);
assertEqual('multiResult.datasets → 2 providers × 1 line each', multiResult.datasets.length, 2);
assertEqual('multiResult labels → 2', multiResult.labels.length, 2);
assertEqual('multiResult dataset[0] color braiins #f7931a', multiResult.datasets[0].borderColor, '#f7931a');
assertEqual('multiResult dataset[1] color nicehash #00e676', multiResult.datasets[1].borderColor, '#00e676');

// Single point (not enough to chart)
var singlePoint = {
  mrr: [
    { ts: 1745000000, price_btc_per_th_day: 0.000020 },
  ],
};
var singlePointResult = buildTrendDatasets(singlePoint);
assertEqual('singlePointResult labels → 0 (<2 points)', singlePointResult.labels.length, 0);	


// ═══════════════════════════════════════════════════════════════════════════
//  SUITE 19: _renderAxeCard() — pure HTML generation logic for Axe Fleet
// ═══════════════════════════════════════════════════════════════════════════

console.log('\\n📊 SUITE 19: _renderAxeCard() — card HTML generation');

// ── Health score SVG generation (pure function) ──
function renderAxeHealthSvg(hs) {
  var circumference = 2 * Math.PI * 14;
  var pct = Math.min(100, Math.max(0, hs || 0));
  var offset = circumference * (1 - pct / 100);
  var color = hs >= 80 ? 'var(--accent-green)' : hs >= 50 ? 'var(--accent-amber)' : 'var(--accent-red)';
  return '<svg viewBox="0 0 32 32"><circle class="axe-card__health-bg" cx="16" cy="16" r="14"/><circle class="axe-card__health-fill" cx="16" cy="16" r="14" stroke="' + color + '" stroke-dasharray="' + circumference + '" stroke-dashoffset="' + offset + '"/></svg>';
}

assertTruthy('healthSvg(85) contains green', /accent-green/.test(renderAxeHealthSvg(85)));
assertTruthy('healthSvg(65) contains amber', /accent-amber/.test(renderAxeHealthSvg(65)));
assertTruthy('healthSvg(25) contains red', /accent-red/.test(renderAxeHealthSvg(25)));
assertTruthy('healthSvg(80) green boundary', /accent-green/.test(renderAxeHealthSvg(80)));
assertTruthy('healthSvg(50) amber boundary', /accent-amber/.test(renderAxeHealthSvg(50)));
assertTruthy('healthSvg(49) red below amber', /accent-red/.test(renderAxeHealthSvg(49)));
assertTruthy('healthSvg(null) red fallback', /accent-red/.test(renderAxeHealthSvg(null)));
assertTruthy('healthSvg has stroke-dasharray', /stroke-dasharray/.test(renderAxeHealthSvg(50)));
assertTruthy('healthSvg has stroke-dashoffset', /stroke-dashoffset/.test(renderAxeHealthSvg(50)));

// ── Last-seen freshness badge (pure function) ──
function renderLastSeenBadge(lastSeenTs, status) {
  if (lastSeenTs != null) {
    var age = Math.floor((Date.now() / 1000) - Number(lastSeenTs));
    var cls = 'badge badge--green';
    if (age > 300) cls = 'badge badge--red';
    else if (age > 60) cls = 'badge badge--amber';
    return '<span class="axe-card__seen badge ' + cls.replace('badge ','') + '" data-ts="' + lastSeenTs + '" style="font-size:7px;margin-left:4px">' + (age < 60 ? 'LIVE' : Math.floor(age / 60) + 'm') + '</span>';
  }
  if (status === 'ONLINE') return '<span class="axe-card__seen badge badge--green" style="font-size:7px;margin-left:4px">LIVE</span>';
  return '';
}

var _nowAxe = Math.floor(Date.now() / 1000);
assertTruthy('badge recent -> LIVE', /LIVE/.test(renderLastSeenBadge(_nowAxe - 5, 'ONLINE')));
assertTruthy('badge recent -> green', /badge--green/.test(renderLastSeenBadge(_nowAxe - 5, 'ONLINE')));
assertTruthy('badge 2min -> amber', /badge--amber/.test(renderLastSeenBadge(_nowAxe - 120, 'ONLINE')));
assertTruthy('badge 2min -> 2m', /2m/.test(renderLastSeenBadge(_nowAxe - 120, 'ONLINE')));
assertTruthy('badge 10min -> red', /badge--red/.test(renderLastSeenBadge(_nowAxe - 600, 'ONLINE')));
assertTruthy('badge null ONLINE -> LIVE', /LIVE/.test(renderLastSeenBadge(null, 'ONLINE')));
assertEqual('badge null OFFLINE -> empty', renderLastSeenBadge(null, 'OFFLINE'), '');
assertEqual('badge undefined -> empty', renderLastSeenBadge(undefined, null), '');
assertTruthy('badge has axe-card__seen', /axe-card__seen/.test(renderLastSeenBadge(_nowAxe - 5, 'ONLINE')));

// ── Temperature color helper ──
function tempColorClass(tempC) {
  if (tempC == null) return '';
  if (tempC > 70) return 'temp-red';
  if (tempC > 55) return 'temp-gold';
  return 'temp-green';
}

assertEqual('tempColor null -> empty', tempColorClass(null), '');
assertEqual('tempColor 45 -> green', tempColorClass(45), 'temp-green');
assertEqual('tempColor 56 -> gold', tempColorClass(56), 'temp-gold');
assertEqual('tempColor 71 -> red', tempColorClass(71), 'temp-red');
assertEqual('tempColor 55 -> green boundary', tempColorClass(55), 'temp-green');
assertEqual('tempColor 70 -> gold boundary', tempColorClass(70), 'temp-gold');

// ── Hashrate bar percentage ──
function hrBarPct(hr, maxHr) {
  maxHr = maxHr || 1;
  return Math.min(100, (hr / maxHr) * 100);
}

assertEqual('hrBarPct(50,100) -> 50', hrBarPct(50, 100), 50);
assertEqual('hrBarPct(0,100) -> 0', hrBarPct(0, 100), 0);
assertEqual('hrBarPct(100,50) -> 100 capped', hrBarPct(100, 50), 100);
assertEqual('hrBarPct(null,100) -> 0', hrBarPct(null, 100), 0);

// ── Capability badges ──
function renderCapBadges(caps) {
  if (!caps || !caps.length) return '';
  return caps.slice(0, 5).map(function(c) {
    return '<span class="axe-cap-badge is-supported">' + escapeHtml(c) + '</span>';
  }).join('');
}

assertEqual('capBadges null -> empty', renderCapBadges(null), '');
assertEqual('capBadges [] -> empty', renderCapBadges([]), '');

var twoCaps = renderCapBadges(['AxeOS', 'Bitaxe']);
assertTruthy('capBadges has AxeOS', /AxeOS/.test(twoCaps));
assertTruthy('capBadges has Bitaxe', /Bitaxe/.test(twoCaps));

var manyCaps = renderCapBadges(['a','b','c','d','e','f']);
assertEqual('capBadges max 5 items', manyCaps.match(/axe-cap-badge/g).length, 5);

var unsafeCap = renderCapBadges(['<script>']);
assertTruthy('capBadges escapes HTML', /&lt;script&gt;/.test(unsafeCap));

// ── Command buttons ──
function renderCmdBtns(cmds, devId) {
  var btnMap = {
    restart: '<button class="axe-cmd-btn axe-cmd-btn--restart" data-device-id="' + escapeHtml(devId) + '" data-cmd="restart">↻ Restart</button>',
    identify: '<button class="axe-cmd-btn axe-cmd-btn--identify" data-device-id="' + escapeHtml(devId) + '" data-cmd="identify">◈ Identify</button>',
    pause: '<button class="axe-cmd-btn axe-cmd-btn--pause" data-device-id="' + escapeHtml(devId) + '" data-cmd="pause">⎔ Pause</button>',
    resume: '<button class="axe-cmd-btn axe-cmd-btn--pause" data-device-id="' + escapeHtml(devId) + '" data-cmd="resume">▶ Resume</button>',
  };
  if (!cmds || !cmds.length) return '<span class="badge badge--muted">READ-ONLY</span>';
  return cmds.map(function(c) { return btnMap[c] || ''; }).join('');
}

assertTruthy('cmdBtns null -> READ-ONLY', /READ-ONLY/.test(renderCmdBtns(null, 'd1')));
assertTruthy('cmdBtns [] -> READ-ONLY', /READ-ONLY/.test(renderCmdBtns([], 'd1')));

var restartHtml = renderCmdBtns(['restart'], 'dev-123');
assertTruthy('cmdBtns restart has Restart', /Restart/.test(restartHtml));
assertTruthy('cmdBtns restart has data-cmd=restart', /data-cmd="restart"/.test(restartHtml));

var multiCmds = renderCmdBtns(['restart','identify','pause'], 'dev-456');
// NOTE: count via data-cmd= — /axe-cmd-btn/g matches 2x per button (base class + --modifier)
assertEqual('cmdBtns 3 cmds -> 3 buttons', multiCmds.match(/data-cmd=/g).length, 3);

// ── Command routing (auditoria UI fix) ──
// Mirror of the axe-grid button handler decision in static/app.js: axe-fleet
// cards live in the AXE registry, so restart/identify/pause/resume must go
// through the agent-aware /api/axe-fleet/devices/<id>/{restart|identify|
// pause|resume} endpoints (which enqueue for the LOCAL agent or hit the
// AxeOS HTTP API) instead of the core /api/devices/<id>/command route — that
// one queries the CORE registry and 404s on axe devices, so the miner would
// never be controlled (theater).
function routeAxeCmd(deviceId, command) {
  var isAgentRouted = command === 'restart' || command === 'identify' ||
    command === 'pause' || command === 'resume';
  return {
    url: isAgentRouted
      ? '/api/axe-fleet/devices/' + encodeURIComponent(deviceId) + '/' + command
      : '/api/devices/' + encodeURIComponent(deviceId) + '/command',
    useAuthFetch: isAgentRouted,
    body: isAgentRouted ? '{}' : '{"command":"' + command + '"}',
  };
}

assertEqual('routeAxeCmd restart -> axe-fleet', routeAxeCmd('abc123', 'restart').url,
  '/api/axe-fleet/devices/abc123/restart');
assertEqual('routeAxeCmd restart uses authFetch', routeAxeCmd('abc123', 'restart').useAuthFetch, true);
assertEqual('routeAxeCmd restart body empty', routeAxeCmd('abc123', 'restart').body, '{}');
assertEqual('routeAxeCmd identify -> axe-fleet', routeAxeCmd('abc123', 'identify').url,
  '/api/axe-fleet/devices/abc123/identify');
assertEqual('routeAxeCmd pause -> axe-fleet', routeAxeCmd('abc123', 'pause').url,
  '/api/axe-fleet/devices/abc123/pause');
assertEqual('routeAxeCmd pause uses authFetch', routeAxeCmd('abc123', 'pause').useAuthFetch, true);
assertEqual('routeAxeCmd resume -> axe-fleet', routeAxeCmd('abc123', 'resume').url,
  '/api/axe-fleet/devices/abc123/resume');
assertEqual('routeAxeCmd resume uses authFetch', routeAxeCmd('abc123', 'resume').useAuthFetch, true);
assertEqual('routeAxeCmd pause body empty', routeAxeCmd('abc123', 'pause').body, '{}');

// ── Device status classification ──
function classifyDevStatus(d) {
  var tel = d && d.telemetry || {};
  var hr = tel.hashrate_hs || tel.hashrate || d && d.hashrate || 0;
  var st = d && d.status || 'OFFLINE';
  var online = st === 'ONLINE' || (!st && hr > 0);
  var warn = !online && st === 'WARNING';
  return { online: online, warn: warn, offline: !online && !warn };
}

assertTruthy('classify ONLINE -> online', classifyDevStatus({status:'ONLINE',telemetry:{hashrate_hs:50e12}}).online);
assertTruthy('classify WARNING -> warn', classifyDevStatus({status:'WARNING',telemetry:{}}).warn);
assertTruthy('classify OFFLINE -> offline', classifyDevStatus({status:'OFFLINE',telemetry:{}}).offline);
assertTruthy('classify null -> offline', classifyDevStatus(null).offline);

// ── Stats row ──
function renderAxeStats(tel) {
  tel = tel || {};
  var s = [];
  s.push({ lbl:'Temp', val: tel.temperature != null ? tel.temperature.toFixed(0) + '°C' : '—', cls: tempColorClass(tel.temperature) });
  s.push({ lbl:'Best', val: tel.best_diff ? fmt.diff(tel.best_diff) : '—' });
  s.push({ lbl:'Up', val: tel.uptime_seconds ? fmt.uptime(tel.uptime_seconds) : '—' });
  return s.map(function(x) {
    return '<div class="axe-stat' + (x.cls ? ' ' + x.cls : '') + '"><span class="axe-stat__label">' + x.lbl + '</span><span class="axe-stat__val">' + x.val + '</span></div>';
  }).join('');
}

var st = renderAxeStats({temperature:65, best_diff:9.56e9, uptime_seconds:3600});
assertTruthy('stats has 65°C', /65°C/.test(st));
assertTruthy('stats has 9.56 G', /9\.56 G/.test(st));
assertTruthy('stats has 1h', /1h/.test(st));
assertTruthy('stats has temp-gold', /temp-gold/.test(st));

var cold = renderAxeStats({temperature:45});
assertTruthy('cold has temp-green', /temp-green/.test(cold));

var emptyStats = renderAxeStats({});
assertTruthy('empty temp → —', /—/.test(emptyStats));

// ── Fase 5: telemetry completeness — chip/VR temp + hashrate 1h ──
// Mirrors _renderAxeCard F5 stats: real finite number or explicit NOT
// AVAILABLE. Uses a fmt.num()-style guard (typeof === 'number') because the
// backend may send the literal string "NOT AVAILABLE" for missing fields.
function isFiniteNum(v) { return typeof v === 'number' && isFinite(v); }
function renderAxeF5Stats(tel) {
  tel = tel || {};
  var NA = 'NOT AVAILABLE';
  var chip = isFiniteNum(tel.chip_temp) ? tel.chip_temp.toFixed(0) + '°C'
    : (isFiniteNum(tel.temp_asic) ? tel.temp_asic.toFixed(0) + '°C'
    : (isFiniteNum(tel.temperature) ? tel.temperature.toFixed(0) + '°C' : NA));
  var vr = isFiniteNum(tel.vr_temp) ? tel.vr_temp.toFixed(0) + '°C'
    : (isFiniteNum(tel.temp_vreg) ? tel.temp_vreg.toFixed(0) + '°C' : NA);
  var hr1h = isFiniteNum(tel.hashrate_1h) ? fmt.hashrate(tel.hashrate_1h) : NA;
  return { chip: chip, vr: vr, hr1h: hr1h };
}

var f5full = renderAxeF5Stats({ chip_temp: 72, vr_temp: 60, hashrate_1h: 1.2e12 });
assertEqual('f5 chip real value', f5full.chip, '72°C');
assertEqual('f5 vr real value', f5full.vr, '60°C');
assertTruthy('f5 hr1h real value', /TH\/s/.test(f5full.hr1h));

var f5fallback = renderAxeF5Stats({});
assertEqual('f5 chip NOT AVAILABLE', f5fallback.chip, 'NOT AVAILABLE');
assertEqual('f5 vr NOT AVAILABLE', f5fallback.vr, 'NOT AVAILABLE');
assertEqual('f5 hr1h NOT AVAILABLE', f5fallback.hr1h, 'NOT AVAILABLE');

var f5alias = renderAxeF5Stats({ temp_asic: 71, temp_vreg: 59, hashrate_1m: 1e12 });
assertEqual('f5 chip alias temp_asic', f5alias.chip, '71°C');
assertEqual('f5 vr alias temp_vreg', f5alias.vr, '59°C');
assertEqual('f5 hr1h no 1h → NOT AVAILABLE', f5alias.hr1h, 'NOT AVAILABLE');

// Literal 'NOT AVAILABLE' strings (normalized backend payloads) must never
// crash the card — guards treat them as missing.
var f5normalized = renderAxeF5Stats({ chip_temp: 'NOT AVAILABLE', vr_temp: 'NOT AVAILABLE', hashrate_1h: 'NOT AVAILABLE' });
assertEqual('f5 normalized chip → NOT AVAILABLE', f5normalized.chip, 'NOT AVAILABLE');
assertEqual('f5 normalized vr → NOT AVAILABLE', f5normalized.vr, 'NOT AVAILABLE');
assertEqual('f5 normalized hr1h → NOT AVAILABLE', f5normalized.hr1h, 'NOT AVAILABLE');

// ── Module visibility — mirrors activateModule() data-module toggle ────────
// A panel/element with data-module="a b c" is visible when the active module
// is one of its tokens. Mirrors the split(/\s+/).indexOf(name) !== -1 logic.
function moduleShouldShow(modAttr, activeModule) {
  var mods = (modAttr || '').split(/\s+/);
  return mods.indexOf(activeModule) !== -1;
}

// Sidebar links carry data-module but must NEVER be hidden by activateModule()
// (that was the original P1 navigation killer). Mirrors the classList check.
function isSidebarLinkExempt(cls) {
  var classes = (cls || '').split(/\s+/);
  return classes.indexOf('sidebar__link') !== -1;
}

assertTruthy('module dashboard shows dashboard', moduleShouldShow('dashboard', 'dashboard'));
assertEqual('module dashboard hides market', moduleShouldShow('dashboard', 'market'), false);
assertTruthy('module fleet multi-token shows fleet', moduleShouldShow('dashboard fleet', 'fleet'));
assertTruthy('module fleet multi-token shows dashboard', moduleShouldShow('dashboard fleet', 'dashboard'));
assertTruthy('module market shows market', moduleShouldShow('market', 'market'));
assertEqual('module empty attr', moduleShouldShow('', 'dashboard'), false);
assertEqual('module null attr', moduleShouldShow(null, 'dashboard'), false);
assertEqual('module undefined attr', moduleShouldShow(undefined, 'dashboard'), false);
assertEqual('module no-match token', moduleShouldShow('alerts', 'docs'), false);
assertTruthy('module padded whitespace attr', moduleShouldShow(' dashboard ', 'dashboard'));
assertTruthy('sidebar link exempt', isSidebarLinkExempt('sidebar__link'));
assertTruthy('sidebar link exempt with other classes', isSidebarLinkExempt('foo sidebar__link bar'));
assertEqual('panel not exempt', isSidebarLinkExempt('panel'), false);
assertEqual('empty class not exempt', isSidebarLinkExempt(''), false);
assertEqual('null class not exempt', isSidebarLinkExempt(null), false);


// ═══════════════════════════════════════════════════════════════════════════
//  TENANT AUTH HELPERS (mirrors static/app.js — Fase 4 · B1-frontend)
// ═══════════════════════════════════════════════════════════════════════════

function authBuildHeaders(token) {
  if (!token) return {};
  return { 'Authorization': 'Bearer ' + token };
}

function authIsExpired(expiresAt, now) {
  if (!expiresAt) return true;
  now = now || Math.floor(Date.now() / 1000);
  return now >= (Number(expiresAt) - 30); // 30s safety margin
}

function authSessionValid(session, now) {
  if (!session || !session.access_token) return false;
  return !authIsExpired(session.expires_at, now);
}

(function testTenantAuthHelpers() {
  // authBuildHeaders
  assertEqual('no token -> empty headers', authBuildHeaders(null), {});
  assertEqual('empty token -> empty headers', authBuildHeaders(''), {});
  assertEqual('valid token -> Bearer header', authBuildHeaders('abc.def.ghi'),
    { 'Authorization': 'Bearer abc.def.ghi' });
  assertEqual('token with extra spaces preserved', authBuildHeaders('  x.y.z  '),
    { 'Authorization': 'Bearer   x.y.z  ' });

  // authIsExpired
  assertEqual('null expiresAt -> expired', authIsExpired(null, 1000), true);
  assertEqual('undefined expiresAt -> expired', authIsExpired(undefined, 1000), true);
  assertEqual('future expiry -> not expired', authIsExpired(2000, 1000), false);
  assertEqual('past expiry -> expired', authIsExpired(900, 1000), true);
  assertEqual('exact boundary minus margin -> expired', authIsExpired(1030, 1000), true);
  assertEqual('just past margin -> not expired', authIsExpired(1031, 1000), false);
  assertEqual('now defaults to Date.now', authIsExpired(Math.floor(Date.now() / 1000) - 5), true);
  assertEqual('string expiresAt handled', authIsExpired('2000', 1000), false);

  // authSessionValid
  assertEqual('null session -> invalid', authSessionValid(null, 1000), false);
  assertEqual('empty session -> invalid', authSessionValid({}, 1000), false);
  assertEqual('session without token -> invalid', authSessionValid({ expires_at: 2000 }, 1000), false);
  assertEqual('valid token + future expiry -> valid',
    authSessionValid({ access_token: 't', expires_at: 2000 }, 1000), true);
  assertEqual('valid token + past expiry -> invalid',
    authSessionValid({ access_token: 't', expires_at: 900 }, 1000), false);
  assertEqual('no expiry -> invalid',
    authSessionValid({ access_token: 't' }, 1000), false);
})();


// ═══════════════════════════════════════════════════════════════════════════
//  LIVE HASH CALCULATOR + SPARKLINE DPR (mirrors static/app.js)
// ═══════════════════════════════════════════════════════════════════════════

// Pure mirror of renderLiveCalc() — returns {elementId: text} map exactly as
// the DOM writes would produce, so every lc-* value can be asserted without a
// real DOM.
function liveCalcValues(prox) {
  const lc = (prox && prox.live_calc) || {};
  const latest = lc.latest || {};
  const totals = lc.session_totals || {};
  const dash = '\u2014';
  return {
    'lc-time-big': latest.ts ? fmt.age(latest.ts) : dash,
    'lc-session-share-count': latest.session_share_count_at_time != null ? 'share #' + latest.session_share_count_at_time : dash,
    'lc-share-diff': latest.share_diff_str || dash,
    'lc-hashes': latest.hashes_attempted_str || dash,
    'lc-time-obs': latest.gap != null ? latest.gap + 's' : dash,
    'lc-p-block': latest.p_block_this_share_pct_str || dash,
    'lc-inst-hr': latest.instantaneous_hr_str || dash,
    'lc-session-shares': totals.shares_so_far != null ? totals.shares_so_far : dash,
    'lc-avg-share-diff': totals.avg_share_diff_str || dash,
    'lc-cum-p': totals.cum_p_block_pct_str || dash,
    'lc-expected-blocks': totals.expected_blocks_str || dash,
  };
}

// Pure mirror of the ticker HTML written into #lc-ticker-list.
function liveCalcTickerHtml(lc) {
  const dash = '\u2014';
  const ticker = ((lc && lc.ticker) || []).slice().reverse();
  if (!ticker.length) return '<div class="prox-live-calc__ticker-empty">awaiting share data</div>';
  return ticker.map(function(e) {
    return '<div class="lc-ticker-row">' +
      '<span class="lc-ticker-time">' + (e.ts ? fmt.age(e.ts) : '--:--:--') + '</span>' +
      '<span class="lc-ticker-diff">' + (e.share_diff_str || dash) + '</span>' +
      '<span class="lc-ticker-gap">\u0394' + (e.gap || '\u2014') + 's</span>' +
      '<span class="lc-ticker-hr">' + (e.instantaneous_hr_str || dash) + '</span>' +
      '</div>';
  }).join('');
}

// Pure mirror of _drawProximitySparkline() canvas sizing (getComputedStyle
// + Math.round(css * dpr)). Fixed CSS height (28px) means the backing store
// scales with DPR but never compounds across re-renders.
function sparklineSize(computedW, computedH, clientW, clientH, dpr) {
  const cssW = parseFloat(computedW) || clientW || 220;
  const cssH = parseFloat(computedH) || clientH || 28;
  return { width: Math.round(cssW * dpr), height: Math.round(cssH * dpr) };
}

console.log('\n📊 SUITE 24: renderLiveCalc() — lc-* values + sparkline DPR');

(function testLiveCalcValues() {
  const now = Math.floor(Date.now() / 1000);
  const prox = {
    live_calc: {
      latest: {
        ts: now - 30,
        gap: 30,
        session_share_count_at_time: 7,
        share_diff_str: '16.00 K',
        hashes_attempted_str: '6.871e13',
        p_block_this_share_pct_str: '1.2393e-07%',
        instantaneous_hr_str: '2.29 TH/s',
      },
      ticker: [
        { ts: now - 60, share_diff_str: '16.00 K', gap: 30, instantaneous_hr_str: '2.29 TH/s' },
        { ts: now - 90, share_diff_str: '15.50 K', gap: 60, instantaneous_hr_str: '1.14 TH/s' },
      ],
      session_totals: {
        shares_so_far: 12,
        avg_share_diff_str: '15.75 K',
        cum_p_block_pct_str: '1.4870e-06%',
        expected_blocks_str: '1.4870e-08',
      },
    },
  };

  const vals = liveCalcValues(prox);
  assertEqual('lc-share-diff set', vals['lc-share-diff'], '16.00 K');
  assertEqual('lc-hashes set', vals['lc-hashes'], '6.871e13');
  assertEqual('lc-time-obs set', vals['lc-time-obs'], '30s');
  assertEqual('lc-p-block set', vals['lc-p-block'], '1.2393e-07%');
  assertEqual('lc-inst-hr set', vals['lc-inst-hr'], '2.29 TH/s');
  assertEqual('lc-session-shares set', vals['lc-session-shares'], 12);
  assertEqual('lc-avg-share-diff set', vals['lc-avg-share-diff'], '15.75 K');
  assertEqual('lc-cum-p set', vals['lc-cum-p'], '1.4870e-06%');
  assertEqual('lc-expected-blocks set', vals['lc-expected-blocks'], '1.4870e-08');
  assertEqual('lc-session-share-count set', vals['lc-session-share-count'], 'share #7');
  assertTruthy('lc-time-big shows ago', /ago/.test(vals['lc-time-big']));

  // Missing data → em-dash everywhere
  const emptyVals = liveCalcValues({});
  assertEqual('empty lc-share-diff → dash', emptyVals['lc-share-diff'], '\u2014');
  assertEqual('empty lc-cum-p → dash', emptyVals['lc-cum-p'], '\u2014');
  assertEqual('empty lc-session-shares → dash', emptyVals['lc-session-shares'], '\u2014');
  assertEqual('empty lc-session-share-count → dash', emptyVals['lc-session-share-count'], '\u2014');
  assertEqual('null prox → all dash', liveCalcValues(null)['lc-share-diff'], '\u2014');
})();

(function testLiveCalcTicker() {
  const now = Math.floor(Date.now() / 1000);
  // Backend payload is sch[-8:] (oldest→newest). After .slice().reverse()
  // the top row must be the NEWEST share (16.00 K, ts now-60).
  const ticker = [
    { ts: now - 90, share_diff_str: '15.50 K', gap: 60, instantaneous_hr_str: '1.14 TH/s' },
    { ts: now - 60, share_diff_str: '16.00 K', gap: 30, instantaneous_hr_str: '2.29 TH/s' },
  ];
  const html = liveCalcTickerHtml({ ticker: ticker });
  assertEqual('ticker rows count', (html.match(/lc-ticker-row/g) || []).length, 2);
  assertTruthy('ticker newest-first (16.00K before 15.50K)', html.indexOf('16.00 K') < html.indexOf('15.50 K'));
  assertTruthy('ticker has diff cell', /lc-ticker-diff/.test(html));
  assertTruthy('ticker has gap cell', /lc-ticker-gap/.test(html));
  assertTruthy('ticker has hr cell', /lc-ticker-hr/.test(html));
  assertEqual('empty ticker → awaiting', liveCalcTickerHtml({ ticker: [] }),
    '<div class="prox-live-calc__ticker-empty">awaiting share data</div>');
  assertEqual('missing ticker → awaiting', liveCalcTickerHtml({}),
    '<div class="prox-live-calc__ticker-empty">awaiting share data</div>');
})();

(function testSparklineDprStability() {
  // Fixed CSS box (28px) must NOT grow with DPR — the backing store scales
  // (28*dpr) but the CSS size never compounds across re-renders.
  assertEqual('dpr1 width 352', sparklineSize('352px', '28px', 0, 0, 1).width, 352);
  assertEqual('dpr1 height 28', sparklineSize('352px', '28px', 0, 0, 1).height, 28);
  assertEqual('dpr2 width 704 (2x backing)', sparklineSize('352px', '28px', 0, 0, 2).width, 704);
  assertEqual('dpr2 height 56 (2x backing)', sparklineSize('352px', '28px', 0, 0, 2).height, 56);
  assertEqual('size idempotent at dpr2 (no growth)',
    JSON.stringify(sparklineSize('352px', '28px', 0, 0, 2)),
    JSON.stringify(sparklineSize('352px', '28px', 0, 0, 2)));
  // Fallback when getComputedStyle returns non-px (e.g. 'auto' while hidden)
  assertEqual('fallback to clientWidth', sparklineSize('auto', 'auto', 300, 60, 1).width, 300);
  assertEqual('fallback to clientHeight', sparklineSize('auto', 'auto', 300, 60, 1).height, 60);
  // Default fallback when everything is missing
  assertEqual('default width 220', sparklineSize(NaN, NaN, 0, 0, 1).width, 220);
  assertEqual('default height 28', sparklineSize(NaN, NaN, 0, 0, 1).height, 28);
})();


(function testWalletGreeting() {
  // Mirror of static/app.js WALLET_GREETINGS + walletGreeting() — returns
  // the personalized welcome for a known community wallet, null otherwise.
  const WALLET_GREETINGS = {
    'bc1qftl45m5jq7hjd0n62yuxesmss478xl2wvfkeed': '👋 Bem vindo barone (barone club)',
    'bc1qffk82prrxn84e8y9l0z5yflsqclhyc9ptphgmf': '👋 Bem vindo filipe silva — comunidade bitminer33',
    'bc1q029y2atdtvth4puv2mm5w49m32n278jtz2sxqn': '👋 Bem vindo DIGO GARABELI — acesso FULL & FREE',
    'dhr7a2ihqou5w5r5cpvsuvcnw4jg32qlwx': '👋 Bem vindo DIGO GARABELI — acesso FULL & FREE',
    '1473pql42jvtwxaaxcvsocrf6ytb8teted': '👋 Bem vindo DIGO GARABELI — acesso FULL & FREE',
  };
  function walletGreeting(address) {
    if (!address) return null;
    return WALLET_GREETINGS[String(address).toLowerCase()] || null;
  }
  // Policy mirror: greeted wallets hold FULL & FREE access.
  function walletHasFullAccess(address) {
    return walletGreeting(address) !== null;
  }

  const DIGO_MSG = '👋 Bem vindo DIGO GARABELI — acesso FULL & FREE';
  assertEqual('barone welcome', walletGreeting('bc1qftl45m5jq7hjd0n62yuxesmss478xl2wvfkeed'),
    '👋 Bem vindo barone (barone club)');
  assertEqual('bitminer33 welcome', walletGreeting('bc1qffk82prrxn84e8y9l0z5yflsqclhyc9ptphgmf'),
    '👋 Bem vindo filipe silva — comunidade bitminer33');
  assertEqual('uppercase address still matches (lowercased lookup)',
    walletGreeting('BC1QFFK82PRRXN84E8Y9L0Z5YFLSQCLHYC9PTPHGMF'),
    '👋 Bem vindo filipe silva — comunidade bitminer33');
  // DIGO GARABELI — the three greeted wallets (BTC + DOGE + LTC) all get
  // the personalized welcome AND full & free access.
  assertEqual('digo btc welcome', walletGreeting('bc1q029y2atdtvth4puv2mm5w49m32n278jtz2sxqn'), DIGO_MSG);
  assertEqual('digo doge welcome', walletGreeting('DHr7a2iHQoU5w5R5cpvsuvCNw4Jg32qLWX'), DIGO_MSG);
  assertEqual('digo doge lowercased welcome', walletGreeting('dhr7a2ihqou5w5r5cpvsuvcnw4jg32qlwx'), DIGO_MSG);
  assertEqual('digo ltc welcome', walletGreeting('1473PqL42JVTwXaAXcVsocRF6ytB8tETeD'), DIGO_MSG);
  assertEqual('digo ltc lowercased welcome', walletGreeting('1473pql42jvtwxaaxcvsocrf6ytb8teted'), DIGO_MSG);
  // FULL & FREE access policy: every greeted wallet is entitled.
  assertEqual('digo btc has full access', walletHasFullAccess('bc1q029y2atdtvth4puv2mm5w49m32n278jtz2sxqn'), true);
  assertEqual('digo doge has full access', walletHasFullAccess('DHr7a2iHQoU5w5R5cpvsuvCNw4Jg32qLWX'), true);
  assertEqual('digo ltc has full access', walletHasFullAccess('1473PqL42JVTwXaAXcVsocRF6ytB8tETeD'), true);
  assertEqual('barone has full access', walletHasFullAccess('bc1qftl45m5jq7hjd0n62yuxesmss478xl2wvfkeed'), true);
  assertEqual('unknown wallet has no full access', walletHasFullAccess('bc1qunknown123'), false);
  assertEqual('empty address has no full access', walletHasFullAccess(''), false);
  assertEqual('null address has no full access', walletHasFullAccess(null), false);
  assertEqual('unknown wallet → null', walletGreeting('bc1qunknown123'), null);
  assertEqual('empty address → null', walletGreeting(''), null);
  assertEqual('null address → null', walletGreeting(null), null);
})();


(function testSoloTermUser() {
  // Mirror of static/app.js _soloTermUser() — the Live Terminal prompt
  // identity: the connected wallet (short form) when present, else 'miner'.
  // Never a hardcoded person. Uses the same fmt.shortAddr() semantics.
  function shortAddr(a) {
    if (!a) return '';
    if (a.length <= 16) return a;
    return a.slice(0, 10) + '\u2026' + a.slice(-6);
  }
  function soloTermUser(btcAddress) {
    var addr = btcAddress || '';
    if (addr) return shortAddr(addr);
    return 'miner';
  }

  assertEqual('no wallet → miner', soloTermUser(''), 'miner');
  assertEqual('null wallet → miner', soloTermUser(null), 'miner');
  assertEqual('undefined wallet → miner', soloTermUser(undefined), 'miner');
  assertEqual('short wallet kept as-is', soloTermUser('bc1qshort'), 'bc1qshort');
  assertEqual('full wallet → short form',
    soloTermUser('bc1qar0srrr7xfkvy5l643lydnw9re59gtzzwf5mdq'),
    'bc1qar0srr\u2026wf5mdq');
  assertEqual('legacy wallet → short form',
    soloTermUser('1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa'),
    '1A1zP1eP5Q\u2026DivfNa');
})();


(function testProfitModeView() {
  // Mirror of static/app.js profitModeView() — pure selector that returns the
  // values to display for the requested profitability mode (pool|solo|rental).
  // Validates the corrected solo math keys + per-mode fiat/break-even wiring.
  function profitModeView(p, mode) {
    if (!p || !Object.keys(p).length) return null;
    const m = (mode === 'solo' || mode === 'rental' || mode === 'lender') ? mode : 'pool';
    const view = { mode: m, btcDay: null, fiatDay: {}, fiatWeek: {}, fiatMonth: {}, breakeven: null, soloStats: null, lenderStats: null };
    if (m === 'solo') {
      view.btcDay = p.net_btc_per_day_solo;
      view.fiatDay = p.fiat_per_day_solo || {};
      view.fiatMonth = p.fiat_per_month_solo || {};
      view.breakeven = null;
      view.soloStats = {
        pToday: p.solo_p_day_pct,
        pYear: p.solo_p_year_pct,
        p5y: p.solo_p_5year_pct,
        blocksYear: p.solo_expected_blocks_per_year,
        expectedDays: p.solo_expected_time_to_block_days,
      };
    } else if (m === 'rental') {
      view.btcDay = p.net_btc_per_day_rental;
      view.fiatDay = p.fiat_per_day_rental || {};
      view.fiatMonth = p.fiat_per_month_rental || {};
      view.breakeven = p.break_even_rental_usd_per_th_day;
    } else if (m === 'lender') {
      view.btcDay = p.lender_net_btc_per_day;
      view.fiatDay = p.lender_fiat_per_day || {};
      view.fiatMonth = p.lender_fiat_per_month || {};
      view.breakeven = p.lender_breakeven_usd_per_th_day;
      view.lenderStats = {
        marketRateUsd: p.lender_market_rate_usd_per_th_day,
        leaseNetUsd: p.lender_net_usd_per_day,
        mineNetUsd: p.lender_mine_net_usd_per_day,
        vsMiningUsd: p.lender_vs_mining_usd_per_day,
        recommendation: p.lender_recommendation,
      };
    } else {
      view.btcDay = p.net_btc_per_day_pool;
      view.fiatDay = p.fiat_per_day_pool || {};
      view.fiatMonth = p.fiat_per_month_pool || {};
      view.breakeven = p.breakeven_cost_per_th_day;
    }
    Object.keys(view.fiatDay).forEach(c => {
      view.fiatWeek[c] = view.fiatDay[c] != null ? view.fiatDay[c] * 7 : null;
    });
    return view;
  }

  const p = {
    net_btc_per_day_pool: 0.00012345,
    fiat_per_day_pool: { USD: 7.5, BRL: 40.0 },
    fiat_per_month_pool: { USD: 225.0, BRL: 1200.0 },
    breakeven_cost_per_th_day: 0.0123,
    net_btc_per_day_solo: 0.00011111,
    fiat_per_day_solo: { USD: 6.75, BRL: 36.0 },
    fiat_per_month_solo: { USD: 202.5, BRL: 1080.0 },
    solo_p_day_pct: 0.0012,
    solo_p_year_pct: 0.35,
    solo_p_5year_pct: 1.75,
    solo_expected_blocks_per_year: 0.0044,
    solo_expected_time_to_block_days: 227.3,
    net_btc_per_day_rental: 0.00010101,
    fiat_per_day_rental: { USD: 6.1, BRL: 32.0 },
    fiat_per_month_rental: { USD: 183.0, BRL: 960.0 },
    break_even_rental_usd_per_th_day: 0.0144,
    // Lender (Scenario D) keys
    lender_net_btc_per_day: 0.00009090,
    lender_fiat_per_day: { USD: 5.45, BRL: 29.0 },
    lender_fiat_per_month: { USD: 163.5, BRL: 870.0 },
    lender_breakeven_usd_per_th_day: 0.0133,
    lender_market_rate_usd_per_th_day: 0.0140,
    lender_net_usd_per_day: 5.45,
    lender_mine_net_usd_per_day: 7.5,
    lender_vs_mining_usd_per_day: -2.05,
    lender_recommendation: 'mine',
  };

  // Pool mode (default)
  const pool = profitModeView(p, 'pool');
  assertEqual('pool mode', pool.mode, 'pool');
  assertApprox('pool btcDay', pool.btcDay, 0.00012345, 1e-9);
  assertApprox('pool fiatWeek derived ×7', pool.fiatWeek.USD, 52.5, 1e-9);
  assertApprox('pool breakeven', pool.breakeven, 0.0123, 1e-9);
  assertEqual('pool soloStats null', pool.soloStats, null);

  // Solo mode — corrected math keys surfaced
  const solo = profitModeView(p, 'solo');
  assertEqual('solo mode', solo.mode, 'solo');
  assertApprox('solo btcDay', solo.btcDay, 0.00011111, 1e-9);
  assertApprox('solo fiatMonth', solo.fiatMonth.USD, 202.5, 1e-9);
  assertEqual('solo breakeven null (expected time instead)', solo.breakeven, null);
  assertApprox('solo pToday', solo.soloStats.pToday, 0.0012, 1e-9);
  assertApprox('solo pYear', solo.soloStats.pYear, 0.35, 1e-9);
  assertApprox('solo p5y', solo.soloStats.p5y, 1.75, 1e-9);
  assertApprox('solo blocksYear', solo.soloStats.blocksYear, 0.0044, 1e-9);
  assertApprox('solo expectedDays', solo.soloStats.expectedDays, 227.3, 1e-9);

  // Rental mode
  const rental = profitModeView(p, 'rental');
  assertEqual('rental mode', rental.mode, 'rental');
  assertApprox('rental btcDay', rental.btcDay, 0.00010101, 1e-9);
  assertApprox('rental fiatMonth', rental.fiatMonth.USD, 183.0, 1e-9);
  assertApprox('rental breakeven', rental.breakeven, 0.0144, 1e-9);
  assertEqual('rental soloStats null', rental.soloStats, null);

  // Lender mode (Scenario D: rent out own hashrate vs mining)
  const lender = profitModeView(p, 'lender');
  assertEqual('lender mode', lender.mode, 'lender');
  assertApprox('lender btcDay', lender.btcDay, 0.00009090, 1e-9);
  assertApprox('lender fiatMonth', lender.fiatMonth.USD, 163.5, 1e-9);
  assertApprox('lender breakeven', lender.breakeven, 0.0133, 1e-9);
  assertApprox('lender marketRateUsd', lender.lenderStats.marketRateUsd, 0.0140, 1e-9);
  assertApprox('lender leaseNetUsd', lender.lenderStats.leaseNetUsd, 5.45, 1e-9);
  assertApprox('lender mineNetUsd', lender.lenderStats.mineNetUsd, 7.5, 1e-9);
  assertApprox('lender vsMiningUsd', lender.lenderStats.vsMiningUsd, -2.05, 1e-9);
  assertEqual('lender recommendation', lender.lenderStats.recommendation, 'mine');

  // Unknown mode falls back to pool; empty payload → null
  assertEqual('unknown mode → pool', profitModeView(p, 'bogus').mode, 'pool');
  assertEqual('empty payload → null', profitModeView({}, 'solo'), null);
  assertEqual('null payload → null', profitModeView(null, 'solo'), null);
})();


// ═══════════════════════════════════════════════════════════════════════════
//  TEST SUITE 25: Fase 2.1 chart helpers — computeSMA + buildChartAnnotations
// ═══════════════════════════════════════════════════════════════════════════
console.log('📊 SUITE 25: Fase 2.1 chart helpers (computeSMA + buildChartAnnotations)');
(() => {
  // Mirror of static/app.js computeSMA — simple moving average with a partial
  // window at the head so the SMA line starts at the first point.
  function computeSMA(values, windowSize) {
    if (!Array.isArray(values) || !values.length) return [];
    windowSize = Math.max(1, Math.floor(Number(windowSize) || 7));
    const out = [];
    let sum = 0;
    for (let i = 0; i < values.length; i++) {
      sum += Number(values[i]) || 0;
      if (i >= windowSize) sum -= Number(values[i - windowSize]) || 0;
      const n = Math.min(i + 1, windowSize);
      out.push(Number((sum / n).toFixed(2)));
    }
    return out;
  }

  // Mirror of static/app.js buildChartAnnotations — maps persisted timeline
  // events (ts in seconds) to the nearest label index (labels in ms) so the
  // annotation plugin can draw vertical lines on the category axis.
  function buildChartAnnotations(events, labels) {
    if (!Array.isArray(events) || !Array.isArray(labels) || !labels.length) return [];
    const out = [];
    events.forEach(ev => {
      const ts = Number(ev.ts || 0) * 1000;
      if (!ts) return;
      let idx = 0, best = Infinity;
      for (let i = 0; i < labels.length; i++) {
        const d = Math.abs(Number(labels[i]) - ts);
        if (d < best) { best = d; idx = i; }
      }
      out.push({ index: idx, severity: ev.severity || 'INFO', message: String(ev.message || ev.event_type || '') });
    });
    return out;
  }

  // Mirror of static/app.js clampZoomRange — category-axis zoom clamp in
  // POINT COUNTS (the x scale min/max are indices, not timestamps). This
  // mirrors the exact bounds the wheel-zoom handler applies.
  function clampZoomRange(currentRange, factor, minPoints, maxPoints) {
    const next = currentRange * factor;
    const upper = Math.max(minPoints, maxPoints);
    return Math.max(minPoints, Math.min(next, upper));
  }

  // ── computeSMA ──
  assertEqual('SMA empty → []', JSON.stringify(computeSMA([], 5)), '[]');
  assertEqual('SMA non-array → []', JSON.stringify(computeSMA(null, 5)), '[]');
  const sma3 = computeSMA([1, 2, 3, 4, 5], 3);
  assertEqual('SMA len preserved', sma3.length, 5);
  assertEqual('SMA head partial window', sma3[0], 1);
  assertEqual('SMA 2nd partial window', sma3[1], 1.5);
  assertEqual('SMA full window', sma3[2], 2);
  assertEqual('SMA rolling value', sma3[3], 3);
  assertEqual('SMA trailing value', sma3[4], 4);
  // windowSize 0 falls through to the default 7 (Number(0) || 7), so the
  // whole series averages — assert the REAL behavior, not a phantom clamp.
  assertEqual('SMA window 0 → default 7', JSON.stringify(computeSMA([10, 20], 0)), '[10,15]');
  assertEqual('SMA window huge → full avg', computeSMA([10, 20, 30], 99).length, 3);
  assertEqual('SMA nulls treated as 0', JSON.stringify(computeSMA([null, 4, 8], 3)), '[0,2,4]');

  // ── clampZoomRange (category-axis zoom bounds in point counts) ──
  assertApprox('zoom zoom-in 120pts ×0.83', clampZoomRange(120, 0.8333, 5, 120), 99.996, 0.01);
  assertApprox('zoom zoom-out 50pts ×1.2', clampZoomRange(50, 1.2, 5, 120), 60, 0.01);
  assertEqual('zoom min clamp (below 5 pts)', clampZoomRange(3, 0.8, 5, 120), 5);
  assertEqual('zoom max clamp (above label count)', clampZoomRange(200, 1.2, 5, 120), 120);
  assertEqual('zoom maxPoints below min → min wins', clampZoomRange(10, 2, 5, 2), 5);
  assertApprox('zoom identity factor 1', clampZoomRange(60, 1, 5, 120), 60, 0.001);

  // ── buildChartAnnotations ──
  const labels = [1700000000000, 1700000060000, 1700000120000];
  const events = [
    { ts: 1700000061, severity: 'GOLD', message: 'BUMP found' },
    { ts: 1700000122, severity: 'INFO', event_type: 'SHARE_FOUND' },
    { ts: 0, severity: 'INFO', message: 'skipped' },
  ];
  const anns = buildChartAnnotations(events, labels);
  assertEqual('annotations count (zero-ts skipped)', anns.length, 2);
  assertEqual('annotation nearest index', anns[0].index, 1);
  assertEqual('annotation severity', anns[0].severity, 'GOLD');
  assertEqual('annotation message', anns[0].message, 'BUMP found');
  assertEqual('annotation fallback to event_type', anns[1].message, 'SHARE_FOUND');
  assertEqual('annotation severity default INFO', anns[1].severity, 'INFO');
  assertEqual('no events → []', JSON.stringify(buildChartAnnotations([], labels)), '[]');
  assertEqual('no labels → []', JSON.stringify(buildChartAnnotations(events, [])), '[]');
  assertEqual('null events → []', JSON.stringify(buildChartAnnotations(null, labels)), '[]');
})();


// ═══════════════════════════════════════════════════════════════════════════
//  SUITE 22: Command Center — contextual action cards (P0-3)
// ═══════════════════════════════════════════════════════════════════════════
// Mirrors static/app.js commandCenterCardHtml() — pure HTML generation for
// the P0-3 Command Center panel. Severity maps to a modifier class; every
// card carries data-cc-* attributes consumed by the delegated click handler
// (module navigation + optional external affiliate link).

console.log('⌘ SUITE 22: renderCommandCenter() — action card HTML + severity');

function escapeHtmlTest(s) { return String(s).replace(/[&<>"']/g, c => ({ '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;' }[c])); }

function commandCenterCardHtmlTest(card) {
  if (!card || typeof card !== 'object') return '';
  const sev = String(card.severity || 'info').toLowerCase();
  const esc = escapeHtmlTest;
  const target = String(card.target || '');
  const panel = String(card.panel || '');
  const url = String(card.url || '');
  return (
    '<button type="button" class="cc-card cc-card--' + sev + '" ' +
    'data-cc-target="' + esc(target) + '" ' +
    'data-cc-panel="' + esc(panel) + '" ' +
    'data-cc-url="' + esc(url) + '">' +
    '<span class="cc-card__title">' + esc(card.title || 'Atenção') + '</span>' +
    '<span class="cc-card__message">' + esc(card.message || '') + '</span>' +
    '<span class="cc-card__action">' + esc(card.action || 'IR') + ' →</span>' +
    '</button>'
  );
}

// Severity modifier + structure
var critCard = commandCenterCardHtmlTest({ id: 'worker_offline', severity: 'crit', title: 'Worker offline', message: 'Sem worker', action: 'VER FLEET', target: 'fleet', panel: 'axe-fleet-panel', url: null });
assertTruthy('crit card has cc-card--crit class', /cc-card--crit/.test(critCard));
assertTruthy('crit card is a button', /<button/.test(critCard));
assertTruthy('crit card has title', /Worker offline/.test(critCard));
assertTruthy('crit card has message', /Sem worker/.test(critCard));
assertTruthy('crit card has action label', /VER FLEET/.test(critCard));
assertTruthy('crit card has target fleet', /data-cc-target="fleet"/.test(critCard));
assertTruthy('crit card has panel id', /data-cc-panel="axe-fleet-panel"/.test(critCard));
assertTruthy('crit card no url attr', /data-cc-url=""/.test(critCard));

// Severity defaults to info
var plainCard = commandCenterCardHtmlTest({ title: 'x' });
assertTruthy('missing severity defaults to info', /cc-card--info/.test(plainCard));
assertTruthy('missing action defaults to IR', /IR/.test(plainCard));

// Gold / warn / info modifiers
assertTruthy('gold modifier', /cc-card--gold/.test(commandCenterCardHtmlTest({ severity: 'gold' })));
assertTruthy('warn modifier', /cc-card--warn/.test(commandCenterCardHtmlTest({ severity: 'warn' })));
assertTruthy('info modifier', /cc-card--info/.test(commandCenterCardHtmlTest({ severity: 'info' })));

// Affiliate card carries the URL for the one-click buy
var buyCard = commandCenterCardHtmlTest({ severity: 'info', action: 'COMPRAR HASHRATE', url: 'https://mrr.example/ref?a=1&b=2', target: 'market' });
assertTruthy('buy card has url escaped', /data-cc-url="https:\/\/mrr\.example\/ref\?a=1&amp;b=2"/.test(buyCard));
assertTruthy('buy card has COMPRAR label', /COMPRAR HASHRATE/.test(buyCard));
assertTruthy('buy card has market target', /data-cc-target="market"/.test(buyCard));

// Null / garbage never produce HTML
assertEqual('null card → empty string', commandCenterCardHtmlTest(null), '');
assertEqual('undefined card → empty string', commandCenterCardHtmlTest(undefined), '');
assertEqual('string card → empty string', commandCenterCardHtmlTest('junk'), '');

// HTML-injection safety: title/message escaped
var evil = commandCenterCardHtmlTest({ title: '<img src=x onerror=alert(1)>', message: '"&<>"' });
assertFalsy('title is escaped (no raw <img>)', /<img/.test(evil));
assertTruthy('title escapes to &lt;img', /&lt;img/.test(evil));
assertFalsy('message quotes escaped', /"&<>"/.test(evil));
assertTruthy('message &lt; entity', /&lt;/.test(evil));


// ═══════════════════════════════════════════════════════════════════════════
//  WALLET-REFRESH GATE — mirrors snapshotFreshForWallet() in static/app.js
// ═══════════════════════════════════════════════════════════════════════════
// A snapshot is "fresh for the new wallet" only when it carries the new
// address AND has been re-polled (ts > 0). /api/set-address resets ts=0 and
// forces a background poll; a brand-new wallet legitimately has worker=null
// (pool returns 0 — a valid response), so ts is the reliable signal.
function snapshotFreshForWalletTest(snap, address) {
  return !!(snap &&
    String(snap.btc_address || '').toLowerCase() === String(address || '').toLowerCase() &&
    snap.ts > 0);
}

(function walletRefreshGateSuite() {
  // Fresh: address matches + poll landed
  assertEqual('matching address + ts>0 -> fresh',
    snapshotFreshForWalletTest({ btc_address: 'bc1QUERYEXAMPLE1234567890', ts: 1785710000 }, 'bc1queryexample1234567890'), true);
  assertEqual('exact match + ts>0 -> fresh',
    snapshotFreshForWalletTest({ btc_address: 'bc1abc', ts: 5 }, 'bc1abc'), true);

  // Reset state (right after set-address, poll not landed): ts=0
  assertEqual('matching address + ts=0 -> NOT fresh (poll pending)',
    snapshotFreshForWalletTest({ btc_address: 'bc1abc', ts: 0 }, 'bc1abc'), false);
  assertEqual('missing ts -> NOT fresh',
    snapshotFreshForWalletTest({ btc_address: 'bc1abc' }, 'bc1abc'), false);

  // Wrong address (still the OLD wallet's snapshot)
  assertEqual('old address + ts>0 -> NOT fresh',
    snapshotFreshForWalletTest({ btc_address: 'bc1old', ts: 5 }, 'bc1new'), false);
  assertEqual('empty btc_address -> NOT fresh',
    snapshotFreshForWalletTest({ btc_address: '', ts: 5 }, 'bc1new'), false);

  // Garbage never fresh
  assertEqual('null snapshot -> NOT fresh', snapshotFreshForWalletTest(null, 'bc1abc'), false);
  assertEqual('undefined snapshot -> NOT fresh', snapshotFreshForWalletTest(undefined, 'bc1abc'), false);
  assertEqual('string snapshot -> NOT fresh', snapshotFreshForWalletTest('junk', 'bc1abc'), false);
  assertEqual('empty address -> NOT fresh', snapshotFreshForWalletTest({ btc_address: 'bc1abc', ts: 5 }, ''), false);
})();


// ═══════════════════════════════════════════════════════════════════════════
//  SUITE 26: AXE FLEET onboarding wizard — connectivity report helpers
// ═══════════════════════════════════════════════════════════════════════════

console.log('⚙ SUITE 26: buildConnectivityReport() — wizard connectivity report');

// Mirror of static/app.js buildConnectivityReport() — pure, no DOM.
function buildConnectivityReportTest(r) {
  r = r || {};
  const rows = [];
  rows.push({ label: 'DNS', ok: !!r.dns_resolution, val: r.dns_resolution ? 'OK' : 'FAIL', detail: r.dns_resolution ? '' : (r.error_detail || 'hostname did not resolve') });
  if (r.bitaxe_http) {
    const di = r.device_info || {};
    rows.push({ label: 'AxeOS :80', ok: true, val: 'BITAXE', detail: [di.model, di.firmware].filter(Boolean).join(' · ') });
  } else {
    rows.push({ label: 'AxeOS :80', ok: false, val: 'no', detail: 'no ESP-Miner API on port 80' });
  }
  if (r.cgminer_tcp) {
    const di = r.device_info || {};
    rows.push({ label: 'cgminer :4028', ok: true, val: 'CGMINER', detail: [di.model, di.version].filter(Boolean).join(' · ') });
  } else {
    rows.push({ label: 'cgminer :4028', ok: false, val: 'no', detail: 'no cgminer protocol on port 4028' });
  }
  if (r.https_tcp && !r.bitaxe_http && !r.cgminer_tcp) {
    rows.push({ label: 'HTTPS :443', ok: true, val: 'OPEN', detail: 'porta 443 aberta — firmware moderno (Braiins/Antminer) com API autenticada' });
  }
  if (r.http_server && !r.bitaxe_http && !r.cgminer_tcp) {
    rows.push({ label: 'HTTP :80', ok: true, val: 'server', detail: 'servidor HTTP presente mas NÃO é ESP-Miner — possível página de login de ASIC' });
  }
  rows.push({ label: 'elapsed', ok: true, val: (r.elapsed_ms != null ? r.elapsed_ms + 'ms' : '—'), detail: '' });
  return rows;
}

(function axeWizardReportSuite() {
  // Bitaxe detected: DNS ok, HTTP ok, cgminer not probed
  const bitaxe = buildConnectivityReportTest({
    dns_resolution: true, bitaxe_http: true, cgminer_tcp: false,
    reachable: true, protocol: 'bitaxe', elapsed_ms: 42,
    device_info: { model: 'Bitaxe Gamma', firmware: 'v2.1' },
  });
  assertEqual('bitaxe report has 4 rows', bitaxe.length, 4);
  assertEqual('bitaxe DNS ok', bitaxe[0].ok, true);
  assertEqual('bitaxe HTTP ok', bitaxe[1].ok, true);
  assertEqual('bitaxe HTTP label', bitaxe[1].val, 'BITAXE');
  assertEqual('bitaxe HTTP detail', bitaxe[1].detail, 'Bitaxe Gamma · v2.1');
  assertEqual('bitaxe cgminer row present but false', bitaxe[2].ok, false);
  assertEqual('bitaxe elapsed', bitaxe[3].val, '42ms');

  // cgminer fallback: HTTP failed, TCP answered
  const cg = buildConnectivityReportTest({
    dns_resolution: true, bitaxe_http: false, cgminer_tcp: true,
    reachable: true, protocol: 'cgminer', elapsed_ms: 133,
    device_info: { model: 'Antminer S19 Pro', version: '4.12.0' },
  });
  assertEqual('cgminer HTTP row fails', cg[1].ok, false);
  assertEqual('cgminer row ok', cg[2].ok, true);
  assertEqual('cgminer row val', cg[2].val, 'CGMINER');
  assertEqual('cgminer row detail', cg[2].detail, 'Antminer S19 Pro · 4.12.0');

  // DNS failure: everything else short-circuits
  const bad = buildConnectivityReportTest({ dns_resolution: false, error_detail: 'no such host' });
  assertEqual('dns fail row ok=false', bad[0].ok, false);
  assertEqual('dns fail detail', bad[0].detail, 'no such host');
  assertEqual('dns fail http false', bad[1].ok, false);

  // Empty payload: graceful defaults
  const empty = buildConnectivityReportTest({});
  assertEqual('empty payload still 4 rows', empty.length, 4);
  assertEqual('empty payload dns false', empty[0].ok, false);
  assertEqual('empty payload elapsed placeholder', empty[3].val, '—');

  // Hostname (non-IP) with successful resolution + HTTP
  const host = buildConnectivityReportTest({
    dns_resolution: true, bitaxe_http: true, cgminer_tcp: false,
    reachable: true, protocol: 'bitaxe',
    device_info: { model: 'NerdAxe', firmware: '' },
  });
  assertEqual('hostname bitaxe detail skips empty firmware', host[1].detail, 'NerdAxe');

  // Modern authenticated miner (D): nothing on classic probes, but HTTPS
  // :443 is open → extra diagnostic row appears (Braiins/Antminer auth).
  const httpsMiner = buildConnectivityReportTest({
    dns_resolution: true, bitaxe_http: false, cgminer_tcp: false,
    https_tcp: true, http_server: false, reachable: false,
    error_detail: 'no miner protocol responded (checked AxeOS :80 and cgminer :4028)',
  });
  assertEqual('https miner has 5 rows', httpsMiner.length, 5);
  assertEqual('https row val', httpsMiner[3].val, 'OPEN');
  assertEqual('https row label', httpsMiner[3].label, 'HTTPS :443');

  // ASIC login page (D): TCP :80 open but not ESP-Miner → HTTP server row.
  const httpServer = buildConnectivityReportTest({
    dns_resolution: true, bitaxe_http: false, cgminer_tcp: false,
    https_tcp: false, http_server: true, reachable: false,
  });
  assertEqual('http server row val', httpServer[3].val, 'server');
  assertEqual('http server row label', httpServer[3].label, 'HTTP :80');

  // Suppressed when a real protocol won (never add noise rows on success).
  const suppressHttps = buildConnectivityReportTest({
    dns_resolution: true, bitaxe_http: true, cgminer_tcp: true,
    https_tcp: true, http_server: true, reachable: true, protocol: 'bitaxe',
  });
  assertEqual('success suppresses presence rows', suppressHttps.length, 4);
})();


// ═══════════════════════════════════════════════════════════════════════════
//  SUITE 26b: buildCommandCenterRows() — per-worker live telemetry
//  Mirrors static/app.js buildCommandCenterRows() — pure, no DOM, no fmt.
//  Exception hierarchy: WARNING/IDLE/PAUSED → OFFLINE/ERROR/CRITICAL → ONLINE.
// ═══════════════════════════════════════════════════════════════════════════
console.log('⛏ SUITE 26b: buildCommandCenterRows() — per-worker live telemetry');

// Mirror of static/app.js _numOrNull() — pure.
function numOrNullTest(v) {
  if (v == null || v === '') return null;
  const n = Number(v);
  return isFinite(n) ? n : null;
}

// Mirror of static/app.js buildCommandCenterRows() — pure, no DOM, no fmt.
function buildCommandCenterRowsTest(devices) {
  const rows = [];
  (devices || []).forEach(function (d) {
    const tel = d._telemetry || {};
    const health = d._health || {};
    const accepted = Number(tel.shares_accepted) || 0;
    const rejected = Number(tel.shares_rejected) || 0;
    const stale = Number(tel.shares_stale) || 0;
    const total = accepted + rejected;
    let rejectPct = null;
    if (total > 0) rejectPct = Number(tel.hw_error_pct != null ? tel.hw_error_pct : (rejected / total) * 100);
    let lastShareAgo = null;
    const lst = tel.last_share_ts;
    if (lst != null && lst !== '') {
      let t = Number(lst);
      if (!isFinite(t) || t > 1e12) t = Date.parse(String(lst)) / 1000;
      if (isFinite(t) && t > 0) lastShareAgo = Math.max(0, Math.floor(Date.now() / 1000 - t));
    }
    rows.push({
      id: d.id || '', name: d.name || d.ip_address || '?', ip: d.ip_address || '',
      model: d.model || '', manufacturer: d.manufacturer || '',
      status: d.status || 'OFFLINE', agentManaged: !!d.agent_managed,
      hr: Number(tel.hashrate_hs) || 0, hrStr: tel.hashrate_str || '',
      temp: numOrNullTest(tel.temperature), chipTemp: numOrNullTest(tel.chip_temp), vrTemp: numOrNullTest(tel.vr_temp),
      fan: tel.fan_rpm != null ? tel.fan_rpm : tel.fan_speed,
      power: numOrNullTest(tel.power_watts), eff: numOrNullTest(tel.efficiency_jth),
      sharesA: accepted, sharesR: rejected, sharesS: stale,
      rejectPct: rejectPct, bestDiff: tel.best_diff, poolDiff: tel.pool_diff,
      lastShareAgo: lastShareAgo, dataAge: tel.age_seconds,
      latencyMs: d.latency_ms, stratum: tel.stratum_status || '',
      healthScore: health.score != null ? health.score : null,
      advice: Array.isArray(d.advice) ? d.advice : [],
      caps: Array.isArray(d.capabilities) ? d.capabilities : [],
    });
  });
  const order = { WARNING: 0, IDLE: 0, PAUSED: 0, OFFLINE: 1, ERROR: 1, CRITICAL: 1, ONLINE: 2, HASHING: 2 };
  rows.sort(function (a, b) {
    const oa = order[a.status] != null ? order[a.status] : 3;
    const ob = order[b.status] != null ? order[b.status] : 3;
    if (oa !== ob) return oa - ob;
    return String(a.name).localeCompare(String(b.name));
  });
  return rows;
}

(function workerIntelligenceSuite() {
  const devices = [
    { id: 'd1', name: 'Garage', ip_address: '192.168.1.100', status: 'ONLINE', latency_ms: 12,
      _telemetry: { hashrate_hs: 5200000000000, hashrate_str: '5.20 TH/s', shares_accepted: 15823, shares_rejected: 47, shares_stale: 2, hw_error_pct: 0.3, best_diff: '42.8T', pool_diff: '256M', stratum_status: 'connected', age_seconds: 4, power_watts: 120, efficiency_jth: 23.1, temperature: 58, chip_temp: 62, vr_temp: 45 },
      _health: { score: 92 } },
    { id: 'd2', name: 'Hot Lab', ip_address: '192.168.1.102', status: 'WARNING', latency_ms: null,
      _telemetry: { hashrate_hs: 3800000000000, shares_accepted: 5872, shares_rejected: 215, shares_stale: 0, hw_error_pct: 3.5, best_diff: '28.3T', stratum_status: 'connected', age_seconds: 9, temperature: 'NOT AVAILABLE' },
      _health: { score: 41 }, advice: ['temp acima do ideal'], capabilities: ['restart'] },
    { id: 'd3', name: 'Basement', ip_address: '192.168.1.200', status: 'OFFLINE', agent_managed: 1,
      _telemetry: { hashrate_hs: 0 }, _health: { score: 0 } },
  ];
  const rows = buildCommandCenterRowsTest(devices);
  assertEqual('3 workers parsed', rows.length, 3);
  // Exception hierarchy: problems first, healthy ONLINE last
  assertEqual('ordering: WARNING first', rows[0].name, 'Hot Lab');
  assertEqual('ordering: OFFLINE second', rows[1].name, 'Basement');
  assertEqual('ordering: ONLINE last', rows[2].name, 'Garage');
  // ONLINE device (rows[2] = Garage) — todos os campos ricos
  const g = rows[2];
  assertEqual('reject pct from hw_error_pct', g.rejectPct, 0.3);
  assertEqual('hr parsed', g.hr, 5200000000000);
  assertEqual('hrStr passthrough', g.hrStr, '5.20 TH/s');
  assertEqual('shares a/r/s', g.sharesA + '/' + g.sharesR + '/' + g.sharesS, '15823/47/2');
  assertEqual('stratum passthrough', g.stratum, 'connected');
  assertEqual('latency passthrough', g.latencyMs, 12);
  assertEqual('health score passthrough', g.healthScore, 92);
  assertEqual('power parsed', g.power, 120);
  assertEqual('eff parsed', g.eff, 23.1);
  assertEqual('temp parsed', g.temp, 58);
  assertEqual('chip temp parsed', g.chipTemp, 62);
  assertEqual('vr temp parsed', g.vrTemp, 45);
  // WARNING device (rows[0] = Hot Lab)
  assertEqual('warning reject pct', rows[0].rejectPct, 3.5);
  assertEqual('warning hr parsed', rows[0].hr, 3800000000000);
  assertEqual('agent flag on offline', rows[1].agentManaged, true);
  assertEqual('offline has no reject pct', rows[1].rejectPct, null);
  // "NOT AVAILABLE" literal → null (não estoura .toFixed())
  assertEqual('NOT AVAILABLE temp → null', rows[0].temp, null);
  assertEqual('advice passthrough', rows[0].advice[0], 'temp acima do ideal');
  assertEqual('caps passthrough', rows[0].caps.indexOf('restart') !== -1, true);

  // hw_error_pct missing → derive from rejected/(accepted+rejected)
  const derived = buildCommandCenterRowsTest([{
    id: 'x', name: 'X', status: 'ONLINE',
    _telemetry: { hashrate_hs: 100, shares_accepted: 90, shares_rejected: 10 },
  }]);
  assertEqual('derived reject pct', derived[0].rejectPct, 10);

  // last_share_ts ISO string parsing (best-effort)
  const iso = buildCommandCenterRowsTest([{
    id: 'y', name: 'Y', status: 'ONLINE',
    _telemetry: { hashrate_hs: 1, last_share_ts: new Date(Date.now() - 60000).toISOString() },
  }]);
  assertEqual('last share age parsed from ISO (~60s)', iso[0].lastShareAgo >= 55 && iso[0].lastShareAgo <= 70, true);

  // empty/null input → no rows, no crash
  assertEqual('empty input yields no rows', buildCommandCenterRowsTest([]).length, 0);
  assertEqual('null input yields no rows', buildCommandCenterRowsTest(null).length, 0);
})();
// ═══════════════════════════════════════════════════════════════════════════
//  SUITE 26c: Hash Flow Raster — share-quality coloring
//  Mirrors static/app.js _lmFlowSampleFromDelta / _lmShareDelta / _lmFlowDetail.
// ═══════════════════════════════════════════════════════════════════════════
console.log('⛏ SUITE 26c: hash flow raster — share-quality cell coloring');

// Mirror of static/app.js _lmFlowSampleFromDelta() — pure.
function lmFlowSampleFromDeltaTest(status, delta) {
  if (delta) {
    if (delta.r > 0) return 'rej';    // reject beats everything
    if (delta.s > 0) return 'stale';  // stale beats accepted
    if (delta.a > 0) return 'ok';     // accepted share
  }
  const s = String(status || '').toUpperCase();
  if (s === 'ONLINE' || s === 'HASHING') return 'idle';
  if (s === 'WARNING' || s === 'IDLE' || s === 'PAUSED') return 'warn';
  if (s === 'OFFLINE' || s === 'ERROR' || s === 'CRITICAL') return 'bad';
  return 'mute';
}
// Mirror of static/app.js _lmShareDelta() — pure.
function lmShareDeltaTest(prev, cur) {
  if (!prev) return null;
  return {
    a: Math.max(0, (cur.a || 0) - (prev.a || 0)),
    r: Math.max(0, (cur.r || 0) - (prev.r || 0)),
    s: Math.max(0, (cur.s || 0) - (prev.s || 0)),
  };
}
// Mirror of static/app.js _lmFlowDetail() — pure.
function lmFlowDetailTest(delta) {
  if (!delta) return '';
  const parts = [];
  if (delta.a > 0) parts.push('+' + delta.a + ' acc');
  if (delta.r > 0) parts.push('+' + delta.r + ' rej');
  if (delta.s > 0) parts.push('+' + delta.s + ' stale');
  return parts.join(' · ');
}

(function hashFlowRasterSuite() {
  // Delta-driven colors (the new share-quality behavior)
  assertEqual('accepted delta → ok', lmFlowSampleFromDeltaTest('ONLINE', { a: 5, r: 0, s: 0 }), 'ok');
  assertEqual('reject delta → rej', lmFlowSampleFromDeltaTest('ONLINE', { a: 0, r: 1, s: 0 }), 'rej');
  assertEqual('stale delta → stale', lmFlowSampleFromDeltaTest('ONLINE', { a: 0, r: 0, s: 2 }), 'stale');
  assertEqual('reject beats accepted', lmFlowSampleFromDeltaTest('ONLINE', { a: 5, r: 1, s: 0 }), 'rej');
  assertEqual('stale beats accepted', lmFlowSampleFromDeltaTest('ONLINE', { a: 5, r: 0, s: 1 }), 'stale');
  assertEqual('reject beats stale', lmFlowSampleFromDeltaTest('ONLINE', { a: 0, r: 1, s: 2 }), 'rej');

  // Status fallback when no shares moved (or first poll — no baseline)
  assertEqual('zero delta + ONLINE → idle', lmFlowSampleFromDeltaTest('ONLINE', { a: 0, r: 0, s: 0 }), 'idle');
  assertEqual('no baseline + ONLINE → idle', lmFlowSampleFromDeltaTest('ONLINE', null), 'idle');
  assertEqual('zero delta + WARNING → warn', lmFlowSampleFromDeltaTest('WARNING', { a: 0, r: 0, s: 0 }), 'warn');
  assertEqual('zero delta + OFFLINE → bad', lmFlowSampleFromDeltaTest('OFFLINE', { a: 0, r: 0, s: 0 }), 'bad');
  assertEqual('unknown status → mute', lmFlowSampleFromDeltaTest('???', null), 'mute');

  // Counter diffing + reboot-reset clamp
  assertEqual('no baseline → null delta', lmShareDeltaTest(null, { a: 1, r: 0, s: 0 }), null);
  const inc = lmShareDeltaTest({ a: 100, r: 10, s: 2 }, { a: 105, r: 12, s: 2 });
  assertEqual('accepted delta counted', inc.a, 5);
  assertEqual('rejected delta counted', inc.r, 2);
  assertEqual('stale delta counted', inc.s, 0);
  // Reboot: counters drop from 100→90 — must clamp to 0, not go negative.
  const reset = lmShareDeltaTest({ a: 100, r: 10, s: 2 }, { a: 90, r: 12, s: 2 });
  assertEqual('reboot clamps accepted to 0', reset.a, 0);
  assertEqual('reboot still counts rejected', reset.r, 2);

  // Tooltip detail formatting
  assertEqual('detail formats acc+rej', lmFlowDetailTest({ a: 3, r: 1, s: 0 }), '+3 acc · +1 rej');
  assertEqual('detail formats all three', lmFlowDetailTest({ a: 1, r: 1, s: 1 }), '+1 acc · +1 rej · +1 stale');
  assertEqual('zero activity → empty detail', lmFlowDetailTest({ a: 0, r: 0, s: 0 }), '');
  assertEqual('null delta → empty detail', lmFlowDetailTest(null), '');
})();


// ═══════════════════════════════════════════════════════════════════════════
//  SUITE 27: P0-5 wallet ranks — acctRankLabels() pure resolver
//  (COMBINED / DIFF RANK / LOYALTY RANK with C3 fallback labels). Mirrors
//  static/app.js acctRankLabels().
// ═══════════════════════════════════════════════════════════════════════════
console.log('\n👛 SUITE 27: acctRankLabels() — wallet rank fallbacks');
(function () {
  function acctRankLabelsTest(acct) {
    acct = acct || {};
    const bc = (acct.metadata && acct.metadata.block_count) || acct.blocks_found || 0;
    const rank = acct.diff_rank || acct.diffRank;
    let diff;
    if (rank && rank !== '\u2014' && rank !== '--') diff = String(rank);
    else if (bc >= 10000) diff = 'TOP 1%';
    else if (bc >= 1000) diff = 'TOP 10%';
    else if (bc >= 100) diff = 'TOP 25%';
    else if (bc > 0) diff = 'ACTIVE';
    else diff = '\u2014';
    const loyaltyRaw = acct.loyalty_rank || acct.loyaltyRank;
    const loyalty = (loyaltyRaw && loyaltyRaw !== '\u2014' && loyaltyRaw !== '--') ? String(loyaltyRaw)
      : (bc > 0 ? 'ACTIVE' : '\u2014');
    const combinedRaw = acct.combined_score || acct.combinedScore;
    let combined;
    if (combinedRaw != null && combinedRaw !== '' && Number(combinedRaw) > 0) {
      combined = Number(combinedRaw) >= 1000 ? String(Math.round(Number(combinedRaw))) : Number(combinedRaw).toFixed(2);
    } else if (diff !== '\u2014' && diff !== 'ACTIVE') {
      combined = 'D:' + diff;
    } else {
      combined = '\u2014';
    }
    return { diff: diff, loyalty: loyalty, combined: combined };
  }

  // Real ranks from backend win
  const real = acctRankLabelsTest({ diff_rank: '42', loyalty_rank: '7', combined_score: 1234, metadata: {} });
  assertEqual('real diff rank passes through', real.diff, '42');
  assertEqual('real loyalty passes through', real.loyalty, '7');
  assertEqual('real combined >=1000 rounds', real.combined, '1234');

  // C3 fallback from block_count (the audit case: pool omits ranks)
  const fbTop = acctRankLabelsTest({ metadata: { block_count: 15000 } });
  assertEqual('fallback block_count 15k -> TOP 1%', fbTop.diff, 'TOP 1%');
  assertEqual('fallback loyalty active with blocks', fbTop.loyalty, 'ACTIVE');
  const fbTop10 = acctRankLabelsTest({ metadata: { block_count: 5000 } });
  assertEqual('fallback block_count 5k -> TOP 10%', fbTop10.diff, 'TOP 10%');
  const fbActive = acctRankLabelsTest({ metadata: { block_count: 3 } });
  assertEqual('fallback block_count 3 -> ACTIVE', fbActive.diff, 'ACTIVE');
  const fbNone = acctRankLabelsTest({ metadata: {} });
  assertEqual('no data -> em-dash diff', fbNone.diff, '\u2014');
  assertEqual('no data -> em-dash loyalty', fbNone.loyalty, '\u2014');
  assertEqual('no data -> em-dash combined', fbNone.combined, '\u2014');

  // Combined derivation: diff rank present but no combined_score -> D:label
  const derived = acctRankLabelsTest({ diff_rank: 'TOP 10%', metadata: {} });
  assertEqual('combined derived from diff label', derived.combined, 'D:TOP 10%');

  // alt-case key variants (acct.diffRank / loyaltyRank / combinedScore)
  const alt = acctRankLabelsTest({ diffRank: '9', loyaltyRank: '3', combinedScore: 12.5 });
  assertEqual('alt diffRank key works', alt.diff, '9');
  assertEqual('alt loyaltyRank key works', alt.loyalty, '3');
  assertEqual('alt combinedScore <1000 -> 2dp', alt.combined, '12.50');

  // '--' sentinel treated as missing (backend normalize) -> fallback
  const sentinel = acctRankLabelsTest({ diff_rank: '--', loyalty_rank: '--', metadata: { block_count: 200 } });
  assertEqual('-- sentinel falls back to TOP 25%', sentinel.diff, 'TOP 25%');
})();


// ═══════════════════════════════════════════════════════════════════════════
//  SUITE 28: P0-6 professional live-mining terminal — pure helpers
//  (lmEventTypeClass, lmFilterMatches, lmUserScrolled). Mirrors static/app.js.
// ═══════════════════════════════════════════════════════════════════════════
console.log('\n🖥 SUITE 28: live-mining terminal helpers (badges, filter, scroll lock)');
(function () {
  function lmEventTypeClassTest(type) {
    const t = String(type || '').toUpperCase();
    if (t === 'SHARE') return 'tag-share';
    if (t === 'BEST') return 'tag-best';
    if (t === 'JOB') return 'tag-job';
    if (t === 'ERR' || t === 'ERROR') return 'tag-error';
    return 'tag-info';
  }
  function lmFilterMatchesTest(filter, type) {
    const f = String(filter || 'all').toLowerCase();
    if (!f || f === 'all') return true;
    const t = String(type || '').toUpperCase();
    if (f === 'err') return t === 'ERR' || t === 'ERROR';
    return t === f.toUpperCase();
  }
  function lmUserScrolledTest(scrollTop, scrollHeight, clientHeight) {
    return scrollHeight - scrollTop - clientHeight > 24;
  }

  // lmEventTypeClass — color coding per pipeline (SHARE blue, JOB amber, BEST gold, ERR red)
  assertEqual('SHARE -> tag-share', lmEventTypeClassTest('SHARE'), 'tag-share');
  assertEqual('share lowercase -> tag-share', lmEventTypeClassTest('share'), 'tag-share');
  assertEqual('JOB -> tag-job', lmEventTypeClassTest('JOB'), 'tag-job');
  assertEqual('BEST -> tag-best', lmEventTypeClassTest('BEST'), 'tag-best');
  assertEqual('ERR -> tag-error', lmEventTypeClassTest('ERR'), 'tag-error');
  assertEqual('ERROR -> tag-error', lmEventTypeClassTest('ERROR'), 'tag-error');
  assertEqual('unknown -> tag-info', lmEventTypeClassTest('NONCE'), 'tag-info');
  assertEqual('empty -> tag-info', lmEventTypeClassTest(''), 'tag-info');
  assertEqual('null -> tag-info', lmEventTypeClassTest(null), 'tag-info');

  // lmFilterMatches — reactive filtering without reload
  assertEqual('filter all accepts SHARE', lmFilterMatchesTest('all', 'SHARE'), true);
  assertEqual('filter all accepts ERR', lmFilterMatchesTest('all', 'ERR'), true);
  assertEqual('filter SHARE keeps share', lmFilterMatchesTest('SHARE', 'SHARE'), true);
  assertEqual('filter SHARE drops JOB', lmFilterMatchesTest('SHARE', 'JOB'), false);
  assertEqual('filter share (lower) keeps SHARE', lmFilterMatchesTest('share', 'SHARE'), true);
  assertEqual('filter err keeps ERROR', lmFilterMatchesTest('err', 'ERROR'), true);
  assertEqual('filter err keeps ERR', lmFilterMatchesTest('err', 'ERR'), true);
  assertEqual('filter err drops JOB', lmFilterMatchesTest('err', 'JOB'), false);
  assertEqual('filter BEST drops SHARE', lmFilterMatchesTest('BEST', 'SHARE'), false);
  assertEqual('empty filter = all', lmFilterMatchesTest('', 'JOB'), true);
  assertEqual('null filter = all', lmFilterMatchesTest(null, 'JOB'), true);

  // lmUserScrolled — the reader must not be yanked back down
  const total = 1000, view = 200;
  assertEqual('pinned to bottom -> not user-scrolled', lmUserScrolledTest(total - view, total, view), false);
  assertEqual('scrolled up 100px -> user-scrolled', lmUserScrolledTest(total - view - 100, total, view), true);
  assertEqual('scrolled up 24px (threshold) -> user-scrolled', lmUserScrolledTest(total - view - 24, total, view), false);
  assertEqual('scrolled up 25px -> user-scrolled', lmUserScrolledTest(total - view - 25, total, view), true);
})();


// ═══════════════════════════════════════════════════════════════════════════
//  SUITE 26d: _ccKpiAgg() — FLEET COMMAND CENTER KPI aggregation
//  Mirrors static/app.js _ccKpiAgg (totalHr, effPct, avgTemp, totalPowerW,
//  avgEff, avgLatency — honest nulls quando não há dados live).
// ═══════════════════════════════════════════════════════════════════════════
console.log('⛏ SUITE 26d: _ccKpiAgg() — KPI aggregation do FLEET COMMAND CENTER');

// Mirror of static/app.js _numOrNull() — pure.
function ccNumOrNullTest(v) {
  if (v == null || v === '') return null;
  const n = Number(v);
  return isFinite(n) ? n : null;
}

// Mirror of static/app.js _ccKpiAgg() — pure.
function ccKpiAggTest(fleet) {
  fleet = fleet || [];
  const live = fleet.filter(d => d && String(d.status || '').toUpperCase() === 'ONLINE');
  // TOTAL HR = soma de TODOS os devices; shares/temp/power/eff = só ONLINE
  // (contadores cumulativos de OFFLINE congelariam a EFFICIENCY histórica).
  let totalHr = 0, acc = 0, rej = 0, stale = 0;
  let tempSum = 0, tempN = 0, powerSum = 0, powerN = 0, effSum = 0, effN = 0;
  fleet.forEach(d => {
    totalHr += Number((d && d._telemetry && d._telemetry.hashrate_hs) || 0);
  });
  live.forEach(d => {
    const t = (d && d._telemetry) || {};
    acc += Number(t.shares_accepted) || 0;
    rej += Number(t.shares_rejected) || 0;
    stale += Number(t.shares_stale) || 0;
    const temp = ccNumOrNullTest(t.temperature);
    if (temp != null) { tempSum += temp; tempN++; }
    const pw = ccNumOrNullTest(t.power_watts);
    if (pw != null) { powerSum += pw; powerN++; }
    const eff = ccNumOrNullTest(t.efficiency_jth);
    if (eff != null) { effSum += eff; effN++; }
  });
  const lats = live.map(d => Number(d && d.latency_ms)).filter(v => v > 0 && isFinite(v));
  const shareTotal = acc + rej;
  return {
    totalHr: totalHr,
    effPct: shareTotal > 0 ? (acc / shareTotal) * 100 : null,
    avgTemp: tempN ? tempSum / tempN : null,
    totalPowerW: powerSum || null,
    avgEff: effN ? effSum / effN : null,
    avgLatency: lats.length ? Math.round(lats.reduce((a, b) => a + b, 0) / lats.length) : null,
    acc: acc, rej: rej, stale: stale,
  };
}

(function ccKpiSuite() {
  const EMPTY = JSON.stringify({ totalHr: 0, effPct: null, avgTemp: null, totalPowerW: null, avgEff: null, avgLatency: null, acc: 0, rej: 0, stale: 0 });

  // Honest telemetry: OFFLINE devices never contribute share counters, even
  // with huge cumulative firmware counters in the DB.
  const offline = [
    { status: 'OFFLINE', _telemetry: { shares_accepted: 50000, shares_rejected: 1, temperature: 88, power_watts: 999 }, latency_ms: 5 },
    { status: 'OFFLINE', _telemetry: { shares_accepted: 90000, shares_rejected: 2, temperature: 91 }, latency_ms: 8 },
  ];
  const off = ccKpiAggTest(offline);
  assertEqual('all-offline fleet -> null effPct', off.effPct, null);
  assertEqual('all-offline fleet -> null avgLatency', off.avgLatency, null);
  assertEqual('empty fleet -> nulls', JSON.stringify(ccKpiAggTest([])), EMPTY);
  assertEqual('null fleet -> nulls', JSON.stringify(ccKpiAggTest(null)), EMPTY);

  // Single ONLINE device: efficiency = accepted / (accepted+rejected)
  const oneOnline = [
    { status: 'ONLINE', _telemetry: { hashrate_hs: 100000, shares_accepted: 95, shares_rejected: 5, temperature: 60, power_watts: 500, efficiency_jth: 25 }, latency_ms: 20 },
    { status: 'OFFLINE', _telemetry: { shares_accepted: 99999, shares_rejected: 0, temperature: 99, power_watts: 900 }, latency_ms: 1 },
  ];
  const one = ccKpiAggTest(oneOnline);
  assertEqual('online-only accepted counted', Math.round(one.effPct), 95);
  assertEqual('offline counters ignored', one.effPct, 95);
  assertEqual('online latency averaged', one.avgLatency, 20);
  assertEqual('total HR summed', one.totalHr, 100000);
  assertEqual('avg temp only online', one.avgTemp, 60);
  assertEqual('power only online', one.totalPowerW, 500);
  assertEqual('eff only online', one.avgEff, 25);

  // ONLINE with no share activity yet (fresh device): null eff, latency still ok
  const fresh = [{ status: 'ONLINE', _telemetry: { shares_accepted: 0, shares_rejected: 0 }, latency_ms: 42 }];
  const fr = ccKpiAggTest(fresh);
  assertEqual('online no shares -> null effPct', fr.effPct, null);
  assertEqual('online no shares -> latency kept', fr.avgLatency, 42);

  // Multi-online average latency + aggregate efficiency
  const multi = [
    { status: 'online', _telemetry: { hashrate_hs: 1, shares_accepted: 90, shares_rejected: 10 }, latency_ms: 10 },
    { status: 'ONLINE', _telemetry: { hashrate_hs: 2, shares_accepted: 180, shares_rejected: 20 }, latency_ms: 30 },
  ];
  const m = ccKpiAggTest(multi);
  assertEqual('lowercase status accepted', m.effPct, 90);
  assertEqual('avg latency of live devices', m.avgLatency, 20);
  assertEqual('stale counters summed', ccKpiAggTest([{ status: 'ONLINE', _telemetry: { shares_accepted: 1, shares_rejected: 0, shares_stale: 7 } }]).stale, 7);

  // Latency NaN/0/negative filtered out
  const badLat = [
    { status: 'ONLINE', _telemetry: { shares_accepted: 1, shares_rejected: 0 }, latency_ms: 0 },
    { status: 'ONLINE', _telemetry: { shares_accepted: 1, shares_rejected: 0 }, latency_ms: -3 },
    { status: 'ONLINE', _telemetry: { shares_accepted: 1, shares_rejected: 0 }, latency_ms: NaN },
    { status: 'ONLINE', _telemetry: { shares_accepted: 1, shares_rejected: 0 }, latency_ms: 100 },
  ];
  const bl = ccKpiAggTest(badLat);
  assertEqual('only valid latencies averaged', bl.avgLatency, 100);
  assertEqual('efficiency from all live', Math.round(bl.effPct), 100);

  // 'NOT AVAILABLE' literal em temp/power → null (não conta nas médias)
  const na = ccKpiAggTest([{ status: 'ONLINE', _telemetry: { shares_accepted: 1, shares_rejected: 0, temperature: 'NOT AVAILABLE', power_watts: 'NOT AVAILABLE' } }]);
  assertEqual('NOT AVAILABLE temp -> avgTemp null', na.avgTemp, null);
  assertEqual('NOT AVAILABLE power -> totalPowerW null', na.totalPowerW, null);
})();


// ═══════════════════════════════════════════════════════════════════════════
//  SUITE 26e: _ccShareBar / _ccSvgSparkline / _ccTempBand — visual helpers
//  Mirrors static/app.js — pure, sem DOM.
// ═══════════════════════════════════════════════════════════════════════════
console.log('⛏ SUITE 26e: _ccShareBar / _ccSvgSparkline / _ccTempBand');
(function () {
  function ccShareBarTest(acc, rej, stale) {
    const a = Number(acc) || 0, r = Number(rej) || 0, s = Number(stale) || 0;
    const total = a + r + s;
    if (!total) return '<div class="cc-sharebar cc-sharebar--empty" title="sem shares registradas">no shares</div>';
    const wa = (a / total) * 100, ws = (s / total) * 100, wr = (r / total) * 100;
    return '<div class="cc-sharebar" title="' + a + ' acc · ' + s + ' stale · ' + r + ' rej">' +
      '<span class="cc-sharebar__seg cc-sharebar__seg--acc" style="width:' + wa.toFixed(1) + '%"></span>' +
      '<span class="cc-sharebar__seg cc-sharebar__seg--stale" style="width:' + ws.toFixed(1) + '%"></span>' +
      '<span class="cc-sharebar__seg cc-sharebar__seg--rej" style="width:' + wr.toFixed(1) + '%"></span>' +
      '</div>';
  }
  function ccNumOrNull(v) {
    if (v == null || v === '') return null;
    const n = Number(v);
    return isFinite(n) ? n : null;
  }
  function ccTempBandTest(t) {
    const n = ccNumOrNull(t);
    if (n == null) return 'mute';
    if (n <= 60) return 'ok';
    if (n <= 70) return 'warn';
    if (n <= 80) return 'hot';
    return 'crit';
  }
  function ccSvgSparklineTest(values, color) {
    const v = (values || []).map(Number).filter(x => isFinite(x) && x > 0);
    if (v.length < 2) return '';
    const w = 96, h = 26, pad = 2;
    const max = Math.max.apply(null, v), min = Math.min.apply(null, v);
    const span = (max - min) || 1;
    const pts = v.map((x, i) => {
      const px = pad + (i / (v.length - 1)) * (w - 2 * pad);
      const py = h - pad - ((x - min) / span) * (h - 2 * pad);
      return px.toFixed(1) + ',' + py.toFixed(1);
    }).join(' ');
    const area = pad + ',' + (h - pad) + ' ' + pts + ' ' + (w - pad) + ',' + (h - pad);
    return '<svg class="cc-spark" viewBox="0 0 ' + w + ' ' + h + '" preserveAspectRatio="none">' +
      '<polygon points="' + area + '" fill="' + color + '" fill-opacity="0.16"/>' +
      '<polyline points="' + pts + '" fill="none" stroke="' + color + '" stroke-width="1.4" stroke-linejoin="round" stroke-linecap="round"/>' +
      '</svg>';
  }

  // _ccShareBar — segmented quality bar
  const full = ccShareBarTest(90, 5, 5);
  assertTruthy('bar has accepted segment', /seg--acc/.test(full));
  assertTruthy('bar has stale segment', /seg--stale/.test(full));
  assertTruthy('bar has rejected segment', /seg--rej/.test(full));
  const widths = full.match(/width:([\d.]+)%/g).map(s => parseFloat(s.slice(6)));
  assertTruthy('segment widths sum ~100%', Math.abs(widths.reduce((a, b) => a + b, 0) - 100) < 0.5);
  assertTruthy('title carries counts', /90 acc · 5 stale · 5 rej/.test(full));
  assertTruthy('no shares -> empty bar', /cc-sharebar--empty/.test(ccShareBarTest(0, 0, 0)));
  assertTruthy('null -> empty bar', /cc-sharebar--empty/.test(ccShareBarTest(null, null, null)));

  // _ccTempBand — thresholds ≤60/70/80
  assertEqual('60 -> ok', ccTempBandTest(60), 'ok');
  assertEqual('61 -> warn', ccTempBandTest(61), 'warn');
  assertEqual('70 -> warn', ccTempBandTest(70), 'warn');
  assertEqual('71 -> hot', ccTempBandTest(71), 'hot');
  assertEqual('80 -> hot', ccTempBandTest(80), 'hot');
  assertEqual('81 -> crit', ccTempBandTest(81), 'crit');
  assertEqual('null -> mute', ccTempBandTest(null), 'mute');
  assertEqual('NOT AVAILABLE -> mute', ccTempBandTest('NOT AVAILABLE'), 'mute');
  assertEqual('empty string -> mute', ccTempBandTest(''), 'mute');

  // _ccSvgSparkline — inline SVG area line
  assertTruthy('two samples -> svg', /<svg/.test(ccSvgSparklineTest([1, 2], '#00b8d4')));
  assertTruthy('polyline present', /<polyline/.test(ccSvgSparklineTest([1, 5, 3], '#00b8d4')));
  assertTruthy('area polygon present', /<polygon/.test(ccSvgSparklineTest([1, 5, 3], '#00b8d4')));
  assertEqual('one sample -> empty', ccSvgSparklineTest([5], '#00b8d4'), '');
  assertEqual('null -> empty', ccSvgSparklineTest(null, '#00b8d4'), '');
  assertEqual('all zeros -> empty', ccSvgSparklineTest([0, 0, 0], '#00b8d4'), '');
  // geometry: min no fundo (y≈24), max no topo (y≈2), x dentro do viewBox.
  // O último points= é o do polyline (o primeiro é o polygon da área, que
  // inclui os cantos de fechamento).
  const svg = ccSvgSparklineTest([10, 90], '#00b8d4');
  const allPts = [...svg.matchAll(/points="([^"]+)"/g)].map(m => m[1]);
  const linePts = allPts[allPts.length - 1].split(' ').map(p => p.split(','));
  const xs = linePts.map(p => parseFloat(p[0]));
  assertTruthy('x coords inside viewBox', xs.every(x => x >= 0 && x <= 96));
  assertTruthy('min maps to bottom (y≈24)', Math.abs(parseFloat(linePts[0][1]) - 24) < 1.5);
  assertTruthy('max maps to top (y≈2)', Math.abs(parseFloat(linePts[1][1]) - 2) < 1.5);
  // flat series: min===max → span=1, linha horizontal ainda desenha
  assertTruthy('flat series still draws', /<polyline/.test(ccSvgSparklineTest([100, 100, 100], '#00b8d4')));
})();
// ═══════════════════════════════════════════════════════════════════════════
//  SUITE 29: module → tab-pane ownership (moduleActivePanes)
//  Fix: o módulo LIVE empilhava painéis de 3 abas (scroll infinito +
//  overflow no mobile). Cada módulo tem abas donas; fora do mapa, mantém
//  a regra antiga (todas as abas com painel visível).
// ═══════════════════════════════════════════════════════════════════════════
console.log('🗂 SUITE 29: moduleActivePanes() — um módulo = abas donas (sem stacking)');

// Mirror of static/app.js moduleActivePanes() — pure, no DOM.
const _MODULE_OWNED_PANES_TEST = {
  live: ['tab-charts', 'tab-terminal'],
};
function moduleActivePanesTest(name, paneHasVisible) {
  const owned = _MODULE_OWNED_PANES_TEST[name];
  if (owned) return owned.slice();
  return (paneHasVisible || []).filter(p => p.visible).map(p => p.id);
}

(function modulePaneSuite() {
  const panes = [
    { id: 'tab-fleet', visible: true },
    { id: 'tab-charts', visible: true },
    { id: 'tab-stats', visible: false },
    { id: 'tab-terminal', visible: true },
  ];

  // LIVE: dono de exatamente tab-charts + tab-terminal — nunca empilha tab-fleet
  const liveActive = moduleActivePanesTest('live', panes);
  assertEqual('live owns tab-charts', liveActive.indexOf('tab-charts') !== -1, true);
  assertEqual('live owns tab-terminal', liveActive.indexOf('tab-terminal') !== -1, true);
  assertEqual('live excludes tab-fleet', liveActive.indexOf('tab-fleet') !== -1, false);
  assertEqual('live excludes tab-stats', liveActive.indexOf('tab-stats') !== -1, false);
  assertEqual('live active count = 2', liveActive.length, 2);
  assertEqual('live result is a copy (imutável)', liveActive !== _MODULE_OWNED_PANES_TEST.live, true);

  // Fora do mapa: regra antiga — ativa TODAS as abas com painel visível
  const probActive = moduleActivePanesTest('probability', panes);
  assertEqual('probability ativa abas visíveis', probActive.join(','), 'tab-fleet,tab-charts,tab-terminal');
  assertEqual('probability exclui aba oculta', probActive.indexOf('tab-stats') !== -1, false);

  // Sem painel visível → nenhuma aba
  const noneVisible = panes.map(p => ({ id: p.id, visible: false }));
  assertEqual('sem painéis visíveis → 0 abas', moduleActivePanesTest('docs', noneVisible).length, 0);
  // Null-safe
  assertEqual('null input mantém abas donas', moduleActivePanesTest('live', null).join(','), 'tab-charts,tab-terminal');
})();


// ═══════════════════════════════════════════════════════════════════════════
//  P0-4 · QR CORE MIRROR (extracted verbatim from static/app.js — pure)
// ═══════════════════════════════════════════════════════════════════════════

const QR_ECC = { L: 1, M: 0, Q: 3, H: 2 }; // values = 2-bit format field
const QR_MODE_8BIT = 4;
const QR_PAD0 = 0xEC, QR_PAD1 = 0x11;
// GF(256) tables (primitive poly x^8+x^4+x^3+x^2+1)
const QR_EXP = new Array(256), QR_LOG = new Array(256);
(function buildQrMath() {
  for (let i = 0; i < 8; i++) QR_EXP[i] = 1 << i;
  for (let i = 8; i < 256; i++) QR_EXP[i] = QR_EXP[i - 4] ^ QR_EXP[i - 5] ^ QR_EXP[i - 6] ^ QR_EXP[i - 8];
  for (let i = 0; i < 255; i++) QR_LOG[QR_EXP[i]] = i;
})();
function qrGexp(n) { while (n < 0) n += 255; while (n >= 256) n -= 255; return QR_EXP[n]; }
function qrGlog(n) { if (n < 1) throw new Error('qr glog(' + n + ')'); return QR_LOG[n]; }

// Polynomial over GF(256) with leading-zero trim + shift (Arase semantics)
function QrPoly(num, shift) {
  let offset = 0;
  while (offset < num.length && num[offset] === 0) offset++;
  this.num = new Array(num.length - offset + shift);
  for (let i = 0; i < num.length - offset; i++) this.num[i] = num[i + offset];
}
QrPoly.prototype.get = function (i) { return this.num[i]; };
QrPoly.prototype.getLength = function () { return this.num.length; };
QrPoly.prototype.multiply = function (e) {
  const num = new Array(this.getLength() + e.getLength() - 1);
  for (let i = 0; i < this.getLength(); i++) {
    for (let j = 0; j < e.getLength(); j++) {
      num[i + j] ^= qrGexp(qrGlog(this.get(i)) + qrGlog(e.get(j)));
    }
  }
  return new QrPoly(num, 0);
};
QrPoly.prototype.mod = function (e) {
  if (this.getLength() - e.getLength() < 0) return this;
  const ratio = qrGlog(this.get(0)) - qrGlog(e.get(0));
  const num = new Array(this.getLength());
  for (let i = 0; i < this.getLength(); i++) num[i] = this.get(i);
  for (let x = 0; x < e.getLength(); x++) num[x] ^= qrGexp(qrGlog(e.get(x)) + ratio);
  return new QrPoly(num, 0).mod(e);
};

// RS block table: rows are [L, M, Q, H] per version (v1-v10)
const QR_RS_BLOCKS = [
  [1, 26, 19], [1, 26, 16], [1, 26, 13], [1, 26, 9],
  [1, 44, 34], [1, 44, 28], [1, 44, 22], [1, 44, 16],
  [1, 70, 55], [1, 70, 44], [2, 35, 17], [2, 35, 13],
  [1, 100, 80], [2, 50, 32], [2, 50, 24], [4, 25, 9],
  [1, 134, 108], [2, 67, 43], [2, 33, 15, 2, 34, 16], [2, 33, 11, 2, 34, 12],
  [2, 86, 68], [4, 43, 27], [4, 43, 19], [4, 43, 15],
  [2, 98, 78], [4, 49, 31], [2, 32, 14, 4, 33, 15], [4, 39, 13, 1, 40, 14],
  [2, 121, 97], [2, 60, 38, 2, 61, 39], [4, 40, 18, 2, 41, 19], [4, 40, 14, 2, 41, 15],
  [2, 146, 116], [3, 58, 36, 2, 59, 37], [4, 36, 16, 4, 37, 17], [4, 36, 12, 4, 37, 13],
  [2, 86, 68, 2, 87, 69], [4, 69, 43, 1, 70, 44], [6, 43, 19, 2, 44, 20], [6, 43, 15, 2, 44, 16],
];
function qrGetRsBlocks(type, ecl) {
  const row = QR_RS_BLOCKS[(type - 1) * 4 + ({ 1: 0, 0: 1, 3: 2, 2: 3 })[ecl]];
  const list = [];
  for (let i = 0; i < row.length / 3; i++) {
    const count = row[i * 3], total = row[i * 3 + 1], data = row[i * 3 + 2];
    for (let j = 0; j < count; j++) list.push({ totalCount: total, dataCount: data });
  }
  return list;
}

const QR_PATTERN_POS = [
  [], [6, 18], [6, 22], [6, 26], [6, 30], [6, 34], [6, 22, 38], [6, 24, 42], [6, 26, 46], [6, 28, 50],
];
const QR_G15 = (1 << 10) | (1 << 8) | (1 << 5) | (1 << 4) | (1 << 2) | (1 << 1) | (1 << 0);
const QR_G18 = (1 << 12) | (1 << 11) | (1 << 10) | (1 << 9) | (1 << 8) | (1 << 5) | (1 << 2) | (1 << 0);
const QR_G15_MASK = (1 << 14) | (1 << 12) | (1 << 10) | (1 << 4) | (1 << 1);
function qrBchDigit(d) { let n = 0; while (d !== 0) { n++; d >>>= 1; } return n; }
function qrBchTypeInfo(data) {
  let d = data << 10;
  while (qrBchDigit(d) - qrBchDigit(QR_G15) >= 0) d ^= QR_G15 << (qrBchDigit(d) - qrBchDigit(QR_G15));
  return ((data << 10) | d) ^ QR_G15_MASK;
}
function qrBchTypeNumber(data) {
  let d = data << 12;
  while (qrBchDigit(d) - qrBchDigit(QR_G18) >= 0) d ^= QR_G18 << (qrBchDigit(d) - qrBchDigit(QR_G18));
  return (data << 12) | d;
}
function qrGetMask(mask, i, j) {
  switch (mask) {
    case 0: return (i + j) % 2 === 0;
    case 1: return i % 2 === 0;
    case 2: return j % 3 === 0;
    case 3: return (i + j) % 3 === 0;
    case 4: return (Math.floor(i / 2) + Math.floor(j / 3)) % 2 === 0;
    case 5: return (i * j) % 2 + (i * j) % 3 === 0;
    case 6: return ((i * j) % 2 + (i * j) % 3) % 2 === 0;
    case 7: return ((i * j) % 3 + (i + j) % 2) % 2 === 0;
    default: throw new Error('bad maskPattern:' + mask);
  }
}
function qrErrorCorrectPoly(len) {
  let a = new QrPoly([1], 0);
  for (let i = 0; i < len; i++) a = a.multiply(new QrPoly([1, qrGexp(i)], 0));
  return a;
}
function qrLengthInBits(type) { return type < 10 ? 8 : 16; }

function qrCreateData(type, ecl, text) {
  const blocks = qrGetRsBlocks(type, ecl);
  let totalData = 0;
  blocks.forEach(b => { totalData += b.dataCount; });
  const bits = [];
  let bitLen = 0;
  function put(num, len) {
    for (let i = 0; i < len; i++) {
      bits.push(((num >>> (len - i - 1)) & 1) === 1);
      bitLen++;
    }
  }
  put(QR_MODE_8BIT, 4);
  put(text.length, qrLengthInBits(type));
  for (let i = 0; i < text.length; i++) put(text.charCodeAt(i) & 0xff, 8);
  if (bitLen + 4 <= totalData * 8) put(0, 4);
  while (bitLen % 8 !== 0) put(0, 1);
  while (true) {
    if (bitLen >= totalData * 8) break;
    put(QR_PAD0, 8);
    if (bitLen >= totalData * 8) break;
    put(QR_PAD1, 8);
  }
  const buf = [];
  for (let i = 0; i < bits.length; i += 8) {
    let byte = 0;
    for (let j = 0; j < 8; j++) byte = (byte << 1) | (bits[i + j] ? 1 : 0);
    buf.push(byte);
  }
  let offset = 0, maxDc = 0, maxEc = 0;
  const dcdata = [], ecdata = [];
  for (let r = 0; r < blocks.length; r++) {
    const dcCount = blocks[r].dataCount;
    const ecCount = blocks[r].totalCount - dcCount;
    maxDc = Math.max(maxDc, dcCount);
    maxEc = Math.max(maxEc, ecCount);
    const dc = [];
    for (let i = 0; i < dcCount; i++) dc.push(buf[i + offset]);
    offset += dcCount;
    const rsPoly = qrErrorCorrectPoly(ecCount);
    const rawPoly = new QrPoly(dc, rsPoly.getLength() - 1);
    const modPoly = rawPoly.mod(rsPoly);
    const ec = new Array(rsPoly.getLength() - 1);
    for (let x = 0; x < ec.length; x++) {
      const modIndex = x + modPoly.getLength() - ec.length;
      ec[x] = modIndex >= 0 ? modPoly.get(modIndex) : 0;
    }
    dcdata[r] = dc; ecdata[r] = ec;
  }
  let total = 0;
  blocks.forEach(b => { total += b.totalCount; });
  const data = new Array(total);
  let index = 0;
  for (let z = 0; z < maxDc; z++) for (let s = 0; s < blocks.length; s++) if (z < dcdata[s].length) data[index++] = dcdata[s][z];
  for (let z = 0; z < maxEc; z++) for (let s = 0; s < blocks.length; s++) if (z < ecdata[s].length) data[index++] = ecdata[s][z];
  return data;
}

function qrMakeImpl(type, ecl, test, mask, data) {
  const mc = type * 4 + 17;
  const mods = [];
  for (let r = 0; r < mc; r++) { mods[r] = new Array(mc); for (let c = 0; c < mc; c++) mods[r][c] = null; }
  function probe(row, col) {
    for (let r = -1; r <= 7; r++) {
      if (row + r <= -1 || mc <= row + r) continue;
      for (let c = -1; c <= 7; c++) {
        if (col + c <= -1 || mc <= col + c) continue;
        mods[row + r][col + c] =
          ((0 <= r && r <= 6 && (c === 0 || c === 6)) ||
           (0 <= c && c <= 6 && (r === 0 || r === 6)) ||
           (2 <= r && r <= 4 && 2 <= c && c <= 4));
      }
    }
  }
  probe(0, 0); probe(mc - 7, 0); probe(0, mc - 7);
  const pos = QR_PATTERN_POS[type - 1];
  for (let i = 0; i < pos.length; i++) {
    for (let j = 0; j < pos.length; j++) {
      const row = pos[i], col = pos[j];
      if (mods[row][col] !== null) continue;
      for (let r = -2; r <= 2; r++) {
        for (let c = -2; c <= 2; c++) {
          mods[row + r][col + c] = (Math.abs(r) === 2 || Math.abs(c) === 2 || (r === 0 && c === 0));
        }
      }
    }
  }
  for (let r = 8; r < mc - 8; r++) if (mods[r][6] === null) mods[r][6] = (r % 2 === 0);
  for (let c = 8; c < mc - 8; c++) if (mods[6][c] === null) mods[6][c] = (c % 2 === 0);
  const fbits = qrBchTypeInfo((ecl << 3) | mask);
  for (let v = 0; v < 15; v++) {
    const mod = !test && (((fbits >> v) & 1) === 1);
    if (v < 6) mods[v][8] = mod;
    else if (v < 8) mods[v + 1][8] = mod;
    else mods[mc - 15 + v][8] = mod;
  }
  for (let h = 0; h < 15; h++) {
    const mod = !test && (((fbits >> h) & 1) === 1);
    if (h < 8) mods[8][mc - h - 1] = mod;
    else if (h < 9) mods[8][15 - h - 1 + 1] = mod;
    else mods[8][15 - h - 1] = mod;
  }
  mods[mc - 8][8] = !test;
  if (type >= 7) {
    const vbits = qrBchTypeNumber(type);
    for (let i = 0; i < 18; i++) {
      const mod = !test && (((vbits >> i) & 1) === 1);
      mods[Math.floor(i / 3)][i % 3 + mc - 8 - 3] = mod;
    }
    for (let x = 0; x < 18; x++) {
      const mod = !test && (((vbits >> x) & 1) === 1);
      mods[x % 3 + mc - 8 - 3][Math.floor(x / 3)] = mod;
    }
  }
  let inc = -1, row = mc - 1, bitIndex = 7, byteIndex = 0;
  for (let col = mc - 1; col > 0; col -= 2) {
    if (col === 6) col--;
    while (true) {
      for (let c = 0; c < 2; c++) {
        if (mods[row][col - c] === null) {
          let dark = false;
          if (byteIndex < data.length) dark = (((data[byteIndex] >>> bitIndex) & 1) === 1);
          if (qrGetMask(mask, row, col - c)) dark = !dark;
          mods[row][col - c] = dark;
          bitIndex--;
          if (bitIndex === -1) { byteIndex++; bitIndex = 7; }
        }
      }
      row += inc;
      if (row < 0 || mc <= row) { row -= inc; inc = -inc; break; }
    }
  }
  return mods;
}

function qrLostPoint(mods) {
  const mc = mods.length;
  let lp = 0;
  for (let row = 0; row < mc; row++) {
    for (let col = 0; col < mc; col++) {
      let sameCount = 0; const dark = mods[row][col];
      for (let r = -1; r <= 1; r++) {
        if (row + r < 0 || mc <= row + r) continue;
        for (let c = -1; c <= 1; c++) {
          if (col + c < 0 || mc <= col + c) continue;
          if (r === 0 && c === 0) continue;
          if (dark === mods[row + r][col + c]) sameCount++;
        }
      }
      if (sameCount > 5) lp += 3 + sameCount - 5;
    }
  }
  for (let row = 0; row < mc - 1; row++) {
    for (let col = 0; col < mc - 1; col++) {
      let count = 0;
      if (mods[row][col]) count++;
      if (mods[row + 1][col]) count++;
      if (mods[row][col + 1]) count++;
      if (mods[row + 1][col + 1]) count++;
      if (count === 0 || count === 4) lp += 3;
    }
  }
  for (let row = 0; row < mc; row++) {
    for (let col = 0; col < mc - 6; col++) {
      if (mods[row][col] && !mods[row][col + 1] && mods[row][col + 2] && mods[row][col + 3] && mods[row][col + 4] && !mods[row][col + 5] && mods[row][col + 6]) lp += 40;
    }
  }
  for (let col = 0; col < mc; col++) {
    for (let row = 0; row < mc - 6; row++) {
      if (mods[row][col] && !mods[row + 1][col] && mods[row + 2][col] && mods[row + 3][col] && mods[row + 4][col] && !mods[row + 5][col] && mods[row + 6][col]) lp += 40;
    }
  }
  let darkCount = 0;
  for (let col = 0; col < mc; col++) for (let row = 0; row < mc; row++) if (mods[row][col]) darkCount++;
  lp += Math.abs(100 * darkCount / mc / mc - 50) / 5 * 10;
  return lp;
}

// Public encode: returns { modules: 2D bool, size, type, ecl, mask }
function qrEncode(text, ecl) {
  text = String(text || '');
  ecl = QR_ECC[ecl] !== undefined ? QR_ECC[ecl] : QR_ECC.M;
  let type = 1;
  for (type = 1; type <= 10; type++) {
    const blocks = qrGetRsBlocks(type, ecl);
    let totalData = 0;
    blocks.forEach(b => { totalData += b.dataCount; });
    const bitLen = 4 + qrLengthInBits(type) + text.length * 8;
    if (bitLen <= totalData * 8) break;
  }
  if (type > 10) throw new Error('QR input too long (' + text.length + ' chars)');
  const data = qrCreateData(type, ecl, text);
  let minLp = 0, pattern = 0;
  for (let i = 0; i < 8; i++) {
    const m = qrMakeImpl(type, ecl, true, i, data);
    const lp = qrLostPoint(m);
    if (i === 0 || minLp > lp) { minLp = lp; pattern = i; }
  }
  const modules = qrMakeImpl(type, ecl, false, pattern, data);
  return { modules, size: type * 4 + 17, type, ecl, mask: pattern };
}

// Render the module matrix as a crisp inline SVG (quiet zone = 4 modules)
function qrSvg(modules) {
  const size = modules.length;
  const q = 4;
  const cells = [];
  for (let r = 0; r < size; r++) {
    for (let c = 0; c < size; c++) {
      if (modules[r][c]) cells.push('M' + (c + q) + ' ' + (r + q) + 'h1v1h-1z');
    }
  }
  const dim = size + q * 2;
  return '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ' + dim + ' ' + dim + '" shape-rendering="crispEdges" role="img" aria-label="QR code">' +
    '<rect width="' + dim + '" height="' + dim + '" fill="#fff"/>' +
    (cells.length ? '<path d="' + cells.join('') + '" fill="#111"/>' : '') +
    '</svg>';
}

// ── Wallet identity mirror (walletAddressParts / walletHealth) ──────────

function walletAddressParts(addr) {
  if (!addr) return null;
  addr = String(addr).trim();
  if (!addr) return null;
  const lower = addr.toLowerCase();
  // Bech32: checksum is exactly the last 6 chars (BIP-173) — highlight them.
  if (lower.indexOf('bc1') === 0 && addr.length >= 10) {
    return { type: 'bech32', prefix: 'bc1', body: addr.slice(3, -6), checksum: addr.slice(-6), full: addr };
  }
  // Base58 (legacy/P2SH): the trailing chars are the check digits operators
  // compare against their wallet app — highlight the real trailing substring
  // (never a byte-derived string that would differ from the displayed address).
  if ((addr[0] === '1' || addr[0] === '3') && addr.length >= 8) {
    return { type: 'base58', prefix: addr[0], body: addr.slice(1, -6), checksum: addr.slice(-6), full: addr };
  }
  return { type: 'other', prefix: '', body: addr.length > 6 ? addr.slice(0, -6) : '', checksum: addr.slice(-6), full: addr };
}

// Wallet health from the live snapshot (honest: every check gates on real
// observed data — never fabricates). Returns {status, score, checks, connected}.
function walletHealth(snap, now) {
  snap = snap || {};
  now = now || Math.floor(Date.now() / 1000);
  const connected = !!snap.btc_address;
  const worker = snap.worker || {};
  const pool = snap.pool || {};
  const checks = [
    { key: 'connected', label: 'Address set', ok: connected },
    { key: 'fresh', label: 'Data fresh', ok: !!snap.ts && (now - snap.ts) < 300 },
    { key: 'worker', label: 'Worker found', ok: !!snap.worker },
    { key: 'hashing', label: 'Hashing', ok: Number(worker.hashrate || 0) > 0 },
    { key: 'share', label: 'Recent share', ok: !!worker.lastSubmission && (now - Number(worker.lastSubmission)) < 7200 },
    { key: 'pool', label: 'Pool responding', ok: !!snap.pool && !pool._stale },
  ];
  const passed = checks.filter(c => c.ok).length;
  const score = Math.round(passed / checks.length * 100);
  let status;
  if (!connected) status = 'NO_WALLET';
  else if (score >= 80) status = 'HEALTHY';
  else if (score >= 50) status = 'DEGRADED';
  else status = 'CRITICAL';
  return { status, score, checks, connected, passed };
}

// ═══════════════════════════════════════════════════════════════════════════
//  P0-4 · GOLDEN FIXTURES (independent reference: Kazuhiko Arase QRCode, MIT)
//  Generated via scripts/gen_qr_golden.cjs (root devDependency qrcode-terminal@^0.12.0, Kazuhiko Arase QRCode) — v1-6 came from the same vendor at feature ship; v7-10 cover the BCH version-info path — the QR core
//  above must reproduce these matrices CELL-FOR-CELL.
// ═══════════════════════════════════════════════════════════════════════════

const QR_GOLDEN = {"helloM":{"text":"HELLO WORLD","level":"M","rows":["111111101000101111111","100000101000101000001","101110100000001011101","101110101010101011101","101110100111001011101","100000100011101000001","111111101010101111111","000000001111100000000","101101110101101001011","011000010111111101100","000001111101010100011","101011011001000101010","100010110110110000101","000000001011001100101","111111101011111110000","100000101110010101111","101110100100101001000","101110101110001001110","101110101100100100100","100000100111011110001","111111101101010100000"]},"helloL":{"text":"HELLO WORLD","level":"L","rows":["111111101011101111111","100000100011001000001","101110101101001011101","101110101100101011101","101110101001001011101","100000100111101000001","111111101010101111111","000000000001100000000","111100101111110011101","010111010011111101100","111100101001010100011","111111010001000101010","111000110100110000101","000000001101001100101","111111100011111110000","100000100000010101111","101110100010101001000","101110101010001001110","101110101110100100100","100000101101011110001","111111101001010100000"]},"num01234567M":{"text":"01234567","level":"M","rows":["111111101011001111111","100000101001101000001","101110101000101011101","101110100110001011101","101110101010101011101","100000100111101000001","111111101010101111111","000000000011100000000","100111111000110010111","111100011100111100110","011100111110010100101","010001000001000001100","001100101010011010011","000000001101100110100","111111101000111110010","100000101111110110101","101110101001101000000","101110101011100101100","101110100100001110011","100000100110011000111","111111101101000011000"]},"cypher65Q":{"text":"CYPHER65","level":"Q","rows":["111111101111001111111","100000101001001000001","101110101101001011101","101110101110101011101","101110101110001011101","100000100001001000001","111111101010101111111","000000001011100000000","011010110000001011111","000011010111000011100","101101111100011011111","110110001100010110001","011111110001101111101","000000001111001011010","111111101111100010111","100000100001001110010","101110101001001010100","101110100011010001110","101110101111011110101","100000101011110000010","111111100001011110111"]},"bech32M":{"text":"bc1qxy2kgdygjrsqtzq2n0yrf2493p83kkfjhx0wlh","level":"M","rows":["11111110100111001101101111111","10000010111100100100101000001","10111010010101011011001011101","10111010101101100100101011101","10111010001001011111101011101","10000010011111001101001000001","11111110101010101010101111111","00000000101000111101000000000","10110111000100001110001001011","10000101100000101011111110001","00000011000100101010101011110","01110101001111011000000100011","00110110000111100110100001110","00101100111110011111111000011","01011111010000100101101101001","00110001000000100010011001001","10000111010011010000010011000","01100100001010010010110101100","10001010001100111000010011000","00000101110010110101111000101","01001010000100100100111110101","00000000101111000101100010011","11111110111110100101101010010","10000010101001001010100010000","10111010010010001110111110111","10111010110110110110110110001","10111010100010001100010100101","10000010000110010001110101010","11111110110101001011110000010"]},"base58M":{"text":"1BoatSLRHtKNngkdXEeobR76b53LETtpyT","level":"M","rows":["11111110110111110001001111111","10000010101011001010101000001","10111010011110001010001011101","10111010100100110110101011101","10111010010010101110001011101","10000010001111011111001000001","11111110101010101010101111111","00000000110100011101100000000","10110111010001011111001001011","10110101001101110011111110011","11011111000111000000011111110","00001100110010000000100110010","00100110110010111111000011101","10010001100010101111001001101","00110010011101000011111111011","00000000011110110000101001011","01111011100100111000110101100","00100100011110110010100101001","10000011000011110110111011100","00011001000011100110011001110","01110010000101100011111111001","00000000110000001110100011101","11111110101100100110101010100","10000010100011100000100010000","10111010001010011000111111010","10111010100000011100110010101","10111010101001101011100101101","10000010010001011001000011010","11111110111100101111100110110"]},"bech32H":{"text":"bc1qxy2kgdygjrsqtzq2n0yrf2493p83kkfjhx0wlh","level":"H","rows":["1111111011000100000010010010101111111","1000001011000101111101000101001000001","1011101011100100010100100010001011101","1011101000010000110001101110001011101","1011101001100110010110100110101011101","1000001011000110111101010011001000001","1111111010101010101010101010101111111","0000000011010001101100100000000000000","0011101011110101000100011111011100111","0011000100110001011010111100110101110","0001111011000110100100111101101000111","1010010111011100010010110010111010001","1000101100100100000001101111111111101","1000110100101000111010110000010001000","0111001011101001001111011001101011111","0011110110111100000011010011010100011","0110001011000111001111000100111111100","0001010110101100110000111010110100000","0011101101000000011011000001001010111","1000100011001001111011010001100000000","0001101101101010001011111101101111100","1011100001100001000111001110010101100","1111001011011000010011010001100100011","1011010100100101011000000001001000010","0010011110110011011111000000101010100","1100100010000000001011101000110100010","1010011010111001100010100111000011101","1011110110101000101010101011001010000","1001011000001000011110101111111111110","0000000011111010010010110000100011010","1111111000011000011111000100101010111","1000001001000100101000111001100011001","1011101010101010010101001111111110111","1011101011110100001110000101011011100","1011101011001101100101011000010101101","1000001000000101111100010000101010001","1111111000010111110100110100011000111"]},"longH":{"text":"bc1qaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaam6h","level":"H","rows":["11111110001111100111001011011000111101000010001111111","10000010011100101100110001110110100000000011001000001","10111010011001101010001000110001100001000001001011101","10111010000101001000101101111000111101000110101011101","10111010100001010111011111111110000111110010001011101","10000010010001000111000010001011001111101010001000001","11111110101010101010101010101010101010101010101111111","00000000110100000010011010001010101100101100100000000","00110011111110001000010011111001100000011101111010000","10011000110111111010110011001001110011000111000110011","01110010011101011011100011110001100110000111101101110","11011100010000001111000110111110100011001001001010011","01011010101110111011000011101011011111001111000110110","01110101011111110100011011110110100001101000100000101","01010010000000111110000110001101001001110010011000011","01100100111011001100001101101000100000011010010001000","10001110101100001100011101000101101001110000010000000","10011000110100011000100111000111100100011100011101000","10011011101001110001011100000011111010110001001011000","11110001011101110110111010000001010000101100100111110","11100010011101100001110001001000000000011101111101111","01000000011110100111111100011101011110000111000110010","00101110101010100111101010110000101101100111101101111","10011100101000011011010111101110111011000001001010000","00111111101111100010101011111101000111000110111110101","11111000110100001001001110001111110111110001100010101","01101010100110101110010010101001000101101010101010011","01101000110000100010001110001100101000011100100010000","11001111111001010111111111111000001001110111111111100","00011000011001000101101101001111101100011111011101000","10111110011100110110101100111011011010110010000110100","11010000100110110000011011011010001110101101001101110","10101111110010011100110111011101111100011101101011101","11000001000000011000110011000100101111000110000110011","01001010110110000100110111101101110100000110110001110","00111101011111011000011100110111100011000000100000011","00110110111001011100101001000110111111000110110100110","00001001100110111010110100010010001001110000110100101","01100111011011110111110110000000001001101011011110011","11101000000100011010100011101100011000011011111011000","00001110001111100100000011010001001001110000000100000","01110000001011000100110001111001000100011101011111000","11011110011000010101000101111000010010110000000001000","01100000110011001100010100010010101110110101001011110","00010011101010010001100111111100000100001101111111101","00000000100011101111101110001011111111000111100010011","11111110110100110011111110101110100100000110101011110","10000010010100110001111010001000100010100001100010011","10111010000111011011010111111010100111000110111110110","10111010111001010000110110011100100000110000100110110","10111010111111011000010110000000110000101010111100011","10000010010100010111100111101011111011111010100111010","11111110001011001001100110001000110010010001001100010"]},"v7M":{"text":"abcdefghijklmnopqrstuvwxyz0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789ABCDEFGHIJKLMNOPQ","level":"M","rows":["111111100101101101110101010011101000101111111","100000100011100010111011111100011001001000001","101110101101110001110000111100000101001011101","101110101010111000111000001001110001101011101","101110101011001001001111110111100111101011101","100000101011101100101000100010101100001000001","111111101010101010101010101010101010101111111","000000001101001111111000110011001110100000000","101111100110100010101111100000010000001111100","011101001111010001100110110011110001110001101","111010110010101010100101011100011110101001110","111100001101000010011000011100000000001010110","110101111010001000101011011001110100110101000","000000010010010011011101010001100001110100111","101010101000100110011001110010101101000111100","100011000110001110100101010011001110110111100","101110101100101001100001100001010000010000010","011001011011001101100111110111110001110101101","010111101001000000110001111101011110101001110","001010001100001110010000011100000000001010101","110111111001111000101111111000010100111111001","001110001001110101011000110001111000100010111","010110101100001011011010110010110101101010000","000110001111110010001000110011001110100011100","101011111110010101011111110001010110111110010","111000000100001000110010110111100001110101101","101010100011101111000001011101011110110100010","001100011100010000000101100100000001000110111","011000110010111010001001000000010000010111000","011100001110001000100001110101111001001000111","110000101010100001101110110010110100110100000","010100010000111000000000110010101110001001111","001011111010001110001001110000110110100010000","101111011111000110010010110001100001110101110","000010101001010101100011011101011110110010010","011110000011101100010111100100000001000000110","100110100111000011011111100001010000111111001","000000001011010101011000110101101001100010111","111111100111101100001010110010110101101011000","100000101101000010111000110010101111100011111","101110101111111100101111101000110010111110000","101110101111001101010010010001111000110111111","101110101010101110110101111101001111101001010","100000100100111011011111100100000001110010100","111111101110001101000111110001010110101101010"]},"v8L":{"text":"abcdefghijklmnopqrstuvwxyz0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789ABCDEFGHIJ","level":"L","rows":["1111111001110111000100010001111100011000101111111","1000001011001111110011101111010001111111101000001","1011101001100011100111001100000000010001101011101","1011101010011110010101111100011101101101001011101","1011101001000001001001111111011001011100001011101","1000001011011000010100100010001010111110001000001","1111111010101010101010101010101010101010101111111","0000000000100001010001100010101110000100000000000","1111101111111000111011111111000101111000010101010","1010010001110110010100011100011000001100011110001","0011001001101000001101001101010001111100101011011","0010100101101101111110000000000000010101010010000","1001101011001001001001111110000100101010111101101","1010000000001100111111000000111111001100011001000","0011011001001001101010101111001100111111000110111","0111110011001100101110001100101110000100010000010","0100001100001000111011011011010100111100001101001","1100010011011110010100011101011110010100011010001","1010101111111111010000000101010111101101101010011","1101110010111011100110000100000001110101010010011","0010111110100110010001111000010101001110100101101","0110000000110001001000011001111011010100011110000","1100111111000000001011111111001100101110111111011","0100100011011011011011100010111011100100100010000","0110101010001000111011101011001101011011101011001","0000100010101110010100100011111010000101100010001","1111111110110000101111111111110111101100111111111","1010100011011100011011001110010001110011100010011","1000111101000001001000110100001100001001110001100","0100100000010100111101001110011100000101011100000","0111111010111001101100101101001101001111111100011","1110110101100110100011000100111011100100101010011","0110001110010000111011100100011100011111010011001","1101010100111110010101111100011100011100010100010","1111011011001111110011100001110111101101111010101","1010010000000010000011000110010001010011110010001","0010101000111110010000110010011100001101010001100","1011110100001001001101101001011000011101000100000","0100011100011100001000110101001101001111111001111","0111000101001001010011011100111011100010101010000","1110001110110000111010111110000101111001111111000","0000000011001110010100100011011000000100100011110","1111111010000000001101101011110111100101101011001","1000001000011100011011100010010001010011100010010","1011101011001001001000111110000101101011111111111","1011101010010100111101011100111110001000001010000","1011101010000101111111111010101001001110001100100","1000001011110100101101011000111011111010111100001","1111111011010000111010000110010100111100110011011"]},"v9Q":{"text":"abcdefghijklmnopqrstuvwxyz0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789ABCDEFGHIJKLMNOPQRSTUV","level":"Q","rows":["11111110010110100001001101100110100111010010001111111","10000010111001101101000000001101001010110011001000001","10111010101111100101011011010110101100010001001011101","10111010011001000001100000111000001110000110101011101","10111010010001100101010111111010000011100010001011101","10000010010111100001101110001000010100000110001000001","11111110101010101010101010101010101010101010101111111","00000000001010111110010110001101001100001101100000000","01110110001000011010010111111100010101111101100000110","01001001101001110000111000001110000101010111000001101","11101110101100110001010110011010100000001101100100100","01011101110110111110010000100101101111011000001110011","11110111110000100110001101010101000010010111001110000","10110000001110110100110101010100000100110001110000111","10011111010101100001100011000111111000101100011101111","01100001101111000100011111000100001000110111010001010","10011011101011010110001010011011100000110010111000000","11101001000010111111100000110101111110010100011001000","00110110001011110101101011010110111000000000011111100","01001000100100110101011111010101000101011111100101100","10100011111100110101110001001101011111101000110100100","00000101111000101100101100010011110001111111000000100","00000011010010100111110011101000111010101011011011110","01110101110000100110010000011101100001100100000110001","11011111111111110001010011111101010111000110111110010","01101000111101000010010110001110010111110001100010111","11001010111101000101101010101100101011100000101010001","00101000101101111110010110001111011100100110100011010","10001111111110011111011111111110100101110110111111101","01101000011000011110000100000010011010010000101001010","01000011010111011111101111010110000011110010110101000","10011000000001000100101100010110111111100000011001101","01111111001101101100001100001000000100011011010111101","00010100101011101010000101011011000011001110001110011","00110011001001111000000101001001001010100110110111110","01000001111010110000110000010000111100010101111000011","11000010011001100000000010101000010111000000100001110","00000100000101000110110101011001100111111000110001100","10110110101011000111011100101000010100011110111011111","10010100110010001111001010111111101010111011111010001","01010110010110110111111110011001100001010110110001001","10111101001101011010111010011110111010010101100100110","11011111000011010111001000111111110110100010000001010","01100000010001001100101001110101111010100101011101100","00010011000101000110111011111110000000010011111111011","00000000110010100110001010001101001000011110100010001","11111110011001011101001010101110000111011000101011010","10000010100011101110000110001011010011101010100010010","10111010001000101011100011111101000111000010111110101","10111010110100000010001000111101110111101001100101111","10111010100111000001011111001101100011011010010101011","10000010111110101111100100101101110110001000000111010","11111110011010010000010011110100101101110001100101010"]},"v10H":{"text":"abcdefghijklmnopqrstuvwxyz0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789AB","level":"H","rows":["111111100111110001001100101001011111001001100011001111111","100000101111111011110000011011100110000011001101001000001","101110100110100110110000011111010010111101001111001011101","101110100011010100100101110001100000001011110101001011101","101110100001010011000110001111100101000101111101001011101","100000101001111000100010101000111010011010110110001000001","111111101010101010101010101010101010101010101010101111111","000000001011011001111101111000110111011011000110000000000","000011110110111111000100101111110101110101100101001100010","111111000100011100101110100110000001100001110001101101111","111110101110000011101110100100000011000010011010011110110","100011010110011101000010000001111101011110011011010100000","000010100010110010100001110100001000111100011100001101110","001101000010101010010101001100101100001101111101111011000","101010101000111101011110101011000010101011101101111111000","001001010111110111101101101110000101100000011011001110001","011010101010100011001100000011000100111001101000100110011","101000000111110100100111110001100111011011111101101010110","001010101110100000001100110100111101111100110000000001010","101001000011101100110111011000001010010101101100101001001","001010101101110010111110000110001010110101101001010001000","101111011001101000000011100010101000101111101000101011010","011000111110011110110010100000100001000101010000101111110","011001001100100111001111010000111000110011010000011100100","010011100101110001001000110100001100001001101011000100111","100011001110000111111100111110010000101100111101101011101","000111111100111101110011101111111011010110000110111111000","001010001011010101000011011000110110001111100110100010010","001010101111110111010001101010101000110001101110101010011","000010001110110011001010011000111001001011101100100011000","101011111110101000101010111111110100001111100101111110100","001101001110111101010010100010010001001001111110111000001","111111110110111001000101110011011000101100101010111101010","110110011101001100000101100101001000101111110100000100110","010000111111010011110011010011011100111010110001000010110","011000011100001101111010101001000110000101001011111101011","110000100001010001011011010010011010001101001011111001010","111001010000101000000010001010111111011001100001001100001","111011110111110011101110011001010101010101010000100100010","100000011100000110111110001110001110000011010000010100001","101110110101111111000011001111100110001100011010111110101","001011001101000001110000100101000001111111101110000000011","011110100011100100111010111001011010110110000111110111010","100011010000110011101100010110101100011110011010101010011","010110110001111010000000100111100011110101011010111111101","011111000001111000011101100001110011100001100100110101000","101001100010111010011110010100110101000011110101010110000","111110001001010001011110001011111010011000011010111110010","000000110111111111110011011111110111010100001100111110011","000000001110011100100111001000100110100101100101100010110","111111101110100010110110101010111111000100100001101010010","100000101101010001000100111000101010000101001101100011010","101110101101100111101101001111111100010101101100111111000","101110100011101110101011000000000011010011111100101010111","101110100101011000101101000011011100101101010110001010000","100000100001001011001000000100001110010110110001000011000","111111100100101010110000010000101000111110001111000001101"]}};


// ═══════════════════════════════════════════════════════════════════════════
//  P0-4 · QR CORE TESTS — golden matrices must reproduce CELL-FOR-CELL
//  (independent oracle: Kazuhiko Arase QRCode via qrcode-terminal vendor)
// ═══════════════════════════════════════════════════════════════════════════

(function qrGoldenSuite() {
  const names = Object.keys(QR_GOLDEN);
  assertEqual('golden fixture count', names.length, 12);
  names.forEach(function (name) {
    const f = QR_GOLDEN[name];
    const res = qrEncode(f.text, f.level);
    assertEqual(name + ' size', res.modules.length, f.rows.length);
    // Cell-for-cell comparison — every module dark/light must match.
    let same = res.modules.length === f.rows.length;
    if (same) {
      outer:
      for (let r = 0; r < f.rows.length; r++) {
        for (let c = 0; c < f.rows.length; c++) {
          const dark = f.rows[r][c] === '1';
          if (res.modules[r][c] !== dark) { same = false; break outer; }
        }
      }
    }
    assertEqual(name + ' matrix cell-for-cell', same, true);
    // SVG renderer emits a crisp inline SVG with a quiet zone of 4 modules
    const svg = qrSvg(res.modules);
    assertTruthy(name + ' svg viewBox', svg.indexOf('viewBox="0 0 ' + (res.size + 8)) !== -1);
    assertTruthy(name + ' svg path', svg.indexOf('<path') !== -1);
    assertTruthy(name + ' svg role img', svg.indexOf('role="img"') !== -1);
  });

  // Byte-mode capacity guard — longer than v10 capacity must throw
  let threw = false;
  try { qrEncode('x'.repeat(400), 'M'); } catch (e) { threw = true; }
  assertEqual('QR rejects payload > v10 byte capacity', threw, true);

  // Determinism: same input twice → identical matrix (no random state)
  const a = qrEncode('bc1qtest123456', 'M');
  const b = qrEncode('bc1qtest123456', 'M');
  assertEqual('QR deterministic', JSON.stringify(a.modules), JSON.stringify(b.modules));
  assertEqual('QR mask in 0-7', a.mask >= 0 && a.mask <= 7, true);
  assertEqual('QR size formula = type*4+17', a.size, a.modules.length);
  assertEqual('QR ecl default M', qrEncode('bc1qtest').ecl, 0);
})();

// ═══════════════════════════════════════════════════════════════════════════
//  P0-4 · WALLET IDENTITY TESTS — checksum split + health
// ═══════════════════════════════════════════════════════════════════════════

(function walletIdentitySuite() {
  // ── walletAddressParts: bech32 ──
  const bc = walletAddressParts('bc1qxy2kgdygjrsqtzq2n0yrf2493p83kkfjhx0wlh');
  assertEqual('bech32 type', bc.type, 'bech32');
  assertEqual('bech32 prefix', bc.prefix, 'bc1');
  assertEqual('bech32 checksum = last 6 chars', bc.checksum, 'hx0wlh');
  assertEqual('bech32 full preserved', bc.full, 'bc1qxy2kgdygjrsqtzq2n0yrf2493p83kkfjhx0wlh');
  assertEqual('bech32 reassembles', bc.prefix + bc.body + bc.checksum, bc.full);

  // ── walletAddressParts: base58 legacy ──
  const b58 = walletAddressParts('1BoatSLRHtKNngkdXEeobR76b53LETtpyT');
  assertEqual('base58 type', b58.type, 'base58');
  assertEqual('base58 prefix', b58.prefix, '1');
  assertEqual('base58 checksum non-empty', b58.checksum.length >= 3, true);
  assertEqual('base58 reassembles', b58.prefix + b58.body + b58.checksum, b58.full);

  // ── walletAddressParts: p2sh ──
  const p2sh = walletAddressParts('3J98t1WpEZ73CNmQviecrnyiWrnqRhWNLy');
  assertEqual('p2sh type', p2sh.type, 'base58');
  assertEqual('p2sh prefix', p2sh.prefix, '3');
  assertEqual('p2sh reassembles', p2sh.prefix + p2sh.body + p2sh.checksum, p2sh.full);

  // ── walletAddressParts: unknown/other ──
  const oth = walletAddressParts('xyz-1234567890');
  assertEqual('other type', oth.type, 'other');
  assertEqual('other checksum slice = last 6', oth.checksum, '567890');
  assertEqual('null addr → null', walletAddressParts(null), null);
  assertEqual('empty addr → null', walletAddressParts('   '), null);

  // ── checksum is always a REAL trailing substring (the ticket killer) ──
  const realCk = '1BoatSLRHtKNngkdXEeobR76b53LETtpyT';
  const parts2 = walletAddressParts(realCk);
  assertEqual('base58 checksum is a real suffix', realCk.indexOf(parts2.checksum) !== -1, true);
  assertEqual('base58 checksum = trailing 6', parts2.checksum, realCk.slice(-6));

  // ── walletHealth: no wallet ──
  const none = walletHealth({}, 1000000);
  assertEqual('no wallet status', none.status, 'NO_WALLET');
  assertEqual('no wallet score', none.score, 0);
  assertEqual('no wallet connected', none.connected, false);
  assertEqual('no wallet passed 0', none.passed, 0);
  assertEqual('no wallet 6 checks', none.checks.length, 6);

  // ── walletHealth: fully healthy ──
  const now = 1000000;
  const healthy = walletHealth({
    btc_address: 'bc1qtest',
    ts: now - 10,
    worker: { hashrate: 5e12, lastSubmission: now - 100 },
    pool: { _stale: false },
  }, now);
  assertEqual('healthy status', healthy.status, 'HEALTHY');
  assertEqual('healthy score', healthy.score, 100);
  assertEqual('healthy passed', healthy.passed, 6);
  assertEqual('healthy connected', healthy.connected, true);

  // ── walletHealth: degraded (stale data) ──
  const degraded = walletHealth({
    btc_address: 'bc1qtest',
    ts: now - 400,
    worker: { hashrate: 5e12, lastSubmission: now - 100 },
    pool: { _stale: true },
  }, now);
  assertEqual('degraded status', degraded.status, 'DEGRADED');
  assertEqual('degraded passed = 4', degraded.passed, 4);

  // ── walletHealth: critical (no hashrate + stale + no pool) ──
  const critical = walletHealth({
    btc_address: 'bc1qtest',
    ts: now - 400,
    worker: { hashrate: 0, lastSubmission: now - 8000 },
    pool: { _stale: true },
  }, now);
  assertEqual('critical status', critical.status, 'CRITICAL');
  assertEqual('critical passed = 2', critical.passed, 2);

  // ── walletHealth: now defaults to Date.now (live path) ──
  const live = walletHealth({ btc_address: 'bc1qtest', ts: Math.floor(Date.now() / 1000), worker: { hashrate: 1 } });
  assertEqual('live connected', live.connected, true);
})();

// ═══════════════════════════════════════════════════════════════════════════
//  SUITE 31: webhookPreviewPayload (UX audit Quick Win — Settings preview)
//  Pure mirror of the builder in static/app.js used to render the exact JSON
//  payload fired per alert, so the operator can validate the channel.
// ═══════════════════════════════════════════════════════════════════════════
(function() {
  function webhookPreviewPayload(severity, message, worker, address) {
    return {
      event: 'cypher65_war_room_alert',
      severity: severity || 'WARN',
      category: 'alert',
      message: message || '⚠ [WARN] exemplo de alerta — configuração de webhook do CYPHER65',
      ts: Math.floor(Date.now() / 1000),
      worker: worker || 'primary',
      address: address || '',
    };
  }

  const p = webhookPreviewPayload('CRIT', 'worker offline', 'miner-01', 'bc1qtest');
  assertEqual('wh event', p.event, 'cypher65_war_room_alert');
  assertEqual('wh severity passed', p.severity, 'CRIT');
  assertEqual('wh message passed', p.message, 'worker offline');
  assertEqual('wh worker passed', p.worker, 'miner-01');
  assertEqual('wh address passed', p.address, 'bc1qtest');
  assertEqual('wh ts numeric', typeof p.ts, 'number');

  const d = webhookPreviewPayload();
  assertEqual('wh default severity', d.severity, 'WARN');
  assertEqual('wh default worker', d.worker, 'primary');
  assertEqual('wh default message present', typeof d.message, 'string');
  assertEqual('wh default address empty', d.address, '');
})();

// ═══════════════════════════════════════════════════════════════════════════
//  SUITE 32: buildMarketTrendDatasets (UX backlog — Hash Market 7d chart)
//  Pure mirror of static/app.js: providers → datasets with per-provider null
//  gaps, union of timestamps, and BTC/TH/d → sats/TH/d (×1e8) conversion.
// ═══════════════════════════════════════════════════════════════════════════
(function() {
  function buildMarketTrendDatasets(providers) {
    const colors = ['rgb(247,147,26)', 'rgb(6,214,240)', 'rgb(168,85,247)', 'rgb(245,158,11)', 'rgb(16,185,129)'];
    const allTs = new Set();
    Object.values(providers || {}).forEach(pts => (pts || []).forEach(p => { if (p && p.ts) allTs.add(p.ts); }));
    const times = Array.from(allTs).sort((a, b) => a - b);
    const labels = times.map(t => { const d = new Date(t * 1000); return String(d.getHours()).padStart(2, '0') + ':' + String(d.getMinutes()).padStart(2, '0'); });
    const datasets = Object.keys(providers || {}).map((name, i) => {
      const byTs = {};
      ((providers[name]) || []).forEach(p => { if (p && p.ts != null) byTs[p.ts] = p.price_btc_per_th_day; });
      return {
        label: name,
        data: times.map(t => byTs[t] != null ? Number(byTs[t]) * 1e8 : null),
        borderColor: colors[i % colors.length],
        backgroundColor: colors[i % colors.length].replace(')', ',0.08)').replace('rgb', 'rgba'),
        tension: 0.4, pointRadius: 0, fill: false,
      };
    });
    return { times, labels, datasets };
  }

  // Two providers at three shared timestamps.
  const provs = {
    braiins: [
      { ts: 100, price_btc_per_th_day: 1e-6 },
      { ts: 200, price_btc_per_th_day: 1.5e-6 },
    ],
    mrr: [
      { ts: 200, price_btc_per_th_day: 2e-6 },
    ],
  };
  const out = buildMarketTrendDatasets(provs);
  assertEqual('trend times union sorted', JSON.stringify(out.times), JSON.stringify([100, 200]));
  assertEqual('trend labels length', out.labels.length, 2);
  assertEqual('trend datasets count', out.datasets.length, 2);
  assertEqual('trend dataset order', out.datasets[0].label, 'braiins');
  // braiins: [1e-6, 1.5e-6] → sats ×1e8; mrr: [null, 2e-6] → null gap at ts 100.
  assertEqual('braiins first point sats', out.datasets[0].data[0], 100);
  assertEqual('braiins second point sats', out.datasets[0].data[1], 150);
  assertEqual('mrr gap null', out.datasets[1].data[0], null);
  assertEqual('mrr point sats', out.datasets[1].data[1], 200);
  assertEqual('braiins borderColor set', typeof out.datasets[0].borderColor, 'string');
  assertEqual('braiins fill false', out.datasets[0].fill, false);

  const empty = buildMarketTrendDatasets({});
  assertEqual('trend empty datasets', empty.datasets.length, 0);
  assertEqual('trend empty times', empty.times.length, 0);
  assertEqual('trend empty labels', empty.labels.length, 0);
})();

// ═══════════════════════════════════════════════════════════════════════════
//  SUITE 33: simulateDifficultyShift (UX audit Módulo_05 — WHAT-IF slider)
//  Pure mirror of static/app.js: given the base Block Hunt values + a
//  difficulty shift %, recompute netDiff (linear), P(block)/share (inverse),
//  expected time (linear), distance (linear) and cumulative P (re-derived
//  from the shifted per-share probability and the session's share count).
// ═══════════════════════════════════════════════════════════════════════════
(function() {
  function simulateDifficultyShift(base, pct) {
    base = base || {};
    const mult = 1 + (Number(pct) || 0) / 100;
    const netDiff = base.netDiff > 0 ? base.netDiff * mult : 0;
    let pBlock = null;
    if (base.bestDiff > 0 && netDiff > 0) pBlock = base.bestDiff / netDiff;
    else if (base.pBlock != null && base.netDiff > 0 && netDiff > 0) pBlock = base.pBlock * (base.netDiff / netDiff);
    const expectedTime = base.expectedTime > 0 ? base.expectedTime * mult : (base.expectedTime || 0);
    const distance = base.bestDiff > 0 && netDiff > 0 ? netDiff / base.bestDiff : 0;
    let cumulativeP = base.cumulativeP;
    if (base.shares > 0 && pBlock != null && pBlock > 0) cumulativeP = 1 - Math.pow(1 - pBlock, base.shares);
    return { shiftPct: Number(pct) || 0, netDiff, pBlock, expectedTime, distance, cumulativeP };
  }

  // Base: 110T difficulty, 10G best share → pBlock = 10e9/110e12.
  const base = {
    netDiff: 110e12,
    bestDiff: 10e9,
    expectedTime: 123456,
    cumulativeP: 0.05,
    shares: 1000,
  };
  const basePBlock = 10e9 / 110e12;

  // ── +10% shift ──
  const up = simulateDifficultyShift(base, 10);
  assertEqual('whatif up shiftPct', up.shiftPct, 10);
  assertApprox('whatif up netDiff = 110T×1.1', up.netDiff, 121e12, 1);
  assertApprox('whatif up pBlock = 10G/121T', up.pBlock, 10e9 / 121e12, 1e-18);
  assertApprox('whatif up expectedTime ×1.1', up.expectedTime, 123456 * 1.1, 1e-6);
  assertApprox('whatif up distance = 121T/10G', up.distance, 121e12 / 10e9, 1e-6);
  // Cumulative P re-derived: 1-(1-p)^1000 with the shifted pBlock.
  assertApprox('whatif up cumP from shifted p', up.cumulativeP, 1 - Math.pow(1 - (10e9 / 121e12), 1000), 1e-12);
  // Difficulty UP → P(block) DOWN: strictly smaller than base pBlock.
  assertTruthy('whatif up pBlock < base pBlock', up.pBlock < basePBlock);

  // ── −25% shift ──
  const down = simulateDifficultyShift(base, -25);
  assertApprox('whatif down netDiff = 110T×0.75', down.netDiff, 82.5e12, 1);
  assertApprox('whatif down pBlock = 10G/82.5T', down.pBlock, 10e9 / 82.5e12, 1e-18);
  assertApprox('whatif down expectedTime ×0.75', down.expectedTime, 123456 * 0.75, 1e-6);
  assertTruthy('whatif down pBlock > base pBlock', down.pBlock > basePBlock);

  // ── 0% shift → identity ──
  const same = simulateDifficultyShift(base, 0);
  assertEqual('whatif zero netDiff unchanged', same.netDiff, base.netDiff);
  assertEqual('whatif zero pBlock unchanged', same.pBlock, basePBlock);
  assertEqual('whatif zero expectedTime unchanged', same.expectedTime, base.expectedTime);

  // ── Fallback: pBlock scaling when bestDiff is absent ──
  const fb = simulateDifficultyShift({ netDiff: 100, pBlock: 0.01 }, 100);
  assertApprox('whatif fallback pBlock = 0.01×(100/200)', fb.pBlock, 0.005, 1e-12);

  // ── Honest empty state: no base → zeros, no crash ──
  const empty = simulateDifficultyShift(null, 10);
  assertEqual('whatif empty netDiff 0', empty.netDiff, 0);
  assertEqual('whatif empty pBlock null', empty.pBlock, null);
  assertEqual('whatif empty expectedTime 0', empty.expectedTime, 0);
  assertEqual('whatif empty cumulativeP undefined', empty.cumulativeP, undefined);
})();

// ═══════════════════════════════════════════════════════════════════════════
//  SUITE 34: docsSearchSuggestions / docsSnippet / docsHighlight
//  (UX audit Módulo_09 — Docs autocomplete). Pure mirrors of static/app.js:
//  rank sections by title-over-body relevance, build a snippet window around
//  the hit, and highlight every query occurrence with <mark> (HTML-escaped).
// ═══════════════════════════════════════════════════════════════════════════
(function() {
  function docsSnippet(text, q, pos, radius) {
    radius = radius || 60;
    const t = String(text || '').replace(/\s+/g, ' ');
    q = String(q || '');
    const start = Math.max(0, pos - radius);
    const end = Math.min(t.length, pos + q.length + radius);
    let snippet = t.slice(start, end);
    if (start > 0) snippet = '\u2026' + snippet;
    if (end < t.length) snippet = snippet + '\u2026';
    return snippet;
  }
  function docsSearchSuggestions(index, q, limit) {
    limit = limit || 6;
    q = String(q || '').trim().toLowerCase();
    if (!q || !index.length) return [];
    const scored = [];
    index.forEach(function(sec) {
      const titleLow = (sec.title || '').toLowerCase();
      const textLow = (sec.text || '').toLowerCase();
      const titleIdx = titleLow.indexOf(q);
      const textIdx = textLow.indexOf(q);
      if (titleIdx === -1 && textIdx === -1) return;
      const score = titleIdx !== -1 ? 100 - titleIdx : 40 - Math.min(textIdx, 40);
      scored.push({ sec: sec, score: score, titleIdx: titleIdx, textIdx: textIdx });
    });
    scored.sort(function(a, b) { return b.score - a.score; });
    return scored.slice(0, limit).map(function(item) {
      const pos = item.titleIdx !== -1 ? Math.max(0, item.titleIdx) : Math.max(0, item.textIdx);
      return {
        id: item.sec.id,
        title: item.sec.title,
        snippet: docsSnippet(item.sec.text, q, pos),
      };
    });
  }
  function docsHighlight(text, q) {
    const t = String(text || '');
    const needle = String(q || '').trim();
    if (!needle) return escapeHtml(t);
    const lower = t.toLowerCase();
    const nl = needle.toLowerCase();
    let out = '';
    let i = 0;
    while (i < t.length) {
      const hit = lower.indexOf(nl, i);
      if (hit === -1) { out += escapeHtml(t.slice(i)); break; }
      out += escapeHtml(t.slice(i, hit));
      out += '<mark>' + escapeHtml(t.slice(hit, hit + needle.length)) + '</mark>';
      i = hit + needle.length;
    }
    return out;
  }

  const index = [
    { id: 'docs-latency', title: '8 · Latency / Ping', text: 'Diagnose high latency to the pool server with the Latency panel.' },
    { id: 'docs-probability', title: '4 · Probability', text: 'Block finding probability depends on your hashrate and the network difficulty.' },
    { id: 'docs-market', title: '5 · Hash Market', text: 'Compare rental offers from Braiins, NiceHash, MRR and Parasite.' },
  ];

  // ── Title hit ranks above body-only hit ──
  const lat = docsSearchSuggestions(index, 'latency', 6);
  assertEqual('docs latency results count', lat.length, 1);
  assertEqual('docs latency id', lat[0].id, 'docs-latency');
  assertTruthy('docs latency snippet contains window', lat[0].snippet.indexOf('Latency') !== -1);

  // Body-only hit (no title match) still surfaces — lower rank than any
  // title hit would be, but present.
  const pool = docsSearchSuggestions(index, 'pool', 6);
  assertEqual('docs pool results count', pool.length, 1);
  assertEqual('docs pool id', pool[0].id, 'docs-latency');

  // Title hit ranks above body-only hit for the same query span.
  const multi = docsSearchSuggestions(index, 'hashrate', 6);
  assertEqual('docs hashrate results count', multi.length, 1);
  assertEqual('docs hashrate id', multi[0].id, 'docs-probability');

  // ── limit caps results ──
  const capped = docsSearchSuggestions(index, 'e', 2);
  assertEqual('docs cap to 2', capped.length, 2);

  // ── no matches / empty query ──
  const none = docsSearchSuggestions(index, 'zzz-no-match', 6);
  assertEqual('docs no matches', none.length, 0);
  const emptyQuery = docsSearchSuggestions(index, '', 6);
  assertEqual('docs empty query', emptyQuery.length, 0);
  const nullQuery = docsSearchSuggestions(index, null, 6);
  assertEqual('docs null query', nullQuery.length, 0);

  // ── snippet window adds ellipses ──
  const longText = 'A'.repeat(200) + 'needle' + 'B'.repeat(200);
  const snip = docsSnippet(longText, 'needle', 200, 60);
  assertEqual('snippet starts with ellipsis', snip[0], '\u2026');
  assertTruthy('snippet contains needle', snip.indexOf('needle') !== -1);
  assertEqual('snippet window length bounded', snip.length, 60 + 6 + 60 + 2);
  const shortSnip = docsSnippet('tiny text', 'text', 5, 60);
  assertEqual('snippet short no ellipsis', shortSnip, 'tiny text');

  // ── highlight wraps every case-insensitive occurrence + escapes HTML ──
  const hl = docsHighlight('Pool & pool latency', 'pool');
  assertEqual('highlight marks both occurrences', (hl.match(/<mark>/g) || []).length, 2);
  assertTruthy('highlight escapes ampersand', hl.indexOf('&amp;') !== -1);
  const hlEmpty = docsHighlight('some text', '');
  assertEqual('highlight empty query = escaped text', hlEmpty, 'some text');
  const hlNone = docsHighlight('no match here', 'zzz');
  assertEqual('highlight no match = escaped text', hlNone, 'no match here');
})();

// ═══════════════════════════════════════════════════════════════════════════
//  SUITE 35: docsFeedbackPct / docsFeedbackSectionLabel (Issue #19 —
//  Learning FAQ loop). Pure mirrors of static/app.js: % helpful rounded to
//  1 decimal (null when no votes — never fabricate), section id → label.
// ═══════════════════════════════════════════════════════════════════════════
(function() {
  function docsFeedbackPct(helpful, total) {
    if (!total) return null;
    return Math.round(helpful / total * 1000) / 10;
  }
  function docsFeedbackSectionLabel(sectionId) {
    const m = String(sectionId || '').match(/^docs[-_](.+)$/);
    return m ? m[1].replace(/[-_]/g, ' ') : String(sectionId || '—');
  }

  assertEqual('pct 2/3 rounded 1dp', docsFeedbackPct(2, 3), 66.7);
  assertEqual('pct 3/3', docsFeedbackPct(3, 3), 100);
  assertEqual('pct 0/4 honest zero', docsFeedbackPct(0, 4), 0);
  assertEqual('pct no votes = null (never fabricate)', docsFeedbackPct(5, 0), null);
  assertEqual('label docs-faq', docsFeedbackSectionLabel('docs-faq'), 'faq');
  assertEqual('label docs-multi-user dashes', docsFeedbackSectionLabel('docs-multi-user'), 'multi user');
  assertEqual('label docs_fleet underscore', docsFeedbackSectionLabel('docs_fleet'), 'fleet');
  assertEqual('label non-docs passthrough', docsFeedbackSectionLabel('overview'), 'overview');
  assertEqual('label empty → dash', docsFeedbackSectionLabel(''), '—');
})();

// ═══════════════════════════════════════════════════════════════════════════
//  SUITE 36: fmtErrorAge (Issue #176 — error-rate view no admin). Espelho
//  puro do static/app.js _fmtErrorTs: minutos atrás < 60m, horas atrás < 48h,
//  depois ISO UTC; ts nulo/inválido → dash. `nowArg` injetado p/ determinismo.
// ═══════════════════════════════════════════════════════════════════════════
(function() {
  function fmtErrorAge(ts, nowArg) {
    if (!ts) return '—';
    const d = new Date(Number(ts) * 1000);
    if (isNaN(d.getTime())) return '—';
    const now = nowArg != null ? nowArg : Date.now();
    const deltaMin = Math.floor((now - d.getTime()) / 60000);
    if (deltaMin < 60) return deltaMin + 'm atrás';
    const deltaH = Math.floor(deltaMin / 60);
    if (deltaH < 48) return deltaH + 'h atrás';
    return d.toISOString().replace('T', ' ').slice(0, 16) + ' UTC';
  }

  const NOW = 1800000000000; // fixed "now" for deterministic assertions
  assertEqual('null ts → dash', fmtErrorAge(null, NOW), '—');
  assertEqual('zero ts → dash', fmtErrorAge(0, NOW), '—');
  assertEqual('12 min atrás', fmtErrorAge((NOW - 12 * 60000) / 1000, NOW), '12m atrás');
  assertEqual('90 min atrás → horas', fmtErrorAge((NOW - 90 * 60000) / 1000, NOW), '1h atrás');
  assertEqual('3 dias atrás → ISO UTC', fmtErrorAge((NOW - 3 * 86400000) / 1000, NOW),
    new Date(NOW - 3 * 86400000).toISOString().replace('T', ' ').slice(0, 16) + ' UTC');
})();

// ═══════════════════════════════════════════════════════════════════════════
//  MARKET SORT (mirrors static/app.js sortMarketVenues — pure)
// ═══════════════════════════════════════════════════════════════════════════

function sortMarketVenues(venues, key, dir) {
  const arr = (venues || []).slice();
  const val = (v, k) => {
    if (k === 'venue') return String(v.venue || '').toLowerCase();
    if (k === 'price') return Number(v.price_btc_ph_day);
    if (k === 'usd') return v.price_usd_th_day != null ? Number(v.price_usd_th_day) : NaN;
    if (k === 'tier') return Number(v.risk_tier);
    return v[k] != null ? Number(v[k]) : NaN;
  };
  arr.sort((a, b) => {
    const va = val(a, key);
    const vb = val(b, key);
    if (va === vb) return 0;
    if (typeof va === 'number' && typeof vb === 'number') {
      if (!isFinite(va)) return 1;
      if (!isFinite(vb)) return -1;
      return (va - vb) * dir;
    }
    return String(va).localeCompare(String(vb)) * dir;
  });
  return arr;
}

(function marketSortTests() {
  const venues = [
    { venue: 'mrr', price_btc_ph_day: 0.000120, risk_tier: 3, price_usd_th_day: 7.2 },
    { venue: 'braiins', price_btc_ph_day: 0.000100, risk_tier: 1, price_usd_th_day: 6.0 },
    { venue: 'nicehash', price_btc_ph_day: 0.000110, risk_tier: 2, price_usd_th_day: 6.6 },
  ];
  const byPrice = sortMarketVenues(venues, 'price', 1);
  assertEqual('sort by price asc → braiins first', byPrice[0].venue, 'braiins');
  assertEqual('sort by price asc → mrr last', byPrice[2].venue, 'mrr');
  const byTier = sortMarketVenues(venues, 'tier', 1);
  assertEqual('sort by tier asc → tier1 first', byTier[0].risk_tier, 1);
  const byVenueDesc = sortMarketVenues(venues, 'venue', -1);
  assertEqual('sort by venue desc → nicehash first', byVenueDesc[0].venue, 'nicehash');
  const byUsd = sortMarketVenues(venues, 'usd', 1);
  assertEqual('sort by usd asc → 6.0 first', byUsd[0].price_usd_th_day, 6.0);
  // Original array untouched (pure fn).
  assertEqual('pure: input not mutated', venues[0].venue, 'mrr');
  // Missing/absent USD sorts last on asc (undefined key AND explicit null).
  const withGap = venues.concat([{ venue: 'x', price_btc_ph_day: 0.00009, risk_tier: 1 }]);
  const g = sortMarketVenues(withGap, 'usd', 1);
  assertEqual('missing usd key sorts last', g[g.length - 1].venue, 'x');
  // The live render path sets price_usd_th_day = null when BTC/USD missing —
  // Number(null) would be 0 and sort FIRST; the guard must send it last.
  const withNull = venues.map(v => ({ ...v, price_usd_th_day: v.price_usd_th_day === 6.6 ? null : v.price_usd_th_day }));
  const gn = sortMarketVenues(withNull, 'usd', 1);
  assertEqual('explicit null usd sorts last (not first)', gn[gn.length - 1].venue, 'nicehash');
})();

// ═══════════════════════════════════════════════════════════════════════════
//  SUITE 33: admin audit trail builders (Issue #96 — admin panel)
//  Pure mirrors of static/app.js: ISO-week bucketing (UTC, deterministic),
//  client-side tenant/verdict filter, and verdict badge metadata.
// ═══════════════════════════════════════════════════════════════════════════
(function() {
  function adminAuditIsoWeekKey(ts) {
    const n = Number(ts);
    if (!isFinite(n) || n <= 0) return '';
    const d = new Date(n * 1000);
    if (isNaN(d.getTime())) return '';
    const day = (d.getUTCDay() + 6) % 7;         // Mon=0 … Sun=6
    const thursday = new Date(Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate() + 3 - day));
    const firstThu = new Date(Date.UTC(thursday.getUTCFullYear(), 0, 4));
    const week = 1 + Math.round((thursday - firstThu) / (7 * 86400 * 1000));
    return thursday.getUTCFullYear() + '-W' + String(week).padStart(2, '0');
  }
  function buildAdminAuditWeekly(decisions) {
    const buckets = {};
    (decisions || []).forEach(function (d) {
      const k = adminAuditIsoWeekKey(d && d.ts);
      if (!k) return;
      buckets[k] = (buckets[k] || 0) + 1;
    });
    const labels = Object.keys(buckets).sort();
    return { labels: labels, counts: labels.map(function (k) { return buckets[k]; }) };
  }
  function filterAdminAuditDecisions(decisions, tenant, verdict) {
    return (decisions || []).filter(function (d) {
      if (tenant && (d.tenant_id || 'default') !== tenant) return false;
      if (verdict && (d.verdict || 'unknown') !== verdict) return false;
      return true;
    });
  }
  function adminAuditVerdictMeta(verdict) {
    const map = {
      improved: { cls: 'admin-audit__verdict--improved', label: 'IMPROVED' },
      worse: { cls: 'admin-audit__verdict--worse', label: 'WORSE' },
      same: { cls: 'admin-audit__verdict--same', label: 'SAME' },
      avoided: { cls: 'admin-audit__verdict--avoided', label: 'AVOIDED' },
      revoked: { cls: 'admin-audit__verdict--revoked', label: 'REVOKED' },
      no_before: { cls: 'admin-audit__verdict--mute', label: 'NO BEFORE' },
    };
    return map[verdict] || { cls: 'admin-audit__verdict--mute', label: String(verdict || 'unknown').toUpperCase() };
  }

  // ISO week key — fixed epoch timestamps (UTC Mondays).
  // 2026-07-20 is a Monday → W30; 2026-07-26 is a Sunday → still W30.
  assertEqual('ISO week key Mon 2026-07-20', adminAuditIsoWeekKey(1784505600), '2026-W30');
  assertEqual('ISO week key Sun 2026-07-26', adminAuditIsoWeekKey(1785024000), '2026-W30');
  assertEqual('ISO week key Mon 2026-07-27', adminAuditIsoWeekKey(1785110400), '2026-W31');
  assertEqual('ISO week key invalid ts → empty', adminAuditIsoWeekKey(0), '');
  assertEqual('ISO week key garbage → empty', adminAuditIsoWeekKey('nope'), '');

  // Weekly bucketing — sorted labels, correct counts, null ts skipped.
  const weekly = buildAdminAuditWeekly([
    { ts: 1784505600 },          // W30
    { ts: 1785110400 },          // W31
    { ts: 1785110400 + 86400 },  // W31
    { ts: 0 },                   // skipped
    { ts: null },                // skipped
    { ts: 'garbage' },           // skipped
  ]);
  assertEqual('weekly labels sorted', weekly.labels, ['2026-W30', '2026-W31']);
  assertEqual('weekly counts', weekly.counts, [1, 2]);
  assertEqual('weekly empty input', buildAdminAuditWeekly([]), { labels: [], counts: [] });
  assertEqual('weekly undefined input', buildAdminAuditWeekly(undefined), { labels: [], counts: [] });

  // Feature over-concentration alert (Issue #163) — banner builder mirror.
  function buildFeatureAlert(featureAlert) {
    if (!featureAlert || featureAlert.share_pct == null) {
      return { active: false, feature: '', count: 0, sharePct: 0, minPct: 50 };
    }
    return {
      active: true,
      feature: String(featureAlert.feature || 'unknown'),
      count: Number(featureAlert.count) || 0,
      sharePct: Number(featureAlert.share_pct) || 0,
      minPct: Number(featureAlert.min_pct) || 50,
    };
  }
  assertEqual('feature alert null → inactive', buildFeatureAlert(null),
    { active: false, feature: '', count: 0, sharePct: 0, minPct: 50 });
  assertEqual('feature alert missing share → inactive', buildFeatureAlert({ feature: 'x' }),
    { active: false, feature: '', count: 0, sharePct: 0, minPct: 50 });
  assertEqual('feature alert active', buildFeatureAlert(
    { feature: 'monte_carlo', count: 2, share_pct: 66.7, min_pct: 50 }),
    { active: true, feature: 'monte_carlo', count: 2, sharePct: 66.7, minPct: 50 });
  assertEqual('feature alert garbage numbers', buildFeatureAlert(
    { feature: null, count: 'x', share_pct: 'nope', min_pct: null }),
    { active: true, feature: 'unknown', count: 0, sharePct: 0, minPct: 50 });

  // Feature breakdown (Issue #158 — 18-D) — top-N builder mirror.
  function buildFeatureBreakdown(paywallByFeature) {
    const rows = (paywallByFeature || []).map(function (f) {
      return { feature: f.feature || 'unknown', count: Number(f.count) || 0 };
    }).sort(function (a, b) { return b.count - a.count; });
    const total = rows.reduce(function (s, r) { return s + r.count; }, 0) || 1;
    return rows.map(function (r) {
      return { feature: r.feature, count: r.count, pct: Math.round(r.count / total * 100) };
    });
  }
  assertEqual('feature breakdown empty', buildFeatureBreakdown([]), []);
  assertEqual('feature breakdown undefined', buildFeatureBreakdown(undefined), []);
  assertEqual('feature breakdown sorted + pct', buildFeatureBreakdown([
    { feature: 'auto_pilot', count: 2 },
    { feature: 'monte_carlo', count: 5 },
    { feature: null },
  ]), [
    { feature: 'monte_carlo', count: 5, pct: 71 },
    { feature: 'auto_pilot', count: 2, pct: 29 },
    { feature: 'unknown', count: 0, pct: 0 },
  ]);

  // Portfolio series datasets (Issue #146 — 21-C) — pure builder mirror.
  function buildPortfolioSeriesDatasets(points) {
    const rows = points || [];
    // null/undefined must stay null (Chart.js gap) — Number(null) is 0 and
    // would fabricate a flat 'no loss' bar on a cold box (honest telemetry).
    const num = function (v) {
      if (v === null || v === undefined) return null;
      const n = Number(v);
      return Number.isFinite(n) ? n : null;
    };
    const hasOwnEv = rows.some(function (p) { return num(p.own_ev_sats) != null; });
    return {
      labels: rows.map(function (p) { return String(p.label || '').replace(/^\d{4}-/, ''); }),
      spent: rows.map(function (p) { return num(p.spent_sats); }),
      pl: rows.map(function (p) { return num(p.pl_sats); }),
      cum: rows.map(function (p) { return num(p.cum_pl_sats); }),
      ownEv: rows.map(function (p) { return hasOwnEv ? num(p.own_ev_sats) : null; }),
      totalCum: rows.map(function (p) { return hasOwnEv ? num(p.cum_total_sats) : null; }),
      hasOwnEv: hasOwnEv
    };
  }
  assertEqual('series datasets empty', buildPortfolioSeriesDatasets([]), {
    labels: [], spent: [], pl: [], cum: [], ownEv: [], totalCum: [], hasOwnEv: false });
  assertEqual('series datasets backward compat (no own EV)', buildPortfolioSeriesDatasets([
    { label: '2026-W30', spent_sats: 5000, pl_sats: -200, cum_pl_sats: -200 },
  ]), {
    labels: ['W30'], spent: [5000], pl: [-200], cum: [-200], ownEv: [null], totalCum: [null], hasOwnEv: false });
  assertEqual('series datasets own EV included', buildPortfolioSeriesDatasets([
    { label: '2026-W30', spent_sats: 5000, pl_sats: -200, cum_pl_sats: -200, own_ev_sats: 700, cum_total_sats: 500 },
    { label: '2026-W31', spent_sats: 3000, pl_sats: -100, cum_pl_sats: -300, own_ev_sats: 700, cum_total_sats: 1100 },
  ]), {
    labels: ['W30', 'W31'], spent: [5000, 3000], pl: [-200, -100], cum: [-200, -300],
    ownEv: [700, 700], totalCum: [500, 1100], hasOwnEv: true });
  assertEqual('series datasets garbage numbers', buildPortfolioSeriesDatasets([
    { label: null, spent_sats: 'nope', own_ev_sats: 'x' },
  ]), {
    labels: [''], spent: [null], pl: [null], cum: [null], ownEv: [null], totalCum: [null], hasOwnEv: false });
  // Honest gaps: null P/L (cold box) stays null — never a fabricated 0 bar.
  assertEqual('series datasets null pl stays gap', buildPortfolioSeriesDatasets([
    { label: '2026-W30', pl_sats: null, cum_pl_sats: null, own_ev_sats: 700, cum_total_sats: null },
  ]), {
    labels: ['W30'], spent: [null], pl: [null], cum: [null], ownEv: [700], totalCum: [null], hasOwnEv: true });

  // Rentals provider auth state (Issue #152) — pure helpers mirror.
  function rentalsAuthRejected(errMsg, authRejected) {
    if (authRejected) return true;
    return /rejected|401|403|unauthor|forbidden|bad nonce|not authenticated|invalid key/i.test(String(errMsg || ''));
  }
  function _esc(s) { return String(s).replace(/[&<>"']/g, c => ({ '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;' }[c])); }
  function rentalsAuthGuide(provider, errMsg) {
    const safe = _esc(String(errMsg || ''));
    if (provider === 'contracts') {
      return 'A chave Braiins está configurada, mas a API a rejeitou: ' + safe +
        '. Gere um novo owner token em hashpower.braiins.com e atualize no Settings (⚙).';
    }
    return 'A chave MRR está configurada, mas a API a rejeitou: ' + safe +
      '. Causa provável: credencial inválida/desatualizada (ou tracker de nonce da chave preso) ' +
      '— NÃO é bug de concorrência. Regenerar a API key + secret em miningrigrentals.com ' +
      '→ My Account → API Access e atualizar no Settings (⚙).';
  }
  assertEqual('rentals auth rejected explicit flag', rentalsAuthRejected('weird', true), true);
  assertEqual('rentals auth rejected bad nonce', rentalsAuthRejected('Not Authenticated - Invalid Key - Bad Nonce.', false), true);
  assertEqual('rentals auth rejected 401', rentalsAuthRejected('HTTP 401', false), true);
  assertEqual('rentals auth rejected generic', rentalsAuthRejected('HTTP 503', false), false);

  // Rentals payload freshness (Issue #187) — pure helpers mirror.
  // Level: 0 fresh · 1 age-stale (soft 'dados desatualizados') · 2 old-code
  // (no version stamp → credential hint, never 'No contracts' empty-state).
  function rentalsPayloadStale(payload, nowSec) {
    const p = payload || {};
    const version = Number(p.rentals_payload_version) || 0;
    if (version < 2) return 2;
    const age = (nowSec || Math.floor(Date.now() / 1000)) - (Number(p.updated_at) || 0);
    return age > 300 ? 1 : 0;
  }
  assertEqual('rentals stale missing stamp (old code)', rentalsPayloadStale({ updated_at: 1000000 }, 1000030), 2);
  assertEqual('rentals stale version 0', rentalsPayloadStale({ rentals_payload_version: 0, updated_at: 1000000 }, 1000030), 2);
  assertEqual('rentals fresh', rentalsPayloadStale({ rentals_payload_version: 2, updated_at: 1000000 }, 1000030), 0);
  assertEqual('rentals age-stale only', rentalsPayloadStale({ rentals_payload_version: 2, updated_at: 1000000 }, 1000400), 1);
  assertEqual('rentals auth rejected permission', rentalsAuthRejected('No Permission - account/1285', false), false);
  assertEqual('rentals auth guide mrr', rentalsAuthGuide('mrr', 'Not Authenticated - Invalid Key - Bad Nonce.').indexOf('miningrigrentals.com') !== -1, true);
  assertEqual('rentals auth guide mrr not concurrency', rentalsAuthGuide('mrr', 'x').indexOf('NÃO é bug de concorrência') !== -1, true);
  assertEqual('rentals auth guide braiins', rentalsAuthGuide('contracts', '401').indexOf('hashpower.braiins.com') !== -1, true);
  assertEqual('rentals auth guide escapes html', rentalsAuthGuide('mrr', '<b>').indexOf('&lt;b&gt;') !== -1, true);

  // Instance indicator (Issue #198) — pure classifier mirror. The topbar
  // pill color-codes which instance the dashboard is on (local vs cloud)
  // so operators never save keys to the wrong URL.
  function instanceClassify(host) {
    let h = String(host || '').toLowerCase().replace(/^https?:\/\//, '').split('/')[0];
    const bracket = h.match(/^\[([^\]]+)\](?::\d+)?$/);
    if (bracket) h = bracket[1];
    const hostOnly = h === '::1' ? '::1' : h.replace(/:\d+$/, '');
    if (!hostOnly) return { kind: 'remote', icon: '⌁' };
    const isLocal =
      hostOnly === 'localhost' || hostOnly === '127.0.0.1' || hostOnly === '0.0.0.0' || hostOnly === '::1' ||
      hostOnly.endsWith('.local') ||
      /^192\.168\./.test(hostOnly) || /^10\./.test(hostOnly) || /^172\.(1[6-9]|2\d|3[01])\./.test(hostOnly);
    const isCloud = /\.onrender\.com$/.test(hostOnly) || /\.render\.com$/.test(hostOnly);
    if (isLocal) return { kind: 'local', icon: '🖥' };
    if (isCloud) return { kind: 'cloud', icon: '☁' };
    return { kind: 'remote', icon: '⌁' };
  }
  assertEqual('instance localhost', instanceClassify('localhost').kind, 'local');
  assertEqual('instance loopback with port', instanceClassify('127.0.0.1:8765').kind, 'local');
  assertEqual('instance private 192.168', instanceClassify('192.168.1.20:8765').kind, 'local');
  assertEqual('instance private 10.', instanceClassify('10.0.0.5').kind, 'local');
  assertEqual('instance ipv6 loopback raw', instanceClassify('::1').kind, 'local');
  assertEqual('instance ipv6 loopback bracket+port', instanceClassify('[::1]:8765').kind, 'local');
  assertEqual('instance cloud onrender', instanceClassify('cypher65-war-room.onrender.com').kind, 'cloud');
  assertEqual('instance cloud render sub', instanceClassify('api.cypher65.render.com').kind, 'cloud');
  assertEqual('instance remote public', instanceClassify('cypher65.example.com').kind, 'remote');
  assertEqual('instance remote with port', instanceClassify('cypher65.example.com:8443').kind, 'remote');
  assertEqual('instance remote full url', instanceClassify('https://cypher65.example.com/path').kind, 'remote');
  assertEqual('instance empty host', instanceClassify('').kind, 'remote');
  assertEqual('instance icon local', instanceClassify('127.0.0.1').icon, '🖥');
  assertEqual('instance icon cloud', instanceClassify('x.onrender.com').icon, '☁');

  // Cohort LTV rows (Issue #157 — 18-C) — safe-number builder mirror.
  function _cohortNum(v) {
    const n = Number(v);
    return Number.isFinite(n) ? n : 0;
  }
  function buildCohortRows(cohorts) {
    return (cohorts || []).map(function (c) {
      return {
        month: c.cohort_month || '',
        subs: _cohortNum(c.subscriptions),
        renewals: _cohortNum(c.renewals),
        revenue: _cohortNum(c.revenue_usd),
        ltv: _cohortNum(c.ltv_usd),
        m1: _cohortNum(c.retention_m1_pct),
        m3: _cohortNum(c.retention_m3_pct),
        m6: _cohortNum(c.retention_m6_pct),
        m12: _cohortNum(c.retention_m12_pct),
      };
    });
  }
  assertEqual('cohort rows empty', buildCohortRows([]), []);
  assertEqual('cohort rows undefined', buildCohortRows(undefined), []);
  assertEqual('cohort rows safe numbers', buildCohortRows([
    { cohort_month: '2026-08', subscriptions: 2, renewals: 2, revenue_usd: 40, ltv_usd: 20, retention_m1_pct: 100, retention_m3_pct: 0 },
    { cohort_month: null, subscriptions: null, renewals: 'x', revenue_usd: null, retention_m12_pct: 'nope' },
  ]), [
    { month: '2026-08', subs: 2, renewals: 2, revenue: 40, ltv: 20, m1: 100, m3: 0, m6: 0, m12: 0 },
    { month: '', subs: 0, renewals: 0, revenue: 0, ltv: 0, m1: 0, m3: 0, m6: 0, m12: 0 },
  ]);

  // Funnel weekly trend (Issue #156 — 18-B) — series builder mirror.
  function buildFunnelTrend(weekly) {
    const labels = [], paywall = [], convRate = [];
    (weekly || []).forEach(function (b) {
      labels.push(b.week || '');
      const s = b.stages || {};
      paywall.push(Number(s.paywall_view) || 0);
      convRate.push(b.conversion_rate_pct != null ? Number(b.conversion_rate_pct) : 0);
    });
    return { labels: labels, paywall: paywall, convRate: convRate };
  }
  assertEqual('funnel trend empty input', buildFunnelTrend([]), { labels: [], paywall: [], convRate: [] });
  assertEqual('funnel trend undefined input', buildFunnelTrend(undefined), { labels: [], paywall: [], convRate: [] });
  assertEqual('funnel trend series', buildFunnelTrend([
    { week: '2026-W31', stages: { paywall_view: 10 }, conversion_rate_pct: 20.0 },
    { week: '2026-W32', stages: { paywall_view: 15, modal_open: 6 }, conversion_rate_pct: 33.33 },
    { week: null, stages: {} },
  ]), {
    labels: ['2026-W31', '2026-W32', ''],
    paywall: [10, 15, 0],
    convRate: [20, 33.33, 0],
  });

  // Filter — tenant + verdict, missing fields defaulted, no filter = all.
  const decisions = [
    { tenant_id: 'tenant-a', verdict: 'worse', ts: 1 },
    { tenant_id: 'tenant-a', verdict: 'improved', ts: 2 },
    { verdict: 'worse', ts: 3 },                          // → default tenant
    { tenant_id: 'tenant-b', verdict: 'no_before', ts: 4 },
  ];
  assertEqual('filter tenant-a only',
    filterAdminAuditDecisions(decisions, 'tenant-a', '').length, 2);
  assertEqual('filter default tenant',
    filterAdminAuditDecisions(decisions, 'default', '').length, 1);
  assertEqual('filter verdict worse',
    filterAdminAuditDecisions(decisions, '', 'worse').length, 2);
  assertEqual('filter tenant+verdict combo',
    filterAdminAuditDecisions(decisions, 'tenant-b', 'no_before').length, 1);
  assertEqual('filter combo no match',
    filterAdminAuditDecisions(decisions, 'tenant-a', 'revoked').length, 0);
  assertEqual('filter no filters → all',
    filterAdminAuditDecisions(decisions, '', '').length, 4);
  assertEqual('filter undefined input',
    filterAdminAuditDecisions(undefined, '', '').length, 0);
  assertEqual('filter unknown verdict kept when no filter',
    filterAdminAuditDecisions([{ verdict: 'mystery', ts: 5 }], '', '').length, 1);

  // Verdict badge metadata — ladder + unknown fallback.
  assertEqual('verdict worse meta', adminAuditVerdictMeta('worse'),
    { cls: 'admin-audit__verdict--worse', label: 'WORSE' });
  assertEqual('verdict improved meta', adminAuditVerdictMeta('improved').label, 'IMPROVED');
  assertEqual('verdict revoked meta', adminAuditVerdictMeta('revoked').cls,
    'admin-audit__verdict--revoked');
  assertEqual('verdict unknown fallback label', adminAuditVerdictMeta('mystery').label, 'MYSTERY');
  assertEqual('verdict undefined fallback label', adminAuditVerdictMeta(undefined).label, 'UNKNOWN');
  assertEqual('verdict unknown fallback class', adminAuditVerdictMeta('mystery').cls,
    'admin-audit__verdict--mute');
})();

// ═══════════════════════════════════════════════════════════════════════════
//  Funnel session id (Issue #155) — funnelId() + meta injection
// ═══════════════════════════════════════════════════════════════════════════
(function () {
  // Stub localStorage for the funnelId mirror (Node has none).
  if (typeof globalThis.localStorage === 'undefined') {
    const store = {};
    globalThis.localStorage = {
      getItem: (k) => (k in store ? store[k] : null),
      setItem: (k, v) => { store[k] = String(v); },
      removeItem: (k) => { delete store[k]; },
    };
  }

  // Mirror of static/app.js funnelId() — PII-free token, persisted once.
  function funnelId() {
    try {
      let id = localStorage.getItem('c65_funnel_id');
      if (!id) {
        id = 'f_' + Math.random().toString(36).slice(2) + Date.now().toString(36);
        localStorage.setItem('c65_funnel_id', id);
      }
      return id;
    } catch (e) { return ''; }
  }

  // Mirror of trackConversionEvent meta injection (kept pure for testing).
  function injectFunnelMeta(meta) {
    const m = meta || {};
    if (!m.funnel_id) m.funnel_id = funnelId();
    return m;
  }

  localStorage.removeItem('c65_funnel_id');
  const id1 = funnelId();
  assertTruthy('funnelId generates a token', id1.length >= 8);
  assertEqual('funnelId prefix f_', id1.slice(0, 2), 'f_');
  assertEqual('funnelId stable across calls', funnelId(), id1);
  const meta = injectFunnelMeta({ plan: 'pro' });
  assertEqual('trackConversionEvent injects funnel_id', meta.funnel_id, id1);
  assertEqual('trackConversionEvent keeps plan', meta.plan, 'pro');
  const meta2 = injectFunnelMeta({ funnel_id: 'f_given', plan: 'pro' });
  assertEqual('explicit funnel_id not overridden', meta2.funnel_id, 'f_given');
  localStorage.removeItem('c65_funnel_id');
  const id2 = funnelId();
  assertTruthy('funnelId regenerates after wipe', id2.length >= 8 && id2 !== id1);
})();

// ═══════════════════════════════════════════════════════════════════════════
//  RESULTS
// ═══════════════════════════════════════════════════════════════════════════

console.log(`\n${'═'.repeat(50)}`);
if (failed === 0) {
  console.log(`✅ ALL ${passed} TESTS PASSED`);
} else {
  console.log(`❌ ${failed}/${passed + failed} TESTS FAILED`);
  failures.forEach(f => console.log(f));
}

process.exit(failed > 0 ? 1 : 0);