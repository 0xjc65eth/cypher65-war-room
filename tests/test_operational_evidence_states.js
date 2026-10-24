/** Issue #757: exercise real UI consumers with synthetic, isolated responses.
 * No source mirrors, physical commands, HTTP server, or external requests.
 * C65_EVIDENCE_TEST_REF loads a Git baseline read-only for red verification.
 */
'use strict';

import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const tests = [];
const test = (name, run) => tests.push({ name, run });
const tick = () => new Promise(resolve => setImmediate(resolve));
const response = (status, data) => ({
  status, ok: status >= 200 && status < 300, json: async () => data,
});
function deferred() {
  let resolve;
  const promise = new Promise(done => { resolve = done; });
  return { promise, resolve };
}

class Element {
  constructor(id = '') {
    this.id = id;
    this.hidden = false;
    this.style = { display: '' };
    this.dataset = {};
    this.attributes = {};
    this.listeners = {};
    this.children = [];
    this._html = '';
    this.classList = { add() {}, remove() {}, toggle() {}, contains: () => false };
  }
  set innerHTML(value) { this._html = String(value); }
  get innerHTML() { return this._html; }
  set textContent(value) { this._html = String(value); }
  get textContent() { return this._html.replace(/<[^>]*>/g, ''); }
  setAttribute(name, value) { this.attributes[name] = String(value); }
  getAttribute(name) { return this.attributes[name] || null; }
  removeAttribute(name) { delete this.attributes[name]; }
  addEventListener(name, callback) { this.listeners[name] = callback; }
  querySelectorAll() { return []; }
  querySelector() { return null; }
  appendChild(child) { this.children.push(child); return child; }
  remove() {}
  getContext() { return { canvas: this }; }
}

function harness(extraIds = [], extra = {}) {
  const ids = [
    'alerts-list', 'alerts-count-badge', 'lm-status-badge', 'lm-workers-grid',
    'lm-workers-count', 'lm-workers-badge', 'lm-workers', 'admin-error',
    'admin-gate-badge', 'admin-sessions', 'axe-detail', 'axe-detail-title',
    'axe-detail-body', 'axe-detail-close', 'axe-detail-chart-wrap',
    'axe-detail-chart', 'axe-detail-chart-count', 'axe-detail-chart-status',
    ...extraIds,
  ];
  const nodes = Object.fromEntries(ids.map(id => [id, new Element(id)]));
  nodes['admin-error'].hidden = true;
  nodes['axe-detail'].style.display = 'none';
  nodes['axe-detail-chart-wrap'].style.display = 'none';
  nodes['lm-status-badge'].textContent = 'LIVE'; // Existing template default.
  const document = {
    getElementById: id => nodes[id] || null,
    querySelector: selector => selector.startsWith('#') ? nodes[selector.slice(1)] || null : null,
    querySelectorAll: () => [], createElement: () => new Element(), body: new Element(),
  };
  const storage = new Map();
  const charts = [];
  class Chart {
    constructor(context, config) {
      this.canvas = context.canvas;
      this.config = config;
      this.data = config.data;
      this.options = config.options;
      this.destroyed = false;
      charts.push(this);
    }
    destroy() { this.destroyed = true; }
    update() {}
    static getChart(canvas) { return charts.findLast(chart => chart.canvas === canvas && !chart.destroyed); }
  }
  const dom = {
    alertsList: nodes['alerts-list'], alertsCountBadge: nodes['alerts-count-badge'],
    lmStatusBadge: nodes['lm-status-badge'], lmWorkersGrid: nodes['lm-workers-grid'],
    lmWorkersCount: nodes['lm-workers-count'], lmWorkersBadge: nodes['lm-workers-badge'],
    lmWorkers: nodes['lm-workers'], axeDetail: nodes['axe-detail'],
    axeDetailTitle: nodes['axe-detail-title'], axeDetailBody: nodes['axe-detail-body'],
    axeDetailClose: nodes['axe-detail-close'],
  };
  const sandbox = {
    document, dom, Chart, console, Date, Map, Set, URLSearchParams,
    setTimeout, clearTimeout, AbortController,
    localStorage: {
      getItem: key => storage.get(key) || null,
      setItem: (key, value) => storage.set(key, String(value)),
      removeItem: key => storage.delete(key),
    },
    window: { matchMedia: () => ({ matches: true }), addEventListener() {} },
    navigator: {}, cssVar: () => 'rgb(10,20,30)',
    setHtmlIfChanged: (element, html) => { if (element.innerHTML !== html) element.innerHTML = html; },
    skelShow() {}, skelHide() {}, logMessage() {},
    _ccLastFleet: [], _ccView: 'grid', _ccHrSeries: [], _ccHrHist: {},
    ...extra,
  };
  return { nodes, sandbox, charts, storage };
}

