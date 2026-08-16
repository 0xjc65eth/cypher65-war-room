#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════════════
# CYPHER65 // WAR ROOM — AGENT INSTALLER (1 line, zero dependencies)
# ═══════════════════════════════════════════════════════════════════════════
# Installs the LOCAL agent on the user's home network machine (macOS /
# Linux / Raspberry Pi). The agent connects OUT to the cloud dashboard — no
# open ports, NAT/CGNAT safe — and pushes miner telemetry.
#
# Usage (copy-paste from the dashboard → Fleet → CONNECT AGENT — the panel
# prints this exact command with YOUR server + token filled in):
#   curl -sSL https://SEU-APP.onrender.com/agent/install.sh \
#     | CYPHER65_SERVER_URL=https://SEU-APP.onrender.com \
#       CYPHER65_AGENT_TOKEN=XXXX bash
#
# Requires: python3 (ships with macOS/Linux/Raspberry Pi OS). No pip, no
# Docker. The agent is 100% stdlib.
# ═══════════════════════════════════════════════════════════════════════════
set -euo pipefail

SERVER_URL="${CYPHER65_SERVER_URL:-}"

TOKEN="${CYPHER65_AGENT_TOKEN:-}"
POLL="${CYPHER65_POLL_INTERVAL:-30}"
INSTALL_DIR="${CYPHER65_AGENT_DIR:-$HOME/.cypher65-agent}"

log() { printf '\033[1;36m[cypher65]\033[0m %s\n' "$*"; }
fail() { printf '\033[1;31m[cypher65] ERROR:\033[0m %s\n' "$*" >&2; exit 1; }

# ── 1 · Validate python3 ─────────────────────────────────────────────────
command -v python3 >/dev/null 2>&1 || fail "python3 not found — install it or use the Docker option"
PY=python3

# ── 2 · Server URL (required) ────────────────────────────────────────────
if [ -z "$SERVER_URL" ]; then
  # Interactive fallback only works when run from a file; under curl|bash
  # stdin is the exhausted pipe, so read would EOF and set -e would abort.
  if [ -t 0 ]; then
    log "CYPHER65_SERVER_URL not set."
    read -r -p "   Dashboard URL (ex: https://war-room.onrender.com): " SERVER_URL
  else
    fail "CYPHER65_SERVER_URL required — the dashboard prints a ready-to-paste command"
  fi
fi
SERVER_URL="${SERVER_URL%/}"
[ -n "$SERVER_URL" ] || fail "dashboard URL required"

# ── 3 · Token (required) ─────────────────────────────────────────────────
if [ -z "$TOKEN" ]; then
  if [ -t 0 ]; then
    log "CYPHER65_AGENT_TOKEN not set."
    log "Generate it in the dashboard → Fleet → CONNECT AGENT, then paste it:"
    read -r -p "   Agent token: " TOKEN
  else
    fail "CYPHER65_AGENT_TOKEN required — the dashboard prints a ready-to-paste command"
  fi
fi
[ -n "$TOKEN" ] || fail "agent token required"

# ── 4 · Download the agent (stdlib-only, from the dashboard server) ──────
mkdir -p "$INSTALL_DIR"
log "downloading agent from ${SERVER_URL}..."
curl -fsSL "$SERVER_URL/agent/agent.py" -o "$INSTALL_DIR/agent.py" \
  || fail "could not download agent.py from $SERVER_URL (check URL)"

# ── 5 · Persist config (env file read by agent.py) ───────────────────────
cat > "$INSTALL_DIR/agent.env" <<EOF
CYPHER65_SERVER_URL=$SERVER_URL
CYPHER65_AGENT_TOKEN=$TOKEN
CYPHER65_POLL_INTERVAL=$POLL
EOF
chmod 600 "$INSTALL_DIR/agent.env"

# ── 6 · Install as a background service ──────────────────────────────────
# Prefer launchd (macOS) / systemd (Linux); fall back to a nohup loop.
IS_MAC=0
[ "$(uname -s)" = "Darwin" ] && IS_MAC=1

