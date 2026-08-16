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
import re
import sqlite3
import time
from functools import wraps
from typing import Any, Dict, Optional

from flask import g, jsonify, request, session

log = logging.getLogger("cypher65.tenant")

# ── Allowlist for the users-table DDL (audit C7) ─────────────────────────
# Only identifiers matching this pattern may be interpolated into ALTER
# TABLE — defense-in-depth so a schema migration can never inject SQL even
# if a future caller passes unsanitized input.
_ALLOWED_COLUMN_NAME = re.compile(r"^[a-z_][a-z0-9_]*$")

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
    """Open a SQLite connection to the war-room DB (env DB_PATH or default).

    Audit C5: per-connection WAL + busy_timeout so concurrent polling writers
    never hit "database is locked". Best-effort — skipped on :memory: DBs.
    """
    db_path = os.environ.get("DB_PATH", "data/war_room.sqlite")
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA busy_timeout=3000")
    except sqlite3.Error:
        pass
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
        # COALESCE(removed_at,0)=0: tombstoned (soft-deleted) devices must NOT
        # consume a worker slot — a removed miner can't resurrect the cap.
        c.execute(
            "SELECT COUNT(*) AS n FROM axe_devices WHERE tenant_id=? AND COALESCE(removed_at,0)=0",
            (tid,),
        )
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


def log_audit(
    tenant_id: str = "",
    action: str = "",
    target: str = "",
    details: Optional[dict] = None,
    user_id: str = "",
) -> Optional[int]:
    """Persist a structured audit entry to the audit_logs table.

    Best-effort by design: audit must never break the request it records,
    so any failure is logged and swallowed. Returns the new row id or None.

    user_id resolution (data provenance — audit C8): when the caller does not
    pass an explicit user_id, it is auto-resolved from the authenticated JWT
    payload (the `username` claim) when available. This fixes the audit trail
    being 100% anonymous (audit_logs.user_id was NULL on every row) while
    staying safe outside request context (no g → empty user_id).

    Columns: ts, tenant_id, user_id, action, target, details (JSON).
    """
    if not action:
        return None
    if not user_id:
        try:
            payload = g.auth_payload
            if payload and payload.get("username"):
                user_id = str(payload["username"])
        except (AttributeError, RuntimeError):
            pass
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


# ── RBAC (Role-Based Access Control) ─────────────────────────────────────
# Roles: admin (full) > member (view + execute) > viewer (read-only).
# Priority values for comparison — higher wins.
ROLE_PRIORITY = {"viewer": 1, "member": 2, "admin": 3}


def auth_configured() -> bool:
    """True when the server has any auth mechanism configured.

    Self-host operators may run without API_KEY/TENANT_API_KEYS — in that
    open mode the operator is implicitly admin and role checks never block.
    """
    return bool(os.environ.get("API_KEY") or os.environ.get("TENANT_API_KEYS"))


def get_current_role() -> str:
    """Resolve the caller's RBAC role from the request context.

    Priority:
      1. JWT payload claim "role" (set at login/register time).
      2. Authenticated (valid token) without a role claim → "admin"
         (operator login via API key — the deployment owner).
      3. Auth not configured on the server → "admin" (open self-host mode;
         the operator is the owner, never locked out).
      4. Otherwise → "anonymous" (no credentials at all). This is NOT the
         viewer role — viewer is reserved for a logged-in read-only user,
         so @role_required("viewer") blocks anonymous callers (403) and
         genuinely requires login even on read endpoints.
    """
    try:
        payload = g.auth_payload
        if payload and payload.get("role"):
            return str(payload["role"])
        if payload:
            return "admin"  # valid token, operator login
    except (AttributeError, RuntimeError):
        pass
    try:
        from services.auth import verify_token

        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            payload = verify_token(auth_header[7:], expected_type="access")
            if payload and payload.get("role"):
                return str(payload["role"])
            if payload:
                return "admin"
    except Exception:
        pass
    # Localhost is the deployment operator by definition (dev + VPS shell) —
    # keep the documented "localhost always allowed" behavior even when auth
    # is configured, so a tokenless local curl never 403s on write endpoints.
    try:
        remote = request.remote_addr or ""
        if remote in ("127.0.0.1", "::1", "localhost"):
            return "admin"
    except RuntimeError:
        pass
    if not auth_configured():
        return "admin"  # open self-host mode
    # Anonymous remote caller with auth configured → NO role (priority 0,
    # since "anonymous" is not in ROLE_PRIORITY). This is the enforcement
    # point for "login required even on reads": @role_required("viewer")
    # will 403 these callers instead of letting them through as viewer.
    return "anonymous"


