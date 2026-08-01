/* ════════════════════════════════════════════════════════════════════════
   CYPHER65 · WAR ROOM · client logic
   ════════════════════════════════════════════════════════════════════════ */

(() => {
  'use strict';

  // ── constants ─────────────────────────────────────────────────────────
  const POLL_MS = window.POLL_INTERVAL_MS || 15000;
  let nextPollAt = Date.now() + POLL_MS;

  // ── formatters ────────────────────────────────────────────────────────
  const fmt = {
    hashrate(h) {
      if (!h && h !== 0) return '\u2014';
      const v = Number(h);
      const units = ['H/s', 'kH/s', 'MH/s', 'GH/s', 'TH/s', 'PH/s', 'EH/s'];
      let i = 0; let x = v;
      while (x >= 1000 && i < units.length - 1) { x /= 1000; i++; }
      return `${x.toFixed(x >= 100 ? 1 : 2)} ${units[i]}`;
    },
    diff(s) {
      if (!s && s !== 0) return '\u2014';
      if (typeof s === 'number') return fmt._diffFromNum(s);
      const str = String(s).trim();
      const m = str.match(/^([\d.,]+)\s*([a-zA-Z]*)$/);
      if (!m) return str;
      const num = parseFloat(m[1].replace(',', '.'));
      const suf = (m[2] || '').toUpperCase();
      const multMap = { '': 1, K: 1e3, M: 1e6, G: 1e9, T: 1e12, P: 1e15, E: 1e18 };
      return fmt._diffFromNum(num * (multMap[suf] || 1));
    },
    _diffFromNum(v) {
      if (!isFinite(v) || v === 0) return '0';
      v = Math.abs(v);
      const units = ['', 'K', 'M', 'G', 'T', 'P', 'E'];
      let i = 0; let x = v;
      while (x >= 1000 && i < units.length - 1) { x /= 1000; i++; }
      return `${x.toFixed(x >= 100 ? 0 : 2)} ${units[i]}`.trim();
    },
    uptime(s) {
      if (!s && s !== 0) return '\u2014';
      s = Math.floor(Number(s));
      if (s < 60) return `${s}s`;
      const d = Math.floor(s / 86400), h = Math.floor((s % 86400) / 3600),
            m = Math.floor((s % 3600) / 60);
      const parts = [];
      if (d) parts.push(`${d}d`);
      if (h) parts.push(`${h}h`);
      if (m && !d) parts.push(`${m}m`);
      return parts.join(' ') || '0m';
    },
    age(ts) {
      if (!ts) return '\u2014';
      const d = Math.max(0, Math.floor((Date.now() / 1000) - Number(ts)));
      if (d < 60) return `${d}s ago`;
      if (d < 3600) return `${Math.floor(d / 60)}m ago`;
      if (d < 86400) return `${Math.floor(d / 86400)}h ago`;
      return `${Math.floor(d / 86400)}d ago`;
    },
    shortAddr(a) {
      if (!a) return '';
      if (a.length <= 16) return a;
      return `${a.slice(0, 10)}\u2026${a.slice(-6)}`;
    },
    chunkAddr(a) {
      if (!a) return '';
      var prefix = '';
      var rest = a;
      if (a.indexOf('bc1') === 0) { prefix = 'bc1'; rest = a.slice(3); }
      else if (a.indexOf('1') === 0 || a.indexOf('3') === 0) { prefix = a[0]; rest = a.slice(1); }
      var chunks = [];
      for (var i = 0; i < rest.length; i += 4) {
        chunks.push(rest.slice(i, i + 4));
      }
      return prefix + ' ' + chunks.join(' ');
    },
    shortAddrChunk(a) {
      if (!a) return '';
      if (a.length <= 20) return fmt.chunkAddr(a);
      return a.slice(0, 6) + '...' + a.slice(-4);
    },
    pct(n) { if (!isFinite(n)) return '\u2014'; return `${n.toFixed(2)}%`; },
    usd(n) { if (!n) return '\u2014'; return `$${Number(n).toLocaleString('en-US', { maximumFractionDigits: 0 })}`; },
    // Shared numeric guard (Fase 5): telemetry fields may hold the literal
    // string "NOT AVAILABLE" after backend normalization — only real finite
    // numbers are treated as values.
    num(v) { return typeof v === 'number' && isFinite(v); },
    expectedBlock(workerHr, networkDiff) {
      if (!workerHr || !networkDiff) return null;
      const secs = (networkDiff * Math.pow(2, 32)) / workerHr * 65536;
      return secs;
    },
    secsToHuman(s) {
      if (!isFinite(s)) return '\u2014';
      if (s < 60) return `${s.toFixed(1)}s`;
      const min = s / 60; if (min < 60) return `${min.toFixed(1)}m`;
      const h = min / 60; if (h < 24) return `${h.toFixed(1)}h`;
      const d = h / 24; if (d < 365) return `${d.toFixed(1)}d`;
      return `${(d / 365).toFixed(2)}y`;
    },
  };

  // ── DOM cache ─────────────────────────────────────────────────────────
  const $ = (s) => document.querySelector(s);
  const $$ = (s) => document.querySelectorAll(s);
  const dom = {
    topbarAddress: $('#topbar-address'), statusPill: $('#status-pill'), statusText: $('#status-text'),
    clock: $('#clock'), nextPoll: $('#next-poll'), refreshNow: $('#refresh-now'),
    workerRankBadge: $('#worker-rank-badge'), workerUptimeBadge: $('#worker-uptime-badge'),
    mHashrate: $('#m-hashrate'), mHashrateSub: $('#m-hashrate-sub'), mBestDiff: $('#m-bestdiff'), mBestDiffSub: $('#m-bestdiff-sub'),
    mLastShare: $('#m-lastshare'), mLastShareSub: $('#m-lastshare-sub'), mState: $('#m-state'), mStateSub: $('#m-state-sub'),
    mSharePct: $('#m-share-pct'), mFairDiff: $('#m-fair-diff'), mExpectedShare: $('#m-expected-share'), mExpectedBlock: $('#m-expected-block'),
    poolUptime: $('#pool-uptime'), pHashrate: $('#p-hashrate'), pWorkers: $('#p-workers'), pHighDiff: $('#p-high-diff'),
    pLastBlock: $('#p-last-block'), pLastBlockTime: $('#p-last-block-time'), pWorkNum: $('#p-work-num'), pWorkFill: $('#p-work-fill'), pExpectedBlocks: $('#p-expected-blocks'),
    pStaleBadge: $('#p-stale-badge'),
    acctBlocksBadge: $('#acct-blocks-badge'), acctLn: $('#acct-ln'), acctTotalDiff: $('#acct-total-diff'),
    acctHighestBlock: $('#acct-highest-block'), acctCombined: $('#acct-combined'), acctDiffRank: $('#acct-diff-rank'), acctLoyaltyRank: $('#acct-loyalty-rank'),
    netStatus: $('#net-status'), nHeight: $('#n-height'), nDiff: $('#n-diff'), nHashrate: $('#n-hashrate'),
    nBtcUsd: $('#n-btc-usd'), nBtcBrl: $('#n-btc-brl'), nBtcEur: $('#n-btc-eur'), nBtcGbp: $('#n-btc-gbp'),
    eventsTbody: $('#events-tbody'), lbTbody: $('#lb-tbody'), logEventsCount: $('#log-events-count'), terminal: $('#terminal'),
    alertsList: $('#alerts-list'), alertsCountBadge: $('#alerts-count-badge'),
    timelineFeed: $('#timeline-feed'), timelineSharesBadge: $('#timeline-shares-badge'), timelineBumpsBadge: $('#timeline-bumps-badge'), timelineRateBadge: $('#timeline-rate-badge'),
    terminalEventsList: $('#terminal-events-list'), terminalEventCount: $('#terminal-event-count'),
    tStatLastShare: $('#t-stat-lastshare'), tStat1h: $('#t-stat-1h'), tStat24h: $('#t-stat-24h'), tStatBumps: $('#t-stat-bumps'),
    hBlocks: $('#h-blocks'), hDays: $('#h-days'), hCurReward: $('#h-cur-reward'), hNextReward: $('#h-next-reward'), hNextHeight: $('#h-next-height'), halvingEpochBadge: $('#halving-epoch-badge'),
    feesStatus: $('#fees-status'), feeEconomy: $('#fee-economy'), feeHour: $('#fee-hour'), feeHalfhour: $('#fee-halfhour'), feeFastest: $('#fee-fastest'), feeMinimum: $('#fee-minimum'),
    profitShareBadge: $('#profit-share-badge'), profitCostBadge: $('#profit-cost-badge'), pBtcDay: $('#p-btc-day'),
    pFiatDay: $('#p-fiat-day'), pFiatDayWeek: $('#p-fiat-day-week'), pFiatMonth: $('#p-fiat-month'), pFiatMonthSub: $('#p-fiat-month-sub'),
    pBreakeven: $('#p-breakeven'), pBreakevenSub: $('#p-breakeven-sub'), pBtcSub: $('#p-btc-sub'), profitFootnote: $('#profit-footnote'), pCurBadge: $('#p-cur-badge'), profitFiatRow: $('#profit-fiat-row'),
    hrReported: $('#hr-reported'), hrObserved: $('#hr-observed'), hrDeviationVal: $('#hr-deviation-val'), hrDeviationBadge: $('#hr-deviation-badge'),
    gaugeLabel: $('#gauge-label'), gaugeWorkerCanvas: $('#gauge-worker-canvas'), gaugePoolCanvas: $('#gauge-pool-canvas'), gaugeLuckCanvas: $('#gauge-luck-canvas'),
    gaugeWorkerPct: $('#gauge-worker-pct'), gaugePoolPct: $('#gauge-pool-pct'), gaugeLuckPct: $('#gauge-luck-pct'), gaugeWorkerBlockchance: $('#gauge-worker-blockchance'),
    badgesStrip: $('#badges-strip'), milestonesCount: $('#milestones-count'),
    proxPctBadge: $('#prox-pct-badge'), proxAlltimeBadge: $('#prox-alltime-badge'), proxStreakBadge: $('#prox-streak-badge'), proxArc: $('#prox-arc'),
    proxHeroPct: $('#prox-hero-pct'), proxHeroSub: $('#prox-hero-sub'), proxHeroBest: $('#prox-hero-best'),
    proxChance: $('#prox-chance'), proxTime: $('#prox-time'), proxTimeSub: $('#prox-time-sub'), proxDistance: $('#prox-distance'), proxTrend: $('#prox-trend'), proxTrendSub: $('#prox-trend-sub'),
    proxLadderRow: $('#prox-ladder-row'), proxSparkline: $('#prox-sparkline'), proxTip: document.getElementById('prox-tip'),
    lcTimeBig: $('#lc-time-big'), lcSessionShareCount: $('#lc-session-share-count'), lcShareDiff: $('#lc-share-diff'), lcHashes: $('#lc-hashes'),
    lcTimeObs: $('#lc-time-obs'), lcPBlock: $('#lc-p-block'), lcInstHr: $('#lc-inst-hr'), lcSessionShares: $('#lc-session-shares'),
    lcAvgShareDiff: $('#lc-avg-share-diff'), lcCumP: $('#lc-cum-p'), lcExpectedBlocks: $('#lc-expected-blocks'), lcTickerList: $('#lc-ticker-list'),
    qlStatusBadge: $('#ql-status-badge'), qlScoreBadge: $('#ql-score-badge'), qlBarFill: $('#ql-bar-fill'),
    qlCompShares: $('#ql-comp-shares'), qlCompProx: $('#ql-comp-prox'), qlCompPower: $('#ql-comp-power'), qlCompMomentum: $('#ql-comp-momentum'), qlLabel: $('#ql-label'),
    lmGrid: $('#lm-grid'), lmStatusBadge: $('#lm-status-badge'), lmWorkersBadge: $('#lm-workers-badge'),
    lmSummaryWallet: $('#lm-summary-wallet'), lmSummaryPool: $('#lm-summary-pool'), lmSummaryDot: $('#lm-summary-dot'),
    lmSummaryWorkers: $('#lm-summary-workers'), lmSummaryHr: $('#lm-summary-hr'), lmSummaryBest: $('#lm-summary-best'),
    lmBestShare: $('#lm-best-share'), lmBestShareVal: $('#lm-best-share-val'), lmBestShareWorker: $('#lm-best-share-worker'), lmBestShareTime: $('#lm-best-share-time'),
    lmEventLogTerminal: $('#lm-event-log-terminal'),
    hsNonceBar: $('#hs-nonce-bar'), hsNoncesSearched: $('#hs-nonces-searched'), hsNoncePct: $('#hs-nonce-pct'), hsHashesPerSec: $('#hs-hashes-per-sec'),
    hsBestDiff: $('#hs-best-diff'), hsTargetDiff: $('#hs-target-diff'), hsTargetBar: $('#hs-target-bar'), hsTargetMarker: $('#hs-target-marker'),
    hsBlockProb: $('#hs-block-prob'), hsExpectedTime: $('#hs-expected-time'), hsStatusText: $('#hs-status-text'),
    openWallet: $('#open-wallet'), walletModal: $('#wallet-modal'), walletStatus: $('#wallet-status'),
    walletAddressInput: $('#wallet-address-input'), walletWorkerInput: $('#wallet-worker-input'),
    walletCurrentAddr: $('#wallet-current-addr'), walletCurrentWorker: $('#wallet-current-worker'),
    walletSave: $('#wallet-save'),
    openSettings: $('#open-settings'), openExports: $('#open-exports'), settingsModal: $('#settings-modal'), exportModal: $('#export-modal'),
    settingsBody: $('#settings-body'), settingsStatus: $('#settings-status'),
    openAlertCenter: $('#open-alert-center'), alertCenterModal: $('#alert-center-modal'), alertCenterStatus: $('#alert-center-status'),
    acTabs: $$('.ac-tab'), acPanes: $$('.ac-pane'), acFilters: $$('.ac-filter'),
    acActiveList: $('#ac-active-list'), acHistoryList: $('#ac-history-list'), acRulesList: $('#ac-rules-list'),
    acRefreshActive: $('#ac-refresh-active'), acRefreshHistory: $('#ac-refresh-history'), acRefreshRules: $('#ac-refresh-rules'),
    acAddRule: $('#ac-add-rule'), acRuleForm: $('#ac-rule-form'), acRuleSave: $('#ac-rule-save'), acRuleCancel: $('#ac-rule-cancel'),
    acRuleName: $('#ac-rule-name'), acRuleDevice: $('#ac-rule-device'), acRuleMetric: $('#ac-rule-metric'), acRuleOp: $('#ac-rule-op'),
    acRuleValue: $('#ac-rule-value'), acRuleAction: $('#ac-rule-action'), acRuleStatus: $('#ac-rule-status'),
    huntStreamFeed: $('#hunt-stream-feed'), huntMetricsHr: $('#hunt-metrics-hr'), huntMetricsPblock: $('#hunt-metrics-pblock'),
    huntMetricsExpblocks: $('#hunt-metrics-expblocks'), huntMetricsBestdiff: $('#hunt-metrics-bestdiff'),
    huntSharesGrid: $('#hunt-shares-grid'), huntSharesCount: $('#hunt-shares-count'),

    // ── AXE FLEET ──
    axeFleetPanel: $('#axe-fleet-panel'),
    axeFleetStatusBadge: $('#axe-fleet-status-badge'),
    axeFleetCountBadge: $('#axe-fleet-count-badge'),
    axeSummaryHr: $('#axe-summary-hr'),
    axeSummaryOnline: $('#axe-summary-online'),
    axeSummaryOffline: $('#axe-summary-offline'),
    axeSummaryTemp: $('#axe-summary-temp'),
    axeSummaryBest: $('#axe-summary-best'),
    axeGrid: $('#axe-grid'),
    axeAddForm: $('#axe-add-form'),
    axeAddIp: $('#axe-add-ip'),
    axeAddName: $('#axe-add-name'),
    axeAddSave: $('#axe-add-save'),
    axeAddCancel: $('#axe-add-cancel'),
    axeAddStatus: $('#axe-add-status'),
    axeFleetAdd: $('#axe-fleet-add'),

    // New summary items
    axeSummaryWarning: $('#axe-summary-warning'),
    axeSummaryHealth: $('#axe-summary-health'),
    axeSummaryPower: $('#axe-summary-power'),
    axeSummaryEff: $('#axe-summary-eff'),

    // Device detail panel
    axeDetail: $('#axe-detail'),
    axeDetailTitle: $('#axe-detail-title'),
    axeDetailBody: $('#axe-detail-body'),
    axeDetailClose: $('#axe-detail-close'),

    // ── STATUS BAR ──
    sbLed: $('#sb-led'),
    sbStatus: $('#sb-status'),
    sbWorkers: $('#sb-workers'),
    sbHashrate: $('#sb-hashrate'),
    sbBestdiff: $('#sb-bestdiff'),
    sbLastshare: $('#sb-lastshare'),
    sbPoolHr: $('#sb-pool-hr'),
    sbPoolWorkers: $('#sb-pool-workers'),
    sbPoolBlock: $('#sb-pool-block'),
    sbNetDiff: $('#sb-net-diff'),
    sbNetPrice: $('#sb-net-price'),
    sbNetHeight: $('#sb-net-height'),
    sbFleetOnline: $('#sb-fleet-online'),
    sbFleetTotal: $('#sb-fleet-total'),
    sbFleetHr: $('#sb-fleet-hr'),
    sbWalletAddr: $('#sb-wallet-addr'),
    statusBar: $('#status-bar'),

    // ── HUD bar elements ──
    hudBar: $('#hud-bar'),
    hudHashrate: $('#hud-hashrate'),
    hudBestdiff: $('#hud-bestdiff'),
    hudShares: $('#hud-shares'),
    hudPoolhr: $('#hud-poolhr'),

    // ── KPI cards ──
    kpiHashrate: $('#kpi-hashrate'),
    kpiBestdiff: $('#kpi-bestdiff'),
    kpiShares: $('#kpi-shares'),
    kpiPoolhr: $('#kpi-poolhr'),

    // ── TENANT AUTH ──
    // Note: authLoginBtn/authLogoutBtn use the `Btn` suffix to avoid
    // clashing with the authLogin()/authLogout() functions in this scope.
    authToggle: $('#auth-toggle'),
    authModal: $('#auth-modal'),
    authStatus: $('#auth-status'),
    authApiKey: $('#auth-api-key'),
    authLoginBtn: $('#auth-login'),
    authLogoutBtn: $('#auth-logout'),
    authCurrentTenant: $('#auth-current-tenant'),
    axeFleetTenantBadge: $('#axe-fleet-tenant-badge'),
  };

  
  // ── FASE 2: Toast notification ──
  function showToast(type, message) {
    var t = document.getElementById('toast-container');
    if (!t) {
      t = document.createElement('div');
      t.id = 'toast-container';
      t.style.cssText = 'position:fixed;bottom:60px;right:16px;z-index:9999;display:flex;flex-direction:column;gap:6px;max-width:320px';
      document.body.appendChild(t);
    }
    var el = document.createElement('div');
    el.style.cssText = 'padding:8px 14px;border-radius:2px;font-size:12px;font-family:JetBrains Mono,monospace;background:#1A1B1D;border:1px solid ' + (type === 'success' ? '#00C853' : '#FF1744') + ';color:#EAEAEB;box-shadow:0 2px 8px rgba(0,0,0,0.4);animation:fadeIn 0.2s ease';
    el.textContent = message;
    t.appendChild(el);
    setTimeout(function() { el.style.opacity = '0'; el.style.transition = 'opacity 0.3s'; setTimeout(function() { el.remove(); }, 300); }, 3000);
  }

// ── escape HTML ───────────────────────────────────────────────────────
  function escapeHtml(s) { return String(s).replace(/[&<>"']/g, c => ({ '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;' }[c])); }

  // ── Tenant Auth (Fase 4 · B1-frontend) ─────────────────────────────
  // Stores the JWT session in localStorage and attaches
  // `Authorization: Bearer <token>` to every /api/axe-fleet/* request so
  // the backend's require_tenant() isolates per tenant.
  // Pure helpers below (authBuildHeaders/authIsExpired/authSessionValid)
  // are mirrored in tests/test_app_js_core.js.
  const AUTH_SESSION_KEY = '_cypher65_auth_session';

  function authLoadSession() {
    try {
      const raw = localStorage.getItem(AUTH_SESSION_KEY);
      if (!raw) return null;
      const s = JSON.parse(raw);
      return (s && s.access_token) ? s : null;
    } catch (e) { return null; }
  }
  function authSaveSession(s) {
    try { localStorage.setItem(AUTH_SESSION_KEY, JSON.stringify(s)); } catch (e) {}
  }
  function authClearSession() {
    try { localStorage.removeItem(AUTH_SESSION_KEY); } catch (e) {}
  }

  function authBuildHeaders(token) {
    if (!token) return {};
    return { 'Authorization': 'Bearer ' + token };
  }
  function authIsExpired(expiresAt, now) {
    if (!expiresAt) return true;
    now = now || Math.floor(Date.now() / 1000);
    return now >= (Number(expiresAt) - 30); // 30s safety margin
  }
  function authSessionValid(session, now) {
    if (!session || !session.access_token) return false;
    return !authIsExpired(session.expires_at, now);
  }

  function authGetToken() {
    const s = authLoadSession();
    return (s && authSessionValid(s)) ? s.access_token : null;
  }

  // Fetch wrapper: attach Bearer header; on 401 try a refresh once, retry.
  // IMPORTANT: /api/axe-fleet/* routes use @require_tenant (not @require_auth),
  // so an invalid/expired token NEVER returns 401 — the server silently falls
  // back to tenant 'default'. We therefore refresh PROACTIVELY whenever the
  // stored token is near/past expiry (authIsExpired already applies a 30s
  // safety margin), so the isolated tenant is never dropped at the refresh
  // boundary. The 401-retry below is a belt-and-suspenders for routes that
  // DO hard-require auth.
  async function authFetch(url, opts) {
    opts = opts || {};
    const session = authLoadSession();
    if (session && session.refresh_token && authIsExpired(session.expires_at)) {
      await authRefresh();
    }
    const token = authGetToken();
    const headers = Object.assign({}, opts.headers || {}, authBuildHeaders(token));
    let res = await fetch(url, Object.assign({}, opts, { headers }));
    if (res.status === 401 && token) {
      const refreshed = await authRefresh();
      if (refreshed) {
        const headers2 = Object.assign({}, opts.headers || {}, authBuildHeaders(authGetToken()));
        res = await fetch(url, Object.assign({}, opts, { headers: headers2 }));
      }
    }
    return res;
  }

  async function authRefresh() {
    const s = authLoadSession();
    if (!s || !s.refresh_token) return false;
    try {
      const r = await fetch('/api/auth/refresh', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ refresh_token: s.refresh_token }),
      });
      if (!r.ok) return false;
      const data = await r.json();
      if (!data.access_token) return false;
      authSaveSession({
        access_token: data.access_token,
        refresh_token: s.refresh_token,
        expires_at: data.expires_at,
        tenant_id: data.tenant_id || s.tenant_id || 'default',
      });
      return true;
    } catch (e) { return false; }
  }

  async function authLogin(apiKey) {
    if (!apiKey) return { ok: false, error: 'API key is required' };
    try {
      const r = await fetch('/api/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ api_key: apiKey }),
      });
      const data = await r.json().catch(() => ({}));
      if (!r.ok) return { ok: false, error: data.error || ('login failed (' + r.status + ')') };
      authSaveSession({
        access_token: data.access_token,
        refresh_token: data.refresh_token,
        expires_at: data.expires_at,
        tenant_id: data.tenant_id || 'default',
      });
      authUpdateUi();
      return { ok: true, tenant_id: data.tenant_id || 'default' };
    } catch (e) {
      return { ok: false, error: e.message || 'network error' };
    }
  }

  async function authLogout() {
    const s = authLoadSession();
    if (s && s.access_token) {
      try {
        await fetch('/api/auth/logout', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ access_token: s.access_token }),
        });
      } catch (e) {}
    }
    authClearSession();
    authUpdateUi();
  }

  function authUpdateUi() {
    const s = authLoadSession();
    const connected = authSessionValid(s);
    const tenant = connected ? (s.tenant_id || 'default') : 'default';
    const toggle = dom.authToggle;
    if (toggle) {
      toggle.textContent = connected ? '🔑 ' + tenant.toUpperCase() : '🔑 LOGIN';
      toggle.classList.toggle('is-authed', connected);
      toggle.title = connected ? 'Tenant: ' + tenant + ' — click to manage' : 'Tenant Login';
    }
    const badge = dom.axeFleetTenantBadge;
    if (badge) {
      badge.textContent = 'TENANT: ' + tenant;
      badge.classList.toggle('badge--green', connected);
      badge.classList.toggle('badge--mute', !connected);
    }
    const cur = dom.authCurrentTenant;
    if (cur) cur.textContent = connected ? tenant : '—';
    if (dom.authLogoutBtn) dom.authLogoutBtn.style.display = connected ? '' : 'none';
    if (dom.authStatus && !connected) dom.authStatus.textContent = '';
  }

  function initAuth() {
    authUpdateUi();
    const toggle = dom.authToggle;
    const modal = dom.authModal;
    if (toggle && modal) {
      toggle.addEventListener('click', function() {
        authUpdateUi();
        modal.classList.add('modal--open');
      });
    }
    const loginBtn = dom.authLoginBtn;
    if (loginBtn) {
      loginBtn.addEventListener('click', async function() {
        const keyInput = dom.authApiKey;
        const statusEl = dom.authStatus;
        const key = keyInput ? keyInput.value.trim() : '';
        if (!key) { if (statusEl) statusEl.textContent = '⚠ API key required'; return; }
        if (statusEl) { statusEl.textContent = 'connecting…'; statusEl.className = 'modal__status'; }
        const res = await authLogin(key);
        if (statusEl) {
          statusEl.textContent = res.ok ? '✓ connected as ' + res.tenant_id : '✗ ' + res.error;
          statusEl.className = res.ok ? 'modal__status modal__status--ok' : 'modal__status modal__status--err';
        }
        if (res.ok) {
          setTimeout(function() {
            if (modal) modal.classList.remove('modal--open');
            fetchAxeFleet();
          }, 400);
        }
      });
    }
    if (dom.authLogoutBtn) {
      dom.authLogoutBtn.addEventListener('click', async function() {
        await authLogout();
        if (modal) modal.classList.remove('modal--open');
        fetchAxeFleet();
      });
    }
    if (dom.authApiKey && loginBtn) {
      dom.authApiKey.addEventListener('keydown', function(e) {
        if (e.key === 'Enter') loginBtn.click();
      });
    }
  }

  // ── Theme Toggle ─────────────────────────────────────────────────────
  // Persists the light/dark preference and toggles the <html data-theme>
  // attribute consumed by the CSS :root[data-theme='light'] selectors.
  // Dark = attribute absent (null) — matches the E2E theme test assertions.
  const THEME_STORAGE_KEY = '_cypher65_theme';

  function themeApply(pref) {
    const isLight = pref === 'light';
    const root = document.documentElement;
    if (isLight) root.setAttribute('data-theme', 'light');
    else root.removeAttribute('data-theme');
  }

  function themeCurrent() {
    return document.documentElement.getAttribute('data-theme') === 'light' ? 'light' : 'dark';
  }

  function themeToggle() {
    const next = themeCurrent() === 'light' ? 'dark' : 'light';
    themeApply(next);
    try { localStorage.setItem(THEME_STORAGE_KEY, next); } catch (e) { /* storage unavailable */ }
    const btn = document.getElementById('theme-toggle');
    if (btn) {
      btn.textContent = next === 'light' ? '☾' : '☀';
      btn.title = next === 'light' ? 'Switch to dark theme' : 'Switch to light theme';
    }
  }

  function initThemeToggle() {
    // Apply persisted preference on boot (fresh sessions default to dark).
    try {
      const saved = localStorage.getItem(THEME_STORAGE_KEY);
      themeApply(saved === 'light' ? 'light' : 'dark');
    } catch (e) { /* storage unavailable */ }
    const btn = document.getElementById('theme-toggle');
    if (btn) {
      btn.addEventListener('click', function() { themeToggle(); });
      btn.textContent = themeCurrent() === 'light' ? '☾' : '☀';
    }
  }

  // ── WebLN detection ───────────────────────────────────────────────────
  var _weblnProvider = null;
  var _weblnConnecting = false;

  function detectWebLN(timeout) {
    timeout = timeout || 3000;
    return new Promise(function(resolve) {
      if (window.webln && typeof window.webln.enable === 'function') {
        resolve(window.webln);
        return;
      }
      var handler = function() {
        document.removeEventListener('webln:ready', handler);
        resolve(window.webln || null);
      };
      document.addEventListener('webln:ready', handler, { once: true });
      setTimeout(function() {
        document.removeEventListener('webln:ready', handler);
        resolve(window.webln || null);
      }, timeout);
    });
  }

  async function connectWebLN() {
    if (_weblnConnecting) return;
    _weblnConnecting = true;
    var statusEl = document.getElementById('webln-status');
    var previewEl = document.getElementById('webln-preview');
    if (!statusEl || !previewEl) { _weblnConnecting = false; return; }

    statusEl.textContent = '\uD83D\uDD0D Detecting Lightning wallet...';
    statusEl.className = 'webln-status webln-status--pending';

    var provider = await detectWebLN(4000);
    if (!provider) {
      statusEl.textContent = '\u26A0 No WebLN wallet detected. Install Alby or Joule browser extension.';
      statusEl.className = 'webln-status webln-status--error';
      _weblnConnecting = false;
      return;
    }

    statusEl.textContent = '\uD83D\uDD11 Requesting permission...';
    try {
      await provider.enable();
    } catch (e) {
      statusEl.textContent = '\u26A0 Permission denied: ' + (e.message || 'user cancelled');
      statusEl.className = 'webln-status webln-status--error';
      _weblnConnecting = false;
      return;
    }

    statusEl.textContent = '\uD83D\uDCE1 Fetching node info...';
    try {
      var info = await provider.getInfo();
      var nodeAlias = info.node && info.node.alias ? info.node.alias : 'Unknown Node';
      var nodePubkey = info.node && info.node.pubkey ? info.node.pubkey : '';
      var lnAddr = info.node && info.node.lightning_address ? info.node.lightning_address : '';
      _weblnProvider = provider;

      previewEl.style.display = 'block';
      previewEl.innerHTML =
        '<div class="webln-preview__header">\u26A1 Lightning Wallet Detected</div>' +
        '<div class="webln-preview__body">' +
          '<div class="webln-preview__row"><span class="webln-preview__label">Provider</span><span class="webln-preview__val">' + escapeHtml(info.providerName || info.node && info.node.alias || 'WebLN') + '</span></div>' +
          '<div class="webln-preview__row"><span class="webln-preview__label">Node</span><span class="webln-preview__val">' + escapeHtml(nodeAlias) + '</span></div>' +
          (nodePubkey ? '<div class="webln-preview__row"><span class="webln-preview__label">Pubkey</span><span class="webln-preview__val mono">' + escapeHtml(fmt.shortAddr(nodePubkey)) + '</span></div>' : '') +
          (lnAddr ? '<div class="webln-preview__row"><span class="webln-preview__label">LN Addr</span><span class="webln-preview__val mono">' + escapeHtml(lnAddr) + '</span></div>' : '') +
        '</div>' +
        '<div class="webln-preview__actions">' +
          '<button class="btn btn--primary" id="webln-confirm-btn">\u2713 CONFIRM & CONNECT</button>' +
          '<button class="btn" id="webln-cancel-btn">\u2715 CANCEL</button>' +
        '</div>';

      statusEl.textContent = '\u2713 WebLN wallet ready — review and confirm';
      statusEl.className = 'webln-status webln-status--success';

      document.getElementById('webln-confirm-btn')?.addEventListener('click', function() {
        var btcAddr = info.walletAddress || '';
        if (btcAddr && dom.walletAddressInput) {
          dom.walletAddressInput.value = btcAddr;
          var evt = new Event('input', { bubbles: true });
          dom.walletAddressInput.dispatchEvent(evt);
          setTimeout(function() { dom.walletSave?.click(); }, 300);
        } else {
          statusEl.textContent = '\u2139 Your LN wallet did not provide a BTC address. Enter it manually above.';
          statusEl.className = 'webln-status webln-status--info';
          previewEl.style.display = 'none';
          _weblnProvider = null;
          setTimeout(function() { dom.walletAddressInput?.focus(); }, 100);
        }
      });
      document.getElementById('webln-cancel-btn')?.addEventListener('click', function() {
        previewEl.style.display = 'none';
        previewEl.innerHTML = '';
        statusEl.textContent = '';
        statusEl.className = 'webln-status';
        _weblnProvider = null;
        _weblnConnecting = false;
      });

    } catch (e) {
      statusEl.textContent = '\u26A0 Failed to get node info: ' + (e.message || 'unknown error');
      statusEl.className = 'webln-status webln-status--error';
    }
    _weblnConnecting = false;
  }

  // ── Bitcoin address validation (Bech32 + Base58Check) ──────────────
  const _BECH32_CHARSET = 'qpzry9x8gf2tvdw0s3jn54khce6mua7l';
  const _VALIDATE_BASE58 = '123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz';

  function _bech32Polymod(values) {
    var GEN = [0x3b6a57b2, 0x26508e6d, 0x1ea119fa, 0x3d4233dd, 0x2a1462b3];
    var chk = 1;
    for (var i = 0; i < values.length; i++) {
      var top = chk >> 25;
      chk = ((chk & 0x1ffffff) << 5) ^ values[i];
      for (var j = 0; j < 5; j++) {
        if ((top >> j) & 1) chk ^= GEN[j];
      }
    }
    return chk;
  }

  // ── Real-time wallet address validation ──
  var _walletValidationTimer = null;
  function _updateWalletValidation() {
    var input = dom.walletAddressInput;
    var statusEl = document.getElementById('wallet-validation-status');
    if (!input || !statusEl) return;
    var addr = input.value.trim();
    if (!addr) {
      statusEl.textContent = '';
      statusEl.className = 'wallet-validation-status';
      input.classList.remove('field__input--valid', 'field__input--invalid');
      return;
    }
    var result = validateBitcoinAddress(addr);
    if (result.valid) {
      input.classList.remove('field__input--invalid');
      input.classList.add('field__input--valid');
      var typeLabel = addr.indexOf('bc1') === 0 ? 'Bech32' : 'Base58';
      statusEl.textContent = '\u2713 Valid ' + typeLabel + ' address';
      statusEl.className = 'wallet-validation-status wallet-validation-status--valid';
    } else {
      input.classList.remove('field__input--valid');
      input.classList.add('field__input--invalid');
      statusEl.textContent = '\u2717 ' + result.error;
      statusEl.className = 'wallet-validation-status wallet-validation-status--invalid';
    }
  }

  // Wire up real-time validation on input + debounced keyup
  dom.walletAddressInput?.addEventListener('input', _updateWalletValidation);
  dom.walletAddressInput?.addEventListener('keyup', function() {
    if (_walletValidationTimer) clearTimeout(_walletValidationTimer);
    _walletValidationTimer = setTimeout(_updateWalletValidation, 200);
  });

  function validateBitcoinAddress(addr) {
    if (!addr || typeof addr !== 'string') return { valid: false, error: 'Address is required' };
    addr = addr.trim();
    if (addr.length < 26 || addr.length > 90) return { valid: false, error: 'Invalid length (' + addr.length + ' chars)' };

    // FULL & FREE whitelist: every greeted wallet (WALLET_GREETINGS keys) is
    // entitled, so its exact address is accepted even when it doesn't match
    // the strict BTC prefix rules (e.g. the DOGE/LTC addresses). Only the
    // exact greeted addresses bypass — everything else is validated strictly.
    if (walletGreeting(addr)) return { valid: true, note: 'FULL & FREE wallet' };

    // Bech32 (bc1...)
    if (addr.indexOf('bc1') === 0 || addr.indexOf('BC1') === 0) {
      var lower = addr.toLowerCase();
      var pos = lower.lastIndexOf('1');
      if (pos < 1 || pos + 7 > lower.length) return { valid: false, error: 'Invalid Bech32 format' };
      var hrp = lower.slice(0, pos);
      var data = lower.slice(pos + 1);
      if (hrp !== 'bc') return { valid: false, error: 'Invalid prefix (expected bc1)' };
      if (data.length < 6) return { valid: false, error: 'Data part too short' };
      for (var i = 0; i < data.length; i++) {
        if (_BECH32_CHARSET.indexOf(data[i]) === -1) return { valid: false, error: 'Invalid Bech32 character' };
      }
      var values = [];
      for (var j = 0; j < data.length; j++) values.push(_BECH32_CHARSET.indexOf(data[j]));
      var hrpExpand = [];
      for (var k = 0; k < hrp.length; k++) hrpExpand.push(hrp.charCodeAt(k) >> 5);
      hrpExpand.push(0);
      for (var l = 0; l < hrp.length; l++) hrpExpand.push(hrp.charCodeAt(l) & 31);
      var all = hrpExpand.concat(values);
      if (_bech32Polymod(all) !== 1) return { valid: false, error: 'Invalid Bech32 checksum' };
      return { valid: true };
    }

    // Base58Check (1... or 3...)
    if (addr.indexOf('1') === 0 || addr.indexOf('3') === 0) {
      for (var m = 0; m < addr.length; m++) {
        if (_VALIDATE_BASE58.indexOf(addr[m]) === -1) return { valid: false, error: 'Invalid Base58 character' };
      }
      // Decode Base58 to hex and verify checksum
      try {
        var n = 0n;
        for (var p = 0; p < addr.length; p++) {
          n = n * 58n + BigInt(_VALIDATE_BASE58.indexOf(addr[p]));
        }
        var hex = n.toString(16);
        if (hex.length % 2 === 1) hex = '0' + hex;
        // Count leading '1's (each = leading zero byte)
        var lead1 = 0;
        while (lead1 < addr.length && addr[lead1] === '1') lead1++;
        if (lead1 > 0) hex = '00'.repeat(lead1) + hex;
        if (hex.length < 10) return { valid: false, error: 'Address too short for checksum' };
        var payload = hex.slice(0, hex.length - 8);
        var checksum = hex.slice(hex.length - 8);
        // We'd need SHA256 here, but can't in pure JS without crypto subtle
        // For now, do a basic format check and let backend do full checksum
        return { valid: true, note: 'Format OK — backend will verify checksum' };
      } catch (e) {
        return { valid: false, error: 'Invalid Base58 format' };
      }
    }

    return { valid: false, error: 'Address must start with bc1, 1, or 3' };
  }

  // ── decode HTML entities (reverse of escapeHtml) ────────────────────
  function decodeHtmlEntities(s) {
    if (!s) return '';
    var txt = document.createElement('textarea');
    txt.innerHTML = String(s);
    return txt.value;
  }

  // ── normalize worker name: decode HTML + trim + lowercase ───────────
  function normalizeWorkerName(s) {
    return decodeHtmlEntities(String(s || '')).trim().toLowerCase();
  }

  // ── Professional value transition ──
  function smoothUpdate(el, newText) {
    if (!el) return;
    const old = el.textContent;
    if (old !== newText && old !== '\u2014' && newText !== '\u2014') {
      el.classList.remove('value-flash'); void el.offsetWidth; el.classList.add('value-flash');
    }
    el.textContent = newText;
  }

  // ── Count-up animation ──
  const _countUpState = new WeakMap();
  function _parseNum(txt) { if (!txt) return NaN; const m = String(txt).match(/([\d.,]+)/); if (!m) return NaN; return parseFloat(m[1].replace(/,/g, '')); }
  function countUpValue(el, targetText, durationMs) {
    durationMs = durationMs || 420;
    if (!el || window.matchMedia('(prefers-reduced-motion: reduce)').matches) { if (el) el.textContent = targetText; return; }
    const num = _parseNum(targetText);
    if (isNaN(num)) { el.textContent = targetText; return; }
    const prefix = String(targetText).replace(/^([^\d]*).*/, '$1');
    const suffix = String(targetText).replace(/^.*?([^\d]*)$/, '$1');
    const decimals = (String(targetText).match(/\.(\d+)/) || ['', ''])[1].length;
    const start = performance.now();
    const from = isNaN(_parseNum(el.textContent)) ? 0 : _parseNum(el.textContent);
    const existing = _countUpState.get(el);
    if (existing && existing.raf) cancelAnimationFrame(existing.raf);
    const step = () => {
      const t = Math.min(1, (performance.now() - start) / durationMs);
      const eased = 1 - Math.pow(1 - t, 3);
      const current = from + (num - from) * eased;
      el.textContent = prefix + current.toFixed(decimals) + suffix;
      if (t < 1) { const rafInner = requestAnimationFrame(step); _countUpState.set(el, { raf: rafInner }); }
      else { el.textContent = targetText; _countUpState.delete(el); }
    };
    const rafOuter = requestAnimationFrame(step);
  }

  // ── Skeleton loading ──
  let _skeletonsHidden = false;
  function showSkeletons() {
    document.querySelectorAll('.panel').forEach(p => {
      if (p.querySelector('.skel-overlay')) return;
      const ov = document.createElement('div'); ov.className = 'skel-overlay';
      for (let i = 0; i < 3; i++) {
        const skel = document.createElement('div'); skel.className = 'skel';
        skel.style.width = `${['w-60','w-80','w-40'][i]}` === 'w-60' ? '60%' : ['w-80','w-40'][i-1] === 'w-80' ? '80%' : '40%';
        ov.appendChild(skel);
      }
      p.appendChild(ov);
    });
  }
  function hideSkeletons() {
    document.querySelectorAll('.skel-overlay').forEach(o => o.remove());
    _skeletonsHidden = true;
  }

  // ══════════════════════════════════════════════════════════════════════
  // RENDER FUNCTIONS
  // ══════════════════════════════════════════════════════════════════════

  // ── HUD — fixed bar with critical metrics ──
  function renderHUD(snap) {
    const w = snap.worker || {};
    const pool = snap.pool || {};
    const prox = snap.proximity || {};
    const workers = snap.all_workers || [];

    if (!dom.hudBar) return;
    if (!snap.worker) { dom.hudBar.style.display = 'none'; return; }
    dom.hudBar.style.display = 'flex';

    if (dom.hudHashrate) dom.hudHashrate.textContent = fmt.hashrate(w.hashrate);
    if (dom.hudBestdiff) dom.hudBestdiff.textContent = fmt.diff(w.bestDifficulty);
    const shares = prox.live_calc?.session_totals?.shares_so_far || 0;
    if (dom.hudShares) dom.hudShares.textContent = shares.toLocaleString();
    if (dom.hudPoolhr) dom.hudPoolhr.textContent = fmt.hashrate(pool.hashrate);
  }

  function renderStatusBar(snap) {
    const w = snap.worker || {};
    const pool = snap.pool || {};
    const net = snap.network || {};
    const btc = snap.btc_price || {};
    const workers = snap.all_workers || [];
    const axeFleet = snap.axe_fleet || [];

    // System block
    if (dom.sbLed) {
      const isOnline = !!snap.worker;
      dom.statusBar?.classList.toggle('is-online', isOnline);
      dom.sbLed.style.background = isOnline ? 'var(--accent-green)' : 'var(--accent-red)';
    }
    if (dom.sbStatus) dom.sbStatus.textContent = snap.worker ? 'ONLINE' : 'OFFLINE';
    if (dom.sbWorkers) dom.sbWorkers.textContent = `${workers.length} worker${workers.length === 1 ? '' : 's'}`;

    // Mining block
    if (dom.sbHashrate) dom.sbHashrate.textContent = fmt.hashrate(w.hashrate);
    if (dom.sbBestdiff) dom.sbBestdiff.textContent = fmt.diff(w.bestDifficulty);
    if (dom.sbLastshare) dom.sbLastshare.textContent = w.lastSubmission ? fmt.age(w.lastSubmission) : '\u2014';

    // Pool block
    if (dom.sbPoolHr) dom.sbPoolHr.textContent = fmt.hashrate(pool.hashrate);
    if (dom.sbPoolWorkers) dom.sbPoolWorkers.textContent = `${pool.workers || 0}`;
    if (dom.sbPoolBlock) dom.sbPoolBlock.textContent = pool.lastBlock ? `#${pool.lastBlock}` : '\u2014';

    // Network block
    if (dom.sbNetDiff) dom.sbNetDiff.textContent = fmt.diff(net.difficulty);
    if (dom.sbNetPrice) dom.sbNetPrice.textContent = btc.usd ? `$${Number(btc.usd).toLocaleString()}` : '\u2014';
    if (dom.sbNetHeight) dom.sbNetHeight.textContent = net.height ? `#${net.height}` : '\u2014';
    _staleChip(dom.sbNetPrice, btc.stale, 'cache');
    _staleChip(dom.sbNetDiff, net.stale, 'cache');

    // Fleet block
    const online = axeFleet.filter(d => d.status === 'ONLINE').length;
    const total = axeFleet.length;
    if (dom.sbFleetOnline) dom.sbFleetOnline.textContent = online;
    if (dom.sbFleetTotal) dom.sbFleetTotal.textContent = total;
    let fleetHr = 0;
    axeFleet.forEach(d => { fleetHr += Number(d.hashrate || 0); });
    if (dom.sbFleetHr) dom.sbFleetHr.textContent = fleetHr > 0 ? fmt.hashrate(fleetHr) : '\u2014';

    // Wallet block — show connected BTC address from snapshot
    if (dom.sbWalletAddr) {
      var addr = snap.btc_address || window.BTC_ADDRESS || '';
      dom.sbWalletAddr.innerHTML = addr ? '<span title="' + escapeHtml(addr) + '">' + fmt.shortAddrChunk(addr) + '</span>' : '—';
      dom.sbWalletAddr.title = addr || 'no wallet connected';
    }
    // Wallet connection state — only topbar button remains
    // Connection state tracked via localStorage.getItem('_wallet_connected')
  }

  // ── HOST CORE — populate the organism mission-control hub ──
  function renderHostCore(snap) {
    const w = snap.worker || {};
    const net = snap.network || {};
    const pool = snap.pool || {};
    const axeFleet = snap.axe_fleet || [];
    const prox = snap.proximity || {};
    const alerts = snap.alerts_recent || [];

    const hcBadge = (id, text) => { const el = document.getElementById(id); if (el) el.textContent = text; };

    hcBadge('hc-hr-badge', fmt.hashrate(w.hashrate));
    hcBadge('hc-net-badge', net.difficulty ? 'diff ' + fmt.diff(net.difficulty) : '—');
    hcBadge('hc-colony-hr', fmt.hashrate(w.hashrate) + ' / ' + fmt.hashrate(net.hashrate));
    hcBadge('hc-best-diff', fmt.diff(w.bestDifficulty));
    hcBadge('hc-network', net.height ? '#' + net.height : '—');

    // Fleet health
    const total = axeFleet.length;
    const online = axeFleet.filter(d => d.status === 'ONLINE').length;
    const healthStr = total > 0 ? (online / total * 100).toFixed(0) + '%' : '—';
    hcBadge('hc-fleet-health', total > 0 ? online + '/' + total + ' (' + healthStr + ')' : '—');

    // Block probability — show ~0% for vanishingly small values
    const pBlock = prox.chance_per_share_pct;
    const pctVal = pBlock != null ? Number(pBlock) * 100 : 0;
    hcBadge('hc-block-prob', pBlock != null ? (pctVal < 0.000001 ? '~0%' : pctVal.toFixed(6) + '%') : '—');

    // Alerts
    hcBadge('hc-alerts', alerts.length > 0 ? alerts.length + ' active' : 'nominal');
  }

  function renderHero(snap) {
    const w = snap.worker || {};
    smoothUpdate(dom.mHashrate, fmt.hashrate(w.hashrate));
    smoothUpdate(dom.mBestDiff, fmt.diff(w.bestDifficulty));
    if (dom.mLastShare) dom.mLastShare.textContent = w.lastSubmission ? fmt.age(w.lastSubmission) : '\u2014';
    if (dom.mState) dom.mState.textContent = w.hashrate ? 'HASHING' : 'IDLE';
  }

  
  // ── HOTFIX: Render Raio X miner fleet ──
  function renderMinersXRay(snap) {
    var workers = snap.all_workers || [];
    var section = document.getElementById('raio-x');
    var grid = document.getElementById('raio-x-grid');
    var count = document.getElementById('raio-x-count');
    if (!section || !grid) return;

    if (!workers || workers.length === 0) {
      section.style.display = 'none';
      return;
    }

    section.style.display = 'block';
    var totalHr = 0;
    var online = 0;
    var html = '';
    workers.forEach(function(w) {
      // Field name fallbacks: handle variations from different APIs
      var hr = parseFloat(w.hashrate || w.hashrate1m || w.hashrate1h || w.hr || 0);
      totalHr += hr;
      var isOnline = hr > 0;
      if (isOnline) online++;
      var statusClass = isOnline ? 'raio-x__led--on' : 'raio-x__led--off';
      var statusLabel = isOnline ? 'ONLINE' : 'OFFLINE';
      var hrStr = hr >= 1e12 ? (hr/1e12).toFixed(2) + ' TH/s' : hr >= 1e9 ? (hr/1e9).toFixed(2) + ' GH/s' : hr + ' H/s';
      var rawName = String(w.name || w.worker || w.id || 'unknown');
      var name = decodeHtmlEntities(rawName);
      var shortName = name.length > 20 ? name.slice(0, 18) + '...' : name;
      var best = w.bestDifficulty || w.best_diff || w.bestShare || w.best_share || '';
      var bestStr = best ? String(best) : '';
      var bestShort = bestStr.length > 12 ? bestStr.slice(0, 10) + '...' : bestStr || '—';
      var uptime = w.uptime || w.up_time || w.uptimeSeconds || w.runtime || '—';
      var lastSub = parseInt(w.lastSubmission || w.last_submission || w.last_share || w.lastShare || 0);
      var age = lastSub > 0 ? Math.floor((Date.now()/1000 - lastSub) / 60) + 'm ago' : '—';
      var temp = w.temperature || w.temp || w.temp_pcb || w.temp_chip || null;
      var tempStr = temp !== null ? temp + '°C' : '—';
      var eff = w.efficiency || w.eff || null;
      var effStr = eff !== null ? eff.toFixed(1) + ' J/TH' : '';

      html += '<div class="raio-x__card">';
      html += '<div class="raio-x__header">';
      html += '<span class="raio-x__led ' + statusClass + '"></span>';
      html += '<span class="raio-x__status ' + statusClass + '">' + statusLabel + '</span>';
      html += '<span class="raio-x__name" title="' + name + '">' + shortName + '</span>';
      html += '</div>';
      html += '<div class="raio-x__metrics">';
      html += '<div class="raio-x__metric"><span class="raio-x__m-label">HR</span><span class="raio-x__m-val">' + hrStr + '</span></div>';
      html += '<div class="raio-x__metric"><span class="raio-x__m-label">Best</span><span class="raio-x__m-val">' + bestShort + '</span></div>';
      html += '<div class="raio-x__metric"><span class="raio-x__m-label">Temp</span><span class="raio-x__m-val">' + tempStr + '</span></div>';
      html += '<div class="raio-x__metric"><span class="raio-x__m-label">Last</span><span class="raio-x__m-val">' + age + '</span></div>';
      html += '<div class="raio-x__metric"><span class="raio-x__m-label">Up</span><span class="raio-x__m-val">' + uptime + '</span></div>';
      if (effStr) {
        html += '<div class="raio-x__metric raio-x__metric--wide"><span class="raio-x__m-label">Eff</span><span class="raio-x__m-val">' + effStr + '</span></div>';
      }
      html += '</div></div>';
    });

    grid.innerHTML = html;
    if (count) {
      var totalHrStr = totalHr >= 1e12 ? (totalHr/1e12).toFixed(2) + ' TH/s' : totalHr >= 1e9 ? (totalHr/1e9).toFixed(2) + ' GH/s' : totalHr + ' H/s';
      count.textContent = workers.length + ' miners · ' + online + ' online · ' + totalHrStr;
    }
  }

