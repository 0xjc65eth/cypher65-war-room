  // ══════════════════════════════════════════════════════════════════════
  // AXE Fleet — domínio extraído de `40-app-logic.js`
  // ══════════════════════════════════════════════════════════════════════
  // RFC 478 (Issue 523). Movimento MECÂNICO: nenhum nome, id de DOM, contrato
  // de fetch, formato de payload ou ordem de execução mudou — as 1.304 linhas
  // abaixo foram recortadas verbatim. Fecha o domínio Fleet/AXE (o 4a levou o
  // Fleet Command Center para `48-fleet-cc.js`).
  //
  // DIFERENTE DO MARKET, RENTALS E DO PR 4a — mas igual ao Admin: a região tem
  // UM statement de execução no topo, o listener de `#remote-test-btn` (click
  // → `fetchTailscale()`). Verificado: nenhum listener do IIFE depende de ordem
  // e `static/app.js` é carregado com `defer` (o DOM já está parseado), então
  // registrar mais tarde dentro do MESMO IIFE síncrono não muda o resultado.
  //
  // TDZ: a região declara 7 variáveis (`_scanning`, `_lmFlow`,
  // `_lmLastCounters`, `_LM_FLOW_MAX`, `_LM_FLOW_LABELS`, `_axeDetailChart`,
  // `_axeWizState`) e NENHUMA delas é referenciada fora da região. O único
  // caminho que entra aqui ANTES da avaliação do fragmento é o prefixo síncrono
  // do `boot()`, que chama `initAxeFleetControls()` → `initAxeScanControls()` /
  // `initAxeAgentPanel()`: varridos os três corpos, nenhuma dessas variáveis é
  // tocada em nível síncrono — todas vivem dentro de handlers.
  //
  // Acoplamento externo (6 nomes, todos no mesmo IIFE — function declarations
  // são hoisted, então a ordem de concatenação não importa):
  //   · `fetchAxeFleet()`             — `initAuth`, `fetchSnapshot`, o SSE do `boot`
  //                                     e `_doActivateModule`
  //   · `fetchRemoteOnboarding()`     — `boot` e `_doActivateModule`
  //   · `fetchTailscale()`           — `boot`
  //   · `initAxeFleetControls()`     — `boot`
  //   · `openAxeDetail()`            — `renderAlerts`
  //   · `initFleetCommandCenterControls()` — `boot`
  //
  // WART CONHECIDO: `initFleetCommandCenterControls` (13 linhas) é controle do
  // painel Fleet Command Center, mas é vizinho de `fetchFleetCommandCenter` e
  // veio junto para o recorte seguir verbatim e contíguo. A posse está
  // documentada na Issue 523 como candidata a realocação mecânica posterior.

  // AXE FLEET — render device cards from snapshot.axe_fleet
  // ══════════════════════════════════════════════════════════════════════

  // ── REMOTE ACCESS · TAILSCALE — fetch local tailscale status ──
  function renderTailscale(d) {
    const set = (id, v) => { const el = document.getElementById(id); if (el) el.textContent = v; };
    const setDot = (id, ok) => { const el = document.getElementById(id); if (el) el.style.background = ok ? 'var(--accent-green)' : 'var(--accent-red)'; };
    if (!d || !d.tailscale_installed) {
      set('remote-status-badge', 'NOT INSTALLED');
      set('remote-status-text', 'Tailscale CLI não encontrado no host — instale para acesso remoto');
      set('remote-host-ip', '—'); set('remote-hostname', '—'); set('remote-tailnet', '—');
      set('remote-online-since', '—'); set('remote-last-check', '—');
      set('health-val-host', 'local'); set('health-val-tailscale', 'absent'); set('health-val-miners', '—'); set('health-val-tuya', '—');
      setDot('health-dot-host', true); setDot('health-dot-tailscale', false);
      return;
    }
    const ok = !!d.connected;
    set('remote-status-badge', ok ? 'CONNECTED' : 'DISCONNECTED');
    set('remote-status-text', ok ? 'Tailscale conectado — acesso remoto disponível' : (d.error || 'Tailscale não conectado'));
    set('remote-host-ip', d.ip || '—');
    set('remote-hostname', d.hostname || '—');
    set('remote-tailnet', d.magic_dns_name ? d.magic_dns_name.split('.').slice(1).join('.') : '—');
    set('remote-online-since', d.online ? 'online' : (d.last_seen || '—'));
    set('remote-last-check', d.checked_at ? fmt.age(d.checked_at) : '—');
    set('health-val-host', 'local'); set('health-val-tailscale', ok ? 'connected' : 'offline');
    set('health-val-miners', '—'); set('health-val-tuya', '—');
    setDot('health-dot-host', true); setDot('health-dot-tailscale', ok);
  }
  async function fetchTailscale() {
    try {
      const r = await authFetch('/api/tailscale');
      if (!r.ok) throw new Error('http ' + r.status);
      const d = await r.json();
      renderTailscale(d);
    } catch (e) {
      const b = document.getElementById('remote-status-badge');
      if (b) b.textContent = 'ERROR';
      const t = document.getElementById('remote-status-text');
      if (t) t.textContent = 'falha ao consultar tailscale: ' + (e.message || 'unknown');
    }
  }
  document.getElementById('remote-test-btn')?.addEventListener('click', () => fetchTailscale());

  // ── REMOTE ACCESS · TAILSCALE — onboarding scope + limitations (G3) ──
  // The backend /api/axe-fleet/remote/onboarding returns the step checklist
  // PLUS an honest scope (what the user can do remotely) and limitations
  // (Tailscale constraints). Rendered here so the tutorial sets expectations
  // before the user wires everything up.
  function renderRemoteOnboarding(d) {
    if (!d) return;
    const set = (id, v) => { const el = document.getElementById(id); if (el) el.textContent = v; };
    // Checklist: rebuild from the payload — the backend is the source of
    // truth (label + instructions + done per step). Mapping onto the static
    // li items was semantically wrong (dashboard_reachable → 'verificar
    // miners', li[5] never updated, install+login collapsed into one item).
    const listEl = document.getElementById('checklist-list');
    if (listEl && Array.isArray(d.steps)) {
      listEl.innerHTML = d.steps.map(s =>
        '<li class="remote-checklist__item ' + (s.done ? 'completed' : 'pending') + '" data-step="' + escapeHtml(String(s.id)) + '">' +
          '<span class="rci-icon">' + (s.done ? '●' : '○') + '</span>' +
          '<span class="rci-text">' + escapeHtml(s.label || s.id) + '</span>' +
          '<span class="rci-status">' + (s.done ? 'ok' : 'pendente') + '</span>' +
        '</li>'
      ).join('');
    }
    // Scope + limitations lists (fill the empty containers).
    const scopeEl = document.getElementById('remote-scope-list');
    if (scopeEl && Array.isArray(d.scope)) {
      scopeEl.innerHTML = d.scope.map(s => '<li>' + escapeHtml(s) + '</li>').join('') || '<li>—</li>';
    }
    const limEl = document.getElementById('remote-limits-list');
    if (limEl && Array.isArray(d.limitations)) {
      limEl.innerHTML = d.limitations.map(s => '<li>' + escapeHtml(s) + '</li>').join('') || '<li>—</li>';
    }
    set('remote-checklist-progress', d.progress || '—/—');
  }
  async function fetchRemoteOnboarding() {
    try {
      const r = await authFetch('/api/axe-fleet/remote/onboarding');
      if (!r.ok) return;
      renderRemoteOnboarding(await r.json());
    } catch (e) { /* best-effort: the static checklist stays pending */ }
  }

  async function fetchAxeFleet() {
    try {
      const r = await authFetch('/api/axe-fleet/health');
      if (!r.ok) throw new Error('fleet health failed (' + r.status + ')');
      const data = await r.json();
      _operationalFleetData = data;
      _operationalFleetError = false;
      renderAxeFleet(data);
      renderOperationalOverview(_lastSnapshot || {}, data, false);
    } catch (e) {
      _operationalFleetError = true;
      if (dom.axeFleetStatusBadge) dom.axeFleetStatusBadge.textContent = 'ERROR';
      renderOperationalOverview(_lastSnapshot || {}, _operationalFleetData, true);
    }
    // FLEET COMMAND CENTER rides the same poll/SSE cadence.
    fetchFleetCommandCenter();
  }

  // ── LAN SCANNER (Phase B) — auto-discover miners on the local network ─
  let _scanning = false;
  async function scanNetwork() {
    if (_scanning) return;
    _scanning = true;
    const btn = dom.axeFleetScan;
    if (btn) { btn.textContent = '⏳ SCANNING…'; btn.disabled = true; }
    try {
      const r = await authFetch('/api/network/scan', { method: 'POST' });
      const data = await r.json();
      if (!data.success) throw new Error(data.error || 'scan failed');
      const found = data.found || 0;
      const dur = data.duration_ms || 0;
      const devs = data.devices || [];
      if (found === 0) {
        showToast('info', 'Scan complete — no mining devices found on LAN (' + (data.scanned || 0) + ' IPs probed in ' + dur + 'ms)');
      } else {
        showToast('success', found + ' device(s) found (' + dur + 'ms) — check Fleet to add them');
        // Render results as a simple list below the fleet grid
        renderScanResults(devs);
      }
    } catch (e) {
      logMessage('SCAN', 'Network scan failed: ' + e.message, 'WARN');
    } finally {
      _scanning = false;
      if (btn) {
        btn.innerHTML = _ic('search', 12, true) + 'SCAN NETWORK';
        btn.disabled = false;
      }
    }
  }

  function renderScanResults(devices) {
    let container = document.getElementById('scan-results');
    if (!container) {
      container = document.createElement('div');
      container.id = 'scan-results';
      container.className = 'scan-results';
      const grid = dom.axeGrid;
      if (grid && grid.parentNode) {
        grid.parentNode.insertBefore(container, grid.nextSibling);
      }
    }
    const items = devices.map(function(d) {
      var ports = (d.open_ports || []).join(', ');
      var hint = d.firmware_hint ? ' <span class="scan-results__hint">' + escapeHtml(d.firmware_hint) + '</span>' : '';
      var host = d.hostname ? ' <span class="scan-results__host">' + escapeHtml(d.hostname) + '</span>' : '';
      return '<div class="scan-results__item" data-ip="' + escapeHtml(d.ip) + '">' +
        '<span class="scan-results__ip">' + escapeHtml(d.ip) + '</span>' +
        '<span class="scan-results__ports">ports: ' + (ports || 'none') + '</span>' +
        hint + host +
        '<button class="chip scan-results__add" data-ip="' + escapeHtml(d.ip) + '">+ Add</button>' +
        '</div>';
    }).join('');
    container.innerHTML = '<div class="scan-results__head">' + _ic('search', 10, true) + 'SCAN RESULTS <button class="chip scan-results__dismiss">' + _ic('x', 10, true) + 'dismiss</button></div>' + items;
    container.style.display = 'block';
    // Wire dismiss + per-device Add buttons
    container.querySelector('.scan-results__dismiss')?.addEventListener('click', function() {
      container.style.display = 'none';
    });
    container.querySelectorAll('.scan-results__add').forEach(function(btn) {
      btn.addEventListener('click', function() {
        var ip = btn.getAttribute('data-ip') || '';
        if (ip) openAxeAddForm(ip);
      });
    });
  }

  // ── Helper: open the AXE add form pre-filled with an IP ───────────────
  function openAxeAddForm(ip) {
    var form = dom.axeAddForm || document.getElementById('axe-add-form');
    var ipInput = document.getElementById('axe-add-ip');
    if (form && ipInput) {
      ipInput.value = ip || '';
      form.style.display = 'block';
      // Trigger the same onboarding wizard reset the add button uses
      if (typeof resetAxeWizard === 'function') resetAxeWizard();
    }
  }

  // ── FLEET COMMAND CENTER · WORKER INTELLIGENCE ────────────────────────
  // Per-worker live telemetry fed by the AXE FLEET /summary endpoint
  // (shares, reject ratio, temps, power, efficiency, latency, health).
  // Honest '—' whenever a firmware doesn't expose a field. Exception
  // hierarchy: WARNING/IDLE/PAUSED first, then OFFLINE/ERROR/CRITICAL,
  // healthy ONLINE workers last. Pure builder mirrored in tests.
  function buildCommandCenterRows(devices) {
    const rows = [];
    (devices || []).forEach(function (d) {
      const tel = d._telemetry || {};
      const health = d._health || {};
      const accepted = Number(tel.shares_accepted) || 0;
      const rejected = Number(tel.shares_rejected) || 0;
      const stale = Number(tel.shares_stale) || 0;
      const total = accepted + rejected;
      let rejectPct = null;
      if (total > 0) {
        rejectPct = Number(tel.hw_error_pct != null ? tel.hw_error_pct : (rejected / total) * 100);
      }
      // Last-share age in seconds (best-effort — firmware may not expose it).
      let lastShareAgo = null;
      const lst = tel.last_share_ts;
      if (lst != null && lst !== '') {
        let t = Number(lst);
        if (!isFinite(t) || t > 1e12) t = Date.parse(String(lst)) / 1000;
        if (isFinite(t) && t > 0) lastShareAgo = Math.max(0, Math.floor(Date.now() / 1000 - t));
      }
      rows.push({
        id: d.id || '',
        name: d.name || d.ip_address || '?',
        ip: d.ip_address || '',
        model: d.model || '',
        manufacturer: d.manufacturer || '',
        status: d.status || 'OFFLINE',
        agentManaged: !!d.agent_managed,
        hr: Number(tel.hashrate_hs) || 0,
        hrStr: tel.hashrate_str || fmt.hashrate(tel.hashrate_hs),
        temp: _numOrNull(tel.temperature),
        chipTemp: _numOrNull(tel.chip_temp),
        vrTemp: _numOrNull(tel.vr_temp),
        fan: tel.fan_rpm != null ? tel.fan_rpm : tel.fan_speed,
        power: _numOrNull(tel.power_watts),
        eff: _numOrNull(tel.efficiency_jth),
        sharesA: accepted, sharesR: rejected, sharesS: stale,
        rejectPct: rejectPct,
        bestDiff: tel.best_diff,
        poolDiff: tel.pool_diff,
        lastShareAgo: lastShareAgo,
        latencyMs: d.latency_ms,
        stratum: tel.stratum_status || '',
        healthScore: health.score != null ? health.score : null,
        advice: Array.isArray(d.advice) ? d.advice : [],
        caps: Array.isArray(d.capabilities) ? d.capabilities : [],
      });
    });
    // Exception hierarchy (research: manage by exception) — problems first.
    const order = { WARNING: 0, IDLE: 0, PAUSED: 0, OFFLINE: 1, ERROR: 1, CRITICAL: 1, ONLINE: 2, HASHING: 2 };
    rows.sort(function (a, b) {
      const oa = order[a.status] != null ? order[a.status] : 3;
      const ob = order[b.status] != null ? order[b.status] : 3;
      if (oa !== ob) return oa - ob;
      return String(a.name).localeCompare(String(b.name));
    });
    return rows;
  }
  // Hash Flow Raster — rolling per-worker status samples (client-side ring
  // buffer, one column per poll tick, max 24) so the feed shows worker
  // health over time without requiring a new backend series.
  const _lmFlow = {};
  const _lmLastCounters = {}; // per-device previous cumulative share counters
  const _LM_FLOW_MAX = 24;
  // Raster cell color reflects SHARE QUALITY for the tick, not just device
  // status: we diff the firmware's cumulative counters (shares_accepted /
  // rejected / stale) between consecutive polls. A reject/stale is far more
  // actionable than a plain "online" cell — it signals pool/hardware trouble.
  const _LM_FLOW_LABELS = { ok: 'share', rej: 'reject', stale: 'stale', idle: 'online', warn: 'warn', bad: 'offline', mute: '' };
  // Pure: map (device status, per-tick share delta) → raster cell color code.
  function _lmFlowSampleFromDelta(status, delta) {
    if (delta) {
      if (delta.r > 0) return 'rej';    // reject beats everything
      if (delta.s > 0) return 'stale';  // stale beats accepted
      if (delta.a > 0) return 'ok';     // accepted share
    }
    const s = String(status || '').toUpperCase();
    if (s === 'ONLINE' || s === 'HASHING') return 'idle';
    if (s === 'WARNING' || s === 'IDLE' || s === 'PAUSED') return 'warn';
    if (s === 'OFFLINE' || s === 'ERROR' || s === 'CRITICAL') return 'bad';
    return 'mute';
  }
  // Pure: diff cumulative share counters, clamping negatives (a firmware
  // reboot resets them — a drop is a reset, not negative shares).
  function _lmShareDelta(prev, cur) {
    if (!prev) return null;
    return {
      a: Math.max(0, (cur.a || 0) - (prev.a || 0)),
      r: Math.max(0, (cur.r || 0) - (prev.r || 0)),
      s: Math.max(0, (cur.s || 0) - (prev.s || 0)),
    };
  }
  // Pure: human tooltip for a tick's delta ("+3 acc · +1 rej").
  function _lmFlowDetail(delta) {
    if (!delta) return '';
    const parts = [];
    if (delta.a > 0) parts.push('+' + delta.a + ' acc');
    if (delta.r > 0) parts.push('+' + delta.r + ' rej');
    if (delta.s > 0) parts.push('+' + delta.s + ' stale');
    return parts.join(' · ');
  }
  function _pushLmFlowSample(id, sample) {
    if (!_lmFlow[id]) _lmFlow[id] = [];
    const buf = _lmFlow[id];
    buf.push(sample);
    if (buf.length > _LM_FLOW_MAX) buf.shift();
  }

  // FLEET COMMAND CENTER — fetch /summary and render. Non-fatal: on
  // failure the panel simply keeps the last good data.
  async function fetchFleetCommandCenter() {
    try {
      const r = await authFetch('/api/axe-fleet/summary');
      if (!r.ok) return;
      const data = await r.json();
      _ccLastFleet = (data && data.devices) || [];
      _ccRenderFleet();
    } catch (e) { /* non-fatal */ }
  }

  // View toggle (grid cards / dense table) — persisted per browser.
  function initFleetCommandCenterControls() {
    try { _ccView = localStorage.getItem('_cc_view') || 'grid'; } catch (e) {}
    const chips = document.querySelectorAll('.chip--view');
    chips.forEach(chip => {
      chip.classList.toggle('is-active', chip.getAttribute('data-cc-view') === _ccView);
      chip.addEventListener('click', () => {
        _ccView = chip.getAttribute('data-cc-view') || 'grid';
        chips.forEach(c => c.classList.toggle('is-active', c.getAttribute('data-cc-view') === _ccView));
        try { localStorage.setItem('_cc_view', _ccView); } catch (e) {}
        _ccRenderFleet();
      });
    });
  }
  function renderAxeFleet(data) {
    if (!dom.axeGrid) return;
    if (!data || !data.fleet_stats) {
      dom.axeGrid.innerHTML = '<div class="mkt-empty" style="padding:20px;text-align:center">no AxeOS devices connected — register your hardware to enable fleet monitoring' +
        '<div class="axe-empty__hint" style="margin-top:8px">⚠ O host precisa estar na mesma rede local dos miners (ou usar Tailscale para alcançá-los remotamente).</div></div>';
      if (dom.axeFleetStatusBadge) dom.axeFleetStatusBadge.textContent = '0 devices';
      if (dom.axeFleetCountBadge) dom.axeFleetCountBadge.textContent = '0';
      return;
    }

    const fleet = data.fleet_stats || {};
    const devices = data.device_health || [];

    // Summary stats
    if (dom.axeSummaryHr) dom.axeSummaryHr.textContent = fleet.total_hashrate_str || '—';
    if (dom.axeSummaryOnline) countUpValue(dom.axeSummaryOnline, String(fleet.online || 0));
    if (dom.axeSummaryWarning) countUpValue(dom.axeSummaryWarning, String(fleet.warning || 0));
    if (dom.axeSummaryOffline) countUpValue(dom.axeSummaryOffline, String(fleet.offline || 0));
    if (dom.axeSummaryHealth) dom.axeSummaryHealth.textContent = fleet.avg_health_score != null ? Math.round(fleet.avg_health_score) + '/100' : '—';
    if (dom.axeSummaryTemp) dom.axeSummaryTemp.textContent = fleet.avg_temperature_c != null ? fleet.avg_temperature_c.toFixed(1) + '°C' : '—';
    if (dom.axeSummaryPower) dom.axeSummaryPower.textContent = fleet.total_power_w ? fleet.total_power_w.toFixed(0) + 'W' : '—';
    if (dom.axeSummaryEff) dom.axeSummaryEff.textContent = fleet.efficiency_jth != null ? fleet.efficiency_jth.toFixed(1) + ' J/TH' : '—';
    if (dom.axeSummaryBest) dom.axeSummaryBest.textContent = fleet.best_diff ? fmt.diff(fleet.best_diff) : '—';

    // Count badge
    const total = fleet.total_devices || 0;
    if (dom.axeFleetCountBadge) dom.axeFleetCountBadge.textContent = total + ' device' + (total === 1 ? '' : 's');

    // Status badge
    if (dom.axeFleetStatusBadge) {
      if (total === 0) dom.axeFleetStatusBadge.textContent = 'NO DEVICES';
      else if (fleet.offline === total) dom.axeFleetStatusBadge.textContent = 'ALL OFFLINE';
      else if (fleet.warning > 0) dom.axeFleetStatusBadge.textContent = fleet.warning + ' WARNING';
      else if (fleet.online === total) dom.axeFleetStatusBadge.textContent = 'ALL ONLINE';
      else dom.axeFleetStatusBadge.textContent = fleet.online + '/' + total + ' ONLINE';
      dom.axeFleetStatusBadge.className = 'badge';
      if (fleet.offline === total) dom.axeFleetStatusBadge.classList.add('badge--red');
      else if (fleet.warning > 0) dom.axeFleetStatusBadge.classList.add('badge--amber');
      else dom.axeFleetStatusBadge.classList.add('badge--green');
    }

    // Group devices by status
    const onlineDevs = devices.filter(d => d.status === 'ONLINE' || d.status === 'HASHING');
    const warningDevs = devices.filter(d => d.status === 'WARNING');
    const offlineDevs = devices.filter(d => d.status !== 'ONLINE' && d.status !== 'HASHING' && d.status !== 'WARNING');

    if (!devices.length) {
      dom.axeGrid.innerHTML = '<div class="axe-empty">no devices registered — add your first Bitaxe/NerdAxe via the + ADD button' +
        '<div class="axe-empty__hint">⚠ Dashboard na nuvem não alcança a sua LAN (192.168.x.x não é roteável a partir do Render). Rode o <strong>AGENTE LOCAL</strong> na sua rede — Fleet → 🤖 CONNECT AGENT — ele descobre os miners e conecta para fora. (Self-host: rode o app na mesma Wi-Fi dos miners ou use um IP Tailscale.)</div></div>';
      return;
    }

    // Compute max hashrate for proportional bars
    const maxHr = Math.max(...devices.map(d => (d.telemetry && d.telemetry.hashrate_hs) || 0), 1);

    let html = '';

    // Online group
    if (onlineDevs.length) {
      html += '<div class="axe-group-header"><strong>' + onlineDevs.length + '</strong> ONLINE</div>';
      html += onlineDevs.map(d => _renderAxeCard(d, maxHr)).join('');
    }

    // Warning group
    if (warningDevs.length) {
      html += '<div class="axe-group-header"><strong>' + warningDevs.length + '</strong> WARNING</div>';
      html += warningDevs.map(d => _renderAxeCard(d, maxHr)).join('');
    }

    // Offline group
    if (offlineDevs.length) {
      html += '<div class="axe-group-header"><strong>' + offlineDevs.length + '</strong> OFFLINE</div>';
      html += offlineDevs.map(d => _renderAxeCard(d, maxHr)).join('');
    }

    dom.axeGrid.innerHTML = html;

    // Attach click handlers for detail panel
    dom.axeGrid.querySelectorAll('.axe-card').forEach(card => {
      card.addEventListener('click', (e) => {
        // Ignore clicks on command buttons (they have their own handler)
        if (e.target.closest('.axe-cmd-btn')) return;
        const id = card.dataset.deviceId;
        if (id) openAxeDetail(id);
      });
    });

    // Attach command button handlers (shared with the FLEET COMMAND CENTER
    // cards — one implementation via _handleAxeCmdClick).
    dom.axeGrid.querySelectorAll('.axe-cmd-btn').forEach(btn => {
      btn.addEventListener('click', (e) => { e.stopPropagation(); _handleAxeCmdClick(btn); });
    });
  }

  // ── Shared axe-fleet command router ──────────────────────────────────
  // restart/identify → agent queue via authFetch (Bearer); pause/resume →
  // core route. Used by both the AXE FLEET grid and the FLEET COMMAND
  // CENTER worker cards. The routing decision is mirrored in tests.
  async function _handleAxeCmdClick(btn) {
    const deviceId = btn.dataset.deviceId;
    const command = btn.dataset.cmd;
    if (!deviceId || !command) return;

    // Explicit human confirmation for every physical state change.
    if (command === 'restart') {
      if (!confirm('Restart this miner? It will go offline for ~30 seconds.')) return;
    } else if (command === 'pause') {
      if (!confirm('Pause mining on this device? Use Resume to restart.')) return;
    } else if (!confirm('Execute ' + command + ' on this miner?')) {
      return;
    }

    // Captura o label original (ex.: '↻' no botão mini da tabela) para
    // restaurar exatamente o que havia — sem hardcodar o texto do botão.
    const originalLabel = btn.textContent;
    btn.disabled = true;
    btn.textContent = '...';

    // FIX (auditoria UI): os cards do AXE FLEET vivem no axe registry
    // (tenant-scoped) e devices agent-managed só podem ser controlados
    // através da fila do AGENTE LOCAL. A rota core /api/devices/<id>/command
    // consulta o core registry — para estes devices ela responde 404 e o
    // miner NUNCA reinicia (teatro). Roteamos restart/identify/pause/resume
    // para os endpoints /api/axe-fleet/devices/<id>/{restart|identify|
    // pause|resume}, que enfileiram no agente (agent-managed) ou executam
    // direto no AxeOS HTTP API, e exigem o Bearer do tenant (authFetch).
    const isAgentRouted = command === 'restart' || command === 'identify' ||
      command === 'pause' || command === 'resume';
    const url = isAgentRouted
      ? '/api/axe-fleet/devices/' + encodeURIComponent(deviceId) + '/' + command
      : '/api/devices/' + encodeURIComponent(deviceId) + '/command';
    const payload = isAgentRouted ? { dry_run: false } : { command: command, dry_run: false };
    const opts = {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    };
    try {
      const send = authFetch;
      let resp = await send(url, opts);
      let data = await resp.json().catch(() => ({}));
      // The server owns the authorization to execute a physical action. The
      // browser confirmation above informs the operator; this short-lived,
      // one-time token makes the second step enforceable at the API boundary.
      if (data.confirmation_required && data.confirmation_token) {
        resp = await send(url, {
          ...opts,
          body: JSON.stringify({ ...payload, confirmation_token: data.confirmation_token }),
        });
        data = await resp.json().catch(() => ({}));
      }
      if (data.success) {
        const name = btn.closest('.axe-card, .fcc-card')?.querySelector('.axe-card__name, .fcc-card__name')?.textContent || 'device';
        showToast('success', (data.message || command + ' sent to ' + name));
      } else {
        showToast('error', data.error || ('Command failed (' + resp.status + ')'));
      }
    } catch (err) {
      showToast('error', 'Network error: ' + err.message);
    } finally {
      btn.disabled = false;
      btn.textContent = originalLabel;
    }
  }
  function _renderAxeCard(d, maxHr) {
    maxHr = maxHr || 1;
    const tel = d.telemetry || {};
    const status = d.status || 'OFFLINE';
    const isOnline = status === 'ONLINE' || status === 'HASHING';
    const isWarning = status === 'WARNING';
    const isOffline = !isOnline && !isWarning;
    const statusClass = isOnline ? 'online' : isWarning ? 'warning' : 'offline';
    const hrStr = tel.hashrate_str || '—';

    // Health score ring
    const hs = d.health_score || 0;
    const circumference = 2 * Math.PI * 14; // r=14
    const offset = circumference * (1 - hs / 100);
    const healthColor = hs >= 80 ? 'var(--accent-green)' : hs >= 50 ? 'var(--accent-amber)' : 'var(--accent-red)';
    const healthSvg = '<svg viewBox="0 0 32 32"><circle class="axe-card__health-bg" cx="16" cy="16" r="14"/><circle class="axe-card__health-fill" cx="16" cy="16" r="14" stroke="' + healthColor + '" stroke-dasharray="' + circumference + '" stroke-dashoffset="' + offset + '"/></svg>';

    // Capability badges
    const caps = d.capabilities || [];
    const capHtml = caps.slice(0, 5).map(c => '<span class="axe-cap-badge is-supported">' + escapeHtml(c) + '</span>').join('');

    // Stats — Fase 5: chip temp, VR temp, hashrate windows with NOT AVAILABLE fallback.
    // NOTE: _num() guard (shared, defined near fmt) — backend may send the
    // literal string "NOT AVAILABLE" for missing fields (core /api/devices
    // normalizes), so a plain != null check would crash .toFixed().
    const _NA = 'NOT AVAILABLE';
    const chipTemp = fmt.num(tel.chip_temp) ? tel.chip_temp.toFixed(0) + '°C' : (fmt.num(tel.temp_asic) ? tel.temp_asic.toFixed(0) + '°C' : (fmt.num(tel.temperature) ? tel.temperature.toFixed(0) + '°C' : _NA));
    const vrTemp = fmt.num(tel.vr_temp) ? tel.vr_temp.toFixed(0) + '°C' : (fmt.num(tel.temp_vreg) ? tel.temp_vreg.toFixed(0) + '°C' : _NA);
    const hr1h = fmt.num(tel.hashrate_1h) ? fmt.hashrate(tel.hashrate_1h) : _NA;
    const temp = fmt.num(tel.temperature) ? tel.temperature.toFixed(0) + '°C' : '—';
    const bestDiff = tel.best_diff ? fmt.diff(tel.best_diff) : '—';
    const shares = tel.shares_accepted != null ? tel.shares_accepted.toLocaleString() : '—';
    const uptime = tel.uptime_str || '—';
    const freq = tel.frequency_mhz ? tel.frequency_mhz + ' MHz' : '—';
    const hw = tel.hw_error_pct != null ? tel.hw_error_pct.toFixed(2) + '%' : '—';
    // FLEET audit G1: EFF + POWER were computed but never rendered on the
    // card. Fallback NOT AVAILABLE like CHIP/VR/HR 1H (honest, no zeros).
    const power = fmt.num(tel.power_watts) ? tel.power_watts.toFixed(0) + 'W' : _NA;
    const eff = fmt.num(tel.efficiency_jth) ? tel.efficiency_jth.toFixed(2) + ' J/TH' : _NA;

    // ── FLEET audit: PING + POOL + advice chips ──
    // latency_ms is probed by the backend per reachable device; the card
    // colors it by band (green ≤50ms, amber ≤150ms, red >150ms).
    const pingMs = fmt.num(d.latency_ms) ? d.latency_ms : null;
    const pingStr = pingMs != null ? pingMs + 'ms' : '—';
    const pingClass = pingMs == null ? '' : (pingMs <= 50 ? 'green' : pingMs <= 150 ? 'gold' : 'red');
    // POOL: prefer the pool host from pool_url, fall back to stratum_status.
    let poolStr = tel.stratum_status || '—';
    const poolRaw = tel.pool_url || '';
    if (poolRaw) {
      const host = String(poolRaw).replace(/^stratum\+tcp:\/\//, '').replace(/^[^@]+@/, '').split(':')[0];
      if (host) poolStr = host;
    }
    // Advice chips from the backend rule engine (healthy fleet → empty).
    const adviceList = Array.isArray(d.advice) ? d.advice : [];
    const adviceHtml = adviceList.length
      ? '<div class="axe-card__advice">' + adviceList.map(a => '<span class="axe-card__advice-chip">' + escapeHtml(a) + '</span>').join('') + '</div>'
      : '';

    // Check if any commands are supported
    var supportedCmds = d.capabilities || [];
    var hasCommands = supportedCmds.indexOf('restart') >= 0 || supportedCmds.indexOf('identify') >= 0 || supportedCmds.indexOf('pause') >= 0 || supportedCmds.indexOf('resume') >= 0;

    return '<div class="axe-card ' + (isOnline ? 'is-online' : isWarning ? 'is-warning' : 'is-offline') + '" data-device-id="' + escapeHtml(d.id) + '">' +
      '<div class="axe-card__head">' +
        '<div class="axe-card__health">' + healthSvg + '<span class="axe-card__health-label" style="color:' + healthColor + '">' + hs + '</span></div>' +
        '<div style="display:flex;flex-direction:column;gap:2px;flex:1;padding-left:10px">' +
          '<div style="display:flex;align-items:center;gap:6px">' +
            '<span class="axe-card__name">' + escapeHtml(d.name) + '</span>' +
            '<span class="axe-card__status-dot ' + statusClass + '"></span>' +
          '</div>' +
          // FLEET audit G2: manufacturer from the payload (fleet_health
          // serializes it). Fallback NOT AVAILABLE when absent.
          '<div class="axe-card__model">' + escapeHtml(d.manufacturer || _NA) + ' · ' + escapeHtml(d.model || 'unknown') + ' · ' + hrStr + '</div>' +
        '</div>' +
      '</div>' +
      (caps.length ? '<div class="axe-card__caps">' + capHtml + '</div>' : '') +
      '<div class="axe-card__mh-wrap"><div class="axe-card__mh-bar" style="width:' + Math.min(100, ((tel.hashrate_hs || 0) / maxHr) * 100) + '%"></div></div>' +
      '<div class="axe-card__stats">' +
        '<div class="axe-card__stat"><div class="lbl">TEMP</div><div class="val ' + (fmt.num(tel.temperature) && tel.temperature > 70 ? 'red' : fmt.num(tel.temperature) && tel.temperature > 55 ? 'gold' : 'green') + '">' + temp + '</div></div>' +
        '<div class="axe-card__stat"><div class="lbl">CHIP</div><div class="val cyan">' + chipTemp + '</div></div>' +
        '<div class="axe-card__stat"><div class="lbl">VR</div><div class="val cyan">' + vrTemp + '</div></div>' +
        '<div class="axe-card__stat"><div class="lbl">HR 1H</div><div class="val cyan">' + hr1h + '</div></div>' +
        '<div class="axe-card__stat"><div class="lbl">EFF</div><div class="val cyan">' + eff + '</div></div>' +
        '<div class="axe-card__stat"><div class="lbl">POWER</div><div class="val cyan">' + power + '</div></div>' +
        '<div class="axe-card__stat"><div class="lbl">DIFF</div><div class="val gold">' + bestDiff + '</div></div>' +
        '<div class="axe-card__stat"><div class="lbl">UPTIME</div><div class="val cyan">' + uptime + '</div></div>' +
        '<div class="axe-card__stat"><div class="lbl">PING</div><div class="val ' + pingClass + '">' + pingStr + '</div></div>' +
        '<div class="axe-card__stat"><div class="lbl">POOL</div><div class="val cyan" title="' + escapeHtml(tel.pool_url || tel.stratum_status || '') + '">' + escapeHtml(poolStr) + '</div></div>' +
      '</div>' +
      adviceHtml +
      (hasCommands ? '<div class="axe-card__cmds">' +
        (supportedCmds.indexOf('restart') >= 0 ? '<button class="axe-cmd-btn axe-cmd-btn--restart" data-device-id="' + escapeHtml(d.id) + '" data-cmd="restart">↻ Restart</button>' : '') +
        (supportedCmds.indexOf('identify') >= 0 ? '<button class="axe-cmd-btn axe-cmd-btn--identify" data-device-id="' + escapeHtml(d.id) + '" data-cmd="identify">◈ Identify</button>' : '') +
        (supportedCmds.indexOf('pause') >= 0 ? '<button class="axe-cmd-btn axe-cmd-btn--pause" data-device-id="' + escapeHtml(d.id) + '" data-cmd="pause">⎔ Pause</button>' : '') +
        (supportedCmds.indexOf('resume') >= 0 ? '<button class="axe-cmd-btn axe-cmd-btn--resume" data-device-id="' + escapeHtml(d.id) + '" data-cmd="resume">▶ Resume</button>' : '') +
      '</div>' : '<div class="axe-card__cmds axe-card__cmds--ro"><span class="axe-card__ro-badge">READ-ONLY</span></div>') +
    '</div>';
  }

  function openAxeDetail(deviceId) {
    if (!dom.axeDetail || !dom.axeDetailTitle || !dom.axeDetailBody) return;
    dom.axeDetail.style.display = 'block';
    dom.axeDetailTitle.textContent = 'Loading device...';
    dom.axeDetailBody.innerHTML = '<div class="axe-detail__loading">loading telemetry…</div>';

    authFetch('/api/axe-fleet/devices/' + encodeURIComponent(deviceId))
      .then(r => r.json())
      .then(data => {
        const dev = data.device || {};
        const tel = data.latest_telemetry || {};
        dom.axeDetailTitle.textContent = dev.name || 'Device';

        const items = [
          { lbl: 'Model', val: dev.model || 'unknown' },
          { lbl: 'Firmware', val: (dev.firmware || '') + ' ' + (dev.firmware_version || '') },
          { lbl: 'IP Address', val: dev.ip_address || '—' },
          { lbl: 'Status', val: dev.status || 'OFFLINE', cls: dev.status === 'ONLINE' ? 'green' : 'red' },
          { lbl: 'Hashrate', val: fmt.hashrate(tel.hashrate_hs || 0) },
          { lbl: 'Hashrate 1m', val: fmt.num(tel.hashrate_1m) ? fmt.hashrate(tel.hashrate_1m) : 'NOT AVAILABLE' },
          { lbl: 'Hashrate 10m', val: fmt.num(tel.hashrate_10m) ? fmt.hashrate(tel.hashrate_10m) : 'NOT AVAILABLE' },
          { lbl: 'Hashrate 1h', val: fmt.num(tel.hashrate_1h) ? fmt.hashrate(tel.hashrate_1h) : 'NOT AVAILABLE' },
          { lbl: 'Chip Temp', val: fmt.num(tel.chip_temp) ? tel.chip_temp + '°C' : (fmt.num(tel.temp_asic) ? tel.temp_asic + '°C' : 'NOT AVAILABLE'), cls: fmt.num(tel.chip_temp) && tel.chip_temp > 70 ? 'red' : 'green' },
          { lbl: 'VR Temp', val: fmt.num(tel.vr_temp) ? tel.vr_temp + '°C' : (fmt.num(tel.temp_vreg) ? tel.temp_vreg + '°C' : 'NOT AVAILABLE') },
          { lbl: 'Temperature', val: fmt.num(tel.temperature) ? tel.temperature + '°C' : '—', cls: fmt.num(tel.temperature) && tel.temperature > 70 ? 'red' : 'green' },
          { lbl: 'Power', val: tel.power_watts ? tel.power_watts + ' W' : '—' },
          { lbl: 'Frequency', val: tel.frequency_mhz ? tel.frequency_mhz + ' MHz' : '—' },
          { lbl: 'Voltage', val: tel.voltage_mv ? tel.voltage_mv + ' mV' : '—' },
          { lbl: 'Best Diff', val: tel.best_diff ? fmt.diff(tel.best_diff) : '—', cls: 'gold' },
          { lbl: 'Shares Accepted', val: tel.shares_accepted != null ? tel.shares_accepted.toLocaleString() : '—' },
          { lbl: 'Shares Rejected', val: tel.shares_rejected != null ? tel.shares_rejected.toLocaleString() : '—' },
          { lbl: 'HW Error %', val: fmt.num(tel.hw_error_pct) ? tel.hw_error_pct.toFixed(2) + '%' : '—', cls: fmt.num(tel.hw_error_pct) && tel.hw_error_pct > 1 ? 'red' : 'green' },
          { lbl: 'Efficiency', val: fmt.num(tel.efficiency_jth) ? tel.efficiency_jth.toFixed(1) + ' J/TH' : '—' },
          { lbl: 'Uptime', val: tel.uptime_str || '—' },
          { lbl: 'Free Heap', val: tel.free_heap ? tel.free_heap.toLocaleString() + ' B' : '—' },
          { lbl: 'WiFi RSSI', val: tel.wifi_rssi != null ? tel.wifi_rssi + ' dBm' : '—' },
          { lbl: 'Last Seen', val: dev.last_seen ? fmt.age(dev.last_seen) : '—' },
        ];

        dom.axeDetailBody.innerHTML = items.map(it =>
          '<div class="axe-detail__item"><div class="lbl">' + escapeHtml(it.lbl) + '</div><div class="val' + (it.cls ? ' ' + escapeHtml(it.cls) : '') + '">' + escapeHtml(String(it.val)) + '</div></div>'
        ).join('');

        // Phase C: load telemetry history chart
        loadDeviceHistoryChart(deviceId);
      })
      .catch(() => {
        dom.axeDetailBody.innerHTML = '<div class="axe-detail__loading">error loading device telemetry</div>';
      });
  }

  // ── Phase C: Device History Chart ─────────────────────────────────────
  let _axeDetailChart = null;

  async function loadDeviceHistoryChart(deviceId) {
    const wrap = document.getElementById('axe-detail-chart-wrap');
    const canvas = document.getElementById('axe-detail-chart');
    const countBadge = document.getElementById('axe-detail-chart-count');
    if (!wrap || !canvas || typeof Chart === 'undefined') return;  // Issue #186: defer-safe

    // Destroy previous chart instance so Chart.js doesn't complain.
    if (_axeDetailChart) { _axeDetailChart.destroy(); _axeDetailChart = null; }

    try {
      const r = await authFetch('/api/axe-fleet/devices/' + encodeURIComponent(deviceId) + '/history?limit=120');
      if (!r.ok) return;
      const data = await r.json();
      const rows = data.history || [];
      if (rows.length < 2) return;  // need at least 2 points for a line

      wrap.style.display = 'block';
      if (countBadge) countBadge.textContent = rows.length + ' points';

      var labels = rows.map(function(r) {
        var d = new Date(r.ts * 1000);
        return d.getHours().toString().padStart(2, '0') + ':' + d.getMinutes().toString().padStart(2, '0');
      });

      var hrVals = rows.map(function(r) { return r.hashrate ? r.hashrate / 1e12 : null; });
      var tempVals = rows.map(function(r) { return r.temperature; });
      var effVals = rows.map(function(r) { return r.efficiency_jth; });

      _axeDetailChart = new Chart(canvas.getContext('2d'), {
        type: 'line',
        data: {
          labels: labels,
          datasets: [
            { label: 'Hashrate TH/s', data: hrVals, borderColor: 'rgb(6,214,240)', backgroundColor: 'rgba(6,214,240,0.06)', tension: 0.3, pointRadius: 0, fill: true, yAxisID: 'y' },
            { label: 'Temp °C', data: tempVals, borderColor: 'rgb(255,160,0)', backgroundColor: 'rgba(255,160,0,0.04)', tension: 0.3, pointRadius: 0, borderDash: [4, 2], yAxisID: 'y1' },
            { label: 'Eff J/TH', data: effVals, borderColor: 'rgb(186,133,224)', backgroundColor: 'transparent', tension: 0.3, pointRadius: 0, borderDash: [2, 3], yAxisID: 'y1' },
          ]
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          interaction: { mode: 'index', intersect: false },
          scales: {
            x: { ticks: { color: cssVar('--text-tertiary'), maxTicksLimit: 10, font: { size: 9 } }, grid: { color: 'rgba(94,89,82,0.12)' } },
            y: { type: 'linear', position: 'left', title: { display: true, text: 'TH/s', color: 'rgb(6,214,240)' }, ticks: { color: cssVar('--text-tertiary'), font: { size: 9 } }, grid: { color: 'rgba(94,89,82,0.10)' } },
            y1: { type: 'linear', position: 'right', title: { display: true, text: '°C / J/TH', color: 'rgb(255,160,0)' }, ticks: { color: cssVar('--text-tertiary'), font: { size: 9 } }, grid: { display: false } }
          },
          plugins: {
            legend: { labels: { color: cssVar('--text-secondary'), font: { size: 9 }, usePointStyle: true, padding: 12 } }
          }
        }
      });
    } catch (e) {
      // Non-fatal: chart is a nice-to-have, detail panel still works.
    }
  }

  // ── AXE FLEET: LAN discovery (subnet scan) ───────────────────────────
  // Automatic miner detection so the operator never types an IP. Flow:
  //  1. POST /api/axe-fleet/scan {cidr}  → 202 {scan_id}
  //  2. Poll GET /api/axe-fleet/scan/<id> every 1.5s (progress + found)
  //  3. Render found miners as rows with a per-row ADD button that reuses
  //     the same addAxeDevice() as the manual form.
  function renderAxeScanResults(found, scan) {
    const box = dom.axeScanResults;
    if (!box) return;
    if (!found || !found.length) {
      // No miners: surface the alive-vs-miner layer (hosts whose TCP port
      // opened but no miner protocol answered) and the private-LAN topology
      // hint — a flat "no miners found" hides whether the subnet is even
      // reachable (cloud dashboard vs home LAN).
      const alive = (scan && scan.alive) || 0;
      const hint = (scan && scan.hint) || '';
      let html = '<div style="font-size:9px;color:var(--text-tertiary)">no miners found on this subnet</div>';
      if (alive > 0) {
        html += '<div style="font-size:9px;color:var(--text-secondary);margin-top:4px">' + alive + ' host(s) alive (porta TCP aberta) mas sem protocolo de miner — possíveis ASICs com API autenticada/firewall. Verifique com TEST CONNECTIVITY em um IP específico.</div>';
      }
      if (hint) {
        html += '<div style="font-size:9px;color:var(--amber);margin-top:4px">' + escapeHtml(hint) + '</div>';
      }
      box.innerHTML = html;
      return;
    }
    const rows = found.map(d => {
      const ip = escapeHtml(d.ip || '');
      const model = escapeHtml(d.model || 'unknown');
      const host = escapeHtml(d.hostname || '');
      const type = d.type === 'cgminer' ? 'CGMINER' : 'BITAXE';
      const hr = d.hashrate_hs ? fmt.hashrate(d.hashrate_hs) : '';
      const title = escapeHtml([d.firmware, d.version].filter(Boolean).join(' ') || 'miner');
      return `<div class="axe-scan__row" data-ip="${ip}" style="display:flex;gap:6px;align-items:center;padding:2px 0;border-bottom:1px dashed var(--border-subtle);font-size:10px">
        <span class="badge badge--green" style="font-size:7px;min-width:48px">${type}</span>
        <span style="color:var(--text-primary)" title="${title}">${ip}</span>
        <span style="color:var(--text-secondary)" title="${title}">${model}${host ? ' · ' + host : ''}</span>
        ${hr ? `<span style="color:var(--text-tertiary)">${escapeHtml(hr)}</span>` : ''}
        <button class="chip axe-scan-add" data-ip="${ip}" data-model="${model}" data-host="${host}" data-fw="${escapeHtml(d.firmware || '')}" data-ver="${escapeHtml(d.version || '')}" data-hr="${Number(d.hashrate_hs) || 0}" style="margin-left:auto;font-size:8px">+ ADD</button>
      </div>`;
    }).join('');
    box.innerHTML = rows;
    // Scan ADD opens the wizard's confirm step (step 3) with the detected
    // miner pre-filled — a single place to review + name before registering.
    box.querySelectorAll('.axe-scan-add').forEach(btn => {
      btn.addEventListener('click', () => {
        _axeWizState.ip = btn.getAttribute('data-ip') || '';
        _axeWizState.mode = 'scan';
        _axeWizState.device = {
          protocol: btn.getAttribute('data-model') ? 'bitaxe' : '',
          model: btn.getAttribute('data-model') || 'miner',
          hostname: btn.getAttribute('data-host') || '',
          firmware: btn.getAttribute('data-fw') || '',
          version: btn.getAttribute('data-ver') || '',
          hashrate_hs: Number(btn.getAttribute('data-hr') || 0),
        };
        if (dom.axeAddName) dom.axeAddName.value = btn.getAttribute('data-model') || '';
        if (dom.axeManualNameRow) dom.axeManualNameRow.style.display = 'block';
        renderAxeConfirm();
        gotoAxeWizStep(3);
      });
    });
  }

  async function startAxeScan(cidr) {
    const statusEl = dom.axeScanStatus;
    const btn = dom.axeScanBtn;
    const cidrInput = dom.axeScanCidr;
    if (btn) btn.disabled = true;
    if (statusEl) { statusEl.textContent = '> scanning ' + cidr + '…'; statusEl.style.color = 'var(--text-tertiary)'; }
    try {
      const r = await authFetch('/api/axe-fleet/scan', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ cidr })
      });
      const data = await r.json();
      if (!r.ok || !data.scan_id) {
        if (statusEl) { statusEl.textContent = '? ' + ((data && data.error) || 'scan failed'); statusEl.style.color = 'var(--accent-red)'; }
        return;
      }
      const scanId = data.scan_id;
      // Poll until done
      for (let i = 0; i < 240; i++) {  // ~6 min cap
        await new Promise(res => setTimeout(res, 1500));
        try {
          const p = await authFetch('/api/axe-fleet/scan/' + scanId);
          const pd = await p.json();
          const s = pd.scan || {};
          const scanned = s.scanned || 0;
          const total = s.total || 0;
          if (statusEl) statusEl.textContent = `> probing ${scanned}/${total} hosts…`;
          if (s.status === 'done' || s.status === 'error') {
            if (statusEl) {
              const foundN = (s.found || []).length;
              const aliveN = s.alive || 0;
              statusEl.textContent = s.error ? '? ' + s.error : foundN > 0 ? `✓ ${foundN} miner(s) found` : (aliveN > 0 ? `✓ 0 miners · ${aliveN} host(s) alive sem protocolo` : '✓ 0 miners — nada respondeu');
              statusEl.style.color = s.error ? 'var(--accent-red)' : 'var(--accent-green)';
            }
            renderAxeScanResults(s.found || [], s);
            return;
          }
        } catch (e) { /* transient poll failure — keep polling */ }
      }
      if (statusEl) { statusEl.textContent = '? scan timed out'; statusEl.style.color = 'var(--accent-red)'; }
    } catch (e) {
      if (statusEl) { statusEl.textContent = '? network error: ' + e.message; statusEl.style.color = 'var(--accent-red)'; }
    } finally {
      if (btn) btn.disabled = false;
      if (cidrInput) cidrInput.disabled = false;
    }
  }

  function initAxeScanControls() {
    const cidrInput = dom.axeScanCidr;
    const btn = dom.axeScanBtn;
    if (!cidrInput || !btn) return;
    // Prefill with a suggested local subnet (best-effort; backend derives it
    // from this host's interfaces).
    authFetch('/api/axe-fleet/scan/subnets')
      .then(r => r.ok ? r.json() : { subnets: [] })
      .then(d => {
        const s = (d.subnets || [])[0];
        if (s && !cidrInput.value.trim()) cidrInput.value = s;
      })
      .catch(() => {});
    btn.addEventListener('click', () => {
      const cidr = (cidrInput.value || '').trim() || '192.168.1.0/24';
      cidrInput.disabled = true;
      // Clear stale results BEFORE the scan starts (a null/empty call must
      // blank the box, not render the "no miners found" placeholder).
      if (dom.axeScanResults) dom.axeScanResults.innerHTML = '';
      startAxeScan(cidr);
    });
    cidrInput.addEventListener('keydown', e => {
      if (e.key === 'Enter') { e.preventDefault(); btn.click(); }
    });
  }

  // ── AXE FLEET onboarding wizard ──────────────────────────────────────
  // 3 steps: 1 · method → 2 · connect (scan OR manual+test) → 3 · confirm.
  // Pure helpers are mirrored in tests/test_app_js_core.js.

  // Build the connectivity report rows from the /diagnose response. Pure —
  // returns an array of {label, ok, val, detail} for rendering + tests.
  function buildConnectivityReport(result) {
    const r = result || {};
    const rows = [];
    rows.push({ label: 'DNS', ok: !!r.dns_resolution, val: r.dns_resolution ? 'OK' : 'FAIL', detail: r.dns_resolution ? '' : (r.error_detail || 'hostname did not resolve') });
    if (r.bitaxe_http) {
      const di = r.device_info || {};
      rows.push({ label: 'AxeOS :80', ok: true, val: 'BITAXE', detail: [di.model, di.firmware].filter(Boolean).join(' · ') });
    } else {
      rows.push({ label: 'AxeOS :80', ok: false, val: 'no', detail: 'no ESP-Miner API on port 80' });
    }
    if (r.cgminer_tcp) {
      const di = r.device_info || {};
      // Show firmware label for the cgminer row — Braiins OS+ devices
      // answer on :4028 but the protocol label should reflect the detector.
      const cgLabel = (r.protocol === 'braiins') ? 'BRAIINS' : 'CGMINER';
      rows.push({ label: 'cgminer :4028', ok: true, val: cgLabel, detail: [di.model, di.version].filter(Boolean).join(' · ') });
    } else {
      rows.push({ label: 'cgminer :4028', ok: false, val: 'no', detail: 'no cgminer protocol on port 4028' });
    }
    // Protocol-presence rows (D): a modern authenticated miner (Braiins
    // OS+/Antminer login page) answers nothing on the classic probes but
    // shows TCP :443 or a non-ESP-Miner web server on :80 — surface that
    // instead of a flat "no protocol".
    if (r.https_tcp && !r.bitaxe_http && !r.cgminer_tcp) {
      rows.push({ label: 'HTTPS :443', ok: true, val: 'OPEN', detail: 'porta 443 aberta — firmware moderno (Braiins/Antminer) com API autenticada' });
    }
    if (r.http_server && !r.bitaxe_http && !r.cgminer_tcp) {
      rows.push({ label: 'HTTP :80', ok: true, val: 'server', detail: 'servidor HTTP presente mas NÃO é ESP-Miner — possível página de login de ASIC' });
    }
    rows.push({ label: 'elapsed', ok: true, val: (r.elapsed_ms != null ? r.elapsed_ms + 'ms' : '—'), detail: '' });
    return rows;
  }

  // Render the connectivity report into #axe-test-result. Pure-ish (DOM
  // writes only) so a failed test leaves clear actionable guidance.
  function renderConnectivityReport(result) {
    const box = dom.axeTestResult;
    if (!box) return;
    const rows = buildConnectivityReport(result);
    const reachable = !!(result || {}).reachable;
    const proto = (result || {}).protocol;
    const html = rows.map(row => {
      const cls = row.ok ? 'axe-wiz-check--ok' : 'axe-wiz-check--fail';
      const icon = row.ok ? '✓' : '✗';
      const detail = row.detail ? `<span style="color:var(--text-tertiary);margin-left:6px">${escapeHtml(row.detail)}</span>` : '';
      return `<div class="axe-wiz-check ${cls}"><span>${icon}</span><span class="axe-wiz-check__label">${escapeHtml(row.label)}</span><span class="axe-wiz-check__val">${escapeHtml(row.val)}</span>${detail}</div>`;
    }).join('');
    const verdict = reachable
      ? `<div class="axe-wiz-check axe-wiz-check--ok" style="margin-top:4px"><span>✓</span><span class="axe-wiz-check__label">READY</span><span class="axe-wiz-check__val">${escapeHtml(String(proto || '').toUpperCase())} miner detected</span></div>`
      : `<div class="axe-wiz-check axe-wiz-check--fail" style="margin-top:4px"><span>✗</span><span class="axe-wiz-check__label">UNREACHABLE</span><span class="axe-wiz-check__val">check power / network / firewall</span><span style="color:var(--text-tertiary);margin-left:6px">${escapeHtml((result || {}).error_detail || '')}</span></div>`;
    box.innerHTML = html + verdict;
    // Reveal the optional name field only when the miner is reachable
    if (dom.axeManualNameRow) dom.axeManualNameRow.style.display = reachable ? 'block' : 'none';
    return reachable;
  }

  // Test connectivity for the manual-IP step. Shows a spinner, calls the
  // backend /diagnose endpoint, renders the report, then advances to step 3
  // when a miner is reachable.
  async function testAxeConnectivity() {
    const ipInput = dom.axeAddIp;
    const btn = dom.axeTestConn;
    const box = dom.axeTestResult;
    if (!ipInput || !btn) return false;
    const ip = (ipInput.value || '').trim();
    if (!ip) {
      if (box) box.innerHTML = '<div class="axe-wiz-check axe-wiz-check--fail"><span>✗</span><span class="axe-wiz-check__label">INPUT</span><span class="axe-wiz-check__val">enter an IP or hostname</span></div>';
      return false;
    }
    const prev = btn.textContent;
    btn.disabled = true;
    btn.textContent = '… testing';
    if (box) box.innerHTML = '<div class="axe-wiz-check axe-wiz-check--idle"><span class="axe-wiz__spinner"></span><span class="axe-wiz-check__label">PROBING</span><span class="axe-wiz-check__val">' + escapeHtml(ip) + '</span></div>';
    try {
      const r = await authFetch('/api/axe-fleet/diagnose/' + encodeURIComponent(ip));
      const data = await r.json();
      const reachable = renderConnectivityReport(data);
      // Store the detected firmware/model from the diagnose response so
      // the confirm screen can preview them before registration.
      _axeWizState._detectedProtocol = data && data.protocol;
      _axeWizState._detectedFirmware = data && data.detected_firmware;
      _axeWizState._detectedModel = data && data.detected_model;
      _axeWizState._detectedVersion = (data && data.device_info && data.device_info.version) || '';
      if (reachable) {
        // Advance to confirm step with the detected device. Carry the
        // protocol from the diagnose response (top-level) into device so
        // the confirm summary can display it.
        _axeWizState.device = Object.assign({}, (data && data.device_info) || {}, { protocol: data && data.protocol });
        _axeWizState.ip = ip;
        renderAxeConfirm();
        gotoAxeWizStep(3);
        return true;
      }
      return false;
    } catch (e) {
      if (box) box.innerHTML = '<div class="axe-wiz-check axe-wiz-check--fail"><span>✗</span><span class="axe-wiz-check__label">ERROR</span><span class="axe-wiz-check__val">' + escapeHtml(e.message) + '</span></div>';
      return false;
    } finally {
      btn.disabled = false;
      btn.textContent = prev;
    }
  }

  const _axeWizState = { ip: '', name: '', device: null, mode: null };

  function gotoAxeWizStep(step) {
    const form = dom.axeAddForm;
    if (!form) return;
    step = Math.max(1, Math.min(3, step));
    // Panels: data-wiz-panel="1|2|3" — show matching, hide others
    form.querySelectorAll('[data-wiz-panel]').forEach(p => {
      p.style.display = (Number(p.getAttribute('data-wiz-panel')) === step) ? 'block' : 'none';
    });
    // Within step 2, choose scan vs manual mode
    if (step === 2) {
      form.querySelectorAll('[data-wiz-panel][data-wiz-mode]').forEach(p => {
        const on = p.getAttribute('data-wiz-mode') === (_axeWizState.mode || 'scan');
        p.style.display = on ? 'block' : 'none';
      });
    }
    // Step indicator
    if (dom.axeWizSteps) {
      dom.axeWizSteps.querySelectorAll('[data-wiz-step]').forEach(s => {
        const n = Number(s.getAttribute('data-wiz-step'));
        s.classList.toggle('is-active', n === step);
        s.classList.toggle('is-done', n < step);
      });
    }
    // Focus primary input of the active panel
    if (step === 1 && dom.axeEmptyAdd) dom.axeEmptyAdd.blur();
    if (step === 2 && _axeWizState.mode === 'manual') { setTimeout(() => dom.axeAddIp?.focus(), 60); }
    if (step === 2 && _axeWizState.mode !== 'manual') { setTimeout(() => dom.axeScanCidr?.focus(), 60); }
    if (step === 3) { setTimeout(() => dom.axeAddName?.focus(), 60); }
  }

  function setAxeWizMode(mode) {
    _axeWizState.mode = mode === 'manual' ? 'manual' : 'scan';
    gotoAxeWizStep(2);
  }

  function resetAxeWizard() {
    clearTimeout(_axeDetectTimer);
    _axeDetectTimer = null;
    _axeWizState.ip = '';
    _axeWizState.name = '';
    _axeWizState.device = null;
    _axeWizState._detectedProtocol = '';
    _axeWizState._detectedFirmware = '';
    _axeWizState._detectedModel = '';
    _axeWizState._detectedVersion = '';
    if (dom.axeTestResult) dom.axeTestResult.innerHTML = '';
    if (dom.axeManualNameRow) dom.axeManualNameRow.style.display = 'none';
    if (dom.axeWizConfirm) dom.axeWizConfirm.innerHTML = '';
    if (dom.axeScanResults) dom.axeScanResults.innerHTML = '';
    if (dom.axeScanStatus) dom.axeScanStatus.textContent = '';
    if (dom.axeAddStatus) dom.axeAddStatus.textContent = '';
    const fwPreview = document.getElementById('axe-fw-preview');
    if (fwPreview) { fwPreview.innerHTML = ''; fwPreview.style.display = 'none'; }
  }

  // Render the detected device summary in the confirm step.
  function renderAxeConfirm() {
    const box = dom.axeWizConfirm;
    if (!box) return;
    const d = _axeWizState.device || {};
    const proto = d.protocol || _axeWizState._detectedProtocol || (_axeWizState.mode === 'manual' ? 'manual' : '');
    const fwLabel = _axeWizState._detectedFirmware || d.firmware || '';
    const fwVersion = d.version || _axeWizState._detectedVersion || '';
    const fwStr = [fwLabel, fwVersion].filter(Boolean).join(' ');
    const rows = [
      ['IP', _axeWizState.ip],
      ['protocol', proto ? proto.toUpperCase() : '—'],
      ['model', d.model || _axeWizState._detectedModel || '—'],
      ['hostname', d.hostname || '—'],
      ['firmware', fwStr || '—'],
      ['hashrate', d.hashrate_hs ? fmt.hashrate(d.hashrate_hs) : '—'],
    ].map(([k, v]) => `<div style="display:flex;gap:6px"><span style="color:var(--text-tertiary);min-width:64px">${k}</span><span style="color:var(--text-primary)">${escapeHtml(String(v))}</span></div>`).join('');
    box.innerHTML = `<div class="axe-wiz__confirm-title">✓ ready to add</div>${rows}`;
  }

  function initAxeFleetControls() {
    // ── Scan Network button ──────────────────────────────────────
    const scanBtn = dom.axeFleetScan || document.getElementById('axe-fleet-scan');
    if (scanBtn) {
      scanBtn.addEventListener('click', function() { scanNetwork(); });
    }

    const addBtn = dom.axeFleetAdd || document.getElementById('axe-fleet-add');
    const form = dom.axeAddForm || document.getElementById('axe-add-form');
    const cancelBtn = document.getElementById('axe-add-cancel');
    const saveBtn = document.getElementById('axe-add-save');
    const ipInput = document.getElementById('axe-add-ip');
    const nameInput = document.getElementById('axe-add-name');
    const statusEl = document.getElementById('axe-add-status');
    const emptyAdd = dom.axeEmptyAdd || document.getElementById('axe-empty-add');
    if (!addBtn || !form) return;

    const openWizard = () => {
      resetAxeWizard();
      form.style.display = 'block';
      gotoAxeWizStep(1);
    };

    addBtn.addEventListener('click', openWizard);
    emptyAdd?.addEventListener('click', openWizard);
    cancelBtn?.addEventListener('click', () => {
      form.style.display = 'none';
      resetAxeWizard();
      if (statusEl) statusEl.textContent = '';
      if (ipInput) ipInput.value = '';
      if (nameInput) nameInput.value = '';
    });

    // Device detail close
    if (dom.axeDetailClose) {
      dom.axeDetailClose.addEventListener('click', () => {
        if (dom.axeDetail) dom.axeDetail.style.display = 'none';
      });
    }

    // Step 1 method cards
    form.querySelectorAll('[data-wiz-method]').forEach(m => {
      m.addEventListener('click', () => setAxeWizMode(m.getAttribute('data-wiz-method')));
    });
    // Back buttons (data-wiz-back="1|2")
    form.querySelectorAll('[data-wiz-back]').forEach(b => {
      b.addEventListener('click', () => gotoAxeWizStep(Number(b.getAttribute('data-wiz-back'))));
    });

    // Manual: test connectivity
    dom.axeTestConn?.addEventListener('click', testAxeConnectivity);
    ipInput?.addEventListener('keydown', e => {
      if (e.key === 'Enter') { e.preventDefault(); testAxeConnectivity(); }
    });

    // ── Auto-detect firmware on IP input (debounced preview) ─────────
    // While the operator types an IP, the diagnose endpoint is silently
    // called in the background (600ms debounce). The result is rendered
    // as a live firmware preview chip so the operator sees the detected
    // firmware/model/protocol BEFORE clicking "TEST CONNECTIVITY" or
    // registering. This turns a blind IP type-in into an informative
    // discovery flow.
    let _axeDetectTimer = null;
    const fwPreview = document.getElementById('axe-fw-preview');

    function _axeAutoDetect(ip) {
      if (!fwPreview) return;
      if (!ip || ip.trim().length < 7) {
        fwPreview.innerHTML = '';
        fwPreview.style.display = 'none';
        return;
      }
      fwPreview.style.display = 'flex';
      fwPreview.innerHTML = '<span class="axe-fw-preview__spinner"></span><span class="axe-fw-preview__text">detecting firmware…</span>';
    }

    async function _axeRunDetect(ip) {
      if (!ip || ip.trim().length < 7) return;
      try {
        // Use the lightweight /detect endpoint — faster than /diagnose
        // since it only calls detect_firmware() (no TCP port scan).
        // Response shape: {firmware, adapter_type, version, model, capabilities, reachable}
        const r = await authFetch('/api/axe-fleet/detect/' + encodeURIComponent(ip.trim()));
        const data = await r.json();
        // Populate the wizard state so confirm step has the data.
        // The /detect response is flat (no device_info wrapper), so
        // we map fields directly to the wizard state.
        _axeWizState.ip = ip.trim();
        _axeWizState._detectedProtocol = data && data.adapter_type;
        _axeWizState._detectedFirmware = data && data.firmware;
        _axeWizState._detectedModel = data && data.model;
        _axeWizState._detectedVersion = (data && data.version) || '';
        if (data && data.reachable) {
          _axeWizState.device = {
            model: data.model || '',
            firmware: data.firmware || '',
            version: data.version || '',
            protocol: data.adapter_type || '',
            hostname: '',
            hashrate_hs: 0,
          };
        }
        _axeRenderFwPreview(data);
      } catch (e) {
        if (fwPreview) {
          fwPreview.innerHTML = '';
          fwPreview.style.display = 'none';
        }
      }
    }

    function _axeRenderFwPreview(data) {
      if (!fwPreview) return;
      // /detect response is flat: {firmware, adapter_type, model, version, capabilities, reachable, error}
      const reachable = !!(data && data.reachable);
      const proto = (data && data.adapter_type) || '';
      const fw = (data && data.firmware) || '';
      const model = (data && data.model) || '';
      if (reachable && (proto || model || fw)) {
        const protoLabel = proto.toUpperCase();
        const protoCls = proto === 'bitaxe' ? 'axe-fw-preview__chip--bitaxe'
          : proto === 'braiins' ? 'axe-fw-preview__chip--braiins'
          : proto === 'cgminer' ? 'axe-fw-preview__chip--cgminer'
          : 'axe-fw-preview__chip--other';
        const parts = []
          .concat(protoLabel ? [`<span class="axe-fw-preview__chip ${protoCls}">${escapeHtml(protoLabel)}</span>`] : [])
          .concat(fw ? [`<span class="axe-fw-preview__text">${escapeHtml(fw)}</span>`] : [])
          .concat(model ? [`<span class="axe-fw-preview__text axe-fw-preview__text--muted">${escapeHtml(model)}</span>`] : [])
          .join('');
        fwPreview.innerHTML = `<span class="axe-fw-preview__icon">✓</span>${parts}`;
        fwPreview.style.display = 'flex';
      } else {
        // Unreachable — show the error from the detector
        const err = (data && data.error) || 'no miner detected on this IP';
        fwPreview.innerHTML = `<span class="axe-fw-preview__icon" style="color:var(--orange)">✗</span><span class="axe-fw-preview__text axe-fw-preview__text--muted">${escapeHtml(String(err).substring(0, 80))}</span>`;
        fwPreview.style.display = 'flex';
      }
    }

    ipInput?.addEventListener('input', () => {
      clearTimeout(_axeDetectTimer);
      const ip = (ipInput.value || '').trim();
      _axeAutoDetect(ip);
      if (ip.length >= 7) {
        _axeDetectTimer = setTimeout(() => _axeRunDetect(ip), 600);
      }
    });

    saveBtn?.addEventListener('click', async () => {
      const ip = (_axeWizState.ip || ipInput?.value || '').trim();
      if (!ip) { if (statusEl) { statusEl.textContent = '? enter IP address'; statusEl.style.color = 'var(--accent-red)'; } gotoAxeWizStep(1); return; }
      const name = (nameInput?.value || '').trim();
      if (statusEl) { statusEl.textContent = '> connecting...'; statusEl.style.color = 'var(--text-tertiary)'; }
      const ok = await addAxeDevice(ip, name);
      if (statusEl) {
        statusEl.textContent = ok ? '? added — refreshing...' : '? failed — see console';
        statusEl.style.color = ok ? 'var(--accent-green)' : 'var(--accent-red)';
      }
      if (ok) {
        setTimeout(() => {
          form.style.display = 'none';
          resetAxeWizard();
          if (ipInput) ipInput.value = '';
          if (nameInput) nameInput.value = '';
          if (statusEl) statusEl.textContent = '';
          fetchAxeFleet();
        }, 1500);
      }
    });

    initAxeScanControls();
    initAxeAgentPanel();
  }

  // ── SaaS AGENT onboarding panel ─────────────────────────────────────
  // The cloud dashboard cannot reach the user's LAN (192.168.x.x is not
  // routable from Render), so a local agent connects OUT and pushes
  // telemetry. This panel mints the per-tenant JWT (POST /api/agent/token)
  // and prints the docker run one-liner for the user's home network.
  function initAxeAgentPanel() {
    const panel = document.getElementById('axe-agent-panel');
    const btn = document.getElementById('axe-agent-btn');
    if (!panel || !btn) return;

    const open = () => {
      // Close the add-wizard if open so the two modals never overlap.
      const form = dom.axeAddForm || document.getElementById('axe-add-form');
      if (form && form.style.display !== 'none') form.style.display = 'none';
      panel.style.display = 'block';
    };
    const close = () => { panel.style.display = 'none'; };
    btn.addEventListener('click', open);
    document.getElementById('axe-agent-close')?.addEventListener('click', close);

    const statusEl = document.getElementById('axe-agent-status');
    const tokenRow = document.getElementById('axe-agent-token-row');
    const tokenArea = document.getElementById('axe-agent-token');
    const dockerPre = document.getElementById('axe-agent-docker');
    const oneLinerPre = document.getElementById('axe-agent-one-liner');
    const setStatus = (msg, color) => {
      if (!statusEl) return;
      statusEl.textContent = msg;
      statusEl.style.color = color || 'var(--text-tertiary)';
    };
    // One-line installer: SERVER_URL + token ride as leading env vars so the
    // piped `bash` process sees them (query-string vars would NOT reach the
    // script through `curl | bash`). Single command — no Docker, no pip.
    const renderCommands = (token, serverUrl) => {
      const origin = (serverUrl || location.origin).replace(/\/$/, '');
      if (oneLinerPre) {
        oneLinerPre.textContent =
          'curl -sSL "' + origin + '/agent/install.sh" \\\n' +
          '  | CYPHER65_SERVER_URL=' + origin + ' CYPHER65_AGENT_TOKEN=' + token + ' bash';
      }
      if (dockerPre) {
        dockerPre.textContent =
          'docker run -d --name cypher65-agent --network host \\\n' +
          '  -e CYPHER65_SERVER_URL=' + origin + ' \\n' +
          '  -e CYPHER65_AGENT_TOKEN=' + token + ' \\n' +
          '  -e CYPHER65_POLL_INTERVAL=30 \\n' +
          '  ghcr.io/0xjc65eth/cypher65-agent';
      }
    };
    const copy = async (text, label) => {
      try {
        await navigator.clipboard.writeText(text);
        setStatus('✓ ' + label + ' copied', 'var(--accent-green)');
      } catch (e) {
        setStatus('! copy failed — select manually', 'var(--accent-red)');
      }
    };

    document.getElementById('axe-agent-gen')?.addEventListener('click', async () => {
      setStatus('> minting token...');
      try {
        const r = await authFetch('/api/agent/token', { method: 'POST' });
        const data = await r.json();
        if (!r.ok || !data.token) {
          setStatus('✗ ' + (data.error || 'token mint failed (HTTP ' + r.status + ')'), 'var(--accent-red)');
          return;
        }
        if (tokenArea) tokenArea.value = data.token;
        renderCommands(data.token, data.server_url || '');
        if (tokenRow) tokenRow.style.display = 'block';
        setStatus('✓ token issued · tenant ' + (data.tenant_id || ''), 'var(--accent-green)');
      } catch (e) {
        setStatus('✗ network error', 'var(--accent-red)');
      }
    });
    document.getElementById('axe-agent-copy-token')?.addEventListener('click', () => {
      if (tokenArea && tokenArea.value) copy(tokenArea.value, 'token');
    });
    document.getElementById('axe-agent-copy-one')?.addEventListener('click', () => {
      if (oneLinerPre && oneLinerPre.textContent) copy(oneLinerPre.textContent, 'install command');
    });
    document.getElementById('axe-agent-copy-docker')?.addEventListener('click', () => {
      if (dockerPre && dockerPre.textContent) copy(dockerPre.textContent, 'docker command');
    });
    document.getElementById('axe-agent-hide-token')?.addEventListener('click', () => {
      if (tokenArea) tokenArea.value = '';
      if (tokenRow) tokenRow.style.display = 'none';
      setStatus('token hidden');
    });
  }

  // Shared device-add helper (used by the manual form + scan ADD buttons).
  // Returns true on success.
  async function addAxeDevice(ip, name) {
    if (!ip) return false;
    try {
      const r = await authFetch('/api/axe-fleet/devices', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ip_address: ip, name: name || '' })
      });
      const data = await r.json();
      return r.ok;
    } catch (e) {
      return false;
    }
  }
