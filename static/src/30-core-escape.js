// ── escape HTML ───────────────────────────────────────────────────────
  function escapeHtml(s) { return String(s).replace(/[&<>"']/g, c => ({ '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;' }[c])); }

  // ── Rentals provider auth state (Issue #152) ────────────────────────
  // A CONFIGURED-but-rejected key (401/403, or MRR's classic 'Not
  // Authenticated - Invalid Key - Bad Nonce.') is a CREDENTIAL problem, not
  // a missing-credential state and not a concurrency bug. These pure
  // helpers classify the rejection and build the FIX guidance per provider;
  // mirrored in tests/test_app_js_core.js.
  function rentalsAuthRejected(errMsg, authRejected) {
    if (authRejected) return true;
    return /rejected|401|403|unauthor|forbidden|bad nonce|not authenticated|invalid key/i.test(String(errMsg || ''));
  }
  function rentalsAuthGuide(provider, errMsg) {
    const safe = escapeHtml(String(errMsg || ''));
    if (provider === 'contracts') {
      return 'A chave Braiins está configurada, mas a API a rejeitou: ' + safe +
        '. Gere um novo owner token em hashpower.braiins.com e atualize no Settings (⚙).';
    }
    return 'A chave MRR está configurada, mas a API a rejeitou: ' + safe +
      '. Causa provável: credencial inválida/desatualizada (ou tracker de nonce da chave preso) ' +
      '— NÃO é bug de concorrência. Regenerar a API key + secret em miningrigrentals.com ' +
      '→ My Account → API Access e atualizar no Settings (⚙).';
  }
  // Rentals payload freshness (Issue #187): a payload built by OLD server
  // code (no version stamp) cannot PROVE the account is empty — it may
  // predate the missing-key guard. Returns a LEVEL: 0 fresh · 1 age-stale
  // (data older than the panel's refresh cadence → soft 'dados
  // desatualizados' + reload) · 2 old-code (no version stamp → credential
  // hint, the case that used to render the misleading 'No contracts rentals
  // on this account'). Only level 2 claims the config may be missing; level 1
  // never lies about credentials on an idle-but-open tab. Pure helper
  // mirrored in tests/test_app_js_core.js.
  const RENTALS_PAYLOAD_VERSION = 2;
  const RENTALS_STALE_MAX_AGE_S = 300;  // panel re-fetches every 15s — 5min = not trustworthy
  function rentalsPayloadStale(payload, nowSec) {
    const p = payload || {};
    const version = Number(p.rentals_payload_version) || 0;
    if (version < RENTALS_PAYLOAD_VERSION) return 2;
    // Sentinel policy (Issue #203): a missing/epoch stamp must never fabricate
    // age (now - 0 → huge → false 'stale'). No stamp → unknown freshness → 0,
    // so valid data is never hidden by an absent field.
    const upd = Number(p.updated_at);
    if (!(upd > 0)) return 0;
    const age = (nowSec || Math.floor(Date.now() / 1000)) - upd;
    return age > RENTALS_STALE_MAX_AGE_S ? 1 : 0;
  }
  // Rentals count surface (Issue #200): "X de N" when the paginated fetch
  // hit the rate-budget safety cap (truncated) — never show a partial count
  // as if it were the whole account. Pure helper — mirrored in
  // tests/test_app_js_core.js. Returns {text, title}; text null = no truncation.
  function rentalsCountSurface(rendered, total) {
    const r = Number(rendered);
    const t = Number(total);
    if (isFinite(r) && isFinite(t) && t > 0 && r < t) {
      return {
        text: r + ' de ' + t,
        title: 'exibindo ' + r + ' de ' + t + ' rentals (limite de segurança do fetch)',
      };
    }
    return { text: null, title: '' };
  }

