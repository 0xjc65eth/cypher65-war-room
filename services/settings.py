"""
CYPHER65 — Settings service
============================
User-tunable settings: cost model, currency, alert thresholds.
Persisted to SQLite via services/db.py.
"""

import time
import logging
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
}

_settings_cache = None


def load_settings():
    """Return a dict of key->value (str), seeded with defaults for any missing key.
    Cached at module level and refreshed on save."""
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


def save_setting(key, value):
    """Persist a setting and refresh in-memory cache.
    Internal keys (prefixed with '_') bypass the DEFAULT_SETTINGS whitelist."""
    global _settings_cache
    if not key.startswith('_') and key not in DEFAULT_SETTINGS:
        raise KeyError(f"unknown setting key: {key}")
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


def invalidate_cache():
    """Force reload of settings on next access."""
    global _settings_cache
    _settings_cache = None


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
    }.get(k, k)
