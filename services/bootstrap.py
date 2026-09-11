"""
CYPHER65 // DB bootstrap — RFC #478 · PR B4 (Issue #507)
========================================================
Bootstrap e schema do SQLite (init_db + versionamento da revisão + retenção),
extraídos verbatim de `app.py`. Mesmos corpos, mesmas tabelas, mesmos índices,
mesma idempotência — nada aqui é comportamento novo.

Peças movidas:

  * ``SCHEMA_VERSION`` — revisão atual, re-export de
    ``services.schema.CURRENT_SCHEMA_VERSION``;
  * ``_record_schema_version(conn)`` — upsert da revisão + timestamp de boot;
  * **``init_db()`` (576 linhas)** — ``CREATE TABLE IF NOT EXISTS``, ALTERs
    guardados por ``PRAGMA table_info`` (DBs legados), todos os índices, os
    pragmas da conexão e o carimbo final da revisão;
  * ``purge_old()`` — retenção de 30 dias (snapshots/alerts/share_timeline/
    proximity_history) + o passe de ``purge_pool_metrics`` (7 dias, Issue #17).

A conexão vem de ``services.db.get_db()``, a implementação canônica. O ``app.py``
carregava uma **DUPLICATA idêntica** (``app.get_db``) — removida neste PR: era o
item "WAL" da tabela do RFC, e agora existe uma única implementação.

O ``app.py`` re-exporta os nomes movidos (o MESMO objeto, sem segunda
implementação), então ``app.init_db()``, ``appmod.purge_old()`` e
``app_module.SCHEMA_VERSION`` seguem válidos — e a chamada de boot ``init_db()``
continua no ``app.py``.

Design rule: este módulo **não** importa ``app`` (o wiring é o inverso). A
sequência de boot (``init_db()`` → ``ensure_users_schema()`` → Sentry →
``error_tracker.install``) permanece no ``app.py``, na ordem, porque depende
dele.
"""

import logging
import sqlite3
import time

import services.beta_analytics as _beta_analytics
import services.conversion as _conversion
import services.doc_feedback as _doc_feedback
import services.error_tracker as _error_tracker
from services.db import get_db
from services.schema import CURRENT_SCHEMA_VERSION
from services.tenant import SELF_HOST_MAX_WORKERS

log = logging.getLogger("cypher65.bootstrap")

SCHEMA_VERSION = CURRENT_SCHEMA_VERSION


# ── Schema version tracking (#5: versioned migrations) ─────────────────────
# init_db() below is idempotent (CREATE IF NOT EXISTS + guarded ALTERs), but
# until now there was no record of WHICH migrations ran. This constant is the
# current schema revision; _record_schema_version() stamps it into the
# schema_version table on every boot so operators/tests can verify the DB
# layout matches the code that wrote it.
# Backwards-compatible name used by existing tests and operational probes.
SCHEMA_VERSION = CURRENT_SCHEMA_VERSION


