  // ══════════════════════════════════════════════════════════════════════
  // Automations / Alerts / Auto-Pilot / Decision Matrix
  // — domínio extraído de `40-app-logic.js` (RFC 478 · PR 6 · Issue 540)
  // ═════════════════════════════════════════════════════════════════════
  // Movimento MECÂNICO: nenhum nome, id de DOM, contrato de fetch ou formato de
  // payload mudou — as 1.073 linhas abaixo foram recortadas verbatim. Quatro
  // blocos contíguos da tabela de inventário da §3.3:
  //   · R7  — feixes de ALERTAS/EVENTOS do dashboard (`acctRankLabels`,
  //           `renderAccount`, `_staleChip`, `renderBtcPrices`, `renderHalving`,
  //           `renderMempoolFees`, `renderAlerts`, `renderEvents`,
  //           `renderLeaderboard`).
  //   · R13 — DECISION MATRIX + COMMAND CENTER (`renderDecisionMatrix`,
  //           `initDecisionMatrixControls`, `commandCenterCardHtml`,
  //           `_lastCcKey`, `renderCommandCenter`, `initCommandCenterControls`).
  //   · R16 — AUTO-PILOT: arming (`_apArmed`/`_apSetUi`/`_apSetArmed`/
  //           `_initAutoPilotToggle`/`_initAutoPilotAutoToggle`), advisory e
  //           dry-run (`_apDr*`, `_initAutoPilotDryRun`).
  //   · R26 — ALERT CENTER / AUTOMATIONS (`acState`, `severityClass`,
  //           `severityLabel`, `ac*`, `acShowTab` e o bloco de topo que injeta a
  //           tab-strip e registra os listeners).
  //
  // ⚠ POR QUE ESTE FRAGMENTO PODE VIR **DEPOIS** DO 40 (ao contrário do
  // `39-terminal.js`, que precisou vir antes) — a regra da §3.3 é sobre
  // ESTADO lido por chamada de nível de módulo, e aqui isso não acontece:
  //   · R7/R13/R16 têm ZERO statements de topo; R26 tem UM
  //     (`if (dom.openAlertCenter) { … }`), que só injeta a tab-strip e
  //     registra listeners — inerte por ordem.
  //   · o prefixo SÍNCRONO do `boot()` chama `initDecisionMatrixControls()` e
  //     `initCommandCenterControls()` (R13). São declarações de função
  //     (hoisted em todo o IIFE) e ambas leem apenas `document` — nenhum
  //     estado movido.
  //   · os 12 nomes de estado movido (`_lastCcKey`, `_apArmed`,
  //     `_apToggleInit`, `_apAuto`, `_apAutoToggleInit`, `_apRecs`, `_apAudit`,
  //     `_apRecsInit`, `_apDrInit`, `acState`, `severityClass`,
  //     `severityLabel`) não são lidos em NENHUM outro ponto do 40 fora
  //     dos blocos (a única menção é um comentário em
  //     `setHtmlIfChanged`) nem em nenhum outro fragmento.
  //   · `render()` (fica no god file) chama `renderAccount`, `renderBtcPrices`,
  //     `renderHalving`, `renderMempoolFees`, `renderDecisionMatrix`,
  //     `renderAlerts`, `renderEvents`, `renderLeaderboard`,
  //     `renderCommandCenter` e `renderAiOperator` → `_apSetUi`/
  //     `_initAutoPilot*`; esses caminhos só existem via `await
  //     fetchSnapshot()` ou pelo `onmessage` do SSE — isto é, depois de o
  //     IIFE inteiro ser avaliado.
  //   · `restoreActiveModule` (IIFE de topo) → `activateModule` →
  //     `_doActivateModule` foi varrido: não chama nenhum símbolo movido.
  //   · a direção inversa é segura por construção: 41 é avaliado depois do
  //     40, então todo `const`/`let` do god file (incl. `_lastSnapshot`) já
  //     está inicializado.
  //
  // Estado compartilhado que NÃO viajou: `_lastSnapshot` (poll/SSE escrevem;
  // terminais e AXE Fleet leem) e o estado do Fleet Command Center
  // (`_ccLastFleet`/`_ccView`/`_ccHrSeries`/`_ccHrHist`/`_ccShareSeen`, que o
  // `boot()` toca de forma síncrona antes de o 48 existir) — permanecem no
  // `40-app-logic.js`.

  // ↳ R7 — feeds de alertas/eventos do dashboard + painel de conta

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
    if (alerts == null) {
      setHtmlIfChanged(dom.alertsList, '<li class="alert-empty">loading operational alerts…</li>');
      if (dom.alertsCountBadge) dom.alertsCountBadge.textContent = 'loading';
      return;
    }
    if (!alerts || !alerts.length) {
      setHtmlIfChanged(dom.alertsList, '<li class="alert-empty">no alerts — all systems nominal</li>');
      if (dom.alertsCountBadge) dom.alertsCountBadge.textContent = '0 active';
      return;
    }
    const severityRank = { CRIT: 4, CRITICAL: 4, ERROR: 4, WARN: 3, WARNING: 3, INFO: 2, SUCCESS: 1 };
    const ordered = alerts.slice().sort((a, b) => {
      const rank = (severityRank[String(b?.severity || '').toUpperCase()] || 0) - (severityRank[String(a?.severity || '').toUpperCase()] || 0);
      return rank || (Number(b?.ts || 0) - Number(a?.ts || 0));
    });
    const criticalCount = ordered.filter(a => (severityRank[String(a?.severity || '').toUpperCase()] || 0) >= 4).length;
    if (dom.alertsCountBadge) dom.alertsCountBadge.textContent = `${alerts.length} active${criticalCount ? ' · ' + criticalCount + ' critical' : ''}`;
    setHtmlIfChanged(dom.alertsList, ordered.slice(0, 10).map(a => `
      <li class="alert-item SEVERITY-${escapeHtml(a.severity || 'INFO')}">
        <span class="alert-icon" aria-hidden="true">!</span>
        <span class="alert-msg"><strong>${escapeHtml(String(a.severity || 'INFO').toUpperCase())}</strong> · ${escapeHtml(a.message || '')}<small>${escapeHtml(a.category || 'uncategorized')}${a.device_id ? ' · ' + escapeHtml(a.device_id) : ''}</small></span>
        <span class="alert-time">${fmt.age(a.ts)}</span>
        ${a.device_id ? '<button type="button" class="chip alert-inspect" data-device-id="' + escapeHtml(a.device_id) + '">INSPECT ASIC</button>' : ''}
      </li>`).join(''));
    dom.alertsList.querySelectorAll('.alert-inspect').forEach(button => {
      button.addEventListener('click', () => {
        activateModule('fleet');
        const id = button.dataset.deviceId;
        if (id) setTimeout(() => openAxeDetail(id), 0);
      });
    });
  }

  function renderEvents(events) {
    if (!dom.eventsTbody) return;
    if (!events || !events.length) { setHtmlIfChanged(dom.eventsTbody, '<tr><td colspan="5" class="empty">awaiting data\u2026</td></tr>'); return; }
    setHtmlIfChanged(dom.eventsTbody, events.map(e => `<tr><td>#${escapeHtml(e.block_height || e.block || '\u2014')}</td><td>${escapeHtml(fmt.shortAddr(e.address || ''))}</td><td>${escapeHtml(fmt.diff(e.difficulty))}</td><td>${escapeHtml(fmt.age(e.block_timestamp || e.ts))}</td><td>${e.claimed ? 'YES' : 'NO'}</td></tr>`).join(''));
  }

  function renderLeaderboard(lb) {
    if (!dom.lbTbody) return;
    if (!lb || !lb.length) { setHtmlIfChanged(dom.lbTbody, '<tr><td colspan="6" class="empty">awaiting data\u2026</td></tr>'); return; }
    setHtmlIfChanged(dom.lbTbody, lb.map((r, i) => `<tr><td>${i+1}</td><td>${escapeHtml(fmt.shortAddr(r.address))}</td><td>${escapeHtml(r.diff_rank || r.diffRank || '\u2014')}</td><td>${escapeHtml(r.loyalty_rank || r.loyalty || '\u2014')}</td><td>${escapeHtml(r.combined_score || r.score || '\u2014')}</td><td>${escapeHtml(r.total_blocks || r.blocks || 0)}</td></tr>`).join(''));
  }

  let _lbRows = [];
  let _lbHasMore = false;
  let _lbLoading = false;
  let _lbTotal = 0;
  let _lbError = '';

  function paintLeaderboardPager() {
    const btn = document.getElementById('lb-load-more');
    const totalEl = document.getElementById('leaderboard-total');
    if (totalEl) {
      totalEl.textContent = String(_lbRows.length) + (_lbTotal > _lbRows.length ? ' / ' + _lbTotal : '') + ' miners';
    }
    if (btn) {
      btn.hidden = !_lbHasMore;
      btn.disabled = _lbLoading;
      btn.setAttribute('aria-busy', _lbLoading ? 'true' : 'false');
      btn.textContent = _lbLoading ? 'LOADING…' : (_lbError ? 'RETRY LOAD MORE' : 'LOAD MORE');
      btn.title = _lbError;
    }
  }

  function resetLeaderboardFromSnapshot(snap) {
    const rows = (snap && snap.leaderboard_table_top_30) || [];
    const head = Array.isArray(rows) ? rows.slice() : [];
    // Keep pages the operator explicitly loaded. The 15s full poll owns the
    // first 30 rows but must not collapse an expanded table back to 30.
    _lbRows = mergeLeaderboardHead(_lbRows, head);
    const total = Number(snap && snap.leaderboard_total);
    _lbTotal = isFinite(total) ? Math.max(total, _lbRows.length) : _lbRows.length;
    _lbHasMore = _lbRows.length < _lbTotal;
    _lbError = '';
    renderLeaderboard(_lbRows);
    paintLeaderboardPager();
  }

  async function loadMoreLeaderboard() {
    if (_lbLoading || !_lbHasMore) return;
    _lbLoading = true;
    _lbError = '';
    paintLeaderboardPager();
    try {
      const r = await fetch('/api/leaderboard?offset=' + _lbRows.length + '&limit=50');
      if (!r.ok) throw new Error('HTTP ' + r.status);
      const data = await r.json();
      const extra = Array.isArray(data && data.entries) ? data.entries : [];
      _lbRows = _lbRows.concat(extra);
      const total = Number(data && data.total);
      _lbTotal = isFinite(total) ? Math.max(total, _lbRows.length) : _lbRows.length;
      _lbHasMore = !!(data && data.has_more);
      renderLeaderboard(_lbRows);
    } catch (err) {
      _lbError = 'Leaderboard unavailable; click to retry.';
      logMessage('LEADERBOARD', 'Load more failed: ' + (err && err.message || 'unknown error'), 'WARN');
    } finally {
      _lbLoading = false;
      paintLeaderboardPager();
    }
  }

  function initLeaderboardPager() {
    const btn = document.getElementById('lb-load-more');
    if (!btn || btn.dataset.bound === '1') return;
    btn.dataset.bound = '1';
    btn.addEventListener('click', function () { loadMoreLeaderboard(); });
  }

  // ↳ R13 — Decision Matrix + Command Center (cards contextuais do snapshot)

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
        buyEl.innerHTML = _ic('zap', 12, true) + 'BUY ' + escapeHtml(String(aff.provider || '').toUpperCase());
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
  // cc-grid. Each card carries only an internal module/panel destination;
  // Command Center never opens commercial URLs. Pure helper mirrored in
  // tests/test_app_js_core.js.
  function commandCenterCardHtml(card) {
    if (!card || typeof card !== 'object') return '';
    const sev = String(card.severity || 'info').toLowerCase();
    const esc = escapeHtml;
    const target = String(card.target || '');
    const panel = String(card.panel || '');
    return (
      '<button type="button" class="cc-card cc-card--' + sev + '" ' +
      'data-cc-target="' + esc(target) + '" ' +
      'data-cc-panel="' + esc(panel) + '">' +
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
    const cards = (snap && Array.isArray(snap.command_center))
      ? snap.command_center.filter(function(c) {
          return c && c.id !== 'affiliate_buy' && !c.url;
        })
      : [];
    // Stable serialization key: id + severity + title + message.
    // Messages are DYNAMIC (proximity_streak embeds the live 1h trend %,
    // negative_operation embeds the $ amount) — a key of id|severity
    // alone froze the card text on the first render (reviewer catch). Only
    // skip the DOM write when the rendered text is truly identical.
    const key = cards.map(c => (c && c.id || '') + '|' + (c && c.severity || '') + '|' + (c && c.title || '') + '|' + (c && c.message || '')).join('\n');
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

  // ↳ R16 — Auto-Pilot: arming, advisory e dry-run

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
      const consent = document.getElementById('ap-arm-consent');
      const _checkArmReady = () => {
        confirm.disabled = !(input.value.trim().toUpperCase() === 'ARMAR' && consent && consent.checked);
      };
      input.addEventListener('input', _checkArmReady);
      if (consent) consent.addEventListener('change', _checkArmReady);
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
    _apRefreshAutoStatus();
  }

  // ── Issue #178 · Auto-Pilot AUTONOMOUS — execução autônoma (PRO gate) ──
  // Backend: GET /api/auto-pilot/autonomous (pro/armed/autonomous),
  // POST /api/auto-pilot/autonomous {autonomous} (gate PRO → 402 em modo
  // licensed sem chave). Fase 4 do Big Bet: quando PRO + armado + ON, o
  // piloto executa sozinho restart/pause das recomendações físicas.
  let _apAuto = false;
  let _apAutoToggleInit = false;

  function _apSetAutoUi(auto) {
    _apAuto = !!auto;
    const btn = document.getElementById('ap-auto-btn');
    const label = document.getElementById('ap-auto-label');
    const dot = document.getElementById('ap-auto-dot');
    if (label) label.textContent = auto ? 'ON' : 'OFF';
    if (btn) {
      btn.classList.toggle('is-armed', auto);
      btn.title = auto
        ? 'EXECUÇÃO AUTÔNOMA ON — o piloto executa restart/pause sozinho (PRO + armado). Clique para desligar.'
        : 'EXECUÇÃO AUTÔNOMA OFF — as recomendações ficam manuais. Clique para ligar (requer PRO + armado).';
    }
    if (dot) {
      dot.style.background = auto ? 'var(--green)' : 'var(--orange)';
      dot.style.boxShadow = auto ? '0 0 8px rgba(0,200,83,0.8)' : '0 0 6px rgba(255,160,0,0.6)';
    }
  }

  async function _apRefreshAutoStatus() {
    try {
      const r = await authFetch('/api/auto-pilot/autonomous');
      if (!r.ok) return;
      const d = await r.json().catch(() => ({}));
      _apSetAutoUi(!!d.autonomous);
      const badge = document.getElementById('ap-auto-pro-badge');
      if (badge) {
        badge.textContent = d.pro ? 'PRO ✓' : 'PRO 🔒';
        badge.classList.toggle('badge--green', !!d.pro);
        badge.classList.toggle('badge--amber', !d.pro);
        badge.title = d.pro
          ? 'Gate PRO ok — execução autônoma permitida (open mode ou licença válida)'
          : 'Gate PRO fechado — é preciso licença PRO para ligar a execução autônoma';
      }
      if (_apAuto && d.armed === false) {
        const autoBtn = document.getElementById('ap-auto-btn');
        if (autoBtn) autoBtn.title = 'Execução autônoma ON mas o Auto-Pilot está DESARMADO — arme o piloto para ativar.';
      }
    } catch (e) { /* advisory — never break the panel */ }
  }

  async function _apSetAuto(enabled) {
    const btn = document.getElementById('ap-auto-btn');
    setBtnLoading(btn, true);
    try {
      const r = await authFetch('/api/auto-pilot/autonomous', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ autonomous: enabled }),
      });
      const d = await r.json().catch(() => ({}));
      if (r.status === 402) {
        const price = d.upgrade && d.upgrade.price_usd_month ? ' ($' + d.upgrade.price_usd_month + '/m)' : '';
        showToast('error', '🔒 EXECUÇÃO AUTÔNOMA é PRO — licença necessária' + price);
        _apRefreshAutoStatus();
        return false;
      }
      if (!r.ok || !d.success) {
        showToast('error', '⚠ Auto-Pilot: ' + (d.error || ('HTTP ' + r.status)));
        _apRefreshAutoStatus();
        return false;
      }
      _apSetAutoUi(!!d.autonomous);
      showToast('success', enabled ? '🤖 EXECUÇÃO AUTÔNOMA ON — o piloto age sozinho (PRO + armado)' : 'Execução autônoma desligada');
      _apRefreshAutoStatus();
      return true;
    } catch (e) {
      showToast('error', '⚠ falha de rede ao alterar a execução autônoma');
      return false;
    } finally {
      setBtnLoading(btn, false);
    }
  }

  function _initAutoPilotAutoToggle() {
    if (_apAutoToggleInit) return;
    _apAutoToggleInit = true;

    const btn = document.getElementById('ap-auto-btn');
    if (btn) {
      btn.addEventListener('click', () => {
        if (_apAuto) { _apSetAuto(false); return; }  // disabling is the kill switch — direct
        const m = document.getElementById('ap-auto-modal');
        const input = document.getElementById('ap-auto-type');
        const confirm = document.getElementById('ap-auto-confirm');
        if (m && input && confirm) {
          input.value = '';
          confirm.disabled = true;
          openModalAnimated(m);
          setTimeout(() => input.focus(), 50);
        } else {
          _apSetAuto(true);
        }
      });
    }

    const m = document.getElementById('ap-auto-modal');
    if (m) {
      m.addEventListener('click', (e) => {
        if (e.target.matches('[data-close]') || e.target === m) closeModalAnimated(m);
      });
    }

    const input = document.getElementById('ap-auto-type');
    const confirm = document.getElementById('ap-auto-confirm');
    if (input && confirm) {
      const consent = document.getElementById('ap-auto-consent');
      const _checkAutoReady = () => {
        confirm.disabled = !(input.value.trim().toUpperCase() === 'AUTONOMO' && consent && consent.checked);
      };
      input.addEventListener('input', _checkAutoReady);
      if (consent) consent.addEventListener('change', _checkAutoReady);
      confirm.addEventListener('click', async () => {
        confirm.disabled = true;
        const ok = await _apSetAuto(true);
        const modal = document.getElementById('ap-auto-modal');
        if (modal) modal.classList.remove('modal--open');
        if (!ok) input.value = '';
      });
    }
  }

  // ── Issue #20 · Auto-Pilot ADVISORY — recomendações por device ──────
  // Backend: GET /api/auto-pilot/recommendations (recs + armed),
  // POST /api/auto-pilot/recommendations/<id>/respond {decision} (audited),
  // GET /api/auto-pilot/recommendations/audit (trail). Fase 2 do Big Bet:
  // o piloto consolida por dispositivo o que merece atenção. Aceitar uma
  // recomendação só registra a intenção e abre o módulo seguro de revisão;
  // nunca executa comando, blacklist ou compra por este painel.
  let _apRecs = [];
  let _apAudit = [];
  let _apRecsInit = false;

  function _apRecCardHtml(rec) {
    if (!rec || typeof rec !== 'object') return '';
    const esc = escapeHtml;
    const sev = String(rec.severity || 'info').toLowerCase();
    const action = (rec.action && typeof rec.action === 'object') ? rec.action : {};
    const actionType = String(action.type || 'navigate');
    const reviewLabel = actionType === 'buy' || actionType === 'blacklist'
      ? 'REVISAR EM RENTALS'
      : 'REVISAR NO FLEET';
    const rawDevice = rec.device_name || rec.device_id || 'device';
    return (
      '<div class="ap-rec ap-rec--' + esc(sev) + '" data-rec-id="' + esc(rec.id || '') + '">' +
      '<div class="ap-rec__head">' +
      '<span class="ap-rec__sev">' + esc(sev) + '</span>' +
      '<span class="ap-rec__dev">' + esc(rawDevice) + '</span>' +
      '<span class="ap-rec__type">' + esc(rec.issue_type || '') + '</span>' +
      '</div>' +
      '<div class="ap-rec__msg">' + esc(rec.message || '') + '</div>' +
      '<div class="ap-rec__actions">' +
      '<button type="button" class="btn btn--primary btn--mini ap-rec-apply" data-action-type="' + esc(actionType) + '" title="Registrar a recomendação e abrir a revisão segura; nenhuma ação será executada">' + reviewLabel + '</button>' +
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

  async function _apRespond(recId, decision, trigger) {
    const originalText = trigger ? trigger.textContent : '';
    if (trigger) {
      trigger.disabled = true;
      trigger.setAttribute('aria-busy', 'true');
      trigger.textContent = 'REGISTRANDO…';
    }
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
        showToast('error', '⚠ ' + (d.action_result.error || 'não foi possível registrar a recomendação'));
      } else if (decision === 'accept') {
        const destination = d.navigate_to === 'rentals' ? 'Rentals' : 'Fleet';
        showToast('success', '✓ recomendação auditada — revise a ação em ' + destination);
        if (d.navigate_to === 'rentals' || d.navigate_to === 'fleet') {
          activateModule(d.navigate_to);
        }
      } else {
        showToast('success', 'recomendação ignorada (auditado)');
      }
      _apLoadRecs();
    } catch (e) {
      showToast('error', '⚠ Auto-Pilot: ' + (e.message || 'falha de rede'));
    } finally {
      if (trigger && trigger.isConnected) {
        trigger.disabled = false;
        trigger.removeAttribute('aria-busy');
        trigger.textContent = originalText;
      }
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
          _apRespond(recId, 'accept', apply);
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
    return '<div class="ap-dr-banner" style="border-color:var(--accent-red);color:var(--accent-red)">' +
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

  // ↳ R26 — Alert Center / Automations (regras, execuções, histórico)

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
