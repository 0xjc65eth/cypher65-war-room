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
from typing import Any, Dict, List, Optional
from datetime import datetime, timezone

from flask import Flask, jsonify, render_template, request, abort
import requests
import concurrent.futures

import solo_mining

from helpers import (
    parse_diff_to_float, fmt_diff, fmt_hashrate, fmt_uptime, fmt_age,
    safe_int, safe_num_from_str, coerce_float, coerce_int,
    human_int, human_secs_long, isfinite_v, make_memory_alert,
)

import services.state as _shared_state
from agents.opportunity_engine import scan as _opp_scan, build_response as _opp_build_response
from agents import solo_mining_advisor as _opp_advisor  # monkeypatch-safe: accessed dynamically in route
from routes.solo_mining_routes import solo_mining_bp
from services.probability_engine import register_probability_routes
from services.probability import calculate_multiple_periods, _seconds_to_human
from services.hashrate_market import (
    fetch_all_offers as _fetch_all_offers,
    score_offer as _score_offer,
    build_highlights as _build_market_highlights,
    persist_market_history as _persist_market_history,
    fetch_market_history as _fetch_market_history,
    enrich_opportunity_dict as _enrich_opportunity,
)
from axe_fleet.routes import axe_fleet_bp, init_routes as _init_axe_routes
from axe_fleet.registry import DeviceRegistry
from routes.alerts_routes import alerts_bp, _set_get_db as _alerts_set_get_db

# ── Core CYPHER65 device registry ───────────────────────────────────────────
from core.registry.device_registry import DeviceRegistry as CoreDeviceRegistry
from core.adapters import get_adapter
from core.models.device import Device as CoreDevice, DeviceStatus as CoreDeviceStatus
from core.safety.safety_engine import SafetyEngine
from core.diagnostics.diagnostics_engine import DiagnosticsEngine, DiagnosticSeverity

# ── Fleet telemetry freshness threshold (seconds) ─────────────────────────────
# Telemetry snapshots older than this are no longer considered "recent".
TELEMETRY_FRESHNESS_THRESHOLD = 300

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

# ── Register blueprints ─────────────────────────────────────────────────────
app.register_blueprint(solo_mining_bp, url_prefix='/api/solo-mining')
register_probability_routes(app)

# ── Register Axe Fleet blueprint ────────────────────────────────────────────
app.register_blueprint(axe_fleet_bp, url_prefix='/api/axe-fleet')

# ── Register Auth blueprint (MILESTONE 11: Security Hardening) ──────────────
from routes.auth_routes import auth_bp
app.register_blueprint(auth_bp)

# ━━ Simple in-memory rate limiter ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
_rate_limit_store = {}  # {ip: [timestamps]}

@app.before_request
def rate_limit():
    """Simple rate limiter: max RATE_LIMIT_PER_MINUTE requests per IP per minute.
    Skips static files and the /healthz endpoint.
    Disabled in TESTING mode so test suites can call endpoints freely."""
    if app.config.get("TESTING", False):
        return None
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
    _rate_limit_store[ip].append(now)    # GC old IPs periodically
    if len(_rate_limit_store) > 5000:
        _rate_limit_store.clear()


@app.after_request
def add_cache_headers(response):
    """Set Cache-Control headers to prevent stale cache:
    - HTML responses (no static): no-cache, must-revalidate
    - Static JS/CSS: short max-age (5 min) so updates propagate
    - API responses: no-cache
    - SW.js: no-cache (never cache the SW itself!)"""
    path = request.path
    if path == '/static/sw.js' or path.endswith('/sw.js'):
        # Service Worker MUST NOT be cached by the browser
        response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '0'
    elif path.startswith('/static/'):
        # Static assets: short cache (5 min) so updates propagate
        response.headers['Cache-Control'] = 'public, max-age=300'
    else:
        # HTML pages and API responses: always fresh
        response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '0'
    return response


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  SQLite
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


