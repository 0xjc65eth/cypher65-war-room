"""
HERMES P0.2 — Authentication Module (MANDATORY by default)
==========================================================
API key protection for the Cypher65 War Room.

AUTH IS ENABLED BY DEFAULT. To disable (development only):
    export HERMES_AUTH_DISABLED=1

When auth is active:
    - Set API_KEY=your-secret-key in .env
    - All /api/hermes/* endpoints (except /health) require header: X-API-Key
    - Requests without valid key return 401

This is a temporary measure until full user/auth system is implemented.
"""

import os
from functools import wraps
from flask import request, abort
import logging

log = logging.getLogger("cypher65")


def _is_auth_disabled():
    """Check if authentication is explicitly disabled for development.
    Only returns True if HERMES_AUTH_DISABLED is set to 1 or true (case-insensitive)."""
    val = os.environ.get("HERMES_AUTH_DISABLED", "").strip().lower()
    return val in ("1", "true", "yes")


def require_api_key(f):
    """Decorator that enforces API key protection.

    Auth is MANDATORY unless HERMES_AUTH_DISABLED=1 is explicitly set.
    When API_KEY is not configured but auth is enabled, requests fail with 500
    to indicate server misconfiguration (rather than silently allowing access).
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # Development override — explicitly disabled
        if _is_auth_disabled():
            return f(*args, **kwargs)

        api_key = os.environ.get("API_KEY", "").strip()

        # Auth enabled but no API_KEY configured = server misconfiguration
        if not api_key:
            log.error("[auth] AUTH ENABLED but API_KEY not set — blocking all requests")
            abort(500, description="Server authentication not configured. Set API_KEY in environment.")

        # Check header
        provided_key = request.headers.get("X-API-Key") or request.args.get("api_key")

        if not provided_key:
            log.warning("[auth] Missing API key from %s to %s",
                       request.remote_addr, request.path)
            abort(401, description="Missing API key. Use header X-API-Key.")

        if provided_key != api_key:
            log.warning("[auth] Invalid API key from %s to %s",
                       request.remote_addr, request.path)
            abort(401, description="Invalid API key. Use header X-API-Key.")

        return f(*args, **kwargs)
    return decorated_function


def init_auth(app):
    """Initialize authentication on the Flask app."""
    api_key = os.environ.get("API_KEY", "").strip()

    @app.before_request
    def enforce_api_key():
        """Global before_request hook for API key protection."""
        if _is_auth_disabled():
            return None

        if not api_key:
            return None  # No API_KEY configured — let decorators handle it

        # Skip public endpoints
        public_paths = [
            "/healthz",
            "/api/healthz",
            "/static",
            "/sw.js",
            "/",
        ]

        if any(request.path.startswith(p) for p in public_paths):
            return None

        provided_key = request.headers.get("X-API-Key") or request.args.get("api_key")

        if not provided_key or provided_key != api_key:
            log.warning("[auth] Blocked unauthorized access to %s from %s",
                       request.path, request.remote_addr)
            abort(401, description="Unauthorized. Provide valid X-API-Key header.")

        return None

    auth_status = "DISABLED" if _is_auth_disabled() else ("ACTIVE" if api_key else "MISCONFIGURED")
    log.info("[auth] Hermes auth initialized: %s", auth_status)