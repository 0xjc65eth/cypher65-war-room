"""
CYPHER65 // Settings API routes
================================
Flask Blueprint for /api/settings endpoints.
Extracted from app.py — Phase 2a of P0.4 refactoring.
"""
import time

from flask import Blueprint, jsonify, request

from services.settings import DEFAULT_SETTINGS, load_settings, save_setting, settings_label
from services.tenant import require_tenant, role_required
from services.licensing import is_pro

settings_bp = Blueprint("settings", __name__, url_prefix="/api")


@settings_bp.route("/settings", methods=["GET"])
@require_tenant
def api_settings_get(tenant_id: str = ""):
    s = load_settings()
    out = []
    for k, v in DEFAULT_SETTINGS.items():
        out.append({"key": k, "value": s.get(k, v), "default": v, "label": settings_label(k)})
    return jsonify({"settings": out, "freshness_ts": int(time.time())})


@settings_bp.route("/settings", methods=["POST"])
@require_tenant
@role_required("member")
def api_settings_post(tenant_id: str = ""):
    """POST JSON body: {key: value, key: value, ...}"""
    body = request.get_json(silent=True) or {}
    if not isinstance(body, dict):
        return jsonify({"error": "expected JSON object body"}), 400
    applied = []
    rejected = []
    for k, v in body.items():
        # R1 (PRO tier): webhooks are a PRO feature. Off-by-default — the
        # gate only fires when the operator sets PRO_LICENSE_KEYS and the
        # caller has no valid key; otherwise is_pro() is True in open mode.
        if k == "webhook_url" and not is_pro():
            rejected.append({"key": k, "reason": "PRO feature — requires a license key"})
            continue
        # Allow internal keys (prefixed with '_') and known settings
        if not k.startswith('_') and k not in DEFAULT_SETTINGS:
            rejected.append({"key": k, "reason": "unknown key"})
            continue
        if save_setting(k, v):
            applied.append(k)
        else:
            rejected.append({"key": k, "reason": "db error"})
    return jsonify({"applied": applied, "rejected": rejected})


# ── FASE 2: Wallet history endpoint ──

@settings_bp.route("/wallet/history", methods=["GET"])
@require_tenant
@role_required("viewer")
def get_wallet_history(tenant_id: str = ""):
    """Return list of past wallet addresses, most recent first."""
    try:
        from app import get_db
        conn = get_db()
        rows = conn.execute(
            "SELECT address, worker, connected_at, label FROM wallet_address_history "
            "ORDER BY connected_at DESC LIMIT 20"
        ).fetchall()
        conn.close()
        return jsonify({"success": True, "history": [dict(r) for r in rows]})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
