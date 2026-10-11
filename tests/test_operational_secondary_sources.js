/** Issue #757: real Market, Wallet, Support and advisory consumers, no network. */
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const cases = [];
const test = (name, run) => cases.push({ name, run });
const tick = () => new Promise(resolve => setImmediate(resolve));
const reply = (status, payload) => ({ status, ok: status >= 200 && status < 300, json: async () => payload });
const errorState = /error|erro|falha|failed|failure|malformed|unavailable|indispon|invalid/i;
const accessState = /access|acesso|restricted|required|restrito/i;
const emptyState = /empty|no .*history|no .*methods|no saved wallets|no .*audit|sem |nenhuma|nenhum|vazi|0 providers/i;

function deferred() {
  let resolve;
  const promise = new Promise(done => { resolve = done; });
  return { resolve, promise };
}
class Element {
  constructor(id = '') {
    this.id = id; this.hidden = false; this.style = {}; this.dataset = {};
    this.children = []; this.html = ''; this.attributes = {};
    const classes = new Set();
    this.classList = {
      toggle(name, force) { const added = force === undefined ? !classes.has(name) : !!force; if (added) classes.add(name); else classes.delete(name); return added; },
      add(...names) { names.forEach(name => classes.add(name)); },
      remove(...names) { names.forEach(name => classes.delete(name)); },
      contains: name => classes.has(name),
    };
  }
  set innerHTML(value) { this.html = String(value); this.children = []; }
  get innerHTML() { return this.html + this.children.map(child => child.innerHTML).join(''); }
  set textContent(value) { this.innerHTML = value; }
  get textContent() { return this.innerHTML.replace(/<[^>]*>/g, ''); }
  setAttribute(name, value) { this.attributes[name] = String(value); }
  getAttribute(name) { return this.attributes[name] || null; }
  removeAttribute(name) { delete this.attributes[name]; }
  addEventListener() {}
  appendChild(child) { this.children.push(child); return child; }
  querySelectorAll() { return []; }
  querySelector() { return null; }
  getContext() { return { canvas: this }; }
}
const nodeIds = [
  'mkt-trend-count', 'mkt-trend-legend', 'mkt-trend-chart', 'wallet-history-list',
  'support-bar-methods', 'support-modal-grid', 'support-modal-manifesto', 'support-ln-address',
  'ap-recs-list', 'ap-recs-badge', 'ap-audit-wrap', 'ap-audit-list', 'ap-audit-count',
  'ap-dr-now-list', 'ap-dr-now-count', 'ap-dr-replay-list', 'ap-dr-replay-count',
  'axe-detail', 'axe-detail-title', 'axe-detail-body', 'axe-detail-chart-wrap',
  'axe-detail-chart', 'axe-detail-chart-count', 'axe-detail-chart-status',
  'admin-error', 'admin-gate-badge', 'lm-status-badge', 'lm-workers-grid',
  'ap-armed-btn', 'ap-armed-label', 'ap-armed-dot', 'ap-budget-badge',
  'ap-auto-btn', 'ap-auto-label', 'ap-auto-dot', 'ap-auto-pro-badge',
  'ap-arm-modal', 'ap-auto-modal', 'ap-arm-type', 'ap-auto-type',
  'ap-arm-consent', 'ap-auto-consent',
];
function harness() {
  const nodes = Object.fromEntries(nodeIds.map(id => [id, new Element(id)]));
  nodes['support-ln-address'].textContent = '—';
  const charts = [];
  const storage = new Map();
  let handler = async url => {
    if (url === '/api/support-config') return reply(200, { methods: [], manifesto: '' });
    if (url === '/api/donations') return reply(200, { donations: [] });
    throw new Error('unexpected fixture request: ' + url);
  };
  const dispatch = (...args) => handler(...args);
  class Chart {
    constructor(context, config) {
      this.canvas = context.canvas; this.data = config.data; this.options = config.options;
      this.config = config; this.destroyed = false; charts.push(this);
    }
    destroy() { this.destroyed = true; }
    update() {}
    static getChart(canvas) { return charts.findLast(chart => chart.canvas === canvas && !chart.destroyed); }
  }
  const document = {
    getElementById: id => nodes[id] || null, addEventListener() {},
    querySelector: () => null, querySelectorAll: () => [],
    createElement: () => new Element(), body: new Element(),
  };
  const sandbox = {
    console: { log() {}, warn() {}, error() {} }, document, dom: {}, Chart,
    Date, Map, Set, AbortController, URLSearchParams, setTimeout, clearTimeout,
    window: { matchMedia: () => ({ matches: true }), addEventListener() {} },
    navigator: {}, fetch: dispatch, authFetch: dispatch,
    localStorage: {
      getItem: key => storage.get(key) || null,
      setItem: (key, value) => storage.set(key, String(value)),
      removeItem: key => storage.delete(key),
    },
    cssVar: () => 'rgb(20,30,40)', setHtmlIfChanged: (node, html) => { node.innerHTML = html; },
    skelShow() {}, skelHide() {}, logMessage() {},
    _ccLastFleet: [], _ccView: 'grid', _ccHrSeries: [], _ccHrHist: {},
  };
  return { nodes, charts, sandbox, setHandler: fn => { handler = fn; } };
}
function source(name) {
  const relative = 'static/src/' + name;
  return process.env.C65_EVIDENCE_TEST_REF
    ? execFileSync('git', ['show', process.env.C65_EVIDENCE_TEST_REF + ':' + relative], { cwd: root, encoding: 'utf8' })
    : fs.readFileSync(path.join(root, relative), 'utf8');
}
async function load(h, fragments, exports) {
  const code = ['10-core-fmt.js', '30-core-escape.js', ...fragments].map(source).join('\n');
  const api = vm.runInNewContext('(function(){\n' + code + '\nreturn (' + exports + ');})()', h.sandbox, { timeout: 5000 });
  await tick(); // Complete the real Support/Donations boot requests using explicit fixtures.
  return api;
}
function failure(kind) {
  if (kind === 'http') return Promise.resolve(reply(503, {}));
  if (kind === 'access') return Promise.resolve(reply(403, {}));
  if (kind === 'network') return Promise.reject(new Error('fixture network failure'));
  if (kind === 'json') return Promise.resolve({ status: 200, ok: true, json: async () => { throw new SyntaxError('fixture malformed JSON'); } });
  return Promise.resolve(reply(200, {})); // Invalid schema, not a legitimate empty dataset.
}
const fullSessionFragments = ['38-billing-auth.js', '41-automations.js', '45-market.js', '47-admin.js', '48-fleet-cc.js', '49-axe-fleet.js', '37-wallet-support.js'];