function renderPool(pool, luck) {
    if (!pool) return;
    // ── FASE 1: Stale data indicator ──
    const isStale = pool._stale === true;
    const panel = document.getElementById('pool-overview');
    if (panel) {
      panel.classList.toggle('is-stale', isStale);
      if (isStale && dom.pStaleBadge) {
        dom.pStaleBadge.textContent = 'STALE (' + (pool._stale_since_ts ? fmt.age(pool._stale_since_ts) : 'old') + ')';
        dom.pStaleBadge.style.display = 'inline';
      } else if (dom.pStaleBadge) {
        dom.pStaleBadge.style.display = 'none';
      }
    }
    if (dom.pHashrate) dom.pHashrate.textContent = fmt.hashrate(pool.hashrate);
    if (dom.pWorkers) dom.pWorkers.textContent = `${pool.workers || 0} / ${pool.users || 0}`;
    if (dom.pHighDiff) dom.pHighDiff.textContent = fmt.diff(pool.highestDiff);
    // FIX: p-last-block — truncate hash to short label + show full hash on hover
    if (dom.pLastBlock) {
      // Use lastBlockTime as block number (API returns height, not timestamp)
      var blockNum = pool.lastBlockTime || 0;
      var refHash = pool.lastBlockHash || '';
      dom.pLastBlock.textContent = blockNum > 0 ? '#' + blockNum.toLocaleString() : '\u2014';
      dom.pLastBlock.title = refHash || '';
    }
    if (dom.pLastBlockTime && pool.lastBlockTime) dom.pLastBlockTime.textContent = fmt.age(pool.lastBlockTime);
    // FIX: p-work-fill — use round_progress_pct from luck_estimate
    if (dom.pWorkFill && luck && luck.round_progress_pct != null) {
      var pct = Math.min(100, Math.max(0, luck.round_progress_pct));
      dom.pWorkFill.style.width = pct + '%';
    }
    // FIX: p-work-num — format workSinceLastBlock
    if (dom.pWorkNum) {
      var w = Number(pool.workSinceLastBlock) || 0;
      dom.pWorkNum.textContent = w > 0 ? fmt.diff(w) + ' work' : '\u2014';
    }
  }

  function renderNetwork(net) {
    if (!net) return;
    if (dom.nHeight) dom.nHeight.textContent = net.height ? `#${net.height}` : '\u2014';
    if (dom.nDiff) dom.nDiff.textContent = fmt.diff(net.difficulty);
    if (dom.nHashrate) dom.nHashrate.textContent = fmt.hashrate(net.hashrate);
    _staleChip(dom.nDiff, net.stale, 'dados em cache');
  }