# Inject the real get_db factory into the alerts blueprint so it doesn't need
# to import the app module at runtime (avoids circular dependency).
_alerts_set_get_db(get_db)
app.register_blueprint(alerts_bp)


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
            message TEXT,
            device_id TEXT DEFAULT '',
            alert_type TEXT DEFAULT 'threshold',
            is_acknowledged INTEGER DEFAULT 0,
            active INTEGER DEFAULT 1,
            meta TEXT DEFAULT '{}'
        )"""
    )
    # ── Milestone 9: ensure legacy alerts tables have the new columns ──
    c.execute("PRAGMA table_info(alerts)")
    existing_cols = {row[1] for row in c.fetchall()}
    col_defs = {
        "device_id": "TEXT DEFAULT ''",
        "alert_type": "TEXT DEFAULT 'threshold'",
        "is_acknowledged": "INTEGER DEFAULT 0",
        "active": "INTEGER DEFAULT 1",
        "meta": "TEXT DEFAULT '{}'",
    }
    for col, defn in col_defs.items():
        if col not in existing_cols:
            try:
                c.execute(f"ALTER TABLE alerts ADD COLUMN {col} {defn}")
            except Exception as e:
                log.warning("[init_db] could not add column %s: %s", col, e)
    c.execute("CREATE INDEX IF NOT EXISTS idx_alerts_active ON alerts(active)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_alerts_device ON alerts(device_id)")
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

    # ── Axe Fleet tables ──
    c.execute(
        """CREATE TABLE IF NOT EXISTS axe_devices (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            model TEXT DEFAULT '',
            manufacturer TEXT DEFAULT '',
            firmware TEXT DEFAULT '',
            firmware_version TEXT DEFAULT '',
            api_version TEXT DEFAULT '',
            ip_address TEXT NOT NULL,
            hostname TEXT DEFAULT '',
            mac_address TEXT DEFAULT '',
            last_seen INTEGER DEFAULT 0,
            status TEXT DEFAULT 'OFFLINE',
            group_id TEXT DEFAULT '',
            capabilities TEXT DEFAULT '{}',
            added_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL
        )"""
    )
    c.execute(
        """CREATE TABLE IF NOT EXISTS axe_telemetry (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts INTEGER NOT NULL,
            device_id TEXT NOT NULL,
            payload TEXT NOT NULL
        )"""
    )
    # ── Maintenance history table (Milestone 5) ──
    c.execute(
        """CREATE TABLE IF NOT EXISTS maintenance_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts INTEGER NOT NULL,
            device_id TEXT NOT NULL,
            type TEXT NOT NULL,
            notes TEXT DEFAULT '',
            performed_by TEXT DEFAULT ''
        )"""
    )
    # ── Best difficulty history table (Milestone 6) ──
    c.execute(
        """CREATE TABLE IF NOT EXISTS best_diff_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts INTEGER NOT NULL,
            device_id TEXT,
            best_diff REAL NOT NULL,
            best_diff_str TEXT DEFAULT '',
            pool TEXT DEFAULT ''
        )"""
    )
    c.execute("CREATE INDEX IF NOT EXISTS idx_best_diff_history_ts ON best_diff_history(ts)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_best_diff_history_device ON best_diff_history(device_id)")
    # ── Hashrate market history table (Milestone 7) ──
    c.execute(
        """CREATE TABLE IF NOT EXISTS hashrate_market_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts INTEGER NOT NULL,
            provider TEXT NOT NULL,
            hashrate REAL,
            price_per_th_day REAL,
            duration_days REAL,
            fee_pct REAL,
            algorithm TEXT,
            score REAL,
            raw_data TEXT
        )"""
    )
    c.execute("CREATE INDEX IF NOT EXISTS idx_hashrate_market_history_ts ON hashrate_market_history(ts)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_hashrate_market_history_provider ON hashrate_market_history(provider)")
    # ── Milestone 9: Alert Rules (configurable thresholds) ──
    c.execute(
        """CREATE TABLE IF NOT EXISTS alert_rules (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            metric TEXT NOT NULL,
            operator TEXT NOT NULL DEFAULT '>',  -- >, <, >=, <=, ==, !=
            threshold REAL NOT NULL,
            severity TEXT NOT NULL,  -- CRIT, WARN, INFO, GOLD
            category TEXT NOT NULL,
            device_id TEXT DEFAULT '',
            model TEXT DEFAULT '',
            enabled INTEGER DEFAULT 1,
            cooldown_seconds INTEGER DEFAULT 300
        )"""
    )
    c.execute("CREATE INDEX IF NOT EXISTS idx_alert_rules_enabled ON alert_rules(enabled)")
    # ── Milestone 9: Automation Rules ──
    c.execute(
        """CREATE TABLE IF NOT EXISTS automation_rules (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            target_device_id TEXT NOT NULL,
            condition_metric TEXT NOT NULL,
            condition_operator TEXT NOT NULL,
            condition_value REAL NOT NULL,
            action_command TEXT NOT NULL,
            action_parameters TEXT DEFAULT '{}',
            is_enabled INTEGER DEFAULT 1,
            min_interval_seconds INTEGER DEFAULT 60
        )"""
    )
    # ── Milestone 9: ensure legacy automation_rules tables have the new column ──
    c.execute("PRAGMA table_info(automation_rules)")
    auto_cols = {row[1] for row in c.fetchall()}
    if "min_interval_seconds" not in auto_cols:
        try:
            c.execute("ALTER TABLE automation_rules ADD COLUMN min_interval_seconds INTEGER DEFAULT 60")
        except Exception as e:
            log.warning("[init_db] could not add column min_interval_seconds: %s", e)
    c.execute("CREATE INDEX IF NOT EXISTS idx_automation_rules_enabled ON automation_rules(is_enabled)")
    # ── Milestone 9: Alert History / Audit ──
    c.execute(
        """CREATE TABLE IF NOT EXISTS alert_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts INTEGER NOT NULL,
            alert_type TEXT NOT NULL,
            device_id TEXT DEFAULT '',
            severity TEXT NOT NULL,
            action_taken TEXT DEFAULT ''
        )"""
    )
    c.execute("CREATE INDEX IF NOT EXISTS idx_alert_history_ts ON alert_history(ts)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_alert_history_device ON alert_history(device_id)")
    # ── Milestone 9: Automation Execution Log ──
    c.execute(
        """CREATE TABLE IF NOT EXISTS automation_execution_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts INTEGER NOT NULL,
            rule_id INTEGER,
            rule_name TEXT DEFAULT '',
            device_id TEXT DEFAULT '',
            action_command TEXT DEFAULT '',
            status TEXT DEFAULT '',
            reason TEXT DEFAULT '',
            result TEXT DEFAULT '{}'
        )"""
    )
    c.execute("CREATE INDEX IF NOT EXISTS idx_automation_execution_log_ts ON automation_execution_log(ts)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_automation_execution_log_rule ON automation_execution_log(rule_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_automation_execution_log_device ON automation_execution_log(device_id)")
    # ── WAL mode for better concurrent read/write ──
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA synchronous=NORMAL")
    c.execute("PRAGMA cache_size=-8000")  # 8MB cache
    c.execute("PRAGMA busy_timeout=3000")
    conn.commit()
    conn.close()


init_db()

# ── Initialize Axe Fleet registry (after get_db/init_db are defined) ──
_axe_registry = DeviceRegistry(get_db)
_init_axe_routes(_axe_registry)

# ── Initialize Core CYPHER65 device registry ───────────────────────────────
# Uses the same SQLite file (WAL mode enabled above) but a separate `devices`
# table managed by core/registry/device_registry.py.
_core_registry = CoreDeviceRegistry(DB_PATH)
_core_registry.load_from_db()

# ── In-memory command history store ──────────────────────────────────────────
# Stores executed commands per device for lightweight audit logging.
# Each entry: { "device_id": str, "command": str, "parameters": dict,
#              "timestamp": int, "result": dict }
_command_history: Dict[str, List[Dict[str, Any]]] = {}

# ── Module-level SafetyEngine ────────────────────────────────────────────────
# Shared across requests so restart cooldowns and other safety state persist.
_safety_engine = SafetyEngine()

# ── Milestone 9: Alert & Automation engines ──────────────────────────────────
from core.alerts.alert_engine import AlertEngine
from core.alerts.automation_engine import AutomationEngine
from services.push_notifier import notify_alert


_alert_engine = None
_automation_engine = None


def _init_alert_engines():
    """Initialize alert/automation engines after all helper functions are defined."""
    global _alert_engine, _automation_engine
    if _alert_engine is None:
        _alert_engine = AlertEngine(DB_PATH, push_callback=notify_alert)
    if _automation_engine is None:
        _automation_engine = AutomationEngine(
            DB_PATH, _safety_engine,
            execute_command_callback=_execute_command_for_automation,
            audit_callback=_audit_automation_result,
        )


def _audit_automation_result(*, ts=None, alert_type="automation", device_id="", severity="INFO", action_taken="", rule_id=None, rule_name="", action_command="", status="", reason="", result=""):
    """Persist automation rule execution outcome to the dedicated execution log.

    Accepts keyword arguments so it can be used as AutomationEngine.audit_callback.
    Also mirrors a short entry to alert_history for backward compatibility.
    """
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute(
            """INSERT INTO automation_execution_log
            (ts, rule_id, rule_name, device_id, action_command, status, reason, result)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                int(ts or time.time()),
                rule_id,
                rule_name or "",
                device_id or "",
                action_command or "",
                status or "",
                reason or "",
                json.dumps(result) if isinstance(result, dict) else str(result),
            ),
        )
        c.execute(
            "INSERT INTO alert_history (ts, alert_type, device_id, severity, action_taken) VALUES (?, ?, ?, ?, ?)",
            (
                int(ts or time.time()),
                alert_type,
                device_id or "",
                severity,
                f"{status}: {action_taken}" if action_taken else status,
            ),
        )
        conn.commit()
        conn.close()
    except Exception as e:
        log.warning("[automation audit] error: %s", e)


