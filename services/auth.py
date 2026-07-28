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
import json
import logging
from functools import wraps
from typing import Optional, Dict, Any, Tuple

from flask import request, jsonify, current_app, g

log = logging.getLogger("cypher65.auth")

# ── Configuration ────────────────────────────────────────────────────────
# These can be overridden in app.config:
#   app.config["JWT_SECRET_KEY"]
#   app.config["JWT_ACCESS_TOKEN_TTL"]
#   app.config["JWT_REFRESH_TOKEN_TTL"]

DEFAULT_ACCESS_TTL = 3600          # 1 hour
DEFAULT_REFRESH_TTL = 86400 * 7    # 7 days
DEFAULT_ISSUER = "cypher65"

# ── Token Blacklist (in-memory, lost on restart) ─────────────────────────
# For a production deployment, move this to Redis or SQLite.
_blacklisted_tokens: set = set()


def _get_secret() -> str:
    """Return the JWT secret key from app config or env."""
    if current_app:
        return current_app.config.get("JWT_SECRET_KEY") or os.environ.get("SECRET_KEY", "")
    return os.environ.get("SECRET_KEY", "")


def _encode(payload: dict, secret: str) -> str:
    """Slim JWT encoder: base64url-encoded JSON header.payload.signature.
    Uses HMAC-SHA256 (HS256). No external dependency beyond hashlib + hmac.
    """
    import base64, hmac, hashlib

    header = json.dumps({"alg": "HS256", "typ": "JWT"}).encode()
    payload_bytes = json.dumps(payload).encode()

    def b64url(data: bytes) -> str:
        return base64.urlsafe_b64encode(data).rstrip(b"=").decode()

    header_b64 = b64url(header)
    payload_b64 = b64url(payload_bytes)
    signing_input = f"{header_b64}.{payload_b64}".encode()

    signature = hmac.new(secret.encode(), signing_input, hashlib.sha256).digest()
    sig_b64 = b64url(signature)

    return f"{header_b64}.{payload_b64}.{sig_b64}"


def _decode(token: str, secret: str) -> Optional[dict]:
    """Decode and verify a JWT token. Returns payload dict or None."""
    import base64, hmac, hashlib

    parts = token.split(".")
    if len(parts) != 3:
        return None

    header_b64, payload_b64, sig_b64 = parts

    # Verify signature
    signing_input = f"{header_b64}.{payload_b64}".encode()
    expected_sig = hmac.new(secret.encode(), signing_input, hashlib.sha256).digest()
    actual_sig = base64.urlsafe_b64decode(sig_b64 + "==")

    if not hmac.compare_digest(expected_sig, actual_sig):
        return None

    # Decode payload
    try:
        # Add padding back
        padded = payload_b64 + "=" * (4 - len(payload_b64) % 4)
        payload_bytes = base64.urlsafe_b64decode(padded)
        return json.loads(payload_bytes)
    except Exception:
        return None


def create_token(subject: str = "user", ttl: Optional[int] = None,
                 extra_claims: Optional[dict] = None) -> str:
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
        log.warning("[auth] SECRET_KEY not set — generated tokens won't be verifiable across restarts")
        secret = os.urandom(32).hex()

    ttl = ttl or (current_app.config.get("JWT_ACCESS_TOKEN_TTL", DEFAULT_ACCESS_TTL)
                  if current_app else DEFAULT_ACCESS_TTL)
    now = int(time.time())

    payload = {
        "sub": subject,
        "iat": now,
        "exp": now + ttl,
        "iss": DEFAULT_ISSUER,
        "type": "access",
    }
    if extra_claims:
        payload.update(extra_claims)

    return _encode(payload, secret)


def create_refresh_token(subject: str = "user") -> Tuple[str, int]:
    """Create a JWT refresh token with longer TTL.

    Returns:
        (token_string, expires_at_timestamp)
    """
    ttl = (current_app.config.get("JWT_REFRESH_TOKEN_TTL", DEFAULT_REFRESH_TTL)
           if current_app else DEFAULT_REFRESH_TTL)
    now = int(time.time())
    secret = _get_secret()

    payload = {
        "sub": subject,
        "iat": now,
        "exp": now + ttl,
        "iss": DEFAULT_ISSUER,
        "type": "refresh",
    }
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

    # Check blacklist
    if token in _blacklisted_tokens:
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
    _blacklisted_tokens.add(token)
    # Keep blacklist from growing unbounded (simple cleanup)
    if len(_blacklisted_tokens) > 10000:
        # Keep only the most recent 5000
        _blacklisted_tokens.clear()
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
            return jsonify({"error": "missing or invalid Authorization header",
                            "hint": "Authorization: Bearer <token>"}), 401

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


def authenticate_with_api_key() -> bool:
    """Check if the request has a valid API key (via X-API-Key header).

    Uses the API_KEY env var as the expected key. If API_KEY is not set,
    this check always passes (no API key protection configured).

    Returns:
        True if authenticated or no API key is configured
    """
    expected_key = os.environ.get("API_KEY")
    if not expected_key:
        return True  # No API key configured → open access

    provided_key = request.headers.get("X-API-Key", "")
    return provided_key == expected_key
