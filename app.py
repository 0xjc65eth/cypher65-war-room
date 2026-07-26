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

# ── Load .env if present (python-dotenv must be installed) ──
try:
    from dotenv import load_dotenv
    load_dotenv()
    logging.getLogger("cypher65").info("[env] loaded .env file")
except ImportError:
    pass  # python-dotenv not installed — env vars must be set manually

from flask import Flask, jsonify, render_template, request, abort, send_from_directory
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
    "",
)
WORKER_NAME = os.environ.get("WORKER_NAME", "")
PARASITE_API = "https://parasite.space/api"
MEMPOOL_API = "https://mempool.space/api"
DATA_DIR = Path(__file__).parent / "data"
DB_PATH = 'data/war_room.sqlite'
POLL_INTERVAL = int(os.environ.get("POLL_INTERVAL", 15))  # seconds
PORT = int(os.environ.get("PORT", 8765))
RATE_LIMIT_PER_MINUTE = int(os.environ.get("RATE_LIMIT_PER_MINUTE", 60))

DATA_DIR.mkdir(exist_ok=True)
app = Flask(__name__)
app.jinja_env.auto_reload = True


# Wallet address source tracking: 'env' | 'db' | 'ui'
# Set at startup based on where the address came from.
WALLET_ADDRESS_SOURCE = os.environ.get("WALLET_SOURCE", "none")


# ── Restore persisted wallet address from settings DB ──
# After init_db() runs below, check if a custom address was saved via
# the UI's /api/set-address endpoint. If found, override the env-var
# default so polling targets the right wallet across server restarts.
def _reset_session_state():
    """Completely wipe all session state to isolate the new address.
    Called on address change to prevent data leakage between sessions.
    Uses defensive try/except for each attribute since some are optional
    and only exist when certain modules are loaded."""
    global _settings_cache
    _settings_cache = None
    
    def _safe_wipe(obj, attr, default=None):
        """Safely wipe or reset a state attribute."""
        try:
            val = getattr(obj, attr, None)
            if val is not None:
                if isinstance(val, list):
                    val.clear()
                elif isinstance(val, dict):
                    val.clear()
                elif isinstance(val, int) or isinstance(val, float):
                    setattr(obj, attr, 0)
                elif val is True or val is False:
                    pass  # leave booleans alone
                else:
                    setattr(obj, attr, default)
        except Exception:
            pass
    
    # Wipe shared in-memory state — every attribute is optional/present only
    # when the corresponding module is loaded.
    try:
        if hasattr(state, "latest_snapshot") and isinstance(state.latest_snapshot, dict):
            state.latest_snapshot.clear()
            state.latest_snapshot.update({"ts": int(time.time())})
    except Exception:
        pass
    _safe_wipe(state, "memory_critical_alerts")
    _safe_wipe(state, "memory_share_buffer")
    _safe_wipe(state, "memory_live_log")
    _safe_wipe(state, "last_known_prices")
    _safe_wipe(state, "event_counter")
    # Re-initialize timeline_state with full defaults (not just .clear())
    # so all direct key accesses in poll_once work after session reset.
    import collections as _collections
    state.timeline_state = {
        "_primed": False,
        "last_submit_ts": 0,
        "last_best_diff_str": "",
        "all_time_best_diff_raw": 0.0,
        "share_submit_history": _collections.deque(maxlen=64),
        "share_calc_history": _collections.deque(maxlen=120),
        "session_share_count": 0,
        "session_best_diff_bumps": 0,
    }
    state.test_opportunities = None
    state.session_share_count = 0
    # Optional attributes — only reset if they exist
    try:
        state.profit_cache.clear()
    except Exception:
        pass
    try:
        state.profit_cache_hit = 0
    except Exception:
        pass
    try:
        state.consecutive_poll_failures = 0
    except Exception:
        pass
    try:
        state.lm_share_counter = 0
    except Exception:
        pass
    # Reset proximity state
    try:
        proximity.reset_session()
    except Exception:
        pass
    log.info("[wallet] session state wiped for address change")


