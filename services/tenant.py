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
from functools import wraps

from flask import g, request, session


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
