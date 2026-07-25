#!/usr/bin/env bash
#
# CYPHER65 · SOAK TEST
# =====================
# Starts the Flask server in a dedicated tmux session, polls / and /api/snapshot
# every 30 seconds for 1 hour (120 iterations), logs every response, and
# produces a final stability report.
#
# Usage:
#   bash tests/soak_test.sh
#
# Output:
#   /tmp/cypher_soak_test.log   — raw per-request log
#   /tmp/cypher_soak_test.err   — stderr of curl failures
#   stdout                      — live summary + final report
#
# Exit code:
#   0 — all requests succeeded (2xx)
#   1 — any request failed (non-2xx, timeout, connection refused)

set -o pipefail
set -o errexit

# ── Config ────────────────────────────────────────────────────────────────
HOST="http://localhost:8765"
INTERVAL=30          # seconds between polls
ITERATIONS=120       # 120 × 30s = 3600s = 1 hour
TMUX_SESSION="cypher-soak"
SERVER_STARTUP_WAIT=8  # seconds to wait after starting server
LOG="/tmp/cypher_soak_test.log"
ERR="/tmp/cypher_soak_test.err"
PID_FILE="/tmp/cypher_soak_test_server.pid"

# ── Cleanup handler ───────────────────────────────────────────────────────
_cleanup() {
  echo ""
  echo "═══ CLEANUP ═══"
  # Kill the tmux server session
  tmux kill-session -t "$TMUX_SESSION" 2>/dev/null || true
  # Also try to kill any lingering Flask process
  if [ -f "$PID_FILE" ]; then
    kill "$(cat "$PID_FILE")" 2>/dev/null || true
    rm -f "$PID_FILE"
  fi
  kill "$(lsof -ti:8765)" 2>/dev/null || true
  echo "[cleanup] server stopped"
}
trap _cleanup EXIT INT TERM

# ── 1. Kill existing server on port 8765 ──────────────────────────────────
echo "═══ CYPHER65 SOAK TEST ═══"
echo "  target  : $HOST"
echo "  interval: ${INTERVAL}s"
echo "  duration: $(( ITERATIONS * INTERVAL / 60 )) min ($ITERATIONS polls)"
echo ""

echo "[1/4] Cleaning up any previous server..."
kill "$(lsof -ti:8765)" 2>/dev/null || true
tmux kill-session -t "$TMUX_SESSION" 2>/dev/null || true
sleep 1

# ── 2. Start server in tmux ───────────────────────────────────────────────
echo "[2/4] Starting Flask server in tmux session '$TMUX_SESSION'..."
cd "$(dirname "$0")/.." || exit 1

# Start server in a detached tmux session
tmux new-session -d -s "$TMUX_SESSION" -x 120 -y 30 \
  "bash -c '.venv/bin/python3 app.py 2>&1 | tee /tmp/cypher_soak_server.log'"

# Save PID for cleanup
SERVER_PID=$(lsof -ti:8765 2>/dev/null || echo "")
if [ -n "$SERVER_PID" ]; then
  echo "$SERVER_PID" > "$PID_FILE"
fi

# ── 3. Wait for server to be ready ────────────────────────────────────────
echo "[3/4] Waiting ${SERVER_STARTUP_WAIT}s for server startup..."
sleep "$SERVER_STARTUP_WAIT"

# Verify server responded at least once
HTTP_CODE=$(curl -s -o /dev/null -w '%{http_code}' "$HOST/" 2>/dev/null || echo "000")
if [ "$HTTP_CODE" = "000" ]; then
  echo "[FATAL] Server did not start within ${SERVER_STARTUP_WAIT}s."
  echo "  Check /tmp/cypher_soak_server.log for errors."
  exit 1
fi
echo "  Server responded with HTTP $HTTP_CODE — ready for soak test."
echo ""

# ── 4. Soak poll loop ─────────────────────────────────────────────────────
echo "[4/4] Starting soak poll loop ($ITERATIONS polls at ${INTERVAL}s intervals)..."
echo ""
echo "═══════════════════════════════════════════════════════════════════════"
echo "  ITER |   TIMESTAMP    |  /  STATUS | SNAPSHOT | WORKER | NOTES"
echo "═══════════════════════════════════════════════════════════════════════"

> "$LOG"
> "$ERR"

TOTAL=$ITERATIONS
OK=0
FAIL=0
FIRST_FAIL_TS=""
FIRST_FAIL_ITER=""
declare -a FAIL_LOG=()

