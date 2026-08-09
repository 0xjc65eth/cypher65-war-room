"""
CYPHER65 — Settings service
============================
User-tunable settings: cost model, currency, alert thresholds.
Persisted to SQLite via services/db.py.
"""

import time
import logging
from typing import Optional

from services.db import get_db

log = logging.getLogger("cypher65.settings")

DEFAULT_SETTINGS = {
    "cost_mode": "none",
    "rental_usd_per_th_day": "0.00",
    "power_watts": "3000",
    "power_kwh_usd": "0.10",
    "btc_block_reward": "3.125",
    "btc_avg_tx_fee": "0.05",
    "pool_fee_pct": "1.5",
    "orphan_rate_pct": "0.5",
    "active_currency": "USD",
    "active_fiat": "USD",
    "stale_share_minutes": "5",
    "hashrate_drop_pct": "50",
    "webhook_url": "",
    "webhook_min_severity": "WARN",
    "show_test_alerts": "0",
    "mrr_api_key": "",
    "mrr_api_secret": "",
    "braiins_api_key": "",
}

# Global (operator / self-host) settings cache — the `settings` table.
_settings_cache = None
# Per-tenant settings cache — the `tenant_settings` table (tenant_id → dict).
# Multi-tenant deployments (1000+ users): every tenant has its OWN settings
# and credentials; a named tenant NEVER reads the operator's global rows.
_tenant_settings_cache: dict = {}


def _ensure_tenant_settings_table():
    """Idempotent CREATE TABLE for per-tenant settings. Called lazily so tests
    that exercise services.settings without booting app.init_db still work."""
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute(
            """CREATE TABLE IF NOT EXISTS tenant_settings (
                tenant_id TEXT NOT NULL,
                key TEXT NOT NULL,
                value TEXT NOT NULL DEFAULT '',
                updated_ts INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (tenant_id, key)
            )"""
        )
        conn.commit()
        conn.close()
    except Exception as e:
        log.warning("[settings] tenant_settings table ensure failed: %s", e)


def is_default_tenant(tenant_id: str = "") -> bool:
    """The 'default'/'' tenant is the operator's own self-host deployment."""
    return not tenant_id or tenant_id == "default"


def load_settings(tenant_id: str = ""):
    """Return a dict of key->value (str), seeded with defaults for any missing key.

    Tenant-aware:
      - default / '' (operator self-host): reads the GLOBAL `settings` table
        (cached at module level, refreshed on save) — exactly the legacy
        behavior. Env-var credential overrides still apply via the resolvers.
      - named tenant (multi-user deployment): reads ONLY that tenant's rows
        from `tenant_settings` (per-tenant cache). Never touches global rows,
        so a user can never see or inherit the operator's keys/settings.
    """
    if is_default_tenant(tenant_id):
        global _settings_cache
        if _settings_cache is not None:
            return _settings_cache
        out = dict(DEFAULT_SETTINGS)
        try:
            conn = get_db()
            c = conn.cursor()
            for k in DEFAULT_SETTINGS.keys():
                c.execute("SELECT value FROM settings WHERE key=?", (k,))
                r = c.fetchone()
                if r is not None and r["value"] is not None:
                    out[k] = r["value"]
            conn.close()
        except Exception as e:
            log.warning("[settings load] error: %s", e)
        _settings_cache = out
        return out

    # Named tenant — isolated settings.
    cached = _tenant_settings_cache.get(tenant_id)
    if cached is not None:
        return cached
    out = dict(DEFAULT_SETTINGS)
    try:
        _ensure_tenant_settings_table()
        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT key, value FROM tenant_settings WHERE tenant_id=?", (tenant_id,))
        for row in c.fetchall():
            if row["value"] is not None:
                out[row["key"]] = row["value"]
        conn.close()
    except Exception as e:
        log.warning("[settings load %s] error: %s", tenant_id, e)
    _tenant_settings_cache[tenant_id] = out
    return out