function fragment(name) {
  const relative = 'static/src/' + name;
  if (process.env.C65_EVIDENCE_TEST_REF) {
    return execFileSync('git', ['show', process.env.C65_EVIDENCE_TEST_REF + ':' + relative], { cwd: root, encoding: 'utf8' });
  }
  return fs.readFileSync(path.join(root, relative), 'utf8');
}
function load(h, names, exports) {
  const source = ['10-core-fmt.js', '30-core-escape.js', ...names].map(fragment).join('\n');
  return vm.runInNewContext('(function(){\n' + source + '\nreturn (' + exports + ');})()', h.sandbox, { timeout: 5000 });
}
function historyRows(hashrate = 1e12) {
  return [{ ts: 1000, hashrate, temperature: 40, efficiency_jth: 25 },
    { ts: 1060, hashrate, temperature: 41, efficiency_jth: 26 }];
}
function historyStatus(h) {
  return h.nodes['axe-detail-chart-status'].textContent + ' ' + h.nodes['axe-detail-chart-count'].textContent;
}

test('empty alerts are neutral, while missing alerts show loading', () => {
  const h = harness();
  const render = load(h, ['41-automations.js'], 'renderAlerts');
  render(null);
  assert.match(h.nodes['alerts-list'].textContent, /loading|carregando/i);
  render([]);
  assert.doesNotMatch(h.nodes['alerts-list'].textContent, /all systems nominal|healthy|saudável/i);
  assert.match(h.nodes['alerts-list'].textContent, /no alerts|sem alertas/i);
});

test('failed first summary exposes ERROR instead of default LIVE', async () => {
  const h = harness([], { authFetch: async () => response(503, { error: 'unavailable' }) });
  const api = load(h, ['48-fleet-cc.js', '49-axe-fleet.js'], '{fetchFleetCommandCenter}');
  await api.fetchFleetCommandCenter();
  assert.match(h.nodes['lm-status-badge'].textContent, /error|erro/i);
  assert.doesNotMatch(h.nodes['lm-status-badge'].textContent, /LIVE/i);
});

test('summary retains prior observations only with an explicit CACHED marker, then recovers', async () => {
  const fleet = [{ id: 'worker-A', name: 'A', status: 'ONLINE', ip_address: '192.0.2.1',
    capabilities: {}, _telemetry: { hashrate_hs: 1e12, temperature: 40 } }];
  const replies = [response(200, { devices: fleet }), response(503, {}), response(200, { devices: [] })];
  const h = harness([], { authFetch: async () => replies.shift() });
  const api = load(h, ['48-fleet-cc.js', '49-axe-fleet.js'], '{fetchFleetCommandCenter}');
  await api.fetchFleetCommandCenter();
  assert.match(h.nodes['lm-status-badge'].textContent, /LIVE/i);
  const prior = h.nodes['lm-workers-grid'].innerHTML;
  assert.match(prior, /worker-A|>A</);
  await api.fetchFleetCommandCenter();
  assert.match(h.nodes['lm-status-badge'].textContent, /CACHED|cache/i);
  assert.doesNotMatch(h.nodes['lm-status-badge'].textContent, /LIVE/i);
  assert.equal(h.nodes['lm-workers-grid'].innerHTML, prior);
  await api.fetchFleetCommandCenter();
  assert.match(h.nodes['lm-status-badge'].textContent, /EMPTY|vazi|sem/i);
  assert.doesNotMatch(h.nodes['lm-workers-grid'].innerHTML, /worker-A/);
});

test('summary denied access clears cached private workers', async () => {
  const replies = [response(200, { devices: [{ id: 'private-A', name: 'private-A', status: 'ONLINE', capabilities: {} }] }), response(403, {})];
  const h = harness([], { authFetch: async () => replies.shift() });
  const api = load(h, ['48-fleet-cc.js', '49-axe-fleet.js'], '{fetchFleetCommandCenter}');
  await api.fetchFleetCommandCenter();
  await api.fetchFleetCommandCenter();
  assert.match(h.nodes['lm-status-badge'].textContent, /ACCESS|required|acesso/i);
  assert.doesNotMatch(h.nodes['lm-workers-grid'].innerHTML, /private-A/);
});

test('partial Admin load identifies failed dataset and allows retry to recovery', async () => {
  let failed = true;
  let calls = 0;
  const h = harness([], { fetch: async url => {
    calls++;
    if (failed && url.includes('/sessions')) return response(503, { error: 'unavailable' });
    return response(200, url.includes('/sessions') ? { pool: { sessions_active: 7 } } : {});
  } });
  const api = load(h, ['47-admin.js'], '{fetchAdminData}');
  await api.fetchAdminData();
  assert.match(h.nodes['admin-gate-badge'].textContent, /partial|parcial/i);
  assert.equal(h.nodes['admin-error'].hidden, false);
  assert.match(h.nodes['admin-error'].textContent, /sessions/i);
  assert.match(h.nodes['admin-error'].textContent, /503/);
  const initialCalls = calls;
  failed = false;
  await api.fetchAdminData();
  assert.ok(calls > initialCalls, 'partial data must remain retryable');
  assert.match(h.nodes['admin-gate-badge'].textContent, /ok/i);
  assert.equal(h.nodes['admin-error'].hidden, true);
  assert.equal(h.nodes['admin-sessions'].textContent, '7');
});

