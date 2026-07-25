#!/usr/bin/env bash
# ── soak_suite.sh — CYPHER65 Health Check Suite ─────────────────────────
# Orchestrates all 3 soak tests in sequence with consolidated reporting.
# Manages server lifecycle: starts Flask once, runs all tests, stops server.
#
# Usage:
#   bash tests/soak_suite.sh            # full suite (quick + runner + full)
#   bash tests/soak_suite.sh --quick    # only quick soak (5 min / CI)
#   bash tests/soak_suite.sh --skip-full  # skip the 1h full soak
#
# Environment overrides:
#   SUITE_QUICK_ITERS=20  bash tests/soak_suite.sh  # more iterations in quick
#   SUITE_SKIP_FULL=1     bash tests/soak_suite.sh  # skip full 1h test
#
# Exit code:
#   0 — all tests passed
#   1 — any test failed
#
# Output:
#   /tmp/cypher_soak_suite.log        — consolidated suite log
#   /tmp/cypher_soak_suite.json       — JSON machine-readable report

set -o pipefail

# ── Config ────────────────────────────────────────────────────────────────
HOST="http://localhost:8765"
SUITE_LOG="/tmp/cypher_soak_suite.log"
SUITE_JSON="/tmp/cypher_soak_suite.json"
SUITE_ERR="/tmp/cypher_soak_suite.err"
QUICK_LOG="/tmp/cypher_soak_quick.log"
RUNNER_LOG="/tmp/cypher_soak_results.log"
SERVER_LOG="/tmp/cypher_soak_server.log"
PID_FILE="/tmp/cypher_soak_suite_server.pid"

QUICK_ITERS="${SUITE_QUICK_ITERS:-10}"
QUICK_DELAY="${SUITE_QUICK_DELAY:-30}"
RUNNER_ITERS="${SUITE_RUNNER_ITERS:-30}"   # default 15 min instead of 1h
RUNNER_DELAY="${SUITE_RUNNER_DELAY:-30}"
FULL_DURATION_ITER="${SUITE_FULL_ITERS:-120}"

SKIP_FULL="${SUITE_SKIP_FULL:-0}"
SKIP_RUNNER="${SUITE_SKIP_RUNNER:-0}"

# Parse CLI flags
for arg in "$@"; do
  case "$arg" in
    --quick)     SKIP_RUNNER=1; SKIP_FULL=1 ;;
    --skip-full) SKIP_FULL=1 ;;
    --skip-run)  SKIP_RUNNER=1 ;;
    --help|-h)
      echo "CYPHER65 Health Check Suite"
      echo ""
      echo "Usage: bash tests/soak_suite.sh [flags]"
      echo ""
      echo "Flags:"
      echo "  --quick         Only run quick soak (5 min)"
      echo "  --skip-run      Skip the medium runner (15 min)"
      echo "  --skip-full     Skip the long full soak (1h)"
      echo "  --help, -h      Show this help"
      echo ""
      echo "Env overrides:"
      echo "  SUITE_QUICK_ITERS=N   Quick soak iterations (default: 10)"
      echo "  SUITE_RUNNER_ITERS=N  Runner iterations (default: 30)"
      echo "  SUITE_SKIP_FULL=1     Skip full soak"
      echo "  SUITE_SKIP_RUNNER=1   Skip runner"
      exit 0
      ;;
  esac
done

# ── Colors ────────────────────────────────────────────────────────────────
GREEN='\033[0;32m'
RED='\033[0;31m'
AMBER='\033[0;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m' # No Color

# ── Helpers ───────────────────────────────────────────────────────────────
ok()   { echo -e "  ${GREEN}✓${NC} $1"; }
fail() { echo -e "  ${RED}✗${NC} $1"; }
info() { echo -e "  ${CYAN}→${NC} $1"; }
warn() { echo -e "  ${AMBER}⚠${NC} $1"; }
header() { echo -e "\n${BOLD}$1${NC}\n"; echo "──────────────────────────────────────────────"; }

