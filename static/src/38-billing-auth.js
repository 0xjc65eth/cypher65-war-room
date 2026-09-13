  // ═════════════════════════════════════════════════════════════════════
  // Billing / Auth
  // — domínio extraído de `40-app-logic.js` (RFC 478 · PR 8 · Issue 545)
  // ═════════════════════════════════════════════════════════════════════
  // Movimento MECÂNICO: nenhum nome, id de DOM, contrato de fetch ou formato de
  // payload mudou — as 924 linhas abaixo foram recortadas verbatim. Cobre:
  //   · SESSÃO/TENANT (`AUTH_SESSION_KEY`, `authLoadSession`/`authSaveSession`/
  //     `authClearSession`, `authBuildHeaders`, `authFetch`, `authRefresh`,
  //     `authLogin`, `authLogout`, `authUpdateUi`, `authIsExpired`,
  //     `authSessionValid`, `authGetToken`, `initAuth`).
  //   · LICENÇA/PRO (`LICENSE_STORAGE_KEY`, `licenseKey`, `_license`,
  //     `fetchLicenseStatus`, `initLicensing`, `renderLicenseBadge`,
  //     `syncAiPremiumUi`, `redeemLicenseKey`, `handleLicenseRequired`).
  //   · FUNIL + UPGRADE on-chain (`funnelId`, `trackConversionEvent`,
  //     `openUpgradeModal`/`closeUpgradeModal`/`syncUpgradeModal`, `buyUpgrade`/
  //     `buyPro`, `_btcUpgrade`, `_upgradeTab`, `setUpgradeTab`,
  //     `startBtcUpgrade`, `pollBtcStatus`, `startBtcCountdown`, `copyBtcPayload`,
  //     `payBtcWithWebLN`, `applyUpgradeKey`, `renderBtcPending`).
  //   · INDICADOR DE INSTÂNCIA (`instanceClassify`, `initInstanceIndicator`).
  //
  // ⚠ POR QUE ESTE FRAGMENTO VEM **ANTES** DO 40 — ao contrário do 41 e do 42, e
  // como o `39-terminal.js`. A regra da §3.3 é sobre ESTADO lido por chamada
  // de nível de módulo, e o prefixo SÍNCRONO do `boot()` (dentro do 40) lê
  // este domínio diretamente:
  //   · `initLicensing()` → `_license` (`let`), via `renderLicenseBadge()`,
  //     `syncUpgradeModal()`, `syncAiPremiumUi()` e `_initUpgradeBindings()`;
  //   · `initAuth()` → `AUTH_SESSION_KEY` + `authSessionValid`/`authUpdateUi`;
  //   · `initInstanceIndicator()` → estado/DOM do indicador.
  // Com o fragmento DEPOIS do 40, esses `let`/`const` estariam em TDZ nesse
  // instante → `ReferenceError` no boot.
  //
  // Além disso é a ORDEM ORIGINAL: o R1 era o topo do god file (linha 1),
  // ANTES do bloco de terminal (linha 2.540+). Como o `39-terminal.js` já está
  // antes do 40, entrar como `38` restaura a ordem relativa do arquivo original
  // — e o error boundary do 39 volta a cobrir a avaliação deste domínio,
  // exatamente como cobria antes do split.
  //
  // Verificações feitas antes de mover: 1 statement de topo na faixa
  // (`window.openUpgradeModal = openUpgradeModal;`, que só atribui uma
  // referência de função); ZERO declarações/statements em coluna 0; nenhuma
  // linha de nível de módulo daqui lê estado definido mais adiante no IIFE;
  // zero colisão dos 7 nomes de estado com os outros 13 fragmentos; e o único
  // consumo externo do estado (`_license` em `aiCanUseReal()`, aninhada no
  // `_initAiChat` do god file) é caminho de runtime, não de módulo.

  // ── Tenant Auth (Fase 4 · B1-frontend) ─────────────────────────────
  // Stores the JWT session in localStorage and attaches
  // `Authorization: Bearer <token>` to every /api/axe-fleet/* request so
  // the backend's require_tenant() isolates per tenant.
  // Pure helpers below (authBuildHeaders/authIsExpired/authSessionValid)
  // are mirrored in tests/test_app_js_core.js.
  const AUTH_SESSION_KEY = '_cypher65_auth_session';

  function authLoadSession() {
    try {
      const raw = localStorage.getItem(AUTH_SESSION_KEY);
      if (!raw) return null;
      const s = JSON.parse(raw);
      return (s && s.access_token) ? s : null;
    } catch (e) { return null; }
  }
  function authSaveSession(s) {
    try { localStorage.setItem(AUTH_SESSION_KEY, JSON.stringify(s)); } catch (e) {}
  }
  function authClearSession() {
    try { localStorage.removeItem(AUTH_SESSION_KEY); } catch (e) {}
  }

  // R1 (PRO tier): the operator's license key rides along on every API call
  // via X-License-Key (persisted in localStorage by initLicensing). Open
  // mode (no PRO_LICENSE_KEYS on the server) ignores it — this header only
  // matters once the gate is active.
  const LICENSE_STORAGE_KEY = '_cypher65_license';
  function licenseKey() {
    try { return localStorage.getItem(LICENSE_STORAGE_KEY) || ''; } catch (e) { return ''; }
  }
  function authBuildHeaders(token) {
    const h = {};
    const lk = licenseKey();
    if (lk) h['X-License-Key'] = lk;
    if (token) h['Authorization'] = 'Bearer ' + token;
    return h;
  }
  // PRO licensing state (open/free/pro) — populated by initLicensing() on
  // boot and used to render the topbar badge + upgrade CTA on 402s.
  let _license = {
    mode: 'loading', tier: 'free', pro: false, premium: false,
    ai_configured: false, checkout_state: 'loading', payment_state: 'not_started',
  };
  async function fetchLicenseStatus(candidateKey) {
    const headers = {};
    const key = typeof candidateKey === 'string' ? candidateKey : licenseKey();
    if (key) headers['X-License-Key'] = key;
    const r = await fetch('/api/license-status', { headers: headers });
    if (!r.ok) throw new Error('license status unavailable');
    return r.json();
  }
  async function initLicensing() {
    try {
      _license = await fetchLicenseStatus();
    } catch (e) {
      _license = {
        mode: 'error', tier: 'free', pro: false, premium: false,
        checkout_state: 'error', payment_state: 'error', ai_configured: false,
      };
    } finally {
      renderLicenseBadge();
      syncUpgradeModal();
      syncAiPremiumUi();
      _initUpgradeBindings();
    }
  }
  function renderLicenseBadge() {
    const badge = dom.topbarProBadge;
    if (!badge) return;
    if (_license.mode === 'open' || _license.premium || _license.pro) {
      // Open mode (everything free), PREMIUM, or PRO — quiet tier tag.
      // O selo PREMIUM aparece SÓ em licensed mode + chave premium (open mode
      // mostra PRO como antes — o operador self-host não vê tier pago).
      const premiumTag = _license.mode === 'licensed' && _license.premium;
      badge.hidden = false;
      badge.textContent = _license.mode === 'open' ? 'BETA' : (premiumTag ? 'PREMIUM' : (_license.pro ? 'PRO' : 'FREE'));
      badge.classList.toggle('is-pro', !!(_license.premium || _license.pro));
      badge.title = premiumTag
        ? 'PREMIUM license active — AI Operator real liberado'
        : (_license.mode === 'open' ? 'Beta/trial access active — checkout is not required' : (_license.pro ? 'PRO license active' : 'Free tier'));
      badge.onclick = null;  // clear any leftover upgrade-CTA handler (audit)
      syncUpgradeModal();
      syncAiPremiumUi();
      return;
    }
    // Licensed mode + free tier → gate is live; badge is the upgrade CTA.
    badge.hidden = false;
    badge.textContent = 'UPGRADE';
    badge.classList.toggle('is-pro', false);
    const stateTitles = {
      revoked: 'License revoked — open for details',
      expired: 'License expired — open for details',
      invalid: 'Stored license is invalid — open for details',
    };
    badge.title = stateTitles[_license.license_state] || 'PRO features locked — open access options';
    badge.onclick = openUpgradeModal;
    syncUpgradeModal();
    syncAiPremiumUi();
  }
  // AI Operator premium CTA (panel header) — shown only in licensed mode
  // WITHOUT a premium key; clicking opens the payload-driven upgrade modal.
  function syncAiPremiumUi() {
    const cta = document.getElementById('ai-premium-cta');
    if (!cta) return;
    const locked = _license.mode === 'licensed' && !_license.premium;
    cta.hidden = !locked;
    if (locked) {
      cta.innerHTML = _ic('robot', 12, true) + (_license.pro ? 'AI PREMIUM' : 'AI = PREMIUM');
      cta.onclick = openUpgradeModal;
    } else {
      cta.onclick = null;
    }
  }
  // R1 revenue: upgrade modal — buy via Lemon Squeezy checkout or redeem a key.
  // CFO: firing the funnel events is best-effort and silent — telemetry must
  // never delay or break the UI (no await on the happy path).
  function funnelId() {
    // Issue #155: anonymous browser session id for funnel attribution.
    // PII-free random token generated once and kept in localStorage — it lets
    // paywall/modal/checkout/paid form a per-user path server-side without
    // storing any personal data (never sent as email, only echoed into the
    // Lemon Squeezy checkout `custom` field and back via the webhook).
    try {
      let id = localStorage.getItem('c65_funnel_id');
      if (!id) {
        id = 'f_' + Math.random().toString(36).slice(2) + Date.now().toString(36);
        localStorage.setItem('c65_funnel_id', id);
      }
      return id;
    } catch (e) { return ''; }
  }
  function trackConversionEvent(event, meta) {
    try {
      const m = meta || {};
      if (!m.funnel_id) m.funnel_id = funnelId();
      fetch('/api/conversion/track', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ event: event, meta: m }),
      }).catch(function () { /* fire-and-forget */ });
    } catch (e) { /* never break the UI for telemetry */ }
  }
  function openUpgradeModal() {
    const m = document.getElementById('upgrade-modal');
    openModalAnimated(m);
    // Fresh invoice every open — never resume a stale pending payment.
    resetBtcUpgradePane();
    const status = document.getElementById('upgrade-status');
    if (status) { status.textContent = ''; status.className = 'modal__status'; }
    syncUpgradeModal();
    const up = _license.upgrade || {};
    trackConversionEvent('modal_open', { plan: (up.plan || 'PRO').toLowerCase() });
  }
  // Exposed for e2e + support console (the PRO badge already wires onclick).
  window.openUpgradeModal = openUpgradeModal;
  function closeUpgradeModal() {
    stopBtcTimers();
    closeModalAnimated(document.getElementById('upgrade-modal'));
  }
  // Show the Buy button only when the server has a payment provider configured,
  // and drive its price copy from the server payload (single source of truth).
  function syncUpgradeModal() {
    const buy = document.getElementById('upgrade-buy-btn');
    const pbuy = document.getElementById('upgrade-premium-buy-btn');
    const up = _license.upgrade || {};
    // Server-driven tier target: upgrade.plan === 'PREMIUM' means the user
    // is PRO (not premium) → the modal sells the PREMIUM upsell; else PRO.
    const wantsPremium = up.plan === 'PREMIUM';
    const cardPlans = _license.payment_plans || {};
    const cardLive = !!_license.payments;
    const targetCardLive = wantsPremium ? !!cardPlans.premium : !!cardPlans.pro;
    if (buy) {
      buy.hidden = !cardLive || !cardPlans.pro || wantsPremium;
      buy.textContent = 'Buy PRO — $' + ((up && up.price_usd_month) || 9) + '/mo';
    }
    if (pbuy) {
      pbuy.hidden = !cardLive || !cardPlans.premium || !wantsPremium;
      pbuy.textContent = 'Buy PREMIUM — $' + ((up && up.price_usd_month) || 29) + '/mo';
    }
    // Issue 249: payment tabs — Bitcoin is the DEFAULT when a BTC provider is
    // live (BTCPay or WebLN fallback); Card is the discreet fallback.
    const btcLive = btcProviderLive();
    const checkoutLive = btcLive || targetCardLive;
    const tabs = document.getElementById('upgrade-tabs');
    const tabBtc = document.getElementById('upgrade-tab-btc');
    const tabCard = document.getElementById('upgrade-tab-card');
    const loading = document.getElementById('upgrade-loading');
    const unavailable = document.getElementById('upgrade-unavailable');
    const statusLoading = _license.checkout_state === 'loading';
    const statusError = _license.checkout_state === 'error';
    if (loading) {
      loading.hidden = !(statusLoading || statusError);
      loading.classList.toggle('upgrade-availability--error', statusError);
      if (statusError) loading.textContent = 'Não foi possível verificar o checkout. Nenhuma compra foi habilitada.';
    }
    if (unavailable) unavailable.hidden = statusLoading || statusError || checkoutLive;
    if (tabs) tabs.hidden = !checkoutLive;
    if (tabBtc) tabBtc.hidden = !btcLive;
    if (tabCard) tabCard.hidden = !targetCardLive;
    // Default tab is only locked when the tabs are actually visible — a boot
    // in open mode (no provider) must never pin 'card' before the real
    // license-status arrives (Issue 249 default: Bitcoin).
    if (checkoutLive) {
      if (!_upgradeTabSet) setUpgradeTab(btcLive ? 'btc' : 'card');
      else if (_upgradeTab === 'btc' && !btcLive) setUpgradeTab('card');
      else if (_upgradeTab === 'card' && !targetCardLive) setUpgradeTab('btc');
    } else {
      const paneBtc = document.getElementById('upgrade-pane-btc');
      const paneCard = document.getElementById('upgrade-pane-card');
      if (paneBtc) paneBtc.hidden = true;
      if (paneCard) paneCard.hidden = true;
      _upgradeTabSet = false;
    }
    const title = document.getElementById('upgrade-modal-title');
    if (title) title.textContent = wantsPremium ? '🤖 CYPHER65 PREMIUM' : '⚡ CYPHER65 PRO';
    const copy = document.getElementById('upgrade-modal-copy');
    if (copy) {
      copy.innerHTML = wantsPremium
        ? 'Unlock the <strong>real AI Operator</strong> (LLM — fleet, pool, probability &amp; market answers) on top of every PRO feature.'
        : 'Unlock <strong>Monte Carlo scenarios</strong>, <strong>best-share ratio history</strong>, <strong>30d history</strong> &amp; <strong>webhooks</strong>. Models are not predictions.';
    }
    // BTC start pane: server-driven price (single source of truth) + tier.
    const btcPrice = document.getElementById('upgrade-btc-price');
    if (btcPrice) {
      const usd = (up && up.price_usd_month) || (wantsPremium ? 29 : 9);
      btcPrice.textContent = (wantsPremium ? 'PREMIUM' : 'PRO') + ' — $' + usd + '/mo via Bitcoin';
    }
    const btcStart = document.getElementById('upgrade-btc-start-btn');
    if (btcStart) {
      btcStart.dataset.plan = wantsPremium ? 'premium' : 'pro';
      btcStart.hidden = !btcLive;
    }
    const stateStatus = document.getElementById('upgrade-status');
    if (stateStatus && !stateStatus.textContent) {
      const stateMessages = {
        revoked: 'A licença salva foi revogada. Ative outra chave válida.',
        expired: 'A licença salva expirou. Ative outra chave válida.',
        invalid: 'A licença salva é inválida. Nenhum recurso pago foi liberado.',
      };
      if (stateMessages[_license.license_state]) {
        stateStatus.textContent = stateMessages[_license.license_state];
        stateStatus.className = 'modal__status modal__status--error';
      }
    }
  }
  async function buyUpgrade(plan) {
    const tier = plan === 'premium' ? 'premium' : 'pro';
    const btn = document.getElementById(tier === 'premium' ? 'upgrade-premium-buy-btn' : 'upgrade-buy-btn');
    const status = document.getElementById('upgrade-status');
    setBtnLoading(btn, true);
    if (status) { status.textContent = 'Preparando checkout seguro…'; status.className = 'modal__status'; }
    trackConversionEvent('checkout_start', { plan: tier });
    try {
      const r = await fetch('/api/upgrade/checkout', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ plan: tier, funnel_id: funnelId() }),
      });
      let data = {};
      try { data = await r.json(); } catch (e) {}
      if (r.ok && data.checkout_url) {
        window.open(data.checkout_url, '_blank', 'noopener');
        if (status) status.textContent = 'Checkout aberto. O pagamento está pendente até a confirmação do provedor.';
      } else {
        if (status) { status.textContent = (data && data.error) || 'Checkout indisponível'; status.className = 'modal__status modal__status--error'; }
        logMessage(tier.toUpperCase(), (data && data.error) || 'Checkout unavailable', 'WARN');
      }
    } catch (e) {
      if (status) { status.textContent = 'Checkout indisponível. Nenhuma cobrança foi iniciada.'; status.className = 'modal__status modal__status--error'; }
      logMessage(tier.toUpperCase(), 'Checkout unavailable', 'WARN');
    } finally {
      setBtnLoading(btn, false);
    }
  }
  // Legacy name kept for e2e / support console compatibility.
  async function buyPro() { return buyUpgrade('pro'); }
  // Wire the modal CTA buttons once (tabs / Buy PRO / Buy PREMIUM / BTC / key).
  let _upgradeBound = false;
  function _initUpgradeBindings() {
    if (_upgradeBound) return;
    _upgradeBound = true;
    const buy = document.getElementById('upgrade-buy-btn');
    const pbuy = document.getElementById('upgrade-premium-buy-btn');
    const redeem = document.getElementById('upgrade-redeem-btn');
    if (buy) buy.addEventListener('click', function () { buyUpgrade('pro'); });
    if (pbuy) pbuy.addEventListener('click', function () { buyUpgrade('premium'); });
    if (redeem) redeem.addEventListener('click', redeemLicenseKey);
    // Issue 249: Bitcoin tab wiring.
    const tabBtc = document.getElementById('upgrade-tab-btc');
    const tabCard = document.getElementById('upgrade-tab-card');
    const btcStart = document.getElementById('upgrade-btc-start-btn');
    const btcCopy = document.getElementById('upgrade-btc-copy');
    const btcOpen = document.getElementById('upgrade-btc-open');
    const btcWebln = document.getElementById('upgrade-btc-webln');
    const btcNew = document.getElementById('upgrade-btc-new');
    if (tabBtc) tabBtc.addEventListener('click', function () { setUpgradeTab('btc'); });
    if (tabCard) tabCard.addEventListener('click', function () { setUpgradeTab('card'); });
    if (btcStart) btcStart.addEventListener('click', startBtcUpgrade);
    if (btcCopy) btcCopy.addEventListener('click', copyBtcPayload);
    if (btcOpen) {
      btcOpen.addEventListener('click', function () {
        if (_btcUpgrade.checkoutUrl) window.open(_btcUpgrade.checkoutUrl, '_blank', 'noopener');
      });
    }
    if (btcWebln) btcWebln.addEventListener('click', payBtcWithWebLN);
    if (btcNew) btcNew.addEventListener('click', function () { resetBtcUpgradePane(); });
    // Late-injected WebLN extension (webln:ready) → reveal the pay CTA.
    document.addEventListener('webln:ready', function () {
      const wl = document.getElementById('upgrade-btc-webln');
      if (wl && _btcUpgrade.started && _btcUpgrade.provider === 'webln') wl.hidden = false;
    });
  }
  async function redeemLicenseKey() {
    const input = document.getElementById('upgrade-key-input');
    const btn = document.getElementById('upgrade-redeem-btn');
    const status = document.getElementById('upgrade-status');
    const key = (input && input.value || '').trim();
    if (!key) return;
    setBtnLoading(btn, true);
    if (status) { status.textContent = 'Validando licença no servidor…'; status.className = 'modal__status'; }
    try {
      const verified = await fetchLicenseStatus(key);
      if (!verified.key_valid) {
        const keyState = verified.submitted_license_state || verified.license_state;
        const messages = {
          revoked: 'Esta licença foi revogada.',
          expired: 'Esta licença expirou.',
          invalid: 'Licença inválida. Nenhuma alteração foi aplicada.',
        };
        if (status) { status.textContent = messages[keyState] || 'Licença não aceita.'; status.className = 'modal__status modal__status--error'; }
        logMessage('LICENSE', messages[keyState] || 'license key rejected', 'WARN');
        return;
      }
      try { localStorage.setItem(LICENSE_STORAGE_KEY, key); } catch (e) {}
      _license = verified;
      renderLicenseBadge();
      syncUpgradeModal();
      syncAiPremiumUi();
      renderCharts();
      trackConversionEvent('key_activated');
      if (status) { status.textContent = verified.license_state === 'trial_active' ? 'Trial ativado.' : 'Licença paga ativada.'; status.className = 'modal__status modal__status--success'; }
      logMessage('LICENSE', 'license key accepted — ' + verified.tier.toUpperCase() + ' unlocked', 'SUCCESS');
      if (input) input.value = '';
    } catch (e) {
      if (status) { status.textContent = 'Não foi possível validar a licença. Tente novamente.'; status.className = 'modal__status modal__status--error'; }
    } finally {
      setBtnLoading(btn, false);
    }
  }

  // ── BTC upgrade (Issue 249): Bitcoin tab — BTCPay invoice or WebLN BOLT-11 ──
  // The checkout payload is the single source of truth for amount/provider;
  // the BTC tab only ever renders what the backend returned (the BTCPay
  // hosted checkout renders its OWN per-invoice QR — the fixed
  // PAYMENT_BTC_ADDRESS never settles a BTCPay invoice, so we never show it
  // as a payment target here).
  const _btcUpgrade = {
    plan: 'pro', started: false, provider: '', // 'btcpay' | 'webln'
    invoiceId: '', statusToken: '', checkoutUrl: '', bolt11: '', paymentHash: '',
    amountSat: 0, expiresAt: 0,
    pollTimer: null, countdownTimer: null, statusTries: 0,
  };
  let _upgradeTab = 'btc';
  let _upgradeTabSet = false;

  function btcProviderLive() { return !!(_license.btcpay || _license.webln); }

  function weblnPresentSync() {
    return !!(window.webln && typeof window.webln.sendPayment === 'function');
  }

  function stopBtcTimers() {
    if (_btcUpgrade.pollTimer) { clearInterval(_btcUpgrade.pollTimer); _btcUpgrade.pollTimer = null; }
    if (_btcUpgrade.countdownTimer) { clearInterval(_btcUpgrade.countdownTimer); _btcUpgrade.countdownTimer = null; }
  }

  function setUpgradeTab(tab) {
    _upgradeTab = tab === 'card' ? 'card' : 'btc';
    _upgradeTabSet = true;
    const isBtc = _upgradeTab === 'btc';
    const tabBtc = document.getElementById('upgrade-tab-btc');
    const tabCard = document.getElementById('upgrade-tab-card');
    const paneBtc = document.getElementById('upgrade-pane-btc');
    const paneCard = document.getElementById('upgrade-pane-card');
    if (tabBtc) { tabBtc.classList.toggle('is-active', isBtc); tabBtc.setAttribute('aria-selected', isBtc ? 'true' : 'false'); }
    if (tabCard) { tabCard.classList.toggle('is-active', !isBtc); tabCard.setAttribute('aria-selected', isBtc ? 'false' : 'true'); }
    if (paneBtc) paneBtc.hidden = !isBtc;
    if (paneCard) paneCard.hidden = isBtc;
  }

  // Reset the BTC pane to the "start" step (fresh invoice). Keeps the
  // pending/paid step untouched unless explicitly requested.
  function resetBtcUpgradePane() {
    stopBtcTimers();
    _btcUpgrade.started = false;
    _btcUpgrade.invoiceId = ''; _btcUpgrade.statusToken = ''; _btcUpgrade.checkoutUrl = '';
    _btcUpgrade.bolt11 = ''; _btcUpgrade.paymentHash = '';
    _btcUpgrade.amountSat = 0; _btcUpgrade.expiresAt = 0; _btcUpgrade.statusTries = 0;
    const startEl = document.getElementById('upgrade-btc-start');
    const pendingEl = document.getElementById('upgrade-btc-pending');
    const paidEl = document.getElementById('upgrade-btc-paid');
    if (startEl) startEl.hidden = false;
    if (pendingEl) pendingEl.hidden = true;
    if (paidEl) paidEl.hidden = true;
    const qr = document.getElementById('upgrade-btc-qr'); if (qr) qr.innerHTML = '';
    const amt = document.getElementById('upgrade-btc-amount'); if (amt) amt.textContent = '—';
    const cd = document.getElementById('upgrade-btc-countdown'); if (cd) cd.textContent = '—';
    const st = document.getElementById('upgrade-btc-status'); if (st) { st.textContent = '—'; st.className = 'upgrade-btc__status'; }
    const wl = document.getElementById('upgrade-btc-webln'); if (wl) wl.hidden = true;
    const op = document.getElementById('upgrade-btc-open'); if (op) op.hidden = true;
    const keyEl = document.getElementById('upgrade-btc-paid-key'); if (keyEl) keyEl.textContent = '';
  }

  function showBtcStatus(msg, kind) {
    const el = document.getElementById('upgrade-btc-status');
    if (!el) return;
    el.textContent = msg || '';
    el.className = 'upgrade-btc__status' + (kind ? ' upgrade-btc__status--' + kind : '');
  }

  async function startBtcUpgrade() {
    const btn = document.getElementById('upgrade-btc-start-btn');
    const modalStatus = document.getElementById('upgrade-status');
    const plan = (btn && btn.dataset && btn.dataset.plan) || 'pro';
    setBtnLoading(btn, true);
    if (modalStatus) { modalStatus.textContent = 'Criando invoice segura…'; modalStatus.className = 'modal__status'; }
    trackConversionEvent('checkout_start', { plan: plan, method: 'btc' });
    try {
      const r = await fetch('/api/upgrade/checkout', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ plan: plan, method: 'btc', funnel_id: funnelId() }),
      });
      let data = {};
      try { data = await r.json(); } catch (e) {}
      if (!r.ok || !data.ok) {
        showBtcStatus((data && data.error) || 'Checkout unavailable', 'error');
        if (modalStatus) { modalStatus.textContent = (data && data.error) || 'Checkout indisponível. Nenhuma cobrança foi iniciada.'; modalStatus.className = 'modal__status modal__status--error'; }
        return;
      }
      _btcUpgrade.started = true;
      _btcUpgrade.plan = plan;
      _btcUpgrade.provider = data.provider || (data.method === 'lightning' ? 'webln' : 'btcpay');
      _btcUpgrade.amountSat = Number(data.amount_sat) || 0;
      if (_btcUpgrade.provider === 'webln') {
        _btcUpgrade.bolt11 = data.bolt11 || '';
        _btcUpgrade.paymentHash = data.payment_hash || '';
      } else {
        _btcUpgrade.invoiceId = data.invoice_id || '';
        _btcUpgrade.statusToken = data.status_token || '';
        _btcUpgrade.checkoutUrl = data.checkout_url || '';
        _btcUpgrade.expiresAt = Date.now() + (Number(data.expires_in_min) || 15) * 60000;
      }
      renderBtcPending();
      if (modalStatus) modalStatus.textContent = '';
    } catch (e) {
      showBtcStatus('Checkout unavailable', 'error');
      if (modalStatus) { modalStatus.textContent = 'Checkout indisponível. Nenhuma cobrança foi iniciada.'; modalStatus.className = 'modal__status modal__status--error'; }
    } finally {
      setBtnLoading(btn, false);
    }
  }

  function renderBtcPending() {
    const startEl = document.getElementById('upgrade-btc-start');
    const pendingEl = document.getElementById('upgrade-btc-pending');
    const paidEl = document.getElementById('upgrade-btc-paid');
    if (startEl) startEl.hidden = true;
    if (paidEl) paidEl.hidden = true;
    if (pendingEl) pendingEl.hidden = false;
    const isWebln = _btcUpgrade.provider === 'webln';
    // Amount: exact sats from the checkout payload + USD reference.
    const amt = document.getElementById('upgrade-btc-amount');
    if (amt) {
      const up = _license.upgrade || {};
      const usd = (up && up.price_usd_month) || (_btcUpgrade.plan === 'premium' ? 29 : 9);
      amt.textContent = fmtSats(_btcUpgrade.amountSat) + ' · ≈ $' + usd + '/mo';
    }
    // QR: BOLT-11 (WebLN fallback — real payment QR) or the hosted BTCPay
    // checkout URL (scan opens the page that renders the per-invoice BIP-21).
    const qrBox = document.getElementById('upgrade-btc-qr');
    if (qrBox) {
      try {
        const payload = isWebln ? _btcUpgrade.bolt11 : _btcUpgrade.checkoutUrl;
        if (payload) {
          const qr = qrEncode(payload, 'M');
          qrBox.innerHTML = qrSvg(qr.modules);
          qrBox.setAttribute('aria-label', isWebln ? 'QR code do invoice Lightning (BOLT-11)' : 'QR code do checkout Bitcoin');
          qrBox.title = payload;
        }
      } catch (e) {
        qrBox.innerHTML = '<div class="upgrade-btc__qr-error">QR unavailable</div>';
      }
    }
    const copy = document.getElementById('upgrade-btc-copy');
    if (copy) copy.textContent = isWebln ? '⧉ COPIAR INVOICE' : '⧉ COPIAR LINK';
    const open = document.getElementById('upgrade-btc-open');
    if (open) open.hidden = isWebln;
    const wl = document.getElementById('upgrade-btc-webln');
    // CTA only when a WebLN provider is actually present (Issue 249: no
    // webln → CTA disappears, never errors). Late-injected extensions re-show
    // it via the 'webln:ready' listener wired in _initUpgradeBindings.
    if (wl) wl.hidden = !isWebln || !weblnPresentSync();
    if (isWebln) {
      showBtcStatus('Abra o invoice na sua wallet ou pague com Lightning', 'info');
    } else {
      const cd = document.getElementById('upgrade-btc-countdown');
      if (cd) cd.textContent = countdownLabel(_btcUpgrade.expiresAt - Date.now());
      startBtcPoll();
      startBtcCountdown();
      pollBtcStatus();
    }
  }

  function startBtcPoll() {
    stopBtcPoll();
    _btcUpgrade.pollTimer = setInterval(pollBtcStatus, 5000);
  }
  function stopBtcPoll() {
    if (_btcUpgrade.pollTimer) { clearInterval(_btcUpgrade.pollTimer); _btcUpgrade.pollTimer = null; }
  }
  async function pollBtcStatus() {
    if (!_btcUpgrade.started || _btcUpgrade.provider !== 'btcpay' || !_btcUpgrade.invoiceId) return;
    if (Date.now() > _btcUpgrade.expiresAt) {
      showBtcStatus('Invoice expirada — gere uma nova.', 'error');
      stopBtcPoll(); stopBtcCountdown();
      return;
    }
    try {
      const statusUrl = '/api/upgrade/status/' + encodeURIComponent(_btcUpgrade.invoiceId);
      const r = await fetch(statusUrl, {
        headers: { 'X-Checkout-Token': _btcUpgrade.statusToken }
      });
      const d = await r.json().catch(function () { return {}; });
      if (!r.ok) {
        _btcUpgrade.statusTries++;
        if (_btcUpgrade.statusTries >= 6) {
          showBtcStatus('Não foi possível consultar o status — tente novamente.', 'error');
          stopBtcPoll();
        }
        return;
      }
      _btcUpgrade.statusTries = 0;
      const st = String(d.status || '').toLowerCase();
      const paymentState = String(d.payment_state || '').toLowerCase();
      if (paymentState === 'confirmed' || st === 'settled') {
        // Webhook may still be in flight — keep polling until the key lands.
        if (d.license_key) applyUpgradeKey(d.license_key);
        else showBtcStatus('Pagamento confirmado — ativando PRO...', 'pending');
        return;
      }
      if (paymentState === 'expired' || paymentState === 'invalid' || st === 'expired' || st === 'invalid') {
        showBtcStatus('Invoice expirada/inválida — gere uma nova.', 'error');
        stopBtcPoll(); stopBtcCountdown();
        return;
      }
      showBtcStatus(
        st === 'processing' ? 'Pagamento recebido — aguardando confirmação...' : 'Aguardando pagamento...',
        st === 'processing' ? 'pending' : 'info'
      );
    } catch (e) { /* keep polling silently */ }
  }

  function startBtcCountdown() {
    stopBtcCountdown();
    const el = document.getElementById('upgrade-btc-countdown');
    if (!el) return;
    const tick = function () {
      const left = _btcUpgrade.expiresAt - Date.now();
      el.textContent = countdownLabel(left);
      if (left <= 0) {
        stopBtcCountdown();
        showBtcStatus('Invoice expirada — gere uma nova.', 'error');
        stopBtcPoll();
      }
    };
    tick();
    _btcUpgrade.countdownTimer = setInterval(tick, 1000);
  }
  function stopBtcCountdown() {
    if (_btcUpgrade.countdownTimer) { clearInterval(_btcUpgrade.countdownTimer); _btcUpgrade.countdownTimer = null; }
  }

  function copyBtcPayload() {
    const payload = _btcUpgrade.provider === 'webln' ? _btcUpgrade.bolt11 : _btcUpgrade.checkoutUrl;
    if (!payload) return;
    const btn = document.getElementById('upgrade-btc-copy');
    const done = function () {
      if (!btn) return;
      const orig = btn.textContent;
      btn.textContent = '✓ copiado';
      setTimeout(function () { btn.textContent = orig; }, 1800);
    };
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(payload).then(done).catch(done);
    } else {
      // Legacy fallback: hidden textarea + execCommand.
      const ta = document.createElement('textarea');
      ta.value = payload;
      ta.style.position = 'fixed'; ta.style.opacity = '0';
      document.body.appendChild(ta);
      ta.select();
      try { document.execCommand('copy'); } catch (e) {}
      document.body.removeChild(ta);
      done();
    }
  }

  async function payBtcWithWebLN() {
    if (!_btcUpgrade.bolt11) return;
    showBtcStatus('Conectando wallet Lightning...', 'pending');
    try {
      const provider = await detectWebLN(5000);
      if (!provider) {
        showBtcStatus('Nenhuma wallet WebLN detectada. Instale Alby ou Joule.', 'error');
        return;
      }
      await provider.enable();
      showBtcStatus('Enviando pagamento...', 'pending');
      const result = await provider.sendPayment(_btcUpgrade.bolt11);
      const preimage = (result && result.preimage) ? String(result.preimage) : '';
      // Record on the donations ledger (existing pattern, dedup by preimage)
      // so the operator sees the payment in Recent Donations + Alerts.
      if (preimage) {
        try {
          authFetch('/api/donations', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ method: 'lightning', preimage: preimage, amount_sat: _btcUpgrade.amountSat, source: 'webln' }),
          }).catch(function () {});
        } catch (e) { /* non-fatal */ }
      }
      if (!preimage) {
        showBtcStatus('Pagamento enviado — aguardando confirmação.', 'info');
        return;
      }
      showBtcStatus('Pagamento confirmado — ativando PRO...', 'pending');
      // Server-side activation: sha256(preimage) == payment_hash proof.
      try {
        const r = await fetch('/api/upgrade/webln/confirm', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ payment_hash: _btcUpgrade.paymentHash, preimage: preimage }),
        });
        const d = await r.json().catch(function () { return {}; });
        if (r.ok && d.license_key) {
          applyUpgradeKey(d.license_key);
        } else {
          showBtcStatus('Pagamento registrado — se a key não ativar, use ACTIVATE KEY na aba Card.', 'info');
        }
      } catch (e) {
        showBtcStatus('Pagamento enviado — aguardando confirmação.', 'info');
      }
    } catch (e) {
      const denied = e && e.message && e.message.indexOf('denied') !== -1;
      showBtcStatus((denied ? 'Pagamento negado: ' : 'Pagamento falhou: ') + ((e && e.message) || 'erro'), 'error');
    }
  }

  async function applyUpgradeKey(key) {
    if (!key) return;
    let verified;
    try {
      verified = await fetchLicenseStatus(key);
    } catch (e) {
      showBtcStatus('Pagamento confirmado, mas a licença ainda não pôde ser validada.', 'error');
      return;
    }
    if (!verified.key_valid || verified.license_state !== 'paid_active') {
      showBtcStatus('Pagamento confirmado, mas a licença retornada é inválida.', 'error');
      return;
    }
    try { localStorage.setItem(LICENSE_STORAGE_KEY, key); } catch (e) {}
    _license = verified;
    stopBtcPoll(); stopBtcCountdown();
    const pendingEl = document.getElementById('upgrade-btc-pending');
    const paidEl = document.getElementById('upgrade-btc-paid');
    const keyEl = document.getElementById('upgrade-btc-paid-key');
    if (pendingEl) pendingEl.hidden = true;
    if (paidEl) paidEl.hidden = false;
    if (keyEl) keyEl.textContent = key;
    showBtcStatus('PRO ativado — key aplicada', 'success');
    trackConversionEvent('key_activated');
    renderLicenseBadge();
    syncUpgradeModal();
    syncAiPremiumUi();
    renderCharts();
    logMessage('PRO', 'BTC payment confirmed — PRO unlocked', 'SUCCESS');
  }

  // Shared handler for 402 (PRO required) responses: surface the upgrade CTA.
  async function handleLicenseRequired(res) {
    let data = {};
    try { data = await res.json(); } catch (e) {}
    renderLicenseBadge();
    logMessage('PRO', (data && data.error) || 'PRO feature locked — license key required', 'WARN');
  }
  function authIsExpired(expiresAt, now) {
    if (!expiresAt) return true;
    now = now || Math.floor(Date.now() / 1000);
    return now >= (Number(expiresAt) - 30); // 30s safety margin
  }
  function authSessionValid(session, now) {
    if (!session || !session.access_token) return false;
    return !authIsExpired(session.expires_at, now);
  }

  function authGetToken() {
    const s = authLoadSession();
    return (s && authSessionValid(s)) ? s.access_token : null;
  }

  // Fetch wrapper: attach Bearer header; on 401 try a refresh once, retry.
  // IMPORTANT: /api/axe-fleet/* routes use @require_tenant (not @require_auth),
  // so an invalid/expired token NEVER returns 401 — the server silently falls
  // back to tenant 'default'. We therefore refresh PROACTIVELY whenever the
  // stored token is near/past expiry (authIsExpired already applies a 30s
  // safety margin), so the isolated tenant is never dropped at the refresh
  // boundary. The 401-retry below is a belt-and-suspenders for routes that
  // DO hard-require auth.
  async function authFetch(url, opts) {
    opts = opts || {};
    const session = authLoadSession();
    if (session && session.refresh_token && authIsExpired(session.expires_at)) {
      await authRefresh();
    }
    const token = authGetToken();
    const headers = Object.assign({}, opts.headers || {}, authBuildHeaders(token));
    let res = await fetch(url, Object.assign({}, opts, { headers }));
    if (res.status === 401 && token) {
      const refreshed = await authRefresh();
      if (refreshed) {
        const headers2 = Object.assign({}, opts.headers || {}, authBuildHeaders(authGetToken()));
        res = await fetch(url, Object.assign({}, opts, { headers: headers2 }));
      }
    }
    return res;
  }

  async function authRefresh() {
    const s = authLoadSession();
    if (!s || !s.refresh_token) return false;
    try {
      const r = await fetch('/api/auth/refresh', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ refresh_token: s.refresh_token }),
      });
      if (!r.ok) return false;
      const data = await r.json();
      if (!data.access_token) return false;
      authSaveSession({
        access_token: data.access_token,
        refresh_token: s.refresh_token,
        expires_at: data.expires_at,
        tenant_id: data.tenant_id || s.tenant_id || 'default',
      });
      return true;
    } catch (e) { return false; }
  }

  async function authLogin(apiKey) {
    if (!apiKey) return { ok: false, error: 'API key is required' };
    try {
      const r = await fetch('/api/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ api_key: apiKey }),
      });
      const data = await r.json().catch(() => ({}));
      if (!r.ok) return { ok: false, error: data.error || ('login failed (' + r.status + ')') };
      authSaveSession({
        access_token: data.access_token,
        refresh_token: data.refresh_token,
        expires_at: data.expires_at,
        tenant_id: data.tenant_id || 'default',
      });
      authUpdateUi();
      return { ok: true, tenant_id: data.tenant_id || 'default' };
    } catch (e) {
      return { ok: false, error: e.message || 'network error' };
    }
  }

  async function authLogout() {
    const s = authLoadSession();
    if (s && s.access_token) {
      try {
        await fetch('/api/auth/logout', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ access_token: s.access_token }),
        });
      } catch (e) {}
    }
    authClearSession();
    authUpdateUi();
  }

  function authUpdateUi() {
    const s = authLoadSession();
    const connected = authSessionValid(s);
    const tenant = connected ? (s.tenant_id || 'default') : 'default';
    const toggle = dom.authToggle;
    if (toggle) {
      toggle.innerHTML = _ic('key', 12, true) + escapeHtml(connected ? tenant.toUpperCase() : 'LOGIN');
      toggle.classList.toggle('is-authed', connected);
      toggle.title = connected ? 'Tenant: ' + tenant + ' — click to manage' : 'Tenant Login';
    }
    const badge = dom.axeFleetTenantBadge;
    if (badge) {
      badge.textContent = 'TENANT: ' + tenant;
      badge.classList.toggle('badge--green', connected);
      badge.classList.toggle('badge--mute', !connected);
    }
    const cur = dom.authCurrentTenant;
    if (cur) cur.textContent = connected ? tenant : '—';
    if (dom.authLogoutBtn) dom.authLogoutBtn.style.display = connected ? '' : 'none';
    if (dom.authStatus && !connected) dom.authStatus.textContent = '';
  }

  function initAuth() {
    authUpdateUi();
    const toggle = dom.authToggle;
    const modal = dom.authModal;
    if (toggle && modal) {
      toggle.addEventListener('click', function() {
        authUpdateUi();
        openModalAnimated(modal);
      });
    }
    const loginBtn = dom.authLoginBtn;
    if (loginBtn) {
      loginBtn.addEventListener('click', async function() {
        const keyInput = dom.authApiKey;
        const statusEl = dom.authStatus;
        const key = keyInput ? keyInput.value.trim() : '';
        if (!key) { if (statusEl) statusEl.textContent = '⚠ API key required'; return; }
        if (statusEl) { statusEl.textContent = 'connecting…'; statusEl.className = 'modal__status'; }
        const res = await authLogin(key);
        if (statusEl) {
          statusEl.textContent = res.ok ? '✓ connected as ' + res.tenant_id : '✗ ' + res.error;
          statusEl.className = res.ok ? 'modal__status modal__status--ok' : 'modal__status modal__status--err';
        }
        if (res.ok) {
          setTimeout(function() {
            closeModalAnimated(modal);
            fetchAxeFleet();
          }, 400);
        }
      });
    }
    if (dom.authLogoutBtn) {
      dom.authLogoutBtn.addEventListener('click', async function() {
        await authLogout();
        closeModalAnimated(modal);
        fetchAxeFleet();
      });
    }
    if (dom.authApiKey && loginBtn) {
      dom.authApiKey.addEventListener('keydown', function(e) {
        if (e.key === 'Enter') loginBtn.click();
      });
    }
  }

  // ── Instance indicator (Issue #198) ─────────────────────────────────
  // Deixa EXPLÍCITO em qual instância/URL o dashboard está. Resolve a
  // confusão real de salvar chaves MRR/Braiins na instância errada (local
  // vs cloud): o pill no topbar mostra o host + color-code por tipo, e o
  // tooltip/clique expõe o origin completo para conferir antes de salvar.
  // Pure classifier — espelhado em tests/test_app_js_core.js.
  function instanceClassify(host) {
    let h = String(host || '').toLowerCase().replace(/^https?:\/\//, '').split('/')[0];
    // Forma IPv6 com brackets "[::1]:8765" → "::1" (porta separada).
    const bracket = h.match(/^\[([^\]]+)\](?::\d+)?$/);
    if (bracket) h = bracket[1];
    // Strip de porta numérica — NUNCA para o loopback IPv6 cru "::1"
    // (o regex :\d+$ casaria o "1" final e destruiria o host).
    const hostOnly = h === '::1' ? '::1' : h.replace(/:\d+$/, '');
    if (!hostOnly) return { kind: 'remote', icon: '⌁' };
    const isLocal =
      hostOnly === 'localhost' || hostOnly === '127.0.0.1' || hostOnly === '0.0.0.0' || hostOnly === '::1' ||
      hostOnly.endsWith('.local') ||
      /^192\.168\./.test(hostOnly) || /^10\./.test(hostOnly) || /^172\.(1[6-9]|2\d|3[01])\./.test(hostOnly);
    const isCloud = /\.onrender\.com$/.test(hostOnly) || /\.render\.com$/.test(hostOnly);
    if (isLocal) return { kind: 'local', icon: '🖥' };
    if (isCloud) return { kind: 'cloud', icon: '☁' };
    return { kind: 'remote', icon: '⌁' };
  }
  function initInstanceIndicator() {
    const el = dom.topbarInstance;
    if (!el) return;
    const origin = window.location.origin || '';
    const host = window.location.host || 'self-hosted';
    const cls = instanceClassify(host);
    const labels = { local: 'LOCAL', cloud: 'CLOUD', remote: 'REMOTE' };
    let display = host;
    if (display.length > 30) display = display.slice(0, 28) + '…';
    el.textContent = cls.icon + ' ' + display;
    el.classList.add('topbar__instance--' + cls.kind);
    el.title = labels[cls.kind] + ' instance · ' + origin +
      '\n(settings/chaves salvam nesta origem — clique para copiar o URL)';
    // A11y: interativo por teclado também (Enter/Space = copiar), como um
    // button de verdade — não só mouse.
    el.setAttribute('role', 'button');
    el.tabIndex = 0;
    const copyOrigin = function () {
      try {
        if (navigator.clipboard && navigator.clipboard.writeText) {
          navigator.clipboard.writeText(origin).then(function () {
            showToast('success', 'Instance URL copiado: ' + origin);
          }).catch(function () { /* clipboard denied */ });
        } else {
          showToast('success', origin);
        }
      } catch (e) { /* never break the topbar for a copy */ }
    };
    el.onclick = copyOrigin;
    el.addEventListener('keydown', function (e) {
      if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); copyOrigin(); }
    });
  }
