#!/usr/bin/env bash
# ── soak_runner.sh — minimal poll loop, no server mgmt, no cleanup traps ──
# Assumes Flask server is already running on port 8765.
# Writes results to /tmp/cypher_soak_results.log
# Designed to be run inside a tmux session so it survives agent exits.
# Usage: bash tests/soak_runner.sh

HOST="http://localhost:8765"
INTERVAL=30
ITERATIONS=120
LOG="/tmp/cypher_soak_results.log"
ERR="/tmp/cypher_soak_results.err"

echo "═══ CYPHER65 SOAK RUNNER ═══"
echo "  target  : $HOST"
echo "  interval: ${INTERVAL}s"
echo "  duration: $(( ITERATIONS * INTERVAL / 60 )) min ($ITERATIONS polls)"
echo "  log     : $LOG"

# Wait for server
for i in $(seq 1 10); do
  CODE=$(curl -s -o /dev/null -w '%{http_code}' "$HOST/" 2>/dev/null || echo "000")
  if [ "$CODE" = "200" ]; then
    echo "  Server ready (attempt $i)"
    break
  fi
  echo "  Waiting for server (attempt $i)..."
  sleep 2
done

if [ "$CODE" != "200" ]; then
  echo "[FATAL] Server not reachable after 20s."
  exit 1
fi

echo ""
echo "  ITER |   TIMESTAMP    |  /  STATUS | SNAPSHOT | WORKER_DATA | NOTES"
echo "═══════════════════════════════════════════════════════════════════════"

> "$LOG"
> "$ERR"
TOTAL=$ITERATIONS
OK=0
FAIL=0

for i in $(seq 1 $ITERATIONS); do
  TS=$(date '+%H:%M:%S')
  NOTES=""

  HTTP_MAIN=$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 "$HOST/" 2>>"$ERR" || echo "000")
  SNAPSHOT_RAW=$(curl -s --max-time 10 "$HOST/api/snapshot" 2>>"$ERR" || true)

  WORKER_HAS_DATA="N"
  SNAPSHOT_STATUS="000"
  if [ -n "$SNAPSHOT_RAW" ]; then
    SNAPSHOT_STATUS="200"
    WORKER_HAS_DATA=$(echo "$SNAPSHOT_RAW" | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    w = d.get('worker') or {}
    hr = w.get('hashrate', 0)
    bd = w.get('bestDifficulty') or ''
    print('Y' if hr else 'N')
except Exception:
    print('N')
" 2>/dev/null || echo "N")
  fi

  if [ "$HTTP_MAIN" = "200" ] && [ "$SNAPSHOT_STATUS" = "200" ]; then
    OK=$((OK + 1))
  else
    FAIL=$((FAIL + 1))
    if [ "$HTTP_MAIN" != "200" ]; then NOTES="MAIN=$HTTP_MAIN"; fi
    if [ "$SNAPSHOT_STATUS" != "200" ]; then
      [ -n "$NOTES" ] && NOTES="$NOTES "
      NOTES="${NOTES}SNAP=$SNAPSHOT_STATUS"
    fi
  fi

  printf "  %4d | %s |   %s    |    %s    |     %s     | %s\n" \
    "$i" "$TS" "$HTTP_MAIN" "$SNAPSHOT_STATUS" "$WORKER_HAS_DATA" "$NOTES" >> "$LOG"

  # Every 20 iterations, log a status line with live stats
  if [ $((i % 20)) -eq 0 ]; then
    PCT=$(echo "scale=1; $OK * 100 / $i" | bc)
    echo "  [checkpoint] iter=$i/$ITERATIONS  ok=$OK  fail=$FAIL  rate=${PCT}%"
  fi

  [ $i -lt $ITERATIONS ] && sleep "$INTERVAL"
done

# ── Final report ──
echo ""
echo "═══════════════════════════════════════════════════════════════════════"
echo "  SOAK TEST COMPLETE"
echo "═══════════════════════════════════════════════════════════════════════"
echo "  Duration     : $(( ITERATIONS * INTERVAL / 60 )) min ($ITERATIONS polls)"
echo "  Successful   : $OK"
echo "  Failed       : $FAIL"
PCT=$(echo "scale=2; $OK * 100 / $TOTAL" | bc)
echo "  Success rate : ${PCT}%"
if [ "$FAIL" -gt 0 ]; then
  echo "  See $LOG for failure details"
fi
echo "═══════════════════════════════════════════════════════════════════════"
echo "$OK/$TOTAL ok, ${PCT}%" >> "$LOG"