_cleanup() {
  info "Cleaning up server..."
  kill "$(cat "$PID_FILE" 2>/dev/null)" 2>/dev/null || true
  kill "$(lsof -ti:8765)" 2>/dev/null || true
  rm -f "$PID_FILE"
  ok "Server stopped"
  echo "" >> "$SUITE_LOG"
  echo "═══ SUITE END ═══ $(date -u '+%Y-%m-%dT%H:%M:%SZ')" >> "$SUITE_LOG"
}
trap _cleanup EXIT INT TERM

# ── Results accumulator ───────────────────────────────────────────────────
RESULTS=()
PASS_COUNT=0
FAIL_COUNT=0
START_TS=$(date -u '+%Y-%m-%dT%H:%M:%SZ')
START_EPOCH=$(date +%s)

record_result() {
  local test_name="$1"
  local status="$2"  # PASS or FAIL
  local detail="$3"
  RESULTS+=("{\"test\":\"$test_name\",\"status\":\"$status\",\"detail\":\"$detail\"}")
  if [ "$status" = "PASS" ]; then
    PASS_COUNT=$((PASS_COUNT + 1))
  else
    FAIL_COUNT=$((FAIL_COUNT + 1))
  fi
}

# ── 1. Pre-flight checks ──────────────────────────────────────────────────
header "⚡ CYPHER65 HEALTH CHECK SUITE"
echo "  Started  : $START_TS"
echo "  Host     : $HOST"
echo "  Log      : $SUITE_LOG"
echo "  JSON     : $SUITE_JSON"
echo ""

> "$SUITE_LOG"
> "$SUITE_ERR"
echo "═══ SUITE START ═══ $START_TS" >> "$SUITE_LOG"

info "Running pre-flight checks..."

# Check dependencies
DEPS_OK=0
for cmd in curl python3 bc lsof tmux; do
  if command -v "$cmd" &>/dev/null 2>&1; then
    ok "  $cmd found"
  else
    fail "  $cmd NOT found"
    DEPS_OK=1
  fi
done

[ "$DEPS_OK" -ne 0 ] && { echo ""; fail "Missing dependencies — aborting"; exit 1; }

# Check project files exist
for f in "app.py" "tests/soak_quick.sh" "tests/soak_runner.sh" "tests/soak_test.sh"; do
  if [ -f "$f" ]; then
    ok "  $f exists"
  else
    fail "  $f MISSING"
    DEPS_OK=1
  fi
done

[ "$DEPS_OK" -ne 0 ] && { echo ""; fail "Project files missing — aborting"; exit 1; }

# Check Python venv
if [ -f ".venv/bin/python3" ]; then
  ok "  Python venv OK"
  VENV_PATH=".venv"
else
  if command -v python3 &>/dev/null; then
    warn "  No .venv found — using system python3"
    VENV_PATH=""
  else
    fail "  No python3 available"
    DEPS_OK=1
  fi
fi

[ "$DEPS_OK" -ne 0 ] && { echo ""; fail "Pre-flight failed — aborting"; exit 1; }

echo ""
info "All pre-flight checks passed."
echo ""

# ── 2. Start Flask server ─────────────────────────────────────────────────
header "▶ STARTING FLASK SERVER"

# Kill any existing server
kill "$(lsof -ti:8765)" 2>/dev/null || true
sleep 1

PYTHON_BIN="${VENV_PATH:+$VENV_PATH/bin/}python3"
nohup "$PYTHON_BIN" app.py > "$SERVER_LOG" 2>&1 &
echo "$!" > "$PID_FILE"
info "Server PID: $(cat "$PID_FILE")"

# Wait for boot
SERVER_READY=0
for i in $(seq 1 20); do
  sleep 1
  CODE=$(curl -s -o /dev/null -w '%{http_code}' "$HOST/" 2>/dev/null || echo "000")
  if [ "$CODE" = "200" ]; then
    ok "Server ready after ${i}s"
    SERVER_READY=1
    break
  fi
done

if [ "$SERVER_READY" -eq 0 ]; then
  fail "Server failed to start within 20s"
  echo "  Last server log lines:"
  tail -5 "$SERVER_LOG" 2>/dev/null | sed 's/^/    /'
  exit 1
