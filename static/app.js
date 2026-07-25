/* ════════════════════════════════════════════════════════════════════════
   CYPHER65 · WAR ROOM · client logic
   ════════════════════════════════════════════════════════════════════════ */

(() => {
  'use strict';

  // ── constants ─────────────────────────────────────────────────────────
  const POLL_MS = window.POLL_INTERVAL_MS || 15000;
  const POLL_MS_BACKGROUND = POLL_MS * 3;  // 3x slower when tab hidden (battery save)
  let nextPollAt = Date.now() + POLL_MS;
  let _pollTimer = null;
  let _isTabHidden = false;
  let _matrixRunning = false;

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
    pct(n) { if (!isFinite(n)) return '\u2014'; return `${n.toFixed(2)}%`; },
    usd(n) { if (!n) return '\u2014'; return `$${Number(n).toLocaleString('en-US', { maximumFractionDigits: 0 })}`; },
    expectedBlock(workerHr, networkDiff) {
      if (!workerHr || !networkDiff) return null;
      // E[time] = difficulty * 2^32 / hashrate  (seconds to find a block)
      const secs = (networkDiff * Math.pow(2, 32)) / workerHr;
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
  const dom = {
    topbarAddress: $('#topbar-address'), statusPill: $('#status-pill'), statusText: $('#status-text'),
    clock: $('#clock'), nextPoll: $('#next-poll'), refreshNow: $('#refresh-now'),
    workerRankBadge: $('#worker-rank-badge'), workerUptimeBadge: $('#worker-uptime-badge'),
    mHashrate: $('#m-hashrate'), mHashrateSub: $('#m-hashrate-sub'), mBestDiff: $('#m-bestdiff'), mBestDiffSub: $('#m-bestdiff-sub'),
    mLastShare: $('#m-lastshare'), mLastShareSub: $('#m-lastshare-sub'), mState: $('#m-state'), mStateSub: $('#m-state-sub'),
    mSharePct: $('#m-share-pct'), mFairDiff: $('#m-fair-diff'), mExpectedShare: $('#m-expected-share'), mExpectedBlock: $('#m-expected-block'),
    poolUptime: $('#pool-uptime'), pHashrate: $('#p-hashrate'), pWorkers: $('#p-workers'), pHighDiff: $('#p-high-diff'),
    pLastBlock: $('#p-last-block'), pLastBlockTime: $('#p-last-block-time'), pWorkNum: $('#p-work-num'), pWorkFill: $('#p-work-fill'), pExpectedBlocks: $('#p-expected-blocks'),
    acctBlocksBadge: $('#acct-blocks-badge'), acctLn: $('#acct-ln'), acctTotalDiff: $('#acct-total-diff'),
    acctHighestBlock: $('#acct-highest-block'), acctCombined: $('#acct-combined'), acctDiffRank: $('#acct-diff-rank'), acctLoyaltyRank: $('#acct-loyalty-rank'),
    netStatus: $('#net-status'), nHeight: $('#n-height'), nDiff: $('#n-diff'), nHashrate: $('#n-hashrate'),
    nBtcUsd: $('#n-btc-usd'), nBtcBrl: $('#n-btc-brl'), nBtcEur: $('#n-btc-eur'), nBtcGbp: $('#n-btc-gbp'),
    eventsTbody: $('#events-tbody'), lbTbody: $('#lb-tbody'), logEventsCount: $('#log-events-count'), terminal: $('#terminal'),
    alertsList: $('#alerts-list'), alertsCountBadge: $('#alerts-count-badge'),
    timelineFeed: $('#timeline-feed'), timelineSharesBadge: $('#timeline-shares-badge'), timelineBumpsBadge: $('#timeline-bumps-badge'), timelineRateBadge: $('#timeline-rate-badge'),
    tStatLastShare: $('#t-stat-lastshare'), tStat1h: $('#t-stat-1h'), tStat24h: $('#t-stat-24h'), tStatBumps: $('#t-stat-bumps'),
    hBlocks: $('#h-blocks'), hDays: $('#h-days'), hCurReward: $('#h-cur-reward'), hNextReward: $('#h-next-reward'), hNextHeight: $('#h-next-height'), halvingEpochBadge: $('#halving-epoch-badge'),
    feeEconomy: $('#fee-economy'), feeHour: $('#fee-hour'), feeHalfhour: $('#fee-halfhour'), feeFastest: $('#fee-fastest'), feeMinimum: $('#fee-minimum'),
    profitShareBadge: $('#profit-share-badge'), profitCostBadge: $('#profit-cost-badge'), pBtcDay: $('#p-btc-day'),
    pFiatDay: $('#p-fiat-day'), pFiatDayWeek: $('#p-fiat-day-week'), pFiatMonth: $('#p-fiat-month'), pFiatMonthSub: $('#p-fiat-month-sub'),
    pBreakeven: $('#p-breakeven'), pBreakevenSub: $('#p-breakeven-sub'), pBtcSub: $('#p-btc-sub'), profitFootnote: $('#profit-footnote'), pCurBadge: $('#p-cur-badge'), profitFiatRow: $('#profit-fiat-row'),
    gaugeLabel: $('#gauge-label'), gaugeWorkerCanvas: $('#gauge-worker-canvas'), gaugePoolCanvas: $('#gauge-pool-canvas'), gaugeLuckCanvas: $('#gauge-luck-canvas'),
    gaugeWorkerPct: $('#gauge-worker-pct'), gaugePoolPct: $('#gauge-pool-pct'), gaugeLuckPct: $('#gauge-luck-pct'), gaugeWorkerBlockchance: $('#gauge-worker-blockchance'),
    badgesStrip: $('#badges-strip'), milestonesCount: $('#milestones-count'),
    proxPctBadge: $('#prox-pct-badge'), proxAlltimeBadge: $('#prox-alltime-badge'), proxStreakBadge: $('#prox-streak-badge'), proxArc: $('#prox-arc'),
    proxHeroPct: $('#prox-hero-pct'), proxHeroSub: $('#prox-hero-sub'), proxHeroBest: $('#prox-hero-best'),
    proxChance: $('#prox-chance'), proxTime: $('#prox-time'), proxTimeSub: $('#prox-time-sub'), proxDistance: $('#prox-distance'), proxTrend: $('#prox-trend'), proxTrendSub: $('#prox-trend-sub'),
    proxLadderRow: $('#prox-ladder-row'), proxSparkline: $('#prox-sparkline'), proxTip: document.getElementById('prox-tip'),
    qlBadge: $('#ql-badge'), qlScoreNum: $('#ql-score-num'), qlScoreArc: document.getElementById('ql-score-arc'),
    qlStatus: $('#ql-status'), qlLabel: $('#ql-label'), qlConfidence: $('#ql-confidence'),
    qlCompShares: $('#ql-comp-shares'), qlCompSharesVal: $('#ql-comp-shares-val'),
    qlCompProximity: $('#ql-comp-proximity'), qlCompProximityVal: $('#ql-comp-proximity-val'),
    qlCompPower: $('#ql-comp-power'), qlCompPowerVal: $('#ql-comp-power-val'),
    qlCompMomentum: $('#ql-comp-momentum'), qlCompMomentumVal: $('#ql-comp-momentum-val'),
    lcTimeBig: $('#lc-time-big'), lcSessionShareCount: $('#lc-session-share-count'), lcShareDiff: $('#lc-share-diff'), lcHashes: $('#lc-hashes'),
    lcTimeObs: $('#lc-time-obs'), lcPBlock: $('#lc-p-block'), lcInstHr: $('#lc-inst-hr'), lcSessionShares: $('#lc-session-shares'),
    lcAvgShareDiff: $('#lc-avg-share-diff'), lcCumP: $('#lc-cum-p'), lcExpectedBlocks: $('#lc-expected-blocks'), lcTickerList: $('#lc-ticker-list'), lcTickerCount: $('#lc-ticker-count'),
    lcChartDiff: document.getElementById('lc-chart-diff'), lcChartPBlock: document.getElementById('lc-chart-pblock'),
    lcChartHr: document.getElementById('lc-chart-hr'), lcChartCumulative: document.getElementById('lc-chart-cumulative'),
    lcConsistencyBadge: $('#lc-consistency-badge'),
    lmGrid: $('#lm-grid'), lmStatusBadge: $('#lm-status-badge'), lmWorkersBadge: $('#lm-workers-badge'),
    lmSummaryWallet: $('#lm-summary-wallet'), lmSummaryPool: $('#lm-summary-pool'), lmSummaryDot: $('#lm-summary-dot'),
    lmSummaryWorkers: $('#lm-summary-workers'), lmSummaryHr: $('#lm-summary-hr'), lmSummaryBest: $('#lm-summary-best'),
    lmBestShare: $('#lm-best-share'), lmBestShareVal: $('#lm-best-share-val'), lmBestShareWorker: $('#lm-best-share-worker'), lmBestShareTime: $('#lm-best-share-time'),
    lmEventLogTerminal: $('#lm-event-log-terminal'),
    hsNonceBar: $('#hs-nonce-bar'), hsNoncesSearched: $('#hs-nonces-searched'), hsNoncePct: $('#hs-nonce-pct'), hsHashesPerSec: $('#hs-hashes-per-sec'),
    hsBestDiff: $('#hs-best-diff'), hsTargetDiff: $('#hs-target-diff'), hsTargetBar: $('#hs-target-bar'), hsTargetMarker: $('#hs-target-marker'),
    hsBlockProb: $('#hs-block-prob'), hsExpectedTime: $('#hs-expected-time'), hsStatusText: $('#hs-status-text'),
    cfoPBlock: $('#cfo-p-block'), cfoPBlockSub: $('#cfo-p-block-sub'), cfoExpected: $('#cfo-expected'), cfoMedian: $('#cfo-median'), cfoP90: $('#cfo-p90'),
    cfoDist: $('#cfo-dist'), cfoHours: $('#cfo-hours'), cfoFootnote: $('#cfo-footnote'), cfoStatus: $('#cfo-status'),
    openSettings: $('#open-settings'), openExports: $('#open-exports'), settingsModal: $('#settings-modal'), exportModal: $('#export-modal'),
    settingsBody: $('#settings-body'), settingsStatus: $('#settings-status'),
    huntStreamFeed: $('#hunt-stream-feed'), huntMetricsHr: $('#hunt-metrics-hr'), huntMetricsPblock: $('#hunt-metrics-pblock'),
    huntMetricsExpblocks: $('#hunt-metrics-expblocks'), huntMetricsBestdiff: $('#hunt-metrics-bestdiff'),
    huntSharesGrid: $('#hunt-shares-grid'), huntSharesCount: $('#hunt-shares-count'),
  };

  // ── escape HTML ───────────────────────────────────────────────────────
  function escapeHtml(s) { return String(s).replace(/[&<>"']/g, c => ({ '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;' }[c])); }

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

  function renderHero(snap) {
    const w = snap.worker || {};
    smoothUpdate(dom.mHashrate, fmt.hashrate(w.hashrate));
    smoothUpdate(dom.mBestDiff, fmt.diff(w.bestDifficulty));
    if (dom.mLastShare) dom.mLastShare.textContent = w.lastSubmission ? fmt.age(w.lastSubmission) : '\u2014';
    if (dom.mState) dom.mState.textContent = w.hashrate ? 'HASHING' : 'IDLE';
  }

  function renderPool(pool) {
    if (!pool) return;
    if (dom.pHashrate) dom.pHashrate.textContent = fmt.hashrate(pool.hashrate);
    if (dom.pWorkers) dom.pWorkers.textContent = `${pool.workers || 0} / ${pool.users || 0}`;
    if (dom.pHighDiff) dom.pHighDiff.textContent = fmt.diff(pool.highestDiff || pool.highestDifficulty);
    if (dom.pLastBlock) dom.pLastBlock.textContent = pool.lastBlockHeight ? `#${pool.lastBlockHeight}` : (pool.lastBlock ? `#${pool.lastBlock}` : '\u2014');
    if (dom.pLastBlockTime && (pool.lastBlockTime || pool.lastBlockTimestamp)) dom.pLastBlockTime.textContent = fmt.age(pool.lastBlockTime || pool.lastBlockTimestamp);
    if (dom.pWorkFill && pool.workPct != null) dom.pWorkFill.style.width = `${pool.workPct}%`;
    if (dom.pWorkNum) dom.pWorkNum.textContent = pool.workStr || '\u2014';
    // Expected seconds per block (pool-wide)
    if (dom.pExpectedBlocks && pool.expectedSecondsPerBlock) {
      const secs = pool.expectedSecondsPerBlock;
      if (secs < 86400) dom.pExpectedBlocks.textContent = fmt.secsToHuman(secs);
      else dom.pExpectedBlocks.textContent = (secs / 86400).toFixed(1) + 'd';
    }
    // API status: LIVE if pool data is present
    setPoolStatus(pool);
  }

  function setPoolStatus(pool) {
    if (!pool || !pool.hashrate) {
      const el = document.getElementById('api-pool');
      if (el) { el.textContent = 'ERROR'; el.className = 'badge api-status badge--error'; }
      return;
    }
    const el = document.getElementById('api-pool');
    if (!el) return;
    const wslb = pool.workSinceLastBlock != null ? pool.workSinceLastBlock : pool.workPct;
    const hasWork = wslb != null;
    el.textContent = hasWork ? 'LIVE' : 'ESTIMATED';
    el.className = 'badge api-status badge--' + (hasWork ? 'live' : 'estimated');
  }

  function renderNetwork(net) {
    if (!net) return;
    if (dom.nHeight) dom.nHeight.textContent = net.height ? `#${net.height}` : '\u2014';
    if (dom.nDiff) dom.nDiff.textContent = fmt.diff(net.difficulty);
    if (dom.nHashrate) dom.nHashrate.textContent = fmt.hashrate(net.hashrate);
  }

  function renderAccount(acct) {
    if (!acct) return;
    // LN address from account API response
    if (dom.acctLn) dom.acctLn.textContent = acct.lightning || '\u2014';
    // totalDifficulty (alias) or total_diff (API field)
    const td = acct.totalDifficulty != null ? acct.totalDifficulty : acct.total_diff;
    if (dom.acctTotalDiff) dom.acctTotalDiff.textContent = td ? fmt.diff(td) : '\u2014';
    if (dom.acctHighestBlock) dom.acctHighestBlock.textContent = acct.highestBlock || acct.highest_blockheight || '\u2014';
    if (dom.acctCombined) dom.acctCombined.textContent = acct.combinedScore != null ? Number(acct.combinedScore).toLocaleString() : '\u2014';
    if (dom.acctDiffRank) dom.acctDiffRank.textContent = acct.diffRank != null ? '#' + acct.diffRank : '\u2014';
    if (dom.acctLoyaltyRank) dom.acctLoyaltyRank.textContent = acct.loyaltyRank != null ? '#' + acct.loyaltyRank : '\u2014';
    if (dom.acctBlocksBadge) dom.acctBlocksBadge.textContent = (acct.blocksFound || 0) + ' BLOCKS';
  }

  function renderBtcPrices(btc) {
    if (!btc) return;
    if (dom.nBtcUsd) dom.nBtcUsd.textContent = btc.usd ? `$${Number(btc.usd).toLocaleString()}` : '\u2014';
    if (dom.nBtcBrl) dom.nBtcBrl.textContent = btc.brl ? `R$${Number(btc.brl).toLocaleString()}` : '\u2014';
    if (dom.nBtcEur) dom.nBtcEur.textContent = btc.eur ? `€${Number(btc.eur).toLocaleString()}` : '\u2014';
    if (dom.nBtcGbp) dom.nBtcGbp.textContent = btc.gbp ? `£${Number(btc.gbp).toLocaleString()}` : '\u2014';
  }

  function renderHalving(h) {
    if (!h) return;
    // Blocks remaining
    if (dom.hBlocks) dom.hBlocks.textContent = h.blocks_remaining != null ? h.blocks_remaining.toLocaleString() : '\u2014';
    // Days remaining (using rolling avg block time)
    if (dom.hDays) dom.hDays.textContent = h.estimated_days_remaining != null ? `${Math.round(h.estimated_days_remaining)}d` : '\u2014';
    // Current reward
    if (dom.hCurReward) dom.hCurReward.textContent = h.current_reward_btc != null ? `${h.current_reward_btc} BTC` : '\u2014';
    // Next reward
    if (dom.hNextReward) dom.hNextReward.textContent = h.next_reward_btc != null ? `${h.next_reward_btc} BTC` : '\u2014';
    // Next height
    if (dom.hNextHeight) dom.hNextHeight.textContent = h.next_height != null ? `#${h.next_height.toLocaleString()}` : '\u2014';
    // Epoch badge
    if (dom.halvingEpochBadge) dom.halvingEpochBadge.textContent = h.epoch_label || '--';
    // Progress bar (pct_complete)
    const pct = h.pct_complete != null ? h.pct_complete : 0;
    const progressEl = document.getElementById('halving-progress-fill');
    if (progressEl) progressEl.style.width = pct + '%';
    const progressLabel = document.getElementById('halving-progress-label');
    if (progressLabel) progressLabel.textContent = pct.toFixed(1) + '%';
    // Block time info
    const avgTimeEl = document.getElementById('halving-avg-time');
    if (avgTimeEl && h.avg_block_time_s) {
      avgTimeEl.textContent = `avg ${h.avg_block_time_s.toFixed(0)}s/block`;
    }
  }

  function renderMempoolFees(f) {
    if (!f) return;
    const set = (el, v) => { if (el) el.textContent = v != null ? `${v} sat/vB` : '\u2014'; };
    set(dom.feeEconomy, f.economyFee); set(dom.feeHour, f.hourFee); set(dom.feeHalfhour, f.halfHourFee);
    set(dom.feeFastest, f.fastestFee); set(dom.feeMinimum, f.minimumFee);

    // Congestion assessment + recommendations
    const fastest = f.fastestFee;
    const el = document.getElementById('fees-status');
    const recEl = document.getElementById('fee-recommendation');
    if (!el) return;
    if (fastest == null) {
      el.textContent = 'FEES UNAVAILABLE';
      el.className = 'badge badge--mute';
      if (recEl) recEl.textContent = '⛔ Fee data unavailable — mempool.space may be unreachable';
      return;
    }
    let status, cls;
    if (fastest >= 200) {
      status = 'HIGH CONGESTION';
      cls = 'badge--red';
    } else if (fastest >= 100) {
      status = 'MODERATE';
      cls = 'badge--gold';
    } else if (fastest >= 30) {
      status = 'NORMAL';
      cls = 'badge--green';
    } else {
      status = 'LOW';
      cls = 'badge--green';
    }
    el.textContent = status;
    el.className = 'badge ' + cls;

    // Recommendation text
    if (recEl) {
      if (fastest <= 5) {
        recEl.textContent = '⇩ Mempool clear — minimum fee sufficient for next block';
      } else if (fastest <= 20) {
        recEl.textContent = '→ Normal conditions — hour fee should confirm within 1-2 blocks';
      } else if (fastest <= 50) {
        recEl.textContent = '↗ Elevated — consider half-hour fee for reliable next-block inclusion';
      } else if (fastest <= 100) {
        recEl.textContent = '↗ Busy — fastest fee recommended for timely confirmation';
      } else if (fastest <= 200) {
        recEl.textContent = '⇈ Congested — high fees; fastest fee required for next-block';
      } else {
        recEl.textContent = '⇈⚠ EXTREME — wait for congestion to clear or pay premium for next-block';
      }
    }
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
    dom.eventsTbody.innerHTML = events.map(e => `<tr><td>#${e.block || '\u2014'}</td><td>${fmt.shortAddr(e.address || '')}</td><td>${fmt.diff(e.difficulty)}</td><td>${fmt.age(e.ts)}</td><td>${e.claimed ? 'YES' : 'NO'}</td></tr>`).join('');
  }

  function renderLeaderboard(lb) {
    if (!dom.lbTbody) return;
    if (!lb || !lb.length) { dom.lbTbody.innerHTML = '<tr><td colspan="6" class="empty">awaiting data\u2026</td></tr>'; return; }
    dom.lbTbody.innerHTML = lb.map((r, i) => `<tr><td>${i+1}</td><td>${fmt.shortAddr(r.address)}</td><td>${r.diffRank || '\u2014'}</td><td>${r.loyalty || '\u2014'}</td><td>${r.score || '\u2014'}</td><td>${r.blocks || 0}</td></tr>`).join('');
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

  document.getElementById('clear-logs')?.addEventListener('click', () => {
    events.length = 0; renderedEventCount = 0;
    dom.terminal.innerHTML = '<div class="terminal__line ts-mute">cleared</div>';
    dom.logEventsCount.textContent = '0 events';
  });

  // ── Timeline ──
  const TIMELINE_MAX = 80; const timelineIdsRendered = new Set(); let timelineTotalRendered = 0;
  function renderTimelineFeed(list) {
    if (!dom.timelineFeed) return;
    if (!list || !list.length) return;
    const ordered = list.slice().reverse();
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
    if (dom.proxChance) {
      const sourceLabel = prox.chance_per_share_source === 'avg' ? 'avg share' : 'best share';
      dom.proxChance.textContent = (prox.chance_per_share_label || '—') + ' (' + sourceLabel + ')';
    }
    if (dom.proxTime) dom.proxTime.textContent = prox.expected_time_human || '—';
    if (dom.proxTimeSub && prox.blocks_per_year != null) {
      dom.proxTimeSub.textContent = '~' + prox.blocks_per_year.toFixed(4) + ' blocks/yr @ current HR';
    }
    if (dom.proxDistance) dom.proxDistance.textContent = prox.distance_label || '—';
    if (dom.proxTrend) dom.proxTrend.textContent = (prox.trend_1h_pct != null ? (prox.trend_1h_pct >= 0 ? '+' : '') + prox.trend_1h_pct.toFixed(1) + '%' : '—') + ' · ' + (prox.trend_label || 'flat');
    if (dom.proxTrendSub) {
      const rolling = prox.trend_rolling || {};
      const shareInfo = rolling.recent_avg_str ? 'avg share: ' + rolling.recent_avg_str + ' (' + rolling.recent_count + ' shares)' : '';
      dom.proxTrendSub.textContent = 'rolling avg share diff · 1h' + (shareInfo ? ' · ' + shareInfo : '');
    }

    // Milestone ladder
    if (dom.proxLadderRow) {
      const milestones = prox.milestones_achieved || [];
      const next = prox.next_milestone_pct;
      dom.proxLadderRow.innerHTML = milestones.map(m => '<span class="prox-ladder__step prox-ladder__step--done">' + (m >= 1 ? m.toFixed(0) + '%' : m.toFixed(2) + '%') + '</span>').join('')
        + (next != null ? '<span class="prox-ladder__step prox-ladder__step--next">' + (next >= 1 ? next.toFixed(0) + '%' : next.toFixed(2) + '%') + '</span>' : '');
    }

    // Sparkline canvas
    _drawProximitySparkline(prox);

    // Quantum-lock assessment
    _renderQuantumLock(prox);
  }

  // ── Quantum-lock render helper ──
  function _renderQuantumLock(prox) {
    const ql = prox.quantum_lock;
    if (!ql) {
      if (dom.qlStatus) dom.qlStatus.textContent = 'NO DATA';
      if (dom.qlLabel) dom.qlLabel.textContent = 'awaiting share data';
      if (dom.qlBadge) dom.qlBadge.textContent = '—';
      if (dom.qlScoreNum) dom.qlScoreNum.textContent = '—';
      return;
    }

    // Badge
    const statusColors = {
      'STRONG_LOCK': 'badge--green',
      'MODERATE_LOCK': 'badge--gold',
      'WEAK_LOCK': 'badge--yellow',
      'TRACKING': 'badge--mute',
      'NO_DATA': 'badge--mute',
    };
    if (dom.qlBadge) {
      dom.qlBadge.textContent = ql.status || '—';
      dom.qlBadge.className = 'badge ql-badge ' + (statusColors[ql.status] || 'badge--mute');
    }

    // Score arc
    const score = Math.min(100, Math.max(0, ql.score || 0));
    const arc = dom.qlScoreArc;
    if (arc) {
      const circumference = 2 * Math.PI * 52;
      const offset = circumference * (1 - score / 100);
      arc.setAttribute('stroke-dasharray', circumference);
      arc.setAttribute('stroke-dashoffset', offset);
    }
    if (dom.qlScoreNum) dom.qlScoreNum.textContent = score;

    // Status + label + confidence
    if (dom.qlStatus) {
      dom.qlStatus.textContent = ql.status ? ql.status.replace(/_/g, ' ') : '—';
      const statusCls = (ql.status || 'NO_DATA').toLowerCase();
      dom.qlStatus.className = 'ql-status ql-status--' + statusCls;
    }
    if (dom.qlLabel) dom.qlLabel.textContent = ql.label || 'awaiting data';
    if (dom.qlConfidence) dom.qlConfidence.textContent = ql.confidence || 'NONE';

    // Components
    const comps = ql.components || {};
    const maxScores = { shares: 30, proximity: 40, power: 20, momentum: 10 };
    const setComp = (barEl, valEl, key, defaultMax) => {
      const raw = comps[key] || 0;
      const max = maxScores[key] || defaultMax || 100;
      const pct = max > 0 ? (raw / max * 100) : 0;
      if (barEl) barEl.style.width = Math.min(100, pct) + '%';
      if (valEl) valEl.textContent = raw + '/' + max;
    };
    setComp(dom.qlCompShares, dom.qlCompSharesVal, 'shares', 30);
    setComp(dom.qlCompProximity, dom.qlCompProximityVal, 'proximity', 40);
    setComp(dom.qlCompPower, dom.qlCompPowerVal, 'power', 20);
    setComp(dom.qlCompMomentum, dom.qlCompMomentumVal, 'momentum', 10);
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
    const cssW = c.clientWidth || 220, cssH = c.clientHeight || 28;
    c.width = cssW * dpr; c.height = cssH * dpr;
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
  // NETWORK SHARE GAUGE — 3 semi-circular canvas gauges
  // ══════════════════════════════════════════════════════════════════════

  function renderNetworkGauge(snap) {
    const gauge = snap.network_share_gauge || {};
    const luck = snap.luck_estimate || {};
    const worker = snap.worker || {};
    const pool = snap.pool || {};
    const net = snap.network || {};

    const hasData = gauge.has_data === true;

    // Label — shows worker % of network and pool % of network
    if (dom.gaugeLabel) {
      dom.gaugeLabel.textContent = hasData && gauge.label ? gauge.label : '—';
    }

    // ── Worker gauge: % of total network hashrate ──
    if (dom.gaugeWorkerPct) {
      if (hasData && gauge.worker_pct != null) {
        dom.gaugeWorkerPct.textContent = gauge.worker_pct.toFixed(6) + '%';
      } else {
        dom.gaugeWorkerPct.textContent = '—';
      }
    }
    // 22-min block chance (Poisson: P(≥1 block in 22 min))
    if (dom.gaugeWorkerBlockchance) {
      if (worker.hashrate && net.difficulty) {
        const hr = Number(worker.hashrate) || 0;
        const diff = Number(net.difficulty) || 1;
        const p22min = 1 - Math.exp(-(hr * 1320) / (diff * Math.pow(2, 32)));
        dom.gaugeWorkerBlockchance.textContent = p22min > 0 ? (p22min * 100).toFixed(4) + '%' : '~0%';
      } else {
        dom.gaugeWorkerBlockchance.textContent = '—';
      }
    }
    _drawGauge('gauge-worker-canvas', hasData && gauge.worker_pct != null ? gauge.worker_pct : 0);

    // ── Pool gauge: % of network the pool controls ──
    if (dom.gaugePoolPct) {
      if (hasData && gauge.pool_pct != null) {
        dom.gaugePoolPct.textContent = gauge.pool_pct.toFixed(4) + '%';
      } else {
        dom.gaugePoolPct.textContent = '—';
      }
    }
    _drawGauge('gauge-pool-canvas', hasData && gauge.pool_pct != null ? gauge.pool_pct : 0);

    // ── Luck gauge: round progress (0-100+%) ──
    const luckPct = luck.round_progress_pct || luck.pool_luck_pct || 0;
    if (dom.gaugeLuckPct) {
      dom.gaugeLuckPct.textContent = luckPct.toFixed(1) + '%';
    }
    // Cap arc at 100% for visual, but show real text value
    _drawGauge('gauge-luck-canvas', Math.min(100, luckPct));

    // ── Worker share of pool (new) — inline text ──
    if (hasData && gauge.worker_share_of_pool_pct != null) {
      // Update or create the pool-share indicator element
      const el = document.getElementById('gauge-pool-share');
      if (el) el.textContent = `you = ${gauge.worker_share_of_pool_pct.toFixed(4)}% of pool`;
    }

    // ── API status badge ──
    const apiEl = document.getElementById('api-gauge');
    if (apiEl) {
      if (hasData) {
        apiEl.textContent = 'LIVE';
        apiEl.className = 'badge api-status badge--live';
      } else if (snap.worker) {
        apiEl.textContent = 'ESTIMATED';
        apiEl.className = 'badge api-status badge--estimated';
      } else {
        apiEl.textContent = 'UNAVAILABLE';
        apiEl.className = 'badge api-status badge--error';
      }
    }
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

  // ══════════════════════════════════════════════════════════════════════
  // CFO MONTE CARLO — block discovery simulation
  // ══════════════════════════════════════════════════════════════════════

  // ── Slider helpers: convert slider value to human-readable label ──
  function _cfoSliderLabel(v) {
    const num = parseInt(v) || 24;
    if (num < 24) return num + 'h';
    if (num < 168) return (num / 24).toFixed(0) + 'd';
    if (num < 720) return (num / 24).toFixed(0) + 'd';
    if (num < 8760) return (num / 24 / 30).toFixed(0) + 'mo';
    return '1yr';
  }

  // ── Debounced Monte Carlo ──
  let _mcDebounceTimer = null;
  function _scheduleMC() {
    if (_mcDebounceTimer) clearTimeout(_mcDebounceTimer);
    _mcDebounceTimer = setTimeout(() => { _mcDebounceTimer = null; loadMonteCarlo(); }, 300);
  }

  // ── Wire up the slider on DOM ready ──
  document.addEventListener('DOMContentLoaded', () => {
    const slider = document.getElementById('cfo-slider');
    const label = document.getElementById('cfo-slider-label');
    if (slider && label) {
      slider.addEventListener('input', () => {
        label.textContent = _cfoSliderLabel(slider.value);
        _scheduleMC();
      });
    }
    // Initial run after settings load
    setTimeout(loadMonteCarlo, 500);
  });
  function loadMonteCarlo() {
    if (!dom.cfoPBlock) return;
    const slider = document.getElementById('cfo-slider');
    const hours = parseInt(slider?.value || 24);
    document.getElementById('api-cfo')?.classList.add('badge--estimated'); document.getElementById('api-cfo') && (document.getElementById('api-cfo').textContent = 'SIMULATING...');

    // Get current hashrate and difficulty from DOM
    const hrText = dom.mHashrate?.textContent || '0 TH/s';
    const hrMatch = hrText.match(/([\d.,]+)\s*([EPTGMk]?H\/s)/i);
    let hashrateHs = 0;
    if (hrMatch) {
      let val = parseFloat(hrMatch[1].replace(/,/g, ''));
      const unit = (hrMatch[2] || 'H/s').toUpperCase();
      const mult = { 'EH/S': 1e18, 'PH/S': 1e15, 'TH/S': 1e12, 'GH/S': 1e9, 'MH/S': 1e6, 'KH/S': 1e3, 'H/S': 1 };
      hashrateHs = val * (mult[unit] || 1);
    }
    if (hashrateHs <= 0) hashrateHs = window.__lastSnapshotHr || 225e12; // fallback from poll data

    const diffText = dom.nDiff?.textContent || fmt.diff(window.__lastSnapshotDiff || 110e12);
    const diffMatch = diffText.match(/([\d.,]+)\s*([EPTGMk]?)/i);
    let difficulty = window.__lastSnapshotDiff || 110e12;
    if (diffMatch) {
      let dval = parseFloat(diffMatch[1].replace(/,/g, ''));
      const dunit = (diffMatch[2] || 'T').toUpperCase();
      const dmult = { 'E': 1e18, 'P': 1e15, 'T': 1e12, 'G': 1e9, 'M': 1e6, 'K': 1e3, '': 1 };
      difficulty = dval * (dmult[dunit] || 1);
    }

    const durationSeconds = hours * 3600;
    const hashesPerBlock = difficulty * Math.pow(2, 32);
    const blockRate = hashrateHs / hashesPerBlock;
    const lambda = blockRate * durationSeconds;

    // Monte Carlo: N runs
    const N = 20000;
    const buckets = {};
    let maxBlocks = 0;
    for (let i = 0; i < N; i++) {
      // Poisson(lambda)
      const L = Math.exp(-lambda);
      let k = 0, p = 1;
      while (p > L) { k++; p *= Math.random(); }
      const blocks = k - 1;
      buckets[blocks] = (buckets[blocks] || 0) + 1;
      if (blocks > maxBlocks) maxBlocks = blocks;
    }

    // Statistics
    let cumulative = 0, totalBlocks = 0;
    const distEntries = [];
    for (let b = 0; b <= maxBlocks; b++) {
      const count = buckets[b] || 0;
      totalBlocks += b * count;
      distEntries.push({ blocks: b, count, pct: count / N * 100 });
    }
    const atLeast1 = N - (buckets[0] || 0);
    const pAtLeast1 = atLeast1 / N * 100;
    const expectedBlocks = totalBlocks / N;
    const medianBlocks = _calcMCMedian(buckets, N);
    const p90Blocks = _calcMCPercentile(buckets, N, 90);
    const p10Blocks = _calcMCPercentile(buckets, N, 10);

    // Display
    if (dom.cfoPBlock) dom.cfoPBlock.textContent = pAtLeast1 < 0.01 ? pAtLeast1.toExponential(2) + '%' : pAtLeast1.toFixed(4) + '%';
    if (dom.cfoPBlockSub) dom.cfoPBlockSub.textContent = 'over ' + hours + 'h · ' + N.toLocaleString() + ' runs';
    if (dom.cfoExpected) dom.cfoExpected.textContent = expectedBlocks < 0.001 ? expectedBlocks.toExponential(2) : expectedBlocks.toFixed(4);
    if (dom.cfoMedian) dom.cfoMedian.textContent = medianBlocks;
    if (dom.cfoP90) dom.cfoP90.textContent = 'P10=' + p10Blocks + ' · P90=' + p90Blocks;
    if (dom.cfoFootnote) dom.cfoFootnote.textContent = 'λ=' + lambda.toExponential(2) + ' · D=' + fmt.diff(difficulty) + ' · HR=' + fmt.hashrate(hashrateHs);
    document.getElementById('api-cfo')?.classList.remove('badge--error','badge--live'); document.getElementById('api-cfo')?.classList.add('badge--estimated'); document.getElementById('api-cfo') && (document.getElementById('api-cfo').textContent = 'SIMULATED');

    // Distribution bars
    if (dom.cfoDist) {
      const maxPct = Math.max(...distEntries.map(d => d.pct), 1);
      dom.cfoDist.innerHTML = distEntries.slice(0, 10).map(d => {
        const barW = (d.pct / maxPct) * 100;
        const barColor = d.blocks === 0 ? '#06d6f0' : d.blocks === 1 ? '#16b981' : '#f5b942';
        return '<div class="cfo-dist-row"><span class="cfo-dist-label">' + d.blocks + ' blk</span>'
          + '<div class="cfo-dist-bar-wrap"><div class="cfo-dist-bar" style="width:' + barW + '%;background:' + barColor + '"></div></div>'
          + '<span class="cfo-dist-pct">' + d.pct.toFixed(1) + '%</span></div>';
      }).join('');
    }
  }

  function _calcMCMedian(buckets, total) {
    let cum = 0; const half = total / 2;
    const keys = Object.keys(buckets).map(Number).sort((a, b) => a - b);
    for (const k of keys) { cum += buckets[k]; if (cum >= half) return k; }
    return keys[keys.length - 1] || 0;
  }

  window.loadMonteCarlo = loadMonteCarlo;
  window.setProfitMode = setProfitMode;
  window._disconnectWallet = _disconnectWallet;

  function _calcMCPercentile(buckets, total, pct) {
    let cum = 0; const target = total * pct / 100;
    const keys = Object.keys(buckets).map(Number).sort((a, b) => a - b);
    for (const k of keys) { cum += buckets[k]; if (cum >= target) return k; }
    return keys[keys.length - 1] || 0;
  }


  let _lcChartsInitialized = false;
  let _lcCharts = {};

  function _drawLcSparkline(canvas, data, color, label, fixedDec) {
    if (!canvas || !data || data.length < 2) return;
    const dpr = window.devicePixelRatio || 1;
    const cssW = canvas.clientWidth || 200;
    const cssH = canvas.clientHeight || 40;
    if (cssW < 10) return;
    canvas.width = cssW * dpr;
    canvas.height = cssH * dpr;
    const ctx = canvas.getContext('2d');
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, cssW, cssH);

    const pad = { top: 8, bottom: 12, left: 4, right: 4 };
    const w = cssW - pad.left - pad.right;
    const h = cssH - pad.top - pad.bottom;
    const max = Math.max(...data, 0.001);
    const min = Math.min(...data, 0);
    const range = max - min || 1;

    const x = (i) => pad.left + (i / Math.max(1, data.length - 1)) * w;
    const y = (v) => pad.top + h - ((v - min) / range) * h;

    // Fill gradient
    const grad = ctx.createLinearGradient(0, pad.top, 0, pad.top + h);
    grad.addColorStop(0, color.replace(')', ',0.3)').replace('rgb', 'rgba'));
    grad.addColorStop(1, color.replace(')', ',0)').replace('rgb', 'rgba'));
    ctx.fillStyle = grad;
    ctx.beginPath();
    ctx.moveTo(x(0), cssH);
    data.forEach((v, i) => ctx.lineTo(x(i), y(v)));
    ctx.lineTo(x(data.length - 1), cssH);
    ctx.closePath();
    ctx.fill();

    // Line
    ctx.strokeStyle = color;
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    data.forEach((v, i) => i === 0 ? ctx.moveTo(x(i), y(v)) : ctx.lineTo(x(i), y(v)));
    ctx.stroke();

    // Dot at end
    ctx.fillStyle = color;
    ctx.beginPath();
    ctx.arc(x(data.length - 1), y(data[data.length - 1]), 2.5, 0, Math.PI * 2);
    ctx.fill();

    // Labels: min and max
    ctx.fillStyle = 'rgba(255,255,255,0.35)';
    ctx.font = '8px JetBrains Mono';
    ctx.textAlign = 'left';
    ctx.fillText(max.toExponential(2), pad.left, pad.top - 2);
    ctx.textAlign = 'right';
    ctx.fillText(min.toExponential(2), cssW - pad.right, cssH - 2);
  }

  function _drawLcCumulativeChart(canvas, timeline, color) {
    if (!canvas || !timeline || timeline.length < 2) return;
    const data = timeline.map(p => p.cum_p_block * 100);
    const labels = timeline.map(p => '#' + p.share_idx);
    const dpr = window.devicePixelRatio || 1;
    const cssW = canvas.clientWidth || 400;
    const cssH = canvas.clientHeight || 60;
    if (cssW < 20) return;
    canvas.width = cssW * dpr;
    canvas.height = cssH * dpr;
    const ctx = canvas.getContext('2d');
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, cssW, cssH);

    const pad = { top: 10, bottom: 14, left: 8, right: 8 };
    const w = cssW - pad.left - pad.right;
    const h = cssH - pad.top - pad.bottom;
    const max = Math.max(...data, 0.01);
    const x = (i) => pad.left + (i / Math.max(1, data.length - 1)) * w;
    const y = (v) => pad.top + h - (v / max) * h;

    // Fill
    const grad = ctx.createLinearGradient(0, pad.top, 0, pad.top + h);
    grad.addColorStop(0, 'rgba(0,255,159,0.25)');
    grad.addColorStop(1, 'rgba(0,255,159,0)');
    ctx.fillStyle = grad;
    ctx.beginPath();
    ctx.moveTo(x(0), cssH);
    data.forEach((v, i) => ctx.lineTo(x(i), y(v)));
    ctx.lineTo(x(data.length - 1), cssH);
    ctx.closePath();
    ctx.fill();

    // Line
    ctx.strokeStyle = '#00ff9f';
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    data.forEach((v, i) => i === 0 ? ctx.moveTo(x(i), y(v)) : ctx.lineTo(x(i), y(v)));
    ctx.stroke();

    // Dot at end
    ctx.fillStyle = '#00ff9f';
    ctx.beginPath();
    ctx.arc(x(data.length - 1), y(data[data.length - 1]), 3, 0, Math.PI * 2);
    ctx.fill();

    // Current value label
    ctx.fillStyle = '#f0f0f0';
    ctx.font = 'bold 9px JetBrains Mono';
    ctx.textAlign = 'right';
    ctx.fillText(data[data.length - 1].toFixed(4) + '%', cssW - pad.right, pad.top + 8);

    // Axis labels
    ctx.fillStyle = 'rgba(255,255,255,0.25)';
    ctx.font = '7px JetBrains Mono';
    ctx.textAlign = 'left';
    ctx.fillText('share ' + labels[0], pad.left, cssH - 2);
    ctx.textAlign = 'right';
    ctx.fillText('share ' + labels[labels.length - 1], cssW - pad.right, cssH - 2);
  }

  function renderLiveCalc(liveCalc) {
    if (!liveCalc || !dom.lcTimeBig) return;
    const latest = liveCalc.latest;
    const totals = liveCalc.session_totals || {};
    const ticker = liveCalc.ticker || [];
    const chartsData = liveCalc.charts_data || {};
    const cumTimeline = chartsData.cumulative_timeline || [];
    const consistency = chartsData.consistency_check || {};

    // Latest share info
    if (latest && latest.ts) {
      const d = new Date(latest.ts * 1000);
      const ts = String(d.getHours()).padStart(2,'0')+':'+String(d.getMinutes()).padStart(2,'0')+':'+String(d.getSeconds()).padStart(2,'0');
      if (dom.lcTimeBig) dom.lcTimeBig.textContent = ts;
      if (dom.lcSessionShareCount) dom.lcSessionShareCount.textContent = 'session share #' + (totals.shares_so_far || '\u2014');
      if (dom.lcShareDiff) dom.lcShareDiff.textContent = latest.share_diff_str || '\u2014';
      if (dom.lcHashes) dom.lcHashes.textContent = latest.hashes_attempted_str || '\u2014';
      if (dom.lcTimeObs) dom.lcTimeObs.textContent = latest.gap ? Number(latest.gap).toFixed(1) + 's' : '\u2014';
      if (dom.lcPBlock) dom.lcPBlock.textContent = latest.p_block_this_share_pct_str || '\u2014';
      if (dom.lcInstHr) dom.lcInstHr.textContent = latest.instantaneous_hr_str || '\u2014';
    }

    // Session totals
    if (dom.lcSessionShares) dom.lcSessionShares.textContent = totals.shares_so_far != null ? totals.shares_so_far : '\u2014';
    if (dom.lcAvgShareDiff) dom.lcAvgShareDiff.textContent = totals.avg_share_diff_str || '\u2014';
    if (dom.lcCumP) dom.lcCumP.textContent = totals.cum_p_block_pct_str || '\u2014';
    if (dom.lcExpectedBlocks) dom.lcExpectedBlocks.textContent = totals.expected_blocks_str || '\u2014';

    // Consistency badge
    if (dom.lcConsistencyBadge && consistency.status) {
      const badgeCls = consistency.status === 'CONSISTENT' ? 'badge--green' : 'badge--red';
      dom.lcConsistencyBadge.textContent = consistency.status;
      dom.lcConsistencyBadge.className = 'badge ' + badgeCls;
      dom.lcConsistencyBadge.title = (consistency.checks || []).map(c => c.check + ': ' + c.status).join('; ');
    }

    // Ticker list (compact text version)
    if (dom.lcTickerList) {
      if (ticker.length) {
        dom.lcTickerList.innerHTML = ticker.slice().reverse().map(s => {
          const d = new Date((s.ts || 0) * 1000);
          const ts = String(d.getHours()).padStart(2,'0')+':'+String(d.getMinutes()).padStart(2,'0')+':'+String(d.getSeconds()).padStart(2,'0');
          return '<div class="lc-ticker__row"><span class="lc-ticker__ts">' + ts + '</span><span class="lc-ticker__diff">' + (s.share_diff_str || '\u2014') + '</span><span class="lc-ticker__p">' + (s.p_block_this_share_pct_str || '\u2014') + '</span><span class="lc-ticker__hr">' + (s.instantaneous_hr_str || '\u2014') + '</span></div>';
        }).join('');
      } else {
        dom.lcTickerList.innerHTML = '<div class="lc-ticker__empty">awaiting share detection</div>';
      }
    }
    if (dom.lcTickerCount) dom.lcTickerCount.textContent = ticker.length + ' shares';

    // ── Charts (deferred to next frame for layout) ──
    requestAnimationFrame(() => {
      // Share diff sparkline
      if (ticker.length >= 2) {
        const diffData = ticker.map(s => s.share_diff_raw || 0);
        _drawLcSparkline(dom.lcChartDiff, diffData, 'rgb(6,214,240)', 'share diff');

        const pBlockData = ticker.map(s => (s.p_block_this_share || 0) * 100);
        _drawLcSparkline(dom.lcChartPBlock, pBlockData, 'rgb(247,147,26)', 'P(block) %');

        const hrData = ticker.map(s => (s.instantaneous_hr_hps || 0) / 1e12);
        _drawLcSparkline(dom.lcChartHr, hrData, 'rgb(16,185,129)', 'TH/s');
      }

      // Cumulative P(block) chart
      if (cumTimeline.length >= 2) {
        _drawLcCumulativeChart(dom.lcChartCumulative, cumTimeline, '#00ff9f');
      }
    });
  }


  // ══════════════════════════════════════════════════════════════════════
  // API STATUS BADGES — LIVE / ESTIMATED / ERROR
  // ══════════════════════════════════════════════════════════════════════

  function _updateApiStatusBadges(snap) {
    const set = (id, status) => {
      const el = document.getElementById(id);
      if (!el) return;
      el.textContent = status;
      el.classList.remove('badge--live', 'badge--estimated', 'badge--error'); el.classList.add('badge--' + status.toLowerCase());
    };

    // paraspace API — worker, pool, account, leaderboard, events, proximity, livecalc, livemining
    const workerOk = !!(snap.worker && (snap.worker.hashrate || snap.worker.bestDifficulty));
    const poolOk = !!(snap.pool && snap.pool.hashrate);
    set('api-worker', workerOk ? 'LIVE' : 'ERROR');
    set('api-pool', poolOk ? 'LIVE' : 'ERROR');
    set('api-proximity', snap.proximity && !snap.proximity.insufficient_data ? 'LIVE' : 'ESTIMATED');
    set('api-livecalc', snap.proximity?.live_calc?.latest ? 'LIVE' : 'ESTIMATED');
    set('api-livemining', (snap.all_workers && snap.all_workers.length > 0) ? 'LIVE' : 'ERROR');
    set('api-worker-details', (snap.all_workers && snap.all_workers.length > 0 && snap.all_workers[0].rejectionRatePct != null) ? 'ESTIMATED' : 'ERROR');

    // mempool.space + blockchain.info — network height, difficulty, hashrate
    const netOk = !!(snap.network && snap.network.difficulty);
    set('api-network', netOk ? 'LIVE' : 'ERROR');

    // mempool.space fees
    const feesOk = !!(snap.mempool_fees && Object.keys(snap.mempool_fees).length > 0);
    set('api-fees', feesOk ? 'LIVE' : 'ERROR');

    // CoinGecko BTC price
    const btcOk = !!(snap.btc_price && (snap.btc_price.usd || snap.btc_price.brl));
    // Network panel also shows BTC price — update if network is live but price might not be
    if (!btcOk && netOk) set('api-network', 'ESTIMATED');

    // Profitability — derived from all above, always ESTIMATED (formulas, not raw API)
    set('api-profit', workerOk && netOk ? 'ESTIMATED' : 'ERROR');

    // CFO Monte Carlo — always simulated
    set('api-cfo', 'ESTIMATED');
  }


  // ── Profitability mode state ──
  let _profitMode = 'pool';

  function setProfitMode(mode) {
    _profitMode = mode;
    // Toggle button active state
    document.querySelectorAll('.profit-mode-btn').forEach(btn => {
      btn.classList.toggle('active', btn.dataset.mode === mode);
    });
    // Toggle solo extra stats visibility
    const soloExtra = document.getElementById('solo-extra-stats');
    if (soloExtra) soloExtra.style.display = mode === 'solo' ? 'flex' : 'none';
    // Skip re-fetch: re-render from existing snapshot
    if (window.__lastProfitability) renderProfitability(window.__lastProfitability);
  }

  function renderProfitability(p) {
    if (!p || !Object.keys(p).length) return;
    window.__lastProfitability = p;
    const cur = (SETTINGS_CACHE.data?.active_currency?.value) || 'USD';
    const symMap = {USD:'$',BRL:'R$',EUR:'€',GBP:'£'}; const sym = symMap[cur] || '$';
    const fiatPerCur = (b) => b != null ? `${sym}${Number(b).toLocaleString(undefined,{maximumFractionDigits:2})}` : '\u2014';

    // ── Data for all 3 modes ──
    const pool = {
      netBtc: p.net_btc_per_day_pool,
      fiatDay: (p.fiat_per_day_pool || {})[cur],
      fiatWeek: (p.fiat_per_week_pool || {})[cur],
      fiatMonth: (p.fiat_per_month_pool || {})[cur],
      netUsdDay: p.pool_net_usd_per_day,
      netUsdMonth: p.pool_net_usd_per_month,
    };
    const soloDefined = p.net_btc_per_day_solo != null;
    const solo = {
      netBtc: p.net_btc_per_day_solo,
      fiatDay: (p.fiat_per_day_solo || {})[cur],
      fiatMonth: null, // not computed server-side; use day*30
      pDay: p.solo_p_day_pct,
      pYear: p.solo_p_year_pct,
      p5y: p.solo_p_5year_pct,
      expectedBlocks: p.solo_expected_blocks_per_year,
      expectedTime: p.solo_expected_time_to_block_days,
    };
    const rentalDefined = p.net_btc_per_day_rental != null;
    const rental = {
      netBtc: p.net_btc_per_day_rental,
      fiatDay: (p.fiat_per_day_rental || {})[cur],
      fiatMonth: null,
      rentalGrossBtc: p.rental_net_btc_per_day,
      rentalNetUsdDay: p.rental_net_usd_per_day,
      rentalNetUsdMonth: p.rental_net_usd_per_month,
    };
    const breakEven = p.break_even_rental_usd_per_th_day;
    const costUsd = p.cost_per_day_usd;
    const sharePct = p.share_of_network_pct;
    const riskComp = p.risk_comparison;

    // ── Share of network badge ──
    if (dom.profitShareBadge) {
      dom.profitShareBadge.textContent = sharePct != null ? sharePct.toFixed(6) + '% of network' : '—%';
    }

    // ── Cost badge ──
    if (dom.profitCostBadge) {
      dom.profitCostBadge.textContent = costUsd != null && costUsd > 0 ? `cost: $${costUsd.toFixed(2)}/d` : 'cost: $0.00/d';
    }

    // ── Pick data by active mode ──
    let activeData, activeLabel, activeVariance, activeRisk;
    if (_profitMode === 'solo' && soloDefined) {
      activeData = solo;
      activeLabel = '☀ SOLO · no pool fee';
      activeVariance = 'EXTREME — lottery-like';
      activeRisk = riskComp?.solo?.risk_score || 10;
    } else if (_profitMode === 'rental' && rentalDefined) {
      activeData = rental;
      activeLabel = '📦 RENTAL · after rental cost';
      activeVariance = 'MODERATE — pool + price risk';
      activeRisk = riskComp?.rental?.risk_score || 6;
    } else {
      // Default: pool mode
      activeData = pool;
      activeLabel = '⛏ POOL · after fee & orphan';
      activeVariance = 'LOW — steady daily BTC';
      activeRisk = riskComp?.pool?.risk_score || 2;
    }

    // ── NET BTC / DAY ──
    if (dom.pBtcDay) {
      dom.pBtcDay.textContent = activeData.netBtc != null ? `${Number(activeData.netBtc).toFixed(8)} BTC` : '\u2014';
    }
    if (dom.pBtcSub) dom.pBtcSub.textContent = activeLabel;

    // ── FIAT / DAY · FIAT / WEEK ──
    if (dom.pFiatDay) dom.pFiatDay.textContent = fiatPerCur(activeData.fiatDay);
    if (dom.pFiatDayWeek) {
      const weekVal = activeData.fiatDay != null ? activeData.fiatDay * 7 : null;
      dom.pFiatDayWeek.textContent = weekVal ? `~ ${fiatPerCur(weekVal)} / week` : '\u2014';
    }

    // ── FIAT / MONTH ──
    if (dom.pFiatMonth) dom.pFiatMonth.textContent = fiatPerCur(activeData.fiatMonth != null ? activeData.fiatMonth : (activeData.fiatDay != null ? activeData.fiatDay * 30 : null));
    if (dom.pFiatMonthSub) {
      const netUsd = activeData.netUsdDay != null ? activeData.netUsdDay : activeData.rentalNetUsdDay;
      dom.pFiatMonthSub.textContent = netUsd != null ? (netUsd >= 0 ? 'net profit' : 'net loss') : 'net of cost';
    }

    // ── BREAK-EVEN ──
    if (dom.pBreakeven) {
      dom.pBreakeven.textContent = breakEven != null ? `$${breakEven.toFixed(4)}` : '\u2014';
    }
    if (dom.pBreakevenSub) {
      dom.pBreakevenSub.textContent = breakEven != null ? 'rental $/TH·d break-even' : 'set cost in ⚙ Settings';
    }

    // ── FOOTNOTE ──
    if (dom.profitFootnote) {
      const costInfo = p.cost_label || 'none';
      const modeInfo = riskComp ? Object.values(riskComp).map(m => `${m.label} risk ${m.risk_score}/10`).join(' · ') : '';
      dom.profitFootnote.textContent = `Mode: ${activeLabel} · Risk: ${activeRisk}/10 · Cost: ${costInfo}${modeInfo ? ' · ' + modeInfo : ''}`;
    }

    // ── SOLO EXTRA STATS ──
    const updateSolo = (id, val, suffix) => {
      const el = document.getElementById(id);
      if (el) el.textContent = val != null ? val + (suffix || '') : '\u2014';
    };
    updateSolo('solo-p-day', p.solo_p_day_pct != null ? Number(p.solo_p_day_pct).toExponential(4) : null, '%');
    updateSolo('solo-p-year', p.solo_p_year_pct != null ? Number(p.solo_p_year_pct).toFixed(4) : null, '%');
    updateSolo('solo-p-5y', p.solo_p_5year_pct != null ? Number(p.solo_p_5year_pct).toFixed(2) : null, '%');
    updateSolo('solo-expected-blocks', p.solo_expected_blocks_per_year != null ? Number(p.solo_expected_blocks_per_year).toFixed(4) : null, '');
    updateSolo('solo-expected-time', p.solo_expected_time_to_block_days != null ? Math.round(Number(p.solo_expected_time_to_block_days)).toLocaleString() : null, ' days');

    // ── FIAT CURRENCY ROW — update all currencies ──
    if (dom.profitFiatRow) {
      const modeKey = _profitMode === 'solo' ? 'fiat_per_day_solo' : (_profitMode === 'rental' ? 'fiat_per_day_rental' : 'fiat_per_day_pool');
      const fiatData = p[modeKey] || {};
      dom.profitFiatRow.querySelectorAll('.profit-fiat-cell').forEach(cell => {
        const curCode = cell.dataset.cur;
        const valEl = cell.querySelector('.val');
        if (valEl) {
          const v = fiatData[curCode];
          const rowSym = symMap[curCode] || '$';
          valEl.textContent = v != null ? `${rowSym}${Number(v).toLocaleString(undefined,{maximumFractionDigits:2})}` : '\u2014';
        }
      });
    }

    // ── Curr badge ──
    if (dom.pCurBadge) dom.pCurBadge.textContent = cur;

    // ── API STATUS ──
    const apiEl = document.getElementById('api-profit');
    if (apiEl && costUsd != null && (p.net_btc_per_day_pool != null || soloDefined)) {
      apiEl.textContent = 'ESTIMATED';
      apiEl.className = 'badge api-status badge--estimated';
    } else if (apiEl) {
      apiEl.textContent = 'ERROR';
      apiEl.className = 'badge api-status badge--error';
    }
  }

  // ══════════════════════════════════════════════════════════════════
  //  CFO · RISK-ADJUSTED COMPARISON — 3 modes side-by-side
  // ══════════════════════════════════════════════════════════════════
  function renderCfoPanel(p) {
    if (!p || !p.risk_comparison) {
      const set = (id, v) => { const el = document.getElementById(id); if (el) el.textContent = v || '\u2014'; };
      ['cforisk-pool-risk','cforisk-solo-risk','cforisk-rental-risk'].forEach(id => set(id, '—'));
      ['cforisk-pool-btc','cforisk-solo-btc','cforisk-rental-btc'].forEach(id => set(id, '—'));
      ['cforisk-pool-usd','cforisk-solo-usd','cforisk-rental-usd'].forEach(id => set(id, '—'));
      ['cforisk-pool-cv','cforisk-solo-cv','cforisk-rental-cv'].forEach(id => set(id, '—'));
      const apiEl = document.getElementById('api-cfo-risk');
      if (apiEl) { apiEl.textContent = 'NO DATA'; apiEl.className = 'badge api-status badge--error'; }
      return;
    }
    const rc = p.risk_comparison;
    const modes = ['pool','solo','rental'];
    const apiEl = document.getElementById('api-cfo-risk');
    if (apiEl) { apiEl.textContent = 'LIVE'; apiEl.className = 'badge api-status badge--live'; }

    for (const mode of modes) {
      const m = rc[mode];
      if (!m) continue;
      const set = (id, v) => { const el = document.getElementById(id); if (el) el.textContent = v != null ? String(v) : '\u2014'; };
      set('cforisk-' + mode + '-risk', m.risk_score + '/10');
      set('cforisk-' + mode + '-btc', m.net_btc_daily != null ? m.net_btc_daily + ' BTC' : '—');
      set('cforisk-' + mode + '-usd', m.net_usd_daily != null ? '$' + Number(m.net_usd_daily).toLocaleString() : '—');
      set('cforisk-' + mode + '-cv', m.cv || '—');
      set('cforisk-' + mode + '-variance', m.variance || '—');
      set('cforisk-' + mode + '-bestfor', m.best_for || '—');

      // Color the risk badge based on score
      const badge = document.getElementById('cforisk-' + mode + '-risk');
      if (badge && m.risk_score != null) {
        const score = Number(m.risk_score);
        badge.className = 'cforisk-card__badge cforisk-badge';
        if (score <= 3) badge.classList.add('cforisk-badge--low');
        else if (score <= 6) badge.classList.add('cforisk-badge--mid');
        else badge.classList.add('cforisk-badge--crit');
      }
    }
  }

  function renderMilestones(list) {
    if (!dom.badgesStrip) return;
    if (!list || !list.length) { dom.badgesStrip.innerHTML = '<div class="empty">awaiting data</div>'; return; }
    dom.badgesStrip.innerHTML = list.map(m => `<div class="badge-card"><div class="badge-card__tier">${m.tier}</div><div class="badge-card__label">${escapeHtml(m.label)}</div></div>`).join('');
  }

  // ── Main render ──
  let prevSnapshot = null;
  function render(snap) {
    // Expose live snapshot values for downstream consumers (e.g. loadMonteCarlo)
    window.__lastSnapshotHr = (snap.worker && snap.worker.hashrate) ? Number(snap.worker.hashrate) : 0;
    window.__lastSnapshotDiff = (snap.network && snap.network.difficulty) ? Number(snap.network.difficulty) : 0;
    _updateApiStatusBadges(snap);
    if (!_skeletonsHidden) hideSkeletons();
    if (dom.topbarAddress) dom.topbarAddress.textContent = `${fmt.shortAddr(window.BTC_ADDRESS || '')} · WORKER ${(window.WORKER_NAME || '').toUpperCase()}`;
    if (dom.statusText) dom.statusText.textContent = snap.worker ? 'ONLINE' : 'OFFLINE';
    dom.statusPill.classList.toggle('is-online', !!snap.worker);
    _updateEmptyState();
    renderHero(snap);
    renderPool(snap.pool);
    renderNetwork(snap.network);
    renderAccount(snap.account);
    renderBtcPrices(snap.btc_price);
    renderHalving(snap.halving);
    renderMempoolFees(snap.mempool_fees);
    renderProfitability(snap.profitability);
    renderCfoPanel(snap.profitability);
    renderProximity(snap.proximity);
    renderLiveCalc(snap.proximity?.live_calc);
    renderNetworkGauge(snap);
    renderMilestones(snap.milestones);
    renderAlerts(snap.alerts_recent);
    renderEvents(snap.highest_diffs);
    renderLeaderboard(snap.leaderboard_table_top_30);
    renderTimelineFeed(snap.timeline_recent);
    renderLiveMining(snap.all_workers, snap.worker);
    renderWorkerDetails(snap.all_workers);
    _updateHashSearchState(snap.worker, snap.network);
    _huntUpdateState(snap.worker, snap.network, parseFloat(snap.proximity?.live_calc?.session_totals?.cum_p_block_pct_str) || 0, parseFloat(snap.proximity?.live_calc?.session_totals?.expected_blocks) || 0, snap.proximity?.live_calc?.ticker || []);
    prevSnapshot = snap;
  }

  // ══════════════════════════════════════════════════════════════════════
  // CHARTS
  // ══════════════════════════════════════════════════════════════════════
  const charts = {};
  function makeChart(id, label, color) {
    const canvas = document.getElementById(id);
    if (!canvas) return null;
    const ctx = canvas.getContext('2d');
    return new Chart(ctx, {
      type: 'line',
      data: { labels: [], datasets: [{ label, data: [], borderColor: color, backgroundColor: color.replace(')', ',0.1)').replace('rgb','rgba'), fill: true, tension: 0.4, pointRadius: 0 }] },
      options: { responsive: true, maintainAspectRatio: false, scales: { x: { ticks: { color: '#5E5952', maxTicksLimit: 8 } }, y: { ticks: { color: '#5E5952' } } }, plugins: { legend: { display: false } } }
    });
  }

  async function loadChart(id, metric, range) {
    try {
      const r = await fetch(`/api/history?metric=${metric}&range=${range}`);
      if (!r.ok) return;
      const data = await r.json();
      const chart = charts[id];
      if (!chart) return;
      chart.data.labels = (data.history || []).map(p => new Date(p.ts * 1000).toLocaleTimeString());
      chart.data.datasets[0].data = (data.history || []).map(p => p.value);
      chart.update();
    } catch (e) { console.error('chart load', e); }
  }

  function initCharts() {
    charts['chart-hashrate'] = makeChart('chart-hashrate', 'Hashrate', 'rgb(247,147,26)');
    charts['chart-pool'] = makeChart('chart-pool', 'Pool HR', 'rgb(6,214,240)');
    charts['chart-bestdiff'] = makeChart('chart-bestdiff', 'Best Diff', 'rgb(16,185,129)');
    charts['chart-net'] = makeChart('chart-net', 'Net Diff', 'rgb(139,92,246)');
  }

  function bindChartRanges() {
    document.querySelectorAll('.chart-range').forEach(row => {
      const target = row.dataset.target;
      row.querySelectorAll('button').forEach(btn => {
        btn.addEventListener('click', () => {
          row.querySelectorAll('button').forEach(b => b.classList.remove('active'));
          btn.classList.add('active');
          const metricMap = { 'chart-hashrate': 'worker_hashrate', 'chart-pool': 'pool_hashrate', 'chart-bestdiff': 'worker_best_diff', 'chart-net': 'network_difficulty' };
          loadChart(target, metricMap[target] || target.replace('chart-',''), btn.dataset.range);
        });
      });
    });
  }

  // ── Matrix Rain ──
  let _matrixRafId = null;
  function initMatrix() {
    const c = document.getElementById('matrix-canvas'); if (!c) return;
    _matrixRunning = true;
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
  async function loadSettings() {
    try { const r = await fetch('/api/settings'); SETTINGS_CACHE.data = (await r.json()).settings.reduce((acc, s) => { acc[s.key] = s; return acc; }, {}); } catch (e) {}
  }
  function openSettingsModal() { dom.settingsModal?.classList.remove('modal--hidden'); }
  function closeSettingsModal() { dom.settingsModal?.classList.add('modal--hidden'); }
  dom.settingsModal?.addEventListener('click', (e) => { if (e.target.matches('[data-close]')) closeSettingsModal(); });
  dom.openSettings?.addEventListener('click', openSettingsModal);
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
      const ok = result.applied && result.applied.length > 0;
      const status = document.getElementById('settings-status');
      if (status) {
        status.textContent = ok ? 'SAVED (' + result.applied.length + ')' : 'ERROR';
        status.className = ok ? 'badge badge--green' : 'badge badge--red';
        setTimeout(() => { if (status) status.textContent = ''; }, 2000);
      }
      if (ok) setTimeout(() => closeSettingsModal(), 800);
    } catch (e) {
      const status = document.getElementById('settings-status');
      if (status) { status.textContent = 'NETWORK ERROR'; status.className = 'badge badge--red'; }
    }
  });

  // ── Export ──
  function openExportModal() { dom.exportModal?.classList.remove('modal--hidden'); }
  function closeExportModal() { dom.exportModal?.classList.add('modal--hidden'); }
  dom.exportModal?.addEventListener('click', (e) => { if (e.target.matches('[data-close]')) closeExportModal(); });
  dom.openExports?.addEventListener('click', openExportModal);

  // ── Wallet Connection ──
  // Xverse wallet provider detection
  function getXverseProvider() {
    if (typeof window.BitcoinProvider !== 'undefined') return window.BitcoinProvider;
    if (typeof window.btc !== 'undefined' && window.btc?.request) return window.btc;
    if (typeof window.ethereum !== 'undefined' && window.ethereum?.isXverse) return window.ethereum;
    return null;
  }

  async function connectXverse() {
    const provider = getXverseProvider();
    if (!provider) {
      _logMiningEvent('WALLET', 'Xverse not detected — install from xverse.app');
      document.getElementById('wallet-connect-xverse').textContent = '✕ NOT DETECTED';
      setTimeout(() => { document.getElementById('wallet-connect-xverse').innerHTML = '<span class="wallet-btn__icon">◆</span> XVERSE'; }, 3000);
      return;
    }
    try {
      // Xverse getAddresses
      const addrs = await provider.request('getAddresses', { purposes: ['ordinals', 'payment'] });
      const btcAddr = addrs?.result?.addresses?.find(a => a.address?.startsWith('bc1') || a.address?.startsWith('1'))?.address
                    || addrs?.addresses?.[0]?.address
                    || addrs?.[0]?.address;
      if (btcAddr) {
        _setWalletAddress(btcAddr, 'xverse');
      }
    } catch (e) {
      _logMiningEvent('WALLET', 'Xverse connection failed: ' + e.message);
    }
  }

  function _setWalletAddress(addr, source) {
    if (!addr || addr.length < 10) return;
    window.BTC_ADDRESS = addr;
    window._userConnectedWallet = true;
    localStorage.setItem('cypher65_wallet', JSON.stringify({ address: addr, source }));
    document.getElementById('wallet-banner').style.display = 'none';
    const dcBtn = document.getElementById('disconnect-wallet');
    if (dcBtn) dcBtn.style.display = '';
    _updateEmptyState();
    _logMiningEvent('WALLET', 'Connected: ' + fmt.shortAddr(addr) + ' (' + source + ')');
    // Refresh the server with new address, then trigger immediate poll
    fetch('/api/set-address', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ address: addr }),
    }).then(() => { fetchSnapshot(); }).catch(() => {});
  }

  function _checkSavedWallet() {
    try {
      const saved = localStorage.getItem('cypher65_wallet');
      if (saved) {
        const { address, source } = JSON.parse(saved);
        if (address && address.length >= 10) {
          window.BTC_ADDRESS = address;
          window._userConnectedWallet = true;
          document.getElementById('wallet-banner').style.display = 'none';
          const dcBtn = document.getElementById('disconnect-wallet');
          if (dcBtn) dcBtn.style.display = '';
          _logMiningEvent('WALLET', 'Restored: ' + fmt.shortAddr(address) + ' (' + (source || 'saved') + ')');
        }
      }
    } catch (e) {}
  }

  // Wallet UI events
  document.getElementById('wallet-connect-xverse')?.addEventListener('click', connectXverse);
  document.getElementById('wallet-connect-manual')?.addEventListener('click', () => {
    document.getElementById('wallet-modal')?.classList.remove('modal--hidden');
  });
  document.getElementById('wallet-address-confirm')?.addEventListener('click', () => {
    const input = document.getElementById('wallet-address-input');
    if (!input) return;
    const addr = input.value.trim();
    if (addr.length >= 10 && (addr.startsWith('bc1') || addr.startsWith('1') || addr.startsWith('3') || addr.startsWith('tb1') || addr.startsWith('2'))) {
      _setWalletAddress(addr, 'manual');
      document.getElementById('wallet-modal')?.classList.add('modal--hidden');
    } else {
      document.getElementById('wallet-input-hint').textContent = 'Invalid Bitcoin address — must start with bc1, 1, or 3';
      document.getElementById('wallet-input-hint').style.color = '#ff6b6b';
    }
  });
  // Validate address input as user types (basic prefix check)
  document.getElementById('wallet-address-input')?.addEventListener('input', (e) => {
    const hint = document.getElementById('wallet-input-hint');
    if (hint) {
      hint.textContent = 'Paste your mining wallet address to view workers and stats';
      hint.style.color = '';
    }
  });

  // ── Disconnect Wallet ──
  function _disconnectWallet() {
    if (!window.BTC_ADDRESS) return;
    if (!confirm('Desconectar carteira? Os dados do dashboard serão limpos.')) return;
    window.BTC_ADDRESS = null;
    window._userConnectedWallet = false;
    localStorage.removeItem('cypher65_wallet');
    if (dom.topbarAddress) dom.topbarAddress.textContent = '—';
    const banner = document.getElementById('wallet-banner');
    if (banner) banner.style.display = '';
    const dcBtn = document.getElementById('disconnect-wallet');
    if (dcBtn) dcBtn.style.display = 'none';
    _updateEmptyState();
    fetch('/api/set-address', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ address: '' }) }).catch(() => {}).finally(() => { fetchSnapshot(); });
    logMessage('WALLET', 'disconnected — session reset');
  }

  document.getElementById('disconnect-wallet')?.addEventListener('click', _disconnectWallet);

  // ── Opportunity Engine Popup ──
  // ── _oppShown with localStorage persistence ──
  const _OPP_LS_KEY = 'cypher_oppShown';
  function _loadOppShown() {
    try {
      const raw = localStorage.getItem(_OPP_LS_KEY);
      if (raw) {
        const obj = JSON.parse(raw);
        // Prune entries older than 7 days to keep localStorage lean
        const cutoff = Date.now() - 7 * 86400 * 1000;
        for (const k of Object.keys(obj)) {
          if (obj[k] < cutoff) delete obj[k];
        }
        return obj;
      }
    } catch (_) { /* ignore corrupt data */ }
    return {};
  }
  function _saveOppShown() {
    try { localStorage.setItem(_OPP_LS_KEY, JSON.stringify(_oppShown)); } catch (_) { /* quota exceeded */ }
  }
  let _oppShown = _loadOppShown(); // dedup by id, persisted across refresh
  async function _checkOpportunities() {
    try {
      const r = await fetch('/api/opportunities');
      if (!r.ok) return;
      const data = await r.json();
      const opps = data.opportunities || [];
      if (!opps.length) {
        document.getElementById('opp-popup').style.display = 'none';
        return;
      }
      // Show best opportunity
      const best = opps[0];
      const isObsolete = best.status === 'OBSOLETE';
      if (!_oppShown[best.id]) {
        _oppShown[best.id] = Date.now();
        _saveOppShown();
        const body = document.getElementById('opp-popup-body');
        if (body) {
          const statusBadge = isObsolete
            ? '<span class="badge badge--obsolete opp-popup__status">OBSOLETE</span>'
            : '<span class="badge badge--live opp-popup__status">LIVE</span>';
          body.innerHTML = statusBadge
            + '<div class="opp-popup__headline">' + escapeHtml(best.title || '') + '</div>'
            + '<div class="opp-popup__desc">' + escapeHtml(best.description || '') + '</div>'
            + '<div class="opp-popup__meta">' + escapeHtml(best.meta || '') + '</div>';
        }
        document.getElementById('opp-popup').style.display = 'block';
        // Auto-hide after 15s for live; 8s for obsolete (less intrusive)
        const hideMs = isObsolete ? 8000 : 15000;
        setTimeout(() => { document.getElementById('opp-popup').style.display = 'none'; }, hideMs);
      }
    } catch (e) { /* silent */ }
  }
  document.getElementById('opp-popup-close')?.addEventListener('click', () => {
    document.getElementById('opp-popup').style.display = 'none';
  });

  // ── Keyboard shortcuts ──
  document.addEventListener('keydown', (e) => {
    if (e.key.toLowerCase() === 'r' && !document.querySelector('.modal:not(.modal--hidden)') && document.activeElement.tagName !== 'INPUT' && !e.metaKey && !e.ctrlKey) fetchSnapshot();
    else if (e.key === 'Escape') { closeSettingsModal(); closeExportModal(); document.getElementById('opp-popup').style.display = 'none'; }
  });

  // ══════════════════════════════════════════════════════════════════════
  // CYPHER // LIVE MINING — Summary, Best Share, Event Log
  // ══════════════════════════════════════════════════════════════════════  let _lmLastWorkerCount = -1; let _lmBestShareEver = 0; let _lmBestShareWorker = ''; let _lmBestShareTime = '';
  let _lmEventCount = 0; const _LM_EVENT_MAX = 50;
  // Track last-seen share ts and best-diff string to fire REAL events at the log terminal
  let _lmPrimed = false;  // first-poll guard: capture baseline without firing events
  let _lmLastSubmitTs = 0;
  let _lmLastBestDiffStr = '';

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

  // ══════════════════════════════════════════════════════════════════════
  // WORKER DETAILS — deep monitoring: rejection rate, temperature, hw errors
  // ══════════════════════════════════════════════════════════════════════
  function renderWorkerDetails(allWorkers) {
    const grid = document.getElementById('wd-grid');
    if (!grid) return;
    const workers = allWorkers || [];
    if (!workers.length) {
      grid.innerHTML = '<div class="wd-empty">Connect wallet and await share data for deep worker metrics.</div>';
      return;
    }
    const badge = document.getElementById('api-worker-details');
    if (badge) { badge.textContent = 'ESTIMATED'; badge.className = 'badge badge--estimated'; }
    const html = workers.map((w, i) => {
      const hr = Number(w.hashrate || 0);
      const bestDiffStr = w.bestDifficulty ? fmt.diff(w.bestDifficulty) : '—';
      const now_sec = Date.now() / 1000;
      const is_recent = w.lastSubmission && (now_sec - Number(w.lastSubmission)) < 3600;
      const state = w.state || (hr > 0 ? 'HASHING' : (is_recent ? 'ONLINE' : (w.lastSubmission ? 'STALE' : 'IDLE')));
      const stateCls = state === 'HASHING' ? 'wd-state--hashing' : state === 'ONLINE' ? 'wd-state--online' : 'wd-state--idle';
      const rejection = w.rejectionRatePct != null ? `<div class="wd-cell"><span class="wd-cell__label">REJECTION RATE</span><span class="wd-cell__val wd-cell__val--warn">${escapeHtml(w.rejectionRateLabel || '—')}</span><span class="wd-cell__formula">= (1 − best_diff_bumps / shares) × 100  ·  session-wide estimate</span></div>` : '';
      const temp = `<div class="wd-cell"><span class="wd-cell__label">TEMPERATURE</span><span class="wd-cell__val wd-cell__val--mute">${w.temperatureLabel || 'UNAVAILABLE'}</span><span class="wd-cell__formula">ASIC-level — pool API does not expose</span></div>`;
      const hw = `<div class="wd-cell"><span class="wd-cell__label">HARDWARE ERRORS</span><span class="wd-cell__val wd-cell__val--mute">${w.hardwareErrorsLabel || 'UNAVAILABLE'}</span><span class="wd-cell__formula">ASIC-level — pool API does not expose</span></div>`;
      const sph = w.sharesPerHour != null ? `<div class="wd-cell"><span class="wd-cell__label">SHARES/HOUR</span><span class="wd-cell__val">${w.sharesPerHour}</span></div>` : '';
      return `<div class="wd-card ${stateCls}">
        <div class="wd-card__head">
          <span class="wd-card__name">${escapeHtml(w.name || w.id || 'Worker ' + (i+1))}</span>
          <span class="wd-card__state">${state}</span>
        </div>
        <div class="wd-card__body">
          <div class="wd-cell"><span class="wd-cell__label">HASHRATE</span><span class="wd-cell__val">${fmt.hashrate(hr)}</span></div>
          <div class="wd-cell"><span class="wd-cell__label">BEST DIFFICULTY</span><span class="wd-cell__val wd-cell__val--gold">${bestDiffStr}</span></div>
          <div class="wd-cell"><span class="wd-cell__label">LAST SHARE</span><span class="wd-cell__val">${w.lastShareAgoLabel || (w.lastSubmission ? fmt.age(w.lastSubmission) : '—')}</span></div>
          <div class="wd-cell"><span class="wd-cell__label">UPTIME</span><span class="wd-cell__val">${w.uptime ? fmt.uptime(w.uptime) : '—'}</span></div>
          ${rejection}
          ${temp}
          ${hw}
          ${sph}
        </div>
      </div>`;
    }).join('');
    grid.innerHTML = html;
  }

  function renderLiveMining(allWorkers, primaryWorker) {
    if (!dom.lmGrid) return;
    const workers = allWorkers || [];
    if (!workers.length) { dom.lmGrid.innerHTML = '<div class="lm-empty">awaiting worker data</div>'; document.getElementById('api-livemining')?.classList.remove('badge--error','badge--estimated'); document.getElementById('api-livemining')?.classList.add('badge--live'); document.getElementById('api-livemining') && (document.getElementById('api-livemining').textContent = 'IDLE'); return; }
    document.getElementById('api-livemining')?.classList.remove('badge--error','badge--estimated'); document.getElementById('api-livemining')?.classList.add('badge--live'); document.getElementById('api-livemining') && (document.getElementById('api-livemining').textContent = 'LIVE');
    if (dom.lmWorkersBadge) dom.lmWorkersBadge.textContent = `${workers.length} worker${workers.length === 1 ? '' : 's'}`;    _updateLiveMiningSummary(workers, primaryWorker);
    _updateBestShare(workers);

    if (workers.length > 0 && workers.length !== _lmLastWorkerCount) {
      _lmLastWorkerCount = workers.length;
      _logMiningEvent('JOB', `${workers.length} worker${workers.length===1?'':'s'} active`);
    } else if (workers.length === 0 && _lmLastWorkerCount !== 0) {
      _lmLastWorkerCount = 0;
      _logMiningEvent('WARN', '0 workers online');
    }

    // ── REAL SHARE + BEST_DIFF event detection from pool API deltas ──
    // First-poll guard: capture baseline without firing false events
    if (primaryWorker && !_lmPrimed) {
      _lmLastSubmitTs = Number(primaryWorker.lastSubmission) || 0;
      _lmLastBestDiffStr = String(primaryWorker.bestDifficulty || '');
      _lmPrimed = true;
    } else if (primaryWorker) {
      const curSubmit = Number(primaryWorker.lastSubmission) || 0;
      if (curSubmit > 0 && curSubmit !== _lmLastSubmitTs) {
        _lmLastSubmitTs = curSubmit;
        _logMiningEvent('SHARE', `share validated by pool — last: ${fmt.age(curSubmit)}`);
      }
      const curBestDiff = String(primaryWorker.bestDifficulty || '');
      if (curBestDiff && curBestDiff !== _lmLastBestDiffStr) {
        _lmLastBestDiffStr = curBestDiff;
        _logMiningEvent('BEST', `best difficulty improved to ${fmt.diff(curBestDiff)}`);
      }
    }

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
      const source = s.source || 'CALCULATED';
      const sourceBadge = source === 'CALCULATED'
        ? '<span class="sc-source badge badge--live" title="Derived from pool API vardiff">CALC.</span>'
        : '<span class="sc-source badge badge--estimated" title="Estimated from bestDifficulty/2 when vardiff unavailable">EST.</span>';
      return `<div class="hunt-share-card${isNewest?' is-newest':''}">${sourceBadge}<span class="sc-lbl">TIME</span><span class="sc-val cyan">${ts}</span><span class="sc-lbl">DIFF</span><span class="sc-val">${s.share_diff_str||'\u2014'}</span><span class="sc-lbl">GAP</span><span class="sc-val green">${s.gap?Number(s.gap).toFixed(1)+'s':'\u2014'}</span><span class="sc-lbl">HASHRATE</span><span class="sc-val">${s.instantaneous_hr_str||'\u2014'}</span><div class="sc-bar"><div class="sc-bar-fill" style="width:${Math.min(100,(s.p_block_this_share||0)*100)}%"></div></div></div>`;
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

  function _soloTermPrint(text) {
    if (!_soloTerm.output) return;
    const lines = String(text).split('\n');
    for (const line of lines) {
      const div = document.createElement('div');
      div.className = 'solo-term__line';
      div.textContent = line;
      _soloTerm.output.appendChild(div);
    }
    _soloTerm.output.scrollTop = _soloTerm.output.scrollHeight;
  }

  function _soloTermPrintHTML(html) {
    if (!_soloTerm.output) return;
    const div = document.createElement('div');
    div.className = 'solo-term__line';
    div.innerHTML = html;
    _soloTerm.output.appendChild(div);
    _soloTerm.output.scrollTop = _soloTerm.output.scrollHeight;
  }

  async function _soloTermExecute(cmd) {
    if (_soloTerm.loading) return;
    _soloTerm.loading = true;

    // Echo command
    _soloTermPrintHTML('<span class="c-green">julio@cypher</span>:<span class="c-blue">~/solo-mining</span>$ <span class="c-white">' + escapeHtml(cmd) + '</span>');

    const parts = cmd.split(/\s+/);
    const verb = (parts[0] || '').toLowerCase();

    if (verb === 'clear' || verb === 'cls') {
      _soloTerm.output.innerHTML = '';
      _soloTermPrintHTML('<span class="c-muted">terminal cleared</span>');
      _soloTerm.loading = false;
      return;
    }

    if (verb === 'help' || verb === '--help' || verb === '-h') {
      _soloTermPrint('');
      _soloTermPrintHTML('<span class="c-amber">COMMANDS:</span>');
      _soloTermPrint('  calc --hashrate <value> --duration <h> [--difficulty <d>]');
      _soloTermPrint('       Calculate solo mining probabilities (auto-fetches live difficulty)');
      _soloTermPrint('');
      _soloTermPrint('  compare --budget <btc> --duration <h> [--braiins <price>] [--mrr <price>]');
      _soloTermPrint('          Compare Braiins vs MRR rental (auto-fetches live prices)');
      _soloTermPrint('');
      _soloTermPrint('  network');
      _soloTermPrint('          Show live Bitcoin network difficulty and BTC price (agent tools)');
      _soloTermPrint('');
      _soloTermPrint('  ask <free-text query>');
_soloTermPrint('          Natural language mining query (e.g. "what is the probability...")');
      _soloTermPrint('');
      _soloTermPrint('  clear');
      _soloTermPrint('          Clear terminal output');
      _soloTerm.loading = false;
      return;
    }

    if (verb === 'network') {
      _soloTermPrintHTML('<span class="c-muted">fetching live data from agent tools...</span>');
      try {
        const [diffRes, priceRes] = await Promise.all([
          fetch('/api/agents/solo-mining/tools', {
            method: 'POST', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({tool: 'get_network_difficulty'})
          }).then(r => r.json()),
          fetch('/api/agents/solo-mining/tools', {
            method: 'POST', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({tool: 'get_btc_price', params: {currencies: 'usd,brl'}})
          }).then(r => r.json())
        ]);

        _soloTermPrint('');
        _soloTermPrintHTML('<span class="c-green">[OK] Agent tools executed</span>');

        if (diffRes.difficulty) {
          _soloTermPrintHTML('<span class="c-cyan">─── Network Difficulty ───</span>');
          _soloTermPrint('  difficulty........ ' + fmt.diff(diffRes.difficulty));
          _soloTermPrint('  source............ ' + (diffRes.source || 'agent tool'));
        } else {
          _soloTermPrintHTML('<span class="c-red">[ERROR] Difficulty: ' + escapeHtml(diffRes.error || 'unavailable') + '</span>');
        }

        if (priceRes.prices) {
          _soloTermPrintHTML('<span class="c-cyan">─── BTC Price ───</span>');
          if (priceRes.prices.usd) _soloTermPrint('  btc/usd........... $' + Number(priceRes.prices.usd).toLocaleString());
          if (priceRes.prices.brl) _soloTermPrint('  btc/brl........... R$' + Number(priceRes.prices.brl).toLocaleString());
          _soloTermPrint('  source............ ' + (priceRes.source || 'coingecko.com'));
        } else {
          _soloTermPrintHTML('<span class="c-red">[ERROR] BTC price: ' + escapeHtml(priceRes.error || 'unavailable') + '</span>');
        }
      } catch (e) {
        _soloTermPrintHTML('<span class="c-red">[ERROR] Agent tools failed: ' + escapeHtml(e.message) + '</span>');
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
        _soloTermPrintHTML('<span class="c-red">[ERROR] Missing required flags. Usage: calc --hashrate <value> --duration <h></span>');
        _soloTerm.loading = false;
        return;
      }
      // If difficulty not provided, fetch live from agent tools
      if (!difficulty) {
        _soloTermPrintHTML('<span class="c-muted">fetching live difficulty from agent tools...</span>');
        try {
          const diffRes = await fetch('/api/agents/solo-mining/tools', {
            method: 'POST', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({tool: 'get_network_difficulty'})
          }).then(r => r.json());
          if (diffRes.difficulty) {
            difficulty = String(Math.round(diffRes.difficulty));
            _soloTermPrintHTML('<span class="c-muted">  using live difficulty: ' + fmt.diff(diffRes.difficulty) + ' (source: ' + (diffRes.source || 'agent tool') + ')</span>');
          } else {
            _soloTermPrintHTML('<span class="c-amber">[WARN] Could not fetch live difficulty — using default</span>');
          }
        } catch (e) {
          _soloTermPrintHTML('<span class="c-amber">[WARN] Failed to fetch difficulty: ' + escapeHtml(e.message) + '</span>');
        }
      }
      const params = new URLSearchParams({ hashrate: hashrate, duration: duration });
      if (difficulty) params.set('difficulty', difficulty);
      _soloTermPrintHTML('<span class="c-muted">running calculations...</span>');
      try {
        const r = await fetch('/api/solo-mining/calc?' + params.toString());
        const data = await r.json();
        if (data.error) {
          _soloTermPrintHTML('<span class="c-red">[ERROR] ' + escapeHtml(data.error) + '</span>');
          _soloTerm.loading = false;
          return;
        }
        _soloTermPrint('');
        const output = data.output || '';
        const lines = output.split('\n');
        for (const line of lines) {
          if (line.startsWith('[OK]')) _soloTermPrintHTML('<span class="c-green">' + escapeHtml(line) + '</span>');
          else if (line.startsWith('[WARN]')) _soloTermPrintHTML('<span class="c-amber">' + escapeHtml(line) + '</span>');
          else if (line.startsWith('[ERROR]')) _soloTermPrintHTML('<span class="c-red">' + escapeHtml(line) + '</span>');
          else _soloTermPrint(line);
        }
      } catch (e) {
        _soloTermPrintHTML('<span class="c-red">[ERROR] ' + escapeHtml(e.message) + '</span>');
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
        _soloTermPrintHTML('<span class="c-red">[ERROR] Missing required flags. Usage: compare --budget <btc> --duration <h> [--braiins <price>] [--mrr <price>]</span>');
        _soloTerm.loading = false;
        return;
      }
      // Fetch live prices from agent tools if not provided by user
      if (!braiins || !mrr) {
        _soloTermPrintHTML('<span class="c-muted">fetching live rental prices from agent tools...</span>');
        try {
          const promises = [];
          if (!braiins) promises.push(
            fetch('/api/agents/solo-mining/tools', {
              method: 'POST', headers: {'Content-Type': 'application/json'},
              body: JSON.stringify({tool: 'get_braiins_orderbook'})
            }).then(r => r.json()).catch(e => ({error: e.message}))
          );
          if (!mrr) promises.push(
            fetch('/api/agents/solo-mining/tools', {
              method: 'POST', headers: {'Content-Type': 'application/json'},
              body: JSON.stringify({tool: 'get_mrr_listings'})
            }).then(r => r.json()).catch(e => ({error: e.message}))
          );
          const results = await Promise.all(promises);
          // Shape-based detection — safer than positional indexing
          for (const r of results) {
            if (!r) continue;
            if (r.price_btc_per_ph_day != null && !braiins) {
              braiins = String(r.price_btc_per_ph_day);
              _soloTermPrintHTML('<span class="c-muted">  braiins: ' + Number(r.price_btc_per_ph_day).toFixed(8) + ' BTC/PH/day (' + (r.available_ph_s || 'N/A') + ' PH avail)</span>');
            } else if (r.best_price_btc_per_ph_day != null && !mrr) {
              mrr = String(r.best_price_btc_per_ph_day);
              _soloTermPrintHTML('<span class="c-muted">  mrr: ' + Number(r.best_price_btc_per_ph_day).toFixed(8) + ' BTC/PH/day (' + (r.available_listings || 'N/A') + ' listings)</span>');
            }
          }
          if (!braiins) {
            _soloTermPrintHTML('<span class="c-amber">[WARN] braiins price unavailable — no data in agent response</span>');
          }
          if (!mrr) {
            _soloTermPrintHTML('<span class="c-amber">[WARN] MRR price unavailable — no data in agent response</span>');
          }
        } catch (e) {
          _soloTermPrintHTML('<span class="c-amber">[WARN] Failed to fetch prices: ' + escapeHtml(e.message) + '</span>');
        }
      }
      const params = new URLSearchParams({ budget: budget, duration: duration, objective, auto_fetch: '1' });
      if (braiins) params.set('braiins_price', braiins);
      if (mrr) params.set('mrr_price', mrr);
      _soloTermPrintHTML('<span class="c-muted">comparing rental options...</span>');
      try {
        const r = await fetch('/api/solo-mining/compare?' + params.toString());
        const data = await r.json();
        if (data.error) {
          _soloTermPrintHTML('<span class="c-red">[ERROR] ' + escapeHtml(data.error) + '</span>');
          _soloTerm.loading = false;
          return;
        }
        _soloTermPrint('');
        const output = data.output || '';
        const lines = output.split('\n');
        for (const line of lines) {
          if (line.startsWith('[OK]')) _soloTermPrintHTML('<span class="c-green">' + escapeHtml(line) + '</span>');
          else if (line.startsWith('[WARN]')) _soloTermPrintHTML('<span class="c-amber">' + escapeHtml(line) + '</span>');
          else if (line.startsWith('[ERROR]')) _soloTermPrintHTML('<span class="c-red">' + escapeHtml(line) + '</span>');
          else _soloTermPrint(line);
        }
      } catch (e) {
        _soloTermPrintHTML('<span class="c-red">[ERROR] ' + escapeHtml(e.message) + '</span>');
      }
      _soloTerm.loading = false;
      return;
    }

    if (verb === 'ask' || verb === 'query') {
      const query = parts.slice(1).join(' ');
      if (!query) {
        _soloTermPrintHTML('<span class="c-red">[ERROR] Usage: ask <free-text query></span>');
        _soloTerm.loading = false;
        return;
      }
      _soloTermPrintHTML('<span class="c-muted">querying agent...</span>');
      try {
        const r = await fetch('/api/agents/solo-mining/ask', {
          method: 'POST', headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({query: query})
        });
        const data = await r.json();
        if (data.error) {
          _soloTermPrintHTML('<span class="c-red">[ERROR] ' + escapeHtml(data.error) + '</span>');
          _soloTerm.loading = false;
          return;
        }
        _soloTermPrint('');
        const output = data.output || '';
        const lines = output.split("\n");

        for (const line of lines) {
          if (line.startsWith('[OK]')) _soloTermPrintHTML('<span class="c-green">' + escapeHtml(line) + '</span>');
          else if (line.startsWith('[WARN]')) _soloTermPrintHTML('<span class="c-amber">' + escapeHtml(line) + '</span>');
          else if (line.startsWith('[HINT]')) _soloTermPrintHTML('<span class="c-muted">' + escapeHtml(line) + '</span>');
          else if (line.startsWith('[ERROR]')) _soloTermPrintHTML('<span class="c-red">' + escapeHtml(line) + '</span>');
          else _soloTermPrint(line);
        }
      } catch (e) {
        _soloTermPrintHTML('<span class="c-red">[ERROR] ' + escapeHtml(e.message) + '</span>');
      }
      _soloTerm.loading = false;
      return;
    }

    // ── Unrecognized command: route to NLP agent for natural language ──
    // Instead of 'Unknown command', treat every input as a natural language
    // mining question. The ask endpoint handles Portuguese, English, typos, etc.
    _soloTermPrintHTML('<span class="c-muted">querying agent...</span>');
    try {
      const r = await fetch('/api/agents/solo-mining/ask', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({query: cmd})
      });
      const data = await r.json();
      if (data.error) {
        _soloTermPrintHTML('<span class="c-red">[ERROR] ' + escapeHtml(data.error) + '</span>');
        _soloTerm.loading = false;
        return;
      }
      _soloTermPrint('');
      const output = data.output || '';
      const lines = output.split("\n");
      for (const line of lines) {
        if (line.startsWith('[OK]')) _soloTermPrintHTML('<span class="c-green">' + escapeHtml(line) + '</span>');
        else if (line.startsWith('[WARN]')) _soloTermPrintHTML('<span class="c-amber">' + escapeHtml(line) + '</span>');
        else if (line.startsWith('[HINT]')) _soloTermPrintHTML('<span class="c-muted">' + escapeHtml(line) + '</span>');
        else if (line.startsWith('[ERROR]')) _soloTermPrintHTML('<span class="c-red">' + escapeHtml(line) + '</span>');
        else _soloTermPrint(line);
      }
    } catch (e) {
      _soloTermPrintHTML('<span class="c-red">[ERROR] ' + escapeHtml(e.message) + '</span>');
    }
    _soloTerm.loading = false;
    return;
  }

  function _soloTermInit() {
    _soloTerm.output = document.getElementById('solo-term-output');
    _soloTerm.input = document.getElementById('solo-term-input');
    if (!_soloTerm.input) return;

    _soloTerm.input.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') {
        const cmd = _soloTerm.input.value.trim();
        if (cmd) {
          _soloTerm.history.push(cmd);
          _soloTerm.historyIdx = _soloTerm.history.length;
          _soloTermExecute(cmd);
          _soloTerm.input.value = '';
        }
      } else if (e.key === 'ArrowUp') {
        e.preventDefault();
        if (_soloTerm.historyIdx > 0) {
          _soloTerm.historyIdx--;
          _soloTerm.input.value = _soloTerm.history[_soloTerm.historyIdx];
        }
      } else if (e.key === 'ArrowDown') {
        e.preventDefault();
        if (_soloTerm.historyIdx < _soloTerm.history.length - 1) {
          _soloTerm.historyIdx++;
          _soloTerm.input.value = _soloTerm.history[_soloTerm.historyIdx];
        } else {
          _soloTerm.historyIdx = _soloTerm.history.length;
          _soloTerm.input.value = '';
        }
      }
    });

    // Keep focus on input when clicking anywhere in the terminal
    const term = document.getElementById('solo-term');
    if (term) {
      term.addEventListener('click', () => _soloTerm.input && _soloTerm.input.focus());
    }

    // Clear button
    document.getElementById('solo-term-clear')?.addEventListener('click', () => {
      if (_soloTerm.output) _soloTerm.output.innerHTML = '';
      _soloTermPrintHTML('<span class="c-muted">terminal cleared — type help for commands</span>');
    });

    // Focus input is handled inside boot() after welcome messages
    // (boot() registers help listener + prints welcome + focuses input)
  }  // end _soloTermInit

