  // ══════════════════════════════════════════════════════════════════════
  // Hashrate Market — domínio extraído de `40-app-logic.js`
  // ══════════════════════════════════════════════════════════════════════
  // RFC 478 · PR 2 (Issue 513). Movimento MECÂNICO: nenhum nome, id de DOM,
  // contrato de fetch, formato de snapshot ou ordem de execução mudou — as
  // três regiões abaixo foram recortadas verbatim.
  //
  // O `MANIFEST` de `scripts/build_app_js.cjs` É a ordem de execução do IIFE,
  // e este fragmento é o último antes de `50-close.js`. Isso é seguro porque
  // as regiões movidas contêm só DECLARAÇÕES: nenhuma lê o estado do market
  // durante a avaliação. Todos os consumidores vivem em funções que rodam
  // depois (`render()` no poll, `boot()` no DOM-ready, `_doActivateModule()`
  // na troca de aba), quando o IIFE já foi avaliado por inteiro — o `let`
  // deste bloco nunca é lido em TDZ.
  //
  // Regiões movidas (linhas originais):
  //   R1  3416–3428  estado do módulo
  //   R2  4487–4792  helpers de preço + grid institucional + renderMarket
  //   R3  4936–5044  controles (filtros/sort/BUY afiliado) + tendência 7d
  //
  // NÃO fazem parte deste domínio (permaneceram em `40-app-logic.js`):
  //   * Admin/CFO/CRO .................... 3437–4551
  //   * Decision Matrix + Command Center .. 4794–4935
  // ══════════════════════════════════════════════════════════════════════

  // ── Hashrate Market render ──
  // Backend schema: offers carry `price_per_th_day` (BTC/TH/day, often ~1e-8..1e-10).
  // The old field name `price_btc_per_th_day` never exists in the payload, which
  // made every card render '—'. `is_best` is NOT sent by the backend, so the
  // best offer is derived client-side from the highest metrics.score (ROI),
  // falling back to the lowest valid price_per_th_day.
  let _mktFilter = 'all';
  let _mktOffers = [];
  let _mktBtcUsd = null;  // BTC/USD from snapshot — for the USD/TH/d line on cards
  let _mktAffiliate = null;  // market_data.affiliate {provider,url,...} — one-click BUY on the offer card
  let _mktSnapTs = 0;  // top-level snapshot ts — when the whole /api/snapshot was generated
  let _mktTrendLoaded = false;  // lazy: /api/market/trend fetched on first module activation
  let _mktInstitutional = null;  // HashratePulse institutional view {regime, snapshot, venues, notes}

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

  // Render cap (Issue #185): the venue list can grow past 50 rows; the DOM
  // only renders the top-50 of the CURRENT sort. The full count stays honest
  // in the badge and a visible note explains the truncation (never silent).
  const MKT_RENDER_CAP = 50;

  // Pure helper (mirrored in tests/test_app_js_core.js).
  function _mktRenderCap(venues, cap) {
    const total = (venues || []).length;
    const rows = total > cap ? (venues || []).slice(0, cap) : (venues || []);
    return { rows, total, capped: total > cap };
  }

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
      if (k === 'sats') return v.price_sats_th_day != null ? Number(v.price_sats_th_day) : NaN;
      if (k === 'roi') return v.roi_pct != null ? Number(v.roi_pct) : NaN;
      if (k === 'ev') return v.expected_value_btc != null ? Number(v.expected_value_btc) : NaN;
      if (k === 'cost') return v.estimated_cost_btc != null ? Number(v.estimated_cost_btc) : NaN;
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
    if (!tbody) return;  // Issue #186: Chart.js é defer agora — o DOM nunca é
    // bloqueado pelo CDN; se o tbody ainda não existe, o próximo poll
    // (renderMarket → renderMarketGrid) re-renderiza sozinho.

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

    // Snapshot freshness — how long since the whole /api/snapshot payload
    // was generated (top-level ts stamped by the polling loop). Same badge
    // pattern as per-venue freshness (M4): '—' on legacy payloads, stale
    // when > 10 min. Written via setHtmlIfChanged so a fresh poll every 15s
    // doesn't rewrite the summary DOM (anti-flicker dedup).
    const snapAgeEl = document.getElementById('mkt-snap-age');
    if (snapAgeEl) {
      const snapFresh = venueFreshness(_mktSnapTs);
      const snapAgeHtml = snapFresh
        ? '<span class="mkt-table__fresh' + (snapFresh.stale ? ' mkt-table__fresh--stale' : '') + '" title="snapshot generated ' + new Date(_mktSnapTs * 1000).toLocaleTimeString() + ' (' + snapFresh.mins + 'm ago)">snapshot ' + (snapFresh.stale ? 'STALE ' + snapFresh.mins + 'm' : snapFresh.mins + 'm') + '</span>'
        : '';
      setHtmlIfChanged(snapAgeEl, snapAgeHtml);
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
      setHtmlIfChanged(tbody, '<tr><td colspan="12" class="mkt-table__empty">' + (_mktOffers.length ? 'no venues for selected filter' : 'no market data — configure API keys in Settings') + '</td></tr>');
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

    // Render cap: keep the full sorted list for the honest count badge, but
    // render only the top-50 in the DOM. The note makes the truncation
    // explicit (Issue #185) — same pattern as the admin audit undercount.
    const mktCap = _mktRenderCap(venues, MKT_RENDER_CAP);
    const capNoteEl = document.getElementById('mkt-render-cap-note');
    if (capNoteEl) {
      capNoteEl.hidden = !mktCap.capped;
      if (mktCap.capped) {
        const _capText = 'mostrando as ' + mktCap.rows.length + ' melhores venues do sort atual — ' + mktCap.total + ' venues no total (use sort/filtro para refinar)';
        if (capNoteEl.textContent !== _capText) capNoteEl.textContent = _capText;
      }
    }

    // Institutional Notes
    const notes = inst.notes || [];
    const notesEl = document.getElementById('mkt-notes');
    const notesBody = document.getElementById('mkt-notes-body');
    if (notesEl && notesBody) {
      if (notes.length) {
        notesEl.style.display = 'block';
        setHtmlIfChanged(notesBody, notes.map(n => '<div class="mkt-notes__item">' + escapeHtml(n) + '</div>').join(''));
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

    // M4: freshness — how OLD this venue's quote really is (fetched_at from
    // the backend stamp). Shows '—' on legacy payloads; stale when > 10 min.
    function venueFreshness(fetchedAt) {
      if (!fetchedAt) return null;
      const mins = Math.max(0, Math.floor((Date.now() / 1000 - fetchedAt) / 60));
      return { mins, stale: mins > 10 };
    }
    // M2: provider metadata surfaced as a hover detail line (asks/bids/rigs/
    // orders/pool stats the fetchers already attach — never exposed before).
    function venueMetaDetail(v) {
      const m = v.meta || {};
      const bits = [];
      if (m.available_asks != null) bits.push('asks ' + m.available_asks);
      if (m.available_bids != null) bits.push('bids ' + m.available_bids);
      if (m.total_listings != null) bits.push(m.total_listings + ' rigs');
      if (m.rig_name) bits.push(String(m.rig_name));
      if (m.available_orders != null) bits.push(m.available_orders + ' orders');
      if (m.pool_hashrate_hs != null) bits.push('pool ' + fmt.hashrate(m.pool_hashrate_hs));
      // No escaping here — the whole string is escapeHtml()'d once at the
      // title attribute (double-escaping would show literal '&amp;').
      return bits.join(' · ');
    }

    setHtmlIfChanged(tbody, mktCap.rows.map(v => {
      const tierCls = v.risk_tier === 1 ? 'mkt-table__tier--t1' : v.risk_tier === 2 ? 'mkt-table__tier--t2' : v.risk_tier === 3 ? 'mkt-table__tier--t3' : 'mkt-table__tier--t4';
      const spreadCls = v.spread_vs_best_pct <= 2 ? 'mkt-table__spread--tight' : v.spread_vs_best_pct > 20 ? 'mkt-table__spread--wide' : '';
      const recCls = v.recommendation.indexOf('Preferred') === 0 ? 'mkt-table__rec--best' : v.recommendation.indexOf('Avoid') === 0 ? 'mkt-table__rec--avoid' : '';
      const metaDetail = venueMetaDetail(v);
      // M1: sats/TH·h — the unit Braiins actually bills (price_sats_th_day is
      // sats/TH/day; ÷24 → the per-hour rate shown in the buy modal).
      const satsPerThH = v.price_sats_th_day != null ? Number(v.price_sats_th_day) / 24 : null;
      const roi = v.roi_pct != null ? (v.roi_pct >= 0 ? '+' : '') + v.roi_pct + '%' : '—';
      const roiCls = v.roi_pct != null ? (v.roi_pct >= 0 ? 'mkt-table__roi--pos' : 'mkt-table__roi--neg') : '';
      const ev = v.expected_value_btc != null ? Number(v.expected_value_btc).toFixed(8) : '—';
      // Estimated cost for the standard 1-day rental (metrics) — what this
      // venue actually charges to deploy 1 TH for the offer's duration.
      const costBtc = v.estimated_cost_btc != null ? Number(v.estimated_cost_btc).toFixed(8) : '—';
      const fresh = venueFreshness(v.fetched_at);
      const freshBadge = fresh
        ? '<span class="mkt-table__fresh' + (fresh.stale ? ' mkt-table__fresh--stale' : '') + '" title="quote fetched ' + fresh.mins + 'm ago">' + (fresh.stale ? 'STALE ' + fresh.mins + 'm' : fresh.mins + 'm') + '</span>'
        : '';
      const venueTitle = [v.venue + (v.estimated ? ' (modeled)' : ''), metaDetail].filter(Boolean).join(' · ');
      return `<tr>
        <td data-label="Venue"><span class="mkt-table__venue" title="${escapeHtml(venueTitle)}">${escapeHtml(v.venue)}</span>${v.estimated ? ' <span class="mkt-table__est">EST</span>' : ''}${freshBadge}</td>
        <td class="mono" data-label="Price">${v.price_btc_ph_day.toFixed(6)}</td>
        <td class="mono" data-label="USD/TH/d">${v.price_usd_th_day != null ? '$' + v.price_usd_th_day.toFixed(4) : '—'}</td>
        <td class="mono" data-label="sats/TH·h">${satsPerThH != null ? satsPerThH.toFixed(2) : '—'}</td>
        <td class="mono ${spreadCls}" data-label="vs Best">${v.spread_vs_best_pct >= 0 ? '+' : ''}${escapeHtml(v.spread_vs_best_pct)}%</td>
        <td class="mono" data-label="vs 4h VWAP">${v.spread_vs_vwap_pct >= 0 ? '+' : ''}${escapeHtml(v.spread_vs_vwap_pct)}%</td>
        <td class="mono" data-label="Available">${escapeHtml(v.available_ph)} PH/s</td>
        <td class="mono ${roiCls}" data-label="Modeled Return Ratio">${roi}</td>
        <td class="mono" data-label="Modeled Net (BTC)">${ev}</td>
        <td class="mono" data-label="Est. Cost (BTC)" title="est. cost for the offer's listed duration">${costBtc}</td>
        <td data-label="Risk Tier"><span class="mkt-table__tier ${tierCls}">${escapeHtml(v.risk_tier_label)}</span></td>
        <td class="${recCls}" data-label="Recommendation">${escapeHtml(v.recommendation)}</td>
      </tr>`;
    }).join(''));
  }

  function renderMarket(snap) {
    const mkt = snap.market_data || {};
    _mktOffers = mkt.offers || [];
    _mktBtcUsd = Number(snap.btc_price && snap.btc_price.usd) || null;
    _mktAffiliate = mkt.affiliate || null;
    _mktInstitutional = mkt.institutional || null;
    _mktSnapTs = Number(snap && snap.ts) || 0;
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
      if (typeof Chart === 'undefined') return false;  // Issue #186: defer — próximo poll re-tenta
      const ctx = canvas.getContext('2d');
      if (window._mktTrendChart) window._mktTrendChart.destroy();
      window._mktTrendChart = new Chart(ctx, {
        type: 'line',
        data: { labels, datasets },
        options: { responsive: true, maintainAspectRatio: false, scales: { x: { ticks: { color: cssVar('--text-tertiary'), maxTicksLimit: 8 } }, y: { ticks: { color: cssVar('--text-tertiary') } } }, plugins: { legend: { display: false } } }
      });
      return true;
    } catch (e) { return false; }
  }
