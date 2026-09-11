  // ══════════════════════════════════════════════════════════════════════
  // Admin / CFO / CRO — domínio extraído de `40-app-logic.js`
  // ══════════════════════════════════════════════════════════════════════
  // RFC 478 (Issue 518). Movimento MECÂNICO: nenhum nome, id de DOM, contrato
  // de fetch, formato de payload ou ordem de execução mudou — as 1.057 linhas
  // abaixo foram recortadas verbatim.
  //
  // ⚠️ DIFERENTE DO MARKET E DO RENTALS: este cluster NÃO contém só
  // declarações. Quatro statements executam na avaliação do script (perto do
  // fim): o listener delegado de `#admin-panel` (change → filtros do audit) e
  // os `click` de `#admin-audit-csv`, `#admin-funnel-csv` e
  // `#admin-refresh-btn`. Verificado: nenhum deles depende de ordem em relação
  // aos outros listeners do IIFE, e `static/app.js` é carregado com `defer`
  // (o DOM já está parseado quando qualquer fragmento roda), então rodar mais
  // tarde dentro do MESMO IIFE sincrono não altera o resultado. A cobertura
  // disso é o e2e: `admin-audit.spec.js` exercita `#admin-audit-tenant` /
  // `#admin-audit-verdict` / `#admin-audit-csv` e `conversion-admin.spec.js`
  // clica `#admin-refresh-btn`.
  //
  // Contrato de estado: TODAS as declarações deste bloco (`_adminLoaded`,
  // `_adminAuditDecisions`, `_adminAuditChart`, `_adminAnalyticsCharts`,
  // `_adminMetricsChart`, `_adminErrorChart`, `_adminFunnelTrendChart`,
  // `_auditFilterHost`, `auditCsvBtn`, `funnelCsvBtn`, `adminRefreshBtn`) foram
  // verificadas: nenhuma é referenciada fora daqui, então não há leitura em TDZ
  // por rodar mais tarde.
  //
  // Ponto de toque de fora: `fetchAdminData()` na ativação do módulo `admin`
  // (dentro de `_doActivateModule`, que roda depois da avaliação do IIFE).
  //
  // Os builders puros do audit trail (`adminAuditIsoWeekKey`,
  // `buildAdminAuditWeekly`, `adminAuditVerdictMeta`, `buildAdminAnalyticsModel`
  // …) são ESPELHADOS em `tests/test_app_js_core.js`. Pelo padrão fixado na
  // Issue 515, a conversão para `loadFragment('47-admin.js')` é follow-up.
  // ══════════════════════════════════════════════════════════════════════

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
  // decisions → weekly buckets {labels: ['2026-W31', …], counts: [n, …],
  // withoutDate: n}. Entries with ts<=0/null/garbage are NEVER dropped
  // silently (Issue #205 — honest telemetry): they surface as a counter the
  // chart renders as a "sem data" note instead of vanishing.
  function buildAdminAuditWeekly(decisions) {
    const buckets = {};
    let withoutDate = 0;
    (decisions || []).forEach(function (d) {
      const k = adminAuditIsoWeekKey(d && d.ts);
      if (!k) { withoutDate += 1; return; }
      buckets[k] = (buckets[k] || 0) + 1;
    });
    const labels = Object.keys(buckets).sort();
    return { labels: labels, counts: labels.map(function (k) { return buckets[k]; }), withoutDate: withoutDate };
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

  // Convert the protected analytics report into bounded chart/table series.
  // Kept pure so zero/partial payloads can be unit-tested without Chart.js.
  function buildAdminAnalyticsModel(report) {
    report = report || {};
    function safeCount(value) {
      const n = Number(value);
      return Number.isFinite(n) && n > 0 ? n : 0;
    }
    const usage = report.module_usage || {};
    const timing = report.module_time || {};
    const names = Array.from(new Set(Object.keys(usage).concat(Object.keys(timing))));
    const modules = names.map(function(name) {
      const time = timing[name] || {};
      return {
        name: name,
        accesses: safeCount(usage[name]),
        sessions: safeCount(time.sessions),
        totalSeconds: safeCount(time.total_seconds),
        avgSeconds: safeCount(time.avg_seconds),
      };
    }).sort(function(a, b) {
      return b.accesses - a.accesses || b.totalSeconds - a.totalSeconds || a.name.localeCompare(b.name);
    });
    const boots = (Array.isArray(report.boots_by_day) ? report.boots_by_day : []).map(function(point) {
      return { day: String(point.day || ''), boots: safeCount(point.boots) };
    }).filter(function(point) { return point.day; });
    const dau = Array.isArray(report.dau) ? report.dau : [];
    const wau = Array.isArray(report.wau) ? report.wau : [];
    const dropoff = report.dropoff || {};
    const bootTotal = safeCount(dropoff.boot_total != null ? dropoff.boot_total : report.boot_count);
    const withoutSwitch = Math.min(bootTotal, safeCount(dropoff.boot_without_switch));
    return {
      totalEvents: safeCount(report.total_events),
      bootCount: safeCount(report.boot_count),
      currentDau: dau.length ? safeCount(dau[dau.length - 1].users) : 0,
      currentWau: wau.length ? safeCount(wau[wau.length - 1].users) : 0,
      modules: modules,
      boots: boots,
      topModule: modules.length ? modules[0].name : '',
      dropoff: { withoutSwitch: withoutSwitch, navigated: Math.max(0, bootTotal - withoutSwitch), total: bootTotal },
    };
  }

  let _adminAuditDecisions = [];      // last payload (for client-side filters)
  let _adminAuditChart = null;        // Chart.js instance (destroy before recreate)
  let _adminAnalyticsCharts = {};
  let _adminAnalyticsRendered = false;

  async function fetchAdminData() {
    if (_adminLoaded) return;
    const errEl = document.getElementById('admin-error');
    const gate = document.getElementById('admin-gate-badge');
    _setAdminAnalyticsLoading(true);
    try {
      // Pool health — no auth needed for localhost/operator-key admin routes.
      const [sessionsResp, convResp, auditResp, metricsResp, docsResp, errResp, degResp, analyticsResp] = await Promise.all([
        fetch('/api/admin/sessions', { headers: { 'X-Requested-With': 'fetch' } }),
        fetch('/api/admin/conversion?weeks=8', { headers: { 'X-Requested-With': 'fetch' } }),
        fetch('/api/admin/rentals/accepted-recos?limit=1000', { headers: { 'X-Requested-With': 'fetch' } }),
        fetch('/api/admin/pool-metrics?hours=24', { headers: { 'X-Requested-With': 'fetch' } }),
        fetch('/api/admin/docs-feedback', { headers: { 'X-Requested-With': 'fetch' } }),
        fetch('/api/admin/error-rate?hours=24', { headers: { 'X-Requested-With': 'fetch' } }),
        fetch('/api/admin/degradation-rate?hours=24', { headers: { 'X-Requested-With': 'fetch' } }),
        fetch('/api/admin/analytics?days=30', { headers: { 'X-Requested-With': 'fetch' } }),
      ]);
      if (sessionsResp.status === 403 || convResp.status === 403 || auditResp.status === 403 || metricsResp.status === 403 || docsResp.status === 403 || errResp.status === 403 || degResp.status === 403 || analyticsResp.status === 403) {
        if (gate) gate.textContent = 'restricted';
        if (errEl) {
          errEl.hidden = false;
          errEl.textContent = 'Admin access required — endpoint só responde de localhost ou com a API key do operador (X-API-Key).';
        }
        _renderAdminAnalytics({ error: 'admin access required' });
        _adminLoaded = true;  // don't re-hammer a 403
        return;
      }
      if (gate) gate.textContent = 'ok';
      const sessions = sessionsResp.ok ? await sessionsResp.json() : {};
      const conv = convResp.ok ? await convResp.json() : {};
      const audit = auditResp.ok ? await auditResp.json() : {};
      const metrics = metricsResp.ok ? await metricsResp.json() : {};
      const docsFb = docsResp.ok ? await docsResp.json() : {};
      const errData = errResp.ok ? await errResp.json() : {};
      const degData = degResp.ok ? await degResp.json() : {};
      const analytics = analyticsResp.ok ? await analyticsResp.json() : { error: 'analytics request failed (' + analyticsResp.status + ')' };
      _renderAdmin(sessions, conv, audit, metrics, docsFb, errData, degData, analytics);
      _adminLoaded = true;
    } catch (e) {
      if (errEl) { errEl.hidden = false; errEl.textContent = 'admin fetch error: ' + e.message; }
      _renderAdminAnalytics({ error: 'analytics indisponível' });
    }
  }
  function _renderAdmin(sessions, conv, audit, metrics, docsFb, errData, degData, analytics) {
    _renderAdminMetrics(metrics || {});
    _renderAdminErrorRate(errData || {});
    _renderAdminDegradation(degData || {});
    _renderAdminAudit(audit);
    _renderAdminAutoExclusions(audit);
    _renderAdminDocsFeedback(docsFb || {});
    _renderAdminAnalytics(analytics || {});
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

  function _setAdminAnalyticsLoading(isLoading) {
    const root = document.getElementById('admin-analytics');
    if (!root) return;
    root.setAttribute('aria-busy', isLoading ? 'true' : 'false');
    root.querySelectorAll('[data-analytics-skeleton]').forEach(function(el) { el.hidden = !isLoading; });
    if (isLoading) {
      root.querySelectorAll('[data-analytics-canvas], [data-analytics-empty]').forEach(function(el) { el.hidden = true; });
      const state = document.getElementById('admin-analytics-state');
      if (state) { state.textContent = 'Carregando analytics…'; state.classList.remove('admin-analytics__state--error'); }
    }
  }

  function _destroyAdminAnalyticsCharts() {
    Object.keys(_adminAnalyticsCharts).forEach(function(key) {
      const chart = _adminAnalyticsCharts[key];
      if (chart && typeof chart.destroy === 'function') chart.destroy();
    });
    _adminAnalyticsCharts = {};
  }

  function _formatAnalyticsSeconds(value) {
    const seconds = Math.max(0, Number(value) || 0);
    if (seconds < 60) return Math.round(seconds) + 's';
    if (seconds < 3600) return Math.round(seconds / 60) + 'm';
    return (seconds / 3600).toFixed(seconds < 36000 ? 1 : 0) + 'h';
  }

  function _renderAdminAnalytics(report) {
    const root = document.getElementById('admin-analytics');
    const state = document.getElementById('admin-analytics-state');
    if (!root) return;
    _setAdminAnalyticsLoading(false);
    _destroyAdminAnalyticsCharts();
    root.querySelectorAll('[data-analytics-canvas], [data-analytics-empty]').forEach(function(el) { el.hidden = true; });

    if (report && report.error) {
      if (state) {
        state.textContent = 'Analytics indisponível: ' + String(report.error);
        state.classList.add('admin-analytics__state--error');
      }
      const tableWrap = document.getElementById('admin-analytics-table-wrap');
      if (tableWrap) tableWrap.hidden = true;
      return;
    }

    const model = buildAdminAnalyticsModel(report);
    _setAdminText('admin-analytics-boots', model.bootCount);
    _setAdminText('admin-analytics-dau', model.currentDau);
    _setAdminText('admin-analytics-wau', model.currentWau);
    _setAdminText('admin-analytics-modules', model.modules.length);
    _setAdminText('admin-analytics-top-module', model.topModule || '—');
    if (state) {
      state.classList.remove('admin-analytics__state--error');
      state.textContent = model.totalEvents
        ? model.totalEvents + ' eventos reais nos últimos ' + String((report && report.days) || 30) + ' dias.'
        : 'Sem eventos reais no período. O painel não preenche métricas com dados fictícios.';
    }

    const tableWrap = document.getElementById('admin-analytics-table-wrap');
    const tableBody = document.getElementById('admin-analytics-table-body');
    if (tableWrap) tableWrap.hidden = model.modules.length === 0;
    if (tableBody) {
      tableBody.innerHTML = model.modules.map(function(row) {
        return '<tr><td>' + escapeHtml(row.name) + '</td>' +
          '<td>' + escapeHtml(String(row.accesses)) + '</td>' +
          '<td>' + escapeHtml(String(row.sessions)) + '</td>' +
          '<td>' + escapeHtml(_formatAnalyticsSeconds(row.totalSeconds)) + '</td>' +
          '<td>' + escapeHtml(_formatAnalyticsSeconds(row.avgSeconds)) + '</td></tr>';
      }).join('');
    }

    const availability = {
      modules: model.modules.length > 0,
      boots: model.boots.length > 0,
      dropoff: model.dropoff.total > 0,
    };
    Object.keys(availability).forEach(function(key) {
      const empty = root.querySelector('[data-analytics-empty="' + key + '"]');
      if (empty) empty.hidden = availability[key];
    });

    if (typeof Chart === 'undefined') {
      if (state && (availability.modules || availability.boots || availability.dropoff)) {
        state.textContent = 'Os dados foram carregados, mas os gráficos estão indisponíveis (Chart.js não carregou).';
        state.classList.add('admin-analytics__state--error');
      }
      return;
    }

    const style = getComputedStyle(document.documentElement);
    const color = function(name, fallback) { return style.getPropertyValue(name).trim() || fallback; };
    const reduced = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    const animation = (reduced || _adminAnalyticsRendered) ? false : { duration: 180, easing: 'easeOutQuart' };
    const baseOptions = function() {
      return {
        responsive: true,
        maintainAspectRatio: false,
        animation: animation,
        plugins: { legend: { labels: { color: color('--text-secondary', 'rgb(144, 146, 150)'), boxWidth: 10 } } },
        scales: {
          x: { ticks: { color: color('--text-tertiary', 'rgb(94, 89, 82)'), maxRotation: 45, minRotation: 0 }, grid: { display: false } },
          y: { beginAtZero: true, ticks: { color: color('--text-tertiary', 'rgb(94, 89, 82)'), precision: 0 }, grid: { color: color('--border-subtle', 'rgba(94, 89, 82, 0.2)') } },
        },
      };
    };
    function showCanvas(id) {
      const canvas = document.getElementById(id);
      const wrap = canvas && canvas.closest('[data-analytics-canvas]');
      if (wrap) wrap.hidden = false;
      return canvas;
    }

    if (availability.modules) {
      const canvas = showCanvas('admin-analytics-modules-chart');
      const options = baseOptions();
      options.scales.y1 = { beginAtZero: true, position: 'right', ticks: { color: color('--text-tertiary', 'rgb(94, 89, 82)') }, grid: { drawOnChartArea: false } };
      _adminAnalyticsCharts.modules = new Chart(canvas.getContext('2d'), {
        type: 'bar',
        data: {
          labels: model.modules.map(function(row) { return row.name; }),
          datasets: [
            { label: 'Acessos', data: model.modules.map(function(row) { return row.accesses; }), backgroundColor: color('--brand-dim', 'rgba(247, 147, 26, 0.55)'), borderColor: color('--brand', 'rgb(247, 147, 26)'), borderWidth: 1, yAxisID: 'y' },
            { label: 'Tempo médio (min)', data: model.modules.map(function(row) { return Math.round(row.avgSeconds / 6) / 10; }), backgroundColor: color('--cyan-dim', 'rgba(247, 147, 26, 0.35)'), borderColor: color('--cyan', 'rgb(247, 147, 26)'), borderWidth: 1, yAxisID: 'y1' },
          ],
        },
        options: options,
      });
    }
    if (availability.boots) {
      const canvas = showCanvas('admin-analytics-boots-chart');
      _adminAnalyticsCharts.boots = new Chart(canvas.getContext('2d'), {
        type: 'line',
        data: {
          labels: model.boots.map(function(point) { return point.day; }),
          datasets: [{ label: 'Boots', data: model.boots.map(function(point) { return point.boots; }), borderColor: color('--green', 'rgb(0, 200, 83)'), backgroundColor: color('--green-bg', 'rgba(0, 200, 83, 0.12)'), fill: true, tension: 0.2, pointRadius: 2 }],
        },
        options: baseOptions(),
      });
    }
    if (availability.dropoff) {
      const canvas = showCanvas('admin-analytics-dropoff-chart');
      _adminAnalyticsCharts.dropoff = new Chart(canvas.getContext('2d'), {
        type: 'doughnut',
        data: {
          labels: ['Navegou', 'Saiu no boot'],
          datasets: [{ data: [model.dropoff.navigated, model.dropoff.withoutSwitch], backgroundColor: [color('--green', 'rgb(0, 200, 83)'), color('--amber', 'rgb(255, 176, 0)')], borderWidth: 0 }],
        },
        options: { responsive: true, maintainAspectRatio: false, animation: animation, cutout: '62%', plugins: { legend: { position: 'bottom', labels: { color: color('--text-secondary', 'rgb(144, 146, 150)'), boxWidth: 10 } } } },
      });
    }

    if (!_adminAnalyticsRendered) {
      root.classList.add('admin-analytics--first-ready');
      setTimeout(function() { root.classList.remove('admin-analytics--first-ready'); }, 260);
    }
    _adminAnalyticsRendered = true;
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
          x: { ticks: { color: cssVar('--text-tertiary'), font: { size: 9 }, maxRotation: 0 }, grid: { display: false } },
          y: { beginAtZero: true, position: 'left', title: { display: true, text: 'paywall', color: 'rgb(6,214,240)', font: { size: 8 } }, ticks: { color: cssVar('--text-tertiary'), font: { size: 9 }, precision: 0 }, grid: { color: 'rgba(94,89,82,0.10)' } },
          y1: { beginAtZero: true, position: 'right', title: { display: true, text: 'conv %', color: 'rgb(0,200,83)', font: { size: 8 } }, ticks: { color: cssVar('--text-tertiary'), font: { size: 9 } }, grid: { display: false } },
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
        plugins: { legend: { labels: { color: cssVar('--text-tertiary'), font: { size: 9 }, boxWidth: 12 } } },
        scales: {
          x: { ticks: { color: cssVar('--text-tertiary'), font: { size: 9 }, maxTicksLimit: 12, maxRotation: 0 }, grid: { color: 'rgba(94,89,82,0.10)' } },
          y: { type: 'linear', position: 'left', title: { display: true, text: 'sessions', color: 'rgb(6,214,240)' }, ticks: { color: cssVar('--text-tertiary'), font: { size: 9 }, precision: 0 }, grid: { color: 'rgba(94,89,82,0.08)' } },
          y1: { type: 'linear', position: 'right', title: { display: true, text: 'pps / queue', color: 'rgb(186,133,224)' }, ticks: { color: cssVar('--text-tertiary'), font: { size: 9 } }, grid: { display: false } },
        },
      },
    });
  }

  // ── Error rate (Issue #176) — local $0 sampler + Sentry badge ─────────
  let _adminErrorChart = null;

  function _fmtErrorTs(ts, nowArg) {
    if (!ts) return '—';
    const d = new Date(Number(ts) * 1000);
    if (isNaN(d.getTime())) return '—';
    const now = nowArg != null ? nowArg : Date.now();
    const deltaMin = Math.floor((now - d.getTime()) / 60000);
    if (deltaMin < 60) return deltaMin + 'm atrás';
    const deltaH = Math.floor(deltaMin / 60);
    if (deltaH < 48) return deltaH + 'h atrás';
    return d.toISOString().replace('T', ' ').slice(0, 16) + ' UTC';
  }

  function _renderAdminErrorRate(data) {
    const wrap = document.getElementById('admin-error-rate');
    const canvas = document.getElementById('admin-error-rate-chart');
    const empty = document.getElementById('admin-error-rate-empty');
    const tableWrap = document.getElementById('admin-error-table-wrap');
    const tbody = document.getElementById('admin-error-table-body');
    if (!wrap || !canvas || !tableWrap || !tbody) return;

    const total = data.total != null ? data.total : 0;
    _setAdminText('admin-err-total', total);
    _setAdminText('admin-err-peak', data.peak_per_hour != null ? data.peak_per_hour : '—');
    const sentryInfo = typeof data.sentry_enabled === 'boolean'
      ? (data.sentry_enabled
        ? (data.sentry_release || 'on').replace('cypher65-war-room@', '') + ' · ' + (data.sentry_environment || '?') + ' ✓'
        : 'off (self-host)')
      : '—';
    _setAdminText('admin-err-sentry', sentryInfo);

    const buckets = (data.buckets || []);
    if (_adminErrorChart) { _adminErrorChart.destroy(); _adminErrorChart = null; }
    if (empty) empty.hidden = buckets.length > 0;
    if (!buckets.length) {
      wrap.hidden = false;
      if (tableWrap) tableWrap.hidden = true;
      return;
    }

    var labels = buckets.map(function (b) {
      var d = new Date(Number(b.ts) * 1000);
      if (isNaN(d.getTime())) return '—';
      return d.getHours().toString().padStart(2, '0') + ':00';
    });
    var errors = buckets.map(function (b) { return b.errors; });
    var topMod = (data.top_modules && data.top_modules.length) ? data.top_modules[0].module : '';

    wrap.hidden = false;
    _adminErrorChart = new Chart(canvas.getContext('2d'), {
      type: 'bar',
      data: {
        labels: labels,
        datasets: [{
          label: 'Erros/hora', data: errors, backgroundColor: 'rgba(255,23,68,0.45)',
          borderColor: 'rgb(255,23,68)', borderWidth: 1, borderRadius: 3, maxBarThickness: 18,
        }],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { display: false },
          tooltip: {
            callbacks: {
              title: function (items) {
                const b = buckets[items[0].dataIndex];
                if (!b || !b.modules) return items[0].label;
                // Module names são log names — escapados mesmo assim (tooltip
                // do Chart.js renderiza como HTML; disciplina anti-XSS do repo).
                return items[0].label + ' — ' + b.modules.map(function (m) {
                  return escapeHtml(String(m.module || '')) + ' x' + m.count;
                }).join(', ');
              },
            },
          },
        },
        scales: {
          x: { ticks: { color: cssVar('--text-tertiary'), font: { size: 9 }, maxTicksLimit: 12, maxRotation: 0 }, grid: { color: 'rgba(94,89,82,0.06)' } },
          y: { beginAtZero: true, ticks: { color: cssVar('--text-tertiary'), font: { size: 9 }, precision: 0 }, grid: { color: 'rgba(94,89,82,0.08)' }, title: { display: true, text: 'erros' + (topMod ? ' · top: ' + topMod : ''), color: 'rgb(255,23,68)', font: { size: 9 } } },
        },
      },
    });

    // Recent errors table — every cell escaped (DOM guard).
    const recent = (data.recent || []);
    tableWrap.hidden = recent.length === 0;
    tbody.innerHTML = recent.map(function (r) {
      return '<tr>' +
        '<td>' + escapeHtml(String(r.module || '—')) + '</td>' +
        '<td title="' + escapeHtml(String(r.message || '')) + '">' + escapeHtml(String((r.message || '—').slice(0, 80))) + '</td>' +
        '<td>' + escapeHtml(String(r.count || 1)) + '</td>' +
        '<td class="admin-err__rid">' + escapeHtml(String(r.last_request_id || '—')) + '</td>' +
        '<td>' + escapeHtml(_fmtErrorTs(r.last_ts)) + '</td>' +
        '</tr>';
    }).join('');
  }

  // ── Degradation (Issue #202) — WARNING bucket ($0, self-host) ─────────
  // The converted `except: pass` sites now emit WARNINGs that land in
  // degradation_metrics. spike = pico >= 100/h; sustained = warnings em >= 2
  // horas distintas. Os badges são o 'alerta de taxa' sem depender de Sentry.
  function _renderAdminDegradation(data) {
    const tableWrap = document.getElementById('admin-deg-table-wrap');
    const tbody = document.getElementById('admin-deg-table-body');
    const empty = document.getElementById('admin-deg-empty');
    if (!tableWrap || !tbody) return;
    const total = data.total != null ? data.total : 0;
    const peak = data.peak_per_hour != null ? data.peak_per_hour : 0;
    _setAdminText('admin-deg-total', total);
    _setAdminText('admin-deg-peak', peak);
    const state = document.getElementById('admin-deg-state');
    if (state) {
      // Keep the kpi-card__value base class so the badge keeps its sizing.
      state.className = 'kpi-card__value badge badge--' + (data.sustained ? 'red' : (data.spike ? 'amber' : 'green'));
      state.textContent = data.sustained ? 'SUSTAINED ⚠' : (data.spike ? 'SPIKE ⚠' : (total > 0 ? 'normal' : 'ok'));
    }
    const recent = data.recent || [];
    if (empty) empty.hidden = (data.buckets || []).length > 0;
    if (!recent.length) { tableWrap.hidden = true; return; }
    tableWrap.hidden = false;
    tbody.innerHTML = recent.map(function (r) {
      return '<tr>' +
        '<td>' + escapeHtml(String(r.module || '—')) + '</td>' +
        '<td title="' + escapeHtml(String(r.message || '')) + '">' + escapeHtml(String((r.message || '—').slice(0, 80))) + '</td>' +
        '<td>' + escapeHtml(String(r.count || 1)) + '</td>' +
        '<td>' + escapeHtml(String(r.last_request_id || '—')) + '</td>' +
        '<td>' + escapeHtml(_fmtErrorTs(r.last_ts)) + '</td>' +
        '</tr>';
    }).join('');
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
    // Issue #205: ts<=0/null decisions must never vanish — surface them as a
    // visible undercount note under the chart (bar axis is weekly, so an
    // "unknown" bar would fake a date that doesn't exist).
    const note = document.getElementById('admin-audit-note');
    if (note) {
      const n = Number(weekly && weekly.withoutDate) || 0;
      note.hidden = n === 0;
      if (n > 0) {
        note.textContent = n + ' decis' + (n === 1 ? 'ão' : 'ões') + ' sem data (ts ausente ou inválido) fora do gráfico semanal';
      }
    }
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
          x: { ticks: { color: cssVar('--text-tertiary'), font: { size: 9 }, maxRotation: 0 }, grid: { display: false } },
          y: { beginAtZero: true, ticks: { color: cssVar('--text-tertiary'), font: { size: 9 }, precision: 0 }, grid: { color: 'rgba(94,89,82,0.10)' } },
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