// ══════════════════════════════════════════════════════════════════════
  // POLLING
  // ══════════════════════════════════════════════════════════════════════

  // ── Error rate limiter for fetch errors ──
  // Prevents flooding the live log / console with repeated "Failed to fetch"
  // messages when the server is temporarily unreachable.
  var _fetchErrorCount = 0;
  var _fetchErrorSuppressed = false;

  async function fetchSnapshot() {
    try {
      const r = await fetch('/api/snapshot');
      if (!r.ok) throw new Error('snapshot failed');
      const snap = await r.json();
      render(snap);
      updateNextPoll();
      // Reset error counter on success
      _fetchErrorCount = 0;
      _fetchErrorSuppressed = false;
    } catch (e) {
      _fetchErrorCount++;
      if (_fetchErrorCount <= 3) {
        logMessage('ERROR', e.message, 'WARN');
      } else if (!_fetchErrorSuppressed) {
        _fetchErrorSuppressed = true;
        logMessage('WARN', 'Connection issues — suppressing further fetch errors (will retry silently)', 'WARN');
      }
    }
  }

  function updateNextPoll() {
    nextPollAt = Date.now() + POLL_MS;
    if (dom.nextPoll) dom.nextPoll.textContent = `${Math.ceil(POLL_MS/1000)}s`;
  }

  // ── Clock ──
  function updateClock() {
    if (dom.clock) dom.clock.textContent = new Date().toLocaleTimeString();
  }

  // ── Empty state management ──────────────────────────────────────────────
  function _updateEmptyState() {
    // Only show empty state if user EXPLICITLY connected a wallet
    // (not when BTC_ADDRESS comes from server env var via template)
    var hasWallet = !!(window._userConnectedWallet && window.BTC_ADDRESS && window.BTC_ADDRESS.length >= 10);
    var panels = document.querySelectorAll('.grid > .panel, .grid section.panel');
    panels.forEach(function(panel) {
      if (hasWallet) {
        panel.classList.remove('panel--no-wallet');
        var badge = panel.querySelector('.panel__empty-badge');
        if (badge) badge.remove();
      } else {
        if (!panel.classList.contains('panel--no-wallet')) {
          panel.classList.add('panel--no-wallet');
          var badge = document.createElement('div');
          badge.className = 'panel__empty-badge';
          badge.innerHTML = '<div class="panel__empty-icon">⛓</div><div class="panel__empty-badge-tag">NO WALLET</div><div class="panel__empty-label">Connect a Bitcoin address to view mining data</div>';
          panel.appendChild(badge);
        }
      }
    });
  }

  // ── Boot ──
  async function boot() {
    initMatrix(); initCharts(); bindChartRanges(); loadSettings(); _checkSavedWallet();
    _updateEmptyState();
    updateClock(); setInterval(updateClock, 1000);
    showSkeletons();
    _huntStart();
    _soloTermInit();
    // Auto-load initial chart data
    ['chart-hashrate','chart-pool','chart-bestdiff','chart-net'].forEach(function(id){
      var row = document.querySelector('.chart-range[data-target="'+id+'"]');
      if (!row) return;
      var active = row.querySelector('.active');
      var range = active && active.dataset.range ? active.dataset.range : '1h';
      var metricMap = {'chart-hashrate':'worker_hashrate','chart-pool':'pool_hashrate','chart-bestdiff':'worker_best_diff','chart-net':'network_difficulty'};
      loadChart(id, metricMap[id] || id.replace('chart-',''), range);
    });
    // Help button
    document.getElementById('solo-term-help')?.addEventListener('click', function(){
      _soloTermExecute('help');
    });
    // Welcome message
    _soloTermPrintHTML('<span class="c-muted">CYPHER SOLO MINING ADVISOR v1.0</span>');
    _soloTermPrintHTML('<span class="c-muted">Type </span><span class="c-green">help</span><span class="c-muted"> for available commands.</span>');
    _soloTermPrintHTML('<span class="c-muted">Examples:</span>');
    _soloTermPrintHTML('<span class="c-muted">  calc --hashrate 225TH --duration 24h</span>');
    _soloTermPrintHTML('<span class="c-muted">  compare --budget 0.01 --duration 24 --braiins 0.002 --mrr 0.0015</span>');
    _soloTermPrintHTML('<span class="c-muted">  network</span>');
    _soloTermPrint('');
    // Focus input
    _soloTerm.input.focus();
    // Start data polling with adaptive intervals (battery-optimized)
    await fetchSnapshot();
    _startAdaptivePolling();
    // Check for rental market opportunities every ~2 min (8 polls at 15s)
    setInterval(_checkOpportunities, POLL_MS * 8);
    logMessage('SYSTEM', 'WAR ROOM ONLINE', 'SUCCESS');

    // ── Battery Optimization: Visibility API ──────────────────────
    document.addEventListener('visibilitychange', _onVisibilityChange);
    window.addEventListener('pagehide', () => { _isTabHidden = true; _stopMatrix(); });
    window.addEventListener('pageshow', () => { _isTabHidden = false; _startMatrix(); });

    // ── Mobile: touch-friendly controls ──────────────────────────
    _initMobileNav();
  }

  // ── Adaptive polling: faster when visible, slower when hidden ──
  function _startAdaptivePolling() {
    if (_pollTimer) clearInterval(_pollTimer);
    const interval = _isTabHidden ? POLL_MS_BACKGROUND : POLL_MS;
    _pollTimer = setInterval(() => {
      if (!_isTabHidden) fetchSnapshot();
    }, interval);
  }

  function _onVisibilityChange() {
    if (document.hidden) {
      _isTabHidden = true;
      _stopMatrix();
      _startAdaptivePolling();
    } else {
      _isTabHidden = false;
      _startMatrix();
      _startAdaptivePolling();
      fetchSnapshot();
      nextPollAt = Date.now() + POLL_MS;
      if (dom.nextPoll) dom.nextPoll.textContent = `${Math.ceil(POLL_MS/1000)}s`;
    }
  }

  function _stopMatrix() {
    _matrixRunning = false;
    if (_matrixRafId) { cancelAnimationFrame(_matrixRafId); _matrixRafId = null; }
  }

  function _startMatrix() {
    if (!_matrixRunning) initMatrix();
  }

  // ── Mobile navigation ─────────────────────────────────────────
  function _initMobileNav() {
    // Handled by responsive CSS breakpoints (see style.css media queries)
  }

  boot();
})();