for i in $(seq 1 $ITERATIONS); do
  TS=$(date '+%H:%M:%S')
  TIMESTAMP_EPOCH=$(date +%s)
  NOTES=""
  ITER_FAIL=0

  # ── Request 1: GET / ──
  HTTP_MAIN=$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 "$HOST/" 2>>"$ERR" || echo "000")

  # ── Request 2: GET /api/snapshot + check worker presence ──
  SNAPSHOT_BODY=""
  SNAPSHOT_STATUS="000"
  WORKER_PRESENT="N"
  SNAPSHOT_RAW=$(curl -s --max-time 10 "$HOST/api/snapshot" 2>>"$ERR" || true)
  if [ -n "$SNAPSHOT_RAW" ]; then
    SNAPSHOT_STATUS="200"
    # Check if worker data is present
    WORKER_PRESENT=$(echo "$SNAPSHOT_RAW" | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    w = d.get('worker') or {}
    ts = d.get('ts', 0)
    hr = w.get('hashrate', 0)
    bd = w.get('bestDifficulty') or ''
    ls = w.get('lastSubmission') or ''
    print(f'Y|ts={ts}|hr={hr}|diff={bd}|last={ls}')
except Exception:
    print('N|||')
" 2>/dev/null || echo "N|||")
  else
    SNAPSHOT_STATUS="000"
    WORKER_PRESENT="N|timeout"
  fi

  # ── Parse worker info ──
  WORKER_HR=$(echo "$WORKER_PRESENT" | cut -d'|' -f3 2>/dev/null || echo "?")
  WORKER_HAS_DATA=$(echo "$WORKER_PRESENT" | cut -d'|' -f1 2>/dev/null || echo "N")

  # ── Classify result ──
  if [ "$HTTP_MAIN" = "200" ] && [ "$SNAPSHOT_STATUS" = "200" ]; then
    OK=$((OK + 1))
    STATUS_ICON="✓"
  else
    FAIL=$((FAIL + 1))
    ITER_FAIL=1
    STATUS_ICON="✗"
    if [ -z "$FIRST_FAIL_TS" ]; then
      FIRST_FAIL_TS="$TS"
      FIRST_FAIL_ITER=$i
    fi
    if [ "$HTTP_MAIN" != "200" ]; then
      NOTES="MAIN=$HTTP_MAIN"
    fi
    if [ "$SNAPSHOT_STATUS" != "200" ]; then
      [ -n "$NOTES" ] && NOTES="$NOTES | "
      NOTES="${NOTES}SNAP=$SNAPSHOT_STATUS"
    fi
    FAIL_LOG+=("iter=$i ts=$TS main=$HTTP_MAIN snap=$SNAPSHOT_STATUS err=$NOTES")
  fi

  # ── Log raw line ──
  REMAINING=$(( ITERATIONS - i ))
  printf "  %4d | %s |   %s    |    %s    |  %s  | %s\n" \
    "$i" "$TS" "$HTTP_MAIN" "$SNAPSHOT_STATUS" "$WORKER_HAS_DATA" "$NOTES" | tee -a "$LOG"

  # ── If server went completely silent, restart ──
  if [ "$HTTP_MAIN" = "000" ] && [ "$SNAPSHOT_STATUS" = "000" ]; then
    NOTES="SERVER_DOWN — attempting restart..."
    echo "  ⚠ SERVER CRASH DETECTED at iter $i ($TS) — restarting..."
    kill "$(lsof -ti:8765)" 2>/dev/null || true
    sleep 2
    tmux new-session -d -s "$TMUX_SESSION" -x 120 -y 30 \
      "bash -c '.venv/bin/python3 app.py 2>&1 | tee /tmp/cypher_soak_server.log'"
    sleep "$SERVER_STARTUP_WAIT"
    echo "  ↻ Server restarted at iter $i ($TS)" >> "$LOG"
  fi

  # ── Throttle ──
  if [ $i -lt $ITERATIONS ]; then
    sleep "$INTERVAL"
  fi
done

# ═══════════════════════════════════════════════════════════════════════════
#  FINAL REPORT
# ═══════════════════════════════════════════════════════════════════════════

echo ""
echo "═══════════════════════════════════════════════════════════════════════"
echo "  SOAK TEST COMPLETE — FINAL REPORT"
echo "═══════════════════════════════════════════════════════════════════════"
echo ""
echo "  Target          : $HOST"
echo "  Duration        : $(( ITERATIONS * INTERVAL / 60 )) min ($ITERATIONS polls at ${INTERVAL}s)"
echo "  Total requests  : $TOTAL"
echo "  Successful (2xx): $OK"
echo "  Failed          : $FAIL"
echo "  Success rate    : $(echo "scale=2; $OK * 100 / $TOTAL" | bc 2>/dev/null || echo "N/A")%"
echo ""

if [ "$FAIL" -gt 0 ]; then
  echo "  First failure   : iter $FIRST_FAIL_ITER at $FIRST_FAIL_TS"
  echo ""
  echo "  Failure details:"
  for fl in "${FAIL_LOG[@]}"; do
    echo "    • $fl"
  done
  echo ""

  # Check if server restarts happened
  RESTART_COUNT=$(grep -c "SERVER_DOWN" "$LOG" 2>/dev/null || echo "0")
  if [ "$RESTART_COUNT" -gt 0 ]; then
    echo "  Server restarts : $RESTART_COUNT"
  fi
else
  echo "  ✓ Zero failures — no server restarts needed."
fi

echo ""

# Server uptime
SERVER_START_TS=$(head -1 "$LOG" 2>/dev/null | grep -oE '[0-9]{2}:[0-9]{2}:[0-9]{2}' || echo "??")
echo "  Server start    : ~$SERVER_START_TS"
echo "  Raw log         : $LOG"
echo "  Error log       : $ERR"
echo "  Server log      : /tmp/cypher_soak_server.log"
echo ""
echo "═══════════════════════════════════════════════════════════════════════"

# Exit code
if [ "$FAIL" -gt 0 ]; then
  exit 1
fi
exit 0
