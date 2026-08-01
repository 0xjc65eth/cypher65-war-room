"""
CYPHER65 // Alerts & Automation Routes
=====================================
Exposes REST endpoints for alert management and automation rules.
"""
import json
import time
from typing import Any, Dict

from flask import Blueprint, jsonify, request

from services.tenant import require_tenant, log_audit as _log_audit

alerts_bp = Blueprint("alerts", __name__, url_prefix="/api")

VALID_OPS = {">", "<", ">=", "<=", "==", "!="}


# `_get_db` is injected from app.py when the blueprint is registered to
# avoid a runtime circular import.
_get_db = None


def _set_get_db(fn):
    global _get_db
    _get_db = fn


def get_db():
    if _get_db is None:
        raise RuntimeError("get_db factory not configured; call _set_get_db() first")
    return _get_db()


def _row_to_alert(row) -> Dict[str, Any]:
    return {
        "id": row["id"],
        "ts": row["ts"],
        "severity": row["severity"],
        "category": row["category"],
        "message": row["message"],
        "device_id": row["device_id"],
        "alert_type": row["alert_type"],
        "is_acknowledged": bool(row["is_acknowledged"]),
        "is_active": bool(row["active"]),
        "meta": json.loads(row["meta"] or "{}"),
    }


@alerts_bp.route("/alerts", methods=["GET"])
@require_tenant
def api_alerts(tenant_id: str = ""):
    """Return active alerts for the current tenant, optionally filtered by severity."""
    severity = request.args.get("severity")
    limit = int(request.args.get("limit", 80))
    conn = get_db()
    c = conn.cursor()
    if severity:
        c.execute(
            "SELECT * FROM alerts WHERE active=1 AND severity=? AND tenant_id=? ORDER BY ts DESC LIMIT ?",
            (severity, tenant_id or "default", limit),
        )
    else:
        c.execute(
            "SELECT * FROM alerts WHERE active=1 AND tenant_id=? ORDER BY ts DESC LIMIT ?",
            (tenant_id or "default", limit),
        )
    rows = [_row_to_alert(r) for r in c.fetchall()]
    conn.close()
    return jsonify({"alerts": rows})


@alerts_bp.route("/alerts/acknowledge", methods=["POST"])
@require_tenant
def api_acknowledge_alert(tenant_id: str = ""):
    """Acknowledge one or more alerts by ID (scoped to tenant)."""
    data = request.get_json(silent=True) or {}
    alert_ids = data.get("ids") or [data.get("id")]
    if not alert_ids or alert_ids == [None]:
        return jsonify({"success": False, "error": "id or ids required"}), 400

    conn = get_db()
    c = conn.cursor()
    placeholders = ",".join(["?"] * len(alert_ids))
    tid = tenant_id or "default"
    c.execute(
        f"UPDATE alerts SET is_acknowledged=1, active=0 WHERE id IN ({placeholders}) AND tenant_id=?",
        tuple(alert_ids) + (tid,),
    )
    conn.commit()
    conn.close()
    _log_audit(tid, "alert.acknowledge", details={"ids": alert_ids})
    return jsonify({"success": True, "acknowledged_ids": alert_ids})


@alerts_bp.route("/alerts/history", methods=["GET"])
@require_tenant
def api_alert_history(tenant_id: str = ""):
    """Return the tenant's alert history/audit log."""
    limit = int(request.args.get("limit", 200))
    device_id = request.args.get("device_id")
    conn = get_db()
    c = conn.cursor()
    if device_id:
        c.execute(
            "SELECT * FROM alert_history WHERE device_id=? AND tenant_id=? ORDER BY ts DESC LIMIT ?",
            (device_id, tenant_id or "default", limit),
        )
    else:
        c.execute(
            "SELECT * FROM alert_history WHERE tenant_id=? ORDER BY ts DESC LIMIT ?",
            (tenant_id or "default", limit),
        )
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return jsonify({"history": rows})


