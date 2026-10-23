import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import { FIELDS, createTimelineLoader, validTimeline, timelineSegments, timelineDomain, timelineValue, readTimelineSession } from '../static/thermal-timeline-core.js';

const sample = (ts = 1000) => ({ ...Object.fromEntries(Object.keys(FIELDS).map(key => [key, null])), ts,
  hashrate_hs: 1e12, temperature_c: 50, source: 'axe_telemetry', window_seconds: null, gap_before_seconds: null });
const payload = () => ({ schema_version: 1, generated_at: 1000, device: { id: 'a' }, hours: 1, state: 'current', stale_after_s: 900,
  samples: [sample()], markers: [], latest_sample_ts: 1000, maintenance_context: 'unlinked', maintenance_truncated: false,
  coverage: { returned: 1, scanned: 1, skipped: 0, gaps: 0, truncated: false } });

function harness(fetchImpl, extra = {}) {
  let seq = 0, key = 'tenant-a'; const timers = new Map(), states = [], data = [];
  const loader = createTimelineLoader({ fetchImpl, readSession: () => ({ valid: true, key, headers: { Authorization: key } }),
    onState: state => states.push(state), onData: (body, selected) => data.push({ body, selected }),
    schedule: (fn, ms) => { timers.set(++seq, { fn, ms }); return seq; }, cancel: id => timers.delete(id), ...extra });
  return { loader, timers, states, data, switchSession() { key = 'tenant-b'; },
    async fire(ms) { const [id, task] = [...timers].find(([, task]) => task.ms === ms); timers.delete(id); await task.fn(); } };
}
const response = (data = payload()) => ({ ok: true, status: 200, json: async () => data });
const flush = async () => { for (let i = 0; i < 12; i++) await Promise.resolve(); };

test('source-backed schema preserves valid negative Celsius, true zero and independent PWM', () => {
  const p = payload(); p.samples[0].temperature_c = -5; p.samples[0].fan_speed = 50;
  assert.equal(validTimeline(p, { id: 'a', hours: 1 }), true);
  assert.equal(timelineValue(-5, 'temperature_c'), '-5 °C');
  assert.equal(timelineValue(0, 'fan_rpm'), '0 RPM'); assert.equal(timelineValue(50, 'fan_speed'), '50 %');
  assert.equal(timelineValue(null, 'fan_rpm'), '—'); assert.equal(timelineValue(1e12, 'hashrate_hs'), '1 TH/s');
  assert.equal(timelineValue(1e9, 'hashrate_hs'), '1 GH/s'); assert.equal(timelineValue(1, '__proto__'), '—');
});

test('schema rejects cross-device, cross-window, excessive, unordered, nonfinite and untyped observations', () => {
  for (const mutate of [p => { p.device.id = 'b'; }, p => { p.hours = 6; }, p => { p.samples = Array(301).fill(sample()); },
    p => { p.samples[0].ts = 1001; }, p => { p.samples.push(sample(999)); p.coverage.returned = 2; },
    p => { p.samples[0].temperature_c = NaN; }, p => { p.samples[0].fan_rpm = true; }, p => { p.samples[0].power_watts = '1'; },
    p => { p.samples[0].temperature_c = 151; }, p => { p.samples[0].gap_before_seconds = -1; },
    p => { p.samples[0].window_seconds = 60; }, p => { p.samples[0].source = 'unverified'; }]) {
    const p = payload(); mutate(p); assert.equal(validTimeline(p, { id: 'a', hours: 1 }), false);
  }
});

test('maintenance and observed-configuration markers accept only bounded typed context, not arbitrary commands', () => {
  const p = payload();
  p.markers = [{ ts: 999, kind: 'maintenance', type: 'cleaning' },
    { ts: 1000, kind: 'observed_configuration_change', changes: [{ field: 'fan_speed', before: 20, after: 30 }] }];
  assert.equal(validTimeline(p, { id: 'a', hours: 1 }), true);
  for (const marker of [{ ts: 999, kind: 'command', command: 'reboot' }, { ts: 999, kind: 'maintenance', type: '__proto__' },
    { ts: 999, kind: 'observed_configuration_change', changes: [{ field: 'fan_speed', before: 20, after: 101 }] },
    { ts: 999, kind: 'observed_configuration_change', changes: [{ field: 'voltage_mv', before: -1, after: 1000 }] },
    { ts: 999, kind: 'observed_configuration_change', changes: [] }]) {
    p.markers = [marker]; assert.equal(validTimeline(p, { id: 'a', hours: 1 }), false);
  }
});

test('lane groups never bridge nulls, a >900s gap or a short gap flagged after invalid observations', () => {
  const samples = [sample(1), sample(10), { ...sample(20), temperature_c: null }, sample(30), sample(1000),
    { ...sample(1010), gap_before_seconds: 10 }];
  assert.deepEqual(timelineSegments(samples, 'temperature_c').map(group => group.map(p => p.ts)), [[1, 10], [30], [1000], [1010]]);
  assert.deepEqual(timelineSegments([], 'fan_rpm'), []);
});