def _restore_btc_address_from_db():
    """Override module-level BTC_ADDRESS if a _btc_address is stored in settings."""
    global BTC_ADDRESS, WALLET_ADDRESS_SOURCE
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT value FROM settings WHERE key='_btc_address'")
        r = c.fetchone()
        conn.close()
        if r and r["value"]:
            addr = str(r["value"]).strip()
            if addr and len(addr) >= 10:
                BTC_ADDRESS = addr
                WALLET_ADDRESS_SOURCE = 'db'
                log.info("[wallet] restored BTC_ADDRESS from DB: %s…%s", addr[:10], addr[-6:])
                # Log the restore event to wallet_history
                try:
                    _log_wallet_change(addr, 'db')
                except Exception:
                    pass
                return True
    except Exception as e:
        log.warning("[wallet] DB restore failed: %s", e)
    return False


# ── Wallet address history helper (defined early so module-level code can use it) ──
def _log_wallet_change(address, source, prev_address=None):
    """Insert a row into wallet_history to track address changes."""
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute(
            "INSERT INTO wallet_history (ts, address, source, prev_address) VALUES (?,?,?,?)",
            (int(time.time()), address, source, prev_address),
        )
        conn.commit()
        conn.close()
    except Exception as e:
        log.warning("[wallet_history] log error: %s", e)


app.secret_key = os.environ.get("SECRET_KEY", os.urandom(32).hex())

# ━━ Simple in-memory rate limiter ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
_rate_limit_store = {}  # {ip: [timestamps]}