test('history preserves zero and keeps temperature and efficiency on separate axes', async () => {
  const h = harness([], { authFetch: async () => response(200, { device_id: 'A', history: historyRows(0) }) });
  const api = load(h, ['49-axe-fleet.js'], '{loadDeviceHistoryChart}');
  await api.loadDeviceHistoryChart('A');
  const chart = h.charts.at(-1);
  assert.ok(chart, 'a chart must represent zero measurements');
  assert.equal(chart.data.datasets[0].data[0], 0);
  assert.notEqual(chart.data.datasets[1].yAxisID, chart.data.datasets[2].yAxisID);
  const scales = chart.options.scales;
  assert.match(scales[chart.data.datasets[1].yAxisID].title.text, /°C/);
  assert.match(scales[chart.data.datasets[2].yAxisID].title.text, /J\/TH/);
});

test('history with a single observation renders a visible point', async () => {
  const h = harness([], { authFetch: async () => response(200, { device_id: 'A', history: historyRows(0).slice(0, 1) }) });
  const api = load(h, ['49-axe-fleet.js'], '{loadDeviceHistoryChart}');
  await api.loadDeviceHistoryChart('A');
  const chart = h.charts.at(-1);
  assert.ok(chart, 'one real observation must not be discarded');
  assert.equal(chart.data.datasets[0].data.length, 1);
  assert.ok(chart.data.datasets[0].pointRadius > 0, 'a line with one point needs a visible marker');
  assert.equal(h.nodes['axe-detail-chart'].hidden, false);
});

for (const [status, expected] of [[503, /error|erro|indisponível/i], [403, /access|acesso|restricted/i]]) {
  test('history HTTP ' + status + ' visibly identifies failure and hides old chart', async () => {
    const replies = [response(200, { device_id: 'A', history: historyRows() }), response(status, {})];
    const h = harness([], { authFetch: async () => replies.shift() });
    const api = load(h, ['49-axe-fleet.js'], '{loadDeviceHistoryChart}');
    await api.loadDeviceHistoryChart('A');
    await api.loadDeviceHistoryChart('A');
    assert.match(historyStatus(h), expected);
    assert.equal(h.nodes['axe-detail-chart'].hidden, true);
    assert.ok(h.charts[0].destroyed);
  });
}

test('history empty differs from failed history and clears the prior chart', async () => {
  const replies = [response(200, { device_id: 'A', history: historyRows() }), response(200, { device_id: 'A', history: [] })];
  const h = harness([], { authFetch: async () => replies.shift() });
  const api = load(h, ['49-axe-fleet.js'], '{loadDeviceHistoryChart}');
  await api.loadDeviceHistoryChart('A');
  await api.loadDeviceHistoryChart('A');
  assert.match(historyStatus(h), /empty|no.*(sample|point)|sem.*(amostra|ponto)|vazio/i);
  assert.doesNotMatch(historyStatus(h), /error|erro/i);
  assert.equal(h.nodes['axe-detail-chart'].hidden, true);
});

test('delayed device A history never overwrites the newer device B chart', async () => {
  const a = deferred(); const b = deferred();
  const h = harness([], { authFetch: url => url.includes('/A/') ? a.promise : b.promise });
  const api = load(h, ['49-axe-fleet.js'], '{loadDeviceHistoryChart}');
  const requestA = api.loadDeviceHistoryChart('A');
  const requestB = api.loadDeviceHistoryChart('B');
  b.resolve(response(200, { device_id: 'B', history: historyRows(2e12) }));
  await requestB;
  a.resolve(response(200, { device_id: 'A', history: historyRows(9e12) }));
  await requestA;
  const chart = h.charts.findLast(item => !item.destroyed);
  assert.equal(chart.data.datasets[0].data[0], 2);
  assert.equal(h.charts.filter(item => !item.destroyed).length, 1);
});

test('delayed device A detail never replaces the newer B identity', async () => {
  const a = deferred(); const b = deferred();
  const h = harness([], { authFetch: url => {
    if (url.includes('/history')) return Promise.resolve(response(200, { device_id: url.includes('/A/') ? 'A' : 'B', history: [] }));
    return url.endsWith('/A') ? a.promise : b.promise;
  } });
  const api = load(h, ['49-axe-fleet.js'], '{openAxeDetail}');
  api.openAxeDetail('A'); api.openAxeDetail('B');
  b.resolve(response(200, { device: { id: 'B', name: 'device B' }, latest_telemetry: {} }));
  await tick();
  a.resolve(response(200, { device: { id: 'A', name: 'device A' }, latest_telemetry: {} }));
  await tick();
  assert.equal(h.nodes['axe-detail-title'].textContent, 'device B');
});

