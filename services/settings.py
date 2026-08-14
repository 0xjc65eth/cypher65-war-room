"""
CYPHER65 — Settings service
============================
User-tunable settings: cost model, currency, alert thresholds.
Persisted to SQLite via services/db.py.
"""

import os
import time
import logging
import hashlib
import base64
from typing import Optional

from services.db import get_db

log = logging.getLogger("cypher65.settings")

# ── Credential-at-rest encryption (defense-in-depth) ─────────────────────────
# Keys carrying secrets (API tokens) are stored Fernet-encrypted when a
# stable SECRET_KEY is available, so a leaked DB dump/backup does not expose
# every user's Braiins/MRR credentials in plaintext. Decryption is
# transparent: load_settings() returns the plaintext value; save_setting()
# stores the ciphertext. No SECRET_KEY (open self-host) → values are stored
# as-is (best-effort, same behavior as before). Legacy plaintext values are
# read back unchanged.
_CREDENTIAL_KEYS = {"braiins_api_key", "mrr_api_key", "mrr_api_secret"}
_ENC_PREFIX = "enc:v1:"
# Cached Fernet instance + the SECRET_KEY it was derived from — creating a
# Fernet (SHA256 + b64) on every credential call is wasteful on the hot
# settings path. Rebuilt lazily when the secret changes (tests rotate it).
_fernet_cache: tuple = (None, None)  # (secret, Fernet|None)


def _fernet():
    """Return a Fernet instance keyed from SECRET_KEY, or None when the
    key is absent (open self-host) — in which case values stay plaintext.
    Cached; rebuilt only when SECRET_KEY changes."""
    global _fernet_cache
    secret = (os.environ.get("SECRET_KEY") or "").strip()
    if _fernet_cache[0] == secret:
        return _fernet_cache[1]
    if not secret:
        _fernet_cache = (secret, None)
        return None
    try:
        from cryptography.fernet import Fernet
    except Exception:
        _fernet_cache = (secret, None)
        return None
    digest = hashlib.sha256(secret.encode("utf-8")).digest()
    f = Fernet(base64.urlsafe_b64encode(digest))
    _fernet_cache = (secret, f)
    return f


def _encrypt_credential(value: str) -> str:
    """Encrypt a secret for storage. Plaintext passthrough when no key."""
    if not value:
        return value
    f = _fernet()
    if f is None:
        return value
    try:
        return _ENC_PREFIX + f.encrypt(value.encode("utf-8")).decode("ascii")
    except Exception:
        return value


