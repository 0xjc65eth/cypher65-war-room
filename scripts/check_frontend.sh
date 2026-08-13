#!/usr/bin/env bash
# check_frontend.sh — pipeline combinado de frontend (Issue #62)
#
# Roda, em sequência e de forma blocking, TODOS os checks de frontend num
# único comando — para dev local e como check único do job `frontend-audit`
# no CI:
#
#   1. check:dom          — guard estático DOM (ids duplicados + XSS
#                           innerHTML/concat/sinks) + 📊 report
#   2. test:dom-guards    — self-test do próprio guard DOM
#   3. JS core            — node --check static/app.js + test_app_js_core.js
#                           (suíte espelhada dos helpers do app.js)
#   4. check-mobile-xss   — guard XSS mobile (React Native): WebView
#                           html/injectedJavaScript, eval, openURL
#   5. test:mobile-guards — self-test do guard mobile
#   6. audit:ui:all       — auditoria visual desktop + mobile (console
#                           errors, overflow, truncamento, skeletons presos)
#
# Boota o Flask localmente (porta 8765) com rate-limit alto (o audit faz
# muitas navegações por viewport) e derruba o servidor ao final. Setando
# AUDIT_URL, o boot é pulado (aponta para servidor externo).
#
# Exit codes (CI-friendly):
#   0 — pipeline green
#   1 — pelo menos um check falhou (merge bloqueado)
#   2 — servidor não subiu / erro de execução
set -u

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

AUDIT_URL="${AUDIT_URL:-}"
SERVER_PID=""

if [ -z "$AUDIT_URL" ]; then
  # Porta 8765 já respondendo = servidor VELHO no ar (dev local). O audit
  # rodaria contra código obsoleto — erro explícito em vez de corrida.
  if curl -s -o /dev/null http://127.0.0.1:8765/api/healthz; then
    echo "❌ [frontend] porta 8765 já está em uso (servidor anterior?)." >&2
    echo "   Mate o processo antigo (pkill -f 'python app.py') ou aponte AUDIT_URL para outro servidor." >&2
    exit 2
  fi

  RATE_LIMIT_PER_MINUTE=10000 \
  SECRET_KEY="${SECRET_KEY:-ci-test-secret-key-0123456789abcdef}" \
    nohup python app.py &> /tmp/c65_frontend_audit.log &
  SERVER_PID=$!

  cleanup() {
    if [ -n "$SERVER_PID" ] && kill -0 "$SERVER_PID" 2>/dev/null; then
      kill "$SERVER_PID" 2>/dev/null || true
    fi
  }
  trap cleanup EXIT

  echo "[frontend] booting Flask (pid $SERVER_PID)…"
  READY=0
  for i in $(seq 1 60); do
    # Healthz precisa responder HTTP 200 (curl sozinho aceita 500 também).
    STATUS=$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8765/api/healthz 2>/dev/null || echo 000)
    if [ "$STATUS" = "200" ]; then
      echo "[frontend] server ready after ${i}s"
      READY=1
      break
    fi
    sleep 1
  done
  if [ "$READY" -ne 1 ]; then
    echo "❌ [frontend] server did not boot — /tmp/c65_frontend_audit.log" >&2
    tail -20 /tmp/c65_frontend_audit.log >&2 || true
    exit 2
  fi
  if ! kill -0 "$SERVER_PID" 2>/dev/null; then
    echo "❌ [frontend] processo do servidor morreu após o healthz — /tmp/c65_frontend_audit.log" >&2
    tail -20 /tmp/c65_frontend_audit.log >&2 || true
    exit 2
  fi
  # Warmup das threads de background (polling/alertas) — mesma convenção do e2e.
  sleep 2
fi

FAIL=0
step() {
  echo
  echo "──── $*"
  if ! "$@"; then
    echo "  ❌ FAILED: $*"
    FAIL=1
  fi
}

step node scripts/check-dom-regression.cjs --report
step node tests/test_dom_guards.js
step node --check static/app.js
step node --test tests/test_app_js_core.js
step node scripts/check-mobile-xss.cjs
step node tests/test_mobile_xss_guards.js
step node scripts/audit_ui.cjs --all

echo
if [ "$FAIL" -ne 0 ]; then
  echo "❌ [frontend] pipeline FAILED — $FAIL check(s) vermelho(s)"
  exit 1
fi
echo "✅ [frontend] pipeline green — guards DOM + XSS mobile + JS core + audit visual"
exit 0