def _execute_command_for_automation(device_id: str, command: str, parameters: Dict[str, Any]) -> Dict[str, Any]:
    """Adapter used by AutomationEngine to run a device command through the
    same path as the REST endpoint (lookup, supports, safety, execute)."""
    device = _core_registry.get_device(device_id)
    if not device:
        return {"success": False, "error": "device not found"}
    try:
        adapter = get_adapter(device)
    except NotImplementedError as e:
        return {"success": False, "error": str(e)}
    if not adapter.supports(command):
        return {"success": False, "error": f"command '{command}' not supported"}
    safety_result = _safety_engine.validate_command(device, command, parameters)
    if not safety_result.allowed:
        return {"success": False, "error": safety_result.reason}
    result = adapter.execute_command(device, command, parameters)
    _record_command(device_id, command, parameters, result)
    if command in ("restart", "reboot") and result.get("success"):
        device.status = "OFFLINE"
        _core_registry.update_device(device.id, status="OFFLINE")
    return result

# ── Command history lock ─────────────────────────────────────────────────────
# Guard the in-memory command history against concurrent request mutation.
_command_history_lock = threading.Lock()

# ── Hashrate market in-memory cache (Milestone 7) ─────────────────────────────
# Avoids hitting live provider APIs on every request. TTL in seconds.
_HASHRATE_MARKET_CACHE = {"ts": 0, "offers": None}
_HASHRATE_MARKET_CACHE_TTL = 60          # successful fetches
_HASHRATE_MARKET_EMPTY_CACHE_TTL = 15      # empty fetches (avoid hammering APIs)


def _record_command(device_id: str, command: str, parameters: Optional[Dict[str, Any]], result: Dict[str, Any]):
    """Append a command execution record to the in-memory history.

    Each entry exposes a top-level "success" boolean plus the original
    "result" payload, making the history easy to consume by the frontend.
    """
    entry = {
        "device_id": device_id,
        "command": command,
        "parameters": parameters or {},
        "timestamp": int(time.time()),
        "success": bool(result.get("success")),
        "result": result,
    }
    with _command_history_lock:
        _command_history.setdefault(device_id, []).append(entry)
        # Keep the last 100 entries per device to avoid unbounded growth.
        _command_history[device_id] = _command_history[device_id][-100:]

# ── Initialize engines now that all callbacks are defined ────────────────────
try:
    _init_alert_engines()
except Exception as e:
    log.warning("[alert_automation] failed to initialize engines: %s", e)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  State cache — single source of truth
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# poll_once() writes to latest_snapshot; Flask blueprints read
# services.state.latest_snapshot. We ensure both refer to the SAME dict
# by explicitly pointing _shared_state.latest_snapshot at our dict.
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

# Point _shared_state.latest_snapshot to the SAME dict so the
# solo_mining_bp blueprint (which reads state.latest_snapshot)
# sees the data that poll_once() writes.
_shared_state.latest_snapshot = latest_snapshot

# Timeline delta tracker — same approach: sync both names to one dict
timeline_state = _shared_state.timeline_state

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

# ── Persisted wallet address ──
# When user changes address via /api/set-address, we save it here and
# in the settings DB so it survives a server restart.
def _load_persisted_address():
    """Restore a previously-saved wallet address from the settings table."""
    global BTC_ADDRESS, WORKER_NAME
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT value FROM settings WHERE key='_wallet_address'")
        r = c.fetchone()
        if r and r["value"]:
            BTC_ADDRESS = r["value"]
        c.execute("SELECT value FROM settings WHERE key='_wallet_worker'")
        r = c.fetchone()
        if r and r["value"]:
            WORKER_NAME = r["value"]
        conn.close()
    except Exception:
        pass

_load_persisted_address()


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