@app.before_request
def rate_limit():
    """Simple rate limiter: max RATE_LIMIT_PER_MINUTE requests per IP per minute.
    Skips static files, healthz, and agent discovery endpoints."""
    # Public endpoints: static files, health checks, and agent discovery only
    if request.path.startswith('/static') or request.path in ('/healthz', '/api/healthz') or request.path == '/api/agents/solo-mining':
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
        """CREATE TABLE IF NOT EXISTS wallet_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts INTEGER NOT NULL,
            address TEXT NOT NULL,
            source TEXT NOT NULL,
            prev_address TEXT
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
    c.execute(
        "CREATE INDEX IF NOT EXISTS idx_wallet_history_ts ON wallet_history(ts)"
    )
    # ── WAL mode for better concurrent read/write ──
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA synchronous=NORMAL")
    c.execute("PRAGMA cache_size=-8000")  # 8MB cache
    c.execute("PRAGMA busy_timeout=3000")
    conn.commit()
    conn.close()


init_db()
_restore_btc_address_from_db()

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
    """Serve the main dashboard page."""
    resp = app.make_response(render_template(
        "dashboard.html",
        worker=WORKER_NAME,
        address=BTC_ADDRESS,
        poll_interval=POLL_INTERVAL,
    ))
    resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    resp.headers["Pragma"] = "no-cache"
    resp.headers["Expires"] = "0"
    return resp


@app.route("/hermes")
def hermes_ui():
    """Serve the Hermes Intelligence chat interface."""
    resp = app.make_response(render_template("hermes.html"))
    resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    resp.headers["Pragma"] = "no-cache"
    resp.headers["Expires"] = "0"
    return resp


@app.route("/sw.js")
def service_worker():
    """Serve the Service Worker with the Service-Worker-Allowed header
    so it can control the entire origin (scope=/)."""
    resp = send_from_directory(
        app.static_folder,
        "sw.js",
        mimetype="application/javascript",
    )
    resp.headers["Service-Worker-Allowed"] = "/"
    resp.headers["Cache-Control"] = "no-cache"
    return resp


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
    return jsonify({"metric": metric, "history": rows, "range": rng})


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
    """CYPHER SOLO MINING ADVISOR v1.0 — natural language mining companion.

    Personality-driven agent that responds in Brazilian Portuguese or English,
    matching the user's tone (casual → street, technical → precise).
    Never forces command syntax. Never says "Unknown command".

    Priority order:
      1. Social greetings & community shout-outs
      2. Casual status queries (using real session data from state.latest_snapshot)
      3. Natural language mining calculations (probability, hashrate, duration)
      4. Rental comparisons (Braiins, MRR, budget)
      5. Network & price queries
      6. Help
      7. Structured commands (still supported, not required)
      8. Friendly fallback
    """

    # ── Quick helper to pull data from session snapshot ──
    def _session_data():
        snap = state.latest_snapshot or {}
        worker = snap.get("worker") or {}
        network = snap.get("network") or {}
        return {
            "hashrate": worker.get("hashrate") or 0,
            "best_diff": worker.get("bestDifficulty") or "—",
            "last_submit": worker.get("lastSubmission") or 0,
            "status": worker.get("status") or "unknown",
            "workers": snap.get("all_workers") or [],
            "net_diff": network.get("difficulty") or 0,
            "net_hashrate": network.get("hashrate") or 0,
            "ts": snap.get("ts") or 0,
            "btc_usd": snap.get("btc_usd") or 0,
            "pool_hashrate": snap.get("pool_hashrate") or 0,
            "pool_workers": snap.get("pool_workers") or 0,
            "address": snap.get("address") or BTC_ADDRESS,
        }

    if not _solo_advisor_loaded:
        return jsonify({"error": "Agent not loaded"}), 503

    body = request.get_json(silent=True) or {}
    query = (body.get("query") or "").strip()[:300]
    if not query:
        return jsonify({
            "output": "Eae! Me manda uma pergunta sobre mineração que eu te ajudo.\n\nTipo:\n  • como ta minha mineracao?\n  • qual a chance de achar bloco com 500th por 7 dias?\n  • qual a dificuldade da rede agora?\n  • compara aluguel de 0.01 btc por 24h\n",
            "status": "prompt"
        })

    import re
    query_lower = query.lower().strip()
    q = re.sub(r'[?!;:]', ' ', query_lower)
    q = re.sub(r'\.(?!\d)', ' ', q)

    # Detect user tone: casual indicators flip the response style
    casual_indicators = ["eae", "eai", "fala", "salve", "cumpade", "cumpr", "parceiro",
                          "irmao", "irmão", "mano", "bro", "dae", "dai", "opa", "bora",
                          "blz", "beleza", "tranquilo", "suave", "pow", "po", "bah"]
    is_casual = any(k in q for k in casual_indicators)

    # ── 1. SOCIAL & COMMUNITY ────────────────────────────────────────────
    social_kw = ["eae", "eai", "fala", "salve", "opa", "dae", "dai", "bora"]
    community_kw = ["comunidade", "bitminer", "bit miner", "33", "salve pra", "da um salve"]

    if any(k in q for k in social_kw) and not any(k in q for k in ["hashrate", "chance", "dif", "calc"]):
        if any(k in q for k in community_kw):
            responses = [
                "Salve pra comunidade Bitminer 33! 👊 Tamo junto, que o bloco saia logo pra geral. Mineração solo é osso mas quando vem, vem forte.",
                "Fala pro povo da Bitminer 33 que o CYPHER tá on! 🔥 Que a sorte acompanhe cada hash de vocês.",
                "Bitminer 33 na área! 👊 Tamo junto nessa luta. Solo mining é loteria, mas alguém tem que ganhar — pode ser nós.",
            ]
        elif "cumpade" in q or "parceiro" in q or "mano" in q or "irmão" in q:
            responses = [
                "Eae parceiro! 👊 Tamo junto, só falar o que cê precisa.",
                "Fala irmão! Tudo tranquilo? Me pergunta o que quiser sobre mineração.",
                "Salve salve! Tamo on. O que cê quer saber?"]
        else:
            responses = [
                "Eae! Tudo certo? Me pergunta sobre mineração que eu ajudo.",
                "Fala aí! O que cê precisa? Dificuldade, hashrate, aluguel — tô dentro.",
                "Salve! CYPHER Solo Mining Advisor na área. Pode perguntar."]
        import random
        return jsonify({"output": random.choice(responses), "status": "social"})

    # ── 2. STATUS (usando dados REAIS da sessão) ────────────────────────
    status_kw = ["status", "dashboard", "resumo", "sumario", "sumário",
                 "como estou", "como eu to", "como eu tô", "como ta minha",
                 "minha mineração", "minha mineracao", "meu minerador",
                 "ta funcionando", "tá funcionando", "funcionando",
                 "to online", "tô online", "online", "offline", "conectado",
                 "how am i", "how's my", "am i mining", "my miner",
                 "stats", "summary", "overview",
                 "ta hasheando", "tá hasheando", "hashrate", "qual hashrate",
                 "minha hashrate", "meu best diff", "qual meu best",
                 "minerando", "minerou",
                 "to on", "to off", "tô on", "tô off"]
    if any(k in q for k in status_kw):
        sd = _session_data()

        # Check if we have real data
        if sd["address"] and sd["ts"] > 0 and sd["hashrate"]:
            hr_val = sd["hashrate"]
            if hr_val >= 1e12:
                hr_display = f"{hr_val / 1e12:.2f} TH/s"
            elif hr_val >= 1e9:
                hr_display = f"{hr_val / 1e9:.2f} GH/s"
            else:
                hr_display = f"{hr_val:.0f} H/s"

            status_emoji = {"hashing": "🟢", "online": "🟢", "idle": "🟡", "offline": "🔴", "unknown": "⚪"}.get(
                sd["status"].lower(), "⚪")

            last_share = ""
            if sd["last_submit"]:
                age_s = int(time.time()) - sd["last_submit"]
                if age_s < 60:
                    last_share = f"{age_s}s atrás"
                elif age_s < 3600:
                    last_share = f"{age_s // 60}min atrás"
                else:
                    last_share = f"{age_s // 3600}h atrás"

            workers_total = len(sd["workers"])

            out = f"""📊 **Status da Mineração**