for (const kind of ['http', 'access', 'network', 'json', 'schema']) {
  test('Market trend exposes ' + kind + ' and recovers to explicit empty history', async () => {
    const h = harness(); const api = await load(h, ['45-market.js'], '{loadMarketTrend}');
    h.setHandler(() => failure(kind));
    assert.equal(await api.loadMarketTrend(), false);
    assert.match(h.nodes['mkt-trend-count'].textContent + h.nodes['mkt-trend-legend'].textContent, kind === 'access' ? accessState : errorState);
    h.setHandler(async () => reply(200, { providers: {}, updated_at: 0 }));
    assert.equal(await api.loadMarketTrend(), true);
    assert.match(h.nodes['mkt-trend-count'].textContent + h.nodes['mkt-trend-legend'].textContent, emptyState);
    assert.doesNotMatch(h.nodes['mkt-trend-count'].textContent, errorState);
  });
}
test('Market preserves zero and displays a sparse provider single observation', async () => {
  const h = harness(); const api = await load(h, ['45-market.js'], '{loadMarketTrend}');
  h.setHandler(async () => reply(200, { updated_at: 1060, providers: {
    Sparse: [{ ts: 1000, price_btc_per_th_day: 0 }],
    Other: [{ ts: 1060, price_btc_per_th_day: 1e-6 }],
  } }));
  assert.equal(await api.loadMarketTrend(), true);
  const sparse = h.charts.at(-1).data.datasets.find(dataset => dataset.label === 'Sparse');
  assert.equal(sparse.data.filter(value => value !== null).length, 1);
  assert.equal(sparse.data[0], 0);
  const radius = Array.isArray(sparse.pointRadius) ? sparse.pointRadius[0] : sparse.pointRadius;
  assert.ok(radius > 0, 'one real observation needs a visible point even with multiple global labels');
});

