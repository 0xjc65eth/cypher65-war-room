"""
CYPHER65 // PARASITE POOL WAR ROOM
==================================
A real-time monitoring dashboard for the cypher65 worker on Parasite Pool.
Author: built by Buffy for Julio Cesar
"""
import os
import json
import time
import random
import sqlite3
import threading
import collections
import logging
from pathlib import Path

from flask import Flask, jsonify, render_template, request, abort
import requests
import concurrent.futures

import solo_mining

from helpers import (
    parse_diff_to_float, fmt_diff, fmt_hashrate, fmt_uptime, fmt_age,
    safe_int, safe_num_from_str, coerce_float, coerce_int,
    human_int, human_secs_long, isfinite_v, make_memory_alert,
)

# ── Structured logging ───────────────────────────────────────────────────────
# ISO-ts + module.tag + level. diagnostic prefix in messages preserved so
# log files remain greppable for [fetch] / [persist] / [purge] / [poll_loop].
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)sZ %(levelname)s [%(module)s.%(funcName)s] %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
log = logging.getLogger("cypher65")

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  CONFIG
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
BTC_ADDRESS = os.environ.get(
    "BTC_ADDRESS",
    "bc1qpc3832jcu6m8qpqjvz5lkuydwjzv8v5vq5t5rs",
)
WORKER_NAME = os.environ.get("WORKER_NAME", "cypher65")
PARASITE_API = "https://parasite.space/api"
MEMPOOL_API = "https://mempool.space/api"
DATA_DIR = Path(__file__).parent / "data"
DB_PATH = 'data/war_room.sqlite'
POLL_INTERVAL = int(os.environ.get("POLL_INTERVAL", 15))  # seconds
PORT = int(os.environ.get("PORT", 8765))
RATE_LIMIT_PER_MINUTE = int(os.environ.get("RATE_LIMIT_PER_MINUTE", 60))

DATA_DIR.mkdir(exist_ok=True)
app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", os.urandom(32).hex())

# ━━ Simple in-memory rate limiter ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
_rate_limit_store = {}  # {ip: [timestamps]}

@app.before_request
def rate_limit():
    """Simple rate limiter: max RATE_LIMIT_PER_MINUTE requests per IP per minute.
    Skips static files, healthz, and agent discovery endpoints."""
    if request.path.startswith('/static') or request.path == '/healthz' or request.path == '/api/healthz' or request.path.startswith('/api/agents'):
        return None
    ip = request.remote_addr or '127.0.0.1'
    now = time.time()
    window = 60.0
    if ip not in _rate_limit_store:
        _rate_limit_store[ip] = []
    # Prune old entries
    _rate_limit_store[ip] = [t for t in _rate_limit_store[ip] if now - t < window]
    if len(_rate_limit_store[ip]) >= RATE_LIMIT_PER_MINUTE:
            abort(429, description="Rate limit exceeded. Please slow down.")
    _rate_limit_store[ip].append(now)
    # GC old IPs periodically
    if len(_rate_limit_store) > 5000:
        _rate_limit_store.clear()

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  SQLite
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    c = conn.cursor()
    c.execute(
        """CREATE TABLE IF NOT EXISTS snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts INTEGER NOT NULL,
            worker_hashrate REAL,
            worker_best_diff TEXT,
            worker_last_submit INTEGER,
            worker_uptime INTEGER,
            worker_status TEXT,
            pool_hashrate REAL,
            pool_workers INTEGER,
            pool_users INTEGER,
            pool_highest_diff TEXT,
            pool_last_block_height INTEGER,
            pool_last_block_time INTEGER,
            pool_work_since_last_block REAL,
            account_total_diff REAL,
            account_block_count INTEGER,
            account_highest_block INTEGER,
            leaderboard_rank INTEGER,
            leaderboard_diff_rank INTEGER,
            leaderboard_loyalty_rank INTEGER,
            leaderboard_combined_score REAL,
            network_height INTEGER,
            network_difficulty REAL,
            network_hashrate REAL,
            btc_usd REAL,
            btc_brl REAL
        )"""
    )
    c.execute(
        """CREATE TABLE IF NOT EXISTS highest_diff_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts INTEGER NOT NULL,
            block_height INTEGER,
            top_diff_address TEXT,
            difficulty TEXT,
            claimed INTEGER,
            block_timestamp INTEGER,
            is_mine INTEGER DEFAULT 0
        )"""
    )
    c.execute(
        """CREATE TABLE IF NOT EXISTS alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts INTEGER NOT NULL,
            severity TEXT,
            category TEXT,
            message TEXT
        )"""
    )
    c.execute(
        """CREATE TABLE IF NOT EXISTS share_timeline (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts INTEGER NOT NULL,
            event_type TEXT NOT NULL,
            severity TEXT NOT NULL,
            message TEXT NOT NULL,
            meta TEXT
        )"""
    )
    c.execute(
        """CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT,
            updated_ts INTEGER
        )"""
    )
    c.execute(
        """CREATE TABLE IF NOT EXISTS proximity_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts INTEGER NOT NULL,
            best_diff REAL,
            best_diff_str TEXT,
            all_time_best_diff REAL,
            network_difficulty REAL,
            worker_hashrate REAL,
            pct_of_network REAL,
            hot_streak INTEGER DEFAULT 0
        )"""
    )
    # NOTE: achievements (milestones) are computed in-memory per poll from
    # session_share_count / worker best-difficulty / worker uptime. No DB
    # table needed — kept lightweight so the badge grid re-derives naturally
    # each poll without needing INSERTs.
    # cleanup just runs at startup; periodic purge handled by purge_old() in poll_loop
    conn.commit()
    conn.close()
    conn = sqlite3.connect("data/war_room.sqlite")
    c = conn.cursor()
    c.execute(
        "CREATE INDEX IF NOT EXISTS idx_snapshots_ts ON snapshots(ts)"
    )
    c.execute(
        "CREATE INDEX IF NOT EXISTS idx_alerts_ts ON alerts(ts)"
    )
    c.execute(
        "CREATE INDEX IF NOT EXISTS idx_high_diff_height ON highest_diff_events(block_height)"
    )
    c.execute(
        "CREATE INDEX IF NOT EXISTS idx_share_timeline_ts ON share_timeline(ts)"
    )
    c.execute(
        "CREATE INDEX IF NOT EXISTS idx_share_timeline_type ON share_timeline(event_type)"
    )
    c.execute(
        "CREATE INDEX IF NOT EXISTS idx_proximity_history_ts ON proximity_history(ts)"
    )
    # ── WAL mode for better concurrent read/write ──
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA synchronous=NORMAL")
    c.execute("PRAGMA cache_size=-8000")  # 8MB cache
    c.execute("PRAGMA busy_timeout=3000")
    conn.commit()
    conn.close()


