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
#   3. check:a11y         — guard a11y (Issue #235): lang pt-BR, botão
#                           ícone-only sem nome, label órfão
#   4. test:a11y-guards   — self-test do guard a11y
#   5. check:tokens-hex   — guard de tokens (Issue #237): zero #hex fora
#                           do style.css/theme-color em app.js/templates
#   6. test:tokens-hex    — self-test do guard de tokens#   7. JS core            — node --check static/app.js + test_app_js_core.js
#                           (suíte espelhada dos helpers do app.js)
#   8. check-mobile-xss   — guard XSS mobile (React Native): WebView
#                           html/injectedJavaScript, eval, openURL
#   9. test:mobile-guards — self-test do guard mobile   #  10. audit:ui:all       — auditoria visual desktop + mobile (console
#                           errors, overflow, truncamento, skeletons presos)
#  11. check:axe           — GATE axe-core real (Issue #244): falha se
#                           button-name > 0 ou score proxy < 90 (2 viewports)
#  12. test:axe-guards     — self-test do gate axe-core (fixtures file://)
#  13. check:fetcher-units — guard de regressão de unidade dos fetchers
#                           (NiceHash/MRR/Braiins × payloads reais, Issue #319)
#  14. test:fetcher-units  — self-test do guard (regressões 1e6x/24k/1000x)
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
step node scripts/check-a11y.cjs --report
step node tests/test_a11y_guards.js
step bash scripts/check-tokens-hex.sh
step bash tests/test_tokens_hex.sh
step node --check static/app.js
step node --check static/sw.js
step node --test tests/test_app_js_core.js
step node tests/test_sw_push.cjs
step node scripts/check-mobile-xss.cjs
step node tests/test_mobile_xss_guards.js
step node scripts/audit_ui.cjs --all
step node scripts/check-axe.cjs --report
step node tests/test_axe_gate.js
step python scripts/check-fetcher-units.py
step python -m pytest tests/test_fetcher_units_guard.py -q

echo
if [ "$FAIL" -ne 0 ]; then
  echo "❌ [frontend] pipeline FAILED — $FAIL check(s) vermelho(s)"
  exit 1
fi
echo "✅ [frontend] pipeline green — guards DOM + a11y + tokens-hex + XSS mobile + JS core + audit visual + axe-core + fetcher-units"
exit 0
