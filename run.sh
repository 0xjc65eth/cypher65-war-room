#!/usr/bin/env bash
# run.sh — Cypher65 War Room local launcher.
#
#   ./run.sh          local dev via venv (fast, no Docker required)
#   ./run.sh --docker run the Docker Compose stack (port 8765)
#
# The venv path is the default and the documented local-dev flow. The
# --docker path mirrors the production deployment (Dockerfile + compose)
# so what you run locally is byte-for-byte what ships.
set -euo pipefail
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$DIR"

GREEN='\033[0;32m'; CYAN='\033[0;36m'; RED='\033[0;31m'; NC='\033[0m'

usage() {
  echo "Usage: $0 [--docker]"
  echo "  (default)  Local dev via venv — fast, no Docker needed"
  echo "  --docker   Run inside the Docker Compose stack (http://localhost:8765)"
}

# ── Docker path ──────────────────────────────────────────────────────────
if [[ "${1:-}" == "--docker" ]]; then
  if ! command -v docker >/dev/null 2>&1; then
    echo -e "${RED}❌ Docker not found. Install Docker + Compose v2 first.${NC}"
    exit 1
  fi
  if [ ! -f .env ]; then
    echo -e "${CYAN}🔧 Creating default .env...${NC}"
    cat > .env <<'EOL'
PORT=8765
# DEBUG_MOCK is intentionally NOT set: the project premise is honest
# telemetry (no invented devices). Set DEBUG_MOCK=1 only for local demos.
# DEBUG_MOCK=1
# INFLUXDB_URL=http://influxdb:8086
# TAILSCALE_AUTH_KEY=tskey-xxxx
# TAILSCALE_ROUTES=192.168.0.0/24
EOL
  fi
  echo -e "${GREEN}📦 Building and starting containers...${NC}"
  docker compose up --build -d
  echo -e "${CYAN}⏳ Waiting for /api/healthz...${NC}"
  for i in $(seq 1 30); do
    if curl -fsS http://localhost:8765/api/healthz >/dev/null 2>&1; then
      echo -e "${GREEN}✅ System ready!${NC}"
      echo "🌍 Access:   http://localhost:8765"
      echo "📊 Logs:     docker compose logs -f"
      echo "🛑 Stop:     docker compose down"
      exit 0
    fi
    sleep 2
  done
  echo -e "${RED}❌ Timed out waiting for http://localhost:8765/api/healthz${NC}" >&2
  docker compose logs --tail 30 >&2
  exit 1
fi

if [[ "${1:-}" != "" ]]; then
  usage; exit 1
fi

# ── Local venv path (default) ─────────────────────────────────────────────
if [ ! -d .venv ]; then
  echo "▶ creating venv…"
  python3 -m venv .venv
fi
source .venv/bin/activate
pip install -q -r requirements.txt
echo "⇢ starting cypher65 war room"
exec python app.py
