"""
CYPHER65 // PARASITE POOL WAR ROOM
==================================
A real-time monitoring dashboard for the cypher65 worker on Parasite Pool.
Author: built by Buffy for Julio Cesar
"""
import os
import json
import time
import sqlite3
import threading
import collections
import logging
import hmac
from typing import Any, Dict, List, Optional
from datetime import datetime, timezone

from flask import Flask, jsonify, render_template, request, abort, Response
import requests
import concurrent.futures
import queue
import markdown as _md
from markupsafe import Markup

import solo_mining

from helpers import (
    parse_diff_to_float, fmt_diff, fmt_hashrate, fmt_uptime, fmt_age,
    safe_int, safe_num_from_str, coerce_float, coerce_int,
    human_int, human_secs_long, isfinite_v, make_memory_alert,
    derive_worker_hashrate,
    compute_solo_probabilities,
    compute_lender_profitability,
    compute_pool_rental_break_even,
    build_decision_matrix,
    enrich_account_ranks,
)

import services.state as _shared_state
import services.names as _names  # name sanitization + normalization
from services.proximity import _compute_quantum_lock  # FENIX: composite confidence score for the Quantum-Lock panel
from services.session_manager import SessionManager
from services.user_polling import UserPollingWorker, _build_snapshot
from agents.opportunity_engine import scan as _opp_scan, build_response as _opp_build_response
from agents import solo_mining_advisor as _opp_advisor  # monkeypatch-safe: accessed dynamically in route
from routes.solo_mining_routes import solo_mining_bp
from routes.device_control import device_control_bp
from services.probability_engine import register_probability_routes
from services.hashrate_market import (
    PH_TO_TH,
    fetch_all_offers as _fetch_all_offers,
    score_offer as _score_offer,
    persist_market_history as _persist_market_history,
    fetch_market_history as _fetch_market_history,
    enrich_opportunity_dict as _enrich_opportunity,
    market_offer_sort_key as _market_offer_sort_key,
)
import services.rental_performance as _rental_perf  # RENTALS panel (MRR + Braiins)
import services.lan_scanner as _lan_scanner  # Phase B: LAN device auto-discovery
from axe_fleet.routes import axe_fleet_bp, agent_bp, agent_assets_bp, init_routes as _init_axe_routes
from axe_fleet.registry import DeviceRegistry
from routes.alerts_routes import alerts_bp, _set_get_db as _alerts_set_get_db
from routes.settings_routes import settings_bp
from routes.export_routes import export_bp
from routes.dashboard_routes import dashboard_bp
from services.tenant import require_tenant, role_required, SELF_HOST_MAX_WORKERS
import services.db_backup as _db_backup  # C4: automatic SQLite backup + boot integrity check
from services.licensing import (
    is_pro,
    license_status as _license_status,
    issue_license as _licensing_issue,
)
from services import payments as _payments  # R1 revenue: Lemon Squeezy adapter (off-by-default)

# ── Core CYPHER65 device registry ───────────────────────────────────────────
from core.registry.device_registry import DeviceRegistry as CoreDeviceRegistry
from core.adapters import get_adapter
from core.models.device import Device as CoreDevice, DeviceStatus as CoreDeviceStatus, normalize_telemetry
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
# Honest-telemetry premise: deliberately NO default wallet. The dashboard
# boots EMPTY and only starts showing data once the user connects their own
# address via the UI (⚡ CONNECT) or by setting BTC_ADDRESS in the
# environment. Each deployment monitors only its own user's wallet.
# External-review quick win (P0 #2): single source of truth. config.py reads
# env vars at import time (including DB_PATH, which the Core registry consumes
# at module level — tests that set os.environ["DB_PATH"] before `import app`
# still redirect every query to a scratch DB). No more "keep in sync" drift.
from config import (
    BTC_ADDRESS, WORKER_NAME, PARASITE_API, MEMPOOL_API, DATA_DIR, DB_PATH,
    POLL_INTERVAL, PORT, RATE_LIMIT_PER_MINUTE, AUTH_RATE_LIMIT_PER_MINUTE,
    API_KEY, TENANT_API_KEYS,
)

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", os.urandom(32).hex())
app.config['TEMPLATES_AUTO_RELOAD'] = True


# CFO quick-win: gzip/brotli compression of JSON/HTML responses. Transparent
# to routes (flask-compress wraps the response) — smaller snapshot/history
# payloads on mobile/Tailscale links. Skipped automatically for tiny payloads.
from flask_compress import Compress
Compress(app)

# ── Audit C2: refuse to run with auth configured but no SECRET_KEY ──────
# services.auth now raises on token issuance when the secret is missing
# (no more silent ephemeral fallback). Surface the misconfiguration at boot
# too — but only when auth is actually configured, so open self-host mode
# (no API keys) keeps working without one. In open mode the failure still
# surfaces at runtime: username/password register/login call create_token,
# which raises a clear RuntimeError (500) instead of minting unverifiable
# tokens.
if (os.environ.get("API_KEY") or os.environ.get("TENANT_API_KEYS")) \
        and not os.environ.get("SECRET_KEY"):
    log.error("[boot] SECRET_KEY is not set but auth (API_KEY/TENANT_API_KEYS) is configured — "
              "JWT issuance/verification will fail. Set SECRET_KEY in the environment.")

# ── Register blueprints ─────────────────────────────────────────────────────
app.register_blueprint(solo_mining_bp, url_prefix='/api/solo-mining')
register_probability_routes(app)

# ── Register Axe Fleet blueprint ────────────────────────────────────────────
app.register_blueprint(axe_fleet_bp, url_prefix='/api/axe-fleet')
# ── Register Agent API blueprint (SaaS: local agent → cloud dashboard) ───
app.register_blueprint(agent_bp)
app.register_blueprint(agent_assets_bp)

# ── Register Device Control blueprint ────────────────────────────────────
app.register_blueprint(device_control_bp)

# ── Register Auth blueprint (MILESTONE 11: Security Hardening) ──────────────
from routes.auth_routes import auth_bp
app.register_blueprint(auth_bp)

# ── Register Settings blueprint (FASE 2: wallet history) ───────────────
app.register_blueprint(settings_bp)

# ── Register Export blueprint (Fase 6: migrated from app.py) ──────────
app.register_blueprint(export_bp)

# ── Register Dashboard blueprint (Fase 6 · PR2: migrated from app.py) ─
app.register_blueprint(dashboard_bp)

# ━━ Simple in-memory rate limiter ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
_rate_limit_store = {}  # {ip: [timestamps]}
_auth_rate_limit_store = {}  # {ip: [timestamps]} — stricter /api/auth/* budget

@app.before_request
def rate_limit():
    """Simple rate limiter: max RATE_LIMIT_PER_MINUTE requests per IP per minute.
    Skips static files and the /healthz endpoint.
    Disabled in TESTING mode so test suites can call endpoints freely."""
    if app.config.get("TESTING", False):
        return None
    if request.path.startswith('/static') or request.path == '/healthz' or request.path == '/api/healthz' or request.path == '/api/v1/status':
        return None
    ip = request.remote_addr or '127.0.0.1'
    now = time.time()
    window = 60.0
    # Stricter budget for credential endpoints (brute-force protection).
    # POST /api/auth/* = login/register/refresh/logout — never bursty for a
    # legit user, so a tight per-IP limit blocks password sprays without
    # false positives. Auth requests don't consume the generic budget.
    if request.method == "POST" and request.path.startswith("/api/auth/"):
        auth_ips = _auth_rate_limit_store.setdefault(ip, [])
        auth_ips[:] = [t for t in auth_ips if now - t < window]
        if len(auth_ips) >= AUTH_RATE_LIMIT_PER_MINUTE:
            abort(429, description="Too many authentication attempts. Please slow down.")
        auth_ips.append(now)
        # GC stale auth-limit IPs by EXPIRY (same pattern as the generic store)
        if len(_auth_rate_limit_store) > 1000:
            cutoff = now - window
            stale = [k for k, stamps in _auth_rate_limit_store.items()
                     if not stamps or stamps[-1] < cutoff]
            for k in stale:
                del _auth_rate_limit_store[k]
        return None
    if ip not in _rate_limit_store:
        _rate_limit_store[ip] = []
    # Prune old entries
    _rate_limit_store[ip] = [t for t in _rate_limit_store[ip] if now - t < window]
    if len(_rate_limit_store[ip]) >= RATE_LIMIT_PER_MINUTE:
            abort(429, description="Rate limit exceeded. Please slow down.")
    _rate_limit_store[ip].append(now)
    # GC stale IPs by EXPIRY, never a global wipe: prune entries whose most
    # recent request fell outside the window (their budget fully reset). A
    # wholesale clear() would let every previously-limited IP burst again at
    # once — audit C3.
    if len(_rate_limit_store) > 5000:
        cutoff = now - window
        stale = [ip for ip, stamps in _rate_limit_store.items()
                 if not stamps or stamps[-1] < cutoff]
        for ip in stale:
            del _rate_limit_store[ip]


@app.after_request
def add_cors_headers(response):
    """Env-gated CORS for the React Native mobile companion.

    Enabled only when CORS_ORIGINS is set (comma-separated allow-list, or
    '*' for any origin). Same-origin dashboard users are unaffected — no
    CORS headers are emitted unless configured, so self-host stays locked
    down by default.
    """
    origins = os.environ.get("CORS_ORIGINS", "").strip()
    if origins:
        origin = request.headers.get("Origin", "")
        allowed = origins == "*" or (origin and origin in [o.strip() for o in origins.split(",")])
        if allowed:
            response.headers["Access-Control-Allow-Origin"] = "*" if origins == "*" else origin
            response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
            response.headers["Access-Control-Allow-Headers"] = "Authorization, Content-Type, X-API-Key"
            response.headers["Access-Control-Max-Age"] = "86400"
    return response