test('Market invalid retained observations are UNKNOWN, never legitimate EMPTY', async () => {
  const h = harness(); const api = await load(h, ['45-market.js'], '{loadMarketTrend}');
  h.setHandler(async () => reply(200, { providers: { Invalid: [{ ts: 1000, price_btc_per_th_day: 'garbage' }] } }));
  assert.equal(await api.loadMarketTrend(), false);
  assert.match(h.nodes['mkt-trend-count'].textContent, /UNKNOWN|invalid/i);
  assert.doesNotMatch(h.nodes['mkt-trend-count'].textContent, /EMPTY/i);
  assert.equal(h.charts.filter(chart => !chart.destroyed).length, 0);
  assert.equal(h.nodes['mkt-trend-chart'].hidden, true);
});

test('Market unrepresentable timestamp is UNKNOWN and cannot produce a live chart', async () => {
  const h = harness(); const api = await load(h, ['45-market.js'], '{loadMarketTrend}');
  h.setHandler(async () => reply(200, { providers: { A: [{ ts: 1e308, price_btc_per_th_day: 1e-6 }] } }));
  assert.equal(await api.loadMarketTrend(), false);
  assert.match(h.nodes['mkt-trend-count'].textContent, /UNKNOWN|invalid/i);
  assert.doesNotMatch(h.nodes['mkt-trend-count'].textContent + h.nodes['mkt-trend-legend'].textContent, /LIVE|NaN:NaN/i);
  assert.equal(h.charts.filter(chart => !chart.destroyed).length, 0);
  assert.equal(h.nodes['mkt-trend-chart'].hidden, true);
});

for (const kind of ['http', 'access', 'network', 'json', 'schema']) {
  test('Wallet history exposes ' + kind + ' separately from successful empty', async () => {
    const h = harness(); const api = await load(h, ['37-wallet-support.js'], '{fetchWalletHistory}');
    h.setHandler(() => failure(kind)); await api.fetchWalletHistory();
    assert.match(h.nodes['wallet-history-list'].textContent, kind === 'access' ? accessState : errorState);
    h.setHandler(async () => reply(200, { success: true, history: [] }));
    await api.fetchWalletHistory();
    assert.match(h.nodes['wallet-history-list'].textContent, emptyState);
    assert.doesNotMatch(h.nodes['wallet-history-list'].textContent, errorState);
  });
}
test('Wallet real history consumer renders entries and logout rejects a pending JSON body', async () => {
  const h = harness();
  const api = await load(h, fullSessionFragments, '{fetchWalletHistory,authSaveSession,authUpdateUi,authLogout}');
  api.authSaveSession({ access_token: 'fixture', tenant_id: 'tenant-A', expires_at: Date.now() / 1000 + 3600 }); api.authUpdateUi();
  h.setHandler(async () => reply(200, { success: true, history: [{ address: 'private-address-111', worker: 'private-worker' }] }));
  await api.fetchWalletHistory();
  assert.match(h.nodes['wallet-history-list'].textContent, /private-worker/);
  const body = deferred();
  h.setHandler(async url => url === '/api/auth/logout' ? reply(200, {}) : { status: 200, ok: true, json: () => body.promise });
  const pending = api.fetchWalletHistory(); await tick();
  await api.authLogout();
  assert.doesNotMatch(h.nodes['wallet-history-list'].textContent, /private-worker/);
  body.resolve({ success: true, history: [{ address: 'late-private-address', worker: 'late-private-worker' }] });
  await pending;
  assert.doesNotMatch(h.nodes['wallet-history-list'].textContent, /late-private/);
});

