#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════════
# CYPHER65 War Room · 1-command installer
#   curl -sSL https://raw.githubusercontent.com/0xjc65eth/cypher65-war-room/master/install.sh | bash
#
# What it does:
#   1. Checks prerequisites (docker / docker compose).
#   2. Asks for the Tailscale auth key + local subnet (both optional —
#      empty answers install the app-only stack).
#   3. Writes a .env from your answers.
#   4. Builds and starts the stack (with --profile tailscale when a key is given).
#   5. Prints the dashboard URL + next steps.
#
# Idempotent: re-running keeps your existing .env values as defaults.
# ═══════════════════════════════════════════════════════════════════════
set -euo pipefail

CYAN='\033[0;36m'; GREEN='\033[0;32m'; YELLOW='\033[0;33m'; RED='\033[0;31m'; NC='\033[0m'
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"

say()  { echo -e "${CYAN}▸${NC} $*"; }
ok()   { echo -e "${GREEN}✓${NC} $*"; }
warn() { echo -e "${YELLOW}⚠${NC} $*"; }
die()  { echo -e "${RED}✗${NC} $*"; exit 1; }

echo -e "${CYAN}"
cat <<'EOF'
  ⚡ CYPHER65 WAR ROOM — installer
  Real-time Bitcoin mining operations dashboard
EOF
echo -e "${NC}"

# ── 1. Prerequisites ─────────────────────────────────────────────────────
command -v docker >/dev/null 2>&1 || die "Docker not found. Install it first: https://docs.docker.com/engine/install/"
docker compose version >/dev/null 2>&1 || die "docker compose plugin not found (v2 required)."
ok "Docker + compose detected: $(docker --version)"

# ── 2. .env seed (preserve existing values) ──────────────────────────────
touch .env
load_env() { # load_env KEY [default]
  local key="$1" default="${2:-}"
  local val
  val=$(grep -E "^${key}=" .env | tail -1 | cut -d= -f2-) || true
  echo "${val:-$default}"
}
write_env() { # write_env KEY VALUE  (keeps first occurrence, appends if missing)
  local key="$1" value="$2"
  if grep -qE "^${key}=" .env; then
    sed -i.bak -E "s|^${key}=.*|${key}=${value}|" .env && rm -f .env.bak
  else
    printf '\n%s=%s\n' "$key" "$value" >> .env
  fi
}

# ── 3. Questions ─────────────────────────────────────────────────────────
# `read -e -i` (readline with a prefilled default) requires a TTY; under piped
# stdin (CI dry-run, cron) it misbehaves. Ask with a prefill only when
# interactive, otherwise plain read.
ask() { # ask <var> <prompt> <default>
  local var="$1" prompt="$2" default="$3"
  if [[ -t 0 ]]; then
    read -r -e -i "$default" -p "$prompt" "$var"
  else
    read -r -p "$prompt" "$var"
    [[ -z "${!var:-}" ]] && eval "$var=\$default"
  fi
}

echo
say "Tailscale setup (REMOTE ACCESS) — press Enter to skip and install app-only."
ask TAILSCALE_AUTH_KEY "  Tailscale Auth Key (https://login.tailscale.com/admin/settings/keys): " "$(load_env TAILSCALE_AUTH_KEY)"
ask LOCAL_SUBNET "  Local subnet to advertise (ex: 192.168.1.0/24, empty = none): " "$(load_env LOCAL_SUBNET)"
ask RATE_LIMIT_PER_MINUTE "  RATE_LIMIT_PER_MINUTE (default 300): " "$(load_env RATE_LIMIT_PER_MINUTE 300)"

write_env TAILSCALE_AUTH_KEY "${TAILSCALE_AUTH_KEY:-}"
write_env LOCAL_SUBNET "${LOCAL_SUBNET:-}"
write_env RATE_LIMIT_PER_MINUTE "${RATE_LIMIT_PER_MINUTE:-300}"
write_env PORT "8765"
ok ".env written (secrets stay local, file is gitignored)."

# ── 4. Build + up ────────────────────────────────────────────────────────
say "Building image (first run downloads the base image — be patient)…"
docker compose build cypher65-app

PROFILE=()
if [[ -n "${TAILSCALE_AUTH_KEY:-}" ]]; then
  PROFILE=(--profile tailscale)
  say "Starting stack WITH Tailscale sidecar (remote access)…"
else
  say "Starting app-only stack…"
fi
docker compose "${PROFILE[@]}" up -d

# ── 5. Wait for boot + report ────────────────────────────────────────────
say "Waiting for the dashboard to come up…"
for i in $(seq 1 20); do
  sleep 2
  if curl -fsS --max-time 3 http://127.0.0.1:8765/api/healthz >/dev/null 2>&1; then
    ok "Server ready after ~$((i * 2))s"
    break
  fi
  [[ "$i" == 20 ]] && warn "Timed out waiting for /api/healthz — check: docker compose logs cypher65-app"
done

echo
echo -e "${GREEN}═══════════════════════════════════════════════════════════${NC}"
echo -e "${GREEN}  ✅ CYPHER65 WAR ROOM IS UP${NC}"
echo
echo -e "  🌍 Local dashboard :  http://localhost:8765"
if [[ -n "${TAILSCALE_AUTH_KEY:-}" ]]; then
  echo -e "  🛰  Remote (Tailscale): https://cypher65-${HOSTNAME:-node}.ts.net"
  echo -e "      (first remote load may take ~30s for the TLS cert)"
fi
echo
echo -e "  📌 Next steps:"
echo -e "     1. Open the dashboard and connect your wallet / add miners."
echo -e "     2. cp .env.example .env  →  set BTC_ADDRESS + WORKER_NAME (then restart)."
echo -e "     3. docker compose logs -f cypher65-app   →  follow the logs."
echo -e "     4. Upgrade: git pull && docker compose build && docker compose up -d"
echo -e "${GREEN}═══════════════════════════════════════════════════════════${NC}"
