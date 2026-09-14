  // ══════════════════════════════════════════════════════════════════════
  // Terminal / SSE — domínio extraído de `40-app-logic.js`
  // ══════════════════════════════════════════════════════════════════════
  // RFC 478 (Issue 529). Movimento MECÂNICO: nenhum nome, id de DOM, contrato
  // de fetch ou formato de payload mudou — as 752 linhas abaixo foram
  // recortadas verbatim. Cobre os três painéis: o terminal de eventos do LIVE
  // MINING (`_lm*`, `_initLmEventLogControls`), o log/timeline de eventos com o
  // error boundary global (`logMessage`, `window.onerror`, `renderTerminalEvents`
  // / `renderTimelineFeed` / `renderTimelineStats`) e o TERMINAL SOLO
  // interativo (`_soloTerm*`, `_termBindInput`, `_soloTermInit`, `_liveTermInit`).
  //
  // ⚠ POR QUE ESTE FRAGMENTO VEM ANTES DE `40-app-logic.js` — e não depois,
  // como 45-49. O `boot()` é CHAMADO no topo do IIFE, dentro do próprio
  // `40-app-logic.js` (linha 6388 pré-recorte). O corpo SÍNCRONO do `boot` roda,
  // portanto, durante a avaliação do fragmento 40 — antes de 45-49 existirem. E
  // ele toca este domínio de forma direta:
  //   · `_initLmEventLogControls()`               (boot, síncrono)
  //   · `_liveTermInit()`                         (boot, síncrono)
  //   · `logMessage('SYSTEM', 'WAR ROOM ONLINE')` (boot, síncrono)
  // `_initLmEventLogControls` termina em `_lmRenderStats()`, que lê o `const
  // _lmStats`; e `logMessage` faz `events.push(...)` sobre o `let events`. Se
  // este fragmento fosse posicionado DEPOIS do 40, esse estado estaria em TDZ
  // nesse instante → ReferenceError no boot. ANTES do 40, ele já está
  // inicializado quando o `boot` roda. Verificado: nenhuma linha de nível de
  // módulo aqui lê estado do `40-app-logic.js` (os 3 statements de topo só usam
  // `window`/`document` e declaram handlers que rodam depois).
  //
  // (Não é caso isolado: vale para todo domínio cujo estado seja lido por chamada
  // de nível de módulo do app-logic — ex.: o `renderSupportMethods()` do domínio
  // Wallet/Support, no PR 9 do RFC.)
  //
  // Estado que NÃO veio junto, de propósito:
  //   · `_lastSnapshot` — global compartilhado (poll/SSE escrevem; AXE Fleet e o
  //     próprio snapshot leem); ficou em `40-app-logic.js` até o PR 10
  //     (RFC 478 · Issue 561), quando foi com o resto do domínio de poll para o
  //     `39b-dashboard.js` — que também é avaliado ANTES deste fragmento.
  //   · `_ccLastFleet`/`_ccView`/`_ccHrSeries`/`_ccHrHist`/`_ccShareSeen` —
  //     estado do FLEET COMMAND CENTER (`48-fleet-cc.js`), que morava no meio do
  //     bloco de estado daqui. Ficou em `40-app-logic.js` porque o `boot()` chama
  //     `initFleetCommandCenterControls()` (que lê/escreve `_ccView`) de forma
  //     síncrona ANTES de o fragmento 48 ser avaliado — movê-lo para o 48 seria
  //     um ReferenceError.
  //
  // Statements de execução no topo: 3 — o error boundary global (`window.onerror`,
  // `unhandledrejection`) e o listener de `#clear-logs`. Consequência deliberada
  // de vir antes do 40: o error boundary passa a cobrir TAMBÉM a avaliação do
  // `40-app-logic.js` (no arquivo original ele só passava a existir na linha
  // 2625). É estritamente mais proteção, nunca menos.

  // ── Live Log ──
  let events = []; let renderedEventCount = 0;
  function logMessage(tag, msg, sev) {
    const now = new Date();
    const ts = String(now.getHours()).padStart(2,'0')+':'+String(now.getMinutes()).padStart(2,'0')+':'+String(now.getSeconds()).padStart(2,'0');
    const cls = `tag-${(sev || 'info').toLowerCase()}`;
    const line = `<div class="terminal__line"><span class="ts">[${ts}]</span><span class="tag ${cls}">${tag}</span>${escapeHtml(msg)}</div>`;
    events.push(line); renderedEventCount++;
    if (dom.terminal) {
      dom.terminal.insertAdjacentHTML('beforeend', line);
      while (renderedEventCount > 100) { const f = dom.terminal.querySelector('.terminal__line'); if (!f) break; f.remove(); renderedEventCount--; }
      dom.terminal.scrollTop = dom.terminal.scrollHeight;
    }
    if (dom.logEventsCount) dom.logEventsCount.textContent = `${renderedEventCount} events`;
  }

  // ── Global error boundary (Fase 1.2 · UI audit) ─────────────────────
  // The dashboard had no global safety net: a render exception or an
  // unhandled promise rejection died silently, leaving a frozen panel with
  // zero signal. These handlers catch both and surface them in the Live Log
  // (tag ERROR) instead of failing silently. Best-effort by design: the
  // handlers are wrapped so a logging failure can never recurse into itself.
  // Throttled so a repeating error (e.g. a broken poll payload) logs once per
  // window instead of spamming 1000 lines/min.
  const _EB_MAX_PER_MIN = 5;
  const _EB_WINDOW_MS = 60000;
  const _ebRecent = {};  // msgKey → { count, firstTs }

  // Pure: converts any thrown value / event into { msg, sev } for the log.
  // Mirrored in tests/test_app_js_core.js (formatClientErrorMirror).
  function formatClientError(err) {
    if (err == null) return { msg: 'unknown error', sev: 'WARN' };
    if (typeof err === 'string') return { msg: err.slice(0, 200), sev: 'WARN' };
    if (err instanceof Error) {
      return { msg: String(err.message || err).slice(0, 200), sev: 'WARN' };
    }
    // ErrorEvent ('error') carries message + filename/lineno; keep the file
    // short (basename:line) so the terminal line stays readable.
    if (typeof err === 'object' && err !== null) {
      if (err.reason != null && err.reason !== err) return formatClientError(err.reason);
      if (err.message) {
        let m = String(err.message);
        if (err.filename) {
          const base = String(err.filename).split('/').pop();
          m += ` (${base}:${err.lineno || '?'})`;
        }
        return { msg: m.slice(0, 200), sev: 'WARN' };
      }
      // Event object with no message/reason (e.g. bare PromiseRejectionEvent)
      // — a clean fallback beats logging "[object X]" garbage.
      return { msg: 'unhandled error (no message)', sev: 'WARN' };
    }
    try { return { msg: String(err).slice(0, 200), sev: 'WARN' }; }
    catch (e) { return { msg: 'unknown error', sev: 'WARN' }; }
  }

  function _ebThrottled(msg) {
    const now = Date.now();
    const key = String(msg).slice(0, 80);
    const hit = _ebRecent[key];
    if (hit && now - hit.firstTs < _EB_WINDOW_MS) {
      if (hit.count >= _EB_MAX_PER_MIN) return false;
      hit.count++;
    } else {
      _ebRecent[key] = { count: 1, firstTs: now };
    }
    // Keep the throttle map bounded on long-running dashboards.
    if (Object.keys(_ebRecent).length > 200) {
      for (const k of Object.keys(_ebRecent)) {
        if (now - _ebRecent[k].firstTs > _EB_WINDOW_MS) delete _ebRecent[k];
      }
    }
    return true;
  }

  function _surfaceClientError(source, err) {
    try {
      const { msg, sev } = formatClientError(err);
      const full = (source ? `[${source}] ` : '') + msg;
      if (_ebThrottled(full)) logMessage('ERROR', full, sev);
    } catch (e) { /* never let the boundary itself throw */ }
  }

  // Register once — errors that occur before this point (very early boot) are
  // not caught, which is acceptable: the boundary covers runtime failures.
  window.addEventListener('error', function (e) {
    // Only surface real JS runtime errors. The 'error' event ALSO fires for
    // resource-load failures (broken <script>/<img>/CSS or cross-origin
    // scripts), where e.target is the failing element and the message is
    // empty/'Script error.' — those aren't exceptions and would spam the
    // Live Log with noise. A real window error has e.target === window.
    if (e && e.target && e.target !== window) return;
    _surfaceClientError('window', e);
  });
  window.addEventListener('unhandledrejection', function (e) {
    _surfaceClientError('promise', e);
  });

  document.getElementById('clear-logs')?.addEventListener('click', () => {
    events.length = 0; renderedEventCount = 0;
    dom.terminal.innerHTML = '<div class="terminal__line ts-mute">cleared</div>';
    dom.logEventsCount.textContent = '0 events';
  });

  // ── Timeline ──
  const TIMELINE_MAX = 80; const timelineIdsRendered = new Set(); let timelineTotalRendered = 0;
  // ── Normalize timeline event: handle both {ts, type, message} and [ts, type, severity, message] formats ──
  function _normalizeTimelineEvent(e) {
    if (Array.isArray(e)) {
      // Format from backend: [ts, event_type, severity, message] or [ts, event_type, message]
      return { id: e[0] + '_' + String(Math.random()).slice(2, 8), ts: e[0], event_type: e[1] || 'EVENT', severity: e[2] || 'INFO', message: e.length > 3 ? e[3] : (e[2] || '') };
    }
    return e; // already an object
  }

  function renderTimelineFeed(list) {
    if (!dom.timelineFeed) return;
    if (!list || !list.length) return;
    // Normalize all events first (handle array format from backend)
    const normalized = list.map(_normalizeTimelineEvent);
    const ordered = normalized.slice().reverse();
    const newOnes = ordered.filter(e => !timelineIdsRendered.has(e.id));
    if (!newOnes.length) return;
    const rows = newOnes.map(ev => {
      const d = new Date((ev.ts || 0) * 1000);
      const ts = String(d.getHours()).padStart(2,'0')+':'+String(d.getMinutes()).padStart(2,'0')+':'+String(d.getSeconds()).padStart(2,'0');
      return `<div class="timeline-row tf-${escapeHtml((ev.severity||'INFO').toLowerCase())}" data-id="${escapeHtml(String(ev.id))}"><span class="tf-time">${ts}</span><span class="tf-type">${escapeHtml(ev.event_type||'EVENT')}</span><span class="tf-msg">${escapeHtml(ev.message||'')}</span></div>`;
    }).join('');
    if (timelineTotalRendered === 0) dom.timelineFeed.innerHTML = '';
    dom.timelineFeed.insertAdjacentHTML('beforeend', rows);
    newOnes.forEach(e => timelineIdsRendered.add(e.id)); timelineTotalRendered += newOnes.length;
    while (timelineTotalRendered > TIMELINE_MAX) { const f = dom.timelineFeed.querySelector('.timeline-row'); if (!f) break; f.remove(); timelineTotalRendered--; }
    dom.timelineFeed.scrollTop = dom.timelineFeed.scrollHeight;
  }

  // ── EVENT STREAM — mirror of timeline_last_n into the terminal panel ──
  function renderTerminalEvents(list) {
    if (!dom.terminalEventsList) return;
    if (!list || !list.length) {
      setHtmlIfChanged(dom.terminalEventsList, '<div class="terminal-empty">awaiting events from pool polling...</div>');
      if (dom.terminalEventCount) dom.terminalEventCount.textContent = '0';
      return;
    }
    const normalized = list.map(_normalizeTimelineEvent);
    const ordered = normalized.slice().reverse();
    const rows = ordered.slice(0, 60).map(ev => {
      const d = new Date((ev.ts || 0) * 1000);
      const ts = String(d.getHours()).padStart(2,'0')+':'+String(d.getMinutes()).padStart(2,'0')+':'+String(d.getSeconds()).padStart(2,'0');
      const sev = (ev.severity || 'INFO').toLowerCase();
      return `<div class="terminal-events-row"><span class="ts">[${ts}]</span><span class="tag tag-${sev}">${escapeHtml(ev.event_type || 'EVENT')}</span>${escapeHtml(ev.message || '')}</div>`;
    }).join('');
    setHtmlIfChanged(dom.terminalEventsList, rows);
    if (dom.terminalEventCount) dom.terminalEventCount.textContent = String(normalized.length);
  }

  // ── SHARE TIMELINE summary cards + badges ──
  // Pure aggregation (mirrored in tests/test_app_js_core.js): counts
  // SHARE_FOUND / BEST_DIFF_BUMP events inside the 1h / 24h windows from a
  // timeline event list. Used as a client-side fallback when the DB-derived
  // aggregates (event_stats.db_*) are absent — e.g. on the very first poll
  // or after a SQLite write failure. Returns numbers; 0 is a real count.
  function computeTimelineStats(list, nowSec) {
    const now = nowSec || Math.floor(Date.now() / 1000);
    const out = { shares1h: 0, shares24h: 0, bumps24h: 0 };
    if (!list || !list.length) return out;
    list.forEach(e => {
      if (!e) return;
      const ev = _normalizeTimelineEvent(e);
      const t = Number(ev.ts);
      if (!t || !isFinite(t)) return;
      const age = now - t;
      if (age < 0) return; // future ts (clock skew) never counts
      if (ev.event_type === 'SHARE_FOUND') {
        if (age <= 3600) out.shares1h++;
        if (age <= 86400) out.shares24h++;
      } else if (ev.event_type === 'BEST_DIFF_BUMP') {
        if (age <= 86400) out.bumps24h++;
      }
    });
    return out;
  }

  // Latest SHARE_FOUND ts from the timeline list (fallback for LAST SHARE
  // when the session-scoped last_submit_ts is 0 — e.g. right after a server
  // restart, where the DB still holds rows but the in-memory tracker is
  // freshly primed). Only events within the last 24h count, so an old share
  // never claims to be "last".
  function lastShareTsFromTimeline(list, nowSec) {
    const now = nowSec || Math.floor(Date.now() / 1000);
    let latest = 0;
    if (!list || !list.length) return 0;
    list.forEach(e => {
      if (!e) return;
      const ev = _normalizeTimelineEvent(e);
      const t = Number(ev.ts);
      if (!t || !isFinite(t)) return;
      if (ev.event_type !== 'SHARE_FOUND') return;
      const age = now - t;
      if (age < 0 || age > 86400) return;
      if (t > latest) latest = t;
    });
    return latest;
  }

  // Renders the 4 summary cards (LAST SHARE / 1H / 24H / BUMPS 24H) and the
  // 3 header badges from snap.event_stats. DB-derived window counts are
  // authoritative; client-side aggregation of the current timeline list is
  // the fallback. A 0 renders as "0" (a real count) — only a missing value
  // renders as the em-dash placeholder.
  function renderTimelineStats(snap) {
    const es = (snap && snap.event_stats) || {};
    const fb = computeTimelineStats(snap && snap.timeline_recent, Math.floor(Date.now() / 1000));
    const shares1h = es.db_shares_last_hour != null ? Number(es.db_shares_last_hour) : fb.shares1h;
    const shares24h = es.db_shares_last_day != null ? Number(es.db_shares_last_day) : fb.shares24h;
    const bumps24h = es.db_best_diffs_last_day != null ? Number(es.db_best_diffs_last_day) : fb.bumps24h;
    if (dom.tStatLastShare) {
      const lastTs = es.last_submit_ts || lastShareTsFromTimeline(snap && snap.timeline_recent, Math.floor(Date.now() / 1000));
      if (lastTs) {
        const d = new Date(Number(lastTs) * 1000);
        dom.tStatLastShare.textContent =
          String(d.getHours()).padStart(2, '0') + ':' +
          String(d.getMinutes()).padStart(2, '0') + ':' +
          String(d.getSeconds()).padStart(2, '0');
      } else {
        dom.tStatLastShare.textContent = '\u2014';
      }
    }
    if (dom.tStat1h) dom.tStat1h.textContent = String(shares1h);
    if (dom.tStat24h) dom.tStat24h.textContent = String(shares24h);
    if (dom.tStatBumps) dom.tStatBumps.textContent = String(bumps24h);
    if (dom.timelineSharesBadge) dom.timelineSharesBadge.textContent = String(es.session_share_count || 0);
    if (dom.timelineBumpsBadge) dom.timelineBumpsBadge.textContent = String(es.session_best_diff_bumps || 0) + ' best';
    if (dom.timelineRateBadge) {
      const rate = Number(es.rolling_shares_per_hour);
      dom.timelineRateBadge.textContent = (es.rolling_shares_per_hour != null && isFinite(rate))
        ? rate.toFixed(1) + '/h'
        : '\u2014/h';
    }
  }

  // ══════════════════════════════════════════════════════════════════════
  // CYPHER // LIVE MINING — Summary, Best Share, Event Log
  // ══════════════════════════════════════════════════════════════════════

  let _lmLoggedActive = false;
  let _lmBestShareEver = 0; let _lmBestShareWorker = ''; let _lmBestShareTime = '';
  // P0-6 audit: professional terminal — bounded ring buffer (never unbounded
  // DOM growth), user scroll lock (never yank the reader back down), pause /
  // filter / live stats. Pure helpers mirrored in tests/test_app_js_core.js.
  let _lmEventCount = 0; const _LM_EVENT_MAX = 200;
  let _lmPaused = false;
  let _lmFilter = 'all';
  let _lmUserScrolled = false;
  const _lmStats = { total: 0, shares: 0, err: 0 };

  // P0-6: event type → badge class (color-coded terminal). Mirrored in tests.
  function lmEventTypeClass(type) {
    const t = String(type || '').toUpperCase();
    if (t === 'SHARE') return 'tag-share';
    if (t === 'BEST') return 'tag-best';
    if (t === 'JOB') return 'tag-job';
    if (t === 'ERR' || t === 'ERROR') return 'tag-error';
    return 'tag-info';
  }
  // P0-6: does an event pass the current filter? Mirrored in tests.
  function lmFilterMatches(filter, type) {
    const f = String(filter || 'all').toLowerCase();
    if (!f || f === 'all') return true;
    const t = String(type || '').toUpperCase();
    if (f === 'err') return t === 'ERR' || t === 'ERROR';
    return t === f.toUpperCase();
  }
  // P0-6: is the user reading history (not pinned to the newest line)?
  // Mirrored in tests.
  function lmUserScrolled(scrollTop, scrollHeight, clientHeight) {
    return scrollHeight - scrollTop - clientHeight > 24;
  }
  function _lmEventLineHtml(type, msg, ts) {
    const cls = lmEventTypeClass(type);
    // The type label is escaped too (defense-in-depth — the classifier maps
    // known types, but an unexpected value must never become raw HTML).
    return `<div class="lm-event-log__line"><span class="ts">[${ts}]</span><span class="${cls}">${escapeHtml(String(type).toUpperCase())}</span> ${escapeHtml(msg)}</div>`;
  }
  function _lmRenderStats() {
    const set = (id, v) => { const el = document.getElementById(id); if (el) el.textContent = String(v); };
    set('lm-stat-total', _lmStats.total);
    set('lm-stat-shares', _lmStats.shares);
    set('lm-stat-err', _lmStats.err);
  }
  // P0-6: connection status dot — LIVE (green) when the last snapshot is
  // fresh, STALE (amber) when the poll recently failed/aged, DOWN (red)
  // when we're pre-first-poll. Called from the main render path. Uses the
  // server-computed network.stale flag (single source of truth) so client
  // clock skew never mislabels the state.
  function _lmSetConn(snap) {
    const dot = document.getElementById('lm-conn-dot');
    if (!dot) return;
    dot.classList.remove('is-stale', 'is-down');
    const ts = snap && snap.ts;
    if (!ts) {
      dot.classList.add('is-down');
      dot.title = 'waiting for first poll';
    } else if ((snap.network && snap.network.stale === true) ||
               (Math.floor(Date.now() / 1000) - Number(ts) > 150)) {
      dot.classList.add('is-stale');
      dot.title = 'stale — network data aged';
    } else {
      dot.title = 'live';
    }
  }
  function _lmApplyFilter() {
    const term = dom.lmEventLogTerminal;
    if (!term) return;
    const keep = term.querySelectorAll('.lm-event-log__line');
    keep.forEach(el => {
      const typeEl = el.querySelector('.tag-share, .tag-best, .tag-job, .tag-error, .tag-info');
      const type = typeEl ? (typeEl.textContent || '').trim() : '';
      el.style.display = lmFilterMatches(_lmFilter, type) ? '' : 'none';
    });
    _lmSyncScrollLock();
  }
  function _lmSyncScrollLock() {
    const term = dom.lmEventLogTerminal;
    const jump = document.getElementById('lm-event-log-jump');
    if (!term) return;
    _lmUserScrolled = lmUserScrolled(term.scrollTop, term.scrollHeight, term.clientHeight);
    if (jump) jump.hidden = !_lmUserScrolled;
  }
  function _lmJumpToBottom() {
    const term = dom.lmEventLogTerminal;
    if (!term) return;
    _lmUserScrolled = false;
    term.scrollTop = term.scrollHeight;
    const jump = document.getElementById('lm-event-log-jump');
    if (jump) jump.hidden = true;
  }
  function _lmAppendEvent(type, msg) {
    const term = dom.lmEventLogTerminal;
    if (!term) return;
    // Every appended line (events AND the pause-resume marker) counts toward
    // the ring buffer — otherwise the count drifts from the real DOM size.
    _lmEventCount++;
    const now = new Date();
    const pad = (n) => String(n).padStart(2, '0');
    const ms = String(now.getMilliseconds()).padStart(3, '0');
    const ts = `${pad(now.getHours())}:${pad(now.getMinutes())}:${pad(now.getSeconds())}.${ms}`;
    term.insertAdjacentHTML('beforeend', _lmEventLineHtml(type, msg, ts));
    while (_lmEventCount > _LM_EVENT_MAX) {
      const f = term.querySelector('.lm-event-log__line');
      if (!f) break;
      f.remove(); _lmEventCount--;
    }
    if (!_lmUserScrolled) term.scrollTop = term.scrollHeight;
    _lmRenderStats();
  }

  function _initLmEventLogControls() {
    const clearBtn = document.getElementById('lm-event-log-clear');
    if (clearBtn) clearBtn.addEventListener('click', () => {
      if (dom.lmEventLogTerminal) dom.lmEventLogTerminal.innerHTML = '<div class="lm-event-log__line ts-mute">> CLEARED</div>';
      _lmEventCount = 1;
      _lmStats.total = 0; _lmStats.shares = 0; _lmStats.err = 0;
      _lmRenderStats();
    });
    const pauseBtn = document.getElementById('lm-event-log-pause');
    if (pauseBtn) pauseBtn.addEventListener('click', () => {
      _lmPaused = !_lmPaused;
      pauseBtn.textContent = _lmPaused ? '▶ resume' : '⏸ pause';
      pauseBtn.classList.toggle('is-active', _lmPaused);
      pauseBtn.title = _lmPaused ? 'Resume the event stream' : 'Pause the event stream';
      if (!_lmPaused) {
        // Unpause marker so the operator knows where the stream restarted.
        _lmAppendEvent('JOB', 'stream resumed');
      }
    });
    const filtersEl = document.getElementById('lm-event-log-filters');
    if (filtersEl) {
      filtersEl.querySelectorAll('.chip--filter').forEach(chip => {
        chip.addEventListener('click', () => {
          filtersEl.querySelectorAll('.chip--filter').forEach(c => c.classList.remove('is-active'));
          chip.classList.add('is-active');
          _lmFilter = chip.getAttribute('data-lm-filter') || 'all';
          _lmApplyFilter();
        });
      });
    }
    const jumpBtn = document.getElementById('lm-event-log-jump');
    if (jumpBtn) jumpBtn.addEventListener('click', _lmJumpToBottom);
    const term = dom.lmEventLogTerminal;
    if (term) {
      term.addEventListener('scroll', _lmSyncScrollLock, { passive: true });
      term.addEventListener('wheel', _lmSyncScrollLock, { passive: true });
    }
    _lmRenderStats();
  }

  // ══════════════════════════════════════════════════════════════════════
  // SOLO MINING TERMINAL — interactive CLI
  // ══════════════════════════════════════════════════════════════════════

  const _soloTerm = {
    output: null, input: null, history: [], historyIdx: -1,
  };

  function _soloTermPrint(text, out) {
    out = out || _soloTerm.output;
    if (!out) return;
    const lines = String(text).split('\n');
    for (const line of lines) {
      const div = document.createElement('div');
      div.className = 'solo-term__line';
      div.textContent = line;
      out.appendChild(div);
    }
    out.scrollTop = out.scrollHeight;
  }

  function _soloTermPrintHTML(html, out) {
    out = out || _soloTerm.output;
    if (!out) return;
    const div = document.createElement('div');
    div.className = 'solo-term__line';
    div.innerHTML = html;
    out.appendChild(div);
    out.scrollTop = out.scrollHeight;
  }

  // Return the latest known snapshot, fetching only if not yet loaded.
  // Reuses the cached snapshot the dashboard already polls, so terminal
  // commands respond instantly instead of blocking on /api/snapshot's
  // external market-offers fetch (E2E terminal tests wait only 1s).
  async function _soloTermCachedSnapshot() {
    if (_lastSnapshot) return _lastSnapshot;
    const r = await fetch('/api/snapshot');
    const snap = await r.json();
    _lastSnapshot = snap;
    return snap;
  }

  // Shared terminal input binder — reuses _soloTermExecute for BOTH the
  // Solo Mining Advisor (#solo-term-input) and the Live Mining terminal
  // (#terminal-input). History navigation + Enter submission in one place.
  function _termBindInput(inputEl, outputEl) {
    if (!inputEl) return;
    inputEl.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') {
        const cmd = inputEl.value.trim();
        if (cmd) {
          _soloTerm.history.push(cmd);
          _soloTerm.historyIdx = _soloTerm.history.length;
          _soloTermExecute(cmd, outputEl);
          inputEl.value = '';
        }
      } else if (e.key === 'ArrowUp') {
        e.preventDefault();
        if (_soloTerm.historyIdx > 0) {
          _soloTerm.historyIdx--;
          inputEl.value = _soloTerm.history[_soloTerm.historyIdx];
        }
      } else if (e.key === 'ArrowDown') {
        e.preventDefault();
        if (_soloTerm.historyIdx < _soloTerm.history.length - 1) {
          _soloTerm.historyIdx++;
          inputEl.value = _soloTerm.history[_soloTerm.historyIdx];
        } else {
          _soloTerm.historyIdx = _soloTerm.history.length;
          inputEl.value = '';
        }
      }
    });
  }

  // Terminal prompt user: the connected wallet address (short form) when
  // available, falling back to a neutral 'miner' for anonymous sessions.
  function _soloTermUser() {
    var addr = window.BTC_ADDRESS || '';
    if (addr) return fmt.shortAddr(addr);
    return 'miner';
  }

  async function _soloTermExecute(cmd, out) {
    if (_soloTerm.loading) return;
    _soloTerm.loading = true;
    out = out || _soloTerm.output;

    // Echo command — prompt shows the connected wallet, never a hardcoded user
    _soloTermPrintHTML('<span class="c-green">' + escapeHtml(_soloTermUser()) + '@cypher</span>:<span class="c-blue">~/solo-mining</span>$ <span class="c-white">' + escapeHtml(cmd) + '</span>', out);

    const parts = cmd.split(/\s+/);
    const verb = (parts[0] || '').toLowerCase();

    if (verb === 'clear' || verb === 'cls') {
      out.innerHTML = '';
      _soloTermPrintHTML('<span class="c-muted">terminal cleared</span>', out);
      _soloTerm.loading = false;
      return;
    }

    if (verb === 'help' || verb === '--help' || verb === '-h') {
      _soloTermPrint('', out);
      _soloTermPrintHTML('<span class="c-amber">Available commands:</span>', out);
      _soloTermPrint('  help ................. Show available commands', out);
      _soloTermPrint('  status ............... Show system status', out);
      _soloTermPrint('  workers .............. Show connected workers and hashrate', out);
      _soloTermPrint('  price ................ Show current BTC price', out);
      _soloTermPrint('  network .............. Show current Bitcoin network data', out);
      _soloTermPrint('', out);
      _soloTermPrint('  calc --hashrate <value> --duration <h> [--difficulty <d>]', out);
      _soloTermPrint('       Calculate solo mining probabilities for a given hashrate', out);
      _soloTermPrint('', out);
      _soloTermPrint('  compare --budget <btc> --duration <h> --braiins <price> --mrr <price>', out);
      _soloTermPrint('          Compare Braiins vs MRR rental options', out);
      _soloTermPrint('', out);
      _soloTermPrint('  clear ................ Clear terminal output', out);
      _soloTerm.loading = false;
      return;
    }

    // ── status: system/worker state from the live snapshot ──
    if (verb === 'status') {
      _soloTermPrintHTML('<span class="c-muted">fetching system status...</span>', out);
      try {
        const snap = await _soloTermCachedSnapshot();
        const w = snap.worker || {};
        const net = snap.network || {};
        const pool = snap.pool || {};
        _soloTermPrint('', out);
        _soloTermPrintHTML('<span class="c-green">[OK] CYPHER65 WAR ROOM — SYSTEM STATUS</span>', out);
        // The war room is ONLINE whenever the snapshot has been fetched.
        _soloTermPrint('  system............ ' + (snap && snap.ts > 0 ? 'ONLINE' : 'OFFLINE'), out);
        _soloTermPrint('  worker............ ' + (w.name || 'N/A'), out);
        _soloTermPrint('  hashrate.......... ' + (w.hashrate ? fmt.hashrate(w.hashrate) : 'N/A'), out);
        _soloTermPrint('  best diff......... ' + (w.bestDifficulty ? fmt.diff(w.bestDifficulty) : 'N/A'), out);
        _soloTermPrint('  network diff...... ' + (net.difficulty ? fmt.diff(net.difficulty) : 'N/A'), out);
        _soloTermPrint('  height............ ' + (net.height ? '#' + net.height : 'N/A'), out);
        _soloTermPrint('  pool hashrate..... ' + (pool.hashrate ? fmt.hashrate(pool.hashrate) : 'N/A'), out);
      } catch (e) {
        _soloTermPrintHTML('<span class="c-red">[ERROR] ' + escapeHtml(e.message) + '</span>', out);
      }
      _soloTerm.loading = false;
      return;
    }

    // ── workers: connected worker list + total hashrate ──
    if (verb === 'workers') {
      _soloTermPrintHTML('<span class="c-muted">fetching workers...</span>', out);
      try {
        const snap = await _soloTermCachedSnapshot();
        const workers = snap.all_workers || [];
        const w = snap.worker || {};
        _soloTermPrint('', out);
        _soloTermPrintHTML('<span class="c-green">[OK] workers: ' + workers.length + ' connected</span>', out);
        workers.slice(0, 10).forEach((wr, i) => {
          const hr = wr.hashrate || wr.hashrate1m || 0;
          _soloTermPrint('  #' + (i+1) + ' ' + (wr.name || wr.worker || 'unknown') + ' .... HR ' + (hr ? fmt.hashrate(hr) : 'N/A'), out);
        });
        if (!workers.length) _soloTermPrint('  (no worker data yet)', out);
        _soloTermPrint('', out);
        _soloTermPrint('  total HR.......... ' + (w.hashrate ? fmt.hashrate(w.hashrate) : 'N/A'), out);
      } catch (e) {
        _soloTermPrintHTML('<span class="c-red">[ERROR] ' + escapeHtml(e.message) + '</span>', out);
      }
      _soloTerm.loading = false;
      return;
    }

    // ── price: current BTC price ──
    if (verb === 'price') {
      _soloTermPrintHTML('<span class="c-muted">fetching BTC price...</span>', out);
      try {
        const snap = await _soloTermCachedSnapshot();
        const btc = snap.btc_price || {};
        _soloTermPrint('', out);
        _soloTermPrintHTML('<span class="c-green">[OK] BTC price</span>', out);
        _soloTermPrint('  BTC/USD........... ' + (btc.usd ? '$' + Number(btc.usd).toLocaleString() : 'N/A'), out);
        _soloTermPrint('  BTC/BRL........... ' + (btc.brl ? 'R$' + Number(btc.brl).toLocaleString() : 'N/A'), out);
      } catch (e) {
        _soloTermPrintHTML('<span class="c-red">[ERROR] ' + escapeHtml(e.message) + '</span>', out);
      }
      _soloTerm.loading = false;
      return;
    }

    if (verb === 'network') {
      _soloTermPrintHTML('<span class="c-muted">fetching network data...</span>', out);
      try {
        const r = await fetch('/api/solo-mining/network');
        const data = await r.json();
        if (data.error) {
          _soloTermPrintHTML('<span class="c-red">[ERROR] ' + escapeHtml(data.error) + '</span>', out);
          _soloTerm.loading = false;
          return;
        }
        _soloTermPrint('', out);
        _soloTermPrintHTML('<span class="c-green">[OK] Network data fetched</span>', out);
        _soloTermPrint('  difficulty........ ' + (data.difficulty ? fmt.diff(data.difficulty) : 'UNAVAILABLE'), out);
        _soloTermPrint('  btc/usd........... ' + (data.btc_price_usd ? '$' + Number(data.btc_price_usd).toLocaleString() : 'UNAVAILABLE'), out);
        _soloTermPrint('  height............ ' + (data.height ? '#' + data.height : 'UNAVAILABLE'), out);
        _soloTermPrint('  source............ ' + (data.source || 'mempool.space'), out);
      } catch (e) {
        _soloTermPrintHTML('<span class="c-red">[ERROR] Failed to fetch network data: ' + escapeHtml(e.message) + '</span>', out);
      }
      _soloTerm.loading = false;
      return;
    }

    if (verb === 'calc') {
      let hashrate = null, duration = null, difficulty = null;
      for (let i = 1; i < parts.length; i++) {
        if (parts[i] === '--hashrate' && parts[i+1]) { hashrate = parts[i+1]; i++; }
        else if (parts[i] === '--duration' && parts[i+1]) { duration = parts[i+1].replace(/[^0-9.]/g, ''); i++; }
        else if (parts[i] === '--difficulty' && parts[i+1]) { difficulty = parts[i+1]; i++; }
      }
      if (!hashrate || !duration) {
        _soloTermPrintHTML('<span class="c-red">[ERROR] Missing required flags. Usage: calc --hashrate <value> --duration <h></span>', out);
        _soloTerm.loading = false;
        return;
      }
      const params = new URLSearchParams({ hashrate: hashrate, duration: duration, user: _soloTermUser() });
      if (difficulty) params.set('difficulty', difficulty);
      _soloTermPrintHTML('<span class="c-muted">running calculations...</span>', out);
      try {
        const r = await fetch('/api/solo-mining/calc?' + params.toString());
        const data = await r.json();
        if (data.error) {
          _soloTermPrintHTML('<span class="c-red">[ERROR] ' + escapeHtml(data.error) + '</span>', out);
          _soloTerm.loading = false;
          return;
        }
        _soloTermPrint('', out);
        const output = data.terminal_output || data.output || '';
        const lines = output.split('\n');
        for (const line of lines) {
          if (line.startsWith('[OK]')) _soloTermPrintHTML('<span class="c-green">' + escapeHtml(line) + '</span>', out);
          else if (line.startsWith('[WARN]')) _soloTermPrintHTML('<span class="c-amber">' + escapeHtml(line) + '</span>', out);
          else if (line.startsWith('[ERROR]')) _soloTermPrintHTML('<span class="c-red">' + escapeHtml(line) + '</span>', out);
          else _soloTermPrint(line, out);
        }
      } catch (e) {
        _soloTermPrintHTML('<span class="c-red">[ERROR] ' + escapeHtml(e.message) + '</span>', out);
      }
      _soloTerm.loading = false;
      return;
    }

    if (verb === 'compare') {
      let budget = null, duration = null, braiins = null, mrr = null, objective = 'EV';
      for (let i = 1; i < parts.length; i++) {
        if (parts[i] === '--budget' && parts[i+1]) { budget = parts[i+1]; i++; }
        else if (parts[i] === '--duration' && parts[i+1]) { duration = parts[i+1].replace(/[^0-9.]/g, ''); i++; }
        else if (parts[i] === '--braiins' && parts[i+1]) { braiins = parts[i+1]; i++; }
        else if (parts[i] === '--mrr' && parts[i+1]) { mrr = parts[i+1]; i++; }
        else if (parts[i] === '--objective' && parts[i+1]) { objective = parts[i+1].toUpperCase(); i++; }
      }
      if (!budget || !duration) {
        _soloTermPrintHTML('<span class="c-red">[ERROR] Missing required flags. Usage: compare --budget <btc> --duration <h> [--braiins <price>] [--mrr <price>]</span>', out);
        _soloTerm.loading = false;
        return;
      }
      const params = new URLSearchParams({ budget: budget, duration: duration, objective, auto_fetch: '1', user: _soloTermUser() });
      if (braiins) params.set('braiins_price', braiins);
      if (mrr) params.set('mrr_price', mrr);
      _soloTermPrintHTML('<span class="c-muted">comparing rental options...</span>', out);
      try {
        const r = await fetch('/api/solo-mining/compare?' + params.toString());
        const data = await r.json();
        if (data.error) {
          _soloTermPrintHTML('<span class="c-red">[ERROR] ' + escapeHtml(data.error) + '</span>', out);
          _soloTerm.loading = false;
          return;
        }
        _soloTermPrint('', out);
        const output = data.terminal_output || data.output || '';
        const lines = output.split('\n');
        for (const line of lines) {
          if (line.startsWith('[OK]')) _soloTermPrintHTML('<span class="c-green">' + escapeHtml(line) + '</span>', out);
          else if (line.startsWith('[WARN]')) _soloTermPrintHTML('<span class="c-amber">' + escapeHtml(line) + '</span>', out);
          else if (line.startsWith('[ERROR]')) _soloTermPrintHTML('<span class="c-red">' + escapeHtml(line) + '</span>', out);
          else _soloTermPrint(line, out);
        }
      } catch (e) {
        _soloTermPrintHTML('<span class="c-red">[ERROR] ' + escapeHtml(e.message) + '</span>', out);
      }
      _soloTerm.loading = false;
      return;
    }

    _soloTermPrintHTML('<span class="c-red">[ERROR] Unknown command: ' + escapeHtml(verb) + '. Type help for available commands.</span>', out);
    _soloTerm.loading = false;
  }

  function _soloTermInit() {
    _soloTerm.output = document.getElementById('solo-term-output');
    _soloTerm.input = document.getElementById('solo-term-input');
    if (!_soloTerm.input) return;

    _termBindInput(_soloTerm.input, _soloTerm.output);

    // Keep focus on input when clicking anywhere in the terminal
    const term = document.getElementById('solo-term');
    if (term) {
      term.addEventListener('click', () => _soloTerm.input && _soloTerm.input.focus());
    }

    // Clear button
    document.getElementById('solo-term-clear')?.addEventListener('click', () => {
      if (_soloTerm.output) _soloTerm.output.innerHTML = '';
      _soloTermPrintHTML('<span class="c-muted">terminal cleared — type help for commands</span>', _soloTerm.output);
    });

    // Help button
    document.getElementById('solo-term-help')?.addEventListener('click', () => {
      _soloTermExecute('help', _soloTerm.output);
    });

    // Welcome message
    _soloTermPrintHTML('<span class="c-muted">CYPHER SOLO MINING ADVISOR v1.0</span>', _soloTerm.output);
    _soloTermPrintHTML('<span class="c-muted">Type </span><span class="c-green">help</span><span class="c-muted"> for available commands.</span>', _soloTerm.output);
    _soloTermPrintHTML('<span class="c-muted">Examples:</span>', _soloTerm.output);
    _soloTermPrintHTML('<span class="c-muted">  calc --hashrate 225TH --duration 24h</span>', _soloTerm.output);
    _soloTermPrintHTML('<span class="c-muted">  compare --budget 0.01 --duration 24 --braiins 0.002 --mrr 0.0015</span>', _soloTerm.output);
    _soloTermPrintHTML('<span class="c-muted">  network</span>', _soloTerm.output);
    _soloTermPrint('', _soloTerm.output);

    // Focus input
    _soloTerm.input.focus();
  }

  // ── LIVE MINING TERMINAL (#terminal-input) ──────────────────────────
  // Binds the Live Terminal pane to the SAME command engine used by the
  // Solo Mining Advisor (_soloTermExecute). Previously #terminal-input had
  // no Enter keydown handler — only a .focus() call — so the E2E terminal
  // tests could never submit commands. Now help/status/workers/price/clear
  // all work from the Live Mining terminal. (Fase 5 · terminal unification)
  function _liveTermInit() {
    const output = document.getElementById('terminal-body');
    const input = document.getElementById('terminal-input');
    if (!input || !output) return;

    _termBindInput(input, output);

    // Keep focus on input when clicking anywhere in the terminal pane
    const panel = document.getElementById('terminal-panel');
    if (panel) {
      panel.addEventListener('click', () => input.focus());
    }

    // Clear button
    document.getElementById('terminal-clear')?.addEventListener('click', () => {
      output.innerHTML = '';
      _soloTermPrintHTML('<span class="c-muted">terminal cleared</span>', output);
    });

    // Welcome message
    _soloTermPrintHTML('<span class="c-muted">CYPHER65 WAR ROOM TERMINAL — type </span><span class="c-green">help</span><span class="c-muted"> for available commands.</span>', output);
  }
