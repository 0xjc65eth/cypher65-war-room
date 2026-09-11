/* ════════════════════════════════════════════════════════════════════════
   CYPHER65 · WAR ROOM · client logic
   ────────────────────────────────────────────────────────────────────────
   ⚠️  ARQUIVO GERADO — NÃO EDITE À MÃO.

   A fonte vive em `static/src/*.js` e este arquivo é montado por:
       node scripts/build_app_js.cjs

   O CI roda `--check` e BLOQUEIA O MERGE se este arquivo divergir das
   fontes (RFC 478 · Opção A · Issue #489). Edite o fragmento, não o build.
   ════════════════════════════════════════════════════════════════════════ */

(() => {
  'use strict';

  // ── constants ─────────────────────────────────────────────────────────
  const POLL_MS = window.POLL_INTERVAL_MS || 15000;
  let nextPollAt = Date.now() + POLL_MS;