test('detail denied access displays access state instead of invented device values', async () => {
  const h = harness([], { authFetch: async () => response(403, { error: 'forbidden' }) });
  const api = load(h, ['49-axe-fleet.js'], '{openAxeDetail}');
  api.openAxeDetail('A'); await tick();
  assert.match(h.nodes['axe-detail-body'].textContent, /access|acesso|restricted/i);
  assert.doesNotMatch(h.nodes['axe-detail-body'].innerHTML, /OFFLINE/);
});

test('logout clears private detail and discards its pending response', async () => {
  const pending = deferred();
  const h = harness([], { fetch: async url => {
    if (url === '/api/auth/logout') return response(200, {});
    if (url.includes('/history')) return response(200, { device_id: 'A', history: historyRows() });
    return pending.promise;
  } });
  const api = load(h, ['38-billing-auth.js', '47-admin.js', '48-fleet-cc.js', '49-axe-fleet.js'], '{openAxeDetail,authSaveSession,authUpdateUi,authLogout}');
  api.authSaveSession({ access_token: 'synthetic-token', tenant_id: 'tenant-A', expires_at: Date.now() / 1000 + 3600 });
  api.authUpdateUi();
  api.openAxeDetail('A');
  await api.authLogout();
  assert.equal(h.nodes['axe-detail'].style.display, 'none');
  assert.equal(h.nodes['axe-detail-body'].innerHTML, '');
  pending.resolve(response(200, { device: { id: 'A', name: 'private A' }, latest_telemetry: {} }));
  await tick();
  assert.equal(h.nodes['axe-detail'].style.display, 'none');
  assert.doesNotMatch(h.nodes['axe-detail-title'].textContent + h.nodes['axe-detail-body'].textContent, /private A/);
  assert.equal(h.charts.filter(chart => !chart.destroyed).length, 0);
});


test('malformed summary differs from a confirmed empty fleet', async () => {
  const h = harness([], { authFetch: async () => response(200, {}) });
  const api = load(h, ['48-fleet-cc.js', '49-axe-fleet.js'], '{fetchFleetCommandCenter}');
  await api.fetchFleetCommandCenter();
  assert.match(h.nodes['lm-status-badge'].textContent, /error/i);
  assert.doesNotMatch(h.nodes['lm-workers-grid'].textContent, /no fleet workers registered/);
});

test('old failed summary cannot relabel the newer successful response as cached', async () => {
  const old = deferred(); let calls = 0;
  const h = harness([], { authFetch: () => ++calls === 1 ? old.promise : Promise.resolve(response(200, { devices: [] })) });
  const api = load(h, ['48-fleet-cc.js', '49-axe-fleet.js'], '{fetchFleetCommandCenter}');
  const pending = api.fetchFleetCommandCenter();
  await api.fetchFleetCommandCenter();
  old.resolve(response(503, {})); await pending;
  assert.equal(h.nodes['lm-status-badge'].textContent, 'EMPTY');
});

for (const failure of ['network', 'json', 'http']) {
  test('Admin ' + failure + ' failure does not hide successful datasets or claim zero degradation', async () => {
    const h = harness(['admin-deg-total', 'admin-deg-state', 'admin-deg-empty'], { fetch: async url => {
      if (url.includes('degradation-rate')) {
        if (failure === 'network') throw new Error('synthetic network failure');
        if (failure === 'json') return { ...response(200, {}), json: async () => { throw new Error('invalid JSON'); } };
        return response(503, {});
      }
      return response(200, url.includes('/sessions') ? { pool: { sessions_active: 7 } } : {});
    } });
    const api = load(h, ['47-admin.js'], '{fetchAdminData}');
    await api.fetchAdminData();
    assert.equal(h.nodes['admin-gate-badge'].textContent, 'partial');
    assert.equal(h.nodes['admin-sessions'].textContent, '7');
    assert.equal(h.nodes['admin-deg-total'].textContent, '—');
    assert.equal(h.nodes['admin-deg-state'].textContent, '—');
    assert.match(h.nodes['admin-error'].textContent, /degradation-rate/);
  });
}

test('late parsed Admin response cannot cross a session boundary', async () => {
  const parsed = deferred();
  const h = harness([], { fetch: async url => url.includes('/sessions')
    ? { ...response(200, {}), json: () => parsed.promise }
    : response(200, {}) });
  const api = load(h, ['47-admin.js', '48-fleet-cc.js', '49-axe-fleet.js'], '{fetchAdminData,syncOperationalEvidenceSession}');
  api.syncOperationalEvidenceSession('tenant-A', true);
  const pending = api.fetchAdminData();
  await tick();
  api.syncOperationalEvidenceSession('tenant-B', true);
  parsed.resolve({ pool: { sessions_active: 12345 } }); await pending;
  assert.equal(h.nodes['admin-sessions'].textContent, '—');
  assert.notEqual(h.nodes['admin-gate-badge'].textContent, 'ok');
});

