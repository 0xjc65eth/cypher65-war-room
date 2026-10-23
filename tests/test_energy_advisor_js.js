/** Production-source transport, privacy and decimal contracts, no mirrored math. */
import test from 'node:test';
import assert from 'node:assert/strict';
import { readEnergySession, createEnergyClient, validDecimal, validEnergyDevice, validEnergySnapshot, validEnergyEvaluation, energyNumber, energyMoney } from '../static/energy-advisor-core.js';

const session = { key: 'a', valid: true, headers: { Authorization: 'Bearer test' } };
const tick = () => new Promise(resolve => setTimeout(resolve, 2));
const deferred = () => { let resolve; const promise = new Promise(r => { resolve = r; }); return { promise, resolve }; };
function snapshot() {
  const now = Math.floor(Date.now() / 1000);
  return { schema_version: 1, generated_at: now, device: { id: 'a', name: 'A', model: 'Gamma', firmware: 'AxeOS', firmware_version: '2.9', capabilities: ['telemetry'] },
    telemetry: { state: 'current', source: 'axe_telemetry', observed_at: now - 30, age_seconds: 30, stale_after_s: 900, power_watts: 0, hashrate_hs: 0, temperature_c: -10 }, solar: { state: 'not_configured', power_watts: null } };
}
function evaluation() {
  const d = snapshot();
  return { ...d, mode: 'read_only', hours: 6, currency: 'EUR', tariff_state: 'current', tariff: { value: .3, currency: 'EUR', source: 'operator', observed_at: d.generated_at - 60, valid_until: d.generated_at + 3600 },
    expires_at: d.telemetry.observed_at + 900, baseline: { state: 'available', energy_kwh: '0.000000', cost: '0.000000', cost_below_resolution: false, energy_below_resolution: false },
    profiles: [{ id: 'p', name: 'P', eligible: true, reasons: [], expected_power_watts: 100, energy_kwh: '0.600000', cost: '0.180000', cost_below_resolution: false, energy_below_resolution: false }], suggestion: { type: 'review_candidates', profile_id: null, eligible_profile_ids: ['p'] } };
}

