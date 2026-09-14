  // ═════════════════════════════════════════════════════════════════════
  // Dashboard / render() — HUD, painéis, gráficos, poll e KPI cards
  // — domínio extraído de `40-app-logic.js` (RFC 478 · PR 10 · Issue 561)
  // ═════════════════════════════════════════════════════════════════════
  // Movimento MECÂNICO: nenhum nome, id de DOM, contrato de fetch ou formato de
  // payload mudou — as 1.082 linhas abaixo são 6 recortes VERBATIM (na ordem do
  // arquivo), somando 40 declarações (31 funções + 9 de estado) e ZERO
  // statements de topo:
  //   · R5  `209–504` (296) — HUD/status bar/freshness + Operational Overview
  //          (`renderHUD`, `renderStatusBar`, `renderSnapshotFreshness`,
  //           `_operationalFleetData`/`_operationalFleetError`,
  //           `buildOperationalOverviewModel`, `renderOperationalOverview`).
  //   · R6  `506–753` (248) — `initOperationalOverviewControls` + painéis do
  //          dashboard (`renderWalletIdentity`, `renderHostCore`, `renderHero`,
  //          `renderMinersXRay`, `renderPool`, `renderNetwork`).
  //   · R8  `769–869` (101) — `CHART_METRICS`, `_chartRange`, `_fmtChartLabel`,
  //          `_updateShareDistBadge`, `_applyShareDistTarget`, `loadChartData`,
  //          `renderCharts`.
  //   · R18 `1364–1723` (360) — `render()` + infraestrutura de gráficos
  //          (`prevSnapshot`, `charts`, `computeSMA`, `buildChartAnnotations`,
  //          `chartEventAnnotationsPlugin`, `clampZoomRange`, `_attachChartZoom`,
  //          `makeChart`, `loadChart`, `initCharts`, `_resetChartZoom`,
  //          `bindChartRanges`).
  //   · R24 `2031–2082` (52) — poll/relógio/snapshot (`_lastSnapshot`,
  //          `updateNextPoll`, `updateClock`, `_snapshotFetching`,
  //          `fetchSnapshot`).
  //   · R31 `3264–3288` (25) — `renderKpiCards`.
  //
  // ⚠ POR QUE ESTE FRAGMENTO VEM **ANTES** DO 40 — como o 37, o 38 e o 39. A
  // régua da §3.3 é sobre ESTADO lido por chamada de NÍVEL DE MÓDULO, e o
  // `boot()` é **chamado no topo do god file** (`40:2232`). O corpo síncrono
  // dele — antes do primeiro `await` — toca este domínio:
  //   · `initCharts()` (1a instrução do `boot()`) escreve/lê `const charts` (R18);
  //   · `await fetchSnapshot()` chama `fetchSnapshot()` (R24), que antes do
  //     primeiro `await` LÊ E ESCREVE `let _snapshotFetching`;
  //   · `updateClock()`/`updateNextPoll()` (R24) e
  //     `initOperationalOverviewControls()` (R5) são chamados nesse prefixo.
  // Com o fragmento DEPOIS do 40, tudo isso seria TDZ → `ReferenceError` no boot.
  //
  // O que este fragmento NÃO tem: statements de topo. É o primeiro domínio
  // extraído sem NENHUM (nem listener, nem `window.X = …`), então não há ordem
  // de execução a preservar do lado dele — a única restrição é a de POSIÇÃO
  // acima. Os 9 inicializadores de estado são literais (`null`/`false`/`{}`/
  // objetos), logo nenhum avalia código no momento da declaração.
  //
  // Verificações feitas antes de mover: zero colisão de declaração dos 40 nomes
  // com os outros 15 fragmentos; zero statement de topo (em qualquer fragmento)
  // que mencione um nome movido; e os consumidores externos são todos de
  // RUNTIME (hoisting de `function` no IIFE único) — `37-wallet-support.js`
  // (`renderWalletIdentity(prevSnapshot)` no `openWalletModal`, `fetchSnapshot()`
  // no save de settings), `38-billing-auth.js` (`renderCharts()` em
  // `pollBtcStatus`/`applyUpgradeKey`), `39-terminal.js` (o handler de comando
  // lê/escreve `_lastSnapshot`) e `49-axe-fleet.js` (`fetchAxeFleet` escreve
  // `_operationalFleetData`/`_operationalFleetError` e chama
  // `renderOperationalOverview(_lastSnapshot || {}, …)`).
  //
  // Desvio de ordem ORIGINAL, registrado: no arquivo pré-split, R5/R6/R8/R18
  // ficavam ANTES do bloco de terminal (R9), e agora caem depois do
  // `39-terminal.js`. Sem efeito observável — não há statement de topo deste
  // lado para ordenar (ver parágrafo acima).

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

  // A single, quiet freshness signal for the operational shell. Individual
  // panels retain their detailed badges; this one prevents a stale network,
  // BTC price, pool, or entire snapshot from being missed while another module
  // is open. It deliberately does not animate because it can update every poll.
  // snapshotFreshness / snapshotFreshnessLabel live in 10-core-fmt.js (Issue #536)
  // so the age is always visible — LIVE / SYNCED / DADOS ANTIGOS / NO DATA.
  function renderSnapshotFreshness(snap) {
    const el = dom.topbarFreshness;
    if (!el) return;
    const freshness = snapshotFreshness(snap);
    const ageText = freshness.age === null ? 'idade desconhecida' : fmt.secsToHuman(freshness.age);
    const label = snapshotFreshnessLabel(freshness, ageText);
    el.hidden = !!label.hidden;
    el.textContent = label.text;
    el.classList.remove('topbar__freshness--live', 'topbar__freshness--synced', 'topbar__freshness--stale', 'topbar__freshness--mute');
    el.classList.add('topbar__freshness--' + label.tone);
    const sourceText = freshness.sources.length ? freshness.sources.join(', ') : 'snapshot';
    el.title = label.tone === 'stale'
      ? ('Dados desatualizados: ' + sourceText + ' · última atualização ' + ageText + ' atrás.')
      : ('Atualizado há ' + ageText + ' · ' + sourceText);
  }

  // ── Operational Overview (Issue 367) ─────────────────────────────────
  // Combines the real snapshot with the independently polled fleet health
  // endpoint. The model is pure and mirrored in the JS core suite. A missing
  // value remains unavailable — zero is shown only when the source proves it.
  let _operationalFleetData = null;
  let _operationalFleetError = false;

  function buildOperationalOverviewModel(snap, fleetData, fleetError, nowSec) {
    const data = snap || {};
    const fleet = fleetData && fleetData.fleet_stats;
    const devices = fleetData && Array.isArray(fleetData.device_health) ? fleetData.device_health : [];
    const freshness = snapshotFreshness(data, nowSec);
    const fleetAges = devices.map(function(d) {
      const raw = d && d.telemetry && d.telemetry.age_seconds;
      return raw === null || raw === undefined || raw === '' ? null : Number(raw);
    }).filter(function(v) { return v !== null && isFinite(v) && v >= 0; });
    const fleetAge = fleetAges.length ? Math.max.apply(null, fleetAges) : null;
    const fleetTelemetryStale = fleetAge !== null && fleetAge > 150;
    const staleSources = freshness.sources.slice();
    if (freshness.stale && freshness.sources.length === 0) staleSources.push('snapshot');
    if (fleetTelemetryStale) staleSources.push('fleet telemetry');
    // Combined freshness cannot be called LIVE when the snapshot has no
    // timestamp, even if the independently fetched Fleet samples are recent.
    const dataAge = freshness.age === null ? null : (fleetAge === null ? freshness.age : Math.max(freshness.age, fleetAge));
    const dataStale = freshness.stale || fleetTelemetryStale;

    const profit = data.profitability || {};
    const costValuePresent = profit.cost_per_day_usd !== null && profit.cost_per_day_usd !== undefined && profit.cost_per_day_usd !== '';
    const rawCost = Number(profit.cost_per_day_usd);
    const hasCost = profit.cost_model_configured === true && costValuePresent && isFinite(rawCost) && rawCost >= 0;

    const model = {
      loading: !fleet && !fleetError,
      fleetError: !!fleetError,
      empty: false,
      overall: 'LOADING',
      tone: 'neutral',
      health: 'WAITING',
      healthDetail: 'Reading fleet telemetry…',
      attention: null,
      attentionDetail: 'Waiting for devices…',
      lostHashrateHs: null,
      lossBaselineDevices: 0,
      costPerDayUsd: hasCost ? rawCost : null,
      costDetail: hasCost ? String(profit.cost_label || 'Configured cost model') : 'Cost model not configured',
      freshness: dataStale ? 'STALE' : (dataAge === null ? 'NO DATA' : 'LIVE'),
      dataAge: dataAge,
      freshnessDetail: staleSources.length ? staleSources.join(', ') : (dataAge === null ? 'Snapshot timestamp unavailable' : 'Snapshot and fleet telemetry'),
      actionTitle: 'WAIT FOR DATA',
      actionTarget: '',
      actionPanel: '',
      actionEnabled: false,
      stateText: 'Loading real operational data…',
    };

    if (fleetError) {
      model.loading = false;
      model.overall = 'UNAVAILABLE';
      model.tone = 'critical';
      model.health = 'UNAVAILABLE';
      model.healthDetail = 'Fleet health endpoint unavailable';
      model.attentionDetail = 'Cannot verify ASIC state';
      model.freshness = 'PARTIAL';
      model.freshnessDetail = 'Fleet telemetry unavailable';
      model.actionTitle = 'OPEN FLEET DIAGNOSTIC';
      model.actionTarget = 'fleet';
      model.actionPanel = 'axe-fleet-panel';
      model.actionEnabled = true;
      model.stateText = 'Fleet data could not be loaded. Snapshot metrics may still be current.';
      return model;
    }
    if (!fleet) return model;

    const total = Math.max(0, Number(fleet.total_devices) || 0);
    const offline = Math.max(0, Number(fleet.offline) || 0);
    const warning = Math.max(0, Number(fleet.warning) || 0);
    const online = Math.max(0, Number(fleet.online) || 0);
    const attention = offline + warning;
    const healthScore = Number(fleet.avg_health_score);
    const baselineCount = Math.max(0, Number(fleet.hashrate_loss_baseline_devices) || 0);
    const lost = Number(fleet.hashrate_lost_hs);
    model.loading = false;
    model.attention = attention;
    model.attentionDetail = warning + ' warning · ' + offline + ' offline';
    model.lossBaselineDevices = baselineCount;
    model.lostHashrateHs = baselineCount > 0 && isFinite(lost) && lost >= 0 ? lost : null;

    if (total === 0) {
      model.empty = true;
      model.overall = dataStale ? 'STALE DATA' : 'NO FLEET';
      model.tone = dataStale ? 'warning' : 'neutral';
      model.health = 'NO FLEET';
      model.healthDetail = 'No ASIC registered';
      model.attentionDetail = '0 registered devices';
      model.actionTitle = 'REGISTER OR DISCOVER ASIC';
      model.actionTarget = 'fleet';
      model.actionPanel = 'axe-fleet-panel';
      model.actionEnabled = true;
      model.stateText = 'No ASIC is registered; fleet health and hashrate loss cannot be calculated.';
      return model;
    }

    if (offline > 0 || (isFinite(healthScore) && healthScore < 30)) {
      model.overall = 'CRITICAL';
      model.tone = 'critical';
      model.health = 'CRITICAL';
    } else if (warning > 0 || (isFinite(healthScore) && healthScore < 60)) {
      model.overall = 'ATTENTION';
      model.tone = 'warning';
      model.health = 'DEGRADED';
    } else {
      model.overall = 'HEALTHY';
      model.tone = 'healthy';
      model.health = 'HEALTHY';
    }
    model.healthDetail = online + '/' + total + ' reachable · health ' + (isFinite(healthScore) ? Math.round(healthScore) + '/100' : 'unavailable');
    if (dataStale) {
      model.overall = 'STALE DATA';
      if (model.tone === 'healthy') model.tone = 'warning';
    }
    model.stateText = attention > 0
      ? attention + ' ASIC exception' + (attention === 1 ? '' : 's') + ' require operator diagnosis.'
      : (dataStale ? 'One or more operational sources are stale; verify data before deciding.' : 'Fleet telemetry is loaded and current.');

    // Exception-first action. Snapshot Command Center cards are advisory, but
    // this surface intentionally ignores external URLs and only navigates to
    // an internal diagnostic module. It cannot dispatch a device command.
    let action = null;
    if (dataStale) {
      action = fleetTelemetryStale
        ? { title: 'VERIFY STALE FLEET TELEMETRY', target: 'fleet', panel: 'axe-fleet-panel' }
        : { title: 'VERIFY STALE DATA SOURCES', target: 'dashboard', panel: staleSources.indexOf('rede') !== -1 || staleSources.indexOf('preço BTC') !== -1 ? 'network-panel' : 'pool-overview' };
    } else if (attention > 0) {
      action = { title: 'INSPECT ' + attention + ' ASIC EXCEPTION' + (attention === 1 ? '' : 'S'), target: 'fleet', panel: 'axe-fleet-panel' };
    } else {
      const cards = Array.isArray(data.command_center) ? data.command_center : [];
      const card = cards.find(function(c) {
        return c && c.target && c.id !== 'affiliate_buy' && !c.url;
      });
      if (card) action = { title: String(card.title || 'OPEN DIAGNOSTIC').toUpperCase(), target: String(card.target), panel: String(card.panel || '') };
    }
    if (!action && !hasCost) {
      action = { title: 'CONFIGURE OPERATIONAL COST', target: 'dashboard', panel: 'profit-panel' };
    }
    if (action) {
      model.actionTitle = action.title;
      model.actionTarget = action.target;
      model.actionPanel = action.panel;
      model.actionEnabled = true;
    } else {
      model.actionTitle = 'NO ACTION REQUIRED';
      model.stateText = dataStale ? 'Operation appears stable, but one or more data sources are stale.' : 'Operation is healthy and current; no operator action is required.';
    }
    return model;
  }

  function renderOperationalOverview(snap, fleetData, fleetError) {
    const root = document.getElementById('operational-overview');
    if (!root) return;
    const model = buildOperationalOverviewModel(snap, fleetData, fleetError);
    const put = function(id, value) { const node = document.getElementById(id); if (node) node.textContent = value; };
    root.setAttribute('aria-busy', model.loading ? 'true' : 'false');
    root.classList.toggle('is-critical', model.tone === 'critical');
    root.classList.toggle('is-warning', model.tone === 'warning');
    root.classList.toggle('is-healthy', model.tone === 'healthy');
    put('op-overall-status', model.overall);
    const badge = document.getElementById('op-overall-status');
    if (badge) badge.className = 'badge ' + (model.tone === 'critical' ? 'badge--red' : model.tone === 'warning' ? 'badge--amber' : model.tone === 'healthy' ? 'badge--green' : 'badge--mute');
    put('op-health', model.health);
    put('op-health-detail', model.healthDetail);
    put('op-attention', model.attention === null ? '—' : String(model.attention));
    put('op-attention-detail', model.attentionDetail);
    put('op-lost-hashrate', model.lostHashrateHs === null ? '—' : fmt.hashrate(model.lostHashrateHs));
    put('op-lost-hashrate-detail', model.lossBaselineDevices > 0 ? 'Baseline available for ' + model.lossBaselineDevices + ' ASIC' + (model.lossBaselineDevices === 1 ? '' : 's') : 'Baseline unavailable');
    put('op-cost', model.costPerDayUsd === null ? 'NOT CONFIGURED' : '$' + model.costPerDayUsd.toFixed(2) + '/day');
    put('op-cost-detail', model.costDetail);
    put('op-freshness', model.freshness + (model.dataAge === null ? '' : ' · ' + fmt.secsToHuman(model.dataAge)));
    put('op-freshness-detail', model.freshnessDetail);
    put('op-action-title', model.actionTitle);
    put('op-action-detail', model.actionEnabled ? 'Opens diagnostic only · no command is executed' : 'Advisory only · no command is executed');
    put('op-state', model.stateText);
    const action = document.getElementById('op-action');
    if (action) {
      action.disabled = !model.actionEnabled;
      action.dataset.target = model.actionTarget;
      action.dataset.panel = model.actionPanel;
      action.textContent = model.actionEnabled ? 'OPEN DIAGNOSTIC' : 'NO ACTION';
    }
  }
  function initOperationalOverviewControls() {
    const action = document.getElementById('op-action');
    if (!action) return;
    action.addEventListener('click', function() {
      if (action.disabled) return;
      const target = action.dataset.target || '';
      const panel = action.dataset.panel || '';
      if (target) activateModule(target);
      if (panel) {
        setTimeout(function() {
          const node = document.getElementById(panel);
          if (!node) return;
          const reduceMotion = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
          node.scrollIntoView({ behavior: reduceMotion ? 'auto' : 'smooth', block: 'start' });
          node.focus && node.focus({ preventScroll: true });
        }, 140);
      }
    });
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
    // QR (pure JS encoder — no external service, address never leaves browser).
    // setHtmlIfChanged: the QR SVG is byte-identical for the same address, so
    // re-encoding on every 15s poll made the identity card visibly flicker.
    var qrBox = document.getElementById('wallet-id-qr');
    if (qrBox) {
      try {
        var qr = qrEncode(addr, 'M');
        setHtmlIfChanged(qrBox, qrSvg(qr.modules));
      } catch (e) {
        setHtmlIfChanged(qrBox, '<div class="wallet-id__qr-error">QR unavailable</div>');
      }
    }
    // Checksum-highlighted address
    var addrEl = document.getElementById('wallet-id-addr');
    if (addrEl) {
      var parts = walletAddressParts(addr);
      if (parts) {
        setHtmlIfChanged(addrEl, '<span class="addr-pfx">' + escapeHtml(parts.prefix) + '</span>' +
          '<span class="addr-body">' + escapeHtml(parts.body) + '</span>' +
          '<span class="addr-ck">' + escapeHtml(parts.checksum) + '</span>');
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
      setHtmlIfChanged(checksEl, health.checks.map(function(c) {
        return '<li class="wallet-id__check wallet-id__check--' + (c.ok ? 'ok' : 'bad') + '">' +
          '<span class="wallet-id__check-dot"></span>' + escapeHtml(c.label) + '</li>';
      }).join(''));
    } else if (checksEl) {
      checksEl.style.display = 'none';
      setHtmlIfChanged(checksEl, '');
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
  // ── Main render ──
  let prevSnapshot = null;
  function render(snap) {
    if (!_skeletonsHidden) hideSkeletons();
    // Sync window.BTC_ADDRESS from snapshot so modal and other components stay consistent
    window.BTC_ADDRESS = snap.btc_address || window.BTC_ADDRESS || '';
    toggleWalletCTA();
    renderHUD(snap);
    renderStatusBar(snap);
    renderSnapshotFreshness(snap);
    renderOperationalOverview(snap, _operationalFleetData, _operationalFleetError);
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
    resetLeaderboardFromSnapshot(snap);
    applyLiveMetrics(liveMetricsFromSnapshot(snap));
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
    // Issue #186: defensivo — app.js roda com defer após o Chart.js, mas se o
    // CDN falhar (offline/blocked) o boot não pode crashar. Null é tratado
    // pelos call sites (mesma convenção do canvas ausente).
    if (typeof Chart === 'undefined') return null;
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
          x: { ticks: { color: cssVar('--text-tertiary'), maxTicksLimit: 8, font: { family: 'JetBrains Mono, monospace', size: 10 } }, grid: { color: 'rgba(94,89,82,0.14)' } },
          y: { ticks: { color: cssVar('--text-tertiary'), font: { family: 'JetBrains Mono, monospace', size: 10 }, ...(yTickCb ? { callback: yTickCb } : {}) }, grid: { color: 'rgba(94,89,82,0.14)' } },
          y1: { position: 'right', display: false, grid: { drawOnChartArea: false }, ticks: { color: cssVar('--brand'), font: { family: 'JetBrains Mono, monospace', size: 10 } } },
        },
        plugins: {
          legend: { display: false },
          tooltip: {
            backgroundColor: 'rgba(17,18,20,0.94)',
            borderColor: 'rgba(255,255,255,0.08)',
            borderWidth: 1,
            titleColor: cssVar('--text-primary'),
            bodyColor: cssVar('--text-secondary'),
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
  // Latest dashboard snapshot received via polling/SSE. Terminal commands
  // (status/workers/price) read this instead of fetching /api/snapshot,
  // which internally triggers external hashrate-market offers and can take
  // >1s — the E2E terminal tests only wait 1000ms after Enter.
  let _lastSnapshot = null;

  // → domínio Terminal/SSE extraído para `static/src/39-terminal.js` (RFC 478, Issue 529)

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
    } catch (e) {
      // Sev-1 (UI audit 2026-08): a failed first fetch must NEVER leave the
      // boot skeletons stuck — the old code only logged, so a fetch failure
      // (network, rate limit on mobile) froze the whole dashboard in a
      // skeleton overlay with the status bar stuck at INIT. Hide on EVERY
      // outcome; the panels then show their honest empty/error state.
      hideSkeletons();
      logMessage('ERROR', e.message, 'WARN');
    }
    finally { _snapshotFetching = false; }
  }
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
