"""CYPHER65 — Authentication API Blueprint."""

import time
import logging
import os

from flask import Blueprint, current_app, jsonify, request, g

from services.auth import (
    DEFAULT_ACCESS_TTL,
    create_token,
    create_refresh_token,
    verify_token,
    revoke_token,
    require_auth,
    resolve_tenant_for_api_key,
)
from services.tenant import log_audit as _log_audit

log = logging.getLogger("cypher65.auth")
security_log = logging.getLogger("cypher65.security")

auth_bp = Blueprint("auth", __name__)


@auth_bp.route("/api/auth/register", methods=["POST"])
def api_auth_register():
    """Register a new user (self-service onboarding).

    Creates a named tenant (free plan) + admin user and returns JWT tokens.
    Password is hashed (pbkdf2) — never stored in plaintext.

    Body (JSON):
        - username (str, required): 3-32 chars
        - password (str, required): min 8 chars

    Returns:
        - access_token, refresh_token, expires_at, tenant_id, role
    """
    data = request.get_json(silent=True) or {}
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""

    errors = []
    if not username or len(username) < 3 or len(username) > 32:
        errors.append("username must be 3-32 characters")
    if not password or len(password) < 8:
        errors.append("password must be at least 8 characters")
    if errors:
        return jsonify({"error": "; ".join(errors)}), 400

    from services.tenant import provision_tenant_with_admin

    # Each signup gets a FRESH tenant (free plan, 5 workers) + admin user —
    # an anonymous caller must never land in the operator's own "default"
    # tenant (privilege escalation: default carries the generous self-host
    # cap and is the deployment owner's).
    created = provision_tenant_with_admin(username, password, tenant_name=username)
    if not created.get("ok"):
        return jsonify({"error": created.get("error", "registration failed")}), 409
    tenant_id = created["tenant_id"]

    # Issue tokens with the role claim so RBAC (@role_required) works — the
    # refresh token carries the role too, so a later /refresh re-issues an
    # access token with the SAME role (no silent escalation to admin).
    access_token = create_token(
        subject=tenant_id, extra_claims={"role": "admin", "username": username}
    )
    refresh_token, expires_at = create_refresh_token(
        subject=tenant_id, extra_claims={"role": "admin", "username": username}
    )

    security_log.info(
        "[auth] registered user=%s tenant=%s from %s",
        username,
        tenant_id,
        request.remote_addr,
    )
    # user_id is the username (known pre-token); the JWT doesn't exist yet so
    # log_audit's auto-resolve can't help here — pass it explicitly.
    _log_audit(
        tenant_id,
        "auth.register",
        user_id=username,
        details={"username": username, "ip": request.remote_addr},
    )

    return (
        jsonify(
            {
                "success": True,
                "access_token": access_token,
                "refresh_token": refresh_token,
                "expires_at": expires_at,
                "token_type": "Bearer",
                "tenant_id": tenant_id,
                "username": username,
                "role": "admin",
            }
        ),
        201,
    )


@auth_bp.route("/api/auth/login", methods=["POST"])
def api_auth_login():
    """Authenticate and receive JWT tokens.

    Two supported credentials:
      - api_key (str): The API key configured via API_KEY / TENANT_API_KEYS env.
      - username + password (str): a registered user (see /api/auth/register).

    Returns:
        - access_token (str): Short-lived JWT (default 1h)
        - refresh_token (str): Longer-lived JWT (default 7d)
        - expires_at (int): Unix timestamp when access_token expires
    """
    data = request.get_json(silent=True) or {}
    provided_key = (data.get("api_key") or "").strip()
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""

    # Username/password path (registered users) — no env API key needed.
    # authenticate_user resolves the tenant GLOBALLY by username (each signup
    # provisions a fresh tenant), so the matched tenant becomes the subject.
    if username and password:
        from services.tenant import authenticate_user, get_tenant_id as _gid

        resolved_tenant = _gid()
        # In open/single-tenant mode resolve_tenant is "default" — the global
        # lookup finds the registered user in their provisioned tenant.
        user = authenticate_user(username, password, tenant_id=resolved_tenant)
        if user is None:
            security_log.warning(
                "[auth] failed user login %s from %s", username, request.remote_addr
            )
            _log_audit(
                resolved_tenant,
                "auth.login_failed",
                user_id=username,
                details={"username": username, "ip": request.remote_addr},
            )
            return jsonify({"error": "invalid username or password"}), 401
        tenant_id = user["tenant_id"]
        access_token = create_token(
            subject=tenant_id,
            extra_claims={"role": user["role"], "username": user["username"]},
        )
        refresh_token, expires_at = create_refresh_token(
            subject=tenant_id,
            extra_claims={"role": user["role"], "username": user["username"]},
        )
        security_log.info(
            "[auth] user login ok=%s role=%s tenant=%s",
            user["username"],
            user["role"],
            tenant_id,
        )
        _log_audit(
            tenant_id,
            "auth.login",
            user_id=user["username"],
            details={"username": user["username"], "ip": request.remote_addr},
        )
        return jsonify(
            {
                "success": True,
                "access_token": access_token,
                "refresh_token": refresh_token,
                "expires_at": expires_at,
                "token_type": "Bearer",
                "tenant_id": tenant_id,
                "username": user["username"],
                "role": user["role"],
            }
        )

    # ── API-key path (env-configured operators) ──
    if not os.environ.get("API_KEY") and not os.environ.get("TENANT_API_KEYS"):
        log.warning(
            "[auth] no API key configured in env — login disabled until API_KEY/TENANT_API_KEYS is set"
        )
        return (
            jsonify(
                {
                    "error": "authentication is not configured on this server",
                    "hint": "Set API_KEY or TENANT_API_KEYS environment variable",
                }
            ),
            503,
        )

    if not provided_key:
        security_log.warning(
            "[auth] login attempt without api_key from %s", request.remote_addr
        )
        return jsonify({"error": "api_key is required"}), 400

    tenant_id = resolve_tenant_for_api_key(provided_key)
    if tenant_id is None:
        security_log.warning("[auth] failed login attempt from %s", request.remote_addr)
        _log_audit("default", "auth.login_failed", details={"ip": request.remote_addr})
        return jsonify({"error": "invalid api_key"}), 401

    # Successful login — subject is the tenant_id so axe_fleet's
    # _get_tenant_id() (which reads payload["sub"]) isolates per tenant.
    # Operator API-key logins get the "admin" role claim by default; the
    # refresh token carries it so a later /refresh keeps the role.
    access_token = create_token(subject=tenant_id, extra_claims={"role": "admin"})
    refresh_token, expires_at = create_refresh_token(
        subject=tenant_id, extra_claims={"role": "admin"}
    )

    security_log.info(
        "[auth] successful login (tenant=%s) from %s", tenant_id, request.remote_addr
    )
    _log_audit(tenant_id, "auth.login", details={"ip": request.remote_addr})

    return jsonify(
        {
            "success": True,
            "access_token": access_token,
            "refresh_token": refresh_token,
            "expires_at": expires_at,
            "token_type": "Bearer",
            "tenant_id": tenant_id,
            "role": "admin",
        }
    )