def _persist_best_diff_history(ts: int, best_diff_raw: float, best_diff_str: str, device_id: str = "", pool: str = ""):
    """Persist a new best-difficulty record to the SQLite history table."""
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute(
            "INSERT INTO best_diff_history (ts, device_id, best_diff, best_diff_str, pool) VALUES (?, ?, ?, ?, ?)",
            (int(ts), device_id or "", best_diff_raw, best_diff_str or "", pool or ""),
        )
        conn.commit()
        conn.close()
    except Exception as e:
        log.warning("[persist_best_diff_history] error: %s", e)


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


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Session reset helper (used by /api/set-address)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def _reset_session_state():
    """Wipe all mutable in-memory state so a new wallet starts fresh.
    Called by /api/set-address after validating the new address."""
    global latest_snapshot, memory_critical_alerts, _next_memory_alert_id
    global persist_consec_failures
    global _last_proximity_sample_ts

    # Reset latest_snapshot to defaults (in-place, preserves alias to _shared_state)
    latest_snapshot.clear()
    latest_snapshot.update({
        "ts": 0,
        "worker": None,
        "user_aggregate": None,
        "pool": None,
        "account": None,
        "lightning": None,
        "leaderboard_entry": None,
        "leaderboard_total": 0,
        "highest_diffs": [],
        "network": {"height": None, "difficulty": None, "hashrate": None},
        "btc_price": {"usd": None, "brl": None},
        "luck_estimate": {},
        "alerts_recent": [],
        "timeline_recent": [],
        "event_stats": {},
        "leaderboard_table_top_30": [],
    })

    # Clear critical alerts
    memory_critical_alerts.clear()
    _next_memory_alert_id = 0

    # Reset timeline_state with fresh defaults
    timeline_state["_primed"] = False
    timeline_state["last_submit_ts"] = 0
    timeline_state["last_best_diff_str"] = ""
    timeline_state["all_time_best_diff_raw"] = 0.0
    timeline_state["share_submit_history"].clear()
    timeline_state["share_calc_history"].clear()
    timeline_state["session_share_count"] = 0
    timeline_state["session_best_diff_bumps"] = 0

    # Clear alert dedup cache
    if hasattr(poll_once, '_alert_seen'):
        poll_once._alert_seen.clear()
    if hasattr(poll_once, '_worker_was_present'):
        poll_once._worker_was_present = False

    # Reset proximity sample throttle
    _last_proximity_sample_ts = 0

    # Reset persist failure counter
    persist_consec_failures = 0

    # Clear BTC price cache so next poll fetches fresh
    global btc_price_cache  # already global at module level
    btc_price_cache = {"ts": 0, "data": None}

    # Reset _shared_state.test_opportunities (mock bypass)
    _shared_state.test_opportunities = None

    # ── Re-sync state alias after in-place mutations ──
    _shared_state.latest_snapshot = latest_snapshot


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
                # Persist milestone best-difficulty entry for the history endpoint.
                _persist_best_diff_history(
                    ts,
                    new_val,
                    best_diff_str,
                    device_id=WORKER_NAME,
                    pool="parasite",
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
        # Track online→offline transition — only fire once per transition.
        # Use identifier based on the last known state so we can re-fire
        # if the worker comes back and goes offline again.
        sig = ("worker_offline", "1")
        if sig not in alert_seen and getattr(poll_once, '_worker_was_present', False):
            alerts.append(("CRIT", "worker_offline", "cypher65 not found in workerData"))
            alert_seen.add(sig)
    # Track worker presence for transition detection
    if worker:
        poll_once._worker_was_present = True
        # Clear the offline sig so it can fire again next time
        if ("worker_offline", "1") in alert_seen:
            alert_seen.discard(("worker_offline", "1"))
    else:
        poll_once._worker_was_present = getattr(poll_once, '_worker_was_present', False)

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
        c.execute("SELECT * FROM alerts WHERE ts > ? ORDER BY ts DESC LIMIT 12", (int(time.time()) - 604800,))
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

    # ── Axe Fleet background polling ──
    # Poll each registered device at AXE_POLL_INTERVAL frequency.
    try:
        if _axe_registry:
            devices = _axe_registry.list_devices()
            for device in devices:
                did = device["id"]
                last = _shared_state.axe_last_poll_ts.get(did, 0)
                if ts - last >= _shared_state.AXE_POLL_INTERVAL:
                    _shared_state.axe_last_poll_ts[did] = ts
                    tel = _axe_registry.poll_device(did)
                    if tel:
                        _shared_state.axe_telemetry_cache[did] = tel
    except Exception as e:
        log.warning("[axe poll] error: %s", e)

    # ── Milestone 9: Alert & Automation engines ───────────────────────────────
    try:
        # Build a list of core Device objects from the registry
        _core_devices = _core_registry.list_devices()
        _alerts_generated = _alert_engine.evaluate(_core_devices, pool=pool)
        if _alerts_generated:
            _alert_engine.persist(_alerts_generated)
            _alert_engine.dispatch_push(_alerts_generated)
            # Also append recent in-memory alerts to the live snapshot feed
            for _a in _alerts_generated[:10]:
                memory_critical_alerts.append(_make_memory_alert(
                    _a.ts, _a.severity, _a.category, _a.message
                ))

        # Automation rules: any triggered action must pass SafetyEngine.
        # Results are already audited by the engine's audit callback.
        _automation_engine.evaluate_rules(_core_devices)
    except Exception as e:
        log.warning("[alert_automation] error: %s", e)

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
    "leaderboard_table_top_30": leaderboard[:30] if isinstance(leaderboard, list) else [],    "all_workers": all_workers,
    "axe_fleet": list(_shared_state.axe_telemetry_cache.values()),
}

# ── Sync shared state after each poll ──
    _shared_state.latest_snapshot = latest_snapshot


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
    """Return the full dashboard snapshot, including a small set of
    market highlights derived from cached prices (no extra HTTP calls)."""
    resp = dict(latest_snapshot)
    resp["market_highlights"] = _build_market_highlights(
        latest_snapshot, _shared_state.last_known_prices, max_age_seconds=300
    )
    return jsonify(resp)


@app.route("/api/pool-stats")
def api_pool_stats():
    """Return the latest pool statistics snapshot."""
    return jsonify(latest_snapshot.get("pool") or {})


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
#  Block Hunt + Best Difficulty (Milestone 6)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def _get_best_diff_history(device_id: Optional[str] = None, limit: int = 100) -> List[Dict[str, Any]]:
    """Return best-difficulty history records, newest first.

    If device_id is provided, filter to that device. Otherwise all records.
    """
    records: List[Dict[str, Any]] = []
    try:
        conn = get_db()
        c = conn.cursor()
        if device_id:
            c.execute(
                "SELECT ts, device_id, best_diff, best_diff_str, pool "
                "FROM best_diff_history WHERE device_id = ? "
                "ORDER BY ts DESC, id DESC LIMIT ?",
                (device_id, limit),
            )
        else:
            c.execute(
                "SELECT ts, device_id, best_diff, best_diff_str, pool "
                "FROM best_diff_history ORDER BY ts DESC, id DESC LIMIT ?",
                (limit,),
            )
        for r in c.fetchall():
            records.append({
                "timestamp": r["ts"],
                "device_id": r["device_id"],
                "best_diff": r["best_diff"],
                "best_diff_str": r["best_diff_str"],
                "pool": r["pool"],
            })
        conn.close()
    except Exception as e:
        log.warning("[get_best_diff_history] error: %s", e)
    return records


