  // ── DOM cache ─────────────────────────────────────────────────────────
  const $ = (s) => document.querySelector(s);
  const $$ = (s) => document.querySelectorAll(s);
  const dom = {
    topbarAddress: $('#topbar-address'), statusPill: $('#status-pill'), statusText: $('#status-text'), topbarFreshness: $('#topbar-freshness'),
    topbarInstance: $('#topbar-instance'),
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

  
  // ── Design tokens para o canvas (Issue #216) ───────────────────────
  // O canvas não resolve CSS var() — lê o valor real do :root. Zero hex
  // fora do style.css: todo consumo de cor passa pelo token system.
  function cssVar(name) {
    return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || '';
  }

  // ── Icon sweep (Issue #236): Lucide 24×24 stroke icons via helper (zero emoji) ──
  // Mesma linguagem visual do sidebar: stroke currentColor, viewBox 0 0 24 24.
  // Uso: _ic('zap', 12, true) → svg 12px com gap para texto ao lado.
  function _ic(name, size, gap) {
    var ICONS = {
      zap: '<polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/>',
      sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2"/><path d="M12 20v2"/><path d="m4.93 4.93 1.41 1.41"/><path d="m17.66 17.66 1.41 1.41"/><path d="M2 12h2"/><path d="M20 12h2"/><path d="m6.34 17.66-1.41 1.41"/><path d="m19.07 4.93-1.41 1.41"/>',
      moon: '<path d="M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9Z"/>',
      settings: '<path d="M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 2 0 0 1-2 0l-.15-.08a2 2 0 0 0-2.73.73l-.22.38a2 2 0 0 0 .73 2.73l.15.1a2 2 0 0 1 1 1.72v.51a2 2 0 0 1-1 1.74l-.15.09a2 2 0 0 0-.73 2.73l.22.38a2 2 0 0 0 2.73.73l.15-.08a2 2 0 0 1 2 0l.43.25a2 2 0 0 1 1 1.73V20a2 2 0 0 0 2 2h.44a2 2 0 0 0 2-2v-.18a2 2 0 0 1 1-1.73l.43-.25a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 2.73-.73l.22-.39a2 2 0 0 0-.73-2.73l-.15-.08a2 2 0 0 1-1-1.74v-.5a2 2 0 0 1 1-1.74l.15-.09a2 2 0 0 0 .73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08a2 2 0 0 1-2 0l-.43-.25a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2z"/><circle cx="12" cy="12" r="3"/>',
      search: '<circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/>',
      flask: '<path d="M10 2v7.527a2 2 0 0 1-.211.896L4.72 20.55a1 1 0 0 0 .9 1.45h12.76a1 1 0 0 0 .9-1.45l-5.069-10.127A2 2 0 0 1 14 9.527V2"/><path d="M8.5 2h7"/><path d="M7 16h10"/>',
      x: '<path d="M18 6 6 18"/><path d="m6 6 12 12"/>',
      check: '<path d="M20 6 9 17l-5-5"/>',
      alert: '<path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 20h16a2 2 0 0 0 1.73-2Z"/><path d="M12 9v4"/><path d="M12 17h.01"/>',
      rotate: '<path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/><path d="M3 3v5h5"/><path d="M12 7v5l4 2"/>',
      refresh: '<path d="M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8"/><path d="M21 3v5h-5"/><path d="M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16"/><path d="M8 16H3v5"/>',
      send: '<path d="m22 2-7 20-4-9-9-4Z"/><path d="M22 2 11 13"/>',
      ban: '<circle cx="12" cy="12" r="10"/><path d="m4.9 4.9 14.2 14.2"/>',
      robot: '<path d="M12 8V4H8"/><rect width="16" height="12" x="4" y="8" rx="2"/><path d="M2 14h2"/><path d="M20 14h2"/><path d="M15 13v2"/><path d="M9 13v2"/>',
      key: '<path d="m15.5 7.5 2.3 2.3a1 1 0 0 0 1.4 0l2.1-2.1a1 1 0 0 0 0-1.4L19 4"/><path d="m21 2-9.6 9.6"/><circle cx="7.5" cy="15.5" r="5.5"/>',
      package: '<path d="m7.5 4.27 9 5.15"/><path d="M21 8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16Z"/><path d="m3.3 7 8.7 5 8.7-5"/><path d="M12 22V12"/>',
      thumbsUp: '<path d="M7 10v12"/><path d="M15 5.88 14 10h5.83a2 2 0 0 1 1.92 2.56l-2.33 8A2 2 0 0 1 17.5 22H4a2 2 0 0 1-2-2v-8a2 2 0 0 1 2-2h2.76a2 2 0 0 0 1.79-1.11L12 2a3.13 3.13 0 0 1 3 3.88Z"/>',
      thumbsDown: '<path d="M17 14V2"/><path d="M9 18.12 10 14H4.17a2 2 0 0 1-1.92-2.56l2.33-8A2 2 0 0 1 6.5 2H20a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2h-2.76a2 2 0 0 0-1.79 1.11L12 22a3.13 3.13 0 0 1-3-3.88Z"/>',
      trophy: '<path d="M6 9H4.5a2.5 2.5 0 0 1 0-5H6"/><path d="M18 9h1.5a2.5 2.5 0 0 0 0-5H18"/><path d="M4 22h16"/><path d="M10 14.66V17c0 .55-.47.98-.97 1.21C7.85 18.75 7 20.24 7 22"/><path d="M14 14.66V17c0 .55.47.98.97 1.21C16.15 18.75 17 20.24 17 22"/><path d="M18 2H6v7a6 6 0 0 0 12 0V2Z"/>'
    };
    var s = size || 12;
    var st = ' style="vertical-align:-2px' + (gap ? ';margin-right:4px' : '') + '"';
    return '<svg xmlns="http://www.w3.org/2000/svg" width="' + s + '" height="' + s + '" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"' + st + '>' + (ICONS[name] || '') + '</svg>';
  }

  // ── FASE 2: Toast notification (design system: classes .toast + tokens) ──
  function showToast(type, message) {
    var t = document.getElementById('toast-container');
    if (!t) {
      t = document.createElement('div');
      t.id = 'toast-container';
      t.setAttribute('role', 'status');
      t.setAttribute('aria-live', 'polite');
      t.setAttribute('aria-atomic', 'true');
      document.body.appendChild(t);
    }
    var el = document.createElement('div');
    var kind = type === 'success' ? 'success' : (type === 'warn' || type === 'warning') ? 'warn' : (type === 'info' ? 'info' : 'error');
    el.className = 'toast toast--' + kind;
    el.textContent = message;
    t.appendChild(el);
    requestAnimationFrame(function() { el.classList.add('visible'); });
    setTimeout(function() {
      el.classList.remove('visible');
      setTimeout(function() { el.remove(); }, 300);
    }, 3000);
  }