test('late parsed device history cannot cross a session boundary', async () => {
  const parsed = deferred();
  const h = harness([], { authFetch: async () => ({ ...response(200, {}), json: () => parsed.promise }) });
  const api = load(h, ['49-axe-fleet.js'], '{loadDeviceHistoryChart,syncOperationalEvidenceSession}');
  api.syncOperationalEvidenceSession('tenant-A', true);
  const pending = api.loadDeviceHistoryChart('A'); await tick();
  api.syncOperationalEvidenceSession('tenant-B', true);
  parsed.resolve({ history: historyRows(9e12) }); await pending;
  assert.equal(h.charts.length, 0);
  assert.equal(h.nodes['axe-detail-chart-wrap'].style.display, 'none');
});

for (const history of [[{ ts: 'invalid', hashrate: 0 }], [{ ts: 1000, hashrate: null, temperature: null, efficiency_jth: null }]]) {
  test('unusable history remains unknown rather than empty or a fabricated point', async () => {
    const h = harness([], { authFetch: async () => response(200, { history }) });
    const api = load(h, ['49-axe-fleet.js'], '{loadDeviceHistoryChart}');
    await api.loadDeviceHistoryChart('A');
    assert.match(historyStatus(h), /unknown/);
    assert.equal(h.charts.length, 0);
    assert.equal(h.nodes['axe-detail-chart'].hidden, true);
  });
}

test('unknown Fleet metrics differ from observed zero, and booleans are not measurements', () => {
  const h = harness();
  const agg = load(h, ['48-fleet-cc.js'], '_ccKpiAgg');
  for (const hashrate_hs of [null, undefined, false, 'NOT AVAILABLE']) {
    assert.equal(agg([{ status: 'ONLINE', _telemetry: { hashrate_hs } }]).totalHr, null);
  }
  const zero = agg([{ status: 'ONLINE', _telemetry: { hashrate_hs: 0, power_watts: 0 } }]);
  assert.equal(zero.totalHr, 0); assert.equal(zero.totalPowerW, 0);
  assert.equal(agg([{ status: 'ONLINE', _telemetry: {} }]).totalPowerW, null);
});

for (const status of ['ONLINE', 'HASHING', 'WARNING']) {
  test('Fleet KPI DOM includes reachable ' + status + ' without changing its status bucket', async () => {
    const fields = { fccSummaryHr: 'hr', fccSummaryOnline: 'online', fccSummaryWarn: 'warn',
      fccSummaryOffline: 'offline', fccSummaryTemp: 'temp', fccSummaryPower: 'power',
      fccSummaryEff: 'eff', fccSummaryPing: 'ping' };
    const h = harness(Object.values(fields), { authFetch: async () => response(200, { devices: [{
      id: 'synthetic-reachable', name: 'Synthetic device', status, capabilities: [], latency_ms: 20,
      _telemetry: { hashrate_hs: 1e12, temperature: 60, power_watts: 100, efficiency_jth: 25,
        shares_accepted: 9, shares_rejected: 1, shares_stale: 2 },
    }] }) });
    for (const [key, id] of Object.entries(fields)) h.sandbox.dom[key] = h.nodes[id];
    const api = load(h, ['48-fleet-cc.js', '49-axe-fleet.js'], '{fetchFleetCommandCenter}');
    await api.fetchFleetCommandCenter();
    assert.equal(h.nodes.temp.textContent, '60.0°C');
    assert.equal(h.nodes.power.textContent, '0.10 kW');
    assert.equal(h.nodes.eff.textContent, '25.0 J/TH');
    assert.equal(h.nodes.ping.textContent, '20ms');
    assert.equal(h.nodes.online.textContent, status === 'WARNING' ? '0' : '1');
    assert.equal(h.nodes.warn.textContent, status === 'WARNING' ? '1' : '0');
    assert.equal(h.nodes.offline.textContent, '0');
  });
}

test('Fleet KPI DOM preserves measured zero power, temperature and rounded latency', async () => {
  const fields = { fccSummaryHr: 'hr', fccSummaryTemp: 'temp', fccSummaryPower: 'power', fccSummaryPing: 'ping' };
  const h = harness(Object.values(fields), { authFetch: async () => response(200, { devices: [{
    id: 'synthetic-zero', name: 'Zero measurements', status: 'HASHING', capabilities: [], latency_ms: 0,
    _telemetry: { hashrate_hs: 0, temperature: 0, power_watts: 0 },
  }] }) });
  for (const [key, id] of Object.entries(fields)) h.sandbox.dom[key] = h.nodes[id];
  const api = load(h, ['48-fleet-cc.js', '49-axe-fleet.js'], '{fetchFleetCommandCenter}');
  await api.fetchFleetCommandCenter();
  assert.equal(h.nodes.hr.textContent, '0.00 H/s');
  assert.equal(h.nodes.power.textContent, '0.00 kW');
  assert.equal(h.nodes.temp.textContent, '0.0°C');
  assert.equal(h.nodes.ping.textContent, '0ms');
});