@auth_bp.route("/api/auth/refresh", methods=["POST"])
def api_auth_refresh():
    """Exchange a valid refresh token for a new access token.

    Body (JSON):
        - refresh_token (str): The refresh token from login.

    Returns:
        - access_token (str): New short-lived JWT
        - expires_at (int): Unix timestamp when access_token expires
    """
    data = request.get_json(silent=True) or {}
    token = (data.get("refresh_token") or "").strip()

    if not token:
        return jsonify({"error": "refresh_token is required"}), 400

    payload = verify_token(token, expected_type="refresh")
    if payload is None:
        return jsonify({"error": "invalid or expired refresh token"}), 401

    # Issue new access token — preserve the original tenant_id subject AND
    # the role claim carried by the refresh token, so a viewer/member does
    # not silently escalate to admin after a refresh. Legacy refresh tokens
    # (issued before RBAC) carry no role claim → default to the LEAST
    # privilege (viewer) rather than the admin the fallback would grant.
    tenant_id = payload.get("sub", "default")
    role = payload.get("role") or "viewer"
    access_token = create_token(subject=tenant_id, extra_claims={"role": role})
    # Align with the configured access-token TTL (same default 3600) so a
    # raised TTL never leaves the client with a stale expires_at.
    ttl = int(
        current_app.config.get("JWT_ACCESS_TOKEN_TTL", DEFAULT_ACCESS_TTL)
        if current_app
        else DEFAULT_ACCESS_TTL
    )
    expires_at = int(time.time()) + ttl
    _log_audit(
        tenant_id,
        "auth.refresh",
        user_id=payload.get("username") or "",
        details={"ip": request.remote_addr},
    )

    return jsonify(
        {
            "success": True,
            "access_token": access_token,
            "expires_at": expires_at,
            "token_type": "Bearer",
            "tenant_id": tenant_id,
            "role": role,
        }
    )


@auth_bp.route("/api/auth/logout", methods=["POST"])
def api_auth_logout():
    """Revoke the provided token (adds to blacklist).

    Body (JSON):
        - access_token (str): The token to revoke.

    Returns:
        - success: True
    """
    data = request.get_json(silent=True) or {}
    token = (data.get("access_token") or data.get("refresh_token") or "").strip()

    if token:
        # Resolve tenant from the token before revoking so the logout audit
        # lands on the right tenant even without an Authorization header.
        payload = verify_token(token, expected_type="access") or verify_token(
            token, expected_type="refresh"
        )
        tid = payload.get("sub", "default") if payload else "default"
        revoke_token(token)
        # Drop the token→tenant rate-limit cache entry NOW (not at exp) so a
        # revoked session stops consuming the tenant's rate budget immediately.
        try:
            from app import evict_token_sub_cache

            evict_token_sub_cache(token)
        except Exception:
            pass  # cache eviction is best-effort; revoke already succeeded
        log.info("[auth] token revoked")
        _log_audit(
            tid,
            "auth.logout",
            user_id=payload.get("username") or "",
            details={"ip": request.remote_addr},
        )
    else:
        return jsonify({"error": "access_token or refresh_token is required"}), 400

    return jsonify({"success": True, "message": "token revoked"})


@auth_bp.route("/api/auth/status", methods=["GET"])
@require_auth
def api_auth_status():
    """Check if the current token is valid. Requires Authorization header.

    Returns the token payload (subject, issue time, expiry).
    """
    return jsonify(
        {
            "success": True,
            "authenticated": True,
            "payload": g.auth_payload,
        }
    )
