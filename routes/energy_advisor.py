"""Private energy evidence and computational-only scenario endpoints."""

from collections.abc import Callable
import json
import sqlite3
from typing import Any

from flask import Blueprint, Response, g, jsonify, render_template, request

from services.auth import resolve_tenant_for_api_key, verify_token
from services.energy_advisor import (
    advisor_snapshot,
    evaluate_energy,
    list_advisor_devices,
)
from services.observability import emit_event
from services.tenant import require_tenant, role_required

MAX_REQUEST_BYTES = 16_384


def _reject_constant(value: str) -> None:
    raise ValueError("invalid_number")


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate_key")
        result[key] = value
    return result


def create_energy_blueprint(get_db: Callable[[], sqlite3.Connection]) -> Blueprint:
    """Construct read-only routes using injected local SQLite connections.

    Example: ``app.register_blueprint(create_energy_blueprint(get_db))``.
    """
    blueprint = Blueprint("energy_advisor", __name__)

    @blueprint.after_app_request
    def private_headers(response: Response) -> Response:
        if request.path == "/energy-advisor" or request.path.startswith(
            "/api/energy-advisor"
        ):
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
            try:
                key_tenant = resolve_tenant_for_api_key(api_key)
            except (ValueError, TypeError):
                key_tenant = None
            if (
                not key_tenant
                or not key_tenant.strip()
                or (bearer_tenant and key_tenant != bearer_tenant)
            ):
                return jsonify({"error": "authentication required"}), 401
        return None

    @blueprint.get("/energy-advisor")
    def page() -> Any:
        return render_template("energy_advisor.html")

    @blueprint.get("/api/energy-advisor/devices")
    @require_tenant
    @role_required("viewer")
    def devices(tenant_id: str = "") -> Any:
        return read(tenant_id, "devices")

    @blueprint.get("/api/energy-advisor/snapshot")
    @require_tenant
    @role_required("viewer")
    def snapshot(tenant_id: str = "") -> Any:
        if (
            set(request.args) != {"device_id"}
            or len(request.args.getlist("device_id")) != 1
        ):
            return jsonify({"error": "invalid device"}), 400
        return read(tenant_id, "snapshot", request.args["device_id"])

    @blueprint.post("/api/energy-advisor/evaluate")
    @require_tenant
    @role_required("viewer")
    def evaluate(tenant_id: str = "") -> Any:
        if request.mimetype != "application/json":
            return jsonify({"error": "JSON required"}), 415
        if (
            request.content_length is not None
            and request.content_length > MAX_REQUEST_BYTES
        ):
            return jsonify({"error": "request too large"}), 413
        raw = request.stream.read(MAX_REQUEST_BYTES + 1)
        if len(raw) > MAX_REQUEST_BYTES:
            return jsonify({"error": "request too large"}), 413
        try:
            value = json.loads(
                raw, parse_constant=_reject_constant, object_pairs_hook=_unique_object
            )
        except (ValueError, UnicodeError, RecursionError):
            return jsonify({"error": "invalid JSON"}), 400
        return read(tenant_id, "evaluate", value)

    def read(tenant_id: str, operation: str, value: Any = None) -> Any:
        if not isinstance(tenant_id, str) or not tenant_id.strip():
            return jsonify({"error": "authentication required"}), 401
        conn = None
        try:
            conn = get_db()
            if operation == "devices":
                result = list_advisor_devices(conn, tenant_id)
            elif operation == "snapshot":
                result = advisor_snapshot(conn, tenant_id, value)
            else:
                result = evaluate_energy(conn, tenant_id, value)
            if result is None:
                return jsonify({"error": "device not found"}), 404
            return jsonify(result)
        except ValueError:
            return jsonify({"error": "invalid scenario input"}), 400
        except Exception:
            emit_event("energy_advisor_unavailable", outcome="unavailable")
            return jsonify({"error": "local energy evidence unavailable"}), 503
        finally:
            if conn is not None:
                conn.close()

    return blueprint
