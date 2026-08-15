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
      // The pool API can return the literal string 'N/A' — guard non-numeric
      // values so we render a clean em-dash instead of NaN.
      if (!isFinite(Number(s))) return '\u2014';
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
    topbarProBadge: $('#topbar-pro-badge'),
    pLastBlock: $('#p-last-block'), pLastBlockTime: $('#p-last-block-time'), pWorkNum: $('#p-work-num'), pWorkFill: $('#p-work-fill'), pExpectedBlocks: $('#p-expected-blocks'),
    pStaleBadge: $('#p-stale-badge'),
    acctBlocksBadge: $('#acct-blocks-badge'), acctLn: $('#acct-ln'), acctTotalDiff: $('#acct-total-diff'),
    acctHighestBlock: $('#acct-highest-block'), acctCombined: $('#acct-combined'), acctDiffRank: $('#acct-diff-rank'), acctLoyaltyRank: $('#acct-loyalty-rank'),
    netStatus: $('#net-status'), nHeight: $('#n-height'), nDiff: $('#n-diff'), nHashrate: $('#n-hashrate'),
    nBtcUsd: $('#n-btc-usd'), nBtcBrl: $('#n-btc-brl'), nBtcEur: $('#n-btc-eur'), nBtcGbp: $('#n-btc-gbp'), nBtcJpy: $('#n-btc-jpy'), nBtcKrw: $('#n-btc-krw'), nBtcCny: $('#n-btc-cny'),
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
    lmStatusBadge: $('#lm-status-badge'), lmWorkersBadge: $('#lm-workers-badge'),
    fccSummaryHr: $('#fcc-summary-hr'), fccSummaryHrSpark: $('#fcc-summary-hr-spark'),
    fccSummaryOnline: $('#fcc-summary-online'), fccSummaryWarn: $('#fcc-summary-warn'), fccSummaryOffline: $('#fcc-summary-offline'),
    fccSummaryTemp: $('#fcc-summary-temp'), fccSummaryPower: $('#fcc-summary-power'), fccSummaryEff: $('#fcc-summary-eff'),
    fccSummaryPing: $('#fcc-summary-ping'), fccSummaryEarnings: $('#fcc-summary-earnings'),
    fccExceptions: $('#fcc-exceptions'), fccThermalGrid: $('#fcc-thermal-grid'),
    lmNetworkDiff: $('#lm-network-diff'), lmNetworkHr: $('#lm-network-hr'), lmNetworkHeight: $('#lm-network-height'),
    lmNetworkBlock: $('#lm-network-block'), lmNetworkPoolWorkers: $('#lm-network-pool-workers'), lmNetworkLastBlock: $('#lm-network-last-block'),
    lmBestShare: $('#lm-best-share'), lmBestShareVal: $('#lm-best-share-val'), lmBestShareWorker: $('#lm-best-share-worker'), lmBestShareTime: $('#lm-best-share-time'),
    lmWorkers: $('#lm-workers'), lmWorkersGrid: $('#lm-workers-grid'), lmWorkersCount: $('#lm-workers-count'), lmFlow: $('#lm-flow'), lmFlowRaster: $('#lm-flow-raster'),
    lmEventLogTerminal: $('#lm-event-log-terminal'),
    hsNonceBar: $('#hs-nonce-bar'), hsNoncesSearched: $('#hs-nonces-searched'), hsNoncePct: $('#hs-nonce-pct'), hsHashesPerSec: $('#hs-hashes-per-sec'),
    hsBestDiff: $('#hs-best-diff'), hsTargetDiff: $('#hs-target-diff'), hsTargetBar: $('#hs-target-bar'), hsTargetMarker: $('#hs-target-marker'),
    hsBlockProb: $('#hs-block-prob'), hsExpectedTime: $('#hs-expected-time'), hsStatusText: $('#hs-status-text'),
    openWallet: $('#open-wallet'), walletModal: $('#wallet-modal'), walletStatus: $('#wallet-status'),
    walletAddressInput: $('#wallet-address-input'), walletWorkerInput: $('#wallet-worker-input'),
    walletCurrentAddr: $('#wallet-current-addr'), walletCurrentWorker: $('#wallet-current-worker'), walletCurrentStatus: $('#wallet-current-status'),
    walletSave: $('#wallet-save'),
    openSettings: $('#open-settings'), openExports: $('#open-exports'), settingsModal: $('#settings-modal'), exportModal: $('#export-modal'),
    settingsBody: $('#settings-body'), settingsStatus: $('#settings-status'),
    openAlertCenter: $('#open-alert-center'), alertCenterModal: $('#alert-center-modal'), alertCenterStatus: $('#alert-center-status'),
    acTabs: $$('.ac-tab'), acPanes: $$('.ac-pane'), acFilters: $$('.ac-filter'),
    acActiveList: $('#ac-active-list'), acHistoryList: $('#ac-history-list'), acRulesList: $('#ac-rules-list'), acExecList: $('#ac-exec-list'),
    acRefreshActive: $('#ac-refresh-active'), acRefreshHistory: $('#ac-refresh-history'), acRefreshRules: $('#ac-refresh-rules'),
    acAddRule: $('#ac-add-rule'), acRuleForm: $('#ac-rule-form'), acRuleSave: $('#ac-rule-save'), acRuleCancel: $('#ac-rule-cancel'),
    acRuleName: $('#ac-rule-name'), acRuleDevice: $('#ac-rule-device'), acRuleMetric: $('#ac-rule-metric'), acRuleOp: $('#ac-rule-op'),
    acRuleValue: $('#ac-rule-value'), acRuleAction: $('#ac-rule-action'), acRuleStatus: $('#ac-rule-status'),

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
    axeScanCidr: $('#axe-scan-cidr'),
    axeScanBtn: $('#axe-scan-btn'),
    axeScanStatus: $('#axe-scan-status'),
    axeScanResults: $('#axe-scan-results'),
    axeFleetAdd: $('#axe-fleet-add'),
    axeFleetScan: $('#axe-fleet-scan'),
    axeTestConn: $('#axe-test-conn'),
    axeTestResult: $('#axe-test-result'),
    axeWizSteps: $('#axe-wiz-steps'),
    axeWizConfirm: $('#axe-wiz-confirm'),
    axeManualNameRow: $('#axe-manual-name-row'),
    axeEmptyAdd: $('#axe-empty-add'),

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

  // ── Rentals provider auth state (Issue #152) ────────────────────────
  // A CONFIGURED-but-rejected key (401/403, or MRR's classic 'Not
  // Authenticated - Invalid Key - Bad Nonce.') is a CREDENTIAL problem, not
  // a missing-credential state and not a concurrency bug. These pure
  // helpers classify the rejection and build the FIX guidance per provider;
  // mirrored in tests/test_app_js_core.js.
  function rentalsAuthRejected(errMsg, authRejected) {
    if (authRejected) return true;
    return /rejected|401|403|unauthor|forbidden|bad nonce|not authenticated|invalid key/i.test(String(errMsg || ''));
  }
  function rentalsAuthGuide(provider, errMsg) {
    const safe = escapeHtml(String(errMsg || ''));
    if (provider === 'contracts') {
      return 'A chave Braiins está configurada, mas a API a rejeitou: ' + safe +
        '. Gere um novo owner token em hashpower.braiins.com e atualize no Settings (⚙).';
    }
    return 'A chave MRR está configurada, mas a API a rejeitou: ' + safe +
      '. Causa provável: credencial inválida/desatualizada (ou tracker de nonce da chave preso) ' +
      '— NÃO é bug de concorrência. Regenerar a API key + secret em miningrigrentals.com ' +
      '→ My Account → API Access e atualizar no Settings (⚙).';
  }

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

  // R1 (PRO tier): the operator's license key rides along on every API call
  // via X-License-Key (persisted in localStorage by initLicensing). Open
  // mode (no PRO_LICENSE_KEYS on the server) ignores it — this header only
  // matters once the gate is active.
  const LICENSE_STORAGE_KEY = '_cypher65_license';
  function licenseKey() {
    try { return localStorage.getItem(LICENSE_STORAGE_KEY) || ''; } catch (e) { return ''; }
  }
  function authBuildHeaders(token) {
    const h = {};
    const lk = licenseKey();
    if (lk) h['X-License-Key'] = lk;
    if (token) h['Authorization'] = 'Bearer ' + token;
    return h;
  }
  // PRO licensing state (open/free/pro) — populated by initLicensing() on
  // boot and used to render the topbar badge + upgrade CTA on 402s.
  let _license = { mode: 'open', tier: 'pro', pro: true };
  async function initLicensing() {
    try {
      const r = await fetch('/api/license-status');
      if (!r.ok) return;
      _license = await r.json();
    } catch (e) { return; }
    renderLicenseBadge();
    syncUpgradeModal();
  }
  function renderLicenseBadge() {
    const badge = dom.topbarProBadge;
    if (!badge) return;
    if (_license.mode === 'open' || _license.pro) {
      // Open mode (everything free) or active PRO — show a quiet PRO tag.
      badge.hidden = false;
      badge.textContent = _license.pro ? 'PRO' : 'FREE';
      badge.classList.toggle('is-pro', !!_license.pro);
      badge.title = _license.pro ? 'PRO license active' : 'Open mode — all features free';
      badge.onclick = null;  // clear any leftover upgrade-CTA handler (audit)
      syncUpgradeModal();
      return;
    }
    // Licensed mode + free tier → gate is live; badge is the upgrade CTA.
    badge.hidden = false;
    badge.textContent = 'UPGRADE';
    badge.classList.toggle('is-pro', false);
    badge.title = 'PRO features locked — click to upgrade';
    badge.onclick = openUpgradeModal;
    syncUpgradeModal();
  }
  // R1 revenue: upgrade modal — buy via Lemon Squeezy checkout or redeem a key.
  // CFO: firing the funnel events is best-effort and silent — telemetry must
  // never delay or break the UI (no await on the happy path).
  function funnelId() {
    // Issue #155: anonymous browser session id for funnel attribution.
    // PII-free random token generated once and kept in localStorage — it lets
    // paywall/modal/checkout/paid form a per-user path server-side without
    // storing any personal data (never sent as email, only echoed into the
    // Lemon Squeezy checkout `custom` field and back via the webhook).
    try {
      let id = localStorage.getItem('c65_funnel_id');
      if (!id) {
        id = 'f_' + Math.random().toString(36).slice(2) + Date.now().toString(36);
        localStorage.setItem('c65_funnel_id', id);
      }
      return id;
    } catch (e) { return ''; }
  }
  function trackConversionEvent(event, meta) {
    try {
      const m = meta || {};
      if (!m.funnel_id) m.funnel_id = funnelId();
      fetch('/api/conversion/track', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ event: event, meta: m }),
      }).catch(function () { /* fire-and-forget */ });
    } catch (e) { /* never break the UI for telemetry */ }
  }
  function openUpgradeModal() {
    const m = document.getElementById('upgrade-modal');
    openModalAnimated(m);
    trackConversionEvent('modal_open');
  }
  // Exposed for e2e + support console (the PRO badge already wires onclick).
  window.openUpgradeModal = openUpgradeModal;
  function closeUpgradeModal() {
    closeModalAnimated(document.getElementById('upgrade-modal'));
  }
  // Show the Buy button only when the server has a payment provider configured,
  // and drive its price copy from the server payload (single source of truth).
  function syncUpgradeModal() {
    const buy = document.getElementById('upgrade-buy-btn');
    const div = document.getElementById('upgrade-divider');
    if (buy) {
      buy.hidden = !_license.payments;
      const up = _license.upgrade;
      const price = (up && up.price_usd_month) || 9;
      buy.textContent = 'Buy PRO — $' + price + '/mo';
    }
    if (div) div.hidden = !_license.payments;
  }
  async function buyPro() {
    const btn = document.getElementById('upgrade-buy-btn');
    if (btn) btn.disabled = true;
    trackConversionEvent('checkout_start', { plan: 'pro' });
    try {
      const r = await fetch('/api/upgrade/checkout', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ plan: 'pro', funnel_id: funnelId() }),
      });
      let data = {};
      try { data = await r.json(); } catch (e) {}
      if (r.ok && data.checkout_url) {
        window.open(data.checkout_url, '_blank', 'noopener');
      } else {
        logMessage('PRO', (data && data.error) || 'Checkout unavailable', 'WARN');
      }
    } catch (e) {
      logMessage('PRO', 'Checkout unavailable', 'WARN');
    } finally {
      if (btn) btn.disabled = false;
    }
  }
  async function redeemLicenseKey() {
    const input = document.getElementById('upgrade-key-input');
    const key = (input && input.value || '').trim();
    if (!key) return;
    try { localStorage.setItem(LICENSE_STORAGE_KEY, key); } catch (e) {}
    await initLicensing();
    closeUpgradeModal();
    // Re-run the current snapshot render so gated panels refresh.
    renderCharts();
    if (_license.pro) trackConversionEvent('key_activated');
    logMessage('PRO', _license.pro ? 'license key accepted — PRO unlocked' : 'license key rejected', _license.pro ? 'SUCCESS' : 'WARN');
    if (input) input.value = '';  // clear the field for the next activation
  }
  // Shared handler for 402 (PRO required) responses: surface the upgrade CTA.
  async function handleLicenseRequired(res) {
    let data = {};
    try { data = await res.json(); } catch (e) {}
    renderLicenseBadge();
    logMessage('PRO', (data && data.error) || 'PRO feature locked — license key required', 'WARN');
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
        openModalAnimated(modal);
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
            closeModalAnimated(modal);
            fetchAxeFleet();
          }, 400);
        }
      });
    }
    if (dom.authLogoutBtn) {
      dom.authLogoutBtn.addEventListener('click', async function() {
        await authLogout();
        closeModalAnimated(modal);
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

  // ══════════════════════════════════════════════════════════════════════
  //  P0-4 · QR CODE CORE — ISO/IEC 18004, byte mode, versions 1-10
  //  Pure functions (no DOM) — mirrored in tests/test_app_js_core.js and
  //  validated cell-by-cell against golden matrices produced by the
  //  independent Kazuhiko Arase QRCode implementation (MIT-licensed, the
  //  vendor inside qrcode-terminal). All ECC levels L/M/Q/H supported;
  //  any valid BTC address (<= 90 chars) fits version <= 10.
  // ══════════════════════════════════════════════════════════════════════
  const QR_ECC = { L: 1, M: 0, Q: 3, H: 2 }; // values = 2-bit format field
  const QR_MODE_8BIT = 4;
  const QR_PAD0 = 0xEC, QR_PAD1 = 0x11;
  // GF(256) tables (primitive poly x^8+x^4+x^3+x^2+1)
  const QR_EXP = new Array(256), QR_LOG = new Array(256);
  (function buildQrMath() {
    for (let i = 0; i < 8; i++) QR_EXP[i] = 1 << i;
    for (let i = 8; i < 256; i++) QR_EXP[i] = QR_EXP[i - 4] ^ QR_EXP[i - 5] ^ QR_EXP[i - 6] ^ QR_EXP[i - 8];
    for (let i = 0; i < 255; i++) QR_LOG[QR_EXP[i]] = i;
  })();
  function qrGexp(n) { while (n < 0) n += 255; while (n >= 256) n -= 255; return QR_EXP[n]; }
  function qrGlog(n) { if (n < 1) throw new Error('qr glog(' + n + ')'); return QR_LOG[n]; }

  // Polynomial over GF(256) with leading-zero trim + shift (Arase semantics)
  function QrPoly(num, shift) {
    let offset = 0;
    while (offset < num.length && num[offset] === 0) offset++;
    this.num = new Array(num.length - offset + shift);
    for (let i = 0; i < num.length - offset; i++) this.num[i] = num[i + offset];
  }
  QrPoly.prototype.get = function (i) { return this.num[i]; };
  QrPoly.prototype.getLength = function () { return this.num.length; };
  QrPoly.prototype.multiply = function (e) {
    const num = new Array(this.getLength() + e.getLength() - 1);
    for (let i = 0; i < this.getLength(); i++) {
      for (let j = 0; j < e.getLength(); j++) {
        num[i + j] ^= qrGexp(qrGlog(this.get(i)) + qrGlog(e.get(j)));
      }
    }
    return new QrPoly(num, 0);
  };
  QrPoly.prototype.mod = function (e) {
    if (this.getLength() - e.getLength() < 0) return this;
    const ratio = qrGlog(this.get(0)) - qrGlog(e.get(0));
    const num = new Array(this.getLength());
    for (let i = 0; i < this.getLength(); i++) num[i] = this.get(i);
    for (let x = 0; x < e.getLength(); x++) num[x] ^= qrGexp(qrGlog(e.get(x)) + ratio);
    return new QrPoly(num, 0).mod(e);
  };

  // RS block table: rows are [L, M, Q, H] per version (v1-v10)
  const QR_RS_BLOCKS = [
    [1, 26, 19], [1, 26, 16], [1, 26, 13], [1, 26, 9],
    [1, 44, 34], [1, 44, 28], [1, 44, 22], [1, 44, 16],
    [1, 70, 55], [1, 70, 44], [2, 35, 17], [2, 35, 13],
    [1, 100, 80], [2, 50, 32], [2, 50, 24], [4, 25, 9],
    [1, 134, 108], [2, 67, 43], [2, 33, 15, 2, 34, 16], [2, 33, 11, 2, 34, 12],
    [2, 86, 68], [4, 43, 27], [4, 43, 19], [4, 43, 15],
    [2, 98, 78], [4, 49, 31], [2, 32, 14, 4, 33, 15], [4, 39, 13, 1, 40, 14],
    [2, 121, 97], [2, 60, 38, 2, 61, 39], [4, 40, 18, 2, 41, 19], [4, 40, 14, 2, 41, 15],
    [2, 146, 116], [3, 58, 36, 2, 59, 37], [4, 36, 16, 4, 37, 17], [4, 36, 12, 4, 37, 13],
    [2, 86, 68, 2, 87, 69], [4, 69, 43, 1, 70, 44], [6, 43, 19, 2, 44, 20], [6, 43, 15, 2, 44, 16],
  ];
  function qrGetRsBlocks(type, ecl) {
    const row = QR_RS_BLOCKS[(type - 1) * 4 + ({ 1: 0, 0: 1, 3: 2, 2: 3 })[ecl]];
    const list = [];
    for (let i = 0; i < row.length / 3; i++) {
      const count = row[i * 3], total = row[i * 3 + 1], data = row[i * 3 + 2];
      for (let j = 0; j < count; j++) list.push({ totalCount: total, dataCount: data });
    }
    return list;
  }

  const QR_PATTERN_POS = [
    [], [6, 18], [6, 22], [6, 26], [6, 30], [6, 34], [6, 22, 38], [6, 24, 42], [6, 26, 46], [6, 28, 50],
  ];
  const QR_G15 = (1 << 10) | (1 << 8) | (1 << 5) | (1 << 4) | (1 << 2) | (1 << 1) | (1 << 0);
  const QR_G18 = (1 << 12) | (1 << 11) | (1 << 10) | (1 << 9) | (1 << 8) | (1 << 5) | (1 << 2) | (1 << 0);
  const QR_G15_MASK = (1 << 14) | (1 << 12) | (1 << 10) | (1 << 4) | (1 << 1);
  function qrBchDigit(d) { let n = 0; while (d !== 0) { n++; d >>>= 1; } return n; }
  function qrBchTypeInfo(data) {
    let d = data << 10;
    while (qrBchDigit(d) - qrBchDigit(QR_G15) >= 0) d ^= QR_G15 << (qrBchDigit(d) - qrBchDigit(QR_G15));
    return ((data << 10) | d) ^ QR_G15_MASK;
  }
  function qrBchTypeNumber(data) {
    let d = data << 12;
    while (qrBchDigit(d) - qrBchDigit(QR_G18) >= 0) d ^= QR_G18 << (qrBchDigit(d) - qrBchDigit(QR_G18));
    return (data << 12) | d;
  }
  function qrGetMask(mask, i, j) {
    switch (mask) {
      case 0: return (i + j) % 2 === 0;
      case 1: return i % 2 === 0;
      case 2: return j % 3 === 0;
      case 3: return (i + j) % 3 === 0;
      case 4: return (Math.floor(i / 2) + Math.floor(j / 3)) % 2 === 0;
      case 5: return (i * j) % 2 + (i * j) % 3 === 0;
      case 6: return ((i * j) % 2 + (i * j) % 3) % 2 === 0;
      case 7: return ((i * j) % 3 + (i + j) % 2) % 2 === 0;
      default: throw new Error('bad maskPattern:' + mask);
    }
  }
  function qrErrorCorrectPoly(len) {
    let a = new QrPoly([1], 0);
    for (let i = 0; i < len; i++) a = a.multiply(new QrPoly([1, qrGexp(i)], 0));
    return a;
  }
  function qrLengthInBits(type) { return type < 10 ? 8 : 16; }

  function qrCreateData(type, ecl, text) {
    const blocks = qrGetRsBlocks(type, ecl);
    let totalData = 0;
    blocks.forEach(b => { totalData += b.dataCount; });
    const bits = [];
    let bitLen = 0;
    function put(num, len) {
      for (let i = 0; i < len; i++) {
        bits.push(((num >>> (len - i - 1)) & 1) === 1);
        bitLen++;
      }
    }
    put(QR_MODE_8BIT, 4);
    put(text.length, qrLengthInBits(type));
    for (let i = 0; i < text.length; i++) put(text.charCodeAt(i) & 0xff, 8);
    if (bitLen + 4 <= totalData * 8) put(0, 4);
    while (bitLen % 8 !== 0) put(0, 1);
    while (true) {
      if (bitLen >= totalData * 8) break;
      put(QR_PAD0, 8);
      if (bitLen >= totalData * 8) break;
      put(QR_PAD1, 8);
    }
    const buf = [];
    for (let i = 0; i < bits.length; i += 8) {
      let byte = 0;
      for (let j = 0; j < 8; j++) byte = (byte << 1) | (bits[i + j] ? 1 : 0);
      buf.push(byte);
    }
    let offset = 0, maxDc = 0, maxEc = 0;
    const dcdata = [], ecdata = [];
    for (let r = 0; r < blocks.length; r++) {
      const dcCount = blocks[r].dataCount;
      const ecCount = blocks[r].totalCount - dcCount;
      maxDc = Math.max(maxDc, dcCount);
      maxEc = Math.max(maxEc, ecCount);
      const dc = [];
      for (let i = 0; i < dcCount; i++) dc.push(buf[i + offset]);
      offset += dcCount;
      const rsPoly = qrErrorCorrectPoly(ecCount);
      const rawPoly = new QrPoly(dc, rsPoly.getLength() - 1);
      const modPoly = rawPoly.mod(rsPoly);
      const ec = new Array(rsPoly.getLength() - 1);
      for (let x = 0; x < ec.length; x++) {
        const modIndex = x + modPoly.getLength() - ec.length;
        ec[x] = modIndex >= 0 ? modPoly.get(modIndex) : 0;
      }
      dcdata[r] = dc; ecdata[r] = ec;
    }
    let total = 0;
    blocks.forEach(b => { total += b.totalCount; });
    const data = new Array(total);
    let index = 0;
    for (let z = 0; z < maxDc; z++) for (let s = 0; s < blocks.length; s++) if (z < dcdata[s].length) data[index++] = dcdata[s][z];
    for (let z = 0; z < maxEc; z++) for (let s = 0; s < blocks.length; s++) if (z < ecdata[s].length) data[index++] = ecdata[s][z];
    return data;
  }

  function qrMakeImpl(type, ecl, test, mask, data) {
    const mc = type * 4 + 17;
    const mods = [];
    for (let r = 0; r < mc; r++) { mods[r] = new Array(mc); for (let c = 0; c < mc; c++) mods[r][c] = null; }
    function probe(row, col) {
      for (let r = -1; r <= 7; r++) {
        if (row + r <= -1 || mc <= row + r) continue;
        for (let c = -1; c <= 7; c++) {
          if (col + c <= -1 || mc <= col + c) continue;
          mods[row + r][col + c] =
            ((0 <= r && r <= 6 && (c === 0 || c === 6)) ||
             (0 <= c && c <= 6 && (r === 0 || r === 6)) ||
             (2 <= r && r <= 4 && 2 <= c && c <= 4));
        }
      }
    }
    probe(0, 0); probe(mc - 7, 0); probe(0, mc - 7);
    const pos = QR_PATTERN_POS[type - 1];
    for (let i = 0; i < pos.length; i++) {
      for (let j = 0; j < pos.length; j++) {
        const row = pos[i], col = pos[j];
        if (mods[row][col] !== null) continue;
        for (let r = -2; r <= 2; r++) {
          for (let c = -2; c <= 2; c++) {
            mods[row + r][col + c] = (Math.abs(r) === 2 || Math.abs(c) === 2 || (r === 0 && c === 0));
          }
        }
      }
    }
    for (let r = 8; r < mc - 8; r++) if (mods[r][6] === null) mods[r][6] = (r % 2 === 0);
    for (let c = 8; c < mc - 8; c++) if (mods[6][c] === null) mods[6][c] = (c % 2 === 0);
    const fbits = qrBchTypeInfo((ecl << 3) | mask);
    for (let v = 0; v < 15; v++) {
      const mod = !test && (((fbits >> v) & 1) === 1);
      if (v < 6) mods[v][8] = mod;
      else if (v < 8) mods[v + 1][8] = mod;
      else mods[mc - 15 + v][8] = mod;
    }
    for (let h = 0; h < 15; h++) {
      const mod = !test && (((fbits >> h) & 1) === 1);
      if (h < 8) mods[8][mc - h - 1] = mod;
      else if (h < 9) mods[8][15 - h - 1 + 1] = mod;
      else mods[8][15 - h - 1] = mod;
    }
    mods[mc - 8][8] = !test;
    if (type >= 7) {
      const vbits = qrBchTypeNumber(type);
      for (let i = 0; i < 18; i++) {
        const mod = !test && (((vbits >> i) & 1) === 1);
        mods[Math.floor(i / 3)][i % 3 + mc - 8 - 3] = mod;
      }
      for (let x = 0; x < 18; x++) {
        const mod = !test && (((vbits >> x) & 1) === 1);
        mods[x % 3 + mc - 8 - 3][Math.floor(x / 3)] = mod;
      }
    }
    let inc = -1, row = mc - 1, bitIndex = 7, byteIndex = 0;
    for (let col = mc - 1; col > 0; col -= 2) {
      if (col === 6) col--;
      while (true) {
        for (let c = 0; c < 2; c++) {
          if (mods[row][col - c] === null) {
            let dark = false;
            if (byteIndex < data.length) dark = (((data[byteIndex] >>> bitIndex) & 1) === 1);
            if (qrGetMask(mask, row, col - c)) dark = !dark;
            mods[row][col - c] = dark;
            bitIndex--;
            if (bitIndex === -1) { byteIndex++; bitIndex = 7; }
          }
        }
        row += inc;
        if (row < 0 || mc <= row) { row -= inc; inc = -inc; break; }
      }
    }
    return mods;
  }

  function qrLostPoint(mods) {
    const mc = mods.length;
    let lp = 0;
    for (let row = 0; row < mc; row++) {
      for (let col = 0; col < mc; col++) {
        let sameCount = 0; const dark = mods[row][col];
        for (let r = -1; r <= 1; r++) {
          if (row + r < 0 || mc <= row + r) continue;
          for (let c = -1; c <= 1; c++) {
            if (col + c < 0 || mc <= col + c) continue;
            if (r === 0 && c === 0) continue;
            if (dark === mods[row + r][col + c]) sameCount++;
          }
        }
        if (sameCount > 5) lp += 3 + sameCount - 5;
      }
    }
    for (let row = 0; row < mc - 1; row++) {
      for (let col = 0; col < mc - 1; col++) {
        let count = 0;
        if (mods[row][col]) count++;
        if (mods[row + 1][col]) count++;
        if (mods[row][col + 1]) count++;
        if (mods[row + 1][col + 1]) count++;
        if (count === 0 || count === 4) lp += 3;
      }
    }
    for (let row = 0; row < mc; row++) {
      for (let col = 0; col < mc - 6; col++) {
        if (mods[row][col] && !mods[row][col + 1] && mods[row][col + 2] && mods[row][col + 3] && mods[row][col + 4] && !mods[row][col + 5] && mods[row][col + 6]) lp += 40;
      }
    }
    for (let col = 0; col < mc; col++) {
      for (let row = 0; row < mc - 6; row++) {
        if (mods[row][col] && !mods[row + 1][col] && mods[row + 2][col] && mods[row + 3][col] && mods[row + 4][col] && !mods[row + 5][col] && mods[row + 6][col]) lp += 40;
      }
    }
    let darkCount = 0;
    for (let col = 0; col < mc; col++) for (let row = 0; row < mc; row++) if (mods[row][col]) darkCount++;
    lp += Math.abs(100 * darkCount / mc / mc - 50) / 5 * 10;
    return lp;
  }

  // Public encode: returns { modules: 2D bool, size, type, ecl, mask }
  function qrEncode(text, ecl) {
    text = String(text || '');
    ecl = QR_ECC[ecl] !== undefined ? QR_ECC[ecl] : QR_ECC.M;
    let type = 1;
    for (type = 1; type <= 10; type++) {
      const blocks = qrGetRsBlocks(type, ecl);
      let totalData = 0;
      blocks.forEach(b => { totalData += b.dataCount; });
      const bitLen = 4 + qrLengthInBits(type) + text.length * 8;
      if (bitLen <= totalData * 8) break;
    }
    if (type > 10) throw new Error('QR input too long (' + text.length + ' chars)');
    const data = qrCreateData(type, ecl, text);
    let minLp = 0, pattern = 0;
    for (let i = 0; i < 8; i++) {
      const m = qrMakeImpl(type, ecl, true, i, data);
      const lp = qrLostPoint(m);
      if (i === 0 || minLp > lp) { minLp = lp; pattern = i; }
    }
    const modules = qrMakeImpl(type, ecl, false, pattern, data);
    return { modules, size: type * 4 + 17, type, ecl, mask: pattern };
  }

  // Render the module matrix as a crisp inline SVG (quiet zone = 4 modules)
  function qrSvg(modules) {
    const size = modules.length;
    const q = 4;
    const cells = [];
    for (let r = 0; r < size; r++) {
      for (let c = 0; c < size; c++) {
        if (modules[r][c]) cells.push('M' + (c + q) + ' ' + (r + q) + 'h1v1h-1z');
      }
    }
    const dim = size + q * 2;
    return '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ' + dim + ' ' + dim + '" shape-rendering="crispEdges" role="img" aria-label="QR code">' +
      '<rect width="' + dim + '" height="' + dim + '" fill="#fff"/>' +
      (cells.length ? '<path d="' + cells.join('') + '" fill="#111"/>' : '') +
      '</svg>';
  }

  // ── P0-4 · Wallet identity: checksum split + health ──────────────────
  // Pure helpers mirrored in tests. walletAddressParts splits an address
  // into {type, prefix, body, checksum, full} so the UI can highlight the
  // checksum region (the classic wrong-address ticket killer).
  function walletAddressParts(addr) {
    if (!addr) return null;
    addr = String(addr).trim();
    if (!addr) return null;
    const lower = addr.toLowerCase();
    // Bech32: checksum is exactly the last 6 chars (BIP-173) — highlight them.
    if (lower.indexOf('bc1') === 0 && addr.length >= 10) {
      return { type: 'bech32', prefix: 'bc1', body: addr.slice(3, -6), checksum: addr.slice(-6), full: addr };
    }
    // Base58 (legacy/P2SH): the trailing chars are the check digits operators
    // compare against their wallet app — highlight the real trailing substring
    // (never a byte-derived string that would differ from the displayed address).
    if ((addr[0] === '1' || addr[0] === '3') && addr.length >= 8) {
      return { type: 'base58', prefix: addr[0], body: addr.slice(1, -6), checksum: addr.slice(-6), full: addr };
    }
    return { type: 'other', prefix: '', body: addr.length > 6 ? addr.slice(0, -6) : '', checksum: addr.slice(-6), full: addr };
  }

  // Wallet health from the live snapshot (honest: every check gates on real
  // observed data — never fabricates). Returns {status, score, checks, connected}.
  function walletHealth(snap, now) {
    snap = snap || {};
    now = now || Math.floor(Date.now() / 1000);
    const connected = !!snap.btc_address;
    const worker = snap.worker || {};
    const pool = snap.pool || {};
    const checks = [
      { key: 'connected', label: 'Address set', ok: connected },
      { key: 'fresh', label: 'Data fresh', ok: !!snap.ts && (now - snap.ts) < 300 },
      { key: 'worker', label: 'Worker found', ok: !!snap.worker },
      { key: 'hashing', label: 'Hashing', ok: Number(worker.hashrate || 0) > 0 },
      { key: 'share', label: 'Recent share', ok: !!worker.lastSubmission && (now - Number(worker.lastSubmission)) < 7200 },
      { key: 'pool', label: 'Pool responding', ok: !!snap.pool && !pool._stale },
    ];
    const passed = checks.filter(c => c.ok).length;
    const score = Math.round(passed / checks.length * 100);
    let status;
    if (!connected) status = 'NO_WALLET';
    else if (score >= 80) status = 'HEALTHY';
    else if (score >= 50) status = 'DEGRADED';
    else status = 'CRITICAL';
    return { status, score, checks, connected, passed };
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

  // ── Skeleton loading (design-motion-principles) ──
  let _skeletonsHidden = false;
  // Shape set per container kind — header line + rows (chart/KPI variants).
  function _skelShapes(kind) {
    if (kind === 'kpi') return ['skel--kpi','skel--kpi','skel--kpi','skel--kpi'];
    if (kind === 'chart') return ['skel--chart','skel--line w-60','skel--line w-40'];
    if (kind === 'table') return ['skel--row','skel--row','skel--row','skel--row w-80','skel--row w-60'];
    return ['skel--line w-40','skel--line w-90','skel--line w-70','skel--line w-50'];
  }
  function _skelKind(p) {
    const id = (p && p.id) || '';
    if (p && p.classList.contains('kpi-row')) return 'kpi';
    if (id.indexOf('chart') !== -1 || id.indexOf('trend') !== -1) return 'chart';
    if (id.indexOf('market') !== -1) return 'table';  // offers grid dominates the panel
    if (id.indexOf('table') !== -1 || (p && p.classList.contains('rentals-list'))) return 'table';
    return '';
  }
  // Build a skeleton overlay INSIDE a container (used both at boot and for
  // lazy module loads). Decorative only — pointer-events:none, aria-hidden.
  function _skelBuild(container, kind) {
    if (container.querySelector('.skel-overlay')) return;
    const ov = document.createElement('div');
    ov.className = 'skel-overlay';
    ov.setAttribute('aria-hidden', 'true');
    _skelShapes(_skelKind(container) || kind).forEach(function (cls) {
      const s = document.createElement('div'); s.className = 'skel ' + cls;
      ov.appendChild(s);
    });
    container.appendChild(ov);
  }
  function skelShow(container, kind) { if (container) _skelBuild(container, kind); }
  function skelHide(container) {
    if (!container) return;
    const ov = container.querySelector('.skel-overlay');
    if (ov) { ov.remove(); }
  }
  // Skeleton around an async load: show → await → hide. Reused by manual
  // refresh buttons and module re-activation when the panel is empty, so the
  // shimmer is identical to the boot skeleton (transform-only, Emil <300ms).
  function skelRefresh(container, kind, p) {
    if (!container) return Promise.resolve(p);
    skelShow(container, kind);
    return Promise.resolve(p).then(
      function (v) { skelHide(container); return v; },
      function (e) { skelHide(container); throw e; }
    );
  }
  function showSkeletons() {
    document.querySelectorAll('.panel').forEach(p => _skelBuild(p, ''));
    // KPI row is the most prominent loading surface — give it KPI-shaped
    // blocks too (review fix: the kpi branch was previously dead code).
    document.querySelectorAll('#kpi-row').forEach(k => _skelBuild(k, 'kpi'));
  }
  function hideSkeletons() {
    document.querySelectorAll('.skel-overlay').forEach(o => o.remove());
    _skeletonsHidden = true;
  }

  // ── Button loading state ──
  function setBtnLoading(btn, on) {
    if (!btn) return;
    btn.classList.toggle('is-loading', on);
    btn.disabled = on;
  }

  // ── Modal exit (Jakub: exit subtler than enter) ──
  // Add .modal--closing, wait for the 120ms fade, then drop .modal--open.
  // Pending close timers are tracked per-modal so a rapid reopen cancels the
  // exit (review fix: close → reopen within 140ms must not force-close).
  const _modalCloseTimers = new Map();
  function closeModalAnimated(modal) {
    if (!modal || !modal.classList.contains('modal--open')) return;
    if (_modalCloseTimers.has(modal)) return;
    const reduce = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    modal.classList.add('modal--closing');
    const timer = setTimeout(function () {
      _modalCloseTimers.delete(modal);
      modal.classList.remove('modal--closing');
      modal.classList.remove('modal--open');
    }, reduce ? 0 : 140);
    _modalCloseTimers.set(modal, timer);
  }
  // Open helper: cancels any pending close + clears the exit class so a modal
  // reopened mid-exit animates in (not out). Pure add otherwise.
  function openModalAnimated(modal) {
    if (!modal) return;
    const t = _modalCloseTimers.get(modal);
    if (t) { clearTimeout(t); _modalCloseTimers.delete(modal); }
    modal.classList.remove('modal--closing');
    modal.classList.add('modal--open');
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
    // Idle worker (hr=0) still renders — bestDiff/lastSubmission/uptime visible

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
    if (dom.sbStatus) dom.sbStatus.textContent = snap.worker ? (snap.worker.hashrate ? 'ONLINE' : 'IDLE') : 'OFFLINE';
    if (dom.sbWorkers) dom.sbWorkers.textContent = `${workers.length} worker${workers.length === 1 ? '' : 's'}`;

    // Mining block
    if (dom.sbHashrate) dom.sbHashrate.textContent = fmt.hashrate(w.hashrate);
    if (dom.sbBestdiff) dom.sbBestdiff.textContent = fmt.diff(w.bestDifficulty);
    if (dom.sbLastshare) dom.sbLastshare.textContent = w.lastSubmission ? fmt.age(w.lastSubmission) : '\u2014';

    // Pool block
    if (dom.sbPoolHr) dom.sbPoolHr.textContent = fmt.hashrate(pool.hashrate);
    if (dom.sbPoolWorkers) dom.sbPoolWorkers.textContent = `${pool.workers || 0}`;
    // The pool API exposes the last block height under lastBlockTime (the
    // old lastBlock key no longer exists). Accept both for backward compat.
    const poolBlock = pool.lastBlock || pool.lastBlockTime;
    if (dom.sbPoolBlock) dom.sbPoolBlock.textContent = poolBlock ? `#${poolBlock.toLocaleString()}` : '\u2014';

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

    // Wallet block — show connected BTC address from snapshot with the
    // checksum region highlighted (P0-4: the wrong-address ticket killer).
    // shortAddrChunk + a checksum span so the operator can visually verify
    // the trailing check digits against their own wallet app.
    if (dom.sbWalletAddr) {
      var addr = snap.btc_address || window.BTC_ADDRESS || '';
      if (addr) {
        var parts = walletAddressParts(addr);
        var ck = (parts && parts.checksum) ? parts.checksum : addr.slice(-6);
        var head = addr.length > 12 ? addr.slice(0, 6) : addr.slice(0, addr.length - 6);
        dom.sbWalletAddr.innerHTML = '<span title="' + escapeHtml(addr) + '">' + escapeHtml(head) + '…<span class="addr-ck">' + escapeHtml(ck) + '</span></span>';
      } else {
        dom.sbWalletAddr.innerHTML = '—';
      }
      dom.sbWalletAddr.title = addr || 'no wallet connected';
    }
    // Wallet connection state — only topbar button remains
    // Connection state tracked via localStorage.getItem('_wallet_connected')
  }

  // ── P0-4 · Wallet identity card (QR + checksum + health) ─────────────
  // Renders the CONNECT WALLET modal's WALLET IDENTITY block: a scannable
  // QR of the full address, the address with its checksum highlighted, a
  // copy button and a live health strip computed from the snapshot.
  function renderWalletIdentity(snap) {
    var box = document.getElementById('wallet-id');
    if (!box) return;
    var addr = (snap && snap.btc_address) || window.BTC_ADDRESS || '';
    if (!addr) {
      box.style.display = 'none';
      return;
    }
    box.style.display = '';
    // QR (pure JS encoder — no external service, address never leaves browser)
    var qrBox = document.getElementById('wallet-id-qr');
    if (qrBox) {
      try {
        var qr = qrEncode(addr, 'M');
        qrBox.innerHTML = qrSvg(qr.modules);
      } catch (e) {
        qrBox.innerHTML = '<div class="wallet-id__qr-error">QR unavailable</div>';
      }
    }
    // Checksum-highlighted address
    var addrEl = document.getElementById('wallet-id-addr');
    if (addrEl) {
      var parts = walletAddressParts(addr);
      if (parts) {
        addrEl.innerHTML = '<span class="addr-pfx">' + escapeHtml(parts.prefix) + '</span>' +
          '<span class="addr-body">' + escapeHtml(parts.body) + '</span>' +
          '<span class="addr-ck">' + escapeHtml(parts.checksum) + '</span>';
      } else {
        addrEl.textContent = addr;
      }
    }
    // Copy button
    var copyBtn = document.getElementById('wallet-id-copy');
    if (copyBtn) {
      copyBtn.onclick = function() {
        if (navigator.clipboard && addr) {
          navigator.clipboard.writeText(addr).then(function() {
            var orig = copyBtn.textContent;
            copyBtn.textContent = '[copied]';
            setTimeout(function() { copyBtn.textContent = orig; }, 1800);
          });
        }
      };
    }
    // Health strip
    var health = walletHealth(snap || {});
    var hEl = document.getElementById('wallet-id-health');
    if (hEl) {
      hEl.className = 'wallet-id__health wallet-id__health--' + health.status.toLowerCase();
      hEl.textContent = health.connected
        ? health.status + ' · ' + health.score + '% (' + health.passed + '/' + health.checks.length + ' checks)'
        : 'NO WALLET CONNECTED';
      hEl.title = health.checks.map(function(c) { return (c.ok ? '✓' : '✗') + ' ' + c.label; }).join('\n');
    }
    var checksEl = document.getElementById('wallet-id-checks');
    if (checksEl && health.connected) {
      checksEl.style.display = '';
      checksEl.innerHTML = health.checks.map(function(c) {
        return '<li class="wallet-id__check wallet-id__check--' + (c.ok ? 'ok' : 'bad') + '">' +
          '<span class="wallet-id__check-dot"></span>' + escapeHtml(c.label) + '</li>';
      }).join('');
    } else if (checksEl) {
      checksEl.style.display = 'none';
      checksEl.innerHTML = '';
    }
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
    if (dom.mState) {
      dom.mState.textContent = w.hashrate ? 'HASHING' : 'IDLE';
      dom.mState.classList.toggle('metric__value--idle', !w.hashrate);
    }
    if (dom.mStateSub) dom.mStateSub.textContent = w.hashrate ? 'active' : 'connected · no shares';
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

// P0-5 // Pure wallet-rank resolver — single source of truth for the
// COMBINED / DIFF RANK / LOYALTY RANK account panel. The pool account API
// often omits these fields, so the C3 fallback derives an honest label from
// metadata.block_count (blocks found in this pool session). Combined is
// derived from the diff+block signals when the backend sends no score.
// Mirrored in tests/test_app_js_core.js.
function acctRankLabels(acct) {
  acct = acct || {};
  const bc = (acct.metadata && acct.metadata.block_count) || acct.blocks_found || 0;
  const rank = acct.diff_rank || acct.diffRank;
  let diff;
  if (rank && rank !== '\u2014' && rank !== '--') diff = String(rank);
  else if (bc >= 10000) diff = 'TOP 1%';
  else if (bc >= 1000) diff = 'TOP 10%';
  else if (bc >= 100) diff = 'TOP 25%';
  else if (bc > 0) diff = 'ACTIVE';
  else diff = '\u2014';
  const loyaltyRaw = acct.loyalty_rank || acct.loyaltyRank;
  const loyalty = (loyaltyRaw && loyaltyRaw !== '\u2014' && loyaltyRaw !== '--') ? String(loyaltyRaw)
    : (bc > 0 ? 'ACTIVE' : '\u2014');
  const combinedRaw = acct.combined_score || acct.combinedScore;
  let combined;
  if (combinedRaw != null && combinedRaw !== '' && Number(combinedRaw) > 0) {
    combined = Number(combinedRaw) >= 1000 ? String(Math.round(Number(combinedRaw))) : Number(combinedRaw).toFixed(2);
  } else if (diff !== '\u2014' && diff !== 'ACTIVE') {
    combined = 'D:' + diff;
  } else {
    combined = '\u2014';
  }
  return { diff: diff, loyalty: loyalty, combined: combined };
}

function renderAccount(acct) {
  if (!acct) return;
  if (dom.acctLn) dom.acctLn.textContent = acct.ln_address || acct.lightning || '\u2014';
  if (dom.acctTotalDiff) dom.acctTotalDiff.textContent = fmt.diff(acct.total_diff || acct.totalDifficulty);
  if (dom.acctHighestBlock) dom.acctHighestBlock.textContent = acct.metadata?.highest_blockheight != null ? '#' + Number(acct.metadata.highest_blockheight).toLocaleString() : '\u2014';
  // P0-5: single resolver — diff/loyalty/combined with C3 fallback (was
  // duplicated inline; the DashboardCore.updateDataGrids pass then stomped
  // these with '--', hiding every fallback label).
  const labels = acctRankLabels(acct);
  if (dom.acctDiffRank) dom.acctDiffRank.textContent = labels.diff;
  if (dom.acctLoyaltyRank) dom.acctLoyaltyRank.textContent = labels.loyalty;
  if (dom.acctCombined) dom.acctCombined.textContent = labels.combined;
  if (dom.acctBlocksBadge) {
    const bc = acct.metadata?.block_count || acct.blocks_found || 0;
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
    if (dom.nBtcJpy) dom.nBtcJpy.textContent = btc.jpy ? `¥${Number(btc.jpy).toLocaleString()}` : '\u2014';
    if (dom.nBtcKrw) dom.nBtcKrw.textContent = btc.krw ? `₩${Number(btc.krw).toLocaleString()}` : '\u2014';
    if (dom.nBtcCny) dom.nBtcCny.textContent = btc.cny ? `CN¥${Number(btc.cny).toLocaleString()}` : '\u2014';
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
      <li class="alert-item SEVERITY-${escapeHtml(a.severity || 'INFO')}">
        <span class="alert-icon">!</span><span class="alert-msg">${escapeHtml(a.message || '')}</span><span class="alert-time">${fmt.age(a.ts)}</span>
      </li>`).join('');
  }

  function renderEvents(events) {
    if (!dom.eventsTbody) return;
    if (!events || !events.length) { dom.eventsTbody.innerHTML = '<tr><td colspan="5" class="empty">awaiting data\u2026</td></tr>'; return; }
    dom.eventsTbody.innerHTML = events.map(e => `<tr><td>#${escapeHtml(e.block_height || e.block || '\u2014')}</td><td>${escapeHtml(fmt.shortAddr(e.address || ''))}</td><td>${escapeHtml(fmt.diff(e.difficulty))}</td><td>${escapeHtml(fmt.age(e.block_timestamp || e.ts))}</td><td>${e.claimed ? 'YES' : 'NO'}</td></tr>`).join('');
  }

  function renderLeaderboard(lb) {
    if (!dom.lbTbody) return;
    if (!lb || !lb.length) { dom.lbTbody.innerHTML = '<tr><td colspan="6" class="empty">awaiting data\u2026</td></tr>'; return; }
    dom.lbTbody.innerHTML = lb.map((r, i) => `<tr><td>${i+1}</td><td>${escapeHtml(fmt.shortAddr(r.address))}</td><td>${escapeHtml(r.diff_rank || r.diffRank || '\u2014')}</td><td>${escapeHtml(r.loyalty_rank || r.loyalty || '\u2014')}</td><td>${escapeHtml(r.combined_score || r.score || '\u2014')}</td><td>${escapeHtml(r.total_blocks || r.blocks || 0)}</td></tr>`).join('');
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
  // Selected time-range per chart id (default 1h). Persisted so the 15s
  // renderCharts refresh keeps the user's toolbar choice instead of silently
  // resetting every chart back to 1h (audit: range chips were being ignored).
  const _chartRange = {};
  function _fmtChartLabel(t, cfg, id) {
    if (cfg.chart === 'share_dist') return String(t); // histogram bucket labels
    const d = new Date(t);
    const rng = _chartRange[id] || '1h';
    const hm = d.getHours() + ':' + String(d.getMinutes()).padStart(2, '0');
    // Ranges ≥24h span multiple days — include dd/mm so the axis stays honest.
    if (rng === '24h' || rng === '7d' || rng === '30d' || rng === 'all') {
      return String(d.getDate()).padStart(2, '0') + '/' + String(d.getMonth() + 1).padStart(2, '0') + ' ' + hm;
    }
    return hm;
  }
  // The Share-Distribution panel badge was hardcoded to "0 shares" in the HTML
  // and never updated. Reflect the real histogram count from the API.
  function _updateShareDistBadge(cfg, data, values) {
    if (!cfg || cfg.chart !== 'share_dist') return;
    const badge = document.getElementById('share-dist-count-badge');
    if (!badge) return;
    const n = (data && data.count != null) ? data.count : values.reduce((a, b) => a + (Number(b) || 0), 0);
    badge.textContent = `${n} shares`;
  }
  // P0-1: overlay the network target difficulty on the share histogram — a
  // solid purple reference line + readable badge so the operator sees how far
  // shares are from block-winning difficulty at a glance.
  function _applyShareDistTarget(cfg, data, chart) {
    if (!cfg || cfg.chart !== 'share_dist' || !chart) return;
    const bucket = (data && data.target_bucket != null) ? data.target_bucket : null;
    if (bucket != null) {
      chart._annotations = (chart._annotations || []).concat([{ index: bucket, target: true }]);
    }
    const badge = document.getElementById('share-dist-target-badge');
    if (badge) {
      badge.textContent = (data && data.target_diff) ? 'target ' + fmt.diff(data.target_diff) : 'target —';
    }
  }

  async function loadChartData(id) {
    const cfg = CHART_METRICS[id];
    if (!cfg) return;
    try {
      const r = await fetch(`/api/chart-data?chart=${cfg.chart}&range=${_chartRange[id] || '1h'}`);
      if (r.status === 402) { await handleLicenseRequired(r); _chartRange[id] = '1h'; const _tb = document.getElementById('share-dist-target-badge'); if (_tb) _tb.textContent = 'target —'; return; }
      if (!r.ok) return;
      const data = await r.json();
      const chart = charts[id];
      if (!chart) return;
      const rawLabels = (data.labels || []);
      const values = (data.datasets?.[0]?.data || data.datasets?.[0]?.values || []);
      chart.data.labels = rawLabels.map(t => _fmtChartLabel(t, cfg, id));
      chart.data.datasets[0].data = values;
      _updateShareDistBadge(cfg, data, values);
      // Fase 2.1: SMA overlay + shares bar + event annotations
      if (chart.data.datasets[1] && cfg.chart !== 'share_dist') {
        chart.data.datasets[1].data = computeSMA(values, Math.max(3, Math.round(values.length / 10)));
      }
      if (chart.data.datasets[2] && Array.isArray(data.shares)) {
        chart.data.datasets[2].data = data.shares;
        chart.options.scales.y1.display = data.shares.some(s => s > 0);
      }
      chart._annotations = buildChartAnnotations(data.events || [], rawLabels);
      _applyShareDistTarget(cfg, data, chart);
      chart.update('none');
    } catch (e) { /* chart load silently */ }
  }
  // R1: gated chart-data ranges (30d/all) return 402 when the gate is live
  // and no key is present — reset the range to 1h and surface the CTA so the
  // chart never silently renders an empty panel.
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
      return `<div class="timeline-row tf-${escapeHtml((ev.severity||'INFO').toLowerCase())}" data-id="${escapeHtml(String(ev.id))}"><span class="tf-time">${ts}</span><span class="tf-type">${escapeHtml(ev.event_type||'EVENT')}</span><span class="tf-msg">${escapeHtml(ev.message||'')}</span></div>`;
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

  // ── SHARE TIMELINE summary cards + badges ──
  // Pure aggregation (mirrored in tests/test_app_js_core.js): counts
  // SHARE_FOUND / BEST_DIFF_BUMP events inside the 1h / 24h windows from a
  // timeline event list. Used as a client-side fallback when the DB-derived
  // aggregates (event_stats.db_*) are absent — e.g. on the very first poll
  // or after a SQLite write failure. Returns numbers; 0 is a real count.
  function computeTimelineStats(list, nowSec) {
    const now = nowSec || Math.floor(Date.now() / 1000);
    const out = { shares1h: 0, shares24h: 0, bumps24h: 0 };
    if (!list || !list.length) return out;
    list.forEach(e => {
      if (!e) return;
      const ev = _normalizeTimelineEvent(e);
      const t = Number(ev.ts);
      if (!t || !isFinite(t)) return;
      const age = now - t;
      if (age < 0) return; // future ts (clock skew) never counts
      if (ev.event_type === 'SHARE_FOUND') {
        if (age <= 3600) out.shares1h++;
        if (age <= 86400) out.shares24h++;
      } else if (ev.event_type === 'BEST_DIFF_BUMP') {
        if (age <= 86400) out.bumps24h++;
      }
    });
    return out;
  }

  // Latest SHARE_FOUND ts from the timeline list (fallback for LAST SHARE
  // when the session-scoped last_submit_ts is 0 — e.g. right after a server
  // restart, where the DB still holds rows but the in-memory tracker is
  // freshly primed). Only events within the last 24h count, so an old share
  // never claims to be "last".
  function lastShareTsFromTimeline(list, nowSec) {
    const now = nowSec || Math.floor(Date.now() / 1000);
    let latest = 0;
    if (!list || !list.length) return 0;
    list.forEach(e => {
      if (!e) return;
      const ev = _normalizeTimelineEvent(e);
      const t = Number(ev.ts);
      if (!t || !isFinite(t)) return;
      if (ev.event_type !== 'SHARE_FOUND') return;
      const age = now - t;
      if (age < 0 || age > 86400) return;
      if (t > latest) latest = t;
    });
    return latest;
  }

  // Renders the 4 summary cards (LAST SHARE / 1H / 24H / BUMPS 24H) and the
  // 3 header badges from snap.event_stats. DB-derived window counts are
  // authoritative; client-side aggregation of the current timeline list is
  // the fallback. A 0 renders as "0" (a real count) — only a missing value
  // renders as the em-dash placeholder.
  function renderTimelineStats(snap) {
    const es = (snap && snap.event_stats) || {};
    const fb = computeTimelineStats(snap && snap.timeline_recent, Math.floor(Date.now() / 1000));
    const shares1h = es.db_shares_last_hour != null ? Number(es.db_shares_last_hour) : fb.shares1h;
    const shares24h = es.db_shares_last_day != null ? Number(es.db_shares_last_day) : fb.shares24h;
    const bumps24h = es.db_best_diffs_last_day != null ? Number(es.db_best_diffs_last_day) : fb.bumps24h;
    if (dom.tStatLastShare) {
      const lastTs = es.last_submit_ts || lastShareTsFromTimeline(snap && snap.timeline_recent, Math.floor(Date.now() / 1000));
      if (lastTs) {
        const d = new Date(Number(lastTs) * 1000);
        dom.tStatLastShare.textContent =
          String(d.getHours()).padStart(2, '0') + ':' +
          String(d.getMinutes()).padStart(2, '0') + ':' +
          String(d.getSeconds()).padStart(2, '0');
      } else {
        dom.tStatLastShare.textContent = '\u2014';
      }
    }
    if (dom.tStat1h) dom.tStat1h.textContent = String(shares1h);
    if (dom.tStat24h) dom.tStat24h.textContent = String(shares24h);
    if (dom.tStatBumps) dom.tStatBumps.textContent = String(bumps24h);
    if (dom.timelineSharesBadge) dom.timelineSharesBadge.textContent = String(es.session_share_count || 0);
    if (dom.timelineBumpsBadge) dom.timelineBumpsBadge.textContent = String(es.session_best_diff_bumps || 0) + ' best';
    if (dom.timelineRateBadge) {
      const rate = Number(es.rolling_shares_per_hour);
      dom.timelineRateBadge.textContent = (es.rolling_shares_per_hour != null && isFinite(rate))
        ? rate.toFixed(1) + '/h'
        : '\u2014/h';
    }
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
            '<span class="lc-ticker-diff">' + escapeHtml(e.share_diff_str || dash) + '</span>' +
            '<span class="lc-ticker-gap">\u0394' + escapeHtml(e.gap || '\u2014') + 's</span>' +
            '<span class="lc-ticker-hr">' + escapeHtml(e.instantaneous_hr_str || dash) + '</span>' +
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
    const cur = (SETTINGS_CACHE.data?.active_currency?.value) || "USD"; const symMap = {USD:"$",BRL:"R$",EUR:"€",GBP:"£",JPY:"¥",KRW:"₩",CNY:"CN¥"}; const sym = symMap[cur] || "$";
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
        // Honest telemetry: without solo data the break-even shows '—', so
        // the sub-label must NOT claim 'to block' (that would imply solo
        // stats rendered when they didn't — the old copy misled the UI).
        dom.pBreakeven.textContent = '\u2014';
        if (dom.pBreakevenSub) dom.pBreakevenSub.textContent = 'no data';
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
    // Issue #50 (audit): the solo CARDS panel uses dedicated ids (renamed
    // from the duplicated #solo-expected-time/#solo-blocks-year in the
    // profit strip) so getElementById never hits the wrong node.
    setAll('solo-expected-time', prox.expected_time_human || dash);
    setAll('solo-blocks-year', prox.blocks_per_year != null ? prox.blocks_per_year.toFixed(2) : dash);
    setAll('solo-cards-expected-time', prox.expected_time_human || dash);
    setAll('solo-cards-blocks-year', prox.blocks_per_year != null ? prox.blocks_per_year.toFixed(2) : dash);
    setAll('solo-best-diff', prox.all_time_best_diff_str || dash);
    setAll('solo-status-badge', prox.insufficient_data ? '—' : (prox.best_diff_raw ? 'READY' : '—'));
  }

  function renderMilestones(list) {
    if (!dom.badgesStrip) return;
    if (!list || !list.length) { dom.badgesStrip.innerHTML = '<div class="empty">awaiting data</div>'; return; }
    dom.badgesStrip.innerHTML = list.map(m => `<div class="badge-card"><div class="badge-card__tier">${escapeHtml(m.tier)}</div><div class="badge-card__label">${escapeHtml(m.label)}</div></div>`).join('');
  }

  // ── WHAT-IF difficulty simulator (UX audit · Módulo_05) ──────────────
  // Pure math + small state. `_bhBase` captures the LAST snapshot's Block
  // Hunt values so the simulator recomputes instantly on slider input
  // (no poll round-trip) and re-renders with the same slider position
  // after every snapshot. Mirrored in tests/test_app_js_core.js (SUITE 33).
  let _bhBase = null;          // {netDiff, bestDiff, pBlock, expectedTime, cumulativeP, shares}
  let _bhSliderEl = null;

  function _bhSliderValue() {
    if (!_bhSliderEl) _bhSliderEl = document.getElementById('bh-whatif-slider');
    return _bhSliderEl ? Number(_bhSliderEl.value || 0) : 0;
  }

  // Pure: given the base Block Hunt values + a difficulty shift %, return
  // the simulated metrics. Difficulty scaling is linear for expected time
  // (Poisson: E[time] = diff·2³² / hashrate) and inverse for P(block)/share
  // (p = bestDiff / diff). Cumulative P re-derives from the shifted per-share
  // probability and the session's share count.
  function simulateDifficultyShift(base, pct) {
    base = base || {};
    const mult = 1 + (Number(pct) || 0) / 100;
    const netDiff = base.netDiff > 0 ? base.netDiff * mult : 0;
    let pBlock = null;
    if (base.bestDiff > 0 && netDiff > 0) pBlock = base.bestDiff / netDiff;
    else if (base.pBlock != null && base.netDiff > 0 && netDiff > 0) pBlock = base.pBlock * (base.netDiff / netDiff);
    const expectedTime = base.expectedTime > 0 ? base.expectedTime * mult : (base.expectedTime || 0);
    const distance = base.bestDiff > 0 && netDiff > 0 ? netDiff / base.bestDiff : 0;
    let cumulativeP = base.cumulativeP;
    if (base.shares > 0 && pBlock != null && pBlock > 0) cumulativeP = 1 - Math.pow(1 - pBlock, base.shares);
    return { shiftPct: Number(pct) || 0, netDiff, pBlock, expectedTime, distance, cumulativeP };
  }

  // Render the WHAT-IF readouts from the current slider position. Honest
  // empty state: without a base netDiff everything shows an em-dash (the
  // panel renders before the first snapshot has real values).
  function _bhRenderWhatIf() {
    const badge = document.getElementById('bh-whatif-badge');
    const diffEl = document.getElementById('bh-whatif-diff');
    const pEl = document.getElementById('bh-whatif-pblock');
    const etEl = document.getElementById('bh-whatif-etime');
    const cumEl = document.getElementById('bh-whatif-cum');
    if (!badge || !diffEl) return;
    const pct = _bhSliderValue();
    badge.textContent = (pct > 0 ? '+' : '') + pct + '%';
    if (!_bhBase || !_bhBase.netDiff) {
      diffEl.textContent = '\u2014'; pEl.textContent = '\u2014'; etEl.textContent = '\u2014'; cumEl.textContent = '\u2014';
      return;
    }
    const sim = simulateDifficultyShift(_bhBase, pct);
    diffEl.textContent = fmt.diff(sim.netDiff);
    pEl.textContent = sim.pBlock != null ? (sim.pBlock * 100).toFixed(8) + '%' : '\u2014';
    etEl.textContent = sim.expectedTime ? fmt.secsToHuman(sim.expectedTime) : '\u2014';
    cumEl.textContent = sim.cumulativeP != null ? (sim.cumulativeP * 100).toFixed(4) + '%' : '\u2014';
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

    // WHAT-IF simulator base: capture the current snapshot's values so the
    // slider recomputes from fresh data on every poll while preserving the
    // operator's chosen shift %. Shares feed the cumulative-P re-derivation.
    _bhBase = {
      netDiff,
      bestDiff,
      pBlock: pBlock != null ? Number(pBlock) : null,
      expectedTime: typeof expectedTime === 'number' ? expectedTime : 0,
      cumulativeP: finalCumP != null ? Number(finalCumP) : null,
      shares: (prox.live_calc && prox.live_calc.session_totals && prox.live_calc.session_totals.shares_so_far) || 0,
    };
    _bhRenderWhatIf();
  }

  // ── Hashrate Market render ──
  // Backend schema: offers carry `price_per_th_day` (BTC/TH/day, often ~1e-8..1e-10).
  // The old field name `price_btc_per_th_day` never exists in the payload, which
  // made every card render '—'. `is_best` is NOT sent by the backend, so the
  // best offer is derived client-side from the highest metrics.score (ROI),
  // falling back to the lowest valid price_per_th_day.
  let _mktFilter = 'all';
  let _mktOffers = [];
  let _mktGridRetried = false;  // retry guard for Chart.js CDN blocking DOM parse
  let _mktBtcUsd = null;  // BTC/USD from snapshot — for the USD/TH/d line on cards
  let _mktAffiliate = null;  // market_data.affiliate {provider,url,...} — one-click BUY on the offer card
  let _mktTrendLoaded = false;  // lazy: /api/market/trend fetched on first module activation
  let _mktInstitutional = null;  // HashratePulse institutional view {regime, snapshot, venues, notes}
  let _adminLoaded = false;  // lazy: fetch once per session (admin-gated)

  // ── Admin (CFO/CRO) — pool health + PRO funnel + LTV/CAC ─────────────
  function _setAdminText(id, text) {
    const el = document.getElementById(id);
    if (el) el.textContent = text;
  }

  // ── Admin audit trail — pure builders (mirrored in JS core tests) ─────
  // ISO week key in UTC (Monday-start, deterministic — no TZ drift).
  // ts <= 0 (missing/epoch) → '' so entries without a real date never
  // bucket into a fake '1970-W01' week (symmetric with the backend's
  // "ts=0 has no place in a windowed audit" rule).
  function adminAuditIsoWeekKey(ts) {
    const n = Number(ts);
    if (!isFinite(n) || n <= 0) return '';
    const d = new Date(n * 1000);
    if (isNaN(d.getTime())) return '';
    const day = (d.getUTCDay() + 6) % 7;         // Mon=0 … Sun=6
    const thursday = new Date(Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate() + 3 - day));
    const firstThu = new Date(Date.UTC(thursday.getUTCFullYear(), 0, 4));
    const week = 1 + Math.round((thursday - firstThu) / (7 * 86400 * 1000));
    return thursday.getUTCFullYear() + '-W' + String(week).padStart(2, '0');
  }
  // decisions → weekly buckets {labels: ['2026-W31', …], counts: [n, …]}
  function buildAdminAuditWeekly(decisions) {
    const buckets = {};
    (decisions || []).forEach(function (d) {
      const k = adminAuditIsoWeekKey(d && d.ts);
      if (!k) return;
      buckets[k] = (buckets[k] || 0) + 1;
    });
    const labels = Object.keys(buckets).sort();
    return { labels: labels, counts: labels.map(function (k) { return buckets[k]; }) };
  }
  // feature_alert (Issue #163) → safe banner payload {feature, count,
  // sharePct, minPct, active}; no HTML, numbers guarded against NaN.
  function buildFeatureAlert(featureAlert) {
    if (!featureAlert || featureAlert.share_pct == null) {
      return { active: false, feature: '', count: 0, sharePct: 0, minPct: 50 };
    }
    return {
      active: true,
      feature: String(featureAlert.feature || 'unknown'),
      count: Number(featureAlert.count) || 0,
      sharePct: Number(featureAlert.share_pct) || 0,
      minPct: Number(featureAlert.min_pct) || 50,
    };
  }
  // paywall_by_feature (Issue #158) → top-N display rows {feature, count,
  // pct} sorted desc; safe strings, no HTML.
  function buildFeatureBreakdown(paywallByFeature) {
    const rows = (paywallByFeature || []).map(function (f) {
      return { feature: f.feature || 'unknown', count: Number(f.count) || 0 };
    }).sort(function (a, b) { return b.count - a.count; });
    const total = rows.reduce(function (s, r) { return s + r.count; }, 0) || 1;
    return rows.map(function (r) {
      return { feature: r.feature, count: r.count, pct: Math.round(r.count / total * 100) };
    });
  }
  // cohort buckets (Issue #157) → rows for the LTV-real table: safe numbers,
  // no HTML, ready for innerHTML via escapeHtml on the render side.
  function _cohortNum(v) {
    const n = Number(v);
    return Number.isFinite(n) ? n : 0;
  }
  function buildCohortRows(cohorts) {
    return (cohorts || []).map(function (c) {
      return {
        month: c.cohort_month || '',
        subs: _cohortNum(c.subscriptions),
        renewals: _cohortNum(c.renewals),
        revenue: _cohortNum(c.revenue_usd),
        ltv: _cohortNum(c.ltv_usd),
        m1: _cohortNum(c.retention_m1_pct),
        m3: _cohortNum(c.retention_m3_pct),
        m6: _cohortNum(c.retention_m6_pct),
        m12: _cohortNum(c.retention_m12_pct),
      };
    });
  }
  // weekly funnel buckets (Issue #156) → trend series for the admin chart.
  function buildFunnelTrend(weekly) {
    const labels = [], paywall = [], convRate = [];
    (weekly || []).forEach(function (b) {
      labels.push(b.week || '');
      const s = b.stages || {};
      paywall.push(Number(s.paywall_view) || 0);
      convRate.push(b.conversion_rate_pct != null ? Number(b.conversion_rate_pct) : 0);
    });
    return { labels: labels, paywall: paywall, convRate: convRate };
  }
  // decisions → filtered by tenant + verdict ('all'/'' = no filter).
  function filterAdminAuditDecisions(decisions, tenant, verdict) {
    return (decisions || []).filter(function (d) {
      if (tenant && (d.tenant_id || 'default') !== tenant) return false;
      if (verdict && (d.verdict || 'unknown') !== verdict) return false;
      return true;
    });
  }
  // Verdict → CSS badge class + label (visual severity ladder).
  function adminAuditVerdictMeta(verdict) {
    const map = {
      improved: { cls: 'admin-audit__verdict--improved', label: 'IMPROVED' },
      worse: { cls: 'admin-audit__verdict--worse', label: 'WORSE' },
      same: { cls: 'admin-audit__verdict--same', label: 'SAME' },
      avoided: { cls: 'admin-audit__verdict--avoided', label: 'AVOIDED' },
      revoked: { cls: 'admin-audit__verdict--revoked', label: 'REVOKED' },
      no_before: { cls: 'admin-audit__verdict--mute', label: 'NO BEFORE' },
    };
    return map[verdict] || { cls: 'admin-audit__verdict--mute', label: String(verdict || 'unknown').toUpperCase() };
  }

  let _adminAuditDecisions = [];      // last payload (for client-side filters)
  let _adminAuditChart = null;        // Chart.js instance (destroy before recreate)

  async function fetchAdminData() {
    if (_adminLoaded) return;
    const errEl = document.getElementById('admin-error');
    const gate = document.getElementById('admin-gate-badge');
    try {
      // Pool health — no auth needed for localhost/operator-key admin routes.
      const [sessionsResp, convResp, auditResp, metricsResp, docsResp] = await Promise.all([
        fetch('/api/admin/sessions', { headers: { 'X-Requested-With': 'fetch' } }),
        fetch('/api/admin/conversion?weeks=8', { headers: { 'X-Requested-With': 'fetch' } }),
        fetch('/api/admin/rentals/accepted-recos?limit=1000', { headers: { 'X-Requested-With': 'fetch' } }),
        fetch('/api/admin/pool-metrics?hours=24', { headers: { 'X-Requested-With': 'fetch' } }),
        fetch('/api/admin/docs-feedback', { headers: { 'X-Requested-With': 'fetch' } }),
      ]);
      if (sessionsResp.status === 403 || convResp.status === 403 || auditResp.status === 403 || metricsResp.status === 403 || docsResp.status === 403) {
        if (gate) gate.textContent = 'restricted';
        if (errEl) {
          errEl.hidden = false;
          errEl.textContent = 'Admin access required — endpoint só responde de localhost ou com a API key do operador (X-API-Key).';
        }
        _adminLoaded = true;  // don't re-hammer a 403
        return;
      }
      if (gate) gate.textContent = 'ok';
      const sessions = sessionsResp.ok ? await sessionsResp.json() : {};
      const conv = convResp.ok ? await convResp.json() : {};
      const audit = auditResp.ok ? await auditResp.json() : {};
      const metrics = metricsResp.ok ? await metricsResp.json() : {};
      const docsFb = docsResp.ok ? await docsResp.json() : {};
      _renderAdmin(sessions, conv, audit, metrics, docsFb);
    } catch (e) {
      if (errEl) { errEl.hidden = false; errEl.textContent = 'admin fetch error: ' + e.message; }
    }
  }
  function _renderAdmin(sessions, conv, audit, metrics, docsFb) {
    _renderAdminMetrics(metrics || {});
    _renderAdminAudit(audit);
    _renderAdminAutoExclusions(audit);
    _renderAdminDocsFeedback(docsFb || {});
    const pool = sessions.pool || {};
    _setAdminText('admin-sessions', pool.sessions_active != null ? pool.sessions_active : '—');
    _setAdminText('admin-polls-per-sec', pool.polls_per_sec != null ? pool.polls_per_sec : '—');
    _setAdminText('admin-queue', pool.queue_pending != null ? pool.queue_pending : '—');
    _setAdminText('admin-workers', pool.workers_alive != null ? (pool.workers_alive + '/' + (pool.pool_size || '?')) : '—');
    _setAdminText('admin-uptime', pool.uptime_secs ? Math.round(pool.uptime_secs / 60) + 'm' : '—');
    // Auto-exclude alerts by path (Issue #112) — total · s<sweep>/p<painel>.
    const axCounters = pool.auto_exclude_alerts || {};
    _setAdminText('admin-autoex-alerts',
      (axCounters.total != null ? axCounters.total : '—') +
      ' · s' + (axCounters.sweep != null ? axCounters.sweep : 0) +
      '/p' + (axCounters.panel != null ? axCounters.panel : 0));
    const stall = document.getElementById('admin-stall');
    if (stall) {
      stall.hidden = !pool.stalled;
      stall.textContent = pool.stalled ? '⚠ POOL STALLED — workers vivos mas sem polls completando. Reiniciar.' : '';
    }
    // Funnel drop-off + LTV/CAC
    const funnel = (conv.funnel || {});
    const econ = (conv.economics || {});
    const drops = {};
    (funnel.drop_off || []).forEach(function(d) { drops[d.from + '->' + d.to] = d.loss_pct; });
    _setAdminText('admin-drop-paywall-modal', _pct(drops['paywall_view->modal_open']));
    _setAdminText('admin-drop-modal-checkout', _pct(drops['modal_open->checkout_start']));
    _setAdminText('admin-drop-checkout-paid', _pct(drops['checkout_start->paid']));
    _setAdminText('admin-conv-rate', _pct(funnel.conversion_rate_pct));
    // Issue #155: per-user funnel attribution (events carrying a funnel_id).
    _setAdminText('admin-funnel-sessions', funnel.sessions_count != null ? funnel.sessions_count : '—');
    _setAdminText('admin-funnel-session-conv', funnel.session_conversion_rate_pct != null ? _pct(funnel.session_conversion_rate_pct) : '—');
    // Issue #157 (18-C): real cohort LTV (renewals) vs the price×months
    // estimate — the tag tells the CFO which number they're looking at.
    const isReal = econ.ltv_source === 'cohort_real';
    const ltvTag = document.getElementById('admin-ltv-source');
    if (ltvTag) {
      ltvTag.textContent = isReal ? 'real' : 'est';
      ltvTag.classList.toggle('kpi-card__tag--real', isReal);
    }
    _setAdminText('admin-ltv', econ.ltv_usd != null ? '$' + econ.ltv_usd : '—');
    _setAdminText('admin-cac', econ.cac_usd != null ? '$' + econ.cac_usd : 'no spend data');
    _setAdminText('admin-ltv-cac', econ.ltv_cac_ratio != null ? econ.ltv_cac_ratio : '—');
    _setAdminText('admin-payback', econ.payback_months != null ? econ.payback_months : '—');
    _renderAdminCohorts(econ);
    // Stage counts list — plus per-stage session counts when available.
    const list = document.getElementById('admin-funnel-list');
    if (list) {
      const stages = funnel.stages || {};
      const sStages = funnel.session_stages || {};
      const rows = Object.keys(stages).map(function(k) {
        const sess = sStages[k] != null ? ' · ' + String(sStages[k]) + ' sessões' : '';
        return '<li class="alert-item"><span class="alert-item__cat">' + escapeHtml(k) + '</span><span class="alert-item__msg">' + escapeHtml(String(stages[k])) + escapeHtml(sess) + '</span></li>';
      });
      list.innerHTML = rows.length ? rows.join('') : '<li class="alert-empty">sem eventos no período</li>';
    }
    // Feature breakdown (Issue #158 — 18-D): where the free tier blocks.
    _renderAdminFeatures(funnel);
    // Feature over-concentration (Issue #163): the #1 friction point.
    _renderAdminFeatureAlert(conv.feature_alert || null);
    // Weekly trend (Issue #156 — 18-B): paywall_view × conversion rate.
    _renderAdminFunnelTrend(conv.weekly || []);
  }

  // ── Learning FAQ loop (Issue #19) — docs feedback summary ─────────────
  function _renderAdminDocsFeedback(fb) {
    const wrap = document.getElementById('admin-docs-feedback');
    const table = document.getElementById('admin-docs-feedback-table');
    const recurringEl = document.getElementById('admin-docs-recurring');
    const metaEl = document.getElementById('admin-docs-feedback-meta');
    if (!table && !recurringEl && !metaEl) return;
    const rows = fb.sections || [];
    const questions = fb.recurring_questions || [];
    if (metaEl) {
      metaEl.textContent = fb.total_votes
        ? (fb.total_votes + ' votos · ' + (fb.overall_helpful_pct != null ? fb.overall_helpful_pct + '% útil' : '—'))
        : 'sem votos ainda — widget no fim de cada seção do DOCS / GUIDE';
    }
    const tbody = table && table.querySelector('tbody');
    if (tbody) {
      tbody.innerHTML = rows.length ? rows.map(function(s) {
        const pct = s.helpful_pct != null ? docsFeedbackPct(s.helpful, s.total) + '%' : '—';
        return '<tr>' +
          '<td>' + escapeHtml(docsFeedbackSectionLabel(s.section_id)) + '</td>' +
          '<td>' + escapeHtml(String(s.total)) + '</td>' +
          '<td>' + escapeHtml(String(s.helpful)) + '</td>' +
          '<td>' + escapeHtml(String(s.not_helpful)) + '</td>' +
          '<td>' + escapeHtml(String(pct)) + '</td>' +
          '</tr>';
      }).join('') : '<tr><td colspan="5" class="alert-empty">sem votos ainda</td></tr>';
    }
    if (recurringEl) {
      recurringEl.innerHTML = questions.length ? questions.map(function(q) {
        return '<li class="alert-item"><span class="alert-item__cat">' + escapeHtml(docsFeedbackSectionLabel(q.section_id)) + '</span><span class="alert-item__msg">' + escapeHtml(q.comment) + ' <em class="admin-docs-feedback__tenant">— ' + escapeHtml(q.tenant) + '</em></span></li>';
      }).join('') : '<li class="alert-empty">nenhuma pergunta recorrente ainda — as perguntas do widget (👎) aparecem aqui para virar FAQ</li>';
    }
    if (wrap) wrap.hidden = false;
  }

  // ── Feature over-concentration banner (Issue #163) ────────────────────
  function _renderAdminFeatureAlert(featureAlert) {
    const el = document.getElementById('admin-feature-alert');
    if (!el) return;
    const a = buildFeatureAlert(featureAlert);
    if (!a.active) { el.hidden = true; el.textContent = ''; return; }
    el.hidden = false;
    el.textContent = '⚠ FEATURE TRAVA DEMAIS — ' + a.feature + ' = ' +
      a.sharePct + '% dos paywalls (threshold ' + a.minPct + '%). ' +
      'Investigar UX/onboarding desta feature.';
  }

  // ── Feature breakdown (Issue #158 — 18-D) ─────────────────────────────
  function _renderAdminFeatures(funnel) {
    const listEl = document.getElementById('admin-feature-list');
    if (!listEl) return;
    const rows = buildFeatureBreakdown((funnel && funnel.paywall_by_feature) || []);
    if (!rows.length) {
      listEl.innerHTML = '<li class="alert-empty">sem paywalls no período</li>';
      return;
    }
    listEl.innerHTML = rows.map(function (r) {
      return '<li class="alert-item">' +
        '<span class="alert-item__cat">' + escapeHtml(r.feature) + '</span>' +
        '<span class="alert-item__msg">' + escapeHtml(String(r.count)) + ' · ' + escapeHtml(String(r.pct)) + '%</span>' +
        '</li>';
    }).join('');
  }

  // ── Funnel weekly trend chart (Issue #156 — 18-B) ──────────────────────
  let _adminFunnelTrendChart = null;

  function _renderAdminFunnelTrend(weekly) {
    const wrap = document.getElementById('admin-funnel-trend-wrap');
    const canvas = document.getElementById('admin-funnel-trend-chart');
    const empty = document.getElementById('admin-funnel-trend-empty');
    const meta = document.getElementById('admin-funnel-trend-meta');
    if (!wrap || !canvas) return;
    const trend = buildFunnelTrend(weekly);
    if (_adminFunnelTrendChart) { _adminFunnelTrendChart.destroy(); _adminFunnelTrendChart = null; }
    if (!trend.labels.length) {
      wrap.hidden = true;
      if (empty) empty.hidden = false;
      if (meta) meta.textContent = '';
      return;
    }
    wrap.hidden = false;
    if (empty) empty.hidden = true;
    if (meta) {
      meta.textContent = trend.labels.length + ' semanas · ' + trend.labels[0] + ' → ' + trend.labels[trend.labels.length - 1];
    }
    if (typeof Chart === 'undefined') return;
    _adminFunnelTrendChart = new Chart(canvas.getContext('2d'), {
      type: 'line',
      data: {
        labels: trend.labels,
        datasets: [
          { label: 'paywall_view', data: trend.paywall, borderColor: 'rgb(6,214,240)', backgroundColor: 'rgba(6,214,240,0.06)', tension: 0.3, pointRadius: 2, fill: true, yAxisID: 'y' },
          { label: 'conversion %', data: trend.convRate, borderColor: 'rgb(0,200,83)', backgroundColor: 'transparent', tension: 0.3, pointRadius: 2, borderDash: [4, 2], yAxisID: 'y1' },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: 'index', intersect: false },
        scales: {
          x: { ticks: { color: '#5E5952', font: { size: 9 }, maxRotation: 0 }, grid: { display: false } },
          y: { beginAtZero: true, position: 'left', title: { display: true, text: 'paywall', color: 'rgb(6,214,240)', font: { size: 8 } }, ticks: { color: '#5E5952', font: { size: 9 }, precision: 0 }, grid: { color: 'rgba(94,89,82,0.10)' } },
          y1: { beginAtZero: true, position: 'right', title: { display: true, text: 'conv %', color: 'rgb(0,200,83)', font: { size: 8 } }, ticks: { color: '#5E5952', font: { size: 9 } }, grid: { display: false } },
        },
      },
    });
  }

  // ── LTV real por coorte (Issue #157 — 18-C) ───────────────────────────
  function _renderAdminCohorts(econ) {
    const wrap = document.getElementById('admin-cohort-wrap');
    const tbody = document.getElementById('admin-cohort-tbody');
    const empty = document.getElementById('admin-cohort-empty');
    const src = document.getElementById('admin-cohort-source');
    if (!wrap || !tbody) return;
    const rows = buildCohortRows((econ && econ.cohorts) || []);
    const isReal = econ && econ.ltv_source === 'cohort_real';
    if (src) src.textContent = isReal ? 'cohort real' : 'estimativa';
    if (!rows.length) {
      wrap.hidden = true;
      if (empty) empty.hidden = false;
      return;
    }
    wrap.hidden = false;
    if (empty) empty.hidden = true;
    tbody.innerHTML = rows.map(function (r) {
      return '<tr>' +
        '<td>' + escapeHtml(r.month) + '</td>' +
        '<td>' + escapeHtml(String(r.subs)) + '</td>' +
        '<td>' + escapeHtml(String(r.renewals)) + '</td>' +
        '<td>$' + escapeHtml(String(r.revenue.toFixed(2))) + '</td>' +
        '<td>$' + escapeHtml(String(r.ltv.toFixed(2))) + '</td>' +
        '<td>' + escapeHtml(String(r.m1.toFixed(1))) + '%</td>' +
        '<td>' + escapeHtml(String(r.m3.toFixed(1))) + '%</td>' +
        '<td>' + escapeHtml(String(r.m6.toFixed(1))) + '%</td>' +
        '<td>' + escapeHtml(String(r.m12.toFixed(1))) + '%</td>' +
        '</tr>';
    }).join('');
  }

  function _pct(v) {
    if (v === undefined || v === null) return '—';
    return Number(v).toFixed(1) + '%';
  }

  // ── Pool metric trends (Issue #17) — persistent 60s sampler history ────
  let _adminMetricsChart = null;  // Chart.js instance (destroy before recreate)

  function _renderAdminMetrics(metrics) {
    const wrap = document.getElementById('admin-metrics');
    const canvas = document.getElementById('admin-metrics-chart');
    const empty = document.getElementById('admin-metrics-empty');
    if (!wrap || !canvas || typeof Chart === 'undefined') return;
    const points = (metrics && metrics.points) || [];
    if (!points.length) {
      wrap.hidden = false;
      if (empty) empty.hidden = false;
      if (_adminMetricsChart) { _adminMetricsChart.destroy(); _adminMetricsChart = null; }
      return;
    }
    if (_adminMetricsChart) { _adminMetricsChart.destroy(); _adminMetricsChart = null; }
    if (empty) empty.hidden = true;

    var labels = points.map(function (p) {
      var d = new Date(Number(p.ts) * 1000);
      if (isNaN(d.getTime())) return '—';
      return d.getHours().toString().padStart(2, '0') + ':' + d.getMinutes().toString().padStart(2, '0');
    });
    var sessions = points.map(function (p) { return p.sessions_active; });
    var pps = points.map(function (p) {
      return (p.polls_per_sec != null && p.polls_per_sec > 0) ? p.polls_per_sec : null;
    });
    var queue = points.map(function (p) {
      return (p.queue_pending != null && p.queue_pending > 0) ? p.queue_pending : null;
    });

    wrap.hidden = false;
    _adminMetricsChart = new Chart(canvas.getContext('2d'), {
      type: 'line',
      data: {
        labels: labels,
        datasets: [
          { label: 'Sessions ativas', data: sessions, borderColor: 'rgb(6,214,240)', backgroundColor: 'rgba(6,214,240,0.06)', tension: 0.3, pointRadius: 0, fill: true, yAxisID: 'y' },
          { label: 'Polls/seg', data: pps, borderColor: 'rgb(186,133,224)', backgroundColor: 'transparent', tension: 0.3, pointRadius: 0, borderDash: [4, 2], yAxisID: 'y1' },
          { label: 'Queue pendente', data: queue, borderColor: 'rgb(255,160,0)', backgroundColor: 'transparent', tension: 0.3, pointRadius: 0, borderDash: [2, 3], yAxisID: 'y1' },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: 'index', intersect: false },
        plugins: { legend: { labels: { color: '#5E5952', font: { size: 9 }, boxWidth: 12 } } },
        scales: {
          x: { ticks: { color: '#5E5952', font: { size: 9 }, maxTicksLimit: 12, maxRotation: 0 }, grid: { color: 'rgba(94,89,82,0.10)' } },
          y: { type: 'linear', position: 'left', title: { display: true, text: 'sessions', color: 'rgb(6,214,240)' }, ticks: { color: '#5E5952', font: { size: 9 }, precision: 0 }, grid: { color: 'rgba(94,89,82,0.08)' } },
          y1: { type: 'linear', position: 'right', title: { display: true, text: 'pps / queue', color: 'rgb(186,133,224)' }, ticks: { color: '#5E5952', font: { size: 9 } }, grid: { display: false } },
        },
      },
    });
  }

  // ── Admin audit trail — table + filters + weekly mini-chart ───────────
  function _fmtAdminTs(ts) {
    if (!ts) return '—';
    const d = new Date(Number(ts) * 1000);
    if (isNaN(d.getTime())) return '—';
    return d.toISOString().replace('T', ' ').slice(0, 16) + ' UTC';
  }
  function _fmtDeliveryPct(v) {
    if (v === undefined || v === null || v === '') return '—';
    return Number(v).toFixed(1) + '%';
  }
  function _renderAdminAudit(audit) {
    const wrap = document.getElementById('admin-audit');
    const tbody = document.getElementById('admin-audit-tbody');
    if (!wrap || !tbody) return;
    const decisions = (audit && audit.decisions) || [];
    _adminAuditDecisions = decisions;
    wrap.hidden = false;
    // Tenant filter options (distinct, sorted, 'default' first).
    const tenantSel = document.getElementById('admin-audit-tenant');
    if (tenantSel) {
      const tenants = Array.from(new Set(decisions.map(function (d) { return d.tenant_id || 'default'; })));
      tenants.sort(function (a, b) { return a === 'default' ? -1 : (b === 'default' ? 1 : a.localeCompare(b)); });
      const prev = tenantSel.value;
      tenantSel.innerHTML = '<option value="">all</option>' + tenants.map(function (t) {
        return '<option value="' + escapeHtml(t) + '">' + escapeHtml(t) + '</option>';
      }).join('');
      if (prev && tenants.indexOf(prev) !== -1) tenantSel.value = prev;
    }
    // Verdict filter options (distinct, ladder order).
    const verdictSel = document.getElementById('admin-audit-verdict');
    if (verdictSel) {
      const order = ['worse', 'improved', 'same', 'avoided', 'revoked', 'no_before'];
      const seen = {};
      decisions.forEach(function (d) { seen[d.verdict || 'unknown'] = true; });
      const verdicts = order.filter(function (v) { return seen[v]; })
        .concat(Object.keys(seen).filter(function (v) { return order.indexOf(v) === -1; }).sort());
      const prev = verdictSel.value;
      verdictSel.innerHTML = '<option value="">all</option>' + verdicts.map(function (v) {
        return '<option value="' + escapeHtml(v) + '">' + escapeHtml(v) + '</option>';
      }).join('');
      if (prev && verdicts.indexOf(prev) !== -1) verdictSel.value = prev;
    }
    _renderAdminAuditTable();
    _renderAdminAuditChart(buildAdminAuditWeekly(decisions));
  }
  // Auto-exclusion history (global, WHEN + CAUSE): compact items — the pilot's
  // auto-exclusions across ALL tenants with the delivery snapshot + the rule
  // that fired. Fed by the same accepted-recos admin route (auto_exclusions).
  function _renderAdminAutoExclusions(audit) {
    const wrap = document.getElementById('admin-autoex');
    const list = document.getElementById('admin-autoex-list');
    if (!wrap || !list) return;
    const ex = ((audit || {}).auto_exclusions || {}).exclusions || [];
    if (!ex.length) { wrap.hidden = true; return; }
    wrap.hidden = false;
    const meta = document.getElementById('admin-autoex-meta');
    if (meta) meta.textContent = ex.length + ' auto-exclus' + (ex.length === 1 ? 'ão' : 'ões') + ' (global)';
    list.innerHTML = ex.map(function (x) {
      const grade = x.grade
        ? '<span class="admin-autoex__grade admin-autoex__grade--' + escapeHtml(String(x.grade)) + '">' + escapeHtml(String(x.grade)) + '</span>' : '';
      const when = x.ts ? new Date(Number(x.ts) * 1000).toLocaleDateString('pt-BR') : '—';
      const tenant = x.tenant_id && x.tenant_id !== 'default'
        ? escapeHtml(String(x.tenant_id))
        : '<span class="admin-autoex__tenant">default</span>';
      const delivery = x.delivery_pct != null ? escapeHtml(Number(x.delivery_pct).toFixed(1) + '%') : '—';
      const samples = x.samples != null ? escapeHtml(String(x.samples)) + ' amostras' : '—';
      return '<div class="admin-autoex__item">' +
        '<div class="admin-autoex__name">' + escapeHtml(String(x.name || x.rig_id)) + grade + '</div>' +
        '<div class="admin-autoex__sub">' + tenant + ' · ' + escapeHtml(when) + ' · entrega ' + delivery + ' · ' + samples + '</div>' +
        '<div class="admin-autoex__cause" title="causa da exclusão">' + escapeHtml(String(x.cause || 'sub-entrega')) + '</div>' +
        '</div>';
    }).join('');
    _renderAdminAutoExclusionAggs(audit);
  }

  // Auto-exclusion CONCENTRATION (padrão global do piloto, Issue #106):
  // grouped by tenant (who triggers the pilot most) and by régua (how
  // aggressive each tenant's floor/min is), from the SAME shared pass as the
  // history list (auto_exclusion_aggregates in the accepted-recos payload).
  function _renderAdminAutoExclusionAggs(audit) {
    const aggWrap = document.getElementById('admin-autoex-agg');
    const byTenant = document.getElementById('admin-autoex-by-tenant');
    const byRule = document.getElementById('admin-autoex-by-rule');
    if (!aggWrap || !byTenant || !byRule) return;
    const agg = ((audit || {}).auto_exclusion_aggregates) || {};
    const tenants = agg.by_tenant || [];
    const rules = agg.by_rule || [];
    if (!tenants.length && !rules.length) { aggWrap.hidden = true; return; }
    aggWrap.hidden = false;
    byTenant.innerHTML = tenants.map(function (t) {
      const tid = t.tenant_id === 'default'
        ? '<span class="admin-autoex__tenant">default</span>'
        : escapeHtml(String(t.tenant_id));
      const grade = t.top_grade
        ? '<span class="admin-autoex__grade admin-autoex__grade--' + escapeHtml(String(t.top_grade)) + '">' + escapeHtml(String(t.top_grade)) + '</span>' : '';
      const delivery = t.delivery_avg_pct != null ? escapeHtml(Number(t.delivery_avg_pct).toFixed(1) + '%') : '—';
      return '<div class="admin-autoex__agg-row">' +
        '<div class="admin-autoex__agg-bar" style="width:' + Math.max(4, Math.min(100, Number(t.pct) || 0)) + '%"></div>' +
        '<div class="admin-autoex__agg-info">' +
        '<div class="admin-autoex__name">' + tid + grade + ' · ' + escapeHtml(String(t.count)) + 'x</div>' +
        '<div class="admin-autoex__sub">' + escapeHtml(String(t.rigs)) + ' rig(s) · entrega média ' + delivery + '</div>' +
        '</div></div>';
    }).join('');
    byRule.innerHTML = rules.map(function (r) {
      const floor = '<span class="admin-autoex__grade admin-autoex__grade--' + escapeHtml(String(r.grade_floor)) + '">' + escapeHtml(String(r.grade_floor)) + '</span>';
      const delivery = r.delivery_avg_pct != null ? escapeHtml(Number(r.delivery_avg_pct).toFixed(1) + '%') : '—';
      return '<div class="admin-autoex__agg-row">' +
        '<div class="admin-autoex__agg-bar admin-autoex__agg-bar--rule" style="width:' + Math.max(4, Math.min(100, Number(r.pct) || 0)) + '%"></div>' +
        '<div class="admin-autoex__agg-info">' +
        '<div class="admin-autoex__name">floor ' + floor + ' · mín ' + escapeHtml(String(r.min_samples)) + ' · ' + escapeHtml(String(r.count)) + 'x</div>' +
        '<div class="admin-autoex__sub">' + escapeHtml(String(r.tenants)) + ' tenant(s) · entrega média ' + delivery + '</div>' +
        '</div></div>';
    }).join('');
    // Systemic-problem rigs: the SAME rig auto-excluded in 2+ tenants.
    const topCol = document.getElementById('admin-autoex-toprigs-col');
    const topRigs = document.getElementById('admin-autoex-toprigs');
    if (topCol && topRigs) {
      const trs = agg.top_rigs || [];
      if (!trs.length) { topCol.hidden = true; return; }
      topCol.hidden = false;
      topRigs.innerHTML = trs.map(function (r) {
        const tids = r.tenants.map(function (x) {
          return x === 'default'
            ? '<span class="admin-autoex__tenant">default</span>'
            : escapeHtml(String(x));
        }).join(' · ');
        const when = r.last_ts ? escapeHtml(new Date(Number(r.last_ts) * 1000).toLocaleDateString('pt-BR')) : '—';
        return '<div class="admin-autoex__agg-row">' +
          '<div class="admin-autoex__agg-info">' +
          '<div class="admin-autoex__name">' + escapeHtml(String(r.name || r.rig_id)) + ' · ' + escapeHtml(String(r.tenant_count)) + ' tenants · ' + escapeHtml(String(r.total_count)) + 'x</div>' +
          '<div class="admin-autoex__sub">' + tids + ' · último ' + when + '</div>' +
          '</div></div>';
      }).join('');
    }
  }

  function _currentAuditFilters() {
    const tenantSel = document.getElementById('admin-audit-tenant');
    const verdictSel = document.getElementById('admin-audit-verdict');
    return {
      tenant: tenantSel ? tenantSel.value : '',
      verdict: verdictSel ? verdictSel.value : '',
    };
  }
  function _renderAdminAuditTable() {
    const tbody = document.getElementById('admin-audit-tbody');
    const empty = document.getElementById('admin-audit-empty');
    if (!tbody) return;
    const f = _currentAuditFilters();
    const rows = filterAdminAuditDecisions(_adminAuditDecisions, f.tenant, f.verdict);
    if (empty) empty.hidden = rows.length > 0;
    tbody.innerHTML = rows.map(function (d) {
      const vmeta = adminAuditVerdictMeta(d.verdict);
      const grade = d.grade ? '<span class="badge badge--' + (d.grade === 'F' ? 'red' : d.grade === 'A' ? 'green' : 'mute') + '">' + escapeHtml(String(d.grade)) + '</span>' : '—';
      const flagged = d.pilot_flagged ? ' <span class="admin-audit__flag" title="pilot flagged">▲</span>' : '';
      return '<tr>' +
        '<td class="mono">' + escapeHtml(_fmtAdminTs(d.ts)) + '</td>' +
        '<td>' + escapeHtml(String(d.tenant_id || 'default')) + '</td>' +
        '<td title="' + escapeHtml(String(d.rig_id || '')) + '">' + escapeHtml(String(d.name || d.rig_id || '—')) + flagged + '</td>' +
        '<td>' + escapeHtml(String(d.source || 'unknown')) + '</td>' +
        '<td>' + grade + '</td>' +
        '<td>' + escapeHtml(_fmtDeliveryPct(d.delivery_pct)) + '</td>' +
        '<td>' + escapeHtml(_fmtDeliveryPct(d.delivery_after_pct)) + '</td>' +
        '<td><span class="admin-audit__verdict ' + escapeHtml(vmeta.cls) + '">' + escapeHtml(vmeta.label) + '</span></td>' +
        '</tr>';
    }).join('');
  }
  function _renderAdminAuditChart(weekly) {
    const canvas = document.getElementById('admin-audit-chart');
    if (!canvas || typeof Chart === 'undefined') return;
    if (_adminAuditChart) { _adminAuditChart.destroy(); _adminAuditChart = null; }
    const labels = weekly.labels || [];
    if (!labels.length) return;
    _adminAuditChart = new Chart(canvas.getContext('2d'), {
      type: 'bar',
      data: {
        labels: labels,
        datasets: [{
          label: 'Aceitas/semana',
          data: weekly.counts,
          backgroundColor: 'rgba(6,214,240,0.35)',
          borderColor: 'rgb(6,214,240)',
          borderWidth: 1,
          borderRadius: 3,
        }],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: { legend: { display: false } },
        scales: {
          x: { ticks: { color: '#5E5952', font: { size: 9 }, maxRotation: 0 }, grid: { display: false } },
          y: { beginAtZero: true, ticks: { color: '#5E5952', font: { size: 9 }, precision: 0 }, grid: { color: 'rgba(94,89,82,0.10)' } },
        },
      },
    });
  }

  // Delegated: filter selects re-render the table (client-side, no refetch).
  const _auditFilterHost = document.getElementById('admin-panel');
  if (_auditFilterHost) {
    _auditFilterHost.addEventListener('change', function (e) {
      if (e.target && e.target.id === 'admin-audit-tenant') _renderAdminAuditTable();
      if (e.target && e.target.id === 'admin-audit-verdict') _renderAdminAuditTable();
    });
  }
  // CSV export — same admin-gated route, blob download (keeps X-API-Key header path).
  const auditCsvBtn = document.getElementById('admin-audit-csv');
  if (auditCsvBtn) {
    auditCsvBtn.addEventListener('click', async function () {
      const errEl = document.getElementById('admin-error');
      const fail = function (msg) {
        if (errEl) { errEl.hidden = false; errEl.textContent = msg; }
      };
      try {
        const r = await fetch('/api/admin/rentals/accepted-recos?format=csv', { headers: { 'X-Requested-With': 'fetch' } });
        if (!r.ok) {
          fail('CSV export blocked (HTTP ' + r.status + ') — a rota exige localhost ou X-API-Key do operador.');
          return;
        }
        const blob = await r.blob();
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = 'accepted_recos_audit_' + Math.floor(Date.now() / 1000) + '.csv';
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
        if (errEl) errEl.hidden = true;  // success clears any prior error
      } catch (err) {
        fail('CSV export error: ' + err.message);
      }
    });
  }

  // Funnel weekly CSV export — same admin-gated route, blob download
  // (keeps the X-API-Key header path for remote operators).
  const funnelCsvBtn = document.getElementById('admin-funnel-csv');
  if (funnelCsvBtn) {
    funnelCsvBtn.addEventListener('click', async function () {
      const errEl = document.getElementById('admin-error');
      const fail = function (msg) {
        if (errEl) { errEl.hidden = false; errEl.textContent = msg; }
      };
      try {
        const r = await fetch('/api/admin/conversion?format=csv&weeks=8', { headers: { 'X-Requested-With': 'fetch' } });
        if (!r.ok) {
          fail('CSV semanal bloqueado (HTTP ' + r.status + ') — a rota exige localhost ou X-API-Key do operador.');
          return;
        }
        const blob = await r.blob();
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = 'funnel_weekly_' + Math.floor(Date.now() / 1000) + '.csv';
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
        if (errEl) errEl.hidden = true;
      } catch (err) {
        fail('CSV semanal error: ' + err.message);
      }
    });
  }

  const adminRefreshBtn = document.getElementById('admin-refresh-btn');
  if (adminRefreshBtn) {
    adminRefreshBtn.addEventListener('click', function() {
      _adminLoaded = false;
      fetchAdminData();
    });
  }

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

  // Origin labels: backend `source` field (braiins|mrr|nicehash|parasite|derived)
  function _mktSourceLabel(src) {
    const map = { braiins: 'BRAIINS', mrr: 'MRR', nicehash: 'NICEHASH', parasite: 'PARASITE', derived: 'DERIVED' };
    return map[src] || (src || 'UNKNOWN').toUpperCase();
  }

  // Best offer: highest metrics.score (backend ROI) wins; only when NO offer
  // carries a finite score do we fall back to the lowest valid price.
  // Two-pass so a low-score offer can never override the score winner via the
  // price fallback (single-pass mixing had that bug).
  // ONLY real marketplace quotes may be crowned "best": estimated offers
  // (parasite pool-fee model) are NOT rental prices —
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

  // ── HashratePulse Enterprise · institutional market grid ────────────
  // Sort state: { key, dir } — dir -1 desc (best price first), 1 asc.
  let _mktSort = { key: 'price', dir: 1 };

  // Pure sort comparator (mirrored in tests/test_app_js_core.js):
  // returns venues sorted by the chosen key with the current direction.
  function sortMarketVenues(venues, key, dir) {
    const arr = (venues || []).slice();
    const val = (v, k) => {
      if (k === 'venue') return String(v.venue || '').toLowerCase();
      if (k === 'price') return Number(v.price_btc_ph_day);
      // Numeric keys: null/undefined → NaN so missing values sort LAST
      // (Number(null) would be 0 and wrongly sort FIRST — reviewer catch).
      if (k === 'usd') return v.price_usd_th_day != null ? Number(v.price_usd_th_day) : NaN;
      if (k === 'tier') return Number(v.risk_tier);
      return v[k] != null ? Number(v[k]) : NaN;
    };
    arr.sort((a, b) => {
      const va = val(a, key);
      const vb = val(b, key);
      if (va === vb) return 0;
      // Numbers: missing/NaN sort last. Strings: plain compare.
      if (typeof va === 'number' && typeof vb === 'number') {
        if (!isFinite(va)) return 1;
        if (!isFinite(vb)) return -1;
        return (va - vb) * dir;
      }
      return String(va).localeCompare(String(vb)) * dir;
    });
    return arr;
  }

  function renderMarketGrid() {
    const tbody = document.getElementById('mkt-table-body');
    if (!tbody) {
      // DOM not yet parsed (Chart.js CDN blocks <head>). Retry once
      // after a short delay so the tbody has time to appear.
      if (!_mktGridRetried) {
        _mktGridRetried = true;
        setTimeout(function () {
          _mktGridRetried = false;
          renderMarketGrid();
        }, 100);
      }
      return;
    }

    const inst = _mktInstitutional || {};
    let venues = (inst.venues || []).filter(v => {
      if (_mktFilter === 'all') return true;
      return (v.venue || '').toLowerCase() === _mktFilter;
    });

    // Executive Snapshot
    const snap = inst.snapshot || {};
    const bestEl = document.getElementById('mkt-snap-best');
    if (bestEl && snap.best_price_sats_th_day) {
      bestEl.textContent = snap.best_price_sats_th_day + ' sat/TH/d · ' + (snap.best_venue || '').toUpperCase();
    }
    const spreadEl = document.getElementById('mkt-snap-spread');
    if (spreadEl) spreadEl.textContent = snap.spread_vs_second_pct != null ? snap.spread_vs_second_pct + '%' : '—';
    const liqEl = document.getElementById('mkt-snap-liquidity');
    if (liqEl) liqEl.textContent = snap.total_liquidity_eh != null ? snap.total_liquidity_eh + ' EH/s' : '—';
    const vwapEl = document.getElementById('mkt-snap-vwap');
    if (vwapEl && snap.vwap_4h_btc_ph_day) vwapEl.textContent = snap.vwap_4h_btc_ph_day.toFixed(6) + ' BTC/PH/d';
    const btcEl = document.getElementById('mkt-snap-btcusd');
    // Real-user audit: institutional.btc_usd can lag behind the top-level
    // btc_price — fall back to _mktBtcUsd (same source the USD/TH/d column
    // uses) so the Executive Snapshot never shows a stale "—".
    const btcUsdCell = snap.btc_usd || _mktBtcUsd;
    if (btcEl && btcUsdCell) btcEl.textContent = '$' + Number(btcUsdCell).toLocaleString('en-US');

    // CFO: rent-vs-own benchmark cell in the snapshot strip.
    const rvo = snap.rent_vs_own;
    const rvoEl = document.getElementById('mkt-snap-rentvsown');
    if (rvoEl) {
      if (rvo && rvo.ratio != null) {
        rvoEl.textContent = rvo.cheaper_than_own
          ? 'RENT -' + rvo.discount_pct + '% vs own'
          : 'RENT +' + rvo.premium_pct + '% vs own';
        rvoEl.className = 'mkt-snapshot__val' + (rvo.cheaper_than_own ? ' mkt-snapshot__val--green' : ' mkt-snapshot__val--red');
        rvoEl.title = 'Best rental $' + rvo.rental_usd_th_day + '/TH/d vs owned-hardware mining cost $' + rvo.own_cost_usd_th_day + '/TH/d';
      } else {
        rvoEl.textContent = '—';
        rvoEl.className = 'mkt-snapshot__val';
        rvoEl.title = '';
      }
    }

    // Regime badge — Dislocated now gets a red treatment (audit: it had NO
    // class, rendering identical to the default badge).
    const regimeEl = document.getElementById('mkt-regime-badge');
    if (regimeEl) {
      regimeEl.textContent = 'REGIME ' + (inst.regime || '—');
      regimeEl.className = 'badge' + (inst.regime === 'Tight' ? ' badge--green' : inst.regime === 'Normal' ? ' badge--blue' : inst.regime === 'Wide' ? ' badge--amber' : inst.regime === 'Dislocated' ? ' badge--red' : '');
    }

    document.getElementById('mkt-best-price-badge') && (document.getElementById('mkt-best-price-badge').textContent = snap.best_price_sats_th_day ? 'best ' + snap.best_price_sats_th_day + ' sat/TH/d' : 'best —');
    document.getElementById('mkt-count-badge') && (document.getElementById('mkt-count-badge').textContent = (snap.offer_count || venues.length) + ' venues');

    if (!venues.length) {
      tbody.innerHTML = '<tr><td colspan="9" class="mkt-table__empty">' + (_mktOffers.length ? 'no venues for selected filter' : 'no market data — configure API keys in Settings') + '</td></tr>';
      document.getElementById('mkt-notes') && (document.getElementById('mkt-notes').style.display = 'none');
      return;
    }

    // CFO: USD/TH/d column — convert BTC/PH/d → USD/TH/d (1 PH = 1000 TH).
    // Kept on the venue object so the sort key 'usd' and the render agree.
    venues.forEach(v => {
      const btcUsd = _mktBtcUsd || (snap.btc_usd) || null;
      v.price_usd_th_day = (v.price_btc_ph_day != null && btcUsd)
        ? Number(v.price_btc_ph_day) / 1000 * Number(btcUsd)
        : null;
    });
    venues = sortMarketVenues(venues, _mktSort.key, _mktSort.dir);

    // Institutional Notes
    const notes = inst.notes || [];
    const notesEl = document.getElementById('mkt-notes');
    const notesBody = document.getElementById('mkt-notes-body');
    if (notesEl && notesBody) {
      if (notes.length) {
        notesEl.style.display = 'block';
        notesBody.innerHTML = notes.map(n => '<div class="mkt-notes__item">' + escapeHtml(n) + '</div>').join('');
      } else {
        notesEl.style.display = 'none';
      }
    }

    // Sort arrows in the header reflect the active sort.
    document.querySelectorAll('#mkt-table thead th[data-mkt-sort]').forEach(th => {
      const arrow = th.querySelector('.mkt-sort-arrow');
      if (arrow) {
        arrow.textContent = th.getAttribute('data-mkt-sort') === _mktSort.key
          ? (_mktSort.dir === 1 ? '▼' : '▲')
          : '';
      }
    });

    tbody.innerHTML = venues.map(v => {
      const tierCls = v.risk_tier === 1 ? 'mkt-table__tier--t1' : v.risk_tier === 2 ? 'mkt-table__tier--t2' : v.risk_tier === 3 ? 'mkt-table__tier--t3' : 'mkt-table__tier--t4';
      const spreadCls = v.spread_vs_best_pct <= 2 ? 'mkt-table__spread--tight' : v.spread_vs_best_pct > 20 ? 'mkt-table__spread--wide' : '';
      const recCls = v.recommendation.indexOf('Preferred') === 0 ? 'mkt-table__rec--best' : v.recommendation.indexOf('Avoid') === 0 ? 'mkt-table__rec--avoid' : '';
      return `<tr>
        <td><span class="mkt-table__venue">${escapeHtml(v.venue)}</span>${v.estimated ? ' <span class="mkt-table__est">EST</span>' : ''}</td>
        <td class="mono">${v.price_btc_ph_day.toFixed(6)}</td>
        <td class="mono">${v.price_usd_th_day != null ? '$' + v.price_usd_th_day.toFixed(4) : '—'}</td>
        <td class="mono ${spreadCls}">${v.spread_vs_best_pct >= 0 ? '+' : ''}${escapeHtml(v.spread_vs_best_pct)}%</td>
        <td class="mono">${v.spread_vs_vwap_pct >= 0 ? '+' : ''}${escapeHtml(v.spread_vs_vwap_pct)}%</td>
        <td class="mono">${escapeHtml(v.available_ph)} PH/s</td>
        <td>${escapeHtml(v.depth_score)}</td>
        <td><span class="mkt-table__tier ${tierCls}">${escapeHtml(v.risk_tier_label)}</span></td>
        <td class="${recCls}">${escapeHtml(v.recommendation)}</td>
      </tr>`;
    }).join('');
  }

  function renderMarket(snap) {
    const mkt = snap.market_data || {};
    _mktOffers = mkt.offers || [];
    _mktBtcUsd = Number(snap.btc_price && snap.btc_price.usd) || null;
    _mktAffiliate = mkt.affiliate || null;
    _mktInstitutional = mkt.institutional || null;
    renderMarketGrid();
  }

  // ── P0-2: Decision Matrix — solo vs pool vs lease (capital allocation) ──
  // Pure render of the backend-aggregated decision_matrix block; every field
  // is read defensively and shows '—' when the strategy has no data yet.
  function renderDecisionMatrix(p) {
    const dm = (p && p.decision_matrix) || null;
    const rows = (dm && dm.rows) || {};
    const el = (id) => document.getElementById(id);
    const usd = (v) => (v != null && isFinite(v)) ? '$' + Number(v).toLocaleString('en-US', { maximumFractionDigits: 2 }) + '/d' : '—';
    const days = (v) => (v != null && isFinite(v)) ? (v >= 365 ? (v/365).toFixed(1) + 'y' : Math.round(v) + 'd') : '—';
    const pct = (v) => (v != null && isFinite(v)) ? (v < 1 ? v.toFixed(4) : v.toFixed(1)) + '%' : '—';

    const poolEl = el('dm-pool-usd'); if (poolEl) poolEl.textContent = usd(rows.pool && rows.pool.net_usd_per_day);
    const soloTime = el('dm-solo-time'); if (soloTime) soloTime.textContent = days(rows.solo && rows.solo.expected_time_days);
    const soloSub = el('dm-solo-sub');
    if (soloSub) {
      const py = rows.solo && rows.solo.p_year_pct;
      soloSub.textContent = (py != null && isFinite(py)) ? 'P(bloco no ano) ' + pct(py) : 'tempo esperado até bloco';
    }
    const leaseEl = el('dm-lease-usd'); if (leaseEl) leaseEl.textContent = usd(rows.lease && rows.lease.net_usd_per_day);
    const bestEl = el('dm-best-badge'); if (bestEl) bestEl.textContent = dm ? 'BEST: ' + String(dm.best_option || '—').toUpperCase() : '—';
    const recoEl = el('dm-reco'); if (recoEl && dm && dm.recommendation) recoEl.textContent = dm.recommendation;
    const beEl = el('dm-breakeven');
    if (beEl) {
      const be = dm && dm.breakeven_cost_per_th_day;
      beEl.textContent = (be != null && isFinite(be)) ? 'break-even $' + Number(be).toFixed(4) + '/TH·d' : 'break-even —';
    }
    // P0-3: one-click affiliate link — honest, only operator-configured URLs.
    // Null/absent → button stays hidden; the BEST OFFER CTA remains the fallback.
    const buyEl = el('dm-buy-affiliate');
    const aff = dm && dm.affiliate;
    if (buyEl) {
      if (aff && aff.url) {
        buyEl.hidden = false;
        buyEl.textContent = '⚡ BUY ' + String(aff.provider || '').toUpperCase();
        buyEl.onclick = () => { window.open(aff.url, '_blank', 'noopener'); };
      } else {
        buyEl.hidden = true;
        buyEl.onclick = null;
      }
    }
  }

  // P0-2: CTA — jump to the best offer in the offers grid (no fake affiliate
  // link: the honest action is to surface the cheapest real market quote).
  function initDecisionMatrixControls() {
    const btn = document.getElementById('dm-goto-offers');
    if (!btn) return;
    btn.addEventListener('click', () => {
      const grid = document.getElementById('mkt-grid');
      if (grid) grid.scrollIntoView({ behavior: 'smooth', block: 'center' });
    });
  }

  // ── P0-3: Command Center — contextual action cards ──
  // Renders snap.command_center (backend-aggregated, advisory-only) into the
  // cc-grid. Each card carries data-cc-target (module to navigate to),
  // data-cc-panel (panel id to scroll) and data-cc-url (optional external
  // link — affiliate buy). Pure helper mirrored in tests/test_app_js_core.js.
  function commandCenterCardHtml(card) {
    if (!card || typeof card !== 'object') return '';
    const sev = String(card.severity || 'info').toLowerCase();
    const esc = escapeHtml;
    const target = String(card.target || '');
    const panel = String(card.panel || '');
    const url = String(card.url || '');
    return (
      '<button type="button" class="cc-card cc-card--' + sev + '" ' +
      'data-cc-target="' + esc(target) + '" ' +
      'data-cc-panel="' + esc(panel) + '" ' +
      'data-cc-url="' + esc(url) + '">' +
      '<span class="cc-card__title">' + esc(card.title || 'Atenção') + '</span>' +
      '<span class="cc-card__message">' + esc(card.message || '') + '</span>' +
      '<span class="cc-card__action">' + esc(card.action || 'IR') + ' →</span>' +
      '</button>'
    );
  }

  // P0-5 audit: the Command Center re-wrote #cc-grid.innerHTML on EVERY
  // 15s snapshot, even when the cards were byte-identical. With the
  // backend aggregating fresh dicts each poll, the panel visibly flickered
  // ("infinite blinking") as buttons were destroyed/recreated. Skip the
  // DOM write when the serialized cards match the previous render — the
  // badge still updates (cheap), so severity changes always surface.
  let _lastCcKey = null;
  function renderCommandCenter(snap) {
    const grid = document.getElementById('cc-grid');
    if (!grid) return;
    const badge = document.getElementById('cc-status-badge');
    const cards = (snap && Array.isArray(snap.command_center)) ? snap.command_center : [];
    // Stable serialization key: id + severity + url + title + message.
    // Messages are DYNAMIC (proximity_streak embeds the live 1h trend %,
    // negative_operation embeds the $ amount) — a key of id|severity|url
    // alone froze the card text on the first render (reviewer catch). Only
    // skip the DOM write when the rendered text is truly identical.
    const key = cards.map(c => (c && c.id || '') + '|' + (c && c.severity || '') + '|' + (c && c.url || '') + '|' + (c && c.title || '') + '|' + (c && c.message || '')).join('\n');
    const keyChanged = key !== _lastCcKey;
    _lastCcKey = key;
    if (keyChanged) {
      if (cards.length === 0) {
        grid.innerHTML = (
          '<div class="empty-state" style="grid-column:1/-1;border:none;padding:10px">' +
          '<div class="empty-state__icon">⌘</div>' +
          '<div class="empty-state__title">All systems nominal</div>' +
          '<div class="empty-state__desc">No action needed right now — the dashboard is monitoring your operation.</div>' +
          '</div>'
        );
      } else {
        grid.innerHTML = cards.map(commandCenterCardHtml).join('');
      }
    }
    if (badge) {
      const count = cards.length;
      const next = count + ' action' + (count === 1 ? '' : 's');
      if (badge.textContent !== next) badge.textContent = next;
      const topSev = cards[0] && cards[0].severity;
      const cls = 'badge ' + (topSev === 'crit' || topSev === 'warn' ? 'badge--amber' : topSev === 'gold' ? 'badge--gold' : 'badge--green');
      if (badge.className !== cls) badge.className = cls;
    }
  }

  function initCommandCenterControls() {
    const grid = document.getElementById('cc-grid');
    if (!grid) return;
    grid.addEventListener('click', (e) => {
      const card = e.target.closest ? e.target.closest('.cc-card') : null;
      if (!card) return;
      const url = card.getAttribute('data-cc-url');
      if (url) { window.open(url, '_blank', 'noopener'); return; }
      const target = card.getAttribute('data-cc-target');
      if (target) activateModule(target);
      const panel = card.getAttribute('data-cc-panel');
      if (panel) {
        // Scroll after module activation settles visibility (charts resize,
        // panels unhide). Small delay keeps the scroll target measurable.
        setTimeout(() => {
          const el = document.getElementById(panel);
          if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' });
        }, 120);
      }
    });
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
    // CFO: interactive column sorting — click toggles asc/desc, re-render
    // honors the filter + sort combination.
    document.querySelectorAll('#mkt-table thead th[data-mkt-sort]').forEach(th => {
      th.addEventListener('click', () => {
        const key = th.getAttribute('data-mkt-sort');
        if (_mktSort.key === key) {
          _mktSort.dir = _mktSort.dir === 1 ? -1 : 1;
        } else {
          _mktSort = { key: key, dir: 1 };
        }
        renderMarketGrid();
      });
    });
    const cfgBtn = document.getElementById('mkt-config-btn');
    if (cfgBtn) cfgBtn.addEventListener('click', () => { if (typeof openSettingsModal === 'function') openSettingsModal(); });
    // P0-4: delegated one-click affiliate BUY — the grid re-renders via
    // innerHTML every snapshot, so the listener lives on the grid itself and
    // reads data-aff-url from the clicked button (window.open, new tab).
    const grid = document.getElementById('mkt-grid');
    if (grid) {
      grid.addEventListener('click', (e) => {
        const btn = e.target.closest ? e.target.closest('.mkt-card__buy') : null;
        if (!btn) return;
        const url = btn.getAttribute('data-aff-url');
        if (url) window.open(url, '_blank', 'noopener');
      });
    }
    // NOTE: loadMarketTrend() is lazy — triggered by activateModule('market').
  }

  // Pure builder for the 7d market trend chart (mirrored in JS tests):
  // providers → { times, labels, datasets } with per-provider null gaps so
  // each line only connects the timestamps it actually has points for.
  // Prices arrive in BTC/TH/d and are converted to sats/TH/d for display.
  function buildMarketTrendDatasets(providers) {
    const colors = ['rgb(247,147,26)', 'rgb(6,214,240)', 'rgb(168,85,247)', 'rgb(245,158,11)', 'rgb(16,185,129)'];
    const allTs = new Set();
    Object.values(providers || {}).forEach(pts => (pts || []).forEach(p => { if (p && p.ts) allTs.add(p.ts); }));
    const times = Array.from(allTs).sort((a, b) => a - b);
    const labels = times.map(t => { const d = new Date(t * 1000); return String(d.getHours()).padStart(2, '0') + ':' + String(d.getMinutes()).padStart(2, '0'); });
    const datasets = Object.keys(providers || {}).map((name, i) => {
      const byTs = {};
      ((providers[name]) || []).forEach(p => { if (p && p.ts != null) byTs[p.ts] = p.price_btc_per_th_day; });
      return {
        label: name,
        data: times.map(t => byTs[t] != null ? Number(byTs[t]) * 1e8 : null),
        borderColor: colors[i % colors.length],
        backgroundColor: colors[i % colors.length].replace(')', ',0.08)').replace('rgb', 'rgba'),
        tension: 0.4, pointRadius: 0, fill: false,
      };
    });
    return { times, labels, datasets };
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
      const legendEl = document.getElementById('mkt-trend-legend');
      const { labels, datasets } = buildMarketTrendDatasets(provs);
      // Frescor honesto: mostra quantos providers têm histórico e QUANDO o
      // snapshot mais recente foi persistido (dado real do /api/market/trend).
      if (countEl) {
        const upd = data.updated_at || 0;
        const clock = upd ? new Date(upd * 1000) : null;
        const hhmm = clock ? String(clock.getHours()).padStart(2, '0') + ':' + String(clock.getMinutes()).padStart(2, '0') : '';
        countEl.textContent = datasets.length
          ? (datasets.length + ' providers' + (hhmm ? ' · ' + hhmm : ''))
          : '0 providers — sem histórico ainda';
      }
      if (legendEl) {
        legendEl.innerHTML = datasets.length
          ? datasets.map(d =>
              `<span class="mkt-trend__legend-item"><span class="mkt-trend__legend-dot" style="background:${d.borderColor}"></span>${escapeHtml(d.label)}</span>`
            ).join('')
          : '<span class="mkt-trend__legend-item" style="color:var(--text-tertiary)">preços são persistidos a cada fetch (warm-up 5min) — volte mais tarde</span>';
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

  // ── RENTALS panel (P2) — operator rental performance (MRR + Braiins) ──
  let _rentalsLoaded = false;   // lazy: /api/rentals fetched on first module activation
  let _rentalsData = null;      // last payload (kept so filters re-render without refetch)
  let _rentalsFilter = 'active';
  let _rentalsAutoTabbed = false;  // UX: auto-lands on the first tab that has data
  let _rentalsDetailChart = null;
  let _rentalsRigChart = null;     // mini bar chart of same-rig % history

  function _setRentalsFilter(name) {
    _rentalsFilter = name;
    const chips = document.querySelectorAll('[data-rentals-filter]');
    chips.forEach(c => c.classList.toggle('active', c.getAttribute('data-rentals-filter') === name));
    // Strip cards mirror the filter state (click-first affordance).
    document.querySelectorAll('.rentals-strip__card').forEach(c =>
      c.classList.toggle('active-strip', c.getAttribute('data-rentals-filter') === name));
  }

  // CFO: portfolio band — consolidated spend/cost/delivery across providers
  // (server-side compute_portfolio_summary; hidden when there's no data).
  function _renderRentalsPortfolio() {
    const wrap = document.getElementById('rentals-portfolio');
    if (!wrap || !_rentalsData) return;
    const set = (id, v) => { const e = document.getElementById(id); if (e) e.textContent = v; };
    const p = _rentalsData.portfolio;
    // Hide the band entirely on an empty account (all-'—' row is noise).
    if (!p || !p.spend || !p.spend.count) { wrap.hidden = true; return; }
    wrap.hidden = false;
    const spend = p.spend || {};
    const income = p.income || {};
    set('rentals-port-total', spend.spent_sats ? Number(spend.spent_sats).toLocaleString('en-US') + ' sats' : '—');
    set('rentals-port-avg-cost', spend.avg_cost_sats_per_thh != null ? Number(spend.avg_cost_sats_per_thh).toFixed(1) + ' st/TH·h' : '—');
    set('rentals-port-avg-delivery', spend.avg_delivery_pct != null ? Number(spend.avg_delivery_pct).toFixed(1) + '%' : '—');
    set('rentals-port-delivered', spend.delivered_thh ? Number(spend.delivered_thh).toLocaleString('en-US') + ' TH·h' : '—');
    // Owner side: what rigs leased OUT earned (sats from renters).
    set('rentals-port-income', income.count && income.spent_sats ? Number(income.spent_sats).toLocaleString('en-US') + ' sats' : '—');
    const split = p.split || {};
    const parts = [];
    if (split.mrr) parts.push('MRR ' + split.mrr);
    if (split.braiins) parts.push('Braiins ' + split.braiins);
    set('rentals-port-split', parts.join(' · ') || '—');
  }

  // Mirror of services/rental_performance._hash_to_th — MRR reports hashrate
  // as {hash, type} where the raw hash is in the type unit (ph/mh/gh/th).
  // Unknown units (e.g. raw 'hash') return null: an honest '—' beats a
  // nonsense astronomical number in the AVG/ADVERTISED cell.
  function _mrToTh(v, unit) {
    if (v === null || v === undefined || v === '') return null;
    const n = Number(v);
    if (!isFinite(n)) return null;
    const u = String(unit || '').toLowerCase();
    if (u === 'ph') return n * 1000;
    if (u === 'th') return n;
    if (u === 'gh') return n / 1000;
    if (u === 'mh') return n / 1e6;
    return null;
  }

  function _rentalStatus(r) {
    if (!r) return '—';
    if (r.ended) return 'ended';
    const st = (r.rig && r.rig.status) || '';
    return st || (r.end ? 'running' : 'active');
  }

  function _rentalHashrateStr(r) {
    if (!r) return '—';
    const avg = r.hashrate_average_th;
    const adv = r.hashrate_advertised_th;
    if (avg && adv) return fmt.hashrate(avg * 1e12) + ' / ' + fmt.hashrate(adv * 1e12) +
      (r.hashrate_percent != null ? ' (' + Number(r.hashrate_percent).toFixed(1) + '%)' : '');
    if (adv) return fmt.hashrate(adv * 1e12);
    return '—';
  }

  function _rentalPriceStr(r) {
    if (!r || r.price_paid_btc == null) return '—';
    return (r.price_paid_btc * 1e8).toFixed(0) + ' sats';
  }

  // CFO: rig trust — is this rig blacklisted (manual OR auto-excluded) or a
  // known bad performer? Returns {blacklisted, auto, grade} for the badges.
  function _rentalRigTrust(r) {
    if (!r || !r.rig) return { blacklisted: false, auto: false, grade: null };
    const bl = (_rentalsData && _rentalsData.rig_blacklist) || [];
    const auto = (_rentalsData && _rentalsData.rig_auto_blacklist) || [];
    const rid = r.rig.id != null ? String(r.rig.id) : null;
    return {
      blacklisted: !!(rid && bl.indexOf(rid) !== -1),
      auto: !!(rid && auto.indexOf(rid) !== -1),
      grade: r.rig_trust && r.rig_trust.grade ? r.rig_trust.grade : null,
    };
  }

  // CFO: should this rental card be hidden by the "hide bad rigs" toggle?
  // Hidden when the rig is blacklisted (manual or auto) OR scored grade F.
  function _rentalIsBad(r) {
    const t = _rentalRigTrust(r);
    return t.blacklisted || t.auto || t.grade === 'F';
  }

  // CFO recommendation engine: 'where to rent again' — top rigs by
  // reliability × price vs market, with an avoid counter.
  function _renderRentalsReco() {
    const wrap = document.getElementById('rentals-reco');
    if (!wrap || !_rentalsData) return;
    const rec = _rentalsData.recommendations;
    const hasTop = !!(rec && rec.top && rec.top.length);
    const hasAvoid = !!(rec && rec.avoid && rec.avoid.length);
    if (!hasTop && !hasAvoid) { wrap.hidden = true; return; }
    wrap.hidden = false;
    const meta = document.getElementById('rentals-reco-meta');
    if (meta) {
      meta.textContent = rec.tracked + ' rigs rastreados' +
        (rec.avoid_count ? ' · ' + rec.avoid_count + ' evitar' : '');
    }
    const topEl = document.getElementById('rentals-reco-cards');
    if (topEl) topEl.innerHTML = (rec.top || []).map(t => {
      const vMkt = t.vs_market_pct != null
        ? (t.vs_market_pct <= 0 ? '✓ ' : '') + (t.vs_market_pct > 0 ? '+' : '') + Number(t.vs_market_pct).toFixed(0) + '% vs mkt'
        : '';
      const trend = t.trend_pct != null
        ? '<span class="rentals-reco__trend ' + (t.trend_pct >= 0 ? 'is-good' : 'is-bad') + '">' +
          (t.trend_pct >= 0 ? '▲' : '▼') + Math.abs(Number(t.trend_pct)).toFixed(1) + '%</span>' : '';
      const badge = t.grade
        ? '<span class="rentals-trust__badge rentals-trust__badge--' + escapeHtml(String(t.grade)) + '">' + escapeHtml(String(t.grade)) + '</span>' : '';
      const score = t.score != null ? Number(t.score).toFixed(0) : '—';
      const samples = t.samples != null ? t.samples + ' amostras' : '';
      return '<div class="rentals-reco__card rentals-reco__card--clickable" data-rig-id="' + escapeHtml(String(t.rig_id != null ? t.rig_id : '')) + '" data-rig-name="' + escapeHtml(String(t.name || '')) + '" title="clique p/ ver o track record do rig ' + escapeHtml(String(t.rig_id)) + '">' +
        '<div class="rentals-reco__name">' + escapeHtml(String(t.name || t.rig_id)) + badge + '</div>' +
        '<div class="rentals-reco__row"><span>SCORE</span><strong>' + score + '</strong>' +
        '<span>MEDIAN</span><strong>' + (t.median_pct != null ? Number(t.median_pct).toFixed(1) + '%' : '—') + '</strong>' +
        '<span>COST</span><strong>' + (t.avg_cost_sats_per_thh != null ? Number(t.avg_cost_sats_per_thh).toFixed(0) + ' st' : '—') + '</strong></div>' +
        '<div class="rentals-reco__row rentals-reco__row--sub"><span>' + escapeHtml(vMkt || '') + '</span><span>' + samples + '</span>' + trend + '</div>' +
        '</div>';
    }).join('');
    // Pilot's avoid case — grade-F rigs with a ONE-CLICK accept (blacklist).
    const avoidHead = document.getElementById('rentals-avoid-head');
    if (avoidHead) avoidHead.hidden = !hasAvoid;
    const avoidEl = document.getElementById('rentals-avoid-cards');
    if (avoidEl) avoidEl.innerHTML = (rec.avoid || []).map(t => {
      const trend = t.trend_pct != null
        ? '<span class="rentals-reco__trend ' + (t.trend_pct >= 0 ? 'is-good' : 'is-bad') + '">' +
          (t.trend_pct >= 0 ? '▲' : '▼') + Math.abs(Number(t.trend_pct)).toFixed(1) + '%</span>' : '';
      const badge = t.grade
        ? '<span class="rentals-trust__badge rentals-trust__badge--' + escapeHtml(String(t.grade)) + '">' + escapeHtml(String(t.grade)) + '</span>' : '';
      const samples = t.samples != null ? t.samples + ' amostras' : '';
      return '<div class="rentals-reco__card rentals-reco__card--avoid" data-rig-id="' + escapeHtml(String(t.rig_id != null ? t.rig_id : '')) + '" data-rig-name="' + escapeHtml(String(t.name || '')) + '" title="clique p/ ver o track record do rig ' + escapeHtml(String(t.rig_id)) + '">' +
        '<div class="rentals-reco__name">' + escapeHtml(String(t.name || t.rig_id)) + badge + '</div>' +
        '<div class="rentals-reco__row"><span>MEDIAN</span><strong>' + (t.median_pct != null ? Number(t.median_pct).toFixed(1) + '%' : '—') + '</strong>' +
        '<span>WORST</span><strong>' + (t.worst_pct != null ? Number(t.worst_pct).toFixed(1) + '%' : '—') + '</strong>' +
        '<span>COST</span><strong>' + (t.avg_cost_sats_per_thh != null ? Number(t.avg_cost_sats_per_thh).toFixed(0) + ' st' : '—') + '</strong></div>' +
        '<div class="rentals-reco__row rentals-reco__row--sub"><span>' + samples + '</span>' + trend + '</div>' +
        '<button type="button" class="btn btn--mini btn--danger rentals-reco__blacklist" data-rig-id="' + escapeHtml(String(t.rig_id != null ? t.rig_id : '')) + '" title="aceitar a sugestão do piloto: nunca alugar este rig de novo">⛔ BLACKLISTAR</button>' +
        '</div>';
    }).join('');
  }

  // CFO: accepted recommendations — rigs que o piloto sugeriu blacklistar e
  // o operador ACEITOU (manual = blacklist, auto = exclusão automática).
  // Mostra o caso do piloto no momento (entrega antes) e o RESULTADO da
  // entrega DEPOIS da decisão: evitado / melhorou / piorou / estável.
  function _renderRentalsAccepted() {
    const wrap = document.getElementById('rentals-accepted');
    if (!wrap || !_rentalsData) return;
    const recos = (_rentalsData.accepted_recos || {}).accepted || [];
    if (!recos.length) { wrap.hidden = true; wrap.innerHTML = ''; return; }
    wrap.hidden = false;
    const meta = document.getElementById('rentals-accepted-meta');
    if (meta) {
      const total = (_rentalsData.accepted_recos || {}).count || recos.length;
      const avoided = recos.filter(r => r.verdict === 'avoided').length;
      meta.textContent = total + ' aceita' + (total === 1 ? '' : 's') + (avoided ? ' · ' + avoided + ' evitada' + (avoided === 1 ? '' : 's') : '');
    }
    const list = document.getElementById('rentals-accepted-list');
    list.innerHTML = recos.map(r => {
      const src = r.source === 'auto'
        ? '<span class="rentals-accepted__src is-auto" title="exclusão automática (sub-entrega)">AUTO</span>'
        : '<span class="rentals-accepted__src is-manual" title="blacklist manual — você aceitou a sugestão do piloto">MANUAL</span>';
      // Honest framing: a manual blacklist of a rig the pilot NEVER flagged
      // (grade ≠ F) renders 'não sugerido' instead of implying it was a
      // pilot recommendation.
      const ns = r.pilot_flagged === false
        ? '<span class="rentals-accepted__src is-ns" title="blacklist manual de um rig que o piloto não havia sinalizado">NÃO SUGERIDO</span>' : '';
      const grade = r.grade
        ? '<span class="rentals-trust__badge rentals-trust__badge--' + escapeHtml(String(r.grade)) + '">' + escapeHtml(String(r.grade)) + '</span>' : '';
      const verdictMap = {
        revoked: ['REVOGADA', 'is-warn', 'decisão revogada — rig restaurado da blacklist'],
        avoided: ['EVITADO', 'is-good', 'sem novos aluguéis após a decisão'],
        improved: ['MELHOROU', 'is-good', 'entrega subiu após a decisão'],
        worse: ['PIOROU', 'is-bad', 'entrega caiu após a decisão'],
        same: ['ESTÁVEL', 'is-mid', 'entrega sem mudança relevante'],
        no_before: ['SEM DADOS', 'is-mid', 'sem referência de entrega anterior'],
      };
      const v = verdictMap[r.verdict] || ['—', 'is-mid', ''];
      const before = r.delivery_pct != null ? Number(r.delivery_pct).toFixed(1) + '%' : '—';
      const after = r.delivery_after_pct != null ? Number(r.delivery_after_pct).toFixed(1) + '%' : '—';
      const when = r.ts ? new Date(Number(r.ts) * 1000).toLocaleDateString('pt-BR') : '—';
      return '<div class="rentals-accepted__card" data-rig-id="' + escapeHtml(String(r.rig_id != null ? r.rig_id : '')) + '" data-rig-name="' + escapeHtml(String(r.name || '')) + '" title="clique p/ ver o track record do rig ' + escapeHtml(String(r.rig_id)) + '">' +
        '<div class="rentals-accepted__name">' + escapeHtml(String(r.name || r.rig_id)) + grade + src + ns + '</div>' +
        '<div class="rentals-accepted__row"><span>ACEITO</span><strong>' + escapeHtml(when) + '</strong>' +
        '<span>ENTREGA</span><strong>' + before + ' → ' + after + '</strong></div>' +
        '<div class="rentals-accepted__row rentals-accepted__row--sub">' +
        '<span class="rentals-accepted__verdict ' + v[1] + '" title="' + escapeHtml(String(v[2] || '')) + '">' + escapeHtml(String(v[0] || '')) + '</span>' +
        (r.samples != null ? '<span>' + escapeHtml(String(r.samples)) + ' amostras</span>' : '') + '</div></div>';
    }).join('');
  }

  // Auto-exclusion history (WHEN + CAUSE): rigs the pilot auto-excluded,
  // with the delivery snapshot at exclusion + the rule that fired. Same
  // card pattern as accepted-recos (click → rig track record).
  function _renderRentalsAutoExclusions() {
    const wrap = document.getElementById('rentals-autoex');
    if (!wrap || !_rentalsData) return;
    const list = document.getElementById('rentals-autoex-list');
    const meta = document.getElementById('rentals-autoex-meta');
    const ex = (_rentalsData.auto_exclusions || {}).exclusions || [];
    if (!list) return;
    if (!ex.length) { wrap.hidden = true; return; }
    wrap.hidden = false;
    if (meta) meta.textContent = ex.length + ' rig' + (ex.length === 1 ? '' : 's') + ' auto-excluído' + (ex.length === 1 ? '' : 's');
    list.innerHTML = ex.map(function (x) {
      const grade = x.grade
        ? '<span class="rentals-trust__badge rentals-trust__badge--' + escapeHtml(String(x.grade)) + '">' + escapeHtml(String(x.grade)) + '</span>' : '';
      const when = x.ts ? new Date(Number(x.ts) * 1000).toLocaleDateString('pt-BR') : '—';
      const delivery = x.delivery_pct != null ? Number(x.delivery_pct).toFixed(1) + '%' : '—';
      const samples = x.samples != null ? escapeHtml(String(x.samples)) + ' amostras' : '—';
      const rule = (x.grade_floor || 'F') + ' · mín ' + (x.min_samples != null ? escapeHtml(String(x.min_samples)) : '2');
      return '<div class="rentals-autoex__card" data-rig-id="' + escapeHtml(String(x.rig_id != null ? x.rig_id : '')) + '" data-rig-name="' + escapeHtml(String(x.name || '')) + '" title="clique p/ ver o track record do rig ' + escapeHtml(String(x.rig_id)) + '">' +
        '<div class="rentals-autoex__name">' + escapeHtml(String(x.name || x.rig_id)) + grade + '</div>' +
        '<div class="rentals-autoex__row"><span>QUANDO</span><strong>' + escapeHtml(when) + '</strong>' +
        '<span>ENTREGA</span><strong>' + escapeHtml(delivery) + '</strong></div>' +
        '<div class="rentals-autoex__row rentals-autoex__row--sub">' +
        '<span title="amostras na exclusão">' + samples + '</span>' +
        '<span class="rentals-autoex__rule" title="régua vigente — floor de grade + mín de amostras">régua ' + escapeHtml(rule) + '</span>' +
        '</div>' +
        '<div class="rentals-autoex__cause" title="causa da exclusão">' + escapeHtml(String(x.cause || 'sub-entrega')) + '</div>' +
        '</div>';
    }).join('');
  }

  // Market timing: cheapest live price vs 30-day average (persisted market
  // history) — 'renting expensive right now?'. Mini Chart.js line.
  let _rentalsTimingChart = null;
  function _renderRentalsMarketTiming() {
    const wrap = document.getElementById('rentals-timing');
    if (!wrap || !_rentalsData) return;
    // Click-first: the whole timing block links to the Hash Market module so
    // the operator can compare the real live prices behind the summary.
    if (!wrap.getAttribute('data-timing-click')) {
      wrap.setAttribute('data-timing-click', '1');
      wrap.addEventListener('click', () => { activateModule('market'); });
    }
    const trend = _rentalsData.market_trend;
    if (!trend || !trend.points || trend.points.length < 2) { wrap.hidden = true; return; }
    wrap.hidden = false;
    const s = trend.summary || {};
    const sumEl = document.getElementById('rentals-timing-summary');
    if (sumEl) {
      // Honest label: 'hoje' only when the newest recorded point IS today;
      // a box where polling stopped shows 'último registro dd' instead.
      const newestDay = trend.points[trend.points.length - 1].day;
      const isToday = newestDay === new Date().toISOString().slice(0, 10);
      const when = isToday ? 'hoje' : 'último ' + newestDay;
      const dir = s.vs_avg_pct == null ? '' : (s.vs_avg_pct >= 0 ? ' · ' + when + ' ' + s.vs_avg_pct.toFixed(0) + '% ACIMA da média 30d (caro)' : ' · ' + when + ' ' + Math.abs(s.vs_avg_pct).toFixed(0) + '% ABAIXO da média 30d (barato)');
      sumEl.textContent = when + ' ' + Number(s.current_sats_per_thh).toFixed(0) + ' · média 30d ' + Number(s.avg_sats_per_thh).toFixed(0) + ' st/TH·h' + dir;
    }
    if (_rentalsTimingChart) { _rentalsTimingChart.destroy(); _rentalsTimingChart = null; }
    if (typeof Chart === 'undefined') return;
    const canvas = document.getElementById('rentals-timing-chart');
    if (!canvas) return;
    _rentalsTimingChart = new Chart(canvas.getContext('2d'), {
      type: 'line',
      data: {
        labels: trend.points.map(p => p.day.slice(5)),
        datasets: [{
          label: 'cheapest sats/TH·h',
          data: trend.points.map(p => p.sats_per_thh),
          borderColor: 'rgb(255,215,0)', backgroundColor: 'rgba(255,215,0,0.08)',
          tension: 0.3, pointRadius: 0, fill: true,
        }]
      },
      options: {
        responsive: true, maintainAspectRatio: false,
        plugins: { legend: { display: false } },
        scales: {
          x: { ticks: { color: '#5E5952', font: { size: 8 }, maxTicksLimit: 8 }, grid: { display: false } },
          y: { ticks: { color: '#5E5952', font: { size: 8 } }, grid: { color: 'rgba(94,89,82,0.12)' } }
        }
      }
    });
  }

  // CFO: difficulty-adjustment forecast — next retarget from the LOCAL block
  // cadence (snapshots table), 'difficulty +X% em ~N h' verdict for timing
  // rental durations around the adjustment. Rendered inside MARKET TIMING.
  function _renderRentalsForecast() {
    const el = document.getElementById('rentals-timing-forecast');
    if (!el || !_rentalsData) return;
    const f = _rentalsData.difficulty_forecast;
    if (!f || !f.available) { el.hidden = true; return; }
    el.hidden = false;
    const cls = f.direction === 'up' ? 'is-up' : (f.direction === 'down' ? 'is-down' : 'is-flat');
    const arrow = f.direction === 'up' ? '▲' : (f.direction === 'down' ? '▼' : '◆');
    const chg = (f.projected_change_pct >= 0 ? '+' : '') + Number(f.projected_change_pct).toFixed(0) + '%';
    el.className = 'rentals-timing__forecast ' + cls;
    el.innerHTML = '<span class="rentals-timing__fc-icon">' + arrow + '</span>' +
      '<span class="rentals-timing__fc-body"><b>PRÓXIMO AJUSTE DE DIFF</b> · ' +
      escapeHtml(chg) + ' em ~' + Number(f.hours_to_adjustment).toFixed(0) + 'h ' +
      '(blocos a cada ' + Number(f.avg_block_time_s).toFixed(0) + 's)' +
      '<div class="rentals-timing__fc-verdict">' + escapeHtml(String(f.verdict || '')) + '</div></span>';
  }

  // Risk alerts fired on this panel load (worst-rig top-N + concentration) —
  // transient banner with severity coloring; dismissible.
  function _renderRentalsRiskBanner() {
    const wrap = document.getElementById('rentals-riskbanner');
    if (!wrap || !_rentalsData) return;
    const alerts = _rentalsData.risk_alerts_fired || [];
    if (!alerts.length) { wrap.hidden = true; wrap.innerHTML = ''; return; }
    wrap.hidden = false;
    wrap.innerHTML = alerts.map(a => {
      const sev = (a.severity || 'WARN') === 'CRIT' ? 'is-crit' : 'is-warn';
      const icon = (a.severity || 'WARN') === 'CRIT' ? '🚨' : '⚠️';
      return '<div class="rentals-riskbanner__item ' + sev + '">' + icon + ' ' +
        escapeHtml(String(a.message || '')) + '</div>';
    }).join('');
  }

  // CFO: market-signal banner — 'compras caras detectadas' (overpay) + 'janela
  // de arbitragem aberta'. Data comes DRY-RUN from /api/rentals.market_signals
  // (the webhook dedup is never consumed by the banner). Overpay item jumps to
  // the history tab; arbitrage item opens the Braiins buy flow.
  function _renderRentalsSignals() {
    const wrap = document.getElementById('rentals-signals');
    if (!wrap || !_rentalsData) return;
    const sig = _rentalsData.market_signals || {};
    const overpay = sig.overpay || [];
    const arb = sig.arbitrage || [];
    if (!overpay.length && !arb.length) { wrap.hidden = true; wrap.innerHTML = ''; return; }
    wrap.hidden = false;
    const items = [];
    if (overpay.length) {
      const crit = overpay.some(a => (a.severity || '') === 'CRIT');
      const total = overpay.length;
      const worst = overpay.reduce((m, a) => Math.max(m, Number(a.overpay_pct) || 0), 0);
      items.push('<div class="rentals-signals__item is-overpay' + (crit ? ' is-crit' : '') + '" data-signal="overpay" title="ver histórico — compras caras">' +
        '<span class="rentals-signals__icon">' + (crit ? '🚨' : '⚠️') + '</span>' +
        '<span class="rentals-signals__msg"><strong>' + total + ' compra(s) cara(s) detectada(s)</strong> — até ' + Math.round(worst) + '% acima do mercado na compra' +
        (overpay.length <= 3 ? ' · ' + overpay.map(a => '#' + escapeHtml(String(a.rental_id || '?')) + ' +' + Math.round(Number(a.overpay_pct) || 0) + '%').join(' · ') : '') + '</span>' +
        '<span class="rentals-signals__cta">VER HISTÓRICO →</span></div>');
    }
    if (arb.length) {
      const a = arb[0];
      // 'comprar agora' prefills the Braiins spot modal with the CURRENT
      // market price from the signal (dry-run, never the stale bid price).
      const mkt = Number(a.market_price_sats_per_thh) || 0;
      // Prefill TH = the tenant's TYPICAL order size (median of past rentals,
      // from the signal) — falls back to 1000 TH ≈ 1 PH/s on the frontend.
      const sugTh = Number(a.suggested_th) > 0 ? Number(a.suggested_th) : 0;
      const buyCta = mkt > 0
        ? '<button type="button" class="rentals-signals__buy" data-signal="arb-buy" data-price="' + mkt + '" data-th="' + sugTh + '" title="abrir compra Braiins com o preço atual pré-preenchido">⚡ COMPRAR AGORA</button>'
        : '<span class="rentals-signals__cta">COMPRAR →</span>';
      items.push('<div class="rentals-signals__item is-arb" data-signal="arb" title="abrir compra Braiins — janela aberta">' +
        '<span class="rentals-signals__icon">🏆</span>' +
        '<span class="rentals-signals__msg"><strong>JANELA DE ARBITRAGEM ABERTA</strong> — ' +
        escapeHtml(String(a.message || '')) + '</span>' + buyCta + '</div>');
    }
    wrap.innerHTML = items.join('');
    wrap.querySelectorAll('[data-signal]').forEach(function (el) {
      el.addEventListener('click', function (e) {
        e.stopPropagation();
        const kind = el.getAttribute('data-signal');
        if (kind === 'overpay') {
          _setRentalsFilter('history');
          document.getElementById('rentals-list')?.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
        } else if (kind === 'arb-buy') {
          // Prefill the modal with the signal's market price + the tenant's
          // TYPICAL order size (TH), so the user only confirms (budget
          // derived from both).
          openBraiinsBuyModal({
            price_sats_per_thh: parseFloat(el.getAttribute('data-price')) || 0,
            th: parseFloat(el.getAttribute('data-th')) || 0,
          });
        } else {
          openBraiinsBuyModal();
        }
      });
    });
  }

  // CFO: consolidated portfolio P/L (Issue #21-A) — PRÓPRIO self-mining EV
  // + RENTALS P/L + NET 30d. Hidden until any leg has data.
  function _renderPortfolioConsolidated() {
    const wrap = document.getElementById('portfolio-consolidated');
    if (!wrap) return;
    const gp = (_rentalsData && _rentalsData.global_portfolio) || {};
    const own = gp.own || {};
    const rent = gp.rentals || {};
    const comb = gp.combined || {};
    const hasOwn = own.hashrate_hs > 0;
    const hasRent = rent.pl_30d_sats != null || rent.pl_all_sats != null;
    if (!hasOwn && !hasRent) { wrap.hidden = true; return; }
    wrap.hidden = false;
    const set = function (id, v) {
      const el = document.getElementById(id);
      if (el) el.textContent = v;
    };
    const fmtSats = function (v, sign) {
      if (v === null || v === undefined) return '—';
      const n = Number(v);
      if (sign && n > 0) return '+' + n.toLocaleString('en-US') + ' sats';
      return n.toLocaleString('en-US') + ' sats';
    };
    set('portfolio-own-daily',
      own.daily_revenue_sats != null ? fmtSats(own.daily_revenue_sats) + '/dia' : '—');
    set('portfolio-own-month',
      own.month_revenue_sats != null ? fmtSats(own.month_revenue_sats) : '—');
    set('portfolio-rentals-30d', fmtSats(rent.pl_30d_sats, true));
    set('portfolio-rentals-all', fmtSats(rent.pl_all_sats, true));
    set('portfolio-net-30d',
      comb.pl_30d_sats != null ? fmtSats(comb.pl_30d_sats, true) : '—');
    const meta = document.getElementById('portfolio-consolidated-meta');
    if (meta) {
      const src = own.source === 'fleet' ? 'frota física'
        : own.source === 'worker' ? 'worker do pool' : '—';
      const hr = own.hashrate_th != null ? own.hashrate_th + ' TH/s' : 'sem hashrate';
      meta.textContent = own.hashrate_hs > 0
        ? ('ESTIMATE · ' + hr + ' (' + src + ')' + (own.estimate ? ' · EV' : ''))
        : 'ESTIMATE · sem hashrate próprio registrado';
    }
  }

  // CFO: portfolio time series — spent bars + estimated P/L (period and
  // cumulative) from the LOCAL rental_history. Bucket toggle week/month
  // re-fetches server-side data (the API ships the week bucket by default).
  let _rentalsSeriesChart = null;
  let _rentalsSeriesBucket = 'week';

  // Issue #146 (21-C): pure series-datasets builder (mirrored in the JS core
  // tests) — safe Number guards (NaN → null so the chart shows honest gaps),
  // own-EV + consolidated-total series included only when the backend sent
  // them (backward compatible with the pre-21-C payload).
  function buildPortfolioSeriesDatasets(points) {
    const rows = points || [];
    // null/undefined must stay null (Chart.js gap) — Number(null) is 0 and
    // would fabricate a flat 'no loss' bar on a cold box (honest telemetry).
    const num = function (v) {
      if (v === null || v === undefined) return null;
      const n = Number(v);
      return Number.isFinite(n) ? n : null;
    };
    const hasOwnEv = rows.some(function (p) { return num(p.own_ev_sats) != null; });
    return {
      labels: rows.map(function (p) { return String(p.label || '').replace(/^\d{4}-/, ''); }),
      spent: rows.map(function (p) { return num(p.spent_sats); }),
      pl: rows.map(function (p) { return num(p.pl_sats); }),
      cum: rows.map(function (p) { return num(p.cum_pl_sats); }),
      ownEv: rows.map(function (p) { return hasOwnEv ? num(p.own_ev_sats) : null; }),
      totalCum: rows.map(function (p) { return hasOwnEv ? num(p.cum_total_sats) : null; }),
      hasOwnEv: hasOwnEv
    };
  }

  function _renderRentalsSeries() {
    const wrap = document.getElementById('rentals-series');
    if (!wrap || !_rentalsData) return;
    const series = _rentalsData.portfolio_series;
    if (!series || !series.points || series.points.length < 1) { wrap.hidden = true; return; }
    wrap.hidden = false;
    const meta = document.getElementById('rentals-series-meta');
    if (meta) {
      const t = series.totals || {};
      const plTxt = t.pl_sats != null
        ? (t.pl_sats >= 0 ? '+' : '') + Number(t.pl_sats).toLocaleString('en-US', { maximumFractionDigits: 0 }) + ' sats'
        : '—';
      let m = (series.estimate ? 'P/L estimado · rede atual · ' : '') +
        (t.rentals != null ? t.rentals + ' aluguéis · ' : '') +
        (t.spent_sats != null ? Number(t.spent_sats).toLocaleString('en-US') + ' sats gastos · ' : '') +
        'P/L total ' + plTxt;
      // Issue #146: when the self-mining EV entered the account, surface the
      // consolidated total + the honest ESTIMATE note (EV, not realized).
      if (t.own_ev_sats != null) {
        const ownTxt = (t.own_ev_sats >= 0 ? '+' : '') +
          Number(t.own_ev_sats).toLocaleString('en-US', { maximumFractionDigits: 0 }) + ' sats';
        m += ' · PRÓPRIO EV ' + ownTxt + ' (ESTIMATE)';
        if (t.total_pl_sats != null) {
          const totTxt = (t.total_pl_sats >= 0 ? '+' : '') +
            Number(t.total_pl_sats).toLocaleString('en-US', { maximumFractionDigits: 0 }) + ' sats';
          m += ' · TOTAL ' + totTxt;
        }
      }
      meta.textContent = m;
    }
    if (_rentalsSeriesChart) { _rentalsSeriesChart.destroy(); _rentalsSeriesChart = null; }
    if (typeof Chart === 'undefined' || series.points.length < 1) return;
    const canvas = document.getElementById('rentals-series-chart');
    if (!canvas) return;
    const d = buildPortfolioSeriesDatasets(series.points);
    const datasets = [
      { type: 'bar', label: 'gasto (sats)', data: d.spent,
        backgroundColor: 'rgba(94,89,82,0.55)', borderRadius: 2, yAxisID: 'y' },
      { type: 'bar', label: 'P/L período (sats)', data: d.pl,
        backgroundColor: d.pl.map(v => v == null ? 'rgba(94,89,82,0.15)' : (v >= 0 ? 'rgba(0,200,83,0.55)' : 'rgba(255,23,68,0.55)')),
        borderRadius: 2, yAxisID: 'y' },
      { type: 'line', label: 'P/L acumulado (sats)', data: d.cum,
        borderColor: 'rgb(255,215,0)', backgroundColor: 'transparent',
        tension: 0.3, pointRadius: 2, borderWidth: 2, spanGaps: false, yAxisID: 'y' },
    ];
    if (d.hasOwnEv) {
      // Issue #146 (21-C): self-mining EV per bucket (constant daily
      // estimate × days) + the CONSOLIDATED cumulative (rentals P/L + own EV).
      datasets.push({ type: 'bar', label: 'PRÓPRIO EV (sats)', data: d.ownEv,
        backgroundColor: 'rgba(6,214,240,0.35)', borderColor: 'rgb(6,214,240)',
        borderWidth: 1, borderRadius: 2, yAxisID: 'y' });
      datasets.push({ type: 'line', label: 'TOTAL acumulado (sats)', data: d.totalCum,
        borderColor: 'rgb(6,214,240)', backgroundColor: 'transparent',
        tension: 0.3, pointRadius: 2, borderWidth: 2, borderDash: [5, 3], spanGaps: false, yAxisID: 'y' });
    }
    // null P/L (cold box / no computable yield) → gaps, never a flat 0 bar.
    _rentalsSeriesChart = new Chart(canvas.getContext('2d'), {
      type: 'bar',
      data: { labels: d.labels, datasets: datasets },
      options: {
        responsive: true, maintainAspectRatio: false,
        interaction: { mode: 'index', intersect: false },
        plugins: { legend: { display: false } },
        // Click-first: a bar = the exact list of rentals behind that week /
        // month (drill-down via /api/rentals/series/rentals, local table).
        onClick: (evt, elements) => {
          if (!elements || !elements.length) return;
          const idx = elements[0].index;
          const pt = series.points[idx];
          if (pt) openRentalsBucketDrill(pt.label, series.bucket || _rentalsSeriesBucket);
        },
        scales: {
          x: { ticks: { color: '#5E5952', font: { size: 9 }, maxTicksLimit: 12 }, grid: { display: false } },
          y: { ticks: { color: '#5E5952', font: { size: 9 } }, grid: { color: 'rgba(94,89,82,0.12)' } }
        }
      }
    });
  }

  // ── Series drill-down modal: rentals that make up a bar/week ───────────
  let _rentalsDrillBucket = 'week';

  async function openRentalsBucketDrill(label, bucket) {
    const modal = document.getElementById('rentals-drill-modal');
    if (!modal) return;
    _rentalsDrillBucket = bucket || _rentalsDrillBucket;
    modal.classList.add('active');
    const title = document.getElementById('rentals-drill-title');
    if (title) title.textContent = label + ' · rentals deste período';
    const body = document.getElementById('rentals-drill-body');
    if (body) body.innerHTML = '<div class="rentals-detail__loading">carregando…</div>';
    try {
      const r = await authFetch('/api/rentals/series/rentals?bucket=' + encodeURIComponent(_rentalsDrillBucket) + '&label=' + encodeURIComponent(label));
      if (!r.ok) {
        if (body) body.innerHTML = '<div class="rentals-detail__loading">sem dados deste período</div>';
        return;
      }
      const d = await r.json();
      const rows = d.rentals || [];
      if (!rows.length) {
        if (body) body.innerHTML = '<div class="rentals-detail__loading">nenhum aluguel neste período</div>';
        return;
      }
      const list = rows.map(x => {
        const plTxt = x.pl_sats != null
          ? (x.pl_sats >= 0 ? '+' : '') + Number(x.pl_sats).toLocaleString('en-US') + ' sats'
          : '—';
        const spentTxt = x.spent_sats != null ? Number(x.spent_sats).toLocaleString('en-US') + ' sats' : '—';
        const ext = x.rental_id && x.provider !== 'braiins'
          ? '<a class="rentals-item__ext" href="' + escapeHtml(_mrrRentalUrl(x.rental_id)) + '" target="_blank" rel="noopener" title="abrir no MRR">↗</a>'
          : '';
        return '<div class="rentals-drill__row" data-rental-id="' + escapeHtml(String(x.rental_id || '')) + '" data-provider="' + escapeHtml(x.provider || 'mrr') + '">' +
          '<span class="rentals-drill__name">#' + escapeHtml(String(x.rental_id || '—')) + ' · ' + escapeHtml(String(x.rig_name || '')) + ext + '</span>' +
          '<span class="rentals-drill__spent">' + escapeHtml(spentTxt) + '</span>' +
          '<strong class="' + (x.pl_sats != null && x.pl_sats < 0 ? 'is-bad' : 'is-good') + '">' + escapeHtml(plTxt) + '</strong>' +
          '</div>';
      }).join('');
      if (body) body.innerHTML = '<div class="rentals-drill__count">' + rows.length + ' aluguéis</div>' + list;
    } catch (e) {
      if (body) body.innerHTML = '<div class="rentals-detail__loading">erro ao carregar</div>';
    }
  }

  async function setRentalsSeriesBucket(bucket) {
    if (bucket === _rentalsSeriesBucket) return;
    _rentalsSeriesBucket = bucket;
    document.querySelectorAll('[data-series-bucket]').forEach(b =>
      b.classList.toggle('active', b.getAttribute('data-series-bucket') === bucket));
    try {
      const r = await authFetch('/api/rentals/series?bucket=' + bucket);
      if (!r.ok) return;
      const data = await r.json();
      if (data && data.points !== undefined) {
        _rentalsData.portfolio_series = data;
        _renderRentalsSeries();
      }
    } catch (e) { /* fail-closed: keep current bucket */ }
  }

  // ── Click-first analytics renderers (rankings / heatmap / expiring) ──
  // Every cell is a drill-down target: provider ranking → filter tab,
  // rig heatmap cell → rig track record, expiring row → rental detail.

  function _renderRentalsRankings() {
    const wrap = document.getElementById('rentals-rank');
    if (!wrap || !_rentalsData) return;
    const rows = _rentalsData.provider_rankings || [];
    if (!rows.length) { wrap.hidden = true; return; }
    wrap.hidden = false;
    const grid = document.getElementById('rentals-rank-grid');
    if (!grid) return;
    grid.innerHTML = rows.map(r => {
      const dlv = r.avg_delivery_pct != null ? Number(r.avg_delivery_pct).toFixed(1) + '%' : '—';
      const pl = r.avg_pl_pct != null
        ? (r.avg_pl_pct >= 0 ? '+' : '') + Number(r.avg_pl_pct).toFixed(1) + '%' : '—';
      const cost = r.avg_cost_sats_per_thh != null
        ? Number(r.avg_cost_sats_per_thh).toFixed(1) + ' st/TH·h' : '—';
      const tab = r.provider === 'braiins' ? 'contracts' : 'history';
      return '<div class="rentals-rank__cell" data-rentals-filter="' + escapeHtml(tab) + '" title="clique p/ ver os ' + escapeHtml(String(r.label)) + '">' +
        '<div class="rentals-rank__name">' + escapeHtml(String(r.label)) + ' <span class="rentals-rank__n">' + escapeHtml(String(r.rentals)) + '</span></div>' +
        '<div class="rentals-rank__row"><span>DELIVERY</span><strong>' + escapeHtml(dlv) + '</strong></div>' +
        '<div class="rentals-rank__row"><span>P/L</span><strong class="' + (r.avg_pl_pct != null && r.avg_pl_pct < 0 ? 'is-bad' : 'is-good') + '">' + escapeHtml(pl) + '</strong></div>' +
        '<div class="rentals-rank__row"><span>COST</span><strong>' + escapeHtml(cost) + '</strong></div>' +
        '</div>';
    }).join('');
  }

  function _renderRentalsHeatmap() {
    const wrap = document.getElementById('rentals-heatmap');
    if (!wrap || !_rentalsData) return;
    const cells = _rentalsData.rig_heatmap || [];
    if (!cells.length) { wrap.hidden = true; return; }
    wrap.hidden = false;
    const grid = document.getElementById('rentals-heatmap-grid');
    if (!grid) return;
    grid.innerHTML = cells.map(c => {
      // Color scale: green ≥95% delivery, amber 90-95%, red <90%.
      const pct = c.avg_delivery_pct;
      const cls = pct == null ? 'is-unknown' : (pct >= 95 ? 'is-good' : (pct >= 90 ? 'is-mid' : 'is-bad'));
      const cost = c.avg_cost_sats_per_thh != null
        ? Number(c.avg_cost_sats_per_thh).toFixed(0) + ' st/TH·h' : '—';
      return '<div class="rentals-heatmap__cell ' + cls + '" data-rig-name="' + escapeHtml(c.rig) + '" title="' + escapeHtml(c.rig) + ' · ' + escapeHtml(String(c.samples)) + ' amostras · clique p/ ver o track record">' +
        '<div class="rentals-heatmap__name">' + escapeHtml(c.rig) + '</div>' +
        '<div class="rentals-heatmap__row"><span>DELIVERY</span><strong>' + (pct != null ? pct.toFixed(1) + '%' : '—') + '</strong></div>' +
        '<div class="rentals-heatmap__row"><span>COST</span><strong>' + escapeHtml(cost) + '</strong></div>' +
        '<div class="rentals-heatmap__sub">' + escapeHtml(String(c.samples)) + ' amostras</div>' +
        '</div>';
    }).join('');
  }

  function _renderRentalsExpiring() {
    const wrap = document.getElementById('rentals-expiring');
    if (!wrap || !_rentalsData) return;
    const rows = _rentalsData.expiring || [];
    if (!rows.length) { wrap.hidden = true; return; }
    wrap.hidden = false;
    const meta = document.getElementById('rentals-expiring-meta');
    if (meta) meta.textContent = rows.length + ' rentals terminando';
    const list = document.getElementById('rentals-expiring-list');
    if (!list) return;
    list.innerHTML = rows.map(r => {
      const rid = r && r.id != null ? r.id : '';
      const name = (r && r.rig && r.rig.name) || '—';
      const left = r.ends_in_hours != null
        ? (r.ends_in_hours < 1 ? Math.round(r.ends_in_hours * 60) + 'min' : Number(r.ends_in_hours).toFixed(1) + 'h')
        : '—';
      return '<button class="rentals-expiring__row" data-rental-id="' + escapeHtml(String(rid)) + '" title="abrir rental #' + escapeHtml(String(rid)) + '">' +
        '<span class="rentals-expiring__name">#' + escapeHtml(String(rid)) + ' · ' + escapeHtml(name) + '</span>' +
        '<span class="rentals-expiring__time">' + escapeHtml(left) + '</span>' +
        '</button>';
    }).join('');
  }

  // ── Worst-rig leaderboard (CFO risk view) ──────────────────────────────
  // The counterpart to RECOMENDADOS: rigs that BURNED the operator — ranked
  // by EWMA delivery (recent rentals weigh more), failure rate, volatility
  // and a composite danger score. Rows click through to the rig track record.
  function _renderRentalsWorst() {
    const wrap = document.getElementById('rentals-worst');
    if (!wrap || !_rentalsData) return;
    const d = _rentalsData.worst_rigs || {};
    const rows = d.worst || [];
    if (!rows.length) { wrap.hidden = true; return; }
    wrap.hidden = false;
    const meta = document.getElementById('rentals-worst-meta');
    if (meta) {
      // Honest label: the local ledger mixes renter spend with owner income
      // (same convention as the heatmap) — said out loud, not hidden.
      meta.textContent = d.count + ' rigs com ≥' + (d.min_samples || 2) + ' amostras · EWMA · fail rate · volatilidade · gasto renter (local ledger)';
    }
    const list = document.getElementById('rentals-worst-list');
    if (!list) return;
    list.innerHTML = rows.map((r, i) => {
      // Color coding on the EWMA delivery: green ≥95%, amber 90-95%, red <90%.
      const ewma = r.ewma_delivery_pct;
      const dlvCls = ewma == null ? 'is-unknown' : (ewma >= 95 ? 'is-good' : (ewma >= 90 ? 'is-mid' : 'is-bad'));
      const danger = Number(r.danger_score || 0);
      const dangerCls = danger >= 70 ? 'is-critical' : (danger >= 45 ? 'is-warn' : 'is-mild');
      const pl = r.pl_sats_per_thh != null
        ? (r.pl_sats_per_thh >= 0 ? '+' : '') + Number(r.pl_sats_per_thh).toFixed(1) + ' st/TH·h'
        : '—';
      const trend = r.trend_pct != null
        ? '<span class="rentals-reco__trend ' + (r.trend_pct >= 0 ? 'is-good' : 'is-bad') + '">' +
          (r.trend_pct >= 0 ? '▲' : '▼') + Math.abs(Number(r.trend_pct)).toFixed(1) + '%</span>' : '';
      const blBadge = r.blacklisted
        ? '<span class="rentals-worst__badge rentals-worst__badge--bl" title="blacklist manual">BL</span>' : '';
      const autoBadge = r.auto_blacklisted
        ? '<span class="rentals-worst__badge rentals-worst__badge--auto" title="auto-excluído (grade F)">AUTO</span>' : '';
      // Same trust grade as the rig track record modal — one consistent story
      // between the leaderboard and the detail (never two scoring systems).
      const gradeBadge = r.grade
        ? '<span class="rentals-trust__badge rentals-trust__badge--' + escapeHtml(String(r.grade)) + '" title="trust grade (modal do rig)">' + escapeHtml(String(r.grade)) + '</span>' : '';
      return '<button class="rentals-worst__row" data-rig-id="' + escapeHtml(String(r.rig_id != null ? r.rig_id : '')) + '" data-rig-name="' + escapeHtml(String(r.name || '')) + '" title="clique p/ ver o track record do rig ' + escapeHtml(String(r.rig_id)) + '">' +
        '<span class="rentals-worst__rank">#' + (i + 1) + '</span>' +
        '<span class="rentals-worst__name">' + escapeHtml(String(r.name || r.rig_id)) + gradeBadge + blBadge + autoBadge + '</span>' +
        '<span class="rentals-worst__cell"><i>EWMA</i><b class="' + dlvCls + '">' + (ewma != null ? Number(ewma).toFixed(1) + '%' : '—') + '</b></span>' +
        '<span class="rentals-worst__cell"><i>Pior</i><b>' + (r.worst_pct != null ? Number(r.worst_pct).toFixed(0) + '%' : '—') + '</b></span>' +
        '<span class="rentals-worst__cell"><i>Fail</i><b>' + (r.fail_rate_pct != null ? Number(r.fail_rate_pct).toFixed(0) + '%' : '—') + '</b></span>' +
        '<span class="rentals-worst__cell"><i>Vol</i><b>' + (r.volatility_pct != null ? Number(r.volatility_pct).toFixed(1) + 'σ' : '—') + '</b></span>' +
        '<span class="rentals-worst__cell"><i>P/L TH·h</i><b class="' + (r.pl_sats_per_thh != null && r.pl_sats_per_thh < 0 ? 'is-bad' : 'is-good') + '">' + escapeHtml(pl) + '</b></span>' +
        '<span class="rentals-worst__cell"><i>P/L ' + escapeHtml(String(r.samples)) + 'x</i>' + trend + '</span>' +
        '<span class="rentals-worst__danger ' + dangerCls + '">' + Number(danger).toFixed(0) + '</span>' +
        '</button>';
    }).join('');
  }

  // ── Exposure allocation (Issue #21-B) ───────────────────────────────────
  // PRÓPRIO vs MRR vs BRAIINS — share do hashrate total gerenciado, com o
  // Herfindahl estendido incluindo o próprio como classe de ativo. Mesmo
  // idioma visual da concentração (barras de share + HHI honesto).
  function _renderRentalsExposure() {
    const wrap = document.getElementById('rentals-exposure');
    if (!wrap || !_rentalsData) return;
    const e = _rentalsData.exposure;
    if (!e || !e.available) { wrap.hidden = true; return; }
    wrap.hidden = false;
    const meta = document.getElementById('rentals-exposure-meta');
    const hhi = Number(e.hhi || 0);
    // Base HASHRATE (TH/s) — distinto do HHI de CONCENTRAÇÃO (base gasto em
    // sats): rótulo explícito para o CFO não comparar bases diferentes.
    if (meta) meta.textContent = 'HHI ' + hhi.toFixed(0) + ' · ' + (e.hhi_verdict || '') + ' (hashrate)';
    const bars = document.getElementById('rentals-exposure-bars');
    if (bars) {
      bars.innerHTML = (e.classes || []).map(c =>
        '<div class="rentals-conc__bar"><span class="rentals-conc__bar-label">' + escapeHtml(String(c.label)) + '</span>' +
        '<span class="rentals-conc__bar-track"><i style="width:' + Number(c.share_pct).toFixed(1) + '%"></i></span>' +
        '<span class="rentals-conc__bar-val">' + Number(c.share_pct).toFixed(0) + '% · ' +
        Number(c.hashrate_th).toLocaleString('en-US') + ' TH/s</span></div>').join('');
    }
    const total = document.getElementById('rentals-exposure-total');
    if (total) total.textContent = 'Hashrate gerenciado: ' + Number(e.total_hashrate_th).toLocaleString('en-US') + ' TH/s';
  }

  // ── Concentration risk (portfolio-level) ────────────────────────────────
  // If most spend sits with ONE provider or ONE rig, a single failure hits
  // the whole book. Shows share bars + the top rig + an honest HHI readout.
  function _renderRentalsConcentration() {
    const wrap = document.getElementById('rentals-conc');
    if (!wrap || !_rentalsData) return;
    const c = _rentalsData.concentration;
    if (!c || !c.available) { wrap.hidden = true; return; }
    wrap.hidden = false;
    const meta = document.getElementById('rentals-conc-meta');
    const hhi = Number(c.hhi || 0);
    const hhiTxt = hhi >= 5000 ? 'alta concentração' : (hhi >= 2500 ? 'concentração moderada' : 'diversificado');
    if (meta) meta.textContent = 'HHI ' + hhi.toFixed(0) + ' · ' + hhiTxt;
    const bars = document.getElementById('rentals-conc-bars');
    if (!bars) return;
    const provBars = (c.providers || []).map(p =>
      '<div class="rentals-conc__bar"><span class="rentals-conc__bar-label">' + escapeHtml(String(p.label)) + '</span>' +
      '<span class="rentals-conc__bar-track"><i style="width:' + Number(p.share_pct).toFixed(1) + '%"></i></span>' +
      '<span class="rentals-conc__bar-val">' + Number(p.share_pct).toFixed(0) + '% · ' +
      Number(p.spend_sats).toLocaleString('en-US') + ' sats</span></div>').join('');
    const rigTxt = c.top_rig
      ? '<span class="rentals-conc__rig">Top rig: <b>' + escapeHtml(String(c.top_rig.rig_name || c.top_rig.rig_id)) + '</b> — ' +
        Number(c.top_rig.share_pct).toFixed(0) + '% do gasto (' + Number(c.top_rig.spend_sats).toLocaleString('en-US') + ' sats)</span>'
      : '';
    bars.innerHTML = '<div class="rentals-conc__bars-row">' + provBars + '</div>' + rigTxt;
  }

  // ── Rig track record modal (recommendation card / heatmap cell click) ──
  // Reuses /api/rentals/rig (same analyze_rig shape as the detail route) so
  // a RECO card click shows the full verdict: trust grade, track record,
  // blacklist state — without opening a specific rental.

  async function openRigTrackRecord(rigId, rigName) {
    const modal = document.getElementById('rentals-rig-modal');
    if (!modal) return;
    const body = document.getElementById('rentals-rig-modal-body');
    if (body) body.innerHTML = '<div class="rentals-detail__loading">carregando track record…</div>';
    modal.classList.add('active');
    const title = document.getElementById('rentals-rig-modal-title');
    if (title) title.textContent = 'RIG · ' + (rigName || rigId || '');
    try {
      const q = new URLSearchParams();
      if (rigId) q.set('rig_id', String(rigId));
      if (rigName) q.set('rig_name', rigName);
      const r = await authFetch('/api/rentals/rig?' + q.toString());
      if (!r.ok) {
        if (body) body.innerHTML = '<div class="rentals-detail__loading">erro ao carregar rig</div>';
        return;
      }
      const data = await r.json();
      const trust = data.trust || {};
      const summary = data.summary || {};
      const hist = data.history || [];
      const grade = trust.grade || '—';
      const gradeCls = /^[A-F]$/.test(String(grade)) ? String(grade) : '';
      const badge = '<span class="rentals-trust__badge rentals-trust__badge--' + escapeHtml(gradeCls || 'none') + '">' + escapeHtml(String(grade)) + '</span>';
      const black = data.blacklisted ? '<span class="rentals-trust__flag is-bad">BLACKLISTED</span>' : '';
      const auto = data.auto_blacklisted ? '<span class="rentals-trust__flag is-mid">AUTO-EXCLUÍDO</span>' : '';
      const score = trust.score != null ? Number(trust.score).toFixed(0) : '—';
      const samples = summary.rentals != null ? summary.rentals + ' amostras' : '—';
      const avg = summary.avg_pct != null ? Number(summary.avg_pct).toFixed(1) + '%' : '—';
      const trend = summary.trend_pct != null
        ? (summary.trend_pct >= 0 ? '▲' : '▼') + Math.abs(Number(summary.trend_pct)).toFixed(1) + '%' : '—';
      const cost = summary.cost_avg_sats_thh != null
        ? Number(summary.cost_avg_sats_thh).toFixed(0) + ' st/TH·h' : '—';
      const histRows = hist.slice(0, 12).map(h => {
        const pct = h.percent != null ? Number(h.percent).toFixed(1) + '%' : '—';
        const paid = h.paid_sats != null ? Number(h.paid_sats).toLocaleString('en-US') + ' sats' : '—';
        const date = h.start || '';
        return '<div class="rentals-rig__hist-row"><span>' + escapeHtml(String(date)) + '</span>' +
          '<strong class="' + (h.percent != null && h.percent < 95 ? 'is-bad' : 'is-good') + '">' + escapeHtml(pct) + '</strong>' +
          '<span>' + escapeHtml(paid) + '</span></div>';
      }).join('');
      if (body) body.innerHTML =
        '<div class="rentals-rig__hero">' + badge + black + auto +
          ' <span class="rentals-rig__score">SCORE ' + score + '</span></div>' +
        '<div class="rentals-rig__stats">' +
          '<div class="rentals-rig__stat"><span>DELIVERY MÉDIO</span><strong>' + escapeHtml(avg) + '</strong></div>' +
          '<div class="rentals-rig__stat"><span>COST MÉDIO</span><strong>' + escapeHtml(cost) + '</strong></div>' +
          '<div class="rentals-rig__stat"><span>TREND</span><strong>' + escapeHtml(trend) + '</strong></div>' +
          '<div class="rentals-rig__stat"><span>AMOSTRAS</span><strong>' + escapeHtml(samples) + '</strong></div>' +
        '</div>' +
        '<div class="rentals-rig__hist">' + (histRows || '<div class="rentals-rig__none">sem track record local</div>') + '</div>' +
        (data.blacklisted
          ? '<button class="btn btn--mini" id="rentals-rig-unblacklist" data-rig-id="' + escapeHtml(String(rigId || '')) + '">♻ restaurar rig (remover da blacklist)</button>'
          : '<button class="btn btn--mini btn--danger" id="rentals-rig-blacklist" data-rig-id="' + escapeHtml(String(rigId || '')) + '">✕ nunca alugar este rig</button>');
      const blBtn = document.getElementById('rentals-rig-blacklist');
      const unBtn = document.getElementById('rentals-rig-unblacklist');
      const handler = (btn, method) => {
        if (!btn) return;
        btn.addEventListener('click', async () => {
          const id = btn.getAttribute('data-rig-id');
          try {
            const opts = { method: method };
            if (method === 'POST') opts.headers = { 'Content-Type': 'application/json' };
            const r = await authFetch('/api/rentals/rig/blacklist' + (method === 'DELETE' ? '?rig_id=' + encodeURIComponent(id) : ''), opts);
            if (!r.ok) return;
            openRigTrackRecord(rigId, rigName);  // re-render fresh state
          } catch (e) { /* fail-closed */ }
        });
      };
      handler(blBtn, 'POST');
      handler(unBtn, 'DELETE');
    } catch (e) {
      if (body) body.innerHTML = '<div class="rentals-detail__loading">erro ao carregar rig</div>';
    }
  }

  // ── Backtest modal: 'what if I rented X TH for Y hours?' ────────────────

  async function runBacktest() {
    const status = document.getElementById('backtest-status');
    if (status) status.textContent = 'calculando…';
    const th = parseFloat(document.getElementById('backtest-th').value || '0');
    const hours = parseFloat(document.getElementById('backtest-hours').value || '0');
    if (!(th > 0) || !(hours > 0)) {
      if (status) status.textContent = 'informe TH/s e horas válidos';
      return;
    }
    try {
      const r = await authFetch('/api/rentals/backtest?th=' + th + '&hours=' + hours);
      if (!r.ok) {
        if (status) status.textContent = 'backtest indisponível';
        return;
      }
      const d = await r.json();
      const out = document.getElementById('backtest-result');
      if (!out) return;
      const cost = d.cost_sats != null ? Number(d.cost_sats).toLocaleString('en-US') + ' sats' : '—';
      const yieldTxt = d.expected_yield_sats != null ? Number(d.expected_yield_sats).toLocaleString('en-US') + ' sats' : '—';
      const pl = d.pl_sats != null
        ? '<strong class="' + (d.pl_sats >= 0 ? 'is-good' : 'is-bad') + '">' + (d.pl_sats >= 0 ? '+' : '') + Number(d.pl_sats).toLocaleString('en-US') + ' sats</strong>' : '—';
      const mkt = d.market_sats_per_thh != null ? Number(d.market_sats_per_thh).toFixed(2) + ' st/TH·h' : '—';
      out.innerHTML =
        '<div class="backtest-row"><span>TH·h</span><strong>' + (d.thh != null ? Number(d.thh).toLocaleString('en-US') : '—') + '</strong></div>' +
        '<div class="backtest-row"><span>CUSTO (preço de mercado ' + escapeHtml(mkt) + ')</span><strong>' + cost + '</strong></div>' +
        '<div class="backtest-row"><span>YIELD BRUTO ESPERADO</span><strong>' + yieldTxt + '</strong></div>' +
        '<div class="backtest-row"><span>P/L</span>' + pl + '</div>' +
        (d.yield_known ? '' : '<div class="backtest-note">yield desconhecido (sem hashrate de rede) — só o custo é mostrado</div>');
      if (status) status.textContent = '';
    } catch (e) {
      if (status) status.textContent = 'erro no backtest';
    }
  }

  function openBacktestModal() {
    const modal = document.getElementById('rentals-backtest-modal');
    if (!modal) return;
    const out = document.getElementById('backtest-result');
    if (out) out.innerHTML = '—';
    const status = document.getElementById('backtest-status');
    if (status) status.textContent = '';
    modal.classList.add('active');
  }

  // ── External deep-links (click-first: ↗ opens the provider site) ───────
  // MRR rental: https://www.miningrigrentals.com/rental/{id}
  // MRR rig:    https://www.miningrigrentals.com/rigs/{id}
  // Braiins:    https://hashpower.braiins.com/ (SPA — no per-order URL)

  function _mrrRentalUrl(id) { return 'https://www.miningrigrentals.com/rental/' + encodeURIComponent(String(id)); }
  function _mrrRigUrl(id) { return 'https://www.miningrigrentals.com/rigs/' + encodeURIComponent(String(id)); }

  function _rentalCardHtml(r) {
    const st = _rentalStatus(r);
    const trust = _rentalRigTrust(r);
    const stCls = [
      r && r.ended ? 'rentals-item--ended' : (st === 'online' ? 'rentals-item--active' : ''),
      trust.blacklisted ? 'rentals-item--blacklisted' : '',
    ].filter(Boolean).join(' ');
    const name = (r && r.rig && r.rig.name) || (r && r.id) || '—';
    const region = (r && r.rig && r.rig.region) || '';
    const span = (r && r.start && r.end) ? (r.start + ' → ' + r.end) : '';
    // Trust grade badge (A-F) on the name line — a rig that under-delivers
    // is visible at a glance before opening the detail.
    const gradeBadge = trust.grade
      ? '<span class="rentals-item__trust rentals-item__trust--' + escapeHtml(trust.grade) + '" title="rig trust grade ' + escapeHtml(trust.grade) + ' (from track record)">' + escapeHtml(trust.grade) + '</span>'
      : '';
    // Click-first: ↗ opens THIS rental on the provider site (real detail,
    // not just our local estimate) — MRR rental URL or Braiins dashboard.
    const rid = r && r.id != null ? String(r.id) : '';
    const rigId = (r && r.rig && r.rig.id != null) ? String(r.rig.id) : '';
    const extUrl = rid ? (r.provider === 'braiins'
      ? 'https://hashpower.braiins.com/'
      : _mrrRentalUrl(rid)) : '';
    const extLink = extUrl
      ? '<a class="rentals-item__ext" href="' + escapeHtml(extUrl) + '" target="_blank" rel="noopener" title="abrir no site do provider" onclick="event.stopPropagation()">↗</a>'
      : '';
    // Rig id is a real MRR profile page — a deep-link to who actually owns
    // the rig, so the operator can check the rig before re-renting.
    const rigLink = rigId && r.provider !== 'braiins'
      ? '<a class="rentals-item__riglink" href="' + escapeHtml(_mrrRigUrl(rigId)) + '" target="_blank" rel="noopener" onclick="event.stopPropagation()">rig #' + escapeHtml(rigId) + ' ↗</a>'
      : '';
    return '<div class="rentals-item ' + stCls + '" data-rental-id="' + escapeHtml(rid) + '">' +
      '<div class="rentals-item__main">' +
        '<div class="rentals-item__name">#' + escapeHtml(rid || '—') + ' · ' + escapeHtml(name) + gradeBadge + extLink + '</div>' +
        '<div class="rentals-item__meta">' + escapeHtml(region || '') + (span ? ' · ' + escapeHtml(span) : '') + (rigLink ? ' · ' + rigLink : '') + '</div>' +
      '</div>' +
      '<div class="rentals-item__stats">' +
        '<div class="rentals-item__stat"><span class="rentals-item__stat-label">HASHRATE</span><span class="rentals-item__stat-value">' + _rentalHashrateStr(r) + '</span></div>' +
        '<div class="rentals-item__stat"><span class="rentals-item__stat-label">PAID</span><span class="rentals-item__stat-value">' + _rentalPriceStr(r) + '</span></div>' +
        '<div class="rentals-item__stat"><span class="rentals-item__stat-label">LENGTH</span><span class="rentals-item__stat-value">' + (r && r.length_hours != null ? Number(r.length_hours).toFixed(1) + 'h' : '—') + '</span></div>' +
      '</div>' +
      '<div class="rentals-item__status">' + escapeHtml(st) + '</div>' +
    '</div>';
  }

  async function loadRentals() {
    const listEl = document.getElementById('rentals-list');
    if (!listEl) return false;
    try {
      // authFetch sends the user's Bearer token so the server resolves the
      // caller's TENANT — with 1000+ users each one sees only their own
      // Braiins/MRR credentials and rentals (never the operator's key).
      const r = await authFetch('/api/rentals');
      if (!r.ok) return false;
      _rentalsData = await r.json();
      // UX: on the first load, land on the first tab that actually has data —
      // an empty 'Active' default used to hide the History tab (e.g. the
      // operator has 0 active rentals but 34 completed ones). Manual tab
      // clicks always win afterwards.
      if (!_rentalsAutoTabbed) {
        _rentalsAutoTabbed = true;
        const mrr = _rentalsData.mrr || {};
        const braiins = _rentalsData.braiins || {};
        const counts = {
          active: (mrr.active || []).length,
          history: (mrr.history || []).length,
          owner: (mrr.owner || []).length,
          contracts: (braiins.contracts || []).length,
        };
        if (counts.active === 0) {
          const first = ['history', 'owner', 'contracts'].find(k => counts[k] > 0);
          if (first) _setRentalsFilter(first);
        }
      }
      renderRentals();
      return true;
    } catch (e) { return false; }
  }

  function renderRentals() {
    const listEl = document.getElementById('rentals-list');
    if (!listEl || !_rentalsData) return;
    const mrr = _rentalsData.mrr || {};
    const braiins = _rentalsData.braiins || {};

    const cnt = document.getElementById('rentals-count-badge');
    if (cnt) {
      const total = (mrr.active || []).length + (mrr.history || []).length +
        (mrr.owner || []).length + (braiins.contracts || []).length;
      cnt.textContent = total + ' rentals';
    }
    const el = (id) => document.getElementById(id);
    // Strip shows the MRR-reported TOTAL (the list is capped at 25/50 by the
    // API) — honest count of the operator's rentals, not just the fetched page.
    // Missing provider credentials → 🔑 hint (with tooltip) instead of a
    // misleading 0/— that looks like an empty account.
    const _stripVal = (cardId, value, auth, err, authRejected, provider) => {
      const card = el(cardId);
      if (!card) return;
      // A configured-but-rejected key (401/403 / Bad Nonce) is an ERROR, not
      // a missing credential — show ⚠ with the FIX so the user knows to
      // regenerate the key, not just add one (Issue #152).
      const rejected = rentalsAuthRejected(err, authRejected);
      if (auth && !rejected) {
        card.textContent = '🔑';
        card.title = 'credentials missing — configure in Settings (⚙)';
      } else if (rejected) {
        card.textContent = '⚠';
        card.title = rentalsAuthGuide(provider, err);
      } else if (err) {
        card.textContent = '⚠';
        card.title = String(err);
      } else {
        card.textContent = value;
        card.title = '';
      }
    };
    _stripVal('rentals-mrr-active', mrr.total_active != null ? mrr.total_active : (mrr.active || []).length, mrr.needs_auth, mrr.error, mrr.auth_rejected, 'mrr');
    _stripVal('rentals-mrr-history', mrr.total_history != null ? mrr.total_history : (mrr.history || []).length, mrr.needs_auth, mrr.error, mrr.auth_rejected, 'mrr');
    _stripVal('rentals-mrr-owner', mrr.total_owner != null ? mrr.total_owner : (mrr.owner || []).length, mrr.needs_auth, mrr.error, mrr.auth_rejected, 'mrr');
    _stripVal('rentals-braiins', (braiins.contracts || []).length, braiins.needs_auth, braiins.error, braiins.auth_rejected, 'contracts');
    _renderRentalsPortfolio();
    _renderPortfolioConsolidated();
    _renderRentalsSeries();
    _renderRentalsReco();
    _renderRentalsAccepted();
    _renderRentalsAutoExclusions();
    _renderRentalsMarketTiming();
    _renderRentalsRankings();
    _renderRentalsHeatmap();
    _renderRentalsExpiring();
    _renderRentalsWorst();
    _renderRentalsConcentration();
    _renderRentalsExposure();
    _renderRentalsForecast();
    _renderRentalsRiskBanner();
    _renderRentalsSignals();

    let items = [];
    if (_rentalsFilter === 'active') items = mrr.active || [];
    else if (_rentalsFilter === 'history') items = mrr.history || [];
    else if (_rentalsFilter === 'owner') items = mrr.owner || [];
    else if (_rentalsFilter === 'contracts') items = (braiins.contracts || []).map(c => ({
      // Ended contracts must render dimmed like MRR history rows (previously
      // hardcoded false — every Braiins row looked 'active').
      id: c.id,
      ended: !!(c.ended_at) || /finish|complete|ended|done|cancel|expire/i.test(String(c.status || '')),
      provider: 'braiins',
      rig: { name: 'Braiins contract', status: c.status, region: '' },
      hashrate_advertised_th: c.speed_limit_ph ? c.speed_limit_ph * 1000 : null,
      price_paid_btc: c.amount_sat != null ? c.amount_sat / 1e8 : null,
      length_hours: null, start: c.started_at || null, end: c.ended_at || null,
    }));

    // CFO: "hide bad rigs" toggle — excludes blacklisted + grade-F rigs so
    // the operator only sees rigs worth re-renting (count badge reflects it).
    const hideBad = document.getElementById('rentals-hide-bad');
    if (hideBad && hideBad.checked) {
      const before = items.length;
      items = items.filter(x => !_rentalIsBad(x));
      if (cnt && before !== items.length) {
        cnt.textContent = cnt.textContent.replace(/\d+ rentals/, items.length + ' shown');
      }
    }

    if (!items.length) {
      const isContracts = _rentalsFilter === 'contracts';
      const needsAuth = isContracts ? braiins.needs_auth : mrr.needs_auth;
      const errMsg = isContracts ? braiins.error : mrr.error;
      const authRejected = isContracts ? braiins.auth_rejected : mrr.auth_rejected;
      // "Key rejected" (401/403 / Bad Nonce with a CONFIGURED key) is NOT the
      // same as "credentials missing" — surface the real reason + the FIX so
      // the user regenerates the key, not just adds one (Issue #152).
      const rejected = rentalsAuthRejected(errMsg, authRejected);
      const title = rejected ? 'API key rejected' : (needsAuth ? 'Credentials required' : (errMsg ? 'Provider error' : 'No rentals'));
      listEl.innerHTML = '<div class="empty-state" style="grid-column:1/-1;border:none">' +
        '<div class="empty-state__icon">' + (rejected ? '🔑' : '⛁') + '</div>' +
        '<div class="empty-state__title">' + title + '</div>' +
        '<div class="empty-state__desc">' + (rejected
          ? rentalsAuthGuide(_rentalsFilter, errMsg)
          : (needsAuth
            ? (isContracts ? 'Add your Braiins Hashpower owner token to list contracts — where to get it: hashpower.braiins.com → API Tokens.' : 'Add your MiningRigRentals API key + secret to see history & performance — get them at miningrigrentals.com → My Account → API Access.')
            : (errMsg ? escapeHtml(errMsg) : 'No ' + _rentalsFilter + ' rentals on this account'))) + '</div>' +
        (needsAuth || rejected ? '<button type="button" class="btn btn--primary btn--mini" id="rentals-open-settings" style="margin-top:8px">⚙ OPEN SETTINGS</button>' : '') +
        '</div>';
      const cta = document.getElementById('rentals-open-settings');
      if (cta) cta.addEventListener('click', function() { openSettingsModal(); });
      return;
    }
    listEl.innerHTML = items.map(_rentalCardHtml).join('');
  }

  async function openRentalDetail(id, provider) {
    const panel = document.getElementById('rentals-detail');
    if (!panel) return;
    // Reset the auto-exclusion banner immediately — a stale
    // 'AUTO-EXCLUSÃO DISPARADA' from a previous detail must never linger
    // while the next detail's fetch is in flight (Issue #110).
    const autoExBanner = document.getElementById('rentals-detail-autoex');
    if (autoExBanner) autoExBanner.hidden = true;
    // Same reset for the auth-rejection strip (Issue #174) — a stale
    // 'API KEY REJECTED' from a previous detail must never linger.
    const authBannerEl = document.getElementById('rentals-detail-auth');
    if (authBannerEl) { authBannerEl.hidden = true; authBannerEl.innerHTML = ''; }
    try {
      // Braiins: the contract's static fields are already in the list payload
      // — send them so the backend skips re-probing the list (detail needs
      // only the speed series; faster on mobile and fewer API calls).
      let body = null;
      let url = '/api/rentals/detail?provider=' + encodeURIComponent(provider) + '&id=' + encodeURIComponent(id);
      if (provider === 'braiins') {
        const braiins = (_rentalsData && _rentalsData.braiins) || {};
        const contract = (braiins.contracts || []).find(c => String(c.id) === String(id));
        body = JSON.stringify({ provider: 'braiins', id: id, contract: contract || {} });
        url = '/api/rentals/detail';
      }
      // authFetch (not plain fetch) — tenant-scoped: the server resolves the
      // caller's tenant from the Bearer token to fetch THEIR contracts.
      const r = await authFetch(url, {
        method: body ? 'POST' : 'GET',
        headers: body ? { 'Content-Type': 'application/json' } : undefined,
        body: body,
      });
      if (!r.ok) return;
      const data = await r.json();
      // Auth-rejection guide (Issue #174): a CONFIGURED but rejected key
      // (Bad Nonce / 401/403) on the detail click explains the SAME fix the
      // list already shows — regenerate the key, not a generic error.
      const authBanner = document.getElementById('rentals-detail-auth');
      if (authBanner) {
        const dErr = (data.detail && data.detail.error) || '';
        const rejected = rentalsAuthRejected(dErr, data.auth_rejected);
        if (rejected) {
          authBanner.hidden = false;
          authBanner.innerHTML =
            '<span class="rentals-detail__autoex-icon">🔑</span>' +
            '<div class="rentals-detail__autoex-body"><strong>API KEY REJECTED</strong>' +
            '<div class="rentals-detail__autoex-sub">' + rentalsAuthGuide(provider, dErr) +
            '</div></div>' +
            '<button type="button" class="rentals-detail__autoex-btn" id="rentals-detail-auth-settings" title="abrir Settings para regenerar a chave">⚙ OPEN SETTINGS</button>';
          const authCta = document.getElementById('rentals-detail-auth-settings');
          if (authCta) authCta.addEventListener('click', function() { openSettingsModal(); });
        } else {
          authBanner.hidden = true;
          authBanner.innerHTML = '';
        }
      }
      // Auto-exclusion feedback (Issue #110): ONLY the detail call that
      // PERFORMED the exclusion shows the banner + toast and pre-adds the
      // card to the AUTO-EXCLUSÕES section — reopening an already-excluded
      // rig never re-fires (auto_excluded_now is false then). The banner
      // was already hidden at the top of this function.
      if (autoExBanner && data.auto_excluded_now) {
        const rule = data.auto_exclude_rule || {};
        const nAlert = Number(data.auto_exclude_alert_dispatched) || 0;
        const ruleStr = 'floor ' + escapeHtml(String(rule.grade_floor || 'F')) +
          ' · mín ' + escapeHtml(String(rule.min_samples != null ? rule.min_samples : 2));
        // The exact ledger row the AUTO-EXCLUSÕES section shows — also feeds
        // the undo button's rig id (Issue #117).
        const entry = data.auto_exclude_entry;
        const bannerRigId = entry && entry.rig_id != null ? String(entry.rig_id)
          : (data.detail && data.detail.rig && data.detail.rig.id != null
             ? String(data.detail.rig.id) : '');
        autoExBanner.hidden = false;
        autoExBanner.innerHTML =
          '<span class="rentals-detail__autoex-icon">🤖</span>' +
          '<div class="rentals-detail__autoex-body">' +
          '<strong>AUTO-EXCLUSÃO DISPARADA</strong>' +
          '<div class="rentals-detail__autoex-sub">régua vigente: ' + ruleStr +
          (nAlert ? ' · alerta webhook/push enviado' : ' · sem canal de alerta configurado (Settings → alertas)') +
          '</div></div>' +
          (bannerRigId
            ? '<button type="button" class="rentals-detail__autoex-btn" id="rentals-detail-autoex-undo" title="desfazer a auto-exclusão e restaurar o rig">↩ DESFAZER</button>'
            : '');
        showToast('success', 'Rig auto-excluído por sub-entrega' + (nAlert ? ' — alerta enviado' : ''));
        // Pre-add the card to the AUTO-EXCLUSÕES section (same local) —
        // dedup by rig_id so a stale entry from an earlier fetch never
        // duplicates. The entry is the exact ledger row the section shows.
        if (entry && entry.rig_id != null && _rentalsData) {
          const ax = (_rentalsData.auto_exclusions = _rentalsData.auto_exclusions || {});
          ax.exclusions = ax.exclusions || [];
          ax.exclusions = ax.exclusions.filter(function (x) {
            return String(x.rig_id) !== String(entry.rig_id);
          });
          ax.exclusions.unshift(entry);
          ax.count = ax.exclusions.length;
          _renderRentalsAutoExclusions();
        }
        // Undo (Issue #117): restaura o rig com confirmação — o backend
        // remove das DUAS blacklists e marca o veredito REVOGADA no ledger
        // (remove_rig_from_blacklist); o detail re-abre sem o banner e o
        // trust re-renderiza sem o estado auto-excluído. Re-exclusão
        // automática volta se o histórico de entrega continuar ruim.
        const undoBtn = document.getElementById('rentals-detail-autoex-undo');
        if (undoBtn && bannerRigId) {
          undoBtn.addEventListener('click', async () => {
            if (!window.confirm('Restaurar o rig ' + bannerRigId + '? A auto-exclusão será revogada — se a entrega continuar ruim, o piloto re-exclui automaticamente.')) return;
            try {
              const r = await authFetch('/api/rentals/rig/blacklist', {
                method: 'DELETE',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ rig_id: bannerRigId }),
              });
              if (!r.ok) return;
              showToast('success', 'Rig ' + bannerRigId + ' restaurado — auto-exclusão revogada');
              // Re-open so trust/blacklist re-render fresh (banner resets).
              openRentalDetail(id, provider);
            } catch (e) { /* fail-closed */ }
          });
        }
      }
      const d = data.detail || {};
      const g = data.graph || {};
      const lg = data.log || {};
      const market = data.market || {};         // cheapest live price (sats/TH/h)
      const rigHistory = data.rig_history || []; // same-rig past rentals
      const title = document.getElementById('rentals-detail-title');
      if (title) title.textContent = (provider === 'braiins' ? 'Braiins contract #' : 'MRR rental #') + id;
      const grid = document.getElementById('rentals-detail-grid');
      const hr = d.hashrate || {};
      const rows = [
        ['Owner', d.owner || '—'],
        ['Renter', d.renter || '—'],
        ['Advertised', hr.advertised ? (hr.advertised.nice || hr.advertised.hash || '—') : '—'],
        ['Average', hr.average ? (hr.average.nice || '—') + (hr.average.percent != null ? ' (' + hr.average.percent + '%)' : '') : '—'],
        ['Paid', d.price && d.price.paid != null ? (Number(d.price.paid) * 1e8).toFixed(0) + ' sats' : '—'],
        ['Length', d.length != null ? d.length + 'h' : '—'],
        ['Rig', d.rig && d.rig.name ? d.rig.name : '—'],
        ['Region', d.rig && d.rig.region ? d.rig.region : '—'],
        ['Start', d.start || '—'],
        ['End', d.end || '—'],
      ];
      grid.innerHTML = rows.map(x => '<div class="rentals-detail__row"><span>' + escapeHtml(x[0]) + '</span><strong>' + escapeHtml(String(x[1])) + '</strong></div>').join('');
      // Performance verdict — how THIS rental delivered vs what was paid, so
      // the operator can compare rigs/providers before renting again.
      const perfEl = document.getElementById('rentals-detail-perf');
      if (perfEl) {
        const adv = hr.advertised, avg = hr.average;
        const advTh = adv ? _mrToTh(adv.hash, adv.type) : null;
        const avgTh = avg ? _mrToTh(avg.hash, avg.type) : null;
        const pct = avg && avg.percent != null ? parseFloat(avg.percent)
          : (avgTh && advTh ? (avgTh / advTh) * 100 : null);
        const lenH = d.length != null ? parseFloat(d.length) : 0;
        const paidSats = d.price && d.price.paid != null ? parseFloat(d.price.paid) * 1e8 : null;
        const costPerThHour = (paidSats != null && avgTh && lenH) ? paidSats / (avgTh * lenH) : null;
        const delivered = (avgTh && lenH) ? avgTh * lenH : null;
        // Backend pre-computes analytics for BOTH providers (Braiins from the
        // speed series, MRR from the raw detail) — prefer those so the banner
        // renders even when the series is empty or sparse.
        const perf = data.perf || d.perf || {};
        const avgThFinal = perf.avg_th != null ? perf.avg_th : avgTh;
        const pctFinal = perf.percent != null ? perf.percent : pct;
        const costFinal = perf.cost_sats_per_thh != null ? perf.cost_sats_per_thh : costPerThHour;
        const deliveredFinal = perf.delivered_thh != null ? perf.delivered_thh : delivered;
        let cls = '', verdict = '—';
        if (pctFinal != null) {
          cls = pctFinal >= 95 ? 'is-good' : (pctFinal >= 80 ? 'is-warn' : 'is-bad');
          verdict = pctFinal.toFixed(1) + '% of advertised';
        }
        // VS MARKET — effective cost vs the cheapest live rental price today
        // (negative % = this rental was cheaper than renting again now).
        let mktVal = '—', mktCls = '', mktTitle = '';
        if (market.available && market.price_sats_per_thh != null && costFinal != null) {
          const diff = ((costFinal - market.price_sats_per_thh) / market.price_sats_per_thh) * 100;
          mktCls = diff <= 0 ? 'is-good' : 'is-bad';
          mktVal = (diff <= 0 ? '−' : '+') + Math.abs(diff).toFixed(0) + '% vs mkt';
          mktTitle = 'market ' + market.price_sats_per_thh.toFixed(2) + ' sats/TH/h (' + (market.provider || '') + ')';
        }
        // P/L — the economic verdict: expected GROSS yield (network hashrate)
        // vs what was paid, computed server-side. Negative = this rental paid
        // more than the hashrate produced at current difficulty.
        const pl = data.pl || {};
        let yieldVal = '—', plVal = '—', plCls = '', plTitle = '';
        if (pl.expected_yield_sats_per_thh != null) {
          yieldVal = Number(pl.expected_yield_sats_per_thh).toFixed(2) + ' st/TH·h';
        }
        if (pl.pl_sats != null) {
          const sign = pl.pl_sats >= 0 ? '+' : '';
          plVal = sign + Number(pl.pl_sats).toFixed(0) + ' sats';
          plCls = pl.pl_sats >= 0 ? 'is-good' : 'is-bad';
          plTitle = pl.pl_pct != null
            ? 'yield vs cost: ' + (pl.pl_sats >= 0 ? '+' : '') + Number(pl.pl_pct).toFixed(1) + '% (gross yield, no pool fee)'
            : 'expected gross yield vs cost';
        }
        const cells = [
          { l: 'PERFORMANCE', v: verdict, c: cls },
          { l: 'AVG / ADVERTISED', v: avgThFinal ? fmt.hashrate(avgThFinal * 1e12) + ' / ' + fmt.hashrate((advTh || 0) * 1e12) : '—', c: '' },
          { l: 'COST', v: costFinal != null ? costFinal.toFixed(2) + ' sats/TH/h' : '—', c: '' },
          { l: 'YIELD (exp)', v: yieldVal, c: '', t: 'expected GROSS yield of 1 TH·h at the current network hashrate (before pool fee)' },
          { l: 'DELIVERED', v: deliveredFinal != null ? deliveredFinal.toFixed(0) + ' TH·h' : '—', c: '' },
          { l: 'P/L', v: plVal, c: plCls, t: plTitle },
          { l: 'VS MARKET', v: mktVal, c: mktCls, t: mktTitle },
        ];
        perfEl.innerHTML = cells.map(c =>
          '<div class="rentals-perf__cell' + (c.c ? ' ' + escapeHtml(c.c) : '') + '"' + (c.t ? ' title="' + escapeHtml(c.t) + '"' : '') + '><span class="rentals-perf__label">' + escapeHtml(c.l) + '</span><strong>' + escapeHtml(String(c.v)) + '</strong></div>'
        ).join('');
      }
      // RIG TRUST (CFO) — grade A-F + score + consistency for THIS rig, with
      // a one-click blacklist button so bad performers are excluded everywhere.
      const trustEl = document.getElementById('rentals-detail-trust');
      const rigId = (d.rig && d.rig.id != null) ? String(d.rig.id) : null;
      if (trustEl) {
        const ra = data.rig_analysis || {};
        const trust = ra.trust || {};
        // Auto-excluded (grade-F streak) counts as blacklisted for the UI —
        // the verdict distinguishes AUTO from manual so the CFO knows why.
        const bl = !!ra.blacklisted;
        const autoBl = !!ra.auto_blacklisted;
        const grade = trust.grade;
        if (rigId && (trust.samples > 0 || bl)) {
          trustEl.hidden = false;
          const sum = ra.summary || {};
          const gCls = grade || '';
          const gradeHtml = grade
            ? '<span class="rentals-trust__badge rentals-trust__badge--' + escapeHtml(gCls) + '">GRADE ' + escapeHtml(gCls) + ' · ' + escapeHtml(String(trust.label || '')) + '</span>'
            : '<span class="rentals-trust__badge">NO TRACK RECORD YET</span>';
          const trend = sum.trend_pct;
          const trendStr = trend == null ? '—'
            : (trend >= 0 ? '▲ ' : '▼ ') + Math.abs(trend).toFixed(1) + '%';
          const cells = [
            { l: 'RIG TRUST', v: gradeHtml, cls: '' },
            { l: 'SCORE', v: trust.score != null ? trust.score.toFixed(1) + ' / 100' : '—', cls: gCls },
            { l: 'MEDIAN DELIVERY', v: trust.median_pct != null ? trust.median_pct.toFixed(1) + '%' : '—', cls: '' },
            { l: 'WORST DELIVERY', v: trust.worst_pct != null ? trust.worst_pct.toFixed(1) + '%' : '—', cls: '' },
            { l: 'CONSISTENCY (MAD)', v: trust.mad_pct != null ? '±' + trust.mad_pct.toFixed(1) + '%' : '—', cls: '' },
            { l: 'SAMPLES', v: trust.samples != null ? trust.samples : '—', cls: '' },
            { l: 'AVG COST', v: sum.cost_avg_sats_thh != null ? sum.cost_avg_sats_thh.toFixed(1) + ' st/TH·h' : '—', cls: '' },
            { l: 'TREND (last 3)', v: trendStr, cls: trend == null ? '' : (trend >= 0 ? 'is-good' : 'is-bad') },
          ];
          let verdict = '', vCls = '';
          if (autoBl) {
            verdict = '🤖 AUTO-EXCLUÍDO: 2+ amostras com grade F (under-delivery). Restaure para ver de novo — re-exclui enquanto o histórico de entrega não melhora.';
            vCls = 'rentals-trust__verdict--bad';
          } else if (bl) {
            verdict = '⛔ Este rig está na sua BLACKLIST — não alugue de novo.';
            vCls = 'rentals-trust__verdict--bad';
          } else if (grade === 'A' || grade === 'B') {
            verdict = '✓ Rig confiável — consistente nas entregas. Pode alugar de novo.';
            vCls = 'rentals-trust__verdict--good';
          } else if (grade === 'C') {
            verdict = '⚠ Rig mediano — entregas inconsistentes. Compare com o track record antes de alugar.';
            vCls = 'rentals-trust__verdict--warn';
          } else if (grade === 'D' || grade === 'F') {
            verdict = '⛔ Rig ruim — entrega bem abaixo do anunciado. Considere excluir (blacklist).';
            vCls = 'rentals-trust__verdict--bad';
          } else {
            verdict = 'Sem histórico suficiente deste rig — colete mais amostras antes de confiar.';
          }
          const btn = bl
            ? '<button type="button" class="rentals-trust__btn rentals-trust__btn--restore" id="rentals-trust-toggle">✓ RESTAURAR RIG</button>'
            : '<button type="button" class="rentals-trust__btn" id="rentals-trust-toggle">⛔ EXCLUIR RIG (BLACKLIST)</button>';
          trustEl.innerHTML =
            '<div class="rentals-trust__cells">' + cells.map(c =>
              '<div class="rentals-trust__cell"><span class="rentals-trust__label">' + escapeHtml(c.l) + '</span><span class="rentals-trust__value' + (c.cls ? ' rentals-trust__value--' + escapeHtml(c.cls) : '') + '">' + escapeHtml(c.v) + '</span></div>'
            ).join('') + '</div>' +
            '<div class="rentals-trust__verdict ' + vCls + '">' + verdict + '</div>' +
            '<div class="rentals-trust__actions">' + btn + '</div>';
          const toggle = document.getElementById('rentals-trust-toggle');
          if (toggle) toggle.addEventListener('click', async () => {
            try {
              const r = await authFetch('/api/rentals/rig/blacklist', {
                method: bl ? 'DELETE' : 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ rig_id: rigId }),
              });
              if (!r.ok) return;
              // Re-open the detail so trust/blacklist re-render fresh.
              openRentalDetail(id, provider);
            } catch (e) { /* fail-closed */ }
          });
        } else {
          // Braiins contracts carry no rig identity → no delivery track
          // record. The speed series yields a STABILITY signal (CV) — show it
          // instead of a dead 'NO DATA' box.
          const stab = data.stability || {};
          if (stab && stab.cv_pct != null) {
            trustEl.hidden = false;
            const stCls = stab.grade === 'STABLE' ? 'is-good' : (stab.grade === 'MODERATE' ? 'is-warn' : 'is-bad');
            const stabCells = [
              { l: 'STABILITY', v: '<span class="rentals-trust__badge rentals-trust__badge--' + escapeHtml(String(stab.grade)) + '">' + escapeHtml(String(stab.grade)) + '</span>', cls: '' },
              { l: 'CV (SPEED)', v: Number(stab.cv_pct).toFixed(1) + '%', cls: stCls },
              { l: 'AVG SPEED', v: stab.mean_ph != null ? Number(stab.mean_ph).toFixed(1) + ' PH/s' : '—', cls: '' },
              { l: 'MIN–MAX', v: (stab.min_ph != null && stab.max_ph != null) ? Number(stab.min_ph).toFixed(1) + '–' + Number(stab.max_ph).toFixed(1) + ' PH' : '—', cls: '' },
              { l: 'SAMPLES', v: stab.label === 'NO DATA' ? '—' : 'series points', cls: '' },
            ];
            trustEl.innerHTML =
              '<div class="rentals-trust__cells">' + stabCells.map(c =>
                '<div class="rentals-trust__cell"><span class="rentals-trust__label">' + escapeHtml(c.l) + '</span><span class="rentals-trust__value' + (c.cls ? ' rentals-trust__value--' + escapeHtml(c.cls) : '') + '">' + escapeHtml(c.v) + '</span></div>'
              ).join('') + '</div>' +
              '<div class="rentals-trust__verdict">Contratos Braiins não expõem identidade de rig — a estabilidade vem da série de speed. CV &lt; 5% = previsível; &gt; 15% = arriscado.</div>';
          } else {
            trustEl.hidden = true;
          }
        }
      }
      // RIG TRACK RECORD — histórico de % por rig (same-rig past rentals) so
      // the operator can judge this rig's consistency before renting again.
      const rigEl = document.getElementById('rentals-detail-rig');
      if (rigEl) {
        if (!rigHistory.length) {
          if (_rentalsRigChart) { _rentalsRigChart.destroy(); _rentalsRigChart = null; }
          rigEl.hidden = true;
        } else {
          rigEl.hidden = false;
          // Entries WITH a measured percent only — labels and bars must come
          // from the SAME filtered list so null-percent rentals never shift
          // a bar off its label.
          const chartRows = rigHistory.filter(h => h.percent != null).slice(0, 8);
          const pcts = chartRows.map(h => h.percent);
          const avg = pcts.length ? pcts.reduce((a, b) => a + b, 0) / pcts.length : null;
          const best = pcts.length ? Math.max.apply(null, pcts) : null;
          const worst = pcts.length ? Math.min.apply(null, pcts) : null;
          const rigName = (d.rig && d.rig.name) || '';
          const rows = rigHistory.slice(0, 8).map(h => {
            const p = h.percent;
            const pCls = p == null ? '' : (p >= 95 ? 'is-good' : (p >= 80 ? 'is-warn' : 'is-bad'));
            const pStr = p != null ? p.toFixed(1) + '%' : '—';
            const costStr = h.cost_sats_per_thh != null ? Number(h.cost_sats_per_thh).toFixed(0) + ' st' : '—';
            return '<div class="rentals-rig__row"><span class="rentals-rig__id">#' + escapeHtml(String(h.id)) + '</span>' +
              '<span class="rentals-rig__date">' + escapeHtml(String(h.start || '—')) + '</span>' +
              '<span class="rentals-rig__cost">' + escapeHtml(costStr) + '</span>' +
              '<span class="rentals-rig__pct ' + pCls + '">' + escapeHtml(pStr) + '</span></div>';
          }).join('');
          rigEl.innerHTML =
            '<div class="rentals-rig__head">RIG TRACK RECORD' +
            (rigName ? ' · ' + escapeHtml(rigName) : '') +
            ' <span class="rentals-rig__sum">' + rigHistory.length + ' prior · avg ' +
            (avg != null ? avg.toFixed(1) + '%' : '—') +
            (best != null ? ' · best ' + best.toFixed(1) + '%' : '') +
            (worst != null ? ' · worst ' + worst.toFixed(1) + '%' : '') + '</span></div>' +
            (pcts.length >= 2 ? '<div class="rentals-rig__chart"><canvas id="rentals-rig-chart"></canvas></div>' : '') +
            '<div class="rentals-rig__rows">' + rows + '</div>';
          // Mini bar chart of % per prior rental (green/amber/red by band).
          if (pcts.length >= 2 && typeof Chart !== 'undefined') {
            const c2 = document.getElementById('rentals-rig-chart');
            if (c2) {
              if (_rentalsRigChart) { _rentalsRigChart.destroy(); _rentalsRigChart = null; }
              _rentalsRigChart = new Chart(c2.getContext('2d'), {
                type: 'bar',
                data: {
                  labels: chartRows.map(h => '#' + h.id),
                  datasets: [{
                    label: '% of advertised',
                    data: pcts,
                    backgroundColor: pcts.map(p => p >= 95 ? 'rgba(0,200,83,0.55)' : (p >= 80 ? 'rgba(255,160,0,0.55)' : 'rgba(255,23,68,0.55)')),
                    borderWidth: 0,
                  }]
                },
                options: {
                  responsive: true, maintainAspectRatio: false,
                  plugins: { legend: { display: false } },
                  scales: {
                    y: { min: 0, max: 110, ticks: { color: '#5E5952', font: { size: 8 }, callback: function (v) { return v + '%'; } }, grid: { color: 'rgba(94,89,82,0.12)' } },
                    x: { ticks: { color: '#5E5952', font: { size: 8 } }, grid: { display: false } }
                  }
                }
              });
            }
          }
        }
      }
      // Graph
      const bars = g.chartdata && g.chartdata.bars ? g.chartdata.bars : null;
      if (typeof Chart !== 'undefined') {
        const canvas = document.getElementById('rentals-detail-chart');
        if (canvas) {
          if (_rentalsDetailChart) { _rentalsDetailChart.destroy(); _rentalsDetailChart = null; }
          const labels = [];
          const values = [];
          if (bars && typeof bars === 'string') {
            // MRR format: "[[ts,hash],...]" (ms, hashrate in H/s)
            const m = bars.match(/\[(\d+),([^\]]+)\]/g) || [];
            m.slice(0, 120).forEach(pair => {
              const mm = pair.match(/\[(\d+),([^\]]+)\]/);
              if (mm) { labels.push(new Date(Number(mm[1])).toLocaleTimeString()); values.push(Number(mm[2]) / 1e12); }
            });
          } else if (Array.isArray(g.points)) {
            // Braiins contract speed comes in PH/s — normalize to TH/s so the
            // dataset matches the MRR bars (both plotted as hashrate TH/s).
            g.points.slice(0, 120).forEach(p => {
              // Accept seconds OR millisecond unix timestamps.
              let t = Number(p.ts);
              if (isFinite(t) && t > 0) {
                if (t < 1e12) t = t * 1000;  // seconds → ms
                labels.push(new Date(t).toLocaleTimeString());
              } else {
                labels.push('');
              }
              values.push(p.speed_ph != null ? p.speed_ph * 1000 : 0);
            });
          }
          if (values.length) {
            _rentalsDetailChart = new Chart(canvas.getContext('2d'), {
              type: 'line',
              data: { labels, datasets: [{ label: 'hashrate TH/s', data: values, borderColor: 'rgb(6,214,240)', backgroundColor: 'rgba(6,214,240,0.08)', tension: 0.4, pointRadius: 0, fill: true }] },
              options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false } } }
            });
          }
        }
      }
      // Log
      const logEl = document.getElementById('rentals-detail-log');
      if (logEl) {
        const items = (lg.rental_log || []).slice(0, 10);
        logEl.innerHTML = items.length
          ? items.map(l => '<div class="rentals-detail__log-item">' + escapeHtml(l.msg || '') + '</div>').join('')
          : '<div class="rentals-detail__log-item">no log entries</div>';
      }
      panel.hidden = false;
    } catch (e) { /* fail-closed: keep panel hidden */ }
  }

  function _initRentalsPanel() {
    const refresh = document.getElementById('rentals-refresh');
    if (refresh) refresh.addEventListener('click', () => {
      _rentalsLoaded = false;
      // Same shimmer as the first-activation skeleton — the table refreshes
      // under an overlay instead of flashing the stale rows.
      skelRefresh(document.getElementById('rentals-panel'), 'table', loadRentals());
    });
    // CFO: CSV export of the full rental ledger (portfólio + track record).
    // Shared downloader — mode 'simple' (default) or 'analysis' (Controle de
    // Rendimento: refund due, spread, real loss, sellers to blacklist).
    async function _downloadRentalsExport(mode, filename) {
      try {
        const q = mode === 'analysis' ? '?mode=analysis' : '';
        const r = await authFetch('/api/rentals/export' + q);
        if (!r.ok) return;
        const blob = await r.blob();
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = filename;
        document.body.appendChild(a);
        a.click();
        setTimeout(() => { URL.revokeObjectURL(url); a.remove(); }, 2000);
      } catch (e) { /* fail-closed */ }
    }
    const exportBtn = document.getElementById('rentals-export');
    if (exportBtn) exportBtn.addEventListener('click', () => _downloadRentalsExport('simple', 'rentals.csv'));
    const exportAnalysisBtn = document.getElementById('rentals-export-analysis');
    if (exportAnalysisBtn) exportAnalysisBtn.addEventListener('click', () => _downloadRentalsExport('analysis', 'rentals_analysis.csv'));
    const closeBtn = document.getElementById('rentals-detail-close');
    if (closeBtn) closeBtn.addEventListener('click', () => { const p = document.getElementById('rentals-detail'); if (p) p.hidden = true; });
    const filters = document.querySelectorAll('[data-rentals-filter]');
    filters.forEach(chip => {
      chip.addEventListener('click', () => {
        _setRentalsFilter(chip.getAttribute('data-rentals-filter') || 'active');
        renderRentals();
      });
    });
    // Click-first: strip cards switch the list tab (same data-rentals-filter
    // attribute as the chips — one handler set covers both).
    // (already covered by the querySelectorAll above — strip cards carry the
    // same attribute; nothing extra needed.)
    // CFO: "hide bad rigs" re-renders the list live when toggled.
    const hideBad = document.getElementById('rentals-hide-bad');
    if (hideBad) hideBad.addEventListener('change', renderRentals);
    // CFO: portfolio series bucket toggle (week/month) — re-fetches the
    // server-side aggregation from the local rental_history.
    document.querySelectorAll('[data-series-bucket]').forEach(b =>
      b.addEventListener('click', () =>
        setRentalsSeriesBucket(b.getAttribute('data-series-bucket') || 'week')));
    const list = document.getElementById('rentals-list');
    if (list) list.addEventListener('click', (e) => {
      const item = e.target.closest ? e.target.closest('.rentals-item') : null;
      if (!item) return;
      const id = item.getAttribute('data-rental-id');
      const provider = _rentalsFilter === 'contracts' ? 'braiins' : 'mrr';
      if (id) openRentalDetail(id, provider);
    });
    // Click-first: recommendation cards + heatmap cells → rig track record.
    const reco = document.getElementById('rentals-reco-cards');
    if (reco) reco.addEventListener('click', (e) => {
      const card = e.target.closest ? e.target.closest('.rentals-reco__card') : null;
      if (!card) return;
      openRigTrackRecord(card.getAttribute('data-rig-id'), card.getAttribute('data-rig-name'));
    });
    // Pilot's AVOID cards: the BLACKLISTAR button accepts the suggestion in
    // one click (POST blacklist → re-render: the card disappears and the
    // accepted ledger gains the entry). Card body still opens the track
    // record. Delegated — the cards are dynamic innerHTML.
    const avoidCards = document.getElementById('rentals-avoid-cards');
    if (avoidCards) avoidCards.addEventListener('click', async (e) => {
      const bl = e.target.closest ? e.target.closest('.rentals-reco__blacklist') : null;
      if (bl) {
        e.stopPropagation();
        const rid = bl.getAttribute('data-rig-id');
        if (!rid) return;
        bl.disabled = true;
        bl.textContent = '…';
        try {
          const r = await authFetch('/api/rentals/rig/blacklist', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ rig_id: rid }),
          });
          if (r.ok) loadRentals();  // avoid shrinks, accepted grows
          else { bl.disabled = false; bl.textContent = '⛔ BLACKLISTAR'; }
        } catch (err) {
          // Fail-closed, but never leave the button stuck on '…'.
          bl.disabled = false;
          bl.textContent = '⛔ BLACKLISTAR';
        }
        return;
      }
      const card = e.target.closest ? e.target.closest('.rentals-reco__card--avoid') : null;
      if (card) openRigTrackRecord(card.getAttribute('data-rig-id'), card.getAttribute('data-rig-name'));
    });
    // Accepted-recommendation cards (dynamic innerHTML — delegated listener)
    // → rig track record modal, same flow as the reco cards.
    const accepted = document.getElementById('rentals-accepted-list');
    if (accepted) accepted.addEventListener('click', (e) => {
      const card = e.target.closest ? e.target.closest('.rentals-accepted__card') : null;
      if (!card) return;
      openRigTrackRecord(card.getAttribute('data-rig-id'), card.getAttribute('data-rig-name'));
    });
    // Auto-exclusion history cards (dynamic innerHTML — delegated listener)
    // → rig track record modal, same flow as the accepted cards.
    const autoex = document.getElementById('rentals-autoex-list');
    if (autoex) autoex.addEventListener('click', (e) => {
      const card = e.target.closest ? e.target.closest('.rentals-autoex__card') : null;
      if (!card) return;
      openRigTrackRecord(card.getAttribute('data-rig-id'), card.getAttribute('data-rig-name'));
    });
    const heatmap = document.getElementById('rentals-heatmap-grid');
    if (heatmap) heatmap.addEventListener('click', (e) => {
      const cell = e.target.closest ? e.target.closest('.rentals-heatmap__cell') : null;
      if (!cell) return;
      openRigTrackRecord('', cell.getAttribute('data-rig-name'));
    });
    // Worst-rig leaderboard rows (dynamic innerHTML — delegated listener)
    // → rig track record modal, same as the reco cards.
    const worst = document.getElementById('rentals-worst-list');
    if (worst) worst.addEventListener('click', (e) => {
      const row = e.target.closest ? e.target.closest('.rentals-worst__row') : null;
      if (!row) return;
      openRigTrackRecord(row.getAttribute('data-rig-id'), row.getAttribute('data-rig-name'));
    });
    // Rank cells are rendered AFTER _initRentalsPanel (dynamic innerHTML) so
    // they need a delegated listener — the static [data-rentals-filter] bind
    // above only covers chips + strip cards that exist at boot.
    const rankGrid = document.getElementById('rentals-rank-grid');
    if (rankGrid) rankGrid.addEventListener('click', (e) => {
      const cell = e.target.closest ? e.target.closest('.rentals-rank__cell') : null;
      if (!cell) return;
      const tab = cell.getAttribute('data-rentals-filter');
      if (tab) {
        _setRentalsFilter(tab);
        renderRentals();
      }
    });
    // Expiring rows + drill-down rows → rental detail (same provider logic).
    const expiring = document.getElementById('rentals-expiring-list');
    if (expiring) expiring.addEventListener('click', (e) => {
      const row = e.target.closest ? e.target.closest('.rentals-expiring__row') : null;
      if (!row) return;
      const id = row.getAttribute('data-rental-id');
      if (id) openRentalDetail(id, 'mrr');
    });
    const drill = document.getElementById('rentals-drill-body');
    if (drill) drill.addEventListener('click', (e) => {
      const row = e.target.closest ? e.target.closest('.rentals-drill__row') : null;
      if (!row) return;
      const id = row.getAttribute('data-rental-id');
      const provider = row.getAttribute('data-provider') || 'mrr';
      if (id) openRentalDetail(id, provider);
    });
    // Backtest modal.
    const backtestBtn = document.getElementById('rentals-backtest');
    if (backtestBtn) backtestBtn.addEventListener('click', openBacktestModal);
    const backtestRun = document.getElementById('backtest-run');
    if (backtestRun) backtestRun.addEventListener('click', runBacktest);
    // Deep-link: #rentals?detail=<id>&provider=mrr opens the panel + detail.
    const applyRentalsHash = () => {
      const m = /^#rentals(?:\?(.*))?$/.exec(window.location.hash || '');
      if (!m) return;
      activateModule('rentals');
      const q = new URLSearchParams(m[1] || '');
      const did = q.get('detail');
      const prov = q.get('provider') || 'mrr';
      if (did) setTimeout(() => openRentalDetail(did, prov), 600);
    };
    applyRentalsHash();
    window.addEventListener('hashchange', applyRentalsHash);
    // ⚡ COMPRAR HASHRATE — Braiins spot (real money, typed confirmation).
    const buyBtn = document.getElementById('rentals-buy');
    if (buyBtn) buyBtn.addEventListener('click', openBraiinsBuyModal);
  }

  // ── Braiins spot buy modal (real money — explicit confirm only) ───────
  let _braiinsBuyQuote = null;   // last /quote payload
  let _braiinsBuyOrderId = '';   // idempotency key, regenerated per modal session
  let _braiinsBuyBalance = null; // {available_sat,...} or null (unknown/failed)

  function _braiinsBuyModal() { return document.getElementById('braiins-buy-modal'); }

  function _braiinsBuySet(id, v) { const e = document.getElementById(id); if (e) e.textContent = v; }

  function openBraiinsBuyModal(prefill) {
    const modal = _braiinsBuyModal();
    if (!modal) return;
    // Reset the form + status on every open (never carry a stale bid).
    ['braiins-buy-th', 'braiins-buy-amount', 'braiins-buy-stratum',
     'braiins-buy-identity', 'braiins-buy-memo', 'braiins-buy-type'].forEach(id => {
      const e = document.getElementById(id); if (e) e.value = '';
    });
    const ack = document.getElementById('braiins-buy-ack'); if (ack) ack.checked = false;
    _braiinsBuySet('braiins-buy-calc', '—');
    _braiinsBuySet('braiins-buy-status', '');
    // Reset balance display + guard (the quote below re-fills them). Classes
    // are reset too — a previous is-exceeded/is-unknown must not flash red
    // through the 'carregando…' state.
    _braiinsBuyBalance = null;
    _braiinsBuySet('braiins-buy-balance', 'saldo: carregando…');
    _syncBraiinsBalanceClass('loading');
    const submit = document.getElementById('braiins-buy-submit');
    if (submit) submit.disabled = true;
    openModalAnimated(modal);
    _braiinsBuyOrderId = 'c65-' + Date.now().toString(36) + '-' + Math.random().toString(36).slice(2, 8);
    // 'comprar agora' prefill: derive TH + budget from the arbitrage signal's
    // CURRENT market price (e.g. 1000 TH/s ≈ 1 PH/s × ~24h at that price), so
    // the user only adds their stratum + typed confirmation. The live quote
    // below still wins for the actual bid price.
    const _prefillPrice = (prefill && prefill.price_sats_per_thh > 0)
      ? prefill.price_sats_per_thh : 0;
    if (_prefillPrice > 0) {
      // TH prefill: explicit override > tenant's typical order size
      // (suggested_th from the arbitrage signal) > 1000 TH default.
      const th = prefill.th || prefill.suggested_th || 1000;
      const amount = Math.max(1000, Math.round(_prefillPrice * th * 24 / 1000) * 1000);
      const thEl = document.getElementById('braiins-buy-th'); if (thEl) thEl.value = th;
      const amtEl = document.getElementById('braiins-buy-amount'); if (amtEl) amtEl.value = amount;
    }
    _braiinsBuyCalc();
    // Load the live ask + tenant balance to prefill the quote line. When the
    // prefill came from an arbitrage signal, show THAT price explicitly so the
    // 'preço atual pré-preenchido' is visible even if the live quote fails
    // (the live ask overwrites this line on success).
    _braiinsBuySet('braiins-buy-quote', _prefillPrice > 0
      ? '⚡ pré-preenchido do sinal: ' + _prefillPrice + ' sats/TH·h · carregando cotação live…'
      : 'carregando cotação…');
    fetch('/api/rentals/braiins/quote')
      .then(r => r.ok ? r.json() : null)
      .then(q => {
        _braiinsBuyQuote = q;
        if (!q || !q.available) {
          _braiinsBuySet('braiins-buy-quote', '⚠ ' + ((q && q.error) || 'cotação indisponível'));
          // Balance stays unknown — surface the is-unknown state (this branch
          // previously returned before _renderBraiinsBuyBalance, leaving the
          // line stuck on 'carregando…' forever).
          _renderBraiinsBuyBalance();
          return;
        }
        const bal = q.balance || {};
        const balTxt = bal.available ? (bal.available_sat != null ? Number(bal.available_sat).toLocaleString('en-US') + ' sats disponíveis' : 'saldo: verifique na conta') : ((bal.error || '') ? 'saldo indisponível (' + bal.error + ')' : '—');
        _braiinsBuySet('braiins-buy-quote',
          'ASK MENOR: ' + q.price_sats_per_thh + ' sats/TH·h · ' + q.price_sat_per_ph_day + ' sats/PH·dia · ' + balTxt);
        // Balance guard: keep the raw number so _braiinsBuyCalc can BLOCK the
        // submit when the budget exceeds the available sats.
        _braiinsBuyBalance = bal.available && bal.available_sat != null
          ? bal : null;
        _renderBraiinsBuyBalance();
        _braiinsBuyCalc();
      })
      .catch(() => _braiinsBuySet('braiins-buy-quote', '⚠ falha ao carregar cotação'));
  }

  function _syncBraiinsBalanceClass(state) {
    // Single source of truth for the balance-line state classes — called
    // from every path (open / quote ok / quote fail / calc) so the visual
    // state can never drift from the actual guard.
    //   state: 'loading' | 'known' | 'exceeded' | 'unknown'
    const el = document.getElementById('braiins-buy-balance');
    if (!el) return;
    el.classList.remove('is-known', 'is-exceeded', 'is-unknown');
    if (state === 'known') el.classList.add('is-known');
    else if (state === 'exceeded') el.classList.add('is-exceeded');
    else if (state === 'unknown') el.classList.add('is-unknown');
  }

  function _renderBraiinsBuyBalance() {
    const bal = _braiinsBuyBalance;
    if (bal) {
      const sat = Number(bal.available_sat) || 0;
      _braiinsBuySet('braiins-buy-balance', 'SALDO DISPONÍVEL: ' + sat.toLocaleString('en-US') + ' sats');
      _syncBraiinsBalanceClass('known');
      _braiinsBuyCalc();  // re-evaluate the guard when balance arrives
    } else {
      _braiinsBuySet('braiins-buy-balance', 'saldo: indisponível — verifique sua chave Braiins no Settings');
      _syncBraiinsBalanceClass('unknown');
    }
  }

  function _braiinsBuyCalc() {
    const th = parseFloat(document.getElementById('braiins-buy-th')?.value) || 0;
    const amount = parseInt(document.getElementById('braiins-buy-amount')?.value, 10) || 0;
    const q = _braiinsBuyQuote;
    let out = '—';
    if (q && q.available && th > 0) {
      const ph = th / 1000;
      // At the cheapest ask, how long does the budget last (TH·h / TH = h)?
      const thh = amount > 0 && q.price_sats_per_thh > 0 ? amount / q.price_sats_per_thh : 0;
      const hours = thh > 0 && th > 0 ? thh / th : 0;
      out = th.toLocaleString('en-US') + ' TH/s = ' + ph.toLocaleString('en-US', { maximumFractionDigits: 3 }) + ' PH/s';
      if (amount > 0 && hours > 0) {
        out += ' · budget cobre ~' + (hours >= 1 ? Math.round(hours) + 'h' : Math.round(hours * 60) + 'min') + ' de hashrate';
      }
    }
    // Balance guard: budget > available sats → warn + keep submit BLOCKED.
    const bal = _braiinsBuyBalance;
    const balSat = bal ? (Number(bal.available_sat) || 0) : null;
    const exceeded = balSat != null && amount > balSat;
    if (exceeded) {
      out += ' · ⚠ budget EXCEDE o saldo em ' + (amount - balSat).toLocaleString('en-US') + ' sats';
      // Sync BOTH ways: when the user lowers the budget back under the
      // balance the class must clear, not linger red forever.
      _syncBraiinsBalanceClass('exceeded');
    } else if (balSat != null) {
      _syncBraiinsBalanceClass('known');
    }
    _braiinsBuySet('braiins-buy-calc', out);
    // Enable only when: live quote present, hashrate > 0, budget + stratum
    // present, budget ≤ available balance, ack checked, typed COMPRAR. A
    // missing quote (network down / no ask) BLOCKS the order — never bid
    // blind with real money.
    const quoteOk = !!(q && q.available);
    const typed = (document.getElementById('braiins-buy-type')?.value || '').trim().toUpperCase() === 'COMPRAR';
    const ack = document.getElementById('braiins-buy-ack')?.checked || false;
    const stratum = (document.getElementById('braiins-buy-stratum')?.value || '').trim();
    const submit = document.getElementById('braiins-buy-submit');
    if (submit) submit.disabled = !(quoteOk && th > 0 && amount >= 1000 && !exceeded && stratum && typed && ack);
  }

  async function submitBraiinsBid() {
    const submit = document.getElementById('braiins-buy-submit');
    setBtnLoading(submit, true);
    _braiinsBuySet('braiins-buy-status', 'enviando ordem…');
    try {
      const th = parseFloat(document.getElementById('braiins-buy-th')?.value) || 0;
      const amount = parseInt(document.getElementById('braiins-buy-amount')?.value, 10) || 0;
      const body = {
        speed_limit_th: th,
        amount_sat: amount,
        price_sat: (_braiinsBuyQuote && _braiinsBuyQuote.price_sat_per_ph_day) || 0,
        upstream_url: (document.getElementById('braiins-buy-stratum')?.value || '').trim(),
        upstream_identity: (document.getElementById('braiins-buy-identity')?.value || '').trim(),
        memo: (document.getElementById('braiins-buy-memo')?.value || '').trim(),
        cl_order_id: _braiinsBuyOrderId,
      };
      const r = await authFetch('/api/rentals/braiins/bid', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      const data = await r.json().catch(() => ({}));
      if (r.ok && data.success) {
        setBtnLoading(submit, false);
        _braiinsBuySet('braiins-buy-status', '✅ ordem enviada — id ' + (data.bid && data.bid.id ? data.bid.id : 'confirmada na Braiins'));
        // Conversion telemetry is recorded SERVER-SIDE on bid success
        // (single source of truth — no double counting).
      } else {
        _braiinsBuySet('braiins-buy-status', '⚠ ' + (data.error || 'falha ao enviar ordem'));
        setBtnLoading(submit, false);
      }
    } catch (e) {
      _braiinsBuySet('braiins-buy-status', '⚠ erro de rede ao enviar ordem');
      setBtnLoading(submit, false);
    }
  }

  function _initBraiinsBuyModal() {
    const modal = _braiinsBuyModal();
    if (!modal) return;
    modal.addEventListener('click', (e) => {
      if (e.target.matches('[data-close]') || e.target === modal) closeModalAnimated(modal);
    });
    ['braiins-buy-th', 'braiins-buy-amount', 'braiins-buy-stratum', 'braiins-buy-type']
      .forEach(id => {
        const el = document.getElementById(id);
        if (el) el.addEventListener('input', _braiinsBuyCalc);
      });
    const ack = document.getElementById('braiins-buy-ack');
    if (ack) ack.addEventListener('change', _braiinsBuyCalc);
    const submit = document.getElementById('braiins-buy-submit');
    if (submit) submit.addEventListener('click', submitBraiinsBid);
  }
  _initBraiinsBuyModal();

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

    document.getElementById('ai-ctx-status') && (document.getElementById('ai-ctx-status').textContent = snap.worker ? (snap.worker.hashrate ? 'ONLINE' : 'IDLE') : 'OFFLINE');
    document.getElementById('ai-ctx-hr') && (document.getElementById('ai-ctx-hr').textContent = fmt.hashrate(w.hashrate));
    document.getElementById('ai-ctx-best') && (document.getElementById('ai-ctx-best').textContent = fmt.diff(w.bestDifficulty));
    document.getElementById('ai-ctx-net') && (document.getElementById('ai-ctx-net').textContent = fmt.diff(net.difficulty));
    // Real-user audit: Net HR / Height / Price were never populated — the
    // CONTEXT sidebar showed "—" for three of nine rows forever. Same
    // sources the status bar uses (network.hashrate, network.height,
    // btc_price.usd).
    document.getElementById('ai-ctx-nethr') && (document.getElementById('ai-ctx-nethr').textContent = fmt.hashrate(net.hashrate));
    document.getElementById('ai-ctx-net-height') && (document.getElementById('ai-ctx-net-height').textContent = net.height ? '#' + net.height : '—');
    const btcUsdCtx = (snap.btc_price && snap.btc_price.usd) || (net.btc_usd) || null;
    document.getElementById('ai-ctx-price') && (document.getElementById('ai-ctx-price').textContent = btcUsdCtx ? '$' + Number(btcUsdCtx).toLocaleString() : '—');
    document.getElementById('ai-ctx-fleet') && (document.getElementById('ai-ctx-fleet').textContent = fleet.length + ' devices');
    document.getElementById('ai-ctx-pblock') && (document.getElementById('ai-ctx-pblock').textContent = prox.chance_per_share_pct ? (Number(prox.chance_per_share_pct) * 100).toFixed(6) + '%' : '—');

    // ── Auto-Pilot armed state (server truth from snapshot) → toggle UI ──
    const ap = snap.auto_pilot || {};
    _apSetUi(!!ap.armed);
    _initAutoPilotToggle();
    _initAutoPilotAdvisory();
    _initAutoPilotDryRun();
  }

  // ── Auto-Pilot arm/disarm toggle (automations module) ─────────────
  // Backend: POST /api/automation/arm {armed} (fail-closed per tenant) +
  // GET /api/automation/status (armed + action budget). Arming enables
  // autonomous rule actions, so it requires typed confirmation.
  let _apArmed = false;
  let _apToggleInit = false;

  function _apSetUi(armed) {
    _apArmed = !!armed;
    const btn = document.getElementById('ap-armed-btn');
    const label = document.getElementById('ap-armed-label');
    const dot = document.getElementById('ap-armed-dot');
    if (label) label.textContent = armed ? 'ARM' : 'OFF';
    if (btn) {
      btn.classList.toggle('is-armed', armed);
      btn.title = armed
        ? 'Auto-Pilot ARMADO — as regras executam ações sozinhas. Clique para desarmar.'
        : 'Auto-Pilot desarmado — as regras não executam. Clique para armar (requer confirmação por digitação).';
    }
    if (dot) {
      dot.style.background = armed ? 'var(--green)' : 'var(--orange)';
      dot.style.boxShadow = armed ? '0 0 8px rgba(0,200,83,0.8)' : '0 0 6px rgba(255,160,0,0.6)';
    }
  }

  async function _apRefreshStatus() {
    try {
      const r = await authFetch('/api/automation/status');
      if (!r.ok) return;
      const d = await r.json().catch(() => ({}));
      _apSetUi(!!d.armed);
      const badge = document.getElementById('ap-budget-badge');
      if (badge && typeof d.max_actions_per_window === 'number') {
        const used = d.actions_in_window || 0;
        const mins = Math.round((d.action_window_seconds || 3600) / 60);
        badge.textContent = used + '/' + d.max_actions_per_window + ' ações';
        badge.title = 'Auto-Pilot: ' + used + ' ação(ões) na janela de ' + mins + 'min (limite ' + d.max_actions_per_window + ')';
        badge.classList.toggle('badge--amber', used > 0);
        badge.classList.toggle('badge--mute', used === 0);
      }
    } catch (e) { /* status is advisory — never break the panel */ }
  }

  async function _apSetArmed(armed) {
    const btn = document.getElementById('ap-armed-btn');
    setBtnLoading(btn, true);
    try {
      const r = await authFetch('/api/automation/arm', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ armed: armed }),
      });
      const d = await r.json().catch(() => ({}));
      if (!r.ok || !d.success) {
        showToast('error', '⚠ Auto-Pilot: ' + (d.error || ('HTTP ' + r.status)));
        _apRefreshStatus();
        return false;
      }
      _apSetUi(!!d.armed);
      showToast('success', armed ? '🛡 Auto-Pilot ARMADO — regras executam sozinhas' : 'Auto-Pilot desarmado');
      _apRefreshStatus();
      return true;
    } catch (e) {
      showToast('error', '⚠ falha de rede ao alterar o Auto-Pilot');
      return false;
    } finally {
      setBtnLoading(btn, false);
    }
  }

  function _initAutoPilotToggle() {
    if (_apToggleInit) return;
    _apToggleInit = true;

    const btn = document.getElementById('ap-armed-btn');
    if (btn) {
      btn.addEventListener('click', () => {
        if (_apArmed) { _apSetArmed(false); return; }  // disarm is safe — direct
        const m = document.getElementById('ap-arm-modal');
        const input = document.getElementById('ap-arm-type');
        const confirm = document.getElementById('ap-arm-confirm');
        const status = document.getElementById('ap-arm-modal-status');
        if (m && input && confirm) {
          input.value = '';
          confirm.disabled = true;
          if (status) status.textContent = '';
          openModalAnimated(m);
          setTimeout(() => input.focus(), 50);
        }
      });
    }

    const m = document.getElementById('ap-arm-modal');
    if (m) {
      m.addEventListener('click', (e) => {
        if (e.target.matches('[data-close]') || e.target === m) closeModalAnimated(m);
      });
    }

    const input = document.getElementById('ap-arm-type');
    const confirm = document.getElementById('ap-arm-confirm');
    if (input && confirm) {
      input.addEventListener('input', () => {
        confirm.disabled = input.value.trim().toUpperCase() !== 'ARMAR';
      });
      input.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !confirm.disabled) confirm.click();
      });
      confirm.addEventListener('click', async () => {
        confirm.disabled = true;
        const ok = await _apSetArmed(true);
        const modal = document.getElementById('ap-arm-modal');
        if (modal) modal.classList.remove('modal--open');
        if (!ok) {
          input.value = '';
        }
      });
    }

    _apRefreshStatus();
  }

  // ── Issue #20 · Auto-Pilot ADVISORY — recomendações por device ──────
  // Backend: GET /api/auto-pilot/recommendations (recs + armed),
  // POST /api/auto-pilot/recommendations/<id>/respond {decision} (audited),
  // GET /api/auto-pilot/recommendations/audit (trail). Fase 2 do Big Bet:
  // o piloto consolida por dispositivo o que merece atenção e sugere a
  // ação em um clique (restart / pause / blacklist / comprar).
  let _apRecs = [];
  let _apAudit = [];
  let _apRecsInit = false;

  function _apRecCardHtml(rec) {
    if (!rec || typeof rec !== 'object') return '';
    const esc = escapeHtml;
    const sev = String(rec.severity || 'info').toLowerCase();
    const action = (rec.action && typeof rec.action === 'object') ? rec.action : {};
    const actionType = String(action.type || 'navigate');
    const actionLabel = String(action.label || (actionType === 'buy' ? 'COMPRAR AGORA' : 'APLICAR'));
    // Confirm text varies by action; buy opens the Braiins flow pre-filled.
    // deviceName is escaped ONCE here (raw value), and data-confirm escapes
    // it a second time for the HTML attribute — no double-escaping (&amp;amp;).
    const rawDevice = rec.device_name || rec.device_id || 'device';
    const confirmMsg = actionType === 'blacklist'
      ? 'Adicionar o rig à blacklist (nunca alugar de novo)?'
      : actionType === 'buy'
        ? 'Abrir o fluxo de compra Braiins com o preço atual?'
        : 'Executar \'' + actionLabel + '\' em ' + rawDevice + '?';
    return (
      '<div class="ap-rec ap-rec--' + esc(sev) + '" data-rec-id="' + esc(rec.id || '') + '">' +
      '<div class="ap-rec__head">' +
      '<span class="ap-rec__sev">' + esc(sev) + '</span>' +
      '<span class="ap-rec__dev">' + esc(rawDevice) + '</span>' +
      '<span class="ap-rec__type">' + esc(rec.issue_type || '') + '</span>' +
      '</div>' +
      '<div class="ap-rec__msg">' + esc(rec.message || '') + '</div>' +
      '<div class="ap-rec__actions">' +
      '<button type="button" class="btn btn--primary btn--mini ap-rec-apply" data-confirm="' + esc(confirmMsg) + '">' + esc(actionLabel) + '</button>' +
      '<button type="button" class="btn btn--mini ap-rec-ignore" title="Ignorar e registrar no audit trail">IGNORAR</button>' +
      '</div>' +
      '</div>'
    );
  }

  function _apAuditRowHtml(row) {
    const esc = escapeHtml;
    const decision = String(row.decision || '').toLowerCase();
    const when = row.ts ? fmt.age(row.ts) : '—';
    const body = (row.device_name || row.device_id || 'device') + ' · ' +
      esc(row.issue_type || '') + ' → ' + esc(row.action_type || '?');
    return (
      '<div class="ap-audit__row">' +
      '<span class="ap-audit__decision is-' + esc(decision === 'accept' ? 'accept' : 'ignore') + '">' +
      esc(decision === 'accept' ? 'ACEITO' : 'IGNORADO') + '</span>' +
      '<span class="ap-audit__body" title="' + esc(row.note || body) + '">' + body + '</span>' +
      '<span class="ap-audit__when">' + esc(when) + '</span>' +
      '</div>'
    );
  }

  function _apRenderRecs() {
    const list = document.getElementById('ap-recs-list');
    const badge = document.getElementById('ap-recs-badge');
    if (!list) return;
    if (badge) {
      badge.textContent = String(_apRecs.length);
      badge.classList.toggle('badge--purple', _apRecs.length > 0);
      badge.classList.toggle('badge--mute', _apRecs.length === 0);
      badge.title = _apRecs.length + ' recomendação(ões) ativa(s)';
    }
    if (!_apRecs.length) {
      list.innerHTML =
        '<div class="empty-state" style="grid-column:1/-1;border:none;padding:12px">' +
        '<div class="empty-state__icon">⌘</div>' +
        '<div class="empty-state__title">Sem recomendações no momento</div>' +
        '<div class="empty-state__desc">O Auto-Pilot (advisory) consolida por dispositivo o que merece atenção — OFFLINE, temperatura alta, hashrate abaixo do pico, rig com track record ruim ou janela de arbitragem — com a ação sugerida em um clique.</div>' +
        '</div>';
    } else {
      list.innerHTML = _apRecs.map(_apRecCardHtml).join('');
    }
  }

  function _apRenderAudit() {
    const wrap = document.getElementById('ap-audit-wrap');
    const list = document.getElementById('ap-audit-list');
    const count = document.getElementById('ap-audit-count');
    if (!wrap || !list) return;
    if (!_apAudit.length) {
      wrap.style.display = 'none';
      return;
    }
    wrap.style.display = '';
    if (count) count.textContent = String(_apAudit.length);
    list.innerHTML = _apAudit.slice(0, 12).map(_apAuditRowHtml).join('');
  }

  async function _apLoadRecs() {
    try {
      const r = await authFetch('/api/auto-pilot/recommendations');
      if (r.ok) {
        const d = await r.json().catch(() => ({}));
        _apRecs = Array.isArray(d.recommendations) ? d.recommendations : [];
        if (typeof d.armed === 'boolean') _apSetUi(d.armed);
      }
    } catch (e) { /* advisory — never break the module */ }
    try {
      const r2 = await authFetch('/api/auto-pilot/recommendations/audit?limit=50');
      if (r2.ok) {
        const d2 = await r2.json().catch(() => ({}));
        _apAudit = Array.isArray(d2.audit) ? d2.audit : [];
      }
    } catch (e) { /* best-effort */ }
    _apRenderRecs();
    _apRenderAudit();
  }

  async function _apRespond(recId, decision, confirmMsg) {
    if (decision === 'accept' && confirmMsg && !window.confirm(confirmMsg)) return;
    try {
      const r = await authFetch('/api/auto-pilot/recommendations/' + encodeURIComponent(recId) + '/respond', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ decision: decision }),
      });
      const d = await r.json().catch(() => ({}));
      if (!r.ok || !d.success) {
        showToast('error', '⚠ Auto-Pilot: ' + (d.error || ('HTTP ' + r.status)));
        return;
      }
      if (decision === 'accept' && d.action_result && d.action_result.ok === false) {
        showToast('error', '⚠ ' + (d.action_result.error || 'ação falhou'));
      } else if (decision === 'accept') {
        showToast('success', d.action_type === 'buy' ? '🛒 abrindo compra…' : '✓ ação executada: ' + (d.action_type || 'ok'));
      } else {
        showToast('success', 'recomendação ignorada (auditado)');
      }
      // Buy flow: open the Braiins spot modal pre-filled with the current
      // price (real-money step stays behind the typed confirmation).
      if (d.open_buy_flow) {
        const buyBtn = document.getElementById('rentals-buy');
        activateModule('rentals');
        setTimeout(() => { if (buyBtn) buyBtn.click(); }, 250);
      }
      _apLoadRecs();
    } catch (e) {
      showToast('error', '⚠ Auto-Pilot: ' + (e.message || 'falha de rede'));
    }
  }

  function _initAutoPilotAdvisory() {
    if (_apRecsInit) return;
    _apRecsInit = true;
    const panel = document.getElementById('ap-advisory-panel');
    const refresh = document.getElementById('ap-recs-refresh');
    if (refresh) refresh.addEventListener('click', _apLoadRecs);
    if (panel) {
      panel.addEventListener('click', (e) => {
        const apply = e.target.closest ? e.target.closest('.ap-rec-apply') : null;
        const ignore = e.target.closest ? e.target.closest('.ap-rec-ignore') : null;
        const card = e.target.closest ? e.target.closest('.ap-rec') : null;
        if (!card) return;
        const recId = card.getAttribute('data-rec-id');
        if (!recId) return;
        if (apply) {
          _apRespond(recId, 'accept', apply.getAttribute('data-confirm') || '');
        } else if (ignore) {
          _apRespond(recId, 'ignore');
        }
      });
    }
    _apLoadRecs();
  }

  // ── Issue #76 · Auto-Pilot DRY-RUN (execução simulada) ─────────────
  let _apDrInit = false;

  function _apDrNowCardHtml(a) {
    const esc = escapeHtml;
    const blocked = a.safety_verdict === 'blocked';
    const cancelled = a.conflict === 'cancelled_by_conflict';
    const rated = a.budget === 'rate_limited';
    const cls = cancelled ? 'ap-dr-card--cancel' : (blocked ? 'ap-dr-card--blocked' : (rated ? 'ap-dr-card--rate' : ''));
    const actual = a.actual_value != null ? String(a.actual_value) : '—';
    let chips = cancelled
      ? '<span class="ap-dr-chip ap-dr-chip--mute">cancelada · conflito</span>'
      : (blocked
        ? '<span class="ap-dr-chip ap-dr-chip--bad">safety: BLOQUEADO</span>'
        : '<span class="ap-dr-chip ap-dr-chip--ok">safety: APROVADO</span>');
    if (blocked && a.safety_reason) {
      chips += '<span class="ap-dr-chip ap-dr-chip--bad" title="' + esc(a.safety_reason) + '">motivo</span>';
    }
    if (rated) {
      chips += '<span class="ap-dr-chip ap-dr-chip--warn">budget: rate-limited</span>';
    } else if (!cancelled) {
      chips += '<span class="ap-dr-chip ap-dr-chip--mute">executaria</span>';
    }
    return (
      '<div class="ap-dr-card ' + cls + '">' +
      '<div class="ap-dr-card__head"><span class="ap-dr-card__rule">' + esc(a.rule_name || ('regra #' + String(a.rule_id))) + '</span>' +
      '<span class="ap-dr-card__dev">' + esc(a.device_name || a.device_id || '') + '</span></div>' +
      '<div class="ap-dr-card__cond">' + esc(String(a.condition_metric || '')) + ' ' + esc(String(a.condition_operator || '')) + ' ' + esc(String(a.condition_value != null ? a.condition_value : '')) + ' · atual: ' + esc(actual) + ' → ' + esc(String(a.action_command || '?')) + '</div>' +
      '<div class="ap-dr-card__outcome">' + esc(a.predicted_outcome || '') + '</div>' +
      '<div class="ap-dr-card__chips">' + chips + '</div>' +
      '</div>'
    );
  }

  function _apDrReplayRowHtml(r) {
    const esc = escapeHtml;
    const when = r.first_ts ? fmt.age(r.first_ts) : '';
    return (
      '<div class="ap-dr-replay__row">' +
      '<span class="ap-dr-replay__rule">' + esc(r.rule_name || ('regra #' + String(r.rule_id))) + ' · ' + esc(r.device_name || r.device_id || '') + '</span>' +
      '<span class="ap-dr-replay__action">' + esc(r.action_command || '') + '</span>' +
      '<span class="ap-dr-replay__fires" title="rate-limited: ' + esc(String(r.rate_limited || 0)) + '">' + esc(String(r.fires || 0)) + '×</span>' +
      '<span class="ap-dr-replay__when">' + esc(when) + '</span>' +
      '</div>'
    );
  }

  function _apDrErrHtml(msg) {
    return '<div class="ap-dr-banner" style="border-color:var(--accent-red,#ff4d4d);color:var(--accent-red,#ff4d4d)">' +
      '⚠ ' + escapeHtml(msg) + '</div>';
  }

  async function _apDrLoad() {
    try {
      const r = await authFetch('/api/automation/dry-run');
      if (r.ok) {
        const d = await r.json().catch(() => ({}));
        const list = document.getElementById('ap-dr-now-list');
        const count = document.getElementById('ap-dr-now-count');
        const actions = Array.isArray(d.actions) ? d.actions : [];
        if (count) count.textContent = actions.length ? String(actions.length) : '0';
        if (list) {
          if (!actions.length) {
            list.innerHTML =
              '<div class="empty-state" style="grid-column:1/-1;border:none;padding:12px">' +
              '<div class="empty-state__icon">◈</div>' +
              '<div class="empty-state__title">Nenhuma regra dispararia agora</div>' +
              '<div class="empty-state__desc">Com a telemetria atual e as regras ativas, o piloto não teria nenhuma ação a tomar.</div>' +
              '</div>';
          } else {
            list.innerHTML = actions.map(_apDrNowCardHtml).join('');
          }
        }
      } else {
        // Honest feedback: a failed simulation is NOT "nothing fires".
        // escapeHtml at the source (status is numeric — double-escape is
        // harmless) to satisfy the DOM regression guard's data-flow scan.
        const list = document.getElementById('ap-dr-now-list');
        if (list) list.innerHTML = _apDrErrHtml('simulação indisponível (' + escapeHtml(r.status) + ')');
      }
    } catch (e) { /* dry-run — never break the module */ }
    try {
      const r2 = await authFetch('/api/automation/dry-run/replay?hours=24&limit=288');
      if (r2.ok) {
        const d2 = await r2.json().catch(() => ({}));
        const list2 = document.getElementById('ap-dr-replay-list');
        const count2 = document.getElementById('ap-dr-replay-count');
        const rows = Array.isArray(d2.per_rule) ? d2.per_rule : [];
        if (count2) count2.textContent = d2.total_fires != null ? String(d2.total_fires) + ' disparos' : '—';
        if (list2) {
          if (!rows.length) {
            list2.innerHTML =
              '<div class="empty-state" style="grid-column:1/-1;border:none;padding:12px">' +
              '<div class="empty-state__icon">↻</div>' +
              '<div class="empty-state__title">Nenhuma regra teria disparado nas últimas 24h</div>' +
              '<div class="empty-state__desc">Simulação sobre o histórico de telemetria — cooldown, conflitos e budget aplicados.</div>' +
              '</div>';
          } else {
            list2.innerHTML = rows.map(_apDrReplayRowHtml).join('');
          }
        }
      }
    } catch (e) { /* best-effort */ }
  }

  function _initAutoPilotDryRun() {
    if (_apDrInit) return;
    _apDrInit = true;
    const refresh = document.getElementById('ap-dr-refresh');
    if (refresh) refresh.addEventListener('click', _apDrLoad);
    _apDrLoad();
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
    toggleWalletCTA();
    renderHUD(snap);
    renderStatusBar(snap);
    // P0-4 fix: an empty shortAddr('') collapses the topbar span to a
    // zero-width box (Playwright/flex reports it hidden on wallet-less
    // boots). Keep the '—' placeholder (same convention as #sb-wallet-addr)
    // so the element always has a real box.
    if (dom.topbarAddress) dom.topbarAddress.textContent = `${fmt.shortAddr(snap.btc_address || window.BTC_ADDRESS || '') || '—'}`;
    if (dom.statusText) {
      dom.statusText.textContent = snap.worker ? (snap.worker.hashrate ? 'ONLINE' : 'IDLE') : 'OFFLINE';
    }
    if (dom.statusPill) {
      dom.statusPill.classList.toggle('is-online', !!(snap.worker && snap.worker.hashrate));
      dom.statusPill.classList.toggle('is-idle', !!(snap.worker && !snap.worker.hashrate));
    }
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
    renderDecisionMatrix(snap.profitability);
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
    renderTimelineStats(snap);
    renderBlockHunt(snap);
    renderCommandCenter(snap);
    renderMarket(snap);
    renderAiOperator(snap);
    renderFleetCommandCenter(snap);
    renderWalletIdentity(snap);
    _lmSetConn(snap);
    renderCharts();
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
        // P0-1: network target difficulty reference line (solid purple).
        if (a.target) {
          ctx.strokeStyle = 'rgba(168,85,247,0.9)';
          ctx.lineWidth = 1.5;
          ctx.setLineDash([]);
          ctx.beginPath(); ctx.moveTo(x, area.top); ctx.lineTo(x, area.bottom); ctx.stroke();
          return;
        }
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
    // Human-readable Y ticks: hashrate/pool render fmt.hashrate (TH/s), best
    // diff/net render fmt.diff — raw 4.7e12 / 1.26e14 labels were unreadable.
    const isHrAxis = cfg && (cfg.chart === 'hashrate' || cfg.chart === 'pool');
    const isDiffAxis = cfg && (cfg.chart === 'bestdiff' || cfg.chart === 'net');
    const yTickCb = isHrAxis ? (v) => fmt.hashrate(v) : isDiffAxis ? (v) => fmt.diff(v) : undefined;
    // P0-5 audit: the share-difficulty histogram was rendered as a line chart
    // with pointRadius 0 + fill alpha 0.1 — with a handful of shares the
    // series was effectively invisible ("empty graph" despite 13+ shares).
    // Histograms belong on bars: one visible column per difficulty bucket.
    const isHistogram = cfg && cfg.chart === 'share_dist';
    const datasets = [
      isHistogram
        ? { label, data: [], borderColor: color, backgroundColor: color.replace(')', ',0.55)').replace('rgb','rgba'), borderWidth: 1, maxBarThickness: 34 }
        : { label, data: [], borderColor: color, backgroundColor: color.replace(')', ',0.1)').replace('rgb','rgba'), fill: true, tension: 0.4, pointRadius: 0 },
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
      type: isHistogram ? 'bar' : 'line',
      data: { labels: [], datasets },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: 'index', intersect: false },
        scales: {
          x: { ticks: { color: '#5E5952', maxTicksLimit: 8, font: { family: 'JetBrains Mono, monospace', size: 10 } }, grid: { color: 'rgba(94,89,82,0.14)' } },
          y: { ticks: { color: '#5E5952', font: { family: 'JetBrains Mono, monospace', size: 10 }, ...(yTickCb ? { callback: yTickCb } : {}) }, grid: { color: 'rgba(94,89,82,0.14)' } },
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
      _chartRange[id] = range || '1h'; // persist the toolbar choice across refreshes
      const r = await fetch(`/api/chart-data?chart=${metric}&range=${range}`);
      if (r.status === 402) { await handleLicenseRequired(r); _chartRange[id] = '1h'; const _tb = document.getElementById('share-dist-target-badge'); if (_tb) _tb.textContent = 'target —'; return; }
      if (!r.ok) return;
      const data = await r.json();
      const chart = charts[id];
      if (!chart) return;
      const cfg = CHART_METRICS[id] || {};
      const rawLabels = (data.labels || []);
      const values = (data.datasets?.[0]?.data || data.datasets?.[0]?.values || []);
      chart.data.labels = rawLabels.map(t => _fmtChartLabel(t, cfg, id));
      chart.data.datasets[0].data = values;
      _updateShareDistBadge(cfg, data, values);
      // Fase 2.1: SMA overlay + shares bar + event annotations
      if (chart.data.datasets[1] && cfg.chart !== 'share_dist') {
        chart.data.datasets[1].data = computeSMA(values, Math.max(3, Math.round(values.length / 10)));
      }
      if (chart.data.datasets[2] && Array.isArray(data.shares)) {
        chart.data.datasets[2].data = data.shares;
        chart.options.scales.y1.display = data.shares.some(s => s > 0);
      }
      chart._annotations = buildChartAnnotations(data.events || [], rawLabels);
      _applyShareDistTarget(cfg, data, chart);
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
          // Fase 2.2: use the BACKEND chart names (hashrate|pool|bestdiff|net).
          // Passing DB column names (worker_hashrate etc.) made every range
          // click fetch an unknown chart and render the panel blank.
          const metricMap = { 'chart-hashrate': 'hashrate', 'chart-pool': 'pool', 'chart-bestdiff': 'bestdiff', 'chart-net': 'net' };
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
  const SETTINGS_SELECTS = { cost_mode: ['none','rental','power'], active_currency: ['USD','BRL','EUR','GBP','JPY','KRW','CNY'], webhook_min_severity: ['INFO','WARN','CRIT','GOLD','SUCCESS'], rental_auto_blacklist_grade: ['A','B','C','D','F'] };
  const SETTINGS_CHECKBOX = { show_test_alerts: true };
  // Didactic hints shown under each settings field so users configure the
  // cost model correctly (Fase: LEASE mode — rental_usd_per_th_day is the
  // rate the LENDER charges, i.e. revenue, not a plain "cost").
  // Pure builder for the Settings → webhook preview (mirrored in JS tests).
  // Shows the operator the exact JSON payload that polling fires per alert.
  function webhookPreviewPayload(severity, message, worker, address) {
    return {
      event: 'cypher65_war_room_alert',
      severity: severity || 'WARN',
      category: 'alert',
      message: message || '⚠ [WARN] exemplo de alerta — configuração de webhook do CYPHER65',
      ts: Math.floor(Date.now() / 1000),
      worker: worker || 'primary',
      address: address || '',
    };
  }

  const SETTINGS_HINTS = {
    mrr_api_key: 'MiningRigRentals API key — crie em miningrigrentals.com → My Account → API Access (gerada uma vez, junto com o secret). Destrava histórico + performance no painel RENTALS.',
    mrr_api_secret: 'MiningRigRentals API secret — par da key acima (mostrado uma vez na criação). Guarde com segurança; nunca compartilhe.',
    braiins_api_key: 'Braiins Hashpower owner token (mostrado UMA vez no registro em hashpower.braiins.com; se perder, regenere em Settings → API Tokens) — destrava bids, contratos e saldo no painel RENTALS. Header de auth: `apikey`.',
    cost_mode: 'none = no cost · rental = pay per TH/s rented · power = rig kWh cost',
    rental_usd_per_th_day: '📤 LEASE: o que VOCÊ cobra ao alugar seu hashrate (receita) · 📦 RENTAL: o que você paga para alugar hashrate. Usado no modo LEASE do Profitability.',
    power_watts: 'Consumo do rig (W) — usado para o custo de energia no modo POWER e no LEASE.',
    power_kwh_usd: 'Tarifa de eletricidade ($/kWh) — usada junto com power_watts no modo POWER e no LEASE.',
    pool_fee_pct: 'Taxa da pool (%) aplicada à receita de mineração.',
    active_currency: 'Moeda exibida nos valores fiat (USD|BRL|EUR|GBP|JPY|KRW|CNY).',
    rental_pl_alert_pct: 'ALERTA CFO: dispara webhook + push quando um aluguel FECHA com P/L econômico abaixo deste % (ex: -50). Vazio ou 0 = desativado. Como o P/L vs yield costuma ser muito negativo, use um limiar realista (ex: -90) para só alertar os piores — ou deixe vazio para desligar. (Sem network hashrate, a checagem usa overpay vs preço de mercado.)',
    rental_pl_alert_window_hours: 'Janela: só alerta aluguéis que FECHARAM nas últimas N horas — evita enxurrada de alertas antigos ao habilitar a primeira vez.',
    rental_market_overpay_pct: 'ALERTA OVERPAY: dispara webhook + push quando o preço PAGO de um aluguel ficar este % ACIMA do mercado NA HORA DA COMPRA (preço acordado vs mercado histórico na data do start). Ex: 100 = alerta se pagou 2× o mercado. Vazio ou 0 = desativado. Dispara também para aluguéis ativos comprados nas últimas N horas.',
    rentals_min_delivery_pct: 'ANÁLISE DE RENDIMENTO (CSV): entrega mínima aceitável por aluguel (default 90). Abaixo dela o aluguel é marcado cancelled_performance no CSV e o reembolso devido é calculado (regra MRR: <80% = total; 80%..mín = proporcional).',
    rental_market_arb_pct: 'ALERTA ARBITRAGEM: dispara webhook + push quando o mercado AGORA estiver este % ABAIXO dos seus custos históricos (seus próprios aluguéis — abra o painel RENTALS uma vez para popular). Compara com 3 referências: CUSTO MÉDIO anunciado, CUSTO EFETIVO com entrega real (paid ÷ TH·h entregues — sobe quando a entrega é <100%) e o ÚLTIMO aluguel; a referência MAIS ALTA dispara o sinal. Ex: 30 = alerta quando o mercado estiver ≥30% mais barato que sua referência mais cara — janela de compra. Vazio ou 0 = desativado. 100% local, custo zero de provider.',
    rental_market_arb_cooldown_hours: 'Cooldown da arbitragem: repete o alerta de oportunidade no máximo 1× a cada N horas (padrão 24). Mercado barato persistente avisa diariamente, sem spam.',
    rental_reco_worse_alert: 'ALERTA RECOMENDAÇÃO ACEITA PIOROU: dispara webhook + push quando um rig que você blacklistou (recomendação aceita) termina com veredito PIOROU — ele voltou a entregar mal DEPOIS da exclusão, o blacklist não resolveu. 0/1, default 0 (off). Decisões revogadas nunca disparam.',
    rental_auto_exclude_alert: 'ALERTA AUTO-EXCLUSÃO: dispara webhook + push quando o sweep automático excluir um rig por sub-entrega (grade ≤ seu floor com amostras suficientes). A mensagem inclui a causa (entrega %, amostras, régua vigente). 0/1, default 0 (off).',
    rental_auto_blacklist_min_samples: 'AUTO-EXCLUSÃO: mínimo de amostras de entrega antes de excluir automaticamente um rig que entrega mal (default 2). Quanto mais alto, mais conservadora a decisão do piloto — precisa de mais histórico para excluir.',
    rental_auto_blacklist_grade: 'AUTO-EXCLUSÃO: o rig é auto-excluído quando a grade de entrega é PIOR OU IGUAL a esta letra (default F = só F). Ex: D exclui D e F; C exclui C, D e F. Grades vêm do trust score (median delivery + consistência).',
  };
  function renderSettingsForm() {
    const box = dom.settingsBody;
    if (!box) return;
    const settings = SETTINGS_CACHE.data;
    if (!settings || !Object.keys(settings).length) {
      box.innerHTML = '<div class="mkt-empty" style="padding:16px;text-align:center">settings unavailable</div>';
      return;
    }
    const order = ['cost_mode','rental_usd_per_th_day','power_watts','power_kwh_usd','btc_block_reward','btc_avg_tx_fee','pool_fee_pct','orphan_rate_pct','active_currency','active_fiat','stale_share_minutes','hashrate_drop_pct','webhook_url','webhook_min_severity','rental_pl_alert_pct','rental_pl_alert_window_hours','rental_market_overpay_pct','rental_market_arb_pct','rental_market_arb_cooldown_hours','rental_reco_worse_alert','rental_auto_exclude_alert','rentals_min_delivery_pct','rental_auto_blacklist_min_samples','rental_auto_blacklist_grade','show_test_alerts','mrr_api_key','mrr_api_secret','braiins_api_key'];
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
    // Credential sanity helpers for the RENTALS providers. Env-var override
    // warning: on a deployed instance (Render) BRAIINS_API_KEY set in the
    // environment silently wins over this field — tell the operator, or they
    // edit the field, nothing changes, and the panel keeps saying "rejected".
    if ((SETTINGS_CACHE.env || {}).braiins_api_key && settings['braiins_api_key']) {
      html += '<div style="margin-top:2px;border:1px solid var(--accent-orange, #ffa000);border-radius:4px;padding:6px 8px;font-size:10px;line-height:1.4;color:var(--text-muted)">⚠ O servidor tem <code>BRAIINS_API_KEY</code> definida como env var — ela <b>SOBRESCREVE</b> o valor abaixo. Remova a env var (Render → Environment) para usar a chave do Settings.</div>';
    }
    // "Test connection" for Braiins: probes the live API and reports the same
    // verdict the RENTALS panel derives (ok / rejected / missing).
    if (settings['braiins_api_key']) {
      html += '<div style="display:flex;align-items:center;gap:6px;margin-top:2px;flex-wrap:wrap">' +
        '<button type="button" class="btn btn--primary btn--mini" id="braiins-test">🔑 TESTAR CHAVE BRAIINS</button>' +
        '<span id="braiins-test-status" style="font-size:10px;color:var(--text-muted)"></span>' +
        '</div>';
    }
    // Webhook preview + test send (UX audit Quick Win): the operator sees
    // the exact JSON payload fired per alert, and can validate the channel
    // without waiting for a real event. Only rendered when a URL is actually
    // configured — otherwise the ENVIAR TESTE button would dead-end in a 400.
    const whConfigured = (settings['webhook_url'] && settings['webhook_url'].value) ? String(settings['webhook_url'].value).trim() : '';
    if (whConfigured) {
      html += '<div class="wh-preview" style="margin-top:6px;border:1px dashed var(--border);border-radius:4px;padding:8px">' +
        '<div style="font-size:10px;color:var(--text-tertiary);letter-spacing:0.06em">WEBHOOK PREVIEW — payload enviado a cada alerta (JSON)</div>' +
        '<pre id="wh-preview-payload" style="background:#0d0f12;padding:6px;border-radius:4px;font-size:9px;line-height:1.5;overflow:auto;margin:6px 0;max-height:140px;color:var(--green)"></pre>' +
        '<div style="display:flex;align-items:center;gap:6px;flex-wrap:wrap">' +
        '<button type="button" class="btn btn--primary btn--mini" id="wh-send-test">📡 ENVIAR TESTE</button>' +
        '<span id="wh-test-status" style="font-size:10px;color:var(--text-muted)"></span>' +
        '</div></div>';
    }
    // "Test alert" for the AUTO-EXCLUSION family (Issue #104): fires the SAME
    // message the sweep dispatches on a real exclusion, through the SAME
    // builders (send_webhook_for_alert + notify_tenant_alert), synchronously —
    // webhook + push verdict in one click. Always visible so the operator can
    // validate the tenant config BEFORE enabling rental_auto_exclude_alert.
    if (settings['rental_auto_exclude_alert']) {
      html += '<div style="margin-top:6px;border:1px dashed var(--border);border-radius:4px;padding:8px">' +
        '<div style="font-size:10px;color:var(--text-tertiary);letter-spacing:0.06em">ALERTA AUTO-EXCLUSÃO — teste do canal (webhook + push)</div>' +
        '<div style="font-size:10px;color:var(--text-muted);line-height:1.4;margin:4px 0 6px">Envia uma mensagem de exemplo do tipo que o piloto dispara quando o sweep exclui um rig por sub-entrega. Nenhuma exclusão real é feita.</div>' +
        '<div style="display:flex;align-items:center;gap:6px;flex-wrap:wrap">' +
        '<button type="button" class="btn btn--primary btn--mini" id="ae-send-test">🧪 TESTAR ALERTA</button>' +
        '<span id="ae-test-status" style="font-size:10px;color:var(--text-muted)"></span>' +
        '</div></div>';
    }
    html += '</div>';
    box.innerHTML = html;
    // Live-update the preview as the operator edits webhook fields, and wire
    // the "send test" button to POST a real sample payload to the channel.
    const whInput = box.querySelector('input[name="webhook_url"]');
    const whSev = box.querySelector('select[name="webhook_min_severity"]');
    const whPreview = document.getElementById('wh-preview-payload');
    function updateWhPreview() {
      if (!whPreview) return;
      const sev = whSev ? whSev.value : (settings['webhook_min_severity'] && settings['webhook_min_severity'].value) || 'WARN';
      whPreview.textContent = JSON.stringify(webhookPreviewPayload(sev), null, 2);
    }
    if (whInput && whPreview) {
      whInput.addEventListener('input', updateWhPreview);
      if (whSev) whSev.addEventListener('change', updateWhPreview);
      updateWhPreview();
    }
    const whTestBtn = document.getElementById('wh-send-test');
    if (whTestBtn) {
      whTestBtn.addEventListener('click', async function() {
        const st = document.getElementById('wh-test-status');
        if (st) { st.textContent = 'enviando…'; st.style.color = 'var(--text-muted)'; }
        try {
          const r = await authFetch('/api/settings/test-webhook', { method: 'POST' });
          const d = await r.json();
          if (st) {
            if (r.ok && d.success) { st.textContent = '✓ enviado (HTTP ' + d.status_code + ')'; st.style.color = 'var(--green)'; }
            else { st.textContent = '✗ ' + (d.error || ('HTTP ' + r.status)); st.style.color = 'var(--accent-red)'; }
          }
        } catch (e) {
          if (st) { st.textContent = '✗ network error: ' + e.message; st.style.color = 'var(--accent-red)'; }
        }
      });
    }
    const braiinsTestBtn = document.getElementById('braiins-test');
    if (braiinsTestBtn) {
      braiinsTestBtn.addEventListener('click', async function() {
        const st = document.getElementById('braiins-test-status');
        if (st) { st.textContent = 'testando… (pode levar ~10s)'; st.style.color = 'var(--text-muted)'; }
        try {
          // The probe can hit up to 4 Braiins endpoints — never let the button
          // hang indefinitely (AbortController 20s hard cap).
          const ctrl = new AbortController();
          const _timer = setTimeout(() => ctrl.abort(), 20000);
          const r = await authFetch('/api/settings/test-braiins', { method: 'POST', signal: ctrl.signal });
          clearTimeout(_timer);
          const d = await r.json();
          if (!st) return;
          if (r.ok && d.success) {
            st.textContent = '✓ chave aceita — ' + d.contracts + ' contrato(s)/bid(s) encontrados' + (d.env_override ? ' (via env var)' : '');
            st.style.color = 'var(--green)';
          } else if (!d.configured) {
            st.textContent = '✗ nenhuma chave configurada — cole o owner token acima' + (d.env_override ? ' (env var presente, mas inválida)' : '');
            st.style.color = 'var(--accent-red)';
          } else {
            st.textContent = '✗ ' + (d.error || 'falhou') + (d.env_override ? ' — a env var BRAIINS_API_KEY SOBRESCREVE este campo' : '');
            st.style.color = 'var(--accent-red)';
          }
        } catch (e) {
          if (st) { st.textContent = '✗ network error: ' + e.message; st.style.color = 'var(--accent-red)'; }
        }
      });
    }
    const aeTestBtn = document.getElementById('ae-send-test');
    if (aeTestBtn) {
      aeTestBtn.addEventListener('click', async function() {
        const st = document.getElementById('ae-test-status');
        if (st) { st.textContent = 'enviando…'; st.style.color = 'var(--text-muted)'; }
        try {
          const r = await authFetch('/api/settings/test-auto-exclude-alert', { method: 'POST' });
          const d = await r.json();
          if (!st) return;
          if (!r.ok) {
            st.textContent = '✗ ' + (d.error || ('HTTP ' + r.status));
            st.style.color = 'var(--accent-red)';
            return;
          }
          if (d.success) {
            const bits = [];
            if (d.webhook_ok) bits.push('webhook ✓');
            if (d.push_targets > 0) bits.push('push → ' + d.push_targets + ' dispositivo(s)');
            // Green success must NOT mask a dead webhook — that's the config
            // failure this button exists to catch (e.g. broken URL + push ok).
            const whWarn = (d.webhook_configured && !d.webhook_ok) ? ('⚠ webhook: ' + (d.webhook_reason || 'falhou')) : '';
            st.textContent = '✓ ' + bits.join(' · ') + (whWarn ? ' · ' + whWarn : '');
            st.style.color = whWarn ? 'var(--accent-orange)' : 'var(--green)';
          } else {
            const why = d.webhook_configured
              ? 'webhook: ' + (d.webhook_reason || 'falhou') + (d.push_targets === 0 ? ' · push sem dispositivos' : '')
              : 'nenhum canal entregou';
            st.textContent = '✗ ' + why + (d.guidance ? ' — ' + d.guidance : '');
            st.style.color = 'var(--accent-red)';
          }
        } catch (e) {
          if (st) { st.textContent = '✗ network error: ' + e.message; st.style.color = 'var(--accent-red)'; }
        }
      });
    }
  }
  async function loadSettings() {
    try {
      const r = await authFetch('/api/settings');
      const _j = await r.json();
      SETTINGS_CACHE.data = (_j.settings || []).reduce((acc, s) => { acc[s.key] = s; return acc; }, {});
      // env_overrides: which credentials are set as env vars on the SERVER —
      // they silently beat the field below (Render deploy gotcha).
      SETTINGS_CACHE.env = _j.env_overrides || {};
      renderSettingsForm();
    } catch (e) {}
  }
  function openSettingsModal() {
    openModalAnimated(dom.settingsModal);
    if (dom.settingsBody && !dom.settingsBody.innerHTML.trim()) renderSettingsForm();
  }
  function closeSettingsModal() { closeModalAnimated(dom.settingsModal); }
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
          return '<span class="support-method support-bar__method" title="' + escapeHtml(m.label) + '">' +
            '<span class="support-method-tag" style="color:' + escapeHtml(m.color || '#00ff41') + '">' + escapeHtml(m.icon || '₿') + ' ' + escapeHtml(m.label) + '</span>' +
            '<span class="support-method-addr" title="' + escapeHtml(m.label) + ': ' + escapeHtml(m.address) + '" data-copy="' + escapeHtml(m.address) + '">' + escapeHtml(m.address) + '</span>' +
            '<button class="support-method-copy" data-copy-btn aria-label="Copy ' + escapeHtml(m.label) + ' address">⧉</button>' +
            '</span>';
        }).join('');
      }

      // Full cards for the modal grid
      var grid = document.getElementById('support-modal-grid');
      if (grid) {
        grid.innerHTML = methods.map(function(m) {
          return '<div class="support-modal__card">' +
            '<div class="support-modal__card-icon" style="color:' + escapeHtml(m.color || '#00ff41') + '">' + escapeHtml(m.icon || '₿') + '</div>' +
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
    authFetch('/api/donations').then(function(r) { return r.json(); }).then(function(d) {
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
        var amt = row.amount_sat != null ? escapeHtml(row.amount_sat >= 1e8 ? (row.amount_sat / 1e8).toFixed(8).replace(/\.?0+$/, '') + ' BTC' : row.amount_sat.toLocaleString('en-US') + ' sats') : '—';
        var t = new Date((row.ts || 0) * 1000);
        var ts = t.toLocaleString('pt-BR', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' });
        var proof = row.txid ? escapeHtml(row.txid.slice(0, 10)) + '…' : (row.preimage ? 'preimage ' + escapeHtml(row.preimage.slice(0, 10)) + '…' : '');
        // verified = onchain (mempool watcher) or manual (operator-confirmed);
        // webln = client-reported, not verified on-chain
        var badge = row.source !== 'webln'
          ? '<span class="donation-row__badge is-verified" title="Confirmado on-chain (mempool)">✓</span>'
          : '<span class="donation-row__badge" title="Relatado pelo doador via WebLN — não verificado on-chain">~</span>';
        return '<div class="donation-row">' +
          '<span class="donation-row__icon">' + methodIcon + '</span>' +
          '<span class="donation-row__amt">' + amt + '</span>' +
          '<span class="donation-row__proof mono">' + (proof ? proof : escapeHtml(row.note || '')) + '</span>' +
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
        if (panel) openModalAnimated(panel);
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
          authFetch('/api/donations', {
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
    openModalAnimated(dom.walletModal);
    // Fill current address info (NOT CONNECTED state when no wallet yet)
    var walletConnected = !!window.BTC_ADDRESS;
    if (dom.walletCurrentAddr) {
      dom.walletCurrentAddr.textContent = walletConnected ? fmt.chunkAddr(window.BTC_ADDRESS) : 'NOT CONNECTED';
      dom.walletCurrentAddr.classList.toggle('wallet-current__addr--empty', !walletConnected);
    }
    if (dom.walletCurrentWorker) dom.walletCurrentWorker.textContent = walletConnected ? (window.WORKER_NAME || '—') : '—';
    if (dom.walletCurrentStatus) {
      dom.walletCurrentStatus.style.display = 'inline-flex';
      dom.walletCurrentStatus.textContent = walletConnected ? '● CONNECTED' : '○ NO WALLET CONNECTED';
      dom.walletCurrentStatus.classList.toggle('wallet-current__status--ok', walletConnected);
      dom.walletCurrentStatus.classList.toggle('wallet-current__status--empty', !walletConnected);
    }
    if (dom.walletAddressInput) dom.walletAddressInput.value = '';
    if (dom.walletWorkerInput) dom.walletWorkerInput.value = '';
    if (dom.walletStatus) dom.walletStatus.textContent = '';
    // P0-4: render the identity card (QR + checksum + health) from the
    // latest snapshot — a wallet may already be connected on open.
    renderWalletIdentity(prevSnapshot);
    // Focus the address input
    setTimeout(() => dom.walletAddressInput?.focus(), 100);
    // ── Hitórico de wallets ──
    fetchWalletHistory();
  }
  function closeWalletModal() {
    closeModalAnimated(dom.walletModal);
    if (dom.walletStatus) dom.walletStatus.textContent = '';
  }
  // Onboarding CTA: show when NO wallet is connected, hide once one is
  function toggleWalletCTA() {
    var cta = document.getElementById('wallet-cta');
    if (!cta) return;
    cta.style.display = window.BTC_ADDRESS ? 'none' : 'flex';
  }
  // CTA button opens the same wallet modal as the topbar ⚡ CONNECT
  document.getElementById('wallet-cta-open')?.addEventListener('click', openWalletModal);
  // Show the onboarding CTA immediately at boot (no wallet yet) instead of
  // waiting for the first snapshot render (~15s)
  toggleWalletCTA();
  dom.walletModal?.addEventListener('click', (e) => { if (e.target.matches('[data-close]')) closeWalletModal(); });
  dom.openWallet?.addEventListener('click', openWalletModal);
  document.getElementById('webln-connect-btn')?.addEventListener('click', connectWebLN);

  // Save wallet
  
  // ── FASE 2: Fetch wallet history ──
  async function fetchWalletHistory() {
    try {
      var resp = await authFetch('/api/wallet/history');
      var data = await resp.json();
      if (data.success && data.history) {
        var list = document.getElementById('wallet-history-list');
        if (list) {
          list.innerHTML = '';
          data.history.forEach(function(entry) {
            var li = document.createElement('button');
            li.className = 'wallet-history__item';
            li.innerHTML = '<span class="mono">' + escapeHtml(entry.address.slice(0, 10)) + '...</span> <span class="mute">' + escapeHtml(entry.worker || '') + '</span>';
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
      const resp = await authFetch('/api/set-address', {
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
      toggleWalletCTA(); // instant feedback: hide the onboarding CTA now
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
        dom.topbarAddress.textContent = fmt.shortAddr(data.address) || '—';
      }
      // Close modal after a short delay. The refresh itself is handled by
      // the wallet-changed listener (dispatched above) — refreshUntilWalletReady
      // — so no second retry chain is started here.
      setTimeout(() => {
        closeWalletModal();
      }, 300);
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
      if (!el.name) return;
      // Secrets/URLs must be trimmed: an owner token pasted with a trailing
      // newline makes the `apikey` header invalid → 401 "key rejected".
      const _trim = ['braiins_api_key', 'mrr_api_key', 'mrr_api_secret', 'webhook_url'].includes(el.name);
      data[el.name] = el.type === 'checkbox' ? (el.checked ? '1' : '0') : (_trim ? el.value.trim() : el.value);
    });
    try {
      const r = await authFetch('/api/settings', {
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
      if (savedOk) {
        // Credentials changed → invalidate the lazy RENTALS cache and refetch
        // NOW (the tab may already be activated, so the activation hook alone
        // would never re-run and the panel would keep showing 🔑/⚠).
        _rentalsLoaded = false;
        _rentalsData = null;
        loadRentals();
        if (typeof fetchSnapshot === 'function') fetchSnapshot();
        setTimeout(() => closeSettingsModal(), 800);
      }
    } catch (e) {
      const status = document.getElementById('settings-status');
      if (status) { status.textContent = 'NETWORK ERROR'; status.className = 'badge badge--red'; }
    }
  });

  // ── Export ──
  function openExportModal() { openModalAnimated(dom.exportModal); }
  function closeExportModal() { closeModalAnimated(dom.exportModal); }
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
  // P0-6 audit: professional terminal — bounded ring buffer (never unbounded
  // DOM growth), user scroll lock (never yank the reader back down), pause /
  // filter / live stats. Pure helpers mirrored in tests/test_app_js_core.js.
  let _lmEventCount = 0; const _LM_EVENT_MAX = 200;
  let _lmPaused = false;
  let _lmFilter = 'all';
  let _lmUserScrolled = false;
  const _lmStats = { total: 0, shares: 0, err: 0 };
  // FLEET COMMAND CENTER state (fleet-fed panel).
  let _ccLastFleet = [];
  let _ccView = 'grid';
  const _ccHrSeries = [];   // fleet total-HR history (KPI sparkline)
  const _ccHrHist = {};     // per-device HR history (card sparklines)
  const _ccShareSeen = {};  // ticker share dedupe (by ts)
  // P0-6: event type → badge class (color-coded terminal). Mirrored in tests.
  function lmEventTypeClass(type) {
    const t = String(type || '').toUpperCase();
    if (t === 'SHARE') return 'tag-share';
    if (t === 'BEST') return 'tag-best';
    if (t === 'JOB') return 'tag-job';
    if (t === 'ERR' || t === 'ERROR') return 'tag-error';
    return 'tag-info';
  }
  // P0-6: does an event pass the current filter? Mirrored in tests.
  function lmFilterMatches(filter, type) {
    const f = String(filter || 'all').toLowerCase();
    if (!f || f === 'all') return true;
    const t = String(type || '').toUpperCase();
    if (f === 'err') return t === 'ERR' || t === 'ERROR';
    return t === f.toUpperCase();
  }
  // P0-6: is the user reading history (not pinned to the newest line)?
  // Mirrored in tests.
  function lmUserScrolled(scrollTop, scrollHeight, clientHeight) {
    return scrollHeight - scrollTop - clientHeight > 24;
  }
  function _lmEventLineHtml(type, msg, ts) {
    const cls = lmEventTypeClass(type);
    // The type label is escaped too (defense-in-depth — the classifier maps
    // known types, but an unexpected value must never become raw HTML).
    return `<div class="lm-event-log__line"><span class="ts">[${ts}]</span><span class="${cls}">${escapeHtml(String(type).toUpperCase())}</span> ${escapeHtml(msg)}</div>`;
  }
  function _lmRenderStats() {
    const set = (id, v) => { const el = document.getElementById(id); if (el) el.textContent = String(v); };
    set('lm-stat-total', _lmStats.total);
    set('lm-stat-shares', _lmStats.shares);
    set('lm-stat-err', _lmStats.err);
  }
  // P0-6: connection status dot — LIVE (green) when the last snapshot is
  // fresh, STALE (amber) when the poll recently failed/aged, DOWN (red)
  // when we're pre-first-poll. Called from the main render path. Uses the
  // server-computed network.stale flag (single source of truth) so client
  // clock skew never mislabels the state.
  function _lmSetConn(snap) {
    const dot = document.getElementById('lm-conn-dot');
    if (!dot) return;
    dot.classList.remove('is-stale', 'is-down');
    const ts = snap && snap.ts;
    if (!ts) {
      dot.classList.add('is-down');
      dot.title = 'waiting for first poll';
    } else if ((snap.network && snap.network.stale === true) ||
               (Math.floor(Date.now() / 1000) - Number(ts) > 150)) {
      dot.classList.add('is-stale');
      dot.title = 'stale — network data aged';
    } else {
      dot.title = 'live';
    }
  }
  function _lmApplyFilter() {
    const term = dom.lmEventLogTerminal;
    if (!term) return;
    const keep = term.querySelectorAll('.lm-event-log__line');
    keep.forEach(el => {
      const typeEl = el.querySelector('.tag-share, .tag-best, .tag-job, .tag-error, .tag-info');
      const type = typeEl ? (typeEl.textContent || '').trim() : '';
      el.style.display = lmFilterMatches(_lmFilter, type) ? '' : 'none';
    });
    _lmSyncScrollLock();
  }
  function _lmSyncScrollLock() {
    const term = dom.lmEventLogTerminal;
    const jump = document.getElementById('lm-event-log-jump');
    if (!term) return;
    _lmUserScrolled = lmUserScrolled(term.scrollTop, term.scrollHeight, term.clientHeight);
    if (jump) jump.hidden = !_lmUserScrolled;
  }
  function _lmJumpToBottom() {
    const term = dom.lmEventLogTerminal;
    if (!term) return;
    _lmUserScrolled = false;
    term.scrollTop = term.scrollHeight;
    const jump = document.getElementById('lm-event-log-jump');
    if (jump) jump.hidden = true;
  }
  function _lmAppendEvent(type, msg) {
    const term = dom.lmEventLogTerminal;
    if (!term) return;
    // Every appended line (events AND the pause-resume marker) counts toward
    // the ring buffer — otherwise the count drifts from the real DOM size.
    _lmEventCount++;
    const now = new Date();
    const pad = (n) => String(n).padStart(2, '0');
    const ms = String(now.getMilliseconds()).padStart(3, '0');
    const ts = `${pad(now.getHours())}:${pad(now.getMinutes())}:${pad(now.getSeconds())}.${ms}`;
    term.insertAdjacentHTML('beforeend', _lmEventLineHtml(type, msg, ts));
    while (_lmEventCount > _LM_EVENT_MAX) {
      const f = term.querySelector('.lm-event-log__line');
      if (!f) break;
      f.remove(); _lmEventCount--;
    }
    if (!_lmUserScrolled) term.scrollTop = term.scrollHeight;
    _lmRenderStats();
  }

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

  // Pure numeric guard (mirrored in tests): backend may send the literal
  // "NOT AVAILABLE" for missing fields, so a plain != null check would
  // crash .toFixed(). Returns null for absent / non-numeric values.
  function _numOrNull(v) {
    if (v == null || v === '') return null;
    const n = Number(v);
    return isFinite(n) ? n : null;
  }

  // ── FLEET COMMAND CENTER — pure aggregation (mirrored in tests) ─────
  // Honest nulls when there is no live data to compute a metric — never
  // invented numbers. OFFLINE devices never contribute share counters
  // (their cumulative firmware counters persist after death and would
  // freeze a historical EFFICIENCY).
  function _ccKpiAgg(fleet) {
    fleet = fleet || [];
    const live = fleet.filter(d => d && String(d.status || '').toUpperCase() === 'ONLINE');
    // TOTAL HR = soma de TODOS os devices (paridade com o fleet summary).
    // Shares/temp/power/eff = APENAS ONLINE — os contadores cumulativos do
    // firmware persistem depois que o miner morre e congelariam um
    // EFFICIENCY histórico se OFFLINE contribuísse.
    let totalHr = 0, acc = 0, rej = 0, stale = 0;
    let tempSum = 0, tempN = 0, powerSum = 0, powerN = 0, effSum = 0, effN = 0;
    fleet.forEach(d => {
      totalHr += Number((d && d._telemetry && d._telemetry.hashrate_hs) || 0);
    });
    live.forEach(d => {
      const t = (d && d._telemetry) || {};
      acc += Number(t.shares_accepted) || 0;
      rej += Number(t.shares_rejected) || 0;
      stale += Number(t.shares_stale) || 0;
      const temp = _numOrNull(t.temperature);
      if (temp != null) { tempSum += temp; tempN++; }
      const pw = _numOrNull(t.power_watts);
      if (pw != null) { powerSum += pw; powerN++; }
      const eff = _numOrNull(t.efficiency_jth);
      if (eff != null) { effSum += eff; effN++; }
    });
    const lats = live.map(d => Number(d && d.latency_ms)).filter(v => v > 0 && isFinite(v));
    const shareTotal = acc + rej;
    return {
      totalHr: totalHr,
      effPct: shareTotal > 0 ? (acc / shareTotal) * 100 : null,
      avgTemp: tempN ? tempSum / tempN : null,
      totalPowerW: powerSum || null,
      avgEff: effN ? effSum / effN : null,
      avgLatency: lats.length ? Math.round(lats.reduce((a, b) => a + b, 0) / lats.length) : null,
      acc: acc, rej: rej, stale: stale,
    };
  }

  // Segmented share-quality bar (accepted / stale / rejected) — HiveOS-style
  // stacked segments. Empty when no shares have ever been recorded.
  function _ccShareBar(acc, rej, stale) {
    const a = Number(acc) || 0, r = Number(rej) || 0, s = Number(stale) || 0;
    const total = a + r + s;
    if (!total) return '<div class="cc-sharebar cc-sharebar--empty" title="sem shares registradas">no shares</div>';
    const wa = (a / total) * 100, ws = (s / total) * 100, wr = (r / total) * 100;
    return '<div class="cc-sharebar" title="' + a + ' acc · ' + s + ' stale · ' + r + ' rej">' +
      '<span class="cc-sharebar__seg cc-sharebar__seg--acc" style="width:' + wa.toFixed(1) + '%"></span>' +
      '<span class="cc-sharebar__seg cc-sharebar__seg--stale" style="width:' + ws.toFixed(1) + '%"></span>' +
      '<span class="cc-sharebar__seg cc-sharebar__seg--rej" style="width:' + wr.toFixed(1) + '%"></span>' +
      '</div>';
  }

  // Inline SVG area sparkline (no canvas, no gradient ids — collision-free).
  // Returns '' when fewer than 2 positive samples exist. Mirrored in tests.
  function _ccSvgSparkline(values, color) {
    const v = (values || []).map(Number).filter(x => isFinite(x) && x > 0);
    if (v.length < 2) return '';
    const w = 96, h = 26, pad = 2;
    const max = Math.max.apply(null, v), min = Math.min.apply(null, v);
    const span = (max - min) || 1;
    const pts = v.map((x, i) => {
      const px = pad + (i / (v.length - 1)) * (w - 2 * pad);
      const py = h - pad - ((x - min) / span) * (h - 2 * pad);
      return px.toFixed(1) + ',' + py.toFixed(1);
    }).join(' ');
    const area = pad + ',' + (h - pad) + ' ' + pts + ' ' + (w - pad) + ',' + (h - pad);
    return '<svg class="cc-spark" viewBox="0 0 ' + w + ' ' + h + '" preserveAspectRatio="none">' +
      '<polygon points="' + area + '" fill="' + color + '" fill-opacity="0.16"/>' +
      '<polyline points="' + pts + '" fill="none" stroke="' + color + '" stroke-width="1.4" stroke-linejoin="round" stroke-linecap="round"/>' +
      '</svg>';
  }

  // Temperature → thermal band: ≤60 ok · 60–70 warn · 70–80 hot · >80 crit.
  function _ccTempBand(t) {
    const n = _numOrNull(t);
    if (n == null) return 'mute';
    if (n <= 60) return 'ok';
    if (n <= 70) return 'warn';
    if (n <= 80) return 'hot';
    return 'crit';
  }

  // ── NETWORK/POOL STRIP — real network/pool telemetry from the snapshot ──
  function _ccRenderNetwork(snap) {
    if (!snap) return;
    const net = snap.network || {};
    const pool = snap.pool || {};
    if (dom.lmNetworkDiff) dom.lmNetworkDiff.textContent = fmt.diff(net.difficulty);
    if (dom.lmNetworkHr) dom.lmNetworkHr.textContent = fmt.hashrate(net.hashrate);
    if (dom.lmNetworkHeight) dom.lmNetworkHeight.textContent = net.height ? '#' + net.height : '—';
    // Est. block time: prefer the probability engine's live estimate.
    if (dom.lmNetworkBlock) {
      const prox = snap.proximity || {};
      const lc = prox.live_calc || {};
      const secs = Number(lc.expected_time_seconds) || Number(prox.time_to_block || 0);
      dom.lmNetworkBlock.textContent = secs > 0 ? fmt.secsToHuman(secs) : '—';
    }
    if (dom.lmNetworkPoolWorkers) dom.lmNetworkPoolWorkers.textContent = pool.workers != null ? pool.workers : '—';
    // lastBlockTime from the pool API is SECONDS SINCE the last block.
    if (dom.lmNetworkLastBlock) {
      const since = Number(pool.lastBlockTime);
      if (isFinite(since) && since > 0) {
        dom.lmNetworkLastBlock.textContent = fmt.secsToHuman(since) + ' ago';
        dom.lmNetworkLastBlock.title = 'segundos desde o último bloco da pool';
      } else {
        dom.lmNetworkLastBlock.textContent = '—';
      }
    }
  }

  // Best-share highlight across the FLEET (best_diff per device).
  function _updateFleetBestShare(rows) {
    if (!dom.lmBestShare) return;
    let best = 0, bestW = '';
    rows.forEach(r => { const bd = parseBestDiff(r.bestDiff); if (bd > best) { best = bd; bestW = r.name; } });
    if (best > _lmBestShareEver && best > 0) {
      _lmBestShareEver = best; _lmBestShareWorker = bestW; _lmBestShareTime = new Date().toISOString().slice(11, 19) + ' UTC';
      if (dom.lmBestShareVal) dom.lmBestShareVal.textContent = fmt.diff(best);
      if (dom.lmBestShareWorker) dom.lmBestShareWorker.textContent = 'Worker: ' + bestW;
      if (dom.lmBestShareTime) dom.lmBestShareTime.textContent = _lmBestShareTime;
      dom.lmBestShare.style.display = 'block';
      dom.lmBestShare.classList.remove('lm-best-share--flash'); void dom.lmBestShare.offsetWidth; dom.lmBestShare.classList.add('lm-best-share--flash');
      _logMiningEvent('BEST', 'novo best share ' + fmt.diff(best) + ' · ' + bestW);
    } else if (_lmBestShareEver > 0) {
      if (dom.lmBestShareVal) dom.lmBestShareVal.textContent = fmt.diff(_lmBestShareEver);
      dom.lmBestShare.style.display = 'block';
    }
  }

  // ── snapshot-fed parts of the panel: network strip, earnings KPI e
  //    eventos de share do live-calc ticker (dedupe por ts) ──
  function renderFleetCommandCenter(snap) {
    if (!snap) return;
    _ccRenderNetwork(snap);
    if (dom.fccSummaryEarnings) {
      const p = snap.profitability || {};
      const usd = Number(p.p_fiat_day);
      if (isFinite(usd) && usd > 0) {
        dom.fccSummaryEarnings.textContent = '$' + usd.toFixed(2) + '/d';
      } else {
        const btc = Number(p.p_btc_day);
        dom.fccSummaryEarnings.textContent = (isFinite(btc) && btc > 0) ? btc.toPrecision(4) + ' BTC/d' : '—';
      }
    }
    // Share events from the live-calc ticker — dedupe keeps the terminal
    // from spamming on repeated polls.
    const ticker = (snap.proximity && snap.proximity.live_calc && snap.proximity.live_calc.ticker) || [];
    if (ticker.length && !_lmLoggedActive) {
      _lmLoggedActive = true;
      _logMiningEvent('JOB', 'live share stream conectado (' + ticker.length + ' share(s) no ticker)');
    }
    if (Object.keys(_ccShareSeen).length > 2000) {
      Object.keys(_ccShareSeen).forEach(k => delete _ccShareSeen[k]);
    }
    ticker.forEach(s => {
      const key = 'sh_' + s.ts;
      if (_ccShareSeen[key]) return;
      _ccShareSeen[key] = 1;
      _logMiningEvent('SHARE', (s.share_diff_str || '—') + (s.gap ? ' · gap ' + Number(s.gap).toFixed(1) + 's' : ''));
    });
  }
  function _logMiningEvent(type, msg) {
    if (!dom.lmEventLogTerminal) return;
    const t = String(type || '').toUpperCase();
    // P0-6: paused → drop the event (recommended for speed; the ring buffer
    // stays bounded and unpause renders a clean single marker line).
    if (_lmPaused) return;
    _lmStats.total++;
    if (t === 'SHARE') _lmStats.shares++;
    else if (t === 'ERR' || t === 'ERROR') _lmStats.err++;
    _lmAppendEvent(t, msg);
  }

  function _initLmEventLogControls() {
    const clearBtn = document.getElementById('lm-event-log-clear');
    if (clearBtn) clearBtn.addEventListener('click', () => {
      if (dom.lmEventLogTerminal) dom.lmEventLogTerminal.innerHTML = '<div class="lm-event-log__line ts-mute">> CLEARED</div>';
      _lmEventCount = 1;
      _lmStats.total = 0; _lmStats.shares = 0; _lmStats.err = 0;
      _lmRenderStats();
    });
    const pauseBtn = document.getElementById('lm-event-log-pause');
    if (pauseBtn) pauseBtn.addEventListener('click', () => {
      _lmPaused = !_lmPaused;
      pauseBtn.textContent = _lmPaused ? '▶ resume' : '⏸ pause';
      pauseBtn.classList.toggle('is-active', _lmPaused);
      pauseBtn.title = _lmPaused ? 'Resume the event stream' : 'Pause the event stream';
      if (!_lmPaused) {
        // Unpause marker so the operator knows where the stream restarted.
        _lmAppendEvent('JOB', 'stream resumed');
      }
    });
    const filtersEl = document.getElementById('lm-event-log-filters');
    if (filtersEl) {
      filtersEl.querySelectorAll('.chip--filter').forEach(chip => {
        chip.addEventListener('click', () => {
          filtersEl.querySelectorAll('.chip--filter').forEach(c => c.classList.remove('is-active'));
          chip.classList.add('is-active');
          _lmFilter = chip.getAttribute('data-lm-filter') || 'all';
          _lmApplyFilter();
        });
      });
    }
    const jumpBtn = document.getElementById('lm-event-log-jump');
    if (jumpBtn) jumpBtn.addEventListener('click', _lmJumpToBottom);
    const term = dom.lmEventLogTerminal;
    if (term) {
      term.addEventListener('scroll', _lmSyncScrollLock, { passive: true });
      term.addEventListener('wheel', _lmSyncScrollLock, { passive: true });
    }
    _lmRenderStats();
  }



  // ── FLEET-fed rendering: KPIs + worker grid + exceptions + thermal ──
  // Fed by /api/axe-fleet/summary (cached in _ccLastFleet). Runs on every
  // fleet poll; snapshot-fed parts live in renderFleetCommandCenter().
  function _ccRenderFleet() {
    const fleet = _ccLastFleet || [];
    const rows = buildCommandCenterRows(fleet);
    if (dom.lmWorkersCount) dom.lmWorkersCount.textContent = rows.length + (rows.length === 1 ? ' worker' : ' workers');
    if (dom.lmWorkersBadge) dom.lmWorkersBadge.textContent = rows.length + (rows.length === 1 ? ' worker' : ' workers');
    if (dom.lmStatusBadge) dom.lmStatusBadge.textContent = rows.length ? 'LIVE' : 'IDLE';
    if (dom.lmWorkers) dom.lmWorkers.style.display = rows.length ? 'block' : 'none';
    if (dom.lmFlow) dom.lmFlow.style.display = rows.length ? 'block' : 'none';
    if (!rows.length) {
      if (dom.lmWorkersGrid) dom.lmWorkersGrid.innerHTML = '<div class="lm-workers__empty">no fleet workers registered — add miners in AXE FLEET (⚙) to see live per-worker telemetry here</div>';
      if (dom.fccExceptions) { dom.fccExceptions.style.display = 'none'; dom.fccExceptions.innerHTML = ''; }
      if (dom.fccThermalGrid) dom.fccThermalGrid.innerHTML = '';
      // Fleet emptied — drop lingering buffers/counters so a re-added device
      // with reset counters never produces a bogus first delta.
      Object.keys(_lmFlow).forEach(k => delete _lmFlow[k]);
      Object.keys(_lmLastCounters).forEach(k => delete _lmLastCounters[k]);
      return;
    }

    // KPI strip (fleet-fed).
    const k = _ccKpiAgg(fleet);
    if (dom.fccSummaryHr) dom.fccSummaryHr.textContent = k.totalHr ? fmt.hashrate(k.totalHr) : '—';
    _ccHrSeries.push(k.totalHr); if (_ccHrSeries.length > 40) _ccHrSeries.shift();
    if (dom.fccSummaryHrSpark) dom.fccSummaryHrSpark.innerHTML = _ccSvgSparkline(_ccHrSeries, '#00b8d4');
    const onlineN = fleet.filter(d => d.status === 'ONLINE' || d.status === 'HASHING').length;
    const warnN = fleet.filter(d => d.status === 'WARNING').length;
    const offlineN = fleet.length - onlineN - warnN;
    if (dom.fccSummaryOnline) dom.fccSummaryOnline.textContent = String(onlineN);
    if (dom.fccSummaryWarn) dom.fccSummaryWarn.textContent = String(warnN);
    if (dom.fccSummaryOffline) dom.fccSummaryOffline.textContent = String(offlineN);
    if (dom.fccSummaryTemp) dom.fccSummaryTemp.textContent = k.avgTemp != null ? k.avgTemp.toFixed(1) + '°C' : '—';
    if (dom.fccSummaryPower) dom.fccSummaryPower.textContent = k.totalPowerW ? (k.totalPowerW / 1000).toFixed(2) + ' kW' : '—';
    if (dom.fccSummaryEff) dom.fccSummaryEff.textContent = k.avgEff != null ? k.avgEff.toFixed(1) + ' J/TH' : '—';
    if (dom.fccSummaryPing) {
      if (k.avgLatency != null) {
        dom.fccSummaryPing.textContent = k.avgLatency + 'ms';
        dom.fccSummaryPing.classList.toggle('fcc-kpi__val--good', k.avgLatency <= 50);
        dom.fccSummaryPing.classList.toggle('fcc-kpi__val--warn', k.avgLatency > 50);
      } else {
        dom.fccSummaryPing.textContent = '—';
        dom.fccSummaryPing.classList.remove('fcc-kpi__val--good', 'fcc-kpi__val--warn');
      }
    }

    // Flow samples (share-quality raster) + per-device HR history.
    rows.forEach(r => {
      const cur = { a: r.sharesA, r: r.sharesR, s: r.sharesS };
      const delta = _lmShareDelta(_lmLastCounters[r.id], cur);
      _pushLmFlowSample(r.id, { code: _lmFlowSampleFromDelta(r.status, delta), detail: _lmFlowDetail(delta) });
      _lmLastCounters[r.id] = cur;
      if (!_ccHrHist[r.id]) _ccHrHist[r.id] = [];
      const hh = _ccHrHist[r.id];
      hh.push(r.hr); if (hh.length > 40) hh.shift();
    });
    const alive = {}; rows.forEach(r => alive[r.id] = 1);
    Object.keys(_lmFlow).forEach(id => { if (!alive[id]) { delete _lmFlow[id]; delete _lmLastCounters[id]; delete _ccHrHist[id]; } });

    _updateFleetBestShare(rows);
    _ccRenderExceptions(rows);
    _ccRenderThermal(rows);

    // Worker grid (cards ou dense table) + bind dos comandos do agente.
    if (dom.lmWorkersGrid) {
      dom.lmWorkersGrid.innerHTML = (_ccView === 'table') ? _ccRenderTable(rows) : _ccRenderCards(rows);
      dom.lmWorkersGrid.querySelectorAll('.axe-cmd-btn').forEach(btn => {
        btn.addEventListener('click', (e) => { e.stopPropagation(); _handleAxeCmdClick(btn); });
      });
    }

    // Raster — rows = workers, cols = last N samples (oldest left, newest right).
    const cols = _LM_FLOW_MAX;
    if (dom.lmFlowRaster) {
      const raster = rows.map(r => {
        const buf = _lmFlow[r.id] || [];
        let cellsHtml = '';
        for (let i = 0; i < cols; i++) {
          const idx = i - (cols - buf.length);
          const s = idx < 0 ? null : (buf[idx] || null);
          const code = s ? s.code : 'mute';
          // NB: '' is a valid label (mute) — use nullish check, not `|| code`.
          const label = _LM_FLOW_LABELS[code] != null ? _LM_FLOW_LABELS[code] : code;
          const tip = s && s.detail ? label + ' — ' + s.detail : label;
          cellsHtml += '<span class="lm-flow__cell lm-flow__cell--' + code + '" title="' + escapeHtml(tip) + '"></span>';
        }
        return '<div class="lm-flow__row"><span class="lm-flow__label" title="' + escapeHtml(r.ip) + '">' + escapeHtml(r.name) + '</span><div class="lm-flow__cells">' + cellsHtml + '</div></div>';
      }).join('');
      dom.lmFlowRaster.innerHTML = raster;
    }
  }

  // Exception hierarchy — only workers that need a human surface here.
  function _ccRenderExceptions(rows) {
    const box = dom.fccExceptions;
    if (!box) return;
    const bad = rows.filter(r => r.status !== 'ONLINE' && r.status !== 'HASHING');
    if (!bad.length) { box.style.display = 'none'; box.innerHTML = ''; return; }
    const items = bad.map(r => {
      const st = r.status === 'WARNING' ? 'warning' : 'offline';
      const reason = r.advice.length ? r.advice[0] : (r.status === 'WARNING' ? 'degradado — checar telemetria' : 'sem resposta do device');
      return '<span class="fcc-exceptions__item fcc-exceptions__item--' + st + '" title="' + escapeHtml(reason) + '"><span class="fcc-exceptions__dot"></span>' + escapeHtml(r.name) + ' · ' + escapeHtml(reason) + '</span>';
    }).join('');
    box.innerHTML = '<div class="fcc-exceptions__label">⚠ ' + bad.length + ' WORKER(S) PRECISAM DE ATENÇÃO</div><div class="fcc-exceptions__items">' + items + '</div>';
    box.style.display = 'block';
  }

  // Thermal map — hasboard temperatures com thresholds (research: control-room).
  function _ccRenderThermal(rows) {
    const grid = dom.fccThermalGrid;
    if (!grid) return;
    if (!rows.length) { grid.innerHTML = '<div class="lm-workers__empty">sem workers — adicione miners no AXE FLEET</div>'; return; }
    const cell = (label, v, band) => '<div class="fcc-temp fcc-temp--' + band + '" title="' + label + ' ' + (v != null ? Math.round(v) + '°C' : 'n/d') + '"><span class="fcc-temp__lbl">' + label + '</span><span class="fcc-temp__val">' + (v != null ? Math.round(v) + '°' : '—') + '</span></div>';
    grid.innerHTML = rows.map(r => {
      const cells = cell('T', r.temp, _ccTempBand(r.temp)) + cell('CHIP', r.chipTemp, _ccTempBand(r.chipTemp)) + cell('VR', r.vrTemp, _ccTempBand(r.vrTemp));
      return '<div class="fcc-temp-col" title="' + escapeHtml(r.name) + '"><span class="fcc-temp-col__name">' + escapeHtml(r.name) + '</span><div class="fcc-temp-col__cells">' + cells + '</div></div>';
    }).join('');
  }

  // Worker cards (grid view) — health ring, sparkline, share-quality bar.
  function _ccRenderCards(rows) {
    const esc = escapeHtml;
    return rows.map(r => {
      const stCls = (r.status === 'ONLINE' || r.status === 'HASHING') ? 'is-online'
        : (r.status === 'WARNING' || r.status === 'IDLE' || r.status === 'PAUSED') ? 'is-warning' : 'is-offline';
      const stDot = '<span class="fcc-card__dot ' + stCls.replace('is-', '') + '"></span>';
      const hs = r.healthScore != null ? r.healthScore : 0;
      const circumference = 2 * Math.PI * 13;
      const offset = circumference * (1 - Math.min(100, hs) / 100);
      const healthColor = hs >= 80 ? '#00c853' : hs >= 50 ? '#ffd600' : '#ff1744';
      const healthSvg = '<svg class="fcc-card__ring" viewBox="0 0 32 32"><circle class="fcc-card__ring-bg" cx="16" cy="16" r="13"/><circle class="fcc-card__ring-fill" cx="16" cy="16" r="13" stroke="' + healthColor + '" stroke-dasharray="' + circumference + '" stroke-dashoffset="' + offset + '"/></svg>';
      const tempTxt = r.temp != null ? Math.round(r.temp) + '°C' : '—';
      const tempCls = r.temp != null ? 't' + _ccTempBand(r.temp) : '';
      const ping = r.latencyMs != null ? r.latencyMs + 'ms' : '—';
      const pingCls = r.latencyMs == null ? '' : (r.latencyMs <= 50 ? 'good' : r.latencyMs <= 150 ? 'warn' : 'bad');
      const lastShare = r.lastShareAgo != null ? fmt.age(Date.now() / 1000 - r.lastShareAgo) : '—';
      const eff = r.eff != null ? r.eff.toFixed(1) + ' J/TH' : '—';
      const power = r.power != null ? r.power.toFixed(0) + 'W' : '—';
      const fan = r.fan != null ? r.fan + ' rpm' : '—';
      const adviceHtml = r.advice.length ? '<div class="fcc-card__advice">' + r.advice.map(a => '<span class="fcc-card__advice-chip">' + esc(a) + '</span>').join('') + '</div>' : '';
      const restartBtn = r.caps.indexOf('restart') >= 0 ? '<button class="axe-cmd-btn axe-cmd-btn--restart" data-device-id="' + esc(r.id) + '" data-cmd="restart">↻ Restart</button>' : '';
      const identifyBtn = r.caps.indexOf('identify') >= 0 ? '<button class="axe-cmd-btn axe-cmd-btn--identify" data-device-id="' + esc(r.id) + '" data-cmd="identify">◈ Identify</button>' : '';
      const pauseBtn = r.caps.indexOf('pause') >= 0 ? '<button class="axe-cmd-btn axe-cmd-btn--pause" data-device-id="' + esc(r.id) + '" data-cmd="pause">⎔ Pause</button>' : '';
      const resumeBtn = r.caps.indexOf('resume') >= 0 ? '<button class="axe-cmd-btn axe-cmd-btn--resume" data-device-id="' + esc(r.id) + '" data-cmd="resume">▶ Resume</button>' : '';
      return '<div class="fcc-card ' + stCls + '" data-device-id="' + esc(r.id) + '">' +
        '<div class="fcc-card__head">' + healthSvg +
          '<div class="fcc-card__id">' +
            '<div class="fcc-card__name">' + esc(r.name) + stDot + '</div>' +
            '<div class="fcc-card__model">' + esc(r.manufacturer || '') + (r.model ? ' · ' + esc(r.model) : '') + (r.agentManaged ? ' · <span class="fcc-card__agent">AGENT</span>' : '') + '</div>' +
          '</div>' +
          (restartBtn || identifyBtn || pauseBtn || resumeBtn ? '<div class="fcc-card__cmds">' + restartBtn + identifyBtn + pauseBtn + resumeBtn + '</div>' : '<div class="fcc-card__cmds"><span class="axe-card__ro-badge">READ-ONLY</span></div>') +
        '</div>' +
        '<div class="fcc-card__hr"><span class="fcc-card__hr-val">' + esc(r.hrStr) + '</span>' + _ccSvgSparkline(_ccHrHist[r.id], '#00b8d4') + '</div>' +
        '<div class="fcc-card__stats">' +
          '<div class="fcc-card__stat"><span class="lbl">TEMP</span><span class="val ' + tempCls + '">' + tempTxt + '</span></div>' +
          '<div class="fcc-card__stat"><span class="lbl">POWER</span><span class="val">' + power + '</span></div>' +
          '<div class="fcc-card__stat"><span class="lbl">EFF</span><span class="val">' + eff + '</span></div>' +
          '<div class="fcc-card__stat"><span class="lbl">FAN</span><span class="val">' + fan + '</span></div>' +
          '<div class="fcc-card__stat"><span class="lbl">LAST SHARE</span><span class="val">' + lastShare + '</span></div>' +
          '<div class="fcc-card__stat"><span class="lbl">PING</span><span class="val ' + pingCls + '">' + ping + '</span></div>' +
        '</div>' +
        '<div class="fcc-card__shares"><span class="fcc-card__shares-lbl">SHARES A/S/R</span>' + _ccShareBar(r.sharesA, r.sharesR, r.sharesS) + '</div>' +
        adviceHtml +
      '</div>';
    }).join('');
  }

  // Dense table view (HiveOS-style worker list).
  function _ccRenderTable(rows) {
    const esc = escapeHtml;
    const cell = (v, cls) => '<span class="fcc-t__cell' + (cls ? ' ' + cls : '') + '">' + v + '</span>';
    const head = ['WORKER', 'HR', 'TEMP', 'POWER', 'EFF', 'SHARES A/S/R', 'REJ%', 'LAST SHARE', 'PING', 'HEALTH', '']
      .map(h => cell(h, 'fcc-t__cell--head')).join('');
    const body = rows.map(r => {
      const stCls = (r.status === 'ONLINE' || r.status === 'HASHING') ? 'fcc-t__st--ok'
        : (r.status === 'WARNING' || r.status === 'IDLE' || r.status === 'PAUSED') ? 'fcc-t__st--warn' : 'fcc-t__st--bad';
      const tempTxt = r.temp != null ? Math.round(r.temp) + '°C' : '—';
      const tempCls = r.temp != null ? 'fcc-t__temp t' + _ccTempBand(r.temp) : '';
      const rej = r.rejectPct != null ? Number(r.rejectPct).toFixed(1) + '%' : '—';
      const lastShare = r.lastShareAgo != null ? fmt.age(Date.now() / 1000 - r.lastShareAgo) : '—';
      const ping = r.latencyMs != null ? r.latencyMs + 'ms' : '—';
      const health = r.healthScore != null ? r.healthScore + '/100' : '—';
      const shares = r.sharesA + '/' + r.sharesS + '/' + r.sharesR;
      const restartBtn = r.caps.indexOf('restart') >= 0
        ? '<button class="axe-cmd-btn axe-cmd-btn--restart axe-cmd-btn--mini" data-device-id="' + esc(r.id) + '" data-cmd="restart" title="Restart">↻</button>' : '';
      return '<div class="fcc-t__row">' +
        cell('<span class="fcc-t__name ' + stCls + '">' + esc(r.name) + '</span>' + (r.agentManaged ? '<span class="fcc-t__agent">AGENT</span>' : '')) +
        cell(esc(r.hrStr)) + cell(tempTxt, tempCls) +
        cell(r.power != null ? r.power.toFixed(0) + 'W' : '—') +
        cell(r.eff != null ? r.eff.toFixed(1) + ' J/TH' : '—') +
        cell(shares) + cell(rej, r.rejectPct != null && r.rejectPct >= 5 ? 'fcc-t__cell--bad' : '') +
        cell(lastShare) + cell(ping) + cell(health) + cell(restartBtn, 'fcc-t__cell--cmd') +
      '</div>';
    }).join('');
    return '<div class="fcc-t"><div class="fcc-t__row fcc-t__row--head">' + head + '</div>' + body + '</div>';
  }
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
      const r = await authFetch('/api/tailscale');
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
      const r = await authFetch('/api/axe-fleet/remote/onboarding');
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
    // FLEET COMMAND CENTER rides the same poll/SSE cadence.
    fetchFleetCommandCenter();
  }

  // ── LAN SCANNER (Phase B) — auto-discover miners on the local network ─
  let _scanning = false;
  async function scanNetwork() {
    if (_scanning) return;
    _scanning = true;
    const btn = dom.axeFleetScan;
    if (btn) { btn.textContent = '⏳ SCANNING…'; btn.disabled = true; }
    try {
      const r = await authFetch('/api/network/scan', { method: 'POST' });
      const data = await r.json();
      if (!data.success) throw new Error(data.error || 'scan failed');
      const found = data.found || 0;
      const dur = data.duration_ms || 0;
      const devs = data.devices || [];
      if (found === 0) {
        showToast('info', 'Scan complete — no mining devices found on LAN (' + (data.scanned || 0) + ' IPs probed in ' + dur + 'ms)');
      } else {
        showToast('success', found + ' device(s) found (' + dur + 'ms) — check Fleet to add them');
        // Render results as a simple list below the fleet grid
        renderScanResults(devs);
      }
    } catch (e) {
      logMessage('SCAN', 'Network scan failed: ' + e.message, 'WARN');
    } finally {
      _scanning = false;
      if (btn) { btn.textContent = '🔍 SCAN NETWORK'; btn.disabled = false; }
    }
  }

  function renderScanResults(devices) {
    let container = document.getElementById('scan-results');
    if (!container) {
      container = document.createElement('div');
      container.id = 'scan-results';
      container.className = 'scan-results';
      const grid = dom.axeGrid;
      if (grid && grid.parentNode) {
        grid.parentNode.insertBefore(container, grid.nextSibling);
      }
    }
    const items = devices.map(function(d) {
      var ports = (d.open_ports || []).join(', ');
      var hint = d.firmware_hint ? ' <span class="scan-results__hint">' + escapeHtml(d.firmware_hint) + '</span>' : '';
      var host = d.hostname ? ' <span class="scan-results__host">' + escapeHtml(d.hostname) + '</span>' : '';
      return '<div class="scan-results__item" data-ip="' + escapeHtml(d.ip) + '">' +
        '<span class="scan-results__ip">' + escapeHtml(d.ip) + '</span>' +
        '<span class="scan-results__ports">ports: ' + (ports || 'none') + '</span>' +
        hint + host +
        '<button class="chip scan-results__add" data-ip="' + escapeHtml(d.ip) + '">+ Add</button>' +
        '</div>';
    }).join('');
    container.innerHTML = '<div class="scan-results__head">🔍 SCAN RESULTS <button class="chip scan-results__dismiss">✕ dismiss</button></div>' + items;
    container.style.display = 'block';
    // Wire dismiss + per-device Add buttons
    container.querySelector('.scan-results__dismiss')?.addEventListener('click', function() {
      container.style.display = 'none';
    });
    container.querySelectorAll('.scan-results__add').forEach(function(btn) {
      btn.addEventListener('click', function() {
        var ip = btn.getAttribute('data-ip') || '';
        if (ip) openAxeAddForm(ip);
      });
    });
  }

  // ── Helper: open the AXE add form pre-filled with an IP ───────────────
  function openAxeAddForm(ip) {
    var form = dom.axeAddForm || document.getElementById('axe-add-form');
    var ipInput = document.getElementById('axe-add-ip');
    if (form && ipInput) {
      ipInput.value = ip || '';
      form.style.display = 'block';
      // Trigger the same onboarding wizard reset the add button uses
      if (typeof resetAxeWizard === 'function') resetAxeWizard();
    }
  }

  // ── FLEET COMMAND CENTER · WORKER INTELLIGENCE ────────────────────────
  // Per-worker live telemetry fed by the AXE FLEET /summary endpoint
  // (shares, reject ratio, temps, power, efficiency, latency, health).
  // Honest '—' whenever a firmware doesn't expose a field. Exception
  // hierarchy: WARNING/IDLE/PAUSED first, then OFFLINE/ERROR/CRITICAL,
  // healthy ONLINE workers last. Pure builder mirrored in tests.
  function buildCommandCenterRows(devices) {
    const rows = [];
    (devices || []).forEach(function (d) {
      const tel = d._telemetry || {};
      const health = d._health || {};
      const accepted = Number(tel.shares_accepted) || 0;
      const rejected = Number(tel.shares_rejected) || 0;
      const stale = Number(tel.shares_stale) || 0;
      const total = accepted + rejected;
      let rejectPct = null;
      if (total > 0) {
        rejectPct = Number(tel.hw_error_pct != null ? tel.hw_error_pct : (rejected / total) * 100);
      }
      // Last-share age in seconds (best-effort — firmware may not expose it).
      let lastShareAgo = null;
      const lst = tel.last_share_ts;
      if (lst != null && lst !== '') {
        let t = Number(lst);
        if (!isFinite(t) || t > 1e12) t = Date.parse(String(lst)) / 1000;
        if (isFinite(t) && t > 0) lastShareAgo = Math.max(0, Math.floor(Date.now() / 1000 - t));
      }
      rows.push({
        id: d.id || '',
        name: d.name || d.ip_address || '?',
        ip: d.ip_address || '',
        model: d.model || '',
        manufacturer: d.manufacturer || '',
        status: d.status || 'OFFLINE',
        agentManaged: !!d.agent_managed,
        hr: Number(tel.hashrate_hs) || 0,
        hrStr: tel.hashrate_str || fmt.hashrate(tel.hashrate_hs),
        temp: _numOrNull(tel.temperature),
        chipTemp: _numOrNull(tel.chip_temp),
        vrTemp: _numOrNull(tel.vr_temp),
        fan: tel.fan_rpm != null ? tel.fan_rpm : tel.fan_speed,
        power: _numOrNull(tel.power_watts),
        eff: _numOrNull(tel.efficiency_jth),
        sharesA: accepted, sharesR: rejected, sharesS: stale,
        rejectPct: rejectPct,
        bestDiff: tel.best_diff,
        poolDiff: tel.pool_diff,
        lastShareAgo: lastShareAgo,
        latencyMs: d.latency_ms,
        stratum: tel.stratum_status || '',
        healthScore: health.score != null ? health.score : null,
        advice: Array.isArray(d.advice) ? d.advice : [],
        caps: Array.isArray(d.capabilities) ? d.capabilities : [],
      });
    });
    // Exception hierarchy (research: manage by exception) — problems first.
    const order = { WARNING: 0, IDLE: 0, PAUSED: 0, OFFLINE: 1, ERROR: 1, CRITICAL: 1, ONLINE: 2, HASHING: 2 };
    rows.sort(function (a, b) {
      const oa = order[a.status] != null ? order[a.status] : 3;
      const ob = order[b.status] != null ? order[b.status] : 3;
      if (oa !== ob) return oa - ob;
      return String(a.name).localeCompare(String(b.name));
    });
    return rows;
  }
  // Hash Flow Raster — rolling per-worker status samples (client-side ring
  // buffer, one column per poll tick, max 24) so the feed shows worker
  // health over time without requiring a new backend series.
  const _lmFlow = {};
  const _lmLastCounters = {}; // per-device previous cumulative share counters
  const _LM_FLOW_MAX = 24;
  // Raster cell color reflects SHARE QUALITY for the tick, not just device
  // status: we diff the firmware's cumulative counters (shares_accepted /
  // rejected / stale) between consecutive polls. A reject/stale is far more
  // actionable than a plain "online" cell — it signals pool/hardware trouble.
  const _LM_FLOW_LABELS = { ok: 'share', rej: 'reject', stale: 'stale', idle: 'online', warn: 'warn', bad: 'offline', mute: '' };
  // Pure: map (device status, per-tick share delta) → raster cell color code.
  function _lmFlowSampleFromDelta(status, delta) {
    if (delta) {
      if (delta.r > 0) return 'rej';    // reject beats everything
      if (delta.s > 0) return 'stale';  // stale beats accepted
      if (delta.a > 0) return 'ok';     // accepted share
    }
    const s = String(status || '').toUpperCase();
    if (s === 'ONLINE' || s === 'HASHING') return 'idle';
    if (s === 'WARNING' || s === 'IDLE' || s === 'PAUSED') return 'warn';
    if (s === 'OFFLINE' || s === 'ERROR' || s === 'CRITICAL') return 'bad';
    return 'mute';
  }
  // Pure: diff cumulative share counters, clamping negatives (a firmware
  // reboot resets them — a drop is a reset, not negative shares).
  function _lmShareDelta(prev, cur) {
    if (!prev) return null;
    return {
      a: Math.max(0, (cur.a || 0) - (prev.a || 0)),
      r: Math.max(0, (cur.r || 0) - (prev.r || 0)),
      s: Math.max(0, (cur.s || 0) - (prev.s || 0)),
    };
  }
  // Pure: human tooltip for a tick's delta ("+3 acc · +1 rej").
  function _lmFlowDetail(delta) {
    if (!delta) return '';
    const parts = [];
    if (delta.a > 0) parts.push('+' + delta.a + ' acc');
    if (delta.r > 0) parts.push('+' + delta.r + ' rej');
    if (delta.s > 0) parts.push('+' + delta.s + ' stale');
    return parts.join(' · ');
  }
  function _pushLmFlowSample(id, sample) {
    if (!_lmFlow[id]) _lmFlow[id] = [];
    const buf = _lmFlow[id];
    buf.push(sample);
    if (buf.length > _LM_FLOW_MAX) buf.shift();
  }

  // FLEET COMMAND CENTER — fetch /summary and render. Non-fatal: on
  // failure the panel simply keeps the last good data.
  async function fetchFleetCommandCenter() {
    try {
      const r = await authFetch('/api/axe-fleet/summary');
      if (!r.ok) return;
      const data = await r.json();
      _ccLastFleet = (data && data.devices) || [];
      _ccRenderFleet();
    } catch (e) { /* non-fatal */ }
  }

  // View toggle (grid cards / dense table) — persisted per browser.
  function initFleetCommandCenterControls() {
    try { _ccView = localStorage.getItem('_cc_view') || 'grid'; } catch (e) {}
    const chips = document.querySelectorAll('.chip--view');
    chips.forEach(chip => {
      chip.classList.toggle('is-active', chip.getAttribute('data-cc-view') === _ccView);
      chip.addEventListener('click', () => {
        _ccView = chip.getAttribute('data-cc-view') || 'grid';
        chips.forEach(c => c.classList.toggle('is-active', c.getAttribute('data-cc-view') === _ccView));
        try { localStorage.setItem('_cc_view', _ccView); } catch (e) {}
        _ccRenderFleet();
      });
    });
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
        '<div class="axe-empty__hint">⚠ Dashboard na nuvem não alcança a sua LAN (192.168.x.x não é roteável a partir do Render). Rode o <strong>AGENTE LOCAL</strong> na sua rede — Fleet → 🤖 CONNECT AGENT — ele descobre os miners e conecta para fora. (Self-host: rode o app na mesma Wi-Fi dos miners ou use um IP Tailscale.)</div></div>';
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

    // Attach command button handlers (shared with the FLEET COMMAND CENTER
    // cards — one implementation via _handleAxeCmdClick).
    dom.axeGrid.querySelectorAll('.axe-cmd-btn').forEach(btn => {
      btn.addEventListener('click', (e) => { e.stopPropagation(); _handleAxeCmdClick(btn); });
    });
  }

  // ── Shared axe-fleet command router ──────────────────────────────────
  // restart/identify → agent queue via authFetch (Bearer); pause/resume →
  // core route. Used by both the AXE FLEET grid and the FLEET COMMAND
  // CENTER worker cards. The routing decision is mirrored in tests.
  async function _handleAxeCmdClick(btn) {
    const deviceId = btn.dataset.deviceId;
    const command = btn.dataset.cmd;
    if (!deviceId || !command) return;

    // Confirmation for restart and pause
    if (command === 'restart') {
      if (!confirm('Restart this miner? It will go offline for ~30 seconds.')) return;
    } else if (command === 'pause') {
      if (!confirm('Pause mining on this device? Use Resume to restart.')) return;
    }

    // Captura o label original (ex.: '↻' no botão mini da tabela) para
    // restaurar exatamente o que havia — sem hardcodar o texto do botão.
    const originalLabel = btn.textContent;
    btn.disabled = true;
    btn.textContent = '...';

    // FIX (auditoria UI): os cards do AXE FLEET vivem no axe registry
    // (tenant-scoped) e devices agent-managed só podem ser controlados
    // através da fila do AGENTE LOCAL. A rota core /api/devices/<id>/command
    // consulta o core registry — para estes devices ela responde 404 e o
    // miner NUNCA reinicia (teatro). Roteamos restart/identify/pause/resume
    // para os endpoints /api/axe-fleet/devices/<id>/{restart|identify|
    // pause|resume}, que enfileiram no agente (agent-managed) ou executam
    // direto no AxeOS HTTP API, e exigem o Bearer do tenant (authFetch).
    const isAgentRouted = command === 'restart' || command === 'identify' ||
      command === 'pause' || command === 'resume';
    const url = isAgentRouted
      ? '/api/axe-fleet/devices/' + encodeURIComponent(deviceId) + '/' + command
      : '/api/devices/' + encodeURIComponent(deviceId) + '/command';
    const opts = {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(isAgentRouted ? {} : { command: command }),
    };
    try {
      const resp = isAgentRouted ? await authFetch(url, opts) : await fetch(url, opts);
      const data = await resp.json().catch(() => ({}));
      if (data.success) {
        const name = btn.closest('.axe-card, .fcc-card')?.querySelector('.axe-card__name, .fcc-card__name')?.textContent || 'device';
        showToast('success', (data.message || command + ' sent to ' + name));
      } else {
        showToast('error', data.error || ('Command failed (' + resp.status + ')'));
      }
    } catch (err) {
      showToast('error', 'Network error: ' + err.message);
    } finally {
      btn.disabled = false;
      btn.textContent = originalLabel;
    }
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
        (supportedCmds.indexOf('resume') >= 0 ? '<button class="axe-cmd-btn axe-cmd-btn--resume" data-device-id="' + escapeHtml(d.id) + '" data-cmd="resume">▶ Resume</button>' : '') +
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
          '<div class="axe-detail__item"><div class="lbl">' + escapeHtml(it.lbl) + '</div><div class="val' + (it.cls ? ' ' + escapeHtml(it.cls) : '') + '">' + escapeHtml(String(it.val)) + '</div></div>'
        ).join('');

        // Phase C: load telemetry history chart
        loadDeviceHistoryChart(deviceId);
      })
      .catch(() => {
        dom.axeDetailBody.innerHTML = '<div class="axe-detail__loading">error loading device telemetry</div>';
      });
  }

  // ── Phase C: Device History Chart ─────────────────────────────────────
  let _axeDetailChart = null;

  async function loadDeviceHistoryChart(deviceId) {
    const wrap = document.getElementById('axe-detail-chart-wrap');
    const canvas = document.getElementById('axe-detail-chart');
    const countBadge = document.getElementById('axe-detail-chart-count');
    if (!wrap || !canvas) return;

    // Destroy previous chart instance so Chart.js doesn't complain.
    if (_axeDetailChart) { _axeDetailChart.destroy(); _axeDetailChart = null; }

    try {
      const r = await authFetch('/api/axe-fleet/devices/' + encodeURIComponent(deviceId) + '/history?limit=120');
      if (!r.ok) return;
      const data = await r.json();
      const rows = data.history || [];
      if (rows.length < 2) return;  // need at least 2 points for a line

      wrap.style.display = 'block';
      if (countBadge) countBadge.textContent = rows.length + ' points';

      var labels = rows.map(function(r) {
        var d = new Date(r.ts * 1000);
        return d.getHours().toString().padStart(2, '0') + ':' + d.getMinutes().toString().padStart(2, '0');
      });

      var hrVals = rows.map(function(r) { return r.hashrate ? r.hashrate / 1e12 : null; });
      var tempVals = rows.map(function(r) { return r.temperature; });
      var effVals = rows.map(function(r) { return r.efficiency_jth; });

      _axeDetailChart = new Chart(canvas.getContext('2d'), {
        type: 'line',
        data: {
          labels: labels,
          datasets: [
            { label: 'Hashrate TH/s', data: hrVals, borderColor: 'rgb(6,214,240)', backgroundColor: 'rgba(6,214,240,0.06)', tension: 0.3, pointRadius: 0, fill: true, yAxisID: 'y' },
            { label: 'Temp °C', data: tempVals, borderColor: 'rgb(255,160,0)', backgroundColor: 'rgba(255,160,0,0.04)', tension: 0.3, pointRadius: 0, borderDash: [4, 2], yAxisID: 'y1' },
            { label: 'Eff J/TH', data: effVals, borderColor: 'rgb(186,133,224)', backgroundColor: 'transparent', tension: 0.3, pointRadius: 0, borderDash: [2, 3], yAxisID: 'y1' },
          ]
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          interaction: { mode: 'index', intersect: false },
          scales: {
            x: { ticks: { color: '#5E5952', maxTicksLimit: 10, font: { size: 9 } }, grid: { color: 'rgba(94,89,82,0.12)' } },
            y: { type: 'linear', position: 'left', title: { display: true, text: 'TH/s', color: 'rgb(6,214,240)' }, ticks: { color: '#5E5952', font: { size: 9 } }, grid: { color: 'rgba(94,89,82,0.10)' } },
            y1: { type: 'linear', position: 'right', title: { display: true, text: '°C / J/TH', color: 'rgb(255,160,0)' }, ticks: { color: '#5E5952', font: { size: 9 } }, grid: { display: false } }
          },
          plugins: {
            legend: { labels: { color: '#C6C3BF', font: { size: 9 }, usePointStyle: true, padding: 12 } }
          }
        }
      });
    } catch (e) {
      // Non-fatal: chart is a nice-to-have, detail panel still works.
    }
  }

  // ── AXE FLEET: LAN discovery (subnet scan) ───────────────────────────
  // Automatic miner detection so the operator never types an IP. Flow:
  //  1. POST /api/axe-fleet/scan {cidr}  → 202 {scan_id}
  //  2. Poll GET /api/axe-fleet/scan/<id> every 1.5s (progress + found)
  //  3. Render found miners as rows with a per-row ADD button that reuses
  //     the same addAxeDevice() as the manual form.
  function renderAxeScanResults(found, scan) {
    const box = dom.axeScanResults;
    if (!box) return;
    if (!found || !found.length) {
      // No miners: surface the alive-vs-miner layer (hosts whose TCP port
      // opened but no miner protocol answered) and the private-LAN topology
      // hint — a flat "no miners found" hides whether the subnet is even
      // reachable (cloud dashboard vs home LAN).
      const alive = (scan && scan.alive) || 0;
      const hint = (scan && scan.hint) || '';
      let html = '<div style="font-size:9px;color:var(--text-tertiary)">no miners found on this subnet</div>';
      if (alive > 0) {
        html += '<div style="font-size:9px;color:var(--text-secondary);margin-top:4px">' + alive + ' host(s) alive (porta TCP aberta) mas sem protocolo de miner — possíveis ASICs com API autenticada/firewall. Verifique com TEST CONNECTIVITY em um IP específico.</div>';
      }
      if (hint) {
        html += '<div style="font-size:9px;color:var(--amber);margin-top:4px">' + escapeHtml(hint) + '</div>';
      }
      box.innerHTML = html;
      return;
    }
    const rows = found.map(d => {
      const ip = escapeHtml(d.ip || '');
      const model = escapeHtml(d.model || 'unknown');
      const host = escapeHtml(d.hostname || '');
      const type = d.type === 'cgminer' ? 'CGMINER' : 'BITAXE';
      const hr = d.hashrate_hs ? fmt.hashrate(d.hashrate_hs) : '';
      const title = escapeHtml([d.firmware, d.version].filter(Boolean).join(' ') || 'miner');
      return `<div class="axe-scan__row" data-ip="${ip}" style="display:flex;gap:6px;align-items:center;padding:2px 0;border-bottom:1px dashed var(--border-subtle);font-size:10px">
        <span class="badge badge--green" style="font-size:7px;min-width:48px">${type}</span>
        <span style="color:var(--text-primary)" title="${title}">${ip}</span>
        <span style="color:var(--text-secondary)" title="${title}">${model}${host ? ' · ' + host : ''}</span>
        ${hr ? `<span style="color:var(--text-tertiary)">${escapeHtml(hr)}</span>` : ''}
        <button class="chip axe-scan-add" data-ip="${ip}" data-model="${model}" data-host="${host}" data-fw="${escapeHtml(d.firmware || '')}" data-ver="${escapeHtml(d.version || '')}" data-hr="${Number(d.hashrate_hs) || 0}" style="margin-left:auto;font-size:8px">+ ADD</button>
      </div>`;
    }).join('');
    box.innerHTML = rows;
    // Scan ADD opens the wizard's confirm step (step 3) with the detected
    // miner pre-filled — a single place to review + name before registering.
    box.querySelectorAll('.axe-scan-add').forEach(btn => {
      btn.addEventListener('click', () => {
        _axeWizState.ip = btn.getAttribute('data-ip') || '';
        _axeWizState.mode = 'scan';
        _axeWizState.device = {
          protocol: btn.getAttribute('data-model') ? 'bitaxe' : '',
          model: btn.getAttribute('data-model') || 'miner',
          hostname: btn.getAttribute('data-host') || '',
          firmware: btn.getAttribute('data-fw') || '',
          version: btn.getAttribute('data-ver') || '',
          hashrate_hs: Number(btn.getAttribute('data-hr') || 0),
        };
        if (dom.axeAddName) dom.axeAddName.value = btn.getAttribute('data-model') || '';
        if (dom.axeManualNameRow) dom.axeManualNameRow.style.display = 'block';
        renderAxeConfirm();
        gotoAxeWizStep(3);
      });
    });
  }

  async function startAxeScan(cidr) {
    const statusEl = dom.axeScanStatus;
    const btn = dom.axeScanBtn;
    const cidrInput = dom.axeScanCidr;
    if (btn) btn.disabled = true;
    if (statusEl) { statusEl.textContent = '> scanning ' + cidr + '…'; statusEl.style.color = 'var(--text-tertiary)'; }
    try {
      const r = await authFetch('/api/axe-fleet/scan', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ cidr })
      });
      const data = await r.json();
      if (!r.ok || !data.scan_id) {
        if (statusEl) { statusEl.textContent = '? ' + ((data && data.error) || 'scan failed'); statusEl.style.color = 'var(--accent-red)'; }
        return;
      }
      const scanId = data.scan_id;
      // Poll until done
      for (let i = 0; i < 240; i++) {  // ~6 min cap
        await new Promise(res => setTimeout(res, 1500));
        try {
          const p = await authFetch('/api/axe-fleet/scan/' + scanId);
          const pd = await p.json();
          const s = pd.scan || {};
          const scanned = s.scanned || 0;
          const total = s.total || 0;
          if (statusEl) statusEl.textContent = `> probing ${scanned}/${total} hosts…`;
          if (s.status === 'done' || s.status === 'error') {
            if (statusEl) {
              const foundN = (s.found || []).length;
              const aliveN = s.alive || 0;
              statusEl.textContent = s.error ? '? ' + s.error : foundN > 0 ? `✓ ${foundN} miner(s) found` : (aliveN > 0 ? `✓ 0 miners · ${aliveN} host(s) alive sem protocolo` : '✓ 0 miners — nada respondeu');
              statusEl.style.color = s.error ? 'var(--accent-red)' : 'var(--accent-green)';
            }
            renderAxeScanResults(s.found || [], s);
            return;
          }
        } catch (e) { /* transient poll failure — keep polling */ }
      }
      if (statusEl) { statusEl.textContent = '? scan timed out'; statusEl.style.color = 'var(--accent-red)'; }
    } catch (e) {
      if (statusEl) { statusEl.textContent = '? network error: ' + e.message; statusEl.style.color = 'var(--accent-red)'; }
    } finally {
      if (btn) btn.disabled = false;
      if (cidrInput) cidrInput.disabled = false;
    }
  }

  function initAxeScanControls() {
    const cidrInput = dom.axeScanCidr;
    const btn = dom.axeScanBtn;
    if (!cidrInput || !btn) return;
    // Prefill with a suggested local subnet (best-effort; backend derives it
    // from this host's interfaces).
    authFetch('/api/axe-fleet/scan/subnets')
      .then(r => r.ok ? r.json() : { subnets: [] })
      .then(d => {
        const s = (d.subnets || [])[0];
        if (s && !cidrInput.value.trim()) cidrInput.value = s;
      })
      .catch(() => {});
    btn.addEventListener('click', () => {
      const cidr = (cidrInput.value || '').trim() || '192.168.1.0/24';
      cidrInput.disabled = true;
      // Clear stale results BEFORE the scan starts (a null/empty call must
      // blank the box, not render the "no miners found" placeholder).
      if (dom.axeScanResults) dom.axeScanResults.innerHTML = '';
      startAxeScan(cidr);
    });
    cidrInput.addEventListener('keydown', e => {
      if (e.key === 'Enter') { e.preventDefault(); btn.click(); }
    });
  }

  // ── AXE FLEET onboarding wizard ──────────────────────────────────────
  // 3 steps: 1 · method → 2 · connect (scan OR manual+test) → 3 · confirm.
  // Pure helpers are mirrored in tests/test_app_js_core.js.

  // Build the connectivity report rows from the /diagnose response. Pure —
  // returns an array of {label, ok, val, detail} for rendering + tests.
  function buildConnectivityReport(result) {
    const r = result || {};
    const rows = [];
    rows.push({ label: 'DNS', ok: !!r.dns_resolution, val: r.dns_resolution ? 'OK' : 'FAIL', detail: r.dns_resolution ? '' : (r.error_detail || 'hostname did not resolve') });
    if (r.bitaxe_http) {
      const di = r.device_info || {};
      rows.push({ label: 'AxeOS :80', ok: true, val: 'BITAXE', detail: [di.model, di.firmware].filter(Boolean).join(' · ') });
    } else {
      rows.push({ label: 'AxeOS :80', ok: false, val: 'no', detail: 'no ESP-Miner API on port 80' });
    }
    if (r.cgminer_tcp) {
      const di = r.device_info || {};
      // Show firmware label for the cgminer row — Braiins OS+ devices
      // answer on :4028 but the protocol label should reflect the detector.
      const cgLabel = (r.protocol === 'braiins') ? 'BRAIINS' : 'CGMINER';
      rows.push({ label: 'cgminer :4028', ok: true, val: cgLabel, detail: [di.model, di.version].filter(Boolean).join(' · ') });
    } else {
      rows.push({ label: 'cgminer :4028', ok: false, val: 'no', detail: 'no cgminer protocol on port 4028' });
    }
    // Protocol-presence rows (D): a modern authenticated miner (Braiins
    // OS+/Antminer login page) answers nothing on the classic probes but
    // shows TCP :443 or a non-ESP-Miner web server on :80 — surface that
    // instead of a flat "no protocol".
    if (r.https_tcp && !r.bitaxe_http && !r.cgminer_tcp) {
      rows.push({ label: 'HTTPS :443', ok: true, val: 'OPEN', detail: 'porta 443 aberta — firmware moderno (Braiins/Antminer) com API autenticada' });
    }
    if (r.http_server && !r.bitaxe_http && !r.cgminer_tcp) {
      rows.push({ label: 'HTTP :80', ok: true, val: 'server', detail: 'servidor HTTP presente mas NÃO é ESP-Miner — possível página de login de ASIC' });
    }
    rows.push({ label: 'elapsed', ok: true, val: (r.elapsed_ms != null ? r.elapsed_ms + 'ms' : '—'), detail: '' });
    return rows;
  }

  // Render the connectivity report into #axe-test-result. Pure-ish (DOM
  // writes only) so a failed test leaves clear actionable guidance.
  function renderConnectivityReport(result) {
    const box = dom.axeTestResult;
    if (!box) return;
    const rows = buildConnectivityReport(result);
    const reachable = !!(result || {}).reachable;
    const proto = (result || {}).protocol;
    const html = rows.map(row => {
      const cls = row.ok ? 'axe-wiz-check--ok' : 'axe-wiz-check--fail';
      const icon = row.ok ? '✓' : '✗';
      const detail = row.detail ? `<span style="color:var(--text-tertiary);margin-left:6px">${escapeHtml(row.detail)}</span>` : '';
      return `<div class="axe-wiz-check ${cls}"><span>${icon}</span><span class="axe-wiz-check__label">${escapeHtml(row.label)}</span><span class="axe-wiz-check__val">${escapeHtml(row.val)}</span>${detail}</div>`;
    }).join('');
    const verdict = reachable
      ? `<div class="axe-wiz-check axe-wiz-check--ok" style="margin-top:4px"><span>✓</span><span class="axe-wiz-check__label">READY</span><span class="axe-wiz-check__val">${escapeHtml(String(proto || '').toUpperCase())} miner detected</span></div>`
      : `<div class="axe-wiz-check axe-wiz-check--fail" style="margin-top:4px"><span>✗</span><span class="axe-wiz-check__label">UNREACHABLE</span><span class="axe-wiz-check__val">check power / network / firewall</span><span style="color:var(--text-tertiary);margin-left:6px">${escapeHtml((result || {}).error_detail || '')}</span></div>`;
    box.innerHTML = html + verdict;
    // Reveal the optional name field only when the miner is reachable
    if (dom.axeManualNameRow) dom.axeManualNameRow.style.display = reachable ? 'block' : 'none';
    return reachable;
  }

  // Test connectivity for the manual-IP step. Shows a spinner, calls the
  // backend /diagnose endpoint, renders the report, then advances to step 3
  // when a miner is reachable.
  async function testAxeConnectivity() {
    const ipInput = dom.axeAddIp;
    const btn = dom.axeTestConn;
    const box = dom.axeTestResult;
    if (!ipInput || !btn) return false;
    const ip = (ipInput.value || '').trim();
    if (!ip) {
      if (box) box.innerHTML = '<div class="axe-wiz-check axe-wiz-check--fail"><span>✗</span><span class="axe-wiz-check__label">INPUT</span><span class="axe-wiz-check__val">enter an IP or hostname</span></div>';
      return false;
    }
    const prev = btn.textContent;
    btn.disabled = true;
    btn.textContent = '… testing';
    if (box) box.innerHTML = '<div class="axe-wiz-check axe-wiz-check--idle"><span class="axe-wiz__spinner"></span><span class="axe-wiz-check__label">PROBING</span><span class="axe-wiz-check__val">' + escapeHtml(ip) + '</span></div>';
    try {
      const r = await authFetch('/api/axe-fleet/diagnose/' + encodeURIComponent(ip));
      const data = await r.json();
      const reachable = renderConnectivityReport(data);
      // Store the detected firmware/model from the diagnose response so
      // the confirm screen can preview them before registration.
      _axeWizState._detectedProtocol = data && data.protocol;
      _axeWizState._detectedFirmware = data && data.detected_firmware;
      _axeWizState._detectedModel = data && data.detected_model;
      _axeWizState._detectedVersion = (data && data.device_info && data.device_info.version) || '';
      if (reachable) {
        // Advance to confirm step with the detected device. Carry the
        // protocol from the diagnose response (top-level) into device so
        // the confirm summary can display it.
        _axeWizState.device = Object.assign({}, (data && data.device_info) || {}, { protocol: data && data.protocol });
        _axeWizState.ip = ip;
        renderAxeConfirm();
        gotoAxeWizStep(3);
        return true;
      }
      return false;
    } catch (e) {
      if (box) box.innerHTML = '<div class="axe-wiz-check axe-wiz-check--fail"><span>✗</span><span class="axe-wiz-check__label">ERROR</span><span class="axe-wiz-check__val">' + escapeHtml(e.message) + '</span></div>';
      return false;
    } finally {
      btn.disabled = false;
      btn.textContent = prev;
    }
  }

  const _axeWizState = { ip: '', name: '', device: null, mode: null };

  function gotoAxeWizStep(step) {
    const form = dom.axeAddForm;
    if (!form) return;
    step = Math.max(1, Math.min(3, step));
    // Panels: data-wiz-panel="1|2|3" — show matching, hide others
    form.querySelectorAll('[data-wiz-panel]').forEach(p => {
      p.style.display = (Number(p.getAttribute('data-wiz-panel')) === step) ? 'block' : 'none';
    });
    // Within step 2, choose scan vs manual mode
    if (step === 2) {
      form.querySelectorAll('[data-wiz-panel][data-wiz-mode]').forEach(p => {
        const on = p.getAttribute('data-wiz-mode') === (_axeWizState.mode || 'scan');
        p.style.display = on ? 'block' : 'none';
      });
    }
    // Step indicator
    if (dom.axeWizSteps) {
      dom.axeWizSteps.querySelectorAll('[data-wiz-step]').forEach(s => {
        const n = Number(s.getAttribute('data-wiz-step'));
        s.classList.toggle('is-active', n === step);
        s.classList.toggle('is-done', n < step);
      });
    }
    // Focus primary input of the active panel
    if (step === 1 && dom.axeEmptyAdd) dom.axeEmptyAdd.blur();
    if (step === 2 && _axeWizState.mode === 'manual') { setTimeout(() => dom.axeAddIp?.focus(), 60); }
    if (step === 2 && _axeWizState.mode !== 'manual') { setTimeout(() => dom.axeScanCidr?.focus(), 60); }
    if (step === 3) { setTimeout(() => dom.axeAddName?.focus(), 60); }
  }

  function setAxeWizMode(mode) {
    _axeWizState.mode = mode === 'manual' ? 'manual' : 'scan';
    gotoAxeWizStep(2);
  }

  function resetAxeWizard() {
    clearTimeout(_axeDetectTimer);
    _axeDetectTimer = null;
    _axeWizState.ip = '';
    _axeWizState.name = '';
    _axeWizState.device = null;
    _axeWizState._detectedProtocol = '';
    _axeWizState._detectedFirmware = '';
    _axeWizState._detectedModel = '';
    _axeWizState._detectedVersion = '';
    if (dom.axeTestResult) dom.axeTestResult.innerHTML = '';
    if (dom.axeManualNameRow) dom.axeManualNameRow.style.display = 'none';
    if (dom.axeWizConfirm) dom.axeWizConfirm.innerHTML = '';
    if (dom.axeScanResults) dom.axeScanResults.innerHTML = '';
    if (dom.axeScanStatus) dom.axeScanStatus.textContent = '';
    if (dom.axeAddStatus) dom.axeAddStatus.textContent = '';
    const fwPreview = document.getElementById('axe-fw-preview');
    if (fwPreview) { fwPreview.innerHTML = ''; fwPreview.style.display = 'none'; }
  }

  // Render the detected device summary in the confirm step.
  function renderAxeConfirm() {
    const box = dom.axeWizConfirm;
    if (!box) return;
    const d = _axeWizState.device || {};
    const proto = d.protocol || _axeWizState._detectedProtocol || (_axeWizState.mode === 'manual' ? 'manual' : '');
    const fwLabel = _axeWizState._detectedFirmware || d.firmware || '';
    const fwVersion = d.version || _axeWizState._detectedVersion || '';
    const fwStr = [fwLabel, fwVersion].filter(Boolean).join(' ');
    const rows = [
      ['IP', _axeWizState.ip],
      ['protocol', proto ? proto.toUpperCase() : '—'],
      ['model', d.model || _axeWizState._detectedModel || '—'],
      ['hostname', d.hostname || '—'],
      ['firmware', fwStr || '—'],
      ['hashrate', d.hashrate_hs ? fmt.hashrate(d.hashrate_hs) : '—'],
    ].map(([k, v]) => `<div style="display:flex;gap:6px"><span style="color:var(--text-tertiary);min-width:64px">${k}</span><span style="color:var(--text-primary)">${escapeHtml(String(v))}</span></div>`).join('');
    box.innerHTML = `<div class="axe-wiz__confirm-title">✓ ready to add</div>${rows}`;
  }

  function initAxeFleetControls() {
    // ── Scan Network button ──────────────────────────────────────
    const scanBtn = dom.axeFleetScan || document.getElementById('axe-fleet-scan');
    if (scanBtn) {
      scanBtn.addEventListener('click', function() { scanNetwork(); });
    }

    const addBtn = dom.axeFleetAdd || document.getElementById('axe-fleet-add');
    const form = dom.axeAddForm || document.getElementById('axe-add-form');
    const cancelBtn = document.getElementById('axe-add-cancel');
    const saveBtn = document.getElementById('axe-add-save');
    const ipInput = document.getElementById('axe-add-ip');
    const nameInput = document.getElementById('axe-add-name');
    const statusEl = document.getElementById('axe-add-status');
    const emptyAdd = dom.axeEmptyAdd || document.getElementById('axe-empty-add');
    if (!addBtn || !form) return;

    const openWizard = () => {
      resetAxeWizard();
      form.style.display = 'block';
      gotoAxeWizStep(1);
    };

    addBtn.addEventListener('click', openWizard);
    emptyAdd?.addEventListener('click', openWizard);
    cancelBtn?.addEventListener('click', () => {
      form.style.display = 'none';
      resetAxeWizard();
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

    // Step 1 method cards
    form.querySelectorAll('[data-wiz-method]').forEach(m => {
      m.addEventListener('click', () => setAxeWizMode(m.getAttribute('data-wiz-method')));
    });
    // Back buttons (data-wiz-back="1|2")
    form.querySelectorAll('[data-wiz-back]').forEach(b => {
      b.addEventListener('click', () => gotoAxeWizStep(Number(b.getAttribute('data-wiz-back'))));
    });

    // Manual: test connectivity
    dom.axeTestConn?.addEventListener('click', testAxeConnectivity);
    ipInput?.addEventListener('keydown', e => {
      if (e.key === 'Enter') { e.preventDefault(); testAxeConnectivity(); }
    });

    // ── Auto-detect firmware on IP input (debounced preview) ─────────
    // While the operator types an IP, the diagnose endpoint is silently
    // called in the background (600ms debounce). The result is rendered
    // as a live firmware preview chip so the operator sees the detected
    // firmware/model/protocol BEFORE clicking "TEST CONNECTIVITY" or
    // registering. This turns a blind IP type-in into an informative
    // discovery flow.
    let _axeDetectTimer = null;
    const fwPreview = document.getElementById('axe-fw-preview');

    function _axeAutoDetect(ip) {
      if (!fwPreview) return;
      if (!ip || ip.trim().length < 7) {
        fwPreview.innerHTML = '';
        fwPreview.style.display = 'none';
        return;
      }
      fwPreview.style.display = 'flex';
      fwPreview.innerHTML = '<span class="axe-fw-preview__spinner"></span><span class="axe-fw-preview__text">detecting firmware…</span>';
    }

    async function _axeRunDetect(ip) {
      if (!ip || ip.trim().length < 7) return;
      try {
        // Use the lightweight /detect endpoint — faster than /diagnose
        // since it only calls detect_firmware() (no TCP port scan).
        // Response shape: {firmware, adapter_type, version, model, capabilities, reachable}
        const r = await authFetch('/api/axe-fleet/detect/' + encodeURIComponent(ip.trim()));
        const data = await r.json();
        // Populate the wizard state so confirm step has the data.
        // The /detect response is flat (no device_info wrapper), so
        // we map fields directly to the wizard state.
        _axeWizState.ip = ip.trim();
        _axeWizState._detectedProtocol = data && data.adapter_type;
        _axeWizState._detectedFirmware = data && data.firmware;
        _axeWizState._detectedModel = data && data.model;
        _axeWizState._detectedVersion = (data && data.version) || '';
        if (data && data.reachable) {
          _axeWizState.device = {
            model: data.model || '',
            firmware: data.firmware || '',
            version: data.version || '',
            protocol: data.adapter_type || '',
            hostname: '',
            hashrate_hs: 0,
          };
        }
        _axeRenderFwPreview(data);
      } catch (e) {
        if (fwPreview) {
          fwPreview.innerHTML = '';
          fwPreview.style.display = 'none';
        }
      }
    }

    function _axeRenderFwPreview(data) {
      if (!fwPreview) return;
      // /detect response is flat: {firmware, adapter_type, model, version, capabilities, reachable, error}
      const reachable = !!(data && data.reachable);
      const proto = (data && data.adapter_type) || '';
      const fw = (data && data.firmware) || '';
      const model = (data && data.model) || '';
      if (reachable && (proto || model || fw)) {
        const protoLabel = proto.toUpperCase();
        const protoCls = proto === 'bitaxe' ? 'axe-fw-preview__chip--bitaxe'
          : proto === 'braiins' ? 'axe-fw-preview__chip--braiins'
          : proto === 'cgminer' ? 'axe-fw-preview__chip--cgminer'
          : 'axe-fw-preview__chip--other';
        const parts = []
          .concat(protoLabel ? [`<span class="axe-fw-preview__chip ${protoCls}">${escapeHtml(protoLabel)}</span>`] : [])
          .concat(fw ? [`<span class="axe-fw-preview__text">${escapeHtml(fw)}</span>`] : [])
          .concat(model ? [`<span class="axe-fw-preview__text axe-fw-preview__text--muted">${escapeHtml(model)}</span>`] : [])
          .join('');
        fwPreview.innerHTML = `<span class="axe-fw-preview__icon">✓</span>${parts}`;
        fwPreview.style.display = 'flex';
      } else {
        // Unreachable — show the error from the detector
        const err = (data && data.error) || 'no miner detected on this IP';
        fwPreview.innerHTML = `<span class="axe-fw-preview__icon" style="color:var(--orange)">✗</span><span class="axe-fw-preview__text axe-fw-preview__text--muted">${escapeHtml(String(err).substring(0, 80))}</span>`;
        fwPreview.style.display = 'flex';
      }
    }

    ipInput?.addEventListener('input', () => {
      clearTimeout(_axeDetectTimer);
      const ip = (ipInput.value || '').trim();
      _axeAutoDetect(ip);
      if (ip.length >= 7) {
        _axeDetectTimer = setTimeout(() => _axeRunDetect(ip), 600);
      }
    });

    saveBtn?.addEventListener('click', async () => {
      const ip = (_axeWizState.ip || ipInput?.value || '').trim();
      if (!ip) { if (statusEl) { statusEl.textContent = '? enter IP address'; statusEl.style.color = 'var(--accent-red)'; } gotoAxeWizStep(1); return; }
      const name = (nameInput?.value || '').trim();
      if (statusEl) { statusEl.textContent = '> connecting...'; statusEl.style.color = 'var(--text-tertiary)'; }
      const ok = await addAxeDevice(ip, name);
      if (statusEl) {
        statusEl.textContent = ok ? '? added — refreshing...' : '? failed — see console';
        statusEl.style.color = ok ? 'var(--accent-green)' : 'var(--accent-red)';
      }
      if (ok) {
        setTimeout(() => {
          form.style.display = 'none';
          resetAxeWizard();
          if (ipInput) ipInput.value = '';
          if (nameInput) nameInput.value = '';
          if (statusEl) statusEl.textContent = '';
          fetchAxeFleet();
        }, 1500);
      }
    });

    initAxeScanControls();
    initAxeAgentPanel();
  }

  // ── SaaS AGENT onboarding panel ─────────────────────────────────────
  // The cloud dashboard cannot reach the user's LAN (192.168.x.x is not
  // routable from Render), so a local agent connects OUT and pushes
  // telemetry. This panel mints the per-tenant JWT (POST /api/agent/token)
  // and prints the docker run one-liner for the user's home network.
  function initAxeAgentPanel() {
    const panel = document.getElementById('axe-agent-panel');
    const btn = document.getElementById('axe-agent-btn');
    if (!panel || !btn) return;

    const open = () => {
      // Close the add-wizard if open so the two modals never overlap.
      const form = dom.axeAddForm || document.getElementById('axe-add-form');
      if (form && form.style.display !== 'none') form.style.display = 'none';
      panel.style.display = 'block';
    };
    const close = () => { panel.style.display = 'none'; };
    btn.addEventListener('click', open);
    document.getElementById('axe-agent-close')?.addEventListener('click', close);

    const statusEl = document.getElementById('axe-agent-status');
    const tokenRow = document.getElementById('axe-agent-token-row');
    const tokenArea = document.getElementById('axe-agent-token');
    const dockerPre = document.getElementById('axe-agent-docker');
    const oneLinerPre = document.getElementById('axe-agent-one-liner');
    const setStatus = (msg, color) => {
      if (!statusEl) return;
      statusEl.textContent = msg;
      statusEl.style.color = color || 'var(--text-tertiary)';
    };
    // One-line installer: SERVER_URL + token ride as leading env vars so the
    // piped `bash` process sees them (query-string vars would NOT reach the
    // script through `curl | bash`). Single command — no Docker, no pip.
    const renderCommands = (token, serverUrl) => {
      const origin = (serverUrl || location.origin).replace(/\/$/, '');
      if (oneLinerPre) {
        oneLinerPre.textContent =
          'curl -sSL "' + origin + '/agent/install.sh" \\\n' +
          '  | CYPHER65_SERVER_URL=' + origin + ' CYPHER65_AGENT_TOKEN=' + token + ' bash';
      }
      if (dockerPre) {
        dockerPre.textContent =
          'docker run -d --name cypher65-agent --network host \\\n' +
          '  -e CYPHER65_SERVER_URL=' + origin + ' \\n' +
          '  -e CYPHER65_AGENT_TOKEN=' + token + ' \\n' +
          '  -e CYPHER65_POLL_INTERVAL=30 \\n' +
          '  ghcr.io/0xjc65eth/cypher65-agent';
      }
    };
    const copy = async (text, label) => {
      try {
        await navigator.clipboard.writeText(text);
        setStatus('✓ ' + label + ' copied', 'var(--accent-green)');
      } catch (e) {
        setStatus('! copy failed — select manually', 'var(--accent-red)');
      }
    };

    document.getElementById('axe-agent-gen')?.addEventListener('click', async () => {
      setStatus('> minting token...');
      try {
        const r = await authFetch('/api/agent/token', { method: 'POST' });
        const data = await r.json();
        if (!r.ok || !data.token) {
          setStatus('✗ ' + (data.error || 'token mint failed (HTTP ' + r.status + ')'), 'var(--accent-red)');
          return;
        }
        if (tokenArea) tokenArea.value = data.token;
        renderCommands(data.token, data.server_url || '');
        if (tokenRow) tokenRow.style.display = 'block';
        setStatus('✓ token issued · tenant ' + (data.tenant_id || ''), 'var(--accent-green)');
      } catch (e) {
        setStatus('✗ network error', 'var(--accent-red)');
      }
    });
    document.getElementById('axe-agent-copy-token')?.addEventListener('click', () => {
      if (tokenArea && tokenArea.value) copy(tokenArea.value, 'token');
    });
    document.getElementById('axe-agent-copy-one')?.addEventListener('click', () => {
      if (oneLinerPre && oneLinerPre.textContent) copy(oneLinerPre.textContent, 'install command');
    });
    document.getElementById('axe-agent-copy-docker')?.addEventListener('click', () => {
      if (dockerPre && dockerPre.textContent) copy(dockerPre.textContent, 'docker command');
    });
    document.getElementById('axe-agent-hide-token')?.addEventListener('click', () => {
      if (tokenArea) tokenArea.value = '';
      if (tokenRow) tokenRow.style.display = 'none';
      setStatus('token hidden');
    });
  }

  // Shared device-add helper (used by the manual form + scan ADD buttons).
  // Returns true on success.
  async function addAxeDevice(ip, name) {
    if (!ip) return false;
    try {
      const r = await authFetch('/api/axe-fleet/devices', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ip_address: ip, name: name || '' })
      });
      const data = await r.json();
      return r.ok;
    } catch (e) {
      return false;
    }
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
    initMatrix(); initCharts(); bindChartRanges(); loadSettings(); initMarketControls(); initDecisionMatrixControls(); initCommandCenterControls(); _initRentalsPanel();
    _initLmEventLogControls();
    initLicensing();  // R1: PRO badge + license state (off-by-default, no-op in open mode)
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
        navigator.serviceWorker.register('/sw.js', { scope: '/' }).then(reg => {
          console.log('[boot] new SW registered');
          // Web Push: subscribe after the SW is ready (never blocks boot).
          setTimeout(() => enablePush(reg), 1500);
        }).catch(e => {
          console.warn('[boot] SW registration failed:', e);
        });
      });
      // Web Push bootstrap — registers a per-tenant push subscription with the
      // server so mining alerts reach this browser even when the tab is closed.
      // Degrades silently: no VAPID key → no prompt; permission denied → no-op.
      async function enablePush(reg) {
        try {
          if (!('PushManager' in window)) return;
          if (!reg || typeof reg.pushManager !== 'object') return;
          // Only offer push when the server has VAPID configured.
          let vapidKey = null;
          try {
            const r = await fetch('/api/push/vapid-key');
            if (r.ok) vapidKey = (await r.json()).vapid_public_key || null;
          } catch (e) { /* offline / push unconfigured — skip silently */ }
          if (!vapidKey) return;
          const sub = await reg.pushManager.getSubscription();
          if (sub) return;  // already subscribed
          let permission = 'default';
          try { permission = await Notification.requestPermission(); } catch (e) {}
          if (permission !== 'granted') return;
          const newSub = await reg.pushManager.subscribe({
            userVisibleOnly: true,
            applicationServerKey: urlBase64ToUint8Array(vapidKey),
          });
          const raw = newSub.toJSON();
          // Issue #115: attach the Bearer token when present so the
          // subscription is stored under the CALLER's tenant (JWT sub is the
          // only authority for a non-empty tenant); anonymous visitors still
          // subscribe under the operator tenant with an https:// endpoint.
          const pushHeaders = { 'Content-Type': 'application/json' };
          const tok = (typeof authGetToken === 'function') ? authGetToken() : '';
          if (tok) pushHeaders['Authorization'] = 'Bearer ' + tok;
          const subRes = await fetch('/api/push/subscribe', {
            method: 'POST',
            headers: pushHeaders,
            body: JSON.stringify({ endpoint: raw.endpoint, keys: raw.keys }),
          });
          if (!subRes.ok) {
            // 401 = token revoked/invalid, 429 = per-IP budget hit, … —
            // surface it instead of pretending push is armed. Never retry
            // WITHOUT the token (that would defeat the Issue #115 boundary).
            console.warn('[push] subscribe rejected (' + subRes.status + ') — push not armed');
            return;
          }
          console.log('[push] subscribed for mining alerts');
        } catch (e) {
          console.warn('[push] enable failed (silent):', e && e.message);
        }
      }
      // VAPID applicationServerKey expects a Uint8Array.
      function urlBase64ToUint8Array(base64String) {
        const padding = '='.repeat((4 - (base64String.length % 4)) % 4);
        const base64 = (base64String + padding).replace(/-/g, '+').replace(/_/g, '/');
        const rawData = atob(base64);
        const output = new Uint8Array(rawData.length);
        for (let i = 0; i < rawData.length; ++i) output[i] = rawData.charCodeAt(i);
        return output;
      }
      // Listen for updates and reload when a new SW takes over
      navigator.serviceWorker.addEventListener('controllerchange', () => {
        console.log('[boot] new SW activated — reloading');
        window.location.reload();
      });
    }

    showSkeletons();
    initFleetCommandCenterControls();
    initAxeFleetControls();
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
  let acState = { active: [], history: [], rules: [], executions: [] };
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
      <div class="ac-item ac-item--${escapeHtml((a.severity || 'INFO').toLowerCase())}">
        <div class="ac-item__meta">
          <span class="ac-item__sev ${severityClass[a.severity] || ''}">${escapeHtml(severityLabel[a.severity] || a.severity)}</span>
          <span class="ac-item__cat">${escapeHtml(a.category)}</span>
          <span class="ac-item__ts">${acFormatTime(a.ts)}</span>
        </div>
        <div class="ac-item__msg">${escapeHtml(a.message)}</div>
        <div class="ac-item__actions">
          <button class="btn btn--mini ac-ack" data-id="${escapeHtml(a.id)}">Acknowledge</button>
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
          <span class="ac-item__sev ${severityClass[h.severity] || ''}">${escapeHtml(severityLabel[h.severity] || h.severity)}</span>
          <span class="ac-item__cat">${escapeHtml(h.alert_type)}</span>
          <span class="ac-item__ts">${acFormatTime(h.ts)}</span>
        </div>
        <div class="ac-item__msg">${escapeHtml(h.action_taken || h.message)}</div>
      </div>
    `).join('');
  }

  function acExecStatusClass(status) {
    const s = String(status || 'ok').toLowerCase();
    if (s.indexOf('ok') === 0 || s.indexOf('succ') === 0 || s === '') return 'severity--success';
    if (s.indexOf('fail') !== -1 || s.indexOf('error') !== -1 || s.indexOf('block') !== -1) return 'severity--crit';
    return '';
  }

  function acRenderExecutions() {
    const list = dom.acExecList;
    if (!list) return;
    if (!acState.executions.length) {
      list.innerHTML = '<span class="ac-empty" style="color:var(--text-muted)">no executions yet — crie uma regra e aguarde o próximo ciclo de polling</span>';
      return;
    }
    list.innerHTML = acState.executions.slice(0, 6).map(x => {
      const cls = acExecStatusClass(x.status);
      return `<div style="display:flex;gap:6px;align-items:center;padding:1px 0">` +
        `<span class="ac-item__sev ${cls}" style="font-size:8px">${escapeHtml(x.status || 'OK')}</span>` +
        `<span style="color:var(--text-muted)">${acFormatTime(x.ts)}</span>` +
        `<span style="color:var(--text-secondary);flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${escapeHtml(x.rule_name || ('rule #' + (x.rule_id || '?')))} → ${escapeHtml(x.action_command || '?')}</span>` +
        `${x.reason ? `<span style="color:var(--text-tertiary)" title="${escapeHtml(x.reason)}">${escapeHtml(x.reason).slice(0, 28)}</span>` : ''}` +
        `</div>`;
    }).join('');
  }

  function acRenderRules() {
    if (!dom.acRulesList) return;
    if (!acState.rules.length) {
      dom.acRulesList.innerHTML = '<div class="ac-empty">no automation rules</div>';
      return;
    }
    const lastRun = {};
    acState.executions.forEach(function(x) {
      if (!lastRun[x.rule_id] || x.ts > lastRun[x.rule_id].ts) lastRun[x.rule_id] = x;
    });
    dom.acRulesList.innerHTML = acState.rules.map(r => {
      const lr = lastRun[r.id];
      const runLine = lr
        ? `<span class="ac-item__run ${acExecStatusClass(lr.status)}">última: ${acFormatTime(lr.ts)} — ${escapeHtml(lr.status || 'OK')}${lr.reason ? ' (' + escapeHtml(lr.reason) + ')' : ''}</span>`
        : '<span class="ac-item__run" style="color:var(--text-tertiary)">nunca executou</span>';
      return `
      <div class="ac-item ac-item--rule">
        <div class="ac-item__meta">
          <span class="ac-item__sev">${r.is_enabled ? 'ON' : 'OFF'}</span>
          <span class="ac-item__cat">${escapeHtml(r.name)}</span>
        </div>
        <div class="ac-item__msg">WHEN ${escapeHtml(r.condition_metric)} ${escapeHtml(r.condition_operator)} ${escapeHtml(r.condition_value)} THEN ${escapeHtml(r.action_command)}</div>
        <div class="ac-item__actions">${runLine}<button class="btn btn--danger btn--mini ac-rule-del" data-id="${escapeHtml(r.id)}">Delete</button></div>
      </div>
    `;
    }).join('');
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
    } catch (e) { acSetStatus('Load rules failed: ' + e.message, true); }
    try {
      acState.executions = (await acFetchJson('/api/automation-executions?limit=50')).executions || [];
    } catch (e) { /* execution log is best-effort */ }
    acRenderRules();
    acRenderExecutions();
  }

  function acShowTab(tab) {
    dom.acTabs.forEach(t => t.classList.toggle('active', t.dataset.tab === tab));
    // Panes are id'd `ac-<tab>-pane` (ac-active-pane / ac-history-pane /
    // ac-rules-pane) and shown via the CSS rule `.ac-pane.active`. The old
    // code compared against `ac-pane-<tab>` — a shape that doesn't exist —
    // so NO pane ever matched and every pane stayed hidden (second bug found
    // by the visual audit; the Rules/History panes were reachable in the DOM
    // but never visible even with the tab strip injected).
    dom.acPanes.forEach(p => p.classList.toggle('active', p.id === 'ac-' + tab + '-pane'));
    if (tab === 'active') acLoadActive();
    if (tab === 'history') acLoadHistory();
    if (tab === 'rules') acLoadRules();
  }

  if (dom.openAlertCenter) {
    // Render the Alert Center tab buttons (Active / History / Rules). The
    // #ac-tabs container ships EMPTY in the template and nothing ever
    // injected the buttons — a pre-existing bug found by the browser visual
    // audit: the History and Rules panes (incl. automation rules + execution
    // log) were unreachable from the UI. The panes exist in the DOM; only
    // the tab strip was missing.
    const acTabsHost = document.getElementById('ac-tabs');
    if (acTabsHost && !acTabsHost.children.length) {
      acTabsHost.innerHTML =
        '<button type="button" class="chip ac-tab active" data-tab="active">Active</button>' +
        '<button type="button" class="chip ac-tab" data-tab="history">History</button>' +
        '<button type="button" class="chip ac-tab" data-tab="rules">Rules</button>';
      dom.acTabs = acTabsHost.querySelectorAll('.ac-tab');
    }
    dom.openAlertCenter.addEventListener('click', () => {
      openModalAnimated(dom.alertCenterModal);
      acShowTab('active');
    });
    dom.alertCenterModal?.querySelectorAll('[data-close]').forEach(el => {
      el.addEventListener('click', () => closeModalAnimated(dom.alertCenterModal));
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
    'rentals':     { title: 'RENTALS',       desc: 'Performance dos aluguéis (MRR + Braiins)' },
    'alerts':      { title: 'ALERTS',        desc: 'Alertas e eventos' },
    'automations': { title: 'AUTOMATIONS',   desc: 'Regras e automação' },
    'docs':        { title: 'DOCS / GUIDE',  desc: 'Manual de uso' },
    'learning':    { title: 'LEARNING',      desc: 'Bitcoin Academy — whitepaper, livros e Ordinals' },
    'support':     { title: 'SUPPORT',       desc: 'Doação e apoio' },
    'admin':       { title: 'ADMIN · CFO',   desc: 'Operador: pool health + funil PRO + LTV/CAC' },
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
  // Helper puro (espelhado em tests/test_app_js_core.js): decide quais
  // abas (tab-panes) ficam ativas para um módulo. Cada módulo tem UMA aba
  // dona — sem esse mapeamento, painéis do mesmo módulo espalhados por
  // várias abas (ex.: LIVE MINING — painel principal em tab-charts,
  // terminal em tab-terminal, timeline/gráficos/logs em tab-fleet)
  // ativavam VÁRIAS abas ao mesmo tempo: página gigante com scroll
  // infinito + overflow horizontal no mobile. Módulos fora do mapa
  // mantêm o comportamento antigo (ativa TODAS as abas com painel
  // visível — a 1ª que aparecer também, sem exclusividade).
  const _MODULE_OWNED_PANES = {
    // LIVE MINING: só o painel principal (CYPHER // LIVE MINING) + o
    // terminal de comandos. Timeline/gráficos ficam fora do módulo para o
    // layout voltar a ser focado (sem scroll infinito). O LIVE LOG (#logs-
    // panel, data-module="live") vive DENTRO de #tab-terminal — painel de
    // mesmo módulo — para ficar visível aqui (era inalcançável em #tab-fleet).
    live: ['tab-charts', 'tab-terminal'],
  };
  function moduleActivePanes(name, paneHasVisible) {
    const owned = _MODULE_OWNED_PANES[name];
    if (owned) return owned.slice();
    return (paneHasVisible || []).filter(p => p.visible).map(p => p.id);
  }
  // Module navigation with exit/enter motion (design-motion-principles).
  // Exit (120ms) plays BEFORE the switch so display:none doesn't kill it;
  // the switch is deferred by the same amount and token-guarded so rapid
  // sidebar clicks cancel the pending transition (Emil: interruptible).
  let _moduleNavToken = 0;
  function activateModule(name) {
    document.body.classList.add('module-mode');
    const reduceMotion = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    const token = ++_moduleNavToken;
    if (!reduceMotion) {
      let leavingCount = 0;
      document.querySelectorAll('[data-module].panel, [data-module].kpi-row').forEach(function(el) {
        if (el.classList.contains('sidebar__link')) return;
        const mods = (el.getAttribute('data-module') || '').split(/\s+/);
        if (mods.indexOf(name) === -1 && !el.classList.contains('module-hidden')) {
          el.classList.add('module-leave');
          leavingCount++;
        }
      });
      if (leavingCount > 0) {
        setTimeout(function() {
          if (token !== _moduleNavToken) return;  // superseded by a newer click
          _doActivateModule(name, reduceMotion);
        }, 120);
        return;
      }
    }
    _doActivateModule(name, reduceMotion);
  }
  function _doActivateModule(name, reduceMotion) {
    // Mostra/esconde cada painel com data-module — MAS nunca os links da
    // sidebar (eles também têm data-module; escondê-los quebraria a navegação)
    document.querySelectorAll('[data-module]').forEach(function(el) {
      // Links da sidebar nunca são escondidos (senão a navegação quebra)
      if (el.classList.contains('sidebar__link')) return;
      const mods = (el.getAttribute('data-module') || '').split(/\s+/);
      const show = mods.indexOf(name) !== -1;
      el.classList.toggle('module-hidden', !show);
      if (show) el.classList.remove('module-leave');
    });
    // Tab panes: apenas as abas que o módulo possui (ou, fora do mapa,
    // as que contêm painel visível) ficam ativas — nunca várias ao mesmo
    // tempo (causa do scroll infinito / overflow no Live Mining).
    const paneStates = Array.prototype.map.call(
      document.querySelectorAll('.tab-pane'),
      function(pane) {
        return {
          id: pane.id,
          visible: !!pane.querySelector('[data-module]:not(.module-hidden)'),
          el: pane,
        };
      }
    );
    const activeIds = moduleActivePanes(name, paneStates);
    paneStates.forEach(function(p) {
      p.el.classList.toggle('active', activeIds.indexOf(p.id) !== -1);
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
      // Motion: staggered enter for the panels that just became visible
      // (opacity + translateY + blur, 200ms, 24ms stagger — Emil <300ms).
      if (!reduceMotion) {
        let idx = 0;
        document.querySelectorAll('[data-module].panel:not(.module-hidden), [data-module].kpi-row:not(.module-hidden)').forEach(function(el) {
          el.classList.remove('module-in');
          void el.offsetWidth; // restart animation on rapid re-triggers
          el.style.setProperty('--i', String(idx++));
          el.classList.add('module-in');
          setTimeout(function() { el.classList.remove('module-in'); }, 500);
        });
      }
      Object.keys(charts).forEach(function(id) {
        const ch = charts[id];
        if (ch && typeof ch.resize === 'function') ch.resize();
      });
      if (typeof renderCharts === 'function') renderCharts();
      // Hash Market: lazy-load the 7d trend chart on first module activation.
      // On failure the flag is reset so the next activation retries.
      if (name === 'market' && !_mktTrendLoaded) {
        _mktTrendLoaded = true;
        skelShow(document.getElementById('market-panel'), 'chart');
        loadMarketTrend().then(ok => {
          skelHide(document.getElementById('market-panel'));
          if (!ok) _mktTrendLoaded = false;
        });
      }
      // Rentals: lazy-load the operator rental list on first module activation.
      if (name === 'rentals' && !_rentalsLoaded) {
        _rentalsLoaded = true;
        skelShow(document.getElementById('rentals-panel'), 'table');
        loadRentals().then(ok => {
          skelHide(document.getElementById('rentals-panel'));
          if (!ok) _rentalsLoaded = false;
        });
      }
      // Hash Market: also refresh the snapshot — the boot-time snapshot can be
      // stale (fetched before the warmup cache is hot), so the grid would open
      // with 0 offers until the next 15s poll. Same pattern as the fleet fix.
      if (name === 'admin' && typeof fetchAdminData === 'function') {
        fetchAdminData();
      }
      if (name === 'market' && typeof fetchSnapshot === 'function') {
        // Re-activation with an EMPTY grid (e.g. offers never landed): show
        // the same table skeleton until the fresh snapshot renders offers.
        const mktPanel = document.getElementById('market-panel');
        const gridEmpty = !_mktOffers || _mktOffers.length === 0;
        if (mktPanel && gridEmpty) skelShow(mktPanel, 'table');
        Promise.resolve(fetchSnapshot()).then(() => { skelHide(mktPanel); });
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
        const fleetPanel = document.getElementById('axe-fleet-panel');
        // Only skeleton when the grid is empty (first activation or a
        // previous fetch failed) — with devices already rendered a refresh
        // keeps them visible and skips the overlay (no flash).
        // #axe-grid starts with a static empty-state in the template, so
        // count only real device cards — with cards rendered the refresh
        // keeps them visible (no overlay flash).
        const fleetEmpty = !dom.axeGrid || !dom.axeGrid.querySelector('.axe-card, .device-card, [data-device-id]');
        if (fleetPanel && fleetEmpty) skelShow(fleetPanel, 'table');
        const _fleetP = Promise.resolve(fetchAxeFleet());
        if (typeof fetchRemoteOnboarding === 'function') fetchRemoteOnboarding();
        _fleetP.then(() => { skelHide(fleetPanel); });
      }
      // Support: abre o modal completo (manifesto + endereços) em vez de só
      // rolar até a barra compacta — o texto autoral e os endereços grandes
      // ficam no modal.
      if (name === 'support') {
        const panel = document.getElementById('support-panel');
        if (panel) {
          openModalAnimated(panel);
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

  // UX audit (Quick Win): KPI cards are drill-down shortcuts to modules.
  // Clicking Total HR → Live Mining, Best Diff → Probability (Block Hunt),
  // etc. Uses event delegation so the (re-rendered) cards stay bound.
  const kpiRow = document.getElementById('kpi-row');
  if (kpiRow) {
    kpiRow.addEventListener('click', function(e) {
      const card = e.target.closest('.kpi-card[data-kpi-target]');
      if (!card) return;
      activateModule(card.getAttribute('data-kpi-target'));
    });
  }

  // P0-1: CTA do histograma de Share Difficulty → Probability (solo stats).
  // Live Mining alimenta a previsão — um clique leva ao cálculo já carregado.
  const shareDistGotoProb = document.getElementById('share-dist-goto-prob');
  if (shareDistGotoProb) {
    shareDistGotoProb.addEventListener('click', function() {
      activateModule('probability');
      const solo = document.getElementById('solo-stats-panel');
      if (solo) solo.scrollIntoView({ behavior: 'smooth', block: 'start' });
    });
  }

  // UX audit (Módulo_05): WHAT-IF difficulty slider — simulate the impact of
  // a network difficulty change on P(block)/share, expected time, distance
  // and cumulative P. Pure simulation, never mutates the live snapshot.
  const bhSlider = document.getElementById('bh-whatif-slider');
  if (bhSlider) {
    bhSlider.addEventListener('input', _bhRenderWhatIf);
    const bhReset = document.getElementById('bh-whatif-reset');
    if (bhReset) {
      bhReset.addEventListener('click', function() {
        bhSlider.value = 0;
        _bhRenderWhatIf();
      });
    }
  }

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


  // ── Wallet-refresh gate (pure, mirrored in tests) ──
  // A snapshot is "fresh for the new wallet" when it carries the new address
  // AND has been re-polled (ts > 0). /api/set-address resets the snapshot
  // (ts=0) and forces a background poll; a brand-new wallet legitimately has
  // worker=null (pool returns 0 — a valid response, not an error), so ts is
  // the reliable "poll landed" signal — not worker presence.
  function snapshotFreshForWallet(snap, address) {
    return !!(snap &&
      String(snap.btc_address || '').toLowerCase() === String(address || '').toLowerCase() &&
      snap.ts > 0);
  }

  // ── HOTFIX v2: deterministic refresh after wallet connect ──
  // A fixed-delay fetch (1.2s) can race a slow pool API and render the
  // still-empty snapshot (ts=0), leaving the dashboard blank until the next
  // poll. The forced poll (set-address → poll_once) runs many external
  // fetches and only stamps ts at the END, so it can take 10-30s. Retry
  // every 1.5s for up to ~30s until the snapshot carries the new address
  // AND ts>0, so the dashboard lights up the moment real data lands. Give
  // up after the budget and render whatever exists — honest: the wallet IS
  // connected; data will arrive on the next scheduled poll.
  //
  // Generation guard: _walletRefreshTarget holds the LATEST wallet the user
  // asked to refresh. A retry chain that started for an older wallet stops
  // silently on its next tick (rapid A→B switching must never let the A
  // chain render B's data or a stale reset state). Only the newest chain
  // renders.
  var _walletRefreshTarget = '';
  function refreshUntilWalletReady(address, attempt) {
    _walletRefreshTarget = address;
    attempt = attempt || 0;
    fetch('/api/snapshot')
      .then(function(r) { return r.json(); })
      .then(function(snap) {
        // A newer wallet was connected — this chain is obsolete, stop now.
        if (address !== _walletRefreshTarget) return;
        if (snapshotFreshForWallet(snap, address)) {
          render(snap);
          return;
        }
        if (attempt < 20) {
          setTimeout(function() { refreshUntilWalletReady(address, attempt + 1); }, 1500);
        } else if (snap) {
          render(snap);
        }
      })
      .catch(function(err) { console.warn('[wallet-changed] refresh error:', err); });
  }

  window.addEventListener('wallet-changed', function(e) {
    var addr = e.detail && e.detail.address;
    if (addr) refreshUntilWalletReady(addr);
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
      // Issue #51 (audit): do NOT setText on #hero-worker — that id is the
      // WHOLE panel section, so el.textContent wipes every child metric
      // (m-hashrate, m-state, hc-*, hero grid). The hero values are owned by
      // renderHero()/renderHostCore() (called by the original render).
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
      // The whole ACCOUNT block (ln address, total diff, COMBINED / DIFF /
      // LOYALTY ranks) is owned by renderAccount() — it applies the C3
      // fallback labels (TOP X% / ACTIVE) and formats with the shared em-dash.
      // Stomping any of those fields here with '--' both hid the fallbacks
      // (P0-5 audit) and rendered a different dash style. This pass only
      // touches the leaderboard table, which no other renderer writes.

      var lbBody = document.getElementById('lb-tbody');
      if (lbBody && leaderboard && leaderboard.length) {
        lbBody.innerHTML = leaderboard.slice(0, 10).map(function(row, i) {
          return '<tr><td>' + (i + 1) + '</td><td>' + (row.address ? escapeHtml(row.address.substring(0, 10)) + '...' : '--') + '</td><td>' + escapeHtml(row.diff_rank || '--') + '</td><td>' + escapeHtml(row.loyalty_rank || '--') + '</td><td>' + escapeHtml(row.combined_score || '--') + '</td><td>' + escapeHtml(row.total_blocks || 0) + '</td></tr>';
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

      // Also bind off-canvas-ai panel — a DEDICATED trigger (#ai-panel-toggle),
      // never the #sidebar-toggle: reusing the sidebar button made the
      // off-canvas panel (z-index 500) cover the ☰ button when both opened,
      // so the second click never reached the sidebar toggle and the sidebar
      // stayed stuck open (E2E topbar-responsive caught it). The AI panel
      // keeps its own close button and outside-click dismiss.
      var toggleBtn = document.getElementById('ai-panel-toggle');
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

    // NOTE (dom-scope fix): the main IIFE opened at the top of this file must
    // close at the very END of the file. Previously a stray `})();` here closed
    // the IIFE early, pushing renderKpiCards() and everything below into GLOBAL
    // scope where `dom` (a const inside the IIFE) does not exist — every render
    // threw "ReferenceError: dom is not defined" (throttled to ~5/min in the
    // LIVE LOG). The IIFE now continues to the file's last line.

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

  // ── Docs: Search / filter + AUTOCOMPLETE (UX audit · Módulo_09) ──
  // Pure helpers below (docsBuildIndex/docsSearchSuggestions/docsSnippet/
  // docsHighlight) are mirrored in tests/test_app_js_core.js (SUITE 34).
  var _docsIndex = [];       // built once from the .docs-container sections
  var _docsSuggestions = []; // current autocomplete results
  var _docsActive = -1;      // keyboard cursor into _docsSuggestions

  // Build the search index from the docs container (scoped — the LEARNING
  // panel reuses .doc-section markup and must NOT pollute the docs index).
  function docsBuildIndex() {
    var container = document.querySelector('.docs-container');
    if (!container) return [];
    var sections = container.querySelectorAll('.doc-section');
    var idx = [];
    sections.forEach(function(sec) {
      var titleEl = sec.querySelector('.doc-section__title');
      idx.push({
        id: sec.id || '',
        title: titleEl ? titleEl.textContent.trim() : '',
        text: (sec.textContent || '').trim(),
      });
    });
    return idx;
  }

  // Pure: rank sections by query relevance. Title hits rank far above body
  // hits; earlier positions beat later ones. Returns up to `limit` entries
  // as {id, title, snippet} where snippet is a text window around the hit.
  function docsSearchSuggestions(index, q, limit) {
    limit = limit || 6;
    q = String(q || '').trim().toLowerCase();
    if (!q || !index.length) return [];
    var scored = [];
    index.forEach(function(sec) {
      var titleLow = (sec.title || '').toLowerCase();
      var textLow = (sec.text || '').toLowerCase();
      var titleIdx = titleLow.indexOf(q);
      var textIdx = textLow.indexOf(q);
      if (titleIdx === -1 && textIdx === -1) return;
      var score = titleIdx !== -1 ? 100 - titleIdx : 40 - Math.min(textIdx, 40);
      scored.push({ sec: sec, score: score, titleIdx: titleIdx, textIdx: textIdx });
    });
    scored.sort(function(a, b) { return b.score - a.score; });
    return scored.slice(0, limit).map(function(item) {
      var pos = item.titleIdx !== -1 ? Math.max(0, item.titleIdx) : Math.max(0, item.textIdx);
      return {
        id: item.sec.id,
        title: item.sec.title,
        snippet: docsSnippet(item.sec.text, q, pos),
      };
    });
  }

  // Pure: a text window of ±radius chars around `pos`, collapsing whitespace.
  function docsSnippet(text, q, pos, radius) {
    radius = radius || 60;
    var t = String(text || '').replace(/\s+/g, ' ');
    q = String(q || '');
    var start = Math.max(0, pos - radius);
    var end = Math.min(t.length, pos + q.length + radius);
    var snippet = t.slice(start, end);
    if (start > 0) snippet = '\u2026' + snippet;
    if (end < t.length) snippet = snippet + '\u2026';
    return snippet;
  }

  // Pure: escape text and wrap every case-insensitive occurrence of `q` in
  // <mark> for visual highlight inside the suggestion item.
  function docsHighlight(text, q) {
    var t = String(text || '');
    var needle = String(q || '').trim();
    if (!needle) return escapeHtml(t);
    var lower = t.toLowerCase();
    var nl = needle.toLowerCase();
    var out = '';
    var i = 0;
    while (i < t.length) {
      var hit = lower.indexOf(nl, i);
      if (hit === -1) { out += escapeHtml(t.slice(i)); break; }
      out += escapeHtml(t.slice(i, hit));
      out += '<mark>' + escapeHtml(t.slice(hit, hit + needle.length)) + '</mark>';
      i = hit + needle.length;
    }
    return out;
  }

  // ── Learning FAQ loop (Issue #19) — 'was this helpful?' widget ───────
  // Pure helpers below (docsFeedbackPct/docsFeedbackSectionLabel) are
  // mirrored in tests/test_app_js_core.js (SUITE 35).
  function docsFeedbackPct(helpful, total) {
    if (!total) return null;  // honest — no votes, no fabricated %
    return Math.round(helpful / total * 1000) / 10;
  }
  function docsFeedbackSectionLabel(sectionId) {
    const m = String(sectionId || '').match(/^docs[-_](.+)$/);
    return m ? m[1].replace(/[-_]/g, ' ') : String(sectionId || '—');
  }

  var _docsFeedbackState = {};      // section_id -> {helpful, voted}
  var _docsFeedbackInitialized = false;

  function _initDocsFeedback() {
    if (_docsFeedbackInitialized) return;
    const container = document.querySelector('.docs-container');
    if (!container) return;
    const sections = container.querySelectorAll('.doc-section');
    if (!sections.length) return;
    _docsFeedbackInitialized = true;

    sections.forEach(function(sec) {
      const id = sec.id;
      if (!id || sec.querySelector('.doc-feedback')) return;
      const widget = document.createElement('div');
      widget.className = 'doc-feedback';
      widget.setAttribute('data-section', id);
      widget.innerHTML =
        '<span class="doc-feedback__ask">Was this section helpful?</span>' +
        '<button type="button" class="doc-feedback__btn doc-feedback__btn--yes" data-helpful="1" title="Yes — it helped">👍 Yes</button>' +
        '<button type="button" class="doc-feedback__btn doc-feedback__btn--no" data-helpful="0" title="No — could be better">👎 No</button>' +
        '<span class="doc-feedback__state" aria-live="polite"></span>' +
        '<div class="doc-feedback__comment" hidden>' +
        '  <textarea class="doc-feedback__textarea" rows="2" maxlength="500" placeholder="What were you looking for? (feeds the FAQ loop)"></textarea>' +
        '  <button type="button" class="doc-feedback__send">Send</button>' +
        '</div>';
      sec.appendChild(widget);
      _bindDocFeedbackWidget(widget, id);
    });

    // Restore the current tenant's votes so thumbs stay across module switches.
    authFetch('/api/docs/feedback').then(function(r) {
      if (!r.ok) return;
      return r.json();
    }).then(function(data) {
      (data && data.votes || []).forEach(function(v) {
        if (!v || !v.section_id) return;
        // The GET was issued before any POST — skip sections the user already
        // voted on locally so a stale restore never reverts a fresh vote.
        if (_docsFeedbackState[v.section_id]) return;
        _docsFeedbackState[v.section_id] = { helpful: !!v.helpful, voted: true };
        const w = container.querySelector('.doc-feedback[data-section="' + v.section_id + '"]');
        if (w) _docsFeedbackSetState(w, v.section_id, !!v.helpful, '');
      });
    }).catch(function() { /* offline — votes stay local */ });
  }

  function _bindDocFeedbackWidget(widget, sectionId) {
    const yesBtn = widget.querySelector('.doc-feedback__btn--yes');
    const noBtn = widget.querySelector('.doc-feedback__btn--no');
    const commentWrap = widget.querySelector('.doc-feedback__comment');
    const textarea = widget.querySelector('.doc-feedback__textarea');
    const sendBtn = widget.querySelector('.doc-feedback__send');

    yesBtn.addEventListener('click', function() {
      if (_docsFeedbackState[sectionId] && _docsFeedbackState[sectionId].voted) return;
      commentWrap.hidden = true;
      _docsFeedbackVote(sectionId, true, widget, '');
    });
    noBtn.addEventListener('click', function() {
      if (_docsFeedbackState[sectionId] && _docsFeedbackState[sectionId].voted) return;
      commentWrap.hidden = false;
      textarea.focus();
    });
    sendBtn.addEventListener('click', function() {
      if (_docsFeedbackState[sectionId] && _docsFeedbackState[sectionId].voted) return;
      const comment = textarea.value.trim();
      _docsFeedbackVote(sectionId, false, widget, comment);
    });
  }

  function _docsFeedbackVote(sectionId, helpful, widget, comment) {
    const stateEl = widget.querySelector('.doc-feedback__state');
    authFetch('/api/docs/feedback', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ section_id: sectionId, helpful: helpful, comment: comment })
    }).then(function(r) {
      if (!r.ok) { stateEl.textContent = 'could not save — try again'; return; }
      _docsFeedbackState[sectionId] = { helpful: helpful, voted: true };
      _docsFeedbackSetState(widget, sectionId, helpful, comment);
    }).catch(function() {
      stateEl.textContent = 'offline — not saved';
    });
  }

  function _docsFeedbackSetState(widget, sectionId, helpful, comment) {
    const yesBtn = widget.querySelector('.doc-feedback__btn--yes');
    const noBtn = widget.querySelector('.doc-feedback__btn--no');
    const stateEl = widget.querySelector('.doc-feedback__state');
    const commentWrap = widget.querySelector('.doc-feedback__comment');
    yesBtn.classList.toggle('is-active', !!helpful);
    noBtn.classList.toggle('is-active', !helpful);
    yesBtn.disabled = true;
    noBtn.disabled = true;
    stateEl.textContent = helpful
      ? 'Thanks — glad it helped ✓'
      : (comment ? 'Thanks — we\'ll improve this section' : 'Thanks — feedback recorded');
    commentWrap.hidden = true;
  }

  function _docsCloseSuggestions() {
    var box = document.getElementById('docs-search-suggestions');
    var input = document.getElementById('docs-search-input');
    if (box) { box.innerHTML = ''; box.classList.remove('open'); }
    if (input) input.setAttribute('aria-expanded', 'false');
    _docsSuggestions = [];
    _docsActive = -1;
  }

  function _docsGoTo(id) {
    var el = document.getElementById(id);
    if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' });
    var links = document.querySelectorAll('.docs-index__link');
    links.forEach(function(link) {
      link.classList.toggle('docs-index__link--active', link.getAttribute('data-section') === id);
    });
    _docsCloseSuggestions();
  }

  // Render the autocomplete dropdown for the current query. Empty query or
  // no matches produce an honest empty state instead of stale suggestions.
  function _docsRenderSuggestions(q) {
    var box = document.getElementById('docs-search-suggestions');
    var input = document.getElementById('docs-search-input');
    if (!box || !input) return;
    if (!q) { _docsCloseSuggestions(); return; }
    _docsSuggestions = docsSearchSuggestions(_docsIndex, q, 6);
    if (!_docsSuggestions.length) {
      box.innerHTML = '<div class="docs-search__empty">no matches for \u201c' + escapeHtml(q) + '\u201d</div>';
      box.classList.add('open');
      input.setAttribute('aria-expanded', 'true');
      return;
    }
    box.innerHTML = _docsSuggestions.map(function(s, i) {
      return '<button type="button" class="docs-search__item' + (i === _docsActive ? ' active' : '') + '" data-docs-id="' + escapeHtml(s.id) + '" role="option" aria-selected="' + (i === _docsActive) + '">' +
        '<span class="docs-search__item-title">' + docsHighlight(s.title, q) + '</span>' +
        '<span class="docs-search__item-snippet">' + docsHighlight(s.snippet, q) + '</span>' +
        '</button>';
    }).join('');
    box.classList.add('open');
    input.setAttribute('aria-expanded', 'true');
  }

  function _initDocsSearch() {
    if (_docsSearchInitialized) return;
    var input = document.getElementById('docs-search-input');
    var clear = document.getElementById('docs-search-clear');
    var box = document.getElementById('docs-search-suggestions');
    var links = document.querySelectorAll('.docs-index__links .docs-index__link');
    if (!input || !links.length) return;
    _docsSearchInitialized = true;
    _docsIndex = docsBuildIndex();

    input.addEventListener('input', function() {
      var q = this.value.trim().toLowerCase();
      _docsActive = -1;  // reset the keyboard cursor on a new query
      _docsRenderSuggestions(q);
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
      // `block` (not '' — an empty string would remove the inline style and
      // restore the stylesheet's `display:none`, keeping the ✕ button forever
      // invisible; found by the docs-autocomplete E2E).
      if (clear) clear.style.display = q ? 'block' : 'none';
    });

    // Keyboard: ↑/↓ move the cursor, Enter opens the selected section,
    // Escape closes the dropdown.
    input.addEventListener('keydown', function(e) {
      if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
        e.preventDefault();
        if (!_docsSuggestions.length) return;
        var step = e.key === 'ArrowDown' ? 1 : -1;
        _docsActive = Math.max(0, Math.min(_docsSuggestions.length - 1, _docsActive + step));
        _docsRenderSuggestions(this.value.trim().toLowerCase());
      } else if (e.key === 'Enter') {
        if (_docsActive >= 0 && _docsSuggestions[_docsActive]) {
          e.preventDefault();
          _docsGoTo(_docsSuggestions[_docsActive].id);
        }
      } else if (e.key === 'Escape') {
        _docsCloseSuggestions();
      }
    });

    // mousedown (not click) so the blur handler below never beats it — the
    // suggestion fires before the input loses focus.
    if (box) {
      box.addEventListener('mousedown', function(e) {
        var item = e.target.closest('.docs-search__item');
        if (item) { e.preventDefault(); _docsGoTo(item.getAttribute('data-docs-id')); }
      });
      // Hover moves the keyboard cursor for Enter-to-open consistency.
      box.addEventListener('mouseover', function(e) {
        var item = e.target.closest('.docs-search__item');
        if (!item) return;
        _docsActive = Array.prototype.indexOf.call(box.children, item);
        var items = box.querySelectorAll('.docs-search__item');
        items.forEach(function(el, i) { el.classList.toggle('active', i === _docsActive); });
      });
    }

    input.addEventListener('blur', function() {
      setTimeout(_docsCloseSuggestions, 120);
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
      _initDocsFeedback();
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

  // ── Close the main IIFE (opened at the top of the file) ──
  // The renderKpiCards() helper and every handler above live INSIDE this scope
  // so `dom`, `fmt`, etc. resolve correctly. Do not add code after this line.
})();
