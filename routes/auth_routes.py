"""CYPHER65 — Authentication API Blueprint."""
import time
import logging
import os

from flask import Blueprint, jsonify, request, g

from services.auth import (
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


@auth_bp.route("/api/auth/login", methods=["POST"])
def api_auth_login():
    """Authenticate and receive JWT tokens.

    Body (JSON):
        - api_key (str): The API key configured via API_KEY env var.

    Returns:
        - access_token (str): Short-lived JWT (default 1h)
        - refresh_token (str): Longer-lived JWT (default 7d)
        - expires_at (int): Unix timestamp when access_token expires
    """
    data = request.get_json(silent=True) or {}
    provided_key = (data.get("api_key") or "").strip()

    if not os.environ.get("API_KEY") and not os.environ.get("TENANT_API_KEYS"):
        log.warning("[auth] no API key configured in env — login disabled until API_KEY/TENANT_API_KEYS is set")
        return jsonify({"error": "authentication is not configured on this server",
                        "hint": "Set API_KEY or TENANT_API_KEYS environment variable"}), 503

    if not provided_key:
        security_log.warning("[auth] login attempt without api_key from %s", request.remote_addr)
        return jsonify({"error": "api_key is required"}), 400

    tenant_id = resolve_tenant_for_api_key(provided_key)
    if tenant_id is None:
        security_log.warning("[auth] failed login attempt from %s", request.remote_addr)
        _log_audit("default", "auth.login_failed", details={"ip": request.remote_addr})
        return jsonify({"error": "invalid api_key"}), 401

    # Successful login — subject is the tenant_id so axe_fleet's
    # _get_tenant_id() (which reads payload["sub"]) isolates per tenant.
    access_token = create_token(subject=tenant_id)
    refresh_token, expires_at = create_refresh_token(subject=tenant_id)

    security_log.info("[auth] successful login (tenant=%s) from %s", tenant_id, request.remote_addr)
    _log_audit(tenant_id, "auth.login", details={"ip": request.remote_addr})

    return jsonify({
        "success": True,
        "access_token": access_token,
        "refresh_token": refresh_token,
        "expires_at": expires_at,
        "token_type": "Bearer",
        "tenant_id": tenant_id,
    })


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

    # Issue new access token — preserve the original tenant_id subject
    tenant_id = payload.get("sub", "default")
    access_token = create_token(subject=tenant_id)
    expires_at = int(time.time()) + 3600
    _log_audit(tenant_id, "auth.refresh", details={"ip": request.remote_addr})

    return jsonify({
        "success": True,
        "access_token": access_token,
        "expires_at": expires_at,
        "token_type": "Bearer",
        "tenant_id": tenant_id,
    })


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
        payload = verify_token(token, expected_type="access") or verify_token(token, expected_type="refresh")
        tid = payload.get("sub", "default") if payload else "default"
        revoke_token(token)
        log.info("[auth] token revoked")
        _log_audit(tid, "auth.logout", details={"ip": request.remote_addr})
    else:
        return jsonify({"error": "access_token or refresh_token is required"}), 400

    return jsonify({"success": True, "message": "token revoked"})


@auth_bp.route("/api/auth/status", methods=["GET"])
@require_auth
def api_auth_status():
    """Check if the current token is valid. Requires Authorization header.

    Returns the token payload (subject, issue time, expiry).
    """
    return jsonify({
        "success": True,
        "authenticated": True,
        "payload": g.auth_payload,
    })
