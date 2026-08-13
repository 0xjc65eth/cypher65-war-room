#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════════
# check_frontend.sh — Frontend Quality Pipeline (combined check)
#
# Roda num único pipeline todos os checks de frontend do dashboard:
#   1. check:dom       — guard estático: ids duplicados + XSS innerHTML
#   2. test:dom-guards — self-test do próprio guard (casos adversários)
#   3. JS core         — node --check + tests/test_app_js_core.js
#   4. audit_ui --all  — auditoria visual (console/overflow/truncamento/
#                        skeletons) em desktop + mobile
#
# O audit visual exige o servidor no ar: o script boota o Flask localmente
# (porta 8765), espera o healthz e derruba ao final. Se AUDIT_URL estiver
# definida, usa o servidor externo em vez de bootar.
#
# Uso:
#   bash scripts/check_frontend.sh              # pipeline completo
#   AUDIT_URL=http://host:8765 bash scripts/check_frontend.sh
#
# Exit codes:
#   0 — todos os checks passaram
#   1 — algum check falhou
#   2 — erro de ambiente (servidor não subiu, deps faltando)
# ═══════════════════════════════════════════════════════════════════════
set -u
cd "$(dirname "$0")/.." || exit 2

RED=$'\033[31m'; GREEN=$'\033[32m'; YELLOW=$'\033[33m'; BOLD=$'\033[1m'; NC=$'\033[0m'
PASS="${GREEN}✅${NC}"; FAIL="${RED}❌${NC}"; WARN="${YELLOW}⚠${NC}"

failures=0

step() { echo; echo "${BOLD}── $1${NC}"; }

# ── Pré-requisitos ───────────────────────────────────────────────────────
command -v node >/dev/null 2>&1 || { echo "${FAIL} node não encontrado"; exit 2; }
[ -d node_modules ] || { echo "${WARN} node_modules ausente — npm install primeiro"; }

# ── 1. Guard estático DOM ────────────────────────────────────────────────
step "1/4 · Guard DOM estático (check:dom)"
if node scripts/check-dom-regression.cjs; then echo "${PASS} check:dom"; else echo "${FAIL} check:dom"; failures=1; fi

# ── 2. Self-test do guard ────────────────────────────────────────────────
step "2/4 · Self-test do guard (test:dom-guards)"
if node tests/test_dom_guards.js; then echo "${PASS} test:dom-guards"; else echo "${FAIL} test:dom-guards"; failures=1; fi

# ── 3. JS core ───────────────────────────────────────────────────────────
step "3/4 · JS syntax + core tests"
if node --check static/app.js && node tests/test_app_js_core.js; then
  echo "${PASS} JS core"
else
  echo "${FAIL} JS core"; failures=1
fi

# ── 4. Auditoria visual (boota o servidor se necessário) ────────────────
step "4/4 · Auditoria visual (audit_ui --all)"
SERVER_PID=""
if [ -z "${AUDIT_URL:-}" ]; then
  echo "  bootando Flask em http://127.0.0.1:8765 ..."
  pkill -f 'python app.py' 2>/dev/null || true
  sleep 1
  RATE_LIMIT_PER_MINUTE=10000 nohup python app.py &> /tmp/c65_frontend_check.log &
  SERVER_PID=$!
  ready=0
  for i in $(seq 1 60); do
    if curl -s http://127.0.0.1:8765/api/healthz >/dev/null 2>&1; then ready=1; break; fi
    sleep 1
  done
  if [ "$ready" != "1" ]; then
    echo "${FAIL} servidor não subiu em 60s (ver /tmp/c65_frontend_check.log)"; exit 2
  fi
  echo "  servidor pronto (${GREEN}healthz OK${NC})"
else
  echo "  usando servidor externo: ${AUDIT_URL}"
fi

if node scripts/audit_ui.cjs --all; then
  echo "${PASS} audit_ui --all"
else
  echo "${FAIL} audit_ui --all"; failures=1
fi

# ── Cleanup ──────────────────────────────────────────────────────────────
if [ -n "$SERVER_PID" ]; then kill "$SERVER_PID" 2>/dev/null || true; fi

echo
if [ "$failures" = "0" ]; then
  echo "${GREEN}${BOLD}═══ FRONTEND PIPELINE: ALL CHECKS PASSED ═══${NC}"
  exit 0
fi
echo "${RED}${BOLD}═══ FRONTEND PIPELINE: ${failures} CHECK(S) FAILED ═══${NC}"
exit 1
