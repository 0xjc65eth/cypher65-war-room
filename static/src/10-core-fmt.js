  // ── formatters ────────────────────────────────────────────────────────
  // Issue #490: `isFinite(...)` (global) coage — `isFinite(null)`,
  // `isFinite('')` e `isFinite(' ')` são `true`. Só número real ou string
  // numérica não-vazia é valor; o resto é dado ausente (em-dash). Imports de
  // API devolvem `null` e a normalização do backend usa `''` para "sem dado".
  function _finiteNum(v) {
    if (typeof v === 'number') return isFinite(v) ? v : null;
    if (typeof v === 'string') {
      const t = v.trim();
      if (t === '') return null;
      const n = Number(t);
      return isFinite(n) ? n : null;
    }
    return null;
  }

  const fmt = {
    hashrate(h) {
      if (!h && h !== 0) return '\u2014';
      const v = Number(h);
      const units = ['H/s', 'kH/s', 'MH/s', 'GH/s', 'TH/s', 'PH/s', 'EH/s'];
      let i = 0; let x = v;
      while (x >= 1000 && i < units.length - 1) { x /= 1000; i++; }
      return `${x.toFixed(x >= 100 ? 1 : 2)} ${units[i]}`;
    },
    diff(s) {
      if (!s && s !== 0) return '\u2014';
      if (typeof s === 'number') return fmt._diffFromNum(s);
      const str = String(s).trim();
      const m = str.match(/^([\d.,]+)\s*([a-zA-Z]*)$/);
      if (!m) return str;
      const num = parseFloat(m[1].replace(',', '.'));
      const suf = (m[2] || '').toUpperCase();
      const multMap = { '': 1, K: 1e3, M: 1e6, G: 1e9, T: 1e12, P: 1e15, E: 1e18 };
      return fmt._diffFromNum(num * (multMap[suf] || 1));
    },
    _diffFromNum(v) {
      if (!isFinite(v) || v === 0) return '0';
      v = Math.abs(v);
      const units = ['', 'K', 'M', 'G', 'T', 'P', 'E'];
      let i = 0; let x = v;
      while (x >= 1000 && i < units.length - 1) { x /= 1000; i++; }
      return `${x.toFixed(x >= 100 ? 0 : 2)} ${units[i]}`.trim();
    },
    uptime(s) {
      if (!s && s !== 0) return '\u2014';
      // The pool API can return the literal string 'N/A' — guard non-numeric
      // values so we render a clean em-dash instead of NaN.
      if (!isFinite(Number(s))) return '\u2014';
      s = Math.floor(Number(s));
      if (s < 60) return `${s}s`;
      const d = Math.floor(s / 86400), h = Math.floor((s % 86400) / 3600),
            m = Math.floor((s % 3600) / 60);
      const parts = [];
      if (d) parts.push(`${d}d`);
      if (h) parts.push(`${h}h`);
      if (m && !d) parts.push(`${m}m`);
      return parts.join(' ') || '0m';
    },
    age(ts) {
      if (!ts) return '\u2014';
      const d = Math.max(0, Math.floor((Date.now() / 1000) - Number(ts)));
      if (d < 60) return `${d}s ago`;
      if (d < 3600) return `${Math.floor(d / 60)}m ago`;
      // Issue #490: era `/ 86400` — toda idade entre 1h e 24h renderizava
      // "0h ago" no dashboard (último bloco, last share, eventos, alertas).
      if (d < 86400) return `${Math.floor(d / 3600)}h ago`;
      return `${Math.floor(d / 86400)}d ago`;
    },
    shortAddr(a) {
      if (!a) return '';
      if (a.length <= 16) return a;
      return `${a.slice(0, 10)}\u2026${a.slice(-6)}`;
    },
    chunkAddr(a) {
      if (!a) return '';
      var prefix = '';
      var rest = a;
      if (a.indexOf('bc1') === 0) { prefix = 'bc1'; rest = a.slice(3); }
      else if (a.indexOf('1') === 0 || a.indexOf('3') === 0) { prefix = a[0]; rest = a.slice(1); }
      var chunks = [];
      for (var i = 0; i < rest.length; i += 4) {
        chunks.push(rest.slice(i, i + 4));
      }
      return prefix + ' ' + chunks.join(' ');
    },
    shortAddrChunk(a) {
      if (!a) return '';
      if (a.length <= 20) return fmt.chunkAddr(a);
      return a.slice(0, 6) + '...' + a.slice(-4);
    },
    // Issue #490: dado ausente não é zero — null/undefined/''/NaN/' ' viram
    // em-dash; um zero real continua sendo `0.00%`.
    pct(n) { const v = _finiteNum(n); return v === null ? '\u2014' : `${v.toFixed(2)}%`; },
    usd(n) { if (!n) return '\u2014'; return `$${Number(n).toLocaleString('en-US', { maximumFractionDigits: 0 })}`; },
    // Shared numeric guard (Fase 5): telemetry fields may hold the literal
    // string "NOT AVAILABLE" after backend normalization — only real finite
    // numbers are treated as values.
    num(v) { return typeof v === 'number' && isFinite(v); },
    expectedBlock(workerHr, networkDiff) {
      if (!workerHr || !networkDiff) return null;
      const secs = (networkDiff * Math.pow(2, 32)) / workerHr * 65536;
      return secs;
    },
    secsToHuman(s) {
      // Issue #490: o guard antigo (`isFinite(s)`) aceitava null e strings
      // em branco e então estourava em `null.toFixed` — `_finiteNum` recusa
      // null/undefined/''/' '/NaN/'N/A' com em-dash e devolve número de fato.
      const v = _finiteNum(s);
      if (v === null) return '\u2014';
      s = v;
      if (s < 60) return `${s.toFixed(1)}s`;
      const min = s / 60; if (min < 60) return `${min.toFixed(1)}m`;
      const h = min / 60; if (h < 24) return `${h.toFixed(1)}h`;
      const d = h / 24; if (d < 365) return `${d.toFixed(1)}d`;
      return `${(d / 365).toFixed(2)}y`;
    },
  };

  // ── BTC upgrade helpers (Issue 249) ────────────────────────────────────
  // Pure functions mirrored in tests/test_app_js_core.js — keep in sync.
  function fmtSats(n) {
    n = Math.max(0, Math.round(Number(n) || 0));
    return n.toLocaleString('en-US') + ' sats';
  }
  function countdownLabel(ms) {
    if (!isFinite(Number(ms)) || Number(ms) <= 0) return '00:00';
    const s = Math.floor(Number(ms) / 1000);
    const m = Math.floor(s / 60); const r = s % 60;
    return (m < 10 ? '0' + m : String(m)) + ':' + (r < 10 ? '0' + r : String(r));
  }
  // BOLT11 amount (msat → sats): lnbc<number><multiplier>1... where the
  // multiplier (m/u/n/p) scales the BTC figure to millisatoshis. Requiring
  // the mandatory '1' HRP separator avoids misreading amountless invoices
  // (lnbc1... — wallet decides the value) as '1 BTC'. Returns null when the
  // amount can't be parsed (amountless or malformed).
  function bolt11AmountSats(invoice) {
    if (!invoice) return null;
    const m = String(invoice).match(/^(?:lnbc|lntb)(?:(\d+)([munp]?))?1/i);
    if (m && m[1] !== undefined) {
      const mult = { '': 1e11, m: 1e8, u: 1e5, n: 1e2, p: 1e-1 }[m[2] || ''];
      if (mult !== undefined) {
        return Math.round((parseInt(m[1], 10) * mult) / 1000);
      }
    }
    return null;
  }