@app.route("/api/block-hunt", methods=["GET"])
def api_block_hunt():
    """Return the Block Hunt panel: network stats, user stats, probabilities
    and network comparison metrics.

    Probabilities are computed from the latest worker hashrate vs network
    hashrate using the Poisson model in services/probability.
    """
    snap = latest_snapshot
    net = snap.get("network") or {}
    worker = snap.get("worker") or {}

    user_hr = float(worker.get("hashrate") or 0)
    net_hr = float(net.get("hashrate") or 0)
    net_diff = float(net.get("difficulty") or 0)
    block_height = net.get("height")

    best_diff_str = worker.get("bestDifficulty") or ""
    best_diff_raw = parse_diff_to_float(best_diff_str) if best_diff_str else 0.0

    # Probabilities for key windows
    prob_periods = {}
    expected_time = None
    expected_time_human = None
    if user_hr > 0 and net_hr > 0:
        try:
            prob_result = calculate_multiple_periods(user_hr, net_hr)
            prob_periods = prob_result.get("periods", {})
            expected_time = prob_periods.get("24h", {}).get("expected_time_to_block_seconds")
            if expected_time is not None:
                expected_time_human = _seconds_to_human(expected_time)
        except Exception as e:
            log.warning("[block-hunt] probability calculation failed: %s", e)

    # Network comparison
    hashrate_pct = 0.0
    if user_hr > 0 and net_hr > 0:
        hashrate_pct = user_hr / net_hr * 100.0

    distance_to_block = None
    if net_diff and best_diff_raw:
        distance_to_block = net_diff / best_diff_raw

    # Distance to the user's all-time best difficulty record
    all_time_best = (snap.get("proximity") or {}).get("all_time_best_diff_raw") or 0.0
    if all_time_best and best_diff_raw:
        distance_to_all_time_best = all_time_best / best_diff_raw
    else:
        distance_to_all_time_best = None

    # Approximate difficulty ranking from leaderboard if available
    leaderboard_entry = snap.get("leaderboard_entry") or {}
    approx_diff_rank = (
        leaderboard_entry.get("diffRank")
        or leaderboard_entry.get("rankDifficulty")
        or leaderboard_entry.get("rank")
    )

    return jsonify({
        "success": True,
        "ts": int(time.time()),
        "network": {
            "hashrate": net_hr,
            "difficulty": net_diff,
            "block_height": block_height,
        },
        "user": {
            "hashrate": user_hr,
            "best_difficulty": best_diff_raw,
            "best_difficulty_str": best_diff_str,
        },
        "probability": {
            "chance_1h": prob_periods.get("1h", {}).get("probability_at_least_one"),
            "chance_24h": prob_periods.get("24h", {}).get("probability_at_least_one"),
            "chance_7d": prob_periods.get("7d", {}).get("probability_at_least_one"),
            "expected_time_to_block_seconds": expected_time,
            "expected_time_to_block_human": expected_time_human,
        },
        "network_comparison": {
            "hashrate_pct_of_network": round(hashrate_pct, 8),
            "distance_to_block_factor": distance_to_block,
            "distance_to_all_time_best_factor": distance_to_all_time_best,
            "approx_difficulty_rank": approx_diff_rank,
        },
    })


@app.route("/api/best-diff-history", methods=["GET"])
def api_best_diff_history():
    """Return the global best-difficulty history."""
    limit = request.args.get("limit", 100, type=int)
    return jsonify({
        "success": True,
        "records": _get_best_diff_history(device_id=None, limit=limit),
    })


@app.route("/api/devices/<device_id>/best-diff-history", methods=["GET"])
def api_device_best_diff_history(device_id: str):
    """Return the best-difficulty history for a specific device."""
    limit = request.args.get("limit", 100, type=int)
    return jsonify({
        "success": True,
        "device_id": device_id,
        "records": _get_best_diff_history(device_id=device_id, limit=limit),
    })


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


# ═══════════════════════════════════════════════════════════════════════════
# CORE DEVICE API
# ═══════════════════════════════════════════════════════════════════════════

