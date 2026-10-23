"""Authorization boundary for legacy, process-global operator wallet resources."""

from functools import wraps
from typing import Any, Callable

from flask import g, jsonify, request, session

from services.auth import resolve_tenant_for_api_key, verify_token
from services.tenant import ROLE_PRIORITY, get_current_role


def operator_wallet_required(min_role: str) -> Callable:
    """Fence global wallet data before a handler can read or change it.

    Explicit credentials must all be valid and identify the same tenant.
    A named tenant never gains access through its own admin role. Default
    tenant identity is not a role: mutations require admin, while history
    accepts viewer. Legacy operator JWTs without a role retain their existing
    admin meaning. Anonymous open self-host and configured loopback access
    retain the project's documented operator behavior, but cannot override
    an explicitly invalid credential or an authenticated lower role.

    Example::

        @app.post("/api/set-address")
        @operator_wallet_required("admin")
        def update_operator_wallet():
            ...
    """
    if min_role not in ROLE_PRIORITY:
        raise ValueError("unknown operator wallet role")

    def decorate(view: Callable) -> Callable:
        @wraps(view)
        def wrapped(*args: Any, **kwargs: Any) -> Any:
            tenants: list[str] = []
            payload = None
            api_key = request.headers.get("X-API-Key")
            authorization = request.headers.get("Authorization")
            if authorization is not None:
                if authorization.startswith("Bearer "):
                    payload = verify_token(authorization[7:], expected_type="access")
                subject = payload.get("sub") if isinstance(payload, dict) else None
                if not isinstance(subject, str) or not subject.strip():
                    return jsonify({"error": "authentication required"}), 401
                tenants.append(subject)
                g.auth_payload = payload
            if api_key is not None:
                try:
                    key_tenant = resolve_tenant_for_api_key(api_key)
                except (ValueError, TypeError):
                    key_tenant = None
                if not isinstance(key_tenant, str) or not key_tenant.strip():
                    return jsonify({"error": "authentication required"}), 401
                tenants.append(key_tenant)
            authenticated_session = bool(session.get("authenticated"))
            if authenticated_session:
                session_tenant = session.get("tenant_id", "default")
                if not isinstance(session_tenant, str) or not session_tenant.strip():
                    return jsonify({"error": "authentication required"}), 401
                tenants.append(session_tenant)
            if len(set(tenants)) > 1:
                return jsonify({"error": "authentication required"}), 401
            tenant = tenants[0] if tenants else "default"
            if tenant != "default":
                return (
                    jsonify(
                        {
                            "error": "operator-scoped wallet resource",
                            "code": "OPERATOR_SCOPED_DATA",
                            "detail": "use /api/connect-wallet for tenant wallet sessions",
                        }
                    ),
                    403,
                )
            # Honor explicit lower roles even on loopback and in open mode.
            if payload is not None:
                role = str(payload.get("role", "admin"))
            elif authenticated_session:
                role = str(session.get("role", "admin"))
            elif api_key is not None:
                role = "admin"
            else:
                role = get_current_role()
            if ROLE_PRIORITY.get(role, 0) < ROLE_PRIORITY[min_role]:
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
            return view(*args, **kwargs)

        return wrapped

    return decorate
