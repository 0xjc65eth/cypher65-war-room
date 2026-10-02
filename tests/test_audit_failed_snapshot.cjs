'use strict';

const assert = require('node:assert/strict');
const { test } = require('node:test');
const { auditFailedSnapshot, snapshotFailureProblem } = require('../scripts/audit-failed-snapshot.cjs');

function fixture({ intercept = true, leftovers = 0, failAt = null, query = '' } = {}) {
  const calls = [];
  let handler;
  const page = {
    async route(matches, fn) {
      assert.equal(matches('http://127.0.0.1:8765/api/snapshot' + query), true);
      assert.equal(matches('https://example.org/api/snapshot'), false);
      assert.equal(matches('http://127.0.0.1:8765/api/healthz'), false);
      handler = fn;
    },
    async waitForResponse(predicate, options) {
      calls.push('wait');
      assert.equal(options.timeout, 10000);
      assert.equal(predicate({ url: () => 'http://127.0.0.1:8765/api/snapshot' + query, status: () => 500 }), true);
      assert.equal(predicate({ url: () => 'http://127.0.0.1:8765/api/snapshot', status: () => 200 }), false);
      if (failAt === 'response') throw new Error('No HTTP 500 observed');
    },
    async goto() {
      calls.push('goto');
      if (failAt === 'navigation') throw new Error('Navigation failed');
      if (intercept) await handler({ fulfill: async (payload) => assert.equal(payload.status, 500) });
    },
    async waitForTimeout(ms) { assert.equal(ms, 3000); },
    async evaluate() { if (failAt === 'evaluate') throw new Error('Page closed'); return leftovers; },
  };
  const context = {
    async newPage() { return page; },
    async close() { calls.push('close'); if (failAt === 'close') throw new Error('Close failed'); },
  };
  const browser = {
    async newContext(options) {
      assert.deepEqual(options, { viewport: { width: 375, height: 812 }, serviceWorkers: 'block' });
      if (failAt === 'context') throw new Error('Context failed');
      return context;
    },
  };
  return { browser, calls };
}

async function probe(options) {
  const f = fixture(options);
  const result = await auditFailedSnapshot(f.browser, 'http://127.0.0.1:8765', { width: 375, height: 812 });
  return { ...f, result };
}

test('500 interception is proven before accepting cleanup, with a fresh SW-blocked context', async () => {
  const { result, calls } = await probe({ query: '?tenant=current' });
  assert.deepEqual(result, { intercepted: 1, leftovers: 0, error: null });
  assert.equal(snapshotFailureProblem(result), null);
  assert.deepEqual(calls, ['wait', 'goto', 'close']);
});

test('zero intercepted requests cannot produce a green audit', async () => {
  const { result } = await probe({ intercept: false });
  assert.match(snapshotFailureProblem(result), /not intercepted/);
});

test('remaining skeletons block the audit', async () => {
  const { result } = await probe({ leftovers: 40 });
  assert.match(snapshotFailureProblem(result), /40 skeleton/);
});

for (const stage of ['response', 'navigation', 'evaluate', 'close']) {
  test(`${stage} failure is blocking and still closes the context`, async () => {
    const { result, calls } = await probe({ failAt: stage });
    assert.match(snapshotFailureProblem(result), /probe failed/);
    assert.equal(calls.at(-1), 'close');
  });
}

test('context creation failure is blocking', async () => {
  const { result } = await probe({ failAt: 'context' });
  assert.match(snapshotFailureProblem(result), /Context failed/);
});

test('unknown/incomplete measurements are not green', () => {
  for (const leftovers of [-1, null, undefined, NaN, 0.5]) {
    assert.match(snapshotFailureProblem({ intercepted: 1, leftovers, error: null }), /incomplete/);
  }
});
