/**
 * CYPHER65 // HERMES INTELLIGENCE — Chat Client
 * =============================================
 * Session-isolated conversational interface for Hermes Cognitive Core.
 */

(function () {
  'use strict';

  // ── State ──────────────────────────────────────────────────────────
  let sessionId = localStorage.getItem('hermes_session_id') || '';
  let messageHistory = [];
  let isWaiting = false;

  // ── DOM refs ───────────────────────────────────────────────────────
  const messagesEl = document.getElementById('hermes-messages');
  const inputEl = document.getElementById('hermes-input');
  const sendBtn = document.getElementById('hermes-send');
  const clearBtn = document.getElementById('hermes-clear');
  const newSessionBtn = document.getElementById('hermes-new-session');

  // Context panel refs
  const ctxSession = document.getElementById('ctx-session');
  const ctxWallet = document.getElementById('ctx-wallet');
  const ctxIntent = document.getElementById('ctx-intent');
  const ctxDataSource = document.getElementById('ctx-data-source');
  const ctxHashrate = document.getElementById('ctx-hashrate');
  const ctxDifficulty = document.getElementById('ctx-difficulty');
  const ctxBtcPrice = document.getElementById('ctx-btc-price');
  const ctxAgents = document.getElementById('ctx-agents');
  const ctxTurns = document.getElementById('ctx-turns');
  const sessionBadge = document.getElementById('hermes-session-badge');
  const dataBadge = document.getElementById('hermes-data-badge');

  // ── Poll for real-time context updates ─────────────────────────────
  async function refreshContext() {
    try {
      const resp = await fetch('/api/snapshot');
      const snap = await resp.json();
      const worker = snap.worker || {};
      const network = snap.network || {};
      const btc = snap.btc_price || {};

      if (worker.hashrate) {
        const hrThs = (worker.hashrate / 1e12).toFixed(2);
        ctxHashrate.textContent = hrThs + ' TH/s';
      }
      if (network.difficulty) {
        ctxDifficulty.textContent = (network.difficulty / 1e12).toFixed(1) + ' T';
      }
      if (btc.usd) {
        ctxBtcPrice.textContent = '$' + Number(btc.usd).toLocaleString();
        dataBadge.textContent = '🟢 REAL DATA';
        dataBadge.style.color = '#00ff9f';
      } else {
        dataBadge.textContent = '⚪ NO DATA';
        dataBadge.style.color = '#888';
      }

      // Wallet
      const addr = snap.address || '';
      ctxWallet.textContent = addr ? addr.slice(0, 10) + '…' + addr.slice(-6) : '—';

      // Agents
      try {
        const agentResp = await fetch('/api/hermes/agents', {
          headers: { 'X-API-Key': sessionStorage.getItem('hermes_api_key') || '' }
        });
        if (agentResp.ok) {
          const data = await agentResp.json();
          ctxAgents.textContent = (data.agents || []).join(', ') || '—';
        }
      } catch (e) { /* agent list optional */ }
    } catch (e) {
      // Context refresh is best-effort
    }
  }

  // ── Send message ───────────────────────────────────────────────────
  async function sendMessage(message) {
    if (isWaiting || !message.trim()) return;
    isWaiting = true;
    sendBtn.disabled = true;

    // Show user message
    appendMessage('user', message);
    inputEl.value = '';
    autoResize(inputEl);

    // Show typing indicator
    const typingEl = appendMessage('assistant', '<span class="hermes-typing">◈ thinking<span class="hermes-typing__dots">...</span></span>', true);

    try {
      const apiKey = sessionStorage.getItem('hermes_api_key') || '';
      const resp = await fetch('/api/hermes/chat', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-API-Key': apiKey,
        },
        body: JSON.stringify({
          message: message,
          session_id: sessionId,
        }),
      });

      // Remove typing indicator
      if (typingEl) typingEl.remove();

      if (resp.status === 401) {
        appendMessage('system', '🔒 Authentication required. Set your API key in session storage: <code>sessionStorage.setItem("hermes_api_key", "your-key")</code>');
        isWaiting = false;
        sendBtn.disabled = false;
        return;
      }

      if (!resp.ok) {
        const err = await resp.json().catch(() => ({ error: 'Unknown error' }));
        appendMessage('system', '⚠ ' + (err.error || 'Request failed'));
        isWaiting = false;
        sendBtn.disabled = false;
        return;
      }

      const data = await resp.json();

      // Persist session ID
      if (data.session_id && data.session_id !== sessionId) {
        sessionId = data.session_id;
        localStorage.setItem('hermes_session_id', sessionId);
        sessionBadge.textContent = 'SESSION ' + sessionId.slice(0, 8);
        ctxSession.textContent = sessionId.slice(0, 8) + '…';
      }

      // Update context
      ctxIntent.textContent = data.intent || '—';
      ctxTurns.textContent = (data.turn_number || '—');

      // Show response
      const responseText = data.response || data.output || 'No response';
      appendMessage('assistant', formatResponse(responseText));

      // Show analysis if available
      if (data.analysis && data.analysis.hashrate_ths !== undefined) {
        const a = data.analysis;
        let analysisHtml = '<div class="hermes-analysis">';
        analysisHtml += '<div class="hermes-analysis__title">📊 Analysis</div>';
        analysisHtml += '<table class="hermes-table">';
        if (a.hashrate_ths) analysisHtml += `<tr><td>Hashrate</td><td>${a.hashrate_ths} TH/s</td></tr>`;
        if (a.status_display) analysisHtml += `<tr><td>Status</td><td>${a.status_display}</td></tr>`;
        if (a.best_difficulty) analysisHtml += `<tr><td>Best Diff</td><td>${a.best_difficulty}</td></tr>`;
        if (a.worker_count !== undefined) analysisHtml += `<tr><td>Workers</td><td>${a.worker_count}</td></tr>`;
        if (a.last_share_age) analysisHtml += `<tr><td>Last Share</td><td>${a.last_share_age}</td></tr>`;
        if (a.data_source) analysisHtml += `<tr><td>Data Source</td><td>${a.data_source}</td></tr>`;
        analysisHtml += '</table></div>';
        appendMessage('assistant', analysisHtml);
      }

      if (data.probability) {
        const p = data.probability;
        let probHtml = '<div class="hermes-analysis">';
        probHtml += '<div class="hermes-analysis__title">🎲 Probability</div>';
        probHtml += '<table class="hermes-table">';
        if (p.probability_at_least_one !== undefined) {
          probHtml += `<tr><td>P(≥1 block)</td><td>${(p.probability_at_least_one * 100).toFixed(6)}%</td></tr>`;
        }
        if (p.expected_time_to_block_human) {
          probHtml += `<tr><td>Expected Time</td><td>${p.expected_time_to_block_human}</td></tr>`;
        }
        probHtml += '</table></div>';
        appendMessage('assistant', probHtml);
      }

    } catch (e) {
      if (typingEl) typingEl.remove();
      appendMessage('system', '⚠ Connection error: ' + e.message);
    }

    isWaiting = false;
    sendBtn.disabled = false;
    inputEl.focus();
    refreshContext();
  }

  // ── Format response ────────────────────────────────────────────────
  function formatResponse(text) {
    if (!text) return '';
    // Escape HTML
    let html = text
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;');
    // Bold: **text**
    html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
    // Newlines
    html = html.replace(/\n/g, '<br>');
    return html;
  }

  // ── Append message to chat ─────────────────────────────────────────
  function appendMessage(role, textHtml, isTemporary) {
    const div = document.createElement('div');
    div.className = 'hermes-msg hermes-msg--' + role;
    if (isTemporary) div.classList.add('hermes-msg--temporary');

    const roleEl = document.createElement('div');
    roleEl.className = 'hermes-msg__role';
    roleEl.textContent = role === 'user' ? 'YOU' : role === 'system' ? '◈ SYSTEM' : '◈ HERMES';

    const textEl = document.createElement('div');
    textEl.className = 'hermes-msg__text';
    textEl.innerHTML = textHtml;

    div.appendChild(roleEl);
    div.appendChild(textEl);
    messagesEl.appendChild(div);
    messagesEl.scrollTop = messagesEl.scrollHeight;
    return div;
  }

  // ── Auto-resize textarea ───────────────────────────────────────────
  function autoResize(el) {
    el.style.height = 'auto';
    el.style.height = Math.min(el.scrollHeight, 150) + 'px';
  }

  // ── Clear conversation ─────────────────────────────────────────────
  function clearConversation() {
    // Keep system welcome message, remove others
    const msgs = messagesEl.querySelectorAll('.hermes-msg');
    for (let i = 1; i < msgs.length; i++) {
      msgs[i].remove();
    }
    ctxIntent.textContent = '—';
    ctxTurns.textContent = '0';
  }

  // ── New session ────────────────────────────────────────────────────
  function newSession() {
    sessionId = '';
    localStorage.removeItem('hermes_session_id');
    sessionBadge.textContent = 'SESSION —';
    ctxSession.textContent = '—';
    inputEl.value = '';
    inputEl.focus();
    // Reload to get fresh welcome
    location.reload();
  }

  // ── Event listeners ────────────────────────────────────────────────
  sendBtn.addEventListener('click', () => sendMessage(inputEl.value));

  inputEl.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendMessage(inputEl.value);
    }
  });

  inputEl.addEventListener('input', () => autoResize(inputEl));

  clearBtn.addEventListener('click', clearConversation);
  newSessionBtn.addEventListener('click', newSession);

  // Suggestion chips
  document.addEventListener('click', (e) => {
    const chip = e.target.closest('.hermes-chip');
    if (chip && chip.dataset.prompt) {
      inputEl.value = chip.dataset.prompt;
      sendMessage(chip.dataset.prompt);
    }
  });

  // ── Init ───────────────────────────────────────────────────────────
  function init() {
    if (sessionId) {
      sessionBadge.textContent = 'SESSION ' + sessionId.slice(0, 8);
      ctxSession.textContent = sessionId.slice(0, 8) + '…';
    }
    refreshContext();
    setInterval(refreshContext, 30000); // Refresh context every 30s
    inputEl.focus();
  }

  init();

})();
