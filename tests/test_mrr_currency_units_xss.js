#!/usr/bin/env node
// Issue #843: execute the real card renderer and real escaping helper, no provider calls.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import test from 'node:test';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const sandbox = { fmt: { hashrate: n => String(n) }, _ic: () => '' };
vm.createContext(sandbox);
vm.runInContext(
  fs.readFileSync(path.join(root, 'static/src/30-core-escape.js'), 'utf8') +
  fs.readFileSync(path.join(root, 'static/src/46-rentals.js'), 'utf8') +
  '\nglobalThis.renderRentalCard = _rentalCardHtml;',
  sandbox,
);

test('provider currency stays literal text in rendered card, including encoded event handlers', () => {
  // Numeric entities survive currency.toUpperCase() and decode to lowercase JS
  // in an HTML event-handler attribute. Never execute this synthetic payload.
  const currency = '<IMG SRC=X ONERROR=&#97;&#108;&#101;&#114;&#116;(1)>';
  const html = sandbox.renderRentalCard({
    id: 'fixture843', price_paid_amount: 2, price_currency: currency,
  });
  assert.ok(
    html.includes('2 &lt;IMG SRC=X ONERROR=&amp;#97;&amp;#108;&amp;#101;&amp;#114;&amp;#116;(1)&gt;'),
    'PAID must contain the original provider currency as escaped text',
  );
  assert.doesNotMatch(html, /<\s*(?:img|svg)\b/i, 'currency must not create an injected element');
  for (const tag of html.match(/<[^>]*>/g) || []) {
    assert.doesNotMatch(tag, /\bonerror\s*=/i, 'currency must not create an executable handler');
  }
});

test('unknown currency remains visible without inventing sats or an FX conversion', () => {
  const html = sandbox.renderRentalCard({
    id: 'fixture843', price_paid_amount: 2, price_currency: ' xyz ', price_paid_btc: 1,
  });
  assert.ok(html.includes('>2 XYZ</span>'));
  assert.ok(!html.includes('100000000 sats'));
});

test('verified BTC still renders the canonical sats amount', () => {
  const html = sandbox.renderRentalCard({
    id: 'fixture843', price_paid_amount: 0.0001, price_currency: 'BTC',
  });
  assert.ok(html.includes('>10000 sats</span>'));
});