@app.after_request
def add_security_headers(response):
    """Content-Security-Policy + hardening headers (defense-in-depth).

    The dashboard template uses a small inline <script> boot block (window
    globals injected from Flask) plus legacy inline onclick handlers, so
    script-src keeps 'unsafe-inline' — the meaningful restrictions here are
    connect-src 'self' (no data exfiltration to third parties), object-src
    'none' (no plugin/embed attacks) and frame-ancestors 'self' (no
    clickjacking). Chart.js is loaded from the jsDelivr CDN and fonts from
    Google Fonts, so those origins are explicitly allowed.
    """
    csp = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src 'self' https://fonts.gstatic.com; "
        "img-src 'self' data:; "
        "connect-src 'self'; "
        "object-src 'none'; "
        "base-uri 'self'; "
        "frame-ancestors 'self'; "
        "form-action 'self'"
    )
    response.headers.setdefault("Content-Security-Policy", csp)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    return response


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
    # Honest Telemetry: read DB_PATH from env at call time (mirroring
    # services/tenant.py) so tests can redirect EVERY route — including the
    # axe_fleet registry — to a scratch DB via monkeypatch.setenv("DB_PATH").
    # A static module constant made RBAC integration tests write Test-*
    # devices into the real data/war_room.sqlite.
    conn = sqlite3.connect(os.environ.get("DB_PATH", DB_PATH))
    conn.row_factory = sqlite3.Row
    # Audit C5: per-connection pragmas so concurrent polling writers never
    # hit "database is locked" and readers benefit from WAL. Best-effort:
    # WAL is unavailable on :memory: DBs (returns 'memory') — never fatal.
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA busy_timeout=3000")
    except sqlite3.Error:
        pass
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
            btc_brl REAL,
            btc_jpy REAL,
            btc_krw REAL,
            btc_cny REAL
        )"""
    )
    # ── Multi-currency migration: add fiat columns to EXISTING snapshots tables ──
    # CREATE TABLE IF NOT EXISTS does NOT alter existing tables, so legacy DBs
    # (pre-JPY/KRW/CNY) need ALTER TABLE to expose the new columns. Column names
    # are allowlisted constants — safe to interpolate into DDL.
    c.execute("PRAGMA table_info(snapshots)")
    snap_cols = {row[1] for row in c.fetchall()}
    for _col, _def in (("btc_jpy", "REAL"), ("btc_krw", "REAL"), ("btc_cny", "REAL")):
        if _col not in snap_cols:
            try:
                c.execute(f"ALTER TABLE snapshots ADD COLUMN {_col} {_def}")
                log.info("[migrate] added snapshots.%s column", _col)
            except Exception as e:
                log.warning("[migrate] could not add snapshots.%s: %s", _col, e)
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
    # ── Multi-tenant settings (1000+ users): each tenant has its OWN settings
    # and provider credentials. Named tenants never read the global `settings`
    # table — services/settings.load_settings(tenant_id) isolates per tenant.
    c.execute(
        """CREATE TABLE IF NOT EXISTS tenant_settings (
            tenant_id TEXT NOT NULL,
            key TEXT NOT NULL,
            value TEXT NOT NULL DEFAULT '',
            updated_ts INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (tenant_id, key)
        )"""
    )
    c.execute("CREATE INDEX IF NOT EXISTS idx_tenant_settings_tenant ON tenant_settings(tenant_id)")
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
    # Honest Telemetry: use the env-aware get_db() instead of a hardcoded
    # path so tests that redirect DB_PATH never touch the real database.
    conn = get_db()
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
    # ── Data audit (2026-08-02): missing time-series ts indexes ──
    c.execute("CREATE INDEX IF NOT EXISTS idx_highest_diff_events_ts ON highest_diff_events(ts)")
    # NOTE: idx_maintenance_records_ts is created AFTER the maintenance_records
    # table below (a fresh DB would otherwise fail with "no such table").
    # One snapshot row per poll second — enforce uniqueness so the forced
    # poll and scheduled poll can never double-write the same ts (9,612 dup
    # groups found in the audit). Best-effort: a legacy DB still holding
    # duplicates logs a warning and skips (the migration cleans them).
    try:
        c.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_snapshots_ts ON snapshots(ts)")
    except sqlite3.Error as e:
        log.warning("[init_db] could not create unique snapshots(ts) index (duplicates?): %s", e)

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
    c.execute("CREATE INDEX IF NOT EXISTS idx_maintenance_records_ts ON maintenance_records(ts)")
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
        # ── FASE 2: Wallet address history (past wallets) ──
    c.execute(
        """CREATE TABLE IF NOT EXISTS wallet_address_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            address TEXT NOT NULL,
            worker TEXT DEFAULT '',
            connected_at INTEGER NOT NULL,
            label TEXT DEFAULT ''
        )"""
    )
    c.execute("CREATE INDEX IF NOT EXISTS idx_wallet_history_addr ON wallet_address_history(address)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_wallet_history_ts ON wallet_address_history(connected_at)")
    # ── Donation tracking (FASE 7: "como saber quem doou") ──
    # Records confirmed donations (auto via WebLN preimage, on-chain via the
    # mempool.space watcher, or manual logging). txid/preimage are dedup keys.
    c.execute(
        """CREATE TABLE IF NOT EXISTS donations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts INTEGER NOT NULL,
            method TEXT NOT NULL DEFAULT 'lightning',  -- lightning | btc | hashpower
            amount_sat INTEGER,
            txid TEXT DEFAULT '',
            preimage TEXT DEFAULT '',
            note TEXT DEFAULT '',
            source TEXT DEFAULT 'webln'  -- webln | onchain | manual
        )"""
    )
    c.execute("CREATE INDEX IF NOT EXISTS idx_donations_ts ON donations(ts)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_donations_txid ON donations(txid)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_donations_preimage ON donations(preimage)")

    # ── Multi-tenant migration: add tenant_id to axe_fleet tables ──
    for table_name in ("axe_devices", "axe_telemetry"):
        try:
            c.execute(f"PRAGMA table_info({table_name})")
            cols = {row[1] for row in c.fetchall()}
            if "tenant_id" not in cols:
                c.execute(f"ALTER TABLE {table_name} ADD COLUMN tenant_id TEXT DEFAULT 'default'")
                log.info("[migrate] added tenant_id to %s", table_name)
        except Exception as e:
            log.warning("[migrate] could not add tenant_id to %s: %s", table_name, e)
    try:
        c.execute("CREATE INDEX IF NOT EXISTS idx_axe_devices_tenant ON axe_devices(tenant_id)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_axe_telemetry_tenant ON axe_telemetry(tenant_id)")
    except Exception:
        pass

    # ── Fase 4 · B2: tenants + users tables ──
    c.execute(
        """CREATE TABLE IF NOT EXISTS tenants (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL DEFAULT '',
            plan TEXT NOT NULL DEFAULT 'free',
            max_workers INTEGER NOT NULL DEFAULT 5,
            created_at INTEGER NOT NULL
        )"""
    )
    # ── Fase 4 · B3: migrate legacy tenants tables (pre-plan) ──
    # CREATE TABLE IF NOT EXISTS does NOT alter existing tables, so a tenants
    # table created before B3 lacks plan/max_workers. Add them if missing;
    # SQLite fills existing rows with the FREE-plan defaults.
    try:
        c.execute("PRAGMA table_info(tenants)")
        tenant_cols = {row[1] for row in c.fetchall()}
        for col, col_def in (("plan", "TEXT NOT NULL DEFAULT 'free'"),
                             ("max_workers", "INTEGER NOT NULL DEFAULT 5")):
            if col not in tenant_cols:
                c.execute(f"ALTER TABLE tenants ADD COLUMN {col} {col_def}")
                log.info("[migrate] added %s to tenants", col)
    except Exception as e:
        log.warning("[migrate] could not migrate tenants table: %s", e)

    # ── Fase 4 · B3: provision the operator's own tenant (self-host) ──
    # The "default" tenant is the operator's own deployment — it must NEVER be
    # silently capped by the free tier (that would 403 the 6th add with no UI
    # to raise the limit). INSERT OR IGNORE provisions it once with a generous
    # SELF_HOST_MAX_WORKERS cap; named tenants provisioned via TENANT_API_KEYS
    # still get the strict free defaults until a row is created for them.
    try:
        c.execute(
            "INSERT OR IGNORE INTO tenants (id, name, plan, max_workers, created_at) "
            "VALUES ('default', 'Self-host', 'free', ?, ?)",
            (SELF_HOST_MAX_WORKERS, int(time.time())),
        )
        # The provisioned row is authoritative for the default tenant cap
        # (the in-code fallback in get_tenant_plan only applies pre-row).
        # Commit IMMEDIATELY: sqlite3 auto-opens a transaction before DML, and
        # the PRAGMA synchronous=NORMAL below fails with "Safety level may
        # not be changed inside a transaction" if one is still open.
        conn.commit()
    except Exception as e:
        log.warning("[migrate] could not provision default tenant: %s", e)

    # ── Fase 4 · B3: structured audit log (multi-tenant) ──
    c.execute(
        """CREATE TABLE IF NOT EXISTS audit_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts INTEGER NOT NULL,
            tenant_id TEXT NOT NULL DEFAULT 'default',
            user_id TEXT NOT NULL DEFAULT '',
            action TEXT NOT NULL,
            target TEXT NOT NULL DEFAULT '',
            details TEXT NOT NULL DEFAULT '{}'
        )"""
    )
    c.execute("CREATE INDEX IF NOT EXISTS idx_audit_logs_tenant_ts ON audit_logs(tenant_id, ts)")
    c.execute(
        """CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tenant_id TEXT NOT NULL,
            username TEXT NOT NULL,
            api_key TEXT DEFAULT '',
            created_at INTEGER NOT NULL,
            UNIQUE(tenant_id, username)
        )"""
    )
    c.execute("CREATE INDEX IF NOT EXISTS idx_users_tenant ON users(tenant_id)")

    # ── Fase 4 · B2: add tenant_id to alerts/automations/core tables ──
    for table_name in (
        "alerts", "alert_history", "alert_rules",
        "automation_rules", "automation_execution_log",
    ):
        try:
            c.execute(f"PRAGMA table_info({table_name})")
            cols = {row[1] for row in c.fetchall()}
            if "tenant_id" not in cols:
                c.execute(f"ALTER TABLE {table_name} ADD COLUMN tenant_id TEXT DEFAULT 'default'")
                log.info("[migrate] added tenant_id to %s", table_name)
        except Exception as e:
            log.warning("[migrate] could not add tenant_id to %s: %s", table_name, e)
    try:
        c.execute("CREATE INDEX IF NOT EXISTS idx_alerts_tenant ON alerts(tenant_id)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_alert_rules_tenant ON alert_rules(tenant_id)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_automation_rules_tenant ON automation_rules(tenant_id)")
    except Exception:
        pass

# ── WAL mode for better concurrent read/write ──
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA synchronous=NORMAL")
    c.execute("PRAGMA cache_size=-8000")  # 8MB cache
    c.execute("PRAGMA busy_timeout=3000")
    conn.commit()
    conn.close()


init_db()

# ── Fase 4 · B4: idempotent RBAC schema migration (users.role/password_hash)
# Safe on every boot — ALTER only runs when the column is missing. Runs after
# init_db() so the users table already exists.
from services.tenant import ensure_users_schema as _ensure_users_schema
_ensure_users_schema()

# ── Optional monitoring: Sentry (env-gated) ────────────────────────────────
# Enabled only when SENTRY_DSN is set. Never a hard dependency: if sentry-sdk
# isn't installed the app boots normally (honest telemetry — no fake errors).
_SENTRY_DSN = os.environ.get("SENTRY_DSN", "").strip()
if _SENTRY_DSN:
    try:
        import sentry_sdk
        sentry_sdk.init(
            dsn=_SENTRY_DSN,
            traces_sample_rate=float(os.environ.get("SENTRY_TRACES_SAMPLE_RATE", "0.1")),
            release="cypher65-war-room",
        )
        log.info("[monitor] Sentry enabled (DSN configured)")
    except Exception as e:
        log.warning("[monitor] Sentry init skipped: %s", e)


# Markers written exclusively by the demo seeders. Devices carrying these
# groups are demo data — safe to purge when DEBUG_MOCK is off.
_SEED_GROUP_MARKERS = ("auto-seed", "test-fleet")


def _purge_seed_marked_devices(registry):
    """Remove devices left behind by previous DEBUG_MOCK=1 demo runs or by
    integration tests that hit the real app.
    Removal criteria (never touches user devices):
      - group_id in _SEED_GROUP_MARKERS (auto-seed / test-fleet), OR
      - name starting with the Test- test convention (RBAC tests name their
        devices Test-*; see tests/test_rbac_register.py).
    Also purges ORPHANED axe_telemetry rows whose device no longer exists.
    Returns the number of devices purged. Logs each removed device for audit.

    Note: list_devices() spans tenants but remove_device targets the default
    tenant — acceptable for the current single-tenant deployment.
    """
    removed = 0
    try:
        for d in registry.list_devices():
            name = d.get("name", "")
            if d.get("group_id") in _SEED_GROUP_MARKERS or name.startswith("Test-") or name.startswith("test-"):
                dev_id = d.get("id")
                # hard=True: demo/test rows must be PHYSICALLY gone — they
                # are never user devices, so no tombstone needed (tombstones
                # are for agent-removal zombie protection, not for purges).
                if registry.remove_device(dev_id, hard=True):
                    removed += 1
                    log.info("[axe] purged demo-seeded device %s (%s)", dev_id, name)
        # Drop orphaned telemetry history (removing a device never deleted
        # its axe_telemetry rows — long-running servers accumulated them).
        try:
            conn = registry._get_db()
            c = conn.cursor()
            c.execute("DELETE FROM axe_telemetry WHERE device_id NOT IN (SELECT id FROM axe_devices)")
            orphaned = c.rowcount
            conn.commit()
            conn.close()
            if orphaned:
                log.info("[axe] purged %d orphaned telemetry rows (no device)", orphaned)
        except Exception as e:
            log.warning("[axe] telemetry orphan purge failed: %s", e)
        if removed:
            log.info("[axe] purged %d demo-seeded devices (DEBUG_MOCK off)", removed)
    except Exception as e:
        log.warning("[axe] seed purge failed: %s", e)
    return removed


def _auto_seed_axe_fleet(registry):
    """Auto-seed test devices if the Axe Fleet registry is empty.
    Creates 4 mock devices (3 online/varying health, 1 offline) with
    10 historical telemetry points each so the dashboard has data immediately.

    GATED by DEBUG_MOCK (config.py): in production (default off) this is a
    no-op — and any rows from previous demo runs are purged — so the
    dashboard never shows invented telemetry. Set DEBUG_MOCK=1 for local
    dev/demo seeding.
    """
    if os.environ.get("DEBUG_MOCK") != "1":
        return _purge_seed_marked_devices(registry)  # Honest Telemetry: cleanup leftovers
    import uuid, time
    try:
        devices = registry.list_devices()
        if devices and len(devices) > 0:
            return 0  # already has devices, skip
        log = logging.getLogger("cypher65.app")
        log.info("[axe] registry empty — auto-seeding 4 test devices")
        now = int(time.time())

        mock_devices = [
            {
                "name": "Garage Bitaxe",
                "ip": "192.168.1.100",
                "model": "Bitaxe ULP",
                "firmware": "AxeOS", "version": "2.6.0",
                "hostname": "bitaxe-garage", "status": "ONLINE",
                "hashrate_hs": 5200000000000,
                "temperature": 62, "fan_speed": 80, "fan_rpm": 4200,
                "power_watts": 42, "voltage_mv": 1200, "frequency_mhz": 525,
                "best_diff": "42.8T", "uptime_seconds": 259200,
                "efficiency_jth": 8.08,
                "shares_accepted": 15823, "shares_rejected": 47,
                "hw_error_pct": 0.3, "wifi_rssi": -65, "free_heap": 128000,
            },
            {
                "name": "Office NerdAxe",
                "ip": "192.168.1.101",
                "model": "NerdAxe v2",
                "firmware": "AxeOS", "version": "2.5.1",
                "hostname": "nerdaxe-office", "status": "ONLINE",
                "hashrate_hs": 2100000000000,
                "temperature": 58, "fan_speed": 65, "fan_rpm": 3800,
                "power_watts": 18, "voltage_mv": 1100, "frequency_mhz": 450,
                "best_diff": "12.5T", "uptime_seconds": 604800,
                "efficiency_jth": 8.57,
                "shares_accepted": 45231, "shares_rejected": 89,
                "hw_error_pct": 0.2, "wifi_rssi": -72, "free_heap": 95000,
            },
            {
                "name": "Lab Bitaxe (hot)",
                "ip": "192.168.1.102",
                "model": "Bitaxe Max",
                "firmware": "AxeOS", "version": "2.6.0",
                "hostname": "bitaxe-lab", "status": "WARNING",
                "hashrate_hs": 3800000000000,
                "temperature": 82, "fan_speed": 100, "fan_rpm": 5200,
                "power_watts": 38, "voltage_mv": 1250, "frequency_mhz": 500,
                "best_diff": "28.3T", "uptime_seconds": 43200,
                "efficiency_jth": 10.0,
                "shares_accepted": 5872, "shares_rejected": 215,
                "hw_error_pct": 3.5, "wifi_rssi": -85, "free_heap": 72000,
            },
            {
                "name": "Basement S19",
                "ip": "192.168.1.200",
                "model": "Antminer S19 Pro",
                "firmware": "Braiins OS+", "version": "22.0",
                "hostname": "s19-basement", "status": "OFFLINE",
                "hashrate_hs": 0,
                "temperature": None, "fan_speed": 0, "fan_rpm": 0,
                "power_watts": 0, "voltage_mv": None, "frequency_mhz": 0,
                "best_diff": "", "uptime_seconds": 0,
                "efficiency_jth": None,
                "shares_accepted": 0, "shares_rejected": 0,
                "hw_error_pct": 0.0, "wifi_rssi": None, "free_heap": 0,
            },
        ]

        for m in mock_devices:
            device_id = uuid.uuid4().hex[:12]
            caps = {
                "telemetry": True, "statistics": True,
                "restart": m["status"] in ("ONLINE", "WARNING"),
                "identify": m["status"] in ("ONLINE", "WARNING"),
                "pause": m["firmware"] == "AxeOS",
                "resume": m["firmware"] == "AxeOS",
                "frequencyControl": m["firmware"] == "AxeOS",
                "voltageControl": m["firmware"] == "AxeOS",
                "powerControl": False,
                "configure": m["firmware"] == "AxeOS",
            }
            device_dict = {
                "id": device_id,
                "name": m["name"],
                "model": m["model"],
                "manufacturer": "Bitaxe" if "Bitaxe" in m["model"] or "NerdAxe" in m["model"] else "Bitmain",
                "firmware": m["firmware"],
                "firmware_version": m["version"],
                "api_version": "2.0.0",
                "ip_address": m["ip"],
                "hostname": m["hostname"],
                "mac_address": "",
                "last_seen": now if m["hashrate_hs"] > 0 else 0,
                "status": m["status"],
                "group_id": "auto-seed",
                "added_at": now,
                "updated_at": now,
                "capabilities": caps,
            }
            registry._persist_device(device_dict)

            for i in range(10):
                ts = now - (9 - i) * 300
                hr_variation = m["hashrate_hs"] * (1 + (i % 5 - 2) * 0.02)
                temp_variation = (i % 3 - 1) * 2
                tel = {
                    "ts": ts,
                    "device_id": device_id,
                    "hashrate_hs": int(hr_variation) if m["hashrate_hs"] > 0 else 0,
                    "temperature": m["temperature"] + temp_variation if m["temperature"] is not None else None,
                    # Fase 5: chip/ASIC/VR temps + hashrate windows so the fleet
                    # cards show real values instead of NOT AVAILABLE.
                    "chip_temp": m["temperature"] + temp_variation + 8 if m["temperature"] is not None else None,
                    "vr_temp": m["temperature"] + temp_variation + 5 if m["temperature"] is not None else None,
                    "temp_asic": m["temperature"] + temp_variation + 8 if m["temperature"] is not None else None,
                    "temp_vreg": m["temperature"] + temp_variation + 5 if m["temperature"] is not None else None,
                    "hashrate_1m": int(hr_variation) if m["hashrate_hs"] > 0 else None,
                    "hashrate_10m": int(hr_variation) if m["hashrate_hs"] > 0 else None,
                    "hashrate_1h": int(m["hashrate_hs"]) if m["hashrate_hs"] > 0 else None,
                    "fan_speed": m["fan_speed"],
                    "fan_rpm": m["fan_rpm"],
                    "power_watts": m["power_watts"],
                    "voltage_mv": m["voltage_mv"],
                    "frequency_mhz": m["frequency_mhz"],
                    "best_diff": m["best_diff"],
                    "uptime_seconds": m["uptime_seconds"] + ts - now,
                    "efficiency_jth": m["efficiency_jth"],
                    "shares_accepted": max(0, m["shares_accepted"] + (i - 5) * 100),
                    "shares_rejected": max(0, m["shares_rejected"] + (i - 5) * 5),
                    "hw_error_pct": m["hw_error_pct"],
                    "wifi_rssi": m["wifi_rssi"],
                    "free_heap": m["free_heap"],
                    "stratum_status": "connected" if m["hashrate_hs"] > 0 else "disconnected",
                }
                registry.save_telemetry(device_id, tel)

        log.info("[axe] auto-seeded %d test devices", len(mock_devices))
        return len(mock_devices)
    except Exception as e:
        log = logging.getLogger("cypher65.app")
        log.warning("[axe] auto-seed failed: %s", e)
        return 0


def _purge_core_seed_marked_devices(registry):
    """Remove core devices carrying the seed_marker metadata (written only by
    the core demo seeder). Safe: real devices never carry that marker.
    Returns the number purged; logs each for audit.
    """
    removed = 0
    try:
        for d in registry.list_devices():
            meta = getattr(d, "metadata", None) or {}
            if meta.get("seed_marker") == "auto-seed":
                try:
                    registry.remove_device(d.id)
                    removed += 1
                    log.info("[core] purged demo-seeded device %s (%s)", d.id, getattr(d, "name", ""))
                except Exception:
                    pass
        if removed:
            log.info("[core] purged %d demo-seeded core devices (DEBUG_MOCK off)", removed)
    except Exception as e:
        log.warning("[core] seed purge failed: %s", e)
    return removed


def _purge_test_devices(axe_registry, core_registry):
    """Remove leftover test-suite artifacts from the production DB.

    The test suites (test_alerts_routes, test_maintenance, test_integration_*,
    ...) register devices named Test-*, Listed-*, Health-*, Maint-*, Diag-*,
    Timeline-* plus a 'test-rule' automation rule directly into the same
    SQLite file when run locally. Those rows are NOT demo seeds (no
    seed_marker), so the DEBUG_MOCK purge above doesn't catch them — and they
    surface in the UI as fake offline devices + CRIT 'status=0 == 0' alerts.

    Targets (name-based, all unambiguous test artifacts):
      - core devices: name starts with Test-/Listed-/Health-/Maint-/Diag-/
        Timeline- or is one of Online/Offline/Stale-Device
      - axe devices: name starts with Test-/test- (RBAC suite convention),
        name == ip_address (auto-added junk) or name in {x, ss}
      - automation rule 'test-rule'
      - alerts whose message references those test devices / 'status=0 == 0'
    Returns a dict with per-table counts for logging.
    """
    counts = {"core": 0, "axe": 0, "rules": 0, "alerts": 0}
    _TEST_PREFIXES = ("Test-", "Listed-", "Health-", "Maint-", "Diag-", "Timeline-")
    _TEST_EXACT = ("Online-Device", "Offline-Device", "Stale-Device")

    # ── Core registry ──
    try:
        for d in core_registry.list_devices():
            name = getattr(d, "name", "") or ""
            if name.startswith(_TEST_PREFIXES) or name in _TEST_EXACT:
                try:
                    core_registry.remove_device(d.id)
                    counts["core"] += 1
                    log.info("[purge] removed test core device %s (%s)", d.id, name)
                except Exception:
                    pass
    except Exception as e:
        log.warning("[purge] core test-device purge failed: %s", e)

    # ── Axe registry ──
    try:
        for d in axe_registry.list_devices():
            nm = (d.get("name") or "").strip()
            ip = (d.get("ip_address") or "").strip()
            if nm.startswith(("Test-", "test-")) or nm in ("x", "ss") or (nm == ip and ip):
                try:
                    # hard=True: test artifacts are never user devices — no
                    # tombstone needed (would accumulate forever).
                    axe_registry.remove_device(d.get("id"), hard=True)
                    counts["axe"] += 1
                    log.info("[purge] removed test axe device %s (%s)", d.get("id"), nm)
                except Exception:
                    pass
    except Exception as e:
        log.warning("[purge] axe test-device purge failed: %s", e)

    # ── Automation rule + test alerts ──
    try:
        conn = get_db()
        c = conn.cursor()
        # Any rule the test suites create is named test-* (the integration
        # suite re-seeds 'test-rule' on every run, so match the prefix).
        c.execute("DELETE FROM automation_rules WHERE name LIKE 'test-%'")
        counts["rules"] = c.rowcount
        c.execute(
            "DELETE FROM alerts WHERE message LIKE '%status=0 == 0%' "
            "OR message LIKE 'Test-%' OR message LIKE 'Listed-%' "
            "OR message LIKE 'Health-%' OR message LIKE 'Maint-%' "
            "OR message LIKE 'Diag-%' OR message LIKE 'Timeline-%' "
            "OR message LIKE 'Online-Device%' OR message LIKE 'Offline-Device%' "
            "OR message LIKE 'Stale-Device%'"
        )
        counts["alerts"] = c.rowcount
        conn.commit()
        conn.close()
    except Exception as e:
        log.warning("[purge] test rule/alert purge failed: %s", e)

    total = sum(counts.values())
    if total:
        log.info("[purge] removed %d test artifacts from DB: %s", total, counts)
    return counts


def _auto_seed_core_devices(registry):
    """Auto-seed core device registry with test devices so the alert engine
    has data to evaluate. Creates 4 CoreDevice objects (3 online, 1 offline).
    If existing devices lack telemetry (stale test data), replaces them.

    GATED by DEBUG_MOCK (config.py): in production (default off) this is a
    no-op — and any seed-marked rows from previous demo runs are purged —
    so the alert engine only ever sees real devices.
    """
    if os.environ.get("DEBUG_MOCK") != "1":
        return _purge_core_seed_marked_devices(registry)  # Honest Telemetry: cleanup leftovers
    import uuid
    try:
        existing = registry.list_devices()
        # Check if existing devices have real telemetry; if not, clear stale data
        needs_replacement = False
        for d in existing:
            tel = getattr(d, 'current_telemetry', None) or {}
            if not tel.get('temperature'):
                needs_replacement = True
                break
        if existing and len(existing) > 0 and not needs_replacement:
            return 0  # already has fresh devices, skip
        if needs_replacement:
            log = logging.getLogger("cypher65.app")
            log.info("[core] replacing %d stale test devices with fresh ones", len(existing))
            # Clear stale test devices from DB
            try:
                conn = sqlite3.connect(registry.db_path)
                c = conn.cursor()
                c.execute("DELETE FROM devices")
                conn.commit()
                conn.close()
            except Exception:
                pass
            registry.devices.clear()
        else:
            log = logging.getLogger("cypher65.app")
            log.info("[core] registry empty — auto-seeding 4 core devices")
        now = int(time.time())

        mock = [
            {"name":"Garage Bitaxe","model":"Bitaxe ULP","firmware":"AxeOS","ip":"192.168.1.100","hostname":"bitaxe-garage","status":"ONLINE","hashrate":5200000000000,"temp":62},
            {"name":"Office NerdAxe","model":"NerdAxe v2","firmware":"AxeOS","ip":"192.168.1.101","hostname":"nerdaxe-office","status":"ONLINE","hashrate":2100000000000,"temp":58},
            {"name":"Lab Bitaxe (hot)","model":"Bitaxe Max","firmware":"AxeOS","ip":"192.168.1.102","hostname":"bitaxe-lab","status":"WARNING","hashrate":3800000000000,"temp":82},
            {"name":"Basement S19","model":"Antminer S19 Pro","firmware":"Braiins OS+","ip":"192.168.1.200","hostname":"s19-basement","status":"OFFLINE","hashrate":0,"temp":None},
        ]

        for m in mock:
            status = getattr(CoreDeviceStatus, m["status"], CoreDeviceStatus.OFFLINE)
            device = CoreDevice(
                id=uuid.uuid4().hex[:12],
                name=m["name"],
                model=m["model"],
                firmware=m["firmware"],
                ip=m["ip"],
                hostname=m["hostname"],
                status=status,
                last_seen=datetime.now(timezone.utc) if m["status"] != "OFFLINE" else None,
                current_telemetry={
                    "temperature": m["temp"],
                    "hashrate_hs": m["hashrate"],
                    "hashrate_drop_pct": 0.0 if m["hashrate"] > 0 else 100.0,
                    "reject_rate": 0.5 if m["temp"] and m["temp"] > 75 else 0.1,
                    "stale_rate": 0.2,
                    "pool_online": 1 if m["hashrate"] > 0 else 0,
                },
                capabilities=[],
                metadata={"seed_marker": "auto-seed", "health_score": 100.0 if m["temp"] and m["temp"] < 65 else (50.0 if m["status"] == "WARNING" else 0.0)},
            )
            registry.add_device(device)
        log.info("[core] auto-seeded %d core devices", len(mock))
        return len(mock)
    except Exception as e:
        log = logging.getLogger("cypher65.app")
        log.warning("[core] auto-seed failed: %s", e)
        import traceback
        log.warning("[core] auto-seed traceback: %s", traceback.format_exc())
        return 0


# ── Support/Donation configuration endpoint ──────────────────────────────────
# Addresses configurable via env vars. Falls back to hardcoded defaults.
_SUPPORT_CONFIG = {
    "title": "Support Cypher65",
    "subtitle": "Cypherpunks support cypherpunks.",
    "description": "Este painel é um instrumento da resistência digital: código aberto, sem intermediários, soberano por design. Sua contribuição mantém o desenvolvimento rodando, financia infraestrutura descentralizada e garante que esta ferramenta continue nas mãos de quem a usa — não de corporações. Sem donos. Sem permissão. Apenas criptografia e comunidade. BTC, Lightning e hashpower são aceitos.",
    "manifesto": "Nós não acreditamos em permissão. Acreditamos em chaves privadas, em código aberto e em uma rede sem dono. Este painel é um instrumento de soberania digital: ele não pertence a uma corporação — pertence a quem o usa.\n\nCada linha deste código existe para um único fim: colocar o minerador no controle dos próprios dados. Sem intermediários. Sem vigilância. Sem pedir licença.\n\nSe esta ferramenta te serve, devolve algo à rede que a tornou possível. Não por caridade — por continuidade. Cada sat reinvestido mantém os servidores de pé, o código evoluindo e a porta aberta para o próximo cypherpunk.\n\nA descentralização não é um slogan. É infraestrutura. E infraestrutura se mantém com trabalho e com sats.\n\n— 1BCP_0XJC65.BTC",
    "methods": [
        {
            "id": "btc",
            "label": "Bitcoin",
            "icon": "₿",
            "color": "#f7931a",
            "address": os.environ.get("SUPPORT_BTC", "35gjAoadgQxrNc1Kx6QiSLx7wCCXRnRFkM"),
        },
        {
            "id": "lightning",
            "label": "Lightning",
            "icon": "⚡",
            "color": "#f5b942",
            "address": os.environ.get("SUPPORT_LN", "spark1pgss98nvpcsssdfekenznqqmmaea6nxltz65e0srj7nh7hfkaufpu53nslvtpc"),
        },
        {
            "id": "hashpower",
            "label": "Hashpower",
            "icon": "⛏",
            "color": "#06d6f0",
            "address": os.environ.get("SUPPORT_HASHPOWER", "bc1qvfct7p8ggsxlfy3257pytcqnsvjv77qzpy9pnv"),
            "note": "Braiins / any pool",
        },
    ],
    "cta_text": "Support the project",
    "status": "active",
    "version": "1.2.0",
}


@app.route("/api/support-config")
def api_support_config():
    """Return donation/support configuration.
    Addresses can be updated via env vars SUPPORT_BTC, SUPPORT_LN, SUPPORT_HASHPOWER
    without requiring a code rebuild.
    """
    return jsonify(_SUPPORT_CONFIG)


@app.route("/api/tenant/status")
@require_tenant
def api_tenant_status(tenant_id: str = ""):
    """Return the current tenant's plan and worker usage (multi-tenant free tier).

    Honest by default: when the tenant row doesn't exist (single-tenant mode)
    the FREE-plan defaults (max 5 workers) are reported — never fabricated.
    """
    from services.tenant import get_tenant_plan, count_tenant_workers
    plan = get_tenant_plan(tenant_id)
    used = count_tenant_workers(tenant_id)
    return jsonify({
        "tenant_id": tenant_id or "default",
        "plan": plan["plan"],
        "max_workers": plan["max_workers"],
        "used_workers": used,
        "remaining_workers": max(0, plan["max_workers"] - used),
    })


# ── Donation tracking ──────────────────────────────────────────────────────
# Records confirmed donations so the operator can see who donated (the
# Support modal shows a Recent Donations list fed by GET /api/donations).
_donation_watch_lock = threading.Lock()


def _record_donation(method="lightning", amount_sat=None, txid="", preimage="", note="", source="webln"):
    """Persist a confirmed donation and raise a GOLD alert + push notification.

    Dedupes by txid/preimage so a re-poll or double-submit never double-counts.
    Returns the row dict, or None if it was a duplicate / failed to persist.
    """
    if not (txid or preimage):
        return None
    with _donation_watch_lock:
        try:
            conn = get_db()
            c = conn.cursor()
            # Dedup: same txid or preimage must not be recorded twice.
            # ONLY match when the incoming value is non-empty AND the stored
            # value is non-empty: an empty-string txid/preimage must never
            # collide with an unrelated row (the on-chain watcher / manual
            # logging can leave txid='' or preimage='' rows — matching those
            # made EVERY subsequent preimage-only donation 409 as a "dup").
            c.execute(
                "SELECT id FROM donations "
                "WHERE (COALESCE(txid,'') <> '' AND txid=?) "
                "OR (COALESCE(preimage,'') <> '' AND preimage=?) LIMIT 1",
                (txid or "", preimage or ""),
            )
            if c.fetchone():
                conn.close()
                return None
            ts = int(time.time())
            c.execute(
                "INSERT INTO donations (ts, method, amount_sat, txid, preimage, note, source) VALUES (?,?,?,?,?,?,?)",
                (ts, method, amount_sat, txid or "", preimage or "", note or "", source or "webln"),
            )
            row_id = c.lastrowid
            conn.commit()
            conn.close()
        except Exception as e:
            log.warning("[donation] persist failed: %s", e)
            return None
    # In-memory GOLD alert so the Alerts panel lights up immediately
    label = {"lightning": "⚡ Lightning", "btc": "₿ Bitcoin", "hashpower": "⛏ Hashpower"}.get(method, method)
    amt = f" · {amount_sat:,} sats" if amount_sat else ""
    memory_critical_alerts.append(_make_memory_alert(ts, "GOLD", "donation", f"♥ Donation received via {label}{amt}"))
    try:
        notify_alert("GOLD", "donation", f"Donation received via {label}{amt}")
    except Exception as e:
        log.warning("[donation] push failed: %s", e)
    log.info("[donation] recorded %s (%s) amount=%s", method, source, amount_sat)
    return {"id": row_id, "ts": ts, "method": method, "amount_sat": amount_sat,
            "txid": txid, "preimage": preimage, "note": note, "source": source}


@app.route("/api/donations", methods=["POST"])
@require_tenant
def api_donations_record(tenant_id: str = ""):
    """Record a confirmed donation (POST) — kept OPEN to anonymous donors.

    This is the public WebLN/manual donation flow (Support modal): a donor
    who paid a Lightning invoice or sent on-chain funds reports the proof
    (txid/preimage) so the operator can see who contributed. Requiring a
    login here would silently drop anonymous donations, so only tenant
    resolution applies — no RBAC gate.

    Body: {method, amount_sat, txid, preimage, note, source}
      - txid or preimage is REQUIRED (dedup key) — without proof of payment
        the record is rejected so the list stays honest.
      - source: 'webln' (auto from provider.sendPayment) | 'onchain' (watcher)
        | 'manual' (operator logging an on-chain/other donation)
    """
    data = request.get_json(silent=True) or {}
    method = (data.get("method") or "lightning").strip()
    if method not in ("lightning", "btc", "hashpower"):
        method = "lightning"
    amount_sat = None
    try:
        if data.get("amount_sat") is not None:
            amount_sat = int(float(data["amount_sat"]))
    except (TypeError, ValueError):
        amount_sat = None
    row = _record_donation(
        method=method,
        amount_sat=amount_sat,
        txid=(data.get("txid") or "").strip()[:128],
        preimage=(data.get("preimage") or "").strip()[:128],
        note=(data.get("note") or "").strip()[:500],
        source=(data.get("source") or "webln").strip()[:16],
    )
    if not row:
        return jsonify({"success": False, "error": "duplicate or missing proof (txid/preimage required)"}), 409
    return jsonify({"success": True, "donation": row}), 201


@app.route("/api/donations", methods=["GET"])
@require_tenant
@role_required("viewer")
def api_donations_list(tenant_id: str = ""):
    """List recent donations (GET) — login required when auth is configured.

    ?limit=20 → {donations: [...], total: n, total_sat: sum}
    Reading who donated reveals operational/community data, so this read is
    gated by @role_required("viewer") — anonymous remote callers get 403 in
    auth-configured deployments (open self-host mode stays unaffected).
    """
    limit = min(request.args.get("limit", 20, type=int) or 20, 100)
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT * FROM donations ORDER BY ts DESC LIMIT ?", (limit,))
        rows = [dict(r) for r in c.fetchall()]
        c.execute("SELECT COUNT(*) AS total, COALESCE(SUM(amount_sat),0) AS total_sat FROM donations")
        agg = c.fetchone()
        conn.close()
        return jsonify({"donations": rows, "total": agg["total"], "total_sat": agg["total_sat"]})
    except Exception as e:
        log.warning("[donation] list failed: %s", e)
        return jsonify({"donations": [], "total": 0, "total_sat": 0})


# ── On-chain donation watcher ──────────────────────────────────────────────
# Polls mempool.space for incoming txs to the configured BTC donation
# addresses (SUPPORT_BTC + SUPPORT_HASHPOWER) and auto-records them, so the
# operator is alerted in real time instead of only seeing the list manually.
_DONATION_WATCH_INTERVAL = int(os.environ.get("DONATION_WATCH_INTERVAL", 120))  # seconds
# Ignore dust-spam (a known attack on public donation addresses). Any incoming
# tx below this threshold is NOT recorded as a donation — prevents an attacker
# from flooding the Alerts panel + push with hundreds of fake 'donations'.
_DONATION_MIN_SATS = int(os.environ.get("DONATION_MIN_SATS", 1000))
_DONATION_WATCH_LAST_TX = {}  # address → set of seen txids (in-memory only)


def _donation_watcher_loop():
    """Background thread: watch on-chain donation addresses via mempool.space.
    Polls every DONATION_WATCH_INTERVAL (default 2 min), finds unconfirmed+
    confirmed incoming txs to the BTC + hashpower addresses, and records them
    once each (deduped by txid both in-memory and via the donations table)."""
    addresses = set()
    for m in _SUPPORT_CONFIG.get("methods", []):
        if m.get("id") in ("btc", "hashpower") and m.get("address"):
            addresses.add(m["address"])
    if not addresses:
        return
    while True:
        for addr in addresses:
            try:
                data = fetch_json(f"{MEMPOOL_API}/address/{addr}/txs", timeout=10)
                if not isinstance(data, list):
                    continue
                for tx in data:
                    txid = tx.get("txid") or ""
                    if not txid:
                        continue
                    seen = _DONATION_WATCH_LAST_TX.setdefault(addr, set())
                    if txid in seen:
                        continue
                    seen.add(txid)
                    # Cap in-memory dedup sets — DB dedup (txid UNIQUE-check in
                    # _record_donation) is the real guard; this is just a
                    # short-circuit to avoid re-polling the same recent txs.
                    if len(seen) > 1000:
                        _DONATION_WATCH_LAST_TX[addr] = set(list(seen)[-1000:])
                    # Incoming value: sum of vout to this address (round to
                    # avoid float BTC→sats drift of ±1 sat)
                    got = 0
                    for vout in tx.get("vout") or []:
                        if (vout.get("scriptpubkey_address") or "") == addr:
                            got += int(round((vout.get("value") or 0) * 1e8))
                    if got <= 0:
                        continue
                    # Dust-spam guard: tiny spam txs never become 'donations'
                    if got < _DONATION_MIN_SATS:
                        log.info("[donation watch] skipped dust tx %s (%.0f sats < %d)", txid[:12], got, _DONATION_MIN_SATS)
                        continue
                    # method: 'btc' for the SUPPORT_BTC address, else 'hashpower'
                    method = "btc"
                    for m in _SUPPORT_CONFIG.get("methods", []):
                        if m.get("address") == addr and m.get("id") == "hashpower":
                            method = "hashpower"
                            break
                    _record_donation(method=method, amount_sat=got, txid=txid,
                                     note=f"on-chain to {addr[:10]}…", source="onchain")
            except Exception as e:
                log.warning("[donation watch] %s: %s", addr[:10], e)
        time.sleep(_DONATION_WATCH_INTERVAL)


# ── Initialize Axe Fleet registry (after get_db/init_db are defined) ──
_axe_registry = DeviceRegistry(get_db)
# ensure_tables() applies the schema migrations the app's init_db() does not
# (agent_managed column + axe_agent_commands queue — SaaS agent model). Must
# run here or fleet writes crash on a fresh DB.
_axe_registry.ensure_tables()
_init_axe_routes(_axe_registry)

# ── Fleet snapshot cache: write-through + boot seed ──────────────────────
# The /api/snapshot fleet block is assembled from axe_telemetry_cache, which
# used to be fed ONLY by the server-side poll — a poll that SKIPS
# agent-managed devices (the cloud can't reach the user's LAN). Result:
# every agent push landed in the database but never reached the dashboard
# (empty fleet → "miners not found" + "telemetry missing"). Fix at the
# single choke point: save_telemetry() is the ONLY writer of axe_telemetry,
# so wrapping it here makes EVERY push (agent, server poll, manual) feed the
# cache — it can no longer diverge from the database.

def _cache_axe_telemetry(device_id: str, telemetry, status: str = "") -> None:
    """Write a normalized entry into the snapshot cache. Carries exactly
    what the UI/serving needs: device_id (tenant scoping), status, and a
    `hashrate` alias (the sidebar sums d.hashrate). Non-dict telemetry is
    ignored (never cache broken stubs).

    Heartbeat guard (zombie-data fix): a {} payload (agent poll failure) is
    a heartbeat — it must refresh status/ts but must NEVER wipe the last
    real hashrate. Without this, one failed poll zeroed the fleet hashrate
    in the top bar while /health still showed the real value (two truths).
    Mirrors the DB-side trusted-payload filter (_is_trusted_payload)."""
    if not isinstance(telemetry, dict):
        return
    entry = dict(telemetry)
    entry["device_id"] = device_id
    if "hashrate_hs" not in entry:
        # Heartbeat-only push. Keep the last real reading if we have one.
        prev = _shared_state.axe_telemetry_cache.get(device_id)
        if isinstance(prev, dict) and prev.get("hashrate_hs") is not None:
            merged = dict(prev)
            merged["status"] = status or "IDLE"
            merged["ts"] = telemetry.get("ts") or prev.get("ts") or int(time.time())
            _shared_state.axe_telemetry_cache[device_id] = merged
            return
    hr = entry.get("hashrate_hs") or 0
    entry["status"] = status or ("ONLINE" if hr > 0 else "IDLE")
    entry.setdefault("hashrate", entry.get("hashrate_hs"))
    _shared_state.axe_telemetry_cache[device_id] = entry


def _seed_axe_telemetry_cache(registry) -> None:
    """Rebuild the snapshot cache from the last push per device so a server
    restart doesn't blank the fleet until the next push. Mirrors the
    write-through exactly: any dict payload is cached (including {} heartbeats
    — the device still shows with its real status), and the device row's
    status wins over the hashrate-derived one."""
    try:
        # Use the last TRUSTED payload per device (hashrate_hs present), not
        # the last row — the final row before a restart may be a {} heartbeat,
        # which would seed the fleet as IDLE/0 and blank the top bar.
        latest = registry._latest_telemetry_by_device()
        for dev in registry.list_devices():
            tel = latest.get(dev["id"]) or {}
            _cache_axe_telemetry(dev["id"], tel,
                                 status=dev.get("status") or "")
    except Exception as e:
        log.warning("[axe] telemetry cache seed failed: %s", e)


_axe_save_telemetry_orig = _axe_registry.save_telemetry


def _axe_save_telemetry_write_through(device_id, telemetry, tenant_id="default"):
    _axe_save_telemetry_orig(device_id, telemetry, tenant_id=tenant_id)
    try:
        _cache_axe_telemetry(device_id, telemetry)
    except Exception as e:
        log.warning("[axe] telemetry cache write-through failed: %s", e)


_axe_registry.save_telemetry = _axe_save_telemetry_write_through

# ── Auto-seed Axe Fleet with test devices if registry is empty ──
_auto_seed_axe_fleet(_axe_registry)
_seed_axe_telemetry_cache(_axe_registry)

# ── Device Control: import now, but init is deferred until after
#    _record_command is defined (below) so commands can be audited.
from routes.device_control import init_device_control

# ── Initialize Core CYPHER65 device registry ───────────────────────────────
# Uses the same SQLite file (WAL mode enabled above) but a separate `devices`
# table managed by core/registry/device_registry.py.
_core_registry = CoreDeviceRegistry(DB_PATH)
_core_registry.load_from_db()
_auto_seed_core_devices(_core_registry)

# ── Purge leftover test-suite artifacts (devices/rules/alerts) so the
#    dashboard never shows invented data in production. Runs after both
#    seeders so seed-marked demo rows and raw test rows are both removed. ──
_purge_test_devices(_axe_registry, _core_registry)

# ── GC old tombstones (soft-deleted devices older than 30 days) so the
#    removed_at zombie-guard never grows the DB forever. ──
_axe_registry.gc_tombstones(max_age_days=30)

# ── In-memory command history store ──────────────────────────────────────────
# Stores executed commands per device for lightweight audit logging.
# Each entry: { "device_id": str, "command": str, "parameters": dict,
#              "timestamp": int, "result": dict }
_command_history: Dict[str, List[Dict[str, Any]]] = {}

# ── Session Manager (multi-user support) ──────────────────────────────────────
_session_manager = SessionManager()
_session_workers: dict[str, UserPollingWorker] = {}  # session_id → worker

# ── Module-level SafetyEngine ────────────────────────────────────────────────
# Shared across requests so restart cooldowns and other safety state persist.
_safety_engine = SafetyEngine()

# ── Milestone 9: Alert & Automation engines ──────────────────────────────────
from core.alerts.alert_engine import AlertEngine
from core.alerts.automation_engine import AutomationEngine
from services.push_notifier import notify_alert, send_webhook_for_alert


_alert_engine = None
_automation_engine = None


def _webhook_dispatch(alert):
    """Webhook callback for AlertEngine — reads settings and dispatches to
    Discord/Telegram via the shared severity-thresholded notifier.

    Signature matches the AlertEngine.webhook_callback contract:
        callback(alert: Alert) -> bool

    Tenant-aware: alerts carrying a tenant_id resolve THAT tenant's webhook
    (so a per-tenant AlertEngine dispatches to the right URL); alerts with
    no tenant (operator's core-device engine) resolve the operator's global
    settings — the legacy behavior.
    """
    from services.settings import load_settings
    try:
        tid = getattr(alert, "tenant_id", "") or ""
        s = load_settings(tid)
        return send_webhook_for_alert(
            url=(s.get("webhook_url") or "").strip(),
            severity=alert.severity,
            category=alert.category,
            message=alert.message,
            ts=alert.ts,
            worker=WORKER_NAME,
            address=BTC_ADDRESS,
            min_severity=s.get("webhook_min_severity", "WARN"),
        )
    except Exception as e:
        log.warning("[webhook] dispatch error: %s", e)
        return False


def _init_alert_engines():
    """Initialize alert/automation engines after all helper functions are defined."""
    global _alert_engine, _automation_engine
    if _alert_engine is None:
        _alert_engine = AlertEngine(DB_PATH, push_callback=notify_alert,
                                     webhook_callback=_webhook_dispatch)
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
# Serializes the TTL-check-then-fetch so the 5-min warmup thread and a
# concurrent /api/hashrate-market request can't both pass the TTL check and
# double-fetch (duplicate provider load + duplicate history rows).
_HASHRATE_MARKET_FETCH_LOCK = threading.Lock()
# Background warm-up: refresh the cache every 5 min so the LEASE (lender)
# profitability block always has a real market rate, even when no client
# ever opens the Hash Market panel (see _hashrate_market_warmup_loop).
_HASHRATE_MARKET_WARMUP_INTERVAL_S = int(os.environ.get("HASHRATE_MARKET_WARMUP_INTERVAL", 300))


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

    # ── Fase 4 · B3: structured audit — every command attempt (including
    #    blocked ones) is recorded so the operator can trace who/what ran
    #    which command on which device. Best-effort: never raises.
    try:
        from services.tenant import log_audit, get_tenant_id
        log_audit(
            get_tenant_id(),
            "device.command",
            target=device_id,
            details={
                "command": command,
                "parameters": parameters or {},
                "success": bool(result.get("success")),
                "error": result.get("error", ""),
            },
        )
    except Exception:
        pass


# ── Wire Device Control to the CORE registry + safety + command history ──────
# Uses _core_registry (NOT the Axe Fleet registry) so the
# /api/devices/<device_id>/command endpoints operate on the same devices as
# the rest of the core module. record_command audits every attempt (including
# blocked ones) so the command history / timeline stay complete.
init_device_control(_core_registry, _safety_engine, record_command=_record_command)

# ── Initialize engines now that all callbacks are defined ────────────────────
try:
    _init_alert_engines()
except Exception as e:
    log.warning("[alert_automation] failed to initialize engines: %s", e)

# Fase 6: inject the boot-initialized automation engine + LIVE core registry
# into snapshot_enrichment so /api/snapshot's auto_pilot preview evaluates
# against the same in-memory telemetry the poll loop uses (a fresh DB reload
# would lose current_telemetry and rules would never match). Same setter
# pattern as routes/alerts_routes._set_get_db.
try:
    from services.snapshot_enrichment import set_auto_pilot_deps as _set_ap_deps
    _set_ap_deps(_automation_engine, _core_registry)
except Exception as e:
    log.warning("[auto-pilot] dep injection failed: %s", e)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  State cache — single source of truth
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# poll_once() writes to latest_snapshot; Flask blueprints read
# services.state.latest_snapshot. We ensure both refer to the SAME dict
# by explicitly pointing _shared_state.latest_snapshot at our dict.
latest_snapshot = {
    "ts": 0,
    "btc_address": BTC_ADDRESS,
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
        "stale": False,
    },
    "btc_price": {"usd": None, "brl": None, "eur": None, "gbp": None,
                  "jpy": None, "krw": None, "cny": None, "stale": False},
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
BTC_PRICE_CACHE_TTL = 600  # 10 minutos (CoinGecko free tier: 10-50 req/min)
btc_price_cache = {"ts": 0, "data": None}  # último timestamp e dados cacheados
_btc_consec_failures = 0  # contagem de falhas consecutivas para fallback
_btc_last_fetch_ts = 0     # throttle: último instante em que tentamos fetch
# ── Stale-while-revalidate (Honest Telemetry) ───────────────────────────────
# Últimos valores REAIS conhecidos — nunca inventados. Quando uma fonte externa
# falha, o snapshot serve estes valores marcados como stale (selo "dados em
# cache") — o frontend nunca vê um número falso nem um "—" evitável.
_last_valid_network = {"difficulty": None, "hashrate": None}


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

    # exchange credentials (kept in sync with services/settings.py)
    "mrr_api_key": "",             # MiningRigRentals API key (Settings → MRR)
    "mrr_api_secret": "",          # MiningRigRentals API secret (Settings → MRR)
    "braiins_api_key": "",         # Braiins Hashpower owner token (Settings → Braiins)
}

_settings_cache = None

# ── Persisted wallet address ──
# When user changes address via /api/set-address, we save it here and
# in the settings DB so it survives a server restart.
def _load_persisted_address() -> bool:
    """Restore a previously-saved wallet address from the settings table.
    Returns True if a valid persisted address (>= 10 chars) was restored,
    False otherwise (no address, too short, or DB error)."""
    global BTC_ADDRESS, WORKER_NAME
    restored = False
    conn = None
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT value FROM settings WHERE key='_wallet_address'")
        r = c.fetchone()
        if r and r["value"] and len(r["value"]) >= 10:
            BTC_ADDRESS = r["value"]
            restored = True
        c.execute("SELECT value FROM settings WHERE key='_wallet_worker'")
        r = c.fetchone()
        if r and r["value"]:
            WORKER_NAME = r["value"]
    except Exception:
        restored = False
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
    return restored

_load_persisted_address()


def _log_wallet_change(old_address: str, old_worker: str) -> bool:
    """Persist the outgoing address/worker to history before it's replaced.
    Returns True on success, False on failure (never raises — a history
    write must never block the actual wallet switch)."""
    if not old_address:
        return False  # nothing to log on first-ever connect
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute(
            "INSERT INTO wallet_address_history(address, worker, connected_at) VALUES (?,?,?)",
            (old_address, old_worker, int(time.time())),
        )
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        log.warning("[_log_wallet_change] failed to persist history: %s", e)
        return False


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
            "expected_time_seconds": expected_secs,  # alias for frontend consistency
            "expected_time_human": _human_secs_long(expected_secs) if expected_secs else "—",
            "blocks_per_year": blocks_per_year,
            "chance_per_share_label": (
                f"1 in {int(round(net_diff / best_diff_raw)):,}"
                if best_diff_raw else "—"
            ),
            "chance_per_share_pct": (best_diff_raw / net_diff) if best_diff_raw and net_diff else 0.0,  # decimal for frontend
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

        # QUANTUM-LOCK assessment (composite confidence score). The pure math
        # lives in services/proximity.py (_compute_quantum_lock) — we reuse it
        # here so production /api/snapshot + /api/proximity expose the payload
        # that the front-end Quantum-Lock panel renders.
        try:
            _sch = list(timeline_state.get("share_calc_history") or [])
            _session_shares = timeline_state.get("session_share_count", 0) or 0
            out["quantum_lock"] = _compute_quantum_lock(
                pct_cur, best_diff_raw, net_diff,
                _sch, _session_shares, trend_1h_pct, worker_hps,
            )
        except Exception as e:
            log.warning("[compute_proximity quantum_lock] error: %s", e)

        # Share rate (shares/hour) — sliding 10-min window over the session's
        # share_calc_history timestamps. Drives the Share Rate KPI + timeline
        # rate badge. Mirrors the E1 derive approach (never raises).
        try:
            _cutoff_ts = int(time.time()) - 600
            _recent = [e for e in (timeline_state.get("share_calc_history") or []) if (e.get("ts") or 0) >= _cutoff_ts]
            out["share_rate_hourly"] = round(len(_recent) * 6.0, 2)  # 600s window x6 = per-hour
        except Exception:
            out["share_rate_hourly"] = 0.0

        return out
    except Exception as e:
        log.warning("[compute_proximity] error: %s", e)
        return {**out, "insufficient_data": True, "error": str(e)}


_human_int = human_int
_human_secs_long = human_secs_long
# isfinite_v imported from helpers.py


# Restore all-time best-difficulty from settings on module load.
_restore_all_time_best_diff()


def _clear_wallet_scoped_history():
    """Delete per-wallet chart history so a wallet switch never mixes data.

    The chart tables (proximity_history, snapshots, share_timeline) have NO
    wallet column — rows accumulate across wallets. On a wallet change the
    previous wallet's real data would otherwise appear in the new session's
    hashrate / best-diff / pool charts as if it belonged to the new wallet.
    Clearing them keeps the honest-telemetry premise: the charts refill from
    the next poll with data for the CURRENT wallet only.

    The in-memory share_calc_history (cum_p / share_dist charts) is already
    cleared by _reset_session_state(); this covers the DB-backed charts.
    """
    tables = ("proximity_history", "snapshots", "share_timeline")
    for t in tables:
        try:
            conn = get_db()
            c = conn.cursor()
            c.execute(f"DELETE FROM {t}")
            conn.commit()
            conn.close()
        except Exception as e:
            log.warning("[set-address] could not clear %s: %s", t, e)


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
        "btc_address": BTC_ADDRESS,
        "worker": None,
        "user_aggregate": None,
        "pool": None,
        "account": None,
        "lightning": None,
        "leaderboard_entry": None,
        "leaderboard_total": 0,
        "highest_diffs": [],
        "network": {"height": None, "difficulty": None, "hashrate": None},
        "btc_price": {"usd": None, "brl": None, "eur": None, "gbp": None,
                      "jpy": None, "krw": None, "cny": None},
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
    if hasattr(_do_poll, '_alert_seen'):
        _do_poll._alert_seen.clear()
    if hasattr(_do_poll, '_worker_was_present'):
        _do_poll._worker_was_present = False

    # Reset proximity sample throttle
    _last_proximity_sample_ts = 0

    # Reset persist failure counter
    persist_consec_failures = 0

    # Clear BTC price cache so next poll fetches fresh
    global btc_price_cache, _shared_state
    btc_price_cache = {"ts": 0, "data": None}

    # Clear last_known_prices (opportunity engine market data)
    _shared_state.last_known_prices["braiins"] = None
    _shared_state.last_known_prices["mrr"] = None
    _shared_state.last_known_prices["nicehash"] = None
    _shared_state.last_known_prices["parasite"] = None
    # Reset stale-while-revalidate caches so a fresh session never inherits
    # another wallet's "last valid" network/price values.
    _last_valid_network["difficulty"] = None
    _last_valid_network["hashrate"] = None

    # Reset _shared_state.test_opportunities (mock bypass)
    _shared_state.test_opportunities = None

    # ── Re-sync state alias after in-place mutations ──
    _shared_state.latest_snapshot = latest_snapshot


# ═══════════════════════════════════════════════════════════════════════════
#  MULTI-USER SESSION ROUTES
# ═══════════════════════════════════════════════════════════════════════════

@app.route("/api/connect-wallet", methods=["POST"])
@require_tenant
@role_required("member")
def api_connect_wallet(tenant_id: str = ""):
    """Create a new session and start per-user polling.

    Body (JSON):
      - address (str): BTC address to monitor
      - worker (str, optional): worker name

    Returns:
      - success, session_id, snapshot (first poll result)
    """
    global _session_manager, _session_workers

    data = request.get_json(silent=True) or {}
    address = (data.get("address") or "").strip()
    worker_name = (data.get("worker") or "").strip()

    # Validate
    if not address:
        return jsonify({"success": False, "error": "address is required"}), 400
    if not (address.startswith("bc1") or address.startswith("1")):
        return jsonify({"success": False, "error": "invalid address prefix"}), 400
    if len(address) < 26 or len(address) > 64:
        return jsonify({"success": False, "error": "invalid address length"}), 400

    # Create session
    session = _session_manager.create_session(address, worker_name)
    sid = session.session_id

    # Start polling worker for this session — tenant-scoped, so alerts and
    # webhooks generated by this worker use the USER'S own settings/keys.
    worker = UserPollingWorker(sid, _session_manager, address, worker_name,
                               tenant_id=tenant_id)
    _session_workers[sid] = worker
    worker.start()

    # Do an immediate first poll so the snapshot is ready
    snapshot = worker.poll_now()

    log.info("[connect] session %s wallet=%s", sid[:8], address[:10])

    return jsonify({
        "success": True,
        "session_id": sid,
        "snapshot": snapshot,
        "has_wallet": True,
    })


@app.route("/api/session-snapshot", methods=["GET"])
def api_session_snapshot():
    """Return the snapshot for the current session.
    Session ID is passed as query param 'session_id'.
    """
    global _session_manager

    sid = request.args.get("session_id") or \
          request.headers.get("X-Session-Id") or ""

    if not sid:
        return jsonify({"error": "session_id required", "has_wallet": False}), 400

    session = _session_manager.get_session(sid)
    if not session:
        return jsonify({"error": "session not found or expired",
                        "has_wallet": False}), 404

    # If session has no wallet yet, return empty state
    if not session.has_wallet:
        return jsonify({"has_wallet": False, "session_id": sid})

    snapshot = _session_manager.get_snapshot(sid) or {}

    return jsonify({
        "has_wallet": True,
        "session_id": sid,
        "btc_address": session.btc_address,
        "snapshot": snapshot,
    })


@app.route("/api/disconnect", methods=["POST"])
def api_disconnect():
    """Stop polling and destroy the session."""
    global _session_manager, _session_workers

    data = request.get_json(silent=True) or {}
    sid = data.get("session_id") or \
          request.headers.get("X-Session-Id") or ""

    if not sid:
        return jsonify({"success": False, "error": "session_id required"}), 400

    # Stop the worker thread
    worker = _session_workers.pop(sid, None)
    if worker:
        worker.stop()
        log.info("[disconnect] stopped worker for %s", sid[:8])

    # Destroy session
    existed = _session_manager.destroy_session(sid)

    return jsonify({"success": True, "session_id": sid, "existed": existed})


@app.route("/api/session-status", methods=["GET"])
def api_session_status():
    """Check if a session is valid."""
    sid = request.args.get("session_id") or \
          request.headers.get("X-Session-Id") or ""
    if not sid:
        return jsonify({"valid": False})
    session = _session_manager.get_session(sid)
    if not session:
        return jsonify({"valid": False})
    return jsonify({
        "valid": True,
        "session_id": sid,
        "has_wallet": session.has_wallet,
        "btc_address": session.btc_address,
        "created_at": session.created_at,
        "last_activity": session.last_activity,
    })


@app.route("/api/admin/sessions", methods=["GET"])
def api_admin_sessions():
    """List all active sessions (debug/admin)."""
    sessions = _session_manager.get_all_sessions()
    return jsonify({
        "count": len(sessions),
        "sessions": [s.to_dict() for s in sessions],
    })


# parse_diff_to_float, fmt_diff, fmt_hashrate, fmt_uptime, fmt_age
# are imported from helpers.py


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Polling worker
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
_poll_lock = threading.Lock()


def _coerce_uptime(v):
    """Coerce worker uptime to an int, or None for non-numeric junk.

    The pool API sometimes returns the literal string 'N/A' for uptime (seen
    in production rows). Storing it in the INTEGER column made fmt.uptime()
    render NaN in the UI instead of a clean em-dash — honest telemetry: a
    non-numeric value means no data."""
    if v is None:
        return None
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None
_poll_start_ts = 0.0  # when the current poll began (watchdog); 0 = idle
_POLL_HANG_TIMEOUT = 60.0  # seconds — a poll must never hold the lock this long


def poll_once():
    """Wrapper with concurrency guard — lock prevents concurrent polls between
    the forced poll (from set-address) and the scheduled poll_loop().

    Data-audit watchdog (2026-08-02): if _do_poll hangs (e.g. a blocking
    fetch that ignores its timeout), the lock would be held forever and every
    later poll would silently skip at debug level — freezing the snapshots
    table while the rest of the app keeps writing (the exact failure mode
    observed in the audit: snapshots stale ~50 min while market/maintenance
    writers kept flowing). If a poll holds the lock past _POLL_HANG_TIMEOUT,
    replace the lock so polling resumes and surface a CRIT alert instead of a
    silent skip.
    """
    global _poll_lock, _poll_start_ts
    now = time.time()

    # Watchdog: a poll that has held the lock past the hang timeout is stuck.
    # Replace the lock so the next poll can run (the hung thread still holds
    # the old lock object, which is now orphaned — it will release a lock
    # nobody references).
    if _poll_start_ts and (now - _poll_start_ts) > _POLL_HANG_TIMEOUT:
        log.error("[poll] poll hung for %.0fs — replacing lock so snapshots resume",
                  now - _poll_start_ts)
        memory_critical_alerts.append(_make_memory_alert(
            int(now), "CRIT", "poll_hang",
            f"Polling stalled {now - _poll_start_ts:.0f}s — replaced lock to resume telemetry.",
        ))
        _poll_lock = threading.Lock()
        _poll_start_ts = 0.0

    if not _poll_lock.acquire(blocking=False):
        # Only warn once a poll has been running suspiciously long; normal
        # overlap (poll still finishing while the next tick fires) stays debug.
        if _poll_start_ts and (now - _poll_start_ts) > _POLL_HANG_TIMEOUT * 0.5:
            log.warning("[poll] skipped — previous poll running %.0fs (slow/hung?)",
                        now - _poll_start_ts)
        else:
            log.debug("[poll] skipped — another poll is already running")
        return
    _poll_start_ts = now
    try:
        _do_poll()
    finally:
        _poll_lock.release()
        _poll_start_ts = 0.0


def _poll_axe_fleet(ts: int) -> None:
    """Server-side poll of non-agent-managed fleet devices.

    SaaS agent model: devices reported by the user's LOCAL agent
    (agent_managed=1) are polled from the home LAN by that agent — the cloud
    cannot reach them, so they are skipped here (never marked OFFLINE by a
    poll that cannot connect). Extracted from _do_poll for unit testing.
    """
    try:
        if _axe_registry:
            devices = _axe_registry.list_devices()
            for device in devices:
                if int(device.get("agent_managed", 0) or 0):
                    continue
                did = device["id"]
                last = _shared_state.axe_last_poll_ts.get(did, 0)
                if ts - last >= _shared_state.AXE_POLL_INTERVAL:
                    _shared_state.axe_last_poll_ts[did] = ts
                    tel = _axe_registry.poll_device(did)
                    if tel:
                        _cache_axe_telemetry(did, tel)
    except Exception as e:
        log.warning("[axe poll] error: %s", e)


def _do_poll():
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
        ("leaderboard", f"{PARASITE_API}/leaderboard?limit=100",                                        10),
        ("highest",     f"{PARASITE_API}/highest-diff?type=user-diffs&address={BTC_ADDRESS}&limit=30",       10),
        ("net_height",  f"{MEMPOOL_API}/blocks/tip/height",                                     6),
        # net_diff removed from main fetch — mempool.space /v1/difficulty deprecated Oct 2024.
        # blockchain.info /q/getdifficulty handles this via bc_specs below.
        ("mempool_fee", f"{MEMPOOL_API}/v1/fees/recommended",                                   6),
    ]
    # BTC price: só adiciona ao fan-out se passou >= 60s desde a última tentativa
    global _btc_consec_failures, _btc_last_fetch_ts
    _btc_now = int(time.time())
    if _btc_now - _btc_last_fetch_ts >= 60:
        # Multi-source BTC price: Binance (fast, no key, 1200 req/min) +
        # CoinGecko (comprehensive, multi-currency). Binance only gives USD;
        # CoinGecko covers BRL/EUR/GBP/JPY/KRW/CNY. Both fetch in parallel.
        fetch_specs.append(("btc", "https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd,brl,eur,gbp,jpy,krw,cny", 6))
        fetch_specs.append(("btc_binance", "https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT", 4))
        # Binance BRL pair for direct BRL conversion
        fetch_specs.append(("btc_binance_brl", "https://api.binance.com/api/v3/ticker/price?symbol=BTCBRL", 4))
    else:
        # Cache recente — pula fetch, usa o cache existente
        fetch_specs.append(("btc", None, 0))

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
            if url is not None  # skip throttled entries (e.g. BTC price when cache is fresh)
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
    # Stale-while-revalidate da rede: se a fonte falhou, serve o último valor
    # REAL conhecido marcado como stale (nunca inventa difficulty/hashrate).
    network_stale = False
    if current_difficulty is not None and net_hashrate is not None:
        _last_valid_network["difficulty"] = current_difficulty
        _last_valid_network["hashrate"] = net_hashrate
    else:
        if _last_valid_network["difficulty"] is not None:
            log.warning("[network] source failed — serving last real values (stale)")
            current_difficulty = _last_valid_network["difficulty"]
            net_hashrate = _last_valid_network["hashrate"]
            network_stale = True

    # BTC price (CoinGecko) — throttle + cache + fallback
    _now = int(time.time())
    # _btc_consec_failures, _btc_last_fetch_ts declared global above (fetch_specs section)
    btc_quote = results["btc"]

    # Throttle: só tenta fetch se passou >= 60s desde a última tentativa
    _fetch_allowed = (_now - _btc_last_fetch_ts) >= 60
    if _fetch_allowed:
        _btc_last_fetch_ts = _now
        # Se a API retornou dados, atualiza o cache e zera contagem de falhas
        if isinstance(btc_quote, dict) and btc_quote.get("bitcoin"):
            btc_price_cache["data"] = btc_quote
            btc_price_cache["ts"] = _now
            _btc_consec_failures = 0
        else:
            # Falhou — incrementa contador
            _btc_consec_failures += 1
    else:
        # Throttle ativo — usa cache mesmo que um pouco velho
        if _now - btc_price_cache["ts"] < BTC_PRICE_CACHE_TTL and btc_price_cache["data"]:
            btc_quote = btc_price_cache["data"]
        else:
            btc_quote = None

    # Stale-while-revalidate (Honest Telemetry): se a API falhou, NUNCA
    # inventar preço — serve o último valor REAL do cache marcado como stale
    # para o frontend exibir o selo "dados em cache". Sem cache real → sem
    # preço (honesto), nunca um número falso.
    btc_price_stale = False
    if not (isinstance(btc_quote, dict) and btc_quote.get("bitcoin")):
        _cached = btc_price_cache.get("data")
        if isinstance(_cached, dict) and _cached.get("bitcoin"):
            log.warning("[btc] %d consecutive failures — serving last real cached price (stale)", _btc_consec_failures)
            btc_quote = _cached
            btc_price_stale = True
        else:
            btc_quote = None

    # Merge Binance (fast, USD-only) with CoinGecko (multi-currency)
    binance_raw = results.get("btc_binance")
    binance_brl_raw = results.get("btc_binance_brl")
    binance_usd = None
    binance_brl = None
    if isinstance(binance_raw, dict) and binance_raw.get("price"):
        try: binance_usd = float(binance_raw["price"])
        except (ValueError, TypeError): pass
    if isinstance(binance_brl_raw, dict) and binance_brl_raw.get("price"):
        try: binance_brl = float(binance_brl_raw["price"])
        except (ValueError, TypeError): pass

    btc_usd = (btc_quote or {}).get("bitcoin", {}).get("usd") if isinstance(btc_quote, dict) else None
    btc_brl = (btc_quote or {}).get("bitcoin", {}).get("brl") if isinstance(btc_quote, dict) else None
    # Prefer Binance real-time USD/BRL when available (faster, lower latency)
    if binance_usd is not None and binance_usd > 0:
        btc_usd = binance_usd
    if binance_brl is not None and binance_brl > 0:
        btc_brl = binance_brl
    btc_eur = (btc_quote or {}).get("bitcoin", {}).get("eur") if isinstance(btc_quote, dict) else None
    btc_gbp = (btc_quote or {}).get("bitcoin", {}).get("gbp") if isinstance(btc_quote, dict) else None
    btc_jpy = (btc_quote or {}).get("bitcoin", {}).get("jpy") if isinstance(btc_quote, dict) else None
    btc_krw = (btc_quote or {}).get("bitcoin", {}).get("krw") if isinstance(btc_quote, dict) else None
    btc_cny = (btc_quote or {}).get("bitcoin", {}).get("cny") if isinstance(btc_quote, dict) else None

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
            raw_name = str(w.get("name", ""))
            raw_id = str(w.get("id", ""))
            clean_name = _names.sanitize(raw_name)
            clean_id = _names.sanitize(raw_id)
            entry = {
                "id": clean_id,
                "name": clean_name,
                "hashrate": w.get("hashrate"),
                "bestDifficulty": w.get("bestDifficulty", ""),
                "lastSubmission": w.get("lastSubmission"),
                "uptime": w.get("uptime"),
                "is_primary": _names.normalize(raw_name) == _names.normalize(WORKER_NAME)
                              or _names.normalize(raw_id) == _names.normalize(WORKER_NAME),
            }
            all_workers.append(entry)
            if entry["is_primary"]:
                worker = w
                worker_index = idx

    # ── Fallback: if no primary worker matched WORKER_NAME, pick best by hashrate ──
    # Workers with hashrate 0 still carry useful data (bestDifficulty, lastSubmission,
    # uptime). When all workers have zero hashrate, pick the first worker instead of
    # leaving the snapshot blank — otherwise the dashboard shows \"OFFLINE\" even for
    # wallets with mining history.
    if worker is None and all_workers and user and isinstance(user.get("workerData"), list):
        best_idx = 0
        best_hr = 0
        for i, entry in enumerate(all_workers):
            hr = float(entry.get("hashrate") or 0)
            if hr > best_hr:
                best_hr = hr
                best_idx = i
        if best_hr > 0:
            if best_idx < len(user["workerData"]):
                all_workers[best_idx]["is_primary"] = True
                worker = user["workerData"][best_idx]
                worker_index = best_idx
                log.info("[primary] auto-selected worker %s with HR %s (best of %d)",
                         all_workers[best_idx]["name"], best_hr, len(all_workers))
        elif len(all_workers) > 0 and len(user["workerData"]) > 0:
            # All workers idle (hr=0) — pick the first so the dashboard still
            # surfaces bestDifficulty / lastSubmission / uptime. Only when a
            # workerData entry exists to pair with (worker stays None otherwise).
            all_workers[0]["is_primary"] = True
            worker = user["workerData"][0]
            worker_index = 0
            log.info("[primary] all workers idle — selected %s as primary (hr=0, %d total)",
                     all_workers[0]["name"], len(all_workers))

    # ── Dedup workers with case-insensitive merging ──
    # Workers with the same normalized name (e.g. CYPHERORDIFUTURE vs cypherordifuture)
    # are merged — keep the entry with the highest hashrate (active beats dead).
    _orig_worker_count = len(all_workers)
    if all_workers:
        seen = {}  # normalized_key -> index in deduped list
        deduped = []
        for entry in all_workers:
            key = _names.dedup_key(entry.get("name", "") or "")
            if not key:
                # Empty name means no dedup possible; keep verbatim
                deduped.append(entry)
                continue
            if key in seen:
                existing_idx = seen[key]
                existing = deduped[existing_idx]
                incoming_hr = entry.get("hashrate") or 0
                existing_hr = existing.get("hashrate") or 0
                if incoming_hr > existing_hr:
                    deduped[existing_idx] = entry
                    log.debug("[dedup] merged %s → %s (HR %s > %s)",
                              existing.get("name"), entry.get("name"),
                              incoming_hr, existing_hr)
            else:
                seen[key] = len(deduped)
                deduped.append(entry)
        all_workers = deduped
        log.info("[dedup] %d workers after dedup (was %d)", len(all_workers), _orig_worker_count)

    # ── Leaderboard lookup ──
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

    # P0-5 audit: the pool account API often omits diff/loyalty/combined
    # ranks, but the leaderboard (same poll) carries REAL values for the
    # wallet. Enrich the account with them so the Wallet panel shows the
    # actual ranks instead of '—' (or a client-side estimate). Values only
    # when the account itself lacks them — leaderboard is authoritative.
    # Pure helper (helpers.enrich_account_ranks) — unit-tested. It returns a
    # COPY, so re-read meta AFTER the call (the copy may carry a backfilled
    # block_count from the leaderboard — the pre-call `meta` above would be
    # stale and leak into latest_snapshot["account_meta"]).
    if isinstance(account, dict) and leaderboard_entry:
        account = enrich_account_ranks(account, leaderboard_entry)
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

    # ━━ FENIX E1 (P1): derive worker hashrate when the pool reports 0 ━━
    # The public API sometimes reports worker hashrate as 0 even while the
    # worker is actively submitting shares. When that happens we fall back to
    # the per-share instantaneous hashrate math (share_calc_history) or the
    # pool workSinceLastBlock delta, and write the derived value into the
    # worker dict so the snapshot row, /api/snapshot worker payload, KPI cards
    # and proximity meter all show a real number instead of 0/—.
    if worker:
        _reported_hr = float(worker.get("hashrate") or 0)
        if _reported_hr <= 0:
            _prev_ts = latest_snapshot.get("ts") if isinstance(latest_snapshot, dict) else 0
            _elapsed_s = (ts - _prev_ts) if _prev_ts else float(POLL_INTERVAL)
            _derived_hr, _hr_source = derive_worker_hashrate(
                share_calc_history=timeline_state.get("share_calc_history") or [],
                prev_pool=prev_pool,
                pool=pool,
                elapsed_s=_elapsed_s,
            )
            if _derived_hr > 0:
                worker["hashrate"] = _derived_hr
                worker["hashrate_source"] = _hr_source
                worker["hashrate_derived"] = True
                # mirror into the fleet panel's primary worker entry — match by
                # the is_primary flag (robust to dedup index shifts)
                for _entry in all_workers:
                    if _entry.get("is_primary"):
                        _entry["hashrate"] = _derived_hr
                        _entry["hashrate_source"] = _hr_source
                        break
                log.info("[poll] worker %s hashrate derived from %s: %s H/s (pool reported 0)",
                         worker.get("name") or "?", _hr_source, fmt_hashrate(_derived_hr))

    # ━━ Persist snapshot ━━
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute(
            """INSERT OR IGNORE INTO snapshots
            (ts, worker_hashrate, worker_best_diff, worker_last_submit, worker_uptime, worker_status,
             pool_hashrate, pool_workers, pool_users, pool_highest_diff, pool_last_block_height,
             pool_last_block_time, pool_work_since_last_block,
             account_total_diff, account_block_count, account_highest_block,
             leaderboard_rank, leaderboard_diff_rank, leaderboard_loyalty_rank, leaderboard_combined_score,
             network_height, network_difficulty, network_hashrate,
             btc_usd, btc_brl, btc_jpy, btc_krw, btc_cny)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                ts,
                worker.get("hashrate") if worker else None,
                worker.get("bestDifficulty") if worker else None,
                worker.get("lastSubmission") if worker else None,
                _coerce_uptime(worker.get("uptime")) if worker else None,
                "online" if worker else "missing",
                pool.get("hashrate") if pool else None,
                pool.get("workers") if pool else None,
                pool.get("users") if pool else None,
                pool.get("highestDifficulty") if pool else None,
                # The pool API exposes the last block HEIGHT under the
                # lastBlockTime field (the old lastBlockHeight key no longer
                # exists — it was 100% NULL). Fall back to lastBlockTime so
                # pool_last_block_height finally gets real data.
                (pool.get("lastBlockHeight") or pool.get("lastBlockTime")) if pool else None,
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
                btc_jpy,
                btc_krw,
                btc_cny,
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
        _do_poll._alert_seen = set()  # set of (category, identifier) seen across restarts
    alert_seen = _do_poll._alert_seen

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
        _do_poll._worker_was_present = True
        # Clear the offline sig so it can fire again next time
        if ("worker_offline", "1") in alert_seen:
            alert_seen.discard(("worker_offline", "1"))
    else:
        _do_poll._worker_was_present = getattr(_do_poll, '_worker_was_present', False)

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
        _do_poll._alert_seen = set(list(alert_seen)[-500:])

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
        btc_prices = {"USD": btc_usd, "BRL": btc_brl, "EUR": btc_eur, "GBP": btc_gbp,
                      "JPY": btc_jpy, "KRW": btc_krw, "CNY": btc_cny}

        profitability["cost_mode"] = cost_mode
        profitability["cost_model_configured"] = cost_mode != "none"
        profitability["cost_per_kwh"] = coerce_float(s.get('power_kwh_usd'), 0.10)
        profitability["cost_label"] = (
            f"${coerce_float(s.get('rental_usd_per_th_day'),0.0):.2f}/d rental"
            if cost_mode == "rental" else
            f"${coerce_float(s.get('power_kwh_usd'),0.10):.4f}/kWh power ({coerce_float(s.get('power_watts'),0.0):.0f}W)"
            if cost_mode == "power" else "no cost model"
        )
        profitability["active_currency_val"] = s.get("active_currency", "USD")
        profitability["pool_fee_pct"] = pool_fee_pct
        profitability["orphan_pct"] = orphan_pct

        # ── Lender market rate (Scenario D) — emitted WITHOUT a worker ──
        # The rental market price only needs the warm hashrate-market cache
        # (plus btc_usd for the USD conversion) — NOT the user's hashrate.
        # Computed outside the cur_hr gate so the LEASE panel always shows the
        # real market rate even on a worker-less / cold-address server.
        lender_market_rate_btc = None
        try:
            _offers = (_HASHRATE_MARKET_CACHE.get("offers") or [])
            _real = [o for o in _offers
                     if not getattr(o, "estimated", False)
                     and (getattr(o, "price_per_th_day", 0) or 0) > 0]
            _pool = _real or [o for o in _offers if (getattr(o, "price_per_th_day", 0) or 0) > 0]
            if _pool:
                lender_market_rate_btc = min(o.price_per_th_day for o in _pool)
        except Exception:
            lender_market_rate_btc = None
        # P0-5 audit (hashmarket honesty guard): a SHA-256 rental rate is
        # physically bounded — real market asks run ~10-50k sats/TH/d
        # (1e-4..5e-4 BTC). A "best price" landing outside 1e-8..1e-2 is a
        # unit-conversion bug (sats vs BTC, TH vs PH), and feeding it into
        # lender_net_usd_per_day produced absurd lease P&L (measured live:
        # $55,411/d for an 87 TH rig — 100× reality). Clamp + log instead of
        # surfacing fake money.
        if lender_market_rate_btc is not None:
            _r = float(lender_market_rate_btc)
            if _r < 1e-8 or _r > 1e-2:
                log.warning("[profitability] implausible lender market rate %.6g BTC/TH/d — ignoring (unit bug?)", _r)
                lender_market_rate_btc = None
        if not lender_market_rate_btc and btc_usd:
            cfg_rate_usd = coerce_float(s.get("rental_usd_per_th_day"), 0.0)
            if cfg_rate_usd > 0:
                lender_market_rate_btc = cfg_rate_usd / btc_usd
        profitability["lender_market_rate_btc_per_th_day"] = (
            round(lender_market_rate_btc, 12) if lender_market_rate_btc else None
        )
        # The USD market rate needs a BTC price. The live fetch may be briefly
        # unavailable (provider 429, throttle) — fall back to the cached quote
        # or the same hardcoded fallback the price fetch itself uses, so the
        # LEASE panel shows the real market rate instead of '—' on a cold box.
        _btc_conv = btc_usd
        if not _btc_conv:
            _cached_quote = (btc_price_cache.get("data") or {}).get("bitcoin") or {}
            _btc_conv = _cached_quote.get("usd")  # stale-while-revalidate: último real, nunca mock
        profitability["lender_market_rate_usd_per_th_day"] = (
            round(lender_market_rate_btc * _btc_conv, 4)
            if lender_market_rate_btc else None
        )

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
            # Solo variance is extreme: share_of_network is the per-BLOCK chance, and
            # with ~144 blocks/day, P(≥1 block in N days) = 1 - (1 - share)^(144·N).
            # Math extracted to helpers.compute_solo_probabilities (pure, unit-tested).
            solo_net_btc_per_day = gross_btc_per_day * (1 - orphan_pct / 100.0)  # no pool fee
            _solo = compute_solo_probabilities(share_of_network, blocks_per_day)
            solo_p_day = _solo["solo_p_day"]
            solo_p_year = _solo["solo_p_year"]
            solo_p_5year = _solo["solo_p_5year"]
            solo_expected_blocks_per_year = _solo["solo_expected_blocks_per_year"]
            solo_expected_time_to_block_days = _solo["solo_expected_time_to_block_days"]

            # ── Rental/power cost + break-even (pure, unit-tested) ──
            # Math extracted to helpers.compute_pool_rental_break_even so the
            # profitability formulas have a single source of truth.
            ths = cur_hr / 1e12
            _be = compute_pool_rental_break_even(
                ths=ths,
                pool_net_btc_per_day=pool_net_btc_per_day,
                btc_usd=btc_usd or 0,
                cost_mode=cost_mode,
                rental_usd_per_th_day=coerce_float(s.get("rental_usd_per_th_day"), 0.0),
                power_watts=coerce_float(s.get("power_watts"), 0.0),
                power_kwh_usd=coerce_float(s.get("power_kwh_usd"), 0.0),
            )
            rental_cost_per_day = _be["rental_cost_per_day"]
            power_cost_per_day = _be["power_cost_per_day"]
            cost_per_day = _be["cost_per_day"]

            def _fiat_convert(btc_val):
                return {
                    cur: (round(btc_val * px, 4) if px else None)
                    for cur, px in btc_prices.items()
                }

            # ── Lender (Scenario D): rent OUT your own hashrate vs mining ──
            # Revenue = ths × market rental rate (BTC/TH/day); the locador keeps
            # paying electricity. lender_market_rate_btc is computed above,
            # outside the cur_hr gate (market price does not need a worker).
            # Math extracted to helpers.compute_lender_profitability (pure).
            lender_watts = coerce_float(s.get("power_watts"), 0.0)
            lender_kwh_usd = coerce_float(s.get("power_kwh_usd"), 0.10)
            lender_power_cost = (lender_watts / 1000.0) * 24.0 * lender_kwh_usd if lender_watts > 0 else 0.0
            _lender = compute_lender_profitability(
                ths=ths,
                market_btc_per_th_day=lender_market_rate_btc or 0,
                power_cost_usd_per_day=lender_power_cost,
                pool_net_btc_per_day=pool_net_btc_per_day,
                btc_usd=btc_usd or 0,
            )
            _lender_net_btc = _lender.get("lender_net_btc_per_day")
            profitability.update({
                "lender_net_btc_per_day": _lender["lender_net_btc_per_day"],
                "lender_net_usd_per_day": _lender["lender_net_usd_per_day"],
                "lender_revenue_btc_per_day": _lender["lender_revenue_btc_per_day"],
                "lender_power_cost_usd_per_day": _lender["lender_power_cost_usd_per_day"],
                "lender_mine_net_usd_per_day": _lender["lender_mine_net_usd_per_day"],
                "lender_vs_mining_usd_per_day": _lender["lender_vs_mining_usd_per_day"],
                "lender_recommendation": _lender["lender_recommendation"],
                "lender_breakeven_btc_per_th_day": _lender["lender_breakeven_btc_per_th_day"],
                "lender_breakeven_usd_per_th_day": _lender["lender_breakeven_usd_per_th_day"],
                "lender_fiat_per_day": (
                    _fiat_convert(_lender_net_btc) if _lender_net_btc is not None else {}
                ),
                "lender_fiat_per_month": (
                    _fiat_convert(_lender_net_btc * 30) if _lender_net_btc is not None else {}
                ),
            })

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
                "pool_net_usd_per_day": round((pool_net_btc_per_day * btc_usd) - cost_per_day, 4) if btc_usd else None,
                "pool_net_usd_per_month": round(((pool_net_btc_per_day * btc_usd) - cost_per_day) * 30, 2) if btc_usd else None,
                # Solo mode
                "net_btc_per_day_solo": round(solo_net_btc_per_day, 8),
                "fiat_per_day_solo": _fiat_convert(solo_net_btc_per_day),
                "fiat_per_month_solo": _fiat_convert(solo_net_btc_per_day * 30),
                "solo_p_day_pct": round(solo_p_day * 100, 8),
                "solo_p_year_pct": round(solo_p_year * 100, 4),
                "solo_p_5year_pct": round(solo_p_5year * 100, 2),
                "solo_expected_blocks_per_year": round(solo_expected_blocks_per_year, 4),
                "solo_expected_time_to_block_days": round(solo_expected_time_to_block_days, 1) if solo_expected_time_to_block_days else None,
                # Rental mode (cost subtracted)
                "net_btc_per_day_rental": round(pool_net_btc_per_day - (cost_per_day / (btc_usd or 1)), 8) if btc_usd else None,
                "fiat_per_day_rental": _fiat_convert(max(0, pool_net_btc_per_day - (cost_per_day / (btc_usd or 1)))) if btc_usd else None,
                "fiat_per_month_rental": _fiat_convert(max(0, pool_net_btc_per_day - (cost_per_day / (btc_usd or 1))) * 30) if btc_usd else None,
                "rental_net_btc_per_day": round(pool_net_btc_per_day, 8),  # gross pool BTC
                "rental_net_usd_per_day": round((pool_net_btc_per_day * (btc_usd or 0)) - cost_per_day, 4),
                "rental_net_usd_per_month": round(((pool_net_btc_per_day * (btc_usd or 0)) - cost_per_day) * 30, 2),
                # Cost info (cost_model_configured, cost_per_kwh, cost_label
                # already set above; cost_per_day_usd is dynamic)
                "cost_per_day_usd": round(cost_per_day, 4),
                # Break-even: rental rate at which pool_net = rental_cost
                # (computed by helpers.compute_pool_rental_break_even)
                "break_even_rental_usd_per_th_day": _be["break_even_rental_usd_per_th_day"],
                # General break-even cost per TH/day (always computed)
                "breakeven_cost_per_th_day": _be["breakeven_cost_per_th_day"],
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
            # P0-2: unified solo vs pool vs lease Decision Matrix (pure agg).
            # Aggregates the per-mode numbers already computed above into one
            # capital-allocation comparison for the market module panel.
            profitability["decision_matrix"] = build_decision_matrix(
                pool_net_usd_per_day=profitability.get("pool_net_usd_per_day"),
                solo_expected_time_days=profitability.get("solo_expected_time_to_block_days"),
                solo_p_year_pct=profitability.get("solo_p_year_pct"),
                lender_net_usd_per_day=profitability.get("lender_net_usd_per_day"),
                lender_recommendation=profitability.get("lender_recommendation"),
                breakeven_cost_per_th_day=profitability.get("breakeven_cost_per_th_day"),
            )
        else:
            profitability["unavailable_reason"] = "no hashrate or network hashrate"
    except Exception as e:
        import traceback as _tb
        log.warning("[profitability] compute error: %s\n%s", e, _tb.format_exc())

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
    # Poll each registered device at AXE_POLL_INTERVAL frequency. IMPORTANT
    # (SaaS agent model): agent_managed devices are polled by the user's
    # LOCAL agent (the cloud cannot reach the home LAN) — the server poll
    # must NEVER touch them, or it would mark them OFFLINE on every tick.
    _poll_axe_fleet(ts)

    # ── Milestone 9: Alert & Automation engines ───────────────────────────────
    try:
        # Build a list of core Device objects from the registry
        _core_devices = _core_registry.list_devices()
        _alerts_generated = _alert_engine.evaluate(_core_devices, pool=pool)
        if _alerts_generated:
            _alert_engine.persist(_alerts_generated)
            _alert_engine.dispatch_push(_alerts_generated)
            _alert_engine.dispatch_webhook(_alerts_generated)
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
        "btc_address": BTC_ADDRESS,
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
            "stale": network_stale,
        },
        "btc_price": {"usd": btc_usd, "brl": btc_brl, "eur": btc_eur, "gbp": btc_gbp,
                      "jpy": btc_jpy, "krw": btc_krw, "cny": btc_cny, "stale": btc_price_stale, "_source": "binance+coingecko", "_age_s": max(0, int(time.time()) - btc_price_cache.get("ts", 0))},
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
}    # ── Sync shared state after each poll ──
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
            # Broadcast updated snapshot to SSE clients
            try:
                _broadcast_snapshot(latest_snapshot)
            except Exception:
                pass
            n += 1
            if n >= CLEANUP_EVERY_N_POLLS:
                purge_old()
                n = 0
        except Exception as e:
            log.error("[poll_loop] error: %s", e)
        time.sleep(POLL_INTERVAL)


