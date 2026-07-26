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
    Skips static files and the /healthz endpoint."""
    if request.path.startswith('/static') or request.path == '/healthz' or request.path == '/api/healthz':
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

# Timeline delta tracker ─ tracks last known values across polls
# so we can flag REAL events (share submit, best-diff bump, work deltas)
# without exposing per-share logs (which the pool simply doesn't publish).
timeline_state = {
    "_primed": False,              # becomes True after the first priming poll
    "last_submit_ts": 0,           # unix ts of last known worker.lastSubmission
    "last_best_diff_str": "",      # str form of last known worker.bestDifficulty
    "all_time_best_diff_raw": 0.0, # never decreases across proxy reconnects (persisted in settings)
    "share_submit_history": collections.deque(maxlen=64),  # recent submit ts list
    "share_calc_history": collections.deque(maxlen=20),    # per-share live-calc entries (latest at right)
    "session_share_count": 0,      # total SHARES observed since process start
    "session_best_diff_bumps": 0,  # total BEST_DIFF bumps since process start
}

# ── Disk-failure watchdog ─────────────────────────────────────────────────────
# Tracks consecutive SQLite write failures and surfaces them to the UI as a
# CRIT alert. Without this, a full disk silently breaks history persistence
# while the UI keeps "working" from in-memory snapshots — user has no signal.
PERSIST_FAILURE_ALERT_AT = 2  # first CRIT once we cross this many consecutive fails
PERSIST_FAILURE_LADDER = (2, 5, 10, 25, 60, 120)  # escalate at these counts
persist_consec_failures = 0
memory_critical_alerts = []  # injected into alerts_recent via _make_memory_alert helper
_next_memory_alert_id = 0  # monotonic counter so JS renderAlerts sees stable ids

# ── BTC price cache (CoinGecko free tier: 10-50 req/min, mas chamamos a cada 15s)
# Cache por 5 minutos para evitar 429 Too Many Requests.
BTC_PRICE_CACHE_TTL = 300  # 5 minutos em segundos
btc_price_cache = {"ts": 0, "data": None}  # último timestamp e dados cacheados


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
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


# ━━━ Proximity meter helpers ━━━
# bestDifficulty vs network difficulty, probability math, trend, hot-streak.
PROXIMITY_MILESTONES_PCT = [0.01, 0.1, 1.0, 5.0, 10.0, 25.0, 50.0, 100.0]
PROXIMITY_HOT_STREAK_THRESHOLD_PCT = 10.0  # >10% growth in 1h → hot streak
PROXIMITY_SAMPLE_THROTTLE_S = 60            # 1 sample/min → manageable DB size
_last_proximity_sample_ts = 0               # python int (seconds), module-level


def _restore_all_time_best_diff():
    """Restore all_time_best_diff from settings table (key `_all_time_best_diff`).
    Falls back to 0 if not set. Called once at module load so the meter keeps
    its 'peak' across process restarts."""
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT value FROM settings WHERE key='_all_time_best_diff'")
        r = c.fetchone()
        conn.close()
        if r and r["value"]:
            try:
                v = float(r["value"])
                if v > 0:
                    timeline_state["all_time_best_diff_raw"] = v
            except Exception:
                pass
    except Exception:
        pass


def _persist_all_time_best_diff(value):
    """Best-effort write of all_time_best_diff to settings so it survives restarts."""
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute(
            "INSERT INTO settings(key,value,updated_ts) VALUES(?,?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_ts=excluded.updated_ts",
            ("_all_time_best_diff", str(value), int(time.time())),
        )
        conn.commit()
        conn.close()
    except Exception as e:
        log.warning("[persist_all_time_best_diff] error: %s", e)


def _update_all_time_best_diff(raw_now):
    """If raw_now exceeds the stored peak, bump and persist. Returns updated value."""
    if raw_now is None or raw_now <= 0:
        return timeline_state.get("all_time_best_diff_raw") or 0.0
    cur = timeline_state.get("all_time_best_diff_raw") or 0.0
    if raw_now > cur:
        timeline_state["all_time_best_diff_raw"] = raw_now
        _persist_all_time_best_diff(raw_now)
        return raw_now
    return cur


def _nearest_history_before(ts_target):
    """Return (best_diff_raw, network_difficulty_raw) from proximity_history
    nearest to ts_target (≤ ts_target, newest), or None if no row exists.
    Used to compute trend over 1h / 6h / 24h windows."""
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute(
            "SELECT best_diff, network_difficulty FROM proximity_history "
            "WHERE ts <= ? ORDER BY ts DESC LIMIT 1",
            (int(ts_target),),
        )
        r = c.fetchone()
        conn.close()
        if r:
            return (r["best_diff"], r["network_difficulty"])
    except Exception:
        pass
    return None


def _sample_proximity(ts, best_diff_raw, current_difficulty, worker_hashrate, hot_streak):
    """Insert a proximity_history row, throttled to once per
    PROXIMITY_SAMPLE_THROTTLE_S seconds."""
    global _last_proximity_sample_ts
    if ts - _last_proximity_sample_ts < PROXIMITY_SAMPLE_THROTTLE_S:
        return
    try:
        pct = None
        if best_diff_raw and current_difficulty:
            pct = best_diff_raw / current_difficulty * 100.0
        conn = get_db()
        c = conn.cursor()
        c.execute(
            "INSERT INTO proximity_history "
            "(ts, best_diff, best_diff_str, all_time_best_diff, "
            " network_difficulty, worker_hashrate, pct_of_network, hot_streak) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (
                int(ts),
                best_diff_raw,
                fmt_diff(best_diff_raw) if best_diff_raw else "",
                timeline_state.get("all_time_best_diff_raw") or 0.0,
                current_difficulty,
                worker_hashrate,
                pct,
                1 if hot_streak else 0,
            ),
        )
        conn.commit()
        conn.close()
        _last_proximity_sample_ts = int(ts)
    except Exception as e:
        log.warning("[sample_proximity] error: %s", e)


def _compute_proximity(worker, current_difficulty, net_hashrate, ts):
    """Compute the full proximity meter payload for /api/proximity and
    included in /api/snapshot. Reads trend points from proximity_history.
    Pure compute: never raises (returns {} on insufficient data)."""
    out = {"ts": ts}
    try:
        best_diff_raw = parse_diff_to_float(worker.get("bestDifficulty")) if worker else 0.0
        if not best_diff_raw:
            return {**out, "insufficient_data": True}
        net_diff = float(current_difficulty) if current_difficulty else 0.0
        if not net_diff:
            return {**out, "insufficient_data": True, "reason": "no network_difficulty"}

        # all-time peak (persisted across restarts)
        all_time_raw = _update_all_time_best_diff(best_diff_raw)

        pct_cur = best_diff_raw / net_diff * 100.0
        pct_all = all_time_raw / net_diff * 100.0
        distance = net_diff / best_diff_raw  # how many × smaller than a block
        # Canonical expected time: hashes-per-block / hashes-per-second
        worker_hps = float(worker.get("hashrate") or 0)
        expected_secs = None
        blocks_per_year = None
        if worker_hps > 0:
            hashes_per_block = net_diff * (2 ** 32)
            expected_secs = hashes_per_block / worker_hps
            seconds_per_year = 365.25 * 86400
            blocks_per_year = seconds_per_year / expected_secs

        # Trend (compare to row 1h, 6h, 24h ago)
        nearest_1h = _nearest_history_before(ts - 3600)
        nearest_6h = _nearest_history_before(ts - 6 * 3600)
        nearest_24h = _nearest_history_before(ts - 86400)
        trend_1h_pct = (
            (best_diff_raw - nearest_1h[0]) / nearest_1h[0] * 100.0
            if nearest_1h and nearest_1h[0] else 0.0
        )
        trend_6h_pct = (
            (best_diff_raw - nearest_6h[0]) / nearest_6h[0] * 100.0
            if nearest_6h and nearest_6h[0] else 0.0
        )
        trend_24h_pct = (
            (best_diff_raw - nearest_24h[0]) / nearest_24h[0] * 100.0
            if nearest_24h and nearest_24h[0] else 0.0
        )
        if trend_1h_pct >= PROXIMITY_HOT_STREAK_THRESHOLD_PCT:
            trend_label = "rising"
        elif trend_1h_pct <= -PROXIMITY_HOT_STREAK_THRESHOLD_PCT:
            trend_label = "falling"
        else:
            trend_label = "flat"

        # Next milestone ladder step above current pct_of_network
        next_ms = None
        for m in PROXIMITY_MILESTONES_PCT:
            if m > pct_cur:
                next_ms = m
                break
        if next_ms is None:
            next_ms = PROXIMITY_MILESTONES_PCT[-1]  # 100% (i.e. block found!)

        out.update({
            "best_diff_str": fmt_diff(best_diff_raw),
            "best_diff_raw": best_diff_raw,
            "all_time_best_diff_str": fmt_diff(all_time_raw),
            "all_time_best_diff_raw": all_time_raw,
            "network_difficulty_str": fmt_diff(net_diff),
            "network_difficulty_raw": net_diff,
            "worker_hashrate_ths": worker_hps / 1e12 if worker_hps else 0.0,
            "pct_of_network_cur": pct_cur,
            "pct_of_network_all_time": pct_all,
            "distance_factor": distance,
            "distance_label": (
                "~" + _human_int(distance) + "× smaller than a block"
                if distance >= 1000
                else f"{distance:.2f}× smaller than a block"
            ),
            "expected_time_secs": expected_secs,
            "expected_time_human": _human_secs_long(expected_secs) if expected_secs else "—",
            "blocks_per_year": blocks_per_year,
            "chance_per_share_label": (
                f"1 in {int(round(net_diff / best_diff_raw)):,}"
                if best_diff_raw else "—"
            ),
            "trend_1h_pct": trend_1h_pct,
            "trend_6h_pct": trend_6h_pct,
            "trend_24h_pct": trend_24h_pct,
            "trend_label": trend_label,
            "hot_streak": bool(trend_1h_pct >= PROXIMITY_HOT_STREAK_THRESHOLD_PCT),
            "milestone_cur_pct": pct_cur,
            "next_milestone_pct": next_ms,
            "next_milestone_label": f"{next_ms:g}% of network difficulty",
            "milestones_achieved": [
                m for m in PROXIMITY_MILESTONES_PCT if m <= pct_all
            ],
        })

        # LIVE HASH CALCULATOR payload: latest per-share calc + cumulative
        # stats derived from share_calc_history. The full per-share math runs
        # in the share-detection block above; we just project it onto the
        # front-end's live-calc panel here.
        try:
            sch = list(timeline_state.get("share_calc_history") or [])
            latest = dict(sch[-1]) if sch else None
            ticker = [dict(e) for e in sch[-8:]]  # last 8 for ticker
            session_shares = timeline_state.get("session_share_count", 0) or 0
            share_diff_avg = 0.0
            if sch:
                share_diff_avg = sum((e.get("share_diff_raw") or 0) for e in sch) / len(sch)
            totals = {
                "shares_so_far": session_shares,
                "shares_in_ticker": len(sch),
                "avg_share_diff_raw": share_diff_avg,
                "avg_share_diff_str": fmt_diff(share_diff_avg) if share_diff_avg else "—",
            }
            if share_diff_avg and net_diff:
                p_per_share = share_diff_avg / net_diff
                shares_per_block = net_diff / share_diff_avg
                totals["avg_p_block_per_share"] = p_per_share
                totals["p_per_share_pct_str"] = (
                    f"{p_per_share * 100:.4e}%"
                    if p_per_share < 0.01
                    else f"{p_per_share * 100:.4f}%"
                )
                totals["shares_per_block_expected"] = shares_per_block
                totals["shares_per_block_expected_str"] = f"{int(shares_per_block):,}"
                if session_shares > 0:
                    cum_p = 1 - (1 - p_per_share) ** session_shares
                    totals["cum_p_block"] = cum_p
                    totals["cum_p_block_pct_str"] = (
                        f"{cum_p * 100:.4e}%"
                        if cum_p < 0.01
                        else f"{cum_p * 100:.4f}%"
                    )
                    expected_blocks = session_shares * p_per_share
                    totals["expected_blocks"] = expected_blocks
                    totals["expected_blocks_str"] = f"{expected_blocks:.4e}"
                # Expected time per share at this avg diff / hashrate
                if worker_hps > 0:
                    expected_time_per_share = (share_diff_avg * (2 ** 32)) / worker_hps
                    totals["expected_time_per_share_s"] = expected_time_per_share
                    totals["expected_time_per_share_str"] = _human_secs_long(expected_time_per_share)
            out["live_calc"] = {
                "latest": latest,
                "ticker": ticker,
                "session_totals": totals,
            }
        except Exception as e:
            log.warning("[compute_proximity live_calc] error: %s", e)

        return out
    except Exception as e:
        log.warning("[compute_proximity] error: %s", e)
        return {**out, "insufficient_data": True, "error": str(e)}


_human_int = human_int
_human_secs_long = human_secs_long
# isfinite_v imported from helpers.py


# Restore all-time best-difficulty from settings on module load.
_restore_all_time_best_diff()


# parse_diff_to_float, fmt_diff, fmt_hashrate, fmt_uptime, fmt_age
# are imported from helpers.py


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Polling worker
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def poll_once():
    global latest_snapshot
    global persist_consec_failures
    global memory_critical_alerts
    # _next_memory_alert_id is mutated only inside _make_memory_alert (which
    # declares its own `global`); no need to redeclare here.

    prev_worker = latest_snapshot.get("worker") or {}
    prev_pool = latest_snapshot.get("pool") or {}

    # ━━ Fetch (parallel) ━━
    # All upstream endpoints kicked off simultaneously — wall-time becomes
    # max(latency) instead of sum(latency), removing 15s drift under slow
    # networks. Per-future exception handling isolates single-endpoint failures.
    fetch_specs = [
        ("user",        f"{PARASITE_API}/user/{BTC_ADDRESS}",                                  10),
        ("pool",        f"{PARASITE_API}/pool-stats",                                          10),
        ("account",     f"{PARASITE_API}/account/{BTC_ADDRESS}",                               10),
        ("leaderboard", f"{PARASITE_API}/leaderboard?limit=30",                                         10),
        ("highest",     f"{PARASITE_API}/highest-diff?type=user-diffs&address={BTC_ADDRESS}&limit=30",       10),
        ("net_height",  f"{MEMPOOL_API}/blocks/tip/height",                                     6),
        # net_diff removed from main fetch — mempool.space /v1/difficulty deprecated Oct 2024.
        # blockchain.info /q/getdifficulty handles this via bc_specs below.
        ("mempool_fee", f"{MEMPOOL_API}/v1/fees/recommended",                                   6),
        ("btc",         "https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd,brl,eur,gbp", 6),
    ]

    # blockchain.info /q/* endpoints return PLAIN TEXT (not JSON), so they
    # live in a separate text-fetch fan-out below. mempool.space /v1/difficulty
    # has been deprecated (~Oct 2024) and returns 404; blockchain.info is the
    # most reliable public source for current_difficulty + network hashrate as
    # of late 2024 / 2025 / 2026.
    bc_specs = [
        ("bc_diff",     "https://blockchain.info/q/getdifficulty", 8),
        ("bc_hashrate", "https://blockchain.info/q/hashrate",      8),
    ]
    bc_results = {key: None for key, _, _ in bc_specs}


    results = {key: None for key, _, _ in fetch_specs}
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        future_to_key = {
            executor.submit(fetch_json, url, timeout): key
            for key, url, timeout in fetch_specs
        }
        # No outer timeout: each fetch_json belongs to a request with its own
        # per-endpoint timeout (≤10s). Worst-case poll wall = max(latencies),
        # well below POLL_INTERVAL=15s. As_completed(timeout=None) prevents the
        # secondary wait-for-shutdown blowout flagged by the code reviewer.
        for fut in concurrent.futures.as_completed(future_to_key):
            key = future_to_key[fut]
            try:
                results[key] = fut.result()
            except Exception as e:
                log.warning("[pool] future %s raised: %s", key, e)
                results[key] = None

    # ━━ Blockchain.info /q/* fallback fan-out (plain-text responses) ━━
    # blockchain.info endpoints return raw text like "154824667684575552"
    # instead of JSON, so they go through fetch_text instead of fetch_json.
    # Keeps wall-clock ~max(latency): both calls in parallel.
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as bc_executor:
        bc_futures = {
            bc_executor.submit(fetch_text, url, timeout): key
            for key, url, timeout in bc_specs
        }
        for fut in concurrent.futures.as_completed(bc_futures):
            key = bc_futures[fut]
            try:
                bc_results[key] = fut.result()
            except Exception as e:
                log.warning("[pool] bc text future %s raised: %s", key, e)
                bc_results[key] = None

    user = results["user"]
    pool = results["pool"]
    account_data = results["account"]
    leaderboard = results["leaderboard"] or []
    highest = results["highest"] or []

    # Network (mempool.space) — /v1/difficulty is preferred; fall back to
    # /v1/difficulty-adjustment embedded value, then to blockchain.info
    # /q/* endpoints (which return plain text integers and are still online).
    # Finally, if current_difficulty is known but net_hashrate isn't, compute
    # it from the canonical Bitcoin formula: hashrate = difficulty * 2^32 / 600.
    network_height_data = results["net_height"]
    # blockchain.info is the primary source for difficulty + hashrate (mempool.space
    # /v1/difficulty was deprecated Oct 2024 and always returns 404).
    bc_diff_val = safe_num_from_str(bc_results.get("bc_diff"))
    bc_hashrate_val = safe_num_from_str(bc_results.get("bc_hashrate"))
    if bc_hashrate_val is not None:
        # blockchain.info /q/hashrate returned TH/s historically, but as of
        # 2025-2026 it returns GH/s. Multiply by 1e9 to get H/s.
        net_hashrate = float(bc_hashrate_val) * 1e9
    else:
        net_hashrate = None
    network_height = network_height_data if isinstance(network_height_data, int) else None
    # Difficulty: use blockchain.info /q/getdifficulty as primary source
    current_difficulty = float(bc_diff_val) if bc_diff_val is not None else None
    # Fallback: derive net_hashrate from difficulty + target block time
    if current_difficulty is not None and (net_hashrate is None or net_hashrate == 0):
        net_hashrate = current_difficulty * (2 ** 32) / 600

    # BTC price (CoinGecko) — com cache de 5 min para evitar 429 rate limit
    _now = int(time.time())
    btc_quote = results["btc"]
    # Se a API retornou dados, atualiza o cache
    if isinstance(btc_quote, dict) and btc_quote.get("bitcoin"):
        btc_price_cache["data"] = btc_quote
        btc_price_cache["ts"] = _now
    # Se falhou (429 etc), usa cache se ainda válido (< 5 min)
    elif _now - btc_price_cache["ts"] < BTC_PRICE_CACHE_TTL and btc_price_cache["data"]:
        btc_quote = btc_price_cache["data"]
    else:
        btc_quote = None
    btc_usd = (btc_quote or {}).get("bitcoin", {}).get("usd") if isinstance(btc_quote, dict) else None
    btc_brl = (btc_quote or {}).get("bitcoin", {}).get("brl") if isinstance(btc_quote, dict) else None
    btc_eur = (btc_quote or {}).get("bitcoin", {}).get("eur") if isinstance(btc_quote, dict) else None
    btc_gbp = (btc_quote or {}).get("bitcoin", {}).get("gbp") if isinstance(btc_quote, dict) else None

    # Mempool fees (sat/vB) — for "what fee should I include if I want fast"
    mf_raw = results["mempool_fee"]
    mempool_fees = {}
    if isinstance(mf_raw, dict):
        for k in ("fastestFee", "halfHourFee", "hourFee", "minimumFee", "economyFee"):
            v = mf_raw.get(k)
            if isinstance(v, (int, float)):
                mempool_fees[k] = v
    if not mempool_fees:
        mempool_fees = {"fastestFee": None, "halfHourFee": None, "hourFee": None}

    # ━━ Halving countdown (post-2024 halving: blocks 0..210000, 210000..420000, ...
    # next halving at block 1050000 (year ~2028). Past-halvings are 210k multiples.
    # Use latest block height to compute distance to the next halving epoch.
    halving = {"height": network_height, "blocks_remaining": None,
               "estimated_seconds_remaining": None, "next_reward_btc": None,
               "epoch_label": ""}
    if isinstance(network_height, int):
        next_halving_h = ((network_height // 210000) + 1) * 210000
        blocks_left = max(0, next_halving_h - network_height)
        # assume 600s/block average → seconds remaining
        secs_left = blocks_left * 600
        # The reward halves from current 3.125 → 1.5625 (always halves by half).
        epoch_idx = (next_halving_h // 210000) - 1
        cur_reward = 50.0 * (0.5 ** epoch_idx) if epoch_idx >= 0 else 50.0
        next_reward = cur_reward * 0.5
        halving = {
            "next_height": next_halving_h,
            "current_height": network_height,
            "blocks_remaining": blocks_left,
            "estimated_seconds_remaining": secs_left,
            "estimated_days_remaining": secs_left / 86400.0,
            "current_reward_btc": cur_reward,
            "next_reward_btc": next_reward,
            "epoch_label": f"#{epoch_idx + 1}/33",
        }

    # ━━ Also capture ALL workers from workerData for the All Workers panel ━━
    all_workers = []
    worker = None
    worker_index = None
    if user and isinstance(user.get("workerData"), list):
        for idx, w in enumerate(user["workerData"]):
            entry = {
                "id": w.get("id", ""),
                "name": w.get("name", ""),
                "hashrate": w.get("hashrate"),
                "bestDifficulty": w.get("bestDifficulty", ""),
                "lastSubmission": w.get("lastSubmission"),
                "uptime": w.get("uptime"),
                "is_primary": str(w.get("name", "")).lower() == WORKER_NAME.lower()
                              or str(w.get("id", "")).lower() == WORKER_NAME.lower(),
            }
            all_workers.append(entry)
            if entry["is_primary"]:
                worker = w
                worker_index = idx

    # ━━ Leaderboard lookup ━━
    leaderboard_entry = None
    for entry in leaderboard:
        if entry.get("address") == BTC_ADDRESS:
            leaderboard_entry = entry
            break

    # Also fallback: search case-insensitive / substr
    if not leaderboard_entry:
        addr_short = BTC_ADDRESS[-8:].lower()
        for entry in leaderboard:
            if addr_short in str(entry.get("address", "")).lower():
                leaderboard_entry = entry
                break

    # ━━ Account unpack ━━
    account = account_data.get("account") if isinstance(account_data, dict) else None
    lightning = account_data.get("lightning") if isinstance(account_data, dict) else None
    meta = account.get("metadata", {}) if isinstance(account, dict) else {}

    ts = int(time.time())

    # ━━ Share timeline delta detection ━━
    # Every real share submitted by the worker changes worker.lastSubmission.
    # Every new best share changes worker.bestDifficulty.
    # We track deltas across polls as proxy "share events" — the closest
    # signal the public API gives us to per-share logs.
    timeline_events = []

    # FIRST-POLL GUARD: the very first poll after process start captures the
    # current observed values as "baseline" without emitting fake SHARE_FOUND /
    # BEST_DIFF_BUMP events. Subsequent polls fire only on real deltas.
    if not timeline_state["_primed"]:
        if worker:
            try:
                ls_int = int(worker.get("lastSubmission") or 0)
            except Exception:
                ls_int = 0
            timeline_state["last_submit_ts"] = ls_int or 0
            timeline_state["last_best_diff_str"] = worker.get("bestDifficulty") or ""
            # seed the rolling share-rate history so sph is meaningful from poll 2
            if ls_int:
                timeline_state["share_submit_history"].append(ls_int)
        timeline_state["_primed"] = True
        fresh_bump_detected = False
    else:
        fresh_bump_detected = False
        if worker:
            ls = worker.get("lastSubmission")
            try:
                ls_int = int(ls) if ls else 0
            except Exception:
                ls_int = 0
            if ls_int and ls_int != timeline_state["last_submit_ts"]:
                gap = (ls_int - timeline_state["last_submit_ts"]) if timeline_state["last_submit_ts"] else 0
                timeline_state["last_submit_ts"] = ls_int
                timeline_state["share_submit_history"].append(ls_int)
                timeline_state["session_share_count"] += 1
                sph = 0.0
                hist = timeline_state["share_submit_history"]
                if len(hist) >= 2:
                    span = hist[-1] - hist[0]
                    if span > 0:
                        sph = (len(hist) - 1) * (3600.0 / span)
                timeline_events.append(
                    (
                        ts,
                        "SHARE_FOUND",
                        "INFO",
                        f"cypher65 share validated by pool (gap Δ{gap}s)",
                        json.dumps({"gap": gap, "shares_per_hour": round(sph, 2)}),
                    )
                )

                # Per-share LIVE HASH CALCULATOR: compute the math that the
                # dashboard exposes in real time (see also live_calc payload
                # in _compute_proximity for cumulative stats).
                #
                # parasite.space exposes worker.difficulty (current vardiff
                # target). When that's missing, fall back to best_diff / 2
                # (vardiff typically doubles after every accepted share).
                share_diff_raw = 0.0
                try:
                    d = worker.get("difficulty")
                    if isinstance(d, (int, float)) and d > 0:
                        share_diff_raw = float(d)
                    elif isinstance(d, str) and d:
                        share_diff_raw = parse_diff_to_float(d)
                    if not share_diff_raw and worker.get("bestDifficulty"):
                        share_diff_raw = parse_diff_to_float(worker.get("bestDifficulty")) / 2.0
                except Exception:
                    share_diff_raw = 0.0
                if share_diff_raw and current_difficulty and gap and gap > 0:
                    hashes_attempted = share_diff_raw * (2 ** 32)
                    p_block_this = share_diff_raw / float(current_difficulty)
                    inst_hr_hps = hashes_attempted / float(gap)
                    share_calc = {
                        "ts": ts,
                        "gap": gap,
                        "share_diff_raw": share_diff_raw,
                        "share_diff_str": fmt_diff(share_diff_raw),
                        "hashes_attempted": hashes_attempted,
                        "hashes_attempted_str": f"{hashes_attempted:.3e}",
                        "p_block_this_share": p_block_this,
                        "p_block_this_share_pct_str": (
                            f"{p_block_this * 100:.4e}%"
                            if p_block_this < 0.01
                            else f"{p_block_this * 100:.4f}%"
                        ),
                        "instantaneous_hr_hps": inst_hr_hps,
                        "instantaneous_hr_str": fmt_hashrate(inst_hr_hps),
                        "best_diff_at_time": (
                            parse_diff_to_float(worker.get("bestDifficulty"))
                            if worker and worker.get("bestDifficulty") else 0.0
                        ),
                        "best_diff_at_time_str": (
                            worker.get("bestDifficulty") if worker else ""
                        ),
                        "network_diff_at_time": current_difficulty,
                        "network_diff_at_time_str": fmt_diff(current_difficulty),
                        "session_share_count_at_time": timeline_state["session_share_count"],
                    }
                    timeline_state["share_calc_history"].append(share_calc)

            best_diff_str = worker.get("bestDifficulty") or ""
            if best_diff_str and best_diff_str != timeline_state["last_best_diff_str"]:
                # IMPORTANT: capture old strings/values BEFORE mutating state,
                # so meta payload reports the true "from→to" transition.
                old_str = timeline_state["last_best_diff_str"]
                old_val = parse_diff_to_float(old_str)
                new_val = parse_diff_to_float(best_diff_str)
                pct = ((new_val - old_val) / old_val * 100) if old_val else 0.0
                timeline_state["last_best_diff_str"] = best_diff_str
                timeline_state["session_best_diff_bumps"] += 1
                fresh_bump_detected = True
                pct_txt = f"+{pct:.1f}%" if pct else "first"
                timeline_events.append(
                    (
                        ts,
                        "BEST_DIFF_BUMP",
                        "GOLD",
                        f"cypher65 best difficulty raised to {best_diff_str} ({pct_txt})",
                        json.dumps({"from": old_str or "0", "to": best_diff_str, "pct": round(pct, 2)}),
                    )
                )

    if pool:
        cur_wslb = pool.get("workSinceLastBlock") or 0
        if prev_pool and prev_pool.get("workSinceLastBlock") is not None and cur_wslb:
            cur_wslb_f = float(cur_wslb)
            prev_wslb_f = float(prev_pool.get("workSinceLastBlock") or 0)
            wslb_delta = cur_wslb_f - prev_wslb_f
            # if pool accumulated more than 1e10 share-diff worth of work since last poll,
            # surface it as a WORK_DELTA milestone
            if abs(wslb_delta) > 1e10:
                timeline_events.append(
                    (
                        ts,
                        "WORK_DELTA",
                        "INFO",
                        f"Pool accumulated +{fmt_diff(wslb_delta)} work since last poll ({fmt_diff(cur_wslb_f)} total)",
                        json.dumps({"delta": wslb_delta, "total": cur_wslb_f}),
                    )
                )

    # ━━ Persist snapshot ━━
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute(
            """INSERT INTO snapshots
            (ts, worker_hashrate, worker_best_diff, worker_last_submit, worker_uptime, worker_status,
             pool_hashrate, pool_workers, pool_users, pool_highest_diff, pool_last_block_height,
             pool_last_block_time, pool_work_since_last_block,
             account_total_diff, account_block_count, account_highest_block,
             leaderboard_rank, leaderboard_diff_rank, leaderboard_loyalty_rank, leaderboard_combined_score,
             network_height, network_difficulty, network_hashrate,
             btc_usd, btc_brl)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                ts,
                worker.get("hashrate") if worker else None,
                worker.get("bestDifficulty") if worker else None,
                worker.get("lastSubmission") if worker else None,
                worker.get("uptime") if worker else None,
                "online" if worker else "missing",
                pool.get("hashrate") if pool else None,
                pool.get("workers") if pool else None,
                pool.get("users") if pool else None,
                pool.get("highestDifficulty") if pool else None,
                pool.get("lastBlockHeight") if pool else None,
                pool.get("lastBlockTime") if pool else None,
                pool.get("workSinceLastBlock") if pool else None,
                account.get("total_diff") if isinstance(account, dict) else None,
                meta.get("block_count") if isinstance(meta, dict) else None,
                meta.get("highest_blockheight") if isinstance(meta, dict) else None,
                (leaderboard.index(leaderboard_entry) + 1) if leaderboard_entry else None,
                leaderboard_entry.get("diff_rank") if leaderboard_entry else None,
                leaderboard_entry.get("loyalty_rank") if leaderboard_entry else None,
                leaderboard_entry.get("combined_score") if leaderboard_entry else None,
                network_height,
                current_difficulty,
                net_hashrate,
                btc_usd,
                btc_brl,
            ),
        )

        # ━━ High-diff events ━━
        if isinstance(highest, list):
            for ev in highest[:30]:
                bh = ev.get("block_height")
                c.execute("SELECT 1 FROM highest_diff_events WHERE block_height=?", (bh,))
                if not c.fetchone():
                    top_addr = ev.get("top_diff_address") or ev.get("address") or ""
                    is_mine = BTC_ADDRESS in top_addr
                    c.execute(
                        """INSERT INTO highest_diff_events
                        (ts, block_height, top_diff_address, difficulty, claimed, block_timestamp, is_mine)
                        VALUES (?,?,?,?,?,?,?)""",
                        (
                            ts,
                            bh,
                            top_addr,
                            str(ev.get("difficulty", "")),
                            1 if ev.get("claimed") else 0,
                            ev.get("block_timestamp"),
                            1 if is_mine else 0,
                        ),
                    )

        # ━━ Share timeline events ━━
        for ev in timeline_events:
            try:
                c.execute(
                    """INSERT INTO share_timeline
                    (ts, event_type, severity, message, meta) VALUES (?,?,?,?,?)""",
                    ev,
                )
            except Exception as e:
                log.warning("[share_timeline insert] error: %s", e)
        conn.commit()
        # ── Persist succeeded → clear failure state, surface SUCCESS alert ──
        if persist_consec_failures > 0:
            memory_critical_alerts.append(_make_memory_alert(
                ts, "SUCCESS", "disk_write_recovered",
                f"SQLite writes recovered after {persist_consec_failures} consecutive "
                f"poll failures; history persistence restored."
            ))
            persist_consec_failures = 0
    except Exception as e:
        log.error("[persist] error: %s", e)
        persist_consec_failures += 1
        # Escalate at ladder steps so we don't flood the alerts panel.
        if persist_consec_failures in PERSIST_FAILURE_LADDER:
            degraded_s = persist_consec_failures * POLL_INTERVAL
            memory_critical_alerts.append(_make_memory_alert(
                ts, "CRIT", "disk_write_failure",
                f"SQLite write failing — {persist_consec_failures} consecutive poll "
                f"failures (~{degraded_s}s degraded). Live UI continues; "
                f"history persistence OFF until disk recovers."
            ))
    finally:
        try:
            conn.close()
        except Exception:
            pass

    # ── Anomaly detection ──
    settings_s = load_settings()
    stale_min = coerce_int(settings_s.get("stale_share_minutes"), 5)
    hr_drop_pct = coerce_float(settings_s.get("hashrate_drop_pct"), 50.0)
    alerts = []

    # ── Alert deduplication ──
    # Track event signatures across polls so the same "pool new high diff 87.1T"
    # never fires twice. Signature = (category, identifier) where identifier is
    # the unique value (block_hash, highest_diff_str, etc.)
    if not hasattr(poll_once, '_alert_seen'):
        poll_once._alert_seen = set()  # set of (category, identifier) seen across restarts
    alert_seen = poll_once._alert_seen

    if worker:
        ls = worker.get("lastSubmission")
        if ls and (ts - int(ls)) > stale_min * 60:
            sev = "WARN" if (ts - int(ls)) <= stale_min * 120 else "CRIT"
            sig = ("stale_submission", str(ls))
            if sig not in alert_seen:
                alerts.append((sev, "stale_submission",
                    f"cypher65 last submit {int((ts - int(ls)) / 60)}min ago (threshold {stale_min}m)"))
                alert_seen.add(sig)
        prev_hr = float(prev_worker.get("hashrate") or 0)
        cur_hr = float(worker.get("hashrate") or 0)
        if prev_hr > 0 and cur_hr < (1 - hr_drop_pct / 100.0) * prev_hr:
            sig = ("hashrate_drop", f"{prev_hr:.0f}->{cur_hr:.0f}")
            if sig not in alert_seen:
                alerts.append(("WARN", "hashrate_drop",
                    f"cypher65 hashrate dropped from {fmt_hashrate(prev_hr)} to {fmt_hashrate(cur_hr)} (-{hr_drop_pct:.0f}%)"))
                alert_seen.add(sig)
    else:
        sig = ("worker_offline", "1")
        if sig not in alert_seen:
            alerts.append(("CRIT", "worker_offline", "cypher65 not found in workerData"))
            alert_seen.add(sig)

    if pool:
        cur_high = str(pool.get("highestDifficulty") or "")
        if cur_high and cur_high != str(prev_pool.get("highestDifficulty") or ""):
            sig = ("new_high_diff", cur_high)
            if sig not in alert_seen:
                alerts.append(("GOLD", "new_high_diff", f"Pool new highest diff: {cur_high}"))
                alert_seen.add(sig)
        cur_block_hash = str(pool.get("lastBlockHash") or "")
        prev_block_hash = str(prev_pool.get("lastBlockHash") or "")
        if cur_block_hash and cur_block_hash != prev_block_hash:
            sig = ("new_block", cur_block_hash)
            if sig not in alert_seen:
                alerts.append(("GOLD", "new_block",
                    f"Pool found block: {cur_block_hash[:16]}…"))
                alert_seen.add(sig)

    # dedication / continuity - only fire once per uptime milestone
    if worker and isinstance(worker.get("uptime"), int):
        up = worker["uptime"]
        if up > 0 and up % 86400 < 90:  # crossed the day boundary
            day_num = up // 86400
            sig = ("uptime_milestone", str(day_num))
            if sig not in alert_seen:
                alerts.append(("INFO", "uptime", f"cypher65 uptime crossed {fmt_uptime(up)}"))
                alert_seen.add(sig)

    # GC old signatures (keep last 1000)
    if len(alert_seen) > 1000:
        poll_once._alert_seen = set(list(alert_seen)[-500:])

    if alerts:
        try:
            conn = get_db()
            c = conn.cursor()
            for sev, cat, msg in alerts:
                c.execute(
                    "INSERT INTO alerts (ts, severity, category, message) VALUES (?,?,?,?)",
                    (ts, sev, cat, msg),
                )
            conn.commit()
            conn.close()
        except Exception as e:
            log.warning("[alert persist] error: %s", e)

    # ━━ Webhook fire (Discord/Telegram compatible JSON payload) ━━
    # Honor user-configured webhook_url. Severity threshold defaults to WARN.
    try:
        s = settings_s
        url = (s.get("webhook_url") or "").strip()
        if url:
            min_sev = s.get("webhook_min_severity", "WARN")
            sev_rank = {"INFO": 0, "WARN": 1, "CRIT": 2, "GOLD": 1, "SUCCESS": 1}
            fire_severities = [a for a in alerts if sev_rank.get(a[0], 0) >= sev_rank.get(min_sev, 1)]
            for sev, cat, msg in fire_severities:
                try:
                    payload = {
                        "event": "cypher65_war_room_alert",
                        "severity": sev,
                        "category": cat,
                        "message": msg,
                        "ts": ts,
                        "worker": WORKER_NAME,
                        "address": BTC_ADDRESS,
                    }
                    requests.post(url, json=payload, timeout=4)
                except Exception as e:
                    log.warning("[webhook] post error: %s", e)
    except Exception as e:
        log.warning("[webhook block] error: %s", e)

    # ━━ Compute luck estimate ━━
    luck = {}
    if worker and pool and current_difficulty:
        try:
            # Each share difficulty roughly = network_diff / (pool_hashrate * target_seconds)
            # We use parasite's highest diff as pool's "best work this round"
            # and we estimate pool avg share diff = current_difficulty * 2^32 / (pool_hashrate_hs * 600) ≈ ...
            # Simpler: best_difficulty / expected_share_diff → luck ratio
            worker_best = parse_diff_to_float(worker.get("bestDifficulty"))
            pool_best = parse_diff_to_float(pool.get("highestDifficulty"))
            # ckpool shares are ~1M by default, but for Plebs pool may be 16k or variable.
            # We use work-since-last-block / pool hashrate to estimate "expected shares" portion
            wslb = pool.get("workSinceLastBlock") or 0  # total integrated diff since last block
            # "luck" → actual best_diff vs expected per this worker.
            # the simplest honest metric: work_since_last_block / pool_hashrate (seconds of work)
            # and our workers's hashrate / pool hashrate → fair share of WSLB.
            cur_hr = float(worker.get("hashrate") or 0)
            pool_hr = float(pool.get("hashrate") or 0)
            fair_share_wslb = (cur_hr / pool_hr) * wslb if pool_hr else 0
            expected_share_diff = current_difficulty / 65536  # rough: 1 share ≈ diff / 64k
            luck = {
                "fair_share_diff_since_last_block": fair_share_wslb,
                "pool_work_since_last_block": wslb,
                "expected_share_diff_estimate": expected_share_diff,
                "worker_share_of_pool_pct": (cur_hr / pool_hr * 100) if pool_hr else 0,
            }
            # pool-luck % — work-on-block progress vs expected by share contribution
            # expected: wslb should equal network_diff when fair share arrives
            try:
                if wslb and current_difficulty and cur_hr and pool_hr:
                    expected_wslb = (cur_hr / pool_hr) * current_difficulty
                    pool_luck_pct = (expected_wslb / wslb * 100.0) if wslb else 0.0
                    luck["pool_luck_pct"] = round(pool_luck_pct, 2)
                if wslb and current_difficulty:
                    luck["round_progress_pct"] = round(min(100, (wslb / current_difficulty) * 100), 2)
            except Exception:
                pass
        except Exception:
            pass

    # ━━ Profitability (real-time, settings-driven, 3 modes) ━━
    #
    # Formulas (Bitcoin consensus + pool economics):
    #
    #   Network hashrate ≈ network_difficulty × 2^32 / 600  [H/s]
    #   Expected blocks/day = your_H/s / net_H/s × 144
    #   Net BTC/day (pool) = expected_blocks × (block_reward + avg_fee) × (1 - pool_fee/100) × (1 - orphan/100)
    #   Net BTC/day (solo) = expected_blocks × (block_reward + avg_fee) × (1 - orphan/100)
    #   Net BTC/day (rental) = net_btc_pool - rental_cost
    #   Hashrate from shares: H = (shares / Δt) × share_diff × 2^32
    #
    profitability = {}
    # Hoist cur_hr / net_hr BEFORE the try block so downstream readers
    # (network_share_gauge block) always see well-defined values even if the
    # profitability compute itself fails.
    cur_hr = float(worker.get("hashrate")) if worker and worker.get("hashrate") else 0.0
    net_hr = float(net_hashrate) if net_hashrate else 0.0
    try:
        s = load_settings()
        reward = coerce_float(s.get("btc_block_reward"), 3.125)
        fee = coerce_float(s.get("btc_avg_tx_fee"), 0.05)
        pool_fee_pct = coerce_float(s.get("pool_fee_pct"), 1.5)
        orphan_pct = coerce_float(s.get("orphan_rate_pct"), 0.5)
        cost_mode = s.get("cost_mode", "none")
        btc_prices = {"USD": btc_usd, "BRL": btc_brl, "EUR": btc_eur, "GBP": btc_gbp}

        profitability["cost_mode"] = cost_mode
        profitability["active_currency_val"] = s.get("active_currency", "USD")
        profitability["pool_fee_pct"] = pool_fee_pct
        profitability["orphan_pct"] = orphan_pct

        if cur_hr > 0 and net_hr > 0:
            share_of_network = cur_hr / net_hr
            blocks_per_day = 144.0
            total_reward_per_block = reward + fee

            # ── Pool mining (PPS/FPPS approximated) ──
            # Expected blocks = your_share × total_blocks
            # Net after pool fee & orphan
            gross_btc_per_day = share_of_network * blocks_per_day * total_reward_per_block
            pool_net_btc_per_day = gross_btc_per_day * (1 - pool_fee_pct / 100.0) * (1 - orphan_pct / 100.0)

            # ── Solo mining ──
            # Same formula but no pool fee. Expected blocks PER YEAR = your_share × 144 × 365
            # Solo variance is extreme: P(at least one block in N days) = 1 - (1 - p)^N
            solo_net_btc_per_day = gross_btc_per_day * (1 - orphan_pct / 100.0)  # no pool fee
            solo_p_day = share_of_network  # probability of finding a block on any given day
            solo_p_year = 1 - (1 - solo_p_day) ** 365
            solo_p_5year = 1 - (1 - solo_p_day) ** (365 * 5)

            # ── Rental cost ──
            ths = cur_hr / 1e12
            rental_cost_per_day = 0.0
            power_cost_per_day = 0.0
            if cost_mode == "rental":
                rental_cost_per_day = ths * coerce_float(s.get("rental_usd_per_th_day"), 0.0)
            elif cost_mode == "power":
                watts = coerce_float(s.get("power_watts"), 0.0)
                kwh_rate_usd = coerce_float(s.get("power_kwh_usd"), 0.0)
                power_cost_per_day = (watts / 1000.0) * 24.0 * kwh_rate_usd

            # ── Net after cost ──
            cost_per_day = rental_cost_per_day + power_cost_per_day

            def _fiat_convert(btc_val):
                return {
                    cur: (round(btc_val * px, 4) if px else None)
                    for cur, px in btc_prices.items()
                }

            # Pool mining output
            profitability.update({
                "share_of_network_pct": round(share_of_network * 100, 8),
                "gross_btc_per_day": round(gross_btc_per_day, 8),
                # Pool mode (default, what the user is using)
                "mode": cost_mode if cost_mode != "none" else "pool",
                "net_btc_per_day_pool": round(pool_net_btc_per_day, 8),
                "fiat_per_day_pool": _fiat_convert(pool_net_btc_per_day),
                "fiat_per_week_pool": _fiat_convert(pool_net_btc_per_day * 7),
                "fiat_per_month_pool": _fiat_convert(pool_net_btc_per_day * 30),
                "pool_net_usd_per_day": round((pool_net_btc_per_day * (btc_usd or 0)) - cost_per_day, 4),
                "pool_net_usd_per_month": round(((pool_net_btc_per_day * (btc_usd or 0)) - cost_per_day) * 30, 2),
                # Solo mode
                "net_btc_per_day_solo": round(solo_net_btc_per_day, 8),
                "fiat_per_day_solo": _fiat_convert(solo_net_btc_per_day),
                "solo_p_day_pct": round(solo_p_day * 100, 8),
                "solo_p_year_pct": round(solo_p_year * 100, 4),
                "solo_p_5year_pct": round(solo_p_5year * 100, 2),
                "solo_expected_blocks_per_year": round(solo_p_day * 365, 4),
                "solo_expected_time_to_block_days": round(1 / solo_p_day, 1) if solo_p_day > 0 else None,
                # Rental mode (cost subtracted)
                "net_btc_per_day_rental": round(pool_net_btc_per_day - (cost_per_day / (btc_usd or 1)), 8) if btc_usd else None,
                "fiat_per_day_rental": _fiat_convert(max(0, pool_net_btc_per_day - (cost_per_day / (btc_usd or 1)))) if btc_usd else None,
                "rental_net_btc_per_day": round(pool_net_btc_per_day, 8),  # gross pool BTC
                "rental_net_usd_per_day": round((pool_net_btc_per_day * (btc_usd or 0)) - cost_per_day, 4),
                "rental_net_usd_per_month": round(((pool_net_btc_per_day * (btc_usd or 0)) - cost_per_day) * 30, 2),
                # Cost info
                "cost_per_day_usd": round(cost_per_day, 4),
                "cost_label": (
                    f"${rental_cost_per_day:.2f}/d rental ({ths:.2f} TH/s × ${coerce_float(s.get('rental_usd_per_th_day'),0.0):.4f})"
                    if cost_mode == "rental" else
                    f"${power_cost_per_day:.2f}/d power ({coerce_float(s.get('power_watts'),0.0):.0f}W × 24h × ${coerce_float(s.get('power_kwh_usd'),0.10):.4f}/kWh)"
                    if cost_mode == "power" else"."
                ),
                # Break-even: rental rate at which pool_net = rental_cost
                "break_even_rental_usd_per_th_day": round(
                    (pool_net_btc_per_day * (btc_usd or 0)) / max(ths, 1e-12), 4
                ) if cost_mode == "rental" and btc_usd and ths > 0 else None,
                # Effective BTC/TH/s/day (marginal)
                "effective_btc_per_th_per_day": round(
                    (1.0 / 1e12 / net_hr) * blocks_per_day * total_reward_per_block
                    * (1 - pool_fee_pct / 100.0) * (1 - orphan_pct / 100.0),
                    10,
                ),
                # Pool fee info
                "pool_fee_info": f"Pool fee: {pool_fee_pct}% · Orphan rate: {orphan_pct}% · Reward: {reward}+{fee} BTC/block",
                # Disclaimer
                "disclaimer": "Estimates based on current hashrate, network difficulty, and BTC price. Actual results vary significantly due to variance, pool luck, and difficulty changes.",
            })
        else:
            profitability["unavailable_reason"] = "no hashrate or network hashrate"
    except Exception as e:
        log.warning("[profitability] compute error: %s", e)

    # ━━ Milestones (session-share-count, best_diff ranks, etc.) ━━
    # This block runs BEFORE event_stats is computed (which happens later in
    # poll_once). We deliberately use only data already in scope here
    # (timeline_state, worker snapshot). The session-wide milestones list is
    # in-memory only — no DB table is needed because entries re-derive from
    # session counters each poll.
    milestones = []
    try:
        sc = timeline_state["session_share_count"]
        milestones_def = [
            (sc >= 100,  "BRONZE",  f"{sc} shares this session"),
            (sc >= 1000, "SILVER",  f"{sc:,} shares this session"),
            (sc >= 10000, "GOLD",    f"{sc:,} shares this session"),
            (worker and parse_diff_to_float(worker.get("bestDifficulty","")) >= 1e9, "BRONZE", "best diff ≥ 1 G"),
            (worker and parse_diff_to_float(worker.get("bestDifficulty","")) >= 1e12, "SILVER", "best diff ≥ 1 T"),
            (worker and parse_diff_to_float(worker.get("bestDifficulty","")) >= 1e15, "GOLD",   "best diff ≥ 1 P"),
            (worker and safe_int(worker.get("uptime", 0)) >= 86400,   "BRONZE", "uptime ≥ 1 day"),
            (worker and safe_int(worker.get("uptime", 0)) >= 7*86400, "SILVER", "uptime ≥ 7 days"),
            (worker and safe_int(worker.get("uptime", 0)) >= 30*86400,"GOLD",   "uptime ≥ 30 days"),
        ]
        for ok, tier, label in milestones_def:
            if ok:
                milestones.append({"tier": tier, "label": label, "value": label})
    except Exception:
        pass

    # ━━ Proximity meter (best_diff vs network_diff, probability, trend) ━━
    proximity = _compute_proximity(worker, current_difficulty, net_hashrate, ts)
    try:
        _sample_proximity(
            ts,
            proximity.get("best_diff_raw") or 0.0,
            proximity.get("network_difficulty_raw") or 0.0,
            worker.get("hashrate") if worker else 0.0,
            proximity.get("hot_streak", False),
        )
    except Exception as e:
        log.warning("[sample_proximity] error: %s", e)

    # Hot-streak detection: build the alert dict NOW so it's available when
    # the inject block (placed after the alerts_recent DB read) runs. Capture
    # as a local dict; persistence + render-inject happen downstream.
    hot_streak_alert = None
    if (
        fresh_bump_detected
        and proximity
        and proximity.get("hot_streak")
        and proximity.get("best_diff_str")
        and proximity.get("trend_1h_pct") is not None
    ):
        hot_streak_alert = {
            "ts": ts,
            "severity": "SUCCESS",
            "category": "hot_streak",
            "message": (
                f"cypher65 best-diff HOT STREAK: {proximity['best_diff_str']} "
                f"(+{proximity['trend_1h_pct']:.1f}% in 1h) — keep going!"
            ),
        }

    # ━━ Worker-share-of-network gauge (server-side compute; client renders) ━━
    network_share_gauge = {"worker_pct": 0.0, "pool_pct": 0.0, "label": ""}
    try:
        if worker and net_hr and cur_hr:
            network_share_gauge["worker_pct"] = round(cur_hr / net_hr * 100, 6)
            network_share_gauge["pool_pct"] = round(
                float(pool.get("hashrate") or 0) / net_hr * 100, 4
            ) if pool else 0.0
            # log10 scale label for readability
            network_share_gauge["label"] = f"cypher65 = {network_share_gauge['worker_pct']:.6f}% of network"
    except Exception:
        pass

    # ━━ Recent alerts ━━
    recent_alerts = []
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT * FROM alerts ORDER BY ts DESC LIMIT 12")
        recent_alerts = [dict(r) for r in c.fetchall()]
        conn.close()
    except Exception:
        pass
    # Merge in-memory CRIT/SUCCESS alerts (disk-watchdog). Each in-memory alert
    # already carries a stable id assigned by _make_memory_alert, so
    # JS renderAlerts sees them as same-item across polls and does NOT re-fire
    # logMessage events. Entries sort above DB alerts naturally because they're
    # prepended to the list.
    if memory_critical_alerts:
        in_mem = memory_critical_alerts[-12:]
        recent_alerts = in_mem + recent_alerts
        # Cap so renderers don't get flooded; SUCCESS alerts auto-clear on next good persist.
        if len(memory_critical_alerts) > 24:
            memory_critical_alerts = memory_critical_alerts[-24:]  # GC oldest

    # ━━ Hot-streak inject (post-DB-read so it lands at top of alerts_recent)
    # Persist directly to alerts DB AND prepend to recent_alerts so the panel
    # shows it this poll. Without the direct INSERT the alerts DB write block
    # (earlier in poll_once) would miss the proximity-driven tuple. We use
    # _make_memory_alert for a stable id so JS prevAlerts-filter dedupes
    # correctly on subsequent polls (no logMessage re-firing).
    if hot_streak_alert is not None:
        try:
            conn = get_db()
            c = conn.cursor()
            c.execute(
                "INSERT INTO alerts (ts, severity, category, message) VALUES (?,?,?,?)",
                (hot_streak_alert["ts"], hot_streak_alert["severity"],
                 hot_streak_alert["category"], hot_streak_alert["message"]),
            )
            conn.commit()
            conn.close()
        except Exception as e:
            log.warning("[hot_streak alert persist] error: %s", e)
        mem_hs = _make_memory_alert(
            hot_streak_alert["ts"], hot_streak_alert["severity"],
            hot_streak_alert["category"], hot_streak_alert["message"],
        )
        # Prepend so it appears at the top of the panel. DO NOT also push to
        # memory_critical_alerts — the existing in_mem prepend block + DB
        # SELECT (which now includes this row) would duplicate the entry on
        # the next poll.
        recent_alerts = [mem_hs] + recent_alerts

    # ━━ Recent timeline events ━━
    timeline_recent = []
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute(
            "SELECT * FROM share_timeline ORDER BY id DESC LIMIT 80"
        )
        timeline_recent = [dict(r) for r in c.fetchall()]
        conn.close()
    except Exception:
        pass

    # ━━ Event stats (session + rolling windows) ━━
    now = int(time.time())
    hour_ago = now - 3600
    day_ago = now - 86400
    session_share_count = timeline_state["session_share_count"]
    session_best_bumps = timeline_state["session_best_diff_bumps"]
    sph = 0.0
    hist = timeline_state["share_submit_history"]
    if len(hist) >= 2 and (hist[-1] - hist[0]) > 0:
        sph = (len(hist) - 1) * (3600.0 / (hist[-1] - hist[0]))
    event_stats = {
        "session_share_count": session_share_count,
        "session_best_diff_bumps": session_best_bumps,
        "rolling_shares_per_hour": round(sph, 2),
        "last_submit_ts": timeline_state["last_submit_ts"],
        "last_share_age_s": (now - timeline_state["last_submit_ts"]) if timeline_state["last_submit_ts"] else None,
    }
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute(
            "SELECT COUNT(*) FROM share_timeline WHERE ts >= ? AND event_type='SHARE_FOUND'",
            (hour_ago,),
        )
        r = c.fetchone()
        shares_last_hour = r[0] if r else 0
        c.execute(
            "SELECT COUNT(*) FROM share_timeline WHERE ts >= ? AND event_type='SHARE_FOUND'",
            (day_ago,),
        )
        r = c.fetchone()
        shares_last_day = r[0] if r else 0
        c.execute(
            "SELECT COUNT(*) FROM share_timeline WHERE event_type='BEST_DIFF_BUMP' AND ts >= ?",
            (day_ago,),
        )
        r = c.fetchone()
        best_diffs_last_day = r[0] if r else 0
        conn.close()
        event_stats.update(
            {
                "db_shares_last_hour": shares_last_hour,
                "db_shares_last_day": shares_last_day,
                "db_best_diffs_last_day": best_diffs_last_day,
            }
        )
    except Exception:
        pass

    # ━━ Hot-streak alert (proximity-driven, fresh-bump gated) ━━
    # Already captured above (right after proximity compute). Here we just
    # route it: direct DB INSERT for persistence + prepend to recent_alerts
    # so the panel shows it THIS poll. We deliberately do NOT push to
    # memory_critical_alerts: the existing `in_mem` prepend block runs every
    # poll, and the DB SELECT also returns the INSERTed row — pushing the
    # memory alert would DUPLICATE the entry on poll N+1.

    latest_snapshot = {
        "ts": ts,
        "worker": worker,
        "worker_index": worker_index,
        "user_aggregate": user,
        "pool": pool,
        "account": account,
        "account_meta": meta,
        "lightning": lightning,
        "leaderboard_entry": leaderboard_entry,
        "leaderboard_total": len(leaderboard),
        "highest_diffs": highest[:20] if isinstance(highest, list) else [],
        "network": {
            "height": network_height,
            "difficulty": current_difficulty,
            "hashrate": net_hashrate,
        },
        "btc_price": {"usd": btc_usd, "brl": btc_brl, "eur": btc_eur, "gbp": btc_gbp},
        "luck_estimate": luck,
        "halving": halving,
        "mempool_fees": mempool_fees,
        "profitability": profitability,
        "milestones": milestones,
        "proximity": proximity,
        "network_share_gauge": network_share_gauge,
        "alerts_recent": recent_alerts,
        "timeline_recent": timeline_recent[:60],
        "event_stats": event_stats,
        "timeline_last_n": timeline_events[-30:],  # brand-new this poll; for live log
    "leaderboard_table_top_30": leaderboard[:30] if isinstance(leaderboard, list) else [],
    "all_workers": all_workers,
}


