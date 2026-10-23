import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import { createMiniController, readMiniSession, formatMiniMetric } from '../static/mini-war-room.js';

const snapshot = () => ({ schema_version: 1, generated_at: 1000, stale_after_s: 900, state: 'current',
  counts: { total: 1, current: 1, stale: 0, offline: 0, unknown: 0 },
  metrics: Object.fromEntries([['hashrate', 'H/s'], ['power', 'W'], ['temperature', '°C']].map(([key, unit]) =>
    [key, { value: 0, unit, contributors: 1, oldest_observed_at: 990, newest_observed_at: 990 }])) });
const response = (data = snapshot()) => ({ ok: true, status: 200, json: async () => data });

function harness(fetchImpl) {
  const frames = [], timers = new Map();
  let seq = 0, key = 'tenant-a';
  const controller = createMiniController({ render: frame => frames.push(frame), fetchImpl,
    readSession: () => ({ key, headers: { Authorization: key }, valid: true }), now: () => 1000,
    schedule: (fn, delay) => { timers.set(++seq, { fn, delay }); return seq; }, cancel: id => timers.delete(id) });
  return { controller, frames, timers, changeSession: () => { key = 'tenant-b'; },
    async fire(delay) { const [id, timer] = [...timers].find(([, t]) => t.delay === delay); timers.delete(id); await timer.fn(); } };
}

test('existing session is read without an anonymous fallback for malformed or unavailable storage', () => {
  for (const raw of ['bad', '{}', 'null', '{"access_token":1}', '{"access_token":""}']) {
    assert.equal(readMiniSession({ getItem: () => raw }).valid, false);
  }
  assert.equal(readMiniSession({ getItem() { throw Error('denied'); } }).valid, false);
  assert.equal(readMiniSession({ getItem: () => null }).valid, true);
  assert.deepEqual(readMiniSession({ getItem: () => '{"access_token":"test-fixture"}' }).headers, { Authorization: 'Bearer test-fixture' });
});

test('production formatter keeps observed zero distinct from invalid/missing and rejects units', () => {
  assert.equal(formatMiniMetric({ value: 0, unit: 'H/s' }), '0 H/s');
  assert.equal(formatMiniMetric({ value: 1e12, unit: 'H/s' }), '1 TH/s');
  for (const value of [null, undefined, NaN, Infinity, -1, '2', true]) assert.equal(formatMiniMetric({ value, unit: 'W' }), '—');
  assert.equal(formatMiniMetric({ value: 1, unit: '<img>' }), '—');
});

test('read-only single-flight request uses existing credentials and no-store', async () => {
  let release, requests = [];
  const h = harness((...args) => { requests.push(args); return new Promise(resolve => { release = resolve; }); });
  const first = h.controller.refresh(); await h.controller.refresh();
  assert.equal(requests.length, 1);
  assert.equal(requests[0][0], '/api/mini-war-room');
  assert.equal(requests[0][1].method, 'GET'); assert.equal(requests[0][1].cache, 'no-store');
  assert.equal(requests[0][1].credentials, 'same-origin');
  release(response()); await first;
  assert.equal(h.frames.at(-1).snapshot.metrics.hashrate.value, 0);
  await h.fire(890000); assert.equal(h.frames.at(-1).state, 'stale'); assert.equal(h.frames.at(-1).snapshot, null);
  h.controller.stop();
});

test('a session change while JSON is pending cannot republish previous tenant observations', async () => {
  let release;
  const h = harness(async () => ({ ok: true, status: 200, json: () => new Promise(resolve => { release = resolve; }) }));
  const first = h.controller.refresh(); await Promise.resolve();
  h.changeSession(); h.controller.sessionChanged(); release(snapshot()); await first;
  assert.equal(h.frames.some(frame => frame.snapshot), false);
  assert.equal(h.frames.at(-1).state, 'auth'); h.controller.stop();
});