def _auto_backup_loop():
    """C4 // periodic SQLite online-backup worker (daemon).

    Snapshots the DB via the crash-safe online backup API every
    AUTO_BACKUP_INTERVAL seconds (default 3600; 0 disables the worker).
    Never auto-restores over a live writer — corruption is reported at boot
    instead, pointing at the newest backup.
    """
    _db_backup.backup_loop()


def _start_background_threads():
    """Start every background worker for the server process.

    Consolidates boot: the initial poll + poll_loop thread (previously
    started at module level, which also fired on plain test-suite imports)
    and the 5-min Hash Market warmup thread all start here, called from the
    __main__ block before app.run(). Test-suite imports of app.py no longer
    spawn ANY network thread.

    C4: also runs a boot-time SQLite integrity check (warning-only) and,
    when enabled (AUTO_BACKUP_INTERVAL != 0), starts the automatic backup
    worker.

    Note: deliberately __main__-gated; a WSGI/gunicorn deployment must call
    this explicitly (the project convention is `python app.py`).
    """
    # C4 // boot-time integrity check — detect the recurring index
    # corruption (idx_maintenance_records_ts / idx_audit_logs_tenant_ts)
    # early and point at the newest backup. Warning-only: restoring over a
    # possibly-live writer (Docker/Colima volume mount) would be destructive.
    boot_db_ok = True
    try:
        if not _db_backup.integrity_ok():
            boot_db_ok = False
            latest = _db_backup.latest_backup()
            log.critical(
                "[boot] SQLite integrity_check FAILED on %s — DB is corrupt. "
                "Newest backup: %s. Stop the container, restore, restart.",
                DB_PATH, latest or "NONE (no backups yet)",
            )
    except Exception as e:
        boot_db_ok = False
        log.warning("[boot] integrity check error: %s", e)
    # Kick off a poll on startup, then run the loop in background. Wrapped
    # so a cold-start provider outage can't take down boot — the loop retries
    # on its next cycle anyway.
    try:
        poll_once()
    except Exception as e:
        log.error("[boot] initial poll failed: %s", e)
    threading.Thread(target=poll_loop, daemon=True).start()
    # Warm the Hash Market cache in the background (5 min loop) so the
    # LEASE profitability mode always has real offers to compare against,
    # regardless of whether the Hash Market panel was ever opened.
    threading.Thread(target=_hashrate_market_warmup_loop, daemon=True).start()
    # Watch on-chain donation addresses (mempool.space) so the operator is
    # alerted as soon as someone sends BTC/hashpower donations.
    try:
        threading.Thread(target=_donation_watcher_loop, daemon=True).start()
    except Exception as e:
        log.warning("[boot] donation watcher failed to start: %s", e)
    # C4 // automatic SQLite backup (online backup API — safe with the live
    # Docker/Colima writer that caused the recurring index corruption).
    # Skipped when the boot integrity check failed: snapshotting a corrupt
    # DB would fill retention slots with garbage an operator might mistake
    # for a good restore point.
    if boot_db_ok and _db_backup.backup_enabled():
        threading.Thread(target=_auto_backup_loop, daemon=True).start()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Routes
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
@app.route("/")
def index():
    from config import is_cloud_deploy
    return render_template(
        "dashboard.html",
        worker=WORKER_NAME,
        address=BTC_ADDRESS,
        poll_interval=POLL_INTERVAL,
        # SaaS fleet topology: the JS needs to know the dashboard is cloud-
        # hosted (Render) so the wizard leads users to the LOCAL AGENT instead
        # of scan/IP-add, which are physically impossible from the cloud.
        is_cloud=is_cloud_deploy(),
    )