def _decrypt_credential(value: str) -> str:
    """Decrypt a stored secret. Legacy plaintext (no prefix) passes through."""
    if not value or not value.startswith(_ENC_PREFIX):
        return value
    f = _fernet()
    if f is None:
        return value
    try:
        raw = f.decrypt(value[len(_ENC_PREFIX):].encode("ascii"))
        return raw.decode("utf-8")
    except Exception:
        # Wrong SECRET_KEY or corrupt value — return as-is (never raise, so
        # an operator key rotation can't brick credential consumers).
        log.warning("[settings] could not decrypt credential value")
        return value

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
    "rental_pl_alert_pct": "-50",
    "rental_pl_alert_window_hours": "48",
    "rental_market_overpay_pct": "",
    "rental_market_arb_pct": "",
    "rental_market_arb_cooldown_hours": "24",
    "rental_reco_worse_alert": "0",
    "rental_auto_exclude_alert": "0",
    "rentals_min_delivery_pct": "90",
    "rental_auto_blacklist_min_samples": "2",
    "rental_auto_blacklist_grade": "F",
    "mrr_api_key": "",
    "mrr_api_secret": "",
    "braiins_api_key": "",
    "auto_pilot_armed": "0",
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

    Credential keys are returned DECRYPTED (transparent to consumers).
    """
    def _finalize(d: dict) -> dict:
        for k in _CREDENTIAL_KEYS:
            if k in d and isinstance(d[k], str):
                d[k] = _decrypt_credential(d[k])
        return d

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
        _settings_cache = _finalize(out)
        return _settings_cache

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
    _tenant_settings_cache[tenant_id] = _finalize(out)
    return _tenant_settings_cache[tenant_id]


def save_setting(key, value, tenant_id: str = ""):
    """Persist a setting and refresh the in-memory cache.

    Tenant-aware (mirrors load_settings):
      - default tenant → global `settings` table (legacy behavior).
      - named tenant   → that tenant's `tenant_settings` rows only.
    Internal keys (prefixed with '_') bypass the DEFAULT_SETTINGS whitelist.

    Credential keys are stored ENCRYPTED when SECRET_KEY is set.
    """
    if not key.startswith('_') and key not in DEFAULT_SETTINGS:
        raise KeyError(f"unknown setting key: {key}")
    stored = str(value)
    if key in _CREDENTIAL_KEYS:
        stored = _encrypt_credential(stored)
    if is_default_tenant(tenant_id):
        global _settings_cache
        try:
            conn = get_db()
            c = conn.cursor()
            c.execute(
                "INSERT INTO settings(key,value,updated_ts) VALUES(?,?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_ts=excluded.updated_ts",
                (key, stored, int(time.time())),
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
            (tenant_id, key, stored, int(time.time())),
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
        "rental_pl_alert_pct": "Rental P/L alert — fire webhook/push when a closed rental's economic P/L is BELOW this % (e.g. -50; empty/0 disables)",
        "rental_pl_alert_window_hours": "Only alert rentals that ENDED within this many hours (avoids backfill flood on first enable)",
        "rental_market_overpay_pct": "Rental overpay alert — fire webhook/push when the price PAID for a rental is this % ABOVE the market at purchase time (e.g. 100; empty/0 disables)",
        "rental_market_arb_pct": "Arbitrage alert — fire webhook/push when the CURRENT market price is this % BELOW the tenant's own cost references per TH·h (e.g. 30; empty/0 disables). Compares vs the ADVERTISED average, the DELIVERED/effective cost (real delivery) and the LAST rental; the highest baseline drives the signal. Local-first: baselines come from the tenant's past rentals (open the RENTALS panel once to populate them) + local market table (no provider calls)",
        "rental_market_arb_cooldown_hours": "Arbitrage dedup: repeat the alert at most once per this many hours (default 24)",
        "rental_reco_worse_alert": "Accepted-recommendation alert — fire webhook/push when a rig you blacklisted (accepted recommendation) ends with verdict WORSE (it kept under-delivering after the exclusion); 0/1, default off. Revoked decisions never alert",
        "rental_auto_exclude_alert": "Auto-exclusion alert — fire webhook/push when the periodic sweep auto-excludes a rig (sub-entrega: grade at/below your floor with enough samples). The message includes the cause (delivery %, samples, rule); 0/1, default off",
        "rentals_min_delivery_pct": "Análise de Rendimento (CSV): delivery % mínimo aceitável por aluguel (default 90). Abaixo dele o aluguel é marcado cancelled_performance e entra o reembolso devido no CSV",
        "rental_auto_blacklist_min_samples": "Auto-exclusão: amostras mínimas de entrega para excluir automaticamente um rig (default 2). Mais alto = decisão mais conservadora",
        "rental_auto_blacklist_grade": "Auto-exclusão: grau máximo aceitável — o rig é auto-excluído quando a grade é pior OU igual a esta letra (default F = só F; D = exclui D e F)",
        "mrr_api_key": "MiningRigRentals API key (Settings → MRR credentials)",
        "mrr_api_secret": "MiningRigRentals API secret (Settings → MRR credentials)",
        "braiins_api_key": "Braiins Hashpower API key — owner token (Settings → Braiins credentials)",
    }.get(k, k)