{status_emoji} **Estado:** {sd['status'].upper()}
⚡ **Hashrate:** {hr_display}
🏆 **Best Difficulty:** {sd['best_diff']}
🕐 **Último Share:** {last_share or '—'}
👷 **Workers ativos:** {workers_total}

📡 Pool: parasite.space ({sd['pool_hashrate'] / 1e12:.2f} TH/s agregado)

"""
            # Se tiver dificuldade de rede, calcula probabilidade 24h
            if sd["net_diff"] and sd["hashrate"]:
                try:
                    sm = solo_mining
                    prob = sm.calc_block_probability(float(sd["hashrate"]), float(sd["net_diff"]), 86400)
                    exp_time = sm.calc_expected_time(float(sd["hashrate"]), float(sd["net_diff"]))
                    pct = prob["p_at_least_1_block_pct"]
                    out += f"📈 **P(≥1 bloco em 24h):** {pct:.6f}%\n"
                    out += f"⏳ **Tempo esperado:** {exp_time['days']:,.0f} dias\n"
                    if pct < 0.001:
                        out += "\n⚠️ Lembrando: solo mining é loteria. Cada hash é uma chance nova."
                except Exception:
                    pass

            return jsonify({"output": out, "status": "success"})
        else:
            out = "Ainda não tenho dados dessa carteira carregados. Conecta sua wallet ou cola um endereço BTC que eu te mostro o status."
            return jsonify({"output": out, "status": "nodata"})

    # ── 3. CALC / PROBABILITY (natural language) ────────────────────────
    calc_indicators = [
        "chance", "probabilidade", "probabilidade", "prob", "odds", "likelihood",
        "calcular", "calcula", "calc", "calculo", "cálculo",
        "acha bloco", "achar bloco", "encontra bloco", "encontrar bloco", "find block",
        "minerar", "minerando", "mineração", "mineracao",
        "bloco", "block", "quanto tempo", "tempo esperado", "expected time",
        "th/s", "ph/s", "eh/s", "gh/s", "mh/s", "ths", "phs", "ehs",
        "hashrate", "hash rate", "hash",
        "solo", "solo mining",
        "se eu", "usando", "durante", "com",
    ]
    if any(k in q for k in calc_indicators):
        hr_match = re.search(r'(\d+\.?\d*)\s*(th/s|ph/s|eh/s|gh/s|mh/s|th|ph|eh|gh|mh|t|p|e|g|m)', q, re.IGNORECASE)
        dur_match = re.search(r'(\d+\.?\d*)\s*(h|hour|hr|hours|horas|hora|d|day|days|dia|dias|w|week|weeks|semana|semanas)', q)

        if hr_match:
            hr_raw = hr_match.group(1) + hr_match.group(2).upper().rstrip('/S')
            dur_val = 24.0  # default 24h
            if dur_match:
                dur_val = float(dur_match.group(1))
                dur_unit = dur_match.group(2).lower()
                if dur_unit in ('d', 'day', 'days', 'dia', 'dias'):
                    dur_val *= 24
                elif dur_unit in ('w', 'week', 'weeks', 'semana', 'semanas'):
                    dur_val *= 168

            try:
                sm = solo_mining
                hashrate_hs = sm._parse_hashrate(hr_raw)
                duration_seconds = dur_val * 3600
                diff_res = execute_tool("get_network_difficulty")
                difficulty = diff_res.get("difficulty", 127e12)

                prob = sm.calc_block_probability(hashrate_hs, difficulty, duration_seconds)
                exp_time = sm.calc_expected_time(hashrate_hs, difficulty)
                pct = prob["p_at_least_1_block_pct"]

                if dur_val >= 24:
                    dur_display = f"{dur_val/24:.1f} dias" if dur_val > 24 else "24h"
                else:
                    dur_display = f"{dur_val:.0f}h"

                if pct < 0.01:
                    pct_str = f"{pct:.6f}%"
                elif pct < 1:
                    pct_str = f"{pct:.4f}%"
                else:
                    pct_str = f"{pct:.2f}%"

                out = f"""📊 **Análise de Mineração Solo**