for (const dataset of ['recommendations', 'audit']) {
  for (const kind of ['http', 'access', 'network', 'json', 'schema']) {
    test('AutoPilot ' + dataset + ' exposes independent ' + kind + ' then recovers', async () => {
      const h = harness(); const api = await load(h, ['41-automations.js'], '{_apLoadRecs}');
      h.setHandler(url => {
        const selected = url.includes('/audit') ? 'audit' : 'recommendations';
        return selected === dataset ? failure(kind) : Promise.resolve(reply(200, { [selected]: [] }));
      });
      await api._apLoadRecs();
      const failedId = dataset === 'audit' ? 'ap-audit-list' : 'ap-recs-list';
      assert.match(h.nodes[failedId].textContent, kind === 'access' ? accessState : errorState);
      if (dataset === 'audit') assert.notEqual(h.nodes['ap-audit-wrap'].style.display, 'none', 'failed audit must remain visible');
      h.setHandler(async url => reply(200, { [url.includes('/audit') ? 'audit' : 'recommendations']: [] }));
      await api._apLoadRecs();
      assert.match(h.nodes[failedId].textContent, emptyState);
      assert.doesNotMatch(h.nodes[failedId].textContent, errorState);
    });
  }
}
for (const dataset of ['now', 'replay']) {
  for (const kind of ['http', 'access', 'network', 'json', 'schema']) {
    test('AutoPilot dry-run ' + dataset + ' exposes independent ' + kind + ' then recovers', async () => {
      const h = harness(); const api = await load(h, ['41-automations.js'], '{_apDrLoad}');
      h.setHandler(url => {
        const selected = url.includes('/replay') ? 'replay' : 'now';
        return selected === dataset ? failure(kind) : Promise.resolve(reply(200, selected === 'now' ? { actions: [] } : { per_rule: [], total_fires: 0 }));
      });
      await api._apDrLoad();
      const id = 'ap-dr-' + dataset + '-list';
      assert.match(h.nodes[id].textContent, kind === 'access' ? accessState : errorState);
      assert.doesNotMatch(h.nodes[id].textContent, /Nenhuma regra/i);
      h.setHandler(async url => reply(200, url.includes('/replay') ? { per_rule: [], total_fires: 0 } : { actions: [] }));
      await api._apDrLoad();
      assert.match(h.nodes[id].textContent, /Nenhuma regra/i);
      assert.doesNotMatch(h.nodes[id].textContent, errorState);
    });
  }
}

for (const dataset of ['recommendations', 'audit', 'now', 'replay']) {
  test('AutoPilot ' + dataset + ' rejects null items as invalid schema, then recovers', async () => {
    const h = harness(); const api = await load(h, ['41-automations.js'], '{_apLoadRecs,_apDrLoad}');
    const selected = url => url.includes('/audit') ? 'audit' : url.includes('/replay') ? 'replay' : url.includes('/dry-run') ? 'now' : 'recommendations';
    h.setHandler(async url => {
      const current = selected(url);
      const key = { recommendations: 'recommendations', audit: 'audit', now: 'actions', replay: 'per_rule' }[current];
      return reply(200, { [key]: current === dataset ? [null] : [] });
    });
    const read = dataset === 'recommendations' || dataset === 'audit' ? api._apLoadRecs : api._apDrLoad;
    await read();
    const id = { recommendations: 'ap-recs-list', audit: 'ap-audit-list', now: 'ap-dr-now-list', replay: 'ap-dr-replay-list' }[dataset];
    assert.match(h.nodes[id].textContent, errorState);
    assert.doesNotMatch(h.nodes[id].textContent, /Loading|Nenhuma regra|Sem recomendações/i);
    h.setHandler(async url => {
      const current = selected(url);
      const key = { recommendations: 'recommendations', audit: 'audit', now: 'actions', replay: 'per_rule' }[current];
      return reply(200, { [key]: [], total_fires: 0 });
    });
    await read();
    assert.match(h.nodes[id].textContent, emptyState);
    assert.doesNotMatch(h.nodes[id].textContent, errorState);
  });
}