def _record_schema_version(conn):
    """Upsert the current schema version + boot timestamp. Safe on legacy
    DBs (table is created if missing)."""
    try:
        c = conn.cursor()
        c.execute(
            "CREATE TABLE IF NOT EXISTS schema_version "
            "(version INTEGER PRIMARY KEY, applied_ts INTEGER NOT NULL)"
        )
        c.execute(
            "INSERT INTO schema_version(version, applied_ts) VALUES(?,?) "
            "ON CONFLICT(version) DO UPDATE SET applied_ts=excluded.applied_ts",
            (SCHEMA_VERSION, int(time.time())),
        )
    except Exception as e:
        log.warning("[migrate] schema_version record failed: %s", e)


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
    c.execute(
        "CREATE INDEX IF NOT EXISTS idx_tenant_settings_tenant ON tenant_settings(tenant_id)"
    )
    c.execute(
        """CREATE TABLE IF NOT EXISTS proximity_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts INTEGER NOT NULL,
            tenant_id TEXT NOT NULL DEFAULT 'default',
            best_diff REAL,
            best_diff_str TEXT,
            all_time_best_diff REAL,
            network_difficulty REAL,
            worker_hashrate REAL,
            pct_of_network REAL,
            hot_streak INTEGER DEFAULT 0
        )"""
    )
    # Issue #423: legacy proximity rows predate tenant isolation.  Attribute
    # those rows to the operator/default tenant instead of allowing them to be
    # read by every tenant through an unscoped peak query.
    c.execute("PRAGMA table_info(proximity_history)")
    proximity_cols = {row[1] for row in c.fetchall()}
    if "tenant_id" not in proximity_cols:
        try:
            c.execute(
                "ALTER TABLE proximity_history "
                "ADD COLUMN tenant_id TEXT NOT NULL DEFAULT 'default'"
            )
            log.info("[migrate] added proximity_history.tenant_id column")
        except sqlite3.Error as e:
            log.warning("[migrate] could not add proximity_history.tenant_id: %s", e)
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
    c.execute("CREATE INDEX IF NOT EXISTS idx_snapshots_ts ON snapshots(ts)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_alerts_ts ON alerts(ts)")
    c.execute(
        "CREATE INDEX IF NOT EXISTS idx_high_diff_height ON highest_diff_events(block_height)"
    )
    c.execute("CREATE INDEX IF NOT EXISTS idx_share_timeline_ts ON share_timeline(ts)")
    c.execute(
        "CREATE INDEX IF NOT EXISTS idx_share_timeline_type ON share_timeline(event_type)"
    )
    c.execute(
        "CREATE INDEX IF NOT EXISTS idx_proximity_history_ts ON proximity_history(ts)"
    )
    c.execute(
        "CREATE INDEX IF NOT EXISTS idx_proximity_history_tenant_ts "
        "ON proximity_history(tenant_id, ts)"
    )
    # ── Data audit (2026-08-02): missing time-series ts indexes ──
    c.execute(
        "CREATE INDEX IF NOT EXISTS idx_highest_diff_events_ts ON highest_diff_events(ts)"
    )
    # NOTE: idx_maintenance_records_ts is created AFTER the maintenance_records
    # table below (a fresh DB would otherwise fail with "no such table").
    # One snapshot row per poll second — enforce uniqueness so the forced
    # poll and scheduled poll can never double-write the same ts (9,612 dup
    # groups found in the audit). Best-effort: a legacy DB still holding
    # duplicates logs a warning and skips (the migration cleans them).
    try:
        c.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_snapshots_ts ON snapshots(ts)")
    except sqlite3.Error as e:
        log.warning(
            "[init_db] could not create unique snapshots(ts) index (duplicates?): %s", e
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
    c.execute(
        "CREATE INDEX IF NOT EXISTS idx_maintenance_records_ts ON maintenance_records(ts)"
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
    c.execute(
        "CREATE INDEX IF NOT EXISTS idx_best_diff_history_ts ON best_diff_history(ts)"
    )
    c.execute(
        "CREATE INDEX IF NOT EXISTS idx_best_diff_history_device ON best_diff_history(device_id)"
    )
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
    c.execute(
        "CREATE INDEX IF NOT EXISTS idx_hashrate_market_history_ts ON hashrate_market_history(ts)"
    )
    c.execute(
        "CREATE INDEX IF NOT EXISTS idx_hashrate_market_history_provider ON hashrate_market_history(provider)"
    )
    # ── Issue #17: persistent pool metrics (60s sampler → trend lines) ──
    from services.pool_metrics import (
        POOL_METRICS_INDEX as _PM_INDEX,
        POOL_METRICS_SCHEMA as _PM_SCHEMA,
    )

    c.execute(_PM_SCHEMA)
    c.execute(_PM_INDEX)
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
    c.execute(
        "CREATE INDEX IF NOT EXISTS idx_alert_rules_enabled ON alert_rules(enabled)"
    )
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
            c.execute(
                "ALTER TABLE automation_rules ADD COLUMN min_interval_seconds INTEGER DEFAULT 60"
            )
        except Exception as e:
            log.warning("[init_db] could not add column min_interval_seconds: %s", e)
    c.execute(
        "CREATE INDEX IF NOT EXISTS idx_automation_rules_enabled ON automation_rules(is_enabled)"
    )
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
    c.execute(
        "CREATE INDEX IF NOT EXISTS idx_alert_history_device ON alert_history(device_id)"
    )
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
    c.execute(
        "CREATE INDEX IF NOT EXISTS idx_automation_execution_log_ts ON automation_execution_log(ts)"
    )
    c.execute(
        "CREATE INDEX IF NOT EXISTS idx_automation_execution_log_rule ON automation_execution_log(rule_id)"
    )
    c.execute(
        "CREATE INDEX IF NOT EXISTS idx_automation_execution_log_device ON automation_execution_log(device_id)"
    )
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
    c.execute(
        "CREATE INDEX IF NOT EXISTS idx_wallet_history_addr ON wallet_address_history(address)"
    )
    c.execute(
        "CREATE INDEX IF NOT EXISTS idx_wallet_history_ts ON wallet_address_history(connected_at)"
    )
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
    c.execute(
        "CREATE INDEX IF NOT EXISTS idx_donations_preimage ON donations(preimage)"
    )

    # ── Multi-tenant migration: add tenant_id to axe_fleet tables ──
    for table_name in ("axe_devices", "axe_telemetry"):
        try:
            c.execute(f"PRAGMA table_info({table_name})")
            cols = {row[1] for row in c.fetchall()}
            if "tenant_id" not in cols:
                c.execute(
                    f"ALTER TABLE {table_name} ADD COLUMN tenant_id TEXT DEFAULT 'default'"
                )
                log.info("[migrate] added tenant_id to %s", table_name)
        except Exception as e:
            log.warning("[migrate] could not add tenant_id to %s: %s", table_name, e)
    try:
        c.execute(
            "CREATE INDEX IF NOT EXISTS idx_axe_devices_tenant ON axe_devices(tenant_id)"
        )
        c.execute(
            "CREATE INDEX IF NOT EXISTS idx_axe_telemetry_tenant ON axe_telemetry(tenant_id)"
        )
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
        for col, col_def in (
            ("plan", "TEXT NOT NULL DEFAULT 'free'"),
            ("max_workers", "INTEGER NOT NULL DEFAULT 5"),
        ):
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
    c.execute(
        "CREATE INDEX IF NOT EXISTS idx_audit_logs_tenant_ts ON audit_logs(tenant_id, ts)"
    )
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
    # ── Learning FAQ loop (Issue #19): doc feedback per section, deduped ──
    try:
        _doc_feedback.ensure_table()
    except Exception as e:
        log.warning("[migrate] doc_feedback init failed: %s", e)

    # ── Observability (Issue #176): local error-rate sampler table ──
    # Buckets per hour + request_id — the $0 half of error tracking, works
    # on self-host with NO Sentry DSN (Sentry is wired at boot, not here).
    try:
        _error_tracker.ensure_table(conn)
    except Exception as e:
        log.warning("[migrate] error_metrics init failed: %s", e)

    # Issue #202: WARNING/degradation bucket — every WARNING record (including
    # the converted `except: pass` sites) lands here so silent failures become
    # visible telemetry ($0, self-host friendly, same discipline).
    try:
        _error_tracker.ensure_degradation_table(conn)
    except Exception as e:
        log.warning("[migrate] degradation_metrics init failed: %s", e)

    # ── CFO: PRO conversion telemetry (funnel + LTV/CAC) ──
    # Rows are funnel events (paywall_view → modal_open → checkout_start →
    # paid → key_activated); tenant_id/email are SHA-256 hashed (privacy).
    try:
        _conversion.ensure_table()
    except Exception as e:
        log.warning("[migrate] conversion_events init failed: %s", e)

    # ── Beta: self-hosted usage analytics (boot, module, time) ──
    try:
        _beta_analytics.ensure_table()
    except Exception as e:
        log.warning("[migrate] beta_analytics init failed: %s", e)

    # ── Fase 4 · B2: add tenant_id to alerts/automations/core tables ──
    for table_name in (
        "alerts",
        "alert_history",
        "alert_rules",
        "automation_rules",
        "automation_execution_log",
    ):
        try:
            c.execute(f"PRAGMA table_info({table_name})")
            cols = {row[1] for row in c.fetchall()}
            if "tenant_id" not in cols:
                c.execute(
                    f"ALTER TABLE {table_name} ADD COLUMN tenant_id TEXT DEFAULT 'default'"
                )
                log.info("[migrate] added tenant_id to %s", table_name)
        except Exception as e:
            log.warning("[migrate] could not add tenant_id to %s: %s", table_name, e)
    try:
        c.execute("CREATE INDEX IF NOT EXISTS idx_alerts_tenant ON alerts(tenant_id)")
        c.execute(
            "CREATE INDEX IF NOT EXISTS idx_alert_rules_tenant ON alert_rules(tenant_id)"
        )
        c.execute(
            "CREATE INDEX IF NOT EXISTS idx_automation_rules_tenant ON automation_rules(tenant_id)"
        )
    except Exception:
        pass  # ── WAL mode for better concurrent read/write ──
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA synchronous=NORMAL")
    c.execute("PRAGMA cache_size=-8000")  # 8MB cache
    c.execute("PRAGMA busy_timeout=3000")
    # Stamp the schema revision so the DB layout is verifiable (audit #5).
    _record_schema_version(conn)
    conn.commit()
    conn.close()


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
    # Pool metrics have their own (shorter) retention — 7 days is enough for
    # the 24h/7d trend lines and keeps the file from growing unbounded
    # (Issue #17).
    try:
        from services.pool_metrics import purge_pool_metrics as _purge_pm

        _conn = get_db()
        try:
            _purge_pm(_conn)
        finally:
            _conn.close()
    except Exception as e:
        log.warning("[purge] pool_metrics error: %s", e)