init_db()

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  State cache

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Shared state (extracted to services/state.py)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
import services.state as state

#  Settings (user-tunable: cost model, currency, alert thresholds)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
DEFAULT_SETTINGS = {
    # cost model — choose rental OR power (kWh) OR none
    "cost_mode": "none",          # 'none' | 'rental' | 'power'
    "rental_usd_per_th_day": "0.00",  # cost per TH/s per day (USD)
    "power_watts": "3000",         # estimated rig power when cost_mode='power'
    "power_kwh_usd": "0.10",       # electricity rate (USD per kWh)

    # profitability assumptions
    "btc_block_reward": "3.125",   # current post-halving reward (BTC, tx fees excluded as conservative)
    "btc_avg_tx_fee": "0.05",      # conservative avg fee per block (BTC)
    "pool_fee_pct": "1.5",         # pool fee in % (parasite defaults ~1%)
    "orphan_rate_pct": "0.5",      # rejected/orphan rate assumption

    # selection
    "active_currency": "USD",      # USD | BRL | EUR | GBP
    "active_fiat": "USD",          # alias kept for backwards-compat

    # alert thresholds
    "stale_share_minutes": "5",    # older than this → CRIT stale_share alert
    "hashrate_drop_pct": "50",     # hashrate drop vs prev poll triggers WARN

    # webhooks (Power-User)
    "webhook_url": "",             # POST JSON payload on CRIT/GOLD/NEW_BLOCK
    "webhook_min_severity": "WARN",# INFO|WARN|CRIT|GOLD|SUCCESS

    # display
    "show_test_alerts": "0",       # 1 → allow injection of synthetic demo alerts
}

_settings_cache = None


