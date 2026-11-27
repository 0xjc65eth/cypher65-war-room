"""Principal required for dangerous mutations.

Localhost and open self-host mode are not a caller identity. A mutation
principal is a verified access JWT with ``sub``, an API key that resolves to
a tenant, or an authenticated Flask session.
"""

from __future__ import annotations

import re

from flask import g, request, session

_EXACT_POSTS = frozenset(
    {
        "/api/connect-wallet",
        "/api/set-address",
        "/api/settings",
        "/api/rentals/braiins/bid",
        "/api/upgrade/checkout",
        "/api/upgrade/webln/confirm",
        "/api/axe-fleet/power-plugs/save-credentials",
    }
)

_POST_PATTERNS = (
    re.compile(r"^/api/devices/[^/]+/command$"),
    re.compile(r"^/api/devices/[^/]+/command/confirmation$"),
    re.compile(r"^/api/devices/[^/]+/commands/[^/]+/rollback$"),
    re.compile(r"^/api/devices/[^/]+/commands/[^/]+/rollback/confirmation$"),
    re.compile(
        r"^/api/axe-fleet/devices/[^/]+/(restart|identify|pause|resume|config)$"
    ),
    re.compile(r"^/api/axe-fleet/power-plugs/[^/]+/(on|off|toggle)$"),
    re.compile(r"^/api/axe-fleet/miners/[^/]+/power-cycle$"),
)


def is_dangerous_mutation(path: str, method: str) -> bool:
    """True for command, pool, wallet, purchase, and secret POSTs."""
    if (method or "").upper() != "POST":
        return False
    clean = (path or "").split("?", 1)[0]
    if len(clean) > 1:
        clean = clean.rstrip("/")
    if clean in _EXACT_POSTS:
        return True
    return any(pattern.match(clean) for pattern in _POST_PATTERNS)


def has_mutation_principal() -> bool:
    """True only when the request carries a real caller identity."""
    payload = getattr(g, "auth_payload", None)
    if isinstance(payload, dict) and str(payload.get("sub") or "").strip():
        return True
    try:
        auth_header = request.headers.get("Authorization", "")
    except RuntimeError:
        return False
    if auth_header.startswith("Bearer "):
        try:
            from services.auth import verify_token

            verified = verify_token(auth_header[7:], expected_type="access")
        except Exception:
            verified = None
        if isinstance(verified, dict) and str(verified.get("sub") or "").strip():
            return True
    try:
        api_key = request.headers.get("X-API-Key", "")
    except RuntimeError:
        api_key = ""
    if api_key:
        try:
            from services.auth import resolve_tenant_for_api_key

            if resolve_tenant_for_api_key(api_key):
                return True
        except Exception:
            pass
    try:
        if session and session.get("authenticated"):
            tenant_id = session.get("tenant_id", "default")
            if isinstance(tenant_id, str) and tenant_id.strip():
                return True
    except RuntimeError:
        pass
    return False
