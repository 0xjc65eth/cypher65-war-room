  // → domínio Billing/Auth extraído para `static/src/38-billing-auth.js` (RFC 478, Issue 545)

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
      btn.innerHTML = next === 'light' ? _ic('moon', 14) : _ic('sun', 14);
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
      btn.innerHTML = themeCurrent() === 'light' ? _ic('moon', 14) : _ic('sun', 14);
    }
  }

  // → domínios Wallet crypto (R3) e Support (R20) extraídos para `static/src/37-wallet-support.js` (RFC 478, Issue 551)

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

  // ── Flicker dedup (audit 18-Ago) ────────────────────────────────────────
  // renderMarketGrid / renderTerminalEvents / renderLeaderboard etc. wrote
  // innerHTML on EVERY 15s snapshot even when the rendered content was
  // byte-identical — destroying/recreating rows every poll ("infinite
  // blinking"). Same root cause the Command Center had (_lastCcKey fix);
  // generalize it: skip the DOM write when the serialized HTML matches the
  // last write for that element. WeakMap keyed by element keeps zero state
  // on window and auto-GCs. Returns true when the write happened.
  const _lastSetHtml = new WeakMap();
  function setHtmlIfChanged(el, html) {
    if (!el || typeof el.innerHTML !== 'string') return false;
    if (_lastSetHtml.get(el) === html) return false;
    _lastSetHtml.set(el, html);
    el.innerHTML = html;
    return true;
  }

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

  // → domínio Dashboard/render() extraído para `static/src/39b-dashboard.js` (RFC 478, Issue 561)

  // → domínio Dashboard/render() extraído para `static/src/39b-dashboard.js` (RFC 478, Issue 561)

  // → domínio Automations/Alerts/Auto-Pilot/Decision Matrix extraído para `static/src/41-automations.js` (RFC 478, Issue 540)

  function applyLiveMetrics(live) {
    const patch = liveMetricsPatch(live);
    const hr = document.getElementById('tbar-hr');
    if (hr) hr.textContent = patch.hashrateText;
    const temp = document.getElementById('tbar-temp');
    if (temp) temp.textContent = patch.tempText;
    if (dom.mHashrate) dom.mHashrate.textContent = patch.hashrateText;
    if (dom.hudHashrate) dom.hudHashrate.textContent = patch.hashrateText;
    if (dom.pHashrate) dom.pHashrate.textContent = patch.poolHashrateText;
    renderSnapshotFreshness({ ts: live && live.ts });
  }

  // → domínio Dashboard/render() extraído para `static/src/39b-dashboard.js` (RFC 478, Issue 561)

  // → domínio Terminal/SSE extraído para `static/src/39-terminal.js` (RFC 478, Issue 529)

  // → domínio Probability/Block Model extraído para `static/src/42-probability.js` (RFC 478, Issue 542)

  // → domínio Automations/Alerts/Auto-Pilot/Decision Matrix extraído para `static/src/41-automations.js` (RFC 478, Issue 540)

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
    _renderBraiinsBuyUnit();
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

  function _renderBraiinsBuyUnit() {
    // Live pricing unit + F7 bid cap (GET /api/rentals/braiins/market) — shows
    // the account's unit next to the quote and the active-bid count against
    // max_bids_per_subaccount (N/M), so a non-PH/day account AND a cap
    // situation are visible before any money moves. Never blocks the modal:
    // on failure the chip stays '—' (the 400 fail-closed in
    // create_braiins_bid is the guard).
    const el = document.getElementById('braiins-buy-unit');
    if (!el) return;
    _braiinsBuySet('braiins-buy-unit', 'unit: —');  // reset on every open — never carry a stale unit
    el.classList.remove('is-active', 'is-danger');
    fetch('/api/rentals/braiins/market')
      .then(r => (r.ok ? r.json() : null))
      .then(m => {
        const hr = m && m.market && m.market.hr_unit;
        if (!hr) return;
        const maxBids = m.market.max_bids_per_subaccount;
        const active = m.active_bids_count;
        let txt = 'unit: ' + hr;
        if (maxBids != null) {
          txt += ' · bids ' + (active != null ? active : '?') + '/' + maxBids;
        }
        el.textContent = txt;
        el.classList.add('is-active');
        // At the cap: the submit would 400 (F7) — surface it in red.
        if (maxBids != null && active != null && active >= maxBids) {
          el.classList.add('is-danger');
        }
      })
      .catch(() => {});
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
    const identity = (document.getElementById('braiins-buy-identity')?.value || '').trim();
    const submit = document.getElementById('braiins-buy-submit');
    if (submit) submit.disabled = !(quoteOk && th > 0 && amount >= 1000 && !exceeded && stratum && identity && typed && ack);
    // F4 hint: worker identity is REQUIRED (Braiins contract) — never leave
    // the operator guessing why the button is dead. Set when missing, and
    // CLEAR the hint once filled (stale-hint bug: the status must not keep
    // saying "informe a worker identity" after the field is filled).
    if (!identity && th > 0 && stratum) {
      const cur = document.getElementById('braiins-buy-status')?.textContent || '';
      if (!cur) _braiinsBuySet('braiins-buy-status', 'informe a worker identity (user.worker) para liberar a compra');
    } else if (identity) {
      const cur = document.getElementById('braiins-buy-status')?.textContent || '';
      if (cur.includes('worker identity')) _braiinsBuySet('braiins-buy-status', '');
    }
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
      // Server-side two-phase safety: validate a read-only preview first, then
      // bind the one-time confirmation token to this exact payload. The same
      // client order id is also the persistent idempotency key.
      _braiinsBuySet('braiins-buy-status', 'validando ordem (dry-run)…');
      const previewResponse = await authFetch('/api/rentals/braiins/bid', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ...body, dry_run: true }),
      });
      const preview = await previewResponse.json().catch(() => ({}));
      if (!previewResponse.ok || !preview.success || !preview.confirmation_token) {
        _braiinsBuySet('braiins-buy-status', '⚠ ' + (preview.error || 'dry-run rejeitado'));
        setBtnLoading(submit, false);
        return;
      }
      _braiinsBuySet('braiins-buy-status', 'dry-run aprovado · enviando uma única ordem…');
      const r = await authFetch('/api/rentals/braiins/bid', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Idempotency-Key': _braiinsBuyOrderId,
        },
        body: JSON.stringify({
          ...body,
          dry_run: false,
          confirmation_token: preview.confirmation_token,
        }),
      });
      const data = await r.json().catch(() => ({}));
      if (r.ok && data.success) {
        setBtnLoading(submit, false);
        _braiinsBuySet('braiins-buy-status', '✅ ordem enviada — id ' + (data.bid && data.bid.id ? data.bid.id : 'confirmada na Braiins'));
        // Conversion telemetry is recorded SERVER-SIDE on bid success
        // (single source of truth — no double counting).
      } else if (data.state === 'unknown' || data.reconciliation?.state === 'unknown') {
        _braiinsBuySet('braiins-buy-status', '⚠ resultado desconhecido — NÃO tente novamente; reconcilie com a Braiins');
        setBtnLoading(submit, false);
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
    ['braiins-buy-th', 'braiins-buy-amount', 'braiins-buy-stratum', 'braiins-buy-identity', 'braiins-buy-type']
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
    _initAutoPilotAutoToggle();
    _initAutoPilotAdvisory();
    _initAutoPilotDryRun();
  }

  // → domínio Automations/Alerts/Auto-Pilot/Decision Matrix extraído para `static/src/41-automations.js` (RFC 478, Issue 540)

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
      'difficulty': 'Network difficulty adjusts every 2016 blocks. Your best difficulty is historical context only; it is not progress toward a block.',
      'best diff': 'Best difficulty is the highest observed share difficulty. It is historical context, not progress, and does not change the next-hash odds.',
      'market': 'Hashrate market data shows rental prices from various providers. Compare costs and expected value before renting hashpower.',
      'fleet': 'Your fleet dashboard shows {fleet} devices. Each device reports hashrate, temperature, power draw, and shares. Monitor for anomalies.',
      'profitability': 'Scenario economics uses the current hashrate, difficulty, configured costs and BTC price. It is a constant-input estimate, not a profit promise.',
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

    // PREMIUM (Issue #182): o AI real (LLM via SSE) é o recurso premium.
    // Entitled quando open mode (tudo grátis) OU tier PREMIUM — e o servidor
    // tem chave de LLM configurada (ai_configured). Senão, bot local.
    function aiCanUseReal() {
      return !!(_license.ai_configured && (_license.mode === 'open' || _license.premium));
    }

    function showPremiumCta(d) {
      logMessage('PREMIUM', (d && d.error) || 'AI Operator real é PREMIUM — upgrade necessário', 'WARN');
      openUpgradeModal();
    }

    // Streams /api/ai/query (SSE). On success morphs typingDiv into the real
    // answer; returns true when a real response was shown (text or a handled
    // provider error). False → caller falls back to the local bot.
    async function tryRealAi(text, typingDiv) {
      // Timeout: um LLM pendurado não pode deixar o indicador de typing
      // para sempre — aborta após 45s e o caller cai no bot local.
      const ctrl = (typeof AbortController !== 'undefined') ? new AbortController() : null;
      const timer = ctrl ? setTimeout(function () { try { ctrl.abort(); } catch (e) {} }, 45000) : null;
      try {
        const r = await authFetch('/api/ai/query', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ query: text }),
          signal: ctrl ? ctrl.signal : undefined,
        });
        if (!r.ok) {
          if (r.status === 402) {
            const d = await r.json().catch(() => ({}));
            if (d && d.required_tier === 'premium') showPremiumCta(d);
          }
          return false;
        }
        if (!r.body || !r.body.getReader) return false;
        const reader = r.body.getReader();
        const decoder = new TextDecoder();
        let buf = '';
        let acc = '';
        let sawText = false;
        let sawError = false;
        const contentEl = document.createElement('div');
        contentEl.className = 'ai-msg__content';
        typingDiv.innerHTML = '<div class="ai-msg__header">◆ CYPHER AI</div>';
        typingDiv.appendChild(contentEl);
        for (;;) {
          const { done, value } = await reader.read();
          if (done) break;
          buf += decoder.decode(value, { stream: true });
          let idx;
          while ((idx = buf.indexOf('\n\n')) !== -1) {
            const raw = buf.slice(0, idx).trim();
            buf = buf.slice(idx + 2);
            if (!raw.startsWith('data:')) continue;
            let obj = {};
            try { obj = JSON.parse(raw.slice(5).trim()); } catch (e) { continue; }
            if (obj.type === 'text') {
              sawText = true;
              acc += obj.content || '';
              contentEl.textContent = acc;
              messages.scrollTop = messages.scrollHeight;
            } else if (obj.type === 'error') {
              sawError = true;
              contentEl.textContent = obj.message || 'AI error';
            } else if (obj.type === 'done') {
              break;
            }
          }
        }
        if (!sawText && !sawError) return false;
        return true;
      } catch (e) {
        return false;  // aborted (timeout), rede ou 5xx → fallback pro bot local
      } finally {
        if (timer) clearTimeout(timer);
      }
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

        // Real AI (PREMIUM/open mode) ou bot local — nunca quebra o chat.
        let usedReal = false;
        if (aiCanUseReal()) {
          usedReal = await tryRealAi(text, typingDiv);
        }
        if (!usedReal) {
          // Brief processing delay (bot local)
          await new Promise(r => setTimeout(r, 200 + Math.random() * 300));
          typingDiv.remove();
          const response = getResponse(text);
          const formatted = response.replace(/\*\*(.*?)\*\*/g, '<strong style="color:var(--accent-btc)">$1</strong>');
          addMessage('assistant', formatted);
        }
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

  // → domínio Dashboard/render() extraído para `static/src/39b-dashboard.js` (RFC 478, Issue 561)

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
      const val = s.secret ? '' : ((s.value !== undefined && s.value !== null && s.value !== '') ? s.value : s.default);
    const label = escapeHtml(s.label || k);
    const hint = SETTINGS_HINTS[k] ? `<small style="color:${cssVar('--text-tertiary')};font-size:10px;line-height:1.3">${escapeHtml(SETTINGS_HINTS[k])}</small>` : '';
    if (SETTINGS_SELECTS[k]) {
      const opts = SETTINGS_SELECTS[k].map(o => `<option value="${o}" ${String(val)===o?'selected':''}>${o}</option>`).join('');
      html += `<label style="display:flex;flex-direction:column;gap:2px;font-size:11px"><span>${label}</span><select name="${k}" class="field__input">${opts}</select>${hint}</label>`;
    } else if (SETTINGS_CHECKBOX[k]) {
      html += `<label style="display:flex;gap:6px;font-size:11px;align-items:center"><input type="checkbox" name="${k}" ${String(val)==='1'?'checked':''}> ${label}${hint}</label>`;
    } else {
      const inputType = s.secret ? 'password' : 'text';
      const placeholder = s.secret && s.configured ? 'Configurado — deixe vazio para preservar' : '';
      const configured = s.secret && s.configured ? '<small class="settings-secret-state">✓ configurado · valor nunca é retornado pelo servidor</small>' : '';
      html += `<label style="display:flex;flex-direction:column;gap:2px;font-size:11px"><span>${label}</span><input type="${inputType}" name="${k}" value="${escapeHtml(String(val ?? ''))}" placeholder="${escapeHtml(placeholder)}" autocomplete="new-password" class="field__input">${configured}${hint}</label>`;
    }
    });
    // Credential sanity helpers for the RENTALS providers. Env-var override
    // warning: on a deployed instance (Render) BRAIINS_API_KEY set in the
    // environment silently wins over this field — tell the operator, or they
    // edit the field, nothing changes, and the panel keeps saying "rejected".
    if ((SETTINGS_CACHE.env || {}).braiins_api_key && settings['braiins_api_key']) {
      html += '<div style="margin-top:2px;border:1px solid var(--accent-orange);border-radius:4px;padding:6px 8px;font-size:10px;line-height:1.4;color:var(--text-muted)">⚠ O servidor tem <code>BRAIINS_API_KEY</code> definida como env var — ela <b>SOBRESCREVE</b> o valor abaixo. Remova a env var (Render → Environment) para usar a chave do Settings.</div>';
    }
    // Same override warning for the MRR key/secret pair (Issue #189): the
    // per-user model is Settings-only — env vars are a default-tenant trap
    // that silently wins over the fields below.
    const mrrEnv = (SETTINGS_CACHE.env || {}).mrr_api_key || (SETTINGS_CACHE.env || {}).mrr_api_secret;
    if (mrrEnv && (settings['mrr_api_key'] || settings['mrr_api_secret'])) {
      html += '<div style="margin-top:2px;border:1px solid var(--accent-orange);border-radius:4px;padding:6px 8px;font-size:10px;line-height:1.4;color:var(--text-muted)">⚠ O servidor tem <code>MRR_API_KEY/MRR_API_SECRET</code> como env var — elas <b>SOBRESCREVEM</b> os valores abaixo. Remova as env vars (Render → Environment) para usar as chaves do Settings.</div>';
    }
    // "Test connection" for Braiins: probes the live API and reports the same
    // verdict the RENTALS panel derives (ok / rejected / missing).
    if (settings['braiins_api_key']) {
      html += '<div style="display:flex;align-items:center;gap:6px;margin-top:2px;flex-wrap:wrap">' +
        '<button type="button" class="btn btn--primary btn--mini" id="braiins-test">' + _ic('key', 12, true) + 'TESTAR CHAVE BRAIINS</button>' +
        '<span id="braiins-test-status" style="font-size:10px;color:var(--text-muted)"></span>' +
        '</div>';
    }
    if (settings['mrr_api_key'] && settings['mrr_api_secret']) {
      html += '<div style="display:flex;align-items:center;gap:6px;margin-top:2px;flex-wrap:wrap">' +
        '<button type="button" class="btn btn--primary btn--mini" id="mrr-test">' + _ic('key', 12, true) + 'TESTAR MRR (READ-ONLY)</button>' +
        '<span id="mrr-test-status" style="font-size:10px;color:var(--text-muted)"></span>' +
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
        '<pre id="wh-preview-payload" style="background:' + cssVar('--bg-input') + ';padding:6px;border-radius:4px;font-size:9px;line-height:1.5;overflow:auto;margin:6px 0;max-height:140px;color:var(--green)"></pre>' +
        '<div style="display:flex;align-items:center;gap:6px;flex-wrap:wrap">' +
        '<button type="button" class="btn btn--primary btn--mini" id="wh-send-test">' + _ic('send', 12, true) + 'ENVIAR TESTE</button>' +
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
        '<button type="button" class="btn btn--primary btn--mini" id="ae-send-test">' + _ic('flask', 12, true) + 'TESTAR ALERTA</button>' +
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
    const mrrTestBtn = document.getElementById('mrr-test');
    if (mrrTestBtn) {
      mrrTestBtn.addEventListener('click', async function() {
        const st = document.getElementById('mrr-test-status');
        if (st) { st.textContent = 'testando /whoami…'; st.style.color = 'var(--text-muted)'; }
        const ctrl = new AbortController();
        const timer = setTimeout(() => ctrl.abort(), 20000);
        try {
          const r = await authFetch('/api/settings/test-mrr', { method: 'POST', signal: ctrl.signal });
          const d = await r.json();
          if (!st) return;
          const labels = {
            accepted: '✓ credenciais aceitas pelo MRR',
            missing: '✗ key e secret não estão configuradas',
            rejected: '✗ MRR rejeitou a credencial — regenere o par key/secret',
            timeout: '✗ timeout ao alcançar o MRR',
            provider_unavailable: '✗ MRR indisponível ou resposta inválida',
            upstream_error: '✗ MRR respondeu HTTP ' + (d.http_status || 'erro'),
            unexpected_response: '✗ resposta de autenticação não reconhecida',
          };
          st.textContent = labels[d.status] || ('✗ diagnóstico: ' + (d.status || 'erro'));
          if (d.env_override) st.textContent += ' · credencial vem da env var';
          st.style.color = d.status === 'accepted' ? 'var(--green)' : 'var(--accent-red)';
        } catch (e) {
          if (st) { st.textContent = e.name === 'AbortError' ? '✗ timeout local (20s)' : '✗ network error'; st.style.color = 'var(--accent-red)'; }
        } finally {
          clearTimeout(timer);
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

  // → domínios Wallet crypto (R3) e Support (R20) extraídos para `static/src/37-wallet-support.js` (RFC 478, Issue 551)

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

  // → domínio Terminal/SSE extraído para `static/src/39-terminal.js` (RFC 478, Issue 529)
  // FLEET COMMAND CENTER state (fleet-fed panel).
  let _ccLastFleet = [];
  let _ccView = 'grid';
  const _ccHrSeries = [];   // fleet total-HR history (KPI sparkline)
  const _ccHrHist = {};     // per-device HR history (card sparklines)
  const _ccShareSeen = {};  // ticker share dedupe (by ts)
  // → domínio Terminal/SSE extraído para `static/src/39-terminal.js` (RFC 478, Issue 529)

  // → domínio Terminal/SSE extraído para `static/src/39-terminal.js` (RFC 478, Issue 529)

  // → domínio Dashboard/render() extraído para `static/src/39b-dashboard.js` (RFC 478, Issue 561)

  // ── Boot ──
  async function boot() {
    initCharts(); bindChartRanges(); loadSettings(); initMarketControls(); initDecisionMatrixControls(); initCommandCenterControls(); initOperationalOverviewControls(); _initRentalsPanel();
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
    // Sev-1 watchdog (UI audit 2026-08): the first fetch has NO timeout — if
    // it hangs (network blackout, proxy stall) the boot skeletons would stay
    // forever. Force-hide after 20s so the panels degrade to their honest
    // empty/error state instead of a frozen skeleton screen.
    setTimeout(function () { hideSkeletons(); }, 20000);
    initLeaderboardPager();
    initFleetCommandCenterControls();
    // UMA vez. Havia duas chamadas idênticas aqui (artefato de merge), então
    // TODO botão do Fleet ganhava dois listeners no boot: como cada
    // `initAxeFleetControls()` tem o próprio estado, o `if (phase === 'working')`
    // de um não bloqueava o outro. Nos handlers idempotentes passou despercebido;
    // no REVOKE AGENTS (Issue #582) significava revogar duas vezes com um clique —
    // o segundo incremento mataria também o token recém-gerado pelo usuário.
    // Achado pelo e2e `agent-revoke.spec.js` (contagem de POSTs).
    initAxeFleetControls();
    initAuth();
    initThemeToggle();
    initInstanceIndicator();
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
            var msg = JSON.parse(e.data);
            if (msg && msg.type === 'live') {
              applyLiveMetrics(msg);
              return;
            }
            if (msg && msg.ts) {
              _lastSnapshot = msg;
              render(msg);
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

  // → domínio Automations/Alerts/Auto-Pilot/Decision Matrix extraído para `static/src/41-automations.js` (RFC 478, Issue 540)

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
    'probability': { title: 'BLOCK MODEL',   desc: 'Estatísticas por janela · sem prazo ou previsão' },
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
  // ── Beta analytics: self-hosted usage tracking (Issue #353) ──
  const ANALYTICS_MIN_INTERVAL_MS = 1100;
  const _analytics = {
    _lastModule: null,
    _lastModuleTs: 0,
    _lastSentAt: 0,
    _flushTimer: 0,
    _queue: [],
  };
  function analyticsNextDelay(lastSentAt, nowMs) {
    return Math.max(0, ANALYTICS_MIN_INTERVAL_MS - (nowMs - lastSentAt));
  }
  function _sendBetaAnalytics(event, meta) {
    try {
      if (navigator.sendBeacon) {
        const blob = new Blob([JSON.stringify({ event: event, meta: meta || {} })],
          { type: 'application/json' });
        navigator.sendBeacon('/api/analytics/track', blob);
      } else {
        fetch('/api/analytics/track', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ event: event, meta: meta || {} }),
          keepalive: true,
        }).catch(function() {});
      }
    } catch(e) {}
  }
  function _flushBetaAnalytics() {
    if (!_analytics._queue.length) return;
    const delay = analyticsNextDelay(_analytics._lastSentAt, Date.now());
    if (delay > 0) {
      if (!_analytics._flushTimer) {
        _analytics._flushTimer = window.setTimeout(function() {
          _analytics._flushTimer = 0;
          _flushBetaAnalytics();
        }, delay);
      }
      return;
    }
    const next = _analytics._queue.shift();
    _analytics._lastSentAt = Date.now();
    _sendBetaAnalytics(next.event, next.meta);
    if (_analytics._queue.length) _flushBetaAnalytics();
  }
  function _betaTrack(event, meta) {
    // The server remains the abuse-control authority. This small client queue
    // avoids known-good dashboard navigation creating visible 429 responses.
    _analytics._queue.push({ event: event, meta: meta || {} });
    _flushBetaAnalytics();
  }
  function _betaTrackModuleSwitch(toMod) {
    var prev = _analytics._lastModule;
    var prevTs = _analytics._lastModuleTs;
    var now = Date.now();
    if (prev && prevTs) {
      var secs = Math.round((now - prevTs) / 1000);
      if (secs > 0 && secs < 3600) {
        _betaTrack('module_time', { module: prev, seconds: secs });
      }
    }
    _analytics._lastModule = toMod;
    _analytics._lastModuleTs = now;
    _betaTrack('module_switch', { from: prev || '(boot)', to: toMod });
  }

  // Boot event
  (function() {
    try {
      _betaTrack('boot', {
        vw: (window.innerWidth || 0) + 'x' + (window.innerHeight || 0),
        ua: navigator.userAgent ? navigator.userAgent.substring(0, 128) : '',
        ts: Date.now(),
      });
    } catch(e) {}
  })();

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
    // Beta analytics: track module switch + time in previous module
    try { _betaTrackModuleSwitch(name); } catch(e) {}
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
    // (o `renderKpiCards()` citado abaixo mora hoje no `39b-dashboard.js`)
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
        '<button type="button" class="doc-feedback__btn doc-feedback__btn--yes" data-helpful="1" title="Yes — it helped">' + _ic('thumbsUp', 12, true) + 'Yes</button>' +
        '<button type="button" class="doc-feedback__btn doc-feedback__btn--no" data-helpful="0" title="No — could be better">' + _ic('thumbsDown', 12, true) + 'No</button>' +
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

  // → domínio Dashboard/render() extraído para `static/src/39b-dashboard.js` (RFC 478, Issue 561)

  // ── Close the main IIFE (opened at the top of the file) ──
  // Every handler above lives INSIDE this scope so `dom`, `fmt`, etc. resolve
  // correctly. Do not add code after this line. (O `renderKpiCards()` — citado
  // aqui até o PR 9 — saiu para `static/src/39b-dashboard.js` no PR 10, RFC 478
  // · Issue 561.)