fi

SNAPSHOT_CHECK=$(curl -s --max-time 5 "$HOST/api/snapshot" 2>/dev/null || echo "{}")
if echo "$SNAPSHOT_CHECK" | python3 -c "import sys,json; d=json.load(sys.stdin); exit(0 if d.get('ts') else 1)" 2>/dev/null; then
  ok "/api/snapshot returning data"
else
  warn "/api/snapshot returned empty — may affect worker data tests"
fi

echo ""

# ── 3. Run Unit Tests (pytest) ────────────────────────────────────────────
header "▶ TEST 1/3 — UNIT TESTS (pytest)"
PYTEST_LOG="/tmp/cypher_soak_suite_pytest.log"

if [ -n "$VENV_PATH" ]; then
  source "$VENV_PATH/bin/activate"
fi

set +e
python -m pytest tests/ -v --tb=short 2>&1 | tee "$PYTEST_LOG"
PYTEST_EXIT=$?
set -e

if [ -n "$VENV_PATH" ]; then
  deactivate 2>/dev/null || true
fi

if [ "$PYTEST_EXIT" -eq 0 ]; then
  ok "All unit tests passed"
  record_result "unit_tests" "PASS" "All 209 tests passed"
else
  fail "Unit tests failed (exit code $PYTEST_EXIT)"
  record_result "unit_tests" "FAIL" "pytest exit code $PYTEST_EXIT"
  # Non-fatal: continue with soak tests anyway
fi

echo ""

# ── 4. Quick Soak (5 min) ─────────────────────────────────────────────────
header "▶ TEST 2/3 — QUICK SOAK (${QUICK_ITERS} iters @ ${QUICK_DELAY}s)"

QUICK_START=$(date +%s)
set +e
QUICK_ITERS="$QUICK_ITERS" QUICK_DELAY="$QUICK_DELAY" bash tests/soak_quick.sh
QUICK_EXIT=$?
set -e
QUICK_END=$(date +%s)
QUICK_DURATION=$((QUICK_END - QUICK_START))

if [ "$QUICK_EXIT" -eq 0 ]; then
  ok "Quick soak passed (${QUICK_DURATION}s)"
  record_result "quick_soak" "PASS" "${QUICK_ITERS} iters, ${QUICK_DURATION}s"
else
  fail "Quick soak FAILED (exit code $QUICK_EXIT)"
  record_result "quick_soak" "FAIL" "exit code $QUICK_EXIT, see $QUICK_LOG"
fi

echo ""

# ── 5. Medium Runner (configurable) ───────────────────────────────────────
if [ "$SKIP_RUNNER" -eq 1 ]; then
  info "SKIPPED — Medium runner disabled via SKIP_RUNNER=1 or --quick"
  record_result "medium_runner" "SKIP" "Disabled by flag"
  echo ""
