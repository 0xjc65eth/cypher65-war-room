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
)

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

    expected_key = os.environ.get("API_KEY")
    if not expected_key:
        log.warning("[auth] API_KEY not set in env — login disabled until API_KEY is configured")
        return jsonify({"error": "authentication is not configured on this server",
                        "hint": "Set API_KEY environment variable"}), 503

    if not provided_key:
        security_log.warning("[auth] login attempt without api_key from %s", request.remote_addr)
        return jsonify({"error": "api_key is required"}), 400

    if provided_key != expected_key:
        security_log.warning("[auth] failed login attempt from %s", request.remote_addr)
        return jsonify({"error": "invalid api_key"}), 401

    # Successful login
    access_token = create_token(subject="user")
    refresh_token, expires_at = create_refresh_token(subject="user")

    security_log.info("[auth] successful login from %s", request.remote_addr)

    return jsonify({
        "success": True,
        "access_token": access_token,
        "refresh_token": refresh_token,
        "expires_at": expires_at,
        "token_type": "Bearer",
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

    # Issue new access token
    access_token = create_token(subject=payload.get("sub", "user"))
    expires_at = int(time.time()) + 3600

    return jsonify({
        "success": True,
        "access_token": access_token,
        "expires_at": expires_at,
        "token_type": "Bearer",
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
        revoke_token(token)
        log.info("[auth] token revoked")
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