⚡ **Hashrate:** {hashrate_hs/1e12:.2f} TH/s
⏱ **Período:** {dur_display}
🔢 **Dificuldade da Rede:** {difficulty:,.0f}

📈 **P(≥1 bloco):** {pct_str}
📉 **P(0 blocos):** {prob['p_zero_blocks_pct']:.2f}%
⏳ **Tempo esperado p/ bloco:** {exp_time['days']:,.0f} dias ({exp_time['years']:.1f} anos)

⚠️ Solo mining é loteria — EV negativo vs pool mining.
Cada hash é uma tentativa independente.
"""
                return jsonify({"output": out, "status": "success"})
            except Exception as e:
                return jsonify({"output": f"Vish, deu erro no cálculo: {e}. Me passa os dados certinhos tipo '225TH por 24h' que eu calculo.", "status": "error"})

        # Mentioned calc but couldn't parse hashrate
        out = "Entendi que cê quer calcular chance de achar bloco! Me passa o hashrate e o período. Tipo:\n  • 'chance com 225TH em 24 horas'\n  • '500TH por 7 dias'\n  • 'calc 300TH 48h'"
        return jsonify({"output": out, "status": "partial"})

    # ── 4. COMPARE / RENTAL ─────────────────────────────────────────────
    compare_kw = ["compara", "comparar", "comparação", "comparacao", "compare",
                  "aluguel", "alugar", "aluga", "rental", "alocação", "alocacao",
                  "braiins", "brain", "brains", "brians",
                  "mrr", "miningrigrentals", "mining rig", "miningrig",
                  "refinery", "qual melhor", "qual vale mais", "qual compensa",
                  "vale a pena", "compensa", "mais barato", "melhor opção",
                  "custo", "orçamento", "orcamento", "budget",
                  "which one", "better", "worth it", "cheaper", "best option",
                  "rent", "renting"]
    if any(k in q for k in compare_kw):
        btc_match = re.search(r'(\d+\.?\d*)\s*(btc|sat|sats|bitcoin)', q, re.IGNORECASE)
        dur_match = re.search(r'(\d+\.?\d*)\s*(h|hour|hr|hours|horas|hora|d|day|days|dia|dias)', q)

        if btc_match and dur_match:
            budget = float(btc_match.group(1))
            dur_val = float(dur_match.group(1))
            dur_unit = dur_match.group(2).lower()
            if dur_unit in ('d', 'day', 'days', 'dia', 'dias'):
                dur_val *= 24

            out_lines = [f"📊 Comparando aluguel de {budget} BTC por {dur_val:.0f}h...", ""]

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
                    out_lines.append("Não achei ofertas válidas agora. Pode ser que os preços de mercado estejam indisponíveis.")
                    out_lines.append("Tenta de novo mais tarde ou passa os preços manualmente.")
                else:
                    for r in results:
                        ev_str = f"{r['ev_btc']:+.6f}"
                        out_lines.append(f"**{r['platform'].upper()}**")
                        out_lines.append(f"  Preço: {r['price_btc_per_ph_day']:.6f} BTC/PH/dia")
                        out_lines.append(f"  Hashpower: {r['hashpower_ph']:.2f} PH/s")
                        out_lines.append(f"  P(bloco): {r['p_block_pct']:.4f}%")
                        out_lines.append(f"  E[tempo]: {r['expected_time_days']:.0f} dias")
                        out_lines.append(f"  EV: {ev_str} BTC")
                        out_lines.append("")

                    if any(r.get('ev_btc', -1) < 0 for r in results):
                        out_lines.append("⚠️ **Aviso:** Todas as opções têm EV negativo. Aluguel de hashrate pra solo mining é loteria — você tá pagando pra ter uma chance, não um retorno garantido.")
            except Exception as e:
                out_lines.append(f"Erro ao buscar dados de mercado: {e}")
                out_lines.append("Tenta: 'compara braiins vs mrr com 0.01 btc por 24h'")

            return jsonify({"output": "\n".join(out_lines), "status": "success"})

        out = "Quer comparar aluguel de hashrate? Manda o orçamento e o tempo. Tipo:\n  • 'compara braiins e mrr com 0.01 btc por 24h'\n  • 'qual compensa mais alugar agora?'"
        return jsonify({"output": out, "status": "partial"})

    # ── 5. NETWORK / PRICE ──────────────────────────────────────────────
    network_kw = ["rede", "dificuldade", "difculdade", "dificudade", "dificul", "network",
                  "preco", "preço", "cotação", "cotacao", "quanto ta", "quanto tá",
                  "ta valendo", "tá valendo", "valor", "preço btc", "preco btc",
                  "bitcoin price", "btc price", "btc/usd", "btc/brl",
                  "difficulty", "dificulty", "diff", "current", "price", "btc",
                  "what's the", "what is the", "how much",
                  "como ta", "como tá", "como esta", "como está",
                  "me mostra", "mostra", "show me", "show",
                  "da rede", "atual", "hoje", "now", "today"]
    if any(k in q for k in network_kw):
        out_lines = ["📡 **Dados da Rede Bitcoin**", ""]

        try:
            diff_res = execute_tool("get_network_difficulty")
            price_res = execute_tool("get_btc_price", {"currencies": "usd,brl"})
            prices = price_res.get("prices", {})

            if diff_res.get("difficulty"):
                diff = diff_res["difficulty"]
                out_lines.append(f"🔢 **Dificuldade:** {diff:,.0f} ({fmt_diff(diff)})")
            else:
                out_lines.append(f"🔢 Dificuldade: indisponível")

            out_lines.append("")
            if prices:
                parts = []
                if prices.get("usd"): parts.append(f"${prices['usd']:,.0f}")
                if prices.get("brl"): parts.append(f"R${prices['brl']:,.0f}")
                out_lines.append(f"💲 **BTC Preço:** {' / '.join(parts)}")
            else:
                out_lines.append("💲 Preço BTC: indisponível")
        except Exception as e:
            out_lines.append(f"Erro ao buscar dados: {e}")

        return jsonify({"output": "\n".join(out_lines), "status": "success"})

    # ── 6. HELP ─────────────────────────────────────────────────────────
    help_kw = ["help", "ajuda", "ajudar", "socorro", "comandos", "commands", "o que faz", "o que vc faz", "o que voce faz"]
    if any(k in q for k in help_kw):
        out = """🤙 **CYPHER Solo Mining Advisor** — tô aqui pra ajudar com mineração.