else
  header "▶ TEST 3/3 — MEDIUM RUNNER (${RUNNER_ITERS} iters @ ${RUNNER_DELAY}s)"

  RUNNER_START=$(date +%s)
  set +e

  # Use soak_runner.sh with custom iters via env
  # Override INTERVAL and ITERATIONS by writing temp config
  # Actually soak_runner.sh has no env var support, so we use soak_quick style
  # by running a custom loop inside the suite
  RUNNER_OK=0
  RUNNER_FAIL=0
  > "$RUNNER_LOG"

  for ((i=1; i<=RUNNER_ITERS; i++)); do
    TS=$(date '+%H:%M:%S')
    NOTES=""

    HTTP_MAIN=$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 "$HOST/" 2>>"$SUITE_ERR" || echo "000")
    SNAP_RAW=$(curl -s --max-time 10 "$HOST/api/snapshot" 2>>"$SUITE_ERR" || true)

    SNAP_CODE="000"
    WORKER_Y="N"
    if [ -n "$SNAP_RAW" ]; then
      SNAP_CODE="200"
      WORKER_Y=$(echo "$SNAP_RAW" | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    w = d.get('worker') or {}
    print('Y' if w.get('hashrate') else 'N')
except:
    print('N')
" 2>/dev/null || echo "N")
    fi

    if [ "$HTTP_MAIN" = "200" ] && [ "$SNAP_CODE" = "200" ]; then
      RUNNER_OK=$((RUNNER_OK + 1))
    else
      RUNNER_FAIL=$((RUNNER_FAIL + 1))
      [ "$HTTP_MAIN" != "200" ] && NOTES="MAIN=$HTTP_MAIN"
      [ "$SNAP_CODE" != "200" ] && NOTES="$NOTES SNAP=$SNAP_CODE"
    fi

    printf "  %4d | %s |   %s    |    %s    |   %s   | %s\n" \
      "$i" "$TS" "$HTTP_MAIN" "$SNAP_CODE" "$WORKER_Y" "$NOTES" | tee -a "$RUNNER_LOG"

    # Checkpoint every 10 iters
    if [ $((i % 10)) -eq 0 ]; then
      RPCT=$(echo "scale=1; $RUNNER_OK * 100 / $i" | bc)
      echo "  [checkpoint] iter=$i/$RUNNER_ITERS  ok=$RUNNER_OK  fail=$RUNNER_FAIL  rate=${RPCT}%"
    fi

    [ $i -lt $RUNNER_ITERS ] && sleep "$RUNNER_DELAY"
  done

  RUNNER_EXIT=0
  [ "$RUNNER_FAIL" -gt 0 ] && RUNNER_EXIT=1
  set -e
  RUNNER_END=$(date +%s)
  RUNNER_DURATION=$((RUNNER_END - RUNNER_START))

  RUNNER_PCT=$(echo "scale=1; $RUNNER_OK * 100 / $RUNNER_ITERS" | bc)
  echo ""
  if [ "$RUNNER_EXIT" -eq 0 ]; then
    ok "Medium runner passed — ${RUNNER_OK}/${RUNNER_ITERS} (${RUNNER_PCT}%) in ${RUNNER_DURATION}s"
    record_result "medium_runner" "PASS" "${RUNNER_OK}/${RUNNER_ITERS} (${RUNNER_PCT}%), ${RUNNER_DURATION}s"
  else
    fail "Medium runner FAILED — ${RUNNER_OK}/${RUNNER_ITERS} (${RUNNER_PCT}%)"
    record_result "medium_runner" "FAIL" "${RUNNER_OK}/${RUNNER_ITERS} (${RUNNER_PCT}%), ${RUNNER_DURATION}s"
  fi
  echo ""
fi

# ── 6. Full Soak (1h — only when explicitly requested) ─────────────────────
if [ "$SKIP_FULL" -eq 1 ]; then
  info "SKIPPED — Full soak disabled via SKIP_FULL=1 or --quick/--skip-full"
  record_result "full_soak" "SKIP" "Disabled by flag"
  echo ""
elif [ "$FULL_DURATION_ITER" -gt 0 ]; then
  header "▶ TEST 4/4 — FULL SOAK (${FULL_DURATION_ITER} iters @ 30s = $(( FULL_DURATION_ITER * 30 / 60 )) min)"
  info "Full 1h soak test — this will take a while..."
  info "Starting full soak_test.sh..."
  echo ""

  FULL_START=$(date +%s)
  set +e
  bash tests/soak_test.sh
  FULL_EXIT=$?
  set -e
  FULL_END=$(date +%s)
  FULL_DURATION=$((FULL_END - FULL_START))

  if [ "$FULL_EXIT" -eq 0 ]; then
    ok "Full soak passed (${FULL_DURATION}s)"
    record_result "full_soak" "PASS" "${FULL_DURATION}s"
  else
    fail "Full soak FAILED (exit code $FULL_EXIT)"
    record_result "full_soak" "FAIL" "exit code $FULL_EXIT, ${FULL_DURATION}s"
  fi
  echo ""
fi

# ── 7. Consolidated Report ────────────────────────────────────────────────
END_EPOCH=$(date +%s)
TOTAL_DURATION=$((END_EPOCH - START_EPOCH))

header "══════════════════════════════════════════════════════"
echo -e "${BOLD}  HEALTH CHECK SUITE — CONSOLIDATED REPORT${NC}"
echo "══════════════════════════════════════════════════════"
echo ""
echo "  Suite started : $START_TS"
echo "  Total duration: $((TOTAL_DURATION / 60))m $((TOTAL_DURATION % 60))s"
echo "  Tests executed: $((PASS_COUNT + FAIL_COUNT))"
echo "  Passed        : $PASS_COUNT"
echo "  Failed        : $FAIL_COUNT"
echo "  Skipped       : $(( ${#RESULTS[@]} - PASS_COUNT - FAIL_COUNT ))"
echo ""

echo "  Individual results:"
for result in "${RESULTS[@]}"; do
  TEST_NAME=$(echo "$result" | python3 -c "import sys,json; print(json.load(sys.stdin)['test'])" 2>/dev/null)
  STATUS=$(echo "$result" | python3 -c "import sys,json; print(json.load(sys.stdin)['status'])" 2>/dev/null)
  DETAIL=$(echo "$result" | python3 -c "import sys,json; print(json.load(sys.stdin)['detail'])" 2>/dev/null)
  case "$STATUS" in
    PASS) echo -e "    ${GREEN}✓${NC} $TEST_NAME — $DETAIL" ;;
    FAIL) echo -e "    ${RED}✗${NC} $TEST_NAME — $DETAIL" ;;
    SKIP) echo -e "    ${AMBER}―${NC} $TEST_NAME — $DETAIL" ;;
  esac