function renderAccount(acct) {
  if (!acct) return;
  if (dom.acctLn) dom.acctLn.textContent = acct.ln_address || acct.lightning || '\u2014';
  if (dom.acctTotalDiff) dom.acctTotalDiff.textContent = fmt.diff(acct.total_diff || acct.totalDifficulty);
  if (dom.acctHighestBlock) dom.acctHighestBlock.textContent = acct.metadata?.highest_blockheight != null ? '#' + Number(acct.metadata.highest_blockheight).toLocaleString() : '\u2014';
  // C3: Calculate approximate rank from block_count relative to leaderboard
  // If diff_rank is not provided by backend, estimate from metadata.block_count
  if (dom.acctDiffRank) {
    var rank = acct.diff_rank || acct.diffRank;
    if (!rank || rank === '\u2014') {
      var bc = (acct.metadata && acct.metadata.block_count) || 0;
      if (bc >= 10000) rank = 'TOP 1%';
      else if (bc >= 1000) rank = 'TOP 10%';
      else if (bc >= 100) rank = 'TOP 25%';
      else if (bc > 0) rank = 'ACTIVE';
      else rank = '\u2014';
    }
    dom.acctDiffRank.textContent = rank;
  }
  if (dom.acctLoyaltyRank) dom.acctLoyaltyRank.textContent = acct.loyalty_rank || acct.loyaltyRank || '\u2014';
  if (dom.acctBlocksBadge) {
    var bc = acct.metadata?.block_count || acct.blocks_found || 0;
    dom.acctBlocksBadge.textContent = Number(bc).toLocaleString() + ' BLOCK' + (Number(bc) !== 1 ? 'S' : '');
  }
}

  // Stale-while-revalidate badge: when the backend serves the last REAL
  // cached value (provider briefly down), show an honest "dados em cache"
  // chip instead of pretending the number is live. Each element owns its own
  // chip (el._staleChipEl) so sibling fields in the SAME parent row (e.g.
  // sbNetDiff + sbNetPrice) never remove/overwrite each other's chip.
  function _staleChip(el, stale, label) {
    if (!el) return;
    if (!stale) {
      if (el._staleChipEl) {
        el._staleChipEl.remove();
        el._staleChipEl = null;
      }
      return;
    }
    if (!el._staleChipEl) {
      el._staleChipEl = document.createElement('span');
      el._staleChipEl.className = 'stale-chip';
      el.after(el._staleChipEl);
    }
    el._staleChipEl.textContent = label || 'dados em cache';
    el._staleChipEl.title = 'Fonte externa indisponível — exibindo o último valor real coletado';
  }

  function renderBtcPrices(btc) {
    // Call _staleChip BEFORE the early return so an orphan chip is removed
    // when a later snapshot arrives without a btc_price block (honest state).
    _staleChip(dom.nBtcUsd, !!(btc && btc.stale), 'preço em cache');
    if (!btc) return;
    if (dom.nBtcUsd) dom.nBtcUsd.textContent = btc.usd ? `$${Number(btc.usd).toLocaleString()}` : '\u2014';
    if (dom.nBtcBrl) dom.nBtcBrl.textContent = btc.brl ? `R$${Number(btc.brl).toLocaleString()}` : '\u2014';
    if (dom.nBtcEur) dom.nBtcEur.textContent = btc.eur ? `€${Number(btc.eur).toLocaleString()}` : '\u2014';
    if (dom.nBtcGbp) dom.nBtcGbp.textContent = btc.gbp ? `£${Number(btc.gbp).toLocaleString()}` : '\u2014';
  }

  function renderHalving(h) {
    if (!h) return;
    if (dom.hBlocks) dom.hBlocks.textContent = h.blocks_remaining != null ? h.blocks_remaining.toLocaleString() : '\u2014';
    if (dom.hDays) dom.hDays.textContent = h.estimated_days_remaining != null ? `${Math.round(h.estimated_days_remaining)}d` : '\u2014';
    if (dom.hCurReward) dom.hCurReward.textContent = h.current_reward_btc != null ? `${h.current_reward_btc} BTC` : '\u2014';
    if (dom.hNextReward) dom.hNextReward.textContent = h.next_reward_btc != null ? `${h.next_reward_btc} BTC` : '\u2014';
    if (dom.hNextHeight) dom.hNextHeight.textContent = h.next_height != null ? `#${h.next_height.toLocaleString()}` : '\u2014';
  }

  function renderMempoolFees(f) {
    if (!f) return;
    const set = (el, v) => { if (el) el.textContent = v != null ? `${v} sat/vB` : '\u2014'; };
    set(dom.feeEconomy, f.economyFee); set(dom.feeHour, f.hourFee); set(dom.feeHalfhour, f.halfHourFee);
    set(dom.feeFastest, f.fastestFee); set(dom.feeMinimum, f.minimumFee);
  }

  function renderAlerts(alerts) {
    if (!dom.alertsList) return;
    if (!alerts || !alerts.length) {
      dom.alertsList.innerHTML = '<li class="alert-empty">no alerts — all systems nominal</li>';
      if (dom.alertsCountBadge) dom.alertsCountBadge.textContent = '0 active';
      return;
    }
    if (dom.alertsCountBadge) dom.alertsCountBadge.textContent = `${alerts.length} active`;
    dom.alertsList.innerHTML = alerts.slice(0, 10).map(a => `
      <li class="alert-item SEVERITY-${a.severity || 'INFO'}">
        <span class="alert-icon">!</span><span class="alert-msg">${escapeHtml(a.message || '')}</span><span class="alert-time">${fmt.age(a.ts)}</span>
      </li>`).join('');
  }

  function renderEvents(events) {
    if (!dom.eventsTbody) return;
    if (!events || !events.length) { dom.eventsTbody.innerHTML = '<tr><td colspan="5" class="empty">awaiting data\u2026</td></tr>'; return; }
    dom.eventsTbody.innerHTML = events.map(e => `<tr><td>#${e.block_height || e.block || '\u2014'}</td><td>${fmt.shortAddr(e.address || '')}</td><td>${fmt.diff(e.difficulty)}</td><td>${fmt.age(e.block_timestamp || e.ts)}</td><td>${e.claimed ? 'YES' : 'NO'}</td></tr>`).join('');
  }

  function renderLeaderboard(lb) {
    if (!dom.lbTbody) return;
    if (!lb || !lb.length) { dom.lbTbody.innerHTML = '<tr><td colspan="6" class="empty">awaiting data\u2026</td></tr>'; return; }
    dom.lbTbody.innerHTML = lb.map((r, i) => `<tr><td>${i+1}</td><td>${fmt.shortAddr(r.address)}</td><td>${r.diff_rank || r.diffRank || '\u2014'}</td><td>${r.loyalty_rank || r.loyalty || '\u2014'}</td><td>${r.combined_score || r.score || '\u2014'}</td><td>${r.total_blocks || r.blocks || 0}</td></tr>`).join('');
  }

  // ── Charts — renderChart fetches data and updates Chart.js instances ──
  const CHART_METRICS = {
    'chart-hashrate': { chart: 'hashrate', label: 'Worker Hashrate', color: 'rgb(6,214,240)' },
    'chart-pool': { chart: 'pool', label: 'Pool Hashrate', color: 'rgb(247,147,26)' },
    'chart-bestdiff': { chart: 'bestdiff', label: 'Best Difficulty', color: 'rgb(16,185,129)' },
    'chart-net': { chart: 'net', label: 'Network Difficulty', color: 'rgb(168,85,247)' },
    'chart-cumulative-p': { chart: 'cum_p', label: 'Cumulative P(Block)', color: 'rgb(168,85,247)' },
    'chart-share-dist': { chart: 'share_dist', label: 'Share Difficulty', color: 'rgb(16,185,129)' },
  };
  async function loadChartData(id) {
    const cfg = CHART_METRICS[id];
    if (!cfg) return;
    try {
      const r = await fetch(`/api/chart-data?chart=${cfg.chart}&range=1h`);
      if (!r.ok) return;
      const data = await r.json();
      const chart = charts[id];
      if (!chart) return;
      const rawLabels = (data.labels || []);
      const values = (data.datasets?.[0]?.data || data.datasets?.[0]?.values || []);
      chart.data.labels = rawLabels.map(t => {
        if (cfg.chart === 'share_dist') return String(t); // histogram bucket labels
        const d = new Date(t); return d.getHours()+':'+String(d.getMinutes()).padStart(2,'0');
      });
      chart.data.datasets[0].data = values;
      // Fase 2.1: SMA overlay + shares bar + event annotations
      if (chart.data.datasets[1] && cfg.chart !== 'share_dist') {
        chart.data.datasets[1].data = computeSMA(values, Math.max(3, Math.round(values.length / 10)));
      }
      if (chart.data.datasets[2] && Array.isArray(data.shares)) {
        chart.data.datasets[2].data = data.shares;
        chart.options.scales.y1.display = data.shares.some(s => s > 0);
      }
      chart._annotations = buildChartAnnotations(data.events || [], rawLabels);
      chart.update('none');
    } catch (e) { /* chart load silently */ }
  }
  function renderCharts() {
    // Charts can only be measured when their canvases are visible.
    // In module-mode the tab panes are controlled by activateModule();
    // in legacy tab mode they are gated by the .active class.
    var chartsTab = document.getElementById('tab-charts');
    var inModuleMode = document.body.classList.contains('module-mode');
    if (!chartsTab) return;
    if (!inModuleMode && !chartsTab.classList.contains('active')) return;
    Object.keys(CHART_METRICS).forEach(id => {
      const canvas = document.getElementById(id);
      if (!canvas) return;
      // Pula canvases dentro de painéis ocultos (outro módulo) —
      // Chart.js não consegue medir display:none
      if (inModuleMode && canvas.offsetParent === null) return;
      // init chart if not yet created
      if (!charts[id]) {
        const cfg = CHART_METRICS[id];
        charts[id] = makeChart(id, cfg.label, cfg.color);
      }
      loadChartData(id);
    });
  }

  // ── Live Log ──
  let events = []; let renderedEventCount = 0;
  function logMessage(tag, msg, sev) {
    const now = new Date();
    const ts = String(now.getHours()).padStart(2,'0')+':'+String(now.getMinutes()).padStart(2,'0')+':'+String(now.getSeconds()).padStart(2,'0');
    const cls = `tag-${(sev || 'info').toLowerCase()}`;
    const line = `<div class="terminal__line"><span class="ts">[${ts}]</span><span class="tag ${cls}">${tag}</span>${escapeHtml(msg)}</div>`;
    events.push(line); renderedEventCount++;
    if (dom.terminal) {
      dom.terminal.insertAdjacentHTML('beforeend', line);
      while (renderedEventCount > 100) { const f = dom.terminal.querySelector('.terminal__line'); if (!f) break; f.remove(); renderedEventCount--; }
      dom.terminal.scrollTop = dom.terminal.scrollHeight;
    }
    if (dom.logEventsCount) dom.logEventsCount.textContent = `${renderedEventCount} events`;
  }

  // ── Global error boundary (Fase 1.2 · UI audit) ─────────────────────
  // The dashboard had no global safety net: a render exception or an
  // unhandled promise rejection died silently, leaving a frozen panel with
  // zero signal. These handlers catch both and surface them in the Live Log
  // (tag ERROR) instead of failing silently. Best-effort by design: the
  // handlers are wrapped so a logging failure can never recurse into itself.
  // Throttled so a repeating error (e.g. a broken poll payload) logs once per
  // window instead of spamming 1000 lines/min.
  const _EB_MAX_PER_MIN = 5;
  const _EB_WINDOW_MS = 60000;
  const _ebRecent = {};  // msgKey → { count, firstTs }

  // Pure: converts any thrown value / event into { msg, sev } for the log.
  // Mirrored in tests/test_app_js_core.js (formatClientErrorMirror).
  function formatClientError(err) {
    if (err == null) return { msg: 'unknown error', sev: 'WARN' };
    if (typeof err === 'string') return { msg: err.slice(0, 200), sev: 'WARN' };
    if (err instanceof Error) {
      return { msg: String(err.message || err).slice(0, 200), sev: 'WARN' };
    }
    // ErrorEvent ('error') carries message + filename/lineno; keep the file
    // short (basename:line) so the terminal line stays readable.
    if (typeof err === 'object' && err !== null) {
      if (err.reason != null && err.reason !== err) return formatClientError(err.reason);
      if (err.message) {
        let m = String(err.message);
        if (err.filename) {
          const base = String(err.filename).split('/').pop();
          m += ` (${base}:${err.lineno || '?'})`;
        }
        return { msg: m.slice(0, 200), sev: 'WARN' };
      }
      // Event object with no message/reason (e.g. bare PromiseRejectionEvent)
      // — a clean fallback beats logging "[object X]" garbage.
      return { msg: 'unhandled error (no message)', sev: 'WARN' };
    }
    try { return { msg: String(err).slice(0, 200), sev: 'WARN' }; }
    catch (e) { return { msg: 'unknown error', sev: 'WARN' }; }
  }

  function _ebThrottled(msg) {
    const now = Date.now();
    const key = String(msg).slice(0, 80);
    const hit = _ebRecent[key];
    if (hit && now - hit.firstTs < _EB_WINDOW_MS) {
      if (hit.count >= _EB_MAX_PER_MIN) return false;
      hit.count++;
    } else {
      _ebRecent[key] = { count: 1, firstTs: now };
    }
    // Keep the throttle map bounded on long-running dashboards.
    if (Object.keys(_ebRecent).length > 200) {
      for (const k of Object.keys(_ebRecent)) {
        if (now - _ebRecent[k].firstTs > _EB_WINDOW_MS) delete _ebRecent[k];
      }
    }
    return true;
  }

  function _surfaceClientError(source, err) {
    try {
      const { msg, sev } = formatClientError(err);
      const full = (source ? `[${source}] ` : '') + msg;
      if (_ebThrottled(full)) logMessage('ERROR', full, sev);
    } catch (e) { /* never let the boundary itself throw */ }
  }

  // Register once — errors that occur before this point (very early boot) are
  // not caught, which is acceptable: the boundary covers runtime failures.
  window.addEventListener('error', function (e) {
    // Only surface real JS runtime errors. The 'error' event ALSO fires for
    // resource-load failures (broken <script>/<img>/CSS or cross-origin
    // scripts), where e.target is the failing element and the message is
    // empty/'Script error.' — those aren't exceptions and would spam the
    // Live Log with noise. A real window error has e.target === window.
    if (e && e.target && e.target !== window) return;
    _surfaceClientError('window', e);
  });
  window.addEventListener('unhandledrejection', function (e) {
    _surfaceClientError('promise', e);
  });

  document.getElementById('clear-logs')?.addEventListener('click', () => {
    events.length = 0; renderedEventCount = 0;
    dom.terminal.innerHTML = '<div class="terminal__line ts-mute">cleared</div>';
    dom.logEventsCount.textContent = '0 events';
  });

  // ── Timeline ──
  const TIMELINE_MAX = 80; const timelineIdsRendered = new Set(); let timelineTotalRendered = 0;
  // ── Normalize timeline event: handle both {ts, type, message} and [ts, type, severity, message] formats ──
  function _normalizeTimelineEvent(e) {
    if (Array.isArray(e)) {
      // Format from backend: [ts, event_type, severity, message] or [ts, event_type, message]
      return { id: e[0] + '_' + String(Math.random()).slice(2, 8), ts: e[0], event_type: e[1] || 'EVENT', severity: e[2] || 'INFO', message: e.length > 3 ? e[3] : (e[2] || '') };
    }
    return e; // already an object
  }

  function renderTimelineFeed(list) {
    if (!dom.timelineFeed) return;
    if (!list || !list.length) return;
    // Normalize all events first (handle array format from backend)
    const normalized = list.map(_normalizeTimelineEvent);
    const ordered = normalized.slice().reverse();
    const newOnes = ordered.filter(e => !timelineIdsRendered.has(e.id));
    if (!newOnes.length) return;
    const rows = newOnes.map(ev => {
      const d = new Date((ev.ts || 0) * 1000);
      const ts = String(d.getHours()).padStart(2,'0')+':'+String(d.getMinutes()).padStart(2,'0')+':'+String(d.getSeconds()).padStart(2,'0');
      return `<div class="timeline-row tf-${(ev.severity||'INFO').toLowerCase()}" data-id="${ev.id}"><span class="tf-time">${ts}</span><span class="tf-type">${ev.event_type||'EVENT'}</span><span class="tf-msg">${escapeHtml(ev.message||'')}</span></div>`;
    }).join('');
    if (timelineTotalRendered === 0) dom.timelineFeed.innerHTML = '';
    dom.timelineFeed.insertAdjacentHTML('beforeend', rows);
    newOnes.forEach(e => timelineIdsRendered.add(e.id)); timelineTotalRendered += newOnes.length;
    while (timelineTotalRendered > TIMELINE_MAX) { const f = dom.timelineFeed.querySelector('.timeline-row'); if (!f) break; f.remove(); timelineTotalRendered--; }
    dom.timelineFeed.scrollTop = dom.timelineFeed.scrollHeight;
  }

  // ── EVENT STREAM — mirror of timeline_last_n into the terminal panel ──
  function renderTerminalEvents(list) {
    if (!dom.terminalEventsList) return;
    if (!list || !list.length) {
      dom.terminalEventsList.innerHTML = '<div class="terminal-empty">awaiting events from pool polling...</div>';
      if (dom.terminalEventCount) dom.terminalEventCount.textContent = '0';
      return;
    }
    const normalized = list.map(_normalizeTimelineEvent);
    const ordered = normalized.slice().reverse();
    const rows = ordered.slice(0, 60).map(ev => {
      const d = new Date((ev.ts || 0) * 1000);
      const ts = String(d.getHours()).padStart(2,'0')+':'+String(d.getMinutes()).padStart(2,'0')+':'+String(d.getSeconds()).padStart(2,'0');
      const sev = (ev.severity || 'INFO').toLowerCase();
      return `<div class="terminal-events-row"><span class="ts">[${ts}]</span><span class="tag tag-${sev}">${escapeHtml(ev.event_type || 'EVENT')}</span>${escapeHtml(ev.message || '')}</div>`;
    }).join('');
    dom.terminalEventsList.innerHTML = rows;
    if (dom.terminalEventCount) dom.terminalEventCount.textContent = String(normalized.length);
  }

  // ══════════════════════════════════════════════════════════════════════
  // HASH PROXIMITY METER — best diff vs network difficulty
  // ══════════════════════════════════════════════════════════════════════

  function renderProximity(prox) {
    if (!prox || !dom.proxHeroPct) return;
    if (prox.insufficient_data) return;

    // Badges
    if (dom.proxPctBadge) dom.proxPctBadge.textContent = prox.pct_of_network_cur != null ? prox.pct_of_network_cur.toFixed(6) + '% of network' : '—';
    if (dom.proxAlltimeBadge) dom.proxAlltimeBadge.textContent = prox.all_time_best_diff_str ? 'peak ' + prox.all_time_best_diff_str : 'peak —';
    if (dom.proxStreakBadge) dom.proxStreakBadge.textContent = prox.hot_streak ? 'hot streak!' : 'streak —';

    // Hero
    if (dom.proxHeroPct) dom.proxHeroPct.textContent = prox.pct_of_network_cur != null ? prox.pct_of_network_cur.toFixed(4) + '%' : '—';
    if (dom.proxHeroSub) dom.proxHeroSub.textContent = prox.next_milestone_label || 'of network difficulty';
    if (dom.proxHeroBest) dom.proxHeroBest.textContent = 'best ' + (prox.all_time_best_diff_str || '—');

    // SVG arc — animate stroke-dashoffset
    const arc = dom.proxArc;
    if (arc) {
      const pct = Math.min(100, prox.pct_of_network_cur || 0);
      const circumference = 2 * Math.PI * 90; // r=90 from SVG
      const offset = circumference * (1 - pct / 100);
      arc.setAttribute('stroke-dasharray', circumference);
      arc.setAttribute('stroke-dashoffset', offset);
      // Color based on progress
      if (pct > 50) arc.setAttribute('stroke', '#f5b942');
      else if (pct > 10) arc.setAttribute('stroke', '#06d6f0');
      else arc.setAttribute('stroke', 'rgba(6,214,240,0.5)');
    }

    // Tip on arc
    if (dom.proxTip) {
      const pct = Math.min(100, prox.pct_of_network_cur || 0);
      const angle = Math.PI - (pct / 100) * Math.PI; // top=0, bottom=PI
      const r = 90, cx = 110, cy = 110;
      const tx = cx + r * Math.cos(angle);
      const ty = cy - r * Math.sin(angle);
      dom.proxTip.setAttribute('cx', tx);
      dom.proxTip.setAttribute('cy', ty);
      dom.proxTip.setAttribute('opacity', '1');
    }

    // Side stats
    if (dom.proxChance) dom.proxChance.textContent = prox.chance_per_share_label || '—';
    if (dom.proxTime) dom.proxTime.textContent = prox.expected_time_human || '—';
    if (dom.proxTimeSub && prox.blocks_per_year != null) {
      dom.proxTimeSub.textContent = '~' + prox.blocks_per_year.toFixed(4) + ' blocks/yr @ current HR';
    }
    if (dom.proxDistance) dom.proxDistance.textContent = prox.distance_label || '—';
    if (dom.proxTrend) dom.proxTrend.textContent = (prox.trend_1h_pct != null ? (prox.trend_1h_pct >= 0 ? '+' : '') + prox.trend_1h_pct.toFixed(1) + '%' : '—') + ' · ' + (prox.trend_label || 'flat');
    if (dom.proxTrendSub) dom.proxTrendSub.textContent = '1h change vs. network';

    // Milestone ladder
    if (dom.proxLadderRow) {
      const milestones = prox.milestones_achieved || [];
      const next = prox.next_milestone_pct;
      dom.proxLadderRow.innerHTML = milestones.map(m => '<span class="prox-ladder__step prox-ladder__step--done">' + (m >= 1 ? m.toFixed(0) + '%' : m.toFixed(2) + '%') + '</span>').join('')
        + (next != null ? '<span class="prox-ladder__step prox-ladder__step--next">' + (next >= 1 ? next.toFixed(0) + '%' : next.toFixed(2) + '%') + '</span>' : '');
    }

    // Sparkline canvas
    _drawProximitySparkline(prox);
  }

  let _proxSparklineData = [];
  function _drawProximitySparkline(prox) {
    const c = dom.proxSparkline;
    if (!c) return;
    // Add current data point
    const cur = prox.pct_of_network_cur || 0;
    _proxSparklineData.push(cur);
    if (_proxSparklineData.length > 180) _proxSparklineData.shift(); // 3h at 1/min

    const dpr = window.devicePixelRatio || 1;
    // Read the CSS box size (fixed by the #prox-sparkline rule) instead of
    // relying on clientHeight, which can mirror the canvas attribute and
    // grow unboundedly on high-DPI displays.
    const cs = getComputedStyle(c);
    const cssW = parseFloat(cs.width) || c.clientWidth || 220;
    const cssH = parseFloat(cs.height) || c.clientHeight || 28;
    c.width = Math.round(cssW * dpr); c.height = Math.round(cssH * dpr);
    const ctx = c.getContext('2d');
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, cssW, cssH);

    const data = _proxSparklineData;
    if (data.length < 2) return;
    const h = cssH - 4;
    const max = Math.max(...data, 0.001);
    const x = (i) => 2 + (i / Math.max(1, data.length - 1)) * (cssW - 4);
    const y = (v) => cssH - 2 - (v / max) * h;

    // Fill
    const grad = ctx.createLinearGradient(0, 0, 0, cssH);
    grad.addColorStop(0, 'rgba(6,214,240,0.25)');
    grad.addColorStop(1, 'rgba(6,214,240,0)');
    ctx.fillStyle = grad;
    ctx.beginPath();
    ctx.moveTo(x(0), cssH);
    data.forEach((v, i) => ctx.lineTo(x(i), y(v)));
    ctx.lineTo(x(data.length - 1), cssH);
    ctx.closePath();
    ctx.fill();

    // Line
    ctx.strokeStyle = '#06d6f0';
    ctx.lineWidth = 1;
    ctx.beginPath();
    data.forEach((v, i) => i === 0 ? ctx.moveTo(x(i), y(v)) : ctx.lineTo(x(i), y(v)));
    ctx.stroke();

    // Dot at latest
    ctx.fillStyle = '#06d6f0';
    ctx.beginPath();
    ctx.arc(x(data.length - 1), y(data[data.length - 1]), 2.5, 0, Math.PI * 2);
    ctx.fill();
  }

  // ══════════════════════════════════════════════════════════════════════
  // QUANTUM LOCK HEALTH SCORE — composite confidence score (0-100)
  // ══════════════════════════════════════════════════════════════════════

  function renderQuantumLock(prox) {
    if (!prox || !dom.qlStatusBadge) return;
    const ql = prox.quantum_lock;
    if (!ql || !ql.score) {
      if (dom.qlStatusBadge) dom.qlStatusBadge.textContent = 'NO DATA';
      if (dom.qlScoreBadge) dom.qlScoreBadge.textContent = '0/100';
      if (dom.qlBarFill) dom.qlBarFill.style.width = '0%';
      if (dom.qlLabel) dom.qlLabel.textContent = 'awaiting share data — submit share to compute quantum lock';
      _setQlComp('ql-comp-shares', 0, 30);
      _setQlComp('ql-comp-prox', 0, 40);
      _setQlComp('ql-comp-power', 0, 20);
      _setQlComp('ql-comp-momentum', 0, 10);
      return;
    }
    const score = Math.min(100, Math.max(0, Number(ql.score) || 0));
    if (dom.qlStatusBadge) dom.qlStatusBadge.textContent = ql.status || 'TRACKING';
    if (dom.qlScoreBadge) dom.qlScoreBadge.textContent = Math.round(score) + '/100';
    if (dom.qlBarFill) dom.qlBarFill.style.width = score + '%';
    if (dom.qlLabel) dom.qlLabel.textContent = ql.label || '';
    const comps = ql.components || {};
    _setQlComp('ql-comp-shares', comps.shares, 30);
    _setQlComp('ql-comp-prox', comps.proximity, 40);
    _setQlComp('ql-comp-power', comps.power, 20);
    _setQlComp('ql-comp-momentum', comps.momentum, 10);
  }

  function _setQlComp(barId, val, max) {
    const bar = document.getElementById(barId);
    if (!bar) return;
    const fill = bar.querySelector('span');
    if (!fill) return;
    const pct = Math.min(100, Math.max(0, (Number(val) || 0) / max * 100));
    fill.style.width = pct + '%';
  }

  // ══════════════════════════════════════════════════════════════════════
  // LIVE HASH CALCULATOR — per-share breakdown from proximity.live_calc
  // ══════════════════════════════════════════════════════════════════════

  function renderLiveCalc(prox) {
    if (!prox || !dom.lcShareDiff) return;
    const lc = prox.live_calc || {};
    const latest = lc.latest || {};
    const totals = lc.session_totals || {};
    const dash = '\u2014';

    // Latest per-share breakdown
    if (dom.lcTimeBig) dom.lcTimeBig.textContent = latest.ts ? fmt.age(latest.ts) : dash;
    if (dom.lcSessionShareCount) dom.lcSessionShareCount.textContent = latest.session_share_count_at_time != null ? 'share #' + latest.session_share_count_at_time : dash;
    if (dom.lcShareDiff) dom.lcShareDiff.textContent = latest.share_diff_str || dash;
    if (dom.lcHashes) dom.lcHashes.textContent = latest.hashes_attempted_str || dash;
    if (dom.lcTimeObs) dom.lcTimeObs.textContent = latest.gap != null ? latest.gap + 's' : dash;
    if (dom.lcPBlock) dom.lcPBlock.textContent = latest.p_block_this_share_pct_str || dash;
    if (dom.lcInstHr) dom.lcInstHr.textContent = latest.instantaneous_hr_str || dash;

    // Session totals
    if (dom.lcSessionShares) dom.lcSessionShares.textContent = totals.shares_so_far != null ? totals.shares_so_far : dash;
    if (dom.lcAvgShareDiff) dom.lcAvgShareDiff.textContent = totals.avg_share_diff_str || dash;
    if (dom.lcCumP) dom.lcCumP.textContent = totals.cum_p_block_pct_str || dash;
    if (dom.lcExpectedBlocks) dom.lcExpectedBlocks.textContent = totals.expected_blocks_str || dash;

    // Ticker — newest first
    if (dom.lcTickerList) {
      const ticker = (lc.ticker || []).slice().reverse();
      if (!ticker.length) {
        dom.lcTickerList.innerHTML = '<div class="prox-live-calc__ticker-empty">awaiting share data</div>';
      } else {
        dom.lcTickerList.innerHTML = ticker.map(function(e) {
          return '<div class="lc-ticker-row">' +
            '<span class="lc-ticker-time">' + (e.ts ? fmt.age(e.ts) : '--:--:--') + '</span>' +
            '<span class="lc-ticker-diff">' + (e.share_diff_str || dash) + '</span>' +
            '<span class="lc-ticker-gap">\u0394' + (e.gap || '\u2014') + 's</span>' +
            '<span class="lc-ticker-hr">' + (e.instantaneous_hr_str || dash) + '</span>' +
            '</div>';
        }).join('');
      }
    }
  }

  // ══════════════════════════════════════════════════════════════════════
  // NETWORK SHARE GAUGE — 3 semi-circular canvas gauges
  // ══════════════════════════════════════════════════════════════════════

  function renderNetworkGauge(snap) {
    const gauge = snap.network_share_gauge;
    const luck = snap.luck_estimate || {};
    const worker = snap.worker || {};
    const pool = snap.pool || {};
    const net = snap.network || {};

    if (dom.gaugeLabel && gauge) dom.gaugeLabel.textContent = gauge.label || '—';

    // Worker gauge
    if (dom.gaugeWorkerPct && gauge) dom.gaugeWorkerPct.textContent = (gauge.worker_pct || 0).toFixed(6) + '%';
    if (dom.gaugeWorkerBlockchance && worker.hashrate && net.difficulty) {
      const hr = Number(worker.hashrate) || 0;
      const diff = Number(net.difficulty) || 1;
      const p22min = 1 - Math.exp(-(hr * 1320) / (diff * Math.pow(2, 32)));
      dom.gaugeWorkerBlockchance.textContent = p22min > 0 ? (p22min * 100).toFixed(4) + '%' : '~0%';
    }
    _drawGauge('gauge-worker-canvas', gauge && gauge.worker_pct ? gauge.worker_pct : 0);

    // Pool gauge
    if (dom.gaugePoolPct && gauge) dom.gaugePoolPct.textContent = (gauge.pool_pct || 0).toFixed(4) + '%';
    _drawGauge('gauge-pool-canvas', gauge && gauge.pool_pct ? gauge.pool_pct : 0);

    // Luck gauge
    const luckPct = luck.round_progress_pct || luck.pool_luck_pct || 0;
    if (dom.gaugeLuckPct) dom.gaugeLuckPct.textContent = luckPct.toFixed(1) + '%';
    _drawGauge('gauge-luck-canvas', Math.min(150, luckPct));
  }

  function _drawGauge(canvasId, pct) {
    const c = document.getElementById(canvasId);
    if (!c) return;
    const dpr = window.devicePixelRatio || 1;
    const cssW = c.clientWidth || 180, cssH = c.clientHeight || 100;
    c.width = cssW * dpr; c.height = cssH * dpr;
    const ctx = c.getContext('2d');
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, cssW, cssH);

    const cx = cssW / 2, cy = cssH - 8;
    const r = Math.min(cx - 10, cssH - 12);
    const displayPct = Math.min(100, Math.max(0, pct));

    // Background arc
    ctx.beginPath();
    ctx.arc(cx, cy, r, Math.PI, 0, false);
    ctx.strokeStyle = 'rgba(255,255,255,0.06)';
    ctx.lineWidth = 12;
    ctx.lineCap = 'round';
    ctx.stroke();

    // Value arc
    const angle = Math.PI - (displayPct / 100) * Math.PI;
    const grad = ctx.createLinearGradient(cx - r, 0, cx + r, 0);
    grad.addColorStop(0, '#00ff9f');
    grad.addColorStop(0.5, '#06d6f0');
    grad.addColorStop(1, '#f5b942');
    ctx.beginPath();
    ctx.arc(cx, cy, r, Math.PI, angle, false);
    ctx.strokeStyle = grad;
    ctx.lineWidth = 12;
    ctx.stroke();

    // Center label
    ctx.fillStyle = '#f0f0f0';
    ctx.font = 'bold 13px Space Grotesk';
    ctx.textAlign = 'center';
    ctx.fillText(displayPct.toFixed(displayPct < 1 ? 4 : 1) + '%', cx, cy - 6);
  }

  // ── Profitability mode state (POOL | SOLO | RENTAL) ───────────────────
  // Pure selector: returns the values to display for a given mode.
  // Isolated so unit tests can exercise the mode math without DOM.
  let _profitMode = 'pool';
  let _lastProfitability = null;

  function profitModeView(p, mode) {
    if (!p || !Object.keys(p).length) return null;
    const m = (mode === 'solo' || mode === 'rental' || mode === 'lender') ? mode : 'pool';
    const view = { mode: m, btcDay: null, fiatDay: {}, fiatWeek: {}, fiatMonth: {}, breakeven: null, soloStats: null, lenderStats: null };
    if (m === 'solo') {
      view.btcDay = p.net_btc_per_day_solo;
      view.fiatDay = p.fiat_per_day_solo || {};
      view.fiatMonth = p.fiat_per_month_solo || {};
      view.breakeven = null; // solo has no rental break-even — expected time shown instead
      view.soloStats = {
        pToday: p.solo_p_day_pct,
        pYear: p.solo_p_year_pct,
        p5y: p.solo_p_5year_pct,
        blocksYear: p.solo_expected_blocks_per_year,
        expectedDays: p.solo_expected_time_to_block_days,
      };
    } else if (m === 'rental') {
      view.btcDay = p.net_btc_per_day_rental;
      view.fiatDay = p.fiat_per_day_rental || {};
      view.fiatMonth = p.fiat_per_month_rental || {};
      view.breakeven = p.break_even_rental_usd_per_th_day;
    } else if (m === 'lender') {
      view.btcDay = p.lender_net_btc_per_day;
      view.fiatDay = p.lender_fiat_per_day || {};
      view.fiatMonth = p.lender_fiat_per_month || {};
      view.breakeven = p.lender_breakeven_usd_per_th_day;
      view.lenderStats = {
        marketRateUsd: p.lender_market_rate_usd_per_th_day,
        leaseNetUsd: p.lender_net_usd_per_day,
        mineNetUsd: p.lender_mine_net_usd_per_day,
        vsMiningUsd: p.lender_vs_mining_usd_per_day,
        recommendation: p.lender_recommendation,
      };
    } else {
      view.btcDay = p.net_btc_per_day_pool;
      view.fiatDay = p.fiat_per_day_pool || {};
      view.fiatMonth = p.fiat_per_month_pool || {};
      view.breakeven = p.breakeven_cost_per_th_day;
    }
    // Weekly fiat = daily × 7 (client-side; backend only ships daily/monthly per mode)
    Object.keys(view.fiatDay).forEach(c => {
      view.fiatWeek[c] = view.fiatDay[c] != null ? view.fiatDay[c] * 7 : null;
    });
    return view;
  }

  function setProfitMode(mode) {
    if (!['pool', 'solo', 'rental', 'lender'].includes(mode)) return;
    _profitMode = mode;
    document.querySelectorAll('.profit-mode-btn').forEach(b => {
      b.classList.toggle('active', b.getAttribute('data-mode') === mode);
    });
    const soloStats = document.getElementById('solo-extra-stats');
    if (soloStats) soloStats.style.display = mode === 'solo' ? '' : 'none';
    const lenderStats = document.getElementById('lender-extra-stats');
    if (lenderStats) lenderStats.style.display = mode === 'lender' ? '' : 'none';
    if (_lastProfitability) renderProfitability(_lastProfitability);
  }
  window.setProfitMode = setProfitMode;

  function renderProfitability(p) {
    if (!p || !Object.keys(p).length) return;
    _lastProfitability = p;
    const cur = (SETTINGS_CACHE.data?.active_currency?.value) || "USD"; const symMap = {USD:"$",BRL:"R$",EUR:"€",GBP:"£"}; const sym = symMap[cur] || "$";
    const fiatPerCur = (b) => b != null ? `${sym}${Number(b).toLocaleString(undefined,{maximumFractionDigits:2})}` : '\u2014';
    const view = profitModeView(p, _profitMode);
    if (dom.pBtcDay) dom.pBtcDay.textContent = view.btcDay != null ? `${Number(view.btcDay).toFixed(8)} BTC` : '\u2014';
    if (dom.pFiatDay) dom.pFiatDay.textContent = fiatPerCur(view.fiatDay[cur]);
    if (dom.pFiatDayWeek) dom.pFiatDayWeek.textContent = fiatPerCur(view.fiatWeek[cur]) + '/week';
    if (dom.pFiatMonth) dom.pFiatMonth.textContent = fiatPerCur(view.fiatMonth[cur]);
    // Break-even: rental → max rental cost per TH/day; solo → expected time to
    // block (matches the BREAK-EVEN tooltip: 'no modo SOLO mostra o tempo
    // esperado até o próximo bloco').
    if (dom.pBreakeven) {
      if (_profitMode === 'solo' && view.soloStats && view.soloStats.expectedDays != null) {
        dom.pBreakeven.textContent = fmt.secsToHuman(view.soloStats.expectedDays * 86400);
        if (dom.pBreakevenSub) dom.pBreakevenSub.textContent = 'to block';
      } else if (_profitMode === 'solo') {
        dom.pBreakeven.textContent = '\u2014';
        if (dom.pBreakevenSub) dom.pBreakevenSub.textContent = 'to block';
      } else {
        dom.pBreakeven.textContent = view.breakeven != null ? `$${Number(view.breakeven).toFixed(4)}` : '\u2014';
        if (dom.pBreakevenSub) dom.pBreakevenSub.textContent = '$/TH·d';
      }
    }
    if (dom.profitCostBadge) dom.profitCostBadge.textContent = 'cost: ' + (p.cost_model_configured ? (p.cost_label || '$0') : '$0 (configure ⚙)');
    // Share badge: worker share of network hashrate (pool mode), else 0%
    if (dom.profitShareBadge) {
      const so = p.share_of_network_pct;
      dom.profitShareBadge.textContent = so != null && Number(so) > 0 ? Number(so).toFixed(6) + '%' : '0%';
    }
    if (dom.profitFiatRow) {
      ['USD','BRL','EUR','GBP'].forEach(c => {
        const el = document.getElementById('profit-fiat-' + c);
        if (el) el.textContent = fiatPerCur(view.fiatDay[c]);
      });
    }
    // Solo stats cells (populated whenever solo data exists — they only show
    // when setProfitMode('solo') reveals the #solo-extra-stats strip)
    if (view.soloStats) {
      const setTxt = (id, v, suffix) => {
        const el = document.getElementById(id);
        if (el) el.textContent = v != null ? `${Number(v).toLocaleString(undefined,{maximumFractionDigits:6})}${suffix || ''}` : '\u2014';
      };
      setTxt('solo-p-today', view.soloStats.pToday, '%');
      setTxt('solo-p-year', view.soloStats.pYear, '%');
      setTxt('solo-p-5y', view.soloStats.p5y, '%');
      setTxt('solo-blocks-year', view.soloStats.blocksYear);
      const expEl = document.getElementById('solo-expected-time');
      if (expEl) {
        const expDays = view.soloStats.expectedDays;
        expEl.textContent = expDays != null ? fmt.secsToHuman(expDays * 86400) : '\u2014';
      }
    }
    // Lender stats strip (Scenario D: rent OUT your own hashrate vs mining)
    if (view.lenderStats) {
      const setL = (id, v, suffix, cls) => {
        const el = document.getElementById(id);
        if (!el) return;
        el.textContent = v != null ? `$${Number(v).toLocaleString(undefined,{maximumFractionDigits:2})}${suffix || ''}` : '\u2014';
        if (cls) el.className = cls;
      };
      setL('lender-market-rate', view.lenderStats.marketRateUsd, '/TH·d');
      setL('lender-lease-net', view.lenderStats.leaseNetUsd, '/d');
      setL('lender-mine-net', view.lenderStats.mineNetUsd, '/d');
      const vs = view.lenderStats.vsMiningUsd;
      const vsEl = document.getElementById('lender-vs-mining');
      if (vsEl) {
        vsEl.textContent = vs != null
          ? `${vs >= 0 ? '+' : '\u2212'}$${Math.abs(vs).toLocaleString(undefined,{maximumFractionDigits:2})}/d`
          : '\u2014';
        vsEl.className = vs == null ? 'badge badge--mute'
          : vs > 0 ? 'badge badge--green' : 'badge badge--red';
      }
      const rec = view.lenderStats.recommendation;
      const recEl = document.getElementById('lender-recommendation');
      if (recEl) {
        const labels = { lease: 'LEASE > MINE', mine: 'MINE > LEASE', equal: 'EQUAL', insufficient: 'NEEDS DATA' };
        recEl.textContent = labels[rec] || 'NEEDS DATA';
        recEl.className = rec === 'lease' ? 'badge badge--green'
          : rec === 'mine' ? 'badge badge--gold'
          : rec === 'equal' ? 'badge badge--mute' : 'badge badge--mute';
      }
    }
  }

  // ── Hashrate Comparison: worker (reported) vs pool-observed (share-derived) ──
  // The panel footnote says "Pool-observed hashrate is estimated from submitted
  // shares" — so `observed` comes from the worker's share_calc_history
  // instantaneous hashrate (mean of the last 8 shares), NOT the pool-wide
  // total (which would always skew deviation to ≈ -100%).
  function renderComparison(snap) {
    const w = snap.worker || {};
    const prox = snap.proximity || {};
    const reported = Number(w.hashrate || 0);
    let observed = 0;
    const ticker = (prox.live_calc && prox.live_calc.ticker) || [];
    const hrs = ticker.map(e => Number(e.instantaneous_hr_hps || 0)).filter(h => h > 0);
    if (hrs.length) observed = hrs.reduce((a, b) => a + b, 0) / hrs.length;
    const dash = '\u2014';
    if (dom.hrReported) dom.hrReported.textContent = reported > 0 ? fmt.hashrate(reported) : dash;
    if (dom.hrObserved) dom.hrObserved.textContent = observed > 0 ? fmt.hashrate(observed) : dash;
    let dev = null;
    if (reported > 0 && observed > 0) dev = ((reported - observed) / observed) * 100;
    if (dom.hrDeviationVal) dom.hrDeviationVal.textContent = dev != null ? (dev >= 0 ? '+' : '') + dev.toFixed(1) + '%' : dash;
    if (dom.hrDeviationBadge) {
      if (dev == null) { dom.hrDeviationBadge.textContent = dash; dom.hrDeviationBadge.className = 'badge badge--mute'; }
      else if (Math.abs(dev) < 10) { dom.hrDeviationBadge.textContent = 'NOMINAL'; dom.hrDeviationBadge.className = 'badge badge--green'; }
      else if (dev > 0) { dom.hrDeviationBadge.textContent = 'REPORTED > OBSERVED'; dom.hrDeviationBadge.className = 'badge badge--gold'; }
      else { dom.hrDeviationBadge.textContent = 'REPORTED < OBSERVED'; dom.hrDeviationBadge.className = 'badge badge--red'; }
    }
  }

  // ── SOLO & STATS — writes proximity payload into solo-* ids ──
  function renderSoloStats(prox) {
    if (!prox) return;
    const dash = '\u2014';
    // #solo-expected-time / #solo-blocks-year appear in TWO panels (profit
    // solo-stats + solo-stats-panel) — write every match.
    const setAll = (id, v) => document.querySelectorAll('#' + id).forEach(el => { el.textContent = v; });
    setAll('solo-net-diff', prox.network_difficulty_str || dash);
    setAll('solo-worker-hr', prox.worker_hashrate_ths ? fmt.hashrate(prox.worker_hashrate_ths * 1e12) : dash);
    setAll('solo-p-block', prox.chance_per_share_label || dash);
    setAll('solo-expected-time', prox.expected_time_human || dash);
    setAll('solo-blocks-year', prox.blocks_per_year != null ? prox.blocks_per_year.toFixed(2) : dash);
    setAll('solo-best-diff', prox.all_time_best_diff_str || dash);
    setAll('solo-status-badge', prox.insufficient_data ? '—' : (prox.best_diff_raw ? 'READY' : '—'));
  }

  function renderMilestones(list) {
    if (!dom.badgesStrip) return;
    if (!list || !list.length) { dom.badgesStrip.innerHTML = '<div class="empty">awaiting data</div>'; return; }
    dom.badgesStrip.innerHTML = list.map(m => `<div class="badge-card"><div class="badge-card__tier">${m.tier}</div><div class="badge-card__label">${escapeHtml(m.label)}</div></div>`).join('');
  }

  // ── Block Hunt render ──
  function renderBlockHunt(snap) {
    const net = snap.network || {};
    const w = snap.worker || {};
    const prox = snap.proximity || {};
    const bh = snap.block_hunt || {};

    const netDiff = net.difficulty || bh.network_difficulty || 0;
    const bestDiff = w.bestDifficulty || bh.best_difficulty || 0;
    const pBlock = bh.p_block_per_share != null ? bh.p_block_per_share : (prox.chance_per_share_pct != null ? prox.chance_per_share_pct : (prox.chance_per_share_raw != null && netDiff > 0 ? prox.chance_per_share_raw / netDiff : 0));
    const expectedTime = bh.expected_time_seconds || prox.expected_time_seconds || prox.expected_time_secs;
    const cumulativeP = bh.cumulative_p_block;

    document.getElementById('bh-network-diff') && (document.getElementById('bh-network-diff').textContent = fmt.diff(netDiff));
    document.getElementById('bh-best-diff') && (document.getElementById('bh-best-diff').textContent = fmt.diff(bestDiff));
    document.getElementById('bh-chance-badge') && (document.getElementById('bh-chance-badge').textContent = pBlock != null ? (Number(pBlock) * 100).toFixed(6) + '% per share' : '—');
    document.getElementById('bh-difficulty-badge') && (document.getElementById('bh-difficulty-badge').textContent = 'diff ' + fmt.diff(netDiff));

    // Distance
    if (bestDiff > 0 && netDiff > 0) {
      const dist = netDiff / bestDiff;
      document.getElementById('bh-distance') && (document.getElementById('bh-distance').textContent = dist.toFixed(1) + '×');
      document.getElementById('bh-distance-sub') && (document.getElementById('bh-distance-sub').textContent = 'your best is ' + (dist > 1 ? 'smaller' : 'larger') + ' than network');
    } else {
      document.getElementById('bh-distance') && (document.getElementById('bh-distance').textContent = '—');
    }

    // P(block) per share
    document.getElementById('bh-p-block') && (document.getElementById('bh-p-block').textContent = pBlock != null ? (Number(pBlock) * 100).toFixed(8) + '%' : '—');

    // Expected time
    document.getElementById('bh-expected-time') && (document.getElementById('bh-expected-time').textContent = expectedTime ? fmt.secsToHuman(expectedTime) : '—');
    if (typeof expectedTime === 'number') {
      const blocksPerYear = expectedTime > 0 ? (365 * 86400) / expectedTime : 0;
      document.getElementById('bh-expected-time-sub') && (document.getElementById('bh-expected-time-sub').textContent = '~' + blocksPerYear.toFixed(4) + ' blocks/yr');
    }

    // Cumulative P(block) — calculate from shares if not provided
    const _calcCumP = () => {
      if (cumulativeP != null) return cumulativeP;
      const shares = prox.live_calc?.session_totals?.shares_so_far || 0;
      const p = Number(pBlock || 0);
      if (shares > 0 && p > 0) return 1 - Math.pow(1 - p, shares);
      return null;
    };
    const finalCumP = _calcCumP();
    document.getElementById('bh-cumulative-p') && (document.getElementById('bh-cumulative-p').textContent = finalCumP != null ? (Number(finalCumP) * 100).toFixed(4) + '%' : '—');
    document.getElementById('bh-cumulative-p-sub') && (document.getElementById('bh-cumulative-p-sub').textContent = 'since session start');

    // Best diff sub
    document.getElementById('bh-best-diff-sub') && (document.getElementById('bh-best-diff-sub').textContent = bh.best_diff_worker ? 'by ' + bh.best_diff_worker : 'highest share found');
  }

  // ── Hashrate Market render ──
  // Backend schema: offers carry `price_per_th_day` (BTC/TH/day, often ~1e-8..1e-10).
  // The old field name `price_btc_per_th_day` never exists in the payload, which
  // made every card render '—'. `is_best` is NOT sent by the backend, so the
  // best offer is derived client-side from the highest metrics.score (ROI),
  // falling back to the lowest valid price_per_th_day.
  let _mktFilter = 'all';
  let _mktOffers = [];
  let _mktBtcUsd = null;  // BTC/USD from snapshot — for the USD/TH/d line on cards
  let _mktTrendLoaded = false;  // lazy: /api/market/trend fetched on first module activation

  function _fmtBtcPerTh(v) {
    const n = Number(v);
    if (!isFinite(n) || n <= 0) return '—';
    if (n >= 0.001) return n.toFixed(6) + ' BTC/TH/d';          // readable BTC scale
    return (n * 1e8).toLocaleString('en-US', { maximumFractionDigits: 2 }) + ' sats/TH/d';  // tiny prices → sats (community convention)
  }

  // USD/TH/d companion line — BTC/TH/day × BTC/USD. Returns null when the
  // price or the BTC price is unavailable so the card simply omits the USD.
  // $1+ → 2 decimals; below $1 → 3 significant figures (no trailing zeros).
  function _mktUsdPerTh(v, btcUsd) {
    const n = Number(v);
    const usd = Number(btcUsd);
    if (!isFinite(n) || n <= 0 || !isFinite(usd) || usd <= 0) return null;
    const x = n * usd;
    if (x >= 1) return '$' + x.toLocaleString('en-US', { maximumFractionDigits: 2 }) + '/TH/d';
    let s = x.toPrecision(3);
    if (s.indexOf('e') !== -1) s = Number(s).toString();
    else s = s.replace(/\.?0+$/, '');
    return '$' + s + '/TH/d';
  }

  // Origin labels: backend `source` field (braiins|mrr|nicehash|kissmyhash|parasite|derived)
  function _mktSourceLabel(src) {
    const map = { braiins: 'BRAIINS', mrr: 'MRR', nicehash: 'NICEHASH', kissmyhash: 'KISSMYHASH', parasite: 'PARASITE', derived: 'DERIVED' };
    return map[src] || (src || 'UNKNOWN').toUpperCase();
  }

  // Best offer: highest metrics.score (backend ROI) wins; only when NO offer
  // carries a finite score do we fall back to the lowest valid price.
  // Two-pass so a low-score offer can never override the score winner via the
  // price fallback (single-pass mixing had that bug).
  // ONLY real marketplace quotes may be crowned "best": estimated offers
  // (parasite pool-fee model, kissmyhash fallback) are NOT rental prices —
  // their score is inflated by the fee-only cost base (measured live: ~1
  // sat/TH/d vs ~10k-50k real market), so they must never win the "best"
  // highlight. They still render as cards (ESTIMATED label) but are skipped
  // here — mirroring the backend best_price fix in app.py.
  function _mktBestIndex(offers) {
    if (!offers || !offers.length) return -1;
    // Build the market-only subset, keeping original indices for mapping back.
    const market = [];
    const marketIdx = [];
    offers.forEach((o, idx) => {
      if (!o.estimated) { market.push(o); marketIdx.push(idx); }
    });
    const pool = market.length ? market : offers;           // all-estimated → fallback to full list
    const poolIdx = market.length ? marketIdx : offers.map((_, i) => i);
    // Pass 1: highest finite metrics.score (first max wins on ties).
    let bestPos = -1;
    let bestScore = -Infinity;
    pool.forEach((o, i) => {
      const sc = Number(o.metrics && o.metrics.score);
      if (isFinite(sc) && sc > bestScore) { bestScore = sc; bestPos = i; }
    });
    if (bestPos >= 0) return poolIdx[bestPos];
    // Pass 2: no scores anywhere → lowest valid price_per_th_day.
    let bestVal = Infinity;
    pool.forEach((o, i) => {
      const p = Number(o.price_per_th_day);
      if (isFinite(p) && p > 0 && p < bestVal) { bestVal = p; bestPos = i; }
    });
    return bestPos >= 0 ? poolIdx[bestPos] : -1;
  }

  function renderMarketGrid() {
    const grid = document.getElementById('mkt-grid');
    if (!grid) return;

    const offers = _mktFilter === 'all'
      ? _mktOffers
      : _mktOffers.filter(o => (o.provider || '').toLowerCase() === _mktFilter);

    if (!offers.length) {
      grid.innerHTML = '<div class="mkt-empty">' + (_mktOffers.length
        ? 'no offers for selected provider — adjust filter'
        : 'no market data available — configure MRR credentials or wait for data to load') + '</div>';
      document.getElementById('mkt-best-price-badge') && (document.getElementById('mkt-best-price-badge').textContent = 'best price —');
      document.getElementById('mkt-count-badge') && (document.getElementById('mkt-count-badge').textContent = _mktOffers.length + ' offers');
      return;
    }

    const bestIdx = _mktBestIndex(offers);
    const bestVal = bestIdx >= 0 ? Number(offers[bestIdx].price_per_th_day) : 0;
    const bestLabel = bestIdx >= 0 ? _fmtBtcPerTh(bestVal) : '—';

    document.getElementById('mkt-best-price-badge') && (document.getElementById('mkt-best-price-badge').textContent = 'best: ' + bestLabel);
    document.getElementById('mkt-count-badge') && (document.getElementById('mkt-count-badge').textContent = offers.length + ' offers');

    grid.innerHTML = offers.map((o, idx) => {
      const src = o.source || o.provider || 'unknown';
      const srcLabel = _mktSourceLabel(src);
      const estTag = o.estimated ? '<span class="mkt-card__est">ESTIMATED</span>' : '';
      const staleCls = (o.meta && o.meta._stale) ? ' mkt-card--stale' : '';
      // Backend hashrate is TH/s — fmt.hashrate expects H/s.
      const hrHps = Number(o.hashrate) > 0 ? Number(o.hashrate) * 1e12 : 0;
      // sats/TH/d (primary) + USD/TH/d (companion, from snapshot BTC price)
      const priceLabel = _fmtBtcPerTh(o.price_per_th_day);
      const usdLabel = _mktUsdPerTh(o.price_per_th_day, _mktBtcUsd);
      return `
      <div class="mkt-card${idx === bestIdx ? ' mkt-card--best' : ''}${staleCls}">
        <div class="mkt-card__head">
          <span class="mkt-card__provider">${escapeHtml(o.provider || 'Unknown')}</span>
          <span class="mkt-card__src mkt-card__src--${escapeHtml(src)}">${srcLabel}</span>
          ${estTag}
        </div>
        <div class="mkt-card__price">${priceLabel}${usdLabel ? ' <span class="mkt-card__usd">≈ ' + usdLabel + '</span>' : ''}</div>
        <div class="mkt-card__detail">
          <span><span class="mkt-card__label">HR:</span>${hrHps > 0 ? fmt.hashrate(hrHps) : '—'}</span>
          <span><span class="mkt-card__label">Fee:</span>${o.fee_pct != null ? o.fee_pct + '%' : '—'}</span>
          <span><span class="mkt-card__label">Duration:</span>${o.duration_days ? o.duration_days + 'd' : '—'}</span>
        </div>
      </div>
    `;
    }).join('');
  }

  function renderMarket(snap) {
    const mkt = snap.market_data || {};
    const grid = document.getElementById('mkt-grid');
    if (!grid) return;
    _mktOffers = mkt.offers || [];
    _mktBtcUsd = Number(snap.btc_price && snap.btc_price.usd) || null;
    renderMarketGrid();
  }

  // Wire the provider filter chips + ⚙ config button + 7d trend chart.
  function initMarketControls() {
    const filtersEl = document.getElementById('mkt-filters');
    if (filtersEl) {
      filtersEl.querySelectorAll('.chip[data-mkt-filter]').forEach(chip => {
        chip.addEventListener('click', () => {
          filtersEl.querySelectorAll('.chip[data-mkt-filter]').forEach(c => c.classList.remove('active'));
          chip.classList.add('active');
          _mktFilter = chip.getAttribute('data-mkt-filter') || 'all';
          renderMarketGrid();
        });
      });
    }
    const cfgBtn = document.getElementById('mkt-config-btn');
    if (cfgBtn) cfgBtn.addEventListener('click', () => { if (typeof openSettingsModal === 'function') openSettingsModal(); });
    // NOTE: loadMarketTrend() is lazy — triggered by activateModule('market').
  }

  async function loadMarketTrend() {
    // Returns true on success, false on failure — the lazy caller (activateModule)
    // resets _mktTrendLoaded on false so a transient failure retries next activation.
    const canvas = document.getElementById('mkt-trend-chart');
    if (!canvas) return false;
    try {
      const r = await fetch('/api/market/trend');
      if (!r.ok) return false;
      const data = await r.json();
      const provs = data.providers || {};
      const countEl = document.getElementById('mkt-trend-count');
      if (countEl) countEl.textContent = Object.keys(provs).length + ' providers';
      const legendEl = document.getElementById('mkt-trend-legend');
      const colors = ['rgb(247,147,26)', 'rgb(6,214,240)', 'rgb(168,85,247)', 'rgb(245,158,11)', 'rgb(16,185,129)'];
      const allTs = new Set();
      Object.values(provs).forEach(pts => (pts || []).forEach(p => { if (p && p.ts) allTs.add(p.ts); }));
      const times = Array.from(allTs).sort((a, b) => a - b);
      const labels = times.map(t => { const d = new Date(t * 1000); return String(d.getHours()).padStart(2, '0') + ':' + String(d.getMinutes()).padStart(2, '0'); });
      const datasets = Object.keys(provs).map((name, i) => {
        const byTs = {};
        (provs[name] || []).forEach(p => { if (p && p.ts != null) byTs[p.ts] = p.price_btc_per_th_day; });
        return {
          label: name,
          data: times.map(t => byTs[t] != null ? Number(byTs[t]) * 1e8 : null),
          borderColor: colors[i % colors.length],
          backgroundColor: colors[i % colors.length].replace(')', ',0.08)').replace('rgb', 'rgba'),
          tension: 0.4, pointRadius: 0, fill: false,
        };
      });
      if (legendEl) {
        legendEl.innerHTML = Object.keys(provs).map((name, i) =>
          `<span class="mkt-trend__legend-item"><span class="mkt-trend__legend-dot" style="background:${colors[i % colors.length]}"></span>${escapeHtml(name)}</span>`
        ).join('');
      }
      if (!datasets.length) return true;  // valid empty state — nothing to plot
      const ctx = canvas.getContext('2d');
      if (window._mktTrendChart) window._mktTrendChart.destroy();
      window._mktTrendChart = new Chart(ctx, {
        type: 'line',
        data: { labels, datasets },
        options: { responsive: true, maintainAspectRatio: false, scales: { x: { ticks: { color: '#5E5952', maxTicksLimit: 8 } }, y: { ticks: { color: '#5E5952' } } }, plugins: { legend: { display: false } } }
      });
      return true;
    } catch (e) { return false; }
  }

  // ── AI Operator render ──
  let _aiInited = false;
  function renderAiOperator(snap) {
    if (!_aiInited) {
      _aiInited = true;
      _initAiChat();
    }

    // Update context sidebar
    const w = snap.worker || {};
    const net = snap.network || {};
    const fleet = snap.axe_fleet || [];
    const prox = snap.proximity || {};

    document.getElementById('ai-ctx-status') && (document.getElementById('ai-ctx-status').textContent = snap.worker ? 'ONLINE' : 'OFFLINE');
    document.getElementById('ai-ctx-hr') && (document.getElementById('ai-ctx-hr').textContent = fmt.hashrate(w.hashrate));
    document.getElementById('ai-ctx-best') && (document.getElementById('ai-ctx-best').textContent = fmt.diff(w.bestDifficulty));
    document.getElementById('ai-ctx-net') && (document.getElementById('ai-ctx-net').textContent = fmt.diff(net.difficulty));
    document.getElementById('ai-ctx-fleet') && (document.getElementById('ai-ctx-fleet').textContent = fleet.length + ' devices');
    document.getElementById('ai-ctx-pblock') && (document.getElementById('ai-ctx-pblock').textContent = prox.chance_per_share_pct ? (Number(prox.chance_per_share_pct) * 100).toFixed(6) + '%' : '—');
  }

  function _initAiChat() {
    const input = document.getElementById('ai-input');
    const send = document.getElementById('ai-send');
    const clear = document.getElementById('ai-clear');
    const messages = document.getElementById('ai-messages');
    if (!input || !send || !messages) return;

    const responses = {
      'hashrate': 'Current hashrate is **{hr}**. This is the speed at which your miners are computing SHA-256 hashes. To improve: add more ASICs, optimize your fleet, or rent hashpower from the market.',
      'temperature': 'Monitoring fleet temperature is critical. Keep ASICs below 75°C for optimal lifespan. Check the Axe Fleet panel for per-device telemetry.',
      'probability': 'Block finding probability depends on your hashrate vs the network difficulty. Currently {pblock}. With solo mining, each share is an independent lottery ticket.',
      'difficulty': 'Network difficulty adjusts every 2016 blocks (~2 weeks). Higher difficulty = more competition. Your best difficulty shows how close you\'ve come to finding a block.',
      'best diff': 'Your best difficulty is the highest share difficulty you\'ve found. The closer to network difficulty, the closer to a block.',
      'market': 'Hashrate market data shows rental prices from various providers. Compare costs and expected value before renting hashpower.',
      'fleet': 'Your fleet dashboard shows {fleet} devices. Each device reports hashrate, temperature, power draw, and shares. Monitor for anomalies.',
      'profitability': 'Profitability depends on hashrate, power cost, and BTC price. Use the Profitability panel to estimate returns across pool, solo, and rental modes.',
      'hello': 'I\'m CYPHER AI, your mining operations intelligence. Ask me about your fleet, probability calculations, market opportunities, or mining metrics.',
    };

    function addMessage(role, content) {
      const div = document.createElement('div');
      div.className = 'ai-msg ai-msg--' + role;
      div.innerHTML = '<div class="ai-msg__header">' + (role === 'user' ? 'You' : '◆ CYPHER AI') + '</div><div class="ai-msg__content">' + content + '</div>';
      messages.appendChild(div);
      messages.scrollTop = messages.scrollHeight;
    }

    function findBestResponse(query) {
      const q = query.toLowerCase();
      const keys = Object.keys(responses);
      let bestKey = 'default';
      let bestScore = 0;
      for (const k of keys) {
        let score = 0;
        const words = k.split(' ');
        for (const w of words) { if (q.includes(w)) score += 10; }
        for (const w of q.split(' ')) { if (k.includes(w) && w.length > 2) score += 5; }
        if (score > bestScore) { bestScore = score; bestKey = k; }
      }
      if (bestScore < 5) return null;
      return bestKey;
    }

    function getResponse(query) {
      const key = findBestResponse(query);
      if (!key) {
        return 'I\'m not sure about that. Try asking about: hashrate, probability, difficulty, market, fleet, profitability, or temperature.';
      }
      let resp = responses[key] || 'Processing your query...';
      // Fill in dynamic context
      const hr = document.getElementById('ai-ctx-hr')?.textContent || '—';
      const pblock = document.getElementById('ai-ctx-pblock')?.textContent || '—';
      const fleetCt = document.getElementById('ai-ctx-fleet')?.textContent || '—';
      resp = resp.replace('{hr}', hr).replace('{pblock}', pblock).replace('{fleet}', fleetCt);
      return resp;
    }

    async function handleSend() {
      try {
        const text = input.value.trim();
        if (!text) return;
        input.value = '';
        send.disabled = true;

        addMessage('user', escapeHtml(text));

        // Show typing indicator
        const typingDiv = document.createElement('div');
        typingDiv.className = 'ai-msg ai-msg--assistant';
        typingDiv.innerHTML = '<div class="ai-msg__header">◆ CYPHER AI</div><div class="ai-typing"><span class="ai-typing__dot"></span><span class="ai-typing__dot"></span><span class="ai-typing__dot"></span></div>';
        messages.appendChild(typingDiv);
        messages.scrollTop = messages.scrollHeight;

        // Brief processing delay
        await new Promise(r => setTimeout(r, 200 + Math.random() * 300));

        typingDiv.remove();

        const response = getResponse(text);
        const formatted = response.replace(/\*\*(.*?)\*\*/g, '<strong style="color:var(--accent-btc)">$1</strong>');
        addMessage('assistant', formatted);
      } finally {
        send.disabled = false;
      }
    }

    send.addEventListener('click', handleSend);
    input.addEventListener('keydown', (e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleSend(); } });
    clear.addEventListener('click', () => {
      messages.innerHTML = '';
      addMessage('assistant', 'Chat cleared. Ask me anything about your mining operation.');
    });
  }

  // ── Main render ──
  let prevSnapshot = null;
  function render(snap) {
    if (!_skeletonsHidden) hideSkeletons();
    // Sync window.BTC_ADDRESS from snapshot so modal and other components stay consistent
    window.BTC_ADDRESS = snap.btc_address || window.BTC_ADDRESS || '';
    renderHUD(snap);
    renderStatusBar(snap);
    if (dom.topbarAddress) dom.topbarAddress.textContent = `${fmt.shortAddr(snap.btc_address || window.BTC_ADDRESS || '')}`;
    if (dom.statusText) dom.statusText.textContent = snap.worker ? 'ONLINE' : 'OFFLINE';
    if (dom.statusPill) dom.statusPill.classList.toggle('is-online', !!snap.worker);
    renderHero(snap);
    renderHostCore(snap);
    renderPool(snap.pool, snap.luck_estimate);
    renderMinersXRay(snap);
    renderNetwork(snap.network);
    renderAccount(snap.account);
    renderBtcPrices(snap.btc_price);
    renderHalving(snap.halving);
    renderMempoolFees(snap.mempool_fees);
    renderProfitability(snap.profitability);
    renderComparison(snap);
    renderSoloStats(snap.proximity);
    renderProximity(snap.proximity);
    renderQuantumLock(snap.proximity);
    renderLiveCalc(snap.proximity);
    renderNetworkGauge(snap);
    renderMilestones(snap.milestones);
    renderAlerts(snap.alerts_recent);
    renderEvents(snap.highest_diffs);
    renderLeaderboard(snap.leaderboard_table_top_30);
    if (typeof updateSidebarStatus === 'function') {
      updateSidebarStatus(!!snap.worker);
    }
    renderTimelineFeed(snap.timeline_recent || snap.timeline_last_n);
    renderTerminalEvents(snap.timeline_last_n || snap.timeline_recent);
    renderBlockHunt(snap);
    renderMarket(snap);
    renderAiOperator(snap);
    renderLiveMining(snap.all_workers, snap.worker);
    renderCharts();
    _updateHashSearchState(snap.worker, snap.network);
    _huntUpdateState(snap.worker, snap.network, parseFloat(snap.proximity?.live_calc?.session_totals?.cum_p_block_pct_str) || 0, parseFloat(snap.proximity?.live_calc?.session_totals?.expected_blocks) || 0, snap.proximity?.live_calc?.ticker || []);
    prevSnapshot = snap;
  }

  // ══════════════════════════════════════════════════════════════════════
  // CHARTS
  // ══════════════════════════════════════════════════════════════════════
  const charts = {};
  // ══════════════════════════════════════════════════════════════════════
  //  FASE 2.1 — PROFESSIONAL CHARTS
  //  moving averages · bar+line overlays · zoom/pan · event annotations
  //  Pure helpers below are mirrored in tests/test_app_js_core.js.
  // ══════════════════════════════════════════════════════════════════════

  // Simple moving average (window in points). Mirrors numpy-rolling mean so
  // the SMA line starts at the first point (partial window at the head).
  function computeSMA(values, windowSize) {
    if (!Array.isArray(values) || !values.length) return [];
    windowSize = Math.max(1, Math.floor(Number(windowSize) || 7));
    const out = [];
    let sum = 0;
    for (let i = 0; i < values.length; i++) {
      sum += Number(values[i]) || 0;
      if (i >= windowSize) sum -= Number(values[i - windowSize]) || 0;
      const n = Math.min(i + 1, windowSize);
      out.push(Number((sum / n).toFixed(2)));
    }
    return out;
  }

  // Map persisted timeline events (ts in seconds) to the nearest label index
  // so the annotation plugin can draw vertical lines at the right x position
  // (category axis — no time adapter needed, stays offline-friendly).
  function buildChartAnnotations(events, labels) {
    if (!Array.isArray(events) || !Array.isArray(labels) || !labels.length) return [];
    const out = [];
    events.forEach(ev => {
      const ts = Number(ev.ts || 0) * 1000;
      if (!ts) return;
      let idx = 0, best = Infinity;
      for (let i = 0; i < labels.length; i++) {
        const d = Math.abs(Number(labels[i]) - ts);
        if (d < best) { best = d; idx = i; }
      }
      out.push({
        index: idx,
        severity: ev.severity || 'INFO',
        message: String(ev.message || ev.event_type || ''),
      });
    });
    return out;
  }

  // ── Zero-dependency annotation plugin (inline, per-chart) ───────────
  // Draws subtle vertical dashed lines at event positions. Bumps/alerts are
  // critical (red), share finds are neutral (amber). Driven by
  // chart._annotations = buildChartAnnotations(...) set on each load.
  const chartEventAnnotationsPlugin = {
    id: 'cypher65EventAnnotations',
    afterDraw(chart) {
      const anns = chart._annotations || [];
      if (!anns.length) return;
      const xScale = chart.scales.x;
      const area = chart.chartArea;
      if (!xScale || !area) return;
      const ctx = chart.ctx;
      ctx.save();
      anns.forEach(a => {
        const x = xScale.getPixelForValue(a.index);
        if (x < area.left || x > area.right) return;
        const critical = a.severity === 'CRIT' || a.severity === 'GOLD';
        ctx.strokeStyle = critical ? 'rgba(255,94,94,0.55)' : 'rgba(255,196,0,0.30)';
        ctx.lineWidth = 1;
        ctx.setLineDash([4, 3]);
        ctx.beginPath(); ctx.moveTo(x, area.top); ctx.lineTo(x, area.bottom); ctx.stroke();
        ctx.setLineDash([]);
      });
      ctx.restore();
    },
  };

  // Pure zoom-range clamp for the category axis (x min/max are POINT INDICES,
  // not timestamps). Expressed in point counts so it works on any dataset size.
  // Mirrored in tests/test_app_js_core.js.
  function clampZoomRange(currentRange, factor, minPoints, maxPoints) {
    const next = currentRange * factor;
    const upper = Math.max(minPoints, maxPoints);
    return Math.max(minPoints, Math.min(next, upper));
  }

  // ── Lightweight zoom/pan (wheel zoom + drag pan + dblclick reset) ───
  // Implemented against Chart.js scale min/max directly — no CDN plugin, so
  // the self-hosted dashboard keeps working fully offline.
  // IMPORTANT: the x scale is CATEGORY (labels are HH:mm strings), so min/max
  // are point indices — zoom bounds are clamped in POINT COUNTS (min 5 points,
  // max = full label count), never wall-clock ms.
  // Drag uses Pointer Capture bound to the canvas only — no window listeners,
  // so re-initializing charts can never leak handlers.
  function _attachChartZoom(chart) {
    const canvas = chart.canvas;
    if (!canvas) return;
    const MIN_POINTS = 5;
    const maxPoints = () => Math.max(MIN_POINTS, (chart.data.labels || []).length);
    const resetZoom = () => {
      delete chart.options.scales.x.min;
      delete chart.options.scales.x.max;
      chart.update('none');
    };
    canvas.addEventListener('wheel', e => {
      e.preventDefault();
      const xs = chart.scales.x;
      if (!xs) return;
      const range = xs.max - xs.min;
      if (!range) return;
      const cursor = (e.offsetX / canvas.clientWidth);
      const anchor = xs.min + range * cursor;
      const factor = e.deltaY > 0 ? 1.2 : 0.8333;
      const newRange = clampZoomRange(range, factor, MIN_POINTS, maxPoints());
      const newMin = anchor - newRange * cursor;
      chart.options.scales.x.min = newMin;
      chart.options.scales.x.max = newMin + newRange;
      chart.update('none');
    }, { passive: false });
    let drag = null;
    canvas.addEventListener('pointerdown', e => {
      if (e.button !== 0) return;
      const xs = chart.scales.x;
      if (!xs) return;
      drag = { startX: e.clientX, startMin: xs.min };
      try { canvas.setPointerCapture(e.pointerId); } catch (err) { /* ignore */ }
      canvas.style.cursor = 'grabbing';
    });
    canvas.addEventListener('pointermove', e => {
      if (!drag) return;
      const xs = chart.scales.x;
      if (!xs || !(xs.max - xs.min)) return;
      const dx = (e.clientX - drag.startX) / canvas.clientWidth * (xs.max - xs.min);
      const newMin = drag.startMin - dx;
      chart.options.scales.x.min = newMin;
      chart.options.scales.x.max = newMin + (xs.max - xs.min);
      chart.update('none');
    });
    canvas.addEventListener('pointerup', () => {
      drag = null;
      canvas.style.cursor = '';
    });
    canvas.addEventListener('pointercancel', () => {
      drag = null;
      canvas.style.cursor = '';
    });
    canvas.addEventListener('dblclick', resetZoom);
    canvas.title = 'scroll to zoom · drag to pan · double-click to reset';
  }

  function makeChart(id, label, color) {
    const canvas = document.getElementById(id);
    if (!canvas) return null;
    const ctx = canvas.getContext('2d');
    const cfg = CHART_METRICS[id];
    const isHistogram = cfg && cfg.chart === 'share_dist';
    const datasets = [
      { label, data: [], borderColor: color, backgroundColor: color.replace(')', ',0.1)').replace('rgb','rgba'), fill: true, tension: 0.4, pointRadius: 0 },
    ];
    // Fase 2.1: moving-average overlay (dashed, no fill) on time series
    if (!isHistogram) {
      datasets.push({ label: label + ' · SMA', data: [], borderColor: 'rgba(234,234,235,0.55)', backgroundColor: 'transparent', borderDash: [5, 3], fill: false, tension: 0.4, pointRadius: 0, borderWidth: 1.5 });
    }
    // Fase 2.1: share-volume bar overlay (2nd y-axis, right) on hashrate
    if (cfg && cfg.chart === 'hashrate') {
      datasets.push({ type: 'bar', label: 'Shares/min', data: [], yAxisID: 'y1', backgroundColor: 'rgba(6,214,240,0.14)', borderColor: 'rgba(6,214,240,0.35)', borderWidth: 1, order: 3 });
    }
    const chart = new Chart(ctx, {
      type: 'line',
      data: { labels: [], datasets },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: 'index', intersect: false },
        scales: {
          x: { ticks: { color: '#5E5952', maxTicksLimit: 8, font: { family: 'JetBrains Mono, monospace', size: 10 } }, grid: { color: 'rgba(94,89,82,0.14)' } },
          y: { ticks: { color: '#5E5952', font: { family: 'JetBrains Mono, monospace', size: 10 } }, grid: { color: 'rgba(94,89,82,0.14)' } },
          y1: { position: 'right', display: false, grid: { drawOnChartArea: false }, ticks: { color: '#06d6f0', font: { family: 'JetBrains Mono, monospace', size: 10 } } },
        },
        plugins: {
          legend: { display: false },
          tooltip: {
            backgroundColor: 'rgba(17,18,20,0.94)',
            borderColor: 'rgba(255,255,255,0.08)',
            borderWidth: 1,
            titleColor: '#EAEAEB',
            bodyColor: '#C9C5BC',
            padding: 10,
            boxPadding: 4,
            usePointStyle: true,
            font: { family: 'JetBrains Mono, monospace', size: 11 },
          },
        },
      },
      plugins: [chartEventAnnotationsPlugin],
    });
    if (!isHistogram) _attachChartZoom(chart);
    return chart;
  }

  async function loadChart(id, metric, range) {
    try {
      const r = await fetch(`/api/chart-data?chart=${metric}&range=${range}`);
      if (!r.ok) return;
      const data = await r.json();
      const chart = charts[id];
      if (!chart) return;
      const cfg = CHART_METRICS[id] || {};
      const rawLabels = (data.labels || []);
      const values = (data.datasets?.[0]?.data || data.datasets?.[0]?.values || []);
      chart.data.labels = rawLabels.map(t => {
        if (cfg.chart === 'share_dist') return String(t); // histogram bucket labels
        const d = new Date(t); return d.getHours()+':'+String(d.getMinutes()).padStart(2,'0');
      });
      chart.data.datasets[0].data = values;
      // Fase 2.1: SMA overlay + shares bar + event annotations
      if (chart.data.datasets[1] && cfg.chart !== 'share_dist') {
        chart.data.datasets[1].data = computeSMA(values, Math.max(3, Math.round(values.length / 10)));
      }
      if (chart.data.datasets[2] && Array.isArray(data.shares)) {
        chart.data.datasets[2].data = data.shares;
        chart.options.scales.y1.display = data.shares.some(s => s > 0);
      }
      chart._annotations = buildChartAnnotations(data.events || [], rawLabels);
      chart.update('none');
    } catch (e) { /* chart load silently */ }
  }

  function initCharts() {
    charts['chart-hashrate'] = makeChart('chart-hashrate', 'Hashrate', 'rgb(247,147,26)');
    charts['chart-pool'] = makeChart('chart-pool', 'Pool HR', 'rgb(6,214,240)');
    charts['chart-bestdiff'] = makeChart('chart-bestdiff', 'Best Diff', 'rgb(16,185,129)');
    charts['chart-net'] = makeChart('chart-net', 'Net Diff', 'rgb(139,92,246)');
    charts['chart-cumulative-p'] = makeChart('chart-cumulative-p', 'Cum P(Block)', 'rgb(139,92,246)');
    charts['chart-share-dist'] = makeChart('chart-share-dist', 'Share Dist', 'rgb(16,185,129)');
  }

  // Fase 2.1: clear any manual zoom/pan state so the chart renders the full
  // window again (used when switching ranges or pressing the ⟲ button).
  // Only re-renders when zoom state actually existed (cheap no-op otherwise).
  function _resetChartZoom(chart) {
    if (!chart || !chart.options || !chart.options.scales || !chart.options.scales.x) return;
    const hadZoom = chart.options.scales.x.min !== undefined || chart.options.scales.x.max !== undefined;
    delete chart.options.scales.x.min;
    delete chart.options.scales.x.max;
    if (hadZoom) chart.update('none');
  }

  function bindChartRanges() {
    document.querySelectorAll('.chart-range').forEach(row => {
      const target = row.dataset.target;
      // Only real range chips carry data-range; the ⟲ reset button (data-zoom-reset)
      // is bound separately below so it is never treated as a range.
      row.querySelectorAll('button[data-range]').forEach(btn => {
        btn.addEventListener('click', () => {
          row.querySelectorAll('button[data-range]').forEach(b => b.classList.remove('active'));
          btn.classList.add('active');
          const metricMap = { 'chart-hashrate': 'worker_hashrate', 'chart-pool': 'pool_hashrate', 'chart-bestdiff': 'worker_best_diff', 'chart-net': 'network_difficulty' };
          // Switching ranges resets any manual zoom/pan from the old window.
          _resetChartZoom(charts[target]);
          loadChart(target, metricMap[target] || target.replace('chart-',''), btn.dataset.range);
        });
      });
    });
    // Fase 2.1: explicit ⟲ reset-zoom buttons in each chart toolbar.
    document.querySelectorAll('[data-zoom-reset]').forEach(btn => {
      btn.addEventListener('click', () => {
        _resetChartZoom(charts[btn.dataset.zoomReset]);
      });
    });
  }

  // ── Matrix Rain ──
  function initMatrix() {
    const c = document.getElementById('matrix-canvas'); if (!c) return;
    const ctx = c.getContext('2d'); let w, h, cols, drops;
    const chars = '01アイウエオカキクケコサシスセソタチツテトABCDEF123456789#$%&*+<=>?';
    function resize() { w = c.width = window.innerWidth; h = c.height = window.innerHeight; cols = Math.floor(w / 14); drops = Array(cols).fill(0).map(() => Math.random() * h / 14); }
    resize(); window.addEventListener('resize', resize);
    function step() {
      if (document.hidden) { requestAnimationFrame(step); return; }
      ctx.fillStyle = 'rgba(4, 6, 10, 0.07)'; ctx.fillRect(0, 0, w, h);
      ctx.font = '13px JetBrains Mono';
      for (let i = 0; i < cols; i++) {
        const x = i * 14, y = drops[i] * 14;
        const ch = chars[Math.floor(Math.random() * chars.length)];
        ctx.fillStyle = Math.random() > 0.985 ? '#a855f7' : Math.random() > 0.95 ? '#00ff9f' : '#06d6f0';
        ctx.fillText(ch, x, y);
        if (y > h && Math.random() > 0.975) drops[i] = 0;
        drops[i] += 0.95;
      }
      requestAnimationFrame(step);
    }
    step();
  }

  // ── Settings ──
  const SETTINGS_CACHE = { data: null };
  const SETTINGS_SELECTS = { cost_mode: ['none','rental','power'], active_currency: ['USD','BRL','EUR','GBP'], webhook_min_severity: ['INFO','WARN','CRIT','GOLD','SUCCESS'] };
  const SETTINGS_CHECKBOX = { show_test_alerts: true };
  // Didactic hints shown under each settings field so users configure the
  // cost model correctly (Fase: LEASE mode — rental_usd_per_th_day is the
  // rate the LENDER charges, i.e. revenue, not a plain "cost").
  const SETTINGS_HINTS = {
    cost_mode: 'none = no cost · rental = pay per TH/s rented · power = rig kWh cost',
    rental_usd_per_th_day: '📤 LEASE: o que VOCÊ cobra ao alugar seu hashrate (receita) · 📦 RENTAL: o que você paga para alugar hashrate. Usado no modo LEASE do Profitability.',
    power_watts: 'Consumo do rig (W) — usado para o custo de energia no modo POWER e no LEASE.',
    power_kwh_usd: 'Tarifa de eletricidade ($/kWh) — usada junto com power_watts no modo POWER e no LEASE.',
    pool_fee_pct: 'Taxa da pool (%) aplicada à receita de mineração.',
    active_currency: 'Moeda exibida nos valores fiat (USD|BRL|EUR|GBP).',
  };
  function renderSettingsForm() {
    const box = dom.settingsBody;
    if (!box) return;
    const settings = SETTINGS_CACHE.data;
    if (!settings || !Object.keys(settings).length) {
      box.innerHTML = '<div class="mkt-empty" style="padding:16px;text-align:center">settings unavailable</div>';
      return;
    }
    const order = ['cost_mode','rental_usd_per_th_day','power_watts','power_kwh_usd','btc_block_reward','btc_avg_tx_fee','pool_fee_pct','orphan_rate_pct','active_currency','active_fiat','stale_share_minutes','hashrate_drop_pct','webhook_url','webhook_min_severity','show_test_alerts','mrr_api_key','mrr_api_secret'];
    const keys = Object.keys(settings).sort((a,b) => {
      const ia = order.indexOf(a), ib = order.indexOf(b);
      return (ia<0?99:ia) - (ib<0?99:ib);
    });
    let html = '<div style="display:flex;flex-direction:column;gap:8px;padding:4px 0">';
    keys.forEach(k => {
      const s = settings[k] || {};
      const val = (s.value !== undefined && s.value !== null && s.value !== '') ? s.value : s.default;
    const label = escapeHtml(s.label || k);
    const hint = SETTINGS_HINTS[k] ? `<small style="color:#8b93a7;font-size:10px;line-height:1.3">${escapeHtml(SETTINGS_HINTS[k])}</small>` : '';
    if (SETTINGS_SELECTS[k]) {
      const opts = SETTINGS_SELECTS[k].map(o => `<option value="${o}" ${String(val)===o?'selected':''}>${o}</option>`).join('');
      html += `<label style="display:flex;flex-direction:column;gap:2px;font-size:11px"><span>${label}</span><select name="${k}" class="field__input">${opts}</select>${hint}</label>`;
    } else if (SETTINGS_CHECKBOX[k]) {
      html += `<label style="display:flex;gap:6px;font-size:11px;align-items:center"><input type="checkbox" name="${k}" ${String(val)==='1'?'checked':''}> ${label}${hint}</label>`;
    } else {
      html += `<label style="display:flex;flex-direction:column;gap:2px;font-size:11px"><span>${label}</span><input type="text" name="${k}" value="${escapeHtml(String(val ?? ''))}" class="field__input">${hint}</label>`;
    }
    });
    html += '</div>';
    box.innerHTML = html;
  }
  async function loadSettings() {
    try { const r = await fetch('/api/settings'); SETTINGS_CACHE.data = (await r.json()).settings.reduce((acc, s) => { acc[s.key] = s; return acc; }, {}); renderSettingsForm(); } catch (e) {}
  }
  function openSettingsModal() {
    dom.settingsModal?.classList.add('modal--open');
    if (dom.settingsBody && !dom.settingsBody.innerHTML.trim()) renderSettingsForm();
  }
  function closeSettingsModal() { dom.settingsModal?.classList.remove('modal--open'); }
  dom.settingsModal?.addEventListener('click', (e) => { if (e.target.matches('[data-close]')) closeSettingsModal(); });
  dom.openSettings?.addEventListener('click', openSettingsModal);

  // ── LN Payment ──
  var _lnPaying = false;

  // Populate LN address from support config on open
  function _populateLNAddress() {
    var el = document.getElementById('support-ln-address');
    if (!el || el.textContent !== '—') return;
    fetch('/api/support-config').then(function(r) { return r.json(); }).then(function(cfg) {
      var ln = cfg.methods && cfg.methods.find(function(m) { return m.id === 'lightning'; });
      if (ln && ln.address) el.textContent = ln.address;
    }).catch(function() { /* support config not available */ });
  }

  // ── Render donation methods into the compact bar + full modal grid ──
  // Fixes the orphaned containers (#support-bar-methods / #support-modal-grid)
  // which had CSS + a copy handler but were never populated by JS. The copy
  // button reads the previous sibling's data-copy attribute (see FASE 3).
  function renderSupportMethods() {
    fetch('/api/support-config').then(function(r) { return r.json(); }).then(function(cfg) {
      var methods = (cfg && cfg.methods) || [];
      var manifesto = cfg && cfg.manifesto ? cfg.manifesto : '';

      // Manifesto (authored, cypherpunk) into the dedicated modal block.
      // Injected BEFORE the methods guard so it renders even if the config
      // ever ships with an empty methods list.
      var maniEl = document.getElementById('support-modal-manifesto');
      if (maniEl && manifesto) {
        maniEl.innerHTML = manifesto.split('\n').map(function(line) {
          if (!line.trim()) return '<br>';
          return line.replace(/^— (.*)$/, '<span class="support-modal__sign">— $1</span>');
        }).join(' ');
      }

      if (!methods.length) return;

      // Compact chips for the fixed footer bar
      var bar = document.getElementById('support-bar-methods');
      if (bar) {
        bar.innerHTML = methods.map(function(m) {
          return '<span class="support-method" title="' + escapeHtml(m.label) + '">' +
            '<span class="support-method-tag" style="color:' + (m.color || '#00ff41') + '">' + (m.icon || '₿') + ' ' + escapeHtml(m.label) + '</span>' +
            '<span class="support-method-addr" data-copy="' + escapeHtml(m.address) + '">' + escapeHtml(m.address) + '</span>' +
            '<button class="support-method-copy" data-copy-btn aria-label="Copy ' + escapeHtml(m.label) + ' address">⧉</button>' +
            '</span>';
        }).join('');
      }

      // Full cards for the modal grid
      var grid = document.getElementById('support-modal-grid');
      if (grid) {
        grid.innerHTML = methods.map(function(m) {
          return '<div class="support-modal__card">' +
            '<div class="support-modal__card-icon" style="color:' + (m.color || '#00ff41') + '">' + (m.icon || '₿') + '</div>' +
            '<div class="support-modal__card-label">' + escapeHtml(m.label) + '</div>' +
            (m.note ? '<div class="support-modal__card-note">' + escapeHtml(m.note) + '</div>' : '') +
            '<div class="support-modal__card-addr" data-copy="' + escapeHtml(m.address) + '">' + escapeHtml(m.address) + '</div>' +
            '<button class="support-modal__card-copy" data-copy-btn>⧉ copy</button>' +
            '</div>';
        }).join('');
      }

      // LN recipient row — same config object, no second fetch needed
      var lnEl = document.getElementById('support-ln-address');
      var ln = methods.find(function(m) { return m.id === 'lightning'; });
      if (lnEl && ln && ln.address && lnEl.textContent === '—') {
        lnEl.textContent = ln.address;
      }
    }).catch(function() { /* support config not available */ });
  }

  // ── Recent Donations list (Support modal) ──
  // Fed by GET /api/donations. Shows total + recent confirmed donations so
  // the operator can answer "como saber quem doou".
  function loadDonations() {
    fetch('/api/donations').then(function(r) { return r.json(); }).then(function(d) {
      var box = document.getElementById('support-modal-donations');
      if (!box) return;
      var stats = document.getElementById('donations-stats');
      var list = document.getElementById('donations-list');
      if (!stats || !list) return;
      var don = d.donations || [];
      if (!don.length) {
        box.style.display = 'none';
        return;
      }
      box.style.display = '';
      var total = d.total || 0;
      var totalSat = d.total_sat || 0;
      stats.textContent = total + ' doação' + (total === 1 ? '' : 'ões') + ' · ' + (totalSat >= 1e8 ? (totalSat / 1e8).toFixed(8).replace(/\.?0+$/, '') + ' BTC' : totalSat.toLocaleString('en-US') + ' sats') + ' recebidos';
      list.innerHTML = don.slice(0, 6).map(function(row) {
        var methodIcon = { lightning: '⚡', btc: '₿', hashpower: '⛏' }[row.method] || '♥';
        var amt = row.amount_sat != null ? (row.amount_sat >= 1e8 ? (row.amount_sat / 1e8).toFixed(8).replace(/\.?0+$/, '') + ' BTC' : row.amount_sat.toLocaleString('en-US') + ' sats') : '—';
        var t = new Date((row.ts || 0) * 1000);
        var ts = t.toLocaleString('pt-BR', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' });
        var proof = row.txid ? row.txid.slice(0, 10) + '…' : (row.preimage ? 'preimage ' + row.preimage.slice(0, 10) + '…' : '');
        // verified = onchain (mempool watcher) or manual (operator-confirmed);
        // webln = client-reported, not verified on-chain
        var badge = row.source !== 'webln'
          ? '<span class="donation-row__badge is-verified" title="Confirmado on-chain (mempool)">✓</span>'
          : '<span class="donation-row__badge" title="Relatado pelo doador via WebLN — não verificado on-chain">~</span>';
        return '<div class="donation-row">' +
          '<span class="donation-row__icon">' + methodIcon + '</span>' +
          '<span class="donation-row__amt">' + amt + '</span>' +
          '<span class="donation-row__proof mono">' + (proof ? proof : (row.note || '')) + '</span>' +
          badge +
          '<span class="donation-row__ts">' + ts + '</span>' +
          '</div>';
      }).join('');
    }).catch(function() { /* donations not available */ });
  }

  // Render once on boot so the footer bar has the chips immediately
  renderSupportMethods();
  loadDonations();
  // Listen for support panel opening — only the ◈ Details button opens the
  // modal (clicks on the compact bar's copy chips must NOT open the full
  // panel); both entry points still populate the LN address.
  document.addEventListener('click', function _onSupportOpen(e) {
    var onExpand = e.target.closest('#support-expand-btn');
    if (onExpand || e.target.closest('#support-bar-methods')) {
      if (onExpand) {
        var panel = document.getElementById('support-panel');
        if (panel) panel.classList.add('modal--open');
      }
      setTimeout(_populateLNAddress, 200);
      // Re-render on open so a failed boot fetch self-heals when the panel
      // is actually opened (same retry semantics as _populateLNAddress).
      setTimeout(renderSupportMethods, 250);
      setTimeout(loadDonations, 300);
    }
  });

  async function sendLNPayment() {
    if (_lnPaying) return;
    _lnPaying = true;
    var invoiceInput = document.getElementById('ln-invoice-input');
    var statusEl = document.getElementById('ln-payment-status');
    if (!invoiceInput || !statusEl) { _lnPaying = false; return; }

    try {
      var invoice = invoiceInput.value.trim();
      if (!invoice) {
        statusEl.textContent = '\u26A0 Please paste a BOLT11 invoice';
        statusEl.className = 'support-modal__ln-status support-modal__ln-status--error';
        return;
      }
      // Smart validation: help the donor paste the RIGHT thing. The spark
      // address / lightning addresses / on-chain addrs are NOT BOLT11 —
      // give a specific hint instead of a generic rejection. Flat chain:
      // spark1 → lnurl → lightning-address → on-chain → BOLT12 → BOLT11 ok.
      var lower = invoice.toLowerCase();
      if (lower.indexOf('spark1') === 0) {
        statusEl.textContent = '\u26A0 Essa é a spark address (destino), não um invoice. Gere um invoice BOLT11 (lnbc1...) na sua wallet para pagar aqui.';
        statusEl.className = 'support-modal__ln-status support-modal__ln-status--error';
        return;
      }
      if (lower.indexOf('lnurl') === 0) {
        statusEl.textContent = '\u26A0 Isso é um lnurl, não um invoice BOLT11. Cole o invoice (lnbc1...) que sua wallet gerou para pagar.';
        statusEl.className = 'support-modal__ln-status support-modal__ln-status--error';
        return;
      }
      if (lower.indexOf('@') > 0) {
        statusEl.textContent = '\u26A0 Isso é um lightning address (user@domínio). Cole o invoice BOLT11 (lnbc1...) gerado na sua wallet.';
        statusEl.className = 'support-modal__ln-status support-modal__ln-status--error';
        return;
      }
      if (lower.indexOf('bc1') === 0 || lower.indexOf('1') === 0 || lower.indexOf('3') === 0) {
        statusEl.textContent = '\u26A0 Isso é um endereço on-chain (BTC). Para Lightning, cole um invoice BOLT11 (lnbc1...).';
        statusEl.className = 'support-modal__ln-status support-modal__ln-status--error';
        return;
      }
      if (lower.indexOf('lno1') === 0) {
        statusEl.textContent = '\u26A0 Isso é um offer BOLT12 (lno1...), ainda não suportado. Cole um invoice BOLT11 (lnbc1...).';
        statusEl.className = 'support-modal__ln-status support-modal__ln-status--error';
        return;
      }
      if (lower.indexOf('lnbc') !== 0 && lower.indexOf('lntb') !== 0) {
        statusEl.textContent = '\u26A0 Invoice inválido — um invoice BOLT11 começa com lnbc1 (mainnet) ou lntb1 (testnet).';
        statusEl.className = 'support-modal__ln-status support-modal__ln-status--error';
        return;
      }
      // Extract the invoice amount (msat → sat) for the donation record.
      // BOLT11 encodes amount as lnbc<number><multiplier>1... where the
      // multiplier (m/u/n/p) scales the BTC figure to millisatoshis.
      var invAmtSat = null;
      // BOLT11 amount = digits + optional multiplier (m/u/n/p) followed by
      // the mandatory '1' HRP separator. Requiring the separator avoids
      // misreading amountless invoices (lnbc1... — the '1' is the separator,
      // and the wallet decides the value) as '1 BTC'.
      var m = invoice.match(/^(?:lnbc|lntb)(?:(\d+)([munp]?))?1/i);
      if (m && m[1] !== undefined) {
        // Multipliers per BOLT11: bare = BTC (1e11 msat), m/u/n/p scale down.
        var mult = { '': 1e11, m: 1e8, u: 1e5, n: 1e2, p: 1e-1 }[m[2] || ''];
        if (mult !== undefined) {
          var msat = parseInt(m[1], 10) * mult;
          invAmtSat = Math.round(msat / 1000);
        }
      }

      statusEl.textContent = '\uD83D\uDD0D Connecting Lightning wallet...';
      statusEl.className = 'support-modal__ln-status support-modal__ln-status--pending';

      var provider = await detectWebLN(5000);
      if (!provider) {
        statusEl.textContent = '\u26A0 No WebLN wallet detected. Install Alby or Joule browser extension.';
        statusEl.className = 'support-modal__ln-status support-modal__ln-status--error';
        return;
      }

      statusEl.textContent = '\uD83D\uDD11 Requesting permission to pay...';
      await provider.enable();

      statusEl.textContent = '\uD83D\uDCB8 Sending payment...';
      var result = await provider.sendPayment(invoice);
      var preimage = result && result.preimage ? result.preimage : '';
      var shortPreimage = preimage ? preimage.slice(0, 16) + '...' : '';
      statusEl.innerHTML = '\u2713 Payment sent! ' + (shortPreimage ? 'Preimage: <code class="mono">' + shortPreimage + '</code>' : '') + '<br><span class="support-modal__ln-footnote">Check your wallet for confirmation.</span>';
      statusEl.className = 'support-modal__ln-status support-modal__ln-status--success';
      invoiceInput.value = '';
      _weblnProvider = provider;
      // Record the donation server-side (dedup by preimage) so the operator
      // can see it in the Recent Donations list + Alerts panel. Sends the
      // invoice amount (parsed above) so the list shows sats, not '—'.
      if (preimage) {
        try {
          fetch('/api/donations', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ method: 'lightning', preimage: preimage, amount_sat: invAmtSat, source: 'webln' })
          }).then(function() { loadDonations(); }).catch(function() {});
        } catch (e) { /* non-fatal */ }
      }
    } catch (e) {
      statusEl.textContent = '\u2717 Payment ' + (e.message && e.message.indexOf('denied') !== -1 ? 'denied' : 'failed') + ': ' + (e.message || 'unknown error');
      statusEl.className = 'support-modal__ln-status support-modal__ln-status--error';
    } finally {
      _lnPaying = false;
    }
  }

  // Wire up LN Pay button
  document.addEventListener('click', function(e) {
    if (e.target.closest('#ln-pay-btn')) sendLNPayment();
  });

  // ── Wallet modal ──
  function openWalletModal() {
    dom.walletModal?.classList.add('modal--open');
    // Fill current address info
    if (dom.walletCurrentAddr) dom.walletCurrentAddr.textContent = window.BTC_ADDRESS ? fmt.chunkAddr(window.BTC_ADDRESS) : '—';
    if (dom.walletCurrentWorker) dom.walletCurrentWorker.textContent = window.WORKER_NAME || '—';
    if (dom.walletAddressInput) dom.walletAddressInput.value = '';
    if (dom.walletWorkerInput) dom.walletWorkerInput.value = '';
    if (dom.walletStatus) dom.walletStatus.textContent = '';
    // Focus the address input
    setTimeout(() => dom.walletAddressInput?.focus(), 100);
    // ── Hitórico de wallets ──
    fetchWalletHistory();
  }
  function closeWalletModal() {
    dom.walletModal?.classList.remove('modal--open');
    if (dom.walletStatus) dom.walletStatus.textContent = '';
  }
  dom.walletModal?.addEventListener('click', (e) => { if (e.target.matches('[data-close]')) closeWalletModal(); });
  dom.openWallet?.addEventListener('click', openWalletModal);
  document.getElementById('webln-connect-btn')?.addEventListener('click', connectWebLN);

  // Save wallet
  
  // ── FASE 2: Fetch wallet history ──
  async function fetchWalletHistory() {
    try {
      var resp = await fetch('/api/wallet/history');
      var data = await resp.json();
      if (data.success && data.history) {
        var list = document.getElementById('wallet-history-list');
        if (list) {
          list.innerHTML = '';
          data.history.forEach(function(entry) {
            var li = document.createElement('button');
            li.className = 'wallet-history__item';
            li.innerHTML = '<span class="mono">' + entry.address.slice(0, 10) + '...</span> <span class="mute">' + (entry.worker || '') + '</span>';
            li.onclick = function() {
              var input = document.getElementById('wallet-address-input');
              if (input) input.value = entry.address;
              var wInput = document.getElementById('wallet-worker-input');
              if (wInput && entry.worker) wInput.value = entry.worker;
            };
            list.appendChild(li);
          });
        }
      }
    } catch(e) {
      console.warn('[wallet history]', e);
    }
  }  // ── Personalized wallet greetings (by address) ───────────────────
  // Wallets in this map are community / early-supporters: they receive a
  // personalized welcome AND hold FULL & FREE access to the tool (policy:
  // every greeted wallet is entitled).
  const WALLET_GREETINGS = {
    'bc1qftl45m5jq7hjd0n62yuxesmss478xl2wvfkeed': '👋 Bem vindo barone (barone club)',
    'bc1qffk82prrxn84e8y9l0z5yflsqclhyc9ptphgmf': '👋 Bem vindo filipe silva — comunidade bitminer33',
    'bc1q029y2atdtvth4puv2mm5w49m32n278jtz2sxqn': '👋 Bem vindo DIGO GARABELI — acesso FULL & FREE',
    'dhr7a2ihqou5w5r5cpvsuvcnw4jg32qlwx': '👋 Bem vindo DIGO GARABELI — acesso FULL & FREE',
    '1473pql42jvtwxaaxcvsocrf6ytb8teted': '👋 Bem vindo DIGO GARABELI — acesso FULL & FREE',
  };

  function walletGreeting(address) {
    if (!address) return null;
    return WALLET_GREETINGS[String(address).toLowerCase()] || null;
  }

  // Policy: every wallet with a personalized greeting holds FULL & FREE
  // access to the tool. Kept as an explicit helper so the connect flow
  // (and any future gated feature) treats greeted wallets as entitled.
  function walletHasFullAccess(address) {
    return walletGreeting(address) !== null;
  }