def role_required(min_role: str = "member"):
    """Flask decorator: require the caller's role to be at least ``min_role``.

    Roles (priority order): viewer(1) < member(2) < admin(3).
    In open self-host mode (no auth configured) every request passes — the
    operator is the owner by definition and must never be locked out.

    Usage:
        @app.route("/api/write")
        @role_required("member")   # viewer → 403
        def write():
            ...
    """

    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            if not auth_configured():
                return f(*args, **kwargs)
            role = get_current_role()
            if ROLE_PRIORITY.get(role, 0) < ROLE_PRIORITY.get(min_role, 0):
                return (
                    jsonify(
                        {
                            "error": "permission denied",
                            "required_role": min_role,
                            "role": role,
                        }
                    ),
                    403,
                )
            return f(*args, **kwargs)

        return wrapper

    return decorator


# ── Users (self-registration) ────────────────────────────────────────────


def provision_tenant_with_admin(
    username: str, password: str, tenant_name: str = ""
) -> Dict[str, Any]:
    """Create a FRESH tenant (free plan, 5 workers) + its first admin user.

    This is the self-registration path: each signup gets an isolated tenant
    so an anonymous caller can NEVER land in the operator's own "default"
    tenant (which would be a privilege-escalation path — default has the
    generous SELF_HOST_MAX_WORKERS cap and is the deployment owner's).

    Returns {"ok": True, "tenant_id": ..., "username": ..., "role": "admin"}
    or {"error": reason}.
    """
    import uuid as _uuid

    username = (username or "").strip()
    if not username or not password:
        return {"error": "username and password are required"}
    try:
        from werkzeug.security import generate_password_hash

        tenant_id = _uuid.uuid4().hex[:16]
        now = int(time.time())
        conn = _db_conn()
        c = conn.cursor()
        # Global username uniqueness: authenticate_user() resolves logins by
        # username ACROSS all tenants (each signup provisions a fresh tenant),
        # so a duplicate would make the login lookup ambiguous. Enforce it at
        # signup time.
        c.execute("SELECT id FROM users WHERE username=? LIMIT 1", (username,))
        if c.fetchone():
            conn.close()
            return {"error": "username already taken"}
        c.execute(
            "INSERT INTO tenants (id, name, plan, max_workers, created_at) "
            "VALUES (?, ?, 'free', ?, ?)",
            (tenant_id, (tenant_name or username)[:100], DEFAULT_MAX_WORKERS, now),
        )
        c.execute(
            "INSERT INTO users (tenant_id, username, password_hash, role, created_at) "
            "VALUES (?, ?, ?, 'admin', ?)",
            (tenant_id, username, generate_password_hash(password), now),
        )
        conn.commit()
        conn.close()
        log.info("[tenant] provisioned tenant=%s admin=%s", tenant_id[:8], username)
        return {
            "ok": True,
            "tenant_id": tenant_id,
            "username": username,
            "role": "admin",
        }
    except Exception as e:
        log.warning("[tenant] provision_tenant_with_admin(%s) failed: %s", username, e)
        try:
            conn.close()
        except Exception:
            pass
        return {"error": "could not create account"}


