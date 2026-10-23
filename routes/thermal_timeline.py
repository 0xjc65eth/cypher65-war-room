"""Private, read-only thermal history endpoints with explicit credential fences."""

from collections.abc import Callable
import sqlite3
from typing import Any

from flask import Blueprint, Response, g, jsonify, render_template, request

from services.auth import resolve_tenant_for_api_key, verify_token
from services.observability import emit_event
from services.tenant import require_tenant, role_required
from services.thermal_timeline import build_thermal_timeline, list_timeline_devices


def create_thermal_blueprint(get_db: Callable[[], sqlite3.Connection]) -> Blueprint:
    """Build a private local-history reader with injected database connections.

    Example: ``app.register_blueprint(create_thermal_blueprint(get_db))``.
    """
    blueprint = Blueprint("thermal_timeline", __name__)
    paths = frozenset(
        ("/thermal-timeline", "/api/thermal-timeline", "/api/thermal-timeline/devices")
    )

    @blueprint.after_app_request
    def private_headers(response: Response) -> Response:
        if request.path in paths:
            response.headers["Cache-Control"] = "no-store, private, max-age=0"
            response.headers["Pragma"] = "no-cache"
            response.vary.update(("Authorization", "Cookie", "X-API-Key", "*"))
        return response

    @blueprint.before_request
    def validate_credentials() -> Any:
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
            if (
                not key_tenant
                or not key_tenant.strip()
                or (bearer_tenant and key_tenant != bearer_tenant)
            ):
                return jsonify({"error": "authentication required"}), 401
        return None

    @blueprint.get("/thermal-timeline")
    def page() -> Any:
        return render_template("thermal_timeline.html")

    @blueprint.get("/api/thermal-timeline/devices")
    @require_tenant
    @role_required("viewer")
    def devices(tenant_id: str = "") -> Any:
        return read_history(tenant_id, picker=True)

    @blueprint.get("/api/thermal-timeline")
    @require_tenant
    @role_required("viewer")
    def history(tenant_id: str = "") -> Any:
        return read_history(tenant_id, picker=False)

    def read_history(tenant_id: str, *, picker: bool) -> Any:
        if not isinstance(tenant_id, str) or not tenant_id.strip():
            return jsonify({"error": "authentication required"}), 401
        device_id = request.args.get("device_id", "")
        raw_hours = request.args.get("hours", "6")
        if not picker and (
            not device_id or len(device_id) > 128 or raw_hours not in ("1", "6", "24")
        ):
            return jsonify({"error": "invalid device or hours"}), 400
        conn = None
        try:
            conn = get_db()
            if picker:
                result = list_timeline_devices(conn, tenant_id)
            else:
                result = build_thermal_timeline(
                    conn, tenant_id, device_id, int(raw_hours)
                )
            if result is None:
                return jsonify({"error": "device not found"}), 404
            return jsonify(result)
        except Exception:
            emit_event("thermal_timeline_unavailable", outcome="unavailable")
            return jsonify({"error": "local history unavailable"}), 503
        finally:
            if conn is not None:
                conn.close()

    return blueprint