test('Admin reset clears analytics KPIs and private table entries', () => {
  const ids = ['boots', 'dau', 'wau', 'modules', 'top-module'].map(id => 'admin-analytics-' + id);
  const h = harness([...ids, 'admin-analytics', 'admin-analytics-table-body']);
  ids.forEach(id => { h.nodes[id].textContent = 'private-A'; });
  h.nodes['admin-analytics-table-body'].innerHTML = '<tr>private-A</tr>';
  const reset = load(h, ['47-admin.js'], 'resetAdminEvidence');
  reset();
  ids.forEach(id => assert.equal(h.nodes[id].textContent, '—'));
  assert.equal(h.nodes['admin-analytics-table-body'].innerHTML, '');
});

for (const boundary of ['logout', 'login B', 'late JSON']) {
  test('late auth refresh cannot restore A after ' + boundary, async () => {
    const pending = deferred(); const parsed = deferred();
    const h = harness([], { fetch: async url => url.includes('/refresh') ? pending.promise : response(200, {}), syncOperationalEvidenceSession() {} });
    const api = load(h, ['38-billing-auth.js'], '{authSaveSession,authLoadSession,authRefresh,authLogout}');
    api.authSaveSession({ access_token: 'A', refresh_token: 'refresh-A', tenant_id: 'A' });
    const refreshing = api.authRefresh();
    if (boundary === 'late JSON') { pending.resolve({ ...response(200, {}), json: () => parsed.promise }); await tick(); }
    if (boundary === 'login B') api.authSaveSession({ access_token: 'B', refresh_token: 'refresh-B', tenant_id: 'B' });
    else await api.authLogout();
    const data = { access_token: 'resurrected-A', expires_at: 9999999999, tenant_id: 'A' };
    if (boundary === 'late JSON') parsed.resolve(data); else pending.resolve(response(200, data));
    assert.equal(await refreshing, false);
    assert.equal(api.authLoadSession()?.access_token || null, boundary === 'login B' ? 'B' : null);
  });
}

test('late login cannot restore a session after logout', async () => {
  const pending = deferred();
  const h = harness([], { fetch: () => pending.promise, syncOperationalEvidenceSession() {} });
  const api = load(h, ['38-billing-auth.js'], '{authLogin,authLogout,authLoadSession}');
  const login = api.authLogin('synthetic-key');
  await api.authLogout();
  pending.resolve(response(200, { access_token: 'A', refresh_token: 'refresh-A', tenant_id: 'A' }));
  assert.equal((await login).ok, false); assert.equal(api.authLoadSession(), null);
});

for (const boundary of ['response', 'JSON']) {
  test('late primary Fleet health cannot repopulate tenant A after switching to B (' + boundary + ')', async () => {
    const pending = deferred(); const parsed = deferred();
    const h = harness(['axe-grid'], { authFetch: () => pending.promise, _lastSnapshot: {}, countUpValue() {}, renderOperationalOverview() {}, fetchFleetCommandCenter() {} });
    h.sandbox.dom.axeGrid = h.nodes['axe-grid'];
    const api = load(h, ['49-axe-fleet.js'], '{fetchAxeFleet,syncOperationalEvidenceSession}');
    api.syncOperationalEvidenceSession('A', true);
    const fetching = api.fetchAxeFleet();
    if (boundary === 'JSON') { pending.resolve({ ...response(200, {}), json: () => parsed.promise }); await tick(); }
    api.syncOperationalEvidenceSession('B', true);
    const data = { fleet_stats: { total_devices: 1 }, device_health: [{ id: 'private-A', name: 'private-A', capabilities: [], telemetry: {} }] };
    if (boundary === 'JSON') parsed.resolve(data); else pending.resolve(response(200, data));
    await fetching;
    assert.doesNotMatch(h.nodes['axe-grid'].innerHTML, /private-A/);
    assert.equal(h.sandbox._operationalFleetData, null);
  });
}

test('an in-flight authenticated request cannot retry under another tenant', async () => {
  const pending = deferred(); let calls = 0;
  const h = harness([], { fetch: () => { calls++; return pending.promise; }, syncOperationalEvidenceSession() {} });
  const api = load(h, ['38-billing-auth.js'], '{authSaveSession,authFetch}');
  api.authSaveSession({ access_token: 'A', refresh_token: 'refresh-A', tenant_id: 'A', expires_at: 9999999999 });
  const request = api.authFetch('/synthetic-read-only');
  api.authSaveSession({ access_token: 'B', refresh_token: 'refresh-B', tenant_id: 'B', expires_at: 9999999999 });
  pending.resolve(response(401, {}));
  await assert.rejects(request, /Session changed/); assert.equal(calls, 1);
});