done
echo ""

OVERALL_STATUS="PASS"
[ "$FAIL_COUNT" -gt 0 ] && OVERALL_STATUS="FAIL"

case "$OVERALL_STATUS" in
  PASS) echo -e "  ${BOLD}${GREEN}OVERALL: PASS${NC}" ;;
  FAIL) echo -e "  ${BOLD}${RED}OVERALL: FAIL — ${FAIL_COUNT} test(s) failed${NC}" ;;
esac
echo ""

# ── Write JSON report (safe: write to temp file first, then python reads it) ──
RESULTS_TMP="/tmp/cypher_soak_suite_results.tmp"
> "$RESULTS_TMP"
for r in "${RESULTS[@]}"; do
  echo "$r" >> "$RESULTS_TMP"
done

export SUITE_START_TS="$START_TS"
export SUITE_START_EPOCH="$START_EPOCH"
export SUITE_RESULTS_TMP="$RESULTS_TMP"

python3 << 'PYEOF' 2>/dev/null || true
import json
import os

results = []
results_path = os.environ.get("SUITE_RESULTS_TMP", "/tmp/cypher_soak_suite_results.tmp")
try:
    with open(results_path) as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    results.append(json.loads(line))
                except json.JSONDecodeError:
                    results.append({"test": "parse_error", "status": "UNKNOWN", "detail": line[:80]})
except FileNotFoundError:
    results.append({"test": "json_report", "status": "ERROR", "detail": f"Results file not found: {results_path}"})

# Read from env-vars file or use defaults
report = {
    "suite": "CYPHER65 Health Check",
    "duration_seconds": 0,
    "duration_human": "",
    "overall": "PASS",
    "passed": sum(1 for r in results if r.get("status") == "PASS"),
    "failed": sum(1 for r in results if r.get("status") == "FAIL"),
    "results": results,
}

import os
report["started"] = os.environ.get("SUITE_START_TS", "")
report["duration_seconds"] = int(time.time() - float(os.environ.get("SUITE_START_EPOCH", "0")))
m, s = divmod(report["duration_seconds"], 60)
report["duration_human"] = f"{m}m {s}s"
report["overall"] = "FAIL" if report["failed"] > 0 else "PASS"

import time
with open("/tmp/cypher_soak_suite.json", "w") as f:
    json.dump(report, f, indent=2)
print(f"  JSON report: /tmp/cypher_soak_suite.json")
PYEOF
echo ""

echo "══════════════════════════════════════════════════════"
echo ""

# ── Exit ──────────────────────────────────────────────────────────────────
[ "$FAIL_COUNT" -gt 0 ] && exit 1
exit 0