Pode perguntar naturalmente, tipo:

📊 **Status:** 'como ta minha mineracao?'
📈 **Probabilidade:** 'qual a chance de achar bloco com 500th por 7 dias?'
💰 **Comparar aluguel:** 'compara braiins vs mrr com 0.01 btc por 24h'
🌐 **Rede:** 'qual a dificuldade da rede agora?'

Comandos estruturados (se preferir):
  network                  → dificuldade + preço BTC
  calc --hashrate <H> --duration <h>  → probabilidade
  compare --budget <BTC> --duration <h> → comparar aluguel
  status                   → dashboard completo
"""
        return jsonify({"output": out, "status": "success"})

    # ── 7. STRUCTURED COMMANDS (power users) ────────────────────────────
    # "calc 225TH 24h" or "compare 0.01 btc 24h" style
    if q.startswith("calc ") or q.startswith("compare ") or q.startswith("network") or q.startswith("status") or q.startswith("clear"):
        # Re-run through the existing compare/calc/network/status logic
        # These are handled by the patterns above; this is a belt-and-suspenders
        pass  # will fall through to the existing /api/solo-mining/calc route

    # ── 8. FRIENDLY FALLBACK ───────────────────────────────────────────
    if is_casual:
        out = "Fala aí! Não captei bem o que cê quis dizer, mas posso ajudar com status, probabilidade de bloco, aluguel de hashrate, dificuldade da rede… É só perguntar!"
    else:
        out = """Não entendi exatamente, mas me pergunta de outro jeito! Exemplos:

• 'como ta minha mineracao?'
• 'qual a chance de achar bloco com 500th por 7 dias?'
• 'compara aluguel de 0.01 btc por 24h'
• 'qual a dificuldade da rede agora?'
• 'help'
"""
    return jsonify({"output": out, "status": "unrecognized"})


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Wallet address setter + Opportunity Engine endpoints
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@app.route("/api/set-address", methods=["POST"])
def api_set_address():
    """Update the BTC address the dashboard monitors.
    POST JSON: {"address": "bc1..."}
    This changes the polling target for subsequent poll() calls.
    Performs COMPLETE session wipe before loading the new address
    to prevent ANY data leakage between addresses."""
    body = request.get_json(silent=True) or {}
    addr = (body.get("address") or "").strip()
    if not addr or len(addr) < 10:
        return jsonify({"error": "invalid address"}), 400
    global BTC_ADDRESS, WALLET_ADDRESS_SOURCE
    prev = BTC_ADDRESS
    
    # ── WIPE THE ENTIRE SESSION BEFORE SWITCHING ──
    _reset_session_state()
    
    WALLET_ADDRESS_SOURCE = 'ui'
    BTC_ADDRESS = addr
    # Update config for the polling module
    try:
        polling.config.BTC_ADDRESS = addr
    except Exception:
        pass
    log.info("[wallet] address changed to %s…%s", addr[:10], addr[-6:])
    # Persist in settings DB so it survives server restart
    save_setting("_btc_address", addr)
    # Log address change to wallet_history
    _log_wallet_change(addr, 'ui', prev_address=prev if prev != addr else None)
    # Update polling config
    try:
        polling.config.BTC_ADDRESS = addr
    except Exception:
        pass
    # Log event
    from helpers import make_memory_alert
    state.memory_critical_alerts.append(make_memory_alert(
        int(time.time()), "SUCCESS", "wallet_changed",
        f"Wallet address changed to {addr[:10]}…{addr[-6:]}; polling target updated."
    ))
    # Prime an immediate poll with the new address
    polling.poll_once()
    return jsonify({"ok": True, "address": addr})


import agents.opportunity_engine as opportunity_engine


@app.route("/api/wallet")
def api_wallet():
    """Return current wallet address info: address, source (env/db/ui),
    and change history from wallet_history table."""
    history = []
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute(
            "SELECT ts, address, source, prev_address FROM wallet_history "
            "ORDER BY id DESC LIMIT 50"
        )
        for r in c.fetchall():
            entry = {"ts": r["ts"], "address": r["address"], "source": r["source"]}
            if r["prev_address"]:
                entry["prev_address"] = r["prev_address"]
            history.append(entry)
        conn.close()
    except Exception as e:
        log.warning("[api/wallet history] error: %s", e)

    return jsonify({
        "address": BTC_ADDRESS,
        "source": WALLET_ADDRESS_SOURCE,
        "history": history,
        "ts": int(time.time()),
    })


@app.route("/api/opportunities")
def api_opportunities():
    """Opportunity Engine — scans Braiins/MRR markets for deals.
    Returns a list of opportunities matching user's context.
    All clearly labeled as ESTIMATED/REAL.
    Delegates to agents/opportunity_engine.py for the actual scan.

    If state.test_opportunities is set (via POST /api/opportunities/mock),
    returns that mock data instead of scanning real markets."""
    # Injected mock opportunities are TEST-ONLY — never served in production.
    # If state.test_opportunities was set via debug endpoint, skip it here.
    # (The mock injection endpoint is gated behind DEBUG_MOCK=1)

    try:
        from agents.solo_mining_advisor import execute_tool
        opps, scan_stats = opportunity_engine.scan(execute_tool, state.latest_snapshot, state.last_known_prices)
        return jsonify(opportunity_engine.build_response(opps, scan_stats))
    except Exception as e:
        log.warning("[opportunities] scan error: %s", e)
        return jsonify({
            "opportunities": [],
            "ts": int(time.time()),
            "disclaimer": "All prices are ESTIMATED based on current market data. Actual rental prices vary."
        })


# ── Mock opportunity injector (for visual testing of the popup UI) ──

MOCK_OPPORTUNITIES = [
    {
        "id": "mock_braiins_0.015",
        "platform": "braiins",
        "title": "🔥 TEST · Braiins 15.0 sats/PH/day",
        "description": (
            "With 225.0 TH/s you could mine ~0.0034 BTC/day equivalent. "
            "This is a MOCK opportunity — not real market data."
        ),
        "meta": "source: MOCK TEST DATA — opportunity engine bypassed",
        "price": 0.000015,
        "severity": "INFO",
        "status": "MOCK",
    },
    {
        "id": "mock_mrr_0.012",
        "platform": "mrr",
        "title": "⚡ TEST · MRR 12.0 sats/PH/day (20% cheaper)",
        "description": (
            "MiningRigRentals has active listings — this is a MOCK test "
            "opportunity to verify the popup UI rendering."
        ),
        "meta": "source: MOCK TEST DATA — does not reflect real market prices",
        "price": 0.000012,
        "severity": "INFO",
        "status": "MOCK",
    },
]


@app.route("/api/opportunities/mock", methods=["POST"])
def api_opportunities_mock():
    """[DEV ONLY] Inject mock opportunities for visual testing.
    This endpoint MUST NEVER be used in production.
    It is protected by the DEBUG_MOCK environment variable.

    Set DEBUG_MOCK=1 to enable. Otherwise this endpoint returns 403.
    """
    if os.environ.get("DEBUG_MOCK") != "1":
        abort(403, description="Mock mode disabled. Set DEBUG_MOCK=1 to enable.")

    body = request.get_json(silent=True) or {}
    opps = body.get("opportunities", MOCK_OPPORTUNITIES)

    state.test_opportunities = {
        "opportunities": opps,
        "ts": int(time.time()),
        "disclaimer": (
            "⚠️ DEVELOPMENT / MOCK DATA ONLY — NOT REAL MARKET PRICES. "
            "This mode must never be enabled in production."
        ),
        "mode": "MOCK",
    }

    log.warning("[opportunities/mock] MOCK MODE ENABLED — %d fake opportunities injected", len(opps))
    return jsonify(state.test_opportunities)


@app.route("/api/opportunities/mock/clear", methods=["POST"])
def api_opportunities_mock_clear():
    """Clear injected mock opportunities and restore real market scanning."""
    state.test_opportunities = None
    log.info("[opportunities/mock] cleared — restored real scanning")
    return jsonify({"status": "cleared", "message": "Real market scanning restored."})

from hermes_register import register_hermes
register_hermes(app)

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
