"""
CYPHER65 War Room — Configuration
=================================
Centralized configuration management.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env if present
load_dotenv()

# ── Core Settings ─────────────────────────────────────────────────────
BTC_ADDRESS = os.environ.get("BTC_ADDRESS", "")
# P4 (#250): fixed address that receives PREMIUM payments in Bitcoin —
# STRICTLY SEPARATE from BTC_ADDRESS (data wallet used by services/polling.py
# for Parasite API fetches). Never conflate the two roles.
PAYMENT_BTC_ADDRESS = os.environ.get("PAYMENT_BTC_ADDRESS", "")
WORKER_NAME = os.environ.get("WORKER_NAME", "")
PARASITE_API = os.environ.get("PARASITE_API", "https://parasite.space/api")
MEMPOOL_API = os.environ.get("MEMPOOL_API", "https://mempool.space/api")
DATA_DIR = Path(__file__).parent / "data"
# Read DB_PATH from the environment at IMPORT time so test suites that set
# os.environ["DB_PATH"] before importing `app` redirect every query to a
# scratch DB (the Core registry is constructed at module level with DB_PATH).
DB_PATH = os.environ.get("DB_PATH", "data/war_room.sqlite")

POLL_INTERVAL = int(os.environ.get("POLL_INTERVAL", 15))
# NOTE: POLL_WORKER_POOL_SIZE is read directly by services/user_polling.py
# (same pattern as its hardcoded POLL_INTERVAL) — NOT from config, to keep
# the module self-contained for tests. P1 Phase 2: ALL connected sessions
# share a fixed pool (default 8 threads, env POLL_WORKER_POOL_SIZE).
PORT = int(os.environ.get("PORT", 8765))
RATE_LIMIT_PER_MINUTE = int(
    os.environ.get("RATE_LIMIT_PER_MINUTE", 300)
)  # E2E overrides to 1000
# Stricter per-IP budget for the auth endpoints (login/register/refresh/
# logout) — credential brute-force protection. Tight budget, separate store.
AUTH_RATE_LIMIT_PER_MINUTE = int(os.environ.get("AUTH_RATE_LIMIT_PER_MINUTE", 10))

# Optional security
API_KEY = os.environ.get("API_KEY")
DEBUG_MOCK = os.environ.get("DEBUG_MOCK") == "1"

# ── Multi-tenant API keys (Fase 4 · B1) ──────────────────────────────
# JSON dict mapping tenant_id -> api_key, e.g. '{"default":"k1","acme":"k2"}'.
# When set, /api/auth/login validates against these and issues JWTs with
# sub=tenant_id, activating the axe_fleet tenant isolation that already
# exists in axe_fleet/routes.py + axe_fleet/registry.py.
# Falls back to the legacy single API_KEY (tenant "default").
TENANT_API_KEYS = os.environ.get("TENANT_API_KEYS", "")

DATA_DIR.mkdir(exist_ok=True)

# ── Cloud-deployment detection (SaaS fleet topology) ────────────────────
# A dashboard hosted in the cloud (Render, Fly, Railway, etc.) can NEVER
# route to RFC1918 private LAN addresses (192.168.x.x / 10.x.x.x) where the
# user's miners live — only a LOCAL agent on the user's network can reach
# them. Render sets RENDER=true + RENDER_SERVICE_ID automatically; CLOUD_MODE
# covers other PaaS. Read at CALL time so tests can monkeypatch the env
# without re-importing this module.
_CLOUD_ENV_FLAGS = ("RENDER", "RENDER_SERVICE_ID", "RENDER_INSTANCE_ID", "CLOUD_MODE")


def is_cloud_deploy() -> bool:
    """True when this process is deployed on a PaaS cloud (Render etc.).

    Used by the axe-fleet onboarding to switch the UX to the local-agent
    model: subnet scan and manual private-IP adds are physically impossible
    from a cloud host, so they are blocked/redirected instead of letting the
    user chase an unreachable miner forever.
    """
    for flag in _CLOUD_ENV_FLAGS:
        val = os.environ.get(flag, "")
        if val and str(val).strip().lower() not in ("", "0", "false", "no"):
            return True
    return False


# ── Wallet source tracking ────────────────────────────────────────────
WALLET_ADDRESS_SOURCE = os.environ.get("WALLET_SOURCE", "none")


def get_config_summary() -> dict:
    """Return a safe summary of current configuration (no secrets)."""
    return {
        "btc_address_set": bool(BTC_ADDRESS),
        "worker_name": WORKER_NAME or "default",
        "poll_interval": POLL_INTERVAL,
        "port": PORT,
        "api_key_protected": bool(API_KEY),
        "debug_mock_enabled": DEBUG_MOCK,
        "db_path": DB_PATH,
    }
