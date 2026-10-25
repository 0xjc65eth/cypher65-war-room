#!/usr/bin/env node
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const source = fs.readFileSync('static/src/45-market.js', 'utf8');
const start = source.indexOf('  function renderMarketGrid() {');
const end = source.indexOf('\n  // Wire the provider filter chips', start);
assert.ok(start >= 0 && end > start, 'market renderer is present');
const renderer = source.slice(start, end);
const elements = new Map([
  ['mkt-table-body', { textContent: '', dataset: {}, style: {}, className: '', innerHTML: '' }],
]);
const sandbox = {
  _mktInstitutional: {
    regime: 'Normal',
    market_intelligence: {
      status: 'PARTIAL',
      available_provider_count: 2,
      total_provider_count: 3,
      cache_age_seconds: 61,
      cache_age_source: 'braiins',
      rankings: {
        cheapest: 'mrr',
        best_score: 'mrr',
        freshest: 'nicehash',
        most_capacity: 'braiins',
      },
    },
    venues: [],
  },
  _mktBtcUsd: null,
  _mktFilter: 'all',
  _mktSort: { key: 'price', dir: 1 },
  _mktSnapTs: 1000,
  _mktOffers: [],
  document: {
    getElementById(id) {
      if (!elements.has(id)) elements.set(id, { textContent: '', dataset: {}, style: {}, className: '', innerHTML: '' });
      return elements.get(id);
    },
    querySelectorAll() { return []; },
  },
  window: {},
  setHtmlIfChanged(el, html) { el.innerHTML = html; },
  escapeHtml: String,
  fmt: { hashrate: String },
};
const renderMarketGrid = vm.runInNewContext(`(() => { ${renderer}; return renderMarketGrid; })()`, sandbox);
const _mktInstitutional = {
  regime: 'Normal',
  market_intelligence: {
    status: 'PARTIAL',
    available_provider_count: 2,
    total_provider_count: 3,
    cache_age_seconds: 61,
    rankings: {
      cheapest: 'mrr',
      best_score: 'mrr',
      freshest: 'nicehash',
      most_capacity: 'braiins',
    },
  },
  venues: [],
};
renderMarketGrid();
assert.equal(elements.get('mkt-provider-health').textContent, 'PARTIAL · 2/3 PROVIDERS');
assert.equal(elements.get('mkt-provider-health').dataset.status, 'partial');
assert.equal(elements.get('mkt-provider-rankings').textContent, 'CHEAPEST MRR · BEST SCORE MRR · FRESHEST NICEHASH · CAPACITY BRAIINS');
assert.equal(elements.get('mkt-provider-cache-age').textContent, 'CACHE AGE 1m · BRAIINS');
console.log('✅ market dashboard shows provider availability, ranks, and cache age');
