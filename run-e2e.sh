#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════════════
# CYPHER65 War Room — E2E Test Runner
# ====================================
# Starts the Flask server, runs Playwright E2E tests, generates report.
#
# Usage:
#   bash run-e2e.sh                          # full run
#   bash run-e2e.sh --headed                 # with browser UI visible
#   bash run-e2e.sh --file dashboard.spec.js # single test file
#   bash run-e2e.sh --debug                  # Playwright UI debug mode
#
# CI usage:
#   CI=true bash run-e2e.sh                  # retry failures once, strict mode
# ═══════════════════════════════════════════════════════════════════════════

set -euo pipefail
cd "$(dirname "$0")"

# ── Config ────────────────────────────────────────────────────────────────
PORT="${PORT:-8765}"
BASE_URL="http://127.0.0.1:${PORT}"
FLASK_LOG="/tmp/cypher65_e2e_server.log"
PLAYWRIGHT_ARGS=""

# Parse CLI flags
for arg in "$@"; do
  case "$arg" in
    --headed)   PLAYWRIGHT_ARGS="$PLAYWRIGHT_ARGS --headed" ;;
    --debug)    PLAYWRIGHT_ARGS="$PLAYWRIGHT_ARGS --debug" ;;
    --file=*)   PLAYWRIGHT_ARGS="$PLAYWRIGHT_ARGS ${arg#--file=}" ;;
    *)          echo "Unknown option: $arg"; exit 1 ;;
  esac
done

# ── Cleanup handler ───────────────────────────────────────────────────────
cleanup() {
  echo ""
  echo "═══ Cleaning up... ═══"
  if [ -n "${SERVER_PID:-}" ]; then
    echo "Stopping Flask server (PID $SERVER_PID)..."
    kill "$SERVER_PID" 2>/dev/null || true
    wait "$SERVER_PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

# ── Check dependencies ────────────────────────────────────────────────────
echo "═══ Checking dependencies ═══"

if ! command -v python3 &>/dev/null; then
  echo "ERROR: python3 not found"; exit 1
fi

if ! command -v npx &>/dev/null; then
  echo "ERROR: npx not found (install Node.js ≥18)"; exit 1
fi

# Ensure Playwright browsers are installed
if [ ! -d "node_modules" ] || [ ! -d "node_modules/@playwright" ]; then
  echo "Installing Playwright test dependencies..."
  npm install 2>&1 | tail -3
fi

if ! npx playwright install chromium 2>/dev/null; then
  echo "Installing Playwright Chromium browser..."
  npx playwright install chromium
fi

# ── Start Flask server ────────────────────────────────────────────────────
echo ""
echo "═══ Starting Flask server on port ${PORT} ═══"

VENV_PYTHON="venv/bin/python3"
if [ ! -f "$VENV_PYTHON" ]; then
  VENV_PYTHON="venv/bin/python"
fi

if [ ! -f "$VENV_PYTHON" ]; then
  echo "WARNING: virtual env not found at venv/bin/python, trying system python..."
  VENV_PYTHON="python3"
fi

# E2E suites fire dozens of requests per minute (page load + 15s polling +
# panel fetches) — raise the per-IP rate limit so the suite never hits 429.
RATE_LIMIT_PER_MINUTE="${RATE_LIMIT_PER_MINUTE:-1000}" $VENV_PYTHON app.py &>"$FLASK_LOG" &
SERVER_PID=$!

# Wait for server to start
for i in $(seq 1 15); do
  if curl -s "$BASE_URL/api/snapshot" >/dev/null 2>&1; then
    echo "Flask server ready (PID $SERVER_PID)"
    break
  fi
  if [ "$i" -eq 15 ]; then
    echo "ERROR: Flask server failed to start (see $FLASK_LOG)"
    cat "$FLASK_LOG" | tail -20
    exit 1
  fi
  sleep 1
done

# Allow one full poll cycle to populate data
sleep 5

# ── Run Playwright tests ──────────────────────────────────────────────────
echo ""
echo "═══ Running Playwright E2E tests ═══"
echo "Base URL: $BASE_URL"
echo ""

export BASE_URL
CI="${CI:-false}" npx playwright test $PLAYWRIGHT_ARGS 2>&1 | tee /tmp/cypher65_e2e_output.log
EXIT_CODE="${PIPESTATUS[0]}"

# ── Results ───────────────────────────────────────────────────────────────
echo ""
echo "═══ E2E Results ═══"
if [ "$EXIT_CODE" -eq 0 ]; then
  echo "✅ ALL E2E TESTS PASSED"
else
  echo "❌ SOME E2E TESTS FAILED (exit code $EXIT_CODE)"
fi

# Show report path
if [ -d "e2e-report" ]; then
  echo "HTML report: e2e-report/index.html"
fi

exit "$EXIT_CODE"
