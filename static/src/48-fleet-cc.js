  // ══════════════════════════════════════════════════════════════════════
  // Fleet Command Center — domínio extraído de `40-app-logic.js`
  // ══════════════════════════════════════════════════════════════════════
  // RFC 478 (Issue 521). Movimento MECÂNICO: nenhum nome, id de DOM, contrato
  // de fetch, formato de payload ou ordem de execução mudou — as 393 linhas
  // abaixo foram recortadas verbatim.
  //
  // DUAS REGIÕES DISJUNTAS: este cluster estava partido no app-logic, com
  // `_initLmEventLogControls` (UI do terminal de eventos do módulo LIVE MINING)
  // ENTRE as duas metades. Essa função NÃO pertence a este domínio: fica em
  // `40-app-logic.js` e vai para o PR 5 (Terminal/SSE). A metade de baixo começa
  // no comentário de seção ("FLEET-fed rendering"), que veio junto.
  //
  // Zero execução no topo: a região contém APENAS declarações de função —
  // nenhuma `const`/`let`/`var`, nenhum statement de nível de módulo. Entra depois
  // de `47-admin.js` e antes de `50-close.js` sem TDZ e sem mudar o instante de
  // nada que já rodava.
  //
  // Acoplamento externo (3 pontos, todos no MESMO IIFE — function declarations
  // são hoisted, então a ordem de concatenação não importa):
  //   · `renderFleetCommandCenter()` — chamado por `render()`
  //   · `_ccRenderFleet()`            — chamado por `initFleetCommandCenterControls()`
  //                                      (região B, permanece) e pelo chip de view
  //   · `_numOrNull()`                — consumido por `buildCommandCenterRows()`
  //                                      (região B, permanece)
  // O terminal de eventos (`_logMiningEvent`) é alimentado por
  // `renderFleetCommandCenter()` e escreve no widget do Live Mining; ambos
  // seguem no mesmo escopo, então a relação não muda.

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
    if (dom.fccSummaryHrSpark) dom.fccSummaryHrSpark.innerHTML = _ccSvgSparkline(_ccHrSeries, cssVar('--brand'));
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
      const healthColor = hs >= 80 ? cssVar('--green') : hs >= 50 ? cssVar('--amber') : cssVar('--red');
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
        '<div class="fcc-card__hr"><span class="fcc-card__hr-val">' + esc(r.hrStr) + '</span>' + _ccSvgSparkline(_ccHrHist[r.id], cssVar('--brand')) + '</div>' +
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