# ── Device serialization helpers ─────────────────────────────────────────────
def _enrich_telemetry(telemetry: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Add runtime freshness info to a telemetry snapshot.

    freshness is the number of seconds between the telemetry timestamp and now.
    If the telemetry has no timestamp, freshness is omitted.
    """
    if telemetry is None:
        return None
    enriched = dict(telemetry)
    ts = enriched.get("timestamp")
    if ts is not None:
        enriched["freshness"] = max(0, int(time.time()) - int(ts))
    return enriched


def _compute_device_health(device: CoreDevice) -> Dict[str, Any]:
    """Run DiagnosticsEngine and derive health_score, active_issues and timestamp."""
    engine = DiagnosticsEngine()
    diagnostics = engine.analyze(device)
    score = 100.0
    active_issues: List[str] = []
    for diag in diagnostics:
        if diag.severity == DiagnosticSeverity.CRITICAL:
            score -= 25.0
        elif diag.severity == DiagnosticSeverity.WARNING:
            score -= 10.0
        if diag.severity in (DiagnosticSeverity.CRITICAL, DiagnosticSeverity.WARNING):
            active_issues.append(diag.message)
    score = max(0.0, min(100.0, score))
    return {
        "health_score": round(score, 1),
        "active_issues": active_issues,
        "last_diagnostic_at": int(datetime.now(timezone.utc).timestamp()),
    }


def _record_status_change(device: CoreDevice, old_status: str, new_status: str):
    """Append a status change event to device.metadata['status_history']."""
    if old_status == new_status:
        return
    metadata = device.metadata or {}
    history = metadata.setdefault("status_history", [])
    history.append({
        "ts": int(time.time()),
        "old_status": old_status,
        "new_status": new_status,
    })
    # Keep last 100 status changes to avoid unbounded growth.
    metadata["status_history"] = history[-100:]
    device.metadata = metadata


def _serialize_device(device: CoreDevice, include_telemetry: bool = True) -> Dict[str, Any]:
    """Serialize a core Device, optionally enriching current_telemetry.

    The device dict always contains last_seen, ip and status.  When
    current_telemetry exists, the freshness field is recomputed at call time.
    Health fields (health_score, active_issues, last_diagnostic_at) are
    recomputed on every serialization so they reflect the latest diagnostics.
    """
    health = _compute_device_health(device)
    device.health_score = health["health_score"]
    device.active_issues = health["active_issues"]
    device.last_diagnostic_at = health["last_diagnostic_at"]

    data = device.to_dict()
    if include_telemetry:
        data["current_telemetry"] = _enrich_telemetry(data.get("current_telemetry"))
    return data


@app.route("/api/devices", methods=["GET"])
def api_list_devices():
    """List all devices registered in the core DeviceRegistry.

    Returns:
      devices: list of device dicts (with current_telemetry when available)
      summary: count per status (online, offline, warning, critical)
      total: total number of registered devices
    """
    devices = _core_registry.list_devices()
    summary = _core_registry.count_by_status()
    return jsonify({
        "devices": [_serialize_device(d) for d in devices],
        "summary": summary,
        "total": len(devices),
    })


@app.route("/api/devices/<device_id>", methods=["GET"])
def api_get_device(device_id: str):
    """Return full details for a single device, including telemetry and capabilities."""
    device = _core_registry.get_device(device_id)
    if not device:
        return jsonify({"error": "device not found", "success": False}), 404
    return jsonify({
        "success": True,
        "device": _serialize_device(device, include_telemetry=True),
    })


@app.route("/api/devices/<device_id>/refresh", methods=["POST"])
def api_refresh_device(device_id: str):
    """Refresh a single device: fetch telemetry, update status, persist.

    Steps:
      1. Look up the device in the core registry.
      2. Select the correct adapter based on device model.
      3. Call get_telemetry() on the adapter.
      4. Determine device status from the telemetry.
      5. Save telemetry in the device object and update the registry.
    """
    device = _core_registry.get_device(device_id)
    if not device:
        return jsonify({"error": "device not found", "success": False}), 404

    try:
        adapter = get_adapter(device)
    except NotImplementedError as e:
        return jsonify({"error": str(e), "success": False}), 501

    telemetry = adapter.get_telemetry()
    previous_status = device.status

    if telemetry is None:
        device.status = CoreDeviceStatus.OFFLINE
        device.current_telemetry = None
    else:
        device.current_telemetry = telemetry
        temperature = float(telemetry.get("temperature") or 0)
        hashrate = float(telemetry.get("hashrate") or 0)
        if temperature > 90:
            device.status = CoreDeviceStatus.CRITICAL
        elif temperature > 80 or hashrate <= 0:
            device.status = CoreDeviceStatus.WARNING
        else:
            device.status = CoreDeviceStatus.ONLINE
        device.last_seen = datetime.now(timezone.utc)

    # Track reconnects when the device comes back online from offline.
    if previous_status == CoreDeviceStatus.OFFLINE and device.status == CoreDeviceStatus.ONLINE:
        metadata = device.metadata or {}
        metadata["reconnect_count"] = metadata.get("reconnect_count", 0) + 1
        device.metadata = metadata

    device.update_status(device.status)

    # Record status transitions for the timeline.
    if previous_status != device.status:
        _record_status_change(device, previous_status.value, device.status.value)

    _core_registry.update_device(device)

    return jsonify({
        "success": True,
        "device": _serialize_device(device, include_telemetry=True),
        "telemetry": _enrich_telemetry(device.current_telemetry),
    })


@app.route("/api/fleet/summary", methods=["GET"])
def api_fleet_summary():
    """Return a high-level health summary for the entire device fleet."""
    devices = _core_registry.list_devices()
    summary = _core_registry.count_by_status()
    now = int(time.time())
    threshold = TELEMETRY_FRESHNESS_THRESHOLD

    devices_with_recent_telemetry = 0
    total_hashrate = 0.0

    for d in devices:
        tel = d.current_telemetry
        if not tel:
            continue
        ts = tel.get("timestamp")
        if ts is not None and (now - int(ts)) <= threshold:
            devices_with_recent_telemetry += 1
            total_hashrate += float(tel.get("hashrate") or 0.0)

    return jsonify({
        "total": len(devices),
        "status_counts": summary,
        "devices_with_recent_telemetry": devices_with_recent_telemetry,
        "total_hashrate": total_hashrate,
    })


@app.route("/api/devices/<device_id>/command", methods=["POST"])
def api_device_command(device_id: str):
    """Execute a command on a device after safety validation.

    Body (JSON):
      - command (str, required): command to execute (e.g. "restart", "identify")
      - parameters (dict, optional): command-specific parameters

    Flow:
      1. Find the device in the registry.
      2. Instantiate the correct adapter.
      3. Check that the adapter supports the command.
      4. Run SafetyEngine.validate_command().
      5. Execute via the adapter.
      6. Record the command in the in-memory history.
      7. Update the device status when applicable.
    """
    device = _core_registry.get_device(device_id)
    if not device:
        return jsonify({"error": "device not found", "success": False}), 404

    payload = request.get_json(silent=True) or {}
    command = (payload.get("command") or "").strip()
    parameters = payload.get("parameters") or {}

    if not command:
        return jsonify({"error": "command is required", "success": False}), 400

    try:
        adapter = get_adapter(device)
    except NotImplementedError as e:
        return jsonify({"error": str(e), "success": False}), 501

    if not adapter.supports(command):
        return jsonify({"error": f"command '{command}' not supported", "success": False}), 400

    previous_status = device.status

    safety_result = _safety_engine.validate_command(device, command, parameters)
    if not safety_result.allowed:
        record = {
            "success": False,
            "allowed": False,
            "reason": safety_result.reason,
            "risk_level": safety_result.risk_level.value,
            "requires_confirmation": safety_result.requires_confirmation,
        }
        _record_command(device_id, command, parameters, record)
        return jsonify({
            "success": False,
            "error": safety_result.reason,
            "risk_level": safety_result.risk_level.value,
            "requires_confirmation": safety_result.requires_confirmation,
        }), 403

    result = adapter.execute_command(command, parameters)
    _record_command(device_id, command, parameters, result)

    # Update restart cooldown tracking and device status when command succeeds
    if command == "restart" and result.get("success"):
        _safety_engine.record_restart(device)
        device.status = CoreDeviceStatus.OFFLINE

    if previous_status != device.status:
        _record_status_change(device, previous_status.value, device.status.value)
        _core_registry.update_device(device)

    return jsonify({
        "success": bool(result.get("success")),
        "device_id": device_id,
        "command": command,
        "result": result,
    })


@app.route("/api/devices/<device_id>/commands", methods=["GET"])
def api_device_command_history(device_id: str):
    """Return the command execution history for a single device.

    Returns the last 100 entries, newest first.
    """
    device = _core_registry.get_device(device_id)
    if not device:
        return jsonify({"error": "device not found", "success": False}), 404

    history = _command_history.get(device_id, [])
    return jsonify({
        "success": True,
        "device_id": device_id,
        "commands": history[::-1],  # newest first
    })


@app.route("/api/devices/<device_id>/diagnostics", methods=["GET"])
def api_device_diagnostics(device_id: str):
    """Return operational diagnostics for a single device.

    Analyzes the device's current telemetry and metadata and returns a list
    of detected issues (empty list when everything looks healthy).
    """
    device = _core_registry.get_device(device_id)
    if not device:
        return jsonify({"error": "device not found", "success": False}), 404

    engine = DiagnosticsEngine()
    diagnostics = engine.analyze(device)
    return jsonify({
        "success": True,
        "device_id": device_id,
        "diagnostics": [d.to_dict() for d in diagnostics],
    })


def _add_maintenance_record(device_id: str, record_type: str, notes: str, performed_by: str) -> dict:
    """Persist a maintenance record to the SQLite database."""
    ts = int(time.time())
    conn = get_db()
    c = conn.cursor()
    c.execute(
        """INSERT INTO maintenance_records (ts, device_id, type, notes, performed_by)
           VALUES (?, ?, ?, ?, ?)""",
        (ts, device_id, record_type, notes, performed_by),
    )
    conn.commit()
    record_id = c.lastrowid
    conn.close()
    return {
        "id": record_id,
        "timestamp": ts,
        "device_id": device_id,
        "type": record_type,
        "notes": notes,
        "performed_by": performed_by,
    }


def _get_maintenance_records(device_id: str, limit: int = 100) -> list:
    """Return maintenance records for a device, newest first."""
    conn = get_db()
    c = conn.cursor()
    c.execute(
        """SELECT id, ts, device_id, type, notes, performed_by
           FROM maintenance_records
           WHERE device_id = ?
           ORDER BY ts DESC, id DESC
           LIMIT ?""",
        (device_id, limit),
    )
    rows = c.fetchall()
    conn.close()
    return [
        {
            "id": row["id"],
            "timestamp": row["ts"],
            "device_id": row["device_id"],
            "type": row["type"],
            "notes": row["notes"],
            "performed_by": row["performed_by"],
        }
        for row in rows
    ]


@app.route("/api/devices/<device_id>/maintenance", methods=["POST", "GET"])
def api_device_maintenance(device_id: str):
    """Record or list maintenance events for a single device.

    POST body (JSON):
      - type (str, required): e.g. firmware_update, cleaning, hardware_check
      - notes (str, optional)
      - performed_by (str, optional)
    """
    device = _core_registry.get_device(device_id)
    if not device:
        return jsonify({"error": "device not found", "success": False}), 404

    if request.method == "POST":
        data = request.get_json(silent=True) or {}
        record_type = (data.get("type") or "").strip()
        notes = (data.get("notes") or "").strip()
        performed_by = (data.get("performed_by") or "").strip()

        if not record_type:
            return jsonify({"error": "type is required", "success": False}), 400

        record = _add_maintenance_record(device_id, record_type, notes, performed_by)
        return jsonify({
            "success": True,
            "record": record,
        }), 201

    # GET
    records = _get_maintenance_records(device_id)
    return jsonify({
        "success": True,
        "device_id": device_id,
        "records": records,
    })


@app.route("/api/devices/<device_id>/timeline", methods=["GET"])
def api_device_timeline(device_id: str):
    """Return a combined timeline of events for a single device.

    Events include: executed commands, maintenance records, status changes
    and current diagnostics. The result is limited to the 50 most recent
    events and sorted newest first.
    """
    device = _core_registry.get_device(device_id)
    if not device:
        return jsonify({"error": "device not found", "success": False}), 404

    events: List[Dict[str, Any]] = []

    # Commands
    for entry in _command_history.get(device_id, [])[::-1][:50]:
        events.append({
            "timestamp": entry["timestamp"],
            "type": "command",
            "source": "command_history",
            "title": f"Command executed: {entry['command']}",
            "details": entry,
        })

    # Maintenance records
    for rec in _get_maintenance_records(device_id, limit=50):
        events.append({
            "timestamp": rec["timestamp"],
            "type": "maintenance",
            "source": "maintenance_records",
            "title": f"Maintenance: {rec['type']}",
            "details": rec,
        })

    # Status changes
    for change in (device.metadata or {}).get("status_history", [])[::-1][:50]:
        events.append({
            "timestamp": change["ts"],
            "type": "status_change",
            "source": "status_history",
            "title": f"Status changed {change['old_status']} → {change['new_status']}",
            "details": change,
        })

    # Current diagnostics
    engine = DiagnosticsEngine()
    for diag in engine.analyze(device):
        events.append({
            "timestamp": diag.timestamp,
            "type": "diagnostic",
            "source": "diagnostics",
            "title": diag.message,
            "severity": diag.severity.value,
            "details": diag.to_dict(),
        })

    events.sort(key=lambda e: e["timestamp"], reverse=True)
    events = events[:50]

    return jsonify({
        "success": True,
        "device_id": device_id,
        "events": events,
    })


# Serve the service worker from root so it can control the entire app scope
@app.route("/sw.js")
def service_worker():
    return app.send_static_file("sw.js")


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
#  OPPORTUNITY ENGINE API
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@app.route("/api/opportunities")
def api_opportunities():
    """Run a full opportunity scan across Braiins + MRR marketplaces.

    Returns a JSON envelope with:
      - opportunities: list of deal dicts (id, platform, title, price, ...)
      - scan_stats: dict with braiins_ok, braiins_errors, mrr_ok, mrr_errors
      - ts: unix timestamp
      - disclaimer: standard caveat

    Reads snapshot data (network difficulty + worker hashrate) from shared
    service state, and executes marketplace API calls through the solo_mining
    advisor tool dispatch.
    """
    # ── Mock injection bypass (for visual testing) ──
    if _shared_state.test_opportunities is not None:
        return jsonify(_shared_state.test_opportunities)

    snapshot = _shared_state.latest_snapshot
    last_known = _shared_state.last_known_prices

    opportunities, scan_stats = _opp_scan(
        _opp_advisor.execute_tool,  # accessed dynamically → monkeypatch-safe
        snapshot,
        last_known_prices=last_known,
    )

    # Enrich each opportunity with cost/revenue/EV/score/risk metrics and sort by score.
    network_hashrate = (snapshot.get("network") or {}).get("hashrate")
    enriched = [
        _enrich_opportunity(dict(opp), snapshot=snapshot, network_hashrate=network_hashrate)
        for opp in opportunities
    ]
    enriched.sort(
        key=lambda o: (o.get("metrics") or {}).get("score", 0.0),
        reverse=True,
    )

    return jsonify(_opp_build_response(enriched, scan_stats))


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Hashrate market + Opportunity comparison (Milestone 7)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _get_hashrate_market_offers() -> list:
    """Fetch live hashrate offers, caching them for a short TTL.

    Empty results are not cached, so a temporary provider failure can
    recover on the next request. Successful fetches are persisted to the
    hashrate_market_history table.
    """
    now = int(time.time())
    cache = _HASHRATE_MARKET_CACHE
    ttl = _HASHRATE_MARKET_CACHE_TTL if cache["offers"] else _HASHRATE_MARKET_EMPTY_CACHE_TTL
    if (now - cache["ts"] < ttl) and cache["offers"] is not None:
        return cache["offers"]

    offers = _fetch_all_offers()
    if offers:
        try:
            conn = get_db()
            _persist_market_history(conn, offers)
            conn.close()
        except Exception as e:
            log.warning("[hashrate_market] history persistence failed: %s", e)
        cache["ts"] = now
        cache["offers"] = offers
    else:
        # Cache empty results briefly to avoid hammering APIs, while still
        # allowing quick recovery once the market is available again.
        cache["ts"] = now
        cache["offers"] = []

    return offers


@app.route("/api/hashrate-market")
def api_hashrate_market():
    """Return normalized hashrate rental offers from supported providers.

    Persists the fetched snapshot to hashrate_market_history so the
    /api/hashrate-market/history endpoint can serve historical data.
    """
    offers = _get_hashrate_market_offers()
    network_hashrate = (latest_snapshot.get("network") or {}).get("hashrate")
    scored = [_score_offer(offer, network_hashrate) for offer in offers]
    scored.sort(key=lambda o: o["metrics"]["score"], reverse=True)

    return jsonify({
        "success": True,
        "ts": int(time.time()),
        "offers": scored,
    })


@app.route("/api/hashrate-market/history")
def api_hashrate_market_history():
    """Return persisted hashrate market snapshots.

    Query params:
        limit: max rows to return (default 100)
    """
    try:
        limit = int(request.args.get("limit", 100))
    except (TypeError, ValueError):
        limit = 100

    try:
        conn = get_db()
        rows = _fetch_market_history(conn, limit)
        conn.close()
        return jsonify({"success": True, "records": rows})
    except Exception as e:
        log.warning("[hashrate_market_history] error: %s", e)
        return jsonify({"success": False, "error": "failed to fetch history"}), 500


@app.route("/api/opportunities/compare")
def api_opportunities_compare():
    """Compare rental offers side-by-side.

    Query params:
        providers: comma-separated list of providers to include, e.g. braiins,mrr
        ids:       comma-separated list of stable IDs (currently provider names)
    """
    offers = _fetch_all_offers()
    network_hashrate = (latest_snapshot.get("network") or {}).get("hashrate")
    scored = [_score_offer(offer, network_hashrate) for offer in offers]

    offers = _get_hashrate_market_offers()
    network_hashrate = (latest_snapshot.get("network") or {}).get("hashrate")
    scored = [_score_offer(offer, network_hashrate) for offer in offers]

    providers_filter = request.args.get("providers", "")
    ids_filter = request.args.get("ids", "")

    if providers_filter:
        wanted = {p.strip().lower() for p in providers_filter.split(",") if p.strip()}
        scored = [o for o in scored if o["provider"].lower() in wanted]

    if ids_filter:
        wanted = {i.strip() for i in ids_filter.split(",") if i.strip()}
        scored = [o for o in scored if o.get("id") in wanted or o["provider"] in wanted]

    scored.sort(key=lambda o: o["metrics"]["score"], reverse=True)

    return jsonify({
        "success": True,
        "ts": int(time.time()),
        "offers": scored,
    })


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Wallet management — change address via UI
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@app.route("/api/set-address", methods=["POST"])
def api_set_address():
    """Change the monitored BTC address and worker name.
    Validates input, persists to DB, resets session state, and returns
    the new address for the UI to update.

    Body (JSON):
      - address (str, required): BTC address (bc1… or 1…)
      - worker (str, optional): worker name (default: existing)

    Returns 400 on invalid input, 200 on success.
    """
    # ── Declare globals at the very top, before any reference ──
    global BTC_ADDRESS, WORKER_NAME

    data = request.get_json(silent=True) or {}
    new_addr = (data.get("address") or "").strip()
    new_worker = (data.get("worker") or "").strip()

    # ── Validation ──
    errors = []
    if not new_addr:
        errors.append("address is required")
    elif not (new_addr.startswith("bc1") or new_addr.startswith("1")):
        errors.append("address must start with bc1 (bech32) or 1 (legacy)")
    elif len(new_addr) < 26 or len(new_addr) > 64:
        errors.append(f"address length {len(new_addr)} is invalid (must be 26-64 chars)")
    elif new_addr == BTC_ADDRESS and not new_worker:
        errors.append("address is the same as current — no change needed")

    # Validate worker name if provided
    if new_worker and (len(new_worker) < 1 or len(new_worker) > 64):
        errors.append("worker name must be 1-64 characters")

    if errors:
        return jsonify({"error": "; ".join(errors), "success": False}), 400

    # ── Unchanged? Only proceed if worker changed. ──
    if new_addr == BTC_ADDRESS and new_worker == WORKER_NAME:
        return jsonify({"error": "address and worker are unchanged", "success": False}), 400

    old_addr = BTC_ADDRESS
    old_worker = WORKER_NAME

    # ── Persist to DB ──
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute(
            "INSERT INTO settings(key,value,updated_ts) VALUES(?,?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_ts=excluded.updated_ts",
            ("_wallet_address", new_addr, int(time.time())),
        )
        if new_worker:
            c.execute(
                "INSERT INTO settings(key,value,updated_ts) VALUES(?,?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_ts=excluded.updated_ts",
                ("_wallet_worker", new_worker, int(time.time())),
            )
        conn.commit()
        conn.close()
    except Exception as e:
        log.warning("[set-address persist] error: %s", e)
        return jsonify({"error": "failed to persist address", "success": False}), 500

    # ── Update globals ──
    BTC_ADDRESS = new_addr
    if new_worker:
        WORKER_NAME = new_worker

    # ── Reset session state ──
    _reset_session_state()

    # ── Add a SUCCESS alert ──
    ts = int(time.time())
    memory_critical_alerts.append(_make_memory_alert(
        ts, "SUCCESS", "wallet_changed",
        f"Wallet changed from {old_addr[:12]}… → {new_addr[:12]}…"
    ))

    log.info("[set-address] %s → %s (%s)", old_addr[:12], new_addr[:12], new_worker or WORKER_NAME)

    return jsonify({
        "success": True,
        "address": new_addr,
        "worker": WORKER_NAME,
        "old_address": old_addr,
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