dom.walletSave?.addEventListener('click', async () => {
    const status = dom.walletStatus;
    if (!status) return;
    const address = dom.walletAddressInput?.value?.trim() || '';
    if (!address) {
      status.textContent = '⚠ paste a BTC address first';
      status.style.color = 'var(--accent-red)';
      return;
    }
    status.textContent = '⏳ connecting...';
    status.style.color = 'var(--text-tertiary)';
    try {
      const resp = await fetch('/api/set-address', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ address }),
      });
      const data = await resp.json();
      if (!resp.ok) {
        status.textContent = '⚠ ' + (data.error || 'request failed');
        status.style.color = 'var(--accent-red)';
        return;
      }
      status.textContent = '✅ connected — updating...';
      status.style.color = 'var(--accent-green)';
      // Update globals
      window.BTC_ADDRESS = data.address;
      localStorage.setItem('_wallet_connected', 'true');
      showToast('success', 'Wallet connectada: ' + data.address.slice(0, 10) + '...');
      // Personalized welcome for known community wallets
      const greeting = walletGreeting(data.address);
      if (greeting) showToast('success', greeting);
      // Greeted wallets hold FULL & FREE access — surface it so the
      // entitlement is visible, not silent.
      if (walletHasFullAccess(data.address)) {
        showToast('success', '⚡ Acesso FULL & FREE confirmado');
      }
      // HOTFIX: Trigger immediate data fetch after wallet connect
      // This forces an immediate poll instead of waiting ~15s
      window.dispatchEvent(new CustomEvent('wallet-changed', { detail: { address: data.address } }));
      // Update topbar — show just the address
      if (dom.topbarAddress) {
        dom.topbarAddress.textContent = fmt.shortAddr(data.address);
      }
      // Update live mining summary wallet display
      if (dom.lmSummaryWallet) {
        dom.lmSummaryWallet.textContent = fmt.shortAddr(data.address);
      }
      // Close modal after delay
      setTimeout(() => {
        closeWalletModal();
        // Trigger immediate re-fetch so new worker data shows up
        fetchSnapshot();
      }, 1200);
    } catch (e) {
      status.textContent = '⚠ network error: ' + e.message;
      status.style.color = 'var(--accent-red)';
    }
  });
  document.getElementById('settings-save')?.addEventListener('click', async () => {
    const form = document.getElementById('settings-body');
    if (!form) return;
    const data = {};
    form.querySelectorAll('input, select, textarea').forEach(el => {
      if (el.name) data[el.name] = el.type === 'checkbox' ? (el.checked ? '1' : '0') : el.value;
    });
    try {
      const r = await fetch('/api/settings', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data)
      });
      const result = await r.json();
      const status = document.getElementById('settings-status');
      // Backend POST /api/settings returns {applied:[], rejected:[]} — no `ok`
      // key. Success = zero rejected keys.
      const rejected = (result && result.rejected) || [];
      const savedOk = r.ok && rejected.length === 0;
      if (status) {
        status.textContent = savedOk ? 'SAVED' : 'ERROR';
        status.className = savedOk ? 'badge badge--green' : 'badge badge--red';
        setTimeout(() => { if (status) status.textContent = ''; }, 2000);
      }
      if (savedOk) setTimeout(() => closeSettingsModal(), 800);
    } catch (e) {
      const status = document.getElementById('settings-status');
      if (status) { status.textContent = 'NETWORK ERROR'; status.className = 'badge badge--red'; }
    }
  });

  // ── Export ──
  function openExportModal() { dom.exportModal?.classList.add('modal--open'); }
  function closeExportModal() { dom.exportModal?.classList.remove('modal--open'); }
  dom.exportModal?.addEventListener('click', (e) => { if (e.target.matches('[data-close]')) closeExportModal(); });
  dom.openExports?.addEventListener('click', openExportModal);

  // ── Keyboard shortcuts ──
  document.addEventListener('keydown', (e) => {
    const anyModalOpen = () => !!document.querySelector('.modal-overlay.modal--open');
    if (e.key.toLowerCase() === 'r' && !anyModalOpen() && document.activeElement.tagName !== 'INPUT' && !e.metaKey && !e.ctrlKey) fetchSnapshot();
    else if (e.key === 'Escape') { closeWalletModal(); closeSettingsModal(); closeExportModal(); }
    else if (e.key.toLowerCase() === 'w' && !anyModalOpen() && document.activeElement.tagName !== 'INPUT' && !e.metaKey && !e.ctrlKey) {
      openWalletModal();
    }
  });

  // ══════════════════════════════════════════════════════════════════════
  // CYPHER // LIVE MINING — Summary, Best Share, Event Log
  // ══════════════════════════════════════════════════════════════════════

  let _lmLoggedActive = false;
  let _lmBestShareEver = 0; let _lmBestShareWorker = ''; let _lmBestShareTime = '';
  let _lmEventCount = 0; const _LM_EVENT_MAX = 50;

  function parseBestDiff(bd) {
    if (!bd) return 0;
    if (typeof bd === 'number') return bd;
    const str = String(bd).trim(); const m = str.match(/^([\d.,]+)/);
    if (!m) return 0;
    let val = parseFloat(m[1].replace(/,/g, ''));
    const su = str.match(/[a-zA-Z]+$/);
    if (su) { const mult = { K: 1e3, M: 1e6, G: 1e9, T: 1e12, P: 1e15, E: 1e18 }; val *= (mult[su[0].toUpperCase()] || 1); }
    return val;
  }

  function _updateLiveMiningSummary(allWorkers, primaryWorker) {
    if (!dom.lmSummaryWallet) return;
    if (dom.lmSummaryWallet) dom.lmSummaryWallet.textContent = window.BTC_ADDRESS ? fmt.shortAddr(window.BTC_ADDRESS) : '\u2014';
    if (dom.lmSummaryDot) dom.lmSummaryDot.classList.toggle('offline', !allWorkers || !allWorkers.length);
    const workers = allWorkers || [];
    if (dom.lmSummaryWorkers) dom.lmSummaryWorkers.textContent = workers.length;
    if (workers.length > 0) {
      let totalHr = 0, bestDiff = 0, bestDiffStr = '\u2014';
      workers.forEach(w => { const hr = Number(w.hashrate || 0); totalHr += hr; const bd = parseBestDiff(w.bestDifficulty); if (bd > bestDiff) { bestDiff = bd; bestDiffStr = fmt.diff(bd); } });
      if (dom.lmSummaryHr) dom.lmSummaryHr.textContent = fmt.hashrate(totalHr);
      if (dom.lmSummaryBest) dom.lmSummaryBest.textContent = bestDiffStr;
    } else { if (dom.lmSummaryHr) dom.lmSummaryHr.textContent = '\u2014'; if (dom.lmSummaryBest) dom.lmSummaryBest.textContent = '\u2014'; }
  }

  function _updateBestShare(allWorkers) {
    if (!dom.lmBestShare) return;
    let best = 0, bestW = '';
    (allWorkers || []).forEach(w => { const bd = parseBestDiff(w.bestDifficulty); if (bd > best) { best = bd; bestW = w.name || w.id || 'unknown'; } });
    if (best > _lmBestShareEver && best > 0) {
      _lmBestShareEver = best; _lmBestShareWorker = bestW; _lmBestShareTime = new Date().toISOString().slice(11, 19) + ' UTC';
      if (dom.lmBestShareVal) dom.lmBestShareVal.textContent = fmt.diff(best);
      if (dom.lmBestShareWorker) dom.lmBestShareWorker.textContent = 'Worker: ' + bestW;
      if (dom.lmBestShareTime) dom.lmBestShareTime.textContent = _lmBestShareTime;
      dom.lmBestShare.style.display = 'block';
      dom.lmBestShare.classList.remove('lm-best-share--flash'); void dom.lmBestShare.offsetWidth; dom.lmBestShare.classList.add('lm-best-share--flash');
    } else if (_lmBestShareEver > 0) {
      if (dom.lmBestShareVal) dom.lmBestShareVal.textContent = fmt.diff(_lmBestShareEver);
      dom.lmBestShare.style.display = 'block';
    }
  }

  function _logMiningEvent(type, msg) {
    if (!dom.lmEventLogTerminal) return;
    _lmEventCount++;
    const now = new Date();
    const ts = String(now.getHours()).padStart(2,'0')+':'+String(now.getMinutes()).padStart(2,'0')+':'+String(now.getSeconds()).padStart(2,'0');
    let cls = ''; if (type==='SHARE') cls='tag-share'; else if (type==='BEST') cls='tag-best'; else if (type==='JOB') cls='tag-job';
    dom.lmEventLogTerminal.insertAdjacentHTML('beforeend', `<div class="lm-event-log__line"><span class="ts">[${ts}]</span><span class="${cls}">${type}</span> ${escapeHtml(msg)}</div>`);
    while (_lmEventCount > _LM_EVENT_MAX) { const f = dom.lmEventLogTerminal.querySelector('.lm-event-log__line'); if (!f) break; f.remove(); _lmEventCount--; }
    dom.lmEventLogTerminal.scrollTop = dom.lmEventLogTerminal.scrollHeight;
  }

  document.getElementById('lm-event-log-clear')?.addEventListener('click', () => {
    if (dom.lmEventLogTerminal) dom.lmEventLogTerminal.innerHTML = '<div class="lm-event-log__line ts-mute">> CLEARED</div>';
    _lmEventCount = 1;
  });

  function renderLiveMining(allWorkers, primaryWorker) {
    if (!dom.lmGrid) return;
    const workers = allWorkers || [];
    if (!workers.length) { dom.lmGrid.innerHTML = '<div class="lm-empty">awaiting worker data</div>'; if (dom.lmStatusBadge) dom.lmStatusBadge.textContent = 'IDLE'; return; }
    if (dom.lmStatusBadge) dom.lmStatusBadge.textContent = 'LIVE';
    if (dom.lmWorkersBadge) dom.lmWorkersBadge.textContent = `${workers.length} worker${workers.length === 1 ? '' : 's'}`;
    _updateLiveMiningSummary(workers, primaryWorker);
    _updateBestShare(workers);
    if (workers.length > 0 && !_lmLoggedActive) { _logMiningEvent('JOB', `${workers.length} worker${workers.length===1?'':'s'} active`); _lmLoggedActive = true; }

    let maxHr = 0; workers.forEach(w => { const h = Number(w.hashrate || 0); if (h > maxHr) maxHr = h; });
    const html = workers.map((w, i) => {
      const hr = Number(w.hashrate || 0);
      const pct = maxHr > 0 ? Math.min(100, (hr / maxHr) * 100) : 0;
      const isPrimary = primaryWorker && (w.name === primaryWorker.name || w.id === primaryWorker.id);
      return `<div class="lm-worker${isPrimary ? ' is-primary' : ''}">
        <div class="lm-worker__head"><span class="lm-worker__name">${escapeHtml(w.name || w.id || `Worker ${i+1}`)}</span>${isPrimary ? '<span class="lm-worker__badge">PRIMARY</span>' : ''}</div>
        <div class="lm-worker__hr-bar-wrap"><div class="lm-worker__hr-bar" style="width:${pct.toFixed(1)}%"></div></div>
        <div class="lm-worker__stats">
          <div class="lm-worker__stat"><span class="lbl">HASHRATE</span><span class="val">${fmt.hashrate(hr)}</span></div>
          <div class="lm-worker__stat"><span class="lbl">BEST DIFF</span><span class="val">${fmt.diff(w.bestDifficulty)}</span></div>
          <div class="lm-worker__stat"><span class="lbl">LAST SHARE</span><span class="val">${w.lastSubmission ? fmt.age(w.lastSubmission) : '\u2014'}</span></div>
          <div class="lm-worker__stat"><span class="lbl">UPTIME</span><span class="val">${w.uptime ? fmt.uptime(w.uptime) : '\u2014'}</span></div>
        </div>
      </div>`;
    }).join('');
    dom.lmGrid.innerHTML = html;
  }

  // ══════════════════════════════════════════════════════════════════════
  // AXE FLEET — render device cards from snapshot.axe_fleet
  // ══════════════════════════════════════════════════════════════════════

  // ── REMOTE ACCESS · TAILSCALE — fetch local tailscale status ──
  function renderTailscale(d) {
    const set = (id, v) => { const el = document.getElementById(id); if (el) el.textContent = v; };
    const setDot = (id, ok) => { const el = document.getElementById(id); if (el) el.style.background = ok ? 'var(--accent-green)' : 'var(--accent-red)'; };
    if (!d || !d.tailscale_installed) {
      set('remote-status-badge', 'NOT INSTALLED');
      set('remote-status-text', 'Tailscale CLI não encontrado no host — instale para acesso remoto');
      set('remote-host-ip', '—'); set('remote-hostname', '—'); set('remote-tailnet', '—');
      set('remote-online-since', '—'); set('remote-last-check', '—');
      set('health-val-host', 'local'); set('health-val-tailscale', 'absent'); set('health-val-miners', '—'); set('health-val-tuya', '—');
      setDot('health-dot-host', true); setDot('health-dot-tailscale', false);
      return;
    }
    const ok = !!d.connected;
    set('remote-status-badge', ok ? 'CONNECTED' : 'DISCONNECTED');
    set('remote-status-text', ok ? 'Tailscale conectado — acesso remoto disponível' : (d.error || 'Tailscale não conectado'));
    set('remote-host-ip', d.ip || '—');
    set('remote-hostname', d.hostname || '—');
    set('remote-tailnet', d.magic_dns_name ? d.magic_dns_name.split('.').slice(1).join('.') : '—');
    set('remote-online-since', d.online ? 'online' : (d.last_seen || '—'));
    set('remote-last-check', d.checked_at ? fmt.age(d.checked_at) : '—');
    set('health-val-host', 'local'); set('health-val-tailscale', ok ? 'connected' : 'offline');
    set('health-val-miners', '—'); set('health-val-tuya', '—');
    setDot('health-dot-host', true); setDot('health-dot-tailscale', ok);
  }
  async function fetchTailscale() {
    try {
      const r = await fetch('/api/tailscale');
      if (!r.ok) throw new Error('http ' + r.status);
      const d = await r.json();
      renderTailscale(d);
    } catch (e) {
      const b = document.getElementById('remote-status-badge');
      if (b) b.textContent = 'ERROR';
      const t = document.getElementById('remote-status-text');
      if (t) t.textContent = 'falha ao consultar tailscale: ' + (e.message || 'unknown');
    }
  }
  document.getElementById('remote-test-btn')?.addEventListener('click', () => fetchTailscale());

  // ── REMOTE ACCESS · TAILSCALE — onboarding scope + limitations (G3) ──
  // The backend /api/axe-fleet/remote/onboarding returns the step checklist
  // PLUS an honest scope (what the user can do remotely) and limitations
  // (Tailscale constraints). Rendered here so the tutorial sets expectations
  // before the user wires everything up.
  function renderRemoteOnboarding(d) {
    if (!d) return;
    const set = (id, v) => { const el = document.getElementById(id); if (el) el.textContent = v; };
    // Checklist: rebuild from the payload — the backend is the source of
    // truth (label + instructions + done per step). Mapping onto the static
    // li items was semantically wrong (dashboard_reachable → 'verificar
    // miners', li[5] never updated, install+login collapsed into one item).
    const listEl = document.getElementById('checklist-list');
    if (listEl && Array.isArray(d.steps)) {
      listEl.innerHTML = d.steps.map(s =>
        '<li class="remote-checklist__item ' + (s.done ? 'completed' : 'pending') + '" data-step="' + escapeHtml(String(s.id)) + '">' +
          '<span class="rci-icon">' + (s.done ? '●' : '○') + '</span>' +
          '<span class="rci-text">' + escapeHtml(s.label || s.id) + '</span>' +
          '<span class="rci-status">' + (s.done ? 'ok' : 'pendente') + '</span>' +
        '</li>'
      ).join('');
    }
    // Scope + limitations lists (fill the empty containers).
    const scopeEl = document.getElementById('remote-scope-list');
    if (scopeEl && Array.isArray(d.scope)) {
      scopeEl.innerHTML = d.scope.map(s => '<li>' + escapeHtml(s) + '</li>').join('') || '<li>—</li>';
    }
    const limEl = document.getElementById('remote-limits-list');
    if (limEl && Array.isArray(d.limitations)) {
      limEl.innerHTML = d.limitations.map(s => '<li>' + escapeHtml(s) + '</li>').join('') || '<li>—</li>';
    }
    set('remote-checklist-progress', d.progress || '—/—');
  }
  async function fetchRemoteOnboarding() {
    try {
      const r = await fetch('/api/axe-fleet/remote/onboarding');
      if (!r.ok) return;
      renderRemoteOnboarding(await r.json());
    } catch (e) { /* best-effort: the static checklist stays pending */ }
  }

  async function fetchAxeFleet() {
    try {
      const r = await authFetch('/api/axe-fleet/health');
      if (!r.ok) return;
      const data = await r.json();
      renderAxeFleet(data);
    } catch (e) {
      if (dom.axeFleetStatusBadge) dom.axeFleetStatusBadge.textContent = 'ERROR';
    }
  }

  function renderAxeFleet(data) {
    if (!dom.axeGrid) return;
    if (!data || !data.fleet_stats) {
      dom.axeGrid.innerHTML = '<div class="mkt-empty" style="padding:20px;text-align:center">no AxeOS devices connected — register your hardware to enable fleet monitoring' +
        '<div class="axe-empty__hint" style="margin-top:8px">⚠ O host precisa estar na mesma rede local dos miners (ou usar Tailscale para alcançá-los remotamente).</div></div>';
      if (dom.axeFleetStatusBadge) dom.axeFleetStatusBadge.textContent = '0 devices';
      if (dom.axeFleetCountBadge) dom.axeFleetCountBadge.textContent = '0';
      return;
    }

    const fleet = data.fleet_stats || {};
    const devices = data.device_health || [];

    // Summary stats
    if (dom.axeSummaryHr) dom.axeSummaryHr.textContent = fleet.total_hashrate_str || '—';
    if (dom.axeSummaryOnline) countUpValue(dom.axeSummaryOnline, String(fleet.online || 0));
    if (dom.axeSummaryWarning) countUpValue(dom.axeSummaryWarning, String(fleet.warning || 0));
    if (dom.axeSummaryOffline) countUpValue(dom.axeSummaryOffline, String(fleet.offline || 0));
    if (dom.axeSummaryHealth) dom.axeSummaryHealth.textContent = fleet.avg_health_score != null ? Math.round(fleet.avg_health_score) + '/100' : '—';
    if (dom.axeSummaryTemp) dom.axeSummaryTemp.textContent = fleet.avg_temperature_c != null ? fleet.avg_temperature_c.toFixed(1) + '°C' : '—';
    if (dom.axeSummaryPower) dom.axeSummaryPower.textContent = fleet.total_power_w ? fleet.total_power_w.toFixed(0) + 'W' : '—';
    if (dom.axeSummaryEff) dom.axeSummaryEff.textContent = fleet.efficiency_jth != null ? fleet.efficiency_jth.toFixed(1) + ' J/TH' : '—';
    if (dom.axeSummaryBest) dom.axeSummaryBest.textContent = fleet.best_diff ? fmt.diff(fleet.best_diff) : '—';

    // Count badge
    const total = fleet.total_devices || 0;
    if (dom.axeFleetCountBadge) dom.axeFleetCountBadge.textContent = total + ' device' + (total === 1 ? '' : 's');

    // Status badge
    if (dom.axeFleetStatusBadge) {
      if (total === 0) dom.axeFleetStatusBadge.textContent = 'NO DEVICES';
      else if (fleet.offline === total) dom.axeFleetStatusBadge.textContent = 'ALL OFFLINE';
      else if (fleet.warning > 0) dom.axeFleetStatusBadge.textContent = fleet.warning + ' WARNING';
      else if (fleet.online === total) dom.axeFleetStatusBadge.textContent = 'ALL ONLINE';
      else dom.axeFleetStatusBadge.textContent = fleet.online + '/' + total + ' ONLINE';
      dom.axeFleetStatusBadge.className = 'badge';
      if (fleet.offline === total) dom.axeFleetStatusBadge.classList.add('badge--red');
      else if (fleet.warning > 0) dom.axeFleetStatusBadge.classList.add('badge--amber');
      else dom.axeFleetStatusBadge.classList.add('badge--green');
    }

    // Group devices by status
    const onlineDevs = devices.filter(d => d.status === 'ONLINE' || d.status === 'HASHING');
    const warningDevs = devices.filter(d => d.status === 'WARNING');
    const offlineDevs = devices.filter(d => d.status !== 'ONLINE' && d.status !== 'HASHING' && d.status !== 'WARNING');

    if (!devices.length) {
      dom.axeGrid.innerHTML = '<div class="axe-empty">no devices registered — add your first Bitaxe/NerdAxe via the + ADD button' +
        '<div class="axe-empty__hint">⚠ O host do dashboard precisa alcançar os miners na MESMA rede local (ou via Tailscale IP). Se o device não aparecer, confira se o IP está correto e se o miner responde em /system/info.</div></div>';
      return;
    }

    // Compute max hashrate for proportional bars
    const maxHr = Math.max(...devices.map(d => (d.telemetry && d.telemetry.hashrate_hs) || 0), 1);

    let html = '';

    // Online group
    if (onlineDevs.length) {
      html += '<div class="axe-group-header"><strong>' + onlineDevs.length + '</strong> ONLINE</div>';
      html += onlineDevs.map(d => _renderAxeCard(d, maxHr)).join('');
    }

    // Warning group
    if (warningDevs.length) {
      html += '<div class="axe-group-header"><strong>' + warningDevs.length + '</strong> WARNING</div>';
      html += warningDevs.map(d => _renderAxeCard(d, maxHr)).join('');
    }

    // Offline group
    if (offlineDevs.length) {
      html += '<div class="axe-group-header"><strong>' + offlineDevs.length + '</strong> OFFLINE</div>';
      html += offlineDevs.map(d => _renderAxeCard(d, maxHr)).join('');
    }

    dom.axeGrid.innerHTML = html;

    // Attach click handlers for detail panel
    dom.axeGrid.querySelectorAll('.axe-card').forEach(card => {
      card.addEventListener('click', (e) => {
        // Ignore clicks on command buttons (they have their own handler)
        if (e.target.closest('.axe-cmd-btn')) return;
        const id = card.dataset.deviceId;
        if (id) openAxeDetail(id);
      });
    });

    // Attach command button handlers
    dom.axeGrid.querySelectorAll('.axe-cmd-btn').forEach(btn => {
      btn.addEventListener('click', async (e) => {
        e.stopPropagation();
        const deviceId = btn.dataset.deviceId;
        const command = btn.dataset.cmd;
        if (!deviceId || !command) return;

        // Confirmation for restart and pause
        if (command === 'restart') {
          if (!confirm('Restart this miner? It will go offline for ~30 seconds.')) return;
        } else if (command === 'pause') {
          if (!confirm('Pause mining on this device? Use Resume to restart.')) return;
        }

        btn.disabled = true;
        btn.textContent = '...';

        try {
          const resp = await fetch('/api/devices/' + encodeURIComponent(deviceId) + '/command', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ command: command }),
          });
          const data = await resp.json();
          if (data.success) {
            showToast('success', command + ' sent to ' + (btn.closest('.axe-card')?.querySelector('.axe-card__name')?.textContent || 'device'));
          } else {
            showToast('error', data.error || 'Command failed');
          }
        } catch (err) {
          showToast('error', 'Network error: ' + err.message);
        } finally {
          btn.disabled = false;
          btn.textContent = command === 'restart' ? '↻ Restart' : command === 'identify' ? '◈ Identify' : command === 'pause' ? '⎔ Pause' : '⎔ Resume';
        }
      });
    });
  }

  function _renderAxeCard(d, maxHr) {
    maxHr = maxHr || 1;
    const tel = d.telemetry || {};
    const status = d.status || 'OFFLINE';
    const isOnline = status === 'ONLINE' || status === 'HASHING';
    const isWarning = status === 'WARNING';
    const isOffline = !isOnline && !isWarning;
    const statusClass = isOnline ? 'online' : isWarning ? 'warning' : 'offline';
    const hrStr = tel.hashrate_str || '—';

    // Health score ring
    const hs = d.health_score || 0;
    const circumference = 2 * Math.PI * 14; // r=14
    const offset = circumference * (1 - hs / 100);
    const healthColor = hs >= 80 ? 'var(--accent-green)' : hs >= 50 ? 'var(--accent-amber)' : 'var(--accent-red)';
    const healthSvg = '<svg viewBox="0 0 32 32"><circle class="axe-card__health-bg" cx="16" cy="16" r="14"/><circle class="axe-card__health-fill" cx="16" cy="16" r="14" stroke="' + healthColor + '" stroke-dasharray="' + circumference + '" stroke-dashoffset="' + offset + '"/></svg>';

    // Capability badges
    const caps = d.capabilities || [];
    const capHtml = caps.slice(0, 5).map(c => '<span class="axe-cap-badge is-supported">' + escapeHtml(c) + '</span>').join('');

    // Stats — Fase 5: chip temp, VR temp, hashrate windows with NOT AVAILABLE fallback.
    // NOTE: _num() guard (shared, defined near fmt) — backend may send the
    // literal string "NOT AVAILABLE" for missing fields (core /api/devices
    // normalizes), so a plain != null check would crash .toFixed().
    const _NA = 'NOT AVAILABLE';
    const chipTemp = fmt.num(tel.chip_temp) ? tel.chip_temp.toFixed(0) + '°C' : (fmt.num(tel.temp_asic) ? tel.temp_asic.toFixed(0) + '°C' : (fmt.num(tel.temperature) ? tel.temperature.toFixed(0) + '°C' : _NA));
    const vrTemp = fmt.num(tel.vr_temp) ? tel.vr_temp.toFixed(0) + '°C' : (fmt.num(tel.temp_vreg) ? tel.temp_vreg.toFixed(0) + '°C' : _NA);
    const hr1h = fmt.num(tel.hashrate_1h) ? fmt.hashrate(tel.hashrate_1h) : _NA;
    const temp = fmt.num(tel.temperature) ? tel.temperature.toFixed(0) + '°C' : '—';
    const bestDiff = tel.best_diff ? fmt.diff(tel.best_diff) : '—';
    const shares = tel.shares_accepted != null ? tel.shares_accepted.toLocaleString() : '—';
    const uptime = tel.uptime_str || '—';
    const freq = tel.frequency_mhz ? tel.frequency_mhz + ' MHz' : '—';
    const hw = tel.hw_error_pct != null ? tel.hw_error_pct.toFixed(2) + '%' : '—';
    // FLEET audit G1: EFF + POWER were computed but never rendered on the
    // card. Fallback NOT AVAILABLE like CHIP/VR/HR 1H (honest, no zeros).
    const power = fmt.num(tel.power_watts) ? tel.power_watts.toFixed(0) + 'W' : _NA;
    const eff = fmt.num(tel.efficiency_jth) ? tel.efficiency_jth.toFixed(2) + ' J/TH' : _NA;

    // ── FLEET audit: PING + POOL + advice chips ──
    // latency_ms is probed by the backend per reachable device; the card
    // colors it by band (green ≤50ms, amber ≤150ms, red >150ms).
    const pingMs = fmt.num(d.latency_ms) ? d.latency_ms : null;
    const pingStr = pingMs != null ? pingMs + 'ms' : '—';
    const pingClass = pingMs == null ? '' : (pingMs <= 50 ? 'green' : pingMs <= 150 ? 'gold' : 'red');
    // POOL: prefer the pool host from pool_url, fall back to stratum_status.
    let poolStr = tel.stratum_status || '—';
    const poolRaw = tel.pool_url || '';
    if (poolRaw) {
      const host = String(poolRaw).replace(/^stratum\+tcp:\/\//, '').replace(/^[^@]+@/, '').split(':')[0];
      if (host) poolStr = host;
    }
    // Advice chips from the backend rule engine (healthy fleet → empty).
    const adviceList = Array.isArray(d.advice) ? d.advice : [];
    const adviceHtml = adviceList.length
      ? '<div class="axe-card__advice">' + adviceList.map(a => '<span class="axe-card__advice-chip">' + escapeHtml(a) + '</span>').join('') + '</div>'
      : '';

    // Check if any commands are supported
    var supportedCmds = d.capabilities || [];
    var hasCommands = supportedCmds.indexOf('restart') >= 0 || supportedCmds.indexOf('identify') >= 0 || supportedCmds.indexOf('pause') >= 0 || supportedCmds.indexOf('resume') >= 0;

    return '<div class="axe-card ' + (isOnline ? 'is-online' : isWarning ? 'is-warning' : 'is-offline') + '" data-device-id="' + escapeHtml(d.id) + '">' +
      '<div class="axe-card__head">' +
        '<div class="axe-card__health">' + healthSvg + '<span class="axe-card__health-label" style="color:' + healthColor + '">' + hs + '</span></div>' +
        '<div style="display:flex;flex-direction:column;gap:2px;flex:1;padding-left:10px">' +
          '<div style="display:flex;align-items:center;gap:6px">' +
            '<span class="axe-card__name">' + escapeHtml(d.name) + '</span>' +
            '<span class="axe-card__status-dot ' + statusClass + '"></span>' +
          '</div>' +
          // FLEET audit G2: manufacturer from the payload (fleet_health
          // serializes it). Fallback NOT AVAILABLE when absent.
          '<div class="axe-card__model">' + escapeHtml(d.manufacturer || _NA) + ' · ' + escapeHtml(d.model || 'unknown') + ' · ' + hrStr + '</div>' +
        '</div>' +
      '</div>' +
      (caps.length ? '<div class="axe-card__caps">' + capHtml + '</div>' : '') +
      '<div class="axe-card__mh-wrap"><div class="axe-card__mh-bar" style="width:' + Math.min(100, ((tel.hashrate_hs || 0) / maxHr) * 100) + '%"></div></div>' +
      '<div class="axe-card__stats">' +
        '<div class="axe-card__stat"><div class="lbl">TEMP</div><div class="val ' + (fmt.num(tel.temperature) && tel.temperature > 70 ? 'red' : fmt.num(tel.temperature) && tel.temperature > 55 ? 'gold' : 'green') + '">' + temp + '</div></div>' +
        '<div class="axe-card__stat"><div class="lbl">CHIP</div><div class="val cyan">' + chipTemp + '</div></div>' +
        '<div class="axe-card__stat"><div class="lbl">VR</div><div class="val cyan">' + vrTemp + '</div></div>' +
        '<div class="axe-card__stat"><div class="lbl">HR 1H</div><div class="val cyan">' + hr1h + '</div></div>' +
        '<div class="axe-card__stat"><div class="lbl">EFF</div><div class="val cyan">' + eff + '</div></div>' +
        '<div class="axe-card__stat"><div class="lbl">POWER</div><div class="val cyan">' + power + '</div></div>' +
        '<div class="axe-card__stat"><div class="lbl">DIFF</div><div class="val gold">' + bestDiff + '</div></div>' +
        '<div class="axe-card__stat"><div class="lbl">UPTIME</div><div class="val cyan">' + uptime + '</div></div>' +
        '<div class="axe-card__stat"><div class="lbl">PING</div><div class="val ' + pingClass + '">' + pingStr + '</div></div>' +
        '<div class="axe-card__stat"><div class="lbl">POOL</div><div class="val cyan" title="' + escapeHtml(tel.pool_url || tel.stratum_status || '') + '">' + escapeHtml(poolStr) + '</div></div>' +
      '</div>' +
      adviceHtml +
      (hasCommands ? '<div class="axe-card__cmds">' +
        (supportedCmds.indexOf('restart') >= 0 ? '<button class="axe-cmd-btn axe-cmd-btn--restart" data-device-id="' + escapeHtml(d.id) + '" data-cmd="restart">↻ Restart</button>' : '') +
        (supportedCmds.indexOf('identify') >= 0 ? '<button class="axe-cmd-btn axe-cmd-btn--identify" data-device-id="' + escapeHtml(d.id) + '" data-cmd="identify">◈ Identify</button>' : '') +
        (supportedCmds.indexOf('pause') >= 0 ? '<button class="axe-cmd-btn axe-cmd-btn--pause" data-device-id="' + escapeHtml(d.id) + '" data-cmd="pause">⎔ Pause</button>' : '') +
      '</div>' : '<div class="axe-card__cmds axe-card__cmds--ro"><span class="axe-card__ro-badge">READ-ONLY</span></div>') +
    '</div>';
  }

  function openAxeDetail(deviceId) {
    if (!dom.axeDetail || !dom.axeDetailTitle || !dom.axeDetailBody) return;
    dom.axeDetail.style.display = 'block';
    dom.axeDetailTitle.textContent = 'Loading device...';
    dom.axeDetailBody.innerHTML = '<div class="axe-detail__loading">loading telemetry…</div>';

    authFetch('/api/axe-fleet/devices/' + encodeURIComponent(deviceId))
      .then(r => r.json())
      .then(data => {
        const dev = data.device || {};
        const tel = data.latest_telemetry || {};
        dom.axeDetailTitle.textContent = dev.name || 'Device';

        const items = [
          { lbl: 'Model', val: dev.model || 'unknown' },
          { lbl: 'Firmware', val: (dev.firmware || '') + ' ' + (dev.firmware_version || '') },
          { lbl: 'IP Address', val: dev.ip_address || '—' },
          { lbl: 'Status', val: dev.status || 'OFFLINE', cls: dev.status === 'ONLINE' ? 'green' : 'red' },
          { lbl: 'Hashrate', val: fmt.hashrate(tel.hashrate_hs || 0) },
          { lbl: 'Hashrate 1m', val: fmt.num(tel.hashrate_1m) ? fmt.hashrate(tel.hashrate_1m) : 'NOT AVAILABLE' },
          { lbl: 'Hashrate 10m', val: fmt.num(tel.hashrate_10m) ? fmt.hashrate(tel.hashrate_10m) : 'NOT AVAILABLE' },
          { lbl: 'Hashrate 1h', val: fmt.num(tel.hashrate_1h) ? fmt.hashrate(tel.hashrate_1h) : 'NOT AVAILABLE' },
          { lbl: 'Chip Temp', val: fmt.num(tel.chip_temp) ? tel.chip_temp + '°C' : (fmt.num(tel.temp_asic) ? tel.temp_asic + '°C' : 'NOT AVAILABLE'), cls: fmt.num(tel.chip_temp) && tel.chip_temp > 70 ? 'red' : 'green' },
          { lbl: 'VR Temp', val: fmt.num(tel.vr_temp) ? tel.vr_temp + '°C' : (fmt.num(tel.temp_vreg) ? tel.temp_vreg + '°C' : 'NOT AVAILABLE') },
          { lbl: 'Temperature', val: fmt.num(tel.temperature) ? tel.temperature + '°C' : '—', cls: fmt.num(tel.temperature) && tel.temperature > 70 ? 'red' : 'green' },
          { lbl: 'Power', val: tel.power_watts ? tel.power_watts + ' W' : '—' },
          { lbl: 'Frequency', val: tel.frequency_mhz ? tel.frequency_mhz + ' MHz' : '—' },
          { lbl: 'Voltage', val: tel.voltage_mv ? tel.voltage_mv + ' mV' : '—' },
          { lbl: 'Best Diff', val: tel.best_diff ? fmt.diff(tel.best_diff) : '—', cls: 'gold' },
          { lbl: 'Shares Accepted', val: tel.shares_accepted != null ? tel.shares_accepted.toLocaleString() : '—' },
          { lbl: 'Shares Rejected', val: tel.shares_rejected != null ? tel.shares_rejected.toLocaleString() : '—' },
          { lbl: 'HW Error %', val: fmt.num(tel.hw_error_pct) ? tel.hw_error_pct.toFixed(2) + '%' : '—', cls: fmt.num(tel.hw_error_pct) && tel.hw_error_pct > 1 ? 'red' : 'green' },
          { lbl: 'Efficiency', val: fmt.num(tel.efficiency_jth) ? tel.efficiency_jth.toFixed(1) + ' J/TH' : '—' },
          { lbl: 'Uptime', val: tel.uptime_str || '—' },
          { lbl: 'Free Heap', val: tel.free_heap ? tel.free_heap.toLocaleString() + ' B' : '—' },
          { lbl: 'WiFi RSSI', val: tel.wifi_rssi != null ? tel.wifi_rssi + ' dBm' : '—' },
          { lbl: 'Last Seen', val: dev.last_seen ? fmt.age(dev.last_seen) : '—' },
        ];

        dom.axeDetailBody.innerHTML = items.map(it =>
          '<div class="axe-detail__item"><div class="lbl">' + escapeHtml(it.lbl) + '</div><div class="val' + (it.cls ? ' ' + it.cls : '') + '">' + escapeHtml(String(it.val)) + '</div></div>'
        ).join('');
      })
      .catch(() => {
        dom.axeDetailBody.innerHTML = '<div class="axe-detail__loading">error loading device telemetry</div>';
      });
  }

  function initAxeFleetControls() {
    const addBtn = document.getElementById('axe-fleet-add');
    const form = document.getElementById('axe-add-form');
    const cancelBtn = document.getElementById('axe-add-cancel');
    const saveBtn = document.getElementById('axe-add-save');
    const ipInput = document.getElementById('axe-add-ip');
    const nameInput = document.getElementById('axe-add-name');
    const statusEl = document.getElementById('axe-add-status');
    if (!addBtn || !form) return;

    addBtn.addEventListener('click', () => {
      form.style.display = 'block';
      setTimeout(() => ipInput?.focus(), 100);
    });
    cancelBtn?.addEventListener('click', () => {
      form.style.display = 'none';
      if (statusEl) statusEl.textContent = '';
      if (ipInput) ipInput.value = '';
      if (nameInput) nameInput.value = '';
    });

    // Device detail close
    if (dom.axeDetailClose) {
      dom.axeDetailClose.addEventListener('click', () => {
        if (dom.axeDetail) dom.axeDetail.style.display = 'none';
      });
    }
    saveBtn?.addEventListener('click', async () => {
      if (!statusEl || !ipInput) return;
      const ip = ipInput.value.trim();
      if (!ip) { statusEl.textContent = '? enter IP address'; statusEl.style.color = 'var(--accent-red)'; return; }
      statusEl.textContent = '> connecting...';
      statusEl.style.color = 'var(--text-tertiary)';
      try {
        const r = await authFetch('/api/axe-fleet/devices', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ ip_address: ip, name: nameInput?.value?.trim() || '' })
        });
        const data = await r.json();
        if (!r.ok) { statusEl.textContent = '? ' + (data.error || 'failed'); statusEl.style.color = 'var(--accent-red)'; return; }
        statusEl.textContent = '? added — refreshing...';
        statusEl.style.color = 'var(--accent-green)';
        setTimeout(() => { form.style.display = 'none'; if (ipInput) ipInput.value = ''; if (nameInput) nameInput.value = ''; statusEl.textContent = ''; fetchAxeFleet(); }, 1500);
      } catch (e) {
        statusEl.textContent = '? network error: ' + e.message;
        statusEl.style.color = 'var(--accent-red)';
      }
    });
  }

  // ══════════════════════════════════════════════════════════════════════
  // HASH SEARCH ENGINE (old — disabled, superseded by hunt engine)
  // ══════════════════════════════════════════════════════════════════════

  function _updateHashSearchState(worker, network) { /* no-op: superseded by _huntUpdateState */ }

  // ══════════════════════════════════════════════════════════════════════
  // HASH HUNT CANVAS ENGINE
  // ══════════════════════════════════════════════════════════════════════

  const _hunt = {
    canvas: null, ctx: null, running: false, rafId: null,
    particles: [], maxParticles: 500, targetY: 0, frontierY: 0, w: 0, h: 0,
    hr: 0, bestDiff: 0, netDiff: 0, startTime: 0,
    frameCount: 0, totalHashes: 0, dpr: 1,
    floatingTexts: [], pBlockCum: 0, expBlocks: 0,
    streamLines: 0, streamQueue: [], shareIdx: 0,
    metricsHrHistory: [], sharesSeen: new Set(),
  };

  function _huntInit() {
    _hunt.canvas = document.getElementById('hunt-canvas'); if (!_hunt.canvas) return;
    _hunt.ctx = _hunt.canvas.getContext('2d');
    setTimeout(() => _hunt.resize(), 50);
    _hunt.seedParticles();
    _hunt.running = true; _hunt.startTime = performance.now() / 1000;
    window.addEventListener('beforeunload', () => { _hunt.running = false; if (_hunt.rafId) { cancelAnimationFrame(_hunt.rafId); _hunt.rafId = null; } });
    _hunt.loop();
  }

  _hunt.resize = () => {
    const wrap = document.getElementById('hunt-canvas-wrap'); if (!wrap || !_hunt.canvas) return;
    _hunt.dpr = window.devicePixelRatio || 1;
    _hunt.w = wrap.clientWidth; _hunt.h = wrap.clientHeight;
    _hunt.canvas.width = _hunt.w * _hunt.dpr; _hunt.canvas.height = _hunt.h * _hunt.dpr;
    _hunt.ctx.setTransform(_hunt.dpr, 0, 0, _hunt.dpr, 0, 0);
    _hunt.targetY = _hunt.h * 0.08; _hunt.frontierY = _hunt.h * 0.65;
  };
  window.addEventListener('resize', _hunt.resize);

  _hunt.seedParticles = () => { for (let i = 0; i < _hunt.maxParticles; i++) _hunt.particles.push(_hunt.createParticle(true)); };
  _hunt.createParticle = (randomY) => ({
    x: Math.random() * (_hunt.w || 800), y: randomY ? Math.random() * (_hunt.h || 400) : (_hunt.h || 400) + 10,
    vy: -(0.15 + Math.random() * 0.5), vx: (Math.random() - 0.5) * 0.3,
    life: 1, maxLife: 0.6 + Math.random() * 0.8,
    color: Math.random() < 0.6 ? 'cyan' : (Math.random() < 0.7 ? 'green' : 'gold'), size: 0.5 + Math.random() * 2,
  });

  _hunt.loop = () => { if (!_hunt.running) return; _hunt.frameCount++; const dt = Math.min(0.05, 1/60); _hunt.update(dt); _hunt.draw(); _hunt.rafId = requestAnimationFrame(_hunt.loop); };

  _hunt.update = (dt) => {
    const { particles, w, h, targetY, hr } = _hunt; if (!w) return;
    if (hr > 0) _hunt.totalHashes += hr * dt;
    for (let i = 0; i < particles.length; i++) {
      const p = particles[i];
      p.y += p.vy * 60 * dt; p.x += p.vx * 60 * dt; p.life -= dt / p.maxLife;
      if (p.x < 0) p.x = w; if (p.x > w) p.x = 0;
      const distToTarget = (p.y - targetY) / (_hunt.frontierY - targetY);
      if (distToTarget < 0.3) p.vy *= 0.97;
      if (p.life <= 0 || p.y < targetY) { p.y = h + Math.random() * 20; p.x = Math.random() * w; p.life = 1; p.maxLife = 0.6 + Math.random() * 0.8; p.vy = -(0.15 + Math.random() * 0.5); p.vx = (Math.random() - 0.5) * 0.3; p.color = Math.random() < 0.6 ? 'cyan' : (Math.random() < 0.7 ? 'green' : 'gold'); p.size = 0.5 + Math.random() * 2; }
    }
    if (_hunt.frameCount % 30 === 0 && hr > 0) {
      const nonce = Math.floor(Math.random() * 0xFFFFFFFF);
      _hunt.floatingTexts.push({ x: Math.random()*w*0.8+w*0.1, y: h*0.3+Math.random()*h*0.4, text: 'nonce:'+nonce.toString(16).padStart(8,'0'), life:1, maxLife:2+Math.random()*3, color:'rgba(20,184,166,' });
    }
    for (let i = _hunt.floatingTexts.length-1; i>=0; i--) { _hunt.floatingTexts[i].life -= dt/_hunt.floatingTexts[i].maxLife; _hunt.floatingTexts[i].y -= 0.3; if (_hunt.floatingTexts[i].life<=0) _hunt.floatingTexts.splice(i,1); }
    if (_hunt.frameCount % 25 === 0 && _hunt.updateStream) _hunt.updateStream();
    if (_hunt.frameCount % 60 === 0) _hunt.updateMetrics();
  };

  _hunt.draw = () => {
    const { ctx, w, h, targetY, particles, floatingTexts } = _hunt; if (!ctx || !w) return;
    ctx.fillStyle = 'rgba(5, 5, 5, 0.35)'; ctx.fillRect(0, 0, w, h);
    const tgGrad = ctx.createRadialGradient(w/2, targetY, 10, w/2, targetY, w*0.5); tgGrad.addColorStop(0, 'rgba(245,185,66,0.08)'); tgGrad.addColorStop(1, 'rgba(245,185,66,0)');
    ctx.fillStyle = tgGrad; ctx.fillRect(0, 0, w, targetY+30);
    ctx.strokeStyle = 'rgba(245,185,66,0.3)'; ctx.lineWidth = 1; ctx.setLineDash([4, 8]); ctx.beginPath(); ctx.moveTo(0, targetY); ctx.lineTo(w, targetY); ctx.stroke(); ctx.setLineDash([]);
    ctx.strokeStyle = 'rgba(6,214,240,0.15)'; ctx.lineWidth = 0.5; ctx.beginPath(); ctx.moveTo(0, _hunt.frontierY); ctx.lineTo(w, _hunt.frontierY); ctx.stroke();

    const batches = { cyan: [], green: [], gold: [] };
    for (const p of particles) {
      const alpha = p.life * (p.y < _hunt.frontierY ? 0.5 : 0.8); if (alpha < 0.02) continue;
      const proximity = 1 - Math.max(0, Math.min(1, (p.y - targetY) / (_hunt.frontierY - targetY)));
      batches[p.color].push({ x: p.x, y: p.y, size: p.size*(1+proximity*2), alpha, proximity });
    }
    ctx.fillStyle = 'rgb(6,214,240)'; for (const p of batches.cyan) { ctx.globalAlpha = p.alpha; ctx.beginPath(); ctx.arc(p.x, p.y, p.size, 0, Math.PI*2); ctx.fill(); }
    ctx.fillStyle = 'rgb(16,185,129)'; for (const p of batches.green) { ctx.globalAlpha = p.alpha*(1+p.proximity); ctx.beginPath(); ctx.arc(p.x, p.y, p.size, 0, Math.PI*2); ctx.fill(); }
    ctx.fillStyle = 'rgb(245,185,66)'; for (const p of batches.gold) { ctx.globalAlpha = p.alpha; ctx.beginPath(); ctx.arc(p.x, p.y, p.size, 0, Math.PI*2); ctx.fill(); }
    ctx.globalAlpha = 1;

    for (const ft of floatingTexts) { if (ft.life<0.05) continue; ctx.fillStyle = ft.color+(ft.life*0.6)+')'; ctx.font = '9px JetBrains Mono'; ctx.fillText(ft.text, ft.x, ft.y); }
    ctx.fillStyle = 'rgba(255,255,255,0.3)'; ctx.font = '8px JetBrains Mono';
    ctx.fillText('HASHES: '+_hunt.fmtNum(_hunt.totalHashes), 8, h-12); ctx.fillText('PARTICLES: '+particles.length, 8, h-2);
    if (_hunt.pBlockCum > 0) { ctx.fillStyle = 'rgba(245,185,66,0.5)'; ctx.font = '9px JetBrains Mono'; ctx.fillText('P(BLOCK) CUM: '+_hunt.fmtPct(_hunt.pBlockCum), w-180, h-12); }
  };

  _hunt.fmtNum = (n) => { if (n<1e3) return n.toFixed(0); if (n<1e6) return (n/1e3).toFixed(1)+'K'; if (n<1e9) return (n/1e6).toFixed(1)+'M'; if (n<1e12) return (n/1e9).toFixed(1)+'G'; if (n<1e15) return (n/1e12).toFixed(1)+'T'; return (n/1e15).toFixed(2)+'P'; };
  _hunt.fmtPct = (n) => { if (n<0.0001) return n.toExponential(2)+'%'; if (n<0.01) return n.toFixed(5)+'%'; return n.toFixed(3)+'%'; };

  _hunt.updateStream = () => {
    const feed = document.getElementById('hunt-stream-feed'); if (!feed || !_hunt.streamQueue.length) return;
    const s = _hunt.streamQueue.shift();
    const d = new Date((s.ts || 0) * 1000);
    const ts = String(d.getHours()).padStart(2,'0')+':'+String(d.getMinutes()).padStart(2,'0')+':'+String(d.getSeconds()).padStart(2,'0');
    const diff = s.share_diff_str || '\u2014'; const gap = s.gap ? Number(s.gap).toFixed(1)+'s' : '\u2014';
    _hunt.streamLines++;
    feed.insertAdjacentHTML('beforeend', `<div class="hunt-stream__line"><span class="ts">${ts}</span><span class="n">SHARE</span><span class="h">${escapeHtml(diff)}</span><span class="d">${gap}</span></div>`);
    while (_hunt.streamLines > 30) { const f = feed.querySelector('.hunt-stream__line'); if (!f) break; f.remove(); _hunt.streamLines--; }
    feed.scrollTop = feed.scrollHeight;
  };

  _hunt.updateMetrics = () => {
    const { hr, bestDiff } = _hunt;
    _hunt.metricsHrHistory.push(hr); if (_hunt.metricsHrHistory.length > 80) _hunt.metricsHrHistory.shift();
    const elHr = document.getElementById('hunt-metrics-hr'); if (elHr && hr > 0) elHr.textContent = fmt.hashrate(hr);
    const elPBlock = document.getElementById('hunt-metrics-pblock'); if (elPBlock && _hunt.pBlockCum > 0) elPBlock.textContent = _hunt.fmtPct(_hunt.pBlockCum);
    const elExp = document.getElementById('hunt-metrics-expblocks'); if (elExp) elExp.textContent = _hunt.expBlocks.toFixed(4);
    const elBest = document.getElementById('hunt-metrics-bestdiff'); if (elBest && bestDiff > 0) elBest.textContent = fmt.diff(bestDiff);
    const statusEl = document.getElementById('hunt-status-label');
    if (statusEl) statusEl.textContent = hr > 0 ? ['HASHING...','SEARCHING...','SCANNING NONCES','COMPUTING SHA-256'][Math.floor(_hunt.frameCount/120)%4] : 'AWAITING DATA';
    const frontEl = document.getElementById('hunt-frontier-label');
    if (frontEl && _hunt.totalHashes > 0) frontEl.textContent = 'FRONTIER · '+_hunt.fmtNum(_hunt.totalHashes)+' HASHES';
    _hunt.drawSparkline(); _hunt.drawGauge();
  };

  _hunt.drawSparkline = () => {
    const c = document.getElementById('hunt-sparkline'); if (!c) return;
    const dpr = window.devicePixelRatio || 1; const cssW = c.clientWidth || 200, cssH = c.clientHeight || 40;
    c.width = cssW*dpr; c.height = cssH*dpr;
    const ctx = c.getContext('2d'); ctx.setTransform(dpr,0,0,dpr,0,0); ctx.clearRect(0,0,cssW,cssH);
    const data = _hunt.metricsHrHistory; if (!data.length) return;
    const max = Math.max(...data, 1); const x = (i) => (i/Math.max(1,data.length-1))*(cssW-4)+2;
    const y = (v) => cssH-2-((v-0)/max)*(cssH-6);
    ctx.strokeStyle = '#06d6f0'; ctx.lineWidth = 1; ctx.beginPath();
    data.forEach((v,i) => { i===0 ? ctx.moveTo(x(i),y(v)) : ctx.lineTo(x(i),y(v)); }); ctx.stroke();
    const grad = ctx.createLinearGradient(0,0,0,cssH); grad.addColorStop(0,'rgba(6,214,240,0.2)'); grad.addColorStop(1,'rgba(6,214,240,0)');
    ctx.fillStyle = grad; ctx.lineTo(x(data.length-1),cssH); ctx.lineTo(x(0),cssH); ctx.closePath(); ctx.fill();
  };

  _hunt.drawGauge = () => {
    const c = document.getElementById('hunt-gauge'); if (!c) return;
    const dpr = window.devicePixelRatio || 1; const cssW = c.clientWidth || 120, cssH = c.clientHeight || 55;
    c.width = cssW*dpr; c.height = cssH*dpr;
    const ctx = c.getContext('2d'); ctx.setTransform(dpr,0,0,dpr,0,0); ctx.clearRect(0,0,cssW,cssH);
    const cx = cssW/2, cy = cssH-2, r = Math.min(cx-6, cssH-4);
    ctx.lineWidth = 8; ctx.lineCap = 'round'; ctx.strokeStyle = 'rgba(255,255,255,0.06)';
    ctx.beginPath(); ctx.arc(cx, cy, r, Math.PI, 0, false); ctx.stroke();
    const rawPct = _hunt.pBlockCum || 0;
    const displayPct = Math.min(100, Math.max(0, rawPct>0 ? (Math.log10(rawPct)+8)/8*80 : 0));
    const angle = Math.PI - (displayPct/100)*Math.PI;
    const grad = ctx.createLinearGradient(cx-r,0,cx+r,0); grad.addColorStop(0,'#00ff9f'); grad.addColorStop(0.5,'#06d6f0'); grad.addColorStop(1,'#f5b942');
    ctx.strokeStyle = grad; ctx.beginPath(); ctx.arc(cx, cy, r, Math.PI, angle, false); ctx.stroke();
    ctx.fillStyle = '#f5b942'; ctx.font = 'bold 11px Space Grotesk'; ctx.textAlign = 'center';
    ctx.fillText(rawPct<0.0001 ? rawPct.toExponential(1)+'%' : rawPct.toFixed(4)+'%', cx, cy-6);
  };

  function _huntUpdateState(worker, network, cumulativeP, expectedBlocks, recentShares) {
    _hunt.hr = (worker && worker.hashrate) ? Number(worker.hashrate) : 0;
    _hunt.bestDiff = worker && worker.bestDifficulty ? parseBestDiff(worker.bestDifficulty) : 0;
    _hunt.netDiff = (network && network.difficulty) ? Number(network.difficulty) : 0;
    _hunt.pBlockCum = cumulativeP || 0; _hunt.expBlocks = expectedBlocks || 0;
    if (recentShares && recentShares.length) {
      const queuedIds = new Set(_hunt.streamQueue.map(s => s.ts));
      for (const s of recentShares) { if (!queuedIds.has(s.ts)) _hunt.streamQueue.push(s); }
      while (_hunt.streamQueue.length > 60) _hunt.streamQueue.shift();
    }
    if (recentShares && recentShares.length) _hunt.renderShareCards(recentShares);
  }

  _hunt.renderShareCards = (shares) => {
    const grid = document.getElementById('hunt-shares-grid');
    const countEl = document.getElementById('hunt-shares-count');
    if (!grid) return; if (countEl) countEl.textContent = shares.length + ' shares';
    const newest = shares[shares.length-1];
    const cards = shares.slice(-12).reverse().map(s => {
      const d = new Date((s.ts||0)*1000);
      const ts = String(d.getHours()).padStart(2,'0')+':'+String(d.getMinutes()).padStart(2,'0')+':'+String(d.getSeconds()).padStart(2,'0');
      const isNewest = newest && s.ts === newest.ts;
      return `<div class="hunt-share-card${isNewest?' is-newest':''}"><span class="sc-lbl">TIME</span><span class="sc-val cyan">${ts}</span><span class="sc-lbl">DIFF</span><span class="sc-val">${s.share_diff_str||'\u2014'}</span><span class="sc-lbl">GAP</span><span class="sc-val green">${s.gap?Number(s.gap).toFixed(1)+'s':'\u2014'}</span><span class="sc-lbl">HASHRATE</span><span class="sc-val">${s.instantaneous_hr_str||'\u2014'}</span><div class="sc-bar"><div class="sc-bar-fill" style="width:${Math.min(100,(s.p_block_this_share||0)*100)}%"></div></div></div>`;
    }).join('');
    grid.innerHTML = cards || '<div class="hunt-shares__empty">awaiting share data</div>';
  };

  let _huntStarted = false;
  function _huntStart() { if (_huntStarted) return; _huntStarted = true;
    _hunt.streamLines = 0;
    const feed = document.getElementById('hunt-stream-feed');
    if (feed) feed.innerHTML = '<div class="hunt-stream__line"><span class="ts">TIME</span><span class="n">EVENT</span><span class="h">DIFFICULTY</span><span class="d">GAP</span></div>';
    _huntInit();
  }


  // ══════════════════════════════════════════════════════════════════════
  // SOLO MINING TERMINAL — interactive CLI
  // ══════════════════════════════════════════════════════════════════════

  const _soloTerm = {
    output: null, input: null, history: [], historyIdx: -1,
  };

  // Latest dashboard snapshot received via polling/SSE. Terminal commands
  // (status/workers/price) read this instead of fetching /api/snapshot,
  // which internally triggers external hashrate-market offers and can take
  // >1s — the E2E terminal tests only wait 1000ms after Enter.
  let _lastSnapshot = null;

  function _soloTermPrint(text, out) {
    out = out || _soloTerm.output;
    if (!out) return;
    const lines = String(text).split('\n');
    for (const line of lines) {
      const div = document.createElement('div');
      div.className = 'solo-term__line';
      div.textContent = line;
      out.appendChild(div);
    }
    out.scrollTop = out.scrollHeight;
  }

  function _soloTermPrintHTML(html, out) {
    out = out || _soloTerm.output;
    if (!out) return;
    const div = document.createElement('div');
    div.className = 'solo-term__line';
    div.innerHTML = html;
    out.appendChild(div);
    out.scrollTop = out.scrollHeight;
  }

  // Return the latest known snapshot, fetching only if not yet loaded.
  // Reuses the cached snapshot the dashboard already polls, so terminal
  // commands respond instantly instead of blocking on /api/snapshot's
  // external market-offers fetch (E2E terminal tests wait only 1s).
  async function _soloTermCachedSnapshot() {
    if (_lastSnapshot) return _lastSnapshot;
    const r = await fetch('/api/snapshot');
    const snap = await r.json();
    _lastSnapshot = snap;
    return snap;
  }

  // Shared terminal input binder — reuses _soloTermExecute for BOTH the
  // Solo Mining Advisor (#solo-term-input) and the Live Mining terminal
  // (#terminal-input). History navigation + Enter submission in one place.
  function _termBindInput(inputEl, outputEl) {
    if (!inputEl) return;
    inputEl.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') {
        const cmd = inputEl.value.trim();
        if (cmd) {
          _soloTerm.history.push(cmd);
          _soloTerm.historyIdx = _soloTerm.history.length;
          _soloTermExecute(cmd, outputEl);
          inputEl.value = '';
        }
      } else if (e.key === 'ArrowUp') {
        e.preventDefault();
        if (_soloTerm.historyIdx > 0) {
          _soloTerm.historyIdx--;
          inputEl.value = _soloTerm.history[_soloTerm.historyIdx];
        }
      } else if (e.key === 'ArrowDown') {
        e.preventDefault();
        if (_soloTerm.historyIdx < _soloTerm.history.length - 1) {
          _soloTerm.historyIdx++;
          inputEl.value = _soloTerm.history[_soloTerm.historyIdx];
        } else {
          _soloTerm.historyIdx = _soloTerm.history.length;
          inputEl.value = '';
        }
      }
    });
  }

  // Terminal prompt user: the connected wallet address (short form) when
  // available, falling back to a neutral 'miner' for anonymous sessions.
  function _soloTermUser() {
    var addr = window.BTC_ADDRESS || '';
    if (addr) return fmt.shortAddr(addr);
    return 'miner';
  }

  async function _soloTermExecute(cmd, out) {
    if (_soloTerm.loading) return;
    _soloTerm.loading = true;
    out = out || _soloTerm.output;

    // Echo command — prompt shows the connected wallet, never a hardcoded user
    _soloTermPrintHTML('<span class="c-green">' + escapeHtml(_soloTermUser()) + '@cypher</span>:<span class="c-blue">~/solo-mining</span>$ <span class="c-white">' + escapeHtml(cmd) + '</span>', out);

    const parts = cmd.split(/\s+/);
    const verb = (parts[0] || '').toLowerCase();

    if (verb === 'clear' || verb === 'cls') {
      out.innerHTML = '';
      _soloTermPrintHTML('<span class="c-muted">terminal cleared</span>', out);
      _soloTerm.loading = false;
      return;
    }

    if (verb === 'help' || verb === '--help' || verb === '-h') {
      _soloTermPrint('', out);
      _soloTermPrintHTML('<span class="c-amber">Available commands:</span>', out);
      _soloTermPrint('  help ................. Show available commands', out);
      _soloTermPrint('  status ............... Show system status', out);
      _soloTermPrint('  workers .............. Show connected workers and hashrate', out);
      _soloTermPrint('  price ................ Show current BTC price', out);
      _soloTermPrint('  network .............. Show current Bitcoin network data', out);
      _soloTermPrint('', out);
      _soloTermPrint('  calc --hashrate <value> --duration <h> [--difficulty <d>]', out);
      _soloTermPrint('       Calculate solo mining probabilities for a given hashrate', out);
      _soloTermPrint('', out);
      _soloTermPrint('  compare --budget <btc> --duration <h> --braiins <price> --mrr <price>', out);
      _soloTermPrint('          Compare Braiins vs MRR rental options', out);
      _soloTermPrint('', out);
      _soloTermPrint('  clear ................ Clear terminal output', out);
      _soloTerm.loading = false;
      return;
    }

    // ── status: system/worker state from the live snapshot ──
    if (verb === 'status') {
      _soloTermPrintHTML('<span class="c-muted">fetching system status...</span>', out);
      try {
        const snap = await _soloTermCachedSnapshot();
        const w = snap.worker || {};
        const net = snap.network || {};
        const pool = snap.pool || {};
        _soloTermPrint('', out);
        _soloTermPrintHTML('<span class="c-green">[OK] CYPHER65 WAR ROOM — SYSTEM STATUS</span>', out);
        // The war room is ONLINE whenever the snapshot has been fetched.
        _soloTermPrint('  system............ ' + (snap && snap.ts > 0 ? 'ONLINE' : 'OFFLINE'), out);
        _soloTermPrint('  worker............ ' + (w.name || 'N/A'), out);
        _soloTermPrint('  hashrate.......... ' + (w.hashrate ? fmt.hashrate(w.hashrate) : 'N/A'), out);
        _soloTermPrint('  best diff......... ' + (w.bestDifficulty ? fmt.diff(w.bestDifficulty) : 'N/A'), out);
        _soloTermPrint('  network diff...... ' + (net.difficulty ? fmt.diff(net.difficulty) : 'N/A'), out);
        _soloTermPrint('  height............ ' + (net.height ? '#' + net.height : 'N/A'), out);
        _soloTermPrint('  pool hashrate..... ' + (pool.hashrate ? fmt.hashrate(pool.hashrate) : 'N/A'), out);
      } catch (e) {
        _soloTermPrintHTML('<span class="c-red">[ERROR] ' + escapeHtml(e.message) + '</span>', out);
      }
      _soloTerm.loading = false;
      return;
    }

    // ── workers: connected worker list + total hashrate ──
    if (verb === 'workers') {
      _soloTermPrintHTML('<span class="c-muted">fetching workers...</span>', out);
      try {
        const snap = await _soloTermCachedSnapshot();
        const workers = snap.all_workers || [];
        const w = snap.worker || {};
        _soloTermPrint('', out);
        _soloTermPrintHTML('<span class="c-green">[OK] workers: ' + workers.length + ' connected</span>', out);
        workers.slice(0, 10).forEach((wr, i) => {
          const hr = wr.hashrate || wr.hashrate1m || 0;
          _soloTermPrint('  #' + (i+1) + ' ' + (wr.name || wr.worker || 'unknown') + ' .... HR ' + (hr ? fmt.hashrate(hr) : 'N/A'), out);
        });
        if (!workers.length) _soloTermPrint('  (no worker data yet)', out);
        _soloTermPrint('', out);
        _soloTermPrint('  total HR.......... ' + (w.hashrate ? fmt.hashrate(w.hashrate) : 'N/A'), out);
      } catch (e) {
        _soloTermPrintHTML('<span class="c-red">[ERROR] ' + escapeHtml(e.message) + '</span>', out);
      }
      _soloTerm.loading = false;
      return;
    }

    // ── price: current BTC price ──
    if (verb === 'price') {
      _soloTermPrintHTML('<span class="c-muted">fetching BTC price...</span>', out);
      try {
        const snap = await _soloTermCachedSnapshot();
        const btc = snap.btc_price || {};
        _soloTermPrint('', out);
        _soloTermPrintHTML('<span class="c-green">[OK] BTC price</span>', out);
        _soloTermPrint('  BTC/USD........... ' + (btc.usd ? '$' + Number(btc.usd).toLocaleString() : 'N/A'), out);
        _soloTermPrint('  BTC/BRL........... ' + (btc.brl ? 'R$' + Number(btc.brl).toLocaleString() : 'N/A'), out);
      } catch (e) {
        _soloTermPrintHTML('<span class="c-red">[ERROR] ' + escapeHtml(e.message) + '</span>', out);
      }
      _soloTerm.loading = false;
      return;
    }

    if (verb === 'network') {
      _soloTermPrintHTML('<span class="c-muted">fetching network data...</span>', out);
      try {
        const r = await fetch('/api/solo-mining/network');
        const data = await r.json();
        if (data.error) {
          _soloTermPrintHTML('<span class="c-red">[ERROR] ' + escapeHtml(data.error) + '</span>', out);
          _soloTerm.loading = false;
          return;
        }
        _soloTermPrint('', out);
        _soloTermPrintHTML('<span class="c-green">[OK] Network data fetched</span>', out);
        _soloTermPrint('  difficulty........ ' + (data.difficulty ? fmt.diff(data.difficulty) : 'UNAVAILABLE'), out);
        _soloTermPrint('  btc/usd........... ' + (data.btc_price_usd ? '$' + Number(data.btc_price_usd).toLocaleString() : 'UNAVAILABLE'), out);
        _soloTermPrint('  height............ ' + (data.height ? '#' + data.height : 'UNAVAILABLE'), out);
        _soloTermPrint('  source............ ' + (data.source || 'mempool.space'), out);
      } catch (e) {
        _soloTermPrintHTML('<span class="c-red">[ERROR] Failed to fetch network data: ' + escapeHtml(e.message) + '</span>', out);
      }
      _soloTerm.loading = false;
      return;
    }

    if (verb === 'calc') {
      let hashrate = null, duration = null, difficulty = null;
      for (let i = 1; i < parts.length; i++) {
        if (parts[i] === '--hashrate' && parts[i+1]) { hashrate = parts[i+1]; i++; }
        else if (parts[i] === '--duration' && parts[i+1]) { duration = parts[i+1].replace(/[^0-9.]/g, ''); i++; }
        else if (parts[i] === '--difficulty' && parts[i+1]) { difficulty = parts[i+1]; i++; }
      }
      if (!hashrate || !duration) {
        _soloTermPrintHTML('<span class="c-red">[ERROR] Missing required flags. Usage: calc --hashrate <value> --duration <h></span>', out);
        _soloTerm.loading = false;
        return;
      }
      const params = new URLSearchParams({ hashrate: hashrate, duration: duration, user: _soloTermUser() });
      if (difficulty) params.set('difficulty', difficulty);
      _soloTermPrintHTML('<span class="c-muted">running calculations...</span>', out);
      try {
        const r = await fetch('/api/solo-mining/calc?' + params.toString());
        const data = await r.json();
        if (data.error) {
          _soloTermPrintHTML('<span class="c-red">[ERROR] ' + escapeHtml(data.error) + '</span>', out);
          _soloTerm.loading = false;
          return;
        }
        _soloTermPrint('', out);
        const output = data.terminal_output || data.output || '';
        const lines = output.split('\n');
        for (const line of lines) {
          if (line.startsWith('[OK]')) _soloTermPrintHTML('<span class="c-green">' + escapeHtml(line) + '</span>', out);
          else if (line.startsWith('[WARN]')) _soloTermPrintHTML('<span class="c-amber">' + escapeHtml(line) + '</span>', out);
          else if (line.startsWith('[ERROR]')) _soloTermPrintHTML('<span class="c-red">' + escapeHtml(line) + '</span>', out);
          else _soloTermPrint(line, out);
        }
      } catch (e) {
        _soloTermPrintHTML('<span class="c-red">[ERROR] ' + escapeHtml(e.message) + '</span>', out);
      }
      _soloTerm.loading = false;
      return;
    }

    if (verb === 'compare') {
      let budget = null, duration = null, braiins = null, mrr = null, objective = 'EV';
      for (let i = 1; i < parts.length; i++) {
        if (parts[i] === '--budget' && parts[i+1]) { budget = parts[i+1]; i++; }
        else if (parts[i] === '--duration' && parts[i+1]) { duration = parts[i+1].replace(/[^0-9.]/g, ''); i++; }
        else if (parts[i] === '--braiins' && parts[i+1]) { braiins = parts[i+1]; i++; }
        else if (parts[i] === '--mrr' && parts[i+1]) { mrr = parts[i+1]; i++; }
        else if (parts[i] === '--objective' && parts[i+1]) { objective = parts[i+1].toUpperCase(); i++; }
      }
      if (!budget || !duration) {
        _soloTermPrintHTML('<span class="c-red">[ERROR] Missing required flags. Usage: compare --budget <btc> --duration <h> [--braiins <price>] [--mrr <price>]</span>', out);
        _soloTerm.loading = false;
        return;
      }
      const params = new URLSearchParams({ budget: budget, duration: duration, objective, auto_fetch: '1', user: _soloTermUser() });
      if (braiins) params.set('braiins_price', braiins);
      if (mrr) params.set('mrr_price', mrr);
      _soloTermPrintHTML('<span class="c-muted">comparing rental options...</span>', out);
      try {
        const r = await fetch('/api/solo-mining/compare?' + params.toString());
        const data = await r.json();
        if (data.error) {
          _soloTermPrintHTML('<span class="c-red">[ERROR] ' + escapeHtml(data.error) + '</span>', out);
          _soloTerm.loading = false;
          return;
        }
        _soloTermPrint('', out);
        const output = data.terminal_output || data.output || '';
        const lines = output.split('\n');
        for (const line of lines) {
          if (line.startsWith('[OK]')) _soloTermPrintHTML('<span class="c-green">' + escapeHtml(line) + '</span>', out);
          else if (line.startsWith('[WARN]')) _soloTermPrintHTML('<span class="c-amber">' + escapeHtml(line) + '</span>', out);
          else if (line.startsWith('[ERROR]')) _soloTermPrintHTML('<span class="c-red">' + escapeHtml(line) + '</span>', out);
          else _soloTermPrint(line, out);
        }
      } catch (e) {
        _soloTermPrintHTML('<span class="c-red">[ERROR] ' + escapeHtml(e.message) + '</span>', out);
      }
      _soloTerm.loading = false;
      return;
    }

    _soloTermPrintHTML('<span class="c-red">[ERROR] Unknown command: ' + escapeHtml(verb) + '. Type help for available commands.</span>', out);
    _soloTerm.loading = false;
  }

  function _soloTermInit() {
    _soloTerm.output = document.getElementById('solo-term-output');
    _soloTerm.input = document.getElementById('solo-term-input');
    if (!_soloTerm.input) return;

    _termBindInput(_soloTerm.input, _soloTerm.output);

    // Keep focus on input when clicking anywhere in the terminal
    const term = document.getElementById('solo-term');
    if (term) {
      term.addEventListener('click', () => _soloTerm.input && _soloTerm.input.focus());
    }

    // Clear button
    document.getElementById('solo-term-clear')?.addEventListener('click', () => {
      if (_soloTerm.output) _soloTerm.output.innerHTML = '';
      _soloTermPrintHTML('<span class="c-muted">terminal cleared — type help for commands</span>', _soloTerm.output);
    });

    // Help button
    document.getElementById('solo-term-help')?.addEventListener('click', () => {
      _soloTermExecute('help', _soloTerm.output);
    });

    // Welcome message
    _soloTermPrintHTML('<span class="c-muted">CYPHER SOLO MINING ADVISOR v1.0</span>', _soloTerm.output);
    _soloTermPrintHTML('<span class="c-muted">Type </span><span class="c-green">help</span><span class="c-muted"> for available commands.</span>', _soloTerm.output);
    _soloTermPrintHTML('<span class="c-muted">Examples:</span>', _soloTerm.output);
    _soloTermPrintHTML('<span class="c-muted">  calc --hashrate 225TH --duration 24h</span>', _soloTerm.output);
    _soloTermPrintHTML('<span class="c-muted">  compare --budget 0.01 --duration 24 --braiins 0.002 --mrr 0.0015</span>', _soloTerm.output);
    _soloTermPrintHTML('<span class="c-muted">  network</span>', _soloTerm.output);
    _soloTermPrint('', _soloTerm.output);

    // Focus input
    _soloTerm.input.focus();
  }

  // ── LIVE MINING TERMINAL (#terminal-input) ──────────────────────────
  // Binds the Live Terminal pane to the SAME command engine used by the
  // Solo Mining Advisor (_soloTermExecute). Previously #terminal-input had
  // no Enter keydown handler — only a .focus() call — so the E2E terminal
  // tests could never submit commands. Now help/status/workers/price/clear
  // all work from the Live Mining terminal. (Fase 5 · terminal unification)
  function _liveTermInit() {
    const output = document.getElementById('terminal-body');
    const input = document.getElementById('terminal-input');
    if (!input || !output) return;

    _termBindInput(input, output);

    // Keep focus on input when clicking anywhere in the terminal pane
    const panel = document.getElementById('terminal-panel');
    if (panel) {
      panel.addEventListener('click', () => input.focus());
    }

    // Clear button
    document.getElementById('terminal-clear')?.addEventListener('click', () => {
      output.innerHTML = '';
      _soloTermPrintHTML('<span class="c-muted">terminal cleared</span>', output);
    });

    // Welcome message
    _soloTermPrintHTML('<span class="c-muted">CYPHER65 WAR ROOM TERMINAL — type </span><span class="c-green">help</span><span class="c-muted"> for available commands.</span>', output);
  }

