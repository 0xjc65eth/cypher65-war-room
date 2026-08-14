"""
CYPHER65 — JWT Authentication Service
=======================================
Provides JWT token creation, verification, and Flask decorator for
protecting sensitive endpoints.

Usage:
    @app.route("/api/sensitive")
    @require_auth
    def sensitive_endpoint():
        ...

    # Token payload contains: { "sub": "user", "iat": ..., "exp": ... }
"""

import os
import time
import sqlite3
import logging
from collections import OrderedDict
from functools import wraps
from typing import Optional, Dict, Any, Tuple

import jwt as _jwt
from flask import request, jsonify, current_app, g

log = logging.getLogger("cypher65.auth")

# ── Configuration ────────────────────────────────────────────────────────
# These can be overridden in app.config:
#   app.config["JWT_SECRET_KEY"]
#   app.config["JWT_ACCESS_TOKEN_TTL"]
#   app.config["JWT_REFRESH_TOKEN_TTL"]

DEFAULT_ACCESS_TTL = 3600  # 1 hour
DEFAULT_REFRESH_TTL = 86400 * 7  # 7 days
DEFAULT_ISSUER = "cypher65"
DEFAULT_AUDIENCE = "cypher65"

# ── Token Blacklist (in-memory + optional SQLite persistence) ────────────
# FIFO-pruned OrderedDict: token -> revoke timestamp. When the cap is hit,
# the OLDEST revocations are dropped — never a wholesale clear() (a clear()
# would silently re-validate every previously-revoked token → replay).
#
# Single-process deploys (python app.py) are fully covered by memory alone.
# For MULTI-PROCESS topologies (gunicorn workers + python -m services.workers)
# each process has its own dict, so a logout in process A wouldn't be seen by
# process B. Setting REVOKED_TOKENS_DB=1 persists revocations to the SQLite
# DB (revoked_tokens table) — then every process honors the shared blacklist.
# Persistence is strictly best-effort: a DB error degrades to memory-only and
# NEVER breaks authentication.
_blacklisted_tokens: "OrderedDict[str, float]" = OrderedDict()
_BLACKLIST_MAX = 10000
_BLACKLIST_KEEP = 5000
# Guards the revoked_tokens DDL — created ONCE per process per DB path
# (avoids running CREATE TABLE IF NOT EXISTS on every verify/revoke in
# multi-worker mode; the path check also resets correctly if DB_PATH is
# redirected at runtime, e.g. per-test scratch DBs).
_revoked_table_ready: Optional[str] = None


def _revoked_db_path() -> Optional[str]:
    """Return the SQLite path for revoked-token persistence, or None when
    disabled (REVOKED_TOKENS_DB != 1). Reads DB_PATH at call time so test
    redirects (conftest sets os.environ["DB_PATH"]) are always honored."""
    if os.environ.get("REVOKED_TOKENS_DB") != "1":
        return None
    try:
        from config import DB_PATH as _cfg_db_path
    except Exception:
        _cfg_db_path = "data/war_room.sqlite"
    return os.environ.get("DB_PATH") or _cfg_db_path


def _ensure_revoked_table(conn, path: str) -> None:
    """Create the revoked_tokens table once per process AND per DB path."""
    global _revoked_table_ready
    if _revoked_table_ready == path:
        return
    conn.execute(
        "CREATE TABLE IF NOT EXISTS revoked_tokens ("
        " token TEXT PRIMARY KEY, revoked_at REAL NOT NULL)"
    )
    conn.commit()
    _revoked_table_ready = path


def _persist_revocation(token: str) -> None:
    """Best-effort write of a revocation to SQLite (shared across processes).
    Also opportunistically prunes rows older than refresh TTL + 1h margin.
    Never raises — persistence is an enhancement, auth must not depend on it.

    NOTE: sqlite3.Connection.__exit__ commits but does NOT close the
    connection — we close explicitly (codebase get_db() convention)."""
    path = _revoked_db_path()
    if not path:
        return
    conn = None
    try:
        conn = sqlite3.connect(path, timeout=3)
        conn.execute("PRAGMA busy_timeout=3000")
        _ensure_revoked_table(conn, path)
        conn.execute(
            "INSERT OR IGNORE INTO revoked_tokens(token, revoked_at) VALUES (?, ?)",
            (token, time.time()),
        )
        conn.execute(
            "DELETE FROM revoked_tokens WHERE revoked_at < ?",
            (time.time() - (DEFAULT_REFRESH_TTL + 3600),),
        )
        conn.commit()
    except Exception as e:
        log.warning("[auth] revoked-token persist skipped (best-effort): %s", e)
    finally:
        if conn is not None:
            conn.close()


