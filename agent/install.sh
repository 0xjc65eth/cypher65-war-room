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
# Requires: python3 installed on the host. No pip, no
# Docker. The agent is 100% stdlib.
# ═══════════════════════════════════════════════════════════════════════════
set -euo pipefail

SERVER_URL="${CYPHER65_SERVER_URL:-}"

TOKEN="${CYPHER65_AGENT_TOKEN:-}"
POLL="${CYPHER65_POLL_INTERVAL:-30}"
SCAN_CIDR="${CYPHER65_SCAN_CIDR:-}"
DEVICES="${CYPHER65_DEVICES:-}"
INSTALL_DIR="${CYPHER65_AGENT_DIR:-$HOME/.cypher65-agent}"

log() { printf '\033[1;36m[cypher65]\033[0m %s\n' "$*"; }
fail() { printf '\033[1;31m[cypher65] ERROR:\033[0m %s\n' "$*" >&2; exit 1; }

# ── 1 · Validate python3 ─────────────────────────────────────────────────
command -v python3 >/dev/null 2>&1 || fail "python3 not found — install it or use the Docker option"
PY="$(command -v python3)"

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

# Serialize values as data for each service format. In particular, shell
# quoting is not XML or systemd quoting; tokens/URLs/paths may contain
# characters meaningful to those formats. All generated files are private
# from creation, including the fallback runner that contains the token.
umask 077
export CYPHER65_SERVER_URL="$SERVER_URL" CYPHER65_AGENT_TOKEN="$TOKEN"
export CYPHER65_POLL_INTERVAL="$POLL" CYPHER65_SCAN_CIDR="$SCAN_CIDR"
export CYPHER65_DEVICES="$DEVICES"
write_config() {
  "$PY" - "$1" "$2" "$INSTALL_DIR" "$PY" <<'PY'
import os
from pathlib import Path
import plistlib
import shlex
import sys

kind, destination, install_dir, python = sys.argv[1:]
config = {
    key: os.environ[key]
    for key in (
        "CYPHER65_SERVER_URL", "CYPHER65_AGENT_TOKEN", "CYPHER65_POLL_INTERVAL",
        "CYPHER65_SCAN_CIDR", "CYPHER65_DEVICES",
    )
}
agent = str(Path(install_dir) / "agent.py")
log = str(Path(install_dir) / "agent.log")


def unit_quote(value, exec_arg=False):
    value = value.replace("%", "%%").replace("\\", "\\\\")
    value = value.replace('"', '\\"').replace("\n", "\\n").replace("\r", "\\r")
    value = value.replace("\t", "\\t")
    if exec_arg:
        value = value.replace("$", "$$")
    return '"' + value + '"'


def write_private(payload):
    # Reinstalling must also repair older world-readable runner/config files
    # before new credentials are written, not just rely on the creation umask.
    descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "wb") as output:
        os.fchmod(output.fileno(), 0o600)
        output.write(payload)


if kind == "launchd":
    write_private(plistlib.dumps({
            "Label": "com.cypher65.agent",
            "ProgramArguments": [python, agent],
            "EnvironmentVariables": config,
            "RunAtLoad": True,
            "KeepAlive": True,
            "StandardOutPath": log,
            "StandardErrorPath": log,
    }))
else:
    if kind == "env":
        content = "".join(f"{key}={shlex.quote(value)}\n" for key, value in config.items())
    elif kind == "systemd":
        content = (
            "[Unit]\nDescription=CYPHER65 local agent\nAfter=network-online.target\n\n"
            "[Service]\nExecStart=" + unit_quote(python, True) + " " + unit_quote(agent, True) + "\n"
            + "".join("Environment=" + unit_quote(key + "=" + value) + "\n" for key, value in config.items())
            + "Restart=always\nRestartSec=10\n\n[Install]\nWantedBy=default.target\n"
        )
    elif kind == "fallback":
        content = (
            "#!/usr/bin/env bash\n"
            + "".join(f"export {key}={shlex.quote(value)}\n" for key, value in config.items())
            + "while true; do\n  " + shlex.quote(python) + " " + shlex.quote(agent)
            + " >> " + shlex.quote(log) + " 2>&1\n  sleep 10\ndone\n"
        )
    elif kind == "cron":
        # Cron treats even a quoted % as a newline unless it is escaped.
        content = "@reboot " + shlex.quote(str(Path(install_dir) / "run.sh"))
        content += " >> " + shlex.quote(log) + " 2>&1\n"
        content = content.replace("%", "\\%")
    else:
        raise ValueError("unsupported config format")
    write_private(content.encode("utf-8"))
PY
}

# ── 4 · Download the agent (stdlib-only, from the dashboard server) ──────
mkdir -p "$INSTALL_DIR"
log "downloading agent from ${SERVER_URL}..."
curl -fsSL "$SERVER_URL/agent/agent.py" -o "$INSTALL_DIR/agent.py" \
  || fail "could not download agent.py from $SERVER_URL (check URL)"

# ── 5 · Persist config (shell-quoted backup; services receive it below) ──
write_config env "$INSTALL_DIR/agent.env"
chmod 600 "$INSTALL_DIR/agent.env"

# ── 6 · Install as a background service ──────────────────────────────────
# Prefer launchd (macOS) / systemd (Linux); fall back to a nohup loop.
IS_MAC=0
[ "$(uname -s)" = "Darwin" ] && IS_MAC=1

if [ "$IS_MAC" = "1" ] && command -v launchctl >/dev/null 2>&1; then
  LABEL="com.cypher65.agent"
  PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
  mkdir -p "$(dirname "$PLIST")"
  write_config launchd "$PLIST"
  chmod 600 "$PLIST"
  launchctl unload "$PLIST" >/dev/null 2>&1 || true
  launchctl load "$PLIST" || fail "launchctl load failed"
  log "installed as macOS service ($LABEL) — logs: $INSTALL_DIR/agent.log"

elif command -v systemctl >/dev/null 2>&1 && [ -d /run/systemd/system ]; then
  UNIT_DIR="$HOME/.config/systemd/user"
  mkdir -p "$UNIT_DIR"
  UNIT="$UNIT_DIR/cypher65-agent.service"
  write_config systemd "$UNIT"
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
  write_config fallback "$INSTALL_DIR/run.sh"
  chmod 700 "$INSTALL_DIR/run.sh"
  pkill -f "$INSTALL_DIR/run.sh" >/dev/null 2>&1 || true
  nohup "$INSTALL_DIR/run.sh" >/dev/null 2>&1 &
  # Survive reboots: a @reboot crontab entry re-launches the loop. (Cron is
  # the one supervisor present on ~every Unix — Pi OS, Synology, macOS.)
  write_config cron "$INSTALL_DIR/agent.cron"
  CRON_LINE="$(cat "$INSTALL_DIR/agent.cron")"
  # -F: fixed string, not regex — the install dir has dots (.cypher65-agent)
  # that would act as regex wildcards and could strip unrelated cron lines.
  ( crontab -l 2>/dev/null | grep -vF -e "$INSTALL_DIR/run.sh" -e "$CRON_LINE" ; echo "$CRON_LINE" ) | crontab - || true
  log "started with nohup loop (auto-restart on reboot via @reboot cron) — logs: $INSTALL_DIR/agent.log"
fi

log "✅ AGENT INSTALLED & RUNNING"
log "   Server : $SERVER_URL"
log "   Poll   : every ${POLL}s (telemetry push)"
log "   Dir    : $INSTALL_DIR"
log "   Reinstall/restart: re-run this same command."
log "   The fleet will appear in the dashboard within ~1 min."
