#!/usr/bin/env node
// Issue #843: execute the canonical rentals fragment, never a copied formatter.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const elements = new Map();
const document = {
  getElementById(id) {
    if (!elements.has(id)) elements.set(id, { textContent: '', innerHTML: '', hidden: false, classList: { add() {}, remove() {}, toggle() {} }, addEventListener() {} });
    return elements.get(id);
  },
  querySelectorAll() { return []; },
};
const sandbox = { document, window: {}, console, rentalsAuthRejected: () => false, escapeHtml: String, fmt: { hashrate: n => n + ' H/s' }, setTimeout, clearTimeout, URLSearchParams };
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync('static/src/46-rentals.js', 'utf8') + '\n globalThis.rentalTest = { _mrToTh, _rentalPriceStr, _rentalWorkThh, _rentalUnitCost, openRentalDetail };', sandbox);
const api = sandbox.rentalTest;
assert.equal(api._mrToTh(1, 'eh'), 1e6);
assert.equal(api._mrToTh(1, 'hash'), 1e-12);
assert.equal(api._mrToTh(1, ''), null);
assert.equal(api._mrToTh(true, 'th'), null);
assert.equal(api._mrToTh(-1, 'th'), null);
assert.equal(api._mrToTh(Infinity, 'eh'), null);
assert.equal(api._rentalWorkThh(1e308, 2), null);
assert.equal(api._rentalWorkThh(1e-308, 1e-308), null);
assert.equal(api._rentalWorkThh(0, 2), 0);
assert.equal(api._rentalWorkThh(1, -1), null);
assert.equal(api._rentalUnitCost(10000, 1e-308), null);
assert.equal(api._rentalUnitCost(0, 2), 0);
assert.equal(api._rentalPriceStr({ price_paid_btc: 1, price_currency: 'LTC', price_paid_amount: 2 }), '2 LTC');
assert.equal(api._rentalPriceStr({ price_paid_btc: 1, price_currency: 'LTC' }), '—');
assert.equal(api._rentalPriceStr({ price_paid_btc: 0, price_currency: 'BTC' }), '0 sats');

for (const currency of ['LTC', 'ETH', 'DOGE', 'BCH']) {
  sandbox.authFetch = async () => ({ ok: true, json: async () => ({
    success: true, provider: 'mrr', detail: {
      price: { paid: '2', currency }, length: 2, rig: { type: 'sha256' },
      hashrate: { advertised: { hash: 100, type: 'th' }, average: { hash: 90, type: 'th', percent: 90 } },
    }, perf: { avg_th: 90, percent: 90, delivered_thh: 180, cost_sats_per_thh: null },
    pl: { available: false }, market: { available: true, price_sats_per_thh: 10 },
  }) });
  sandbox._loadRentalEvidence = async () => {};
  await api.openRentalDetail('fixture843', 'mrr');
  assert.ok(elements.get('rentals-detail-grid').innerHTML.includes('2 ' + currency));
  assert.ok(!elements.get('rentals-detail-grid').innerHTML.includes('200000000 sats'));
  assert.ok(!elements.get('rentals-detail-perf').innerHTML.includes('1111111.11 sats/TH/h'));
  assert.ok(!elements.get('rentals-detail-perf').innerHTML.includes('% vs mkt'));
}
sandbox.authFetch = async () => ({ ok: true, json: async () => ({
  success: true, provider: 'braiins', detail: {
    price: { paid: '0.5', currency: 'BTC' }, length: 1, rig: { name: 'Braiins contract' },
    hashrate: { advertised: { hash: 100, type: 'ph' }, average: { hash: 95, type: 'ph', percent: 95 } },
    perf: { avg_th: 95000, percent: 95, delivered_thh: 95000, cost_sats_per_thh: 526.3 },
  }, pl: { available: true, pl_sats: -48218750 }, market: { available: false },
}) });
await api.openRentalDetail('B843', 'braiins');
assert.ok(elements.get('rentals-detail-perf').innerHTML.includes('526.30 sats/TH/h'), 'Braiins normalized contract still has provider-average cost');
assert.ok(elements.get('rentals-detail-perf').innerHTML.includes('-48218750 sats'), 'Braiins P/L is not gated by an MRR-only raw rig type');
sandbox.authFetch = async () => ({ ok: true, json: async () => ({
  success: true, provider: 'braiins', detail: {
    price: { paid: '0.5', currency: 'BTC' }, length: 0, rig: { name: 'Short sampled contract' },
    hashrate: { advertised: { hash: 100, type: 'ph' }, average: { hash: 95, type: 'ph', percent: 95 } },
    perf: { avg_th: 95000, percent: 95, delivered_thh: 250, cost_sats_per_thh: 200000 },
  }, pl: { available: true, pl_sats: -49999999 }, market: { available: false },
}) });
await api.openRentalDetail('short843', 'braiins');
assert.ok(elements.get('rentals-detail-perf').innerHTML.includes('200000.00 sats/TH/h'), 'rounded display duration cannot discard verified Braiins work');
console.log('PASS MRR original-currency and unit guards plus Braiins compatibility use the real source');