test('observed focus preserves time spacing and full-window bounds, including single/empty history', () => {
  const data = payload(); data.samples = [sample(800), sample(1000)];
  assert.deepEqual(timelineDomain(data), [800, 1000]);
  assert.deepEqual(timelineDomain(data, false), [-2600, 1000]);
  data.samples = [sample(1000)]; assert.deepEqual(timelineDomain(data), [970, 1000]);
  data.samples = []; assert.deepEqual(timelineDomain(data), [-2600, 1000]);
});

test('new selection is coalesced and previous JSON cannot republish; at most one request is active', async () => {
  let release; const calls = [];
  const h = harness(async (url, options) => { calls.push({ url, options }); return { ok: true, json: () => new Promise(resolve => { release = resolve; }) }; });
  const pending = h.loader.request({ url: 'a' }); await flush();
  h.loader.request({ url: 'b' }); h.loader.request({ url: 'c' });
  assert.equal(calls.length, 1); release(payload()); await pending; await flush();
  assert.deepEqual(calls.map(call => call.url), ['a', 'c']); assert.equal(h.data.length, 0);
  release(payload()); await flush();
  assert.equal(h.data[0].selected.url, 'c'); assert.equal(calls[0].options.method, 'GET');
  assert.equal(calls[0].options.cache, 'no-store'); assert.equal(calls[0].options.credentials, 'same-origin'); h.loader.stop();
});

test('session change, offline invalidation and pagehide-style stop fence uncooperative transport', async () => {
  for (const action of ['session', 'offline', 'stop']) {
    let release; const h = harness(() => new Promise(resolve => { release = resolve; }));
    const pending = h.loader.request({ url: 'private' });
    if (action === 'session') { h.switchSession(); h.loader.invalidate('auth'); }
    else if (action === 'offline') h.loader.invalidate('offline'); else h.loader.stop();
    release(response()); await pending; assert.equal(h.data.length, 0); h.loader.stop();
  }
});

test('deadline covers JSON body and backoff does not exceed60s', async () => {
  const h = harness(async () => ({ ok: true, json: () => new Promise(() => {}) }));
  const pending = h.loader.request({ url: 'body' }); await flush(); await h.fire(8000); await pending;
  assert.equal(h.states.at(-1), 'error'); assert.equal([...h.timers.values()][0].ms, 60000); h.loader.stop();
});

test('auth rejects without retry and malformed storage never falls back anonymously', async () => {
  const h = harness(async () => ({ ok: false, status: 401 })); await h.loader.request({ url: 'private' });
  assert.equal(h.states.at(-1), 'auth'); assert.equal(h.timers.size, 0); h.loader.stop();
  for (const raw of ['{}', 'null', 'bad', '{"access_token":1}']) assert.equal(readTimelineSession({ getItem: () => raw }).valid, false);
  assert.equal(readTimelineSession({ getItem: () => null }).valid, true);
  assert.equal(readTimelineSession({ getItem() { throw Error('blocked'); } }).valid, false);
  assert.equal(readTimelineSession({ getItem: () => '{"access_token":"fixture"}' }).headers.Authorization, 'Bearer fixture');
});

test('offline/invalid sessions perform no request and input validation failure surfaces an error', async () => {
  for (const options of [{ online: () => false }, { readSession: () => ({ valid: false }) }, { readSession() { throw Error('getter'); } }]) {
    let calls = 0; const h = harness(async () => { calls++; }, options);
    await h.loader.request({ url: 'private' }); assert.equal(calls, 0); h.loader.stop();
  }
  const h = harness(async () => response(), { onData() { throw Error('schema'); } });
  await h.loader.request({ url: 'bad' }); assert.equal(h.states.at(-1), 'error'); h.loader.stop();
});

test('lazy storage getter exceptions are caught before they escape the session boundary', () => {
  assert.equal(readTimelineSession(() => { throw Error('blocked getter'); }).valid, false);
});

test('actual SW excludes private API/page aliases before fetch or cache fallback', () => {
  const handlers = {}; let intercepts = 0, fetches = 0;
  vm.runInNewContext(fs.readFileSync(new URL('../static/sw.js', import.meta.url), 'utf8'), { URL,
    self: { addEventListener: (name, fn) => { handlers[name] = fn; }, location: { origin: 'https://fixture.test' } },
    fetch: () => { fetches++; return Promise.resolve({ ok: false }); } });
  for (const path of ['/thermal-timeline', '/api/thermal-timeline?device_id=a', '/api/thermal-timeline/devices',
    '/api/%74hermal-timeline/devices', '/api//thermal-timeline', '/%74hermal-timeline', '/api/%zz']) {
    handlers.fetch({ request: { method: 'GET', url: 'https://fixture.test' + path }, respondWith: () => intercepts++ });
  }
  assert.equal(intercepts, 0); assert.equal(fetches, 0);
});
