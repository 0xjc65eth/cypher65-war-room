#!/usr/bin/env bash
# ── soak_quick.sh — short soak test (5 min / 10 iters) for quick CI ──
# Assumes Flask server is already running on port 8765.
# This is a minimal wrapper around the soak_runner logic with fewer iterations.
#
# Usage:
#   bash tests/soak_quick.sh          # default: 10 iterations at 30s
#   QUICK_ITERS=5  bash tests/soak_quick.sh   # override iterations
#   QUICK_DELAY=10 bash tests/soak_quick.sh   # override interval (s)

set -o pipefail

HOST="http://localhost:8765"
INTERVAL="${QUICK_DELAY:-30}"
ITERATIONS="${QUICK_ITERS:-10}"
LOG="/tmp/cypher_soak_quick.log"
ERR="/tmp/cypher_soak_quick.err"

echo "═══ CYPHER65 SOAK QUICK ═══"
echo "  target   : $HOST"
echo "  interval : ${INTERVAL}s"
echo "  duration : $(( ITERATIONS * INTERVAL / 60 )) min ($ITERATIONS polls)"
echo "  log      : $LOG"

# Verify server is reachable
CODE=$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 "$HOST/" 2>/dev/null || echo "000")
if [ "$CODE" != "200" ]; then
  echo "[FATAL] Server not reachable at $HOST (HTTP $CODE)"
  exit 1
fi
echo "  Server HTTP 200 — starting poll loop."
echo ""

echo "  ITER |   TIMESTAMP    |  /  STATUS | SNAPSHOT | WORKER | NOTES"
echo "═══════════════════════════════════════════════════════════════════════"

> "$LOG"
> "$ERR"
OK=0
FAIL=0

for ((i=1; i<=ITERATIONS; i++)); do
  TS=$(date '+%H:%M:%S')
  NOTES=""

  HTTP_MAIN=$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 "$HOST/" 2>>"$ERR" || echo "000")
  SNAPSHOT_RAW=$(curl -s --max-time 10 "$HOST/api/snapshot" 2>>"$ERR" || true)

  WORKER_DATA="N"
  SNAP_CODE="000"
  if [ -n "$SNAPSHOT_RAW" ]; then
    SNAP_CODE="200"
    WORKER_DATA=$(echo "$SNAPSHOT_RAW" | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    w = d.get('worker') or {}
    print('Y' if w.get('hashrate') else 'N')
except Exception:
    print('N')
" 2>/dev/null || echo "N")
  fi

  if [ "$HTTP_MAIN" = "200" ] && [ "$SNAP_CODE" = "200" ]; then
    OK=$((OK + 1))
  else
    FAIL=$((FAIL + 1))
    [ "$HTTP_MAIN" != "200" ] && NOTES="MAIN=$HTTP_MAIN"
    [ "$SNAP_CODE" != "200" ] && NOTES="$NOTES SNAP=$SNAP_CODE"
  fi

  printf "  %4d | %s |   %s    |    %s    |   %s   | %s\n" \
    "$i" "$TS" "$HTTP_MAIN" "$SNAP_CODE" "$WORKER_DATA" "$NOTES" | tee -a "$LOG"

  [ $i -lt $ITERATIONS ] && sleep "$INTERVAL"
done

# ── Final report ──
echo ""
echo "═══════════════════════════════════════════════════════════════════════"
echo "  SOAK QUICK — COMPLETE"
echo "═══════════════════════════════════════════════════════════════════════"
echo "  Duration      : $(( ITERATIONS * INTERVAL / 60 )) min ($ITERATIONS polls at ${INTERVAL}s)"
echo "  Successful    : $OK"
echo "  Failed        : $FAIL"
PCT=$(echo "scale=1; $OK * 100 / $ITERATIONS" | bc 2>/dev/null || echo "0")
echo "  Success rate  : ${PCT}%"
echo "  Log file      : $LOG"

if [ "$FAIL" -gt 0 ]; then
  echo ""
  echo "  ⚠ FAILURES DETECTED — check $LOG for details"
  exit 1
fi
exit 0