def create_user(
    tenant_id: str, username: str, password: str, role: str = "member"
) -> Dict[str, Any]:
    """Create a user row with a hashed password.

    Returns {"ok": True, "id": n} on success or {"error": reason} on
    failure (duplicate username / db error). Passwords are hashed with
    werkzeug (pbkdf2) — never stored in plaintext.
    """
    username = (username or "").strip()
    if not username or not password:
        return {"error": "username and password are required"}
    try:
        from werkzeug.security import generate_password_hash

        conn = _db_conn()
        c = conn.cursor()
        # Global username uniqueness: authenticate_user() resolves logins by
        # username ACROSS all tenants, so a duplicate anywhere would make the
        # login lookup ambiguous. Enforce it for operator-created users too
        # (this subsumes any per-tenant duplicate check).
        c.execute("SELECT id FROM users WHERE username=? LIMIT 1", (username,))
        if c.fetchone():
            conn.close()
            return {"error": "username already exists"}
        c.execute(
            "INSERT INTO users (tenant_id, username, password_hash, role, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                tenant_id,
                username,
                generate_password_hash(password),
                role,
                int(time.time()),
            ),
        )
        row_id = c.lastrowid
        conn.commit()
        conn.close()
        return {"ok": True, "id": row_id}
    except Exception as e:
        log.warning("[tenant] create_user(%s) failed: %s", username, e)
        try:
            conn.close()
        except Exception:
            pass
        return {"error": "could not create user"}


def authenticate_user(
    username: str, password: str, tenant_id: str = ""
) -> Optional[Dict[str, Any]]:
    """Verify username+password against the users table.

    Lookup scope:
      - tenant_id empty or "default" (open / single-tenant mode): GLOBAL by
        username across all tenants — matching the self-registration flow
        where each signup provisions a fresh tenant, so a registered user can
        always log in and the matched tenant becomes the token subject.
      - explicit non-default tenant_id (multi-tenant request context): scoped
        to that tenant.

    Returns {"id", "tenant_id", "username", "role"} on success or None on
    failure / missing row. Constant-time hash check via werkzeug.
    """
    try:
        from werkzeug.security import check_password_hash

        conn = _db_conn()
        c = conn.cursor()
        if tenant_id and tenant_id != "default":
            c.execute(
                "SELECT id, tenant_id, username, password_hash, role FROM users "
                "WHERE tenant_id=? AND username=? LIMIT 1",
                (tenant_id, username),
            )
        else:
            # Global lookup — first-registered wins deterministically so a
            # stray duplicate (e.g. pre-existing data) never resolves
            # arbitrarily.
            c.execute(
                "SELECT id, tenant_id, username, password_hash, role FROM users "
                "WHERE username=? ORDER BY created_at ASC, id ASC LIMIT 1",
                (username,),
            )
        row = c.fetchone()
        conn.close()
        if row is None or not row["password_hash"]:
            return None
        if not check_password_hash(row["password_hash"], password):
            return None
        return {
            "id": row["id"],
            "tenant_id": row["tenant_id"],
            "username": row["username"],
            "role": row["role"] or "member",
        }
    except Exception as e:
        log.warning("[tenant] authenticate_user(%s) failed: %s", username, e)
        return None


def ensure_users_schema() -> None:
    """Idempotent migration: add role + password_hash columns to users.

    Safe to call on every boot — ALTER TABLE only runs when the column is
    missing (legacy DBs created before RBAC).
    """
    try:
        conn = _db_conn()
        c = conn.cursor()
        c.execute("PRAGMA table_info(users)")
        cols = {row[1] for row in c.fetchall()}
        for col, col_def in (
            ("role", "TEXT DEFAULT 'member'"),
            ("password_hash", "TEXT DEFAULT ''"),
        ):
            if col in cols:
                continue
            if not _ALLOWED_COLUMN_NAME.fullmatch(col):
                log.warning("[tenant] refusing DDL for non-allowlisted column %r", col)
                continue
            c.execute(f"ALTER TABLE users ADD COLUMN {col} {col_def}")
            log.info("[tenant] added users.%s column", col)
        conn.commit()
        conn.close()
    except Exception as e:
        log.warning("[tenant] ensure_users_schema failed: %s", e)