CLEANUP_EVERY_N_POLLS = max(60, int(86400 / POLL_INTERVAL))  # ~once a day


def purge_old():
    cutoff = int(time.time()) - 30 * 86400
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute("DELETE FROM snapshots WHERE ts < ?", (cutoff,))
        c.execute("DELETE FROM alerts WHERE ts < ?", (cutoff,))
        c.execute("DELETE FROM share_timeline WHERE ts < ?", (cutoff,))
        c.execute("DELETE FROM proximity_history WHERE ts < ?", (cutoff,))
        conn.commit()
        conn.close()
    except Exception as e:
        log.warning("[purge] error: %s", e)


def poll_loop():
    n = 0
    while True:
        try:
            poll_once()
            n += 1
            if n >= CLEANUP_EVERY_N_POLLS:
                purge_old()
                n = 0
        except Exception as e:
            log.error("[poll_loop] error: %s", e)
        time.sleep(POLL_INTERVAL)


# Kick off a poll on startup, then run loop in background.
poll_once()
threading.Thread(target=poll_loop, daemon=True).start()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Routes
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
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
    return jsonify(latest_snapshot)


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
    top = latest_snapshot.get("leaderboard_table_top_30") or []
    enriched = []
    for entry in top:
        if isinstance(entry, dict):
            entry_copy = dict(entry)  # don't mutate the cached list
            entry_copy["is_me"] = entry_copy.get("address") == BTC_ADDRESS
            enriched.append(entry_copy)
    return jsonify({
        "entries": enriched,
        "total": latest_snapshot.get("leaderboard_total", len(top)),
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
    snap = dict(latest_snapshot.get("event_stats") or {})
    snap["server_now"] = int(time.time())
    snap["poll_age_s"] = (
        snap["server_now"] - (latest_snapshot.get("ts") or 0)
        if latest_snapshot.get("ts")
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
    return jsonify(latest_snapshot.get("halving") or {})


@app.route("/api/mempool_fees")
def api_mempool_fees():
    return jsonify(latest_snapshot.get("mempool_fees") or {})


@app.route("/api/profitability")
def api_profitability():
    p = dict(latest_snapshot.get("profitability") or {})
    p["active_currency"] = load_settings().get("active_currency", "USD")
    return jsonify(p)


@app.route("/api/network_share")
def api_network_share():
    return jsonify(latest_snapshot.get("network_share_gauge") or {})


@app.route("/api/milestones")
def api_milestones():
    return jsonify({"milestones": latest_snapshot.get("milestones") or []})


@app.route("/api/workers")
def api_workers():
    """Return all workers from the connected wallet's workerData."""
    return jsonify({"workers": latest_snapshot.get("all_workers") or []})


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

    worker = latest_snapshot.get("worker") or {}
    net_diff = (latest_snapshot.get("network") or {}).get("difficulty")
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
    base = dict(latest_snapshot.get("proximity") or {})
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
            "last_poll_ts": latest_snapshot.get("ts"),
            "now": int(time.time()),
            "age_s": int(time.time()) - (latest_snapshot.get("ts") or 0),
        }
    )



# ═══════════════════════════════════════════════════════════════════════════
# SOLO MINING ADVISOR API
# ═══════════════════════════════════════════════════════════════════════════

@app.route("/api/solo-mining/calc")
def api_solo_mining_calc():
    """Calculate solo mining probabilities.
    Params: hashrate (e.g. 225TH), duration (hours), difficulty (optional)
    """
    hashrate = request.args.get("hashrate", "")
    duration = request.args.get("duration", 24)
    difficulty = request.args.get("difficulty", None)

    if not hashrate:
        return jsonify({"error": "hashrate required (e.g. 225TH)"}), 400

    try:
        duration = float(duration)
    except ValueError:
        return jsonify({"error": "invalid duration"}), 400

    # Use provided difficulty or fetch from live data
    if difficulty:
        try:
            difficulty = float(difficulty)
        except ValueError:
            difficulty = None

    if not difficulty:
        # Try live data from latest snapshot
        net = latest_snapshot.get("network", {})
        difficulty = float(net.get("difficulty", 0))
        if not difficulty:
            # Fallback: fetch from mempool
            d = solo_mining.get_network_difficulty()
            if d:
                difficulty = d

    if not difficulty or difficulty <= 0:
        return jsonify({"error": "could not determine network difficulty",
                        "hint": "pass ?difficulty=N as query param"}), 400

    hashrate_hs = solo_mining._parse_hashrate(hashrate)
    result = {
        "hashrate": hashrate,
        "hashrate_hs": hashrate_hs,
        "duration_hours": duration,
        "difficulty": difficulty,
        "probability": solo_mining.calc_block_probability(hashrate_hs, difficulty, duration * 3600),
        "expected_time": solo_mining.calc_expected_time(hashrate_hs, difficulty),
        "best_diff": solo_mining.calc_best_diff_expected(hashrate_hs, duration * 3600),
        "terminal_output": solo_mining.format_calc_output(hashrate, difficulty, duration),
    }
    return jsonify(result)


@app.route("/api/solo-mining/compare")
def api_solo_mining_compare():
    """Compare rental platforms. Auto-fetches Braiins orderbook + MRR listings.
    Params: budget (BTC), duration (hours), braiins_price, mrr_price (optional),
            mrr_api_key, mrr_api_secret (optional, for MRR auth)
    """
    budget = request.args.get("budget", 0)
    duration = request.args.get("duration", 24)
    braiins_price = request.args.get("braiins_price", None)
    mrr_price = request.args.get("mrr_price", None)
    auto_fetch = request.args.get("auto_fetch", "1") != "0"
    mrr_api_key = request.args.get("mrr_api_key") or os.environ.get("MRR_API_KEY")
    mrr_api_secret = request.args.get("mrr_api_secret") or os.environ.get("MRR_API_SECRET")

    try:
        budget = float(budget)
        duration = float(duration)
    except ValueError:
        return jsonify({"error": "invalid budget or duration"}), 400

    if budget <= 0:
        return jsonify({"error": "budget must be > 0 BTC"}), 400

    # Get difficulty
    net = latest_snapshot.get("network", {})
    difficulty = float(net.get("difficulty", 0))
    if not difficulty:
        d = solo_mining.get_network_difficulty()
        difficulty = d or 110e12  # last resort fallback

    results = solo_mining.compare_rentals(
        budget, difficulty, duration,
        float(braiins_price) if braiins_price else None,
        float(mrr_price) if mrr_price else None,
        auto_fetch=auto_fetch,
        mrr_api_key=mrr_api_key,
        mrr_api_secret=mrr_api_secret,
    )

    terminal = solo_mining.format_compare_output(
        budget, difficulty, duration,
        float(braiins_price) if braiins_price else None,
        float(mrr_price) if mrr_price else None,
        auto_fetch=auto_fetch,
        mrr_api_key=mrr_api_key,
        mrr_api_secret=mrr_api_secret,
    )

    return jsonify({
        "budget_btc": budget,
        "duration_hours": duration,
        "difficulty": difficulty,
        "options": results,
        "terminal_output": terminal,
    })


@app.route("/api/solo-mining/network")
def api_solo_mining_network():
    """Get current network stats for solo mining calculations."""
    difficulty = solo_mining.get_network_difficulty()
    btc_price = solo_mining.get_btc_price()
    pool_stats = solo_mining.get_parasite_best_diff()

    net = latest_snapshot.get("network", {})
    return jsonify({
        "difficulty": difficulty or float(net.get("difficulty", 0)),
        "btc_price_usd": btc_price.get("usd", 0),
        "btc_price_brl": btc_price.get("brl", 0),
        "pool_hashrate": pool_stats.get("pool_hashrate", 0),
        "pool_workers": pool_stats.get("pool_workers", 0),
    })


if __name__ == "__main__":
    art = r"""
   ___ __  __ ____  _   _ ____  __  __ ___ ______   __
  / __|  \/  |  _ \| \ | |  _ \ \ \/ // ___/ __\ \ / /
 | (__| |\/| | |_) |  \| | |_) | \  / \___ \__ \\ V /
  \___|_|  |_|____/|_|\__|____/   |_| |___/___/ \_/

   ⇢  cypher65 war room starting on http://localhost:%d
   ⇢  address:    %s
   ⇢  worker:     %s
   ⇢  poll every: %ds — DB at %s
    """ % (PORT, BTC_ADDRESS[:14] + "…", WORKER_NAME, POLL_INTERVAL, DB_PATH)
    print(art)
    app.run(host="0.0.0.0", port=PORT, debug=False, threaded=True)