# ── Docs: guia do usuário renderizado dentro do app ────────────────────────
# Serves docs/AGENT_SETUP_GUIDE.md (single source of truth — o mesmo arquivo
# do repo) convertido para HTML com a lib `markdown`. Página pública, como o
# index; o guia não expõe dados sensíveis do tenant.
_GUIDE_MD_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "docs", "AGENT_SETUP_GUIDE.md"
)


@app.route("/docs/agent")
def docs_agent_guide():
    """Render the agent setup guide inside the dashboard (public)."""
    try:
        with open(_GUIDE_MD_PATH, encoding="utf-8") as f:
            raw = f.read()
    except OSError:
        abort(404)
    html = _md.markdown(raw, extensions=["tables", "fenced_code", "nl2br"])
    return render_template("agent_guide.html", guide_html=Markup(html))


# Fase 6 · PR2: /api/snapshot now served by dashboard_bp.
# _compute_block_hunt is shared with the blueprint via
# services/snapshot_enrichment — the thin delegating wrapper at the END of
# this file keeps `api_block_hunt` working with the single implementation.


@app.route("/api/pool-stats")
def api_pool_stats():
    """Return the latest pool statistics snapshot."""
    return jsonify(latest_snapshot.get("pool") or {})


# Moved to routes/dashboard_routes.py (dashboard_bp) — Fase 6 · PR2
# /api/halving → dashboard_bp
# /api/mempool_fees → dashboard_bp
# /api/profitability → dashboard_bp
# /api/network_share → dashboard_bp
# /api/milestones → dashboard_bp
# /api/workers → dashboard_bp
# /api/monte_carlo → dashboard_bp
# /api/proximity → dashboard_bp
# /api/alerts → routes/alerts_routes.py (alerts_bp — owns this route since
#   Fase 4 · B2 tenant scoping; the old app.py copy was shadowed dead code).




# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Settings API (GET/POST) — lives in routes/settings_routes.py (settings_bp,
#  registered at import time). It is the single source of truth: same auth
#  (require_tenant / role_required), plus the PRO webhook gate and the
#  services/settings.settings_label() descriptions.
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Subset endpoints (Halving / Mempool / Profitability / Network-share)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━




@app.route("/api/license-status")
def api_license_status():
    """Return current PRO licensing state (open/free/pro) + feature matrix.

    Drives the topbar PRO badge and the frontend lock overlays. Always 200
    — this endpoint reports state, it never gates."""
    return jsonify(_license_status())


@app.route("/api/upgrade/checkout", methods=["POST"])
def api_upgrade_checkout():
    """R1 revenue: create a hosted Lemon Squeezy checkout for PRO.

    Off-by-default — returns 503 until the operator sets LEMON_SQUEEZY_*.
    """
    if not _payments.payments_configured():
        return jsonify({
            "error": "Payments are not configured on this server",
            "code": "PAYMENTS_NOT_CONFIGURED",
            "upgrade": {"plan": "PRO", "price_usd_month": 9},
        }), 503
    body = request.get_json(silent=True) or {}
    plan = (body.get("plan") or "pro").strip()
    email = (body.get("email") or "").strip()
    url = _payments.create_checkout(plan=plan, email=email)
    if not url:
        return jsonify({
            "error": "Could not create a checkout — check LEMON_SQUEEZY_* env vars",
            "code": "CHECKOUT_FAILED",
        }), 502
    return jsonify({"checkout_url": url, "plan": plan})


