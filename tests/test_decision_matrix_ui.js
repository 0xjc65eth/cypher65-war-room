#!/usr/bin/env node
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const source = fs.readFileSync('static/src/41-automations.js', 'utf8');
const start = source.indexOf('  function renderDecisionMatrix(p) {');
const end = source.indexOf('\n  // P0-2: CTA — jump to the best offer', start);
assert.ok(start >= 0 && end > start, 'decision-matrix renderer is present');
const renderer = source.slice(start, end);
const elements = new Map();
const sandbox = {
  document: {
    getElementById(id) {
      if (!elements.has(id)) elements.set(id, { textContent: '', hidden: false, onclick: null });
      return elements.get(id);
    },
  },
  window: {},
  escapeHtml: (value) => String(value),
  _ic: () => '',
};
const renderDecisionMatrix = vm.runInNewContext(`(() => { ${renderer}; return renderDecisionMatrix; })()`, sandbox);
renderDecisionMatrix({
  decision_matrix: { rows: {}, breakeven_cost_per_th_day: null },
  economic_scenarios: {
    horizon: '24h',
    best_option: 'POOL',
    recommendation: 'Pool has the highest modeled net.',
    scenarios: {
      POOL: {
        modeled_net_usd_per_day: { value: null, status: 'NOT CONFIGURED' },
        direct_cost_usd_per_day: { value: null, status: 'NOT CONFIGURED' },
      },
      SOLO: {
        modeled_ev_btc_per_day: { value: 0.0001, status: 'AVAILABLE' },
        modeled_net_usd_per_day: { value: 3.25, status: 'AVAILABLE' },
        p_block_selected_window_pct: { value: null, status: 'UNKNOWN' },
        direct_cost_usd_per_day: { value: null, status: 'NOT CONFIGURED' },
      },
      RENTAL: {
        modeled_net_usd_per_day: { value: null, status: 'UNKNOWN' },
        direct_cost_usd_per_day: { value: null, status: 'NOT CONFIGURED' },
      },
      LEASE: {
        modeled_net_usd_per_day: { value: null, status: 'NOT CONFIGURED' },
        direct_cost_usd_per_day: { value: null, status: 'NOT CONFIGURED' },
      },
    },
  },
});

assert.equal(elements.get('dm-horizon').textContent, 'MODELED · 24h');
assert.equal(elements.get('dm-pool-usd').textContent, 'NOT CONFIGURED');
assert.equal(elements.get('dm-pool-cost').textContent, 'NOT CONFIGURED');
assert.equal(elements.get('dm-solo-time').textContent, '0.00010000 BTC/d');
assert.match(elements.get('dm-solo-sub').textContent, /UNKNOWN/);
assert.equal(elements.get('dm-rental-usd').textContent, 'UNKNOWN');
assert.equal(elements.get('dm-lease-usd').textContent, 'NOT CONFIGURED');
assert.equal(elements.get('dm-best-badge').textContent, 'BEST: POOL');
assert.equal(elements.get('dm-reco').textContent, 'Pool has the highest modeled net.');
console.log('✅ decision-matrix renderer displays modeled, unknown, and not-configured states');
