  // ══════════════════════════════════════════════════════════════════════
  // Rentals — domínio extraído de `40-app-logic.js`
  // ══════════════════════════════════════════════════════════════════════
  // RFC 478 · PR 3 (Issue 517). Movimento MECÂNICO: nenhum nome, id de DOM,
  // contrato de fetch, formato de payload ou ordem de execução mudou — as
  // 1.770 linhas abaixo foram recortadas verbatim.
  //
  // O `MANIFEST` de `scripts/build_app_js.cjs` É a ordem de execução do IIFE,
  // e este fragmento é o último antes de `50-close.js`. Isso é seguro porque a
  // região movida contém SÓ DECLARAÇÕES — zero statements no topo (verificado:
  // nenhum `document.*`/`addEventListener` em nível de módulo aqui; os
  // listeners do painel vivem dentro de `_initRentalsPanel()`, chamada no boot).
  // Portanto nada lê o estado do módulo em TDZ.
  //
  // Pontos de toque de fora do fragmento (todos dentro de funções que rodam
  // depois da avaliação do IIFE):
  //   * `_initRentalsPanel()`  — boot, em `40-app-logic.js`
  //   * `loadRentals()`        — poll do snapshot + ativação do módulo
  //   * `_rentalsLoaded`       — guard de lazy-load
  //   * `_rentalsData`         — payload do render
  //
  // NÃO fazem parte deste domínio: o modal de compra spot da Braiins, o
  // AI Operator e o Auto-Pilot (seguem em `40-app-logic.js`).
  // ══════════════════════════════════════════════════════════════════════

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
    if (topEl) setHtmlIfChanged(topEl, (rec.top || []).map(t => {
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
    }).join(''));
    // Pilot's avoid case — grade-F rigs with a ONE-CLICK accept (blacklist).
    const avoidHead = document.getElementById('rentals-avoid-head');
    if (avoidHead) avoidHead.hidden = !hasAvoid;
    const avoidEl = document.getElementById('rentals-avoid-cards');
    if (avoidEl) setHtmlIfChanged(avoidEl, (rec.avoid || []).map(t => {
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
        '<button type="button" class="btn btn--mini btn--danger rentals-reco__blacklist" data-rig-id="' + escapeHtml(String(t.rig_id != null ? t.rig_id : '')) + '" title="aceitar a sugestão do piloto: nunca alugar este rig de novo">' + _ic('ban', 12, true) + 'BLACKLISTAR</button>' +
        '</div>';
    }).join(''));
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
          x: { ticks: { color: cssVar('--text-tertiary'), font: { size: 8 }, maxTicksLimit: 8 }, grid: { display: false } },
          y: { ticks: { color: cssVar('--text-tertiary'), font: { size: 8 } }, grid: { color: 'rgba(94,89,82,0.12)' } }
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
      '<span class="rentals-timing__fc-body"><b>ESTIMATIVA DO RETARGET ATUAL</b> · ' +
      escapeHtml(chg) + ' em ~' + Number(f.hours_to_adjustment).toFixed(0) + 'h ' +
      '(blocos a cada ' + Number(f.avg_block_time_s).toFixed(0) + 's)' +
      '<div class="rentals-timing__fc-verdict">' + escapeHtml(String(f.verdict || '')) +
      ' · Fonte: snapshots locais; janela: até 100 amostras; unidades: % e horas; premissa: cadência recente constante. Não é previsão garantida.</div></span>';
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
      const icon = _ic('alert', 12, true);
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
        '<span class="rentals-signals__icon">' + _ic('alert', 12) + '</span>' +
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
        ? '<button type="button" class="rentals-signals__buy" data-signal="arb-buy" data-price="' + mkt + '" data-th="' + sugTh + '" title="abrir compra Braiins com o preço atual pré-preenchido">' + _ic('zap', 12, true) + 'COMPRAR AGORA</button>'
        : '<span class="rentals-signals__cta">COMPRAR →</span>';
      items.push('<div class="rentals-signals__item is-arb" data-signal="arb" title="abrir compra Braiins — janela aberta">' +
        '<span class="rentals-signals__icon">' + _ic('trophy', 12) + '</span>' +
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
          x: { ticks: { color: cssVar('--text-tertiary'), font: { size: 9 }, maxTicksLimit: 12 }, grid: { display: false } },
          y: { ticks: { color: cssVar('--text-tertiary'), font: { size: 9 } }, grid: { color: 'rgba(94,89,82,0.12)' } }
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
          ? '<button class="btn btn--mini" id="rentals-rig-unblacklist" data-rig-id="' + escapeHtml(String(rigId || '')) + '">' + _ic('rotate', 12, true) + 'restaurar rig (remover da blacklist)</button>'
          : '<button class="btn btn--mini btn--danger" id="rentals-rig-blacklist" data-rig-id="' + escapeHtml(String(rigId || '')) + '">' + _ic('x', 12, true) + 'nunca alugar este rig</button>');
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

  function _rentalsLoadErrorHtml(reason) {
    return '<div class="empty-state" role="alert" style="grid-column:1/-1;border:none">' +
      '<div class="empty-state__icon">⚠</div>' +
      '<div class="empty-state__title">Rentals indisponível</div>' +
      '<div class="empty-state__desc">Não foi possível carregar dados reais de MRR/Braiins (' + escapeHtml(reason || 'falha de rede') + '). Nenhum valor foi estimado.</div>' +
      '<button type="button" class="btn btn--primary btn--mini" id="rentals-load-retry">TENTAR NOVAMENTE</button>' +
      '</div>';
  }

  function _renderRentalsLoadError(reason) {
    const listEl = document.getElementById('rentals-list');
    if (!listEl) return;
    listEl.innerHTML = _rentalsLoadErrorHtml(reason);
    const badge = document.getElementById('rentals-count-badge');
    if (badge) {
      badge.textContent = 'erro';
      badge.className = 'badge badge--amber';
    }
    const retry = document.getElementById('rentals-load-retry');
    if (retry) {
      retry.addEventListener('click', function () {
        retry.disabled = true;
        retry.setAttribute('aria-busy', 'true');
        retry.textContent = 'CARREGANDO…';
        const panel = document.getElementById('rentals-panel');
        skelShow(panel, 'table');
        loadRentals(true).then(function () { skelHide(panel); });
      });
    }
  }

  async function loadRentals(force) {
    const listEl = document.getElementById('rentals-list');
    if (!listEl) return false;
    try {
      // authFetch sends the user's Bearer token so the server resolves the
      // caller's TENANT — with 1000+ users each one sees only their own
      // Braiins/MRR credentials and rentals (never the operator's key).
      // force=1 (RECARREGAR on a stale empty-state, Issue #187) bypasses the
      // server TTL cache so credentials just added in Settings show up
      // without a full page reload.
      const r = await authFetch('/api/rentals' + (force ? '?refresh=1' : ''));
      if (!r.ok) {
        _renderRentalsLoadError('HTTP ' + r.status);
        return false;
      }
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
    } catch (e) {
      _renderRentalsLoadError('rede ou resposta inválida');
      return false;
    }
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
    // Strip shows the MRR-reported TOTAL — the paginated fetch (Issue #200)
    // now covers every page up to the safety cap, so the count IS the account
    // (and "X de N" surfaces honestly when the cap cut the series). Missing
    // provider credentials → 🔑 hint (with tooltip) instead of a misleading
    // 0/— that looks like an empty account.
    const _stripVal = (cardId, value, auth, err, authRejected, provider, rendered, total) => {
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
        const surf = rentalsCountSurface(rendered, total);
        card.textContent = surf.text != null ? surf.text : value;
        card.title = surf.title || '';
      }
    };
    _stripVal('rentals-mrr-active', mrr.total_active != null ? mrr.total_active : (mrr.active || []).length, mrr.needs_auth, mrr.error, mrr.auth_rejected, 'mrr', mrr.rendered_active, mrr.total_active);
    _stripVal('rentals-mrr-history', mrr.total_history != null ? mrr.total_history : (mrr.history || []).length, mrr.needs_auth, mrr.error, mrr.auth_rejected, 'mrr', mrr.rendered_history, mrr.total_history);
    _stripVal('rentals-mrr-owner', mrr.total_owner != null ? mrr.total_owner : (mrr.owner || []).length, mrr.needs_auth, mrr.error, mrr.auth_rejected, 'mrr', mrr.rendered_owner, mrr.total_owner);
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
      // Payload staleness (Issue #187): a payload built by old server code
      // (no version stamp) or too old to trust cannot prove an empty account
      // — it may predate the missing-key guard. Level 2 (old code) shows the
      // config hint; level 1 (age only) shows a soft 'dados desatualizados'
      // + reload. Never the misleading 'No contracts rentals on this
      // account'.
      const staleLevel = rentalsPayloadStale(_rentalsData, Math.floor(Date.now() / 1000));
      const payloadStale = staleLevel > 0;
      const credHint = staleLevel >= 2;
      const title = rejected ? 'API key rejected' : (needsAuth ? 'Credentials required' : (errMsg ? 'Provider error' : (credHint ? 'Configuração não verificada' : (staleLevel === 1 ? 'Dados desatualizados' : 'No rentals'))));
      const staleHint = credHint
        ? (isContracts
          ? 'Dados carregados por uma versão antiga do servidor — não dá para confirmar se a conta está vazia. Adicione o owner token Braiins (hashpower.braiins.com → API Tokens) no Settings (⚙), ou recarregue para verificar:'
          : 'Dados carregados por uma versão antiga do servidor — não dá para confirmar se a conta está vazia. Configure a chave MRR (miningrigrentals.com → My Account → API Access) no Settings (⚙), ou recarregue para verificar:')
        : 'Os dados estão antigos (mais de 5 min) — recarregue para confirmar o estado real da conta.';
      listEl.innerHTML = '<div class="empty-state" style="grid-column:1/-1;border:none">' +
        '<div class="empty-state__icon">' + (rejected || credHint ? _ic('key', 20) : _ic('package', 20)) + '</div>' +
        '<div class="empty-state__title">' + title + '</div>' +
        '<div class="empty-state__desc">' + (rejected
          ? rentalsAuthGuide(_rentalsFilter, errMsg)
          : (needsAuth
            ? (isContracts ? 'Add your Braiins Hashpower owner token to list contracts — where to get it: hashpower.braiins.com → API Tokens.' : 'Add your MiningRigRentals API key + secret to see history & performance — get them at miningrigrentals.com → My Account → API Access.')
            : (errMsg ? escapeHtml(errMsg) : (payloadStale ? staleHint : 'No ' + _rentalsFilter + ' rentals on this account')))) + '</div>' +
        (needsAuth || rejected || credHint ? '<button type="button" class="btn btn--primary btn--mini" id="rentals-open-settings" style="margin-top:8px">' + _ic('settings', 12, true) + 'OPEN SETTINGS</button>' : '') +
        (payloadStale ? '<button type="button" class="btn btn--mini" id="rentals-refresh-btn" style="margin-top:8px">' + _ic('refresh', 12, true) + 'RECARREGAR</button>' : '') +
        '</div>';
      const cta = document.getElementById('rentals-open-settings');
      if (cta) cta.addEventListener('click', function() { openSettingsModal(); });
      // RECARREGAR re-fetches with ?refresh=1 — creds just saved in Settings
      // take effect without a full page reload.
      const refreshBtn = document.getElementById('rentals-refresh-btn');
      if (refreshBtn) refreshBtn.addEventListener('click', function() { loadRentals(true); });
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
            '<span class="rentals-detail__autoex-icon">' + _ic('key', 12) + '</span>' +
            '<div class="rentals-detail__autoex-body"><strong>API KEY REJECTED</strong>' +
            '<div class="rentals-detail__autoex-sub">' + rentalsAuthGuide(provider, dErr) +
            '</div></div>' +
            '<button type="button" class="rentals-detail__autoex-btn" id="rentals-detail-auth-settings" title="abrir Settings para regenerar a chave">' + _ic('settings', 12, true) + 'OPEN SETTINGS</button>';
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
          '<span class="rentals-detail__autoex-icon">' + _ic('robot', 12) + '</span>' +
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
            ? '<button type="button" class="rentals-trust__btn rentals-trust__btn--restore" id="rentals-trust-toggle">' + _ic('check', 12, true) + 'RESTAURAR RIG</button>'
            : '<button type="button" class="rentals-trust__btn" id="rentals-trust-toggle">' + _ic('ban', 12, true) + 'EXCLUIR RIG (BLACKLIST)</button>';
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
                    y: { min: 0, max: 110, ticks: { color: cssVar('--text-tertiary'), font: { size: 8 }, callback: function (v) { return v + '%'; } }, grid: { color: 'rgba(94,89,82,0.12)' } },
                    x: { ticks: { color: cssVar('--text-tertiary'), font: { size: 8 } }, grid: { display: false } }
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
          else { bl.disabled = false; bl.innerHTML = _ic('ban', 12, true) + 'BLACKLISTAR'; }
        } catch (err) {
          // Fail-closed, but never leave the button stuck on '…'.
          bl.disabled = false;
          bl.innerHTML = _ic('ban', 12, true) + 'BLACKLISTAR';
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