@app.route("/api/payments/webhook", methods=["POST"])
def api_payments_webhook():
    """Lemon Squeezy webhook: verify x-signature, fulfill order_created.

    Server-to-server — no auth decorator; trust comes from the HMAC-SHA256
    signature over the raw body (x-signature header)."""
    if not _payments.payments_configured():
        return jsonify({"error": "not configured"}), 400
    raw = request.get_data()
    sig = (request.headers.get("X-Signature") or "").strip()
    if not _payments.verify_webhook_signature(raw, sig):
        return jsonify({"error": "invalid signature"}), 403
    payload = request.get_json(silent=True) or {}
    key = _payments.handle_webhook(payload)
    if key:
        return jsonify({"ok": True, "license_key": key}), 200
    # Unhandled event (subscription_created etc.) — acknowledge, no-op.
    return jsonify({"ok": True, "handled": False}), 200


@app.route("/api/admin/licenses", methods=["POST"])
def api_admin_issue_license():
    """Manual PRO key issuance (community/beta keys).

    Gated to localhost requests or a valid X-API-Key matching the operator's
    API_KEY env var — never exposed to the public checkout path."""
    remote = request.remote_addr or ""
    local = remote in ("127.0.0.1", "::1", "localhost")
    operator_key = os.environ.get("API_KEY") or ""
    sent = (request.headers.get("X-API-Key") or "").strip()
    if not local and not (operator_key and hmac.compare_digest(sent, operator_key)):
        return jsonify({"error": "admin access required"}), 403
    body = request.get_json(silent=True) or {}
    months = body.get("months")
    if months is not None:
        try:
            months = int(months)
        except (TypeError, ValueError):
            months = None
    key = _licensing_issue(
        plan=(body.get("plan") or "pro").strip(),
        email=(body.get("email") or "").strip(),
        source=(body.get("source") or "admin").strip(),
        months=months,
    )
    return jsonify({"ok": True, "license_key": key}), 200


# Moved to routes/dashboard_routes.py (dashboard_bp) — Fase 6 · PR2:
# /api/network_share, /api/milestones, /api/workers, /api/monte_carlo,
# /api/proximity (same bodies, same pro_required gates, same responses).


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


# Fase 6 · PR2: _compute_block_hunt moved to services/snapshot_enrichment.py
# (single source of truth shared with dashboard_bp). The thin wrapper at the
# END of this file keeps `api_block_hunt` below working unchanged.


@app.route("/api/block-hunt", methods=["GET"])
def api_block_hunt():
    """Return the Block Hunt panel: network stats, user stats, probabilities
    and network comparison metrics.

    Probabilities are computed from the latest worker hashrate vs network
    hashrate using the Poisson model in services/probability.
    Same payload is injected into /api/snapshot under `block_hunt`.
    """
    payload = _compute_block_hunt(latest_snapshot)
    return jsonify({"success": True, "ts": int(time.time()), **payload})


@app.route("/api/best-diff-history", methods=["GET"])
def api_best_diff_history():
    """Return the global best-difficulty history."""
    limit = request.args.get("limit", 100, type=int)
    return jsonify({
        "success": True,
        "records": _get_best_diff_history(device_id=None, limit=limit),
    })


@app.route("/api/devices/<device_id>/best-diff-history", methods=["GET"])
@require_tenant
def api_device_best_diff_history(device_id: str, tenant_id: str = ""):
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


@app.route("/api/tax/export")
@require_tenant
@role_required("viewer")
def api_tax_export(tenant_id: str = ""):
    """Export a tax-report CSV (Japan 雑所得 / Korea 2027 gains / generic).

    Honest-telemetry export: rows come ONLY from recorded data — mined block
    events (highest_diff_events.is_mine=1) valued at the BTC price recorded in
    snapshots for the requested currency, plus a daily BTC price ledger so any
    other received coins can be valued at receipt time. No invented figures.

    Query params:
      - currency (default JPY): JPY | KRW | CNY | USD | BRL | EUR | GBP
      - year (optional int): restrict to that calendar year (UTC)

    Returns a CSV attachment: event rows + daily price ledger.
    """
    currency = (request.args.get("currency") or "JPY").upper()
    col = {
        "JPY": "btc_jpy", "KRW": "btc_krw", "CNY": "btc_cny",
        "USD": "btc_usd", "BRL": "btc_brl", "EUR": "btc_eur", "GBP": "btc_gbp",
    }.get(currency)
    if col is None:
        return jsonify({"error": f"unsupported currency {currency}"}), 400
    year = request.args.get("year", type=int)
    since = int(time.time()) - 10 ** 10
    if year:
        since = int(datetime(year, 1, 1, tzinfo=timezone.utc).timestamp())

    try:
        s = load_settings()
        block_reward = coerce_float(s.get("btc_block_reward"), 3.125)
    except Exception:
        block_reward = 3.125

    conn = get_db()
    c = conn.cursor()
    # ── Mined block events (the actual taxable income events) ──
    c.execute(
        "SELECT ts, block_height, difficulty, block_timestamp FROM highest_diff_events "
        "WHERE is_mine=1 AND ts >= ? ORDER BY ts ASC",
        (since,),
    )
    blocks = [dict(r) for r in c.fetchall()]
    # ── Daily BTC price ledger (last snapshot per UTC day) ──
    # Correlated subquery so `price` is the value at MAX(ts) of each day —
    # a bare GROUP BY would return an arbitrary (first) row's price.
    c.execute(
        f"SELECT MAX(s.ts) AS ts, "
        f"(SELECT s2.{col} FROM snapshots s2 WHERE s2.ts/86400 = s.ts/86400 "
        f" ORDER BY s2.ts DESC LIMIT 1) AS price "
        "FROM snapshots s WHERE s.ts >= ? GROUP BY s.ts/86400 ORDER BY s.ts ASC",
        (since,),
    )
    ledger = [dict(r) for r in c.fetchall()]
    conn.close()

    buf = _StringIO()
    writer = _csv.writer(buf)
    writer.writerow(["# CYPHER65 tax export", f"currency={currency}",
                     f"generated_utc={datetime.now(timezone.utc).isoformat(timespec='seconds')}"])
    writer.writerow(["# Mined-block income events (is_mine=1) — value at block time using recorded price"])
    writer.writerow(["type", "ts", "date_utc", "block_height", "difficulty",
                     f"btc_price_{currency}", "reward_btc", f"value_{currency}"])
    for b in blocks:
        # Value the block at the last recorded price at/after block discovery.
        price = None
        try:
            conn2 = get_db()
            c2 = conn2.cursor()
            c2.execute(
                f"SELECT {col} AS price FROM snapshots WHERE ts <= ? ORDER BY ts DESC LIMIT 1",
                (b.get("block_timestamp") or b.get("ts") or 0,),
            )
            row = c2.fetchone()
            price = row["price"] if row else None
            conn2.close()
        except Exception:
            price = None
        bts = b.get("ts") or 0
        value = round(block_reward * price, 2) if price is not None else ""
        writer.writerow(["block_hit", bts,
                         datetime.fromtimestamp(bts, tz=timezone.utc).isoformat(timespec="seconds") if bts else "",
                         b.get("block_height"), b.get("difficulty"),
                         price, block_reward, value])
    writer.writerow(["# Daily BTC price ledger — value any other received coin at receipt time"])
    writer.writerow(["type", "ts", "date_utc", "block_height", "difficulty",
                     f"btc_price_{currency}", "reward_btc", f"value_{currency}"])
    for r in ledger:
        ts = r.get("ts") or 0
        writer.writerow(["price_ledger", ts,
                         datetime.fromtimestamp(ts, tz=timezone.utc).isoformat(timespec="seconds") if ts else "",
                         "", "", r.get("price"), "", ""])

    out = buf.getvalue()
    return app.response_class(
        out,
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename=cypher65_tax_{currency.lower()}.csv"},
    )


# ═══════════════════════════════════════════════════════════════════════════
# CORE DEVICE API
# ═══════════════════════════════════════════════════════════════════════════

