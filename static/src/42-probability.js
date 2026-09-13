  // ═════════════════════════════════════════════════════════════════════
  // Probability / Block Model
  // — domínio extraído de `40-app-logic.js` (RFC 478 · PR 7 · Issue 542)
  // ═════════════════════════════════════════════════════════════════════
  // Movimento MECÂNICO: nenhum nome, id de DOM, contrato de fetch ou formato de
  // payload mudou — as 635 linhas abaixo foram recortadas verbatim. O cluster
  // é CONTÍGUO (não houve corte no meio de um domínio, como no 4a/4b):
  //   · R10 — PROBABILIDADE / BLOCK MODEL (`_proxSparklineData`,
  //           `renderProximity`, `_drawProximitySparkline`, `renderQuantumLock`,
  //           `_setQlComp`, `renderLiveCalc`, `renderNetworkGauge`, `_drawGauge`).
  //   · R11 — RENTABILIDADE + COMPARAÇÃO/SOLO/MARCOS (`_profitMode`,
  //           `_lastProfitability`, `profitModeView`, `setProfitMode` + o
  //           `window.setProfitMode`, `renderProfitability`, `renderComparison`,
  //           `renderSoloStats`, `renderMilestones`).
  //   · R12 — BLOCK HUNT / what-if de dificuldade (`_bhBase`, `_bhSliderEl`,
  //           `_bhSliderValue`, `_bhFinitePositive`, `simulateDifficultyShift`,
  //           `_bhRenderWhatIf`, `renderBlockHunt`).
  //
  // ⚠ POSICIONAMENTO — depois do god file, como o `41-automations.js` e ao
  // contrário do `39-terminal.js` (a regra da §3.3 é sobre ESTADO lido por
  // chamada de nível de módulo):
  //   · único statement de topo da faixa é `window.setProfitMode =
  //     setProfitMode;`, que viaja junto.
  //   · os 5 nomes de estado (`_proxSparklineData`, `_profitMode`,
  //     `_lastProfitability`, `_bhBase`, `_bhSliderEl`) não são lidos em nenhum
  //     outro ponto do 40 fora da faixa nem em qualquer outro fragmento.
  //   · o prefixo síncrono do `boot()` não chama nenhuma função do domínio;
  //     `render()` chama `renderProfitability`/`renderSoloStats`/
  //     `renderProximity`/`renderQuantumLock`/`renderLiveCalc`/
  //     `renderNetworkGauge`/`renderMilestones`/`renderBlockHunt` só depois do
  //     `await fetchSnapshot()` (ou do SSE).
  //   · o bloco `#bh-whatif-slider` (topo, e que FICA no god file) apenas
  //     registra handlers — `input` → `_bhRenderWhatIf` e o reset — sem
  //     chamada síncrona.

  // ══════════════════════════════════════════════════════════════════════
  // HASH PROXIMITY METER — best diff vs network difficulty
  // ══════════════════════════════════════════════════════════════════════

  function renderProximity(prox) {
    if (!prox || !dom.proxHeroPct) return;
    if (prox.insufficient_data) return;

    // Badges
    if (dom.proxPctBadge) dom.proxPctBadge.textContent = prox.pct_of_network_cur != null ? Number(prox.pct_of_network_cur).toPrecision(3) + '% of target' : '—';
    if (dom.proxAlltimeBadge) dom.proxAlltimeBadge.textContent = prox.all_time_best_diff_str ? 'peak ' + prox.all_time_best_diff_str : 'peak —';
    if (dom.proxStreakBadge) dom.proxStreakBadge.textContent = prox.hot_streak ? 'share diff ↑ 1h' : 'share trend —';

    // Hero
    if (dom.proxHeroPct) dom.proxHeroPct.textContent = prox.pct_of_network_cur != null ? Number(prox.pct_of_network_cur).toPrecision(3) + '%' : '—';
    if (dom.proxHeroSub) dom.proxHeroSub.textContent = 'best-share / target ratio';
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
      if (pct > 50) arc.setAttribute('stroke', cssVar('--amber'));
      else if (pct > 10) arc.setAttribute('stroke', cssVar('--brand'));
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
      dom.proxTimeSub.textContent = '~' + Number(prox.blocks_per_year).toPrecision(3) + ' model avg blocks/yr';
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
    ctx.strokeStyle = cssVar('--brand');
    ctx.lineWidth = 1;
    ctx.beginPath();
    data.forEach((v, i) => i === 0 ? ctx.moveTo(x(i), y(v)) : ctx.lineTo(x(i), y(v)));
    ctx.stroke();

    // Dot at latest
    ctx.fillStyle = cssVar('--brand');
    ctx.beginPath();
    ctx.arc(x(data.length - 1), y(data[data.length - 1]), 2.5, 0, Math.PI * 2);
    ctx.fill();
  }

  // ══════════════════════════════════════════════════════════════════════
  // SESSION WORK SIGNAL — legacy payload key `quantum_lock` (0-100 heuristic)
  // ══════════════════════════════════════════════════════════════════════

  function renderQuantumLock(prox) {
    if (!prox || !dom.qlStatusBadge) return;
    const ql = prox.quantum_lock;
    if (!ql || !ql.score) {
      if (dom.qlStatusBadge) dom.qlStatusBadge.textContent = 'NO DATA';
      if (dom.qlScoreBadge) dom.qlScoreBadge.textContent = '0/100';
      if (dom.qlBarFill) dom.qlBarFill.style.width = '0%';
      if (dom.qlLabel) dom.qlLabel.textContent = 'Awaiting share data. This heuristic is not block probability, device health or a prediction.';
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
    if (dom.qlLabel) dom.qlLabel.textContent = (ql.label || 'Session work signal') + ' This score does not change the next-hash odds.';
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
    grad.addColorStop(0, cssVar('--green'));
    grad.addColorStop(0.5, cssVar('--brand'));
    grad.addColorStop(1, cssVar('--amber'));
    ctx.beginPath();
    ctx.arc(cx, cy, r, Math.PI, angle, false);
    ctx.strokeStyle = grad;
    ctx.lineWidth = 12;
    ctx.stroke();

    // Center label
    ctx.fillStyle = cssVar('--text-primary');
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
    const thresholdLabel = document.getElementById('p-breakeven-label');
    // The legacy shared cell remains for compatibility. Its visible label
    // changes by mode so a statistical mean is never presented as break-even.
    if (dom.pBreakeven) {
      if (_profitMode === 'solo' && view.soloStats && view.soloStats.expectedDays != null) {
        if (thresholdLabel) thresholdLabel.childNodes[0].nodeValue = 'MODEL MEAN INTERVAL ';
        dom.pBreakeven.textContent = fmt.secsToHuman(view.soloStats.expectedDays * 86400);
        if (dom.pBreakevenSub) dom.pBreakevenSub.textContent = 'not a countdown';
      } else if (_profitMode === 'solo') {
        // Honest telemetry: without solo data the break-even shows '—', so
        // the sub-label must NOT claim 'to block' (that would imply solo
        // stats rendered when they didn't — the old copy misled the UI).
        if (thresholdLabel) thresholdLabel.childNodes[0].nodeValue = 'MODEL MEAN INTERVAL ';
        dom.pBreakeven.textContent = '\u2014';
        if (dom.pBreakevenSub) dom.pBreakevenSub.textContent = 'no data';
      } else {
        if (thresholdLabel) thresholdLabel.childNodes[0].nodeValue = 'MODELED COST THRESHOLD ';
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
  function _bhFinitePositive(value) {
    const n = Number(value);
    return Number.isFinite(n) && n > 0 ? n : 0;
  }

  function simulateDifficultyShift(base, pct) {
    base = base || {};
    const mult = 1 + (Number(pct) || 0) / 100;
    const baseNet = _bhFinitePositive(base.netDiff);
    const netDiff = baseNet > 0 ? baseNet * mult : 0;
    const bestDiff = _bhFinitePositive(base.bestDiff);
    const baseP = Number(base.pBlock);
    let pBlock = null;
    if (bestDiff > 0 && netDiff > 0) pBlock = bestDiff / netDiff;
    else if (Number.isFinite(baseP) && baseNet > 0 && netDiff > 0) pBlock = baseP * (baseNet / netDiff);
    const expectedTimeRaw = Number(base.expectedTime);
    const expectedTime = Number.isFinite(expectedTimeRaw) && expectedTimeRaw > 0
      ? expectedTimeRaw * mult
      : (Number.isFinite(expectedTimeRaw) ? expectedTimeRaw : 0);
    const distance = bestDiff > 0 && netDiff > 0 ? netDiff / bestDiff : 0;
    let cumulativeP = Number.isFinite(Number(base.cumulativeP)) ? Number(base.cumulativeP) : base.cumulativeP;
    const shares = _bhFinitePositive(base.shares);
    if (shares > 0 && pBlock != null && Number.isFinite(pBlock) && pBlock > 0) {
      cumulativeP = 1 - Math.pow(1 - pBlock, shares);
    }
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
    const baseNet = _bhFinitePositive(_bhBase && _bhBase.netDiff);
    if (!_bhBase || !baseNet) {
      diffEl.textContent = '\u2014'; pEl.textContent = '\u2014'; etEl.textContent = '\u2014'; cumEl.textContent = '\u2014';
      return;
    }
    const sim = simulateDifficultyShift(_bhBase, pct);
    const pBlock = Number(sim.pBlock);
    const cumP = Number(sim.cumulativeP);
    diffEl.textContent = Number.isFinite(sim.netDiff) && sim.netDiff > 0 ? fmt.diff(sim.netDiff) : '\u2014';
    pEl.textContent = Number.isFinite(pBlock) ? (pBlock * 100).toExponential(2) + '%' : '\u2014';
    etEl.textContent = sim.expectedTime ? fmt.secsToHuman(sim.expectedTime) : '\u2014';
    cumEl.textContent = Number.isFinite(cumP) ? (cumP * 100).toFixed(4) + '%' : '\u2014';
  }

  // ── Block Hunt render ──
  function renderBlockHunt(snap) {
    const net = snap.network || {};
    const w = snap.worker || {};
    const prox = snap.proximity || {};
    const bh = snap.block_hunt || {};

    const netDiff = net.difficulty || bh.network_difficulty || 0;
    const bestDiff = w.bestDifficulty || bh.best_difficulty || 0;
    const bestShareRatio = bh.best_share_target_ratio != null
      ? Number(bh.best_share_target_ratio)
      : (bh.p_block_per_share != null ? Number(bh.p_block_per_share) : null);
    const pBlock = bh.modeled_share_probability != null
      ? Number(bh.modeled_share_probability)
      : (prox.chance_per_share_pct != null
        ? Number(prox.chance_per_share_pct)
        : (prox.chance_per_share_raw != null && netDiff > 0
          ? Number(prox.chance_per_share_raw) / netDiff
          : null));
    const expectedTime = bh.expected_time_seconds || prox.expected_time_seconds || prox.expected_time_secs;
    const cumulativeP = bh.cumulative_p_block;

    document.getElementById('bh-network-diff') && (document.getElementById('bh-network-diff').textContent = fmt.diff(netDiff));
    document.getElementById('bh-best-diff') && (document.getElementById('bh-best-diff').textContent = fmt.diff(bestDiff));
    document.getElementById('bh-chance-badge') && (document.getElementById('bh-chance-badge').textContent = pBlock != null ? (Number(pBlock) * 100).toExponential(2) + '% modeled/share' : '—');
    document.getElementById('bh-difficulty-badge') && (document.getElementById('bh-difficulty-badge').textContent = 'diff ' + fmt.diff(netDiff));

    // Distance
    if (bestDiff > 0 && netDiff > 0) {
      const ratio = bestShareRatio != null ? bestShareRatio : bestDiff / netDiff;
      document.getElementById('bh-distance') && (document.getElementById('bh-distance').textContent = (ratio * 100).toPrecision(3) + '%');
      document.getElementById('bh-distance-sub') && (document.getElementById('bh-distance-sub').textContent = 'target / historical best-share ratio');
    } else {
      document.getElementById('bh-distance') && (document.getElementById('bh-distance').textContent = '—');
    }

    // P(block) per share
    document.getElementById('bh-p-block') && (document.getElementById('bh-p-block').textContent = pBlock != null ? (Number(pBlock) * 100).toExponential(2) + '%' : '—');

    // Expected time
    document.getElementById('bh-expected-time') && (document.getElementById('bh-expected-time').textContent = expectedTime ? fmt.secsToHuman(expectedTime) : '—');
    if (typeof expectedTime === 'number') {
      const blocksPerYear = expectedTime > 0 ? (365 * 86400) / expectedTime : 0;
      document.getElementById('bh-expected-time-sub') && (document.getElementById('bh-expected-time-sub').textContent = '~' + blocksPerYear.toPrecision(3) + ' model avg blocks/yr · not a countdown');
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
    document.getElementById('bh-cumulative-p-sub') && (document.getElementById('bh-cumulative-p-sub').textContent = 'session work; next hash remains independent');

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
