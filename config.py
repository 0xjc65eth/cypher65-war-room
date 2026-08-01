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
WORKER_NAME = os.environ.get("WORKER_NAME", "")
PARASITE_API = os.environ.get("PARASITE_API", "https://parasite.space/api")
MEMPOOL_API = os.environ.get("MEMPOOL_API", "https://mempool.space/api")
DATA_DIR = Path(__file__).parent / "data"
DB_PATH = "data/war_room.sqlite"

POLL_INTERVAL = int(os.environ.get("POLL_INTERVAL", 15))
PORT = int(os.environ.get("PORT", 8765))
RATE_LIMIT_PER_MINUTE = int(os.environ.get("RATE_LIMIT_PER_MINUTE", 300))  # keep in sync with app.py; E2E overrides to 1000

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