test('a single zero within a sparse history remains visible without bridging gaps', async () => {
  const h = harness([], { authFetch: async () => response(200, { history: [{ ts: 1000, hashrate: 0 }, { ts: 1060, hashrate: null }] }) });
  const loadHistory = load(h, ['49-axe-fleet.js'], 'loadDeviceHistoryChart');
  await loadHistory('A');
  assert.equal(h.charts[0].data.datasets[0].data[0], 0);
  assert.equal(h.charts[0].data.datasets[0].data[1], null);
  assert.ok(h.charts[0].data.datasets[0].pointRadius > 0);
});

for (const boundary of ['existing token', 'late JSON', 'late network error', 'late revoke JSON']) {
  test('agent credential panel clears on session change: ' + boundary, async () => {
    const ids = ['axe-agent-panel', 'axe-agent-btn', 'axe-agent-gen', 'axe-agent-status', 'axe-agent-token-row', 'axe-agent-token', 'axe-agent-docker', 'axe-agent-one-liner', 'axe-revoke', 'axe-revoke-confirm', 'axe-revoke-do', 'axe-revoke-open', 'axe-revoke-status'];
    const pending = deferred(); const parsed = deferred();
    const h = harness(ids, { _lastSnapshot: {}, renderOperationalOverview() {}, authFetch: () => pending.promise });
    const api = load(h, ['49-axe-fleet.js'], '{initAxeAgentPanel,syncOperationalEvidenceSession}');
    api.initAxeAgentPanel(); api.syncOperationalEvidenceSession('A', true);
    const token = h.nodes['axe-agent-token'];
    if (boundary === 'existing token') {
      token.value = 'SYNTHETIC-A'; h.nodes['axe-agent-token-row'].style.display = 'block';
      h.nodes['axe-agent-docker'].textContent = 'SYNTHETIC-A';
      h.nodes['axe-agent-one-liner'].textContent = 'SYNTHETIC-A';
      api.syncOperationalEvidenceSession('B', true);
    } else {
      if (boundary === 'late revoke JSON') h.nodes['axe-revoke-open'].listeners.click();
      const request = h.nodes[boundary === 'late revoke JSON' ? 'axe-revoke-do' : 'axe-agent-gen'].listeners.click();
      if (boundary !== 'late network error') { pending.resolve({ ...response(200, {}), json: () => parsed.promise }); await tick(); }
      api.syncOperationalEvidenceSession('B', true);
      if (boundary === 'late network error') pending.resolve(Promise.reject(new Error('synthetic failure')));
      else parsed.resolve({ token: 'SYNTHETIC-LATE-A', tenant_id: 'A', server_url: 'https://example.invalid', success: true, active_epoch: 1 });
      await request;
    }
    assert.equal(token.value, '');
    assert.equal(h.nodes['axe-agent-token-row'].style.display, 'none');
    assert.equal(h.nodes['axe-agent-panel'].style.display, 'none');
    assert.equal(h.nodes['axe-agent-docker'].textContent, '');
    assert.equal(h.nodes['axe-agent-one-liner'].textContent, '');
    assert.equal(h.nodes['axe-agent-status'].textContent, '');
    assert.equal(h.nodes['axe-revoke'].dataset.phase, 'idle');
  });
}

for (const devices of [[null], [{}]]) {
  test('malformed first Fleet summary cannot become a cached snapshot', async () => {
    const h = harness([], { authFetch: async () => response(200, { devices }) });
    const fetchSummary = load(h, ['48-fleet-cc.js', '49-axe-fleet.js'], 'fetchFleetCommandCenter');
    await fetchSummary();
    assert.equal(h.nodes['lm-status-badge'].textContent, 'ERROR');
    assert.doesNotMatch(h.nodes['lm-workers-grid'].textContent, /loading|cached/i);
  });
}

for (const [name, stats, expected] of [
  ['missing counts', {}, 'UNKNOWN'],
  ['missing online count', { total_devices: 1, warning: 0, offline: 0 }, 'UNKNOWN'],
  ['boolean online count', { total_devices: 1, online: true, warning: 0, offline: 0 }, 'UNKNOWN'],
  ['confirmed empty', { total_devices: 0, online: 0, warning: 0, offline: 0 }, 'NO DEVICES'],
  ['confirmed online', { total_devices: 1, online: 1, warning: 0, offline: 0 }, 'ALL ONLINE'],
]) {
  test('primary Fleet count evidence: ' + name, () => {
    const h = harness(['grid', 'status', 'count', 'online', 'warning', 'offline'], { countUpValue: (el, value) => { el.textContent = value; } });
    Object.assign(h.sandbox.dom, { axeGrid: h.nodes.grid, axeFleetStatusBadge: h.nodes.status, axeFleetCountBadge: h.nodes.count, axeSummaryOnline: h.nodes.online, axeSummaryWarning: h.nodes.warning, axeSummaryOffline: h.nodes.offline });
    const render = load(h, ['49-axe-fleet.js'], 'renderAxeFleet');
    render({ fleet_stats: stats, device_health: [] });
    assert.equal(h.nodes.status.textContent, expected);
    if (expected === 'UNKNOWN') {
      assert.equal(h.nodes.online.textContent, '—');
      assert.doesNotMatch(h.nodes.status.className, /green/);
      assert.doesNotMatch(h.nodes.status.textContent + h.nodes.count.textContent, /undefined|NaN/);
    } else assert.equal(h.nodes.online.textContent, String(stats.online));
  });
}