def save_setting(key, value, tenant_id: str = ""):
    """Persist a setting and refresh the in-memory cache.

    Tenant-aware (mirrors load_settings):
      - default tenant → global `settings` table (legacy behavior).
      - named tenant   → that tenant's `tenant_settings` rows only.
    Internal keys (prefixed with '_') bypass the DEFAULT_SETTINGS whitelist.
    """
    if not key.startswith('_') and key not in DEFAULT_SETTINGS:
        raise KeyError(f"unknown setting key: {key}")
    if is_default_tenant(tenant_id):
        global _settings_cache
        try:
            conn = get_db()
            c = conn.cursor()
            c.execute(
                "INSERT INTO settings(key,value,updated_ts) VALUES(?,?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_ts=excluded.updated_ts",
                (key, str(value), int(time.time())),
            )
            conn.commit()
            conn.close()
            if _settings_cache is None:
                _settings_cache = dict(DEFAULT_SETTINGS)
            _settings_cache[key] = str(value)
            return True
        except Exception as e:
            log.warning("[settings save %s] error: %s", key, e)
            return False

    # Named tenant — upsert into their own rows.
    try:
        _ensure_tenant_settings_table()
        conn = get_db()
        c = conn.cursor()
        c.execute(
            "INSERT INTO tenant_settings(tenant_id,key,value,updated_ts) VALUES(?,?,?,?) "
            "ON CONFLICT(tenant_id,key) DO UPDATE SET value=excluded.value, updated_ts=excluded.updated_ts",
            (tenant_id, key, str(value), int(time.time())),
        )
        conn.commit()
        conn.close()
        cached = _tenant_settings_cache.setdefault(tenant_id, dict(DEFAULT_SETTINGS))
        cached[key] = str(value)
        return True
    except Exception as e:
        log.warning("[settings save %s (%s)] error: %s", tenant_id, key, e)
        return False


def invalidate_cache(tenant_id: Optional[str] = None):
    """Force reload of settings on next access.

    tenant_id=None clears ALL caches (global + every tenant); a specific
    tenant_id clears just that tenant's cache.
    """
    global _settings_cache
    if tenant_id is None:
        _settings_cache = None
        _tenant_settings_cache.clear()
        return
    if is_default_tenant(tenant_id):
        _settings_cache = None
    else:
        _tenant_settings_cache.pop(tenant_id, None)


def settings_label(k):
    """Human-readable label for a settings key."""
    return {
        "cost_mode": "Cost model (none|rental|power)",
        "rental_usd_per_th_day": "Rental rate ($ per TH/s per day) — what YOU charge to lease out hashrate (revenue)",
        "power_watts": "Estimated rig power (W)",
        "power_kwh_usd": "Electricity rate ($ per kWh)",
        "btc_block_reward": "Current BTC block reward",
        "btc_avg_tx_fee": "Assumed average fee per block (BTC)",
        "pool_fee_pct": "Pool fee (%)",
        "orphan_rate_pct": "Assumed orphan/stale rate (%)",
        "active_currency": "Display currency (USD|BRL|EUR|GBP|JPY|KRW|CNY)",
        "active_fiat": "Display currency (alias)",
        "stale_share_minutes": "Stale-share alert threshold (minutes)",
        "hashrate_drop_pct": "Hashrate drop alert threshold (%)",
        "webhook_url": "Webhook URL (Discord/Telegram-compatible)",
        "webhook_min_severity": "Min severity to fire webhook (INFO|WARN|CRIT|GOLD|SUCCESS)",
        "show_test_alerts": "Allow synthetic demo alerts (0|1)",
        "mrr_api_key": "MiningRigRentals API key (Settings → MRR credentials)",
        "mrr_api_secret": "MiningRigRentals API secret (Settings → MRR credentials)",
        "braiins_api_key": "Braiins Hashpower API key — owner token (Settings → Braiins credentials)",
    }.get(k, k)