def _revocation_persisted(token: str) -> bool:
    """Best-effort check against the shared SQLite blacklist. Never raises."""
    path = _revoked_db_path()
    if not path:
        return False
    conn = None
    try:
        conn = sqlite3.connect(path, timeout=3)
        conn.execute("PRAGMA busy_timeout=3000")
        _ensure_revoked_table(conn, path)
        row = conn.execute(
            "SELECT 1 FROM revoked_tokens WHERE token = ?", (token,)
        ).fetchone()
        return row is not None
    except Exception as e:
        log.warning("[auth] revoked-token lookup failed (best-effort): %s", e)
        return False
    finally:
        if conn is not None:
            conn.close()


def _get_secret() -> str:
    """Return the JWT secret key from app config or env."""
    if current_app:
        return current_app.config.get("JWT_SECRET_KEY") or os.environ.get(
            "SECRET_KEY", ""
        )
    return os.environ.get("SECRET_KEY", "")


def _encode(payload: dict, secret: str) -> str:
    """Encode a JWT using PyJWT (HS256).

    Migrated from the handcrafted hmac/base64 implementation (audit C4) so
    signing/verification is delegated to a battle-tested library instead of
    bespoke crypto.
    """
    return _jwt.encode(payload, secret, algorithm="HS256")


def _decode(token: str, secret: str) -> Optional[dict]:
    """Decode and verify a JWT token. Returns payload dict or None.

    PyJWT validates the signature AND the `alg` header (rejects alg-confusion
    like 'none'), and enforces `exp` automatically. Any invalid/expired/
    tampered token → None (never raises).
    """
    try:
        return _jwt.decode(
            token, secret, algorithms=["HS256"], audience=DEFAULT_AUDIENCE
        )
    except _jwt.InvalidTokenError:
        return None


def create_token(
    subject: str = "user",
    ttl: Optional[int] = None,
    extra_claims: Optional[dict] = None,
) -> str:
    """Create a JWT access token.

    Args:
        subject: Token subject (default: "user")
        ttl: Time-to-live in seconds (default: JWT_ACCESS_TOKEN_TTL or 3600)
        extra_claims: Additional claims to include in the payload

    Returns:
        Encoded JWT string
    """
    secret = _get_secret()
    if not secret:
        # Audit C2: never mint tokens with a missing/volatile secret — they
        # would be silently unverifiable (every login issues a token, every
        # verify fails, auth appears broken with no error). Fail loud instead.
        log.error(
            "[auth] SECRET_KEY is not configured — refusing to issue JWTs. "
            "Set SECRET_KEY in the environment (or app.config JWT_SECRET_KEY)."
        )
        raise RuntimeError("SECRET_KEY is not configured; refusing to issue JWTs")

    ttl = ttl or (
        current_app.config.get("JWT_ACCESS_TOKEN_TTL", DEFAULT_ACCESS_TTL)
        if current_app
        else DEFAULT_ACCESS_TTL
    )
    now = int(time.time())

    payload = {
        "sub": subject,
        "iat": now,
        "nbf": now - 5,  # 5s skew tolerance
        "exp": now + ttl,
        "iss": DEFAULT_ISSUER,
        "aud": DEFAULT_AUDIENCE,
        "type": "access",
    }
    if extra_claims:
        payload.update(extra_claims)

    return _encode(payload, secret)


def create_refresh_token(
    subject: str = "user", extra_claims: Optional[dict] = None
) -> Tuple[str, int]:
    """Create a JWT refresh token with longer TTL.

    Args:
        subject: Token subject (tenant_id)
        extra_claims: Additional claims to include (e.g. role, username) so
            the refresh flow can re-issue access tokens with the SAME role —
            otherwise a viewer/member would silently escalate to admin after
            a token refresh (get_current_role treats a valid token without a
            role claim as the operator/admin).

    Returns:
        (token_string, expires_at_timestamp)
    """
    ttl = (
        current_app.config.get("JWT_REFRESH_TOKEN_TTL", DEFAULT_REFRESH_TTL)
        if current_app
        else DEFAULT_REFRESH_TTL
    )
    now = int(time.time())
    secret = _get_secret()
    if not secret:
        # Audit C2: same fail-loud policy as create_token — a refresh token
        # signed with a missing secret would be silently unverifiable.
        log.error(
            "[auth] SECRET_KEY is not configured — refusing to issue refresh tokens."
        )
        raise RuntimeError("SECRET_KEY is not configured; refusing to issue JWTs")

    payload = {
        "sub": subject,
        "iat": now,
        "nbf": now - 5,  # 5s skew tolerance
        "exp": now + ttl,
        "iss": DEFAULT_ISSUER,
        "aud": DEFAULT_AUDIENCE,
        "type": "refresh",
    }
    if extra_claims:
        payload.update(extra_claims)
    return _encode(payload, secret), now + ttl