if [ "$IS_MAC" = "1" ] && command -v launchctl >/dev/null 2>&1; then
  LABEL="com.cypher65.agent"
  PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
  mkdir -p "$(dirname "$PLIST")"
  cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>$PY</string>
    <string>$INSTALL_DIR/agent.py</string>
  </array>
  <key>EnvironmentVariables</key>
  <dict>
    <key>CYPHER65_SERVER_URL</key><string>$SERVER_URL</string>
    <key>CYPHER65_AGENT_TOKEN</key><string>$TOKEN</string>
    <key>CYPHER65_POLL_INTERVAL</key><string>$POLL</string>
  </dict>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>$INSTALL_DIR/agent.log</string>
  <key>StandardErrorPath</key><string>$INSTALL_DIR/agent.log</string>
</dict>
</plist>
EOF
  chmod 600 "$PLIST"
  launchctl unload "$PLIST" >/dev/null 2>&1 || true
  launchctl load "$PLIST" || fail "launchctl load failed"
  log "installed as macOS service ($LABEL) — logs: $INSTALL_DIR/agent.log"

elif command -v systemctl >/dev/null 2>&1 && [ -d /run/systemd/system ]; then
  UNIT_DIR="$HOME/.config/systemd/user"
  mkdir -p "$UNIT_DIR"
  UNIT="$UNIT_DIR/cypher65-agent.service"
  cat > "$UNIT" <<EOF
[Unit]
Description=CYPHER65 local agent
After=network-online.target

[Service]
ExecStart=$PY $INSTALL_DIR/agent.py
Environment=CYPHER65_SERVER_URL=$SERVER_URL
Environment=CYPHER65_AGENT_TOKEN=$TOKEN
Environment=CYPHER65_POLL_INTERVAL=$POLL
Restart=always
RestartSec=10

[Install]
WantedBy=default.target
EOF
  chmod 600 "$UNIT"
  systemctl --user daemon-reload
  # enable-linger: user services only start at boot for a logged-in session.
  # A headless Pi/NAS must run the agent WITHOUT anyone logged in — linger
  # makes systemd start it at boot regardless. Best-effort (may need sudo).
  loginctl enable-linger "$(whoami)" >/dev/null 2>&1 || sudo -n loginctl enable-linger "$(whoami)" >/dev/null 2>&1 || true
  systemctl --user enable --now cypher65-agent.service || fail "systemctl enable failed"
  log "installed as systemd user service (boot-safe via linger) — logs: journalctl --user -u cypher65-agent"

else
  # Fallback: nohup loop (works anywhere, incl. Raspberry Pi without systemd)
  cat > "$INSTALL_DIR/run.sh" <<EOF
#!/usr/bin/env bash
cd "$INSTALL_DIR"
export CYPHER65_SERVER_URL="$SERVER_URL"
export CYPHER65_AGENT_TOKEN="$TOKEN"
export CYPHER65_POLL_INTERVAL="$POLL"
while true; do
  "$PY" agent.py >> agent.log 2>&1
  sleep 10
done
EOF
  chmod +x "$INSTALL_DIR/run.sh"
  pkill -f "$INSTALL_DIR/run.sh" >/dev/null 2>&1 || true
  nohup "$INSTALL_DIR/run.sh" >/dev/null 2>&1 &
  # Survive reboots: a @reboot crontab entry re-launches the loop. (Cron is
  # the one supervisor present on ~every Unix — Pi OS, Synology, macOS.)
  CRON_LINE="@reboot $INSTALL_DIR/run.sh >> $INSTALL_DIR/agent.log 2>&1"
  # -F: fixed string, not regex — the install dir has dots (.cypher65-agent)
  # that would act as regex wildcards and could strip unrelated cron lines.
  ( crontab -l 2>/dev/null | grep -vF "$INSTALL_DIR/run.sh" ; echo "$CRON_LINE" ) | crontab - || true
  log "started with nohup loop (auto-restart on reboot via @reboot cron) — logs: $INSTALL_DIR/agent.log"
fi

log "✅ AGENT INSTALLED & RUNNING"
log "   Server : $SERVER_URL"
log "   Poll   : every ${POLL}s (telemetry push)"
log "   Dir    : $INSTALL_DIR"
log "   Reinstall/restart: re-run this same command."
log "   The fleet will appear in the dashboard within ~1 min."
