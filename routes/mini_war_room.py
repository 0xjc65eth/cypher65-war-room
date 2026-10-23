"""Read-only compact monitor with existing authentication and tenant scopes."""

from collections.abc import Callable
from typing import Any

from flask import Blueprint, Response, g, jsonify, render_template, request

from services.auth import resolve_tenant_for_api_key, verify_token
from services.mini_war_room import build_mini_snapshot
from services.observability import emit_event
from services.tenant import require_tenant, role_required


def create_mini_war_room_blueprint(registry: Callable[[], Any]) -> Blueprint:
    """Create the monitor with an injected, already initialized fleet registry.

    Example::

        app.register_blueprint(create_mini_war_room_blueprint(lambda: fleet))
    """
    blueprint = Blueprint("mini_war_room", __name__)
    paths = frozenset(("/mini-war-room", "/api/mini-war-room"))

    @blueprint.after_app_request
    def private_headers(response: Response) -> Response:
        # App-level hook also covers routing errors such as 405 on these paths.
        if request.path in paths:
            response.headers["Cache-Control"] = "no-store, private, max-age=0"
            response.headers["Pragma"] = "no-cache"
            # Cache API.put rejects Vary: * even in an older installed worker
            # that ignores no-store. Keep explicit identity dimensions too.
            response.vary.update(("Authorization", "Cookie", "X-API-Key", "*"))
        return response

    @blueprint.before_request
    def validate_explicit_credentials() -> Any:
        authorization = request.headers.get("Authorization")
        api_key = request.headers.get("X-API-Key")
        bearer_tenant = None
        if authorization is not None:
            if not authorization.startswith("Bearer "):
                return jsonify({"error": "authentication required"}), 401
            payload = verify_token(authorization[7:], expected_type="access")
            subject = payload.get("sub") if payload else None
            if not isinstance(subject, str) or not subject.strip():
                return jsonify({"error": "authentication required"}), 401
            bearer_tenant = subject
            g.auth_payload = payload
        if api_key is not None:
            key_tenant = resolve_tenant_for_api_key(api_key)
            if not key_tenant or (bearer_tenant and key_tenant != bearer_tenant):
                return jsonify({"error": "authentication required"}), 401
        return None

    @blueprint.route("/mini-war-room", methods=["GET"])
    def monitor_page() -> Any:
        presentation = request.args.get("presentation", "monitor")
        if presentation not in ("monitor", "obs"):
            return jsonify({"error": "invalid presentation"}), 400
        # Public shell has no injected identity, account, or fleet information.
        return render_template("mini_war_room.html", presentation=presentation)

    @blueprint.route("/api/mini-war-room", methods=["GET"])
    @require_tenant
    @role_required("viewer")
    def monitor_snapshot(tenant_id: str = "") -> Any:
        try:
            # Never allow an empty tenant to invoke the registry's admin mode.
            if not isinstance(tenant_id, str) or not tenant_id.strip():
                return jsonify({"error": "authentication required"}), 401
            fleet = registry()
            if fleet is None:
                raise RuntimeError("registry unavailable")
            rows = fleet.list_devices(tenant_id=tenant_id, with_telemetry=True)
            return jsonify(build_mini_snapshot(rows))
        except Exception:
            emit_event("mini_snapshot_unavailable", outcome="unavailable")
            return jsonify({"error": "fleet telemetry unavailable"}), 503

    return blueprint