def verify_token(token: str, expected_type: str = "access") -> Optional[dict]:
    """Verify a JWT token and return its payload if valid.

    Args:
        token: The JWT string to verify
        expected_type: Expected token type ("access" or "refresh")

    Returns:
        Payload dict if valid, None otherwise
    """
    if not token:
        return None

    # Check in-memory blacklist
    if token in _blacklisted_tokens:
        return None

    # Multi-process: honor revocations persisted to SQLite by another
    # process (only when REVOKED_TOKENS_DB=1). Cache the hit locally so a
    # repeated token skips the DB round-trip.
    if _revocation_persisted(token):
        if len(_blacklisted_tokens) < _BLACKLIST_MAX:
            _blacklisted_tokens[token] = time.time()
        return None

    secret = _get_secret()
    if not secret:
        return None

    payload = _decode(token, secret)
    if payload is None:
        return None

    # Check expiry
    now = int(time.time())
    if payload.get("exp", 0) < now:
        return None

    # Check type
    if payload.get("type") != expected_type:
        return None

    return payload


def revoke_token(token: str) -> bool:
    """Add a token to the blacklist so it can no longer be used.

    Args:
        token: The JWT string to revoke

    Returns:
        True if added to blacklist
    """
    _blacklisted_tokens[token] = time.time()
    # FIFO prune: keep only the most recent _BLACKLIST_KEEP revocations.
    # (OrderedDict preserves first-insertion order — assigning to an
    # existing key does NOT move it to the end, which is fine: the token
    # stays revoked while present, and old entries are the first pruned.)
    if len(_blacklisted_tokens) > _BLACKLIST_MAX:
        while len(_blacklisted_tokens) > _BLACKLIST_KEEP:
            _blacklisted_tokens.popitem(last=False)
    # Persist to the shared SQLite blacklist when enabled (multi-process).
    _persist_revocation(token)
    return True


def require_auth(f):
    """Flask decorator: require a valid JWT access token on the endpoint.

    The token must be sent as:
        Authorization: Bearer <token>

    On success, the decoded payload is available as `g.auth_payload`.
    """

    @wraps(f)
    def decorated(*args, **kwargs):
        auth_header = request.headers.get("Authorization", "")

        if not auth_header.startswith("Bearer "):
            return (
                jsonify(
                    {
                        "error": "missing or invalid Authorization header",
                        "hint": "Authorization: Bearer <token>",
                    }
                ),
                401,
            )

        token = auth_header[7:]  # Strip "Bearer "
        payload = verify_token(token, expected_type="access")

        if payload is None:
            return jsonify({"error": "invalid or expired token"}), 401

        g.auth_payload = payload
        return f(*args, **kwargs)

    return decorated


def optional_auth(f):
    """Flask decorator: if a valid JWT is present, decode it; if not, proceed.

    The decoded payload (or None) is available as `g.auth_payload`.
    """

    @wraps(f)
    def decorated(*args, **kwargs):
        g.auth_payload = None
        auth_header = request.headers.get("Authorization", "")

        if auth_header.startswith("Bearer "):
            token = auth_header[7:]
            payload = verify_token(token, expected_type="access")
            if payload is not None:
                g.auth_payload = payload

        return f(*args, **kwargs)

    return decorated


def resolve_tenant_for_api_key(api_key: str) -> Optional[str]:
    """Map an API key to a tenant_id.

    Uses the TENANT_API_KEYS env var (JSON dict tenant_id → api_key) when
    set; otherwise falls back to the legacy single API_KEY env var, which
    maps to tenant "default".

    Returns:
        tenant_id (str) if the key is valid, None otherwise.
    """
    if not api_key:
        return None

    import json
    import hmac as _hmac

    raw = os.environ.get("TENANT_API_KEYS", "")
    if raw.strip():
        try:
            mapping = json.loads(raw)
            if isinstance(mapping, dict):
                for tid, key in mapping.items():
                    if (
                        isinstance(key, str)
                        and key
                        and _hmac.compare_digest(api_key, key)
                    ):
                        return str(tid)
        except (ValueError, TypeError):
            log.warning(
                "[auth] TENANT_API_KEYS is not valid JSON — falling back to API_KEY"
            )

    expected_key = os.environ.get("API_KEY")
    if expected_key and _hmac.compare_digest(api_key, expected_key):
        return "default"

    return None


def authenticate_with_api_key() -> bool:
    """Check if the request has a valid API key (via X-API-Key header).

    Uses TENANT_API_KEYS (multi-tenant) or the legacy API_KEY env var.
    If neither is configured, this check always passes.

    Returns:
        True if authenticated or no API key is configured
    """
    if not os.environ.get("API_KEY") and not os.environ.get("TENANT_API_KEYS"):
        return True  # No API key configured → open access

    provided_key = request.headers.get("X-API-Key", "")
    return resolve_tenant_for_api_key(provided_key) is not None