for (const boundary of ['missing before first frame', 'missing after first frame', 'reset before first frame', 'reset after first frame', 'reduced motion replacement']) {
  test('real pending count animation cannot restore stale Fleet evidence: ' + boundary, () => {
    let now = 0; let reduced = false; let nextFrame = 0;
    const frames = new Map(); const queued = [];
    const h = harness(['grid', 'status', 'count', 'online', 'warning', 'offline'], {
      performance: { now: () => now },
      window: { matchMedia: () => ({ matches: reduced }), addEventListener() {} },
      requestAnimationFrame: callback => { const id = ++nextFrame; frames.set(id, callback); queued.push(callback); return id; },
      cancelAnimationFrame: id => frames.delete(id), _lastSnapshot: {}, renderOperationalOverview() {},
    });
    Object.assign(h.sandbox.dom, { axeGrid: h.nodes.grid, axeFleetStatusBadge: h.nodes.status, axeFleetCountBadge: h.nodes.count, axeSummaryOnline: h.nodes.online, axeSummaryWarning: h.nodes.warning, axeSummaryOffline: h.nodes.offline });
    const source = fragment('40-app-logic.js');
    h.sandbox.countUpValue = vm.runInNewContext('(function(){' + source.slice(0, source.indexOf('  // ── Skeleton loading')) + '; return countUpValue;})()', h.sandbox);
    const api = load(h, ['49-axe-fleet.js'], '{renderAxeFleet,resetAxeFleetEvidence}');
    api.renderAxeFleet({ fleet_stats: { total_devices: 5, online: 5, warning: 0, offline: 0 }, device_health: [] });
    assert.ok(frames.size > 0);
    if (boundary.includes('after first')) { now = 100; [...frames.values()].forEach(callback => callback()); }
    if (boundary.startsWith('reset')) api.resetAxeFleetEvidence();
    else {
      if (boundary.startsWith('reduced')) reduced = true;
      api.renderAxeFleet({ fleet_stats: { total_devices: 5, warning: 0, offline: 0 }, device_health: [] });
    }
    now = 1000;
    // Even a callback captured before cancellation must have lost ownership.
    queued.forEach(callback => callback());
    assert.equal(h.nodes.online.textContent, '—');
    assert.equal(h.nodes.status.textContent, boundary.startsWith('reset') ? '—' : 'UNKNOWN');
  });
}

for (const [name, invalid] of [
  ['array stats', { fleet_stats: [], device_health: [] }],
  ['null device', { fleet_stats: {}, device_health: [null] }],
  ['missing identity', { fleet_stats: {}, device_health: [{}] }],
]) {
  for (const cached of [false, true]) test('invalid primary Fleet schema keeps the last valid snapshot: ' + name + ', cached=' + cached, async () => {
    const good = { fleet_stats: { total_devices: 0, online: 0, warning: 0, offline: 0 }, device_health: [] };
    let payload = cached ? good : invalid;
    const h = harness(['grid', 'status'], { authFetch: async () => response(200, payload), countUpValue: (el, value) => { el.textContent = value; }, _lastSnapshot: {}, _operationalFleetData: null, renderOperationalOverview() {}, fetchFleetCommandCenter() {} });
    Object.assign(h.sandbox.dom, { axeGrid: h.nodes.grid, axeFleetStatusBadge: h.nodes.status });
    const api = load(h, ['49-axe-fleet.js'], '{fetchAxeFleet}');
    if (cached) { await api.fetchAxeFleet(); payload = invalid; }
    await api.fetchAxeFleet();
    assert.equal(h.nodes.status.textContent, cached ? 'CACHED · ERROR' : 'ERROR');
    assert.equal(h.sandbox._operationalFleetData, cached ? good : null);
  });
}

(async () => {
  let failures = 0;
  for (const { name, run } of tests) {
    try { await run(); console.log('PASS ' + name); }
    catch (error) { failures++; console.error('FAIL ' + name + '\n' + error.stack); }
  }
  console.log(`${tests.length - failures} passed, ${failures} failed`);
  process.exitCode = failures ? 1 : 0;
})();