test('offline/paused/stopped responses cannot publish, even if transport ignores abort', async () => {
  for (const action of ['stop', 'setPaused', 'invalidate']) {
    let release;
    const h = harness(() => new Promise(resolve => { release = resolve; }));
    const request = h.controller.refresh();
    h.controller[action](action === 'invalidate' ? 'offline' : true);
    release(response()); await request;
    assert.equal(h.frames.some(frame => frame.snapshot), false); h.controller.stop();
  }
});

test('deadline includes a JSON body that never resolves and retry backoff is bounded', async () => {
  let calls = 0;
  const h = harness(async () => { calls++; return { ok: true, status: 200, json: () => new Promise(() => {}) }; });
  const request = h.controller.refresh(); await Promise.resolve(); await h.fire(8000); await request;
  assert.equal(h.frames.at(-1).state, 'error');
  assert.equal([...h.timers.values()].some(t => t.delay === 30000), true);
  // Run the next request without waiting on its never-resolving body.
  [...h.timers.values()].find(t => t.delay === 30000).fn();
  await Promise.resolve(); await h.fire(8000); await Promise.resolve(); await Promise.resolve();
  assert.equal(calls, 2); assert.equal([...h.timers.values()].some(t => t.delay === 60000), true);
  h.controller.stop();
});

test('authentication rejection clears observations and stops automatic retries', async () => {
  const h = harness(async () => ({ ok: false, status: 401 }));
  await h.controller.refresh(); assert.equal(h.frames.at(-1).state, 'auth');
  assert.equal(h.timers.size, 0); h.controller.stop();
});

test('expired observations, bad schema and future timestamps never become current', async () => {
  const old = snapshot(); old.metrics.hashrate.oldest_observed_at = 1;
  const future = snapshot(); future.metrics.hashrate.oldest_observed_at = 1001;
  for (const [data, expected] of [[old, 'stale'], [future, 'error'], [{...snapshot(), schema_version: 2}, 'error']]) {
    const h = harness(async () => response(data)); await h.controller.refresh();
    assert.equal(h.frames.at(-1).state, expected); assert.equal(h.frames.at(-1).snapshot, null); h.controller.stop();
  }
});

test('malformed metric metadata is rejected, but an overflow sum does not hide other valid metrics', async () => {
  const overflow = snapshot(); overflow.state = 'partial'; overflow.metrics.hashrate.value = null;
  const h = harness(async () => response(overflow)); await h.controller.refresh();
  assert.equal(h.frames.at(-1).snapshot.metrics.power.value, 0); h.controller.stop();
  for (const mutate of [s => { s.counts.total = '<img>'; }, s => { s.metrics.power.unit = 'USD'; },
    s => { s.metrics.power.value = -1; }, s => { s.metrics.power.newest_observed_at = Infinity; },
    s => { s.metrics.power.contributors = 5; }, s => { s.metrics.power = null; }]) {
    const data = snapshot(); mutate(data);
    const bad = harness(async () => response(data)); await bad.controller.refresh();
    assert.equal(bad.frames.at(-1).state, 'error'); bad.controller.stop();
  }
});

test('service-worker production handler never intercepts monitor/API query variants', () => {
  const handlers = {}; let calls = 0, fetches = 0;
  vm.runInNewContext(fs.readFileSync(new URL('../static/sw.js', import.meta.url), 'utf8'), {
    self: { addEventListener: (name, fn) => { handlers[name] = fn; }, location: { origin: 'https://fixture.test' } }, URL,
    fetch: () => { fetches++; return Promise.resolve({ ok: false }); },
  });
  for (const path of ['/api/mini-war-room', '/api/mini-war-room?tenant=ignored', '/mini-war-room?presentation=obs',
    '/api/%6dini-war-room', '/%61pi/mini-war-room', '/api//mini-war-room', '/api/%2fmini-war-room', '/%6dini-war-room', '/api/%zz']) {
    handlers.fetch({ request: { method: 'GET', url: 'https://fixture.test' + path }, respondWith: () => calls++ });
  }
  assert.equal(calls, 0);
  assert.equal(fetches, 0);
});
