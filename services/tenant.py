"""
CYPHER65 // Tenant helpers (shared)
====================================
Single source of truth for extracting ``tenant_id`` from the request context
and for the ``@require_tenant`` decorator.

Priority for tenant resolution:
  1. ``g.auth_payload`` (set by ``@require_auth``)
  2. ``Authorization: Bearer <token>`` (decoded directly, so routes protected
     only by ``@require_tenant`` still isolate per account)
  3. Legacy Flask session (``session["authenticated"]`` → ``tenant_id``)
  4. ``"default"`` (single-tenant / self-host mode)

Used by axe_fleet, alerts, automations and core device routes so every module
isolates with exactly the same logic.
"""
import json
import logging
import os
import sqlite3
import time
from functools import wraps
from typing import Any, Dict, Optional

from flask import g, request, session

log = logging.getLogger("cypher65.tenant")

# Defaults for the FREE plan — used when a tenant row doesn't exist yet (or
# the column is missing), so the system is honest instead of crashing or
# inventing a limit. Named tenants provisioned via TENANT_API_KEYS get these
# strict free-tier defaults until a tenants row is created for them.
DEFAULT_PLAN = "free"
DEFAULT_MAX_WORKERS = 5

# The operator's own "default" tenant (single-tenant / self-host mode) must
# NEVER be silently capped by the free tier — that would 403 the 6th add with
# no UI to raise the limit. init_db provisions a 'default' row with this
# generous cap; this constant is also the in-code fallback if the row is ever
# missing. Configurable via env for power users.
SELF_HOST_MAX_WORKERS = int(os.environ.get("SELF_HOST_MAX_WORKERS", "50"))


# ── Plan / worker-limit helpers ──────────────────────────────────────────


def _db_conn():
    """Open a SQLite connection to the war-room DB (env DB_PATH or default)."""
    db_path = os.environ.get("DB_PATH", "data/war_room.sqlite")
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def get_tenant_plan(tenant_id: str = "") -> Dict[str, Any]:
    """Return the plan limits for a tenant.

    Reads the `tenants` table (plan + max_workers). When the tenant row is
    missing (legacy / not yet provisioned), returns the FREE-plan defaults so
    every tenant is bounded by the free tier by default. Never raises: a DB
    error degrades to the safe free-plan default.
    """
    tid = tenant_id or "default"
    try:
        conn = _db_conn()
        c = conn.cursor()
        c.execute("SELECT plan, max_workers FROM tenants WHERE id=?", (tid,))
        row = c.fetchone()
        conn.close()
        if row is not None:
            return {
                "plan": row["plan"] or DEFAULT_PLAN,
                "max_workers": int(row["max_workers"] or DEFAULT_MAX_WORKERS),
            }
    except Exception as e:
        log.warning("[tenant] get_tenant_plan(%s) failed: %s", tid, e)
    # No row (yet) or DB error — honest defaults, never fabricated:
    #   - "default"  → the operator's own self-host deployment: generous cap,
    #     never silently blocked (matches the row init_db provisions).
    #   - named tenants (provisioned via TENANT_API_KEYS) → strict free tier.
    if tid == "default":
        return {"plan": DEFAULT_PLAN, "max_workers": SELF_HOST_MAX_WORKERS}
    return {"plan": DEFAULT_PLAN, "max_workers": DEFAULT_MAX_WORKERS}


def count_tenant_workers(tenant_id: str = "") -> int:
    """Count the tenant's registered fleet devices (axe_devices rows).

    The Axe Fleet is the worker surface the plan limit applies to (home
    miners / ASICs registered as workers). Core 'devices' are diagnostics
    entities, not workers. Returns 0 on any DB error (honest: no data).
    """
    tid = tenant_id or "default"
    try:
        conn = _db_conn()
        c = conn.cursor()
        c.execute("SELECT COUNT(*) AS n FROM axe_devices WHERE tenant_id=?", (tid,))
        row = c.fetchone()
        conn.close()
        return int(row["n"] or 0) if row is not None else 0
    except Exception as e:
        log.warning("[tenant] count_tenant_workers(%s) failed: %s", tid, e)
        return 0