for (const kind of ['http', 'access', 'network', 'json', 'schema']) {
  test('Support configuration exposes ' + kind + ' and recovers to explicit empty', async () => {
    const h = harness(); const api = await load(h, ['37-wallet-support.js'], '{renderSupportMethods}');
    h.setHandler(() => failure(kind));
    await api.renderSupportMethods(); await tick();
    assert.match(h.nodes['support-bar-methods'].textContent + h.nodes['support-modal-grid'].textContent, kind === 'access' ? accessState : errorState);
    h.setHandler(async () => reply(200, { methods: [], manifesto: '' }));
    await api.renderSupportMethods(); await tick();
    assert.match(h.nodes['support-bar-methods'].textContent + h.nodes['support-modal-grid'].textContent, emptyState);
    assert.doesNotMatch(h.nodes['support-bar-methods'].textContent, errorState);
  });
}
test('Support real consumer renders supplied method without inventing payment data', async () => {
  const h = harness(); const api = await load(h, ['37-wallet-support.js'], '{renderSupportMethods}');
  h.setHandler(async () => reply(200, { manifesto: 'Fixture manifesto', methods: [
    { id: 'btc', label: 'Fixture Bitcoin', address: 'synthetic-support-address', color: '#abc', icon: 'B' },
  ] }));
  await api.renderSupportMethods(); await tick();
  assert.match(h.nodes['support-bar-methods'].textContent, /synthetic-support-address/);
  assert.match(h.nodes['support-modal-grid'].textContent, /Fixture Bitcoin/);
  assert.match(h.nodes['support-modal-manifesto'].textContent, /Fixture manifesto/);
});

test('Support delayed JSON from an older request cannot replace newer configuration', async () => {
  const h = harness(); const api = await load(h, ['37-wallet-support.js'], '{renderSupportMethods}');
  const olderBody = deferred(); const newerBody = deferred();
  let calls = 0;
  h.setHandler(async () => ({ status: 200, ok: true, json: () => ++calls === 1 ? olderBody.promise : newerBody.promise }));
  const older = api.renderSupportMethods(); await tick();
  const newer = api.renderSupportMethods(); await tick();
  const config = label => ({ manifesto: 'Manifesto ' + label, methods: [{ id: 'btc', label, address: 'synthetic-' + label }] });
  newerBody.resolve(config('NEW')); await newer; await tick();
  olderBody.resolve(config('OLD')); await older; await tick();
  assert.match(h.nodes['support-bar-methods'].textContent, /synthetic-NEW/);
  assert.doesNotMatch(h.nodes['support-bar-methods'].textContent + h.nodes['support-modal-grid'].textContent, /synthetic-OLD/);
  assert.equal(h.nodes['support-modal-manifesto'].textContent, 'Manifesto NEW');
});

test('Support recipient refresh shares configuration ownership and rejects its older response', async () => {
  const h = harness(); const api = await load(h, ['37-wallet-support.js'], '{renderSupportMethods,_populateLNAddress}');
  const oldBody = deferred(); let calls = 0;
  const config = suffix => ({ methods: [{ id: 'lightning', label: 'Fixture Lightning', address: 'synthetic-recipient-' + suffix }] });
  h.setHandler(async () => ++calls === 1
    ? { status: 200, ok: true, json: () => oldBody.promise }
    : reply(200, config('NEW')));
  const older = api._populateLNAddress(); await tick();
  await api.renderSupportMethods(); await tick();
  assert.equal(h.nodes['support-ln-address'].textContent, 'synthetic-recipient-NEW');
  oldBody.resolve(config('OLD')); await older; await tick();
  assert.equal(h.nodes['support-ln-address'].textContent, 'synthetic-recipient-NEW');
  assert.doesNotMatch(h.nodes['support-bar-methods'].textContent + h.nodes['support-modal-grid'].textContent, /synthetic-recipient-OLD/);
});