# ── Device serialization helpers ─────────────────────────────────────────────
def _enrich_telemetry(telemetry: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Add runtime freshness info to a telemetry snapshot.

    freshness is the number of seconds between the telemetry timestamp and now.
    If the telemetry has no timestamp, freshness is omitted.

    Fase 5: canonical telemetry fields (chip_temp, vr_temp, hashrate 1m/10m/1h,
    pool_status, ...) missing from the snapshot are filled with the explicit
    NOT_AVAILABLE marker so the UI never displays a guessed value.
    """
    if telemetry is None:
        return None
    enriched = dict(telemetry)
    ts = enriched.get("timestamp")
    if ts is not None:
        enriched["freshness"] = max(0, int(time.time()) - int(ts))
    return normalize_telemetry(enriched)


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
@require_tenant
def api_list_devices(tenant_id: str = ""):
    """List all devices registered in the core DeviceRegistry (tenant-scoped).

    Returns:
      devices: list of device dicts (with current_telemetry when available)
      summary: count per status (online, offline, warning, critical)
      total: total number of registered devices
    """
    devices = _core_registry.list_devices(tenant_id=tenant_id)
    summary = _core_registry.count_by_status()
    return jsonify({
        "devices": [_serialize_device(d) for d in devices],
        "summary": summary,
        "total": len(devices),
    })


@app.route("/api/devices/<device_id>", methods=["GET"])
@require_tenant
def api_get_device(device_id: str, tenant_id: str = ""):
    """Return full details for a single device, including telemetry and capabilities."""
    device = _core_registry.get_device(device_id, tenant_id=tenant_id)
    if not device:
        return jsonify({"error": "device not found", "success": False}), 404
    return jsonify({
        "success": True,
        "device": _serialize_device(device, include_telemetry=True),
    })


@app.route("/api/devices/<device_id>/refresh", methods=["POST"])
@require_tenant
def api_refresh_device(device_id: str, tenant_id: str = ""):
    """Refresh a single device: fetch telemetry, update status, persist.

    Steps:
      1. Look up the device in the core registry (tenant-scoped).
      2. Select the correct adapter based on device model.
      3. Call get_telemetry() on the adapter.
      4. Determine device status from the telemetry.
      5. Save telemetry in the device object and update the registry.
    """
    device = _core_registry.get_device(device_id, tenant_id=tenant_id)
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
@require_tenant
def api_fleet_summary(tenant_id: str = ""):
    """Return a high-level health summary for the tenant's device fleet."""
    devices = _core_registry.list_devices(tenant_id=tenant_id)
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
@require_tenant
def api_device_command(device_id: str, tenant_id: str = ""):
    """Execute a command on a device after safety validation (tenant-scoped).

    Body (JSON):
      - command (str, required): command to execute (e.g. "restart", "identify")
      - parameters (dict, optional): command-specific parameters

    Flow:
      1. Find the device in the registry (tenant-scoped).
      2. Instantiate the correct adapter.
      3. Check that the adapter supports the command.
      4. Run SafetyEngine.validate_command().
      5. Execute via the adapter.
      6. Record the command in the in-memory history.
      7. Update the device status when applicable.
    """
    device = _core_registry.get_device(device_id, tenant_id=tenant_id)
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
@require_tenant
def api_device_command_history(device_id: str, tenant_id: str = ""):
    """Return the command execution history for a single device.

    Returns the last 100 entries, newest first.
    """
    device = _core_registry.get_device(device_id, tenant_id=tenant_id)
    if not device:
        return jsonify({"error": "device not found", "success": False}), 404

    history = _command_history.get(device_id, [])
    return jsonify({
        "success": True,
        "device_id": device_id,
        "commands": history[::-1],  # newest first
    })


@app.route("/api/devices/<device_id>/diagnostics", methods=["GET"])
@require_tenant
def api_device_diagnostics(device_id: str, tenant_id: str = ""):
    """Return operational diagnostics for a single device (tenant-scoped).

    Analyzes the device's current telemetry and metadata and returns a list
    of detected issues (empty list when everything looks healthy).
    """
    device = _core_registry.get_device(device_id, tenant_id=tenant_id)
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
@require_tenant
def api_device_maintenance(device_id: str, tenant_id: str = ""):
    """Record or list maintenance events for a single device (tenant-scoped).

    POST body (JSON):
      - type (str, required): e.g. firmware_update, cleaning, hardware_check
      - notes (str, optional)
      - performed_by (str, optional)
    """
    device = _core_registry.get_device(device_id, tenant_id=tenant_id)
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
@require_tenant
def api_device_timeline(device_id: str, tenant_id: str = ""):
    """Return a combined timeline of events for a single device (tenant-scoped).

    Events include: executed commands, maintenance records, status changes
    and current diagnostics. The result is limited to the 50 most recent
    events and sorted newest first.
    """
    device = _core_registry.get_device(device_id, tenant_id=tenant_id)
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


@app.route("/api/v1/status")
def api_v1_status():
    """Health of external integrations (blockchain, exchange, pool).

    Returns per-source status: 'online' (fresh real data), 'stale' (serving
    last real cached value — provider briefly down, see stale-while-revalidate)
    or 'offline' (no real data yet). Consumed by the operator to distinguish
    "our bug" from "provider down", and by the frontend cache badge.
    """
    now = int(time.time())
    net = latest_snapshot.get("network") or {}
    btc = latest_snapshot.get("btc_price") or {}
    worker = latest_snapshot.get("worker") or {}
    pool = latest_snapshot.get("pool") or {}

    def _status(has_value: bool, stale: bool) -> str:
        if has_value:
            return "stale" if stale else "online"
        return "offline"

    return jsonify(
        {
            "ok": True,
            "ts": now,
            "last_poll_ts": latest_snapshot.get("ts"),
            "integrations": {
                "blockchain_api": {
                    "status": _status(net.get("difficulty") is not None, bool(net.get("stale"))),
                    "difficulty": net.get("difficulty"),
                    "hashrate": net.get("hashrate"),
                },
                "exchange_api": {
                    "status": _status(btc.get("usd") is not None, bool(btc.get("stale"))),
                    "btc_usd": btc.get("usd"),
                    "btc_brl": btc.get("brl"),
                },
                "pool_stratum": {
                    "status": "online" if (worker or pool) else "offline",
                    "worker_hashrate": worker.get("hashrate") if worker else None,
                    "pool_workers": pool.get("workers") if pool else None,
                },
            },
        }
    )


@app.route("/api/tailscale")
@require_tenant
def api_tailscale(tenant_id: str = ""):
    """Report local Tailscale connection status for the remote-access panel.
    Uses services.tailscale_adapter.get_local_status() (CLI + tailnet API).
    Returns tailscale_installed/connected/ip/hostname/magic_dns_name etc."""
    try:
        from services.tailscale_adapter import get_local_status
        return jsonify(get_local_status())
    except Exception as e:
        log.warning("[tailscale] endpoint error: %s", e)
        return jsonify({"tailscale_installed": False, "connected": False, "error": str(e)})



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

    Also updates _shared_state.last_known_prices so that build_highlights
    (called by /api/snapshot) can serve market_data without extra HTTP calls.

    The TTL-check-then-fetch is serialized with _HASHRATE_MARKET_FETCH_LOCK so
    the background warm-up thread and HTTP requests never double-fetch.
    """
    now = int(time.time())
    cache = _HASHRATE_MARKET_CACHE
    ttl = _HASHRATE_MARKET_CACHE_TTL if cache["offers"] else _HASHRATE_MARKET_EMPTY_CACHE_TTL
    if (now - cache["ts"] < ttl) and cache["offers"] is not None:
        _sync_market_prices_to_state(cache["offers"])
        return cache["offers"]

    with _HASHRATE_MARKET_FETCH_LOCK:
        # Re-check under the lock: another thread may have just refreshed it.
        now = int(time.time())
        ttl = _HASHRATE_MARKET_CACHE_TTL if cache["offers"] else _HASHRATE_MARKET_EMPTY_CACHE_TTL
        if (now - cache["ts"] < ttl) and cache["offers"] is not None:
            _sync_market_prices_to_state(cache["offers"])
            return cache["offers"]

        # Real network hashrate (H/s) feeds the Parasite EV model + metrics
        network_hashrate = (latest_snapshot.get("network") or {}).get("hashrate")
        offers = _fetch_all_offers(network_hashrate=network_hashrate)
        if offers:
            try:
                conn = get_db()
                _persist_market_history(conn, offers)
                conn.close()
            except Exception as e:
                log.warning("[hashrate_market] history persistence failed: %s", e)
            cache["ts"] = now
            cache["offers"] = offers
            _sync_market_prices_to_state(offers)
        else:
            cache["ts"] = now
            cache["offers"] = []

    return offers


def _hashrate_market_health() -> dict:
    """Expose warmup/cache health for /api/hashrate-market and the snapshot's
    market_data: when the in-memory cache was last filled and how many offers
    it holds. Lets operators confirm the 5-min background warm-up is actually
    running (last_fetch_ts keeps advancing, stale stays False).

    Notes:
      - offers_count reflects the RAW fetch cache (_HASHRATE_MARKET_CACHE);
        it may differ from market_data.provider_count, which counts scored
        highlights that can drop stale/unpriced offers.
      - stale means "older than the cache TTL" (60s success / 15s empty),
        NOT "warmup broken": with the 300s warmup interval the cache is
        legitimately stale for ~240s of every cycle. Watch age_s instead —
        it should stay below ~interval + TTL.
    """
    cache = _HASHRATE_MARKET_CACHE
    now = int(time.time())
    ts = cache.get("ts") or 0
    offers = cache.get("offers")
    count = len(offers) if offers else 0
    ttl = _HASHRATE_MARKET_CACHE_TTL if offers else _HASHRATE_MARKET_EMPTY_CACHE_TTL
    age = (now - ts) if ts else None
    return {
        "last_fetch_ts": ts,
        "offers_count": count,
        "age_s": age,
        "ttl_s": ttl,
        "stale": age is not None and age > ttl,
        "warmup_interval_s": _HASHRATE_MARKET_WARMUP_INTERVAL_S,
    }


def _hashrate_market_warmup_cycle():
    """One warm-up cycle: refresh the market cache via the shared getter.

    Reuses _get_hashrate_market_offers() so the cache write, history
    persistence and _shared_state.last_known_prices sync all stay in one
    place. Never raises — errors are logged and swallowed so a provider
    outage can't kill the background thread.
    """
    try:
        _get_hashrate_market_offers()
    except Exception as e:
        log.warning("[hashrate_market] warmup cycle error: %s", e)


def _hashrate_market_warmup_loop():
    """Slow background loop (default 5 min) that keeps the Hash Market cache
    warm so the LEASE (lender) profitability block in _do_poll() always has a
    real market rate to compare against, instead of falling back to the
    user-configured rental rate or 'NEEDS DATA'.

    Started by _start_background_threads() from the __main__ block (NOT at
    import time) so no network thread spawns on plain test-suite imports;
    only the real server process (python app.py) boots the workers.
    """
    while True:
        _hashrate_market_warmup_cycle()
        time.sleep(_HASHRATE_MARKET_WARMUP_INTERVAL_S)


def _sync_market_prices_to_state(offers: list):
    """Update _shared_state.last_known_prices with current offer data.
    This feeds build_highlights() so that /api/snapshot can serve market_data
    without extra HTTP calls."""
    for offer in offers:
        provider = getattr(offer, "provider", None) or offer.get("provider")
        if not provider:
            continue
        price = getattr(offer, "price_per_th_day", None)
        if price is None:
            price = offer.get("price_per_th_day")
        if price is None:
            continue
        price_ph = price * PH_TO_TH  # 1 PH = 1000 TH
        # offer may be a NormalizedOffer (attr access) or a dict (in tests)
        source = getattr(offer, "source", "")
        if not source and isinstance(offer, dict):
            source = offer.get("source") or ""
        estimated = bool(getattr(offer, "estimated", False))
        if isinstance(offer, dict):
            estimated = bool(offer.get("estimated", False))
        _shared_state.last_known_prices[provider] = {
            "price": price_ph,
            "ts": int(time.time()),
            "label": provider.capitalize(),
            "source": source or provider,
            "estimated": estimated,
        }


@app.route("/api/hashrate-market")
def api_hashrate_market():
    """Return normalized hashrate rental offers from supported providers.

    Persists the fetched snapshot to hashrate_market_history so the
    /api/hashrate-market/history endpoint can serve historical data.
    """
    offers = _get_hashrate_market_offers()
    network_hashrate = (latest_snapshot.get("network") or {}).get("hashrate")
    btc_usd = (latest_snapshot.get("network") or {}).get("btc_usd")
    scored = [_score_offer(offer, network_hashrate) for offer in offers]
    scored.sort(key=_market_offer_sort_key)

    # HashratePulse Enterprise institutional view
    from services.hashrate_market import compute_institutional_view
    inst_view = compute_institutional_view(offers, network_hashrate, btc_usd)

    return jsonify({
        "success": True,
        "ts": int(time.time()),
        "offers": scored,
        "health": _hashrate_market_health(),
        "institutional": inst_view,
    })


@app.route("/api/hashrate-market/institutional")
def api_hashrate_market_institutional():
    """Return the HashratePulse Enterprise institutional view only.

    Lighter payload for clients that only need the ranked venue table,
    executive snapshot, and risk surface — without the full offer detail.
    """
    offers = _get_hashrate_market_offers()
    network_hashrate = (latest_snapshot.get("network") or {}).get("hashrate")
    btc_usd = (latest_snapshot.get("network") or {}).get("btc_usd")
    from services.hashrate_market import compute_institutional_view
    return jsonify({"success": True, **compute_institutional_view(offers, network_hashrate, btc_usd)})


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


@app.route("/api/market/history")
def api_market_history():
    """Return raw time-series market data for the price history chart.

    Returns all historical market records as a flat array with timestamps
    and prices in both TH/s and PH/s units. Optimized for frontend charting.

    Query params:
        limit: max rows per provider (default 200)
        hours: lookback window in hours (default 168 = 7 days)
    """
    try:
        limit = int(request.args.get("limit", 200))
        hours = int(request.args.get("hours", 168))
    except (TypeError, ValueError):
        limit = 200
        hours = 168

    try:
        conn = get_db()
        c = conn.cursor()
        cutoff = int(time.time()) - hours * 3600
        c.execute(
            """SELECT ts, provider, hashrate, price_per_th_day, score
               FROM hashrate_market_history
               WHERE ts >= ?
               ORDER BY ts ASC""",
            (cutoff,),
        )
        rows = c.fetchall()
        conn.close()

        records = []
        for r in rows:
            ppth = r["price_per_th_day"]
            records.append({
                "ts": r["ts"],
                "provider": r["provider"],
                "hashrate": r["hashrate"],
                "price_btc_per_th_day": ppth,
                "price_btc_per_ph_day": (ppth * 1000) if ppth is not None else None,
                "score": r["score"],
            })

        return jsonify({
            "success": True,
            "records": records,
            "count": len(records),
            "updated_at": int(time.time()),
        })
    except Exception as e:
        log.warning("[market/history] error: %s", e)
        return jsonify({"success": False, "error": "failed to fetch history"}), 500


@app.route("/api/market/trend")
def api_market_trend():
    """Return time-series price data aggregated by provider for the 7-day trend chart.
    Returns datasets per provider with timestamps and prices in both TH/s and PH/s units.
    """
    try:
        conn = get_db()
        c = conn.cursor()
        cutoff = int(time.time()) - 7 * 86400  # last 7 days
        c.execute(
            """SELECT ts, provider, price_per_th_day, score
               FROM hashrate_market_history
               WHERE ts >= ?
               ORDER BY ts ASC""",
            (cutoff,),
        )
        rows = c.fetchall()
        conn.close()

        from collections import defaultdict
        by_provider = defaultdict(list)
        for r in rows:
            ppth = r["price_per_th_day"]
            by_provider[r["provider"]].append({
                "ts": r["ts"],
                "price_btc_per_th_day": ppth,
                "price_btc_per_ph_day": (ppth * 1000) if ppth is not None else None,
                "score": r["score"],
            })

        # Honest display: only CURRENTLY offered providers go into the
        # buying-comparison chart. A provider without any quote for >48h
        # (e.g. kissmyhash, removed from the pipeline but with legacy rows
        # still inside the 7d window) is dropped — its stale line would
        # otherwise inflate the "N providers" badge and mislead the operator.
        active_cutoff = int(time.time()) - 48 * 3600
        by_provider = {
            p: pts for p, pts in by_provider.items()
            if any(x["ts"] >= active_cutoff for x in pts)
        }

        return jsonify({
            "success": True,
            "providers": dict(by_provider),
            "updated_at": int(time.time()),
        })
    except Exception as e:
        log.warning("[market/trend] error: %s", e)
        return jsonify({"success": False, "error": "failed to fetch trend"}), 500


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  RENTALS panel — operator rental performance (MRR rentals + Braiins contracts)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@app.route("/api/rentals")
@require_tenant
@role_required("viewer")
def api_rentals(tenant_id: str = ""):
    """Consolidated rental list for the RENTALS panel (tenant-scoped).

    - MRR: GET /rental (renter + owner, active + history)
    - Braiins: GET /contract (caller-owned, requires BRAIINS_API_KEY)

    Tenant-aware: with 1000+ users each tenant carries ITS OWN Braiins/MRR
    credentials (tenant_settings) — a user only ever sees their own
    contracts and rental history, never the operator's global key.

    Fail-closed: missing credentials yield an explicit needs_auth block so
    the panel never pretends there are zero rentals.
    """
    try:
        mrr_active = _rental_perf.fetch_mrr_rentals(rtype="renter", history=False, limit=50, tenant_id=tenant_id)
        mrr_history = _rental_perf.fetch_mrr_rentals(rtype="renter", history=True, limit=50, tenant_id=tenant_id)
        mrr_owner = _rental_perf.fetch_mrr_rentals(rtype="owner", history=True, limit=50, tenant_id=tenant_id)
        braiins = _rental_perf.fetch_braiins_contracts(tenant_id=tenant_id)
        return jsonify({
            "success": True,
            "updated_at": int(time.time()),
            "mrr": {
                "needs_auth": mrr_active.get("needs_auth", False),
                "active": mrr_active.get("rentals", []),
                "history": mrr_history.get("rentals", []),
                "owner": mrr_owner.get("rentals", []),
                "total_active": mrr_active.get("total") or len(mrr_active.get("rentals", [])),
                "total_history": mrr_history.get("total") or len(mrr_history.get("rentals", [])),
                "total_owner": mrr_owner.get("total") or len(mrr_owner.get("rentals", [])),
                "error": mrr_active.get("error") or mrr_history.get("error"),
            },
            "braiins": {
                "needs_auth": braiins.get("needs_auth", False),
                "contracts": braiins.get("contracts", []),
                "error": braiins.get("error"),
            },
        })
    except Exception as e:
        log.warning("[rentals] list error: %s", e)
        return jsonify({"success": False, "error": "failed to fetch rentals"}), 500


@app.route("/api/rentals/detail", methods=["GET", "POST"])
@require_tenant
@role_required("viewer")
def api_rentals_detail(tenant_id: str = ""):
    """Detail + graph + log for one rental (tenant-scoped).

    Query params (GET):
        provider: mrr (default) | braiins
        id:       rental/contract id

    JSON body (POST, braiins):
        {provider, id, contract: {...}} — the contract's static fields from
        the list payload, so the detail skips re-probing the list endpoints.

    Tenant-aware: the provider credentials resolve from the CALLER's tenant
    (their own Braiins/MRR keys), never the operator's global/env values.
    """
    body = request.get_json(silent=True) or {}
    provider = (body.get("provider") or request.args.get("provider") or "mrr").lower()
    rid = (body.get("id") or request.args.get("id") or "").strip()
    if not rid:
        return jsonify({"success": False, "error": "missing id"}), 400
    try:
        if provider == "braiins":
            contract = body.get("contract")
            result = _rental_perf.fetch_braiins_contract_detail(rid, contract=contract,
                                                                 tenant_id=tenant_id)
            return jsonify({"success": True, "provider": "braiins",
                            "detail": result.get("detail") or {},
                            "graph": result.get("graph") or {},
                            "log": result.get("log") or {},
                            # Analytics: effective cost vs the cheapest live
                            # market price (sats/TH/h) for the perf banner.
                            "market": _rental_perf.fetch_market_reference(),
                            "rig_history": []})
        detail = _rental_perf.fetch_mrr_rental_detail(rid, tenant_id=tenant_id)
        raw = detail.get("detail") or {}
        # Compute the same perf block Braiins carries, from the RAW MRR
        # detail (percent / avg TH / delivered TH·h / cost sats/TH/h).
        perf = _rental_perf.compute_mrr_perf(raw) if raw and not raw.get("error") else {}
        # Track record of the SAME rig (histórico de % por rig) so the
        # operator sees how this rig delivered on previous rentals.
        rig = raw.get("rig") or {}
        rig_history = _rental_perf.fetch_rig_performance_history(
            rig.get("id"), rig.get("name"), exclude_rental_id=rid, tenant_id=tenant_id)
        return jsonify({"success": True, "provider": "mrr", "detail": raw,
                        "graph": detail.get("graph") or {},
                        "log": detail.get("log") or {},
                        "perf": perf,
                        "rig_history": rig_history,
                        "market": _rental_perf.fetch_market_reference()})
    except Exception as e:
        log.warning("[rentals] detail error: %s", e)
        return jsonify({"success": False, "error": "failed to fetch rental detail"}), 500


@app.route("/api/network/scan", methods=["POST"])
def api_network_scan():
    """Scan the local network for mining devices.

    Probes ARP cache + subnet for IPs, then checks cgminer (4028),
    Braiins REST (80), and Bitaxe (8080) ports with 200ms timeouts.
    Returns discovered devices with firmware hints.
    """
    try:
        result = _lan_scanner.scan_network()
        return jsonify({"success": True, **result})
    except Exception as e:
        log.warning("[lan_scanner] scan failed: %s", e)
        return jsonify({"success": False, "error": str(e)}), 500


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

    scored.sort(key=_market_offer_sort_key)

    return jsonify({
        "success": True,
        "ts": int(time.time()),
        "offers": scored,
    })


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Wallet management — change address via UI
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@app.route('/api/chart-data')
def api_chart_data():
    """Return historical chart data for the 4 charts.
    Params: chart (hashrate|pool|bestdiff|net), range (1h|6h|24h|7d|all).
    Reads from proximity_history table (sampled every ~60s)."""
    chart = request.args.get('chart', 'hashrate')
    rng = request.args.get('range', '1h')
    # R1 (PRO tier): 30d/all history is a PRO feature. Off-by-default — the
    # gate only fires when the operator sets PRO_LICENSE_KEYS and the caller
    # has no valid key; otherwise is_pro() is True in open mode.
    if rng in ('30d', 'all') and not is_pro():
        return jsonify({
            "error": "30d history is a PRO feature — requires a license key",
            "code": "LICENSE_REQUIRED",
            "required_tier": "pro",
            "upgrade": {"plan": "PRO", "price_usd_month": 9},
        }), 402
    # Fase 2.1: full range set — 15m (hashrate toolbar) and 30d (net toolbar)
    # previously fell back to 1h, silently showing the wrong window.
    window_seconds = {'15m': 900, '1h': 3600, '6h': 21600, '24h': 86400, '7d': 604800, '30d': 2592000, 'all': 2592000}
    window = window_seconds.get(rng, 3600)
    cutoff = int(time.time()) - window
    max_points = {'15m': 60, '1h': 120, '6h': 360, '24h': 500, '7d': 1000, '30d': 1500, 'all': 2000}
    limit = max_points.get(rng, 500)

    labels = []
    values = []

    # ── Live-session charts (no DB): cumulative P progression + share
    # difficulty histogram — fed from in-memory share_calc_history ──
    if chart in ('cum_p', 'share_dist'):
        sch = list(timeline_state.get("share_calc_history") or [])
        if chart == 'cum_p':
            # Cumulative P(block) = 1-(1-p)^n compounded over the session
            cum = 0.0
            for e in sch:
                p = float(e.get("p_block_this_share") or 0)
                if p > 0:
                    cum = 1.0 - (1.0 - cum) * (1.0 - p)
                labels.append(int(e.get("ts") or 0) * 1000)
                values.append(round(cum * 100, 6))
        else:
            # Histogram of share difficulty across the session
            diffs = [float(e.get("share_diff_raw") or 0) for e in sch if e.get("share_diff_raw")]
            target_diff = None
            target_bucket = None
            if diffs:
                lo, hi = min(diffs), max(diffs)
                nb = min(12, max(5, len(diffs) // 3))
                if hi > lo:
                    step = (hi - lo) / nb
                    buckets = [0] * nb
                    for d in diffs:
                        bi = min(nb - 1, int((d - lo) / step))
                        buckets[bi] += 1
                    for i in range(nb):
                        # Audit 2026-08-02: labels were raw scientific notation
                        # ("7.19e+07") — unreadable. Format as human diff (71.9M).
                        labels.append(fmt_diff(lo + i * step))
                        values.append(buckets[i])
                    # P0-1: map the network difficulty onto the histogram so the
                    # UI can draw a "target" reference line — actionable intel
                    # ("how far are my shares from block-winning difficulty?").
                    net_diff = float(_last_valid_network.get("difficulty") or 0)
                    if net_diff > 0:
                        target_diff = net_diff
                        if net_diff < lo:
                            target_bucket = 0
                        elif net_diff > hi:
                            target_bucket = nb - 1
                        else:
                            target_bucket = min(nb - 1, int((net_diff - lo) / step))
                else:
                    labels.append(fmt_diff(lo))
                    values.append(len(diffs))
            if not labels:
                labels = []
                values = []
        return jsonify({
            'labels': labels,
            # Fase 2.2: expose the real share count so the panel badge
            # ("0 shares" was hardcoded in the HTML) can reflect reality.
            'count': len(diffs) if chart == 'share_dist' else None,
            # P0-1: network target difficulty + its histogram bucket (for the
            # purple reference line overlay). Null when unavailable.
            'target_diff': target_diff if chart == 'share_dist' else None,
            'target_bucket': target_bucket if chart == 'share_dist' else None,
            'datasets': [{
                'label': 'Cumulative P(Block) %' if chart == 'cum_p' else 'Shares',
                'data': values,
                'fill': True,
                'borderColor': '#a855f7' if chart == 'cum_p' else '#10b981',
                'backgroundColor': 'rgba(168,85,247,0.1)' if chart == 'cum_p' else 'rgba(16,185,129,0.1)',
                'tension': 0.3,
            }],
        })

    try:
        conn = get_db()
        c = conn.cursor()
        if chart == 'hashrate':
            c.execute(
                "SELECT ts, worker_hashrate FROM proximity_history "
                "WHERE ts > ? AND worker_hashrate > 0 ORDER BY ts ASC LIMIT ?",
                (cutoff, limit),
            )
        elif chart == 'bestdiff':
            c.execute(
                "SELECT ts, best_diff FROM proximity_history "
                "WHERE ts > ? AND best_diff > 0 ORDER BY ts ASC LIMIT ?",
                (cutoff, limit),
            )
        elif chart == 'pool':
            # Pool hashrate not in proximity_history; use snapshots table
            c.execute(
                "SELECT ts, pool_hashrate FROM snapshots "
                "WHERE ts > ? AND pool_hashrate > 0 ORDER BY ts ASC LIMIT ?",
                (cutoff, limit),
            )
        elif chart == 'net':
            c.execute(
                "SELECT ts, network_difficulty FROM proximity_history "
                "WHERE ts > ? AND network_difficulty > 0 ORDER BY ts ASC LIMIT ?",
                (cutoff, limit),
            )
        rows = c.fetchall()
        conn.close()
        for row in rows:
            labels.append(int(row['ts']) * 1000)  # JS expects ms timestamps
            values.append(float(row[1]))  # second column is the value
    except Exception as e:
        logging.getLogger("cypher65").warning("[chart-data] error: %s", e)

    # ── Fase 2.1: event annotations + share-volume overlay ──
    # Events feed the vertical annotation lines on the charts (bumps are
    # drawn as critical, share finds as subtle); shares powers the bar
    # overlay on the hashrate chart. Both are honest telemetry — only real
    # persisted timeline events are returned, never invented.
    events = []
    shares = None
    try:
        import bisect
        conn = get_db()
        c = conn.cursor()
        c.execute(
            """SELECT ts, event_type, severity, message FROM share_timeline
               WHERE ts > ? AND event_type IN ('SHARE_FOUND', 'BEST_DIFF_BUMP')
               ORDER BY ts ASC LIMIT 600""",
            (cutoff,),
        )
        for r in c.fetchall():
            events.append({
                "ts": int(r["ts"]),
                "event_type": r["event_type"],
                "severity": r["severity"] or "INFO",
                "message": r["message"] or "",
            })
        # Shares-per-bucket overlay aligned to the label timestamps (ms).
        # Only the hashrate chart renders the bar overlay.
        if chart == "hashrate" and labels:
            pts = [int(t) for t in labels]  # already ms
            buckets = [0] * len(pts)
            for e in events:
                if e["event_type"] != "SHARE_FOUND":
                    continue
                idx = bisect.bisect_right(pts, e["ts"] * 1000) - 1
                if 0 <= idx < len(buckets):
                    buckets[idx] += 1
            shares = buckets
        conn.close()
    except Exception as e:
        logging.getLogger("cypher65").warning("[chart-data] events: %s", e)

    # Fallback: if no history data, return current snapshot value as single point
    if not labels:
        # Audit 2026-08-02: latest_snapshot is None before the first poll
        # completes (and in tests) — .get() on None raised AttributeError (500)
        # for any chart request hitting the fallback. The snapshot dict also
        # initializes worker/pool/account to None (not missing), so the guard
        # must be `(snap.get(k) or {})` — the `, {}` default only applies to
        # ABSENT keys, not keys present with a None value.
        snap = latest_snapshot or {}
        worker = snap.get('worker') or {}
        labels = [int(time.time()) * 1000]
        if chart == 'cum_p':
            lc = (snap.get("proximity") or {}).get("live_calc") or {}
            values = [float((lc.get("session_totals") or {}).get("cum_p_block") or 0) * 100]
        elif chart == 'share_dist':
            labels = []
            values = []
        elif chart == 'hashrate':
            values = [float(worker.get('hashrate') or 0)]
        elif chart == 'bestdiff':
            bd = worker.get('bestDifficulty') or 0
            try:
                values = [float(bd)]
            except (ValueError, TypeError):
                values = [0]
        elif chart == 'pool':
            values = [float((snap.get('pool') or {}).get('hashrate') or 0)]
        elif chart == 'net':
            net = snap.get('network') or {}
            values = [float(net.get('difficulty') or 0)]

    return jsonify({
        'labels': labels,
        'datasets': [{
            'label': 'Worker Hashrate' if chart == 'hashrate' else 'Best Difficulty' if chart == 'bestdiff' else 'Pool Hashrate' if chart == 'pool' else 'Network Difficulty',
            'data': values,
            'fill': True,
            'borderColor': '#06d6f0',
            'backgroundColor': 'rgba(6,214,240,0.1)',
            'tension': 0.3,
        }],
        # Fase 2.1: event annotations (ts in seconds) + share-volume overlay
        'events': events,
        'shares': shares,
    })


# ── FULL & FREE community wallets (exact addresses) ─────────────────────
# Wallets granted full & free access: they receive the personalized greeting
# on connect. These exact addresses bypass the strict BTC prefix/checksum
# validation in /api/set-address because a DOGE/LTC address does not start
# with bc1/1/3 — but ONLY these exact addresses; every other address is
# validated strictly. Stored lowercase (lookup is case-insensitive).
_FULL_ACCESS_WALLETS = frozenset({
    "bc1q029y2atdtvth4puv2mm5w49m32n278jtz2sxqn",
    "dhr7a2ihqou5w5r5cpvsuvcnw4jg32qlwx",   # DOGE
    "1473pql42jvtwxaaxcvsocrf6ytb8teted",   # LTC
})


@app.route("/api/set-address", methods=["POST"])
@require_tenant
@role_required("member")
def api_set_address(tenant_id: str = ""):
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
    import re

    data = request.get_json(silent=True) or {}
    new_addr = (data.get("address") or "").strip()
    new_worker = (data.get("worker") or "").strip()

    # ── Validation ──
    errors = []
    # FULL & FREE community wallets (exact addresses, case-insensitive) bypass
    # the strict BTC prefix/checksum checks — a DOGE/LTC address intentionally
    # doesn't start with bc1/1/3. Every OTHER address goes through the full
    # validator unchanged.
    is_full_access = new_addr.lower() in _FULL_ACCESS_WALLETS
    if not new_addr:
        errors.append("address is required")
    elif not is_full_access and not (new_addr.startswith("bc1") or new_addr.startswith("1") or new_addr.startswith("3")):
        errors.append("address must start with bc1 (bech32), 1 (legacy) or 3 (P2SH)")
    elif new_addr == BTC_ADDRESS and not new_worker:
        errors.append("address is the same as current — no change needed")
    else:
        if not is_full_access:
            # Proper checksum validation via helpers.py
            from helpers import validate_btc_address as _val_btc
            val = _val_btc(new_addr)
            if not val.get("valid"):
                errors.append(val.get("error", "invalid address"))


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

    # ── Log the OLD address to history before reset ──
    _log_wallet_change(old_addr, old_worker)

    # ── Reset session state ──
    _reset_session_state()

    # ── Honest Telemetry: a wallet SWITCH must not leak the previous
    #    wallet's DB-backed chart history into the new session. Clearing only
    #    happens when the address actually changed (worker-only updates keep
    #    the existing history). Charts refill from the immediate poll below.
    if old_addr.lower() != new_addr.lower():
        _clear_wallet_scoped_history()

    # ── Force immediate poll with the NEW address ──
    # Without this, the snapshot stays empty until the next scheduled poll
    # (up to 15s later), leaving the dashboard blank after connect wallet.
    threading.Thread(target=poll_once, daemon=True).start()

    # ── Add a SUCCESS alert ──
    ts = int(time.time())
    memory_critical_alerts.append(_make_memory_alert(
        ts, "SUCCESS", "wallet_changed",
        f"Wallet changed from {old_addr[:12]}… → {new_addr[:12]}…"
    ))

    log.info("[set-address] %s → %s (%s)", old_addr[:12], new_addr[:12], new_worker or WORKER_NAME)

    return jsonify({
        "success": True,
        "ok": True,          # alias for test compatibility
        "address": new_addr,
        "worker": WORKER_NAME,
        "old_address": old_addr,
    })


# ═══════════════════════════════════════════════════════════════════════════
#  AI OPERATOR — POST /api/ai/query  (SSE streaming)
# ═══════════════════════════════════════════════════════════════════════════

from services.ai_operator import stream_response, AI_QUERIES_PER_MINUTE

# Per-IP rate limiter for AI queries
_ai_rate_store: Dict[str, List[float]] = {}


@app.route("/api/ai/query", methods=["POST"])
@require_tenant
@role_required("member")
def api_ai_query(tenant_id: str = ""):
    """AI Operator chat endpoint. Accepts a JSON body with `query` and
    streams the LLM response as Server-Sent Events (SSE).

    Request body:
        {"query": "What is my current hashrate?"}

    Response (SSE stream):
        data: {"type":"text","content":"..."}\n\n
        data: {"type":"action","action":{"device_id":"...","command":"restart","reason":"..."}}\n\n
        data: {"type":"done"}\n\n
    """
    # Rate limiting: max AI_QUERIES_PER_MINUTE per IP
    ip = request.remote_addr or "127.0.0.1"
    now = time.time()
    if ip not in _ai_rate_store:
        _ai_rate_store[ip] = []
    _ai_rate_store[ip] = [t for t in _ai_rate_store[ip] if now - t < 60]
    if len(_ai_rate_store[ip]) >= AI_QUERIES_PER_MINUTE:
        return jsonify({"error": "Rate limit: max 10 queries per minute"}), 429
    _ai_rate_store[ip].append(now)

    data = request.get_json(silent=True) or {}
    query = (data.get("query") or "").strip()
    if not query:
        return jsonify({"error": "query is required"}), 400

    def generate():
        # Use the global latest_snapshot as context
        snapshot = latest_snapshot if latest_snapshot.get("ts") else {}
        for chunk in stream_response(query, snapshot):
            yield f"data: {chunk}\n\n"

    return Response(
        generate(),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


# ── SSE live stream endpoint ──────────────────────────────────────────────
# Pushes snapshot updates to the frontend via Server-Sent Events (EventSource)
# so the UI updates in near-real-time without polling.
_sse_clients: List["queue.Queue"] = []
_sse_clients_lock = threading.Lock()

@app.route("/api/stream")
def sse_stream():
    """SSE endpoint: yields latest snapshot data when it changes.
    Frontend connects via EventSource and receives push updates at ~3s intervals.
    Falls back gracefully to polling if SSE disconnects."""
    def event_stream():
        q = queue.Queue(maxsize=5)
        with _sse_clients_lock:
            _sse_clients.append(q)
            _sse_client_count = len(_sse_clients)
        try:
            # Yield initial keepalive
            yield ": connected\n\n"
            while True:
                try:
                    data = q.get(timeout=3)
                    yield f"data: {data}\n\n"
                except queue.Empty:
                    # Send keepalive comment to prevent proxy timeouts
                    yield ": keepalive\n\n"
        except GeneratorExit:
            pass
        finally:
            with _sse_clients_lock:
                try:
                    _sse_clients.remove(q)
                except ValueError:
                    pass

    return Response(
        event_stream(),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


def _broadcast_snapshot(snapshot: dict):
    """Send the latest snapshot to all connected SSE clients.
    Called by poll_loop after fetching and processing data."""
    try:
        payload = json.dumps(snapshot, default=str)
        dead_clients = []
        with _sse_clients_lock:
            for q in _sse_clients:
                try:
                    q.put_nowait(payload)
                except queue.Full:
                    dead_clients.append(q)
            for q in dead_clients:
                _sse_clients.remove(q)
    except Exception as e:
        log.warning("[sse broadcast] error: %s", e)


# ── FASE 2: Wallet address history table ──
# In init_db(), add the wallet_address_history table


# ═══════════════════════════════════════════════════════════════════════════
# Fase 6 · PR2: /api/snapshot now served by dashboard_bp.
# build_auto_pilot_context and _compute_block_hunt are shared with the
# blueprint via services/snapshot_enrichment.py — these thin wrappers keep
# the app.py call sites (api_block_hunt + external importers) working with
# the single shared implementation.
# _get_hashrate_market_offers and _hashrate_market_health stay in app.py
# (their cache/state is separate from snapshot_enrichment's — the warmup
# thread fills this cache for app.py routes; snapshot_enrichment fills its
# own for the blueprint). Merging them is a future cleanup.
# ═══════════════════════════════════════════════════════════════════════════

# Re-import with aliases for delegation.
from services.snapshot_enrichment import (  # noqa: E402
    _compute_block_hunt as _sre_block_hunt,
)


def _compute_block_hunt(snap):
    """Delegate to shared implementation in snapshot_enrichment."""
    return _sre_block_hunt(snap)


if __name__ == "__main__":
    # External-review quick win (P1 #8): when the API is locked behind API
    # keys, SECRET_KEY must be stable — a missing/volatile secret silently
    # invalidates every JWT and Flask session on restart. Refuse to boot
    # instead of running with broken auth. Open mode (no API_KEY /
    # TENANT_API_KEYS) is unaffected. Checked here (not at import) so pytest
    # and gunicorn app:app imports never abort.
    if (API_KEY or TENANT_API_KEYS) and not (os.environ.get("SECRET_KEY")
                                             or os.environ.get("JWT_SECRET_KEY")):
        raise SystemExit(
            "FATAL: SECRET_KEY is required when API_KEY/TENANT_API_KEYS is set. "
            "Set a stable SECRET_KEY in the environment."
        )
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
    # ── Start all background workers (initial poll + poll loop + 5-min
    #    Hash Market warmup) from one place — see _start_background_threads. ──
    _start_background_threads()
    # TLS opcional: defina CERT_FILE/KEY_FILE para servir HTTPS. Sem elas o
    # app continua HTTP (uso típico: atrás de Tailscale/tailnet).
    _ssl_ctx = None
    if os.environ.get("CERT_FILE") and os.environ.get("KEY_FILE"):
        _ssl_ctx = (os.environ["CERT_FILE"], os.environ["KEY_FILE"])
        print("⇢  TLS habilitado (HTTPS)")
    app.run(host="0.0.0.0", port=PORT, debug=False, threaded=True, ssl_context=_ssl_ctx)