def can_add_worker(tenant_id: str = "") -> bool:
    """True if the tenant is below its plan's max_workers limit.

    The enforcement point (axe_fleet add_device) calls this BEFORE persisting
    a new worker. Free plan default caps at DEFAULT_MAX_WORKERS (5)."""
    plan = get_tenant_plan(tenant_id)
    used = count_tenant_workers(tenant_id)
    return used < plan["max_workers"]


# ── Structured audit log ─────────────────────────────────────────────────


def log_audit(tenant_id: str = "", action: str = "", target: str = "",
              details: Optional[dict] = None, user_id: str = "") -> Optional[int]:
    """Persist a structured audit entry to the audit_logs table.

    Best-effort by design: audit must never break the request it records,
    so any failure is logged and swallowed. Returns the new row id or None.

    Columns: ts, tenant_id, user_id, action, target, details (JSON).
    """
    if not action:
        return None
    try:
        conn = _db_conn()
        c = conn.cursor()
        c.execute(
            """INSERT INTO audit_logs (ts, tenant_id, user_id, action, target, details)
            VALUES (?, ?, ?, ?, ?, ?)""",
            (
                int(time.time()),
                tenant_id or "default",
                user_id or "",
                action,
                target or "",
                json.dumps(details or {}),
            ),
        )
        row_id = c.lastrowid
        conn.commit()
        conn.close()
        return row_id
    except Exception as e:
        log.warning("[tenant] log_audit(%s, %s) failed: %s", tenant_id, action, e)
        return None


def recent_audit_logs(tenant_id: str = "", limit: int = 100) -> list:
    """Return the tenant's most recent audit entries, newest first."""
    tid = tenant_id or "default"
    try:
        conn = _db_conn()
        c = conn.cursor()
        c.execute(
            "SELECT * FROM audit_logs WHERE tenant_id=? ORDER BY ts DESC, id DESC LIMIT ?",
            (tid, int(limit)),
        )
        rows = [dict(r) for r in c.fetchall()]
        conn.close()
        # details is stored as JSON text — parse it so consumers get a dict
        # (with a safe {} fallback for legacy/broken rows).
        for row in rows:
            try:
                row["details"] = json.loads(row.get("details") or "{}")
            except (json.JSONDecodeError, TypeError):
                row["details"] = {}
        return rows
    except Exception as e:
        log.warning("[tenant] recent_audit_logs(%s) failed: %s", tid, e)
        return []


def get_tenant_id() -> str:
    """Extract tenant ID from the current request context.

    Priority: JWT auth payload > Authorization Bearer > session.
    Returns 'default' as fallback (single-tenant mode).
    """
    # 1) JWT auth payload (from require_auth decorator)
    try:
        payload = g.auth_payload
        if payload and payload.get("sub"):
            return payload["sub"]
    except (AttributeError, RuntimeError):
        pass
    # 2) Decode the Authorization Bearer token directly, so tenant
    #    isolation works on routes protected only by require_tenant.
    try:
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            from services.auth import verify_token
            payload = verify_token(auth_header[7:], expected_type="access")
            if payload and payload.get("sub"):
                return payload["sub"]
    except Exception:
        pass
    # 3) Flask session (legacy)
    try:
        if session and session.get("authenticated"):
            return session.get("tenant_id", "default")
    except RuntimeError:
        pass
    # 4) Default tenant (single-user mode)
    return "default"


def require_tenant(f):
    """Flask decorator: extract tenant_id from JWT/session and inject
    as keyword argument `tenant_id` to the route handler."""
    @wraps(f)
    def wrapper(*args, **kwargs):
        kwargs["tenant_id"] = get_tenant_id()
        return f(*args, **kwargs)
    return wrapper
