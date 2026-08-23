#!/usr/bin/env bash
# issue-beta-trial.sh — Issue PRO trial keys for beta testers
#
# Usage:
#   ./scripts/issue-beta-trial.sh                        # 10 keys, 30 days each
#   ./scripts/issue-beta-trial.sh --count 5 --days 14    # 5 keys, 14 days each
#   ./scripts/issue-beta-trial.sh --email user@test.com  # single key for a specific user
#
# Requires: curl, jq (optional), running server on localhost:8765
# The server must have PRO_LICENSE_KEYS or LEMON_SQUEEZY_API_KEY configured,
# OR run in open mode (no licensing env) — keys are issued but gate is bypassed.

set -euo pipefail

BASE_URL="${BASE_URL:-http://localhost:8765}"
API_KEY="${API_KEY:-}"
COUNT=10
DAYS=30
EMAIL=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --count) COUNT="$2"; shift 2 ;;
    --days)  DAYS="$2";  shift 2 ;;
    --email) EMAIL="$2"; shift 2 ;;
    --url)   BASE_URL="$2"; shift 2 ;;
    --api-key) API_KEY="$2"; shift 2 ;;
    *) echo "Unknown option: $1"; exit 1 ;;
  esac
done

MONTHS=$(( (DAYS + 29) / 30 ))  # round up to months
if [[ $MONTHS -lt 1 ]]; then MONTHS=1; fi

echo "🔧 CYPHER65 Beta PRO Trial Key Issuer"
echo "   Server: $BASE_URL"
echo "   Keys:   $COUNT × ${DAYS} days (plan=pro, months=${MONTHS})"
echo ""

# Verify server is up
HTTP_CODE=$(curl -s -o /dev/null -w '%{http_code}' -m 5 "${BASE_URL}/api/healthz" 2>/dev/null || echo "000")
if [[ "$HTTP_CODE" != "200" ]]; then
  echo "❌ Server not reachable at ${BASE_URL}/api/healthz (HTTP ${HTTP_CODE})"
  echo "   Start the server first: python app.py"
  exit 1
fi
echo "✅ Server healthy"

ISSUED=0
FAILED=0

for i in $(seq 1 "$COUNT"); do
  AUTH_HEADER=""
  if [[ -n "$API_KEY" ]]; then
    AUTH_HEADER="-H 'X-API-Key: ${API_KEY}'"
  fi

  PAYLOAD="{\"plan\":\"pro\",\"months\":${MONTHS},\"source\":\"beta-trial\",\"email\":\"${EMAIL}\"}"

  RESPONSE=$(eval curl -s -X POST "${BASE_URL}/api/admin/licenses" \
    -H "'Content-Type: application/json'" \
    ${AUTH_HEADER} \
    -d "'${PAYLOAD}'" 2>/dev/null)

  KEY=$(echo "$RESPONSE" | grep -o '"license_key":"[^"]*"' | cut -d'"' -f4 2>/dev/null || echo "")

  if [[ -n "$KEY" ]]; then
    echo "   [${i}/${COUNT}] ✅ ${KEY}"
    ISSUED=$((ISSUED + 1))
  else
    ERROR=$(echo "$RESPONSE" | grep -o '"error":"[^"]*"' | cut -d'"' -f4 2>/dev/null || echo "unknown error")
    echo "   [${i}/${COUNT}] ❌ ${ERROR}"
    FAILED=$((FAILED + 1))
  fi

  # Small delay to avoid rate limiting
  sleep 0.2
done

echo ""
echo "📊 Results: ${ISSUED} issued, ${FAILED} failed"
echo ""
echo "To activate PRO for a user, they set the header:"
echo "   X-License-Key: ${KEY}"
echo ""
echo "Or append ?license=KEY to the dashboard URL."