@alerts_bp.route("/automation-rules", methods=["GET", "POST"])
@require_tenant
def api_automation_rules(tenant_id: str = ""):
    tid = tenant_id or "default"
    conn = get_db()
    c = conn.cursor()

    if request.method == "GET":
        c.execute(
            "SELECT * FROM automation_rules WHERE tenant_id=? ORDER BY id DESC",
            (tid,),
        )
        rows = []
        for r in c.fetchall():
            row = dict(r)
            try:
                row["action_parameters"] = json.loads(row.get("action_parameters") or "{}")
            except Exception:
                row["action_parameters"] = {}
            rows.append(row)
        conn.close()
        return jsonify({"rules": rows})

    data = request.get_json(silent=True) or {}
    required = ["name", "target_device_id", "condition_metric",
                "condition_operator", "condition_value", "action_command"]
    missing = [f for f in required if f not in data]
    if missing:
        return jsonify({"success": False, "error": f"missing fields: {missing}"}), 400

    if data["condition_operator"] not in VALID_OPS:
        return jsonify({"success": False, "error": f"invalid operator: {data['condition_operator']}"}), 400
    try:
        condition_value = float(data["condition_value"])
    except (TypeError, ValueError):
        return jsonify({"success": False, "error": "condition_value must be numeric"}), 400
    try:
        min_interval = int(data.get("min_interval_seconds", 60))
        if min_interval < 0:
            return jsonify({"success": False, "error": "min_interval_seconds must be >= 0"}), 400
    except (TypeError, ValueError):
        return jsonify({"success": False, "error": "min_interval_seconds must be an integer"}), 400

    c.execute(
        """INSERT INTO automation_rules
        (name, target_device_id, condition_metric, condition_operator,
         condition_value, action_command, action_parameters, is_enabled, min_interval_seconds, tenant_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            data["name"],
            data["target_device_id"],
            data["condition_metric"],
            data["condition_operator"],
            float(data["condition_value"]),
            data["action_command"],
            json.dumps(data.get("action_parameters", {})),
            int(data.get("is_enabled", True)),
            min_interval,
            tid,
        ),
    )
    conn.commit()
    rule_id = c.lastrowid
    conn.close()
    _log_audit(tid, "automation.rule.create", target=str(rule_id),
               details={"name": data["name"], "action_command": data["action_command"]})
    return jsonify({"success": True, "id": rule_id})


@alerts_bp.route("/automation-rules/<int:rule_id>", methods=["PUT", "DELETE"])
@require_tenant
def api_automation_rule(rule_id: int, tenant_id: str = ""):
    tid = tenant_id or "default"
    conn = get_db()
    c = conn.cursor()

    if request.method == "DELETE":
        c.execute("DELETE FROM automation_rules WHERE id=? AND tenant_id=?", (rule_id, tid))
        conn.commit()
        conn.close()
        _log_audit(tid, "automation.rule.delete", target=str(rule_id))
        return jsonify({"success": True})

    data = request.get_json(silent=True) or {}

    # Validate operator/value before touching the database.
    if "condition_operator" in data and data["condition_operator"] not in VALID_OPS:
        return jsonify({"success": False, "error": f"invalid operator: {data['condition_operator']}"}), 400
    if "condition_value" in data:
        try:
            data["condition_value"] = float(data["condition_value"])
        except (TypeError, ValueError):
            return jsonify({"success": False, "error": "condition_value must be numeric"}), 400
    if "min_interval_seconds" in data:
        try:
            if int(data["min_interval_seconds"]) < 0:
                return jsonify({"success": False, "error": "min_interval_seconds must be >= 0"}), 400
        except (TypeError, ValueError):
            return jsonify({"success": False, "error": "min_interval_seconds must be an integer"}), 400

    fields = []
    values = []
    for field in ["name", "target_device_id", "condition_metric",
                  "condition_operator", "condition_value", "action_command",
                  "action_parameters", "is_enabled", "min_interval_seconds"]:
        if field in data:
            if field == "action_parameters":
                fields.append(f"{field}=?")
                values.append(json.dumps(data[field]))
            elif field in ("is_enabled", "min_interval_seconds"):
                fields.append(f"{field}=?")
                values.append(int(data[field]))
            elif field == "condition_value":
                fields.append(f"{field}=?")
                values.append(data[field])
            else:
                fields.append(f"{field}=?")
                values.append(data[field])
    if not fields:
        return jsonify({"success": False, "error": "no fields to update"}), 400

    values.append(rule_id)
    values.append(tid)
    c.execute(f"UPDATE automation_rules SET {','.join(fields)} WHERE id=? AND tenant_id=?", tuple(values))
    conn.commit()
    conn.close()
    _log_audit(tid, "automation.rule.update", target=str(rule_id), details={"fields": fields})
    return jsonify({"success": True})