test('storage getter, invalid sessions and legitimate self-host absence are distinguished', () => {
  assert.deepEqual(readEnergySession(() => ({ getItem: () => null })), { key: '', valid: true, headers: {} });
  assert.equal(readEnergySession(() => { throw Error('blocked'); }).valid, false);
  for (const raw of ['{', '{}', '{"access_token":false}', '{"access_token":""}']) assert.equal(readEnergySession(() => ({ getItem: () => raw })).valid, false);
  assert.equal(readEnergySession(() => ({ getItem: () => '{"access_token":"test"}' })).headers.Authorization, 'Bearer test');
});
test('decimal and unit display never coerce null/bool/string to real measurements', () => {
  for (const value of [null, 0, true, 'NaN', 'Infinity', '-1', '1e10', '.1', '9'.repeat(17)]) assert.equal(validDecimal(value), false);
  for (const value of ['0', '0.000001', '123.45']) assert.equal(validDecimal(value), true);
  assert.equal(energyNumber(null, 'W'), '—'); assert.equal(energyNumber('0', 'W'), '—'); assert.equal(energyNumber(0, 'W'), '0 W');
  assert.equal(energyMoney(null, 'EUR'), '—'); assert.equal(energyMoney('1', 'XXX'), '—'); assert.match(energyMoney('0.18', 'EUR'), /0,18/);
  assert.match(energyMoney('0.000001', 'EUR'), /^< .*0,0001/);
  assert.match(energyMoney('0.000000', 'EUR', true), /^< .*0,000001/);
  assert.doesNotMatch(energyMoney('0.000000', 'EUR'), /^</);
  assert.equal(energyNumber(.00001, 'EUR/kWh'), '< 0,001 EUR/kWh');
});
test('snapshot guard preserves zero and rejects incoherent age/source/missing/future/extreme data', () => {
  assert.equal(validEnergySnapshot(snapshot(), 'a'), true); assert.equal(validEnergySnapshot(null, 'a'), false);
  assert.equal(validEnergySnapshot(snapshot(), 'b'), false); assert.equal(validEnergyDevice({}), false);
  for (const patch of [{ age_seconds: null }, { age_seconds: 0 }, { observed_at: null }, { power_watts: false }, { temperature_c: 151 }, { power_watts: 1e10 }, { source: 'fake' }, { hashrate_hs: null }, { observed_at: 999999999999 }]) {
    const d = snapshot(); Object.assign(d.telemetry, patch); assert.equal(validEnergySnapshot(d, 'a'), false, JSON.stringify(patch));
  }
  const d = snapshot(); d.telemetry.age_seconds = 900; d.telemetry.observed_at = d.generated_at - 900; assert.equal(validEnergySnapshot(d, 'a'), false);
  d.telemetry.state = 'stale'; assert.equal(validEnergySnapshot(d, 'a'), true);
  d.solar.state = 'current'; assert.equal(validEnergySnapshot(d, 'a'), false);
});
test('evaluation guard rejects fabricated eligibility, invalid cost, deadline and ranking', () => {
  assert.equal(validEnergyEvaluation(evaluation(), 'a'), true);
  const changed = mutate => { const d = evaluation(); mutate(d); assert.equal(validEnergyEvaluation(d, 'a'), false); };
  changed(d => { d.mode = 'apply'; }); changed(d => { d.tariff_state = 'expired'; }); changed(d => { d.tariff.source = 'assumed'; });
  changed(d => { d.profiles[0].cost = '-1'; }); changed(d => { d.profiles[0].eligible = 'yes'; }); changed(d => { d.expires_at = null; });
  changed(d => { d.expires_at = d.generated_at + 5000; }); changed(d => { d.suggestion.profile_id = 'p'; }); changed(d => { d.suggestion.eligible_profile_ids = ['unknown']; });
  const blocked = evaluation(); blocked.baseline = { state: 'blocked', cost: null, energy_kwh: null, cost_below_resolution: false, energy_below_resolution: false }; blocked.expires_at = null; blocked.profiles[0].eligible = false; blocked.suggestion.eligible_profile_ids = [];
  assert.equal(validEnergyEvaluation(blocked, 'a'), true);
});
test('single-flight coalesces selection changes and rejects delayed JSON from older selection', async () => {
  const first = deferred(), calls = [], data = [], states = [];
  const client = createEnergyClient({ readSession: () => session, onData: d => data.push(d), onState: s => states.push(s), fetchImpl: async url => { calls.push(url); return { ok: true, json: () => first.promise }; } });
  client.request({ url: '/a', kind: 'snapshot' }); await tick();
  client.request({ url: '/b', kind: 'snapshot' }); client.request({ url: '/c', kind: 'snapshot' });
  first.resolve({ id: 'latest' }); await tick();
  assert.deepEqual(calls, ['/a', '/c']); assert.deepEqual(data, [{ id: 'latest' }]); client.stop();
  client.request({ url: '/ignored', kind: 'snapshot' }); assert.equal(calls.length, 2);
});
test('session change fences late successful JSON even without a storage event', async () => {
  const pending = deferred(), states = [], data = []; let key = 'a';
  const client = createEnergyClient({ readSession: () => ({ ...session, key }), onData: d => data.push(d), onState: s => states.push(s), fetchImpl: async () => ({ ok: true, json: () => pending.promise }) });
  client.request({ url: '/a', kind: 'snapshot' }); await tick(); key = 'b'; pending.resolve({ private: true }); await tick();
  assert.equal(data.length, 0); assert.equal(states.at(-1), 'auth'); client.stop();
});
test('invalid session, throwing reader and offline never issue anonymous requests', async () => {
  for (const read of [() => ({ ...session, valid: false }), () => { throw Error(); }]) {
    let calls = 0; const states = []; const client = createEnergyClient({ readSession: read, onState: s => states.push(s), onData() {}, fetchImpl: async () => { calls++; } });
    await client.request({ url: '/x', kind: 'devices' }); assert.equal(calls, 0); assert.equal(states.at(-1), 'auth'); client.stop();
  }
  const states = []; const client = createEnergyClient({ readSession: () => session, online: () => false, onState: s => states.push(s), onData() {} });
  await client.request({ url: '/x', kind: 'devices' }); assert.equal(states.at(-1), 'offline'); client.stop();
});
test('GET retries once with backoff; POST/401/400 never replay automatically', async () => {
  let calls = 0; const data = [];
  const client = createEnergyClient({ readSession: () => session, retryMs: 1, onData: d => data.push(d), onState() {}, fetchImpl: async () => ++calls === 1 ? { ok: false, status: 503 } : { ok: true, json: async () => 'ok' } });
  await client.request({ url: '/x', kind: 'devices' }); await new Promise(r => setTimeout(r, 12)); assert.equal(calls, 2); assert.deepEqual(data, ['ok']); client.stop();
  for (const [status, body, expected] of [[503, {}, 'error'], [401, undefined, 'auth'], [403, undefined, 'auth'], [400, undefined, 'invalid']]) {
    let attempts = 0; const states = [];
    const c = createEnergyClient({ readSession: () => session, retryMs: 1, onData() {}, onState: s => states.push(s), fetchImpl: async () => { attempts++; return { ok: false, status }; } });
    await c.request({ url: '/x', kind: 'evaluate', ...(body ? { body } : {}) }); await tick(); assert.equal(attempts, 1); assert.equal(states.at(-1), expected); c.stop();
  }
});
test('deadline covers JSON body; bounded POST has no accidental retry or late-data render', async () => {
  const pending = deferred(), data = [], states = []; let calls = 0;
  const client = createEnergyClient({ readSession: () => session, timeoutMs: 4, onData: d => data.push(d), onState: s => states.push(s), fetchImpl: async (_url, options) => {
    calls++; assert.equal(options.method, 'POST'); assert.equal(options.cache, 'no-store'); assert.equal(options.headers.Authorization, 'Bearer test'); return { ok: true, json: () => pending.promise };
  } });
  await client.request({ url: '/x', kind: 'evaluate', body: {} }); assert.equal(states.at(-1), 'error'); pending.resolve('obsolete'); await tick();
  assert.equal(calls, 1); assert.equal(data.length, 0); client.stop();
});
test('persistent GET failures stop after one retry and surface offline/errors', async () => {
  let calls = 0; const states = [];
  const client = createEnergyClient({ readSession: () => session, retryMs: 1, onState: s => states.push(s), onData() {}, fetchImpl: async () => { calls++; throw 'failure'; } });
  await client.request({ url: '/x', kind: 'devices' }); await new Promise(r => setTimeout(r, 12)); assert.equal(calls, 2); assert.equal(states.at(-1), 'error'); client.stop();
});