// ══════════════════════════════════════════════════════════════════════
  // POLLING
  // ══════════════════════════════════════════════════════════════════════



  function updateNextPoll() {
    nextPollAt = Date.now() + POLL_MS;
    if (dom.nextPoll) dom.nextPoll.textContent = `${Math.ceil(POLL_MS/1000)}s`;
  }

  // ── Clock ──
  function updateClock() {
    if (dom.clock) dom.clock.textContent = new Date().toLocaleTimeString();
  }

  // ── Snapshot fetch dedup ──
  // Guards against concurrent /api/snapshot fetches (e.g. rapid market-module
  // activations each firing fetchSnapshot) so render() never runs twice in
  // parallel with two different snapshots. The poll loop and manual refreshes
  // both go through fetchSnapshot, so this keeps a single in-flight fetch.
  let _snapshotFetching = false;
  async function fetchSnapshot() {
    if (_snapshotFetching) return;
    _snapshotFetching = true;
    try {
      const r = await fetch('/api/snapshot');
      if (!r.ok) throw new Error('snapshot failed');
      const snap = await r.json();
      _lastSnapshot = snap;
      render(snap);
      fetchAxeFleet();
      updateNextPoll();
    } catch (e) { logMessage('ERROR', e.message, 'WARN'); }
    finally { _snapshotFetching = false; }
  }

  // ── Boot ──
  async function boot() {
    initMatrix(); initCharts(); bindChartRanges(); loadSettings(); initMarketControls();
    fetchTailscale();
    if (typeof fetchRemoteOnboarding === 'function') fetchRemoteOnboarding();
    updateClock(); setInterval(updateClock, 1000);
    // ── Service Worker: unregister old caches, force fresh install ──
    if ('serviceWorker' in navigator) {
      navigator.serviceWorker.getRegistrations().then(registrations => {
        for (const reg of registrations) {
          reg.unregister();
          console.log('[boot] unregistered old SW:', reg.scope);
        }
        // Register fresh with cache bust
        navigator.serviceWorker.register('/sw.js', { scope: '/' }).then(() => {
          console.log('[boot] new SW registered');
        }).catch(e => {
          console.warn('[boot] SW registration failed:', e);
        });
      });
      // Listen for updates and reload when a new SW takes over
      navigator.serviceWorker.addEventListener('controllerchange', () => {
        console.log('[boot] new SW activated — reloading');
        window.location.reload();
      });
    }

    showSkeletons();
    _huntStart();
    initAxeFleetControls();
    initAuth();
    initThemeToggle();
    _liveTermInit();
    await fetchSnapshot();
    setInterval(fetchSnapshot, POLL_MS);
    // ── SSE live stream ── subscribe to push updates at ~3s intervals
    // Fallback: if EventSource fails, the regular 15s poll still works.
    try {
      if (typeof EventSource !== 'undefined') {
        var es = new EventSource('/api/stream');
        var sseRetries = 0;
        var sseLastErrorTs = 0;
        var sseLastFleetFetch = 0;
        es.onmessage = function(e) {
          try {
            var snap = JSON.parse(e.data);
            if (snap && snap.ts) {
              _lastSnapshot = snap;
              render(snap);
              // Debounce fleet fetch to avoid 5x request rate
              var now = Date.now();
              if (now - sseLastFleetFetch > 10000) {
                sseLastFleetFetch = now;
                fetchAxeFleet();
              }
            }
          } catch(err) { /* ignore parse errors */ }
        };
        es.onerror = function() {
          var now = Date.now();
          // Debounce: ignore errors within 2s (EventSource auto-reconnects)
          if (now - sseLastErrorTs < 2000) return;
          sseLastErrorTs = now;
          sseRetries++;
          if (sseRetries > 5) {
            // After 5 distinct error events (>=2s apart), close SSE and rely on polling
            es.close();
            logMessage('SSE', 'Live stream disconnected — falling back to polling', 'WARN');
          }
        };
      }
    } catch(e) { /* SSE not supported */ }

    logMessage('SYSTEM', 'WAR ROOM ONLINE', 'SUCCESS');
  }

  boot();

  // ═════════════════════════════════════════════════════════════════════
  // ALERT CENTER (Milestone 9)
  // ══════════════════════════════════════════════════════════════════════
  let acState = { active: [], history: [], rules: [] };
  const severityClass = { CRIT: 'severity--crit', WARN: 'severity--warn', INFO: 'severity--info', GOLD: 'severity--gold', SUCCESS: 'severity--success' };
  const severityLabel = { CRIT: 'CRIT', WARN: 'WARN', INFO: 'INFO', GOLD: 'GOLD', SUCCESS: 'OK' };

  function acSetStatus(msg, isErr) {
    if (!dom.alertCenterStatus) return;
    dom.alertCenterStatus.textContent = msg;
    dom.alertCenterStatus.className = 'modal__status' + (isErr ? ' modal__status--error' : '');
    setTimeout(() => { dom.alertCenterStatus.textContent = ''; }, 3000);
  }

  function acFormatTime(ts) {
    if (!ts) return '—';
    const d = new Date(ts * 1000);
    return d.toLocaleString();
  }

  async function acFetchJson(url, opts) {
    const res = await fetch(url, opts);
    if (!res.ok) {
      let msg;
      try { msg = (await res.json()).error; } catch (_) { /* ignore */ }
      throw new Error(msg || res.statusText || ('HTTP ' + res.status));
    }
    return res.json();
  }

  function acRenderActive() {
    if (!dom.acActiveList) return;
    const filter = (document.querySelector('.ac-filter.active')?.dataset.filter) || 'all';
    const list = acState.active.filter(a => filter === 'all' || a.severity === filter);
    if (!list.length) {
      dom.acActiveList.innerHTML = '<div class="ac-empty">no active alerts</div>';
      return;
    }
    dom.acActiveList.innerHTML = list.map(a => `
      <div class="ac-item ac-item--${(a.severity || 'INFO').toLowerCase()}">
        <div class="ac-item__meta">
          <span class="ac-item__sev ${severityClass[a.severity] || ''}">${severityLabel[a.severity] || a.severity}</span>
          <span class="ac-item__cat">${a.category}</span>
          <span class="ac-item__ts">${acFormatTime(a.ts)}</span>
        </div>
        <div class="ac-item__msg">${a.message}</div>
        <div class="ac-item__actions">
          <button class="btn btn--mini ac-ack" data-id="${a.id}">Acknowledge</button>
        </div>
      </div>
    `).join('');
    dom.acActiveList.querySelectorAll('.ac-ack').forEach(btn => {
      btn.addEventListener('click', async () => {
        try {
          await acFetchJson('/api/alerts/acknowledge', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ id: parseInt(btn.dataset.id, 10) }),
          });
          acLoadActive();
        } catch (e) { acSetStatus('Acknowledge failed: ' + e.message, true); }
      });
    });
  }

  function acRenderHistory() {
    if (!dom.acHistoryList) return;
    if (!acState.history.length) {
      dom.acHistoryList.innerHTML = '<div class="ac-empty">no history entries</div>';
      return;
    }
    dom.acHistoryList.innerHTML = acState.history.map(h => `
      <div class="ac-item ac-item--history">
        <div class="ac-item__meta">
          <span class="ac-item__sev ${severityClass[h.severity] || ''}">${severityLabel[h.severity] || h.severity}</span>
          <span class="ac-item__cat">${h.alert_type}</span>
          <span class="ac-item__ts">${acFormatTime(h.ts)}</span>
        </div>
        <div class="ac-item__msg">${h.action_taken || h.message}</div>
      </div>
    `).join('');
  }

  function acRenderRules() {
    if (!dom.acRulesList) return;
    if (!acState.rules.length) {
      dom.acRulesList.innerHTML = '<div class="ac-empty">no automation rules</div>';
      return;
    }
    dom.acRulesList.innerHTML = acState.rules.map(r => `
      <div class="ac-item ac-item--rule">
        <div class="ac-item__meta">
          <span class="ac-item__sev">${r.is_enabled ? 'ON' : 'OFF'}</span>
          <span class="ac-item__cat">${r.name}</span>
        </div>
        <div class="ac-item__msg">WHEN ${r.condition_metric} ${r.condition_operator} ${r.condition_value} THEN ${r.action_command}</div>
        <div class="ac-item__actions">
          <button class="btn btn--danger btn--mini ac-rule-del" data-id="${r.id}">Delete</button>
        </div>
      </div>
    `).join('');
    dom.acRulesList.querySelectorAll('.ac-rule-del').forEach(btn => {
      btn.addEventListener('click', async () => {
        try {
          await acFetchJson('/api/automation-rules/' + btn.dataset.id, { method: 'DELETE' });
          acLoadRules();
        } catch (e) { acSetStatus('Delete failed: ' + e.message, true); }
      });
    });
  }

  async function acLoadActive() {
    try {
      acState.active = (await acFetchJson('/api/alerts?limit=100')).alerts || [];
      acRenderActive();
    } catch (e) { acSetStatus('Load alerts failed: ' + e.message, true); }
  }

  async function acLoadHistory() {
    try {
      acState.history = (await acFetchJson('/api/alerts/history?limit=100')).history || [];
      acRenderHistory();
    } catch (e) { acSetStatus('Load history failed: ' + e.message, true); }
  }

  async function acLoadRules() {
    try {
      acState.rules = (await acFetchJson('/api/automation-rules')).rules || [];
      acRenderRules();
    } catch (e) { acSetStatus('Load rules failed: ' + e.message, true); }
  }

  function acShowTab(tab) {
    dom.acTabs.forEach(t => t.classList.toggle('active', t.dataset.tab === tab));
    dom.acPanes.forEach(p => p.style.display = (p.id === 'ac-pane-' + tab ? '' : 'none'));
    if (tab === 'active') acLoadActive();
    if (tab === 'history') acLoadHistory();
    if (tab === 'rules') acLoadRules();
  }

  if (dom.openAlertCenter) {
    dom.openAlertCenter.addEventListener('click', () => {
      dom.alertCenterModal.classList.add('modal--open');
      acShowTab('active');
    });
    dom.alertCenterModal?.querySelectorAll('[data-close]').forEach(el => {
      el.addEventListener('click', () => dom.alertCenterModal.classList.remove('modal--open'));
    });
    dom.acTabs.forEach(t => t.addEventListener('click', () => acShowTab(t.dataset.tab)));
    dom.acFilters.forEach(f => f.addEventListener('click', () => {
      dom.acFilters.forEach(x => x.classList.remove('active'));
      f.classList.add('active');
      acRenderActive();
    }));
    dom.acRefreshActive?.addEventListener('click', acLoadActive);
    dom.acRefreshHistory?.addEventListener('click', acLoadHistory);
    dom.acRefreshRules?.addEventListener('click', acLoadRules);
    dom.acAddRule?.addEventListener('click', () => { dom.acRuleForm.style.display = ''; });
    dom.acRuleCancel?.addEventListener('click', () => { dom.acRuleForm.style.display = 'none'; });
    dom.acRuleSave?.addEventListener('click', async () => {
      const payload = {
        name: dom.acRuleName.value.trim() || 'rule',
        target_device_id: dom.acRuleDevice.value.trim(),
        condition_metric: dom.acRuleMetric.value,
        condition_operator: dom.acRuleOp.value,
        condition_value: parseFloat(dom.acRuleValue.value),
        action_command: dom.acRuleAction.value.trim(),
        action_parameters: {},
        is_enabled: true,
      };
      if (!payload.target_device_id || isNaN(payload.condition_value) || !payload.action_command) {
        acSetStatus('Please fill all fields', true); return;
      }
      try {
        await acFetchJson('/api/automation-rules', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        });
        dom.acRuleForm.style.display = 'none';
        dom.acRuleName.value = ''; dom.acRuleDevice.value = ''; dom.acRuleValue.value = ''; dom.acRuleAction.value = '';
        acLoadRules();
      } catch (e) { acSetStatus('Save rule failed: ' + e.message, true); }
    });
  }

  // ── Sidebar toggle (desktop collapse + mobile open/close) ──
  const sidebar = document.getElementById('sidebar');
  const sidebarBackdrop = document.getElementById('sidebar-backdrop');
  const sidebarOverlay = document.getElementById('sidebar-overlay');
  const sidebarToggle = document.getElementById('sidebar-toggle');
  const sidebarMobileToggle = document.getElementById('sidebar-mobile-toggle');
  const sidebarLinks = document.querySelectorAll('.sidebar__link');

  // MODULE_MAP — módulo → título/descrição do header
  const MODULE_MAP = {
    'dashboard':   { title: 'DASHBOARD',     desc: 'Visão geral — pool, worker e rede' },
    'wallet':      { title: 'WALLET',        desc: 'Conexão e status da wallet' },
    'fleet':       { title: 'FLEET',         desc: 'Visão dos miners' },
    'live':        { title: 'LIVE MINING',   desc: 'Dados ao vivo' },
    'probability': { title: 'PROBABILITY',   desc: 'Chance e probabilidade' },
    'market':      { title: 'HASH MARKET',   desc: 'Mercado e cotações' },
    'alerts':      { title: 'ALERTS',        desc: 'Alertas e eventos' },
    'automations': { title: 'AUTOMATIONS',   desc: 'Regras e automação' },
    'docs':        { title: 'DOCS / GUIDE',  desc: 'Manual de uso' },
    'learning':    { title: 'LEARNING',      desc: 'Bitcoin Academy — whitepaper, livros e Ordinals' },
    'support':     { title: 'SUPPORT',       desc: 'Doação e apoio' },
  };

  function openSidebar() {
    sidebar.classList.add('open');
    if (sidebarBackdrop) sidebarBackdrop.classList.add('visible');
    if (sidebarOverlay) sidebarOverlay.classList.add('visible');
  }
  function closeSidebar() {
    sidebar.classList.remove('open');
    if (sidebarBackdrop) sidebarBackdrop.classList.remove('visible');
    if (sidebarOverlay) sidebarOverlay.classList.remove('visible');
  }
  function toggleSidebar() {
    sidebar.classList.contains('open') ? closeSidebar() : openSidebar();
  }

  if (sidebarToggle) {
    sidebarToggle.addEventListener('click', () => {
      // Em viewport mobile, o ☰ do topbar ABRE a sidebar (não colapsa)
      if (window.innerWidth <= 1100) { toggleSidebar(); return; }
      // CSS usa .sidebar.collapsed (compatível com o media query mobile)
      sidebar.classList.toggle('collapsed');
      sidebarToggle.textContent = sidebar.classList.contains('collapsed') ? '▶' : '◀';
    });
  }

  if (sidebarMobileToggle) sidebarMobileToggle.addEventListener('click', toggleSidebar);
  if (sidebarBackdrop) sidebarBackdrop.addEventListener('click', closeSidebar);
  if (sidebarOverlay) sidebarOverlay.addEventListener('click', closeSidebar);

  // ── MODULE SYSTEM: mostra só os painéis do módulo ativo ──
  function activateModule(name) {
    document.body.classList.add('module-mode');
    // Mostra/esconde cada painel com data-module — MAS nunca os links da
    // sidebar (eles também têm data-module; escondê-los quebraria a navegação)
    document.querySelectorAll('[data-module]').forEach(function(el) {
      // Links da sidebar nunca são escondidos (senão a navegação quebra)
      if (el.classList.contains('sidebar__link')) return;
      const mods = (el.getAttribute('data-module') || '').split(/\s+/);
      const show = mods.indexOf(name) !== -1;
      el.classList.toggle('module-hidden', !show);
    });
    // Tab panes só ficam visíveis se contiverem painel visível
    document.querySelectorAll('.tab-pane').forEach(function(pane) {
      const hasVisible = pane.querySelector('[data-module]:not(.module-hidden)');
      pane.classList.toggle('active', !!hasVisible);
    });
    // Sidebar active state
    sidebarLinks.forEach(function(l) {
      l.classList.toggle('active', l.getAttribute('data-module') === name);
    });
    // Module header
    const info = MODULE_MAP[name] || {};
    const mhTitle = document.getElementById('module-header-title');
    const mhDesc = document.getElementById('module-header-desc');
    if (mhTitle) mhTitle.textContent = info.title || name.toUpperCase();
    if (mhDesc) mhDesc.textContent = info.desc || '';
    // Persist
    try { localStorage.setItem('_active_module', name); } catch(e) {}
    closeSidebar();
    // Depois que a visibilidade estabiliza: resize dos charts já criados
    // E cria/atualiza charts dos canvases que acabaram de ficar visíveis
    // (renderCharts pula canvases ocultos, então é seguro chamá-lo aqui)
    requestAnimationFrame(function() {
      Object.keys(charts).forEach(function(id) {
        const ch = charts[id];
        if (ch && typeof ch.resize === 'function') ch.resize();
      });
      if (typeof renderCharts === 'function') renderCharts();
      // Hash Market: lazy-load the 7d trend chart on first module activation.
      // On failure the flag is reset so the next activation retries.
      if (name === 'market' && !_mktTrendLoaded) {
        _mktTrendLoaded = true;
        loadMarketTrend().then(ok => { if (!ok) _mktTrendLoaded = false; });
      }
      // Hash Market: also refresh the snapshot — the boot-time snapshot can be
      // stale (fetched before the warmup cache is hot), so the grid would open
      // with 0 offers until the next 15s poll. Same pattern as the fleet fix.
      if (name === 'market' && typeof fetchSnapshot === 'function') {
        fetchSnapshot();
      }
      // Live Mining / Terminal: foca o input para digitação imediata
      if (name === 'live') {
        const termInput = document.getElementById('terminal-input');
        if (termInput) termInput.focus();
      }
      // Fleet: garante que o grid renderize imediatamente ao ativar a aba.
      // Antes o fetchAxeFleet() só rodava no poll/SSE, então a aba abria
      // com o empty-state estático mesmo com devices registrados.
      if (name === 'fleet' && typeof fetchAxeFleet === 'function') {
        if (typeof fetchRemoteOnboarding === 'function') fetchRemoteOnboarding();
        fetchAxeFleet();
      }
      // Support: abre o modal completo (manifesto + endereços) em vez de só
      // rolar até a barra compacta — o texto autoral e os endereços grandes
      // ficam no modal.
      if (name === 'support') {
        const panel = document.getElementById('support-panel');
        if (panel) {
          panel.classList.add('modal--open');
          renderSupportMethods();  // also fills the LN recipient row
        }
      }
    });
  }

  sidebarLinks.forEach(function(link) {
    link.addEventListener('click', function() {
      const name = link.getAttribute('data-module');
      if (name) activateModule(name);
    });
  });

  // Restore active module from localStorage on boot
  (function restoreActiveModule() {
    try {
      const saved = localStorage.getItem('_active_module');
      activateModule(saved && MODULE_MAP[saved] ? saved : 'dashboard');
    } catch(e) { activateModule('dashboard'); }
  })();

  // Close sidebar on Escape key
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && sidebar.classList.contains('open')) closeSidebar();
  });

  // Update sidebar status (called from render)
  function updateSidebarStatus(isOnline) {
    const led = document.getElementById('sidebar-led');
    const text = document.getElementById('sidebar-status-text');
    if (led) led.style.background = isOnline ? 'var(--accent-green)' : 'var(--accent-red)';
    if (text) text.textContent = isOnline ? 'ONLINE' : 'OFFLINE';
  }


  // ── HOTFIX: Immediate fetch on wallet connect ──
  window.addEventListener('wallet-changed', function(e) {
    var addr = e.detail && e.detail.address;
    if (addr) {
      // Force immediate snapshot refresh — render ALL panels, not just Raio X
      fetch('/api/snapshot')
        .then(function(r) { return r.json(); })
        .then(function(snap) {
          render(snap);
        })
        .catch(function(err) { console.warn('[wallet-changed] fetch error:', err); });
    }
  });
  // The IIFE continues below — do NOT close it here!

  // ── FASE 3: Clipboard copy for donation footer ──
  document.addEventListener('click', function(e) {
    var btn = e.target.closest('[data-copy-btn]');
    if (btn) {
      var code = btn.previousElementSibling;
      var addr = code ? code.getAttribute('data-copy') || code.textContent : '';
      if (addr && navigator.clipboard) {
        navigator.clipboard.writeText(addr).then(function() {
          var orig = btn.textContent;
          btn.textContent = '[copied]';
          setTimeout(function() { btn.textContent = orig; }, 2000);
        });
      }
    }
  });

  // ════════════════════════════════════════════════════════════════════════
  // INSTITUTIONAL DASHBOARD · UI CONTROLLER
  // ════════════════════════════════════════════════════════════════════════
  const InstitutionalUI = {
    init: function() {
      this.bindTabs();
      this.bindAIOperator();
    },
    bindTabs: function() {
      var tabBtns = document.querySelectorAll('.tab-btn');
      var tabPanes = document.querySelectorAll('.tab-pane');
      if (!tabBtns.length) return;
      tabBtns.forEach(function(btn) {
        btn.addEventListener('click', function(e) {
          var targetId = e.currentTarget.getAttribute('data-target');
          var targetPane = document.getElementById(targetId);
          if (!targetPane) return;
          tabBtns.forEach(function(b) { b.classList.remove('active'); });
          tabPanes.forEach(function(p) { p.classList.remove('active'); });
          e.currentTarget.classList.add('active');
          targetPane.classList.add('active');
          // When Deep Analytics tab is clicked, resize charts
          // (canvases have display:none; Chart.js can't measure them)
          // requestAnimationFrame ensures browser computed layout after display:block
          if (targetId === 'tab-charts' && typeof charts !== 'undefined') {
            requestAnimationFrame(function() {
              Object.values(charts).forEach(function(ch) {
                if (ch && typeof ch.resize === 'function') ch.resize();
              });
            });
          }
        });
      });
    },
    bindAIOperator: function() {
      var aiToggleBtn = document.getElementById('sidebar-toggle');
      var aiPanel = document.getElementById('ai-operator-panel');
      if (!aiToggleBtn || !aiPanel) return;
      aiToggleBtn.addEventListener('click', function(e) {
        e.stopPropagation();
        aiPanel.classList.toggle('active');
      });
      document.addEventListener('click', function(e) {
        if (aiPanel.classList.contains('active') && !aiPanel.contains(e.target) && !aiToggleBtn.contains(e.target)) {
          aiPanel.classList.remove('active');
        }
      });
    }
  };

  // ── Initialize Institutional UI after DOM ready ──
  if (document.readyState !== 'loading') {
    InstitutionalUI.init();
  } else {
    document.addEventListener('DOMContentLoaded', function() { InstitutionalUI.init(); });
  }

  // ════════════════════════════════════════════════════════════════════════
  // INSTITUTIONAL DASHBOARD · CORE DATA BINDER
  // ════════════════════════════════════════════════════════════════════════
  var DashboardCore = {
    renderSnapshot: function(snap) {
      if (!snap) return;
      this.updateTopbar(snap.network, snap.mempool_fees, snap.btc_price, snap.alerts_recent);
      this.updateCommandCenter(snap.worker, snap.axe_fleet, snap.pool, snap.profitability);
      this.updateRadar(snap.proximity, snap.worker);
      this.updateDataGrids(snap.all_workers, snap.axe_fleet, snap.account, snap.leaderboard_table_top_30);
      this.setSystemStatus('online');
    },
    setText: function(id, text) {
      var el = document.getElementById(id);
      if (el) el.textContent = text || '\u2014';
    },
    setSystemStatus: function(status) {
      var pill = document.getElementById('status-pill');
      if (pill) { pill.className = 'status-indicator ' + status; }
    },
    formatHashrate: function(hs) {
      if (!hs) return '0 H/s';
      if (hs > 1e18) return (hs / 1e18).toFixed(2) + ' EH/s';
      if (hs > 1e15) return (hs / 1e15).toFixed(2) + ' PH/s';
      if (hs > 1e12) return (hs / 1e12).toFixed(2) + ' TH/s';
      if (hs > 1e9) return (hs / 1e9).toFixed(2) + ' GH/s';
      return Number(hs).toLocaleString() + ' H/s';
    },
    updateTopbar: function(net, fees, btc, alerts) {
      var btcPrice = btc && btc.usd ? '$' + Number(btc.usd).toLocaleString() : '--';
      this.setText('n-btc-usd', btcPrice);
      this.setText('n-diff', net ? this.formatHashrate(net.difficulty) : '--');
      this.setText('n-hashrate', net ? this.formatHashrate(net.hashrate) : '--');
      this.setText('n-height', net && net.height ? '#' + net.height : '--');
      this.setText('fee-fastest', fees && fees.fastestFee != null ? fees.fastestFee + ' sat/vB' : '--');
      var alertBadge = document.getElementById('alerts-count-badge');
      if (alertBadge && alerts) {
        alertBadge.textContent = alerts.length;
        alertBadge.style.display = alerts.length > 0 ? 'inline-block' : 'none';
      }
    },
    updateCommandCenter: function(worker, fleet, pool, profit) {
      var hrStr = worker ? this.formatHashrate(worker.hashrate) : '0 H/s';
      this.setText('hero-worker', hrStr);
      // p-hashrate, p-workers handled by renderPool() — do not duplicate
      this.setText('p-high-diff', pool ? String(pool.highestDifficulty || '--') : '--');
      this.setText('hc-network', pool ? String(pool.hashrate || '--') : '--');
      if (profit) {
        this.setText('p-btc-day', profit.net_btc_per_day_pool != null ? profit.net_btc_per_day_pool.toFixed(6) + ' BTC' : '--');
        var fiatDay = profit.fiat_per_day_pool ? profit.fiat_per_day_pool.USD : null;
        this.setText('p-fiat-day', fiatDay != null ? '$' + Number(fiatDay).toLocaleString(undefined, {maximumFractionDigits: 0}) : '--');
      }
    },
    updateRadar: function(prox, worker) {
      if (prox) {
        this.setText('prox-hero-pct', prox.pct_of_network_cur != null ? prox.pct_of_network_cur.toFixed(4) + '%' : '--');
        this.setText('prox-chance', prox.chance_per_share_label || '--');
        this.setText('prox-time', prox.expected_time_human || '--');
        this.setText('bh-distance', prox.distance_label || '--');
        this.setText('bh-p-block', prox.chance_per_share_pct != null ? (Number(prox.chance_per_share_pct) * 100).toFixed(6) + '%' : '--');
      }
      this.setText('prox-hero-best', prox && prox.all_time_best_diff_str ? 'best ' + prox.all_time_best_diff_str : '--');
      this.setText('hunt-metrics-bestdiff', worker && worker.bestDifficulty ? String(worker.bestDifficulty) : '--');
    },
    updateDataGrids: function(workers, fleet, account, leaderboard) {
    // raio-x grid is rendered by renderMinersXRay() — do not overwrite
      // (handled by renderAccount)
      this.setText('acct-ln', account ? (account.ln_address || '--') : '--');
      this.setText('acct-total-diff', account && account.total_diff ? this.formatHashrate(account.total_diff) : '--');
      this.setText('acct-diff-rank', account && account.diff_rank != null ? String(account.diff_rank) : '--');
      this.setText('acct-loyalty-rank', account && account.loyalty_rank != null ? String(account.loyalty_rank) : '--');

      var lbBody = document.getElementById('lb-tbody');
      if (lbBody && leaderboard && leaderboard.length) {
        lbBody.innerHTML = leaderboard.slice(0, 10).map(function(row, i) {
          return '<tr><td>' + (i + 1) + '</td><td>' + (row.address ? row.address.substring(0, 10) + '...' : '--') + '</td><td>' + (row.diff_rank || '--') + '</td><td>' + (row.loyalty_rank || '--') + '</td><td>' + (row.combined_score || '--') + '</td><td>' + (row.total_blocks || 0) + '</td></tr>';
        }).join('');
      }
    }
  };

  // ── Extend existing InstitutionalUI to also handle off-canvas AI panel ──
  if (typeof InstitutionalUI !== 'undefined' && InstitutionalUI) {
    var _origBindAI = InstitutionalUI.bindAIOperator;
    InstitutionalUI.bindAIOperator = function() {
      // Call original binding for inline ai-operator-panel
      if (_origBindAI) _origBindAI.call(this);

      // Also bind off-canvas-ai panel
      var toggleBtn = document.getElementById('sidebar-toggle');
      var panel = document.getElementById('off-canvas-ai');
      var closeBtn = document.getElementById('off-canvas-ai-close');
      if (!toggleBtn || !panel) return;
      toggleBtn.addEventListener('click', function(e) {
        e.stopPropagation();
        panel.classList.toggle('active');
      });
      if (closeBtn) {
        closeBtn.addEventListener('click', function() {
          panel.classList.remove('active');
        });
      }
      document.addEventListener('click', function(e) {
        if (panel.classList.contains('active') && !panel.contains(e.target) && !toggleBtn.contains(e.target)) {
          panel.classList.remove('active');
        }
      });
    };

    // Note: init() is called by existing DOMContentLoaded listener
    // (which fires after this sync extension, so the overridden methods are active)
  }    // ── Wire DashboardCore into the existing render cycle ──
    var _origRender = render;
    render = function(snap) {
      _origRender(snap);
      DashboardCore.renderSnapshot(snap);
      renderKpiCards(snap);
    };
  })();

  // ── Sidebar collapse toggle ──
  document.getElementById('sidebar-collapse')?.addEventListener('click', function() {
    document.getElementById('sidebar')?.classList.toggle('collapsed');
    var btn = document.getElementById('sidebar-collapse');
    if (btn) btn.textContent = document.getElementById('sidebar')?.classList.contains('collapsed') ? '▶' : '◀';
  });

  // ── Docs: IntersectionObserver for active section ──
  var _docsObserver = null;
  var _docsSearchInitialized = false;
  function _initDocsObserver() {
    if (_docsObserver) return;
    // Scoped to the docs container: the LEARNING panel also uses .doc-section
    // markup (whitepaper/library) but must NOT feed the docs active-link
    // highlight — otherwise its sections would steal the observer's focus.
    var docsContainer = document.querySelector('.docs-container');
    var sections = docsContainer ? docsContainer.querySelectorAll('.doc-section') : [];
    if (!sections.length) return;
    var links = document.querySelectorAll('.docs-index__link');
    _docsObserver = new IntersectionObserver(function(entries) {
      var visible = [];
      entries.forEach(function(entry) {
        if (entry.isIntersecting) visible.push(entry.target.id);
      });
      if (!visible.length) return;
      var topId = visible.reduce(function(a, b) {
        var elA = document.getElementById(a), elB = document.getElementById(b);
        return (elA && elA.getBoundingClientRect().top || 0) < (elB && elB.getBoundingClientRect().top || 0) ? a : b;
      });
      links.forEach(function(link) {
        link.classList.toggle('docs-index__link--active', link.getAttribute('data-section') === topId);
      });
    }, { rootMargin: '-80px 0px -60% 0px', threshold: 0 });
    sections.forEach(function(s) { _docsObserver.observe(s); });
  }

  // ── Docs: Search / filter ──
  function _initDocsSearch() {
    if (_docsSearchInitialized) return;
    var input = document.getElementById('docs-search-input');
    var clear = document.getElementById('docs-search-clear');
    var links = document.querySelectorAll('.docs-index__links .docs-index__link');
    if (!input || !links.length) return;
    _docsSearchInitialized = true;

    input.addEventListener('input', function() {
      var q = this.value.trim().toLowerCase();
      links.forEach(function(link) {
        var section = document.getElementById(link.getAttribute('data-section'));
        if (!section) return;
        if (!q) {
          section.style.display = '';
          link.style.display = '';
        } else {
          var match = section.textContent.toLowerCase().indexOf(q) !== -1;
          section.style.display = match ? '' : 'none';
          link.style.display = match ? '' : 'none';
        }
      });
      if (clear) clear.style.display = q ? '' : 'none';
    });

    clear?.addEventListener('click', function() {
      input.value = '';
      input.dispatchEvent(new Event('input', { bubbles: true }));
      input.focus();
    });
  }

  // Initialize docs features once at boot if the section exists
  if (document.getElementById('section-docs')) {
    // Use requestIdleCallback or on first scroll to not block initial render
    var _initDocs = function() {
      _initDocsObserver();
      _initDocsSearch();
    };
    if (window.requestIdleCallback) {
      requestIdleCallback(_initDocs, { timeout: 2000 });
    } else {
      setTimeout(_initDocs, 1500);
    }
  }

  // ── Collapsible FAQ ──
  document.addEventListener('click', function(e) {
    var faqQ = e.target.closest('.doc-faq-item__q');
    if (faqQ) {
      var answer = faqQ.nextElementSibling;
      if (answer && answer.classList.contains('doc-faq-item__a')) {
        if (answer.style.display === 'none') {
          answer.style.display = '';
          faqQ.classList.remove('doc-faq-item__q--collapsed');
        } else {
          answer.style.display = 'none';
          faqQ.classList.add('doc-faq-item__q--collapsed');
        }
      }
    }
  });

  // ── Sidebar module navigation — implemented via activateModule() above ──
  // (SECTION_MAP removido — a navegação agora usa data-module)

  // ── Collapsible panels toggle ──
  document.addEventListener('click', function(e) {
    var toggle = e.target.closest('.panel__toggle');
    if (!toggle) return;
    var panel = toggle.closest('.panel--collapsible');
    if (!panel) return;
    panel.classList.toggle('collapsed');
    toggle.classList.toggle('collapsed');
  });

  // ── KPI Cards render ──
  function renderKpiCards(snap) {
    if (!snap) return;
    var w = snap.worker || {};
    var pool = snap.pool || {};
    var prox = snap.proximity || {};
    var workers = snap.all_workers || [];

    if (dom.kpiHashrate) dom.kpiHashrate.textContent = fmt.hashrate(w.hashrate);
    if (dom.kpiBestdiff) dom.kpiBestdiff.textContent = fmt.diff(w.bestDifficulty || w.best_diff);
    if (dom.kpiPoolhr) dom.kpiPoolhr.textContent = fmt.hashrate(pool.hashrate);

    // Share rate — from active workers or timeline
    if (dom.kpiShares) {
      var sharesCount = prox.live_calc?.session_totals?.shares_so_far || 0;
      var shareRate = prox.share_rate_hourly || 0;
      if (shareRate > 0) {
        dom.kpiShares.textContent = shareRate.toFixed(0) + '/h';
      } else if (sharesCount > 0) {
        dom.kpiShares.textContent = sharesCount + ' total';
      } else {
        dom.kpiShares.textContent = '\u2014';
      }
    }
  }