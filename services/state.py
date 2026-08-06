"""
CYPHER65 // Shared mutable state
=================================
Single source of truth for polling, routes, and proximity.
Extracted from app.py to break circular import chains.
"""
import collections

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  State cache
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
latest_snapshot = {
    "ts": 0,
    "worker": None,
    "user_aggregate": None,
    "pool": None,
    "account": None,
    "lightning": None,
    "leaderboard_entry": None,
    "leaderboard_total": 0,
    "highest_diffs": [],
    "network": {
        "height": None,
        "difficulty": None,
        "hashrate": None,
    },
    "btc_price": {"usd": None, "brl": None},
    "luck_estimate": {},
    "alerts_recent": [],
    "timeline_recent": [],
    "event_stats": {},
    "leaderboard_table_top_30": [],
}

# Timeline delta tracker ─ tracks last-known values across polls
# so we can flag REAL events (share submit, best-diff bump, work deltas)
# without exposing per-share logs (which the pool simply doesn't publish).
timeline_state = {
    "_primed": False,              # becomes True after the first priming poll
    "last_submit_ts": 0,           # unix ts of last known worker.lastSubmission
    "last_best_diff_str": "",      # str form of last known worker.bestDifficulty
    "all_time_best_diff_raw": 0.0, # never decreases across proxy reconnects (persisted in settings)
    "share_submit_history": collections.deque(maxlen=64),  # recent submit ts list
    "share_calc_history": collections.deque(maxlen=120),   # per-share live-calc entries (latest at right)
    "session_share_count": 0,      # total SHARES observed since process start
    "session_best_diff_bumps": 0,  # total BEST_DIFF bumps since process start
}

# ── Disk-failure watchdog ─────────────────────────────────────────────────────
PERSIST_FAILURE_ALERT_AT = 2
PERSIST_FAILURE_LADDER = (2, 5, 10, 25, 60, 120)
persist_consec_failures = 0
memory_critical_alerts = []  # injected into alerts_recent via make_memory_alert helper
_next_memory_alert_id = 0    # monotonic counter so JS renderAlerts sees stable ids

# ── Mock opportunity injection (for visual testing)
test_opportunities = None  # set by POST /api/opportunities/mock; bypasses real scan

# ── Last known market prices (fallback when live scan returns empty)
# Each entry: {"price": float, "ts": int, "label": str}
last_known_prices = {
    "braiins": None,  # e.g. {"price": 0.000123, "ts": 1700000000, "label": "123.0 sats/PH/day"}
    "mrr": None,
    "nicehash": None,
    "parasite": None,
}

# ── Market data cache (full offers with metrics, refreshed by background poll)
# Structure: {"offers": [...], "best_price": str, "updated_at": int (unix ts), "loading": bool}
market_data_cache = {
    "offers": [],
    "best_price": None,
    "updated_at": 0,
    "loading": True,
    "error": None,
}

# ── BTC price cache (CoinGecko free tier: 10-50 req/min)
BTC_PRICE_CACHE_TTL = 300  # 5 minutes
btc_price_cache = {"ts": 0, "data": None}

# ── Axe Fleet state ─────────────────────────────────────────────────────────
# Cached telemetry for each device, updated by _poll_axe_fleet()
# Format: {device_id: telemetry_dict}
axe_telemetry_cache = {}

# Last poll timestamp per device (for throttling)
# Format: {device_id: unix_ts}
axe_last_poll_ts = {}

# Axe fleet polling interval (seconds) — conservative to avoid network load
AXE_POLL_INTERVAL = 60