def load_settings():
    """Return a dict of key→value (str), seeded with defaults for any missing key.
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
    """Persist a setting and refresh in-memory cache."""
    global _settings_cache
    if key not in DEFAULT_SETTINGS:
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


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Network helpers
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
FETCH_MAX_RETRIES = 2
FETCH_BACKOFF_BASE = 1.5  # seconds: 0, 1.5, 3.0

def fetch_json(url, timeout=10):
    last_err = None
    for attempt in range(FETCH_MAX_RETRIES + 1):
        try:
            r = requests.get(
                url,
                timeout=timeout,
                headers={"User-Agent": "cypher65-war-room/1.0"},
            )
            r.raise_for_status()
            return r.json()
        except Exception as e:
            last_err = e
            if attempt < FETCH_MAX_RETRIES:
                delay = FETCH_BACKOFF_BASE * attempt
                if delay > 0:
                    time.sleep(delay)
    log.warning(f"[fetch] error %s (retries={FETCH_MAX_RETRIES}): %s", url, last_err)
    return None


def fetch_text(url, timeout=8):
    """Like fetch_json but returns the raw text body. Used for blockchain.info
    /q/* endpoints which return plain integers like '154824667684575552', not
    JSON. Returns stripped string or None on failure."""
    last_err = None
    for attempt in range(FETCH_MAX_RETRIES + 1):
        try:
            r = requests.get(
                url,
                timeout=timeout,
                headers={"User-Agent": "cypher65-war-room/1.0"},
            )
            r.raise_for_status()
            return r.text.strip()
        except Exception as e:
            last_err = e
            if attempt < FETCH_MAX_RETRIES:
                delay = FETCH_BACKOFF_BASE * attempt
                if delay > 0:
                    time.sleep(delay)
    log.warning(f"[fetch_text] error %s (retries={FETCH_MAX_RETRIES}): %s", url, last_err)
    return None


_make_memory_alert = make_memory_alert



# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Proximity meter (extracted to services/proximity.py)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
import services.proximity as proximity
proximity.init(get_db)  # inject DB + restore all-time best diff


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Polling worker (extracted to services/polling.py)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
import services.polling as polling

# Build config object that the polling + solo-mining modules use
class _PollConfig:
    pass
_poll_cfg = _PollConfig()
_poll_cfg.PARASITE_API = PARASITE_API
_poll_cfg.MEMPOOL_API = MEMPOOL_API
_poll_cfg.BTC_ADDRESS = BTC_ADDRESS
_poll_cfg.WORKER_NAME = WORKER_NAME
_poll_cfg.POLL_INTERVAL = POLL_INTERVAL
_poll_cfg.DB_PATH = DB_PATH
_poll_cfg.PERSIST_FAILURE_LADDER = state.PERSIST_FAILURE_LADDER
_poll_cfg.PERSIST_FAILURE_ALERT_AT = state.PERSIST_FAILURE_ALERT_AT
_poll_cfg.get_db = get_db
_poll_cfg.load_settings = load_settings
_poll_cfg.fetch_json = fetch_json
_poll_cfg.fetch_text = fetch_text
_poll_cfg.make_memory_alert = make_memory_alert
_poll_cfg.human_int = human_int
_poll_cfg.human_secs_long = human_secs_long
polling.init(_poll_cfg)

@app.route("/")
def index():
    return render_template(
        "dashboard.html",
        worker=WORKER_NAME,
        address=BTC_ADDRESS,
        poll_interval=POLL_INTERVAL,
    )


@app.route("/api/snapshot")
def api_snapshot():
    return jsonify(state.latest_snapshot)


@app.route("/api/history")
def api_history():
    metric = request.args.get("metric", "worker_hashrate")
    rng = request.args.get("range", "24h")
    now = int(time.time())
    span = {
        "15m": 900,
        "1h": 3600,
        "6h": 6 * 3600,
        "24h": 86400,
        "7d": 7 * 86400,
        "30d": 30 * 86400,
        "all": 10**10,
    }.get(rng, 86400)
    since = now - span
    allowed = {
        "worker_hashrate",
        "pool_hashrate",
        "pool_work_since_last_block",
        "account_total_diff",
        "leaderboard_combined_score",
        "network_difficulty",
        "network_hashrate",
        "btc_usd",
        "worker_best_diff",
    }
    if metric not in allowed:
        return jsonify({"error": f"invalid metric {metric}"}), 400
    conn = get_db()
    c = conn.cursor()
    c.execute(
        f"SELECT ts, {metric} FROM snapshots WHERE ts >= ? AND {metric} IS NOT NULL ORDER BY ts ASC",
        (since,),
    )
    rows = [{"ts": r["ts"], "value": r[metric]} for r in c.fetchall()]
    conn.close()
    return jsonify({"metric": metric, "rows": rows, "range": rng})


@app.route("/api/alerts")
def api_alerts():
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM alerts ORDER BY ts DESC LIMIT 80")
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return jsonify({"alerts": rows})


@app.route("/api/diff_events")
def api_diff_events():
    only_mine = request.args.get("mine", "0") == "1"
    limit = int(request.args.get("limit", 30))
    conn = get_db()
    c = conn.cursor()
    if only_mine:
        c.execute(
            "SELECT * FROM highest_diff_events WHERE is_mine=1 ORDER BY block_height DESC LIMIT ?",
            (limit,),
        )
    else:
        c.execute(
            "SELECT * FROM highest_diff_events ORDER BY block_height DESC LIMIT ?",
            (limit,),
        )
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return jsonify({"events": rows})


@app.route("/api/leaderboard")
def api_leaderboard():
    # Served from the poll_once() cache so 100 open UI tabs → 0 upstream calls
    # (eliminates the trivial-DoS vector and matches the "poll once centrally,
    # serve many locally" pattern used by the rest of the dashboard).
    top = state.latest_snapshot.get("leaderboard_table_top_30") or []
    enriched = []
    for entry in top:
        if isinstance(entry, dict):
            entry_copy = dict(entry)  # don't mutate the cached list
            entry_copy["is_me"] = entry_copy.get("address") == BTC_ADDRESS
            enriched.append(entry_copy)
    return jsonify({
        "entries": enriched,
        "total": state.latest_snapshot.get("leaderboard_total", len(top)),
        "stale_after_s": POLL_INTERVAL,  # client knows to refresh at poll cadence
    })


@app.route("/api/share_timeline")
def api_share_timeline():
    """Return recent share-timeline events (worker share submissions,
    best-diff bumps, work deltas). Newest first."""
    try:
        limit = max(1, min(int(request.args.get("limit", 80)), 500))
        event_type = request.args.get("type")
        conn = get_db()
        c = conn.cursor()
        if event_type:
            c.execute(
                "SELECT * FROM share_timeline WHERE event_type=? ORDER BY id DESC LIMIT ?",
                (event_type, limit),
            )
        else:
            c.execute(
                "SELECT * FROM share_timeline ORDER BY id DESC LIMIT ?",
                (limit,),
            )
        rows = [dict(r) for r in c.fetchall()]
        conn.close()
        # parse meta JSON for client convenience
        for r in rows:
            try:
                if r.get("meta"):
                    r["meta"] = json.loads(r["meta"])
            except Exception:
                pass
        return jsonify({"events": rows, "count": len(rows)})
    except Exception as e:
        return jsonify({"error": str(e), "events": []}), 500


@app.route("/api/event_stats")
def api_event_stats():
    """Return session + rolling-window event statistics derived from the
    public API (no per-share logs from the pool)."""
    snap = dict(state.latest_snapshot.get("event_stats") or {})
    snap["server_now"] = int(time.time())
    snap["poll_age_s"] = (
        snap["server_now"] - (state.latest_snapshot.get("ts") or 0)
        if state.latest_snapshot.get("ts")
        else None
    )
    return jsonify(snap)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Settings API (GET/POST) — drives cost model, currency, thresholds
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
@app.route("/api/settings", methods=["GET"])
def api_settings_get():
    s = load_settings()
    out = []
    for k, v in DEFAULT_SETTINGS.items():
        out.append({"key": k, "value": s.get(k, v), "default": v, "label": _settings_label(k)})
    return jsonify({"settings": out, "freshness_ts": int(time.time())})


@app.route("/api/settings", methods=["POST"])
def api_settings_post():
    """POST JSON body: {key: value, key: value, ...}
    Validates known keys, coerces to str, persists to SQLite, refreshes cache."""
    body = request.get_json(silent=True) or {}
    if not isinstance(body, dict):
        return jsonify({"error": "expected JSON object body"}), 400
    applied = []
    rejected = []
    for k, v in body.items():
        if k not in DEFAULT_SETTINGS:
            rejected.append({"key": k, "reason": "unknown key"})
            continue
        if save_setting(k, v):
            applied.append(k)
        else:
            rejected.append({"key": k, "reason": "db error"})
    return jsonify({"applied": applied, "rejected": rejected})


def _settings_label(k):
    return {
        "cost_mode": "Cost model (none|rental|power)",
        "rental_usd_per_th_day": "Rental cost ($ per TH/s per day)",
        "power_watts": "Estimated rig power (W)",
        "power_kwh_usd": "Electricity rate ($ per kWh)",
        "btc_block_reward": "Current BTC block reward",
        "btc_avg_tx_fee": "Assumed average fee per block (BTC)",
        "pool_fee_pct": "Pool fee (%)",
        "orphan_rate_pct": "Assumed orphan/stale rate (%)",
        "active_currency": "Display currency (USD|BRL|EUR|GBP)",
        "active_fiat": "Display currency (alias)",
        "stale_share_minutes": "Stale-share alert threshold (minutes)",
        "hashrate_drop_pct": "Hashrate drop alert threshold (%)",
        "webhook_url": "Webhook URL (Discord/Telegram-compatible)",
        "webhook_min_severity": "Min severity to fire webhook (INFO|WARN|CRIT|GOLD|SUCCESS)",
        "show_test_alerts": "Allow synthetic demo alerts (0|1)",
    }.get(k, k)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Subset endpoints (Halving / Mempool / Profitability / Network-share)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
@app.route("/api/halving")
def api_halving():
    return jsonify(state.latest_snapshot.get("halving") or {})


@app.route("/api/mempool_fees")
def api_mempool_fees():
    return jsonify(state.latest_snapshot.get("mempool_fees") or {})


@app.route("/api/profitability")
def api_profitability():
    p = dict(state.latest_snapshot.get("profitability") or {})
    p["active_currency"] = load_settings().get("active_currency", "USD")
    return jsonify(p)


@app.route("/api/network_share")
def api_network_share():
    return jsonify(state.latest_snapshot.get("network_share_gauge") or {})


@app.route("/api/milestones")
def api_milestones():
    return jsonify({"milestones": state.latest_snapshot.get("milestones") or []})


@app.route("/api/workers")
def api_workers():
    """Return all workers from the connected wallet's workerData."""
    return jsonify({"workers": state.latest_snapshot.get("all_workers") or []})


@app.route("/api/monte_carlo")
def api_monte_carlo():
    """Monte Carlo simulation engine.
    Accepts ?hours=N (default 24) and ?runs=N (default 10000).
    Simulates block-finding probability over the specified period using
    the current worker hashrate and network difficulty.
    Returns: distribution of blocks found across N runs, percentiles,
    and key probability stats. All clearly labeled as SIMULATED."""
    hours = request.args.get("hours", 24, type=int)
    runs = request.args.get("runs", 10000, type=int)
    # Clamp params
    hours = max(1, min(hours, 8760))  # 1h .. 1year
    runs = max(100, min(runs, 100000))

    worker = state.latest_snapshot.get("worker") or {}
    net_diff = (state.latest_snapshot.get("network") or {}).get("difficulty")
    cur_hr = float(worker.get("hashrate") or 0)

    if not cur_hr or not net_diff:
        return jsonify({"error": "insufficient data", "status": "SIMULATED"})

    # Expected blocks in period: hashrate / (difficulty * 2^32) * seconds
    hashes_per_block = float(net_diff) * (2 ** 32)
    seconds = hours * 3600.0
    expected_blocks = cur_hr * seconds / hashes_per_block

    # Monte Carlo: Poisson process for block finding
    distribution = [0] * (min(int(expected_blocks * 5) + 5, 5000))
    for _ in range(runs):
        blocks = 0
        t = 0.0
        rate = cur_hr / hashes_per_block  # blocks per second
        while t < seconds:
            t += random.expovariate(rate)
            if t < seconds:
                blocks += 1
        if blocks >= len(distribution):
            distribution.extend([0] * (blocks - len(distribution) + 10))
        distribution[blocks] += 1

    # Compute median and p90
    cum = 0
    median_blocks = 0
    p90_blocks = 0
    for k, count in enumerate(distribution):
        cum += count
        if cum >= runs / 2 and median_blocks == 0 and k > 0:
            median_blocks = k
        if cum >= runs * 0.9 and p90_blocks == 0:
            p90_blocks = k
        if median_blocks and p90_blocks:
            break
    if median_blocks == 0:
        median_blocks = 0
    if p90_blocks == 0:
        p90_blocks = len(distribution) - 1 if distribution else 0

    # Build result
    dist_pct = []
    cumulative = 0.0
    for k, count in enumerate(distribution):
        if count > 0 or k <= int(expected_blocks) + 2:
            pct = round(count / runs * 100, 4)
            cumulative += pct
            dist_pct.append({
                "blocks": k,
                "count": count,
                "pct": pct,
                "cumulative_pct": round(cumulative, 4),
                "bar": "█" * max(1, int(pct * 2)),
            })

    p_zero = distribution[0] / runs * 100 if len(distribution) > 0 else 100.0

    return jsonify({
        "status": "SIMULATED",
        "params": {"hours": hours, "runs": runs},
        "inputs": {
            "worker_hashrate_hs": cur_hr,
            "worker_hashrate_ths": round(cur_hr / 1e12, 2),
            "network_difficulty": net_diff,
            "network_difficulty_str": fmt_diff(net_diff),
        },
        "results": {
            "expected_blocks": round(expected_blocks, 6),
            "expected_blocks_str": f"{expected_blocks:.6f}",
            "p_zero_blocks_pct": round(p_zero, 4),
            "p_at_least_one_block_pct": round(100 - p_zero, 4),
            "median_blocks": median_blocks,
            "p90_blocks": p90_blocks,
            "distribution": dist_pct[:20],  # top 20 outcomes
        },
        "disclaimer": "MONTE CARLO SIMULATION — results are statistical estimates based on current hashrate and difficulty. Actual mining outcomes are governed by random chance and may differ significantly.",
    })


@app.route("/api/proximity")
def api_proximity():
    """Returns the current proximity meter payload PLUS a 24h history slice
    for the front-end mini-chart. History is read from the proximity_history
    DB table (sampled once per minute by poll_once)."""
    base = dict(state.latest_snapshot.get("proximity") or {})
    history_24h = []
    try:
        conn = get_db()
        c = conn.cursor()
        cutoff = int(time.time()) - 86400
        c.execute(
            "SELECT ts, best_diff, all_time_best_diff, network_difficulty, "
            "worker_hashrate, pct_of_network, hot_streak "
            "FROM proximity_history WHERE ts >= ? ORDER BY ts ASC",
            (cutoff,),
        )
        for r in c.fetchall():
            history_24h.append({
                "ts": r["ts"],
                "best_diff_raw": r["best_diff"],
                "all_time_best_diff_raw": r["all_time_best_diff"],
                "network_difficulty_raw": r["network_difficulty"],
                "worker_hashrate": r["worker_hashrate"],
                "pct_of_network": r["pct_of_network"],
                "hot_streak": bool(r["hot_streak"]),
            })
        conn.close()
    except Exception as e:
        log.warning("[api/proximity history] error: %s", e)
    base["history_24h"] = history_24h
    base["history_count"] = len(history_24h)
    return jsonify(base)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  CSV / JSON exports + Config backup/restore
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
import csv as _csv
from io import StringIO as _StringIO


@app.route("/api/export/<table>.<fmt>")
def api_export(table, fmt):
    """Export a table as csv or json. Tables: snapshots, alerts, share_timeline,
    highest_diff_events."""
    allowed = {"snapshots", "alerts", "share_timeline", "highest_diff_events"}
    if table not in allowed:
        return jsonify({"error": f"unknown table {table}"}), 400
    rng = request.args.get("range", "24h")
    span = {
        "15m": 900,
        "1h": 3600,
        "6h": 21600,
        "24h": 86400,
        "7d": 604800,
        "30d": 2592000,
        "all": 10 ** 10,
    }.get(rng, 86400)
    since = int(time.time()) - span
    conn = get_db()
    c = conn.cursor()
    c.execute(f"SELECT * FROM {table} WHERE ts >= ? ORDER BY ts DESC LIMIT 5000", (since,))
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    if fmt == "csv":
        buf = _StringIO()
        if rows:
            writer = _csv.DictWriter(buf, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            for r in rows:
                writer.writerow(r)
        out = buf.getvalue()
        return app.response_class(
            out,
            mimetype="text/csv",
            headers={"Content-Disposition": f"attachment; filename={table}_{rng}.csv"},
        )
    elif fmt == "json":
        return app.response_class(
            json.dumps({"table": table, "range": rng, "rows": rows}, default=str),
            mimetype="application/json",
            headers={"Content-Disposition": f"attachment; filename={table}_{rng}.json"},
        )
    else:
        return jsonify({"error": f"unknown format {fmt}"}), 400


@app.route("/api/config/backup")
def api_config_backup():
    """Download entire config (settings + worker + btc_address) as JSON."""
    s = load_settings()
    payload = {
        "settings": s,
        "worker_name": WORKER_NAME,
        "btc_address": BTC_ADDRESS,
        "exported_ts": int(time.time()),
        "version": 1,
    }
    return app.response_class(
        json.dumps(payload, indent=2, default=str),
        mimetype="application/json",
        headers={"Content-Disposition": "attachment; filename=cypher65_config_backup.json"},
    )


@app.route("/api/config/restore", methods=["POST"])
def api_config_restore():
    """Restore settings from a backup JSON body.
    Only updates keys that exist in DEFAULT_SETTINGS."""
    body = request.get_json(silent=True) or {}
    settings = body.get("settings") or {}
    if not isinstance(settings, dict):
        return jsonify({"error": "expected object with 'settings' key"}), 400
    applied, rejected = [], []
    for k, v in settings.items():
        if k not in DEFAULT_SETTINGS:
            rejected.append(k)
            continue
        if save_setting(k, v):
            applied.append(k)
    return jsonify({"applied": applied, "rejected": rejected})


@app.route("/healthz")
@app.route("/api/healthz")
def healthz():
    return jsonify(
        {
            "ok": True,
            "last_poll_ts": state.latest_snapshot.get("ts"),
            "now": int(time.time()),
            "age_s": int(time.time()) - (state.latest_snapshot.get("ts") or 0),
        }
    )



# ═══════════════════════════════════════════════════════════════════════════
# SOLO MINING ADVISOR API
# ═══════════════════════════════════════════════════════════════════════════


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Solo-mining routes (extracted to routes/solo_mining_routes.py)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
from routes.solo_mining_routes import solo_mining_bp
app.register_blueprint(solo_mining_bp, url_prefix="/api/solo-mining")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Agent registry — exposes the Solo Mining Advisor agent to freebuff
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
try:
    from agents.solo_mining_advisor import get_agent_descriptor, execute_tool
    _solo_advisor_loaded = True
    _solo_advisor_error = None
    log.info("[agents] Solo Mining Advisor loaded")
except Exception as e:
    _solo_advisor_loaded = False
    _solo_advisor_error = str(e)
    log.warning("[agents] Solo Mining Advisor failed to load: %s", e)


@app.route("/api/agents/solo-mining")
def api_agent_solo_mining():
    """Return the Solo Mining Advisor agent descriptor.
    This is the endpoint freebuff calls to discover and register the agent."""
    if not _solo_advisor_loaded:
        return jsonify({"error": "Agent not loaded", "detail": _solo_advisor_error or "unknown", "loaded": False}), 503
    return jsonify(get_agent_descriptor())


@app.route("/api/agents/solo-mining/tools", methods=["POST"])
def api_agent_solo_mining_tool():
    """Execute a tool on behalf of the Solo Mining Advisor.
    POST JSON: {"tool": "get_network_difficulty", "params": {}}"""
    if not _solo_advisor_loaded:
        return jsonify({"error": "Agent not loaded"}), 503
    body = request.get_json(silent=True) or {}
    tool_name = body.get("tool", "")
    params = body.get("params")
    if not tool_name:
        return jsonify({"error": "Missing 'tool' field"}), 400
    result = execute_tool(tool_name, params)
    return jsonify(result)


@app.route("/api/agents/solo-mining/ask", methods=["POST"])
def api_agent_solo_mining_ask():
    """Free-text natural-language query endpoint for the Solo Mining Advisor.
    Accepts: {"query": "what's the probability of finding a block..."}
    Parses the query for recognized patterns (compare, status, calc, network, help)
    and delegates to the appropriate agent tools + solo_mining calculation engine.

    Supports casual Portuguese, English, typos, and mixed language.
    """
    if not _solo_advisor_loaded:
        return jsonify({"error": "Agent not loaded"}), 503

    body = request.get_json(silent=True) or {}
    query = (body.get("query") or "").strip()[:300]
    if not query:
        return jsonify({
            "output": "julio@cypher:~/solo-mining$ ask \"\"\n\n[ERROR] Digite uma pergunta!\n\nSugestões:\n  • qual a dificuldade da rede agora?\n  • qual a chance de achar bloco com 500th por 7 dias?\n  • como ta minha mineracao?\n  • compara aluguel de 0.01 btc por 24h\n",
            "status": "error"
        })

    output_lines = [f"julio@cypher:~/solo-mining$ ask \"{query[:80]}\"", ""]

    import re
    query_lower = query.lower().strip()
    # Normalize for keyword matching: strip sentence punctuation but preserve decimal dots
    q = re.sub(r'[?!;:]', ' ', query_lower)
    q = re.sub(r'\.(?!\d)', ' ', q)

    # ══ Check patterns: compare first (most specific), then status, calc, network, help ══

    # ── Pattern 1: compare / rental / aluguel ──
    compare_kw = [
        "compara", "comparar", "comparação", "comparacao", "compare",
        "aluguel", "alugar", "aluga", "rental", "alocação", "alocacao",
        "braiins", "brain", "brains", "brians",
        "mrr", "miningrigrentals", "mining rig", "miningrig",
        "qual melhor", "qual vale mais", "qual compensa",
        "vale a pena", "compensa", "mais barato", "melhor opção",
        "custo", "orçamento", "orcamento", "budget",
        "which one", "better", "worth it", "cheaper", "best option",
        "rent", "renting",
    ]
    if any(k in q for k in compare_kw):
        btc_match = re.search(r'(\d+\.?\d*)\s*(btc|sat|sats|bitcoin)', q, re.IGNORECASE)
        dur_match = re.search(r'(\d+\.?\d*)\s*(h|hour|hr|hours|horas|hora|d|day|days|dia|dias)', q)
        if btc_match and dur_match:
            budget = float(btc_match.group(1))
            dur_val = float(dur_match.group(1))
            dur_unit = dur_match.group(2).lower()
            if dur_unit in ('d', 'day', 'days', 'dia', 'dias'):
                dur_val *= 24

            output_lines.append("[OK] Comparação de aluguel detectada")
            output_lines.append(f"      budget={budget} BTC, duração={dur_val:.0f}h")
            output_lines.append("")

            try:
                diff_res = execute_tool("get_network_difficulty")
                difficulty = diff_res.get("difficulty", 127e12)
                braiins_res = execute_tool("get_braiins_orderbook")
                mrr_res = execute_tool("get_mrr_listings")
                braiins_price = braiins_res.get("price_btc_per_ph_day")
                mrr_price = mrr_res.get("price_btc_per_ph_day")

                sm = solo_mining
                results = sm.compare_rentals(
                    budget, difficulty, dur_val,
                    braiins_price, mrr_price,
                    objective="EV", auto_fetch=False,
                )

                if not results:
                    output_lines.append("[ERROR] Nenhuma opção válida de aluguel")
                    output_lines.append("[HINT] Forneça preços manualmente: --braiins <preço> --mrr <preço>")
                else:
                    output_lines.append(f"{'Plataforma':<22s}  {'Preço/PH/d':>10s}   {'Hashpower':>10s}  {'P(bloco)':>9s}  {'E[tempo]':>10s}   {'EV(BTC)':>10s}")
                    output_lines.append(f"{'─'*22}  {'─'*10}   {'─'*10}  {'─'*9}  {'─'*10}   {'─'*10}")
                    for r in results:
                        output_lines.append(
                            f"  {r['platform']:<22s}  {r['price_btc_per_ph_day']:>10.6f}   "
                            f"{r['hashpower_ph']:>8.2f}PH  {r['p_block_pct']:>7.4f}%  "
                            f"{r['expected_time_days']:>8.0f}d  {r['ev_btc']:>+10.6f}"
                        )
                    if any(r.get('ev_btc', -1) < 0 for r in results):
                        output_lines.append("")
                        output_lines.append("[WARN] Todas as opções têm EV negativo. Solo mining é loteria.")
            except Exception as e:
                output_lines.append(f"[ERROR] Falha ao buscar dados: {e}")
                output_lines.append("[HINT] Tente: compare --budget 0.01 --duration 24h")

            return jsonify({"output": "\n".join(output_lines), "status": "success"})

        output_lines.append("[OK] Entendi que é pergunta sobre aluguel de hashrate")
        output_lines.append("[WARN] Preciso de orçamento e duração pra comparar. Exemplo:")
        output_lines.append("[HINT] 'compara braiins vs mrr com 0.01 btc por 24h'")
        output_lines.append("[HINT] Ou use: compare --budget 0.01 --duration 24h")
        return jsonify({"output": "\n".join(output_lines), "status": "partial"})

    # ── Pattern 2: status / dashboard ──
    status_kw = [
        "status", "dashboard", "resumo", "sumario", "sumário",
        "como estou", "como eu to", "como eu tô", "como ta minha",
        "minha mineração", "minha mineracao", "meu minerador",
        "ta funcionando", "tá funcionando", "funcionando",
        "online", "offline", "conectado",
        "how am i", "how's my", "am i mining", "my miner",
        "stats", "summary", "overview",
    ]
    if any(k in q for k in status_kw):
        output_lines.append("[OK] Consulta de status detectada — buscando dados")
        output_lines.append("")

        try:
            diff_res = execute_tool("get_network_difficulty")
            price_res = execute_tool("get_btc_price", {"currencies": "usd,brl"})
            pool_res = execute_tool("get_parasite_pool_stats")

            difficulty = diff_res.get("difficulty", 0)
            prices = price_res.get("prices", {})
            worker_hr = pool_res.get("worker_hashrate", 0)
            pool_hr = pool_res.get("pool_hashrate", 0)

            output_lines.append("╔══════════════════════════════════════════════╗")
            output_lines.append("║          CYPHER MINING STATUS              ║")
            output_lines.append("╚══════════════════════════════════════════════╝")
            output_lines.append("")

            output_lines.append("─── Network ───")
            if difficulty:
                output_lines.append(f"  Difficulty        {difficulty:,.0f}  ({fmt_diff(difficulty)})")
            else:
                output_lines.append("  Difficulty        unavailable")
            if prices:
                parts = []
                if prices.get("usd"): parts.append(f"${prices['usd']:,.0f}")
                if prices.get("brl"): parts.append(f"R${prices['brl']:,.0f}")
                output_lines.append(f"  BTC Price         {' / '.join(parts)}")
            output_lines.append("")

            output_lines.append("─── Worker ───")
            output_lines.append(f"  Hashrate          {worker_hr}" if worker_hr else "  Hashrate          no worker data")
            output_lines.append(f"  Best Share        {pool_res.get('worker_best_diff', '—')}")
            output_lines.append(f"  Status            {pool_res.get('worker_status', 'unknown').upper()}")

            if pool_res.get("worker_uptime"):
                output_lines.append(f"  Uptime            {pool_res['worker_uptime']}")
            output_lines.append("")

            output_lines.append("─── Pool (parasite.space) ───")
            output_lines.append(f"  Pool Hashrate     {pool_hr}" if pool_hr else "  Pool Hashrate     —")
            output_lines.append(f"  Workers           {pool_res.get('pool_workers', '—')} / {pool_res.get('pool_users', '—')} users")
            output_lines.append("")

            try:
                sm = solo_mining
                w_hr = float(worker_hr) if worker_hr else 0
                diff_f = float(difficulty) if difficulty else 0
                if w_hr and diff_f:
                    prob = sm.calc_block_probability(w_hr, diff_f, 86400)
                    exp_time = sm.calc_expected_time(w_hr, diff_f)
                    pct = prob["p_at_least_1_block_pct"]
                    pct_str = f"{pct:.6f}%" if pct < 0.0001 else f"{pct:.4f}%" if pct < 0.01 else f"{pct:.2f}%"

                    output_lines.append("─── 24h Block Probability ───")
                    output_lines.append(f"  P(>=1 block)      {pct_str}")
                    output_lines.append(f"  P(0 blocks)       {prob['p_zero_blocks_pct']:.1f}%")
                    output_lines.append(f"  E[time]           {exp_time['days']:,.0f} dias ({exp_time['years']:.1f} anos)")
                    output_lines.append(f"  Hashes/24h        {w_hr * 86400:,.0f}")
                    output_lines.append("")
                    if pct < 0.01:
                        output_lines.append("[WARN] Probabilidade extremamente baixa — solo mining é loteria.")
            except Exception:
                pass
        except Exception as e:
            output_lines.append(f"[ERROR] Falha ao buscar dados: {e}")

        return jsonify({"output": "\n".join(output_lines), "status": "success"})

    # ── Pattern 3: calc / probability / chance ──
    calc_kw = [
        "calcular", "calcula", "calc", "calulo", "calculo", "cálculo",
        "probabilidade", "probabilida", "prob", "chance", "chances",
        "qual a chance", "quais as chances", "quanto tempo", "tempo esperado",
        "acha bloco", "achar bloco", "encontra bloco", "encontrar bloco",
        "minerar", "minerando", "mineração", "mineracao",
        "quantos blocos", "quantos bloco",
        "probability", "probablity", "probabilty", "odds",
        "chance of", "chances of", "likely", "likelihood",
        "how long", "expected time", "how many",
        "find a block", "finding", "block chance",
        "th/s", "ph/s", "eh/s", "gh/s", "mh/s",
        "ths", "phs", "ehs",
        "hashrate", "hash rate", "hash",
        "se eu", "usando", "durante",
        "solo", "solo mining",
    ]
    if any(k in q for k in calc_kw):
        hr_match = re.search(r'(\d+\.?\d*)\s*(th/s|ph/s|eh/s|gh/s|mh/s|th|ph|eh|gh|mh)', q, re.IGNORECASE)
        dur_match = re.search(r'(\d+\.?\d*)\s*(h|hour|hr|hours|horas|hora|d|day|days|dia|dias|w|week|weeks|semana|semanas)', q)
        if hr_match and dur_match:
            hashrate_str = hr_match.group(1) + hr_match.group(2).upper().replace('/S', '')
            dur_val = float(dur_match.group(1))
            dur_unit = dur_match.group(2).lower()
            if dur_unit in ('d', 'day', 'days', 'dia', 'dias'):
                dur_val *= 24
            elif dur_unit in ('w', 'week', 'weeks', 'semana', 'semanas'):
                dur_val *= 168

            output_lines.append(f"[OK] Entendi: hashrate={hashrate_str}, duração={dur_val:.0f}h")
            output_lines.append("")

            try:
                sm = solo_mining
                hashrate_hs = sm._parse_hashrate(hashrate_str)
                duration_seconds = dur_val * 3600
                diff_res = execute_tool("get_network_difficulty")
                difficulty = diff_res.get("difficulty", 127e12)

                prob = sm.calc_block_probability(hashrate_hs, difficulty, duration_seconds)
                exp_time = sm.calc_expected_time(hashrate_hs, difficulty)

                output_lines.append("─── Block Discovery ───")
                output_lines.append(f"  Hashrate............ {hashrate_hs:,.0f} H/s ({hashrate_str.upper()})")
                output_lines.append(f"  Duração............. {dur_val:.0f}h ({dur_val / 24:.2f} dias)")
                output_lines.append(f"  Dificuldade......... {difficulty:,.0f}")
                output_lines.append(f"  Hashes/bloco........ {prob['hashes_per_block']:,.0f}")
                output_lines.append(f"  Lambda(t)........... {prob['lambda']:.6e}")
                output_lines.append("")
                output_lines.append(f"  P(>=1 bloco)........ {prob['p_at_least_1_block_pct']:.6f}%")
                output_lines.append(f"  P(0 blocos)......... {prob['p_zero_blocks_pct']:.2f}%")
                output_lines.append(f"  E[tempo]............ {exp_time['days']:,.1f} dias ({exp_time['years']:.2f} anos)")
                output_lines.append("")
                output_lines.append("[WARN] Solo mining é loteria. EV é negativo vs pool mining.")
            except Exception as e:
                output_lines.append(f"[ERROR] Falha no cálculo: {e}")
                output_lines.append("[HINT] Tente: calc --hashrate 225TH --duration 24h")

            return jsonify({"output": "\n".join(output_lines), "status": "success"})

        output_lines.append("[OK] Entendi que é pergunta sobre probabilidade de mineração")
        output_lines.append("[WARN] Preciso de hashrate e duração pra calcular. Exemplo:")
        output_lines.append("[HINT] 'qual a chance de achar bloco com 225TH por 24h?'")
        output_lines.append("[HINT] Ou use: calc --hashrate 225TH --duration 24h")
        return jsonify({"output": "\n".join(output_lines), "status": "partial"})

    # ── Pattern 4: network / difficulty / price ──
    network_kw = [
        "rede", "dificuldade", "difculdade", "dificudade", "dificul", "network",
        "preco", "preço", "cotação", "cotacao", "quanto ta", "quanto tá",
        "ta valendo", "tá valendo", "valor", "preço btc", "preco btc",
        "bitcoin price", "btc price", "btc/usd", "btc/brl",
        "difficulty", "dificulty", "diff", "current", "price", "btc",
        "what's the", "what is the", "how much",
        "como ta", "como tá", "como esta", "como está",
        "me mostra", "mostra", "show me", "show",
        "da rede", "atual", "hoje", "now", "today",
    ]
    if any(k in q for k in network_kw):
        output_lines.append("[OK] Consulta de rede detectada — buscando dados")
        output_lines.append("")

        try:
            diff_res = execute_tool("get_network_difficulty")
            price_res = execute_tool("get_btc_price", {"currencies": "usd,brl"})
            prices = price_res.get("prices", {})

            if diff_res.get("difficulty"):
                diff = diff_res["difficulty"]
                output_lines.append("─── Network Difficulty ───")
                output_lines.append(f"  difficulty........ {diff:,.0f}")
                output_lines.append(f"  formatted......... {fmt_diff(diff)}")
                output_lines.append(f"  source............ {diff_res.get('source', 'agent tool')}")
            else:
                output_lines.append(f"[ERROR] Difficulty: {diff_res.get('error', 'unavailable')}")

            output_lines.append("")
            output_lines.append("─── BTC Price ───")
            if prices:
                if prices.get("usd"):
                    output_lines.append(f"  btc/usd........... ${prices['usd']:,.0f}")
                if prices.get("brl"):
                    output_lines.append(f"  btc/brl........... R${prices['brl']:,.0f}")
                output_lines.append(f"  source............ {price_res.get('source', 'coingecko.com')}")
            else:
                output_lines.append(f"[ERROR] BTC price: {price_res.get('error', 'unavailable')}")
        except Exception as e:
            output_lines.append(f"[ERROR] Falha ao buscar dados: {e}")

        return jsonify({"output": "\n".join(output_lines), "status": "success"})

    # ── Pattern 5: help ──
    help_kw = ["help", "ajuda", "ajudar", "socorro", "comandos", "commands", "o que faz", "o que vc faz"]
    if any(k in q for k in help_kw):
        output_lines.append("[OK] Ajuda:")
        output_lines.append("")
        output_lines.append("  network                          — Dificuldade da rede + preço do BTC")
        output_lines.append("  calc --hashrate <H> --duration <h> — Probabilidade de minerar")
        output_lines.append("  compare --budget <BTC> --duration <h> — Comparar aluguel")
        output_lines.append("  status                           — Dashboard completo")
        output_lines.append("  ask <pergunta>                    — Pergunta em linguagem natural")
        output_lines.append("")
        output_lines.append("  Exemplos:")
        output_lines.append("    • 'qual a dificuldade da rede?'")
        output_lines.append("    • 'chance de achar bloco com 500th por 7 dias'")
        output_lines.append("    • 'compara aluguel de 0.01 btc por 24h'")
        output_lines.append("    • 'como ta minha mineracao?'")
        return jsonify({"output": "\n".join(output_lines), "status": "success"})

    # ── Fallback: can't parse, but be friendly ──
    output_lines.append("[WARN] Não entendi exatamente o que você quer, mas posso ajudar com:")
    output_lines.append("")
    output_lines.append("  • 'network' — dificuldade e preço do BTC agora")
    output_lines.append("  • 'status' — resumo completo da sua mineração")
    output_lines.append("  • 'calc --hashrate 225TH --duration 24h' — chance de achar bloco")
    output_lines.append("  • 'compare --budget 0.01 --duration 24h' — comparar aluguel de hashrate")
    output_lines.append("  • 'help' — todos os comandos")
    output_lines.append("")
    output_lines.append("  Ou me pergunte de outro jeito, tipo:")
    output_lines.append("  'qual a chance de achar bloco com 500th por 7 dias?'")
    output_lines.append("  'compara braiins vs mrr com 0.01 btc por 24h'")
    output_lines.append("  'como ta minha mineracao?'")
    return jsonify({"output": "\n".join(output_lines), "status": "unrecognized"})


if __name__ == "__main__":
    banner = r"""
   ▄████████  ▄██   ▄    ▄███████▄ ▄██   ▄      ▄████████  ▄████████
  ███    ███ ███   ██▄ ███    ███ ███   ██▄   ███    ███ ███    ███
  ███    █▀  ███▄▄▄███ ███    ███ ███▄▄▄███   ███    █▀  ███    █▀
  ███        ▀▀▀▀▀▀███ ███    ███ ▀▀▀▀▀▀███  ▄███▄▄▄    ▄███▄▄▄
▀███████████ ▄██   ███ ███    ███ ▄██   ███ ▀▀███▀▀▀   ▀▀███▀▀▀
         ███ ███   ███ ███    ███ ███   ███   ███    █▄  ███    █▄
   ▄█    ███ ███   ███ ███    ███ ███   ███   ███    ███ ███    ███
 ▄████████▀   ▀█████▀  ████████▀   ▀█████▀    ██████████ ██████████
"""
    print(banner)
    print(f"\n  cypher65 war room // parasite pool monitoring")
    print(f"  port {PORT}  |  address {BTC_ADDRESS[:10]}…{BTC_ADDRESS[-6:]}")
    print(f"  worker {WORKER_NAME}  |  poll interval {POLL_INTERVAL}s\n")
    print(f"  DB: {DB_PATH}\n")

    # Prime: run one poll immediately so the dashboard has data on first load
    polling.poll_once()

    # Background poll loop (daemon thread)
    import threading
    t = threading.Thread(target=polling.poll_loop, daemon=True)
    t.start()

    app.run(host="0.0.0.0", port=PORT, debug=False, threaded=True)