test('AutoPilot delayed recommendations cannot overwrite fresh canonical armed OFF status', async () => {
  const h = harness(); const api = await load(h, ['41-automations.js'], '{_apLoadRecs,_apRefreshStatus}');
  const body = deferred();
  h.setHandler(async url => {
    if (url === '/api/automation/status') return reply(200, { armed: false });
    if (url.includes('/audit')) return reply(200, { audit: [] });
    return { status: 200, ok: true, json: () => body.promise };
  });
  const pending = api._apLoadRecs(); await tick();
  await api._apRefreshStatus();
  assert.equal(h.nodes['ap-armed-label'].textContent, 'OFF');
  assert.equal(h.nodes['ap-armed-btn'].disabled, false);
  body.resolve({ recommendations: [], armed: true }); await pending;
  assert.match(h.nodes['ap-recs-list'].textContent, emptyState);
  assert.equal(h.nodes['ap-armed-label'].textContent, 'OFF');
  assert.equal(h.nodes['ap-armed-btn'].disabled, false);
});

for (const control of ['armed', 'auto']) {
  test('AutoPilot ' + control + ' late status body cannot replace another tenant known OFF', async () => {
    const h = harness();
    const api = await load(h, fullSessionFragments, '{_apRefreshStatus,_apRefreshAutoStatus,authSaveSession,authUpdateUi}');
    const read = control === 'armed' ? api._apRefreshStatus : api._apRefreshAutoStatus;
    const prefix = control === 'armed' ? 'ap-armed' : 'ap-auto';
    const badge = control === 'armed' ? 'ap-budget-badge' : 'ap-auto-pro-badge';
    const payload = enabled => control === 'armed'
      ? { armed: enabled, max_actions_per_window: 8, actions_in_window: 0 }
      : { autonomous: enabled, pro: false, armed: false };
    const session = tenant => { api.authSaveSession({ access_token: 'fixture-' + tenant, tenant_id: tenant, expires_at: Date.now() / 1000 + 3600 }); api.authUpdateUi(); };
    session('tenant-A');
    h.setHandler(async () => reply(200, payload(true))); await read();
    assert.equal(h.nodes[prefix + '-label'].textContent, control === 'armed' ? 'ARM' : 'ON');
    assert.equal(h.nodes[prefix + '-btn'].disabled, false);
    ['ap-arm-modal', 'ap-auto-modal'].forEach(id => h.nodes[id].classList.add('modal--open'));
    ['ap-arm-type', 'ap-auto-type'].forEach(id => { h.nodes[id].value = 'fixture consent'; });
    ['ap-arm-consent', 'ap-auto-consent'].forEach(id => { h.nodes[id].checked = true; });
    const body = deferred();
    h.setHandler(async () => ({ status: 200, ok: true, json: () => body.promise }));
    const older = read(); await tick();
    session('tenant-B');
    for (const kind of ['armed', 'auto']) {
      const id = kind === 'armed' ? 'ap-armed' : 'ap-auto';
      assert.equal(h.nodes[id + '-label'].textContent, 'UNKNOWN');
      assert.equal(h.nodes[id + '-btn'].disabled, true);
    }
    assert.equal(h.nodes[badge].textContent, '—');
    ['ap-arm-modal', 'ap-auto-modal'].forEach(id => assert.equal(h.nodes[id].classList.contains('modal--open'), false));
    ['ap-arm-type', 'ap-auto-type'].forEach(id => assert.equal(h.nodes[id].value, ''));
    ['ap-arm-consent', 'ap-auto-consent'].forEach(id => assert.equal(h.nodes[id].checked, false));
    h.setHandler(async () => reply(200, payload(false))); await read();
    assert.equal(h.nodes[prefix + '-label'].textContent, 'OFF');
    assert.equal(h.nodes[prefix + '-btn'].disabled, false);
    assert.notEqual(h.nodes[badge].textContent, '—');
    body.resolve(payload(true)); await older;
    assert.equal(h.nodes[prefix + '-label'].textContent, 'OFF');
    assert.equal(h.nodes[prefix + '-btn'].disabled, false);
  });
  for (const kind of ['http', 'json', 'schema']) {
    test('AutoPilot ' + control + ' status ' + kind + ' is UNKNOWN and successful false recovers OFF', async () => {
      const h = harness(); const api = await load(h, ['41-automations.js'], '{_apRefreshStatus,_apRefreshAutoStatus}');
      const read = control === 'armed' ? api._apRefreshStatus : api._apRefreshAutoStatus;
      const prefix = control === 'armed' ? 'ap-armed' : 'ap-auto';
      h.setHandler(() => failure(kind)); await read();
      assert.equal(h.nodes[prefix + '-label'].textContent, 'UNKNOWN');
      assert.equal(h.nodes[prefix + '-btn'].disabled, true);
      h.setHandler(async () => reply(200, control === 'armed' ? { armed: false } : { autonomous: false, pro: false }));
      await read();
      assert.equal(h.nodes[prefix + '-label'].textContent, 'OFF');
      assert.equal(h.nodes[prefix + '-btn'].disabled, false);
    });
  }
}

for (const kind of ['recommendations', 'dry-run']) {
  test('AutoPilot ' + kind + ' discards pending JSON for both datasets after logout', async () => {
    const h = harness();
    const api = await load(h, fullSessionFragments, '{_apLoadRecs,_apDrLoad,authSaveSession,authUpdateUi,authLogout}');
    api.authSaveSession({ access_token: 'fixture', tenant_id: 'tenant-A', expires_at: Date.now() / 1000 + 3600 }); api.authUpdateUi();
    const firstBody = deferred(); const secondBody = deferred();
    h.setHandler(async url => {
      if (url === '/api/auth/logout') return reply(200, {});
      return { status: 200, ok: true, json: () => url.includes('/audit') || url.includes('/replay') ? secondBody.promise : firstBody.promise };
    });
    const pending = kind === 'recommendations' ? api._apLoadRecs() : api._apDrLoad();
    await tick();
    await api.authLogout();
    if (kind === 'recommendations') {
      firstBody.resolve({ recommendations: [{ id: 'late-rec', device_name: 'LATE_PRIVATE_RECOMMENDATION', issue_type: 'offline', action_type: 'restart' }] });
      secondBody.resolve({ audit: [{ decision: 'accept', device_name: 'LATE_PRIVATE_AUDIT', issue_type: 'offline', action_type: 'restart' }] });
    } else {
      firstBody.resolve({ actions: [{ rule_name: 'LATE_PRIVATE_SIMULATION', device_name: 'private-device', action_command: 'pause' }] });
      secondBody.resolve({ per_rule: [{ rule_name: 'LATE_PRIVATE_REPLAY', device_name: 'private-device', action_command: 'pause', fires: 1 }], total_fires: 1 });
    }
    await pending;
    const ids = kind === 'recommendations' ? ['ap-recs-list', 'ap-audit-list'] : ['ap-dr-now-list', 'ap-dr-replay-list'];
    ids.forEach(id => {
      assert.doesNotMatch(h.nodes[id].textContent, /LATE_PRIVATE/);
      assert.match(h.nodes[id].textContent, /not loaded|session|sessão/i);
    });
  });
}

(async () => {
  let failed = 0;
  for (const { name, run } of cases) {
    try { await run(); console.log('PASS ' + name); }
    catch (error) { failed++; console.error('FAIL ' + name + '\n' + error.stack); }
  }
  console.log(`${cases.length - failed} passed, ${failed} failed`);
  process.exitCode = failed ? 1 : 0;
})();
